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
                run = self.run_cmd("run", "--fixture", fixture,
                                   "--trace", plan / "trace.jsonl",
                                   "--manifest", plan / "manifest.json",
                                   "--device", device, "--candidate", candidate,
                                   "--source-sha", "rootless-no-module",
                                   "--regular-file-test", "--packed-read",
                                   "--result", result)
                for subphase in ("prefill", "mixed", "packed_read"):
                    self.assertIn(f"BENCH_IO_PHASE={candidate}:{subphase}",
                                  run.stderr)
                record = json.loads(result.read_text())
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
                    self.assertGreater(phase["useful_read_mbps"], 0)
                    self.assertGreaterEqual(phase["replay_cpu_user_s"], 0)
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
        before = dict(zip(fields, (10, 4, 5, 3000, 100, 50, 4096, 200,
                                   2, 1, 1, 1, 0, 0, 0, 0, 0, 0,
                                   0, 0, 0, 0, 0, 0, 0, 0, 1000)))
        after = dict(zip(fields, (1034, 516, 517, 90000000, 3000000,
                                  100050, 4198400, 500200,
                                  402, 102, 321, 201, 200, 8, 3, 5, 2, 12,
                                  2, 2, 8, 0, 3, 4, 5, 0, 101000)))
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
        self.assertEqual(measured["read_full_extent_reqs"], 320)
        self.assertEqual(measured["read_full_cache_hits"], 200)
        self.assertEqual(measured["read_two_block_skips"], 200)
        self.assertEqual(measured["parallel_read_pairs"], 8)
        self.assertEqual(measured["parallel_read_same_extent_pairs"], 3)
        self.assertEqual(measured["parallel_read_distinct_extent_pairs"], 5)
        self.assertEqual(measured["parallel_read_adjacent_extent_pairs"], 2)
        self.assertEqual(measured["parallel_read_adjacent_extent_blocks"], 12)
        self.assertEqual(measured["parallel_read_coalesced_pairs"], 2)
        self.assertEqual(measured["parallel_read_coalesced_reqs_saved"], 2)
        self.assertEqual(measured["parallel_read_coalesced_blocks"], 8)
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
            module.kernel_read_delta(
                before, dict(after, parallel_read_same_extent_pairs=9))
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            module.kernel_read_delta(
                before, dict(after, parallel_read_adjacent_extent_pairs=6))
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            module.kernel_read_delta(
                before, dict(after, parallel_read_coalesced_reqs_saved=4))
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
            "lz4_wall_ns": 100,
            "ordered_lz4_wall_ns": 60,
            "prep_lz4_wall_ns": 40,
            "write_copy_wall_ns": 30,
            "write_copy_bytes": 4096,
            "ordered_write_copy_wall_ns": 20,
            "prep_write_copy_wall_ns": 10,
            "direct_lz4_input_pages": 1,
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
            "lz4_wall_ns": 50100,
            "ordered_lz4_wall_ns": 30060,
            "prep_lz4_wall_ns": 20040,
            "write_copy_wall_ns": 1030,
            "write_copy_bytes": 8192,
            "ordered_write_copy_wall_ns": 620,
            "prep_write_copy_wall_ns": 410,
            "direct_lz4_input_pages": 5,
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
        delta = module.kernel_write_delta(before, after)
        self.assertEqual(delta["physical_write_reqs"], 5)
        self.assertEqual([delta[key] for key in module.WRITE_WAIT_BINS],
                         [2, 2, 1])
        self.assertEqual(delta["write_copy_wall_ns"], 1000)
        self.assertEqual(delta["ordered_lz4_wall_ns"], 30000)
        self.assertEqual(delta["prep_lz4_wall_ns"], 20000)
        self.assertEqual(delta["ordered_write_copy_wall_ns"], 600)
        self.assertEqual(delta["prep_write_copy_wall_ns"], 400)
        self.assertEqual(delta["write_copy_bytes"], 4096)
        self.assertEqual(delta["direct_lz4_input_pages"], 4)
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
        with self.assertRaisesRegex(ValueError, "K=1 ready-wait"):
            module.kernel_write_delta(
                before, dict(after, k1_ready_wait_full=2))
        with self.assertRaisesRegex(ValueError, "upper-tail"):
            module.kernel_write_delta(
                before, dict(after, single_tail_comp_age_251_500us=0,
                             single_tail_comp_age_gt1000us=1))
        with self.assertRaisesRegex(ValueError, "retained burst target"):
            module.kernel_write_delta(
                before, dict(after, retained_burst_target=0))
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


if __name__ == "__main__":
    unittest.main()
