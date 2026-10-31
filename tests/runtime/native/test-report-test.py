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


class FakeStreamingProcess:
    """Minimal Popen-compatible process for streamed loaded-stage tests."""

    def __init__(self, output: str, returncode: int = 0):
        self.stdout = io.StringIO(output)
        self.returncode = returncode

    def wait(self):
        return self.returncode


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
            "structured_eligible": 77,
            "structured_calls": 70,
            "structured_useful": 60,
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
            "eligible_pages": 269,
            "early_abort_pages": 120,
            "benchmark_repeats": 256,
            "benchmark_calls": 68864,
            "ns_per_page": 55,
            "scalar_ns_per_page": 70,
        },
        "lz4_acceleration_sweep": [
            {
                "acceleration": acceleration,
                "wall_ns_per_page": 1000 // acceleration,
                "accepted_payload_bytes": 10000 + acceleration,
                "raw_pages": 12,
                "planner_blocks": 20,
                "planner_extents": 16,
            }
            for acceleration in runner.LZ4_ACCELERATIONS
        ],
        "sampling_controls": [
            {"name": "repeated_512b_headers", "score": 32,
             "minimum_score": 24},
            {"name": "lane1_only_signal", "score": 32,
             "minimum_score": 16},
        ],
        "backend_benchmarks": [
            {"name": "scalar", "transform_ns_per_page": 700,
             "inverse_ns_per_page": 650},
            {"name": "sse2", "transform_ns_per_page": 430,
             "inverse_ns_per_page": 550},
            {"name": "avx2", "transform_ns_per_page": 300,
             "inverse_ns_per_page": 600},
        ],
        "sse2_forward_ab": {
            "scope": "SAME_HOST_NATIVE_BASELINE_VS_PROMOTED_PRODUCTION",
            "pages": 576,
            "repeats_per_arm": 64,
            "pairs": [
                {
                    "order": "unrolled_first" if index % 2 else "baseline_first",
                    "baseline_ns_per_page": 300 + index,
                    "unrolled_ns_per_page": 287 + index,
                }
                for index in range(5)
            ],
        },
        "io_model_block_ns": {"sd_emulated": 390625, "ssd_emulated": 48828},
        "thresholds": thresholds,
        "transforms": transforms,
        "production_route": {
            "scope": "OFFLINE_NATIVE_ONLY_NOT_KERNEL_POLICY",
            "general_threshold": 24,
            "packing_threshold": 16,
            "eligible_pages": 269,
            "packing_eligible_pages": 20,
            "classifier_passes": 100,
            "candidate_attempts": 100,
            "adopted_pages": 80,
            "raw_rescues": 20,
            "lz4_rescues": 60,
            "packing_adoptions": 10,
            "payload_bytes_saved": 10000,
            "baseline_blocks": 400,
            "candidate_blocks": 350,
            "blocks_saved": 50,
            "baseline_extents": 200,
            "candidate_extents": 180,
            "extents_saved": 20,
            "modeled_wall_ns_total": 2500000,
            "modeled_wall_ns_per_page": 4340,
            "ns_per_saved_block": 50000,
        },
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
        "lz4_acceleration": 1,
        "delta64_lz4_acceleration": runner.PRODUCTION_DELTA64_LZ4_ACCELERATION,
        "delta64_prepare_workers": 1,
        "write_pipeline_depth": 1,
        "pipeline_active_max": 1 if mode else 0,
        "k1_allow_after_read_bypass": 0,
        "read_coalesce_max_blocks": 8,
        "invalidate_cache_on_write_admit": 0,
        "delta64_rescue": 1,
        "delta64_eligible": 10,
        "delta64_classifier_pass": 5,
        "delta64_attempts": 5,
        "delta64_adopted": 3,
        "delta64_raw_rescues": 1,
        "delta64_lz4_rescues": 2,
        "delta64_pack_eligible": 4,
        "delta64_pack_attempts": 1,
        "delta64_pack_cliff_crossings": 1,
        "delta64_pack_adopted": 1,
        "delta64_score_0_7": 2,
        "delta64_score_8_15": 2,
        "delta64_score_16_23": 2,
        "delta64_score_ge24": 4,
        "delta64_raw_payload_bytes_saved": 1000,
        "delta64_lz4_payload_bytes_saved": 200,
        "delta64_payload_bytes_saved": 1200,
        "delta64_wall_ns": 50000,
        "lz4_wall_ns": 20000000,
        "ordered_lz4_wall_ns": 15000000,
        "prep_lz4_wall_ns": 5000000,
        "write_copy_wall_ns": 3000000,
        "write_copy_bytes": 6000000,
        "ordered_write_copy_wall_ns": 2000000,
        "prep_write_copy_wall_ns": 1000000,
        "direct_lz4_input_pages": 3000,
        "mapped_snapshot_input_pages": 1000,
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
        "prep_lower_read_overlap_ns": 0,
        "prep_lower_write_samples": 5,
        "prep_lower_write_start_queued": 4,
        "prep_lower_write_start_nonempty": 3,
        "prep_lower_write_end_queued": 1,
        "prep_lower_write_end_nonempty": 1,
        "pipeline_async_runs": 4 if mode else 0,
        "pipeline_read_bypass_skips": 3 if mode else 0,
        "pipeline_active_wall_ns": 800000000 if mode else 0,
        "pipeline_post_lower_wall_ns": 8000000 if mode else 0,
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
        "prep_lower_read_overlap_starts": 0,
        "prep_wave_kicks": 5 if mode else 0,
        "prep_producer_head_claims": 2 if mode else 0,
        "prep_producer_tail_claims": 3 if mode else 0,
        "prep_ordered_inline": 4 if mode else 0,
        "prep_ordered_handoffs": 3 if mode else 0,
        "prep_ordered_waits": 1 if mode else 0,
    })
    return record


def standard_kernel_write(*, mode, target=8):
    """Standard loaded benchmark policy: LZ4 accel 1, production delta64 default."""
    record = timed_kernel_write(mode=mode, target=target)
    record["delta64_rescue"] = runner.PRODUCTION_DELTA64_RESCUE
    for field in runner.DELTA64_FIELDS:
        record[field] = 0
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
                    "read_meta_set_lookups": 1024,
                    "read_meta_set_hits": 100,
                    "read_meta_primary_hits": 80,
                    "read_meta_secondary_hits": 20,
                    "read_meta_set_probes": 7700,
                    "read_meta_set_replacements": 12,
                    "read_meta_copy_bytes": 207200,
                    "read_full_extent_reqs": 200,
                    "read_full_cache_hits": 64,
                    "read_two_block_skips": 128,
                    "parallel_read_pairs": 128,
                    "parallel_read_same_extent_pairs": 64,
                    "parallel_read_async_batches": 32,
                    "parallel_read_async_slots": 64,
                    "parallel_read_distinct_extent_pairs": 64,
                    "parallel_read_adjacent_extent_pairs": 24,
                    "parallel_read_adjacent_extent_blocks": 144,
                    "parallel_read_adjacent_chain_3plus": 0,
                    "parallel_read_adjacent_chain_extent_max": 0,
                    "parallel_read_adjacent_chain_blocks_max": 0,
                    "parallel_read_coalesced_pairs": 20,
                    "parallel_read_coalesced_reqs_saved": 20,
                    "parallel_read_coalesced_blocks": 80,
                    "parallel_read_coalesce_extra_blocks": 0,
                    "parallel_read_coalesce_skip_cached": 1,
                    "parallel_read_coalesce_skip_noncontig_slot": 2,
                    "parallel_read_coalesce_skip_gap": 1,
                    "parallel_read_coalesce_skip_other": 0,
                    "read_worker_cpu_ns": 1000000,
                    "read_coalesce_max_blocks": 8,
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
        "host_cpu": {
            "status": "AVAILABLE", "wall_ns": 2_000_000_000,
            "online_cpus": 4, "affinity_cpus": 4, "tick_hz": 100,
            "busy_fraction": 0.50, "steal_fraction": 0.0,
            "pressure_some_fraction": 0.10,
        },
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
        "kernel_write_path": (standard_kernel_write(mode=mode, target=8)
                              if swapz else None),
        "kernel_read_path": (
            dict(packed["passes"]["sequential"]["kernel_read_path"])
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
                    "parallel_read_async_batches", "parallel_read_async_slots",
                    "parallel_read_distinct_extent_pairs",
                    "parallel_read_adjacent_extent_pairs",
                    "parallel_read_adjacent_extent_blocks"):
                kernel[field] = 0
        else:
            kernel["parallel_read_pairs"] = 128
            kernel["parallel_read_same_extent_pairs"] = 64
            kernel["parallel_read_async_batches"] = 32
            kernel["parallel_read_async_slots"] = 64
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


def fanout_arm(enabled):
    record = parallel_arm(enabled, regime="ssd_emulated")
    mixed_kernel = record["kernel_read_path"]
    source_kernel = record["packed_read"]["passes"]["sequential"]["kernel_read_path"]
    mixed_kernel.clear()
    mixed_kernel.update(source_kernel)

    # This final decision forces ID63 off. Preserve independent fan-out only.
    coalesce_fields = (
        "parallel_read_adjacent_extent_pairs",
        "parallel_read_adjacent_extent_blocks",
        "parallel_read_adjacent_chain_3plus",
        "parallel_read_adjacent_chain_extent_max",
        "parallel_read_adjacent_chain_blocks_max",
        "parallel_read_coalesced_pairs",
        "parallel_read_coalesced_reqs_saved",
        "parallel_read_coalesced_blocks",
        "parallel_read_coalesce_extra_blocks",
        "parallel_read_coalesce_skip_cached",
        "parallel_read_coalesce_skip_noncontig_slot",
        "parallel_read_coalesce_skip_gap",
        "parallel_read_coalesce_skip_other",
    )
    for kernel in [mixed_kernel] + [
            phase["kernel_read_path"]
            for phase in record["packed_read"]["passes"].values()]:
        for field in coalesce_fields:
            kernel[field] = 0

    if enabled:
        mixed_kernel["parallel_read_pairs"] = 96
        mixed_kernel["parallel_read_same_extent_pairs"] = 0
        mixed_kernel["parallel_read_async_batches"] = 48
        mixed_kernel["parallel_read_async_slots"] = 144
        mixed_kernel["parallel_read_distinct_extent_pairs"] = 96
        record["throughput_mbps"]["logical_write_mbps"] = 25.0
        record["throughput_mbps"]["logical_read_mbps"] = 7.8
        record["read_p99_ns"] = 4_000_000
        record["lower_io"]["lower_read_requests"] = 3
        for phase in record["packed_read"]["passes"].values():
            phase["useful_read_mbps"] *= 1.05
            phase["read_p99_ms"] *= .95
    else:
        for field in ("parallel_read_pairs", "parallel_read_same_extent_pairs",
                      "parallel_read_async_batches", "parallel_read_async_slots",
                      "parallel_read_distinct_extent_pairs"):
            mixed_kernel[field] = 0
        record["throughput_mbps"]["logical_write_mbps"] = 24.0
        record["throughput_mbps"]["logical_read_mbps"] = 7.0
        record["read_p99_ns"] = 5_000_000
        record["lower_io"]["lower_read_requests"] = 4
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


def k1_read_bypass_arm(allow, regime):
    record = arm("swapz", mode=1, regime=regime)
    kernel = record["kernel_write_path"]
    kernel["k1_allow_after_read_bypass"] = allow
    kernel["read_coalesce_max_blocks"] = 8
    kernel["invalidate_cache_on_write_admit"] = 0
    kernel["pipeline_read_bypass_skips"] = 3 if not allow else 0
    record["fixture_sha256"] = "1" * 64
    record["trace_sha256"] = "2" * 64
    return record


def read_coalesce_cap_arm(cap, regime):
    record = coalesce_arm(True, regime=regime)
    for phase in record["packed_read"]["passes"].values():
        phase["kernel_read_path"]["read_coalesce_max_blocks"] = cap
    record["fixture_sha256"] = "3" * 64
    record["trace_sha256"] = "4" * 64
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
        "host_cpu": {
            "status": "AVAILABLE", "wall_ns": 2_000_000_000,
            "online_cpus": 4, "affinity_cpus": 4, "tick_hz": 100,
            "busy_fraction": 0.50, "steal_fraction": 0.0,
            "pressure_some_fraction": 0.10,
        },
        "lower_inflight": lower_inflight(has_reads=False),
        "kernel_write_path": (standard_kernel_write(
            mode=mode, target=max(4, qd)) if swapz else None),
    }

