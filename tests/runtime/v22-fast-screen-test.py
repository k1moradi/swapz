#!/usr/bin/env python3
"""Purely rootless fast-screen planning + sidecar-gate regression.

All samples and performance figures below are FABRICATED fixtures, NEVER
empirical or independently attested measurements. No device access or fio.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "v22-fast-screen.py"
SPEC = importlib.util.spec_from_file_location("swapz_fast_screen_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

MIB = 1048576


class ThreeCaseScreenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="swapz-fast-screen-rootless-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "results.jsonl"
        self.marker = self.root / mod.finalizer.NAME
        self.rows = [self._row(strategy, batch, i)
                     for i, (strategy, batch) in enumerate(mod.FAST_CASES)]
        self.save()
        self.seal()

    def seal(self):
        if self.marker.exists() or self.marker.is_symlink():
            self.marker.unlink()
        return mod.finalizer.write_marker(
            self.path, self.marker, 3, mod.BACKEND)

    def _row(self, strategy, batch, i):
        samples = 1200
        p99_ns = 1_000_000 + i * 100_000
        sidecar = f"reader-{i}.latbin"
        content = struct.pack("!QQ", p99_ns, samples)
        (self.root / sidecar).write_bytes(content)
        return {
            "backend": mod.BACKEND, "strategy": strategy, "batch_kib": batch,
            "logical_write_bytes": 16 * MIB, "upper_write_mib_s": 123.0,
            "logical_flush_window_mib_s": 8.0,
            "lower_counter_window_mib_s": 1.0,
            "drain_window_s": 2.0, "lower_write_ios": 10,
            "lower_write_sectors": 4096, "read_count": samples,
            "read_p99_ms": p99_ns / 1e6, "read_max_ms": 3.0,
            "staged_early": 0, "isolated_sentinel_readback_ok": True,
            "status": {"failed": "0", "strategy": strategy,
                       "batch_kib": str(batch), "lower_discard": "off"},
            "fio_full_writer_verification": {
                "full_writer_readback_ok": True,
                "writer_verified_bytes": 28 * MIB - 4096,
                "writer_verified_pages": (28 * MIB - 4096) // 4096,
                "writer_verify_method": "fio-crc32c-sequential-read-diagnostic",
            },
            "exact_read_latency": {
                "read_count": samples, "read_p99_ns": p99_ns,
                "read_latency_sidecar": sidecar,
                "read_latency_sha256": hashlib.sha256(content).hexdigest(),
                "read_latency_bytes": len(content),
                "read_latency_source": mod.SOURCE,
            },
        }

    def save(self):
        self.path.write_text("".join(json.dumps(row) + "\n" for row in self.rows),
                             encoding="utf-8")

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPT), *map(str, args)],
            capture_output=True, text=True, timeout=5, check=False,
        )

    def test_fast_profile_is_exactly_three_no_execution(self):
        p = mod.make_plan("fast")
        self.assertEqual(p["total_planned_runs"], 3)
        self.assertEqual(p["cases"], [
            {"strategy": "immediate", "batch_kib": 4},
            {"strategy": "opportunistic", "batch_kib": 64},
            {"strategy": "staged", "batch_kib": 64},
        ])
        self.assertEqual(p["null_blk_tick_budget_bytes"], 419420)
        self.assertEqual(p["environment"]["SWAPZ_BENCH_BATCHES"], "64")
        self.assertEqual(p["environment"]["SWAPZ_BENCH_RUNTIME"], "10")
        self.assertEqual(p["environment"]["SWAPZ_BENCH_READ_IOPS"], "300")
        self.assertEqual(p["nominal_reads_per_case_NOT_GUARANTEED"], 3000)
        self.assertIs(p["execution_authorized"], False)
        self.assertIs(p["device_operations_performed"], False)
        self.assertIsNone(p["qualified_winner"])
        self.assertEqual(p["evidence"], "PLAN_ONLY_NO_MEASUREMENTS")
        cli = self.cli("--plan", "fast")
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(json.loads(cli.stdout)["cases"], p["cases"])

    def test_full_profile_admits_fifteen_4_through_256(self):
        p = mod.make_plan("full")
        self.assertEqual(len(p["cases"]), 15)
        self.assertEqual(p["total_planned_runs"], 15)
        self.assertEqual(p["environment"]["SWAPZ_BENCH_BATCHES"],
                         "4 8 16 32 64 128 256")
        self.assertEqual(p["environment"]["SWAPZ_BENCH_RUNTIME"], "30")
        self.assertEqual(p["environment"]["SWAPZ_BENCH_READ_IOPS"], "500")
        self.assertNotIn(512, [row["batch_kib"] for row in p["cases"]])
        self.assertIsNone(p["qualified_winner"])

    def test_three_case_diagnostic_acceptance_is_not_winner_promotion(self):
        result = mod.check_results(self.path)
        self.assertEqual(result["case_count"], 3)
        self.assertEqual(result["diagnostic_gate"], "PASS_SOURCE_REPORTED_ONLY")
        self.assertEqual(result["cases"][0]["observed_reads"], 1200)
        self.assertEqual(result["cases"][2]["exact_read_p99_ms"], 1.2)
        self.assertIsNone(result["qualified_winner"])
        self.assertIn("NO QUALIFIED WINNER", result["limitations"])
        cli = self.cli("--results", self.path)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(json.loads(cli.stdout)["case_count"], 3)

    def test_missing_extra_swapped_or_duplicate_cases_fail(self):
        originals = copy.deepcopy(self.rows)
        for rows in (
            originals[:2], originals + [originals[0]],
            [originals[1], originals[0], originals[2]],
            [originals[0], originals[0], originals[2]],
        ):
            with self.subTest(cases=[x["strategy"] for x in rows]):
                self.rows = rows
                self.save()
                with self.assertRaisesRegex(ValueError, "exactly three|expected case"):
                    mod.check_results(self.path)
        self.rows = originals

    def test_subthreshold_read_counts_fail_without_claimed_target_iops(self):
        self.rows[1]["read_count"] = 999
        self.rows[1]["exact_read_latency"]["read_count"] = 999
        self.save()
        with self.assertRaisesRegex(ValueError, "fewer than 1000"):
            mod.check_results(self.path)

    def test_wrong_backend_or_kernel_status_fails(self):
        for key, value in (
            ("backend", "null_blk-unthrottled-500000ns-QD1"),
            ("batch_kib", 128),
            ("isolated_sentinel_readback_ok", False),
            ("lower_write_ios", 0),
        ):
            with self.subTest(key=key):
                original = self.rows[1][key]
                self.rows[1][key] = value
                self.save()
                with self.assertRaises(ValueError):
                    mod.check_results(self.path)
                self.rows[1][key] = original
        for field, value in (
            ("batch_kib", "128"), ("lower_discard", "on"), ("strategy", "staged"),
        ):
            with self.subTest(field=field):
                original = self.rows[1]["status"][field]
                self.rows[1]["status"][field] = value
                self.save()
                with self.assertRaisesRegex(ValueError, "status"):
                    mod.check_results(self.path)
                self.rows[1]["status"][field] = original

    def test_missing_crc_summary_and_tampered_exact_sidecar_fail(self):
        self.rows[0].pop("fio_full_writer_verification")
        self.save()
        with self.assertRaisesRegex(ValueError, "CRC checks required"):
            mod.check_results(self.path)
        self.rows[0]["fio_full_writer_verification"] = copy.deepcopy(
            self.rows[1]["fio_full_writer_verification"])
        self.save()
        raw = self.root / self.rows[1]["exact_read_latency"]["read_latency_sidecar"]
        raw.write_bytes(raw.read_bytes()[:-1] + b"!")
        # A one-bin histogram cannot be changed without altering its count or
        # p99, so exact-distribution validation may catch tampering first.
        with self.assertRaisesRegex(ValueError,
                                    "exact count or nearest-rank p99 mismatch|SHA-256 mismatch"):
            mod.check_results(self.path)

    def test_symlink_missing_traversal_and_duplicate_sidecars_fail(self):
        alias = self.root / "alias.jsonl"
        alias.symlink_to(self.path)
        with self.assertRaises(ValueError):
            mod.check_results(alias)
        original = self.rows[1]["exact_read_latency"]["read_latency_sidecar"]
        for invalid in ("../file.latbin", "bad/sidecar.latbin", "reader-0.latbin"):
            with self.subTest(sidecar=invalid):
                self.rows[1]["exact_read_latency"]["read_latency_sidecar"] = invalid
                self.save()
                with self.assertRaises(ValueError):
                    mod.check_results(self.path)
        self.rows[1]["exact_read_latency"]["read_latency_sidecar"] = original
        self.save()
        (self.root / original).unlink()
        (self.root / original).symlink_to(self.root / "reader-0.latbin")
        with self.assertRaises(ValueError):
            mod.check_results(self.path)

    def test_missing_corrupt_unlinked_marker_and_stale_results_fail_closed(self):
        self.marker.unlink()
        with self.assertRaises(FileNotFoundError):
            mod.check_results(self.path)
        self.seal()
        self.rows[1]["upper_write_mib_s"] = 120.0
        self.save()
        with self.assertRaisesRegex(ValueError, "not bound to exact results"):
            mod.check_results(self.path)
        self.rows[1]["upper_write_mib_s"] = 123.0
        self.save()
        self.seal()
        self.assertEqual(mod.check_results(self.path)["case_count"], 3)

        original = self.marker.read_bytes()
        for corrupted in (b"", b"{", original[:20], original + b"x"):
            with self.subTest(corrupted=corrupted[:20]):
                self.marker.write_bytes(corrupted)
                with self.assertRaises(ValueError):
                    mod.check_results(self.path)
        self.marker.write_bytes(original)
        self.assertIsNone(mod.check_results(self.path)["qualified_winner"])

    def test_marker_state_counter_backend_and_digest_forgery_rejected(self):
        marker = json.loads(self.marker.read_text(encoding="utf-8"))
        for key, value in (
            ("state", "incomplete_after_case_three"),
            ("completed_cases", 2),
            ("completed_cases", True),
            ("backend", "null_blk-unthrottled-500000ns-QD1"),
            ("results_file", "../other.jsonl"),
            ("results_bytes", marker["results_bytes"] + 1),
            ("results_sha256", "f" * 64),
            ("evidence", "INDEPENDENT_ATTESTED"),
            ("qualified_winner", "staged"),
        ):
            with self.subTest(key=key):
                bad = dict(marker)
                bad[key] = value
                self.marker.write_text(json.dumps(bad), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "finalization marker"):
                    mod.check_results(self.path)
        self.marker.write_bytes(
            self.marker.read_bytes().replace(b'"schema":', b'"schema":"forged","schema":', 1))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            mod.check_results(self.path)
        self.marker.write_text(json.dumps(marker) + "\n", encoding="utf-8")

    def test_marker_symlink_hardlink_and_reuse_refused(self):
        self.marker.unlink()
        self.marker.symlink_to(self.root / "reader-0.latbin")
        with self.assertRaises(OSError):
            mod.check_results(self.path)
        with self.assertRaises(FileExistsError):
            mod.finalizer.write_marker(self.path, self.marker, 3, mod.BACKEND)
        self.marker.unlink()
        self.seal()
        hardlink = self.root / "second-marker"
        hardlink.hardlink_to(self.marker)
        with self.assertRaisesRegex(ValueError, "singly-linked"):
            mod.check_results(self.path)
        hardlink.unlink()
        self.assertEqual(mod.check_results(self.path)["case_count"], 3)
        with self.assertRaises(FileExistsError):
            mod.finalizer.write_marker(self.path, self.marker, 3, mod.BACKEND)

    def test_rootless_mock_teardown_never_finalizes_failed_or_interrupted_run(self):
        # Extract only the Bash EXIT handler; all device cleanup commands are
        # replaced by the stub and must never reach the kernel in this test.
        shell = (HERE / "streaming-benchmark.sh").read_text(encoding="utf-8")
        function = "cleanup() {" + shell.split("cleanup() {", 1)[1].split(
            "\n}\ntrap cleanup EXIT", 1)[0] + "\n}"
        repo_root = HERE.parents[1]
        def call(*, teardown_ok, report_ok, initial_ok, kept="1"):
            fixture = self.root / "rootless-cleanup-case"
            fixture.mkdir(exist_ok=True)
            (fixture / "results.jsonl").write_bytes(self.path.read_bytes())
            final = fixture / mod.finalizer.NAME
            if final.exists():
                final.unlink()
            source = (
                "set -u\n"
                f"ROOT={str(repo_root)!r}\n"
                f"TMP={str(fixture)!r}\n"
                'RESULTS="$TMP/results.jsonl"\n'
                "TARGET_ACTIVE=0\n"
                f"KEEP_ARTIFACTS={kept!r}\n"
                f"REPORT_COMPLETE={int(report_ok)}\n"
                "CASES_COMPLETED=3\n"
                f"BACKEND={mod.BACKEND!r}\n"
                'BACKEND_KIND=null_blk\n'
                'NBD_STATS=""\n'
                "swapz_benchmark_cleanup_resources() { "
                f"return {0 if teardown_ok else 1}; }}\n"
                + function + "\n" +
                ("true\n" if initial_ok else "false\n") +
                "cleanup\n"
            )
            cmd = subprocess.run(["bash", "-c", source],
                                 capture_output=True, text=True, timeout=5)
            return cmd, final
        successful, marker = call(teardown_ok=True, report_ok=True, initial_ok=True)
        self.assertEqual(successful.returncode, 0, successful.stderr)
        self.assertTrue(marker.is_file())
        self.assertIn("PASS (OWNED RESOURCES REMOVED", successful.stdout)
        for kwargs in (
            {"teardown_ok": False, "report_ok": True, "initial_ok": True},
            {"teardown_ok": True, "report_ok": False, "initial_ok": True},
            {"teardown_ok": True, "report_ok": True, "initial_ok": False},
        ):
            with self.subTest(kwargs=kwargs):
                failed, marker = call(**kwargs)
                self.assertNotEqual(failed.returncode, 0)
                self.assertFalse(marker.exists())
                self.assertNotIn("PASS (OWNED RESOURCES REMOVED", failed.stdout)

    def test_mock_runner_profile_is_only_environment_not_executed(self):
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("subprocess.run", script)
        self.assertNotIn("dmsetup ", script)
        self.assertNotIn("modprobe ", script)
        self.assertNotIn("insmod ", script)
        self.assertNotIn("os.system", script)
        self.assertNotIn("sudo ", script)
        self.assertIn("qualified_winner", script)
        self.assertIn("execution_authorized", script)


if __name__ == "__main__":
    unittest.main(verbosity=2)
