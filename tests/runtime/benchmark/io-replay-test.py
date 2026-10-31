#!/usr/bin/env python3
"""Rootless proof that both labels replay one exact immutable I/O plan.

This does NOT load the swapz module: same regular-file replay code tests only
the trace contract, oracle, safety guard and fail-closed pair comparator.
"""
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PAGE = 4096
SCRIPT = Path(__file__).with_name("io-replay.py")


class PairReplayContract(unittest.TestCase):
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
        arguments = fast.scenario_arguments("nvme5-mixed-lanes", "/plan", 0, True, True)
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

    def run_cmd(self, *args, success=True):
        run = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                             capture_output=True, text=True, timeout=30)
        if success and run.returncode:
            self.fail(f"command {args}: rc={run.returncode}\n{run.stdout}\n{run.stderr}")
        if not success:
            self.assertNotEqual(run.returncode, 0, repr(args))
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
        helper = SCRIPT.parents[3] / "build/tests/native/io-replay-native"
        self.assertTrue(helper.is_file())
        self.assertTrue(os.access(helper, os.X_OK))
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
                self.run_cmd(*prepare)
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
                        "--result", result)
                    record = json.loads(result.read_text())
                    self.assertEqual(record["replay_engine"], "native-c")
                    self.assertEqual(record["replay_mode"], mode)
                    self.assertEqual(
                        record["verified_post_sha256"],
                        record["expected_post_sha256"])
                    self.assertEqual(record["write_ops"] + record["read_ops"], 32)
                    self.assertGreater(record["seconds"], 0)
                    self.assertIn("native", record["mixed_timed_scope"])
                    reports.append(result)
                compared = json.loads(
                    self.run_cmd("compare", "--reports", *reports).stdout)
                self.assertEqual(compared["replay_engine"], "native-c")
                self.assertEqual(
                    compared["verdict"], "PASS_IDENTICAL_LOGICAL_INPUT")

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


if __name__ == "__main__":
    unittest.main()