def delta64_prepare_arm(workers):
    record = write_arm("swapz", qd=32, regime="ssd_emulated", mode=1)
    kernel = record["kernel_write_path"]
    kernel.update({
        "delta64_rescue": 1,
        "delta64_prepare_workers": workers,
        "delta64_prepare_active_max": workers,
        "delta64_prepare_pages": 100,
        "delta64_prepare_parallel_starts": 0 if workers == 1 else 20,
        "delta64_eligible": 100,
        "delta64_classifier_pass": 100,
        "delta64_attempts": 100,
        "delta64_adopted": 100,
        "delta64_raw_rescues": 0,
        "delta64_lz4_rescues": 100,
        "delta64_pack_eligible": 0,
        "delta64_pack_attempts": 0,
        "delta64_pack_cliff_crossings": 0,
        "delta64_pack_adopted": 0,
        "delta64_score_0_7": 0,
        "delta64_score_8_15": 0,
        "delta64_score_16_23": 0,
        "delta64_score_ge24": 100,
        "delta64_payload_bytes_saved": 100000,
        "delta64_raw_payload_bytes_saved": 0,
        "delta64_lz4_payload_bytes_saved": 100000,
        "delta64_transform_calls": 100,
        "delta64_transform_wall_ns": 100000,
        "delta64_wall_ns": 1500000,
    })
    record["throughput_mbps"]["logical_write_mbps"] = 18 + workers
    record["fixture_sha256"] = "e" * 64
    record["trace_sha256"] = "f" * 64
    return record


def delta64_rescue_arm(enabled):
    if enabled:
        record = delta64_prepare_arm(1)
        record["throughput_mbps"]["logical_write_mbps"] = 20.0
        record["write_p99_ns"] = 2_300_000
    else:
        # The A/B off arm is pinned with --no-delta64-rescue.
        record = write_arm("swapz", qd=32, regime="ssd_emulated", mode=1)
        record["kernel_write_path"]["delta64_rescue"] = 0
        record["kernel_write_path"]["delta64_prepare_workers"] = 1
    record["kernel_write_path"]["delta64_lz4_acceleration"] = 4
    record["fixture_sha256"] = "e" * 64
    record["trace_sha256"] = "f" * 64
    return record


def write_pipeline_arm(depth):
    record = write_arm("swapz", qd=32, regime="ssd_emulated", mode=1)
    kernel = record["kernel_write_path"]
    kernel["delta64_rescue"] = 0  # retired depth A/B pins LZ4-only arms
    kernel["write_pipeline_depth"] = depth
    kernel["pipeline_active_max"] = depth
    if depth == 2:
        record["throughput_mbps"]["logical_write_mbps"] *= 1.10
        record["write_p99_ns"] = int(record["write_p99_ns"] * .90)
        record["lower_io"]["lower_write_requests"] = 1500
    record["fixture_sha256"] = "7" * 64
    record["trace_sha256"] = "8" * 64
    return record


def storage_envelope_arm(candidate, *, envelope, delta64_rescue):
    swapz = candidate == "swapz"
    spec = runner.STORAGE_ENVELOPE_SPECS[envelope]
    cap = spec["cap_mib_s"]
    raw = min(cap, 50.0)
    swapz_rate = raw * (1.1 if delta64_rescue else 1.05)
    logical = 4096 * 4096
    lower = int(logical / 1.5) if swapz else logical
    record = {
        "candidate": candidate,
        "verdict": "PASS",
        "source_sha": "a" * 40,
        "fixture_sha256": "b" * 64,
        "trace_sha256": "c" * 64,
        "replay_engine": "native-c",
        "seconds": 2.0,
        "throughput_mbps": {
            "logical_write_mbps": swapz_rate if swapz else raw,
            "logical_read_mbps": 0.0,
            "logical_write_bytes": logical,
            "logical_read_bytes": 0,
        },
        "lower_io": {
            "lower_write_bytes": lower,
            "lower_write_requests": 1500 if swapz else 4096,
            "lower_read_bytes": 0,
            "lower_read_requests": 0,
        },
        "lower_inflight": {
            "write_peak": 4,
            "write_time_weighted": 2.5,
        },
        "write_p99_ns": 2000000,
    }
    if swapz:
        record["kernel_write_path"] = {
            field: 0 for field in runner.KERNEL_WRITE_FIELDS
        }
        record["kernel_write_path"].update({
            "delta64_rescue": delta64_rescue,
            "prep_lower_write_samples": 10,
            "prep_lower_write_start_queued": 2,
            "prep_lower_write_end_queued": 2,
            "prep_lower_write_start_nonempty": 3,
            "prep_lower_write_end_nonempty": 3,
            "k1_ready_wait_windows": 1,
            "k1_ready_wait_records": 1,
            "k1_ready_wait_max_records": 1,
            "k1_ready_wait_wall_ns": 1000,
            "pipeline_finalize_wait_wall_ns": 2000,
            "pipeline_active_wall_ns": 5000,
            "pipeline_post_lower_wall_ns": 1000,
            "prep_wait_wall_ns": 500,
            "window_commit_nonio_wall_ns": 500,
            "engine_plan_wall_ns": 500,
            "pack_wall_ns": 500,
            "publish_wall_ns": 500,
            "publish_crc32c_wall_ns": 500,
        })
    return record


def lz4_acceleration_log():
    out = []
    spec = runner.MODEL_SPECS["ssd_emulated"]
    sequence = [4 if bit else 1 for bit in runner.CONFIRMATION_SEQUENCE]
    for index, acceleration in enumerate(sequence):
        out.append(f"START_LZ4_ACCELERATION={acceleration}")
        out.append("REPLAY_ORDER=swapz-first" if index % 2 else
                   "REPLAY_ORDER=off-first")
        out.append(
            "PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} "
            "COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} "
            "QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} "
            "HW_QUEUE_DEPTH={hw_queue_depth}".format(**spec))
        off = arm("off", mode=1, regime="ssd_emulated")
        swapz = arm("swapz", mode=1, regime="ssd_emulated")
        off["throughput_mbps"]["logical_write_mbps"] = 28.0
        swapz["throughput_mbps"]["logical_write_mbps"] = (
            26.0 if acceleration == 1 else 27.0)
        swapz["write_p99_ns"] = 4_000_000 if acceleration == 1 else 3_800_000
        kernel = swapz["kernel_write_path"]
        kernel["delta64_rescue"] = 0  # retired LZ4 A/B pins LZ4-only arms
        kernel["lz4_acceleration"] = acceleration
        kernel["lz4_wall_ns"] = 1_000_000 if acceleration == 1 else 800_000
        kernel["ordered_lz4_wall_ns"] = (
            700_000 if acceleration == 1 else 560_000)
        kernel["prep_lz4_wall_ns"] = (
            300_000 if acceleration == 1 else 240_000)
        for record in ((swapz, off) if index % 2 else (off, swapz)):
            out.append(json.dumps(record))
        out.append(f"PASS_LZ4_ACCELERATION={acceleration}")
    return out


