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
MAP_RECORD_BYTES = 16
PHYSICAL_LIVENESS_RECORD_BYTES = 2
SAMPLING_INTERVAL_NS = 100_000_000
MEMINFO_UNIT_BYTES = 1024
CLOCK_AGREEMENT_TOLERANCE_NS = 500_000_000
UNIX_EPOCH_ORDINAL = datetime.date(1970, 1, 1).toordinal()
SIZE_T_MAX = (1 << (8 * struct.calcsize("P"))) - 1
PHASES = ("baseline", "initialization", "steady", "gc", "teardown")
PHASE_STAGES = {
    "baseline": 0,
    "initialization": 1,
    # GC can recur throughout the sustained workload; a later steady sample
    # must not be rejected merely because an earlier interval observed GC.
    "steady": 2,
    "gc": 2,
    "teardown": 3,
}
MINIMUM_PHASE_SAMPLES = {
    "baseline": 11,
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
HOST_UTC_TIME = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,9})?(?:Z|\+00:00)"
)
SAMPLE_FIELDS = {
    "phase", "monotonic_ns", "timestamp_utc", "mem_available_kib",
    "s_unreclaim_kib", "vmalloc_used_kib", "mapper_present",
}
MEMINFO_FIELDS = {
    "MemAvailable": "mem_available_kib",
    "SUnreclaim": "s_unreclaim_kib",
    "VmallocUsed": "vmalloc_used_kib",
}


def parse_meminfo_counters(text: Any) -> dict[str, int]:
    """Parse the required /proc/meminfo counters without unit coercion."""
    if not isinstance(text, str) or not text:
        raise ValueError("meminfo evidence is empty")
    values: dict[str, int] = {}
    if len(text) > 32 * 1024:
        raise ValueError("meminfo evidence exceeds 32768-byte input bound")
    maximum_kib = ((1 << 64) - 1) // MEMINFO_UNIT_BYTES
    for line in text.splitlines():
        # Even an indented counter is a malformed required field, not an
        # ignorable extra line that could conceal a conflicting value.
        # Whitespace before its colon can conceal a contradictory duplicate.
        name_match = re.match(
            r"[ \t]*(MemAvailable|SUnreclaim|VmallocUsed)(?=[: \t]|$)", line)
        if name_match is None:
            continue
        match = re.fullmatch(
            r"(MemAvailable|SUnreclaim|VmallocUsed):[ \t]+([0-9]+)[ \t]+kB",
            line)
        if match is None:
            raise ValueError(
                f"malformed meminfo counter: {name_match.group(1)}")
        source_name, value_text = match.groups()
        destination = MEMINFO_FIELDS[source_name]
        if destination in values:
            raise ValueError(f"duplicate meminfo counter: {source_name}")
        if len(value_text) > 20:
            raise ValueError(f"meminfo counter overflows bytes: {source_name}")
        value = int(value_text, 10)
        if value > maximum_kib:
            raise ValueError(f"meminfo counter overflows bytes: {source_name}")
        values[destination] = value
    if set(values) != set(MEMINFO_FIELDS.values()):
        raise ValueError("required meminfo counters are missing or use wrong units")
    if values["mem_available_kib"] <= 0:
        raise ValueError("MemAvailable must be positive")
    return values


MAX_UINT32 = (1 << 32) - 1
MAX_UINT64 = (1 << 64) - 1
CAPACITY_INDEX_ELEMENT_BYTES = {
    "logical_pages": (MAP_RECORD_BYTES, 4, 4),
    "physical_blocks": (PHYSICAL_LIVENESS_RECORD_BYTES, 1, 1),
    "segments": (4, 4, 2, 4, 4, 4, 4, 4, 4, 1, 1),
}


