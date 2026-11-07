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
from collections import deque
from dataclasses import dataclass, asdict
import errno
import fcntl
import hashlib
import json
import math
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

_BOOTSTRAP_SOURCE_ROOT = globals().get("__swapz_source_root__")
if _BOOTSTRAP_SOURCE_ROOT is None:
    ROOT = Path(__file__).resolve().parents[2]
else:
    if not isinstance(_BOOTSTRAP_SOURCE_ROOT, str) or \
            not Path(_BOOTSTRAP_SOURCE_ROOT).is_absolute():
        raise RuntimeError("invalid commit-bound source root")
    ROOT = Path(_BOOTSTRAP_SOURCE_ROOT)
SELECTOR = Path("/etc/swapz/primary-target")
# PARTUUID= (9 bytes), up to 64 ASCII characters, and optional CRLF.
SELECTOR_MAX_BYTES = len("PARTUUID=") + 64 + 2
RECOVERY_BASE = Path("/var/lib/swapz/physical-recovery")
CGROUP_ROOT = Path("/sys/fs/cgroup")
AUTHORIZATION_SNAPSHOT = ROOT / "docs/handoff/production-readiness.json"
ACCEPTANCE_MANIFEST = ROOT / "docs/production-acceptance.json"
REAL_SWAP_ORACLE = ROOT / "tests/tools/primary-real-swap-oracle.py"
PHYSICAL_CONTROL_INPUT_PATHS = (
    "src/kernel/VERSION",
    "src/kernel/authority.h",
    "src/kernel/codec.h",
    "src/kernel/superblock.h",
    "src/kernel/swapz-build-info.h",
    "src/userspace/swapz-primary.h",
    "src/userspace/swapz-primary.c",
    "src/userspace/swapzctl.c",
    "docs/production-acceptance.json",
    "docs/handoff/production-readiness.json",
)
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
MAX_PHYSICAL_SOURCE_BYTES = 16 * 1024 * 1024
SOURCE_ADMISSION_TIMEOUT_SECONDS = 45
MAX_ORACLE_RECORD_BYTES = 4096
MAX_ORACLE_MISMATCH_SAMPLES = 16
# A sustained memory stall is a safety stop, not an integrity oracle.
PSI_STOP_FRACTION = 0.85
PSI_STOP_GRACE_SECONDS = 5
PSI_STOP_SAMPLE_INTERVAL_SECONDS = 0.05
PSI_STOP_MAX_SAMPLES = 256
CYCLE_TELEMETRY_INTERVAL_SECONDS = 0.1
CYCLE_TELEMETRY_THREAD_TIMEOUT_SECONDS = 5
TRUSTED_EXTERNAL_COMMANDS = frozenset(("cc", "dmsetup", "lsblk", "dmesg"))
SAFE_CHILD_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"


class Blocked(RuntimeError):
    pass


class QualificationFailure(RuntimeError):
    pass


class PsiStallWindow:
    """Bounded rolling detector for sustained cgroup memory-pressure stalls."""

    def __init__(self, monotonic_seconds: float, total_usec: int):
        self._samples: deque[tuple[float, int]] = deque(
            [(monotonic_seconds, total_usec)], maxlen=PSI_STOP_MAX_SAMPLES)
        self._last_observed_time = monotonic_seconds
        self._last_observed_total = total_usec

    def observe(self, monotonic_seconds: float, total_usec: int) -> bool:
        if monotonic_seconds < self._last_observed_time:
            raise QualificationFailure(
                "monotonic clock regressed during cgroup PSI monitoring")
        if total_usec < self._last_observed_total:
            raise QualificationFailure(
                "cgroup memory PSI total regressed during workload")
        self._last_observed_time = monotonic_seconds
        self._last_observed_total = total_usec

        if monotonic_seconds - self._samples[-1][0] < \
                PSI_STOP_SAMPLE_INTERVAL_SECONDS:
            return False
        self._samples.append((monotonic_seconds, total_usec))

        cutoff = monotonic_seconds - PSI_STOP_GRACE_SECONDS
        while len(self._samples) >= 2 and self._samples[1][0] <= cutoff:
            self._samples.popleft()

        oldest_time, oldest_total = self._samples[0]
        elapsed_seconds = monotonic_seconds - oldest_time
        if elapsed_seconds < PSI_STOP_GRACE_SECONDS:
            return False
        stalled_usec = total_usec - oldest_total
        return stalled_usec > (
            PSI_STOP_FRACTION * elapsed_seconds * 1_000_000)


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key}")
        result[key] = value
    return result


def _reject_nonfinite_json_constant(value: str):
    raise ValueError(f"non-finite JSON number {value}")


def _finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number {value}")
    return parsed


def _exception_text(error: BaseException) -> str:
    detail = str(error)
    return detail if detail else type(error).__name__


def _lstat_optional(path: Path, label: str,
                    error_type: type[Exception] = Blocked) -> os.stat_result | None:
    """Return identity or absence; never collapse an inspection error to absence."""
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise error_type(f"cannot inspect {label}: {exc}") from exc


def _path_present(path: Path, label: str,
                  error_type: type[Exception] = Blocked) -> bool:
    return _lstat_optional(path, label, error_type) is not None



def _source_parent_refusal(phase: str, check: str, observed: str,
                           error_number: int | str = "none") -> Blocked:
    """Bounded, failure-only proof classes; never disclose private PIDs or paths."""
    return Blocked(
        f"source_admission_parent_auth:phase={phase}:check={check}:"
        "expected=live_ancestor_pid_starttime_uid_socket_inode_reply_sender:"
        f"observed={observed}:errno={error_number}:authorization=BLOCKED:"
        "next=inspect_parent_identity_read_only")


def _source_parent_ancestors(
        phase: str, parent_uid: int) -> tuple[tuple[int, int, int], ...]:
    """Capture only the living lineage through the authorized parent candidate."""
    ancestry: list[tuple[int, int, int]] = []
    visited: set[int] = set()
    process_id = os.getppid()
    for _ in range(32):
        if process_id <= 1:
            raise _source_parent_refusal(
                phase, "parent_ancestry", "missing_authorized_parent")
        if process_id in visited:
            raise _source_parent_refusal(
                phase, "process_lineage", "cyclic_process_ancestry")
        visited.add(process_id)
        try:
            process_stat = (Path("/proc") / str(process_id) / "stat").read_text(
                encoding="ascii")
        except OSError as exc:
            raise _source_parent_refusal(
                phase, "process_lineage", "unavailable_process_identity",
                exc.errno if exc.errno is not None else "none") from exc
        except UnicodeError as exc:
            raise _source_parent_refusal(
                phase, "process_lineage", "malformed_process_identity") from exc
        closing_parenthesis = process_stat.rfind(") ")
        fields = (process_stat[closing_parenthesis + 2:].split()
                  if closing_parenthesis >= 0 else [])
        try:
            if len(fields) < 20:
                raise ValueError("truncated process stat")
            parent_id = int(fields[1])
            start_ticks = int(fields[19])
        except ValueError as exc:
            raise _source_parent_refusal(
                phase, "process_lineage", "malformed_process_identity") from exc
        if (fields[0] in {"Z", "X", "x"} or parent_id < 0 or
                start_ticks <= 0 or parent_id == process_id):
            raise _source_parent_refusal(
                phase, "process_lineage", "exited_or_invalid_process")
        ancestry.append((process_id, parent_id, start_ticks))
        if _source_nearest_uid_ancestor(
                (ancestry[-1],), parent_uid, phase) == process_id:
            return tuple(ancestry)
        process_id = parent_id
    raise _source_parent_refusal(
        phase, "process_lineage", "ambiguous_process_ancestry")


def _source_parent_lineage_matches(
        pinned_ancestors: tuple[tuple[int, int, int], ...],
        observed_ancestors: tuple[tuple[int, int, int], ...]) -> bool:
    """Verify every intermediate link but not the terminal parent's upstream PPID.

    The authorized parent's PID and start ticks remain bound to its live
    pidfd, socket and effective UID; its own parent is not source authority.
    """
    if not pinned_ancestors or len(pinned_ancestors) != len(observed_ancestors):
        return False
    return (
        pinned_ancestors[:-1] == observed_ancestors[:-1] and
        pinned_ancestors[-1][0] == observed_ancestors[-1][0] and
        pinned_ancestors[-1][2] == observed_ancestors[-1][2])


def _source_nearest_uid_ancestor(
        ancestors: tuple[tuple[int, int, int], ...],
        parent_uid: int, phase: str) -> int | None:
    """Use the effective UID to select the nearest authorized parent ancestor.

    The caller stops at the first match and revalidates that child-to-parent
    start-tick lineage, so unrelated ancestors above the parent are not authority.
    """
    for process_id, _parent_pid, _start_ticks in ancestors:
        try:
            status = (Path("/proc") / str(process_id) / "status").read_text(
                encoding="ascii")
        except OSError as exc:
            raise _source_parent_refusal(
                phase, "parent_ancestry", "unavailable_process_owner",
                exc.errno if exc.errno is not None else "none") from exc
        except UnicodeError as exc:
            raise _source_parent_refusal(
                phase, "parent_ancestry", "malformed_process_owner") from exc
        user_ids = [
            record.split() for record in status.splitlines()
            if record.startswith("Uid:")
        ]
        if (len(user_ids) != 1 or len(user_ids[0]) != 5 or
                user_ids[0][0] != "Uid:" or
                any(not value.isascii() or not value.isdecimal()
                    for value in user_ids[0][1:])):
            raise _source_parent_refusal(
                phase, "parent_ancestry", "malformed_process_owner")
        if int(user_ids[0][2]) == parent_uid:
            return process_id
    return None



def _source_parent_pidfd_alive(descriptor: int, phase: str) -> None:
    """A pinned pidfd cannot silently become a different process after PID reuse."""
    try:
        poller = select.poll()
        poller.register(descriptor, select.POLLIN | select.POLLHUP | select.POLLERR)
        if poller.poll(0):
            raise _source_parent_refusal(
                phase, "parent_liveness", "exited_parent_process")
    except OSError as exc:
        raise _source_parent_refusal(
            phase, "parent_liveness", "unavailable_parent_liveness",
            exc.errno if exc.errno is not None else "none") from exc


