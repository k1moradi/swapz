#!/usr/bin/env python3
"""Read-only physical-host snapshot and immutable campaign evidence sealer.

This helper never activates swap, creates/removes mappings, writes block
devices, or schedules benchmark work. The physical scheduler owns execution
ordering; this helper only records and seals evidence.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import os
import re
import runpy
import stat
import subprocess
import time
from pathlib import Path

from evidence_io import write_new_json

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_PATH = Path(__file__)
QUALIFICATION_PATH = EVIDENCE_PATH.with_name("qualification.py")
ACCEPTANCE_MANIFEST = ROOT / "docs/production-acceptance.json"
AMENDMENT_MANIFEST = Path(__file__).with_name(
    "physical-qualification-amendment-v2.json")

HOST_SCHEMA = "swapz-performance-host-snapshot-v1"
CAMPAIGN_SCHEMA = "swapz-performance-campaign-evidence-v1"
PAIR_SCHEMA = "swapz-performance-pair-v1"
SUMMARY_SCHEMA = "swapz-performance-summary-v1"
MAX_EVIDENCE_FILE_BYTES = 64 * 1024 * 1024
MAX_EVIDENCE_DIAGNOSTICS = 96
QUALIFICATION = runpy.run_path(str(QUALIFICATION_PATH))
RAM_VALIDATOR_PATH = EVIDENCE_PATH.with_name("metadata_ram_evidence.py")
RAM_VALIDATOR = runpy.run_path(str(RAM_VALIDATOR_PATH))


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key}")
        result[key] = value
    return result


def identical_json_types_and_values(left, right):
    """Prevent bool/int or float/int coercion in nested JSON provenance."""
    return (json.dumps(left, sort_keys=True, allow_nan=False) ==
            json.dumps(right, sort_keys=True, allow_nan=False))


def reject_json_constant(value):
    raise ValueError(f"non-finite JSON number {value}")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha(data: bytes) -> str:
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {len(data)}\0".encode("ascii"))
    digest.update(data)
    return digest.hexdigest()


def read_regular_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"evidence path is not a regular file: {path}")
        if info.st_size > MAX_EVIDENCE_FILE_BYTES:
            raise ValueError("evidence exceeds 64 MiB")
        data = bytearray()
        while True:
            chunk = os.read(
                fd, min(1024 * 1024, MAX_EVIDENCE_FILE_BYTES - len(data) + 1))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > MAX_EVIDENCE_FILE_BYTES:
                raise ValueError("evidence exceeds 64 MiB")
        return bytes(data)
    finally:
        os.close(fd)


def read_json(path: Path) -> tuple[dict, bytes]:
    data = read_regular_bytes(path)
    try:
        value = json.loads(
            data.decode("utf-8"), object_pairs_hook=unique_object,
            parse_constant=reject_json_constant)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"invalid JSON evidence {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON evidence must be one object: {path}")
    return value, data


def run_text(command: list[str]) -> str:
    result = subprocess.run(
        command, text=True, capture_output=True, check=False, timeout=20)
    if result.returncode:
        raise ValueError(
            f"read-only host command failed: {command[0]}: "
            f"{result.stderr.strip()}")
    return result.stdout.strip()


def require_clean_source(source_sha: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha or ""):
        raise ValueError("physical evidence requires exact source SHA")

    def git(*args):
        return run_text(["git", "-C", str(ROOT), *args])

    if git("rev-parse", "HEAD") != source_sha or \
            git("rev-parse", "origin/main") != source_sha:
        raise ValueError(
            "physical evidence requires HEAD == origin/main == source SHA")
    if git("status", "--porcelain"):
        raise ValueError("physical evidence requires clean source")


def read_optional_text(path: Path):
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def parse_mem_total_bytes() -> int:
    for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
        if line.startswith("MemTotal:"):
            fields = line.split()
            if len(fields) == 3 and fields[2] == "kB":
                return int(fields[1]) * 1024
    raise ValueError("MemTotal unavailable")


def cpu_snapshot() -> dict:
    model_names = []
    for line in Path("/proc/cpuinfo").read_text(
            encoding="utf-8", errors="replace").splitlines():
        if line.startswith(("model name", "Hardware", "Processor")) and ":" in line:
            value = line.split(":", 1)[1].strip()
            if value and value not in model_names:
                model_names.append(value)
    cpu_root = Path("/sys/devices/system/cpu")
    governors, drivers = set(), set()
    minimum_khz, maximum_khz = [], []
    for cpu in sorted(cpu_root.glob("cpu[0-9]*")):
        cpufreq = cpu / "cpufreq"
        governor = read_optional_text(cpufreq / "scaling_governor")
        driver = read_optional_text(cpufreq / "scaling_driver")
        if governor:
            governors.add(governor)
        if driver:
            drivers.add(driver)
        for target, path in (
                (minimum_khz, cpufreq / "scaling_min_freq"),
                (maximum_khz, cpufreq / "scaling_max_freq")):
            value = read_optional_text(path)
            if value is not None:
                try:
                    target.append(int(value))
                except ValueError:
                    pass
    return {
        "model_names": model_names,
        "configured_cpus": os.cpu_count(),
        "online_cpus": os.sysconf("SC_NPROCESSORS_ONLN"),
        "affinity_cpus": sorted(os.sched_getaffinity(0)),
        "governors": sorted(governors),
        "frequency_drivers": sorted(drivers),
        "scaling_min_khz": sorted(set(minimum_khz)),
        "scaling_max_khz": sorted(set(maximum_khz)),
    }


def pressure_snapshot() -> dict:
    result = {}
    for name in ("cpu", "io", "memory"):
        result[name] = read_optional_text(Path("/proc/pressure") / name)
    return result


def thermal_snapshot() -> list[dict]:
    rows = []
    for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
        row = {
            "zone": zone.name,
            "type": read_optional_text(zone / "type"),
            "temp_millicelsius": None,
        }
        value = read_optional_text(zone / "temp")
        if value is not None:
            try:
                row["temp_millicelsius"] = int(value)
            except ValueError:
                pass
        rows.append(row)
    return rows


def module_parameters() -> dict:
    root = Path("/sys/module/dm_swapz/parameters")
    if not root.is_dir():
        return {"status": "NOT_LOADED", "values": {}}
    values = {}
    for path in sorted(root.iterdir()):
        if path.is_file():
            values[path.name] = read_optional_text(path)
    return {"status": "LOADED", "values": values}


def swap_inventory() -> list[dict]:
    lines = Path("/proc/swaps").read_text(encoding="utf-8").splitlines()
    rows = []
    for line in lines[1:]:
        fields = line.split()
        if len(fields) != 5:
            raise ValueError("cannot parse /proc/swaps")
        major_minor = None
        try:
            info = Path(fields[0]).stat()
            if stat.S_ISBLK(info.st_mode):
                major_minor = (
                    f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}")
        except OSError as exc:
            if fields[1] == "partition":
                raise ValueError(
                    "cannot resolve block-backed swap identity") from exc
        if fields[1] == "partition" and major_minor is None:
            raise ValueError("block-backed swap row lacks major:minor")
        rows.append({
            "path": fields[0], "type": fields[1],
            "size_kib": int(fields[2]), "used_kib": int(fields[3]),
            "priority": int(fields[4]), "major_minor": major_minor,
        })
    return rows


def block_device_snapshot(device: Path) -> dict:
    resolved = device.resolve(strict=True)
    info = resolved.stat()
    if not stat.S_ISBLK(info.st_mode):
        raise ValueError("physical host snapshot requires a block device")
    major_minor = f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}"
    sys_path = (Path("/sys/dev/block") / major_minor).resolve(strict=True)
    if not (sys_path / "partition").is_file():
        raise ValueError("physical host snapshot requires the admitted partition")
    block_root = next(
        (candidate for candidate in (sys_path, *sys_path.parents)
         if (candidate / "queue").is_dir()),
        None)
    if block_root is None:
        raise ValueError("cannot resolve physical block queue")
    queue = block_root / "queue"
    size_text = read_optional_text(sys_path / "size")
    if size_text is None:
        raise ValueError("block size is unavailable")
    scheduler = read_optional_text(queue / "scheduler")
    selected_scheduler = None
    if scheduler:
        selected = re.findall(r"\[([^\]]+)\]", scheduler)
        selected_scheduler = selected[0] if len(selected) == 1 else None

    def integer(path):
        value = read_optional_text(path)
        try:
            return int(value) if value is not None else None
        except ValueError:
            return None

    queue_fields = {}
    for name in (
            "logical_block_size", "physical_block_size", "minimum_io_size",
            "optimal_io_size", "nr_requests", "read_ahead_kb",
            "max_sectors_kb", "max_hw_sectors_kb", "rotational",
            "rq_affinity", "nomerges", "io_poll"):
        queue_fields[name] = integer(queue / name)
    queue_fields["write_cache"] = read_optional_text(queue / "write_cache")
    holders = []
    holders_path = sys_path / "holders"
    if holders_path.is_dir():
        for holder in sorted(holders_path.iterdir()):
            resolved_holder = holder.resolve(strict=True)
            holder_major_minor = read_optional_text(resolved_holder / "dev")
            if not holder_major_minor or not re.fullmatch(
                    r"[0-9]+:[0-9]+", holder_major_minor):
                raise ValueError("cannot resolve admitted-device holder identity")
            holders.append({
                "kernel_name": resolved_holder.name,
                "major_minor": holder_major_minor,
            })
    return {
        "requested_path": str(device),
        "resolved_path": str(resolved),
        "kernel_name": sys_path.name,
        "major_minor": major_minor,
        "parent_major_minor": read_optional_text(block_root / "dev"),
        "size_bytes": int(size_text) * 512,
        "physical_disk": block_root.name,
        "model": read_optional_text(block_root / "device/model"),
        "vendor": read_optional_text(block_root / "device/vendor"),
        "serial": read_optional_text(block_root / "device/serial"),
        "wwid": read_optional_text(block_root / "device/wwid"),
        "partuuid": run_text(
            ["lsblk", "-dnro", "PARTUUID", str(resolved)]),
        "removable": integer(block_root / "removable"),
        "transport": run_text(
            ["lsblk", "-dnro", "TRAN", str(resolved)]),
        "scheduler": scheduler,
        "selected_scheduler": selected_scheduler,
        "queue": queue_fields,
        "holders": holders,
        "ancestry": json.loads(run_text([
            "lsblk", "--json", "-s", "-o",
            "NAME,KNAME,TYPE,MAJ:MIN,SIZE,MODEL,TRAN,MOUNTPOINTS",
            str(resolved)])),
    }


def source_tree_sha(source_sha: str) -> str:
    tree = run_text([
        "git", "-C", str(ROOT), "rev-parse", f"{source_sha}^{{tree}}"])
    if not re.fullmatch(r"[0-9a-f]{40}", tree):
        raise ValueError("source tree SHA is unavailable")
    return tree


def boot_uptime_seconds() -> float:
    fields = Path("/proc/uptime").read_text(encoding="ascii").split()
    if len(fields) != 2:
        raise ValueError("host uptime is unavailable")
    value = float(fields[0])
    if not math.isfinite(value) or value < 0:
        raise ValueError("host uptime is invalid")
    return value


def physical_virtualization() -> str:
    result = subprocess.run(
        ["systemd-detect-virt", "--quiet"], capture_output=True,
        text=True, check=False, timeout=10)
    if result.returncode == 1:
        return "none"
    if result.returncode == 0:
        raise ValueError("physical campaign evidence refuses VM/container host")
    raise ValueError("virtualization detection was inconclusive")


def host_snapshot(source_sha: str, device: Path) -> dict:
    require_clean_source(source_sha)
    snapshot = {
        "schema": HOST_SCHEMA,
        "captured_at_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "source_sha": source_sha,
        "source_tree_sha": source_tree_sha(source_sha),
        # Same CLOCK_MONOTONIC clock used by physical benchmark arms.
        "captured_monotonic_ns": time.monotonic_ns(),
        "virtualization": physical_virtualization(),
        "kernel": {
            "node": run_text(["uname", "-n"]),
            "release": run_text(["uname", "-r"]),
            "machine": run_text(["uname", "-m"]),
            "version": run_text(["uname", "-v"]),
            "boot_id": read_optional_text(
                Path("/proc/sys/kernel/random/boot_id")),
            "uptime_seconds": boot_uptime_seconds(),
        },
        "cpu": cpu_snapshot(),
        "memory": {"total_bytes": parse_mem_total_bytes()},
        "device": block_device_snapshot(device),
        "swap_inventory": swap_inventory(),
        "mount_inventory": run_text([
            "findmnt", "-rn", "-o", "TARGET,SOURCE,FSTYPE,MAJ:MIN"]),
        "pressure": pressure_snapshot(),
        "thermal": thermal_snapshot(),
        "dm_swapz_module": module_parameters(),
    }
    validate_host_snapshot(snapshot, source_sha)
    return snapshot


def snapshot_time(snapshot: dict) -> datetime.datetime:
    try:
        captured = datetime.datetime.fromisoformat(snapshot["captured_at_utc"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("campaign host snapshot capture time is invalid") from exc
    if captured.tzinfo is None or captured.utcoffset() is None:
        raise ValueError("campaign host snapshot capture time lacks timezone")
    return captured


def validate_host_snapshot(snapshot: dict, source_sha: str) -> None:
    if snapshot.get("schema") != HOST_SCHEMA:
        raise ValueError("campaign host snapshot uses an unknown schema")
    if snapshot.get("source_sha") != source_sha:
        raise ValueError("campaign host snapshot does not match source SHA")
    if not re.fullmatch(
            r"[0-9a-f]{40}", str(snapshot.get("source_tree_sha") or "")):
        raise ValueError("campaign host snapshot lacks exact source tree SHA")
    if snapshot.get("virtualization") != "none":
        raise ValueError("campaign host snapshot is not a physical host")
    snapshot_time(snapshot)
    captured_monotonic = snapshot.get("captured_monotonic_ns")
    # Historical evidence without a clock stays readable but cannot PASS.
    if captured_monotonic is not None and (
            type(captured_monotonic) is not int or captured_monotonic <= 0):
        raise ValueError("malformed host monotonic timestamp")

    kernel = snapshot.get("kernel")
    cpu = snapshot.get("cpu")
    memory = snapshot.get("memory")
    device = snapshot.get("device")
    if not isinstance(kernel, dict) or not all(
            isinstance(kernel.get(key), str) and kernel.get(key)
            for key in ("release", "machine", "version", "node")) or \
            not re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                str(kernel.get("boot_id") or "")) or \
            not isinstance(kernel.get("uptime_seconds"), (int, float)) or \
            isinstance(kernel.get("uptime_seconds"), bool) or \
            not math.isfinite(float(kernel["uptime_seconds"])) or \
            kernel["uptime_seconds"] < 0:
        raise ValueError("campaign host kernel identity is incomplete")
    if not isinstance(cpu, dict) or type(cpu.get("configured_cpus")) is not int or \
            type(cpu.get("online_cpus")) is not int or \
            not isinstance(cpu.get("affinity_cpus"), list) or \
            cpu["configured_cpus"] <= 0 or cpu["online_cpus"] <= 0:
        raise ValueError("campaign host CPU identity is incomplete")
    if not isinstance(memory, dict) or \
            type(memory.get("total_bytes")) is not int or \
            memory["total_bytes"] <= 0:
        raise ValueError("campaign host memory identity is incomplete")
    if not isinstance(device, dict) or not re.fullmatch(
            r"[0-9]+:[0-9]+", str(device.get("major_minor") or "")) or \
            type(device.get("size_bytes")) is not int or \
            device["size_bytes"] <= 0 or \
            not re.fullmatch(r"[0-9]+:[0-9]+", str(device.get("parent_major_minor") or "")) or \
            not all(isinstance(device.get(key), str) and device.get(key)
                    for key in ("physical_disk", "model", "transport", "partuuid")):
        raise ValueError("campaign physical-device identity is incomplete")
    queue = device.get("queue")
    holders = device.get("holders")
    if not isinstance(holders, list) or any(
            not isinstance(holder, dict) or
            not isinstance(holder.get("kernel_name"), str) or
            not re.fullmatch(
                r"[0-9]+:[0-9]+", str(holder.get("major_minor") or ""))
            for holder in holders):
        raise ValueError("campaign physical-device holder identity is malformed")
    if not isinstance(queue, dict) or \
            type(queue.get("logical_block_size")) is not int or \
            type(queue.get("physical_block_size")) is not int or \
            queue["logical_block_size"] <= 0 or queue["physical_block_size"] <= 0:
        raise ValueError("campaign physical-device queue geometry is incomplete")
    pressure = snapshot.get("pressure")
    module = snapshot.get("dm_swapz_module")
    swaps = snapshot.get("swap_inventory")
    mounts = snapshot.get("mount_inventory")
    if not isinstance(swaps, list) or \
            any(not isinstance(row, dict) or
                not isinstance(row.get("path"), str) or
                row.get("type") not in ("partition", "file") or
                type(row.get("size_kib")) is not int or row["size_kib"] < 0 or
                type(row.get("used_kib")) is not int or row["used_kib"] < 0 or
                type(row.get("priority")) is not int or
                (row.get("major_minor") is not None and not re.fullmatch(
                    r"[0-9]+:[0-9]+", str(row.get("major_minor")))) or
                (row.get("type") == "partition" and
                 row.get("major_minor") is None)
                for row in swaps) or \
            not isinstance(mounts, str) or \
            not isinstance(pressure, dict) or \
            not all(isinstance(pressure.get(name), str)
                    for name in ("cpu", "io", "memory")) or \
            not isinstance(snapshot.get("thermal"), list) or \
            not isinstance(module, dict) or \
            module.get("status") not in ("LOADED", "NOT_LOADED") or \
            not isinstance(module.get("values"), dict):
        raise ValueError("campaign host context is incomplete")
    mount_rows(mounts)


def swap_identity(rows: list[dict]) -> list[tuple]:
    identity = []
    for row in rows:
        if not isinstance(row, dict):
            return []
        identity.append((
            row.get("path"), row.get("type"), row.get("size_kib"),
            row.get("priority"), row.get("major_minor")))
    return sorted(identity)


def mount_rows(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 4 or not re.fullmatch(r"[0-9]+:[0-9]+", fields[3]):
            raise ValueError("campaign mount inventory is malformed")
        rows.append({
            "target": fields[0], "source": fields[1],
            "fstype": fields[2], "major_minor": fields[3],
        })
    return rows


def physical_target_identity(snapshot: dict) -> dict:
    device = snapshot.get("device") or {}
    partuuid = QUALIFICATION["normalize_partuuid"](device.get("partuuid"))
    size_bytes = device.get("size_bytes")
    if partuuid is None or type(size_bytes) is not int or size_bytes <= 0:
        raise ValueError("campaign physical target identity is incomplete")
    return {
        "partuuid": partuuid,
        "device_bytes": size_bytes,
    }


def qualification_target_identity(snapshot: dict) -> dict:
    """Translate the host snapshot into the evaluator's physical-target schema."""
    physical = physical_target_identity(snapshot)
    major_minor = (snapshot.get("device") or {}).get("major_minor")
    if not isinstance(major_minor, str) or not re.fullmatch(
            r"[0-9]+:[0-9]+", major_minor):
        raise ValueError("campaign target major:minor is incomplete")
    return {
        "physical_partuuid": physical["partuuid"],
        "physical_device_bytes": physical["device_bytes"],
        "lower_major_minor": major_minor,
        "parent_major_minor": snapshot["device"]["parent_major_minor"],
        "parent_model": snapshot["device"]["model"],
        "parent_transport": snapshot["device"]["transport"],
    }


