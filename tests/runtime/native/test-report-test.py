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
                                               ROOT / "tests/tools/run-tests.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def lower_inflight(*, has_reads):
    read_peak = 1 if has_reads else 0
    read_mean = 0.25 if has_reads else 0.0
    write_mean = 0.50
    return {
        "target_interval_ns": 500000,
        "samples": 4000,
        "read_start": 0,
        "write_start": 0,
        "read_end": 0,
        "write_end": 0,
        "read_peak": read_peak,
        "write_peak": 1,
        "total_peak": 1,
        "read_time_weighted": read_mean,
        "write_time_weighted": write_mean,
        "total_time_weighted": read_mean + write_mean,
    }


def timed_kernel_write(*, mode, target=8):
    record = {field: 0 for field in runner.KERNEL_WRITE_FIELDS}
    record.update({
        "physical_write_reqs": 5,
        "lz4_wall_ns": 20000000,
        "ordered_lz4_wall_ns": 15000000,
        "prep_lz4_wall_ns": 5000000,
        "write_copy_wall_ns": 3000000,
        "write_copy_bytes": 6000000,
        "ordered_write_copy_wall_ns": 2000000,
        "prep_write_copy_wall_ns": 1000000,
        "direct_lz4_input_pages": 3000,
        "window_sort_wall_ns": 1000000,
        "window_commit_wall_ns": 40000000,
        "window_commit_nonio_wall_ns": 10000000,
        "engine_plan_wall_ns": 1000000,
        "engine_pack_wall_ns": 2000000,
        "engine_publish_wall_ns": 3000000,
        "engine_publish_crc_wall_ns": 1000000,
        "engine_publish_auth_wall_ns": 2000000,
        "engine_prehashed_records": 2500,
        "batch_snapshot_crc_wall_ns": 250000,
        "batch_pause_crc_wall_ns": 100000,
        "batch_resume_crc_wall_ns": 150000,
        "prep_crc_wall_ns": 700000,
        "ordered_crc_wall_ns": 1300000,
        "lower_write_wall_ns": 30000000,
        "ordered_worker_wall_ns": 52000000,
        "prep_worker_wall_ns": 5000000,
        "ordered_worker_cpu_ns": 16000000,
        "prep_worker_cpu_ns": 3000000,
        "read_worker_cpu_ns": 1000000,
        "prep_wait_wall_ns": 500000,
        "prep_lower_write_overlap_ns": 5000000,
        "prep_lower_write_samples": 5,
        "prep_lower_write_start_queued": 4,
        "prep_lower_write_start_nonempty": 3,
        "prep_lower_write_end_queued": 1,
        "prep_lower_write_end_nonempty": 1,
        "pipeline_async_runs": 4 if mode else 0,
        "pipeline_active_wall_ns": 800000000 if mode else 0,
        "pipeline_finalize_wait_wall_ns": 5000000 if mode else 0,
        "k1_ready_wait_windows": 2 if mode else 0,
        "k1_ready_wait_records": 12 if mode else 0,
        "k1_ready_wait_wall_ns": 4000000 if mode else 0,
        "k1_ready_wait_max_records": 8 if mode else 0,
        "k1_ready_wait_pack_ready": 2 if mode else 0,
        "write_wait_le1ms": 2,
        "write_wait_1to4ms": 2,
        "write_wait_gt4ms": 1,
        "retained_burst_target": target,
        "windows": 20,
        "one_page_windows": 4,
        "win1": 4,
        "win3_4": 8,
        "win5_8": 8,
        "close_idle": 4,
        "close_deadline": 2,
        "close_pack_ready": 14,
        "pack_close_tail_target": 5,
        "pack_close_tail_target_le4": 4,
        "pack_close_burst_target": 6,
        "pack_close_service_dry": 3,
        "pack_close_burst_admission": 4,
        "pack_close_burst_worker": 2,
        "pack_close_burst_target_le4": 2,
        "pack_close_burst_target_5_8": 4,
        "pack_close_burst_count_le4": 1,
        "pack_close_burst_count_5_8": 5,
        "pack_close_burst_overshoot": 1,
        "pack_tail_samples": 6,
        "pack_tail_zero_inflight": 2 if mode else 0,
        "pack_tail_zero_idle": 1 if mode else 2,
        "pack_tail_one_inflight": 1 if mode else 0,
        "pack_tail_one_idle": 0 if mode else 1,
        "pack_tail_many_inflight": 1 if mode else 0,
        "pack_tail_many_idle": 1 if mode else 3,
        "burst_target_grows": 3 if mode else 2,
        "burst_target_shrinks": 2 if mode else 1,
        "win1_idle": 1,
        "win1_deadline": 2,
        "win1_pack_ready": 1,
        "win1_pack_tail_target": 1,
        "win1_pack_read_bypass": 0,
        "win1_pack_wave_interrupted": 0,
        "deadline_before_bio": 1,
        "deadline_worker_empty": 1,
        "packed_early_commits": 8,
        "single_pack_deferrals": 24,
        "accepted_burst_extensions": 6,
        "accepted_burst_tail_flushes": 5,
        "accepted_burst_read_caps": 4,
        "prep_lower_write_overlap_starts": 42 if mode else 0,
        "prep_wave_kicks": 5 if mode else 0,
        "prep_producer_head_claims": 2 if mode else 0,
        "prep_producer_tail_claims": 3 if mode else 0,
        "prep_ordered_inline": 4 if mode else 0,
        "prep_ordered_handoffs": 3 if mode else 0,
        "prep_ordered_waits": 1 if mode else 0,
    })
    return record


