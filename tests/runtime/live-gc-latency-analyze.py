#!/usr/bin/env python3
"""Correlate per-request swap-in latency with verified live-victim GC windows.

Offline analyzer only. Both CSVs must use CLOCK_MONOTONIC nanoseconds. It does
not collect kernel traces or assume gc_victims implies live-page movement.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


CLOCK_NAME = "monotonic"


def load_intervals(path: Path, *, gc: bool) -> list[tuple[int, int, int]]:
    required = {"clock", "start_ns", "end_ns", "moved_pages" if gc else "result"}
    events: list[tuple[int, int, int]] = []
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"{path}: expected CSV columns {sorted(required)}")
        for line_number, row in enumerate(reader, start=2):
            if row["clock"] != CLOCK_NAME:
                raise ValueError(f"{path}:{line_number}: inconsistent clock domain")
            try:
                start_ns = int(row["start_ns"])
                end_ns = int(row["end_ns"])
                moved_pages = int(row["moved_pages"]) if gc else 0
            except (TypeError, ValueError) as error:
                raise ValueError(f"{path}:{line_number}: invalid integer") from error
            if start_ns < 0 or end_ns <= start_ns or moved_pages < 0:
                raise ValueError(f"{path}:{line_number}: invalid interval or page count")
            if not gc and row["result"] != "ok":
                raise ValueError(f"{path}:{line_number}: unsuccessful swap-in read")
            events.append((start_ns, end_ns, moved_pages))
    if not events:
        raise ValueError(f"{path}: no events")
    return events


def merge_live_gc_windows(gc_intervals: list[tuple[int, int, int]]) -> list[tuple[int, int]]:
    live_intervals = sorted((start, end) for start, end, moved in gc_intervals if moved > 0)
    merged: list[tuple[int, int]] = []
    for start, end in live_intervals:
        if merged and start <= merged[-1][1]:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


def latencies_ms(read_intervals: list[tuple[int, int, int]],
                 gc_windows: list[tuple[int, int]]) -> tuple[list[float], list[float]]:
    overlapping: list[float] = []
    not_overlapping: list[float] = []
    current_gc = 0
    for start, end, _ in sorted(read_intervals):
        while current_gc < len(gc_windows) and gc_windows[current_gc][1] < start:
            current_gc += 1
        overlap = (current_gc < len(gc_windows) and gc_windows[current_gc][0] <= end)
        (overlapping if overlap else not_overlapping).append((end - start) / 1_000_000)
    return overlapping, not_overlapping


def summarize(samples: list[float]) -> dict[str, float | int | None]:
    if not samples:
        return {"count": 0, "p95_ms": None, "p99_ms": None, "max_ms": None}
    values = sorted(samples)
    # Nearest-rank percentile, with an exact sample count for tail confidence.
    return {"count": len(values),
            "p95_ms": values[math.ceil(0.95 * len(values)) - 1],
            "p99_ms": values[math.ceil(0.99 * len(values)) - 1],
            "max_ms": values[-1]}


def analyze(gc_path: Path, reads_path: Path,
            minimum_overlap_reads: int) -> dict[str, object]:
    if minimum_overlap_reads < 1:
        raise ValueError("minimum_overlap_reads must be positive")
    gc_intervals = load_intervals(gc_path, gc=True)
    read_intervals = load_intervals(reads_path, gc=False)
    windows = merge_live_gc_windows(gc_intervals)
    if not windows:
        raise ValueError("no GC event recorded actual live-page relocation")
    overlapping, other = latencies_ms(read_intervals, windows)
    if len(overlapping) < minimum_overlap_reads:
        raise ValueError(f"insufficient live-GC-overlapping reads: "
                         f"{len(overlapping)} < {minimum_overlap_reads}")
    return {
        "clock": CLOCK_NAME,
        "classification": "read interval overlaps GC interval with moved_pages > 0",
        "gc_events": len(gc_intervals),
        "live_gc_events": sum(moved > 0 for _, _, moved in gc_intervals),
        "live_pages_moved": sum(moved for _, _, moved in gc_intervals),
        "merged_live_gc_windows": len(windows),
        "all_reads": summarize(overlapping + other),
        "overlapping_live_gc": summarize(overlapping),
        "outside_live_gc": summarize(other),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gc-events", type=Path, required=True)
    parser.add_argument("--reads", type=Path, required=True)
    parser.add_argument("--min-overlap-reads", type=int, default=10000)
    args = parser.parse_args()
    try:
        report = analyze(args.gc_events, args.reads, args.min_overlap_reads)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
