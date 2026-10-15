#!/usr/bin/env python3
"""Rootless contract tests for the sole make test JSON/XZ reporting pipeline."""
import contextlib
import importlib.util
import io
import json
import lzma
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("swapz_private_test_runner",
                                               ROOT / "tools/run-tests.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def arm(candidate, *, mode):
    v3 = candidate == "v3"
    return {
        "candidate": candidate, "verdict": "PASS",
        "source_sha": "a" * 40,
        "fixture_sha256": "b" * 64, "trace_sha256": "c" * 64,
        "device_identity": {"device": "PRIVATE_DEVICE_MUST_NOT_ESCAPE"},
        "throughput_mbps": {
            "logical_write_mbps": (20 if mode == 0 else 19) if v3 else 14,
            "lower_write_mbps": 12 if v3 else 14,
            "logical_read_mbps": 7 if v3 else 4,
            "logical_write_bytes": 8000, "logical_read_bytes": 4000,
        },
        "lower_io": {
            "lower_write_bytes": 5000 if v3 else 8000,
            "lower_read_bytes": 4000,
            "lower_write_requests": 5 if v3 else 8,
            "lower_read_requests": 4,
        },
        "read_p95_ns": 4000000 if v3 else 8000000,
        "read_p99_ns": 5000000 if v3 else 10000000,
        "write_p99_ns": 2000000,
        "seconds": 2, "verified_pages": 1024
    }


def synthetic_log():
    out = ["HOST_SWAPS_BEFORE:", "/private/system/swapfile",
           "SOURCE_HEAD=a" + "a" * 39, "PASS_LOADED_OWNED_NULLBLK_SMOKE"]
    for i, mode in enumerate((0, 1, 1, 0)):
        out.append(f"START_OWNED_RAM_PAIR_ASYNC_PREPARE={mode}")
        out.append("REPLAY_ORDER=v3-first" if i % 2 else "REPLAY_ORDER=off-first")
        for candidate in (("v3", "off") if i % 2 else ("off", "v3")):
            out.append(json.dumps(arm(candidate, mode=mode)))
        if mode:
            out.append("PASS_ASYNC_LOWER_IO_OVERLAP_STARTS=42")
        out.append(f"PASS_OWNED_RAM_PAIR_ASYNC_PREPARE={mode}")
    return "\n".join(out) + "\n"


class ReportContract(unittest.TestCase):
    def test_immutable_inputs_and_alternating_arm_order(self):
        sessions = runner.parse_sessions(synthetic_log())
        self.assertEqual([s["async_prepare"] for s in sessions], [0, 1, 1, 0])
        self.assertEqual([s["order"] for s in sessions],
                         ["off-first", "v3-first", "off-first", "v3-first"])
        self.assertTrue(all(s["status"] == "PASS" for s in sessions))
        self.assertEqual(sessions[1]["overlap_starts"], 42)
        self.assertEqual(sessions[2]["overlap_starts"], 42)
        self.assertNotIn("overlap_starts", sessions[0])
        self.assertNotIn("overlap_starts", sessions[3])
        self.assertNotIn("device_identity", json.dumps(sessions))
        self.assertNotIn("PRIVATE_DEVICE_MUST_NOT_ESCAPE", json.dumps(sessions))

    def test_comparison_gives_all_three_user_vision_dimensions(self):
        data = runner.benchmark_verdicts(runner.parse_sessions(synthetic_log()))
        self.assertEqual(data["overall"], "PASS_BOUNDED_RAM_PILOT")
        sync = data["criteria"]["sync"]
        self.assertEqual(sync["write_throughput_vs_raw"], "PASS")
        self.assertEqual(sync["lower_write_bytes_vs_raw"], "PASS")
        self.assertEqual(sync["swap_in_p99_vs_raw"], "PASS")
        self.assertAlmostEqual(sync["lower_write_saved_fraction"], .375)
        self.assertEqual(data["criteria"]["async_vs_sync"]["write_throughput"],
                         "NO_GAIN")
        self.assertAlmostEqual(data["columns"]["sync"]["swap_in_100mb_estimate_s"],
                               100 / 7)
        self.assertEqual(data["gc"][:13], "NOT_EXERCISED")
        self.assertEqual(data["physical_media"], "NOT_TESTED")
        self.assertEqual(data["cpu_memory"], "NOT_MEASURED")
        self.assertIn("PROXY_ONLY", data["endurance"])

    def test_partial_benchmarks_never_pass(self):
        sessions = runner.parse_sessions(synthetic_log())
        self.assertEqual(runner.benchmark_verdicts(sessions[:3])["overall"],
                         "INCOMPLETE")
        sessions[1]["source_sha"] = "different-source"
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCONCLUSIVE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[1]["trace_sha256"] = "tampered-trace"
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCONCLUSIVE")

    def test_report_replaced_and_not_raw_json_to_terminal(self):
        with tempfile.TemporaryDirectory(prefix="report-", dir=ROOT / "build/tests") as name:
            original_root, original_report = runner.ROOT, runner.REPORT
            try:
                runner.ROOT = Path(name)
                runner.REPORT = runner.ROOT / "build/test_results.json.xz"
                report = {"schema": "swapz-test-results-v1", "stages": [],
                          "benchmarks": {"sessions": [], "verdicts": {}}}
                fake = ["python3", "-c",
                        "print('{\"candidate\":\"off\", \"device\": \"SECRET\"}')"]
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(runner.run_stage("fake safe", fake, report), 0)
                self.assertNotIn('"candidate"', output.getvalue())
                self.assertNotIn("SECRET", output.getvalue())
                self.assertEqual(report["stages"][0]["status"], "PASS")
                path = runner.REPORT
                first = lzma.open(path, "rt").read()
                self.assertNotIn("SECRET", first)
                report["overall"] = "FAIL"
                runner.write_report(report)
                second = json.loads(lzma.open(path, "rt").read())
                self.assertEqual(second["overall"], "FAIL")
                self.assertEqual(len(list((runner.ROOT / "build").glob("*.xz"))), 1)
                self.assertIn("test_results.json.xz", str(path))
            finally:
                runner.ROOT, runner.REPORT = original_root, original_report

    def test_loaded_failure_identifies_failed_phase_without_private_paths(self):
        # This was a real regression: privileged benchmarks created
        # build/benchmark/ (mode 0700), then a non-root user attempted
        # mktemp in the same root-owned directory.
        log = ("START_LOADED_OWNED_NULLBLK_SMOKE\n"
               "PASS_LOADED_OWNED_NULLBLK_SMOKE\n"
               "mktemp: failed to create directory via template "
               "'/home/secret/swapz/build/benchmark/shared.XXXXXXXX': "
               "Permission denied\n")
        phase, reason = runner.failure_context(log)
        self.assertIn("shared fixture", phase)
        self.assertIn("not writable", reason)
        self.assertNotIn("/home/secret", reason)

        blocked = ("START_LOADED_OWNED_NULLBLK_SMOKE\n"
                   "BLOCKED: backing mismatch: "
                   "/home/private/dev/nullb-swapz-abcdef0123456789\n")
        phase, reason = runner.failure_context(blocked)
        self.assertIn("owned RAM kernel smoke", phase)
        self.assertIn("BLOCKED:", reason)
        self.assertNotIn("/home/private", reason)
        self.assertNotIn("abcdef0123456789", reason)

        pair = ("PASS_LOADED_OWNED_NULLBLK_SMOKE\n"
                "START_OWNED_RAM_PAIR_ASYNC_PREPARE=0\n"
                "PASS_OWNED_RAM_PAIR_ASYNC_PREPARE=0\n"
                "START_OWNED_RAM_PAIR_ASYNC_PREPARE=1\n"
                "FAIL: independent backing lower I/O mismatch\n")
        phase, reason = runner.failure_context(pair)
        self.assertIn("comparison 2/4 (async)", phase)
        self.assertIn("backing lower I/O mismatch", reason)

    def test_non_root_fixture_never_uses_privileged_evidence_directory(self):
        loaded = (ROOT / "tools/test-loaded.sh").read_text()
        private = (ROOT / "tools/benchmark-owned-pair.sh").read_text()
        self.assertIn('mkdir -p "$ROOT/build/tests"', loaded)
        self.assertIn('mktemp -d "$ROOT/build/tests/benchmark-plan.XXXXXXXX"', loaded)
        self.assertIn('"$ROOT/build/tests/benchmark-plan."*', loaded)
        self.assertIn('"$ROOT/build/tests/benchmark-plan."*', private)
        self.assertNotIn('mktemp -d "$ROOT/build/benchmark/', loaded)
        # Simulate the historical mode-0700 benchmark log directory without
        # any privilege or actual device. A fixture can still be created.
        import os
        with tempfile.TemporaryDirectory(prefix="fixture-permissions-",
                                         dir=ROOT / "build/tests") as folder:
            root = Path(folder)
            evidence = root / "benchmark"
            evidence.mkdir()
            evidence.chmod(0o500)
            scratch = root / "tests"
            scratch.mkdir()
            try:
                import tempfile as temporary
                owned = Path(temporary.mkdtemp(prefix="benchmark-plan.",
                                              dir=scratch))
                self.assertTrue(owned.is_dir())
                (owned / "fixture.bin").write_bytes(b"safe")
                self.assertEqual((owned / "fixture.bin").read_bytes(), b"safe")
            finally:
                evidence.chmod(0o700)

    def test_no_auto_upload_from_fake_root(self):
        with tempfile.TemporaryDirectory(prefix="publish-", dir=ROOT / "build/tests") as name:
            previous_root = runner.ROOT
            try:
                runner.ROOT = Path(name)
                notice = runner.publish()
                self.assertIn("SKIPPED", notice)
                self.assertIn("sandbox", notice)
            finally:
                runner.ROOT = previous_root


if __name__ == "__main__":
    (ROOT / "build/tests").mkdir(parents=True, exist_ok=True)
    unittest.main()
