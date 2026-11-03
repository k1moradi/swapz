#!/usr/bin/env python3
"""Private native-host qualification for the primary swapz lifecycle.

This helper validates the exact transaction-owned primary mapper independently
of the primary manager's success text, drives a bounded cgroup-v2 anonymous
memory oracle through real Linux swap, and requests only the normal primary
stop path for teardown. It never calls swapon, swapoff, or dmsetup remove.

Exit status: 0 PASS, 1 FAIL after admission, 2 BLOCKED before safe admission or
when required independent evidence cannot be established.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, asdict
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
SELECTOR = Path("/etc/swapz/primary-target")
RECOVERY_BASE = Path("/var/lib/swapz/physical-recovery")
CGROUP_ROOT = Path("/sys/fs/cgroup")
AUTHORIZATION_SNAPSHOT = ROOT / "docs/handoff/production-readiness.json"
MAPPER_NAME = "swapz-primary"
PAGE_BYTES = 4096
MIB = 1024 * 1024
BLKGETSIZE64 = 0x80081272
SWAP_MAGIC = b"SWAPSPACE2"
SWAP_VERSION_OFFSET = 1024
SWAP_LAST_PAGE_OFFSET = 1028
SWAP_BAD_PAGES_OFFSET = 1032
SWAP_UUID_OFFSET = 1036
SWAP_UUID_BYTES = 16
MIN_AVAILABLE_MIB = 1024
MIN_TRAFFIC_MIB = 128
DEFAULT_WORKLOAD_MIB = 384
DEFAULT_RESIDENT_MIB = 128
DEFAULT_SWAP_LIMIT_MIB = 384
VERIFY_HEADROOM_MIB = 128
DEFAULT_TIMEOUT_SECONDS = 240
DEFAULT_CYCLES = 2
MAX_CYCLES = 4
RESULT_PREFIX = "PRIMARY_REAL_SWAP_RESULT="


class Blocked(RuntimeError):
    pass


class QualificationFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class SwapRow:
    path: str
    type: str
    size_kib: int
    used_kib: int
    priority: int
    device: tuple[int, int] | None = None


@dataclass(frozen=True)
class DmIdentity:
    name: str
    uuid: str
    major: int
    minor: int
    open_count: int


@dataclass(frozen=True)
class BlockStats:
    read_sectors: int
    write_sectors: int


@dataclass(frozen=True)
class StopSample:
    monotonic_ns: int
    mapper_before: bool
    mapper_after: bool
    swap_active: bool
    identity_valid: bool


def _run(argv: list[str], *, check: bool = True, timeout: float = 30,
         input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            argv,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Blocked(f"cannot execute required command {argv[0]}: {exc}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().replace("\n", "; ")
        raise QualificationFailure(
            f"command failed rc={result.returncode}: {' '.join(argv)}: {detail}")
    return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise Blocked(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _load_unique_json(text: str, label: str) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key {key}")
            result[key] = value
        return result
    try:
        value = json.loads(text, object_pairs_hook=unique)
    except (ValueError, TypeError) as exc:
        raise Blocked(f"cannot parse {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise Blocked(f"{label} is not a JSON object")
    return value


def parse_selector(text: str) -> str:
    lines = text.splitlines()
    if len(lines) != 1 or not lines[0].startswith("PARTUUID="):
        raise Blocked("primary target selector must contain exactly one PARTUUID line")
    partuuid = lines[0][len("PARTUUID="):]
    if not re.fullmatch(r"[0-9A-Fa-f][0-9A-Fa-f-]{6,62}[0-9A-Fa-f]", partuuid):
        raise Blocked("primary target selector PARTUUID is malformed")
    return partuuid.lower()


def _read_selector() -> str:
    try:
        info = SELECTOR.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or \
                stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
            raise Blocked("primary target selector must be root-owned mode 0600 regular file")
        return parse_selector(SELECTOR.read_text(encoding="ascii"))
    except Blocked:
        raise
    except OSError as exc:
        raise Blocked(f"cannot read primary target selector: {exc}") from exc


def parse_swap_rows(contents: str,
                    stat_func: Callable[[str], os.stat_result] = os.stat) -> list[SwapRow]:
    lines = contents.splitlines()
    if not lines or lines[0].split() != ["Filename", "Type", "Size", "Used", "Priority"]:
        raise Blocked("/proc/swaps header is malformed")
    rows: list[SwapRow] = []
    seen_paths: set[str] = set()
    for line in lines[1:]:
        fields = line.split()
        if len(fields) != 5 or not fields[0].startswith("/"):
            raise Blocked("/proc/swaps row is malformed")
        path, swap_type, size_text, used_text, priority_text = fields
        if path in seen_paths:
            raise Blocked("/proc/swaps contains duplicate paths")
        seen_paths.add(path)
        try:
            size_kib, used_kib, priority = int(size_text), int(used_text), int(priority_text)
        except ValueError as exc:
            raise Blocked("/proc/swaps has nonnumeric size/usage/priority") from exc
        if size_kib <= 0 or used_kib < 0 or used_kib > size_kib:
            raise Blocked("/proc/swaps usage is outside capacity")
        device = None
        try:
            info = stat_func(path)
            if stat.S_ISBLK(info.st_mode):
                device = (os.major(info.st_rdev), os.minor(info.st_rdev))
        except OSError:
            # A stale path cannot be considered a verified block identity. The
            # caller may still track a previously known path during stop.
            device = None
        rows.append(SwapRow(path, swap_type, size_kib, used_kib, priority, device))
    return rows


def read_swap_rows() -> list[SwapRow]:
    try:
        return parse_swap_rows(Path("/proc/swaps").read_text(encoding="ascii"))
    except OSError as exc:
        raise Blocked(f"cannot read /proc/swaps: {exc}") from exc


def _swap_identity(rows: list[SwapRow], excluded_device: tuple[int, int] | None = None) -> set[tuple]:
    result = set()
    for row in rows:
        if excluded_device is not None and row.device == excluded_device:
            continue
        result.add((row.path, row.type, row.size_kib, row.priority, row.device))
    return result


def _row_for_device(rows: list[SwapRow], device: tuple[int, int]) -> SwapRow | None:
    matches = [row for row in rows if row.device == device]
    if len(matches) > 1:
        raise QualificationFailure(f"multiple /proc/swaps aliases resolve to {device[0]}:{device[1]}")
    return matches[0] if matches else None


def require_expected_swap_priority(expected: SwapRow, unrelated: list[SwapRow]) -> None:
    for row in unrelated:
        if row.priority >= expected.priority:
            raise Blocked(
                "expected primary mapper is not the unique highest-priority swap area; "
                "real-swap traffic cannot be attributed without touching unrelated swap")


def parse_manifest(text: str) -> dict:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        if not raw_line or "=" not in raw_line:
            raise Blocked("primary manifest has malformed line")
        key, value = raw_line.split("=", 1)
        if not key or key in values:
            raise Blocked("primary manifest has duplicate/empty key")
        values[key] = value
    required = {
        "schema", "run_id", "source_sha", "swapzctl_sha256", "module_sha256",
        "qualification_report_sha256", "device_major", "device_minor", "partuuid",
        "device_bytes", "original_header_sha256", "logical_pages", "logical_sectors",
        "mapper_name", "mapper_uuid", "dm_table",
    }
    if set(values) != required or values.get("schema") != "swapz-primary-manifest-v2":
        raise Blocked("primary manifest schema/fields are not canonical")
    if not re.fullmatch(r"[0-9a-f]{32}", values["run_id"]):
        raise Blocked("primary manifest run_id is malformed")
    if not re.fullmatch(r"[0-9a-f]{40}", values["source_sha"]):
        raise Blocked("primary manifest source SHA is malformed")
    for key in ("swapzctl_sha256", "module_sha256", "qualification_report_sha256",
                "original_header_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", values[key]):
            raise Blocked(f"primary manifest {key} is malformed")
    try:
        major = int(values["device_major"])
        minor = int(values["device_minor"])
        device_bytes = int(values["device_bytes"])
        logical_pages = int(values["logical_pages"])
        logical_sectors = int(values["logical_sectors"])
    except ValueError as exc:
        raise Blocked("primary manifest numeric field is malformed") from exc
    if major <= 0 or minor < 0 or device_bytes <= PAGE_BYTES or logical_pages <= 0 or \
            logical_sectors != logical_pages * 8:
        raise Blocked("primary manifest geometry is invalid")
    if values["mapper_name"] != MAPPER_NAME or \
            values["mapper_uuid"] != f"SWAPZ-PRIMARY-{values['run_id']}":
        raise Blocked("primary manifest mapper identity is not run-bound")
    expected_table = f"0 {logical_sectors} swapz {major}:{minor} 0 64 0 2 0 1 0 0"
    if values["dm_table"] != expected_table:
        raise Blocked("primary manifest Device Mapper table is not canonical")
    values.update({
        "device_major_int": major,
        "device_minor_int": minor,
        "device_bytes_int": device_bytes,
        "logical_pages_int": logical_pages,
        "logical_sectors_int": logical_sectors,
    })
    return values


def read_state() -> dict | None:
    path = RECOVERY_BASE / "primary-state.json"
    if not path.exists():
        return None
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or \
                stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
            raise Blocked("primary state file identity/mode is unsafe")
        value = _load_unique_json(path.read_text(encoding="ascii"), "primary state")
    except OSError as exc:
        raise Blocked(f"cannot read primary state: {exc}") from exc
    if set(value) != {"schema", "run_id", "stage", "recovery_previous_stage"} or \
            value.get("schema") != "swapz-primary-state-v1" or \
            not re.fullmatch(r"[0-9a-f]{32}", str(value.get("run_id", ""))):
        raise Blocked("primary state record is malformed")
    return value


def read_manifest(run_id: str) -> dict:
    path = RECOVERY_BASE / f"primary-manifest-{run_id}.txt"
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or \
                stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
            raise Blocked("primary manifest identity/mode is unsafe")
        return parse_manifest(path.read_text(encoding="ascii"))
    except OSError as exc:
        raise Blocked(f"cannot read primary manifest: {exc}") from exc


def linux_swap_header(header: bytes, logical_pages: int) -> dict:
    if len(header) != PAGE_BYTES or logical_pages <= 0 or logical_pages > 0xFFFFFFFF:
        raise QualificationFailure("mapper Linux swap header has invalid geometry")
    version = struct.unpack_from("<I", header, SWAP_VERSION_OFFSET)[0]
    last_page = struct.unpack_from("<I", header, SWAP_LAST_PAGE_OFFSET)[0]
    bad_pages = struct.unpack_from("<I", header, SWAP_BAD_PAGES_OFFSET)[0]
    swap_uuid = header[SWAP_UUID_OFFSET:SWAP_UUID_OFFSET + SWAP_UUID_BYTES]
    if version != 1 or last_page != logical_pages - 1 or bad_pages != 0 or \
            header[-len(SWAP_MAGIC):] != SWAP_MAGIC or not any(swap_uuid):
        raise QualificationFailure("mapper Linux swap header is not canonical for manifest geometry")
    return {"uuid": swap_uuid.hex(), "last_page": last_page, "version": version}


def _read_mapper_header(path: Path, logical_pages: int) -> dict:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOCTTY)
        try:
            header = os.pread(fd, PAGE_BYTES, 0)
        finally:
            os.close(fd)
    except OSError as exc:
        raise QualificationFailure(f"cannot independently read mapper swap header: {exc}") from exc
    return linux_swap_header(header, logical_pages)


def parse_dm_info(text: str) -> DmIdentity:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        raise QualificationFailure("Device Mapper identity query is not unique")
    fields = [field.strip() for field in lines[0].split(":")]
    if len(fields) != 5:
        raise QualificationFailure("Device Mapper identity row is malformed")
    name, uuid, major_text, minor_text, open_text = fields
    try:
        major, minor, open_count = int(major_text), int(minor_text), int(open_text)
    except ValueError as exc:
        raise QualificationFailure("Device Mapper identity has nonnumeric fields") from exc
    if major <= 0 or minor < 0 or open_count < 0:
        raise QualificationFailure("Device Mapper identity fields are invalid")
    return DmIdentity(name, uuid, major, minor, open_count)


def _dm_identity() -> DmIdentity | None:
    result = _run([
        "dmsetup", "info", "-c", "--noheadings", "--separator", ":",
        "-o", "name,uuid,major,minor,open", MAPPER_NAME,
    ], check=False, timeout=10)
    if result.returncode != 0:
        return None
    return parse_dm_info(result.stdout)


def parse_dm_table(text: str, manifest: dict,
                   stat_func: Callable[[str], os.stat_result] = os.stat) -> dict:
    lines = [re.sub(r"\s+", " ", line.strip()) for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        raise QualificationFailure("Device Mapper table query is not unique")
    observed = lines[0].split(" ")
    expected = manifest["dm_table"].split(" ")
    if len(observed) != len(expected) or len(observed) < 5:
        raise QualificationFailure("Device Mapper table geometry is malformed")
    if observed[:3] != expected[:3] or observed[4:] != expected[4:]:
        raise QualificationFailure("Device Mapper table parameters differ from manifest")
    backing = observed[3]
    match = re.fullmatch(r"([0-9]+):([0-9]+)", backing)
    if match:
        backing_device = (int(match.group(1)), int(match.group(2)))
    else:
        path = backing if backing.startswith("/") else "/dev/" + backing
        try:
            info = stat_func(path)
        except OSError as exc:
            raise QualificationFailure(
                f"cannot resolve Device Mapper table backing identity {backing}: {exc}") from exc
        if not stat.S_ISBLK(info.st_mode):
            raise QualificationFailure("Device Mapper table backing is not a block device")
        backing_device = (os.major(info.st_rdev), os.minor(info.st_rdev))
    expected_device = (manifest["device_major_int"], manifest["device_minor_int"])
    if backing_device != expected_device:
        raise QualificationFailure("Device Mapper table backing differs from exact manifest device")
    return {"row": lines[0], "backing_device": backing_device}


def _dm_table(manifest: dict) -> dict:
    result = _run(["dmsetup", "table", "--showkeys", MAPPER_NAME], timeout=10)
    return parse_dm_table(result.stdout, manifest)


def _dm_dependency() -> tuple[int, int]:
    result = _run(["dmsetup", "deps", "--noheadings", "-o", "devno", MAPPER_NAME], timeout=10)
    matches = re.findall(r"\((\d+)\s*,\s*(\d+)\)", result.stdout)
    if len(matches) != 1:
        raise QualificationFailure("primary mapper does not have exactly one dependency")
    return int(matches[0][0]), int(matches[0][1])


def parse_status(text: str) -> dict[str, int]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        raise QualificationFailure("dmsetup status is not one canonical row")
    tokens = lines[0].split()
    if len(tokens) < 4 or tokens[2] != "swapz":
        raise QualificationFailure("dmsetup status is not a swapz target")
    values: dict[str, int] = {}
    for token in tokens[3:]:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        if key in values:
            raise QualificationFailure(f"duplicate swapz status token {key}")
        if re.fullmatch(r"-?[0-9]+", value):
            values[key] = int(value)
    for key in ("logical_write", "logical_read", "physical_write", "physical_read", "failed", "last_error"):
        if key not in values:
            raise QualificationFailure(f"swapz status lacks numeric token {key}")
    return values


def read_status() -> dict[str, int]:
    return parse_status(_run(["dmsetup", "status", MAPPER_NAME], timeout=10).stdout)


def read_block_stats(device: tuple[int, int]) -> BlockStats:
    path = Path(f"/sys/dev/block/{device[0]}:{device[1]}/stat")
    try:
        fields = path.read_text(encoding="ascii").split()
        numbers = [int(value) for value in fields]
    except (OSError, ValueError) as exc:
        raise Blocked(f"cannot read backing block statistics: {exc}") from exc
    if len(numbers) < 7 or any(number < 0 for number in numbers):
        raise Blocked("backing block statistics are malformed")
    return BlockStats(read_sectors=numbers[2], write_sectors=numbers[6])


def read_vmstat() -> dict[str, int]:
    wanted = {"pswpin", "pswpout"}
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/vmstat").read_text(encoding="ascii").splitlines():
            fields = line.split()
            if len(fields) == 2 and fields[0] in wanted:
                values[fields[0]] = int(fields[1])
    except (OSError, ValueError) as exc:
        raise Blocked(f"cannot read /proc/vmstat swap counters: {exc}") from exc
    if set(values) != wanted:
        raise Blocked("/proc/vmstat lacks swap counters")
    return values


def _read_uint(path: Path) -> int:
    try:
        value = path.read_text(encoding="ascii").strip()
        if not re.fullmatch(r"[0-9]+", value):
            raise ValueError(value)
        return int(value)
    except (OSError, ValueError) as exc:
        raise Blocked(f"cannot read numeric cgroup control {path.name}: {exc}") from exc


def _memory_events(path: Path) -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in path.read_text(encoding="ascii").splitlines():
            fields = line.split()
            if len(fields) != 2 or not re.fullmatch(r"[0-9]+", fields[1]):
                raise ValueError(line)
            values[fields[0]] = int(fields[1])
    except (OSError, ValueError) as exc:
        raise Blocked(f"cannot parse cgroup memory.events: {exc}") from exc
    return values


def _psi_total(path: Path, kind: str = "some") -> int:
    try:
        for line in path.read_text(encoding="ascii").splitlines():
            fields = line.split()
            if fields and fields[0] == kind:
                for field in fields[1:]:
                    if field.startswith("total="):
                        value = field.split("=", 1)[1]
                        if re.fullmatch(r"[0-9]+", value):
                            return int(value)
    except OSError as exc:
        raise Blocked(f"cannot read cgroup PSI: {exc}") from exc
    raise Blocked("cgroup PSI lacks total counter")


def _mem_available_mib() -> int:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            fields = line.split()
            if fields[:1] == ["MemAvailable:"] and len(fields) >= 2:
                return int(fields[1]) // 1024
    except (OSError, ValueError) as exc:
        raise Blocked(f"cannot read MemAvailable: {exc}") from exc
    raise Blocked("MemAvailable is unavailable")


def _block_size(path: Path) -> int:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOCTTY)
        try:
            return struct.unpack("=Q", fcntl.ioctl(fd, BLKGETSIZE64, bytes(8)))[0]
        finally:
            os.close(fd)
    except OSError as exc:
        raise Blocked(f"cannot verify block geometry for {path}: {exc}") from exc


def _flatten_lsblk(rows: list[dict]) -> list[dict]:
    result: list[dict] = []
    for row in rows:
        result.append(row)
        children = row.get("children")
        if isinstance(children, list):
            result.extend(_flatten_lsblk(children))
    return result


def _read_readiness_snapshot() -> dict:
    try:
        return _load_unique_json(
            AUTHORIZATION_SNAPSHOT.read_text(encoding="utf-8"),
            "production readiness snapshot")
    except OSError as exc:
        raise Blocked(f"cannot read committed production readiness snapshot: {exc}") from exc


def verify_acceptance_manifest() -> dict:
    snapshot = _read_readiness_snapshot()
    acceptance = snapshot.get("acceptance_manifest")
    if not isinstance(acceptance, dict) or acceptance.get("status") != "FROZEN":
        raise Blocked("quantitative production acceptance manifest is not frozen")
    return snapshot


def verify_authorized_target(plan: dict, selector_partuuid: str) -> tuple[Path, tuple[int, int]]:
    required_true = (
        "target_config_read", "target_device_preflight", "target_not_mounted",
        "target_device_chain_checked", "recovery_directory_safe",
        "recovery_filesystem_supported", "recovery_source_chain_checked",
        "recovery_active_marker_clear", "root_mount_source_chain_checked",
    )
    for key in required_true:
        if plan.get(key) is not True:
            raise Blocked(f"primary plan safety gate {key} is not true")
    if plan.get("root_same_physical_disk") is True or plan.get("recovery_same_physical_disk") is True:
        raise Blocked("target shares a physical disk with root or recovery storage")
    if str(plan.get("target_partuuid", "")).lower() != selector_partuuid:
        raise Blocked("primary plan target differs from protected selector")
    try:
        major = int(plan["target_device_major"])
        minor = int(plan["target_device_minor"])
        size_bytes = int(plan["target_device_bytes"])
        parent_major = int(plan["target_physical_parent_major"])
        parent_minor = int(plan["target_physical_parent_minor"])
    except (KeyError, TypeError, ValueError) as exc:
        raise Blocked("primary plan target geometry is unavailable") from exc

    by_partuuid = Path("/dev/disk/by-partuuid") / selector_partuuid
    try:
        target = by_partuuid.resolve(strict=True)
        info = target.stat()
    except OSError as exc:
        raise Blocked(f"authorized PARTUUID path is unavailable: {exc}") from exc
    if not stat.S_ISBLK(info.st_mode) or (os.major(info.st_rdev), os.minor(info.st_rdev)) != (major, minor):
        raise Blocked("authorized PARTUUID resolves to a different block device")
    if _block_size(target) != size_bytes:
        raise Blocked("authorized partition size changed")

    result = _run([
        "lsblk", "--json", "--bytes", "--output",
        "PATH,TYPE,MAJ:MIN,SIZE,PARTUUID,PKNAME,RM,TRAN,MODEL",
    ], timeout=15)
    try:
        rows = _flatten_lsblk(json.loads(result.stdout).get("blockdevices", []))
    except (ValueError, AttributeError) as exc:
        raise Blocked("cannot parse lsblk topology") from exc
    target_rows = [row for row in rows if row.get("maj:min") == f"{major}:{minor}"]
    parent_rows = [row for row in rows if row.get("maj:min") == f"{parent_major}:{parent_minor}"]
    if len(target_rows) != 1 or len(parent_rows) != 1:
        raise Blocked("cannot identify unique target partition and physical parent")
    target_row, parent_row = target_rows[0], parent_rows[0]
    if target_row.get("type") != "part" or str(target_row.get("partuuid", "")).lower() != selector_partuuid or \
            int(target_row.get("size", -1)) != size_bytes:
        raise Blocked("lsblk target identity differs from selector/plan")
    if parent_row.get("type") != "disk" or int(parent_row.get("rm", 0)) != 1 or \
            str(parent_row.get("tran", "")).lower() != "usb":
        raise Blocked("physical parent is not the authorized removable USB topology")

    try:
        snapshot = verify_acceptance_manifest()
        authorized = snapshot["authorized_target"]
        expected_parent = f"{parent_major}:{parent_minor}"
        if str(authorized.get("partuuid", "")).lower() != selector_partuuid or \
                int(authorized.get("size_bytes", -1)) != size_bytes or \
                str(authorized.get("parent_major_minor", "")) != expected_parent or \
                str(authorized.get("transport", "")).lower() != "usb" or \
                str(authorized.get("parent_model", "")).strip() != str(parent_row.get("model", "")).strip():
            raise Blocked("live target differs from committed authorized-target snapshot")
    except (KeyError, TypeError, ValueError) as exc:
        raise Blocked(f"committed authorized-target snapshot is malformed: {exc}") from exc
    return target, (major, minor)


def _kernel_log_snapshot() -> list[str]:
    result = _run(["dmesg", "--notime", "--level=emerg,alert,crit,err,warn"],
                  check=False, timeout=10)
    if result.returncode != 0:
        raise Blocked("kernel warning/error log is not readable")
    return result.stdout.splitlines()


def _kernel_log_delta(before: list[str], after: list[str]) -> list[str]:
    if len(after) < len(before) or after[:len(before)] != before:
        raise Blocked("kernel log changed non-monotonically; new errors cannot be attributed safely")
    return after[len(before):]


def _reject_relevant_kernel_errors(lines: list[str]) -> None:
    pattern = re.compile(
        r"swapz|dm_swapz|device-mapper.*swapz|BUG:|Oops:|Kernel panic|general protection|"
        r"KASAN:|UBSAN:|hung task|I/O error.*(?:dm-|sd[a-z])",
        re.IGNORECASE,
    )
    relevant = [line for line in lines if pattern.search(line)]
    if relevant:
        raise QualificationFailure("kernel reported relevant errors: " + " | ".join(relevant[:8]))


def _read_plan(swapzctl: Path) -> dict:
    result = _run([str(swapzctl), "primary", "plan"], check=False, timeout=30)
    if not result.stdout.strip():
        raise Blocked("primary plan produced no JSON")
    plan = _load_unique_json(result.stdout.strip(), "primary plan")
    return plan


def verify_provenance(plan: dict, validated_source: str, report_path: Path,
                      swapzctl: Path) -> None:
    required_true = (
        "control_build_source_clean", "module_build_provenance_read",
        "module_build_source_clean", "control_module_source_matches",
        "qualification_report_valid", "qualification_source_matches_build",
        "live_artifact_hashes_read", "live_artifacts_match_qualification",
    )
    for key in required_true:
        if plan.get(key) is not True:
            raise Blocked(f"primary provenance gate {key} is not true")
    if plan.get("control_build_source_sha") != validated_source:
        raise Blocked("primary control binary source SHA differs from validated source")
    report_digest = _sha256_file(report_path)
    if plan.get("qualification_report_sha256") != report_digest:
        raise Blocked("imported qualification report digest differs from supplied report")
    if plan.get("qualified_swapzctl_sha256") != plan.get("live_swapzctl_sha256") or \
            plan.get("qualified_module_sha256") != plan.get("live_module_sha256"):
        raise Blocked("live userspace/module artifacts differ from qualification")
    if _sha256_file(swapzctl) != plan.get("qualified_swapzctl_sha256"):
        raise Blocked("executed swapzctl bytes differ from qualified userspace artifact")
    if plan.get("privileged_execution_enabled") is not True:
        raise Blocked("primary privileged lifecycle execution gate is still disabled")


def _check_git_source(validated_source: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", validated_source):
        raise Blocked("validated source must be one full lowercase SHA")
    head = _run(["git", "rev-parse", "HEAD"], timeout=10).stdout.strip()
    if head != validated_source:
        raise Blocked(f"checkout HEAD {head} differs from validated source {validated_source}")
    dirty = _run(["git", "status", "--porcelain"], timeout=10).stdout
    if dirty:
        raise Blocked("production source tree is not clean")


def _ensure_commands(names: tuple[str, ...]) -> None:
    for name in names:
        if shutil.which(name) is None:
            raise Blocked(f"missing required command {name}")


def _validate_precycle_state(partuuid: str, target_device: tuple[int, int], baseline: list[SwapRow]) -> None:
    state = read_state()
    if state is not None and state.get("stage") != "COMPLETE":
        raise Blocked(f"unresolved primary state {state.get('stage')}")
    marker = RECOVERY_BASE / f"partition-{partuuid}.active"
    if marker.exists():
        raise Blocked("selected partition already has an active ownership marker")
    if _dm_identity() is not None:
        raise Blocked("primary mapper already exists before cycle")
    if _row_for_device(baseline, target_device) is not None:
        raise Blocked("raw backing partition is already active swap")
    if Path("/sys/module/dm_swapz").exists():
        raise Blocked("dm_swapz is already loaded before primary cycle")


def _read_primary_output(result: subprocess.CompletedProcess[str], prefix: str) -> str:
    for line in result.stdout.splitlines():
        if line.startswith(prefix):
            return line
    raise QualificationFailure(f"primary command omitted expected marker {prefix}")


def _primary(swapzctl: Path, action: str, timeout: float, *, admitted: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [str(swapzctl), "primary", action],
            text=True, capture_output=True, timeout=timeout, check=False,
            env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
    except subprocess.TimeoutExpired as exc:
        if admitted:
            raise QualificationFailure(f"primary {action} exceeded {timeout}s timeout") from exc
        raise Blocked(f"primary {action} timed out before admission") from exc
    except OSError as exc:
        if admitted:
            raise QualificationFailure(f"cannot execute admitted primary {action}: {exc}") from exc
        raise Blocked(f"cannot execute primary {action}: {exc}") from exc


def verify_active_mapper(manifest: dict, baseline_swap_identity: set[tuple]) -> dict:
    expected_uuid = manifest["mapper_uuid"]
    target_device = (manifest["device_major_int"], manifest["device_minor_int"])
    identity = _dm_identity()
    if identity is None:
        raise QualificationFailure("PRIMARY_START=ACTIVE but primary mapper is absent")
    if identity.name != MAPPER_NAME or identity.uuid != expected_uuid:
        raise QualificationFailure("primary mapper name/UUID differs from transaction manifest")
    mapper_device = (identity.major, identity.minor)
    mapper_path = Path("/dev/mapper") / MAPPER_NAME
    try:
        info = mapper_path.stat()
    except OSError as exc:
        raise QualificationFailure(f"primary mapper node is unavailable: {exc}") from exc
    if not stat.S_ISBLK(info.st_mode) or (os.major(info.st_rdev), os.minor(info.st_rdev)) != mapper_device:
        raise QualificationFailure("primary mapper node device number differs from dm identity")
    sysfs_uuid = Path(f"/sys/dev/block/{identity.major}:{identity.minor}/dm/uuid")
    try:
        if sysfs_uuid.read_text(encoding="ascii").strip() != expected_uuid:
            raise QualificationFailure("primary mapper sysfs UUID differs from manifest")
    except OSError as exc:
        raise QualificationFailure(f"cannot read primary mapper sysfs UUID: {exc}") from exc
    _dm_table(manifest)
    if _dm_dependency() != target_device:
        raise QualificationFailure("primary mapper dependency differs from exact backing partition")

    swaps = read_swap_rows()
    expected_swap = _row_for_device(swaps, mapper_device)
    if expected_swap is None:
        raise QualificationFailure("PRIMARY_START=ACTIVE but exact mapper is absent from /proc/swaps")
    if _row_for_device(swaps, target_device) is not None:
        raise QualificationFailure("raw backing partition is active swap instead of only the mapper")
    unrelated = [row for row in swaps if row.device != mapper_device]
    if _swap_identity(unrelated) != baseline_swap_identity:
        raise QualificationFailure("unexpected swap entry appeared or baseline swap identity changed")
    require_expected_swap_priority(expected_swap, unrelated)
    expected_size_kib = manifest["logical_pages_int"] * PAGE_BYTES // 1024 - PAGE_BYTES // 1024
    if expected_swap.type != "partition" or expected_swap.size_kib != expected_size_kib:
        raise QualificationFailure("/proc/swaps mapper geometry differs from manifest Linux swap size")
    if expected_swap.used_kib != 0:
        raise QualificationFailure("fresh mapper begins with nonzero Linux swap usage")
    header = _read_mapper_header(mapper_path, manifest["logical_pages_int"])
    status = read_status()
    if status["failed"] != 0 or status["last_error"] != 0:
        raise QualificationFailure("fresh primary mapper already reports target failure")
    return {
        "mapper_device": mapper_device,
        "mapper_uuid": expected_uuid,
        "swap_path": expected_swap.path,
        "swap_priority": expected_swap.priority,
        "swap_uuid": header["uuid"],
        "status": status,
    }


def _write_control(path: Path, value: str, *, admitted: bool = False) -> None:
    error_type = QualificationFailure if admitted else Blocked
    try:
        path.write_text(value + "\n", encoding="ascii")
        observed = path.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise error_type(f"cannot configure cgroup control {path.name}: {exc}") from exc
    if observed != value:
        raise error_type(f"cgroup control {path.name} did not retain requested value")


def _cgroup_prerequisites() -> None:
    controllers = CGROUP_ROOT / "cgroup.controllers"
    subtree = CGROUP_ROOT / "cgroup.subtree_control"
    try:
        if "memory" not in controllers.read_text(encoding="ascii").split() or \
                "memory" not in subtree.read_text(encoding="ascii").split():
            raise Blocked("cgroup v2 memory controller is not delegated")
    except Blocked:
        raise
    except OSError as exc:
        raise Blocked(f"cannot inspect cgroup v2 controllers: {exc}") from exc


def _cgroup_create(token: str, resident_mib: int, swap_limit_mib: int,
                   *, admitted: bool = True) -> Path:
    _cgroup_prerequisites()
    error_type = QualificationFailure if admitted else Blocked
    cgroup = CGROUP_ROOT / f"swapz-primary-real-swap-{token}"
    created = False
    try:
        cgroup.mkdir(mode=0o755)
        created = True
        required = (
            "cgroup.procs", "memory.max", "memory.swap.max", "memory.zswap.max",
            "memory.swap.current", "memory.swap.peak", "memory.current",
            "memory.events", "memory.pressure",
        )
        for name in required:
            if not (cgroup / name).exists():
                raise error_type(f"dedicated cgroup lacks required control {name}")
        _write_control(cgroup / "memory.max", str(resident_mib * MIB), admitted=admitted)
        _write_control(cgroup / "memory.swap.max", str(swap_limit_mib * MIB), admitted=admitted)
        _write_control(cgroup / "memory.zswap.max", "0", admitted=admitted)
        if (cgroup / "memory.oom.group").exists():
            _write_control(cgroup / "memory.oom.group", "1", admitted=admitted)
        return cgroup
    except Exception:
        if created:
            try:
                if not (cgroup / "cgroup.procs").read_text(encoding="ascii").strip():
                    cgroup.rmdir()
            except OSError:
                pass
        raise


def preflight_workload_environment(workload_mib: int, resident_mib: int,
                                   swap_limit_mib: int) -> None:
    if not (64 <= resident_mib < workload_mib <= 512):
        raise Blocked("workload must be 64..512 MiB with resident limit below workload")
    if workload_mib - resident_mib < MIN_TRAFFIC_MIB:
        raise Blocked(
            f"workload must expose at least {MIN_TRAFFIC_MIB} MiB above the resident limit")
    if not (workload_mib - resident_mib + MIN_TRAFFIC_MIB <= swap_limit_mib <= 512):
        raise Blocked("swap limit is too small for bounded workload or exceeds 512 MiB")
    required_available = max(MIN_AVAILABLE_MIB, workload_mib + 512)
    if _mem_available_mib() < required_available:
        raise Blocked(f"host lacks required MemAvailable headroom ({required_available} MiB)")
    token = "preflight-" + os.urandom(8).hex()
    cgroup = _cgroup_create(token, resident_mib, swap_limit_mib, admitted=False)
    try:
        _read_uint(cgroup / "memory.swap.current")
        _read_uint(cgroup / "memory.swap.peak")
        _memory_events(cgroup / "memory.events")
        _psi_total(cgroup / "memory.pressure")
    finally:
        try:
            if (cgroup / "cgroup.procs").read_text(encoding="ascii").strip():
                raise Blocked("preflight cgroup unexpectedly contains processes")
            cgroup.rmdir()
        except Blocked:
            raise
        except OSError as exc:
            raise Blocked(f"cannot remove preflight cgroup: {exc}") from exc


def _remove_cgroup(cgroup: Path) -> None:
    if not cgroup.exists():
        return
    try:
        procs = (cgroup / "cgroup.procs").read_text(encoding="ascii").split()
    except OSError:
        procs = ["unknown"]
    if procs:
        raise QualificationFailure("dedicated real-swap cgroup still has processes; no force cleanup attempted")
    try:
        cgroup.rmdir()
    except OSError as exc:
        raise QualificationFailure(f"cannot remove empty real-swap cgroup: {exc}") from exc


def _terminate_child(process: subprocess.Popen[str], cgroup: Path) -> None:
    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    # The helper has exactly one child process and no grandchildren.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            if not (cgroup / "cgroup.procs").read_text(encoding="ascii").strip():
                return
        except OSError:
            return
        time.sleep(0.05)


def _oracle_event(process: subprocess.Popen[str], prefix: str, deadline: float,
                  guard: Callable[[], None]) -> dict:
    if process.stdout is None:
        raise QualificationFailure("oracle stdout pipe is unavailable")
    fd = process.stdout.fileno()
    while True:
        guard()
        if process.poll() is not None:
            stderr = process.stderr.read().strip() if process.stderr else ""
            raise QualificationFailure(f"real-swap oracle exited before {prefix}: rc={process.returncode} {stderr}")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise QualificationFailure(f"real-swap oracle timed out waiting for {prefix}")
        readable, _, _ = select.select([fd], [], [], min(0.1, remaining))
        if not readable:
            continue
        line = process.stdout.readline()
        if not line:
            continue
        line = line.strip()
        if not line.startswith(prefix):
            raise QualificationFailure(f"real-swap oracle emitted unexpected record: {line}")
        try:
            value = json.loads(line[len(prefix):])
        except ValueError as exc:
            raise QualificationFailure("real-swap oracle emitted malformed JSON") from exc
        if not isinstance(value, dict):
            raise QualificationFailure("real-swap oracle record is not an object")
        return value


def evaluate_workload_evidence(*, cgroup_swap_bytes: int, cgroup_swap_peak: int,
                               min_swap_bytes: int, oom_delta: int, oom_kill_delta: int,
                               mapper_used_delta_kib: int,
                               fill_status_before: dict[str, int], fill_status_after: dict[str, int],
                               verify_status_before: dict[str, int], verify_status_after: dict[str, int],
                               lower_before: BlockStats, lower_after_fill: BlockStats,
                               lower_before_verify: BlockStats, lower_after_verify: BlockStats,
                               vm_before: dict[str, int], vm_after_fill: dict[str, int],
                               vm_before_verify: dict[str, int], vm_after_verify: dict[str, int],
                               oracle: dict) -> None:
    if cgroup_swap_bytes < min_swap_bytes or cgroup_swap_peak < min_swap_bytes:
        raise QualificationFailure("bounded cgroup never accumulated required real swap usage")
    if oom_delta != 0 or oom_kill_delta != 0:
        raise QualificationFailure("bounded real-swap workload encountered cgroup OOM")
    if mapper_used_delta_kib <= 0:
        raise QualificationFailure("exact mapper /proc/swaps usage never increased")
    if fill_status_after["logical_write"] <= fill_status_before["logical_write"] or \
            fill_status_after["physical_write"] <= fill_status_before["physical_write"]:
        raise QualificationFailure("swapz target counters show no real swap-out WRITE activity")
    if lower_after_fill.write_sectors <= lower_before.write_sectors:
        raise QualificationFailure("backing partition counters show no lower WRITE activity")
    if vm_after_fill["pswpout"] <= vm_before["pswpout"]:
        raise QualificationFailure("kernel vmstat shows no swap-out during admitted workload")
    if verify_status_after["logical_read"] <= verify_status_before["logical_read"] or \
            verify_status_after["physical_read"] <= verify_status_before["physical_read"]:
        raise QualificationFailure("swapz target counters show no real swap-in READ activity")
    if lower_after_verify.read_sectors <= lower_before_verify.read_sectors:
        raise QualificationFailure("backing partition counters show no lower READ activity")
    if vm_after_verify["pswpin"] <= vm_before_verify["pswpin"]:
        raise QualificationFailure("kernel vmstat shows no swap-in during byte verification")
    if oracle.get("mismatches") != 0 or oracle.get("digest") != oracle.get("expected_digest") or \
            int(oracle.get("verified_pages", 0)) <= 0:
        raise QualificationFailure("real-swap byte oracle reported corruption or incomplete verification")
    for status in (fill_status_after, verify_status_after):
        if status["failed"] != 0 or status["last_error"] != 0:
            raise QualificationFailure("swapz target entered failed state during real-swap workload")


def _run_workload(manifest: dict, active: dict, oracle_path: Path,
                  workload_mib: int, resident_mib: int, swap_limit_mib: int,
                  timeout_seconds: int) -> dict:
    token = os.urandom(8).hex()
    cgroup = _cgroup_create(token, resident_mib, swap_limit_mib, admitted=True)
    process: subprocess.Popen[str] | None = None
    events_before = _memory_events(cgroup / "memory.events")
    psi_before = _psi_total(cgroup / "memory.pressure")
    try:
        process = subprocess.Popen(
            [sys.executable, "-B", str(oracle_path), "--seed", manifest["run_id"],
             "--memory-mib", str(workload_mib)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env={**os.environ, "LC_ALL": "C", "LANG": "C"},
        )
        try:
            (cgroup / "cgroup.procs").write_text(f"{process.pid}\n", encoding="ascii")
        except OSError as exc:
            raise Blocked(f"cannot move oracle into dedicated cgroup: {exc}") from exc
        deadline = time.monotonic() + timeout_seconds

        def guard() -> None:
            events = _memory_events(cgroup / "memory.events")
            if events.get("oom", 0) > events_before.get("oom", 0) or \
                    events.get("oom_kill", 0) > events_before.get("oom_kill", 0):
                raise QualificationFailure("cgroup OOM occurred during admitted real-swap workload")
            if _read_uint(cgroup / "memory.swap.current") > swap_limit_mib * MIB:
                raise QualificationFailure("cgroup exceeded configured swap-usage bound")
            if _mem_available_mib() < 256:
                raise QualificationFailure("host MemAvailable crossed 256 MiB early-stop threshold")

        waiting = _oracle_event(process, "ORACLE_WAITING=", deadline, guard)
        if int(waiting.get("pid", -1)) != process.pid or int(waiting.get("bytes", 0)) != workload_mib * MIB:
            raise QualificationFailure("oracle readiness identity/geometry mismatch")
        fill_status_before = read_status()
        lower_before = read_block_stats((manifest["device_major_int"], manifest["device_minor_int"]))
        vm_before = read_vmstat()
        swaps_before = read_swap_rows()
        expected_before = _row_for_device(swaps_before, active["mapper_device"])
        if expected_before is None:
            raise QualificationFailure("expected mapper vanished before workload")
        if process.stdin is None:
            raise QualificationFailure("oracle command pipe is unavailable")
        process.stdin.write("FILL\n")
        process.stdin.flush()
        filled = _oracle_event(process, "ORACLE_FILLED=", deadline, guard)
        swap_current = _read_uint(cgroup / "memory.swap.current")
        swap_peak = _read_uint(cgroup / "memory.swap.peak")
        fill_status_after = read_status()
        lower_after_fill = read_block_stats((manifest["device_major_int"], manifest["device_minor_int"]))
        vm_after_fill = read_vmstat()
        swaps_after_fill = read_swap_rows()
        expected_after_fill = _row_for_device(swaps_after_fill, active["mapper_device"])
        if expected_after_fill is None:
            raise QualificationFailure("expected mapper vanished during swap-out")
        mapper_used_delta = expected_after_fill.used_kib - expected_before.used_kib
        min_swap_bytes = MIN_TRAFFIC_MIB * MIB
        if swap_current < min_swap_bytes or mapper_used_delta <= 0:
            raise QualificationFailure("fill completed without independently proven swapz swap-out")

        verify_status_before = read_status()
        lower_before_verify = read_block_stats((manifest["device_major_int"], manifest["device_minor_int"]))
        vm_before_verify = read_vmstat()
        _write_control(cgroup / "memory.max", str((workload_mib + VERIFY_HEADROOM_MIB) * MIB), admitted=True)
        process.stdin.write("VERIFY\n")
        process.stdin.flush()
        verified = _oracle_event(process, "ORACLE_VERIFIED=", deadline, guard)
        try:
            process.wait(timeout=max(1, int(deadline - time.monotonic())))
        except subprocess.TimeoutExpired as exc:
            raise QualificationFailure("oracle did not exit after byte verification") from exc
        if process.returncode != 0:
            stderr = process.stderr.read().strip() if process.stderr else ""
            raise QualificationFailure(f"oracle verification failed rc={process.returncode}: {stderr}")
        verify_status_after = read_status()
        lower_after_verify = read_block_stats((manifest["device_major_int"], manifest["device_minor_int"]))
        vm_after_verify = read_vmstat()
        events_after = _memory_events(cgroup / "memory.events")
        psi_after = _psi_total(cgroup / "memory.pressure")
        oom_delta = events_after.get("oom", 0) - events_before.get("oom", 0)
        oom_kill_delta = events_after.get("oom_kill", 0) - events_before.get("oom_kill", 0)
        evaluate_workload_evidence(
            cgroup_swap_bytes=swap_current,
            cgroup_swap_peak=swap_peak,
            min_swap_bytes=min_swap_bytes,
            oom_delta=oom_delta,
            oom_kill_delta=oom_kill_delta,
            mapper_used_delta_kib=mapper_used_delta,
            fill_status_before=fill_status_before,
            fill_status_after=fill_status_after,
            verify_status_before=verify_status_before,
            verify_status_after=verify_status_after,
            lower_before=lower_before,
            lower_after_fill=lower_after_fill,
            lower_before_verify=lower_before_verify,
            lower_after_verify=lower_after_verify,
            vm_before=vm_before,
            vm_after_fill=vm_after_fill,
            vm_before_verify=vm_before_verify,
            vm_after_verify=vm_after_verify,
            oracle=verified,
        )
        return {
            "oracle_filled": filled,
            "oracle_verified": verified,
            "cgroup_swap_current_bytes_after_fill": swap_current,
            "cgroup_swap_peak_bytes": swap_peak,
            "cgroup_memory_pressure_some_usec": psi_after - psi_before,
            "mapper_used_delta_kib": mapper_used_delta,
            "swapz_logical_write_delta": fill_status_after["logical_write"] - fill_status_before["logical_write"],
            "swapz_physical_write_delta": fill_status_after["physical_write"] - fill_status_before["physical_write"],
            "swapz_logical_read_delta": verify_status_after["logical_read"] - verify_status_before["logical_read"],
            "swapz_physical_read_delta": verify_status_after["physical_read"] - verify_status_before["physical_read"],
            "lower_write_sector_delta": lower_after_fill.write_sectors - lower_before.write_sectors,
            "lower_read_sector_delta": lower_after_verify.read_sectors - lower_before_verify.read_sectors,
            "pswpout_delta": vm_after_fill["pswpout"] - vm_before["pswpout"],
            "pswpin_delta": vm_after_verify["pswpin"] - vm_before_verify["pswpin"],
            "oom_delta": oom_delta,
            "oom_kill_delta": oom_kill_delta,
        }
    finally:
        if process is not None:
            _terminate_child(process, cgroup)
        _remove_cgroup(cgroup)


def _mapper_sysfs_state(device: tuple[int, int], expected_uuid: str) -> tuple[bool, bool]:
    base = Path(f"/sys/dev/block/{device[0]}:{device[1]}")
    if not base.exists():
        return False, True
    uuid_path = base / "dm/uuid"
    try:
        observed = uuid_path.read_text(encoding="ascii").strip()
    except OSError:
        return True, False
    return True, observed == expected_uuid


def evaluate_stop_samples(samples: list[StopSample]) -> dict:
    if not samples:
        raise Blocked("stop sampler collected no observations")
    if any(not sample.identity_valid for sample in samples if sample.mapper_before or sample.mapper_after):
        raise QualificationFailure("mapper identity changed during stop")
    if any((not sample.mapper_before and not sample.mapper_after and sample.swap_active)
           for sample in samples):
        raise QualificationFailure("mapper disappeared while still present in swap inventory")
    initial = any(sample.mapper_before and sample.mapper_after and sample.swap_active for sample in samples)
    deactivated = any(sample.mapper_before and sample.mapper_after and not sample.swap_active for sample in samples)
    absent = any(not sample.mapper_before and not sample.mapper_after and not sample.swap_active for sample in samples)
    if not initial:
        raise Blocked("stop sampler did not witness initial active mapper")
    if not deactivated:
        raise Blocked("stop completed but sampler did not independently witness swapoff before mapper removal")
    if not absent:
        raise Blocked("stop sampler did not witness final mapper absence")
    return {"initial_active": True, "swapoff_before_remove_witness": True, "final_absent": True,
            "samples": len(samples)}


class StopSampler:
    def __init__(self, mapper_device: tuple[int, int], expected_uuid: str, known_swap_path: str):
        self.mapper_device = mapper_device
        self.expected_uuid = expected_uuid
        self.known_swap_path = known_swap_path
        self.samples: list[StopSample] = []
        self.error: Exception | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="swapz-stop-sampler", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> dict:
        self._stop.set()
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            raise Blocked("stop sampler thread did not terminate")
        if self.error:
            raise Blocked(f"stop sampler failed: {self.error}")
        return evaluate_stop_samples(self.samples)

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                before, identity_before = _mapper_sysfs_state(self.mapper_device, self.expected_uuid)
                rows = read_swap_rows()
                swap_active = any(
                    row.device == self.mapper_device or row.path == self.known_swap_path
                    for row in rows
                )
                after, identity_after = _mapper_sysfs_state(self.mapper_device, self.expected_uuid)
                self.samples.append(StopSample(
                    time.monotonic_ns(), before, after, swap_active,
                    (not before or identity_before) and (not after or identity_after),
                ))
                time.sleep(0.001)
        except Exception as exc:  # sampler errors become BLOCKED, never silent PASS
            self.error = exc


def _post_stop_verify(manifest: dict, active: dict, baseline_identity: set[tuple],
                      partuuid: str) -> None:
    rows = read_swap_rows()
    if _row_for_device(rows, active["mapper_device"]) is not None:
        raise QualificationFailure("exact mapper remains active swap after successful primary stop")
    if _row_for_device(rows, (manifest["device_major_int"], manifest["device_minor_int"])) is not None:
        raise QualificationFailure("raw backing partition became active swap during teardown")
    if _swap_identity(rows) != baseline_identity:
        raise QualificationFailure("unrelated swap inventory changed across primary cycle")
    if _dm_identity() is not None or Path(f"/sys/dev/block/{active['mapper_device'][0]}:{active['mapper_device'][1]}").exists():
        raise QualificationFailure("primary mapper remains after successful stop")
    if Path("/sys/module/dm_swapz").exists():
        raise QualificationFailure("transaction-owned dm_swapz module remains loaded after stop")
    state = read_state()
    if state is None or state.get("run_id") != manifest["run_id"] or state.get("stage") != "COMPLETE":
        raise QualificationFailure("durable primary state is not COMPLETE after stop")
    if (RECOVERY_BASE / f"partition-{partuuid}.active").exists():
        raise QualificationFailure("partition ownership marker remains after COMPLETE")


def _validate_prepared_manifest(manifest: dict, plan: dict, validated_source: str,
                                selector_partuuid: str) -> None:
    if manifest["source_sha"] != validated_source:
        raise QualificationFailure("prepared manifest source differs from validated source")
    if manifest["partuuid"].lower() != selector_partuuid:
        raise QualificationFailure("prepared manifest PARTUUID differs from protected selector")
    for manifest_key, plan_key in (
        ("swapzctl_sha256", "qualified_swapzctl_sha256"),
        ("module_sha256", "qualified_module_sha256"),
        ("qualification_report_sha256", "qualification_report_sha256"),
    ):
        if manifest[manifest_key] != plan.get(plan_key):
            raise QualificationFailure(f"prepared manifest {manifest_key} differs from qualified provenance")
    if manifest["device_major_int"] != int(plan["target_device_major"]) or \
            manifest["device_minor_int"] != int(plan["target_device_minor"]) or \
            manifest["device_bytes_int"] != int(plan["target_device_bytes"]):
        raise QualificationFailure("prepared manifest target identity differs from admitted target")


def _verify_completed_cleanup(manifest: dict, baseline_identity: set[tuple], partuuid: str) -> None:
    rows = read_swap_rows()
    target_device = (manifest["device_major_int"], manifest["device_minor_int"])
    if _row_for_device(rows, target_device) is not None:
        raise QualificationFailure("raw backing partition is active swap after cleanup")
    if _swap_identity(rows) != baseline_identity:
        raise QualificationFailure("swap inventory did not return to its pre-cycle identity")
    if _dm_identity() is not None:
        raise QualificationFailure("primary mapper remains after cleanup")
    if Path("/sys/module/dm_swapz").exists():
        raise QualificationFailure("transaction-owned dm_swapz module remains after cleanup")
    state = read_state()
    if state is None or state.get("run_id") != manifest["run_id"] or state.get("stage") != "COMPLETE":
        raise QualificationFailure("durable primary state is not COMPLETE after cleanup")
    if (RECOVERY_BASE / f"partition-{partuuid}.active").exists():
        raise QualificationFailure("partition ownership marker remains after cleanup")


def _cleanup_failed_start(swapzctl: Path, manifest: dict, baseline_identity: set[tuple],
                          partuuid: str, timeout_seconds: int, original_reason: str) -> None:
    state = read_state()
    if state is None or state.get("run_id") != manifest["run_id"]:
        raise QualificationFailure(original_reason + "; durable state cannot be reconciled automatically")
    if state.get("stage") == "ACTIVE":
        cleanup = _primary(swapzctl, "stop", timeout_seconds, admitted=True)
    elif state.get("stage") in {"STARTING", "STOPPING", "RECOVERY_REQUIRED", "RECOVERING", "RESTORED"}:
        cleanup = _primary(swapzctl, "recover", timeout_seconds, admitted=True)
    else:
        raise QualificationFailure(original_reason + f"; state {state.get('stage')} requires manual review")
    if cleanup.returncode != 0:
        detail = (cleanup.stderr or cleanup.stdout).strip().replace("\n", "; ")
        raise QualificationFailure(original_reason + f"; normal recovery cleanup failed rc={cleanup.returncode}: {detail}")
    _verify_completed_cleanup(manifest, baseline_identity, partuuid)
    raise QualificationFailure(original_reason)


def _normal_stop(swapzctl: Path, manifest: dict, active: dict | None,
                 baseline_identity: set[tuple], partuuid: str, timeout_seconds: int) -> dict | None:
    sampler = None
    sampler_evidence = None
    if active is not None:
        sampler = StopSampler(active["mapper_device"], active["mapper_uuid"], active["swap_path"])
        sampler.start()
        time.sleep(0.02)
    primary_error = None
    sampler_error = None
    stopped = None
    try:
        stopped = _primary(swapzctl, "stop", timeout_seconds, admitted=True)
    except Exception as exc:
        primary_error = exc
    finally:
        if sampler is not None:
            time.sleep(0.05)
            try:
                sampler_evidence = sampler.stop()
            except Exception as exc:
                sampler_error = exc
    if primary_error is not None:
        raise primary_error
    assert stopped is not None
    if stopped.returncode != 0:
        detail = (stopped.stderr or stopped.stdout).strip().replace("\n", "; ")
        raise QualificationFailure(
            f"primary stop/swapoff failed rc={stopped.returncode}; no force cleanup attempted: {detail}")
    if sampler_error is not None:
        raise sampler_error
    _read_primary_output(stopped, f"PRIMARY_STOP=COMPLETE run_id={manifest['run_id']} ")
    if active is not None:
        _post_stop_verify(manifest, active, baseline_identity, partuuid)
    else:
        _verify_completed_cleanup(manifest, baseline_identity, partuuid)
    return sampler_evidence


def run_cycle(index: int, *, swapzctl: Path, oracle_path: Path, validated_source: str,
              plan: dict, selector_partuuid: str, target_device: tuple[int, int],
              workload_mib: int, resident_mib: int, swap_limit_mib: int,
              timeout_seconds: int, prior_run_ids: set[str], prior_swap_uuids: set[str]) -> dict:
    baseline_rows = read_swap_rows()
    baseline_identity = _swap_identity(baseline_rows)
    _validate_precycle_state(selector_partuuid, target_device, baseline_rows)
    kernel_before = _kernel_log_snapshot()

    prepared = _primary(swapzctl, "prepare", timeout_seconds, admitted=True)
    if prepared.returncode != 0:
        detail = (prepared.stderr or prepared.stdout).strip().replace("\n", "; ")
        raise QualificationFailure(f"primary prepare failed after admission rc={prepared.returncode}: {detail}")
    marker = _read_primary_output(prepared, "PRIMARY_PREPARE=READY ")
    match = re.search(r"\brun_id=([0-9a-f]{32})\b", marker)
    if not match:
        raise QualificationFailure("primary prepare marker lacks canonical run_id")
    run_id = match.group(1)
    if run_id in prior_run_ids:
        raise QualificationFailure("primary reused a previous transaction run_id")
    state = read_state()
    if state is None or state.get("run_id") != run_id or state.get("stage") != "READY":
        raise QualificationFailure("durable state is not READY for prepared run")
    manifest = read_manifest(run_id)
    _validate_prepared_manifest(manifest, plan, validated_source, selector_partuuid)

    started = _primary(swapzctl, "start", timeout_seconds, admitted=True)
    if started.returncode != 0:
        detail = (started.stderr or started.stdout).strip().replace("\n", "; ")
        _cleanup_failed_start(
            swapzctl, manifest, baseline_identity, selector_partuuid, timeout_seconds,
            f"primary start failed after admitted prepare rc={started.returncode}: {detail}")

    active = None
    original_failure = None
    workload_result = None
    try:
        _read_primary_output(started, f"PRIMARY_START=ACTIVE run_id={run_id} ")
        state = read_state()
        if state is None or state.get("run_id") != run_id or state.get("stage") != "ACTIVE":
            raise QualificationFailure(
                "primary reported success without matching durable ACTIVE state")
        active = verify_active_mapper(manifest, baseline_identity)
        if active["swap_uuid"] in prior_swap_uuids:
            raise QualificationFailure("fresh mapper reused a previous Linux swap UUID")
        workload_result = _run_workload(
            manifest, active, oracle_path,
            workload_mib, resident_mib, swap_limit_mib, timeout_seconds,
        )
    except Exception as exc:
        original_failure = exc

    try:
        if original_failure is not None and active is None:
            # We cannot safely assume the start failed merely because independent
            # verification did. Reconcile the durable stage and request only the
            # coordinator's normal stop/recover path.
            state = read_state()
            if state is not None and state.get("run_id") == run_id and state.get("stage") == "ACTIVE":
                _normal_stop(
                    swapzctl, manifest, None, baseline_identity, selector_partuuid, timeout_seconds)
            else:
                _cleanup_failed_start(
                    swapzctl, manifest, baseline_identity, selector_partuuid, timeout_seconds,
                    str(original_failure))
            stop_evidence = None
        else:
            stop_evidence = _normal_stop(
                swapzctl, manifest, active, baseline_identity, selector_partuuid, timeout_seconds)
    except Exception as cleanup_error:
        if original_failure is not None:
            raise QualificationFailure(
                f"{original_failure}; normal stop/recovery also failed: {cleanup_error}") from cleanup_error
        raise
    kernel_after = _kernel_log_snapshot()
    _reject_relevant_kernel_errors(_kernel_log_delta(kernel_before, kernel_after))
    if original_failure is not None:
        raise original_failure
    if active is None or workload_result is None or stop_evidence is None:
        raise QualificationFailure("cycle completed without activation/workload/stop evidence")
    return {
        "cycle": index,
        "run_id": run_id,
        "mapper_uuid": active["mapper_uuid"],
        "mapper_device": f"{active['mapper_device'][0]}:{active['mapper_device'][1]}",
        "linux_swap_uuid": active["swap_uuid"],
        "swap_priority": active["swap_priority"],
        "workload": workload_result,
        "stop_order": stop_evidence,
        "fresh_mapper_used_kib": 0,
        "durable_final_stage": "COMPLETE",
    }


def _import_qualification(swapzctl: Path, report_path: Path) -> None:
    result = _run([str(swapzctl), "primary", "qualification-import", str(report_path)],
                  check=False, timeout=30)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().replace("\n", "; ")
        raise Blocked(f"cannot import exact qualification report: {detail}")


def execute(arguments: argparse.Namespace) -> dict:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        raise Blocked("physical real-swap qualification must not run in GitHub-hosted CI")
    if os.geteuid() != 0:
        raise Blocked("physical real-swap qualification requires noninteractive root privilege")
    _ensure_commands(("git", "dmsetup", "lsblk", "dmesg"))
    if os.sysconf("SC_PAGE_SIZE") != PAGE_BYTES:
        raise Blocked("primary real-swap qualification requires a 4096-byte host page")
    swapzctl = Path(arguments.swapzctl).resolve()
    report_path = Path(arguments.qualification_report).resolve()
    oracle_path = Path(arguments.oracle).resolve()
    for path, label in ((swapzctl, "swapzctl"), (report_path, "qualification report"),
                        (oracle_path, "real-swap oracle")):
        if not path.is_file():
            raise Blocked(f"{label} is unavailable: {path}")
    if not os.access(swapzctl, os.X_OK) or not os.access(oracle_path, os.X_OK):
        raise Blocked("swapzctl/oracle executable permission is missing")
    _check_git_source(arguments.validated_source)
    preflight_workload_environment(
        arguments.workload_mib, arguments.resident_mib, arguments.swap_limit_mib)
    verify_acceptance_manifest()
    _kernel_log_snapshot()
    _import_qualification(swapzctl, report_path)
    plan = _read_plan(swapzctl)
    verify_provenance(plan, arguments.validated_source, report_path, swapzctl)
    selector_partuuid = _read_selector()
    _target_path, target_device = verify_authorized_target(plan, selector_partuuid)
    baseline = read_swap_rows()
    _validate_precycle_state(selector_partuuid, target_device, baseline)
    kernel_before = _kernel_log_snapshot()
    _reject_relevant_kernel_errors([])

    run_ids: set[str] = set()
    swap_uuids: set[str] = set()
    cycles = []
    for cycle_index in range(1, arguments.cycles + 1):
        result = run_cycle(
            cycle_index,
            swapzctl=swapzctl,
            oracle_path=oracle_path,
            validated_source=arguments.validated_source,
            plan=plan,
            selector_partuuid=selector_partuuid,
            target_device=target_device,
            workload_mib=arguments.workload_mib,
            resident_mib=arguments.resident_mib,
            swap_limit_mib=arguments.swap_limit_mib,
            timeout_seconds=arguments.timeout_seconds,
            prior_run_ids=run_ids,
            prior_swap_uuids=swap_uuids,
        )
        run_ids.add(result["run_id"])
        swap_uuids.add(result["linux_swap_uuid"])
        cycles.append(result)
    kernel_after = _kernel_log_snapshot()
    _reject_relevant_kernel_errors(_kernel_log_delta(kernel_before, kernel_after))
    return {
        "schema": "swapz-primary-real-swap-v1",
        "status": "PASS",
        "source_sha": arguments.validated_source,
        "helper_sha256": _sha256_file(Path(__file__)),
        "oracle_sha256": _sha256_file(oracle_path),
        "qualification_report_sha256": _sha256_file(report_path),
        "partuuid": selector_partuuid,
        "target_device": f"{target_device[0]}:{target_device[1]}",
        "cycles_requested": arguments.cycles,
        "cycles_passed": len(cycles),
        "workload_mib": arguments.workload_mib,
        "resident_limit_mib": arguments.resident_mib,
        "swap_limit_mib": arguments.swap_limit_mib,
        "timeout_seconds": arguments.timeout_seconds,
        "cycles": cycles,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validated-source", required=True)
    parser.add_argument("--qualification-report", required=True)
    parser.add_argument("--swapzctl", default=str(ROOT / "build/userspace/swapzctl"))
    parser.add_argument("--oracle", default=str(ROOT / "tests/tools/primary-real-swap-oracle.py"))
    parser.add_argument("--cycles", type=int, default=DEFAULT_CYCLES)
    parser.add_argument("--workload-mib", type=int, default=DEFAULT_WORKLOAD_MIB)
    parser.add_argument("--resident-mib", type=int, default=DEFAULT_RESIDENT_MIB)
    parser.add_argument("--swap-limit-mib", type=int, default=DEFAULT_SWAP_LIMIT_MIB)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    return parser


def main() -> int:
    parser = build_parser()
    arguments = parser.parse_args()
    if not 2 <= arguments.cycles <= MAX_CYCLES:
        print("BLOCKED_PRIMARY_REAL_SWAP=cycles_must_be_2_to_4", file=sys.stderr)
        return 2
    if not 60 <= arguments.timeout_seconds <= 600:
        print("BLOCKED_PRIMARY_REAL_SWAP=timeout_must_be_60_to_600_seconds", file=sys.stderr)
        return 2
    try:
        result = execute(arguments)
    except Blocked as exc:
        payload = {"schema": "swapz-primary-real-swap-v1", "status": "BLOCKED",
                   "reason": str(exc)}
        print("BLOCKED_PRIMARY_REAL_SWAP=" + str(exc).replace("\n", "; "), file=sys.stderr)
        print(RESULT_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return 2
    except QualificationFailure as exc:
        payload = {"schema": "swapz-primary-real-swap-v1", "status": "FAIL",
                   "reason": str(exc)}
        print("FAIL_PRIMARY_REAL_SWAP=" + str(exc).replace("\n", "; "), file=sys.stderr)
        print(RESULT_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return 1
    print(
        "PASS_PRIMARY_REAL_SWAP="
        f"cycles:{result['cycles_passed']} source:{result['source_sha']} "
        f"target:{result['target_device']}")
    print(RESULT_PREFIX + json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
