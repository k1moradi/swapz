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
import math
import mmap
import os
import re
import resource
import runpy
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

from evidence_io import write_new_json

PAGE = 4096
MIB = 1024 * 1024
SCHEMA = "swapz-anonymous-swap-v1"
CONTENT_DEFINITION = "50% deterministic compressible + 50% deterministic entropy anonymous pages"
REPLAY = runpy.run_path(str(Path(__file__).with_name("io-replay.py")))
QUALIFICATION = runpy.run_path(str(Path(__file__).with_name("qualification.py")))
ANONYMOUS_SPEC = QUALIFICATION["CONTRACT"]["workloads"]["anonymous-swap"]


class BenchmarkInterrupted(Exception):
    pass


def interrupt_benchmark(signum, _frame) -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    raise BenchmarkInterrupted(f"interrupted by signal {signum}")


def require_source_identity(source_sha: str) -> None:
    """Read-only physical provenance check; never mutate the checkout."""
    root = Path(__file__).resolve().parents[3]

    def git(*args):
        result = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True,
            text=True, check=False, timeout=20)
        if result.returncode:
            raise ValueError("physical anonymous source verification failed")
        return result.stdout.strip()

    if git("rev-parse", "HEAD") != source_sha or \
            git("rev-parse", "origin/main") != source_sha:
        raise ValueError(
            "physical anonymous qualification requires HEAD == origin/main == source SHA")
    if git("status", "--porcelain"):
        raise ValueError("physical anonymous qualification requires clean source")


def require_isolated_cgroup(cgroup: dict) -> None:
    """Cgroup-v2 hierarchical fault/swap counters must belong to this worker."""
    path = cgroup.get("path")
    if not isinstance(path, str) or path in ("/", "/sys/fs/cgroup"):
        raise ValueError("physical anonymous qualification requires a private cgroup")
    base = Path(path)
    processes = (base / "cgroup.procs").read_text(encoding="ascii").split()
    if processes != [str(os.getpid())]:
        raise ValueError("anonymous qualification cgroup has foreign processes")
    if any(child.is_dir() for child in base.iterdir()):
        raise ValueError("anonymous qualification cgroup has descendant cgroups")


def page_bytes(index: int) -> bytes:
    if index < 0:
        raise ValueError("page index must be nonnegative")
    if index & 1:
        return hashlib.shake_256(index.to_bytes(8, "little") + b"swapz-entropy").digest(PAGE)
    header = b"swapz-anonymous-page:" + str(index).encode("ascii") + b"\0"
    word = hashlib.sha256(index.to_bytes(8, "little") + b"swapz-medium").digest()[:16]
    return header + (word * ((PAGE - len(header) + 15) // 16))[:PAGE - len(header)]


def process_cpu_delta(before, after) -> dict:
    user = max(0.0, after.ru_utime - before.ru_utime)
    system = max(0.0, after.ru_stime - before.ru_stime)
    return {
        "user_seconds": user,
        "system_seconds": system,
        "total_seconds": user + system,
    }


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


def physical_lower_identity(sysdev: Path) -> dict:
    """Resolve the exact removable partition backing one anonymous swap arm."""
    if not (sysdev / "partition").is_file():
        raise ValueError("anonymous physical lower must be a partition")
    lower_device = (sysdev / "dev").read_text().strip()
    if not re.fullmatch(r"[0-9]+:[0-9]+", lower_device):
        raise ValueError("anonymous physical lower major:minor is malformed")
    partuuid = subprocess.run(
        ["lsblk", "-dnro", "PARTUUID", "/dev/" + sysdev.name],
        text=True, capture_output=True, check=True, timeout=10).stdout.strip()
    partuuid = QUALIFICATION["normalize_partuuid"](partuuid)
    if partuuid is None:
        raise ValueError("anonymous physical lower PARTUUID is malformed")
    size_bytes = int((sysdev / "size").read_text()) * 512
    parent = sysdev.parent
    parent_device = (parent / "dev").read_text().strip()
    if (not re.fullmatch(r"[0-9]+:[0-9]+", parent_device) or
            (parent / "removable").read_text().strip() != "1"):
        raise ValueError("anonymous physical parent identity is invalid")
    parent_model = (parent / "device/model").read_text().strip()
    parent_transport = subprocess.run(
        ["lsblk", "-dnro", "TRAN", "/dev/" + parent.name],
        text=True, capture_output=True, check=True, timeout=10).stdout.strip()
    if not parent_model or not parent_transport or size_bytes <= 0:
        raise ValueError("anonymous physical lower/parent identity is incomplete")
    return {
        "lower_device": lower_device,
        "physical_partuuid": partuuid,
        "physical_device_bytes": size_bytes,
        "parent_major_minor": parent_device,
        "parent_model": parent_model,
        "parent_transport": parent_transport,
    }


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
        "physical_partuuid": None,
        "physical_device_bytes": None,
        "parent_major_minor": None,
        "parent_model": None,
        "parent_transport": None,
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
            **physical_lower_identity(lower),
        })
    else:
        if candidate != "raw":
            raise ValueError("swapz anonymous arm requires the exact DM mapper")
        if expected_dm_uuid:
            raise ValueError("raw anonymous arm must not name a DM UUID")
        identity.update(physical_lower_identity(sysdev))
        if identity["lower_device"] != identity["device"]:
            raise ValueError("raw anonymous lower identity differs from device")
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
    if not values:
        return {
            "count": 0, "p50_ns": None, "p95_ns": None,
            "p99_ns": None, "max_ns": None,
            "histogram": {"count": 0, "max_ns": None, "bins": []},
        }
    bins = {}
    maximum = 0
    for raw_value in values:
        value = int(raw_value)
        index = QUALIFICATION["latency_bin_index"](value)
        bins[index] = bins.get(index, 0) + 1
        maximum = max(maximum, value)
    rows = [[index, bins[index]] for index in sorted(bins)]

    def percentile(fraction):
        target = max(1, math.ceil(len(values) * fraction))
        seen = 0
        for index, count in rows:
            seen += count
            if seen >= target:
                return QUALIFICATION["latency_bin_upper"](index)
        raise ValueError("anonymous latency histogram is incomplete")

    return {
        "count": len(values),
        "p50_ns": percentile(.50),
        "p95_ns": percentile(.95),
        "p99_ns": percentile(.99),
        "max_ns": maximum,
        "histogram": {
            "count": len(values), "max_ns": maximum, "bins": rows,
        },
    }


