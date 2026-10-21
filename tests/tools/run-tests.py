#!/usr/bin/env python3
"""Private make test runner: one bounded, replace-in-place, sanitized report."""
import argparse
import json
import lzma
import math
import os
import re
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
GIT_RESULT = "test_results.json.xz"
REPORT = ROOT / GIT_RESULT
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
# Five adjacent matched rounds with mode order alternated between rounds.
CONFIRMATION_SEQUENCE = (0, 1, 1, 0, 0, 1, 1, 0, 0, 1)
PAIRED_CI95_T_N5 = 2.7764451051977987
LOGICAL_BLOCK_BYTES = 4096


def device_model_limits(spec):
    """Analytical null_blk cap and unmerged 4KiB latency ceiling."""
    cap_mbps = spec["cap_mib_s"] * (1 << 20) / 1_000_000.0
    latency_mbps = (LOGICAL_BLOCK_BYTES * spec["hw_queue_depth"] *
                    1_000_000_000.0 / spec["completion_nsec"] / 1_000_000.0)
    return {
        "cap_decimal_mbps": cap_mbps,
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
    if len(rows) != len(CONFIRMATION_SEQUENCE) or             [row.get(field) for row in rows] != list(CONFIRMATION_SEQUENCE):
        raise ValueError("five counterbalanced matched rounds required")
    pairs = []
    for index in range(0, len(rows), 2):
        first, second = rows[index:index + 2]
        pairs.append({
            first[field]: first,
            second[field]: second,
        })
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
                      "read_full_extent_reqs", "read_full_cache_hits",
                      "read_two_block_skips", "parallel_read_pairs",
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
                      "parallel_read_coalesce_skip_other",
                      "read_worker_cpu_ns")
WRITE_WAIT_BINS = ("write_wait_le1ms", "write_wait_1to4ms",
                   "write_wait_gt4ms")
PREPARATION_FIELDS = (
    "prep_lower_write_overlap_starts", "prep_wave_kicks",
    "prep_producer_head_claims", "prep_producer_tail_claims",
    "prep_ordered_inline", "prep_ordered_handoffs", "prep_ordered_waits")
WINDOW_SIZE_FIELDS = (
    "windows", "one_page_windows", "win1", "win2", "win3_4", "win5_8",
    "win9_16", "win17_64")
BURST_COUNTER_FIELDS = (
    "packed_early_commits", "single_pack_deferrals",
    "accepted_burst_extensions", "accepted_burst_tail_flushes",
    "accepted_burst_read_caps")
TIMED_WINDOW_COUNTER_FIELDS = (
    WINDOW_SIZE_FIELDS + CLOSE_REASON_FIELDS + ONE_PAGE_CLOSE_FIELDS +
    WIN1_PACK_CAUSE_FIELDS + SINGLE_TAIL_FIELDS + ID52_FIELDS + PACK_CLOSE_FIELDS + BURST_CLOSE_DETAIL_FIELDS + TAIL_SAMPLE_FIELDS + K1_READY_WAIT_FIELDS + DEADLINE_CONTEXT_FIELDS +
    BURST_COUNTER_FIELDS + ("gc_victims",))
SATURATION_WINDOW_FIELDS = WINDOW_SIZE_FIELDS + (
    "close_idle", "close_deadline", "close_pack_ready")
KERNEL_WRITE_FIELDS = (
    "physical_write_reqs", "lz4_wall_ns",
    "ordered_lz4_wall_ns", "prep_lz4_wall_ns",
    "write_copy_wall_ns", "write_copy_bytes",
    "ordered_write_copy_wall_ns", "prep_write_copy_wall_ns",
    "direct_lz4_input_pages", "window_sort_wall_ns",
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
    "prep_lower_write_samples", "prep_lower_write_start_queued",
    "prep_lower_write_start_nonempty", "prep_lower_write_end_queued",
    "prep_lower_write_end_nonempty", "pipeline_async_runs",
    "pipeline_active_wall_ns", "pipeline_finalize_wait_wall_ns",
    "write_wait_le1ms", "write_wait_1to4ms",
    "write_wait_gt4ms", "retained_burst_target"
) + TIMED_WINDOW_COUNTER_FIELDS + PREPARATION_FIELDS
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
PREDICTOR_BACKENDS = ("scalar", "sse2", "avx2", "neon")
PREDICTOR_THRESHOLDS = (4, 8, 16, 24, 32)
PREDICTOR_NEGATIVE_PROFILES = ("zero", "repeat", "entropy", "mixed", "medium")
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
    return {
        "scope": record["scope"],
        "negative_pages": record["negative_pages"],
        "structured_pages": record["structured_pages"],
        "classifier": classifier,
        "backend_benchmarks": backend_rows,
        "io_model_block_ns": io_model_block_ns,
        "thresholds": threshold_rows,
        "transforms": transform_rows,
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
    if any(type(record.get(field)) is not int or record[field] < 0
           for field in TIMED_WINDOW_COUNTER_FIELDS + PREPARATION_FIELDS):
        return "invalid timed swapz window telemetry"
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
            record["pipeline_finalize_wait_wall_ns"]):
        return "timed K=1 ready-wait attribution is inconsistent"
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
        "write_fault": re.compile(
            r"PASS_RETAINED_SYNTHETIC_WRITE_FAULT=retain_ms:(\d+) "
            r"injected:(\d+) lower_write_delta:(\d+)$"),
        "flush_fault": re.compile(
            r"PASS_RETAINED_SYNTHETIC_FLUSH_FAULT=retain_ms:(\d+) "
            r"injected:(\d+) data_write_reached_lower:(\d+)$"),
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
     run_splits_by_hole, alloc_probe_segments, alloc_probe_full_scans,
     alloc_probe_wall_ns, trim_skipped, segment_program_min,
     segment_program_sum, segment_program_max,
     segment_program_segments) = found["gc_pressure"]
    (discard_trim_pages, discard_trim_immediate, discard_trim_sectors,
     discard_trim_reuse_skips, discard_trim_verified) = found["discard_trim"]
    (packed_enabled, packed_verified_pages, packed_holes,
     packed_run_splits, packed_failed) = found["packed_placement"]
    suspend_retain, observed_open, verified_pages = found["suspend"]
    write_retain, write_injected, write_lower_delta = found["write_fault"]
    flush_retain, flush_injected, flush_data_lower = found["flush_fault"]
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
            tail_waste_fg > alignment_hole_fg or
            tail_waste_gc > alignment_hole_gc or
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
    if (packed_enabled != 1 or packed_verified_pages != 128 or packed_failed != 0):
        return {"overall": "INCOMPLETE",
                "reason": "loaded packed-placement smoke evidence is incomplete"}
    if suspend_retain != 4 or observed_open != 1 or verified_pages != 128:
        return {"overall": "INCOMPLETE",
                "reason": "loaded suspend/drain evidence is incomplete"}
    if write_retain != 2 or write_injected != 1 or write_lower_delta != 0:
        return {"overall": "INCOMPLETE",
                "reason": "synthetic retained WRITE fault contract failed"}
    if flush_retain != 2 or flush_injected != 1 or flush_data_lower != 1:
        return {"overall": "INCOMPLETE",
                "reason": "synthetic retained FLUSH fault contract failed"}
    return {
        "overall": "PASS",
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
        "retained_write_fault": "PRE_SUBMISSION_EIO_ZERO_LOWER_WRITE",
        "retained_flush_fault": "PRE_SUBMISSION_FLUSH_EIO_AFTER_DATA_WRITE",
        "scope": "OWNED_RAM_NULL_BLK_SYNTHETIC_FAILURE_ONLY",
    }