def qualification_target_binding(summary: dict, snapshot: dict) -> dict:
    expected = qualification_target_identity(snapshot)
    observed = summary.get("campaign_target_identity")
    consistent = (
        summary.get("campaign_target_consistent") is True and
        observed == expected)
    return {
        "status": "MATCH" if consistent else "MISMATCH",
        "consistent": consistent,
        "expected": expected,
        "observed": observed,
    }


def admitted_device_boundary(snapshot: dict) -> dict:
    device = snapshot.get("device") or {}
    major_minor = device.get("major_minor")
    swaps = [
        row for row in snapshot.get("swap_inventory") or []
        if isinstance(row, dict) and row.get("major_minor") == major_minor]
    mounts = [
        row for row in mount_rows(snapshot.get("mount_inventory") or "")
        if row["major_minor"] == major_minor]
    holders = device.get("holders") or []
    return {
        "major_minor": major_minor,
        "swap_rows": swaps,
        "mount_rows": mounts,
        "holders": holders,
        "quiescent": not swaps and not mounts and not holders,
    }


def pair_key(record: dict):
    return (
        record.get("workload"), record.get("pair_id"),
        record.get("pair_index"), record.get("order"))


def host_stability(before: dict, after: dict) -> dict:
    checks = {
        "source_sha": before.get("source_sha") == after.get("source_sha"),
        "source_tree_sha":
            before.get("source_tree_sha") == after.get("source_tree_sha"),
        "kernel_release":
            (before.get("kernel") or {}).get("release") ==
            (after.get("kernel") or {}).get("release"),
        "kernel_machine":
            (before.get("kernel") or {}).get("machine") ==
            (after.get("kernel") or {}).get("machine"),
        "kernel_version":
            (before.get("kernel") or {}).get("version") ==
            (after.get("kernel") or {}).get("version"),
        "kernel_node":
            (before.get("kernel") or {}).get("node") ==
            (after.get("kernel") or {}).get("node"),
        "kernel_boot_id":
            (before.get("kernel") or {}).get("boot_id") ==
            (after.get("kernel") or {}).get("boot_id"),
        "capture_monotonic_increasing":
            (before.get("captured_monotonic_ns") is None or
             after.get("captured_monotonic_ns") is None or
             after["captured_monotonic_ns"] > before["captured_monotonic_ns"]),
        "kernel_uptime_non_decreasing":
            (after.get("kernel") or {}).get("uptime_seconds", -1) >=
            (before.get("kernel") or {}).get("uptime_seconds", 0),
        "device_major_minor":
            (before.get("device") or {}).get("major_minor") ==
            (after.get("device") or {}).get("major_minor"),
        "device_size_bytes":
            (before.get("device") or {}).get("size_bytes") ==
            (after.get("device") or {}).get("size_bytes"),
        "device_parent_major_minor":
            (before.get("device") or {}).get("parent_major_minor") ==
            (after.get("device") or {}).get("parent_major_minor"),
        "device_partuuid":
            (before.get("device") or {}).get("partuuid") ==
            (after.get("device") or {}).get("partuuid"),
        "device_serial":
            (before.get("device") or {}).get("serial") ==
            (after.get("device") or {}).get("serial"),
        "device_wwid":
            (before.get("device") or {}).get("wwid") ==
            (after.get("device") or {}).get("wwid"),
        "physical_disk":
            (before.get("device") or {}).get("physical_disk") ==
            (after.get("device") or {}).get("physical_disk"),
        "device_model":
            (before.get("device") or {}).get("model") ==
            (after.get("device") or {}).get("model"),
        "device_transport":
            (before.get("device") or {}).get("transport") ==
            (after.get("device") or {}).get("transport"),
        "device_scheduler":
            (before.get("device") or {}).get("selected_scheduler") ==
            (after.get("device") or {}).get("selected_scheduler"),
        "device_queue":
            (before.get("device") or {}).get("queue") ==
            (after.get("device") or {}).get("queue"),
        "admitted_device_quiescent_before":
            admitted_device_boundary(before)["quiescent"],
        "admitted_device_quiescent_after":
            admitted_device_boundary(after)["quiescent"],
        "cpu_model_names":
            (before.get("cpu") or {}).get("model_names") ==
            (after.get("cpu") or {}).get("model_names"),
        "configured_cpus":
            (before.get("cpu") or {}).get("configured_cpus") ==
            (after.get("cpu") or {}).get("configured_cpus"),
        "online_cpus":
            (before.get("cpu") or {}).get("online_cpus") ==
            (after.get("cpu") or {}).get("online_cpus"),
        "affinity_cpus":
            (before.get("cpu") or {}).get("affinity_cpus") ==
            (after.get("cpu") or {}).get("affinity_cpus"),
        "cpu_governors":
            (before.get("cpu") or {}).get("governors") ==
            (after.get("cpu") or {}).get("governors"),
        "cpu_frequency_drivers":
            (before.get("cpu") or {}).get("frequency_drivers") ==
            (after.get("cpu") or {}).get("frequency_drivers"),
        "cpu_scaling_min":
            (before.get("cpu") or {}).get("scaling_min_khz") ==
            (after.get("cpu") or {}).get("scaling_min_khz"),
        "cpu_scaling_max":
            (before.get("cpu") or {}).get("scaling_max_khz") ==
            (after.get("cpu") or {}).get("scaling_max_khz"),
        "memory_total_bytes":
            (before.get("memory") or {}).get("total_bytes") ==
            (after.get("memory") or {}).get("total_bytes"),
        "mount_inventory":
            before.get("mount_inventory") == after.get("mount_inventory"),
        "swap_inventory":
            swap_identity(before.get("swap_inventory") or []) ==
            swap_identity(after.get("swap_inventory") or []),
        "module_state":
            before.get("dm_swapz_module") == after.get("dm_swapz_module"),
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    return {
        "status": "STABLE" if not failed else "CHANGED",
        "checks": checks,
        "failed_checks": failed,
    }


def artifact(path: Path, data: bytes) -> dict:
    return {
        "name": path.name,
        "size_bytes": len(data),
        "sha256": sha256_bytes(data),
    }


def metadata_ram_trace_matches_swapz_arm(
        trace: dict, swapz_arm: dict) -> bool:
    """Bind labeled RAM phases to measured sustained-arm GC chronology."""
    try:
        binding = RAM_VALIDATOR["metadata_ram_arm_binding"](swapz_arm)
        RAM_VALIDATOR["validate_metadata_ram_arm_binding"](trace, binding)
    except ValueError:
        return False
    return True

def campaign_capacity_and_ram(
        pair_records: list[dict], target_device_bytes: int,
        source_sha: str, metadata_ram_trace: dict | None = None) -> dict | None:
    """Seal maximum logical capacity and measured target RAM from sustained I/O."""
    accepted = [
        pair for pair in pair_records
        if pair.get("workload") == "sd-high-occupancy-churn" and
        pair.get("status") == "PASS" and pair.get("excluded") is False
    ]
    if (
            len(accepted) != 1 or
            type(target_device_bytes) is not int or
            not 0 < target_device_bytes <= RAM_VALIDATOR["MAX_UINT64"]):
        return None
    swapz = accepted[0].get("swapz")
    if not isinstance(swapz, dict):
        return None
    logical_pages = swapz.get("logical_pages")
    resources = swapz.get("resources")
    if type(logical_pages) is not int or logical_pages <= 0:
        return None
    logical_capacity_bytes = RAM_VALIDATOR["_checked_product"](
        logical_pages, 4096, RAM_VALIDATOR["MAX_UINT64"])
    # A smaller, easier-to-create mapper is not maximum-capacity evidence.
    if (logical_capacity_bytes is None or
            logical_pages != RAM_VALIDATOR[
                "maximum_logical_pages_for_partition"](target_device_bytes) or
            logical_capacity_bytes > target_device_bytes):
        return None
    identity = swapz.get("device_identity")
    mapper_uuid = identity.get("dm_uuid") if isinstance(identity, dict) else None
    # Post-teardown RAM observations are sealed separately from the replay
    # pair, which completes before the mapper can be safely destroyed.
    trace = metadata_ram_trace
    try:
        ram_summary = RAM_VALIDATOR["validate_metadata_ram_trace"](
            trace, source_sha=source_sha, mapper_uuid=mapper_uuid)
        arm_binding = RAM_VALIDATOR["metadata_ram_arm_binding"](swapz)
        RAM_VALIDATOR["validate_metadata_ram_arm_binding"](
            trace, arm_binding)
    except ValueError:
        return None
    peak_ram_bytes = ram_summary["peak_ram_bytes"]
    if (type(peak_ram_bytes) is not int or
            not 0 < peak_ram_bytes <= RAM_VALIDATOR["MAX_UINT64"]):
        return None
    # The replay process cannot know a post-teardown host peak at start. Keep
    # any legacy scalar diagnostic only when it agrees; zero/missing has no
    # qualifying authority.
    replay_peak = (
        resources.get("metadata_and_target_peak_ram_bytes")
        if isinstance(resources, dict) else None)
    if (replay_peak is not None and
            (type(replay_peak) is not int or
             replay_peak not in (0, peak_ram_bytes))):
        return None
    return {
        # Preserve the measured peak even when it is over the frozen limit.
        # The release evaluator owns the acceptance verdict and rederives it
        # from the sealed measurement plus the exact frozen policy.
        "page_bytes": 4096,
        "logical_pages": logical_pages,
        "logical_capacity_bytes": logical_capacity_bytes,
        "peak_ram_bytes": peak_ram_bytes,
        "mapper_uuid": mapper_uuid,
        "metadata_ram_trace": trace,
        "metadata_ram_summary": ram_summary,
        "metadata_ram_arm_binding": arm_binding,
    }


def metadata_ram_trace_within_host_window(
        capacity: dict, before: dict, after: dict) -> bool:
    """Require samples in the same physical boot and snapshot time envelope."""
    trace = capacity.get("metadata_ram_trace")
    samples = trace.get("samples") if isinstance(trace, dict) else None
    first_kernel = before.get("kernel")
    last_kernel = after.get("kernel")
    first_memory = before.get("memory")
    last_memory = after.get("memory")
    total_bytes = (
        first_memory.get("total_bytes")
        if isinstance(first_memory, dict) else None)
    if (not isinstance(samples, list) or not samples or
            not isinstance(first_kernel, dict) or
            not isinstance(last_kernel, dict) or
            not isinstance(first_memory, dict) or
            not isinstance(last_memory, dict) or
            type(total_bytes) is not int or total_bytes <= 0 or
            last_memory.get("total_bytes") != total_bytes or
            trace.get("meminfo_unit") != "kB" or
            any(type(sample.get("mem_available_kib")) is not int or
                not 0 < sample["mem_available_kib"] * 1024 <= total_bytes
                for sample in samples if isinstance(sample, dict)) or
            any(not isinstance(sample, dict) for sample in samples) or
            trace.get("host_boot_id") != first_kernel.get("boot_id") or
            trace.get("host_boot_id") != last_kernel.get("boot_id")):
        return False
    try:
        first = datetime.datetime.fromisoformat(
            samples[0]["timestamp_utc"].replace("Z", "+00:00"))
        last = datetime.datetime.fromisoformat(
            samples[-1]["timestamp_utc"].replace("Z", "+00:00"))
        # Boot ID plus the UTC snapshot envelope binds the trace to this
        # campaign. Do not compare CLOCK_MONOTONIC samples with /proc/uptime:
        # their suspend-time semantics differ on Linux.
        return snapshot_time(before) <= first < last <= snapshot_time(after)
    except (KeyError, TypeError, ValueError):
        return False


def audit_physical_pairs(summary: dict, before: dict, after: dict) -> dict:
    """Fail closed on stale or counterfeit arm chronology and evidence.

    Numeric diagnostics are bounded; do not publish fixture fingerprints,
    arbitrary exclusion strings, or replay payload contents.
    """
    diagnostics = []
    omitted = 0
    first_failed_phase = None
    encountered_statuses = set()
    # A known failed check must not be downgraded by a later prerequisite gap.
    diagnostic_priority = {"UNAVAILABLE": 0, "BLOCKED": 1, "FAIL": 2}
    retained_status_counts = {
        status: 0 for status in diagnostic_priority
    }
    # Only authenticated failure candidates may become measured FAIL. Invalid
    # identities invalidate that attempt; unusable cohorts cannot claim a
    # measured aggregate failure from their stored decision/checks.
    untrusted_pair_keys, untrusted_cohorts = set(), set()
    pending_producer_failures = []
    first_problem, first_terminal_failure = None, None

    def diagnose(status, metric_name, expected, observed=None,
                 workload=None, pair_index=None, arm=None,
                 reason="physical evidence missing or inconsistent",
                 producer_status=None, failure_phase=None):
        nonlocal omitted, first_failed_phase, first_problem, first_terminal_failure
        encountered_statuses.add(status)
        if workload is not None:
            if status in ("BLOCKED", "UNAVAILABLE"):
                untrusted_cohorts.add(workload)
                if metric_name in (
                        "pair.schema", "pair.pair_id", "pair.pair_index",
                        "pair.order", "pair.source_sha", "pair.workload_id",
                        "pair.prospective_chronology_ns",
                        "arm.candidate", "arm.workload_id", "arm.source_sha",
                        "arm.arm_boot_id", "arm.monotonic_window_ns",
                        "pair.target_identity"):
                    untrusted_pair_keys.add((workload, pair_index))
            location = {"workload": workload, "pair_index": pair_index,
                        "arm": arm, "metric": metric_name,
                        "evidence_class": status}
            if first_problem is None:
                first_problem = location
            if status == "FAIL" and first_terminal_failure is None:
                first_terminal_failure = location
        if status == "FAIL" and first_failed_phase is None:
            # Only producer-proven or independently derived failures own this
            # field. Missing prerequisites remain BLOCKED/UNAVAILABLE.
            first_failed_phase = (
                failure_phase or metric_name.partition(".")[0])
        replacement_index = None
        if len(diagnostics) == MAX_EVIDENCE_DIAGNOSTICS:
            omitted += 1
            # Preserve at least one field-level diagnostic for every observed
            # classification. Remaining slots favor higher-severity findings.
            status_is_retained = retained_status_counts[status] > 0
            replaceable_statuses = [
                retained_status
                for retained_status, count in retained_status_counts.items()
                if count > 1 and (
                    not status_is_retained or
                    diagnostic_priority[retained_status] <
                    diagnostic_priority[status])
            ]
            if not replaceable_statuses:
                return
            replacement_status = min(
                replaceable_statuses, key=diagnostic_priority.get)
            replacement_index = next(
                index for index, entry in enumerate(diagnostics)
                if entry["status"] == replacement_status)
            retained_status_counts[replacement_status] -= 1
        # Avoid unbounded integers, non-finite floats and private strings.
        if type(observed) is int:
            value = observed if 0 <= abs(observed) <= (1 << 64) - 1 else None
        elif type(observed) is float:
            value = observed if math.isfinite(observed) else None
        else:
            value = None
        detail = {
            "status": status, "metric": metric_name, "expected": expected,
            "observed": value, "workload": workload, "pair_index": pair_index,
            "arm": arm, "reason": reason,
        }
        if status == "FAIL" and producer_status is not None:
            # Never echo an arbitrary producer string or a private host path.
            detail["producer_status"] = (
                producer_status if producer_status in ("PASS", "FAIL", "EXCLUDED")
                else "INVALID")
        if replacement_index is None:
            diagnostics.append(detail)
        else:
            diagnostics[replacement_index] = detail
        retained_status_counts[status] += 1

    records = summary.get("records")
    if not isinstance(records, list):
        records = []
    workloads = QUALIFICATION["WORKLOADS"]
    before_source_sha = before.get("source_sha")
    after_source_sha = after.get("source_sha")
    valid_source_binding = (
        isinstance(before_source_sha, str) and
        re.fullmatch(r"[0-9a-f]{40}", before_source_sha) is not None and
        after_source_sha == before_source_sha)
    if not valid_source_binding:
        diagnose("BLOCKED", "host.source_sha",
                 "matching exact admitted source SHA",
                 reason="host source identity is missing, malformed or changed")

    boot_id = (before.get("kernel") or {}).get("boot_id")
    after_boot_id = (after.get("kernel") or {}).get("boot_id")
    valid_boot_binding = (
        isinstance(boot_id, str) and
        re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            boot_id) is not None and
        after_boot_id == boot_id)
    if not valid_boot_binding:
        diagnose("BLOCKED", "host.kernel_boot_id",
                 "matching exact physical host boot ID",
                 reason="host boot identity is missing, malformed or changed")

    host_start = before.get("captured_monotonic_ns")
    host_end = after.get("captured_monotonic_ns")
    valid_host_clock = (
        type(host_start) is int and type(host_end) is int and
        0 < host_start < host_end)
    if not valid_host_clock:
        diagnose("UNAVAILABLE", "host.captured_monotonic_ns",
                 "strict host before/after monotonic window",
                 reason="host monotonic window unavailable or reversed")
    valid_host_window = valid_host_clock and valid_boot_binding

    campaign_protocol = summary.get("evaluation_protocol")
    valid_protocol_state = (
        campaign_protocol is None or campaign_protocol in ("v1", "v2"))
    requires_target_binding = campaign_protocol in ("v1", "v2")
    has_target_binding_claim = (
        "campaign_target_identity" in summary or
        "campaign_target_consistent" in summary)
    # Isolated rootless record audits may omit a campaign protocol/target.
    # Once a real v1/v2 protocol is claimed, the evaluator target is mandatory.
    target_binding_consistent = not requires_target_binding
    if requires_target_binding or has_target_binding_claim:
        try:
            target_binding_consistent = (
                qualification_target_binding(summary, before)["consistent"] and
                qualification_target_identity(before) ==
                qualification_target_identity(after))
        except (KeyError, TypeError, ValueError):
            target_binding_consistent = False
        if not target_binding_consistent:
            diagnose("BLOCKED", "qualification.campaign_target_identity",
                     "same admitted source-bound physical target",
                     reason="evaluator target is missing or differs from host boundary")
    qualification_status = summary.get("status")
    if qualification_status != "PASS":
        # INCOMPLETE includes absent evidence, not necessarily a measured FAIL.
        diagnose("BLOCKED", "qualification.status", "PASS",
                 reason="qualification is incomplete or rejected")

    pair_identifiers, pair_indices = {}, set()
    run_identifiers, windows = {}, []
    for record in records:
        if not isinstance(record, dict):
            diagnose("BLOCKED", "pair.schema", "physical pair object")
            continue
        workload = record.get("workload")
        pair_index = record.get("pair_index")
        index = pair_index if type(pair_index) is int else None
        known_workload = workload if workload in workloads else None
        if record.get("schema") != PAIR_SCHEMA:
            diagnose("BLOCKED", "pair.schema", PAIR_SCHEMA,
                     workload=known_workload, pair_index=index,
                     reason="pair schema is missing or invalid")
        if workload not in workloads:
            diagnose("BLOCKED", "pair.workload", "frozen cohort")
            continue
        spec = workloads[workload]
        if (index is None or not 1 <= index <= spec["pairs"] or
                (workload, index) in pair_indices):
            diagnose("BLOCKED", "pair.pair_index",
                     {"operator": "range", "min": 1, "max": spec["pairs"],
                      "unique": True},
                     index, workload=workload, pair_index=index,
                     reason="missing, repeated or out-of-plan pair index")
        else:
            pair_indices.add((workload, index))
        if (index is not None and 1 <= index <= spec["pairs"] and
                record.get("order") != spec["counterbalanced_order"][index - 1]):
            diagnose("BLOCKED", "pair.order",
                     spec["counterbalanced_order"][index - 1],
                     workload=workload, pair_index=index,
                     reason="counterbalanced pair order differs from frozen plan")
        if (record.get("source_sha") != before.get("source_sha") or
                record.get("source_sha") != after.get("source_sha")):
            diagnose("BLOCKED", "pair.source_sha", "admitted exact source",
                     workload=workload, pair_index=index,
                     reason="pair source differs from host source")
        pair_identity = (workload, index)
        identifier = (workload, record.get("pair_id"))
        if not isinstance(identifier[1], str) or not identifier[1]:
            diagnose("BLOCKED", "pair.pair_id", "unique per workload",
                     workload=workload, pair_index=index,
                     reason="missing or duplicated attempted pair")
        elif identifier in pair_identifiers:
            diagnose("BLOCKED", "pair.pair_id", "unique per workload",
                     workload=workload, pair_index=index,
                     reason="missing or duplicated attempted pair")
            first_identity = pair_identifiers[identifier]
            untrusted_pair_keys.add(first_identity)
            untrusted_cohorts.add(first_identity[0])
        else:
            pair_identifiers[identifier] = pair_identity
        if record.get("status") != "PASS" or record.get("excluded") is not False:
            diagnose("BLOCKED", "pair.status", "PASS and excluded=false",
                     workload=workload, pair_index=index,
                     reason=(
                         "excluded or malformed pair requires independent "
                         "producer/measurement failure proof"))
        if record.get("analysis_usable") is not True:
            diagnose("BLOCKED", "pair.analysis_usable", True,
                     workload=workload, pair_index=index,
                     reason=(
                         "evaluator excluded, screened or could not validate "
                         "this pair"))
        raw_arm = record.get("raw")
        swapz_arm = record.get("swapz")
        if isinstance(raw_arm, dict) and isinstance(swapz_arm, dict):
            # The label cannot override the actual temporal arm sequence.
            if record.get("order") in ("raw-first", "swapz-first"):
                first_label, second_label = (
                    ("raw", "swapz") if record["order"] == "raw-first"
                    else ("swapz", "raw"))
                first_arm, second_arm = record[first_label], record[second_label]
                first_end = first_arm.get("arm_finished_monotonic_ns")
                second_start = second_arm.get("arm_started_monotonic_ns")
                if (type(first_end) is int and type(second_start) is int and
                        first_end >= second_start):
                    diagnose("BLOCKED", "pair.order",
                             "nonoverlapping actual counterbalanced arms",
                             workload=workload, pair_index=index,
                             reason="recorded raw/swapz order contradicts chronology")
            raw_run_id = raw_arm.get("workload_id")
            swapz_run_id = swapz_arm.get("workload_id")
            if (isinstance(raw_run_id, str) and raw_run_id and
                    isinstance(swapz_run_id, str) and swapz_run_id and
                    raw_run_id != swapz_run_id):
                diagnose(
                    "BLOCKED", "pair.workload_id",
                    "matching raw/swapz physical run identity",
                    workload=workload, pair_index=index,
                    reason="paired raw/swapz run identity mismatch")
        for label in ("raw", "swapz"):
            arm = record.get(label)
            if not isinstance(arm, dict):
                diagnose("UNAVAILABLE", "arm.evidence", "measured physical arm",
                         workload=workload, pair_index=index, arm=label)
                continue
            if arm.get("candidate") != label:
                diagnose("BLOCKED", "arm.candidate", label,
                         workload=workload, pair_index=index, arm=label,
                         reason="arm candidate does not match pair position")
            producer_verdict = arm.get("verdict")
            if producer_verdict == "FAIL":
                pending_producer_failures.append(
                    (workload, index, label, arm, record))
            elif producer_verdict != "PASS":
                diagnose(
                    "BLOCKED", "arm.verdict", "PASS",
                    workload=workload, pair_index=index, arm=label,
                    reason="physical arm terminal verdict is missing or invalid")
            run_identity = (workload, label, arm.get("workload_id"))
            if not isinstance(run_identity[2], str) or not run_identity[2]:
                diagnose("BLOCKED", "arm.workload_id", "unique per cohort/candidate",
                         workload=workload, pair_index=index, arm=label,
                         reason="reused or absent physical run identifier")
            elif run_identity in run_identifiers:
                diagnose("BLOCKED", "arm.workload_id", "unique per cohort/candidate",
                         workload=workload, pair_index=index, arm=label,
                         reason="reused or absent physical run identifier")
                first_identity = run_identifiers[run_identity]
                untrusted_pair_keys.add(first_identity)
                untrusted_cohorts.add(first_identity[0])
            else:
                run_identifiers[run_identity] = pair_identity
            if arm.get("source_sha") != before.get("source_sha"):
                diagnose("BLOCKED", "arm.source_sha", "admitted source",
                         workload=workload, pair_index=index, arm=label,
                         reason="stale source or artifact provenance")
            if (arm.get("arm_boot_id") != boot_id or
                    arm.get("arm_boot_id") !=
                    (after.get("kernel") or {}).get("boot_id")):
                diagnose("BLOCKED", "arm.arm_boot_id", "same host boot",
                         workload=workload, pair_index=index, arm=label,
                         reason="mixed or absent physical boot identity")
            start, end = (arm.get("arm_started_monotonic_ns"),
                          arm.get("arm_finished_monotonic_ns"))
            if (type(start) is not int or type(end) is not int or
                    not 0 < start < end):
                diagnose("UNAVAILABLE", "arm.monotonic_window_ns", "start < end",
                         workload=workload, pair_index=index, arm=label,
                         reason="arm timestamp missing or reversed")
            else:
                windows.append((start, end, workload, index, label))
                if valid_host_window and not host_start < start < end < host_end:
                    diagnose("BLOCKED", "arm.monotonic_window_ns",
                             "inside same-boot host snapshots",
                             workload=workload, pair_index=index, arm=label,
                             reason="cached, stale or post-snapshot arm")
            required = [
                "lower_io.lower_write_bytes", "lower_io.lower_write_requests",
                "cpu.measured_cpu_seconds_per_useful_byte"]
            if workload == "anonymous-swap":
                required += ["swapin_latency.p95_ns", "swapin_latency.p99_ns",
                             "throughput.useful_read_bytes"]
            else:
                required += [
                    "throughput.logical_write_mbps", "read_ops", "write_ops",
                    "latency.read_p95_ns", "latency.read_p99_ns",
                    "latency.write_p95_ns", "latency.write_p99_ns",
                    "measurement_snapshots.lower_before",
                    "measurement_snapshots.lower_after"]
                if workload == "sd-high-occupancy-churn":
                    required += ["cold_read.p99_ns", "minute_buckets",
                                 "occupancy_transitions"]
                    # Raw has no Device Mapper target status by contract.
                    # GC wall evidence is authoritative only for swapz.
                    if label == "swapz":
                        required += ["gc.wall_fraction", "gc.gc_wall_ns"]
            for name in required:
                observed = arm
                for segment in name.split("."):
                    observed = observed.get(segment) if isinstance(observed, dict) else None
                if observed is None or (
                        type(observed) is float and not math.isfinite(observed)):
                    diagnose("UNAVAILABLE", name, "measured value",
                             workload=workload, pair_index=index, arm=label,
                             reason="required useful I/O, tail, CPU or GC missing")
    windows.sort()
    active_windows = []
    for current in windows:
        # Keep every still-overlapping predecessor, not just the adjacent
        # sorted interval. A long arm can overlap several shorter later arms.
        active_windows = [
            prior for prior in active_windows if prior[1] >= current[0]]
        if active_windows:
            for row in (*active_windows, current):
                untrusted_pair_keys.add((row[2], row[3]))
                untrusted_cohorts.add(row[2])
            diagnose("BLOCKED", "arm.monotonic_window_ns", "nonoverlapping",
                     workload=current[2], pair_index=current[3], arm=current[4],
                     reason="replayed or overlapping physical arms")
        active_windows.append(current)
    for workload in workloads:
        rows = sorted(
            (r for r in records if isinstance(r, dict) and
             r.get("workload") == workload and type(r.get("pair_index")) is int),
            key=lambda r: r["pair_index"])
        latest_end = None
        latest_end_identity = None
        for row in rows:
            times = [
                (arm.get("arm_started_monotonic_ns"),
                 arm.get("arm_finished_monotonic_ns"))
                for arm in (row.get("raw"), row.get("swapz"))
                if isinstance(arm, dict)]
            if len(times) != 2 or any(
                    type(a) is not int or type(b) is not int or
                    not 0 < a < b for a, b in times):
                continue
            first, end = min(a for a, _ in times), max(b for _, b in times)
            current_identity = (workload, row["pair_index"])
            if latest_end is not None and first <= latest_end:
                if latest_end_identity is not None:
                    untrusted_pair_keys.add(latest_end_identity)
                untrusted_pair_keys.add(current_identity)
                untrusted_cohorts.add(workload)
                diagnose("BLOCKED", "pair.prospective_chronology_ns",
                         "ascending pair indices",
                         workload=workload, pair_index=row["pair_index"],
                         reason="later pair reuses earlier physical time")
            if latest_end is None or end > latest_end:
                latest_end = end
                latest_end_identity = current_identity

    # Authenticate terminal producer failures only after seeing every attempt:
    # a later duplicate, foreign source or overlapping window can invalidate an
    # earlier apparently valid failure. Preserve the original arm error/stage
    # inside its immutable artifact; do not publish arbitrary error strings.
    for workload, index, label, arm, record in pending_producer_failures:
        pair_identity = (workload, index)
        if (not valid_source_binding or not valid_host_window or
                not valid_protocol_state or not target_binding_consistent or
                pair_identity in untrusted_pair_keys):
            diagnose("BLOCKED", "arm.verdict", "authenticated terminal failure",
                     workload=workload, pair_index=index, arm=label,
                     reason="producer FAIL lacks valid physical arm identity")
            continue
        if (record.get("status") != "EXCLUDED" or
                record.get("excluded") is not True or
                record.get("analysis_usable") is not False):
            diagnose("BLOCKED", "arm.verdict",
                     "EXCLUDED evaluator-unusable failure pair",
                     workload=workload, pair_index=index, arm=label,
                     reason="producer FAIL contradicts pair audit disposition")
            continue
        if qualification_status != "FAIL_OR_INCOMPLETE":
            diagnose("BLOCKED", "arm.verdict",
                     "FAIL_OR_INCOMPLETE qualification disposition",
                     workload=workload, pair_index=index, arm=label,
                     reason="producer FAIL contradicts qualification disposition")
            continue
        stage = arm.get("stage")
        stage_is_valid = (
            isinstance(stage, str) and len(stage) <= 48 and
            re.fullmatch(
                r"(?:preflight|fill|warmup|measure|steady|gc|teardown|"
                r"publish|round-[1-9][0-9]*(?:-verify)?)", stage) is not None)
        if not stage_is_valid:
            diagnose("BLOCKED", "arm.verdict",
                     "authenticated non-setup producer phase",
                     workload=workload, pair_index=index, arm=label,
                     reason="producer FAIL phase is missing or invalid")
            continue
        # Setup failures are real producer errors, but not authenticated
        # terminal measurements of a completed physical workload.
        if stage in ("preflight", "fill", "warmup"):
            diagnose("BLOCKED", "arm.verdict", "terminal measured workload",
                     workload=workload, pair_index=index, arm=label,
                     reason="producer failed before the measurement phase")
            continue
        diagnose(
            "FAIL", "arm.verdict", "PASS",
            workload=workload, pair_index=index, arm=label,
            reason="authenticated physical producer terminal failure",
            producer_status="FAIL", failure_phase=stage)

    decisions = summary.get("decisions")
    if not isinstance(decisions, dict):
        diagnose("BLOCKED", "qualification.decisions", "workload decision object")
        decisions = {}
    protocol = campaign_protocol
    if protocol == "v2":
        required_workloads = workloads
    elif protocol == "v1":
        required_workloads = QUALIFICATION["CONTRACT"]["workloads"]
    else:
        # Isolated rootless record audits have no campaign protocol. The
        # campaign sealer always supplies one and checks its policy identity.
        required_workloads = decisions
        if protocol is not None:
            diagnose("BLOCKED", "qualification.evaluation_protocol", "v1 or v2")
    cohort_pair_counts = {}
    for workload in required_workloads:
        spec = workloads[workload]
        decision = decisions.get(workload)
        if not isinstance(decision, dict):
            diagnose("BLOCKED", "qualification.decision",
                     "required workload decision", workload=workload,
                     reason="frozen or v2 cohort decision is missing")
        attempts = [r for r in records if isinstance(r, dict) and
                    r.get("workload") == workload]
        accepted_count = sum(
            r.get("analysis_usable") is True for r in attempts)
        cohort_pair_counts[workload] = {
            "required_pairs": spec["pairs"],
            "attempted_pairs": len(attempts),
            "accepted_pairs": accepted_count,
        }
        for name, count in (
                ("attempted_pairs", len(attempts)),
                ("accepted_pairs", accepted_count)):
            if count != spec["pairs"]:
                diagnose("BLOCKED", "qualification." + name,
                         {"operator": "==", "value": spec["pairs"], "unit": "pairs"},
                         count, workload=workload,
                         reason="frozen or v2 cohort is incomplete")
        if not isinstance(decision, dict):
            continue
        cohort_verified = (
            len(attempts) == spec["pairs"] and
            accepted_count == spec["pairs"] and
            workload not in untrusted_cohorts and valid_source_binding and
            valid_host_window and valid_protocol_state and
            target_binding_consistent and
            all((workload, pair_index) in pair_indices for pair_index
                in range(1, spec["pairs"] + 1)))
        decision_status = decision.get("status")
        if decision_status == "FAIL":
            if qualification_status != "FAIL_OR_INCOMPLETE":
                diagnose("BLOCKED", "qualification.decision_authentication",
                         "FAIL_OR_INCOMPLETE qualification disposition",
                         workload=workload,
                         reason="failed decision contradicts qualification disposition")
                continue
            if not cohort_verified:
                diagnose("BLOCKED", "qualification.decision_authentication",
                         "complete verified measured cohort",
                         workload=workload,
                         reason="unusable cohort cannot claim measured FAIL")
                continue
            checks = decision.get("checks")
            if (spec["evidence"] == "statistical_paired" or
                    workload == "sd-high-occupancy-churn"):
                coherent = (
                    isinstance(checks, dict) and
                    any(value is False for value in checks.values()) and
                    all(type(value) is bool for value in checks.values()))
            else:
                pair_decisions = decision.get("pairs")
                coherent = (
                    isinstance(pair_decisions, list) and
                    len(pair_decisions) == spec["pairs"] and
                    any(row.get("status") == "FAIL" for row in pair_decisions
                        if isinstance(row, dict)))
            if not coherent:
                diagnose("BLOCKED", "qualification.decision_authentication",
                         "consistent measured FAIL checks",
                         workload=workload,
                         reason="reported failure contradicts decision evidence")
                continue
            diagnose("FAIL", "qualification.decision_status", "PASS",
                     workload=workload,
                     reason="verified frozen measurements failed")
        elif decision_status != "PASS":
            diagnose("BLOCKED", "qualification.decision_status", "PASS",
                     workload=workload,
                     reason="cohort decision is incomplete or unavailable")
            # An incomplete cohort can still carry independently observed raw
            # screening drift; keep its bounded BLOCKED diagnostic visible.
            if spec["evidence"] == "statistical_paired":
                spread = (summary.get("raw_repeat_spread") or {}).get(workload)
                bound = QUALIFICATION["CONTRACT"]["screening"][
                    "same_workload_raw_spread_max"]
                if (type(spread) in (int, float) and math.isfinite(spread)
                        and spread > bound):
                    diagnose("BLOCKED", "raw_repeat_spread",
                             {"operator": "<=", "value": bound,
                              "unit": "fraction"},
                             spread, workload=workload,
                             reason="raw drift screens out the cohort")
            continue
        elif any(value is False for value in
                 (decision.get("checks") or {}).values()):
            diagnose("BLOCKED", "qualification.decision_authentication",
                     "PASS consistent with measured checks",
                     workload=workload,
                     reason="PASS disposition contradicts failed checks")
            continue
        if not cohort_verified:
            # The aggregate decision cannot authorize PASS or measured metrics
            # when source, order, cohort counts or screening are incomplete.
            continue
        if spec["evidence"] == "statistical_paired":
            limits = QUALIFICATION["service_limits"](workload)
            for name, endpoint, op, bound in (
                    ("useful_write", "lower", ">=", "useful_write_ci_lower_min"),
                    ("lower_write_bytes", "upper", "<=", "lower_write_bytes_ci_upper_max"),
                    ("lower_write_requests", "upper", "<=", "lower_write_requests_ci_upper_max"),
                    ("read_p95", "upper", "<=", "tail_ci_upper_max"),
                    ("read_p99", "upper", "<=", "tail_ci_upper_max"),
                    ("write_p95", "upper", "<=", "tail_ci_upper_max"),
                    ("write_p99", "upper", "<=", "tail_ci_upper_max"),
                    ("cpu", "upper", "<=", "cpu_ci_upper_max")):
                if (decision.get("checks") or {}).get(name) is False:
                    ci = (decision.get("confidence_intervals") or {}).get(name)
                    value = ci.get(endpoint) if isinstance(ci, dict) else None
                    diagnose("FAIL", name + ".paired_95pct_ci_" + endpoint,
                             {"operator": op, "value": limits[bound],
                              "unit": "fractional_delta"},
                             value, workload=workload,
                             reason="frozen paired uncertainty bound failed")
            spread = (summary.get("raw_repeat_spread") or {}).get(workload)
            bound = QUALIFICATION["CONTRACT"]["screening"][
                "same_workload_raw_spread_max"]
            if type(spread) in (int, float) and math.isfinite(spread) and spread > bound:
                diagnose("BLOCKED", "raw_repeat_spread",
                         {"operator": "<=", "value": bound, "unit": "fraction"},
                         spread, workload=workload,
                         reason="raw drift screens out the cohort")
        elif workload == "sd-high-occupancy-churn":
            bounds = QUALIFICATION["CONTRACT"]["acceptance"]["sustained"]
            for name, op, bound in (
                    ("useful_write", ">=", "useful_write_ratio_min"),
                    ("lower_write_bytes", "<=", "lower_write_bytes_ratio_max"),
                    ("lower_write_requests", "<=", "lower_write_requests_ratio_max"),
                    ("read_p99", "<=", "tail_ratio_max"),
                    ("write_p99", "<=", "tail_ratio_max"),
                    ("cold_read_p99", "<=", "tail_ratio_max"),
                    ("throughput_drift", ">=", "throughput_drift_ratio_min"),
                    ("p99_drift", "<=", "p99_drift_ratio_max")):
                if (decision.get("checks") or {}).get(name) is False:
                    diagnose("FAIL", name + ".swapz_raw_ratio",
                             {"operator": op, "value": bounds[bound], "unit": "ratio"},
                             (decision.get("ratios") or {}).get(name),
                             workload=workload, pair_index=1,
                             reason="frozen 3600-second directional bound failed")
        elif workload == "anonymous-swap":
            bounds = QUALIFICATION["CONTRACT"]["acceptance"]["anonymous"]
            for position, result in enumerate(decision.get("pairs") or [], 1):
                for name, op, bound in (
                        ("swapin_p95", "<=", "swapin_tail_ratio_max"),
                        ("swapin_p99", "<=", "swapin_tail_ratio_max"),
                        ("useful_read", ">=", "useful_read_ratio_min"),
                        ("lower_write_bytes", "<=", "lower_write_bytes_ratio_max"),
                        ("lower_write_requests", "<=", "lower_write_requests_ratio_max"),
                        ("cpu", "<=", "cpu_ratio_max")):
                    value = (result.get("ratios") or {}).get(name)
                    if type(value) not in (int, float) or not math.isfinite(value):
                        continue
                    if value >= bounds[bound] if op == ">=" else value <= bounds[bound]:
                        continue
                    diagnose("FAIL", name + ".swapz_raw_ratio",
                             {"operator": op, "value": bounds[bound], "unit": "ratio"},
                             value, workload=workload, pair_index=position,
                             reason="frozen three-pair directional bound failed")
    return {
        # UNAVAILABLE is a diagnostic evidence class, never a campaign
        # disposition: missing required measurements block qualification.
        "status": ("FAIL" if "FAIL" in encountered_statuses else
                   "BLOCKED" if encountered_statuses else "PASS"),
        "diagnostics": diagnostics, "omitted_diagnostic_count": omitted,
        "qualification_status": (
            qualification_status if qualification_status in
            ("PASS", "FAIL_OR_INCOMPLETE") else "INVALID"),
        "first_failed_phase": first_failed_phase,
        "first_failed_evidence": first_terminal_failure or first_problem,
        "cohort_pair_counts": cohort_pair_counts,
        # Only validated non-path identifiers appear in public diagnostics.
        "admitted_source_sha": (
            before.get("source_sha")
            if isinstance(before.get("source_sha"), str) and
            re.fullmatch(r"[0-9a-f]{40}", before["source_sha"]) else None),
        "admitted_target_partuuid": QUALIFICATION["normalize_partuuid"](
            (before.get("device") or {}).get("partuuid")),
        "claim_boundary": QUALIFICATION["CONTRACT"]["claim_boundary"],
        "measurement_authority": "host-visible lower I/O, not NAND wear",
    }


