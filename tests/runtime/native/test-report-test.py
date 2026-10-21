#!/usr/bin/env python3
"""Rootless contract tests for the sole make test plain JSON reporting pipeline."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("swapz_private_test_runner",
                                               ROOT / "tests/tools/run-tests.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def predictor_evidence():
    thresholds = []
    profile_pages = {"zero": 32, "repeat": 32,
                     "entropy": 64, "mixed": 64, "medium": 64}
    for threshold in runner.PREDICTOR_THRESHOLDS:
        profiles = []
        for name in runner.PREDICTOR_NEGATIVE_PROFILES:
            eligible = 0 if name in ("zero", "repeat") else profile_pages[name]
            profiles.append({
                "name": name, "pages": profile_pages[name],
                "eligible": eligible, "calls": 0, "useful": 0,
            })
        thresholds.append({
            "threshold": threshold,
            "negative_eligible": sum(item["eligible"] for item in profiles),
            "negative_calls": 0,
            "negative_useful": 0,
            "structured_eligible": 128,
            "structured_calls": 96,
            "structured_useful": 80,
            "routed_baseline_blocks": 200,
            "routed_candidate_blocks": 165,
            "routed_blocks_saved": 35,
            "routed_baseline_extents": 100,
            "routed_candidate_extents": 85,
            "routed_extents_saved": 15,
            "routed_cpu_ns_total": 2500000,
            "routed_cpu_ns_per_page": 4340,
            "ns_per_saved_block": 71428,
            "negative_profiles": profiles,
        })
    transforms = []
    for index, name in enumerate(runner.PREDICTOR_TRANSFORM_NAMES):
        transforms.append({
            "name": name,
            "adopted": 80 - index,
            "raw_rescued": 20 - index,
            "cliff_2024": 30 - index,
            "saved_payload_bytes": 100000 - index * 1000,
            "baseline_blocks": 200,
            "candidate_blocks": 160 + index,
            "planner_blocks_saved": 40 - index,
            "baseline_extents": 100,
            "candidate_extents": 80 + index,
            "planner_extents_saved": 20 - index,
            "transform_backend": "avx2",
            "inverse_backend": "sse2",
            "transform_ns_per_page": 1000 + index * 100,
            "inverse_ns_per_page": 900 + index * 100,
            "scalar_transform_ns_per_page": 1400 + index * 100,
            "scalar_inverse_ns_per_page": 1300 + index * 100,
            "second_lz4_ns_per_page": 5000 + index * 100,
        })
    return {
        "scope": "OFFLINE_NATIVE_ONLY_NOT_KERNEL_POLICY",
        "negative_pages": sum(profile_pages.values()),
        "structured_pages": 320,
        "classifier": {
            "candidate": "delta64",
            "backend": "scalar",
            "sample_pairs": 32,
            "stage1_pairs": 8,
            "stage1_min_score": 2,
            "eligible_pages": 320,
            "early_abort_pages": 120,
            "benchmark_repeats": 256,
            "benchmark_calls": 81920,
            "ns_per_page": 55,
            "scalar_ns_per_page": 70,
        },
        "backend_benchmarks": [
            {"name": "scalar", "transform_ns_per_page": 700,
             "inverse_ns_per_page": 650},
            {"name": "sse2", "transform_ns_per_page": 430,
             "inverse_ns_per_page": 550},
            {"name": "avx2", "transform_ns_per_page": 300,
             "inverse_ns_per_page": 600},
        ],
        "io_model_block_ns": {"sd_emulated": 390625, "ssd_emulated": 48828},
        "thresholds": thresholds,
        "transforms": transforms,
    }


def gc_scan_scale_evidence():
    return {
        "scope": "OFFLINE_NATIVE_GC_SCALE_ONLY",
        "rows": [
            {
                "logical_pages": 262144, "segments": 1024,
                "legacy_score_scan_ns": 2000000,
                "incremental_select_ns": 20000,
                "relocation_scan_ns": 800000,
                "relocation_list_ns": 4000,
                "legacy_dead_probe_ns": 700000,
                "mapped_dead_probe_ns": 12000,
                "victim_records": 256,
            },
            {
                "logical_pages": 1048576, "segments": 4096,
                "legacy_score_scan_ns": 8000000,
                "incremental_select_ns": 80000,
                "relocation_scan_ns": 3200000,
                "relocation_list_ns": 4500,
                "legacy_dead_probe_ns": 2800000,
                "mapped_dead_probe_ns": 15000,
                "victim_records": 256,
            },
        ],
    }


def extent_geometry_evidence():
    return {
        "scope": "OFFLINE_NATIVE_GEOMETRY_ONLY_NOT_FORMAT_POLICY",
        "logical_pages": 1024,
        "normal_windows": 64,
        "rows": [
            {"name": "aligned_1_2_4", "physical_blocks": 320,
             "waste_blocks": 24, "write_runs": 80,
             "cold_read_blocks_x1000": 1800, "seq_4m_requests": 1500},
            {"name": "packed_1_2_4", "physical_blocks": 320,
             "waste_blocks": 4, "write_runs": 60,
             "cold_read_blocks_x1000": 1800, "seq_4m_requests": 1500},
            {"name": "packed_1_2_3_4", "physical_blocks": 300,
             "waste_blocks": 3, "write_runs": 55,
             "cold_read_blocks_x1000": 1750, "seq_4m_requests": 1450},
            {"name": "packed_1_2_4_8", "physical_blocks": 292,
             "waste_blocks": 2, "write_runs": 48,
             "cold_read_blocks_x1000": 1900, "seq_4m_requests": 1300},
            {"name": "packed_1_2_4_8_16", "physical_blocks": 288,
             "waste_blocks": 1, "write_runs": 44,
             "cold_read_blocks_x1000": 2150, "seq_4m_requests": 1200},
        ],
    }


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
        "burst_shrink_inflight_zero_skips": 2 if mode else 0,
        "burst_shrink_after_inflight_zero": 0,
        "burst_shrink_after_read_bypass": 0,
        "burst_shrink_other": 2 if mode else 1,
        "burst_shrink_target_le8": 1 if mode else 0,
        "burst_shrink_target_9_32": 1,
        "burst_shrink_target_gt32": 0,
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
                    "parallel_read_coalesced_pairs": 20,
                    "parallel_read_coalesced_reqs_saved": 20,
                    "parallel_read_coalesced_blocks": 80,
                    "parallel_read_coalesce_extra_blocks": 0,
                    "parallel_read_coalesce_skip_cached": 1,
                    "parallel_read_coalesce_skip_noncontig_slot": 2,
                    "parallel_read_coalesce_skip_gap": 1,
                    "parallel_read_coalesce_skip_other": 0,
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



def parallel_arm(enabled, regime="ssd_emulated"):
    record = arm("swapz", mode=0, regime=regime)
    for phase in record["packed_read"]["passes"].values():
        kernel = phase["kernel_read_path"]
        if regime == "sd_emulated":
            kernel["read_worker_cpu_ns"] = 0
        if not enabled:
            for field in (
                    "parallel_read_pairs", "parallel_read_same_extent_pairs",
                    "parallel_read_distinct_extent_pairs",
                    "parallel_read_adjacent_extent_pairs",
                    "parallel_read_adjacent_extent_blocks"):
                kernel[field] = 0
        else:
            kernel["parallel_read_pairs"] = 128
            kernel["parallel_read_same_extent_pairs"] = 64
        for field in (
                "parallel_read_coalesced_pairs",
                "parallel_read_coalesced_reqs_saved",
                "parallel_read_coalesced_blocks",
                "parallel_read_coalesce_extra_blocks",
                "parallel_read_coalesce_skip_cached",
                "parallel_read_coalesce_skip_noncontig_slot",
                "parallel_read_coalesce_skip_gap",
                "parallel_read_coalesce_skip_other"):
            kernel[field] = 0
    return record


def coalesce_arm(enabled, regime="ssd_emulated"):
    record = parallel_arm(enabled, regime=regime)
    for mode, phase in record["packed_read"]["passes"].items():
        kernel = phase["kernel_read_path"]
        if enabled:
            kernel["parallel_read_coalesced_pairs"] = (
                20 if mode == "sequential" else 2)
            kernel["parallel_read_coalesced_reqs_saved"] = (
                kernel["parallel_read_coalesced_pairs"])
            kernel["parallel_read_coalesced_blocks"] = (
                80 if mode == "sequential" else 8)
            if mode == "sequential":
                kernel["parallel_read_coalesce_skip_cached"] = 1
                kernel["parallel_read_coalesce_skip_noncontig_slot"] = 2
                kernel["parallel_read_coalesce_skip_gap"] = 1
            else:
                kernel["parallel_read_coalesce_skip_cached"] = 8
                kernel["parallel_read_coalesce_skip_noncontig_slot"] = 10
                kernel["parallel_read_coalesce_skip_gap"] = 4
            phase["lower_io"]["lower_read_requests"] -= (
                kernel["parallel_read_coalesced_reqs_saved"])
            phase["read_p99_ms"] *= .95
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
        "replay_mode": "persistent-write",
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
           "PASS_LOADED_GC_PRESSURE=rounds:5 write_wall_ns:1000000000 baseline_p99_ns:1000000 pressure_p99_ns:5000000 gc_wall_ns:200000000 gc_fraction_ppm:200000 choose_wall_ns:20000000 choose_calls:12 choose_map_entries:0 choose_segment_entries:768 relocation_map_entries:12 no_headroom_skips:3 alignment_hole_fg:4 alignment_hole_gc:1 tail_waste_fg:4 tail_waste_gc:1 run_splits_by_hole:0 alloc_probe_segments:1024 alloc_probe_full_scans:16 alloc_probe_wall_ns:50000 trim_skipped:6 segment_program_min:0 segment_program_sum:80 segment_program_max:4 segment_program_segments:32",
           "PASS_LOADED_DISCARD_TRIM=pages:256 immediate_discards:1 immediate_sectors:2048 reuse_skips:2 verified_pages:4096",
           "PASS_LOADED_PACKED_PLACEMENT=enabled:1 verified_pages:128 holes:0 run_splits:0 failed:0",
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
    for index, enabled in enumerate(runner.CONFIRMATION_SEQUENCE):
        out.append(f"START_READ_COALESCE_AB={enabled}")
        out.append("REPLAY_ORDER=swapz-first" if index % 2 else
                   "REPLAY_ORDER=off-first")
        out.append(
            "PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} "
            "COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} "
            "QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} "
            "HW_QUEUE_DEPTH={hw_queue_depth}".format(**spec))
        raw = arm("off", mode=0, regime="ssd_emulated")
        swapz = coalesce_arm(enabled)
        for record in ((swapz, raw) if index % 2 else (raw, swapz)):
            out.append(json.dumps(record))
        out.append(f"PASS_READ_COALESCE_AB={enabled}")
    spec = runner.MODEL_SPECS["sd_emulated"]
    for index, enabled in enumerate(runner.CONFIRMATION_SEQUENCE):
        out.append(f"START_SD_READ_COALESCE_AB={enabled}")
        out.append("REPLAY_ORDER=swapz-first" if index % 2 else
                   "REPLAY_ORDER=off-first")
        out.append(
            "PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} "
            "COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} "
            "QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} "
            "HW_QUEUE_DEPTH={hw_queue_depth}".format(**spec))
        raw = arm("off", mode=0, regime="sd_emulated")
        swapz = coalesce_arm(enabled, regime="sd_emulated")
        for record in ((swapz, raw) if index % 2 else (raw, swapz)):
            out.append(json.dumps(record))
        out.append(f"PASS_SD_READ_COALESCE_AB={enabled}")
    for regime in runner.MODEL_ORDER:
        spec = runner.MODEL_SPECS[regime]
        out.append(f"START_WRITE_SATURATION_REGIME={regime}")
        index = 0
        for qd in (1, 4, 8, 32):
            modes = (runner.CONFIRMATION_SEQUENCE
                     if regime == "ssd_emulated" and qd in (4, 8, 32)
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
    def test_host_cpu_record_keeps_aggregate_counters_and_missing_status(self):
        raw = {"status": "AVAILABLE", "wall_ns": 1000000000,
               "online_cpus": 4, "affinity_cpus": 2, "tick_hz": 100,
               "busy_fraction": .7, "steal_fraction": 0.,
               "pressure_some_fraction": .25, "processes": "SECRET"}
        observed = runner.host_cpu_record({"host_cpu": raw})
        self.assertNotIn("SECRET", json.dumps(observed))
        self.assertEqual(observed["busy_fraction"], .7)
        self.assertEqual(runner.host_cpu_record({}), {"status": "NOT_COLLECTED"})
        self.assertEqual(runner.host_cpu_record({"host_cpu": {
            **raw, "busy_fraction": float("nan")}}), {"status": "INVALID"})
        partial = runner.host_cpu_record({"host_cpu": {
            **raw, "status": "PARTIAL", "pressure_some_fraction": None}})
        self.assertEqual(partial["status"], "PARTIAL")
        self.assertIsNone(partial["pressure_some_fraction"])

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
        self.assertNotIn("START_PARALLEL_READ_AB=", loaded)
        self.assertNotIn("START_SD_READ_GROUPING_AB=", loaded)
        self.assertIn("--parallel-reads", loaded)
        self.assertIn("--write-only-qd", loaded)
        self.assertNotIn("swapon ", loaded)
        self.assertNotIn("swapoff ", loaded)
        self.assertNotIn("/dev/sdb", loaded)

    def test_predictor_evidence_is_sanitized(self):
        raw = predictor_evidence()
        parsed = runner.parse_predictor_evidence(
            "SWAPZ_PREDICTOR_EVIDENCE=" + json.dumps(raw) + "\n")
        self.assertEqual(parsed, raw)
        broken = json.loads(json.dumps(raw))
        broken["thresholds"][2]["negative_calls"] = 65
        self.assertIsNone(runner.parse_predictor_evidence(
            "SWAPZ_PREDICTOR_EVIDENCE=" + json.dumps(broken) + "\n"))
        broken = predictor_evidence()
        broken["thresholds"][2]["routed_blocks_saved"] += 1
        self.assertIsNone(runner.parse_predictor_evidence(
            "SWAPZ_PREDICTOR_EVIDENCE=" + json.dumps(broken) + "\n"))
        duplicate = (
            "SWAPZ_PREDICTOR_EVIDENCE=" + json.dumps(raw) + "\n" +
            "SWAPZ_PREDICTOR_EVIDENCE=" + json.dumps(raw) + "\n")
        self.assertIsNone(runner.parse_predictor_evidence(duplicate))

    def test_gc_scan_scale_evidence_is_sanitized(self):
        raw = gc_scan_scale_evidence()
        parsed = runner.parse_gc_scan_scale_evidence(
            "SWAPZ_GC_SCAN_SCALE_EVIDENCE=" + json.dumps(raw) + "\n")
        self.assertEqual(parsed["rows"][1]["logical_pages"], 1048576)
        self.assertEqual(parsed["rows"][1]["relocation_list_ns"], 4500)
        broken = json.loads(json.dumps(raw))
        broken["rows"][1]["victim_records"] = 255
        self.assertIsNone(runner.parse_gc_scan_scale_evidence(
            "SWAPZ_GC_SCAN_SCALE_EVIDENCE=" + json.dumps(broken) + "\n"))

    def test_extent_geometry_evidence_is_sanitized(self):
        raw = extent_geometry_evidence()
        parsed = runner.parse_extent_geometry_evidence(
            "SWAPZ_EXTENT_GEOMETRY_EVIDENCE=" + json.dumps(raw) + "\n")
        self.assertEqual(parsed["rows"][1]["name"], "packed_1_2_4")
        self.assertEqual(parsed["rows"][4]["seq_4m_requests"], 1200)
        broken = json.loads(json.dumps(raw))
        broken["rows"][2]["name"] = "packed_1_4"
        self.assertIsNone(runner.parse_extent_geometry_evidence(
            "SWAPZ_EXTENT_GEOMETRY_EVIDENCE=" + json.dumps(broken) + "\n"))

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
        self.assertEqual(loaded["gc_pressure_rounds"], 5)
        self.assertEqual(loaded["gc_fraction_ppm"], 200000)
        self.assertEqual(loaded["gc_baseline_p99_ns"], 1000000)
        self.assertEqual(loaded["gc_pressure_p99_ns"], 5000000)
        self.assertEqual(loaded["gc_choose_map_entries"], 0)
        self.assertEqual(loaded["gc_relocation_map_entries"], 12)
        self.assertEqual(loaded["gc_no_headroom_skips"], 3)
        self.assertEqual(loaded["alignment_hole_blocks_foreground"], 4)
        self.assertEqual(loaded["segment_tail_waste_blocks_foreground"], 4)
        self.assertEqual(loaded["segment_tail_waste_blocks_gc"], 1)
        self.assertEqual(loaded["run_splits_by_hole"], 0)
        self.assertEqual(loaded["segment_discards_skipped_already_trimmed"], 6)
        self.assertEqual(loaded["segment_program_max"], 4)
        self.assertEqual(loaded["discard_trim_immediate"], 1)
        self.assertEqual(loaded["discard_trim_reuse_skips"], 2)
        self.assertEqual(loaded["packed_placement_enabled"], 1)
        self.assertEqual(loaded["packed_placement_holes"], 0)
        self.assertEqual(loaded["packed_placement_run_splits"], 0)
        self.assertEqual(loaded["alignment_hole_blocks_foreground"],
                         loaded["segment_tail_waste_blocks_foreground"])
        self.assertEqual(loaded["alignment_hole_blocks_gc"],
                         loaded["segment_tail_waste_blocks_gc"])
        self.assertEqual(loaded["run_splits_by_hole"], 0)
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

        missing_pressure = synthetic_log().replace(
            "PASS_LOADED_GC_PRESSURE=rounds:5 write_wall_ns:1000000000 "
            "baseline_p99_ns:1000000 pressure_p99_ns:5000000 "
            "gc_wall_ns:200000000 gc_fraction_ppm:200000 "
            "choose_wall_ns:20000000 choose_calls:12 "
            "choose_map_entries:0 choose_segment_entries:768 "
            "relocation_map_entries:12 no_headroom_skips:3 "
            "alignment_hole_fg:4 alignment_hole_gc:1 tail_waste_fg:4 tail_waste_gc:1 run_splits_by_hole:0 "
            "alloc_probe_segments:1024 alloc_probe_full_scans:16 "
            "alloc_probe_wall_ns:50000 trim_skipped:6 segment_program_min:0 "
            "segment_program_sum:80 segment_program_max:4 "
            "segment_program_segments:32\n", "")
        self.assertEqual(
            runner.parse_loaded_correctness(missing_pressure)["overall"],
            "INCOMPLETE")

        missing_trim = synthetic_log().replace(
            "PASS_LOADED_DISCARD_TRIM=pages:256 immediate_discards:1 "
            "immediate_sectors:2048 reuse_skips:2 verified_pages:4096\n", "")
        self.assertEqual(
            runner.parse_loaded_correctness(missing_trim)["overall"],
            "INCOMPLETE")

        bad_packed_hole = synthetic_log().replace(
            "PASS_LOADED_PACKED_PLACEMENT=enabled:1 verified_pages:128 "
            "holes:0 run_splits:0 failed:0",
            "PASS_LOADED_PACKED_PLACEMENT=enabled:1 verified_pages:128 "
            "holes:1 run_splits:0 failed:0")
        self.assertEqual(
            runner.parse_loaded_correctness(bad_packed_hole)["overall"],
            "INCOMPLETE")

        bad_packed_split = synthetic_log().replace(
            "PASS_LOADED_PACKED_PLACEMENT=enabled:1 verified_pages:128 "
            "holes:0 run_splits:0 failed:0",
            "PASS_LOADED_PACKED_PLACEMENT=enabled:1 verified_pages:128 "
            "holes:0 run_splits:1 failed:0")
        self.assertEqual(
            runner.parse_loaded_correctness(bad_packed_split)["overall"],
            "INCOMPLETE")

        bad_gc_internal_hole = synthetic_log().replace(
            "alignment_hole_fg:4 alignment_hole_gc:1 "
            "tail_waste_fg:4 tail_waste_gc:1 run_splits_by_hole:0",
            "alignment_hole_fg:5 alignment_hole_gc:1 "
            "tail_waste_fg:4 tail_waste_gc:1 run_splits_by_hole:0", 1)
        self.assertEqual(
            runner.parse_loaded_correctness(bad_gc_internal_hole)["overall"],
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
        coalesce = runner.parse_read_coalesce_ab(synthetic_log())
        self.assertEqual([row["read_coalesce"] for row in coalesce],
                         list(runner.CONFIRMATION_SEQUENCE))
        coalesce_diag = runner.read_coalesce_ab_verdict(coalesce)
        self.assertEqual(coalesce_diag["overall"],
                         "PASS_READ_COALESCE_AB_CONFIRMATION")
        self.assertEqual(coalesce_diag["matched_pairs"], 5)
        self.assertEqual(
            coalesce_diag["modes"]["0"]["sequential"][
                "parallel_read_coalesced_pairs"], 0)
        self.assertGreater(
            coalesce_diag["modes"]["1"]["sequential"][
                "parallel_read_coalesced_reqs_saved"], 0)
        self.assertEqual(
            coalesce_diag["modes"]["1"]["sequential"][
                "parallel_read_coalesce_skip_other"], 0)

        sd_coalesce = runner.parse_sd_read_coalesce_ab(synthetic_log())
        self.assertEqual([row["read_coalesce"] for row in sd_coalesce],
                         list(runner.CONFIRMATION_SEQUENCE))
        sd_coalesce_diag = runner.sd_read_coalesce_ab_verdict(sd_coalesce)
        self.assertEqual(sd_coalesce_diag["overall"],
                         "PASS_SD_READ_COALESCE_AB_CONFIRMATION")
        self.assertEqual(sd_coalesce_diag["matched_pairs"], 5)
        self.assertGreater(
            sd_coalesce_diag["modes"]["1"]["sequential"][
                "parallel_read_coalesced_reqs_saved"], 0)
        self.assertEqual(
            sd_coalesce_diag["modes"]["1"]["sequential"][
                "read_worker_cpu_ns"], 0)
        self.assertEqual(
            sd_coalesce_diag["modes"]["1"]["sequential"][
                "parallel_read_coalesce_skip_other"], 0)

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

    def test_write_saturation_evidence_repeats_fast_qd4_qd8_and_qd32(self):
        sessions = runner.parse_write_saturation(synthetic_log())
        self.assertEqual(len(sessions), 40)
        verdict = runner.write_saturation_verdict(sessions)
        self.assertEqual(verdict["overall"], "PASS_WRITE_SATURATION_EVIDENCE")
        self.assertAlmostEqual(
            verdict["model_limits"]["sd_emulated"]["effective_4k_model_ceiling_mbps"],
            4.096, places=3)
        self.assertAlmostEqual(
            verdict["model_limits"]["ssd_emulated"]["cap_decimal_mbps"],
            80 * (1 << 20) / 1_000_000.0, places=3)
        self.assertEqual(verdict["fast_qd8_matched_pairs"], 5)
        self.assertEqual(verdict["fast_qd32_matched_pairs"], 5)
        self.assertEqual(
            verdict["fast_qd8_paired"]["throughput_change_fraction"]["n"], 5)
        self.assertEqual(
            verdict["fast_qd32_paired"]["throughput_change_fraction"]["n"], 5)
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
        fast_qd32 = [p for p in verdict["regimes"]["ssd_emulated"]
                     if p["qd"] == 32]
        self.assertEqual([p["observations"] for p in fast_qd4], [5, 5])
        self.assertEqual([p["observations"] for p in fast_qd8], [5, 5])
        self.assertEqual([p["observations"] for p in fast_qd32], [5, 5])
        broken = runner.parse_write_saturation(synthetic_log())
        broken[0]["arms"]["off"]["logical_read_bytes"] = 4096
        self.assertEqual(runner.write_saturation_verdict(broken)["overall"],
                         "INCOMPLETE")
        broken = runner.parse_write_saturation(synthetic_log())
        broken[0]["arms"]["off"]["replay_mode"] = "qd-waves"
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
        report = {"evidence": {"predictor": predictor_evidence(),
                                "gc_scan_scale": gc_scan_scale_evidence(),
                                "extent_geometry": extent_geometry_evidence()},
                  "benchmarks": {
            "verdicts": verdicts,
            "read_coalesce_ab": runner.read_coalesce_ab_verdict(
                runner.parse_read_coalesce_ab(synthetic_log())),
            "sd_read_coalesce_ab": runner.sd_read_coalesce_ab_verdict(
                runner.parse_sd_read_coalesce_ab(synthetic_log())),
            "write_saturation": saturation,
            "loaded_correctness": runner.parse_loaded_correctness(synthetic_log()),
        }}
        with contextlib.redirect_stdout(io.StringIO()) as output:
            runner.print_bench(report)
        rendered = output.getvalue()
        self.assertIn("Predictive-compression screening", rendered)
        self.assertIn("Garbage-collection map-scan scaling", rendered)
        self.assertIn("Simulated extent geometry", rendered)
        self.assertNotIn("ID69 PACKED PLACEMENT A/B", rendered)
        self.assertIn("placement waste", rendered)
        self.assertIn("packed smoke", rendered)
        self.assertIn("packed_1_2_4_8_16", rendered)
        self.assertIn("upper DISCARD TRIM", rendered)
        self.assertIn("packed smoke", rendered)
        self.assertIn("1048576", rendered)
        self.assertIn("Sampled delta64 classifier", rendered)
        self.assertIn("Negative classifier profile breakdown", rendered)
        self.assertIn("delta64", rendered)
        self.assertIn("classifier=scalar", rendered)
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
        self.assertIn("Mixed burst-target shrink attribution", rendered)
        self.assertIn("skip-I0", rendered)
        self.assertIn("after-I0", rendered)
        self.assertIn("segment TRIM", rendered)
        self.assertIn("Adjacent-range READ coalescing", rendered)
        self.assertNotIn("ID39 SAME-CACHE PARALLEL READ", rendered)
        self.assertNotIn("SD ID60 SAME-EXTENT GROUPING", rendered)
        self.assertIn("Merged-range accounting", rendered)
        self.assertIn("Reasons adjacent READs were not merged", rendered)
        self.assertIn("noncontig", rendered)
        self.assertIn("Serial-depth adjacent-range READ coalescing", rendered)
        self.assertIn("Serial-depth merged-range attribution", rendered)
        self.assertIn("saved", rendered)
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
        self.assertIn("Routed delta64 CPU economics", rendered)
        self.assertIn("Delta64 selected backends", rendered)
        self.assertNotIn("dry-close followups", rendered)
        self.assertIn("direct LZ4 input", rendered)
        self.assertIn("Lifecycle", rendered)
        self.assertIn("retained WRITE/FLUSH failed closed", rendered)
        self.assertIn("WRITE-ONLY SUSTAINED-QD EVIDENCE", rendered)
        self.assertIn("Persistent lane workers", rendered)
        self.assertIn("Fast QD4 A/S paired 95% CI", rendered)
        self.assertIn("Fast QD8 A/S paired 95% CI", rendered)
        self.assertIn("Fast QD32 A/S paired 95% CI", rendered)
        self.assertIn("five pairs at fast QD4/8/32; QD1 is directional", rendered)
        self.assertIn("QD1 remains a directional control.", rendered)
        self.assertIn("DEVICE MODEL LIMITS", rendered)
        self.assertIn("4K latency MB/s", rendered)
        self.assertIn("Async preparation", rendered)
        self.assertIn("Async windows; close=P/D/I", rendered)
        self.assertIn("Full telemetry", rendered)
        self.assertIn("test_results.json", rendered)
        self.assertIn("Async useful WRITE throughput is", rendered)
        self.assertIn("95% intervals", rendered)
        self.assertIn("overlap zero for", rendered)
        self.assertIn("Merge-on means versus merge-off", rendered)
        self.assertIn("Read each criterion separately", rendered)
        self.assertNotRegex(rendered, r"(?m)^\s*(?:SD\s+)?ID\d+\b")
        self.assertNotIn("ID63 active", rendered)
        self.assertNotIn("All-window close reasons per-pair mean", rendered)
        self.assertNotIn("Timed 4MiB", rendered)
        self.assertNotIn("QD4 sync windows:", rendered)
        # Every stdout table must be directly copy/pasteable as Markdown:
        # unindented GFM pipe syntax, >=3 separator dashes per column, and a
        # literal horizontal rule immediately after the last row.
        lines = rendered.splitlines()
        table_starts = [
            index for index in range(len(lines) - 1)
            if lines[index].startswith("| ") and
            lines[index + 1].startswith("| ") and
            all(set(cell.strip()) <= {"-"} and len(cell.strip()) >= 3
                for cell in lines[index + 1].strip("|").split("|"))
        ]
        self.assertGreater(len(table_starts), 10)
        self.assertEqual(rendered.count("  Legend:"), len(table_starts))
        self.assertEqual(rendered.count("  Interpretation:"), len(table_starts))
        for start in table_starts:
            index = start + 2
            while index < len(lines) and lines[index].startswith("| "):
                index += 1
            self.assertLess(index, len(lines))
            self.assertEqual(lines[index], "---")
            index += 1
            self.assertLess(index, len(lines))
            self.assertTrue(lines[index].startswith("  Legend:"))
            index += 1
            while (index < len(lines) and lines[index].startswith("    ") and
                   not lines[index].startswith("  Interpretation:")):
                index += 1
            self.assertLess(index, len(lines))
            self.assertTrue(lines[index].startswith("  Interpretation:"))
        self.assertNotRegex(rendered, r"(?m)^  \|")
        self.assertLess(max(map(len, lines)), 96)

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
                runner.REPORT = runner.ROOT / "test_results.json"
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
                first = path.read_text(encoding="utf-8")
                self.assertNotIn("SECRET", first)
                report["overall"] = "FAIL"
                runner.write_report(report)
                second = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(second["overall"], "FAIL")
                self.assertEqual({item.name for item in runner.ROOT.iterdir()},
                                 {runner.GIT_RESULT})
                self.assertEqual(path.name, "test_results.json")
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

    def test_randomized_native_failure_reports_safe_source_and_line(self):
        phase, reason = runner.failure_context(
            "FAIL: randomized-authority.c:188 expression=result == 0\n",
            loaded=False, default_phase="Native and rootless contracts")
        self.assertEqual(phase, "Native and rootless contracts")
        self.assertEqual(
            reason,
            "FAIL: randomized-authority.c:188 expression=result == 0")

    def test_lower_write_aggregation_failure_reports_fixed_source_and_line(self):
        phase, reason = runner.failure_context(
            "FAIL: lower-write-aggregation.c:490 expression=maps[0].extent_blocks == 2\n",
            loaded=False, default_phase="Native and rootless contracts")
        self.assertEqual(phase, "Native and rootless contracts")
        self.assertEqual(
            reason,
            "FAIL: lower-write-aggregation.c:490 expression=maps[0].extent_blocks == 2")

    def test_exit_two_is_fail_before_loaded_stage_and_blocked_only_when_marked(self):
        with tempfile.TemporaryDirectory(prefix="report-", dir=ROOT / "build/tests") as name:
            original_root, original_report = runner.ROOT, runner.REPORT
            try:
                runner.ROOT = Path(name)
                runner.REPORT = runner.ROOT / "test_results.json"
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

    def test_read_coalesce_diagnostic_failure_reports_its_own_reason(self):
        broken = synthetic_log().replace("PASS_READ_COALESCE_AB=1\n", "", 1)
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
        self.assertEqual(stage["failed_phase"],
                         "adjacent READ coalescing A/B evidence")
        self.assertIn("confirmation", stage["diagnostic"])

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
            (checkout / runner.GIT_RESULT).write_text(
                '{"overall":"NOT_RUN"}\n', encoding="utf-8")
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
                        json.loads((checkout / runner.GIT_RESULT).read_text(
                            encoding="utf-8")),
                        original)

                    self.assertEqual(runner.git_sha(), source_sha)
                    updated = dict(original, overall="PASS")
                    runner.write_report(updated)
                    second = runner.publish(source_sha)
                    self.assertIn("SYNCED_GIT", second)
                    second_head = git("rev-parse", "HEAD",
                                      cwd=checkout).stdout.strip()
                    self.assertNotEqual(first_head, second_head)
                    self.assertEqual(
                        git("--git-dir", str(origin), "rev-parse",
                            "refs/heads/main", cwd=sandbox).stdout.strip(),
                        second_head)
                    self.assertEqual(
                        json.loads((checkout / runner.GIT_RESULT).read_text(
                            encoding="utf-8")),
                        updated)
                    self.assertEqual(len(list(checkout.glob("*.json"))), 1)

                    (checkout / "source.c").write_text("unsaved owner change\n")
                    blocked = dict(updated, overall="FAIL")
                    runner.write_report(blocked)
                    before = git("--git-dir", str(origin), "rev-parse",
                                 "refs/heads/main", cwd=sandbox).stdout.strip()
                    self.assertIn("not clean", runner.publish(source_sha))
                    self.assertEqual(
                        git("--git-dir", str(origin), "rev-parse",
                            "refs/heads/main", cwd=sandbox).stdout.strip(),
                        before)
            finally:
                runner.ROOT, runner.REPORT = old_root, old_report


    def test_git_sha_walks_report_only_chains_beyond_32_commits(self):
        """Repeated qualifications never turn a report commit into source."""
        import subprocess

        def git(*args, cwd, check=True):
            return subprocess.run(["git", *args], cwd=cwd, check=check,
                                  capture_output=True, text=True, timeout=12)

        with tempfile.TemporaryDirectory(
                prefix="report-chain-", dir=ROOT / "build/tests") as name:
            checkout = Path(name)
            git("init", cwd=checkout)
            git("checkout", "-b", "main", cwd=checkout)
            git("config", "user.name", "test-report CI", cwd=checkout)
            git("config", "user.email", "test@example.invalid", cwd=checkout)
            (checkout / "source.c").write_text("source\n")
            (checkout / runner.GIT_RESULT).write_text(
                '{"overall":"NOT_RUN"}\n', encoding="utf-8")
            git("add", "source.c", runner.GIT_RESULT, cwd=checkout)
            git("commit", "-m", "Tested source", cwd=checkout)
            source_sha = git("rev-parse", "HEAD", cwd=checkout).stdout.strip()

            for index in range(40):
                (checkout / runner.GIT_RESULT).write_text(
                    json.dumps({"run": index}), encoding="utf-8")
                git("add", runner.GIT_RESULT, cwd=checkout)
                git("commit", "-m",
                    f"test: latest run for {source_sha[:12]} [skip ci]",
                    cwd=checkout)

            old_root = runner.ROOT
            runner.ROOT = checkout
            try:
                self.assertEqual(runner.git_sha(), source_sha)
            finally:
                runner.ROOT = old_root

    def test_git_sync_retries_after_concurrent_main_advance(self):
        """A completed failure report survives a normal source commit race."""
        import subprocess
        from unittest import mock

        def git(*args, cwd, check=True):
            return subprocess.run(["git", *args], cwd=cwd, check=check,
                                  capture_output=True, text=True, timeout=12)

        with tempfile.TemporaryDirectory(
                prefix="report-race-", dir=ROOT / "build/tests") as name:
            sandbox = Path(name)
            checkout, origin, peer = (
                sandbox / "checkout", sandbox / "origin.git", sandbox / "peer")
            checkout.mkdir()
            git("init", "--bare", str(origin), cwd=sandbox)
            git("init", cwd=checkout)
            git("checkout", "-b", "main", cwd=checkout)
            git("config", "user.name", "test-report CI", cwd=checkout)
            git("config", "user.email", "test@example.invalid", cwd=checkout)
            (checkout / "source.c").write_text("old source\n")
            (checkout / runner.GIT_RESULT).write_text(
                '{"overall":"NOT_RUN"}\n', encoding="utf-8")
            git("add", "source.c", runner.GIT_RESULT, cwd=checkout)
            git("commit", "-m", "Tested source", cwd=checkout)
            source_sha = git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
            git("remote", "add", "origin", str(origin), cwd=checkout)
            git("push", "origin", "main", cwd=checkout)

            git("clone", "-b", "main", str(origin), str(peer), cwd=sandbox)
            git("config", "user.name", "concurrent writer", cwd=peer)
            git("config", "user.email", "writer@example.invalid", cwd=peer)
            (peer / "source.c").write_text("newer source\n")
            git("add", "source.c", cwd=peer)
            git("commit", "-m", "Concurrent source", cwd=peer)
            concurrent_sha = git("rev-parse", "HEAD", cwd=peer).stdout.strip()
            git("push", "origin", "main", cwd=peer)

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
                    failed = {
                        "schema": "swapz-test-results-v1",
                        "source_sha": source_sha,
                        "tested_commit_sha": source_sha,
                        "overall": "FAIL",
                    }
                    runner.write_report(failed)
                    notice = runner.publish(source_sha)
                    self.assertIn("SYNCED_GIT_AFTER_ADVANCE", notice)

                    final_head = git("rev-parse", "HEAD",
                                     cwd=checkout).stdout.strip()
                    remote_head = git("--git-dir", str(origin), "rev-parse",
                                      "refs/heads/main",
                                      cwd=sandbox).stdout.strip()
                    self.assertEqual(final_head, remote_head)
                    self.assertEqual(
                        git("rev-parse", "HEAD^",
                            cwd=checkout).stdout.strip(), concurrent_sha)
                    self.assertEqual((checkout / "source.c").read_text(),
                                     "newer source\n")
                    self.assertEqual(
                        json.loads((checkout / runner.GIT_RESULT).read_text(
                            encoding="utf-8")),
                        failed)
                    self.assertEqual(git("status", "--porcelain",
                                         cwd=checkout).stdout, "")
            finally:
                runner.ROOT, runner.REPORT = old_root, old_report

    def test_git_sync_retries_transient_push_and_fetch_failure(self):
        """Retry transient publication failures even when main did not move."""
        import subprocess
        from unittest import mock

        def git(*args, cwd, check=True):
            return subprocess.run(["git", *args], cwd=cwd, check=check,
                                  capture_output=True, text=True, timeout=12)

        with tempfile.TemporaryDirectory(
                prefix="report-retry-", dir=ROOT / "build/tests") as name:
            sandbox = Path(name)
            checkout, origin = sandbox / "checkout", sandbox / "origin.git"
            checkout.mkdir()
            git("init", "--bare", str(origin), cwd=sandbox)
            git("init", cwd=checkout)
            git("checkout", "-b", "main", cwd=checkout)
            git("config", "user.name", "test-report CI", cwd=checkout)
            git("config", "user.email", "test@example.invalid", cwd=checkout)
            (checkout / "source.c").write_text("source\n")
            (checkout / runner.GIT_RESULT).write_text(
                '{"overall":"NOT_RUN"}\n', encoding="utf-8")
            git("add", "source.c", runner.GIT_RESULT, cwd=checkout)
            git("commit", "-m", "Tested source", cwd=checkout)
            source_sha = git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
            git("remote", "add", "origin", str(origin), cwd=checkout)
            git("push", "origin", "main", cwd=checkout)

            old_root, old_report, old_git_result = (
                runner.ROOT, runner.REPORT, runner.git_result)
            runner.ROOT = checkout
            runner.REPORT = checkout / runner.GIT_RESULT
            failures = {"push": 1, "fetch": 1}

            def intercept(command, *, data=None, timeout=15, env=None):
                if command == ["remote", "get-url", "--push", "origin"]:
                    return subprocess.CompletedProcess(
                        command, 0,
                        stdout=b"git@github.com:k1moradi/swapz.git",
                        stderr=b"")
                if command[:2] == ["push", "origin"] and failures["push"]:
                    failures["push"] -= 1
                    return subprocess.CompletedProcess(
                        command, 1, stdout=b"", stderr=b"transient push")
                if command[:3] == ["fetch", "--no-tags", "origin"] and \
                        failures["fetch"]:
                    failures["fetch"] -= 1
                    return subprocess.CompletedProcess(
                        command, 1, stdout=b"", stderr=b"transient fetch")
                return old_git_result(command, data=data, timeout=timeout,
                                      env=env)

            try:
                result = {
                    "schema": "swapz-test-results-v1",
                    "source_sha": source_sha,
                    "tested_commit_sha": source_sha,
                    "overall": "FAIL",
                }
                runner.write_report(result)
                with mock.patch.object(runner, "git_result",
                                       side_effect=intercept), \
                     mock.patch.object(runner.time, "sleep") as sleep:
                    notice = runner.publish(source_sha)
                self.assertIn("SYNCED_GIT", notice)
                self.assertEqual(failures, {"push": 0, "fetch": 0})
                self.assertGreaterEqual(sleep.call_count, 2)
                self.assertEqual(runner.git_sha(), source_sha)
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

    def test_git_sync_rejects_invalid_json_before_git_access(self):
        from unittest import mock

        source_sha = "a" * 40
        invalid_reports = (
            (b"{broken", "JSON report is unreadable"),
            (b"\xff", "JSON report is unreadable"),
            (b"[]", "does not match tested Git commit"),
            (b"null", "does not match tested Git commit"),
            (b'{"source_sha":"wrong"}', "does not match tested Git commit"),
        )
        with tempfile.TemporaryDirectory(
                prefix="publish-json-", dir=ROOT / "build/tests") as name:
            previous_root, previous_report = runner.ROOT, runner.REPORT
            try:
                runner.ROOT = Path(name)
                runner.REPORT = runner.ROOT / runner.GIT_RESULT
                with mock.patch.object(runner, "git_result") as git:
                    for payload, reason in invalid_reports:
                        with self.subTest(payload=payload):
                            runner.REPORT.write_bytes(payload)
                            self.assertIn(reason, runner.publish(source_sha))
                    git.assert_not_called()
            finally:
                runner.ROOT, runner.REPORT = previous_root, previous_report


if __name__ == "__main__":
    (ROOT / "build/tests").mkdir(parents=True, exist_ok=True)
    unittest.main()