def write_report(result):
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, sort_keys=True, indent=2,
                         allow_nan=False).encode("utf-8") + b"\n"
    temporary = REPORT.with_name(".test_results.json.xz.tmp")
    try:
        with lzma.open(temporary, "wb", preset=6) as out:
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
            elif line.startswith("START_LOADED_LIVE_GC"):
                phase = "owned RAM live-GC pressure"
            elif line.startswith("START_LOADED_SUSPEND_DRAIN"):
                phase = "owned RAM retained suspend/drain"
            elif line.startswith("START_LOADED_RETAINED_WRITE_FAULT"):
                phase = "owned RAM retained synthetic WRITE fault"
            elif line.startswith("START_LOADED_RETAINED_FLUSH_FAULT"):
                phase = "owned RAM retained synthetic FLUSH fault"
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

    if unittest_failure is not None:
        reason = f"Unit test failed: {unittest_failure}"
    elif loaded and "BLOCKED_LOADED_QUALIFICATION" in output:
        reason = "Noninteractive root/sudo authorization is unavailable"
    elif loaded and "QUARANTINED:" in output:
        reason = "Safety quarantine: owned device or swap identity could not be safely released"
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

def run_stage(title, command, result, *, parse_bench=False):
    start = time.monotonic()
    try:
        child_env = os.environ.copy()
        tested_source = result.get("tested_commit_sha")
        if isinstance(tested_source, str) and re.fullmatch(
                r"[0-9a-f]{40}", tested_source):
            child_env["SWAPZ_TESTED_SOURCE_SHA"] = tested_source
        proc = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8",
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
    read_coalesce_sessions = parse_read_coalesce_ab(output) if parse_bench else []
    read_coalesce_diagnostic = (
        read_coalesce_ab_verdict(read_coalesce_sessions)
        if parse_bench else None)
    sd_coalesce_sessions = parse_sd_read_coalesce_ab(output) if parse_bench else []
    sd_coalesce_diagnostic = (
        sd_read_coalesce_ab_verdict(sd_coalesce_sessions)
        if parse_bench else None)
    packed_placement_sessions = (
        parse_packed_placement_ab(output) if parse_bench else [])
    packed_placement_diagnostic = (
        packed_placement_ab_verdict(packed_placement_sessions)
        if parse_bench else None)
    marker_failure = (parse_bench and rc == 0 and
                      (loaded_correctness.get("overall") != "PASS" or
                       read_coalesce_diagnostic.get("overall") !=
                       "PASS_READ_COALESCE_AB_CONFIRMATION" or
                       sd_coalesce_diagnostic.get("overall") !=
                       "PASS_SD_READ_COALESCE_AB_CONFIRMATION" or
                       packed_placement_diagnostic.get("overall") !=
                       "PASS_PACKED_PLACEMENT_AB"))
    if marker_failure:
        rc = 1
    blocked_marker = parse_bench and any(
        line.startswith(("BLOCKED:", "BLOCKED_LOADED_QUALIFICATION"))
        for line in output.splitlines())
    status = ("PASS" if rc == 0 else "BLOCKED" if blocked_marker else "FAIL")
    record = {"name": title, "status": status, "elapsed_s":
              round(time.monotonic() - start, 3), "exit_code": rc}
    if rc:
        record["signals"] = safe_lines(output)
        # The sanitized report may be published via Git only.
        # Do not publish an untrusted last log line: it can contain a host
        # path, swap inventory, block-device identity or local username.
        if predictor_failure:
            record["failed_phase"] = "ID67 offline predictor evidence"
            record["diagnostic"] = (
                "Native predictor evidence marker missing, malformed or incomplete")
        elif gc_scale_failure:
            record["failed_phase"] = "ID61 GC scan scaling evidence"
            record["diagnostic"] = (
                "Native GC scan scaling marker missing, malformed or incomplete")
        elif extent_geometry_failure:
            record["failed_phase"] = "ID73 offline extent geometry evidence"
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
                    "reason", "ID63 diagnostic evidence is incomplete")
            elif sd_coalesce_diagnostic.get("overall") != (
                    "PASS_SD_READ_COALESCE_AB_CONFIRMATION"):
                record["failed_phase"] = "SD adjacent READ coalescing A/B evidence"
                record["diagnostic"] = sd_coalesce_diagnostic.get(
                    "reason", "SD ID63 diagnostic evidence is incomplete")
            elif packed_placement_diagnostic.get("overall") != (
                    "PASS_PACKED_PLACEMENT_AB"):
                record["failed_phase"] = "ID69 packed placement A/B evidence"
                record["diagnostic"] = packed_placement_diagnostic.get(
                    "reason", "ID69 placement evidence is incomplete")
            else:
                record["failed_phase"] = "ID69 packed placement A/B evidence"
                record["diagnostic"] = packed_placement_diagnostic.get(
                    "reason", "ID69 placement evidence is incomplete")
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
        result["benchmarks"]["read_coalesce_ab_sessions"] = read_coalesce_sessions
        result["benchmarks"]["read_coalesce_ab"] = read_coalesce_diagnostic
        result["benchmarks"]["sd_read_coalesce_ab_sessions"] = sd_coalesce_sessions
        result["benchmarks"]["sd_read_coalesce_ab"] = sd_coalesce_diagnostic
        result["benchmarks"]["packed_placement_ab_sessions"] = packed_placement_sessions
        result["benchmarks"]["packed_placement_ab"] = packed_placement_diagnostic
        result["benchmarks"]["write_saturation_sessions"] = parse_write_saturation(output)
        result["benchmarks"]["write_saturation"] = write_saturation_verdict(
            result["benchmarks"]["write_saturation_sessions"])
    print(f"  {len(result['stages']):>2}/5  {title:<29} "
          f"{status:<8} {record['elapsed_s']:>8.2f}s", flush=True)
    if rc and "diagnostic" in record:
        print(f"        Failed during: {record['failed_phase']}", flush=True)
        print(f"        Reason: {record['diagnostic']}", flush=True)
    return rc