class SourceAdmissionClient:
    """Authenticated channel to the unprivileged source-verification parent."""

    def __init__(self, socket_path: str, parent_uid: int,
                 expected_parent_process_id: int,
                 expected_parent_start_ticks: int,
                 validated_source: str):
        if not re.fullmatch(r"[0-9a-f]{40}", validated_source):
            raise Blocked("validated source must be one full lowercase SHA")
        if parent_uid <= 0:
            raise Blocked("source admission parent must be unprivileged")
        if type(expected_parent_process_id) is not int or \
                expected_parent_process_id <= 1:
            raise Blocked("source admission parent process ID is invalid")
        if type(expected_parent_start_ticks) is not int or \
                expected_parent_start_ticks <= 0:
            raise Blocked("source admission parent start time is invalid")
        path = Path(socket_path)
        if not path.is_absolute():
            raise Blocked("source admission socket path must be absolute")
        try:
            before = path.lstat()
        except OSError as exc:
            raise _source_parent_refusal(
                "connect", "socket_identity", "unavailable_socket",
                exc.errno if exc.errno is not None else "none") from exc
        if (not stat.S_ISSOCK(before.st_mode) or before.st_uid != parent_uid or
                stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1):
            raise _source_parent_refusal(
                "connect", "socket_identity", "unsafe_socket_metadata")

        channel = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        channel.settimeout(SOURCE_ADMISSION_TIMEOUT_SECONDS)
        parent_pidfd: int | None = None
        try:
            # Capture ancestry before connecting: a replaced pathname must
            # not choose its own authority merely by matching our UID.
            ancestors = _source_parent_ancestors("connect", parent_uid)
            (authorized_parent_pid, _upstream_pid,
             authorized_parent_start_ticks) = ancestors[-1]
            if (authorized_parent_pid != expected_parent_process_id or
                    authorized_parent_start_ticks != expected_parent_start_ticks):
                raise _source_parent_refusal(
                    "connect", "parent_ancestry", "stale_or_replaced_parent")
            if not hasattr(os, "pidfd_open"):
                raise _source_parent_refusal(
                    "connect", "parent_liveness", "pidfd_unavailable")
            parent_pidfd = os.pidfd_open(authorized_parent_pid)
            _source_parent_pidfd_alive(parent_pidfd, "connect")
            if not _source_parent_lineage_matches(
                    ancestors, _source_parent_ancestors("connect", parent_uid)):
                raise _source_parent_refusal(
                    "connect", "parent_ancestry", "changed_parent_process")
            channel.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
            channel.connect(os.fspath(path))
            credentials = channel.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            peer_pid, peer_uid, _peer_gid = struct.unpack("3i", credentials)
            after = path.lstat()
            before_identity = (
                before.st_dev, before.st_ino, before.st_uid,
                before.st_mode, before.st_nlink, before.st_ctime_ns)
            after_identity = (
                after.st_dev, after.st_ino, after.st_uid,
                after.st_mode, after.st_nlink, after.st_ctime_ns)
            if before_identity != after_identity:
                raise _source_parent_refusal(
                    "connect", "socket_identity", "exchanged_socket_inode")
            if peer_uid != parent_uid:
                raise _source_parent_refusal(
                    "connect", "peer_uid", "wrong_peer_uid")
            # sudo may insert root-owned monitors, but the listener creator
            # must terminate the child-to-parent lineage at the nearest
            # ancestor with the source parent's effective UID.
            if peer_pid != authorized_parent_pid:
                raise _source_parent_refusal(
                    "connect", "parent_ancestry", "unrelated_peer_run")
            _source_parent_pidfd_alive(parent_pidfd, "connect")
        except Blocked as exc:
            if parent_pidfd is not None:
                os.close(parent_pidfd)
            try:
                channel.close()
            except OSError as cleanup_error:
                _raise_cleanup_errors(
                    exc, [f"source admission socket close:errno="
                          f"{cleanup_error.errno if cleanup_error.errno is not None else 'none'}"],
                    error_type=Blocked)
            raise
        except (OSError, struct.error) as exc:
            failure = _source_parent_refusal(
                "connect", "connection", "transport_or_credential_error",
                exc.errno if isinstance(exc, OSError) and exc.errno is not None
                else "none")
            if parent_pidfd is not None:
                os.close(parent_pidfd)
            try:
                channel.close()
            except OSError as cleanup_error:
                _raise_cleanup_errors(
                    failure, [f"source admission socket close:errno="
                              f"{cleanup_error.errno if cleanup_error.errno is not None else 'none'}"],
                    error_type=Blocked)
            raise failure from exc
        self._channel = channel
        self._parent_pidfd = parent_pidfd
        self._parent_process_id = peer_pid
        self._parent_uid = parent_uid
        self._parent_ancestors = ancestors
        self._parent_socket_path = path
        self._parent_socket_identity = after_identity
        self._validated_source = validated_source
        self._oracle_sha256: str | None = None
        self._physical_control_inputs_sha256: dict[str, str] | None = None
        self._executed_helper_sha256: str | None = None

    def bind_executed_helper_sha256(self, digest: str) -> None:
        if not isinstance(digest, str) or \
                re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise Blocked("executed helper digest is malformed")
        if self._executed_helper_sha256 is not None and \
                self._executed_helper_sha256 != digest:
            raise Blocked("executed helper identity changed")
        self._executed_helper_sha256 = digest

    def bind_physical_control_inputs(self, hashes: dict[str, str]) -> None:
        if not isinstance(hashes, dict) or set(hashes) != set(PHYSICAL_CONTROL_INPUT_PATHS):
            raise Blocked("physical control source input inventory is incomplete")
        normalized: dict[str, str] = {}
        for path in PHYSICAL_CONTROL_INPUT_PATHS:
            digest = hashes.get(path)
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise Blocked("physical control source input digest is malformed")
            normalized[path] = digest
        if self._physical_control_inputs_sha256 is not None and \
                self._physical_control_inputs_sha256 != normalized:
            raise Blocked("physical control source input identity changed")
        self._physical_control_inputs_sha256 = normalized

    def close(self) -> None:
        channel = getattr(self, "_channel", None)
        if channel is not None:
            # Keep ownership until close succeeds so a reported close failure
            # can be retried by the outer cleanup path.
            channel.close()
            self._channel = None
        parent_pidfd = getattr(self, "_parent_pidfd", None)
        if parent_pidfd is not None:
            os.close(parent_pidfd)
            self._parent_pidfd = None

    def _require_parent_authority(self, phase: str) -> None:
        # The PID is not an authority by itself. Pin its creation-time kernel
        # reference and lineage through the authenticated parent, then recheck
        # the named endpoint. Ancestors above that parent are not authority.
        _source_parent_pidfd_alive(self._parent_pidfd, phase)
        if not _source_parent_lineage_matches(
                self._parent_ancestors,
                _source_parent_ancestors(phase, self._parent_uid)):
            raise _source_parent_refusal(
                phase, "parent_ancestry", "changed_parent_process")
        try:
            named = self._parent_socket_path.lstat()
        except OSError as exc:
            raise _source_parent_refusal(
                phase, "socket_identity", "unavailable_socket",
                exc.errno if exc.errno is not None else "none") from exc
        named_identity = (
            named.st_dev, named.st_ino, named.st_uid,
            named.st_mode, named.st_nlink, named.st_ctime_ns)
        if named_identity != self._parent_socket_identity:
            raise _source_parent_refusal(
                phase, "socket_identity", "exchanged_socket_inode")

    def _read_line(self, phase: str) -> bytes:
        data = bytearray()
        kernel_socket = isinstance(self._channel, socket.socket)
        credential_bytes = struct.calcsize("3i") if kernel_socket else 0
        ancillary_capacity = (
            socket.CMSG_SPACE(credential_bytes) if kernel_socket else 0)
        while len(data) <= SOURCE_ADMISSION_MAX_LINE_BYTES:
            if kernel_socket:
                # SO_PEERCRED alone survives SCM_RIGHTS/duplicate-fd handoff.
                # Check SCM_CREDENTIALS on *each received byte* so a foreign
                # writer cannot append to a trusted process's stream reply.
                chunk, ancillary, flags, _address = self._channel.recvmsg(
                    1, ancillary_capacity)
                if not chunk:
                    raise _source_parent_refusal(
                        phase, "reply_transport", "parent_disconnected")
                if (flags & (socket.MSG_CTRUNC | socket.MSG_TRUNC) or
                        len(ancillary) != 1 or
                        ancillary[0][:2] != (
                            socket.SOL_SOCKET, socket.SCM_CREDENTIALS) or
                        len(ancillary[0][2]) != credential_bytes):
                    raise _source_parent_refusal(
                        phase, "reply_sender", "missing_or_ambiguous_credentials")
                sender_pid, sender_uid, _sender_gid = struct.unpack(
                    "3i", ancillary[0][2])
                if (sender_pid != self._parent_process_id or
                        sender_uid != self._parent_uid):
                    raise _source_parent_refusal(
                        phase, "reply_sender", "foreign_message_sender")
            else:
                # Legacy unit-test doubles have no kernel credentials.
                chunk = self._channel.recv(1)
            if not chunk:
                raise _source_parent_refusal(
                    phase, "reply_transport", "parent_disconnected")
            if chunk == b"\n":
                return bytes(data)
            data.extend(chunk)
        raise _source_parent_refusal(
            phase, "reply_bounds", "oversized_authorization_reply")

    def require(self, phase: str) -> str:
        if not re.fullmatch(r"(?:initial|final|cycle-[1-4])", phase):
            raise Blocked("source admission phase is invalid")
        if self._physical_control_inputs_sha256 is None:
            raise Blocked("physical control source inputs are not pinned")
        if self._executed_helper_sha256 is None:
            raise Blocked("executed helper identity is not pinned")
        if isinstance(self._channel, socket.socket):
            self._require_parent_authority(phase)
        nonce = os.urandom(16).hex()
        request = {
            "schema": SOURCE_ADMISSION_SCHEMA,
            "phase": phase,
            "source_sha": self._validated_source,
            "nonce": nonce,
            "physical_control_inputs_sha256": self._physical_control_inputs_sha256,
            "executed_helper_sha256": self._executed_helper_sha256,
        }
        try:
            self._channel.sendall(
                json.dumps(
                    request, sort_keys=True, separators=(",", ":")).encode("ascii") +
                b"\n")
            response_bytes = self._read_line(phase)
            if isinstance(self._channel, socket.socket):
                self._require_parent_authority(phase)
        except OSError as exc:
            error_number = exc.errno if exc.errno is not None else "none"
            raise Blocked(
                f"source admission transport failed at {phase}:"
                f"{_source_parent_refusal(phase, 'transport', 'transport_error', error_number)}") from exc
        try:
            response = json.loads(
                response_bytes.decode("ascii"),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_nonfinite_json_constant,
                parse_float=_finite_json_float)
        except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
            raise Blocked(
                "source admission response is malformed:" +
                str(_source_parent_refusal(
                    phase, "reply_parser", "malformed_authorization_reply"))) from exc
        required = {
            "schema", "status", "phase", "source_sha", "nonce",
            "oracle_sha256",
        }
        status = response.get("status") if isinstance(response, dict) else None
        if status == "BLOCKED":
            required.add("reason")
        oracle_sha256 = (
            response.get("oracle_sha256") if isinstance(response, dict) else None)
        if (not isinstance(response, dict) or set(response) != required or
                (not isinstance(status, str) or
                 status not in {"PASS", "BLOCKED"}) or
                (status == "BLOCKED" and (
                    not isinstance(response.get("reason"), str) or
                    not response["reason"].isascii() or
                    not 1 <= len(response["reason"]) <= 256 or
                    any(ord(character) < 0x20 for character in response["reason"]))) or
                response.get("schema") != SOURCE_ADMISSION_SCHEMA or
                response.get("phase") != phase or
                response.get("source_sha") != self._validated_source or
                response.get("nonce") != nonce or
                not isinstance(oracle_sha256, str) or
                re.fullmatch(r"[0-9a-f]{64}", oracle_sha256) is None):
            raise Blocked(
                "source admission response identity mismatch:" +
                str(_source_parent_refusal(
                    phase, "reply_fields", "mismatched_authorization_reply")))
        if status != "PASS":
            if isinstance(self._channel, socket.socket):
                raise _source_parent_refusal(
                    phase, "authorization_reply", "parent_refused")
            raise Blocked(
                f"unprivileged source admission refused at {phase}: "
                f"{response['reason']}")
        if self._oracle_sha256 is None:
            self._oracle_sha256 = oracle_sha256
        elif self._oracle_sha256 != oracle_sha256:
            raise Blocked(
                "source admission oracle identity changed:" +
                str(_source_parent_refusal(
                    phase, "oracle_sha256", "changed_oracle_identity")))
        return oracle_sha256


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
            original_error = sys.exc_info()[1]
            cleanup_errors = []
            for descriptor in (file_descriptor, directory_descriptor):
                if descriptor >= 0:
                    try:
                        os.close(descriptor)
                    except OSError as cleanup_error:
                        cleanup_errors.append(
                            f"persistent evidence descriptor: {cleanup_error}")
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError as cleanup_error:
                cleanup_errors.append(
                    f"persistent evidence temporary artifact: {cleanup_error}")
            _raise_cleanup_errors(original_error, cleanup_errors,
                                  error_type=error_type)

    def update(self, phase: str, **fields) -> None:
        self.record.update(fields)
        self.record["phase"] = phase
        self.record["updated_unix_ns"] = time.time_ns()
        self._write()

    def finish(self, status_value: str, reason: str | None = None, **fields) -> None:
        if status_value not in {"PASS", "FAIL", "BLOCKED"}:
            raise ValueError("terminal evidence status must be PASS, FAIL, or BLOCKED")
        self.record.update(fields)
        if status_value != "PASS":
            # A failed post-publication check must not retain a nested PASS result.
            self.record.pop("result", None)
        self.record["status"] = status_value
        self.record["reason"] = reason
        self.record["phase"] = "COMPLETE"
        self.record["updated_unix_ns"] = time.time_ns()
        self._write()


def _trusted_executable_path(candidate: str, label: str) -> str:
    try:
        resolved = Path(candidate).resolve(strict=True)
        info = resolved.stat()
    except OSError as exc:
        raise Blocked(f"cannot inspect required {label}") from exc
    if not resolved.is_absolute() or not stat.S_ISREG(info.st_mode) or \
            info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022 or \
            not os.access(resolved, os.X_OK):
        raise Blocked(f"unsafe required {label}")
    return os.fspath(resolved)


def _trusted_executable(name: str) -> str:
    candidate = shutil.which(name, path=SAFE_CHILD_PATH)
    if not candidate:
        raise Blocked(f"missing required command {name}")
    return _trusted_executable_path(candidate, f"command {name}")


def _safe_child_environment(
        extra_environment: dict[str, str] | None = None) -> dict[str, str]:
    environment = {
        "LC_ALL": "C",
        "LANG": "C",
        "PATH": SAFE_CHILD_PATH,
    }
    if extra_environment:
        environment.update(extra_environment)
    return environment


def _run(argv: list[str], *, check: bool = True, timeout: float = 30,
         input_text: str | None = None,
         extra_environment: dict[str, str] | None = None,
         cwd: Path | None = None
         ) -> subprocess.CompletedProcess[str]:
    if not argv:
        raise Blocked("required command invocation is empty")
    command = list(argv)
    if command[0] in TRUSTED_EXTERNAL_COMMANDS:
        command[0] = _trusted_executable(command[0])
    environment = _safe_child_environment(extra_environment)
    try:
        result = subprocess.run(
            command,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=environment,
            cwd=cwd,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Blocked(
            f"cannot execute required command {command[0]}: {exc}") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().replace("\n", "; ")
        raise QualificationFailure(
            f"command failed rc={result.returncode}: {' '.join(command)}: {detail}")
    return result


def _stable_file_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
        info.st_ctime_ns, info.st_mode, info.st_uid, info.st_gid,
        info.st_nlink,
    )


