#!/usr/bin/env python3
"""Fail-closed validation of serialized loaded-host metadata RAM traces.

This module validates evidence; it does not manufacture host measurements.
Maximum-capacity RAM acceptance remains a serialized loaded-host qualification.
"""
from __future__ import annotations

import datetime
import re
import struct
from typing import Any

BLOCK_BYTES = 4096
SEGMENT_BLOCKS = 256
FOREGROUND_HEADROOM_BLOCKS = SEGMENT_BLOCKS
MINIMUM_GC_RESERVE_BLOCKS = 2 * SEGMENT_BLOCKS
SAMPLING_INTERVAL_NS = 100_000_000
MEMINFO_UNIT_BYTES = 1024
SIZE_T_MAX = (1 << (8 * struct.calcsize("P"))) - 1
PHASES = ("baseline", "initialization", "steady", "gc", "teardown")
MINIMUM_PHASE_SAMPLES = {
    "baseline": 10,
    "initialization": 2,
    "steady": 2,
    "gc": 2,
    # One target-present observation followed by at least two seconds of
    # target-absent quiescence at the required 100 ms cadence.
    "teardown": 22,
}
BOOT_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
SOURCE_SHA = re.compile(r"[0-9a-f]{40}")
MAPPER_UUID = re.compile(r"SWAPZ-[A-Za-z0-9-]{1,120}")
UTC_TIME = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,9})?Z"
)
SAMPLE_FIELDS = {
    "phase", "monotonic_ns", "timestamp_utc", "mem_available_kib",
    "s_unreclaim_kib", "vmalloc_used_kib", "mapper_present",
}