def arm(candidate, *, mode, regime):
    swapz = candidate == "swapz"
    raw_mbps = 14 if regime == "sd_emulated" else 32
    cand_mbps = (20 if mode == 0 else 20.01) if regime == "sd_emulated" else (
        24 if mode == 0 else 24.01)
    raw_read_time = 1.0
    packed = {
        "logical_bytes": 4194304,
        "logical_image_sha256": "d" * 64,
        "packed_close_delta": 4 if swapz else None,
        "qualification": ("OWNED_PACK_READY_AND_VERIFIED_4MIB_READ" if swapz
                          else "ROOTLESS_NO_PACK_PROOF"),
        "passes": {
            key: {
                "logical_bytes": 4194304,
                "verified_pages": 1024,
                "verified_image_sha256": "d" * 64,
                "seconds": raw_read_time * (0.9 if swapz else 1.),
                "useful_read_mbps": 4.19 if not swapz else 4.65,
                "read_p99_ms": 2 if swapz else 3,
                "lower_io": {
                    "lower_read_bytes": 6291456 if swapz else 4194304,
                    "lower_read_requests": 1536 if swapz else 1024,
                },
                "kernel_read_path": ({
                    "read_meta_reqs": 1024,
                    "read_payload_reqs": 512,
                    "read_payload_blocks": 512,
                    "lower_read_wall_ns": 120000000,
                    "decode_wall_ns": 20000000,
                    "read_copy_wall_ns": 4000000,
                    "read_copy_bytes": 4194304,
                    "read_engine_nonio_wall_ns": 6000000,
                    "read_meta_cache_hits": 128,
                    "read_meta_lru_hits": 100,
                    "read_full_extent_reqs": 200,
                    "read_full_cache_hits": 64,
                    "read_two_block_skips": 128,
                    "parallel_read_pairs": 128,
                    "parallel_read_same_extent_pairs": 64,
                    "parallel_read_distinct_extent_pairs": 64,
                    "parallel_read_adjacent_extent_pairs": 24,
                    "parallel_read_adjacent_extent_blocks": 144,
                    "read_worker_cpu_ns": 1000000,
                } if swapz else None),
                "replay_cpu_user_s": .15,
                "replay_cpu_system_s": .12,
                "replay_peak_rss_kb": 12000,
            }
            for key in ("sequential", "seeded_random")
        },
    }
    return {
        "candidate": candidate, "verdict": "PASS",
        "source_sha": "a" * 40,
        "fixture_sha256": "b" * 64, "trace_sha256": "c" * 64,
        "device_identity": {"device": "PRIVATE_DEVICE_MUST_NOT_ESCAPE"},
        "throughput_mbps": {
            "logical_write_mbps": cand_mbps if swapz else raw_mbps,
            "lower_write_mbps": 12 if swapz else 14,
            "logical_read_mbps": 7 if swapz else 4,
            "logical_write_bytes": 8000, "logical_read_bytes": 4000,
        },
        "lower_io": {
            "lower_write_bytes": 5000 if swapz else 8000,
            "lower_read_bytes": 4000,
            "lower_write_requests": 5 if swapz else 8,
            "lower_read_requests": 4,
        },
        "read_p95_ns": 4000000 if swapz else 8000000,
        "read_p99_ns": 5000000 if swapz else 10000000,
        "write_p99_ns": 2000000,
        "seconds": 2, "verified_pages": 1024,
        "mixed_replay_cpu_user_s": .12,
        "mixed_replay_cpu_system_s": .08,
        "mixed_replay_peak_rss_kb": 12000,
        "lower_inflight": lower_inflight(has_reads=True),
        "workload_opportunity": {
            "scope": "TRACE_FIXTURE_OPPORTUNITY_ONLY_NOT_KERNEL_SAVINGS",
            "measured_write_ops": 100,
            "measured_unique_write_payloads": 20,
            "nonzero_same_filled_write_ops": 5,
            "same_page_rewrite_ops": 7,
            "resident_duplicate_write_ops": 30,
            "final_live_unique_payloads": 18,
            "final_live_duplicate_pages": 40,
            "final_live_nonzero_same_filled_pages": 3,
        },
        "packed_read": packed,
        "kernel_write_path": (timed_kernel_write(mode=mode, target=8)
                              if swapz else None),
    }



def parallel_arm(enabled):
    record = arm("swapz", mode=0, regime="ssd_emulated")
    for phase in record["packed_read"]["passes"].values():
        if not enabled:
            phase["kernel_read_path"]["parallel_read_pairs"] = 0
            phase["kernel_read_path"]["parallel_read_same_extent_pairs"] = 0
        else:
            phase["kernel_read_path"]["parallel_read_pairs"] = 128
            phase["kernel_read_path"]["parallel_read_same_extent_pairs"] = 64
    return record


def write_arm(candidate, *, qd, regime, mode):
    swapz = candidate == "swapz"
    raw = 8.0 if regime == "sd_emulated" else 20.0
    swapz_rate = raw * (0.72 + qd / 200.0)
    logical = 4096 * 4096
    lower = int(logical / 1.40) if swapz else logical
    return {
        "candidate": candidate, "verdict": "PASS",
        "source_sha": "a" * 40,
        "fixture_sha256": "b" * 64,
        "trace_sha256": (f"{qd:x}" * 64)[:64],
        "throughput_mbps": {
            "logical_write_mbps": swapz_rate if swapz else raw,
            "lower_write_mbps": (swapz_rate / 1.40) if swapz else raw,
            "logical_read_mbps": 0.0,
            "logical_write_bytes": logical,
            "logical_read_bytes": 0,
        },
        "lower_io": {
            "lower_write_bytes": lower,
            "lower_write_requests": 1600 if swapz else 4096,
            "lower_read_bytes": 0,
            "lower_read_requests": 0,
        },
        "write_p99_ns": 2500000 if swapz else 1500000,
        "seconds": 2.0,
        "mixed_replay_cpu_user_s": .12,
        "mixed_replay_cpu_system_s": .08,
        "mixed_replay_peak_rss_kb": 12000,
        "lower_inflight": lower_inflight(has_reads=False),
        "kernel_write_path": (timed_kernel_write(
            mode=mode, target=max(4, qd)) if swapz else None),
    }

