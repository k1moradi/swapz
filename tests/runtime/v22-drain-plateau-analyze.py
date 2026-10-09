#!/usr/bin/env python3
"""Offline V2.2 drain/p99 plateau evaluator; no device access or benchmark runs.

Consumes strict JSONL observations from a *separate* trusted collector.
Lower-device write-sector deltas, not logical request bytes or fio write
bandwidth, supply the throughput numerator. The supplied provenance is
NOT independently authenticated by this parser. Synthetic observations
can only yield explicitly non-benchmark illustrative candidates.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import io
import json
import math
import os
from pathlib import Path
import stat
from statistics import median

SCHEMA = "swapz-drain-observation-v1"
SCHEMA_V2 = "swapz-drain-observation-v2"
# V2 requires an exact, run-length-encoded latency distribution. These are
# still caller-asserted counts, not authenticated device observations.
MAX_LATENCY_BINS = 256
MAX_READ_COUNT = 10_000_000
MAX_NS = 10**13
MAX_COUNTER = (1 << 64) - 1
SECTOR_BYTES = 512
MIB = 1024 * 1024
BATCHES = (4, 8, 16, 32, 64, 128, 256, 512, 1024)
STRATEGIES = ("immediate", "opportunistic", "staged")
EVIDENCE = ("synthetic", "kernel", "physical")
MIN_REPEATS = 3
MIN_READS_PER_RUN = 10000
MAX_SPREAD = 0.10
THROUGHPUT_TOLERANCE = 0.97
READ_P99_TOLERANCE = 1.10
MAX_INPUT_BYTES = 2 * MIB
MAX_OBSERVATIONS = 5000
FIELDS = frozenset((
    "schema", "evidence", "backend", "profile", "strategy", "batch_kib",
    "run_id", "source_revision", "clock", "duration_ns",
    "lower_write_sectors_before", "lower_write_sectors_after",
    "lower_write_ios_before", "lower_write_ios_after", "logical_write_bytes",
    "read_count", "read_p99_ns", "integrity_ok", "quiescence_ok",
    "flush_ok", "all_reaped", "source_kind",
))
INTEGER_FIELDS = (
    "batch_kib", "duration_ns", "lower_write_sectors_before",
    "lower_write_sectors_after", "lower_write_ios_before",
    "lower_write_ios_after", "logical_write_bytes", "read_count",
    "read_p99_ns",
)
BOOL_FIELDS = ("integrity_ok", "quiescence_ok", "flush_ok", "all_reaped")
FIELDS_V2 = FIELDS | {"read_latency_counts"}


def _validate_latency_counts(row: dict[str, object], line: int) -> None:
    """Recompute exact nearest-rank p99 from a bounded histogram.

    Each [latency_ns, count] pair represents an exact observed latency,
    NOT a coarse bucket upper bound. Counts are still supplied by an
    external, unauthenticated collector; source-only checks cannot prove
    the observations actually occurred.
    """
    histogram = row["read_latency_counts"]
    if (type(histogram) is not list or not 1 <= len(histogram) <= MAX_LATENCY_BINS):
        raise ValueError(f"line {line}: invalid bounded read latency distribution")
    previous_latency = 0
    total = 0
    cumulative: list[tuple[int, int]] = []
    for pair in histogram:
        if (type(pair) is not list or len(pair) != 2
                or type(pair[0]) is not int or type(pair[1]) is not int):
            raise ValueError(f"line {line}: invalid latency/count pair")
        latency, count = pair
        if (not previous_latency < latency <= MAX_NS
                or not 0 < count <= MAX_READ_COUNT):
            raise ValueError(f"line {line}: nonpositive, duplicate, unsorted or oversized latency bucket")
        previous_latency = latency
        total += count
        if total > MAX_READ_COUNT:
            raise ValueError(f"line {line}: read latency count exceeds limit")
        cumulative.append((latency, total))
    if total != row["read_count"]:
        raise ValueError(f"line {line}: read_count differs from exact latency distribution")
    rank = (99 * total + 99) // 100  # ceil(0.99 * n), one-based nearest rank
    p99 = next(latency for latency, observed in cumulative if observed >= rank)
    if row["read_p99_ns"] != p99:
        raise ValueError(f"line {line}: read_p99_ns differs from recomputed nearest-rank p99")


def _unique_object(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON object field")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"nonfinite JSON constant: {value}")


def validate(row: object, line: int) -> dict[str, object]:
    if not isinstance(row, dict):
        raise ValueError(f"line {line}: missing or unexpected observation fields")
    if type(row.get("schema")) is not str or row["schema"] not in (SCHEMA, SCHEMA_V2):
        raise ValueError(f"line {line}: unsupported observation schema")
    required = FIELDS_V2 if row["schema"] == SCHEMA_V2 else FIELDS
    if set(row) != required:
        raise ValueError(f"line {line}: missing or unexpected observation fields")
    if type(row["evidence"]) is not str or row["evidence"] not in EVIDENCE:
        raise ValueError(f"line {line}: invalid evidence class")
    if type(row["strategy"]) is not str or row["strategy"] not in STRATEGIES:
        raise ValueError(f"line {line}: invalid strategy")
    if row["source_kind"] != "lower-device-counters":
        raise ValueError(f"line {line}: lower-level sector counters required")
    if row["clock"] != "monotonic":
        raise ValueError(f"line {line}: one monotonic drain clock required")
    for key in ("backend", "profile", "run_id", "source_revision"):
        text = row[key]
        if (type(text) is not str or not (1 <= len(text) <= 128)
                or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in text)):
            raise ValueError(f"line {line}: invalid or missing {key}")
    for key in INTEGER_FIELDS:
        if type(row[key]) is not int or not 0 <= row[key] <= MAX_COUNTER:
            raise ValueError(f"line {line}: invalid bounded nonnegative integer {key}")
    if row["batch_kib"] not in BATCHES:
        raise ValueError(f"line {line}: unsupported batch size")
    if row["strategy"] == "immediate" and row["batch_kib"] != 4:
        raise ValueError(f"line {line}: immediate strategy has only the 4 KiB baseline")
    if not (0 < row["duration_ns"] <= 10**13):
        raise ValueError(f"line {line}: invalid drain observation duration")
    if (not MIN_READS_PER_RUN <= row["read_count"] <= MAX_READ_COUNT
            or not 0 < row["read_p99_ns"] <= MAX_NS):
        raise ValueError(f"line {line}: insufficient p99 samples or invalid p99")
    if row["schema"] == SCHEMA_V2:
        _validate_latency_counts(row, line)
    if row["lower_write_sectors_after"] <= row["lower_write_sectors_before"]:
        raise ValueError(f"line {line}: missing or decreasing physical-sector write evidence")
    if row["lower_write_ios_after"] <= row["lower_write_ios_before"]:
        raise ValueError(f"line {line}: missing or decreasing lower-device write I/O evidence")
    if row["logical_write_bytes"] <= 0:
        raise ValueError(f"line {line}: no successful logical workload")
    for key in BOOL_FIELDS:
        if row[key] is not True:
            raise ValueError(f"line {line}: failed or unverified gate: {key}")
    return row


def _read_pinned_observation_text(path: Path) -> str:
    """Bound original bytes through one non-symlink regular-file descriptor.

    This closes the check/open race. It does not authenticate a same-identity
    actor that can rewrite file contents, or prove physical data provenance.
    """
    if not hasattr(os, "O_NOFOLLOW"):
        raise ValueError("symlink-safe observation input unavailable")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"observation input cannot be pinned: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError("observation input must be a singly-linked regular file")
        if before.st_size > MAX_INPUT_BYTES:
            raise ValueError("observation input too large")
        remaining = MAX_INPUT_BYTES + 1
        blocks: list[bytes] = []
        total = 0
        while remaining:
            block = os.read(descriptor, min(65536, remaining))
            if not block:
                break
            blocks.append(block)
            total += len(block)
            remaining -= len(block)
        if total > MAX_INPUT_BYTES:
            raise ValueError("observation input too large")
        after = os.fstat(descriptor)
        def identity(metadata: os.stat_result) -> tuple[int, ...]:
            return (metadata.st_dev, metadata.st_ino, metadata.st_mode,
                    metadata.st_nlink, metadata.st_size, metadata.st_mtime_ns,
                    metadata.st_ctime_ns)
        if identity(before) != identity(after) or total != before.st_size:
            raise ValueError("observation input changed during bounded read")
        try:
            return b"".join(blocks).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("observation input is not UTF-8") from exc
    finally:
        os.close(descriptor)


def load_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    with io.StringIO(_read_pinned_observation_text(path)) as stream:
        for number, line in enumerate(stream, start=1):
            if number > MAX_OBSERVATIONS:
                raise ValueError("too many observations")
            if not line.strip():
                raise ValueError(f"line {number}: blank observation")
            try:
                parsed = json.loads(line, object_pairs_hook=_unique_object,
                                    parse_constant=_reject_constant)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"line {number}: invalid JSON: {exc}") from exc
            row = validate(parsed, number)
            run_id = row["run_id"]
            if run_id in seen_ids:
                raise ValueError(f"line {number}: duplicate run identifier")
            seen_ids.add(run_id)
            rows.append(row)
    if not rows:
        raise ValueError("no observations")
    return rows


def _measurement(row: dict[str, object]) -> float:
    sectors = row["lower_write_sectors_after"] - row["lower_write_sectors_before"]
    return (sectors * SECTOR_BYTES / MIB) / (row["duration_ns"] / 10**9)


def _series(rows: list[dict[str, object]]) -> dict[str, object]:
    example = rows[0]
    group = {
        "schema": example["schema"],
        "read_p99_integrity": ("RECOMPUTED FROM EXACT LATENCY COUNTS"
                               if example["schema"] == SCHEMA_V2
                               else "SELF-REPORTED - NOT VERIFIED"),
        "evidence": example["evidence"],
        "backend": example["backend"],
        "profile": example["profile"],
        "strategy": example["strategy"],
        "source_revision": example["source_revision"],
        "qualification": "PLATEAU NOT REACHED",
        "candidate_batch_kib": None,
        "provisional_selection_kib": None,
        "reason": "",
        "points": [],
    }
    per_batch: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        per_batch[row["batch_kib"]].append(row)
    expected = (4,) if example["strategy"] == "immediate" else BATCHES
    if set(per_batch) != set(expected):
        group["reason"] = "INCOMPLETE SWEEP: required batch sizes not all observed"
        return group
    points: list[dict[str, object]] = []
    # Display rounding must NEVER change the 97% or 10% qualification
    # comparisons. Retain full unrounded measurements separately.
    raw_medians: dict[int, float] = {}
    raw_worst_p99_ms: dict[int, float] = {}
    for size in expected:
        replicas = per_batch[size]
        if len(replicas) < MIN_REPEATS:
            group["reason"] = f"INSUFFICIENT REPLICATION: {size} KiB"
            return group
        throughputs = [_measurement(row) for row in replicas]
        middle = median(throughputs)
        spread = (max(throughputs) - min(throughputs)) / middle
        if not math.isfinite(middle) or middle <= 0 or spread > MAX_SPREAD:
            group["reason"] = f"UNSTABLE LOWER DRAIN: {size} KiB"
            return group
        raw_medians[size] = middle
        raw_worst_p99_ms[size] = max(row["read_p99_ns"] for row in replicas) / 10**6
        points.append({
            "batch_kib": size,
            "repeats": len(replicas),
            "lower_drained_mib_s_median": round(middle, 6),
            "lower_drained_mib_s_min": round(min(throughputs), 6),
            "lower_drained_mib_s_max": round(max(throughputs), 6),
            "replicate_range_fraction": round(spread, 6),
            "read_p99_ms_worst_run": round(
                max(row["read_p99_ns"] for row in replicas) / 10**6, 6
            ),
            "read_count_min": min(row["read_count"] for row in replicas),
        })
    group["points"] = points
    if example["strategy"] == "immediate":
        group["reason"] = "SINGLE BATCH BASELINE: not a saturation sweep"
        return group
    best_drain = max(raw_medians.values())
    # Three largest adjacent required sizes (256, 512, 1024 KiB) must
    # independently reach >=97% of the observed series' drain peak.
    # Qualify against UNROUNDED values; output rounding is display only.
    tail = points[-3:]
    if any(raw_medians[item["batch_kib"]] < THROUGHPUT_TOLERANCE * best_drain
           for item in tail):
        group["reason"] = "NO STABLE HIGH-BATCH PLATEAU: final 3 sizes below 97% of peak"
        return group
    plateau = [item for item in points
               if raw_medians[item["batch_kib"]] >= THROUGHPUT_TOLERANCE * best_drain]
    best_p99 = min(raw_worst_p99_ms[item["batch_kib"]] for item in plateau)
    choices = [item for item in plateau if raw_worst_p99_ms[item["batch_kib"]]
               <= READ_P99_TOLERANCE * best_p99]
    if not choices:
        group["reason"] = "NO READ-P99-COMPATIBLE PLATEAU POINT"
        return group
    chosen = min(choices, key=lambda item: item["batch_kib"])
    group["candidate_batch_kib"] = chosen["batch_kib"]
    group["plateau_median_mib_s"] = round(best_drain, 6)
    group["best_plateau_worst_run_read_p99_ms"] = best_p99
    if example["evidence"] == "synthetic":
        group["qualification"] = "SYNTHETIC ONLY - NOT BENCHMARK EVIDENCE"
        group["reason"] = "Illustrative candidate only; no measured kernel or physical drain"
    elif example["schema"] == SCHEMA:
        # Even an unqualified algorithmic candidate can be mistaken for a
        # performance nomination. Legacy self-labeled kernel/physical
        # evidence supplies NO candidate or provisional selection.
        group["candidate_batch_kib"] = None
        group["qualification"] = "UNVERIFIED P99 - EXACT LATENCY DISTRIBUTION REQUIRED"
        group["reason"] = (
            "V1 read_count and read_p99_ns are self-reported; no provisional "
            "selection without recomputing p99 from exact latency counts"
        )
    else:
        group["qualification"] = "PROVISIONAL - INDEPENDENT EVIDENCE REVIEW REQUIRED"
        group["provisional_selection_kib"] = chosen["batch_kib"]
        group["reason"] = (
            "Exact latency histogram is internally consistent, but raw "
            "samples, collector provenance and lower-device drain are unauthenticated"
        )
    return group


def analyze(rows: list[dict[str, object]]) -> dict[str, object]:
    groups: dict[tuple[str, str, str, str, str, str], list[dict[str, object]]] = defaultdict(list)
    # Never pool schema/p99 integrity, measurement provenance, backend,
    # profile, strategy or revision into a fake cross-configuration plateau.
    for row in rows:
        key = tuple(row[name] for name in (
            "schema", "evidence", "backend", "profile", "strategy", "source_revision"
        ))
        groups[key].append(row)
    results = [_series(groups[key]) for key in sorted(groups)]
    return {
        "schema": "swapz-drain-analysis-v1",
        "status": "OFFLINE ANALYSIS - NO DEVICE ACCESS",
        "warning": ("Counter and latency-distribution origins are self-reported; "
                    "v2 proves only internal nearest-rank p99 consistency, "
                    "not the existence of real swap-in samples or kernel I/O drain"),
        "observation_count": len(rows),
        "series": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", required=True, type=Path,
                        help="strict JSON Lines with independently measured lower-device sector counters")
    args = parser.parse_args()
    try:
        report = analyze(load_rows(args.observations))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
