#!/usr/bin/env python3
"""Historical old-host live-swap coordinator, retained for recovery review.

This tool is separate from physical-swap-probe.py. Its plan action is
read-only. Its run and recover actions are permanently disabled because its
approval and target bindings are specific to the retired /dev/sda4 host. It is
not a production deployment interface or a selector for the current target.
"""
import argparse
from datetime import datetime, timezone
import ctypes
import fcntl
import hashlib
import importlib.util
import json
import math
import mmap
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
QUALIFIED_SOURCE = "6ff945e8c5e6671f9ffd6d1920343190ae1e5e28"
DEVICE_UUID_PATH = "/dev/disk/by-uuid/728b4c06-44b0-46ee-91ec-560ab1bad358"
DEVICE_PATH = "/dev/sda4"
DEVICE_MAJOR = 8
DEVICE_MINOR = 4
DEVICE_PARTUUID = "7fb9401d-04"
DEVICE_SIZE_BYTES = 17179869184
ORIGINAL_HEADER_SHA256 = (
    "ace016a7a3ecd22b0aca05946a305aef2113bc50439452756ae68909010f0afe")
EXPECTED_ARTIFACTS = {
    "formatter_sha256": (
        "7f38c6f4226142ceb0c655009f0917d7370ccd0aac7a5db110148b1a861e00e0"),
    "module_sha256": (
        "e9001e487e3a86f2404c716f69bb01aa4cc4676f4a5f869201468d1a91850d67"),
    "oracle_sha256": (
        "f47c6f9c9ca97d4d580e0a2d88efcb41cca8d34f4a35e0456a4a4d9a6e85ffe8"),
}
PAGE_BYTES = 4096
SWAPZ_SEGMENT_BLOCKS = 256
SWAPZ_MIN_RESERVE_BLOCKS = 2 * SWAPZ_SEGMENT_BLOCKS


