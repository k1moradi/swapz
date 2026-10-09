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

    def test_provisional_kernel_evidence_requires_independent_review(self):
        report = self.analyze(sweep(evidence="kernel"))
        item = report["series"][0]
        self.assertEqual(item["provisional_selection_kib"], 64)
        self.assertIn("INDEPENDENT EVIDENCE REVIEW", item["qualification"])
        self.assertIn("self-reported", item["reason"].lower())

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
