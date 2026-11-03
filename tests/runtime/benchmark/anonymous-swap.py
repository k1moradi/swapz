#!/usr/bin/env python3
"""Bounded deterministic anonymous-memory worker for real swap-in evidence.

The worker never activates swap or creates cgroups. A privileged scheduler must
place it in a bounded cgroup and arrange exactly one admitted swap device.
"""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import mmap
import os
import re
import resource
import runpy
import stat
import sys
import time
from pathlib import Path

PAGE = 4096
MIB = 1024 * 1024
SCHEMA = "swapz-anonymous-swap-v1"
CONTENT_DEFINITION = "50% deterministic compressible + 50% deterministic entropy anonymous pages"
REPLAY = runpy.run_path(str(Path(__file__).with_name("io-replay.py")))
QUALIFICATION = runpy.run_path(str(Path(__file__).with_name("qualification.py")))
ANONYMOUS_SPEC = QUALIFICATION["CONTRACT"]["workloads"]["anonymous-swap"]


def page_bytes(index: int) -> bytes:
    if index < 0:
        raise ValueError("page index must be nonnegative")
    if index & 1:
        return hashlib.shake_256(index.to_bytes(8, "little") + b"swapz-entropy").digest(PAGE)
    header = b"swapz-anonymous-page:" + str(index).encode("ascii") + b"\0"
    word = hashlib.sha256(index.to_bytes(8, "little") + b"swapz-medium").digest()[:16]
    return header + (word * ((PAGE - len(header) + 15) // 16))[:PAGE - len(header)]


def process_swap_bytes() -> int:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmSwap:"):
            return int(line.split()[1]) * 1024
    return 0


def cgroup_values() -> dict:
    relative = None
    for line in Path("/proc/self/cgroup").read_text().splitlines():
        fields = line.split(":", 2)
        if len(fields) == 3 and fields[:2] == ["0", ""]:
            relative = fields[2]; break
    if relative is None:
        return {"path": None}
    base = (Path("/sys/fs/cgroup") / relative.lstrip("/")).resolve()
    result = {"path": str(base)}
    for name in ("memory.current", "memory.max", "memory.swap.current", "memory.swap.max"):
        key = name.replace(".", "_")
        try:
            text = (base / name).read_text().strip()
            result[key] = text if text == "max" else int(text)
        except (OSError, ValueError):
            result[key] = None
    return result


def swap_inventory(expected_device: str | None) -> list[dict]:
    rows = []
    for line in Path("/proc/swaps").read_text().splitlines()[1:]:
        fields = line.split()
        if len(fields) < 5: raise ValueError("malformed /proc/swaps row")
        path = Path(fields[0]); info = path.stat()
        rows.append({"path": str(path), "type": fields[1], "size_kib": int(fields[2]),
                     "used_kib": int(fields[3]), "priority": int(fields[4]),
                     "device": f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}" if stat.S_ISBLK(info.st_mode) else None})
    if expected_device:
        expected = Path(expected_device).resolve(strict=True).stat()
        if not stat.S_ISBLK(expected.st_mode): raise ValueError("expected swap identity is not block device")
        matches = [row for row in rows if row["device"] == f"{os.major(expected.st_rdev)}:{os.minor(expected.st_rdev)}"]
        if len(rows) != 1 or len(matches) != 1:
            raise ValueError("real anonymous qualification requires exactly the admitted swap device")
    return rows


def lower_disk_name(expected_device: str | None):
    if not expected_device: return None
    info = Path(expected_device).resolve(strict=True).stat()
    sysdev = (Path("/sys/dev/block") / f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}").resolve(strict=True)
    if sysdev.name.startswith("dm-"):
        slaves = list((sysdev / "slaves").iterdir())
        if len(slaves) != 1: raise ValueError("anonymous swap mapper must have exactly one lower")
        sysdev = slaves[0].resolve(strict=True)
    return sysdev.parent.name if (sysdev / "partition").is_file() else sysdev.name


def quiet_window():
    before = REPLAY["host_cpu_snapshot"](); time.sleep(.2); after = REPLAY["host_cpu_snapshot"]()
    observed = REPLAY["host_cpu_delta"](before, after); reasons = []
    if observed.get("status") != "AVAILABLE": reasons.append("quiet-window counters unavailable")
    else:
        if observed.get("busy_fraction", 1) > .25: reasons.append("quiet-window busy exceeds 25%")
        if observed.get("pressure_some_fraction", 1) > .05: reasons.append("quiet-window CPU PSI exceeds 5%")
        if observed.get("steal_fraction", 1) > .01: reasons.append("quiet-window steal exceeds 1%")
    return {"observed": observed, "reasons": reasons}


def latency_summary(values: array.array) -> dict:
    if not values: return {"count": 0, "p50_ns": None, "p95_ns": None, "p99_ns": None, "max_ns": None}
    ordered = sorted(values)
    def percentile(fraction): return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]
    return {"count": len(ordered), "p50_ns": percentile(.50), "p95_ns": percentile(.95),
            "p99_ns": percentile(.99), "max_ns": ordered[-1]}


def run(args):
    if args.bytes % PAGE or not 64 * MIB <= args.bytes <= 4096 * MIB:
        raise ValueError("anonymous bytes must be page aligned and within 64..4096 MiB")
    if not 1 <= args.rounds <= 8: raise ValueError("rounds must be 1..8")
    if not 0 <= args.require_swap_bytes <= args.bytes: raise ValueError("invalid required swap bytes")
    if args.require_swap_bytes and not args.expected_swap_device:
        raise ValueError("real swap qualification requires exact expected swap device")
    if args.expected_swap_device and not re.fullmatch(r"[a-f0-9]{40}", args.source_sha or ""):
        raise ValueError("physical anonymous qualification requires exact source SHA")

    rows_before = swap_inventory(args.expected_swap_device); cgroup_before = cgroup_values()
    if args.expected_swap_device:
        if (args.bytes != ANONYMOUS_SPEC["bytes"] or
                args.rounds != ANONYMOUS_SPEC["rounds"] or
                args.require_swap_bytes != ANONYMOUS_SPEC["minimum_observed_swap_bytes"]):
            raise ValueError("anonymous workload differs from prospective geometry")
        memory_max = cgroup_before.get("memory_max")
        swap_max = cgroup_before.get("memory_swap_max")
        if memory_max != ANONYMOUS_SPEC["memory_max_bytes"]:
            raise ValueError("anonymous cgroup memory.max differs from prospective geometry")
        required_swap_headroom = args.bytes - memory_max
        if swap_max != "max" and (
                type(swap_max) is not int or swap_max < required_swap_headroom):
            raise ValueError("anonymous cgroup memory.swap.max cannot cover working-set excess")
    page_count = args.bytes // PAGE
    args._partial_report = {"schema": SCHEMA, "verdict": "IN_PROGRESS", "stage": "preflight",
                            "workload_id": args.workload_id, "candidate": args.candidate,
                            "source_sha": args.source_sha, "bytes": args.bytes, "pages": page_count,
                            "round_count": args.rounds, "required_swap_bytes": args.require_swap_bytes,
                            "content": CONTENT_DEFINITION, "swap_inventory_before": rows_before,
                            "swap_device_identity": rows_before[0] if args.expected_swap_device else None}
    lower_disk = lower_disk_name(args.expected_swap_device); pre_quiet = quiet_window()
    lower_before = REPLAY["lower_stat"](lower_disk); host_before = REPLAY["host_cpu_snapshot"]()
    cpu_before = resource.getrusage(resource.RUSAGE_SELF)
    mapping = mmap.mmap(-1, args.bytes, flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS,
                        prot=mmap.PROT_READ | mmap.PROT_WRITE)
    try:
        fill_start = time.monotonic_ns()
        for page in range(page_count):
            offset = page * PAGE; mapping[offset:offset + PAGE] = page_bytes(page)
        fill_seconds = (time.monotonic_ns() - fill_start) / 1e9
        rounds, mismatches, combined, max_observed = [], 0, array.array("Q"), 0
        for round_index in range(args.rounds):
            cgroup = cgroup_values(); vm_swap = process_swap_bytes(); rows = swap_inventory(args.expected_swap_device)
            cgroup_swap = cgroup.get("memory_swap_current"); cgroup_swap = cgroup_swap if isinstance(cgroup_swap, int) else 0
            observed = max(vm_swap, cgroup_swap); max_observed = max(max_observed, observed)
            target_used = max((row["used_kib"] * 1024 for row in rows), default=0)
            if observed < args.require_swap_bytes: raise ValueError("workload-specific swap below prospective minimum")
            if args.expected_swap_device and target_used < args.require_swap_bytes:
                raise ValueError("admitted target swap usage below prospective minimum")
            round_lower_before = REPLAY["lower_stat"](lower_disk)
            samples = array.array("Q"); start = time.monotonic_ns()
            for page in range(page_count):
                offset = page * PAGE; expected = page_bytes(page); begin = time.monotonic_ns()
                actual = mapping[offset:offset + PAGE]; elapsed = time.monotonic_ns() - begin
                samples.append(elapsed); combined.append(elapsed)
                if actual != expected:
                    mismatches += 1
                    if mismatches > 16: raise ValueError("anonymous byte oracle exceeded mismatch limit")
            round_lower_after = REPLAY["lower_stat"](lower_disk)
            round_lower = (
                REPLAY["iostat_delta"](round_lower_before, round_lower_after)
                if round_lower_before is not None else None)
            if args.expected_swap_device and (
                    round_lower is None or round_lower["lower_read_bytes"] <= 0):
                raise ValueError("timed anonymous reread produced no admitted lower-device READ bytes")
            rounds.append({"round": round_index, "seconds": (time.monotonic_ns() - start) / 1e9,
                           "observed_swap_bytes_before_read": observed, "target_swap_used_bytes": target_used,
                           "vm_swap_bytes": vm_swap, "cgroup": cgroup,
                           "lower_io": round_lower, "latency": latency_summary(samples)})
            args._partial_report.update(stage=f"round-{round_index + 1}", rounds=list(rounds),
                                        observed_swap_bytes=max_observed,
                                        oracle={"mismatches": mismatches, "verified_pages": page_count * (round_index + 1)})
        if mismatches: raise ValueError("anonymous swap-in byte oracle failed")
        host_after = REPLAY["host_cpu_snapshot"](); cpu_after = resource.getrusage(resource.RUSAGE_SELF)
        lower_after = REPLAY["lower_stat"](lower_disk); rows_after = swap_inventory(args.expected_swap_device)
        post_quiet = quiet_window(); host_cpu = REPLAY["host_cpu_delta"](host_before, host_after)
        lower = REPLAY["iostat_delta"](lower_before, lower_after) if lower_before is not None else None
        if lower is not None:
            lower["lower_write_bytes_per_logical_fill_byte"] = lower["lower_write_bytes"] / args.bytes
            lower["lower_write_requests_per_1000_fill_pages"] = lower["lower_write_requests"] * 1000 / page_count
            lower["lower_read_bytes_per_logical_read_byte"] = lower["lower_read_bytes"] / (args.bytes * args.rounds)
        cpu_seconds = max(0., cpu_after.ru_utime - cpu_before.ru_utime) + max(0., cpu_after.ru_stime - cpu_before.ru_stime)
        read_seconds = sum(row["seconds"] for row in rounds); useful_read_bytes = args.bytes * args.rounds
        reasons = list(pre_quiet["reasons"]) + list(post_quiet["reasons"])
        if host_cpu.get("steal_fraction") is None or host_cpu.get("steal_fraction") > .01:
            reasons.append("timed-arm steal exceeds 1% or is unavailable")
        report = {"schema": SCHEMA, "verdict": "PASS", "workload_id": args.workload_id,
                  "candidate": args.candidate, "source_sha": args.source_sha,
                  "bytes": args.bytes, "pages": page_count, "content": CONTENT_DEFINITION,
                  "round_count": args.rounds, "rounds": rounds, "fill_seconds": fill_seconds,
                  "observed_swap_bytes": max_observed, "required_swap_bytes": args.require_swap_bytes,
                  "swap_inventory_before": rows_before, "swap_inventory_after": rows_after,
                  "swap_device_identity": rows_before[0] if args.expected_swap_device else None,
                  "cgroup_before": cgroup_before, "host_cpu": host_cpu,
                  "performance_screening": {"status": "SCREENED" if not reasons else "EXCLUDED",
                                            "reasons": reasons, "pre": pre_quiet, "post": post_quiet},
                  "swapin_latency": latency_summary(combined),
                  "throughput": {"useful_read_mbps": useful_read_bytes / read_seconds / 1_000_000,
                                 "useful_read_bytes": useful_read_bytes, "read_seconds": read_seconds},
                  "lower_io": lower, "oracle": {"mismatches": mismatches, "verified_pages": page_count * args.rounds},
                  "cpu": {"user_seconds": max(0., cpu_after.ru_utime - cpu_before.ru_utime),
                          "system_seconds": max(0., cpu_after.ru_stime - cpu_before.ru_stime),
                          "peak_rss_bytes": cpu_after.ru_maxrss * 1024,
                          "measured_cpu_seconds_per_useful_byte": cpu_seconds / (args.bytes + useful_read_bytes)}}
        args._partial_report = report
        output = Path(args.result)
        if output.exists(): raise ValueError("refusing to overwrite anonymous swap result")
        output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(json.dumps(report, sort_keys=True))
    finally:
        mapping.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload-id", default="anonymous-swap")
    parser.add_argument("--candidate", choices=("raw", "swapz"), required=True)
    parser.add_argument("--source-sha", required=True); parser.add_argument("--bytes", type=int, required=True)
    parser.add_argument("--rounds", type=int, default=3); parser.add_argument("--require-swap-bytes", type=int, default=134217728)
    parser.add_argument("--expected-swap-device"); parser.add_argument("--result", required=True)
    args = parser.parse_args(); error = None
    try: run(args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        failure = dict(getattr(args, "_partial_report", {}) or {})
        failure.update({"schema": SCHEMA, "verdict": "FAIL", "workload_id": args.workload_id,
                        "candidate": args.candidate, "source_sha": args.source_sha, "failure_reason": str(exc)})
        try:
            output = Path(args.result)
            if not output.exists(): output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n")
        except OSError: pass
        error = exc
    if error is not None: parser.exit(2, "BLOCKED/FAIL: " + str(error) + "\n")


if __name__ == "__main__":
    main()