def _status_u64(status, key):
    match = re.search(r"(?:^|\\s)" + re.escape(key) + r"=(\\d+)(?:\\s|$)",
                      status)
    return int(match.group(1)) if match else None


def parse_packed_placement_ab(output):
    sessions, current = [], None
    for raw in output.splitlines():
        line = raw.strip()
        if line.startswith("START_PACKED_PLACEMENT_AB="):
            try:
                mode = int(line.rsplit("=", 1)[-1])
            except ValueError:
                return []
            if mode not in (0, 1):
                return []
            current = {"packed_placement": mode, "status": "INCOMPLETE",
                       "order": "unknown", "swapz": None,
                       "status_after": None}
            sessions.append(current)
        elif current is not None and line.startswith("REPLAY_ORDER="):
            current["order"] = line.partition("=")[2].strip()
        elif current is not None and line.startswith("SWAPZ_STATUS_AFTER="):
            current["status_after"] = line.partition("=")[2].strip()
        elif current is not None and line.startswith("{"):
            try:
                obj = json.loads(line)
            except (TypeError, ValueError):
                continue
            if obj.get("candidate") != "swapz" or obj.get("verdict") != "PASS":
                continue
            rates = obj.get("throughput_mbps") or {}
            lower = obj.get("lower_io") or {}
            kernel = obj.get("kernel_write_path") or {}
            current["swapz"] = {
                "source_sha": obj.get("source_sha"),
                "fixture_sha256": obj.get("fixture_sha256"),
                "trace_sha256": obj.get("trace_sha256"),
                "replay_mode": obj.get("replay_mode"),
                "qd": obj.get("qd"), "write_ops": obj.get("write_ops"),
                "read_ops": obj.get("read_ops"),
                "verified_pages": obj.get("verified_pages"),
                "logical_write_mbps": rates.get("logical_write_mbps"),
                "write_p99_ns": obj.get("write_p99_ns"),
                "lower_write_bytes": lower.get("lower_write_bytes"),
                "lower_write_requests": lower.get("lower_write_requests"),
                "physical_write_reqs": kernel.get("physical_write_reqs"),
            }
        elif current is not None and line.startswith("PASS_PACKED_PLACEMENT_AB="):
            try:
                mode = int(line.rsplit("=", 1)[-1])
            except ValueError:
                return []
            if mode != current["packed_placement"]:
                return []
            current["status"] = "PASS"
            current = None
    return sessions


