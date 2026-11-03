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
import os
import re
import stat
import subprocess
from pathlib import Path

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


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key}")
        result[key] = value
    return result


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
            data.decode("utf-8"), object_pairs_hook=unique_object)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"invalid JSON evidence {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON evidence must be one object: {path}")
    return value, data


def write_new_json(path: Path, value: dict) -> None:
    parent = path.parent
    if not parent.exists() or not parent.is_dir() or parent.is_symlink():
        raise ValueError("evidence output parent must be an existing real directory")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
        offset = 0
        while offset < len(payload):
            written = os.write(fd, payload[offset:])
            if written <= 0:
                raise OSError("short campaign evidence write")
            offset += written
        os.fsync(fd)
    finally:
        os.close(fd)


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
        rows.append({
            "path": fields[0], "type": fields[1],
            "size_kib": int(fields[2]), "used_kib": int(fields[3]),
            "priority": int(fields[4]),
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
    return {
        "requested_path": str(device),
        "resolved_path": str(resolved),
        "kernel_name": sys_path.name,
        "major_minor": major_minor,
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
    return {
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

    kernel = snapshot.get("kernel")
    cpu = snapshot.get("cpu")
    memory = snapshot.get("memory")
    device = snapshot.get("device")
    if not isinstance(kernel, dict) or not all(
            isinstance(kernel.get(key), str) and kernel.get(key)
            for key in ("release", "machine", "version", "node")):
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
            not all(isinstance(device.get(key), str) and device.get(key)
                    for key in ("physical_disk", "model", "transport", "partuuid")):
        raise ValueError("campaign physical-device identity is incomplete")
    queue = device.get("queue")
    if not isinstance(queue, dict) or \
            type(queue.get("logical_block_size")) is not int or \
            type(queue.get("physical_block_size")) is not int or \
            queue["logical_block_size"] <= 0 or queue["physical_block_size"] <= 0:
        raise ValueError("campaign physical-device queue geometry is incomplete")
    if not isinstance(snapshot.get("swap_inventory"), list) or \
            not isinstance(snapshot.get("mount_inventory"), str) or \
            not isinstance(snapshot.get("pressure"), dict) or \
            not isinstance(snapshot.get("thermal"), list) or \
            not isinstance(snapshot.get("dm_swapz_module"), dict):
        raise ValueError("campaign host context is incomplete")


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
        "device_major_minor":
            (before.get("device") or {}).get("major_minor") ==
            (after.get("device") or {}).get("major_minor"),
        "device_size_bytes":
            (before.get("device") or {}).get("size_bytes") ==
            (after.get("device") or {}).get("size_bytes"),
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
        "configured_cpus":
            (before.get("cpu") or {}).get("configured_cpus") ==
            (after.get("cpu") or {}).get("configured_cpus"),
        "online_cpus":
            (before.get("cpu") or {}).get("online_cpus") ==
            (after.get("cpu") or {}).get("online_cpus"),
        "affinity_cpus":
            (before.get("cpu") or {}).get("affinity_cpus") ==
            (after.get("cpu") or {}).get("affinity_cpus"),
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


def seal_campaign(source_sha: str, before_path: Path, after_path: Path,
                  summary_path: Path, pair_paths: list[Path]) -> dict:
    require_clean_source(source_sha)
    before, before_data = read_json(before_path)
    after, after_data = read_json(after_path)
    summary, summary_data = read_json(summary_path)
    validate_host_snapshot(before, source_sha)
    validate_host_snapshot(after, source_sha)
    current_tree_sha = source_tree_sha(source_sha)
    if before["source_tree_sha"] != current_tree_sha or \
            after["source_tree_sha"] != current_tree_sha:
        raise ValueError("campaign host snapshots reference a different source tree")
    if summary.get("schema") != SUMMARY_SCHEMA:
        raise ValueError("campaign qualification summary uses an unknown schema")
    if summary.get("campaign_source_sha") != source_sha:
        raise ValueError("campaign summary does not match exact source SHA")

    acceptance_data = read_regular_bytes(ACCEPTANCE_MANIFEST)
    amendment_data = read_regular_bytes(AMENDMENT_MANIFEST)
    evaluator_data = read_regular_bytes(QUALIFICATION_PATH)
    sealer_data = read_regular_bytes(EVIDENCE_PATH)
    if summary.get("acceptance_manifest_sha256") != sha256_bytes(acceptance_data):
        raise ValueError("qualification summary references a different acceptance manifest")
    amendment = summary.get("prospective_amendment")
    if not isinstance(amendment, dict) or amendment.get("schema") != \
            "swapz-performance-qualification-amendment-v2":
        raise ValueError("qualification summary lacks the prospective amendment")

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

    pair_artifacts, seen_names, seen_keys = [], set(), set()
    for path in pair_paths:
        pair, data = read_json(path)
        if pair.get("schema") != PAIR_SCHEMA:
            raise ValueError(f"invalid pair schema: {path}")
        if pair.get("source_sha") != source_sha:
            raise ValueError(f"pair source SHA differs from campaign: {path}")
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

    stability = host_stability(before, after)
    summary_status = summary.get("status")
    if summary_status == "PASS" and stability["status"] == "STABLE":
        campaign_status = "PASS"
    elif summary_status == "PASS":
        campaign_status = "BLOCKED_HOST_IDENTITY_CHANGED"
    else:
        campaign_status = "FAIL_OR_INCOMPLETE"

    return {
        "schema": CAMPAIGN_SCHEMA,
        "sealed_at_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "source_sha": source_sha,
        "source_tree_sha": current_tree_sha,
        "campaign_status": campaign_status,
        "qualification_status": summary_status,
        "evaluation_protocol": summary.get("evaluation_protocol"),
        "host_stability": stability,
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
        },
        "artifacts": {
            "host_before": artifact(before_path, before_data),
            "host_after": artifact(after_path, after_data),
            "qualification_summary": artifact(summary_path, summary_data),
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
    seal.add_argument("--result", type=Path, required=True)

    args = parser.parse_args()
    try:
        if args.command == "snapshot":
            value = host_snapshot(args.source_sha, args.device)
        else:
            value = seal_campaign(
                args.source_sha, args.host_before, args.host_after,
                args.summary, args.pair)
        write_new_json(args.result, value)
        print(json.dumps(value, sort_keys=True))
    except (OSError, ValueError, TypeError, KeyError,
            subprocess.SubprocessError) as exc:
        parser.exit(2, "BLOCKED/FAIL: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
