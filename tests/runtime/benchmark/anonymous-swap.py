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
import subprocess
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


def _read_counter_file(path: Path):
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except FileNotFoundError:
        return None
    counters = {}
    for line in lines:
        fields = line.split()
        if len(fields) != 2:
            raise ValueError(f"malformed counter file {path}")
        try:
            value = int(fields[1])
        except ValueError as exc:
            raise ValueError(f"non-numeric counter in {path}") from exc
        if value < 0:
            raise ValueError(f"negative counter in {path}")
        counters[fields[0]] = value
    return counters


def cgroup_values() -> dict:
    relative = None
    for line in Path("/proc/self/cgroup").read_text().splitlines():
        fields = line.split(":", 2)
        if len(fields) == 3 and fields[:2] == ["0", ""]:
            relative = fields[2]
            break
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
    for name in ("memory.stat", "memory.events", "memory.swap.events"):
        key = name.replace(".", "_")
        try:
            result[key] = _read_counter_file(base / name)
        except OSError:
            result[key] = None
    return result


def vmstat_snapshot() -> dict:
    wanted = {"pswpin", "pswpout"}
    counters = {}
    for line in Path("/proc/vmstat").read_text(encoding="ascii").splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0] in wanted:
            counters[fields[0]] = int(fields[1])
    if set(counters) != wanted or any(value < 0 for value in counters.values()):
        raise ValueError("required pswpin/pswpout counters are unavailable")
    return counters


def monotonic_counter_delta(before: dict, after: dict, names=None) -> dict:
    keys = tuple(names) if names is not None else tuple(before)
    result = {}
    for key in keys:
        start = before.get(key)
        end = after.get(key)
        if type(start) is not int or type(end) is not int or end < start:
            raise ValueError("counter reset or missing: " + key)
        result[key] = end - start
    return result


def cgroup_counter_delta(before: dict, after: dict) -> dict:
    result = {}
    for key in ("memory_stat", "memory_events", "memory_swap_events"):
        start = before.get(key)
        end = after.get(key)
        if start is None and end is None:
            result[key] = None
        elif not isinstance(start, dict) or not isinstance(end, dict):
            result[key] = None
        else:
            common = tuple(sorted(set(start) & set(end)))
            result[key] = monotonic_counter_delta(start, end, common)
    start_swap = before.get("memory_swap_current")
    end_swap = after.get("memory_swap_current")
    result["memory_swap_current_delta_bytes"] = (
        end_swap - start_swap
        if type(start_swap) is int and type(end_swap) is int else None)
    return result


def _device_sysfs(expected_device: str) -> tuple[Path, os.stat_result]:
    resolved = Path(expected_device).resolve(strict=True)
    info = resolved.stat()
    if not stat.S_ISBLK(info.st_mode):
        raise ValueError("expected swap identity is not block device")
    sysdev = (Path("/sys/dev/block") /
              f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}").resolve(strict=True)
    return sysdev, info


def device_stat(expected_device: str | None):
    if not expected_device:
        return None
    sysdev, _ = _device_sysfs(expected_device)
    values = [int(value) for value in (sysdev / "stat").read_text().split()]
    if len(values) < 16:
        raise ValueError("insufficient target device stat fields")
    return values


def target_io_delta(before, after):
    lower = REPLAY["iostat_delta"](before, after)
    if lower is None:
        return None
    return {
        key.replace("lower_", "target_", 1): value
        for key, value in lower.items()
    }


