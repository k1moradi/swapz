#!/usr/bin/env python3
"""Rootless geometry experiment for zsmalloc-inspired *block* size classes.

This is NOT an executable kernel driver, GC simulation, or I/O benchmark.
Models packet size, 8-byte header and 8-byte logical-page descriptors,
and counts touched 4096-byte sectors per random record read. It exposes
trade-offs and a simple GC-victim sensitivity curve without making up WAF.
"""

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

BLOCK = 4096
HEADER = 8
DESCRIPTOR = 8


@dataclass(frozen=True)
class Container:
    block_count: int
    record_sizes: tuple[int, ...]

    @property
    def bytes_written(self) -> int:
        return self.block_count * BLOCK

    @property
    def bytes_needed(self) -> int:
        return (BLOCK if self.block_count == 1 and self.record_sizes == (BLOCK,)
                else HEADER + DESCRIPTOR * len(self.record_sizes) + sum(self.record_sizes))

    def physical_read_blocks(self) -> list[int]:
        """Read amplification for a compacted serialized container."""
        if self.block_count == 1 and self.record_sizes == (BLOCK,):
            return [1]
        offset = HEADER + DESCRIPTOR * len(self.record_sizes)
        result = []
        for size in self.record_sizes:
            first = offset // BLOCK
            last = (offset + size - 1) // BLOCK
            result.append(last - first + 1)
            offset += size
        return result


def greedy(pages: Iterable[int], block_count: int = 1) -> list[Container]:
    """Actual ordered repack policy's key geometry: one current container."""
    result: list[Container] = []
    cur: list[int] = []
    capacity = BLOCK * block_count
    for page in pages:
        if not 0 < page <= BLOCK:
            raise ValueError("page size outside 1..4096")
        if page == BLOCK:
            if cur:
                result.append(Container(block_count, tuple(cur)))
                cur = []
            result.append(Container(1, (BLOCK,)))
            continue
        if HEADER + DESCRIPTOR * (len(cur) + 1) + sum(cur) + page > capacity:
            if cur:
                result.append(Container(block_count, tuple(cur)))
                cur = []
        if HEADER + DESCRIPTOR + page > capacity:
            raise ValueError("page cannot fit in container")
        cur.append(page)
    if cur:
        result.append(Container(block_count, tuple(cur)))
    return result


def bounded_ordered(pages: Iterable[int], window: int = 16) -> list[Container]:
    """Same size window as best-fit, preserving order and closing every window."""
    values = list(pages)
    if window <= 0:
        raise ValueError("window must be positive")
    return [c for i in range(0, len(values), window)
            for c in greedy(values[i:i + window])]


def bounded_best_fit(pages: Iterable[int], window: int = 16) -> list[Container]:
    """Rootless optimistic comparator; reorder only within fixed input windows."""
    values = list(pages)
    result: list[Container] = []
    if window <= 0:
        raise ValueError("window must be positive")
    for start in range(0, len(values), window):
        bins: list[list[int]] = []
        for page in sorted(values[start:start + window], reverse=True):
            if not 0 < page <= BLOCK:
                raise ValueError("page size outside 1..4096")
            if page == BLOCK:
                result.append(Container(1, (BLOCK,)))
                continue
            valid = [i for i, bin_ in enumerate(bins)
                     if HEADER + DESCRIPTOR * (len(bin_) + 1) + sum(bin_) + page <= BLOCK]
            if valid:
                best = max(valid, key=lambda i: sum(bins[i]) + DESCRIPTOR * len(bins[i]))
                bins[best].append(page)
            else:
                bins.append([page])
        result.extend(Container(1, tuple(bin_)) for bin_ in bins)
    return result


def size_class_slab(pages: Iterable[int], block_count: int) -> list[Container]:
    """Optimistic homogeneous size-class pool; all records are live and may wait.

    Uses a single class determined by the largest compressed record in the
    *fixture*. This is an optimistic no-timeout experiment of ONE class, not
    a claim of optimal mixed-trace performance or a true dynamic class pool.
    No overwrite/GC accounting is performed. Final partial slab charges the
    entire aligned slab.
    """
    values = list(pages)
    if not values:
        return []
    raw = [Container(1, (BLOCK,)) for p in values if p == BLOCK]
    values = [p for p in values if p != BLOCK]
    if not values:
        return raw
    if any(not 0 < p < BLOCK for p in values):
        raise ValueError("invalid compressed page length")
    max_len = max(values)
    capacity = block_count * BLOCK
    slots = (capacity - HEADER) // (max_len + DESCRIPTOR)
    if slots < 1:
        raise ValueError("size class does not fit")
    return raw + [Container(block_count, tuple(values[i:i + slots]))
                  for i in range(0, len(values), slots)]


