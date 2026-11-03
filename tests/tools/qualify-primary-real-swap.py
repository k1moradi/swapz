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
import socket
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
ACCEPTANCE_MANIFEST = ROOT / "docs/production-acceptance.json"
REAL_SWAP_ORACLE = ROOT / "tests/tools/primary-real-swap-oracle.py"
MAPPER_NAME = "swapz-primary"
PAGE_BYTES = 4096
SEGMENT_BLOCKS = 256
MIN_RESERVE_BLOCKS = 2 * SEGMENT_BLOCKS
FOREGROUND_HEADROOM_BLOCKS = SEGMENT_BLOCKS
UINT32_MAX = (1 << 32) - 1
MIB = 1024 * 1024
SECTOR_BYTES = 512
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
CONCURRENT_ORACLE_PROCESSES = 2
REUSE_ROUNDS = 2
RESULT_PREFIX = "PRIMARY_REAL_SWAP_RESULT="
SOURCE_ADMISSION_SCHEMA = "swapz-primary-real-swap-admission-v1"
SOURCE_ADMISSION_MAX_LINE_BYTES = 4096
SOURCE_ADMISSION_TIMEOUT_SECONDS = 45


class Blocked(RuntimeError):
    pass


class QualificationFailure(RuntimeError):
    pass


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key}")
        result[key] = value
    return result


class SourceAdmissionClient:
    """Authenticated channel to the unprivileged source-verification parent."""

    def __init__(self, socket_path: str, parent_uid: int, validated_source: str):
        if not re.fullmatch(r"[0-9a-f]{40}", validated_source):
            raise Blocked("validated source must be one full lowercase SHA")
        if parent_uid <= 0:
            raise Blocked("source admission parent must be unprivileged")
        path = Path(socket_path)
        if not path.is_absolute():
            raise Blocked("source admission socket path must be absolute")
        try:
            before = path.lstat()
        except OSError as exc:
            raise Blocked("source admission socket is unavailable") from exc
        if (not stat.S_ISSOCK(before.st_mode) or before.st_uid != parent_uid or
                stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1):
            raise Blocked("source admission socket ownership is unsafe")

        channel = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        channel.settimeout(SOURCE_ADMISSION_TIMEOUT_SECONDS)
        try:
            channel.connect(os.fspath(path))
            credentials = channel.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            _peer_pid, peer_uid, _peer_gid = struct.unpack("3i", credentials)
            after = path.lstat()
            before_identity = (
                before.st_dev, before.st_ino, before.st_uid,
                stat.S_IMODE(before.st_mode), before.st_nlink)
            after_identity = (
                after.st_dev, after.st_ino, after.st_uid,
                stat.S_IMODE(after.st_mode), after.st_nlink)
            if peer_uid != parent_uid or before_identity != after_identity:
                raise Blocked("source admission parent identity changed")
        except Exception:
            channel.close()
            raise
        self._channel = channel
        self._validated_source = validated_source

    def close(self) -> None:
        channel = getattr(self, "_channel", None)
        if channel is not None:
            self._channel = None
            channel.close()

    def _read_line(self) -> bytes:
        data = bytearray()
        while len(data) <= SOURCE_ADMISSION_MAX_LINE_BYTES:
            chunk = self._channel.recv(1)
            if not chunk:
                raise Blocked("source admission parent disconnected")
            if chunk == b"\n":
                return bytes(data)
            data.extend(chunk)
        raise Blocked("source admission response is oversized")

    def require(self, phase: str) -> None:
        if not re.fullmatch(r"(?:initial|final|cycle-[1-4])", phase):
            raise Blocked("source admission phase is invalid")
        nonce = os.urandom(16).hex()
        request = {
            "schema": SOURCE_ADMISSION_SCHEMA,
            "phase": phase,
            "source_sha": self._validated_source,
            "nonce": nonce,
        }
        self._channel.sendall(
            json.dumps(
                request, sort_keys=True, separators=(",", ":")).encode("ascii") +
            b"\n")
        try:
            response = json.loads(
                self._read_line().decode("ascii"),
                object_pairs_hook=_unique_json_object)
        except (UnicodeError, ValueError, TypeError) as exc:
            raise Blocked("source admission response is malformed") from exc
        required = {"schema", "status", "phase", "source_sha", "nonce"}
        if (not isinstance(response, dict) or set(response) != required or
                response.get("schema") != SOURCE_ADMISSION_SCHEMA or
                response.get("phase") != phase or
                response.get("source_sha") != self._validated_source or
                response.get("nonce") != nonce):
            raise Blocked("source admission response identity mismatch")
        if response.get("status") != "PASS":
            raise Blocked(
                f"unprivileged source admission refused at {phase}")


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