def synthetic_log():
    out = ["HOST_SWAPS_BEFORE:", "/private/system/swapfile",
           "SOURCE_HEAD=a" + "a" * 39,
           "PASS_LOADED_ORACLE_PROFILE=raw_pages:64 zero_pages:9 flush_calls:2",
           "PASS_LOADED_LIVE_GC=victims:12 rotations:12 pages:12 read_bytes:49152 write_bytes:49152 read_reqs:12 write_reqs:12 distinct:6 victim_min:1 victim_max:3 last:11->29 discards:12 discard_sectors:24576 discard_unsupported:0 discard_failed:0 verified_pages:4096",
           "PASS_LOADED_SUSPEND_DRAIN=retain_ms:4 observed_open:1 verified_pages:128",
           "PASS_RETAINED_SYNTHETIC_WRITE_FAULT=retain_ms:2 injected:1 lower_write_delta:0",
           "PASS_RETAINED_SYNTHETIC_FLUSH_FAULT=retain_ms:2 injected:1 data_write_reached_lower:1",
           "PASS_LOADED_OWNED_NULLBLK_SMOKE"]
    for regime in runner.MODEL_ORDER:
        spec = runner.MODEL_SPECS[regime]
        out.append(f"START_OWNED_RAM_REGIME={regime}")
        modes = (runner.CONFIRMATION_SEQUENCE
                 if regime == "ssd_emulated" else (0, 1, 1, 0))
        for i, mode in enumerate(modes):
            out.append(f"START_OWNED_RAM_PAIR_ASYNC_PREPARE={mode}")
            out.append("REPLAY_ORDER=swapz-first" if i % 2 else "REPLAY_ORDER=off-first")
            out.append("PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} HW_QUEUE_DEPTH={hw_queue_depth}".format(**spec))
            out.append("SWAPZ_STATUS_BEFORE=windows=0 close_unknown=0 close_full=0 close_duplicate=0 close_zero=0 close_fua=0 close_raw=0 close_read_conflict=0 close_read_unrelated=0 close_discard=0 close_preflush=0 close_quantum=0 close_idle=0 close_shutdown=0 close_other=0 close_deadline=0 close_pack_ready=0 packed_early_commits=0 single_pack_deferrals=0 accepted_burst_extensions=0 accepted_burst_tail_flushes=0 accepted_burst_read_caps=0 retained_burst_target=4 one_page_windows=0 gc_victims=0 gc_role_rotations=0 win1_unknown=0 win1_full=0 win1_duplicate=0 win1_zero=0 win1_fua=0 win1_raw=0 win1_read_conflict=0 win1_read_unrelated=0 win1_discard=0 win1_preflush=0 win1_quantum=0 win1_idle=0 win1_shutdown=0 win1_other=0 win1_deadline=0 win1_pack_ready=0 win1_pack_tail_target=0 win1_pack_read_bypass=0 win1_pack_wave_interrupted=0 single_tail_deferrals=0 single_tail_companions=0 win1_deadline_deferred_tail=0 win1_idle_deferred_tail=0 single_tail_other_clears=0 deadline_before_bio=0 deadline_after_read=0 deadline_worker_with_local=0 deadline_worker_empty=0 prep_producer_head_claims=0 prep_producer_tail_claims=0 prep_ordered_inline=0 prep_ordered_handoffs=0 prep_ordered_waits=0 prep_lower_write_overlap_starts=0 prep_wave_kicks=0")
            out.append("SWAPZ_STATUS_AFTER=windows=20 close_unknown=0 close_full=0 close_duplicate=0 close_zero=0 close_fua=0 close_raw=0 close_read_conflict=0 close_read_unrelated=0 close_discard=0 close_preflush=0 close_quantum=0 close_idle=0 close_shutdown=0 close_other=0 close_deadline=2 close_pack_ready=18 packed_early_commits=8 single_pack_deferrals=24 accepted_burst_extensions=6 accepted_burst_tail_flushes=5 accepted_burst_read_caps=4 retained_burst_target=8 one_page_windows=4 gc_victims=0 gc_role_rotations=0 win1_unknown=0 win1_full=0 win1_duplicate=0 win1_zero=0 win1_fua=0 win1_raw=0 win1_read_conflict=0 win1_read_unrelated=1 win1_discard=0 win1_preflush=0 win1_quantum=0 win1_idle=0 win1_shutdown=0 win1_other=0 win1_deadline=2 win1_pack_ready=1 win1_pack_tail_target=1 win1_pack_read_bypass=0 win1_pack_wave_interrupted=0 single_tail_deferrals=0 single_tail_companions=0 win1_deadline_deferred_tail=0 win1_idle_deferred_tail=0 single_tail_other_clears=0 deadline_before_bio=1 deadline_after_read=0 deadline_worker_with_local=0 deadline_worker_empty=1 prep_producer_head_claims=2 prep_producer_tail_claims=3 prep_ordered_inline=4 prep_ordered_handoffs=3 prep_ordered_waits=1 prep_lower_write_overlap_starts=42 prep_wave_kicks=5")
            for candidate in (("swapz", "off") if i % 2 else ("off", "swapz")):
                out.append(json.dumps(arm(candidate, mode=mode, regime=regime)))
            if mode:
                out.append("PASS_ASYNC_LOWER_IO_OVERLAP_STARTS=42")
            out.append(f"PASS_OWNED_RAM_PAIR_ASYNC_PREPARE={mode}")
        out.append(f"PASS_OWNED_RAM_REGIME={regime}")
    spec = runner.MODEL_SPECS["ssd_emulated"]
    for index, enabled in enumerate(runner.CONFIRMATION_SEQUENCE):
        out.append(f"START_PARALLEL_READ_AB={enabled}")
        out.append("REPLAY_ORDER=swapz-first" if index % 2 else
                   "REPLAY_ORDER=off-first")
        out.append(
            "PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} "
            "COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} "
            "QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} "
            "HW_QUEUE_DEPTH={hw_queue_depth}".format(**spec))
        raw = arm("off", mode=0, regime="ssd_emulated")
        swapz = parallel_arm(enabled)
        for record in ((swapz, raw) if index % 2 else (raw, swapz)):
            out.append(json.dumps(record))
        out.append(f"PASS_PARALLEL_READ_AB={enabled}")
    for regime in runner.MODEL_ORDER:
        spec = runner.MODEL_SPECS[regime]
        out.append(f"START_WRITE_SATURATION_REGIME={regime}")
        index = 0
        for qd in (1, 4, 8, 32):
            modes = (runner.CONFIRMATION_SEQUENCE
                     if regime == "ssd_emulated" and qd == 8
                     else (0, 1))
            for mode in modes:
                out.append(
                    f"START_WRITE_SATURATION_PAIR_QD={qd} ASYNC_PREPARE={mode}")
                out.append("REPLAY_ORDER=swapz-first" if index % 2 else
                           "REPLAY_ORDER=off-first")
                out.append(
                    "PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} "
                    "COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} "
                    "QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} "
                    "HW_QUEUE_DEPTH={hw_queue_depth}".format(**spec))
                out.append(
                    "SWAPZ_STATUS_BEFORE=windows=0 one_page_windows=0 "
                    "win1=0 win2=0 win3_4=0 win5_8=0 win9_16=0 "
                    "win17_64=0 close_idle=0 close_deadline=0 "
                    "close_pack_ready=0 retained_burst_target=4 prep_producer_head_claims=0 prep_producer_tail_claims=0 prep_ordered_inline=0 prep_ordered_handoffs=0 prep_ordered_waits=0 prep_lower_write_overlap_starts=0 prep_wave_kicks=0")
                out.append(
                    "SWAPZ_STATUS_AFTER=windows=20 one_page_windows=4 "
                    "win1=4 win2=0 win3_4=8 win5_8=8 win9_16=0 "
                    "win17_64=0 close_idle=4 close_deadline=2 "
                    f"close_pack_ready=14 retained_burst_target={max(4, qd)} prep_producer_head_claims=2 prep_producer_tail_claims=3 prep_ordered_inline=4 prep_ordered_handoffs=3 prep_ordered_waits=1 prep_lower_write_overlap_starts=42 prep_wave_kicks=5")
                for candidate in (("swapz", "off") if index % 2 else ("off", "swapz")):
                    out.append(json.dumps(write_arm(
                        candidate, qd=qd, regime=regime, mode=mode)))
                out.append(
                    f"PASS_WRITE_SATURATION_PAIR_QD={qd} ASYNC_PREPARE={mode}")
                index += 1
        out.append(f"PASS_WRITE_SATURATION_REGIME={regime}")
    return "\n".join(out) + "\n"