def maximum_logical_pages_for_partition(
        partition_bytes: Any, *, size_t_max: int = SIZE_T_MAX) -> int | None:
    """Mirror production header/segment/reserve/addressability admission.

    This is allocation-free sizing only. Loaded allocation success and actual
    page-table/allocator overhead still require host measurement.
    """
    if (
            type(partition_bytes) is not int or partition_bytes <= 0 or
            partition_bytes > (1 << 64) - 1 or
            partition_bytes % BLOCK_BYTES or
            type(size_t_max) is not int or size_t_max <= 0):
        return None
    total_blocks = partition_bytes // BLOCK_BYTES
    if total_blocks <= 1:
        return None
    physical_blocks = (
        (total_blocks - 1) // SEGMENT_BLOCKS) * SEGMENT_BLOCKS
    if (
            physical_blocks < 3 * SEGMENT_BLOCKS or
            physical_blocks > (1 << 32) - 1 or
            physical_blocks * 2 > size_t_max):
        return None

    def admitted(logical_pages: int) -> bool:
        if (
                logical_pages <= 0 or logical_pages > (1 << 32) - 1 or
                logical_pages * 16 > size_t_max):
            return False
        reserve_blocks = max(
            (logical_pages + 7) // 8, MINIMUM_GC_RESERVE_BLOCKS)
        if reserve_blocks >= physical_blocks:
            return False
        foreground_blocks = (
            (physical_blocks - reserve_blocks) // SEGMENT_BLOCKS
        ) * SEGMENT_BLOCKS
        return (
            logical_pages + FOREGROUND_HEADROOM_BLOCKS <= foreground_blocks)

    low, high, maximum = 1, physical_blocks, 0
    while low <= high:
        middle = low + (high - low) // 2
        if admitted(middle):
            maximum = middle
            low = middle + 1
        else:
            high = middle - 1
    return maximum or None


def _median(values: list[int]) -> int:
    if not values or any(type(value) is not int for value in values):
        raise ValueError("metadata RAM median input is invalid")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    total = ordered[middle - 1] + ordered[middle]
    if total % 2:
        raise ValueError("metadata RAM median is not integral")
    return total // 2


def validate_metadata_ram_trace(
        trace: Any, *, source_sha: str, mapper_uuid: str,
        expected_peak_ram_bytes: int | None = None) -> dict[str, int]:
    """Validate chronology and derive the conservative whole-host RAM peak.

    The frozen methodology samples /proc/meminfo every 100 ms. The qualifying
    peak is baseline-median MemAvailable minus the minimum MemAvailable while
    the mapper exists/workloads run. SUnreclaim and VmallocUsed are retained
    for provenance/recovery checks; they are not added to MemAvailable delta.
    """
    if not isinstance(trace, dict) or set(trace) != {
            "schema", "capture", "scope", "source_sha", "mapper_uuid",
            "host_boot_id", "sampling_interval_ns", "meminfo_unit", "samples"}:
        raise ValueError("metadata RAM trace fields are incomplete")
    if (
            trace["schema"] != "swapz-metadata-ram-samples-v1" or
            trace["capture"] != "serialized-loaded-host" or
            trace["scope"] !=
            "whole-host-conservative-metadata-and-target-ram" or
            trace["meminfo_unit"] != "kB" or
            not isinstance(source_sha, str) or
            not SOURCE_SHA.fullmatch(source_sha) or
            trace["source_sha"] != source_sha or
            not isinstance(mapper_uuid, str) or
            not MAPPER_UUID.fullmatch(mapper_uuid) or
            trace["mapper_uuid"] != mapper_uuid or
            not isinstance(trace["host_boot_id"], str) or
            not BOOT_ID.fullmatch(trace["host_boot_id"])):
        raise ValueError("metadata RAM trace provenance is invalid")
    if trace["sampling_interval_ns"] != SAMPLING_INTERVAL_NS:
        raise ValueError("metadata RAM trace must declare 100 ms sampling")

    samples = trace["samples"]
    minimum_samples = sum(MINIMUM_PHASE_SAMPLES.values())
    if (
            not isinstance(samples, list) or
            not minimum_samples <= len(samples) <= 1_000_000):
        raise ValueError("metadata RAM trace is missing phase samples")

    phase_index = 0
    phase_samples: dict[str, list[dict[str, Any]]] = {
        phase: [] for phase in PHASES
    }
    previous_monotonic = None
    previous_utc = None
    for sample in samples:
        if not isinstance(sample, dict) or set(sample) != SAMPLE_FIELDS:
            raise ValueError("metadata RAM sample fields are invalid")
        phase = sample["phase"]
        if not isinstance(phase, str) or phase not in PHASES:
            raise ValueError("metadata RAM sample phase is invalid")
        next_index = PHASES.index(phase)
        if next_index < phase_index or next_index > phase_index + 1:
            raise ValueError("metadata RAM trace phase order is invalid")
        phase_index = next_index

        monotonic_ns = sample["monotonic_ns"]
        mem_available_kib = sample["mem_available_kib"]
        s_unreclaim_kib = sample["s_unreclaim_kib"]
        vmalloc_used_kib = sample["vmalloc_used_kib"]
        utc_text = sample["timestamp_utc"]
        maximum_kib = ((1 << 64) - 1) // MEMINFO_UNIT_BYTES
        if (
                type(monotonic_ns) is not int or monotonic_ns <= 0 or
                type(mem_available_kib) is not int or
                not 0 < mem_available_kib <= maximum_kib or
                type(s_unreclaim_kib) is not int or
                not 0 <= s_unreclaim_kib <= maximum_kib or
                type(vmalloc_used_kib) is not int or
                not 0 <= vmalloc_used_kib <= maximum_kib or
                type(sample["mapper_present"]) is not bool or
                not isinstance(utc_text, str) or
                not UTC_TIME.fullmatch(utc_text)):
            raise ValueError("metadata RAM sample counters or timestamp invalid")
        try:
            utc_time = datetime.datetime.fromisoformat(
                utc_text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("metadata RAM sample UTC timestamp invalid") from exc
        if previous_monotonic is not None:
            elapsed_ns = monotonic_ns - previous_monotonic
            if (
                    elapsed_ns < SAMPLING_INTERVAL_NS // 2 or
                    elapsed_ns > 3 * SAMPLING_INTERVAL_NS):
                raise ValueError("metadata RAM sample cadence is invalid")
            wall_elapsed_ns = int(
                (utc_time - previous_utc).total_seconds() * 1_000_000_000)
            if (
                    wall_elapsed_ns < 0 or
                    abs(wall_elapsed_ns - elapsed_ns) > 500_000_000):
                raise ValueError(
                    "metadata RAM sample UTC/monotonic clocks disagree")
        previous_monotonic = monotonic_ns
        previous_utc = utc_time
        phase_samples[phase].append(sample)

    for phase, minimum in MINIMUM_PHASE_SAMPLES.items():
        if len(phase_samples[phase]) < minimum:
            raise ValueError(
                "metadata RAM trace lacks baseline/init/steady/GC/teardown "
                "observations")

    baseline = phase_samples["baseline"]
    if any(sample["mapper_present"] for sample in baseline):
        raise ValueError("metadata RAM baseline was sampled with mapper present")
    if (baseline[-1]["monotonic_ns"] - baseline[0]["monotonic_ns"] <
            900_000_000):
        raise ValueError("metadata RAM baseline is shorter than one second")

    initialization = phase_samples["initialization"]
    seen_mapper = False
    for sample in initialization:
        if sample["mapper_present"]:
            seen_mapper = True
        elif seen_mapper:
            raise ValueError("metadata RAM initialization mapper state regressed")
    if not initialization[-1]["mapper_present"]:
        raise ValueError("metadata RAM initialization never observed mapper")

    for phase in ("steady", "gc"):
        if any(not sample["mapper_present"] for sample in phase_samples[phase]):
            raise ValueError(
                f"metadata RAM {phase} phase lost mapper identity")

    teardown = phase_samples["teardown"]
    if not teardown[0]["mapper_present"]:
        raise ValueError("metadata RAM teardown started after mapper disappeared")
    first_absent = next(
        (index for index, sample in enumerate(teardown)
         if not sample["mapper_present"]), None)
    if first_absent is None:
        raise ValueError("metadata RAM teardown never observed mapper removal")
    if any(sample["mapper_present"] for sample in teardown[first_absent:]):
        raise ValueError("metadata RAM mapper reappeared during teardown")
    absent_teardown = teardown[first_absent:]
    if (
            len(absent_teardown) < 21 or
            absent_teardown[-1]["monotonic_ns"] -
            absent_teardown[0]["monotonic_ns"] < 2_000_000_000):
        raise ValueError(
            "metadata RAM teardown lacks two seconds of quiescent recovery")

    baseline_available_kib = [
        sample["mem_available_kib"] for sample in baseline]
    baseline_median_available_kib = _median(baseline_available_kib)
    post_baseline = [
        sample for phase in PHASES[1:] for sample in phase_samples[phase]]
    minimum_sample = min(
        post_baseline, key=lambda sample: sample["mem_available_kib"])
    peak_ram_bytes = (
        baseline_median_available_kib - minimum_sample["mem_available_kib"]
    ) * MEMINFO_UNIT_BYTES
    if peak_ram_bytes <= 0 or not minimum_sample["mapper_present"]:
        raise ValueError(
            "metadata RAM peak was not observed while mapper was present")
    if (
            expected_peak_ram_bytes is not None and
            (type(expected_peak_ram_bytes) is not int or
             expected_peak_ram_bytes <= 0 or
             expected_peak_ram_bytes != peak_ram_bytes)):
        raise ValueError("metadata RAM peak is not derived from raw samples")

    # Use the last second of target-absent samples to prove the whole-host
    # counters returned to the pre-create envelope. This is intentionally
    # fail-closed on a noisy/non-quiescent host rather than manufacturing PASS.
    recovery = absent_teardown[-11:]
    if (
            _median([sample["mem_available_kib"] for sample in recovery]) <
            min(baseline_available_kib) or
            _median([sample["s_unreclaim_kib"] for sample in recovery]) >
            max(sample["s_unreclaim_kib"] for sample in baseline) or
            _median([sample["vmalloc_used_kib"] for sample in recovery]) >
            max(sample["vmalloc_used_kib"] for sample in baseline)):
        raise ValueError(
            "metadata RAM teardown did not recover the pre-create envelope")

    return {
        "peak_ram_bytes": peak_ram_bytes,
        "baseline_median_mem_available_bytes":
            baseline_median_available_kib * MEMINFO_UNIT_BYTES,
        "minimum_mem_available_bytes":
            minimum_sample["mem_available_kib"] * MEMINFO_UNIT_BYTES,
        "baseline_samples": len(baseline),
        "teardown_samples": len(teardown),
        "sample_count": len(samples),
    }
