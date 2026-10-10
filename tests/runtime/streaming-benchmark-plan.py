#!/usr/bin/env python3
"""Rootless V2.2 benchmark case planner and pre-device admission check.

No device, subprocess, sysfs, root, kernel module or network operations.
The existing live benchmark remains the sole executor and does NOT use
this plan as evidence of completed runs or a qualified batch winner.
"""
from __future__ import annotations

import argparse
import json
import re

BATCH_KIB = (4, 8, 16, 32, 64, 128, 256, 512, 1024)
POLICIES = ("immediate", "opportunistic", "staged")
TICKS_PER_SECOND = 50
TICK_QUANTUM_BYTES = 1048576 // TICKS_PER_SECOND
MAX_BANDWIDTH_MIB_S = 4096


def policy_list(raw: str) -> tuple[str, ...]:
    values = tuple(raw.split())
    if (not values or len(values) > len(POLICIES)
            or len(set(values)) != len(values)
            or any(value not in POLICIES for value in values)):
        raise ValueError("strategies must be distinct immediate/opportunistic/staged names")
    return values


def batch_list(raw: str, backend: str, bandwidth: int) -> tuple[int, ...]:
    if raw == "auto":
        batches = BATCH_KIB
        if backend == "null_blk" and bandwidth:
            limit = bandwidth * TICK_QUANTUM_BYTES
            batches = tuple(size for size in batches if size * 1024 <= limit)
        if not batches:
            raise ValueError("no batch fits the null_blk per-tick request budget")
        return batches

    tokens = raw.split()
    if (not tokens or len(tokens) > len(BATCH_KIB)
            or any(re.fullmatch(r"[0-9]+", item) is None for item in tokens)):
        raise ValueError("batches must be a nonempty space-separated list of KiB sizes")
    numbers = tuple(int(item) for item in tokens)
    if (any(item not in BATCH_KIB for item in numbers)
            or tuple(sorted(set(numbers))) != numbers):
        raise ValueError("batches must be strictly increasing, distinct supported KiB sizes")
    if backend == "null_blk" and bandwidth:
        budget = bandwidth * TICK_QUANTUM_BYTES
        too_large = [item for item in numbers if item * 1024 > budget]
        if too_large:
            raise ValueError(
                f"null_blk {bandwidth} MiB/s has {budget} bytes per tick "
                f"(50 Hz); unserviceable batch KiB: "
                + " ".join(map(str, too_large))
                + ". Select smaller batches, an unthrottled latency-only "
                  "control, or a separately qualified size-aware backend.")
    return numbers


def plan(*, backend: str, bandwidth: int, latency_ns: int,
         strategies: str, batches: str, repeats: int,
         runtime: int = 3, write_qd: int = 64, compress: int = 50) -> dict[str, object]:
    if backend not in ("null_blk", "nbd"):
        raise ValueError("backend must be null_blk or nbd")
    if not 0 <= bandwidth <= MAX_BANDWIDTH_MIB_S:
        raise ValueError("bandwidth must be 0..4096 MiB/s (0 is unthrottled)")
    if not 0 <= latency_ns <= 10_000_000_000:
        raise ValueError("latency must be 0..10000000000 ns")
    if not 1 <= repeats <= 20:
        raise ValueError("repeats must be 1..20")
    if not 1 <= runtime <= 3600:
        raise ValueError("runtime must be 1..3600 seconds")
    if not 1 <= write_qd <= 1024:
        raise ValueError("writer QD must be 1..1024")
    if not 0 <= compress <= 100:
        raise ValueError("compressibility must be 0..100 percent")
    selected_policies = policy_list(strategies)
    selected_batches = batch_list(batches, backend, bandwidth)
    cases = [
        {"strategy": strategy, "batch_kib": batch}
        for strategy in selected_policies
        for batch in ((4,) if strategy == "immediate" else selected_batches)
    ]
    if len({(c["strategy"], c["batch_kib"]) for c in cases}) != len(cases):
        raise ValueError("duplicate benchmark configuration")
    if backend == "nbd":
        limitation = (
            "PLANNING ONLY: NBD benchmark execution remains disabled pending "
            "independent pidfd-owned lifecycle and virtual-device qualification")
        runnable = False
    elif bandwidth == 0:
        limitation = ("UNTHROTTLED null_blk: latency/overhead control only, "
                      "NOT evidence for a 20 MiB/s bandwidth plateau")
        runnable = True
    else:
        limitation = ("null_blk per-tick admission only; no module/device "
                      "qualification or independent full-drain attestation")
        runnable = True
    return {
        "schema": "swapz-v22-rootless-benchmark-plan-v1",
        "backend": backend,
        "bandwidth_mib_s": bandwidth,
        "latency_ns": latency_ns,
        "runtime_s": runtime,
        "writer_qd": write_qd,
        "compressibility_pct": compress,
        "null_blk_tick_budget_bytes":
            bandwidth * TICK_QUANTUM_BYTES if backend == "null_blk" and bandwidth else None,
        "strategies": list(selected_policies),
        "batches_kib": list(selected_batches),
        "repeats_requested": repeats,
        "cases": cases,
        "total_planned_runs": len(cases) * repeats,
        "backend_runnable": runnable,
        "limits": limitation,
        "qualified_winner": None,
        "evidence": "PLAN_ONLY_NO_MEASUREMENTS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", default="null_blk")
    parser.add_argument("--mbps", type=int, default=20)
    parser.add_argument("--latency-ns", type=int, default=500000)
    parser.add_argument("--strategies", default="immediate opportunistic staged")
    parser.add_argument("--batches", default="auto",
                        help="auto or ordered space-separated KiB ceilings")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--runtime", type=int, default=3)
    parser.add_argument("--qd", type=int, default=64)
    parser.add_argument("--compress", type=int, default=50)
    parser.add_argument("--emit-batches", action="store_true",
                        help="print admitted space-separated KiB sizes for existing Bash benchmark")
    args = parser.parse_args()
    try:
        result = plan(backend=args.backend, bandwidth=args.mbps,
                      latency_ns=args.latency_ns, strategies=args.strategies,
                      batches=args.batches, repeats=args.repeats,
                      runtime=args.runtime, write_qd=args.qd,
                      compress=args.compress)
        if args.emit_batches:
            if args.backend != "null_blk":
                raise ValueError("NBD execution remains disabled; cannot emit live NBD batches")
            print(" ".join(map(str, result["batches_kib"])))
        else:
            print(json.dumps(result, sort_keys=True))
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