def swap_device_identity(expected_device: str, candidate: str,
                         expected_dm_uuid: str | None) -> dict:
    sysdev, info = _device_sysfs(expected_device)
    identity = {
        "requested_path": expected_device,
        "resolved_path": str(Path(expected_device).resolve(strict=True)),
        "device": f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}",
        "kernel_name": sysdev.name,
        "dm_name": None,
        "dm_uuid": None,
        "dm_target": None,
        "lower_device": None,
    }
    if sysdev.name.startswith("dm-"):
        if candidate != "swapz":
            raise ValueError("raw anonymous arm unexpectedly uses a DM target")
        dm_name = (sysdev / "dm/name").read_text().strip()
        dm_uuid = (sysdev / "dm/uuid").read_text().strip()
        if not expected_dm_uuid or dm_uuid != expected_dm_uuid:
            raise ValueError("anonymous swap mapper UUID mismatch")
        slaves = list((sysdev / "slaves").iterdir())
        if len(slaves) != 1:
            raise ValueError("anonymous swap mapper must have exactly one lower")
        lower = slaves[0].resolve(strict=True)
        table = subprocess.run(
            ["dmsetup", "table", dm_name], text=True, capture_output=True,
            check=False, timeout=10)
        if table.returncode:
            raise ValueError("anonymous swap mapper table unavailable")
        rows = [row.split() for row in table.stdout.splitlines() if row.strip()]
        if len(rows) != 1 or len(rows[0]) < 3 or rows[0][2] != "swapz":
            raise ValueError("anonymous swap mapper is not exactly one swapz target")
        identity.update({
            "dm_name": dm_name,
            "dm_uuid": dm_uuid,
            "dm_target": "swapz",
            "lower_device": (lower / "dev").read_text().strip(),
        })
    else:
        if candidate != "raw":
            raise ValueError("swapz anonymous arm requires the exact DM mapper")
        if expected_dm_uuid:
            raise ValueError("raw anonymous arm must not name a DM UUID")
        identity["lower_device"] = identity["device"]
    return identity


def swap_inventory(expected_device: str | None) -> list[dict]:
    rows = []
    for line in Path("/proc/swaps").read_text().splitlines()[1:]:
        fields = line.split()
        if len(fields) < 5:
            raise ValueError("malformed /proc/swaps row")
        path = Path(fields[0])
        info = path.stat()
        rows.append({
            "path": str(path), "type": fields[1], "size_kib": int(fields[2]),
            "used_kib": int(fields[3]), "priority": int(fields[4]),
            "device": (
                f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}"
                if stat.S_ISBLK(info.st_mode) else None),
        })
    if expected_device:
        _, expected = _device_sysfs(expected_device)
        device = f"{os.major(expected.st_rdev)}:{os.minor(expected.st_rdev)}"
        matches = [row for row in rows if row["device"] == device]
        if len(rows) != 1 or len(matches) != 1:
            raise ValueError(
                "real anonymous qualification requires exactly the admitted swap device")
    return rows


def lower_disk_name(expected_device: str | None):
    if not expected_device:
        return None
    sysdev, _ = _device_sysfs(expected_device)
    if sysdev.name.startswith("dm-"):
        slaves = list((sysdev / "slaves").iterdir())
        if len(slaves) != 1:
            raise ValueError("anonymous swap mapper must have exactly one lower")
        sysdev = slaves[0].resolve(strict=True)
    return sysdev.parent.name if (sysdev / "partition").is_file() else sysdev.name


SWAPZ_WORKER_CPU_FIELDS = (
    "ordered_worker_cpu_ns", "prep_worker_cpu_ns", "read_worker_cpu_ns")


def swapz_worker_cpu_snapshot(identity: dict | None):
    if not identity or not identity.get("dm_uuid"):
        return None
    status = subprocess.run(
        ["dmsetup", "status", identity["dm_name"]], text=True,
        capture_output=True, check=False, timeout=10)
    if status.returncode:
        raise ValueError("anonymous swapz worker CPU telemetry unavailable")
    counters = {}
    for field in SWAPZ_WORKER_CPU_FIELDS:
        match = re.search(
            r"(?:^|\s)" + re.escape(field) + r"=(\d+)(?:\s|$)",
            status.stdout)
        if not match:
            raise ValueError("anonymous swapz status missing " + field)
        counters[field] = int(match.group(1))
    return counters