def bounded_size_class_slabs(pages: Iterable[int], block_count: int,
                             window: int = 16) -> list[Container]:
    """Force partial slabs at an upper-record-count flush boundary.

    W=16 is an illustrative dispatch limit, NOT an exact model of swapz's
    physical-container-based 64KiB buffer or real timer/backpressure.
    """
    values = list(pages)
    if window <= 0:
        raise ValueError("window must be positive")
    return [c for i in range(0, len(values), window)
            for c in size_class_slab(values[i:i + window], block_count)]


def summary(containers: list[Container]) -> dict:
    if not containers:
        raise ValueError("empty workload")
    physical = sum(c.bytes_written for c in containers)
    read_blocks = [count for c in containers for count in c.physical_read_blocks()]
    if any(c.bytes_needed > c.bytes_written for c in containers):
        raise AssertionError("slab overflow")
    logical = len(read_blocks) * BLOCK
    return {
        "records": len(read_blocks),
        "containers": len(containers),
        "physical_write_bytes_no_gc": physical,
        "gross_logical_to_physical": round(logical / physical, 6),
        "mean_4k_blocks_per_random_read": round(sum(read_blocks) / len(read_blocks), 6),
        "spanning_record_fraction": round(sum(b > 1 for b in read_blocks) / len(read_blocks), 6),
        "physical_read_4k_block_histogram": dict(Counter(read_blocks)),
    }


def gc_sensitivity(gross: float) -> dict:
    """Idealized victim-live fraction sensitivity, NOT measured device WAF.

    Assumes relocation traffic of f/(1-f) for each new physical payload unit.
    Actual WAF depends on segment selection, workload, free-space reserve,
    grouping and invalidation rates; utilization != victim live fraction.
    """
    return {
        "victim_live_fraction_break_even": round(1.0 - 1.0 / gross, 6),
        "net_ratio_by_victim_live_fraction": {
            str(f): round(gross * (1 - f), 6) for f in (0, 0.1, 0.3, 0.5, 0.8)
        },
    }


def report(pages: list[int]) -> dict:
    if not pages:
        raise ValueError("empty workload")
    results = {
        "streaming_ordered_4k": summary(greedy(pages)),
        "bounded_ordered_4k_W16": summary(bounded_ordered(pages)),
        "bounded_best_fit_4k_W16": summary(bounded_best_fit(pages)),
    }
    for blocks in (2, 4, 16):
        results[f"homogeneous_{blocks * 4}k_slab_optimistic"] = summary(
            size_class_slab(pages, blocks))
        results[f"homogeneous_{blocks * 4}k_slab_flush_W16"] = summary(
            bounded_size_class_slabs(pages, blocks, 16))
    for v in results.values():
        v["idealized_gc_sensitivity"] = gc_sensitivity(v["gross_logical_to_physical"])
    return results


def fixtures() -> dict[str, list[int]]:
    return {
        "uniform_fio_like_2072_651pages": [2072] * 651,
        "clustered_8x2200_then_8x1600": [2200] * 8 + [1600] * 8,
        "alternating_2200_1600": [v for _ in range(8) for v in (2200, 1600)],
        "uniform_fio_like_1048_112pages": [1048] * 112,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lengths", help="optional path to audit's page_index/payload_bytes/kind TSV")
    args = parser.parse_args()
    cases = fixtures()
    if args.lengths:
        with open(args.lengths, encoding="utf-8") as f:
            rows = [row.rstrip("\n").split("\t") for row in f]
        if not rows or rows[0] != ["page_index", "payload_bytes", "kind"]:
            raise SystemExit("unsupported TSV header")
        if any(i != str(n) or kind not in ("raw", "compressed")
               for n, (i, length, kind) in enumerate(rows[1:])):
            raise SystemExit("invalid index/type in TSV")
        cases["real_audit_capture"] = [int(length) if kind == "compressed" else BLOCK
                                       for _, length, kind in rows[1:]]
    print(json.dumps({name: report(pages) for name, pages in cases.items()}, indent=2))


if __name__ == "__main__":
    main()