def _maximum_logical_pages(physical_blocks):
    """Mirror authority_init()'s reserve and segment-alignment admission."""
    if type(physical_blocks) is not int or physical_blocks <= 0:
        raise ValueError("physical block count must be a positive integer")
    low, high = 0, physical_blocks
    while low < high:
        candidate = (low + high + 1) // 2
        reserve = max((candidate + 7) // 8, SWAPZ_MIN_RESERVE_BLOCKS)
        admitted = reserve < physical_blocks and candidate <= (
            (physical_blocks - reserve) // SWAPZ_SEGMENT_BLOCKS
        ) * SWAPZ_SEGMENT_BLOCKS
        if admitted:
            low = candidate
        else:
            high = candidate - 1
    return low


MAX_PHYSICAL_BLOCKS = (
    ((DEVICE_SIZE_BYTES // PAGE_BYTES - 1) // SWAPZ_SEGMENT_BLOCKS) *
    SWAPZ_SEGMENT_BLOCKS)
MAX_LOGICAL_PAGES = _maximum_logical_pages(MAX_PHYSICAL_BLOCKS)
LOGICAL_BYTES = MAX_LOGICAL_PAGES * PAGE_BYTES
LOGICAL_SECTORS = LOGICAL_BYTES // 512
TRIAL_SECONDS = 30 * 60
SAMPLE_SECONDS = 5
PRESSURE_SETTLE_SECONDS = 60
SWAPOFF_TIMEOUT_SECONDS = 30 * 60
PRESSURE_PAGES = 80000
MAPPER_OPEN_ATTEMPTS = 6
PRESSURE_MEMORY_MAX_BYTES = 128 * 1024 * 1024
PRESSURE_TIMEOUT_SECONDS = 15 * 60
RAM_DRAIN_MARGIN_BYTES = 512 * 1024 * 1024
MIN_DRAIN_HEADROOM_BYTES = RAM_DRAIN_MARGIN_BYTES
# The trial starts, samples and stops at this headroom above the 2 GiB
# reserve. Cleanup then still has the 512 MiB drain margin to spend.
TRIAL_HEADROOM_BYTES = 1024 * 1024 * 1024
MIN_AVAILABLE_BYTES = 2 * 1024 * 1024 * 1024
MIN_CGROUP_HEADROOM_BYTES = 512 * 1024 * 1024
MAX_MEMORY_SOME_AVG10 = 5.0
MAX_MEMORY_FULL_AVG10 = 1.0
RESULT_LIMIT = 4096
STATE_NAME = "state.json"
BACKUP_NAME = "block0.bin"
RESULTS_NAME = "results.json"
APPROVAL_NAME = "approval.json"
LIVE_NAME_PREFIX = "swapz-live-"
LIVE_UUID_PREFIX = "SWAPZ-LIVE-"
RECOVERY_BASE = Path("/var/lib/swapz/physical-recovery")
PRESSURE_CGROUP_ROOT = Path("/sys/fs/cgroup")
# Retained only for read-only plan output and synthetic policy tests. Do not
# re-enable this helper: its device and approval model are historical.
LIVE_SWAP_EXECUTION_ENABLED = False
POST_QUALIFICATION_PATHS = {
    "docs/ROADMAP.md",
    "docs/testing_standards.md",
    "docs/live-swap-trial-recovery.md",
    "test_results.json",
    "tests/runtime/native/physical-swap-probe-test.py",
    "tests/runtime/native/live-swap-supervisor-test.py",
    "tests/tools/physical-swap-probe.py",
    "tests/tools/live-swap-supervisor.py",
    "tests/tools/test-rootless.sh",
}
REQUIRED_CI_WORKFLOWS = (
    "Native kernel-C project-goal regressions",
    "Experimental swapz production C qualification",
)
GH_RUN_LIST_ARGS = (
    "gh", "run", "list", "--repo", "k1moradi/swapz", "--branch", "main",
    "--limit", "40", "--json", "headSha,name,conclusion,status",
)
PLANNED_MUTATION_TRACE = (
    "persist and fsync one-use recovery state and artifact snapshots",
    "swapoff only the exact original /dev/sda4 swap entry",
    "clear and format only the identity-checked original partition",
    "load only the snapshotted qualified dm_swapz module",
    "create one exact maximum-capacity helper-owned mapper over /dev/sda4",
    "initialize Linux swap on the verified mapper only",
    "activate only the maximum-capacity mapper as the sole swap area; discard disabled",
    "run one cgroup-limited, byte-verified swap-pressure child inside the trial",
    "observe for at most 30 minutes with memory and I/O stop gates",
    "swapoff only the helper mapper after RAM drain-capacity checks",
    "remove only the exact mapper without force",
    "unload only a same-process-owned module with zero references",
    "restore and reread the exact original 4096-byte header",
    "reactivate /dev/sda4 with its saved priority and verify restoration",
    "durably complete recovery and release the active marker",
)
LIVE_APPROVAL_TEXT = (
    "Approved by the owner for one supervised experimental Linux swap trial "
    "only, with swapz capacity set to the maximum admitted for the complete "
    "selected partition as the sole swap area, without fallback swap, for at "
    "most 30 minutes including one bounded cgroup swap-pressure check. Require "
    "RAM use below 50 percent before original swapoff, and enough measured "
    "MemAvailable to start with a 1 GiB trial headroom above the 2 GiB reserve, "
    "which leaves the 512 MiB drain margin for cleanup. Use the exact artifact "
    "and device bindings. Stop on any mismatch or uncertainty; preserve an active "
    "mapper if swapoff cannot safely drain it. Never force-remove, reboot, or "
    "overwrite an ambiguous header. This does not authorize endurance or "
    "production qualification."
)
OWNER_APPROVAL_TEXT = (
    "I explicitly authorize this one no-fallback live-swap trial using only "
    "/dev/sda4 after the exact device, artifacts, helper, maximum capacity, "
    "RAM drain gates, duration, and recovery record are bound below."
)
OWNER_WAIVER_TEXT = (
    "I waive the separate external-review requirement for this one no-fallback "
    "live-swap trial only. This is an owner decision, not a reviewer approval."
)
PROC_ROOT = Path("/proc")
SWAPOFF_STAGES = {"ORIGINAL_SWAPOFF_PENDING", "MAPPER_SWAPOFF_PENDING"}
RECOVERY_RECOGNIZED_STAGES = {
    "ORIGINAL_SWAPOFF_PENDING", "ORIGINAL_SWAP_OFF",
    "HEADER_CLEAR_PENDING", "HEADER_CLEARED", "FORMAT_PENDING",
    "SWZ_FORMATTED", "MODULE_LOAD_PENDING", "MODULE_LOADED",
    "MAPPER_CREATE_PENDING", "MAPPED", "MKSWAP_PENDING",
    "MAPPED_SWAP_READY", "SWAPON_PENDING", "LIVE_SWAP_ACTIVE",
    "TRIAL_STOPPING", "MAPPER_SWAPOFF_PENDING", "MAPPER_SWAP_OFF",
    "MAPPER_REMOVE_PENDING", "MAPPER_REMOVED", "MODULE_UNLOAD_PENDING",
    "MODULE_UNLOADED", "HEADER_RESTORE_PENDING", "HEADER_RESTORED",
    "ORIGINAL_SWAPON_PENDING", "ORIGINAL_SWAP_ACTIVE",
    "RECOVERY_REQUIRED",
}


class LiveSwapError(RuntimeError):
    pass


class SafeStop(LiveSwapError):
    """A conservative stop before or during the trial; restoration still runs."""

    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


_STOP_REQUESTED = False


def _load_physical_helper():
    path = ROOT / "tests/tools/physical-swap-probe.py"
    spec = importlib.util.spec_from_file_location(
        "swapz_physical_swap_probe", path)
    if spec is None or spec.loader is None:
        raise LiveSwapError("cannot load reviewed physical-swap primitives")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PHYSICAL = _load_physical_helper()
PHYSICAL_HELPER_PATH = ROOT / "tests/tools/physical-swap-probe.py"
PHYSICAL_HELPER_SHA256 = hashlib.sha256(PHYSICAL_HELPER_PATH.read_bytes()).hexdigest()


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z")


def _request_stop(_signum, _frame):
    global _STOP_REQUESTED
    _STOP_REQUESTED = True


def _check_stop(ops):
    if ops.stop_requested():
        raise SafeStop("operator_stop", "operator requested a supervised stop")


def _bounded(value, limit=RESULT_LIMIT):
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str):
        value = str(value)
    if len(value) <= limit:
        return value
    suffix = "\n...[truncated]"
    return value[:limit - len(suffix)] + suffix


def _public_diagnostic(value):
    """Bound diagnostics and remove absolute paths before CLI/result exposure."""
    text = _bounded(value).strip()
    return re.sub(r"(?<![A-Za-z0-9_.-])/(?:[^\s\"'<>]+)", "<path>", text)


def _public_argv(argv):
    """Expose command intent without private executable/artifact paths."""
    public = []
    for index, item in enumerate(map(str, argv)):
        if item.startswith("/dev/"):
            public.append(item)
        elif item.startswith("/"):
            name = Path(item).name
            public.append(name if index == 0 else f"<path>/{name}")
        else:
            public.append(item)
    return public


def _run_isolated(argv, timeout):
    """Run one mutating tool in its own session, so terminal signals reach only the supervisor.

    The supervisor records a stop request and finishes the current step; a
    terminal Ctrl-C must not kill a swapoff, format or module load halfway.
    """
    command_name = Path(str(argv[0])).name if argv else "<missing>"
    try:
        return subprocess.run(
            [str(arg) for arg in argv], check=False, capture_output=True,
            text=True, timeout=timeout, start_new_session=True)
    except OSError as exc:
        raise PHYSICAL.ProbeError(
            f"command failed phase=spawn command={command_name} "
            f"errno={exc.errno}") from exc
    except subprocess.TimeoutExpired as exc:
        raise PHYSICAL.ProbeError(
            f"command failed phase=timeout command={command_name} "
            f"timeout_seconds={timeout}") from exc


def _durable_write(path, data, mode=0o600, exclusive=True):
    flags = os.O_WRONLY | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
    flags |= os.O_EXCL if exclusive else os.O_TRUNC
    fd = os.open(path, flags, mode)
    try:
        view = memoryview(data)
        offset = 0
        while offset < len(view):
            written = os.write(fd, view[offset:])
            if written <= 0:
                raise LiveSwapError("short write to durable trial evidence")
            offset += written
        os.fsync(fd)
    finally:
        os.close(fd)
    PHYSICAL._fsync_directory(Path(path).parent)


def _atomic_json(path, value):
    path = Path(path)
    tmp = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    data = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    try:
        _durable_write(tmp, data, exclusive=True)
        os.replace(tmp, path)
        PHYSICAL._fsync_directory(path.parent)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _load_unique_json(path):
    try:
        return PHYSICAL._load_unique_json(Path(path).read_bytes())
    except (OSError, ValueError) as exc:
        raise LiveSwapError(f"cannot read unambiguous JSON {Path(path).name}: {exc}") from exc


def _read_recovery_file(path, *, expected_mode=0o600):
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW |
                 os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or \
                info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != expected_mode:
            raise LiveSwapError("recovery evidence file ownership or mode is unsafe")
        chunks = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _assert_recovery_ownership(state, *, allow_released=False):
    base = PHYSICAL._recovery_base(state)
    expected = {"run_id": state["run_id"], "partuuid": state["partuuid"],
                "major": state["major"], "minor": state["minor"]}
    active_path = base / f"partition-{state['partuuid']}.active"
    consumed_path = base / f"consumed-{state['run_id']}.json"
    try:
        consumed = PHYSICAL._load_unique_json(
            _read_recovery_file(consumed_path))
    except (OSError, ValueError) as exc:
        raise LiveSwapError("permanent one-use consumption record is missing") from exc
    if consumed != expected:
        raise LiveSwapError("consumed run record differs from saved recovery identity")
    try:
        active = PHYSICAL._load_unique_json(_read_recovery_file(active_path))
    except FileNotFoundError:
        if allow_released and state.get("stage") == "COMPLETE":
            return False
        raise LiveSwapError("active recovery ownership marker is missing")
    except (OSError, ValueError) as exc:
        raise LiveSwapError("active recovery marker is unreadable") from exc
    if active != expected:
        raise LiveSwapError("another run owns the partition recovery marker")
    return True


def _parse_kv_status(output):
    """Parse the target's key=value status without accepting duplicates."""
    fields = {}
    for token in output.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        if not key or key in fields or not value:
            raise LiveSwapError("malformed or duplicate swapz status field")
        fields[key] = value
    required = {
        "logical_write", "logical_read", "physical_write", "physical_read",
        "failed", "error",
    }
    if not required.issubset(fields):
        raise LiveSwapError("swapz status is missing required counters")
    numeric = {}
    for key in required | {
            "flush_err", "segment_discards_failed", "gc_write", "gc_read"}:
        if key not in fields:
            continue
        if not re.fullmatch(r"[0-9]+", fields[key]):
            raise LiveSwapError(f"invalid numeric swapz status field: {key}")
        numeric[key] = int(fields[key])
    return numeric


def _approval_digest(record):
    return hashlib.sha256(
        (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        .encode()).hexdigest()


def validate_approval(record, *, head, helper_sha256, artifacts, target):
    """Validate the one-use live-trial binding: verbal review or owner waiver."""
    if not isinstance(record, dict):
        raise LiveSwapError("live-trial approval must be a JSON object")
    if record.get("approved") is not True or \
            record.get("approval_text") != LIVE_APPROVAL_TEXT or \
            record.get("owner_authorized") is not True or \
            record.get("owner_approval_text") != OWNER_APPROVAL_TEXT:
        raise LiveSwapError("owner authorization and exact approval text are required")
    mode = record.get("approval_mode")
    if mode == "verbal":
        if record.get("reviewer") != "openai-chatgpt-external-reviewer" or \
                record.get("source_policy_reviewed") is not True:
            raise LiveSwapError("verbal approval requires the named external reviewer")
    elif mode == "owner_waiver":
        if record.get("reviewer") is not None or \
                record.get("external_review") != "waived_by_owner" or \
                record.get("external_review_waiver") != OWNER_WAIVER_TEXT:
            raise LiveSwapError(
                "owner waiver must state the exact external-review waiver")
    else:
        raise LiveSwapError("approval_mode must be verbal or owner_waiver")
    review_reference = record.get("review_reference")
    if record.get("issue_number") != 76 or \
            record.get("reviewed_commit_sha") != head or \
            record.get("ci_commit_sha") != head or \
            record.get("ci_status") != "PASS" or \
            record.get("ci_workflows") != list(REQUIRED_CI_WORKFLOWS) or \
            not isinstance(review_reference, str) or \
            not re.fullmatch(
                r"https://github\.com/k1moradi/swapz/(?:issues/76(?:#issuecomment-[1-9][0-9]*)?|commit/[0-9a-f]{40})",
                review_reference):
        raise LiveSwapError("approval is not bound to the reviewed issue-76 change")
    if review_reference.startswith("https://github.com/k1moradi/swapz/commit/") and \
            review_reference.rsplit("/", 1)[1] != head:
        raise LiveSwapError("review commit reference must name the reviewed HEAD")
    run_id = record.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise LiveSwapError("approval requires a unique lowercase 32-hex run_id")
    expected = {
        "source_sha": QUALIFIED_SOURCE,
        "helper_git_sha": head,
        "helper_sha256": helper_sha256,
        "physical_helper_sha256": PHYSICAL_HELPER_SHA256,
        "device_uuid_path": DEVICE_UUID_PATH,
        "device": DEVICE_PATH,
        "device_major_minor": f"{DEVICE_MAJOR}:{DEVICE_MINOR}",
        "device_partuuid": DEVICE_PARTUUID,
        "device_size_bytes": DEVICE_SIZE_BYTES,
        "original_header_sha256": ORIGINAL_HEADER_SHA256,
        "logical_capacity_bytes": LOGICAL_BYTES,
        "duration_seconds": TRIAL_SECONDS,
        "pressure_pages": PRESSURE_PAGES,
        "pressure_memory_max_bytes": PRESSURE_MEMORY_MAX_BYTES,
        "scope": "experimental live Linux swap trial only",
    }
    if any(record.get(key) != value for key, value in expected.items()):
        raise LiveSwapError("approval does not match exact live-swap bindings")
    if record.get("artifact_digests") != artifacts:
        raise LiveSwapError("approval artifact hashes do not match live binaries")
    if not isinstance(target, dict) or any(target.get(key) != value for key, value in {
            "device": DEVICE_PATH, "major": DEVICE_MAJOR,
            "minor": DEVICE_MINOR, "partuuid": DEVICE_PARTUUID,
            "size_bytes": DEVICE_SIZE_BYTES,
    }.items()):
        raise LiveSwapError("live target evidence differs from approval binding")
    if record.get("fallback") is not None or \
            record.get("fallback_mode") != "none" or \
            record.get("accept_no_fallback_risk") is not True:
        raise LiveSwapError(
            "approval must explicitly bind the single-swap no-fallback mode")
    return run_id


class LinuxOps:
    """Read-only inspection and exact-command wrappers for the supervisor."""

    def command(self, argv, *, timeout=15, check=False):
        argv = [str(item) for item in argv]
        if not self._read_only_command_allowed(argv):
            raise LiveSwapError(
                "read-only plan refused mutating or unsupported command")
        return PHYSICAL._run(argv, timeout=timeout, check=check)

    @staticmethod
    def _read_only_command_allowed(argv):
        if not argv:
            return False
        name = Path(argv[0]).name
        if name == "dmsetup":
            return len(argv) > 1 and argv[1] in {
                "info", "table", "status", "deps", "ls",
            }
        if name == "systemd-detect-virt":
            return argv in ([argv[0], "--vm"], [argv[0], "--container"])
        if name == "journalctl":
            return len(argv) == 6 and argv[1:5] == [
                "--boot", "--kernel", "--no-pager", "--output=short-iso"] and \
                bool(re.fullmatch(
                    r"--since=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
                    argv[5]))
        if name == "dmesg":
            return argv == [argv[0], "--color=never", "--time-format=iso"]
        if name == "modinfo":
            return len(argv) == 4 and argv[1] == "-F" and \
                argv[2] in {"vermagic", "srcversion"} and \
                Path(argv[3]).name == "dm-swapz.ko" and \
                Path(argv[3]).parent.parent == RECOVERY_BASE and \
                bool(re.fullmatch(
                    r"swapz-live-[0-9a-f]{32}", Path(argv[3]).parent.name))
        if name == "blkid":
            return len(argv) == 7 and argv[1:6] == [
                "-p", "-s", "TYPE", "-o", "value"] and bool(
                    re.fullmatch(
                        r"/dev/mapper/swapz-live-[0-9a-f]{16}", argv[6]))
        if name == "gh":
            return list(argv) == list(GH_RUN_LIST_ARGS)
        if name == "runuser":
            return len(argv) == 4 + len(GH_RUN_LIST_ARGS) and \
                argv[1] == "--user" and argv[2] != "root" and \
                bool(re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", argv[2])) and \
                argv[3] == "--" and argv[4:] == list(GH_RUN_LIST_ARGS)
        return name in {"lsblk", "findmnt"}

    def mutate(self, argv, *, timeout=120):
        """Separate privileged operation channel, never used by plan."""
        argv = [str(item) for item in argv]
        if os.geteuid() != 0:
            raise LiveSwapError("privileged action requires root; no escalation")
        if not self._mutation_allowed(argv):
            raise LiveSwapError("supervisor refused an unreviewed mutation")
        return _run_isolated(argv, timeout=timeout)

    @staticmethod
    def _mutation_allowed(argv):
        if not argv:
            return False
        name = Path(argv[0]).name
        mapper = re.compile(r"^swapz-live-[0-9a-f]{16}$")
        mapper_uuid = re.compile(r"^SWAPZ-LIVE-[0-9a-f]{16}$")
        if name == "swapoff" and len(argv) == 3 and argv[1] == "--":
            return argv[2] in {DEVICE_PATH, DEVICE_UUID_PATH} or bool(
                re.fullmatch(r"/dev/mapper/swapz-live-[0-9a-f]{16}", argv[2]))
        if name == "swapon":
            if len(argv) == 3 and argv[1] == "--":
                return argv[2] in {DEVICE_PATH, DEVICE_UUID_PATH}
            return len(argv) == 5 and argv[1:3] == ["--priority", "32767"] and \
                argv[3] == "--" and bool(re.fullmatch(
                    r"/dev/mapper/swapz-live-[0-9a-f]{16}", argv[4]))
        if name == "mkswap":
            return len(argv) == 3 and argv[1] == "--" and bool(
                re.fullmatch(r"/dev/mapper/swapz-live-[0-9a-f]{16}", argv[2]))
        if name == "insmod":
            if len(argv) != 3 or argv[2] != "allow_physical_backing=1":
                return False
            path = Path(argv[1])
            return path.name == "dm-swapz.ko" and \
                path.parent.parent == RECOVERY_BASE and \
                bool(re.fullmatch(r"swapz-live-[0-9a-f]{32}", path.parent.name))
        if name == "rmmod":
            return argv == [argv[0], "dm_swapz"]
        if name == "dmsetup":
            if len(argv) == 7 and argv[1] == "create":
                _, _, dm_name, uuid_flag, dm_uuid, table_flag, table = argv
                token = dm_name.removeprefix(LIVE_NAME_PREFIX)
                return bool(re.fullmatch(r"[0-9a-f]{16}", token)) and \
                    uuid_flag == "--uuid" and \
                    dm_uuid == LIVE_UUID_PREFIX + token and \
                    table_flag == "--table" and table == (
                        f"0 {LOGICAL_SECTORS} swapz {DEVICE_PATH} "
                        "0 64 0 2 0 1 0 0")
            if len(argv) == 4 and argv[1:3] == ["remove", "--"]:
                return bool(mapper.fullmatch(argv[3]))
            return False
        if name == "swapzctl" and len(argv) == 7:
            _, command, device, major_flag, major_minor, size_flag, size = argv
            path = Path(argv[0])
            return command == "format" and device == DEVICE_PATH and \
                major_flag == "--expect-major-minor" and \
                major_minor == f"{DEVICE_MAJOR}:{DEVICE_MINOR}" and \
                size_flag == "--expect-bytes" and size == str(DEVICE_SIZE_BYTES) and \
                path.parent.parent == RECOVERY_BASE and path.name == "swapzctl" and \
                bool(re.fullmatch(r"swapz-live-[0-9a-f]{32}", path.parent.name))
        return False

    def text(self, path):
        return Path(path).read_text()

    def read_header(self, target):
        return PHYSICAL._read_block0(target["device"], target)

    def write_header(self, target, data, expected_current):
        PHYSICAL._write_block0(target["device"], data, target,
                               expected_current=expected_current)

    def inspect_target(self):
        target = PHYSICAL.inspect_target(
            DEVICE_UUID_PATH, DEVICE_UUID_PATH, allow_used_swap=True)
        if (target["device"], target["major"], target["minor"],
                target["partuuid"], target["size_bytes"]) != (
                DEVICE_PATH, DEVICE_MAJOR, DEVICE_MINOR, DEVICE_PARTUUID,
                DEVICE_SIZE_BYTES):
            raise LiveSwapError("selected partition identity differs from issue 76")
        if hashlib.sha256(target["header"]).hexdigest() != ORIGINAL_HEADER_SHA256:
            raise LiveSwapError("original swap header digest differs from issue 76")
        return target

    def recheck_target(self, state, *, expected_header=None,
                       require_active=False, require_zero=False):
        device = state["device"]
        if PHYSICAL.block_identity(device) != (
                state["major"], state["minor"]):
            raise LiveSwapError("selected block major:minor changed")
        result = self.command([
            "lsblk", "--json", "--bytes", "--nodeps",
            "--output", "TYPE,PARTUUID,SIZE", device,
        ])
        if result.returncode:
            raise LiveSwapError("cannot recheck selected partition identity")
        try:
            rows = json.loads(result.stdout).get("blockdevices", [])
        except (TypeError, ValueError) as exc:
            raise LiveSwapError("partition identity output is malformed") from exc
        if len(rows) != 1 or rows[0].get("type") != "part" or \
                str(rows[0].get("partuuid", "")).lower() != state["partuuid"] or \
                rows[0].get("size") != state["size_bytes"]:
            raise LiveSwapError("selected partition identity or geometry changed")
        parent_major_minor = PHYSICAL._physical_parent_identity(
            state["major"], state["minor"])
        if parent_major_minor != state.get("parent_major_minor"):
            raise LiveSwapError("selected partition physical parent changed")
        if PHYSICAL._mountinfo_has_device(state["major"], state["minor"]):
            raise LiveSwapError("selected partition became mounted")
        PHYSICAL._require_root_not_on_target(state["major"], state["minor"])
        header = self.read_header(state)
        digest = hashlib.sha256(header).hexdigest()
        if expected_header is not None and digest != expected_header:
            raise LiveSwapError("selected block-zero header changed unexpectedly")
        row = _active_swap_row(self, state["major"], state["minor"])
        if require_active and row is None:
            raise LiveSwapError("original swap is no longer active")
        if require_zero and row is not None and row["used_kib"] != 0:
            raise LiveSwapError("selected swap has nonzero usage")
        if not require_active and row is not None:
            raise LiveSwapError("selected partition is unexpectedly active as swap")
        if PHYSICAL._holder_names(state["major"], state["minor"]):
            raise LiveSwapError("selected partition has unexpected holders")
        return header

    def target_descriptor(self, state):
        device = state["device"]
        if PHYSICAL.block_identity(device) != (
                state["major"], state["minor"]):
            raise LiveSwapError("recovery block major:minor changed")
        result = self.command([
            "lsblk", "--json", "--bytes", "--nodeps",
            "--output", "TYPE,PARTUUID,SIZE", device,
        ])
        if result.returncode:
            raise LiveSwapError("cannot identify recovery partition")
        try:
            rows = json.loads(result.stdout).get("blockdevices", [])
        except (TypeError, ValueError) as exc:
            raise LiveSwapError("recovery partition output is malformed") from exc
        if len(rows) != 1 or rows[0].get("type") != "part" or \
                str(rows[0].get("partuuid", "")).lower() != state["partuuid"] or \
                rows[0].get("size") != state["size_bytes"]:
            raise LiveSwapError("recovery partition identity or geometry changed")
        if not (Path(f"/sys/dev/block/{state['major']}:{state['minor']}/partition").is_file()):
            raise LiveSwapError("recovery target is no longer a real partition")
        saved_parent = state.get("parent_major_minor")
        if saved_parent is not None and PHYSICAL._physical_parent_identity(
                state["major"], state["minor"]) != saved_parent:
            raise LiveSwapError("recovery partition physical parent changed")
        if PHYSICAL._mountinfo_has_device(state["major"], state["minor"]):
            raise LiveSwapError("recovery partition became mounted")
        PHYSICAL._require_root_not_on_target(state["major"], state["minor"])
        target = {
            "device": device,
            "major": state["major"],
            "minor": state["minor"],
            "size_bytes": state["size_bytes"],
            "partuuid": state["partuuid"],
        }
        target["header"] = self.read_header(target)
        return target

    def target_holders(self, major, minor):
        return PHYSICAL._holder_names(major, minor)

    def active_swap_for(self, major, minor):
        return _active_swap_row(self, major, minor)

    def verify_module(self, module_path):
        if not self.module_loaded():
            raise LiveSwapError("dm_swapz did not appear after insertion")
        try:
            enabled = Path(
                "/sys/module/dm_swapz/parameters/allow_physical_backing"
            ).read_text().strip().lower()
        except OSError as exc:
            raise LiveSwapError("cannot verify module physical-backing opt-in") from exc
        if enabled not in {"y", "1"}:
            raise LiveSwapError("dm_swapz physical backing opt-in is disabled")
        info = self.command(["modinfo", "-F", "vermagic", str(module_path)])
        if info.returncode or not info.stdout.strip().startswith(platform.release()):
            raise LiveSwapError("qualified module vermagic differs from running kernel")
        srcversion = self.command(["modinfo", "-F", "srcversion", str(module_path)])
        try:
            loaded_srcversion = Path(
                "/sys/module/dm_swapz/srcversion").read_text().strip()
        except OSError as exc:
            raise LiveSwapError("cannot verify loaded module source identity") from exc
        if srcversion.returncode or not srcversion.stdout.strip() or \
                srcversion.stdout.strip() != loaded_srcversion:
            raise LiveSwapError("loaded dm_swapz differs from the snapshotted module")

    def verify_mapper(self, state, *, allow_open=False):
        return _verify_mapper(self, state, allow_open=allow_open)

    def verify_mapper_swap_signature(self, state, mapper):
        self.verify_mapper(state, allow_open=False)
        result = self.command([
            "blkid", "-p", "-s", "TYPE", "-o", "value", mapper,
        ])
        if result.returncode or result.stdout.strip() != "swap":
            raise LiveSwapError("swap signature is absent from verified mapper")
        return True

    def stop_requested(self):
        return _STOP_REQUESTED

    def artifact_digests(self):
        return PHYSICAL._artifact_digests()

    def qualification_matches(self):
        try:
            report = json.loads((ROOT / "test_results.json").read_text())
        except (OSError, ValueError):
            return False
        host = PHYSICAL.live_host_identity()
        return (
            isinstance(report, dict)
            and report.get("source_sha") == QUALIFIED_SOURCE
            and report.get("tested_commit_sha") == QUALIFIED_SOURCE
            and PHYSICAL._report_is_owner_pass(report, host)
            and PHYSICAL._report_artifact_digests(report) == EXPECTED_ARTIFACTS
        )

    def recovery_base(self, target):
        return PHYSICAL._recovery_base(target)

    def repo_snapshot(self):
        def git(*args, check=True):
            result = PHYSICAL._git_result(*args, timeout=20, check=False)
            if check and result.returncode:
                raise LiveSwapError(
                    f"git {' '.join(args)} failed: {_bounded(result.stderr)}")
            return result.stdout.strip()

        ancestry_result = PHYSICAL._git_result(
            "merge-base", "--is-ancestor", QUALIFIED_SOURCE, "HEAD",
            timeout=20, check=False)
        canonical_main = PHYSICAL._remote_main_sha()
        changed = git(
            "diff", "--name-only", f"{QUALIFIED_SOURCE}...HEAD").splitlines()
        merge_result = PHYSICAL._git_result(
            "rev-list", "--merges", f"{QUALIFIED_SOURCE}..HEAD",
            timeout=20, check=False)
        production_paths = [
            path for path in changed
            if path.startswith("src/") or path.startswith("include/") or
            path in {
                "Makefile", "tests/Makefile",
                "tests/tools/device-roundtrip.c",
                "tests/tools/build-kernel.sh",
            }
        ]
        return {
            "branch": git("branch", "--show-current"),
            "head": git("rev-parse", "HEAD"),
            "origin_main": git("rev-parse", "origin/main"),
            "canonical_main": canonical_main,
            "dirty": bool(git("status", "--porcelain")),
            "clean": not bool(git("status", "--porcelain")),
            "source_ancestor": ancestry_result.returncode == 0,
            "no_post_qualification_merges": (
                merge_result.returncode == 0 and not merge_result.stdout.strip()),
            "production_diff": production_paths,
            "changed_paths": changed,
        }

    def host_physical(self):
        if platform.machine() != "x86_64":
            raise LiveSwapError("live-swap trial is restricted to x86_64")
        PHYSICAL._require_physical_host()
        return True

    def dm_rows(self):
        result = self.command([
            "dmsetup", "info", "-c", "--noheadings", "-o", "name,uuid",
        ])
        if result.returncode:
            raise LiveSwapError("cannot enumerate Device Mapper inventory")
        return PHYSICAL._dm_info_rows(result.stdout, 2)

    def module_loaded(self):
        return Path("/sys/module/dm_swapz").exists()

    def module_refcount(self):
        try:
            value = Path("/sys/module/dm_swapz/refcnt").read_text().strip()
        except OSError as exc:
            raise LiveSwapError("cannot read dm_swapz module reference count") from exc
        if not re.fullmatch(r"[0-9]+", value):
            raise LiveSwapError("dm_swapz module reference count is malformed")
        return int(value)

    def memory_facts(self):
        values = {}
        for line in self.text("/proc/meminfo").splitlines():
            key, _, rest = line.partition(":")
            fields = rest.split()
            if fields and key in {"MemAvailable", "MemTotal"}:
                values[key] = int(fields[0]) * 1024
        if not {"MemAvailable", "MemTotal"}.issubset(values) or \
                values["MemTotal"] <= 0 or values["MemAvailable"] > values["MemTotal"]:
            raise LiveSwapError("MemAvailable or MemTotal is unavailable or invalid")
        values["ram_used_percent"] = (
            100.0 * (values["MemTotal"] - values["MemAvailable"]) /
            values["MemTotal"])
        values["psi_some_avg10"], values["psi_full_avg10"] = (
            self._psi_avg10(self.text("/proc/pressure/memory")))
        values["cgroup_headroom"] = self._cgroup_headroom()
        return values

    def kernel_diagnostics(self, start_timestamp, state):
        """Return bounded swapz/OOM/lower-device diagnostics for this run."""
        journalctl_error = None
        filters = [
            r"swapz|dm-swapz",
            r"\b(?:oom|out of memory|killed process)\b",
            r"warning:|\bwarn\b|bug:|oops:|call trace:",
            r"blk_update_request|I/O error|buffer I/O error|critical medium error|end_request",
        ]
        device = Path(state.get("device", DEVICE_PATH)).name
        if device:
            filters.append(rf"\b{re.escape(device)}\b")
            parent = Path(device).name
            if parent and parent[-1:].isdigit():
                parent = parent.rstrip("0123456789")
                if parent:
                    filters.append(rf"\b{re.escape(parent)}\b")
        mapper = state.get("dm_name")
        if isinstance(mapper, str) and re.fullmatch(
                r"swapz-live-[0-9a-f]{16}", mapper):
            filters.append(re.escape(mapper))
        pattern = re.compile("|".join(f"(?:{item})" for item in filters),
                             re.IGNORECASE)
        journalctl = shutil.which("journalctl")
        if journalctl:
            argv = [journalctl, "--boot", "--kernel", "--no-pager",
                    "--output=short-iso", f"--since={start_timestamp}"]
            try:
                result = self.command(argv, timeout=20, check=False)
                if result.returncode == 0:
                    matching = [line for line in result.stdout.splitlines()
                                if pattern.search(line)]
                    return {
                        "available": True, "source": "journalctl",
                        "time_filter_applied": True,
                        "matching_line_count": len(matching),
                        "messages": _bounded("\n".join(matching[-32:])),
                    }
                journalctl_error = _bounded(result.stderr or result.stdout)
            except (LiveSwapError, PHYSICAL.ProbeError) as exc:
                journalctl_error = _bounded(exc)
        dmesg = shutil.which("dmesg")
        if not dmesg:
            return {"available": False, "source": None,
                    "time_filter_applied": False,
                    "journalctl_error": journalctl_error,
                    "error": "journalctl and dmesg are unavailable"}
        try:
            result = self.command(
                [dmesg, "--color=never", "--time-format=iso"],
                timeout=20, check=False)
        except (LiveSwapError, PHYSICAL.ProbeError) as exc:
            return {"available": False, "source": "dmesg",
                    "time_filter_applied": False,
                    "journalctl_error": journalctl_error,
                    "error": _bounded(exc)}
        if result.returncode:
            return {"available": False, "source": "dmesg",
                    "time_filter_applied": False,
                    "journalctl_error": journalctl_error,
                    "return_code": result.returncode,
                    "error": _bounded(result.stderr or result.stdout)}
        matching = [line for line in result.stdout.splitlines()
                    if pattern.search(line)]
        return {"available": True, "source": "dmesg",
                "time_filter_applied": False,
                "journalctl_error": journalctl_error,
                "matching_line_count": len(matching),
                "messages": _bounded("\n".join(matching[-32:]))}

    @staticmethod
    def _psi_avg10(contents):
        """Require exactly one finite memory-PSI average per category."""
        rows = {}
        for line in contents.splitlines():
            fields = line.split()
            if not fields or fields[0] not in {"some", "full"}:
                continue
            category = fields[0]
            if category in rows:
                raise LiveSwapError(f"memory PSI duplicate category={category}")
            values = {}
            for field in fields[1:]:
                key, separator, value = field.partition("=")
                if not separator or not key or key in values:
                    raise LiveSwapError(f"memory PSI malformed category={category}")
                values[key] = value
            try:
                average = float(values["avg10"])
            except (KeyError, ValueError, OverflowError) as exc:
                raise LiveSwapError(
                    f"memory PSI missing/invalid avg10 category={category}") from exc
            if not math.isfinite(average) or not 0 <= average <= 100:
                raise LiveSwapError(f"memory PSI out-of-range category={category}")
            rows[category] = average
        if set(rows) != {"some", "full"}:
            raise LiveSwapError("memory PSI missing some/full categories")
        return rows["some"], rows["full"]

    def _cgroup_headroom(self):
        """Only an explicitly unlimited parent has no numeric headroom."""
        try:
            cgroup = next(line.split(":", 2)[2] for line in
                          self.text("/proc/self/cgroup").splitlines()
                          if line.startswith("0::"))
            base = Path("/sys/fs/cgroup") / cgroup.lstrip("/")
            maximum = (base / "memory.max").read_text().strip()
            current = (base / "memory.current").read_text().strip()
            if not re.fullmatch(r"[0-9]+", current):
                raise ValueError("invalid parent current charge")
            if maximum == "max":
                return None
            if not re.fullmatch(r"[0-9]+", maximum):
                raise ValueError("invalid parent maximum")
            return max(0, int(maximum) - int(current))
        except (OSError, StopIteration, ValueError) as exc:
            raise LiveSwapError(
                "cgroup parent headroom unavailable; admission=BLOCKED") from exc


    def pressure_workload(self, state, *, cgroup_name, guard, stop_requested, timeout):
        """Own one fork child and report all cleanup failures without losing its cause."""
        run_id = state["run_id"]
        if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
            raise LiveSwapError("pressure seed must be the bound run id")
        if not re.fullmatch(r"swapz-live-[0-9a-f]{16}", str(cgroup_name)):
            raise LiveSwapError("pressure cgroup name is malformed")
        cgroup = PRESSURE_CGROUP_ROOT / cgroup_name
        if cgroup.exists():
            raise LiveSwapError("pressure cgroup name is already in use")
        try:
            os.mkdir(cgroup, 0o755)
        except OSError as exc:
            raise LiveSwapError(
                f"phase=cgroup_create errno={exc.errno} "
                "retained=unowned_or_unknown") from exc
        outcome = {"cgroup": str(cgroup), "timed_out": False, "stopped": False,
                   "child_reaped": False, "cgroup_removed": False}
        pid = None
        read_fd = None
        status = None
        first_error = None
        cleanup_errors = []
        phase = "cgroup_admission"
        try:
            _write_control(cgroup / "memory.max", str(PRESSURE_MEMORY_MAX_BYTES))
            _require_control(cgroup / "memory.max", str(PRESSURE_MEMORY_MAX_BYTES))
            if (cgroup / "memory.swap.max").exists():
                _write_control(cgroup / "memory.swap.max", "max")
                _require_control(cgroup / "memory.swap.max", "max")
            if not (cgroup / "memory.zswap.max").exists():
                raise LiveSwapError(
                    "pressure cgroup cannot disable zswap; pressure would not reach the device")
            _write_control(cgroup / "memory.zswap.max", "0")
            _require_control(cgroup / "memory.zswap.max", "0")
            phase = "child_spawn"
            pid, read_fd = _spawn_pressure_child(
                cgroup, run_id, PRESSURE_PAGES, PRESSURE_TIMEOUT_SECONDS + 60)
            started = time.monotonic()
            last_guard = started
            phase = "worker_watch"
            while True:
                waited, code = os.waitpid(pid, os.WNOHANG)
                if waited == pid:
                    status = code
                    break
                if stop_requested():
                    outcome["stopped"] = True
                    break
                if time.monotonic() - started >= timeout:
                    outcome["timed_out"] = True
                    break
                if time.monotonic() - last_guard >= SAMPLE_SECONDS:
                    phase = "pressure_guard"
                    guard()
                    phase = "worker_watch"
                    last_guard = time.monotonic()
                time.sleep(1)
        except BaseException as exc:
            first_error = exc

        # Only our unreaped direct child's PID may be signalled. Never signal
        # the entire cgroup: untrusted membership is not ownership proof.
        if pid is not None and status is None:
            try:
                status = _terminate_pressure_child(cgroup, pid)
            except BaseException as exc:
                cleanup_errors.append(("child_reap", exc))
        if pid is not None and status is not None:
            outcome["child_reaped"] = True
            outcome["exit_code"] = os.waitstatus_to_exitcode(status)
        if read_fd is not None:
            try:
                if status is not None:
                    outcome["stdout"] = _read_all_fd(read_fd)
            except BaseException as exc:
                cleanup_errors.append(("child_report", exc))
            finally:
                try:
                    os.close(read_fd)
                except OSError as exc:
                    cleanup_errors.append(("child_pipe_close", exc))
        for label, reader in (
                ("memory_events", lambda: _read_memory_events(cgroup)),
                ("swap_peak_bytes", lambda: _read_int_control(
                    cgroup / "memory.swap.peak")),
                ("zswap_peak_bytes", lambda: _read_int_control(
                    cgroup / "memory.zswap.peak"))):
            try:
                outcome[label] = reader()
            except BaseException as exc:
                cleanup_errors.append((label, exc))
        if pid is None or status is not None:
            try:
                _remove_empty_cgroup(cgroup)
                outcome["cgroup_removed"] = True
            except BaseException as exc:
                cleanup_errors.append(("cgroup_remove", exc))

        if cleanup_errors:
            cleanup_detail = ",".join(
                f"{label}:{type(exc).__name__}:errno={getattr(exc, 'errno', None)}"
                for label, exc in cleanup_errors)
            retained = ("child_and_cgroup" if pid is not None and status is None
                        else "cgroup_or_telemetry")
            detail = (f"; cleanup={cleanup_detail}; retained={retained}; "
                      f"exit={outcome.get('exit_code')}; timed_out={outcome['timed_out']}")
        else:
            detail = ""
        if first_error is not None:
            original = (f"phase={phase} original={type(first_error).__name__}"
                        f" errno={getattr(first_error, 'errno', None)}")
            if isinstance(first_error, SafeStop):
                first_error.args = (
                    f"{original} category={first_error.reason} "
                    f"detail={_bounded(first_error)}{detail}",)
                raise first_error
            if isinstance(first_error, LiveSwapError):
                original += f" detail={_bounded(first_error)}"
            raise LiveSwapError(f"{original}{detail}") from first_error
        if cleanup_errors:
            child = _parse_pressure_child_output(outcome.get("stdout", ""))
            observed_pages = child.get("verified_pages") if child else None
            observed_bytes = child.get("verified_bytes") if child else None
            report_failure = _pressure_report_failure(
                child, run_id, PRESSURE_PAGES)
            memory_failure = _pressure_memory_event_failure(
                outcome.get("memory_events"))
            if outcome["timed_out"]:
                phase_name = "worker_timeout"
            elif outcome["stopped"]:
                phase_name = "operator_stop"
            elif outcome.get("exit_code") != 0 or \
                    report_failure is not None or memory_failure is not None:
                phase_name = "pressure_verify"
            else:
                phase_name = "pressure_teardown"
            raise LiveSwapError(
                f"phase={phase_name} original_exit={outcome.get('exit_code')} "
                f"admission=memory/PSI/cgroup "
                f"report={report_failure or 'valid'} "
                f"memory_events={memory_failure or 'zero_oom'} "
                f"expected_pages={PRESSURE_PAGES} observed_pages={observed_pages} "
                f"expected_bytes={PRESSURE_PAGES * PAGE_BYTES} "
                f"observed_bytes={observed_bytes}{detail}") from cleanup_errors[0][1]
        return outcome

    def ci_status(self, head):
        """Ask GitHub, as the operator who holds gh credentials, which workflows passed."""
        argv = list(GH_RUN_LIST_ARGS)
        operator = os.environ.get("SUDO_USER")
        if os.geteuid() == 0 and operator and operator != "root":
            runuser = shutil.which("runuser")
            if not runuser:
                raise LiveSwapError("runuser is required to query CI as the operator")
            argv = [runuser, "--user", operator, "--", *argv]
        result = self.command(argv, timeout=60, check=False)
        if result.returncode:
            raise LiveSwapError("cannot query GitHub workflow results")
        try:
            runs = json.loads(result.stdout)
        except ValueError as exc:
            raise LiveSwapError("GitHub workflow results are malformed") from exc
        if not isinstance(runs, list):
            raise LiveSwapError("GitHub workflow results are malformed")
        passed = {run.get("name") for run in runs
                  if isinstance(run, dict) and run.get("headSha") == head and
                  run.get("status") == "completed" and
                  run.get("conclusion") == "success"}
        ok = set(REQUIRED_CI_WORKFLOWS).issubset(passed)
        return {"status": "PASS" if ok else "BLOCKED", "commit_sha": head,
                "workflows": list(REQUIRED_CI_WORKFLOWS) if ok else []}

    def release_pressure_cgroup(self, state):
        """Never remove a surviving cgroup whose inode was not durably bound."""
        name = state.get("pressure_cgroup")
        if not name:
            return False
        if not re.fullmatch(r"swapz-live-[0-9a-f]{16}", str(name)):
            raise LiveSwapError("saved pressure cgroup name is malformed")
        cgroup = PRESSURE_CGROUP_ROOT / name
        if not cgroup.exists():
            return False
        # pressure_workload removes the group before returning success. After
        # an interruption only its name is durable, not inode ownership, so a
        # later same-name cgroup must be retained rather than modified.
        raise LiveSwapError(
            "phase=pressure_recovery ownership=unproven retained=cgroup")

    def swapoff_processes(self):
        """Pids whose command is swapoff, so recovery never races a live swapoff.

        A process that exits during the scan is skipped. Any other read failure
        is an error: an entry that cannot be read could be a live swapoff.
        """
        found = []
        for entry in PROC_ROOT.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                argv = (entry / "cmdline").read_bytes().split(b"\0")
            except (FileNotFoundError, ProcessLookupError):
                continue
            except OSError as exc:
                raise LiveSwapError(
                    f"cannot read {entry.name}/cmdline; manual review") from exc
            if argv and argv[0] and \
                    Path(argv[0].decode("utf-8", "replace")).name == "swapoff":
                found.append(int(entry.name))
        return found

    def read_swap_rows(self):
        return PHYSICAL.parse_swap_rows(self.text("/proc/swaps"))


def _validate_target_facts(target):
    if not isinstance(target, dict):
        raise LiveSwapError("selected partition evidence is unavailable")
    expected = {
        "device": DEVICE_PATH,
        "major": DEVICE_MAJOR,
        "minor": DEVICE_MINOR,
        "partuuid": DEVICE_PARTUUID,
        "size_bytes": DEVICE_SIZE_BYTES,
        "swap_size_kib": DEVICE_SIZE_BYTES // 1024 - PAGE_BYTES // 1024,
        "swap_priority": -1,
    }
    if any(target.get(key) != value for key, value in expected.items()):
        raise LiveSwapError("selected partition facts do not match the fixed target")
    parent_major_minor = target.get("parent_major_minor")
    if not isinstance(parent_major_minor, str) or not re.fullmatch(
            r"[0-9]+:[0-9]+", parent_major_minor):
        raise LiveSwapError("selected physical parent identity is unavailable")
    if parent_major_minor == f"{target['major']}:{target['minor']}":
        raise LiveSwapError("selected partition cannot be its own physical parent")
    if type(target.get("swap_used_kib")) is not int or \
            not 0 <= target["swap_used_kib"] <= target["swap_size_kib"]:
        raise LiveSwapError("selected swap usage is missing or outside its capacity")
    if hashlib.sha256(target.get("header", b"")).hexdigest() != \
            ORIGINAL_HEADER_SHA256:
        raise LiveSwapError("selected partition header does not match original")


def _exact_active_swap_inventory(ops):
    """The original partition must be the sole active swap area."""
    if _observed_swap_identities(ops) != {f"block:{DEVICE_MAJOR}:{DEVICE_MINOR}"}:
        raise LiveSwapError(
            "active swap inventory differs from the sole original swap area")
    return True


def _observed_swap_identities(ops):
    observed = set()
    for row in ops.read_swap_rows():
        if row["kind"] == "file":
            identity = "file:" + os.path.realpath(row["path"])
        else:
            try:
                major, minor = PHYSICAL.block_identity(row["path"])
            except PHYSICAL.ProbeError as exc:
                raise LiveSwapError("cannot identify an active swap device") from exc
            identity = f"block:{major}:{minor}"
        if identity in observed:
            raise LiveSwapError("duplicate active swap inventory entry")
        observed.add(identity)
    return observed


def _reconcile_trial_state(state_dir, state, ops):
    """Make persisted flags agree with the kernel before the cleanup inventory check.

    The mapper flag is set only after a successful post-swapon check, so a
    failed check or a crash can leave it false while the mapper is live, or
    true after the mapper vanished. The kernel's tables decide. A device that
    is still listed may be draining, so no swapoff process may run in a swapoff
    stage, whether or not the listing still shows the device.
    """
    stage = _resolved_stage(state)
    if stage in SWAPOFF_STAGES and ops.swapoff_processes():
        raise LiveSwapError(
            "an orphaned swapoff is still running; manual review")
    rows = _mapper_rows_for_state(ops, state)
    if not rows:
        state["active_mapper_swap"] = False
    else:
        dm_major, dm_minor, _ = _mapper_info(ops, state)
        state["dm_major"], state["dm_minor"] = dm_major, dm_minor
        state["active_mapper_swap"] = \
            ops.active_swap_for(dm_major, dm_minor) is not None
    if stage == "ORIGINAL_SWAPOFF_PENDING" and \
            not state.get("original_swapoff_complete") and \
            ops.active_swap_for(state["major"], state["minor"]) is None:
        state["original_swapoff_complete"] = True
    _save_state(state_dir, state)


def _verify_trial_swap_inventory(ops, state):
    original = {f"block:{DEVICE_MAJOR}:{DEVICE_MINOR}"}
    if state.get("active_mapper_swap"):
        allowed = [{f"block:{state['dm_major']}:{state['dm_minor']}"}]
    elif state.get("original_swap_restored") or \
            not state.get("original_swapoff_complete"):
        allowed = [original]
    elif _resolved_stage(state) == "ORIGINAL_SWAPON_PENDING":
        # A crash can fall before or after the swapon; both outcomes are valid.
        allowed = [set(), original]
    else:
        allowed = [set()]
    if _observed_swap_identities(ops) not in allowed:
        raise LiveSwapError("live swap inventory differs from the sole owned swap area")
    return True


def evaluate_plan(facts):
    """Pure gate evaluation. It never runs commands or writes files."""
    gates = {}

    def gate(name, condition, detail):
        gates[name] = {"status": "PASS" if condition else "BLOCKED",
                       "detail": detail}

    repo = facts.get("repo", {})
    gate("repository", repo.get("branch") == "main" and
         repo.get("clean") is True and repo.get("head") == repo.get("origin_main") and
         repo.get("head") == repo.get("canonical_main") and
         repo.get("source_ancestor") is True,
         "requires clean main synchronized with local origin and canonical GitHub main")
    gate("production_inputs", not repo.get("production_diff"),
         "production C, oracle and build inputs must remain unchanged")
    changed_paths = repo.get("changed_paths", [])
    gate("post_qualification_path_policy",
         isinstance(changed_paths, list) and
         set(changed_paths).issubset(POST_QUALIFICATION_PATHS),
         "only the reviewed supervisor, focused tests and safety records may change")
    gate("history_shape", repo.get("no_post_qualification_merges") is True,
         "post-qualification history must be linear")
    gate("host", facts.get("physical_x86_64") is True,
         "requires a positively identified bare-metal x86_64 host")
    target = facts.get("target", {})
    target_ok = all(target.get(key) == value for key, value in {
        "device": DEVICE_PATH, "major": DEVICE_MAJOR, "minor": DEVICE_MINOR,
        "partuuid": DEVICE_PARTUUID, "size_bytes": DEVICE_SIZE_BYTES,
        "swap_priority": -1,
        "header_sha256": ORIGINAL_HEADER_SHA256,
        "mounted": False, "holders": [],
        "root_chain_contains_target": False,
    }.items())
    target_used_kib = target.get("swap_used_kib")
    target_size_kib = target.get("swap_size_kib")
    target_ok = target_ok and type(target_used_kib) is int and \
        type(target_size_kib) is int and 0 <= target_used_kib <= target_size_kib
    gate("target", target_ok,
         "exact original active swap partition, saved header and no conflicts")
    gate("swap_inventory", facts.get("swap_inventory_exact") is True,
         "only the selected original swap partition may be active")
    gate("artifacts", facts.get("artifacts") == EXPECTED_ARTIFACTS,
         "all three qualified artifact digests must match")
    gate("owner_qualification", facts.get("qualification_matches") is True,
         "latest exact-source x86_64 owner PASS and artifact hashes must match")
    ci = facts.get("ci", {})
    gate("current_ci", ci.get("status") == "PASS" and
         ci.get("commit_sha") == repo.get("head") and
         ci.get("workflows") == list(REQUIRED_CI_WORKFLOWS),
         "both required non-privileged workflows must pass for current HEAD")
    recovery = facts.get("recovery", {})
    gate("recovery_storage", recovery.get("persistent") is True and
         recovery.get("outside_target") is True and recovery.get("root_owned_0700") is True and
         recovery.get("active_marker") is False and
         recovery.get("other_unresolved_markers") == [],
         "durable root-only storage and no unresolved recovery owner")
    gate("module_and_mapper", facts.get("module_loaded") is False and
         facts.get("owned_mapper_present") is False,
         "no pre-existing swapz module or live-trial mapper")
    approval = facts.get("approval")
    fallback = facts.get("fallback")
    no_fallback_ok = facts.get("fallback") is None and \
        isinstance(approval, dict) and approval.get("fallback_mode") == "none" and \
        approval.get("accept_no_fallback_risk") is True
    gate("fallback", no_fallback_ok,
         "owner and reviewer explicitly bind /dev/sda4 as the sole swap area")
    gate("fallback_media_risk", no_fallback_ok,
         "no fallback swap area is active or created")
    memory = facts.get("memory", {})
    numeric_keys = ("mem_available_bytes", "mem_total_bytes", "ram_used_percent",
                    "psi_some_avg10", "psi_full_avg10")
    numeric = all(isinstance(memory.get(key), (int, float)) and
                  not isinstance(memory.get(key), bool) for key in numeric_keys)
    cgroup_value = memory.get("cgroup_headroom_bytes")
    cgroup_ok = cgroup_value is None or (
        isinstance(cgroup_value, int) and cgroup_value >= MIN_CGROUP_HEADROOM_BYTES)
    original_swap_bytes = target_used_kib * 1024 if type(target_used_kib) is int else None
    original_drain_headroom = (
        memory.get("mem_available_bytes") - original_swap_bytes - MIN_AVAILABLE_BYTES
        if numeric and original_swap_bytes is not None else -1)
    memory_ok = numeric and \
        memory.get("mem_available_bytes") >= MIN_AVAILABLE_BYTES and \
        memory.get("mem_total_bytes") > 0 and \
        memory.get("ram_used_percent") < 50.0 and \
        original_drain_headroom >= TRIAL_HEADROOM_BYTES and \
        cgroup_ok and \
        memory.get("psi_some_avg10") < MAX_MEMORY_SOME_AVG10 and \
        memory.get("psi_full_avg10") < MAX_MEMORY_FULL_AVG10
    gate("memory", memory_ok,
         "RAM use < 50%, MemAvailable covers current swap plus the 2 GiB reserve "
         "and 1 GiB trial headroom, cgroup headroom >= 512 MiB when limited, "
         "PSI some < 5% and full < 1%")


    approval_ok = isinstance(approval, dict) and \
        approval.get("validated") is True and \
        approval.get("run_id_unconsumed") is True and \
        approval.get("state_directory_unused") is True
    gate("one_use_review", approval_ok,
         "requires a one-use approval bound to this commit with owner "
         "authorization and either verbal external review or the exact waiver")
    return {
        "schema": "swapz-live-swap-plan-v1",
        "read_only": True,
        "status": "PASS" if all(g["status"] == "PASS"
                                for g in gates.values()) else "BLOCKED",
        "gates": gates,
        "head": repo.get("head"),
        "device": target.get("device"),
        "fallback": fallback,
        "original_swap_drain_headroom_bytes": original_drain_headroom,
    }


def collect_plan_facts(approval_path, ops=None):
    ops = ops or LinuxOps()
    facts = {}
    errors = []
    try:
        facts["physical_x86_64"] = ops.host_physical()
    except Exception as exc:
        facts["physical_x86_64"] = False
        errors.append(_bounded(exc))
    try:
        target = ops.inspect_target()
        _validate_target_facts(target)
        target["header_sha256"] = hashlib.sha256(target["header"]).hexdigest()
        target["mounted"] = False
        target["holders"] = []
        target["root_chain_contains_target"] = False
        facts["target"] = target
    except Exception as exc:
        facts["target"] = {}
        errors.append(_bounded(exc))
    try:
        facts["repo"] = ops.repo_snapshot()
    except Exception as exc:
        facts["repo"] = {}
        errors.append(_bounded(exc))
    try:
        facts["artifacts"] = ops.artifact_digests()
    except Exception as exc:
        facts["artifacts"] = {}
        errors.append(_bounded(exc))
    try:
        facts["qualification_matches"] = ops.qualification_matches()
    except Exception as exc:
        facts["qualification_matches"] = False
        errors.append(_bounded(exc))
    try:
        target = facts.get("target")
        base = ops.recovery_base(target) if target else PHYSICAL.RECOVERY_BASE
        markers = sorted(path.name for path in base.glob("partition-*.active"))
        facts["recovery"] = {
            "persistent": True,
            "outside_target": True,
            "root_owned_0700": (
                base.is_dir() and base.stat().st_uid == 0 and
                stat.S_IMODE(base.stat().st_mode) == 0o700),
            "active_marker": (
                base / f"partition-{DEVICE_PARTUUID}.active").exists(),
            "other_unresolved_markers": [
                name for name in markers
                if name != f"partition-{DEVICE_PARTUUID}.active"],
        }
    except Exception as exc:
        facts["recovery"] = {}
        errors.append(_bounded(exc))
    try:
        rows = ops.dm_rows()
        facts["module_loaded"] = ops.module_loaded()
        facts["owned_mapper_present"] = any(
            name.startswith(LIVE_NAME_PREFIX) or
            uuid.startswith(LIVE_UUID_PREFIX) for name, uuid in rows)
    except Exception as exc:
        facts["module_loaded"] = None
        facts["owned_mapper_present"] = None
        errors.append(_bounded(exc))
    try:
        facts["memory"] = {
            "mem_available_bytes": None,
            "cgroup_headroom_bytes": None,
        }
        raw = ops.memory_facts()
        facts["memory"] = {
            "mem_available_bytes": raw["MemAvailable"],
            "mem_total_bytes": raw["MemTotal"],
            "ram_used_percent": raw["ram_used_percent"],
            "cgroup_headroom_bytes": raw.get("cgroup_headroom"),
            "psi_some_avg10": raw["psi_some_avg10"],
            "psi_full_avg10": raw["psi_full_avg10"],
        }
    except Exception as exc:
        errors.append(_bounded(exc))
    try:
        facts["ci"] = ops.ci_status((facts.get("repo") or {}).get("head"))
    except Exception as exc:
        facts["ci"] = {"status": None, "commit_sha": None, "workflows": None}
        errors.append(_bounded(exc))
    try:
        approval = _load_unique_json(approval_path)
        facts["approval_sha256"] = _approval_digest(approval)
        fallback = None
        facts["swap_inventory_exact"] = _exact_active_swap_inventory(ops)
        facts["fallback"] = None
        artifacts = facts.get("artifacts", {})
        repo = facts.get("repo", {})
        target = facts.get("target", {})
        validate_approval(
            approval,
            head=repo.get("head"),
            helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            artifacts=artifacts,
            target=target,
        )
        base = ops.recovery_base(target)
        run_id = approval["run_id"]
        state_dir = base / f"swapz-live-{run_id}"
        approval["run_id_unconsumed"] = not (
            base / f"consumed-{run_id}.json").exists()
        approval["state_directory_unused"] = not state_dir.exists()
        approval["validated"] = True
        if not approval["run_id_unconsumed"] or \
                not approval["state_directory_unused"]:
            raise LiveSwapError("run id or live state directory has already been used")
        facts["approval"] = approval
    except Exception as exc:
        facts["fallback"] = None
        facts["approval"] = None
        facts.setdefault("ci", {})
        errors.append(_bounded(exc))
    facts["errors"] = errors
    return facts


def read_only_plan(approval_path, ops=None):
    facts = collect_plan_facts(approval_path, ops=ops)
    plan = evaluate_plan(facts)
    plan["errors"] = facts.get("errors", [])
    plan["approval_sha256"] = facts.get("approval_sha256")
    # Inert description of the future sequence; no mutation is run here and
    # a PASS still requires the one-use approval bound to this commit.
    plan["operation_trace"] = list(PLANNED_MUTATION_TRACE)
    return plan


def _target_state(target):
    return {
        "device_arg": DEVICE_UUID_PATH,
        "device": target["device"],
        "major": target["major"],
        "minor": target["minor"],
        "parent_major_minor": target["parent_major_minor"],
        "partuuid": target["partuuid"],
        "size_bytes": target["size_bytes"],
        "original_header_sha256": ORIGINAL_HEADER_SHA256,
        "swap_path": target["swap_path"],
        "swap_size_kib": target["swap_size_kib"],
        "swap_used_kib": target["swap_used_kib"],
        "swap_priority": target["swap_priority"],
    }


def _save_state(state_dir, state):
    _atomic_json(Path(state_dir) / STATE_NAME, state)


def _save_results(state_dir, results):
    _atomic_json(Path(state_dir) / RESULTS_NAME, results)


def _transition(state_dir, state, stage, results=None):
    if stage == "TRIAL_STOPPING" and state.get("stage") != "TRIAL_STOPPING":
        state["stage_before_trial_stopping"] = state.get("stage")
    state["stage"] = stage
    state["updated_at"] = _utc_now()
    _save_state(state_dir, state)
    if results is not None:
        results["stage"] = stage
        results["updated_at"] = state["updated_at"]
        _save_results(state_dir, results)


def _verify_artifacts(ops, expected):
    actual = ops.artifact_digests()
    if actual != expected:
        raise LiveSwapError("qualified artifacts changed during live-swap trial")
    return actual


def _verify_snapshots(snapshots, expected):
    for key, path in snapshots.items():
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW |
                     os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or \
                    stat.S_IMODE(info.st_mode) not in {0o400, 0o500}:
                raise LiveSwapError(f"unsafe snapshotted artifact: {key}")
            digest = hashlib.sha256()
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            if digest.hexdigest() != expected.get(key):
                raise LiveSwapError(f"snapshotted artifact changed: {key}")
        finally:
            os.close(fd)
    if set(snapshots) != set(expected):
        raise LiveSwapError("qualified artifact snapshot set is incomplete")


def _mapper_table(state):
    return (f"0 {LOGICAL_SECTORS} swapz {state['device']} "
            "0 64 0 2 0 1 0 0")


def _new_mapper_identity(existing_rows):
    names = {name for name, _ in existing_rows}
    uuids = {uuid for _, uuid in existing_rows}
    for _ in range(32):
        token = secrets.token_hex(8)
        name, uuid = LIVE_NAME_PREFIX + token, LIVE_UUID_PREFIX + token
        if name not in names and uuid not in uuids:
            return name, uuid
    raise LiveSwapError("cannot allocate unique live mapper identity")


def _read_swaps(ops):
    return PHYSICAL.parse_swap_rows(ops.text("/proc/swaps"))


def _active_swap_row(ops, major, minor):
    rows = []
    for row in _read_swaps(ops):
        if row["kind"] == "file":
            continue
        try:
            identity = PHYSICAL.block_identity(row["path"])
        except PHYSICAL.ProbeError as exc:
            raise LiveSwapError("cannot verify active swap device identity") from exc
        if identity == (major, minor):
            rows.append(row)
    if len(rows) > 1:
        raise LiveSwapError("multiple active swap entries match one device")
    return rows[0] if rows else None


def _mapper_info(ops, state):
    result = ops.command([
        "dmsetup", "info", "-c", "--noheadings",
        "-o", "name,uuid,major,minor,open", state["dm_name"],
    ], check=False)
    if result.returncode:
        raise LiveSwapError("cannot verify owned mapper information")
    rows = PHYSICAL._dm_info_rows(result.stdout, 5)
    if len(rows) != 1 or rows[0][:2] != (
            state["dm_name"], state["dm_uuid"]):
        raise LiveSwapError("live mapper name or UUID was substituted")
    try:
        dm_major, dm_minor, opened = map(int, rows[0][2:])
    except ValueError as exc:
        raise LiveSwapError("mapper major, minor or open count is malformed") from exc
    return dm_major, dm_minor, opened


def _verify_mapper_once(ops, state, *, allow_open=False):
    dm_major, dm_minor, opened = _mapper_info(ops, state)
    node = f"/dev/mapper/{state['dm_name']}"
    if PHYSICAL.block_identity(node) != (dm_major, dm_minor):
        raise LiveSwapError("mapper node identity differs from Device Mapper")
    sysfs = Path(f"/sys/dev/block/{dm_major}:{dm_minor}")
    try:
        actual_name = (sysfs / "dm/name").read_text().strip()
        actual_uuid = (sysfs / "dm/uuid").read_text().strip()
        size = int((sysfs / "size").read_text().strip())
        slaves = list((sysfs / "slaves").iterdir())
        lower = [Path(path / "dev").read_text().strip() for path in slaves]
    except (OSError, ValueError) as exc:
        raise LiveSwapError("cannot prove live mapper sysfs identity") from exc
    table = ops.command([
        "dmsetup", "table", "--showkeys", state["dm_name"],
    ], check=False)
    if table.returncode:
        raise LiveSwapError("cannot read exact live mapper table")
    _validate_mapper_observation(
        state, sysfs_identity=(actual_name, actual_uuid, size, lower),
        table_output=table.stdout, open_count=opened, allow_open=allow_open)
    return node


def _verify_mapper(ops, state, *, allow_open=False):
    """Zero-open checks retry briefly: udev probes can hold a fresh mapper open."""
    for attempt in range(MAPPER_OPEN_ATTEMPTS):
        try:
            return _verify_mapper_once(ops, state, allow_open=allow_open)
        except LiveSwapError as exc:
            if allow_open or "open references" not in str(exc) or \
                    attempt == MAPPER_OPEN_ATTEMPTS - 1:
                raise
        time.sleep(0.5)


def _validate_mapper_observation(state, *, sysfs_identity, table_output,
                                 open_count, allow_open=False):
    """Check normalized live DM evidence without reading host state."""
    expected_sysfs = (
        state["dm_name"], state["dm_uuid"], LOGICAL_SECTORS,
        [f"{state['major']}:{state['minor']}"])
    if sysfs_identity != expected_sysfs:
        raise LiveSwapError("mapper has unexpected UUID, size or lower device")
    actual = table_output.split()
    expected = _mapper_table(state).split()
    if len(actual) != len(expected) or actual[:3] != expected[:3] or \
            actual[4:] != expected[4:] or actual[3] not in {
                expected[3], f"{state['major']}:{state['minor']}"}:
        raise LiveSwapError("live mapper table differs from exact approved table")
    if type(open_count) is not int or open_count < 0:
        raise LiveSwapError("mapper open count is invalid")
    if open_count and not allow_open:
        raise LiveSwapError("owned mapper has unexpected open references")
    return True


def _status_snapshot(ops, state):
    result = ops.command(["dmsetup", "status", state["dm_name"]], check=False)
    if result.returncode:
        raise LiveSwapError("dmsetup status failed")
    counters = _parse_kv_status(result.stdout)
    if counters["failed"] != 0 or counters["error"] != 0 or \
            counters.get("flush_err", 0) != 0 or \
            counters.get("segment_discards_failed", 0) != 0:
        raise LiveSwapError("swapz status reports a failure counter")
    return {"text": _bounded(result.stdout), "counters": counters}


def _read_vmstat(ops):
    values = {}
    for line in ops.text("/proc/vmstat").splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0] in {"pswpin", "pswpout"}:
            values[fields[0]] = int(fields[1])
    if set(values) != {"pswpin", "pswpout"}:
        raise LiveSwapError("kernel swap-in/out counters are unavailable")
    return values


def _memory_sample(ops):
    facts = ops.memory_facts()
    return {
        "mem_available_bytes": facts["MemAvailable"],
        "mem_total_bytes": facts["MemTotal"],
        "ram_used_percent": facts["ram_used_percent"],
        "cgroup_headroom_bytes": facts.get("cgroup_headroom"),
        "psi_some_avg10": facts["psi_some_avg10"],
        "psi_full_avg10": facts["psi_full_avg10"],
    }


def _check_memory_sample(sample, *, require_low_ram=False):
    """Missing, malformed or exhausted memory/PSI evidence cannot admit work."""
    if not isinstance(sample, dict):
        raise SafeStop("memory_pressure", "memory pressure admission=invalid memory/PSI sample")
    available = sample.get("mem_available_bytes")
    headroom = sample.get("cgroup_headroom_bytes")
    if type(available) is not int or available < 0 or \
            "cgroup_headroom_bytes" not in sample or \
            (headroom is not None and (type(headroom) is not int or headroom < 0)):
        raise SafeStop("memory_pressure", "memory pressure admission=invalid MemAvailable/cgroup")
    for category in ("psi_some_avg10", "psi_full_avg10"):
        value = sample.get(category)
        if type(value) not in (int, float) or \
                not math.isfinite(value) or not 0 <= value <= 100:
            raise SafeStop("memory_pressure", f"memory pressure admission=invalid {category}")
    if "mem_total_bytes" in sample and (
            type(sample["mem_total_bytes"]) is not int or
            sample["mem_total_bytes"] <= 0 or
            available > sample["mem_total_bytes"]):
        raise SafeStop("memory_pressure", "memory pressure admission=invalid MemTotal")
    if available < MIN_AVAILABLE_BYTES:
        raise SafeStop(
            "memory_pressure",
            f"memory pressure admission=MemAvailable below floor={MIN_AVAILABLE_BYTES}")
    if headroom is not None and headroom < MIN_CGROUP_HEADROOM_BYTES:
        raise SafeStop(
            "memory_pressure",
            f"memory pressure admission=cgroup below floor={MIN_CGROUP_HEADROOM_BYTES}")
    if sample["psi_some_avg10"] >= MAX_MEMORY_SOME_AVG10:
        raise SafeStop(
            "memory_pressure",
            f"memory pressure admission=PSI_some threshold={MAX_MEMORY_SOME_AVG10}")
    if sample["psi_full_avg10"] >= MAX_MEMORY_FULL_AVG10:
        raise SafeStop(
            "memory_pressure",
            f"memory pressure admission=PSI_full threshold={MAX_MEMORY_FULL_AVG10}")
    if require_low_ram:
        used = sample.get("ram_used_percent")
        if type(used) not in (int, float) or not math.isfinite(used) or \
                not 0 <= used <= 100:
            raise SafeStop("ram_not_low", "memory pressure admission=invalid RAM-use percent")
        if used >= 50.0:
            raise SafeStop(
                "ram_not_low",
                "RAM use must be below 50 percent before original swapoff")


def _drain_headroom_bytes(mapper_used_kib, memory):
    """RAM capacity remaining after swap pages and the 2 GiB reserve."""
    if type(mapper_used_kib) is not int or mapper_used_kib < 0 or \
            not isinstance(memory, dict) or \
            type(memory.get("mem_available_bytes")) is not int:
        raise LiveSwapError("mapper drain-capacity evidence is malformed")
    return memory["mem_available_bytes"] - MIN_AVAILABLE_BYTES - mapper_used_kib * 1024


def _check_drain_headroom(mapper_used_kib, memory):
    headroom = _drain_headroom_bytes(mapper_used_kib, memory)
    if headroom < MIN_DRAIN_HEADROOM_BYTES:
        raise SafeStop(
            "drain_headroom",
            "available RAM cannot safely evacuate active swap pages")
    return headroom


def _pressure_page(seed, index):
    """Deterministic, incompressible 4 KiB page for one working-set index."""
    return hashlib.shake_256(seed + index.to_bytes(8, "little")).digest(PAGE_BYTES)


def _pressure_verify(working_set, seed, pages):
    """Count pages whose bytes differ from the deterministic expectation."""
    mismatches = 0
    for index in range(pages):
        offset = index * PAGE_BYTES
        if working_set[offset:offset + PAGE_BYTES] != _pressure_page(seed, index):
            mismatches += 1
    return mismatches


def _check_start_headroom(original_used_kib, memory):
    headroom = _drain_headroom_bytes(original_used_kib, memory)
    if headroom < TRIAL_HEADROOM_BYTES:
        raise SafeStop(
            "drain_headroom",
            "available RAM cannot start the trial with the required headroom")
    return headroom


def _pressure_run(run_id, pages):
    """Verify the complete anonymous mapping; report close errors, not PASS."""
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id) or \
            type(pages) is not int or not 0 < pages <= PRESSURE_PAGES:
        raise LiveSwapError("phase=pressure_setup invalid run identity/page bound")
    seed = run_id.encode("ascii")
    started = time.monotonic()
    working_set = mmap.mmap(-1, pages * PAGE_BYTES, access=mmap.ACCESS_WRITE)
    original_error = None
    mismatches = None
    try:
        for index in range(pages):
            offset = index * PAGE_BYTES
            working_set[offset:offset + PAGE_BYTES] = _pressure_page(seed, index)
        mismatches = _pressure_verify(working_set, seed, pages)
    except BaseException as exc:
        original_error = exc
    close_error = None
    try:
        working_set.close()
    except BaseException as exc:
        close_error = exc
    if original_error is not None:
        if close_error is not None:
            original_error.add_note(
                "phase=mapping_close secondary="
                f"{type(close_error).__name__} errno={getattr(close_error, 'errno', None)}")
        raise original_error
    return {
        "run_id": run_id,
        "requested_pages": pages,
        "verified_pages": pages - mismatches,
        "expected_bytes": pages * PAGE_BYTES,
        "verified_bytes": (pages - mismatches) * PAGE_BYTES,
        "mismatches": mismatches,
        "mapping_closed": close_error is None,
        "mapping_close_errno": getattr(close_error, "errno", None),
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def _set_parent_death_signal():
    """Kill the child if the supervisor dies, so no pressure process outlives it."""
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        raise OSError(ctypes.get_errno(), "cannot set parent-death signal")


def _pressure_child(cgroup, run_id, pages, deadline_seconds, report_fd,
                    parent_pid):
    """Forked child: join the cgroup, exceed its limit, verify, report, exit.

    The child runs code the supervisor already loaded and verified, so nothing
    is re-read from disk. It always ends through os._exit.
    """
    code = 2
    try:
        _set_parent_death_signal()
        if os.getppid() != parent_pid:
            raise LiveSwapError("pressure parent exited before death-signal binding")
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.alarm(int(deadline_seconds))
        with open(Path(cgroup) / "cgroup.procs", "w") as procs:
            procs.write(f"{os.getpid()}\n")
        result = _pressure_run(run_id, pages)
        data = memoryview((json.dumps(result, sort_keys=True) + "\n").encode())
        while data:
            data = data[os.write(report_fd, data):]
        code = 0 if result["mismatches"] == 0 and result["mapping_closed"] else 1
    except BaseException:
        code = 2
    finally:
        os._exit(code)


def _spawn_pressure_child(cgroup, run_id, pages, deadline_seconds):
    """Fork one owned child without losing it on pipe/fork cleanup failures."""
    parent_pid = os.getpid()
    read_fd, write_fd = os.pipe()
    try:
        pid = os.fork()
    except BaseException as fork_exc:
        cleanup_errors = []
        for label, fd in (("read_pipe_close", read_fd),
                          ("write_pipe_close", write_fd)):
            try:
                os.close(fd)
            except OSError as close_exc:
                cleanup_errors.append(
                    f"{label}:errno={getattr(close_exc, 'errno', None)}")
        detail = (
            f" cleanup={','.join(cleanup_errors)} retained=parent_pipe_unknown"
            if cleanup_errors else "")
        original_type = (
            "OSError" if isinstance(fork_exc, OSError)
            else type(fork_exc).__name__)
        raise LiveSwapError(
            f"phase=child_fork original={original_type} "
            f"errno={getattr(fork_exc, 'errno', None)}{detail}") from fork_exc
    if pid == 0:
        # No exception before _pressure_child may return into the parent's
        # supervisor stack. Any child-side descriptor failure terminates here.
        try:
            os.close(read_fd)
            _pressure_child(
                cgroup, run_id, pages, deadline_seconds, write_fd, parent_pid)
        finally:
            os._exit(2)

    try:
        os.close(write_fd)
    except OSError as close_exc:
        cleanup_errors = []
        child_reaped = False
        try:
            _terminate_pressure_child(cgroup, pid)
            child_reaped = True
        except BaseException as reap_exc:
            cleanup_errors.append(
                f"child_reap:{type(reap_exc).__name__}:"
                f"errno={getattr(reap_exc, 'errno', None)}")
        try:
            os.close(read_fd)
        except OSError as read_close_exc:
            cleanup_errors.append(
                f"read_pipe_close:errno={getattr(read_close_exc, 'errno', None)}")
        retained = (
            "child_and_parent_pipe_unknown" if not child_reaped
            else "parent_pipe_unknown")
        detail = ",".join(cleanup_errors) or "none"
        raise LiveSwapError(
            "phase=child_spawn_parent_pipe_close "
            f"original=OSError errno={getattr(close_exc, 'errno', None)} "
            f"cleanup={detail} retained={retained}") from close_exc
    return pid, read_fd


def _read_all_fd(fd):
    """A reaped child is not proof that inherited pipe writers have closed."""
    chunks = []
    total = 0
    os.set_blocking(fd, False)
    while True:
        try:
            chunk = os.read(fd, 4096)
        except BlockingIOError as exc:
            raise LiveSwapError(
                "phase=child_report retained=open_writer; EOF unproven") from exc
        if not chunk:
            break
        total += len(chunk)
        if total > RESULT_LIMIT:
            raise LiveSwapError("phase=child_report report exceeds bound")
        chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", errors="replace")


def _terminate_pressure_child(cgroup, pid):
    """Signal only our unreaped fork child; never cgroup-wide foreign members."""
    del cgroup
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + 60
    while True:
        waited, status = os.waitpid(pid, os.WNOHANG)
        if waited == pid:
            return status
        if time.monotonic() >= deadline:
            raise LiveSwapError(
                "phase=child_reap SIGKILL child still live; retained=child_and_cgroup")
        time.sleep(0.2)


def _require_control(path, expected):
    if Path(path).read_text().strip() != expected:
        raise LiveSwapError(f"pressure cgroup control was not applied: {Path(path).name}")


def _pressure_guard(ops, state, progress):
    """Stop on RAM, cgroup or PSI threshold before recording mapper usage."""
    memory = _memory_sample(ops)
    available = memory.get("mem_available_bytes") if isinstance(memory, dict) else None
    if type(available) is not int or available < 0:
        _check_memory_sample(memory)
    if available < MIN_AVAILABLE_BYTES:
        raise SafeStop(
            "memory_floor",
            "admission=MemAvailable below 2 GiB during swap pressure")
    _check_memory_sample(memory)
    progress["guard_samples"] = progress.get("guard_samples", 0) + 1
    row = ops.active_swap_for(state["dm_major"], state["dm_minor"])
    if row is None:
        raise LiveSwapError("phase=pressure_guard mapped swap entry disappeared")
    used_kib = row["used_kib"]
    progress["peak_mapper_used_kib"] = max(
        progress["peak_mapper_used_kib"], used_kib)
    if _drain_headroom_bytes(used_kib, memory) < TRIAL_HEADROOM_BYTES:
        raise SafeStop(
            "mapper_drain_headroom_low",
            "admission=mapper drain headroom below trial stop threshold")
    return used_kib


def _parse_pressure_child_output(text):
    """Parse one bounded oracle report without retaining arbitrary child data."""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        value = PHYSICAL._load_unique_json(text.encode("utf-8"))
    except (ValueError, UnicodeError):
        return None
    fields = {
        "run_id", "requested_pages", "verified_pages", "expected_bytes",
        "verified_bytes", "mismatches", "mapping_closed", "mapping_close_errno",
        "elapsed_seconds",
    }
    if not isinstance(value, dict) or set(value) != fields:
        return None
    run_id = value["run_id"]
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
        return None
    for key in ("requested_pages", "verified_pages", "expected_bytes",
                "verified_bytes", "mismatches"):
        item = value[key]
        if type(item) is not int or item < 0:
            return None
    if type(value["mapping_closed"]) is not bool:
        return None
    close_errno = value["mapping_close_errno"]
    if close_errno is not None and (
            type(close_errno) is not int or close_errno <= 0):
        return None
    if value["mapping_closed"] and close_errno is not None:
        return None
    elapsed_seconds = value["elapsed_seconds"]
    if type(elapsed_seconds) not in (int, float) or \
            not math.isfinite(elapsed_seconds) or elapsed_seconds < 0:
        return None
    return value


def _pressure_report_failure(child, run_id, pages):
    """Return a stable category when the byte oracle cannot qualify."""
    if not isinstance(child, dict):
        return "missing_or_malformed_report"
    expected_bytes = pages * PAGE_BYTES
    if child.get("run_id") != run_id:
        return "run_identity_mismatch"
    if type(child.get("requested_pages")) is not int or \
            child["requested_pages"] != pages:
        return "requested_page_count_mismatch"
    if type(child.get("expected_bytes")) is not int or \
            child["expected_bytes"] != expected_bytes:
        return "expected_byte_count_mismatch"
    if type(child.get("verified_pages")) is not int or \
            child["verified_pages"] != pages:
        return "verified_page_count_mismatch"
    if type(child.get("verified_bytes")) is not int or \
            child["verified_bytes"] != expected_bytes:
        return "verified_byte_count_mismatch"
    if type(child.get("mismatches")) is not int or child["mismatches"] != 0:
        return "byte_mismatch"
    if child.get("mapping_closed") is not True:
        return "mapping_close_failed"
    if child.get("mapping_close_errno") is not None:
        return "mapping_close_errno_inconsistent"
    return None


def _pressure_memory_event_failure(memory_events):
    """Zero OOM and OOM-kill are mandatory; missing counters are not zero."""
    if not isinstance(memory_events, dict):
        return "memory_events_missing"
    for key in ("oom", "oom_kill"):
        value = memory_events.get(key)
        if type(value) is not int or value < 0:
            return f"{key}_missing_or_malformed"
        if value != 0:
            return f"{key}_observed"
    return None


def _write_control(path, value):
    with open(path, "w") as handle:
        handle.write(f"{value}\n")


def _kill_cgroup(cgroup):
    kill_file = Path(cgroup) / "cgroup.kill"
    if kill_file.exists():
        _write_control(kill_file, "1")


def _read_int_control(path):
    try:
        text = Path(path).read_text().strip()
    except FileNotFoundError:
        return None
    if not re.fullmatch(r"[0-9]+", text):
        raise LiveSwapError("cgroup counter is malformed")
    return int(text)


def _read_memory_events(cgroup):
    events = {}
    try:
        text = (Path(cgroup) / "memory.events").read_text()
    except FileNotFoundError:
        return events
    allowed = {
        "low", "high", "max", "oom", "oom_kill", "oom_group_kill",
        "sock_throttled",
    }
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 2 or fields[0] not in allowed or \
                not re.fullmatch(r"[0-9]+", fields[1]) or \
                fields[0] in events:
            raise LiveSwapError("phase=memory_events duplicate/malformed counter")
        events[fields[0]] = int(fields[1])
    return events


def _remove_empty_cgroup(cgroup):
    try:
        os.rmdir(cgroup)
    except OSError as exc:
        raise LiveSwapError(
            "pressure cgroup could not be removed; manual review") from exc


def _run_pressure_phase(state_dir, state, results, ops):
    """Require source-bound byte counts, zero OOM and proven teardown."""
    run_id = state.get("run_id")
    head = state.get("head")
    helper_sha256 = state.get("helper_sha256")
    artifacts = state.get("artifact_digests")
    if run_id != results.get("run_id") or \
            not isinstance(run_id, str) or \
            not re.fullmatch(r"[0-9a-f]{32}", run_id) or \
            state.get("qualified_source") != QUALIFIED_SOURCE or \
            results.get("qualified_source") != QUALIFIED_SOURCE or \
            head != results.get("head") or \
            not isinstance(head, str) or \
            not re.fullmatch(r"[0-9a-f]{40}", head) or \
            not isinstance(helper_sha256, str) or \
            not re.fullmatch(r"[0-9a-f]{64}", helper_sha256) or \
            results.get("helper_sha256") != helper_sha256 or \
            artifacts != EXPECTED_ARTIFACTS or \
            results.get("artifact_digests") != artifacts:
        raise LiveSwapError("phase=pressure_admission source/run identity mismatch")
    cgroup_name = f"swapz-live-{secrets.token_hex(8)}"
    state["pressure_cgroup"] = cgroup_name
    _save_state(state_dir, state)
    progress = {"peak_mapper_used_kib": 0, "guard_samples": 0}
    phase = {
        "status": "FAIL", "cgroup": cgroup_name,
        "memory_max_bytes": PRESSURE_MEMORY_MAX_BYTES,
        "zswap_max_bytes": 0,
        "requested_pages": PRESSURE_PAGES,
        "expected_verified_pages": PRESSURE_PAGES,
        "expected_verified_bytes": PRESSURE_PAGES * PAGE_BYTES,
        "oracle_outcome": "UNVERIFIED",
        "peak_mapper_used_kib": 0,
        "retained_state": state.get("stage"),
    }
    results["pressure_phase"] = phase
    try:
        outcome = ops.pressure_workload(
            state, cgroup_name=cgroup_name,
            guard=lambda: _pressure_guard(ops, state, progress),
            stop_requested=ops.stop_requested,
            timeout=PRESSURE_TIMEOUT_SECONDS)
    except (SafeStop, LiveSwapError) as exc:
        phase.update(status="SAFE_STOP" if isinstance(exc, SafeStop) else "FAIL",
                     error=_bounded(exc),
                     peak_mapper_used_kib=progress["peak_mapper_used_kib"],
                     guard_samples=progress["guard_samples"])
        _save_results(state_dir, results)
        raise
    if not isinstance(outcome, dict):
        raise LiveSwapError("phase=pressure_workload missing child outcome")
    child = _parse_pressure_child_output(outcome.get("stdout", ""))
    memory_events = outcome.get("memory_events")
    memory_events = memory_events if isinstance(memory_events, dict) else {}
    report_failure = _pressure_report_failure(child, run_id, PRESSURE_PAGES)
    memory_failure = _pressure_memory_event_failure(memory_events)
    phase.update(
        exit_code=outcome.get("exit_code"),
        timed_out=outcome.get("timed_out") is True,
        stopped=outcome.get("stopped") is True,
        child_reaped=outcome.get("child_reaped") is True,
        cgroup_removed=outcome.get("cgroup_removed") is True,
        memory_events=memory_events,
        child=child,
        oracle_failure=report_failure,
        memory_event_failure=memory_failure,
        observed_verified_pages=child.get("verified_pages") if child else None,
        observed_verified_bytes=child.get("verified_bytes") if child else None,
        swap_peak_bytes=outcome.get("swap_peak_bytes"),
        zswap_peak_bytes=outcome.get("zswap_peak_bytes"),
        peak_mapper_used_kib=progress["peak_mapper_used_kib"],
        guard_samples=progress["guard_samples"],
    )
    _save_results(state_dir, results)
    detail = (
        f"phase=pressure_verify exit={phase['exit_code']} "
        f"admission=memory/PSI/cgroup "
        f"oracle={report_failure or 'byte_exact'} "
        f"memory_events={memory_failure or 'zero_oom'} "
        f"expected_pages={PRESSURE_PAGES} observed_pages={phase['observed_verified_pages']} "
        f"expected_bytes={PRESSURE_PAGES * PAGE_BYTES} "
        f"observed_bytes={phase['observed_verified_bytes']} "
        f"mapping_closed={child.get('mapping_closed') if child else None} "
        f"mapping_close_errno={child.get('mapping_close_errno') if child else None} "
        f"oom={memory_events.get('oom')} "
        f"oom_kill={memory_events.get('oom_kill')} "
        f"retained={state.get('stage')}")
    if phase["stopped"]:
        raise SafeStop("operator_stop", f"operator requested stop; {detail}")
    if phase["timed_out"]:
        raise LiveSwapError(f"pressure child timed out; {detail}")
    if not phase["child_reaped"] or not phase["cgroup_removed"]:
        raise LiveSwapError(f"pressure teardown unproven; {detail}")
    if type(phase["exit_code"]) is not int or phase["exit_code"] != 0 or \
            report_failure is not None or memory_failure is not None:
        raise LiveSwapError(f"swap-pressure verification failed; {detail}")
    swap_peak = phase["swap_peak_bytes"]
    zswap_peak = phase["zswap_peak_bytes"]
    if type(swap_peak) is not int or swap_peak <= 0 or \
            (zswap_peak is not None and
             (type(zswap_peak) is not int or zswap_peak != 0)):
        raise LiveSwapError(f"swap pressure did not reach owned swap; {detail}")
    if progress["guard_samples"] == 0 or progress["peak_mapper_used_kib"] <= 0:
        raise LiveSwapError(f"pressure samples missing or mapper unused; {detail}")
    phase["oracle_outcome"] = "BYTE_EXACT"
    phase["memory_event_outcome"] = "ZERO_OOM"
    phase["status"] = "PASS"
    _save_results(state_dir, results)
    return phase


def _save_observation(state_dir, state, results, ops, *, first=False):
    _verify_mapper(ops, state, allow_open=True)
    status = _status_snapshot(ops, state)
    vmstat = _read_vmstat(ops)
    memory = _memory_sample(ops)
    _check_memory_sample(memory)
    _verify_trial_swap_inventory(ops, state)
    row = _active_swap_row(ops, state["dm_major"], state["dm_minor"])
    if row is None:
        raise LiveSwapError("experimental mapper is not active as swap")
    drain_headroom = _drain_headroom_bytes(row["used_kib"], memory)
    entry = {
        "timestamp": _utc_now(),
        "swap_used_kib": row["used_kib"],
        "swap_size_kib": row["size_kib"],
        "swap_priority": row["priority"],
        "vmstat": vmstat,
        "memory": memory,
        "sample_index": len(results.get("observations", [])),
        "drain_headroom_bytes": drain_headroom,
        "dmsetup_status": status,
        "block_stats": PHYSICAL._block_stat_snapshot({
            "major": state["major"], "minor": state["minor"],
            "parent_major_minor": state.get("parent_major_minor"),
        }),
    }
    results.setdefault("observations", []).append(entry)
    results["max_swapz_used_kib"] = max(
        results.get("max_swapz_used_kib", 0), row["used_kib"])
    if first:
        results["trial_baseline"] = entry
    _save_results(state_dir, results)
    return entry


def _actual_swap_io(results):
    """Only fully bound, byte-exact and chronologically complete I/O qualifies."""
    if not isinstance(results, dict):
        return False
    run_id = results.get("run_id")
    head = results.get("head")
    helper_sha256 = results.get("helper_sha256")
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id) or \
            not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head) or \
            results.get("qualified_source") != QUALIFIED_SOURCE or \
            not isinstance(helper_sha256, str) or \
            not re.fullmatch(r"[0-9a-f]{64}", helper_sha256) or \
            results.get("artifact_digests") != EXPECTED_ARTIFACTS or \
            results.get("device") != DEVICE_PATH or \
            results.get("major_minor") != f"{DEVICE_MAJOR}:{DEVICE_MINOR}" or \
            results.get("partuuid") != DEVICE_PARTUUID or \
            not isinstance(results.get("parent_major_minor"), str) or \
            not re.fullmatch(
                r"[0-9]+:[0-9]+", results["parent_major_minor"]) or \
            results.get("size_bytes") != DEVICE_SIZE_BYTES or \
            results.get("original_header_sha256") != ORIGINAL_HEADER_SHA256 or \
            results.get("fallback_mode") != "none" or \
            results.get("logical_capacity_bytes") != LOGICAL_BYTES:
        return False

    baseline = results.get("trial_baseline")
    observations = results.get("observations", [])
    pressure = results.get("pressure_phase")
    if not isinstance(baseline, dict) or not isinstance(observations, list) or \
            len(observations) < 2 or observations[0] != baseline or \
            not isinstance(pressure, dict) or pressure.get("status") != "PASS":
        return False
    if any(not isinstance(sample, dict) or
           type(sample.get("sample_index")) is not int or
           sample["sample_index"] != index
           for index, sample in enumerate(observations)):
        return False

    if pressure.get("memory_max_bytes") != PRESSURE_MEMORY_MAX_BYTES or \
            pressure.get("zswap_max_bytes") != 0 or \
            pressure.get("requested_pages") != PRESSURE_PAGES or \
            pressure.get("expected_verified_pages") != PRESSURE_PAGES or \
            pressure.get("expected_verified_bytes") != PRESSURE_PAGES * PAGE_BYTES or \
            pressure.get("oracle_outcome") != "BYTE_EXACT" or \
            pressure.get("memory_event_outcome") != "ZERO_OOM" or \
            pressure.get("child_reaped") is not True or \
            pressure.get("cgroup_removed") is not True or \
            pressure.get("timed_out") is not False or \
            pressure.get("stopped") is not False or \
            type(pressure.get("exit_code")) is not int or \
            pressure["exit_code"] != 0 or \
            _pressure_report_failure(
                pressure.get("child"), run_id, PRESSURE_PAGES) is not None or \
            _pressure_memory_event_failure(
                pressure.get("memory_events")) is not None:
        return False
    peak_kib = pressure.get("peak_mapper_used_kib")
    guard_samples = pressure.get("guard_samples")
    swap_peak = pressure.get("swap_peak_bytes")
    zswap_peak = pressure.get("zswap_peak_bytes")
    if type(peak_kib) is not int or peak_kib <= 0 or \
            type(guard_samples) is not int or guard_samples <= 0 or \
            type(swap_peak) is not int or swap_peak <= 0 or \
            (zswap_peak is not None and
             (type(zswap_peak) is not int or zswap_peak != 0)):
        return False

    try:
        lower_deltas = []
        for before, after in zip(observations, observations[1:]):
            before_block = before["block_stats"]
            after_block = after["block_stats"]
            if before_block.get("device_major_minor") != \
                    results["parent_major_minor"] or \
                    after_block.get("device_major_minor") != \
                    results["parent_major_minor"]:
                return False
            lower_deltas.append(
                PHYSICAL._lower_io_delta(before_block, after_block))
            for group, keys in (
                    ("vmstat", ("pswpin", "pswpout")),
                    ("dmsetup_status", ("logical_write", "logical_read"))):
                left = before[group]
                right = after[group]
                if group == "dmsetup_status":
                    left, right = left["counters"], right["counters"]
                for key in keys:
                    if type(left[key]) is not int or type(right[key]) is not int or \
                            left[key] < 0 or right[key] < left[key]:
                        return False
        final = observations[-1]
        total_lower_write_bytes = sum(
            delta["lower_write_bytes"] for delta in lower_deltas)
        total_lower_write_requests = sum(
            delta["lower_write_requests"] for delta in lower_deltas)
        return bool(
            final["vmstat"]["pswpout"] > baseline["vmstat"]["pswpout"] and
            final["vmstat"]["pswpin"] > baseline["vmstat"]["pswpin"] and
            final["dmsetup_status"]["counters"]["logical_write"] >
            baseline["dmsetup_status"]["counters"]["logical_write"] and
            final["dmsetup_status"]["counters"]["logical_read"] >
            baseline["dmsetup_status"]["counters"]["logical_read"] and
            (total_lower_write_bytes > 0 or total_lower_write_requests > 0))
    except (KeyError, IndexError, TypeError, ValueError, PHYSICAL.ProbeError):
        return False


def _release_marker(state):
    PHYSICAL._release_partition_ownership(state)


def _create_durable_state(approval, target, plan, state_dir, ops):
    state_dir = Path(state_dir)
    base = ops.recovery_base(target)
    if state_dir.parent != base or state_dir.name != \
            f"swapz-live-{approval['run_id']}":
        raise LiveSwapError("live state directory must be the exact fixed-base child")
    state_dir.mkdir(mode=0o700)
    os.chmod(state_dir, 0o700)
    directory_info = state_dir.lstat()
    if not stat.S_ISDIR(directory_info.st_mode) or directory_info.st_uid != 0 or \
            stat.S_IMODE(directory_info.st_mode) != 0o700:
        raise LiveSwapError("live recovery directory is not root-owned mode 0700")
    PHYSICAL._fsync_directory(base)
    header = ops.read_header(target)
    if len(header) != PAGE_BYTES or hashlib.sha256(header).hexdigest() != \
            ORIGINAL_HEADER_SHA256:
        raise LiveSwapError("original block-zero backup differs from approval")
    backup_path = state_dir / BACKUP_NAME
    _durable_write(backup_path, header)
    artifacts = ops.artifact_digests()
    if artifacts != EXPECTED_ARTIFACTS:
        raise LiveSwapError("qualified artifact hashes changed before snapshot")
    snapshots = PHYSICAL._snapshot_reviewed_artifacts(
        state_dir, EXPECTED_ARTIFACTS)
    approval_bytes = (json.dumps(
        approval, sort_keys=True, indent=2) + "\n").encode()
    _durable_write(state_dir / APPROVAL_NAME, approval_bytes)
    state = {
        "schema": "swapz-live-swap-state-v1",
        "run_id": approval["run_id"],
        "stage": "PREPARED",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        **_target_state(target),
        "head": plan["head"],
        "qualified_source": QUALIFIED_SOURCE,
        "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "artifact_digests": dict(artifacts),
        "artifact_snapshots": {key: str(path) for key, path in snapshots.items()},
        "original_header_sha256": ORIGINAL_HEADER_SHA256,
        "formatted_header_sha256": None,
        "dm_name": None,
        "dm_uuid": None,
        "module_loaded_by_process": False,
        "active_mapper_swap": False,
        "fallback_mode": "none",
        "fallback": None,
        "initial_swap_used_kib": target["swap_used_kib"],
        "authorization_sha256": _approval_digest(approval),
    }
    _save_state(state_dir, state)
    return state, header, snapshots


def _validate_state(state, backup, state_dir):
    if not isinstance(state, dict) or \
            state.get("schema") != "swapz-live-swap-state-v1" or \
            not re.fullmatch(r"[0-9a-f]{32}", str(state.get("run_id", ""))):
        raise LiveSwapError("saved live-trial state is malformed")
    if Path(state_dir).name != f"swapz-live-{state['run_id']}":
        raise LiveSwapError("saved live-trial directory and run id differ")
    state_dir = Path(state_dir)
    try:
        base = PHYSICAL._recovery_base(state)
        directory_info = state_dir.lstat()
        state_info = (state_dir / STATE_NAME).lstat()
        backup_info = (state_dir / BACKUP_NAME).lstat()
    except OSError as exc:
        raise LiveSwapError("saved live-trial recovery files are unavailable") from exc
    if state_dir.parent != base or not stat.S_ISDIR(directory_info.st_mode) or \
            directory_info.st_uid != 0 or \
            stat.S_IMODE(directory_info.st_mode) != 0o700 or \
            not stat.S_ISREG(state_info.st_mode) or state_info.st_uid != 0 or \
            state_info.st_nlink != 1 or \
            stat.S_IMODE(state_info.st_mode) != 0o600 or \
            not stat.S_ISREG(backup_info.st_mode) or backup_info.st_uid != 0 or \
            backup_info.st_nlink != 1 or \
            stat.S_IMODE(backup_info.st_mode) != 0o600:
        raise LiveSwapError("saved state directory or files have unsafe ownership/mode")
    if state.get("stage") not in RECOVERY_RECOGNIZED_STAGES | {
            "PREPARED", "COMPLETE", "CANCELLED_SAFE"}:
        raise LiveSwapError("saved state has an unknown recovery stage")
    saved_parent = state.get("parent_major_minor")
    if saved_parent is not None and (
            not isinstance(saved_parent, str) or
            not re.fullmatch(r"[0-9]+:[0-9]+", saved_parent)):
        raise LiveSwapError("saved physical parent identity is malformed")
    if len(backup) != PAGE_BYTES or hashlib.sha256(backup).hexdigest() != \
            ORIGINAL_HEADER_SHA256 or \
            state.get("original_header_sha256") != ORIGINAL_HEADER_SHA256:
        raise LiveSwapError("saved original block-zero backup is invalid")
    if any(state.get(key) != value for key, value in {
            "device": DEVICE_PATH, "major": DEVICE_MAJOR,
            "minor": DEVICE_MINOR, "partuuid": DEVICE_PARTUUID,
            "size_bytes": DEVICE_SIZE_BYTES}.items()):
        raise LiveSwapError("saved live-trial device identity differs")


def _record_phase(state_dir, state, results, ops, phase, argv, *, timeout=120):
    entry = {"phase": phase, "argv": _public_argv(argv),
             "started_at": _utc_now(), "return_code": None,
             "status": "STARTED"}
    results.setdefault("phases", []).append(entry)
    _save_results(state_dir, results)
    try:
        result = ops.mutate(argv, timeout=timeout)
        entry["return_code"] = result.returncode
        entry["status"] = "PASS" if result.returncode == 0 else "FAIL"
        entry["ended_at"] = _utc_now()
        if result.returncode:
            entry["diagnostic"] = _public_diagnostic(
                result.stderr or result.stdout)
        _save_results(state_dir, results)
        if result.returncode:
            raise LiveSwapError(
                f"{phase} failed exit={result.returncode}: "
                f"{entry['diagnostic']}")
        return result
    except BaseException as exc:
        if entry["status"] == "STARTED":
            entry["status"] = "INTERRUPTED"
            entry["diagnostic"] = _public_diagnostic(exc)
            entry["ended_at"] = _utc_now()
            _save_results(state_dir, results)
        raise


def _activate_trial(state_dir, state, results, target, snapshots, ops,
                    monotonic=time.monotonic, sleep=time.sleep):
    """Run activation, one swap-pressure check and bounded observation."""
    _check_stop(ops)
    _transition(state_dir, state, "ORIGINAL_SWAPOFF_PENDING", results)
    _verify_artifacts(ops, state["artifact_digests"])
    _verify_snapshots(snapshots, state["artifact_digests"])
    _verify_trial_swap_inventory(ops, state)
    repo = ops.repo_snapshot()
    if repo.get("branch") != "main" or repo.get("clean") is not True or \
            repo.get("head") != state["head"] or \
            repo.get("origin_main") != state["head"] or \
            repo.get("canonical_main") != state["head"]:
        raise LiveSwapError("main or canonical GitHub HEAD changed after admission")
    memory = _memory_sample(ops)
    _check_memory_sample(memory, require_low_ram=True)
    ops.recheck_target(state, expected_header=ORIGINAL_HEADER_SHA256,
                       require_active=True, require_zero=False)
    original_swap = ops.active_swap_for(state["major"], state["minor"])
    if original_swap is None or \
            original_swap["priority"] != state["swap_priority"] or \
            original_swap["size_kib"] != state["swap_size_kib"]:
        raise LiveSwapError("original swap size, priority or active identity changed")
    results["original_swap_used_before_swapoff_kib"] = original_swap["used_kib"]
    results["original_swap_drain_headroom_bytes"] = _check_start_headroom(
        original_swap["used_kib"], memory)
    _save_results(state_dir, results)
    _record_phase(state_dir, state, results, ops, "original_swapoff",
                  ["swapoff", "--", state["swap_path"]],
                  timeout=SWAPOFF_TIMEOUT_SECONDS)
    if ops.active_swap_for(state["major"], state["minor"]) is not None:
        raise LiveSwapError("original partition remains active after swapoff")
    state["original_swapoff_complete"] = True
    _transition(state_dir, state, "ORIGINAL_SWAP_OFF", results)
    _verify_trial_swap_inventory(ops, state)
    _check_stop(ops)

    _transition(state_dir, state, "HEADER_CLEAR_PENDING", results)
    ops.recheck_target(state, expected_header=ORIGINAL_HEADER_SHA256,
                       require_active=False, require_zero=True)
    ops.write_header(
        target, bytes(PAGE_BYTES),
        expected_current=_read_recovery_file(
            Path(state_dir) / BACKUP_NAME))
    if ops.read_header(target) != bytes(PAGE_BYTES):
        raise LiveSwapError("checked block-zero clear failed exact readback")
    state["header_clear_started"] = True
    _transition(state_dir, state, "HEADER_CLEARED", results)
    _check_stop(ops)
    ops.recheck_target(
        state, expected_header=hashlib.sha256(bytes(PAGE_BYTES)).hexdigest(),
        require_active=False)

    _transition(state_dir, state, "FORMAT_PENDING", results)
    formatter = snapshots["formatter_sha256"]
    _verify_snapshots(snapshots, state["artifact_digests"])
    _record_phase(
        state_dir, state, results, ops, "format_swz",
        [str(formatter), "format", state["device"], "--expect-major-minor",
         f"{state['major']}:{state['minor']}", "--expect-bytes",
         str(state["size_bytes"])])
    swz_header = ops.read_header(target)
    if not PHYSICAL.swapz_header_valid(swz_header, state["size_bytes"]):
        raise LiveSwapError("formatter did not produce the exact SWZ header")
    state["formatted_header_sha256"] = hashlib.sha256(swz_header).hexdigest()
    _transition(state_dir, state, "SWZ_FORMATTED", results)
    _check_stop(ops)
    ops.recheck_target(
        state, expected_header=state["formatted_header_sha256"],
        require_active=False)

    _transition(state_dir, state, "MODULE_LOAD_PENDING", results)
    if ops.module_loaded():
        raise LiveSwapError("dm_swapz appeared before this process loaded it")
    module = snapshots["module_sha256"]
    _verify_snapshots(snapshots, state["artifact_digests"])
    _record_phase(
        state_dir, state, results, ops, "load_module",
        ["insmod", str(module), "allow_physical_backing=1"])
    state["module_loaded_by_process"] = True
    _save_state(state_dir, state)
    ops.verify_module(module)
    _transition(state_dir, state, "MODULE_LOADED", results)
    _check_stop(ops)
    ops.recheck_target(
        state, expected_header=state["formatted_header_sha256"],
        require_active=False)

    _transition(state_dir, state, "MAPPER_CREATE_PENDING", results)
    existing = ops.dm_rows()
    state["dm_name"], state["dm_uuid"] = _new_mapper_identity(existing)
    state["dm_table"] = _mapper_table(state)
    _save_state(state_dir, state)
    _record_phase(
        state_dir, state, results, ops, "create_mapper",
        ["dmsetup", "create", state["dm_name"], "--uuid", state["dm_uuid"],
         "--table", state["dm_table"]])
    mapper = ops.verify_mapper(state, allow_open=False)
    info = _mapper_info(ops, state)
    state["dm_major"], state["dm_minor"] = info[:2]
    state["mapper_size_bytes"] = LOGICAL_BYTES
    state["physical_header_after_map_sha256"] = hashlib.sha256(
        ops.read_header(target)).hexdigest()
    if state["physical_header_after_map_sha256"] != \
            state["formatted_header_sha256"]:
        raise LiveSwapError("mapper creation changed the physical SWZ header")
    state["dmsetup_status_before_mkswap"] = _status_snapshot(ops, state)
    _transition(state_dir, state, "MAPPED", results)
    _check_stop(ops)

    _verify_mapper(ops, state)
    _transition(state_dir, state, "MKSWAP_PENDING", results)
    _record_phase(state_dir, state, results, ops, "mkswap_mapper",
                  ["mkswap", "--", mapper])
    ops.verify_mapper_swap_signature(state, mapper)
    if hashlib.sha256(ops.read_header(target)).hexdigest() != \
            state["formatted_header_sha256"]:
        raise LiveSwapError("mkswap changed physical block-zero SWZ authorization")
    _transition(state_dir, state, "MAPPED_SWAP_READY", results)
    _check_stop(ops)

    state["mapper_priority"] = 32767
    _verify_mapper(ops, state)
    _transition(state_dir, state, "SWAPON_PENDING", results)
    _record_phase(
        state_dir, state, results, ops, "swapon_mapper",
        ["swapon", "--priority", str(state["mapper_priority"]), "--", mapper])
    row = ops.active_swap_for(state["dm_major"], state["dm_minor"])
    expected_pages_kib = LOGICAL_BYTES // 1024 - PAGE_BYTES // 1024
    if row is None or row["priority"] != state["mapper_priority"] or \
            row["size_kib"] != expected_pages_kib:
        raise LiveSwapError("mapped swap entry has wrong identity, size or priority")
    state["active_mapper_swap"] = True
    _transition(state_dir, state, "LIVE_SWAP_ACTIVE", results)
    _verify_trial_swap_inventory(ops, state)
    _check_stop(ops)
    results["trial_start_timestamp"] = _utc_now()
    results["trial_baseline"] = None
    results["observations"] = []
    _save_results(state_dir, results)

    start = monotonic()
    deadline = start + TRIAL_SECONDS
    stop_reason = None
    try:
        baseline = _save_observation(state_dir, state, results, ops, first=True)
        if baseline["drain_headroom_bytes"] < TRIAL_HEADROOM_BYTES:
            raise SafeStop(
                "baseline_headroom_low",
                "mapper baseline headroom is below the trial stop threshold")
        _run_pressure_phase(state_dir, state, results, ops)
        for _ in range(PRESSURE_SETTLE_SECONDS // SAMPLE_SECONDS):
            _check_stop(ops)
            sleep(SAMPLE_SECONDS)
        while monotonic() < deadline:
            _check_stop(ops)
            sample = _save_observation(
                state_dir, state, results, ops, first=False)
            if sample["drain_headroom_bytes"] < TRIAL_HEADROOM_BYTES:
                raise SafeStop(
                    "mapper_drain_headroom_low",
                    "mapper drain headroom fell below the safe stop threshold")
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            sleep(min(SAMPLE_SECONDS, remaining))
    except SafeStop as exc:
        stop_reason = exc.reason
        results["safe_stop_detail"] = _bounded(exc)
    results["trial_end_timestamp"] = _utc_now()
    results["trial_duration_seconds"] = min(
        TRIAL_SECONDS, max(0, int(monotonic() - start)))
    results["stop_reason"] = stop_reason or "duration_complete"
    results["actual_swap_io_observed"] = _actual_swap_io(results)
    _save_results(state_dir, results)
    _transition(state_dir, state, "TRIAL_STOPPING", results)


def _resolved_stage(state):
    """The stage recovery reasons about, past the durable wrappers.

    Standalone recovery can re-enter cleanup after RECOVERY_REQUIRED, and the
    cleanup entry records TRIAL_STOPPING over that wrapper. Missing or cyclic
    provenance raises, so no caller acts on a guessed stage.
    """
    stage = state.get("stage")
    visited_stages = set()
    while stage in {"RECOVERY_REQUIRED", "TRIAL_STOPPING"}:
        if stage in visited_stages:
            raise LiveSwapError("saved recovery stage provenance is ambiguous")
        visited_stages.add(stage)
        previous_stage_key = (
            "recovery_previous_stage" if stage == "RECOVERY_REQUIRED"
            else "stage_before_trial_stopping")
        stage = state.get(previous_stage_key)
    if not isinstance(stage, str):
        raise LiveSwapError("saved recovery stage provenance is ambiguous")
    return stage


def _recognized_current_header(header, state):
    digest = hashlib.sha256(header).hexdigest()
    if digest == state["original_header_sha256"]:
        return "ORIGINAL"
    stage = _resolved_stage(state)
    # HEADER_RESTORE_PENDING is recorded before the checked restore write, so a
    # zero page there is an interrupted restore that a retry must still finish.
    zeroed_stages = {"HEADER_CLEAR_PENDING", "HEADER_CLEARED", "FORMAT_PENDING",
                     "HEADER_RESTORE_PENDING"}
    if stage in zeroed_stages and header == bytes(PAGE_BYTES):
        return "ZEROED"
    formatted_stages = {
        "FORMAT_PENDING", "SWZ_FORMATTED", "MODULE_LOAD_PENDING",
        "MODULE_LOADED", "MAPPER_CREATE_PENDING", "MAPPED",
        "MKSWAP_PENDING", "MAPPED_SWAP_READY", "SWAPON_PENDING",
        "LIVE_SWAP_ACTIVE", "TRIAL_STOPPING", "MAPPER_SWAPOFF_PENDING",
        "MAPPER_SWAP_OFF", "MAPPER_REMOVE_PENDING", "MAPPER_REMOVED",
        "MODULE_UNLOAD_PENDING", "MODULE_UNLOADED", "HEADER_RESTORE_PENDING",
    }
    if stage in formatted_stages and \
            PHYSICAL.swapz_header_valid(header, state["size_bytes"]):
        known_digest = state.get("formatted_header_sha256")
        if isinstance(known_digest, str) and digest == known_digest:
            return "FORMATTED_SWZ"
    raise LiveSwapError("current header is ambiguous or torn; manual review required")


def _mapper_rows_for_state(ops, state):
    if not state.get("dm_name") or not state.get("dm_uuid"):
        return []
    rows = ops.dm_rows()
    matches = [(name, uuid) for name, uuid in rows
               if name == state["dm_name"] or uuid == state["dm_uuid"]]
    if matches and matches != [(state["dm_name"], state["dm_uuid"])]:
        raise LiveSwapError("saved mapper identity was substituted")
    return matches


def _record_recovery_required(state_dir, state, results, error):
    prior = state.get("stage")
    if prior == "TRIAL_STOPPING":
        prior = state.get("stage_before_trial_stopping")
    if prior != "RECOVERY_REQUIRED":
        state["recovery_previous_stage"] = prior
    state["stage"] = "RECOVERY_REQUIRED"
    state["recovery_error"] = _bounded(error)
    state["updated_at"] = _utc_now()
    _save_state(state_dir, state)
    results["final_recovery_state"] = "RECOVERY_REQUIRED"
    results["recovery_error"] = _bounded(error)
    results["recovery_disposition"] = "REQUIRES_REVIEW"
    results["end_timestamp"] = _utc_now()
    _save_results(state_dir, results)


def _cleanup_and_restore(state_dir, state, results, ops, *,
                         module_owned_by_process):
    """Conditional normal/failure cleanup, preserving an active mapper on error."""
    state_dir = Path(state_dir)
    _transition(state_dir, state, "TRIAL_STOPPING", results)
    ops.release_pressure_cgroup(state)
    _reconcile_trial_state(state_dir, state, ops)
    target = ops.target_descriptor(state)
    _verify_trial_swap_inventory(ops, state)
    live_rows = _mapper_rows_for_state(ops, state)
    if live_rows:
        _verify_mapper(ops, state, allow_open=True)
        dm_major, dm_minor, _ = _mapper_info(ops, state)
        state["dm_major"], state["dm_minor"] = dm_major, dm_minor
        active = ops.active_swap_for(dm_major, dm_minor)
        if active is not None:
            sample = _memory_sample(ops)
            drain_headroom = _check_drain_headroom(active["used_kib"], sample)
            results["mapper_swapoff_drain_headroom_bytes"] = drain_headroom
            _save_results(state_dir, results)
            _transition(state_dir, state, "MAPPER_SWAPOFF_PENDING", results)
            _record_phase(state_dir, state, results, ops, "swapoff_mapper",
                          ["swapoff", "--", f"/dev/mapper/{state['dm_name']}"],
                          timeout=SWAPOFF_TIMEOUT_SECONDS)
            if ops.active_swap_for(dm_major, dm_minor) is not None:
                raise LiveSwapError(
                    "mapper swap remains active after successful swapoff")
            state["active_mapper_swap"] = False
            _save_state(state_dir, state)
            _verify_trial_swap_inventory(ops, state)
        _verify_mapper(ops, state, allow_open=False)
        _transition(state_dir, state, "MAPPER_REMOVE_PENDING", results)
        for attempt in range(1, MAPPER_OPEN_ATTEMPTS + 1):
            try:
                _record_phase(state_dir, state, results, ops,
                              f"remove_mapper_attempt_{attempt}",
                              ["dmsetup", "remove", "--", state["dm_name"]])
                break
            except LiveSwapError:
                if attempt == MAPPER_OPEN_ATTEMPTS or \
                        not _mapper_rows_for_state(ops, state):
                    raise
                time.sleep(0.5)
        if _mapper_rows_for_state(ops, state):
            raise LiveSwapError("owned mapper remains after normal removal")
        state["mapper_removal_succeeded"] = True
        _transition(state_dir, state, "MAPPER_REMOVED", results)
    elif state.get("active_mapper_swap"):
        raise LiveSwapError("state says mapper swap was active but mapper is absent")

    if ops.target_holders(state["major"], state["minor"]):
        raise LiveSwapError("backing partition still has holders before restoration")
    module_present = ops.module_loaded()
    if module_present and module_owned_by_process and \
            state.get("module_loaded_by_process") is True:
        module_refs = ops.module_refcount()
        if module_refs != 0:
            raise LiveSwapError("dm_swapz still has users; leave it loaded for review")
        _transition(state_dir, state, "MODULE_UNLOAD_PENDING", results)
        _record_phase(state_dir, state, results, ops, "unload_module",
                      ["rmmod", "dm_swapz"])
        if ops.module_loaded():
            raise LiveSwapError("dm_swapz remained loaded after owned unload")
        state["module_cleanup"] = "unloaded_by_owner_process"
        _transition(state_dir, state, "MODULE_UNLOADED", results)
    elif module_present:
        raise LiveSwapError(
            "dm_swapz remains loaded without same-process ownership; manual review required")
    else:
        state["module_cleanup"] = "already_absent"

    header = ops.read_header(target)
    kind = _recognized_current_header(header, state)
    active_original = ops.active_swap_for(state["major"], state["minor"])
    if kind != "ORIGINAL" and active_original is not None:
        raise LiveSwapError("backing partition is active as swap with a non-original header")
    if kind != "ORIGINAL":
        _transition(state_dir, state, "HEADER_RESTORE_PENDING", results)
        ops.write_header(target, _read_recovery_file(state_dir / BACKUP_NAME),
                         expected_current=header)
    restored = ops.read_header(target)
    if hashlib.sha256(restored).hexdigest() != ORIGINAL_HEADER_SHA256:
        raise LiveSwapError("exact original header restoration failed")
    state["final_header_sha256"] = hashlib.sha256(restored).hexdigest()
    _transition(state_dir, state, "HEADER_RESTORED", results)
    if active_original is None:
        _transition(state_dir, state, "ORIGINAL_SWAPON_PENDING", results)
        _record_phase(state_dir, state, results, ops, "swapon_original",
                      ["swapon", "--", state["swap_path"]])
    final_swap = ops.active_swap_for(state["major"], state["minor"])
    if final_swap is None or (final_swap["size_kib"], final_swap["priority"]) != (
            state["swap_size_kib"], state["swap_priority"]):
        raise LiveSwapError("original swap size or priority failed restoration")
    state["original_swap_restored"] = True
    _verify_trial_swap_inventory(ops, state)

    state["recovery_state"] = "COMPLETE"
    _transition(state_dir, state, "COMPLETE", results)
    results["final_header_sha256"] = state["final_header_sha256"]
    results["final_swap_row"] = final_swap
    results["final_recovery_state"] = "COMPLETE"
    results["recovery_disposition"] = "COMPLETE"
    results["mapper_removal_succeeded"] = not bool(
        _mapper_rows_for_state(ops, state))
    results["module_cleanup"] = state["module_cleanup"]
    results["end_timestamp"] = _utc_now()
    _release_marker(state)
    _save_results(state_dir, results)
    return {"status": "COMPLETE", "state": state}


def _existing_results(state_dir, state):
    try:
        return PHYSICAL._load_unique_json(
            _read_recovery_file(Path(state_dir) / RESULTS_NAME))
    except (LiveSwapError, OSError, ValueError):
        return {
            "schema": "swapz-live-swap-results-v1",
            "run_id": state["run_id"],
            "commands": [],
            "phases": [],
            "observations": [],
        }


def _recovery_refusal(state_dir, state, message):
    """Record REQUIRES_REVIEW for a refusal, so stranded swap is never silent.

    A COMPLETE state keeps its stage, so a repaired host can still re-confirm
    the completed restoration. The refusal is then recorded in the results only.
    """
    error = LiveSwapError(message)
    if state.get("stage") == "COMPLETE":
        results = _existing_results(state_dir, state)
        results["recovery_disposition"] = "REQUIRES_REVIEW"
        results["recovery_error"] = _bounded(error)
        results["end_timestamp"] = _utc_now()
        _save_results(state_dir, results)
        return error
    _record_recovery_required(
        state_dir, state, _existing_results(state_dir, state), error)
    return error


def recover_state(state_dir, *, ops=None, module_owned_by_process=False,
                  lock_fd=None):
    """Cold/manual recovery refuses live mappings and ambiguous device state."""
    del lock_fd
    ops = ops or LinuxOps()
    state_dir = Path(state_dir)
    state = PHYSICAL._load_unique_json(
        _read_recovery_file(state_dir / STATE_NAME))
    backup = _read_recovery_file(state_dir / BACKUP_NAME)
    _validate_state(state, backup, state_dir)
    marker_present = _assert_recovery_ownership(
        state, allow_released=state.get("stage") == "COMPLETE")
    try:
        target = ops.target_descriptor(state)
        kind = _recognized_current_header(target["header"], state)
        mapper_rows = _mapper_rows_for_state(ops, state)
    except LiveSwapError as exc:
        raise _recovery_refusal(state_dir, state, str(exc)) from exc
    if mapper_rows:
        raise _recovery_refusal(
            state_dir, state,
            "mapper still exists; standalone recovery will not remove a live mapping")
    active = ops.active_swap_for(state["major"], state["minor"])
    if active is not None and (kind != "ORIGINAL" or (
            active["size_kib"], active["priority"]) != (
            state["swap_size_kib"], state["swap_priority"])):
        raise _recovery_refusal(
            state_dir, state, "active swap conflicts with saved recovery state")
    if ops.target_holders(state["major"], state["minor"]):
        raise _recovery_refusal(
            state_dir, state, "backing partition has holders; recovery stopped")
    if state.get("stage") != "COMPLETE":
        results = _existing_results(state_dir, state)
        try:
            return _cleanup_and_restore(
                state_dir, state, results, ops,
                module_owned_by_process=module_owned_by_process)
        except BaseException as exc:
            _record_recovery_required(state_dir, state, results, exc)
            raise
    final = ops.active_swap_for(state["major"], state["minor"])
    if final is None or (final["size_kib"], final["priority"]) != (
            state["swap_size_kib"], state["swap_priority"]):
        raise _recovery_refusal(
            state_dir, state, "COMPLETE state does not match current normal swap")
    if hashlib.sha256(ops.read_header(target)).hexdigest() != \
            ORIGINAL_HEADER_SHA256 or ops.module_loaded() or \
            _mapper_rows_for_state(ops, state) or \
            ops.target_holders(state["major"], state["minor"]):
        raise _recovery_refusal(
            state_dir, state,
            "COMPLETE recovery state does not match current host state")
    if marker_present:
        _release_marker(state)
    return {"status": "COMPLETE", "state": state}


def _trial_outcome(activation_error, results):
    if activation_error is not None and not isinstance(activation_error, SafeStop):
        return "FAIL"
    if activation_error is not None or \
            results.get("stop_reason") != "duration_complete":
        return "SAFE_STOP"
    return "PASS" if results.get("actual_swap_io_observed") else "ACTIVATION_ONLY"


def run_trial(approval_path, state_dir, *, confirm, ops=None,
              monotonic=time.monotonic, sleep=time.sleep):
    """Execute one owner-authorized trial, with one cleanup attempt and no retry."""
    global _STOP_REQUESTED
    if not LIVE_SWAP_EXECUTION_ENABLED:
        raise LiveSwapError(
            "live-swap mutations are disabled pending owner authorization")
    ops = ops or LinuxOps()
    if os.geteuid() != 0:
        raise LiveSwapError("run requires root; no automatic privilege escalation")
    if confirm != "LIVE-SWAP-TRIAL":
        raise LiveSwapError("run requires the exact LIVE-SWAP-TRIAL confirmation")
    lock_fd = PHYSICAL._partition_lock(DEVICE_PARTUUID)
    state_dir = Path(state_dir)
    _STOP_REQUESTED = False
    try:
        plan = read_only_plan(approval_path, ops=ops)
        if plan["status"] != "PASS":
            raise LiveSwapError("read-only plan is not fully positive")
        approval = _load_unique_json(approval_path)
        if _approval_digest(approval) != plan.get("approval_sha256"):
            raise LiveSwapError("approval record changed after the read-only plan")
        target = ops.inspect_target()
        _validate_target_facts(target)
        run_id = validate_approval(
            approval,
            head=plan["head"],
            helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            artifacts=ops.artifact_digests(), target=target)
        if run_id != approval.get("run_id"):
            raise LiveSwapError("approval run identity changed after the read-only plan")
        _exact_active_swap_inventory(ops)
        state, backup, snapshots = _create_durable_state(
            approval, target, plan, state_dir, ops)
        results = {
            "schema": "swapz-live-swap-results-v1",
            "run_id": approval["run_id"],
            "head": plan["head"],
            "qualified_source": QUALIFIED_SOURCE,
            "helper_sha256": state["helper_sha256"],
            "artifact_digests": dict(state["artifact_digests"]),
            "device": DEVICE_PATH,
            "major_minor": f"{DEVICE_MAJOR}:{DEVICE_MINOR}",
            "partuuid": DEVICE_PARTUUID,
            "parent_major_minor": state["parent_major_minor"],
            "size_bytes": DEVICE_SIZE_BYTES,
            "original_header_sha256": ORIGINAL_HEADER_SHA256,
            "fallback_mode": "none",
            "logical_capacity_bytes": LOGICAL_BYTES,
            "start_timestamp": _utc_now(),
            "commands": [],
            "phases": [],
            "observations": [],
            "max_swapz_used_kib": 0,
        }
        _save_results(state_dir, results)
        PHYSICAL._consume_review(target, approval["run_id"])
        state["consumed_run_id"] = True
        _transition(state_dir, state, "PREPARED", results)
        activation_error = None
        try:
            _activate_trial(
                state_dir, state, results, target, snapshots, ops,
                monotonic=monotonic, sleep=sleep)
        except BaseException as exc:
            activation_error = exc
            results["failure"] = _bounded(exc)
            if isinstance(exc, SafeStop):
                results.setdefault("stop_reason", exc.reason)
            _save_results(state_dir, results)
        try:
            recovery = _cleanup_and_restore(
                state_dir, state, results, ops,
                module_owned_by_process=bool(
                    state.get("module_loaded_by_process")))
        except BaseException as recovery_exc:
            # Persist review-required state if possible, but a failed evidence
            # write cannot replace the earlier worker or cleanup failure.
            recovery_record_error = None
            try:
                _record_recovery_required(
                    state_dir, state, results, recovery_exc)
            except BaseException as record_exc:
                recovery_record_error = record_exc
            try:
                results["kernel_diagnostics"] = ops.kernel_diagnostics(
                    results["start_timestamp"], state)
                results["kernel_diagnostics_capture_error"] = None
                _save_results(state_dir, results)
            except Exception as diagnostics_exc:
                results["kernel_diagnostics_capture_error"] = _bounded(
                    diagnostics_exc)
                try:
                    _save_results(state_dir, results)
                except Exception:
                    pass
            # A cleanup failure never replaces the first worker/integrity cause.
            original_detail = (
                f"phase=activation original={type(activation_error).__name__} "
                f"errno={getattr(activation_error, 'errno', None)} "
                f"detail={_bounded(activation_error)}; "
                if activation_error is not None else "")
            raise LiveSwapError(
                f"{original_detail}phase=cleanup recovery=REQUIRES_REVIEW "
                f"retained=private_recovery_state "
                f"cleanup={type(recovery_exc).__name__} "
                f"errno={getattr(recovery_exc, 'errno', None)} "
                f"record={'FAILED' if recovery_record_error else 'RECORDED'} "
                f"record_errno={getattr(recovery_record_error, 'errno', None)}"
                ) from (
                    activation_error if activation_error is not None
                    else recovery_exc)
        try:
            results["kernel_diagnostics"] = ops.kernel_diagnostics(
                results["start_timestamp"], state)
            results["kernel_diagnostics_capture_error"] = None
        except Exception as diagnostics_exc:
            results["kernel_diagnostics"] = {
                "available": False,
                "source": None,
                "time_filter_applied": False,
            }
            results["kernel_diagnostics_capture_error"] = _bounded(
                diagnostics_exc)
        results["final_recovery_state"] = recovery["state"]["stage"]
        results["recovery_disposition"] = "COMPLETE"
        results["actual_swap_io_observed"] = _actual_swap_io(results)
        results["live_swap_trial"] = _trial_outcome(activation_error, results)
        results["normal_swap_restored"] = True
        results["end_timestamp"] = _utc_now()
        _save_results(state_dir, results)
        if activation_error is not None and \
                not isinstance(activation_error, SafeStop):
            raise LiveSwapError(
                "live trial failed; normal swap restored; "
                f"phase=activation errno={getattr(activation_error, 'errno', None)} "
                f"retained=private_recovery_state: {_bounded(activation_error)}"
                ) from activation_error
        return results
    finally:
        os.close(lock_fd)


def recover_cli(state_dir, *, confirm, ops=None):
    if not LIVE_SWAP_EXECUTION_ENABLED:
        raise LiveSwapError(
            "live-swap recovery CLI is disabled pending independent safety review")
    if os.geteuid() != 0:
        raise LiveSwapError("recover requires root; no automatic privilege escalation")
    if confirm != "RESTORE-ORIGINAL-SWAP":
        raise LiveSwapError("recover requires exact RESTORE-ORIGINAL-SWAP confirmation")
    state_dir = Path(state_dir)
    lock_fd = PHYSICAL._partition_lock(DEVICE_PARTUUID)
    try:
        return recover_state(state_dir, ops=ops,
                             module_owned_by_process=False,
                             lock_fd=lock_fd)
    finally:
        os.close(lock_fd)


def main(argv=None):
    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)
    parser = argparse.ArgumentParser(
        description="Private experimental swapz live-swap supervisor")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan", help="read-only host and approval gates")
    plan.add_argument("--approval", required=True)
    run = subparsers.add_parser("run", help="run one owner-authorized bounded trial")
    run.add_argument("--approval", required=True)
    run.add_argument("--state-dir", required=True)
    run.add_argument("--confirm", required=True)
    recover = subparsers.add_parser("recover", help="restore a saved live-trial state")
    recover.add_argument("--state-dir", required=True)
    recover.add_argument("--confirm", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            result = read_only_plan(args.approval)
            print(json.dumps(result, sort_keys=True, indent=2))
            return 0 if result["status"] == "PASS" else 2
        if args.command == "run":
            result = run_trial(args.approval, args.state_dir,
                               confirm=args.confirm)
            print(json.dumps(result, sort_keys=True, indent=2))
            return 0 if result["live_swap_trial"] in {"PASS", "SAFE_STOP"} else 2
        result = recover_cli(args.state_dir, confirm=args.confirm)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (LiveSwapError, PHYSICAL.ProbeError, OSError, ValueError) as exc:
        print(f"LIVE_SWAP_BLOCKED: {_bounded(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