def campaign_status(summary_status: str, source_consistent: bool,
                    protocol_v2: bool, stability_status: str,
                    target_consistent: bool = True,
                    arm_boot_consistent: bool = True,
                    physical_audit_ok: bool = True) -> str:
    if summary_status != "PASS":
        return "FAIL_OR_INCOMPLETE"
    if not source_consistent:
        return "BLOCKED_SOURCE_IDENTITY_CHANGED"
    if not protocol_v2:
        return "BLOCKED_PROTOCOL_NOT_V2"
    if not target_consistent:
        return "BLOCKED_TARGET_IDENTITY_CHANGED"
    if not arm_boot_consistent:
        return "BLOCKED_ARM_BOOT_IDENTITY_CHANGED"
    if stability_status != "STABLE":
        return "BLOCKED_HOST_IDENTITY_CHANGED"
    if not physical_audit_ok:
        return "BLOCKED_PHYSICAL_EVIDENCE"
    return "PASS"


def seal_campaign(source_sha: str, before_path: Path, after_path: Path,
                  summary_path: Path, pair_paths: list[Path],
                  metadata_ram_trace_path: Path | None = None) -> dict:
    require_clean_source(source_sha)
    evidence_paths = [before_path, after_path, summary_path, *pair_paths]
    if metadata_ram_trace_path is not None:
        evidence_paths.append(metadata_ram_trace_path)
    identities = []
    for path in evidence_paths:
        info = os.stat(path, follow_symlinks=False)
        identities.append((info.st_dev, info.st_ino))
    if len(set(identities)) != len(identities):
        raise ValueError("campaign evidence inputs must be distinct files")

    before, before_data = read_json(before_path)
    after, after_data = read_json(after_path)
    summary, summary_data = read_json(summary_path)
    metadata_ram_trace = None
    metadata_ram_trace_data = None
    if metadata_ram_trace_path is not None:
        metadata_ram_trace, metadata_ram_trace_data = read_json(
            metadata_ram_trace_path)
        if metadata_ram_trace_data != (
                json.dumps(metadata_ram_trace, indent=2,
                           sort_keys=True) + "\n").encode():
            raise ValueError("serialized RAM trace JSON is not canonical")
    validate_host_snapshot(before, source_sha)
    validate_host_snapshot(after, source_sha)
    if snapshot_time(after) <= snapshot_time(before):
        raise ValueError("campaign host snapshot time moved backwards")
    current_tree_sha = source_tree_sha(source_sha)
    if before["source_tree_sha"] != current_tree_sha or \
            after["source_tree_sha"] != current_tree_sha:
        raise ValueError("campaign host snapshots reference a different source tree")
    if summary.get("schema") != SUMMARY_SCHEMA:
        raise ValueError("campaign qualification summary uses an unknown schema")

    acceptance_data = read_regular_bytes(ACCEPTANCE_MANIFEST)
    amendment_data = read_regular_bytes(AMENDMENT_MANIFEST)
    evaluator_data = read_regular_bytes(QUALIFICATION_PATH)
    sealer_data = read_regular_bytes(EVIDENCE_PATH)
    validator_data = read_regular_bytes(RAM_VALIDATOR_PATH)
    if summary.get("acceptance_manifest_sha256") != sha256_bytes(acceptance_data):
        raise ValueError("qualification summary references a different acceptance manifest")
    acceptance = json.loads(
        acceptance_data.decode("utf-8"), object_pairs_hook=unique_object)
    local_amendment = json.loads(
        amendment_data.decode("utf-8"), object_pairs_hook=unique_object)
    if not identical_json_types_and_values(
            summary.get("contract"), acceptance.get("physical_qualification")):
        raise ValueError("qualification summary contract differs from frozen policy")
    if not identical_json_types_and_values(
            summary.get("prospective_amendment"), local_amendment):
        raise ValueError("qualification summary amendment differs from frozen policy")

    v1_workloads = set(
        (acceptance.get("physical_qualification") or {}).get("workloads") or {})
    v2_workloads = set(local_amendment.get("workloads") or {})
    protocol = summary.get("evaluation_protocol")
    if protocol == "v2" and summary.get("amendment_active") is True:
        expected_workloads = v1_workloads | v2_workloads
        protocol_v2 = True
    elif protocol == "v1" and summary.get("amendment_active") is False:
        expected_workloads = v1_workloads
        protocol_v2 = False
    else:
        raise ValueError("qualification summary protocol state is inconsistent")
    decisions = summary.get("decisions")
    if not isinstance(decisions, dict) or set(decisions) != expected_workloads:
        raise ValueError("qualification summary workload decision set is incomplete")
    decision_pass = all(
        isinstance(decision, dict) and decision.get("status") == "PASS"
        for decision in decisions.values())
    expected_summary_status = "PASS" if decision_pass else "FAIL_OR_INCOMPLETE"
    if summary.get("status") != expected_summary_status:
        raise ValueError("qualification summary status is inconsistent with decisions")

    records = summary.get("records")
    if not isinstance(records, list):
        raise ValueError("qualification summary records are missing")
    summary_by_key = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("qualification summary contains invalid record")
        key = pair_key(record)
        if key in summary_by_key:
            raise ValueError("qualification summary contains duplicate pair identity")
        summary_by_key[key] = record

    pair_artifacts, pair_records, seen_names, seen_keys = [], [], set(), set()
    for path in pair_paths:
        pair, data = read_json(path)
        if pair.get("schema") != PAIR_SCHEMA:
            raise ValueError(f"invalid pair schema: {path}")
        pair_records.append(pair)
        key = pair_key(pair)
        if key in seen_keys:
            raise ValueError("duplicate pair evidence supplied to campaign sealer")
        seen_keys.add(key)
        if path.name in seen_names:
            raise ValueError("campaign evidence basenames must be unique")
        seen_names.add(path.name)
        summary_record = summary_by_key.get(key)
        if summary_record is None:
            raise ValueError(f"pair is absent from evaluator summary: {path}")
        for field, value in pair.items():
            if (field not in summary_record or
                    not identical_json_types_and_values(summary_record[field], value)):
                raise ValueError(
                    f"summary changed original pair field {field}: {path}")
        pair_artifacts.append({
            **artifact(path, data),
            "workload": pair.get("workload"),
            "pair_id": pair.get("pair_id"),
            "pair_index": pair.get("pair_index"),
            "order": pair.get("order"),
            "status": pair.get("status"),
            "excluded": pair.get("excluded"),
        })
    if seen_keys != set(summary_by_key):
        raise ValueError(
            "campaign sealer requires every evaluator record, including failed/excluded attempts")

    regenerated = QUALIFICATION["evaluate"](pair_records, protocol=protocol)
    if not identical_json_types_and_values(regenerated, summary):
        raise ValueError(
            "qualification summary does not exactly match supplied pair evidence")

    pair_source_shas = sorted({
        pair.get("source_sha") for pair in pair_records
        if isinstance(pair.get("source_sha"), str)})
    summary_source_sha = summary.get("campaign_source_sha")
    source_consistent = (
        summary_source_sha == source_sha and pair_source_shas == [source_sha])

    stability = host_stability(before, after)
    target_identity = physical_target_identity(before)
    target_binding = qualification_target_binding(summary, before)
    capacity_and_ram = campaign_capacity_and_ram(
        pair_records, target_identity["device_bytes"], source_sha,
        metadata_ram_trace)
    if capacity_and_ram is not None:
        host_binding = {
            "host_boot_id": before["kernel"]["boot_id"],
            "host_before_captured_at_utc": before["captured_at_utc"],
            "host_after_captured_at_utc": after["captured_at_utc"],
            "memory_total_bytes": before["memory"]["total_bytes"],
        }
        if not metadata_ram_trace_within_host_window(
                capacity_and_ram, before, after):
            capacity_and_ram = None
        else:
            try:
                RAM_VALIDATOR["validate_metadata_ram_host_binding"](
                    capacity_and_ram["metadata_ram_trace"], host_binding)
            except ValueError:
                capacity_and_ram = None
            else:
                capacity_and_ram["metadata_ram_host_binding"] = host_binding
    physical_audit = audit_physical_pairs(summary, before, after)
    summary_status = summary.get("status")
    admitted_boot_id = before["kernel"]["boot_id"]
    arm_boot_consistent = all(
        isinstance(pair.get(label), dict) and
        pair[label].get("arm_boot_id") == admitted_boot_id
        for pair in pair_records for label in ("raw", "swapz"))
    sealed_status = campaign_status(
        summary_status, source_consistent, protocol_v2, stability["status"],
        target_binding["consistent"], arm_boot_consistent,
        physical_audit_ok=physical_audit["status"] == "PASS")
    if sealed_status == "PASS" and capacity_and_ram is None:
        limit = QUALIFICATION["CONTRACT"]["acceptance"]["sustained"][
            "metadata_and_target_peak_ram_bytes_max"]
        raise ValueError(
            "BLOCKED capacity/RAM evidence: phase=seal_campaign "
            "metric=metadata_and_target_peak_ram_bytes "
            f"limit={limit} observed=invalid_or_unavailable "
            "next_prerequisite=verified_source_boot_mapper_maximum_geometry_"
            "bound_loaded_host_trace_with_teardown")

    return {
        "schema": CAMPAIGN_SCHEMA,
        "sealed_at_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "source_sha": source_sha,
        "source_tree_sha": current_tree_sha,
        "campaign_source_sha": summary_source_sha,
        "pair_source_shas": pair_source_shas,
        "source_consistent": source_consistent,
        "campaign_status": sealed_status,
        "qualification_status": summary_status,
        "evaluation_protocol": summary.get("evaluation_protocol"),
        "target": target_identity,
        "qualification_target_binding": target_binding,
        "arm_boot_consistent": arm_boot_consistent,
        "physical_evidence_audit": physical_audit,
        "capacity_and_ram": capacity_and_ram,
        "host_stability": stability,
        "admitted_device_boundary": {
            "before": admitted_device_boundary(before),
            "after": admitted_device_boundary(after),
        },
        "policy": {
            "acceptance_manifest": {
                "name": ACCEPTANCE_MANIFEST.name,
                "sha256": sha256_bytes(acceptance_data),
                "git_blob_sha": git_blob_sha(acceptance_data),
            },
            "prospective_amendment": {
                "name": AMENDMENT_MANIFEST.name,
                "sha256": sha256_bytes(amendment_data),
                "git_blob_sha": git_blob_sha(amendment_data),
            },
            "evaluator": {
                "name": QUALIFICATION_PATH.name,
                "sha256": sha256_bytes(evaluator_data),
                "git_blob_sha": git_blob_sha(evaluator_data),
            },
            "evidence_sealer": {
                "name": EVIDENCE_PATH.name,
                "sha256": sha256_bytes(sealer_data),
                "git_blob_sha": git_blob_sha(sealer_data),
            },
            "metadata_ram_validator": {
                "name": RAM_VALIDATOR_PATH.name,
                "sha256": sha256_bytes(validator_data),
                "git_blob_sha": git_blob_sha(validator_data),
            },
        },
        "artifacts": {
            "host_before": artifact(before_path, before_data),
            "host_after": artifact(after_path, after_data),
            "qualification_summary": artifact(summary_path, summary_data),
            "metadata_ram_trace": (
                artifact(metadata_ram_trace_path, metadata_ram_trace_data)
                if metadata_ram_trace_path is not None else None),
            "pairs": pair_artifacts,
        },
        "record_count": len(pair_artifacts),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    snapshot = commands.add_parser("snapshot")
    snapshot.add_argument("--source-sha", required=True)
    snapshot.add_argument("--device", type=Path, required=True)
    snapshot.add_argument("--result", type=Path, required=True)

    seal = commands.add_parser("seal")
    seal.add_argument("--source-sha", required=True)
    seal.add_argument("--host-before", type=Path, required=True)
    seal.add_argument("--host-after", type=Path, required=True)
    seal.add_argument("--summary", type=Path, required=True)
    seal.add_argument("--pair", type=Path, action="append", default=[])
    seal.add_argument("--metadata-ram-trace", type=Path)
    seal.add_argument("--result", type=Path, required=True)

    args = parser.parse_args()
    try:
        if args.command == "snapshot":
            value = host_snapshot(args.source_sha, args.device)
        else:
            value = seal_campaign(
                args.source_sha, args.host_before, args.host_after,
                args.summary, args.pair, args.metadata_ram_trace)
        write_new_json(args.result, value)
        print(json.dumps(value, sort_keys=True))
    except (OSError, ValueError, TypeError, KeyError,
            subprocess.SubprocessError) as exc:
        parser.exit(2, "BLOCKED/FAIL: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
