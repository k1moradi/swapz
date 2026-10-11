#!/usr/bin/env python3
"""Read-only exploratory 3-policy report; NEVER selects a qualified winner.

First demands the complete existing V2.2 fast-screen validation, including
exact CLAT, full writer CRC and source-reported successful owned teardown.
Re-pins each RLE sidecar by the already-validated digest before computing
exact nearest-rank p95. No device I/O, subprocess, or fio invocation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys

HERE = Path(__file__).resolve().parent


def load_module(module_name: str, path: str):
    spec = importlib.util.spec_from_file_location(module_name, HERE / path)
    if spec is None or spec.loader is None:
        raise ValueError(f"required validator unavailable: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


screen = load_module("swapz_fast_compare_screen", "v22-fast-screen.py")
plateau = screen.plateau


def exact_p95_from_pinned_sidecar(dirfd: int, name: str, digest: str,
                                  expected_count: int) -> int:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK |
                 os.O_CLOEXEC, dir_fd=dirfd)
    try:
        before = os.fstat(fd)
        record = plateau._LATENCY_RECORD
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
                before.st_size <= 0 or before.st_size % record.size or
                before.st_size > min(expected_count * record.size,
                                    plateau.MAX_TOTAL_SIDECAR_BYTES)):
            raise ValueError("invalid pinned exact-latency sidecar")
        remaining = before.st_size
        raw = bytearray()
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                raise ValueError("exact sidecar truncated")
            raw.extend(chunk)
            remaining -= len(chunk)
        if (os.read(fd, 1) or
                plateau._file_identity(before) != plateau._file_identity(os.fstat(fd))):
            raise ValueError("exact sidecar modified during read")
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("exact sidecar digest changed after fast-screen check")
        total = previous = 0
        p95 = None
        rank = (95 * expected_count + 99) // 100
        for latency, count in record.iter_unpack(raw):
            if (not previous < latency <= plateau.MAX_NS or
                    not 0 < count <= plateau.MAX_READ_COUNT):
                raise ValueError("invalid exact sidecar RLE record")
            previous = latency
            total += count
            if total > expected_count:
                raise ValueError("exact sidecar count exceeds reader completions")
            if p95 is None and total >= rank:
                p95 = latency
        if total != expected_count or p95 is None:
            raise ValueError("exact sidecar count/p95 incomplete")
        return p95
    finally:
        os.close(fd)


def cumulative_lz4_payload_ratio(status: dict[str, object]) -> float | None:
    """Kernel's cumulative compressed-page payload ratio, NOT physical savings."""
    pair = (status.get("compressed_pages"), status.get("compressed_payload"))
    if pair == (None, None):
        return None
    if any(type(value) is not str or re.fullmatch(r"[0-9]{1,20}", value) is None
           for value in pair):
        raise ValueError("malformed cumulative LZ4 payload counters")
    pages, payload_bytes = map(int, pair)
    if pages == 0 and payload_bytes == 0:
        return None
    if pages <= 0 or payload_bytes <= 0:
        raise ValueError("inconsistent cumulative LZ4 payload counters")
    return (pages * 4096) / payload_bytes