def packed_placement_ab_verdict(sessions):
    expected_modes = (0, 1, 1, 0)
    if len(sessions) != len(expected_modes) or tuple(
            row.get("packed_placement") for row in sessions) != expected_modes:
        return {"overall": "INCOMPLETE",
                "reason": "ID69 placement A/B session sequence is incomplete"}
    clean = []
    for row in sessions:
        arm = row.get("swapz")
        status = row.get("status_after")
        if row.get("status") != "PASS" or not isinstance(arm, dict) or \
                not isinstance(status, str):
            return {"overall": "INCOMPLETE",
                    "reason": "ID69 placement A/B arm did not complete"}
        integer_fields = (
            "qd", "write_ops", "read_ops", "verified_pages", "write_p99_ns",
            "lower_write_bytes", "lower_write_requests", "physical_write_reqs")
        if any(type(arm.get(field)) is not int or arm[field] < 0
               for field in integer_fields):
            return {"overall": "INCOMPLETE",
                    "reason": "ID69 placement A/B I/O evidence is malformed"}
        if (arm["qd"] != 32 or arm["write_ops"] != 2048 or arm["read_ops"] != 0 or
                arm["verified_pages"] != 1024 or
                arm["replay_mode"] != "persistent-write" or
                not isinstance(arm.get("source_sha"), str) or
                not re.fullmatch(r"[0-9a-f]{40}", arm["source_sha"]) or
                not isinstance(arm.get("fixture_sha256"), str) or
                not re.fullmatch(r"[0-9a-f]{64}", arm["fixture_sha256"]) or
                not isinstance(arm.get("trace_sha256"), str) or
                not re.fullmatch(r"[0-9a-f]{64}", arm["trace_sha256"]) or
                not isinstance(arm.get("logical_write_mbps"), (int, float)) or
                not math.isfinite(arm["logical_write_mbps"]) or
                arm["logical_write_mbps"] <= 0):
            return {"overall": "INCOMPLETE",
                    "reason": "ID69 placement A/B workload identity is invalid"}
        mode = row["packed_placement"]
        status_values = {
            key: _status_u64(status, key) for key in (
                "packed_placement", "logical_open_balance",
                "alignment_hole_blocks_foreground",
                "segment_tail_waste_blocks_foreground",
                "run_splits_by_hole", "segment_program_sum")
        }
        if any(value is None for value in status_values.values()) or \
                status_values["packed_placement"] != mode or \
                status_values["logical_open_balance"] != 0:
            return {"overall": "INCOMPLETE",
                    "reason": "ID69 placement A/B status policy mismatch"}
        if (arm["physical_write_reqs"] <= 0 or
                arm["lower_write_bytes"] <= 0 or arm["write_p99_ns"] <= 0 or
                status_values["segment_program_sum"] <= 0):
            return {"overall": "INCOMPLETE",
                    "reason": "ID69 placement A/B measured write evidence is empty"}
        aggregate_holes = status_values["alignment_hole_blocks_foreground"]
        tail_waste = status_values["segment_tail_waste_blocks_foreground"]
        if tail_waste > aggregate_holes:
            return {"overall": "INCOMPLETE",
                    "reason": "ID69 placement telemetry has tail waste above aggregate holes"}
        clean.append({
            **row,
            "holes": aggregate_holes,
            "tail_waste": tail_waste,
            "internal_holes": aggregate_holes - tail_waste,
            "run_splits": status_values["run_splits_by_hole"],
            "segment_program_sum": status_values["segment_program_sum"],
        })
    if len({row["swapz"]["source_sha"] for row in clean}) != 1 or \
            len({row["swapz"]["fixture_sha256"] for row in clean}) != 1 or \
            len({row["swapz"]["trace_sha256"] for row in clean}) != 1:
        return {"overall": "INCOMPLETE",
                "reason": "ID69 placement A/B did not reuse one immutable workload"}
    pairs = ((clean[0], clean[1]), (clean[3], clean[2]))
    paired = []
    for aligned, packed in pairs:
        if aligned["packed_placement"] != 0 or packed["packed_placement"] != 1:
            return {"overall": "INCOMPLETE",
                    "reason": "ID69 placement A/B pairing is invalid"}
        if aligned["internal_holes"] <= 0 and aligned["run_splits"] <= 0:
            return {"overall": "INCOMPLETE",
                    "reason": "ID69 control workload did not exercise alignment waste"}
        if packed["internal_holes"] != 0 or packed["run_splits"] != 0:
            return {"overall": "REGRESSION",
                    "reason": "ID69 packed placement retained internal holes"}
        a, p = aligned["swapz"], packed["swapz"]
        if p["physical_write_reqs"] >= a["physical_write_reqs"]:
            return {"overall": "NO_GAIN",
                    "reason": "ID69 packed placement did not reduce physical WRITE requests"}
        if p["lower_write_bytes"] > a["lower_write_bytes"]:
            return {"overall": "REGRESSION",
                    "reason": "ID69 packed placement increased lower WRITE bytes"}
        if packed["segment_program_sum"] >= aligned["segment_program_sum"]:
            return {"overall": "NO_GAIN",
                    "reason": "ID69 packed placement did not reduce logical segment opens"}
        paired.append({
            "request_change_pct":
                (p["physical_write_reqs"] - a["physical_write_reqs"]) * 100.0 /
                a["physical_write_reqs"],
            "byte_change_pct":
                (p["lower_write_bytes"] - a["lower_write_bytes"]) * 100.0 /
                a["lower_write_bytes"] if a["lower_write_bytes"] else 0.0,
            "throughput_change_pct":
                (p["logical_write_mbps"] - a["logical_write_mbps"]) * 100.0 /
                a["logical_write_mbps"],
            "p99_change_pct":
                (p["write_p99_ns"] - a["write_p99_ns"]) * 100.0 /
                a["write_p99_ns"] if a["write_p99_ns"] else 0.0,
            "program_change":
                packed["segment_program_sum"] - aligned["segment_program_sum"],
        })
    return {
        "overall": "PASS_PACKED_PLACEMENT_AB",
        "scope": "OWNED_RAM_MIXED_CLASS_PLACEMENT_ONLY",
        "sessions": clean, "paired": paired,
        "mean_request_change_pct":
            statistics.mean(row["request_change_pct"] for row in paired),
        "mean_byte_change_pct":
            statistics.mean(row["byte_change_pct"] for row in paired),
        "mean_throughput_change_pct":
            statistics.mean(row["throughput_change_pct"] for row in paired),
        "mean_p99_change_pct":
            statistics.mean(row["p99_change_pct"] for row in paired),
    }


