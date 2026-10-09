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
import json
import math
from pathlib import Path
from statistics import median

SCHEMA = "swapz-drain-observation-v1"
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
    if not isinstance(row, dict) or set(row) != FIELDS:
        raise ValueError(f"line {line}: missing or unexpected observation fields")
    if row["schema"] != SCHEMA:
        raise ValueError(f"line {line}: unsupported observation schema")
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
        if type(row[key]) is not int or row[key] < 0:
            raise ValueError(f"line {line}: invalid nonnegative integer {key}")
    if row["batch_kib"] not in BATCHES:
        raise ValueError(f"line {line}: unsupported batch size")
    if row["strategy"] == "immediate" and row["batch_kib"] != 4:
        raise ValueError(f"line {line}: immediate strategy has only the 4 KiB baseline")
    if not (0 < row["duration_ns"] <= 10**13):
        raise ValueError(f"line {line}: invalid drain observation duration")
    if row["read_count"] < MIN_READS_PER_RUN or row["read_p99_ns"] <= 0:
        raise ValueError(f"line {line}: insufficient p99 samples or invalid p99")
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


def load_rows(path: Path) -> list[dict[str, object]]:
    if not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("observation input missing or too large")
    rows: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    with path.open(encoding="utf-8") as stream:
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
    best_drain = max(item["lower_drained_mib_s_median"] for item in points)
    # Three largest adjacent required sizes (256, 512, 1024 KiB) must
    # independently reach >=97% of the observed series' drain peak.
    tail = points[-3:]
    if any(item["lower_drained_mib_s_median"] < THROUGHPUT_TOLERANCE * best_drain
           for item in tail):
        group["reason"] = "NO STABLE HIGH-BATCH PLATEAU: final 3 sizes below 97% of peak"
        return group
    plateau = [item for item in points
               if item["lower_drained_mib_s_median"] >= THROUGHPUT_TOLERANCE * best_drain]
    best_p99 = min(item["read_p99_ms_worst_run"] for item in plateau)
    choices = [item for item in plateau if item["read_p99_ms_worst_run"]
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
    else:
        group["qualification"] = "PROVISIONAL - INDEPENDENT EVIDENCE REVIEW REQUIRED"
        group["provisional_selection_kib"] = chosen["batch_kib"]
        group["reason"] = "Input provenance is asserted, not authenticated by this offline analyzer"
    return group


def analyze(rows: list[dict[str, object]]) -> dict[str, object]:
    groups: dict[tuple[str, str, str, str, str], list[dict[str, object]]] = defaultdict(list)
    # Never pool measurement provenance, backend, profile, strategy or
    # compiled source revision into a fake cross-configuration plateau.
    for row in rows:
        key = tuple(row[name] for name in (
            "evidence", "backend", "profile", "strategy", "source_revision"
        ))
        groups[key].append(row)
    results = [_series(groups[key]) for key in sorted(groups)]
    return {
        "schema": "swapz-drain-analysis-v1",
        "status": "OFFLINE ANALYSIS - NO DEVICE ACCESS",
        "warning": "Provenance self-reported; operator must verify counter source and kernel I/O drain",
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
