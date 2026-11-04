#!/usr/bin/env python3
"""Fail-closed, allocation-free validation of serialized loaded-host RAM traces.

This checks evidence shape and chronology; it does not measure kernel RAM or
turn rootless fixtures into a loaded-host qualification. A scalar peak alone
cannot establish a resource PASS.
"""
from __future__ import annotations

import datetime
import re
from typing import Any

PHASES = ("baseline", "initialization", "steady", "gc", "teardown")


def maximum_logical_pages_for_partition(partition_bytes: Any) -> int | None:
    """Model the production reserve/header/u32 admission without allocations.

    The loaded target still has to execute and measure this maximum. This is
    not a replacement for the kernel's authoritative geometry validator.
    """
    if type(partition_bytes) is not int or partition_bytes <= 0:
        return None
    total_blocks = partition_bytes // 4096
    physical_blocks = ((total_blocks - 1) // 256) * 256
    if physical_blocks < 3 * 256 or physical_blocks > (1 << 32) - 1:
        return None
    low, high, maximum = 1, physical_blocks, 0
    while low <= high:
        middle = low + (high - low) // 2
        reserve = max((middle + 7) // 8, 512)
        foreground = ((physical_blocks - reserve) // 256) * 256
        if middle + 256 <= foreground:
            maximum = middle
            low = middle + 1
        else:
            high = middle - 1
    if not maximum or maximum * 16 > (1 << 64) - 1:
        return None
    return maximum
BOOT_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
UTC_TIME = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,9})?Z"
)


def validate_metadata_ram_trace(
        trace: Any, *, source_sha: str, mapper_uuid: str,
        expected_peak_ram_bytes: int) -> None:
    """Raise ValueError unless all phases and resource recovery are observed.

    Each sample is host-collected, target-attributed resident bytes (including
    metadata allocation backing and page tables), never a model estimate.
    Monotonic timestamps constrain cadence; UTC timestamps identify evidence.
    The sampler must continue through ordinary removal of the owned mapper.
    """
    if not isinstance(trace, dict) or set(trace) != {
            "schema", "capture", "scope", "source_sha", "mapper_uuid",
            "host_boot_id", "sampling_interval_ns", "samples"}:
        raise ValueError("metadata RAM trace fields are incomplete")
    if (trace["schema"] != "swapz-metadata-ram-samples-v1" or
            trace["capture"] != "serialized-loaded-host" or
            trace["scope"] != "target-owned-resident-bytes-including-page-tables" or
            trace["source_sha"] != source_sha or
            not isinstance(mapper_uuid, str) or
            not mapper_uuid.startswith("SWAPZ-") or
            trace["mapper_uuid"] != mapper_uuid or
            not isinstance(trace["host_boot_id"], str) or
            not BOOT_ID.fullmatch(trace["host_boot_id"])):
        raise ValueError("metadata RAM trace provenance is invalid")
    interval = trace["sampling_interval_ns"]
    if type(interval) is not int or not 10_000_000 <= interval <= 1_000_000_000:
        raise ValueError("metadata RAM trace sampling interval is invalid")
    if type(expected_peak_ram_bytes) is not int or expected_peak_ram_bytes <= 0:
        raise ValueError("metadata RAM trace expected peak is invalid")
    samples = trace["samples"]
    if not isinstance(samples, list) or not 10 <= len(samples) <= 1_000_000:
        raise ValueError("metadata RAM trace is missing phase samples")

    phase_index = 0
    phase_counts = [0] * len(PHASES)
    peak = 0
    previous_monotonic = None
    previous_utc = None
    first_baseline = None
    last_baseline = None
    first_teardown = None
    last_teardown = None
    for sample in samples:
        if not isinstance(sample, dict) or set(sample) != {
                "phase", "monotonic_ns", "timestamp_utc", "ram_bytes"}:
            raise ValueError("metadata RAM sample fields are invalid")
        phase = sample["phase"]
        if not isinstance(phase, str) or phase not in PHASES:
            raise ValueError("metadata RAM sample phase is invalid")
        next_index = PHASES.index(phase)
        if next_index < phase_index or next_index > phase_index + 1:
            raise ValueError("metadata RAM trace phase order is invalid")
        phase_index = next_index
        timestamp_ns = sample["monotonic_ns"]
        ram_bytes = sample["ram_bytes"]
        utc_text = sample["timestamp_utc"]
        if (type(timestamp_ns) is not int or timestamp_ns <= 0 or
                type(ram_bytes) is not int or ram_bytes < 0 or
                not isinstance(utc_text, str) or
                not UTC_TIME.fullmatch(utc_text)):
            raise ValueError("metadata RAM sample timestamp or bytes invalid")
        try:
            utc_time = datetime.datetime.fromisoformat(
                utc_text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("metadata RAM sample UTC timestamp invalid") from exc
        if previous_monotonic is not None:
            elapsed_ns = timestamp_ns - previous_monotonic
            if elapsed_ns <= 0 or elapsed_ns > 3 * interval:
                raise ValueError("metadata RAM sample cadence is invalid")
            wall_elapsed_ns = int(
                (utc_time - previous_utc).total_seconds() * 1_000_000_000)
            if wall_elapsed_ns < 0 or abs(wall_elapsed_ns - elapsed_ns) > 2_000_000_000:
                raise ValueError("metadata RAM sample UTC/monotonic clocks disagree")
        previous_monotonic = timestamp_ns
        previous_utc = utc_time
        phase_counts[phase_index] += 1
        peak = max(peak, ram_bytes)
        if phase == "baseline":
            first_baseline = ram_bytes if first_baseline is None else first_baseline
            last_baseline = ram_bytes
        if phase == "teardown":
            first_teardown = ram_bytes if first_teardown is None else first_teardown
            last_teardown = ram_bytes

    if any(count < 2 for count in phase_counts):
        raise ValueError("metadata RAM trace lacks baseline/init/steady/GC/teardown observations")
    if (first_baseline != last_baseline or
            first_teardown <= last_baseline or
            last_teardown > last_baseline):
        raise ValueError("metadata RAM teardown did not recover baseline memory")
    if peak != expected_peak_ram_bytes or peak <= last_baseline:
        raise ValueError("metadata RAM peak is not the observed sample maximum")
