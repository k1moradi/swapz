#!/usr/bin/env python3
"""Fail-closed loaded-kernel smoke for an explicitly authorized disposable VM.

The default invocation is intentionally inert: every live operation requires
an exact authorization statement bound to the VM label, source revision, and
selected module digest.  Rootless coverage lives in virtual-smoke-test.py and
uses an injected fake operations object; this file is not a benchmark.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Protocol


ROOT = Path(__file__).resolve().parents[2]
PAGE_BYTES = 4096
SECTOR_BYTES = 512
TARGET_SECTORS = PAGE_BYTES // SECTOR_BYTES
BACKING_BYTES = 32 * 1024 * 1024
BACKING_SECTORS = BACKING_BYTES // SECTOR_BYTES
WRITE_DELAY_MS = 5000
WRITE_TIMEOUT_MS = 5000
STAGED_WAIT_MS = 4000
READ_TIMEOUT_MS = 2500
STATUS_TIMEOUT_MS = 1000
SUSPEND_TIMEOUT_MS = 12000
COMMAND_GRACE_MS = 500
LOG_READ_TIMEOUT_MS = 250
POLL_INTERVAL_S = 0.025
RUN_DIR_ROOT = Path("/dev/shm")
REQUIRED_STATUS = (
    "staged_hits",
    "staged_early",
    "inflight_blocks",
    "async_cb",
    "failed",
    "pack_records",
    "fill_blocks",
    "buf0_blocks",
    "buf1_blocks",
)
KERNEL_WARNING = re.compile(
    r"(?:\bWARNING:\s|\bBUG:\s|\bOops:\s|\bCall Trace:\s|"
    r"dm-swapz.*(?:\bWARN\b|\bERROR\b|ownership.{0,32}(?:fail|bad)|"
    r"(?:fail|bad).{0,32}(?:bio|owner)|pending callback))",
    re.IGNORECASE,
)


class SmokeFailure(RuntimeError):
    """A known validation or operation failure."""


class SetupFailure(SmokeFailure):
    """A setup command failed and its intended resource is confirmed absent."""


class QuarantineRequired(SmokeFailure):
    """State is ambiguous or a live-kernel safety condition failed."""


class CommandTimeout(QuarantineRequired):
    """A bounded command timed out; its kernel-side effects are uncertain."""


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class Config:
    vm_id: str
    source_sha: str
    module_path: Path
    module_sha256: str
    authorization: str
    live: bool
    host_id: str | None = None
    host_machine_id_sha256: str | None = None


@dataclass
class Owned:
    run_dir: Path | None = None
    image: Path | None = None
    payload: Path | None = None
    loop: str | None = None
    loop_candidate: bool = False
    loop_owned: bool = False
    module_candidate: bool = False
    module_owned: bool = False
    delay_name: str | None = None
    delay_uuid: str | None = None
    delay_table: str | None = None
    delay_candidate: bool = False
    delay_owned: bool = False
    target_name: str | None = None
    target_uuid: str | None = None
    target_table: str | None = None
    target_candidate: bool = False
    target_owned: bool = False
    io_started: bool = False
    quarantined: bool = False


class Operations(Protocol):
    """Small seam used by rootless lifecycle tests."""

    def preflight(self, config: Config, names: tuple[str, str]) -> int: ...
    def make_run_dir(self, run_id: str) -> Path: ...
    def make_page_and_backing(self, run_dir: Path) -> tuple[Path, Path, bytes]: ...
    def load_module(self, module: Path) -> None: ...
    def module_loaded(self) -> bool: ...
    def targets(self) -> set[str]: ...
    def attach_loop(self, image: Path) -> str: ...
    def verify_loop(self, loop: str, image: Path) -> bool: ...
    def device_number(self, path: str) -> str: ...
    def loop_holders_empty(self, loop: str) -> bool: ...
    def detach_loop(self, loop: str) -> None: ...
    def loop_exists(self, loop: str) -> bool: ...
    def dm_create(self, name: str, uuid: str, table: str) -> None: ...
    def dm_exists(self, name: str) -> bool: ...
    def dm_uuid(self, name: str) -> str: ...
    def dm_open_count(self, name: str) -> int: ...
    def dm_table(self, name: str) -> list[str]: ...
    def dm_status(self, name: str) -> dict[str, int]: ...
    def dm_is_suspended(self, name: str) -> bool: ...
    def dm_suspend(self, name: str) -> None: ...
    def dm_resume(self, name: str) -> None: ...
    def dm_remove(self, name: str) -> None: ...
    def dm_holders_empty(self, name: str) -> bool: ...
    def write_page(self, target: str, payload: Path) -> None: ...
    def read_page(self, target: str, output: Path) -> bytes: ...
    def new_kernel_messages(self) -> list[str]: ...
    def sleep(self, seconds: float) -> None: ...
    def unload_module(self) -> None: ...
    def remove_run_dir(self, run_dir: Path) -> None: ...
    def quarantine_record(self, owned: Owned, reason: str,
                          latest_status: dict[str, int] | None,
                          messages: list[str]) -> None: ...


def authorization_statement(vm_id: str, source_sha: str,
                            module_sha256: str, *,
                            host_id: str | None = None,
                            host_machine_id_sha256: str | None = None) -> str:
    if host_id is not None:
        machine = host_machine_id_sha256 or ""
        return (
            "I AUTHORIZE swapz V2.2 smoke only on bare-metal development PC "
            f"{host_id} with machine-id SHA-256 {machine}, source {source_sha} "
            f"and module SHA-256 {module_sha256}; permitted operations are "
            "one 32 MiB /dev/shm-backed file attached to one owned loop device, "
            "one dm-delay target, one one-page swapz target, one aligned 4 KiB "
            "write and two aligned 4 KiB reads (first while lower I/O is "
            "outstanding, second after ordinary suspend/resume drain), "
            "read-only status and kernel-log checks, ordinary suspend/resume, "
            "ordinary cleanup of positively owned test resources, and "
            "insmod/rmmod of only the selected dm-swapz module; "
            "the developer accepts risk of kernel hang or crash on this PC; "
            "NOT authorized are swapoff or swapon, SD-card or other raw "
            "physical-partition reads/writes, mounts, swap activation, "
            "forced removal, unrelated-device cleanup or host reboot."
        )
    return (
        f"I AUTHORIZE swapz V2.2 smoke only on disposable VM {vm_id} with "
        f"source {source_sha} and module SHA-256 {module_sha256}; permitted "
        "operations are one /dev/shm-backed loop device, one dm-delay target, "
        "one swapz target, one aligned 4 KiB write, two separate aligned "
        "4 KiB reads (one while the lower write is outstanding and one after "
        "ordinary suspend/resume drain), ordinary suspend and "
        "resume, ordinary removal of resources positively created by this run, "
        "and insmod/rmmod of only the selected dm-swapz module; no swap "
        "activation, mount, physical storage, forced removal, or host reboot."
    )


def validate_cli_config(config: Config) -> None:
    if not config.live:
        raise SmokeFailure("missing --run-live; no operation was attempted")
    if config.host_id is None:
        if not re.fullmatch(r"disposable-[A-Za-z0-9._-]{1,60}", config.vm_id):
            raise SmokeFailure("--vm-id must use the disposable-<label> form")
        if config.host_machine_id_sha256 is not None:
            raise SmokeFailure("bare-metal machine digest cannot be used with VM mode")
    else:
        if (config.vm_id or
                not re.fullmatch(r"devpc-[A-Za-z0-9._-]{1,60}", config.host_id)):
            raise SmokeFailure("host mode requires --host-id devpc-<label> and no VM ID")
        if not config.host_machine_id_sha256 or not re.fullmatch(
                r"[0-9a-f]{64}", config.host_machine_id_sha256):
            raise SmokeFailure("host mode requires exact machine-id SHA-256")
    if not re.fullmatch(r"[0-9a-f]{40}", config.source_sha):
        raise SmokeFailure("--source-sha must be a full lowercase Git SHA")
    if not re.fullmatch(r"[0-9a-f]{64}", config.module_sha256):
        raise SmokeFailure("--module-sha256 must be a full lowercase SHA-256")
    if config.authorization != authorization_statement(
            config.vm_id, config.source_sha, config.module_sha256,
            host_id=config.host_id,
            host_machine_id_sha256=config.host_machine_id_sha256):
        raise SmokeFailure(
            "authorization text does not exactly bind the VM, source, module, "
            "and permitted operation list")


def parse_status(text: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for key, value in re.findall(r"([A-Za-z][A-Za-z0-9_]*)=([^\s]+)", text):
        if key in values:
            raise QuarantineRequired(f"duplicate status field: {key}")
        if not value.isdecimal():
            raise QuarantineRequired(f"non-numeric status field: {key}={value}")
        values[key] = int(value, 10)
    missing = sorted(set(REQUIRED_STATUS) - values.keys())
    if missing:
        raise QuarantineRequired(f"dmsetup status lacks required fields: {missing}")
    return values


def parse_info_value(text: str) -> str:
    fields = text.split()
    if len(fields) != 1:
        raise QuarantineRequired(f"expected one dmsetup info value, got {text!r}")
    return fields[0]


def parse_dm_attr(text: str) -> bool:
    """Return suspended state for the exact writable, live-table attr forms."""
    attr = parse_info_value(text)
    if attr == "L--w":
        return False
    if attr == "L-sw":
        return True
    raise QuarantineRequired(
        f"unexpected or ambiguous dmsetup attr value: {attr!r}")


class SystemOperations:
    """Host operations. Constructed only by the explicitly gated live CLI."""

    def __init__(self) -> None:
        self._kmsg_fd: int | None = None
        self._watchdog_ms: int | None = None
        self._validated_module: Path | None = None

    @staticmethod
    def _decode(file_obj: Any) -> str:
        file_obj.seek(0)
        return file_obj.read().decode("utf-8", errors="replace")

    @staticmethod
    def _kernel_record_is_warning(record: str) -> tuple[bool, str]:
        header, separator, message = record.partition(";")
        if not separator:
            raise QuarantineRequired("unrecognized /dev/kmsg record; warning evidence is incomplete")
        fields = header.split(",")
        if len(fields) != 4 or not fields[0].isdecimal():
            raise QuarantineRequired("malformed /dev/kmsg header; warning evidence is incomplete")
        priority = int(fields[0], 10)
        # printk priorities 0..4 cover emergency through warning. This catches
        # DMERR/DMWARN, whose message text need not contain the words ERROR or WARN.
        return priority <= 4 or bool(KERNEL_WARNING.search(message)), message.rstrip()

    def run(self, argv: list[str], timeout_ms: int) -> CommandResult:
        """Run without an unbounded communicate()/wait after timeout."""
        if not argv or timeout_ms <= 0:
            raise SmokeFailure("invalid command or timeout")
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            try:
                process = subprocess.Popen(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    start_new_session=True,
                    close_fds=True,
                )
            except OSError as exc:
                raise SmokeFailure(f"cannot start {argv[0]}: {exc}") from exc
            deadline = time.monotonic() + timeout_ms / 1000.0
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(min(0.025, max(0, deadline - time.monotonic())))
            if process.poll() is None:
                self._signal_process_group(process.pid, signal.SIGTERM)
                grace = time.monotonic() + COMMAND_GRACE_MS / 1000.0
                while process.poll() is None and time.monotonic() < grace:
                    time.sleep(0.025)
                self._signal_process_group(process.pid, signal.SIGKILL)
                grace = time.monotonic() + COMMAND_GRACE_MS / 1000.0
                while process.poll() is None and time.monotonic() < grace:
                    time.sleep(0.025)
                raise CommandTimeout(
                    f"command timed out after {timeout_ms} ms: {argv!r}; "
                    f"pid={process.pid}, reaped={process.poll() is not None}; "
                    "kernel-side ownership is uncertain")
            return CommandResult(
                tuple(argv),
                int(process.returncode),
                self._decode(stdout_file),
                self._decode(stderr_file),
            )

    @staticmethod
    def _signal_process_group(pid: int, sig: int) -> None:
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            pass

    def _checked(self, argv: list[str], timeout_ms: int = 3000) -> str:
        result = self.run(argv, timeout_ms)
        if result.returncode != 0:
            raise SmokeFailure(
                f"command failed rc={result.returncode}: {argv!r}\n"
                f"stdout: {result.stdout[-2000:]}\n"
                f"stderr: {result.stderr[-2000:]}"
            )
        return result.stdout.strip()

    def _require_root(self) -> None:
        if os.geteuid() != 0:
            raise SmokeFailure("live smoke requires root after explicit authorization")

    @staticmethod
    def _secure_module_path(path: Path) -> Path:
        try:
            if stat.S_ISLNK(path.lstat().st_mode):
                raise SmokeFailure("selected module path must not be a symlink")
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise SmokeFailure(f"selected module is unavailable: {path}: {exc}") from exc
        if not resolved.is_file():
            raise SmokeFailure("selected module must be a regular file")
        for item in (resolved, *resolved.parents):
            try:
                info = item.stat()
            except OSError as exc:
                raise SmokeFailure(f"cannot inspect module path component {item}: {exc}") from exc
            if info.st_uid != 0 or info.st_mode & 0o022:
                raise SmokeFailure(
                    "selected module and every parent directory must be root-owned "
                    f"and not group/world writable: {item}")
        return resolved

    @staticmethod
    def _require_protected_source_tree() -> None:
        # The Python code itself runs as root. A checkout writable by the
        # invoking user is therefore not an acceptable live execution source.
        for item in (ROOT, *ROOT.parents):
            try:
                info = item.stat()
            except OSError as exc:
                raise SmokeFailure(f"cannot inspect source path component {item}: {exc}") from exc
            if info.st_uid != 0 or info.st_mode & 0o022:
                raise SmokeFailure(
                    "live harness source tree and parents must be root-owned and "
                    f"not group/world writable: {item}")
        git_dir = ROOT / ".git"
        try:
            info = git_dir.lstat()
        except OSError as exc:
            raise SmokeFailure(f"protected source must be a full Git checkout: {exc}") from exc
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
                or info.st_mode & 0o022):
            raise SmokeFailure(
                "live smoke requires a root-owned full checkout, not a user-owned "
                "worktree or writable .git directory")
        for relative in ("kernel/dm-swapz.c", "tests/runtime/virtual-smoke.py",
                         "tests/runtime/virtual-smoke.sh"):
            path = ROOT / relative
            for component in (path, *path.parents):
                if component == ROOT.parent:
                    break
                info = component.lstat()
                if (stat.S_ISLNK(info.st_mode) or info.st_uid != 0
                        or info.st_mode & 0o022):
                    raise SmokeFailure(
                        "live source path components must be root-owned and "
                        f"non-writable: {component}")

    def _verify_baremetal_identity(self, expected_machine_sha: str) -> None:
        """Fail before mutation if the specifically approved real PC changed."""
        try:
            machine_id = Path("/etc/machine-id").read_text(encoding="ascii").strip()
        except (OSError, UnicodeError) as exc:
            raise SmokeFailure(f"cannot read host identity: {exc}") from exc
        if not re.fullmatch(r"[0-9a-f]{32}", machine_id):
            raise SmokeFailure("host machine-id format invalid")
        actual = hashlib.sha256(machine_id.encode("ascii")).hexdigest()
        if actual != expected_machine_sha:
            raise SmokeFailure("approved bare-metal machine identity differs")
        for kind in ("--vm", "--container"):
            result = self.run(["systemd-detect-virt", kind], 2000)
            # On a real host, systemd-detect-virt returns rc=1 and usually
            # no output. Any guest/container indication or ambiguity refuses.
            if result.returncode != 1 or result.stdout.strip() not in ("", "none"):
                raise SmokeFailure(
                    f"bare-metal preflight refused virtualization indicator {kind}: "
                    f"rc={result.returncode} output={result.stdout.strip()!r}")

    def preflight(self, config: Config, names: tuple[str, str]) -> int:
        """Complete all read-only authorization and identity checks first."""
        validate_cli_config(config)
        self._require_root()
        self._require_protected_source_tree()
        required = (
            "dmsetup", "losetup", "blockdev", "dd", "insmod", "rmmod",
            "modinfo", "systemd-detect-virt", "git", "stat",
        )
        missing = [tool for tool in required if shutil.which(tool) is None]
        if missing:
            raise SmokeFailure(f"missing required tools: {missing}")
        if os.sysconf("SC_PAGE_SIZE") != PAGE_BYTES:
            raise SmokeFailure("the loaded-kernel smoke requires 4096-byte pages")
        if config.host_id is not None:
            # Bare-metal is a separately approved mode, not a general escape
            # hatch for an unexpected VM/container response. Two read-only
            # systemd checks exclude known virtual machines and containers.
            self._verify_baremetal_identity(config.host_machine_id_sha256 or "")
            virt = "bare-metal"
        else:
            virt = self._checked(["systemd-detect-virt", "--vm"], 2000)
            if not virt or virt.lower() == "none":
                raise SmokeFailure("systemd-detect-virt did not confirm a virtual machine")
        fs_type = self._checked(["stat", "-f", "-c", "%T", "/dev/shm"], 2000)
        if fs_type != "tmpfs":
            raise SmokeFailure("/dev/shm is not tmpfs; refusing to create a backing file")

        head = self._checked(["git", "-C", str(ROOT), "rev-parse", "HEAD"], 2000)
        if head != config.source_sha:
            raise SmokeFailure(f"source SHA mismatch: expected {config.source_sha}, got {head}")
        for source_path in (
                "kernel/dm-swapz.c",
                "tests/runtime/virtual-smoke.py",
                "tests/runtime/virtual-smoke.sh"):
            blob = self._checked([
                "git", "-C", str(ROOT), "rev-parse",
                f"{config.source_sha}:{source_path}",
            ], 2000)
            worktree_blob = self._checked([
                "git", "-C", str(ROOT), "hash-object", source_path,
            ], 2000)
            if blob != worktree_blob:
                raise SmokeFailure(
                    f"{source_path} differs from the authorized source SHA")

        module = self._secure_module_path(config.module_path)
        digest = hashlib.sha256(module.read_bytes()).hexdigest()
        if digest != config.module_sha256:
            raise SmokeFailure(f"selected module SHA-256 mismatch: got {digest}")
        self._validated_module = module
        module_name = self._checked(["modinfo", "-F", "name", str(module)], 2000)
        if module_name.replace("_", "-") != "dm-swapz":
            raise SmokeFailure(f"selected module is not dm-swapz: name={module_name!r}")
        vermagic = self._checked(["modinfo", "-F", "vermagic", str(module)], 2000)
        kernel = os.uname().release
        if not vermagic.split() or vermagic.split()[0] != kernel:
            raise SmokeFailure(
                f"module vermagic does not match running kernel {kernel}: {vermagic!r}")
        if Path("/sys/module/dm_swapz").exists() or Path("/sys/module/dm-swapz").exists():
            raise SmokeFailure("dm-swapz is already loaded; refusing to reuse/unload it")

        self._checked(["dmsetup", "version"], 2000)
        target_lines = self._checked(["dmsetup", "targets"], 2000).splitlines()
        available_targets = {line.split()[0] for line in target_lines if line.split()}
        if "delay" not in available_targets:
            raise SmokeFailure(
                "dm-delay is not registered; it requires separate host/VM provisioning "
                "approval and must be available before invoking this harness")
        names_output = self._checked([
            "dmsetup", "info", "--columns", "--noheadings", "-o", "name",
        ], 2000)
        existing_names = {line.strip() for line in names_output.splitlines() if line.strip()}
        collision = existing_names.intersection(names)
        if collision:
            raise SmokeFailure(f"generated Device Mapper name collision: {sorted(collision)}")

        watchdog_text = (ROOT / "kernel/dm-swapz.c").read_text(encoding="utf-8")
        watchdog_match = re.search(
            r"^#define\s+SWAPZ_ASYNC_WATCHDOG_MS\s+(\d+)U\s*$",
            watchdog_text, re.MULTILINE)
        if watchdog_match is None:
            raise SmokeFailure("cannot identify the production async watchdog value")
        watchdog_ms = int(watchdog_match.group(1))
        # SWAPZ_ASYNC_WATCHDOG_MS applies to an individual in-flight lower
        # request.  It is not a wall-clock budget for all userspace polling,
        # readback, diagnostics, and suspend commands combined.
        if watchdog_ms <= WRITE_DELAY_MS + 1000:
            raise SmokeFailure(
                f"controlled lower-write delay {WRITE_DELAY_MS} ms must be at "
                f"least 1000 ms below the per-request async watchdog "
                f"{watchdog_ms} ms")

        try:
            self._kmsg_fd = os.open("/dev/kmsg", os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        except OSError as exc:
            raise SmokeFailure(f"cannot establish a bounded /dev/kmsg warning cursor: {exc}") from exc
        # Drain anything immediately available at the cursor, before mutation.
        initial_warnings = self.new_kernel_messages()
        if initial_warnings:
            print(f"KERNEL_LOG_BASELINE_WARNINGS={len(initial_warnings)} "
                  "(pre-existing records drained before fixture setup)")
            for message in initial_warnings:
                print(f"KERNEL_LOG_BASELINE: {message}")
        self._watchdog_ms = watchdog_ms
        print(f"PREFLIGHT: PASS environment={virt} identity={config.host_id or config.vm_id} "
              f"source={head} module_sha256={digest} watchdog_ms={watchdog_ms}")
        return watchdog_ms

    def make_run_dir(self, run_id: str) -> Path:
        path = RUN_DIR_ROOT / f"swapz-v22-smoke-{run_id}"
        created = False
        try:
            path.mkdir(mode=0o700)
            created = True
            os.chmod(path, 0o700)
        except OSError as exc:
            if created:
                try:
                    if (path.is_dir() and path.stat().st_uid == os.geteuid()
                            and not any(path.iterdir())):
                        path.rmdir()
                except OSError:
                    pass
            raise SmokeFailure(f"cannot create owned tmpfs run directory {path}: {exc}") from exc
        if path.stat().st_uid != 0 or stat.S_IMODE(path.stat().st_mode) != 0o700:
            raise QuarantineRequired("new run directory did not retain root-only ownership")
        return path

    def make_page_and_backing(self, run_dir: Path) -> tuple[Path, Path, bytes]:
        payload = bytes([0xA5]) * PAGE_BYTES
        payload_path = run_dir / "payload-4k.bin"
        image_path = run_dir / "backing-32m.img"
        fd = os.open(payload_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        try:
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
        image_fd = os.open(image_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        try:
            os.ftruncate(image_fd, BACKING_BYTES)
            os.fsync(image_fd)
        finally:
            os.close(image_fd)
        if payload_path.stat().st_size != PAGE_BYTES or image_path.stat().st_size != BACKING_BYTES:
            raise SmokeFailure("created tmpfs fixtures have unexpected sizes")
        return payload_path, image_path, payload

    def load_module(self, module: Path) -> None:
        if self._validated_module is None:
            raise QuarantineRequired("insmod requested before module identity preflight")
        result = self.run(["insmod", str(self._validated_module)], 5000)
        if result.returncode != 0:
            if Path("/sys/module/dm_swapz").exists():
                raise QuarantineRequired(
                    "insmod returned failure but dm-swapz appears loaded; preserve VM")
            raise SetupFailure(
                f"insmod failed rc={result.returncode}: {result.stderr[-1000:]}")

    def module_loaded(self) -> bool:
        return Path("/sys/module/dm_swapz").exists() or Path("/sys/module/dm-swapz").exists()

    def targets(self) -> set[str]:
        text = self._checked(["dmsetup", "targets"], 2000)
        return {line.split()[0] for line in text.splitlines() if line.split()}

    def attach_loop(self, image: Path) -> str:
        text = self._checked(["losetup", "--find", "--show", str(image)], 5000)
        loop = text.strip()
        if not re.fullmatch(r"/dev/loop[0-9]+", loop):
            raise QuarantineRequired(f"losetup returned an unexpected device path: {loop!r}")
        return loop

    def device_number(self, path: str) -> str:
        return self._devno(path)

    def verify_loop(self, loop: str, image: Path) -> bool:
        try:
            dev = Path(loop)
            info = dev.stat()
            if not stat.S_ISBLK(info.st_mode):
                return False
            output = self._checked([
                "losetup", "--json", "--output", "NAME,BACK-FILE", loop,
            ], 2000)
            records = json.loads(output).get("loopdevices", [])
            if len(records) != 1:
                return False
            backing = str(Path(records[0]["back-file"]).resolve(strict=True))
            if records[0]["name"] != loop or backing != str(image.resolve(strict=True)):
                return False
            size = int(self._checked(["blockdev", "--getsize64", loop], 2000))
            return size == BACKING_BYTES
        except (OSError, KeyError, ValueError, json.JSONDecodeError, SmokeFailure):
            return False

    @staticmethod
    def _devno(path: str) -> str:
        info = Path(path).stat()
        if not stat.S_ISBLK(info.st_mode):
            raise QuarantineRequired(f"expected block device: {path}")
        return f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}"

    def dm_create(self, name: str, uuid: str, table: str) -> None:
        result = self.run(["dmsetup", "create", name, "--uuid", uuid,
                           "--table", table], 5000)
        if result.returncode == 0:
            return
        if self.dm_exists(name):
            raise QuarantineRequired(
                f"dmsetup create failed rc={result.returncode} but {name} exists; "
                "ownership is ambiguous")
        raise SetupFailure(
            f"dmsetup create {name} failed rc={result.returncode}: "
            f"{result.stderr[-1000:]}")

    def dm_exists(self, name: str) -> bool:
        result = self.run(["dmsetup", "info", "--columns", "--noheadings", "-o", "name", name], 2000)
        if result.returncode == 0:
            names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            if names == [name]:
                return True
            if not names:
                raise QuarantineRequired(
                    f"dmsetup returned success but no exact name for {name}; state is ambiguous")
            raise QuarantineRequired(
                f"dmsetup name query for {name} returned unexpected names {names!r}")
        # dmsetup reports an absent named target with nonzero status; any other
        # command failure is indistinguishable from an unknown live resource.
        if any(marker in result.stderr.lower() for marker in
               ("not found", "does not exist", "no such device")):
            return False
        raise QuarantineRequired(
            f"cannot determine whether Device Mapper name {name} exists: "
            f"{result.stderr[-500:]}")

    def dm_uuid(self, name: str) -> str:
        return parse_info_value(self._checked([
            "dmsetup", "info", "--columns", "--noheadings", "-o", "uuid", name,
        ], 2000))

    def dm_open_count(self, name: str) -> int:
        value = parse_info_value(self._checked([
            "dmsetup", "info", "--columns", "--noheadings", "-o", "open", name,
        ], 2000))
        if not value.isdecimal():
            raise QuarantineRequired(f"invalid dmsetup open count for {name}: {value!r}")
        return int(value, 10)

    def dm_table(self, name: str) -> list[str]:
        result = self._checked(["dmsetup", "table", name], 2000)
        rows = [line.split() for line in result.splitlines() if line.split()]
        if len(rows) != 1:
            raise QuarantineRequired(f"expected one table row for {name}, got {rows!r}")
        return rows[0]

    def dm_status(self, name: str) -> dict[str, int]:
        return parse_status(self._checked(["dmsetup", "status", name], STATUS_TIMEOUT_MS))

    def dm_is_suspended(self, name: str) -> bool:
        try:
            attr = self._checked([
                "dmsetup", "info", "--columns", "--noheadings", "-o", "attr", name,
            ], 2000)
        except QuarantineRequired:
            raise
        except SmokeFailure as exc:
            raise QuarantineRequired(
                f"cannot establish Device Mapper suspended state for {name}: {exc}") from exc
        return parse_dm_attr(attr)

    def dm_suspend(self, name: str) -> None:
        self._checked(["dmsetup", "suspend", name], SUSPEND_TIMEOUT_MS)

    def dm_resume(self, name: str) -> None:
        self._checked(["dmsetup", "resume", name], 3000)

    def dm_holders_empty(self, name: str) -> bool:
        try:
            info = Path(f"/dev/mapper/{name}").stat()
            holders = Path(f"/sys/dev/block/{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}/holders")
            return holders.is_dir() and not any(holders.iterdir())
        except OSError:
            return False

    def dm_remove(self, name: str) -> None:
        result = self.run(["dmsetup", "remove", name], 5000)
        if result.returncode != 0:
            raise QuarantineRequired(
                f"ordinary dmsetup remove failed for owned target {name}: "
                f"{result.stderr[-1000:]}")
        if self.dm_exists(name):
            raise QuarantineRequired(f"{name} remains after ordinary dmsetup remove")

    def loop_holders_empty(self, loop: str) -> bool:
        try:
            info = Path(loop).stat()
            holders = Path(f"/sys/dev/block/{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}/holders")
            return holders.is_dir() and not any(holders.iterdir())
        except OSError:
            return False

    def detach_loop(self, loop: str) -> None:
        result = self.run(["losetup", "--detach", loop], 5000)
        if result.returncode != 0:
            raise QuarantineRequired(
                f"losetup detach failed for owned {loop}: {result.stderr[-1000:]}")
        if self.loop_exists(loop):
            raise QuarantineRequired(f"{loop} remains attached after detach")

    def loop_exists(self, loop: str) -> bool:
        result = self.run(["losetup", "--json", "--output", "NAME,BACK-FILE", loop], 2000)
        if result.returncode != 0:
            if "not found" in result.stderr.lower() or "not a loop device" in result.stderr.lower():
                return False
            raise QuarantineRequired(f"cannot verify loop state for {loop}: {result.stderr[-500:]}")
        try:
            records = json.loads(result.stdout).get("loopdevices", [])
        except json.JSONDecodeError as exc:
            raise QuarantineRequired(f"invalid losetup JSON for {loop}: {exc}") from exc
        return bool(records)

    def write_page(self, target: str, payload: Path) -> None:
        self._checked([
            "dd", f"if={payload}", f"of=/dev/mapper/{target}",
            f"bs={PAGE_BYTES}", "count=1", "oflag=direct", "conv=notrunc",
            "status=none",
        ], WRITE_TIMEOUT_MS)

    def read_page(self, target: str, output: Path) -> bytes:
        self._checked([
            "dd", f"if=/dev/mapper/{target}", f"of={output}",
            f"bs={PAGE_BYTES}", "count=1", "iflag=direct", "status=none",
        ], READ_TIMEOUT_MS)
        try:
            data = output.read_bytes()
        except OSError as exc:
            raise QuarantineRequired(f"cannot read smoke output {output}: {exc}") from exc
        if len(data) != PAGE_BYTES:
            raise QuarantineRequired(f"readback length was {len(data)}, expected {PAGE_BYTES}")
        return data

    def new_kernel_messages(self) -> list[str]:
        if self._kmsg_fd is None:
            raise QuarantineRequired("kernel log cursor is unavailable")
        messages: list[str] = []
        deadline = time.monotonic() + LOG_READ_TIMEOUT_MS / 1000.0
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self._kmsg_fd], [], [], 0)
            if not ready:
                break
            try:
                record = os.read(self._kmsg_fd, 16384).decode("utf-8", errors="replace")
            except BlockingIOError:
                break
            except OSError as exc:
                if exc.errno == errno.EPIPE:
                    raise QuarantineRequired("/dev/kmsg cursor overran; warning evidence is incomplete") from exc
                raise QuarantineRequired(f"cannot read /dev/kmsg: {exc}") from exc
            # Linux /dev/kmsg records carry priority, sequence, timestamp,
            # flags;message. Keep only warnings/errors after the baseline drain.
            warning, message = self._kernel_record_is_warning(record)
            if warning:
                messages.append(message)
        ready, _, _ = select.select([self._kmsg_fd], [], [], 0)
        if ready:
            raise QuarantineRequired(
                "/dev/kmsg did not reach a caught-up cursor within its bounded read window")
        return messages

    @staticmethod
    def sleep(seconds: float) -> None:
        time.sleep(seconds)

    def unload_module(self) -> None:
        result = self.run(["rmmod", "dm_swapz"], 5000)
        if result.returncode != 0:
            raise QuarantineRequired(
                f"ordinary rmmod dm_swapz failed: {result.stderr[-1000:]}")
        if self.module_loaded():
            raise QuarantineRequired("dm-swapz remains loaded after ordinary rmmod")

    def remove_run_dir(self, run_dir: Path) -> None:
        resolved = run_dir.resolve(strict=True)
        if resolved.parent != RUN_DIR_ROOT or not resolved.name.startswith("swapz-v22-smoke-"):
            raise QuarantineRequired(f"refusing to remove non-owned fixture path {resolved}")
        if resolved.stat().st_uid != 0:
            raise QuarantineRequired("fixture directory owner changed before cleanup")
        shutil.rmtree(resolved)

    def quarantine_record(self, owned: Owned, reason: str,
                          latest_status: dict[str, int] | None,
                          messages: list[str]) -> None:
        body = {
            "status": "QUARANTINED_DO_NOT_REUSE_VM",
            "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "reason": reason,
            "owned_or_candidate_resources": {
                key: str(value) if isinstance(value, Path) else value
                for key, value in vars(owned).items()
            },
            "last_status": latest_status,
            "new_kernel_warning_messages": messages,
            "instruction": "Preserve current kernel/device/module state; do not force-remove or reboot.",
        }
        if owned.run_dir is not None and owned.run_dir.exists():
            marker = owned.run_dir / "QUARANTINED.json"
            try:
                marker.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
                os.chmod(marker, 0o600)
            except OSError as exc:
                print(f"QUARANTINE_RECORD_WRITE_FAILED: {exc}", file=sys.stderr)
        print("VM QUARANTINED: preserve all remaining resources and do not reuse this VM",
              file=sys.stderr)
        print(json.dumps(body, sort_keys=True), file=sys.stderr)


class SmokeRunner:
    def __init__(self, config: Config, ops: Operations):
        self.config = config
        self.ops = ops
        self.owned = Owned()
        self.run_id = os.urandom(6).hex()
        self.delay_name = f"swapz-smoke-delay-{self.run_id}"
        self.target_name = f"swapz-smoke-target-{self.run_id}"
        self.delay_uuid = f"SWAPZ-SMOKE-{self.run_id.upper()}-DELAY"
        self.target_uuid = f"SWAPZ-SMOKE-{self.run_id.upper()}-TARGET"
        self.loop_devno: str | None = None
        self.delay_devno: str | None = None
        self.expected_payload: bytes | None = None
        self.watchdog_ms: int | None = None
        self.last_status: dict[str, int] | None = None
        self.last_messages: list[str] = []

    @staticmethod
    def _assert(condition: bool, message: str) -> None:
        if not condition:
            raise QuarantineRequired(message)

    def _check_messages(self, point: str) -> None:
        messages = self.ops.new_kernel_messages()
        if messages:
            self.last_messages.extend(messages)
            raise QuarantineRequired(
                f"unexpected kernel warning at {point}: {messages!r}")

    def _status(self) -> dict[str, int]:
        if self.owned.target_name is None:
            raise QuarantineRequired("cannot query status without an owned swapz target")
        status = self.ops.dm_status(self.owned.target_name)
        self.last_status = status
        if status["failed"] != 0:
            raise QuarantineRequired(f"swapz reports failed={status['failed']}")
        return status

    def _create_delay_table(self) -> str:
        if self.loop_devno is None:
            raise QuarantineRequired("loop device identity was not established")
        return (f"0 {BACKING_SECTORS} delay {self.loop_devno} 0 0 "
                f"{self.loop_devno} 0 {WRITE_DELAY_MS}")

    def _verify_dm(self, name: str, uuid: str, table: str) -> list[str]:
        if self.ops.dm_uuid(name) != uuid:
            raise QuarantineRequired(f"Device Mapper UUID does not match owned {name}")
        fields = self.ops.dm_table(name)
        expected = table.split()
        if fields != expected:
            raise QuarantineRequired(
                f"Device Mapper table identity mismatch for {name}: "
                f"expected {expected!r}, got {fields!r}")
        return fields

    def _setup(self) -> None:
        self.owned.run_dir = self.ops.make_run_dir(self.run_id)
        self.owned.payload, self.owned.image, self.expected_payload = \
            self.ops.make_page_and_backing(self.owned.run_dir)

        self.owned.loop_candidate = True
        self.owned.loop = self.ops.attach_loop(self.owned.image)
        self.owned.loop_candidate = False
        self.owned.loop_owned = True
        if not self.ops.verify_loop(self.owned.loop, self.owned.image):
            raise QuarantineRequired(
                f"loop attachment is not positively bound to owned tmpfs image: {self.owned.loop}")
        # The devno string is read from the verified block-device node; it is
        # passed to the table and checked again in the exact loaded DM table.
        self.loop_devno = self.ops.device_number(self.owned.loop)  # type: ignore[attr-defined]

        self.owned.module_candidate = True
        try:
            self.ops.load_module(self.config.module_path)
        except SetupFailure:
            self.owned.module_candidate = False
            raise
        self.owned.module_candidate = False
        self.owned.module_owned = True
        if not self.ops.module_loaded() or "swapz" not in self.ops.targets():
            raise QuarantineRequired("selected dm-swapz module did not register its target")

        delay_table = self._create_delay_table()
        self.owned.delay_name = self.delay_name
        self.owned.delay_uuid = self.delay_uuid
        self.owned.delay_table = delay_table
        self.owned.delay_candidate = True
        try:
            self.ops.dm_create(self.delay_name, self.delay_uuid, delay_table)
        except SetupFailure:
            self.owned.delay_candidate = False
            raise
        self.owned.delay_candidate = False
        self.owned.delay_owned = True
        self._verify_dm(self.delay_name, self.delay_uuid, delay_table)
        self.delay_devno = self.ops.device_number(  # type: ignore[attr-defined]
            f"/dev/mapper/{self.delay_name}")

        # Keep the creation table's operator-supplied path.  Device Mapper
        # resolves it to a dev_t, and dm_dev.name (used by swapz's table status)
        # is emitted as canonical major:minor, so verification substitutes
        # only the devno obtained from this verified owned target.
        target_table = (
            f"0 {TARGET_SECTORS} swapz /dev/mapper/{self.delay_name} staged 64")
        expected_target = target_table.split()
        expected_target[3] = self.delay_devno
        target_table_for_verification = " ".join(expected_target)
        self.owned.target_name = self.target_name
        self.owned.target_uuid = self.target_uuid
        self.owned.target_table = target_table_for_verification
        self.owned.target_candidate = True
        try:
            self.ops.dm_create(self.target_name, self.target_uuid, target_table)
        except SetupFailure:
            self.owned.target_candidate = False
            raise
        self.owned.target_candidate = False
        self.owned.target_owned = True
        self._verify_dm(self.target_name, self.target_uuid,
                        target_table_for_verification)
        print(f"FIXTURE: loop={self.owned.loop} delay={self.delay_name} "
              f"target={self.target_name} table={target_table}")

    def _wait_for_staged_inflight(self) -> dict[str, int]:
        deadline = time.monotonic() + STAGED_WAIT_MS / 1000.0
        latest: dict[str, int] | None = None
        while time.monotonic() < deadline:
            latest = self._status()
            if (latest["inflight_blocks"] > 0 and latest["async_cb"] > 0
                    and latest["staged_early"] > 0):
                return latest
            self.ops.sleep(min(POLL_INTERVAL_S, max(0, deadline - time.monotonic())))
        raise QuarantineRequired(
            f"no qualifying staged write remained in flight within {STAGED_WAIT_MS} ms; "
            f"last status={latest}")

    def _run_smoke(self) -> None:
        if self.owned.payload is None or self.owned.run_dir is None:
            raise QuarantineRequired("smoke payload was not created")
        self.owned.io_started = True
        self.ops.write_page(self.target_name, self.owned.payload)

        before = self._wait_for_staged_inflight()
        hits_before = before["staged_hits"]
        first_read = self.ops.read_page(
            self.target_name, self.owned.run_dir / "read-before-drain.bin")
        self._assert(first_read == self.expected_payload,
                     "pre-drain staged read did not match the known 4 KiB payload")
        after = self._status()
        self._assert(after["staged_hits"] > hits_before,
                     "dmsetup status staged_hits= did not increase after staged read")
        self._assert(after["inflight_blocks"] > 0 and after["async_cb"] > 0,
                     "lower write completed before staged-hit evidence was collected")
        print(f"STAGED_READ: PASS staged_hits={hits_before}->{after['staged_hits']} "
              f"inflight_blocks={after['inflight_blocks']} async_cb={after['async_cb']}")
        self._check_messages("pre-drain staged read")

        # Presuspend stops new upper I/O, seals pack/batch state, and waits for
        # the lower callback.  The 12 s command bound plus 5 s controlled delay
        # remains below the source-verified 30 s watchdog with margin.
        self.ops.dm_suspend(self.target_name)
        self._assert(self.ops.dm_is_suspended(self.target_name),
                     "ordinary dmsetup suspend did not leave target suspended")
        drained = self._status()
        self._assert(
            all(drained[key] == 0 for key in
                ("inflight_blocks", "async_cb", "pack_records", "fill_blocks",
                 "buf0_blocks", "buf1_blocks")),
            f"suspend returned before pack/buffers/callbacks drained: {drained}")
        self._check_messages("suspend drain")
        self.ops.dm_resume(self.target_name)
        self._assert(not self.ops.dm_is_suspended(self.target_name),
                     "ordinary dmsetup resume did not reactivate target")

        final_read = self.ops.read_page(
            self.target_name, self.owned.run_dir / "read-after-drain.bin")
        self._assert(final_read == self.expected_payload,
                     "post-drain read did not match the known 4 KiB payload")
        final_status = self._status()
        self._assert(
            all(final_status[key] == 0 for key in
                ("inflight_blocks", "async_cb", "pack_records", "fill_blocks",
                 "buf0_blocks", "buf1_blocks")),
            f"pending pack/buffer/callback state remains after drain: {final_status}")
        self._check_messages("post-drain read")
        print("DRAINED_READ: PASS suspend/resume completed and bytes match")

    def _cleanup(self) -> None:
        if self.owned.target_owned:
            status = self._status()
            self._assert(
                all(status[key] == 0 for key in
                    ("inflight_blocks", "async_cb", "pack_records", "fill_blocks",
                     "buf0_blocks", "buf1_blocks")),
                f"refusing target removal with pending pack/buffer/callback state: {status}")
            assert self.owned.target_name and self.owned.target_uuid and self.owned.target_table
            self._verify_dm(self.owned.target_name, self.owned.target_uuid,
                            self.owned.target_table)
            if self.ops.dm_open_count(self.owned.target_name) != 0:
                raise QuarantineRequired("swapz target has an unexpected open reference")
            if not self.ops.dm_holders_empty(self.owned.target_name):
                raise QuarantineRequired("swapz target has an unexpected Device Mapper holder")
            self._check_messages("before target removal")
            self.ops.dm_remove(self.owned.target_name)
            self.owned.target_owned = False
            self._check_messages("after target removal")

        if self.owned.delay_owned:
            assert self.owned.delay_name and self.owned.delay_uuid and self.owned.delay_table
            self._verify_dm(self.owned.delay_name, self.owned.delay_uuid,
                            self.owned.delay_table)
            if self.ops.dm_open_count(self.owned.delay_name) != 0:
                raise QuarantineRequired("delay target has an unexpected open reference")
            if not self.ops.dm_holders_empty(self.owned.delay_name):
                raise QuarantineRequired("delay target has an unexpected holder")
            self._check_messages("before delay removal")
            self.ops.dm_remove(self.owned.delay_name)
            self.owned.delay_owned = False
            self._check_messages("after delay removal")

        if self.owned.loop_owned:
            assert self.owned.loop and self.owned.image
            if not self.ops.verify_loop(self.owned.loop, self.owned.image):
                raise QuarantineRequired("loop backing identity changed before detach")
            if not self.ops.loop_holders_empty(self.owned.loop):
                raise QuarantineRequired("loop device has an unexpected holder")
            self.ops.detach_loop(self.owned.loop)
            self.owned.loop_owned = False
            if self.ops.loop_exists(self.owned.loop):
                raise QuarantineRequired("loop device remains attached after detach")
            self._check_messages("after loop detach")

        if self.owned.module_owned:
            if not self.ops.module_loaded():
                raise QuarantineRequired("owned dm-swapz module disappeared before unload")
            self.ops.unload_module()
            self.owned.module_owned = False
            self._check_messages("after dm-swapz unload")

        if self.owned.run_dir is not None:
            self.ops.remove_run_dir(self.owned.run_dir)
            self.owned.run_dir = None

    def _quarantine(self, reason: str) -> None:
        self.owned.quarantined = True
        try:
            if self.owned.target_owned and self.owned.target_name:
                self.last_status = self.ops.dm_status(self.owned.target_name)
        except BaseException:
            pass
        try:
            self.last_messages.extend(self.ops.new_kernel_messages())
        except BaseException:
            pass
        self.ops.quarantine_record(self.owned, reason,
                                   self.last_status, self.last_messages)

    def run(self) -> None:
        validate_cli_config(self.config)
        self.watchdog_ms = self.ops.preflight(
            self.config, (self.delay_name, self.target_name))
        if self.watchdog_ms <= 0:
            raise SmokeFailure("invalid async watchdog reported by preflight")
        try:
            self._setup()
            self._run_smoke()
            self._cleanup()
        except SetupFailure:
            try:
                self._cleanup()
            except BaseException as cleanup_error:
                self._quarantine(f"setup failed and partial cleanup was unsafe: {cleanup_error}")
                raise QuarantineRequired(str(cleanup_error)) from cleanup_error
            raise
        except BaseException as exc:
            self._quarantine(str(exc))
            if isinstance(exc, QuarantineRequired):
                raise
            raise QuarantineRequired(
                f"live smoke stopped with uncertain state: {type(exc).__name__}: {exc}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run narrowly scoped loaded-kernel smoke on a separately authorized VM or real development PC.")
    parser.add_argument("--run-live", action="store_true",
                        help="required explicit switch; never set by rootless tests")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--vm-id", help="approved disposable-<label> VM identity")
    mode.add_argument("--host-id", help="approved devpc-<label> real development PC")
    parser.add_argument("--host-machine-id-sha256",
                        help="bare-metal only: SHA-256 of stripped /etc/machine-id")
    parser.add_argument("--source-sha", required=True,
                        help="exact checked-out Git commit whose kernel source built the module")
    parser.add_argument("--module", required=True, type=Path,
                        help="root-owned, non-writable selected dm-swapz.ko")
    parser.add_argument("--module-sha256", required=True,
                        help="independently recorded SHA-256 of selected module")
    parser.add_argument("--authorization", required=True,
                        help="exact authorization_statement() for this VM, source, module and operation scope")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = Config(
        vm_id=args.vm_id or "",
        source_sha=args.source_sha,
        module_path=args.module,
        module_sha256=args.module_sha256,
        authorization=args.authorization,
        live=args.run_live,
        host_id=args.host_id,
        host_machine_id_sha256=args.host_machine_id_sha256,
    )
    try:
        SmokeRunner(config, SystemOperations()).run()
    except SmokeFailure as exc:
        print(f"VIRTUAL_SMOKE: FAIL: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("VIRTUAL_SMOKE: INTERRUPTED; preserve PC/VM state and remaining resources; no forced cleanup",
              file=sys.stderr)
        return 1
    print("VIRTUAL_SMOKE: PASS (authorized host/VM, tmpfs-loop only; not benchmark evidence)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