def run(args):
    arm_started_monotonic_ns = time.monotonic_ns()
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

    arm_boot_id = (Path("/proc/sys/kernel/random/boot_id").read_text().strip()
                   if args.expected_swap_device else None)
    if args.expected_swap_device:
        require_source_identity(args.source_sha)
    rows_before = swap_inventory(args.expected_swap_device)
    cgroup_before = cgroup_values()
    if args.expected_swap_device:
        require_isolated_cgroup(cgroup_before)
        if any(row["used_kib"] != 0 for row in rows_before):
            raise ValueError("anonymous qualification swap device is not initially empty")
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
        "arm_started_monotonic_ns": arm_started_monotonic_ns,
        "arm_boot_id": arm_boot_id,
    }
    if args.expected_swap_device:
        args._partial_report["loaded_module_provenance"] = (
            QUALIFICATION["capture_loaded_module_provenance"](
                args.source_sha, args.candidate == "swapz"))
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
        fill_cpu_before = resource.getrusage(resource.RUSAGE_SELF)
        fill_start = time.monotonic_ns()
        for page in range(page_count):
            offset = page * PAGE
            mapping[offset:offset + PAGE] = page_bytes(page)
        fill_seconds = (time.monotonic_ns() - fill_start) / 1e9
        fill_cpu_after = resource.getrusage(resource.RUSAGE_SELF)
        fill_process_cpu = process_cpu_delta(fill_cpu_before, fill_cpu_after)

        rounds, mismatches, combined, max_observed = [], 0, array.array("Q"), 0
        for round_index in range(args.rounds):
            cgroup = cgroup_values()
            if args.expected_swap_device:
                require_isolated_cgroup(cgroup)
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
            round_cpu_before = resource.getrusage(resource.RUSAGE_SELF)
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
            round_cpu_after = resource.getrusage(resource.RUSAGE_SELF)
            round_process_cpu = process_cpu_delta(
                round_cpu_before, round_cpu_after)
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
            first_touch_latency = latency_summary(samples)
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
                "latency": first_touch_latency,
                "fault_first_touch_latency": first_touch_latency,
                "process_cpu": {
                    **round_process_cpu,
                    "scope": (
                        "worker-process CPU during page recipe generation, "
                        "first-byte accesses, and 4KiB copy/verification; "
                        "kernel swapz workers are excluded"),
                },
                "timing": {
                    "scope": (
                        "first-touch timing includes Python one-byte access "
                        "overhead and both resident and swap-faulted pages; "
                        "kernel faults and swap I/O are verified only in aggregate. "
                        "Page generation, 4KiB copy and byte comparison "
                        "are excluded from the individual latency sample"),
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
        if args.expected_swap_device:
            require_isolated_cgroup(cgroup_after)
            if swap_device_identity(
                    args.expected_swap_device, args.candidate,
                    args.expected_dm_uuid) != identity:
                raise ValueError("anonymous swap-device identity changed during arm")
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

        acceptance_process_cpu = process_cpu_delta(cpu_before, cpu_after)
        process_user = acceptance_process_cpu["user_seconds"]
        process_system = acceptance_process_cpu["system_seconds"]
        process_cpu_seconds = acceptance_process_cpu["total_seconds"]
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
        if args.expected_swap_device:
            if arm_vmstat["pswpout"] <= 0:
                raise ValueError("anonymous workload produced no pswpout")
            if target_io is None or target_io["target_write_bytes"] <= 0:
                raise ValueError("anonymous workload produced no exact-target WRITE")
            if lower is None or lower["lower_write_bytes"] <= 0:
                raise ValueError("anonymous workload produced no backing-device WRITE")
        report = {
            "schema": SCHEMA, "verdict": "PASS", "workload_id": args.workload_id,
            "candidate": args.candidate, "source_sha": args.source_sha,
            "arm_started_monotonic_ns": arm_started_monotonic_ns,
            "arm_finished_monotonic_ns": time.monotonic_ns(),
            "arm_boot_id": arm_boot_id,
            "bytes": args.bytes, "pages": page_count, "content": CONTENT_DEFINITION,
            "round_count": args.rounds, "rounds": rounds,
            "fill_seconds": fill_seconds, "observed_swap_bytes": max_observed,
            "required_swap_bytes": args.require_swap_bytes,
            "swap_inventory_before": rows_before,
            "swap_inventory_after": rows_after,
            "swap_device_identity": identity,
            "loaded_module_provenance":
                args._partial_report.get("loaded_module_provenance"),
            "cgroup_before": cgroup_before, "cgroup_after": cgroup_after,
            "host_cpu": host_cpu,
            "performance_screening": {
                "status": "SCREENED" if not reasons else "EXCLUDED",
                "reasons": reasons, "pre": pre_quiet, "post": post_quiet,
            },
            "swapin_latency": latency_summary(combined),
            "swapin_latency_scope": (
                "first-byte Python access latency includes resident and "
                "swap-faulted pages; positive per-round pswpin, cgroup major "
                "faults, target READ and backing READ independently establish "
                "aggregate swap-in, not individual-sample fault attribution; "
                "page generation and full-page verification are excluded"),
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
                "phase_process_cpu": {
                    "fill": fill_process_cpu,
                    "reread_rounds": [
                        row["process_cpu"] for row in rounds],
                    "scope": (
                        "diagnostic process-only phase attribution; the frozen "
                        "acceptance metric remains the whole-arm process CPU "
                        "plus exported swapz worker CPU"),
                },
                "peak_rss_bytes": cpu_after.ru_maxrss * 1024,
                "scope": (
                    "workload process user+system CPU plus exported swapz "
                    "worker CPU; block softirq/other kernel work and unrelated "
                    "host CPU are excluded and host_cpu is reported separately"),
            },
        }
        args._partial_report = report
        write_new_json(Path(args.result), report)
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
    previous_sigint = signal.signal(signal.SIGINT, interrupt_benchmark)
    previous_sigterm = signal.signal(signal.SIGTERM, interrupt_benchmark)
    try: run(args)
    except (OSError, ValueError, KeyError, TypeError, BenchmarkInterrupted,
            subprocess.SubprocessError) as exc:
        failure = dict(getattr(args, "_partial_report", {}) or {})
        failure.update({"schema": SCHEMA, "verdict": "FAIL", "workload_id": args.workload_id,
                        "candidate": args.candidate, "source_sha": args.source_sha, "failure_reason": str(exc)})
        try:
            write_new_json(Path(args.result), failure)
        except (OSError, ValueError):
            # Preserve any earlier result and the original worker exception.
            pass
        error = exc
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)
    if error is not None: parser.exit(2, "BLOCKED/FAIL: " + str(error) + "\n")


if __name__ == "__main__":
    main()