def _read_stable_file_bytes(
        path: Path, label: str,
        error_type: type[Exception] = Blocked) -> bytes:
    """Read one regular pathname without following or racing a replacement."""
    file_descriptor = -1
    try:
        named_before = path.lstat()
        if not stat.S_ISREG(named_before.st_mode):
            raise error_type(f"{label} is not a regular file")
        file_descriptor = os.open(
            path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        opened_before = os.fstat(file_descriptor)
        if not stat.S_ISREG(opened_before.st_mode) or \
                opened_before.st_dev != named_before.st_dev or \
                opened_before.st_ino != named_before.st_ino:
            raise error_type(f"{label} pathname identity changed before open")
        payload = bytearray()
        while True:
            chunk = os.read(file_descriptor, 1024 * 1024)
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > MAX_PHYSICAL_SOURCE_BYTES:
                raise error_type(f"{label} exceeds the bounded source input size")
        opened_after = os.fstat(file_descriptor)
        named_after = path.lstat()
        if _stable_file_identity(opened_after) != _stable_file_identity(opened_before) or \
                _stable_file_identity(named_after) != _stable_file_identity(opened_after) or \
                len(payload) != opened_after.st_size:
            raise error_type(f"{label} changed while being read")
        return bytes(payload)
    except (Blocked, QualificationFailure):
        raise
    except OSError as exc:
        raise error_type(f"cannot read {label}: {exc}") from exc
    finally:
        original_error = sys.exc_info()[1]
        if file_descriptor >= 0:
            try:
                os.close(file_descriptor)
            except OSError as cleanup_error:
                _raise_cleanup_errors(
                    original_error, [f"{label} descriptor: {cleanup_error}"],
                    error_type=error_type)


def _read_stable_relative_file_bytes(
        root: Path, relative: Path, label: str,
        error_type: type[Exception] = Blocked) -> bytes:
    """Read a bounded regular file beneath root without following symlinks."""
    if relative.is_absolute() or not relative.parts or any(
            part in {"", ".", ".."} for part in relative.parts):
        raise error_type(f"{label} relative path is not canonical")

    descriptors: list[int] = []
    try:
        named_root = root.lstat()
        if not stat.S_ISDIR(named_root.st_mode):
            raise error_type(f"{label} root is not a directory")
        root_descriptor = os.open(
            root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
        descriptors.append(root_descriptor)
        opened_root = os.fstat(root_descriptor)
        if not stat.S_ISDIR(opened_root.st_mode) or \
                opened_root.st_dev != named_root.st_dev or \
                opened_root.st_ino != named_root.st_ino:
            raise error_type(f"{label} root identity changed before open")

        directory_descriptor = root_descriptor
        for component in relative.parts[:-1]:
            next_descriptor = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=directory_descriptor,
            )
            descriptors.append(next_descriptor)
            if not stat.S_ISDIR(os.fstat(next_descriptor).st_mode):
                raise error_type(f"{label} parent is not a directory")
            directory_descriptor = next_descriptor

        file_descriptor = os.open(
            relative.parts[-1],
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=directory_descriptor,
        )
        descriptors.append(file_descriptor)
        opened_before = os.fstat(file_descriptor)
        if not stat.S_ISREG(opened_before.st_mode):
            raise error_type(f"{label} is not a regular file")

        payload = bytearray()
        while len(payload) <= MAX_PHYSICAL_SOURCE_BYTES:
            chunk = os.read(file_descriptor, min(
                1024 * 1024, MAX_PHYSICAL_SOURCE_BYTES + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) > MAX_PHYSICAL_SOURCE_BYTES:
            raise error_type(f"{label} exceeds the bounded source input size")

        opened_after = os.fstat(file_descriptor)
        named_after = os.stat(
            relative.parts[-1], dir_fd=directory_descriptor,
            follow_symlinks=False)
        root_after = root.lstat()
        if _stable_file_identity(opened_after) != _stable_file_identity(opened_before) or \
                _stable_file_identity(named_after) != _stable_file_identity(opened_after) or \
                _stable_file_identity(root_after) != _stable_file_identity(opened_root) or \
                len(payload) != opened_after.st_size:
            raise error_type(f"{label} changed while being read")
        return bytes(payload)
    except (Blocked, QualificationFailure):
        raise
    except OSError as exc:
        raise error_type(f"cannot read {label}: {exc}") from exc
    finally:
        original_error = sys.exc_info()[1]
        cleanup_errors = []
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError as cleanup_error:
                cleanup_errors.append(f"{label} descriptor: {cleanup_error}")
        _raise_cleanup_errors(
            original_error, cleanup_errors, error_type=error_type)


def _sha256_file(
        path: Path, *, error_type: type[Exception] = Blocked) -> str:
    """Hash a stable regular file without buffering the entire artifact."""
    label = f"hash input {path}"
    file_descriptor = -1
    try:
        named_before = path.lstat()
        if not stat.S_ISREG(named_before.st_mode):
            raise error_type(f"{label} is not a regular file")
        file_descriptor = os.open(
            path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        opened_before = os.fstat(file_descriptor)
        if not stat.S_ISREG(opened_before.st_mode) or \
                opened_before.st_dev != named_before.st_dev or \
                opened_before.st_ino != named_before.st_ino:
            raise error_type(f"{label} pathname identity changed before open")
        digest = hashlib.sha256()
        byte_count = 0
        while True:
            chunk = os.read(file_descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            byte_count += len(chunk)
        opened_after = os.fstat(file_descriptor)
        named_after = path.lstat()
        if _stable_file_identity(opened_after) != _stable_file_identity(opened_before) or \
                _stable_file_identity(named_after) != _stable_file_identity(opened_after) or \
                byte_count != opened_after.st_size:
            raise error_type(f"{label} changed while being hashed")
        return digest.hexdigest()
    except (Blocked, QualificationFailure):
        raise
    except OSError as exc:
        raise error_type(f"cannot read {label}: {exc}") from exc
    finally:
        original_error = sys.exc_info()[1]
        if file_descriptor >= 0:
            try:
                os.close(file_descriptor)
            except OSError as cleanup_error:
                _raise_cleanup_errors(
                    original_error, [f"{label} descriptor: {cleanup_error}"],
                    error_type=error_type)


def pin_real_swap_oracle(oracle_path: Path, private_directory: Path,
                         expected_sha256: str) -> tuple[Path, str]:
    """Pin exact commit-bound oracle bytes before admitted mutation."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise Blocked("validated real-swap oracle digest is malformed")
    supplied = Path(os.path.abspath(os.fspath(oracle_path)))
    if supplied != REAL_SWAP_ORACLE:
        raise Blocked("real-swap oracle must be the exact source-controlled oracle")
    payload = _read_stable_relative_file_bytes(
        ROOT, Path("tests/tools/primary-real-swap-oracle.py"),
        "real-swap oracle")
    digest = hashlib.sha256(payload).hexdigest()
    if digest != expected_sha256:
        raise Blocked(
            "real-swap oracle bytes differ from validated source commit")

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
        original_error = sys.exc_info()[1]
        if output_fd >= 0:
            try:
                os.close(output_fd)
            except OSError as cleanup_error:
                _raise_cleanup_errors(
                    original_error,
                    [f"pinned real-swap oracle descriptor: {cleanup_error}"],
                    error_type=Blocked)

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


def pin_physical_control_inputs(
        private_parent: Path) -> tuple[Path, dict[str, str]]:
    """Snapshot every local C build input before unprivileged source admission."""
    source_root = private_parent / "source"
    source_root.mkdir(mode=0o700, parents=False, exist_ok=False)
    os.chmod(source_root, 0o700)
    hashes: dict[str, str] = {}
    for relative_text in PHYSICAL_CONTROL_INPUT_PATHS:
        relative = Path(relative_text)
        payload = _read_stable_relative_file_bytes(
            ROOT, relative, f"physical control source {relative_text}")
        digest = hashlib.sha256(payload).hexdigest()
        destination_parent = source_root
        for component in relative.parent.parts:
            destination_parent = destination_parent / component
            try:
                destination_parent.mkdir(mode=0o700)
            except FileExistsError:
                pass
            info = destination_parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
                raise Blocked("private physical source directory identity is unsafe")
            os.chmod(destination_parent, 0o700)
        destination = source_root / relative
        descriptor = -1
        try:
            descriptor = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                os.O_CLOEXEC | os.O_NOFOLLOW,
                0o400,
            )
            offset = 0
            while offset < len(payload):
                written = os.write(descriptor, payload[offset:])
                if written <= 0:
                    raise OSError(errno.EIO, "short private source snapshot write")
                offset += written
            os.fsync(descriptor)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or \
                    stat.S_IMODE(info.st_mode) != 0o400 or info.st_nlink != 1:
                raise Blocked("private physical source snapshot identity is unsafe")
        except (Blocked, QualificationFailure):
            raise
        except OSError as exc:
            raise Blocked(
                f"cannot snapshot physical control source {relative_text}: {exc}") from exc
        finally:
            original_error = sys.exc_info()[1]
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError as cleanup_error:
                    _raise_cleanup_errors(
                        original_error,
                        [f"physical control source {relative_text} descriptor: "
                         f"{cleanup_error}"],
                        error_type=Blocked)
        if _sha256_file(destination) != digest:
            raise Blocked("private physical source snapshot digest mismatch")
        hashes[relative_text] = digest
    return source_root, hashes


def require_pinned_physical_control_inputs(
        source_root: Path, private_directory: Path,
        expected_hashes: dict[str, str] | None, phase: str) -> None:
    """Prove the private compiler's complete repository input closure.

    The snapshot is owned by this root-only workspace until final cleanup.
    Rechecking on both sides of compilation detects unauthorized edits; the
    unprivileged worktree cannot supply an include inside this tree.
    """
    if source_root.name != "source" or source_root.parent != private_directory.parent \
            or source_root == ROOT:
        raise Blocked(f"physical control source root is not private at {phase}")
    try:
        workspace_identity = source_root.parent.lstat()
    except OSError as exc:
        raise Blocked(
            f"private physical control workspace unavailable at {phase}") from exc
    if not stat.S_ISDIR(workspace_identity.st_mode) or \
            workspace_identity.st_uid != os.geteuid() or \
            stat.S_IMODE(workspace_identity.st_mode) != 0o700:
        raise Blocked(f"private physical control workspace unsafe at {phase}")
    if not isinstance(expected_hashes, dict) or \
            set(expected_hashes) != set(PHYSICAL_CONTROL_INPUT_PATHS):
        raise Blocked("physical control validated-commit input inventory is incomplete")

    expected_files = set(PHYSICAL_CONTROL_INPUT_PATHS)
    for relative in PHYSICAL_CONTROL_INPUT_PATHS:
        expected = expected_hashes[relative]
        if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise Blocked("physical control validated-commit digest is malformed")
        path = source_root / relative
        # O_NOFOLLOW on a file alone does not reject symlink parent directories.
        directory = source_root
        for part in (".", *Path(relative).parent.parts):
            if part != ".":
                directory = directory / part
            try:
                identity = directory.lstat()
            except OSError as exc:
                raise Blocked(
                    f"physical control source directory missing at {phase}: {relative}"
                ) from exc
            if not stat.S_ISDIR(identity.st_mode) or \
                    identity.st_uid != os.geteuid() or \
                    stat.S_IMODE(identity.st_mode) != 0o700:
                raise Blocked(
                    f"physical control source directory unsafe at {phase}: {relative}")
        try:
            identity = path.lstat()
        except OSError as exc:
            raise Blocked(
                f"physical control source missing at {phase}: {relative}") from exc
        if not stat.S_ISREG(identity.st_mode) or \
                identity.st_uid != os.geteuid() or \
                stat.S_IMODE(identity.st_mode) != 0o400 or identity.st_nlink != 1:
            raise Blocked(
                f"physical control source identity unsafe at {phase}: {relative}")
        payload = _read_stable_relative_file_bytes(
            source_root, Path(relative),
            f"private physical control source {relative}")
        if hashlib.sha256(payload).hexdigest() != expected:
            raise Blocked(
                f"physical control source differs from validated commit at "
                f"{phase}: {relative}")

    # Enumerate transitive quoted includes. Angle includes are toolchain/system
    # headers, not worktree inputs: no -I, -include or inherited CPATH is used.
    for relative in PHYSICAL_CONTROL_INPUT_PATHS:
        if not relative.endswith((".c", ".h")):
            continue
        payload = _read_stable_relative_file_bytes(
            source_root, Path(relative),
            f"private source include graph {relative}")
        if hashlib.sha256(payload).hexdigest() != expected_hashes[relative]:
            raise Blocked(
                f"physical control source differs from validated commit at "
                f"{phase}: {relative}")
        for line in payload.splitlines():
            match = re.match(rb"^[ \t]*#[ \t]*(include|include_next)\b[ \t]*(.*)$", line)
            if match is None:
                continue
            directive, operand = match.groups()
            if directive != b"include" or not (
                    operand.startswith(b"<") and b">" in operand or
                    operand.startswith(b'"') and b'"' in operand[1:]):
                raise Blocked(
                    f"physical control has an unpinned include at {phase}: {relative}")
            if operand.startswith(b"<"):
                continue
            try:
                header = operand[1:operand.index(b'"', 1)].decode("ascii")
            except (UnicodeError, ValueError) as exc:
                raise Blocked(
                    f"physical control has an invalid include at {phase}: {relative}"
                ) from exc
            normalized = os.path.normpath(
                os.path.join(os.path.dirname(relative), header)).replace(os.sep, "/")
            if normalized not in expected_files or not normalized.endswith(".h"):
                raise Blocked(
                    f"physical control has an unpinned transitive header at "
                    f"{phase}: {relative} -> {header}")


def _physical_control_expected_dependencies(source_root: Path) -> set[Path]:
    return {
        Path(os.path.normpath(os.fspath(source_root / relative)))
        for relative in PHYSICAL_CONTROL_INPUT_PATHS
        if relative.endswith((".c", ".h"))
    }


def _verify_physical_compile_dependencies(
        source_root: Path, dependency_output: str) -> None:
    """Require the compiler's actual non-system dependency closure to be pinned."""
    if not isinstance(dependency_output, str) or "\x00" in dependency_output:
        raise Blocked("physical compile dependency output is malformed")
    logical_output = dependency_output.replace("\\\n", " ")
    observed: set[Path] = set()
    rule_count = 0
    for raw_line in logical_output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ":" not in line:
            raise Blocked("physical compile dependency output is malformed")
        target, dependencies = line.split(":", 1)
        if not target.strip():
            raise Blocked("physical compile dependency output is malformed")
        rule_count += 1
        for token in dependencies.split():
            # The private tempfile source paths have no Make escaping. Reject
            # escaped or relative paths rather than interpreting them loosely.
            if "\\" in token:
                raise Blocked("physical compile dependency path is escaped")
            dependency = Path(os.path.normpath(token))
            if not dependency.is_absolute():
                raise Blocked("physical compile dependency path is not absolute")
            observed.add(dependency)
    expected = _physical_control_expected_dependencies(source_root)
    if rule_count != 2 or observed != expected:
        raise Blocked(
            "physical compile dependency closure differs from pinned source inventory")


def build_physical_execution_control(validated_source: str,
                                     qualified_swapzctl: Path,
                                     private_directory: Path,
                                     source_root: Path = ROOT,
                                     expected_input_hashes: dict[str, str] | None = None
                                     ) -> tuple[Path, str]:
    """Build a noninstalled exact-source coordinator bound to qualified bytes."""
    if not re.fullmatch(r"[0-9a-f]{40}", validated_source):
        raise Blocked("validated source SHA is malformed")
    require_pinned_physical_control_inputs(
        source_root, private_directory, expected_input_hashes, "before_compile")
    try:
        qualified_control = qualified_swapzctl.resolve(strict=True)
    except OSError as exc:
        raise Blocked(f"cannot resolve qualified installed swapzctl: {exc}") from exc
    if not qualified_control.is_file():
        raise Blocked("qualified installed swapzctl is not a regular file")
    if qualified_control.name != "swapzctl" or qualified_control.parent.name != "sbin":
        raise Blocked("qualified control must use installed <prefix>/sbin/swapzctl layout")

    version_payload = _read_stable_relative_file_bytes(
        source_root, Path("src/kernel/VERSION"), "exact-source version")
    try:
        version = version_payload.decode("ascii").strip()
    except UnicodeError as exc:
        raise Blocked("exact-source version is not valid ASCII") from exc
    version_literal = _c_string_literal(version, "swapz version")
    control_literal = _c_string_literal(
        str(qualified_control), "qualified control path")
    source_literal = _c_string_literal(validated_source, "validated source SHA")

    private_directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    os.chmod(private_directory, 0o700)
    output = private_directory / "swapzctl"
    # These flags are part of the commit-bound helper bytes admitted by the
    # unprivileged parent. Reuse the exact tuple for dependency discovery and
    # compilation so include resolution cannot silently use different options.
    compile_flags = [
        "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
        f"-DSWAPZ_BUILD_SOURCE_SHA={source_literal}",
        "-DSWAPZ_BUILD_SOURCE_CLEAN=1",
        f"-DSWAPZ_VERSION={version_literal}",
        "-DSWAPZ_PRIMARY_PHYSICAL_QUALIFICATION_TEST=1",
        f"-DSWAPZ_PRIMARY_PHYSICAL_QUALIFIED_CONTROL={control_literal}",
    ]
    sources = [
        str(source_root / "src/userspace/swapzctl.c"),
        str(source_root / "src/userspace/swapz-primary.c"),
    ]
    dependency_result = _run(
        ["cc", *compile_flags, "-MM", *sources],
        check=False, timeout=120, cwd=private_directory)
    if dependency_result.returncode != 0:
        detail = (dependency_result.stderr or dependency_result.stdout).strip().replace(
            "\n", "; ")
        raise Blocked(
            "cannot resolve exact-source physical compile dependencies: " + detail)
    _verify_physical_compile_dependencies(
        source_root, dependency_result.stdout)
    command = ["cc", *compile_flags, *sources, "-o", str(output)]
    # The compiler must not resolve relative inputs against the mutable checkout.
    # System headers and toolchain are root-owned host prerequisites.
    result = _run(command, check=False, timeout=120, cwd=private_directory)
    require_pinned_physical_control_inputs(
        source_root, private_directory, expected_input_hashes, "after_compile")
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


def require_private_execution_artifact_identity(
        control_path: Path, oracle_path: Path,
        expected_control_sha256: str, expected_oracle_sha256: str,
        phase: str) -> None:
    """Retain exact root-owned runtime bytes between build, use and publication."""
    for label, path, expected in (
            ("coordinator", control_path, expected_control_sha256),
            ("oracle", oracle_path, expected_oracle_sha256)):
        if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise Blocked(f"private {label} artifact digest invalid at {phase}")
        if _sha256_file(path) != expected:
            raise Blocked(f"private {label} artifact changed at {phase}")


def qualification_artifact_hashes(
        report_path: Path, validated_source: str,
        expected_report_sha256: str | None = None) -> dict[str, str]:
    """Read artifact digests from one stable, optionally digest-pinned report."""
    payload = _read_stable_file_bytes(report_path, "qualification report")
    digest = hashlib.sha256(payload).hexdigest()
    if expected_report_sha256 is not None:
        if not isinstance(expected_report_sha256, str) or \
                re.fullmatch(r"[0-9a-f]{64}", expected_report_sha256) is None:
            raise Blocked("imported qualification report digest is malformed")
        if digest != expected_report_sha256:
            raise Blocked(
                "imported qualification report digest differs from supplied report")
    try:
        text_payload = payload.decode("utf-8")
    except UnicodeError as exc:
        raise Blocked("qualification report is not valid UTF-8") from exc
    report = _load_unique_json(text_payload, "qualification report")
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
        value = json.loads(
            text, object_pairs_hook=unique,
            parse_constant=_reject_nonfinite_json_constant,
            parse_float=_finite_json_float)
    except (ValueError, TypeError, RecursionError) as exc:
        raise Blocked(f"cannot parse {label}: {type(exc).__name__}") from exc
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


@dataclass(frozen=True)
class SelectorEvidence:
    """An admitted selector's bytes and filesystem identity."""

    partuuid: str
    identity: tuple[int, ...]


def _selector_identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _selector_inode_identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _qualification_failure_exit_status(error: QualificationFailure) -> int | None:
    match = re.match(r"command failed rc=(-?\d+):", str(error))
    return int(match.group(1)) if match is not None else None


def _reject_selector(phase: str, expected: str, observed: str,
                     original_errno: int | None = None,
                     original_status: int | None = None) -> None:
    status_detail = (
        f" status={original_status}" if original_status is not None else "")
    raise Blocked(
        f"primary selector phase={phase} expected={expected} observed={observed} "
        f"errno={original_errno if original_errno is not None else 'none'}"
        f"{status_detail}; "
        "action=BLOCK-before-prepare-and-inspect-protected-selector")


def _check_selector_info(info: os.stat_result, phase: str) -> None:
    expected = "root-owned-0600-regular-single-link"
    if not stat.S_ISREG(info.st_mode):
        _reject_selector(phase, expected, "nonregular")
    if info.st_uid != 0:
        _reject_selector(phase, expected, "owner-mismatch")
    if stat.S_IMODE(info.st_mode) != 0o600:
        _reject_selector(phase, expected, "mode-mismatch")
    if info.st_nlink != 1:
        _reject_selector(phase, expected, "link-count-mismatch")
    if info.st_size > SELECTOR_MAX_BYTES:
        _reject_selector(phase, "bounded-ASCII-selector", "oversized")


def _read_selector_evidence() -> SelectorEvidence:
    """Bind inspected path and final path to one opened descriptor.

    The context-managed file exclusively owns the O_NOFOLLOW/O_CLOEXEC
    descriptor. No independent pathname read supplies selection bytes.
    """
    try:
        inspected = SELECTOR.lstat()
    except OSError as exc:
        _reject_selector("inspect", "protected-selector", "stat-error", exc.errno)
    _check_selector_info(inspected, "inspect")
    inspected_identity = _selector_identity(inspected)

    phase = "open"
    try:
        selector_file = open(
            SELECTOR, "rb", buffering=0,
            opener=lambda path, flags: os.open(
                path, flags | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        )
        try:
            phase = "fstat"
            opened = os.fstat(selector_file.fileno())
            _check_selector_info(opened, phase)
            if _selector_identity(opened) != inspected_identity:
                _reject_selector(phase, "inspected-inode", "substituted-inode-or-metadata")

            phase = "read"
            payload = selector_file.read(SELECTOR_MAX_BYTES + 1)
            if len(payload) > SELECTOR_MAX_BYTES:
                _reject_selector(phase, "bounded-ASCII-selector", "oversized")
            if len(payload) != opened.st_size:
                _reject_selector(phase, "complete-opened-file", "truncated-or-changed")
            try:
                partuuid = parse_selector(payload.decode("ascii"))
            except (Blocked, UnicodeError) as exc:
                _reject_selector(phase, "single-ASCII-PARTUUID-line", "malformed")

            phase = "revalidate"
            reread_info = os.fstat(selector_file.fileno())
            pathname_info = SELECTOR.lstat()
            if _selector_inode_identity(pathname_info) != \
                    _selector_inode_identity(reread_info):
                _reject_selector(
                    phase, "opened-selector-inode", "replaced-selector-path")
            _check_selector_info(reread_info, phase)
            if _selector_identity(reread_info) != inspected_identity:
                _reject_selector(
                    phase, "unchanged-opened-inode", "changed-file-metadata")
            _check_selector_info(pathname_info, phase)
            if _selector_identity(pathname_info) != inspected_identity:
                _reject_selector(
                    phase, "unchanged-selector-metadata", "changed-path-metadata")
        finally:
            # The stream owns its descriptor; do not mask the first mismatch
            # or original errno if closing the descriptor also fails.
            first_error = sys.exc_info()[1]
            try:
                selector_file.close()
            except OSError as close_error:
                if first_error is None:
                    _reject_selector(
                        "close", "descriptor-bound-selector",
                        "io-error", close_error.errno)
    except OSError as exc:
        _reject_selector(phase, "descriptor-bound-selector", "io-error", exc.errno)

    return SelectorEvidence(partuuid, inspected_identity)


def _read_selector() -> str:
    return _read_selector_evidence().partuuid


def _require_selector_at_policy_use(
        expected: SelectorEvidence, plan: dict, authorization_snapshot: dict,
        target_device: tuple[int, int], parent_device: tuple[int, int]) -> None:
    """Reject stale selector or target admission before coordinator prepare."""
    observed = _read_selector_evidence()
    if observed != expected:
        _reject_selector("policy_use", "admitted-selector-identity",
                         "changed-selector-identity")
    try:
        _target_path, current_target, current_parent = verify_authorized_target(
            plan, expected.partuuid, authorization_snapshot)
    except QualificationFailure as exc:
        _reject_selector(
            "policy_use", "frozen-authorized-target-and-parent",
            "authorization-command-failed",
            original_status=_qualification_failure_exit_status(exc))
    except (Blocked, OSError, TypeError, ValueError) as exc:
        original_error = exc.__cause__ if isinstance(exc.__cause__, OSError) else exc
        _reject_selector(
            "policy_use", "frozen-authorized-target-and-parent",
            "authorization-unavailable-or-mismatch",
            getattr(original_error, "errno", None))
    if current_target != target_device or current_parent != parent_device:
        _reject_selector("policy_use", "admitted-target-and-parent",
                         "changed-target-or-parent")
    # Inspecting the live target can itself race a selector replacement.
    # End last-use admission with the same opened selector identity.
    if _read_selector_evidence() != expected:
        _reject_selector("policy_use", "admitted-selector-identity",
                         "changed-selector-after-target-inspection")




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
    info = _lstat_optional(path, "primary state file")
    if info is None:
        return None
    try:
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
    swap_uuid_text = (
        f"{swap_uuid[0:4].hex()}-{swap_uuid[4:6].hex()}-"
        f"{swap_uuid[6:8].hex()}-{swap_uuid[8:10].hex()}-"
        f"{swap_uuid[10:16].hex()}")
    return {"uuid": swap_uuid_text, "last_page": last_page, "version": version}


def _read_mapper_header(path: Path, logical_pages: int) -> dict:
    fd = -1
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOCTTY)
        header = os.pread(fd, PAGE_BYTES, 0)
    except OSError as exc:
        raise QualificationFailure(
            f"cannot independently read mapper swap header: {exc}") from exc
    finally:
        original_error = sys.exc_info()[1]
        if fd >= 0:
            try:
                os.close(fd)
            except OSError as cleanup_error:
                _raise_cleanup_errors(
                    original_error,
                    [f"mapper swap-header descriptor: {cleanup_error}"],
                    error_type=QualificationFailure)
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


def _sysfs_dm_names() -> set[str]:
    """Read the kernel's mapper-name inventory for an independent absence proof."""
    root = Path("/sys/class/block")
    try:
        entries = list(root.iterdir())
    except OSError as exc:
        raise Blocked(f"cannot enumerate kernel Device Mapper inventory: {exc}") from exc

    names: set[str] = set()
    for entry in entries:
        if not re.fullmatch(r"dm-[0-9]+", entry.name):
            continue
        try:
            name = (entry / "dm/name").read_text(encoding="ascii").strip()
        except OSError as exc:
            raise Blocked(
                f"cannot read kernel Device Mapper identity {entry.name}: {exc}") from exc
        if not name or name in names:
            raise Blocked("kernel Device Mapper name inventory is malformed")
        names.add(name)
    return names


def _dm_identity() -> DmIdentity | None:
    result = _run([
        "dmsetup", "info", "-c", "--noheadings", "--separator", ":",
        "-o", "name,uuid,major,minor,open", MAPPER_NAME,
    ], check=False, timeout=10)
    if result.returncode == 0:
        return parse_dm_info(result.stdout)
    # dmsetup uses a nonzero status both for an absent named mapper and for
    # control/query failures. Only an independent kernel inventory may turn
    # that ambiguous result into an absence observation.
    if MAPPER_NAME in _sysfs_dm_names():
        raise Blocked(
            "dmsetup could not query a primary mapper that remains present in sysfs")
    return None


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
    seen_keys: set[str] = set()
    for token in tokens[3:]:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        if key in seen_keys:
            raise QualificationFailure(f"duplicate swapz status token {key}")
        seen_keys.add(key)
        if re.fullmatch(r"-?[0-9]+", value):
            values[key] = int(value)
    counter_keys = ("logical_write", "logical_read", "physical_write", "physical_read")
    for key in (*counter_keys, "failed", "error"):
        if key not in values:
            raise QualificationFailure(f"swapz status lacks numeric token {key}")
    if any(values[key] < 0 for key in counter_keys) or values["failed"] not in {0, 1}:
        raise QualificationFailure("swapz status has invalid counter/failure values")
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
                if fields[0] in values:
                    raise ValueError("duplicate swap counter")
                values[fields[0]] = int(fields[1])
    except (OSError, ValueError) as exc:
        raise Blocked(f"cannot read /proc/vmstat swap counters: {exc}") from exc
    if set(values) != wanted or any(value < 0 for value in values.values()):
        raise Blocked("/proc/vmstat lacks valid swap counters")
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
            if fields[0] in values:
                raise ValueError("duplicate memory.events counter")
            values[fields[0]] = int(fields[1])
    except (OSError, ValueError) as exc:
        raise Blocked(f"cannot parse cgroup memory.events: {exc}") from exc
    if not {"oom", "oom_kill"}.issubset(values):
        raise Blocked("cgroup memory.events lacks required OOM counters")
    return values


def require_no_cgroup_oom_events(
        initial_events: dict[str, int], observed_events: dict[str, int]) -> None:
    """An OOM event or counter regression invalidates the dedicated workload."""
    if any(observed_events[key] != initial_events[key]
           for key in ("oom", "oom_kill")):
        raise QualificationFailure(
            "cgroup OOM counters changed during admitted real-swap workload")


def _psi_total(path: Path, kind: str = "some") -> int:
    observed: int | None = None
    try:
        for line in path.read_text(encoding="ascii").splitlines():
            fields = line.split()
            if not fields or fields[0] != kind:
                continue
            if observed is not None:
                raise ValueError(f"duplicate PSI {kind} row")
            totals = [
                field.split("=", 1)[1]
                for field in fields[1:] if field.startswith("total=")
            ]
            if len(totals) != 1 or not re.fullmatch(r"[0-9]+", totals[0]):
                raise ValueError(f"malformed PSI {kind} total")
            observed = int(totals[0])
    except (OSError, ValueError) as exc:
        raise Blocked(f"cannot parse cgroup PSI: {exc}") from exc
    if observed is None:
        raise Blocked("cgroup PSI lacks total counter")
    return observed


def _mem_available_mib() -> int:
    observed_kib: int | None = None
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            fields = line.split()
            if fields[:1] != ["MemAvailable:"]:
                continue
            if observed_kib is not None or len(fields) != 3 or fields[2] != "kB" or \
                    not re.fullmatch(r"[0-9]+", fields[1]):
                raise ValueError("malformed or duplicate MemAvailable")
            observed_kib = int(fields[1])
    except (OSError, ValueError) as exc:
        raise Blocked(f"cannot read MemAvailable: {exc}") from exc
    if observed_kib is None:
        raise Blocked("MemAvailable is unavailable")
    return observed_kib // 1024


def _block_size(path: Path) -> int:
    fd = -1
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOCTTY)
        return struct.unpack(
            "=Q", fcntl.ioctl(fd, BLKGETSIZE64, bytes(8)))[0]
    except OSError as exc:
        raise Blocked(f"cannot verify block geometry for {path}: {exc}") from exc
    finally:
        original_error = sys.exc_info()[1]
        if fd >= 0:
            try:
                os.close(fd)
            except OSError as cleanup_error:
                _raise_cleanup_errors(
                    original_error,
                    [f"block-geometry descriptor: {cleanup_error}"],
                    error_type=Blocked)


def _flatten_lsblk(rows: list[dict]) -> list[dict]:
    if not isinstance(rows, list):
        raise Blocked("lsblk blockdevices inventory is not a list")
    result: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            raise Blocked("lsblk topology row is not an object")
        result.append(row)
        children = row.get("children")
        if children is not None:
            if not isinstance(children, list):
                raise Blocked("lsblk topology children are not a list")
            result.extend(_flatten_lsblk(children))
    return result


def parse_lsblk_topology(text: str) -> list[dict]:
    topology = _load_unique_json(text, "lsblk topology")
    rows = topology.get("blockdevices")
    if not isinstance(rows, list):
        raise Blocked("lsblk topology lacks blockdevices list")
    return _flatten_lsblk(rows)


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


def _read_readiness_snapshot(
        path: Path = AUTHORIZATION_SNAPSHOT,
        expected_sha256: str | None = None) -> tuple[dict, str]:
    payload = _read_stable_file_bytes(
        path, "production readiness snapshot")
    try:
        text_payload = payload.decode("utf-8")
    except UnicodeError as exc:
        raise Blocked(
            "production readiness snapshot is not valid UTF-8") from exc
    observed = hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None and observed != expected_sha256:
        raise Blocked(
            "production readiness snapshot differs from validated commit at policy_use")
    snapshot = _load_unique_json(
        text_payload, "production readiness snapshot")
    return snapshot, observed


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


def _verify_acceptance_manifest_snapshot(
        *, cycles: int, workload_mib: int, resident_mib: int,
        swap_limit_mib: int, timeout_seconds: int,
        path: Path = ACCEPTANCE_MANIFEST,
        expected_sha256: str | None = None) -> tuple[dict, str]:
    payload = _read_stable_file_bytes(
        path, "production acceptance manifest")
    try:
        text_payload = payload.decode("utf-8")
    except UnicodeError as exc:
        raise Blocked(
            "production acceptance manifest is not valid UTF-8") from exc
    observed = hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None and observed != expected_sha256:
        raise Blocked(
            "production acceptance manifest differs from validated commit at policy_use")
    manifest = _load_unique_json(text_payload, "production acceptance manifest")
    accepted = validate_acceptance_manifest(
        manifest, cycles=cycles, workload_mib=workload_mib,
        resident_mib=resident_mib, swap_limit_mib=swap_limit_mib,
        timeout_seconds=timeout_seconds)
    return accepted, observed


def verify_acceptance_manifest(
        *, cycles: int, workload_mib: int, resident_mib: int,
        swap_limit_mib: int, timeout_seconds: int) -> dict:
    accepted, _digest = _verify_acceptance_manifest_snapshot(
        cycles=cycles, workload_mib=workload_mib,
        resident_mib=resident_mib, swap_limit_mib=swap_limit_mib,
        timeout_seconds=timeout_seconds)
    return accepted


def acceptance_manifest_sha256() -> str:
    """Hash the current stable frozen-policy pathname."""
    return _sha256_file(ACCEPTANCE_MANIFEST)


def verify_authorized_target(
        plan: dict, selector_partuuid: str,
        authorization_snapshot: dict | None = None,
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
    rows = parse_lsblk_topology(result.stdout)
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
        if authorization_snapshot is None:
            authorization_snapshot, _snapshot_digest = \
                _read_readiness_snapshot()
        authorized = authorization_snapshot["authorized_target"]
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


def _read_installed_plan(swapzctl: Path) -> dict:
    result = _run(
        [str(swapzctl), "primary", "plan"], check=False, timeout=30)
    if not result.stdout.strip():
        raise Blocked("installed primary plan produced no JSON")
    return _load_unique_json(
        result.stdout.strip(), "installed primary plan")


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
    report_digest = plan.get("qualification_report_sha256")
    if not isinstance(report_digest, str) or \
            re.fullmatch(r"[0-9a-f]{64}", report_digest) is None:
        raise Blocked("imported qualification report digest is malformed")
    report_hashes = qualification_artifact_hashes(
        report_path, validated_source, report_digest)
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
        _trusted_executable(name)


def _validate_precycle_state(
        partuuid: str, target_device: tuple[int, int],
        parent_device: tuple[int, int],
        baseline: list[SwapRow]) -> dict | None:
    state = read_state()
    if state is not None and state.get("stage") != "COMPLETE":
        raise Blocked(f"unresolved primary state {state.get('stage')}")
    marker = RECOVERY_BASE / f"partition-{partuuid}.active"
    if _path_present(marker, "primary partition ownership marker"):
        raise Blocked("selected partition already has an active ownership marker")
    if _dm_identity() is not None:
        raise Blocked("primary mapper already exists before cycle")
    require_no_conflicting_raw_swap_aliases(
        baseline, target_device, parent_device)
    if _path_present(Path("/sys/module/dm_swapz"), "dm_swapz module sysfs state"):
        raise Blocked("dm_swapz is already loaded before primary cycle")
    return state


def _read_primary_output(result: subprocess.CompletedProcess[str], prefix: str) -> str:
    for line in result.stdout.splitlines():
        if line.startswith(prefix):
            return line
    raise QualificationFailure(f"primary command omitted expected marker {prefix}")


def _primary(swapzctl: Path, action: str, timeout: float, *, admitted: bool = False) -> subprocess.CompletedProcess[str]:
    environment = _safe_child_environment(
        _physical_control_environment())
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
            if _lstat_optional(
                    cgroup / name, f"cgroup control {name}",
                    error_type) is None:
                raise error_type(f"dedicated cgroup lacks required control {name}")
        _write_control(cgroup / "memory.max", str(resident_mib * MIB), admitted=admitted)
        _write_control(cgroup / "memory.swap.max", str(swap_limit_mib * MIB), admitted=admitted)
        _write_control(cgroup / "memory.zswap.max", "0", admitted=admitted)
        if _lstat_optional(
                cgroup / "memory.oom.group", "cgroup control memory.oom.group",
                error_type) is not None:
            _write_control(cgroup / "memory.oom.group", "1", admitted=admitted)
        return cgroup
    except BaseException as original_error:
        if created:
            # This admission path has not launched any workers. Even if the
            # kernel process file became unreadable, try an ordinary rmdir:
            # cgroup v2 refuses to remove a group still containing processes.
            inspection_error = None
            try:
                if (cgroup / "cgroup.procs").read_text(encoding="ascii").strip():
                    raise error_type("partially created cgroup unexpectedly contains processes")
            except OSError as exc:
                inspection_error = exc
            except Exception as cleanup_error:
                raise error_type(
                    f"{original_error}; partial cgroup cleanup also failed: "
                    f"{cleanup_error}") from original_error
            try:
                cgroup.rmdir()
            except OSError as cleanup_error:
                inspection_detail = (
                    f"process inventory unavailable: {inspection_error}; "
                    if inspection_error is not None else "")
                raise error_type(
                    f"{original_error}; partial cgroup cleanup also failed: "
                    f"{inspection_detail}{cleanup_error}") from original_error
            if inspection_error is not None:
                raise error_type(
                    f"{original_error}; cgroup was removed despite unreadable "
                    f"process inventory: {inspection_error}") from original_error
        raise


def _raise_cleanup_errors(original_error: BaseException | None,
                          errors: list[str], *,
                          error_type: type[Exception] = QualificationFailure) -> None:
    """Keep the initiating failure visible when teardown also fails."""
    if not errors:
        return
    disposition = Blocked if isinstance(original_error, Blocked) else error_type
    details = "; ".join(errors)
    if original_error is not None:
        raise disposition(f"{original_error}; cleanup also failed: {details}") from original_error
    raise disposition(f"cleanup failed: {details}")


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
        initial_events = _memory_events(cgroup / "memory.events")
        if any(initial_events[key] != 0 for key in ("oom", "oom_kill")):
            raise Blocked("fresh preflight cgroup has preexisting OOM events")
        _psi_total(cgroup / "memory.pressure")
    finally:
        original_error = sys.exc_info()[1]
        try:
            _remove_cgroup(cgroup)
        except Exception as cleanup_error:
            _raise_cleanup_errors(
                original_error, [f"preflight cgroup: {cleanup_error}"],
                error_type=Blocked)


def _remove_cgroup(cgroup: Path) -> None:
    if _lstat_optional(
            cgroup, "dedicated real-swap cgroup",
            QualificationFailure) is None:
        return
    try:
        procs = (cgroup / "cgroup.procs").read_text(encoding="ascii").split()
    except OSError as inspection_error:
        # Ordinary cgroup rmdir is a safe independent emptiness check: the
        # kernel refuses a non-empty cgroup. Do not leave an empty group behind
        # merely because its process inventory became unreadable.
        try:
            cgroup.rmdir()
        except OSError as cleanup_error:
            raise QualificationFailure(
                f"cannot inspect dedicated real-swap cgroup processes: "
                f"{inspection_error}; empty-group removal also failed: "
                f"{cleanup_error}") from cleanup_error
        raise QualificationFailure(
            "dedicated real-swap cgroup process inventory was unreadable; "
            f"empty cgroup was removed: {inspection_error}") from inspection_error
    if procs:
        raise QualificationFailure(
            "dedicated real-swap cgroup still has processes; "
            "no force cleanup attempted")
    try:
        cgroup.rmdir()
    except OSError as exc:
        raise QualificationFailure(
            f"cannot remove empty real-swap cgroup: {exc}") from exc


def _read_oracle_cgroup_members(cgroup: Path) -> set[int]:
    try:
        raw_processes = (cgroup / "cgroup.procs").read_text(
            encoding="ascii").split()
    except OSError as exc:
        raise QualificationFailure(
            "cannot read dedicated oracle cgroup membership") from exc
    if any(not re.fullmatch(r"[1-9][0-9]*", value) for value in raw_processes):
        raise QualificationFailure(
            "dedicated oracle cgroup has malformed process identity")
    observed = {int(value) for value in raw_processes}
    if len(observed) != len(raw_processes):
        raise QualificationFailure(
            "dedicated oracle cgroup has duplicate process identity")
    return observed


def require_oracle_worker_cgroup_ownership(
        cgroup: Path, processes: list[subprocess.Popen], *,
        allow_worker_exit: bool = False) -> None:
    """Require exact live-worker membership and no foreign cgroup members."""
    expected = {process.pid for process in processes}
    if len(expected) != len(processes):
        raise QualificationFailure("owned oracle worker PIDs are not unique")
    # Each owned worker can transition from live to exited only once. Allow
    # one fresh membership read per such transition plus the initial sample.
    attempts = len(processes) + 1 if allow_worker_exit else 1
    for attempt in range(attempts):
        observed = _read_oracle_cgroup_members(cgroup)
        membership_valid = (
            observed.issubset(expected)
            if allow_worker_exit else observed == expected)
        if not membership_valid:
            raise QualificationFailure(
                "dedicated oracle cgroup membership differs from owned worker PIDs")
        states = {process.pid: process.poll() for process in processes}
        if not allow_worker_exit:
            if any(state is not None for state in states.values()):
                raise QualificationFailure(
                    "oracle worker exited before verification was allowed")
            return
        if any(pid not in observed and states[pid] is None for pid in expected):
            raise QualificationFailure(
                "live oracle worker left dedicated cgroup during verification")
        exited_present = [
            pid for pid in expected
            if pid in observed and states[pid] is not None
        ]
        if not exited_present:
            return
        # The first snapshot may precede a normal exit by a few instructions.
        # Re-read after poll() made the exit definite. A terminal worker PID
        # that remains in the fresh snapshot is recycled/foreign membership.
        if attempt + 1 == attempts:
            raise QualificationFailure(
                "exited oracle PID is present in dedicated cgroup")


def _close_oracle_pipes(process: subprocess.Popen) -> None:
    """Release all parent-owned pipe descriptors after failed worker admission."""
    errors = []
    for pipe in (process.stdin, process.stdout, process.stderr):
        if pipe is not None:
            try:
                pipe.close()
            except OSError as exc:
                errors.append(str(exc))
    if errors:
        raise QualificationFailure("oracle pipe cleanup failed: " + "; ".join(errors))


def _terminate_child(process: subprocess.Popen, cgroup: Path) -> None:
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


_ORACLE_FAILURE_SUMMARY_RE = re.compile(
    r"(?:FAIL|BLOCKED): oracle phase=[a-z_]+ "
    r"verified_pages=[0-9]+/[0-9]+ verified_bytes=[0-9]+/[0-9]+ "
    r"expected_page_mismatches=0 observed_page_mismatches=[0-9]+ "
    r"expected_byte_mismatches=0 observed_byte_mismatches=[0-9]+ "
    r"error=[A-Za-z_][A-Za-z0-9_]* errno=(?:none|[0-9]+) "
    r"cleanup_complete=(?:true|false)"
)


def _bounded_oracle_failure_summary(process: subprocess.Popen) -> str:
    """Expose only a complete structured oracle failure/refusal, never raw stderr."""
    if process.stderr is None:
        return ""
    try:
        diagnostic = process.stderr.read(MAX_ORACLE_RECORD_BYTES + 1)
    except (OSError, ValueError):
        return ""
    if len(diagnostic) > MAX_ORACLE_RECORD_BYTES:
        diagnostic = diagnostic[:MAX_ORACLE_RECORD_BYTES]
    for line in reversed(diagnostic.splitlines()):
        if _ORACLE_FAILURE_SUMMARY_RE.fullmatch(line):
            return line
    return ""


def _raise_oracle_event_failure(
        process: subprocess.Popen, prefix: str, return_code: int,
        reason: str) -> None:
    """Preserve only an authenticated pre-readiness BLOCKED child refusal."""
    summary = _bounded_oracle_failure_summary(process)
    detail = f": {summary}" if summary else ""
    message = (
        f"real-swap oracle phase=terminal child_exit={return_code} "
        f"evidence_complete=false: {reason}{detail}")
    if (return_code == 2 and prefix == "ORACLE_WAITING=" and
            summary.startswith("BLOCKED: oracle phase=preflight ")):
        raise Blocked(message)
    raise QualificationFailure(message)


def _oracle_event(process: subprocess.Popen, prefix: str, deadline: float,
                  guard: Callable[[], None], pending: bytearray) -> dict:
    """Consume bounded records without TextIO/select buffering races.

    A single os.read may contain multiple records; keep unread bytes for the
    next phase. Buffered readline can block on incomplete records and hide
    already-buffered records from a subsequent select call.
    """
    if process.stdout is None:
        raise QualificationFailure("oracle stdout pipe is unavailable")
    fd = process.stdout.fileno()
    prefix_bytes = prefix.encode("ascii")
    while True:
        guard()
        if b"\n" in pending:
            record, _, remainder = pending.partition(b"\n")
            pending[:] = remainder
            if len(record) > MAX_ORACLE_RECORD_BYTES or not record.startswith(prefix_bytes):
                raise QualificationFailure("real-swap oracle emitted unexpected or oversized record")
            try:
                value = json.loads(
                    record[len(prefix_bytes):].decode("ascii"),
                    object_pairs_hook=_unique_json_object,
                    parse_constant=_reject_nonfinite_json_constant,
                    parse_float=_finite_json_float)
            except (UnicodeError, ValueError, TypeError) as exc:
                raise QualificationFailure("real-swap oracle emitted malformed JSON") from exc
            if not isinstance(value, dict):
                raise QualificationFailure("real-swap oracle record is not an object")
            return value
        if len(pending) > MAX_ORACLE_RECORD_BYTES:
            raise QualificationFailure("real-swap oracle emitted oversized unterminated record")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return_code = process.poll()
            if return_code is not None:
                _raise_oracle_event_failure(
                    process, prefix, return_code, f"exited before {prefix}")
            raise QualificationFailure(
                "real-swap oracle phase=terminal child_exit=running "
                f"evidence_complete=false: timed out waiting for {prefix}")
        try:
            readable, _, _ = select.select(
                [fd], [], [], min(0.1, remaining))
        except (OSError, ValueError) as exc:
            return_code = process.poll()
            child_exit = return_code if return_code is not None else "running"
            original_errno = getattr(exc, "errno", None)
            raise QualificationFailure(
                f"real-swap oracle phase=terminal child_exit={child_exit} "
                f"evidence_complete=false: cannot wait for {prefix} "
                f"errno={original_errno if original_errno is not None else 'none'}"
            ) from exc
        if not readable:
            return_code = process.poll()
            if return_code is not None:
                _raise_oracle_event_failure(
                    process, prefix, return_code, f"exited before {prefix}")
            continue
        try:
            chunk = os.read(fd, MAX_ORACLE_RECORD_BYTES + 1)
        except OSError as exc:
            return_code = process.poll()
            child_exit = return_code if return_code is not None else "running"
            original_errno = exc.errno if exc.errno is not None else "none"
            raise QualificationFailure(
                f"real-swap oracle phase=terminal child_exit={child_exit} "
                f"evidence_complete=false: cannot read real-swap oracle record "
                f"errno={original_errno}") from exc
        if not chunk:
            return_code = process.poll()
            if return_code is not None:
                _raise_oracle_event_failure(
                    process, prefix, return_code,
                    f"closed output before {prefix}")
            raise QualificationFailure(
                "real-swap oracle phase=terminal child_exit=running "
                f"evidence_complete=false: closed output before {prefix}")
        pending.extend(chunk)


def _require_oracle_terminal_exit(
        process: subprocess.Popen, deadline: float,
        guard: Callable[[], None], pending: bytearray) -> None:
    """Require zero exit and EOF after the one accepted terminal record."""
    if process.stdout is None:
        raise QualificationFailure("oracle stdout pipe is unavailable")
    try:
        return_code = process.wait(
            timeout=max(1, int(deadline - time.monotonic())))
    except subprocess.TimeoutExpired as exc:
        raise QualificationFailure(
            "real-swap oracle phase=terminal child_exit=timeout "
            "evidence_complete=false: did not exit after byte verification") from exc
    if return_code != 0:
        summary = _bounded_oracle_failure_summary(process)
        detail = f": {summary}" if summary else ""
        raise QualificationFailure(
            f"real-swap oracle phase=terminal child_exit={return_code} "
            f"evidence_complete=false{detail}")

    guard()
    if pending:
        raise QualificationFailure(
            "real-swap oracle phase=terminal child_exit=0 "
            "evidence_complete=false: trailing output after ORACLE_VERIFIED")
    stdout_fd = process.stdout.fileno()
    try:
        readable, _, _ = select.select([stdout_fd], [], [], 0)
    except (OSError, ValueError) as exc:
        raise QualificationFailure(
            "real-swap oracle phase=terminal child_exit=0 "
            "evidence_complete=false: cannot confirm terminal EOF") from exc
    if not readable:
        raise QualificationFailure(
            "real-swap oracle phase=terminal child_exit=0 "
            "evidence_complete=false: cannot confirm terminal EOF")
    try:
        trailing = os.read(stdout_fd, MAX_ORACLE_RECORD_BYTES + 1)
    except OSError as exc:
        raise QualificationFailure(
            "real-swap oracle phase=terminal child_exit=0 "
            "evidence_complete=false: cannot confirm terminal EOF") from exc
    if trailing:
        raise QualificationFailure(
            "real-swap oracle phase=terminal child_exit=0 "
            "evidence_complete=false: trailing output after ORACLE_VERIFIED")


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
    oracle_digest = oracle.get("digest")
    if expected_verified_pages <= 0 or \
            oracle.get("verified_pages") != expected_verified_pages or \
            oracle.get("verified_bytes") != expected_verified_pages * PAGE_BYTES or \
            oracle.get("mismatches") != 0 or \
            not isinstance(oracle_digest, str) or \
            re.fullmatch(r"[0-9a-f]{64}", oracle_digest) is None or \
            oracle_digest != oracle.get("expected_digest"):
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
        if not isinstance(record, dict) or \
                type(record.get(page_field)) is not int or \
                type(record.get(byte_field)) is not int or \
                record[page_field] != expected_pages or \
                record[byte_field] != expected_bytes:
            raise QualificationFailure(
                f"concurrent oracle worker {worker_index} {phase} page/byte count is incomplete")


def require_oracle_verification_details(records: list[dict]) -> None:
    """Validate full mismatch totals independently of capped diagnostics."""
    for worker_index, record in enumerate(records):
        required_integer_fields = (
            "verified_pages", "verified_bytes", "mismatched_pages", "mismatches")
        if not isinstance(record, dict) or any(
                type(record.get(key)) is not int
                for key in required_integer_fields):
            raise QualificationFailure(
                f"concurrent oracle worker {worker_index} "
                "verification mismatch totals are malformed")

        verified_pages = record["verified_pages"]
        verified_bytes = record["verified_bytes"]
        mismatched_pages = record["mismatched_pages"]
        mismatched_bytes = record["mismatches"]
        mismatch_samples = record.get("mismatch_samples")
        expected_sample_count = min(
            mismatched_pages, MAX_ORACLE_MISMATCH_SAMPLES)
        mismatch_evidence_valid = (
            verified_pages > 0 and
            verified_bytes == verified_pages * PAGE_BYTES and
            0 <= mismatched_pages <= verified_pages and
            mismatched_pages <= mismatched_bytes <= mismatched_pages * PAGE_BYTES and
            isinstance(mismatch_samples, list) and
            len(mismatch_samples) == expected_sample_count
        )
        if not mismatch_evidence_valid:
            raise QualificationFailure(
                f"concurrent oracle worker {worker_index} "
                "verification mismatch evidence is inconsistent")

        previous_page = -1
        for sample in mismatch_samples:
            sample_valid = (
                isinstance(sample, dict) and
                set(sample) == {"page", "byte"} and
                type(sample["page"]) is int and
                type(sample["byte"]) is int and
                previous_page < sample["page"] < verified_pages and
                0 <= sample["byte"] < PAGE_BYTES
            )
            if not sample_valid:
                raise QualificationFailure(
                    f"concurrent oracle worker {worker_index} "
                    "verification mismatch sample is malformed")
            previous_page = sample["page"]


def aggregate_oracle_verification(records: list[dict]) -> dict:
    if len(records) != CONCURRENT_ORACLE_PROCESSES:
        raise QualificationFailure("concurrent oracle verification record count is incomplete")
    observed_digest = hashlib.sha256()
    expected_digest = hashlib.sha256()
    verified_pages = 0
    verified_bytes = 0
    mismatches = 0
    for record in records:
        if not isinstance(record, dict) or any(
                type(record.get(key)) is not int
                for key in ("verified_pages", "verified_bytes", "mismatches")) or any(
                not isinstance(record.get(key), str) or
                re.fullmatch(r"[0-9a-f]{64}", record[key]) is None
                for key in ("digest", "expected_digest")):
            raise QualificationFailure("concurrent oracle verification record is malformed")
        pages = record["verified_pages"]
        byte_count = record["verified_bytes"]
        mismatch_count = record["mismatches"]
        if pages <= 0 or byte_count != pages * PAGE_BYTES or mismatch_count < 0:
            raise QualificationFailure("concurrent oracle verification geometry/digest is invalid")
        observed_bytes = bytes.fromhex(record["digest"])
        expected_bytes = bytes.fromhex(record["expected_digest"])
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
                  timeout_seconds: int,
                  telemetry_check: Callable[[], None] | None = None) -> dict:
    worker_memory_mib = split_concurrent_workload_mib(workload_mib)
    token = os.urandom(8).hex()
    cgroup = _cgroup_create(token, resident_mib, swap_limit_mib, admitted=True)
    # The first telemetry read may fail before the workload's main try/finally.
    try:
        events_before = _memory_events(cgroup / "memory.events")
        # A newly created dedicated cgroup must start at zero: accepting a
        # nonzero baseline would conceal an OOM before the first fill sample.
        if any(events_before[key] != 0 for key in ("oom", "oom_kill")):
            raise QualificationFailure(
                "fresh dedicated oracle cgroup already recorded OOM events")
        psi_before = _psi_total(cgroup / "memory.pressure")
    except BaseException as original_error:
        try:
            _remove_cgroup(cgroup)
        except Exception as cleanup_error:
            _raise_cleanup_errors(
                original_error, [f"initial telemetry cgroup: {cleanup_error}"])
        raise
    psi_window = PsiStallWindow(time.monotonic(), psi_before)
    rounds: list[dict] = []
    active_processes: list[subprocess.Popen] = []
    guard_processes: list[subprocess.Popen] | None = None
    guard_allow_worker_exit = False

    def guard() -> None:
        if telemetry_check is not None:
            telemetry_check()
        if guard_processes is not None:
            require_oracle_worker_cgroup_ownership(
                cgroup, guard_processes,
                allow_worker_exit=guard_allow_worker_exit)
        require_no_cgroup_oom_events(
            events_before, _memory_events(cgroup / "memory.events"))
        if _read_uint(cgroup / "memory.swap.current") > swap_limit_mib * MIB:
            raise QualificationFailure("cgroup exceeded configured swap-usage bound")
        if _mem_available_mib() < MIN_AVAILABLE_MIB:
            raise QualificationFailure(
                f"host MemAvailable crossed {MIN_AVAILABLE_MIB} MiB early-stop threshold")
        current_psi_total = _psi_total(cgroup / "memory.pressure")
        if psi_window.observe(time.monotonic(), current_psi_total):
            raise QualificationFailure(
                "sustained cgroup memory PSI exceeded safe stop threshold")

    oracle_python = _trusted_executable_path(
        sys.executable, "running Python interpreter")
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
                        [oracle_python, "-I", "-B", str(oracle_path),
                         "--seed", seed, "--memory-mib", str(memory_mib)],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, bufsize=1,
                        env=_safe_child_environment(),
                    )
                    # Own the worker and descriptors before cgroup migration.
                    round_processes.append(process)
                    active_processes.append(process)
                    try:
                        (cgroup / "cgroup.procs").write_text(
                            f"{process.pid}\n", encoding="ascii")
                    except OSError as exc:
                        # A security-preflight refusal can exit before this
                        # migration races the child. Preserve only the same
                        # authenticated BLOCKED refusal on Linux's ESRCH;
                        # every other cgroup ownership failure stays fatal.
                        if exc.errno == errno.ESRCH:
                            return_code = process.poll()
                            if return_code is not None:
                                _raise_oracle_event_failure(
                                    process, "ORACLE_WAITING=", return_code,
                                    "exited before dedicated cgroup migration")
                        raise QualificationFailure(
                            "cannot move admitted oracle into dedicated cgroup "
                            f"errno={exc.errno if exc.errno is not None else 'none'}") from exc

                guard_processes = round_processes
                # Before readiness, an oracle may fail its own security
                # preflight and exit. Permit only exited workers to disappear
                # here so _oracle_event() can preserve a structured BLOCKED
                # refusal; live-worker escape and foreign membership still fail.
                guard_allow_worker_exit = True
                deadline = time.monotonic() + timeout_seconds
                oracle_buffers = {process.pid: bytearray() for process in round_processes}
                waiting = [
                    _oracle_event(process, "ORACLE_WAITING=", deadline, guard,
                                  oracle_buffers[process.pid])
                    for process in round_processes
                ]
                guard_allow_worker_exit = False
                if any(type(record.get("pid")) is not int for record in waiting):
                    raise QualificationFailure(
                        "concurrent oracle readiness PID identity is malformed")
                waiting_pids = [record["pid"] for record in waiting]
                if len(set(waiting_pids)) != CONCURRENT_ORACLE_PROCESSES or \
                        waiting_pids != [process.pid for process in round_processes] or \
                        any(record.get("seed") != seed
                            for record, seed in zip(waiting, worker_seeds)):
                    raise QualificationFailure("concurrent oracle readiness PID/seed identities differ")
                expected_pages = workload_mib * MIB // PAGE_BYTES
                require_oracle_worker_geometry(
                    waiting, worker_memory_mib, "pages", "bytes", "readiness")
                require_oracle_worker_cgroup_ownership(cgroup, round_processes)

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
                    _oracle_event(process, "ORACLE_FILLED=", deadline, guard,
                                  oracle_buffers[process.pid])
                    for process in round_processes
                ]
                require_oracle_worker_geometry(
                    filled_records, worker_memory_mib, "pages", "bytes", "fill")
                if any(not isinstance(record.get("digest"), str) or
                       re.fullmatch(r"[0-9a-f]{64}", record["digest"]) is None
                       for record in filled_records):
                    raise QualificationFailure("concurrent oracle fill digests are malformed")
                require_oracle_worker_cgroup_ownership(cgroup, round_processes)

                swap_current = _read_uint(cgroup / "memory.swap.current")
                swap_peak = _read_uint(cgroup / "memory.swap.peak")
                if swap_peak < swap_current:
                    raise QualificationFailure(
                        "cgroup swap peak is below current swap usage")
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
                require_oracle_worker_cgroup_ownership(
                    cgroup, round_processes)
                # A worker may exit immediately after emitting VERIFIED.
                # From this point the live set may shrink, but no foreign PID
                # may enter the dedicated cgroup.
                guard_allow_worker_exit = True
                for process in round_processes:
                    if process.stdin is None:
                        raise QualificationFailure("oracle command pipe is unavailable")
                    process.stdin.write("VERIFY\n")
                    process.stdin.flush()
                verified_records = [
                    _oracle_event(process, "ORACLE_VERIFIED=", deadline, guard,
                                  oracle_buffers[process.pid])
                    for process in round_processes
                ]
                require_oracle_worker_geometry(
                    verified_records, worker_memory_mib,
                    "verified_pages", "verified_bytes", "verification")
                require_oracle_verification_details(verified_records)
                if any(filled.get("digest") != verified.get("expected_digest")
                       for filled, verified in zip(filled_records, verified_records)):
                    raise QualificationFailure(
                        "oracle fill digest differs from expected verification digest")
                for process in round_processes:
                    _require_oracle_terminal_exit(
                        process, deadline, guard, oracle_buffers[process.pid])

                guard_processes = None
                guard_allow_worker_exit = False
                require_oracle_worker_cgroup_ownership(cgroup, [])
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
                guard_processes = None
                guard_allow_worker_exit = False
                original_error = sys.exc_info()[1]
                cleanup_errors = []
                for process in round_processes:
                    process_cleanup_failed = False
                    try:
                        _terminate_child(process, cgroup)
                    except Exception as cleanup_error:
                        process_cleanup_failed = True
                        cleanup_errors.append(
                            f"oracle pid {process.pid} termination: {cleanup_error}")
                    try:
                        _close_oracle_pipes(process)
                    except Exception as cleanup_error:
                        process_cleanup_failed = True
                        cleanup_errors.append(
                            f"oracle pid {process.pid} pipes: {cleanup_error}")
                    if process in active_processes and not process_cleanup_failed:
                        active_processes.remove(process)
                _raise_cleanup_errors(original_error, cleanup_errors)

            if round_result is None:
                raise QualificationFailure("real-swap round ended without evidence")
            release = _wait_for_round_release(
                cgroup, active["mapper_device"], expected_before.used_kib,
                time.monotonic() + min(timeout_seconds, 30), guard)
            round_result.update(release)
            rounds.append(round_result)

        reuse = evaluate_reuse_rounds(rounds)
        events_after = _memory_events(cgroup / "memory.events")
        # Do not trust a previously clean guard observation as terminal proof.
        require_no_cgroup_oom_events(events_before, events_after)
        psi_after = _psi_total(cgroup / "memory.pressure")
        if psi_window.observe(time.monotonic(), psi_after):
            raise QualificationFailure(
                "sustained cgroup memory PSI exceeded safe stop threshold")
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
        original_error = sys.exc_info()[1]
        cleanup_errors = []
        for process in list(active_processes):
            try:
                _terminate_child(process, cgroup)
            except Exception as cleanup_error:
                cleanup_errors.append(
                    f"oracle pid {process.pid} termination: {cleanup_error}")
            try:
                _close_oracle_pipes(process)
            except Exception as cleanup_error:
                cleanup_errors.append(
                    f"oracle pid {process.pid} pipes: {cleanup_error}")
        try:
            _remove_cgroup(cgroup)
        except Exception as cleanup_error:
            cleanup_errors.append(f"dedicated cgroup: {cleanup_error}")
        _raise_cleanup_errors(original_error, cleanup_errors)


def _mapper_sysfs_state(device: tuple[int, int], expected_uuid: str) -> tuple[bool, bool]:
    base = Path(f"/sys/dev/block/{device[0]}:{device[1]}")
    if _lstat_optional(base, "primary mapper sysfs device") is None:
        return False, True
    uuid_path = base / "dm/uuid"
    try:
        observed = uuid_path.read_text(encoding="ascii").strip()
    except OSError:
        return True, False
    return True, observed == expected_uuid


class StopOrderTracker:
    """Constant-memory proof of active -> swapoff -> mapper removal ordering."""

    def __init__(self):
        self.phase = 0  # 0: none; 1: active; 2: swapoff; 3: removed
        self.last_timestamp = -1
        self.sample_count = 0

    def observe(self, sample: StopSample) -> None:
        if sample.monotonic_ns <= self.last_timestamp:
            raise Blocked("stop sampler timestamps are not strictly increasing")
        self.last_timestamp = sample.monotonic_ns
        self.sample_count += 1
        if not sample.identity_valid and (
                sample.mapper_before or sample.mapper_after):
            raise QualificationFailure("mapper identity changed during stop")
        if not sample.mapper_before and not sample.mapper_after and \
                sample.swap_active:
            raise QualificationFailure(
                "mapper disappeared while still present in swap inventory")
        if sample.mapper_before != sample.mapper_after:
            return
        if sample.mapper_before:
            if sample.swap_active:
                if self.phase >= 2:
                    raise QualificationFailure(
                        "mapper swap reactivated after swapoff during stop")
                self.phase = 1
            else:
                if self.phase == 0:
                    raise Blocked(
                        "stop sampler did not witness initial active mapper")
                if self.phase == 3:
                    raise QualificationFailure(
                        "mapper reappeared after removal during stop")
                self.phase = 2
        else:
            if self.phase < 2:
                raise Blocked(
                    "stop completed but sampler did not independently witness "
                    "swapoff before mapper removal")
            self.phase = 3

    def result(self) -> dict:
        if self.sample_count == 0:
            raise Blocked("stop sampler collected no observations")
        if self.phase == 0:
            raise Blocked("stop sampler did not witness initial active mapper")
        if self.phase == 1:
            raise Blocked(
                "stop completed but sampler did not independently witness "
                "swapoff before mapper removal")
        if self.phase == 2:
            raise Blocked("stop sampler did not witness final mapper absence")
        return {
            "initial_active": True,
            "swapoff_before_remove_witness": True,
            "final_absent": True,
            "samples": self.sample_count,
        }


def evaluate_stop_samples(samples: list[StopSample]) -> dict:
    tracker = StopOrderTracker()
    for sample in samples:
        tracker.observe(sample)
    return tracker.result()


class CycleTelemetrySampler:
    """Constant-memory host telemetry spanning pressure through normal teardown."""

    def __init__(self):
        self.error: Exception | None = None
        self.samples = 0
        self.started_monotonic_ns = 0
        self.ended_monotonic_ns = 0
        self.minimum_mem_available_mib: int | None = None
        self._first_memory_psi_total: int | None = None
        self._last_memory_psi_total: int | None = None
        self._first_vmstat: dict[str, int] | None = None
        self._last_vmstat: dict[str, int] | None = None
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="swapz-cycle-telemetry", daemon=True)

    def start(self) -> None:
        self._thread.start()
        startup_error: BaseException | None = None
        try:
            if not self._ready.wait(CYCLE_TELEMETRY_THREAD_TIMEOUT_SECONDS):
                startup_error = Blocked(
                    "cycle telemetry sampler produced no initial observation")
            else:
                self.check()
        except BaseException as exc:
            startup_error = exc

        if startup_error is None:
            return

        self._stop.set()
        cleanup_errors = []
        try:
            self._thread.join(timeout=CYCLE_TELEMETRY_THREAD_TIMEOUT_SECONDS)
        except BaseException as cleanup_error:
            cleanup_errors.append(
                f"cycle telemetry thread join: {_exception_text(cleanup_error)}")
        if self._thread.is_alive():
            cleanup_errors.append(
                "cycle telemetry sampler did not terminate after startup failure")
        _raise_cleanup_errors(startup_error, cleanup_errors)
        raise startup_error

    def check(self) -> None:
        if self.error is None:
            return
        if isinstance(self.error, QualificationFailure):
            raise QualificationFailure(
                f"cycle telemetry failed: {self.error}") from self.error
        raise Blocked(f"cycle telemetry failed: {self.error}") from self.error

    def stop(self) -> dict:
        self._stop.set()
        self._thread.join(timeout=CYCLE_TELEMETRY_THREAD_TIMEOUT_SECONDS)
        if self._thread.is_alive():
            raise Blocked("cycle telemetry sampler thread did not terminate")
        self.check()
        if self.samples <= 0 or self.minimum_mem_available_mib is None or \
                self._first_memory_psi_total is None or \
                self._last_memory_psi_total is None or \
                self._first_vmstat is None or self._last_vmstat is None or \
                self.ended_monotonic_ns <= self.started_monotonic_ns:
            raise Blocked("cycle telemetry sampler evidence is incomplete")
        return {
            "samples": self.samples,
            "started_monotonic_ns": self.started_monotonic_ns,
            "ended_monotonic_ns": self.ended_monotonic_ns,
            "minimum_mem_available_mib": self.minimum_mem_available_mib,
            "memory_psi_some_usec_delta":
                self._last_memory_psi_total - self._first_memory_psi_total,
            "pswpin_delta":
                self._last_vmstat["pswpin"] - self._first_vmstat["pswpin"],
            "pswpout_delta":
                self._last_vmstat["pswpout"] - self._first_vmstat["pswpout"],
        }

    def _run(self) -> None:
        try:
            self.started_monotonic_ns = time.monotonic_ns()
            while True:
                mem_available_mib = _mem_available_mib()
                memory_psi_total = _psi_total(
                    Path("/proc/pressure/memory"))
                vmstat = read_vmstat()
                if mem_available_mib < MIN_AVAILABLE_MIB:
                    raise QualificationFailure(
                        f"host MemAvailable crossed {MIN_AVAILABLE_MIB} MiB "
                        "during cycle telemetry")
                if self._last_memory_psi_total is not None and \
                        memory_psi_total < self._last_memory_psi_total:
                    raise Blocked(
                        "host memory PSI total regressed during cycle telemetry")
                if self._last_vmstat is not None and (
                        vmstat["pswpin"] < self._last_vmstat["pswpin"] or
                        vmstat["pswpout"] < self._last_vmstat["pswpout"]):
                    raise Blocked(
                        "kernel swap counters regressed during cycle telemetry")
                if self.samples == 0:
                    self._first_memory_psi_total = memory_psi_total
                    self._first_vmstat = dict(vmstat)
                    self.minimum_mem_available_mib = mem_available_mib
                else:
                    self.minimum_mem_available_mib = min(
                        self.minimum_mem_available_mib, mem_available_mib)
                self._last_memory_psi_total = memory_psi_total
                self._last_vmstat = dict(vmstat)
                self.samples += 1
                self._ready.set()
                if self._stop.wait(CYCLE_TELEMETRY_INTERVAL_SECONDS):
                    break
        except Exception as exc:
            self.error = exc
            self._ready.set()
        finally:
            self.ended_monotonic_ns = time.monotonic_ns()