class PersistentEvidence:
    """Crash-persistent qualification disposition under the validated recovery base."""

    def __init__(self, directory: Path, attempt_id: str, initial: dict,
                 expected_uid: int | None = None):
        if not re.fullmatch(r"[0-9a-f]{32}", attempt_id):
            raise Blocked("persistent evidence attempt ID is malformed")
        self.expected_uid = os.geteuid() if expected_uid is None else expected_uid
        self.directory = directory
        self.path = directory / f"primary-real-swap-{attempt_id}.json"
        try:
            directory_info = directory.lstat()
        except OSError as exc:
            raise Blocked(f"persistent evidence directory is unavailable: {exc}") from exc
        if not stat.S_ISDIR(directory_info.st_mode) or \
                directory_info.st_uid != self.expected_uid or \
                stat.S_IMODE(directory_info.st_mode) != 0o700:
            raise Blocked("persistent evidence directory ownership/mode is unsafe")
        try:
            self.path.lstat()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise Blocked(f"cannot inspect persistent evidence path: {exc}") from exc
        else:
            raise Blocked("persistent evidence attempt path already exists")
        self.record = {
            "schema": "swapz-primary-real-swap-evidence-v1",
            "attempt_id": attempt_id,
            "status": "FAIL",
            "reason": "qualification_interrupted_or_incomplete",
            "phase": "ADMITTED",
            "started_unix_ns": time.time_ns(),
            "updated_unix_ns": time.time_ns(),
            **initial,
        }
        self._write(first=True)

    def _validate_existing(self, error_type=QualificationFailure) -> None:
        try:
            info = self.path.lstat()
        except OSError as exc:
            raise error_type(f"persistent evidence file is unavailable: {exc}") from exc
        if not stat.S_ISREG(info.st_mode) or info.st_uid != self.expected_uid or \
                stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
            raise error_type("persistent evidence file ownership/mode changed")

    def _write(self, *, first: bool = False) -> None:
        error_type = Blocked if first else QualificationFailure
        if not first:
            self._validate_existing(error_type)
        payload = (json.dumps(self.record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        temporary = self.directory / f".{self.path.name}.{os.urandom(8).hex()}.tmp"
        file_descriptor = -1
        directory_descriptor = -1
        try:
            file_descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
            )
            info = os.fstat(file_descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != self.expected_uid or \
                    stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
                raise error_type("persistent evidence temporary file is unsafe")
            offset = 0
            while offset < len(payload):
                written = os.write(file_descriptor, payload[offset:])
                if written <= 0:
                    raise OSError(errno.EIO, "short persistent evidence write")
                offset += written
            os.fsync(file_descriptor)
            os.close(file_descriptor)
            file_descriptor = -1
            os.replace(temporary, self.path)
            directory_descriptor = os.open(
                self.directory,
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
            )
            os.fsync(directory_descriptor)
            self._validate_existing(error_type)
            if self.path.read_bytes() != payload:
                raise error_type("persistent evidence readback differs from written bytes")
        except (Blocked, QualificationFailure):
            raise
        except OSError as exc:
            raise error_type(f"cannot persist real-swap evidence: {exc}") from exc
        finally:
            if file_descriptor >= 0:
                os.close(file_descriptor)
            if directory_descriptor >= 0:
                os.close(directory_descriptor)
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

    def update(self, phase: str, **fields) -> None:
        self.record.update(fields)
        self.record["phase"] = phase
        self.record["updated_unix_ns"] = time.time_ns()
        self._write()

    def finish(self, status_value: str, reason: str | None = None, **fields) -> None:
        if status_value not in {"PASS", "FAIL", "BLOCKED"}:
            raise ValueError("terminal evidence status must be PASS, FAIL, or BLOCKED")
        self.record.update(fields)
        self.record["status"] = status_value
        self.record["reason"] = reason
        self.record["phase"] = "COMPLETE"
        self.record["updated_unix_ns"] = time.time_ns()
        self._write()


def _run(argv: list[str], *, check: bool = True, timeout: float = 30,
         input_text: str | None = None,
         extra_environment: dict[str, str] | None = None
         ) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "LC_ALL": "C", "LANG": "C"}
    if extra_environment:
        environment.update(extra_environment)
    try:
        result = subprocess.run(
            argv,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=environment,
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




def pin_real_swap_oracle(oracle_path: Path, private_directory: Path) -> tuple[Path, str]:
    """Pin the exact source-controlled byte oracle before admitted mutation."""
    try:
        canonical = REAL_SWAP_ORACLE.resolve(strict=True)
        supplied = oracle_path.resolve(strict=True)
    except OSError as exc:
        raise Blocked(f"cannot resolve real-swap oracle: {exc}") from exc
    if supplied != canonical:
        raise Blocked("real-swap oracle must be the exact source-controlled oracle")

    source_fd = -1
    try:
        named_before = canonical.stat()
        source_fd = os.open(canonical, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        opened = os.fstat(source_fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or \
                opened.st_dev != named_before.st_dev or opened.st_ino != named_before.st_ino:
            raise Blocked("real-swap oracle identity is unsafe")
        payload = bytearray()
        while True:
            chunk = os.read(source_fd, 1024 * 1024)
            if not chunk:
                break
            payload.extend(chunk)
        opened_after = os.fstat(source_fd)
        named_after = canonical.stat()
        if (opened_after.st_dev, opened_after.st_ino, opened_after.st_size,
                opened_after.st_mtime_ns, opened_after.st_ctime_ns) != (
                    opened.st_dev, opened.st_ino, opened.st_size,
                    opened.st_mtime_ns, opened.st_ctime_ns) or \
                named_after.st_dev != opened.st_dev or \
                named_after.st_ino != opened.st_ino:
            raise Blocked("real-swap oracle changed while being pinned")
        if len(payload) != opened.st_size:
            raise Blocked("real-swap oracle read was incomplete")
    except OSError as exc:
        raise Blocked(f"cannot pin real-swap oracle: {exc}") from exc
    finally:
        if source_fd >= 0:
            os.close(source_fd)

    pinned = private_directory / "primary-real-swap-oracle.py"
    output_fd = -1
    try:
        output_fd = os.open(
            pinned,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o500,
        )
        offset = 0
        while offset < len(payload):
            written = os.write(output_fd, payload[offset:])
            if written <= 0:
                raise OSError("short oracle snapshot write")
            offset += written
        os.fsync(output_fd)
        identity = os.fstat(output_fd)
        if not stat.S_ISREG(identity.st_mode) or identity.st_nlink != 1 or \
                stat.S_IMODE(identity.st_mode) != 0o500:
            raise Blocked("pinned real-swap oracle identity is unsafe")
    except OSError as exc:
        raise Blocked(f"cannot create pinned real-swap oracle: {exc}") from exc
    finally:
        if output_fd >= 0:
            os.close(output_fd)

    digest = hashlib.sha256(payload).hexdigest()
    if _sha256_file(pinned) != digest:
        raise Blocked("pinned real-swap oracle digest mismatch")
    return pinned, digest

def installed_artifact_paths(swapzctl: Path) -> dict[str, Path]:
    """Derive the exact package artifacts the primary manager will consume."""
    try:
        control = swapzctl.resolve(strict=True)
    except OSError as exc:
        raise Blocked(f"cannot resolve installed swapzctl: {exc}") from exc
    if control.name != "swapzctl" or control.parent.name != "sbin":
        raise Blocked("primary real-swap qualification requires installed <prefix>/sbin/swapzctl")
    prefix = control.parent.parent
    return {
        "formatter_sha256": control,
        "module_sha256": prefix / "libexec/swapz/dm-swapz.ko",
        "oracle_sha256": prefix / "libexec/swapz/device-roundtrip",
    }


def _physical_control_environment() -> dict[str, str]:
    """Environment accepted only by the private physical-qualification seam."""
    return {"SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION": "1"}


def _c_string_literal(value: str, label: str) -> str:
    if not value or any(ord(character) < 0x20 or ord(character) > 0x7e
                        for character in value):
        raise Blocked(f"{label} is not a printable ASCII C-string value")
    return json.dumps(value)


def build_physical_execution_control(validated_source: str,
                                     qualified_swapzctl: Path,
                                     private_directory: Path
                                     ) -> tuple[Path, str]:
    """Build a noninstalled exact-source coordinator bound to qualified bytes."""
    if not re.fullmatch(r"[0-9a-f]{40}", validated_source):
        raise Blocked("validated source SHA is malformed")
    try:
        qualified_control = qualified_swapzctl.resolve(strict=True)
    except OSError as exc:
        raise Blocked(f"cannot resolve qualified installed swapzctl: {exc}") from exc
    if not qualified_control.is_file():
        raise Blocked("qualified installed swapzctl is not a regular file")
    if qualified_control.name != "swapzctl" or qualified_control.parent.name != "sbin":
        raise Blocked("qualified control must use installed <prefix>/sbin/swapzctl layout")

    try:
        version = (ROOT / "src/kernel/VERSION").read_text(
            encoding="ascii").strip()
    except OSError as exc:
        raise Blocked(f"cannot read exact-source version: {exc}") from exc
    version_literal = _c_string_literal(version, "swapz version")
    control_literal = _c_string_literal(
        str(qualified_control), "qualified control path")
    source_literal = _c_string_literal(validated_source, "validated source SHA")

    private_directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    os.chmod(private_directory, 0o700)
    output = private_directory / "swapzctl"
    command = [
        "cc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
        f"-DSWAPZ_BUILD_SOURCE_SHA={source_literal}",
        "-DSWAPZ_BUILD_SOURCE_CLEAN=1",
        f"-DSWAPZ_VERSION={version_literal}",
        "-DSWAPZ_PRIMARY_PHYSICAL_QUALIFICATION_TEST=1",
        f"-DSWAPZ_PRIMARY_PHYSICAL_QUALIFIED_CONTROL={control_literal}",
        str(ROOT / "src/userspace/swapzctl.c"),
        str(ROOT / "src/userspace/swapz-primary.c"),
        "-o", str(output),
    ]
    result = _run(command, check=False, timeout=120)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().replace("\n", "; ")
        raise Blocked(
            "cannot build exact-source private physical coordinator: " + detail)
    try:
        os.chmod(output, 0o700)
        identity = output.stat()
    except OSError as exc:
        raise Blocked(f"cannot secure private physical coordinator: {exc}") from exc
    if not stat.S_ISREG(identity.st_mode) or identity.st_uid != os.geteuid() or \
            stat.S_IMODE(identity.st_mode) != 0o700:
        raise Blocked("private physical coordinator identity is unsafe")
    return output, _sha256_file(output)


def qualification_artifact_hashes(report_path: Path, validated_source: str) -> dict[str, str]:
    """Read qualified artifact digests directly from the supplied owner report."""
    try:
        report = _load_unique_json(
            report_path.read_text(encoding="utf-8"), "qualification report")
    except OSError as exc:
        raise Blocked(f"cannot read qualification report: {exc}") from exc
    if report.get("schema") != "swapz-test-results-v1" or \
            report.get("source_sha") != validated_source or \
            report.get("tested_commit_sha") != validated_source or \
            report.get("overall") != "PASS" or \
            report.get("qualification") != "RAM_BACKED_NULL_BLK_ONLY":
        raise Blocked("qualification report does not bind the validated source and PASS scope")
    artifacts = report.get("qualified_artifacts")
    if not isinstance(artifacts, dict) or artifacts.get("status") != "AVAILABLE":
        raise Blocked("qualification report has no available qualified artifacts")
    result: dict[str, str] = {}
    for key in ("formatter_sha256", "module_sha256", "oracle_sha256"):
        digest = artifacts.get(key)
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise Blocked(f"qualification report {key} is unavailable or malformed")
        result[key] = digest
    return result


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
    normalized = partuuid.lower()
    if (
            not 8 <= len(normalized) <= 64 or
            not re.fullmatch(r"[0-9a-f]+(?:-[0-9a-f]+)*", normalized) or
            sum(ch != "-" for ch in normalized) < 8):
        raise Blocked("primary target selector PARTUUID is malformed")
    return normalized


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


def require_no_conflicting_raw_swap_aliases(
        rows: list[SwapRow], target_device: tuple[int, int],
        parent_device: tuple[int, int]) -> None:
    protected_devices = {
        target_device: "raw backing partition",
        parent_device: "physical parent disk",
    }
    for row in rows:
        # A path that cannot be stat'ed must never hide an active raw block
        # swap alias. Ordinary swap files have type "file", not "partition".
        if row.type == "partition" and row.device is None:
            raise Blocked(
                f"cannot resolve active block-swap alias identity: {row.path}")
        label = protected_devices.get(row.device)
        if label is not None:
            raise Blocked(
                f"{label} is already active swap through alias {row.path}")


def require_expected_swap_priority(expected: SwapRow, unrelated: list[SwapRow]) -> None:
    for row in unrelated:
        if row.priority >= expected.priority:
            raise Blocked(
                "expected primary mapper is not the unique highest-priority swap area; "
                "real-swap traffic cannot be attributed without touching unrelated swap")


def maximum_primary_geometry(device_bytes: int) -> dict[str, int]:
    """Derive the allocation-free production capacity from backing bytes."""
    if not isinstance(device_bytes, int) or isinstance(device_bytes, bool) or \
            device_bytes < PAGE_BYTES or device_bytes % PAGE_BYTES:
        raise Blocked("primary backing geometry is invalid")
    blocks = device_bytes // PAGE_BYTES
    physical_blocks = ((blocks - 1) // SEGMENT_BLOCKS) * SEGMENT_BLOCKS
    if physical_blocks == 0 or physical_blocks > UINT32_MAX:
        raise Blocked("primary physical block geometry is outside authority limits")

    def fits(logical_pages: int) -> bool:
        if logical_pages <= 0 or logical_pages > UINT32_MAX:
            return False
        reserve_blocks = (logical_pages + 7) // 8
        reserve_blocks = max(reserve_blocks, MIN_RESERVE_BLOCKS)
        if reserve_blocks >= physical_blocks:
            return False
        foreground_blocks = (
            (physical_blocks - reserve_blocks) // SEGMENT_BLOCKS
        ) * SEGMENT_BLOCKS
        return logical_pages + FOREGROUND_HEADROOM_BLOCKS <= foreground_blocks

    low = 0
    high = physical_blocks
    while low < high:
        candidate = low + (high - low + 1) // 2
        if fits(candidate):
            low = candidate
        else:
            high = candidate - 1
    if low == 0:
        raise Blocked("primary backing has no admissible logical capacity")

    reserve_blocks = max((low + 7) // 8, MIN_RESERVE_BLOCKS)
    logical_bytes = low * PAGE_BYTES
    return {
        "physical_blocks": physical_blocks,
        "logical_pages": low,
        "logical_sectors": low * (PAGE_BYTES // SECTOR_BYTES),
        "logical_bytes": logical_bytes,
        "linux_swap_kib": logical_bytes // 1024 - PAGE_BYTES // 1024,
        "gc_reserve_blocks": reserve_blocks,
    }


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
    for key in ("logical_write", "logical_read", "physical_write", "physical_read", "failed", "error"):
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


def require_plan_storage_separation(plan: dict) -> None:
    for key in (
        "root_same_physical_disk_as_target",
        "recovery_same_physical_disk_as_target",
    ):
        if plan.get(key) is not False:
            raise Blocked(f"primary plan does not prove {key}=false")


def require_clean_mapper_ownership(plan: dict) -> None:
    if plan.get("module_mapper_inventory_read") is not True or \
            plan.get("swapz_mapper_absent") is not True or \
            plan.get("dm_swapz_module_loaded") is not False:
        raise Blocked("unexpected swapz mapper/module ownership exists before qualification")


def require_sole_partition_topology(target_row: dict, parent_row: dict,
                                    target_major_minor: str) -> None:
    parent_path = parent_row.get("path")
    if not isinstance(parent_path, str) or not parent_path.startswith("/dev/"):
        raise Blocked("physical parent path is unavailable")
    if target_row.get("pkname") != Path(parent_path).name:
        raise Blocked("selected partition does not name the admitted physical parent")
    children = parent_row.get("children")
    if not isinstance(children, list):
        raise Blocked("physical parent partition topology is unavailable")
    partitions = [child for child in children if child.get("type") == "part"]
    if len(partitions) != 1 or partitions[0].get("maj:min") != target_major_minor:
        raise Blocked("authorized parent must contain exactly the selected partition")


def _read_readiness_snapshot() -> dict:
    try:
        return _load_unique_json(
            AUTHORIZATION_SNAPSHOT.read_text(encoding="utf-8"),
            "production readiness snapshot")
    except OSError as exc:
        raise Blocked(f"cannot read committed production readiness snapshot: {exc}") from exc


def validate_acceptance_manifest(
        manifest: dict, *, cycles: int, workload_mib: int, resident_mib: int,
        swap_limit_mib: int, timeout_seconds: int) -> dict:
    if set(manifest) != {
            "schema", "status", "primary_real_swap", "physical_qualification"} or \
            manifest.get("schema") != "swapz-production-acceptance-v1" or \
            manifest.get("status") != "FROZEN":
        raise Blocked(
            "quantitative production acceptance manifest is not canonical and frozen")
    real_swap = manifest.get("primary_real_swap")
    expected = {
        "page_bytes": PAGE_BYTES,
        "cycles": cycles,
        "workload_mib": workload_mib,
        "resident_mib": resident_mib,
        "swap_limit_mib": swap_limit_mib,
        "minimum_mem_available_mib": MIN_AVAILABLE_MIB,
        "minimum_swap_traffic_mib": MIN_TRAFFIC_MIB,
        "verify_headroom_mib": VERIFY_HEADROOM_MIB,
        "timeout_seconds": timeout_seconds,
        "zswap_disabled": True,
        "oom_events_max": 0,
        "oom_kill_events_max": 0,
        "byte_mismatches_max": 0,
        "fresh_run_id_each_cycle": True,
        "fresh_linux_swap_uuid_each_cycle": True,
        "normal_teardown_only": True,
    }
    if not isinstance(real_swap, dict) or set(real_swap) != set(expected):
        raise Blocked(
            "frozen primary real-swap acceptance fields are not canonical")
    for key, expected_value in expected.items():
        observed = real_swap.get(key)
        if type(observed) is not type(expected_value) or observed != expected_value:
            raise Blocked(
                f"requested primary real-swap {key} differs from frozen acceptance")
    physical = manifest.get("physical_qualification")
    if not isinstance(physical, dict) or \
            physical.get("schema") != "swapz-performance-qualification-v1" or \
            physical.get("prospective") is not True:
        raise Blocked("frozen physical qualification contract is malformed")
    return manifest


def verify_acceptance_manifest(
        *, cycles: int, workload_mib: int, resident_mib: int,
        swap_limit_mib: int, timeout_seconds: int) -> dict:
    try:
        manifest = _load_unique_json(
            ACCEPTANCE_MANIFEST.read_text(encoding="utf-8"),
            "production acceptance manifest")
    except OSError as exc:
        raise Blocked(
            f"cannot read production acceptance manifest: {exc}") from exc
    return validate_acceptance_manifest(
        manifest, cycles=cycles, workload_mib=workload_mib,
        resident_mib=resident_mib, swap_limit_mib=swap_limit_mib,
        timeout_seconds=timeout_seconds)


def acceptance_manifest_sha256() -> str:
    """Hash the exact frozen policy bytes consumed by physical qualification."""
    try:
        payload = ACCEPTANCE_MANIFEST.read_bytes()
    except OSError as exc:
        raise Blocked(
            f"cannot hash production acceptance manifest: {exc}") from exc
    return hashlib.sha256(payload).hexdigest()


def verify_authorized_target(
        plan: dict, selector_partuuid: str,
) -> tuple[Path, tuple[int, int], tuple[int, int]]:
    required_true = (
        "target_config_read", "target_device_preflight", "target_not_mounted",
        "target_device_chain_checked", "recovery_directory_safe",
        "recovery_filesystem_supported", "recovery_source_chain_checked",
        "recovery_active_marker_clear", "root_mount_source_chain_checked",
    )
    for key in required_true:
        if plan.get(key) is not True:
            raise Blocked(f"primary plan safety gate {key} is not true")
    require_plan_storage_separation(plan)
    if str(plan.get("target_partuuid", "")).lower() != selector_partuuid:
        raise Blocked("primary plan target differs from protected selector")
    try:
        major = int(plan["target_device_major"])
        minor = int(plan["target_device_minor"])
        size_bytes = int(plan["target_device_bytes"])
        parent_major = int(plan["target_physical_parent_major"])
        parent_minor = int(plan["target_physical_parent_minor"])
        plan_logical_pages = int(plan["logical_pages"])
        plan_logical_bytes = int(plan["logical_bytes"])
        plan_linux_swap_kib = int(plan["linux_swap_kib"])
        plan_reserve_blocks = int(plan["gc_reserve_blocks"])
    except (KeyError, TypeError, ValueError) as exc:
        raise Blocked("primary plan target geometry is unavailable") from exc

    expected_geometry = maximum_primary_geometry(size_bytes)
    plan_geometry = {
        "logical_pages": plan_logical_pages,
        "logical_bytes": plan_logical_bytes,
        "linux_swap_kib": plan_linux_swap_kib,
        "gc_reserve_blocks": plan_reserve_blocks,
    }
    for key, observed in plan_geometry.items():
        if observed != expected_geometry[key]:
            raise Blocked(
                f"primary plan {key} differs from independently derived capacity")

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
    require_sole_partition_topology(target_row, parent_row, f"{major}:{minor}")

    try:
        snapshot = _read_readiness_snapshot()
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
    return target, (major, minor), (parent_major, parent_minor)


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
    result = _run(
        [str(swapzctl), "primary", "plan"], check=False, timeout=30,
        extra_environment=_physical_control_environment())
    if not result.stdout.strip():
        raise Blocked("primary plan produced no JSON")
    plan = _load_unique_json(result.stdout.strip(), "primary plan")
    return plan


def verify_provenance(plan: dict, validated_source: str, report_path: Path,
                      swapzctl: Path) -> dict[str, str]:
    # The module must be absent before primary start, so live module sysfs
    # provenance is intentionally unavailable here. Bind the package-held
    # module bytes to the owner report now; verify live module provenance only
    # after the coordinator has loaded that exact artifact.
    required_true = (
        "control_build_source_clean",
        "qualification_report_valid", "qualification_source_matches_build",
        "live_artifact_hashes_read", "live_artifacts_match_qualification",
    )
    for key in required_true:
        if plan.get(key) is not True:
            raise Blocked(f"primary provenance gate {key} is not true")
    require_clean_mapper_ownership(plan)
    if plan.get("control_build_source_sha") != validated_source:
        raise Blocked("primary control binary source SHA differs from validated source")
    report_digest = _sha256_file(report_path)
    if plan.get("qualification_report_sha256") != report_digest:
        raise Blocked("imported qualification report digest differs from supplied report")

    report_hashes = qualification_artifact_hashes(report_path, validated_source)
    installed_paths = installed_artifact_paths(swapzctl)
    plan_keys = {
        "formatter_sha256": ("qualified_swapzctl_sha256", "live_swapzctl_sha256"),
        "module_sha256": ("qualified_module_sha256", "live_module_sha256"),
        "oracle_sha256": ("qualified_oracle_sha256", "live_oracle_sha256"),
    }
    observed: dict[str, str] = {}
    for artifact_key, path in installed_paths.items():
        qualified_key, live_key = plan_keys[artifact_key]
        expected = report_hashes[artifact_key]
        if plan.get(qualified_key) != expected or plan.get(live_key) != expected:
            raise Blocked(f"primary plan {artifact_key} differs from supplied qualification report")
        digest = _sha256_file(path)
        if digest != expected:
            raise Blocked(f"installed {artifact_key} bytes differ from qualification")
        observed[artifact_key] = digest

    if plan.get("privileged_execution_enabled") is not True:
        raise Blocked("primary privileged lifecycle execution gate is still disabled")
    return observed


def validate_loaded_module_provenance(source_sha: str, source_clean: str,
                                      physical_backing: str,
                                      validated_source: str) -> None:
    if source_sha != validated_source or source_clean != "1" or \
            physical_backing not in {"1", "Y"}:
        raise QualificationFailure(
            "loaded dm_swapz provenance/physical-backing parameter is not exact")


def verify_loaded_module_provenance(validated_source: str) -> dict[str, str]:
    parameter_base = Path("/sys/module/dm_swapz/parameters")
    try:
        source_sha = (parameter_base / "build_source_sha").read_text(
            encoding="ascii").strip()
        source_clean = (parameter_base / "build_source_clean").read_text(
            encoding="ascii").strip()
        physical_backing = (parameter_base / "allow_physical_backing").read_text(
            encoding="ascii").strip()
    except OSError as exc:
        raise QualificationFailure(
            f"cannot independently read loaded dm_swapz provenance: {exc}") from exc
    validate_loaded_module_provenance(
        source_sha, source_clean, physical_backing, validated_source)
    return {
        "build_source_sha": source_sha,
        "build_source_clean": source_clean,
        "allow_physical_backing": physical_backing,
    }


def _ensure_commands(names: tuple[str, ...]) -> None:
    for name in names:
        if shutil.which(name) is None:
            raise Blocked(f"missing required command {name}")


def _validate_precycle_state(
        partuuid: str, target_device: tuple[int, int],
        parent_device: tuple[int, int], baseline: list[SwapRow]) -> None:
    state = read_state()
    if state is not None and state.get("stage") != "COMPLETE":
        raise Blocked(f"unresolved primary state {state.get('stage')}")
    marker = RECOVERY_BASE / f"partition-{partuuid}.active"
    if marker.exists():
        raise Blocked("selected partition already has an active ownership marker")
    if _dm_identity() is not None:
        raise Blocked("primary mapper already exists before cycle")
    require_no_conflicting_raw_swap_aliases(
        baseline, target_device, parent_device)
    if Path("/sys/module/dm_swapz").exists():
        raise Blocked("dm_swapz is already loaded before primary cycle")


def _read_primary_output(result: subprocess.CompletedProcess[str], prefix: str) -> str:
    for line in result.stdout.splitlines():
        if line.startswith(prefix):
            return line
    raise QualificationFailure(f"primary command omitted expected marker {prefix}")


def _primary(swapzctl: Path, action: str, timeout: float, *, admitted: bool = False) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ, "LC_ALL": "C", "LANG": "C",
        **_physical_control_environment(),
    }
    try:
        return subprocess.run(
            [str(swapzctl), "primary", action],
            text=True, capture_output=True, timeout=timeout, check=False,
            env=environment,
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
    if status["failed"] != 0 or status["error"] != 0:
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
    if not (64 <= resident_mib < workload_mib <= 512) or \
            workload_mib < CONCURRENT_ORACLE_PROCESSES * 64:
        raise Blocked(
            "workload must be 128..512 MiB with resident limit below workload "
            "for two concurrent bounded oracles")
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
        try:
            process.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            # The oracle may exit between poll() and signal delivery.
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
    # Two independent oracles share this cgroup: wait only for this child.
    # The final _remove_cgroup() independently requires every worker gone.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            if str(process.pid) not in (cgroup / "cgroup.procs").read_text(
                    encoding="ascii").split():
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
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise QualificationFailure(f"real-swap oracle timed out waiting for {prefix}")
        readable, _, _ = select.select([fd], [], [], min(0.1, remaining))
        if not readable:
            if process.poll() is not None:
                stderr = process.stderr.read().strip() if process.stderr else ""
                raise QualificationFailure(
                    f"real-swap oracle exited before {prefix}: rc={process.returncode} {stderr}")
            continue
        line = process.stdout.readline()
        if not line:
            if process.poll() is not None:
                stderr = process.stderr.read().strip() if process.stderr else ""
                raise QualificationFailure(
                    f"real-swap oracle exited before {prefix}: rc={process.returncode} {stderr}")
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
                               min_swap_bytes: int, expected_verified_pages: int,
                               oom_delta: int, oom_kill_delta: int,
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
    if mapper_used_delta_kib * 1024 < min_swap_bytes:
        raise QualificationFailure("exact mapper /proc/swaps usage stayed below required real-swap floor")
    logical_write_delta = fill_status_after["logical_write"] - fill_status_before["logical_write"]
    physical_write_delta = fill_status_after["physical_write"] - fill_status_before["physical_write"]
    if logical_write_delta < min_swap_bytes or physical_write_delta <= 0:
        raise QualificationFailure("swapz target counters stay below required swap-out WRITE activity")
    lower_write_sector_delta = lower_after_fill.write_sectors - lower_before.write_sectors
    if lower_write_sector_delta <= 0:
        raise QualificationFailure("backing partition counters show no lower WRITE activity")
    if lower_write_sector_delta * SECTOR_BYTES < physical_write_delta:
        raise QualificationFailure(
            "backing partition WRITE counters do not cover swapz target physical WRITE bytes")
    if vm_after_fill["pswpout"] <= vm_before["pswpout"]:
        raise QualificationFailure("kernel vmstat shows no swap-out during admitted workload")
    logical_read_delta = verify_status_after["logical_read"] - verify_status_before["logical_read"]
    physical_read_delta = verify_status_after["physical_read"] - verify_status_before["physical_read"]
    if logical_read_delta < min_swap_bytes or physical_read_delta <= 0:
        raise QualificationFailure("swapz target counters stay below required swap-in READ activity")
    lower_read_sector_delta = lower_after_verify.read_sectors - lower_before_verify.read_sectors
    if lower_read_sector_delta <= 0:
        raise QualificationFailure("backing partition counters show no lower READ activity")
    if lower_read_sector_delta * SECTOR_BYTES < physical_read_delta:
        raise QualificationFailure(
            "backing partition READ counters do not cover swapz target physical READ bytes")
    if vm_after_verify["pswpin"] <= vm_before_verify["pswpin"]:
        raise QualificationFailure("kernel vmstat shows no swap-in during byte verification")
    if expected_verified_pages <= 0 or \
            oracle.get("verified_pages") != expected_verified_pages or \
            oracle.get("verified_bytes") != expected_verified_pages * PAGE_BYTES or \
            oracle.get("mismatches") != 0 or \
            oracle.get("digest") != oracle.get("expected_digest"):
        raise QualificationFailure("real-swap byte oracle reported corruption or incomplete verification")
    for status in (fill_status_after, verify_status_after):
        if status["failed"] != 0 or status["error"] != 0:
            raise QualificationFailure("swapz target entered failed state during real-swap workload")


def split_concurrent_workload_mib(workload_mib: int) -> tuple[int, int]:
    first = workload_mib // CONCURRENT_ORACLE_PROCESSES
    second = workload_mib - first
    if first < 64 or second < 64:
        raise Blocked("concurrent real-swap workers each require at least 64 MiB")
    return first, second


def require_oracle_worker_geometry(
        records: list[dict], worker_memory_mib: tuple[int, int],
        page_field: str, byte_field: str, phase: str) -> None:
    if len(records) != len(worker_memory_mib):
        raise QualificationFailure(f"concurrent oracle {phase} record count is incomplete")
    for worker_index, (record, memory_mib) in enumerate(zip(records, worker_memory_mib)):
        expected_bytes = memory_mib * MIB
        expected_pages = expected_bytes // PAGE_BYTES
        if record.get(page_field) != expected_pages or record.get(byte_field) != expected_bytes:
            raise QualificationFailure(
                f"concurrent oracle worker {worker_index} {phase} page/byte count is incomplete")


def aggregate_oracle_verification(records: list[dict]) -> dict:
    if len(records) != CONCURRENT_ORACLE_PROCESSES:
        raise QualificationFailure("concurrent oracle verification record count is incomplete")
    observed_digest = hashlib.sha256()
    expected_digest = hashlib.sha256()
    verified_pages = 0
    verified_bytes = 0
    mismatches = 0
    for record in records:
        try:
            pages = int(record["verified_pages"])
            byte_count = int(record["verified_bytes"])
            mismatch_count = int(record["mismatches"])
            observed_bytes = bytes.fromhex(str(record["digest"]))
            expected_bytes = bytes.fromhex(str(record["expected_digest"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise QualificationFailure("concurrent oracle verification record is malformed") from exc
        if pages <= 0 or byte_count != pages * PAGE_BYTES or mismatch_count < 0 or \
                len(observed_bytes) != 32 or len(expected_bytes) != 32:
            raise QualificationFailure("concurrent oracle verification geometry/digest is invalid")
        verified_pages += pages
        verified_bytes += byte_count
        mismatches += mismatch_count
        observed_digest.update(observed_bytes)
        expected_digest.update(expected_bytes)
    return {
        "verified_pages": verified_pages,
        "verified_bytes": verified_bytes,
        "mismatches": mismatches,
        "digest": observed_digest.hexdigest(),
        "expected_digest": expected_digest.hexdigest(),
    }


def evaluate_reuse_rounds(rounds: list[dict]) -> dict:
    if len(rounds) < REUSE_ROUNDS:
        raise QualificationFailure("real-swap qualification did not complete repeated slot-reuse rounds")
    baseline_used_kib = int(rounds[0].get("mapper_used_start_kib", -1))
    if baseline_used_kib != 0:
        raise QualificationFailure("slot-reuse proof did not start from a fresh zero-use mapper")
    for result in rounds:
        if int(result.get("concurrent_workers", 0)) < CONCURRENT_ORACLE_PROCESSES:
            raise QualificationFailure("real-swap round lacked concurrent test-process activity")
        if int(result.get("mapper_used_start_kib", -1)) != baseline_used_kib or \
                int(result.get("mapper_used_delta_kib", 0)) <= 0:
            raise QualificationFailure("real-swap round did not allocate fresh swap slots")
        if int(result.get("release_swap_current_bytes", -1)) != 0 or \
                int(result.get("mapper_used_released_kib", -1)) != baseline_used_kib:
            raise QualificationFailure("swap slots were not fully released before reuse")
    return {
        "rounds": len(rounds),
        "concurrent_workers": CONCURRENT_ORACLE_PROCESSES,
        "baseline_mapper_used_kib": baseline_used_kib,
        "slot_reuse_proven": True,
    }


def _wait_for_round_release(cgroup: Path, mapper_device: tuple[int, int],
                            expected_used_kib: int, deadline: float,
                            guard: Callable[[], None]) -> dict:
    while time.monotonic() < deadline:
        guard()
        swap_current = _read_uint(cgroup / "memory.swap.current")
        row = _row_for_device(read_swap_rows(), mapper_device)
        if row is None:
            raise QualificationFailure("expected mapper vanished while releasing swap slots")
        if row.used_kib < expected_used_kib:
            raise QualificationFailure("mapper swap usage fell below the round baseline")
        if swap_current == 0 and row.used_kib == expected_used_kib:
            return {
                "release_swap_current_bytes": 0,
                "mapper_used_released_kib": row.used_kib,
            }
        time.sleep(0.05)
    raise QualificationFailure("swap slots did not return to baseline within the bounded release timeout")


def _run_workload(manifest: dict, active: dict, oracle_path: Path,
                  workload_mib: int, resident_mib: int, swap_limit_mib: int,
                  timeout_seconds: int) -> dict:
    worker_memory_mib = split_concurrent_workload_mib(workload_mib)
    token = os.urandom(8).hex()
    cgroup = _cgroup_create(token, resident_mib, swap_limit_mib, admitted=True)
    events_before = _memory_events(cgroup / "memory.events")
    psi_before = _psi_total(cgroup / "memory.pressure")
    rounds: list[dict] = []
    active_processes: list[subprocess.Popen[str]] = []

    def guard() -> None:
        events = _memory_events(cgroup / "memory.events")
        if events.get("oom", 0) > events_before.get("oom", 0) or \
                events.get("oom_kill", 0) > events_before.get("oom_kill", 0):
            raise QualificationFailure("cgroup OOM occurred during admitted real-swap workload")
        if _read_uint(cgroup / "memory.swap.current") > swap_limit_mib * MIB:
            raise QualificationFailure("cgroup exceeded configured swap-usage bound")
        if _mem_available_mib() < 256:
            raise QualificationFailure("host MemAvailable crossed 256 MiB early-stop threshold")

    try:
        for round_index in range(1, REUSE_ROUNDS + 1):
            _write_control(cgroup / "memory.max", str(resident_mib * MIB), admitted=True)
            swaps_before = read_swap_rows()
            expected_before = _row_for_device(swaps_before, active["mapper_device"])
            if expected_before is None:
                raise QualificationFailure("expected mapper vanished before real-swap round")
            if expected_before.used_kib != 0:
                raise QualificationFailure(
                    "exact mapper has nonzero use before dedicated round; unrelated pages may depend on it")

            round_processes: list[subprocess.Popen[str]] = []
            worker_seeds: list[str] = []
            round_result: dict | None = None
            try:
                for worker_index, memory_mib in enumerate(worker_memory_mib):
                    seed = hashlib.blake2s(
                        f"{manifest['run_id']}:{round_index}:{worker_index}".encode("ascii"),
                        digest_size=16,
                    ).hexdigest()
                    worker_seeds.append(seed)
                    process = subprocess.Popen(
                        [sys.executable, "-B", str(oracle_path), "--seed", seed,
                         "--memory-mib", str(memory_mib)],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, bufsize=1,
                        env={**os.environ, "LC_ALL": "C", "LANG": "C"},
                    )
                    try:
                        (cgroup / "cgroup.procs").write_text(f"{process.pid}\n", encoding="ascii")
                    except OSError as exc:
                        process.terminate()
                        process.wait(timeout=5)
                        raise QualificationFailure(
                            f"cannot move admitted oracle into dedicated cgroup: {exc}") from exc
                    round_processes.append(process)
                    active_processes.append(process)

                deadline = time.monotonic() + timeout_seconds
                waiting = [
                    _oracle_event(process, "ORACLE_WAITING=", deadline, guard)
                    for process in round_processes
                ]
                waiting_pids = [int(record.get("pid", -1)) for record in waiting]
                if len(set(waiting_pids)) != CONCURRENT_ORACLE_PROCESSES or \
                        waiting_pids != [process.pid for process in round_processes] or \
                        any(record.get("seed") != seed
                            for record, seed in zip(waiting, worker_seeds)):
                    raise QualificationFailure("concurrent oracle readiness PID/seed identities differ")
                expected_pages = workload_mib * MIB // PAGE_BYTES
                require_oracle_worker_geometry(
                    waiting, worker_memory_mib, "pages", "bytes", "readiness")

                fill_status_before = read_status()
                lower_before = read_block_stats(
                    (manifest["device_major_int"], manifest["device_minor_int"]))
                vm_before = read_vmstat()

                for process in round_processes:
                    if process.stdin is None:
                        raise QualificationFailure("oracle command pipe is unavailable")
                    process.stdin.write("FILL\n")
                    process.stdin.flush()
                filled_records = [
                    _oracle_event(process, "ORACLE_FILLED=", deadline, guard)
                    for process in round_processes
                ]
                require_oracle_worker_geometry(
                    filled_records, worker_memory_mib, "pages", "bytes", "fill")
                if any(not re.fullmatch(r"[0-9a-f]{64}", str(record.get("digest", "")))
                       for record in filled_records):
                    raise QualificationFailure("concurrent oracle fill digests are malformed")

                swap_current = _read_uint(cgroup / "memory.swap.current")
                swap_peak = _read_uint(cgroup / "memory.swap.peak")
                fill_status_after = read_status()
                lower_after_fill = read_block_stats(
                    (manifest["device_major_int"], manifest["device_minor_int"]))
                vm_after_fill = read_vmstat()
                swaps_after_fill = read_swap_rows()
                expected_after_fill = _row_for_device(
                    swaps_after_fill, active["mapper_device"])
                if expected_after_fill is None:
                    raise QualificationFailure("expected mapper vanished during swap-out")
                mapper_used_delta = expected_after_fill.used_kib - expected_before.used_kib
                min_swap_bytes = MIN_TRAFFIC_MIB * MIB
                if swap_current < min_swap_bytes or mapper_used_delta <= 0:
                    raise QualificationFailure(
                        "concurrent fill completed without independently proven swapz swap-out")

                mapper_used_bytes = mapper_used_delta * 1024
                if mapper_used_bytes != swap_current:
                    raise Blocked(
                        "exact mapper usage and dedicated-cgroup swap charge differ; "
                        "traffic attribution or mapper ownership is ambiguous")

                verify_status_before = read_status()
                lower_before_verify = read_block_stats(
                    (manifest["device_major_int"], manifest["device_minor_int"]))
                vm_before_verify = read_vmstat()
                _write_control(
                    cgroup / "memory.max",
                    str((workload_mib + VERIFY_HEADROOM_MIB) * MIB),
                    admitted=True,
                )
                for process in round_processes:
                    if process.stdin is None:
                        raise QualificationFailure("oracle command pipe is unavailable")
                    process.stdin.write("VERIFY\n")
                    process.stdin.flush()
                verified_records = [
                    _oracle_event(process, "ORACLE_VERIFIED=", deadline, guard)
                    for process in round_processes
                ]
                require_oracle_worker_geometry(
                    verified_records, worker_memory_mib,
                    "verified_pages", "verified_bytes", "verification")
                if any(filled.get("digest") != verified.get("expected_digest")
                       for filled, verified in zip(filled_records, verified_records)):
                    raise QualificationFailure(
                        "oracle fill digest differs from expected verification digest")
                for process in round_processes:
                    try:
                        process.wait(timeout=max(1, int(deadline - time.monotonic())))
                    except subprocess.TimeoutExpired as exc:
                        raise QualificationFailure(
                            "concurrent oracle did not exit after byte verification") from exc
                    if process.returncode != 0:
                        stderr = process.stderr.read().strip() if process.stderr else ""
                        raise QualificationFailure(
                            f"oracle verification failed rc={process.returncode}: {stderr}")

                verified = aggregate_oracle_verification(verified_records)
                verify_status_after = read_status()
                lower_after_verify = read_block_stats(
                    (manifest["device_major_int"], manifest["device_minor_int"]))
                vm_after_verify = read_vmstat()
                events_after = _memory_events(cgroup / "memory.events")
                oom_delta = events_after.get("oom", 0) - events_before.get("oom", 0)
                oom_kill_delta = events_after.get("oom_kill", 0) - events_before.get("oom_kill", 0)
                evaluate_workload_evidence(
                    cgroup_swap_bytes=swap_current,
                    cgroup_swap_peak=swap_peak,
                    min_swap_bytes=min_swap_bytes,
                    expected_verified_pages=expected_pages,
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
                round_result = {
                    "round": round_index,
                    "concurrent_workers": len(round_processes),
                    "worker_pids": waiting_pids,
                    "worker_memory_mib": list(worker_memory_mib),
                    "oracle_filled": filled_records,
                    "oracle_verified": verified_records,
                    "aggregate_verified": verified,
                    "cgroup_swap_current_bytes_after_fill": swap_current,
                    "cgroup_swap_peak_bytes": swap_peak,
                    "mapper_used_start_kib": expected_before.used_kib,
                    "mapper_used_delta_kib": mapper_used_delta,
                    "swapz_logical_write_delta":
                        fill_status_after["logical_write"] - fill_status_before["logical_write"],
                    "swapz_physical_write_delta":
                        fill_status_after["physical_write"] - fill_status_before["physical_write"],
                    "swapz_logical_read_delta":
                        verify_status_after["logical_read"] - verify_status_before["logical_read"],
                    "swapz_physical_read_delta":
                        verify_status_after["physical_read"] - verify_status_before["physical_read"],
                    "lower_write_sector_delta":
                        lower_after_fill.write_sectors - lower_before.write_sectors,
                    "lower_write_bytes_delta":
                        (lower_after_fill.write_sectors - lower_before.write_sectors) * SECTOR_BYTES,
                    "lower_read_sector_delta":
                        lower_after_verify.read_sectors - lower_before_verify.read_sectors,
                    "lower_read_bytes_delta":
                        (lower_after_verify.read_sectors - lower_before_verify.read_sectors) * SECTOR_BYTES,
                    "pswpout_delta": vm_after_fill["pswpout"] - vm_before["pswpout"],
                    "pswpin_delta": vm_after_verify["pswpin"] - vm_before_verify["pswpin"],
                    "oom_delta": oom_delta,
                    "oom_kill_delta": oom_kill_delta,
                }
            finally:
                for process in round_processes:
                    _terminate_child(process, cgroup)
                    if process in active_processes:
                        active_processes.remove(process)

            if round_result is None:
                raise QualificationFailure("real-swap round ended without evidence")
            release = _wait_for_round_release(
                cgroup, active["mapper_device"], expected_before.used_kib,
                time.monotonic() + min(timeout_seconds, 30), guard)
            round_result.update(release)
            rounds.append(round_result)

        reuse = evaluate_reuse_rounds(rounds)
        events_after = _memory_events(cgroup / "memory.events")
        psi_after = _psi_total(cgroup / "memory.pressure")
        return {
            "concurrent_workers": CONCURRENT_ORACLE_PROCESSES,
            "reuse_rounds": len(rounds),
            "slot_reuse_proven": reuse["slot_reuse_proven"],
            "rounds": rounds,
            "cgroup_swap_peak_bytes": max(
                int(result["cgroup_swap_peak_bytes"]) for result in rounds),
            "cgroup_memory_pressure_some_usec": psi_after - psi_before,
            "mapper_used_delta_kib": sum(
                int(result["mapper_used_delta_kib"]) for result in rounds),
            "swapz_logical_write_delta": sum(
                int(result["swapz_logical_write_delta"]) for result in rounds),
            "swapz_physical_write_delta": sum(
                int(result["swapz_physical_write_delta"]) for result in rounds),
            "swapz_logical_read_delta": sum(
                int(result["swapz_logical_read_delta"]) for result in rounds),
            "swapz_physical_read_delta": sum(
                int(result["swapz_physical_read_delta"]) for result in rounds),
            "lower_write_sector_delta": sum(
                int(result["lower_write_sector_delta"]) for result in rounds),
            "lower_write_bytes_delta": sum(
                int(result["lower_write_bytes_delta"]) for result in rounds),
            "lower_read_sector_delta": sum(
                int(result["lower_read_sector_delta"]) for result in rounds),
            "lower_read_bytes_delta": sum(
                int(result["lower_read_bytes_delta"]) for result in rounds),
            "pswpout_delta": sum(int(result["pswpout_delta"]) for result in rounds),
            "pswpin_delta": sum(int(result["pswpin_delta"]) for result in rounds),
            "oom_delta": events_after.get("oom", 0) - events_before.get("oom", 0),
            "oom_kill_delta":
                events_after.get("oom_kill", 0) - events_before.get("oom_kill", 0),
        }
    finally:
        for process in list(active_processes):
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
    # Only stable two-sided observations can advance the proof. Their order is
    # essential: witnessing all three states in arbitrary order is not proof
    # that ordinary swapoff preceded mapper removal.
    phase = 0  # 0: no active witness; 1: active; 2: swapoff; 3: removed
    last_timestamp = -1
    for sample in samples:
        if sample.monotonic_ns <= last_timestamp:
            raise Blocked("stop sampler timestamps are not strictly increasing")
        last_timestamp = sample.monotonic_ns
        if not sample.identity_valid and (sample.mapper_before or sample.mapper_after):
            raise QualificationFailure("mapper identity changed during stop")
        if not sample.mapper_before and not sample.mapper_after and sample.swap_active:
            raise QualificationFailure("mapper disappeared while still present in swap inventory")
        if sample.mapper_before != sample.mapper_after:
            continue
        if sample.mapper_before:
            if sample.swap_active:
                if phase >= 2:
                    raise QualificationFailure("mapper swap reactivated after swapoff during stop")
                phase = 1
            else:
                if phase == 0:
                    raise Blocked("stop sampler did not witness initial active mapper")
                if phase == 3:
                    raise QualificationFailure("mapper reappeared after removal during stop")
                phase = 2
        else:
            if phase < 2:
                raise Blocked(
                    "stop completed but sampler did not independently witness swapoff before mapper removal")
            phase = 3
    if phase == 0:
        raise Blocked("stop sampler did not witness initial active mapper")
    if phase == 1:
        raise Blocked("stop completed but sampler did not independently witness swapoff before mapper removal")
    if phase == 2:
        raise Blocked("stop sampler did not witness final mapper absence")
    return {"initial_active": True, "swapoff_before_remove_witness": True,
            "final_absent": True, "samples": len(samples)}


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
    try:
        expected_geometry = maximum_primary_geometry(
            manifest["device_bytes_int"])
        plan_logical_pages = int(plan["logical_pages"])
        plan_logical_bytes = int(plan["logical_bytes"])
        plan_linux_swap_kib = int(plan["linux_swap_kib"])
        plan_reserve_blocks = int(plan["gc_reserve_blocks"])
    except (Blocked, KeyError, TypeError, ValueError) as exc:
        raise QualificationFailure(
            "prepared manifest capacity cannot be independently verified") from exc
    if manifest["logical_pages_int"] != expected_geometry["logical_pages"] or \
            manifest["logical_sectors_int"] != expected_geometry["logical_sectors"] or \
            plan_logical_pages != expected_geometry["logical_pages"] or \
            plan_logical_bytes != expected_geometry["logical_bytes"] or \
            plan_linux_swap_kib != expected_geometry["linux_swap_kib"] or \
            plan_reserve_blocks != expected_geometry["gc_reserve_blocks"]:
        raise QualificationFailure(
            "prepared manifest/plan capacity differs from production authority geometry")


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
              target_parent_device: tuple[int, int],
              workload_mib: int, resident_mib: int, swap_limit_mib: int,
              timeout_seconds: int, prior_run_ids: set[str], prior_swap_uuids: set[str],
              admission: SourceAdmissionClient) -> dict:
    baseline_rows = read_swap_rows()
    baseline_identity = _swap_identity(baseline_rows)
    _validate_precycle_state(
        selector_partuuid, target_device, target_parent_device, baseline_rows)
    kernel_before = _kernel_log_snapshot()

    # The unprivileged parent owns Git/network source admission. Revalidate
    # immediately before this cycle's first durable/card mutation.
    admission.require(f"cycle-{index}")

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
        loaded_module = verify_loaded_module_provenance(validated_source)
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
        "loaded_module": loaded_module,
        "workload": workload_result,
        "stop_order": stop_evidence,
        "fresh_mapper_used_kib": 0,
        "durable_final_stage": "COMPLETE",
    }


def _import_qualification(swapzctl: Path, report_path: Path) -> None:
    result = _run(
        [str(swapzctl), "primary", "qualification-import", str(report_path)],
        check=False, timeout=30,
        extra_environment=_physical_control_environment())
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().replace("\n", "; ")
        raise Blocked(f"cannot import exact qualification report: {detail}")


def _execute_admitted(arguments: argparse.Namespace,
                      admission: SourceAdmissionClient) -> dict:
    admission.require("initial")
    _ensure_commands(("cc", "dmsetup", "lsblk", "dmesg"))
    if os.sysconf("SC_PAGE_SIZE") != PAGE_BYTES:
        raise Blocked("primary real-swap qualification requires a 4096-byte host page")
    qualified_swapzctl = Path(arguments.swapzctl).resolve()
    report_path = Path(arguments.qualification_report).resolve()
    requested_oracle_path = Path(arguments.oracle)
    for path, label in (
            (qualified_swapzctl, "qualified installed swapzctl"),
            (report_path, "qualification report"),
            (requested_oracle_path, "real-swap oracle")):
        if not path.is_file():
            raise Blocked(f"{label} is unavailable: {path}")
    if not os.access(qualified_swapzctl, os.X_OK) or \
            not os.access(requested_oracle_path, os.X_OK):
        raise Blocked("qualified swapzctl/oracle executable permission is missing")
    private_workspace = tempfile.TemporaryDirectory(
        prefix="swapz-primary-physical-")
    private_parent = Path(private_workspace.name)
    os.chmod(private_parent, 0o700)
    private_directory = private_parent / "control"
    try:
        swapzctl, execution_control_sha256 = build_physical_execution_control(
            arguments.validated_source, qualified_swapzctl, private_directory)
        oracle_path, oracle_sha256 = pin_real_swap_oracle(
            requested_oracle_path, private_parent)
    except Exception:
        private_workspace.cleanup()
        raise

    try:
        preflight_workload_environment(
            arguments.workload_mib, arguments.resident_mib, arguments.swap_limit_mib)
        verify_acceptance_manifest(
            cycles=arguments.cycles,
            workload_mib=arguments.workload_mib,
            resident_mib=arguments.resident_mib,
            swap_limit_mib=arguments.swap_limit_mib,
            timeout_seconds=arguments.timeout_seconds)
        acceptance_policy_sha256 = acceptance_manifest_sha256()
        _kernel_log_snapshot()
        _import_qualification(swapzctl, report_path)
        plan = _read_plan(swapzctl)
        artifact_hashes = verify_provenance(
            plan, arguments.validated_source, report_path, qualified_swapzctl)
        selector_partuuid = _read_selector()
        _target_path, target_device, target_parent_device = verify_authorized_target(
            plan, selector_partuuid)
        # The verifier has already matched this value against live block
        # geometry, lsblk and the authorized target snapshot.
        target_size_bytes = int(plan["target_device_bytes"])
        baseline = read_swap_rows()
        _validate_precycle_state(
            selector_partuuid, target_device, target_parent_device, baseline)
        kernel_before = _kernel_log_snapshot()
        _reject_relevant_kernel_errors([])
    
        evidence = PersistentEvidence(
            RECOVERY_BASE,
            os.urandom(16).hex(),
            {
                "source_sha": arguments.validated_source,
                "acceptance_manifest_sha256": acceptance_policy_sha256,
                "qualification_report_sha256": _sha256_file(report_path),
                "helper_sha256": _sha256_file(Path(__file__)),
                "oracle_sha256": oracle_sha256,
                "qualified_installed_artifacts": artifact_hashes,
                "physical_execution_control_sha256": execution_control_sha256,
                "partuuid": selector_partuuid,
                "target_size_bytes": target_size_bytes,
                "target_device": f"{target_device[0]}:{target_device[1]}",
                "cycles_requested": arguments.cycles,
                "workload_mib": arguments.workload_mib,
                "resident_limit_mib": arguments.resident_mib,
                "swap_limit_mib": arguments.swap_limit_mib,
                "timeout_seconds": arguments.timeout_seconds,
                "concurrent_oracles": CONCURRENT_ORACLE_PROCESSES,
                "reuse_rounds_per_cycle": REUSE_ROUNDS,
                "cycles": [],
            },
        )
    
    except Exception:
        private_workspace.cleanup()
        raise

    run_ids: set[str] = set()
    swap_uuids: set[str] = set()
    cycles: list[dict] = []
    try:
        for cycle_index in range(1, arguments.cycles + 1):
            evidence.update(
                f"CYCLE_{cycle_index}_STARTING",
                cycles=cycles,
                cycle=cycle_index,
            )
            result = run_cycle(
                cycle_index,
                swapzctl=swapzctl,
                oracle_path=oracle_path,
                validated_source=arguments.validated_source,
                plan=plan,
                selector_partuuid=selector_partuuid,
                target_device=target_device,
                target_parent_device=target_parent_device,
                workload_mib=arguments.workload_mib,
                resident_mib=arguments.resident_mib,
                swap_limit_mib=arguments.swap_limit_mib,
                timeout_seconds=arguments.timeout_seconds,
                prior_run_ids=run_ids,
                prior_swap_uuids=swap_uuids,
                admission=admission,
            )
            run_ids.add(result["run_id"])
            swap_uuids.add(result["linux_swap_uuid"])
            cycles.append(result)
            evidence.update(
                f"CYCLE_{cycle_index}_COMPLETE",
                cycles=cycles,
                cycle=cycle_index,
                run_id=result["run_id"],
            )
        # A long physical run must not qualify a source superseded on main.
        # The final source proof is again performed by the unprivileged parent.
        admission.require("final")
        kernel_after = _kernel_log_snapshot()
        _reject_relevant_kernel_errors(_kernel_log_delta(kernel_before, kernel_after))
        result = {
            "schema": "swapz-primary-real-swap-v1",
            "status": "PASS",
            "source_sha": arguments.validated_source,
            "acceptance_manifest_sha256": acceptance_policy_sha256,
            "helper_sha256": _sha256_file(Path(__file__)),
            "oracle_sha256": oracle_sha256,
            "qualification_report_sha256": _sha256_file(report_path),
            "qualified_installed_artifacts": artifact_hashes,
            "physical_execution_control_sha256": execution_control_sha256,
            "partuuid": selector_partuuid,
            "target_size_bytes": target_size_bytes,
            "target_device": f"{target_device[0]}:{target_device[1]}",
            "cycles_requested": arguments.cycles,
            "cycles_passed": len(cycles),
            "workload_mib": arguments.workload_mib,
            "resident_limit_mib": arguments.resident_mib,
            "swap_limit_mib": arguments.swap_limit_mib,
            "timeout_seconds": arguments.timeout_seconds,
            "concurrent_oracles": CONCURRENT_ORACLE_PROCESSES,
            "reuse_rounds_per_cycle": REUSE_ROUNDS,
            "evidence_path": str(evidence.path),
            "cycles": cycles,
        }
        evidence.finish("PASS", cycles=cycles, result=result)
        return result
    except Blocked as exc:
        setattr(exc, "evidence_path", str(evidence.path))
        evidence.finish("BLOCKED", str(exc), cycles=cycles)
        raise
    except QualificationFailure as exc:
        setattr(exc, "evidence_path", str(evidence.path))
        evidence.finish("FAIL", str(exc), cycles=cycles)
        raise
    except Exception as exc:
        failure = QualificationFailure(
            f"internal qualification error: {type(exc).__name__}: {exc}")
        setattr(failure, "evidence_path", str(evidence.path))
        evidence.finish("FAIL", str(failure), cycles=cycles)
        raise failure from exc
    finally:
        private_workspace.cleanup()

def execute(arguments: argparse.Namespace,
            admission: SourceAdmissionClient | None = None) -> dict:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        raise Blocked("physical real-swap qualification must not run in GitHub-hosted CI")
    if os.geteuid() != 0:
        raise Blocked("physical real-swap qualification requires noninteractive root privilege")

    owns_admission = admission is None
    if admission is None:
        socket_path = getattr(arguments, "source_admission_socket", None)
        parent_uid = getattr(arguments, "source_admission_parent_uid", None)
        if not socket_path or parent_uid is None:
            raise Blocked("unprivileged source admission channel is required")
        admission = SourceAdmissionClient(
            socket_path, parent_uid, arguments.validated_source)
    try:
        return _execute_admitted(arguments, admission)
    finally:
        if owns_admission:
            admission.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validated-source", required=True)
    parser.add_argument("--qualification-report", required=True)
    parser.add_argument(
        "--swapzctl", default="/usr/local/sbin/swapzctl",
        help="qualified installed <prefix>/sbin/swapzctl whose artifact identity "
             "is bound by the owner report (default: /usr/local/sbin/swapzctl)")
    parser.add_argument("--oracle", default=str(ROOT / "tests/tools/primary-real-swap-oracle.py"))
    parser.add_argument("--cycles", type=int, default=DEFAULT_CYCLES)
    parser.add_argument("--workload-mib", type=int, default=DEFAULT_WORKLOAD_MIB)
    parser.add_argument("--resident-mib", type=int, default=DEFAULT_RESIDENT_MIB)
    parser.add_argument("--swap-limit-mib", type=int, default=DEFAULT_SWAP_LIMIT_MIB)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--source-admission-socket", default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--source-admission-parent-uid", type=int, default=None,
        help=argparse.SUPPRESS)
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
        if getattr(exc, "evidence_path", None):
            payload["evidence_path"] = exc.evidence_path
        print("BLOCKED_PRIMARY_REAL_SWAP=" + str(exc).replace("\n", "; "), file=sys.stderr)
        print(RESULT_PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return 2
    except QualificationFailure as exc:
        payload = {"schema": "swapz-primary-real-swap-v1", "status": "FAIL",
                   "reason": str(exc)}
        if getattr(exc, "evidence_path", None):
            payload["evidence_path"] = exc.evidence_path
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