class ReportContract(unittest.TestCase):
    def test_unsupported_owned_storage_delay_tuples_fail_before_privilege(self):
        """Reject arbitrary timer or cap input BEFORE touching host devices."""
        import subprocess
        script = ROOT / "tests/tools/benchmark-owned-pair.sh"
        common = ["bash", str(script), "--run-owned-ram-pair",
                  "--profile", "medium", "--retain-ms", "2", "--unpaced"]
        forbidden = (
            ("--lower-mbps", "80", "--completion-nsec", "1000000"),
            ("--lower-mbps", "10", "--completion-nsec", "150000"),
            ("--lower-mbps", "80", "--completion-nsec", "5"),
            ("--lower-mbps", "999", "--completion-nsec", "150000"),
            ("--completion-nsec", "1000000"),
            ("--lower-mbps", "12"),
            ("--lower-mbps", "20"),
            ("--lower-mbps", "0"),
            ("--lower-mbps", "10"),
        )
        for option in forbidden:
            with self.subTest(option=option):
                run = subprocess.run(common + list(option), text=True,
                                     capture_output=True, timeout=4)
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertIn("BLOCKED", run.stderr)
        source = script.read_text()
        for key in ('"$config/mbps"', '"$config/irqmode"',
                    '"$config/completion_nsec"', '"$config/memory_backed"'):
            self.assertIn(key, source)
        self.assertIn('PASS_RAM_MODEL_LOWER_MBPS=', source)
        # The deleted shell preflight was redundant with this rootless
        # Python contract. Preserve teardown/ownership/swap guard checks.
        for gate in ("SWAPS=", "nullb-swapz-", "memory_backed",
                     "dmsetup remove", "QUARANTINE=0",
                     "READY_COUNT=0", "COUNT != READY_COUNT",
                     "--expected-dm-uuid", "timeout --signal=TERM"):
            self.assertIn(gate, source)
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        self.assertIn("for regime in sd_emulated ssd_emulated", loaded)
        self.assertIn("START_WRITE_SATURATION_PAIR_QD=", loaded)
        self.assertIn("START_PARALLEL_READ_AB=", loaded)
        self.assertIn("--parallel-reads", loaded)
        self.assertIn("--write-only-qd", loaded)
        self.assertNotIn("swapon ", loaded)
        self.assertNotIn("swapoff ", loaded)
        self.assertNotIn("/dev/sdb", loaded)

    def test_loaded_lifecycle_markers_are_strict_and_sanitized(self):
        loaded = runner.parse_loaded_correctness(synthetic_log())
        self.assertEqual(loaded["overall"], "PASS")
        self.assertEqual(loaded["raw_pages"], 64)
        self.assertEqual(loaded["gc_victims"], 12)
        self.assertEqual(loaded["gc_rotations"], 12)
        self.assertEqual(loaded["gc_distinct_victims"], 6)
        self.assertEqual(loaded["gc_victim_min_evictions"], 1)
        self.assertEqual(loaded["gc_victim_max_evictions"], 3)
        self.assertEqual(loaded["gc_verified_pages"], 4096)
        self.assertEqual(loaded["gc_segment_discards"], 12)
        self.assertEqual(loaded["gc_segment_discard_sectors"], 24576)
        self.assertEqual(loaded["suspend_retain_ms"], 4)
        self.assertEqual(loaded["suspend_observed_open"], 1)
        self.assertEqual(loaded["suspend_verified_pages"], 128)
        self.assertIn("PRE_SUBMISSION", loaded["retained_write_fault"])

        missing_gc = synthetic_log().replace(
            "PASS_LOADED_LIVE_GC=victims:12 rotations:12 pages:12 "
            "read_bytes:49152 write_bytes:49152 read_reqs:12 write_reqs:12 "
            "distinct:6 victim_min:1 victim_max:3 last:11->29 "
            "discards:12 discard_sectors:24576 discard_unsupported:0 "
            "discard_failed:0 verified_pages:4096\n", "")
        self.assertEqual(runner.parse_loaded_correctness(missing_gc)["overall"],
                         "INCOMPLETE")

        missing = synthetic_log().replace(
            "PASS_LOADED_SUSPEND_DRAIN=retain_ms:4 observed_open:1 "
            "verified_pages:128\n", "")
        self.assertEqual(runner.parse_loaded_correctness(missing)["overall"],
                         "INCOMPLETE")

        bad = synthetic_log().replace(
            "PASS_RETAINED_SYNTHETIC_WRITE_FAULT=retain_ms:2 injected:1 "
            "lower_write_delta:0",
            "PASS_RETAINED_SYNTHETIC_WRITE_FAULT=retain_ms:2 injected:1 "
            "lower_write_delta:1")
        self.assertEqual(runner.parse_loaded_correctness(bad)["overall"],
                         "INCOMPLETE")

    def test_immutable_inputs_and_alternating_arm_order(self):
        sessions = runner.parse_sessions(synthetic_log())
        self.assertEqual(len(sessions), 14)
        parallel = runner.parse_parallel_read_ab(synthetic_log())
        self.assertEqual([row["parallel_reads"] for row in parallel],
                         list(runner.CONFIRMATION_SEQUENCE))
        diagnostic = runner.parallel_read_ab_verdict(parallel)
        self.assertEqual(diagnostic["overall"],
                         "PASS_PARALLEL_READ_AB_CONFIRMATION")
        self.assertEqual(diagnostic["matched_pairs"], 5)
        self.assertEqual(
            diagnostic["paired"]["sequential"]["p99_change_fraction"]["n"], 5)
        self.assertEqual(diagnostic["modes"]["0"]["sequential"]["parallel_read_pairs"], 0)
        self.assertGreater(diagnostic["modes"]["1"]["sequential"]["parallel_read_pairs"], 0)
        inactive = runner.parse_parallel_read_ab(synthetic_log())
        next(row for row in inactive if row["parallel_reads"] == 1)["swapz"]["passes"][
            "sequential"]["kernel_read_path"]["parallel_read_pairs"] = 0
        rejected = runner.parallel_read_ab_verdict(inactive)
        self.assertEqual(rejected["overall"], "INCOMPLETE")
        self.assertIn("executed no parallel pairs", rejected["reason"])
        self.assertEqual(
            [s["async_prepare"] for s in sessions],
            [0, 1, 1, 0] + list(runner.CONFIRMATION_SEQUENCE))
        self.assertEqual(
            [s["regime"] for s in sessions],
            ["sd_emulated"] * 4 + ["ssd_emulated"] * 10)
        self.assertEqual([s["order"] for s in sessions],
                         ["off-first", "swapz-first"] * 7)
        self.assertTrue(all(s["status"] == "PASS" for s in sessions))
        for j, session in enumerate(sessions):
            self.assertEqual(session["device_model"],
                             {k: runner.MODEL_SPECS[session["regime"]][k]
                              for k in ("cap_mib_s", "completion_nsec", "irqmode",
                                        "queue_mode", "submit_queues",
                                        "hw_queue_depth")})
            if session["async_prepare"]:
                self.assertEqual(session["overlap_starts"], 42)
            else:
                self.assertNotIn("overlap_starts", session)
        self.assertNotIn("device_identity", json.dumps(sessions))
        self.assertNotIn("PRIVATE_DEVICE_MUST_NOT_ESCAPE", json.dumps(sessions))
        self.assertTrue(all("kernel_status" not in session for session in sessions))

    def test_write_saturation_evidence_repeats_only_fast_qd8(self):
        sessions = runner.parse_write_saturation(synthetic_log())
        self.assertEqual(len(sessions), 24)
        verdict = runner.write_saturation_verdict(sessions)
        self.assertEqual(verdict["overall"], "PASS_WRITE_SATURATION_EVIDENCE")
        self.assertEqual(verdict["fast_qd8_matched_pairs"], 5)
        self.assertEqual(
            verdict["fast_qd8_paired"]["throughput_change_fraction"]["n"], 5)
        self.assertIn("PAIRED_95PCT_CI", verdict["confidence"])
        self.assertEqual(
            verdict["regimes"]["sd_emulated"][2]["retained_burst_target"], 4)
        self.assertEqual(
            verdict["regimes"]["sd_emulated"][4]["retained_burst_target"], 8)
        self.assertEqual(
            verdict["regimes"]["sd_emulated"][2]["window_delta"]["win3_4"], 8)
        self.assertEqual(
            verdict["regimes"]["sd_emulated"][2]["timed_window_delta"]
            ["win1_pack_ready"], 1)
        self.assertEqual(
            verdict["regimes"]["sd_emulated"][2]["timed_window_delta"]
            ["deadline_worker_empty"], 1)
        self.assertEqual(
            verdict["regimes"]["sd_emulated"][3]["preparation_delta"]
            ["prep_producer_tail_claims"], 3)
        self.assertEqual(
            [(p["qd"], p["mode"]) for p in verdict["regimes"]["sd_emulated"]],
            [(1, "sync"), (1, "async"), (4, "sync"), (4, "async"),
             (8, "sync"), (8, "async"), (32, "sync"), (32, "async")])
        fast_qd4 = [p for p in verdict["regimes"]["ssd_emulated"]
                    if p["qd"] == 4]
        fast_qd8 = [p for p in verdict["regimes"]["ssd_emulated"]
                    if p["qd"] == 8]
        self.assertEqual([p["observations"] for p in fast_qd4], [1, 1])
        self.assertEqual([p["observations"] for p in fast_qd8], [5, 5])
        broken = runner.parse_write_saturation(synthetic_log())
        broken[0]["arms"]["off"]["logical_read_bytes"] = 4096
        self.assertEqual(runner.write_saturation_verdict(broken)["overall"],
                         "INCOMPLETE")
        for field, bad_value in (
                ("source_sha", "b" * 40),
                ("fixture_sha256", "c" * 64),
                ("trace_sha256", "d" * 64)):
            with self.subTest(provenance=field):
                broken = runner.parse_write_saturation(synthetic_log())
                broken[0]["arms"]["off"][field] = bad_value
                self.assertEqual(
                    runner.write_saturation_verdict(broken)["overall"],
                    "INCONCLUSIVE")

    def test_paired_benchmark_provenance_mismatch_is_inconclusive(self):
        for field, bad_value in (
                ("source_sha", "b" * 40),
                ("fixture_sha256", "c" * 64),
                ("trace_sha256", "d" * 64)):
            with self.subTest(provenance=field):
                sessions = runner.parse_sessions(synthetic_log())
                sessions[0]["arms"]["off"][field] = bad_value
                self.assertEqual(
                    runner.benchmark_verdicts(sessions)["overall"],
                    "INCONCLUSIVE")

    def test_slow_model_gain_and_fast_model_loss_are_both_visible(self):
        data = runner.benchmark_verdicts(runner.parse_sessions(synthetic_log()))
        self.assertEqual(data["overall"], "PASS_BOUNDED_RAM_MATRIX")
        slow = data["regimes"]["sd_emulated"]
        fast = data["regimes"]["ssd_emulated"]
        self.assertEqual(slow["criteria"]["sync"]["throughput_vs_raw"],
                         "MATERIAL_GAIN_PRELIMINARY")
        self.assertEqual(fast["criteria"]["sync"]["throughput_vs_raw"],
                         "MATERIAL_LOSS_PRELIMINARY")
        self.assertEqual(fast["interpretation"],
                         "SYNTHETIC_RAM_MODEL_ONLY_NOT_PHYSICAL_MEDIA")
        self.assertEqual(data["regimes"]["sd_emulated"]["device_model"]["completion_nsec"],
                         1000000)
        self.assertEqual(data["regimes"]["ssd_emulated"]["device_model"]["cap_mib_s"],
                         80)
        self.assertEqual(
            data["workload_opportunity"]["resident_duplicate_write_ops"], 30)
        self.assertEqual(
            data["workload_opportunity"]["nonzero_same_filled_write_ops"], 5)
        self.assertAlmostEqual(
            slow["criteria"]["sync"]["lower_write_saved_fraction"], .375)
        self.assertEqual(
            slow["criteria"]["async_vs_sync"]["write_throughput"],
            "NO_SIGNIFICANT_ASYNC_GAIN")
        self.assertAlmostEqual(
            slow["columns"]["sync"]["sequential_4mib_s"], .9)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_reqs"], 1024)
        self.assertEqual(slow["columns"]["async"]["seeded_random_read_payload_reqs"], 512)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_copy_wall_ns"], 4000000)
        self.assertEqual(slow["columns"]["async"]["seeded_random_read_copy_bytes"], 4194304)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_engine_nonio_wall_ns"], 6000000)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_cache_hits"], 128)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_lru_hits"], 100)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_full_extent_reqs"], 200)
        self.assertEqual(slow["columns"]["async"]["seeded_random_read_full_cache_hits"], 64)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_two_block_skips"], 128)
        self.assertEqual(slow["columns"]["sync"]["sequential_parallel_read_pairs"], 128)
        self.assertEqual(slow["columns"]["sync"]["sequential_parallel_read_same_extent_pairs"], 64)
        self.assertEqual(slow["columns"]["sync"]["mixed_physical_write_reqs"], 5)
        self.assertEqual(slow["columns"]["async"]["mixed_write_wait_gt4ms"], 1)
        self.assertEqual(slow["columns"]["sync"]["mixed_write_copy_wall_ns"], 3000000)
        self.assertEqual(slow["columns"]["sync"]["mixed_ordered_lz4_wall_ns"], 15000000)
        self.assertEqual(slow["columns"]["async"]["mixed_prep_lz4_wall_ns"], 5000000)
        self.assertEqual(slow["columns"]["async"]["mixed_ordered_write_copy_wall_ns"], 2000000)
        self.assertEqual(slow["columns"]["async"]["mixed_prep_write_copy_wall_ns"], 1000000)
        self.assertEqual(slow["columns"]["async"]["mixed_write_copy_bytes"], 6000000)
        self.assertEqual(slow["columns"]["async"]["mixed_direct_lz4_input_pages"], 3000)
        self.assertEqual(slow["columns"]["sync"]["mixed_window_commit_nonio_wall_ns"], 10000000)
        self.assertEqual(slow["columns"]["sync"]["mixed_engine_plan_wall_ns"], 1000000)
        self.assertEqual(slow["columns"]["sync"]["mixed_engine_pack_wall_ns"], 2000000)
        self.assertEqual(slow["columns"]["sync"]["mixed_engine_publish_wall_ns"], 3000000)
        self.assertEqual(slow["columns"]["sync"]["mixed_engine_publish_crc_wall_ns"], 1000000)
        self.assertEqual(slow["columns"]["sync"]["mixed_engine_publish_auth_wall_ns"], 2000000)
        self.assertEqual(slow["columns"]["async"]["mixed_prep_lower_write_samples"], 5)
        self.assertEqual(slow["columns"]["async"]["mixed_prep_lower_write_start_queued"], 4)
        self.assertEqual(slow["columns"]["async"]["mixed_prep_lower_write_end_queued"], 1)
        self.assertEqual(
            slow["columns"]["async"]["lower_inflight_write_time_weighted"], .5)
        self.assertEqual(slow["columns"]["async"]["lower_inflight_write_peak"], 1)
        self.assertEqual(slow["columns"]["async"]["mixed_pipeline_active_mean"], .4)
        self.assertEqual(slow["columns"]["async"]["mixed_pipeline_active_peak"], 1)
        self.assertEqual(slow["columns"]["sync"]["mixed_pipeline_active_mean"], 0)
        self.assertEqual(slow["columns"]["sync"]["mixed_lower_write_wall_ns"], 30000000)
        self.assertEqual(slow["columns"]["sync"]["mixed_ordered_worker_wall_ns"], 52000000)
        self.assertEqual(slow["columns"]["async"]["mixed_prep_worker_wall_ns"], 5000000)
        self.assertEqual(slow["columns"]["async"]["mixed_ordered_worker_cpu_ns"], 16000000)
        self.assertEqual(slow["columns"]["async"]["mixed_prep_worker_cpu_ns"], 3000000)
        self.assertEqual(slow["columns"]["async"]["mixed_read_worker_cpu_ns"], 1000000)
        self.assertEqual(slow["columns"]["async"]["mixed_engine_prehashed_records"], 2500)
        self.assertEqual(
            slow["columns"]["async"]["mixed_batch_snapshot_crc_wall_ns"], 250000)
        self.assertEqual(
            slow["columns"]["async"]["mixed_batch_pause_crc_wall_ns"], 100000)
        self.assertEqual(
            slow["columns"]["async"]["mixed_batch_resume_crc_wall_ns"], 150000)
        self.assertEqual(slow["columns"]["async"]["mixed_prep_wait_wall_ns"], 500000)
        self.assertEqual(
            slow["columns"]["async"]["mixed_prep_lower_write_overlap_ns"], 5000000)
        self.assertEqual(slow["preparation_counters"]["prep_wave_kicks"], 5)
        self.assertEqual(slow["kernel_counters"]["single_pack_deferrals"], 24)
        self.assertEqual(slow["kernel_counters"]["accepted_burst_extensions"], 6)
        self.assertEqual(slow["kernel_counters"]["accepted_burst_tail_flushes"], 5)
        self.assertEqual(slow["kernel_counters"]["accepted_burst_read_caps"], 4)
        self.assertEqual(slow["kernel_counters"]["windows"], 20)
        self.assertEqual(slow["kernel_counters"]["close_pack_ready"], 14)
        self.assertEqual(slow["kernel_counters"]["pack_close_tail_target"], 5)
        self.assertEqual(slow["kernel_counters"]["pack_close_tail_target_le4"], 4)
        self.assertEqual(slow["kernel_counters"]["pack_close_burst_target"], 6)
        self.assertEqual(slow["kernel_counters"]["pack_close_service_dry"], 3)
        self.assertEqual(slow["kernel_counters"]["pack_close_burst_admission"], 4)
        self.assertEqual(slow["kernel_counters"]["pack_close_burst_worker"], 2)
        self.assertEqual(slow["kernel_counters"]["pack_close_burst_target_le4"], 2)
        self.assertEqual(slow["kernel_counters"]["pack_close_burst_target_5_8"], 4)
        self.assertEqual(slow["kernel_counters"]["pack_close_burst_count_le4"], 1)
        self.assertEqual(slow["kernel_counters"]["pack_close_burst_count_5_8"], 5)
        self.assertEqual(slow["kernel_counters"]["pack_close_burst_overshoot"], 1)
        self.assertEqual(slow["kernel_counters"]["pack_tail_samples"], 6)
        self.assertEqual(slow["kernel_counters"]["pack_tail_zero_inflight"], 1)
        self.assertEqual(slow["kernel_counters"]["pack_tail_zero_idle"], 1.5)
        self.assertEqual(slow["kernel_counters"]["burst_target_grows"], 2.5)
        self.assertEqual(slow["kernel_counters"]["burst_target_shrinks"], 1.5)
        self.assertEqual(slow["kernel_counters"]["k1_ready_wait_windows"], 1)
        self.assertEqual(slow["kernel_counters"]["k1_ready_wait_records"], 6)
        self.assertEqual(slow["kernel_counters"]["k1_ready_wait_pack_ready"], 1)
        self.assertEqual(slow["kernel_counters"]["close_idle"], 4)
        self.assertEqual(slow["kernel_counters"]["close_deadline"], 2)
        self.assertEqual(slow["kernel_counters"]["win1_deadline"], 2)
        self.assertEqual(slow["kernel_counters"]["win1_pack_ready"], 1)
        self.assertEqual(slow["kernel_counters"]["win1_pack_tail_target"], 1)
        self.assertEqual(slow["kernel_counters"]["win1_pack_read_bypass"], 0)
        self.assertEqual(slow["kernel_counters"]["win1_pack_wave_interrupted"], 0)
        self.assertEqual(slow["kernel_counters"]["win1_idle"], 1)
        self.assertEqual(slow["kernel_counters"]["deadline_before_bio"], 1)
        self.assertEqual(slow["kernel_counters"]["deadline_worker_empty"], 1)
        self.assertEqual(slow["kernel_gauges"]["retained_burst_target"], 8)
        self.assertEqual(data["gc"], "SEPARATE_LOADED_EVIDENCE_REQUIRED")
        self.assertEqual(data["physical_media"], "NOT_TESTED")
        self.assertIn("scheduler-accounted", data["cpu_scope"])
        self.assertIn("PROXY_ONLY", data["endurance"])

    def test_benchmark_console_is_compact_and_keeps_sync_control(self):
        verdicts = runner.benchmark_verdicts(runner.parse_sessions(synthetic_log()))
        saturation = runner.write_saturation_verdict(
            runner.parse_write_saturation(synthetic_log()))
        report = {"benchmarks": {
            "verdicts": verdicts,
            "parallel_read_ab": runner.parallel_read_ab_verdict(
                runner.parse_parallel_read_ab(synthetic_log())),
            "write_saturation": saturation,
            "loaded_correctness": runner.parse_loaded_correctness(synthetic_log()),
        }}
        with contextlib.redirect_stdout(io.StringIO()) as output:
            runner.print_bench(report)
        rendered = output.getvalue()
        self.assertRegex(rendered, r"\|\s*mode\s*\|\s*W\s*\|")
        self.assertIn("| sync", rendered)
        self.assertIn("Lower queue", rendered)
        self.assertIn("K=1 run slot", rendered)
        self.assertIn("Async pipeline", rendered)
        self.assertIn("wave kicks", rendered)
        self.assertIn("scheduling", rendered)
        self.assertIn("Verified 4MiB packed reads", rendered)
        self.assertIn("Packed-read C attribution", rendered)
        self.assertIn("RAM copies", rendered)
        self.assertIn("commit non-I/O", rendered)
        self.assertIn("engine plan", rendered)
        self.assertIn("engine pack", rendered)
        self.assertIn("engine publish", rendered)
        self.assertIn("publish CRC", rendered)
        self.assertIn("publish authority", rendered)
        self.assertIn("batch snapshot CRC", rendered)
        self.assertIn("engine residual", rendered)
        self.assertIn("payload CRC prep", rendered)
        self.assertIn("ordered callback", rendered)
        self.assertIn("prep callback", rendered)
        self.assertIn("lower-W queue start/end", rendered)
        self.assertIn("lower-W nonempty start/end", rendered)
        self.assertIn("deferred tail D/C/DL/I/O", rendered)
        self.assertIn("Workload content opportunity", rendered)
        self.assertIn("resident-dup", rendered)
        self.assertIn("Mixed PACK_READY causes", rendered)
        self.assertIn("Mixed burst-close split", rendered)
        self.assertIn("Mixed post-PACK tail samples", rendered)
        self.assertIn("segment TRIM", rendered)
        self.assertIn("adj-ext", rendered)
        self.assertIn("K=1 ready wait win/records/ms", rendered)
        self.assertIn("K=1 ready wait P/F/D/X/O", rendered)
        self.assertIn("Fast mixed burst-close async-sync paired 95% CI", rendered)
        self.assertIn("async-sync", rendered)
        self.assertIn("Fast mixed async-sync paired 95% CI", rendered)
        self.assertIn("ordered measured floor", rendered)
        self.assertIn("prep measured floor", rendered)
        self.assertIn("deferred C >1ms <=1.25/1.50/1.75/>", rendered)
        self.assertIn("CPU", rendered)
        self.assertIn("deferred C age <=250/500/1000/>", rendered)
        self.assertIn("deferred DL service L/R/B", rendered)
        self.assertIn("Mixed window bins; close=P/D/I", rendered)
        self.assertIn("ID39 SAME-CACHE PARALLEL READ A/B", rendered)
        self.assertNotIn("dry-close followups", rendered)
        self.assertIn("direct LZ4 input", rendered)
        self.assertIn("Lifecycle", rendered)
        self.assertIn("retained WRITE/FLUSH failed closed", rendered)
        self.assertIn("WRITE-ONLY SATURATION EVIDENCE", rendered)
        self.assertNotIn("Fast QD4 A/S paired 95% CI", rendered)
        self.assertIn("Fast QD8 A/S paired 95% CI", rendered)
        self.assertIn("QD1/QD4/QD32 remain directional controls.", rendered)
        self.assertIn("Async preparation", rendered)
        self.assertIn("Async windows; close=P/D/I", rendered)
        self.assertIn("Full telemetry", rendered)
        self.assertIn("test_results.json.xz", rendered)
        self.assertNotIn("All-window close reasons per-pair mean", rendered)
        self.assertNotIn("Timed 4MiB", rendered)
        self.assertNotIn("QD4 sync windows:", rendered)
        self.assertLess(max(map(len, rendered.splitlines())), 96)

    def test_mixed_write_diagnostics_missing_or_inconsistent_fails_closed(self):
        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["arms"]["swapz"]["kernel_write_path"] = None
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[3]["arms"]["swapz"]["kernel_write_path"]["write_wait_gt4ms"] = 2
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[2]["arms"]["swapz"]["kernel_write_path"]["lz4_wall_ns"] = -1
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[2]["arms"]["swapz"]["kernel_write_path"][
            "window_commit_nonio_wall_ns"] = 50000000
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[2]["arms"]["swapz"]["kernel_write_path"][
            "engine_publish_wall_ns"] = 11000000
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[2]["arms"]["swapz"]["kernel_write_path"][
            "engine_publish_crc_wall_ns"] = 2000000
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[2]["arms"]["swapz"]["kernel_write_path"][
            "prep_lower_write_start_nonempty"] = 6
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["arms"]["swapz"]["kernel_write_path"][
            "accepted_burst_tail_flushes"] = 7
        sessions[0]["arms"]["swapz"]["kernel_write_path"][
            "accepted_burst_extensions"] = 6
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["arms"]["swapz"]["kernel_write_path"][
            "accepted_burst_read_caps"] = 7
        sessions[0]["arms"]["swapz"]["kernel_write_path"][
            "accepted_burst_extensions"] = 6
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["arms"]["swapz"]["kernel_write_path"][
            "pack_tail_zero_idle"] += 1
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[1]["arms"]["swapz"]["kernel_write_path"][
            "k1_ready_wait_full"] = 1
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")

    def test_close_and_deadline_accounting_fail_closed(self):
        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["arms"]["swapz"]["kernel_write_path"]["close_zero"] += 1
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")

        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["arms"]["swapz"]["kernel_write_path"]["win1_deadline"] += 1
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")

        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["arms"]["swapz"]["kernel_write_path"][
            "deadline_worker_empty"] += 1
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
    def test_incomplete_mismatch_or_forged_packed_result_fails_closed(self):
        sessions = runner.parse_sessions(synthetic_log())
        self.assertEqual(runner.benchmark_verdicts(sessions[:7])["overall"],
                         "INCOMPLETE")
        sessions[1]["source_sha"] = "different-source"
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCONCLUSIVE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[1]["trace_sha256"] = "tampered-trace"
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCONCLUSIVE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[6]["arms"]["swapz"]["packed_read"]["packed_close_delta"] = 0
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[6]["arms"]["swapz"]["packed_read"]["passes"]["sequential"][
            "logical_bytes"] = 0
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")

        sessions = runner.parse_sessions(synthetic_log())
        sessions[5]["device_model"]["completion_nsec"] = 1234
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions.pop()
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")

    def test_report_replaced_and_not_raw_json_to_terminal(self):
        with tempfile.TemporaryDirectory(prefix="report-", dir=ROOT / "build/tests") as name:
            original_root, original_report = runner.ROOT, runner.REPORT
            try:
                runner.ROOT = Path(name)
                runner.REPORT = runner.ROOT / "test_results.json.xz"
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
                self.assertFalse(path.exists())
                runner.write_report(report)
                first = lzma.open(path, "rt").read()
                self.assertNotIn("SECRET", first)
                report["overall"] = "FAIL"
                runner.write_report(report)
                second = json.loads(lzma.open(path, "rt").read())
                self.assertEqual(second["overall"], "FAIL")
                self.assertEqual(len(list(runner.ROOT.glob("*.xz"))), 1)
                self.assertEqual(path.name, "test_results.json.xz")
            finally:
                runner.ROOT, runner.REPORT = original_root, original_report

    def test_overall_status_follows_stage_semantics_not_raw_exit_code(self):
        self.assertEqual(runner.qualification_overall(0, [{"status": "PASS"}]),
                         "PASS")
        self.assertEqual(runner.qualification_overall(2, [{"status": "FAIL"}]),
                         "FAIL")
        self.assertEqual(runner.qualification_overall(
            2, [{"status": "BLOCKED"}]), "BLOCKED")

    def test_rootless_unittest_failure_names_safe_test(self):
        phase, reason = runner.failure_context(
            "FAIL: test_fixture_schema (__main__.Contract.test_fixture_schema)\n"
            "AssertionError\n",
            loaded=False, default_phase="Native and rootless contracts")
        self.assertEqual(phase, "Native and rootless contracts")
        self.assertEqual(reason, "Unit test failed: test_fixture_schema")

    def test_exit_two_is_fail_before_loaded_stage_and_blocked_only_when_marked(self):
        with tempfile.TemporaryDirectory(prefix="report-", dir=ROOT / "build/tests") as name:
            original_root, original_report = runner.ROOT, runner.REPORT
            try:
                runner.ROOT = Path(name)
                runner.REPORT = runner.ROOT / "test_results.json.xz"
                report = {"schema": "swapz-test-results-v1", "stages": [],
                          "benchmarks": {"sessions": [], "verdicts": {}}}
                rootless = [
                    "python3", "-c",
                    "import sys; print('/private/native.c:155: FAIL: extents == 3'); sys.exit(2)",
                ]
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(
                        runner.run_stage("Native and rootless contracts",
                                         rootless, report), 2)
                stage = report["stages"][-1]
                self.assertEqual(stage["status"], "FAIL")
                self.assertEqual(stage["failed_phase"],
                                 "Native and rootless contracts")
                self.assertIn("extents == 3", stage["diagnostic"])
                self.assertNotIn("/private", stage["diagnostic"])
                self.assertNotIn("administrator", stage["failed_phase"])

                loaded = [
                    "python3", "-c",
                    "import sys; print('BLOCKED_LOADED_QUALIFICATION: no root'); sys.exit(2)",
                ]
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(
                        runner.run_stage("Owned RAM smoke and 8 pairs",
                                         loaded, report, parse_bench=True), 2)
                stage = report["stages"][-1]
                self.assertEqual(stage["status"], "BLOCKED")
                self.assertIn("administrator authorization",
                              stage["failed_phase"])
            finally:
                runner.ROOT, runner.REPORT = original_root, original_report

    def test_parallel_read_diagnostic_failure_reports_its_own_reason(self):
        broken = synthetic_log().replace("PASS_PARALLEL_READ_AB=1\n", "", 1)
        fake_process = type("FakeProcess", (), {
            "stdout": broken,
            "returncode": 0,
        })()
        original_run = runner.subprocess.run
        report = {"schema": "swapz-test-results-v1", "stages": [],
                  "benchmarks": {"sessions": [], "verdicts": {}}}
        try:
            runner.subprocess.run = lambda *args, **kwargs: fake_process
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    runner.run_stage("Owned RAM smoke and 8 pairs",
                                     ["unused"], report, parse_bench=True), 1)
        finally:
            runner.subprocess.run = original_run

        stage = report["stages"][-1]
        self.assertEqual(stage["status"], "FAIL")
        self.assertEqual(stage["failed_phase"], "parallel READ A/B evidence")
        self.assertIn("Kread confirmation", stage["diagnostic"])

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
        self.assertNotIn("swapz", reason)
        self.assertNotIn("abcdef0123456789", reason)

        pair = ("PASS_LOADED_OWNED_NULLBLK_SMOKE\n"
                "START_OWNED_RAM_PAIR_ASYNC_PREPARE=0\n"
                "PASS_OWNED_RAM_PAIR_ASYNC_PREPARE=0\n"
                "START_OWNED_RAM_PAIR_ASYNC_PREPARE=1\n"
                "FAIL: independent backing lower I/O mismatch\n")
        phase, reason = runner.failure_context(pair)
        self.assertIn("comparison 2/8 (async)", phase)
        self.assertIn("backing lower I/O mismatch", reason)
        lifecycle = (
            "START_LOADED_OWNED_NULLBLK_SMOKE\n"
            "START_LOADED_SUSPEND_DRAIN\n"
            "FAIL: retained lifecycle bytes changed\n"
        )
        phase, reason = runner.failure_context(lifecycle)
        self.assertIn("suspend/drain", phase)
        self.assertIn("retained lifecycle bytes changed", reason)

        loaded_subphase = (
            "START_OWNED_RAM_REGIME=sd_emulated\n"
            "START_OWNED_RAM_PAIR_ASYNC_PREPARE=0\n"
            "BENCH_IO_PHASE=swapz:packed_read\n"
            "FAIL: verified fixed volume was not returned\n"
        )
        phase, reason = runner.failure_context(loaded_subphase)
        self.assertIn("sd_emulated comparison 1/8 (sync)", phase)
        self.assertIn("[swapz packed_read]", phase)
        self.assertIn("verified fixed volume", reason)

        replay_detail = (
            "START_OWNED_RAM_REGIME=ssd_emulated\n"
            "START_OWNED_RAM_PAIR_ASYNC_PREPARE=1\n"
            "BENCH_IO_PHASE=swapz:packed_read\n"
            "BLOCKED/FAIL: short or mismatched packed swap-in page\n"
            "BLOCKED: swapz replay rejected\n"
        )
        phase, reason = runner.failure_context(replay_detail)
        self.assertIn("ssd_emulated comparison 1/8 (async)", phase)
        self.assertIn("[swapz packed_read]", phase)
        self.assertEqual(reason, "FAIL: short or mismatched packed swap-in page")

    def test_non_root_fixture_never_uses_privileged_evidence_directory(self):
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        private = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
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




    def test_git_only_report_sync_updates_main_and_keeps_one_report_file(self):
        """Exercise real Git plumbing against a local bare remote."""
        import os
        import subprocess
        from unittest import mock

        def git(*args, cwd, check=True):
            return subprocess.run(["git", *args], cwd=cwd, check=check,
                                  capture_output=True, text=True, timeout=12)

        with tempfile.TemporaryDirectory(
                prefix="report-git-", dir=ROOT / "build/tests") as name:
            sandbox = Path(name)
            checkout, origin = sandbox / "checkout", sandbox / "origin.git"
            checkout.mkdir()
            git("init", "--bare", str(origin), cwd=sandbox)
            git("init", cwd=checkout)
            git("checkout", "-b", "main", cwd=checkout)
            git("config", "user.name", "test-report CI", cwd=checkout)
            git("config", "user.email", "test@example.invalid", cwd=checkout)
            (checkout / "source.c").write_text("int source(void){return 7;}\n")
            (checkout / runner.GIT_RESULT).write_bytes(
                lzma.compress(b'{"overall":"NOT_RUN"}\n'))
            git("add", "source.c", runner.GIT_RESULT, cwd=checkout)
            git("commit", "-m", "Testable source", cwd=checkout)
            source_sha = git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
            git("remote", "add", "origin", str(origin), cwd=checkout)
            git("push", "origin", "main", cwd=checkout)

            old_root, old_report, old_git_result = (
                runner.ROOT, runner.REPORT, runner.git_result)
            runner.ROOT = checkout
            runner.REPORT = checkout / runner.GIT_RESULT

            def intercept(command, *, data=None, timeout=15, env=None):
                if command == ["remote", "get-url", "--push", "origin"]:
                    return subprocess.CompletedProcess(
                        command, 0,
                        stdout=b"git@github.com:k1moradi/swapz.git",
                        stderr=b"")
                return old_git_result(command, data=data, timeout=timeout,
                                      env=env)

            try:
                with mock.patch.object(runner, "git_result",
                                       side_effect=intercept):
                    original = {
                        "schema": "swapz-test-results-v1",
                        "source_sha": source_sha,
                        "tested_commit_sha": source_sha,
                        "overall": "BLOCKED",
                    }
                    runner.write_report(original)
                    first = runner.publish(source_sha)
                    self.assertIn("SYNCED_GIT", first)
                    first_head = git("rev-parse", "HEAD",
                                     cwd=checkout).stdout.strip()
                    first_remote = git("--git-dir", str(origin), "rev-parse",
                                       "refs/heads/main",
                                       cwd=sandbox).stdout.strip()
                    self.assertEqual(first_head, first_remote)
                    self.assertNotEqual(source_sha, first_head)
                    self.assertEqual(git("status", "--porcelain",
                                         cwd=checkout).stdout, "")
                    self.assertEqual(
                        json.loads(lzma.decompress(
                            (checkout / runner.GIT_RESULT).read_bytes())),
                        original)

                    updated = dict(original,
                                   source_sha=first_head,
                                   tested_commit_sha=first_head,
                                   overall="PASS")
                    runner.write_report(updated)
                    second = runner.publish(first_head)
                    self.assertIn("SYNCED_GIT", second)
                    second_head = git("rev-parse", "HEAD",
                                      cwd=checkout).stdout.strip()
                    self.assertNotEqual(first_head, second_head)
                    self.assertEqual(
                        git("--git-dir", str(origin), "rev-parse",
                            "refs/heads/main", cwd=sandbox).stdout.strip(),
                        second_head)
                    self.assertEqual(
                        json.loads(lzma.decompress(
                            (checkout / runner.GIT_RESULT).read_bytes())),
                        updated)
                    self.assertEqual(len(list(checkout.glob("*.xz"))), 1)

                    (checkout / "source.c").write_text("unsaved owner change\n")
                    blocked = dict(updated,
                                   source_sha=second_head,
                                   tested_commit_sha=second_head,
                                   overall="FAIL")
                    runner.write_report(blocked)
                    before = git("--git-dir", str(origin), "rev-parse",
                                 "refs/heads/main", cwd=sandbox).stdout.strip()
                    self.assertIn("not clean", runner.publish(second_head))
                    self.assertEqual(
                        git("--git-dir", str(origin), "rev-parse",
                            "refs/heads/main", cwd=sandbox).stdout.strip(),
                        before)
            finally:
                runner.ROOT, runner.REPORT = old_root, old_report

    def test_publisher_preserves_configured_git_credentials(self):
        source = (ROOT / "tests/tools/run-tests.py").read_text()
        self.assertIn('env["GIT_TERMINAL_PROMPT"] = "0"', source)
        self.assertNotIn('env["GIT_ASKPASS"] = "false"', source)
        self.assertNotIn('env["GCM_INTERACTIVE"] = "never"', source)
        self.assertNotIn('"ls-remote"', source)

    def test_git_sync_declines_invalid_source(self):
        with tempfile.TemporaryDirectory(
                prefix="publish-", dir=ROOT / "build/tests") as name:
            previous_root, previous_report = runner.ROOT, runner.REPORT
            try:
                runner.ROOT = Path(name)
                runner.REPORT = runner.ROOT / runner.GIT_RESULT
                runner.write_report({"source_sha": "unknown",
                                     "overall": "BLOCKED"})
                self.assertIn("unavailable", runner.publish("unknown"))
            finally:
                runner.ROOT, runner.REPORT = previous_root, previous_report


if __name__ == "__main__":
    (ROOT / "build/tests").mkdir(parents=True, exist_ok=True)
    unittest.main()
