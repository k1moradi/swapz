#!/usr/bin/env python3
"""Rootless proof that both labels replay one exact immutable I/O plan.

This does NOT load the swapz module: same regular-file replay code tests only
the trace contract, oracle, safety guard and fail-closed pair comparator.
"""
import contextlib
import copy
import errno
import hashlib
import io
import json
import os
import random
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import private_memory

PAGE = 4096
ROOT = Path(__file__).resolve().parents[3]
SCRIPT = Path(__file__).with_name("io-replay.py")


class PairReplayContract(unittest.TestCase):
    def test_representative_fixture_requires_fail_closed_memory_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.bin"
            self.assertFalse(private_memory.fixture_is_representative(path))
            (path.parent / "fixture.json").write_text(
                json.dumps({"content_profile": "representative"}))
            self.assertTrue(private_memory.fixture_is_representative(path))
            metadata_path = path.parent / "fixture.json"
            metadata_path.write_text("not json")
            with self.assertRaisesRegex(ValueError, "privacy metadata"):
                private_memory.fixture_is_representative(path)
            metadata_path.unlink()
            metadata_target = path.parent / "metadata-target.json"
            metadata_target.write_text(json.dumps({"content_profile": "representative"}))
            metadata_path.symlink_to(metadata_target)
            with self.assertRaisesRegex(ValueError, "privacy metadata"):
                private_memory.fixture_is_representative(path)
            # A FIFO at the metadata path must not stall privacy classification.
            metadata_path.unlink()
            os.mkfifo(metadata_path)
            with self.assertRaisesRegex(ValueError, "regular file"):
                private_memory.fixture_is_representative(path)

        libc = mock.Mock()
        libc.prctl.return_value = 0
        libc.mlockall.return_value = -1
        with mock.patch.object(private_memory.resource, "setrlimit") as no_core, \
                mock.patch.object(private_memory.ctypes, "CDLL",
                                  return_value=libc):
            with self.assertRaisesRegex(ValueError, "protection unavailable"):
                private_memory.protect_private_memory()
            no_core.assert_called_once_with(
                private_memory.resource.RLIMIT_CORE, (0, 0))
            libc.prctl.assert_called_once_with(4, 0, 0, 0, 0)
            libc.mlockall.assert_called_once_with(3)

    def test_private_fixture_snapshot_protects_representative_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "fixture.bin"
            destination = root / "snapshot.bin"
            payload = (b"private-page" * 4096)[:8192]
            source.write_bytes(payload)
            (root / "fixture.json").write_text(
                json.dumps({"content_profile": "representative"}))
            with mock.patch.object(
                    private_memory, "protect_private_memory") as protect:
                self.assertTrue(
                    private_memory.copy_fixture(source, destination))
                protect.assert_called_once_with()
            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)

            destination.unlink()
            destination.write_bytes(b"pre-existing")
            with mock.patch.object(
                    private_memory, "protect_private_memory") as protect:
                with self.assertRaises(FileExistsError):
                    private_memory.copy_fixture(source, destination)
                protect.assert_called_once_with()
            self.assertEqual(destination.read_bytes(), b"pre-existing")

            destination.unlink()
            (root / "fixture.json").write_text(
                json.dumps({"content_profile": "medium"}))
            with mock.patch.object(
                    private_memory, "protect_private_memory") as protect:
                self.assertFalse(
                    private_memory.copy_fixture(source, destination))
                protect.assert_not_called()
            destination.unlink()
            with mock.patch.object(
                    private_memory, "protect_private_memory") as protect:
                self.assertTrue(
                    private_memory.copy_fixture(
                        source, destination, force_private=True))
                protect.assert_called_once_with()

            destination.unlink()
            source.unlink()
            target = root / "fixture-target.bin"
            target.write_bytes(payload)
            source.symlink_to(target)
            with self.assertRaises(OSError):
                private_memory.copy_fixture(source, destination)
            self.assertFalse(destination.exists())

            # O_NONBLOCK must reject an unexpected FIFO without waiting for a writer.
            source.unlink()
            os.mkfifo(source)
            with self.assertRaisesRegex(ValueError, "regular file"):
                private_memory.copy_fixture(source, destination)
            self.assertFalse(destination.exists())

    def test_representative_memory_protection_success_path(self):
        libc = mock.Mock()
        libc.prctl.return_value = 0
        libc.mlockall.return_value = 0
        with mock.patch.object(private_memory.resource, "setrlimit"), \
                mock.patch.object(private_memory.ctypes, "CDLL",
                                  return_value=libc):
            private_memory.protect_private_memory()
            libc.prctl.assert_called_once_with(4, 0, 0, 0, 0)
            libc.mlockall.assert_called_once_with(3)

    def test_id178_replay_conservation_and_fail_closed_fields(self):
        import runpy
        replay = runpy.run_path(str(SCRIPT))
        check = replay["validate_lane_gap_counters"]
        values = {field: 0 for field in replay["LANE_GAP_COUNTER_FIELDS"]}
        values["deferred_upper_completion_bios"] = 1
        values["upper_write_completed_ok"] = 1
        values["lane_runs_submitted"] = 1
        values["lane_gap_runs"] = 1
        values["lane_gap_wall_ns"] = 60
        values["lane_gap_owner_read_ns"] = 20
        values["lane_gap_owner_reads"] = 2
        for field in replay["LANE_GAP_PART_FIELDS"]:
            values[field] = 10
        values["lane_successor_admitted_by_completion_1"] = 1
        values["lane_successor_owned_by_completion_0"] = 1
        values["ack_dwell_deferred_count"] = 1
        values["ack_dwell_deferred_ns"] = 1001
        values["ack_dwell_deferred_le_4us"] = 1
        check(values)
        for key, bad in (
                ("lane_gap_wall_ns", 61),
                ("lane_gap_owner_read_ns", 61),
                ("lane_gap_invalid", 1),
                ("lane_runs_submitted", 2),
                ("lane_successor_owned_by_completion_16_plus", 1),
                ("ack_dwell_deferred_count", 2),
                ("ack_dwell_deferred_le_4us", 0),
                ("ack_dwell_immediate_count", 1)):
            trial = {**values, key: bad}
            with self.subTest(key=key), self.assertRaises(ValueError):
                check(trial)
        for key in replay["LANE_GAP_COUNTER_FIELDS"]:
            trial = values.copy()
            del trial[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                check(trial)
        for trial in (
                {**values, "lane_gap_runs": 0},
                {**values, "lane_gap_foreign_ns": 1}):
            with self.assertRaises(ValueError):
                check(trial)
        # Foreign gaps have successor bins but no six-part contribution.
        foreign = values.copy()
        foreign.update(lane_gap_runs=0, lane_gap_wall_ns=0,
                       lane_gap_foreign_runs=1, lane_gap_foreign_ns=70)
        for key in replay["LANE_GAP_PART_FIELDS"]:
            foreign[key] = 0
        check(foreign)

    def test_id178_report_table_bins_and_host_cpu(self):
        import contextlib
        import importlib.util
        import io
        spec = importlib.util.spec_from_file_location(
            "swapz_lane_gap_reporter", SCRIPT.parents[2] / "tools/run-tests.py")
        reporter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reporter)
        values = {field: 0 for field in reporter.LANE_GAP_FIELDS}
        values.update(lane_gap_runs=2, lane_gap_wall_ns=20000,
                      lane_gap_completion_wake_ns=2000,
                      lane_gap_publication_ns=2000,
                      lane_gap_no_work_ns=4000,
                      lane_gap_admitted_unowned_ns=4000,
                      lane_gap_staged_held_ns=4000,
                      lane_gap_seal_ns=4000,
                      lane_gap_foreign_runs=1, lane_gap_foreign_ns=5000,
                      lane_gap_unpaired_runs=1,
                      lane_gap_owner_read_ns=3000, lane_gap_owner_reads=2,
                      lane_successor_admitted_by_completion_0=1,
                      lane_successor_admitted_by_completion_1=1,
                      lane_successor_admitted_by_completion_2_3=1,
                      lane_successor_owned_by_completion_0=2,
                      lane_successor_owned_by_completion_1=1,
                      ack_dwell_deferred_count=2,
                      ack_dwell_deferred_le_16us=1,
                      ack_dwell_deferred_le_64us=1)
        arm = {"lane_gap": values, "host_cpu": {"busy_fraction": .45}}
        failed = {"lane_gap": {**values, "lane_gap_runs": 99},
                  "host_cpu": {"busy_fraction": .9}}
        benchmarks = {
            # A failed session never supplies a descriptive row.
            "storage_envelope_sessions": [
                {"envelope": "sata_ssd", "status": "FAIL",
                 "arms": {"swapz": failed}},
                {"envelope": "sata_ssd", "status": "PASS",
                 "arms": {"swapz": arm}},
                {"envelope": "nvme_gen4", "status": "PASS",
                 "arms": {"swapz": arm}},
                {"envelope": "nvme_gen5", "status": "PASS",
                 "arms": {"swapz": arm}}],
            "sessions": [{"regime": "ssd_emulated", "async_prepare": 1,
                          "status": "PASS", "arms": {"swapz": arm}}],
        }
        rows = reporter.lane_gap_attribution_rows(benchmarks)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["runs"], 2)
        # Descriptive parsing is UNAVAILABLE on a missing token, never fatal;
        # io-replay and the timed-telemetry gates fail such sessions closed.
        incomplete = dict(values)
        del incomplete["lane_gap_seal_ns"]
        self.assertIsNone(reporter.lane_gap_record(incomplete))
        self.assertIsNone(reporter.lane_gap_record(None))
        self.assertEqual(reporter.lane_gap_record(values)["lane_gap_runs"], 2)
        self.assertEqual(rows[0]["gap_per_run_us"], 10)
        self.assertEqual(rows[0]["foreign_runs"], 1)
        self.assertEqual(rows[0]["foreign_gap_ms"], .005)
        self.assertEqual(rows[0]["unpaired_runs"], 1)
        self.assertEqual(rows[0]["successor_admitted_distribution"],
                         [1, 1, 1, 0, 0, 0])
        self.assertEqual(rows[0]["successor_owned_distribution"],
                         [2, 1, 0, 0, 0, 0])
        self.assertEqual(rows[0]["owner_read_ms"], .003)
        self.assertEqual(rows[0]["owner_reads"], 2)
        self.assertEqual(rows[0]["deferred_ack_p99_bin_bound"], "<=64us")
        self.assertEqual(rows[0]["host_busy_pct"], 45)
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            reporter.print_lane_gap_attribution(rows)
        self.assertIn("SSD lower-lane gap attribution", stream.getvalue())
        self.assertIn("1/1/1/0/0/0", stream.getvalue())
        self.assertIn("0.003/2", stream.getvalue())
        self.assertIn("<=64us", stream.getvalue())

        fast_spec = importlib.util.spec_from_file_location(
            "swapz_lane_gap_fast", SCRIPT.parents[2] / "tools/fast-test.py")
        fast = importlib.util.module_from_spec(fast_spec)
        fast_spec.loader.exec_module(fast)
        fast_rows = fast.lane_gap_table_rows([{
            "scenario": "nvme5-mixed", "lane_gap": values,
            "host_busy_pct": 45.0}])
        self.assertEqual(fast_rows[0]["successor_owned_distribution"],
                         [2, 1, 0, 0, 0, 0])
        self.assertEqual(fast_rows[0]["owner_reads"], 2)


    def test_linear_calibration_rejects_foreign_or_offset_backing(self):
        import runpy
        validate = runpy.run_path(str(SCRIPT))["validate_linear_table"]
        validate("0 8192 linear 251:1 0", 1024, "251:1")
        for table in ("0 8192 linear 251:2 0", "0 8192 linear 251:1 8",
                      "0 8191 linear 251:1 0", "0 8192 swapz 251:1 0",
                      "0 8192 linear 251:1 0\n8192 8 linear 251:1 0"):
            with self.assertRaises(ValueError):
                validate(table, 1024, "251:1")

    def test_linear_calibration_keeps_product_arm_separate_and_suffixes_ordered(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "swapz_linear_fast", SCRIPT.parents[2] / "tools/fast-test.py")
        fast = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fast)
        arguments = fast.scenario_arguments("nvme5-mixed-lanes", "/plan", True, True)
        self.assertEqual(arguments[-4:], ["--shared-plan", "/plan",
                                         "--linear-calibration", "--swapz-first"][-5:])
        output = "\n".join(json.dumps({"candidate": arm, "verdict": "PASS"})
                            for arm in ("off", "swapz", "linear"))
        self.assertEqual(set(fast.parse_arms(output)), {"off", "swapz"})
        self.assertEqual(set(fast.parse_arms(output, "linear")), {"off", "linear"})

    def test_fast_development_noise_screen_does_not_reject_workload_cpu(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "swapz_fast_test", SCRIPT.parents[2] / "tools/fast-test.py")
        fast = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fast)
        idle = {"status": "AVAILABLE", "busy_fraction": .03,
                "pressure_some_fraction": .01, "steal_fraction": 0}
        busy = {**idle, "busy_fraction": .99, "pressure_some_fraction": .85}
        arms = {name: {"host_cpu": busy} for name in ("off", "swapz")}
        screened = fast.performance_validity(idle, idle, arms)
        self.assertEqual(screened["status"], "SCREENED")
        self.assertTrue(screened["performance_usable"])
        self.assertEqual(screened["reasons"], [])
        for key, value in (("busy_fraction", .26),
                           ("pressure_some_fraction", .06),
                           ("steal_fraction", .02)):
            for before, after in (({**idle, key: value}, idle),
                                  (idle, {**idle, key: value})):
                noisy = fast.performance_validity(before, after, arms)
                self.assertEqual(noisy["status"], "NOISY")
                self.assertFalse(noisy["performance_usable"])
        unknown = fast.performance_validity({}, idle, arms)
        self.assertEqual(unknown["status"], "UNKNOWN")
        self.assertFalse(unknown["performance_usable"])
        partial = fast.performance_validity(
            {**idle, "status": "PARTIAL", "pressure_some_fraction": None},
            idle, arms)
        self.assertEqual(partial["status"], "UNKNOWN")
        self.assertEqual(fast.performance_validity(
            {**idle, "pressure_some_fraction": None}, idle, arms)["status"],
            "UNKNOWN")
        stolen = {"off": {"host_cpu": {**busy, "steal_fraction": .02}}}
        self.assertEqual(fast.performance_validity(idle, idle, stolen)["status"],
                         "NOISY")
        missing_arm = fast.performance_validity(idle, idle, {"off": {}})
        self.assertEqual(missing_arm["status"], "UNKNOWN")
        self.assertEqual(fast.performance_validity(
            idle, idle, {"off": {"host_cpu": {"status": "AVAILABLE"}}})["status"],
            "UNKNOWN")
        rows = [
            {"scenario": "sata-mixed#1", "raw_w": 100,
             "performance_validity": fast.performance_validity(idle, idle, arms)},
            {"scenario": "sata-mixed#2", "raw_w": 112,
             "performance_validity": fast.performance_validity(idle, idle, arms)},
            {"scenario": "fast-mixed", "raw_w": 50,
             "performance_validity": fast.performance_validity(idle, idle, arms)},
        ]
        fast.reject_raw_drift(rows)
        for row in rows[:2]:
            self.assertEqual(row["performance_validity"]["status"], "NOISY")
            self.assertFalse(row["performance_validity"]["performance_usable"])
            self.assertIn("raw repeat spread", row["performance_validity"]["reasons"][0])
        self.assertEqual(rows[2]["performance_validity"]["status"], "SCREENED")
        rows[2]["raw_w"] = 0
        fast.reject_raw_drift(rows[2:])
        self.assertEqual(rows[2]["performance_validity"]["status"], "UNKNOWN")
        self.assertFalse(rows[2]["performance_validity"]["performance_usable"])

    def test_fast_content_controls_preserve_fixture_provenance(self):
        import hashlib
        import importlib.util
        import shutil

        spec = importlib.util.spec_from_file_location(
            "swapz_fast_content", SCRIPT.parents[2] / "tools/fast-test.py")
        fast = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fast)
        fixtures = {}
        for content, profiles, raw_pages in (
                ("medium", {"medium": 128}, 0),
                ("entropy", {"entropy": 128}, 128),
                ("balanced", {"medium": 64, "entropy": 64}, 64)):
            plan = fast.prepare_plan(content)
            try:
                fixture = (plan / "fixture.bin").read_bytes()
                metadata = json.loads((plan / "fixture.json").read_text())
                self.assertEqual(metadata["profile_pages"], profiles)
                self.assertEqual(metadata["raw_pages"], raw_pages)
                self.assertEqual(metadata["fixture_sha256"],
                                 hashlib.sha256(fixture).hexdigest())
                # Both candidates consume this fixture's immutable replay plan.
                for name in ("plan", "plan-write-qd4"):
                    manifest = json.loads((plan / name / "manifest.json").read_text())
                    self.assertEqual(manifest["fixture_sha256"],
                                     metadata["fixture_sha256"])
                fixtures[content] = metadata["fixture_sha256"]
            finally:
                shutil.rmtree(plan)
        self.assertEqual(len(set(fixtures.values())), 3)

    def test_representative_content_is_private_matched_and_analyzed(self):
        import hashlib
        import importlib.util
        import shutil
        import struct

        spec = importlib.util.spec_from_file_location(
            "swapz_fast_representative", SCRIPT.parents[2] / "tools/fast-test.py")
        fast = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fast)
        self.require_native_tool("anon-page-analyzer", "representative")

        marker = b"PRIVATE_REPRESENTATIVE_PAGE_5d741fc2"
        zero = bytes(PAGE)
        same = bytes([0x6b]) * PAGE
        counter = b"".join(struct.pack("<Q", 0x8317 + index)
                            for index in range(PAGE // 8))
        varied = marker + bytes((index * 47 + 31) & 0xff
                                for index in range(PAGE - len(marker)))
        sample_bytes = b"".join((zero, same, counter, varied) * 32)

        with tempfile.TemporaryDirectory(prefix="swapz-page-sample-") as temp:
            sample = Path(temp) / "pages.bin"
            sample.write_bytes(sample_bytes)
            sample.chmod(0o600)
            try:
                plan = fast.prepare_plan("representative", sample_path=sample)
            except ValueError as exc:
                if "representative page protection unavailable" not in str(exc):
                    raise
                # CI frequently lacks sufficient RLIMIT_MEMLOCK even for the
                # Python interpreter. This is an expected fail-closed BLOCKED,
                # never authorization to run representative pages unprotected.
                self.skipTest("representative plan BLOCKED: mlockall budget unavailable")
            try:
                fixture = (plan / "fixture.bin").read_bytes()
                metadata_text = (plan / "fixture.json").read_text()
                metadata = json.loads(metadata_text)
                self.assertEqual(fixture, sample_bytes)
                self.assertEqual(metadata["pages"], 128)
                self.assertEqual(metadata["profile_pages"], {"representative": 128})
                self.assertEqual(metadata["fixture_sha256"],
                                 hashlib.sha256(sample_bytes).hexdigest())
                self.assertEqual(metadata["offline_page_analysis"]["zero_pages"], 32)
                self.assertEqual(
                    metadata["offline_page_analysis"]["nonzero_same_filled_pages"], 32)
                self.assertEqual(metadata["offline_page_analysis"]["pages"], 128)
                self.assertNotIn(str(sample), metadata_text)
                self.assertNotIn(marker.decode(), metadata_text)
                for name in ("plan", "plan-write-qd4"):
                    manifest = json.loads((plan / name / "manifest.json").read_text())
                    self.assertEqual(manifest["fixture_sha256"],
                                     metadata["fixture_sha256"])
                    self.assertEqual(manifest["fixture_pages"], 128)
            finally:
                shutil.rmtree(plan)

            symlink = Path(temp) / "sample-link"
            symlink.symlink_to(sample)
            with self.assertRaisesRegex(ValueError, "open representative page sample"):
                fast.prepare_plan("representative", sample_path=symlink)

    def test_long_mixed_development_plan_preserves_prefix_and_oracle(self):
        import hashlib
        import importlib.util
        import shutil

        spec = importlib.util.spec_from_file_location(
            "swapz_fast_long_mixed", SCRIPT.parents[2] / "tools/fast-test.py")
        fast = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fast)
        with self.assertRaises(ValueError):
            fast.prepare_plan(mixed_ops=32768)
        plan = fast.prepare_plan(mixed_ops=65536)
        try:
            check = fast.HOST_CPU["check_plan"]
            fixture = (plan / "fixture.bin").read_bytes()
            for name in ("plan", "plan-mixed-lanes-waves",
                         "plan-mixed-lanes-persistent"):
                manifest = json.loads((plan / name / "manifest.json").read_text())
                self.assertEqual(manifest["measure_ops"], 65536)
                self.assertEqual(manifest["warmup_ops"], 1024)
                _, latest = check(plan / name / "trace.jsonl", manifest, 128)
                expected = b"".join(fixture[i * PAGE:(i + 1) * PAGE]
                                    for i in latest)
                self.assertEqual(hashlib.sha256(expected).hexdigest(),
                                 manifest["expected_post_sha256"])
            for qd in (1, 4, 8, 32):
                manifest = json.loads(
                    (plan / f"plan-write-qd{qd}" / "manifest.json").read_text())
                self.assertEqual(manifest["measure_ops"], 4096)
            baseline = plan / "short-prefix"
            subprocess.run([
                sys.executable, "-B", str(SCRIPT), "prepare", "--fixture",
                str(plan / "fixture.bin"), "--output-dir", str(baseline),
                "--logical-pages", "1024", "--writer-pages", "256",
                "--reader-start", "512", "--reader-pages", "256", "--qd",
                "32", "--read-pct", "25", "--warmup-ops", "1024",
                "--measure-ops", "16384", "--iops", "0"],
                check=True, stdout=subprocess.DEVNULL)
            short = (baseline / "trace.jsonl").read_bytes().splitlines()
            long = (plan / "plan" / "trace.jsonl").read_bytes().splitlines()
            self.assertEqual(long[:len(short)], short)
        finally:
            shutil.rmtree(plan)

    def test_long_mixed_selector_rejects_other_cohorts_before_privilege(self):
        import importlib.util
        from unittest.mock import patch

        spec = importlib.util.spec_from_file_location(
            "swapz_fast_long_scope", SCRIPT.parents[2] / "tools/fast-test.py")
        fast = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fast)
        for scenario, extra in (("fast-w8", []), ("fast-stripes-w4", []),
                                ("fast-mixed", ["--calibration", "linear"])):
            parser_stderr = io.StringIO()
            with contextlib.redirect_stderr(parser_stderr), \
                    patch.object(sys, "argv", ["fast-test", "--mixed-ops",
                    "65536", "--scenarios", scenario, *extra]), \
                    patch.object(fast, "privileged") as privileged, \
                    patch.object(fast, "build") as build:
                with self.assertRaises(SystemExit) as error:
                    fast.main()
                self.assertEqual(error.exception.code, 2)
                privileged.assert_not_called()
                build.assert_not_called()
            self.assertIn("MIXED_OPS=65536 requires ordinary mixed-only scenarios",
                          parser_stderr.getvalue())

    def test_host_cpu_boundaries_expose_contention_without_idle_inference(self):
        import importlib.util
        from unittest.mock import patch

        spec = importlib.util.spec_from_file_location("swapz_host_cpu", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        def read_proc(path, **kwargs):
            if str(path) == "/proc/stat":
                return "cpu 100 0 30 100 0 3 2 0 90 0\ncpu0 0\n"
            return "some avg10=0.00 avg60=0.00 avg300=0.00 total=10000\n"

        with patch.object(module.Path, "read_text", read_proc), \
                patch.object(module.os, "sysconf", side_effect=lambda name:
                             {"SC_NPROCESSORS_ONLN": 4, "SC_CLK_TCK": 100}[name]), \
                patch.object(module.os, "sched_getaffinity", return_value={0, 1}), \
                patch.object(module.time, "monotonic_ns", return_value=1000000000):
            before = module.host_cpu_snapshot()
        self.assertEqual(before["ticks"], (100, 0, 30, 100, 0, 3, 2, 0))
        after = {**before, "ticks": (110, 0, 35, 150, 5, 3, 2, 5),
                 "time_ns": 2000000000, "pressure_us": 110000}
        observed = module.host_cpu_delta(before, after)
        self.assertEqual(observed["status"], "AVAILABLE")
        self.assertAlmostEqual(observed["busy_fraction"], 15 / 75)
        self.assertAlmostEqual(observed["steal_fraction"], 5 / 75)
        self.assertAlmostEqual(observed["pressure_some_fraction"], .1)
        self.assertEqual(observed["affinity_cpus"], 2)
        missing_psi = module.host_cpu_delta(before, {**after, "pressure_us": None})
        self.assertEqual(missing_psi["status"], "PARTIAL")
        self.assertIsNone(missing_psi["pressure_some_fraction"])
        for invalid in (None, before, {**after, "online_cpus": 8},
                        {**after, "ticks": (99, 0, 30, 100, 0, 3, 2, 0)}):
            self.assertEqual(module.host_cpu_delta(before, invalid)["status"],
                             "UNAVAILABLE")

    def require_native_tool(self, target, scenario):
        # The source-contract job invokes this suite on an unbuilt checkout.
        # Only the required native leaf target is compiled; no sudo or root make.
        executable = ROOT / "build/tests/native" / target
        context = (f"phase=native-build scenario={scenario} "
                   f"candidate=off/swapz target={target}")
        try:
            build = subprocess.run(
                ["make", "-s", "--no-print-directory", "-C",
                 str(ROOT / "tests/suites"), str(executable)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, timeout=60)
        except subprocess.TimeoutExpired:
            self.fail(f"{context} invariant=build-timeout seconds=60 "
                      "reason=native leaf build did not finish")
        except OSError as error:
            reason = " ".join(str(error).split())[:256] or type(error).__name__
            self.fail(f"{context} invariant=build-launch errno={error.errno} "
                      f"reason={reason}")
        build_reason = " ".join((build.stderr or "").split())
        build_reason = build_reason.replace(str(ROOT), "<repo>")
        build_reason = build_reason[:512] or "make exited without diagnostic stderr"
        self.assertEqual(
            build.returncode, 0,
            f"{context} invariant=build-exit-status exit_status={build.returncode} "
            f"reason={build_reason}")
        self.assertTrue(
            executable.is_file() and os.access(executable, os.X_OK),
            f"{context} invariant=executable-native-tool "
            "reason=make returned success without an executable")
        return executable

    def run_cmd(self, *args, success=True, scenario=None):
        phase = str(args[0])
        candidate = (str(args[args.index("--candidate") + 1])
                     if "--candidate" in args else
                     "off/swapz" if phase == "compare" else "none")
        context = (f"phase={phase} scenario={scenario or self._testMethodName} "
                   f"candidate={candidate}")
        try:
            run = subprocess.run(
                [sys.executable, str(SCRIPT), *map(str, args)],
                capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            self.fail(f"{context} invariant=command-timeout seconds=30 "
                      "reason=replay subprocess did not finish")
        if success and run.returncode:
            self.fail(f"{context} invariant=command-exit-status "
                      f"exit_status={run.returncode} "
                      "reason=replay subprocess failed (private child output withheld)")
        if not success:
            self.assertNotEqual(
                run.returncode, 0,
                f"{context} invariant=expected-rejection exit_status=0 "
                "reason=invalid replay input accepted")
        return run

    def test_four_mib_verified_fixed_volume_read_rootless(self):
        # Identical direct replay path and oracle, but WITHOUT any real
        # Device Mapper loaded or claims about kernel packed extents.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = root / "fixture.bin"
            fixture.write_bytes(b"".join(bytes([i + 1]) * PAGE
                                         for i in range(32)))
            plan = root / "plan"
            self.run_cmd("prepare", "--fixture", fixture,
                         "--output-dir", plan, "--logical-pages", 1024,
                         "--writer-pages", 256, "--reader-start", 512,
                         "--reader-pages", 256, "--qd", 32,
                         "--warmup-ops", 32, "--measure-ops", 64,
                         "--read-pct", 25, "--iops", 0)
            reports = []
            for candidate in ("off", "swapz"):
                device = root / f"swapz-replay-{candidate}.bin"
                with device.open("wb") as fd:
                    fd.truncate(1024 * PAGE)
                result = root / f"{candidate}.json"
                packed_mode = (["--allocation-bounded-packed-read"]
                               if candidate == "swapz" else [])
                run = self.run_cmd("run", "--fixture", fixture,
                                   "--trace", plan / "trace.jsonl",
                                   "--manifest", plan / "manifest.json",
                                   "--device", device, "--candidate", candidate,
                                   "--source-sha", "rootless-no-module",
                                   "--regular-file-test", "--packed-read",
                                   *packed_mode, "--result", result)
                for subphase in ("prefill", "mixed", "packed_read"):
                    self.assertIn(f"BENCH_IO_PHASE={candidate}:{subphase}",
                                  run.stderr)
                record = json.loads(result.read_text())
                self.assertIn(record["host_cpu"]["status"],
                              ("AVAILABLE", "PARTIAL", "UNAVAILABLE"))
                read = record["packed_read"]
                self.assertIn("executor startup", record["mixed_timed_scope"])
                self.assertEqual(read["qualification"], "ROOTLESS_NO_PACK_PROOF")
                self.assertEqual(read["logical_bytes"], 4194304)
                self.assertIsNone(read["packed_close_delta"])
                for mode in ("sequential", "seeded_random"):
                    phase = read["passes"][mode]
                    self.assertEqual(phase["logical_bytes"], 4194304)
                    self.assertEqual(phase["verified_pages"], 1024)
                    self.assertEqual(phase["verified_image_sha256"],
                                     read["logical_image_sha256"])
                    self.assertGreater(phase["seconds"], 0)
                    self.assertIsNone(phase["kernel_read_path"])
                    self.assertIn("buffers and worker setup excluded", phase["timed_scope"])
                    if candidate == "swapz":
                        self.assertIn("allocation-bounded ID36 path",
                                      phase["timed_scope"])
                    else:
                        self.assertNotIn("allocation-bounded ID36 path",
                                         phase["timed_scope"])
                    self.assertGreater(phase["useful_read_mbps"], 0)
                    self.assertGreaterEqual(phase["replay_cpu_user_s"], 0)
                    self.assertIn(phase["host_cpu"]["status"],
                                  ("AVAILABLE", "PARTIAL", "UNAVAILABLE"))
                reports.append(result)
            self.run_cmd("compare", "--reports", *reports)
            wrong = json.loads(reports[0].read_text())
            wrong["packed_read"]["passes"]["sequential"]["verified_pages"] = 100
            reports[0].write_text(json.dumps(wrong))
            self.run_cmd("compare", "--reports", *reports, success=False)

    def test_timed_swapz_read_counters_fail_closed_and_skip_rootless(self):
        import importlib.util
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location("swapz_read_metrics", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertIsNone(module.kernel_read_snapshot(
            Path("/tmp/not-used"), {"dm_uuid": None}))
        self.assertIsNone(module.kernel_read_delta(None, None))
        fields = module.KERNEL_READ_FIELDS
        before = {field: 0 for field in fields}
        before.update({
            "read_meta_reqs": 10,
            "read_payload_reqs": 4,
            "read_payload_blocks": 5,
            "lower_read_wall_ns": 3000,
            "decode_wall_ns": 100,
            "read_copy_wall_ns": 50,
            "read_copy_bytes": 4096,
            "read_engine_nonio_wall_ns": 200,
            "read_meta_cache_hits": 2,
            "read_meta_lru_hits": 1,
            "read_meta_set_lookups": 10,
            "read_meta_set_hits": 2,
            "read_meta_primary_hits": 1,
            "read_meta_secondary_hits": 1,
            "read_meta_set_probes": 72,
            "read_meta_set_replacements": 0,
            "read_meta_copy_bytes": 0,
            "read_full_extent_reqs": 1,
            "read_full_cache_hits": 1,
            "read_worker_cpu_ns": 1000,
        })
        after = dict(before)
        after.update({
            "read_meta_reqs": 1034,
            "read_payload_reqs": 516,
            "read_payload_blocks": 517,
            "lower_read_wall_ns": 90000000,
            "decode_wall_ns": 3000000,
            "read_copy_wall_ns": 100050,
            "read_copy_bytes": 4198400,
            "read_engine_nonio_wall_ns": 500200,
            "read_meta_cache_hits": 402,
            "read_meta_lru_hits": 102,
            "read_meta_set_lookups": 1034,
            "read_meta_set_hits": 202,
            "read_meta_primary_hits": 151,
            "read_meta_secondary_hits": 51,
            "read_meta_set_probes": 7272,
            "read_meta_set_replacements": 50,
            "read_meta_copy_bytes": 207200,
            "read_full_extent_reqs": 321,
            "read_full_cache_hits": 201,
            "read_two_block_skips": 200,
            "parallel_read_pairs": 8,
            "parallel_read_same_extent_pairs": 3,
            "parallel_read_async_batches": 2,
            "parallel_read_async_slots": 5,
            "parallel_read_distinct_extent_pairs": 5,
            "parallel_read_adjacent_extent_pairs": 2,
            "parallel_read_adjacent_extent_blocks": 12,
            "parallel_read_adjacent_chain_3plus": 2,
            "parallel_read_adjacent_chain_extent_max": 3,
            "parallel_read_adjacent_chain_blocks_max": 4,
            "parallel_read_coalesced_pairs": 2,
            "parallel_read_coalesced_reqs_saved": 4,
            "parallel_read_coalesced_blocks": 6,
            "parallel_read_coalesce_extra_blocks": 0,
            "parallel_read_coalesce_skip_cached": 3,
            "parallel_read_coalesce_skip_noncontig_slot": 4,
            "parallel_read_coalesce_skip_gap": 5,
            "parallel_read_coalesce_skip_other": 0,
            "read_worker_cpu_ns": 101000,
        })
        result = subprocess.CompletedProcess(
            ["dmsetup"], 0, stdout="0 8192 swapz " +
            " ".join(f"{key}={value}" for key, value in before.items()))
        with patch.object(module.subprocess, "run", return_value=result):
            self.assertEqual(module.kernel_read_snapshot(
                Path("/dev/mapper/owned"), {"dm_uuid": "SWAPZ-TEST"}), before)
        measured = module.kernel_read_delta(before, after)
        self.assertEqual(measured["read_meta_reqs"], 1024)
        self.assertEqual(measured["read_payload_reqs"], 512)
        self.assertEqual(measured["read_payload_blocks"], 512)
        self.assertEqual(measured["read_copy_wall_ns"], 100000)
        self.assertEqual(measured["read_copy_bytes"], 4194304)
        self.assertEqual(measured["read_engine_nonio_wall_ns"], 500000)
        self.assertEqual(measured["read_meta_cache_hits"], 400)
        self.assertEqual(measured["read_meta_lru_hits"], 101)
        self.assertEqual(measured["read_meta_set_lookups"], 1024)
        self.assertEqual(measured["read_meta_set_hits"], 200)
        self.assertEqual(measured["read_meta_primary_hits"], 150)
        self.assertEqual(measured["read_meta_secondary_hits"], 50)
        self.assertEqual(measured["read_meta_set_probes"], 7200)
        self.assertEqual(measured["read_meta_set_replacements"], 50)
        self.assertEqual(measured["read_meta_copy_bytes"], 207200)
        self.assertEqual(measured["read_full_extent_reqs"], 320)
        self.assertEqual(measured["read_full_cache_hits"], 200)
        self.assertEqual(measured["read_two_block_skips"], 200)
        self.assertEqual(measured["parallel_read_pairs"], 8)
        self.assertEqual(measured["parallel_read_same_extent_pairs"], 3)
        self.assertEqual(measured["parallel_read_async_batches"], 2)
        self.assertEqual(measured["parallel_read_async_slots"], 5)
        self.assertEqual(measured["parallel_read_distinct_extent_pairs"], 5)
        self.assertEqual(measured["parallel_read_adjacent_extent_pairs"], 2)
        self.assertEqual(measured["parallel_read_adjacent_extent_blocks"], 12)
        self.assertEqual(measured["parallel_read_adjacent_chain_3plus"], 2)
        self.assertEqual(measured["parallel_read_adjacent_chain_extent_max"], 3)
        self.assertEqual(measured["parallel_read_adjacent_chain_blocks_max"], 4)
        self.assertEqual(measured["parallel_read_coalesced_pairs"], 2)
        self.assertEqual(measured["parallel_read_coalesced_reqs_saved"], 4)
        self.assertEqual(measured["parallel_read_coalesced_blocks"], 6)
        self.assertEqual(measured["parallel_read_coalesce_extra_blocks"], 0)
        self.assertEqual(measured["parallel_read_coalesce_skip_cached"], 3)
        self.assertEqual(
            measured["parallel_read_coalesce_skip_noncontig_slot"], 4)
        self.assertEqual(measured["parallel_read_coalesce_skip_gap"], 5)
        self.assertEqual(measured["parallel_read_coalesce_skip_other"], 0)
        self.assertEqual(measured["read_worker_cpu_ns"], 100000)
        # A high reuse rate may make metadata requests fewer than payload
        # requests; this is valid as long as lower payload blocks match.
        self.assertEqual(module.kernel_read_delta(
            before, dict(after, read_meta_reqs=11,
                         read_full_extent_reqs=1,
                         read_two_block_skips=0))["read_meta_reqs"], 1)
        with self.assertRaisesRegex(ValueError, "reset"):
            module.kernel_read_delta(after, before)
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            module.kernel_read_delta(before, dict(after, read_payload_blocks=200))
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            module.kernel_read_delta(before, dict(after, read_full_extent_reqs=1100))
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            module.kernel_read_delta(before, dict(after, read_full_cache_hits=500))
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            module.kernel_read_delta(before, dict(after, read_two_block_skips=850))
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            module.kernel_read_delta(before, dict(after, read_meta_set_hits=2000))
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            module.kernel_read_delta(before, dict(after, read_meta_set_probes=9000))
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            module.kernel_read_delta(
                before,
                dict(after, parallel_read_coalesced_reqs_saved=15))
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            module.kernel_read_delta(before, dict(after, read_meta_secondary_hits=52))
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            module.kernel_read_delta(before, dict(after, read_meta_set_probes=700))
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            module.kernel_read_delta(before, dict(after, read_meta_set_hits=50))
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            module.kernel_read_delta(
                before, dict(after, parallel_read_same_extent_pairs=9))
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            module.kernel_read_delta(
                before, dict(after, parallel_read_adjacent_extent_pairs=6))
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            module.kernel_read_delta(
                before, dict(after, parallel_read_coalesce_extra_blocks=1))

        bad = subprocess.CompletedProcess(["dmsetup"], 0,
                                          stdout="0 8192 swapz read_meta_reqs=4")
        with patch.object(module.subprocess, "run", return_value=bad):
            with self.assertRaisesRegex(ValueError, "missing"):
                module.kernel_read_snapshot(
                    Path("/dev/mapper/owned"), {"dm_uuid": "SWAPZ-TEST"})

    def test_mixed_swapz_write_wait_telemetry_is_time_bracketed_and_fail_closed(self):
        import importlib.util
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location("swapz_write_metrics", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertIsNone(module.kernel_write_snapshot(
            Path("/tmp/not-used"), {"dm_uuid": None}))
        self.assertIsNone(module.kernel_write_delta(None, None))
        before = {key: 0 for key in module.KERNEL_WRITE_FIELDS}
        before.update({
            "physical_write_reqs": 2,
            "lz4_acceleration": 1,
            "delta64_lz4_acceleration": 1,
            "write_pipeline_depth": 1,
            "pipeline_active_max": 0,
            "read_coalesce_max_blocks": 8,
            "work_conserving_hand_records": 8,
            "submitter_prepare": 1,
            "submitter_prepare_lanes": 8,
            "submitter_prepare_active": 0,
            "submitter_prepare_active_max": 2,
            "submitter_prepare_claims": 2,
            "submitter_prepare_lane_misses": 1,
            "submitter_prepare_page_misses": 0,
            "submitter_owner_deferrals": 1,
            "submitter_prepare_pages": 2,
            "submitter_prepare_wall_ns": 2000,
            "submitter_prepare_cpu_ns": 1500,
            "submitter_lz4_wall_ns": 800,
            "submitter_copy_wall_ns": 500,
            "submitter_copy_bytes": 8192,
            "submitter_crc_wall_ns": 100,
            "lz4_wall_ns": 900,
            "ordered_lz4_wall_ns": 60,
            "prep_lz4_wall_ns": 40,
            "write_copy_wall_ns": 530,
            "write_copy_bytes": 4096,
            "ordered_write_copy_wall_ns": 20,
            "prep_write_copy_wall_ns": 10,
            "direct_lz4_input_pages": 1,
            "mapped_snapshot_input_pages": 1,
            "window_sort_wall_ns": 20,
            "window_commit_wall_ns": 400,
            "window_commit_nonio_wall_ns": 100,
            "engine_plan_wall_ns": 10,
            "engine_pack_wall_ns": 20,
            "engine_publish_wall_ns": 30,
            "engine_publish_crc_wall_ns": 10,
            "engine_publish_auth_wall_ns": 20,
            "engine_prehashed_records": 1,
            "batch_snapshot_crc_wall_ns": 3,
            "batch_pause_crc_wall_ns": 1,
            "batch_resume_crc_wall_ns": 2,
            "prep_crc_wall_ns": 5,
            "ordered_crc_wall_ns": 7,
            "lower_write_wall_ns": 300,
            "ordered_worker_wall_ns": 400,
            "prep_worker_wall_ns": 40,
            "ordered_worker_cpu_ns": 100,
            "prep_worker_cpu_ns": 20,
            "read_worker_cpu_ns": 10,
            "prep_wait_wall_ns": 10,
            "prep_lower_write_overlap_ns": 20,
            "windows": 1,
            "close_pack_ready": 1,
            "pack_close_tail_target": 1,
            "pack_close_tail_target_le4": 1,
            "pack_close_burst_target": 0,
            "pack_close_service_dry": 0,
            "retained_burst_target": 4,
            "prep_lower_write_samples": 2,
            "prep_lower_write_start_queued": 1,
            "prep_lower_write_start_nonempty": 1,
            "prep_lower_write_end_queued": 0,
            "prep_lower_write_end_nonempty": 0,
            "write_wait_le1ms": 1,
            "write_wait_1to4ms": 1,
        })
        after = dict(before)
        after.update({
            "physical_write_reqs": 7,
            "submitter_prepare_active_max": 4,
            "submitter_prepare_claims": 12,
            "submitter_prepare_lane_misses": 3,
            "submitter_prepare_page_misses": 1,
            "submitter_owner_deferrals": 5,
            "submitter_prepare_pages": 10,
            "submitter_prepare_wall_ns": 12000,
            "submitter_prepare_cpu_ns": 8500,
            "submitter_lz4_wall_ns": 4800,
            "submitter_copy_wall_ns": 2500,
            "submitter_copy_bytes": 40960,
            "submitter_crc_wall_ns": 700,
            "lz4_wall_ns": 54900,
            "ordered_lz4_wall_ns": 30060,
            "prep_lz4_wall_ns": 20040,
            "write_copy_wall_ns": 3530,
            "write_copy_bytes": 40960,
            "ordered_write_copy_wall_ns": 620,
            "prep_write_copy_wall_ns": 410,
            "direct_lz4_input_pages": 5,
            "mapped_snapshot_input_pages": 5,
            "window_sort_wall_ns": 1020,
            "window_commit_wall_ns": 70400,
            "window_commit_nonio_wall_ns": 10100,
            "engine_plan_wall_ns": 1010,
            "engine_pack_wall_ns": 2020,
            "engine_publish_wall_ns": 3030,
            "engine_publish_crc_wall_ns": 1010,
            "engine_publish_auth_wall_ns": 2020,
            "engine_prehashed_records": 101,
            "batch_snapshot_crc_wall_ns": 250003,
            "batch_pause_crc_wall_ns": 100001,
            "batch_resume_crc_wall_ns": 150002,
            "prep_crc_wall_ns": 505,
            "ordered_crc_wall_ns": 707,
            "lower_write_wall_ns": 60300,
            "ordered_worker_wall_ns": 70400,
            "prep_worker_wall_ns": 4040,
            "ordered_worker_cpu_ns": 30100,
            "prep_worker_cpu_ns": 2020,
            "read_worker_cpu_ns": 1010,
            "prep_wait_wall_ns": 510,
            "prep_lower_write_overlap_ns": 5020,
            "pipeline_read_bypass_skips": 4,
            "pipeline_finalize_wait_wall_ns": 9000,
            "k1_ready_wait_windows": 1,
            "k1_ready_wait_records": 8,
            "k1_ready_wait_wall_ns": 7000,
            "k1_ready_wait_max_records": 8,
            "k1_ready_wait_pack_ready": 1,
            "windows": 4,
            "close_pack_ready": 4,
            "pack_close_tail_target": 2,
            "pack_close_tail_target_le4": 2,
            "pack_close_burst_target": 1,
            "pack_close_service_dry": 1,
            "pack_close_burst_admission": 1,
            "pack_close_burst_worker": 0,
            "pack_close_burst_target_5_8": 1,
            "pack_close_burst_count_5_8": 1,
            "pack_close_burst_overshoot": 0,
            "pack_tail_samples": 3,
            "pack_tail_zero_inflight": 1,
            "pack_tail_zero_idle": 1,
            "pack_tail_many_idle": 1,
            "burst_target_grows": 1,
            "burst_target_shrinks": 1,
            "burst_shrink_inflight_zero_skips": 2,
            "burst_shrink_after_inflight_zero": 1,
            "burst_shrink_after_read_bypass": 0,
            "burst_shrink_other": 0,
            "burst_shrink_target_le8": 1,
            "burst_shrink_target_9_32": 0,
            "burst_shrink_target_gt32": 0,
            "packed_early_commits": 2,
            "retained_burst_target": 8,
            "prep_lower_write_samples": 7,
            "prep_lower_write_start_queued": 5,
            "prep_lower_write_start_nonempty": 4,
            "prep_lower_write_end_queued": 2,
            "prep_lower_write_end_nonempty": 2,
            "write_wait_le1ms": 3,
            "write_wait_1to4ms": 3,
            "write_wait_gt4ms": 1,
            "single_tail_deferrals": 4,
            "single_tail_companions": 2,
            "win1_deadline_deferred_tail": 0,
            "win1_idle_deferred_tail": 0,
            "single_tail_other_clears": 2,
            "single_tail_comp_age_le250us": 1,
            "single_tail_comp_age_251_500us": 1,
            "single_tail_comp_age_501_1000us": 0,
            "single_tail_comp_age_gt1000us": 0,
            "single_tail_deadline_age_le250us": 0,
            "single_tail_deadline_age_251_500us": 0,
            "single_tail_deadline_age_501_1000us": 0,
            "single_tail_deadline_age_gt1000us": 0,
            "single_tail_comp_after_lower_done": 1,
            "single_tail_comp_after_read_bypass": 1,
            "single_tail_comp_after_both": 1,
            "single_tail_deadline_after_lower_done": 0,
            "single_tail_deadline_after_read_bypass": 0,
            "single_tail_deadline_after_both": 0,
        })
        fake = subprocess.CompletedProcess(
            ["dmsetup"], 0, stdout="0 8192 swapz " +
            " ".join(f"{key}={value}" for key, value in before.items()))
        with patch.object(module.subprocess, "run", return_value=fake):
            self.assertEqual(module.kernel_write_snapshot(
                Path("/dev/mapper/owned"), {"dm_uuid": "SWAPZ-TEST"}), before)
        after.update({
            "delta64_eligible": 10, "delta64_classifier_pass": 5,
            "delta64_attempts": 5, "delta64_adopted": 4,
            "delta64_direct_adopted": 1, "delta64_first_lz4_skipped": 1,
            "delta64_raw_rescues": 1, "delta64_lz4_rescues": 2,
            "delta64_pack_eligible": 4, "delta64_pack_attempts": 1,
            "delta64_pack_cliff_crossings": 1, "delta64_pack_adopted": 1,
            "delta64_score_0_7": 2, "delta64_score_8_15": 2,
            "delta64_score_16_23": 2, "delta64_score_ge24": 4,
            "delta64_raw_payload_bytes_saved": 1000,
            "delta64_lz4_payload_bytes_saved": 200,
            "delta64_payload_bytes_saved": 1200, "delta64_wall_ns": 50000,
        })
        before["delta64_rescue"] = after["delta64_rescue"] = 1
        delta = module.kernel_write_delta(before, after)
        self.assertEqual(delta["delta64_adopted"], 4)
        self.assertEqual(delta["delta64_direct_adopted"], 1)
        self.assertEqual(delta["delta64_first_lz4_skipped"], 1)
        self.assertEqual(delta["delta64_pack_adopted"], 1)
        self.assertEqual(delta["delta64_pack_cliff_crossings"], 1)
        self.assertEqual(delta["delta64_score_16_23"], 2)
        self.assertEqual(delta["delta64_payload_bytes_saved"], 1200)
        self.assertEqual(delta["submitter_prepare"], 1)
        self.assertEqual(delta["submitter_prepare_lanes"], 8)
        self.assertEqual(delta["submitter_prepare_active"], 0)
        self.assertEqual(delta["submitter_prepare_active_max"], 4)
        self.assertEqual(delta["submitter_prepare_claims"], 10)
        self.assertEqual(delta["submitter_prepare_lane_misses"], 2)
        self.assertEqual(delta["submitter_prepare_page_misses"], 1)
        self.assertEqual(delta["submitter_owner_deferrals"], 4)
        self.assertEqual(delta["submitter_prepare_pages"], 8)
        self.assertEqual(delta["submitter_prepare_wall_ns"], 10000)
        self.assertEqual(delta["submitter_prepare_cpu_ns"], 7000)
        self.assertEqual(delta["submitter_lz4_wall_ns"], 4000)
        self.assertEqual(delta["submitter_copy_wall_ns"], 2000)
        self.assertEqual(delta["submitter_copy_bytes"], 32768)
        self.assertEqual(delta["submitter_crc_wall_ns"], 600)
        disabled_before = dict(before, delta64_rescue=0)
        disabled_after = dict(after, delta64_rescue=0,
                              **{field: 0 for field in module.DELTA64_FIELDS})
        self.assertEqual(module.kernel_write_delta(
            disabled_before, disabled_after)["delta64_rescue"], 0)
        for invalid, message in (
                ({"submitter_prepare": 0}, "policy"),
                ({"submitter_prepare_lanes": 9}, "lanes"),
                ({"submitter_prepare_active": 1}, "measurement boundary"),
                ({"submitter_prepare_active_max": 9}, "concurrency"),
                ({"submitter_prepare_pages": 13}, "claims"),
                ({"submitter_copy_bytes": 40961}, "copy bytes"),
                ({"submitter_prepare_wall_ns": 4000}, "timing")):
            with self.subTest(submitter=invalid):
                with self.assertRaisesRegex(ValueError, message):
                    module.kernel_write_delta(before, dict(after, **invalid))
        submitter_disabled_before = {
            **before,
            "submitter_prepare": 0,
            "submitter_prepare_lanes": 0,
            "submitter_prepare_active_max": 0,
            **{field: 0 for field in (
                "submitter_prepare_claims", "submitter_prepare_lane_misses",
                "submitter_prepare_page_misses", "submitter_owner_deferrals",
                "submitter_prepare_pages", "submitter_prepare_wall_ns",
                "submitter_prepare_cpu_ns", "submitter_lz4_wall_ns",
                "submitter_copy_wall_ns", "submitter_copy_bytes",
                "submitter_crc_wall_ns")},
        }
        submitter_disabled_after = dict(submitter_disabled_before)
        with self.assertRaisesRegex(ValueError, "disabled.*submitter"):
            module.kernel_write_delta(
                submitter_disabled_before,
                dict(submitter_disabled_after, submitter_prepare_claims=1))
        for selected in (16, 64):
            before_hand = dict(submitter_disabled_before,
                               work_conserving_hand_records=selected)
            hand_delta = module.kernel_write_delta(before_hand, before_hand)
            self.assertEqual(hand_delta["work_conserving_hand_records"], selected)
        for selected in (0, 9, 65):
            with self.assertRaisesRegex(ValueError, "hand threshold"):
                module.kernel_write_delta(
                    dict(submitter_disabled_before,
                         work_conserving_hand_records=selected),
                    dict(submitter_disabled_before,
                         work_conserving_hand_records=selected))
        with self.assertRaisesRegex(ValueError, "hand threshold"):
            module.kernel_write_delta(
                submitter_disabled_before,
                dict(submitter_disabled_before,
                     work_conserving_hand_records=16))
        with self.assertRaisesRegex(ValueError, "disabled.*delta64"):
            module.kernel_write_delta(disabled_before,
                                      dict(disabled_after, delta64_wall_ns=1))
        for invalid in (
                {"delta64_rescue": 0}, {"delta64_rescue": 2},
                {"delta64_classifier_pass": 11},
                {"delta64_attempts": 6},
                {"delta64_adopted": 6},
                {"delta64_direct_adopted": 2},
                {"delta64_first_lz4_skipped": 0},
                {"delta64_raw_rescues": 2},
                {"delta64_payload_bytes_saved": 1201},
                {"delta64_raw_payload_bytes_saved": 527,
                 "delta64_payload_bytes_saved": 727},
                {"delta64_raw_payload_bytes_saved": 4096,
                 "delta64_payload_bytes_saved": 4296},
                {"delta64_lz4_payload_bytes_saved": 1,
                 "delta64_payload_bytes_saved": 1001},
                {"delta64_lz4_payload_bytes_saved": 7135,
                 "delta64_payload_bytes_saved": 8135},
                {"delta64_pack_attempts": 5},
                {"delta64_pack_adopted": 2},
                {"delta64_pack_cliff_crossings": 6},
                {"delta64_score_0_7": 3},
                {"delta64_score_ge24": 6}):
            with self.subTest(delta64=invalid), self.assertRaisesRegex(ValueError, "delta64"):
                module.kernel_write_delta(before, dict(after, **invalid))
        # Missing fields must not silently become zero-use evidence.
        missing = dict(before)
        del missing["delta64_adopted"]
        fake.stdout = "0 8192 swapz " + " ".join(
            f"{key}={value}" for key, value in missing.items())
        with patch.object(module.subprocess, "run", return_value=fake), \
                self.assertRaisesRegex(ValueError, "missing delta64_adopted"):
            module.kernel_write_snapshot(
                Path("/dev/mapper/owned"), {"dm_uuid": "SWAPZ-TEST"})
        self.assertEqual(delta["physical_write_reqs"], 5)
        self.assertEqual([delta[key] for key in module.WRITE_WAIT_BINS],
                         [2, 2, 1])
        self.assertEqual(delta["write_copy_wall_ns"], 3000)
        self.assertEqual(delta["write_copy_bytes"], 36864)
        self.assertEqual(delta["lz4_wall_ns"], 54000)
        self.assertEqual(delta["ordered_lz4_wall_ns"], 30000)
        self.assertEqual(delta["prep_lz4_wall_ns"], 20000)
        self.assertEqual(delta["ordered_write_copy_wall_ns"], 600)
        self.assertEqual(delta["prep_write_copy_wall_ns"], 400)
        self.assertEqual(delta["direct_lz4_input_pages"], 4)
        self.assertEqual(delta["mapped_snapshot_input_pages"], 4)
        self.assertEqual(delta["window_commit_nonio_wall_ns"], 10000)
        self.assertEqual(delta["engine_plan_wall_ns"], 1000)
        self.assertEqual(delta["engine_pack_wall_ns"], 2000)
        self.assertEqual(delta["engine_publish_wall_ns"], 3000)
        self.assertEqual(delta["lower_write_wall_ns"], 60000)
        self.assertEqual(delta["ordered_worker_wall_ns"], 70000)
        self.assertEqual(delta["prep_worker_wall_ns"], 4000)
        self.assertEqual(delta["ordered_worker_cpu_ns"], 30000)
        self.assertEqual(delta["prep_worker_cpu_ns"], 2000)
        self.assertEqual(delta["read_worker_cpu_ns"], 1000)
        self.assertEqual(delta["engine_prehashed_records"], 100)
        self.assertEqual(delta["batch_snapshot_crc_wall_ns"], 250000)
        self.assertEqual(delta["batch_pause_crc_wall_ns"], 100000)
        self.assertEqual(delta["batch_resume_crc_wall_ns"], 150000)
        self.assertEqual(delta["retained_burst_target"], 8)
        self.assertEqual(delta["windows"], 3)
        self.assertEqual(delta["close_pack_ready"], 3)
        self.assertEqual(delta["pack_close_tail_target"], 1)
        self.assertEqual(delta["pack_close_tail_target_le4"], 1)
        self.assertEqual(delta["pack_close_burst_target"], 1)
        self.assertEqual(delta["pack_close_service_dry"], 1)
        self.assertEqual(delta["pack_close_burst_admission"], 1)
        self.assertEqual(delta["pack_close_burst_worker"], 0)
        self.assertEqual(delta["pack_close_burst_target_5_8"], 1)
        self.assertEqual(delta["pack_close_burst_count_5_8"], 1)
        self.assertEqual(delta["pack_tail_samples"], 3)
        self.assertEqual(delta["pack_tail_zero_inflight"], 1)
        self.assertEqual(delta["pack_tail_zero_idle"], 1)
        self.assertEqual(delta["pack_tail_many_idle"], 1)
        self.assertEqual(delta["burst_target_grows"], 1)
        self.assertEqual(delta["burst_target_shrinks"], 1)
        self.assertEqual(delta["burst_shrink_inflight_zero_skips"], 2)
        self.assertEqual(delta["burst_shrink_after_inflight_zero"], 1)
        self.assertEqual(delta["burst_shrink_after_read_bypass"], 0)
        self.assertEqual(delta["burst_shrink_other"], 0)
        self.assertEqual(delta["burst_shrink_target_le8"], 1)
        self.assertEqual(delta["burst_shrink_target_9_32"], 0)
        self.assertEqual(delta["burst_shrink_target_gt32"], 0)
        self.assertEqual(delta["prep_crc_wall_ns"], 500)
        self.assertEqual(delta["ordered_crc_wall_ns"], 700)
        self.assertEqual(delta["engine_publish_crc_wall_ns"], 1000)
        self.assertEqual(delta["engine_publish_auth_wall_ns"], 2000)
        self.assertEqual(delta["prep_lower_write_samples"], 5)
        self.assertEqual(delta["prep_lower_write_start_queued"], 4)
        self.assertEqual(delta["prep_lower_write_start_nonempty"], 3)
        self.assertEqual(delta["prep_lower_write_end_queued"], 2)
        self.assertEqual(delta["prep_lower_write_end_nonempty"], 2)
        self.assertEqual(delta["prep_wait_wall_ns"], 500)
        self.assertEqual(delta["prep_lower_write_overlap_ns"], 5000)
        self.assertEqual(delta["pipeline_read_bypass_skips"], 4)
        self.assertEqual(delta["pipeline_finalize_wait_wall_ns"], 9000)
        self.assertEqual(delta["k1_ready_wait_windows"], 1)
        self.assertEqual(delta["k1_ready_wait_records"], 8)
        self.assertEqual(delta["k1_ready_wait_wall_ns"], 7000)
        self.assertEqual(delta["k1_ready_wait_pack_ready"], 1)
        self.assertEqual(delta["single_tail_deferrals"], 4)
        self.assertEqual(delta["single_tail_companions"], 2)
        self.assertEqual(delta["single_tail_other_clears"], 2)
        self.assertEqual(delta["single_tail_comp_age_le250us"], 1)
        self.assertEqual(delta["single_tail_comp_age_251_500us"], 1)
        self.assertEqual(delta["single_tail_comp_after_both"], 1)

        with self.assertRaisesRegex(ValueError, "reset"):
            module.kernel_write_delta(after, before)
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            module.kernel_write_delta(
                before, dict(after, write_wait_gt4ms=2))
        with self.assertRaisesRegex(ValueError, "non-I/O"):
            module.kernel_write_delta(
                before, dict(after, window_commit_nonio_wall_ns=80000))
        with self.assertRaisesRegex(ValueError, "engine phase"):
            module.kernel_write_delta(
                before, dict(after, engine_publish_wall_ns=15000))
        with self.assertRaisesRegex(ValueError, "publish attribution"):
            module.kernel_write_delta(
                before, dict(after, engine_publish_crc_wall_ns=2011))
        with self.assertRaisesRegex(ValueError, "snapshot CRC"):
            module.kernel_write_delta(
                before, dict(after, batch_resume_crc_wall_ns=150003))
        with self.assertRaisesRegex(ValueError, "queue attribution"):
            module.kernel_write_delta(
                before, dict(after, prep_lower_write_start_nonempty=8))
        with self.assertRaisesRegex(ValueError, "deferred singleton"):
            module.kernel_write_delta(
                before, dict(after, single_tail_companions=1))
        with self.assertRaisesRegex(ValueError, "deferred singleton"):
            module.kernel_write_delta(
                before, dict(after, win1_deadline_deferred_tail=2))
        with self.assertRaisesRegex(ValueError, "companion age"):
            module.kernel_write_delta(
                before, dict(after, single_tail_comp_age_le250us=2))
        with self.assertRaisesRegex(ValueError, "service attribution"):
            module.kernel_write_delta(
                before, dict(after, single_tail_comp_after_both=2))
        with self.assertRaisesRegex(ValueError, "PACK_READY"):
            module.kernel_write_delta(
                before, dict(after, pack_close_burst_target=2))
        with self.assertRaisesRegex(ValueError, "burst-target"):
            module.kernel_write_delta(
                before, dict(after, pack_close_burst_worker=1))
        with self.assertRaisesRegex(ValueError, "tail-sample"):
            module.kernel_write_delta(
                before, dict(after, pack_tail_zero_idle=2))
        with self.assertRaisesRegex(ValueError, "burst-shrink"):
            module.kernel_write_delta(
                before, dict(after, burst_shrink_after_inflight_zero=0))
        with self.assertRaisesRegex(ValueError, "K=1/post-lower"):
            module.kernel_write_delta(
                before, dict(after, k1_ready_wait_full=2))
        with self.assertRaisesRegex(ValueError, "upper-tail"):
            module.kernel_write_delta(
                before, dict(after, single_tail_comp_age_251_500us=0,
                             single_tail_comp_age_gt1000us=1))
        with self.assertRaisesRegex(ValueError, "retained burst target"):
            module.kernel_write_delta(
                before, dict(after, retained_burst_target=0))
        with self.assertRaisesRegex(ValueError, "READ coalescing cap"):
            module.kernel_write_delta(
                before, dict(after, read_coalesce_max_blocks=4))
        with self.assertRaisesRegex(ValueError, "close-reason"):
            module.kernel_write_delta(
                before, dict(after, close_idle=1))
        with self.assertRaisesRegex(ValueError, "incomplete"):
            module.kernel_write_delta(None, after)
        with patch.object(module.subprocess, "run",
                          return_value=subprocess.CompletedProcess(
                              ["dmsetup"], 0, stdout="0 8192 swapz physical_write_reqs=1")):
            with self.assertRaisesRegex(ValueError, "missing"):
                module.kernel_write_snapshot(
                    Path("/dev/mapper/owned"), {"dm_uuid": "SWAPZ-TEST"})

    def test_pair_exact_bytes_and_ordered_wave_oracle(self):
        for layout in ("disjoint", "same-region"):
            with self.subTest(layout=layout), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                fixture = root / "fixture.bin"
                rng = random.Random(119)
                pages = [
                    bytes([index]) * PAGE if index % 3 != 1
                    else rng.randbytes(PAGE) for index in range(16)
                ]
                fixture.write_bytes(b"".join(pages))
                plan = root / "plan"
                reader_start = 32 if layout == "disjoint" else 0
                self.run_cmd("prepare", "--fixture", fixture,
                             "--output-dir", plan, "--seed", "0xfeed123",
                             "--logical-pages", 64, "--writer-pages", 16,
                             "--reader-start", reader_start,
                             "--reader-pages", 16, "--layout", layout,
                             "--qd", 4, "--read-pct", 50,
                             "--warmup-ops", 32, "--measure-ops", 128,
                             "--iops", 0)
                manifest = json.loads((plan / "manifest.json").read_text())
                self.assertEqual(manifest["fixture_pages"], 16)
                self.assertEqual(manifest["measure_ops"], 128)
                opportunity = manifest["workload_opportunity"]
                self.assertEqual(
                    opportunity["scope"],
                    "TRACE_FIXTURE_OPPORTUNITY_ONLY_NOT_KERNEL_SAVINGS")
                self.assertGreater(opportunity["measured_write_ops"], 0)
                self.assertGreaterEqual(
                    opportunity["measured_unique_write_payloads"], 1)
                reports = []
                for candidate in ("off", "swapz"):
                    path = root / f"swapz-replay-{candidate}.bin"
                    with path.open("wb") as handle:
                        handle.truncate(64 * PAGE)
                    out = root / f"{candidate}.json"
                    self.run_cmd("run", "--fixture", fixture,
                                 "--trace", plan / "trace.jsonl",
                                 "--manifest", plan / "manifest.json",
                                 "--candidate", candidate,
                                 "--source-sha", "rootless-test-not-a-module",
                                 "--device", path,
                                 "--result", out, "--regular-file-test")
                    self.assertTrue(out.is_file())
                    reports.append(out)
                compare = self.run_cmd("compare", "--reports", *reports)
                result = json.loads(compare.stdout)
                self.assertEqual(result["verdict"], "PASS_IDENTICAL_LOGICAL_INPUT")
                self.assertEqual(result["fixture_sha256"], manifest["fixture_sha256"])
                self.assertEqual(result["trace_sha256"], manifest["trace_sha256"])
                self.assertEqual(result["workload_opportunity"], opportunity)
                self.assertEqual(len(result["results"]), 2)
                self.assertEqual(result["performance_qualification"],
                                 "ROOTLESS_NOT_DEVICE_EVIDENCE")
                self.assertTrue(all(
                    entry["throughput_mbps"]["lower_write_mbps"] is None
                    for entry in result["results"]
                ))
                expected = manifest["expected_post_sha256"]
                for report_path in reports:
                    record = json.loads(report_path.read_text())
                    self.assertEqual(record["verified_post_sha256"], expected)
                    self.assertEqual(record["write_ops"] + record["read_ops"], 128)
                    self.assertEqual(record["warmup_ops"], 32)
                    self.assertEqual(record["verified_pages"], 64)
                    self.assertEqual(record["verdict"], "PASS")
                    self.assertEqual(record["workload_opportunity"], opportunity)
                    rates = record["throughput_mbps"]
                    self.assertGreater(rates["logical_total_mbps"], 0)
                    self.assertIsNone(rates["lower_write_mbps"])
                    self.assertIsNone(rates["write_input_per_lower_byte"])
                # Fail-closed: altered trace provenance makes pair invalid.
                tampered = json.loads(reports[0].read_text())
                tampered["write_payload_stream_sha256"] = "0" * 64
                reports[0].write_text(json.dumps(tampered) + "\n")
                self.run_cmd("compare", "--reports", *reports, success=False)
                # Fail-closed: altered fixture bytes are rejected before I/O.
                fixture.write_bytes(fixture.read_bytes()[:-PAGE] +
                                    b"Z" * PAGE)
                forbidden = root / "swapz-replay-refused.bin"
                with forbidden.open("wb") as handle:
                    handle.truncate(64 * PAGE)
                self.run_cmd("run", "--fixture", fixture,
                             "--trace", plan / "trace.jsonl",
                             "--manifest", plan / "manifest.json",
                             "--candidate", "off",
                             "--source-sha", "rootless-test",
                             "--device", forbidden,
                             "--result", root / "refused.json",
                             "--regular-file-test", success=False)
                self.assertFalse((root / "refused.json").exists())

    def test_owned_nullblk_modern_legacy_and_invalid_identities(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("swapz_replay", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_root = root / "config"
            block_root = root / "block"
            sysdev_root = root / "devblock"
            config_name = "nullb-swapz-0123456789abcdef"
            conf = config_root / config_name
            conf.mkdir(parents=True)
            sysdev_root.mkdir()
            for name, value in (("index", "7"), ("memory_backed", "1"),
                                ("power", "1")):
                (conf / name).write_text(value + "\n")
            proc = root / "devices"
            proc.write_text("Character devices:\n1 mem\nBlock devices:\n251 nullb\n")
            modern = block_root / config_name
            legacy = block_root / "nullb7"
            modern.mkdir(parents=True)
            legacy.mkdir(parents=True)
            (modern / "dev").write_text("251:7\n")
            marker = sysdev_root / "251:7"
            marker.symlink_to(modern, target_is_directory=True)

            def resolve(dev="251:7", name=config_name):
                return mod.resolve_owned_nullblk(
                    name, dev, config_root, block_root, sysdev_root, proc
                )

            self.assertEqual(resolve(), (config_name, "251:7"))
            (legacy / "dev").write_text("251:7\n")
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                resolve()
            (modern / "dev").unlink()
            marker.unlink()
            marker.symlink_to(legacy, target_is_directory=True)
            self.assertEqual(resolve(), ("nullb7", "251:7"))
            with self.assertRaisesRegex(ValueError, "non-owned"):
                resolve(name="nullb_swapz_old")
            with self.assertRaisesRegex(ValueError, "mismatch"):
                resolve(dev="251:8")
            (legacy / "dev").write_text("252:7\n")
            with self.assertRaisesRegex(ValueError, "mismatch"):
                resolve()
            (legacy / "dev").write_text("251:7\n")
            (conf / "memory_backed").write_text("0\n")
            with self.assertRaisesRegex(ValueError, "RAM-backed"):
                resolve()
            (conf / "memory_backed").write_text("1\n")
            (conf / "index").write_text("07\n")
            with self.assertRaisesRegex(ValueError, "index"):
                resolve()
            (conf / "index").write_text("7\n")
            marker.unlink()
            with self.assertRaises((ValueError, FileNotFoundError)):
                resolve()
            (legacy / "dev").unlink()
            with self.assertRaisesRegex(ValueError, "missing"):
                resolve()

    def test_exact_swapz_table_accepts_only_owned_nonfaulting_backing(self):
        import importlib.util
        from unittest.mock import patch
        from types import SimpleNamespace
        spec = importlib.util.spec_from_file_location("swapz_replay_table", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        lower = "251:7"
        name = "nullb-swapz-0123456789abcdef"
        tokens = f"0 32768 swapz {lower} 0 64 0 2 0 1 0 0"
        self.assertEqual(module.validate_swapz_table(tokens, 4096, lower, name)["window"], 64)
        self.assertEqual(module.validate_swapz_table(tokens, 4096, lower, name)["retain_ms"], 0)
        retained = tokens.rsplit(" ", 1)[0] + " 2"
        self.assertEqual(module.validate_swapz_table(
            retained, 4096, lower, name
        )["retain_ms"], 2)
        fake_block = SimpleNamespace(st_mode=__import__("stat").S_IFBLK,
                                     st_rdev=os.makedev(251, 7))
        with patch.object(module.Path, "stat", return_value=fake_block):
            path_table = tokens.replace(lower, "/dev/" + name)
            self.assertEqual(module.validate_swapz_table(
                path_table, 4096, lower, name
            )["lower_bulk"], 1)
        for broken in (
            tokens.replace("251:7", "251:8"),
            tokens.replace("251:7", "/dev/sda1"),
            tokens.replace("32768", "32760"),
            tokens.replace("swapz", "linear"),
            tokens + "\n" + tokens,
            tokens + " 0",
            tokens.rsplit(" ", 1)[0] + " 5",
            tokens.rsplit(" ", 1)[0] + " -1",
            tokens.replace(" 0 64 0 2 0 1 0 0", " 0 64 0 2 1 1 0 0"),
            tokens.replace(" 0 64 0 2 0 1 0 0", " 0 64 0 2 0 1 1 0"),
            tokens.replace(" 0 64 0 2 0 1 0 0", " 0 64 0 2 0 3 0 0"),
        ):
            with self.subTest(table=broken), self.assertRaises(ValueError):
                module.validate_swapz_table(broken, 4096, lower, name)

    def test_loaded_pair_qualification_requires_distinct_backing_and_rate(self):
        import contextlib
        import importlib.util
        import io
        from types import SimpleNamespace
        spec = importlib.util.spec_from_file_location("swapz_replay_pair", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            base = {
                "fixture_sha256": "a" * 64, "trace_sha256": "b" * 64,
                "write_payload_stream_sha256": "c" * 64,
                "prefill_sha256": "d" * 64, "expected_post_sha256": "e" * 64,
                "manifest_sha256": "f" * 64, "qd": 4, "layout": "disjoint",
                "seed": 77, "iops_requested": 200, "warmup_ops": 20,
                "measure_ops": 100, "read_ops": 50, "write_ops": 50,
                "seconds": 1.0,
                "verified_pages": 32, "verified_post_sha256": "e" * 64,
                "verdict": "PASS", "source_sha": "1" * 40,
                "lower_io": {
                    "lower_read_requests": 50, "lower_read_bytes": 204800,
                    "lower_write_requests": 50, "lower_write_bytes": 204800,
                    "lower_flush_requests": 1,
                },
            }
            off = {**base, "candidate": "off", "achieved_iops": 190.0,
                   "device_identity": {"device": "251:0",
                                       "owned_disk": "nullb0",
                                       "lower_major_minor": "251:0",
                                       "dm_uuid": None}}
            swapz = {**base, "candidate": "swapz", "achieved_iops": 188.0,
                  "device_identity": {"device": "253:0",
                                      "owned_disk": "nullb1",
                                      "lower_major_minor": "251:1",
                                      "dm_uuid": "SWZTEST-00001"}}
            paths = [directory / "off.json", directory / "swapz.json"]
            def compare():
                for location, report in zip(paths, (off, swapz)):
                    location.write_text(json.dumps(report))
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    module.compare(SimpleNamespace(reports=paths))
                return json.loads(output.getvalue())
            output = compare()
            self.assertEqual(output["performance_qualification"],
                             "MATCHED_LOAD_MEASUREMENT_ONLY")
            self.assertEqual(output["lower_write_bytes_saved_fraction"], 0)
            for entry in output["results"]:
                rates = entry["throughput_mbps"]
                self.assertAlmostEqual(rates["logical_write_mbps"], 0.2048)
                self.assertAlmostEqual(rates["logical_read_mbps"], 0.2048)
                self.assertAlmostEqual(rates["lower_write_mbps"], 0.2048)
                self.assertAlmostEqual(rates["lower_read_mbps"], 0.2048)
                self.assertEqual(rates["write_input_per_lower_byte"], 1.0)
            swapz["lower_io"] = {**base["lower_io"],
                              "lower_write_bytes": 102400}
            candidate = compare()
            self.assertAlmostEqual(
                candidate["results"][1]["throughput_mbps"]["lower_write_mbps"],
                0.1024
            )
            self.assertAlmostEqual(
                candidate["results"][1]["throughput_mbps"]["write_input_per_lower_byte"],
                2.0
            )
            self.assertAlmostEqual(candidate["lower_write_bytes_saved_fraction"], 0.5)
            swapz["lower_io"] = base["lower_io"]
            off["iops_requested"] = swapz["iops_requested"] = 0
            swapz["achieved_iops"] = 250
            swapz["seconds"] = 0.4
            unpaced = compare()
            self.assertEqual(unpaced["rate_mode"], "unpaced")
            self.assertEqual(unpaced["performance_qualification"],
                             "UNPACED_THROUGHPUT_MEASUREMENT_ONLY")
            self.assertIsNone(unpaced["allowed_iops_difference_fraction"])
            self.assertAlmostEqual(
                unpaced["logical_write_mbps_ratio_swapz_to_off"], 2.5)
            self.assertAlmostEqual(
                unpaced["lower_write_mbps_ratio_swapz_to_off"], 2.5)
            off["iops_requested"] = swapz["iops_requested"] = 500
            swapz["seconds"] = 1.0
            swapz["achieved_iops"] = 120
            self.assertEqual(compare()["performance_qualification"],
                             "INCONCLUSIVE_UNMATCHED_ACHIEVED_LOAD")
            swapz["achieved_iops"] = 188
            swapz["device_identity"]["lower_major_minor"] = "251:0"
            with self.assertRaisesRegex(ValueError, "not independent"):
                compare()
            swapz["device_identity"]["lower_major_minor"] = "251:1"
            swapz["lower_io"] = None
            with self.assertRaisesRegex(ValueError, "missing independent"):
                compare()
            swapz["lower_io"] = base["lower_io"]
            swapz["source_sha"] = "2" * 40
            with self.assertRaisesRegex(ValueError, "revision mismatch"):
                compare()

    def test_workload_opportunity_is_offline_exact_content_evidence(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("swapz_replay_opportunity", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        repeated_a = b"A" * PAGE
        repeated_b = b"B" * PAGE
        varied = bytes(range(256)) * 16
        self.assertTrue(module.nonzero_same_filled_page(repeated_a))
        self.assertFalse(module.nonzero_same_filled_page(b"\x00" * PAGE))
        self.assertFalse(module.nonzero_same_filled_page(varied))
        events = [
            {"op": "W", "phase": "warmup", "page": 0, "fixture": 2},
            {"op": "W", "phase": "measure", "page": 1, "fixture": 0},
            {"op": "W", "phase": "measure", "page": 2, "fixture": 2},
            {"op": "W", "phase": "measure", "page": 3, "fixture": 0},
        ]
        evidence = module.workload_opportunity(
            events, [repeated_a, repeated_b, varied], 4)
        self.assertEqual(evidence["measured_write_ops"], 3)
        self.assertEqual(evidence["measured_unique_write_payloads"], 2)
        self.assertEqual(evidence["nonzero_same_filled_write_ops"], 2)
        self.assertEqual(evidence["same_page_rewrite_ops"], 2)
        self.assertEqual(evidence["resident_duplicate_write_ops"], 3)
        self.assertEqual(evidence["final_live_unique_payloads"], 2)
        self.assertEqual(evidence["final_live_duplicate_pages"], 4)
        self.assertEqual(evidence["final_live_nonzero_same_filled_pages"], 2)
        self.assertIn("NOT_KERNEL_SAVINGS", evidence["scope"])

    def test_throughput_invalid_times_counts_and_lower_sectors_fail_closed(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("swapz_replay_rates", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        report = {
            "seconds": 2.0, "write_ops": 10, "read_ops": 2,
            "measure_ops": 12, "lower_io": {
                "lower_write_bytes": 20480, "lower_read_bytes": 8192,
            },
        }
        rates = module.measured_throughput(report, require_lower=True)
        self.assertAlmostEqual(rates["logical_write_mbps"], 0.02048)
        self.assertAlmostEqual(rates["lower_write_mbps"], 0.01024)
        self.assertAlmostEqual(rates["write_input_per_lower_byte"], 2)
        for seconds in (0, -1, float("nan"), float("inf"), None, True):
            with self.subTest(seconds=seconds):
                with self.assertRaisesRegex(ValueError, "elapsed time"):
                    module.measured_throughput({**report, "seconds": seconds})
        for count in (-1, 1.5, True, None):
            with self.subTest(count=count):
                with self.assertRaisesRegex(ValueError, "logical operations"):
                    module.measured_throughput({**report, "write_ops": count})
        for lower_bytes in (-512, 513, True, None):
            with self.subTest(lower_bytes=lower_bytes):
                with self.assertRaisesRegex(ValueError, "lower sector bytes"):
                    module.measured_throughput({
                        **report, "lower_io": {**report["lower_io"],
                                               "lower_write_bytes": lower_bytes}
                    })
        with self.assertRaisesRegex(ValueError, "independent lower I/O"):
            module.measured_throughput({**report, "lower_io": None},
                                       require_lower=True)
        zero = module.measured_throughput({
            **report, "lower_io": {**report["lower_io"], "lower_write_bytes": 0}
        })
        self.assertIsNone(zero["write_input_per_lower_byte"])

    def test_nonzero_medium_pages_have_measured_lz4_in_2k_range(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "swapz_medium_fixture", SCRIPT.with_name("anon-page-fixture.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            compressor = module.lz4_compressor()
        except RuntimeError as error:
            self.skipTest(str(error))
        content, manifest = module.generate(
            0x51A0A9, 128, module.parse_weights("medium=100"), compressor
        )
        self.assertEqual(len(content), 128 * PAGE)
        self.assertEqual(manifest["profile_pages"], {"medium": 128})
        self.assertEqual(manifest["lz4_size_buckets"], {"2049_3072": 128})
        self.assertEqual(manifest["raw_pages"], 0)
        self.assertGreaterEqual(manifest["lz4_min_accepted_payload_bytes"], 2049)
        self.assertLessEqual(manifest["lz4_max_accepted_payload_bytes"], 2200)
        self.assertLessEqual(
            manifest["lz4_min_accepted_payload_bytes"],
            manifest["lz4_max_accepted_payload_bytes"]
        )
        for index in range(128):
            chunk = content[index * PAGE:(index + 1) * PAGE]
            self.assertNotEqual(chunk, bytes(PAGE))
            actual = module.measure(compressor, chunk)
            self.assertGreaterEqual(actual, 2049)
            self.assertLessEqual(actual, 2200)
        repeat, same_manifest = module.generate(
            0x51A0A9, 128, module.parse_weights("medium=100"), compressor
        )
        self.assertEqual(content, repeat)
        self.assertEqual(manifest, same_manifest)

    def test_owned_swapz_uuid_matches_owned_pair_harness(self):
        self.assertIn('r"SWAPZ-TEST-[a-f0-9]{16}"', SCRIPT.read_text())
        script = SCRIPT.parents[3] / "tests/tools/benchmark-owned-pair.sh"
        self.assertIn('DMUUID="SWAPZ-TEST-$token"', script.read_text())

    def test_protected_regular_file_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bad = root / "not-an-owned-benchmark-file.bin"
            bad.write_bytes(b"\0" * (PAGE * 8))
            # A regular file needs a distinctive name plus an explicit
            # rootless-test opt-in. Arbitrary file paths are never writable.
            sys.path.insert(0, str(SCRIPT.parent))
            import importlib.util
            spec = importlib.util.spec_from_file_location("threeway", SCRIPT)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            class A: pass
            a = A()
            a.device = str(bad)
            a.regular_file_test = True
            with self.assertRaises(ValueError):
                mod.check_device(a, 8)
            a.device = str(root / "swapz-replay-allowed.bin")
            with (root / "swapz-replay-allowed.bin").open("wb") as file:
                file.truncate(8 * PAGE)
            a.regular_file_test = False
            with self.assertRaises(ValueError):
                mod.check_device(a, 8)

    def test_native_replay_preserves_rootless_oracle(self):
        self.require_native_tool("io-replay-native", "qd-waves")
        for mode in ("qd-waves", "persistent-write", "persistent-mixed", "lane-mixed-waves"):
            with self.subTest(mode=mode), \
                    tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                fixture = root / "fixture.bin"
                fixture.write_bytes(b"".join(bytes([i + 1]) * PAGE
                                             for i in range(16)))
                plan = root / "plan"
                prepare = [
                    "prepare", "--fixture", fixture, "--output-dir", plan,
                    "--qd", 4, "--logical-pages", 64, "--writer-pages", 16,
                    "--reader-start", 32, "--reader-pages", 16,
                    "--warmup-ops", 8, "--measure-ops", 32, "--iops", 0,
                    "--read-pct", 0 if mode == "persistent-write" else 50,
                ]
                if mode == "persistent-write":
                    prepare.append("--sustained-write")
                elif mode in ("persistent-mixed", "lane-mixed-waves"):
                    prepare += ["--mixed-lanes", "persistent" if mode == "persistent-mixed" else "waves"]
                self.run_cmd(*prepare, scenario=mode)
                reports = []
                for candidate in ("off", "swapz"):
                    device = root / f"swapz-replay-native-{candidate}.bin"
                    with device.open("wb") as handle:
                        handle.truncate(64 * PAGE)
                    result = root / f"{candidate}.json"
                    self.run_cmd(
                        "run", "--fixture", fixture,
                        "--trace", plan / "trace.jsonl",
                        "--manifest", plan / "manifest.json",
                        "--device", device, "--candidate", candidate,
                        "--source-sha", "rootless-no-module",
                        "--regular-file-test", "--native-replay",
                        "--result", result, scenario=mode)
                    record = json.loads(result.read_text())
                    self.assertEqual(record["replay_engine"], "native-c")
                    self.assertEqual(record["replay_mode"], mode)
                    self.assertEqual(
                        record["verified_post_sha256"],
                        record["expected_post_sha256"],
                        f"phase=native-replay scenario={mode} candidate={candidate} "
                        "invariant=post-image-sha256")
                    self.assertEqual(record["write_ops"] + record["read_ops"], 32)
                    self.assertGreater(record["seconds"], 0)
                    self.assertIn("native", record["mixed_timed_scope"])
                    reports.append(result)
                compared = json.loads(
                    self.run_cmd("compare", "--reports", *reports,
                                 scenario=mode).stdout)
                self.assertEqual(compared["replay_engine"], "native-c")
                self.assertEqual(
                    compared["verdict"], "PASS_IDENTICAL_LOGICAL_INPUT",
                    f"phase=pair-compare scenario={mode} candidate=off/swapz "
                    "invariant=identical-logical-input")

    def test_mixed_lanes_isolate_barrier_and_reject_cross_lane_mutations(self):
        import runpy
        replay = runpy.run_path(str(SCRIPT))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = root / "fixture.bin"
            fixture.write_bytes(b"".join(bytes([i + 1]) * PAGE for i in range(16)))
            plans = []
            for mode in ("waves", "persistent"):
                plan = root / mode
                self.run_cmd("prepare", "--fixture", fixture, "--output-dir", plan,
                             "--qd", 4, "--logical-pages", 64, "--writer-pages", 16,
                             "--reader-start", 32, "--reader-pages", 16,
                             "--warmup-ops", 8, "--measure-ops", 64,
                             "--read-pct", 50, "--iops", 0, "--mixed-lanes", mode)
                plans.append(plan)
            self.assertEqual((plans[0] / "trace.jsonl").read_bytes(),
                             (plans[1] / "trace.jsonl").read_bytes())
            manifests = [json.loads((p / "manifest.json").read_text()) for p in plans]
            for key in ("trace_sha256", "expected_post_sha256", "write_payload_stream_sha256"):
                self.assertEqual(manifests[0][key], manifests[1][key])
            rows, _ = replay["check_plan"](plans[1] / "trace.jsonl", manifests[1], 16)
            self.assertTrue(any(r["op"] == "R" for r in rows))
            self.assertTrue(any(r["op"] == "W" for r in rows))
            for mode in ("persistent-mixed", "lane-mixed-waves"):
                manifest = {**manifests[1], "replay_mode": mode}
                for field, value in (("reader_start", 0), ("layout", "same-region"),
                                     ("iops", 500), ("writer_pages", 15)):
                    with self.assertRaisesRegex(ValueError, "mixed-lane manifest"):
                        replay["check_plan"](plans[1] / "trace.jsonl",
                                             {**manifest, field: value}, 16)
                bad = [dict(row) for row in rows]
                write = next(r for r in bad if r["op"] == "W")
                # Stay within the WRITE region and avoid an in-wave collision,
                # but move the page to another lane's stripe.
                wave_pages = {r["page"] for r in bad if r["wave"] == write["wave"]}
                write["page"] = next(p for p in range(16)
                                     if p % 4 != write["lane"] and p not in wave_pages)
                data = "".join(json.dumps(r) + "\n" for r in bad).encode()
                bad_path = root / "bad.jsonl"
                bad_path.write_bytes(data)
                with self.assertRaisesRegex(ValueError, "mixed-lane ownership"):
                    replay["check_plan"](bad_path, {**manifest, "trace_sha256": replay["sha"](data)}, 16)

    def test_stripe_partitionable_mixed_plan_and_prefill_mapping(self):
        import runpy
        replay = runpy.run_path(str(SCRIPT))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = root / "fixture.bin"
            fixture.write_bytes(b"".join(bytes([i + 1]) * PAGE for i in range(16)))
            plan = root / "plan"
            self.run_cmd(
                "prepare", "--fixture", fixture, "--output-dir", plan,
                "--qd", 4, "--logical-pages", 64, "--writer-pages", 16,
                "--reader-start", 32, "--reader-pages", 16,
                "--warmup-ops", 8, "--measure-ops", 32, "--read-pct", 50,
                "--iops", 0, "--mixed-lanes", "persistent",
                "--stripe-partitionable")
            manifest = json.loads((plan / "manifest.json").read_text())
            rows = [json.loads(line) for line in
                    (plan / "trace.jsonl").read_text().splitlines()]
            self.assertTrue(manifest["stripe_partitionable"])
            self.assertTrue(all(row["page"] % 4 == row["lane"] for row in rows))
            child = {**manifest, "prefill_fixture_stride": 2,
                     "prefill_fixture_offset": 1}
            self.assertEqual(replay["prefill_fixture_index"](child, 3, 16), 7)
            child["prefill_fixture_offset"] = 2
            with self.assertRaisesRegex(ValueError, "striped prefill"):
                replay["prefill_fixture_index"](child, 3, 16)

    def test_external_start_gate_uses_private_owned_directory(self):
        import runpy
        import threading
        import time
        replay = runpy.run_path(str(SCRIPT))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o700)
            ready = root / "ready"
            start = root / "start"

            def release():
                time.sleep(0.02)
                start.write_text("GO\n")

            worker = threading.Thread(target=release)
            worker.start()
            try:
                replay["wait_for_external_start_gate"](ready, start)
            finally:
                worker.join()
            self.assertEqual(ready.read_text(), "READY\n")
            open_dir = root / "open"
            open_dir.mkdir(mode=0o755)
            with self.assertRaisesRegex(ValueError, "private and owned"):
                replay["wait_for_external_start_gate"](
                    open_dir / "ready", open_dir / "start")

    def test_striped_helper_targets_satisfy_replay_owned_checks(self):
        """The loaded swapz arm validates UUID shape and exact mapped size.

        CI cannot run the privileged striped helper, so pin the helper's
        mapper contract against the replay's own validators instead.
        """
        import re
        import runpy
        replay = runpy.run_path(str(SCRIPT))
        source = SCRIPT.read_text()
        helper = (SCRIPT.parents[2] / "tools/benchmark-striped-owned.sh").read_text()
        uuid_pattern = re.search(
            r're\.fullmatch\(\s*r"(SWAPZ-TEST-[^"]+)",\s*args\.expected_dm_uuid',
            source).group(1)
        template = re.search(r'^\s*uuid="([^"]+)"', helper, re.M).group(1)
        self.assertIsNotNone(re.fullmatch(
            uuid_pattern, template.replace("$token", "0123456789abcdef")))
        self.assertNotIn("0 8192 swapz", helper)
        table = re.search(r'^\s*table="([^"]+)"', helper, re.M).group(1)
        self.assertTrue(table.startswith("0 $STRIPE_SECTORS swapz "))
        self.assertIn('["logical_pages"]', helper)
        # The replay's own table validator accepts one stripe of each count.
        for stripes in (1, 2, 4):
            pages = 1024 // stripes
            row = table.replace("$STRIPE_SECTORS", str(pages * 8)).replace(
                "${LOWERS[lower_index]}", "251:7")
            replay["validate_swapz_table"](row, pages, "251:7", "nullb7")

    def test_external_start_gate_follows_all_pre_measurement_work(self):
        import ast
        tree = ast.parse(SCRIPT.read_text())
        body = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "run_native_replay")
        calls = [node.func.id if isinstance(node.func, ast.Name) else
                 node.func.attr for node in ast.walk(body)
                 if isinstance(node, ast.Call) and
                 isinstance(node.func, (ast.Name, ast.Attribute))]
        lines = {name: min(node.lineno for node in ast.walk(body)
                           if isinstance(node, ast.Call) and
                           getattr(node.func, "id", getattr(node.func, "attr", None)) == name)
                 for name in ("wait_for_external_start_gate",
                              "kernel_write_profile_epoch",
                              "kernel_write_snapshot", "kernel_read_snapshot",
                              "host_cpu_snapshot", "begin")}
        self.assertEqual(calls.count("wait_for_external_start_gate"), 1)
        for earlier in ("kernel_write_profile_epoch", "kernel_write_snapshot",
                        "kernel_read_snapshot", "host_cpu_snapshot"):
            self.assertLess(lines[earlier], lines["wait_for_external_start_gate"])
        self.assertLess(lines["wait_for_external_start_gate"], lines["begin"])

    def test_fast_striped_plan_split_reconstructs_parent_trace(self):
        import importlib.util
        import runpy
        replay = runpy.run_path(str(SCRIPT))
        spec = importlib.util.spec_from_file_location(
            "swapz_striped_fast", SCRIPT.parents[2] / "tools/fast-test.py")
        fast = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fast)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = root / "fixture.bin"
            fixture.write_bytes(b"".join(bytes([i + 1]) * PAGE for i in range(16)))
            base = root / "plan-striped-base"
            self.run_cmd(
                "prepare", "--fixture", fixture, "--output-dir", base,
                "--qd", 32, "--logical-pages", 128, "--writer-pages", 64,
                "--reader-start", 64, "--reader-pages", 64,
                "--warmup-ops", 64, "--measure-ops", 128, "--read-pct", 50,
                "--iops", 0, "--mixed-lanes", "persistent",
                "--stripe-partitionable")
            fast.prepare_striped_plans(root, (1, 2, 4))
            parent = [json.loads(line) for line in
                      (base / "trace.jsonl").read_text().splitlines()]
            parent_projection = sorted(
                (row["wave"], row["lane"], row["op"], row["page"],
                 row["fixture"], row["phase"]) for row in parent)
            for stripe_count in (1, 2, 4):
                rebuilt = []
                total_ops = 0
                for stripe_index in range(stripe_count):
                    child_dir = root / f"striped-{stripe_count}" / f"stripe-{stripe_index}"
                    manifest = json.loads((child_dir / "manifest.json").read_text())
                    child, _ = replay["check_plan"](
                        child_dir / "trace.jsonl", manifest, 16)
                    total_ops += len(child)
                    rebuilt.extend(
                        (row["wave"], row["lane"] * stripe_count + stripe_index,
                         row["op"], row["page"] * stripe_count + stripe_index,
                         row["fixture"], row["phase"]) for row in child)
                self.assertEqual(total_ops, len(parent))
                self.assertEqual(sorted(rebuilt), parent_projection)

    def test_fast_striped_sustained_write_conserves_every_operation(self):
        import importlib.util
        import runpy
        replay = runpy.run_path(str(SCRIPT))
        spec = importlib.util.spec_from_file_location(
            "swapz_striped_write_fast", SCRIPT.parents[2] / "tools/fast-test.py")
        fast = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fast)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = root / "fixture.bin"
            fixture.write_bytes(b"".join(bytes([i + 1]) * PAGE for i in range(16)))
            for qd in (4, 8):
                workload = f"write-q{qd}"
                base = root / f"plan-striped-write-qd{qd}"
                self.run_cmd(
                    "prepare", "--fixture", fixture, "--output-dir", base,
                    "--qd", qd, "--logical-pages", 128, "--writer-pages", 64,
                    "--reader-start", 64, "--reader-pages", 64,
                    "--warmup-ops", 64, "--measure-ops", 128, "--read-pct", 0,
                    "--iops", 0, "--sustained-write", "--stripe-partitionable")
                fast.prepare_striped_plans(root, (1, 2, 4), workload)
                parent = [json.loads(line) for line in
                          (base / "trace.jsonl").read_text().splitlines()]
                projection = sorted(
                    (row["wave"], row["lane"], row["op"], row["page"],
                     row["fixture"], row["phase"]) for row in parent)
                for stripe_count in (1, 2, 4):
                    rebuilt = []
                    for stripe_index in range(stripe_count):
                        child_dir = (root / f"striped-{workload}-{stripe_count}" /
                                     f"stripe-{stripe_index}")
                        manifest = json.loads(
                            (child_dir / "manifest.json").read_text())
                        self.assertEqual(manifest["qd"], qd // stripe_count)
                        self.assertEqual(manifest["replay_mode"], "persistent-write")
                        self.assertEqual(manifest["read_pct"], 0)
                        child, _ = replay["check_plan"](
                            child_dir / "trace.jsonl", manifest, 16)
                        rebuilt.extend(
                            (row["wave"], row["lane"] * stripe_count + stripe_index,
                             row["op"], row["page"] * stripe_count + stripe_index,
                             row["fixture"], row["phase"]) for row in child)
                    self.assertEqual(sorted(rebuilt), projection)
                    self.assertEqual(len(rebuilt), len(parent))
                    self.assertTrue(all(row[2] == "W" for row in rebuilt))
                invalid = dict(json.loads((base / "manifest.json").read_text()))
                invalid["replay_mode"] = "qd-waves"
                with self.assertRaisesRegex(ValueError, "stripe-partitionable manifest"):
                    replay["check_plan"](base / "trace.jsonl", invalid, 16)

    def test_fast_submitter_switch_is_explicit_development_only(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "swapz_submitter_fast", SCRIPT.parents[2] / "tools/fast-test.py")
        fast = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fast)
        self.assertEqual(fast.striped_scenario("fast-stripes-w4"),
                         ("fast", "write-q4"))
        self.assertEqual(fast.striped_scenario("fast-stripes-w8"),
                         ("fast", "write-q8"))
        self.assertIsNone(fast.striped_scenario("fast-stripes-w32"))
        arguments = fast.scenario_arguments(
            "fast-w4", "/plan", submitter_prepare=0)
        self.assertEqual(
            arguments[-5:], ["--async-prepare", "--submitter-prepare", "0",
                             "--shared-plan", "/plan"])
        self.assertNotIn("--submitter-prepare", fast.scenario_arguments(
            "fast-w4", "/plan"))
        self.assertEqual(fast.STRIPED_WRITE_QDS, (4, 8))
        hand = fast.scenario_arguments("fast-w32", "/plan",
                                       submitter_prepare=0, hand_records=16)
        self.assertEqual(
            hand[-7:], ["--async-prepare", "--submitter-prepare", "0",
                        "--hand-records", "16", "--shared-plan", "/plan"])
        self.assertNotIn("--hand-records", fast.scenario_arguments(
            "fast-w32", "/plan"))
        arms = {
            "off": {
                "throughput_mbps": {
                    "logical_write_mbps": 80.0,
                    "logical_read_mbps": 0.0,
                    "logical_write_bytes": 4096 * 4096,
                },
                "lower_io": {
                    "lower_write_bytes": 4096 * 4096,
                    "lower_write_requests": 4096,
                },
                "read_p99_ns": 0,
                "write_p99_ns": 1000000,
            },
            "swapz": {
                "throughput_mbps": {
                    "logical_write_mbps": 96.0,
                    "logical_read_mbps": 0.0,
                    "logical_write_bytes": 4096 * 4096,
                },
                "lower_io": {
                    "lower_write_bytes": 12 * 1024 * 1024,
                    "lower_write_requests": 400,
                },
                "read_p99_ns": 0,
                "write_p99_ns": 1200000,
                "seconds": 1.0,
                "kernel_write_path": {
                    "windows": 390,
                    "work_conserving_hand_records": 16,
                    "work_conserving_hand_closes": 200,
                    "lower_write_service_ewma_ns": 300000,
                    "lower_write_block_service_ewma_ns": 150000,
                },
            },
        }
        summary = fast.summarize("fast-w32", arms, 2.0)
        self.assertEqual(summary["hand_records"], 16)
        self.assertEqual(summary["hand_closes"], 200)
        self.assertAlmostEqual(summary["pages_per_lower_write"], 10.24)
        self.assertEqual(summary["service_us"], 300.0)
        self.assertEqual(summary["block_service_us"], 150.0)


    @contextlib.contextmanager
    def python_final_drain_case(self, replay_mode):
        """Small canonical-plan regular-file replay; never touches swap or a mapper."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "fixture.bin"
            fixture.write_bytes(b"".join(bytes([index + 1]) * PAGE
                                         for index in range(16)))
            plan = root / "plan"
            mode_flags = ({"persistent-write": ["--sustained-write"],
                           "persistent-mixed": ["--mixed-lanes", "persistent"]}
                          .get(replay_mode, []))
            self.run_cmd("prepare", "--fixture", fixture,
                         "--output-dir", plan, "--seed", "0x51a0a9",
                         "--logical-pages", 64, "--writer-pages", 16,
                         "--reader-start", 32, "--reader-pages", 16,
                         "--qd", 4, "--warmup-ops", 8, "--measure-ops", 24,
                         "--read-pct", 0 if replay_mode == "persistent-write" else 25,
                         "--iops", 0, *mode_flags)
            manifest = json.loads((plan / "manifest.json").read_text())
            self.assertEqual(manifest["replay_mode"], replay_mode)
            target = root / "swapz-replay-off.bin"
            with target.open("wb") as handle:
                handle.truncate(64 * PAGE)
            result = root / "report.json"
            arguments = ["run", "--fixture", fixture,
                         "--trace", plan / "trace.jsonl",
                         "--manifest", plan / "manifest.json",
                         "--device", target, "--candidate", "off",
                         "--source-sha", "rootless-no-module",
                         "--regular-file-test", "--result", result]
            yield manifest, target, result, arguments

    def invoke_python_replay_main(self, replay_module, arguments):
        output, errors = io.StringIO(), io.StringIO()
        status = 0
        with mock.patch.object(sys, "argv", [str(SCRIPT), *map(str, arguments)]), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            try:
                replay_module.main()
            except SystemExit as error:
                status = error.code
        return status, output.getvalue(), errors.getvalue()

    def python_replay_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("swapz_final_drain_replay", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_python_final_drain_success_is_after_workers_and_inside_clock(self):
        for mode in ("qd-waves", "persistent-write", "persistent-mixed"):
            with self.subTest(mode=mode), self.python_final_drain_case(mode) as case:
                manifest, target, result, arguments = case
                module = self.python_replay_module()
                original_pool = module.concurrent.futures.ThreadPoolExecutor
                original_fsync = os.fsync
                jobs, drains = [], []

                class ObservedPool(original_pool):
                    def submit(self, function, *args, **kwargs):
                        future = super().submit(function, *args, **kwargs)
                        jobs.append(future)
                        return future

                def checked_fsync(descriptor):
                    drains.append(time.monotonic_ns())
                    self.assertEqual(os.fstat(descriptor).st_ino, target.stat().st_ino)
                    if len(drains) == 3:
                        self.assertTrue(jobs)
                        self.assertTrue(all(job.done() for job in jobs))
                        self.assertFalse(result.exists())
                    original_fsync(descriptor)
                    drains.append(time.monotonic_ns())

                with mock.patch.object(module.os, "fsync", side_effect=checked_fsync), \
                        mock.patch.object(module.concurrent.futures,
                                          "ThreadPoolExecutor", ObservedPool):
                    status, output, errors = self.invoke_python_replay_main(
                        module, arguments)
                self.assertEqual(status, 0, errors)
                self.assertEqual(len(drains), 4)  # prefill plus one measured drain
                self.assertEqual(len(jobs), 4 if mode != "qd-waves" else 32)
                report = json.loads(result.read_text())
                self.assertEqual(report["verdict"], "PASS")
                self.assertIn('"verdict": "PASS"', output)
                self.assertEqual(report["replay_mode"], mode)
                self.assertEqual(report["write_ops"],
                                 manifest["workload_opportunity"]["measured_write_ops"])
                self.assertLessEqual(report["measured_start_monotonic_ns"], drains[2])
                self.assertGreaterEqual(report["measured_end_monotonic_ns"], drains[3])
                self.assertAlmostEqual(report["seconds"],
                    (report["measured_end_monotonic_ns"] -
                     report["measured_start_monotonic_ns"]) / 1e9)

    def test_python_final_drain_eio_blocks_pass_with_redacted_reason(self):
        for mode in ("qd-waves", "persistent-write", "persistent-mixed"):
            with self.subTest(mode=mode), self.python_final_drain_case(mode) as case:
                manifest, target, result, arguments = case
                candidate = "swapz" if mode == "persistent-mixed" else "off"
                arguments[arguments.index("--candidate") + 1] = candidate
                module = self.python_replay_module()
                original_fsync = os.fsync
                calls = 0
                private_path = str(target.parent / "PRIVATE-FILENAME-MUST-NOT-LEAK")
                expected_bytes = (manifest["workload_opportunity"]
                                  ["measured_write_ops"] * PAGE)

                def fail_final_fsync(descriptor):
                    nonlocal calls
                    calls += 1
                    self.assertEqual(os.fstat(descriptor).st_ino, target.stat().st_ino)
                    if calls == 1:
                        return original_fsync(descriptor)
                    self.assertEqual(calls, 2)
                    raise OSError(errno.EIO, "synthetic final-drain device error",
                                  private_path)

                with mock.patch.object(module.os, "fsync", side_effect=fail_final_fsync):
                    status, output, errors = self.invoke_python_replay_main(
                        module, arguments)
                self.assertEqual(status, 2)
                self.assertEqual(calls, 2)
                self.assertFalse(result.exists())
                self.assertNotIn('"verdict": "PASS"', output)
                self.assertIn(f"BENCH_IO_PHASE={candidate}:mixed", errors)
                self.assertIn(f"{candidate}:mixed final fsync failed", errors)
                self.assertIn(
                    f"expected measured WRITE bytes {expected_bytes}, "
                    f"observed completed WRITE bytes {expected_bytes}", errors)
                self.assertIn("final-drain oracle=success, observed=synthetic "
                              "final-drain device error", errors)
                self.assertNotIn(private_path, output + errors)
                self.assertNotIn("PRIVATE-FILENAME", output + errors)

    def test_python_partial_worker_completion_rejects_without_final_drain(self):
        for mode in ("qd-waves", "persistent-write", "persistent-mixed"):
            with self.subTest(mode=mode), self.python_final_drain_case(mode) as case:
                _, _, result, arguments = case
                module = self.python_replay_module()
                original_fsync = os.fsync
                original_pwrite = os.pwrite
                original_begin = module.LowerInflightSampler.begin
                measured = False
                failed = False
                fsync_calls = 0

                def begin_measurement(sampler):
                    nonlocal measured
                    started = original_begin(sampler)
                    measured = True
                    return started

                def incomplete_write(descriptor, data, offset):
                    nonlocal failed
                    if measured and not failed:
                        failed = True
                        return PAGE - 1
                    return original_pwrite(descriptor, data, offset)

                def count_fsync(descriptor):
                    nonlocal fsync_calls
                    fsync_calls += 1
                    return original_fsync(descriptor)

                with mock.patch.object(module.LowerInflightSampler, "begin",
                                       begin_measurement), \
                        mock.patch.object(module.os, "pwrite",
                                          side_effect=incomplete_write), \
                        mock.patch.object(module.os, "fsync", side_effect=count_fsync):
                    status, output, errors = self.invoke_python_replay_main(
                        module, arguments)
                self.assertTrue(failed)
                self.assertEqual(status, 2)
                self.assertEqual(fsync_calls, 1)  # prefill only; workers failed
                self.assertFalse(result.exists())
                self.assertNotIn('"verdict": "PASS"', output)
                self.assertIn("BENCH_IO_PHASE=off:mixed", errors)
                self.assertIn(
                    "short timed WRITE logical I/O "
                    "(expected 4096 bytes, observed 4095)", errors)
                self.assertNotIn("final fsync failed", errors)
                self.assertNotIn("BufferError", errors)

    def test_python_persistent_warmup_failure_preserves_write_reason(self):
        with self.python_final_drain_case("persistent-write") as case:
            manifest, _, result, arguments = case
            module = self.python_replay_module()
            original_pool = module.concurrent.futures.ThreadPoolExecutor
            original_pwrite = os.pwrite
            original_fsync = os.fsync
            prefill_complete = False
            injected = False
            fsync_calls = 0

            class PendingDoneFuture:
                """Model a worker still unwinding after its barrier was aborted."""

                def __init__(self, future):
                    self._future = future

                def done(self):
                    return False

                def result(self, *args, **kwargs):
                    return self._future.result(*args, **kwargs)

            class PendingDonePool(original_pool):
                def submit(self, function, *args, **kwargs):
                    return PendingDoneFuture(
                        super().submit(function, *args, **kwargs))

            def track_fsync(descriptor):
                nonlocal prefill_complete, fsync_calls
                fsync_calls += 1
                result_value = original_fsync(descriptor)
                prefill_complete = True
                return result_value

            def short_lane_zero_warmup(descriptor, data, offset):
                nonlocal injected
                page = offset // PAGE
                if (prefill_complete and not injected and
                        page % manifest["qd"] == 0):
                    injected = True
                    return PAGE - 1
                return original_pwrite(descriptor, data, offset)

            with mock.patch.object(module.concurrent.futures,
                                   "ThreadPoolExecutor", PendingDonePool), \
                    mock.patch.object(module.os, "pwrite",
                                      side_effect=short_lane_zero_warmup), \
                    mock.patch.object(module.os, "fsync",
                                      side_effect=track_fsync):
                status, output, errors = self.invoke_python_replay_main(
                    module, arguments)
            self.assertTrue(injected)
            self.assertEqual(fsync_calls, 1)  # prefill only
            self.assertEqual(status, 2)
            self.assertFalse(result.exists())
            self.assertNotIn('"verdict": "PASS"', output)
            self.assertIn("BENCH_IO_PHASE=off:mixed", errors)
            self.assertIn(
                "short timed WRITE logical I/O "
                "(expected 4096 bytes, observed 4095)", errors)
            self.assertNotIn("persistent workers failed before measurement", errors)
            self.assertNotIn("BrokenBarrierError", errors)
            self.assertNotIn("Traceback", errors)

    def test_python_final_drain_failure_precedes_sampler_cleanup_error(self):
        for mode in ("qd-waves", "persistent-write", "persistent-mixed"):
            with self.subTest(mode=mode), self.python_final_drain_case(mode) as case:
                _, _, result, arguments = case
                module = self.python_replay_module()
                original_fsync = os.fsync
                fsync_calls = 0

                def fail_final_fsync(descriptor):
                    nonlocal fsync_calls
                    fsync_calls += 1
                    if fsync_calls == 1:
                        return original_fsync(descriptor)
                    raise OSError(errno.EIO, "synthetic primary drain error")

                with mock.patch.object(module.os, "fsync", side_effect=fail_final_fsync), \
                        mock.patch.object(module.LowerInflightSampler, "close",
                                          side_effect=OSError(errno.EIO,
                                                              "synthetic cleanup error")):
                    status, output, errors = self.invoke_python_replay_main(
                        module, arguments)
                self.assertEqual(fsync_calls, 2)
                self.assertEqual(status, 2)
                self.assertFalse(result.exists())
                self.assertNotIn('"verdict": "PASS"', output)
                self.assertIn("off:mixed final fsync failed", errors)
                self.assertIn("synthetic primary drain error", errors)
                self.assertNotIn("synthetic cleanup error", errors)

    def test_python_sampler_cleanup_error_alone_blocks_pass(self):
        with self.python_final_drain_case("qd-waves") as case:
            _, _, result, arguments = case
            module = self.python_replay_module()
            original_fsync = os.fsync
            fsync_calls = 0

            def track_fsync(descriptor):
                nonlocal fsync_calls
                fsync_calls += 1
                return original_fsync(descriptor)

            with mock.patch.object(module.os, "fsync", side_effect=track_fsync), \
                    mock.patch.object(module.LowerInflightSampler, "close",
                                      side_effect=OSError(errno.EIO,
                                                          "synthetic sampler close error")):
                status, output, errors = self.invoke_python_replay_main(
                    module, arguments)
            self.assertEqual(fsync_calls, 2)
            self.assertEqual(status, 2)
            self.assertFalse(result.exists())
            self.assertNotIn('"verdict": "PASS"', output)
            self.assertIn("synthetic sampler close error", errors)
            self.assertNotIn("final fsync failed", errors)

    def test_python_byte_oracle_failure_is_not_a_drain_failure(self):
        with self.python_final_drain_case("persistent-write") as case:
            manifest, _, result, arguments = case
            module = self.python_replay_module()
            original_pwrite = os.pwrite
            original_begin = module.LowerInflightSampler.begin
            original_fsync = os.fsync
            expected_writes = manifest["workload_opportunity"]["measured_write_ops"]
            measuring = False
            measured_writes = 0
            drains = 0

            def begin_measurement(sampler):
                nonlocal measuring
                started = original_begin(sampler)
                measuring = True
                return started

            def corrupt_last_write(descriptor, data, offset):
                nonlocal measured_writes
                if measuring:
                    measured_writes += 1
                    if measured_writes == expected_writes:
                        return original_pwrite(descriptor, bytes(PAGE), offset)
                return original_pwrite(descriptor, data, offset)

            def track_fsync(descriptor):
                nonlocal drains
                drains += 1
                return original_fsync(descriptor)

            with mock.patch.object(module.LowerInflightSampler, "begin",
                                   begin_measurement), \
                    mock.patch.object(module.os, "pwrite",
                                      side_effect=corrupt_last_write), \
                    mock.patch.object(module.os, "fsync", side_effect=track_fsync):
                status, output, errors = self.invoke_python_replay_main(
                    module, arguments)
            self.assertEqual(measured_writes, expected_writes)
            self.assertEqual(drains, 2)  # successful final drain precedes oracle
            self.assertEqual(status, 2)
            self.assertFalse(result.exists())
            self.assertNotIn('"verdict": "PASS"', output)
            self.assertIn("short or mismatched logical page read", errors)
            self.assertNotIn("final fsync failed", errors)

    def test_sustained_write_uses_persistent_lane_owned_streams(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = root / "fixture.bin"
            fixture.write_bytes(b"".join(bytes([i + 1]) * PAGE
                                         for i in range(16)))
            plan = root / "plan"
            self.run_cmd("prepare", "--fixture", fixture,
                         "--output-dir", plan, "--qd", 4,
                         "--logical-pages", 64, "--writer-pages", 16,
                         "--reader-start", 32, "--reader-pages", 16,
                         "--warmup-ops", 8, "--measure-ops", 16,
                         "--read-pct", 0, "--iops", 0,
                         "--sustained-write")
            manifest = json.loads((plan / "manifest.json").read_text())
            self.assertEqual(manifest["replay_mode"], "persistent-write")
            rows = [json.loads(line) for line in
                    (plan / "trace.jsonl").read_text().splitlines()]
            self.assertTrue(all(row["op"] == "W" for row in rows))
            self.assertTrue(all(row["page"] % 4 == row["lane"] for row in rows))
            reports = []
            for candidate in ("off", "swapz"):
                device = root / f"swapz-replay-{candidate}.bin"
                with device.open("wb") as handle:
                    handle.truncate(64 * PAGE)
                result = root / f"{candidate}.json"
                self.run_cmd("run", "--fixture", fixture,
                             "--trace", plan / "trace.jsonl",
                             "--manifest", plan / "manifest.json",
                             "--device", device, "--candidate", candidate,
                             "--source-sha", "rootless-no-module",
                             "--regular-file-test", "--result", result)
                record = json.loads(result.read_text())
                self.assertEqual(record["replay_mode"], "persistent-write")
                self.assertIn("persistent lane-owned write workers",
                              record["mixed_timed_scope"])
                reports.append(result)
            compared = json.loads(
                self.run_cmd("compare", "--reports", *reports).stdout)
            self.assertEqual(compared["replay_mode"], "persistent-write")

            bad = root / "bad-plan"
            self.run_cmd("prepare", "--fixture", fixture,
                         "--output-dir", bad, "--qd", 4,
                         "--logical-pages", 64, "--writer-pages", 16,
                         "--reader-start", 32, "--reader-pages", 16,
                         "--warmup-ops", 8, "--measure-ops", 16,
                         "--read-pct", 25, "--iops", 0,
                         "--sustained-write", success=False)

    def test_manifest_cannot_have_duplicate_inflight_slot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = root / "fixture.bin"
            fixture.write_bytes(bytes([1]) * PAGE * 16)
            plan = root / "plan"
            self.run_cmd("prepare", "--fixture", fixture,
                         "--output-dir", plan, "--qd", 4,
                         "--logical-pages", 64, "--writer-pages", 16,
                         "--reader-start", 32, "--reader-pages", 16,
                         "--warmup-ops", 4, "--measure-ops", 8)
            import importlib.util
            spec = importlib.util.spec_from_file_location("threeway", SCRIPT)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mf = json.loads((plan / "manifest.json").read_text())
            # Plan validation checks both SHA and in-wave independence.
            rows = [json.loads(line) for line in (plan / "trace.jsonl").read_text().splitlines()]
            rows[1]["page"] = rows[0]["page"]
            replacement = "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n"
                                  for r in rows).encode()
            (plan / "trace.jsonl").write_bytes(replacement)
            mf["trace_sha256"] = mod.sha(replacement)
            with self.assertRaisesRegex(ValueError, "same logical page"):
                mod.check_plan(plan / "trace.jsonl", mf, 16)

    def test_lower_inflight_sampler_timeout_diagnostic_lock_free(self):
        import importlib.util
        import threading

        spec = importlib.util.spec_from_file_location("swapz_replay_diag", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with tempfile.TemporaryDirectory() as temp:
            dummy_path = Path(temp) / "inflight"
            dummy_path.write_text("0 0\n", encoding="ascii")
            sampler = mod.LowerInflightSampler("dummy")
            sampler._path = dummy_path

            read_entered = threading.Event()
            block_read = threading.Event()

            def blocking_read_fd(fd):
                read_entered.set()
                block_read.wait(timeout=5.0)
                return (0, 0)

            orig_read_fd = mod.LowerInflightSampler._read_fd
            mod.LowerInflightSampler._read_fd = staticmethod(blocking_read_fd)
            try:
                sampler.start()
                self.assertTrue(read_entered.wait(timeout=2.0))
                with sampler._lock:
                    diagnostic = sampler._format_timeout_diagnostic(action="test")
                    self.assertIn("state=READING", diagnostic)
                    self.assertIn("lock_held=True", diagnostic)
                    self.assertIn("blocking_read_fd", diagnostic)
            finally:
                block_read.set()
                mod.LowerInflightSampler._read_fd = orig_read_fd
                sampler.close()

    def test_physical_partuuid_grammar_matches_production_selector(self):
        import importlib.util

        qualification_path = SCRIPT.with_name("qualification.py")
        qualification_spec = importlib.util.spec_from_file_location(
            "swapz_partuuid_contract", qualification_path)
        qualification = importlib.util.module_from_spec(qualification_spec)
        qualification_spec.loader.exec_module(qualification)

        self.assertEqual(
            qualification.normalize_partuuid("F13428F6-01"),
            "f13428f6-01")
        for malformed in (
                "--------", "f13428f6--01", "f13428f6.",
                ".f13428f6", "1234-567", "nothex001",
                "a" * 65):
            with self.subTest(partuuid=malformed):
                self.assertIsNone(
                    qualification.normalize_partuuid(malformed))

        sustained_source = SCRIPT.with_name("sustained-replay.py").read_text()
        self.assertIn(
            'QUALIFICATION["normalize_partuuid"](\n'
            '        args.physical_partuuid)',
            sustained_source)
        self.assertNotIn(
            'r"[A-Za-z0-9][A-Za-z0-9.-]{7,127}"',
            sustained_source)

    def test_physical_qualification_contract_and_o1_oracle(self):
        import importlib.util

        qualification_path = SCRIPT.with_name("qualification.py")
        spec = importlib.util.spec_from_file_location(
            "swapz_performance_qualification", qualification_path)
        qualification = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(qualification)
        contract = qualification.contract()
        frozen = json.loads(
            (ROOT / "docs/production-acceptance.json").read_text())
        self.assertEqual(frozen["status"], "FROZEN")
        self.assertEqual(contract, frozen["physical_qualification"])
        self.assertEqual(contract["schema"], "swapz-performance-qualification-v1")
        balanced = contract["workloads"]["sd-service-balanced"]
        self.assertEqual(balanced["pairs"], 5)
        self.assertEqual(balanced["warmup_operations"], 65536)
        self.assertEqual(balanced["measure_operations"], 1048576)
        self.assertEqual(balanced["qd"], 8)
        self.assertEqual(balanced["read_percent"], 20)
        self.assertEqual(
            balanced["counterbalanced_order"],
            ["raw-first", "swapz-first", "swapz-first", "raw-first", "raw-first"])
        amendment = qualification.amendment()
        self.assertEqual(
            amendment["schema"],
            "swapz-performance-qualification-amendment-v2")
        self.assertEqual(amendment["status"], "FROZEN_PROSPECTIVE")
        qd1 = amendment["workloads"]["sd-service-qd1-balanced"]
        self.assertEqual(qd1["qd"], 1)
        self.assertEqual(qd1["acceptance_profile"], "service-v1")
        self.assertEqual(
            qualification.service_limits("sd-service-qd1-balanced"),
            contract["acceptance"]["service"])
        incompressible = amendment["workloads"]["sd-service-incompressible"]
        self.assertEqual(incompressible["fill_content_profile"], "entropy")
        self.assertEqual(incompressible["churn_content_profile"], "entropy")
        non_regression = qualification.service_limits(
            "sd-service-incompressible")
        self.assertEqual(non_regression["useful_write_ci_lower_min"], -.10)
        self.assertEqual(non_regression["lower_write_bytes_ci_upper_max"], .10)
        self.assertEqual(
            non_regression["lower_write_requests_ci_upper_max"], .10)
        sustained_contract = contract["workloads"]["sd-high-occupancy-churn"]
        self.assertEqual(sustained_contract["logical_occupancy_percent"], 90)
        self.assertEqual(sustained_contract["hot_region_percent"], 80)
        self.assertEqual(sustained_contract["measure_seconds"], 3600)
        anonymous_contract = contract["workloads"]["anonymous-swap"]
        self.assertEqual(anonymous_contract["bytes"], 1024 * 1024 * 1024)
        self.assertEqual(anonymous_contract["memory_max_bytes"], 512 * 1024 * 1024)
        self.assertEqual(
            contract["acceptance"]["service"][
                "useful_write_ci_lower_min"], .05)
        self.assertEqual(
            contract["acceptance"]["sustained"]["gc_wall_fraction_max"], .20)
        self.assertEqual(
            contract["acceptance"]["sustained"]["minimum_rewritten_hot_pages"], 1)
        self.assertIn("not direct NAND-wear", contract["claim_boundary"])
        with self.assertRaisesRegex(ValueError, "exactly five"):
            qualification.paired_ci95([.1] * 4)

        sustained_path = SCRIPT.with_name("sustained-replay.py")
        sustained_spec = importlib.util.spec_from_file_location(
            "swapz_sustained_replay", sustained_path)
        sustained = importlib.util.module_from_spec(sustained_spec)
        sustained_spec.loader.exec_module(sustained)
        self.assertEqual(sustained.maximum_logical_pages(124787884032), 27080192)
        lane_pages = 17
        stride = sustained.coprime_stride(lane_pages, 0x1234)
        offset = sustained.sequence_offset(lane_pages, 0x5678)
        sequence = [(index * stride + offset) % lane_pages for index in range(53)]
        for page in range(lane_pages):
            expected = max((index for index, item in enumerate(sequence)
                            if item == page), default=None)
            self.assertEqual(
                sustained.latest_write_index(page, 53, lane_pages, stride, offset),
                expected)
        histogram = sustained.LatencyHistogram()
        for value in range(1, 1001):
            histogram.observe(value)
        self.assertGreaterEqual(histogram.percentile(.95), 950)
        self.assertLessEqual(histogram.percentile(.95), 1024)
        self.assertGreaterEqual(histogram.percentile(.99), 990)
        self.assertLessEqual(histogram.percentile(.99), 1024)
        low_tail = sustained.LatencyHistogram()
        high_tail = sustained.LatencyHistogram()
        for _ in range(100):
            low_tail.observe(1_000_000)
            high_tail.observe(1_100_000)
        self.assertLess(
            high_tail.percentile(.99) / low_tail.percentile(.99), 1.20)
        coverage = sustained.overwrite_coverage(16, 4, [5, 5, 5, 5])
        self.assertEqual(coverage["measured_hot_pages_touched"], 16)
        self.assertEqual(coverage["measured_hot_pages_rewritten"], 4)
        self.assertEqual(coverage["measured_repeat_write_operations"], 4)
        self.assertEqual(coverage["measured_min_writes_per_hot_page"], 1)
        self.assertEqual(coverage["measured_max_writes_per_hot_page"], 2)
        status = sustained.status_delta(
            {"gc_wall_ns": 10, "gc_role_rotations": 2, "cursor": 4,
             "failed": 0, "error": 0},
            {"gc_wall_ns": 30, "gc_role_rotations": 5, "cursor": 9,
             "failed": 0, "error": 0},
            100)
        self.assertEqual(status["gc_role_rotations"], 3)
        self.assertEqual(status["cursor"], 9)
        self.assertEqual(status["wall_fraction"], .20)

    def test_sustained_replay_vmhwm_parser_is_strict(self):
        import importlib.util

        sustained_path = SCRIPT.with_name("sustained-replay.py")
        sustained_spec = importlib.util.spec_from_file_location(
            "swapz_sustained_hwm", sustained_path)
        sustained = importlib.util.module_from_spec(sustained_spec)
        sustained_spec.loader.exec_module(sustained)
        self.assertEqual(
            sustained.parse_process_hwm_bytes(
                "Name:\tpython\nVmHWM:\t   12345 kB\nVmRSS:\t   10000 kB\n"),
            12345 * 1024)
        for invalid in (
                "Name:\tpython\n",
                "VmHWM:\t0 kB\n",
                "VmHWM:\t12 MB\n",
                "VmHWM:\t12 kB\nVmHWM:\t13 kB\n"):
            with self.assertRaises(RuntimeError):
                sustained.parse_process_hwm_bytes(invalid)
        self.assertGreater(sustained.process_hwm_bytes(), 0)

    def test_sustained_replay_rootless_fixed_work_and_failure_record(self):
        sustained = SCRIPT.with_name("sustained-replay.py")
        with tempfile.TemporaryDirectory(prefix="swapz-sustain-test-") as directory:
            root = Path(directory)
            fill = root / "fill.bin"
            churn = root / "churn.bin"
            fill.write_bytes(bytes([0x11]) * PAGE + bytes([0x22]) * PAGE)
            churn.write_bytes(bytes([0x33]) * PAGE + bytes([0x44]) * PAGE)
            import hashlib
            (root / "fill.json").write_text(json.dumps({
                "pages": 2, "page_bytes": PAGE, "profile_pages": {"medium": 2},
                "fixture_sha256": hashlib.sha256(fill.read_bytes()).hexdigest()}))
            (root / "churn.json").write_text(json.dumps({
                "pages": 2, "page_bytes": PAGE, "profile_pages": {"medium": 2},
                "fixture_sha256": hashlib.sha256(churn.read_bytes()).hexdigest()}))
            target = root / "swapz-sustain-raw.bin"
            with target.open("wb") as stream:
                stream.truncate(128 * PAGE)
            result = root / "result.json"
            command = [
                sys.executable, str(sustained), "--workload-id", "rootless-test",
                "--candidate", "raw", "--source-sha", "rootless-no-module",
                "--device", str(target), "--result", str(result),
                "--fill-fixture", str(fill), "--churn-fixture", str(churn),
                "--fill-content-profile", "medium", "--churn-content-profile", "medium",
                "--logical-pages", "128", "--occupancy-percent", "75",
                "--hot-percent", "50", "--qd", "4", "--read-percent", "20",
                "--warmup-operations", "32", "--measure-operations", "256",
                "--cold-read-pages", "8", "--regular-file-test",
            ]
            run = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            report = json.loads(result.read_text())
            self.assertEqual(report["verdict"], "PASS")
            self.assertLessEqual(
                report["arm_started_monotonic_ns"],
                report["measured_start_monotonic_ns"])
            self.assertGreater(
                report["measured_end_monotonic_ns"],
                report["measured_start_monotonic_ns"])
            self.assertLessEqual(
                report["measured_end_monotonic_ns"],
                report["arm_finished_monotonic_ns"])
            self.assertAlmostEqual(
                (report["measured_end_monotonic_ns"] -
                 report["measured_start_monotonic_ns"]) / 1e9,
                report["seconds"], places=6)
            warmup = report["warmup_evidence"]
            self.assertEqual(warmup["operations"], 32)
            self.assertLessEqual(
                warmup["end_monotonic_ns"],
                report["measurement_snapshots"][
                    "lower_before_monotonic_ns"])
            boundary_times = [
                report["measurement_snapshots"][field]
                for field in (
                    "worker_before_monotonic_ns",
                    "lower_before_monotonic_ns",
                    "target_before_monotonic_ns",
                    "process_before_monotonic_ns")]
            self.assertEqual(boundary_times, sorted(boundary_times))
            self.assertLessEqual(
                boundary_times[-1], report["measured_start_monotonic_ns"])
            after_boundary_times = [
                report["measurement_snapshots"][field]
                for field in (
                    "process_after_monotonic_ns",
                    "target_after_monotonic_ns",
                    "lower_after_monotonic_ns",
                    "worker_after_monotonic_ns")]
            self.assertEqual(
                after_boundary_times, sorted(after_boundary_times))
            self.assertGreaterEqual(
                after_boundary_times[0], report["measured_end_monotonic_ns"])
            self.assertEqual(report["read_ops"] + report["write_ops"], 256)
            self.assertEqual(report["oracle"]["mismatches"], 0)
            self.assertEqual(report["oracle"]["verified_pages"], 96)
            self.assertEqual(report["cold_read"]["pages"], 8)
            self.assertGreater(report["overwrite"]["measured_hot_pages_rewritten"], 0)
            self.assertGreater(report["overwrite"]["measured_repeat_write_operations"], 0)
            self.assertEqual(report["sustained_intervals"], [])
            self.assertEqual(
                report["sustained_observer_overhead"]["samples"], 0)
            self.assertEqual(
                report["sustained_observer_overhead"]["child_cpu_seconds"], 0.0)
            self.assertIn("not live physical-segment utilization",
                          report["occupancy_scope"])
            self.assertGreaterEqual(report["max_no_progress_seconds"], 0)
            self.assertEqual(len(report["minute_buckets"]), 1)
            minute = report["minute_buckets"][0]
            self.assertGreaterEqual(
                minute["start_monotonic_ns"],
                report["measured_start_monotonic_ns"])
            self.assertLessEqual(
                minute["end_monotonic_ns"],
                report["measured_end_monotonic_ns"])
            self.assertAlmostEqual(
                (minute["end_monotonic_ns"] -
                 minute["start_monotonic_ns"]) / 1e9,
                minute["duration_seconds"], places=9)
            self.assertIn("p95_ns", minute)
            self.assertIn("read_p99_ns", minute)
            self.assertIn("write_p99_ns", minute)
            self.assertIn("cumulative_overwrite", minute)
            self.assertEqual(
                [row["phase"] for row in report["occupancy_transitions"]],
                ["initial", "post-fill", "post-warmup", "measured-end"])
            self.assertIn(report["performance_screening"]["status"],
                          ("SCREENED", "EXCLUDED"))
            for phase in ("pre", "post"):
                self.assertIn("before", report["performance_screening"][phase])
                self.assertIn("after", report["performance_screening"][phase])
            self.assertIn(
                "host_cpu_before", report["measurement_snapshots"])
            self.assertIn(
                "host_cpu_after", report["measurement_snapshots"])
            resources = report["resources"]
            self.assertLessEqual(resources["replay_peak_rss_bytes"],
                                 128 * 1024 * 1024)
            self.assertEqual(resources["replay_process_maxrss_bytes"],
                             resources["replay_peak_rss_bytes"])
            self.assertLessEqual(resources["replay_measurement_start_maxrss_bytes"],
                                 resources["replay_peak_rss_bytes"])
            self.assertEqual(
                resources["replay_measurement_peak_rss_growth_bytes"],
                resources["replay_peak_rss_bytes"] -
                resources["replay_measurement_start_maxrss_bytes"])
            sustained_source = sustained.read_text()
            self.assertEqual(
                sustained_source.count("ThreadPoolExecutor(max_workers=args.qd)"),
                1)
            self.assertNotIn(
                "ThreadPoolExecutor(max_workers=qd)", sustained_source)

            failed = root / "failed.json"
            bad = command.copy()
            bad[bad.index(str(result))] = str(failed)
            bad[bad.index("75")] = "101"
            run = subprocess.run(bad, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(run.returncode, 0)
            failure = json.loads(failed.read_text())
            self.assertEqual(failure["verdict"], "FAIL")
            self.assertIn("occupancy", failure["failure_reason"])

            # External physical timeouts send SIGTERM. A bounded worker must
            # preserve that first failure instead of disappearing silently.
            import time
            interrupted_result = root / "interrupted.json"
            interrupted = command.copy()
            interrupted[interrupted.index(str(result))] = str(interrupted_result)
            measure_index = interrupted.index("--measure-operations")
            interrupted[measure_index:measure_index + 2] = [
                "--measure-seconds", "2"]
            process = subprocess.Popen(
                interrupted, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True)
            time.sleep(.50)
            process.terminate()
            stdout, stderr = process.communicate(timeout=6)
            self.assertNotEqual(process.returncode, 0, stdout + stderr)
            interrupted_failure = json.loads(interrupted_result.read_text())
            self.assertEqual(interrupted_failure["verdict"], "FAIL")
            self.assertIn("interrupted by signal 15",
                          interrupted_failure["failure_reason"])

            # A later attempt targeting the same result path must not erase the
            # original interruption evidence, even when it fails differently.
            preserved = interrupted_result.read_bytes()
            repeated = bad.copy()
            repeated[repeated.index(str(failed))] = str(interrupted_result)
            rerun = subprocess.run(
                repeated, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(rerun.returncode, 0)
            self.assertEqual(interrupted_result.read_bytes(), preserved)

    def test_qualification_preserves_exclusions_and_rejects_raw_drift(self):
        import importlib.util

        path = SCRIPT.with_name("qualification.py")
        spec = importlib.util.spec_from_file_location("swapz_qualification_eval", path)
        qualification = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(qualification)

        def histogram(sample_ns, count):
            index = qualification.latency_bin_index(sample_ns)
            return {
                "count": count, "max_ns": sample_ns,
                "bins": [[index, count]],
            }

        def arm(candidate, raw_write=100.0, screened=True, order="raw-first"):
            swapz = candidate == "swapz"
            writes, reads = 838860, 209716
            write_mbps = raw_write * 1.06 if swapz else raw_write
            lower_write_bytes = (
                int(writes * PAGE * (.8 if swapz else 1.0)) // 512 * 512)
            lower_write_requests = int(83886 * (.8 if swapz else 1.0))
            cpu_per_byte = 1.1e-9 if swapz else 1.0e-9
            elapsed_seconds = writes * PAGE / write_mbps / 1_000_000
            first = (candidate == "raw") == (order == "raw-first")
            arm_start_ns = (
                1_000_000_000_000 if first else 2_000_000_000_000)
            measured_start_ns = arm_start_ns + 1_000_000_000
            measured_end_ns = (
                measured_start_ns + round(elapsed_seconds * 1e9))
            target_before = (
                {field: 0 for field in qualification.TARGET_STATUS_FIELDS}
                if swapz else None)
            target_after = copy.deepcopy(target_before)
            target_delta = ({
                **{field: 0 for field in qualification.TARGET_STATUS_FIELDS},
                "wall_fraction": 0.0,
            } if swapz else None)

            def host_cpu_pair(start_ns, end_ns):
                before = {
                    "ticks": [100] * 8, "pressure_us": 1000,
                    "online_cpus": 4, "affinity_cpus": 4,
                    "tick_hz": 100, "time_ns": start_ns}
                after = {
                    **before,
                    "ticks": [101, 100, 100, 109, 100, 100, 100, 100],
                    "time_ns": end_ns}
                observed = qualification.host_cpu_delta_from_snapshots(
                    before, after, "synthetic")
                return before, after, observed

            pre_host_before, pre_host_after, pre_host = host_cpu_pair(
                arm_start_ns + 250_000_000,
                arm_start_ns + 450_000_000)
            timed_host_before, timed_host_after, timed_host = host_cpu_pair(
                arm_start_ns + 650_000_000,
                measured_end_ns + 250_000_000)
            post_host_before, post_host_after, post_host = host_cpu_pair(
                measured_end_ns + 500_000_000,
                measured_end_ns + 700_000_000)
            return {
                "candidate": candidate, "verdict": "PASS", "source_sha": "a" * 40,
                "claim_boundary": qualification.CONTRACT["claim_boundary"],
                "arm_started_monotonic_ns": arm_start_ns,
                "measured_start_monotonic_ns": measured_start_ns,
                "measured_end_monotonic_ns": measured_end_ns,
                "arm_finished_monotonic_ns":
                    measured_end_ns + 1_000_000_000,
                "arm_boot_id": "11111111-2222-3333-4444-555555555555",
                "loaded_module_provenance": ({
                    "status": "LOADED",
                    "build_source_sha": "a" * 40,
                    "build_source_clean": "1",
                    "allow_physical_backing": "Y",
                } if swapz else {"status": "NOT_LOADED"}),
                "logical_pages": 4096, "occupied_pages": 409, "hot_pages": 327,
                "occupancy_percent": 10, "hot_percent": 8,
                "qd": 8, "read_percent": 20, "fill_fixture_sha256": "f" * 64,
                "churn_fixture_sha256": "c" * 64,
                "fill_content_profile": "balanced", "churn_content_profile": "balanced",
                "workload_seed": 1,
                "operation_recipe_sha256": hashlib.sha256(json.dumps({
                    "seed": 1, "logical": 4096, "occupied": 409,
                    "hot": 327, "qd": 8, "read": 20,
                    "fill": "f" * 64, "churn": "c" * 64,
                }, sort_keys=True).encode()).hexdigest(),
                "warmup_operations": 65536, "warmup_seconds": None,
                "warmup_evidence": {
                    "start_monotonic_ns": arm_start_ns + 100_000_000,
                    "end_monotonic_ns": arm_start_ns + 200_000_000,
                    "duration_seconds": .1,
                    "operations": 65536},
                "measure_operations": 1048576, "measure_seconds_requested": None,
                "read_ops": reads,
                "write_ops": writes, "oracle": {"mismatches": 0},
                "seconds": elapsed_seconds,
                "host_cpu": timed_host,
                "performance_screening": {
                    "status": "SCREENED" if screened else "EXCLUDED",
                    "reasons": [] if screened else ["synthetic noise"],
                    "pre": {
                        "before": pre_host_before, "after": pre_host_after,
                        "observed": pre_host, "reasons": []},
                    "post": {
                        "before": post_host_before, "after": post_host_after,
                        "observed": post_host, "reasons": []}},
                "throughput": {
                    "logical_write_mbps": write_mbps,
                    "logical_read_mbps": reads * PAGE / elapsed_seconds / 1_000_000,
                    "logical_total_mbps": (reads + writes) * PAGE /
                        elapsed_seconds / 1_000_000},
                "measurement_snapshots": {
                    "lower_before": [0] * 16,
                    "lower_after": [
                        10, 0, 80, 0, lower_write_requests, 0,
                        lower_write_bytes // 512, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                    "worker_before_monotonic_ns":
                        arm_start_ns + 600_000_000,
                    "lower_before_monotonic_ns":
                        arm_start_ns + 700_000_000,
                    "target_before_monotonic_ns":
                        arm_start_ns + 750_000_000,
                    "process_before_monotonic_ns":
                        arm_start_ns + 800_000_000,
                    "process_after_monotonic_ns":
                        measured_end_ns + 100_000_000,
                    "target_after_monotonic_ns":
                        measured_end_ns + 150_000_000,
                    "lower_after_monotonic_ns":
                        measured_end_ns + 200_000_000,
                    "worker_after_monotonic_ns":
                        measured_end_ns + 300_000_000,
                    "process_before": {
                        "user_seconds": 0.0, "system_seconds": 0.0,
                        "peak_rss_bytes": 31 * 1024 * 1024},
                    "process_after": {
                        "user_seconds": cpu_per_byte * (reads + writes) * PAGE,
                        "system_seconds": 0.0,
                        "peak_rss_bytes": 32 * 1024 * 1024},
                    "worker_cpu_ns_before": 0, "worker_cpu_ns_after": 0,
                    "host_cpu_before": timed_host_before,
                    "host_cpu_after": timed_host_after},
                "lower_io": {
                    "lower_read_requests": 10,
                    "lower_read_bytes": 80 * 512,
                    "lower_flush_requests": 0,
                    "lower_read_bytes_per_logical_read_byte":
                        (80 * 512) / (reads * PAGE),
                    "lower_write_bytes": lower_write_bytes,
                    "lower_write_requests": lower_write_requests,
                    "lower_write_bytes_per_logical_write_byte":
                        lower_write_bytes / (writes * PAGE),
                    "lower_write_requests_per_1000_logical_writes":
                        lower_write_requests * 1000 / writes},
                "latency": {
                    "read_count": reads,
                    "write_count": writes,
                    "read_histogram": histogram(
                        105 if swapz else 100, reads),
                    "write_histogram": histogram(
                        105 if swapz else 100, writes),
                    "read_p50_ns": qualification.latency_bin_upper(
                        qualification.latency_bin_index(
                            105 if swapz else 100)),
                    "read_p95_ns": qualification.latency_bin_upper(
                        qualification.latency_bin_index(
                            105 if swapz else 100)),
                    "read_p99_ns": qualification.latency_bin_upper(
                        qualification.latency_bin_index(
                            105 if swapz else 100)),
                    "read_max_ns": 105 if swapz else 100,
                    "write_p50_ns": qualification.latency_bin_upper(
                        qualification.latency_bin_index(
                            105 if swapz else 100)),
                    "write_p95_ns": qualification.latency_bin_upper(
                        qualification.latency_bin_index(
                            105 if swapz else 100)),
                    "write_p99_ns": qualification.latency_bin_upper(
                        qualification.latency_bin_index(
                            105 if swapz else 100)),
                    "write_max_ns": 105 if swapz else 100},
                "cpu": {
                    "measured_cpu_seconds_per_useful_byte": cpu_per_byte,
                    "replay_user_seconds": cpu_per_byte * (reads + writes) * PAGE,
                    "replay_system_seconds": 0.0,
                    "exported_swapz_worker_cpu_seconds": 0.0,
                },
                "resources": {
                    "replay_peak_rss_bytes": 32 * 1024 * 1024,
                    "replay_process_maxrss_bytes": 32 * 1024 * 1024,
                    "replay_measurement_start_maxrss_bytes": 31 * 1024 * 1024,
                    "replay_measurement_peak_rss_growth_bytes": 1024 * 1024,
                    "metadata_and_target_peak_ram_bytes":
                        512 * 1024 * 1024 if swapz else 0,
                },
                "target_status_before": target_before,
                "target_status_after": target_after,
                "gc": target_delta,
                "device_identity": {
                    "physical_partuuid": "f13428f6-01",
                    "physical_device_bytes": 124787884032,
                    "lower_major_minor": "8:1",
                    "parent_major_minor": "8:0",
                    "parent_model": "SD",
                    "parent_transport": "usb",
                    "dm_uuid": "SWAPZ-BENCH-0123456789abcdef0123456789abcdef"
                        if swapz else None,
                },
            }

        excluded = qualification.compare_pair(
            arm("raw", screened=False), arm("swapz"), "sd-service-balanced",
            "excluded", 1, "raw-first")
        self.assertTrue(excluded["excluded"])
        self.assertIn("synthetic noise", " ".join(excluded["exclusion_reasons"]))
        incomplete = qualification.evaluate([excluded])
        self.assertFalse(incomplete["records"][0]["analysis_usable"])
        self.assertEqual(
            incomplete["decisions"]["sd-service-balanced"]["status"], "INCOMPLETE")

        orders = ["raw-first", "swapz-first", "swapz-first", "raw-first", "raw-first"]
        raw_rates = [100.0, 100.0, 100.0, 100.0, 120.0]
        pairs = [qualification.compare_pair(
            arm("raw", raw_write=rate, order=orders[index - 1]),
            arm("swapz", raw_write=rate, order=orders[index - 1]),
            "sd-service-balanced", f"pair-{index}", index, orders[index - 1])
            for index, rate in enumerate(raw_rates, 1)]
        summary = qualification.evaluate(pairs)
        self.assertGreater(summary["raw_repeat_spread"]["sd-service-balanced"], .10)
        self.assertEqual(
            summary["decisions"]["sd-service-balanced"]["status"], "INCOMPLETE")
        self.assertTrue(all(
            not row["analysis_usable"] for row in summary["records"]
            if row["workload"] == "sd-service-balanced"))

        stable_pairs = [
            qualification.compare_pair(
                arm("raw", order=orders[index - 1]),
                arm("swapz", order=orders[index - 1]), "sd-service-balanced",
                f"stable-{index}", index, orders[index - 1])
            for index in range(1, 6)]
        stable = qualification.evaluate(stable_pairs)
        self.assertEqual(stable["campaign_source_sha"], "a" * 40)
        self.assertEqual(stable["decisions"]["sd-service-balanced"]["status"], "PASS")

        # Forged derived columns, counters, RSS or arm chronology must never
        # promote the otherwise successful five-pair cohort.
        for corrupt in (
                lambda row: row["raw"]["lower_io"].update(lower_write_bytes=1),
                lambda row: row["swapz"]["cpu"].update(
                    measured_cpu_seconds_per_useful_byte=1e-15),
                lambda row: row["raw"]["resources"].update(
                    replay_process_maxrss_bytes=0),
                lambda row: row["raw"].update(arm_finished_monotonic_ns=99),
                lambda row: row["swapz"]["device_identity"].update(
                    parent_major_minor="8:16"),
                lambda row: row["swapz"].pop("arm_boot_id"),
                lambda row: row["swapz"]["lower_io"].update(
                    lower_write_requests=True),
                lambda row: (
                    row["raw"].pop("warmup_seconds"),
                    row["swapz"].pop("warmup_seconds")),
                lambda row: (
                    row["raw"].update(operation_recipe_sha256="0" * 64),
                    row["swapz"].update(operation_recipe_sha256="0" * 64)),
                lambda row: row["raw"]["latency"].update(read_p50_ns=101),
                lambda row: row["swapz"].update(
                    claim_boundary="direct NAND-wear reduction proven"),
                lambda row: row["raw"]["measurement_snapshots"][
                    "lower_after"].__setitem__(6, 1),
                lambda row: row["swapz"]["measurement_snapshots"][
                    "lower_after"].__setitem__(4, 0),
                lambda row: row["raw"]["measurement_snapshots"][
                    "process_after"].update(user_seconds=0.0),
                lambda row: row["swapz"]["measurement_snapshots"][
                    "process_after"].update(peak_rss_bytes=0),
                lambda row: row["raw"]["throughput"].update(
                    logical_read_mbps=0.0),
                lambda row: row["swapz"]["throughput"].update(
                    logical_total_mbps=0.0),
                lambda row: row["raw"]["measurement_snapshots"].pop(
                    "lower_before"),
                lambda row: row["swapz"].pop("measured_end_monotonic_ns"),
                lambda row: row["raw"]["warmup_evidence"].update(
                    operations=65535),
                lambda row: row["swapz"]["measurement_snapshots"].update(
                    process_before_monotonic_ns=
                        row["swapz"]["measured_start_monotonic_ns"] + 1),
                lambda row: row["swapz"]["target_status_after"].update(
                    gc_wall_ns=1),
                lambda row: row["swapz"]["target_status_before"].update(
                    failed=1),
                lambda row: row["swapz"]["gc"].update(
                    wall_fraction=.25),
                lambda row: row["raw"]["performance_screening"]["pre"][
                    "after"]["ticks"].__setitem__(0, 200),
                lambda row: row["swapz"]["host_cpu"].update(
                    steal_fraction=.5),
                lambda row: row["raw"]["measurement_snapshots"].pop(
                    "host_cpu_before"),
                lambda row: row["swapz"].update(resources=["malformed"]),
                lambda row: row["swapz"].update(
                    device_identity=["malformed"]),
        ):
            tampered_pairs = json.loads(json.dumps(stable_pairs))
            corrupt(tampered_pairs[0])
            tampered = qualification.evaluate(tampered_pairs)
            self.assertEqual(
                tampered["decisions"]["sd-service-balanced"]["status"],
                "INCOMPLETE")
            self.assertFalse(tampered["records"][0]["analysis_usable"])

        # JSON decoding is strict: duplicate keys and non-standard numeric
        # constants cannot be converted into apparently valid evidence.
        with tempfile.TemporaryDirectory() as directory:
            duplicate = Path(directory) / "duplicate.json"
            duplicate.write_text('{"status":"PASS","status":"EXCLUDED"}')
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                qualification._load_json_path(duplicate)
            nonfinite = Path(directory) / "nonfinite.json"
            for payload in ('NaN', 'Infinity', '-Infinity',
                            '1e999', '-1e999'):
                with self.subTest(nonfinite_json=payload):
                    nonfinite.write_text('{"value":' + payload + '}')
                    with self.assertRaisesRegex(
                            ValueError, "non-finite JSON number"):
                        qualification._load_json_path(nonfinite)
            truncated = Path(directory) / "truncated.json"
            truncated.write_text('{"value":')
            with self.assertRaises(ValueError):
                qualification._load_json_path(truncated)
        with self.assertRaisesRegex(ValueError, "must be finite"):
            qualification.number(10 ** 10000, "oversized integer")

        # Python bool is an int subclass; QD1 must still require a JSON integer.
        qd1 = arm("raw")
        qd1["qd"] = True
        qd1["operation_recipe_sha256"] = hashlib.sha256(json.dumps({
            "seed": 1, "logical": 4096, "occupied": 409,
            "hot": 327, "qd": True, "read": 20,
            "fill": "f" * 64, "churn": "c" * 64,
        }, sort_keys=True).encode()).hexdigest()
        qd1_reasons = qualification.validate_arm(
            qd1, "sd-service-qd1-balanced", "raw")
        self.assertTrue(any(
            "qd is missing, mistyped" in reason for reason in qd1_reasons))

        self.assertTrue(stable["campaign_target_consistent"])
        self.assertEqual(
            stable["campaign_target_identity"],
            {
                "physical_partuuid": "f13428f6-01",
                "physical_device_bytes": 124787884032,
                "lower_major_minor": "8:1",
                "parent_major_minor": "8:0",
                "parent_model": "SD",
                "parent_transport": "usb",
            })

        for failed_value, error_value in (
                (1, 0), (0, -5), (False, 0), (0, "0")):
            with self.subTest(
                    failed_value=failed_value, error_value=error_value):
                unhealthy_raw = arm("raw")
                unhealthy_swapz = arm("swapz")
                unhealthy_swapz["gc"] = {
                    "failed": failed_value, "error": error_value}
                unhealthy_pair = qualification.compare_pair(
                    unhealthy_raw, unhealthy_swapz,
                    "sd-service-balanced", "unhealthy", 1, "raw-first")
                self.assertTrue(unhealthy_pair["excluded"])
                self.assertIn(
                    "swapz target health failed or is unavailable",
                    unhealthy_pair["exclusion_reasons"])

        self.assertTrue(
            qualification.target_health_ok({"failed": 0, "error": 0}))
        sustained_source = SCRIPT.with_name("sustained-replay.py").read_text()
        self.assertIn(
            'QUALIFICATION["target_health_ok"](gc)',
            sustained_source)

        # Malformed physical PARTUUID evidence must never enter analysis even
        # when both arms repeat the same bad identity. Evidence is canonical
        # lowercase; hardware-facing normalization happens before pair records.
        for bad_partuuid in (
                "--------", "f13428f6--01", "f13428f6.",
                "1234-567", "F13428F6-01"):
            with self.subTest(bad_partuuid=bad_partuuid):
                bad_raw = arm("raw")
                bad_swapz = arm("swapz")
                bad_raw["device_identity"]["physical_partuuid"] = bad_partuuid
                bad_swapz["device_identity"]["physical_partuuid"] = bad_partuuid
                bad_pair = qualification.compare_pair(
                    bad_raw, bad_swapz, "sd-service-balanced",
                    "bad-partuuid", 1, "raw-first")
                self.assertTrue(bad_pair["excluded"])
                self.assertIsNone(qualification.pair_target_identity(bad_pair))
                self.assertIn(
                    "physical identity is missing or malformed",
                    " ".join(bad_pair["exclusion_reasons"]))

        # Historical v1 pair records may predate the explicit protocol
        # field; retain that deliberate compatibility. V2 still requires it.
        legacy_v1_pairs = json.loads(json.dumps(stable_pairs))
        for legacy_pair in legacy_v1_pairs:
            legacy_pair.pop("qualification_protocol")
        legacy_v1 = qualification.evaluate(legacy_v1_pairs, protocol="v1")
        self.assertEqual(
            legacy_v1["decisions"]["sd-service-balanced"]["status"], "PASS")

        # Stored pair deltas are derived evidence, not an editable acceptance
        # surface. A changed delta with unchanged arms must be excluded.
        tampered_pairs = json.loads(json.dumps(stable_pairs))
        tampered_pairs[0]["deltas"]["useful_write"] = 9.0
        tampered = qualification.evaluate(tampered_pairs)
        self.assertEqual(
            tampered["decisions"]["sd-service-balanced"]["status"],
            "INCOMPLETE")
        self.assertTrue(any(
            "stored pair deltas differ" in reason
            for reason in tampered["records"][0]["analysis_exclusion_reasons"]))

        # Internally matched pairs from a different physical lower cannot be
        # pooled into one campaign even when excluded by screening.
        other_raw = arm("raw", screened=False, order=orders[1])
        other_swapz = arm("swapz", screened=False, order=orders[1])
        for other_arm in (other_raw, other_swapz):
            other_arm["device_identity"] = {
                **other_arm["device_identity"],
                "physical_partuuid": "deadbeef-01",
                "lower_major_minor": "8:17",
            }
        mixed_target_pairs = list(stable_pairs)
        mixed_target_pairs[1] = qualification.compare_pair(
            other_raw, other_swapz,
            "sd-service-balanced", "other-target", 2, orders[1])
        self.assertTrue(mixed_target_pairs[1]["excluded"])
        mixed_target = qualification.evaluate(mixed_target_pairs)
        self.assertFalse(mixed_target["campaign_target_consistent"])
        self.assertIsNone(mixed_target["campaign_target_identity"])
        self.assertEqual(
            mixed_target["decisions"]["sd-service-balanced"]["status"],
            "INCOMPLETE")
        self.assertIsNone(qualification.pair_target_identity({
            "workload": "anonymous-swap",
            "raw": {"swap_device_identity": ["malformed"]},
            "swapz": {"swap_device_identity": {}}}))

        missing_lower_raw = arm("raw")
        missing_lower_swapz = arm("swapz")
        missing_lower_raw["device_identity"].pop("lower_major_minor")
        missing_lower_swapz["device_identity"].pop("lower_major_minor")
        missing_lower = qualification.compare_pair(
            missing_lower_raw, missing_lower_swapz, "sd-service-balanced",
            "missing-lower", 1, "raw-first")
        self.assertTrue(missing_lower["excluded"])
        self.assertIn(
            "physical identity is missing or malformed",
            " ".join(missing_lower["exclusion_reasons"]))

        # An excluded original cannot be hidden by a full set of later PASS
        # attempts. Preserve the original attempt and block promotion.
        masked = qualification.evaluate([*stable_pairs, excluded])
        self.assertEqual(
            masked["decisions"]["sd-service-balanced"]["status"], "INCOMPLETE")
        self.assertEqual(
            masked["decisions"]["sd-service-balanced"]["attempted_pairs"], 6)
        self.assertEqual(len(masked["records"]), 6)

        # All source revisions must match across the entire campaign.
        mixed_pairs = list(stable_pairs)
        mixed_pairs[1] = qualification.compare_pair(
            {**arm("raw", order=orders[1]), "source_sha": "b" * 40},
            {**arm("swapz", order=orders[1]), "source_sha": "b" * 40},
            "sd-service-balanced", "mixed-revision", 2, orders[1])
        mixed = qualification.evaluate(mixed_pairs)
        self.assertIsNone(mixed["campaign_source_sha"])
        self.assertEqual(
            mixed["decisions"]["sd-service-balanced"]["status"], "INCOMPLETE")
        self.assertTrue(all(
            not pair["analysis_usable"] for pair in mixed["records"]))

        # Pair IDs must identify distinct attempted repeats.
        duplicate_ids = list(stable_pairs)
        duplicate_ids[1] = {
            **stable_pairs[1], "pair_id": stable_pairs[0]["pair_id"]}
        duplicate = qualification.evaluate(duplicate_ids)
        self.assertEqual(
            duplicate["decisions"]["sd-service-balanced"]["status"], "INCOMPLETE")
        self.assertFalse(
            duplicate["decisions"]["sd-service-balanced"]["pair_ids_unique"])


    def test_physical_sustained_gc_headroom_requires_actual_counter(self):
        import importlib.util

        path = SCRIPT.with_name("qualification.py")
        spec = importlib.util.spec_from_file_location(
            "swapz_sustained_headroom_contract", path)
        qualification = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(qualification)

        raw = {
            "throughput": {"logical_write_mbps": 100.0},
            "lower_io": {
                "lower_write_bytes_per_logical_write_byte": 1.0,
                "lower_write_requests_per_1000_logical_writes": 100,
            },
            "latency": {"read_p99_ns": 1000, "write_p99_ns": 1000},
            "cold_read": {"p99_ns": 1000, "pages": 16},
            "overwrite": {"measured_hot_pages_rewritten": 1},
        }
        swapz = {
            "throughput": {"logical_write_mbps": 110.0},
            "lower_io": {
                "lower_write_bytes_per_logical_write_byte": 0.8,
                "lower_write_requests_per_1000_logical_writes": 80,
            },
            "latency": {"read_p99_ns": 1050, "write_p99_ns": 1050},
            "cold_read": {"p99_ns": 1050, "pages": 16},
            "minute_buckets": [
                {"logical_write_mbps": 110.0, "p99_ns": 1000}
                for _ in range(4)],
            "gc": {
                "wall_fraction": 0.05, "gc_no_headroom_skips": 0,
                "gc_victims": 2, "gc_pages": 10,
                "segment_program_sum": 3, "failed": 0, "error": 0,
            },
            "resources": {
                "replay_peak_rss_bytes": 32 * 1024 * 1024,
                "metadata_and_target_peak_ram_bytes": 512 * 1024 * 1024,
            },
            "overwrite": {"measured_hot_pages_rewritten": 2},
            "oracle": {"mismatches": 0},
            "occupancy_percent": 90,
            "max_no_progress_seconds": 1.0,
        }
        passing = qualification.sustained_decision(
            {"raw": raw, "swapz": swapz})
        self.assertEqual(passing["status"], "PASS")
        self.assertTrue(passing["checks"]["gc_headroom"])

        # A missing/negative/positive counter cannot be interpreted as zero.
        for observed in (None, -1, 1, True, "0"):
            with self.subTest(observed=observed):
                gc = dict(swapz["gc"])
                if observed is None:
                    gc.pop("gc_no_headroom_skips")
                else:
                    gc["gc_no_headroom_skips"] = observed
                failed = qualification.sustained_decision(
                    {"raw": raw, "swapz": {**swapz, "gc": gc}})
                self.assertEqual(failed["status"], "FAIL")
                self.assertFalse(failed["checks"]["gc_headroom"])

        # JSON numeric evidence is not coerced from strings or booleans.
        malformed_gc = {
            **swapz, "gc": {**swapz["gc"], "gc_victims": "2"}}
        self.assertEqual(
            qualification.sustained_decision(
                {"raw": raw, "swapz": malformed_gc})["status"],
            "FAIL")
        malformed_cold_read = {
            **swapz, "cold_read": {**swapz["cold_read"], "pages": "16"}}
        self.assertEqual(
            qualification.sustained_decision(
                {"raw": raw, "swapz": malformed_cold_read})["status"],
            "FAIL")

        malformed_oracle = {
            **swapz, "oracle": {"mismatches": False}}
        self.assertEqual(
            qualification.sustained_decision(
                {"raw": raw, "swapz": malformed_oracle})["status"],
            "FAIL")

    def test_sustained_coverage_requires_full_hour_and_continuous_gc_evidence(self):
        import importlib.util

        path = SCRIPT.with_name("qualification.py")
        spec = importlib.util.spec_from_file_location(
            "swapz_hour_coverage_qualification", path)
        qualification = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(qualification)

        minute_latency_index = qualification.latency_bin_index(1)
        minute_latency = qualification.latency_bin_upper(
            minute_latency_index)
        minute_buckets = [
            {
                "minute": index, "duration_seconds": 60.0,
                "read_operations": 1, "write_operations": 1,
                "operations": 2,
                "logical_write_mbps": PAGE / 60.0 / 1_000_000,
                "p95_ns": minute_latency, "p99_ns": minute_latency,
                "latency_histogram": {
                    "count": 2, "max_ns": 1,
                    "bins": [[minute_latency_index, 2]],
                },
                "read_latency_histogram": {
                    "count": 1, "max_ns": 1,
                    "bins": [[minute_latency_index, 1]],
                },
                "write_latency_histogram": {
                    "count": 1, "max_ns": 1,
                    "bins": [[minute_latency_index, 1]],
                },
                "read_p95_ns": minute_latency, "read_p99_ns": minute_latency,
                "write_p95_ns": minute_latency, "write_p99_ns": minute_latency,
            }
            for index in range(60)]
        arm_started_ns = 1_000_000_000
        measured_started_ns = arm_started_ns
        measured_finished_ns = measured_started_ns + 3600_000_000_000
        intervals = [
            {
                "interval": index,
                "start_monotonic_ns":
                    arm_started_ns + index * 60_000_000_000,
                "end_monotonic_ns":
                    arm_started_ns + (index + 1) * 60_000_000_000,
                "start_seconds": float(index * 60),
                "end_seconds": float((index + 1) * 60),
                "duration_seconds": 60.0,
                "max_no_progress_seconds": 1.0,
                "gc": {
                    "failed": 0, "error": 0, "gc_no_headroom_skips": 0,
                    "gc_wall_ns": 1 if index == 20 else 0,
                    "gc_victims": 1 if index == 20 else 0,
                    "gc_pages": 1 if index == 20 else 0,
                    "segment_program_sum": 1 if index == 20 else 0,
                },
            }
            for index in range(60)]
        for index, row in enumerate(minute_buckets):
            row["start_monotonic_ns"] = (
                measured_started_ns + index * 60_000_000_000)
            row["end_monotonic_ns"] = (
                measured_started_ns + (index + 1) * 60_000_000_000)
        raw = {
            "arm_started_monotonic_ns": arm_started_ns,
            "measured_start_monotonic_ns": measured_started_ns,
            "measured_end_monotonic_ns": measured_finished_ns,
            "arm_finished_monotonic_ns":
                measured_finished_ns + 60_000_000_000,
            "seconds": 3600.0, "logical_pages": 100,
            "occupied_pages": 90, "read_ops": 60, "write_ops": 60,
            "minute_buckets": minute_buckets, "sustained_intervals": intervals,
            "latency": {
                "read_histogram": {
                    "count": 60, "max_ns": 1,
                    "bins": [[minute_latency_index, 60]],
                },
                "write_histogram": {
                    "count": 60, "max_ns": 1,
                    "bins": [[minute_latency_index, 60]],
                },
            },
            "occupancy_transitions": [
                {"phase": phase, "occupied_pages": 0 if index == 0 else 90}
                for index, phase in enumerate((
                    "initial", "post-fill", "post-warmup", "measured-end"))],
            "oracle": {"verified_pages": 90},
            "gc": {
                "gc_wall_ns": 1, "gc_no_headroom_skips": 0,
                "gc_victims": 1, "gc_pages": 1,
                "segment_program_sum": 1,
            },
        }
        self.assertEqual(
            qualification.sustained_coverage_reasons(raw, "raw"), [])
        self.assertEqual(
            qualification.sustained_coverage_reasons(raw, "swapz"), [])
        corruptions = (
            lambda arm: arm.update(seconds=3599.0),
            lambda arm: arm.update(
                measured_start_monotonic_ns=
                    arm["measured_start_monotonic_ns"] + 1_000_000_000),
            lambda arm: arm.update(
                measured_end_monotonic_ns=
                    arm["measured_end_monotonic_ns"] + 1_000_000_000),
            lambda arm: arm["minute_buckets"].pop(30),
            lambda arm: arm["minute_buckets"][0].update(write_operations=0),
            lambda arm: arm["minute_buckets"][0].update(
                logical_write_mbps=999.0),
            lambda arm: arm["minute_buckets"][0].update(duration_seconds=59.0),
            lambda arm: arm["minute_buckets"][1].update(
                start_monotonic_ns=
                    arm["minute_buckets"][1]["start_monotonic_ns"] + 1),
            lambda arm: arm["minute_buckets"][1].update(
                end_monotonic_ns=
                    arm["minute_buckets"][1]["end_monotonic_ns"] + 1),
            lambda arm: [
                row.update(start_monotonic_ns=row["start_monotonic_ns"] + 1)
                for row in arm["minute_buckets"]],
            lambda arm: arm["minute_buckets"][0][
                "latency_histogram"]["bins"][0].__setitem__(1, 1),
            lambda arm: arm["sustained_intervals"].pop(),
            lambda arm: arm["sustained_intervals"][1].update(start_seconds=61.0),
            lambda arm: arm["sustained_intervals"][1].update(
                start_monotonic_ns=arm["sustained_intervals"][0][
                    "start_monotonic_ns"]),
            lambda arm: arm["sustained_intervals"][20].update(
                max_no_progress_seconds=11.0),
            lambda arm: arm["sustained_intervals"][20]["gc"].update(
                gc_no_headroom_skips=1),
            lambda arm: arm["sustained_intervals"][20]["gc"].pop(
                "gc_no_headroom_skips"),
            lambda arm: arm["gc"].update(segment_program_sum=0),
            lambda arm: arm["occupancy_transitions"][3].update(
                occupied_pages=0),
            lambda arm: arm["oracle"].update(verified_pages=89),
        )
        for corrupt in corruptions:
            tampered = copy.deepcopy(raw)
            corrupt(tampered)
            with self.subTest(corrupt=corrupt):
                self.assertTrue(
                    qualification.sustained_coverage_reasons(
                        tampered, "swapz"))

        # A changed combined minute histogram must still agree with its
        # independently counted READ and WRITE histograms before it can be
        # used to alter the first/last-quartile drift.
        redistributed_latency = copy.deepcopy(raw)
        changed_minute = redistributed_latency["minute_buckets"][0]
        changed_index = qualification.latency_bin_index(2)
        changed_tail_ns = qualification.latency_bin_upper(changed_index)
        changed_minute["latency_histogram"] = {
            "count": 2, "max_ns": 2, "bins": [[changed_index, 2]],
        }
        changed_minute["p95_ns"] = changed_tail_ns
        changed_minute["p99_ns"] = changed_tail_ns
        self.assertTrue(any(
            "minute combined histogram differs from READ/WRITE distributions"
            in reason for reason in qualification.sustained_coverage_reasons(
                redistributed_latency, "swapz")))

        # Rewriting a whole-arm histogram without updating the original
        # minute distributions is equally inconsistent.
        altered_whole_arm = copy.deepcopy(raw)
        altered_whole_arm["latency"]["read_histogram"] = {
            "count": 60, "max_ns": 2, "bins": [[changed_index, 60]],
        }
        self.assertTrue(any(
            "minute read bins differ from whole-arm evidence"
            in reason for reason in qualification.sustained_coverage_reasons(
                altered_whole_arm, "swapz")))

        # Exchange high-tail bins between two minutes without changing
        # whole-arm histograms, operation totals or per-minute counts.
        compensated = copy.deepcopy(raw)
        late = compensated["minute_buckets"][-1]
        early = compensated["minute_buckets"][0]
        high_index = qualification.latency_bin_index(2)
        high_p99 = qualification.latency_bin_upper(high_index)
        late["latency_histogram"] = {
            "count": 2, "max_ns": 2, "bins": [[high_index, 2]]}
        for operation in ("read", "write"):
            late[f"{operation}_latency_histogram"] = {
                "count": 1, "max_ns": 2, "bins": [[high_index, 1]]}
            compensated["latency"][f"{operation}_histogram"] = {
                "count": 60, "max_ns": 2,
                "bins": [[minute_latency_index, 59], [high_index, 1]]}
        for field in ("p95_ns", "p99_ns", "read_p95_ns", "read_p99_ns",
                      "write_p95_ns", "write_p99_ns"):
            late[field] = high_p99
        self.assertEqual(
            qualification.sustained_coverage_reasons(compensated, "swapz"), [])
        redistributed = copy.deepcopy(compensated)
        first_minute = redistributed["minute_buckets"][0]
        last_minute = redistributed["minute_buckets"][-1]
        first_minute["latency_histogram"] = {
            "count": 2, "max_ns": 2, "bins": [[high_index, 2]]}
        last_minute["latency_histogram"] = {
            "count": 2, "max_ns": 1,
            "bins": [[minute_latency_index, 2]]}
        for field in ("p95_ns", "p99_ns"):
            first_minute[field] = high_p99
            last_minute[field] = minute_latency
        self.assertNotEqual(
            qualification.quartile_ratio(compensated["minute_buckets"], "p99_ns"),
            qualification.quartile_ratio(redistributed["minute_buckets"], "p99_ns"))
        self.assertTrue(any(
            "minute combined histogram differs from READ/WRITE distributions"
            in reason
            for reason in qualification.sustained_coverage_reasons(
                redistributed, "swapz")))

        outside_window_gc = copy.deepcopy(raw)
        outside_window_gc["sustained_intervals"][20]["gc"].update(
            gc_victims=0, gc_pages=0)
        after_measure = copy.deepcopy(
            outside_window_gc["sustained_intervals"][-1])
        after_measure.update(
            interval=60,
            start_monotonic_ns=measured_finished_ns,
            end_monotonic_ns=measured_finished_ns + 60_000_000_000,
            start_seconds=3600.0,
            end_seconds=3660.0,
        )
        after_measure["gc"].update(
            gc_wall_ns=1, gc_victims=1, gc_pages=1)
        outside_window_gc["sustained_intervals"].append(after_measure)
        # Preserve the enclosing target-counter totals so this mutant reaches
        # the absolute measured-window check rather than failing conservation.
        outside_window_gc["gc"].update(
            gc_wall_ns=2, gc_victims=1, gc_pages=1,
            segment_program_sum=1)
        self.assertTrue(any(
            "fully measured interval with GC relocation" in reason
            for reason in qualification.sustained_coverage_reasons(
                outside_window_gc, "swapz")))

    def test_sustained_interval_sampler_gc_and_trailing_gap(self):
        import importlib.util
        import time

        path = SCRIPT.with_name("sustained-replay.py")
        spec = importlib.util.spec_from_file_location(
            "swapz_interval_audit", path)
        sustained = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sustained)

        progress = sustained.ProgressTracker()
        with progress.lock:
            progress.last_ns = time.monotonic_ns() - 20_000_000
        self.assertGreaterEqual(progress.snapshot_max_gap_ns(), 20_000_000)

        sampler = sustained.SustainedIntervalSampler(None, progress)
        sampler.start_ns = 100
        sampler.previous = {
            "time_ns": 100, "host_cpu": {"ticks": (0,)},
            "lower": None, "max_no_progress_ns": 0,
            "target_status": {
                "gc_wall_ns": 0, "gc_role_rotations": 2, "cursor": 8,
                "failed": 0, "error": 0},
        }
        current = {
            "time_ns": 1_000_000_100, "host_cpu": {"ticks": (1,)},
            "lower": None, "max_no_progress_ns": 20_000_000,
            "target_status": {
                "gc_wall_ns": 10_000_000, "gc_role_rotations": 5,
                "cursor": 1, "failed": 0, "error": 0},
        }
        with mock.patch.dict(
                sustained.REPLAY,
                {"host_cpu_delta": lambda before, after: {
                    "status": "AVAILABLE"}}):
            sampler._append(current)
        self.assertEqual(len(sampler.rows), 1)
        row = sampler.rows[0]
        self.assertEqual(row["start_monotonic_ns"], 100)
        self.assertEqual(row["end_monotonic_ns"], 1_000_000_100)
        self.assertEqual(row["gc"]["gc_role_rotations"], 3)
        self.assertEqual(row["gc"]["cursor"], 1)
        self.assertAlmostEqual(row["gc"]["wall_fraction"], .01)
        self.assertEqual(row["max_no_progress_seconds"], .02)

    def test_sustained_interval_sampler_failure_is_fail_closed(self):
        import importlib.util

        path = SCRIPT.with_name("sustained-replay.py")
        spec = importlib.util.spec_from_file_location(
            "swapz_interval_failure_audit", path)
        sustained = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sustained)

        class FailingSampler:
            def __init__(self):
                self.rows = [{"interval": 0}]

            def stop(self):
                raise ValueError("telemetry failed")

            def observer_summary(self):
                return {
                    "samples": 1, "wall_seconds": .01,
                    "thread_cpu_seconds": .0005,
                    "child_user_seconds": .001,
                    "child_system_seconds": .002,
                    "child_cpu_seconds": .003,
                    "scope": "synthetic observer",
                }

        partial = {}
        with self.assertRaisesRegex(ValueError, "telemetry failed"):
            sustained.stop_interval_sampler(
                FailingSampler(), partial, primary_failure_active=False)
        self.assertEqual(
            partial["interval_sampler_failure"], "telemetry failed")
        self.assertEqual(partial["sustained_intervals"], [{"interval": 0}])
        self.assertEqual(
            partial["sustained_observer_overhead"]["child_cpu_seconds"], .003)

        partial = {}
        rows = sustained.stop_interval_sampler(
            FailingSampler(), partial, primary_failure_active=True)
        self.assertEqual(rows, [{"interval": 0}])
        self.assertEqual(partial["sustained_intervals"], rows)
        self.assertEqual(
            partial["interval_sampler_failure"], "telemetry failed")
        self.assertEqual(
            partial["sustained_observer_overhead"]["child_cpu_seconds"], .003)

        progress = sustained.ProgressTracker()
        observer = sustained.SustainedIntervalSampler(None, progress)
        observer._snapshot()
        observer_cost = observer.observer_summary()
        self.assertEqual(observer_cost["samples"], 1)
        self.assertGreaterEqual(observer_cost["wall_seconds"], 0)
        self.assertGreaterEqual(observer_cost["thread_cpu_seconds"], 0)
        self.assertGreaterEqual(observer_cost["child_cpu_seconds"], 0)

    def test_evidence_io_is_atomic_create_only_and_signal_safe(self):
        import signal
        import stat
        import evidence_io

        previous_sigint = signal.getsignal(signal.SIGINT)
        previous_sigterm = signal.getsignal(signal.SIGTERM)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = root / "evidence.json"
            evidence_io.write_new_json(result, {"status": "PASS", "value": 1})
            expected = result.read_bytes()
            self.assertEqual(
                json.loads(expected), {"status": "PASS", "value": 1})
            self.assertEqual(stat.S_IMODE(result.stat().st_mode), 0o600)
            self.assertEqual(signal.getsignal(signal.SIGINT), previous_sigint)
            self.assertEqual(signal.getsignal(signal.SIGTERM), previous_sigterm)

            with self.assertRaises(FileExistsError):
                evidence_io.write_new_json(
                    result, {"status": "FAIL", "value": 2})
            self.assertEqual(result.read_bytes(), expected)

            nonfinite = root / "nonfinite.json"
            with self.assertRaisesRegex(ValueError, "Out of range float"):
                evidence_io.write_new_json(
                    nonfinite, {"status": "PASS", "value": float("nan")})
            self.assertFalse(nonfinite.exists())

            failed = root / "link-failure.json"
            with mock.patch.object(
                    evidence_io.os, "link",
                    side_effect=OSError("synthetic link failure")):
                with self.assertRaisesRegex(OSError, "synthetic link failure"):
                    evidence_io.write_new_json(failed, {"status": "FAIL"})
            self.assertFalse(failed.exists())
            self.assertEqual(
                [path.name for path in root.iterdir()
                 if ".swapz-tmp-" in path.name],
                [])
            self.assertEqual(signal.getsignal(signal.SIGINT), previous_sigint)
            self.assertEqual(signal.getsignal(signal.SIGTERM), previous_sigterm)

    def test_physical_module_provenance_is_fail_closed(self):
        import importlib.util

        path = SCRIPT.with_name("qualification.py")
        spec = importlib.util.spec_from_file_location(
            "swapz_physical_provenance_contract", path)
        qualification_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(qualification_module)

        source_sha = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            parameter_base = Path(directory) / "parameters"
            self.assertEqual(
                qualification_module.capture_loaded_module_provenance(
                    source_sha, False, parameter_base),
                {"status": "NOT_LOADED"})
            with self.assertRaisesRegex(ValueError, "requires loaded"):
                qualification_module.capture_loaded_module_provenance(
                    source_sha, True, parameter_base)

            parameter_base.mkdir()
            (parameter_base / "build_source_sha").write_text(source_sha)
            (parameter_base / "build_source_clean").write_text("1\n")
            (parameter_base / "allow_physical_backing").write_text("Y\n")
            observed = qualification_module.capture_loaded_module_provenance(
                source_sha, True, parameter_base)
            self.assertEqual(observed["status"], "LOADED")
            with self.assertRaisesRegex(ValueError, "requires dm_swapz"):
                qualification_module.capture_loaded_module_provenance(
                    source_sha, False, parameter_base)
            (parameter_base / "build_source_clean").write_text("0\n")
            with self.assertRaisesRegex(ValueError, "not exact"):
                qualification_module.capture_loaded_module_provenance(
                    source_sha, True, parameter_base)

        good = {
            "source_sha": source_sha,
            "loaded_module_provenance": {
                "status": "LOADED", "build_source_sha": source_sha,
                "build_source_clean": "1",
                "allow_physical_backing": "Y",
            },
        }
        self.assertEqual(
            qualification_module.validate_module_provenance(
                good, "swapz"), [])
        missing = dict(good)
        del missing["loaded_module_provenance"]
        self.assertTrue(
            qualification_module.validate_module_provenance(
                missing, "swapz"))
        self.assertEqual(
            qualification_module.validate_module_provenance(
                {"loaded_module_provenance": {"status": "NOT_LOADED"}},
                "raw"),
            [])

    def test_physical_campaign_evidence_helper_is_importable(self):
        import importlib.util

        path = SCRIPT.with_name("physical-campaign-evidence.py")
        spec = importlib.util.spec_from_file_location(
            "swapz_campaign_syntax_contract", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(callable(module.seal_campaign))
        self.assertTrue(callable(module.write_new_json))

    def test_physical_campaign_evidence_seals_all_attempts_and_policy(self):
        import importlib.util

        evidence_path = SCRIPT.with_name("physical-campaign-evidence.py")
        evidence_spec = importlib.util.spec_from_file_location(
            "swapz_campaign_evidence", evidence_path)
        evidence = importlib.util.module_from_spec(evidence_spec)
        evidence_spec.loader.exec_module(evidence)

        with tempfile.TemporaryDirectory() as directory:
            nonfinite = Path(directory) / "nonfinite.json"
            nonfinite.write_text('{"value":Infinity}')
            with self.assertRaisesRegex(ValueError, "invalid JSON evidence"):
                evidence.read_json(nonfinite)
            duplicate = Path(directory) / "duplicate.json"
            duplicate.write_text('{"value":1,"value":2}')
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                evidence.read_json(duplicate)
            truncated = Path(directory) / "truncated.json"
            truncated.write_text('{"value":')
            with self.assertRaisesRegex(ValueError, "invalid JSON evidence"):
                evidence.read_json(truncated)

        self.assertEqual(
            evidence.campaign_status(
                "FAIL_OR_INCOMPLETE", True, True, "STABLE"),
            "FAIL_OR_INCOMPLETE")
        self.assertEqual(
            evidence.campaign_status("PASS", False, True, "STABLE"),
            "BLOCKED_SOURCE_IDENTITY_CHANGED")
        self.assertEqual(
            evidence.campaign_status("PASS", True, False, "STABLE"),
            "BLOCKED_PROTOCOL_NOT_V2")
        self.assertEqual(
            evidence.campaign_status("PASS", True, True, "CHANGED"),
            "BLOCKED_HOST_IDENTITY_CHANGED")
        self.assertEqual(
            evidence.campaign_status(
                "PASS", True, True, "STABLE", target_consistent=False),
            "BLOCKED_TARGET_IDENTITY_CHANGED")
        self.assertEqual(
            evidence.campaign_status("PASS", True, True, "STABLE"),
            "PASS")
        self.assertEqual(
            evidence.campaign_status(
                "PASS", True, True, "STABLE", arm_boot_consistent=False),
            "BLOCKED_ARM_BOOT_IDENTITY_CHANGED")
        source_sha = "a" * 40
        mapper_uuid = "SWAPZ-PRIMARY-" + "f" * 32
        with mock.patch.object(
                evidence, "run_text",
                side_effect=[source_sha, "b" * 40]):
            with self.assertRaisesRegex(
                    ValueError, "HEAD == origin/main == source SHA"):
                evidence.require_clean_source(source_sha)

        def ram_trace(peak=8192):
            self.assertEqual(peak % 1024, 0)
            baseline_available_kib = 16 * 1024
            samples = []
            phases = (
                ("baseline", [0] * 11, False),
                ("initialization", [2, 4], True),
                ("steady", [6, peak // 1024], True),
                ("gc", [peak // 1024, 6], True),
                ("teardown", [6] + [0] * 21, None),
            )
            for phase, deltas_kib, mapper_state in phases:
                for phase_index, delta_kib in enumerate(deltas_kib):
                    index = len(samples) + 1
                    seconds, tenths = divmod(index, 10)
                    present = (
                        phase_index > 0 if phase == "initialization" else
                        phase_index == 0
                        if phase == "teardown" else mapper_state)
                    samples.append({
                        "phase": phase,
                        "monotonic_ns": index * 100_000_000,
                        "timestamp_utc":
                            f"2026-11-03T00:00:{seconds:02d}.{tenths}Z",
                        "mem_available_kib":
                            baseline_available_kib - delta_kib,
                        "s_unreclaim_kib":
                            1024 + (delta_kib if present else 0),
                        "vmalloc_used_kib":
                            2048 + (delta_kib if present else 0),
                        "mapper_present": present,
                    })
            return {
                "schema": "swapz-metadata-ram-samples-v1",
                "capture": "serialized-loaded-host",
                "scope": "whole-host-conservative-metadata-and-target-ram",
                "source_sha": source_sha,
                "mapper_uuid": mapper_uuid,
                "host_boot_id":
                    "11111111-1111-4111-8111-111111111111",
                "sampling_interval_ns": 100_000_000,
                "meminfo_unit": "kB",
                "samples": samples,
            }

        trace = ram_trace()
        validator = evidence.RAM_VALIDATOR["validate_metadata_ram_trace"]
        ram_summary = validator(
            trace, source_sha=source_sha, mapper_uuid=mapper_uuid,
            expected_peak_ram_bytes=8192)
        self.assertEqual(ram_summary["peak_ram_bytes"], 8192)
        self.assertEqual(
            evidence.RAM_VALIDATOR["_median_twice"]([16_384, 16_383]),
            32_767)
        constructor_peak = copy.deepcopy(trace)
        first_initialization = next(
            sample for sample in constructor_peak["samples"]
            if sample["phase"] == "initialization")
        self.assertFalse(first_initialization["mapper_present"])
        first_initialization["mem_available_kib"] -= 9
        constructor_summary = validator(
            constructor_peak, source_sha=source_sha,
            mapper_uuid=mapper_uuid, expected_peak_ram_bytes=11 * 1024)
        self.assertEqual(constructor_summary["peak_ram_bytes"], 11 * 1024)

        parse_meminfo = evidence.RAM_VALIDATOR["parse_meminfo_counters"]
        self.assertEqual(
            parse_meminfo(
                "MemTotal:       8388608 kB\n"
                "MemAvailable:     16384 kB\n"
                "SUnreclaim:        1024 kB\n"
                "VmallocUsed:       2048 kB\n"),
            {
                "mem_available_kib": 16384,
                "s_unreclaim_kib": 1024,
                "vmalloc_used_kib": 2048,
            })
        for malformed in (
                "MemAvailable: 16384 kB\nSUnreclaim: 1024 kB\n",
                "MemAvailable: 16384 bytes\nSUnreclaim: 1024 kB\n"
                "VmallocUsed: 2048 kB\n",
                "MemAvailable: 16384 kB\nMemAvailable: 16384 kB\n"
                "SUnreclaim: 1024 kB\nVmallocUsed: 2048 kB\n"):
            with self.subTest(meminfo=malformed):
                with self.assertRaises(ValueError):
                    parse_meminfo(malformed)

        # Four segment-rounded data segments support exactly 256 pages after
        # the separate two-segment GC reserve and foreground headroom.
        target_bytes = (1024 + 1) * 4096
        maximum_pages = evidence.RAM_VALIDATOR[
            "maximum_logical_pages_for_partition"]
        self.assertEqual(maximum_pages(target_bytes), 256)
        self.assertEqual(maximum_pages(124787884032), 27080192)
        self.assertIsNone(maximum_pages(target_bytes + 1))
        near_u32_partition_bytes = (0xffffff00 + 1) * 4096
        self.assertIsNone(maximum_pages(
            near_u32_partition_bytes, size_t_max=0xffffffff))

        capacity_pair = {
            "workload": "sd-high-occupancy-churn",
            "status": "PASS",
            "excluded": False,
            "swapz": {
                "logical_pages": 256,
                "arm_started_monotonic_ns": 1_300_000_000,
                "arm_finished_monotonic_ns": 1_700_000_000,
                "sustained_intervals": [{
                    "interval": 0,
                    "start_monotonic_ns": 1_300_000_000,
                    "end_monotonic_ns": 1_700_000_000,
                    "gc": {
                        "gc_wall_ns": 1,
                        "gc_victims": 1,
                        "gc_pages": 1,
                    },
                }],
                "device_identity": {"dm_uuid": mapper_uuid},
                "resources": {
                    # A pre-teardown replay scalar has no qualifying authority.
                    "metadata_and_target_peak_ram_bytes": 0,
                },
            },
        }
        self.assertEqual(
            evidence.campaign_capacity_and_ram(
                [capacity_pair], target_bytes, source_sha, trace),
            {
                "ram_acceptance_status": "PASS",
                "ram_limit_bytes": evidence.QUALIFICATION["CONTRACT"]
                    ["acceptance"]["sustained"]
                    ["metadata_and_target_peak_ram_bytes_max"],
                "page_bytes": 4096,
                "logical_pages": 256,
                "logical_capacity_bytes": 256 * 4096,
                "peak_ram_bytes": 8192,
                "mapper_uuid": mapper_uuid,
                "metadata_ram_trace": trace,
                "metadata_ram_summary": ram_summary,
                "metadata_ram_arm_binding": {
                    "arm_started_monotonic_ns": 1_300_000_000,
                    "arm_finished_monotonic_ns": 1_700_000_000,
                    "gc_activity_intervals": [{
                        "start_monotonic_ns": 1_300_000_000,
                        "end_monotonic_ns": 1_700_000_000,
                        "gc_wall_ns": 1,
                        "gc_victims": 1,
                        "gc_pages": 1,
                    }],
                },
            })
        self.assertIsNone(evidence.campaign_capacity_and_ram(
            [capacity_pair], 4096, source_sha, trace))
        self.assertIsNone(evidence.campaign_capacity_and_ram(
            [capacity_pair], target_bytes, source_sha))
        contradictory = copy.deepcopy(capacity_pair)
        contradictory["swapz"]["resources"][
            "metadata_and_target_peak_ram_bytes"] = 8193
        self.assertIsNone(evidence.campaign_capacity_and_ram(
            [contradictory], target_bytes, source_sha, trace))

        wrong_arm = copy.deepcopy(capacity_pair)
        wrong_arm["swapz"]["arm_started_monotonic_ns"] = 1_500_000_000
        self.assertIsNone(evidence.campaign_capacity_and_ram(
            [wrong_arm], target_bytes, source_sha, trace))
        fake_gc = copy.deepcopy(capacity_pair)
        fake_gc["swapz"]["sustained_intervals"][0]["gc"] = {
            "gc_wall_ns": 0, "gc_victims": 0, "gc_pages": 0}
        self.assertIsNone(evidence.campaign_capacity_and_ram(
            [fake_gc], target_bytes, source_sha, trace))
        displaced_gc = copy.deepcopy(capacity_pair)
        displaced_gc["swapz"]["sustained_intervals"][0][
            "start_monotonic_ns"] = 1_700_000_001
        displaced_gc["swapz"]["sustained_intervals"][0][
            "end_monotonic_ns"] = 1_800_000_000
        self.assertIsNone(evidence.campaign_capacity_and_ram(
            [displaced_gc], target_bytes, source_sha, trace))
        self.assertTrue(evidence.metadata_ram_trace_matches_swapz_arm(
            trace, capacity_pair["swapz"]))

        capacity = evidence.campaign_capacity_and_ram(
            [capacity_pair], target_bytes, source_sha, trace)
        # A transient whole-host dip after the exact mapper is already absent
        # is not the target peak. Final teardown recovery is checked separately.
        post_remove_dip = copy.deepcopy(trace)
        first_absent = next(
            sample for sample in post_remove_dip["samples"]
            if sample["phase"] == "teardown" and
            not sample["mapper_present"])
        first_absent["mem_available_kib"] -= 16
        post_remove_summary = validator(
            post_remove_dip, source_sha=source_sha,
            mapper_uuid=mapper_uuid, expected_peak_ram_bytes=8192)
        self.assertEqual(post_remove_summary["peak_ram_bytes"], 8192)

        before = {
            "kernel": {
                "boot_id": trace["host_boot_id"],
                "uptime_seconds": 0.0,
            },
            "memory": {"total_bytes": 8 * 1024 * 1024 * 1024},
            "captured_at_utc": "2026-11-03T00:00:00Z",
        }
        after = {
            "kernel": {
                "boot_id": trace["host_boot_id"],
                "uptime_seconds": 10.0,
            },
            "memory": {"total_bytes": 8 * 1024 * 1024 * 1024},
            "captured_at_utc": "2026-11-03T00:00:10Z",
        }
        self.assertTrue(evidence.metadata_ram_trace_within_host_window(
            capacity, before, after))
        invalid_before = copy.deepcopy(before)
        invalid_before["kernel"]["boot_id"] = (
            "22222222-2222-4222-8222-222222222222")
        self.assertFalse(evidence.metadata_ram_trace_within_host_window(
            capacity, invalid_before, after))
        invalid_before = copy.deepcopy(before)
        invalid_before["captured_at_utc"] = "2026-11-03T00:00:02Z"
        self.assertFalse(evidence.metadata_ram_trace_within_host_window(
            capacity, invalid_before, after))
        invalid_after = copy.deepcopy(after)
        invalid_after["captured_at_utc"] = "2026-11-03T00:00:03Z"
        self.assertFalse(evidence.metadata_ram_trace_within_host_window(
            capacity, before, invalid_after))

        def corrupt_recovery(item):
            for sample in item["samples"][-10:]:
                sample["mem_available_kib"] -= 100

        def corrupt_baseline_outlier(item):
            # The old minimum-baseline comparison hid 100 KiB of leaked RAM.
            item["samples"][0]["mem_available_kib"] -= 1000
            corrupt_recovery(item)

        def corrupt_slab_outlier(item):
            # A single slab spike must not excuse sustained teardown growth.
            item["samples"][0]["s_unreclaim_kib"] += 1000
            for sample in item["samples"][-10:]:
                sample["s_unreclaim_kib"] += 100

        def corrupt_vmalloc_outlier(item):
            item["samples"][0]["vmalloc_used_kib"] += 1000
            for sample in item["samples"][-10:]:
                sample["vmalloc_used_kib"] += 100

        def corrupt_actual_cadence(item):
            # Every interval fits the existing jitter bound, yet the sampler
            # averages 140 ms instead of its declared 100 ms.
            for index, sample in enumerate(item["samples"], start=1):
                sample["monotonic_ns"] = index * 140_000_000

        def corrupt_wall_clock_drift(item):
            # A 200 ms UTC step differs from each 100 ms monotonic interval by
            # only 100 ms, but the cumulative timestamp drift is fabricated.
            for index, sample in enumerate(item["samples"], start=1):
                seconds, tenths = divmod(index * 2, 10)
                sample["timestamp_utc"] = (
                    f"2026-11-03T00:00:{seconds:02d}.{tenths}Z")

        corruptions = (
            lambda item: item["samples"].pop(),
            lambda item: item["samples"][11].update(phase="baseline"),
            lambda item: item["samples"][13].update(monotonic_ns=1),
            lambda item: item["samples"][13].update(
                monotonic_ns=(
                    item["samples"][12]["monotonic_ns"] + 151_000_000)),
            lambda item: item["samples"][13].update(
                timestamp_utc="2026-11-03T00:00:00Z"),
            lambda item: item.update(source_sha="b" * 40),
            lambda item: item.update(
                mapper_uuid="SWAPZ-PRIMARY-" + "e" * 32),
            lambda item: item["samples"][13].update(mapper_present=False),
            lambda item: item.update(scope="target-owned-estimate"),
            lambda item: item.update(meminfo_unit="bytes"),
            lambda item: item.update(sampling_interval_ns=1_000_000_000),
            corrupt_actual_cadence,
            corrupt_wall_clock_drift,
            corrupt_recovery,
            corrupt_baseline_outlier,
            corrupt_slab_outlier,
            corrupt_vmalloc_outlier,
        )
        for corrupt in corruptions:
            damaged = copy.deepcopy(trace)
            corrupt(damaged)
            with self.subTest(corrupt=corrupt):
                with self.assertRaises(ValueError):
                    validator(
                        damaged, source_sha=source_sha,
                        mapper_uuid=mapper_uuid,
                        expected_peak_ram_bytes=8192)
                self.assertIsNone(evidence.campaign_capacity_and_ram(
                    [capacity_pair], target_bytes, source_sha, damaged))

        qualification_path = SCRIPT.with_name("qualification.py")
        qualification_spec = importlib.util.spec_from_file_location(
            "swapz_campaign_qualification", qualification_path)
        qualification = importlib.util.module_from_spec(qualification_spec)
        qualification_spec.loader.exec_module(qualification)

        source_sha = "a" * 40
        other_source_sha = "c" * 40
        source_tree_sha = "b" * 40
        host = {
            "schema": evidence.HOST_SCHEMA,
            "captured_at_utc": "2026-11-03T18:00:00+00:00",
            "source_sha": source_sha,
            "source_tree_sha": source_tree_sha,
            "virtualization": "none",
            "kernel": {
                "release": "6.8.0", "machine": "x86_64",
                "version": "#1 SMP", "node": "physical-host",
                "boot_id": "11111111-2222-3333-4444-555555555555",
                "uptime_seconds": 1000.0},
            "device": {
                "major_minor": "8:1", "parent_major_minor": "8:0",
                "size_bytes": 123456,
                "physical_disk": "sda", "model": "SD", "transport": "usb",
                "partuuid": "11111111-01", "serial": "serial-1",
                "wwid": "wwid-1", "selected_scheduler": "mq-deadline",
                "holders": [],
                "queue": {
                    "logical_block_size": 512,
                    "physical_block_size": 512,
                },
            },
            "cpu": {
                "configured_cpus": 4, "online_cpus": 4,
                "affinity_cpus": [0, 1, 2, 3],
                "model_names": ["Synthetic CPU"],
                "governors": ["performance"],
                "frequency_drivers": ["synthetic"],
                "scaling_min_khz": [1000000],
                "scaling_max_khz": [2000000],
            },
            "memory": {"total_bytes": 8 * 1024 * 1024 * 1024},
            "swap_inventory": [],
            "mount_inventory": "/ /dev/root ext4 8:2",
            "pressure": {
                "cpu": "some avg10=0.00",
                "io": "some avg10=0.00",
                "memory": "some avg10=0.00"},
            "thermal": [],
            "dm_swapz_module": {"status": "NOT_LOADED", "values": {}},
        }


        # Campaign snapshots reject malformed PARTUUID identity before sealing;
        # uppercase hardware output is accepted only by canonicalizing it.
        for bad_partuuid in (
                "--------", "11111111--01", "11111111.", "1234-567"):
            with self.subTest(campaign_partuuid=bad_partuuid):
                bad_host = {
                    **host,
                    "device": {**host["device"], "partuuid": bad_partuuid},
                }
                with self.assertRaises(ValueError):
                    evidence.physical_target_identity(bad_host)
        uppercase_host = {
            **host,
            "device": {**host["device"], "partuuid": "ABCDEF12-01"},
        }
        self.assertEqual(
            evidence.physical_target_identity(uppercase_host),
            {"partuuid": "abcdef12-01", "device_bytes": 123456})

        def excluded_pair(pair_id, pair_index, order, pair_source):
            return {
                "schema": qualification.PAIR_SCHEMA,
                "workload": "sd-service-balanced",
                "pair_id": pair_id, "pair_index": pair_index, "order": order,
                "source_sha": pair_source,
                "qualification_protocol": qualification.SCHEMA,
                "status": "EXCLUDED", "excluded": True,
                "exclusion_reasons": ["synthetic exclusion"],
                "deltas": {},
                "raw": {"source_sha": pair_source},
                "swapz": {"source_sha": pair_source},
            }

        pair = excluded_pair("pair-1", 1, "raw-first", source_sha)
        summary = qualification.evaluate([pair], protocol="v2")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before_path = root / "host-before.json"
            after_path = root / "host-after.json"
            pair_path = root / "pair-1.json"
            summary_path = root / "summary.json"
            result_path = root / "campaign.json"
            before_path.write_text(json.dumps(host))
            after_host = {
                **host,
                "captured_at_utc": "2026-11-03T19:00:00+00:00",
                "kernel": {**host["kernel"], "uptime_seconds": 1060.0},
            }
            after_path.write_text(json.dumps(after_host))
            pair_path.write_text(json.dumps(pair))
            summary_path.write_text(json.dumps(summary))

            cli_summary_path = root / "cli-summary.json"
            cli_command = [
                sys.executable, str(qualification_path), "evaluate",
                "--protocol", "v2", "--result", str(cli_summary_path),
                str(pair_path),
            ]
            cli_run = subprocess.run(
                cli_command, capture_output=True, text=True, timeout=20)
            self.assertEqual(cli_run.returncode, 0, cli_run.stderr)
            self.assertEqual(json.loads(cli_summary_path.read_text()), summary)
            cli_summary_bytes = cli_summary_path.read_bytes()
            cli_rerun = subprocess.run(
                cli_command, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(cli_rerun.returncode, 0)
            self.assertIn(
                "refusing to overwrite qualification summary",
                cli_rerun.stderr)
            self.assertEqual(cli_summary_path.read_bytes(), cli_summary_bytes)

            with mock.patch.object(
                    evidence, "require_clean_source", return_value=None), \
                    mock.patch.object(
                        evidence, "source_tree_sha",
                        return_value=source_tree_sha):
                sealed = evidence.seal_campaign(
                    source_sha, before_path, after_path,
                    summary_path, [pair_path])
                ram_trace_path = root / "metadata-ram-trace.json"
                canonical_ram_trace = (
                    json.dumps(trace, indent=2, sort_keys=True) + "\n").encode()
                ram_trace_path.write_bytes(canonical_ram_trace)
                sealed_with_ram_trace = evidence.seal_campaign(
                    source_sha, before_path, after_path,
                    summary_path, [pair_path], ram_trace_path)
                self.assertEqual(
                    sealed_with_ram_trace["artifacts"][
                        "metadata_ram_trace"]["sha256"],
                    hashlib.sha256(canonical_ram_trace).hexdigest())
                self.assertEqual(
                    sealed_with_ram_trace["artifacts"][
                        "metadata_ram_trace"]["size_bytes"],
                    len(canonical_ram_trace))
                ram_trace_path.write_text(json.dumps(trace))
                with self.assertRaisesRegex(ValueError, "not canonical"):
                    evidence.seal_campaign(
                        source_sha, before_path, after_path,
                        summary_path, [pair_path], ram_trace_path)
            self.assertEqual(sealed["record_count"], 1)
            pair_bytes = pair_path.read_bytes()
            summary_bytes = summary_path.read_bytes()
            self.assertEqual(
                sealed["artifacts"]["pairs"][0]["sha256"],
                hashlib.sha256(pair_bytes).hexdigest())
            self.assertEqual(
                sealed["artifacts"]["qualification_summary"]["sha256"],
                hashlib.sha256(summary_bytes).hexdigest())
            pair_path.write_bytes(pair_bytes + b"\n")
            self.assertNotEqual(
                sealed["artifacts"]["pairs"][0]["sha256"],
                hashlib.sha256(pair_path.read_bytes()).hexdigest())
            pair_path.write_bytes(pair_bytes)
            self.assertEqual(sealed["campaign_status"], "FAIL_OR_INCOMPLETE")
            self.assertIsNone(sealed["capacity_and_ram"])
            self.assertTrue(sealed["source_consistent"])
            self.assertEqual(sealed["pair_source_shas"], [source_sha])
            self.assertEqual(
                sealed["artifacts"]["pairs"][0]["status"], "EXCLUDED")
            self.assertEqual(
                sealed["policy"]["acceptance_manifest"]["git_blob_sha"],
                evidence.git_blob_sha(
                    evidence.ACCEPTANCE_MANIFEST.read_bytes()))
            self.assertEqual(sealed["host_stability"]["status"], "STABLE")
            self.assertEqual(
                sealed["target"],
                {"partuuid": "11111111-01", "device_bytes": 123456})
            self.assertEqual(
                evidence.physical_target_identity(host), sealed["target"])
            self.assertFalse(
                sealed["qualification_target_binding"]["consistent"])
            expected_binding = evidence.qualification_target_binding({
                "campaign_target_consistent": True,
                "campaign_target_identity": {
                    "physical_partuuid": "11111111-01",
                    "physical_device_bytes": 123456,
                    "lower_major_minor": "8:1",
                    "parent_major_minor": "8:0",
                    "parent_model": "SD",
                    "parent_transport": "usb",
                },
            }, host)
            self.assertTrue(expected_binding["consistent"])
            wrong_binding = evidence.qualification_target_binding({
                "campaign_target_consistent": True,
                "campaign_target_identity": {
                    "physical_partuuid": "22222222-01",
                    "physical_device_bytes": 123456,
                    "lower_major_minor": "8:1",
                },
            }, host)
            self.assertFalse(wrong_binding["consistent"])
            self.assertTrue(
                sealed["admitted_device_boundary"]["before"]["quiescent"])
            self.assertTrue(
                sealed["admitted_device_boundary"]["after"]["quiescent"])

            dirty_swap = {
                **after_host,
                "swap_inventory": [{
                    "path": "/dev/sda1", "type": "partition",
                    "size_kib": 1024, "used_kib": 0, "priority": -2,
                    "major_minor": "8:1",
                }],
            }
            dirty_mount = {
                **after_host,
                "mount_inventory":
                    "/ /dev/root ext4 8:2\n/mnt/sd /dev/sda1 ext4 8:1",
            }
            dirty_holder = {
                **after_host,
                "device": {
                    **after_host["device"],
                    "holders": [{
                        "kernel_name": "dm-0", "major_minor": "253:0"}],
                },
            }
            for dirty in (dirty_swap, dirty_mount, dirty_holder):
                stability = evidence.host_stability(host, dirty)
                self.assertEqual(stability["status"], "CHANGED")
                self.assertIn(
                    "admitted_device_quiescent_after",
                    stability["failed_checks"])

            rebooted = {
                **after_host,
                "kernel": {
                    **after_host["kernel"],
                    "boot_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "uptime_seconds": 30.0,
                },
            }
            reboot_stability = evidence.host_stability(host, rebooted)
            self.assertEqual(reboot_stability["status"], "CHANGED")
            self.assertIn("kernel_boot_id", reboot_stability["failed_checks"])
            self.assertIn(
                "kernel_uptime_non_decreasing",
                reboot_stability["failed_checks"])

            malformed_swap = {
                **host,
                "swap_inventory": [{
                    "path": "/dev/sda1", "type": "partition",
                    "size_kib": 1024, "used_kib": 0, "priority": -2,
                    "major_minor": None,
                }],
            }
            with self.assertRaisesRegex(
                    ValueError, "host context is incomplete"):
                evidence.validate_host_snapshot(malformed_swap, source_sha)

            evidence.write_new_json(result_path, sealed)
            with self.assertRaises(FileExistsError):
                evidence.write_new_json(result_path, sealed)

            # Create-only publication must not follow an attacker-controlled
            # final symlink or leave a partial final JSON on write failure.
            sentinel_path = root / "sentinel.txt"
            sentinel_path.write_text("unchanged")
            symlink_path = root / "symlink-result.json"
            symlink_path.symlink_to(sentinel_path)
            with self.assertRaises(FileExistsError):
                evidence.write_new_json(symlink_path, sealed)
            self.assertEqual(sentinel_path.read_text(), "unchanged")

            failed_publish = root / "failed-publish.json"
            writer_module = sys.modules[
                evidence.write_new_json.__module__]
            with mock.patch.object(
                    writer_module.os, "write",
                    side_effect=OSError("synthetic evidence storage failure")):
                with self.assertRaisesRegex(
                        OSError, "synthetic evidence storage failure"):
                    evidence.write_new_json(failed_publish, sealed)
            self.assertFalse(failed_publish.exists())
            self.assertFalse(any(
                path.name.startswith(
                    "." + failed_publish.name + ".swapz-tmp-")
                for path in root.iterdir()))

            # An edit to derived evaluator output must fail even if original
            # pair fields in the summary remain untouched.
            tampered_summary = dict(summary)
            tampered_summary["raw_repeat_spread"] = {
                "sd-service-balanced": 0.0}
            summary_path.write_text(json.dumps(tampered_summary))
            with mock.patch.object(
                    evidence, "require_clean_source", return_value=None), \
                    mock.patch.object(
                        evidence, "source_tree_sha",
                        return_value=source_tree_sha):
                with self.assertRaisesRegex(
                        ValueError, "does not exactly match supplied pair"):
                    evidence.seal_campaign(
                        source_sha, before_path, after_path,
                        summary_path, [pair_path])

            # Preserve an invalid mixed-source campaign as sealed failure
            # evidence instead of refusing to record why it was incomplete.
            pair_two = excluded_pair(
                "pair-2", 2, "swapz-first", other_source_sha)
            pair_two_path = root / "pair-2.json"
            pair_two_path.write_text(json.dumps(pair_two))
            mixed_summary = qualification.evaluate(
                [pair, pair_two], protocol="v2")
            self.assertIsNone(mixed_summary["campaign_source_sha"])
            summary_path.write_text(json.dumps(mixed_summary))
            with mock.patch.object(
                    evidence, "require_clean_source", return_value=None), \
                    mock.patch.object(
                        evidence, "source_tree_sha",
                        return_value=source_tree_sha):
                mixed = evidence.seal_campaign(
                    source_sha, before_path, after_path,
                    summary_path, [pair_path, pair_two_path])
            self.assertEqual(mixed["campaign_status"], "FAIL_OR_INCOMPLETE")
            self.assertFalse(mixed["source_consistent"])
            self.assertEqual(
                mixed["pair_source_shas"],
                [source_sha, other_source_sha])

            with mock.patch.object(
                    evidence, "require_clean_source", return_value=None):
                with self.assertRaisesRegex(
                        ValueError, "inputs must be distinct files"):
                    evidence.seal_campaign(
                        source_sha, before_path, before_path,
                        summary_path, [pair_path, pair_two_path])

            # Before/after chronology is itself part of campaign provenance.
            backwards = {
                **after_host,
                "captured_at_utc": "2026-11-03T17:00:00+00:00"}
            after_path.write_text(json.dumps(backwards))
            summary_path.write_text(json.dumps(summary))
            with mock.patch.object(
                    evidence, "require_clean_source", return_value=None), \
                    mock.patch.object(
                        evidence, "source_tree_sha",
                        return_value=source_tree_sha):
                with self.assertRaisesRegex(ValueError, "time moved backwards"):
                    evidence.seal_campaign(
                        source_sha, before_path, after_path,
                        summary_path, [pair_path])

            changed_host = {
                **after_host,
                "device": {**after_host["device"], "major_minor": "8:2"}}
            self.assertEqual(
                evidence.host_stability(host, changed_host)["status"],
                "CHANGED")

            context_changed = {
                **after_host,
                "kernel": {
                    **after_host["kernel"], "version": "#2 SMP"},
                "cpu": {
                    **after_host["cpu"],
                    "model_names": ["Different CPU"]},
                "memory": {
                    "total_bytes": host["memory"]["total_bytes"] * 2},
                "mount_inventory":
                    host["mount_inventory"] + "\n/mnt /dev/sdb1 ext4 8:17",
            }
            context_stability = evidence.host_stability(
                host, context_changed)
            self.assertEqual(context_stability["status"], "CHANGED")
            self.assertTrue({
                "kernel_version", "cpu_model_names",
                "memory_total_bytes", "mount_inventory",
            }.issubset(context_stability["failed_checks"]))

            after_path.write_text(json.dumps(after_host))
            summary_path.write_text(json.dumps(summary))
            with mock.patch.object(
                    evidence, "require_clean_source", return_value=None), \
                    mock.patch.object(
                        evidence, "source_tree_sha",
                        return_value=source_tree_sha):
                with self.assertRaisesRegex(
                        ValueError, "requires every evaluator record"):
                    evidence.seal_campaign(
                        source_sha, before_path, after_path,
                        summary_path, [])

    def test_prospective_amendment_and_attribution_fail_closed(self):
        import importlib.util

        qualification_path = SCRIPT.with_name("qualification.py")
        qualification_spec = importlib.util.spec_from_file_location(
            "swapz_protocol_audit", qualification_path)
        qualification = importlib.util.module_from_spec(qualification_spec)
        qualification_spec.loader.exec_module(qualification)

        self.assertEqual(
            qualification._git_blob_sha(qualification.AMENDMENT_MANIFEST),
            qualification.AMENDMENT_GIT_BLOB_SHA)
        with tempfile.TemporaryDirectory() as directory:
            tampered = Path(directory) / "amendment.json"
            tampered.write_text("{}")
            original = qualification.AMENDMENT_MANIFEST
            try:
                qualification.AMENDMENT_MANIFEST = tampered
                with self.assertRaisesRegex(ValueError, "blob hash changed"):
                    qualification._load_frozen_amendment()
            finally:
                qualification.AMENDMENT_MANIFEST = original

        v1_only = qualification.evaluate([], protocol="v1")
        self.assertEqual(
            v1_only["acceptance_manifest_sha256"],
            hashlib.sha256(
                qualification.ACCEPTANCE_MANIFEST.read_bytes()
            ).hexdigest())
        self.assertFalse(v1_only["amendment_active"])
        self.assertNotIn("sd-service-qd1-balanced", v1_only["decisions"])
        v2 = qualification.evaluate([], protocol="v2")
        self.assertTrue(v2["amendment_active"])
        self.assertEqual(v2["evaluation_protocol"], "v2")
        self.assertEqual(
            v2["decisions"]["sd-service-qd1-balanced"]["status"],
            "INCOMPLETE")
        self.assertEqual(
            v2["decisions"]["sd-service-incompressible"]["status"],
            "INCOMPLETE")
        with self.assertRaisesRegex(ValueError, "unsupported"):
            qualification.evaluate([], protocol="v3")
        with self.assertRaisesRegex(ValueError, "v2 workload"):
            qualification.evaluate([{
                "schema": qualification.PAIR_SCHEMA,
                "workload": "sd-service-qd1-balanced", "status": "EXCLUDED",
                "excluded": True,
            }], protocol="v1")

        round_evidence = {
            "lower_io": {"lower_read_bytes": 4096},
            "target_io": {"target_read_bytes": 4096},
            "vmstat": {"pswpin_pages": 1},
            "cgroup_delta": {"memory_stat": {"pgmajfault": 1}},
        }
        arm = {
            "observed_swap_bytes": 134217728,
            "oracle": {"mismatches": 0},
            "anonymous_swap_attribution": {
                "vmstat": {"pswpout_pages": 128}},
            "target_io": {"target_write_bytes": 1048576},
            "lower_io": {"lower_write_bytes": 1048576},
            "rounds": [round_evidence.copy() for _ in range(3)],
        }
        pair = {
            "pair_id": "audit-pair",
            "deltas": {
                "swapin_p95": 0, "swapin_p99": 0, "useful_read": 0,
                "lower_write_bytes": -.2,
                "lower_write_requests": -.2, "cpu": 0,
            },
            "raw": arm, "swapz": arm,
        }
        def verdict():
            return qualification.anonymous_decision([pair])["status"]

        self.assertEqual(verdict(), "PASS")
        arm["rounds"][0] = {
            **round_evidence,
            "cgroup_delta": {"memory_stat": {"pgmajfault": 0}},
        }
        self.assertEqual(verdict(), "FAIL")
        arm["rounds"][0] = round_evidence.copy()
        arm["anonymous_swap_attribution"]["vmstat"]["pswpout_pages"] = 0
        self.assertEqual(verdict(), "FAIL")
        arm["anonymous_swap_attribution"]["vmstat"]["pswpout_pages"] = 128
        arm["target_io"]["target_write_bytes"] = 0
        self.assertEqual(verdict(), "FAIL")
        arm["target_io"]["target_write_bytes"] = 1048576
        arm["observed_swap_bytes"] = "134217728"
        self.assertEqual(verdict(), "FAIL")
        arm["observed_swap_bytes"] = 134217728
        arm["oracle"]["mismatches"] = False
        self.assertEqual(verdict(), "FAIL")

        anonymous_path = SCRIPT.with_name("anonymous-swap.py")
        anonymous_spec = importlib.util.spec_from_file_location(
            "swapz_cgroup_audit", anonymous_path)
        anonymous = importlib.util.module_from_spec(anonymous_spec)
        anonymous_spec.loader.exec_module(anonymous)
        with tempfile.TemporaryDirectory() as directory:
            cgroup = Path(directory)
            (cgroup / "cgroup.procs").write_text(f"{os.getpid()}\n")
            anonymous.require_isolated_cgroup({"path": str(cgroup)})
            (cgroup / "child").mkdir()
            with self.assertRaisesRegex(ValueError, "descendant cgroups"):
                anonymous.require_isolated_cgroup({"path": str(cgroup)})

    def test_anonymous_swap_page_recipe_is_deterministic_and_bimodal(self):
        import importlib.util

        path = SCRIPT.with_name("anonymous-swap.py")
        spec = importlib.util.spec_from_file_location("swapz_anonymous_swap", path)
        anonymous = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(anonymous)
        medium = anonymous.page_bytes(2)
        entropy = anonymous.page_bytes(3)
        self.assertEqual(len(medium), PAGE)
        self.assertEqual(len(entropy), PAGE)
        self.assertEqual(medium, anonymous.page_bytes(2))
        self.assertEqual(entropy, anonymous.page_bytes(3))
        self.assertNotEqual(medium, entropy)
        self.assertTrue(medium.startswith(b"swapz-anonymous-page:2\0"))
        self.assertGreater(len(set(entropy)), 200)
        cpu_delta = anonymous.process_cpu_delta(
            mock.Mock(ru_utime=1.0, ru_stime=.5),
            mock.Mock(ru_utime=1.25, ru_stime=.75))
        self.assertEqual(cpu_delta["user_seconds"], .25)
        self.assertEqual(cpu_delta["system_seconds"], .25)
        self.assertEqual(cpu_delta["total_seconds"], .5)
        self.assertEqual(
            anonymous.monotonic_counter_delta(
                {"pswpin": 100, "pswpout": 200},
                {"pswpin": 104, "pswpout": 207},
                ("pswpin", "pswpout")),
            {"pswpin": 4, "pswpout": 7})
        cgroup_delta = anonymous.cgroup_counter_delta(
            {"memory_stat": {"pgmajfault": 10, "pgfault": 100},
             "memory_events": {"oom": 0},
             "memory_swap_events": {"fail": 0},
             "memory_swap_current": 4096},
            {"memory_stat": {"pgmajfault": 13, "pgfault": 120},
             "memory_events": {"oom": 0},
             "memory_swap_events": {"fail": 0},
             "memory_swap_current": 2048})
        self.assertEqual(cgroup_delta["memory_stat"]["pgmajfault"], 3)
        self.assertEqual(cgroup_delta["memory_swap_current_delta_bytes"], -2048)

        qualification_path = SCRIPT.with_name("qualification.py")
        qualification_spec = importlib.util.spec_from_file_location(
            "swapz_anonymous_contract", qualification_path)
        qualification = importlib.util.module_from_spec(qualification_spec)
        qualification_spec.loader.exec_module(qualification)
        spec = qualification.CONTRACT["workloads"]["anonymous-swap"]
        pages = spec["bytes"] // PAGE
        anonymous_latency_index = qualification.latency_bin_index(1)
        anonymous_latency = qualification.latency_bin_upper(
            anonymous_latency_index)
        round_latency = {
            "count": pages,
            "p50_ns": anonymous_latency,
            "p95_ns": anonymous_latency,
            "p99_ns": anonymous_latency,
            "max_ns": 1,
            "histogram": {
                "count": pages, "max_ns": 1,
                "bins": [[anonymous_latency_index, pages]],
            },
        }
        rounds = [
            {"seconds": 1.0, "latency": copy.deepcopy(round_latency)}
            for _ in range(spec["rounds"])]
        useful_read_bytes = spec["bytes"] * spec["rounds"]
        arm = {
            "source_sha": "a" * 40,
            "bytes": spec["bytes"], "pages": pages,
            "round_count": spec["rounds"], "rounds": rounds,
            "required_swap_bytes": spec["minimum_observed_swap_bytes"],
            "content": spec["content"],
            "arm_started_monotonic_ns": 100,
            "arm_finished_monotonic_ns": 200,
            "arm_boot_id": "11111111-2222-3333-4444-555555555555",
            "loaded_module_provenance": {"status": "NOT_LOADED"},
            "swap_device_identity": {
                "device": "8:1", "dm_uuid": None, "dm_target": None,
                "lower_device": "8:1",
                "physical_partuuid": "f13428f6-01",
                "physical_device_bytes": 124787884032,
                "parent_major_minor": "8:0",
                "parent_model": "SD",
                "parent_transport": "usb"},
            "cgroup_before": {
                "path": "/sys/fs/cgroup/swapz-audit",
                "memory_max": spec["memory_max_bytes"],
                "memory_swap_max": "max",
            },
            "cgroup_after": {
                "path": "/sys/fs/cgroup/swapz-audit",
            },
            "swap_inventory_before": [{
                "device": "8:1", "used_kib": 0,
            }],
            "swap_inventory_after": [{
                "device": "8:1", "used_kib": 128 * 1024,
            }],
            "throughput": {
                "useful_read_bytes": useful_read_bytes,
                "read_seconds": float(spec["rounds"]),
                "useful_read_mbps":
                    useful_read_bytes / spec["rounds"] / 1_000_000,
            },
            "lower_io": {
                "lower_write_bytes": spec["bytes"],
                "lower_write_requests": pages,
                "lower_read_bytes": useful_read_bytes,
                "lower_write_bytes_per_logical_fill_byte": 1.0,
                "lower_write_requests_per_1000_fill_pages": 1000.0,
                "lower_read_bytes_per_logical_read_byte": 1.0,
            },
            "cpu": {
                "workload_process_user_seconds": 1.0,
                "workload_process_system_seconds": .5,
                "workload_process_cpu_seconds": 1.5,
                "exported_swapz_worker_cpu_seconds": 0.0,
                "attributed_cpu_seconds": 1.5,
                "measured_cpu_seconds_per_useful_byte":
                    1.5 / (spec["bytes"] + useful_read_bytes),
            },
            "swapin_latency": {
                "count": pages * spec["rounds"],
                "p50_ns": anonymous_latency,
                "p95_ns": anonymous_latency,
                "p99_ns": anonymous_latency,
                "max_ns": 1,
                "histogram": {
                    "count": pages * spec["rounds"], "max_ns": 1,
                    "bins": [[
                        anonymous_latency_index,
                        pages * spec["rounds"]]],
                },
            },
            "oracle": {
                "mismatches": 0,
                "verified_pages": pages * spec["rounds"],
            },
        }
        self.assertEqual(
            qualification.validate_arm(arm, "anonymous-swap", "raw"), [])
        tampered_accounting = copy.deepcopy(arm)
        tampered_accounting["lower_io"][
            "lower_write_bytes_per_logical_fill_byte"] = 0.0
        self.assertTrue(any(
            "anonymous accounting" in reason
            for reason in qualification.validate_arm(
                tampered_accounting, "anonymous-swap", "raw")))
        tampered_latency = copy.deepcopy(arm)
        tampered_latency["swapin_latency"]["p99_ns"] += 1
        self.assertTrue(any(
            "aggregate swap-in latency evidence" in reason
            for reason in qualification.validate_arm(
                tampered_latency, "anonymous-swap", "raw")))
        insufficient_swap_max = copy.deepcopy(arm)
        insufficient_swap_max["cgroup_before"]["memory_swap_max"] = 1
        self.assertTrue(any(
            "memory.swap.max" in reason
            for reason in qualification.validate_arm(
                insufficient_swap_max, "anonymous-swap", "raw")))
        wrong_inventory = copy.deepcopy(arm)
        wrong_inventory["swap_inventory_after"][0]["device"] = "8:17"
        self.assertTrue(any(
            "swap_inventory_after" in reason
            for reason in qualification.validate_arm(
                wrong_inventory, "anonymous-swap", "raw")))
        malformed_identity = copy.deepcopy(arm)
        malformed_identity["swap_device_identity"][
            "physical_partuuid"] = "F13428F6-01"
        self.assertTrue(any(
            "anonymous physical lower identity" in reason
            for reason in qualification.validate_arm(
                malformed_identity, "anonymous-swap", "raw")))
        # A synthetic arm cannot bypass the physical chronology contract.
        missing_boot = {**arm, "arm_boot_id": None}
        self.assertTrue(any(
            "chronology/boot identity" in reason
            for reason in qualification.validate_arm(
                missing_boot, "anonymous-swap", "raw")))
        arm["cgroup_before"]["memory_max"] += PAGE
        self.assertTrue(any(
            "memory.max" in reason
            for reason in qualification.validate_arm(
                arm, "anonymous-swap", "raw")))


if __name__ == "__main__":
    unittest.main()