def synthetic_log():
    out = ["HOST_SWAPS_BEFORE:", "/private/system/swapfile",
           "SOURCE_HEAD=a" + "a" * 39,
           "PASS_LOADED_RAW_READ_FANOUT=profiles:2 verified_pages:2048 async_batches:64 lower_read_reqs:512",
                "PASS_LOADED_ORACLE_PROFILE=raw_pages:64 zero_pages:9 flush_calls:2",
           "PASS_LOADED_LIVE_GC=victims:12 rotations:12 pages:12 read_bytes:49152 write_bytes:49152 read_reqs:12 write_reqs:12 distinct:6 victim_min:1 victim_max:3 last:11->29 discards:12 discard_sectors:24576 discard_unsupported:0 discard_failed:0 verified_pages:4096",
           "PASS_LOADED_GC_PRESSURE=rounds:5 write_wall_ns:1000000000 baseline_p99_ns:1000000 pressure_p99_ns:5000000 gc_wall_ns:200000000 gc_fraction_ppm:200000 choose_wall_ns:20000000 choose_calls:12 choose_map_entries:0 choose_segment_entries:768 relocation_map_entries:12 no_headroom_skips:3 alignment_hole_fg:4 alignment_hole_gc:1 tail_waste_fg:4 tail_waste_gc:1 run_splits_by_hole:0 alloc_probe_segments:1024 alloc_probe_full_scans:16 alloc_probe_wall_ns:50000 trim_skipped:6 segment_program_min:0 segment_program_sum:80 segment_program_max:4 segment_program_segments:32",
           "PASS_LOADED_DISCARD_TRIM=pages:256 immediate_discards:1 immediate_sectors:2048 reuse_skips:2 verified_pages:4096",
           "PASS_LOADED_PACKED_PLACEMENT=enabled:1 verified_pages:128 holes:0 run_splits:0 failed:0",
           "PASS_LOADED_SUSPEND_DRAIN=retain_ms:64 observed_open:1 verified_pages:128",
           "PASS_LOADED_COMPLETION_HANDOFF=offloaded:4 verified_pages:128 completed_writes:16512 active_after:0 fault_offloaded:2 fault_injected:1 post_failure_eio:1",
           "PASS_RETAINED_SYNTHETIC_WRITE_FAULT=retain_ms:2 injected:1 syscall_errno:EIO lower_write_delta:0",
           "PASS_RETAINED_SYNTHETIC_FLUSH_FAULT=retain_ms:2 injected:1 data_write_reached_lower:1",
           "PASS_ID36_RESOURCE_PRESSURE=memory_high_events:8 memory_peak_bytes:734003200 cpu_some_usec:250000 cpu_workers:8 pressure_mib:576 oom:0 oom_kill:0",
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
    for envelope in runner.STORAGE_ENVELOPE_ORDER:
        envelope_spec = runner.STORAGE_ENVELOPE_SPECS[envelope]
        for delta64_rescue in (0, 1):
            out.append(f"START_STORAGE_ENVELOPE={envelope} DELTA64_RESCUE={delta64_rescue}")
            out.append("REPLAY_ORDER=off-first")
            out.append(
                "PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} "
                "COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} "
                "QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} "
                "HW_QUEUE_DEPTH={hw_queue_depth}".format(**envelope_spec))
            off = storage_envelope_arm("off", envelope=envelope, delta64_rescue=delta64_rescue)
            swapz = storage_envelope_arm("swapz", envelope=envelope, delta64_rescue=delta64_rescue)
            out.append(json.dumps(off))
            out.append(json.dumps(swapz))
            out.append(f"PASS_STORAGE_ENVELOPE={envelope} DELTA64_RESCUE={delta64_rescue}")
    out.extend(lz4_acceleration_log())
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
        raw = arm("off", mode=1, regime="ssd_emulated")
        swapz = fanout_arm(enabled)
        for record in ((swapz, raw) if index % 2 else (raw, swapz)):
            out.append(json.dumps(record))
        out.append(f"PASS_PARALLEL_READ_AB={enabled}")

    for regime in runner.MODEL_ORDER:
        policy_spec = runner.MODEL_SPECS[regime]
        for index, allow in enumerate(runner.CONFIRMATION_SEQUENCE):
            out.append(f"START_K1_READ_BYPASS_AB={regime}:{allow}")
            out.append("REPLAY_ORDER=swapz-first" if index % 2 else
                       "REPLAY_ORDER=off-first")
            out.append(
                "PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} "
                "COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} "
                "QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} "
                "HW_QUEUE_DEPTH={hw_queue_depth}".format(**policy_spec))
            raw = arm("off", mode=1, regime=regime)
            swapz = k1_read_bypass_arm(allow, regime)
            for record in ((swapz, raw) if index % 2 else (raw, swapz)):
                out.append(json.dumps(record))
            out.append(f"PASS_K1_READ_BYPASS_AB={regime}:{allow}")
        for index, read_cap in enumerate(runner.READ_COALESCE_CAP_SEQUENCE):
            out.append(f"START_READ_COALESCE_CAP_AB={regime}:{read_cap}")
            out.append("REPLAY_ORDER=swapz-first" if index % 2 else
                       "REPLAY_ORDER=off-first")
            out.append(
                "PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} "
                "COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} "
                "QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} "
                "HW_QUEUE_DEPTH={hw_queue_depth}".format(**policy_spec))
            raw = arm("off", mode=0, regime=regime)
            swapz = read_coalesce_cap_arm(read_cap, regime)
            for record in ((swapz, raw) if index % 2 else (raw, swapz)):
                out.append(json.dumps(record))
            out.append(f"PASS_READ_COALESCE_CAP_AB={regime}:{read_cap}")
    spec = runner.MODEL_SPECS["ssd_emulated"]
    for index, enabled in enumerate(runner.CONFIRMATION_SEQUENCE):
        out.append(f"START_DELTA64_RESCUE={enabled}")
        out.append("REPLAY_ORDER=swapz-first" if index % 2 else
                   "REPLAY_ORDER=off-first")
        out.append(
            "PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} "
            "COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} "
            "QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} "
            "HW_QUEUE_DEPTH={hw_queue_depth}".format(**spec))
        off = write_arm("off", qd=32, regime="ssd_emulated", mode=0)
        off["fixture_sha256"] = "e" * 64
        off["trace_sha256"] = "f" * 64
        swapz = delta64_rescue_arm(enabled)
        for record in ((swapz, off) if index % 2 else (off, swapz)):
            out.append(json.dumps(record))
        out.append(f"PASS_DELTA64_RESCUE={enabled}")
    delta64_sequence = [2 if bit else 1
                        for bit in runner.CONFIRMATION_SEQUENCE]
    for index, workers in enumerate(delta64_sequence):
        out.append(f"START_DELTA64_PREPARE_WORKERS={workers}")
        out.append("REPLAY_ORDER=swapz-first" if index % 2 else
                   "REPLAY_ORDER=off-first")
        out.append(
            "PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} "
            "COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} "
            "QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} "
            "HW_QUEUE_DEPTH={hw_queue_depth}".format(**spec))
        off = write_arm("off", qd=32, regime="ssd_emulated", mode=0)
        off["fixture_sha256"] = "e" * 64
        off["trace_sha256"] = "f" * 64
        swapz = delta64_prepare_arm(workers)
        for record in ((swapz, off) if index % 2 else (off, swapz)):
            out.append(json.dumps(record))
        out.append(f"PASS_DELTA64_PREPARE_WORKERS={workers}")
    for regime in runner.MODEL_ORDER:
        spec = runner.MODEL_SPECS[regime]
        out.append(f"START_WRITE_SATURATION_REGIME={regime}")
        index = 0
        for qd in (1, 4, 8, 32):
            modes = (runner.CONFIRMATION_SEQUENCE
                     if ((regime == "ssd_emulated" and qd in (4, 8, 32)) or
                         (regime == "sd_emulated" and qd == 32))
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
    spec = runner.MODEL_SPECS["ssd_emulated"]
    depth_sequence = [2 if bit else 1 for bit in runner.CONFIRMATION_SEQUENCE]
    for index, depth in enumerate(depth_sequence):
        out.append(f"START_WRITE_PIPELINE_DEPTH={depth}")
        out.append("REPLAY_ORDER=swapz-first" if index % 2 else
                   "REPLAY_ORDER=off-first")
        out.append(
            "PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} "
            "COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} "
            "QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} "
            "HW_QUEUE_DEPTH={hw_queue_depth}".format(**spec))
        off = write_arm("off", qd=32, regime="ssd_emulated", mode=1)
        off["fixture_sha256"] = "7" * 64
        off["trace_sha256"] = "8" * 64
        swapz = write_pipeline_arm(depth)
        for record in ((swapz, off) if index % 2 else (off, swapz)):
            out.append(json.dumps(record))
        out.append(f"PASS_WRITE_PIPELINE_DEPTH={depth}")
    return "\n".join(out) + "\n"


class ReportContract(unittest.TestCase):
    def test_raw_read_fanout_evidence_is_mandatory(self):
        marker = ("PASS_LOADED_RAW_READ_FANOUT=profiles:2 verified_pages:2048 "
                  "async_batches:64 lower_read_reqs:512")
        output = synthetic_log()
        self.assertEqual(runner.parse_loaded_correctness(output)["overall"], "PASS")
        self.assertEqual(runner.parse_loaded_correctness(
            output.replace(marker, ""))["overall"], "INCOMPLETE")
        for before, after in (("profiles:2", "profiles:1"),
                              ("verified_pages:2048", "verified_pages:1024"),
                              ("async_batches:64", "async_batches:0"),
                              ("lower_read_reqs:512", "lower_read_reqs:0")):
            self.assertEqual(runner.parse_loaded_correctness(output.replace(
                marker, marker.replace(before, after)))["overall"], "INCOMPLETE")

    def test_vm_history_excludes_unqualified_other_host_and_mismatched_inputs(self):
        import copy

        spec = importlib.util.spec_from_file_location(
            "swapz_history_plot", ROOT / "tests/tools/plot-history.py")
        history = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(history)
        raw = {"source_sha": "source", "fixture_sha256": "fixture",
               "trace_sha256": "trace", "host_cpu": {"online_cpus": 7},
               "input_write_mbps": 100, "swap_in_read_mbps": 40,
               "swap_in_read_p99_ms": 4, "write_p99_ms": 8,
               "lower_write_bytes": 1000, "lower_write_requests": 100}
        swapz = {**raw, "input_write_mbps": 150, "swap_in_read_mbps": 60,
                 "swap_in_read_p99_ms": 2, "write_p99_ms": 4,
                 "lower_write_bytes": 700, "lower_write_requests": 20,
                 "kernel_write_path": {"delta64_rescue": 0}}
        session = {"status": "PASS", "async_prepare": 1, "regime": "sd_emulated",
                   "device_model": {"cap_mib_s": 10}, "arms": {"off": raw, "swapz": swapz}}
        report = {"overall": "PASS", "tested_commit_sha": "source", "kernel_release": "kernel",
                  "evidence": {"predictor": {"backend_benchmarks": [{"name": "neon"}]}},
                  "benchmarks": {"sessions": [session]}}
        self.assertTrue(history.host_matches(report))
        points = history.report_points(report)
        self.assertEqual(len(points), 1)
        for metric in ("write_mbps_gain_pct", "read_mbps_gain_pct", "read_p99_ms_gain_pct"):
            self.assertAlmostEqual(points[0][metric], 50)
        self.assertAlmostEqual(points[0]["lower_write_bytes_gain_pct"], 30)
        self.assertAlmostEqual(points[0]["lower_write_requests_gain_pct"], 80)
        self.assertEqual(history.change(0, 100, True), 100)
        self.assertIsNone(history.change(1, 0))
        for key, value in (("source_sha", "other"), ("fixture_sha256", "other"),
                           ("trace_sha256", "other"), ("kernel_write_path", None)):
            bad = copy.deepcopy(report)
            bad["benchmarks"]["sessions"][0]["arms"]["swapz"][key] = value
            self.assertEqual(history.report_points(bad), [])
        for state in ("FAIL", "BLOCKED"):
            self.assertEqual(history.report_points({**report, "overall": state}), [])
        self.assertFalse(history.host_matches({**report, "evidence": {}}))
        bad = copy.deepcopy(report)
        bad["benchmarks"]["sessions"][0]["arms"]["off"]["host_cpu"] = {"online_cpus": 8}
        self.assertFalse(history.host_matches(bad))
        bad = copy.deepcopy(report)
        bad["kernel_release"] = "another kernel"
        self.assertNotEqual(history.report_points(bad)[0]["compatibility"], points[0]["compatibility"])
        bad = copy.deepcopy(report)
        bad["benchmarks"]["sessions"][0]["async_prepare"] = 0
        self.assertEqual(history.report_points(bad), [])
        on = copy.deepcopy(report)
        on["benchmarks"]["sessions"][0]["arms"]["swapz"]["kernel_write_path"]["delta64_rescue"] = 1
        on_points = history.report_points(on)
        self.assertEqual(len(on_points), 1)
        self.assertEqual(on_points[0]["workload"], "mixed QD32, delta64 on")
        self.assertEqual(points[0]["workload"], "mixed QD32, delta64 off")
        self.assertNotEqual(on_points[0]["compatibility"], points[0]["compatibility"])
        bad = copy.deepcopy(report)
        bad["benchmarks"]["sessions"][0]["arms"]["swapz"]["kernel_write_path"]["delta64_rescue"] = None
        self.assertEqual(history.report_points(bad), [])
        sustained = copy.deepcopy(report)
        write_session = copy.deepcopy(session)
        write_session["qd"] = 4
        for arm in write_session["arms"].values():
            arm["replay_mode"] = "persistent-write"
        sustained["benchmarks"]["write_saturation"] = {
            "replay_mode": "persistent-write", "regimes": {"sd_emulated": [
                {"mode": "async", "qd": 4, "raw_write_mbps": 100,
                 "swapz_write_mbps": 150, "observations": 1}]}}
        sustained["benchmarks"]["write_saturation_sessions"] = [write_session]
        self.assertEqual(len(history.report_points(sustained)), 2)
        sustained["benchmarks"]["write_saturation"]["replay_mode"] = "qd-waves"
        self.assertEqual(len(history.report_points(sustained)), 1)
        sustained["benchmarks"]["write_saturation"]["replay_mode"] = "persistent-write"
        off_write = history.report_points(sustained)[-1]
        write_session["arms"]["swapz"]["kernel_write_path"]["delta64_rescue"] = 1
        on_write = history.report_points(sustained)
        self.assertEqual(len(on_write), 2)
        self.assertNotEqual(on_write[-1]["compatibility"], off_write["compatibility"])
        mixed = copy.deepcopy(write_session)
        mixed["arms"]["swapz"]["kernel_write_path"]["delta64_rescue"] = 0
        sustained["benchmarks"]["write_saturation_sessions"].append(mixed)
        self.assertEqual(len(history.report_points(sustained)), 1)

    def test_x86_history_requires_audited_reports_and_separate_isa_profile(self):
        import copy

        spec = importlib.util.spec_from_file_location(
            "swapz_x86_history", ROOT / "tests/tools/plot-history.py")
        history = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(history)
        sha = "a" * 40
        profile = {"id": "x86-i7-avx512", "title": "x86 AVX-512 host",
                   "online_cpus": 8, "host_id_sha256": "b" * 64,
                   "report_shas": [sha]}
        self.assertEqual(history.validate_host_profile(profile), profile)
        report = {"overall": "PASS", "stages": [{"status": "PASS"}] * 5,
                  "evidence": {"predictor": {"backend_benchmarks": [
                      {"name": name} for name in ("scalar", "sse2", "avx2", "avx512")]}},
                  "benchmarks": {"sessions": [{"arms": {
                      arm: {"host_cpu": {"online_cpus": 8}} for arm in ("off", "swapz")}}]}}
        self.assertTrue(history.selected_host_report(report, sha, profile))
        self.assertFalse(history.selected_host_report(report, "c" * 40, profile))
        self.assertFalse(history.selected_host_report(report, sha))
        for mutate in (lambda r: r.update(overall="BLOCKED"),
                       lambda r: r["stages"].pop(),
                       lambda r: r["evidence"]["predictor"]["backend_benchmarks"].pop(),
                       lambda r: r["benchmarks"]["sessions"][0]["arms"]["off"].update(
                           host_cpu={"online_cpus": 4}),
                       lambda r: r["benchmarks"]["sessions"][0]["arms"]["off"].pop("host_cpu")):
            bad = copy.deepcopy(report)
            mutate(bad)
            self.assertFalse(history.selected_host_report(bad, sha, profile))
        for changes in ({"id": "../arm64-neon"}, {"report_shas": []},
                        {"report_shas": ["HEAD"]}, {"host_id_sha256": ""}):
            with self.assertRaises(ValueError):
                history.validate_host_profile({**profile, **changes})

    def test_history_snapshots_preserve_report_specific_artifacts(self):
        spec = importlib.util.spec_from_file_location(
            "swapz_history_snapshots", ROOT / "tests/tools/plot-history.py")
        history = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(history)
        with tempfile.TemporaryDirectory() as directory:
            history.OUT = Path(directory)
            names = ("mixed-service.png", "mixed-throughput.png", "mixed-latency.png",
                     "lower-write-savings.png", "sustained-write.png", "history.csv", "history.json")
            for name in names:
                (history.OUT / name).write_bytes(b"first report")
            data = {"reports": [{"report_sha": "a" * 40}]}
            first = history.snapshot_history(data)
            for name in names:
                self.assertEqual((first / name).read_bytes(), b"first report")
                (history.OUT / name).write_bytes(b"next report")
            self.assertEqual(history.snapshot_history(data), first)
            self.assertEqual((first / names[0]).read_bytes(), b"first report")
            second = history.snapshot_history({"reports": [{"report_sha": "b" * 40}]})
            self.assertNotEqual(second, first)
            self.assertEqual((second / names[0]).read_bytes(), b"next report")

    def test_computer_history_rejects_other_and_unidentified_hosts(self):
        spec = importlib.util.spec_from_file_location(
            "swapz_computer_history", ROOT / "tests/tools/plot-history.py")
        history = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(history)
        identity = {"schema": "swapz-host-v1", "architecture": "x86_64",
                    "id_sha256": "a" * 64}
        report = {"host_identity": identity, "overall": "PASS",
                  "stages": [{"status": "PASS"}] * 5}
        self.assertTrue(history.same_computer_report(report, identity))
        for different in ({**identity, "id_sha256": "b" * 64},
                          {**identity, "architecture": "aarch64"}, {},
                          {**identity, "schema": "unknown"}):
            self.assertFalse(history.same_computer_report(report, different))
        self.assertFalse(history.same_computer_report(
            {**report, "overall": "BLOCKED"}, identity))
        self.assertFalse(history.same_computer_report(
            {**report, "stages": [{"status": "PASS"}] * 4}, identity))

    def test_history_collects_only_matching_computer_from_shared_git_reports(self):
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location(
            "swapz_shared_history", ROOT / "tests/tools/plot-history.py")
        history = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(history)
        identity = {"schema": "swapz-host-v1", "architecture": "x86_64",
                    "id_sha256": "a" * 64}
        reports = {}
        for index, host in enumerate((identity, {**identity, "id_sha256": "b" * 64},
                                      {**identity, "id_sha256": "c" * 64}, None,
                                      identity), 1):
            reports[f"{index:040x}"] = {"host_identity": host, "overall": "PASS",
                "stages": [{"status": "PASS"}] * 5, "tested_commit_sha": "f" * 40}
        def git_output(command, **kwargs):
            if command[1] == "log":
                return "\n".join(sha + " 2026-10-30T12:00:00-07:00" for sha in reports)
            return json.dumps(reports[command[2].split(":")[0]]).encode()
        with patch.object(history.subprocess, "check_output", side_effect=git_output), \
                patch.object(history, "report_points", return_value=[{"target": "ssd_emulated"}]):
            data = history.collect(computer=identity)
        self.assertEqual([r["report_sha"] for r in data["reports"]],
                         [f"{1:040x}", f"{5:040x}"])
        self.assertEqual(data["excluded"]["other or unproven host"], 3)

    def test_host_identity_missing_or_invalid_fails_closed(self):
        from unittest.mock import patch
        for value in ("", "0" * 32, "not-a-machine-id"):
            with patch.object(Path, "read_text", return_value=value):
                self.assertEqual(runner.report_host_identity()["status"], "UNAVAILABLE")
        with patch.object(Path, "read_text", return_value="a" * 32):
            identity = runner.report_host_identity()
            self.assertEqual(len(identity["id_sha256"]), 64)
            self.assertNotIn("a" * 32, json.dumps(identity))
        with patch.object(Path, "read_text", side_effect=OSError):
            self.assertEqual(runner.report_host_identity()["status"], "UNAVAILABLE")

    def test_history_refresh_executes_after_publication_without_changing_verdicts(self):
        from unittest.mock import patch
        identity = {"schema": "swapz-host-v1", "architecture": "x86_64",
                    "id_sha256": "a" * 64}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = root / "tests/tools/plot-history.py"
            helper.parent.mkdir(parents=True)
            helper.write_text(
                "import json, sys\n"
                "from pathlib import Path\n"
                "Path('build/history/marker').write_text(json.dumps(sys.argv))\n"
                "print('{\"reports\": 3, \"latest_source\": \"abcdef0123456789\"}')\n")
            with patch.object(runner, "ROOT", root):
                result = runner.refresh_history(identity)
                self.assertIn("UPDATED: 3 this-computer PASS reports", result)
                self.assertIn("abcdef012345", result)
                marker = root / "build/history/marker"
                command = json.loads(marker.read_text())
                self.assertEqual(command[1:], ["--host-id", "a" * 64,
                                               "--host-architecture", "x86_64"])
                helper.write_text("raise SystemExit('matplotlib unavailable')\n")
                self.assertTrue(runner.refresh_history(identity).startswith("NOT UPDATED:"))
                log = root / "build/history" / ("x86_64-" + "a" * 64) / "refresh.log"
                self.assertIn("matplotlib unavailable", log.read_text())
                helper.write_text("print('invalid summary')\n")
                self.assertTrue(runner.refresh_history(identity).startswith("NOT UPDATED:"))
                marker.unlink()
                self.assertIn("stable host identity unavailable", runner.refresh_history({}))
                self.assertFalse(marker.exists())
        main = (ROOT / "tests/tools/run-tests.py").read_text().split("def main():", 1)[1]
        self.assertLess(main.index("notice = publish("), main.index("refresh_history("))

    def test_vm_history_lines_break_at_workload_changes_and_missing_reports(self):
        spec = importlib.util.spec_from_file_location(
            "swapz_history_lines", ROOT / "tests/tools/plot-history.py")
        history = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(history)

        class Axes:
            def __init__(self):
                self.chunks = []

            def plot(self, x, y, *args, **kwargs):
                self.chunks.append(x)

        axes = Axes()
        history.draw_line(axes, [
            {"sequence": 1, "compatibility": "a", "gain": 1},
            {"sequence": 2, "compatibility": "a", "gain": 2},
            {"sequence": 3, "compatibility": "b", "gain": 3},
            {"sequence": 5, "compatibility": "b", "gain": 4},
        ], "gain", "gain", "blue")
        self.assertEqual(axes.chunks, [[1, 2], [3], [5]])

    def test_loaded_progress_stream_hides_bulk_evidence_but_keeps_phase_and_failure(self):
        self.assertIsNone(runner.loaded_progress_line(
            "TARGET_STATUS_AFTER=0 8192 swapz physical_write=123456"))
        self.assertIsNone(runner.loaded_progress_line(
            '{"candidate":"swapz","verdict":"PASS","throughput_mbps":{}}'))
        self.assertEqual(
            runner.loaded_progress_line("START_OWNED_RAM_PAIR_ASYNC_PREPARE=1"),
            "START_OWNED_RAM_PAIR_ASYNC_PREPARE=1")
        self.assertEqual(
            runner.loaded_progress_line(
                "PASS_LOADED_LIVE_GC=victims:20 rotations:20 pages:20"),
            "PASS_LOADED_LIVE_GC")
        self.assertEqual(
            runner.loaded_progress_line(
                "PASS_RETAINED_SYNTHETIC_WRITE_FAULT=retain_ms:2 injected:1"),
            "PASS_RETAINED_SYNTHETIC_WRITE_FAULT")
        self.assertEqual(
            runner.loaded_progress_line(
                "START_ID36_RESOURCE_PRESSURE=memory_high:1 pressure_mib:576"),
            "START_ID36_RESOURCE_PRESSURE")
        self.assertEqual(
            runner.loaded_progress_line("FAIL: owned RAM pair timed out"),
            "FAIL: owned RAM pair timed out")

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
        self.assertIn("for envelope in sd_card sata_ssd nvme_gen4 nvme_gen5", loaded)
        self.assertIn("START_STORAGE_ENVELOPE=", loaded)
        self.assertIn("--submit-queues", loaded)
        self.assertIn("START_WRITE_SATURATION_PAIR_QD=", loaded)
        self.assertEqual(
            runner.STORAGE_ENVELOPE_SPECS["sd_card"]["cap_mib_s"], 100)
        self.assertEqual(
            runner.STORAGE_ENVELOPE_SPECS["sata_ssd"]["cap_mib_s"], 500)
        self.assertEqual(
            runner.STORAGE_ENVELOPE_SPECS["nvme_gen4"]["submit_queues"], 4)
        self.assertEqual(
            runner.STORAGE_ENVELOPE_SPECS["nvme_gen5"]["submit_queues"], 4)
        nvme_limits = runner.device_model_limits(
            runner.STORAGE_ENVELOPE_SPECS["nvme_gen5"], offered_qd=32)
        self.assertEqual(nvme_limits["effective_queue_depth"], 32)
        self.assertNotIn("START_PARALLEL_READ_AB=", loaded)
        self.assertNotIn("PASS_PARALLEL_READ_AB=", loaded)
        self.assertNotIn("START_SD_READ_GROUPING_AB=", loaded)
        self.assertNotIn("--parallel-reads", loaded)
        self.assertIn("--write-only-qd", loaded)
        self.assertNotIn("swapon ", loaded)
        self.assertNotIn("swapoff ", loaded)
        self.assertNotIn("/dev/sdb", loaded)

    def test_storage_envelopes_report_capture_and_qd_limited_ceiling(self):
        lines = []
        for envelope in runner.STORAGE_ENVELOPE_ORDER:
            spec = runner.STORAGE_ENVELOPE_SPECS[envelope]
            for rescue in (0, 1):
                raw = arm("off", mode=1, regime="ssd_emulated")
                swapz = arm("swapz", mode=1, regime="ssd_emulated")
                raw["replay_engine"] = "native-c"
                swapz["replay_engine"] = "native-c"
                swapz["kernel_write_path"]["delta64_rescue"] = rescue
                lines.extend((
                    f"START_STORAGE_ENVELOPE={envelope} DELTA64_RESCUE={rescue}",
                    "PASS_RAM_MODEL_LOWER_MBPS="
                    f"{spec['cap_mib_s']} COMPLETION_NSEC={spec['completion_nsec']} "
                    f"IRQMODE={spec['irqmode']} QUEUE_MODE={spec['queue_mode']} "
                    f"SUBMIT_QUEUES={spec['submit_queues']} "
                    f"HW_QUEUE_DEPTH={spec['hw_queue_depth']}",
                    json.dumps(raw),
                    json.dumps(swapz),
                    f"PASS_STORAGE_ENVELOPE={envelope} DELTA64_RESCUE={rescue}",
                ))
        sessions = runner.parse_storage_envelope_sessions("\n".join(lines))
        self.assertEqual(len(sessions), 8)
        verdict = runner.storage_envelope_verdict(sessions)
        self.assertEqual(
            verdict["overall"], "PASS_DIRECTIONAL_STORAGE_ENVELOPES")
        self.assertEqual(len(verdict["rows"]), 8)
        for row in verdict["rows"]:
            spec = runner.STORAGE_ENVELOPE_SPECS[row["envelope"]]
            self.assertEqual(
                row["device_limits"]["effective_queue_depth"],
                min(32, spec["submit_queues"] * spec["hw_queue_depth"]))
            self.assertAlmostEqual(row["byte_speedup"], 1.6)
            self.assertAlmostEqual(row["request_speedup"], 1.6)
            self.assertLess(
                row["bandwidth_opportunity_capture_fraction"], 0.0)
            self.assertAlmostEqual(row["post_lower_hold_fraction"], 0.004)
            self.assertEqual(row["replay_engine"], "native-c")

        bad = [dict(session) for session in sessions]
        bad[0] = dict(bad[0], arms={
            name: dict(arm_record) for name, arm_record in bad[0]["arms"].items()
        })
        bad[0]["arms"]["off"]["replay_engine"] = "python-threaded"
        self.assertEqual(
            runner.storage_envelope_verdict(bad)["overall"], "INCONCLUSIVE")


    def test_predictor_evidence_is_sanitized(self):
        raw = predictor_evidence()
        parsed = runner.parse_predictor_evidence(
            "SWAPZ_PREDICTOR_EVIDENCE=" + json.dumps(raw) + "\n")
        self.assertEqual(parsed, raw)
        broken = json.loads(json.dumps(raw))
        broken["sse2_forward_ab"]["pairs"][2]["order"] = "unrolled_first"
        self.assertIsNone(runner.parse_predictor_evidence(
            "SWAPZ_PREDICTOR_EVIDENCE=" + json.dumps(broken) + "\n"))
        broken = json.loads(json.dumps(raw))
        broken["sse2_forward_ab"]["pairs"][0]["unrolled_ns_per_page"] = 0
        self.assertIsNone(runner.parse_predictor_evidence(
            "SWAPZ_PREDICTOR_EVIDENCE=" + json.dumps(broken) + "\n"))
        broken = json.loads(json.dumps(raw))
        broken["thresholds"][2]["negative_calls"] = 65
        self.assertIsNone(runner.parse_predictor_evidence(
            "SWAPZ_PREDICTOR_EVIDENCE=" + json.dumps(broken) + "\n"))
        broken = predictor_evidence()
        broken["thresholds"][2]["routed_blocks_saved"] += 1
        self.assertIsNone(runner.parse_predictor_evidence(
            "SWAPZ_PREDICTOR_EVIDENCE=" + json.dumps(broken) + "\n"))
        broken = predictor_evidence()
        broken["sampling_controls"][0]["score"] = 1
        self.assertIsNone(runner.parse_predictor_evidence(
            "SWAPZ_PREDICTOR_EVIDENCE=" + json.dumps(broken) + "\n"))
        broken = predictor_evidence()
        broken["production_route"]["candidate_attempts"] -= 1
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
        # The null_blk lifecycle oracle alone uses 64 ms for slow observers;
        # the production retained-window ceiling remains 4 ms.
        self.assertEqual(loaded["suspend_retain_ms"], 64)
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
            "PASS_LOADED_SUSPEND_DRAIN=retain_ms:64 observed_open:1 "
            "verified_pages:128\n", "")
        self.assertEqual(runner.parse_loaded_correctness(missing)["overall"],
                         "INCOMPLETE")

        handoff = ("PASS_LOADED_COMPLETION_HANDOFF=offloaded:4 verified_pages:128 "
                   "completed_writes:16512 active_after:0 fault_offloaded:2 "
                   "fault_injected:1 post_failure_eio:1")
        for replacement in (
                "", handoff.replace("offloaded:4", "offloaded:0"),
                handoff.replace("verified_pages:128", "verified_pages:127"),
                handoff.replace("completed_writes:16512", "completed_writes:16511"),
                handoff.replace("active_after:0", "active_after:1"),
                handoff.replace("fault_offloaded:2", "fault_offloaded:0"),
                handoff.replace("fault_injected:1", "fault_injected:0"),
                handoff.replace("post_failure_eio:1", "post_failure_eio:0")):
            self.assertEqual(runner.parse_loaded_correctness(
                synthetic_log().replace(handoff, replacement))["overall"],
                "INCOMPLETE")

        # The exact loaded test now proves an aligned O_DIRECT pwrite(2)
        # returned -1/EIO, not just that the kernel injected a fault.
        # Missing, wrong or reordered syscall evidence must fail closed.
        marker = (
            "PASS_RETAINED_SYNTHETIC_WRITE_FAULT=retain_ms:2 injected:1 "
            "syscall_errno:EIO lower_write_delta:0")
        # Prevent a future contract drift: the rootless fixture must match
        # the exact marker the privileged owner script actually emits.
        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()
        make_interface = (
            ROOT / "tests/runtime/native/make-interface-test.py").read_text()
        self.assertIn('note "' + marker + '"', deploy)
        self.assertIn(marker, make_interface)
        self.assertIn(marker, synthetic_log())
        for replacement in (
            marker.replace("syscall_errno:EIO ", ""),
            marker.replace("syscall_errno:EIO", "syscall_errno:ENOSPC"),
            marker.replace("syscall_errno:EIO", "syscall_errno:0"),
            marker.replace("syscall_errno:EIO lower_write_delta:0",
                           "lower_write_delta:0 syscall_errno:EIO"),
            marker.replace("lower_write_delta:0", "lower_write_delta:1"),
            marker.replace("injected:1", "injected:0"),
            marker.replace("retain_ms:2", "retain_ms:0"),
        ):
            with self.subTest(invalid_write_fault_marker=replacement):
                bad = synthetic_log().replace(marker, replacement)
                result = runner.parse_loaded_correctness(bad)
                self.assertEqual(result["overall"], "INCOMPLETE")
                self.assertIn("write", result["reason"].lower())


    def test_mixed_sessions_end_before_later_benchmark_families(self):
        log = synthetic_log()
        sessions = runner.parse_sessions(log)
        self.assertEqual(len(sessions), 14)
        self.assertTrue(all(
            row["arms"]["swapz"]["kernel_write_path"][
                "lz4_acceleration"] == 1 and
            row["arms"]["swapz"]["kernel_write_path"][
                "delta64_rescue"] == runner.PRODUCTION_DELTA64_RESCUE
            for row in sessions))

        lz4_start = log.index("START_LZ4_ACCELERATION=")
        self.assertEqual(
            sessions,
            runner.parse_sessions(log[:lz4_start]))

        # An incomplete mixed pair remains incomplete when the next family
        # starts; its later JSON must never be attached to that pair.
        unfinished = "\n".join((
            "START_OWNED_RAM_REGIME=ssd_emulated",
            "START_OWNED_RAM_PAIR_ASYNC_PREPARE=1",
            json.dumps(arm("swapz", mode=1, regime="ssd_emulated")),
            "START_LZ4_ACCELERATION=1",
            json.dumps(arm("off", mode=1, regime="ssd_emulated")),
        ))
        incomplete = runner.parse_sessions(unfinished)
        self.assertEqual(len(incomplete), 1)
        self.assertEqual(incomplete[0]["status"], "INCOMPLETE")
        self.assertEqual(set(incomplete[0]["arms"]), {"swapz"})

        for field, value in (("lz4_acceleration", 4),
                             ("delta64_rescue",
                              1 - runner.PRODUCTION_DELTA64_RESCUE)):
            mixed = runner.parse_sessions(log)
            mixed[-1]["arms"]["swapz"]["kernel_write_path"][field] = value
            with self.subTest(mixed_policy=field):
                self.assertEqual(
                    runner.benchmark_verdicts(mixed)["overall"],
                    "INCOMPLETE")

    def test_loaded_lz4_acceleration_sweep_is_separate_and_fail_closed(self):
        log = synthetic_log()
        sessions = runner.parse_lz4_acceleration(log)
        expected = [4 if bit else 1 for bit in runner.CONFIRMATION_SEQUENCE]
        self.assertEqual([row["lz4_acceleration"] for row in sessions], expected)
        verdict = runner.lz4_acceleration_verdict(sessions)
        self.assertEqual(verdict["overall"], "PASS_LZ4_ACCELERATION_AB", verdict)
        self.assertEqual(verdict["matched_pairs"], 5)
        self.assertEqual(verdict["modes"]["1"]["observations"], 5)
        self.assertEqual(verdict["modes"]["4"]["observations"], 5)
        self.assertLess(
            verdict["paired"]["lz4_wall_change_fraction"]["high"], 0)
        self.assertGreater(
            verdict["paired"]["throughput_change_fraction"]["low"], 0)

        incomplete_log = log.replace("PASS_LZ4_ACCELERATION=4\n", "", 1)
        incomplete = runner.parse_lz4_acceleration(incomplete_log)
        self.assertNotEqual(
            runner.lz4_acceleration_verdict(incomplete)["overall"],
            "PASS_LZ4_ACCELERATION_AB")

        duplicate = sessions + [sessions[0]]
        self.assertNotEqual(
            runner.lz4_acceleration_verdict(duplicate)["overall"],
            "PASS_LZ4_ACCELERATION_AB")

        changed = runner.parse_lz4_acceleration(log)
        changed[1]["arms"]["swapz"]["kernel_write_path"]["lz4_acceleration"] = 1
        self.assertNotEqual(
            runner.lz4_acceleration_verdict(changed)["overall"],
            "PASS_LZ4_ACCELERATION_AB")

        changed = runner.parse_lz4_acceleration(log)
        changed[2]["arms"]["off"]["trace_sha256"] = "d" * 64
        self.assertEqual(
            runner.lz4_acceleration_verdict(changed)["overall"],
            "INCONCLUSIVE")

        changed = runner.parse_lz4_acceleration(log)
        changed[0]["arms"]["off"]["lower_write_requests"] = True
        self.assertNotEqual(
            runner.lz4_acceleration_verdict(changed)["overall"],
            "PASS_LZ4_ACCELERATION_AB")

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

        parallel_read = runner.parse_parallel_read_ab(synthetic_log())
        self.assertEqual([row["parallel_reads"] for row in parallel_read],
                         list(runner.CONFIRMATION_SEQUENCE))
        parallel_diag = runner.parallel_read_ab_verdict(parallel_read)
        self.assertEqual(parallel_diag["overall"],
                         "PASS_PARALLEL_READ_AB_EVIDENCE", parallel_diag)
        self.assertEqual(parallel_diag["matched_pairs"], 5)
        self.assertEqual(
            parallel_diag["modes"]["0"]["mixed"]["async_batches"], 0)
        self.assertGreater(
            parallel_diag["modes"]["1"]["mixed"]["async_batches"], 0)
        self.assertIn("write_mbps", parallel_diag["paired"]["mixed"])
        self.assertIn("sequential", parallel_diag["paired"]["packed"])

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

        delta64_rescue = runner.parse_delta64_rescue_sessions(
            synthetic_log())
        self.assertEqual([row["rescue"] for row in delta64_rescue],
                         list(runner.CONFIRMATION_SEQUENCE))
        rescue_diag = runner.delta64_rescue_verdict(delta64_rescue)
        self.assertEqual(rescue_diag["overall"],
                         "PASS_DELTA64_RESCUE_AB", rescue_diag)
        self.assertEqual(rescue_diag["matched_pairs"], 5)
        self.assertEqual(rescue_diag["modes"]["0"]["delta64_attempts"], 0)
        self.assertGreater(rescue_diag["modes"]["1"]["delta64_attempts"], 0)
        self.assertIn("throughput_change_fraction", rescue_diag["paired"])
        self.assertEqual(
            rescue_diag["interpretation"],
            "SAME_SOURCE_K1_DELTA64_RESCUE_OFF_ON_POSITIVE_FIXTURE_SECOND_LZ4_ACCEL4")

        write_depth = runner.parse_write_pipeline_depth(synthetic_log())
        self.assertEqual(
            [row["write_pipeline_depth"] for row in write_depth],
            [2 if bit else 1 for bit in runner.CONFIRMATION_SEQUENCE])
        depth_diag = runner.write_pipeline_depth_verdict(write_depth)
        self.assertEqual(depth_diag["overall"],
                         "PASS_WRITE_PIPELINE_DEPTH_EVIDENCE", depth_diag)
        self.assertEqual(depth_diag["matched_pairs"], 5)
        self.assertEqual(depth_diag["modes"]["2"]["pipeline_active_max"], 2)

        delta64_pilot = runner.parse_delta64_prepare_sessions(synthetic_log())
        expected_workers = [2 if bit else 1
                            for bit in runner.CONFIRMATION_SEQUENCE]
        self.assertEqual([row["workers"] for row in delta64_pilot],
                         expected_workers)
        delta64_diag = runner.delta64_prepare_verdict(delta64_pilot)
        self.assertEqual(delta64_diag["overall"],
                         "PASS_DELTA64_PREPARE_AB", delta64_diag)
        self.assertEqual(delta64_diag["matched_pairs"], 5)
        self.assertEqual(delta64_diag["modes"]["1"]["prepare_parallel_starts"], 0)
        self.assertGreater(
            delta64_diag["modes"]["2"]["prepare_parallel_starts"], 0)
        self.assertGreater(
            delta64_diag["modes"]["2"]["prepare_active_max"], 1)
        self.assertIn("throughput_change_fraction", delta64_diag["paired"])

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
        self.assertEqual(len(sessions), 48)
        verdict = runner.write_saturation_verdict(sessions)
        self.assertEqual(verdict["overall"], "PASS_WRITE_SATURATION_EVIDENCE")
        self.assertAlmostEqual(
            verdict["model_limits"]["sd_emulated"]["effective_4k_model_ceiling_mbps"],
            4.096, places=3)
        self.assertAlmostEqual(
            verdict["model_limits"]["ssd_emulated"]["cap_decimal_mbps"],
            80 * (1 << 20) / 1_000_000.0, places=3)
        self.assertEqual(verdict["serial_qd32_matched_pairs"], 5)
        self.assertEqual(verdict["fast_qd8_matched_pairs"], 5)
        self.assertEqual(verdict["fast_qd32_matched_pairs"], 5)
        self.assertEqual(
            verdict["serial_qd32_paired"]["throughput_change_fraction"]["n"], 5)
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
        serial_qd32 = [p for p in verdict["regimes"]["sd_emulated"]
                       if p["qd"] == 32]
        self.assertEqual([p["observations"] for p in serial_qd32], [5, 5])
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

    def test_standard_write_only_policy_is_pinned(self):
        for field, value in (("lz4_acceleration", 2),
                              ("delta64_lz4_acceleration", 2),
                              ("write_pipeline_depth", 2),
                             ("delta64_rescue",
                              1 - runner.PRODUCTION_DELTA64_RESCUE)):
            sessions = runner.parse_write_saturation(synthetic_log())
            sessions[0]["arms"]["swapz"]["kernel_write_path"][field] = value
            with self.subTest(policy=field):
                self.assertEqual(
                    runner.write_saturation_verdict(sessions)["overall"],
                    "INCOMPLETE")

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
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_set_lookups"], 1024)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_set_hits"], 100)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_primary_hits"], 80)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_secondary_hits"], 20)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_set_probes"], 7700)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_set_replacements"], 12)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_copy_bytes"], 207200)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_full_extent_reqs"], 200)
        self.assertEqual(slow["columns"]["async"]["seeded_random_read_full_cache_hits"], 64)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_two_block_skips"], 128)
        self.assertEqual(slow["columns"]["sync"]["sequential_parallel_read_pairs"], 128)
        self.assertEqual(slow["columns"]["sync"]["sequential_parallel_read_same_extent_pairs"], 64)
        self.assertEqual(slow["columns"]["sync"]["sequential_parallel_read_async_batches"], 32)
        self.assertEqual(slow["columns"]["sync"]["sequential_parallel_read_async_slots"], 64)
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

    def test_two_choice_metadata_accounting_is_fail_closed(self):
        record = {"read_meta_set_lookups": 1024, "read_meta_set_hits": 100,
                  "read_meta_set_probes": 7700, "read_meta_primary_hits": 80,
                  "read_meta_secondary_hits": 20}
        self.assertTrue(runner.read_metadata_counters_consistent(record))
        for change in ({"read_meta_secondary_hits": 21}, {"read_meta_primary_hits": -1},
                       {"read_meta_set_hits": 1025}, {"read_meta_set_probes": 1800},
                       {"read_meta_set_probes": 8200}):
            self.assertFalse(runner.read_metadata_counters_consistent(dict(record, **change)))
        del record["read_meta_secondary_hits"]
        self.assertFalse(runner.read_metadata_counters_consistent(record))

    def test_submitter_preparation_accounting_is_fail_closed(self):
        record = timed_kernel_write(mode=1)
        record.update({
            "submitter_prepare": 1,
            "submitter_prepare_lanes": 8,
            "submitter_prepare_active": 0,
            "submitter_prepare_active_max": 4,
            "submitter_prepare_claims": 100,
            "submitter_prepare_lane_misses": 3,
            "submitter_prepare_page_misses": 2,
            "submitter_owner_deferrals": 7,
            "submitter_prepare_pages": 80,
            "submitter_prepare_wall_ns": 3000000,
            "submitter_prepare_cpu_ns": 2000000,
            "submitter_lz4_wall_ns": 1000000,
            "submitter_copy_wall_ns": 500000,
            "submitter_copy_bytes": 80 * 4096,
            "submitter_crc_wall_ns": 200000,
            "lz4_wall_ns": 21000000,
            "write_copy_wall_ns": 3500000,
        })
        self.assertIsNone(runner.timed_window_error(record))
        for invalid in (
                {"submitter_prepare": 0},
                {"submitter_prepare_lanes": 0},
                {"submitter_prepare_lanes": 9},
                {"submitter_prepare_active": 1},
                {"submitter_prepare_active_max": 9},
                {"submitter_prepare_pages": 101},
                {"submitter_copy_bytes": 1},
                {"submitter_prepare_wall_ns": 1000000},
                {"lz4_wall_ns": 20000000},
                {"write_copy_wall_ns": 3000000}):
            with self.subTest(invalid=invalid):
                self.assertIsNotNone(
                    runner.timed_window_error({**record, **invalid}))

        disabled = timed_kernel_write(mode=1)
        self.assertEqual(disabled["submitter_prepare"], 0)
        self.assertIsNone(runner.timed_window_error(disabled))
        disabled["submitter_prepare_claims"] = 1
        self.assertIsNotNone(runner.timed_window_error(disabled))

    def test_delta64_accounting_and_interpretation_are_fail_closed(self):
        record = timed_kernel_write(mode=1)
        self.assertIsNone(runner.timed_window_error(record))
        zero = {**record, **dict.fromkeys(runner.DELTA64_FIELDS, 0)}
        self.assertIsNone(runner.timed_window_error(zero))
        invalid_records = [
            {"delta64_classifier_pass": 11}, {"delta64_attempts": 6},
            {"delta64_adopted": 6}, {"delta64_raw_rescues": 2},
            {"delta64_payload_bytes_saved": 1201},
            {"delta64_raw_payload_bytes_saved": 527, "delta64_payload_bytes_saved": 727},
            {"delta64_lz4_payload_bytes_saved": 7135, "delta64_payload_bytes_saved": 8135},
            {"delta64_pack_attempts": 5}, {"delta64_pack_adopted": 2},
            {"delta64_pack_cliff_crossings": 6},
            {"delta64_score_0_7": 3},
            {"delta64_score_ge24": 6},
            {"delta64_wall_ns": -1}, {"delta64_eligible": True},
            {"delta64_rescue": 0}, {"delta64_rescue": 2},
        ]
        for invalid in invalid_records:
            with self.subTest(invalid=invalid):
                self.assertIsNotNone(runner.timed_window_error({**record, **invalid}))
        for field in runner.DELTA64_FIELDS:
            missing = dict(record)
            del missing[field]
            self.assertIsNotNone(runner.timed_window_error(missing))
        zero["delta64_rescue"] = 0
        self.assertIsNone(runner.timed_window_error(zero))
        missing = dict(zero)
        del missing["delta64_rescue"]
        self.assertIsNotNone(runner.timed_window_error(missing))
        headers = ("mode", "eligible", "passed", "attempts", "adopted", "RAW+", "LZ4+")
        interpretation = runner._table_interpretation(
            headers, [("async", "10", "0", "0", "0", "0", "0")])
        self.assertIn("No delta64 payload was adopted", interpretation)
        self.assertIn("no loaded delta64 savings evidence", interpretation)
        disabled_headers = ("mode", "rescue", *headers[1:])
        self.assertIn("disabled", runner._table_interpretation(
            disabled_headers, [("async", "off", "0", "0", "0", "0", "0", "0")]))
        self.assertIn("not committed mappings", runner._table_interpretation(
            headers, [("async", "10", "5", "5", "3", "1", "2")]))

    def test_product_interpretations_compare_against_raw(self):
        headers = ("mode", "W", "lower W", "W req", "R", "R p99")
        aligned = runner._table_interpretation(headers, [
            ("off", "10", "10", "100", "5", "2"),
            ("sync", "11", "7", "80", "5.2", "1.9"),
            ("async", "12", "7", "70", "5.5", "1.8"),
        ])
        self.assertIn("Directional project view vs raw: ALIGNED", aligned)
        self.assertIn("backing WRITE bytes/useful byte", aligned)
        self.assertIn("lower WRITE requests", aligned)
        tradeoff = runner._table_interpretation(headers, [
            ("off", "10", "10", "100", "5", "2"),
            ("sync", "10", "8", "90", "5", "2"),
            ("async", "9", "6", "70", "5.2", "1.8"),
        ])
        self.assertIn("Directional project view vs raw: TRADE-OFF", tradeoff)

        reads = runner._table_interpretation(
            ("read", "lower KiB", "req", "p99"),
            [("seq-off", "4096", "1024", "5"),
             ("seq-async", "3000", "800", "4"),
             ("rnd-off", "4096", "1024", "6"),
             ("rnd-async", "3500", "900", "5.5")])
        self.assertIn("Directional project view vs raw: ALIGNED", reads)
        self.assertIn("lower READ bytes", reads)

        sustained = runner._table_interpretation(
            ("QD", "raw", "sync", "async", "A/S", "A req"),
            [("4", "20", "15", "18", "+20%", "500"),
             ("8", "30", "20", "25", "+25%", "400")])
        self.assertIn("Directional performance view vs raw: NOT ALIGNED", sustained)
        self.assertIn("cannot turn a swapz result that still trails raw into a product win",
                      sustained)

        aligned_reasoning = runner._table_project_reasoning(
            "Fast QD32 mixed I/O throughput and latency",
            headers,
            [("off", "10", "10", "100", "5", "2"),
             ("sync", "11", "7", "80", "5.2", "1.9"),
             ("async", "12", "7", "70", "5.5", "1.8")],
            aligned)
        self.assertIn("Verdict: ALIGNED", aligned_reasoning)
        self.assertIn("host-write endurance proxy", aligned_reasoning)

        native_reasoning = runner._table_project_reasoning(
            "Ordinary LZ4 acceleration CPU and planner geometry — native corpus",
            ("accel", "ns/page"), [("1", "2400"), ("4", "2100")],
            "Acceleration 4 is faster natively.")
        self.assertIn("Verdict: SUPPORTING ONLY", native_reasoning)

        diagnostic_reasoning = runner._table_project_reasoning(
            "Fast mixed-I/O async pipeline wall-time attribution",
            ("stage", "busy ms"), [("LZ4", "5.0")],
            "LZ4=5 ms.")
        self.assertIn("Verdict: DIAGNOSTIC ONLY", diagnostic_reasoning)

        ci_reasoning = runner._table_project_reasoning(
            "Candidate paired 95% confidence intervals",
            ("metric", "mean", "low", "high"),
            [("W %", "+5", "+1", "+9"),
             ("lower req %", "-4", "-8", "-1")],
            "Project evidence from 95% intervals.")
        self.assertIn("Verdict: ALIGNED", ci_reasoning)

        limits_reasoning = runner._table_project_reasoning(
            "Qualification scope and evidence limitations",
            ("scope", "value"), [("media", "synthetic RAM only")],
            "Synthetic RAM only.")
        self.assertIn("Verdict: CLAIM BOUNDARY", limits_reasoning)

    def test_unqualified_console_does_not_bury_the_blocking_gate(self):
        report = {
            "overall": "BLOCKED",
            "stages": [
                {"status": "PASS"} for _ in range(4)
            ] + [{"status": "BLOCKED"}],
            "benchmarks": {"verdicts": {
                "overall": "INCOMPLETE",
                "reason": "sd_emulated: required counterbalanced sessions missing",
            }},
            "evidence": {
                "predictor": predictor_evidence(),
                "gc_scan_scale": gc_scan_scale_evidence(),
                "extent_geometry": extent_geometry_evidence(),
            },
        }
        with contextlib.redirect_stdout(io.StringIO()) as output:
            runner.print_bench(report)
        rendered = output.getvalue()
        self.assertIn("Stages passed: 4/5", rendered)
        self.assertIn("loaded service: NOT QUALIFIED", rendered)
        self.assertIn("sd_emulated: required counterbalanced sessions missing", rendered)
        self.assertIn("No new byte-exact loaded mixed/QD comparison", rendered)
        self.assertIn("Native diagnostics captured", rendered)
        self.assertNotIn("Predictive transform compression", rendered)
        self.assertNotIn("Simulated extent placement geometry", rendered)
        self.assertLess(len(rendered.splitlines()), 16)

    def test_delta64_rescue_accepts_real_submitter_preparation(self):
        # ID150 can own every prepared page. Exercise the same reporter
        # verdict on matched positive fixtures with background prep at zero.
        def sessions_with_submitter_preparation():
            sessions = runner.parse_delta64_rescue_sessions(synthetic_log())
            for session in sessions:
                if not session["rescue"]:
                    continue
                kernel = session["arms"]["swapz"]["kernel_write_path"]
                kernel.update({
                    "delta64_prepare_pages": 0,
                    "submitter_prepare": 1,
                    "submitter_prepare_lanes": 8,
                    "submitter_prepare_active": 0,
                    "submitter_prepare_active_max": 1,
                    "submitter_prepare_claims": 100,
                    "submitter_prepare_pages": 100,
                    "submitter_prepare_wall_ns": 100000,
                    "submitter_copy_wall_ns": 20000,
                    "submitter_copy_bytes": 100 * 4096,
                })
                kernel["write_copy_wall_ns"] += 20000
                kernel["write_copy_bytes"] += 100 * 4096
            return sessions

        sessions = sessions_with_submitter_preparation()
        self.assertEqual(
            runner.delta64_rescue_verdict(sessions)["overall"],
            "PASS_DELTA64_RESCUE_AB")
        # Neither placement path may make a zero-work rescue arm pass.
        for session in sessions:
            if session["rescue"]:
                kernel = session["arms"]["swapz"]["kernel_write_path"]
                kernel["submitter_prepare_pages"] = 0
                kernel["submitter_copy_bytes"] = 0
                kernel["submitter_copy_wall_ns"] = 0
                kernel["write_copy_bytes"] -= 100 * 4096
                kernel["write_copy_wall_ns"] -= 20000
        self.assertEqual(
            runner.delta64_rescue_verdict(sessions)["overall"],
            "INCOMPLETE")
        # Positive submitted pages with missing classifier/adoption evidence
        # still fail even though the submitter lane was active.
        sessions = sessions_with_submitter_preparation()
        for session in sessions:
            if session["rescue"]:
                session["arms"]["swapz"]["kernel_write_path"][
                    "delta64_adopted"] = 0
        self.assertEqual(
            runner.delta64_rescue_verdict(sessions)["overall"],
            "INCOMPLETE")
        # Existing global telemetry checks reject unowned/missing activity.
        sessions = sessions_with_submitter_preparation()
        for session in sessions:
            if session["rescue"]:
                session["arms"]["swapz"]["kernel_write_path"][
                    "submitter_prepare_claims"] = 0
        self.assertEqual(
            runner.delta64_rescue_verdict(sessions)["overall"],
            "INCOMPLETE")

    def test_benchmark_console_is_compact_and_keeps_sync_control(self):
        verdicts = runner.benchmark_verdicts(runner.parse_sessions(synthetic_log()))
        saturation = runner.write_saturation_verdict(
            runner.parse_write_saturation(synthetic_log()))
        report = {"evidence": {"predictor": predictor_evidence(),
                                "gc_scan_scale": gc_scan_scale_evidence(),
                                "extent_geometry": extent_geometry_evidence()},
                  "benchmarks": {
            "verdicts": verdicts,
            "parallel_read_ab": runner.parallel_read_ab_verdict(
                runner.parse_parallel_read_ab(synthetic_log())),
            "read_coalesce_ab": runner.read_coalesce_ab_verdict(
                runner.parse_read_coalesce_ab(synthetic_log())),
            "sd_read_coalesce_ab": runner.sd_read_coalesce_ab_verdict(
                runner.parse_sd_read_coalesce_ab(synthetic_log())),
            "lz4_acceleration": runner.lz4_acceleration_verdict(
                runner.parse_lz4_acceleration(synthetic_log())),
            "delta64_rescue": runner.delta64_rescue_verdict(
                runner.parse_delta64_rescue_sessions(synthetic_log())),
            "delta64_prepare": runner.delta64_prepare_verdict(
                runner.parse_delta64_prepare_sessions(synthetic_log())),
            "write_saturation": saturation,
            "loaded_correctness": runner.parse_loaded_correctness(synthetic_log()),
        }}
        # The operator view is short and puts the product control first.
        with contextlib.redirect_stdout(io.StringIO()) as summary:
            runner.print_bench(report)
        operator = summary.getvalue()
        self.assertIn("Product decision snapshot", operator)
        self.assertIn("Sustained lane-owned WRITE", operator)
        self.assertIn("accepted-work lower-idle", operator)
        self.assertIn("A/raw", operator)
        self.assertNotIn("Negative classifier profile breakdown", operator)
        self.assertIn("Directional performance view vs raw", operator)
        self.assertLess(len(operator.splitlines()), 160)

        # The diagnostic renderer stays under the existing strict Markdown contract.
        with contextlib.redirect_stdout(io.StringIO()) as output:
            runner.print_bench(report, detailed=True)
        rendered = output.getvalue()
        self.assertIn("Predictive-compression screening", rendered)
        self.assertIn("LZ4 acceleration 1 vs 4", rendered)
        self.assertIn("Acceleration 4 minus 1 paired 95% confidence intervals",
                      rendered)
        self.assertIn("Delta64 rescue off vs on", rendered)
        self.assertIn("Rescue on minus off paired 95% confidence intervals",
                      rendered)
        self.assertIn("Delta64 preparation K=1 vs K=2", rendered)
        self.assertIn("K=2 minus K=1 paired 95% confidence intervals",
                      rendered)
        self.assertIn("native corpus; not loaded attribution", rendered)
        self.assertIn("Production delta64 during mixed I/O", rendered)
        self.assertIn("payload KiB", rendered)
        self.assertIn("RAW+ KiB", rendered)
        self.assertIn("rescue ms", rendered)
        # Standard mixed sessions now run the production delta64 default; the
        # synthetic ordinary content adopts nothing, which must read as such.
        self.assertNotIn("Delta64 rescue is disabled", rendered)
        self.assertIn("No delta64 payload was adopted in these measured intervals",
                      rendered)
        self.assertNotIn("not kernel policy", rendered)
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
        self.assertIn("classifier sampling regressions", rendered)
        self.assertIn("shared production-route screening", rendered)
        self.assertIn("no loaded I/O proof", rendered)
        self.assertIn("Negative classifier profile breakdown", rendered)
        self.assertIn("delta64", rendered)
        self.assertIn("pack eligible", rendered)
        self.assertIn("score 0-7", rendered)
        readable = " ".join(rendered.split())
        for column in ("pack eligible", "pack try", "cliff", "pack+", "score 0-7",
                       "8-15", "16-23", "24+", "lookups", "set hit %",
                       "probes/lookup", "repl", "meta copy KiB", "primary %", "secondary %"):
            self.assertNotIn(f"literal column: {column}", readable)
        self.assertIn("excludes cache insertion copies", readable)
        self.assertIn("threshold 16", readable)
        self.assertIn("Secondary hits show use of the second choice", readable)
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
        self.assertIn("Metadata-cache locality", rendered)
        self.assertIn("probes/lookup", rendered)
        self.assertIn("meta copy KiB", rendered)
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
        self.assertIn("Independent lower-READ fan-out", rendered)
        self.assertIn("Fan-out on minus off paired 95% confidence intervals",
                      rendered)
        self.assertIn("Fan-out experiment raw-control drift", rendered)
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
        self.assertIn("ordered phase wall", rendered)
        self.assertIn("prep phase wall", rendered)
        self.assertIn("deferred C >1ms <=1.25/1.50/1.75/>", rendered)
        self.assertIn("CPU", rendered)
        self.assertIn("deferred C age <=250/500/1000/>", rendered)
        self.assertIn("deferred DL service L/R/B", rendered)
        self.assertIn("Mixed window bins; close=P/D/I", rendered)
        self.assertIn("Routed delta64 CPU economics", rendered)
        self.assertIn("elapsed-time model", rendered)
        self.assertIn("not a demonstrated speedup", rendered)
        self.assertIn("Delta64 selected backends", rendered)
        self.assertIn("LZ4 ns", rendered)
        self.assertNotIn("LZ4-2 ns", rendered)
        self.assertIn("Directional project view vs raw", rendered)
        self.assertIn("backing WRITE bytes/useful byte", rendered)
        self.assertIn("Directional performance view vs raw", rendered)
        self.assertIn("Project evidence from 95% intervals", rendered)
        self.assertNotIn("dry-close followups", rendered)
        self.assertIn("direct LZ4 input", rendered)
        self.assertIn("Lifecycle", rendered)
        self.assertIn("retained WRITE/FLUSH failed closed", rendered)
        self.assertIn("WRITE-ONLY SUSTAINED-QD EVIDENCE", rendered)
        self.assertIn("Persistent lane workers", rendered)
        self.assertIn("Serial QD32 A/S paired 95% CI", rendered)
        self.assertIn("Fast QD4 A/S paired 95% CI", rendered)
        self.assertIn("Fast QD8 A/S paired 95% CI", rendered)
        self.assertIn("Fast QD32 A/S paired 95% CI", rendered)
        self.assertIn(
            "five pairs at fast QD4/8/32 and serial QD32; QD1 is directional",
            rendered)
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
        # a bold self-contained title, unindented GFM pipe syntax, explicit
        # left alignment with >=3 separator dashes per column, then the legend,
        # interpretation, and a literal horizontal rule.
        lines = rendered.splitlines()

        def is_left_aligned_separator(cell):
            cell = cell.strip()
            return (cell.startswith(":") and len(cell[1:]) >= 3 and
                    set(cell[1:]) <= {"-"})

        table_starts = [
            index for index in range(len(lines) - 1)
            if lines[index].startswith("| ") and
            lines[index + 1].startswith("| ") and
            all(is_left_aligned_separator(cell)
                for cell in lines[index + 1].strip("|").split("|"))
        ]
        self.assertGreater(len(table_starts), 10)
        self.assertEqual(rendered.count("  Legend:"), len(table_starts))
        self.assertEqual(rendered.count("  Interpretation:"), len(table_starts))
        self.assertEqual(rendered.count("  Project reasoning:"), len(table_starts))
        self.assertIn("  Goal chain:", rendered)
        self.assertIn("  Endurance scope:", rendered)
        self.assertIn("host-I/O endurance proxy", rendered)
        self.assertEqual(
            sum(line.startswith("**") and line.endswith("**") for line in lines),
            len(table_starts))
        for start in table_starts:
            self.assertGreater(start, 0)
            self.assertRegex(lines[start - 1], r"^\*\*\S.+\S\*\*$")
            # GFM alignment cells are at least four characters wide (:---).
            # Keep every divider pipe at the same terminal column as the
            # header, including narrow columns such as W, R, 1 and 2.
            header_pipes = [pos for pos, char in enumerate(lines[start])
                            if char == "|"]
            divider_pipes = [pos for pos, char in enumerate(lines[start + 1])
                             if char == "|"]
            self.assertEqual(divider_pipes, header_pipes)
            index = start + 2
            while index < len(lines) and lines[index].startswith("| "):
                index += 1
            self.assertLess(index, len(lines))
            self.assertTrue(lines[index].startswith("  Legend:"))
            legend_lines = [lines[index]]
            index += 1
            while index < len(lines) and lines[index].startswith("    "):
                legend_lines.append(lines[index])
                index += 1
            legend_text = " ".join(line.strip() for line in legend_lines)
            headers = [cell.strip() for cell in lines[start].strip("|").split("|")]
            for header in headers:
                self.assertIn(f"{header}:", legend_text)
                goal = runner.TABLE_HEADER_GOAL.get(header)
                if goal:
                    self.assertIn(f"[{goal}]", legend_text)
            self.assertNotIn("goal:", legend_text)
            self.assertLess(index, len(lines))
            self.assertTrue(lines[index].startswith("  Interpretation:"))
            index += 1
            while index < len(lines) and lines[index].startswith("    "):
                index += 1
            self.assertLess(index, len(lines))
            self.assertTrue(lines[index].startswith("  Project reasoning:"))
            reasoning_lines = [lines[index]]
            index += 1
            while index < len(lines) and lines[index].startswith("    "):
                reasoning_lines.append(lines[index])
                index += 1
            reasoning_text = " ".join(line.strip() for line in reasoning_lines)
            self.assertIn("Evidence:", reasoning_text)
            self.assertIn("Goal implication:", reasoning_text)
            self.assertIn("Verdict:", reasoning_text)
            self.assertLess(index, len(lines))
            self.assertEqual(lines[index], "---")
        self.assertNotRegex(rendered, r"(?m)^  \|")
        longest = max(lines, key=len)
        self.assertLess(len(longest), 96, longest)

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

    def test_retired_lz4_ab_does_not_gate_overall_qualification(self):
        benchmarks = {
            "verdicts": {"overall": "PASS_BOUNDED_RAM_MATRIX"},
            "write_saturation": {"overall": "PASS_WRITE_SATURATION_EVIDENCE"},
            "lz4_acceleration": {
                "overall": "NOT_RUN",
                "reason": "retired; ordinary LZ4 is fixed at acceleration 1",
            },
        }
        self.assertTrue(runner.required_benchmark_gates_pass(benchmarks))
        benchmarks["verdicts"]["overall"] = "INCONCLUSIVE"
        self.assertFalse(runner.required_benchmark_gates_pass(benchmarks))
        benchmarks["verdicts"]["overall"] = "PASS_BOUNDED_RAM_MATRIX"
        benchmarks["write_saturation"]["overall"] = "INCOMPLETE"
        self.assertFalse(runner.required_benchmark_gates_pass(benchmarks))

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

    def test_id36_resource_pressure_is_required_and_fail_closed(self):
        evidence = runner.parse_loaded_correctness(synthetic_log())
        self.assertEqual(evidence["overall"], "PASS", evidence)
        self.assertEqual(evidence["id36_pressure_mib"], 576)
        self.assertGreater(evidence["id36_memory_high_events"], 0)
        self.assertGreater(evidence["id36_cpu_some_usec"], 0)

        missing = synthetic_log().replace(
            "PASS_ID36_RESOURCE_PRESSURE=memory_high_events:8 "
            "memory_peak_bytes:734003200 cpu_some_usec:250000 cpu_workers:8 "
            "pressure_mib:576 oom:0 oom_kill:0\n", "", 1)
        diagnostic = runner.parse_loaded_correctness(missing)
        self.assertEqual(diagnostic["overall"], "INCOMPLETE")
        self.assertIn("id36", diagnostic["reason"].lower())

        oom = synthetic_log().replace(
            "pressure_mib:576 oom:0 oom_kill:0",
            "pressure_mib:576 oom:1 oom_kill:0", 1)
        diagnostic = runner.parse_loaded_correctness(oom)
        self.assertEqual(diagnostic["overall"], "INCOMPLETE")
        self.assertIn("ID36", diagnostic["reason"])

    def test_retired_parallel_read_diagnostic_is_observational(self):
        broken = synthetic_log().replace("PASS_PARALLEL_READ_AB=1\n", "", 1)
        fake_process = FakeStreamingProcess(broken)
        original_popen = runner.subprocess.Popen
        report = {"schema": "swapz-test-results-v1", "stages": [],
                  "benchmarks": {"sessions": [], "verdicts": {}}}
        try:
            runner.subprocess.Popen = lambda *args, **kwargs: fake_process
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    runner.run_stage("Owned RAM smoke and pairs",
                                     ["unused"], report, parse_bench=True), 0)
        finally:
            runner.subprocess.Popen = original_popen
        stage = report["stages"][-1]
        self.assertEqual(stage["status"], "PASS")
        diagnostic = report["benchmarks"]["parallel_read_ab"]
        self.assertEqual(diagnostic["overall"], "INCOMPLETE")
        self.assertIn("five counterbalanced matched rounds",
                      diagnostic["reason"])

    def test_read_coalesce_diagnostic_failure_reports_its_own_reason(self):
        broken = synthetic_log().replace("PASS_READ_COALESCE_AB=1\n", "", 1)
        fake_process = FakeStreamingProcess(broken)
        original_popen = runner.subprocess.Popen
        report = {"schema": "swapz-test-results-v1", "stages": [],
                  "benchmarks": {"sessions": [], "verdicts": {}}}
        try:
            runner.subprocess.Popen = lambda *args, **kwargs: fake_process
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    runner.run_stage("Owned RAM smoke and 8 pairs",
                                     ["unused"], report, parse_bench=True), 1)
        finally:
            runner.subprocess.Popen = original_popen
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

        discard_trim = (
            "START_LOADED_OWNED_NULLBLK_SMOKE\n"
            "START_LOADED_DISCARD_TRIM\n"
            "FAIL: owned upper DISCARD failed\n"
        )
        phase, reason = runner.failure_context(discard_trim)
        self.assertIn("discard-time TRIM reclamation", phase)
        self.assertIn("owned upper DISCARD failed", reason)

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

    def test_loaded_quarantine_reports_specific_sanitized_reason(self):
        log = (
            "START_OWNED_RAM_REGIME=sd_emulated\n"
            "START_OWNED_RAM_PAIR_ASYNC_PREPARE=0\n"
            "QUARANTINED: owned DM removal failed open:1->1\n"
            "BLOCKED: retain all remaining resources for read-only investigation\n"
        )
        phase, reason = runner.failure_context(log)
        self.assertIn("sd_emulated comparison 1/8 (sync)", phase)
        self.assertEqual(
            reason, "Safety quarantine: owned DM removal failed open:1->1")

    def test_native_failure_identifies_sanitized_helper_error(self):
        log = "predictor sampling/route control failed: -117\n"
        phase, reason = runner.failure_context(
            log, loaded=False, default_phase="Native and rootless contracts")
        self.assertEqual(phase, "Native and rootless contracts")
        self.assertEqual(reason,
                         "Native helper: predictor sampling/route control failed: -117")

        compiler = "/home/private/build/predictor.c:10: error: signedness mismatch\n"
        _, reason = runner.failure_context(
            compiler, loaded=False, default_phase="Native and rootless contracts")
        self.assertEqual(reason, "Native build error: signedness mismatch")

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
            git("init", "--object-format=sha1", "--bare", str(origin), cwd=sandbox)
            git("init", "--object-format=sha1", cwd=checkout)
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
            git("init", "--object-format=sha1", cwd=checkout)
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
            git("init", "--object-format=sha1", "--bare", str(origin), cwd=sandbox)
            git("init", "--object-format=sha1", cwd=checkout)
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

    def test_git_sync_declines_older_source_when_newer_evidence_published(self):
        """Do not overwrite origin/main when it already carries newer qualification evidence."""
        import subprocess
        from unittest import mock

        def git(*args, cwd, check=True):
            return subprocess.run(["git", *args], cwd=cwd, check=check,
                                  capture_output=True, text=True, timeout=12)

        with tempfile.TemporaryDirectory(
                prefix="report-monotonic-", dir=ROOT / "build/tests") as name:
            sandbox = Path(name)
            checkout, origin, peer = (
                sandbox / "checkout", sandbox / "origin.git", sandbox / "peer")
            checkout.mkdir()
            git("init", "--object-format=sha1", "--bare", str(origin), cwd=sandbox)
            git("init", "--object-format=sha1", cwd=checkout)
            git("checkout", "-b", "main", cwd=checkout)
            git("config", "user.name", "test-report CI", cwd=checkout)
            git("config", "user.email", "test@example.invalid", cwd=checkout)
            (checkout / "source.c").write_text("v1 source\n")
            (checkout / runner.GIT_RESULT).write_text(
                '{"overall":"NOT_RUN"}\n', encoding="utf-8")
            git("add", "source.c", runner.GIT_RESULT, cwd=checkout)
            git("commit", "-m", "Older source C1", cwd=checkout)
            c1_sha = git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
            git("remote", "add", "origin", str(origin), cwd=checkout)
            git("push", "origin", "main", cwd=checkout)

            git("clone", "-b", "main", str(origin), str(peer), cwd=sandbox)
            git("config", "user.name", "newer tester", cwd=peer)
            git("config", "user.email", "tester@example.invalid", cwd=peer)
            (peer / "source.c").write_text("v2 source\n")
            git("add", "source.c", cwd=peer)
            git("commit", "-m", "Newer source C2", cwd=peer)
            c2_sha = git("rev-parse", "HEAD", cwd=peer).stdout.strip()

            newer_report = {
                "schema": "swapz-test-results-v1",
                "source_sha": c2_sha,
                "tested_commit_sha": c2_sha,
                "overall": "PASS",
            }
            (peer / runner.GIT_RESULT).write_text(
                json.dumps(newer_report) + "\n", encoding="utf-8")
            git("add", runner.GIT_RESULT, cwd=peer)
            git("commit", "-m", f"test: latest run for {c2_sha[:12]} [skip ci]",
                cwd=peer)
            peer_report_sha = git("rev-parse", "HEAD", cwd=peer).stdout.strip()
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
                    older_report = {
                        "schema": "swapz-test-results-v1",
                        "source_sha": c1_sha,
                        "tested_commit_sha": c1_sha,
                        "overall": "PASS",
                    }
                    runner.write_report(older_report)
                    notice = runner.publish(c1_sha)
                    self.assertEqual(
                        notice,
                        f"SKIPPED_GIT_SYNC: newer-source qualification evidence "
                        f"already published ({c2_sha[:12]})")

                    remote_head = git("--git-dir", str(origin), "rev-parse",
                                      "refs/heads/main",
                                      cwd=sandbox).stdout.strip()
                    self.assertEqual(remote_head, peer_report_sha)
            finally:
                runner.ROOT, runner.REPORT = old_root, old_report

    def test_git_sync_fails_closed_when_merge_base_errors(self):
        """Fail closed when git merge-base encounters an error checking remote evidence."""
        import subprocess
        from unittest import mock

        def git(*args, cwd, check=True):
            return subprocess.run(["git", *args], cwd=cwd, check=check,
                                  capture_output=True, text=True, timeout=12)

        with tempfile.TemporaryDirectory(
                prefix="report-monotonic-error-", dir=ROOT / "build/tests") as name:
            sandbox = Path(name)
            checkout, origin, peer = (
                sandbox / "checkout", sandbox / "origin.git", sandbox / "peer")
            checkout.mkdir()
            git("init", "--object-format=sha1", "--bare", str(origin), cwd=sandbox)
            git("init", "--object-format=sha1", cwd=checkout)
            git("checkout", "-b", "main", cwd=checkout)
            git("config", "user.name", "test-report CI", cwd=checkout)
            git("config", "user.email", "test@example.invalid", cwd=checkout)
            (checkout / "source.c").write_text("v1 source\n")
            (checkout / runner.GIT_RESULT).write_text(
                '{"overall":"NOT_RUN"}\n', encoding="utf-8")
            git("add", "source.c", runner.GIT_RESULT, cwd=checkout)
            git("commit", "-m", "Older source C1", cwd=checkout)
            c1_sha = git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
            git("remote", "add", "origin", str(origin), cwd=checkout)
            git("push", "origin", "main", cwd=checkout)

            git("clone", "-b", "main", str(origin), str(peer), cwd=sandbox)
            git("config", "user.name", "newer tester", cwd=peer)
            git("config", "user.email", "tester@example.invalid", cwd=peer)
            (peer / "source.c").write_text("v2 source\n")
            git("add", "source.c", cwd=peer)
            git("commit", "-m", "Newer source C2", cwd=peer)
            c2_sha = git("rev-parse", "HEAD", cwd=peer).stdout.strip()

            newer_report = {
                "schema": "swapz-test-results-v1",
                "source_sha": c2_sha,
                "tested_commit_sha": c2_sha,
                "overall": "PASS",
            }
            (peer / runner.GIT_RESULT).write_text(
                json.dumps(newer_report) + "\n", encoding="utf-8")
            git("add", runner.GIT_RESULT, cwd=peer)
            git("commit", "-m", f"test: latest run for {c2_sha[:12]} [skip ci]",
                cwd=peer)
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
                if len(command) == 4 and command[:2] == ["merge-base", "--is-ancestor"] and command[3] == c2_sha:
                    return subprocess.CompletedProcess(
                        command, 128,
                        stdout=b"",
                        stderr=b"fatal: simulated git merge-base error")
                return old_git_result(command, data=data, timeout=timeout,
                                      env=env)

            try:
                with mock.patch.object(runner, "git_result",
                                       side_effect=intercept):
                    older_report = {
                        "schema": "swapz-test-results-v1",
                        "source_sha": c1_sha,
                        "tested_commit_sha": c1_sha,
                        "overall": "PASS",
                    }
                    runner.write_report(older_report)
                    notice = runner.publish(c1_sha)
                    self.assertEqual(
                        notice,
                        "GIT_SYNC_FAILED: git merge-base failed while "
                        "evaluating remote qualification evidence")
            finally:
                runner.ROOT, runner.REPORT = old_root, old_report

    def test_git_sync_allows_newer_source_over_older_evidence(self):
        """Allow publishing newer qualification evidence over older published evidence."""
        import subprocess
        from unittest import mock

        def git(*args, cwd, check=True):
            return subprocess.run(["git", *args], cwd=cwd, check=check,
                                  capture_output=True, text=True, timeout=12)

        with tempfile.TemporaryDirectory(
                prefix="report-monotonic-newer-", dir=ROOT / "build/tests") as name:
            sandbox = Path(name)
            checkout, origin, peer = (
                sandbox / "checkout", sandbox / "origin.git", sandbox / "peer")
            checkout.mkdir()
            git("init", "--object-format=sha1", "--bare", str(origin), cwd=sandbox)
            git("init", "--object-format=sha1", cwd=checkout)
            git("checkout", "-b", "main", cwd=checkout)
            git("config", "user.name", "test-report CI", cwd=checkout)
            git("config", "user.email", "test@example.invalid", cwd=checkout)
            (checkout / "source.c").write_text("v0 source\n")
            git("add", "source.c", cwd=checkout)
            git("commit", "-m", "Base source C0", cwd=checkout)
            c0_sha = git("rev-parse", "HEAD", cwd=checkout).stdout.strip()

            (checkout / "source.c").write_text("v1 source\n")
            older_report = {
                "schema": "swapz-test-results-v1",
                "source_sha": c0_sha,
                "tested_commit_sha": c0_sha,
                "overall": "PASS",
            }
            (checkout / runner.GIT_RESULT).write_text(
                json.dumps(older_report) + "\n", encoding="utf-8")
            git("add", "source.c", runner.GIT_RESULT, cwd=checkout)
            git("commit", "-m", "Older source C1 with old report", cwd=checkout)
            c1_sha = git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
            git("remote", "add", "origin", str(origin), cwd=checkout)
            git("push", "origin", "main", cwd=checkout)

            # Checkout advances to C2 (tested commit)
            (checkout / "source.c").write_text("v2 source\n")
            git("add", "source.c", cwd=checkout)
            git("commit", "-m", "Newer source C2", cwd=checkout)
            c2_sha = git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
            git("push", "origin", "main", cwd=checkout)

            # Peer clones and adds a concurrent docs commit C3 on top of C2
            git("clone", "-b", "main", str(origin), str(peer), cwd=sandbox)
            git("config", "user.name", "concurrent committer", cwd=peer)
            git("config", "user.email", "committer@example.invalid", cwd=peer)
            (peer / "README.md").write_text("concurrent doc\n")
            git("add", "README.md", cwd=peer)
            git("commit", "-m", "Concurrent doc commit C3", cwd=peer)
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
                    newer_report = {
                        "schema": "swapz-test-results-v1",
                        "source_sha": c2_sha,
                        "tested_commit_sha": c2_sha,
                        "overall": "PASS",
                    }
                    runner.write_report(newer_report)
                    notice = runner.publish(c2_sha)
                    self.assertIn("SYNCED_GIT", notice)

                    remote_report = json.loads(
                        git("--git-dir", str(origin), "show",
                            f"refs/heads/main:{runner.GIT_RESULT}",
                            cwd=sandbox).stdout)
                    self.assertEqual(remote_report["tested_commit_sha"], c2_sha)
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
            git("init", "--object-format=sha1", "--bare", str(origin), cwd=sandbox)
            git("init", "--object-format=sha1", cwd=checkout)
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
