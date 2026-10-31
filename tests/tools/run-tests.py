#!/usr/bin/env python3
"""Private make test runner: one bounded, replace-in-place, sanitized report."""
import argparse
import hashlib
import json
import math
import os
import re
from pathlib import Path
import statistics
import subprocess
import sys
import textwrap
import time

ROOT = Path(__file__).resolve().parents[2]
GIT_RESULT = "test_results.json"
REPORT = ROOT / GIT_RESULT
HOST_CPU_INT_FIELDS = ("wall_ns", "online_cpus", "affinity_cpus", "tick_hz")
HOST_CPU_FLOAT_FIELDS = ("busy_fraction", "steal_fraction", "pressure_some_fraction")
HOST_CPU_FIELDS = HOST_CPU_INT_FIELDS + HOST_CPU_FLOAT_FIELDS
REPO = "k1moradi/swapz"
COLUMNS = ("off", "sync", "async")
# Cap values are kernel null_blk MiB/s units; request delay is nanoseconds.
# Labels describe SYNTHETIC profiles, never a real SD/SSD device.
MODEL_SPECS = {
    "sd_emulated": {"cap_mib_s": 10, "completion_nsec": 1000000, "irqmode": 2,
                    "queue_mode": 2, "submit_queues": 1, "hw_queue_depth": 1,
                    "purpose": "SYNTHETIC_LOW_BANDWIDTH_HIGH_DELAY_SERIAL_DEPTH1"},
    "ssd_emulated": {"cap_mib_s": 80, "completion_nsec": 150000, "irqmode": 2,
                     "queue_mode": 2, "submit_queues": 1, "hw_queue_depth": 64,
                     "purpose": "SYNTHETIC_HIGHER_BANDWIDTH_LOWER_DELAY_QUEUED_DEPTH64"},
}
MODEL_ORDER = tuple(MODEL_SPECS)
# Directional service envelopes answer a different question from the retained
# slow/fast qualification pair: where does saved lower I/O stop translating
# into useful service as storage latency falls and queue capability rises?
# They remain null_blk models, never physical-device claims.
STORAGE_ENVELOPE_SPECS = {
    "sd_card": {"cap_mib_s": 100, "completion_nsec": 500000, "irqmode": 2,
                "queue_mode": 2, "submit_queues": 1, "hw_queue_depth": 4,
                "purpose": "SYNTHETIC_MODERN_SD_SERVICE_ENVELOPE"},
    "sata_ssd": {"cap_mib_s": 500, "completion_nsec": 100000, "irqmode": 2,
                 "queue_mode": 2, "submit_queues": 1, "hw_queue_depth": 32,
                 "purpose": "SYNTHETIC_MODERN_SATA_SERVICE_ENVELOPE"},
    "nvme_gen4": {"cap_mib_s": 6500, "completion_nsec": 25000, "irqmode": 2,
                  "queue_mode": 2, "submit_queues": 4, "hw_queue_depth": 64,
                  "purpose": "SYNTHETIC_GEN4_NVME_SERVICE_ENVELOPE"},
    "nvme_gen5": {"cap_mib_s": 12000, "completion_nsec": 14000, "irqmode": 2,
                  "queue_mode": 2, "submit_queues": 4, "hw_queue_depth": 64,
                  "purpose": "SYNTHETIC_GEN5_NVME_SERVICE_ENVELOPE"},
}
STORAGE_ENVELOPE_ORDER = tuple(STORAGE_ENVELOPE_SPECS)
# Five adjacent matched rounds with mode order alternated between rounds.
CONFIRMATION_SEQUENCE = (0, 1, 1, 0, 0, 1, 1, 0, 0, 1)
# Five balanced three-arm rounds. Each consecutive triplet contains 2/4/8
# exactly once so within-round pairwise deltas remain matched.
READ_COALESCE_CAP_SEQUENCE = (
    2, 4, 8,
    4, 8, 2,
    8, 2, 4,
    2, 8, 4,
    4, 2, 8,
)
PAIRED_CI95_T_N5 = 2.7764451051977987
LOGICAL_BLOCK_BYTES = 4096


def device_model_limits(spec, offered_qd=None):
    """Analytical null_blk cap and unmerged 4KiB latency ceiling.

    A workload cannot consume hardware depth that it does not offer. Historical
    qualification calls omit offered_qd to preserve the existing model record;
    modern storage-envelope diagnostics pass QD32 explicitly.
    """
    cap_mbps = spec["cap_mib_s"] * (1 << 20) / 1_000_000.0
    available_depth = spec["submit_queues"] * spec["hw_queue_depth"]
    effective_depth = available_depth
    if offered_qd is not None:
        effective_depth = min(effective_depth, offered_qd)
    latency_mbps = (LOGICAL_BLOCK_BYTES * effective_depth *
                    1_000_000_000.0 / spec["completion_nsec"] / 1_000_000.0)
    return {
        "cap_decimal_mbps": cap_mbps,
        "effective_queue_depth": effective_depth,
        "unmerged_4k_latency_ceiling_mbps": latency_mbps,
        "effective_4k_model_ceiling_mbps": min(cap_mbps, latency_mbps),
    }


def paired_ci95(values):
    if len(values) != 5 or any(not isinstance(value, (int, float))
                               for value in values):
        raise ValueError("five numeric matched deltas required")
    center = statistics.mean(values)
    half_width = PAIRED_CI95_T_N5 * statistics.stdev(values) / math.sqrt(5)
    return {
        "n": 5,
        "mean": center,
        "low": center - half_width,
        "high": center + half_width,
    }


def matched_binary_pairs(rows, field):
    if len(rows) != len(CONFIRMATION_SEQUENCE) or \
            [row.get(field) for row in rows] != list(CONFIRMATION_SEQUENCE):
        raise ValueError("five counterbalanced matched rounds required")
    pairs = []
    for index in range(0, len(rows), 2):
        first, second = rows[index:index + 2]
        pairs.append({
            first[field]: first,
            second[field]: second,
        })
    return pairs


def matched_value_pairs(rows, field, low, high):
    expected = [high if bit else low for bit in CONFIRMATION_SEQUENCE]
    if len(rows) != len(expected) or \
            [row.get(field) for row in rows] != expected:
        raise ValueError(
            f"five counterbalanced {low}/{high} matched rounds required")
    pairs = []
    for index in range(0, len(rows), 2):
        first, second = rows[index:index + 2]
        pair = {first[field]: first, second[field]: second}
        if set(pair) != {low, high}:
            raise ValueError("matched pair does not contain both settings")
        pairs.append(pair)
    return pairs

CLOSE_REASON_LABELS = (
    ("close_unknown", "unknown"), ("close_full", "full"),
    ("close_duplicate", "duplicate"), ("close_zero", "zero"),
    ("close_fua", "fua"), ("close_raw", "raw"),
    ("close_read_conflict", "read-conflict"),
    ("close_read_unrelated", "read-unrelated"),
    ("close_discard", "discard"), ("close_preflush", "preflush"),
    ("close_quantum", "quantum"), ("close_idle", "idle"),
    ("close_shutdown", "shutdown"), ("close_other", "other"),
    ("close_deadline", "deadline"), ("close_pack_ready", "pack-ready"),
)
CLOSE_REASON_FIELDS = tuple(field for field, _ in CLOSE_REASON_LABELS)
ONE_PAGE_CLOSE_LABELS = (
    ("win1_unknown", "unknown"), ("win1_full", "full"),
    ("win1_duplicate", "duplicate"), ("win1_zero", "zero"),
    ("win1_fua", "fua"), ("win1_raw", "raw"),
    ("win1_read_conflict", "read-conflict"),
    ("win1_read_unrelated", "read-unrelated"),
    ("win1_discard", "discard"), ("win1_preflush", "preflush"),
    ("win1_quantum", "quantum"), ("win1_idle", "idle"),
    ("win1_shutdown", "shutdown"), ("win1_other", "other"),
    ("win1_deadline", "deadline"), ("win1_pack_ready", "pack-ready"),
)
ONE_PAGE_CLOSE_FIELDS = tuple(field for field, _ in ONE_PAGE_CLOSE_LABELS)
WIN1_PACK_CAUSE_FIELDS = (
    "win1_pack_tail_target", "win1_pack_read_bypass",
    "win1_pack_wave_interrupted")
SINGLE_TAIL_FIELDS = (
    "single_tail_deferrals", "single_tail_companions",
    "win1_deadline_deferred_tail", "win1_idle_deferred_tail",
    "single_tail_other_clears")
SINGLE_TAIL_TIMING_FIELDS = (
    "single_tail_comp_age_le250us", "single_tail_comp_age_251_500us",
    "single_tail_comp_age_501_1000us", "single_tail_comp_age_gt1000us",
    "single_tail_deadline_age_le250us", "single_tail_deadline_age_251_500us",
    "single_tail_deadline_age_501_1000us", "single_tail_deadline_age_gt1000us")
SINGLE_TAIL_COMP_UPPER_FIELDS = (
    "single_tail_comp_age_1001_1250us",
    "single_tail_comp_age_1251_1500us",
    "single_tail_comp_age_1501_1750us",
    "single_tail_comp_age_gt1750us")
SINGLE_TAIL_SERVICE_FIELDS = (
    "single_tail_comp_after_lower_done", "single_tail_comp_after_read_bypass",
    "single_tail_comp_after_both", "single_tail_deadline_after_lower_done",
    "single_tail_deadline_after_read_bypass", "single_tail_deadline_after_both")
ID52_FIELDS = (
    SINGLE_TAIL_TIMING_FIELDS + SINGLE_TAIL_COMP_UPPER_FIELDS +
    SINGLE_TAIL_SERVICE_FIELDS)
PACK_CLOSE_FIELDS = (
    "pack_close_tail_target", "pack_close_tail_target_le4",
    "pack_close_burst_target", "pack_close_service_dry")
SMALL_TAIL_CLOSE_FIELDS = (
    "pack_close_tail_target_2", "pack_close_tail_target_3",
    "pack_close_tail_target_4")
BURST_CLOSE_DETAIL_FIELDS = (
    "pack_close_burst_admission", "pack_close_burst_worker",
    "pack_close_burst_target_le4", "pack_close_burst_target_5_8",
    "pack_close_burst_target_9_16", "pack_close_burst_target_17_64",
    "pack_close_burst_count_le4", "pack_close_burst_count_5_8",
    "pack_close_burst_count_9_16", "pack_close_burst_count_17_64",
    "pack_close_burst_overshoot")
TAIL_SAMPLE_FIELDS = (
    "pack_tail_samples", "pack_tail_zero_inflight", "pack_tail_zero_idle",
    "pack_tail_one_inflight", "pack_tail_one_idle",
    "pack_tail_many_inflight", "pack_tail_many_idle",
    "burst_target_grows", "burst_target_shrinks",
    "burst_shrink_inflight_zero_skips",
    "burst_shrink_after_inflight_zero", "burst_shrink_after_read_bypass",
    "burst_shrink_other", "burst_shrink_target_le8",
    "burst_shrink_target_9_32", "burst_shrink_target_gt32")
K1_READY_WAIT_FIELDS = (
    "k1_ready_wait_windows", "k1_ready_wait_records",
    "k1_ready_wait_wall_ns", "k1_ready_wait_max_records",
    "k1_ready_wait_pack_ready", "k1_ready_wait_full",
    "k1_ready_wait_deadline", "k1_ready_wait_fence",
    "k1_ready_wait_other")
PACK_CLOSE_PRIMARY_FIELDS = (
    "pack_close_tail_target", "pack_close_burst_target",
    "pack_close_service_dry")
DEADLINE_CONTEXT_LABELS = (
    ("deadline_before_bio", "before-bio"),
    ("deadline_after_read", "after-read"),
    ("deadline_worker_with_local", "worker-local"),
    ("deadline_worker_empty", "worker-empty"),
)
DEADLINE_CONTEXT_FIELDS = tuple(field for field, _ in DEADLINE_CONTEXT_LABELS)
KERNEL_READ_FIELDS = ("read_meta_reqs", "read_payload_reqs",
                      "read_payload_blocks", "lower_read_wall_ns",
                      "decode_wall_ns", "read_copy_wall_ns",
                      "read_copy_bytes", "read_engine_nonio_wall_ns",
                      "read_meta_cache_hits", "read_meta_lru_hits",
                      "read_meta_set_lookups", "read_meta_set_hits",
                      "read_meta_set_probes", "read_meta_set_replacements",
                      "read_meta_primary_hits", "read_meta_secondary_hits",
                      "read_meta_copy_bytes",
                      "read_full_extent_reqs", "read_full_cache_hits",
                      "read_two_block_skips", "parallel_read_pairs",
                      "parallel_read_same_extent_pairs",
                      "parallel_read_async_batches",
                      "parallel_read_async_slots",
                      "parallel_read_distinct_extent_pairs",
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
                      "read_worker_cpu_ns",
                      "read_coalesce_max_blocks")


def read_metadata_counters_consistent(record):
    fields = ("read_meta_set_lookups", "read_meta_set_hits", "read_meta_set_probes",
              "read_meta_primary_hits", "read_meta_secondary_hits")
    if not isinstance(record, dict) or any(
            type(record.get(field)) is not int or record[field] < 0 for field in fields):
        return False
    lookups, hits, probes, primary, secondary = (record[field] for field in fields)
    if hits > lookups or primary + secondary != hits:
        return False
    misses = lookups - hits
    return (primary + 5 * secondary + 8 * misses <= probes <=
            4 * primary + 8 * secondary + 8 * misses)


WRITE_WAIT_BINS = ("write_wait_le1ms", "write_wait_1to4ms",
                   "write_wait_gt4ms")
PREPARATION_FIELDS = (
    "prep_lower_write_overlap_starts", "prep_lower_read_overlap_starts",
    "prep_wave_kicks",
    "prep_producer_head_claims", "prep_producer_tail_claims",
    "prep_ordered_inline", "prep_ordered_handoffs", "prep_ordered_waits",
    "prep_ordered_raw")
WINDOW_SIZE_FIELDS = (
    "windows", "one_page_windows", "win1", "win2", "win3_4", "win5_8",
    "win9_16", "win17_64")
BURST_COUNTER_FIELDS = (
    "packed_early_commits", "single_pack_deferrals",
    "accepted_burst_extensions", "accepted_burst_tail_flushes",
    "accepted_burst_read_caps")
# These are interval deltas, including accepted lower-idle time; keep them in
# kernel_counter_delta so mixed-regime means cannot silently drop new telemetry.
TIMED_WINDOW_COUNTER_FIELDS = (
    WINDOW_SIZE_FIELDS + CLOSE_REASON_FIELDS + ONE_PAGE_CLOSE_FIELDS +
    WIN1_PACK_CAUSE_FIELDS + SINGLE_TAIL_FIELDS + ID52_FIELDS + PACK_CLOSE_FIELDS +
    SMALL_TAIL_CLOSE_FIELDS + BURST_CLOSE_DETAIL_FIELDS + TAIL_SAMPLE_FIELDS +
    K1_READY_WAIT_FIELDS + DEADLINE_CONTEXT_FIELDS + BURST_COUNTER_FIELDS + (
        "gc_victims", "accepted_work_lower_idle_events",
        "accepted_work_lower_idle_ns",
        "accepted_work_lower_idle_undersized_batch_ns",
        "accepted_work_lower_idle_worker_unscheduled_ns",
        "accepted_work_lower_idle_preparing_head_ns",
        "accepted_work_lower_idle_no_ready_work_ns",
        "accepted_work_lower_idle_post_lower_ns"))
SATURATION_WINDOW_FIELDS = WINDOW_SIZE_FIELDS + (
    "close_idle", "close_deadline", "close_pack_ready")
# Standard (non-A/B) sessions run the production module default: delta64
# rescue on. Explicit A/B control arms pin it off with --no-delta64-rescue.
PRODUCTION_DELTA64_RESCUE = 1
# Production second-pass LZ4 acceleration used only by delta64 rescue (ID67).
PRODUCTION_DELTA64_LZ4_ACCELERATION = 4

DELTA64_FIELDS = (
    "delta64_eligible", "delta64_classifier_pass", "delta64_attempts",
    "delta64_adopted", "delta64_direct_adopted",
    "delta64_first_lz4_skipped", "delta64_raw_rescues",
    "delta64_lz4_rescues",
    "delta64_pack_eligible", "delta64_pack_attempts",
    "delta64_pack_cliff_crossings", "delta64_pack_adopted",
    "delta64_score_0_7", "delta64_score_8_15",
    "delta64_score_16_23", "delta64_score_ge24",
    "delta64_payload_bytes_saved", "delta64_raw_payload_bytes_saved",
    "delta64_lz4_payload_bytes_saved", "delta64_transform_calls",
    "delta64_transform_wall_ns", "delta64_wall_ns",
)
KERNEL_WRITE_FIELDS = (
    "physical_write_reqs", "lz4_wall_ns",
    "ordered_lz4_wall_ns", "prep_lz4_wall_ns",
    "write_copy_wall_ns", "write_copy_bytes",
    "ordered_write_copy_wall_ns", "prep_write_copy_wall_ns",
    "direct_lz4_input_pages", "mapped_snapshot_input_pages",
    "window_sort_wall_ns",
    "window_commit_wall_ns", "window_commit_nonio_wall_ns",
    "engine_plan_wall_ns", "engine_pack_wall_ns",
    "engine_publish_wall_ns", "engine_publish_crc_wall_ns",
    "engine_publish_auth_wall_ns", "engine_prehashed_records",
    "batch_snapshot_crc_wall_ns", "batch_pause_crc_wall_ns",
    "batch_resume_crc_wall_ns", "prep_crc_wall_ns",
    "ordered_crc_wall_ns", "lower_write_wall_ns",
    "ordered_worker_wall_ns", "prep_worker_wall_ns",
    "ordered_worker_cpu_ns", "prep_worker_cpu_ns", "read_worker_cpu_ns",
    "prep_wait_wall_ns", "prep_lower_write_overlap_ns",
    "prep_lower_read_overlap_ns", "prep_lower_write_samples", "prep_lower_write_start_queued",
    "prep_lower_write_start_nonempty", "prep_lower_write_end_queued",
    "prep_lower_write_end_nonempty", "pipeline_async_runs",
    "pipeline_read_bypass_skips",
    "pipeline_active_wall_ns", "pipeline_finalize_wait_wall_ns",
    "pipeline_post_lower_wall_ns",
    "write_admit_worker_samples", "write_admit_worker_wall_ns",
    "sync4_windows", "sync4_wall_ns", "sync4_lower_write_ns",
    "sync4_nonio_ns", "sync4_reissue_samples", "sync4_reissue_gap_ns",
    "write_wait_le1ms", "write_wait_1to4ms",
    "write_wait_gt4ms", "delta64_prepare_pages",
    "delta64_prepare_parallel_starts",
    "retained_burst_target", "delta64_rescue",
    "delta64_prepare_workers", "delta64_prepare_active_max",
    "lz4_acceleration", "delta64_lz4_acceleration",
    "write_pipeline_depth", "pipeline_active_max",
    "k1_allow_after_read_bypass", "read_coalesce_max_blocks",
    "invalidate_cache_on_write_admit",
    "work_conserving_hand_records", "prep_ready_current", "prep_ready_max",
    "prep_slots_in_use", "prep_slots_in_use_max",
    "submitter_prepare", "submitter_prepare_lanes",
    "submitter_prepare_claims", "submitter_prepare_lane_misses",
    "submitter_prepare_page_misses", "submitter_prepare_active",
    "submitter_prepare_active_max", "submitter_owner_deferrals",
    "submitter_prepare_pages", "submitter_prepare_wall_ns",
    "submitter_prepare_cpu_ns", "submitter_lz4_wall_ns",
    "submitter_copy_wall_ns", "submitter_copy_bytes",
    "submitter_crc_wall_ns", "lone_raw",
    "lone_raw_candidates", "lone_raw_cancelled_followers",
    "lone_raw_selected", "lone_raw_zero_elided",
    "lone_raw_multi_record_windows", "lone_raw_multi_record_pages"
) + TIMED_WINDOW_COUNTER_FIELDS + PREPARATION_FIELDS + DELTA64_FIELDS + (
    "work_conserving_hand_closes", "work_conserving_dry_closes",
    "work_conserving_raw_not_ready", "work_conserving_compressed_ready",
    "work_conserving_raw_ready", "prep_late_results_discarded")
BENCHMARK_PROVENANCE_FIELDS = ("source_sha", "fixture_sha256", "trace_sha256")
LOWER_INFLIGHT_INT_FIELDS = (
    "target_interval_ns", "samples", "read_start", "write_start",
    "read_end", "write_end", "read_peak", "write_peak", "total_peak")
LOWER_INFLIGHT_FLOAT_FIELDS = (
    "read_time_weighted", "write_time_weighted", "total_time_weighted")
LOWER_INFLIGHT_FIELDS = LOWER_INFLIGHT_INT_FIELDS + LOWER_INFLIGHT_FLOAT_FIELDS
WORKLOAD_OPPORTUNITY_FIELDS = (
    "measured_write_ops", "measured_unique_write_payloads",
    "nonzero_same_filled_write_ops", "same_page_rewrite_ops",
    "resident_duplicate_write_ops", "final_live_unique_payloads",
    "final_live_duplicate_pages", "final_live_nonzero_same_filled_pages")


PREDICTOR_TRANSFORM_NAMES = ("delta64",)
PREDICTOR_BACKENDS = ("scalar", "sse2", "avx2", "avx512", "neon")
PREDICTOR_THRESHOLDS = (4, 8, 16, 24, 32)
LZ4_ACCELERATIONS = (1, 2, 3, 4)
PREDICTOR_NEGATIVE_PROFILES = ("zero", "repeat", "entropy", "mixed", "medium")
PREDICTOR_SAMPLING_CONTROL_NAMES = (
    "repeated_512b_headers", "lane1_only_signal")
PREDICTOR_TRANSFORM_FIELDS = (
    "adopted", "raw_rescued", "cliff_2024", "saved_payload_bytes",
    "baseline_blocks", "candidate_blocks", "planner_blocks_saved",
    "baseline_extents", "candidate_extents", "planner_extents_saved",
    "transform_ns_per_page", "inverse_ns_per_page",
    "scalar_transform_ns_per_page", "scalar_inverse_ns_per_page",
    "second_lz4_ns_per_page")
PREDICTOR_BACKEND_TIMING_FIELDS = ("transform_ns_per_page", "inverse_ns_per_page")
PREDICTOR_ROUTE_CPU_FIELDS = (
    "routed_cpu_ns_total", "routed_cpu_ns_per_page", "ns_per_saved_block")


def parse_predictor_evidence(output):
    """Sanitize ID67a native/offline evidence emitted by the C evaluator."""
    prefix = "SWAPZ_PREDICTOR_EVIDENCE="
    record = None
    for line in output.splitlines():
        if not line.startswith(prefix):
            continue
        try:
            candidate = json.loads(line[len(prefix):])
        except (TypeError, ValueError):
            return None
        if record is not None:
            return None
        record = candidate
    if not isinstance(record, dict) or record.get("scope") != (
            "OFFLINE_NATIVE_ONLY_NOT_KERNEL_POLICY"):
        return None
    if type(record.get("negative_pages")) is not int or \
            record["negative_pages"] <= 0 or \
            type(record.get("structured_pages")) is not int or \
            record["structured_pages"] <= 0:
        return None
    classifier = record.get("classifier")
    if not isinstance(classifier, dict) or \
            classifier.get("candidate") != "delta64" or \
            classifier.get("backend") != "scalar" or \
            classifier.get("sample_pairs") != 32 or \
            classifier.get("stage1_pairs") != 8 or \
            classifier.get("stage1_min_score") != 2 or \
            classifier.get("benchmark_repeats") != 256 or \
            type(classifier.get("eligible_pages")) is not int or \
            classifier["eligible_pages"] <= 0 or \
            type(classifier.get("early_abort_pages")) is not int or \
            not 0 <= classifier["early_abort_pages"] <= classifier["eligible_pages"] or \
            type(classifier.get("benchmark_calls")) is not int or \
            classifier["benchmark_calls"] != \
            classifier["eligible_pages"] * classifier["benchmark_repeats"] or \
            type(classifier.get("ns_per_page")) is not int or \
            classifier["ns_per_page"] < 0 or \
            type(classifier.get("scalar_ns_per_page")) is not int or \
            classifier["scalar_ns_per_page"] < 0:
        return None

    lz4_acceleration_sweep = record.get("lz4_acceleration_sweep")
    if not isinstance(lz4_acceleration_sweep, list) or \
            len(lz4_acceleration_sweep) != len(LZ4_ACCELERATIONS) or \
            [row.get("acceleration") if isinstance(row, dict) else None
             for row in lz4_acceleration_sweep] != list(LZ4_ACCELERATIONS):
        return None
    for row in lz4_acceleration_sweep:
        if any(type(row.get(field)) is not int or row[field] < 0
               for field in ("wall_ns_per_page", "accepted_payload_bytes",
                             "raw_pages", "planner_blocks",
                             "planner_extents")) or \
                row["planner_blocks"] <= 0 or row["planner_extents"] <= 0:
            return None

    sampling_controls = record.get("sampling_controls")
    if not isinstance(sampling_controls, list) or \
            len(sampling_controls) != len(PREDICTOR_SAMPLING_CONTROL_NAMES):
        return None
    for item, expected_name, expected_minimum in zip(
            sampling_controls, PREDICTOR_SAMPLING_CONTROL_NAMES, (24, 16)):
        if not isinstance(item, dict) or \
                item.get("name") != expected_name or \
                type(item.get("score")) is not int or \
                type(item.get("minimum_score")) is not int or \
                item["minimum_score"] != expected_minimum or \
                not expected_minimum <= item["score"] <= 64:
            return None

    backend_rows = record.get("backend_benchmarks")
    if not isinstance(backend_rows, list) or not backend_rows or \
            backend_rows[0].get("name") != "scalar" or \
            any(not isinstance(row, dict) or
                row.get("name") not in PREDICTOR_BACKENDS or
                any(type(row.get(field)) is not int or row[field] < 0
                    for field in PREDICTOR_BACKEND_TIMING_FIELDS)
                for row in backend_rows) or \
            len({row["name"] for row in backend_rows}) != len(backend_rows):
        return None
    # SSE2 native A/B retains the pre-promotion 1x loop as a regression baseline.
    sse2_ab = record.get("sse2_forward_ab")
    has_sse2 = any(row["name"] == "sse2" for row in backend_rows)
    if has_sse2:
        if not isinstance(sse2_ab, dict) or \
                sse2_ab.get("scope") != (
                    "SAME_HOST_NATIVE_BASELINE_VS_PROMOTED_PRODUCTION") or \
                sse2_ab.get("repeats_per_arm") != 64 or \
                sse2_ab.get("pages") != (
                    record["negative_pages"] + record["structured_pages"]):
            return None
        pairs = sse2_ab.get("pairs")
        if not isinstance(pairs, list) or len(pairs) != 5:
            return None
        for index, pair in enumerate(pairs):
            if not isinstance(pair, dict) or pair.get("order") != (
                    "unrolled_first" if index % 2 else "baseline_first"):
                return None
            if any(type(pair.get(name)) is not int or pair[name] <= 0
                   for name in ("baseline_ns_per_page",
                                "unrolled_ns_per_page")):
                return None
    elif sse2_ab is not None:
        return None
    io_model_block_ns = record.get("io_model_block_ns")
    if not isinstance(io_model_block_ns, dict) or \
            io_model_block_ns.get("sd_emulated") != 390625 or \
            io_model_block_ns.get("ssd_emulated") != 48828:
        return None

    threshold_rows = record.get("thresholds")
    if not isinstance(threshold_rows, list) or \
            [row.get("threshold") if isinstance(row, dict) else None
             for row in threshold_rows] != list(PREDICTOR_THRESHOLDS):
        return None
    threshold_fields = (
        "negative_eligible", "negative_calls", "negative_useful",
        "structured_eligible", "structured_calls", "structured_useful",
        "routed_baseline_blocks", "routed_candidate_blocks",
        "routed_baseline_extents", "routed_candidate_extents")
    for row in threshold_rows:
        if any(type(row.get(field)) is not int or row[field] < 0
               for field in threshold_fields) or \
                any(type(row.get(field)) is not int or row[field] < 0
                    for field in PREDICTOR_ROUTE_CPU_FIELDS):
            return None
        if row["negative_calls"] > row["negative_eligible"] or \
                row["negative_useful"] > row["negative_calls"] or \
                row["structured_calls"] > row["structured_eligible"] or \
                row["structured_useful"] > row["structured_calls"] or \
                type(row.get("routed_blocks_saved")) is not int or \
                type(row.get("routed_extents_saved")) is not int or \
                row["routed_baseline_blocks"] <= 0 or \
                row["routed_candidate_blocks"] <= 0 or \
                row["routed_baseline_extents"] <= 0 or \
                row["routed_candidate_extents"] <= 0 or \
                row["routed_blocks_saved"] != (
                    row["routed_baseline_blocks"] -
                    row["routed_candidate_blocks"]) or \
                row["routed_extents_saved"] != (
                    row["routed_baseline_extents"] -
                    row["routed_candidate_extents"]):
            return None
        profiles = row.get("negative_profiles")
        if not isinstance(profiles, list) or \
                [item.get("name") if isinstance(item, dict) else None
                 for item in profiles] != list(PREDICTOR_NEGATIVE_PROFILES):
            return None
        for item in profiles:
            for field in ("pages", "eligible", "calls", "useful"):
                if type(item.get(field)) is not int or item[field] < 0:
                    return None
            if item["eligible"] > item["pages"] or \
                    item["calls"] > item["eligible"] or \
                    item["useful"] > item["calls"]:
                return None
        if sum(item["eligible"] for item in profiles) != \
                row["negative_eligible"] or \
                sum(item["calls"] for item in profiles) != \
                row["negative_calls"] or \
                sum(item["useful"] for item in profiles) != \
                row["negative_useful"]:
            return None

    transform_rows = record.get("transforms")
    if not isinstance(transform_rows, list) or \
            [row.get("name") if isinstance(row, dict) else None
             for row in transform_rows] != list(PREDICTOR_TRANSFORM_NAMES):
        return None
    for row in transform_rows:
        for field in PREDICTOR_TRANSFORM_FIELDS:
            value = row.get(field)
            if type(value) is not int:
                return None
            if field not in ("planner_blocks_saved", "planner_extents_saved") and \
                    value < 0:
                return None
        if row["baseline_blocks"] <= 0 or row["candidate_blocks"] <= 0 or \
                row["baseline_extents"] <= 0 or row["candidate_extents"] <= 0 or \
                row.get("transform_backend") not in PREDICTOR_BACKENDS or \
                row.get("inverse_backend") not in PREDICTOR_BACKENDS:
            return None
        if row["planner_blocks_saved"] != (
                row["baseline_blocks"] - row["candidate_blocks"]) or \
                row["planner_extents_saved"] != (
                row["baseline_extents"] - row["candidate_extents"]):
            return None
    production_route = record.get("production_route")
    if not isinstance(production_route, dict) or \
            production_route.get("scope") != (
                "OFFLINE_NATIVE_ONLY_NOT_KERNEL_POLICY") or \
            production_route.get("general_threshold") != 24 or \
            production_route.get("packing_threshold") != 16:
        return None
    route_count_fields = (
        "eligible_pages", "packing_eligible_pages", "classifier_passes",
        "candidate_attempts", "adopted_pages", "raw_rescues", "lz4_rescues",
        "packing_adoptions", "baseline_blocks", "candidate_blocks",
        "baseline_extents", "candidate_extents")
    route_timing_fields = (
        "payload_bytes_saved", "modeled_wall_ns_total",
        "modeled_wall_ns_per_page", "ns_per_saved_block")
    if any(type(production_route.get(field)) is not int or
           production_route[field] < 0 for field in route_count_fields +
           route_timing_fields):
        return None
    total_pages = record["negative_pages"] + record["structured_pages"]
    if production_route["eligible_pages"] <= 0 or \
            production_route["eligible_pages"] > total_pages or \
            production_route["packing_eligible_pages"] > \
            production_route["eligible_pages"] or \
            production_route["classifier_passes"] > \
            production_route["eligible_pages"] or \
            production_route["candidate_attempts"] != \
            production_route["classifier_passes"] or \
            production_route["adopted_pages"] > \
            production_route["candidate_attempts"] or \
            production_route["raw_rescues"] + \
            production_route["lz4_rescues"] != \
            production_route["adopted_pages"] or \
            production_route["packing_adoptions"] > \
            production_route["adopted_pages"] or \
            production_route["packing_adoptions"] > \
            production_route["packing_eligible_pages"] or \
            production_route["baseline_blocks"] <= 0 or \
            production_route["candidate_blocks"] <= 0 or \
            production_route["baseline_extents"] <= 0 or \
            production_route["candidate_extents"] <= 0:
        return None
    if type(production_route.get("blocks_saved")) is not int or \
            type(production_route.get("extents_saved")) is not int or \
            production_route["blocks_saved"] != (
                production_route["baseline_blocks"] -
                production_route["candidate_blocks"]) or \
            production_route["extents_saved"] != (
                production_route["baseline_extents"] -
                production_route["candidate_extents"]) or \
            production_route["modeled_wall_ns_per_page"] != (
                production_route["modeled_wall_ns_total"] // total_pages) or \
            production_route["ns_per_saved_block"] != (
                production_route["modeled_wall_ns_total"] //
                production_route["blocks_saved"]
                if production_route["blocks_saved"] > 0 else 0):
        return None
    if classifier["eligible_pages"] != production_route["eligible_pages"]:
        return None
    if any(row["negative_eligible"] + row["structured_eligible"] !=
           production_route["eligible_pages"] for row in threshold_rows):
        return None
    return {
        "scope": record["scope"],
        "negative_pages": record["negative_pages"],
        "structured_pages": record["structured_pages"],
        "classifier": classifier,
        "lz4_acceleration_sweep": lz4_acceleration_sweep,
        "sampling_controls": sampling_controls,
        "backend_benchmarks": backend_rows,
        "sse2_forward_ab": sse2_ab,
        "io_model_block_ns": io_model_block_ns,
        "thresholds": threshold_rows,
        "transforms": transform_rows,
        "production_route": production_route,
    }


def parse_gc_scan_scale_evidence(output):
    """Sanitize native million-page GC scan scaling evidence."""
    prefix = "SWAPZ_GC_SCAN_SCALE_EVIDENCE="
    record = None
    for line in output.splitlines():
        if not line.startswith(prefix):
            continue
        try:
            candidate = json.loads(line[len(prefix):])
        except (TypeError, ValueError):
            return None
        if record is not None:
            return None
        record = candidate
    if not isinstance(record, dict) or record.get("scope") != (
            "OFFLINE_NATIVE_GC_SCALE_ONLY"):
        return None
    rows = record.get("rows")
    expected = ((262144, 1024), (1048576, 4096))
    if not isinstance(rows, list) or len(rows) != len(expected):
        return None
    clean = []
    for row, (pages, segments) in zip(rows, expected):
        if not isinstance(row, dict) or \
                row.get("logical_pages") != pages or \
                row.get("segments") != segments or \
                row.get("victim_records") != 256:
            return None
        for field in ("legacy_score_scan_ns", "incremental_select_ns",
                      "relocation_scan_ns", "relocation_list_ns",
                      "legacy_dead_probe_ns", "mapped_dead_probe_ns"):
            if type(row.get(field)) is not int or row[field] <= 0:
                return None
        clean.append({key: row[key] for key in (
            "logical_pages", "segments", "legacy_score_scan_ns",
            "incremental_select_ns", "relocation_scan_ns",
            "relocation_list_ns", "legacy_dead_probe_ns",
            "mapped_dead_probe_ns", "victim_records")})
    return {"scope": record["scope"], "rows": clean}


def parse_extent_geometry_evidence(output):
    """Sanitize deterministic ID73 offline extent-geometry evidence."""
    prefix = "SWAPZ_EXTENT_GEOMETRY_EVIDENCE="
    record = None
    for line in output.splitlines():
        if not line.startswith(prefix):
            continue
        try:
            candidate = json.loads(line[len(prefix):])
        except (TypeError, ValueError):
            return None
        if record is not None:
            return None
        record = candidate
    if not isinstance(record, dict) or record.get("scope") != (
            "OFFLINE_NATIVE_GEOMETRY_ONLY_NOT_FORMAT_POLICY"):
        return None
    if record.get("logical_pages") != 1024 or record.get("normal_windows") != 64:
        return None
    expected = (
        "aligned_1_2_4",
        "packed_1_2_4",
        "packed_1_2_3_4",
        "packed_1_2_4_8",
        "packed_1_2_4_8_16",
    )
    rows = record.get("rows")
    if not isinstance(rows, list) or len(rows) != len(expected):
        return None
    clean = []
    for row, name in zip(rows, expected):
        if not isinstance(row, dict) or row.get("name") != name:
            return None
        for field in ("physical_blocks", "write_runs",
                      "cold_read_blocks_x1000", "seq_4m_requests"):
            if type(row.get(field)) is not int or row[field] <= 0:
                return None
        if type(row.get("waste_blocks")) is not int or row["waste_blocks"] < 0:
            return None
        clean.append({key: row[key] for key in (
            "name", "physical_blocks", "waste_blocks", "write_runs",
            "cold_read_blocks_x1000", "seq_4m_requests")})
    return {
        "scope": record["scope"],
        "logical_pages": record["logical_pages"],
        "normal_windows": record["normal_windows"],
        "rows": clean,
    }


def workload_opportunity_record(obj):
    record = obj.get("workload_opportunity")
    if not isinstance(record, dict) or record.get("scope") != (
            "TRACE_FIXTURE_OPPORTUNITY_ONLY_NOT_KERNEL_SAVINGS"):
        return None
    if any(type(record.get(field)) is not int or record[field] < 0
           for field in WORKLOAD_OPPORTUNITY_FIELDS):
        return None
    return {"scope": record["scope"],
            **{field: record[field] for field in WORKLOAD_OPPORTUNITY_FIELDS}}


def lower_inflight_record(obj):
    """Copy only non-identifying lower queue metrics into the report."""
    record = obj.get("lower_inflight")
    if not isinstance(record, dict):
        return None
    return {field: record.get(field) for field in LOWER_INFLIGHT_FIELDS}


def timed_window_error(record):
    if not isinstance(record, dict):
        return "missing timed swapz window telemetry"
    if type(record.get("delta64_rescue")) is not int or record["delta64_rescue"] not in (0, 1):
        return "missing or invalid timed delta64 policy"
    if type(record.get("delta64_prepare_workers")) is not int or not (
            0 <= record["delta64_prepare_workers"] <= 4):
        return "missing or invalid timed delta64 preparation width"
    if type(record.get("delta64_prepare_active_max")) is not int or not (
            0 <= record["delta64_prepare_active_max"] <=
            record["delta64_prepare_workers"]):
        return "invalid timed delta64 preparation concurrency"
    if (type(record.get("delta64_prepare_pages")) is not int or
            record["delta64_prepare_pages"] < 0):
        return "invalid timed delta64 preparation page count"
    if (type(record.get("delta64_prepare_parallel_starts")) is not int or
            record["delta64_prepare_parallel_starts"] < 0):
        return "invalid timed delta64 parallel-start count"
    submitter_counters = (
        "submitter_prepare_claims", "submitter_prepare_lane_misses",
        "submitter_prepare_page_misses", "submitter_owner_deferrals",
        "submitter_prepare_pages", "submitter_prepare_wall_ns",
        "submitter_prepare_cpu_ns", "submitter_lz4_wall_ns",
        "submitter_copy_wall_ns", "submitter_copy_bytes",
        "submitter_crc_wall_ns",
    )
    if (type(record.get("submitter_prepare")) is not int or
            record["submitter_prepare"] not in (0, 1)):
        return "missing or invalid timed submitter preparation policy"
    if (type(record.get("submitter_prepare_lanes")) is not int or
            not 0 <= record["submitter_prepare_lanes"] <= 8 or
            bool(record["submitter_prepare_lanes"]) !=
            bool(record["submitter_prepare"])):
        return "invalid timed submitter preparation lanes"
    if (type(record.get("submitter_prepare_active")) is not int or
            record["submitter_prepare_active"] != 0):
        return "submitter preparation active at timed boundary"
    if type(record.get("submitter_prepare_active_max")) is not int or not (
            0 <= record["submitter_prepare_active_max"] <=
            record["submitter_prepare_lanes"]):
        return "invalid timed submitter preparation concurrency"
    if any(type(record.get(field)) is not int or record[field] < 0
           for field in submitter_counters):
        return "invalid timed submitter preparation telemetry"
    if not record["submitter_prepare"] and any(
            record[field] for field in submitter_counters):
        return "disabled submitter preparation recorded activity"
    if record["submitter_prepare_pages"] > record["submitter_prepare_claims"]:
        return "inconsistent timed submitter preparation claims"
    if (record["submitter_copy_bytes"] !=
            record["submitter_prepare_pages"] * 4096):
        return "inconsistent timed submitter preparation copy bytes"
    if record["submitter_copy_bytes"] > record["write_copy_bytes"]:
        return "inconsistent timed submitter/global copy bytes"
    if (record["submitter_lz4_wall_ns"] +
            record["submitter_copy_wall_ns"] +
            record["submitter_crc_wall_ns"] >
            record["submitter_prepare_wall_ns"]):
        return "inconsistent timed submitter preparation timing"
    if (record["ordered_lz4_wall_ns"] + record["prep_lz4_wall_ns"] +
            record["submitter_lz4_wall_ns"] != record["lz4_wall_ns"]):
        return "inconsistent timed LZ4 attribution"
    if (record["ordered_write_copy_wall_ns"] +
            record["prep_write_copy_wall_ns"] +
            record["submitter_copy_wall_ns"] !=
            record["write_copy_wall_ns"]):
        return "inconsistent timed WRITE-copy attribution"
    if any(type(record.get(field)) is not int or record[field] < 0
           for field in TIMED_WINDOW_COUNTER_FIELDS + PREPARATION_FIELDS + DELTA64_FIELDS):
        return "invalid timed swapz window telemetry"
    if sum(record[field] for field in (
            "accepted_work_lower_idle_undersized_batch_ns",
            "accepted_work_lower_idle_worker_unscheduled_ns",
            "accepted_work_lower_idle_preparing_head_ns",
            "accepted_work_lower_idle_no_ready_work_ns")) != \
            record["accepted_work_lower_idle_ns"]:
        return "inconsistent accepted lower-idle attribution"
    if not record["delta64_rescue"] and any(record[field] for field in DELTA64_FIELDS):
        return "disabled delta64 recorded rescue activity"
    if not (record["delta64_adopted"] <= record["delta64_attempts"] <=
            record["delta64_classifier_pass"] <= record["delta64_eligible"]):
        return "inconsistent timed delta64 attempt accounting"
    if (sum(record[field] for field in (
            "delta64_score_0_7", "delta64_score_8_15",
            "delta64_score_16_23", "delta64_score_ge24")) !=
            record["delta64_eligible"] or
            record["delta64_score_ge24"] > record["delta64_classifier_pass"] or
            record["delta64_classifier_pass"] >
            record["delta64_score_ge24"] + record["delta64_score_16_23"]):
        return "inconsistent timed delta64 score accounting"
    if not (record["delta64_pack_adopted"] <=
            record["delta64_pack_cliff_crossings"] <=
            record["delta64_attempts"] and
            record["delta64_pack_adopted"] <=
            record["delta64_pack_attempts"] <=
            record["delta64_pack_eligible"] <= record["delta64_eligible"] and
            record["delta64_pack_adopted"] <= record["delta64_lz4_rescues"]):
        return "inconsistent timed delta64 packing accounting"
    if (record["delta64_raw_rescues"] + record["delta64_lz4_rescues"] +
            record["delta64_direct_adopted"] != record["delta64_adopted"] or
            record["delta64_first_lz4_skipped"] <
            record["delta64_direct_adopted"] or
            record["delta64_raw_payload_bytes_saved"] +
            record["delta64_lz4_payload_bytes_saved"] !=
            record["delta64_payload_bytes_saved"]):
        return "inconsistent timed delta64 rescue accounting"
    for kind, minimum, maximum in (("raw", 528, 4095), ("lz4", 1, 3567)):
        if not (record[f"delta64_{kind}_rescues"] * minimum <=
                record[f"delta64_{kind}_payload_bytes_saved"] <=
                record[f"delta64_{kind}_rescues"] * maximum):
            return "inconsistent timed delta64 payload accounting"
    if type(record.get("retained_burst_target")) is not int or not (
            1 <= record["retained_burst_target"] <= 64):
        return "invalid timed retained burst target"
    if sum(record[field] for field in CLOSE_REASON_FIELDS) != record["windows"]:
        return "timed window close-reason accounting is inconsistent"
    if sum(record[field] for field in ONE_PAGE_CLOSE_FIELDS) != record["one_page_windows"]:
        return "timed one-page close-reason accounting is inconsistent"
    if sum(record[field] for field in WIN1_PACK_CAUSE_FIELDS) != record["win1_pack_ready"]:
        return "timed one-page PACK_READY attribution is inconsistent"
    if (record["single_tail_deferrals"] !=
            record["single_tail_companions"] +
            record["win1_deadline_deferred_tail"] +
            record["win1_idle_deferred_tail"] +
            record["single_tail_other_clears"]):
        return "timed deferred-singleton conservation is inconsistent"
    if record["win1_deadline_deferred_tail"] > record["win1_deadline"]:
        return "timed deferred deadline attribution is inconsistent"
    if record["win1_idle_deferred_tail"] > record["win1_idle"]:
        return "timed deferred idle attribution is inconsistent"
    if sum(record[field] for field in SINGLE_TAIL_TIMING_FIELDS[:4]) != record["single_tail_companions"]:
        return "timed deferred companion age attribution is inconsistent"
    if sum(record[field] for field in SINGLE_TAIL_TIMING_FIELDS[4:]) != record["win1_deadline_deferred_tail"]:
        return "timed deferred deadline age attribution is inconsistent"
    if (sum(record[field] for field in SINGLE_TAIL_COMP_UPPER_FIELDS) !=
            record["single_tail_comp_age_gt1000us"]):
        return "timed deferred companion upper-tail attribution is inconsistent"
    if (sum(record[field] for field in PACK_CLOSE_PRIMARY_FIELDS) !=
            record["close_pack_ready"] or
            record["pack_close_tail_target_le4"] >
            record["pack_close_tail_target"]):
        return "timed PACK_READY close attribution is inconsistent"
    burst = record["pack_close_burst_target"]
    if (record["pack_close_burst_admission"] +
            record["pack_close_burst_worker"] != burst or
            sum(record[field] for field in (
                "pack_close_burst_target_le4", "pack_close_burst_target_5_8",
                "pack_close_burst_target_9_16",
                "pack_close_burst_target_17_64")) != burst or
            sum(record[field] for field in (
                "pack_close_burst_count_le4", "pack_close_burst_count_5_8",
                "pack_close_burst_count_9_16",
                "pack_close_burst_count_17_64")) != burst or
            record["pack_close_burst_overshoot"] > burst):
        return "timed burst-target close attribution is inconsistent"
    if (sum(record[field] for field in (
                "pack_tail_zero_inflight", "pack_tail_zero_idle",
                "pack_tail_one_inflight", "pack_tail_one_idle",
                "pack_tail_many_inflight", "pack_tail_many_idle")) !=
            record["pack_tail_samples"]):
        return "timed post-pack tail-sample attribution is inconsistent"
    if (sum(record[field] for field in (
                "burst_shrink_after_inflight_zero",
                "burst_shrink_after_read_bypass",
                "burst_shrink_other")) != record["burst_target_shrinks"] or
            sum(record[field] for field in (
                "burst_shrink_target_le8",
                "burst_shrink_target_9_32",
                "burst_shrink_target_gt32")) != record["burst_target_shrinks"]):
        return "timed burst-shrink attribution is inconsistent"
    if (sum(record[field] for field in (
            "k1_ready_wait_pack_ready", "k1_ready_wait_full",
            "k1_ready_wait_deadline", "k1_ready_wait_fence",
            "k1_ready_wait_other")) != record["k1_ready_wait_windows"] or
            record["k1_ready_wait_records"] < record["k1_ready_wait_windows"] or
            record["k1_ready_wait_max_records"] > 64 or
            record["k1_ready_wait_wall_ns"] >
            record["pipeline_finalize_wait_wall_ns"] or
            record["pipeline_post_lower_wall_ns"] >
            record["pipeline_active_wall_ns"]):
        return "timed K=1/post-lower attribution is inconsistent"
    for total, lower, read, both in (
            ("single_tail_companions", "single_tail_comp_after_lower_done",
             "single_tail_comp_after_read_bypass", "single_tail_comp_after_both"),
            ("win1_deadline_deferred_tail", "single_tail_deadline_after_lower_done",
             "single_tail_deadline_after_read_bypass", "single_tail_deadline_after_both")):
        if (record[lower] > record[total] or record[read] > record[total] or
                record[both] > record[lower] or record[both] > record[read]):
            return "timed deferred singleton service attribution is inconsistent"
    if (record["batch_pause_crc_wall_ns"] +
            record["batch_resume_crc_wall_ns"] !=
            record["batch_snapshot_crc_wall_ns"]):
        return "batch snapshot CRC phase accounting is inconsistent"
    if sum(record[field] for field in DEADLINE_CONTEXT_FIELDS) != record["close_deadline"]:
        return "timed deadline-context accounting is inconsistent"
    if (record["accepted_burst_tail_flushes"] >
            record["accepted_burst_extensions"] or
            record["accepted_burst_read_caps"] >
            record["accepted_burst_extensions"]):
        return "timed accepted-burst accounting is inconsistent"
    return None


def host_cpu_record(obj):
    """Keep only aggregate host CPU telemetry, never process names or paths."""
    raw = obj.get("host_cpu")
    if not isinstance(raw, dict):
        return {"status": "NOT_COLLECTED"}
    if raw.get("status") in ("UNAVAILABLE", "NOT_COLLECTED"):
        return {"status": raw["status"]}
    if raw.get("status") not in ("AVAILABLE", "PARTIAL"):
        return {"status": "INVALID"}
    if any(type(raw.get(key)) is not int or raw[key] <= 0
           for key in HOST_CPU_INT_FIELDS):
        return {"status": "INVALID"}
    for key in HOST_CPU_FLOAT_FIELDS:
        value = raw.get(key)
        if value is None and key == "pressure_some_fraction" and raw["status"] == "PARTIAL":
            continue
        if (type(value) not in (int, float) or not math.isfinite(value) or
                not 0 <= value <= 1):
            return {"status": "INVALID"}
    return {"status": raw["status"], **{key: raw.get(key) for key in HOST_CPU_FIELDS}}


def lower_inflight_error(record):
    if not isinstance(record, dict):
        return "missing lower in-flight telemetry"
    if any(type(record.get(field)) is not int or record[field] < 0
           for field in LOWER_INFLIGHT_INT_FIELDS):
        return "invalid lower in-flight integer telemetry"
    if record["target_interval_ns"] <= 0 or record["samples"] <= 0:
        return "empty lower in-flight telemetry"
    if any(not isinstance(record.get(field), (int, float)) or
           not math.isfinite(record[field]) or record[field] < 0
           for field in LOWER_INFLIGHT_FLOAT_FIELDS):
        return "invalid lower in-flight weighted telemetry"
    if (record["read_start"] > record["read_peak"] or
            record["write_start"] > record["write_peak"] or
            record["read_end"] > record["read_peak"] or
            record["write_end"] > record["write_peak"] or
            record["total_peak"] < max(record["read_peak"], record["write_peak"]) or
            record["total_peak"] > record["read_peak"] + record["write_peak"] or
            record["read_time_weighted"] > record["read_peak"] + 1e-9 or
            record["write_time_weighted"] > record["write_peak"] + 1e-9 or
            record["total_time_weighted"] > record["total_peak"] + 1e-9 or
            abs(record["total_time_weighted"] -
                record["read_time_weighted"] -
                record["write_time_weighted"]) > 1e-6):
        return "inconsistent lower in-flight telemetry"
    return None



def git_sha():
    """Return the nearest non-report code revision for the current checkout."""
    def git_text(*args):
        cmd = subprocess.run(["git", *args], cwd=ROOT, text=True,
                             capture_output=True, check=False)
        return cmd.stdout.strip() if cmd.returncode == 0 else None

    current = git_text("rev-parse", "HEAD")
    if not current or not re.fullmatch(r"[0-9a-f]{40}", current):
        return "unknown"
    while True:
        subject = git_text("show", "-s", "--format=%s", current)
        changed = git_text("diff-tree", "--no-commit-id", "--name-only",
                           "-r", current)
        if subject is None or changed is None:
            break
        names = [line for line in changed.splitlines() if line]
        if not (re.fullmatch(
                r"test: latest run for [0-9a-f]{12} \[skip ci\]",
                subject) and names == [GIT_RESULT]):
            break
        parent = git_text("rev-parse", f"{current}^")
        if not parent or not re.fullmatch(r"[0-9a-f]{40}", parent):
            break
        current = parent
    return current


def paired_provenance_error(row, label):
    """Require exact source/fixture/trace identity within every off/swapz pair."""
    arms = row.get("arms", {})
    for field in BENCHMARK_PROVENANCE_FIELDS:
        values = [arms.get(candidate, {}).get(field)
                  for candidate in ("off", "swapz")]
        if (any(not isinstance(value, str) or not value for value in values) or
                len(set(values)) != 1):
            return {"overall": "INCONCLUSIVE",
                    "reason": f"{label}: {field} missing or differs within pair"}
        agreed_value = values[0]
        if row.get(field) is not None and row[field] != agreed_value:
            return {"overall": "INCONCLUSIVE",
                    "reason": f"{label}: {field} aggregate differs from paired arms"}
        # Preserve the existing pair-level shape only after both arms agree.
        row[field] = agreed_value
    return None


def safe_lines(log):
    """Never put arbitrary host paths, device identities or raw JSON in report."""
    found = []
    for line in log.splitlines():
        text = line.strip()
        if text.startswith(("PASS:", "FAIL:", "BLOCKED:", "QUARANTINED:",
                            "PASS_", "BLOCKED_LOADED_QUALIFICATION")):
            label = text.split("=", 1)[0].split(":", 1)[0]
            if len(label) <= 90 and label.replace("_", "").replace("-", "").isalnum():
                found.append(label)
    return list(dict.fromkeys(found))[-20:]


def parse_loaded_correctness(output):
    """Parse fixed, non-identifying owned-RAM correctness evidence."""
    patterns = {
        "raw_read": re.compile(
            r"PASS_LOADED_RAW_READ_FANOUT=profiles:(\d+) verified_pages:(\d+) "
            r"async_batches:(\d+) lower_read_reqs:(\d+)$"),
        "oracle": re.compile(
            r"PASS_LOADED_ORACLE_PROFILE=raw_pages:(\d+) zero_pages:(\d+) "
            r"flush_calls:(\d+)$"),
        "gc": re.compile(
            r"PASS_LOADED_LIVE_GC=victims:(\d+) rotations:(\d+) "
            r"pages:(\d+) read_bytes:(\d+) write_bytes:(\d+) "
            r"read_reqs:(\d+) write_reqs:(\d+) distinct:(\d+) "
            r"victim_min:(\d+) victim_max:(\d+) last:(\d+)->(\d+) "
            r"discards:(\d+) discard_sectors:(\d+) "
            r"discard_unsupported:(\d+) discard_failed:(\d+) "
            r"verified_pages:(\d+)$"),
        "gc_pressure": re.compile(
            r"PASS_LOADED_GC_PRESSURE=rounds:(\d+) write_wall_ns:(\d+) "
            r"baseline_p99_ns:(\d+) pressure_p99_ns:(\d+) "
            r"gc_wall_ns:(\d+) gc_fraction_ppm:(\d+) "
            r"choose_wall_ns:(\d+) choose_calls:(\d+) "
            r"choose_map_entries:(\d+) choose_segment_entries:(\d+) "
            r"relocation_map_entries:(\d+) no_headroom_skips:(\d+) "
            r"alignment_hole_fg:(\d+) alignment_hole_gc:(\d+) "
            r"tail_waste_fg:(\d+) tail_waste_gc:(\d+) "
            r"run_splits_by_hole:(\d+) alloc_probe_segments:(\d+) "
            r"alloc_probe_full_scans:(\d+) alloc_probe_wall_ns:(\d+) "
            r"trim_skipped:(\d+) segment_program_min:(\d+) "
            r"segment_program_sum:(\d+) segment_program_max:(\d+) "
            r"segment_program_segments:(\d+)$"),
        "discard_trim": re.compile(
            r"PASS_LOADED_DISCARD_TRIM=pages:(\d+) immediate_discards:(\d+) "
            r"immediate_sectors:(\d+) reuse_skips:(\d+) verified_pages:(\d+)$"),
        "packed_placement": re.compile(
            r"PASS_LOADED_PACKED_PLACEMENT=enabled:(\d+) verified_pages:(\d+) "
            r"holes:(\d+) run_splits:(\d+) failed:(\d+)$"),
        "suspend": re.compile(
            r"PASS_LOADED_SUSPEND_DRAIN=retain_ms:(\d+) "
            r"observed_open:(\d+) verified_pages:(\d+)$"),
        "completion_handoff": re.compile(
            r"PASS_LOADED_COMPLETION_HANDOFF=offloaded:(\d+) verified_pages:(\d+) "
            r"completed_writes:(\d+) active_after:(\d+) fault_offloaded:(\d+) "
            r"fault_injected:(\d+) post_failure_eio:(\d+)$"),
        "write_fault": re.compile(
            r"PASS_RETAINED_SYNTHETIC_WRITE_FAULT=retain_ms:(\d+) "
            r"injected:(\d+) syscall_errno:EIO lower_write_delta:(\d+)$"),
        "flush_fault": re.compile(
            r"PASS_RETAINED_SYNTHETIC_FLUSH_FAULT=retain_ms:(\d+) "
            r"injected:(\d+) data_write_reached_lower:(\d+)$"),
        "id36": re.compile(
            r"PASS_ID36_RESOURCE_PRESSURE=memory_high_events:(\d+) "
            r"memory_peak_bytes:(\d+) cpu_some_usec:(\d+) "
            r"cpu_workers:(\d+) pressure_mib:(\d+) oom:(\d+) oom_kill:(\d+)$"),
    }
    found = {}
    for line in output.splitlines():
        text = line.strip()
        for name, pattern in patterns.items():
            match = pattern.fullmatch(text)
            if match:
                found[name] = tuple(int(value) for value in match.groups())
    missing = [name for name in patterns if name not in found]
    if missing:
        return {"overall": "INCOMPLETE",
                "reason": "missing loaded correctness markers: " + ",".join(missing)}

    raw_read_profiles, raw_read_pages, raw_read_batches, raw_read_reqs = found["raw_read"]
    if (raw_read_profiles != 2 or raw_read_pages != 2048 or
            raw_read_batches <= 0 or raw_read_reqs <= 0):
        return {"overall": "INCOMPLETE",
                "reason": "RAW/mixed asynchronous READ evidence is incomplete"}
    raw_pages, zero_pages, flush_calls = found["oracle"]
    (gc_victims, gc_rotations, gc_pages, gc_read_bytes, gc_write_bytes,
     gc_read_reqs, gc_write_reqs, gc_distinct_victims,
     gc_victim_min_evictions, gc_victim_max_evictions,
     gc_last_victim, gc_last_destination, gc_segment_discards,
     gc_segment_discard_sectors, gc_discard_unsupported,
     gc_discard_failed, gc_verified_pages) = found["gc"]
    (gc_pressure_rounds, gc_useful_write_wall_ns, gc_baseline_p99_ns,
     gc_pressure_p99_ns, gc_wall_ns, gc_fraction_ppm,
     gc_choose_wall_ns, gc_choose_calls, gc_choose_map_entries,
     gc_choose_segment_entries, gc_relocation_map_entries,
     gc_no_headroom_skips, alignment_hole_fg, alignment_hole_gc,
     tail_waste_fg, tail_waste_gc, run_splits_by_hole,
     alloc_probe_segments, alloc_probe_full_scans, alloc_probe_wall_ns,
     trim_skipped, segment_program_min, segment_program_sum,
     segment_program_max, segment_program_segments) = found["gc_pressure"]
    (discard_trim_pages, discard_trim_immediate, discard_trim_sectors,
     discard_trim_reuse_skips, discard_trim_verified) = found["discard_trim"]
    (packed_enabled, packed_verified_pages, packed_holes,
     packed_run_splits, packed_failed) = found["packed_placement"]
    suspend_retain, observed_open, verified_pages = found["suspend"]
    (completion_batches, completion_pages, completion_writes, completion_active,
     completion_fault_batches, completion_faults,
     completion_terminal_eio) = found["completion_handoff"]
    write_retain, write_injected, write_lower_delta = found["write_fault"]
    flush_retain, flush_injected, flush_data_lower = found["flush_fault"]
    (id36_high_events, id36_peak_bytes, id36_cpu_some_usec,
     id36_cpu_workers, id36_pressure_mib, id36_oom,
     id36_oom_kill) = found["id36"]
    if raw_pages != 64 or zero_pages != 9 or flush_calls < 2:
        return {"overall": "INCOMPLETE",
                "reason": "loaded RAW/zero/flush oracle counters are inconsistent"}
    if (gc_victims < 2 or gc_rotations != gc_victims or gc_pages <= 0 or
            gc_read_bytes <= 0 or gc_write_bytes <= 0 or gc_read_reqs <= 0 or
            gc_write_reqs <= 0 or gc_distinct_victims < 3 or
            gc_victim_min_evictions <= 0 or
            gc_victim_max_evictions < gc_victim_min_evictions or
            gc_victim_max_evictions > gc_victims or
            gc_last_victim == gc_last_destination or
            gc_segment_discards < gc_victims or
            gc_segment_discard_sectors != gc_segment_discards * 2048 or
            gc_discard_unsupported or gc_discard_failed or
            gc_verified_pages != 4096):
        return {"overall": "INCOMPLETE",
                "reason": "loaded live-GC evidence is incomplete"}
    if (gc_pressure_rounds != 5 or gc_useful_write_wall_ns <= 0 or
            gc_baseline_p99_ns <= 0 or gc_pressure_p99_ns <= 0 or
            gc_wall_ns <= 0 or gc_choose_wall_ns <= 0 or
            gc_choose_calls < gc_victims or
            gc_choose_map_entries != 0 or
            gc_choose_segment_entries <= 0 or
            gc_relocation_map_entries != gc_pages or
            alloc_probe_segments <= 0 or alloc_probe_full_scans <= 0 or
            alloc_probe_full_scans > alloc_probe_segments or
            tail_waste_fg != alignment_hole_fg or
            tail_waste_gc != alignment_hole_gc or
            run_splits_by_hole != 0 or
            segment_program_segments <= 0 or
            segment_program_min > segment_program_max or
            segment_program_sum < segment_program_max or
            gc_fraction_ppm !=
            gc_wall_ns * 1000000 // gc_useful_write_wall_ns):
        return {"overall": "INCOMPLETE",
                "reason": "loaded foreground-GC pressure evidence is incomplete"}
    if (discard_trim_pages != 256 or discard_trim_immediate != 1 or
            discard_trim_sectors != 2048 or discard_trim_reuse_skips < 1 or
            discard_trim_verified != 4096):
        return {"overall": "INCOMPLETE",
                "reason": "loaded discard-time TRIM evidence is incomplete"}
    if (packed_enabled != 1 or packed_verified_pages != 128 or
            packed_holes != 0 or packed_run_splits != 0 or packed_failed != 0):
        return {"overall": "INCOMPLETE",
                "reason": "loaded packed-placement structural invariant failed"}
    if suspend_retain != 64 or observed_open != 1 or verified_pages != 128:
        return {"overall": "INCOMPLETE",
                "reason": "loaded suspend/drain evidence is incomplete"}
    if (completion_batches <= 0 or completion_pages != 128 or
            completion_writes != 16512 or completion_active != 0 or
            completion_fault_batches <= 0 or completion_faults != 1 or
            completion_terminal_eio != 1):
        return {"overall": "INCOMPLETE",
                "reason": "published completion handoff/drain/failure evidence is incomplete"}
    if write_retain != 2 or write_injected != 1 or write_lower_delta != 0:
        return {"overall": "INCOMPLETE",
                "reason": "synthetic retained WRITE fault contract failed"}
    if flush_retain != 2 or flush_injected != 1 or flush_data_lower != 1:
        return {"overall": "INCOMPLETE",
                "reason": "synthetic retained FLUSH fault contract failed"}
    if (id36_high_events <= 0 or id36_peak_bytes <
            id36_pressure_mib * 1024 * 1024 or
            id36_cpu_some_usec <= 0 or id36_cpu_workers < 2 or
            id36_pressure_mib != 576 or id36_oom or id36_oom_kill):
        return {"overall": "INCOMPLETE",
                "reason": "ID36 low-RAM/heavy-CPU evidence is incomplete"}
    return {
        "overall": "PASS",
        "raw_read_profiles": raw_read_profiles,
        "raw_read_verified_pages": raw_read_pages,
        "raw_read_async_batches": raw_read_batches,
        "raw_read_lower_requests": raw_read_reqs,
        "raw_pages": raw_pages,
        "zero_pages": zero_pages,
        "flush_calls": flush_calls,
        "gc_victims": gc_victims,
        "gc_rotations": gc_rotations,
        "gc_pages": gc_pages,
        "gc_read_bytes": gc_read_bytes,
        "gc_write_bytes": gc_write_bytes,
        "gc_read_reqs": gc_read_reqs,
        "gc_write_reqs": gc_write_reqs,
        "gc_distinct_victims": gc_distinct_victims,
        "gc_victim_min_evictions": gc_victim_min_evictions,
        "gc_victim_max_evictions": gc_victim_max_evictions,
        "gc_segment_discards": gc_segment_discards,
        "gc_segment_discard_sectors": gc_segment_discard_sectors,
        "gc_verified_pages": gc_verified_pages,
        "gc_pressure_rounds": gc_pressure_rounds,
        "gc_useful_write_wall_ns": gc_useful_write_wall_ns,
        "gc_baseline_p99_ns": gc_baseline_p99_ns,
        "gc_pressure_p99_ns": gc_pressure_p99_ns,
        "gc_wall_ns": gc_wall_ns,
        "gc_fraction_ppm": gc_fraction_ppm,
        "gc_choose_wall_ns": gc_choose_wall_ns,
        "gc_choose_calls": gc_choose_calls,
        "gc_choose_map_entries": gc_choose_map_entries,
        "gc_choose_segment_entries": gc_choose_segment_entries,
        "gc_relocation_map_entries": gc_relocation_map_entries,
        "gc_no_headroom_skips": gc_no_headroom_skips,
        "alignment_hole_blocks_foreground": alignment_hole_fg,
        "alignment_hole_blocks_gc": alignment_hole_gc,
        "segment_tail_waste_blocks_foreground": tail_waste_fg,
        "segment_tail_waste_blocks_gc": tail_waste_gc,
        "run_splits_by_hole": run_splits_by_hole,
        "alloc_probe_segments": alloc_probe_segments,
        "alloc_probe_full_scans": alloc_probe_full_scans,
        "alloc_probe_wall_ns": alloc_probe_wall_ns,
        "segment_discards_skipped_already_trimmed": trim_skipped,
        "segment_program_min": segment_program_min,
        "segment_program_sum": segment_program_sum,
        "segment_program_max": segment_program_max,
        "segment_program_segments": segment_program_segments,
        "discard_trim_pages": discard_trim_pages,
        "discard_trim_immediate": discard_trim_immediate,
        "discard_trim_sectors": discard_trim_sectors,
        "discard_trim_reuse_skips": discard_trim_reuse_skips,
        "discard_trim_verified_pages": discard_trim_verified,
        "packed_placement_enabled": packed_enabled,
        "packed_placement_verified_pages": packed_verified_pages,
        "packed_placement_holes": packed_holes,
        "packed_placement_run_splits": packed_run_splits,
        "suspend_retain_ms": suspend_retain,
        "suspend_observed_open": observed_open,
        "suspend_verified_pages": verified_pages,
        "completion_offloaded_batches": completion_batches,
        "completion_verified_pages": completion_pages,
        "completion_completed_writes": completion_writes,
        "completion_fault_offloaded_batches": completion_fault_batches,
        "retained_write_fault": "PRE_SUBMISSION_EIO_ZERO_LOWER_WRITE",
        "retained_flush_fault": "PRE_SUBMISSION_FLUSH_EIO_AFTER_DATA_WRITE",
        "id36_memory_high_events": id36_high_events,
        "id36_memory_peak_bytes": id36_peak_bytes,
        "id36_cpu_some_usec": id36_cpu_some_usec,
        "id36_cpu_workers": id36_cpu_workers,
        "id36_pressure_mib": id36_pressure_mib,
        "scope": "OWNED_RAM_NULL_BLK_SYNTHETIC_FAILURE_AND_RESOURCE_PRESSURE",
    }


def write_report(result):
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    # Newlines allow ranged reader requests. Omitting indentation keeps the
    # complete fixed matrix small enough for GitHub's contents reader.
    payload = json.dumps(result, sort_keys=True, indent=0,
                         allow_nan=False).encode("utf-8") + b"\n"
    temporary = REPORT.with_name(".test_results.json.tmp")
    try:
        with temporary.open("wb") as out:
            out.write(payload)
        os.replace(temporary, REPORT)
    finally:
        temporary.unlink(missing_ok=True)


def jobserver_fds():
    """Pass GNU Make tokens through Python into its private child builds."""
    flags = os.environ.get("MAKEFLAGS", "")
    match = re.search(r"--jobserver-auth=(\d+),(\d+)", flags)
    if not match:
        return ()
    fds = tuple(map(int, match.groups()))
    try:
        for fd in fds:
            os.fstat(fd)
    except OSError:
        return ()
    return fds


def automatic_build_jobs():
    """Choose bounded compilation parallelism when no parent jobserver exists."""
    try:
        available = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        available = os.cpu_count() or 1
    return max(1, min(available, 16))


def make_invocation():
    """Use the caller's jobserver, otherwise create a bounded private one."""
    if jobserver_fds():
        os.environ.pop("SWAPZ_TEST_JOBS", None)
        return ["make"], "independent compilation uses inherited Make jobserver."
    jobs = automatic_build_jobs()
    os.environ["SWAPZ_TEST_JOBS"] = str(jobs)
    return ["make", f"-j{jobs}"], (
        f"independent compilation uses automatic -j{jobs}."
    )


def failure_context(output, *, loaded=True, default_phase=None):
    """Return a sanitized failure phase/reason without leaking host details.

    Loaded diagnostics track the last named owned-device phase. Earlier
    build/rootless stages retain their own stage name and must never be
    mislabeled as administrator-authorization failures.
    """
    phase = default_phase or "preflight / administrator authorization"
    pair_number = 0
    regime = None
    if loaded:
        for line in output.splitlines():
            if line.startswith("START_LOADED_OWNED_NULLBLK_SMOKE"):
                phase = "owned RAM kernel smoke"
            elif line.startswith("START_LOADED_COMPOUND_BIO"):
                phase = "owned RAM compound/segmented BIO observation"
            elif line.startswith("START_LOADED_LIVE_GC"):
                phase = "owned RAM live-GC pressure"
            elif line.startswith("START_LOADED_DISCARD_TRIM"):
                phase = "owned RAM discard-time TRIM reclamation"
            elif line.startswith("START_LOADED_SUSPEND_DRAIN"):
                phase = "owned RAM retained suspend/drain"
            elif line.startswith("START_LOADED_RETAINED_WRITE_FAULT"):
                phase = "owned RAM retained synthetic WRITE fault"
            elif line.startswith("START_LOADED_RETAINED_FLUSH_FAULT"):
                phase = "owned RAM retained synthetic FLUSH fault"
            elif line.startswith("START_LOADED_PACKED_PLACEMENT"):
                phase = "owned RAM packed placement verification"
            elif line.startswith("START_LOADED_COMPLETION_HANDOFF"):
                phase = "owned RAM published completion handoff/drain/failure"
            elif line.startswith("START_ID36_RESOURCE_PRESSURE="):
                phase = "ID36 low-RAM/heavy-CPU pressure"
            elif (match := re.fullmatch(
                    r"START_STORAGE_ENVELOPE=(sd_card|sata_ssd|nvme_gen4|nvme_gen5) "
                    r"DELTA64_RESCUE=(0|1)", line)):
                mode = "delta64-positive write" if match.group(2) == "1" else "mixed"
                phase = f"{match.group(1)} synthetic service envelope ({mode})"
            elif line.startswith("PASS_LOADED_OWNED_NULLBLK_SMOKE"):
                phase = "shared fixture allocation and workload generation"
            elif line.startswith("START_OWNED_RAM_REGIME="):
                label = line.partition("=")[2]
                if label in MODEL_ORDER:
                    regime = label
            elif line.startswith("START_OWNED_RAM_PAIR_ASYNC_PREPARE="):
                pair_number += 1
                mode = "async" if line.rstrip().endswith("=1") else "sync"
                where = (regime + " " if regime else "")
                phase = f"owned RAM {where}comparison {pair_number}/8 ({mode})"
            elif (match := re.fullmatch(
                    r"BENCH_IO_PHASE=(off|swapz):(prefill|mixed|packed_read)", line)):
                phase += f" [{match.group(1)} {match.group(2)}]"
            elif line.startswith("PASS_OWNED_RAM_PAIR_ASYNC_PREPARE="):
                phase = f"after completed owned RAM comparison {pair_number}/8"

    unittest_failure = None
    if not loaded:
        for line in output.splitlines():
            match = re.match(
                r"^(?:FAIL|ERROR): (test_[A-Za-z0-9_]+) \(",
                line.strip())
            if match:
                unittest_failure = match.group(1)

    native_diagnostic = None
    if not loaded:
        for line in output.splitlines():
            candidate = line.strip()
            helper = re.match(
                r"^((?:predictor|routed production planner) .+?\b"
                r"(?:failed|rejected)):\s*(.*)$", candidate, re.I)
            compiler = re.search(
                r"\b(?:fatal )?error:\s*(.+)$", candidate, re.I)
            if helper:
                detail = f"{helper.group(1)}: {helper.group(2)}"
                native_diagnostic = "Native helper: " + detail
            elif compiler:
                native_diagnostic = "Native build error: " + compiler.group(1)
            elif "undefined reference to" in candidate:
                native_diagnostic = "Native link error: undefined reference"
            if native_diagnostic:
                native_diagnostic = re.sub(
                    r"(?<![A-Za-z0-9])/(?:[^\s'\"<>]+)",
                    "[path]", native_diagnostic)
                native_diagnostic = re.sub(
                    r"\b(?:[a-f0-9]{16,}|[0-9a-f]{8}-[0-9a-f-]{18,})\b",
                    "[id]", native_diagnostic, flags=re.I)
                native_diagnostic = re.sub(
                    r"[^A-Za-z0-9 .,:;()_+=/\-\[\]]", "?",
                    native_diagnostic)[:155]
                break

    if unittest_failure is not None:
        nested_phase = None
        nested_reason = None
        incremental_phase = None
        for line in output.splitlines():
            candidate = line.strip()
            if candidate.startswith("MAKE_INCREMENTAL_PHASE="):
                value = candidate.partition("=")[2]
                if re.fullmatch(r"[a-z0-9_-]{1,32}", value):
                    incremental_phase = value
            elif candidate.startswith("Failed during: "):
                value = candidate.partition(": ")[2]
                if re.fullmatch(r"[A-Za-z0-9 ._+/-]{1,96}", value):
                    nested_phase = value
            elif candidate.startswith("Reason: "):
                value = candidate.partition(": ")[2]
                value = re.sub(r"[^A-Za-z0-9 .,:;()_+=/\-\[\]%]", "?", value)
                if value:
                    nested_reason = value[:155]
        reason = f"Unit test failed: {unittest_failure}"
        if unittest_failure == (
                "test_parallel_build_is_incremental_and_test_stages_stay_ordered"
        ) and incremental_phase:
            reason += f" [{incremental_phase}]"
        if nested_phase and nested_reason:
            reason += f"; nested {nested_phase}: {nested_reason}"
    elif native_diagnostic is not None:
        reason = native_diagnostic
    elif loaded and "BLOCKED_LOADED_QUALIFICATION" in output:
        reason = "Noninteractive root/sudo authorization is unavailable"
    elif loaded and "QUARANTINED:" in output:
        reason = None
        for line in reversed(output.splitlines()):
            candidate = line.strip()
            if not candidate.startswith("QUARANTINED: "):
                continue
            msg = candidate.partition(": ")[2]
            msg = re.sub(r"(?<![A-Za-z0-9])/[^s'\"<>]+", "[path]", msg)
            msg = re.sub(r"\b(?:[a-f0-9]{16,}|[0-9a-f]{8}-[0-9a-f-]{18,})\b",
                         "[id]", msg, flags=re.I)
            msg = re.sub(r"[^A-Za-z0-9 .,:;()_+=/\-\[\]>]", "?", msg)
            reason = f"Safety quarantine: {msg[:155]}"
            break
        if reason is None:
            reason = ("Safety quarantine: owned device or swap identity "
                      "could not be safely released")
    elif loaded and any("mktemp:" in line and "Permission denied" in line
                        for line in output.splitlines()):
        reason = ("Cannot allocate the shared fixture: directory is not writable "
                  "(check build/tests permissions)")
    else:
        # A deliberately small allowlist preserves actionable errors without
        # exposing paths, UUIDs, usernames, raw JSON or system swap entries.
        # Replay helpers may emit a detailed BLOCKED/FAIL line before a generic
        # shell epilogue, so preserve the detailed marker regardless of order.
        reason = None
        for line in reversed(output.splitlines()):
            candidate = line.strip()
            if candidate.startswith("BLOCKED/FAIL: "):
                msg = candidate.partition(": ")[2]
                msg = re.sub(r"(?<![A-Za-z0-9])/[^\s'\"<>]+", "[path]", msg)
                msg = re.sub(r"\b(?:[a-f0-9]{16,}|[0-9a-f]{8}-[0-9a-f-]{18,})\b",
                             "[id]", msg, flags=re.I)
                msg = re.sub(r"[^A-Za-z0-9 .,:;()_+=/\-\[\]]", "?", msg)
                reason = f"FAIL: {msg[:155]}"
                break
        for line in reversed(output.splitlines()) if reason is None else ():
            candidate = line.strip()
            if candidate == "FAIL: test exit 1; safe teardown attempted":
                continue
            if candidate.startswith(("BLOCKED: ", "FAIL: ")):
                msg = candidate.partition(": ")[2]
                msg = re.sub(r"(?<![A-Za-z0-9])/[^\s'\"<>]+", "[path]", msg)
                msg = re.sub(r"\b(?:[a-f0-9]{16,}|[0-9a-f]{8}-[0-9a-f-]{18,})\b",
                             "[id]", msg, flags=re.I)
                msg = re.sub(r"[^A-Za-z0-9 .,:;()_+=/\-\[\]]", "?", msg)
                reason = f"{candidate.split(':', 1)[0]}: {msg[:155]}"
                break
            if ": FAIL:" in candidate:
                msg = candidate.rsplit(": FAIL:", 1)[1].strip()
                msg = re.sub(r"[^A-Za-z0-9 .,:;()_+=/\-\[\]]", "?", msg)
                reason = f"FAIL: {msg[:155]}"
                break
            if "PermissionError:" in candidate or "Permission denied" in candidate:
                reason = "Filesystem permissions rejected the operation"
                break
            if "FileNotFoundError:" in candidate:
                reason = "A required generated file or helper was not found"
                break
            if "AssertionError" in candidate:
                reason = "A fixture, manifest or correctness assertion failed"
                break
            if "TimeoutExpired" in candidate or "timed out" in candidate:
                reason = "Operation exceeded its bounded timeout"
                break
        if reason is None:
            reason = (("Child returned nonzero without a sanitized loaded diagnostic marker")
                      if loaded else
                      "Child returned nonzero in this non-privileged stage")
    return phase, reason

LOADED_PROGRESS_PREFIXES = (
    "START_LOADED_", "PASS_LOADED_", "PASS_RETAINED_SYNTHETIC_",
    "START_OWNED_RAM_REGIME=", "PASS_OWNED_RAM_REGIME=",
    "START_OWNED_RAM_PAIR_ASYNC_PREPARE=", "PASS_OWNED_RAM_PAIR_ASYNC_PREPARE=",
    "START_STORAGE_ENVELOPE=", "PASS_STORAGE_ENVELOPE=",
    "START_DELTA64_RESCUE=", "PASS_DELTA64_RESCUE=",
    "START_READ_COALESCE_AB=", "PASS_READ_COALESCE_AB=",
    "START_SD_READ_COALESCE_AB=", "PASS_SD_READ_COALESCE_AB=",
    "START_WRITE_SATURATION_REGIME=", "PASS_WRITE_SATURATION_REGIME=",
    "START_WRITE_SATURATION_PAIR_QD=", "PASS_WRITE_SATURATION_PAIR_QD=",
    "START_LONE_RAW_QD1=", "PASS_LONE_RAW_QD1=",
    "START_ID36_RESOURCE_PRESSURE=", "PASS_ID36_RESOURCE_PRESSURE=",
)


def loaded_progress_line(line):
    """Return concise live stage-5 progress while retaining full captured output."""
    stripped = line.strip()
    if stripped.startswith(("BLOCKED:", "BLOCKED_LOADED_QUALIFICATION:", "FAIL:")):
        return stripped
    if not stripped.startswith(LOADED_PROGRESS_PREFIXES):
        return None
    if stripped.startswith(("PASS_LOADED_", "PASS_RETAINED_SYNTHETIC_",
                            "START_ID36_RESOURCE_PRESSURE=",
                            "PASS_ID36_RESOURCE_PRESSURE=")):
        return re.split(r"[=:]", stripped, maxsplit=1)[0]
    return stripped


def run_stage(title, command, result, *, parse_bench=False):
    start = time.monotonic()
    try:
        child_env = os.environ.copy()
        tested_source = result.get("tested_commit_sha")
        if isinstance(tested_source, str) and re.fullmatch(
                r"[0-9a-f]{40}", tested_source):
            child_env["SWAPZ_TESTED_SOURCE_SHA"] = tested_source
        if title == "Build module and helpers":
            child_env["SWAPZ_SIGN_NONINTERACTIVE"] = "1"
        if parse_bench:
            print("       loaded qualification progress:")
            proc = subprocess.Popen(
                command, cwd=ROOT, text=True, encoding="utf-8",
                errors="replace", stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, pass_fds=jobserver_fds(),
                env=child_env, bufsize=1)
            chunks = []
            assert proc.stdout is not None
            for line in proc.stdout:
                chunks.append(line)
                progress = loaded_progress_line(line)
                if progress is not None:
                    sys.stdout.write("       " + progress + "\n")
                    sys.stdout.flush()
            rc = proc.wait()
            output = "".join(chunks)
        else:
            proc = subprocess.run(
                command, cwd=ROOT, text=True, encoding="utf-8",
                errors="replace", stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, check=False,
                pass_fds=jobserver_fds(), env=child_env)
            output, rc = proc.stdout, proc.returncode
    except OSError as exc:
        output, rc = type(exc).__name__, 127
    predictor_evidence = parse_predictor_evidence(output)
    gc_scale_evidence = parse_gc_scan_scale_evidence(output)
    extent_geometry_evidence = parse_extent_geometry_evidence(output)
    native_evidence_required = title == "Native and rootless contracts"
    predictor_failure = (native_evidence_required and rc == 0 and
                         predictor_evidence is None)
    gc_scale_failure = (native_evidence_required and rc == 0 and
                        gc_scale_evidence is None)
    extent_geometry_failure = (native_evidence_required and rc == 0 and
                               extent_geometry_evidence is None)
    if predictor_failure or gc_scale_failure or extent_geometry_failure:
        rc = 1
    loaded_correctness = parse_loaded_correctness(output) if parse_bench else None
    parallel_read_sessions = parse_parallel_read_ab(output) if parse_bench else []
    parallel_read_diagnostic = (
        parallel_read_ab_verdict(parallel_read_sessions)
        if parallel_read_sessions else
        {"overall": "NOT_RUN",
         "reason": "promoted fixed-on; routine fan-out A/B retired"})
    read_coalesce_sessions = parse_read_coalesce_ab(output) if parse_bench else []
    read_coalesce_diagnostic = (
        read_coalesce_ab_verdict(read_coalesce_sessions)
        if parse_bench else None)
    sd_coalesce_sessions = parse_sd_read_coalesce_ab(output) if parse_bench else []
    sd_coalesce_diagnostic = (
        sd_read_coalesce_ab_verdict(sd_coalesce_sessions)
        if parse_bench else None)
    lz4_acceleration_sessions = (
        parse_lz4_acceleration(output) if parse_bench else [])
    lz4_acceleration_diagnostic = (
        lz4_acceleration_verdict(lz4_acceleration_sessions)
        if lz4_acceleration_sessions else
        {"overall": "NOT_RUN",
         "reason": "retired; ordinary LZ4 is fixed at acceleration 1"})
    delta64_rescue_sessions = (
        parse_delta64_rescue_sessions(output) if parse_bench else [])
    delta64_rescue_diagnostic = (
        delta64_rescue_verdict(delta64_rescue_sessions)
        if parse_bench else None)
    delta64_prepare_sessions = (
        parse_delta64_prepare_sessions(output) if parse_bench else [])
    delta64_prepare_diagnostic = (
        delta64_prepare_verdict(delta64_prepare_sessions)
        if delta64_prepare_sessions else
        {"overall": "NOT_RUN", "reason": "retired from routine qualification"})
    k1_read_bypass_sessions = (
        parse_k1_read_bypass_ab(output) if parse_bench else [])
    k1_read_bypass_diagnostic = (
        k1_read_bypass_ab_verdict(k1_read_bypass_sessions)
        if k1_read_bypass_sessions else
        {"overall": "NOT_RUN", "reason": "refuted and retired"})
    read_coalesce_cap_sessions = (
        parse_read_coalesce_cap_ab(output) if parse_bench else [])
    read_coalesce_cap_diagnostic = (
        read_coalesce_cap_ab_verdict(read_coalesce_cap_sessions)
        if read_coalesce_cap_sessions else
        {"overall": "NOT_RUN",
         "reason": "retired; production coalescing cap is fixed at 8 blocks"})
    write_pipeline_sessions = (
        parse_write_pipeline_depth(output) if parse_bench else [])
    write_pipeline_diagnostic = (
        write_pipeline_depth_verdict(write_pipeline_sessions)
        if write_pipeline_sessions else
        {"overall": "NOT_RUN",
         "reason": "refuted and retired from routine qualification"})
    storage_envelope_sessions = (
        parse_storage_envelope_sessions(output) if parse_bench else [])
    storage_envelope_diagnostic = (
        storage_envelope_verdict(storage_envelope_sessions)
        if storage_envelope_sessions else
        {"overall": "NOT_RUN", "reason": "storage-envelope sweep not executed"})
    lone_raw_qd1 = (parse_lone_raw_qd1(output) if parse_bench else
                    {"overall": "NOT_RUN"})
    marker_failure = (parse_bench and rc == 0 and
                      (loaded_correctness.get("overall") != "PASS" or
                       read_coalesce_diagnostic.get("overall") !=
                       "PASS_READ_COALESCE_AB_CONFIRMATION" or
                       sd_coalesce_diagnostic.get("overall") !=
                       "PASS_SD_READ_COALESCE_AB_CONFIRMATION" or
                       delta64_rescue_diagnostic.get("overall") !=
                       "PASS_DELTA64_RESCUE_AB" or
                       storage_envelope_diagnostic.get("overall") !=
                       "PASS_DIRECTIONAL_STORAGE_ENVELOPES" or
                       lone_raw_qd1.get("overall") !=
                       "PASS_LONE_RAW_QD1_CANDIDATE"))
    if marker_failure:
        rc = 1
    secure_boot_signing_blocked = (
        title == "Build module and helpers" and any(
            line.startswith("BLOCKED: Secure Boot module signing:")
            for line in output.splitlines()))
    blocked_marker = secure_boot_signing_blocked or (parse_bench and any(
        line.startswith(("BLOCKED:", "BLOCKED_LOADED_QUALIFICATION"))
        for line in output.splitlines()))
    status = ("PASS" if rc == 0 else "BLOCKED" if blocked_marker else "FAIL")
    record = {"name": title, "status": status, "elapsed_s":
              round(time.monotonic() - start, 3), "exit_code": rc}
    if rc:
        record["signals"] = safe_lines(output)
        # The sanitized report may be published via Git only.
        # Do not publish an untrusted last log line: it can contain a host
        # path, swap inventory, block-device identity or local username.
        if predictor_failure:
            record["failed_phase"] = "predictive-compression screening"
            record["diagnostic"] = (
                "Native predictor evidence marker missing, malformed or incomplete")
        elif gc_scale_failure:
            record["failed_phase"] = "garbage-collection map-scan scaling"
            record["diagnostic"] = (
                "Native GC scan scaling marker missing, malformed or incomplete")
        elif extent_geometry_failure:
            record["failed_phase"] = "simulated extent geometry"
            record["diagnostic"] = (
                "Native extent geometry marker missing, malformed or incomplete")
        elif marker_failure:
            if loaded_correctness.get("overall") != "PASS":
                record["failed_phase"] = "owned RAM lifecycle evidence"
                record["diagnostic"] = loaded_correctness.get(
                    "reason", "Loaded correctness evidence is incomplete")
            elif read_coalesce_diagnostic.get("overall") != (
                    "PASS_READ_COALESCE_AB_CONFIRMATION"):
                record["failed_phase"] = "adjacent READ coalescing A/B evidence"
                record["diagnostic"] = read_coalesce_diagnostic.get(
                    "reason", "adjacent-range READ coalescing evidence is incomplete")
            elif sd_coalesce_diagnostic.get("overall") != (
                    "PASS_SD_READ_COALESCE_AB_CONFIRMATION"):
                record["failed_phase"] = "SD adjacent READ coalescing A/B evidence"
                record["diagnostic"] = sd_coalesce_diagnostic.get(
                    "reason", "serial-depth adjacent-range READ coalescing evidence is incomplete")
            elif delta64_rescue_diagnostic.get("overall") != (
                    "PASS_DELTA64_RESCUE_AB"):
                record["failed_phase"] = "delta64 rescue off/on A/B"
                record["diagnostic"] = delta64_rescue_diagnostic.get(
                    "reason", "paired delta64 rescue evidence is incomplete")
            elif storage_envelope_diagnostic.get("overall") != (
                    "PASS_DIRECTIONAL_STORAGE_ENVELOPES"):
                record["failed_phase"] = "modern storage service-envelope evidence"
                record["diagnostic"] = storage_envelope_diagnostic.get(
                    "reason", "storage-envelope evidence is incomplete")
            elif lone_raw_qd1.get("overall") != "PASS_LONE_RAW_QD1_CANDIDATE":
                record["failed_phase"] = "ID161 lone-RAW QD1 candidate"
                record["diagnostic"] = lone_raw_qd1.get(
                    "reason", "lone-RAW QD1 candidate evidence is incomplete")
        else:
            record["failed_phase"], record["diagnostic"] = failure_context(
                output, loaded=parse_bench,
                default_phase=None if parse_bench else title)
    result["stages"].append(record)
    if predictor_evidence is not None:
        result.setdefault("evidence", {})["predictor"] = predictor_evidence
    if gc_scale_evidence is not None:
        result.setdefault("evidence", {})["gc_scan_scale"] = gc_scale_evidence
    if extent_geometry_evidence is not None:
        result.setdefault("evidence", {})["extent_geometry"] = extent_geometry_evidence
    if parse_bench:
        result["benchmarks"]["loaded_correctness"] = loaded_correctness
        result["benchmarks"]["sessions"] = parse_sessions(output)
        result["benchmarks"]["verdicts"] = benchmark_verdicts(
            result["benchmarks"]["sessions"])
        if (loaded_correctness.get("overall") == "PASS" and
                result["benchmarks"]["verdicts"].get("overall") ==
                "PASS_BOUNDED_RAM_MATRIX"):
            result["benchmarks"]["verdicts"]["gc"] = (
                "LIVE_VICTIMS_EXERCISED_OWNED_RAM")
        result["benchmarks"]["parallel_read_ab_sessions"] = parallel_read_sessions
        result["benchmarks"]["parallel_read_ab"] = parallel_read_diagnostic
        result["benchmarks"]["read_coalesce_ab_sessions"] = read_coalesce_sessions
        result["benchmarks"]["read_coalesce_ab"] = read_coalesce_diagnostic
        result["benchmarks"]["sd_read_coalesce_ab_sessions"] = sd_coalesce_sessions
        result["benchmarks"]["sd_read_coalesce_ab"] = sd_coalesce_diagnostic
        result["benchmarks"]["lz4_acceleration_sessions"] = (
            lz4_acceleration_sessions)
        result["benchmarks"]["lz4_acceleration"] = lz4_acceleration_diagnostic
        result["benchmarks"]["delta64_rescue_sessions"] = delta64_rescue_sessions
        result["benchmarks"]["delta64_rescue"] = delta64_rescue_diagnostic
        result["benchmarks"]["delta64_prepare_sessions"] = delta64_prepare_sessions
        result["benchmarks"]["delta64_prepare"] = delta64_prepare_diagnostic
        result["benchmarks"]["k1_read_bypass_sessions"] = k1_read_bypass_sessions
        result["benchmarks"]["k1_read_bypass"] = k1_read_bypass_diagnostic
        result["benchmarks"]["read_coalesce_cap_sessions"] = (
            read_coalesce_cap_sessions)
        result["benchmarks"]["read_coalesce_cap"] = read_coalesce_cap_diagnostic
        result["benchmarks"]["write_saturation_sessions"] = parse_write_saturation(output)
        result["benchmarks"]["write_saturation"] = write_saturation_verdict(
            result["benchmarks"]["write_saturation_sessions"])
        result["benchmarks"]["write_pipeline_depth_sessions"] = (
            write_pipeline_sessions)
        result["benchmarks"]["write_pipeline_depth"] = (
            write_pipeline_diagnostic)
        result["benchmarks"]["storage_envelope_sessions"] = (
            storage_envelope_sessions)
        result["benchmarks"]["storage_envelopes"] = storage_envelope_diagnostic
        result["benchmarks"]["lone_raw_qd1"] = lone_raw_qd1
    print(f"  {len(result['stages']):>2}/5  {title:<29} "
          f"{status:<8} {record['elapsed_s']:>8.2f}s", flush=True)
    if rc and "diagnostic" in record:
        print(f"        Failed during: {record['failed_phase']}", flush=True)
        print(f"        Reason: {record['diagnostic']}", flush=True)
    return rc


def parse_sessions(output):
    sessions, current, regime = [], None, None
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("START_OWNED_RAM_PAIR_ASYNC_PREPARE="):
            current = {"async_prepare": int(line.rsplit("=", 1)[-1]),
                       "regime": regime, "status": "INCOMPLETE", "arms": {},
                       "order": "unknown", "device_model": None}
            sessions.append(current)
        elif line.startswith("START_OWNED_RAM_REGIME="):
            current = None
            regime = line.partition("=")[2]
        elif line.startswith("START_") or line.startswith("PASS_OWNED_RAM_REGIME="):
            current = None
        elif current is not None and line.startswith("REPLAY_ORDER="):
            current["order"] = line.partition("=")[2].strip()
        elif current is not None and line.startswith("PASS_RAM_MODEL_LOWER_MBPS="):
            match = re.fullmatch(
                r"PASS_RAM_MODEL_LOWER_MBPS=(\d+) COMPLETION_NSEC=(\d+) IRQMODE=(\d+) QUEUE_MODE=(\d+) SUBMIT_QUEUES=(\d+) HW_QUEUE_DEPTH=(\d+)",
                line)
            if match:
                current["device_model"] = {
                    "cap_mib_s": int(match.group(1)),
                    "completion_nsec": int(match.group(2)),
                    "irqmode": int(match.group(3)),
                    "queue_mode": int(match.group(4)),
                    "submit_queues": int(match.group(5)),
                    "hw_queue_depth": int(match.group(6)),
                }
        elif current is not None and line.startswith(
                ("SWAPZ_STATUS_BEFORE=", "SWAPZ_STATUS_AFTER=")):
            # Full-process status includes prefill/warmup/post-mixed work.
            # Keep it in the private session log only; report diagnostics come
            # from io-replay's exact timed kernel_write_path snapshots.
            continue
        elif current is not None and line.startswith(
                "PASS_OWNED_RAM_PAIR_ASYNC_PREPARE="):
            current["status"] = "PASS"
            current = None
        elif current is not None and line.startswith(
                "PASS_ASYNC_LOWER_IO_OVERLAP_STARTS="):
            current["overlap_starts"] = int(line.rsplit("=", 1)[-1])
        elif current is not None and line.startswith(
                "PASS_ASYNC_PREPARATION_ACTIVITY="):
            match = re.fullmatch(
                r"PASS_ASYNC_PREPARATION_ACTIVITY="
                r"producer_lower_write_overlap:(\d+) submitter_pages:(\d+)",
                line)
            if match:
                current["overlap_starts"] = int(match.group(1))
                current["submitter_prepared_pages"] = int(match.group(2))
        elif current is not None and line.startswith("{"):
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            if obj.get("candidate") in ("off", "swapz") and \
                    obj.get("verdict") == "PASS":
                candidate = obj["candidate"]
                rates = obj.get("throughput_mbps") or {}
                lower = obj.get("lower_io") or {}
                # Only aggregate numeric values; exclude paths, host IDs,
                # UUIDs, device serials, mounted swap inventory and timing logs.
                current["arms"][candidate] = {
                    "source_sha": obj.get("source_sha"),
                    "fixture_sha256": obj.get("fixture_sha256"),
                    "trace_sha256": obj.get("trace_sha256"),
                    "input_write_mbps": rates.get("logical_write_mbps"),
                    "output_lower_write_mbps": rates.get("lower_write_mbps"),
                    "swap_in_read_mbps": rates.get("logical_read_mbps"),
                    "swap_in_read_p95_ms": (obj.get("read_p95_ns") / 1e6
                                            if isinstance(obj.get("read_p95_ns"), (int, float))
                                            else 0.0),
                    "swap_in_read_p99_ms": (obj.get("read_p99_ns") / 1e6
                                            if isinstance(obj.get("read_p99_ns"), (int, float))
                                            else 0.0),
                    "write_p99_ms": (obj.get("write_p99_ns") / 1e6
                                     if isinstance(obj.get("write_p99_ns"), (int, float))
                                     else 0.0),
                    "lower_write_bytes": lower.get("lower_write_bytes"),
                    "lower_write_requests": lower.get("lower_write_requests"),
                    "lower_read_bytes": lower.get("lower_read_bytes"),
                    "lower_read_requests": lower.get("lower_read_requests"),
                    "verified_pages": obj.get("verified_pages"),
                    "logical_read_bytes": rates.get("logical_read_bytes"),
                    "logical_write_bytes": rates.get("logical_write_bytes"),
                    "seconds": obj.get("seconds"),
                    "mixed_replay_cpu_user_s": obj.get("mixed_replay_cpu_user_s"),
                    "mixed_replay_cpu_system_s": obj.get("mixed_replay_cpu_system_s"),
                    "mixed_replay_peak_rss_kb": obj.get("mixed_replay_peak_rss_kb"),
                    "lower_inflight": lower_inflight_record(obj),
                    "host_cpu": host_cpu_record(obj),
                    "workload_opportunity": workload_opportunity_record(obj),
                    "kernel_write_path": obj.get("kernel_write_path"),
                    "kernel_read_path": obj.get("kernel_read_path"),
                    "packed_read": None,
                }
                packed = obj.get("packed_read")
                if isinstance(packed, dict):
                    measures = {}
                    for mode in ("sequential", "seeded_random"):
                        phase = packed.get("passes", {}).get(mode) or {}
                        lower_read = phase.get("lower_io") or {}
                        measures[mode] = {
                            "logical_bytes": phase.get("logical_bytes"),
                            "verified_pages": phase.get("verified_pages"),
                            "verified_image_sha256": phase.get("verified_image_sha256"),
                            "seconds": phase.get("seconds"),
                            "useful_read_mbps": phase.get("useful_read_mbps"),
                            "read_p99_ms": phase.get("read_p99_ms"),
                            "host_cpu": host_cpu_record(phase),
                            "lower_read_bytes": lower_read.get("lower_read_bytes"),
                            "lower_read_requests": lower_read.get("lower_read_requests"),
                            "kernel_read_path": phase.get("kernel_read_path"),
                            "replay_cpu_user_s": phase.get("replay_cpu_user_s"),
                            "replay_cpu_system_s": phase.get("replay_cpu_system_s"),
                            "replay_peak_rss_kb": phase.get("replay_peak_rss_kb")
                        }
                    current["arms"][candidate]["packed_read"] = {
                        "logical_bytes": packed.get("logical_bytes"),
                        "logical_image_sha256": packed.get("logical_image_sha256"),
                        "packed_close_delta": packed.get("packed_close_delta"),
                        "qualification": packed.get("qualification"),
                        "passes": measures,
                    }
                if obj.get("source_sha"):
                    current["source_sha"] = obj["source_sha"]
                if obj.get("fixture_sha256"):
                    current["fixture_sha256"] = obj["fixture_sha256"]
                if obj.get("trace_sha256"):
                    current["trace_sha256"] = obj["trace_sha256"]
    return sessions




def parse_storage_envelope_sessions(output):
    """Parse directional modern-storage off/swapz pairs without host identity."""
    sessions, current = [], None
    start_re = re.compile(
        r"START_STORAGE_ENVELOPE=(sd_card|sata_ssd|nvme_gen4|nvme_gen5) "
        r"DELTA64_RESCUE=(0|1)")
    pass_re = re.compile(
        r"PASS_STORAGE_ENVELOPE=(sd_card|sata_ssd|nvme_gen4|nvme_gen5) "
        r"DELTA64_RESCUE=(0|1)")
    model_re = re.compile(
        r"PASS_RAM_MODEL_LOWER_MBPS=(\d+) COMPLETION_NSEC=(\d+) "
        r"IRQMODE=(\d+) QUEUE_MODE=(\d+) SUBMIT_QUEUES=(\d+) "
        r"HW_QUEUE_DEPTH=(\d+)")
    for raw in output.splitlines():
        line = raw.strip()
        match = start_re.fullmatch(line)
        if match:
            current = {
                "envelope": match.group(1),
                "delta64_rescue": int(match.group(2)),
                "offered_qd": 32,
                "status": "INCOMPLETE",
                "device_model": None,
                "arms": {},
            }
            sessions.append(current)
            continue
        match = pass_re.fullmatch(line)
        if match:
            if current is not None and (
                    current["envelope"] == match.group(1) and
                    current["delta64_rescue"] == int(match.group(2))):
                current["status"] = "PASS"
            current = None
            continue
        if current is None:
            continue
        match = model_re.fullmatch(line)
        if match:
            current["device_model"] = {
                "cap_mib_s": int(match.group(1)),
                "completion_nsec": int(match.group(2)),
                "irqmode": int(match.group(3)),
                "queue_mode": int(match.group(4)),
                "submit_queues": int(match.group(5)),
                "hw_queue_depth": int(match.group(6)),
                "purpose": STORAGE_ENVELOPE_SPECS[
                    current["envelope"]]["purpose"],
            }
            continue
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        candidate = obj.get("candidate")
        if candidate not in ("off", "swapz") or obj.get("verdict") != "PASS":
            continue
        rates = obj.get("throughput_mbps") or {}
        lower = obj.get("lower_io") or {}
        current["arms"][candidate] = {
            "source_sha": obj.get("source_sha"),
            "fixture_sha256": obj.get("fixture_sha256"),
            "trace_sha256": obj.get("trace_sha256"),
            "input_write_mbps": rates.get("logical_write_mbps"),
            "input_read_mbps": rates.get("logical_read_mbps"),
            "lower_write_bytes": lower.get("lower_write_bytes"),
            "lower_write_requests": lower.get("lower_write_requests"),
            "lower_read_bytes": lower.get("lower_read_bytes"),
            "lower_read_requests": lower.get("lower_read_requests"),
            "write_p99_ms": (obj.get("write_p99_ns") / 1e6
                             if isinstance(obj.get("write_p99_ns"), (int, float))
                             else 0.0),
            "read_p99_ms": (obj.get("read_p99_ns") / 1e6
                            if isinstance(obj.get("read_p99_ns"), (int, float))
                            else 0.0),
            "seconds": obj.get("seconds"),
            "replay_engine": obj.get("replay_engine"),
            "lower_inflight": lower_inflight_record(obj),
            "kernel_write_path": obj.get("kernel_write_path"),
        }
    return sessions



def storage_envelope_verdict(sessions):
    expected = {(name, rescue) for name in STORAGE_ENVELOPE_ORDER
                for rescue in (0, 1)}
    if len(sessions) != len(expected):
        return {"overall": "INCOMPLETE",
                "reason": "eight directional storage-envelope sessions required"}
    observed = {(row.get("envelope"), row.get("delta64_rescue"))
                for row in sessions}
    if observed != expected or len(observed) != len(sessions):
        return {"overall": "INCONCLUSIVE",
                "reason": "storage-envelope model/rescue matrix mismatch"}

    rows = []
    for session in sessions:
        envelope = session["envelope"]
        expected_model = STORAGE_ENVELOPE_SPECS[envelope]
        model = session.get("device_model") or {}
        if (session.get("status") != "PASS" or
                any(model.get(key) != expected_model[key] for key in (
                    "cap_mib_s", "completion_nsec", "irqmode", "queue_mode",
                    "submit_queues", "hw_queue_depth"))):
            return {"overall": "INCONCLUSIVE",
                    "reason": f"{envelope} service envelope was incomplete or changed"}
        arms = session.get("arms") or {}
        if set(arms) != {"off", "swapz"}:
            return {"overall": "INCOMPLETE",
                    "reason": f"{envelope} missing raw/off or swapz arm"}
        off, swapz = arms["off"], arms["swapz"]
        if (off.get("replay_engine") != "native-c" or
                swapz.get("replay_engine") != "native-c"):
            return {"overall": "INCONCLUSIVE",
                    "reason": f"{envelope} did not use the native replay engine"}
        if (off.get("source_sha") != swapz.get("source_sha") or
                off.get("fixture_sha256") != swapz.get("fixture_sha256") or
                off.get("trace_sha256") != swapz.get("trace_sha256")):
            return {"overall": "INCONCLUSIVE",
                    "reason": f"{envelope} did not compare identical source/work"}
        kernel = swapz.get("kernel_write_path") or {}
        if kernel.get("delta64_rescue") != session["delta64_rescue"]:
            return {"overall": "INCONCLUSIVE",
                    "reason": f"{envelope} delta64 policy did not match marker"}
        numeric = (
            off.get("input_write_mbps"), swapz.get("input_write_mbps"),
            off.get("lower_write_bytes"), swapz.get("lower_write_bytes"),
            off.get("lower_write_requests"), swapz.get("lower_write_requests"),
            swapz.get("seconds"),
        )
        if any(type(value) not in (int, float) or not math.isfinite(value) or
               value <= 0 for value in numeric):
            return {"overall": "INCONCLUSIVE",
                    "reason": f"{envelope} missing positive throughput/lower-I/O evidence"}

        byte_speedup = off["lower_write_bytes"] / swapz["lower_write_bytes"]
        request_speedup = (
            off["lower_write_requests"] / swapz["lower_write_requests"])
        useful_speedup = swapz["input_write_mbps"] / off["input_write_mbps"]
        capture = ((useful_speedup - 1.0) / (byte_speedup - 1.0)
                   if byte_speedup > 1.0 else None)
        inflight = swapz.get("lower_inflight") or {}
        elapsed_ns = swapz["seconds"] * 1e9

        def wall_fraction(field):
            value = kernel.get(field)
            return (value / elapsed_ns
                    if type(value) in (int, float) and value >= 0 else None)

        samples = kernel.get("prep_lower_write_samples")
        start_queued = kernel.get("prep_lower_write_start_queued")
        end_queued = kernel.get("prep_lower_write_end_queued")
        start_nonempty = kernel.get("prep_lower_write_start_nonempty")
        end_nonempty = kernel.get("prep_lower_write_end_nonempty")
        if not all(type(value) is int and value >= 0 for value in (
                samples, start_queued, end_queued, start_nonempty,
                end_nonempty)):
            samples = start_queued = end_queued = start_nonempty = end_nonempty = 0

        rows.append({
            "envelope": envelope,
            "delta64_rescue": session["delta64_rescue"],
            "offered_qd": 32,
            "device_model": model,
            "device_limits": device_model_limits(expected_model, offered_qd=32),
            "replay_engine": swapz.get("replay_engine"),
            "byte_speedup": byte_speedup,
            "request_speedup": request_speedup,
            "useful_write_speedup": useful_speedup,
            "bandwidth_opportunity_capture_fraction": capture,
            "swapz_write_depth_peak": inflight.get("write_peak"),
            "swapz_write_depth_mean": inflight.get("write_time_weighted"),
            "k1_ready_wait_windows": kernel.get("k1_ready_wait_windows"),
            "k1_ready_wait_max_records": kernel.get("k1_ready_wait_max_records"),
            "k1_ready_wait_fraction": wall_fraction("k1_ready_wait_wall_ns"),
            "run_slot_active_fraction": wall_fraction("pipeline_active_wall_ns"),
            "post_lower_hold_fraction": wall_fraction("pipeline_post_lower_wall_ns"),
            "preparation_wait_fraction": wall_fraction("prep_wait_wall_ns"),
            "commit_nonio_fraction": wall_fraction("window_commit_nonio_wall_ns"),
            "plan_fraction": wall_fraction("engine_plan_wall_ns"),
            "pack_fraction": wall_fraction("engine_pack_wall_ns"),
            "publish_fraction": wall_fraction("engine_publish_wall_ns"),
            "publish_crc_fraction": wall_fraction("engine_publish_crc_wall_ns"),
            "prep_queue_start_mean": (start_queued / samples if samples else 0.0),
            "prep_queue_end_mean": (end_queued / samples if samples else 0.0),
            "prep_queue_start_nonempty_fraction": (
                start_nonempty / samples if samples else 0.0),
            "prep_queue_end_nonempty_fraction": (
                end_nonempty / samples if samples else 0.0),
        })
    rows.sort(key=lambda row: (
        STORAGE_ENVELOPE_ORDER.index(row["envelope"]),
        row["delta64_rescue"]))
    return {
        "overall": "PASS_DIRECTIONAL_STORAGE_ENVELOPES",
        "scope": "SYNTHETIC_NULL_BLK_DIRECTIONAL_NOT_PHYSICAL_MEDIA",
        "rows": rows,
    }


def parse_lz4_acceleration(output):
    """Parse each terminally bracketed loaded LZ4 acceleration observation."""
    sessions, current = [], None
    model_pattern = re.compile(
        r"PASS_RAM_MODEL_LOWER_MBPS=(\d+) COMPLETION_NSEC=(\d+) "
        r"IRQMODE=(\d+) QUEUE_MODE=(\d+) SUBMIT_QUEUES=(\d+) "
        r"HW_QUEUE_DEPTH=(\d+)")
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("START_LZ4_ACCELERATION="):
            match = re.fullmatch(r"START_LZ4_ACCELERATION=([1-4])", line)
            acceleration = int(match.group(1)) if match else None
            current = {
                "lz4_acceleration": acceleration,
                "async_prepare": 1,
                "regime": "ssd_emulated",
                "status": "INCOMPLETE",
                "arms": {},
                "order": "unknown",
                "device_model": None,
                "parse_error": None,
            }
            sessions.append(current)
            continue
        if line.startswith("START_"):
            current = None
            continue
        if current is None:
            continue
        if line.startswith("REPLAY_ORDER="):
            current["order"] = line.partition("=")[2].strip()
        elif line.startswith("PASS_RAM_MODEL_LOWER_MBPS="):
            match = model_pattern.fullmatch(line)
            if match:
                current["device_model"] = {
                    "cap_mib_s": int(match.group(1)),
                    "completion_nsec": int(match.group(2)),
                    "irqmode": int(match.group(3)),
                    "queue_mode": int(match.group(4)),
                    "submit_queues": int(match.group(5)),
                    "hw_queue_depth": int(match.group(6)),
                }
        elif line.startswith("{"):
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            if obj.get("candidate") not in ("off", "swapz") or \
                    obj.get("verdict") != "PASS":
                continue
            candidate = obj["candidate"]
            if candidate in current["arms"]:
                current["parse_error"] = "duplicate paired arm"
                continue
            rates = obj.get("throughput_mbps") or {}
            lower = obj.get("lower_io") or {}
            current["arms"][candidate] = {
                "source_sha": obj.get("source_sha"),
                "fixture_sha256": obj.get("fixture_sha256"),
                "trace_sha256": obj.get("trace_sha256"),
                "input_write_mbps": rates.get("logical_write_mbps"),
                "output_lower_write_mbps": rates.get("lower_write_mbps"),
                "write_p99_ms": (obj.get("write_p99_ns") / 1e6
                                 if type(obj.get("write_p99_ns")) in
                                 (int, float) else None),
                "lower_write_bytes": lower.get("lower_write_bytes"),
                "lower_write_requests": lower.get("lower_write_requests"),
                "host_cpu": host_cpu_record(obj),
                "kernel_write_path": ({
                    field: obj["kernel_write_path"].get(field)
                    for field in KERNEL_WRITE_FIELDS
                } if isinstance(obj.get("kernel_write_path"), dict) else None),
            }
        elif line.startswith("PASS_LZ4_ACCELERATION="):
            match = re.fullmatch(r"PASS_LZ4_ACCELERATION=(\d+)", line)
            if match and current["lz4_acceleration"] == int(match.group(1)) and \
                    current["parse_error"] is None and \
                    set(current["arms"]) == {"off", "swapz"}:
                current["status"] = "PASS"
            current = None
    return sessions


def lz4_acceleration_verdict(sessions):
    """Require five counterbalanced loaded acceleration-1/4 matched pairs."""
    try:
        pairs = matched_value_pairs(
            sessions, "lz4_acceleration", 1, 4)
    except ValueError as exc:
        return {"overall": "NOT_QUALIFIED", "reason": str(exc)}

    expected_model = MODEL_SPECS["ssd_emulated"]
    provenance = None
    for index, row in enumerate(sessions):
        if row.get("status") != "PASS" or row.get("async_prepare") != 1 or \
                row.get("regime") != "ssd_emulated" or \
                row.get("order") != ("swapz-first" if index % 2 else
                                     "off-first"):
            return {"overall": "NOT_QUALIFIED",
                    "reason": "loaded LZ4 A/B session is incomplete or misordered"}
        model = row.get("device_model")
        if not isinstance(model, dict) or any(
                model.get(key) != expected_model[key]
                for key in ("cap_mib_s", "completion_nsec", "irqmode",
                            "queue_mode", "submit_queues", "hw_queue_depth")):
            return {"overall": "NOT_QUALIFIED",
                    "reason": "loaded LZ4 A/B device model mismatch"}
        if set(row.get("arms", {})) != {"off", "swapz"}:
            return {"overall": "NOT_QUALIFIED",
                    "reason": "loaded LZ4 A/B must retain both paired arms"}
        swapz = row["arms"]["swapz"]
        off = row["arms"]["off"]
        kernel = swapz.get("kernel_write_path")
        error = timed_window_error(kernel)
        if error:
            return {"overall": "NOT_QUALIFIED",
                    "reason": "loaded LZ4 A/B telemetry: " + error}
        if (kernel["lz4_acceleration"] != row["lz4_acceleration"] or
                kernel["delta64_rescue"] != 0):
            return {"overall": "NOT_QUALIFIED",
                    "reason": "loaded LZ4 A/B policy does not match its arm"}
        arm_provenance = tuple(swapz.get(key) for key in
                               BENCHMARK_PROVENANCE_FIELDS)
        off_provenance = tuple(off.get(key) for key in
                               BENCHMARK_PROVENANCE_FIELDS)
        if (not isinstance(arm_provenance[0], str) or
                not re.fullmatch(r"[0-9a-f]{40}", arm_provenance[0]) or
                not isinstance(arm_provenance[1], str) or
                not re.fullmatch(r"[0-9a-f]{64}", arm_provenance[1]) or
                not isinstance(arm_provenance[2], str) or
                not re.fullmatch(r"[0-9a-f]{64}", arm_provenance[2]) or
                arm_provenance != off_provenance):
            return {"overall": "INCONCLUSIVE",
                    "reason": "loaded LZ4 A/B paired provenance is missing or mismatched"}
        if provenance is None:
            provenance = arm_provenance
        elif arm_provenance != provenance:
            return {"overall": "INCONCLUSIVE",
                    "reason": "loaded LZ4 A/B workload differs across sessions"}
        for arm in (off, swapz):
            host = arm.get("host_cpu")
            if (type(arm.get("input_write_mbps")) not in (int, float) or
                    not math.isfinite(arm["input_write_mbps"]) or
                    arm["input_write_mbps"] <= 0 or
                    type(arm.get("lower_write_bytes")) is not int or
                    arm["lower_write_bytes"] <= 0 or
                    type(arm.get("lower_write_requests")) is not int or
                    arm["lower_write_requests"] <= 0 or
                    type(arm.get("write_p99_ms")) not in (int, float) or
                    not math.isfinite(arm["write_p99_ms"]) or
                    arm["write_p99_ms"] <= 0 or
                    not isinstance(host, dict) or
                    host.get("status") != "AVAILABLE" or
                    type(host.get("busy_fraction")) not in (int, float) or
                    type(host.get("pressure_some_fraction")) not in
                    (int, float)):
                return {"overall": "NOT_QUALIFIED",
                        "reason": "loaded LZ4 A/B performance or host-load counters are missing"}
        if any(type(kernel.get(field)) is not int or kernel[field] <= 0
               for field in ("lz4_wall_ns", "ordered_lz4_wall_ns",
                             "prep_lz4_wall_ns", "direct_lz4_input_pages")):
            return {"overall": "NOT_QUALIFIED",
                    "reason": "loaded LZ4 A/B compression timing is missing"}

    modes = {}
    for acceleration in (1, 4):
        rows = [row for row in sessions
                if row["lz4_acceleration"] == acceleration]
        modes[str(acceleration)] = {
            "observations": len(rows),
            "swapz_write_mbps": statistics.mean(
                row["arms"]["swapz"]["input_write_mbps"] for row in rows),
            "swapz_write_p99_ms": statistics.mean(
                row["arms"]["swapz"]["write_p99_ms"] for row in rows),
            "lower_write_bytes": statistics.mean(
                row["arms"]["swapz"]["lower_write_bytes"] for row in rows),
            "lower_write_requests": statistics.mean(
                row["arms"]["swapz"]["lower_write_requests"] for row in rows),
            "lz4_wall_ns": statistics.mean(
                row["arms"]["swapz"]["kernel_write_path"]["lz4_wall_ns"]
                for row in rows),
            "ordered_lz4_wall_ns": statistics.mean(
                row["arms"]["swapz"]["kernel_write_path"]["ordered_lz4_wall_ns"]
                for row in rows),
            "prep_lz4_wall_ns": statistics.mean(
                row["arms"]["swapz"]["kernel_write_path"]["prep_lz4_wall_ns"]
                for row in rows),
            "direct_lz4_input_pages": statistics.mean(
                row["arms"]["swapz"]["kernel_write_path"]
                ["direct_lz4_input_pages"] for row in rows),
            "off_write_mbps": statistics.mean(
                row["arms"]["off"]["input_write_mbps"] for row in rows),
            "host_busy_fraction": statistics.mean(
                row["arms"]["swapz"]["host_cpu"]["busy_fraction"] for row in rows),
            "host_pressure_some_fraction": statistics.mean(
                row["arms"]["swapz"]["host_cpu"]["pressure_some_fraction"]
                for row in rows),
        }

    changes = {
        "throughput_change_fraction": [],
        "p99_change_fraction": [],
        "lower_bytes_change_fraction": [],
        "lower_requests_change_fraction": [],
        "lz4_wall_change_fraction": [],
        "ordered_lz4_wall_change_fraction": [],
        "prep_lz4_wall_change_fraction": [],
        "off_throughput_change_fraction": [],
        "host_busy_delta": [],
        "host_pressure_some_delta": [],
    }
    for pair in pairs:
        a1, a4 = pair[1], pair[4]
        lo, hi = a1["arms"]["swapz"], a4["arms"]["swapz"]
        lo_k, hi_k = lo["kernel_write_path"], hi["kernel_write_path"]
        changes["throughput_change_fraction"].append(
            hi["input_write_mbps"] / lo["input_write_mbps"] - 1.0)
        changes["p99_change_fraction"].append(
            hi["write_p99_ms"] / lo["write_p99_ms"] - 1.0)
        changes["lower_bytes_change_fraction"].append(
            hi["lower_write_bytes"] / lo["lower_write_bytes"] - 1.0)
        changes["lower_requests_change_fraction"].append(
            hi["lower_write_requests"] / lo["lower_write_requests"] - 1.0)
        changes["lz4_wall_change_fraction"].append(
            hi_k["lz4_wall_ns"] / lo_k["lz4_wall_ns"] - 1.0)
        changes["ordered_lz4_wall_change_fraction"].append(
            hi_k["ordered_lz4_wall_ns"] /
            lo_k["ordered_lz4_wall_ns"] - 1.0)
        changes["prep_lz4_wall_change_fraction"].append(
            hi_k["prep_lz4_wall_ns"] / lo_k["prep_lz4_wall_ns"] - 1.0)
        changes["off_throughput_change_fraction"].append(
            a4["arms"]["off"]["input_write_mbps"] /
            a1["arms"]["off"]["input_write_mbps"] - 1.0)
        changes["host_busy_delta"].append(
            hi["host_cpu"]["busy_fraction"] -
            lo["host_cpu"]["busy_fraction"])
        changes["host_pressure_some_delta"].append(
            hi["host_cpu"]["pressure_some_fraction"] -
            lo["host_cpu"]["pressure_some_fraction"])

    return {
        "overall": "PASS_LZ4_ACCELERATION_AB",
        "scope": "PAIRED_SYNTHETIC_RAM_MODEL_ONLY",
        "confidence": "PAIRED_95PCT_CI_REPORTED",
        "matched_pairs": 5,
        "device_model": expected_model,
        "modes": modes,
        "paired": {name: paired_ci95(values)
                   for name, values in changes.items()},
        "interpretation":
            "SAME_SOURCE_ACCEL1_ACCEL4_COUNTERBALANCED_ASYNC_DELTA64_OFF",
    }


def parse_delta64_rescue_sessions(output):
    """Parse the counterbalanced SSD-model delta64 rescue off/on A/B."""
    sessions, current = [], None
    for line in output.splitlines():
        line = line.strip()
        match = re.fullmatch(r"START_DELTA64_RESCUE=(0|1)", line)
        if match:
            current = {
                "rescue": int(match.group(1)), "status": "INCOMPLETE",
                "device_model": None, "arms": {}, "order": "unknown",
            }
            sessions.append(current)
            continue
        if current is None:
            continue
        if line.startswith("REPLAY_ORDER="):
            current["order"] = line.partition("=")[2].strip()
        elif line.startswith("PASS_RAM_MODEL_LOWER_MBPS="):
            model = re.fullmatch(
                r"PASS_RAM_MODEL_LOWER_MBPS=(\d+) COMPLETION_NSEC=(\d+) IRQMODE=(\d+) QUEUE_MODE=(\d+) SUBMIT_QUEUES=(\d+) HW_QUEUE_DEPTH=(\d+)",
                line)
            if model:
                current["device_model"] = {
                    "cap_mib_s": int(model.group(1)),
                    "completion_nsec": int(model.group(2)),
                    "irqmode": int(model.group(3)),
                    "queue_mode": int(model.group(4)),
                    "submit_queues": int(model.group(5)),
                    "hw_queue_depth": int(model.group(6)),
                }
        elif line.startswith("{"):
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            if obj.get("candidate") not in ("off", "swapz") or \
                    obj.get("verdict") != "PASS":
                continue
            candidate = obj["candidate"]
            rates = obj.get("throughput_mbps") or {}
            lower = obj.get("lower_io") or {}
            current["arms"][candidate] = {
                "source_sha": obj.get("source_sha"),
                "fixture_sha256": obj.get("fixture_sha256"),
                "trace_sha256": obj.get("trace_sha256"),
                "write_mbps": rates.get("logical_write_mbps"),
                "lower_write_bytes": lower.get("lower_write_bytes"),
                "lower_write_requests": lower.get("lower_write_requests"),
                "write_p99_ms": (obj.get("write_p99_ns") / 1e6
                                 if type(obj.get("write_p99_ns")) in
                                 (int, float) else None),
                "host_cpu": host_cpu_record(obj),
                "kernel_write_path": obj.get("kernel_write_path"),
            }
        else:
            done = re.fullmatch(r"PASS_DELTA64_RESCUE=(0|1)", line)
            if done and int(done.group(1)) == current["rescue"] and \
                    set(current["arms"]) == {"off", "swapz"}:
                current["status"] = "PASS"
                current = None
    return sessions


def delta64_rescue_verdict(sessions):
    """Require five matched rescue-off/on pairs at fixed async K=1."""
    try:
        pairs = matched_binary_pairs(sessions, "rescue")
    except ValueError as exc:
        return {"overall": "INCOMPLETE", "reason": str(exc)}

    expected = MODEL_SPECS["ssd_emulated"]
    provenance = None
    for index, row in enumerate(sessions):
        if row.get("status") != "PASS" or row.get("order") != (
                "swapz-first" if index % 2 else "off-first"):
            return {"overall": "INCOMPLETE",
                    "reason": "delta64 rescue A/B order/status mismatch"}
        model = row.get("device_model")
        if not isinstance(model, dict) or any(
                model.get(key) != expected[key]
                for key in ("cap_mib_s", "completion_nsec", "irqmode",
                            "queue_mode", "submit_queues", "hw_queue_depth")):
            return {"overall": "INCOMPLETE",
                    "reason": "delta64 rescue A/B device model mismatch"}
        arm, off = row["arms"]["swapz"], row["arms"]["off"]
        kernel = arm.get("kernel_write_path")
        error = timed_window_error(kernel)
        if error:
            return {"overall": "INCOMPLETE",
                    "reason": "delta64 rescue A/B: " + error}
        rescue = row["rescue"]
        if (kernel["delta64_rescue"] != rescue or
                kernel["delta64_lz4_acceleration"] != 4 or
                kernel["write_pipeline_depth"] != 1 or
                kernel["pipeline_active_max"] > 1 or
                kernel["delta64_prepare_workers"] != 1 or
                kernel["delta64_prepare_active_max"] > 1 or
                kernel["delta64_prepare_parallel_starts"]):
            return {"overall": "INCOMPLETE",
                    "reason": "delta64 rescue A/B policy/concurrency mismatch"}
        if rescue:
            # ID150 can prepare every positive-fixture page in the submitting
            # task. delta64_prepare_pages counts only the background producer;
            # retain proof of actual delta64 execution and preparation on
            # either path, not an obsolete producer-only scheduling mandate.
            prepared_pages = (kernel["delta64_prepare_pages"] +
                              kernel["submitter_prepare_pages"])
            if (not kernel["delta64_classifier_pass"] or
                    not kernel["delta64_attempts"] or
                    not kernel["delta64_adopted"] or
                    not prepared_pages or
                    not kernel["delta64_transform_wall_ns"] or
                    not kernel["delta64_wall_ns"]):
                return {"overall": "INCOMPLETE",
                        "reason": "enabled delta64 rescue arm did not exercise rescue"}
        elif any(kernel[field] for field in DELTA64_FIELDS):
            return {"overall": "INCOMPLETE",
                    "reason": "disabled delta64 rescue arm recorded rescue activity"}
        arm_prov = tuple(arm.get(key) for key in BENCHMARK_PROVENANCE_FIELDS)
        off_prov = tuple(off.get(key) for key in BENCHMARK_PROVENANCE_FIELDS)
        if (not isinstance(arm_prov[0], str) or
                not re.fullmatch(r"[0-9a-f]{40}", arm_prov[0]) or
                not isinstance(arm_prov[1], str) or
                not re.fullmatch(r"[0-9a-f]{64}", arm_prov[1]) or
                not isinstance(arm_prov[2], str) or
                not re.fullmatch(r"[0-9a-f]{64}", arm_prov[2]) or
                arm_prov != off_prov):
            return {"overall": "INCONCLUSIVE",
                    "reason": "delta64 rescue paired provenance mismatch"}
        if provenance is None:
            provenance = arm_prov
        elif arm_prov != provenance:
            return {"overall": "INCONCLUSIVE",
                    "reason": "delta64 rescue workload differs across sessions"}
        for candidate in (off, arm):
            if (type(candidate.get("write_mbps")) not in (int, float) or
                    candidate["write_mbps"] <= 0 or
                    type(candidate.get("write_p99_ms")) not in (int, float) or
                    candidate["write_p99_ms"] <= 0 or
                    type(candidate.get("lower_write_bytes")) is not int or
                    candidate["lower_write_bytes"] <= 0 or
                    type(candidate.get("lower_write_requests")) is not int or
                    candidate["lower_write_requests"] <= 0):
                return {"overall": "INCOMPLETE",
                        "reason": "delta64 rescue performance counters missing"}

    modes = {}
    for rescue in (0, 1):
        rows = [row for row in sessions if row["rescue"] == rescue]
        modes[str(rescue)] = {
            "observations": len(rows),
            "write_mbps": statistics.mean(
                row["arms"]["swapz"]["write_mbps"] for row in rows),
            "write_p99_ms": statistics.mean(
                row["arms"]["swapz"]["write_p99_ms"] for row in rows),
            "lower_write_bytes": statistics.mean(
                row["arms"]["swapz"]["lower_write_bytes"] for row in rows),
            "lower_write_requests": statistics.mean(
                row["arms"]["swapz"]["lower_write_requests"] for row in rows),
            "delta64_attempts": statistics.mean(
                row["arms"]["swapz"]["kernel_write_path"]["delta64_attempts"]
                for row in rows),
            "delta64_adopted": statistics.mean(
                row["arms"]["swapz"]["kernel_write_path"]["delta64_adopted"]
                for row in rows),
            "delta64_direct_adopted": statistics.mean(
                row["arms"]["swapz"]["kernel_write_path"]["delta64_direct_adopted"]
                for row in rows),
            "delta64_first_lz4_skipped": statistics.mean(
                row["arms"]["swapz"]["kernel_write_path"]["delta64_first_lz4_skipped"]
                for row in rows),
            "delta64_wall_ns": statistics.mean(
                row["arms"]["swapz"]["kernel_write_path"]["delta64_wall_ns"]
                for row in rows),
        }
    changes = {name: [] for name in (
        "throughput_change_fraction", "p99_change_fraction",
        "lower_bytes_change_fraction", "lower_requests_change_fraction",
        "off_throughput_change_fraction")}
    for pair in pairs:
        disabled, enabled = pair[0], pair[1]
        lo, hi = disabled["arms"]["swapz"], enabled["arms"]["swapz"]
        changes["throughput_change_fraction"].append(
            hi["write_mbps"] / lo["write_mbps"] - 1.0)
        changes["p99_change_fraction"].append(
            hi["write_p99_ms"] / lo["write_p99_ms"] - 1.0)
        changes["lower_bytes_change_fraction"].append(
            hi["lower_write_bytes"] / lo["lower_write_bytes"] - 1.0)
        changes["lower_requests_change_fraction"].append(
            hi["lower_write_requests"] / lo["lower_write_requests"] - 1.0)
        changes["off_throughput_change_fraction"].append(
            enabled["arms"]["off"]["write_mbps"] /
            disabled["arms"]["off"]["write_mbps"] - 1.0)
    return {
        "overall": "PASS_DELTA64_RESCUE_AB",
        "scope": "PAIRED_SYNTHETIC_RAM_MODEL_ONLY",
        "confidence": "FIVE_PAIRED_ROUNDS_SSD_MODEL",
        "matched_pairs": 5,
        "device_model": expected,
        "modes": modes,
        "paired": {name: paired_ci95(values)
                   for name, values in changes.items()},
        "interpretation":
            "SAME_SOURCE_K1_DELTA64_RESCUE_OFF_ON_POSITIVE_FIXTURE_SECOND_LZ4_ACCEL4",
    }


def parse_delta64_prepare_sessions(output):
    """Parse the counterbalanced SSD-model delta64 K=1/K=2 preparation A/B."""
    sessions, current = [], None
    for line in output.splitlines():
        line = line.strip()
        match = re.fullmatch(r"START_DELTA64_PREPARE_WORKERS=(1|2)", line)
        if match:
            current = {
                "workers": int(match.group(1)), "status": "INCOMPLETE",
                "device_model": None, "arms": {}, "order": "unknown",
            }
            sessions.append(current)
            continue
        if current is None:
            continue
        if line.startswith("REPLAY_ORDER="):
            current["order"] = line.partition("=")[2].strip()
        elif line.startswith("PASS_RAM_MODEL_LOWER_MBPS="):
            model = re.fullmatch(
                r"PASS_RAM_MODEL_LOWER_MBPS=(\d+) COMPLETION_NSEC=(\d+) IRQMODE=(\d+) QUEUE_MODE=(\d+) SUBMIT_QUEUES=(\d+) HW_QUEUE_DEPTH=(\d+)",
                line)
            if model:
                current["device_model"] = {
                    "cap_mib_s": int(model.group(1)),
                    "completion_nsec": int(model.group(2)),
                    "irqmode": int(model.group(3)),
                    "queue_mode": int(model.group(4)),
                    "submit_queues": int(model.group(5)),
                    "hw_queue_depth": int(model.group(6)),
                }
        elif line.startswith("{"):
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            if obj.get("candidate") not in ("off", "swapz") or \
                    obj.get("verdict") != "PASS":
                continue
            candidate = obj["candidate"]
            rates = obj.get("throughput_mbps") or {}
            lower = obj.get("lower_io") or {}
            current["arms"][candidate] = {
                "source_sha": obj.get("source_sha"),
                "fixture_sha256": obj.get("fixture_sha256"),
                "trace_sha256": obj.get("trace_sha256"),
                "write_mbps": rates.get("logical_write_mbps"),
                "lower_write_bytes": lower.get("lower_write_bytes"),
                "lower_write_requests": lower.get("lower_write_requests"),
                "write_p99_ms": (obj.get("write_p99_ns") / 1e6
                                 if type(obj.get("write_p99_ns")) in
                                 (int, float) else None),
                "host_cpu": host_cpu_record(obj),
                "kernel_write_path": obj.get("kernel_write_path"),
            }
        else:
            done = re.fullmatch(r"PASS_DELTA64_PREPARE_WORKERS=(1|2)", line)
            if done and int(done.group(1)) == current["workers"] and \
                    set(current["arms"]) == {"off", "swapz"}:
                current["status"] = "PASS"
                current = None
    return sessions


def delta64_prepare_verdict(sessions):
    """Require five counterbalanced K=1/K=2 pairs with real timed overlap."""
    try:
        pairs = matched_value_pairs(sessions, "workers", 1, 2)
    except ValueError as exc:
        return {"overall": "INCOMPLETE", "reason": str(exc)}

    expected = MODEL_SPECS["ssd_emulated"]
    provenance = None
    for index, row in enumerate(sessions):
        if row.get("status") != "PASS" or \
                row.get("order") != ("swapz-first" if index % 2 else
                                     "off-first"):
            return {"overall": "INCOMPLETE",
                    "reason": "delta64 K=1/K=2 A/B did not complete in counterbalanced order"}
        model = row.get("device_model")
        if not isinstance(model, dict) or any(
                model.get(key) != expected[key]
                for key in ("cap_mib_s", "completion_nsec", "irqmode",
                            "queue_mode", "submit_queues", "hw_queue_depth")):
            return {"overall": "INCOMPLETE",
                    "reason": "delta64 K=1/K=2 A/B device model mismatch"}
        if set(row.get("arms", {})) != {"off", "swapz"}:
            return {"overall": "INCOMPLETE",
                    "reason": "delta64 K=1/K=2 A/B requires both paired arms"}
        arm = row["arms"]["swapz"]
        off = row["arms"]["off"]
        kernel = arm.get("kernel_write_path")
        if not isinstance(kernel, dict) or any(
                type(kernel.get(field)) is not int or kernel[field] < 0
                for field in KERNEL_WRITE_FIELDS):
            return {"overall": "INCOMPLETE",
                    "reason": "delta64 K=1/K=2 A/B telemetry missing"}
        error = timed_window_error(kernel)
        if error:
            return {"overall": "INCOMPLETE",
                    "reason": "delta64 K=1/K=2 A/B: " + error}
        workers = row["workers"]
        if (kernel["delta64_rescue"] != 1 or
                kernel["delta64_prepare_workers"] != workers):
            return {"overall": "INCOMPLETE",
                    "reason": "delta64 K=1/K=2 A/B policy mismatch"}
        if (not kernel["delta64_classifier_pass"] or
                not kernel["delta64_attempts"] or
                not kernel["delta64_adopted"] or
                not kernel["delta64_prepare_pages"]):
            return {"overall": "INCOMPLETE",
                    "reason": "delta64 K=1/K=2 A/B did not exercise rescue and producer lanes"}
        if any(kernel[field] <= 0 for field in (
                "delta64_transform_wall_ns", "delta64_wall_ns",
                "prep_lz4_wall_ns", "prep_worker_cpu_ns")):
            return {"overall": "INCOMPLETE",
                    "reason": "delta64 K=1/K=2 timing or worker CPU evidence is missing"}
        if workers == 1 and (
                kernel["delta64_prepare_active_max"] > 1 or
                kernel["delta64_prepare_parallel_starts"]):
            return {"overall": "INCOMPLETE",
                    "reason": "K=1 delta64 preparation unexpectedly overlapped"}
        if workers == 2 and (
                kernel["delta64_prepare_active_max"] <= 1 or
                not kernel["delta64_prepare_parallel_starts"]):
            return {"overall": "INCOMPLETE",
                    "reason": "K=2 delta64 preparation never overlapped during timed replay"}
        arm_provenance = tuple(arm.get(key) for key in
                               BENCHMARK_PROVENANCE_FIELDS)
        off_provenance = tuple(off.get(key) for key in
                               BENCHMARK_PROVENANCE_FIELDS)
        if (not isinstance(arm_provenance[0], str) or
                not re.fullmatch(r"[0-9a-f]{40}", arm_provenance[0]) or
                not isinstance(arm_provenance[1], str) or
                not re.fullmatch(r"[0-9a-f]{64}", arm_provenance[1]) or
                not isinstance(arm_provenance[2], str) or
                not re.fullmatch(r"[0-9a-f]{64}", arm_provenance[2]) or
                arm_provenance != off_provenance):
            return {"overall": "INCONCLUSIVE",
                    "reason": "delta64 K=1/K=2 paired provenance is missing or mismatched"}
        if provenance is None:
            provenance = arm_provenance
        elif arm_provenance != provenance:
            return {"overall": "INCONCLUSIVE",
                    "reason": "delta64 K=1/K=2 workload differs across sessions"}
        for candidate in (off, arm):
            host = candidate.get("host_cpu")
            if (type(candidate.get("write_mbps")) not in (int, float) or
                    candidate["write_mbps"] <= 0 or
                    type(candidate.get("write_p99_ms")) not in (int, float) or
                    candidate["write_p99_ms"] <= 0 or
                    type(candidate.get("lower_write_bytes")) is not int or
                    candidate["lower_write_bytes"] <= 0 or
                    type(candidate.get("lower_write_requests")) is not int or
                    candidate["lower_write_requests"] <= 0 or
                    not isinstance(host, dict) or
                    host.get("status") != "AVAILABLE" or
                    type(host.get("busy_fraction")) not in (int, float) or
                    type(host.get("pressure_some_fraction")) not in
                    (int, float)):
                return {"overall": "INCOMPLETE",
                        "reason": "delta64 K=1/K=2 performance or host-load counters missing"}

    for pair in pairs:
        k1 = pair[1]["arms"]["swapz"]["kernel_write_path"]
        k2 = pair[2]["arms"]["swapz"]["kernel_write_path"]
        for field in ("delta64_attempts", "delta64_adopted",
                      "delta64_payload_bytes_saved"):
            if k1[field] != k2[field]:
                return {"overall": "INCONCLUSIVE",
                        "reason": f"delta64 K=1/K=2 useful work differs for {field}"}

    modes = {}
    for workers in (1, 2):
        rows = [row for row in sessions if row["workers"] == workers]
        modes[str(workers)] = {
            "observations": len(rows),
            "write_mbps": statistics.mean(
                row["arms"]["swapz"]["write_mbps"] for row in rows),
            "write_p99_ms": statistics.mean(
                row["arms"]["swapz"]["write_p99_ms"] for row in rows),
            "lower_write_bytes": statistics.mean(
                row["arms"]["swapz"]["lower_write_bytes"] for row in rows),
            "lower_write_requests": statistics.mean(
                row["arms"]["swapz"]["lower_write_requests"] for row in rows),
            "prepare_active_max": max(
                row["arms"]["swapz"]["kernel_write_path"]
                ["delta64_prepare_active_max"] for row in rows),
            "prepare_pages": statistics.mean(
                row["arms"]["swapz"]["kernel_write_path"]
                ["delta64_prepare_pages"] for row in rows),
            "prepare_parallel_starts": statistics.mean(
                row["arms"]["swapz"]["kernel_write_path"]
                ["delta64_prepare_parallel_starts"] for row in rows),
            "delta64_attempts": statistics.mean(
                row["arms"]["swapz"]["kernel_write_path"]
                ["delta64_attempts"] for row in rows),
            "delta64_adopted": statistics.mean(
                row["arms"]["swapz"]["kernel_write_path"]
                ["delta64_adopted"] for row in rows),
            "delta64_payload_bytes_saved": statistics.mean(
                row["arms"]["swapz"]["kernel_write_path"]
                ["delta64_payload_bytes_saved"] for row in rows),
            "delta64_transform_wall_ns": statistics.mean(
                row["arms"]["swapz"]["kernel_write_path"]
                ["delta64_transform_wall_ns"] for row in rows),
            "delta64_wall_ns": statistics.mean(
                row["arms"]["swapz"]["kernel_write_path"]
                ["delta64_wall_ns"] for row in rows),
            "prep_lz4_wall_ns": statistics.mean(
                row["arms"]["swapz"]["kernel_write_path"]
                ["prep_lz4_wall_ns"] for row in rows),
            "prep_worker_cpu_ns": statistics.mean(
                row["arms"]["swapz"]["kernel_write_path"]
                ["prep_worker_cpu_ns"] for row in rows),
            "host_busy_fraction": statistics.mean(
                row["arms"]["swapz"]["host_cpu"]["busy_fraction"] for row in rows),
            "host_pressure_some_fraction": statistics.mean(
                row["arms"]["swapz"]["host_cpu"]["pressure_some_fraction"]
                for row in rows),
        }

    changes = {
        "throughput_change_fraction": [],
        "p99_change_fraction": [],
        "lower_bytes_change_fraction": [],
        "lower_requests_change_fraction": [],
        "delta64_wall_change_fraction": [],
        "transform_wall_change_fraction": [],
        "prep_lz4_wall_change_fraction": [],
        "prep_worker_cpu_change_fraction": [],
        "off_throughput_change_fraction": [],
        "host_busy_delta": [],
        "host_pressure_some_delta": [],
    }
    for pair in pairs:
        r1, r2 = pair[1], pair[2]
        k1, k2 = r1["arms"]["swapz"], r2["arms"]["swapz"]
        w1, w2 = k1["kernel_write_path"], k2["kernel_write_path"]
        changes["throughput_change_fraction"].append(
            k2["write_mbps"] / k1["write_mbps"] - 1.0)
        changes["p99_change_fraction"].append(
            k2["write_p99_ms"] / k1["write_p99_ms"] - 1.0)
        changes["lower_bytes_change_fraction"].append(
            k2["lower_write_bytes"] / k1["lower_write_bytes"] - 1.0)
        changes["lower_requests_change_fraction"].append(
            k2["lower_write_requests"] / k1["lower_write_requests"] - 1.0)
        changes["delta64_wall_change_fraction"].append(
            w2["delta64_wall_ns"] / w1["delta64_wall_ns"] - 1.0)
        changes["transform_wall_change_fraction"].append(
            w2["delta64_transform_wall_ns"] /
            w1["delta64_transform_wall_ns"] - 1.0)
        changes["prep_lz4_wall_change_fraction"].append(
            w2["prep_lz4_wall_ns"] / w1["prep_lz4_wall_ns"] - 1.0)
        changes["prep_worker_cpu_change_fraction"].append(
            w2["prep_worker_cpu_ns"] / w1["prep_worker_cpu_ns"] - 1.0)
        changes["off_throughput_change_fraction"].append(
            r2["arms"]["off"]["write_mbps"] /
            r1["arms"]["off"]["write_mbps"] - 1.0)
        changes["host_busy_delta"].append(
            k2["host_cpu"]["busy_fraction"] -
            k1["host_cpu"]["busy_fraction"])
        changes["host_pressure_some_delta"].append(
            k2["host_cpu"]["pressure_some_fraction"] -
            k1["host_cpu"]["pressure_some_fraction"])

    return {
        "overall": "PASS_DELTA64_PREPARE_AB",
        "qualification": "PAIRED_SYNTHETIC_RAM_ONLY",
        "confidence": "PAIRED_95PCT_CI_REPORTED",
        "matched_pairs": 5,
        "device_model": expected,
        "modes": modes,
        "paired": {name: paired_ci95(values)
                   for name, values in changes.items()},
        "interpretation":
            "SAME_SOURCE_K1_K2_COUNTERBALANCED_POSITIVE_FIXTURE_ORDERED_PUBLICATION_UNCHANGED",
    }


def _parse_policy_evidence_sessions(output, marker, values):
    """Parse private same-source policy evidence emitted by test-loaded.sh."""
    start_re = re.compile(
        r"START_" + marker + r"=(sd_emulated|ssd_emulated):(" +
        "|".join(str(value) for value in values) + r")")
    pass_re = re.compile(
        r"PASS_" + marker + r"=(sd_emulated|ssd_emulated):(" +
        "|".join(str(value) for value in values) + r")")
    sessions, current = [], None
    for line in output.splitlines():
        line = line.strip()
        match = start_re.fullmatch(line)
        if match:
            current = {
                "regime": match.group(1), "value": int(match.group(2)),
                "status": "INCOMPLETE", "order": "unknown",
                "device_model": None, "swapz": None,
            }
            sessions.append(current)
            continue
        if current is None:
            continue
        if line.startswith("REPLAY_ORDER="):
            current["order"] = line.partition("=")[2].strip()
        elif line.startswith("PASS_RAM_MODEL_LOWER_MBPS="):
            model = re.fullmatch(
                r"PASS_RAM_MODEL_LOWER_MBPS=(\d+) COMPLETION_NSEC=(\d+) "
                r"IRQMODE=(\d+) QUEUE_MODE=(\d+) SUBMIT_QUEUES=(\d+) "
                r"HW_QUEUE_DEPTH=(\d+)", line)
            if model:
                current["device_model"] = {
                    "cap_mib_s": int(model.group(1)),
                    "completion_nsec": int(model.group(2)),
                    "irqmode": int(model.group(3)),
                    "queue_mode": int(model.group(4)),
                    "submit_queues": int(model.group(5)),
                    "hw_queue_depth": int(model.group(6)),
                }
        elif line.startswith("{"):
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            if obj.get("candidate") != "swapz" or obj.get("verdict") != "PASS":
                continue
            rates = obj.get("throughput_mbps") or {}
            lower = obj.get("lower_io") or {}
            packed = obj.get("packed_read") or {}
            packed_passes = {}
            for mode in ("sequential", "seeded_random"):
                phase = (packed.get("passes") or {}).get(mode) or {}
                lower_read = phase.get("lower_io") or {}
                packed_passes[mode] = {
                    "useful_read_mbps": phase.get("useful_read_mbps"),
                    "read_p99_ms": phase.get("read_p99_ms"),
                    "lower_read_bytes": lower_read.get("lower_read_bytes"),
                    "lower_read_requests": lower_read.get("lower_read_requests"),
                    "kernel_read_path": phase.get("kernel_read_path"),
                }
            current["swapz"] = {
                "source_sha": obj.get("source_sha"),
                "fixture_sha256": obj.get("fixture_sha256"),
                "trace_sha256": obj.get("trace_sha256"),
                "write_mbps": rates.get("logical_write_mbps"),
                "read_mbps": rates.get("logical_read_mbps"),
                "read_p99_ms": (obj.get("read_p99_ns", 0) / 1e6
                                if isinstance(obj.get("read_p99_ns"), (int, float))
                                else None),
                "lower_write_requests": lower.get("lower_write_requests"),
                "lower_read_requests": lower.get("lower_read_requests"),
                "kernel_write_path": obj.get("kernel_write_path"),
                "packed_passes": packed_passes,
            }
        else:
            done = pass_re.fullmatch(line)
            if done and done.group(1) == current["regime"] and \
                    int(done.group(2)) == current["value"] and \
                    current["swapz"] is not None:
                current["status"] = "PASS"
                current = None
    return sessions


def parse_k1_read_bypass_ab(output):
    return _parse_policy_evidence_sessions(
        output, "K1_READ_BYPASS_AB", (0, 1))


def k1_read_bypass_ab_verdict(sessions):
    verdict = {}
    for regime in MODEL_ORDER:
        rows = [row for row in sessions if row.get("regime") == regime]
        paired_rows = [{"allow": row["value"], **row} for row in rows]
        try:
            pairs = matched_binary_pairs(paired_rows, "allow")
        except ValueError as exc:
            return {"overall": "INCOMPLETE",
                    "reason": f"{regime}: {exc}"}
        expected = MODEL_SPECS[regime]
        provenance = None
        for index, row in enumerate(rows):
            if row.get("status") != "PASS" or row.get("order") != (
                    "swapz-first" if index % 2 else "off-first"):
                return {"overall": "INCOMPLETE",
                        "reason": f"{regime}: K=1 read-bypass order/status mismatch"}
            model = row.get("device_model")
            if not isinstance(model, dict) or any(
                    model.get(key) != expected[key]
                    for key in ("cap_mib_s", "completion_nsec", "irqmode",
                                "queue_mode", "submit_queues", "hw_queue_depth")):
                return {"overall": "INCOMPLETE",
                        "reason": f"{regime}: K=1 read-bypass device model mismatch"}
            arm = row.get("swapz") or {}
            kernel = arm.get("kernel_write_path")
            error = timed_window_error(kernel)
            if error:
                return {"overall": "INCOMPLETE",
                        "reason": f"{regime}: K=1 read-bypass telemetry: {error}"}
            allow = row["value"]
            if (kernel["k1_allow_after_read_bypass"] != allow or
                    kernel["invalidate_cache_on_write_admit"] != 0 or
                    kernel["read_coalesce_max_blocks"] != 8):
                return {"overall": "INCOMPLETE",
                        "reason": f"{regime}: K=1 read-bypass policy mismatch"}
            if allow == 0 and not kernel["pipeline_read_bypass_skips"]:
                return {"overall": "INCONCLUSIVE",
                        "reason": f"{regime}: control arm hit no read-bypass detach block"}
            if allow == 1 and kernel["pipeline_read_bypass_skips"]:
                return {"overall": "INCOMPLETE",
                        "reason": f"{regime}: enabled arm still counted blocked detach skips"}
            arm_provenance = tuple(arm.get(key) for key in
                                   BENCHMARK_PROVENANCE_FIELDS)
            if (not isinstance(arm_provenance[0], str) or
                    not re.fullmatch(r"[0-9a-f]{40}", arm_provenance[0]) or
                    not isinstance(arm_provenance[1], str) or
                    not re.fullmatch(r"[0-9a-f]{64}", arm_provenance[1]) or
                    not isinstance(arm_provenance[2], str) or
                    not re.fullmatch(r"[0-9a-f]{64}", arm_provenance[2])):
                return {"overall": "INCONCLUSIVE",
                        "reason": f"{regime}: K=1 read-bypass provenance missing"}
            if provenance is None:
                provenance = arm_provenance
            elif arm_provenance != provenance:
                return {"overall": "INCONCLUSIVE",
                        "reason": f"{regime}: K=1 read-bypass workload differs"}
            for field in ("write_mbps", "read_p99_ms",
                          "lower_write_requests", "lower_read_requests"):
                if not isinstance(arm.get(field), (int, float)) or arm[field] <= 0:
                    return {"overall": "INCOMPLETE",
                            "reason": f"{regime}: K=1 read-bypass metric missing"}

        modes = {}
        for allow in (0, 1):
            selected = [row["swapz"] for row in rows if row["value"] == allow]
            modes[str(allow)] = {
                "observations": len(selected),
                "write_mbps": statistics.mean(row["write_mbps"] for row in selected),
                "read_p99_ms": statistics.mean(row["read_p99_ms"] for row in selected),
                "lower_write_requests": statistics.mean(
                    row["lower_write_requests"] for row in selected),
                "lower_read_requests": statistics.mean(
                    row["lower_read_requests"] for row in selected),
                "pipeline_read_bypass_skips": statistics.mean(
                    row["kernel_write_path"]["pipeline_read_bypass_skips"]
                    for row in selected),
                "prep_lower_write_overlap_starts": statistics.mean(
                    row["kernel_write_path"]["prep_lower_write_overlap_starts"]
                    for row in selected),
                "prep_lower_write_overlap_ns": statistics.mean(
                    row["kernel_write_path"]["prep_lower_write_overlap_ns"]
                    for row in selected),
                "pipeline_async_runs": statistics.mean(
                    row["kernel_write_path"]["pipeline_async_runs"]
                    for row in selected),
            }
        changes = {
            "throughput_change_fraction": [],
            "read_p99_change_fraction": [],
            "lower_write_requests_change_fraction": [],
            "lower_read_requests_change_fraction": [],
            "overlap_starts_delta": [],
            "overlap_ns_delta": [],
            "pipeline_async_runs_delta": [],
        }
        for pair in pairs:
            control = pair[0]["swapz"]
            enabled = pair[1]["swapz"]
            kc, ke = control["kernel_write_path"], enabled["kernel_write_path"]
            changes["throughput_change_fraction"].append(
                enabled["write_mbps"] / control["write_mbps"] - 1.0)
            changes["read_p99_change_fraction"].append(
                enabled["read_p99_ms"] / control["read_p99_ms"] - 1.0)
            changes["lower_write_requests_change_fraction"].append(
                enabled["lower_write_requests"] /
                control["lower_write_requests"] - 1.0)
            changes["lower_read_requests_change_fraction"].append(
                enabled["lower_read_requests"] /
                control["lower_read_requests"] - 1.0)
            changes["overlap_starts_delta"].append(
                ke["prep_lower_write_overlap_starts"] -
                kc["prep_lower_write_overlap_starts"])
            changes["overlap_ns_delta"].append(
                ke["prep_lower_write_overlap_ns"] -
                kc["prep_lower_write_overlap_ns"])
            changes["pipeline_async_runs_delta"].append(
                ke["pipeline_async_runs"] - kc["pipeline_async_runs"])
        verdict[regime] = {
            "device_model": expected,
            "modes": modes,
            "paired": {name: paired_ci95(values)
                       for name, values in changes.items()},
        }
    return {
        "overall": "PASS_K1_READ_BYPASS_AB_EVIDENCE",
        "confidence": "FIVE_PAIRED_ROUNDS_PER_MODEL",
        "regimes": verdict,
        "interpretation":
            "SAME_SOURCE_DEFAULT_OFF_K1_READ_BYPASS_DETACH_ELIGIBILITY_ONLY",
    }


def parse_read_coalesce_cap_ab(output):
    return _parse_policy_evidence_sessions(
        output, "READ_COALESCE_CAP_AB", (2, 4, 8))


def read_coalesce_cap_ab_verdict(sessions):
    verdict = {}
    for regime in MODEL_ORDER:
        rows = [row for row in sessions if row.get("regime") == regime]
        if len(rows) != len(READ_COALESCE_CAP_SEQUENCE) or \
                [row.get("value") for row in rows] != \
                list(READ_COALESCE_CAP_SEQUENCE):
            return {"overall": "INCOMPLETE",
                    "reason": f"{regime}: balanced 2/4/8 cap rounds missing"}
        expected = MODEL_SPECS[regime]
        provenance = None
        for index, row in enumerate(rows):
            if row.get("status") != "PASS" or row.get("order") != (
                    "swapz-first" if index % 2 else "off-first"):
                return {"overall": "INCOMPLETE",
                        "reason": f"{regime}: cap study order/status mismatch"}
            model = row.get("device_model")
            if not isinstance(model, dict) or any(
                    model.get(key) != expected[key]
                    for key in ("cap_mib_s", "completion_nsec", "irqmode",
                                "queue_mode", "submit_queues", "hw_queue_depth")):
                return {"overall": "INCOMPLETE",
                        "reason": f"{regime}: cap study device model mismatch"}
            arm = row.get("swapz") or {}
            arm_provenance = tuple(arm.get(key) for key in
                                   BENCHMARK_PROVENANCE_FIELDS)
            if (not isinstance(arm_provenance[0], str) or
                    not re.fullmatch(r"[0-9a-f]{40}", arm_provenance[0]) or
                    not isinstance(arm_provenance[1], str) or
                    not re.fullmatch(r"[0-9a-f]{64}", arm_provenance[1]) or
                    not isinstance(arm_provenance[2], str) or
                    not re.fullmatch(r"[0-9a-f]{64}", arm_provenance[2])):
                return {"overall": "INCONCLUSIVE",
                        "reason": f"{regime}: cap-study provenance missing"}
            if provenance is None:
                provenance = arm_provenance
            elif arm_provenance != provenance:
                return {"overall": "INCONCLUSIVE",
                        "reason": f"{regime}: cap-study workload differs"}
            for mode in ("sequential", "seeded_random"):
                phase = (arm.get("packed_passes") or {}).get(mode) or {}
                kernel = phase.get("kernel_read_path")
                if not isinstance(kernel, dict) or any(
                        type(kernel.get(field)) is not int or kernel[field] < 0
                        for field in KERNEL_READ_FIELDS):
                    return {"overall": "INCOMPLETE",
                            "reason": f"{regime}: cap-study READ telemetry missing"}
                if kernel["read_coalesce_max_blocks"] != row["value"]:
                    return {"overall": "INCOMPLETE",
                            "reason": f"{regime}: cap-study policy mismatch"}
                if kernel["parallel_read_coalesce_extra_blocks"]:
                    return {"overall": "INCOMPLETE",
                            "reason": f"{regime}: cap study read extra blocks"}
                for field in ("useful_read_mbps", "read_p99_ms",
                              "lower_read_bytes", "lower_read_requests"):
                    if not isinstance(phase.get(field), (int, float)) or \
                            phase[field] <= 0:
                        return {"overall": "INCOMPLETE",
                                "reason": f"{regime}: cap-study metric missing"}

        modes = {}
        for cap in (2, 4, 8):
            selected = [row["swapz"] for row in rows if row["value"] == cap]
            modes[str(cap)] = {}
            for mode in ("sequential", "seeded_random"):
                phases = [row["packed_passes"][mode] for row in selected]
                modes[str(cap)][mode] = {
                    "useful_read_mbps": statistics.mean(
                        phase["useful_read_mbps"] for phase in phases),
                    "read_p99_ms": statistics.mean(
                        phase["read_p99_ms"] for phase in phases),
                    "lower_read_bytes": statistics.mean(
                        phase["lower_read_bytes"] for phase in phases),
                    "lower_read_requests": statistics.mean(
                        phase["lower_read_requests"] for phase in phases),
                    "coalesced_requests_saved": statistics.mean(
                        phase["kernel_read_path"]
                        ["parallel_read_coalesced_reqs_saved"]
                        for phase in phases),
                }

        rounds = []
        for offset in range(0, len(rows), 3):
            group = rows[offset:offset + 3]
            rounds.append({row["value"]: row for row in group})
        comparisons = {}
        for low, high in ((2, 4), (4, 8), (2, 8)):
            comparison = {}
            for mode in ("sequential", "seeded_random"):
                changes = {
                    "throughput_change_fraction": [],
                    "p99_change_fraction": [],
                    "lower_bytes_change_fraction": [],
                    "lower_requests_change_fraction": [],
                }
                for group in rounds:
                    a = group[low]["swapz"]["packed_passes"][mode]
                    b = group[high]["swapz"]["packed_passes"][mode]
                    changes["throughput_change_fraction"].append(
                        b["useful_read_mbps"] / a["useful_read_mbps"] - 1.0)
                    changes["p99_change_fraction"].append(
                        b["read_p99_ms"] / a["read_p99_ms"] - 1.0)
                    changes["lower_bytes_change_fraction"].append(
                        b["lower_read_bytes"] / a["lower_read_bytes"] - 1.0)
                    changes["lower_requests_change_fraction"].append(
                        b["lower_read_requests"] / a["lower_read_requests"] - 1.0)
                comparison[mode] = {
                    name: paired_ci95(values)
                    for name, values in changes.items()
                }
            comparisons[f"{high}_vs_{low}"] = comparison
        verdict[regime] = {
            "device_model": expected,
            "modes": modes,
            "paired": comparisons,
        }
    return {
        "overall": "PASS_READ_COALESCE_CAP_EVIDENCE",
        "confidence": "FIVE_BALANCED_THREE_ARM_ROUNDS_PER_MODEL",
        "regimes": verdict,
        "interpretation":
            "SAME_SOURCE_ZERO_EXTRA_READ_COALESCE_CAP_2_4_8",
    }


def parse_parallel_read_ab(output):
    """Parse the final five-pair fast-model independent READ fan-out decision."""
    sessions, current = [], None
    for line in output.splitlines():
        line = line.strip()
        match = re.fullmatch(r"START_PARALLEL_READ_AB=([01])", line)
        if match:
            current = {
                "parallel_reads": int(match.group(1)),
                "status": "INCOMPLETE", "order": "unknown",
                "device_model": None, "arms": {},
            }
            sessions.append(current)
            continue
        if current is None:
            continue
        if line.startswith("REPLAY_ORDER="):
            current["order"] = line.partition("=")[2].strip()
        elif line.startswith("PASS_RAM_MODEL_LOWER_MBPS="):
            model = re.fullmatch(
                r"PASS_RAM_MODEL_LOWER_MBPS=(\d+) COMPLETION_NSEC=(\d+) "
                r"IRQMODE=(\d+) QUEUE_MODE=(\d+) SUBMIT_QUEUES=(\d+) "
                r"HW_QUEUE_DEPTH=(\d+)", line)
            if model:
                current["device_model"] = {
                    "cap_mib_s": int(model.group(1)),
                    "completion_nsec": int(model.group(2)),
                    "irqmode": int(model.group(3)),
                    "queue_mode": int(model.group(4)),
                    "submit_queues": int(model.group(5)),
                    "hw_queue_depth": int(model.group(6)),
                }
        elif line.startswith("{"):
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            candidate = obj.get("candidate")
            if candidate not in ("off", "swapz") or obj.get("verdict") != "PASS":
                continue
            rates = obj.get("throughput_mbps") or {}
            lower = obj.get("lower_io") or {}
            packed = obj.get("packed_read") or {}
            passes = {}
            for mode in ("sequential", "seeded_random"):
                phase = (packed.get("passes") or {}).get(mode) or {}
                phase_lower = phase.get("lower_io") or {}
                passes[mode] = {
                    "logical_bytes": phase.get("logical_bytes"),
                    "verified_pages": phase.get("verified_pages"),
                    "verified_image_sha256": phase.get("verified_image_sha256"),
                    "useful_read_mbps": phase.get("useful_read_mbps"),
                    "read_p99_ms": phase.get("read_p99_ms"),
                    "lower_read_bytes": phase_lower.get("lower_read_bytes"),
                    "lower_read_requests": phase_lower.get("lower_read_requests"),
                    "kernel_read_path": phase.get("kernel_read_path"),
                }
            current["arms"][candidate] = {
                "source_sha": obj.get("source_sha"),
                "fixture_sha256": obj.get("fixture_sha256"),
                "trace_sha256": obj.get("trace_sha256"),
                "input_write_mbps": rates.get("logical_write_mbps"),
                "swap_in_read_mbps": rates.get("logical_read_mbps"),
                "read_p99_ms": (obj.get("read_p99_ns") / 1e6
                                if isinstance(obj.get("read_p99_ns"), (int, float))
                                else None),
                "lower_read_bytes": lower.get("lower_read_bytes"),
                "lower_read_requests": lower.get("lower_read_requests"),
                "kernel_read_path": obj.get("kernel_read_path"),
                "logical_image_sha256": packed.get("logical_image_sha256"),
                "packed_close_delta": packed.get("packed_close_delta"),
                "passes": passes,
            }
        else:
            done = re.fullmatch(r"PASS_PARALLEL_READ_AB=([01])", line)
            if done and int(done.group(1)) == current["parallel_reads"]:
                current["status"] = "PASS"
                current = None
    return sessions


def parallel_read_ab_verdict(sessions):
    """Validate isolated fan-out with ID63 disabled; report decision evidence only."""
    try:
        pairs = matched_binary_pairs(sessions, "parallel_reads")
    except ValueError as exc:
        return {"overall": "INCOMPLETE", "reason": str(exc)}
    expected = MODEL_SPECS["ssd_emulated"]
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
    for index, row in enumerate(sessions):
        if row.get("status") != "PASS" or row.get("order") != (
                "swapz-first" if index % 2 else "off-first"):
            return {"overall": "INCOMPLETE",
                    "reason": "independent READ fan-out requires five counterbalanced matched rounds with matching order/status"}
        model = row.get("device_model")
        if not isinstance(model, dict) or any(
                model.get(key) != expected[key]
                for key in ("cap_mib_s", "completion_nsec", "irqmode",
                            "queue_mode", "submit_queues", "hw_queue_depth")):
            return {"overall": "INCOMPLETE",
                    "reason": "independent READ fan-out device model mismatch"}
        if set(row.get("arms", {})) != {"off", "swapz"}:
            return {"overall": "INCOMPLETE",
                    "reason": "independent READ fan-out paired arms missing"}
        provenance_error = paired_provenance_error(
            row, "independent READ fan-out")
        if provenance_error:
            return provenance_error
        arm = row["arms"]["swapz"]
        for key in ("input_write_mbps", "swap_in_read_mbps", "read_p99_ms",
                    "lower_read_bytes", "lower_read_requests"):
            if not isinstance(arm.get(key), (int, float)) or arm[key] < 0:
                return {"overall": "INCOMPLETE",
                        "reason": "independent READ fan-out mixed metrics missing"}
        mixed_kernel = arm.get("kernel_read_path")
        if (not isinstance(mixed_kernel, dict) or
                any(type(mixed_kernel.get(name)) is not int or
                    mixed_kernel[name] < 0 for name in KERNEL_READ_FIELDS) or
                not read_metadata_counters_consistent(mixed_kernel)):
            return {"overall": "INCOMPLETE",
                    "reason": "independent READ fan-out mixed telemetry missing"}
        if any(mixed_kernel[field] for field in coalesce_fields):
            return {"overall": "INCOMPLETE",
                    "reason": "fan-out decision arm executed ID63 coalescing"}
        if not row["parallel_reads"] and (
                mixed_kernel["parallel_read_async_batches"] or
                mixed_kernel["parallel_read_async_slots"]):
            return {"overall": "INCOMPLETE",
                    "reason": "fan-out off arm submitted asynchronous READ slots"}
        if row["parallel_reads"] and (
                mixed_kernel["parallel_read_async_batches"] <= 0 or
                mixed_kernel["parallel_read_async_slots"] < 2):
            return {"overall": "INCOMPLETE",
                    "reason": "fan-out on arm did not exercise mixed lower-READ concurrency"}
        if (not isinstance(arm.get("packed_close_delta"), int) or
                arm["packed_close_delta"] <= 0):
            return {"overall": "INCOMPLETE",
                    "reason": "independent READ fan-out packed population missing"}
        for mode in ("sequential", "seeded_random"):
            phase = arm["passes"].get(mode)
            if (not isinstance(phase, dict) or
                    phase.get("logical_bytes") != 4194304 or
                    phase.get("verified_pages") != 1024):
                return {"overall": "INCOMPLETE",
                        "reason": "independent READ fan-out packed verification incomplete"}
            if any(not isinstance(phase.get(key), (int, float)) or
                   phase[key] < 0 for key in
                   ("useful_read_mbps", "read_p99_ms",
                    "lower_read_bytes", "lower_read_requests")):
                return {"overall": "INCOMPLETE",
                        "reason": "independent READ fan-out packed metrics missing"}
            kernel = phase.get("kernel_read_path")
            if (not isinstance(kernel, dict) or
                    any(type(kernel.get(name)) is not int or kernel[name] < 0
                        for name in KERNEL_READ_FIELDS) or
                    not read_metadata_counters_consistent(kernel)):
                return {"overall": "INCOMPLETE",
                        "reason": "independent READ fan-out packed telemetry missing"}
            if any(kernel[field] for field in coalesce_fields):
                return {"overall": "INCOMPLETE",
                        "reason": "packed fan-out decision arm executed ID63 coalescing"}
            if not row["parallel_reads"] and (
                    kernel["parallel_read_async_batches"] or
                    kernel["parallel_read_async_slots"]):
                return {"overall": "INCOMPLETE",
                        "reason": "packed fan-out off arm submitted asynchronous READ slots"}

    if (len({row["source_sha"] for row in sessions}) != 1 or
            len({row["fixture_sha256"] for row in sessions}) != 1 or
            len({row["trace_sha256"] for row in sessions}) != 1 or
            len({row["arms"]["swapz"]["logical_image_sha256"]
                 for row in sessions}) != 1):
        return {"overall": "INCONCLUSIVE",
                "reason": "independent READ fan-out provenance mismatch"}

    modes = {}
    for enabled in (0, 1):
        rows = [row["arms"]["swapz"] for row in sessions
                if row["parallel_reads"] == enabled]
        mixed = {
            "write_mbps": statistics.mean(row["input_write_mbps"] for row in rows),
            "read_mbps": statistics.mean(row["swap_in_read_mbps"] for row in rows),
            "read_p99_ms": statistics.mean(row["read_p99_ms"] for row in rows),
            "lower_read_bytes": statistics.mean(row["lower_read_bytes"] for row in rows),
            "lower_read_requests": statistics.mean(
                row["lower_read_requests"] for row in rows),
            "async_batches": statistics.mean(
                row["kernel_read_path"]["parallel_read_async_batches"]
                for row in rows),
            "async_slots": statistics.mean(
                row["kernel_read_path"]["parallel_read_async_slots"]
                for row in rows),
        }
        packed = {}
        for mode in ("sequential", "seeded_random"):
            phases = [row["passes"][mode] for row in rows]
            packed[mode] = {
                "useful_read_mbps": statistics.mean(
                    phase["useful_read_mbps"] for phase in phases),
                "read_p99_ms": statistics.mean(
                    phase["read_p99_ms"] for phase in phases),
                "lower_read_bytes": statistics.mean(
                    phase["lower_read_bytes"] for phase in phases),
                "lower_read_requests": statistics.mean(
                    phase["lower_read_requests"] for phase in phases),
                "async_batches": statistics.mean(
                    phase["kernel_read_path"]["parallel_read_async_batches"]
                    for phase in phases),
                "async_slots": statistics.mean(
                    phase["kernel_read_path"]["parallel_read_async_slots"]
                    for phase in phases),
            }
        modes[str(enabled)] = {"mixed": mixed, "packed": packed}

    paired = {"mixed": {}}
    mixed_metrics = (
        ("write_mbps", "input_write_mbps"),
        ("read_mbps", "swap_in_read_mbps"),
        ("read_p99_ms", "read_p99_ms"),
        ("lower_read_bytes", "lower_read_bytes"),
        ("lower_read_requests", "lower_read_requests"),
    )
    for output_name, source_name in mixed_metrics:
        changes = []
        for pair in pairs:
            off = pair[0]["arms"]["swapz"][source_name]
            on = pair[1]["arms"]["swapz"][source_name]
            if not off:
                return {"overall": "INCOMPLETE",
                        "reason": "independent READ fan-out mixed zero denominator"}
            changes.append(on / off - 1.0)
        paired["mixed"][output_name] = paired_ci95(changes)

    paired["packed"] = {}
    for mode in ("sequential", "seeded_random"):
        paired["packed"][mode] = {}
        for output_name, source_name in (
                ("read_mbps", "useful_read_mbps"),
                ("read_p99_ms", "read_p99_ms"),
                ("lower_read_bytes", "lower_read_bytes"),
                ("lower_read_requests", "lower_read_requests")):
            changes = []
            for pair in pairs:
                off = pair[0]["arms"]["swapz"]["passes"][mode][source_name]
                on = pair[1]["arms"]["swapz"]["passes"][mode][source_name]
                if not off:
                    return {"overall": "INCOMPLETE",
                            "reason": "independent READ fan-out packed zero denominator"}
                changes.append(on / off - 1.0)
            paired["packed"][mode][output_name] = paired_ci95(changes)

    raw_control = {}
    for metric, source_name in (
            ("write_mbps", "input_write_mbps"),
            ("read_mbps", "swap_in_read_mbps"),
            ("read_p99_ms", "read_p99_ms")):
        changes = []
        for pair in pairs:
            off = pair[0]["arms"]["off"][source_name]
            on = pair[1]["arms"]["off"][source_name]
            if not off:
                return {"overall": "INCOMPLETE",
                        "reason": "independent READ fan-out raw-control zero denominator"}
            changes.append(on / off - 1.0)
        raw_control[metric] = paired_ci95(changes)

    return {
        "overall": "PASS_PARALLEL_READ_AB_EVIDENCE",
        "matched_pairs": 5,
        "confidence": "PAIRED_95PCT_CI_REPORTED",
        "device_model": expected,
        "modes": modes,
        "paired": paired,
        "raw_control_paired": raw_control,
        "interpretation":
            "FINAL_SAME_SOURCE_INDEPENDENT_READ_FANOUT_DECISION_ID63_OFF_FAST_MODEL",
    }


def parse_read_coalesce_ab(output):
    """Parse five matched fast-model rounds varying only ID63 coalescing."""
    sessions, current = [], None
    for line in output.splitlines():
        line = line.strip()
        match = re.fullmatch(r"START_READ_COALESCE_AB=([01])", line)
        if match:
            current = {"read_coalesce": int(match.group(1)),
                       "status": "INCOMPLETE", "order": "unknown",
                       "device_model": None, "swapz": None}
            sessions.append(current)
            continue
        if current is None:
            continue
        if line.startswith("REPLAY_ORDER="):
            current["order"] = line.partition("=")[2].strip()
        elif line.startswith("PASS_RAM_MODEL_LOWER_MBPS="):
            model = re.fullmatch(
                r"PASS_RAM_MODEL_LOWER_MBPS=(\d+) COMPLETION_NSEC=(\d+) IRQMODE=(\d+) QUEUE_MODE=(\d+) SUBMIT_QUEUES=(\d+) HW_QUEUE_DEPTH=(\d+)",
                line)
            if model:
                current["device_model"] = {
                    "cap_mib_s": int(model.group(1)),
                    "completion_nsec": int(model.group(2)),
                    "irqmode": int(model.group(3)),
                    "queue_mode": int(model.group(4)),
                    "submit_queues": int(model.group(5)),
                    "hw_queue_depth": int(model.group(6)),
                }
        elif line.startswith("{"):
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            if obj.get("candidate") != "swapz" or obj.get("verdict") != "PASS":
                continue
            packed = obj.get("packed_read") or {}
            passes = {}
            for mode in ("sequential", "seeded_random"):
                phase = (packed.get("passes") or {}).get(mode) or {}
                lower = phase.get("lower_io") or {}
                passes[mode] = {
                    "logical_bytes": phase.get("logical_bytes"),
                    "verified_pages": phase.get("verified_pages"),
                    "verified_image_sha256": phase.get("verified_image_sha256"),
                    "useful_read_mbps": phase.get("useful_read_mbps"),
                    "read_p99_ms": phase.get("read_p99_ms"),
                    "host_cpu": host_cpu_record(phase),
                    "lower_read_bytes": lower.get("lower_read_bytes"),
                    "lower_read_requests": lower.get("lower_read_requests"),
                    "kernel_read_path": phase.get("kernel_read_path"),
                }
            current["swapz"] = {
                "source_sha": obj.get("source_sha"),
                "fixture_sha256": obj.get("fixture_sha256"),
                "trace_sha256": obj.get("trace_sha256"),
                "logical_image_sha256": packed.get("logical_image_sha256"),
                "packed_close_delta": packed.get("packed_close_delta"),
                "passes": passes,
            }
        else:
            done = re.fullmatch(r"PASS_READ_COALESCE_AB=([01])", line)
            if done and int(done.group(1)) == current["read_coalesce"]:
                current["status"] = "PASS"
                current = None
    return sessions


def read_coalesce_ab_verdict(sessions):
    """Validate five same-cache rounds varying only ID63 with the off arm on ordinary FIFO."""
    try:
        pairs = matched_binary_pairs(sessions, "read_coalesce")
    except ValueError as exc:
        return {"overall": "INCOMPLETE", "reason": str(exc)}
    expected = MODEL_SPECS["ssd_emulated"]
    for index, row in enumerate(sessions):
        if row.get("status") != "PASS" or row.get("order") != (
                "swapz-first" if index % 2 else "off-first"):
            return {"overall": "INCOMPLETE",
                    "reason": "adjacent-range READ confirmation order/status mismatch"}
        model = row.get("device_model")
        if not isinstance(model, dict) or any(model.get(key) != expected[key]
                for key in ("cap_mib_s", "completion_nsec", "irqmode",
                            "queue_mode", "submit_queues", "hw_queue_depth")):
            return {"overall": "INCOMPLETE",
                    "reason": "adjacent-range READ confirmation device model mismatch"}
        arm = row.get("swapz")
        if not isinstance(arm, dict) or not re.fullmatch(
                r"[0-9a-f]{40}", str(arm.get("source_sha", ""))):
            return {"overall": "INCOMPLETE",
                    "reason": "adjacent-range READ confirmation source missing"}
        if not isinstance(arm.get("packed_close_delta"), int) or \
                arm["packed_close_delta"] <= 0:
            return {"overall": "INCOMPLETE",
                    "reason": "adjacent-range READ packed population missing"}
        for mode in ("sequential", "seeded_random"):
            phase = arm["passes"].get(mode)
            if not isinstance(phase, dict) or \
                    phase.get("logical_bytes") != 4194304 or \
                    phase.get("verified_pages") != 1024:
                return {"overall": "INCOMPLETE",
                        "reason": "adjacent-range READ packed verification incomplete"}
            if any(not isinstance(phase.get(key), (int, float)) or
                   phase[key] < 0 for key in
                   ("useful_read_mbps", "read_p99_ms",
                    "lower_read_bytes", "lower_read_requests")):
                return {"overall": "INCOMPLETE",
                        "reason": "adjacent-range READ metrics missing"}
            kernel = phase.get("kernel_read_path")
            if not isinstance(kernel, dict) or any(
                    type(kernel.get(name)) is not int or kernel[name] < 0
                    for name in KERNEL_READ_FIELDS) or not read_metadata_counters_consistent(kernel):
                return {"overall": "INCOMPLETE",
                        "reason": "adjacent-range READ kernel telemetry missing"}
            if not row["read_coalesce"] and any(kernel[field] for field in (
                    "parallel_read_adjacent_extent_pairs",
                    "parallel_read_adjacent_extent_blocks",
                    "parallel_read_adjacent_chain_3plus",
                    "parallel_read_coalesced_pairs",
                    "parallel_read_coalesced_reqs_saved",
                    "parallel_read_coalesced_blocks",
                    "parallel_read_coalesce_extra_blocks",
                    "parallel_read_coalesce_skip_cached",
                    "parallel_read_coalesce_skip_noncontig_slot",
                    "parallel_read_coalesce_skip_gap",
                    "parallel_read_coalesce_skip_other")):
                return {"overall": "INCOMPLETE",
                        "reason": "merge-off arm executed adjacent-range READ coalescing"}
        if row["read_coalesce"] and not arm["passes"]["sequential"][
                "kernel_read_path"]["parallel_read_coalesced_pairs"]:
            return {"overall": "INCOMPLETE",
                    "reason": "merge-on arm executed no sequential READ coalescing"}
        if row["read_coalesce"] and any(
                arm["passes"][mode]["kernel_read_path"][
                    "parallel_read_coalesce_skip_other"]
                for mode in ("sequential", "seeded_random")):
            return {"overall": "INCOMPLETE",
                    "reason": "merge-on arm hit an unexpected READ merge skip reason"}
    if len({row["swapz"]["source_sha"] for row in sessions}) != 1 or \
            len({row["swapz"]["fixture_sha256"] for row in sessions}) != 1 or \
            len({row["swapz"]["trace_sha256"] for row in sessions}) != 1 or \
            len({row["swapz"]["logical_image_sha256"] for row in sessions}) != 1:
        return {"overall": "INCONCLUSIVE",
                "reason": "adjacent-range READ confirmation provenance mismatch"}

    modes = {}
    for enabled in (0, 1):
        rows = [row["swapz"] for row in sessions
                if row["read_coalesce"] == enabled]
        passes = {}
        for mode in ("sequential", "seeded_random"):
            phases = [row["passes"][mode] for row in rows]
            passes[mode] = {
                "useful_read_mbps":
                    statistics.mean(p["useful_read_mbps"] for p in phases),
                "read_p99_ms":
                    statistics.mean(p["read_p99_ms"] for p in phases),
                "lower_read_bytes":
                    statistics.mean(p["lower_read_bytes"] for p in phases),
                "lower_read_requests":
                    statistics.mean(p["lower_read_requests"] for p in phases),
            }
            for field in (
                    "parallel_read_pairs",
                    "parallel_read_same_extent_pairs",
                    "parallel_read_distinct_extent_pairs",
                    "parallel_read_adjacent_extent_pairs",
                    "parallel_read_adjacent_extent_blocks",
                    "parallel_read_coalesced_pairs",
                    "parallel_read_coalesced_reqs_saved",
                    "parallel_read_coalesced_blocks",
                    "parallel_read_coalesce_extra_blocks",
                    "parallel_read_coalesce_skip_cached",
                    "parallel_read_coalesce_skip_noncontig_slot",
                    "parallel_read_coalesce_skip_gap",
                    "parallel_read_coalesce_skip_other"):
                passes[mode][field] = statistics.mean(
                    p["kernel_read_path"][field] for p in phases)
        modes[str(enabled)] = passes

    paired = {}
    for mode in ("sequential", "seeded_random"):
        p99, throughput, lower_bytes, lower_requests = [], [], [], []
        for pair in pairs:
            off = pair[0]["swapz"]["passes"][mode]
            on = pair[1]["swapz"]["passes"][mode]
            if not off["read_p99_ms"] or not off["useful_read_mbps"] or \
                    not off["lower_read_bytes"] or not off["lower_read_requests"]:
                return {"overall": "INCOMPLETE",
                        "reason": "adjacent-range READ confirmation has a zero denominator"}
            p99.append(on["read_p99_ms"] / off["read_p99_ms"] - 1.0)
            throughput.append(
                on["useful_read_mbps"] / off["useful_read_mbps"] - 1.0)
            lower_bytes.append(
                on["lower_read_bytes"] / off["lower_read_bytes"] - 1.0)
            lower_requests.append(
                on["lower_read_requests"] / off["lower_read_requests"] - 1.0)
        paired[mode] = {
            "p99_change_fraction": paired_ci95(p99),
            "throughput_change_fraction": paired_ci95(throughput),
            "lower_bytes_change_fraction": paired_ci95(lower_bytes),
            "lower_requests_change_fraction": paired_ci95(lower_requests),
        }
    return {
        "overall": "PASS_READ_COALESCE_AB_CONFIRMATION",
        "matched_pairs": 5,
        "confidence": "PAIRED_95PCT_CI_REPORTED",
        "device_model": expected,
        "modes": modes,
        "paired": paired,
        "interpretation":
            "SAME_SOURCE_ID63_TOGGLE_COMMON_INDEPENDENT_FANOUT_SYNTHETIC_RAM_ONLY",
    }



def _parse_sd_read_toggle_ab(output, start_marker, pass_marker, field):
    """Parse one five-pair depth-one READ isolation with one binary toggle."""
    sessions, current = [], None
    start_re = re.compile(re.escape(start_marker) + r"=([01])")
    pass_re = re.compile(re.escape(pass_marker) + r"=([01])")
    for line in output.splitlines():
        line = line.strip()
        match = start_re.fullmatch(line)
        if match:
            current = {field: int(match.group(1)), "status": "INCOMPLETE",
                       "order": "unknown", "device_model": None, "swapz": None}
            sessions.append(current)
            continue
        if current is None:
            continue
        if line.startswith("REPLAY_ORDER="):
            current["order"] = line.partition("=")[2].strip()
        elif line.startswith("PASS_RAM_MODEL_LOWER_MBPS="):
            model = re.fullmatch(
                r"PASS_RAM_MODEL_LOWER_MBPS=(\d+) COMPLETION_NSEC=(\d+) IRQMODE=(\d+) QUEUE_MODE=(\d+) SUBMIT_QUEUES=(\d+) HW_QUEUE_DEPTH=(\d+)",
                line)
            if model:
                current["device_model"] = {
                    "cap_mib_s": int(model.group(1)),
                    "completion_nsec": int(model.group(2)),
                    "irqmode": int(model.group(3)),
                    "queue_mode": int(model.group(4)),
                    "submit_queues": int(model.group(5)),
                    "hw_queue_depth": int(model.group(6)),
                }
        elif line.startswith("{"):
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            if obj.get("candidate") != "swapz" or obj.get("verdict") != "PASS":
                continue
            packed = obj.get("packed_read") or {}
            passes = {}
            for mode in ("sequential", "seeded_random"):
                phase = (packed.get("passes") or {}).get(mode) or {}
                lower = phase.get("lower_io") or {}
                passes[mode] = {
                    "logical_bytes": phase.get("logical_bytes"),
                    "verified_pages": phase.get("verified_pages"),
                    "verified_image_sha256": phase.get("verified_image_sha256"),
                    "useful_read_mbps": phase.get("useful_read_mbps"),
                    "read_p99_ms": phase.get("read_p99_ms"),
                    "host_cpu": host_cpu_record(phase),
                    "lower_read_bytes": lower.get("lower_read_bytes"),
                    "lower_read_requests": lower.get("lower_read_requests"),
                    "kernel_read_path": phase.get("kernel_read_path"),
                }
            current["swapz"] = {
                "source_sha": obj.get("source_sha"),
                "fixture_sha256": obj.get("fixture_sha256"),
                "trace_sha256": obj.get("trace_sha256"),
                "logical_image_sha256": packed.get("logical_image_sha256"),
                "packed_close_delta": packed.get("packed_close_delta"),
                "passes": passes,
            }
        else:
            done = pass_re.fullmatch(line)
            if done and int(done.group(1)) == current[field]:
                current["status"] = "PASS"
                current = None
    return sessions


def parse_sd_read_coalesce_ab(output):
    return _parse_sd_read_toggle_ab(
        output, "START_SD_READ_COALESCE_AB", "PASS_SD_READ_COALESCE_AB",
        "read_coalesce")


def _sd_read_ab_verdict(sessions, field, kind):
    """Validate a five-pair hwq=1 READ isolation and report paired CIs."""
    try:
        pairs = matched_binary_pairs(sessions, field)
    except ValueError as exc:
        return {"overall": "INCOMPLETE", "reason": str(exc)}
    expected = MODEL_SPECS["sd_emulated"]
    for index, row in enumerate(sessions):
        if row.get("status") != "PASS" or row.get("order") != (
                "swapz-first" if index % 2 else "off-first"):
            return {"overall": "INCOMPLETE",
                    "reason": f"SD {kind} order/status mismatch"}
        model = row.get("device_model")
        if not isinstance(model, dict) or any(model.get(key) != expected[key]
                for key in ("cap_mib_s", "completion_nsec", "irqmode",
                            "queue_mode", "submit_queues", "hw_queue_depth")):
            return {"overall": "INCOMPLETE",
                    "reason": f"SD {kind} device model mismatch"}
        arm = row.get("swapz")
        if not isinstance(arm, dict) or not re.fullmatch(
                r"[0-9a-f]{40}", str(arm.get("source_sha", ""))):
            return {"overall": "INCOMPLETE",
                    "reason": f"SD {kind} source missing"}
        if not isinstance(arm.get("packed_close_delta"), int) or \
                arm["packed_close_delta"] <= 0:
            return {"overall": "INCOMPLETE",
                    "reason": f"SD {kind} packed population missing"}
        for mode in ("sequential", "seeded_random"):
            phase = arm["passes"].get(mode)
            if not isinstance(phase, dict) or \
                    phase.get("logical_bytes") != 4194304 or \
                    phase.get("verified_pages") != 1024:
                return {"overall": "INCOMPLETE",
                        "reason": f"SD {kind} packed read incomplete"}
            if any(not isinstance(phase.get(key), (int, float)) or
                   phase[key] < 0 for key in
                   ("useful_read_mbps", "read_p99_ms",
                    "lower_read_bytes", "lower_read_requests")):
                return {"overall": "INCOMPLETE",
                        "reason": f"SD {kind} metrics missing"}
            kernel = phase.get("kernel_read_path")
            if not isinstance(kernel, dict) or any(
                    type(kernel.get(name)) is not int or kernel[name] < 0
                    for name in KERNEL_READ_FIELDS) or not read_metadata_counters_consistent(kernel):
                return {"overall": "INCOMPLETE",
                        "reason": f"SD {kind} C telemetry missing"}
            if kernel["read_worker_cpu_ns"]:
                return {"overall": "INCOMPLETE",
                        "reason": f"SD {kind} unexpectedly used read workqueue"}
            if kernel["parallel_read_coalesce_skip_other"]:
                return {"overall": "INCOMPLETE",
                        "reason": f"SD {kind} hit unexpected coalesce skip reason"}
        seq_kernel = arm["passes"]["sequential"]["kernel_read_path"]
        if not row[field] and any(
                arm["passes"][mode]["kernel_read_path"][name]
                for mode in ("sequential", "seeded_random")
                for name in (
                    "parallel_read_adjacent_extent_pairs",
                    "parallel_read_adjacent_extent_blocks",
                    "parallel_read_adjacent_chain_3plus",
                    "parallel_read_coalesced_pairs",
                    "parallel_read_coalesced_reqs_saved",
                    "parallel_read_coalesced_blocks",
                    "parallel_read_coalesce_extra_blocks",
                    "parallel_read_coalesce_skip_cached",
                    "parallel_read_coalesce_skip_noncontig_slot",
                    "parallel_read_coalesce_skip_gap",
                    "parallel_read_coalesce_skip_other")):
            return {"overall": "INCOMPLETE",
                    "reason": "serial-depth merge-off arm executed a retired grouped READ path"}
        if row[field] and not seq_kernel["parallel_read_coalesced_pairs"]:
            return {"overall": "INCOMPLETE",
                    "reason": "serial-depth merge-on arm executed no sequential READ coalescing"}
    if len({row["swapz"]["source_sha"] for row in sessions}) != 1 or \
            len({row["swapz"]["fixture_sha256"] for row in sessions}) != 1 or \
            len({row["swapz"]["trace_sha256"] for row in sessions}) != 1 or \
            len({row["swapz"]["logical_image_sha256"] for row in sessions}) != 1:
        return {"overall": "INCONCLUSIVE",
                "reason": f"SD {kind} provenance mismatch"}

    modes = {}
    for enabled in (0, 1):
        rows = [row["swapz"] for row in sessions if row[field] == enabled]
        passes = {}
        for mode in ("sequential", "seeded_random"):
            phases = [row["passes"][mode] for row in rows]
            passes[mode] = {
                "useful_read_mbps":
                    statistics.mean(p["useful_read_mbps"] for p in phases),
                "read_p99_ms":
                    statistics.mean(p["read_p99_ms"] for p in phases),
                "lower_read_bytes":
                    statistics.mean(p["lower_read_bytes"] for p in phases),
                "lower_read_requests":
                    statistics.mean(p["lower_read_requests"] for p in phases),
            }
            for name in KERNEL_READ_FIELDS:
                passes[mode][name] = statistics.mean(
                    p["kernel_read_path"][name] for p in phases)
        modes[str(enabled)] = passes

    paired = {}
    for mode in ("sequential", "seeded_random"):
        req, p99, throughput, lower_bytes = [], [], [], []
        for pair in pairs:
            off = pair[0]["swapz"]["passes"][mode]
            on = pair[1]["swapz"]["passes"][mode]
            if not off["lower_read_requests"] or not off["read_p99_ms"] or \
                    not off["useful_read_mbps"] or not off["lower_read_bytes"]:
                return {"overall": "INCOMPLETE",
                        "reason": f"SD {kind} zero denominator"}
            req.append(on["lower_read_requests"] /
                       off["lower_read_requests"] - 1.0)
            p99.append(on["read_p99_ms"] / off["read_p99_ms"] - 1.0)
            throughput.append(on["useful_read_mbps"] /
                              off["useful_read_mbps"] - 1.0)
            lower_bytes.append(on["lower_read_bytes"] /
                               off["lower_read_bytes"] - 1.0)
        paired[mode] = {
            "lower_requests_change_fraction": paired_ci95(req),
            "p99_change_fraction": paired_ci95(p99),
            "throughput_change_fraction": paired_ci95(throughput),
            "lower_bytes_change_fraction": paired_ci95(lower_bytes),
        }
    return {
        "overall": "PASS_SD_READ_COALESCE_AB_CONFIRMATION",
        "matched_pairs": 5,
        "confidence": "PAIRED_95PCT_CI_REPORTED",
        "device_model": expected,
        "modes": modes,
        "paired": paired,
        "interpretation":
            "SAME_SOURCE_HWQ1_ID63_TOGGLE_COMMON_INDEPENDENT_FANOUT_SYNTHETIC_RAM",
    }


def sd_read_coalesce_ab_verdict(sessions):
    return _sd_read_ab_verdict(sessions, "read_coalesce", "coalescing")



def parse_lone_raw_qd1(output):
    """Parse the isolated ID161 QD1 candidate without touching saturation rows."""
    row = None
    completed = None
    seen = 0
    for original in output.splitlines():
        line = original.strip()
        if line == "START_LONE_RAW_QD1=1":
            seen += 1
            if row is not None:
                return {"overall": "INCOMPLETE",
                        "reason": "nested lone-RAW QD1 candidate markers"}
            row = {
                "status": "INCOMPLETE", "order": "unknown",
                "device_model": None, "arms": {}, "activity": None,
            }
            continue
        if row is None:
            continue
        if line.startswith("REPLAY_ORDER="):
            row["order"] = line.partition("=")[2]
        elif line.startswith("PASS_RAM_MODEL_LOWER_MBPS="):
            match = re.fullmatch(
                r"PASS_RAM_MODEL_LOWER_MBPS=(\d+) COMPLETION_NSEC=(\d+) "
                r"IRQMODE=(\d+) QUEUE_MODE=(\d+) SUBMIT_QUEUES=(\d+) "
                r"HW_QUEUE_DEPTH=(\d+)", line)
            if match:
                row["device_model"] = {
                    "cap_mib_s": int(match.group(1)),
                    "completion_nsec": int(match.group(2)),
                    "irqmode": int(match.group(3)),
                    "queue_mode": int(match.group(4)),
                    "submit_queues": int(match.group(5)),
                    "hw_queue_depth": int(match.group(6)),
                }
        elif line.startswith("PASS_LONE_RAW_ACTIVITY="):
            match = re.fullmatch(
                r"PASS_LONE_RAW_ACTIVITY=candidates:(\d+) selected:(\d+) "
                r"cancelled:(\d+) zero_elided:(\d+) "
                r"multi_record_windows:(\d+) multi_record_pages:(\d+)", line)
            if match:
                row["activity"] = {
                    key: int(value) for key, value in zip(
                        ("candidates", "selected", "cancelled", "zero_elided",
                         "multi_record_windows", "multi_record_pages"),
                        match.groups())
                }
        elif line.startswith("{"):
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            if (obj.get("candidate") not in ("off", "swapz") or
                    obj.get("verdict") != "PASS"):
                continue
            rates = obj.get("throughput_mbps") or {}
            lower = obj.get("lower_io") or {}
            row["arms"][obj["candidate"]] = {
                "source_sha": obj.get("source_sha"),
                "fixture_sha256": obj.get("fixture_sha256"),
                "trace_sha256": obj.get("trace_sha256"),
                "qd": obj.get("qd"),
                "replay_mode": obj.get("replay_mode"),
                "logical_write_mbps": rates.get("logical_write_mbps"),
                "logical_write_bytes": rates.get("logical_write_bytes"),
                "logical_read_bytes": rates.get("logical_read_bytes"),
                "lower_write_bytes": lower.get("lower_write_bytes"),
                "lower_write_requests": lower.get("lower_write_requests"),
                "write_p99_ms": (obj.get("write_p99_ns") / 1e6
                                 if isinstance(obj.get("write_p99_ns"),
                                               (int, float)) else None),
                "kernel_write_path": obj.get("kernel_write_path"),
                "host_cpu": host_cpu_record(obj),
            }
        elif line == "PASS_LONE_RAW_QD1=1":
            row["status"] = "PASS"
            completed = row
            row = None
    if seen != 1 or completed is None or completed.get("status") != "PASS":
        return {"overall": "INCOMPLETE",
                "reason": "exactly one completed lone-RAW QD1 candidate pair required"}
    row = completed
    if row.get("order") != "off-first":
        return {"overall": "INCOMPLETE",
                "reason": "lone-RAW QD1 replay order mismatch"}
    expected = MODEL_SPECS["ssd_emulated"]
    model = row.get("device_model")
    if not isinstance(model, dict) or any(
            model.get(key) != expected[key]
            for key in ("cap_mib_s", "completion_nsec", "irqmode",
                        "queue_mode", "submit_queues", "hw_queue_depth")):
        return {"overall": "INCOMPLETE",
                "reason": "lone-RAW QD1 device model mismatch"}
    if set(row.get("arms", {})) != {"off", "swapz"}:
        return {"overall": "INCOMPLETE",
                "reason": "lone-RAW QD1 pair missing raw/swapz arm"}
    off, swapz = row["arms"]["off"], row["arms"]["swapz"]
    if any(off.get(field) != swapz.get(field)
           for field in BENCHMARK_PROVENANCE_FIELDS):
        return {"overall": "INCONCLUSIVE",
                "reason": "lone-RAW QD1 arm provenance mismatch"}
    if not re.fullmatch(r"[0-9a-f]{40}", swapz.get("source_sha") or ""):
        return {"overall": "INCONCLUSIVE",
                "reason": "lone-RAW QD1 source unavailable"}
    for arm in (off, swapz):
        if (arm.get("qd") != 1 or arm.get("replay_mode") != "persistent-write" or
                arm.get("logical_read_bytes") != 0 or
                not isinstance(arm.get("logical_write_mbps"), (int, float)) or
                not isinstance(arm.get("logical_write_bytes"), int) or
                arm["logical_write_bytes"] <= 0 or
                not isinstance(arm.get("lower_write_bytes"), int) or
                arm["lower_write_bytes"] <= 0 or
                not isinstance(arm.get("lower_write_requests"), int) or
                arm["lower_write_requests"] <= 0 or
                not isinstance(arm.get("write_p99_ms"), (int, float))):
            return {"overall": "INCOMPLETE",
                    "reason": "lone-RAW QD1 arm metrics invalid"}
    timed = swapz.get("kernel_write_path")
    if not isinstance(timed, dict) or any(
            type(timed.get(field)) is not int or timed[field] < 0
            for field in KERNEL_WRITE_FIELDS):
        return {"overall": "INCOMPLETE",
                "reason": "lone-RAW QD1 kernel telemetry incomplete"}
    if (timed["lone_raw"] != 1 or timed["submitter_prepare"] != 0 or
            timed["write_pipeline_depth"] != 1 or
            timed["lone_raw_candidates"] !=
            timed["lone_raw_selected"] + timed["lone_raw_cancelled_followers"] or
            timed["lone_raw_selected"] <= 0 or
            timed["lone_raw_zero_elided"] > timed["lone_raw_selected"] or
            timed["lone_raw_multi_record_windows"] != 0 or
            timed["lone_raw_multi_record_pages"] != 0):
        return {"overall": "INCOMPLETE",
                "reason": "lone-RAW QD1 policy/activity invariant failed"}
    activity = row.get("activity")
    if (not isinstance(activity, dict) or activity["selected"] <= 0 or
            activity["candidates"] !=
            activity["selected"] + activity["cancelled"] or
            activity["zero_elided"] > activity["selected"] or
            activity["multi_record_windows"] or activity["multi_record_pages"]):
        return {"overall": "INCOMPLETE",
                "reason": "lone-RAW QD1 full-session activity invalid"}
    return {
        "overall": "PASS_LONE_RAW_QD1_CANDIDATE",
        "scope": "DEVELOPMENT_CANDIDATE_DEFAULT_OFF",
        "row": row,
        "swapz_to_raw_write_ratio":
            swapz["logical_write_mbps"] / off["logical_write_mbps"],
        "lower_write_bytes_ratio":
            swapz["lower_write_bytes"] / off["lower_write_bytes"],
        "lower_write_requests_ratio":
            swapz["lower_write_requests"] / off["lower_write_requests"],
    }


def parse_write_saturation(output):
    """Parse only the bounded sustained write-only QD pilot."""
    sessions, current, regime = [], None, None
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("START_WRITE_SATURATION_REGIME="):
            regime = line.partition("=")[2]
            current = None
        elif line.startswith("START_WRITE_SATURATION_PAIR_QD="):
            match = re.fullmatch(
                r"START_WRITE_SATURATION_PAIR_QD=(1|4|8|32) ASYNC_PREPARE=([01])",
                line)
            if not match:
                continue
            current = {
                "regime": regime, "qd": int(match.group(1)),
                "async_prepare": int(match.group(2)),
                "status": "INCOMPLETE", "order": "unknown",
                "device_model": None, "arms": {},
            }
            sessions.append(current)
        elif current is not None and line.startswith("REPLAY_ORDER="):
            current["order"] = line.partition("=")[2].strip()
        elif current is not None and line.startswith("PASS_RAM_MODEL_LOWER_MBPS="):
            match = re.fullmatch(
                r"PASS_RAM_MODEL_LOWER_MBPS=(\d+) COMPLETION_NSEC=(\d+) IRQMODE=(\d+) QUEUE_MODE=(\d+) SUBMIT_QUEUES=(\d+) HW_QUEUE_DEPTH=(\d+)",
                line)
            if match:
                current["device_model"] = {
                    "cap_mib_s": int(match.group(1)),
                    "completion_nsec": int(match.group(2)),
                    "irqmode": int(match.group(3)),
                    "queue_mode": int(match.group(4)),
                    "submit_queues": int(match.group(5)),
                    "hw_queue_depth": int(match.group(6)),
                }
        elif current is not None and line.startswith(
                ("SWAPZ_STATUS_BEFORE=", "SWAPZ_STATUS_AFTER=")):
            # Never use full-process window counters for the QD pilot.
            continue
        elif current is not None and line.startswith("{"):
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            if obj.get("candidate") not in ("off", "swapz") or obj.get("verdict") != "PASS":
                continue
            candidate = obj["candidate"]
            rates = obj.get("throughput_mbps") or {}
            lower = obj.get("lower_io") or {}
            current["arms"][candidate] = {
                "source_sha": obj.get("source_sha"),
                "fixture_sha256": obj.get("fixture_sha256"),
                "trace_sha256": obj.get("trace_sha256"),
                "replay_mode": obj.get("replay_mode"),
                "input_write_mbps": rates.get("logical_write_mbps"),
                "output_lower_write_mbps": rates.get("lower_write_mbps"),
                "logical_write_bytes": rates.get("logical_write_bytes"),
                "logical_read_bytes": rates.get("logical_read_bytes"),
                "lower_write_bytes": lower.get("lower_write_bytes"),
                "lower_write_requests": lower.get("lower_write_requests"),
                "lower_read_bytes": lower.get("lower_read_bytes"),
                "lower_read_requests": lower.get("lower_read_requests"),
                "write_p99_ms": (obj.get("write_p99_ns") / 1e6
                                 if isinstance(obj.get("write_p99_ns"), (int, float))
                                 else 0.0),
                "seconds": obj.get("seconds"),
                "cpu_user_s": obj.get("mixed_replay_cpu_user_s"),
                "cpu_system_s": obj.get("mixed_replay_cpu_system_s"),
                "peak_rss_kb": obj.get("mixed_replay_peak_rss_kb"),
                "lower_inflight": lower_inflight_record(obj),
                "host_cpu": host_cpu_record(obj),
                "kernel_write_path": obj.get("kernel_write_path"),
            }
            for field in ("source_sha", "fixture_sha256", "trace_sha256"):
                if obj.get(field):
                    current[field] = obj[field]
        elif current is not None and line.startswith("PASS_WRITE_SATURATION_PAIR_QD="):
            match = re.fullmatch(
                r"PASS_WRITE_SATURATION_PAIR_QD=(1|4|8|32) ASYNC_PREPARE=([01])",
                line)
            if match and int(match.group(1)) == current["qd"] and \
                    int(match.group(2)) == current["async_prepare"]:
                current["status"] = "PASS"
                current = None
    return sessions


def write_saturation_verdict(sessions):
    """Validate bounded QD controls plus matched fast-QD8/QD32 rounds."""
    regimes = {}
    expected_total = 0
    for regime in MODEL_ORDER:
        rows = [row for row in sessions if row.get("regime") == regime]
        expected_shape = []
        for qd in (1, 4, 8, 32):
            modes = (CONFIRMATION_SEQUENCE
                     if ((regime == "ssd_emulated" and qd in (4, 8, 32)) or
                         (regime == "sd_emulated" and qd == 32))
                     else (0, 1))
            expected_shape.extend((qd, mode) for mode in modes)
        expected_total += len(expected_shape)
        shape = [(row.get("qd"), row.get("async_prepare")) for row in rows]
        if shape != expected_shape:
            return {"overall": "INCOMPLETE",
                    "reason": f"{regime}: write-only evidence shape mismatch"}
        expected = MODEL_SPECS[regime]
        for index, row in enumerate(rows):
            if row.get("status") != "PASS" or                     set(row.get("arms", {})) != {"off", "swapz"}:
                return {"overall": "INCOMPLETE",
                        "reason": f"{regime}: incomplete write-only pair"}
            provenance_error = paired_provenance_error(
                row, f"{regime}: write-only")
            if provenance_error is not None:
                return provenance_error
            if row.get("order") != (
                    "swapz-first" if index % 2 else "off-first"):
                return {"overall": "INCOMPLETE",
                        "reason": f"{regime}: write-only replay order mismatch"}
            model = row.get("device_model")
            if not isinstance(model, dict) or any(
                    model.get(key) != expected[key]
                    for key in ("cap_mib_s", "completion_nsec", "irqmode",
                                "queue_mode", "submit_queues",
                                "hw_queue_depth")):
                return {"overall": "INCOMPLETE",
                        "reason": f"{regime}: write-only device model mismatch"}
            timed = row["arms"].get("swapz", {}).get("kernel_write_path")
            if not isinstance(timed, dict) or any(
                    type(timed.get(field)) is not int or timed[field] < 0
                    for field in KERNEL_WRITE_FIELDS) or                     timed_window_error(timed) is not None:
                return {"overall": "INCOMPLETE",
                        "reason":
                            f"{regime}: write-only timed attribution missing"}
            if (timed["lz4_acceleration"] != 1 or
                    timed["delta64_lz4_acceleration"] !=
                    PRODUCTION_DELTA64_LZ4_ACCELERATION or
                    timed["write_pipeline_depth"] != 1 or
                    timed["pipeline_active_max"] > 1 or
                    timed["delta64_rescue"] != PRODUCTION_DELTA64_RESCUE):
                return {"overall": "INCOMPLETE",
                        "reason": f"{regime}: standard write-only policy mismatch"}
            row["timed_window_delta"] = {
                field: timed[field] for field in TIMED_WINDOW_COUNTER_FIELDS
            }
            row["window_delta"] = {
                field: timed[field] for field in SATURATION_WINDOW_FIELDS
            }
            row["preparation_delta"] = {
                field: timed[field] for field in PREPARATION_FIELDS
            }
            row["retained_burst_target"] = timed["retained_burst_target"]
            if not row["async_prepare"] and (
                    timed["pipeline_async_runs"] or
                    timed["pipeline_active_wall_ns"]):
                return {"overall": "INCOMPLETE",
                        "reason":
                            f"{regime}: write-only sync arm used async run"}
            for arm in row["arms"].values():
                if arm.get("replay_mode") != "persistent-write":
                    return {"overall": "INCOMPLETE",
                            "reason":
                                f"{regime}: write-only replay is not sustained"}
                required = (
                    "input_write_mbps", "output_lower_write_mbps",
                    "logical_write_bytes", "logical_read_bytes",
                    "lower_write_bytes", "lower_write_requests",
                    "write_p99_ms", "seconds")
                if any(not isinstance(arm.get(key), (int, float))
                       for key in required):
                    return {"overall": "INCOMPLETE",
                            "reason": f"{regime}: write-only metrics missing"}
                if arm["logical_read_bytes"] != 0:
                    return {"overall": "INCOMPLETE",
                            "reason":
                                f"{regime}: write-only trace contained reads"}
                if arm["logical_write_bytes"] <= 0 or                         arm["lower_write_bytes"] <= 0:
                    return {"overall": "INCOMPLETE",
                            "reason":
                                f"{regime}: write-only byte accounting invalid"}
                if lower_inflight_error(arm.get("lower_inflight")) is not None:
                    return {"overall": "INCOMPLETE",
                            "reason":
                                f"{regime}: write-only in-flight invalid"}
            if not re.fullmatch(r"[0-9a-f]{40}",
                                row.get("source_sha", "")):
                return {"overall": "INCONCLUSIVE",
                        "reason":
                            f"{regime}: write-only source SHA unavailable"}
        regimes[regime] = rows
    if len(sessions) != expected_total:
        return {"overall": "INCOMPLETE",
                "reason": "exactly 48 write-only evidence sessions required"}
    if len({row["source_sha"] for row in sessions}) != 1 or \
            len({row.get("fixture_sha256") for row in sessions}) != 1:
        return {"overall": "INCONCLUSIVE",
                "reason": "write-only source/fixture differs"}
    for regime, rows in regimes.items():
        for qd in (1, 4, 8, 32):
            traces = {row.get("trace_sha256") for row in rows
                      if row["qd"] == qd}
            if None in traces or len(traces) != 1:
                return {"overall": "INCONCLUSIVE",
                        "reason":
                            f"{regime}: QD{qd} write-only trace mismatch"}

    summaries = {}
    for regime, rows in regimes.items():
        points = []
        for qd in (1, 4, 8, 32):
            for enabled in (0, 1):
                group = [row for row in rows
                         if row["qd"] == qd and
                         row["async_prepare"] == enabled]
                def arm_mean(candidate, field):
                    return statistics.mean(
                        row["arms"][candidate][field] for row in group)
                def dict_mean(key, fields):
                    return {
                        field: statistics.mean(row[key][field] for row in group)
                        for field in fields
                    }
                lower_fields = tuple(LOWER_INFLIGHT_FIELDS)
                points.append({
                    "qd": qd,
                    "mode": "async" if enabled else "sync",
                    "observations": len(group),
                    "raw_write_mbps": arm_mean("off", "input_write_mbps"),
                    "swapz_write_mbps":
                        arm_mean("swapz", "input_write_mbps"),
                    "swapz_to_raw_write_ratio": statistics.mean(
                        row["arms"]["swapz"]["input_write_mbps"] /
                        row["arms"]["off"]["input_write_mbps"]
                        for row in group),
                    "swapz_logical_to_lower_ratio": statistics.mean(
                        row["arms"]["swapz"]["logical_write_bytes"] /
                        row["arms"]["swapz"]["lower_write_bytes"]
                        for row in group),
                    "raw_lower_write_requests":
                        arm_mean("off", "lower_write_requests"),
                    "swapz_lower_write_requests":
                        arm_mean("swapz", "lower_write_requests"),
                    "raw_write_p99_ms": arm_mean("off", "write_p99_ms"),
                    "swapz_write_p99_ms":
                        arm_mean("swapz", "write_p99_ms"),
                    "timed_window_delta": dict_mean(
                        "timed_window_delta", TIMED_WINDOW_COUNTER_FIELDS),
                    "window_delta":
                        dict_mean("window_delta", SATURATION_WINDOW_FIELDS),
                    "preparation_delta":
                        dict_mean("preparation_delta", PREPARATION_FIELDS),
                    "retained_burst_target": statistics.mean(
                        row["retained_burst_target"] for row in group),
                    "raw_lower_inflight": {
                        field: statistics.mean(
                            row["arms"]["off"]["lower_inflight"][field]
                            for row in group)
                        for field in lower_fields
                    },
                    "swapz_lower_inflight": {
                        field: statistics.mean(
                            row["arms"]["swapz"]["lower_inflight"][field]
                            for row in group)
                        for field in lower_fields
                    },
                })
        summaries[regime] = points

    paired_results = {}
    for qd in (4, 8, 32):
        fast_rows = [row for row in regimes["ssd_emulated"]
                     if row["qd"] == qd]
        try:
            pairs = matched_binary_pairs(fast_rows, "async_prepare")
        except ValueError as exc:
            return {"overall": "INCOMPLETE",
                    "reason": f"fast QD{qd}: {exc}"}
        throughput, requests, lower_bytes = [], [], []
        for pair in pairs:
            sync = pair[0]["arms"]["swapz"]
            asynchronous = pair[1]["arms"]["swapz"]
            throughput.append(
                asynchronous["input_write_mbps"] /
                sync["input_write_mbps"] - 1.0)
            requests.append(
                asynchronous["lower_write_requests"] /
                sync["lower_write_requests"] - 1.0)
            lower_bytes.append(
                asynchronous["lower_write_bytes"] /
                sync["lower_write_bytes"] - 1.0)
        paired_results[qd] = {
            "throughput_change_fraction": paired_ci95(throughput),
            "lower_requests_change_fraction": paired_ci95(requests),
            "lower_bytes_change_fraction": paired_ci95(lower_bytes),
        }

    serial_qd32_rows = [row for row in regimes["sd_emulated"]
                         if row["qd"] == 32]
    try:
        serial_qd32_pairs = matched_binary_pairs(
            serial_qd32_rows, "async_prepare")
    except ValueError as exc:
        return {"overall": "INCOMPLETE",
                "reason": f"serial QD32: {exc}"}
    serial_throughput, serial_requests, serial_lower_bytes = [], [], []
    for pair in serial_qd32_pairs:
        sync = pair[0]["arms"]["swapz"]
        asynchronous = pair[1]["arms"]["swapz"]
        serial_throughput.append(
            asynchronous["input_write_mbps"] /
            sync["input_write_mbps"] - 1.0)
        serial_requests.append(
            asynchronous["lower_write_requests"] /
            sync["lower_write_requests"] - 1.0)
        serial_lower_bytes.append(
            asynchronous["lower_write_bytes"] /
            sync["lower_write_bytes"] - 1.0)
    serial_qd32_paired = {
        "throughput_change_fraction": paired_ci95(serial_throughput),
        "lower_requests_change_fraction": paired_ci95(serial_requests),
        "lower_bytes_change_fraction": paired_ci95(serial_lower_bytes),
    }

    return {
        "overall": "PASS_WRITE_SATURATION_EVIDENCE",
        "serial_qd32_matched_pairs": 5,
        "fast_qd4_matched_pairs": 5,
        "fast_qd8_matched_pairs": 5,
        "fast_qd32_matched_pairs": 5,
        "replay_mode": "persistent-write",
        "confidence":
            "FAST_QD4_QD8_QD32_AND_SERIAL_QD32_PAIRED_95PCT_CI_QD1_DIRECTIONAL",
        "model_limits": {
            regime: device_model_limits(MODEL_SPECS[regime])
            for regime in MODEL_ORDER
        },
        "fast_qd4_paired": paired_results[4],
        "fast_qd8_paired": paired_results[8],
        "fast_qd32_paired": paired_results[32],
        "serial_qd32_paired": serial_qd32_paired,
        "regimes": summaries,
        "interpretation":
            "SYNTHETIC_RAM_SUSTAINED_FAST_QD4_QD8_QD32_SERIAL_QD32_CONFIRMATION_QD1_DIRECTIONAL",
    }


def parse_write_pipeline_depth(output):
    """Parse five matched fast-QD32 lower-WRITE depth 1/2 rounds."""
    sessions, current = [], None
    for line in output.splitlines():
        line = line.strip()
        match = re.fullmatch(r"START_WRITE_PIPELINE_DEPTH=(1|2)", line)
        if match:
            current = {
                "write_pipeline_depth": int(match.group(1)),
                "status": "INCOMPLETE", "order": "unknown",
                "device_model": None, "arms": {},
            }
            sessions.append(current)
            continue
        if current is None:
            continue
        if line.startswith("REPLAY_ORDER="):
            current["order"] = line.partition("=")[2].strip()
        elif line.startswith("PASS_RAM_MODEL_LOWER_MBPS="):
            model = re.fullmatch(
                r"PASS_RAM_MODEL_LOWER_MBPS=(\d+) COMPLETION_NSEC=(\d+) IRQMODE=(\d+) QUEUE_MODE=(\d+) SUBMIT_QUEUES=(\d+) HW_QUEUE_DEPTH=(\d+)",
                line)
            if model:
                current["device_model"] = {
                    "cap_mib_s": int(model.group(1)),
                    "completion_nsec": int(model.group(2)),
                    "irqmode": int(model.group(3)),
                    "queue_mode": int(model.group(4)),
                    "submit_queues": int(model.group(5)),
                    "hw_queue_depth": int(model.group(6)),
                }
        elif line.startswith("{"):
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            if obj.get("candidate") not in ("off", "swapz") or \
                    obj.get("verdict") != "PASS":
                continue
            candidate = obj["candidate"]
            rates = obj.get("throughput_mbps") or {}
            lower = obj.get("lower_io") or {}
            current["arms"][candidate] = {
                "source_sha": obj.get("source_sha"),
                "fixture_sha256": obj.get("fixture_sha256"),
                "trace_sha256": obj.get("trace_sha256"),
                "replay_mode": obj.get("replay_mode"),
                "write_mbps": rates.get("logical_write_mbps"),
                "lower_write_bytes": lower.get("lower_write_bytes"),
                "lower_write_requests": lower.get("lower_write_requests"),
                "write_p99_ms": (obj.get("write_p99_ns") / 1e6
                                 if type(obj.get("write_p99_ns")) in
                                 (int, float) else None),
                "kernel_write_path": obj.get("kernel_write_path"),
            }
        else:
            done = re.fullmatch(r"PASS_WRITE_PIPELINE_DEPTH=(1|2)", line)
            if done and int(done.group(1)) == current["write_pipeline_depth"] and \
                    set(current["arms"]) == {"off", "swapz"}:
                current["status"] = "PASS"
                current = None
    return sessions


def write_pipeline_depth_verdict(sessions):
    """Validate the depth-1/2 experiment without treating gain as a gate."""
    try:
        pairs = matched_value_pairs(
            sessions, "write_pipeline_depth", 1, 2)
    except ValueError as exc:
        return {"overall": "INCOMPLETE", "reason": str(exc)}

    expected = MODEL_SPECS["ssd_emulated"]
    provenance = None
    depth2_activated = False
    for index, row in enumerate(sessions):
        if row.get("status") != "PASS" or row.get("order") != (
                "swapz-first" if index % 2 else "off-first"):
            return {"overall": "INCOMPLETE",
                    "reason": "lower-WRITE depth A/B order/status mismatch"}
        model = row.get("device_model")
        if not isinstance(model, dict) or any(
                model.get(key) != expected[key]
                for key in ("cap_mib_s", "completion_nsec", "irqmode",
                            "queue_mode", "submit_queues", "hw_queue_depth")):
            return {"overall": "INCOMPLETE",
                    "reason": "lower-WRITE depth A/B device model mismatch"}
        arm, off = row["arms"]["swapz"], row["arms"]["off"]
        kernel = arm.get("kernel_write_path")
        error = timed_window_error(kernel)
        if error:
            return {"overall": "INCOMPLETE",
                    "reason": "lower-WRITE depth A/B: " + error}
        depth = row["write_pipeline_depth"]
        if (kernel["write_pipeline_depth"] != depth or
                kernel["pipeline_active_max"] > depth or
                kernel["lz4_acceleration"] != 1 or
                kernel["delta64_lz4_acceleration"] !=
                PRODUCTION_DELTA64_LZ4_ACCELERATION or
                kernel["delta64_rescue"] != 0 or
                kernel["delta64_prepare_workers"] != 1):
            return {"overall": "INCOMPLETE",
                    "reason": "lower-WRITE depth A/B policy mismatch"}
        if depth == 2 and kernel["pipeline_active_max"] == 2:
            depth2_activated = True
        arm_prov = tuple(arm.get(key) for key in BENCHMARK_PROVENANCE_FIELDS)
        off_prov = tuple(off.get(key) for key in BENCHMARK_PROVENANCE_FIELDS)
        if (not isinstance(arm_prov[0], str) or
                not re.fullmatch(r"[0-9a-f]{40}", arm_prov[0]) or
                not isinstance(arm_prov[1], str) or
                not re.fullmatch(r"[0-9a-f]{64}", arm_prov[1]) or
                not isinstance(arm_prov[2], str) or
                not re.fullmatch(r"[0-9a-f]{64}", arm_prov[2]) or
                arm_prov != off_prov):
            return {"overall": "INCONCLUSIVE",
                    "reason": "lower-WRITE depth paired provenance mismatch"}
        if provenance is None:
            provenance = arm_prov
        elif arm_prov != provenance:
            return {"overall": "INCONCLUSIVE",
                    "reason": "lower-WRITE depth workload differs across sessions"}
        for candidate in (off, arm):
            if candidate.get("replay_mode") != "persistent-write":
                return {"overall": "INCOMPLETE",
                        "reason": "lower-WRITE depth replay is not sustained"}
            if (type(candidate.get("write_mbps")) not in (int, float) or
                    candidate["write_mbps"] <= 0 or
                    type(candidate.get("write_p99_ms")) not in (int, float) or
                    candidate["write_p99_ms"] <= 0 or
                    type(candidate.get("lower_write_bytes")) is not int or
                    candidate["lower_write_bytes"] <= 0 or
                    type(candidate.get("lower_write_requests")) is not int or
                    candidate["lower_write_requests"] <= 0):
                return {"overall": "INCOMPLETE",
                        "reason": "lower-WRITE depth performance counters missing"}
    if not depth2_activated:
        return {"overall": "INCOMPLETE",
                "reason": "depth=2 never reached two simultaneous lower WRITEs"}

    modes = {}
    for depth in (1, 2):
        rows = [row for row in sessions if row["write_pipeline_depth"] == depth]
        modes[str(depth)] = {
            "observations": len(rows),
            "write_mbps": statistics.mean(
                row["arms"]["swapz"]["write_mbps"] for row in rows),
            "write_p99_ms": statistics.mean(
                row["arms"]["swapz"]["write_p99_ms"] for row in rows),
            "lower_write_bytes": statistics.mean(
                row["arms"]["swapz"]["lower_write_bytes"] for row in rows),
            "lower_write_requests": statistics.mean(
                row["arms"]["swapz"]["lower_write_requests"] for row in rows),
            "pipeline_active_max": statistics.mean(
                row["arms"]["swapz"]["kernel_write_path"]["pipeline_active_max"]
                for row in rows),
        }
    changes = {name: [] for name in (
        "throughput_change_fraction", "p99_change_fraction",
        "lower_bytes_change_fraction", "lower_requests_change_fraction",
        "raw_control_throughput_change_fraction")}
    for pair in pairs:
        one, two = pair[1], pair[2]
        lo, hi = one["arms"]["swapz"], two["arms"]["swapz"]
        changes["throughput_change_fraction"].append(
            hi["write_mbps"] / lo["write_mbps"] - 1.0)
        changes["p99_change_fraction"].append(
            hi["write_p99_ms"] / lo["write_p99_ms"] - 1.0)
        changes["lower_bytes_change_fraction"].append(
            hi["lower_write_bytes"] / lo["lower_write_bytes"] - 1.0)
        changes["lower_requests_change_fraction"].append(
            hi["lower_write_requests"] / lo["lower_write_requests"] - 1.0)
        changes["raw_control_throughput_change_fraction"].append(
            two["arms"]["off"]["write_mbps"] /
            one["arms"]["off"]["write_mbps"] - 1.0)
    return {
        "overall": "PASS_WRITE_PIPELINE_DEPTH_EVIDENCE",
        "scope": "PAIRED_SYNTHETIC_RAM_FAST_QD32_ONLY",
        "confidence": "FIVE_PAIRED_ROUNDS_DEPTH1_DEPTH2",
        "matched_pairs": 5,
        "device_model": expected,
        "modes": modes,
        "paired": {name: paired_ci95(values)
                   for name, values in changes.items()},
        "interpretation":
            "SAME_SOURCE_QD32_K1_PREPARATION_FIFO_PUBLICATION_DEPTH1_VS_DEPTH2",
    }



def mean(items, key):
    vals = [arm[key] for arm in items if isinstance(arm.get(key), (int, float))]
    return statistics.mean(vals) if vals else None


def benchmark_verdicts(sessions):
    """Validate 8 loaded sessions; keep capped/uncapped conclusions separate."""
    regimes = {}
    for regime in MODEL_ORDER:
        rows = [s for s in sessions if s.get("regime") == regime]
        expected_modes = (list(CONFIRMATION_SEQUENCE)
                          if regime == "ssd_emulated" else [0, 1, 1, 0])
        if len(rows) != len(expected_modes) or \
                [s.get("async_prepare") for s in rows] != expected_modes or \
                any(s.get("status") != "PASS" or
                       set(s.get("arms", {})) != {"off", "swapz"} or
                       s.get("order") != ("swapz-first" if i % 2 else "off-first")
                       for i, s in enumerate(rows)):
            return {"overall": "INCOMPLETE",
                    "reason":
                        f"{regime}: required counterbalanced sessions missing"}
        expected = MODEL_SPECS[regime]
        for row in rows:
            actual = row.get("device_model")
            if not isinstance(actual, dict) or any(
                    actual.get(key) != expected[key]
                    for key in ("cap_mib_s", "completion_nsec", "irqmode", "queue_mode", "submit_queues", "hw_queue_depth")):
                return {"overall": "INCOMPLETE",
                        "reason": f"{regime}: exact owned-RAM bandwidth/timer model was not verified"}
            provenance_error = paired_provenance_error(row, f"{regime}: benchmark")
            if provenance_error is not None:
                return provenance_error
        regimes[regime] = rows
    if len(sessions) != 14:
        return {"overall": "INCOMPLETE",
                "reason": "exactly 14 modeled RAM-only sessions required"}
    all_rows = [row for regime in MODEL_ORDER for row in regimes[regime]]
    opportunities = [
        row["arms"][candidate].get("workload_opportunity")
        for row in all_rows for candidate in ("off", "swapz")]
    if (any(record is None for record in opportunities) or
            any(record != opportunities[0] for record in opportunities[1:])):
        return {"overall": "INCOMPLETE",
                "reason": "workload opportunity evidence missing or mismatched"}
    workload_opportunity = opportunities[0]
    for row in all_rows:
        timed = row["arms"].get("swapz", {}).get("kernel_write_path")
        error = timed_window_error(timed)
        if error is not None:
            return {"overall": "INCOMPLETE",
                    "reason": f"timed mixed window telemetry: {error}"}
        if (timed["lz4_acceleration"] != 1 or
                timed["delta64_rescue"] != PRODUCTION_DELTA64_RESCUE):
            return {"overall": "INCOMPLETE",
                    "reason": "standard mixed sessions require LZ4 acceleration 1 and the production delta64 default"}
        row["kernel_counter_delta"] = {
            key: timed[key]
            for key in TIMED_WINDOW_COUNTER_FIELDS + PREPARATION_FIELDS
        }
        row["retained_burst_target"] = timed["retained_burst_target"]
    for digest in ("source_sha", "fixture_sha256", "trace_sha256"):
        vals = [row.get(digest) for row in all_rows]
        if None in vals or len(set(vals)) != 1:
            return {"overall": "INCONCLUSIVE",
                    "reason": f"benchmark {digest} differs across regimes"}

    verdicts = {}
    for regime, rows in regimes.items():
        arms = {"off": [s["arms"]["off"] for s in rows],
                "sync": [s["arms"]["swapz"] for s in rows if not s["async_prepare"]],
                "async": [s["arms"]["swapz"] for s in rows if s["async_prepare"]]}
        columns = {}
        keys = ("input_write_mbps", "output_lower_write_mbps",
                "swap_in_read_mbps", "swap_in_read_p99_ms",
                "write_p99_ms", "lower_write_bytes", "lower_write_requests",
                "lower_read_bytes", "lower_read_requests",
                "mixed_replay_cpu_user_s", "mixed_replay_cpu_system_s",
                "mixed_replay_peak_rss_kb", "seconds")
        for name, rows_for_arm in arms.items():
            columns[name] = {key: mean(rows_for_arm, key) for key in keys}
            host_records = [host_cpu_record(arm) for arm in rows_for_arm]
            columns[name]["host_cpu"] = {
                **{key: mean(host_records, key) for key in HOST_CPU_FIELDS},
                "observations": sum(record.get("status") in ("AVAILABLE", "PARTIAL")
                                    for record in host_records),
                "expected_observations": len(rows_for_arm),
                "pressure_observations": sum(record.get("pressure_some_fraction") is not None
                                             for record in host_records),
            }
            input_bytes = mean(rows_for_arm, "logical_write_bytes")
            backing_bytes = columns[name]["lower_write_bytes"]
            columns[name]["write_input_per_lower_byte"] = (
                input_bytes / backing_bytes if input_bytes and backing_bytes else None)
            inflight_records = [arm.get("lower_inflight") for arm in rows_for_arm]
            if any(lower_inflight_error(record) is not None
                   for record in inflight_records):
                return {"overall": "INCOMPLETE",
                        "reason": f"{regime}: missing/inconsistent lower in-flight telemetry"}
            for field in LOWER_INFLIGHT_FIELDS:
                columns[name][f"lower_inflight_{field}"] = statistics.mean(
                    record[field] for record in inflight_records)
            if name != "off":
                # kernel_write_path is an interval delta. Histogram totals
                # must remain exact, but a follow-up can land inside this
                # interval after its matching dry close occurred just before
                # the starting snapshot.
                diagnostics = [arm.get("kernel_write_path") for arm in rows_for_arm]
                if any(not isinstance(record, dict) or
                       any(type(record.get(field)) is not int or
                           record[field] < 0 for field in KERNEL_WRITE_FIELDS) or
                       sum(record[field] for field in WRITE_WAIT_BINS) !=
                           record["physical_write_reqs"] or
                       record["window_commit_nonio_wall_ns"] >
                           record["window_commit_wall_ns"] or
                       sum(record[field] for field in
                           ("engine_plan_wall_ns", "engine_pack_wall_ns",
                            "engine_publish_wall_ns")) >
                           record["window_commit_nonio_wall_ns"] or
                       record["engine_publish_crc_wall_ns"] +
                           record["engine_publish_auth_wall_ns"] !=
                           record["engine_publish_wall_ns"] or
                       record["sync4_lower_write_ns"] +
                           record["sync4_nonio_ns"] !=
                           record["sync4_wall_ns"] or
                       record["sync4_reissue_samples"] >
                           record["sync4_windows"] or
                       timed_window_error(record) is not None or
                       record["prep_lower_write_start_nonempty"] >
                           record["prep_lower_write_samples"] or
                       record["prep_lower_write_end_nonempty"] >
                           record["prep_lower_write_samples"] or
                       record["prep_lower_write_start_queued"] <
                           record["prep_lower_write_start_nonempty"] or
                       record["prep_lower_write_end_queued"] <
                           record["prep_lower_write_end_nonempty"]
                       for record in diagnostics):
                    return {"overall": "INCOMPLETE",
                            "reason": f"{regime}: missing/inconsistent timed swapz C write counters"}
                for field in KERNEL_WRITE_FIELDS:
                    columns[name][f"mixed_{field}"] = statistics.mean(
                        record[field] for record in diagnostics)
                if name == "sync" and any(
                        record["pipeline_async_runs"] or
                        record["pipeline_active_wall_ns"] or
                        record["pipeline_post_lower_wall_ns"]
                        for record in diagnostics):
                    return {"overall": "INCOMPLETE",
                            "reason": f"{regime}: sync arm used async run occupancy"}
                if any(record["pipeline_active_wall_ns"] >
                       arm["seconds"] * 1e9 + 1000000
                       for record, arm in zip(diagnostics, rows_for_arm)):
                    return {"overall": "INCOMPLETE",
                            "reason": f"{regime}: K=1 run occupancy exceeds timed interval"}
                columns[name]["mixed_pipeline_active_mean"] = statistics.mean(
                    record["pipeline_active_wall_ns"] / (arm["seconds"] * 1e9)
                    for record, arm in zip(diagnostics, rows_for_arm))
                columns[name]["mixed_pipeline_active_peak"] = max(
                    1 if record["pipeline_async_runs"] else 0
                    for record in diagnostics)
            for mode in ("sequential", "seeded_random"):
                reads = [(arm.get("packed_read") or {}).get("passes", {}).get(mode)
                         for arm in rows_for_arm]
                if any(not isinstance(item, dict) or
                       item.get("logical_bytes") != 4194304 or
                       item.get("verified_pages") != 1024 or
                       not item.get("verified_image_sha256") for item in reads):
                    return {"overall": "INCOMPLETE",
                            "reason": f"{regime}: measured 4MiB {mode} read missing"}
                columns[name][f"{mode}_4mib_s"] = statistics.mean(
                    item["seconds"] for item in reads)
                columns[name][f"{mode}_read_p99_ms"] = statistics.mean(
                    item["read_p99_ms"] for item in reads)
                columns[name][f"{mode}_lower_read_bytes"] = statistics.mean(
                    item["lower_read_bytes"] for item in reads)
                columns[name][f"{mode}_lower_read_requests"] = statistics.mean(
                    item["lower_read_requests"] for item in reads)
                if name != "off":
                    diagnostics = [item.get("kernel_read_path") for item in reads]
                    if any(not isinstance(record, dict) or
                           any(type(record.get(field)) is not int or
                               record[field] < 0 for field in KERNEL_READ_FIELDS) or
                           not read_metadata_counters_consistent(record) or
                           record["parallel_read_same_extent_pairs"] >
                               record["parallel_read_pairs"] or
                           record["parallel_read_distinct_extent_pairs"] >
                               record["parallel_read_pairs"] or
                           record["parallel_read_adjacent_extent_pairs"] >
                               record["parallel_read_distinct_extent_pairs"] or
                           record["parallel_read_adjacent_extent_blocks"] <
                               2 * record["parallel_read_adjacent_extent_pairs"] or
                           record["parallel_read_adjacent_extent_blocks"] >
                               8 * record["parallel_read_adjacent_extent_pairs"] or
                           record["parallel_read_coalesced_pairs"] >
                               record["parallel_read_adjacent_extent_pairs"] or
                           record["parallel_read_coalesced_reqs_saved"] <
                               record["parallel_read_coalesced_pairs"] or
                           record["parallel_read_coalesced_reqs_saved"] >
                               7 * record["parallel_read_coalesced_pairs"] or
                           record["parallel_read_coalesced_blocks"] <
                               2 * record["parallel_read_coalesced_pairs"] or
                           record["parallel_read_coalesced_blocks"] >
                               8 * record["parallel_read_coalesced_pairs"] or
                           record["parallel_read_coalesce_extra_blocks"] != 0 or
                           record["parallel_read_coalesce_skip_other"] != 0
                           for record in diagnostics):
                        return {"overall": "INCOMPLETE",
                                "reason": f"{regime}: missing/inconsistent measured swapz {mode} C read counters"}
                    for field in KERNEL_READ_FIELDS:
                        columns[name][f"{mode}_{field}"] = statistics.mean(
                            record[field] for record in diagnostics)
            if name != "off" and any(
                    not (arm["packed_read"].get("packed_close_delta") or 0) > 0
                    for arm in rows_for_arm):
                return {"overall": "INCOMPLETE",
                        "reason": f"{regime}: packed-write closure not demonstrated"}

        raw = columns["off"]
        criteria = {}
        for mode in ("sync", "async"):
            paired = [s for s in rows if s["async_prepare"] == (mode == "async")]
            change = [(s["arms"]["swapz"]["input_write_mbps"] /
                       s["arms"]["off"]["input_write_mbps"] - 1)
                      for s in paired]
            def decision(vals):
                return ("MATERIAL_GAIN_PRELIMINARY" if all(v >= .05 for v in vals)
                        else "MATERIAL_LOSS_PRELIMINARY" if all(v <= -.05 for v in vals)
                        else "NO_ESTABLISHED_GAIN")
            criteria[mode] = {
                "throughput_vs_raw": decision(change),
                "paired_write_gain_fraction": change,
                "lower_write_saved_fraction": (
                    1 - columns[mode]["lower_write_bytes"] / raw["lower_write_bytes"]),
                "lower_write_savings": (
                    "PASS" if all(s["arms"]["swapz"]["lower_write_bytes"] <
                                  s["arms"]["off"]["lower_write_bytes"]
                                  for s in paired) else "NO_GAIN"),
                "mixed_read_p99": (
                    "LOWER" if all(s["arms"]["swapz"]["swap_in_read_p99_ms"] <
                                   s["arms"]["off"]["swap_in_read_p99_ms"]
                                   for s in paired) else "NOT_LOWER"),
                "packed_4mib_sequential": (
                    "FASTER" if all(
                        s["arms"]["swapz"]["packed_read"]["passes"]["sequential"]["seconds"] <
                        s["arms"]["off"]["packed_read"]["passes"]["sequential"]["seconds"]
                        for s in paired) else "NOT_FASTER"),
            }
        delta = (columns["async"]["input_write_mbps"] /
                 columns["sync"]["input_write_mbps"] - 1)
        if regime == "ssd_emulated":
            try:
                mixed_pairs = matched_binary_pairs(rows, "async_prepare")
            except ValueError as exc:
                return {"overall": "INCOMPLETE",
                        "reason": f"{regime}: {exc}"}
            pair_deltas = []
            pair_request_deltas = []
            pair_request_absolute_deltas = []
            cause_deltas = {field: [] for field in PACK_CLOSE_FIELDS}
            burst_detail_deltas = {
                field: [] for field in BURST_CLOSE_DETAIL_FIELDS}
            for pair in mixed_pairs:
                sync = pair[0]["arms"]["swapz"]
                asynchronous = pair[1]["arms"]["swapz"]
                pair_deltas.append(
                    asynchronous["input_write_mbps"] /
                    sync["input_write_mbps"] - 1.0)
                pair_request_deltas.append(
                    asynchronous["lower_write_requests"] /
                    sync["lower_write_requests"] - 1.0)
                pair_request_absolute_deltas.append(
                    asynchronous["lower_write_requests"] -
                    sync["lower_write_requests"])
                for field in PACK_CLOSE_FIELDS:
                    cause_deltas[field].append(
                        asynchronous["kernel_write_path"][field] -
                        sync["kernel_write_path"][field])
                for field in BURST_CLOSE_DETAIL_FIELDS:
                    burst_detail_deltas[field].append(
                        asynchronous["kernel_write_path"][field] -
                        sync["kernel_write_path"][field])
            throughput_ci = paired_ci95(pair_deltas)
            request_ci = paired_ci95(pair_request_deltas)
            request_absolute_ci = paired_ci95(pair_request_absolute_deltas)
            cause_ci = {
                field: paired_ci95(values)
                for field, values in cause_deltas.items()
            }
            burst_detail_ci = {
                field: paired_ci95(values)
                for field, values in burst_detail_deltas.items()
            }
            if throughput_ci["low"] >= .05:
                throughput_result = "CONFIRMED_5PCT_GAIN"
            elif throughput_ci["high"] <= -.05:
                throughput_result = "CONFIRMED_5PCT_LOSS"
            else:
                throughput_result = "NO_CONFIRMED_5PCT_GAIN"
            criteria["async_vs_sync"] = {
                "write_gain_fraction": throughput_ci["mean"],
                "write_throughput": throughput_result,
                "matched_pairs": 5,
                "paired_95pct_ci": throughput_ci,
                "lower_request_change_paired_95pct_ci": request_ci,
                "lower_request_absolute_delta_paired_95pct_ci":
                    request_absolute_ci,
                "pack_ready_cause_delta_paired_95pct_ci": cause_ci,
                "burst_close_detail_delta_paired_95pct_ci":
                    burst_detail_ci,
                "caution": "Synthetic RAM model; five matched pairs",
            }
        else:
            criteria["async_vs_sync"] = {
                "write_gain_fraction": delta,
                "write_throughput": (
                    "PRELIMINARY_5PCT_GAIN" if delta >= .05 else
                    "PRELIMINARY_5PCT_LOSS" if delta <= -.05 else
                    "NO_SIGNIFICANT_ASYNC_GAIN"),
                "caution":
                    "Only two observations per mode; no confidence interval",
            }
        verdicts[regime] = {
            "columns": columns, "criteria": criteria,
            "device_model": MODEL_SPECS[regime],
            "interpretation": "SYNTHETIC_RAM_MODEL_ONLY_NOT_PHYSICAL_MEDIA",
            "kernel_counters": {
                key: statistics.mean(row["kernel_counter_delta"][key]
                                     for row in rows)
                for key in (BURST_COUNTER_FIELDS + ("windows",
                            "one_page_windows", "gc_victims",
                            "accepted_work_lower_idle_events",
                            "accepted_work_lower_idle_ns",
                            "accepted_work_lower_idle_undersized_batch_ns",
                            "accepted_work_lower_idle_worker_unscheduled_ns",
                            "accepted_work_lower_idle_preparing_head_ns",
                            "accepted_work_lower_idle_no_ready_work_ns",
                            "accepted_work_lower_idle_post_lower_ns") + WIN1_PACK_CAUSE_FIELDS +
                            SINGLE_TAIL_FIELDS + ID52_FIELDS + PACK_CLOSE_FIELDS + BURST_CLOSE_DETAIL_FIELDS + TAIL_SAMPLE_FIELDS + K1_READY_WAIT_FIELDS + CLOSE_REASON_FIELDS + ONE_PAGE_CLOSE_FIELDS +
                            DEADLINE_CONTEXT_FIELDS)
            },
            "kernel_gauges": {
                "retained_burst_target": statistics.mean(
                    row["retained_burst_target"] for row in rows)
            },
            "preparation_counters": {
                key: statistics.mean(row["kernel_counter_delta"][key]
                                     for row in rows if row["async_prepare"])
                for key in PREPARATION_FIELDS
            },
        }
    return {
        "overall": "PASS_BOUNDED_RAM_MATRIX",
        "regimes": verdicts,
        "endurance": "PROXY_ONLY: lower RAM device writes, no flash endurance",
        "packed_read": "MEASURED_4MIB_QD32_NO_COLD_CACHE_PROOF",
        "gc": "SEPARATE_LOADED_EVIDENCE_REQUIRED",
        "cpu_scope":
            "worker-boundary sum_exec_runtime is a scheduler-accounted diagnostic "
            "that may omit pending runtime or charge earlier execution at boundaries; ACK helper has no dedicated CPU measurement; "
            "phase timers measure partial wall time including preemption, not CPU bounds",
        "physical_media": "NOT_TESTED",
        "host_load_scope": "WHOLE_HOST_INCLUDING_BENCHMARK_AND_BACKGROUND",
        "idle_host_control": "NOT_ESTABLISHED",
        "cross_report_cpu_comparability": "REQUIRES_EQUIVALENT_HOST_LOAD",
        "delta64_scope": "FOREGROUND_PREPARATION_ATTEMPTS_NOT_COMMITTED_OR_LOWER_IO",
        "delta64_timing_scope": "WALL_INCLUDING_PREEMPTION_AND_SECOND_LZ4_OVERLAP",
        "workload_opportunity": workload_opportunity,
        "statistical_confidence":
            "FAST_MIXED_FIVE_MATCHED_PAIRS_WITH_PAIRED_95PCT_CI; "
            "SLOW_TWO_OBSERVATIONS_PER_MODE",
        "real_swap_device": "NOT_AUTHORIZED_NOT_TESTED",
    }


TABLE_HEADER_LEGEND = {
    "A/raw": "async swapz useful WRITE percent change versus raw/off",
    "scope": "evidence area",
    "value": "scope limit or result detail",
    "control": "deterministic classifier input designed to catch a sampling blind spot",
    "accel": "LZ4 compression acceleration setting",
    "ns/page": "elapsed LZ4 compression nanoseconds per page",
    "payload B": "total accepted encoded payload bytes",
    "RAW": "pages retained uncompressed",
    "pair": "counterbalanced same-host measurement pair",
    "order": "measurement order within the pair",
    "baseline ns/page": "original SSE2 forward nanoseconds per page",
    "2x ns/page": "two-vector SSE2 forward nanoseconds per page",
    "minimum": "minimum score required for the control to pass",
    "pack eligible": "already-compressed pages with an exact uniform packing limit",
    "passed": "eligible pages meeting their configured route threshold",
    "attempts": "full-page transform and delta64-candidate LZ4 attempts",
    "payload bytes": "encoded payload bytes avoided in the native model",
    "blocks saved": "physical blocks saved by the actual native window planner",
    "extents saved": "physical extents saved by the actual native window planner",
    "modeled ns/page": "elapsed-time model per page; not measured worker CPU",
    "transform": "candidate page transform",
    "adopt": "pages adopting the candidate transform",
    "RAW+": "raw pages made compressible",
    "<=2024": "payloads at or below 2024 bytes",
    "blocks": "physical 4KiB blocks (signed values indicate savings)",
    "extents": "physical extents",
    "xform ns": "native elapsed delta64 transform nanoseconds per page",
    "inv ns": "native elapsed delta64 inverse-transform nanoseconds per page",
    "LZ4 ns": "native elapsed LZ4 compression nanoseconds per transformed page; excludes delta64 transform",
    "backend": "implementation backend",
    "score": "candidate threshold or score",
    "neg call/eligible": "negative calls / eligible pages",
    "neg useful": "useful negative classifications",
    "struct call/eligible": "structured calls / eligible pages",
    "struct useful": "useful structured classifications",
    "cpu/page ns": "modeled write CPU cost from native elapsed ns per page",
    "ns/saved block": "modeled cost per planner block saved; not measured worker CPU",
    "SD x": "modeled SD I/O-time / modeled write CPU-cost ratio",
    "SSD x": "modeled SSD I/O-time / modeled write CPU-cost ratio",
    "profile": "input-content profile",
    "call/eligible": "classifier calls / eligible pages",
    "useful": "useful classifier outcomes",
    "pages": "logical 4KiB pages",
    "logical pages": "logical 4KiB pages",
    "segs": "physical segments",
    "segments": "physical segments",
    "old ms": "legacy scan time in milliseconds",
    "select ms": "candidate selection time in milliseconds",
    "map ms": "mapping scan time in milliseconds",
    "list ms": "survivor-list scan time in milliseconds",
    "old probe ms": "legacy allocator-probe time in milliseconds",
    "mapped probe ms": "mapped-count allocator-probe time in milliseconds",
    "geometry": "simulated placement policy",
    "waste": "unused physical blocks",
    "W runs": "contiguous backing WRITE runs",
    "cold R blk": "cold READ blocks per logical workload unit",
    "seq req": "sequential lower READ requests",
    "writes": "logical WRITE operations",
    "same-filled": "nonzero pages filled by one repeated 64-bit word",
    "same-page": "rewrites to the same logical page",
    "resident-dup": "writes matching a currently resident value",
    "uniq payloads": "distinct payload values",
    "mode": "arm: off=raw, sync=ordered swapz, async=prepared swapz",
    "W": "useful logical WRITE throughput in decimal MB/s",
    "lower W": "backing-device WRITE throughput in decimal MB/s",
    "W req": "backing-device WRITE request count",
    "R": "useful logical READ throughput in decimal MB/s",
    "R p99": "READ 99th-percentile latency in milliseconds",
    "host busy %": "active CPU ticks as a percentage of all online-CPU ticks",
    "CPU wait %": "wall-time percentage with CPU-waiting tasks from PSI some",
    "steal %": "online-CPU time unavailable to a virtual guest",
    "replay cores": "replay user plus system CPU seconds per measured second",
    "CPUs": "online CPUs / replay affinity CPUs",
    "CPU n": "phases with CPU counters / phases expected; missing values are N/A",
    "read": "READ workload or access pattern",
    "lower KiB": "backing-device READ data in KiB",
    "lower": "lower-device I/O wall time in milliseconds",
    "req": "backing-device request count",
    "p99": "99th-percentile latency in milliseconds",
    "engine": "swapz read-engine time in milliseconds",
    "LZ4": "decompression time in milliseconds",
    "copy": "read-copy time in milliseconds",
    "bdev R": "lower-device READ in-flight mean / peak",
    "bdev W": "lower-device WRITE in-flight mean / peak",
    "K=1 run slot": "active immutable lower-WRITE run mean / peak",
    "1": "one-record windows or one-block extents, as titled",
    "2": "two-record windows or two-block extents, as titled",
    "3-4": "three-to-four-record windows or extents, as titled",
    "5-8": "five-to-eight-record windows or extents, as titled",
    "9-16": "nine-to-sixteen-record windows",
    "17-64": "seventeen-to-sixty-four-record windows",
    "P/D/I": "PACK_READY / deadline / idle window closes",
    "tail<=4": "PACK_READY closes with at most four records remaining",
    "tail": "PACK_READY closes with a larger remaining tail",
    "t2/3/4": "sampled-tail PACK_READY closes with exact target two / three / four",
    "next<ddl 2/3": "target-2 / target-3 closes followed by a later plain "
                    "WRITE before the displaced deadline",
    "sup": "small-tail follow-up observations superseded by another 2/3-target close",
    "burst": "burst-target PACK_READY closes",
    "dry": "service-dry PACK_READY closes",
    "adm/wrk": "burst closes attributed to admission / worker",
    "t<=4/5-8/9-16/17+": "target-close counts by target-size range",
    "c<=4/5-8/9-16/17+": "window record counts by size range",
    "over": "burst-target overshoot count",
    "0 I/N": "zero-record tails with lower WRITE in flight / no WRITE in flight",
    "1 I/N": "one-record tails with lower WRITE in flight / no WRITE in flight",
    "2+ I/N": "tails of two or more records with WRITE in flight / no WRITE in flight",
    "grow/shrink": "burst-target growth / shrink events",
    "skip-I0": "shrink skips at zero in-flight",
    "after-I0": "shrinks after in-flight reaches zero",
    "after-read": "shrinks after a READ bypass",
    "other": "other recorded causes",
    "<=8": "shrink targets up to eight records",
    "9-32": "shrink targets of nine to thirty-two records",
    ">32": "shrink targets above thirty-two records",
    "stage": "measured pipeline stage",
    "busy ms": "stage wall time in milliseconds",
    "overlap/stall ms": "overlap or stall time in milliseconds",
    "async signal": "asynchronous-preparation counter",
    "mean": "paired effect estimate or average; units follow the metric",
    "check": "qualification criterion",
    "result": "measured outcome for that criterion",
    "merge": "adjacent-range merge: 0=off, 1=on",
    "fanout": "independent lower-READ fan-out: 0=off, 1=on",
    "R req": "backing-device READ request count during mixed I/O",
    "batches/slots": "asynchronous independent READ batches / submitted lower ranges",
    "seq req": "sequential lower READ requests",
    "seq p99": "sequential READ p99 latency in milliseconds",
    "rnd req": "seeded-random lower READ requests",
    "rnd p99": "seeded-random READ p99 latency in milliseconds",
    "seq saved": "sequential READ requests saved by merging",
    "rnd saved": "seeded-random READ requests saved by merging",
    "dist": "distinct eligible extent pairs",
    "adj": "physically adjacent extent pairs",
    "merged": "pairs merged into one lower READ",
    "extra": "extra blocks read outside requested extents",
    "cached": "pairs skipped because data was cached",
    "noncontig": "pairs skipped because extents were not contiguous",
    "gap": "pairs skipped because a physical gap existed",
    "metric": "measured effect",
    "low": "paired 95% confidence-interval lower bound",
    "high": "paired 95% confidence-interval upper bound",
    "model": "synthetic lower-device model",
    "cap MB/s": "configured lower-device cap in decimal MB/s",
    "4K latency MB/s": "analytical unmerged 4KiB latency ceiling",
    "effective MB/s": "minimum of configured cap and 4KiB ceiling",
    "raw QD32 MB/s": "measured raw WRITE throughput at queue depth 32",
    "QD": "upper workload queue depth",
    "raw": "raw, uncompressed WRITE throughput in MB/s",
    "sync": "synchronous swapz WRITE throughput in MB/s",
    "async": "asynchronous-preparation swapz WRITE throughput in MB/s",
    "A/S": "percentage change in async versus sync throughput: 100 * (async/sync - 1)",
    "A req": "lower-device WRITE requests in the async arm",
    "wave": "preparation waves started",
    "head/tail": "producer head / tail claims",
    "inline": "ordered-worker inline preparations",
    "hand/wait": "preparation handoffs / blocking waits",
    "target": "retained burst target in records",
    "eligible": "RAW or >2024-byte LZ4 baselines, plus smaller LZ4 pages with a uniform packing limit",
    "rescue": "delta64 policy: off=default bypass, on=opted in, mixed=unmatched policy",
    "passed": "eligible pages passing threshold 24, or threshold 16 on the smaller-LZ4 packing path",
    "attempts": "full-page delta64 transform attempts",
    "adopted": "attempts selecting a strictly smaller delta64 payload",
    "LZ4+": "adoptions replacing ordinary LZ4, including smaller packing-path payloads",
    "pack eligible": "LZ4 baselines at most 2024 bytes with a lower uniform packing limit",
    "pack try": "packing-path full-page delta64 attempts after threshold-16 classification",
    "cliff": "candidates crossing a uniform packing limit; not measured lower blocks saved",
    "pack+": "smaller-LZ4 packing-path adoptions that crossed their uniform limit",
    "score 0-7": "eligible pages with sampled classifier scores from zero through seven",
    "8-15": "eligible pages with classifier scores from eight through fifteen",
    "16-23": "eligible pages with classifier scores from sixteen through twenty-three",
    "24+": "eligible pages with classifier scores of at least twenty-four",
    "lookups": "metadata-directory lookups; scratch/extent-cache hits bypass this lookup",
    "set hit %": "percentage of directory lookups finding the exact key in either candidate set",
    "primary %": "percentage of directory lookups hitting the primary four-way set",
    "secondary %": "percentage of directory lookups hitting the secondary set after a primary miss",
    "probes/lookup": "mean directory tags inspected per lookup; at most eight across two sets",
    "repl": "insertions evicting the oldest eligible tag when both candidate sets are full",
    "meta copy KiB": "cached block-zero payload fragments copied to read scratch; excludes cache insertion copies",
    "payload KiB": "encoded bytes avoided versus ordinary LZ4 or 4KiB RAW; not lower I/O",
    "RAW+ KiB": "encoded bytes avoided by RAW rescues, in KiB",
    "LZ4+ KiB": "encoded bytes avoided by ordinary LZ4 rescues, in KiB",
    "rescue ms": "classifier, delta64 transform, candidate LZ4 and copy wall ms; not CPU time",
    "swap W": "useful swapz WRITE throughput in decimal MB/s",
    "W MB/s": "useful logical WRITE throughput in decimal MB/s",
    "seq MB/s": "useful sequential READ throughput in decimal MB/s",
    "rnd MB/s": "useful seeded-random READ throughput in decimal MB/s",
    "lower req": "backing-device request count",
    "LZ4 ms": "measured LZ4 wall time in the interval",
    "PSI some %": "CPU pressure-stall some fraction during the measured interval",
    "D64 ms": "delta64 route wall time in the measured interval",
    "prep LZ4 ms": "preparation-worker LZ4 wall time in the measured interval",
    "parallel": "parallel preparation starts",
    "depth": "configured lower-WRITE submission depth",
    "active max": "maximum simultaneously active lower-WRITE runs",
    "K": "preparation width",
}

TABLE_HEADER_GOAL = {
    "A/raw": "positive is better; requires correct lower-I/O and latency tradeoffs",
    "ns/page": "lower for equal work",
    "payload B": "lower for equal input",
    "baseline ns/page": "lower is faster",
    "2x ns/page": "lower is faster",
    "xform ns": "lower is better for equivalent work",
    "inv ns": "lower is better for equivalent work",
    "LZ4 ns": "lower is better for equivalent work",
    "neg call/eligible": "lower is better",
    "cpu/page ns": "lower is better",
    "ns/saved block": "lower is better",
    "old ms": "lower is faster",
    "select ms": "lower is faster",
    "map ms": "lower is faster",
    "list ms": "lower is faster",
    "old probe ms": "lower is faster",
    "mapped probe ms": "lower is faster",
    "waste": "lower is better",
    "W runs": "lower is better for equivalent useful work",
    "cold R blk": "lower is better",
    "seq req": "lower is better",
    "W": "higher is better",
    "lower W": "lower is better for equivalent useful work",
    "W req": "lower is better",
    "R": "higher is better",
    "R p99": "lower is better",
    "host busy %": "lower is preferable for equivalent useful work",
    "CPU wait %": "lower is better",
    "steal %": "lower is better",
    "replay cores": "lower is preferable for equivalent useful work",
    "CPU n": "target is all expected phases",
    "lower KiB": "lower is better",
    "lower": "lower is better",
    "req": "lower is better",
    "p99": "lower is better",
    "engine": "lower is better for equivalent work",
    "LZ4": "lower is better for equivalent work",
    "copy": "lower is better for equivalent work",
    "seq p99": "lower is better",
    "rnd req": "lower is better",
    "rnd p99": "lower is better",
    "R req": "lower is better",
    "seq saved": "higher is better if latency and correctness hold",
    "rnd saved": "higher is better if latency and correctness hold",
    "extra": "target is zero",
    "other": "target is zero for defensive skip accounting",
    "probes/lookup": "lower is better",
    "repl": "lower is better",
    "meta copy KiB": "lower is better",
    "set hit %": "higher is preferable; end-to-end I/O still decides",
    "raw QD32 MB/s": "higher is better",
    "raw": "higher is better",
    "sync": "higher is better",
    "async": "higher is better",
    "A/S": "higher is better when other acceptance gates hold",
    "A req": "lower is better",
    "rescue ms": "lower is better for equivalent rescue outcome",
    "swap W": "higher is better",
    "W MB/s": "higher is better",
    "seq MB/s": "higher is better",
    "rnd MB/s": "higher is better",
    "lower req": "lower is better",
    "LZ4 ms": "lower is better for equivalent outcome",
    "PSI some %": "lower is better for equivalent useful work",
    "D64 ms": "lower is better for equivalent outcome",
    "prep LZ4 ms": "lower is better for equivalent outcome",
}


def _table_number(value):
    """Read a scalar measurement; slash-separated tuples are not scalars."""
    value = str(value).strip()
    if "/" in value:
        return None
    match = re.match(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+))", value)
    return float(match.group(1)) if match else None


def _print_table_note(label, message):
    prefix = f"  {label}: "
    print(textwrap.fill(message, width=94, initial_indent=prefix,
                         subsequent_indent="    "))


def _percent_change(candidate, baseline):
    if baseline in (None, 0) or candidate is None:
        return None
    return candidate / baseline - 1.0


def _directional_project_state(changes):
    """Classify mean directions only; confidence intervals still qualify claims."""
    benefits = 0
    regressions = 0
    for change, lower_is_better in changes:
        if change is None or change == 0:
            continue
        helpful = change < 0 if lower_is_better else change > 0
        if helpful:
            benefits += 1
        else:
            regressions += 1
    if benefits and not regressions:
        return "ALIGNED"
    if benefits and regressions:
        return "TRADE-OFF"
    if regressions:
        return "NOT ALIGNED"
    return "NEUTRAL"


def _ci_metric_preference(metric):
    """Return higher/lower/control for product-facing confidence-interval rows."""
    metric = metric.lower()
    if "raw-control" in metric:
        return "control"
    if any(token in metric for token in ("p99", "lower b", "lower req",
                                          "wall", "cpu")) or metric == "req":
        return "lower"
    if any(token in metric for token in ("throughput", "mb/s")) or metric == "w %":
        return "higher"
    return None


def _table_interpretation(headers, rows):
    """Summarize table data without turning descriptive rows into a verdict."""
    header_index = {str(header): index for index, header in enumerate(headers)}
    if "set hit %" in header_index:
        summary = ", ".join(
            f"{row[0]} {row[header_index['set hit %']]}% hits / "
            f"{row[header_index['repl']]} replacements" for row in rows)
        return (f"Directory observations: {summary}. Primary plus secondary hits equal "
                "total hits; percentages are rounded. Misses inspect eight tags. Scratch/extent hits "
                "bypass lookup. Secondary hits show use of the second choice, not proved "
                "I/O savings; compare lower bytes/requests, engine wall time and host CPU.")
    if "pack eligible" in header_index:
        return ("Packing-path attempts concern already-compressed pages at most 2024 bytes. "
                "A cliff crossing is uniform-page geometry opportunity; the actual mixed "
                "window may save no blocks. A disabled rescue policy also produces all zeros.")
    if "score 0-7" in header_index:
        return ("The four score bins partition eligible pages. Threshold 24 applies to RAW "
                "and larger LZ4 baselines; threshold 16 applies to smaller packing candidates. "
                "All-zero bins under rescue=off provide no classifier-selectivity evidence.")
    if "cpu/page ns" in header_index:
        return ("This model combines separate native elapsed-time measurements, "
                "which include scheduling effects. It does not measure worker CPU, "
                "inverse-read cost or loaded throughput; a ratio above one is "
                "modeled opportunity, not a demonstrated speedup.")
    if "eligible" in header_index and "adopted" in header_index:
        if "rescue" in header_index and all(
                row[header_index["rescue"]] == "off" for row in rows):
            return ("Delta64 rescue is disabled: no classifier, transform or rescue timer "
                    "runs. Zero counters describe the bypass, not classifier selectivity.")
        adopted = [_table_number(row[header_index["adopted"]]) or 0 for row in rows]
        if not any(adopted):
            return ("No delta64 payload was adopted in these measured intervals. "
                    "This workload supplies no loaded delta64 savings evidence; "
                    "native corpus opportunity does not establish a speedup.")
        summary = ", ".join(f"{row[0]}={count:g}" for row, count in zip(rows, adopted))
        return (f"Observed mean adoptions: {summary}. "
                "These are preparation attempts, including later-aborted writes, "
                "not committed mappings. Adoption proves use, not a throughput benefit.")
    if "payload KiB" in header_index:
        summary = ", ".join(
            f"{row[0]}={_table_number(row[header_index['payload KiB']]) or 0:g} KiB"
            for row in rows)
        return (f"Mean encoded payload avoided: {summary}. "
                "Extent packing, padding, reads and GC determine actual lower I/O. "
                "Rescue wall time includes preemption and overlaps other timing rows; "
                "do not add it to LZ4 time or call it CPU cost.")
    if all(name in header_index for name in ("read", "lower KiB", "req", "p99")):
        by_read = {str(row[header_index["read"]]): row for row in rows}
        summaries = []
        project_changes = []
        for label in ("seq", "rnd"):
            raw_row = by_read.get(f"{label}-off")
            swapz_row = by_read.get(f"{label}-async")
            if raw_row is None or swapz_row is None:
                continue
            changes = []
            for column, name in (("lower KiB", "lower READ bytes"),
                                 ("req", "requests"), ("p99", "p99")):
                raw_value = _table_number(raw_row[header_index[column]])
                swapz_value = _table_number(swapz_row[header_index[column]])
                change = _percent_change(swapz_value, raw_value)
                if change is not None:
                    changes.append(f"{name} {change * 100:+.1f}%")
                    project_changes.append((change, True))
            if changes:
                summaries.append(f"{label} vs raw: " + ", ".join(changes))
        if summaries:
            state = _directional_project_state(project_changes)
            return (f"Directional project view vs raw: {state}. " +
                    "; ".join(summaries) +
                    ". Lower READ bytes/requests support swap-in I/O efficiency; they are not a "
                    "write-endurance claim. Lower p99 supports latency. These are means; "
                    "qualification still "
                    "depends on matched evidence where available.")
    if "host busy %" in header_index:
        return ("Host activity includes the benchmark, kernel workers and background apps. "
                "PSI measures CPU waiting, not its owner. These observations do not prove "
                "an idle host or equivalent load across reports; no throughput correction is applied.")

    # Paired confidence intervals qualify whether a directional product effect
    # is repeatable. Interpret the sign using each metric's product objective.
    if all(name in header_index for name in ("metric", "mean", "low", "high")):
        benefits = []
        regressions = []
        changed = []
        uncertain = []
        controls = []
        for row in rows:
            low = _table_number(row[header_index["low"]])
            high = _table_number(row[header_index["high"]])
            if low is None or high is None:
                continue
            name = str(row[header_index["metric"]])
            if "read" in header_index:
                name = f"{row[header_index['read']]} {name}"
            preference = _ci_metric_preference(name)
            if low <= 0 <= high:
                uncertain.append(name)
                continue
            direction = "positive" if low > 0 else "negative"
            if preference == "control":
                controls.append(f"{name} changed {direction}")
            elif preference == "higher":
                (benefits if low > 0 else regressions).append(name)
            elif preference == "lower":
                (benefits if high < 0 else regressions).append(name)
            else:
                changed.append(f"{name} {direction}")
        if benefits or regressions or changed or uncertain or controls:
            parts = ["Project evidence from 95% intervals"]
            if benefits:
                parts.append("benefits: " + ", ".join(benefits))
            if regressions:
                parts.append("regressions: " + ", ".join(regressions))
            if controls:
                parts.append("control drift: " + ", ".join(controls))
            if changed:
                parts.append("other repeatable changes: " + ", ".join(changed))
            if uncertain:
                parts.append("overlap zero for " + ", ".join(uncertain))
            return "; ".join(parts) + "."

    # The primary loaded table answers the product question first: does swapz
    # beat raw useful service while reducing lower-device work and preserving
    # READ service? Sync remains a scheduling control, not the product baseline.
    if ("mode" in header_index and "W" in header_index and
            "off" in {str(row[header_index["mode"]]) for row in rows} and
            "async" in {str(row[header_index["mode"]]) for row in rows}):
        by_mode = {str(row[header_index["mode"]]): row for row in rows}
        raw_w = _table_number(by_mode["off"][header_index["W"]])
        async_w = _table_number(by_mode["async"][header_index["W"]])
        sync_w = (_table_number(by_mode["sync"][header_index["W"]])
                  if "sync" in by_mode else None)
        if raw_w is not None and async_w is not None and raw_w:
            write_change = _percent_change(async_w, raw_w)
            changes = [(write_change, False)]
            details = [
                f"Async useful WRITE throughput is {async_w:.2f} MB/s, "
                f"{write_change * 100:+.1f}% versus raw"
            ]
            if sync_w:
                details.append(f"{_percent_change(async_w, sync_w) * 100:+.1f}% versus sync")

            if "lower W" in header_index:
                raw_lower = _table_number(by_mode["off"][header_index["lower W"]])
                async_lower = _table_number(by_mode["async"][header_index["lower W"]])
                if raw_lower is not None and async_lower is not None and raw_lower:
                    raw_bytes_per_useful = raw_lower / raw_w
                    async_bytes_per_useful = async_lower / async_w
                    change = _percent_change(async_bytes_per_useful,
                                             raw_bytes_per_useful)
                    changes.append((change, True))
                    details.append("backing WRITE bytes/useful byte "
                                   f"{change * 100:+.1f}% vs raw")

            if "W req" in header_index:
                raw_req = _table_number(by_mode["off"][header_index["W req"]])
                async_req = _table_number(by_mode["async"][header_index["W req"]])
                change = _percent_change(async_req, raw_req)
                if change is not None:
                    changes.append((change, True))
                    details.append(f"lower WRITE requests {change * 100:+.1f}% vs raw")

            for column, label, lower_is_better in (
                    ("R", "mixed READ throughput", False),
                    ("R p99", "mixed READ p99", True)):
                if column not in header_index:
                    continue
                raw_value = _table_number(by_mode["off"][header_index[column]])
                async_value = _table_number(by_mode["async"][header_index[column]])
                change = _percent_change(async_value, raw_value)
                if change is not None:
                    changes.append((change, lower_is_better))
                    details.append(f"{label} {change * 100:+.1f}% vs raw")

            state = _directional_project_state(changes)
            return (f"Directional project view vs raw: {state}. " +
                    "; ".join(details) +
                    ". Reduced lower-WRITE bytes per useful byte supports I/O efficiency and the "
                    "host-write endurance proxy; it is not physical NAND lifetime proof. "
                    "Higher useful throughput and lower p99 support performance. Mean values "
                    "only; paired intervals decide qualification.")

    # Internal A/Bs are useful only if their direction serves product goals.
    # Confidence and qualification remain in the paired interval table.
    if "merge" in header_index:
        by_merge = {str(row[header_index["merge"]]): row for row in rows}
        if "0" in by_merge and "1" in by_merge:
            summaries = []
            project_changes = []
            for column in ("seq MB/s", "seq req", "seq p99",
                           "rnd MB/s", "rnd req", "rnd p99"):
                if column not in header_index:
                    continue
                before = _table_number(by_merge["0"][header_index[column]])
                after = _table_number(by_merge["1"][header_index[column]])
                change = _percent_change(after, before)
                if change is None:
                    continue
                lower_is_better = "req" in column or "p99" in column
                project_changes.append((change, lower_is_better))
                summaries.append(f"{column} {change * 100:+.1f}%")
            if summaries:
                state = _directional_project_state(project_changes)
                return ("Merge-on means versus merge-off: " + ", ".join(summaries) +
                        f". Directional project view: {state}; fewer requests/lower p99 "
                        "and higher useful MB/s are helpful. Use the paired interval "
                        "below for repeatable evidence.")

    if all(name in header_index for name in ("QD", "raw", "async", "A/raw")):
        comparisons = []
        changes = []
        for row in rows:
            raw_value = _table_number(row[header_index["raw"]])
            async_value = _table_number(row[header_index["async"]])
            change = _percent_change(async_value, raw_value)
            if change is None:
                continue
            changes.append((change, False))
            comparisons.append(f"QD{row[header_index['QD']]} {change * 100:+.1f}%")
        if comparisons:
            state = _directional_project_state(changes)
            return (f"Directional performance view vs raw: {state}. "
                    "Async useful WRITE changes: " + ", ".join(comparisons) +
                    ". Native/raw service direction is not a paired confidence result. "
                    "Check lower WRITE bytes/requests, p99, READ service and resource "
                    "cost before treating higher throughput as a project win.")
    if all(name in header_index for name in ("QD", "raw", "sync", "async", "A/S")):
        comparisons = []
        project_changes = []
        for row in rows:
            raw_value = _table_number(row[header_index["raw"]])
            async_value = _table_number(row[header_index["async"]])
            change = _percent_change(async_value, raw_value)
            if change is not None:
                project_changes.append((change, False))
                comparisons.append(f"QD{row[header_index['QD']]} {change * 100:+.1f}%")
        if comparisons:
            state = _directional_project_state(project_changes)
            return (f"Directional performance view vs raw: {state}. Async swapz useful "
                    "WRITE throughput change: " + ", ".join(comparisons) +
                    ". A/S only measures preparation scheduling versus sync; it cannot "
                    "turn a swapz result that still trails raw into a product win. "
                    "This table does not contain raw lower-byte/request totals, so it "
                    "does not by itself establish endurance benefit.")
    if "check" in header_index and "result" in header_index and rows:
        outcomes = [str(row[header_index["result"]]).upper() for row in rows]
        terminal_statuses = {"PASS", "FAIL", "BLOCKED", "INCOMPLETE", "NOT_RUN"}
        if set(outcomes) <= terminal_statuses:
            counts = {status: outcomes.count(status)
                      for status in terminal_statuses if status in outcomes}
            return (f"{len(outcomes)} checks have terminal results: " +
                    ", ".join(f"{count} {status}" for status, count in counts.items()) +
                    ".")
        descriptions = list(dict.fromkeys(
            outcome.replace("_", " ").lower() for outcome in outcomes))
        shown = ", ".join(descriptions[:3])
        suffix = "; additional outcomes are listed" if len(descriptions) > 3 else ""
        return (f"{len(outcomes)} criteria are summarized by these outcomes: {shown}{suffix}. "
                "Read each criterion separately; the rows do not form one overall verdict.")

    # Compare the experiment's outcome, rather than an identifier, input size
    # or threshold. These are native/offline observations unless titled loaded.
    if "transform" in header_index and "adopt" in header_index and rows:
        adopted = _table_number(rows[0][header_index["adopt"]])
        raw = _table_number(rows[0][header_index["RAW+"]])
        blocks = _table_number(rows[0][header_index["blocks"]])
        extents = _table_number(rows[0][header_index["extents"]])
        if None not in (adopted, raw, blocks, extents):
            return (f"Native candidate adopted on {adopted:g} pages, including {raw:g} "
                    f"RAW rescues; the planner saves {blocks:g} blocks and "
                    f"{extents:g} extents on this corpus. Neither result "
                    "establishes loaded-device savings.")
    if "accel" in header_index and "ns/page" in header_index and rows:
        timings = [(_table_number(row[header_index["ns/page"]]), row)
                   for row in rows]
        timings = [(value, row) for value, row in timings if value is not None]
        if timings:
            fastest = min(timings, key=lambda item: item[0])
            slowest = max(timings, key=lambda item: item[0])
            difference = ((1 - fastest[0] / slowest[0]) * 100
                          if slowest[0] else 0)
            return (f"Acceleration {fastest[1][header_index['accel']]} has the "
                    f"lowest native compression time ({fastest[0]:g} ns/page; "
                    f"{difference:.1f}% below the slowest setting). "
                    "Compare accepted payload bytes and planner blocks as well; "
                    "native timing alone does not establish loaded throughput.")
    if "backend" in header_index and "xform ns" in header_index and rows:
        fastest = min(rows, key=lambda row:
                      _table_number(row[header_index["xform ns"]]) or float("inf"))
        inverse = min(rows, key=lambda row:
                      _table_number(row[header_index["inv ns"]]) or float("inf"))
        return (f"Fastest native forward: {fastest[0]} "
                f"({fastest[header_index['xform ns']]} ns/page); fastest inverse: "
                f"{inverse[0]} ({inverse[header_index['inv ns']]} ns/page). "
                "These are separate measurements, not a loaded speedup.")
    if "baseline ns/page" in header_index and "2x ns/page" in header_index and rows:
        differences = []
        for row in rows:
            baseline = _table_number(row[header_index["baseline ns/page"]])
            unrolled = _table_number(row[header_index["2x ns/page"]])
            if baseline and unrolled is not None:
                differences.append(100 * (unrolled / baseline - 1))
        if differences:
            return (f"The 2x forward candidate is faster in "
                    f"{sum(change < 0 for change in differences)}/{len(differences)} "
                    f"same-host pairs; mean paired change "
                    f"{statistics.mean(differences):+.1f}%. "
                    "Use the separately reported paired 95% interval for inference.")
    if "control" in header_index and "minimum" in header_index and rows:
        margins = []
        for row in rows:
            score = _table_number(row[header_index["score"]])
            minimum = _table_number(row[header_index["minimum"]])
            if score is not None and minimum is not None:
                margins.append((str(row[0]), score - minimum))
        if margins:
            failed = [name for name, margin in margins if margin < 0]
            return (f"{len(margins) - len(failed)}/{len(margins)} classifier "
                    "blind-spot controls meet their minimum scores"
                    + (f"; failures: {', '.join(failed)}." if failed else
                       f"; narrowest margin {min(margins, key=lambda x: x[1])[1]:g} points."))
    if "neg call/eligible" in header_index and "struct useful" in header_index:
        safe = [row for row in rows if row[header_index["neg call/eligible"]]
                .startswith("0/")]
        if safe:
            best = max(safe, key=lambda row:
                       _table_number(row[header_index["struct useful"]]) or 0)
            return (f"Among thresholds with zero negative calls, score "
                    f"{best[header_index['score']]} retains "
                    f"{best[header_index['struct useful']]} useful structured "
                    "calls. Lower thresholds route more negative pages; this "
                    "corpus does not establish loaded savings.")
    if "score" in header_index and "blocks" in header_index and "extents" in header_index:
        best = max(rows, key=lambda row:
                   _table_number(row[header_index["blocks"]]) or 0)
        return (f"Threshold {best[header_index['score']]} yields the most "
                f"modeled planner block savings ({best[header_index['blocks']]} "
                f"blocks, {best[header_index['extents']]} extents). "
                "More savings can require more classification/transform work.")
    if "old ms" in header_index and "map ms" in header_index and rows:
        ratios = []
        for row in rows:
            old = _table_number(row[header_index["old ms"]])
            mapping = _table_number(row[header_index["map ms"]])
            if old and mapping is not None:
                ratios.append(old / mapping if mapping else float("inf"))
        if ratios:
            return (f"Mapping scan versus legacy scan: "
                    f"{min(ratios):.1f}–{max(ratios):.1f}x less elapsed time "
                    "across tested sizes; selection and survivor-list costs "
                    "are separate. Native CPU benchmark, not loaded GC I/O.")
    if "old probe ms" in header_index and "mapped probe ms" in header_index and rows:
        ratios = []
        for row in rows:
            old = _table_number(row[header_index["old probe ms"]])
            mapped = _table_number(row[header_index["mapped probe ms"]])
            if old is not None and mapped:
                ratios.append(old / mapped)
        if ratios:
            return (f"Mapped-count probing takes "
                    f"{min(ratios):.1f}–{max(ratios):.1f}x less elapsed time "
                    "than legacy probing at tested sizes (rounded timings); "
                    "native CPU only, not lower-device I/O.")
    if "geometry" in header_index and "W runs" in header_index and rows:
        fewest = min(rows, key=lambda row:
                     _table_number(row[header_index["W runs"]]) or float("inf"))
        return (f"{fewest[0]} has the fewest modeled contiguous WRITE runs "
                f"({fewest[header_index['W runs']]}). Check wasted blocks, "
                "cold READ blocks and sequential READ requests before choosing "
                "a placement policy; this is an offline simulation.")
    if "resident-dup" in header_index and "uniq payloads" in header_index and rows:
        row = rows[0]
        return (f"The trace contains {row[header_index['uniq payloads']]} distinct "
                f"payloads across {row[header_index['writes']]} writes; "
                f"{row[header_index['resident-dup']]} writes match a resident "
                "value. Duplicate-content potential is not an implemented "
                "deduplication or a measured lower-I/O saving.")
    if "blocks saved" in header_index and "modeled ns/page" in header_index and rows:
        row = rows[0]
        return (f"Native planner saves {row[header_index['blocks saved']]} blocks "
                f"and {row[header_index['extents saved']]} extents, with modeled "
                f"{row[header_index['modeled ns/page']]} ns/page write cost. "
                "Modeled elapsed cost is not worker CPU or loaded performance.")

    # Fallback: prefer a directional measurement over identifiers or workload
    # sizes. Never treat a descriptive maximum as automatically preferable.
    metric_index = None
    values = []
    prioritized = [index for index, name in enumerate(headers)
                   if index and name in TABLE_HEADER_GOAL]
    for index in prioritized + [index for index in range(1, len(headers))
                                if index not in prioritized]:
        parsed = [(_table_number(row[index]), str(row[0])) for row in rows]
        parsed = [(value, label) for value, label in parsed if value is not None]
        if parsed:
            metric_index = index
            values = parsed
            break
    if values:
        low = min(values, key=lambda item: item[0])
        high = max(values, key=lambda item: item[0])
        metric = str(headers[metric_index])
        if len(rows) == 1:
            return (f"{metric}={low[0]:g} in this single observation. "
                    "No across-setting comparison or performance claim is possible.")
        if low[0] == high[0]:
            return f"{metric} is {low[0]:g} across {len(rows)} rows; no difference is visible."
        direction = TABLE_HEADER_GOAL.get(metric)
        return (f"{metric}: {low[0]:g} ({low[1]}) to {high[0]:g} "
                f"({high[1]}). " +
                (f"Preference: {direction}; verify other outcomes and scope."
                 if direction else "Descriptive range, not a performance verdict."))

    if not rows:
        return "No rows were reported."
    return (f"{len(rows)} named status or scope rows are listed; read each value as "
            "a check result or evidence limit.")


def _table_mean_comparison_state(headers, rows, key, baseline, candidate, metrics):
    """Classify a two-setting means table using only product-facing metrics."""
    header_index = {str(header): index for index, header in enumerate(headers)}
    if key not in header_index:
        return None, []
    by_setting = {str(row[header_index[key]]): row for row in rows}
    if baseline not in by_setting or candidate not in by_setting:
        return None, []
    changes = []
    details = []
    for column, label, lower_is_better in metrics:
        if column not in header_index:
            continue
        before = _table_number(by_setting[baseline][header_index[column]])
        after = _table_number(by_setting[candidate][header_index[column]])
        change = _percent_change(after, before)
        if change is None:
            continue
        changes.append((change, lower_is_better))
        details.append(f"{label} {change * 100:+.1f}%")
    return (_directional_project_state(changes) if changes else None), details


def _table_project_reasoning(title, headers, rows, interpretation):
    """Connect each table to the project decision chain without overclaiming."""
    lower_title = title.lower()
    header_index = {str(header): index for index, header in enumerate(headers)}

    if not rows:
        return ("Evidence: no rows were reported -> Goal implication: there is no evidence "
                "for correctness, useful service, lower I/O or resource cost -> "
                "Verdict: INCOMPLETE.")

    if lower_title.startswith("loaded correctness, lifecycle"):
        return ("Evidence: this table is emitted only after loaded correctness, GC, reclaim, "
                "fault-injection and teardown qualification passes -> Goal implication: "
                "performance evidence is admissible only because byte-exact/fail-closed "
                "behavior held; segment-open spread is logical allocator fairness -> "
                "Verdict: CORRECTNESS ALIGNED, while physical-media endurance remains unproven.")

    if lower_title.startswith("qualification scope and evidence limitations"):
        return ("Evidence: qualification is RAM-backed and the listed scope limits still "
                "apply -> Goal implication: lower-WRITE bytes/requests are a host-I/O "
                "endurance proxy and logical segment-open spread is allocator fairness, "
                "not NAND P/E evidence -> Verdict: CLAIM BOUNDARY; do not promote physical "
                "wear or real-swap conclusions from this run.")

    if "mixed-i/o qualification criteria" in lower_title:
        return ("Evidence: the rows separately summarize swapz-vs-raw service, async-vs-sync "
                "mechanism, lower-WRITE savings and packed READ service -> Goal implication: "
                "a project win needs correctness plus useful service and lower-device work; "
                "async-vs-sync alone cannot establish that -> Verdict: GATE SUMMARY; read all "
                "criteria together rather than collapsing them into one mechanism result.")

    directional = re.search(
        r"Directional (?:project|performance) view(?: vs raw)?: "
        r"(ALIGNED|TRADE-OFF|NOT ALIGNED|NEUTRAL)",
        interpretation)
    if directional:
        state = directional.group(1)
        if all(name in header_index for name in ("read", "lower KiB", "req", "p99")):
            implication = (
                "lower READ bytes/requests and acceptable READ latency improve swap-in "
                "efficiency/performance; READ traffic alone is not the write-endurance proxy")
        elif all(name in header_index for name in ("mode", "W", "lower W", "W req")):
            implication = (
                "useful WRITE/READ service and lower-WRITE work jointly test performance "
                "and the host-write endurance proxy")
        elif "merge" in header_index or "fanout" in header_index:
            implication = (
                "higher useful READ service with fewer lower READ requests/lower p99 is "
                "aligned with swap-in performance and I/O efficiency")
        else:
            implication = (
                "higher useful service is favorable, but lower-WRITE bytes/requests must "
                "be shown separately before claiming the endurance proxy")
        if state == "ALIGNED":
            conclusion = "the measured mean directions support the relevant project goals"
        elif state == "TRADE-OFF":
            conclusion = "some project metrics improve while others regress, so there is no unqualified win"
        elif state == "NOT ALIGNED":
            conclusion = "the measured direction does not satisfy the project goal in this table"
        else:
            conclusion = "no directional project change is visible in this table"
        return (f"Evidence: {state} mean direction -> Goal implication: {implication} -> "
                f"Verdict: {state}; {conclusion}. Paired evidence still decides repeatability.")

    if all(name in header_index for name in ("metric", "mean", "low", "high")):
        if "raw-control" in lower_title:
            stable = []
            drift = []
            for row in rows:
                low = _table_number(row[header_index["low"]])
                high = _table_number(row[header_index["high"]])
                if low is None or high is None:
                    continue
                name = str(row[header_index["metric"]])
                (stable if low <= 0 <= high else drift).append(name)
            if drift:
                return ("Evidence: raw-control confidence intervals exclude zero for " +
                        ", ".join(drift) +
                        " -> Goal implication: background/host drift can confound the feature "
                        "comparison -> Verdict: CONTROL DRIFT; do not attribute the paired "
                        "difference solely to swapz.")
            return ("Evidence: raw-control confidence intervals overlap zero" +
                    (f" for {', '.join(stable)}" if stable else "") +
                    " -> Goal implication: no repeatable raw-control drift is established -> "
                    "Verdict: CONTROL STABLE for the measured metrics.")

        benefits = []
        regressions = []
        uncertain = []
        classified = 0
        for row in rows:
            low = _table_number(row[header_index["low"]])
            high = _table_number(row[header_index["high"]])
            if low is None or high is None:
                continue
            name = str(row[header_index["metric"]])
            if "read" in header_index:
                name = f"{row[header_index['read']]} {name}"
            preference = _ci_metric_preference(name)
            if preference not in ("higher", "lower"):
                continue
            classified += 1
            if low <= 0 <= high:
                uncertain.append(name)
            elif ((preference == "higher" and low > 0) or
                  (preference == "lower" and high < 0)):
                benefits.append(name)
            else:
                regressions.append(name)
        if classified:
            if benefits and regressions:
                verdict = "TRADE-OFF"
            elif regressions:
                verdict = "NOT ALIGNED"
            elif benefits and uncertain:
                verdict = "PARTIALLY ALIGNED"
            elif benefits:
                verdict = "ALIGNED"
            else:
                verdict = "INCONCLUSIVE"
            evidence = []
            if benefits:
                evidence.append("favorable: " + ", ".join(benefits))
            if regressions:
                evidence.append("regressing: " + ", ".join(regressions))
            if uncertain:
                evidence.append("CI overlaps zero: " + ", ".join(uncertain))
            return ("Evidence: " + "; ".join(evidence) +
                    " -> Goal implication: only repeatable favorable changes in useful "
                    "service, latency or lower I/O support an optimization; zero-overlap "
                    "metrics remain undecided -> Verdict: " + verdict + ".")
        return ("Evidence: these confidence intervals cover internal attribution rather "
                "than a project-facing service/lower-I/O metric -> Goal implication: they "
                "can explain a mechanism but cannot qualify an optimization -> "
                "Verdict: DIAGNOSTIC ONLY.")

    comparisons = (
        ("loaded lz4 acceleration means", "accel", "1", "4",
         (("swap W", "useful WRITE", False), ("p99", "WRITE p99", True),
          ("lower KiB", "lower WRITE bytes", True), ("lower req", "lower WRITE requests", True)),
         "acceleration=4 versus production acceleration=1"),
        ("delta64 rescue means", "rescue", "0", "1",
         (("W MB/s", "useful WRITE", False), ("p99", "WRITE p99", True),
          ("lower req", "lower WRITE requests", True)),
         "rescue on versus off"),
        ("delta64 preparation means", "K", "1", "2",
         (("W MB/s", "useful WRITE", False), ("p99", "WRITE p99", True),
          ("lower req", "lower WRITE requests", True)),
         "K=2 versus K=1"),
        ("independent read fan-out means", "fanout", "0", "1",
         (("W", "mixed WRITE", False), ("R", "mixed READ", False),
          ("R p99", "READ p99", True), ("R req", "lower READ requests", True)),
         "fan-out on versus off"),
        ("bounded lower-write depth means", "depth", "1", "2",
         (("W MB/s", "useful WRITE", False), ("p99", "WRITE p99", True),
          ("lower req", "lower WRITE requests", True)),
         "depth 2 versus depth 1"),
    )
    for marker, key, baseline, candidate, metrics, label in comparisons:
        if marker not in lower_title:
            continue
        state, details = _table_mean_comparison_state(
            headers, rows, key, baseline, candidate, metrics)
        if state is None:
            break
        return (f"Evidence: {label}: " + ", ".join(details) +
                f" -> Goal implication: useful service should rise while latency and lower "
                f"I/O stay flat or improve; lower WRITE work is the host-write endurance "
                f"proxy when present -> Verdict: {state} on means; the paired confidence "
                f"interval table decides promotion.")

    if "host cpu and load context" in lower_title:
        return ("Evidence: host CPU/PSI includes swapz, replay and unrelated background work "
                "-> Goal implication: CPU pressure must remain acceptable, but this table "
                "cannot attribute cost to swapz or prove an I/O win -> Verdict: RESOURCE "
                "CONTEXT ONLY; use product-facing service/lower-I/O tables for the decision.")

    if ("native" in lower_title or "simulated" in lower_title or
            "trace workload" in lower_title):
        return ("Evidence: this is native/offline/model evidence rather than loaded swapz "
                "service -> Goal implication: it can identify compression, packing, CPU or "
                "allocator opportunity, but cannot prove useful READ/WRITE performance or "
                "lower-device traffic -> Verdict: SUPPORTING ONLY; require loaded "
                "byte-exact evidence before changing production policy.")

    if "synthetic lower-device model limits" in lower_title:
        return ("Evidence: the table describes the synthetic device ceiling and raw control "
                "throughput -> Goal implication: it explains whether latency or bandwidth "
                "limits the experiment, not whether swapz is better -> Verdict: MODEL "
                "CONTEXT ONLY.")

    diagnostic_markers = (
        "general attempt counters", "packing-path activity",
        "classifier score distribution", "payload savings and rescue wall time",
        "engine wall-time attribution", "metadata-cache locality",
        "lower-queue and k=1 run-slot occupancy", "retained-window size",
        "pack_ready close causes", "burst-close site", "post-pack tail",
        "burst-target shrink", "async pipeline wall-time attribution",
        "asynchronous-preparation scheduling signals",
        "asynchronous-preparation activity", "retained-window geometry",
        "merged-range read accounting", "reasons eligible adjacent reads",
        "merged-range read attribution",
    )
    if any(marker in lower_title for marker in diagnostic_markers):
        return ("Evidence: this table describes an internal mechanism or bottleneck -> "
                "Goal implication: it can explain why a product-facing result moved, but "
                "without its own raw/off useful-service and lower-I/O comparison it cannot "
                "establish a performance or endurance-proxy win -> Verdict: DIAGNOSTIC ONLY.")

    if "check" in header_index and "result" in header_index:
        return ("Evidence: the table reports explicit check outcomes -> Goal implication: "
                "failed or blocked correctness/safety checks invalidate performance claims; "
                "passing component checks make later performance evidence admissible -> "
                "Verdict: CHECK SUMMARY; use the named outcomes rather than inferring a "
                "different optimization result.")

    if any(name in TABLE_HEADER_GOAL for name in headers):
        return ("Evidence: the Legend states the preferred direction for the measured "
                "metrics -> Goal implication: a favorable component matters only when "
                "correctness holds and no material opposing service/lower-I/O metric "
                "regresses -> Verdict: COMPONENT EVIDENCE; combine it with the nearest "
                "product-facing table before changing swapz.")

    return ("Evidence: this table is descriptive/status evidence -> Goal implication: it "
            "does not directly compare useful service and lower-device work against the "
            "appropriate control -> Verdict: CONTEXT ONLY; no optimization claim follows "
            "from this table alone.")


def print_table(title, headers, rows):
    """Print a GFM table plus evidence, goal implication, and decision chain."""
    text_headers = [str(header) for header in headers]
    text_rows = [[str(value) for value in row] for row in rows]
    # GFM requires at least three dashes after an alignment colon. Keep
    # the terminal divider exactly as wide as the data column by making four
    # characters the minimum printable column width.
    widths = [
        max(4, len(text_headers[index]),
            *(len(row[index]) for row in text_rows))
        for index in range(len(headers))
    ]
    print(f"\n**{title}**")
    print("| " + " | ".join(
        f"{header:<{widths[index]}}"
        for index, header in enumerate(text_headers)) + " |")
    print("| " + " | ".join(
        ":" + "-" * (width - 1) for width in widths) + " |")
    for row in text_rows:
        print("| " + " | ".join(
            f"{value:<{widths[index]}}"
            for index, value in enumerate(row)) + " |")
    # Define each column once; omit repetitive context-dependent boilerplate.
    legend = "; ".join(
        f"{header}: {TABLE_HEADER_LEGEND.get(header, 'reported ' + header)}" +
        (f" [{TABLE_HEADER_GOAL[header]}]" if header in TABLE_HEADER_GOAL else "")
        for header in text_headers)
    _print_table_note("Legend", legend)
    interpretation = _table_interpretation(text_headers, text_rows)
    _print_table_note("Interpretation", interpretation)
    _print_table_note(
        "Project reasoning",
        _table_project_reasoning(title, text_headers, text_rows, interpretation))
    print("---")


def print_bench(result, *, detailed=False):
    """Show the decision first; retain detailed rendering for rootless contract fixtures."""
    benchmarks = result.get("benchmarks", {})
    verdict = benchmarks.get("verdicts", {})
    print("\n  Product decision snapshot — synthetic owned-RAM evidence only")
    if verdict.get("overall") != "PASS_BOUNDED_RAM_MATRIX":
        stages = result.get("stages", [])
        passed = sum(stage.get("status") == "PASS" for stage in stages)
        print(f"  Stages passed: {passed}/5; loaded service: NOT QUALIFIED")
        _print_table_note(
            "Gate", verdict.get("reason", verdict.get("overall", "NOT_RUN")))
        _print_table_note(
            "Goal implication",
            "No new byte-exact loaded mixed/QD comparison against raw is qualified. "
            "Do not infer a throughput, latency, lower-I/O or endurance-proxy win "
            "from native compression and allocator models.")
        evidence = result.get("evidence", {})
        present = [name for key, name in (
            ("predictor", "compression"),
            ("gc_scan_scale", "GC scans"),
            ("extent_geometry", "placement"))
            if isinstance(evidence.get(key), dict)]
        if present:
            print("  Native diagnostics captured: " + ", ".join(present) +
                  " (supporting only; full data in test_results.json).")
        return

    print("  Qualified mixed workload: useful READ/WRITE vs raw, lower WRITE work and READ p99.")
    print("  Both device profiles are synthetic null_blk; sync isolates scheduling only.")
    for regime in MODEL_ORDER:
        data = verdict["regimes"][regime]
        columns = data["columns"]
        label = "Serial-depth" if regime == "sd_emulated" else "Fast"
        print_table(
            f"{label} QD32 mixed-I/O service and lower WRITE cost",
            ("mode", "W", "lower W", "W req", "R", "R p99"),
            [(mode,
              f"{columns[mode]['input_write_mbps']:.2f}",
              f"{columns[mode]['output_lower_write_mbps']:.2f}",
              f"{columns[mode]['lower_write_requests']:.1f}",
              f"{columns[mode]['swap_in_read_mbps']:.2f}",
              f"{columns[mode]['swap_in_read_p99_ms']:.2f}")
             for mode in COLUMNS])
        raw, asynchronous = columns["off"], columns["async"]
        direction = _directional_project_state((
            (_percent_change(asynchronous["input_write_mbps"],
                             raw["input_write_mbps"]), False),
            (_percent_change(asynchronous["swap_in_read_mbps"],
                             raw["swap_in_read_mbps"]), False),
            (_percent_change(asynchronous["output_lower_write_mbps"],
                             raw["output_lower_write_mbps"]), True),
            (_percent_change(asynchronous["lower_write_requests"],
                             raw["lower_write_requests"]), True),
            (_percent_change(asynchronous["swap_in_read_p99_ms"],
                             raw["swap_in_read_p99_ms"]), True),
        ))
        print(f"  {label} vs raw: {direction} mean directions; not a paired confidence verdict.")
        counters = data["kernel_counters"]
        def counter_ms(field):
            value = counters.get(field)
            return (f"{value / 1_000_000:.1f}"
                    if isinstance(value, (int, float)) else "N/A")
        print(f"  {label} accepted-work lower-idle: "
              f"{counter_ms('accepted_work_lower_idle_ns')} ms; "
              f"undersized batches: "
              f"{counter_ms('accepted_work_lower_idle_undersized_batch_ns')} ms")
        print(f"  {label} preparing-head idle: "
              f"{counter_ms('accepted_work_lower_idle_preparing_head_ns')} ms; "
              f"K=1 ready-run wait: {counter_ms('k1_ready_wait_wall_ns')} ms")
        if regime == "ssd_emulated":
            interval = data["criteria"]["async_vs_sync"]["paired_95pct_ci"]
            status = ("overlaps zero" if interval["low"] <= 0 <= interval["high"]
                      else "excludes zero")
            print(f"  Fast mixed async-minus-sync WRITE 95% paired CI: "
                  f"{interval['mean'] * 100:+.1f}% "
                  f"[{interval['low'] * 100:+.1f}%, "
                  f"{interval['high'] * 100:+.1f}%]; {status}.")
            print("  Async-vs-sync measures scheduling; raw remains the product control.")

    saturation = benchmarks.get("write_saturation", {})
    if saturation.get("overall") == "PASS_WRITE_SATURATION_EVIDENCE":
        print("\n  Sustained lane-owned WRITE — MB/s, raw is the product control")
        for regime in MODEL_ORDER:
            label = "Serial-depth" if regime == "sd_emulated" else "Fast"
            points = {point["qd"]: point for point in saturation["regimes"][regime]
                      if point["mode"] == "async"}
            print_table(
                f"{label} sustained-QD useful WRITE throughput",
                ("QD", "raw", "async", "A/raw"),
                [(qd, f"{points[qd]['raw_write_mbps']:.2f}",
                  f"{points[qd]['swapz_write_mbps']:.2f}",
                  f"{_percent_change(points[qd]['swapz_write_mbps'], points[qd]['raw_write_mbps']) * 100:+.1f}%")
                 for qd in (1, 4, 8, 32)])
        for qd in (4, 8, 32):
            interval = saturation[f"fast_qd{qd}_paired"]["throughput_change_fraction"]
            status = ("overlaps zero" if interval["low"] <= 0 <= interval["high"]
                      else "excludes zero")
            print(f"  Fast QD{qd} async-minus-sync paired 95% CI: "
                  f"{interval['mean'] * 100:+.1f}% "
                  f"[{interval['low'] * 100:+.1f}%, "
                  f"{interval['high'] * 100:+.1f}%]; {status}.")
        print("  QD1 and the raw gaps are directional; paired CIs above compare async vs sync.")
    else:
        _print_table_note(
            "Sustained QD", "NOT QUALIFIED: " +
            str(saturation.get("reason", saturation.get("overall", "NOT_RUN"))))

    lone_raw = benchmarks.get("lone_raw_qd1", {})
    if lone_raw.get("overall") == "PASS_LONE_RAW_QD1_CANDIDATE":
        row = lone_raw["row"]
        off, candidate = row["arms"]["off"], row["arms"]["swapz"]
        print("\n  Learned-singleton RAW (ID161) — default-off QD1 candidate")
        print_table(
            "Fast QD1 candidate; one directional owned-RAM pair",
            ("mode", "WRITE MB/s", "lower MB", "lower req", "WRITE p99 ms"),
            [
                ("raw", f"{off['logical_write_mbps']:.2f}",
                 f"{off['lower_write_bytes'] / 1_000_000:.3f}",
                 off["lower_write_requests"], f"{off['write_p99_ms']:.3f}"),
                ("lone-RAW", f"{candidate['logical_write_mbps']:.2f}",
                 f"{candidate['lower_write_bytes'] / 1_000_000:.3f}",
                 candidate["lower_write_requests"],
                 f"{candidate['write_p99_ms']:.3f}"),
            ])
        print(f"  Useful WRITE vs raw: "
              f"{(lone_raw['swapz_to_raw_write_ratio'] - 1) * 100:+.1f}%; "
              f"lower bytes ratio={lone_raw['lower_write_bytes_ratio']:.3f}; "
              f"lower requests ratio={lone_raw['lower_write_requests_ratio']:.3f}.")
        activity = row["activity"]
        print("  Candidate activity: "
              f"selected={activity['selected']} cancelled={activity['cancelled']} "
              f"zero-elided={activity['zero_elided']} "
              f"multi-record windows/pages="
              f"{activity['multi_record_windows']}/{activity['multi_record_pages']}.")
        print("  Directional correctness/telemetry evidence only; default remains off.")
    else:
        _print_table_note(
            "Lone-RAW QD1 (ID161)", "NOT QUALIFIED: " +
            str(lone_raw.get("reason", lone_raw.get("overall", "NOT_RUN"))))
    print("  Resource, lifecycle, GC, lower READ and full telemetry: test_results.json.")
    if result.get("overall") not in (None, "PASS"):
        print(f"  Overall gate remains {result['overall']}; partial performance is not promotion.")
    if not detailed:
        return

    print("\n  Project decision rule")
    _print_table_note(
        "Goal chain",
        "Correctness/fail-closed behavior must hold -> compare the same useful workload "
        "against the proper control -> prefer higher useful READ/WRITE and acceptable "
        "latency with fewer lower-device bytes/requests -> accept only with bounded "
        "CPU, RAM and GC cost.")
    _print_table_note(
        "Endurance scope",
        "Lower WRITE bytes/requests are the host-I/O endurance proxy. Circular segment "
        "opening should avoid pathological logical allocator concentration, but logical "
        "open spread is not NAND P/E or physical wear-leveling evidence.")
    predictor = result.get("evidence", {}).get("predictor")
    if isinstance(predictor, dict):
        print("\n  Predictive-compression screening — native corpus; not loaded attribution")
        print_table(
            "Predictive transform compression and planner savings — native corpus",
            ("transform", "adopt", "RAW+", "<=2024", "blocks", "extents",
             "xform ns", "inv ns", "LZ4 ns"),
            [(
                row["name"],
                row["adopted"],
                row["raw_rescued"],
                row["cliff_2024"],
                f"{row['planner_blocks_saved']:+d}",
                f"{row['planner_extents_saved']:+d}",
                row["transform_ns_per_page"],
                row["inverse_ns_per_page"],
                row["second_lz4_ns_per_page"],
            ) for row in predictor["transforms"]])
        transform = predictor["transforms"][0]
        classifier = predictor["classifier"]
        print_table(
            "Ordinary LZ4 acceleration CPU and planner geometry — native corpus",
            ("accel", "ns/page", "payload B", "RAW", "blocks", "extents"),
            [(
                row["acceleration"], row["wall_ns_per_page"],
                row["accepted_payload_bytes"], row["raw_pages"],
                row["planner_blocks"], row["planner_extents"],
            ) for row in predictor["lz4_acceleration_sweep"]])
        print("  Delta64 selected backends — "
              f"transform={transform['transform_backend']} "
              f"inverse={transform['inverse_backend']}; classifier=scalar")
        print_table(
            "Delta64 backend transform and inverse timing — native corpus",
            ("backend", "xform ns", "inv ns"),
            [(row["name"], row["transform_ns_per_page"],
              row["inverse_ns_per_page"])
             for row in predictor["backend_benchmarks"]])
        sse2_ab = predictor["sse2_forward_ab"]
        if sse2_ab is not None:
            paired = sse2_ab["pairs"]
            ci = paired_ci95([
                row["unrolled_ns_per_page"] / row["baseline_ns_per_page"] - 1.0
                for row in paired
            ])
            print_table(
                "SSE2 forward 2x production vs legacy baseline — native same-host corpus",
                ("pair", "order", "baseline ns/page", "2x ns/page"),
                [(index + 1, row["order"], row["baseline_ns_per_page"],
                  row["unrolled_ns_per_page"])
                 for index, row in enumerate(paired)])
            print("  SSE2 2x minus baseline paired 95% CI "
                  f"(n={ci['n']}, {sse2_ab['repeats_per_arm']} repeats/arm): "
                  f"{ci['mean'] * 100:+.1f}% "
                  f"[{ci['low'] * 100:+.1f}%, {ci['high'] * 100:+.1f}%]")
            print("  Native same-host regression evidence for the promoted SSE2 production loop.")
        print("  Sampled delta64 classifier — scalar; "
              f"{classifier['stage1_pairs']} -> {classifier['sample_pairs']} pairs; "
              f"{classifier['ns_per_page']} ns/eligible page")
        print("  Stage-1 aborts: "
              f"{classifier['early_abort_pages']}/{classifier['eligible_pages']}; "
              f"timing: {classifier['benchmark_repeats']} batched repeats")
        print_table(
            "Delta64 classifier sampling regressions — native controls",
            ("control", "score", "minimum"),
            [(row["name"], row["score"], row["minimum_score"])
             for row in predictor["sampling_controls"]])
        print_table(
            "Delta64 classifier routing quality by score threshold — native corpus",
            ("score", "neg call/eligible", "neg useful", "struct call/eligible",
             "struct useful"),
            [(
                row["threshold"],
                f"{row['negative_calls']}/{row['negative_eligible']}",
                row["negative_useful"],
                f"{row['structured_calls']}/{row['structured_eligible']}",
                row["structured_useful"],
            ) for row in predictor["thresholds"]])
        print("  Routed delta64 planner savings")
        print_table(
            "Delta64 planner block and extent savings by score threshold — native corpus",
            ("score", "blocks", "extents"),
            [(row["threshold"], f"{row['routed_blocks_saved']:+d}",
              f"{row['routed_extents_saved']:+d}")
             for row in predictor["thresholds"]])
        io_ns = predictor["io_model_block_ns"]
        print("  Routed delta64 CPU economics — elapsed-time model")
        print_table(
            "Delta64 modeled CPU cost versus I/O opportunity — native corpus",
            ("score", "cpu/page ns", "ns/saved block", "SD x", "SSD x"),
            [(row["threshold"], row["routed_cpu_ns_per_page"],
              row["ns_per_saved_block"],
              f"{io_ns['sd_emulated'] / row['ns_per_saved_block']:.1f}"
              if row["ns_per_saved_block"] else "-",
              f"{io_ns['ssd_emulated'] / row['ns_per_saved_block']:.2f}"
              if row["ns_per_saved_block"] else "-")
             for row in predictor["thresholds"]])
        print("  Negative classifier profile breakdown")
        print_table(
            "Delta64 negative-control classifier calls by profile — native corpus",
            ("score", "profile", "call/eligible", "useful"),
            [(row["threshold"], profile["name"],
              f"{profile['calls']}/{profile['eligible']}",
              profile["useful"])
             for row in predictor["thresholds"]
             for profile in row["negative_profiles"]])
        route = predictor["production_route"]
        print("  Exact hybrid production route — native-only model; no loaded I/O proof")
        print_table(
            "Delta64 shared production-route screening decisions — native corpus",
            ("eligible", "pack eligible", "passed", "attempts",
             "adopt", "RAW+", "LZ4+", "pack+"),
            [(route["eligible_pages"], route["packing_eligible_pages"],
              route["classifier_passes"], route["candidate_attempts"],
              route["adopted_pages"], route["raw_rescues"],
              route["lz4_rescues"], route["packing_adoptions"])])
        print_table(
            "Delta64 shared production-route savings and CPU model — native corpus",
            ("payload bytes", "blocks saved", "extents saved",
             "modeled ns/page", "ns/saved block"),
            [(route["payload_bytes_saved"], f"{route['blocks_saved']:+d}",
              f"{route['extents_saved']:+d}",
              route["modeled_wall_ns_per_page"],
              route["ns_per_saved_block"])])

    gc_scale = result.get("evidence", {}).get("gc_scan_scale")
    if isinstance(gc_scale, dict):
        print("\n  Garbage-collection map-scan scaling — native CPU only; no lower I/O")
        print_table(
            "Garbage-collection victim and relocation scan scaling — native CPU",
            ("pages", "segs", "old ms", "select ms", "map ms", "list ms"),
            [(
                row["logical_pages"], row["segments"],
                f"{row['legacy_score_scan_ns'] / 1e6:.3f}",
                f"{row['incremental_select_ns'] / 1e6:.3f}",
                f"{row['relocation_scan_ns'] / 1e6:.3f}",
                f"{row['relocation_list_ns'] / 1e6:.3f}",
            ) for row in gc_scale["rows"]])
        print("  Dead-segment allocator-probe scaling — native CPU only; no lower I/O")
        print_table(
            "Dead-segment allocator probe scaling — native CPU",
            ("logical pages", "segments", "old probe ms", "mapped probe ms"),
            [(
                row["logical_pages"], row["segments"],
                f"{row['legacy_dead_probe_ns'] / 1e6:.3f}",
                f"{row['mapped_dead_probe_ns'] / 1e6:.3f}",
            ) for row in gc_scale["rows"]])

    geometry = result.get("evidence", {}).get("extent_geometry")
    if isinstance(geometry, dict):
        print("\n  Simulated extent geometry — offline model; no format policy")
        print_table(
            "Simulated extent placement geometry and estimated I/O",
            ("geometry", "blocks", "waste", "W runs", "cold R blk", "seq req"),
            [(
                row["name"], row["physical_blocks"], row["waste_blocks"],
                row["write_runs"],
                f"{row['cold_read_blocks_x1000'] / 1000:.2f}",
                row["seq_4m_requests"],
            ) for row in geometry["rows"]])

    verdict = result["benchmarks"]["verdicts"]
    if verdict.get("overall") != "PASS_BOUNDED_RAM_MATRIX":
        print("  Benchmark matrix: NOT QUALIFIED "
              f"({verdict.get('reason', verdict.get('overall', 'NOT_RUN'))})")
        return

    opportunity = verdict.get("workload_opportunity")
    if isinstance(opportunity, dict):
        print("\n  Workload content opportunity — trace/fixture only; not kernel savings.")
        print_table(
            "Trace workload duplicate-content opportunity",
            ("writes", "same-filled", "same-page", "resident-dup", "uniq payloads"),
            [(
                opportunity["measured_write_ops"],
                opportunity["nonzero_same_filled_write_ops"],
                opportunity["same_page_rewrite_ops"],
                opportunity["resident_duplicate_write_ops"],
                opportunity["measured_unique_write_payloads"],
            )])
        print("  Final live: "
              f"{opportunity['final_live_unique_payloads']} unique payloads; "
              f"{opportunity['final_live_duplicate_pages']} pages in duplicate sets; "
              f"{opportunity['final_live_nonzero_same_filled_pages']} nonzero same-filled.")

    for regime in MODEL_ORDER:
        data = verdict["regimes"][regime]
        columns = data["columns"]
        cfg = data["device_model"]
        asynchronous = columns["async"]
        prep = data["preparation_counters"]
        counters = data["kernel_counters"]
        model_label = "Serial-depth" if regime == "sd_emulated" else "Fast"

        print(f"\n  {regime.upper()} QD32 mixed — synthetic RAM model "
              f"{cfg['cap_mib_s']} MiB/s, {cfg['completion_nsec']} ns, "
              f"hwq={cfg['hw_queue_depth']}")
        print("  Throughput MB/s; p99 ms. Sync stays as the scheduling control.")
        print_table(
            f"{model_label} QD32 mixed I/O throughput and latency",
            ("mode", "W", "lower W", "W req", "R", "R p99"),
            [
                (mode,
                 f"{columns[mode]['input_write_mbps']:.2f}",
                 f"{columns[mode]['output_lower_write_mbps']:.2f}",
                 f"{columns[mode]['lower_write_requests']:.1f}",
                 f"{columns[mode]['swap_in_read_mbps']:.2f}",
                 f"{columns[mode]['swap_in_read_p99_ms']:.2f}")
                for mode in COLUMNS
            ])

        print("  Host CPU during mixed I/O — phase-boundary counters; background load included")
        cpu_rows = []
        def cpu_number(value, scale=1):
            return "N/A" if value is None else f"{value * scale:.1f}"
        for mode in COLUMNS:
            arm = columns[mode]
            host = arm["host_cpu"]
            replay_user = arm["mixed_replay_cpu_user_s"]
            replay_system = arm["mixed_replay_cpu_system_s"]
            replay_cores = ((replay_user + replay_system) / arm["seconds"]
                            if replay_user is not None and replay_system is not None
                            and arm["seconds"] else None)
            cpus = (f"{host['online_cpus']:g}/{host['affinity_cpus']:g}"
                    if host["online_cpus"] is not None and host["affinity_cpus"] is not None
                    else "N/A")
            cpu_rows.append((mode, cpu_number(host["busy_fraction"], 100),
                             cpu_number(host["pressure_some_fraction"], 100),
                             cpu_number(host["steal_fraction"], 100),
                             cpu_number(replay_cores), cpus,
                             f"{host['observations']}/{host['expected_observations']}"))
        print_table(
            f"{model_label} mixed-I/O host CPU and load context",
            ("mode", "host busy %", "CPU wait %", "steal %",
                     "replay cores", "CPUs", "CPU n"), cpu_rows)

        print("  Production delta64 during mixed I/O — mean foreground attempt counters")
        print_table(
            f"{model_label} mixed-I/O delta64 general attempt counters",
            ("mode", "rescue", "eligible", "passed", "attempts", "adopted",
             "direct", "LZ4-1 skip", "RAW+", "LZ4+"),
            [(mode, {0: "off", 1: "on"}.get(columns[mode]['mixed_delta64_rescue'], "mixed"),
              *(f"{columns[mode]['mixed_' + field]:.1f}" for field in (
                "delta64_eligible", "delta64_classifier_pass", "delta64_attempts",
                "delta64_adopted", "delta64_direct_adopted",
                "delta64_first_lz4_skipped",
                "delta64_raw_rescues", "delta64_lz4_rescues")))
             for mode in ("sync", "async")])
        print_table(
            f"{model_label} mixed-I/O delta64 packing-path activity",
            ("mode", "pack eligible", "pack try", "cliff", "pack+"),
            [(mode, *(f"{columns[mode]['mixed_' + field]:.1f}" for field in (
                "delta64_pack_eligible", "delta64_pack_attempts",
                "delta64_pack_cliff_crossings", "delta64_pack_adopted")))
             for mode in ("sync", "async")])
        print_table(
            f"{model_label} mixed-I/O delta64 classifier score distribution",
            ("mode", "score 0-7", "8-15", "16-23", "24+"),
            [(mode, *(f"{columns[mode]['mixed_' + field]:.1f}" for field in (
                "delta64_score_0_7", "delta64_score_8_15",
                "delta64_score_16_23", "delta64_score_ge24")))
             for mode in ("sync", "async")])
        print_table(
            f"{model_label} mixed-I/O delta64 payload savings and rescue wall time",
            ("mode", "payload KiB", "RAW+ KiB", "LZ4+ KiB", "rescue ms"),
            [(mode, *(f"{columns[mode]['mixed_' + field] / 1024:.3f}" for field in (
                "delta64_payload_bytes_saved", "delta64_raw_payload_bytes_saved",
                "delta64_lz4_payload_bytes_saved")),
              f"{columns[mode]['mixed_delta64_wall_ns'] / 1e6:.3f}")
             for mode in ("sync", "async")])

        print("  Verified 4MiB packed reads — detailed cache counters remain in JSON.")
        read_rows = []
        for label, read_mode in (("seq", "sequential"),
                                 ("rnd", "seeded_random")):
            for mode in ("off", "async"):
                read_rows.append((
                    f"{label}-{mode}",
                    f"{columns[mode][f'{read_mode}_lower_read_bytes'] / 1024:.0f}",
                    f"{columns[mode][f'{read_mode}_lower_read_requests']:.1f}",
                    f"{columns[mode][f'{read_mode}_read_p99_ms']:.2f}",
                ))
        print_table(
            f"{model_label} verified 4 MiB packed-READ backing I/O and p99 latency",
            ("read", "lower KiB", "req", "p99"), read_rows)
        print("  Packed-read C attribution — wall ms; engine excludes lower READ.")
        print_table(
            f"{model_label} packed-READ engine wall-time attribution",
            ("read", "lower", "engine", "LZ4", "copy"),
            [
                (label,
                 f"{asynchronous[f'{mode}_lower_read_wall_ns'] / 1e6:.1f}",
                 f"{asynchronous[f'{mode}_read_engine_nonio_wall_ns'] / 1e6:.1f}",
                 f"{asynchronous[f'{mode}_decode_wall_ns'] / 1e6:.1f}",
                 f"{asynchronous[f'{mode}_read_copy_wall_ns'] / 1e6:.1f}")
                for label, mode in (("seq", "sequential"),
                                    ("rnd", "seeded_random"))
            ])

        print("  Metadata-cache locality — async arm; two choices in 128 sets x 4 ways.")
        locality_rows = []
        for label, mode in (("seq", "sequential"), ("rnd", "seeded_random")):
            lookups = asynchronous[f"{mode}_read_meta_set_lookups"]
            hits = asynchronous[f"{mode}_read_meta_set_hits"]
            probes = asynchronous[f"{mode}_read_meta_set_probes"]
            primary = asynchronous[f"{mode}_read_meta_primary_hits"]
            secondary = asynchronous[f"{mode}_read_meta_secondary_hits"]
            locality_rows.append((
                label,
                f"{lookups:.1f}",
                f"{(100.0 * hits / lookups) if lookups else 0.0:.1f}",
                f"{(100.0 * primary / lookups) if lookups else 0.0:.1f}",
                f"{(100.0 * secondary / lookups) if lookups else 0.0:.1f}",
                f"{(probes / lookups) if lookups else 0.0:.2f}",
                f"{asynchronous[f'{mode}_read_meta_set_replacements']:.1f}",
                f"{asynchronous[f'{mode}_read_meta_copy_bytes'] / 1024:.1f}",
            ))
        print_table(
            f"{model_label} packed-READ metadata-cache locality — async arm",
            ("read", "lookups", "set hit %", "primary %", "secondary %", "probes/lookup",
                     "repl", "meta copy KiB"), locality_rows)

        print("  Lower queue — sampled time-weighted mean / peak during mixed I/O.")
        print_table(
            f"{model_label} mixed-I/O lower-queue and K=1 run-slot occupancy",
            ("mode", "bdev R", "bdev W", "K=1 run slot"),
            [
                (mode,
                 f"{columns[mode]['lower_inflight_read_time_weighted']:.2f}/"
                 f"{columns[mode]['lower_inflight_read_peak']:.1f}",
                 f"{columns[mode]['lower_inflight_write_time_weighted']:.2f}/"
                 f"{columns[mode]['lower_inflight_write_peak']:.1f}",
                 ("-" if mode == "off" else
                  f"{columns[mode]['mixed_pipeline_active_mean']:.2f}/"
                  f"{columns[mode]['mixed_pipeline_active_peak']:.0f}"))
                for mode in COLUMNS
            ])
        print("  Mixed window bins; close=P/D/I")
        print_table(
            f"{model_label} mixed-I/O retained-window size and close reasons",
            ("mode", "1", "2", "3-4", "5-8", "9-16", "17-64", "P/D/I"),
            [
                (mode,
                 f"{columns[mode]['mixed_win1']:.1f}",
                 f"{columns[mode]['mixed_win2']:.1f}",
                 f"{columns[mode]['mixed_win3_4']:.1f}",
                 f"{columns[mode]['mixed_win5_8']:.1f}",
                 f"{columns[mode]['mixed_win9_16']:.1f}",
                 f"{columns[mode]['mixed_win17_64']:.1f}",
                 f"{columns[mode]['mixed_close_pack_ready']:.1f}/"
                 f"{columns[mode]['mixed_close_deadline']:.1f}/"
                 f"{columns[mode]['mixed_close_idle']:.1f}")
                for mode in ("sync", "async")
            ])
        print("  Mixed PACK_READY causes")
        pack_fields = (
            "pack_close_tail_target_le4", "pack_close_tail_target",
            "pack_close_burst_target", "pack_close_service_dry")
        print_table(
            f"{model_label} mixed-I/O PACK_READY close causes",
            ("mode", "tail<=4", "tail", "burst", "dry"),
            [
                (mode, *(f"{columns[mode][f'mixed_{field}']:.1f}"
                         for field in pack_fields))
                for mode in ("sync", "async")
            ] + [
                ("async-sync",
                 *(f"{columns['async'][f'mixed_{field}'] - columns['sync'][f'mixed_{field}']:+.1f}"
                   for field in pack_fields))
            ])
        print("  Mixed exact sampled-tail close attribution")
        print_table(
            f"{model_label} mixed-I/O exact sampled-tail PACK_READY attribution",
            ("mode", "t2/3/4"),
            [(mode, "/".join(
                f"{columns[mode][f'mixed_pack_close_tail_target_{target}']:.1f}"
                for target in (2, 3, 4))) for mode in ("sync", "async")])
        print("  Mixed burst-close split")
        burst_fields = (
            "pack_close_burst_admission", "pack_close_burst_worker",
            "pack_close_burst_target_le4", "pack_close_burst_target_5_8",
            "pack_close_burst_target_9_16", "pack_close_burst_target_17_64",
            "pack_close_burst_count_le4", "pack_close_burst_count_5_8",
            "pack_close_burst_count_9_16", "pack_close_burst_count_17_64",
            "pack_close_burst_overshoot")
        print_table(
            f"{model_label} mixed-I/O burst-close site and geometry attribution",
            ("mode", "adm/wrk", "t<=4/5-8/9-16/17+", "c<=4/5-8/9-16/17+", "over"),
            [
                (mode,
                 f"{columns[mode]['mixed_pack_close_burst_admission']:.1f}/"
                 f"{columns[mode]['mixed_pack_close_burst_worker']:.1f}",
                 "/".join(f"{columns[mode][f'mixed_{field}']:.1f}"
                          for field in burst_fields[2:6]),
                 "/".join(f"{columns[mode][f'mixed_{field}']:.1f}"
                          for field in burst_fields[6:10]),
                 f"{columns[mode]['mixed_pack_close_burst_overshoot']:.1f}")
                for mode in ("sync", "async")
            ] + [
                ("async-sync",
                 f"{columns['async']['mixed_pack_close_burst_admission'] - columns['sync']['mixed_pack_close_burst_admission']:+.1f}/"
                 f"{columns['async']['mixed_pack_close_burst_worker'] - columns['sync']['mixed_pack_close_burst_worker']:+.1f}",
                 "/".join(
                     f"{columns['async'][f'mixed_{field}'] - columns['sync'][f'mixed_{field}']:+.1f}"
                     for field in burst_fields[2:6]),
                 "/".join(
                     f"{columns['async'][f'mixed_{field}'] - columns['sync'][f'mixed_{field}']:+.1f}"
                     for field in burst_fields[6:10]),
                 f"{columns['async']['mixed_pack_close_burst_overshoot'] - columns['sync']['mixed_pack_close_burst_overshoot']:+.1f}")
            ])
        print("  Mixed post-PACK tail samples")
        tail_rows = []
        for mode in ("sync", "async"):
            tail_rows.append((
                mode,
                f"{columns[mode]['mixed_pack_tail_zero_inflight']:.1f}/"
                f"{columns[mode]['mixed_pack_tail_zero_idle']:.1f}",
                f"{columns[mode]['mixed_pack_tail_one_inflight']:.1f}/"
                f"{columns[mode]['mixed_pack_tail_one_idle']:.1f}",
                f"{columns[mode]['mixed_pack_tail_many_inflight']:.1f}/"
                f"{columns[mode]['mixed_pack_tail_many_idle']:.1f}",
                f"{columns[mode]['mixed_burst_target_grows']:.1f}/"
                f"{columns[mode]['mixed_burst_target_shrinks']:.1f}"))
        print_table(
            f"{model_label} mixed-I/O post-PACK tail samples",
            ("mode", "0 I/N", "1 I/N", "2+ I/N", "grow/shrink"),
                    tail_rows)
        print("  Mixed burst-target shrink attribution")
        shrink_rows = []
        shrink_fields = (
            "burst_shrink_inflight_zero_skips",
            "burst_shrink_after_inflight_zero",
            "burst_shrink_after_read_bypass",
            "burst_shrink_other",
            "burst_shrink_target_le8",
            "burst_shrink_target_9_32",
            "burst_shrink_target_gt32",
        )
        for mode in ("sync", "async"):
            shrink_rows.append((
                mode,
                *(f"{columns[mode][f'mixed_{field}']:.1f}"
                  for field in shrink_fields),
            ))
        shrink_rows.append((
            "async-sync",
            *(f"{columns['async'][f'mixed_{field}'] - columns['sync'][f'mixed_{field}']:+.1f}"
              for field in shrink_fields),
        ))
        print_table(
            f"{model_label} mixed-I/O burst-target shrink attribution",
            ("mode", "skip-I0", "after-I0", "after-read", "other",
                     "<=8", "9-32", ">32"), shrink_rows)
        if regime == "ssd_emulated":
            mixed_ab = data["criteria"]["async_vs_sync"]
            throughput_ci = mixed_ab["paired_95pct_ci"]
            requests_ci = mixed_ab[
                "lower_request_absolute_delta_paired_95pct_ci"]
            cause_ci = mixed_ab["pack_ready_cause_delta_paired_95pct_ci"]
            print("  Fast mixed async-sync paired 95% CI")
            ci_rows = [
                ("W %", throughput_ci["mean"] * 100,
                 throughput_ci["low"] * 100, throughput_ci["high"] * 100),
                ("lower req", requests_ci["mean"],
                 requests_ci["low"], requests_ci["high"]),
            ]
            ci_rows.extend(
                (label, cause_ci[field]["mean"],
                 cause_ci[field]["low"], cause_ci[field]["high"])
                for label, field in (
                    ("tail<=4", "pack_close_tail_target_le4"),
                    ("tail", "pack_close_tail_target"),
                    ("burst", "pack_close_burst_target"),
                    ("dry", "pack_close_service_dry")))
            print_table(
                "Fast mixed-I/O async-minus-sync paired 95% confidence intervals",
                ("metric", "mean", "low", "high"),
                [(label, f"{mean:+.1f}", f"{low:+.1f}", f"{high:+.1f}")
                 for label, mean, low, high in ci_rows])
            burst_ci = mixed_ab[
                "burst_close_detail_delta_paired_95pct_ci"]
            print("  Fast mixed burst-close async-sync paired 95% CI")
            burst_ci_rows = []
            for label, field in (
                    ("admission", "pack_close_burst_admission"),
                    ("worker", "pack_close_burst_worker"),
                    ("target<=4", "pack_close_burst_target_le4"),
                    ("target5-8", "pack_close_burst_target_5_8"),
                    ("target9-16", "pack_close_burst_target_9_16"),
                    ("target17+", "pack_close_burst_target_17_64"),
                    ("count<=4", "pack_close_burst_count_le4"),
                    ("count5-8", "pack_close_burst_count_5_8"),
                    ("count9-16", "pack_close_burst_count_9_16"),
                    ("count17+", "pack_close_burst_count_17_64"),
                    ("overshoot", "pack_close_burst_overshoot")):
                interval = burst_ci[field]
                burst_ci_rows.append((
                    label, f"{interval['mean']:+.1f}",
                    f"{interval['low']:+.1f}", f"{interval['high']:+.1f}"))
            print_table(
                "Fast mixed-I/O burst-close async-minus-sync paired 95% confidence intervals",
                ("metric", "mean", "low", "high"), burst_ci_rows)
        print("  Async pipeline — wall timings overlap; callback rows include scheduler delay.")
        print_table(
            f"{model_label} async pipeline wall-time attribution",
            ("stage", "busy ms", "overlap/stall ms"),
            [
                ("LZ4",
                 f"{asynchronous['mixed_lz4_wall_ns'] / 1e6:.1f}",
                 f"{asynchronous['mixed_prep_lower_write_overlap_ns'] / 1e6:.1f} W + "
                 f"{asynchronous['mixed_prep_lower_read_overlap_ns'] / 1e6:.1f} R overlap"),
                ("payload CRC prep",
                 f"{(asynchronous['mixed_prep_crc_wall_ns'] + asynchronous['mixed_ordered_crc_wall_ns']) / 1e6:.1f}",
                 f"{asynchronous['mixed_engine_prehashed_records']:.0f} packed"),
                ("RAM copies",
                 f"{asynchronous['mixed_write_copy_wall_ns'] / 1e6:.1f}",
                 f"{asynchronous['mixed_write_copy_bytes'] / 1048576:.1f} MiB"),
                ("commit non-I/O",
                 f"{asynchronous['mixed_window_commit_nonio_wall_ns'] / 1e6:.1f}", "-"),
                ("engine plan",
                 f"{asynchronous['mixed_engine_plan_wall_ns'] / 1e6:.1f}", "-"),
                ("engine pack",
                 f"{asynchronous['mixed_engine_pack_wall_ns'] / 1e6:.1f}", "-"),
                ("engine publish",
                 f"{asynchronous['mixed_engine_publish_wall_ns'] / 1e6:.1f}", "-"),
                ("publish CRC",
                 f"{asynchronous['mixed_engine_publish_crc_wall_ns'] / 1e6:.1f}", "-"),
                ("publish authority",
                 f"{asynchronous['mixed_engine_publish_auth_wall_ns'] / 1e6:.1f}", "-"),
                ("batch snapshot CRC",
                 f"{asynchronous['mixed_batch_snapshot_crc_wall_ns'] / 1e6:.1f}",
                 f"{asynchronous['mixed_batch_pause_crc_wall_ns'] / 1e6:.1f}/"
                 f"{asynchronous['mixed_batch_resume_crc_wall_ns'] / 1e6:.1f} pause/resume"),
                ("engine residual",
                 f"{max(0.0, asynchronous['mixed_window_commit_nonio_wall_ns'] - asynchronous['mixed_engine_plan_wall_ns'] - asynchronous['mixed_engine_pack_wall_ns'] - asynchronous['mixed_engine_publish_wall_ns'] - asynchronous['mixed_batch_pause_crc_wall_ns']) / 1e6:.1f}",
                 "after pause CRC"),
                ("lower WRITE",
                 f"{asynchronous['mixed_lower_write_wall_ns'] / 1e6:.1f}", "-"),
                ("ordered callback",
                 f"{asynchronous['mixed_ordered_worker_wall_ns'] / 1e6:.1f}",
                 f"{asynchronous['mixed_ordered_worker_cpu_ns'] / 1e6:.1f} sched sample"),
                ("ordered phase wall",
                 f"{(asynchronous['mixed_ordered_lz4_wall_ns'] + asynchronous['mixed_ordered_crc_wall_ns'] + asynchronous['mixed_ordered_write_copy_wall_ns'] + asynchronous['mixed_window_commit_nonio_wall_ns']) / 1e6:.1f}",
                 "partial wall; may be preempted"),
                ("prep callback",
                 f"{asynchronous['mixed_prep_worker_wall_ns'] / 1e6:.1f}",
                 f"{asynchronous['mixed_prep_worker_cpu_ns'] / 1e6:.1f} sched sample"),
                ("prep phase wall",
                 f"{(asynchronous['mixed_prep_lz4_wall_ns'] + asynchronous['mixed_prep_crc_wall_ns'] + asynchronous['mixed_prep_write_copy_wall_ns']) / 1e6:.1f}",
                 "partial wall; may be preempted"),
                ("read helper", "-",
                 f"{asynchronous['mixed_read_worker_cpu_ns'] / 1e6:.1f} sched sample"),
                ("scheduling", "-",
                 f"{asynchronous['mixed_prep_wait_wall_ns'] / 1e6:.2f} wait"),
            ])
        print_table(
            f"{model_label} asynchronous-preparation scheduling signals",
            ("async signal", "mean"),
            [
                ("direct LZ4 input",
                 f"{asynchronous['mixed_direct_lz4_input_pages']:.1f} pages"),
                ("mapped snapshot input",
                 f"{asynchronous['mixed_mapped_snapshot_input_pages']:.1f} pages"),
                ("wave kicks", f"{prep['prep_wave_kicks']:.1f}"),
                ("lower-WRITE prep starts",
                 f"{prep['prep_lower_write_overlap_starts']:.1f}"),
                ("lower-READ prep starts",
                 f"{prep['prep_lower_read_overlap_starts']:.1f}"),
                ("producer head/tail",
                 f"{prep['prep_producer_head_claims']:.1f}/"
                 f"{prep['prep_producer_tail_claims']:.1f}"),
                ("inline/handoff/wait",
                 f"{prep['prep_ordered_inline']:.1f}/"
                 f"{prep['prep_ordered_handoffs']:.1f}/"
                 f"{prep['prep_ordered_waits']:.1f}"),
                ("worker-empty deadlines",
                 f"{counters['deadline_worker_empty']:.1f}"),
                ("one-page pack/deadline",
                 f"{counters['win1_pack_ready']:.1f}/"
                 f"{counters['win1_deadline']:.1f}"),
                ("win1 pack T/R/W",
                 f"{counters['win1_pack_tail_target']:.1f}/"
                 f"{counters['win1_pack_read_bypass']:.1f}/"
                 f"{counters['win1_pack_wave_interrupted']:.1f}"),
                ("deferred tail D/C/DL/I/O",
                 f"{counters['single_tail_deferrals']:.1f}/"
                 f"{counters['single_tail_companions']:.1f}/"
                 f"{counters['win1_deadline_deferred_tail']:.1f}/"
                 f"{counters['win1_idle_deferred_tail']:.1f}/"
                 f"{counters['single_tail_other_clears']:.1f}"),
                ("deferred C age <=250/500/1000/>",
                 f"{counters['single_tail_comp_age_le250us']:.1f}/"
                 f"{counters['single_tail_comp_age_251_500us']:.1f}/"
                 f"{counters['single_tail_comp_age_501_1000us']:.1f}/"
                 f"{counters['single_tail_comp_age_gt1000us']:.1f}"),
                ("deferred C >1ms <=1.25/1.50/1.75/>",
                 f"{counters['single_tail_comp_age_1001_1250us']:.1f}/"
                 f"{counters['single_tail_comp_age_1251_1500us']:.1f}/"
                 f"{counters['single_tail_comp_age_1501_1750us']:.1f}/"
                 f"{counters['single_tail_comp_age_gt1750us']:.1f}"),
                ("deferred DL age <=250/500/1000/>",
                 f"{counters['single_tail_deadline_age_le250us']:.1f}/"
                 f"{counters['single_tail_deadline_age_251_500us']:.1f}/"
                 f"{counters['single_tail_deadline_age_501_1000us']:.1f}/"
                 f"{counters['single_tail_deadline_age_gt1000us']:.1f}"),
                ("deferred C service L/R/B",
                 f"{counters['single_tail_comp_after_lower_done']:.1f}/"
                 f"{counters['single_tail_comp_after_read_bypass']:.1f}/"
                 f"{counters['single_tail_comp_after_both']:.1f}"),
                ("deferred DL service L/R/B",
                 f"{counters['single_tail_deadline_after_lower_done']:.1f}/"
                 f"{counters['single_tail_deadline_after_read_bypass']:.1f}/"
                 f"{counters['single_tail_deadline_after_both']:.1f}"),
                ("lower-W queue start/end",
                 f"{asynchronous['mixed_prep_lower_write_start_queued'] / max(1.0, asynchronous['mixed_prep_lower_write_samples']):.2f}/"
                 f"{asynchronous['mixed_prep_lower_write_end_queued'] / max(1.0, asynchronous['mixed_prep_lower_write_samples']):.2f}"),
                ("lower-W nonempty start/end",
                 f"{asynchronous['mixed_prep_lower_write_start_nonempty']:.1f}/"
                 f"{asynchronous['mixed_prep_lower_write_end_nonempty']:.1f}"),
                ("K=1 read-bypass detach skips",
                 f"{asynchronous['mixed_pipeline_read_bypass_skips']:.1f}"),
                ("accepted lower-idle events/ms",
                 f"{counters['accepted_work_lower_idle_events']:.1f}/"
                 f"{counters['accepted_work_lower_idle_ns'] / 1e6:.2f}"),
                ("idle U/W/P/N ms",
                 f"{counters['accepted_work_lower_idle_undersized_batch_ns'] / 1e6:.2f}/"
                 f"{counters['accepted_work_lower_idle_worker_unscheduled_ns'] / 1e6:.2f}/"
                 f"{counters['accepted_work_lower_idle_preparing_head_ns'] / 1e6:.2f}/"
                 f"{counters['accepted_work_lower_idle_no_ready_work_ns'] / 1e6:.2f}"),
                ("accepted post-lower ms",
                 f"{counters['accepted_work_lower_idle_post_lower_ns'] / 1e6:.2f}"),
                ("K=1 ready wait win/records/ms",
                 f"{counters['k1_ready_wait_windows']:.1f}/"
                 f"{counters['k1_ready_wait_records']:.1f}/"
                 f"{counters['k1_ready_wait_wall_ns'] / 1e6:.2f}"),
                ("K=1 ready wait P/F/D/X/O",
                 f"{counters['k1_ready_wait_pack_ready']:.1f}/"
                 f"{counters['k1_ready_wait_full']:.1f}/"
                 f"{counters['k1_ready_wait_deadline']:.1f}/"
                 f"{counters['k1_ready_wait_fence']:.1f}/"
                 f"{counters['k1_ready_wait_other']:.1f}"),
                ("GC victims", f"{counters['gc_victims']:.1f}"),
            ])
        async_criteria = data["criteria"]["async"]
        print("  Verdict")
        print_table(
            f"{model_label} mixed-I/O qualification criteria",
            ("check", "result"),
            [
                ("async/raw W", async_criteria["throughput_vs_raw"]),
                ("async/sync W",
                 data["criteria"]["async_vs_sync"]["write_throughput"]),
                ("lower WRITE", async_criteria["lower_write_savings"]),
                ("packed read", async_criteria["packed_4mib_sequential"]),
            ])

    lz4_sweep = result["benchmarks"].get("lz4_acceleration", {})
    if lz4_sweep.get("overall") == "PASS_LZ4_ACCELERATION_AB":
        print("\n  LZ4 acceleration 1 vs 4 — five matched SSD-model rounds")
        rows = []
        for acceleration in ("1", "4"):
            mode = lz4_sweep["modes"][acceleration]
            rows.append((
                acceleration,
                f"{mode['swapz_write_mbps']:.2f}",
                f"{mode['swapz_write_p99_ms']:.2f}",
                f"{mode['lower_write_bytes'] / 1024:.1f}",
                f"{mode['lower_write_requests']:.1f}",
                f"{mode['lz4_wall_ns'] / 1e6:.2f}",
                f"{mode['host_pressure_some_fraction'] * 100:.1f}",
            ))
        print_table(
            "Loaded LZ4 acceleration means — SSD RAM model",
            ("accel", "swap W", "p99", "lower KiB", "lower req",
             "LZ4 ms", "PSI some %"), rows)
        print("  accel4-vs-1 paired 95% CI")
        ci_rows = []
        for label, field in (
                ("W %", "throughput_change_fraction"),
                ("p99 %", "p99_change_fraction"),
                ("lower B %", "lower_bytes_change_fraction"),
                ("lower req %", "lower_requests_change_fraction"),
                ("LZ4 wall %", "lz4_wall_change_fraction"),
                ("ordered LZ4 %", "ordered_lz4_wall_change_fraction"),
                ("prep LZ4 %", "prep_lz4_wall_change_fraction"),
                ("raw-control W %", "off_throughput_change_fraction")):
            ci = lz4_sweep["paired"][field]
            ci_rows.append((label, f"{ci['mean'] * 100:+.1f}",
                            f"{ci['low'] * 100:+.1f}",
                            f"{ci['high'] * 100:+.1f}"))
        print_table(
            "Acceleration 4 minus 1 paired 95% confidence intervals",
            ("metric", "mean", "low", "high"), ci_rows)
    else:
        print("\n  LZ4 acceleration 1/4 A/B: NOT QUALIFIED "
              f"({lz4_sweep.get('reason', lz4_sweep.get('overall', 'NOT_RUN'))})")

    delta64_rescue_ab = result["benchmarks"].get("delta64_rescue", {})
    if delta64_rescue_ab.get("overall") == "PASS_DELTA64_RESCUE_AB":
        print("\n  Delta64 rescue off vs on — five matched SSD-model K=1 rounds")
        rows = []
        for enabled in ("0", "1"):
            mode = delta64_rescue_ab["modes"][enabled]
            rows.append((
                enabled,
                f"{mode['write_mbps']:.2f}",
                f"{mode['write_p99_ms']:.2f}",
                f"{mode['lower_write_requests']:.1f}",
                f"{mode['delta64_attempts']:.1f}",
                f"{mode['delta64_adopted']:.1f}",
                f"{mode['delta64_direct_adopted']:.1f}",
                f"{mode['delta64_first_lz4_skipped']:.1f}",
                f"{mode['delta64_wall_ns'] / 1e6:.2f}",
            ))
        print_table(
            "Delta64 rescue means — positive fixture, fixed K=1",
            ("rescue", "W MB/s", "p99", "lower req", "attempts",
             "adopted", "direct", "LZ4-1 skip", "D64 ms"), rows)
        ci_rows = []
        for label, field in (
                ("W %", "throughput_change_fraction"),
                ("p99 %", "p99_change_fraction"),
                ("lower B %", "lower_bytes_change_fraction"),
                ("lower req %", "lower_requests_change_fraction"),
                ("raw-control W %", "off_throughput_change_fraction")):
            ci = delta64_rescue_ab["paired"][field]
            ci_rows.append((label, f"{ci['mean'] * 100:+.1f}",
                            f"{ci['low'] * 100:+.1f}",
                            f"{ci['high'] * 100:+.1f}"))
        print_table(
            "Rescue on minus off paired 95% confidence intervals",
            ("metric", "mean", "low", "high"), ci_rows)
    else:
        print("\n  Delta64 rescue off/on A/B: NOT QUALIFIED "
              f"({delta64_rescue_ab.get('reason', delta64_rescue_ab.get('overall', 'NOT_RUN'))})")

    delta64_ab = result["benchmarks"].get("delta64_prepare", {})
    if delta64_ab.get("overall") == "PASS_DELTA64_PREPARE_AB":
        print("\n  Delta64 preparation K=1 vs K=2 — five matched SSD-model rounds")
        rows = []
        for workers in ("1", "2"):
            mode = delta64_ab["modes"][workers]
            rows.append((
                workers,
                f"{mode['write_mbps']:.2f}",
                f"{mode['write_p99_ms']:.2f}",
                f"{mode['lower_write_requests']:.1f}",
                f"{mode['delta64_wall_ns'] / 1e6:.2f}",
                f"{mode['prep_lz4_wall_ns'] / 1e6:.2f}",
                f"{mode['prepare_parallel_starts']:.1f}",
                f"{mode['host_pressure_some_fraction'] * 100:.1f}",
            ))
        print_table(
            "Delta64 preparation means — positive fixture",
            ("K", "W MB/s", "p99", "lower req", "D64 ms",
             "prep LZ4 ms", "parallel", "PSI some %"), rows)
        ci_rows = []
        for label, field in (
                ("W %", "throughput_change_fraction"),
                ("p99 %", "p99_change_fraction"),
                ("lower B %", "lower_bytes_change_fraction"),
                ("lower req %", "lower_requests_change_fraction"),
                ("D64 wall %", "delta64_wall_change_fraction"),
                ("xform wall %", "transform_wall_change_fraction"),
                ("prep LZ4 %", "prep_lz4_wall_change_fraction"),
                ("prep CPU %", "prep_worker_cpu_change_fraction"),
                ("raw-control W %", "off_throughput_change_fraction")):
            ci = delta64_ab["paired"][field]
            ci_rows.append((label, f"{ci['mean'] * 100:+.1f}",
                            f"{ci['low'] * 100:+.1f}",
                            f"{ci['high'] * 100:+.1f}"))
        print_table(
            "K=2 minus K=1 paired 95% confidence intervals",
            ("metric", "mean", "low", "high"), ci_rows)
    elif delta64_ab.get("overall") != "NOT_RUN":
        print("\n  Delta64 K=1/K=2 diagnostic: NOT QUALIFIED "
              f"({delta64_ab.get('reason', delta64_ab.get('overall', 'NOT_RUN'))})")

    parallel_ab = result["benchmarks"].get("parallel_read_ab", {})
    if parallel_ab.get("overall") == "PASS_PARALLEL_READ_AB_EVIDENCE":
        print("\n  Independent lower-READ fan-out — final five matched fast-model rounds")
        rows = []
        for enabled in ("0", "1"):
            mixed = parallel_ab["modes"][enabled]["mixed"]
            rows.append((
                enabled,
                f"{mixed['write_mbps']:.2f}",
                f"{mixed['read_mbps']:.2f}",
                f"{mixed['read_p99_ms']:.2f}",
                f"{mixed['lower_read_requests']:.1f}",
                f"{mixed['async_batches']:.1f}/{mixed['async_slots']:.1f}",
            ))
        print_table(
            "Fast QD32 mixed independent READ fan-out means — ID63 off",
            ("fanout", "W", "R", "R p99", "R req", "batches/slots"), rows)

        ci_rows = []
        for label, ci in (
                ("mixed W MB/s", parallel_ab["paired"]["mixed"]["write_mbps"]),
                ("mixed R MB/s", parallel_ab["paired"]["mixed"]["read_mbps"]),
                ("mixed R p99", parallel_ab["paired"]["mixed"]["read_p99_ms"]),
                ("mixed lower B", parallel_ab["paired"]["mixed"]["lower_read_bytes"]),
                ("mixed lower req", parallel_ab["paired"]["mixed"]["lower_read_requests"]),
                ("seq R MB/s", parallel_ab["paired"]["packed"]["sequential"]["read_mbps"]),
                ("seq R p99", parallel_ab["paired"]["packed"]["sequential"]["read_p99_ms"]),
                ("seq lower req", parallel_ab["paired"]["packed"]["sequential"]["lower_read_requests"]),
                ("rnd R MB/s", parallel_ab["paired"]["packed"]["seeded_random"]["read_mbps"]),
                ("rnd R p99", parallel_ab["paired"]["packed"]["seeded_random"]["read_p99_ms"]),
                ("rnd lower req", parallel_ab["paired"]["packed"]["seeded_random"]["lower_read_requests"])):
            ci_rows.append((label, f"{ci['mean'] * 100:+.1f}",
                            f"{ci['low'] * 100:+.1f}",
                            f"{ci['high'] * 100:+.1f}"))
        print_table(
            "Fan-out on minus off paired 95% confidence intervals",
            ("metric", "mean", "low", "high"), ci_rows)
        raw_rows = []
        for label, key in (("raw W MB/s", "write_mbps"),
                           ("raw R MB/s", "read_mbps"),
                           ("raw R p99", "read_p99_ms")):
            ci = parallel_ab["raw_control_paired"][key]
            raw_rows.append((label, f"{ci['mean'] * 100:+.1f}",
                             f"{ci['low'] * 100:+.1f}",
                             f"{ci['high'] * 100:+.1f}"))
        print_table(
            "Fan-out experiment raw-control drift paired 95% intervals",
            ("metric", "mean", "low", "high"), raw_rows)
    elif parallel_ab.get("overall") == "NOT_RUN":
        print("\n  Independent lower-READ fan-out: PROMOTED; routine A/B retired")
    else:
        print("\n  Independent lower-READ fan-out historical diagnostic: NOT QUALIFIED "
              f"({parallel_ab.get('reason', parallel_ab.get('overall', 'NOT_RUN'))})")

    coalesce_ab = result["benchmarks"].get("read_coalesce_ab", {})
    if coalesce_ab.get("overall") == "PASS_READ_COALESCE_AB_CONFIRMATION":
        print("\n  Adjacent-range READ coalescing — five matched rounds")
        rows = []
        for enabled in ("0", "1"):
            seq = coalesce_ab["modes"][enabled]["sequential"]
            rnd = coalesce_ab["modes"][enabled]["seeded_random"]
            rows.append((
                enabled,
                f"{seq['useful_read_mbps']:.2f}",
                f"{seq['lower_read_requests']:.1f}",
                f"{seq['read_p99_ms']:.2f}",
                f"{rnd['useful_read_mbps']:.2f}",
                f"{rnd['lower_read_requests']:.1f}",
                f"{rnd['read_p99_ms']:.2f}",
                f"{seq['parallel_read_coalesced_reqs_saved']:.1f}",
                f"{rnd['parallel_read_coalesced_reqs_saved']:.1f}",
            ))
        print_table(
            "Fast-model adjacent-range READ coalescing means — five matched rounds",
            ("merge", "seq MB/s", "seq req", "seq p99", "rnd MB/s",
                     "rnd req", "rnd p99", "seq saved", "rnd saved"), rows)
        active = coalesce_ab["modes"]["1"]
        print("  Merged-range accounting")
        print_table(
            "Fast-model merged-range READ accounting — merge enabled",
            ("read", "dist", "adj", "merged", "blocks", "extra"),
            [
                ("seq",
                 f"{active['sequential']['parallel_read_distinct_extent_pairs']:.1f}",
                 f"{active['sequential']['parallel_read_adjacent_extent_pairs']:.1f}",
                 f"{active['sequential']['parallel_read_coalesced_pairs']:.1f}",
                 f"{active['sequential']['parallel_read_coalesced_blocks']:.1f}",
                 f"{active['sequential']['parallel_read_coalesce_extra_blocks']:.1f}"),
                ("rnd",
                 f"{active['seeded_random']['parallel_read_distinct_extent_pairs']:.1f}",
                 f"{active['seeded_random']['parallel_read_adjacent_extent_pairs']:.1f}",
                 f"{active['seeded_random']['parallel_read_coalesced_pairs']:.1f}",
                 f"{active['seeded_random']['parallel_read_coalesced_blocks']:.1f}",
                 f"{active['seeded_random']['parallel_read_coalesce_extra_blocks']:.1f}"),
            ])
        print("  Reasons adjacent READs were not merged")
        print_table(
            "Fast-model reasons eligible adjacent READs were not merged",
            ("read", "cached", "noncontig", "gap", "other"),
            [
                ("seq",
                 f"{active['sequential']['parallel_read_coalesce_skip_cached']:.1f}",
                 f"{active['sequential']['parallel_read_coalesce_skip_noncontig_slot']:.1f}",
                 f"{active['sequential']['parallel_read_coalesce_skip_gap']:.1f}",
                 f"{active['sequential']['parallel_read_coalesce_skip_other']:.1f}"),
                ("rnd",
                 f"{active['seeded_random']['parallel_read_coalesce_skip_cached']:.1f}",
                 f"{active['seeded_random']['parallel_read_coalesce_skip_noncontig_slot']:.1f}",
                 f"{active['seeded_random']['parallel_read_coalesce_skip_gap']:.1f}",
                 f"{active['seeded_random']['parallel_read_coalesce_skip_other']:.1f}"),
            ])
        throughput_ci = coalesce_ab["paired"]["sequential"][
            "throughput_change_fraction"]
        req_ci = coalesce_ab["paired"]["sequential"]["lower_requests_change_fraction"]
        p99_ci = coalesce_ab["paired"]["sequential"]["p99_change_fraction"]
        print("  seq on/off paired 95% CI: "
              f"MB/s {throughput_ci['mean'] * 100:+.1f}% "
              f"[{throughput_ci['low'] * 100:+.1f},{throughput_ci['high'] * 100:+.1f}]%; "
              f"req {req_ci['mean'] * 100:+.1f}% "
              f"[{req_ci['low'] * 100:+.1f},{req_ci['high'] * 100:+.1f}]%")
        print("    p99 "
              f"{p99_ci['mean'] * 100:+.1f}% "
              f"[{p99_ci['low'] * 100:+.1f},{p99_ci['high'] * 100:+.1f}]%")
    else:
        print("\n  Adjacent-range READ coalescing: NOT QUALIFIED "
              f"({coalesce_ab.get('reason', coalesce_ab.get('overall', 'NOT_RUN'))})")

    sd_coalesce_ab = result["benchmarks"].get("sd_read_coalesce_ab", {})
    if sd_coalesce_ab.get("overall") == "PASS_SD_READ_COALESCE_AB_CONFIRMATION":
        print("\n  Serial-depth adjacent-range READ coalescing — five matched rounds")
        rows = []
        for enabled in ("0", "1"):
            seq = sd_coalesce_ab["modes"][enabled]["sequential"]
            rnd = sd_coalesce_ab["modes"][enabled]["seeded_random"]
            rows.append((
                enabled,
                f"{seq['useful_read_mbps']:.2f}",
                f"{seq['lower_read_requests']:.1f}",
                f"{seq['read_p99_ms']:.2f}",
                f"{rnd['useful_read_mbps']:.2f}",
                f"{rnd['lower_read_requests']:.1f}",
                f"{rnd['read_p99_ms']:.2f}",
                f"{seq['parallel_read_coalesced_reqs_saved']:.1f}",
            ))
        print_table(
            "Serial-depth adjacent-range READ coalescing means — five matched rounds",
            ("merge", "seq MB/s", "seq req", "seq p99", "rnd MB/s",
                     "rnd req", "rnd p99", "seq saved"), rows)
        active = sd_coalesce_ab["modes"]["1"]
        print("  Serial-depth merged-range attribution")
        print_table(
            "Serial-depth merged-range READ attribution — merge enabled",
            ("read", "merged", "cached", "noncontig", "gap", "other"),
            [
                ("seq",
                 f"{active['sequential']['parallel_read_coalesced_pairs']:.1f}",
                 f"{active['sequential']['parallel_read_coalesce_skip_cached']:.1f}",
                 f"{active['sequential']['parallel_read_coalesce_skip_noncontig_slot']:.1f}",
                 f"{active['sequential']['parallel_read_coalesce_skip_gap']:.1f}",
                 f"{active['sequential']['parallel_read_coalesce_skip_other']:.1f}"),
                ("rnd",
                 f"{active['seeded_random']['parallel_read_coalesced_pairs']:.1f}",
                 f"{active['seeded_random']['parallel_read_coalesce_skip_cached']:.1f}",
                 f"{active['seeded_random']['parallel_read_coalesce_skip_noncontig_slot']:.1f}",
                 f"{active['seeded_random']['parallel_read_coalesce_skip_gap']:.1f}",
                 f"{active['seeded_random']['parallel_read_coalesce_skip_other']:.1f}"),
            ])
        ci_rows = []
        for label, mode in (("seq", "sequential"),
                            ("rnd", "seeded_random")):
            throughput = sd_coalesce_ab["paired"][mode][
                "throughput_change_fraction"]
            req = sd_coalesce_ab["paired"][mode][
                "lower_requests_change_fraction"]
            p99 = sd_coalesce_ab["paired"][mode]["p99_change_fraction"]
            ci_rows.extend((
                (label, "MB/s", f"{throughput['mean'] * 100:+.1f}%",
                 f"{throughput['low'] * 100:+.1f}%",
                 f"{throughput['high'] * 100:+.1f}%"),
                (label, "req", f"{req['mean'] * 100:+.1f}%",
                 f"{req['low'] * 100:+.1f}%", f"{req['high'] * 100:+.1f}%"),
                (label, "p99", f"{p99['mean'] * 100:+.1f}%",
                 f"{p99['low'] * 100:+.1f}%", f"{p99['high'] * 100:+.1f}%"),
            ))
        print_table(
            "Serial-depth READ coalescing paired 95% confidence intervals",
            ("read", "metric", "mean", "low", "high"), ci_rows)
    else:
        print("\n  Serial-depth adjacent-range READ coalescing: NOT QUALIFIED "
              f"({sd_coalesce_ab.get('reason', sd_coalesce_ab.get('overall', 'NOT_RUN'))})")

    loaded = result["benchmarks"].get("loaded_correctness", {})
    if loaded.get("overall") == "PASS":
        print("\n  Lifecycle")
        print_table(
            "Loaded correctness, lifecycle, GC, and reclaim checks",
            ("check", "result"),
            [
                ("RAW/zero pages",
                 f"{loaded['raw_pages']}/{loaded['zero_pages']}"),
                ("flushes", loaded["flush_calls"]),
                ("live GC",
                 f"{loaded['gc_victims']} victims / "
                 f"{loaded['gc_rotations']} rotations; "
                 f"{loaded['gc_verified_pages']} pages verified"),
                ("GC lower I/O",
                 f"R {loaded['gc_read_reqs']} / W {loaded['gc_write_reqs']} req"),
                ("GC victim spread",
                 f"{loaded['gc_distinct_victims']} distinct; "
                 f"{loaded['gc_victim_min_evictions']}/"
                 f"{loaded['gc_victim_max_evictions']} min/max"),
                ("segment TRIM",
                 f"{loaded['gc_segment_discards']} x 1MiB; "
                 f"{loaded['gc_segment_discard_sectors']} sectors; "
                 f"{loaded['segment_discards_skipped_already_trimmed']} duplicate skips"),
                ("placement waste",
                 f"FG {loaded['alignment_hole_blocks_foreground']} "
                 f"(tail {loaded['segment_tail_waste_blocks_foreground']}) / "
                 f"GC {loaded['alignment_hole_blocks_gc']} "
                 f"(tail {loaded['segment_tail_waste_blocks_gc']}); "
                 f"{loaded['run_splits_by_hole']} splits"),
                ("allocator probes",
                 f"{loaded['alloc_probe_segments']} segments / "
                 f"{loaded['alloc_probe_full_scans']} full scans; "
                 f"{loaded['alloc_probe_wall_ns'] / 1e6:.2f} ms"),
                ("segment opens",
                 f"{loaded['segment_program_min']}/"
                 f"{loaded['segment_program_sum'] / loaded['segment_program_segments']:.2f}/"
                 f"{loaded['segment_program_max']} min/mean/max"),
                ("upper DISCARD TRIM",
                 f"{loaded['discard_trim_immediate']} immediate; "
                 f"{loaded['discard_trim_reuse_skips']} reuse skips"),
                ("packed smoke",
                 f"{loaded['packed_placement_verified_pages']} pages; "
                 f"holes {loaded['packed_placement_holes']}; "
                 f"splits {loaded['packed_placement_run_splits']}"),
            ("GC pressure",
                 f"wall {loaded['gc_fraction_ppm'] / 10000:.2f}% useful-W; "
                 f"p99 {loaded['gc_baseline_p99_ns'] / 1e6:.2f}->"
                 f"{loaded['gc_pressure_p99_ns'] / 1e6:.2f} ms"),
            ("GC map/list",
                 f"choose-map {loaded['gc_choose_map_entries']} / "
                 f"relocate {loaded['gc_relocation_map_entries']} survivors; "
                 f"choose {loaded['gc_choose_wall_ns'] / 1e6:.2f} ms; "
                 f"no-headroom {loaded['gc_no_headroom_skips']}"),
                ("suspend/resume",
                 f"retain {loaded['suspend_retain_ms']} ms; "
                 f"{loaded['suspend_verified_pages']} pages verified"),
                ("fault injection", "retained WRITE/FLUSH failed closed"),
            ])

    print("\n  Limitations")
    print_table(
        "Qualification scope and evidence limitations",
        ("scope", "value"),
        [
            ("media", "synthetic RAM only; no physical-device evidence"),
            ("mixed CI", "fast: five matched pairs; slow: two observations per mode"),
            ("READ coalescing", "five pairs per model; fast-model p99 unresolved"),
            ("zero-tail shrink", "retired; compatibility fields stay fixed at zero"),
            ("write-only QD",
             "five pairs at fast QD4/8/32 and serial QD32; QD1 is directional"),
            ("CPU", "scheduler-update diagnostics and partial wall phases; no total CPU proof"),
            ("host load", "background apps included; idle-host control not established"),
            ("4MiB READ", "RAM-backed; not a cold physical swap-in"),
            ("GC", "RAM exercise only; physical wear is unproven"),
            ("Full telemetry", "test_results.json"),
        ])

    saturation = result["benchmarks"].get("write_saturation", {})
    if saturation.get("overall") == "PASS_WRITE_SATURATION_EVIDENCE":
        print("\n  DEVICE MODEL LIMITS — analytical; not a bulk calibration measurement")
        print("  null_blk cap is MiB/s; 4KiB ceiling = min(cap, 4096 * hwq / completion latency).")
        rows = []
        for regime in MODEL_ORDER:
            limits = saturation["model_limits"][regime]
            raw_qd32 = next(
                point["raw_write_mbps"]
                for point in saturation["regimes"][regime]
                if point["qd"] == 32 and point["mode"] == "async")
            rows.append((
                regime,
                f"{limits['cap_decimal_mbps']:.2f}",
                f"{limits['unmerged_4k_latency_ceiling_mbps']:.2f}",
                f"{limits['effective_4k_model_ceiling_mbps']:.2f}",
                f"{raw_qd32:.2f}",
            ))
        print_table(
            "Synthetic lower-device model limits and measured raw QD32 throughput",
            ("model", "cap MB/s", "4K latency MB/s",
                     "effective MB/s", "raw QD32 MB/s"), rows)

        print("\n  WRITE-ONLY SUSTAINED-QD EVIDENCE")
        print("  Persistent lane workers; logical WRITE MB/s, no timed per-I/O Future dispatch.")
        for regime in MODEL_ORDER:
            cfg = MODEL_SPECS[regime]
            model_label = "Serial-depth" if regime == "sd_emulated" else "Fast"
            points = saturation["regimes"][regime]
            by_qd = {}
            for point in points:
                by_qd.setdefault(point["qd"], {})[point["mode"]] = point

            print(f"\n  {regime.upper()} — {cfg['cap_mib_s']} MiB/s, "
                  f"{cfg['completion_nsec']} ns, hwq={cfg['hw_queue_depth']}")
            throughput_rows = []
            prep_rows = []
            window_rows = []
            for qd in (1, 4, 8, 32):
                sync = by_qd[qd]["sync"]
                asynchronous_point = by_qd[qd]["async"]
                gain = (asynchronous_point["swapz_write_mbps"] /
                        sync["swapz_write_mbps"] - 1.0) * 100.0
                throughput_rows.append((
                    qd,
                    f"{asynchronous_point['raw_write_mbps']:.2f}",
                    f"{sync['swapz_write_mbps']:.2f}",
                    f"{asynchronous_point['swapz_write_mbps']:.2f}",
                    f"{gain:+.1f}%",
                    f"{asynchronous_point['swapz_lower_write_requests']:.0f}",
                ))
                preparation = asynchronous_point["preparation_delta"]
                prep_rows.append((
                    qd,
                    preparation["prep_wave_kicks"],
                    f"{preparation['prep_producer_head_claims']}/"
                    f"{preparation['prep_producer_tail_claims']}",
                    preparation["prep_ordered_inline"],
                    f"{preparation['prep_ordered_handoffs']}/"
                    f"{preparation['prep_ordered_waits']}",
                ))
                windows = asynchronous_point["window_delta"]
                window_rows.append((
                    qd,
                    asynchronous_point["retained_burst_target"],
                    windows["win1"],
                    windows["win3_4"],
                    windows["win5_8"],
                    windows["win17_64"],
                    f"{windows['close_pack_ready']}/"
                    f"{windows['close_deadline']}/"
                    f"{windows['close_idle']}",
                ))
            print_table(
                f"{model_label} sustained-QD WRITE throughput and lower requests",
                ("QD", "raw", "sync", "async", "A/S", "A req"),
                        throughput_rows)
            print("  Async preparation")
            print_table(
                f"{model_label} sustained-QD asynchronous-preparation activity",
                ("QD", "wave", "head/tail", "inline", "hand/wait"),
                        prep_rows)
            print("  Async windows; close=P/D/I")
            print_table(
                f"{model_label} sustained-QD retained-window geometry and close reasons",
                ("QD", "target", "1", "3-4", "5-8", "17-64", "P/D/I"),
                        window_rows)
        serial_ci = saturation["serial_qd32_paired"][
            "throughput_change_fraction"]
        print("  Serial QD32 A/S paired 95% CI: "
              f"{serial_ci['mean'] * 100:+.1f}% "
              f"[{serial_ci['low'] * 100:+.1f},"
              f"{serial_ci['high'] * 100:+.1f}]%")
        for qd in (4, 8, 32):
            ci = saturation[f"fast_qd{qd}_paired"][
                "throughput_change_fraction"]
            print(f"  Fast QD{qd} A/S paired 95% CI: "
                  f"{ci['mean'] * 100:+.1f}% "
                  f"[{ci['low'] * 100:+.1f},{ci['high'] * 100:+.1f}]%")
        print("  QD1 remains a directional control.")
    else:
        print("\n  Write-only saturation evidence: NOT QUALIFIED "
              f"({saturation.get('reason', saturation.get('overall', 'NOT_RUN'))})")



    storage = result["benchmarks"].get("storage_envelopes", {})
    if storage.get("overall") == "PASS_DIRECTIONAL_STORAGE_ENVELOPES":
        print("\n  MODERN STORAGE SERVICE ENVELOPES — directional synthetic null_blk")
        print("  QD32 offered load; these are service envelopes, not measurements of physical media.")
        rows = []
        phase_rows = []
        for row in storage["rows"]:
            capture = row["bandwidth_opportunity_capture_fraction"]
            rows.append((
                row["envelope"],
                row["delta64_rescue"],
                row["replay_engine"],
                f"{row['byte_speedup']:.2f}x",
                f"{row['request_speedup']:.2f}x",
                f"{row['useful_write_speedup']:.2f}x",
                "n/a" if capture is None else f"{capture * 100:+.1f}%",
                row["swapz_write_depth_peak"],
                (f"{row['swapz_write_depth_mean']:.2f}"
                 if isinstance(row["swapz_write_depth_mean"], (int, float))
                 else "n/a"),
            ))
            def pct(name):
                value = row.get(name)
                return ("n/a" if value is None else f"{value * 100:.1f}%")
            phase_rows.append((
                row["envelope"],
                row["delta64_rescue"],
                pct("run_slot_active_fraction"),
                pct("post_lower_hold_fraction"),
                pct("k1_ready_wait_fraction"),
                pct("preparation_wait_fraction"),
                pct("commit_nonio_fraction"),
                pct("plan_fraction"),
                pct("pack_fraction"),
                pct("publish_fraction"),
                pct("publish_crc_fraction"),
            ))
        print_table(
            "Saved lower work versus useful WRITE service",
            ("model", "D64", "engine", "byte x", "req x", "useful x",
             "capture", "W peak", "W mean"), rows)
        print("  capture=(useful speedup-1)/(lower-WRITE byte speedup-1); "
              "low/negative values mean saved media work is not reaching useful service.")
        print_table(
            "Timed swapz WRITE-path occupancy versus replay wall",
            ("model", "D64", "slot active", "post-lower", "K1 ready wait",
             "prep wait", "commit nonio", "plan", "pack", "publish", "pub CRC"),
            phase_rows)
        print("  post-lower isolates callback-to-publication slot hold; K1 ready-wait isolates a ready window "
              "blocked by the single immutable lower-WRITE slot; prep wait isolates ordered-worker handoff "
              "starvation. Plan/pack/publish split serialized commit CPU.")
    else:
        print("\n  Modern storage service-envelope evidence: "
              f"{storage.get('overall', 'NOT_RUN')} "
              f"({storage.get('reason', 'directional sweep unavailable')})")


    write_depth = result["benchmarks"].get("write_pipeline_depth", {})
    if write_depth.get("overall") == "PASS_WRITE_PIPELINE_DEPTH_EVIDENCE":
        print("\n  Lower-WRITE submission depth 1 vs 2 — five matched fast QD32 rounds")
        rows = []
        for depth in ("1", "2"):
            mode = write_depth["modes"][depth]
            rows.append((
                depth,
                f"{mode['write_mbps']:.2f}",
                f"{mode['write_p99_ms']:.2f}",
                f"{mode['lower_write_requests']:.1f}",
                f"{mode['pipeline_active_max']:.1f}",
            ))
        print_table(
            "Bounded lower-WRITE depth means — SSD RAM model",
            ("depth", "W MB/s", "p99", "lower req", "active max"), rows)
        ci_rows = []
        for label, field in (
                ("W %", "throughput_change_fraction"),
                ("p99 %", "p99_change_fraction"),
                ("lower B %", "lower_bytes_change_fraction"),
                ("lower req %", "lower_requests_change_fraction"),
                ("raw-control W %", "raw_control_throughput_change_fraction")):
            ci = write_depth["paired"][field]
            ci_rows.append((label, f"{ci['mean'] * 100:+.1f}",
                            f"{ci['low'] * 100:+.1f}",
                            f"{ci['high'] * 100:+.1f}"))
        print_table(
            "Depth 2 minus depth 1 paired 95% confidence intervals",
            ("metric", "mean", "low", "high"), ci_rows)
    else:
        print("\n  Lower-WRITE depth 1/2 A/B: RETIRED FROM ROUTINE QUALIFICATION "
              f"({write_depth.get('reason', write_depth.get('overall', 'NOT_RUN'))})")



def git_result(command, *, data=None, timeout=15, env=None):
    """Run noninteractive Git plumbing without exposing remote/credential stderr."""
    try:
        return subprocess.run(["git", *command], input=data, cwd=ROOT,
                              capture_output=True, check=False, timeout=timeout,
                              env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None


def publish(source_sha):
    """Publish the canonical report with bounded nonforce retry.

    source_sha names the nearest non-report code commit. HEAD may already be a
    generated report-only commit. Publication always builds on the actual main
    head so report-on-report updates stay fast-forward, while ancestry checks
    ensure a concurrent source advance still descends from the tested code.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        return "SKIPPED_GIT_SYNC: tested source commit unavailable"
    if REPORT != ROOT / GIT_RESULT or not REPORT.is_file():
        return "SKIPPED_GIT_SYNC: canonical report missing"

    try:
        with REPORT.open("rt", encoding="utf-8") as stream:
            contents = json.load(stream)
        if not isinstance(contents, dict) or \
                contents.get("tested_commit_sha") != source_sha or \
                contents.get("source_sha") != source_sha:
            return "SKIPPED_GIT_SYNC: report does not match tested Git commit"
    except (OSError, ValueError):
        return "SKIPPED_GIT_SYNC: JSON report is unreadable"

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    if not env.get("GIT_SSH_COMMAND"):
        env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes -o ConnectTimeout=8"

    def run(*args, data=None, timeout=15):
        return git_result(list(args), data=data, env=env, timeout=timeout)

    location = run("rev-parse", "--show-toplevel")
    branch = run("symbolic-ref", "--quiet", "--short", "HEAD")
    head = run("rev-parse", "HEAD")
    if any(item is None or item.returncode for item in (location, branch, head)):
        return "SKIPPED_GIT_SYNC: not an authenticated Git checkout"
    if Path(os.fsdecode(location.stdout).strip()).resolve() != ROOT or \
            branch.stdout.strip() != b"main":
        return "SKIPPED_GIT_SYNC: only the canonical main checkout may publish"
    head_sha = head.stdout.decode("ascii", "replace").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", head_sha) or git_sha() != source_sha:
        return "SKIPPED_GIT_SYNC: checkout changed during testing"

    remote = run("remote", "get-url", "--push", "origin")
    if remote is None or remote.returncode:
        return "SKIPPED_GIT_SYNC: Git remote origin missing"
    url = os.fsdecode(remote.stdout).strip()
    if not re.fullmatch(
            r"(?:git@github[.]com:|ssh://git@github[.]com/|https://github[.]com/)"
            r"k1moradi/swapz(?:[.]git)?", url):
        return "SKIPPED_GIT_SYNC: origin is not k1moradi/swapz"

    tracked = run("diff", "--quiet", "--", ".", f":(exclude){GIT_RESULT}")
    cached = run("diff", "--cached", "--quiet")
    report_tracked = run("ls-files", "--error-unmatch", "--", GIT_RESULT)
    if any(item is None or item.returncode
           for item in (tracked, cached, report_tracked)):
        return "SKIPPED_GIT_SYNC: tracked source/index is not clean"

    blob = run("hash-object", "-w", "--no-filters", str(REPORT))
    if blob is None or blob.returncode:
        return "GIT_SYNC_FAILED: could not prepare report Git objects"
    blob_id = blob.stdout.decode("ascii", "replace").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", blob_id):
        return "GIT_SYNC_FAILED: invalid report blob"

    message = (f"test: latest run for {source_sha[:12]} "
               "[skip ci]").encode("utf-8")

    def build_report_commit(parent_sha):
        root_tree = run("ls-tree", "-z", parent_sha)
        if root_tree is None or root_tree.returncode:
            return None, "GIT_SYNC_FAILED: could not prepare report Git objects"
        entries = []
        for item in root_tree.stdout.split(b"\0"):
            if not item:
                continue
            try:
                _, name = item.split(b"\t", 1)
            except ValueError:
                return None, "GIT_SYNC_FAILED: malformed root Git tree"
            if name != GIT_RESULT.encode("ascii"):
                entries.append(item)
        entries.append(f"100644 blob {blob_id}\t{GIT_RESULT}".encode())
        entries.sort(key=lambda item: item.split(b"\t", 1)[1])
        tree = run("mktree", "-z", data=b"\0".join(entries) + b"\0")
        if tree is None or tree.returncode:
            return None, "GIT_SYNC_FAILED: could not assemble report-only tree"
        tree_id = tree.stdout.decode("ascii", "replace").strip()
        commit = run("commit-tree", tree_id, "-p", parent_sha, data=message)
        if commit is None or commit.returncode:
            return None, ("SKIPPED_GIT_SYNC: Git commit identity unavailable "
                          "(configure user.name/user.email)")
        report_sha = commit.stdout.decode("ascii", "replace").strip()
        if not re.fullmatch(r"[0-9a-f]{40}", report_sha):
            return None, "GIT_SYNC_FAILED: invalid report commit"
        return report_sha, None

    report_sha, error = build_report_commit(head_sha)
    if error:
        return error
    push = run("push", "origin", f"{report_sha}:refs/heads/main", timeout=60)
    concurrent_parent = None

    if push is None or push.returncode:
        report_sha = None
        for attempt in range(3):
            time.sleep(2 << attempt)
            fetch = run("fetch", "--no-tags", "origin", "main", timeout=60)
            if fetch is None or fetch.returncode:
                continue
            remote_head = run("rev-parse", "FETCH_HEAD")
            if remote_head is None or remote_head.returncode:
                continue
            remote_sha = remote_head.stdout.decode("ascii", "replace").strip()
            if not re.fullmatch(r"[0-9a-f]{40}", remote_sha):
                return "GIT_SYNC_FAILED: fetched origin/main is malformed"
            if remote_sha != head_sha:
                ancestor = run("merge-base", "--is-ancestor",
                               source_sha, remote_sha)
                if ancestor is None:
                    continue
                if ancestor.returncode:
                    return ("GIT_SYNC_FAILED: origin/main no longer descends "
                            "from the tested source; report remains local")
                remote_blob = run("show", f"{remote_sha}:{GIT_RESULT}")
                if remote_blob is not None and not remote_blob.returncode:
                    try:
                        remote_json = json.loads(
                            remote_blob.stdout.decode("utf-8", "replace"))
                        remote_tested = (remote_json.get("tested_commit_sha") or
                                         remote_json.get("source_sha"))
                        if isinstance(remote_tested, str) and \
                                re.fullmatch(r"[0-9a-f]{40}", remote_tested) and \
                                remote_tested != source_sha:
                            tested_ancestor = run(
                                "merge-base", "--is-ancestor",
                                source_sha, remote_tested)
                            if tested_ancestor is None:
                                continue
                            if tested_ancestor.returncode > 1:
                                return ("GIT_SYNC_FAILED: git merge-base failed while "
                                        "evaluating remote qualification evidence")
                            if not tested_ancestor.returncode:
                                return (f"SKIPPED_GIT_SYNC: newer-source qualification "
                                        f"evidence already published ({remote_tested[:12]})")
                    except (ValueError, UnicodeDecodeError):
                        pass
            retry_sha, error = build_report_commit(remote_sha)
            if error:
                return error
            retry = run("push", "origin",
                        f"{retry_sha}:refs/heads/main", timeout=60)
            if retry is not None and not retry.returncode:
                report_sha = retry_sha
                if remote_sha != head_sha:
                    concurrent_parent = remote_sha
                break
        if report_sha is None:
            return ("GIT_SYNC_FAILED: report publication failed after bounded "
                    "noninteractive push/fetch retries")

    if concurrent_parent is not None:
        head_now = run("rev-parse", "HEAD")
        tracked_now = run("diff", "--quiet", "--", ".",
                          f":(exclude){GIT_RESULT}")
        cached_now = run("diff", "--cached", "--quiet")
        clean_for_refresh = (
            head_now is not None and not head_now.returncode and
            head_now.stdout.decode("ascii", "replace").strip() == head_sha and
            tracked_now is not None and not tracked_now.returncode and
            cached_now is not None and not cached_now.returncode)
        if clean_for_refresh:
            refresh = run("reset", "--hard", report_sha, timeout=30)
            if refresh is not None and not refresh.returncode:
                return (f"SYNCED_GIT_AFTER_ADVANCE: "
                        f"https://github.com/{REPO}/blob/main/{GIT_RESULT} "
                        f"(report {report_sha[:12]}; tested {source_sha[:12]}; "
                        f"preserved main {concurrent_parent[:12]})")
        return (f"SYNCED_GIT_REMOTE: https://github.com/{REPO}/blob/main/"
                f"{GIT_RESULT} (report {report_sha[:12]}; tested "
                f"{source_sha[:12]}; local refresh skipped after concurrent "
                "main advance)")

    local_ref = run("update-ref", "refs/heads/main", report_sha, head_sha)
    if local_ref is None or local_ref.returncode:
        return (f"SYNCED_GIT_REMOTE: https://github.com/{REPO}/blob/main/"
                f"{GIT_RESULT} (local main refresh failed)")
    index = run("read-tree", report_sha)
    if index is None or index.returncode:
        return (f"SYNCED_GIT_REMOTE: https://github.com/{REPO}/blob/main/"
                f"{GIT_RESULT} (local index refresh failed)")

    return (f"SYNCED_GIT: https://github.com/{REPO}/blob/main/{GIT_RESULT} "
            f"(report {report_sha[:12]}; tested {source_sha[:12]})")

def report_host_identity():
    """Stable OS installation identity; never publish raw machine-id or hostname."""
    try:
        machine_id = Path("/etc/machine-id").read_text().strip()
        if not re.fullmatch(r"[0-9a-fA-F]{32}", machine_id) or int(machine_id, 16) == 0:
            raise ValueError("invalid machine-id")
        return {"schema": "swapz-host-v1", "architecture": os.uname().machine,
                "id_sha256": hashlib.sha256(
                    b"swapz-host\0" + machine_id.lower().encode()).hexdigest()}
    except (OSError, ValueError):
        return {"schema": "swapz-host-v1", "status": "UNAVAILABLE"}


def refresh_history(host_identity):
    """Render only this run's computer after publication, independently of verdict."""
    digest = host_identity.get("id_sha256", "")
    arch = host_identity.get("architecture", "")
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or not re.fullmatch(r"[a-zA-Z0-9_-]+", arch):
        return "NOT UPDATED: stable host identity unavailable; refusing to mix computers"
    output = ROOT / "build/history" / (arch + "-" + digest)
    log = output / "refresh.log"
    env = os.environ.copy()
    env["MPLBACKEND"] = "Agg"
    env.setdefault("MPLCONFIGDIR", str(output / "matplotlib-cache"))
    try:
        output.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [sys.executable, "-B", str(ROOT / "tests/tools/plot-history.py"),
             "--host-id", digest, "--host-architecture", arch],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        log.write_text(proc.stdout + proc.stderr)
        if proc.returncode:
            return f"NOT UPDATED: history helper failed; see {log.relative_to(ROOT)}"
        summary = json.loads(proc.stdout)
        result = (f"UPDATED: {summary['reports']} this-computer PASS reports; latest source "
                  f"{summary['latest_source'][:12]}; {output.relative_to(ROOT)}/index.md")
        # Historical cohorts without a stable machine ID remain separate
        # references. Do not append them to the exact-computer series.
        reference_command = None
        if arch == "aarch64":
            reference_command = [sys.executable, "-B",
                                 str(ROOT / "tests/tools/plot-history.py")]
        elif arch == "x86_64":
            profile_path = ROOT / "docs/handoff/x86-host-history.json"
            try:
                profile = json.loads(profile_path.read_text())
            except (OSError, ValueError):
                profile = {}
            if profile.get("host_id_sha256") == digest:
                reference_command = [sys.executable, "-B",
                                     str(ROOT / "tests/tools/plot-history.py"),
                                     "--host-profile", str(profile_path)]
        if reference_command is not None:
            reference_log = output / "reference-refresh.log"
            try:
                reference_run = subprocess.run(
                    reference_command, cwd=ROOT, env=env, capture_output=True,
                    text=True, timeout=120)
                reference_log.write_text(reference_run.stdout + reference_run.stderr)
                if reference_run.returncode:
                    result += (f"; separate historical reference NOT UPDATED "
                               f"(see {reference_log.relative_to(ROOT)})")
                else:
                    reference = json.loads(reference_run.stdout)
                    result += (f"; separate audited/cohort reference UPDATED: "
                               f"{reference['reports']} PASS reports; "
                               f"{Path(reference['output']).relative_to(ROOT)}/index.md")
            except (OSError, ValueError, KeyError, TypeError,
                    subprocess.TimeoutExpired) as error:
                result += (f"; separate historical reference NOT UPDATED "
                           f"({type(error).__name__}; see {reference_log.relative_to(ROOT)})")
        return result
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        return f"NOT UPDATED: {type(error).__name__}; see {log.relative_to(ROOT)}"


def qualification_overall(exit_code, stages):
    if not exit_code:
        return "PASS"
    if stages and stages[-1].get("status") == "BLOCKED":
        return "BLOCKED"
    return "FAIL"


def required_benchmark_gates_pass(benchmarks):
    """Only current, non-retired loaded evidence may gate qualification."""
    return (
        benchmarks["verdicts"].get("overall") == "PASS_BOUNDED_RAM_MATRIX" and
        benchmarks["write_saturation"].get("overall") ==
        "PASS_WRITE_SATURATION_EVIDENCE" and
        benchmarks.get("lone_raw_qd1", {}).get("overall") ==
        "PASS_LONE_RAW_QD1_CANDIDATE"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kdir", required=True)
    args = parser.parse_args()
    result = {
        "schema": "swapz-test-results-v1",
        "host_identity": report_host_identity(),
        "source_sha": git_sha(),
        "tested_commit_sha": git_sha(),
        "kernel_release": os.uname().release,
        "qualification": "RAM_BACKED_NULL_BLK_ONLY",
        "stages": [],
        "benchmarks": {"sessions": [], "verdicts": {"overall": "NOT_RUN"},
                       "loaded_correctness": {"overall": "NOT_RUN"},
                       "lz4_acceleration_sessions": [],
                       "lz4_acceleration": {"overall": "NOT_RUN"},
                       "write_saturation_sessions": [],
                       "write_saturation": {"overall": "NOT_RUN"},
                       "write_pipeline_depth_sessions": [],
                       "write_pipeline_depth": {"overall": "NOT_RUN"},
                       "storage_envelope_sessions": [],
                       "storage_envelopes": {"overall": "NOT_RUN"}},
        "overall": "INCOMPLETE"
    }
    make_cmd, parallelism = make_invocation()
    print("swapz: full test and benchmark qualification")
    print(f"  Tests are sequential; {parallelism}")
    stages = [
        ("Build module and helpers", [*make_cmd, f"KDIR={args.kdir}"]),
        ("Native and rootless contracts", ["bash", "tests/tools/test-rootless.sh"]),
        ("Kernel warnings W=1", [*make_cmd, "-C", "src/kernel",
                                 f"KDIR={args.kdir}", "W=1", "all"]),
        ("Kernel warnings W=2", [*make_cmd, "-C", "src/kernel",
                                 f"KDIR={args.kdir}", "W=2", "all"]),
        ("Owned RAM smoke + mixed/QD pilot", ["bash", "tests/tools/test-loaded.sh"])
    ]
    exit_code = 0
    for i, (title, command) in enumerate(stages):
        code = run_stage(title, command, result, parse_bench=(i == 4))
        if code:
            exit_code = code
            break
    result["overall"] = qualification_overall(exit_code, result["stages"])
    if not exit_code:
        benchmark = result["benchmarks"]["verdicts"]
        if benchmark.get("overall") == "PASS_BOUNDED_RAM_MATRIX" and \
                re.fullmatch(r"[0-9a-f]{40}", result["tested_commit_sha"]):
            if any(session.get("source_sha") != result["tested_commit_sha"]
                   for session in result["benchmarks"]["sessions"]):
                benchmark["overall"] = "INCONCLUSIVE"
                benchmark["reason"] = "Loaded benchmark source Git ID mismatched tested checkout"
        saturation = result["benchmarks"]["write_saturation"]
        if saturation.get("overall") == "PASS_WRITE_SATURATION_EVIDENCE" and \
                re.fullmatch(r"[0-9a-f]{40}", result["tested_commit_sha"]):
            if any(session.get("source_sha") != result["tested_commit_sha"]
                   for session in result["benchmarks"]["write_saturation_sessions"]):
                saturation["overall"] = "INCONCLUSIVE"
                saturation["reason"] = "Write-only evidence source Git ID mismatched tested checkout"
        write_depth = result["benchmarks"]["write_pipeline_depth"]
        if write_depth.get("overall") == "PASS_WRITE_PIPELINE_DEPTH_EVIDENCE" and \
                re.fullmatch(r"[0-9a-f]{40}", result["tested_commit_sha"]):
            if any(session.get("arms", {}).get(candidate, {}).get("source_sha") !=
                   result["tested_commit_sha"]
                   for session in result["benchmarks"]["write_pipeline_depth_sessions"]
                   for candidate in ("off", "swapz")):
                write_depth["overall"] = "INCONCLUSIVE"
                write_depth["reason"] = (
                    "Lower-WRITE depth A/B source Git ID mismatched tested checkout")
        lz4_sweep = result["benchmarks"]["lz4_acceleration"]
        if lz4_sweep.get("overall") == "PASS_LZ4_ACCELERATION_AB" and \
                re.fullmatch(r"[0-9a-f]{40}", result["tested_commit_sha"]):
            if any(session.get("arms", {}).get(candidate, {}).get("source_sha") !=
                   result["tested_commit_sha"]
                   for session in result["benchmarks"]["lz4_acceleration_sessions"]
                   for candidate in ("off", "swapz")):
                lz4_sweep["overall"] = "INCONCLUSIVE"
                lz4_sweep["reason"] = (
                    "Loaded LZ4 A/B source Git ID mismatched tested checkout")
        delta64_ab = result["benchmarks"]["delta64_prepare"]
        if delta64_ab.get("overall") == "PASS_DELTA64_PREPARE_AB" and \
                re.fullmatch(r"[0-9a-f]{40}", result["tested_commit_sha"]):
            if any(session.get("arms", {}).get(candidate, {}).get("source_sha") !=
                   result["tested_commit_sha"]
                   for session in result["benchmarks"]["delta64_prepare_sessions"]
                   for candidate in ("off", "swapz")):
                delta64_ab["overall"] = "INCONCLUSIVE"
                delta64_ab["reason"] = (
                    "Delta64 K=1/K=2 diagnostic source Git ID mismatched tested checkout")
        if not required_benchmark_gates_pass(result["benchmarks"]):
            result["overall"] = "FAIL"
            exit_code = 1
    write_report(result)
    print_bench(result)
    print(f"\n  Overall qualification: {result['overall']}")
    print(f"  Report: {REPORT.relative_to(ROOT)} (single overwriteable artifact)")
    print(f"  Tested Git commit: {result['tested_commit_sha']}", flush=True)
    notice = publish(result["tested_commit_sha"])
    print(f"  Git result: {notice}", flush=True)
    print("  History plots: " + refresh_history(result["host_identity"]), flush=True)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