def swapz_worker_cpu_delta(before, after) -> dict:
    if before is None and after is None:
        return {field: 0 for field in SWAPZ_WORKER_CPU_FIELDS}
    if before is None or after is None:
        raise ValueError("incomplete anonymous swapz worker CPU telemetry")
    return monotonic_counter_delta(before, after, SWAPZ_WORKER_CPU_FIELDS)


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
    if not 1 <= args.rounds <= 8:
        raise ValueError("rounds must be 1..8")
    if not 0 <= args.require_swap_bytes <= args.bytes:
        raise ValueError("invalid required swap bytes")
    if args.require_swap_bytes and not args.expected_swap_device:
        raise ValueError("real swap qualification requires exact expected swap device")
    if args.expected_swap_device and not re.fullmatch(r"[a-f0-9]{40}", args.source_sha or ""):
        raise ValueError("physical anonymous qualification requires exact source SHA")
    if args.expected_swap_device and args.candidate == "swapz" and not args.expected_dm_uuid:
        raise ValueError("physical swapz anonymous qualification requires exact DM UUID")
    if args.candidate == "raw" and args.expected_dm_uuid:
        raise ValueError("raw anonymous qualification must not name a DM UUID")

    rows_before = swap_inventory(args.expected_swap_device)
    cgroup_before = cgroup_values()
    identity = (
        swap_device_identity(
            args.expected_swap_device, args.candidate, args.expected_dm_uuid)
        if args.expected_swap_device else None)
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
        memory_stat = cgroup_before.get("memory_stat")
        if not isinstance(memory_stat, dict) or type(memory_stat.get("pgmajfault")) is not int:
            raise ValueError("anonymous cgroup pgmajfault counter is unavailable")

    page_count = args.bytes // PAGE
    args._partial_report = {
        "schema": SCHEMA, "verdict": "IN_PROGRESS", "stage": "preflight",
        "workload_id": args.workload_id, "candidate": args.candidate,
        "source_sha": args.source_sha, "bytes": args.bytes, "pages": page_count,
        "round_count": args.rounds, "required_swap_bytes": args.require_swap_bytes,
        "content": CONTENT_DEFINITION, "swap_inventory_before": rows_before,
        "swap_device_identity": identity,
    }
    lower_disk = lower_disk_name(args.expected_swap_device)
    pre_quiet = quiet_window()
    lower_before = REPLAY["lower_stat"](lower_disk)
    target_before = device_stat(args.expected_swap_device)
    vmstat_before = vmstat_snapshot()
    host_before = REPLAY["host_cpu_snapshot"]()
    cpu_before = resource.getrusage(resource.RUSAGE_SELF)
    worker_cpu_before = swapz_worker_cpu_snapshot(identity)
    mapping = mmap.mmap(
        -1, args.bytes, flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS,
        prot=mmap.PROT_READ | mmap.PROT_WRITE)
    try:
        fill_start = time.monotonic_ns()
        for page in range(page_count):
            offset = page * PAGE
            mapping[offset:offset + PAGE] = page_bytes(page)
        fill_seconds = (time.monotonic_ns() - fill_start) / 1e9

        rounds, mismatches, combined, max_observed = [], 0, array.array("Q"), 0
        for round_index in range(args.rounds):
            cgroup = cgroup_values()
            vm_swap = process_swap_bytes()
            rows = swap_inventory(args.expected_swap_device)
            cgroup_swap = cgroup.get("memory_swap_current")
            cgroup_swap = cgroup_swap if isinstance(cgroup_swap, int) else 0
            observed = max(vm_swap, cgroup_swap)
            max_observed = max(max_observed, observed)
            target_used = max(
                (row["used_kib"] * 1024 for row in rows), default=0)
            if observed < args.require_swap_bytes:
                raise ValueError("workload-specific swap below prospective minimum")
            if args.expected_swap_device and target_used < args.require_swap_bytes:
                raise ValueError("admitted target swap usage below prospective minimum")

            round_vmstat_before = vmstat_snapshot()
            round_cgroup_before = cgroup_values()
            round_target_before = device_stat(args.expected_swap_device)
            round_lower_before = REPLAY["lower_stat"](lower_disk)
            samples = array.array("Q")
            verification_ns = 0
            start = time.monotonic_ns()
            for page in range(page_count):
                offset = page * PAGE
                expected = page_bytes(page)
                begin = time.monotonic_ns()
                _ = mapping[offset]
                elapsed = time.monotonic_ns() - begin
                samples.append(elapsed)
                combined.append(elapsed)

                verify_begin = time.monotonic_ns()
                actual = mapping[offset:offset + PAGE]
                if actual != expected:
                    mismatches += 1
                    if mismatches > 16:
                        raise ValueError(
                            "anonymous byte oracle exceeded mismatch limit")
                verification_ns += time.monotonic_ns() - verify_begin
            round_seconds = (time.monotonic_ns() - start) / 1e9
            round_lower_after = REPLAY["lower_stat"](lower_disk)
            round_target_after = device_stat(args.expected_swap_device)
            round_cgroup_after = cgroup_values()
            round_vmstat_after = vmstat_snapshot()

            round_lower = (
                REPLAY["iostat_delta"](round_lower_before, round_lower_after)
                if round_lower_before is not None else None)
            round_target = target_io_delta(
                round_target_before, round_target_after)
            vmstat = monotonic_counter_delta(
                round_vmstat_before, round_vmstat_after, ("pswpin", "pswpout"))
            cgroup_delta = cgroup_counter_delta(
                round_cgroup_before, round_cgroup_after)
            pgmajfault = (
                (cgroup_delta.get("memory_stat") or {}).get("pgmajfault"))
            if args.expected_swap_device:
                if round_lower is None or round_lower["lower_read_bytes"] <= 0:
                    raise ValueError(
                        "timed anonymous reread produced no backing-device READ bytes")
                if round_target is None or round_target["target_read_bytes"] <= 0:
                    raise ValueError(
                        "timed anonymous reread produced no exact-target READ bytes")
                if vmstat["pswpin"] <= 0:
                    raise ValueError(
                        "timed anonymous reread produced no pswpin delta")
                if type(pgmajfault) is not int or pgmajfault <= 0:
                    raise ValueError(
                        "timed anonymous reread produced no cgroup pgmajfault delta")

            first_touch_ns = sum(samples)
            total_ns = int(round_seconds * 1e9)
            rounds.append({
                "round": round_index, "seconds": round_seconds,
                "observed_swap_bytes_before_read": observed,
                "target_swap_used_bytes": target_used,
                "vm_swap_bytes": vm_swap, "cgroup": cgroup,
                "lower_io": round_lower, "target_io": round_target,
                "vmstat": {
                    "pswpin_pages": vmstat["pswpin"],
                    "pswpout_pages": vmstat["pswpout"],
                    "pswpin_bytes": vmstat["pswpin"] * PAGE,
                    "pswpout_bytes": vmstat["pswpout"] * PAGE,
                },
                "cgroup_delta": cgroup_delta,
                "latency": latency_summary(samples),
                "fault_first_touch_latency": latency_summary(samples),
                "timing": {
                    "scope": (
                        "fault_first_touch times one-byte anonymous accesses; "
                        "page generation, 4KiB Python copy and byte verification "
                        "are outside that latency sample"),
                    "fault_first_touch_seconds": first_touch_ns / 1e9,
                    "verification_copy_compare_seconds": verification_ns / 1e9,
                    "other_loop_seconds": max(
                        0, total_ns - first_touch_ns - verification_ns) / 1e9,
                },
            })
            args._partial_report.update(
                stage=f"round-{round_index + 1}", rounds=list(rounds),
                observed_swap_bytes=max_observed,
                oracle={
                    "mismatches": mismatches,
                    "verified_pages": page_count * (round_index + 1),
                })
        if mismatches:
            raise ValueError("anonymous swap-in byte oracle failed")

        worker_cpu_after = swapz_worker_cpu_snapshot(identity)
        cpu_after = resource.getrusage(resource.RUSAGE_SELF)
        host_after = REPLAY["host_cpu_snapshot"]()
        vmstat_after = vmstat_snapshot()
        target_after = device_stat(args.expected_swap_device)
        lower_after = REPLAY["lower_stat"](lower_disk)
        rows_after = swap_inventory(args.expected_swap_device)
        cgroup_after = cgroup_values()
        post_quiet = quiet_window()
        host_cpu = REPLAY["host_cpu_delta"](host_before, host_after)
        lower = (
            REPLAY["iostat_delta"](lower_before, lower_after)
            if lower_before is not None else None)
        target_io = target_io_delta(target_before, target_after)
        if lower is not None:
            lower["lower_write_bytes_per_logical_fill_byte"] = (
                lower["lower_write_bytes"] / args.bytes)
            lower["lower_write_requests_per_1000_fill_pages"] = (
                lower["lower_write_requests"] * 1000 / page_count)
            lower["lower_read_bytes_per_logical_read_byte"] = (
                lower["lower_read_bytes"] / (args.bytes * args.rounds))

        process_user = max(0., cpu_after.ru_utime - cpu_before.ru_utime)
        process_system = max(0., cpu_after.ru_stime - cpu_before.ru_stime)
        process_cpu_seconds = process_user + process_system
        worker_cpu = swapz_worker_cpu_delta(
            worker_cpu_before, worker_cpu_after)
        worker_cpu_seconds = sum(worker_cpu.values()) / 1e9
        attributed_cpu_seconds = process_cpu_seconds + worker_cpu_seconds
        read_seconds = sum(row["seconds"] for row in rounds)
        useful_read_bytes = args.bytes * args.rounds
        reasons = list(pre_quiet["reasons"]) + list(post_quiet["reasons"])
        if host_cpu.get("steal_fraction") is None or host_cpu.get("steal_fraction") > .01:
            reasons.append("timed-arm steal exceeds 1% or is unavailable")

        arm_vmstat = monotonic_counter_delta(
            vmstat_before, vmstat_after, ("pswpin", "pswpout"))
        report = {
            "schema": SCHEMA, "verdict": "PASS", "workload_id": args.workload_id,
            "candidate": args.candidate, "source_sha": args.source_sha,
            "bytes": args.bytes, "pages": page_count, "content": CONTENT_DEFINITION,
            "round_count": args.rounds, "rounds": rounds,
            "fill_seconds": fill_seconds, "observed_swap_bytes": max_observed,
            "required_swap_bytes": args.require_swap_bytes,
            "swap_inventory_before": rows_before,
            "swap_inventory_after": rows_after,
            "swap_device_identity": identity,
            "cgroup_before": cgroup_before, "cgroup_after": cgroup_after,
            "host_cpu": host_cpu,
            "performance_screening": {
                "status": "SCREENED" if not reasons else "EXCLUDED",
                "reasons": reasons, "pre": pre_quiet, "post": post_quiet,
            },
            "swapin_latency": latency_summary(combined),
            "swapin_latency_scope": (
                "one-byte first-touch anonymous page-fault latency; excludes "
                "page recipe generation and subsequent 4KiB copy/verification"),
            "throughput": {
                "useful_read_mbps": useful_read_bytes / read_seconds / 1_000_000,
                "useful_read_bytes": useful_read_bytes,
                "read_seconds": read_seconds,
            },
            "lower_io": lower, "target_io": target_io,
            "anonymous_swap_attribution": {
                "vmstat": {
                    "pswpin_pages": arm_vmstat["pswpin"],
                    "pswpout_pages": arm_vmstat["pswpout"],
                    "pswpin_bytes": arm_vmstat["pswpin"] * PAGE,
                    "pswpout_bytes": arm_vmstat["pswpout"] * PAGE,
                },
                "cgroup_delta": cgroup_counter_delta(
                    cgroup_before, cgroup_after),
                "target_io": target_io,
                "backing_io": lower,
                "identity": identity,
            },
            "oracle": {
                "mismatches": mismatches,
                "verified_pages": page_count * args.rounds,
            },
            "cpu": {
                "workload_process_user_seconds": process_user,
                "workload_process_system_seconds": process_system,
                "workload_process_cpu_seconds": process_cpu_seconds,
                "exported_swapz_worker_cpu_seconds": worker_cpu_seconds,
                "exported_swapz_worker_cpu": worker_cpu,
                "attributed_cpu_seconds": attributed_cpu_seconds,
                "measured_cpu_seconds_per_useful_byte": (
                    attributed_cpu_seconds / (args.bytes + useful_read_bytes)),
                "peak_rss_bytes": cpu_after.ru_maxrss * 1024,
                "scope": (
                    "workload process user+system CPU plus exported swapz "
                    "worker CPU; block softirq/other kernel work and unrelated "
                    "host CPU are excluded and host_cpu is reported separately"),
            },
        }
        args._partial_report = report
        output = Path(args.result)
        if output.exists():
            raise ValueError("refusing to overwrite anonymous swap result")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(json.dumps(report, sort_keys=True))
    finally:
        mapping.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload-id", default="anonymous-swap")
    parser.add_argument("--candidate", choices=("raw", "swapz"), required=True)
    parser.add_argument("--source-sha", required=True); parser.add_argument("--bytes", type=int, required=True)
    parser.add_argument("--rounds", type=int, default=3); parser.add_argument("--require-swap-bytes", type=int, default=134217728)
    parser.add_argument("--expected-swap-device")
    parser.add_argument("--expected-dm-uuid")
    parser.add_argument("--result", required=True)
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
