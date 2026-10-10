#!/usr/bin/env python3
"""Rootless V2.2 three-strategy screen plan and read-only diagnostic gate.

Never runs fio, a benchmark, subprocesses or device/kernel commands. Planning
does not authorize execution. A positive result is NOT a qualified winner,
physical I/O attribution, independent quiescence or live kernel qualification.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"required rootless source unavailable: {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


planner = _load("swapz_fast_screen_planner", "streaming-benchmark-plan.py")
reporter = _load("swapz_fast_screen_reporter", "streaming-benchmark-report.py")
plateau = _load("swapz_fast_screen_exact_sidecars", "v22-drain-plateau-analyze.py")

FAST_CASES = (
    ("immediate", 4),
    ("opportunistic", 64),
    ("staged", 64),
)
BACKEND = "null_blk-20MiBps-500000ns-QD1"
MIN_EXPLORATORY_READS = 1000
SOURCE = "fio-clat-log-only-NOT-independent-attestation"


def make_plan(profile: str) -> dict[str, object]:
    if profile not in ("fast", "full"):
        raise ValueError("profile must be fast or full")
    fast = profile == "fast"
    batches = "64" if fast else "4 8 16 32 64 128 256"
    runtime, iops = (10, 300) if fast else (30, 500)
    result = planner.plan(
        backend="null_blk", bandwidth=20, latency_ns=500000,
        strategies="immediate opportunistic staged", batches=batches,
        repeats=1, runtime=runtime, write_qd=64, compress=50)
    cases = tuple((c["strategy"], c["batch_kib"]) for c in result["cases"])
    if fast and cases != FAST_CASES:
        raise ValueError("unexpected three-case planner expansion")
    if not result["backend_runnable"] or result["qualified_winner"] is not None:
        raise ValueError("benchmark admission or evidence contract changed")
    environment = {
        "SWAPZ_BENCH_BACKEND": "null_blk",
        "SWAPZ_BENCH_MBPS": "20",
        "SWAPZ_BENCH_LATENCY_NS": "500000",
        "SWAPZ_BENCH_RUNTIME": str(runtime),
        "SWAPZ_BENCH_READ_IOPS": str(iops),
        "SWAPZ_BENCH_QD": "64",
        "SWAPZ_BENCH_COMPRESS": "50",
        "SWAPZ_BENCH_BATCHES": batches,
        "SWAPZ_BENCH_STRATEGIES": "immediate opportunistic staged",
        "SWAPZ_BENCH_KEEP_ARTIFACTS": "1",
        "SWAPZ_BENCH_DISCARD": "0",
    }
    return {
        "schema": "swapz-v22-rootless-screen-plan-v1",
        "profile": profile,
        "cases": result["cases"],
        "total_planned_runs": result["total_planned_runs"],
        "backend": BACKEND,
        "environment": environment,
        "read_iops_target": iops,
        "runtime_seconds_per_case": runtime,
        "nominal_reads_per_case_NOT_GUARANTEED": iops * runtime,
        "null_blk_tick_budget_bytes": result["null_blk_tick_budget_bytes"],
        "benchmark_entrypoint": "tests/runtime/streaming-benchmark.sh",
        "execution_authorized": False,
        "device_operations_performed": False,
        "evidence": "PLAN_ONLY_NO_MEASUREMENTS",
        "qualified_winner": None,
        "limits": ("Only after reviewed Codex harness passes in explicitly authorized "
                   "disposable VM; null_blk tick throttle is not a faithful "
                   "serialized 20 MiB/s storage model"),
    }


def check_results(path: Path) -> dict[str, object]:
    """Validate all three completed diagnostic rows and pinned exact CLAT logs.

    Enforces the *specific* fast screen profile, not a general result bundle.
    Does not independently attest device identity, quiescence or kernel state.
    """
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise ValueError("safe pinned sidecar access unavailable")
    if path.name in ("", ".", ".."):
        raise ValueError("invalid result filename")
    # The V3 helper pins regular-file identity and bounds JSONL reads. It does
    # NOT interpret these non-qualifying diagnostic rows as V3 observations.
    raw = plateau._read_pinned_observation_text(path)
    lines = raw.splitlines()
    if len(lines) != len(FAST_CASES) or any(not x.strip() for x in lines):
        raise ValueError("screen must contain exactly three nonblank observations")
    cases = []
    used_names: set[str] = set()
    byte_budget = 64 * 1024 * 1024
    try:
        dirfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY |
                        os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise ValueError(f"screen artifact directory cannot be pinned: {exc}") from exc
    try:
        for line_no, raw_row in enumerate(lines, 1):
            row = json.loads(raw_row, object_pairs_hook=reporter._object,
                             parse_constant=reporter._constant)
            reporter.validate(row, line_no)
            key = (row["strategy"], row["batch_kib"])
            if key != FAST_CASES[line_no - 1]:
                raise ValueError(f"line {line_no}: expected case {FAST_CASES[line_no-1]}")
            if row["backend"] != BACKEND:
                raise ValueError(f"line {line_no}: unexpected benchmark backend")
            status = row["status"]
            if (status.get("strategy") != key[0] or
                    status.get("batch_kib") != str(key[1]) or
                    status.get("lower_discard") != "off"):
                raise ValueError(f"line {line_no}: status did not confirm configuration")
            if (row.get("isolated_sentinel_readback_ok") is not True or
                    "fio_full_writer_verification" not in row):
                raise ValueError(f"line {line_no}: full-range and sentinel CRC checks required")
            if row["lower_write_ios"] <= 0 or row["lower_write_sectors"] <= 0:
                raise ValueError(f"line {line_no}: no measured lower write activity")
            # One nominal rate cannot guarantee any number of completions.
            if row["read_count"] < MIN_EXPLORATORY_READS:
                raise ValueError(f"line {line_no}: fewer than {MIN_EXPLORATORY_READS} observed reads")
            exact = row.get("exact_read_latency")
            if type(exact) is not dict:
                raise ValueError(f"line {line_no}: exact reader distribution missing")
            name, digest = exact.get("read_latency_sidecar"), exact.get("read_latency_sha256")
            if (type(name) is not str or re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.latbin", name) is None
                    or type(digest) is not str or
                    re.fullmatch(r"[0-9a-f]{64}", digest) is None or
                    exact.get("read_latency_source") != SOURCE or
                    type(exact.get("read_latency_bytes")) is not int):
                raise ValueError(f"line {line_no}: missing or untrusted CLAT sidecar metadata")
            lat_row = {
                "read_latency_sidecar": name,
                "read_latency_sha256": digest,
                "read_count": row["read_count"],
                "read_p99_ns": exact["read_p99_ns"],
            }
            used_bytes = plateau._verify_v3_sidecar(
                lat_row, line_no, dirfd, byte_budget, used_names)
            if exact["read_latency_bytes"] != used_bytes:
                raise ValueError(f"line {line_no}: exact sidecar byte count mismatch")
            byte_budget -= used_bytes
            cases.append({
                "strategy": key[0],
                "batch_kib": key[1],
                "observed_reads": row["read_count"],
                "exact_read_p99_ms": row["read_p99_ms"],
                "upper_write_mib_s": row["upper_write_mib_s"],
                "lower_counter_window_mib_s": row["lower_counter_window_mib_s"],
                "lower_write_ios": row["lower_write_ios"],
                "lower_write_sectors": row["lower_write_sectors"],
                "full_writer_crc32c": True,
                "sentinel_readback": True,
            })
    finally:
        os.close(dirfd)
    return {
        "schema": "swapz-v22-rootless-fast-screen-check-v1",
        "diagnostic_gate": "PASS_SOURCE_REPORTED_ONLY",
        "case_count": len(cases),
        "cases": cases,
        "qualified_winner": None,
        "evidence": "UNQUALIFIED_EXPLORATORY_DIAGNOSTICS",
        "execution_authorized": False,
        "limitations": (
            "NO QUALIFIED WINNER: exact fio CLAT and source-reported CRC checked; "
            "kernel/module identity, backend attribution, complete drain and "
            "quiescence remain independently unverified"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--plan", choices=("fast", "full"),
                         help="emit non-executing planned environment")
    actions.add_argument("--results", type=Path,
                         help="read-only check of the exact 3-case diagnostic JSONL")
    args = parser.parse_args()
    try:
        result = make_plan(args.plan) if args.plan else check_results(args.results)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