def compare(path: Path) -> dict[str, object]:
    validated = screen.check_results(path)
    raw = plateau._read_pinned_observation_text(path)
    if hashlib.sha256(raw.encode("utf-8")).hexdigest() != validated[
            "completed_results_sha256"]:
        raise ValueError("results bytes changed between validation and comparison")
    rows = [json.loads(line, object_pairs_hook=screen.reporter._object,
                       parse_constant=screen.reporter._constant)
            for line in raw.splitlines()]
    if len(rows) != 3:
        raise ValueError("unexpected number of validated cases")

    dirfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY |
                    os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        cases = []
        for i, (r, case) in enumerate(zip(rows, validated["cases"]), 1):
            name = r["exact_read_latency"]["read_latency_sidecar"]
            digest = r["exact_read_latency"]["read_latency_sha256"]
            p95_ns = exact_p95_from_pinned_sidecar(
                dirfd, name, digest, case["observed_reads"])
            cases.append({
                **case,
                "exact_read_p95_ms": p95_ns / 1e6,
                "staged_early_source_reported": r.get("staged_early"),
                "staged_hits_source_reported": r.get("staged_hits"),
                "physical_write_reqs_source_reported": r.get("physical_write_reqs"),
                # Timed fio logical bytes versus sysfs lower sectors.
                # This can include GC/foreign backend I/O and is NOT an
                # independent device-attributed compression measurement.
                "effective_io_reduction_ratio":
                    r["logical_write_bytes"] / (r["lower_write_sectors"] * 512),
                # Cumulative kernel LZ4 payload-only ratio; raw pages and
                # container/record overhead are excluded.
                "lz4_payload_ratio_cumulative":
                    cumulative_lz4_payload_ratio(r["status"]),
            })
    finally:
        os.close(dirfd)

    control = cases[0]
    for case in cases:
        case["relative_to_immediate"] = {
            # Both tails use the same Immediate baseline and exact CLAT samples.
            "exact_read_p95_ratio": case["exact_read_p95_ms"] /
                                    control["exact_read_p95_ms"],
            "exact_read_p99_ratio": case["exact_read_p99_ms"] /
                                    control["exact_read_p99_ms"],
            "upper_write_mib_s_ratio": case["upper_write_mib_s"] /
                                        control["upper_write_mib_s"],
            "lower_write_ios_ratio": case["lower_write_ios"] /
                                       control["lower_write_ios"],
            "lower_write_sectors_ratio": case["lower_write_sectors"] /
                                           control["lower_write_sectors"],
        }

    return {
        "schema": "swapz-v22-fast-three-policy-exploratory-comparison-v1",
        "diagnostic_gate": validated["diagnostic_gate"],
        "source_reported_teardown": validated["source_reported_teardown"],
        "completed_results_sha256": validated["completed_results_sha256"],
        "cases": cases,
        "comparison_baseline": "Immediate 4 KiB",
        "qualified_winner": None,
        "independent_kernel_quiescence_or_device_attribution": False,
        "evidence": "SOURCE_REPORTED_EXPLORATORY_ONLY",
        "limitations": (
            "One sweep without randomization/repetition; lower-device sectors and "
            "requests are source-reported, not exclusively attributed. Reader "
            "p95/p99 are nearest-rank exact fio CLAT sidecar samples, not "
            "independent timing instrumentation. The effective lower-byte "
            "ratio includes possible GC/unrelated I/O, while the cumulative "
            "LZ4 payload ratio excludes raw pages and container overhead. "
            "No qualified winner."
        ),
    }


def markdown(report: dict[str, object]) -> str:
    output = [
        "# swapz V2.2 — three-strategy exploratory diagnostics",
        "",
        "Source-reported completed sweep; NO QUALIFIED WINNER.",
        "",
        "| Policy (batch) | Completed reads | Exact p95 (ms) | Exact p99 (ms) | "
        "p95 ratio | p99 ratio | Upper write (MiB/s) | Upper ratio | "
        "LZ4 payload ratio (cumulative) | Effective I/O reduction | "
        "Lower write I/Os | Lower sectors | I/O ratio vs Immediate | "
        "Sector ratio vs Immediate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in report["cases"]:
        ratios = c["relative_to_immediate"]
        lz4 = c["lz4_payload_ratio_cumulative"]
        lz4_label = f"{lz4:.3f}x" if lz4 is not None else "n/a"
        output.append(
            f"| {c['strategy'].title()} ({c['batch_kib']} KiB) | "
            f"{c['observed_reads']} | {c['exact_read_p95_ms']:.3f} | "
            f"{c['exact_read_p99_ms']:.3f} | "
            f"{ratios['exact_read_p95_ratio']:.3f}x | "
            f"{ratios['exact_read_p99_ratio']:.3f}x | "
            f"{c['upper_write_mib_s']:.2f} | "
            f"{ratios['upper_write_mib_s_ratio']:.3f}x | "
            f"{lz4_label} | {c['effective_io_reduction_ratio']:.3f}x | "
            f"{c['lower_write_ios']} | {c['lower_write_sectors']} | "
            f"{ratios['lower_write_ios_ratio']:.3f}x | "
            f"{ratios['lower_write_sectors_ratio']:.3f}x |"
        )
    output.extend([
        "",
        "All cases passed the existing exact-CLAT, full writer CRC32C, sentinel, "
        "and source-reported teardown-marker gates.",
        "",
        "**Not qualified:** kernel quiescence, exclusive physical write attribution, "
        "or a strategy winner. LZ4 payload ratio is kernel-cumulative and "
        "excludes metadata/raw pages. Effective I/O reduction is based on "
        "fio logical bytes and shared lower sysfs sector deltas, including "
        "potential GC/foreign I/O. No separate benchmark execution was performed.",
    ])
    return "\n".join(output) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    args = parser.parse_args()
    try:
        result = compare(args.results)
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
        parser.error(str(exc))
    if args.format == "json":
        print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
    else:
        print(markdown(result), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