def _checked_product(first: int, second: int, limit: int) -> int | None:
    """Model an unsigned allocation-length multiplication without wrapping."""
    if (any(type(value) is not int or value < 0
            for value in (first, second, limit)) or
            (first and second > limit // first)):
        return None
    return first * second


def _checked_sum(first: int, second: int, limit: int) -> int | None:
    """Model an unsigned addition without wrapping."""
    if (any(type(value) is not int or value < 0
            for value in (first, second, limit)) or
            second > limit or first > limit - second):
        return None
    return first + second


def capacity_index_estimate(
        logical_pages: Any, physical_blocks: Any, *,
        size_t_max: int = SIZE_T_MAX) -> dict[str, int] | None:
    """Predict current capacity-index payload/page-rounded bytes only.

    This mirrors the 17 source-derived capacity-scaled arrays. It is an
    allocation-length model, not constructor-success or host-RAM evidence.
    """
    if (
            type(logical_pages) is not int or
            not 0 < logical_pages <= MAX_UINT32 or
            type(physical_blocks) is not int or
            not 0 < physical_blocks <= MAX_UINT32 or
            physical_blocks % SEGMENT_BLOCKS or
            type(size_t_max) is not int or
            not 0 < size_t_max <= MAX_UINT64):
        return None
    dimensions = {
        "logical_pages": logical_pages,
        "physical_blocks": physical_blocks,
        "segments": physical_blocks // SEGMENT_BLOCKS,
    }
    payload_bytes = 0
    page_rounded_bytes = 0
    array_count = 0
    for dimension, widths in CAPACITY_INDEX_ELEMENT_BYTES.items():
        count = dimensions[dimension]
        for element_bytes in widths:
            allocation_bytes = _checked_product(
                count, element_bytes, size_t_max)
            if allocation_bytes is None:
                return None
            payload_bytes = _checked_sum(
                payload_bytes, allocation_bytes, MAX_UINT64)
            rounding_input = _checked_sum(
                allocation_bytes, BLOCK_BYTES - 1, MAX_UINT64)
            if payload_bytes is None or rounding_input is None:
                return None
            rounded_bytes = _checked_product(
                rounding_input // BLOCK_BYTES, BLOCK_BYTES, MAX_UINT64)
            if rounded_bytes is None:
                return None
            page_rounded_bytes = _checked_sum(
                page_rounded_bytes, rounded_bytes, MAX_UINT64)
            if page_rounded_bytes is None:
                return None
            array_count += 1
    return {
        "array_count": array_count,
        "payload_bytes": payload_bytes,
        "page_rounded_bytes": page_rounded_bytes,
    }


def maximum_logical_pages_for_partition(
        partition_bytes: Any, *, size_t_max: int = SIZE_T_MAX) -> int | None:
    """Mirror production header/segment/reserve/addressability admission.

    Arithmetic is bounded explicitly, even though Python integers cannot
    overflow. This predicts index lengths, never successful kernel allocation
    or measured host peak RAM.
    """
    if (
            type(partition_bytes) is not int or partition_bytes <= 0 or
            partition_bytes > MAX_UINT64 or
            partition_bytes % BLOCK_BYTES or
            type(size_t_max) is not int or
            size_t_max <= 0 or size_t_max > MAX_UINT64):
        return None
    total_blocks = partition_bytes // BLOCK_BYTES
    if total_blocks <= 1:
        return None
    physical_blocks = (
        (total_blocks - 1) // SEGMENT_BLOCKS) * SEGMENT_BLOCKS
    if (
            physical_blocks < 3 * SEGMENT_BLOCKS or
            physical_blocks > MAX_UINT32 or
            _checked_product(
                physical_blocks, PHYSICAL_LIVENESS_RECORD_BYTES,
                size_t_max) is None):
        return None

    def admitted(logical_pages: int) -> bool:
        if (
                not 0 < logical_pages <= MAX_UINT32 or
                _checked_product(
                    logical_pages, MAP_RECORD_BYTES, size_t_max) is None):
            return False
        # The production header divides before addition to avoid u32 wrap.
        reserve_blocks = max(
            logical_pages // 8 + (logical_pages % 8 != 0),
            MINIMUM_GC_RESERVE_BLOCKS)
        if reserve_blocks >= physical_blocks:
            return False
        foreground_blocks = (
            (physical_blocks - reserve_blocks) // SEGMENT_BLOCKS
        ) * SEGMENT_BLOCKS
        required_blocks = _checked_sum(
            logical_pages, FOREGROUND_HEADROOM_BLOCKS, MAX_UINT64)
        return required_blocks is not None and required_blocks <= foreground_blocks

    low, high, maximum = 1, physical_blocks, 0
    while low <= high:
        middle = low + (high - low) // 2
        if admitted(middle):
            maximum = middle
            low = middle + 1
        else:
            high = middle - 1
    return maximum or None


def _median_twice(values: list[int]) -> int:
    """Return exactly twice the integer-sample median without float rounding."""
    if not values or any(type(value) is not int for value in values):
        raise ValueError("metadata RAM median input is invalid")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return 2 * ordered[middle]
    return ordered[middle - 1] + ordered[middle]


def _bounded_observed(value: Any) -> str:
    """Bound malformed evidence diagnostics without exposing raw artifacts."""
    if type(value) is int:
        return str(value) if value.bit_length() <= 64 else "<integer_over_64_bits>"
    if type(value) in (bool, float) or value is None:
        return repr(value)
    if isinstance(value, str):
        # Untrusted evidence can contain private trace content. Report only
        # its size, never even a short prefix of the supplied string.
        return f"<string_length={len(value)}>"
    return f"<{type(value).__name__}>"


def _parse_utc_ns(value: Any, pattern: re.Pattern[str]) -> int | None:
    """Parse canonical UTC text into exact integer nanoseconds."""
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        return None
    core = value[:-1] if value.endswith("Z") else value[:-6]
    fraction_ns = 0
    if len(core) > 19:
        fraction_ns = int(core[20:].ljust(9, "0"), 10)
    try:
        observed = datetime.datetime(
            int(core[0:4]), int(core[5:7]), int(core[8:10]),
            int(core[11:13]), int(core[14:16]), int(core[17:19]))
    except ValueError:
        return None
    whole_seconds = (
        (observed.toordinal() - UNIX_EPOCH_ORDINAL) * 86400 +
        observed.hour * 3600 + observed.minute * 60 + observed.second)
    return whole_seconds * 1_000_000_000 + fraction_ns


def _timedelta_ns(value: datetime.timedelta) -> int:
    """Convert a timedelta to nanoseconds without floating-point rounding."""
    return (
        (value.days * 86400 + value.seconds) * 1_000_000_000 +
        value.microseconds * 1000)


def metadata_ram_arm_binding(swapz_arm: Any) -> dict[str, Any]:
    """Extract the minimum sustained-arm chronology needed to revalidate RAM."""
    if not isinstance(swapz_arm, dict):
        raise ValueError("metadata RAM arm binding requires a swapz arm")
    started = swapz_arm.get("arm_started_monotonic_ns")
    finished = swapz_arm.get("arm_finished_monotonic_ns")
    intervals = swapz_arm.get("sustained_intervals")
    if (
            type(started) is not int or started <= 0 or
            type(finished) is not int or finished <= started or
            finished > MAX_UINT64 or
            not isinstance(intervals, list) or
            not 0 < len(intervals) <= 1_000_000):
        raise ValueError("metadata RAM arm chronology is missing")
    gc_activity_intervals = []
    for row in intervals:
        if not isinstance(row, dict):
            raise ValueError("metadata RAM arm telemetry interval is invalid")
        interval_start = row.get("start_monotonic_ns")
        interval_end = row.get("end_monotonic_ns")
        gc = row.get("gc")
        if (
                type(interval_start) is not int or
                type(interval_end) is not int or
                interval_start < started or interval_end > MAX_UINT64 or
                interval_end <= interval_start or
                interval_end > finished or not isinstance(gc, dict)):
            raise ValueError("metadata RAM arm telemetry chronology is invalid")
        counters = {}
        for field in ("gc_wall_ns", "gc_victims", "gc_pages"):
            value = gc.get(field)
            if type(value) is not int or not 0 <= value <= MAX_UINT64:
                raise ValueError(
                    "metadata RAM arm GC counters are missing or malformed")
            counters[field] = value
        if any(counters.values()):
            gc_activity_intervals.append({
                "start_monotonic_ns": interval_start,
                "end_monotonic_ns": interval_end,
                **counters,
            })
    if not gc_activity_intervals:
        raise ValueError("metadata RAM arm has no measured GC activity interval")
    return {
        "arm_started_monotonic_ns": started,
        "arm_finished_monotonic_ns": finished,
        "gc_activity_intervals": gc_activity_intervals,
    }


def validate_metadata_ram_arm_binding(trace: Any, binding: Any) -> None:
    """Revalidate phase chronology against sealed sustained-arm GC evidence."""
    if not isinstance(binding, dict) or set(binding) != {
            "arm_started_monotonic_ns", "arm_finished_monotonic_ns",
            "gc_activity_intervals"}:
        raise ValueError("metadata RAM arm binding fields are invalid")
    started = binding["arm_started_monotonic_ns"]
    finished = binding["arm_finished_monotonic_ns"]
    windows = binding["gc_activity_intervals"]
    if (
            type(started) is not int or started <= 0 or
            type(finished) is not int or finished <= started or
            finished > MAX_UINT64 or
            not isinstance(windows, list) or
            not 0 < len(windows) <= 1_000_000):
        raise ValueError("metadata RAM arm binding chronology is invalid")
    previous_end = None
    for window in windows:
        if not isinstance(window, dict) or set(window) != {
                "start_monotonic_ns", "end_monotonic_ns",
                "gc_wall_ns", "gc_victims", "gc_pages"}:
            raise ValueError("metadata RAM GC activity window is invalid")
        window_start = window["start_monotonic_ns"]
        window_end = window["end_monotonic_ns"]
        counters = [
            window["gc_wall_ns"], window["gc_victims"], window["gc_pages"]]
        if (
                type(window_start) is not int or
                type(window_end) is not int or
                window_start < started or window_end <= window_start or
                window_end > finished or window_end > MAX_UINT64 or
                any(type(value) is not int or
                    not 0 <= value <= MAX_UINT64 for value in counters) or
                not any(counters) or
                (previous_end is not None and window_start < previous_end)):
            raise ValueError("metadata RAM GC activity window is malformed")
        previous_end = window_end

    samples = trace.get("samples") if isinstance(trace, dict) else None
    if not isinstance(samples, list) or not samples:
        raise ValueError("metadata RAM trace samples are missing")
    phases = {}
    for phase in PHASES:
        values = [
            sample.get("monotonic_ns") for sample in samples
            if isinstance(sample, dict) and sample.get("phase") == phase]
        if (
                not values or
                any(type(value) is not int or value <= 0 for value in values)):
            raise ValueError("metadata RAM trace phase chronology is incomplete")
        phases[phase] = values
    if (
            max(phases["initialization"]) > started or
            any(value < started or value > finished
                for phase in ("steady", "gc") for value in phases[phase]) or
            min(phases["teardown"]) < finished):
        raise ValueError("metadata RAM phases do not bind to sustained arm")
    # Both the validated sample timeline and measured GC windows are ordered.
    # Walk them once rather than scanning every window for every GC sample.
    window_index = 0
    previous_sample_time = None
    for sample_time in phases["gc"]:
        if (previous_sample_time is not None and
                sample_time <= previous_sample_time):
            raise ValueError("metadata RAM GC sample chronology is invalid")
        previous_sample_time = sample_time
        while (window_index < len(windows) and
               windows[window_index]["end_monotonic_ns"] < sample_time):
            window_index += 1
        if (window_index == len(windows) or
                sample_time < windows[window_index]["start_monotonic_ns"]):
            raise ValueError(
                "metadata RAM GC sample lacks measured target GC activity")


def validate_metadata_ram_host_binding(trace: Any, binding: Any) -> None:
    """Bind a serialized RAM trace to the sealed physical-host time window."""
    if not isinstance(binding, dict) or set(binding) != {
            "host_boot_id", "host_before_captured_at_utc",
            "host_after_captured_at_utc", "memory_total_bytes"}:
        raise ValueError("metadata RAM host binding fields are invalid")
    boot_id = binding["host_boot_id"]
    total_bytes = binding["memory_total_bytes"]
    if not isinstance(boot_id, str) or not BOOT_ID.fullmatch(boot_id):
        raise ValueError(
            "metadata RAM host binding identity is invalid: "
            f"metric=host_boot_id observed={_bounded_observed(boot_id)} "
            "expected=canonical_boot_id")
    # The sealed snapshot derives this field from /proc/meminfo MemTotal,
    # whose source unit is kB. Reject sub-KiB precision that the producer
    # cannot have measured rather than silently flooring it below.
    if (
            type(total_bytes) is not int or
            not MEMINFO_UNIT_BYTES <= total_bytes <= MAX_UINT64 or
            total_bytes % MEMINFO_UNIT_BYTES):
        raise ValueError(
            "metadata RAM host binding memory total is invalid: "
            f"metric=memory_total_bytes observed={_bounded_observed(total_bytes)} "
            f"minimum={MEMINFO_UNIT_BYTES} maximum={MAX_UINT64} "
            f"multiple={MEMINFO_UNIT_BYTES}")
    if any(
            not isinstance(binding[field], str) or
            HOST_UTC_TIME.fullmatch(binding[field]) is None
            for field in ("host_before_captured_at_utc",
                          "host_after_captured_at_utc")):
        raise ValueError(
            "metadata RAM host binding requires canonical UTC timestamps")
    before_ns = _parse_utc_ns(
        binding["host_before_captured_at_utc"], HOST_UTC_TIME)
    after_ns = _parse_utc_ns(
        binding["host_after_captured_at_utc"], HOST_UTC_TIME)
    if before_ns is None or after_ns is None or after_ns < before_ns:
        raise ValueError("metadata RAM host binding time envelope is invalid")
    samples = trace.get("samples") if isinstance(trace, dict) else None
    if not isinstance(samples, list) or not 0 < len(samples) <= 1_000_000:
        raise ValueError(
            "metadata RAM trace host samples are missing or excessive: "
            f"metric=sample_count expected=1..1000000 "
            f"observed={len(samples) if isinstance(samples, list) else '<not_list>'}")
    if trace.get("host_boot_id") != boot_id:
        raise ValueError(
            "metadata RAM trace host boot binding mismatch: "
            f"metric=host_boot_id observed={_bounded_observed(trace.get('host_boot_id'))} "
            "expected=host_binding.host_boot_id required=same_loaded_host_boot")
    try:
        first_text = samples[0]["timestamp_utc"]
        last_text = samples[-1]["timestamp_utc"]
    except (KeyError, TypeError) as exc:
        raise ValueError("metadata RAM trace time envelope is invalid") from exc
    first_ns = _parse_utc_ns(first_text, UTC_TIME)
    last_ns = _parse_utc_ns(last_text, UTC_TIME)
    if (
            first_ns is None or last_ns is None or
            not before_ns <= first_ns < last_ns <= after_ns):
        raise ValueError("metadata RAM trace falls outside host snapshot window")
    maximum_host_kib = total_bytes // MEMINFO_UNIT_BYTES
    for sample_index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            raise ValueError(
                "metadata RAM host sample is malformed: "
                f"metric=samples[{sample_index}] expected=object "
                f"observed={_bounded_observed(sample)}")
        # Both MemAvailable and unreclaimable slab represent physical RAM.
        # Unlike VmallocUsed (virtual address space), neither may exceed the
        # independently sealed total physical host memory.
        for field, minimum in (("mem_available_kib", 1),
                               ("s_unreclaim_kib", 0)):
            value = sample.get(field)
            if (type(value) is not int or
                    not minimum <= value <= maximum_host_kib):
                raise ValueError(
                    "metadata RAM sample contradicts host physical memory: "
                    f"metric=samples[{sample_index}].{field} "
                    f"observed={_bounded_observed(value)} minimum={minimum} "
                    f"maximum={maximum_host_kib} "
                    f"memory_total_bytes={total_bytes}")
        # MemAvailable is a derived estimate from independently changing VM
        # counters, not an additive partition of MemTotal. Keep the exact
        # physical bound on each counter, but do not invent a cross-field sum
        # invariant with SUnreclaim.


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
    if trace["meminfo_unit"] != "kB":
        raise ValueError(
            "metadata RAM sample unit declaration is invalid: "
            f"metric=meminfo_unit observed={_bounded_observed(trace['meminfo_unit'])} "
            "expected=kB")
    # A rootless or synthetic label must not be promoted to loaded-host
    # evidence. Matching strings alone do not authenticate a host capture.
    for field, expected in (
            ("capture", "serialized-loaded-host"),
            ("scope", "whole-host-conservative-metadata-and-target-ram")):
        if trace[field] != expected:
            raise ValueError(
                "metadata RAM trace capture scope is invalid: "
                f"metric={field} observed={_bounded_observed(trace[field])} "
                f"expected={expected} first_failed_phase=provenance")
    if (
            trace["schema"] != "swapz-metadata-ram-samples-v1" or
            trace["meminfo_unit"] != "kB" or
            not isinstance(source_sha, str) or
            not SOURCE_SHA.fullmatch(source_sha) or
            not isinstance(mapper_uuid, str) or
            not MAPPER_UUID.fullmatch(mapper_uuid) or
            not isinstance(trace["host_boot_id"], str) or
            not BOOT_ID.fullmatch(trace["host_boot_id"])):
        raise ValueError("metadata RAM trace provenance is invalid")
    if trace["mapper_uuid"] != mapper_uuid:
        raise ValueError(
            "metadata RAM trace mapper binding mismatch: "
            f"metric=mapper_uuid observed={_bounded_observed(trace['mapper_uuid'])} "
            "expected=exact_mapper_uuid")
    if trace["source_sha"] != source_sha:
        raise ValueError(
            "metadata RAM trace source binding mismatch: "
            f"metric=source_sha observed={_bounded_observed(trace['source_sha'])} "
            f"expected={source_sha} required=exact_release_source")
    if (
            type(trace["sampling_interval_ns"]) is not int or
            trace["sampling_interval_ns"] != SAMPLING_INTERVAL_NS):
        raise ValueError(
            "metadata RAM trace sampling declaration is invalid: "
            f"metric=sampling_interval_ns "
            f"observed={_bounded_observed(trace['sampling_interval_ns'])} "
            f"required={SAMPLING_INTERVAL_NS}")

    samples = trace["samples"]
    minimum_samples = sum(MINIMUM_PHASE_SAMPLES.values())
    if not isinstance(samples, list):
        raise ValueError("metadata RAM trace samples are missing")
    if not minimum_samples <= len(samples) <= 1_000_000:
        first_failed_phase = "unknown"
        if len(samples) < minimum_samples:
            phase_sample_counts = {phase: 0 for phase in PHASES}
            for sample in samples:
                if isinstance(sample, dict):
                    phase = sample.get("phase")
                    if isinstance(phase, str) and phase in phase_sample_counts:
                        phase_sample_counts[phase] += 1
            first_failed_phase = next(
                (phase for phase, minimum in MINIMUM_PHASE_SAMPLES.items()
                 if phase_sample_counts[phase] < minimum), "unknown")
        raise ValueError(
            "metadata RAM trace sample count is invalid: "
            f"metric=sample_count observed={len(samples)} "
            f"minimum={minimum_samples} maximum=1000000 "
            f"missing_samples={max(0, minimum_samples - len(samples))} "
            f"first_failed_phase={first_failed_phase}")

    phase_stage = 0
    phase_samples: dict[str, list[dict[str, Any]]] = {
        phase: [] for phase in PHASES
    }
    previous_monotonic = None
    previous_utc_ns = None
    first_utc_ns = None
    for sample_index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            raise ValueError(
                "metadata RAM sample fields are invalid: "
                f"metric=samples[{sample_index}] expected=object "
                f"observed={_bounded_observed(sample)}")
        if set(sample) != SAMPLE_FIELDS:
            missing = ",".join(sorted(SAMPLE_FIELDS - set(sample)))
            unexpected_count = len(set(sample) - SAMPLE_FIELDS)
            raise ValueError(
                "metadata RAM sample fields are invalid: "
                f"metric=samples[{sample_index}].fields "
                f"missing={missing or 'none'} unexpected_count={unexpected_count}")
        phase = sample["phase"]
        if not isinstance(phase, str) or phase not in PHASES:
            raise ValueError(
                "metadata RAM sample phase is invalid: "
                f"metric=samples[{sample_index}].phase "
                f"observed={_bounded_observed(phase)} expected=known_phase")
        next_stage = PHASE_STAGES[phase]
        if next_stage < phase_stage or next_stage > phase_stage + 1:
            raise ValueError(
                "metadata RAM trace phase order is invalid: "
                f"metric=samples[{sample_index}].phase observed={phase} "
                "required=baseline_then_initialization_then_sustained_then_teardown")
        phase_stage = next_stage

        monotonic_ns = sample["monotonic_ns"]
        mem_available_kib = sample["mem_available_kib"]
        s_unreclaim_kib = sample["s_unreclaim_kib"]
        vmalloc_used_kib = sample["vmalloc_used_kib"]
        utc_text = sample["timestamp_utc"]
        maximum_kib = ((1 << 64) - 1) // MEMINFO_UNIT_BYTES
        if (
                type(monotonic_ns) is not int or
                not 0 < monotonic_ns <= MAX_UINT64):
            raise ValueError(
                "metadata RAM sample counter is invalid: "
                f"metric=monotonic_ns observed={_bounded_observed(monotonic_ns)} "
                f"minimum=1 maximum={MAX_UINT64}")
        for metric, value, minimum in (
                ("MemAvailable_kib", mem_available_kib, 1),
                ("SUnreclaim_kib", s_unreclaim_kib, 0),
                ("VmallocUsed_kib", vmalloc_used_kib, 0)):
            if (
                    type(value) is not int or
                    not minimum <= value <= maximum_kib):
                raise ValueError(
                    "metadata RAM sample counter is invalid: "
                    f"metric={metric} observed={_bounded_observed(value)} "
                    f"minimum={minimum} maximum={maximum_kib}")
        if type(sample["mapper_present"]) is not bool:
            raise ValueError(
                "metadata RAM mapper-presence evidence is invalid: "
                f"metric=mapper_present observed={_bounded_observed(sample['mapper_present'])} "
                "required=boolean")
        if not isinstance(utc_text, str) or not UTC_TIME.fullmatch(utc_text):
            raise ValueError(
                "metadata RAM sample timestamp is invalid: "
                f"metric=timestamp_utc observed={_bounded_observed(utc_text)} "
                "required=canonical_UTC_Z")
        utc_ns = _parse_utc_ns(utc_text, UTC_TIME)
        if utc_ns is None:
            raise ValueError(
                "metadata RAM sample UTC timestamp invalid: "
                f"metric=samples[{sample_index}].timestamp_utc "
                "expected=valid_calendar_UTC_Z")
        if first_utc_ns is None:
            first_utc_ns = utc_ns
        if previous_monotonic is not None:
            elapsed_ns = monotonic_ns - previous_monotonic
            if (
                    elapsed_ns < SAMPLING_INTERVAL_NS // 2 or
                    elapsed_ns > SAMPLING_INTERVAL_NS +
                                 SAMPLING_INTERVAL_NS // 2):
                raise ValueError(
                    "metadata RAM sample cadence is invalid: "
                    f"metric=monotonic_interval_ns observed={elapsed_ns} "
                    f"minimum={SAMPLING_INTERVAL_NS // 2} "
                    f"maximum={SAMPLING_INTERVAL_NS + SAMPLING_INTERVAL_NS // 2} "
                    f"first_failed_phase={phase} "
                    f"missing_samples={max(0, (elapsed_ns - SAMPLING_INTERVAL_NS // 2) // SAMPLING_INTERVAL_NS)}")
            wall_elapsed_ns = utc_ns - previous_utc_ns
            if (
                    wall_elapsed_ns <= 0 or
                    abs(wall_elapsed_ns - elapsed_ns) >
                    SAMPLING_INTERVAL_NS // 2):
                raise ValueError(
                    "metadata RAM sample UTC/monotonic clocks disagree: "
                    f"metric=interval_clock_delta_ns "
                    f"observed={abs(wall_elapsed_ns - elapsed_ns)} "
                    f"limit={SAMPLING_INTERVAL_NS // 2}")
        previous_monotonic = monotonic_ns
        previous_utc_ns = utc_ns
        phase_samples[phase].append(sample)

    # Per-interval jitter is tolerated, but it must not systematically turn
    # the declared 100 ms cadence into slower, under-sampled host evidence.
    # Use integer arithmetic to avoid rounding multi-hour trace durations.
    observed_span_ns = (
        samples[-1]["monotonic_ns"] - samples[0]["monotonic_ns"])
    expected_span_ns = (len(samples) - 1) * SAMPLING_INTERVAL_NS
    wall_span_ns = previous_utc_ns - first_utc_ns
    if abs(wall_span_ns - observed_span_ns) > CLOCK_AGREEMENT_TOLERANCE_NS:
        raise ValueError(
            "metadata RAM UTC/monotonic trace spans disagree: "
            f"metric=trace_clock_delta_ns "
            f"observed={abs(wall_span_ns - observed_span_ns)} "
            f"limit={CLOCK_AGREEMENT_TOLERANCE_NS}")
    if not (9 * expected_span_ns <= 10 * observed_span_ns <=
            11 * expected_span_ns):
        raise ValueError(
            "metadata RAM observed sampling cadence differs from 100 ms: "
            f"metric=monotonic_trace_span_ns observed={observed_span_ns} "
            f"expected={expected_span_ns} tolerance_percent=10")

    for phase, minimum in MINIMUM_PHASE_SAMPLES.items():
        if len(phase_samples[phase]) < minimum:
            raise ValueError(
                "metadata RAM trace lacks required phase observations: "
                f"metric={phase}_sample_count "
                f"observed={len(phase_samples[phase])} minimum={minimum} "
                f"missing_samples={minimum - len(phase_samples[phase])} "
                f"first_failed_phase={phase}")

    baseline = phase_samples["baseline"]
    if any(sample["mapper_present"] for sample in baseline):
        raise ValueError("metadata RAM baseline was sampled with mapper present")
    if (baseline[-1]["monotonic_ns"] - baseline[0]["monotonic_ns"] <
            1_000_000_000):
        raise ValueError("metadata RAM baseline is shorter than one second")

    initialization = phase_samples["initialization"]
    if initialization[0]["mapper_present"]:
        raise ValueError(
            "metadata RAM initialization did not start before mapper creation")
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
        raise ValueError(
            "metadata RAM mapper reappeared during teardown: "
            "metric=mapper_present observed=true "
            "required=false_after_first_removal")
    absent_teardown = teardown[first_absent:]
    if (
            len(absent_teardown) < 21 or
            absent_teardown[-1]["monotonic_ns"] -
            absent_teardown[0]["monotonic_ns"] < 2_000_000_000):
        raise ValueError(
            "metadata RAM teardown lacks two seconds of quiescent recovery")

    baseline_available_kib = [
        sample["mem_available_kib"] for sample in baseline]
    baseline_median_available_twice_kib = _median_twice(
        baseline_available_kib)
    # Constructor allocations occur before Device Mapper publishes the exact
    # UUID, so the qualifying target-lifecycle window starts with the first
    # initialization sample and ends with the last target-present teardown
    # sample. Post-removal recovery is intentionally excluded from the peak.
    lifecycle_samples = [
        *initialization,
        *phase_samples["steady"],
        *phase_samples["gc"],
        *teardown[:first_absent],
    ]
    minimum_sample = min(
        lifecycle_samples, key=lambda sample: sample["mem_available_kib"])
    peak_ram_bytes = (
        baseline_median_available_twice_kib * (MEMINFO_UNIT_BYTES // 2) -
        minimum_sample["mem_available_kib"] * MEMINFO_UNIT_BYTES)
    if peak_ram_bytes <= 0:
        raise ValueError(
            "metadata RAM peak was not observed during target lifecycle")
    if (
            expected_peak_ram_bytes is not None and
            (type(expected_peak_ram_bytes) is not int or
             not 0 < expected_peak_ram_bytes <= MAX_UINT64 or
             expected_peak_ram_bytes != peak_ram_bytes)):
        raise ValueError(
            "metadata RAM peak is not derived from raw samples: "
            f"metric=peak_ram_bytes observed={peak_ram_bytes} "
            f"reported={_bounded_observed(expected_peak_ram_bytes)} "
            f"maximum={MAX_UINT64}")

    # Use the last second of target-absent samples to prove the whole-host
    # counters returned to the pre-create envelope. This is intentionally
    # fail-closed on a noisy/non-quiescent host rather than manufacturing PASS.
    recovery_cutoff_ns = (
        absent_teardown[-1]["monotonic_ns"] - 1_000_000_000)
    recovery_start = max(
        index for index, sample in enumerate(absent_teardown)
        if sample["monotonic_ns"] <= recovery_cutoff_ns)
    recovery = absent_teardown[recovery_start:]
    # Compare robust medians on both sides: a single low MemAvailable or
    # high slab/vmalloc baseline outlier must not conceal a persistent leak.
    baseline_s_unreclaim_twice_kib = _median_twice([
        sample["s_unreclaim_kib"] for sample in baseline])
    baseline_vmalloc_used_twice_kib = _median_twice([
        sample["vmalloc_used_kib"] for sample in baseline])
    recovery_span_ns = (
        recovery[-1]["monotonic_ns"] - recovery[0]["monotonic_ns"])
    if recovery_span_ns < 1_000_000_000:
        raise ValueError(
            "metadata RAM teardown recovery evidence gap: "
            f"metric=recovery_span_ns observed={recovery_span_ns} "
            "required=1000000000")
    recovery_median_available_twice_kib = _median_twice([
        sample["mem_available_kib"] for sample in recovery])
    recovery_median_s_unreclaim_twice_kib = _median_twice([
        sample["s_unreclaim_kib"] for sample in recovery])
    recovery_median_vmalloc_used_twice_kib = _median_twice([
        sample["vmalloc_used_kib"] for sample in recovery])
    for metric, observed_twice_kib, baseline_twice_kib, recovered in (
            ("MemAvailable_median_twice_kib",
             recovery_median_available_twice_kib,
             baseline_median_available_twice_kib, "minimum"),
            ("SUnreclaim_median_twice_kib",
             recovery_median_s_unreclaim_twice_kib,
             baseline_s_unreclaim_twice_kib, "maximum"),
            ("VmallocUsed_median_twice_kib",
             recovery_median_vmalloc_used_twice_kib,
             baseline_vmalloc_used_twice_kib, "maximum")):
        if ((recovered == "minimum" and observed_twice_kib <
             baseline_twice_kib) or
                (recovered == "maximum" and observed_twice_kib >
                 baseline_twice_kib)):
            raise ValueError(
                "metadata RAM teardown did not recover the pre-create "
                f"envelope: metric={metric} observed={observed_twice_kib} "
                f"limit={baseline_twice_kib} evidence=last-second-median")

    # These are observed 100 ms sample-window maxima, not a prediction of
    # constructor allocation sizes or an unsampled instantaneous maximum.
    phase_peaks = {}
    for phase in ("initialization", "steady", "gc"):
        phase_minimum_available_kib = min(
            sample["mem_available_kib"] for sample in phase_samples[phase])
        phase_peaks[f"{phase}_peak_ram_bytes"] = max(
            0, baseline_median_available_twice_kib *
            (MEMINFO_UNIT_BYTES // 2) -
            phase_minimum_available_kib * MEMINFO_UNIT_BYTES)

    return {
        "peak_ram_bytes": peak_ram_bytes,
        **phase_peaks,
        "baseline_median_mem_available_bytes":
            baseline_median_available_twice_kib *
            (MEMINFO_UNIT_BYTES // 2),
        "minimum_mem_available_bytes":
            minimum_sample["mem_available_kib"] * MEMINFO_UNIT_BYTES,
        "baseline_samples": len(baseline),
        "initialization_samples": len(phase_samples["initialization"]),
        "steady_samples": len(phase_samples["steady"]),
        "gc_samples": len(phase_samples["gc"]),
        "teardown_samples": len(teardown),
        "recovery_samples": len(recovery),
        "recovery_span_ns": recovery_span_ns,
        "recovery_median_mem_available_bytes":
            recovery_median_available_twice_kib *
            (MEMINFO_UNIT_BYTES // 2),
        "recovery_median_s_unreclaim_bytes":
            recovery_median_s_unreclaim_twice_kib *
            (MEMINFO_UNIT_BYTES // 2),
        "recovery_median_vmalloc_used_bytes":
            recovery_median_vmalloc_used_twice_kib *
            (MEMINFO_UNIT_BYTES // 2),
        "sample_count": len(samples),
    }
