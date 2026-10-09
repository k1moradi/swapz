#!/usr/bin/env python3
"""Rootless, synthetic-only regression for the offline V2.2 drain evaluator.

Every observation is fabricated for test purposes. No devices, fio, swap,
process workers, benchmarks or kernel performance data are accessed.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ANALYZER_PATH = HERE / "v22-drain-plateau-analyze.py"
spec = importlib.util.spec_from_file_location("swapz_offline_drain_plateau", ANALYZER_PATH)
assert spec is not None and spec.loader is not None
analyzer = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = analyzer
spec.loader.exec_module(analyzer)

RATES = {4: 5, 8: 9, 16: 12, 32: 16, 64: 19.8,
         128: 20, 256: 20.1, 512: 20, 1024: 20}
P99 = {4: 2.0, 8: 1.8, 16: 1.6, 32: 1.3, 64: 1.1,
       128: 1.0, 256: 1.2, 512: 1.0, 1024: 1.0}


def observation(batch=64, replicate=0, *, rate=20.0, p99=1.0,
                strategy="staged", backend="synthetic-backend",
                evidence="synthetic", profile="standard", source_revision="deadbeef"):
    sectors = round(rate * 2048)
    return {
        "schema": analyzer.SCHEMA,
        "evidence": evidence,
        "backend": backend,
        "profile": profile,
        "strategy": strategy,
        "batch_kib": batch,
        "run_id": f"{backend}-{profile}-{strategy}-{batch}-r{replicate}",
        "source_revision": source_revision,
        "clock": "monotonic",
        "duration_ns": 1_000_000_000,
        "lower_write_sectors_before": 5000,
        "lower_write_sectors_after": 5000 + sectors,
        "lower_write_ios_before": 100,
        "lower_write_ios_after": 100 + 50,
        "logical_write_bytes": 64 * 1024 * 1024,
        "read_count": 12000,
        "read_p99_ns": round(p99 * 1_000_000),
        "integrity_ok": True,
        "quiescence_ok": True,
        "flush_ok": True,
        "all_reaped": True,
        "source_kind": "lower-device-counters",
    }


def sweep(*, evidence="synthetic", backend="synthetic-backend",
          strategy="staged", profile="standard"):
    return [
        observation(batch, rep, rate=RATES[batch] * (0.99 + rep * 0.01),
                    p99=P99[batch], strategy=strategy, backend=backend,
                    evidence=evidence, profile=profile)
        for batch in analyzer.BATCHES for rep in range(3)
    ]


def as_v2(row, *, histogram=None):
    """Synthetic exact-value latency distribution, not actual read traces."""
    row = dict(row)
    row["schema"] = analyzer.SCHEMA_V2
    row["run_id"] += "-v2"
    row["read_latency_counts"] = (
        histogram if histogram is not None
        else [[row["read_p99_ns"], row["read_count"]]]
    )
    return row


def sweep_v2(**kwargs):
    return [as_v2(row) for row in sweep(**kwargs)]


class OfflineDrainPlateauTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="swapz-plateau-rootless-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "synthetic.jsonl"

    def write(self, rows):
        self.path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                             encoding="utf-8")
        return self.path

    def analyze(self, rows):
        return analyzer.analyze(analyzer.load_rows(self.write(rows)))

    def test_synthetic_candidate_is_never_an_empirical_winner(self):
        report = self.analyze(sweep())
        self.assertEqual(report["observation_count"], 27)
        item = report["series"][0]
        self.assertEqual(item["candidate_batch_kib"], 64)
        self.assertIsNone(item["provisional_selection_kib"])
        self.assertIn("SYNTHETIC ONLY", item["qualification"])
        self.assertEqual(len(item["points"]), 9)
        self.assertEqual(item["points"][-1]["batch_kib"], 1024)
        self.assertAlmostEqual(item["points"][-1]["lower_drained_mib_s_median"], 20.0, places=3)

    def test_legacy_v1_kernel_self_report_never_provides_provisional_selection(self):
        report = self.analyze(sweep(evidence="kernel"))
        item = report["series"][0]
        self.assertEqual(item["candidate_batch_kib"], 64)
        self.assertIsNone(item["provisional_selection_kib"])
        self.assertIn("UNVERIFIED P99", item["qualification"])
        self.assertIn("SELF-REPORTED", item["read_p99_integrity"])
        self.assertIn("self-reported", item["reason"].lower())

    def test_v2_exact_latency_counts_recompute_provisional_kernel_p99(self):
        report = self.analyze(sweep_v2(evidence="kernel"))
        item = report["series"][0]
        self.assertEqual(item["schema"], analyzer.SCHEMA_V2)
        self.assertEqual(item["provisional_selection_kib"], 64)
        self.assertIn("INDEPENDENT EVIDENCE REVIEW", item["qualification"])
        self.assertIn("RECOMPUTED", item["read_p99_integrity"])
        self.assertIn("unauthenticated", item["reason"])

    def test_worst_run_p99_guards_small_fast_batch(self):
        rows = sweep()
        for row in rows:
            if row["batch_kib"] == 64 and row["run_id"].endswith("r2"):
                row["read_p99_ns"] = 1_110_000
        item = self.analyze(rows)["series"][0]
        self.assertEqual(item["candidate_batch_kib"], 128)
        self.assertAlmostEqual(item["points"][4]["read_p99_ms_worst_run"], 1.11)

    def test_no_plateau_when_largest_batch_drops(self):
        rows = sweep()
        for row in rows:
            if row["batch_kib"] == 1024:
                row["lower_write_sectors_after"] -= 4 * 2048
        item = self.analyze(rows)["series"][0]
        self.assertIsNone(item["candidate_batch_kib"])
        self.assertEqual(item["qualification"], "PLATEAU NOT REACHED")
        self.assertIn("NO STABLE", item["reason"])

    def test_incomplete_sweep_and_repeats_reject_nomination(self):
        cases = [
            ([r for r in sweep() if r["batch_kib"] != 512], "INCOMPLETE SWEEP"),
            ([r for r in sweep() if not (r["batch_kib"] == 64
                                         and r["run_id"].endswith("r2"))],
             "INSUFFICIENT REPLICATION"),
        ]
        for rows, reason in cases:
            with self.subTest(reason=reason):
                item = self.analyze(rows)["series"][0]
                self.assertIsNone(item["candidate_batch_kib"])
                self.assertIn(reason, item["reason"])

    def test_noisy_repeats_reject_nomination(self):
        rows = sweep()
        for row in rows:
            if row["batch_kib"] == 256 and row["run_id"].endswith("r2"):
                row["lower_write_sectors_after"] += 7 * 2048
        item = self.analyze(rows)["series"][0]
        self.assertIsNone(item["candidate_batch_kib"])
        self.assertIn("UNSTABLE", item["reason"])

    def test_immediate_is_baseline_not_a_sweep(self):
        rows = [
            observation(4, rep, rate=5, strategy="immediate")
            for rep in range(3)
        ]
        item = self.analyze(rows)["series"][0]
        self.assertIn("SINGLE BATCH BASELINE", item["reason"])
        self.assertIsNone(item["provisional_selection_kib"])

    def test_separate_backend_strategy_profile_and_revision(self):
        rows = (sweep() + sweep(backend="other-backend") +
                sweep(strategy="opportunistic") + sweep(profile="slow"))
        report = self.analyze(rows)
        self.assertEqual(len(report["series"]), 4)
        self.assertEqual(sum(len(s["points"]) for s in report["series"]), 36)
        self.assertTrue(all(s["candidate_batch_kib"] == 64 for s in report["series"]))

    def test_source_and_logical_bytes_are_not_throughput_numerator(self):
        rows = sweep()
        for row in rows:
            row["logical_write_bytes"] *= 250
        report = self.analyze(rows)
        self.assertEqual(report["series"][0]["candidate_batch_kib"], 64)
        self.assertAlmostEqual(report["series"][0]["points"][-1]["lower_drained_mib_s_median"],
                               20.0, places=3)

    def test_forged_success_flags_rejected(self):
        for name in analyzer.BOOL_FIELDS:
            for flag in (False, 1, "true", None):
                with self.subTest(field=name, value=flag):
                    row = observation()
                    row[name] = flag
                    with self.assertRaisesRegex(ValueError, "unverified gate"):
                        self.analyze([row])

    def test_invalid_rate_clock_schema_and_source(self):
        cases = [
            ("clock", "realtime"), ("source_kind", "fio-upper-bytes"),
            ("schema", "old"), ("evidence", "guessed"),
            ("strategy", "unknown"), ("batch_kib", 512 if False else 3),
            ("source_revision", ""), ("backend", "not safe/"),
            ("duration_ns", 0), ("read_count", 9999),
            ("read_p99_ns", 0), ("lower_write_sectors_after", 5000),
            ("lower_write_ios_after", 100), ("logical_write_bytes", 0),
            ("read_count", True), ("batch_kib", True),
        ]
        for key, bad in cases:
            with self.subTest(field=key, value=bad):
                row = observation()
                row[key] = bad
                with self.assertRaises(ValueError):
                    self.analyze([row])

    def test_missing_or_unknown_fields_rejected(self):
        row = observation()
        for changed in ({k:v for k,v in row.items() if k != "source_kind"},
                        {**row, "unexpected": "/dev/sda"}):
            with self.assertRaisesRegex(ValueError, "missing or unexpected"):
                self.analyze([changed])

    def test_duplicate_run_ids_and_duplicate_json_keys_rejected(self):
        row = observation()
        with self.assertRaisesRegex(ValueError, "duplicate run identifier"):
            self.analyze([row, copy.deepcopy(row)])
        payload = json.dumps(row)
        self.path.write_text(payload[:-1] + ', "run_id": "duplicate"}\n',
                             encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate JSON"):
            analyzer.load_rows(self.path)

    def test_blank_nan_empty_oversized_inputs_rejected(self):
        for value in ("\n", "{bad}\n", '{"x":NaN}\n', ""):
            with self.subTest(value=value):
                self.path.write_text(value, encoding="utf-8")
                with self.assertRaises(ValueError):
                    analyzer.load_rows(self.path)
        self.path.write_bytes(b"x" * (analyzer.MAX_INPUT_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "too large"):
            analyzer.load_rows(self.path)

    def test_nearest_rank_histogram_changes_p99_at_exact_99pct_boundary(self):
        # 10,000 samples means nearest-rank p99 is exactly the 9,900th.
        row = as_v2(observation())
        row["read_count"] = 10_000
        row["read_p99_ns"] = 1_000_000
        row["read_latency_counts"] = [[1_000_000, 9900], [2_000_000, 100]]
        self.assertEqual(analyzer.validate(row, 1), row)
        changed = copy.deepcopy(row)
        changed["read_latency_counts"] = [[1_000_000, 9899], [2_000_000, 101]]
        with self.assertRaisesRegex(ValueError, "recomputed nearest-rank p99"):
            analyzer.validate(changed, 1)
        changed["read_p99_ns"] = 2_000_000
        self.assertEqual(analyzer.validate(changed, 1), changed)

    def test_v2_false_p99_and_fabricated_sample_count_rejected(self):
        for changed in (
            {"read_p99_ns": 1_100_000},
            {"read_count": 12_001},
            {"read_count": 11_999},
            {"read_latency_counts": [[1_000_000, 11_999]]},
        ):
            with self.subTest(changed=changed):
                row = as_v2(observation())
                row.update(changed)
                with self.assertRaisesRegex(ValueError, "read_count differs|recomputed nearest-rank"):
                    self.analyze([row])

    def test_v2_histogram_strictly_ordered_positive_exact_latency_bins(self):
        malformed = (
            [], "not histogram", None, True, {},
            [[1_000_000, 6000], [1_000_000, 6000]],
            [[2_000_000, 6000], [1_000_000, 6000]],
            [[0, 12_000]], [[-1, 12_000]],
            [[analyzer.MAX_NS + 1, 12_000]],
            [[1_000_000, -1]], [[1_000_000, 0]],
            [[1_000_000, True]], [[True, 12_000]],
            [[1_000_000, 12_000.0]],
            [[1_000_000]],
            [[1_000_000, 12_000, "extra"]],
            [[1_000_000, analyzer.MAX_READ_COUNT + 1]],
            [[i, 1] for i in range(1, analyzer.MAX_LATENCY_BINS + 2)],
        )
        for value in malformed:
            with self.subTest(value=str(value)[:75]):
                row = as_v2(observation())
                row["read_latency_counts"] = value
                with self.assertRaisesRegex(ValueError, "latency|read_count"):
                    self.analyze([row])

    def test_v2_histogram_cannot_overflow_aggregate_sample_ceiling(self):
        row = as_v2(observation())
        row["read_count"] = analyzer.MAX_READ_COUNT
        row["read_latency_counts"] = [
            [100, analyzer.MAX_READ_COUNT], [200, 1],
        ]
        with self.assertRaisesRegex(ValueError, "exceeds limit"):
            self.analyze([row])

    def test_v1_and_v2_never_pool_into_one_spurious_plateau(self):
        rows = sweep(evidence="kernel") + sweep_v2(evidence="kernel")
        report = self.analyze(rows)
        self.assertEqual(len(report["series"]), 2)
        legacy, verified = report["series"]
        self.assertEqual(legacy["schema"], analyzer.SCHEMA)
        self.assertIsNone(legacy["provisional_selection_kib"])
        self.assertEqual(verified["schema"], analyzer.SCHEMA_V2)
        self.assertEqual(verified["provisional_selection_kib"], 64)
        self.assertEqual(report["observation_count"], 54)

    def test_v2_missing_or_unexpected_histogram_fails_closed(self):
        row = as_v2(observation())
        missing = dict(row)
        del missing["read_latency_counts"]
        with self.assertRaisesRegex(ValueError, "missing or unexpected"):
            self.analyze([missing])
        v1_with_hist = observation()
        v1_with_hist["read_latency_counts"] = [[1_000_000, 12_000]]
        with self.assertRaisesRegex(ValueError, "missing or unexpected"):
            self.analyze([v1_with_hist])

    def test_bounded_64bit_counter_and_read_sample_limits(self):
        for key, value in (
            ("lower_write_sectors_before", analyzer.MAX_COUNTER + 1),
            ("lower_write_ios_after", analyzer.MAX_COUNTER + 1),
            ("logical_write_bytes", analyzer.MAX_COUNTER + 1),
            ("read_count", analyzer.MAX_READ_COUNT + 1),
            ("read_p99_ns", analyzer.MAX_NS + 1),
        ):
            with self.subTest(key=key):
                row = as_v2(observation())
                row[key] = value
                with self.assertRaises(ValueError):
                    self.analyze([row])

    def test_v2_synthetic_histogram_cannot_claim_measured_winner(self):
        item = self.analyze(sweep_v2())["series"][0]
        self.assertIsNone(item["provisional_selection_kib"])
        self.assertEqual(item["candidate_batch_kib"], 64)
        self.assertIn("SYNTHETIC ONLY", item["qualification"])
        self.assertIn("RECOMPUTED", item["read_p99_integrity"])

    def test_v2_self_labeled_physical_remains_provisional_not_qualified(self):
        item = self.analyze(sweep_v2(evidence="physical"))["series"][0]
        self.assertEqual(item["provisional_selection_kib"], 64)
        self.assertIn("INDEPENDENT EVIDENCE REVIEW", item["qualification"])
        self.assertNotIn("QUALIFIED WINNER", item["qualification"])

    def test_v2_jsonl_duplicate_histogram_field_is_rejected(self):
        row = as_v2(observation())
        payload = json.dumps(row)
        self.path.write_text(
            payload[:-1] + ', "read_latency_counts": []}\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate JSON"):
            analyzer.load_rows(self.path)

    def test_command_line_reads_only_jsonl_and_reports_not_device_access(self):
        self.write(sweep())
        result = subprocess.run(
            [sys.executable, "-B", str(ANALYZER_PATH),
             "--observations", str(self.path)],
            text=True, capture_output=True, timeout=10, check=True,
        )
        report = json.loads(result.stdout)
        self.assertIn("NO DEVICE ACCESS", report["status"])
        self.assertIn("SYNTHETIC ONLY", report["series"][0]["qualification"])


if __name__ == "__main__":
    unittest.main()
