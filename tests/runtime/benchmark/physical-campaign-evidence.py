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
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
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
            target_device_bytes <= 0):
        return None
    swapz = accepted[0].get("swapz")
    if not isinstance(swapz, dict):
        return None
    logical_pages = swapz.get("logical_pages")
    resources = swapz.get("resources")
    if type(logical_pages) is not int or logical_pages <= 0:
        return None
    logical_capacity_bytes = logical_pages * 4096
    # A smaller, easier-to-create mapper is not maximum-capacity evidence.
    if (logical_pages != RAM_VALIDATOR[
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
    limit = QUALIFICATION["CONTRACT"]["acceptance"]["sustained"][
        "metadata_and_target_peak_ram_bytes_max"]
    if peak_ram_bytes > limit:
        return None
    # The replay process cannot know a post-teardown host peak at start. Keep
    # any legacy scalar diagnostic only when it agrees; zero/missing has no
    # qualifying authority.
    replay_peak = (
        resources.get("metadata_and_target_peak_ram_bytes")
        if isinstance(resources, dict) else None)
    if replay_peak not in (None, 0, peak_ram_bytes):
        return None
    return {
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


def campaign_status(summary_status: str, source_consistent: bool,
                    protocol_v2: bool, stability_status: str,
                    target_consistent: bool = True,
                    arm_boot_consistent: bool = True) -> str:
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
    if snapshot_time(after) < snapshot_time(before):
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
    if summary.get("contract") != acceptance.get("physical_qualification"):
        raise ValueError("qualification summary contract differs from frozen policy")
    if summary.get("prospective_amendment") != local_amendment:
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
            if summary_record.get(field) != value:
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
    if regenerated != summary:
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
    if capacity_and_ram is not None and not metadata_ram_trace_within_host_window(
            capacity_and_ram, before, after):
        capacity_and_ram = None
    summary_status = summary.get("status")
    admitted_boot_id = before["kernel"]["boot_id"]
    arm_boot_consistent = all(
        isinstance(pair.get(label), dict) and
        pair[label].get("arm_boot_id") == admitted_boot_id
        for pair in pair_records for label in ("raw", "swapz"))
    sealed_status = campaign_status(
        summary_status, source_consistent, protocol_v2, stability["status"],
        target_binding["consistent"], arm_boot_consistent)
    if sealed_status == "PASS" and capacity_and_ram is None:
        raise ValueError(
            "PASS campaign lacks exact maximum-capacity/peak-RAM evidence")

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