def parse_sessions(output):
    sessions, current, regime = [], None, None
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("START_OWNED_RAM_REGIME="):
            regime = line.partition("=")[2]
        elif line.startswith(("START_READ_COALESCE_AB=",
                              "START_SD_READ_COALESCE_AB=",
                              "START_PACKED_PLACEMENT_AB=",
                              "START_BURST_GUARD_AB=",
                              "START_WRITE_SATURATION_REGIME=")):
            current = None
        elif line.startswith("START_OWNED_RAM_PAIR_ASYNC_PREPARE="):
            current = {"async_prepare": int(line.rsplit("=", 1)[-1]),
                       "regime": regime, "status": "INCOMPLETE", "arms": {},
                       "order": "unknown", "device_model": None}
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
            # Full-process status includes prefill/warmup/post-mixed work.
            # Keep it in the private session log only; report diagnostics come
            # from io-replay's exact timed kernel_write_path snapshots.
            continue
        elif current is not None and line.startswith(
                "PASS_OWNED_RAM_PAIR_ASYNC_PREPARE="):
            current["status"] = "PASS"
        elif current is not None and line.startswith(
                "PASS_ASYNC_LOWER_IO_OVERLAP_STARTS="):
            current["overlap_starts"] = int(line.rsplit("=", 1)[-1])
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
                    "swap_in_read_p95_ms": obj.get("read_p95_ns", 0) / 1e6,
                    "swap_in_read_p99_ms": obj.get("read_p99_ns", 0) / 1e6,
                    "write_p99_ms": obj.get("write_p99_ns", 0) / 1e6,
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
                    "workload_opportunity": workload_opportunity_record(obj),
                    "kernel_write_path": obj.get("kernel_write_path"),
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
                    "reason": "ID63 confirmation order/status mismatch"}
        model = row.get("device_model")
        if not isinstance(model, dict) or any(model.get(key) != expected[key]
                for key in ("cap_mib_s", "completion_nsec", "irqmode",
                            "queue_mode", "submit_queues", "hw_queue_depth")):
            return {"overall": "INCOMPLETE",
                    "reason": "ID63 confirmation device model mismatch"}
        arm = row.get("swapz")
        if not isinstance(arm, dict) or not re.fullmatch(
                r"[0-9a-f]{40}", str(arm.get("source_sha", ""))):
            return {"overall": "INCOMPLETE",
                    "reason": "ID63 confirmation source missing"}
        if not isinstance(arm.get("packed_close_delta"), int) or \
                arm["packed_close_delta"] <= 0:
            return {"overall": "INCOMPLETE",
                    "reason": "ID63 confirmation packed population missing"}
        for mode in ("sequential", "seeded_random"):
            phase = arm["passes"].get(mode)
            if not isinstance(phase, dict) or \
                    phase.get("logical_bytes") != 4194304 or \
                    phase.get("verified_pages") != 1024:
                return {"overall": "INCOMPLETE",
                        "reason": "ID63 confirmation packed read incomplete"}
            if any(not isinstance(phase.get(key), (int, float)) or
                   phase[key] < 0 for key in
                   ("useful_read_mbps", "read_p99_ms",
                    "lower_read_bytes", "lower_read_requests")):
                return {"overall": "INCOMPLETE",
                        "reason": "ID63 confirmation metrics missing"}
            kernel = phase.get("kernel_read_path")
            if not isinstance(kernel, dict) or any(
                    type(kernel.get(name)) is not int or kernel[name] < 0
                    for name in KERNEL_READ_FIELDS):
                return {"overall": "INCOMPLETE",
                        "reason": "ID63 confirmation C telemetry missing"}
            if not row["read_coalesce"] and kernel["parallel_read_pairs"]:
                return {"overall": "INCOMPLETE",
                        "reason": "ID63-off arm executed retired grouped READ path"}
            if not row["read_coalesce"] and any(kernel[field] for field in (
                    "parallel_read_coalesced_pairs",
                    "parallel_read_coalesced_reqs_saved",
                    "parallel_read_coalesced_blocks",
                    "parallel_read_coalesce_extra_blocks",
                    "parallel_read_coalesce_skip_cached",
                    "parallel_read_coalesce_skip_noncontig_slot",
                    "parallel_read_coalesce_skip_gap",
                    "parallel_read_coalesce_skip_other")):
                return {"overall": "INCOMPLETE",
                        "reason": "ID63-off arm executed coalescing"}
        if row["read_coalesce"] and not arm["passes"]["sequential"][
                "kernel_read_path"]["parallel_read_coalesced_pairs"]:
            return {"overall": "INCOMPLETE",
                    "reason": "ID63-on arm executed no sequential coalescing"}
        if row["read_coalesce"] and any(
                arm["passes"][mode]["kernel_read_path"][
                    "parallel_read_coalesce_skip_other"]
                for mode in ("sequential", "seeded_random")):
            return {"overall": "INCOMPLETE",
                    "reason": "ID63-on arm hit unexpected coalesce skip reason"}
    if len({row["swapz"]["source_sha"] for row in sessions}) != 1 or \
            len({row["swapz"]["fixture_sha256"] for row in sessions}) != 1 or \
            len({row["swapz"]["trace_sha256"] for row in sessions}) != 1 or \
            len({row["swapz"]["logical_image_sha256"] for row in sessions}) != 1:
        return {"overall": "INCONCLUSIVE",
                "reason": "ID63 confirmation provenance mismatch"}

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
                        "reason": "ID63 confirmation zero denominator"}
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
            "SAME_SOURCE_ID63_TOGGLE_ORDINARY_OFF_PATH_SYNTHETIC_RAM_ONLY",
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
                    for name in KERNEL_READ_FIELDS):
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
                    "parallel_read_pairs",
                    "parallel_read_coalesced_pairs",
                    "parallel_read_coalesced_reqs_saved",
                    "parallel_read_coalesced_blocks",
                    "parallel_read_coalesce_extra_blocks",
                    "parallel_read_coalesce_skip_cached",
                    "parallel_read_coalesce_skip_noncontig_slot",
                    "parallel_read_coalesce_skip_gap",
                    "parallel_read_coalesce_skip_other")):
            return {"overall": "INCOMPLETE",
                    "reason": "SD ID63-off arm executed retired grouped/coalesced READ path"}
        if row[field] and not seq_kernel["parallel_read_coalesced_pairs"]:
            return {"overall": "INCOMPLETE",
                    "reason": "SD ID63-on arm executed no sequential coalescing"}
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
            "SAME_SOURCE_HWQ1_ID63_TOGGLE_ORDINARY_OFF_PATH_SYNTHETIC_RAM",
    }


def sd_read_coalesce_ab_verdict(sessions):
    return _sd_read_ab_verdict(sessions, "read_coalesce", "coalescing")



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
                "write_p99_ms": obj.get("write_p99_ns", 0) / 1e6,
                "seconds": obj.get("seconds"),
                "cpu_user_s": obj.get("mixed_replay_cpu_user_s"),
                "cpu_system_s": obj.get("mixed_replay_cpu_system_s"),
                "peak_rss_kb": obj.get("mixed_replay_peak_rss_kb"),
                "lower_inflight": lower_inflight_record(obj),
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
                     if regime == "ssd_emulated" and qd in (4, 8, 32)
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
                "reason": "exactly 40 write-only evidence sessions required"}
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

    return {
        "overall": "PASS_WRITE_SATURATION_EVIDENCE",
        "fast_qd4_matched_pairs": 5,
        "fast_qd8_matched_pairs": 5,
        "fast_qd32_matched_pairs": 5,
        "replay_mode": "persistent-write",
        "confidence":
            "FAST_QD4_QD8_QD32_PAIRED_95PCT_CI_QD1_DIRECTIONAL",
        "model_limits": {
            regime: device_model_limits(MODEL_SPECS[regime])
            for regime in MODEL_ORDER
        },
        "fast_qd4_paired": paired_results[4],
        "fast_qd8_paired": paired_results[8],
        "fast_qd32_paired": paired_results[32],
        "regimes": summaries,
        "interpretation":
            "SYNTHETIC_RAM_SUSTAINED_QD4_QD8_QD32_CONFIRMATION_QD1_DIRECTIONAL",
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
                        record["pipeline_active_wall_ns"]
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
                           record["parallel_read_coalesced_reqs_saved"] !=
                               record["parallel_read_coalesced_pairs"] or
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
                            "one_page_windows", "gc_victims") + WIN1_PACK_CAUSE_FIELDS +
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
            "worker-boundary sum_exec_runtime is a scheduler-accounted lower "
            "bound that can miss short current slices; separately reported "
            "non-sleeping phase floors are the trusted in-callback evidence",
        "physical_media": "NOT_TESTED",
        "workload_opportunity": workload_opportunity,
        "statistical_confidence":
            "FAST_MIXED_FIVE_MATCHED_PAIRS_WITH_PAIRED_95PCT_CI; "
            "SLOW_TWO_OBSERVATIONS_PER_MODE",
        "real_swap_device": "NOT_AUTHORIZED_NOT_TESTED",
    }