class StopSampler:
    def __init__(self, mapper_device: tuple[int, int], expected_uuid: str, known_swap_path: str):
        self.mapper_device = mapper_device
        self.expected_uuid = expected_uuid
        self.known_swap_path = known_swap_path
        self._tracker = StopOrderTracker()
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
            if isinstance(self.error, QualificationFailure):
                raise QualificationFailure(
                    f"stop sampler failed: {self.error}") from self.error
            raise Blocked(f"stop sampler failed: {self.error}") from self.error
        return self._tracker.result()

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
                self._tracker.observe(StopSample(
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
    mapper_sysfs = Path(
        f"/sys/dev/block/{active['mapper_device'][0]}:{active['mapper_device'][1]}")
    if _dm_identity() is not None or _path_present(
            mapper_sysfs, "primary mapper sysfs device"):
        raise QualificationFailure("primary mapper remains after successful stop")
    if _path_present(Path("/sys/module/dm_swapz"), "dm_swapz module sysfs state"):
        raise QualificationFailure("transaction-owned dm_swapz module remains loaded after stop")
    state = read_state()
    if state is None or state.get("run_id") != manifest["run_id"] or state.get("stage") != "COMPLETE":
        raise QualificationFailure("durable primary state is not COMPLETE after stop")
    if _path_present(
            RECOVERY_BASE / f"partition-{partuuid}.active",
            "primary partition ownership marker"):
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
    if _path_present(
            Path("/sys/module/dm_swapz"), "dm_swapz module sysfs state",
            QualificationFailure):
        raise QualificationFailure("transaction-owned dm_swapz module remains after cleanup")
    state = read_state()
    if state is None or state.get("run_id") != manifest["run_id"] or state.get("stage") != "COMPLETE":
        raise QualificationFailure("durable primary state is not COMPLETE after cleanup")
    if _path_present(
            RECOVERY_BASE / f"partition-{partuuid}.active",
            "primary partition ownership marker", QualificationFailure):
        raise QualificationFailure("partition ownership marker remains after cleanup")


def _reconcile_primary_cleanup(swapzctl: Path, manifest: dict,
                               baseline_identity: set[tuple], partuuid: str,
                               timeout_seconds: int) -> None:
    """Converge an interrupted coordinator through normal stop/recover only."""
    state = read_state()
    if state is None or state.get("run_id") != manifest["run_id"]:
        raise QualificationFailure(
            "durable state cannot be reconciled automatically")
    stage = state.get("stage")
    cleanup = None
    if stage == "ACTIVE":
        cleanup = _primary(swapzctl, "stop", timeout_seconds, admitted=True)
    elif stage in {
            "STARTING", "STOPPING", "RECOVERY_REQUIRED", "RECOVERING", "RESTORED"}:
        cleanup = _primary(swapzctl, "recover", timeout_seconds, admitted=True)
    elif stage != "COMPLETE":
        raise QualificationFailure(f"state {stage} requires manual review")
    if cleanup is not None and cleanup.returncode != 0:
        detail = (cleanup.stderr or cleanup.stdout).strip().replace("\n", "; ")
        raise QualificationFailure(
            f"normal recovery cleanup failed rc={cleanup.returncode}: {detail}")
    _verify_completed_cleanup(manifest, baseline_identity, partuuid)


def _cleanup_failed_start(swapzctl: Path, manifest: dict, baseline_identity: set[tuple],
                          partuuid: str, timeout_seconds: int, original_reason: str) -> None:
    try:
        _reconcile_primary_cleanup(
            swapzctl, manifest, baseline_identity, partuuid, timeout_seconds)
    except BaseException as cleanup_error:
        raise QualificationFailure(
            f"{original_reason}; normal recovery cleanup also failed: "
            f"{_exception_text(cleanup_error)}") from cleanup_error
    raise QualificationFailure(original_reason)


def _normal_stop(swapzctl: Path, manifest: dict, active: dict | None,
                 baseline_identity: set[tuple], partuuid: str, timeout_seconds: int) -> dict | None:
    sampler = None
    sampler_evidence = None
    sampler_error = None
    sampler_started = False
    if active is not None:
        try:
            sampler = StopSampler(active["mapper_device"], active["mapper_uuid"], active["swap_path"])
            sampler.start()
            sampler_started = True
            time.sleep(0.02)
        except BaseException as exc:
            # Sampling failure or interruption cannot strand a verified live mapper.
            sampler_error = exc
    primary_error: BaseException | None = None
    stopped = None
    try:
        stopped = _primary(swapzctl, "stop", timeout_seconds, admitted=True)
    except BaseException as exc:
        primary_error = exc
    finally:
        if sampler_started:
            delay_error: BaseException | None = None
            try:
                time.sleep(0.05)
            except BaseException as exc:
                delay_error = exc
            try:
                sampler_evidence = sampler.stop()
            except BaseException as exc:
                cleanup_detail = _exception_text(exc)
                if delay_error is not None:
                    cleanup_detail = (
                        f"{_exception_text(delay_error)}; sampler cleanup also "
                        f"failed: {cleanup_detail}")
                sampler_error = (
                    Blocked(
                        f"{_exception_text(sampler_error)}; "
                        f"sampler cleanup also failed: {cleanup_detail}")
                    if sampler_error is not None else
                    Blocked(cleanup_detail))
            else:
                if delay_error is not None:
                    sampler_error = (
                        Blocked(
                            f"{_exception_text(sampler_error)}; sampler final "
                            f"observation delay was interrupted: "
                            f"{_exception_text(delay_error)}")
                        if sampler_error is not None else delay_error)
    if primary_error is not None:
        try:
            _reconcile_primary_cleanup(
                swapzctl, manifest, baseline_identity, partuuid,
                timeout_seconds)
        except BaseException as cleanup_error:
            details = (
                f"{_exception_text(primary_error)}; normal stop/recovery also "
                f"failed: {_exception_text(cleanup_error)}")
            if sampler_error is not None:
                details += (
                    f"; stop sampler also failed: "
                    f"{_exception_text(sampler_error)}")
            raise QualificationFailure(details) from cleanup_error
        if sampler_error is not None:
            raise QualificationFailure(
                f"{_exception_text(primary_error)}; stop sampler also failed: "
                f"{_exception_text(sampler_error)}") from primary_error
        raise primary_error
    assert stopped is not None
    if stopped.returncode != 0:
        detail = (stopped.stderr or stopped.stdout).strip().replace("\n", "; ")
        message = (
            f"primary stop/swapoff failed rc={stopped.returncode}; "
            f"no force cleanup attempted: {detail}")
        if sampler_error is not None:
            message += (
                f"; stop sampler also failed: "
                f"{_exception_text(sampler_error)}")
        raise QualificationFailure(message)
    completion_error: BaseException | None = None
    try:
        _read_primary_output(
            stopped, f"PRIMARY_STOP=COMPLETE run_id={manifest['run_id']} ")
        if active is not None:
            _post_stop_verify(
                manifest, active, baseline_identity, partuuid)
        else:
            _verify_completed_cleanup(
                manifest, baseline_identity, partuuid)
    except BaseException as exc:
        completion_error = exc

    if completion_error is not None:
        if sampler_error is not None:
            details = (
                f"{_exception_text(completion_error)}; stop sampler also "
                f"failed: {_exception_text(sampler_error)}")
            if isinstance(completion_error, Blocked) and \
                    not isinstance(sampler_error, QualificationFailure):
                raise Blocked(details) from completion_error
            raise QualificationFailure(details) from completion_error
        raise completion_error
    if sampler_error is not None:
        raise sampler_error
    return sampler_evidence


def run_cycle(index: int, *, swapzctl: Path, oracle_path: Path, validated_source: str,
              plan: dict, selector_partuuid: str, selector_evidence: SelectorEvidence,
              authorization_snapshot: dict, target_device: tuple[int, int],
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
    _require_selector_at_policy_use(
        selector_evidence, plan, authorization_snapshot,
        target_device, target_parent_device)

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

    try:
        started = _primary(swapzctl, "start", timeout_seconds, admitted=True)
    except BaseException as start_error:
        # A timeout or interruption can occur after swapon has succeeded.
        # Reconcile through the ordinary coordinator path before propagating it.
        try:
            _reconcile_primary_cleanup(
                swapzctl, manifest, baseline_identity, selector_partuuid,
                timeout_seconds)
        except BaseException as cleanup_error:
            raise QualificationFailure(
                f"primary start invocation failed: {_exception_text(start_error)}; "
                f"normal stop/recovery also failed: "
                f"{_exception_text(cleanup_error)}") from cleanup_error
        raise
    if started.returncode != 0:
        detail = (started.stderr or started.stdout).strip().replace("\n", "; ")
        _cleanup_failed_start(
            swapzctl, manifest, baseline_identity, selector_partuuid, timeout_seconds,
            f"primary start failed after admitted prepare rc={started.returncode}: {detail}")

    active = None
    original_failure: BaseException | None = None
    workload_result = None
    cycle_telemetry_sampler: CycleTelemetrySampler | None = None
    cycle_telemetry_result = None
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
        telemetry_candidate = CycleTelemetrySampler()
        telemetry_candidate.start()
        cycle_telemetry_sampler = telemetry_candidate
        workload_result = _run_workload(
            manifest, active, oracle_path,
            workload_mib, resident_mib, swap_limit_mib, timeout_seconds,
            telemetry_check=cycle_telemetry_sampler.check,
        )
    except BaseException as exc:
        original_failure = exc

    cleanup_failure: BaseException | None = None
    stop_evidence = None
    try:
        if original_failure is not None and active is None:
            # We cannot safely assume the start failed merely because independent
            # verification did. Reconcile the durable stage and request only the
            # coordinator's normal stop/recover path.
            state = read_state()
            if state is not None and state.get("run_id") == run_id and \
                    state.get("stage") == "ACTIVE":
                _normal_stop(
                    swapzctl, manifest, None, baseline_identity,
                    selector_partuuid, timeout_seconds)
            else:
                _reconcile_primary_cleanup(
                    swapzctl, manifest, baseline_identity,
                    selector_partuuid, timeout_seconds)
        else:
            stop_evidence = _normal_stop(
                swapzctl, manifest, active, baseline_identity,
                selector_partuuid, timeout_seconds)
    except BaseException as exc:
        cleanup_failure = exc

    telemetry_failure: BaseException | None = None
    if cycle_telemetry_sampler is not None:
        try:
            cycle_telemetry_result = cycle_telemetry_sampler.stop()
        except BaseException as exc:
            telemetry_failure = exc

    if cleanup_failure is not None:
        if original_failure is not None:
            details = (
                f"{_exception_text(original_failure)}; normal stop/recovery also "
                f"failed: {_exception_text(cleanup_failure)}")
            if telemetry_failure is not None:
                details += (
                    f"; cycle telemetry also failed: "
                    f"{_exception_text(telemetry_failure)}")
            raise QualificationFailure(details) from cleanup_failure
        if telemetry_failure is not None:
            raise QualificationFailure(
                f"{_exception_text(cleanup_failure)}; cycle telemetry also "
                f"failed: {_exception_text(telemetry_failure)}"
            ) from cleanup_failure
        raise cleanup_failure
    if telemetry_failure is not None:
        if original_failure is not None:
            raise QualificationFailure(
                f"{_exception_text(original_failure)}; cycle telemetry also "
                f"failed: {_exception_text(telemetry_failure)}"
            ) from telemetry_failure
        raise telemetry_failure

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
        "cycle_telemetry": cycle_telemetry_result,
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


def require_final_installed_artifact_identity(
        qualified_swapzctl: Path, expected_hashes: dict[str, str]) -> None:
    """Retain the initially qualified package identity through terminal PASS.

    The imported report digest is intentionally pinned at admission; do not
    re-hash its mutable pathname after the workload.
    """
    paths = installed_artifact_paths(qualified_swapzctl)
    if set(expected_hashes) != set(paths):
        raise QualificationFailure("final qualified artifact inventory is incomplete")
    for artifact_key, path in paths.items():
        if _sha256_file(
                path, error_type=QualificationFailure) != expected_hashes[artifact_key]:
            raise QualificationFailure(
                f"installed {artifact_key} bytes changed during real-swap campaign")


def _execute_admitted(
        arguments: argparse.Namespace, admission: SourceAdmissionClient,
        terminal_cleanup: Callable[[], None] | None = None) -> dict:
    helper_sha256 = getattr(arguments, "executed_helper_sha256", None)
    if not isinstance(helper_sha256, str) or \
            re.fullmatch(r"[0-9a-f]{64}", helper_sha256) is None:
        raise Blocked("commit-bound executed helper digest is required")
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
    try:
        private_parent = Path(private_workspace.name)
        try:
            os.chmod(private_parent, 0o700)
        except OSError as exc:
            raise Blocked(
                f"cannot secure private physical workspace: {exc}") from exc
        pinned_source_root, physical_control_inputs_sha256 = \
            pin_physical_control_inputs(private_parent)
        pinned_acceptance_manifest = (
            pinned_source_root / "docs/production-acceptance.json")
        pinned_authorization_snapshot = (
            pinned_source_root / "docs/handoff/production-readiness.json")
        admission.bind_physical_control_inputs(
            physical_control_inputs_sha256)
        admission.bind_executed_helper_sha256(helper_sha256)
        expected_oracle_sha256 = admission.require("initial")
        private_directory = private_parent / "control"
        swapzctl, execution_control_sha256 = build_physical_execution_control(
            arguments.validated_source, qualified_swapzctl, private_directory,
            source_root=pinned_source_root,
            expected_input_hashes=physical_control_inputs_sha256)
        oracle_path, oracle_sha256 = pin_real_swap_oracle(
            requested_oracle_path, private_parent, expected_oracle_sha256)
    except BaseException as original_error:
        try:
            private_workspace.cleanup()
        except Exception as cleanup_error:
            _raise_cleanup_errors(
                original_error, [f"private workspace: {cleanup_error}"],
                error_type=Blocked)
        raise

    try:
        preflight_workload_environment(
            arguments.workload_mib, arguments.resident_mib, arguments.swap_limit_mib)
        _accepted_policy, acceptance_policy_sha256 = \
            _verify_acceptance_manifest_snapshot(
                cycles=arguments.cycles,
                workload_mib=arguments.workload_mib,
                resident_mib=arguments.resident_mib,
                swap_limit_mib=arguments.swap_limit_mib,
                timeout_seconds=arguments.timeout_seconds,
                path=pinned_acceptance_manifest,
                expected_sha256=physical_control_inputs_sha256[
                    "docs/production-acceptance.json"])
        authorization_snapshot, authorization_snapshot_sha256 = \
            _read_readiness_snapshot(
                pinned_authorization_snapshot,
                expected_sha256=physical_control_inputs_sha256[
                    "docs/handoff/production-readiness.json"])
        _kernel_log_snapshot()
        require_private_execution_artifact_identity(
            swapzctl, oracle_path, execution_control_sha256, oracle_sha256,
            "before_qualification_import")
        _import_qualification(swapzctl, report_path)
        plan = _read_plan(swapzctl)
        artifact_hashes = verify_provenance(
            plan, arguments.validated_source, report_path, qualified_swapzctl)
        # Bind evidence to the exact report digest imported and independently
        # verified above. Do not re-hash a mutable pathname after the workload.
        qualification_report_sha256 = plan["qualification_report_sha256"]
        installed_plan = _read_installed_plan(qualified_swapzctl)
        if installed_plan.get("privileged_execution_enabled") is not False:
            raise Blocked(
                "installed production control is already authorized for "
                "privileged lifecycle execution")
        if execution_control_sha256 == artifact_hashes["formatter_sha256"]:
            raise Blocked(
                "private physical execution control is not distinct from "
                "the installed qualified control")
        selector_evidence = _read_selector_evidence()
        selector_partuuid = selector_evidence.partuuid
        _target_path, target_device, target_parent_device = verify_authorized_target(
            plan, selector_partuuid, authorization_snapshot)
        # The verifier has already matched this value against live block
        # geometry, lsblk and the authorized target snapshot.
        target_size_bytes = int(plan["target_device_bytes"])
        baseline = read_swap_rows()
        baseline_state = _validate_precycle_state(
            selector_partuuid, target_device, target_parent_device, baseline)
        kernel_before = _kernel_log_snapshot()
        _reject_relevant_kernel_errors([])
    
        evidence = PersistentEvidence(
            RECOVERY_BASE,
            os.urandom(16).hex(),
            {
                "source_sha": arguments.validated_source,
                "acceptance_manifest_sha256": acceptance_policy_sha256,
                "authorization_snapshot_sha256":
                    authorization_snapshot_sha256,
                "qualification_report_sha256": qualification_report_sha256,
                "helper_sha256": helper_sha256,
                "oracle_sha256": oracle_sha256,
                "qualified_installed_artifacts": artifact_hashes,
                "physical_execution_control_sha256": execution_control_sha256,
                "physical_control_inputs_sha256":
                    physical_control_inputs_sha256,
                "installed_control_privileged_execution_enabled": False,
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
    
    except BaseException as original_error:
        try:
            private_workspace.cleanup()
        except Exception as cleanup_error:
            _raise_cleanup_errors(
                original_error, [f"private workspace: {cleanup_error}"],
                error_type=Blocked)
        raise

    # First-cycle freshness also excludes the immediately preceding durable
    # COMPLETE transaction, not only IDs observed later in this campaign.
    run_ids: set[str] = (
        {baseline_state["run_id"]} if baseline_state is not None else set())
    swap_uuids: set[str] = set()
    cycles: list[dict] = []
    workspace_cleanup_complete = False
    try:
        for cycle_index in range(1, arguments.cycles + 1):
            evidence.update(
                f"CYCLE_{cycle_index}_STARTING",
                cycles=cycles,
                cycle=cycle_index,
            )
            require_private_execution_artifact_identity(
                swapzctl, oracle_path, execution_control_sha256, oracle_sha256,
                f"before_cycle-{cycle_index}")
            result = run_cycle(
                cycle_index,
                swapzctl=swapzctl,
                oracle_path=oracle_path,
                validated_source=arguments.validated_source,
                plan=plan,
                selector_partuuid=selector_partuuid,
                selector_evidence=selector_evidence,
                authorization_snapshot=authorization_snapshot,
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
            # Revalidate on completion before a later cycle or terminal PASS.
            _require_selector_at_policy_use(
                selector_evidence, plan, authorization_snapshot,
                target_device, target_parent_device)
            run_ids.add(result["run_id"])
            swap_uuids.add(result["linux_swap_uuid"])
            cycles.append(result)
            evidence.update(
                f"CYCLE_{cycle_index}_COMPLETE",
                cycles=cycles,
                cycle=cycle_index,
                run_id=result["run_id"],
            )
        require_private_execution_artifact_identity(
            swapzctl, oracle_path, execution_control_sha256, oracle_sha256,
            "before_final_publication")
        kernel_after = _kernel_log_snapshot()
        _reject_relevant_kernel_errors(_kernel_log_delta(kernel_before, kernel_after))
        # A terminal PASS must never coexist with a leaked privileged control
        # or pinned-oracle workspace. Clean it before the final source proof so
        # that proof remains as close as possible to the PASS evidence commit.
        try:
            private_workspace.cleanup()
        except Exception as cleanup_error:
            raise QualificationFailure(
                f"private workspace cleanup failed before terminal PASS: "
                f"{cleanup_error}") from cleanup_error
        if _path_present(
                private_parent, "private physical workspace",
                QualificationFailure):
            raise QualificationFailure(
                "private physical workspace remains after reported cleanup")
        workspace_cleanup_complete = True
        result = {
            "schema": "swapz-primary-real-swap-v1",
            "status": "PASS",
            "source_sha": arguments.validated_source,
            "acceptance_manifest_sha256": acceptance_policy_sha256,
            "authorization_snapshot_sha256":
                authorization_snapshot_sha256,
            "helper_sha256": helper_sha256,
            "oracle_sha256": oracle_sha256,
            "qualification_report_sha256": qualification_report_sha256,
            "qualified_installed_artifacts": artifact_hashes,
            "physical_execution_control_sha256": execution_control_sha256,
            "physical_control_inputs_sha256":
                physical_control_inputs_sha256,
            "installed_control_privileged_execution_enabled": False,
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
        # A long physical run must not qualify a source superseded on main.
        # Stabilize every result input, persist a non-PASS publication marker,
        # then use the existing final admission immediately before channel close.
        require_final_installed_artifact_identity(
            qualified_swapzctl, artifact_hashes)
        evidence.update("FINAL_PUBLICATION_PENDING", cycles=cycles)
        # Policy and target authorization were consumed from commit-bound
        # private snapshots. This final admission re-proves that exact source
        # commit is still canonical after the private workspace is removed.
        admission.require("final")
        _require_selector_at_policy_use(
            selector_evidence, plan, authorization_snapshot,
            target_device, target_parent_device)
        if terminal_cleanup is not None:
            terminal_cleanup()
        evidence.finish("PASS", cycles=cycles, result=result)
        return result
    except Blocked as exc:
        setattr(exc, "evidence_path", str(evidence.path))
        try:
            evidence.finish("BLOCKED", str(exc), cycles=cycles)
        except Exception as write_error:
            raise Blocked(
                f"{exc}; failure evidence persistence also failed: {write_error}") from exc
        raise
    except QualificationFailure as exc:
        setattr(exc, "evidence_path", str(evidence.path))
        try:
            evidence.finish("FAIL", str(exc), cycles=cycles)
        except Exception as write_error:
            raise QualificationFailure(
                f"{exc}; failure evidence persistence also failed: {write_error}") from exc
        raise
    except Exception as exc:
        failure = QualificationFailure(
            f"internal qualification error: {type(exc).__name__}: {exc}")
        setattr(failure, "evidence_path", str(evidence.path))
        try:
            evidence.finish("FAIL", str(failure), cycles=cycles)
        except Exception as write_error:
            raise QualificationFailure(
                f"{failure}; failure evidence persistence also failed: {write_error}") from exc
        raise failure from exc
    finally:
        if not workspace_cleanup_complete:
            original_error = sys.exc_info()[1]
            try:
                private_workspace.cleanup()
            except Exception as cleanup_error:
                _raise_cleanup_errors(
                    original_error, [f"private workspace: {cleanup_error}"])

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
        parent_process_id = getattr(
            arguments, "source_admission_parent_process_id", None)
        parent_start_ticks = getattr(
            arguments, "source_admission_parent_start_ticks", None)
        if (not socket_path or parent_uid is None or
                parent_process_id is None or parent_start_ticks is None):
            raise Blocked("unprivileged source admission channel is required")
        admission = SourceAdmissionClient(
            socket_path, parent_uid, parent_process_id, parent_start_ticks,
            arguments.validated_source)

    admission_closed = False

    def close_owned_admission_before_pass() -> None:
        nonlocal admission_closed
        try:
            admission.close()
        except Exception as cleanup_error:
            raise QualificationFailure(
                "source admission channel cleanup failed before terminal PASS: "
                f"{cleanup_error}") from cleanup_error
        admission_closed = True

    try:
        if owns_admission:
            return _execute_admitted(
                arguments, admission,
                terminal_cleanup=close_owned_admission_before_pass)
        return _execute_admitted(arguments, admission)
    finally:
        if owns_admission and not admission_closed:
            original_error = sys.exc_info()[1]
            try:
                admission.close()
            except Exception as cleanup_error:
                _raise_cleanup_errors(
                    original_error, [f"source admission channel: {cleanup_error}"])


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
        "--executed-helper-sha256", default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--source-admission-socket", default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--source-admission-parent-uid", type=int, default=None,
        help=argparse.SUPPRESS)
    parser.add_argument(
        "--source-admission-parent-process-id", type=int, default=None,
        help=argparse.SUPPRESS)
    parser.add_argument(
        "--source-admission-parent-start-ticks", type=int, default=None,
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