def print_table(headers, rows):
    """Print one valid compact GFM pipe table followed by a horizontal rule."""
    text_headers = [str(header) for header in headers]
    text_rows = [[str(value) for value in row] for row in rows]
    widths = [
        max(3, len(text_headers[index]),
            *(len(row[index]) for row in text_rows))
        for index in range(len(headers))
    ]
    print("| " + " | ".join(
        f"{header:<{widths[index]}}"
        for index, header in enumerate(text_headers)) + " |")
    print("| " + " | ".join("-" * width for width in widths) + " |")
    for row in text_rows:
        print("| " + " | ".join(
            f"{value:<{widths[index]}}"
            for index, value in enumerate(row)) + " |")
    print("---")


def print_bench(result):
    predictor = result.get("evidence", {}).get("predictor")
    if isinstance(predictor, dict):
        print("\n  ID67 OFFLINE PREDICTOR EVIDENCE — native controls; not kernel policy")
        print_table(
            ("transform", "adopt", "RAW+", "<=2024", "blocks", "extents",
             "xform ns", "inv ns", "LZ4-2 ns"),
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
        print("  Delta64 selected backends — "
              f"transform={transform['transform_backend']} "
              f"inverse={transform['inverse_backend']}; classifier=scalar")
        print_table(
            ("backend", "xform ns", "inv ns"),
            [(row["name"], row["transform_ns_per_page"],
              row["inverse_ns_per_page"])
             for row in predictor["backend_benchmarks"]])
        print("  Sampled delta64 classifier — scalar; "
              f"{classifier['stage1_pairs']} -> {classifier['sample_pairs']} pairs; "
              f"{classifier['ns_per_page']} ns/eligible page")
        print("  Stage-1 aborts: "
              f"{classifier['early_abort_pages']}/{classifier['eligible_pages']}; "
              f"timing: {classifier['benchmark_repeats']} batched repeats")
        print_table(
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
            ("score", "blocks", "extents"),
            [(row["threshold"], f"{row['routed_blocks_saved']:+d}",
              f"{row['routed_extents_saved']:+d}")
             for row in predictor["thresholds"]])
        io_ns = predictor["io_model_block_ns"]
        print("  Routed delta64 CPU economics")
        print_table(
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
            ("score", "profile", "call/eligible", "useful"),
            [(row["threshold"], profile["name"],
              f"{profile['calls']}/{profile['eligible']}",
              profile["useful"])
             for row in predictor["thresholds"]
             for profile in row["negative_profiles"]])

    gc_scale = result.get("evidence", {}).get("gc_scan_scale")
    if isinstance(gc_scale, dict):
        print("\n  ID61 GC MAP-SCAN SCALE — native CPU evidence; no lower I/O")
        print_table(
            ("pages", "segs", "old ms", "select ms", "map ms", "list ms"),
            [(
                row["logical_pages"], row["segments"],
                f"{row['legacy_score_scan_ns'] / 1e6:.3f}",
                f"{row['incremental_select_ns'] / 1e6:.3f}",
                f"{row['relocation_scan_ns'] / 1e6:.3f}",
                f"{row['relocation_list_ns'] / 1e6:.3f}",
            ) for row in gc_scale["rows"]])
        print("  ID71 DEAD-SEGMENT PROBE SCALE — native CPU evidence; no lower I/O")
        print_table(
            ("logical pages", "segments", "old probe ms", "mapped probe ms"),
            [(
                row["logical_pages"], row["segments"],
                f"{row['legacy_dead_probe_ns'] / 1e6:.3f}",
                f"{row['mapped_dead_probe_ns'] / 1e6:.3f}",
            ) for row in gc_scale["rows"]])

    geometry = result.get("evidence", {}).get("extent_geometry")
    if isinstance(geometry, dict):
        print("\n  ID73 OFFLINE EXTENT GEOMETRY — simulation only; no format policy")
        print_table(
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

        print(f"\n  {regime.upper()} QD32 mixed — synthetic RAM model "
              f"{cfg['cap_mib_s']} MiB/s, {cfg['completion_nsec']} ns, "
              f"hwq={cfg['hw_queue_depth']}")
        print("  Throughput MB/s; p99 ms. Sync stays as the scheduling control.")
        print_table(
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
        print_table(("read", "lower KiB", "req", "p99"), read_rows)
        print("  Packed-read C attribution — wall ms; engine excludes lower READ.")
        print_table(
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

        print("  Lower queue — sampled time-weighted mean / peak during mixed I/O.")
        print_table(
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
        print("  Mixed burst-close split")
        burst_fields = (
            "pack_close_burst_admission", "pack_close_burst_worker",
            "pack_close_burst_target_le4", "pack_close_burst_target_5_8",
            "pack_close_burst_target_9_16", "pack_close_burst_target_17_64",
            "pack_close_burst_count_le4", "pack_close_burst_count_5_8",
            "pack_close_burst_count_9_16", "pack_close_burst_count_17_64",
            "pack_close_burst_overshoot")
        print_table(
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
        print_table(("mode", "0 I/N", "1 I/N", "2+ I/N", "grow/shrink"),
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
        print_table(("mode", "skip-I0", "after-I0", "after-read", "other",
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
            print_table(("metric", "mean", "low", "high"), burst_ci_rows)
        print("  Async pipeline — wall timings overlap; callback rows include scheduler delay.")
        print_table(
            ("stage", "busy ms", "overlap/stall ms"),
            [
                ("LZ4",
                 f"{asynchronous['mixed_lz4_wall_ns'] / 1e6:.1f}",
                 f"{asynchronous['mixed_prep_lower_write_overlap_ns'] / 1e6:.1f} IO"),
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
                 f"{asynchronous['mixed_ordered_worker_cpu_ns'] / 1e6:.1f} sched floor"),
                ("ordered measured floor",
                 f"{(asynchronous['mixed_ordered_lz4_wall_ns'] + asynchronous['mixed_ordered_crc_wall_ns'] + asynchronous['mixed_ordered_write_copy_wall_ns'] + asynchronous['mixed_window_commit_nonio_wall_ns']) / 1e6:.1f}",
                 "non-sleeping phases"),
                ("prep callback",
                 f"{asynchronous['mixed_prep_worker_wall_ns'] / 1e6:.1f}",
                 f"{asynchronous['mixed_prep_worker_cpu_ns'] / 1e6:.1f} sched floor"),
                ("prep measured floor",
                 f"{(asynchronous['mixed_prep_lz4_wall_ns'] + asynchronous['mixed_prep_crc_wall_ns'] + asynchronous['mixed_prep_write_copy_wall_ns']) / 1e6:.1f}",
                 "non-sleeping phases"),
                ("read helper", "-",
                 f"{asynchronous['mixed_read_worker_cpu_ns'] / 1e6:.1f} sched floor"),
                ("scheduling", "-",
                 f"{asynchronous['mixed_prep_wait_wall_ns'] / 1e6:.2f} wait"),
            ])
        print_table(
            ("async signal", "mean"),
            [
                ("direct LZ4 input",
                 f"{asynchronous['mixed_direct_lz4_input_pages']:.1f} pages"),
                ("wave kicks", f"{prep['prep_wave_kicks']:.1f}"),
                ("lower-IO prep starts",
                 f"{prep['prep_lower_write_overlap_starts']:.1f}"),
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
            ("check", "result"),
            [
                ("async/raw W", async_criteria["throughput_vs_raw"]),
                ("async/sync W",
                 data["criteria"]["async_vs_sync"]["write_throughput"]),
                ("lower WRITE", async_criteria["lower_write_savings"]),
                ("packed read", async_criteria["packed_4mib_sequential"]),
            ])

    coalesce_ab = result["benchmarks"].get("read_coalesce_ab", {})
    if coalesce_ab.get("overall") == "PASS_READ_COALESCE_AB_CONFIRMATION":
        print("\n  ID63 ADJACENT READ COALESCE A/B — five matched rounds")
        rows = []
        for enabled in ("0", "1"):
            seq = coalesce_ab["modes"][enabled]["sequential"]
            rnd = coalesce_ab["modes"][enabled]["seeded_random"]
            rows.append((
                enabled,
                f"{seq['lower_read_requests']:.1f}",
                f"{seq['read_p99_ms']:.2f}",
                f"{rnd['lower_read_requests']:.1f}",
                f"{rnd['read_p99_ms']:.2f}",
                f"{seq['parallel_read_coalesced_reqs_saved']:.1f}",
                f"{rnd['parallel_read_coalesced_reqs_saved']:.1f}",
            ))
        print_table(("merge", "seq req", "seq p99", "rnd req", "rnd p99",
                     "seq saved", "rnd saved"), rows)
        active = coalesce_ab["modes"]["1"]
        print("  ID63 active exact-range accounting")
        print_table(
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
        print("  ID63 active non-merge attribution")
        print_table(
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
        req_ci = coalesce_ab["paired"]["sequential"]["lower_requests_change_fraction"]
        p99_ci = coalesce_ab["paired"]["sequential"]["p99_change_fraction"]
        print("  seq on/off paired 95% CI: "
              f"req {req_ci['mean'] * 100:+.1f}% "
              f"[{req_ci['low'] * 100:+.1f},{req_ci['high'] * 100:+.1f}]%; "
              f"p99 {p99_ci['mean'] * 100:+.1f}% "
              f"[{p99_ci['low'] * 100:+.1f},{p99_ci['high'] * 100:+.1f}]%")
    else:
        print("\n  ID63 adjacent READ coalescing A/B: NOT QUALIFIED "
              f"({coalesce_ab.get('reason', coalesce_ab.get('overall', 'NOT_RUN'))})")

    sd_coalesce_ab = result["benchmarks"].get("sd_read_coalesce_ab", {})
    if sd_coalesce_ab.get("overall") == "PASS_SD_READ_COALESCE_AB_CONFIRMATION":
        print("\n  SD ID63 ADJACENT READ COALESCE A/B — five matched rounds")
        rows = []
        for enabled in ("0", "1"):
            seq = sd_coalesce_ab["modes"][enabled]["sequential"]
            rnd = sd_coalesce_ab["modes"][enabled]["seeded_random"]
            rows.append((
                enabled,
                f"{seq['lower_read_requests']:.1f}",
                f"{seq['read_p99_ms']:.2f}",
                f"{rnd['lower_read_requests']:.1f}",
                f"{rnd['read_p99_ms']:.2f}",
                f"{seq['parallel_read_coalesced_reqs_saved']:.1f}",
            ))
        print_table(("merge", "seq req", "seq p99", "rnd req", "rnd p99",
                     "seq saved"), rows)
        active = sd_coalesce_ab["modes"]["1"]
        print("  SD ID63 exact-range attribution")
        print_table(
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
            req = sd_coalesce_ab["paired"][mode][
                "lower_requests_change_fraction"]
            p99 = sd_coalesce_ab["paired"][mode]["p99_change_fraction"]
            ci_rows.extend((
                (label, "req", f"{req['mean'] * 100:+.1f}%",
                 f"{req['low'] * 100:+.1f}%", f"{req['high'] * 100:+.1f}%"),
                (label, "p99", f"{p99['mean'] * 100:+.1f}%",
                 f"{p99['low'] * 100:+.1f}%", f"{p99['high'] * 100:+.1f}%"),
            ))
        print_table(("read", "metric", "mean", "low", "high"), ci_rows)
    else:
        print("\n  SD ID63 adjacent READ coalescing A/B: NOT QUALIFIED "
              f"({sd_coalesce_ab.get('reason', sd_coalesce_ab.get('overall', 'NOT_RUN'))})")

    packed_ab = result["benchmarks"].get("packed_placement_ab")
    if isinstance(packed_ab, dict):
        print("\n  ID69 PACKED PLACEMENT A/B — mixed-class owned RAM")
        if packed_ab.get("overall") == "PASS_PACKED_PLACEMENT_AB":
            print_table(
                ("metric", "paired mean"),
                [
                    ("physical WRITE req",
                     f"{packed_ab['mean_request_change_pct']:+.1f}%"),
                    ("lower WRITE bytes",
                     f"{packed_ab['mean_byte_change_pct']:+.1f}%"),
                    ("logical W throughput",
                     f"{packed_ab['mean_throughput_change_pct']:+.1f}%"),
                    ("write p99",
                     f"{packed_ab['mean_p99_change_pct']:+.1f}%"),
                ])
        else:
            print(f"  verdict: {packed_ab.get('overall')} — "
                  f"{packed_ab.get('reason', 'incomplete')}")

    loaded = result["benchmarks"].get("loaded_correctness", {})
    if loaded.get("overall") == "PASS":
        print("\n  Lifecycle")
        print_table(
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
        ("scope", "value"),
        [
            ("media", "synthetic RAM only"),
            ("mixed statistics", "fast: 5 matched pairs + paired CI; slow: 2/mode"),
            ("read isolation", "ID63 slow+fast 5 matched pairs; standalone grouping retired"),
            ("ID64", "retired; compatibility tokens fixed at zero"),
            ("write-only", "fast QD4/QD8/QD32: 5 matched pairs + paired CI; QD1 directional"),
            ("CPU", "sum_exec_runtime is a lower bound; measured phase floors are separate"),
            ("4MiB read", "RAM-backed; not cold physical swap-in"),
            ("GC", "live victims exercised on synthetic RAM; physical wear unproven"),
            ("Full telemetry", "test_results.json.xz"),
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
        print_table(("model", "cap MB/s", "4K latency MB/s",
                     "effective MB/s", "raw QD32 MB/s"), rows)

        print("\n  WRITE-ONLY SUSTAINED-QD EVIDENCE")
        print("  Persistent lane workers; logical WRITE MB/s, no timed per-I/O Future dispatch.")
        for regime in MODEL_ORDER:
            cfg = MODEL_SPECS[regime]
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
            print_table(("QD", "raw", "sync", "async", "A/S", "A req"),
                        throughput_rows)
            print("  Async preparation")
            print_table(("QD", "wave", "head/tail", "inline", "hand/wait"),
                        prep_rows)
            print("  Async windows; close=P/D/I")
            print_table(("QD", "target", "1", "3-4", "5-8", "17-64", "P/D/I"),
                        window_rows)
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
        with lzma.open(REPORT, "rt", encoding="utf-8") as stream:
            contents = json.load(stream)
        if contents.get("tested_commit_sha") != source_sha or \
                contents.get("source_sha") != source_sha:
            return "SKIPPED_GIT_SYNC: report does not match tested Git commit"
    except (OSError, ValueError, lzma.LZMAError):
        return "SKIPPED_GIT_SYNC: compressed report is unreadable"

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

def qualification_overall(exit_code, stages):
    if not exit_code:
        return "PASS"
    if stages and stages[-1].get("status") == "BLOCKED":
        return "BLOCKED"
    return "FAIL"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kdir", required=True)
    args = parser.parse_args()
    result = {
        "schema": "swapz-test-results-v1",
        "source_sha": git_sha(),
        "tested_commit_sha": git_sha(),
        "kernel_release": os.uname().release,
        "qualification": "RAM_BACKED_NULL_BLK_ONLY",
        "stages": [],
        "benchmarks": {"sessions": [], "verdicts": {"overall": "NOT_RUN"},
                       "loaded_correctness": {"overall": "NOT_RUN"},
                       "write_saturation_sessions": [],
                       "write_saturation": {"overall": "NOT_RUN"}},
        "overall": "INCOMPLETE"
    }
    print("swapz: full test and benchmark qualification")
    print("  Tests are sequential; independent compilation uses Make jobserver.")
    stages = [
        ("Build module and helpers", ["make"]),
        ("Native and rootless contracts", ["bash", "tests/tools/test-rootless.sh"]),
        ("Kernel warnings W=1", ["make", "-C", "src/kernel",
                                 f"KDIR={args.kdir}", "W=1", "all"]),
        ("Kernel warnings W=2", ["make", "-C", "src/kernel",
                                 f"KDIR={args.kdir}", "W=2", "all"]),
        ("Owned RAM smoke + mixed/QD pilot", ["bash", "tests/tools/test-loaded.sh"])
    ]
    exit_code = 0
    for i, (title, command) in enumerate(stages):
        if i == 0:
            command = ["make", f"KDIR={args.kdir}"]
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
        if benchmark.get("overall") != "PASS_BOUNDED_RAM_MATRIX" or \
                saturation.get("overall") != "PASS_WRITE_SATURATION_EVIDENCE":
            result["overall"] = "FAIL"
            exit_code = 1
    write_report(result)
    print_bench(result)
    print(f"\n  Overall qualification: {result['overall']}")
    print(f"  Report: {REPORT.relative_to(ROOT)} (single overwriteable artifact)")
    print(f"  Tested Git commit: {result['tested_commit_sha']}", flush=True)
    notice = publish(result["tested_commit_sha"])
    print(f"  Git result: {notice}", flush=True)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
