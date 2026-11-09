#!/usr/bin/env python3
"""Private physical correctness smoke/recovery and campaign preflight.

This is not part of make test and produces no performance qualification.
The campaign-plan action is read-only and can only report admission readiness;
it never substitutes for paired physical workloads. Before any correctness-smoke
write the helper requires an explicitly repeated stable device path, an
unused active swap partition, a latest-source owner PASS and identical
qualified-artifact evidence, plus a verbal review record bound to source,
helper and device.
"""
import argparse
from datetime import datetime, timezone
import errno
import fcntl
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import secrets
import select
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[2]
PAGE_BYTES = 4096
SWAP_SIGNATURE = b"SWAPSPACE2"
LOGICAL_SECTORS = 32768
EXPECTED_SCOPE = "physical swap backing correctness smoke only"
DEVELOPMENT_SCOPE = (
    "physical backing data-path smoke only; not production qualification")
STATE_NAME = "state.json"
# block0.bin is read only for historical pre-migration journals. New trials
# never copy or restore the ordinary SWAPSPACE2 header.
BACKUP_NAME = "block0.bin"
RESULTS_NAME = "results.json"
RUNTIME_OWNERSHIP_PHASE = "ONE_USE_RUNTIME_BOUND"
RECOVERY_OWNERSHIP_PHASE = "ONE_USE_RECOVERY_BOUND"
LEGACY_ACTIVE_RECOVERY_OWNERSHIP_PHASE = "ACTIVE_RECOVERY"
LEGACY_PRECLAIM_RECOVERY_OWNERSHIP_PHASE = "RECOVERY_PREPARED"
CANONICAL_MAIN_REMOTE = "https://github.com/k1moradi/swapz.git"
VERBAL_REVIEWER = "openai-chatgpt-external-reviewer"
VERBAL_APPROVAL_TEXT = (
    "Approved for one bounded physical swap-partition correctness round-trip only, "
    "provided the exact qualified artifacts remain unchanged, the current "
    "helper-policy commit passes its non-privileged CI, the selected partition "
    "passes every read-only identity/safety check, recovery state is durably "
    "stored on persistent media, and the helper restores and verifies the "
    "original swap partition before completion. Any mismatch, unexpected state, "
    "or recovery uncertainty voids this approval and requires the run to stop."
)
MAX_RECORDED_OUTPUT_CHARS = 4096
DEVELOPMENT_SWAPOFF_MIN_AVAILABLE_KIB = 1024 * 1024
DEVELOPMENT_SWAPOFF_MARGIN_KIB = 512 * 1024
# Recovery can reproduce Linux's default -1 priority or an explicit
# util-linux priority in 0..32767. Reject anything else before mutation.
LINUX_SWAP_PRIORITY_MIN = -1
LINUX_SWAP_PRIORITY_MAX = 32767
# The swapz DM status ABI contains many named counters. Preserve a bounded
# complete status line rather than certifying a clipped prefix as healthy.
MAX_STATUS_OUTPUT_CHARS = 32768
LOWER_IO_CLAIM_BOUNDARY = (
    "lower-device bytes and requests are host-visible physical I/O; "
    "they are not direct NAND-wear or endurance measurements"
)
VIRTUAL_LOWER_IO_CLAIM_BOUNDARY = (
    "guest partition bytes and requests are virtual-device I/O only; "
    "they are not physical-media, NAND-wear or endurance measurements"
)
KERNEL_FATAL_PATTERN = re.compile(
    r"\b(?:BUG|Oops|panic|WARNING|error|failed|failure|drain invariant|"
    r"corrupt(?:ion|ed)?)\b", re.IGNORECASE)
VIRTUAL_BLOCK_PARENT_RE = re.compile(
    r"(?:dm-|loop|ram|zram|nullb|nbd|rbd|md|zd|vd|xvd).*")
POST_QUALIFICATION_PATHS = frozenset({
    "tests/tools/physical-swap-probe.py",
    "tests/runtime/native/physical-swap-probe-test.py",
    "docs/testing_standards.md",
    "docs/ROADMAP.md",
    "test_results.json",
})
# The independent reviewer attests the exact binaries used, not merely their names.
PHYSICAL_ARTIFACTS = (
    ("formatter_sha256", "build/userspace/swapzctl", True),
    ("module_sha256", "build/kernel/experimental/dm-swapz.ko", False),
    ("oracle_sha256", "build/tests/device-roundtrip", True),
)
QUALIFICATION_STAGE_NAMES = (
    "Build module and helpers", "Native and rootless contracts",
    "Kernel warnings W=1", "Kernel warnings W=2",
    "Owned RAM smoke + mixed/QD pilot",
)
# Legacy pre-migration journal recognition only. New runs never create or\n# write this header; physical backing remains ordinary SWAPSPACE2.\nSWAPZ_HEADER_MAGIC = b"SWAPZ001"\nSWAPZ_HEADER_VERSION = 1
BLKGETSIZE64 = 0x80081272  # Linux 64-bit x86_64/aarch64 _IOR(0x12, 114, size_t).
RECOVERY_BASE = Path("/var/lib/swapz/physical-recovery")
# New development/algorithm trials keep ownership state in tmpfs. If the
# machine reboots, mapper/module state is gone and the unchanged SWAPSPACE2
# partition needs no raw-header recovery.
ALGORITHM_RUNTIME_BASE = Path("/run/swapz/algorithm-physical")
PERSISTENT_RECOVERY_FILESYSTEMS = frozenset({
    "ext2", "ext3", "ext4", "xfs", "btrfs", "f2fs",
})


class ProbeError(RuntimeError):
    pass


class ProbeFailure(ProbeError):
    """A physical execution ran and failed, with cleanup otherwise complete."""


class RecoveryRequiredError(ProbeError):
    """Recovery or ownership is incomplete/uncertain and must stay non-PASS."""


def _terminal_error_status(error):
    if isinstance(error, RecoveryRequiredError):
        return "RECOVERY_REQUIRED", 3
    if isinstance(error, ProbeFailure):
        return "FAIL", 1
    return "BLOCKED", 2


def _close_fd_preserving_active_error(fd):
    """Close once; a cleanup error must not replace an active first failure."""
    had_active_error = sys.exc_info()[0] is not None
    try:
        os.close(fd)
    except OSError:
        if not had_active_error:
            raise


def _unlink_path_preserving_active_error(path):
    """Best-effort temporary cleanup without masking an active first failure."""
    had_active_error = sys.exc_info()[0] is not None
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
    except OSError:
        if not had_active_error:
            raise


def _run(args, timeout=15, check=True, cwd=None, env=None):
    try:
        result = subprocess.run(
            [str(arg) for arg in args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProbeError(f"command failed to run: {args[0]}: {exc}") from exc
    if check and result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ProbeError(f"{args[0]} failed ({result.returncode}): {detail}")
    return result


def swap_signature_valid(header, page_size=PAGE_BYTES):
    return (
        isinstance(header, bytes)
        and len(header) == PAGE_BYTES
        and page_size == PAGE_BYTES
        and header[page_size - len(SWAP_SIGNATURE):page_size] == SWAP_SIGNATURE
    )


def parse_swap_rows(contents):
    lines = contents.splitlines()
    if not lines or lines[0].split() != [
        "Filename", "Type", "Size", "Used", "Priority"
    ]:
        raise ProbeError("cannot parse /proc/swaps header")
    rows = []
    for line in lines[1:]:
        fields = line.split()
        if len(fields) != 5:
            raise ProbeError("cannot parse /proc/swaps row")
        path, kind, size_text, used_text, priority_text = fields
        try:
            size_kib = int(size_text)
            used_kib = int(used_text)
            priority = int(priority_text)
        except ValueError as exc:
            raise ProbeError("invalid numeric /proc/swaps field") from exc
        if size_kib <= 0 or used_kib < 0:
            raise ProbeError("invalid negative or empty /proc/swaps capacity")
        rows.append({
            "path": path,
            "kind": kind,
            "size_kib": size_kib,
            "used_kib": used_kib,
            "priority": priority,
        })
    return rows


def require_development_formatter_inventory_clear():
    """Fail before any card work the formatter would reject later anyway."""
    try:
        contents = Path("/proc/swaps").read_text(encoding="utf-8")
    except OSError as exc:
        raise ProbeError(
            "phase=preflight operation=formatter_inventory "
            "expected=readable_complete_table "
            f"observed=errno_{exc.errno} header_mutation=not_attempted"
        ) from exc
    except UnicodeError as exc:
        raise ProbeError(
            "phase=preflight operation=formatter_inventory "
            "expected=readable_complete_table observed=invalid_encoding "
            "header_mutation=not_attempted"
        ) from exc
    try:
        rows = parse_swap_rows(contents)
    except ProbeError as exc:
        raise ProbeError(
            "phase=preflight operation=formatter_inventory "
            f"expected=complete_table observed=malformed ({exc}) "
            "header_mutation=not_attempted"
        ) from exc
    if rows:
        raise ProbeError(
            "phase=preflight operation=formatter_inventory "
            "expected=complete_zero_rows observed=active_rows "
            f"count={len(rows)} header_mutation=not_attempted"
        )


def block_identity(path):
    try:
        info = os.stat(path)
    except OSError as exc:
        raise ProbeError(
            f"selected_block_stat expected=statable observed=errno_{exc.errno}"
        ) from exc
    if not stat.S_ISBLK(info.st_mode):
        raise ProbeError("selected path is not a block device")
    return os.major(info.st_rdev), os.minor(info.st_rdev)


def _mountinfo_has_device(major, minor):
    expected = f"{major}:{minor}"
    try:
        lines = Path("/proc/self/mountinfo").read_text().splitlines()
    except OSError as exc:
        raise ProbeError(f"cannot read mount inventory: {exc}") from exc
    return any(len(fields := line.split()) >= 3 and fields[2] == expected
               for line in lines)


def _require_root_not_on_target(major, minor, *, allow_shared_parent=False):
    source = _run([
        "findmnt", "--raw", "--noheadings", "--evaluate",
        "--output", "SOURCE", "--target", "/",
    ]).stdout.strip()
    if not source:
        raise ProbeError("cannot identify the root filesystem block source")
    result = _run([
        "lsblk", "--noheadings", "--raw", "--inverse",
        "--output", "MAJ:MIN", source,
    ])
    identities = {line.strip() for line in result.stdout.splitlines()
                  if line.strip()}
    if f"{major}:{minor}" in identities:
        raise ProbeError("selected partition contains or backs the root filesystem")
    # A different partition on the root disk is not dedicated development
    # media. Apply this inside the root-owned writer too, not just in the
    # unprivileged algorithm selector, before opening recovery or swapping off.
    shared_parent = _physical_parent_identity(major, minor) in identities
    if shared_parent and not allow_shared_parent:
        raise ProbeError(
            "selected swap partition shares the root filesystem physical parent")
    return shared_parent


def _verify_open_block_device(fd, target):
    """Bind block I/O to the opened FD, never just a prior pathname."""
    try:
        info = os.fstat(fd)
        if not stat.S_ISBLK(info.st_mode) or (
                os.major(info.st_rdev), os.minor(info.st_rdev)) != (
                target["major"], target["minor"]):
            raise ProbeError("opened partition has a different major:minor")
        size = struct.unpack("=Q", fcntl.ioctl(
            fd, BLKGETSIZE64, bytes(8)))[0]
    except OSError as exc:
        raise ProbeError("cannot verify opened partition geometry") from exc
    if size != target["size_bytes"]:
        raise ProbeError("opened partition geometry differs from reviewed size")


def _read_exact_block0(fd):
    """Read the bounded 4 KiB header even if pread returns a short fragment."""
    header = bytearray(PAGE_BYTES)
    offset = 0
    while offset < PAGE_BYTES:
        try:
            fragment = os.pread(fd, PAGE_BYTES - offset, offset)
        except OSError as exc:
            raise ProbeError(
                f"operation=header_read offset={offset} original_errno={exc.errno} "
                "safe_next_step=inspect_saved_header_read_only") from exc
        if not fragment or len(fragment) > PAGE_BYTES - offset:
            raise ProbeError(
                f"operation=header_read offset={offset} expected=4096_bytes "
                "observed=short_or_invalid_read "
                "safe_next_step=inspect_saved_header_read_only")
        header[offset:offset + len(fragment)] = fragment
        offset += len(fragment)
    return bytes(header)


def _read_block0(device, target):
    try:
        fd = os.open(device, os.O_RDONLY | os.O_CLOEXEC | os.O_NOCTTY)
    except OSError as exc:
        raise ProbeError(f"cannot open selected block device for reading: {exc}") from exc
    try:
        _verify_open_block_device(fd, target)
        return _read_exact_block0(fd)
    finally:
        # A secondary close error must not hide the first identity/I/O fault.
        _close_fd_preserving_active_error(fd)


def swapz_header_valid(header, size_bytes):\n    """Recognize only a legacy pre-migration SWZ recovery header.\n\n    This parser exists solely for historical interrupted journals. It never\n    authorizes a new raw-partition write or defines a current backing format.\n    """
    return (
        len(header) == PAGE_BYTES
        and header[:8] == SWAPZ_HEADER_MAGIC
        and struct.unpack_from("<IIQ", header, 8) ==
        (SWAPZ_HEADER_VERSION, PAGE_BYTES, size_bytes)
        and any(header[24:40])
        and not any(header[40:])
    )


def _kernel_partition_table_uuid(device):
    """Read the kernel partition identity when udev omits PARTUUID."""
    major, minor = block_identity(device)
    descriptor = None
    try:
        descriptor = os.open(
            f"/sys/dev/block/{major}:{minor}/uevent",
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ProbeError("kernel partition identity is not a sysfs file")
        content = os.read(descriptor, 4097)
        if len(content) > 4096:
            raise ProbeError("kernel partition identity exceeds the fixed bound")
        fields = {}
        for line in content.decode("ascii").splitlines():
            key, separator, value = line.partition("=")
            if not separator or not key or key in fields:
                raise ProbeError("kernel partition identity is malformed")
            fields[key] = value
        if (fields.get("MAJOR") != str(major) or
                fields.get("MINOR") != str(minor) or
                fields.get("DEVTYPE") != "partition" or
                not fields.get("PARTN", "").isdigit() or
                int(fields["PARTN"]) <= 0):
            raise ProbeError(
                "kernel partition identity does not bind the selected device")
        return fields.get("PARTUUID")
    except (OSError, UnicodeError, ValueError) as exc:
        raise ProbeError("kernel partition identity cannot be read") from exc
    finally:
        if descriptor is not None:
            _close_fd_preserving_active_error(descriptor)


def _partition_identity(device):
    try:
        result = json.loads(_run([
            "lsblk", "--json", "--bytes", "--nodeps",
            "--output", "TYPE,PARTUUID,SIZE", device,
        ]).stdout)
        rows = result.get("blockdevices", [])
        if len(rows) != 1 or rows[0].get("type") != "part":
            raise ProbeError("cannot identify exactly one partition")
        row = rows[0]
        partuuid = row.get("partuuid")
        # lsblk can lose the udev-backed PARTUUID while the swap/SWZ
        # signature changes. For a missing field only, use the kernel
        # partition-table identity, still requiring the exact by-partuuid
        # block alias below. Never override an explicit lsblk value.
        if partuuid is None or partuuid == "":
            partuuid = _kernel_partition_table_uuid(device)
        normalized_partuuid = (
            partuuid.lower() if isinstance(partuuid, str) else None)
        if (
                normalized_partuuid is None or
                not 8 <= len(normalized_partuuid) <= 64 or
                not re.fullmatch(
                    r"[0-9a-f]+(?:-[0-9a-f]+)*", normalized_partuuid) or
                sum(ch != "-" for ch in normalized_partuuid) < 8):
            raise ProbeError("partition lacks a stable PARTUUID")
        size = row.get("size")
        if type(size) is not int or size <= 0:
            raise ProbeError("partition lacks a valid size")
        # Filesystem UUID links disappear when the original swap header is
        # replaced. The partition-table UUID must survive that transition.
        by_partuuid = Path("/dev/disk/by-partuuid") / normalized_partuuid
        expected_device_identity = block_identity(device)
        linked_device_identity = block_identity(by_partuuid)
        if linked_device_identity != expected_device_identity:
            raise ProbeError(
                "partuuid_link_major_minor "
                f"expected={expected_device_identity[0]}:{expected_device_identity[1]} "
                f"observed={linked_device_identity[0]}:{linked_device_identity[1]}")
        return normalized_partuuid, size
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ProbeError("cannot verify stable partition identity") from exc


def _trusted_host_identity_record(path, byte_limit, pattern):
    """Match the official reporter's bounded, stable, root-owned byte input."""
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_CLOEXEC |
                           os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as source:
        before = os.fstat(source.fileno())
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or
                before.st_nlink != 1 or (before.st_mode & 0o022)):
            raise ValueError("untrusted host identity metadata")
        record = source.read(byte_limit)
        after = os.fstat(source.fileno())
        stable_fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid",
                         "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(after, field)
               for field in stable_fields):
            raise ValueError("host identity changed during read")
    if len(record) == byte_limit:
        raise ValueError("oversized host identity record")
    if record.endswith(b"\n"):
        record = record[:-1]
    if (re.fullmatch(pattern, record) is None or
            not any(byte not in (ord("0"), ord("-")) for byte in record)):
        raise ValueError("invalid host identity record")
    return record.lower()


def live_host_identity():
    """Mirror production's trusted DMI UUID + machine-ID digest bytes."""
    try:
        product_uuid = _trusted_host_identity_record(
            "/sys/class/dmi/id/product_uuid", 40,
            rb"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            rb"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
        machine_id = _trusted_host_identity_record(
            "/etc/machine-id", 64, rb"[0-9a-fA-F]{32}")
        return {
            # The importer requires the existing JSON schema label.
            "schema": "swapz-host-v1",
            "architecture": platform.machine(),
            "id_sha256": hashlib.sha256(
                b"swapz-host-v2\0" + product_uuid + machine_id).hexdigest(),
        }
    except (OSError, ValueError):
        # Raw hardware/installation identifiers must never enter diagnostics.
        raise ProbeError("cannot identify the current host for physical smoke") from None

def _require_physical_host(*, allow_virtual=False):
    """Reject virtual hosts unless a development-only VM lane was requested."""
    detector = shutil.which("systemd-detect-virt")
    if not detector:
        raise ProbeError("systemd-detect-virt is required to verify a physical host")
    virtual_machine = False
    for mode in ("--vm", "--container"):
        result = _run([detector, mode], check=False)
        detected = result.stdout.strip()
        if result.returncode == 0:
            if mode == "--vm" and allow_virtual and re.fullmatch(
                    r"[A-Za-z0-9_.-]{1,32}", detected):
                virtual_machine = True
                continue
            raise ProbeError(
                f"physical swap smoke is not allowed in a {mode[2:]}: "
                f"{detected or 'virtualized environment'}")
        if result.returncode != 1 or detected not in {"", "none"}:
            raise ProbeError(
                f"cannot establish a physical host with {mode}: "
                f"{_bounded_text(result.stderr or detected)}")
    if allow_virtual and not virtual_machine:
        raise ProbeError("virtual-only development requires a verified VM")
    return virtual_machine


def _physical_parent_identity(major, minor):
    """Prove one sysfs partition-to-physical-disk parent, never a DM fallback."""
    try:
        partition = Path(f"/sys/dev/block/{major}:{minor}").resolve(strict=True)
        parent = partition.parent
        parent_identity = (parent / "dev").read_text().strip()
        if not re.fullmatch(r"[0-9]+:[0-9]+", parent_identity):
            raise ProbeError(
                "parent_major_minor expected=number:number observed=malformed")
        if not (partition / "partition").is_file():
            raise ProbeError(
                "parent_topology expected=one physical disk "
                "observed=missing_partition_marker")
        if Path(f"/sys/dev/block/{parent_identity}").resolve(
                strict=True) != parent:
            raise ProbeError(
                "parent_topology expected=one physical disk "
                "observed=parent_link_mismatch")
        if not (parent / "device").exists():
            raise ProbeError(
                "parent_topology expected=one physical disk "
                "observed=missing_parent_device")
        if VIRTUAL_BLOCK_PARENT_RE.fullmatch(parent.name):
            raise ProbeError(
                "parent_topology expected=one physical disk "
                f"observed=virtual_parent_{parent.name!r}")
        return parent_identity
    except ProbeError:
        raise
    except (OSError, RuntimeError) as exc:
        raise ProbeError(
            "parent_topology expected=one verifiable physical disk "
            f"observed=unreadable_sysfs errno={getattr(exc, 'errno', None)!r}"
        ) from exc


def _require_matching_swap_uuid(device_arg, observed_uuid):
    """A stale by-uuid alias must not approve another swap signature."""
    selected_uuid = Path(device_arg).name
    if not isinstance(observed_uuid, str) or (
            selected_uuid.lower() != observed_uuid.lower()):
        raise ProbeError(
            f"swap_uuid expected={selected_uuid!r} observed={observed_uuid!r}")


def _verify_target_identity(target):
    observed_identity = block_identity(target["device"])
    expected_identity = (target["major"], target["minor"])
    if observed_identity != expected_identity:
        raise ProbeError(
            "selected block identity changed during the operation: "
            f"selected_major_minor expected={target['major']}:{target['minor']} "
            f"observed={observed_identity[0]}:{observed_identity[1]}")
    try:
        size = int(_run([
            "blockdev", "--getsize64", target["device"],
        ]).stdout.strip())
    except ValueError as exc:
        raise ProbeError("cannot verify selected partition size") from exc
    if size != target["size_bytes"]:
        raise ProbeError(
            "selected partition size changed during the operation: "
            f"size_bytes expected={target['size_bytes']} observed={size}")
    partuuid, part_size = _partition_identity(target["device"])
    if (partuuid != target["partuuid"] or part_size != target["size_bytes"]):
        raise ProbeError(
            f"persistent_identity expected=({target['partuuid']}, "
            f"{target['size_bytes']}) observed=({partuuid}, {part_size})")
    parent = _physical_parent_identity(target["major"], target["minor"])
    if parent != target.get("parent_major_minor"):
        raise ProbeError(
            f"parent_major_minor expected={target.get('parent_major_minor')!r} "
            f"observed={parent!r}")
    expected_card_sha = target.get("card_identity_sha256")
    if expected_card_sha is not None:
        observed_card = _campaign_card_identity(target["device"], parent)
        if observed_card["sha256"] != expected_card_sha:
            raise ProbeError(
                "parent_card_identity changed during the operation")
        if (observed_card["model"] != target.get("parent_model") or
                observed_card["transport"] != target.get("parent_transport")):
            raise ProbeError(
                "parent_card_attributes changed during the operation")


def inspect_target(device_arg, confirm_arg, *, allow_used_swap=False,
                   allow_inactive_swap=False, allow_shared_root=False,
                   virtual_device_only=False):
    """Identify the selected partition; dev smoke may preserve inactive swap."""
    if not device_arg or device_arg != confirm_arg:
        raise ProbeError("--device and --confirm-device must match exactly")
    # New trials bind the partition table identity. Accept only the legacy
    # by-UUID selector when processing previously confirmed trial records.
    by_partuuid = device_arg.startswith("/dev/disk/by-partuuid/")
    by_swap_uuid = device_arg.startswith("/dev/disk/by-uuid/")
    if not (by_partuuid or by_swap_uuid) or (
            device_arg != (
                "/dev/disk/by-partuuid/" if by_partuuid else
                "/dev/disk/by-uuid/") + Path(device_arg).name):
        raise ProbeError("select the partition through /dev/disk/by-partuuid/ "
                         "(legacy by-uuid remains supported)")
    try:
        device = str(Path(device_arg).resolve(strict=True))
    except OSError as exc:
        raise ProbeError(f"cannot resolve selected device path: {exc}") from exc
    major, minor = block_identity(device)
    sys_entry = Path(f"/sys/dev/block/{major}:{minor}").resolve()
    if not (sys_entry / "partition").is_file():
        raise ProbeError("selected block device is not a partition")
    parent_major_minor = _physical_parent_identity(major, minor)
    if any((sys_entry / "holders").iterdir()):
        raise ProbeError("selected partition has active block-device holders")
    if _mountinfo_has_device(major, minor):
        raise ProbeError("selected partition is mounted")
    root_same_physical_parent = _require_root_not_on_target(
        major, minor, allow_shared_parent=allow_shared_root)

    lsblk = json.loads(_run([
        "lsblk", "--json", "--bytes", "--nodeps",
        "--output", "TYPE,FSTYPE,UUID,SIZE", device,
    ]).stdout)
    devices = lsblk.get("blockdevices", [])
    if len(devices) != 1:
        raise ProbeError("cannot identify exactly one selected partition")
    row = devices[0]
    size_bytes = row.get("size")
    if row.get("type") != "part" or row.get("fstype") != "swap":
        raise ProbeError("selected partition is not identified as Linux swap")
    if type(size_bytes) is not int or size_bytes <= 0:
        raise ProbeError("selected swap partition lacks stable identity or size")
    partuuid, partition_size = _partition_identity(device)
    if by_partuuid and Path(device_arg).name.lower() != partuuid:
        raise ProbeError("PARTUUID selector does not match the selected partition")
    if by_swap_uuid:
        _require_matching_swap_uuid(device_arg, row.get("uuid"))
    if partition_size != size_bytes:
        raise ProbeError("selected partition inventory has inconsistent size")
    if size_bytes < 3 * 1024 * 1024 + PAGE_BYTES:
        raise ProbeError("selected swap partition is too small for swapz")

    active = _active_swap_for(major, minor)
    if active is None and not allow_inactive_swap:
        raise ProbeError("selected partition must be exactly one active system swap")
    if active is not None and active["size_kib"] > size_bytes // 1024:
        raise ProbeError(
            "selected swap capacity exceeds the selected partition geometry")
    if active is not None and not LINUX_SWAP_PRIORITY_MIN <= active["priority"] <= \
            LINUX_SWAP_PRIORITY_MAX:
        raise ProbeError(
            "selected swap priority cannot be restored exactly by this helper")
    if active is not None and not 0 <= active["used_kib"] <= active["size_kib"]:
        raise ProbeError("selected swap usage is outside its capacity")
    if active is not None and active["used_kib"] != 0 and not allow_used_swap:
        raise ProbeError("selected swap partition is in use; require zero used KiB")
    header = _read_block0(device, {
        "major": major, "minor": minor, "size_bytes": size_bytes,
    })
    if not swap_signature_valid(header, os.sysconf("SC_PAGE_SIZE")):
        raise ProbeError("selected partition does not have a supported SWAPSPACE2 header")
    card_identity = _campaign_card_identity(device, parent_major_minor)
    if not virtual_device_only and (
            card_identity["transport"] != "usb" or
            card_identity["parent_removable"] is not True):
        raise ProbeError(
            "physical_parent expected=removable_usb "
            f"observed=transport_{card_identity['transport']!r},"
            f"removable_{card_identity['parent_removable']!r}")
    return {
        "device": device,
        "major": major,
        "minor": minor,
        "parent_major_minor": parent_major_minor,
        "parent_model": card_identity["model"],
        "parent_transport": card_identity["transport"],
        "parent_size_bytes": card_identity["parent_size_bytes"],
        "parent_removable": card_identity["parent_removable"],
        "card_identity_sha256": card_identity["sha256"],
        "virtual_device_only": virtual_device_only,
        "root_same_physical_parent": root_same_physical_parent,
        "size_bytes": size_bytes,
        "uuid": row.get("uuid"),
        "partuuid": partuuid,
        "header": header,
        "swap_was_active": active is not None,
        "swap_path": active["path"] if active is not None else None,
        "swap_priority": active["priority"] if active is not None else None,
        "swap_size_kib": active["size_kib"] if active is not None else None,
        "swap_used_kib": active["used_kib"] if active is not None else None,
    }


def _git_result(*args, check=True, timeout=20):
    """Run local Git as the sudo operator so ownership/config stay consistent."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=8")
    git_args = ["git", *args]
    sudo_user = os.environ.get("SUDO_USER")
    if os.geteuid() == 0 and sudo_user and sudo_user != "root":
        runuser = shutil.which("runuser")
        if not runuser:
            raise ProbeError("runuser is required to verify Git state as the operator")
        git_args = [runuser, "--user", sudo_user, "--", *git_args]
    return _run(git_args, timeout=timeout, check=check, cwd=ROOT, env=env)


def _git(*args, check=True):
    return _git_result(*args, check=check).stdout.strip()


def _remote_main_sha():
    """Query the canonical public GitHub repository without checkout Git config."""
    # cwd=/ prevents local .git/config and worktree URL rewrites from affecting
    # this query; disable system/global/injected Git configuration as well.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("GIT_CONFIG_") and key not in {
               "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR",
               "GIT_CEILING_DIRECTORIES", "GIT_INDEX_FILE",
           }}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_TERMINAL_PROMPT"] = "0"
    git_args = ["git", "ls-remote", CANONICAL_MAIN_REMOTE, "refs/heads/main"]
    sudo_user = os.environ.get("SUDO_USER")
    if os.geteuid() == 0 and sudo_user and sudo_user != "root":
        runuser = shutil.which("runuser")
        if not runuser:
            raise ProbeError("runuser is required to verify canonical main as operator")
        git_args = [runuser, "--user", sudo_user, "--", *git_args]
    result = _run(git_args, timeout=20, check=False, cwd="/", env=env)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ProbeError(f"cannot verify canonical main: {detail}")
    rows = [line.split() for line in result.stdout.splitlines()]
    if len(rows) != 1 or len(rows[0]) != 2 or \
            rows[0][1] != "refs/heads/main" or \
            not re.fullmatch(r"[0-9a-f]{40}", rows[0][0]):
        raise ProbeError("canonical repository did not return exactly one main ref")
    return rows[0][0]


def _has_five_passing_stages(report):
    """Require five executed owner stages, never just an overall PASS."""
    stages = report.get("stages")
    return (isinstance(stages, list) and
            len(stages) == len(QUALIFICATION_STAGE_NAMES) and
            all(isinstance(stage, dict) and stage.get("name") == name and
                stage.get("status") == "PASS" and
                type(stage.get("exit_code")) is int and
                stage["exit_code"] == 0
                for stage, name in zip(stages, QUALIFICATION_STAGE_NAMES)))


def _report_artifact_digests(report):
    record = report.get("qualified_artifacts")
    if not isinstance(record, dict) or record.get("status") != "AVAILABLE":
        return None
    digests = {}
    for key, _, _ in PHYSICAL_ARTIFACTS:
        value = record.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            return None
        digests[key] = value
    return digests


def _report_is_owner_pass(report, host_identity):
    return (
        isinstance(report, dict)
        and report.get("overall") == "PASS"
        and report.get("tested_commit_sha") == report.get("source_sha")
        and isinstance(report.get("source_sha"), str)
        and re.fullmatch(r"[0-9a-f]{40}", report["source_sha"])
        and _has_five_passing_stages(report)
        and report.get("host_identity") == host_identity
        and host_identity.get("architecture") == "x86_64"
        and _report_artifact_digests(report) is not None
    )


def _check_post_qualification_paths(source, head):
    """Allow only non-binary physical policy/report changes after qualification."""
    ancestor = _git_result(
        "merge-base", "--is-ancestor", source, head, check=False)
    if ancestor.returncode:
        raise ProbeError("qualified source is not an ancestor of main")
    commits = _git("rev-list", "--reverse", "--first-parent",
                   f"{source}..{head}").splitlines()
    for commit in commits:
        parents = _git("rev-list", "--parents", "-n", "1", commit).split()
        if len(parents) != 2:
            raise ProbeError(
                "merge commits after qualified source block physical admission")
        names = _git("diff-tree", "--no-commit-id", "--name-only", "-r",
                     parents[1], commit).splitlines()
        unexpected = sorted(set(names) - POST_QUALIFICATION_PATHS)
        if unexpected:
            raise ProbeError(
                "post-qualification change can affect qualified artifacts: "
                + ", ".join(unexpected))


def _distinct_report_digest(report):
    encoded = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _development_code_source_sha(head):
    """Bind built artifacts to code, not generated report-only main commits.

    The development physical gate still requires local HEAD, tracking main
    and canonical main to match exactly, including immediately before writes.
    """
    source = _git("log", "-1", "--format=%H", head, "--", ".",
                  ":(exclude)test_results.json")
    if not re.fullmatch(r"[0-9a-f]{40}", source):
        raise ProbeError("cannot identify development code source revision")
    if source == head:
        return source
    if _git_result("merge-base", "--is-ancestor", source, head,
                   check=False).returncode:
        raise ProbeError("development code source is not an ancestor of main")
    commits = _git("rev-list", "--reverse", "--first-parent",
                   f"{source}..{head}").splitlines()
    if not commits or len(commits) > 1000:
        raise ProbeError("development report-only history is invalid or excessive")
    for commit in commits:
        parents = _git("rev-list", "--parents", "-n", "1", commit).split()
        if len(parents) != 2 or parents[0] != commit:
            raise ProbeError("development report-only history contains a merge")
        paths = _git("diff-tree", "--no-commit-id", "--name-only", "-r",
                     parents[1], commit).splitlines()
        subject = _git("show", "-s", "--format=%s", commit)
        if paths != ["test_results.json"]:
            raise ProbeError("development HEAD contains a non-report-only change")
        if subject == f"test: latest run for {source[:12]} [skip ci]":
            continue
        # An older host may publish its old-source result after new code
        # reaches main. This is report history, never executable source or
        # qualification of the new revision. Authenticate the publication.
        publication = re.fullmatch(
            r"test: latest run for ([0-9a-f]{12}) \[skip ci\]", subject)
        if publication is None:
            raise ProbeError("development HEAD contains a non-report-only change")
        resolved = _git_result(
            "rev-parse", f"{publication.group(1)}^{{commit}}", check=False)
        reported_source = resolved.stdout.strip() if not resolved.returncode else ""
        if (not re.fullmatch(r"[0-9a-f]{40}", reported_source) or
                _git_result("merge-base", "--is-ancestor",
                            reported_source, source, check=False).returncode):
            raise ProbeError("development HEAD contains a non-report-only change")

        message = _git("show", "-s", "--format=%B", commit)
        report_commit = commit
        if message == subject + "\n\nswapz-canonical-restore: true":
            # The publisher archives one old report, then restores the
            # previously canonical tree. Validate both commits as a pair.
            if (_git("show", "-s", "--format=%s", parents[1]) != subject or
                    _git("rev-parse", f"{commit}^{{tree}}") !=
                    _git("rev-parse", f"{commit}~2^{{tree}}")):
                raise ProbeError("development HEAD contains a non-report-only change")
            report_commit = parents[1]
        elif message != subject:
            raise ProbeError("development HEAD contains a non-report-only change")
        try:
            report = _load_unique_json(
                _git("show", f"{report_commit}:test_results.json"))
        except ValueError as exc:
            raise ProbeError(
                "development HEAD contains a non-report-only change") from exc
        if (not isinstance(report, dict) or
                report.get("schema") != "swapz-test-results-v1" or
                report.get("source_sha") != reported_source or
                report.get("tested_commit_sha") != reported_source):
            raise ProbeError("development HEAD contains a non-report-only change")
    return source


def _require_development_canonical_main(local_head, code_source_sha):
    """Permit only proven report-only canonical-main advances.

    Do not change main, origin/main, or the worktree. Fetch canonical Git
    objects and authenticate every intervening commit before admitting the
    unchanged code source. A malformed, changed, or racing remote fails closed.
    """
    canonical_head = _remote_main_sha()
    if canonical_head == local_head:
        return
    if not re.fullmatch(r"[0-9a-f]{40}", canonical_head):
        raise ProbeError("canonical main identity is malformed")
    fetched = _git_result(
        "-c", "gc.auto=0", "-c", "maintenance.auto=false",
        "fetch", "--quiet", "--no-write-fetch-head", "--no-tags",
        "--no-recurse-submodules", CANONICAL_MAIN_REMOTE, "refs/heads/main",
        timeout=60, check=False)
    if fetched.returncode:
        raise ProbeError("cannot verify canonical main report-only advancement")
    if _remote_main_sha() != canonical_head:
        raise ProbeError("canonical main advanced during source verification")
    if (_git("rev-parse", "HEAD") != local_head or
            _git("rev-parse", "origin/main") != local_head):
        raise ProbeError("local main or origin/main moved during physical admission")
    if _git("cat-file", "-t", canonical_head) != "commit":
        raise ProbeError("canonical main is not a fetched commit")
    if _git_result("merge-base", "--is-ancestor", local_head,
                   canonical_head, check=False).returncode:
        raise ProbeError("canonical main is not a descendant of local main")
    if _development_code_source_sha(canonical_head) != code_source_sha:
        raise ProbeError("canonical main contains changed source after qualification")


def current_source_evidence():
    if platform.machine() != "x86_64":
        raise ProbeError("physical swap smoke is currently limited to x86_64")
    _require_physical_host()
    branch = _git("symbolic-ref", "--quiet", "--short", "HEAD")
    if branch != "main":
        raise ProbeError("physical smoke is restricted to main")
    if _git("status", "--porcelain"):
        raise ProbeError("worktree changes block physical smoke")
    head = _git("rev-parse", "HEAD")
    if head != _git("rev-parse", "origin/main"):
        raise ProbeError("local main must be synchronized with origin/main")
    if _remote_main_sha() != head:
        raise ProbeError("origin/main is not synchronized with local main")
    try:
        report = json.loads((ROOT / "test_results.json").read_text())
    except (OSError, ValueError) as exc:
        raise ProbeError(f"cannot read the current test report: {exc}") from exc
    if not isinstance(report, dict):
        raise ProbeError("current test_results.json must be an object")
    source = report.get("source_sha")
    if report.get("overall") != "PASS" or \
            report.get("tested_commit_sha") != source or \
            not isinstance(source, str) or \
            not re.fullmatch(r"[0-9a-f]{40}", source) or \
            not _has_five_passing_stages(report):
        raise ProbeError("current test_results.json is not an exact-source five-stage PASS")
    if _report_artifact_digests(report) is None:
        raise ProbeError(
            "current test_results.json lacks qualified artifact digests")
    host_identity = live_host_identity()
    if not _report_is_owner_pass(report, host_identity):
        raise ProbeError(
            "current report is not a five-stage PASS from this x86_64 host")
    _check_post_qualification_paths(source, head)

    artifact_digests = _report_artifact_digests(report)
    distinct_reports = set()
    latest_source_reports = set()
    prior_matching_reports = set()
    # test_results.json is overwriteable and shared by hosts. Read each
    # first-parent publication as committed, count distinct owner reports with
    # the live host identity, and accept earlier production sources only when
    # their three final artifact bytes equal the latest qualification.
    for commit in _git("log", "--first-parent", "--format=%H", head,
                       "--", "test_results.json").splitlines():
        result = _git_result(
            "show", f"{commit}:test_results.json", timeout=10, check=False)
        if result.returncode:
            continue
        try:
            historical = json.loads(result.stdout)
        except ValueError:
            continue
        if not _report_is_owner_pass(historical, host_identity):
            continue
        historical_source = historical["source_sha"]
        if _git_result("merge-base", "--is-ancestor", historical_source,
                       source, check=False).returncode:
            continue
        historical_digests = _report_artifact_digests(historical)
        if historical_digests != artifact_digests:
            continue
        report_digest = _distinct_report_digest(historical)
        if historical_source == source:
            latest_source_reports.add(report_digest)
        else:
            prior_matching_reports.add(report_digest)
        distinct_reports.add(report_digest)
    if not latest_source_reports:
        raise ProbeError(
            "no complete owner x86_64 PASS report for the latest qualified source")
    helper_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return {
        "source_sha": source,
        "host_identity": host_identity,
        "artifact_digests": artifact_digests,
        "pass_reports": len(distinct_reports),
        "latest_source_reports": len(latest_source_reports),
        "prior_matching_reports": len(prior_matching_reports),
        "helper_sha256": helper_sha256,
        "head": head,
    }


def _read_fast_test_development_evidence(path, expected_uid, head, nonce):
    descriptor = -1
    try:
        descriptor = os.open(
            path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != expected_uid or
                stat.S_IMODE(before.st_mode) != 0o600 or
                not 1 <= before.st_size <= 65536):
            raise ProbeError(
                "development_evidence expected=user_owned_private_regular_file "
                "observed=invalid_metadata")
        chunks = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                raise ProbeError("development_evidence was truncated while reading")
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                before.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
                after.st_ctime_ns):
            raise ProbeError("development_evidence changed while reading")
        try:
            record = _load_unique_json(b"".join(chunks))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ProbeError(
                "development_evidence expected=unique_valid_json "
                "observed=malformed") from exc
    except OSError as exc:
        raise ProbeError(
            "development_evidence expected=readable_no_follow_file "
            f"observed=errno_{exc.errno}") from exc
    finally:
        if descriptor >= 0:
            _close_fd_preserving_active_error(descriptor)
    if (not isinstance(record, dict) or
            record.get("schema") != "swapz-fast-test-development-evidence-v1" or
            record.get("head") != head or record.get("dirty") is not False or
            record.get("nonce") != nonce or
            record.get("native_status") != "PASS"):
        raise ProbeError(
            "development_evidence expected=current_clean_main_native_PASS "
            "observed=mismatch")
    preflight = record.get("loaded_preflight")
    if (record.get("fast_test_status") == "PASS" and
            isinstance(preflight, dict) and preflight.get("status") == "PASS" and
            preflight.get("check") == "complete"):
        outcome = "FAST_TEST_PASS"
    elif (record.get("fast_test_status") == "BLOCKED" and
          isinstance(preflight, dict) and preflight.get("status") == "BLOCKED" and
          preflight.get("check") == "unclaimed_null_blk"):
        # Do not remove or reuse the ambiguous null_blk instance. The physical
        # smoke has its own stricter mapper/module and target-identity checks.
        outcome = "LOADED_PREFLIGHT_BLOCKED_UNCLAIMED_NULL_BLK"
    else:
        raise ProbeError(
            "development_evidence expected=fast_test_PASS_or_exact_"
            "unclaimed_null_blk_block observed=other_failure")
    return {"outcome": outcome, "preflight": preflight,
            "native_status": record["native_status"],
            "fast_test_status": record["fast_test_status"]}


def _read_algorithm_ram_development_evidence(
        path, expected_uid, head, source_sha, nonce):
    """Read the exact completed make-test RAM record without rerunning fast_test."""
    expected_path = ROOT / "build/tests/algorithm-ram-evidence.json"
    if Path(path) != expected_path:
        raise ProbeError("algorithm RAM evidence path is not canonical")
    descriptor = -1
    try:
        descriptor = os.open(
            expected_path, os.O_RDONLY | os.O_NOFOLLOW |
            os.O_NONBLOCK | os.O_CLOEXEC)
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != expected_uid or
                stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1 or
                not 1 <= before.st_size <= 65536):
            raise ProbeError("algorithm RAM evidence metadata is invalid")
        payload = bytearray()
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                raise ProbeError("algorithm RAM evidence was truncated")
            payload.extend(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                before.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
                after.st_ctime_ns):
            raise ProbeError("algorithm RAM evidence changed while reading")
        record = _load_unique_json(bytes(payload))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        if isinstance(exc, ProbeError):
            raise
        raise ProbeError("algorithm RAM evidence is unreadable") from exc
    finally:
        if descriptor >= 0:
            _close_fd_preserving_active_error(descriptor)

    stages = record.get("stages") if isinstance(record, dict) else None
    expected_stages = [
        {"name": name, "status": "PASS", "exit_code": 0}
        for name in QUALIFICATION_STAGE_NAMES
    ]
    artifacts = record.get("artifact_sha256") if isinstance(record, dict) else None
    if (record.get("schema") != "swapz-algorithm-ram-development-evidence-v1" or
            record.get("head") != head or record.get("source_sha") != source_sha or
            record.get("nonce") != nonce or stages != expected_stages or
            not isinstance(artifacts, dict) or
            set(artifacts) != {key for key, _, _ in PHYSICAL_ARTIFACTS} or
            any(not isinstance(value, str) or
                re.fullmatch(r"[0-9a-f]{64}", value) is None
                for value in artifacts.values())):
        raise ProbeError("algorithm RAM evidence does not match this qualification")
    return {
        "outcome": "MAKE_TEST_RAM_PASS",
        "source_sha": source_sha,
        "head": head,
        "artifact_digests": artifacts,
    }


def _require_development_linux_abi():
    """Require the tested 64-bit/4KiB Linux block and swap ABI."""
    if platform.system() != "Linux" or platform.machine() not in (
            "x86_64", "aarch64"):
        raise ProbeError("physical development smoke requires Linux x86_64 or aarch64")
    if struct.calcsize("P") != 8 or os.sysconf("SC_PAGE_SIZE") != PAGE_BYTES:
        raise ProbeError(
            "physical development smoke requires 64-bit Linux with 4096-byte pages")


def current_development_evidence(nonce, algorithm_ram_evidence=None,
                                 virtual_device_only=False):
    """Admit current make-test RAM evidence or run the standalone fast_test path."""
    _require_development_linux_abi()
    _require_physical_host(allow_virtual=virtual_device_only)
    if os.geteuid() != 0:
        raise ProbeError("development physical smoke evidence requires root wrapper")
    operator = os.environ.get("SUDO_USER")
    if (not operator or operator == "root" or
            not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,31}", operator)):
        raise ProbeError("development smoke must be invoked through sudo by the checkout owner")
    branch = _git("symbolic-ref", "--quiet", "--short", "HEAD")
    if branch != "main":
        raise ProbeError("physical development smoke is restricted to main")
    if _git("status", "--porcelain"):
        raise ProbeError("worktree changes block physical development smoke")
    head = _git("rev-parse", "HEAD")
    if head != _git("rev-parse", "origin/main"):
        raise ProbeError("local and origin/main must match before development smoke")
    code_source_sha = _development_code_source_sha(head)
    _require_development_canonical_main(head, code_source_sha)
    try:
        repository_uid = os.stat(ROOT, follow_symlinks=False).st_uid
    except OSError as exc:
        raise ProbeError("cannot verify checkout owner for development evidence") from exc
    try:
        import pwd
        operator_uid = pwd.getpwnam(operator).pw_uid
    except (KeyError, ImportError) as exc:
        raise ProbeError("cannot resolve sudo checkout owner") from exc
    if operator_uid != repository_uid:
        raise ProbeError("sudo operator does not own the source checkout")
    nonce = nonce or secrets.token_hex(16)
    if not re.fullmatch(r"[0-9a-f]{32}", nonce):
        raise ProbeError("development admission nonce is malformed")
    if algorithm_ram_evidence is not None:
        development = _read_algorithm_ram_development_evidence(
            algorithm_ram_evidence, operator_uid, head, code_source_sha, nonce)
    else:
        runuser = shutil.which("runuser")
        env = shutil.which("env")
        make = shutil.which("make")
        if not runuser or not env or not make:
            raise ProbeError(
                "runuser, env and make are required for development evidence")
        try:
            result = subprocess.run(
                [runuser, "--user", operator, "--", env,
                 f"SWAPZ_DEVELOPMENT_ADMISSION_NONCE={nonce}", make,
                 "fast_test", "SCENARIOS=fast-mixed", "REPEAT=1",
                 "RESUME=1"],
                cwd=ROOT, check=False, timeout=1200)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ProbeError(
                f"source-bound development test failed to run: {exc}") from exc
        evidence_path = ROOT / "build/tests/fast-test/development-evidence.json"
        development = _read_fast_test_development_evidence(
            evidence_path, operator_uid, head, nonce)
        if result.returncode == 0:
            if development["outcome"] != "FAST_TEST_PASS":
                raise ProbeError(
                    "fast_test returned success without a PASS evidence record")
        elif result.returncode == 2 and development["outcome"] == \
                "LOADED_PREFLIGHT_BLOCKED_UNCLAIMED_NULL_BLK":
            pass
        else:
            raise ProbeError(
                "fast_test result expected=0_or_exact_preflight_exit_2 "
                f"observed={result.returncode}")
    try:
        build_info = (ROOT / "build/source-build-info.h").read_text()
    except OSError as exc:
        raise ProbeError(
            "development build identity expected=readable "
            f"observed=errno_{exc.errno}") from exc
    source_match = re.search(
        r'^#define SWAPZ_BUILD_SOURCE_SHA "([0-9a-f]{40})"$',
        build_info, re.MULTILINE)
    clean_match = re.search(
        r'^#define SWAPZ_BUILD_SOURCE_CLEAN ([01])$', build_info, re.MULTILINE)
    if not source_match or source_match.group(1) != code_source_sha or not clean_match or \
            clean_match.group(1) != "1":
        raise ProbeError("development build artifacts are not clean and bound to current main")
    artifact_digests = _artifact_digests()
    if (algorithm_ram_evidence is not None and
            development.get("artifact_digests") != artifact_digests):
        raise ProbeError(
            "algorithm RAM evidence artifact digests differ from current build")
    _require_development_canonical_main(head, code_source_sha)
    return {
        "source_sha": code_source_sha,
        "head": head,
        "development_only": True,
        "scope": DEVELOPMENT_SCOPE,
        "development_evidence": development,
        "artifact_digests": artifact_digests,
        "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }


def _artifact_paths():
    return {key: (ROOT / relative_path, executable)
            for key, relative_path, executable in PHYSICAL_ARTIFACTS}


def _artifact_digests():
    """Digest the tested build artifacts with stable no-follow descriptors."""
    digests = {}
    for key, (path, executable) in _artifact_paths().items():
        descriptor = -1
        try:
            descriptor = os.open(
                path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size <= 0 or (
                    executable and not before.st_mode & 0o111):
                raise ProbeError(
                    f"physical_artifact.{key} expected=usable_regular_file "
                    "observed=invalid_metadata")
            digest = hashlib.sha256()
            while chunk := os.read(descriptor, 1024 * 1024):
                digest.update(chunk)
            after = os.fstat(descriptor)
            if (before.st_dev, before.st_ino, before.st_size,
                    before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_dev, after.st_ino, after.st_size,
                    after.st_mtime_ns, after.st_ctime_ns):
                raise ProbeError(
                    f"physical_artifact.{key} expected=stable_bytes "
                    "observed=changed_while_hashing")
            digests[key] = digest.hexdigest()
        except OSError as exc:
            raise ProbeError(
                f"physical_artifact.{key} expected=readable_no_follow_file "
                f"observed=errno_{exc.errno}"
            ) from exc
        finally:
            if descriptor >= 0:
                _close_fd_preserving_active_error(descriptor)
    return digests


def _require_shared_root_development_plan(target, evidence):
    """Keep bare-metal shared-root authorization separate from VM-only tests."""
    if target.get("root_same_physical_parent") is not True:
        return
    if target.get("virtual_device_only") is True:
        if evidence.get("virtual_device_only") is not True:
            raise ProbeError("virtual shared-root target lacks VM-only evidence")
        return
    swapzctl = _artifact_paths()["formatter_sha256"][0]
    result = _run([str(swapzctl), "primary", "plan"],
                  timeout=30, check=False)
    if result.returncode not in (0, 2) or len(result.stdout) > 65536:
        raise ProbeError(
            "shared-root authorization plan is unavailable or oversized")
    try:
        plan = _load_unique_json(result.stdout.encode("utf-8"))
    except (UnicodeEncodeError, ValueError) as exc:
        raise ProbeError("shared-root authorization plan is malformed") from exc
    if not isinstance(plan, dict) or plan.get("schema") != "swapz-primary-plan-v1":
        raise ProbeError("shared-root authorization plan has the wrong schema")

    parent_identity = target.get("parent_major_minor")
    if (not isinstance(parent_identity, str) or
            re.fullmatch(r"[0-9]+:[0-9]+", parent_identity) is None):
        raise ProbeError("shared-root target parent identity is unavailable")
    parent_major, parent_minor = map(int, parent_identity.split(":"))

    required_true = (
        "control_build_source_clean",
        "target_config_read",
        "target_device_preflight",
        "original_swap_signature",
        # This bounded development trial keeps ownership state in /run and
        # never rewrites block zero, so persistent-recovery fields from the
        # primary deployment plan are not admission requirements here.
        "target_device_chain_checked",
        "module_mapper_inventory_read",
        "swapz_mapper_absent",
        "mount_inventory_read",
        "target_not_mounted",
        "root_mount_source_chain_checked",
        "root_same_physical_disk_as_target",
        "shared_root_parent_exception_required",
        "swap_inventory_read",
        "target_swap_size_ok",
        "target_swap_zero_used",
        "target_swap_priority_ok",
    )
    if any(plan.get(field) is not True for field in required_true):
        raise ProbeError(
            "shared-root authorization plan did not satisfy every required gate")
    if (plan.get("dm_swapz_module_loaded") is not False or
            plan.get("shared_root_parent_exception_status") != "valid"):
        raise ProbeError("shared-root host authorization is not valid")
    if (plan.get("control_build_source_sha") != evidence.get("source_sha") or
            plan.get("target_partuuid") != target.get("partuuid") or
            plan.get("target_device_major") != target.get("major") or
            plan.get("target_device_minor") != target.get("minor") or
            plan.get("target_device_bytes") != target.get("size_bytes") or
            plan.get("target_physical_parent_major") != parent_major or
            plan.get("target_physical_parent_minor") != parent_minor):
        raise ProbeError(
            "shared-root authorization plan does not bind the selected target")
    fingerprint = plan.get("shared_root_parent_scope_fingerprint")
    if (not isinstance(fingerprint, str) or
            re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None):
        raise ProbeError(
            "shared-root authorization scope fingerprint is unavailable")


def _snapshot_reviewed_artifacts(state_dir, expected_digests):
    """Pin reviewed binary bytes under the root-owned recovery directory.

    Source files are not trusted after review. Every executable/insmod input
    comes from this private snapshot, which is verified before swapoff.
    """
    snapshots = {}
    for key, (source_path, executable) in _artifact_paths().items():
        source_fd = destination_fd = -1
        destination_created = False
        succeeded = False
        destination = Path(state_dir) / source_path.name
        try:
            source_fd = os.open(
                source_path, os.O_RDONLY | os.O_NOFOLLOW |
                os.O_NONBLOCK | os.O_CLOEXEC)
            before = os.fstat(source_fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size <= 0 or (
                    executable and not before.st_mode & 0o111):
                raise ProbeError(f"invalid physical artifact source: {source_path.name}")
            destination_fd = os.open(
                destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                os.O_NOFOLLOW | os.O_CLOEXEC, 0o400)
            destination_created = True
            digest = hashlib.sha256()
            remaining = before.st_size
            while remaining:
                chunk = os.read(source_fd, min(1024 * 1024, remaining))
                if not chunk:
                    raise ProbeError(f"physical artifact truncated: {source_path.name}")
                digest.update(chunk)
                _write_all(destination_fd, chunk)
                remaining -= len(chunk)
            if os.read(source_fd, 1):
                raise ProbeError(f"physical artifact grew during snapshot: {source_path.name}")
            after = os.fstat(source_fd)
            if (before.st_dev, before.st_ino, before.st_size,
                    before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_dev, after.st_ino, after.st_size,
                    after.st_mtime_ns, after.st_ctime_ns):
                raise ProbeError(f"physical artifact changed during snapshot: {source_path.name}")
            if digest.hexdigest() != expected_digests[key]:
                raise ProbeError(f"physical artifact differs from reviewed bytes: {source_path.name}")
            os.fchmod(destination_fd, 0o500 if executable else 0o400)
            os.fsync(destination_fd)
            succeeded = True
            snapshots[key] = destination
        except OSError as exc:
            raise ProbeError(
                f"physical_artifact_snapshot.{key} "
                "expected=readable_source_and_writable_snapshot "
                f"observed=errno_{exc.errno}"
            ) from exc
        finally:
            if destination_fd >= 0:
                _close_fd_preserving_active_error(destination_fd)
            if source_fd >= 0:
                _close_fd_preserving_active_error(source_fd)
            if destination_created and not succeeded:
                _unlink_path_preserving_active_error(destination)
    return snapshots


def _load_unique_json(record_bytes):
    """Safety records must have one unambiguous value per JSON key."""
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(record_bytes, object_pairs_hook=unique_object)


def validate_review(review_path, evidence, target):
    try:
        record_bytes = Path(review_path).read_bytes()
        review = _load_unique_json(record_bytes)
    except (OSError, ValueError) as exc:
        raise ProbeError(f"cannot read verbal safety review: {exc}") from exc
    if not isinstance(review, dict):
        raise ProbeError("verbal safety review must be an object")
    reviewer = review.get("reviewer")
    operator = os.environ.get("SUDO_USER") or os.environ.get("USER") or "root"
    if review.get("approved") is not True or not isinstance(reviewer, str) or \
            review.get("approval_mode") != "verbal" or \
            review.get("approval_text") != VERBAL_APPROVAL_TEXT or \
            reviewer != VERBAL_REVIEWER or \
            (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@+-]{0,127}", reviewer) or
             reviewer.lower() in {"root", operator.lower()}):
        raise ProbeError(
            "review record must contain the exact verbal approval and a separate reviewer")
    run_id = review.get("run_id")
    if review.get("scope") != EXPECTED_SCOPE or \
            review.get("source_sha") != evidence["source_sha"] or \
            review.get("helper_git_sha") != evidence["head"] or \
            review.get("device_major_minor") != \
            f"{target['major']}:{target['minor']}" or \
            review.get("device_partuuid") != target["partuuid"] or \
            type(review.get("device_size_bytes")) is not int or \
            review["device_size_bytes"] != target["size_bytes"] or \
            review.get("original_header_sha256") != hashlib.sha256(
                target["header"]).hexdigest() or \
            review.get("device_uuid_path") != target["device_arg"] or \
            not isinstance(run_id, str) or \
            not re.fullmatch(r"[0-9a-f]{32}", run_id) or \
            review.get("helper_sha256") != hashlib.sha256(
                Path(__file__).read_bytes()).hexdigest() or \
            review.get("helper_sha256") != evidence.get("helper_sha256"):
        raise ProbeError("review record does not match this source, helper and device")
    artifact_digests = evidence.get("artifact_digests")
    if not isinstance(artifact_digests, dict) or any(
           not isinstance(review.get(key), str) or
           not re.fullmatch(r"[0-9a-f]{64}", review[key]) or
           review[key] != artifact_digests.get(key)
           for key, _, _ in PHYSICAL_ARTIFACTS):
        raise ProbeError("review record does not match the tested binary artifacts")
    return {"reviewer": reviewer, "run_id": run_id,
            "approval_mode": "verbal"}


def _fsync_directory(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY |
                 os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        _close_fd_preserving_active_error(fd)


def _algorithm_runtime_base():
    """Return a root-only same-boot state directory backed by /run tmpfs."""
    base = ALGORITHM_RUNTIME_BASE
    parent = base.parent
    run_root = parent.parent
    try:
        root_info = run_root.lstat()
    except OSError as exc:
        raise ProbeError("runtime state root is unavailable") from exc
    if (not stat.S_ISDIR(root_info.st_mode) or root_info.st_uid != 0 or
            root_info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
        raise ProbeError("runtime state root is not root-controlled")
    for directory in (parent, base):
        try:
            info = directory.lstat()
        except FileNotFoundError:
            try:
                directory.mkdir(mode=0o700)
            except OSError as exc:
                raise ProbeError(
                    "cannot create root-only runtime state directory") from exc
            _fsync_directory(directory.parent)
            info = directory.lstat()
        except OSError as exc:
            raise ProbeError("cannot inspect runtime state directory") from exc
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or
                stat.S_IMODE(info.st_mode) != 0o700):
            raise ProbeError(
                "runtime state directory must be root-owned mode 0700")
    return base


def _recovery_base(target=None):
    """Return legacy persistent state or new same-boot development state."""
    if isinstance(target, dict) and target.get("development_only") is True:
        return _algorithm_runtime_base()
    base = RECOVERY_BASE
    for directory in (base, *base.parents):
        try:
            info = directory.lstat()
        except OSError as exc:
            raise ProbeError("recovery base or a parent is missing") from exc
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or (
                info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            raise ProbeError("recovery path must have root-controlled directory parents")
    if stat.S_IMODE(base.stat().st_mode) != 0o700:
        raise ProbeError("operator must pre-provision recovery base as root-only 0700")
    filesystem = _run([
        "findmnt", "--first-only", "--noheadings", "--output", "FSTYPE",
        "--target", str(base),
    ]).stdout.strip()
    if filesystem not in PERSISTENT_RECOVERY_FILESYSTEMS:
        raise ProbeError("recovery base has unverified or nonpersistent filesystem")
    source = _run([
        "findmnt", "--first-only", "--noheadings", "--output", "SOURCE",
        "--target", str(base),
    ]).stdout.strip()
    source_device = source.split("[", 1)[0]
    if not source_device.startswith("/dev/") or re.match(
            r"^/dev/(?:loop|ram|zram|nullb)", source_device):
        raise ProbeError("recovery filesystem has no verified persistent block source")
    ancestry = _run([
        "lsblk", "--inverse", "--raw", "--noheadings",
        "--output", "MAJ:MIN,TYPE,NAME", source_device,
    ]).stdout.splitlines()
    devices = [line.split() for line in ancestry if line.strip()]
    if not devices or any(len(row) != 3 or not re.fullmatch(
            r"[0-9]+:[0-9]+", row[0]) or row[1] in {
            "loop", "ram", "zram"} or re.match(
            r"^(?:loop|ram|zram|nullb)", row[2]) for row in devices) or (
            not any(row[1] == "disk" for row in devices)):
        raise ProbeError("recovery backing chain is volatile or unverifiable")
    if target is not None:
        # Bare-metal recovery must remain on another physical disk. A verified
        # VM-only development run may use a sibling guest partition because it
        # makes no physical-failure claim, but never the target partition.
        target_parent = target.get("parent_major_minor")
        if (not isinstance(target_parent, str) or
                re.fullmatch(r"(0|[1-9][0-9]*):(0|[1-9][0-9]*)",
                             target_parent) is None):
            raise ProbeError("target physical parent identity is unavailable")
        physical_disk_parents = {
            row[0] for row in devices if row[1] == "disk"
        }
        if len(physical_disk_parents) != 1:
            raise ProbeError("recovery physical parent identity is ambiguous")
        recovery_devices = {row[0] for row in devices}
        target_device = f"{target['major']}:{target['minor']}"
        if target_device in recovery_devices:
            raise ProbeError(
                "recovery storage resolves through the selected swap partition")
        if target.get("virtual_device_only") is not True and (
                target_parent in recovery_devices or
                target_parent in physical_disk_parents):
            raise ProbeError(
                "recovery storage is on the selected swap physical parent")
    return base


def _recovery_run_directory(state_dir, run_id=None):
    directory = Path(state_dir)
    if directory.parent == ALGORITHM_RUNTIME_BASE:
        base = _algorithm_runtime_base()
    else:
        base = _recovery_base()
    if not directory.is_absolute() or directory.parent != base:
        raise ProbeError("state run directory must be a direct child of its fixed base")
    if run_id is not None:
        if directory.name != f"swapz-physical-{run_id}":
            raise ProbeError("run directory must match the one-use approval run_id")
    elif not re.fullmatch(r"swapz-physical-[0-9a-f]{32}", directory.name):
        raise ProbeError("invalid recovery run directory name")
    return directory


def _select_run_directory(state_dir, run_id, development_only):
    """Use a fresh root-only tmpfs child for an unreviewed development trial."""
    if development_only:
        if state_dir is not None:
            raise ProbeError(
                "development-only mode chooses its own fresh runtime directory")
        _algorithm_runtime_base()
        state_dir = ALGORITHM_RUNTIME_BASE / f"swapz-physical-{run_id}"
    elif state_dir is None:
        raise ProbeError("qualified run requires an explicit recovery directory")
    return _recovery_run_directory(state_dir, run_id)


def _partition_lock(partuuid, base=None):
    """Lock one partition for the lifetime of the same-boot/legacy state."""
    if base is None:
        base = _recovery_base()
    else:
        base = Path(base)
    name = f"partition-{partuuid}.lock"
    fd = os.open(base / name, os.O_RDWR | os.O_CREAT |
                 os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or (
                stat.S_IMODE(info.st_mode) != 0o600):
            raise ProbeError("partition lock is not root-controlled")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ProbeError("another physical attempt owns this partition") from exc
        _fsync_directory(base)
        return fd
    except BaseException:
        _close_fd_preserving_active_error(fd)
        raise


def _durable_exclusive_record(path, record):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        _write_all(fd, (json.dumps(record, sort_keys=True) + "\n").encode())
        os.fsync(fd)
    finally:
        _close_fd_preserving_active_error(fd)
    _fsync_directory(path.parent)


def _review_consumption_record(target, run_id):
    return {"run_id": run_id, "partuuid": target["partuuid"],
            "major": target["major"], "minor": target["minor"]}


def _check_review_unconsumed(target, run_id):
    base = _recovery_base(target)
    if (base / f"consumed-{run_id}.json").exists() or (
            base / f"partition-{target['partuuid']}.active").exists():
        raise ProbeError("review consumed or partition recovery outstanding")


def _burn_review(target, run_id):
    """Permanently consume one approved run before any preparation can fail."""
    base = _recovery_base(target)
    record = _review_consumption_record(target, run_id)
    if (base / f"partition-{target['partuuid']}.active").exists():
        raise ProbeError("partition recovery is already outstanding")
    try:
        _durable_exclusive_record(base / f"consumed-{run_id}.json", record)
    except FileExistsError as exc:
        raise ProbeError("verbal physical review was already consumed") from exc


def _consume_review(target, run_id, *, preburned=False):
    """Claim partition recovery exactly once, including for direct callers."""
    base = _recovery_base(target)
    record = _review_consumption_record(target, run_id)
    active_path = base / f"partition-{target['partuuid']}.active"
    used_path = base / f"consumed-{run_id}.json"
    if active_path.exists():
        raise ProbeError("physical partition recovery is already outstanding")
    if not preburned:
        # Direct callers cannot reinterpret an old consumed review as a fresh
        # run. run_probe() explicitly burns its review before preparation.
        _burn_review(target, run_id)
    try:
        used = _load_unique_json(used_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ProbeError("consumed review record is missing or unreadable") from exc
    if used != record:
        raise ProbeError("consumed review record belongs to another device")
    try:
        _durable_exclusive_record(active_path, record)
    except FileExistsError as exc:
        raise ProbeError("physical partition recovery is already outstanding") from exc


def _release_partition_ownership(state):
    """Release an active marker only after durable COMPLETE, never the consumption."""
    stage = state.get("stage")
    if stage != "COMPLETE":
        # Persisted state is untrusted; name only known stages in diagnostics.
        observed_stage = (
            stage if type(stage) is str and stage in {
                "PREPARED", "BACKED_UP", "SWAP_OFF", "HEADER_CLEAR_PENDING",
                "HEADER_CLEARED", "HEADER_RESTORE_PENDING", "SWZ_FORMATTED",
                "EXISTING_SWAP_READY", "MODULE_PENDING", "MODULE_OWNED",
                "MAPPED", "ORACLE_PASS",
                "RECOVERY_REQUIRED", "PRE_DESTRUCTIVE_FAILED",
            } else "invalid_or_unknown")
        raise ProbeError(
            "partition ownership release refused: "
            "restoration_stage expected='COMPLETE' "
            f"observed={observed_stage!r}; "
            "ownership_marker_action=not_attempted")
    base = _recovery_base(state)
    active_path = base / f"partition-{state['partuuid']}.active"
    try:
        marker = _load_unique_json(active_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ProbeError("partition ownership marker missing or damaged") from exc
    if marker != {"run_id": state["run_id"], "partuuid": state["partuuid"],
                  "major": state["major"], "minor": state["minor"]}:
        raise ProbeError("another physical run owns the recovery marker")
    used_path = base / f"consumed-{state['run_id']}.json"
    try:
        used = _load_unique_json(used_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ProbeError("one-use run-authorization consumption is missing") from exc
    if used != marker:
        raise ProbeError("consumed review identity does not match partition owner")
    active_path.unlink()
    try:
        _fsync_directory(base)
    except OSError as release_sync_error:
        # A failed directory sync makes marker deletion durability ambiguous.
        # Re-create and durably sync the exact owner before reporting failure.
        try:
            _durable_exclusive_record(active_path, marker)
        except BaseException as retention_error:
            raise ProbeError(
                "partition ownership release durability uncertain: "
                f"first_errno={_errno_text(release_sync_error)} "
                f"retention_errno={_errno_text(retention_error)} "
                "owner_marker=uncertain; "
                "safe_next_step=inspect_owner_and_state_read_only"
            ) from release_sync_error
        raise ProbeError(
            "partition ownership release durability uncertain: "
            f"first_errno={_errno_text(release_sync_error)} "
            "owner_marker=retained; "
            "safe_next_step=retry_recovery_after_read_only_inspection"
        ) from release_sync_error


def _validate_state_dir(state_dir):
    state_dir = _recovery_run_directory(state_dir)
    try:
        info = state_dir.lstat()
    except OSError as exc:
        raise ProbeError(f"cannot inspect saved state directory: {exc}") from exc
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or \
            stat.S_IMODE(info.st_mode) != 0o700:
        raise ProbeError("saved state directory must be a root-owned 0700 directory")
    try:
        state_entry = (state_dir / STATE_NAME).lstat()
    except OSError as exc:
        raise ProbeError(f"missing saved state file {STATE_NAME}: {exc}") from exc
    if (not stat.S_ISREG(state_entry.st_mode) or state_entry.st_uid != 0 or
            stat.S_IMODE(state_entry.st_mode) != 0o600):
        raise ProbeError(
            f"saved state file {STATE_NAME} must be root-owned mode 0600")
    try:
        state = _load_unique_json((state_dir / STATE_NAME).read_bytes())
    except (OSError, ValueError) as exc:
        raise ProbeError("saved state record is unreadable") from exc
    if state.get("raw_header_preservation_required") is True:
        return
    # Historical pre-migration journals alone need their original header copy.
    try:
        backup_entry = (state_dir / BACKUP_NAME).lstat()
    except OSError as exc:
        raise ProbeError(
            f"missing legacy recovery file {BACKUP_NAME}: {exc}") from exc
    if (not stat.S_ISREG(backup_entry.st_mode) or backup_entry.st_uid != 0 or
            stat.S_IMODE(backup_entry.st_mode) != 0o600):
        raise ProbeError(
            f"legacy recovery file {BACKUP_NAME} must be root-owned mode 0600")


def _write_all(fd, data):
    view = memoryview(data)
    offset = 0
    while offset < len(view):
        written = os.write(fd, view[offset:])
        if written <= 0:
            raise ProbeError("short write while saving recovery state")
        offset += written


def _save_state(state_dir, state):
    state_dir = Path(state_dir)
    fd, temp_name = tempfile.mkstemp(prefix=".state-", dir=state_dir)
    try:
        os.fchmod(fd, 0o600)
        _write_all(fd, (json.dumps(state, sort_keys=True, indent=2) + "\n").encode())
        os.fsync(fd)
        closing_fd = fd
        fd = -1
        _close_fd_preserving_active_error(closing_fd)
        os.replace(temp_name, state_dir / STATE_NAME)
        dir_fd = os.open(state_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            _close_fd_preserving_active_error(dir_fd)
    finally:
        if fd >= 0:
            closing_fd = fd
            fd = -1
            _close_fd_preserving_active_error(closing_fd)
        _unlink_path_preserving_active_error(temp_name)


def _utc_timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z")


def _bounded_text(value, limit=MAX_RECORDED_OUTPUT_CHARS):
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str):
        value = str(value)
    if len(value) <= limit:
        return value
    suffix = "\n...[truncated]"
    return value[:limit - len(suffix)] + suffix


def _errno_text(error):
    """Return the first numeric errno from a wrapped failure chain."""
    seen = set()
    current = error
    while isinstance(current, BaseException) and id(current) not in seen:
        seen.add(id(current))
        value = getattr(current, "errno", None)
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
        cause = getattr(current, "__cause__", None)
        current = cause if isinstance(cause, BaseException) else getattr(
            current, "__context__", None)
    return "unavailable"


def _save_results(state_dir, results):
    """Atomically persist bounded metadata/output and its directory entry."""
    state_dir = Path(state_dir)
    fd, temp_name = tempfile.mkstemp(prefix=".results-", dir=state_dir)
    try:
        os.fchmod(fd, 0o600)
        payload = (json.dumps(results, sort_keys=True, indent=2) + "\n").encode()
        _write_all(fd, payload)
        os.fsync(fd)
        closing_fd = fd
        fd = -1
        _close_fd_preserving_active_error(closing_fd)
        os.replace(temp_name, state_dir / RESULTS_NAME)
        _fsync_directory(state_dir)
    finally:
        if fd >= 0:
            closing_fd = fd
            fd = -1
            _close_fd_preserving_active_error(closing_fd)
        _unlink_path_preserving_active_error(temp_name)


def _captured_command(args, timeout=15):
    """Return a bounded command record; never conceal output truncation."""
    output_limit = (MAX_STATUS_OUTPUT_CHARS if args[:2] ==
                    ["dmsetup", "status"] else MAX_RECORDED_OUTPUT_CHARS)
    try:
        result = _run(args, timeout=timeout, check=False)
    except ProbeError as exc:
        message = _bounded_text(exc)
        return {"return_code": None, "stdout": "", "stderr": message,
                "timed_out": "timed out" in message.lower(),
                "stdout_truncated": False, "stderr_truncated": False}
    return {"return_code": result.returncode,
            "stdout": _bounded_text(result.stdout, output_limit),
            "stderr": _bounded_text(result.stderr, output_limit),
            "timed_out": False,
            "stdout_truncated": len(result.stdout) > output_limit,
            "stderr_truncated": len(result.stderr) > output_limit}


# Linux /sys/block/*/stat sector units are 512 bytes, independent of
# logical/physical sector sizes. These are host-visible device I/O counters,
# NOT direct SD NAND wear, write amplification or endurance observations.
# The supported Linux ABI is exactly 17 fields; reject missing or extra fields
# so a shifted/truncated record cannot be certified as continuous evidence.
MAX_BLOCK_COUNTER = (1 << 64) - 1
MIN_BLOCK_STAT_FIELDS = 17
LOWER_COUNTER_FIELDS = (
    ("lower_read_requests", 0),
    ("lower_read_sectors", 2),
    ("lower_write_requests", 4),
    ("lower_write_sectors", 6),
    ("lower_flush_requests", 15),
)


def _lower_io_major_minor(target):
    """Use exact partition counters in VM mode to exclude guest-root traffic."""
    if target.get("virtual_device_only") is True:
        major = target.get("major")
        minor = target.get("minor")
        if type(major) is int and major >= 0 and type(minor) is int and minor >= 0:
            return f"{major}:{minor}"
        return None
    parent = target.get("parent_major_minor")
    return parent if isinstance(parent, str) else None


def _block_stat_snapshot(target):
    lower_identity = _lower_io_major_minor(target)
    if not isinstance(lower_identity, str) or not re.fullmatch(
            r"[0-9]+:[0-9]+", lower_identity):
        return {"available": False,
                "error": "lower_device_major_minor expected=number:number "
                         "observed=invalid_format"}
    path = Path(f"/sys/dev/block/{lower_identity}/stat")
    try:
        tokens = path.read_text().split()
        if len(tokens) <= LOWER_COUNTER_FIELDS[-1][1]:
            raise ValueError(
                "lower_flush_requests expected=field_16 observed=missing "
                f"field_count={len(tokens)}")
        if len(tokens) != MIN_BLOCK_STAT_FIELDS:
            raise ValueError(
                f"lower_stat_fields expected={MIN_BLOCK_STAT_FIELDS} "
                f"observed={len(tokens)}")
        fields = []
        for index, token in enumerate(tokens):
            if not token.isascii() or not token.isdecimal():
                raise ValueError(
                    f"lower_stat[{index}] expected=unsigned_integer "
                    "observed=non_decimal")
            value = int(token)
            if value > MAX_BLOCK_COUNTER:
                raise ValueError(
                    f"lower_stat[{index}] expected<=uint64_max observed={value}")
            fields.append(value)
        for field, index in LOWER_COUNTER_FIELDS:
            if "sectors" in field and fields[index] > MAX_BLOCK_COUNTER // 512:
                raise ValueError(
                    f"{field} expected<=uint64_max/512 "
                    f"observed={fields[index]}")
        return {"available": True, "values": fields,
                "device_major_minor": lower_identity, "sector_bytes": 512}
    except OSError as exc:
        return {"available": False,
                "error": f"lower_stat_read expected=readable observed=errno_{exc.errno}",
                "device_major_minor": lower_identity}
    except ValueError as exc:
        return {"available": False, "error": _bounded_text(exc),
                "device_major_minor": lower_identity}


def _lower_io_delta(before, after):
    """Fail closed on missing, invalid, substituted, or reset lower counters."""
    for label, snapshot in (("before", before), ("after", after)):
        if not isinstance(snapshot, dict) or snapshot.get("available") is not True:
            detail = (snapshot.get("error") if isinstance(snapshot, dict)
                      else repr(snapshot))
            raise ProbeError(
                f"lower_io_{label} expected=available observed={_bounded_text(detail)}")
        values = snapshot.get("values")
        if not isinstance(values, list) or len(values) != MIN_BLOCK_STAT_FIELDS or any(
                type(value) is not int or value < 0 or value > MAX_BLOCK_COUNTER
                for value in values):
            raise ProbeError(
                f"lower_io_{label}.values "
                f"expected={MIN_BLOCK_STAT_FIELDS}_uint64_counters "
                f"observed={_bounded_text(values)}")
        for field, index in LOWER_COUNTER_FIELDS:
            if "sectors" in field and values[index] > MAX_BLOCK_COUNTER // 512:
                raise ProbeError(
                    f"{label}.{field} expected<=uint64_max/512 "
                    f"observed={values[index]}")
    if len(before["values"]) != len(after["values"]):
        raise ProbeError(
            f"lower_io_field_count expected={len(before['values'])} "
            f"observed={len(after['values'])}")
    parent = before.get("device_major_minor")
    if (not isinstance(parent, str) or
            not re.fullmatch(r"[0-9]+:[0-9]+", parent) or
            after.get("device_major_minor") != parent or
            before.get("sector_bytes") != 512 or
            after.get("sector_bytes") != 512):
        raise ProbeError(
            f"lower_io_device expected=({parent},512) "
            f"observed=({after.get('device_major_minor')},"
            f"{after.get('sector_bytes')})")
    delta = {}
    for field, index in LOWER_COUNTER_FIELDS:
        previous = before["values"][index]
        current = after["values"][index]
        if current < previous:
            raise ProbeError(
                f"{field} reset_or_wrap expected>={previous} observed={current}")
        difference = current - previous
        delta[field.replace("_sectors", "_bytes")] = (
            difference * 512 if "sectors" in field else difference)
    return delta


def _kernel_swapz_messages(start_timestamp):
    """Retain bounded kernel evidence, identifying when time filtering is absent."""
    journalctl = shutil.which("journalctl")
    journalctl_error = None
    if journalctl:
        command = [journalctl, "--boot", "--dmesg", "--no-pager",
                   "--output=short-iso", f"--since={start_timestamp}"]
        try:
            result = _run(command, timeout=20, check=False)
            if result.returncode == 0:
                matching = [line for line in result.stdout.splitlines()
                            if re.search(r"swapz", line, re.IGNORECASE)]
                selected = "\n".join(matching[-32:])
                return {"available": True, "source": "journalctl",
                        "time_filter_applied": True,
                        "matching_line_count": len(matching),
                        "truncated": len(matching) > 32 or
                                     len(selected) > MAX_RECORDED_OUTPUT_CHARS,
                        "messages": _bounded_text(selected)}
            journalctl_error = _bounded_text(result.stderr or result.stdout)
        except ProbeError as exc:
            journalctl_error = _bounded_text(exc)

    dmesg = shutil.which("dmesg")
    if not dmesg:
        return {"available": False, "source": "journalctl" if journalctl else None,
                "time_filter_applied": False,
                "error": journalctl_error or "journalctl and dmesg are unavailable"}
    command = [dmesg, "--color=never", "--time-format=iso"]
    try:
        result = _run(command, timeout=20, check=False)
    except ProbeError as exc:
        return {"available": False, "source": "dmesg",
                "time_filter_applied": False,
                "journalctl_error": journalctl_error,
                "error": _bounded_text(exc)}
    if result.returncode:
        return {"available": False, "source": "dmesg",
                "time_filter_applied": False,
                "journalctl_error": journalctl_error,
                "return_code": result.returncode,
                "error": _bounded_text(result.stderr or result.stdout)}
    matching = [line for line in result.stdout.splitlines()
                if re.search(r"swapz", line, re.IGNORECASE)]
    selected = "\n".join(matching[-32:])
    return {"available": True, "source": "dmesg",
            "time_filter_applied": False,
            "journalctl_error": journalctl_error,
            "matching_line_count": len(matching),
            "truncated": len(matching) > 32 or
                         len(selected) > MAX_RECORDED_OUTPUT_CHARS,
            "messages": _bounded_text(selected)}


def _kernel_diagnostics_error(record):
    """Return a named fail-closed kernel-evidence error, or None when usable."""
    if not isinstance(record, dict):
        return f"kernel_trace expected=object observed={record!r}"
    if record.get("available") is not True:
        return "kernel_trace expected=available observed=unavailable"
    if record.get("time_filter_applied") is not True:
        return "kernel_trace expected=time_filtered observed=unfiltered"
    if record.get("truncated") is not False:
        return (
            "kernel_trace expected=complete "
            f"observed_truncated={record.get('truncated')!r}")
    messages = record.get("messages")
    if not isinstance(messages, str):
        return f"kernel_trace.messages expected=string observed={messages!r}"
    for line in messages.splitlines():
        fatal_match = KERNEL_FATAL_PATTERN.search(line)
        if fatal_match:
            # A kernel line can contain raw device identifiers or private paths.
            return (
                "kernel_trace_health expected=no_swapz_failure_or_warning "
                f"observed={fatal_match.group(0).lower()!r}")
    return None


def _require_kernel_diagnostics(record, context):
    error = _kernel_diagnostics_error(record)
    if error is not None:
        raise ProbeError(f"{context}: {error}")


def _swapz_status_healthy(captured):
    """Require a complete, unique terminal-health pair from the exact DM status."""
    if (not isinstance(captured, dict) or captured.get("return_code") != 0
            or captured.get("timed_out") is not False
            or captured.get("stdout_truncated") is not False
            or captured.get("stderr_truncated") is not False):
        return False
    lines = captured.get("stdout", "").strip().splitlines()
    if len(lines) != 1:
        return False
    fields = lines[0].split()
    if fields[:3] != ["0", str(LOGICAL_SECTORS), "swapz"]:
        return False
    for key in ("failed", "error"):
        matches = [field for field in fields if field.startswith(f"{key}=")]
        if matches != [f"{key}=0"]:
            return False
    return not any(field.startswith("status_snapshot_error=")
                   for field in fields)


def _dm_info_rows(stdout, field_count):
    """Parse dmsetup columns without treating an existing mapper as absent."""
    output = stdout.strip()
    if output == "No devices found":
        return []
    if not output:
        raise ProbeError("empty Device Mapper inventory is ambiguous")
    rows = []
    for line in stdout.splitlines():
        if line.strip() == "No devices found":
            raise ProbeError("mixed Device Mapper inventory diagnostic and rows")
        # dmsetup -c defaults to colon-separated columns on some hosts, while
        # other versions and existing fixtures emit whitespace columns.
        fields = line.strip().split(":") if ":" in line else line.split()
        if field_count == 2 and len(fields) == 1:
            fields.append("")  # An unrelated mapper may have no DM UUID.
        fields = tuple(field.strip() for field in fields)
        if len(fields) != field_count or not fields[0]:
            raise ProbeError("cannot parse Device Mapper inventory")
        rows.append(fields)
    return rows


def _dm_inventory_snapshot(
        owned_name=None, owned_uuid=None, *, reject_swapz_namespace=False):
    result = _run([
        "dmsetup", "info", "-c", "--noheadings", "-o", "name,uuid",
    ], check=False)
    if result.returncode:
        raise ProbeError("cannot snapshot Device Mapper inventory")
    rows = []
    for name, uuid in _dm_info_rows(result.stdout, 2):
        if reject_swapz_namespace and (
                name.startswith("swapz") or uuid.startswith("SWAPZ")):
            conflict = ("name_namespace_collision" if name.startswith("swapz")
                        else "uuid_namespace_collision")
            raise ProbeError(
                "mapper_provenance expected=no_swapz_namespace "
                f"observed={conflict}")
        if name == owned_name or uuid == owned_uuid:
            if (name, uuid) != (owned_name, owned_uuid):
                raise ProbeError("owned mapper name or UUID changed in inventory")
            continue
        rows.append([name, uuid])
    rows.sort()
    digest = hashlib.sha256(json.dumps(
        rows, separators=(",", ":")).encode()).hexdigest()
    return {"other_mapper_count": len(rows), "other_mapper_sha256": digest}


def _module_loaded_from_sysfs():
    """Read the module inventory so unreadable provenance cannot look absent."""
    try:
        with os.scandir("/sys/module") as entries:
            return any(entry.name == "dm_swapz" for entry in entries)
    except OSError as exc:
        raise ProbeError(
            "module_provenance expected=readable_module_inventory "
            f"observed=unavailable_errno_{exc.errno}"
        ) from exc


def _mapper_inventory_unchanged(before, after):
    """Validate and compare the two bounded non-owned mapper inventories."""
    expected_fields = {"other_mapper_count", "other_mapper_sha256"}
    for label, snapshot in (("before", before), ("after", after)):
        if not isinstance(snapshot, dict) or set(snapshot) != expected_fields:
            raise ProbeError(
                f"dm_inventory_{label} expected=exact_bounded_inventory "
                f"observed={type(snapshot).__name__}")
        count = snapshot.get("other_mapper_count")
        digest = snapshot.get("other_mapper_sha256")
        if type(count) is not int or count < 0:
            raise ProbeError(
                f"dm_inventory_{label}.other_mapper_count "
                "expected=nonnegative_integer observed=invalid")
        if not isinstance(digest, str) or not re.fullmatch(
                r"[0-9a-f]{64}", digest):
            raise ProbeError(
                f"dm_inventory_{label}.other_mapper_sha256 "
                "expected=lowercase_sha256 observed=invalid")
    return before == after


def _module_mapper_preflight():
    """Prove a clean swapz module baseline and readable DM inventory."""
    if _module_loaded_from_sysfs():
        raise ProbeError(
            "module_provenance expected=dm_swapz_absent observed=loaded")
    inventory = _dm_inventory_snapshot(reject_swapz_namespace=True)
    if _module_loaded_from_sysfs():
        raise ProbeError(
            "module_provenance expected=stable_absence observed=loaded_during_check")
    return inventory


def _final_observations(results, state_dir, state, target):
    """Collect final identity-only observations; never read test page contents."""
    current_errors = []
    current_header_matches = False
    try:
        header = _read_block0(target["device"], target)
        results["final_block0_sha256"] = hashlib.sha256(header).hexdigest()
        current_header_matches = (
            results["final_block0_sha256"] == results.get(
                "original_header_sha256"))
        results["original_header_matches_final"] = current_header_matches
    except ProbeError as exc:
        results["final_block0_sha256"] = None
        results["original_header_matches_final"] = False
        results.setdefault("final_block0_error", _bounded_text(exc))
        current_errors.append("final_block0_unverifiable")

    current_swap_inventory_verified = True
    try:
        results["final_swap_row"] = _active_swap_for(
            target["major"], target["minor"])
    except ProbeError as exc:
        results["final_swap_row"] = None
        results.setdefault("final_swap_error", _bounded_text(exc))
        current_swap_inventory_verified = False
        current_errors.append("final_swap_inventory_unverifiable")

    current_block_stats = _block_stat_snapshot(target)
    # Final observations may be retried after an uncertain sample. Preserve the
    # first unavailable sample instead of certifying a later retry as complete.
    if results.get("lower_io_evidence_gate") != "BLOCKED":
        results["block_stats_after"] = current_block_stats
    try:
        results["lower_io_delta"] = _lower_io_delta(
            results.get("block_stats_before"), results.get("block_stats_after"))
        if results.get("lower_io_evidence_gate") != "BLOCKED":
            results["lower_io_evidence_gate"] = "AVAILABLE"
    except ProbeError as exc:
        results["lower_io_delta"] = None
        results["lower_io_evidence_gate"] = "BLOCKED"
        results.setdefault("lower_io_evidence_error", _bounded_text(exc))

    current_kernel_messages = _kernel_swapz_messages(
        results.get("start_timestamp", "now"))
    if results.get("kernel_diagnostics_gate") != "BLOCKED":
        results["kernel_swapz_messages"] = current_kernel_messages
    diagnostics = results.get("kernel_swapz_messages")
    diagnostics_error = _kernel_diagnostics_error(diagnostics)
    if diagnostics_error is None:
        if results.get("kernel_diagnostics_gate") != "BLOCKED":
            results["kernel_diagnostics_gate"] = "AVAILABLE"
    else:
        results["kernel_diagnostics_gate"] = "BLOCKED"
        results.setdefault("kernel_diagnostics_error", diagnostics_error)

    row = results.get("final_swap_row")
    if state.get("swap_was_active") is True:
        current_restored_swap_verified = (
            current_swap_inventory_verified
            and isinstance(row, dict)
            and row.get("kind") == "partition"
            and type(state.get("swap_size_kib")) is int
            and type(state.get("swap_priority")) is int
            and row.get("size_kib") == state["swap_size_kib"]
            and row.get("priority") == state["swap_priority"])
    else:
        # Development-only physical backing smoke preserves an originally
        # inactive target. Absence from /proc/swaps is the required post-state.
        current_restored_swap_verified = (
            current_swap_inventory_verified
            and state.get("development_only") is True
            and state.get("swap_was_active") is False
            and row is None)
    # A historical failed inventory read remains disqualifying evidence for the
    # run, even when a later recovery retry can finally verify safe cleanup.
    results["restored_swap_verified"] = (
        "final_swap_error" not in results and current_restored_swap_verified)

    current_mapper_removed = False
    try:
        results["final_mapper_present"] = _mapper_exists(state)
        current_mapper_removed = results["final_mapper_present"] is False
    except ProbeError as exc:
        results["final_mapper_present"] = None
        results.setdefault("final_mapper_error", _bounded_text(exc))
        current_errors.append("final_mapper_unverifiable")

    results["final_module_present"] = Path("/sys/module/dm_swapz").exists()
    current_module_cleanup = results["final_module_present"] is False
    active = _recovery_base(target) / f"partition-{state['partuuid']}.active"
    active_marker_present = active.exists()
    results["active_partition_marker_present"] = active_marker_present
    consumed = _recovery_base(target) / f"consumed-{state['run_id']}.json"
    run_claim_consumed = consumed.is_file()
    results["run_claim_consumed"] = run_claim_consumed
    results["approval_consumed"] = (
        run_claim_consumed if state.get("development_only") is not True else None)
    current_target_inactive = (
        current_swap_inventory_verified
        and state.get("development_only") is True
        and state.get("swap_was_active") is False and row is None)
    results["target_remains_inactive"] = (
        "final_swap_error" not in results and current_target_inactive)
    try:
        results["unrelated_swapfiles_restored"] = (
            _development_swapfiles_restored(state))
        if not results["unrelated_swapfiles_restored"]:
            current_errors.append("unrelated_swapfiles_not_restored")
    except ProbeError as exc:
        results["unrelated_swapfiles_restored"] = False
        results.setdefault("unrelated_swapfiles_error", _bounded_text(exc))
        current_errors.append("unrelated_swapfiles_unverifiable")
    results["final_recovery_state"] = state.get("stage")
    results["mapper_removal_succeeded"] = current_mapper_removed
    results["module_cleanup_succeeded"] = current_module_cleanup

    current_inventory_unchanged = False
    try:
        results["dm_inventory_after"] = _dm_inventory_snapshot(
            state.get("dm_name"), state.get("dm_uuid"))
        current_inventory_unchanged = _mapper_inventory_unchanged(
            results.get("dm_inventory_before"), results["dm_inventory_after"])
        results["unrelated_mapper_inventory_unchanged"] = (
            current_inventory_unchanged)
    except ProbeError as exc:
        results["dm_inventory_after"] = None
        results["unrelated_mapper_inventory_unchanged"] = None
        results.setdefault("dm_inventory_error", _bounded_text(exc))
        current_errors.append("dm_inventory_unverifiable")

    results["end_timestamp"] = _utc_timestamp()
    _save_results(state_dir, results)
    return {
        "errors": current_errors,
        "original_header_matches_final": current_header_matches,
        "restored_swap_verified": current_restored_swap_verified,
        "mapper_removal_succeeded": current_mapper_removed,
        "module_cleanup_succeeded": current_module_cleanup,
        "unrelated_mapper_inventory_unchanged": current_inventory_unchanged,
        "active_partition_marker_present": active_marker_present,
        "run_claim_consumed": run_claim_consumed,
        "unrelated_swapfiles_restored":
            results.get("unrelated_swapfiles_restored") is True,
    }


def _final_cleanup_evidence_error(observation):
    """Return why this cleanup sample is unsafe to release, or None."""
    if not isinstance(observation, dict):
        return "cleanup_observation expected=object observed=invalid"
    errors = observation.get("errors")
    if not isinstance(errors, list):
        return "cleanup_observation.errors expected=list observed=invalid"
    if errors:
        return "current_errors=" + ",".join(str(error) for error in errors)
    required_true = (
        "original_header_matches_final",
        "restored_swap_verified",
        "mapper_removal_succeeded",
        "module_cleanup_succeeded",
        "unrelated_mapper_inventory_unchanged",
        "active_partition_marker_present",
        "run_claim_consumed",
        "unrelated_swapfiles_restored",
    )
    failures = [
        f"{field} expected=True observed={observation.get(field)!r}"
        for field in required_true
        if observation.get(field) is not True
    ]
    if failures:
        return "; ".join(failures)
    return None


def _allocate_dm_identity():
    result = _run([
        "dmsetup", "info", "-c", "--noheadings", "-o", "name,uuid",
    ])
    if result.returncode:
        raise ProbeError("cannot enumerate Device Mapper identities")
    existing = set(_dm_info_rows(result.stdout, 2))
    existing_names = {name for name, _ in existing}
    existing_uuids = {uuid for _, uuid in existing}
    for _ in range(16):
        token = secrets.token_hex(8)
        name = f"swapz-demo-physical-{token}"
        uuid = f"SWAPZ-TEST-PHYSICAL-{token}"
        if name not in existing_names and uuid not in existing_uuids:
            return name, uuid
    raise ProbeError("cannot allocate a unique owned Device Mapper identity")


def _write_block0(device, data, target, expected_current=None):
    if len(data) != PAGE_BYTES:
        raise ProbeError("recovery header has the wrong length")
    if expected_current is not None and len(expected_current) != PAGE_BYTES:
        raise ProbeError("expected partition header has the wrong length")
    try:
        fd = os.open(device, os.O_RDWR | os.O_CLOEXEC | os.O_EXCL | os.O_SYNC)
    except OSError as exc:
        raise ProbeError(f"cannot exclusively open selected partition: {exc}") from exc
    try:
        _verify_open_block_device(fd, target)
        if expected_current is not None and (
                _read_exact_block0(fd) != expected_current):
            raise ProbeError("partition header changed before exclusive update")
        try:
            written = os.pwrite(fd, data, 0)
        except OSError as exc:
            raise ProbeError(
                "operation=header_write offset=0 "
                f"original_errno={exc.errno} "
                "safe_next_step=recover_with_durable_state") from exc
        if type(written) is not int or written != PAGE_BYTES:
            observed_written = (
                written if type(written) is int and written >= 0 else "invalid")
            raise ProbeError(
                "operation=header_write offset=0 original_errno=unavailable "
                "expected=4096_bytes observed=short_or_invalid_write "
                f"written_bytes={observed_written!r} "
                "safe_next_step=recover_with_durable_state")
        os.fsync(fd)
        if _read_exact_block0(fd) != data:
            raise ProbeError("partition header readback did not match")
    finally:
        # Never resume a short block-device write; recovery owns any partial
        # mutation. A secondary close failure cannot replace the first fault.
        _close_fd_preserving_active_error(fd)

def _active_swap_for(major, minor):
    """Resolve all active swap entries without mistaking swapfiles for devices."""
    matching = []
    for row in parse_swap_rows(Path("/proc/swaps").read_text()):
        if row["kind"] == "file":
            try:
                info = os.stat(row["path"])
            except OSError as exc:
                raise ProbeError("cannot verify active swapfile identity") from exc
            if not stat.S_ISREG(info.st_mode):
                raise ProbeError("active swapfile is not a regular file")
            continue
        if row["kind"] != "partition":
            raise ProbeError("unsupported active swap entry type")
        try:
            identity = block_identity(row["path"])
        except ProbeError as exc:
            raise ProbeError("cannot verify active swap block identity") from exc
        if identity == (major, minor):
            matching.append(row)
    if len(matching) > 1:
        raise ProbeError("ambiguous duplicate active swap entries")
    return matching[0] if matching else None


def _development_swapfile_identity(row):
    """Capture one unrelated active swapfile without treating its path as target proof."""
    if not isinstance(row, dict) or row.get("kind") != "file":
        raise ProbeError("development swapfile record is malformed")
    path = row.get("path")
    if not isinstance(path, str) or not path.startswith("/"):
        raise ProbeError("development swapfile path is not absolute")
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise ProbeError("cannot verify active swapfile identity") from exc
    if not stat.S_ISREG(info.st_mode):
        raise ProbeError("active swapfile path is not a regular file")
    return {
        "path": path,
        "size_kib": row["size_kib"],
        "used_kib": row["used_kib"],
        "priority": row["priority"],
        "st_dev": info.st_dev,
        "st_ino": info.st_ino,
    }


def _validate_saved_swapfile(record):
    required = {"path", "size_kib", "used_kib", "priority", "st_dev", "st_ino"}
    if not isinstance(record, dict) or set(record) != required:
        raise ProbeError("saved unrelated swapfile record is malformed")
    if not isinstance(record["path"], str) or not record["path"].startswith("/"):
        raise ProbeError("saved unrelated swapfile path is malformed")
    for field in ("size_kib", "used_kib", "priority", "st_dev", "st_ino"):
        if type(record[field]) is not int:
            raise ProbeError("saved unrelated swapfile numeric identity is malformed")
    if (record["size_kib"] <= 0 or record["used_kib"] < 0 or
            record["used_kib"] > record["size_kib"] or
            record["st_dev"] < 0 or record["st_ino"] <= 0):
        raise ProbeError("saved unrelated swapfile bounds are malformed")


def _swapfile_identity_matches(left, right):
    return all(left.get(field) == right.get(field) for field in (
        "path", "size_kib", "priority", "st_dev", "st_ino"))


def _active_swapfile_for(saved):
    """Return the active row for the exact saved regular-file inode, if any."""
    _validate_saved_swapfile(saved)
    try:
        named = os.lstat(saved["path"])
    except OSError as exc:
        raise ProbeError("saved unrelated swapfile path is unavailable") from exc
    if (not stat.S_ISREG(named.st_mode) or
            named.st_dev != saved["st_dev"] or
            named.st_ino != saved["st_ino"]):
        raise ProbeError("saved unrelated swapfile identity changed")
    matches = []
    try:
        rows = parse_swap_rows(Path("/proc/swaps").read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise ProbeError("cannot read active swap inventory") from exc
    for row in rows:
        if row["kind"] != "file":
            continue
        current = _development_swapfile_identity(row)
        if (current["st_dev"] == saved["st_dev"] and
                current["st_ino"] == saved["st_ino"]):
            matches.append(row)
    if len(matches) > 1:
        raise ProbeError("saved unrelated swapfile has duplicate active aliases")
    return matches[0] if matches else None


def _development_swap_inventory_plan(target):
    """Snapshot only the selected target plus unrelated regular swapfiles."""
    target_device = (target["major"], target["minor"])
    target_rows = []
    swapfiles = []
    try:
        rows = parse_swap_rows(Path("/proc/swaps").read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise ProbeError("cannot read active swap inventory for physical trial") from exc
    for row in rows:
        if row["kind"] == "file":
            swapfiles.append(_development_swapfile_identity(row))
            continue
        if row["kind"] != "partition":
            raise ProbeError("unsupported active swap entry type")
        identity = block_identity(row["path"])
        if identity != target_device:
            raise ProbeError(
                "unrelated active block swap is not admitted by the bounded physical trial")
        target_rows.append(row)
    if len(target_rows) > 1:
        raise ProbeError("selected target has duplicate active swap aliases")
    expected_active = target.get("swap_was_active")
    if expected_active is True:
        if len(target_rows) != 1:
            raise ProbeError("selected target active-swap state changed before transaction")
        target_row = target_rows[0]
        if (target_row["size_kib"] != target.get("swap_size_kib") or
                target_row["priority"] != target.get("swap_priority")):
            raise ProbeError("selected target swap size or priority changed")
    elif expected_active is False:
        if target_rows:
            raise ProbeError("selected target became active swap before transaction")
        target_row = None
    else:
        raise ProbeError("selected target saved swap-active state is malformed")
    return target_row, swapfiles


def _require_development_swapoff_headroom(target_row, swapfiles):
    total_used_kib = target_row["used_kib"] if target_row is not None else 0
    total_used_kib += sum(record["used_kib"] for record in swapfiles)
    try:
        contents = Path("/proc/meminfo").read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise ProbeError("cannot prove host memory headroom before swapoff") from exc
    match = re.search(r"(?m)^MemAvailable:\s+(\d+) kB$", contents)
    if match is None:
        raise ProbeError("cannot parse MemAvailable before swapoff")
    available_kib = int(match.group(1))
    required_kib = max(
        DEVELOPMENT_SWAPOFF_MIN_AVAILABLE_KIB,
        total_used_kib + DEVELOPMENT_SWAPOFF_MARGIN_KIB,
    )
    if available_kib < required_kib:
        raise ProbeError(
            "insufficient host memory headroom for bounded swapoff; "
            f"available_kib={available_kib} required_kib={required_kib}")


def _quiesce_development_swap_inventory(state, target, state_dir):
    """Temporarily quiesce the exact target and saved swapfiles before formatting."""
    target_row, current_swapfiles = _development_swap_inventory_plan(target)
    saved_swapfiles = state.get("unrelated_swapfiles")
    if (not isinstance(saved_swapfiles, list) or
            len(saved_swapfiles) != len(current_swapfiles)):
        raise ProbeError("unrelated swapfile inventory changed before swapoff")
    for saved, current in zip(saved_swapfiles, current_swapfiles):
        _validate_saved_swapfile(saved)
        if not _swapfile_identity_matches(saved, current):
            raise ProbeError("unrelated swapfile identity changed before swapoff")
    _require_development_swapoff_headroom(target_row, current_swapfiles)

    if target_row is not None:
        _verify_target_identity(target)
        _run(["swapoff", "--", target["device"]], timeout=120)
        if _active_swap_for(target["major"], target["minor"]) is not None:
            raise ProbeError("swapoff returned but selected partition remains active")

    for saved in saved_swapfiles:
        current = _active_swapfile_for(saved)
        if current is None:
            raise ProbeError("saved unrelated swapfile became inactive before owned swapoff")
        _run(["swapoff", "--", saved["path"]], timeout=120)
        if _active_swapfile_for(saved) is not None:
            raise ProbeError("swapoff returned but unrelated swapfile remains active")

    require_development_formatter_inventory_clear()
    state["stage"] = "SWAP_OFF"
    _save_state(state_dir, state)


def _restore_development_swapfiles(state):
    """Restore only the exact unrelated swapfiles saved by this run."""
    saved_swapfiles = state.get("unrelated_swapfiles")
    if saved_swapfiles is None:
        return True
    if not isinstance(saved_swapfiles, list):
        raise ProbeError("saved unrelated swapfile inventory is malformed")
    for saved in saved_swapfiles:
        _validate_saved_swapfile(saved)
        active = _active_swapfile_for(saved)
        if active is None:
            if saved["priority"] >= 0:
                _run(["swapon", "--priority", str(saved["priority"]),
                      "--", saved["path"]], timeout=60)
            else:
                _run(["swapon", "--", saved["path"]], timeout=60)
            active = _active_swapfile_for(saved)
        if (active is None or active["size_kib"] != saved["size_kib"] or
                active["priority"] != saved["priority"]):
            raise ProbeError("unrelated swapfile was not restored exactly")
    return True


def _development_swapfiles_restored(state):
    saved_swapfiles = state.get("unrelated_swapfiles")
    if saved_swapfiles is None:
        return True
    if not isinstance(saved_swapfiles, list):
        raise ProbeError("saved unrelated swapfile inventory is malformed")
    for saved in saved_swapfiles:
        active = _active_swapfile_for(saved)
        if (active is None or active["size_kib"] != saved["size_kib"] or
                active["priority"] != saved["priority"]):
            return False
    return True


def _holder_names(major, minor):
    holders = Path(f"/sys/dev/block/{major}:{minor}/holders")
    return sorted(path.name for path in holders.iterdir())


def _validate_owned_mapper_identity(state):
    name = state.get("dm_name")
    uuid = state.get("dm_uuid")
    if not isinstance(name, str) or not isinstance(uuid, str) or \
            not name.startswith("swapz-demo-physical-") or \
            not uuid.startswith("SWAPZ-TEST-PHYSICAL-"):
        raise ProbeError("saved state lacks a valid owned mapper identity")
    name_token = name[len("swapz-demo-physical-"):]
    uuid_token = uuid[len("SWAPZ-TEST-PHYSICAL-"):]
    if not re.fullmatch(r"[0-9a-f]{16}", name_token) or \
            name_token != uuid_token:
        raise ProbeError("saved mapper name and UUID tokens do not match")


def _expected_dm_table(target):
    return (f"0 {LOGICAL_SECTORS} swapz {target['device']} "
            "0 64 0 2 0 1 0 0")


def _verify_owned_mapper(state, target):
    """Prove mapper identity, exact table, size and one genuine lower slave."""
    _validate_owned_mapper_identity(state)
    name, expected_uuid = state["dm_name"], state["dm_uuid"]
    info = _run([
        "dmsetup", "info", "-c", "--noheadings",
        "-o", "name,uuid,major,minor", name,
    ])
    rows = _dm_info_rows(info.stdout, 4)
    if len(rows) != 1 or rows[0][:2] != (name, expected_uuid):
        raise ProbeError("mapper name or UUID was substituted")
    try:
        dm_major, dm_minor = int(rows[0][2]), int(rows[0][3])
    except ValueError as exc:
        raise ProbeError("mapper major:minor is invalid") from exc
    mapper = f"/dev/mapper/{name}"
    if block_identity(mapper) != (dm_major, dm_minor):
        raise ProbeError("mapper node does not match DM's kernel identity")
    sysfs = Path(f"/sys/dev/block/{dm_major}:{dm_minor}")
    try:
        if (sysfs / "dm/name").read_text().strip() != name or (
                sysfs / "dm/uuid").read_text().strip() != expected_uuid or (
                sysfs / "size").read_text().strip() != str(LOGICAL_SECTORS):
            raise ProbeError("mapper sysfs identity or 16 MiB size differs")
        slaves = list((sysfs / "slaves").iterdir())
        if len(slaves) != 1 or (
                slaves[0] / "dev").read_text().strip() != (
                f"{target['major']}:{target['minor']}"):
            raise ProbeError("mapper has wrong or ambiguous lower block device")
    except OSError as exc:
        raise ProbeError("cannot prove mapper size and lower dependency") from exc
    actual_table = _run(["dmsetup", "table", "--showkeys", name]).stdout.split()
    expected_table = _expected_dm_table(target).split()
    if len(actual_table) != len(expected_table) or (
            actual_table[:3] != expected_table[:3] or
            actual_table[4:] != expected_table[4:]) or (
            actual_table[3] not in {
                expected_table[3], f"{target['major']}:{target['minor']}"}):
        raise ProbeError("mapper table differs from the one approved for the smoke")
    return mapper


def _expected_physical_oracle_stdout(options):
    """Exact affirmative output of the reviewed device-roundtrip C oracle."""
    if len(options) == 2 and options[0] == "--expect-dm-uuid":
        return ("PASS: owned V3 DM 128-page direct I/O, flush, "
                "full readback, overwrite\n")
    if len(options) != 3 or options[1] != "128":
        return None
    mode, _, round_number = options
    output_modes = {
        "--delta64-write-series": ("delta64-write", ("1",)),
        "--delta64-verify-series": ("delta64-verify", ("1",)),
        "--segmented-write-series": ("segmented write", ("5",)),
        "--segmented-verify-series": ("segmented verify", ("5", "6")),
        "--write-series": ("write", ("6",)),
        "--verify-series": ("verify", ("5", "7")),
        "--thp-write-series": ("THP compound-folio write", ("7",)),
        "--thp-verify-series": ("THP compound-folio verify", ("7",)),
    }
    expected = output_modes.get(mode)
    if expected is None or round_number not in expected[1]:
        return None
    return (f"PASS: owned swapz direct {expected[0]} series "
            f"count=128 round={round_number}\n")


def _run_positive_oracle_phase(oracle, mapper, state, target, state_dir,
                               results, phase, options=()):
    command = [oracle, mapper, *options]
    entry = {
        "phase": phase,
        "argv": [str(value) for value in command],
        "status": "IDENTITY_CHECK_PENDING",
        "started_at": _utc_timestamp(),
        "return_code": None,
        "stdout": "",
        "stderr": "",
        "dmsetup_status_before": None,
        "dmsetup_status_after": None,
        "block_stats_before": None,
        "block_stats_after": None,
        "lower_io_delta": None,
    }
    results["physical_oracle_phases"].append(entry)
    _save_results(state_dir, results)
    try:
        verified_mapper = _verify_owned_mapper(state, target)
        if verified_mapper != mapper:
            raise ProbeError("verified mapper path changed before oracle phase")
    except ProbeError as exc:
        entry["status"] = "BLOCKED_BEFORE_ORACLE"
        entry["pre_oracle_identity_error"] = _bounded_text(exc)
        entry["ended_at"] = _utc_timestamp()
        _save_results(state_dir, results)
        raise

    entry["dmsetup_status_before"] = _captured_command(
        ["dmsetup", "status", state["dm_name"]])
    entry["block_stats_before"] = _block_stat_snapshot(target)
    before_status = entry["dmsetup_status_before"]
    if (not _swapz_status_healthy(before_status) or
            entry["block_stats_before"].get("available") is not True):
        entry["status"] = "BLOCKED_BEFORE_ORACLE"
        entry["pre_oracle_status_error"] = (
            "pre_oracle_evidence expected=complete_status_and_lower_counters "
            f"observed={_bounded_text(before_status)},"
            f"{_bounded_text(entry['block_stats_before'])}")
        entry["ended_at"] = _utc_timestamp()
        _save_results(state_dir, results)
        raise ProbeError(entry["pre_oracle_status_error"])

    entry["status"] = "RUNNING"
    entry["oracle_started_at"] = _utc_timestamp()
    _save_results(state_dir, results)
    captured = _captured_command(command, timeout=180)
    entry["return_code"] = captured["return_code"]
    entry["stdout"] = captured["stdout"]
    entry["stderr"] = captured["stderr"]
    entry["timed_out"] = captured["timed_out"]

    try:
        verified_mapper = _verify_owned_mapper(state, target)
        if verified_mapper != mapper:
            raise ProbeError("verified mapper path changed after oracle phase")
        entry["post_oracle_identity"] = "PASS"
    except ProbeError as exc:
        entry["post_oracle_identity"] = "FAIL"
        entry["post_oracle_identity_error"] = _bounded_text(exc)
    entry["dmsetup_status_after"] = _captured_command(
        ["dmsetup", "status", state["dm_name"]])
    entry["block_stats_after"] = _block_stat_snapshot(target)
    entry["ended_at"] = _utc_timestamp()
    try:
        entry["lower_io_delta"] = _lower_io_delta(
            entry["block_stats_before"], entry["block_stats_after"])
    except ProbeError as exc:
        entry["lower_io_error"] = _bounded_text(exc)
    after_status = entry["dmsetup_status_after"]
    if (captured.get("stdout_truncated") or captured.get("stderr_truncated")
            or after_status.get("stdout_truncated")
            or after_status.get("stderr_truncated")):
        entry["trace_error"] = (
            "oracle_or_status_trace expected=complete observed=truncated")

    expected_stdout = _expected_physical_oracle_stdout(options)
    if (expected_stdout is None or entry["stdout"] != expected_stdout
            or entry["stderr"] != "" or entry["timed_out"] is not False):
        entry["oracle_output_error"] = (
            "operation=device_roundtrip phase=oracle_execution "
            f"original_exit={entry['return_code']!r} "
            "expected=exact_affirmative_comparison_line_and_empty_stderr "
            "observed=missing_or_contradictory_or_wrong_count "
            "safe_next_step=inspect_results_read_only")
    passed = (
        entry["return_code"] == 0
        and "oracle_output_error" not in entry
        and entry.get("post_oracle_identity") == "PASS"
        and _swapz_status_healthy(after_status)
        and entry["lower_io_delta"] is not None
        and "trace_error" not in entry
    )
    entry["status"] = "PASS" if passed else "FAIL"
    _save_results(state_dir, results)
    if not passed:
        failure_detail = entry.get("oracle_output_error") or (
            "operation=device_roundtrip phase=oracle_execution "
            f"original_exit={entry['return_code']!r} "
            "expected=healthy_mapper_verified_identity_and_complete_evidence "
            "observed=failed_or_incomplete_oracle_phase "
            "safe_next_step=inspect_results_read_only")
        raise ProbeError(
            f"physical oracle phase {phase} failed; later phases stopped; "
            + failure_detail)


def _mapper_exists(state):
    """Prove absence or exact identity; never suppress a substituted mapper."""
    _validate_owned_mapper_identity(state)
    result = _run([
        "dmsetup", "info", "-c", "--noheadings", "-o", "name,uuid",
    ])
    if result.returncode:
        raise ProbeError("cannot enumerate Device Mapper inventory")
    matches = [
        (name, uuid) for name, uuid in _dm_info_rows(result.stdout, 2)
        if name == state["dm_name"] or uuid == state["dm_uuid"]
    ]
    if not matches:
        return False
    if len(matches) != 1 or matches[0] != (
            state["dm_name"], state["dm_uuid"]):
        raise ProbeError("owned mapper name or UUID was substituted")
    return True


def _header_prefix_transition_matches(current_header, prefix_header,
                                      suffix_header):
    """Accept only one prefix/suffix boundary, including either endpoint."""
    if any(len(value) != PAGE_BYTES for value in (
            current_header, prefix_header, suffix_header)):
        return False
    last_suffix_difference = max((
        offset for offset in range(PAGE_BYTES)
        if current_header[offset] != suffix_header[offset]), default=-1)
    first_prefix_difference = next((
        offset for offset in range(PAGE_BYTES)
        if current_header[offset] != prefix_header[offset]), PAGE_BYTES)
    return last_suffix_difference < first_prefix_difference


def _recovery_header_stage(state):
    stage = state.get("stage")
    if stage == "RECOVERY_REQUIRED":
        return state.get("stage_before_recovery", stage)
    return stage


def _header_matches_recovery_stage(header, backup, state, size_bytes, stage):
    if header == backup:
        return True
    if stage == "HEADER_CLEAR_PENDING" and _header_prefix_transition_matches(
            header, bytes(PAGE_BYTES), backup):
        return True
    if header == bytes(PAGE_BYTES) and stage in {
            "SWAP_OFF", "HEADER_CLEARED"}:
        return True
    digest = state.get("formatted_header_sha256")
    return (
        stage in {"SWZ_FORMATTED", "MODULE_PENDING", "MODULE_OWNED",
                  "MAPPED", "ORACLE_PASS"}
        and isinstance(digest, str)
        and hashlib.sha256(header).hexdigest() == digest
        and swapz_header_valid(header, size_bytes)
    )




def _virtual_development_header(size_bytes):
    """Construct the formatter-compatible SWZ header for VM-only testing."""
    if type(size_bytes) is not int or size_bytes <= 0:
        raise ProbeError("virtual development header size is invalid")
    header = bytearray(PAGE_BYTES)
    header[:8] = SWAPZ_HEADER_MAGIC
    struct.pack_into("<IIQ", header, 8,
                     SWAPZ_HEADER_VERSION, PAGE_BYTES, size_bytes)
    identifier = bytearray(secrets.token_bytes(16))
    identifier[6] = (identifier[6] & 0x0f) | 0x40
    identifier[8] = (identifier[8] & 0x3f) | 0x80
    header[24:40] = identifier
    built = bytes(header)
    if not swapz_header_valid(built, size_bytes):
        raise ProbeError("virtual development SWZ header construction failed")
    return built

def _saved_header_restore_source(state, backup, size_bytes):
    source_stage = state.get("header_restore_source_stage")
    source_hex = state.get("header_restore_source_hex")
    source_sha256 = state.get("header_restore_source_sha256")
    if (source_stage not in {
            "SWAP_OFF", "HEADER_CLEAR_PENDING", "HEADER_CLEARED",
            "SWZ_FORMATTED", "MODULE_PENDING", "MODULE_OWNED",
            "MAPPED", "ORACLE_PASS"} or
            not isinstance(source_hex, str) or
            len(source_hex) != PAGE_BYTES * 2 or
            re.fullmatch(r"[0-9a-f]+", source_hex) is None or
            not isinstance(source_sha256, str) or
            re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None):
        raise ProbeError(
            "saved header restoration source is missing or malformed; "
            "manual review required")
    source = bytes.fromhex(source_hex)
    if (source == backup or
            hashlib.sha256(source).hexdigest() != source_sha256 or
            not _header_matches_recovery_stage(
                source, backup, state, size_bytes, source_stage)):
        raise ProbeError(
            "saved header restoration source is not an authenticated "
            "pre-restoration state; manual review required")
    return source


def _validate_recovery_header(current_header, backup, state, size_bytes):
    if len(current_header) != PAGE_BYTES or len(backup) != PAGE_BYTES:
        raise ProbeError("recovery header must be exactly 4096 bytes")
    # New SWAPSPACE2 runs must never repair or replace block zero. Historical
    # interrupted pre-migration journals retain their separate recovery path.
    if state.get("raw_header_preservation_required") is True and current_header != backup:
        raise ProbeError(
            "original SWAPSPACE2 header changed; raw header writes are forbidden "
            "for this run; preserve journal and inspect read-only")
    stage = _recovery_header_stage(state)
    if stage == "HEADER_RESTORE_PENDING":
        source = _saved_header_restore_source(state, backup, size_bytes)
        if _header_prefix_transition_matches(
                current_header, backup, source):
            return
    elif _header_matches_recovery_stage(
            current_header, backup, state, size_bytes, stage):
        return
    raise ProbeError(
        "partition header is not an expected recovery state; manual review required")

RECOVERY_RECORD_BINDINGS = (
    ("run_id", "run_id"),
    ("source_sha", "source_commit_sha"),
    ("helper_git_sha", "helper_git_sha"),
    ("helper_sha256", "helper_sha256"),
    ("device_arg", "device_uuid_path"),
    ("device", "canonical_device"),
    ("partuuid", "partuuid"),
    ("size_bytes", "device_size_bytes"),
    ("header_sha256", "original_header_sha256"),
    ("dm_name", "dm_name"),
    ("dm_uuid", "dm_uuid"),
    ("parent_major_minor", "parent_major_minor"),
    ("parent_model", "parent_model"),
    ("parent_transport", "parent_transport"),
    ("parent_size_bytes", "parent_size_bytes"),
    ("parent_removable", "parent_removable"),
    ("card_identity_sha256", "card_identity_sha256"),
    ("swap_was_active", "swap_was_active"),
    ("ownership_phase", "ownership_phase"),
)


def _recovery_state_identity_matches(expected, observed):
    """Recovery stages may advance; their immutable ownership cannot change."""
    if not isinstance(expected, dict) or not isinstance(observed, dict) or not all(
            field in expected and field in observed and
            type(expected[field]) is type(observed[field]) and
            expected[field] == observed[field]
            for field, _ in RECOVERY_RECORD_BINDINGS):
        return False
    # A new SWAPSPACE2 trial cannot downgrade its permanent no-header-write
    # claim by deleting/changing the field in a later recovery state record.
    # Two absent fields identify historical pre-migration journals only.
    if ("raw_header_preservation_required" in expected or
            "raw_header_preservation_required" in observed) and (
            expected.get("raw_header_preservation_required") is not True or
            observed.get("raw_header_preservation_required") is not True):
        return False
    if "unrelated_swapfiles" in expected or "unrelated_swapfiles" in observed:
        return expected.get("unrelated_swapfiles") == observed.get(
            "unrelated_swapfiles")
    return True


def _require_recovery_results_binding(state, results):
    """Refuse stale or cross-run results before touching recovery resources."""
    if not isinstance(results, dict):
        raise ProbeError("saved physical results record is not an object")
    if state.get("virtual_device_only") is True and (
            results.get("virtual_device_only") is not True or
            results.get("evidence_class") !=
            "VIRTUAL_DEVICE_ONLY_NOT_PHYSICAL_QUALIFICATION"):
        raise ProbeError("virtual-device recovery evidence label is inconsistent")
    if state.get("algorithm_real_swap") is True and (
            results.get("algorithm_real_swap") is not True or
            state.get("development_only") is not True):
        raise ProbeError("real-swap recovery mode differs from saved results")
    for state_field, result_field in RECOVERY_RECORD_BINDINGS:
        if state_field not in state or result_field not in results or (
                type(state[state_field]) is not type(results[result_field]) or
                state[state_field] != results[result_field]):
            raise ProbeError(
                "saved physical results/state binding mismatch: "
                f"{result_field}; safe_next_step=inspect_records_read_only")
    if "unrelated_swapfiles" in state or "unrelated_swapfiles" in results:
        if state.get("unrelated_swapfiles") != results.get("unrelated_swapfiles"):
            raise ProbeError(
                "saved physical results/state binding mismatch: "
                "unrelated_swapfiles; safe_next_step=inspect_records_read_only")
        for swapfile in state.get("unrelated_swapfiles", []):
            _validate_saved_swapfile(swapfile)
    result_stage = results.get("final_recovery_state")
    ownership_phase = state["ownership_phase"]
    legacy_preclaim_recovery = (
        ownership_phase == LEGACY_PRECLAIM_RECOVERY_OWNERSHIP_PHASE
        and state.get("stage") == "BACKED_UP"
        and result_stage == "BACKED_UP")
    if (type(state.get("major")) is not int or
            type(state.get("minor")) is not int or
            type(state["source_sha"]) is not str or
            re.fullmatch(r"[0-9a-f]{40}", state["source_sha"]) is None or
            type(state["helper_git_sha"]) is not str or
            re.fullmatch(r"[0-9a-f]{40}", state["helper_git_sha"]) is None or
            type(state["helper_sha256"]) is not str or
            re.fullmatch(r"[0-9a-f]{64}", state["helper_sha256"]) is None or
            results.get("major_minor") !=
            f"{state['major']}:{state['minor']}" or
            results.get("development_only") is not (
                state.get("development_only") is True) or
            (ownership_phase not in {
                RUNTIME_OWNERSHIP_PHASE,
                RECOVERY_OWNERSHIP_PHASE,
                LEGACY_ACTIVE_RECOVERY_OWNERSHIP_PHASE,
            } and not legacy_preclaim_recovery)):
        raise ProbeError(
            "saved physical results/state identity or ownership phase "
            "is incomplete; safe_next_step=inspect_records_read_only")
    if result_stage not in {"PREPARED", "BACKED_UP", "ORACLE_PASS",
                            "RECOVERY_REQUIRED"} or (
            (state.get("stage") == "RECOVERY_REQUIRED") != (
                result_stage == "RECOVERY_REQUIRED")):
        raise ProbeError(
            "saved recovery publication phases disagree; "
            "safe_next_step=inspect_records_read_only")
    if state.get("stage") == "RECOVERY_REQUIRED" and (
            state.get("stage_before_recovery") not in {
                "PREPARED", "BACKED_UP", "SWAP_OFF", "HEADER_CLEAR_PENDING",
                "HEADER_CLEARED", "HEADER_RESTORE_PENDING", "SWZ_FORMATTED",
                "EXISTING_SWAP_READY", "MODULE_PENDING", "MODULE_OWNED",
                "MAPPED", "ORACLE_PASS"}):
        raise ProbeError(
            "saved RECOVERY_REQUIRED origin is incomplete; "
            "safe_next_step=inspect_records_read_only")


def recover(state_dir, device_arg, confirm_arg, lock_held=False,
            module_owned_by_process=False):
    state_dir = Path(state_dir)
    _validate_state_dir(state_dir)
    try:
        state = _load_unique_json((state_dir / STATE_NAME).read_bytes())
    except (OSError, ValueError) as exc:
        raise ProbeError("cannot load unambiguous saved physical state") from exc
    if not isinstance(state, dict) or not re.fullmatch(
            r"[0-9a-f]{32}", str(state.get("run_id", ""))):
        raise ProbeError("saved state lacks one-use run identity")
    preserve_header = state.get("raw_header_preservation_required") is True
    backup = None
    if not preserve_header:
        try:
            backup = (state_dir / BACKUP_NAME).read_bytes()
        except OSError as exc:
            raise ProbeError("legacy recovery header copy is unavailable") from exc
    _recovery_run_directory(state_dir, state["run_id"])
    if device_arg != confirm_arg or device_arg != state.get("device_arg"):
        raise ProbeError(
            "recovery requires the exact originally confirmed device path; "
            "safe_next_step=inspect_records_read_only")
    if (not preserve_header and
            (len(backup) != PAGE_BYTES or hashlib.sha256(backup).hexdigest() !=
             state.get("header_sha256"))):
        raise ProbeError("legacy original header is missing or digest-mismatched")
    if state.get("stage") == "COMPLETE":
        raise ProbeError(
            "saved recovery is already COMPLETE; "
            "safe_next_step=inspect_records_read_only")
    try:
        results = _load_unique_json((state_dir / RESULTS_NAME).read_bytes())
    except (OSError, ValueError) as exc:
        raise ProbeError(
            "saved physical results record missing or unreadable; "
            "safe_next_step=inspect_records_read_only") from exc
    # Normal mode restores an originally active, zero-use swap partition.
    # The distinct development-only physical data-path smoke is admitted only
    # when the card was already inactive and recovery must leave it inactive.
    swap_was_active = state.get("swap_was_active")
    development_only = state.get("development_only") is True
    if swap_was_active is False:
        if not development_only:
            raise ProbeError(
                "recovery_original_swap_active expected=true observed=false; "
                "restoration_stage=not_attempted "
                "ownership_marker_action=not_attempted; manual recovery required")
        if (state.get("development_scope") != DEVELOPMENT_SCOPE or
                any(state.get(field) is not None for field in (
                    "swap_path", "swap_size_kib", "swap_priority",
                    "swap_used_kib"))):
            raise ProbeError(
                "recovery_original_swap_active expected=canonical_inactive_"
                "development_state observed=invalid; restoration_stage="
                "not_attempted ownership_marker_action=not_attempted; "
                "manual recovery required")
    elif swap_was_active is not True:
        observed = ("missing" if "swap_was_active" not in state else "invalid")
        raise ProbeError(
            "recovery_original_swap_active expected=true "
            f"observed={observed}; restoration_stage=not_attempted "
            "ownership_marker_action=not_attempted; manual recovery required")
    if swap_was_active is True and (
            type(state.get("swap_size_kib")) is not int or
            state["swap_size_kib"] <= 0):
        observed = "missing" if "swap_size_kib" not in state else "invalid"
        raise ProbeError(
            "recovery_original_swap_size_kib expected=positive_integer "
            f"observed={observed}; restoration_stage=not_attempted "
            "ownership_marker_action=not_attempted; manual recovery required")
    saved_size_bytes = state.get("size_bytes")
    if type(saved_size_bytes) is not int or saved_size_bytes <= 0:
        observed = "missing" if "size_bytes" not in state else "invalid"
        raise ProbeError(
            "recovery_saved_device_size_bytes expected=positive_integer "
            f"observed={observed}; restoration_stage=not_attempted "
            "ownership_marker_action=not_attempted; manual recovery required")
    if swap_was_active is True and state["swap_size_kib"] > saved_size_bytes // 1024:
        raise ProbeError(
            "recovery_original_swap_size_kib expected=within_saved_device "
            "observed=exceeds_saved_device; restoration_stage=not_attempted "
            "ownership_marker_action=not_attempted; manual recovery required")
    if swap_was_active is True and type(state.get("swap_priority")) is not int:
        observed = "missing" if "swap_priority" not in state else "invalid"
        raise ProbeError(
            "recovery_original_swap_priority expected=integer "
            f"observed={observed}; restoration_stage=not_attempted "
            "ownership_marker_action=not_attempted; manual recovery required")
    if swap_was_active is True and not LINUX_SWAP_PRIORITY_MIN <= state["swap_priority"] <= \
            LINUX_SWAP_PRIORITY_MAX:
        raise ProbeError(
            "recovery_original_swap_priority expected=-1..32767 "
            "observed=out_of_range; restoration_stage=not_attempted "
            "ownership_marker_action=not_attempted; manual recovery required")
    if state.get("module_ownership") not in {
            "NOT_STARTED", "MODULE_PENDING", "MODULE_OWNED"}:
        raise ProbeError("saved module ownership is unknown; manual review required")
    _validate_owned_mapper_identity(state)
    _require_recovery_results_binding(state, results)
    lock_fd = None if lock_held else _partition_lock(
        state["partuuid"], base=state_dir.parent)
    try:
        base = _recovery_base(state)
        try:
            marker = _load_unique_json(
                (base / f"partition-{state['partuuid']}.active").read_bytes())
        except (OSError, ValueError) as exc:
            raise ProbeError("cannot prove this run owns partition recovery") from exc
        if marker != {"run_id": state["run_id"],
                      "partuuid": state["partuuid"],
                      "major": state["major"], "minor": state["minor"]}:
            raise ProbeError("saved recovery state does not own partition marker")
        target = inspect_target_identity_for_recovery(
            state, device_arg, confirm_arg)
        target["development_only"] = development_only
        target["algorithm_real_swap"] = state.get("algorithm_real_swap") is True
        _recovery_base(target)
        module_present = Path("/sys/module/dm_swapz").exists()
        if module_present and state["module_ownership"] != "MODULE_OWNED":
            raise ProbeError(
                "module load interrupted or foreign; manual recovery required")
        if module_present and not module_owned_by_process:
            raise ProbeError(
                "persisted module ownership cannot prove load continuity; "
                "manual recovery required")
        if _mapper_exists(state):
            _prepare_owned_mapper_removal(state, target)
            _run(["dmsetup", "remove", state["dm_name"]], timeout=60)
        if _mapper_exists(state):
            raise ProbeError("helper-owned mapper remains after removal")
        state["mapper_removal_succeeded"] = True
        if state["module_ownership"] == "MODULE_OWNED" and module_present:
            parameter = Path(
                "/sys/module/dm_swapz/parameters/allow_physical_backing")
            if not parameter.is_file() or (
                    parameter.read_text().strip().lower() not in {"y", "1"}):
                raise ProbeError("module identity/physical opt-in cannot be proven")
            _run(["rmmod", "dm_swapz"], timeout=30)
        if Path("/sys/module/dm_swapz").exists():
            raise ProbeError("dm_swapz remains loaded after helper cleanup")
        state["module_cleanup_succeeded"] = True
        _save_state(state_dir, state)
        if (state.get("development_only") is True and
                state.get("algorithm_real_swap") is True):
            _restore_development_swapfiles(state)
        if _holder_names(target["major"], target["minor"]):
            raise ProbeError("recovery refused while partition has holders")
        if _mountinfo_has_device(target["major"], target["minor"]):
            raise ProbeError("recovery refused while partition is mounted")

        current_header = _read_block0(target["device"], target)
        active = _active_swap_for(target["major"], target["minor"])
        if swap_was_active is False and active is not None:
            raise ProbeError(
                "development cleanup refused because the originally inactive "
                "partition became active swap")
        if preserve_header:
            current_digest = hashlib.sha256(current_header).hexdigest()
            if current_digest != state.get("header_sha256"):
                raise ProbeError(
                    "ordinary SWAPSPACE2 header changed; raw header writes are "
                    "forbidden for this trial")
            state["final_block0_sha256"] = current_digest
        else:
            # Historical pre-migration journals alone may restore their saved
            # block-zero image. No newly created run reaches this branch.
            if active is not None and current_header != backup:
                raise ProbeError("recovery refused to rewrite active swap")
            _validate_recovery_header(
                current_header, backup, state, target["size_bytes"])
            if current_header != backup:
                if active is not None:
                    raise ProbeError("cannot restore header while swap is active")
                if _recovery_header_stage(state) != "HEADER_RESTORE_PENDING":
                    source_stage = _recovery_header_stage(state)
                    state["header_restore_source_stage"] = source_stage
                    state["header_restore_source_sha256"] = hashlib.sha256(
                        current_header).hexdigest()
                    state["header_restore_source_hex"] = current_header.hex()
                    state["stage_before_recovery"] = "HEADER_RESTORE_PENDING"
                    state["stage"] = "HEADER_RESTORE_PENDING"
                    _save_state(state_dir, state)
                _verify_target_identity(target)
                _write_block0(target["device"], backup, target,
                              expected_current=current_header)
            if _read_block0(target["device"], target) != backup:
                raise ProbeError(
                    "legacy original 4 KiB header not restored exactly")
            state["final_block0_sha256"] = hashlib.sha256(backup).hexdigest()

        if swap_was_active is True:
            if _active_swap_for(target["major"], target["minor"]) is None:
                _verify_target_identity(target)
                if state.get("swap_priority", -1) >= 0:
                    _run(["swapon", "--priority", str(state["swap_priority"]),
                          target["device"]], timeout=60)
                else:
                    _run(["swapon", target["device"]], timeout=60)
            active = _active_swap_for(target["major"], target["minor"])
            if active is None or active["size_kib"] != state["swap_size_kib"] or (
                    active["priority"] != state["swap_priority"]):
                raise ProbeError(
                    "original swap major, size or priority was not restored")
        elif _active_swap_for(target["major"], target["minor"]) is not None:
            raise ProbeError(
                "development recovery expected the partition to remain inactive")
        # COMPLETE and marker release are cleanup claims. Keep ownership
        # until one current restored-state sample verifies them.
        cleanup_observation = _final_observations(
            results, state_dir, state, target)
        cleanup_error = _final_cleanup_evidence_error(cleanup_observation)
        if cleanup_error is not None:
            state["stage_before_recovery"] = state.get("stage")
            state["stage"] = "RECOVERY_REQUIRED"
            state["recovery_error"] = (
                "final cleanup evidence expected=verified observed="
                + cleanup_error)
            _save_state(state_dir, state)
            results["final_recovery_state"] = state["stage"]
            results["recovery_error"] = state["recovery_error"]
            results["end_timestamp"] = _utc_timestamp()
            _save_results(state_dir, results)
            raise ProbeError(state["recovery_error"])
        state["stage"] = "COMPLETE"
        _save_state(state_dir, state)
        _release_partition_ownership(state)
        # Marker unlink + directory fsync is the only state transition after
        # the verified cleanup sample. Do not perform another fallible
        # swap/header/mapper observation after ownership is released.
        results["active_partition_marker_present"] = False
        results["final_recovery_state"] = state["stage"]
        results["end_timestamp"] = _utc_timestamp()
        _save_results(state_dir, results)
        return state
    finally:
        if lock_fd is not None:
            _close_fd_preserving_active_error(lock_fd)


def recover_pending_algorithm_trial():
    """Clean one exact same-boot run-owned trial, never an unidentified partition."""
    base = _algorithm_runtime_base()
    markers = sorted(base.glob("partition-*.active"))
    if not markers:
        print("PHYSICAL_AUTO_RECOVERY=NO_PENDING")
        return False
    if len(markers) != 1:
        raise RecoveryRequiredError(
            "multiple recovery markers exist; inspect journals read-only")
    marker_path = markers[0]
    info = marker_path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or
            info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600 or
            re.fullmatch(r"partition-[0-9a-f-]{8,64}\.active",
                         marker_path.name) is None):
        raise RecoveryRequiredError(
            "active recovery marker is not a trusted root-owned record")
    try:
        marker = _load_unique_json(marker_path.read_bytes())
        run_id = marker["run_id"]
        partuuid = marker["partuuid"]
        if (not isinstance(run_id, str) or
                re.fullmatch(r"[0-9a-f]{32}", run_id) is None or
                not isinstance(partuuid, str) or
                marker_path.name != f"partition-{partuuid}.active"):
            raise ValueError("marker identity invalid")
        state_dir = _recovery_run_directory(
            base / f"swapz-physical-{run_id}", run_id)
        _validate_state_dir(state_dir)
        state = _load_unique_json((state_dir / STATE_NAME).read_bytes())
        if (not isinstance(state, dict) or
                state.get("run_id") != run_id or
                state.get("partuuid") != partuuid or
                state.get("development_only") is not True or
                state.get("algorithm_real_swap") is not True or
                state.get("ownership_phase") not in {
                    RECOVERY_OWNERSHIP_PHASE,
                    LEGACY_ACTIVE_RECOVERY_OWNERSHIP_PHASE,
                } or marker != {
                    "run_id": run_id, "partuuid": partuuid,
                    "major": state.get("major"), "minor": state.get("minor")
                }):
            raise ValueError("not an owned development real-swap journal")
        device_arg = state.get("device_arg")
        if (not isinstance(device_arg, str) or not (
                device_arg.startswith("/dev/disk/by-partuuid/") or
                device_arg.startswith("/dev/disk/by-uuid/")) or
                device_arg != (
                    "/dev/disk/by-partuuid/" if
                    device_arg.startswith("/dev/disk/by-partuuid/") else
                    "/dev/disk/by-uuid/") + Path(device_arg).name):
            raise ValueError("original confirmed device selector invalid")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RecoveryRequiredError(
            "pending recovery journal is ambiguous; inspect read-only") from exc
    try:
        recovered = recover(state_dir, device_arg, device_arg)
    except (ProbeError, OSError) as exc:
        raise RecoveryRequiredError(
            "automatic recovery refused; inspect journal: "
            + _bounded_text(exc)) from exc
    if recovered.get("stage") != "COMPLETE":
        raise RecoveryRequiredError(
            "automatic recovery did not complete; inspect saved journal")
    print("PHYSICAL_AUTO_RECOVERY=COMPLETE restored_previous_trial")
    return True


def inspect_target_identity_for_recovery(state, device_arg, confirm_arg):
    if device_arg != confirm_arg or device_arg != state.get("device_arg"):
        raise ProbeError("recovery requires the exact originally confirmed device path")
    # The confirmed swap-filesystem UUID link may have vanished after
    # formatting. Resolve only the previously saved canonical block path.
    device = state.get("device")
    if not isinstance(device, str) or not device.startswith("/dev/"):
        raise ProbeError("recovery state lacks a canonical block device")
    major, minor = block_identity(device)
    if (major, minor) != (state.get("major"), state.get("minor")):
        raise ProbeError("recovery device identity does not match the saved state")
    try:
        size = int(_run(["blockdev", "--getsize64", device]).stdout.strip())
    except ValueError as exc:
        raise ProbeError("cannot verify selected partition size during recovery") from exc
    if size != state.get("size_bytes"):
        raise ProbeError("recovery partition size does not match saved state")
    expected_partuuid = state.get("partuuid")
    if not isinstance(expected_partuuid, str) or not expected_partuuid:
        raise ProbeError("recovery state lacks a persistent PARTUUID")
    partuuid, partition_size = _partition_identity(device)
    if (partuuid != expected_partuuid or partition_size != size):
        raise ProbeError(
            f"recovery_partuuid_size expected=({expected_partuuid}, {size}) "
            f"observed=({partuuid}, {partition_size})")
    # Old durable recovery records may predate parent recording; do not
    # prevent emergency restoration solely because the field was not saved.
    parent = _physical_parent_identity(major, minor)
    if state.get("parent_major_minor") is not None and (
            parent != state["parent_major_minor"]):
        raise ProbeError(
            f"recovery_parent_major_minor "
            f"expected={state['parent_major_minor']!r} observed={parent!r}")
    card_identity = None
    if state.get("card_identity_sha256") is not None:
        card_identity = _campaign_card_identity(device, parent)
        if (card_identity["sha256"] != state["card_identity_sha256"] or
                card_identity["model"] != state.get("parent_model") or
                card_identity["transport"] != state.get("parent_transport")):
            raise ProbeError(
                "recovery_parent_card_identity does not match saved state")
    return {
        "device": device,
        "major": major,
        "minor": minor,
        "parent_major_minor": parent,
        **({"virtual_device_only": True}
           if state.get("virtual_device_only") is True else {}),
        **({
            "parent_model": card_identity["model"],
            "parent_transport": card_identity["transport"],
            "parent_size_bytes": card_identity["parent_size_bytes"],
            "parent_removable": card_identity["parent_removable"],
            "card_identity_sha256": card_identity["sha256"],
        } if card_identity is not None else {}),
        "size_bytes": size,
        "partuuid": partuuid,
    }


def _prepare_state(target, state_dir, evidence, review):
    """Create the ownership record; block zero is identity-only and immutable."""
    dm_name, dm_uuid = _allocate_dm_identity()
    state_dir = _recovery_run_directory(state_dir, review["run_id"])
    if state_dir.exists() or state_dir.is_symlink():
        raise ProbeError("one-use state run directory already exists")
    _verify_target_identity(target)
    if _read_block0(target["device"], target) != target["header"]:
        raise ProbeError("original header changed since device review")
    state_dir.mkdir(mode=0o700)  # Deliberately no recursive parent creation.
    _fsync_directory(state_dir.parent)
    info = state_dir.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or (
            stat.S_IMODE(info.st_mode) != 0o700):
        raise ProbeError("state run directory is not root-owned mode 0700")
    # New trials never save or restore block zero. The digest below detects
    # any violation and forces read-only inspection.
    state = {
        "device_arg": target["device_arg"],
        "device": target["device"],
        "major": target["major"],
        "minor": target["minor"],
        "parent_major_minor": target.get("parent_major_minor"),
        "parent_model": target.get("parent_model"),
        "parent_transport": target.get("parent_transport"),
        "parent_size_bytes": target.get("parent_size_bytes"),
        "parent_removable": target.get("parent_removable"),
        "card_identity_sha256": target.get("card_identity_sha256"),
        "size_bytes": target["size_bytes"],
        "partuuid": target["partuuid"],
        "header_sha256": hashlib.sha256(target["header"]).hexdigest(),
        # This durable invariant distinguishes all new non-formatting trials
        # from historical recovery records that had replaced block zero.
        "raw_header_preservation_required": True,
        "swap_was_active": target.get("swap_was_active", True),
        "swap_path": target.get("swap_path"),
        "swap_priority": target.get("swap_priority"),
        "swap_size_kib": target.get("swap_size_kib"),
        "swap_used_kib": target.get("swap_used_kib"),
        "unrelated_swapfiles": target.get("unrelated_swapfiles", []),
        "development_only": evidence.get("development_only") is True,
        **({"virtual_device_only": True}
           if evidence.get("virtual_device_only") is True else {}),
        **({"algorithm_real_swap": True}
           if evidence.get("algorithm_real_swap") is True else {}),
        "development_scope": (DEVELOPMENT_SCOPE
                              if evidence.get("development_only") is True
                              else None),
        "source_sha": evidence["source_sha"],
        "helper_git_sha": evidence["head"],
        "helper_sha256": evidence["helper_sha256"],
        "host_report_count": evidence.get("pass_reports"),
        "reviewer": review.get("reviewer"),
        "run_id": review["run_id"],
        "module_ownership": "NOT_STARTED",
        "ownership_phase": RUNTIME_OWNERSHIP_PHASE,
        "dm_name": dm_name,
        "dm_uuid": dm_uuid,
        "stage": "PREPARED",
    }
    _save_state(state_dir, state)
    return state, state_dir


def _prepare_owned_mapper_removal(state, target):
    """Permit DM removal only after normal swapoff of the run-owned mapper.

    No active-page state is inferred from a successful command alone; the
    exact mapper is independently observed inactive before removal.
    """
    mapper = _verify_owned_mapper(state, target)
    if state.get("algorithm_real_swap") is not True:
        return
    if state.get("development_only") is not True:
        raise ProbeError("real-swap mode has invalid recovery scope")
    mapper_device = block_identity(mapper)
    if _active_swap_for(*mapper_device) is not None:
        _run(["swapoff", "--", mapper], timeout=120)
        if _active_swap_for(*mapper_device) is not None:
            raise ProbeError("owned mapper remains active after swapoff")


def _algorithm_pageout_event(worker, expected_prefix):
    """Read one bounded, phase-specific worker record without waiting forever."""
    if worker.stdout is None:
        raise ProbeError("real-swap oracle stdout pipe is unavailable")
    ready, _writable, _exceptional = select.select(
        [worker.stdout], [], [], 30)
    if not ready:
        raise ProbeError("real-swap oracle phase timed out")
    line = worker.stdout.readline()
    if (not line.startswith(expected_prefix) or not line.endswith("\n") or
            len(line) > 512):
        raise ProbeError("real-swap oracle returned missing or malformed phase")
    try:
        record = _load_unique_json(
            line[len(expected_prefix):-1].encode("ascii"))
    except (UnicodeError, ValueError) as exc:
        raise ProbeError("real-swap oracle record is not canonical JSON") from exc
    if not isinstance(record, dict):
        raise ProbeError("real-swap oracle phase record is not an object")
    return record


def _algorithm_pageout_oracle_snapshot(state_dir, source_sha):
    """Execute only source-bound oracle bytes from the private run directory."""
    relative = "tests/tools/algorithm-pageout-oracle.py"
    original = ROOT / relative
    try:
        payload = original.read_bytes()
        recorded = _git_result("show", f"{source_sha}:{relative}").stdout.encode(
            "utf-8")
    except (OSError, UnicodeError, ProbeError) as exc:
        raise ProbeError("real-swap oracle source identity unavailable") from exc
    if not payload or payload != recorded or len(payload) > 65536:
        raise ProbeError("real-swap oracle differs from the exact source commit")
    snapshot = state_dir / "algorithm-pageout-oracle.py"
    descriptor = os.open(
        snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
        os.O_NOFOLLOW | os.O_CLOEXEC, 0o400)
    try:
        _write_all(descriptor, payload)
        os.fsync(descriptor)
    finally:
        _close_fd_preserving_active_error(descriptor)
    _fsync_directory(state_dir)
    if snapshot.read_bytes() != payload:
        raise ProbeError("private real-swap oracle source changed after snapshot")
    return snapshot, hashlib.sha256(payload).hexdigest()


def _run_algorithm_live_swap_oracle(mapper, state, target, state_dir):
    """Prove Linux anonymous pageout/pagein through the exact owned mapper.

    The worker's READY event alone is not evidence. Require positive exact
    mapper swap usage and lower I/O before accepting byte-exact readback.
    Recovery, not this function, owns swapoff and mapper destruction.
    """
    if _verify_owned_mapper(state, target) != mapper:
        raise ProbeError("owned mapper changed before real swap")
    mapper_device = block_identity(mapper)
    if _active_swap_for(*mapper_device) is not None:
        raise ProbeError("owned mapper unexpectedly active before real-swap setup")
    try:
        meminfo = Path("/proc/meminfo").read_text(encoding="ascii")
        match = re.search(r"(?m)^MemAvailable:\s+(\d+) kB$", meminfo)
    except (OSError, UnicodeError) as exc:
        raise ProbeError("cannot prove safe host memory headroom") from exc
    if not match or int(match.group(1)) < 512 * 1024:
        raise ProbeError("insufficient host memory headroom for bounded real swap")

    private_oracle, oracle_sha256 = _algorithm_pageout_oracle_snapshot(
        state_dir, state["source_sha"])
    # Oracle pinning may take time. Recheck the exact owned DM identity
    # immediately before mkswap touches the mapper's visible block zero.
    if (_verify_owned_mapper(state, target) != mapper or
            block_identity(mapper) != mapper_device):
        raise ProbeError("owned mapper changed before real-swap formatting")
    # A run-owned mapper needs no force override: preserve mkswap's
    # partition-table and geometry refusal checks before activation.
    _run(["mkswap", "--", mapper], timeout=30)
    # The state already durably recorded the real-swap mode before mutation.
    # A failure after swapon must always retain the normal swapoff path.
    _run(["swapon", "--priority", "32767", "--", mapper], timeout=30)
    active = _active_swap_for(*mapper_device)
    if active is None or active["used_kib"] != 0:
        raise ProbeError("run-owned swap mapper activation is unproven")
    lower_before = _block_stat_snapshot(target)
    if lower_before.get("available") is not True:
        raise ProbeError("cannot sample physical I/O before anonymous pageout")

    worker = None
    try:
        worker = subprocess.Popen(
            [sys.executable, "-I", "-B", str(private_oracle),
             "--seed", state["run_id"]],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1,
            start_new_session=True)
        expected_pages = 2048
        expected_bytes = expected_pages * PAGE_BYTES
        ready = _algorithm_pageout_event(worker, "ALGORITHM_PAGEOUT_READY=")
        if (set(ready) != {"pages", "bytes", "expected_sha256"} or
                ready["pages"] != expected_pages or
                ready["bytes"] != expected_bytes or
                not isinstance(ready["expected_sha256"], str) or
                re.fullmatch(r"[0-9a-f]{64}", ready["expected_sha256"]) is None):
            raise ProbeError("real-swap pageout oracle readiness is invalid")

        deadline = time.monotonic() + 10.0
        used_swap_kib = 0
        while time.monotonic() < deadline:
            if _verify_owned_mapper(state, target) != mapper or (
                    block_identity(mapper) != mapper_device):
                raise ProbeError("run-owned mapper identity changed during pageout")
            observed = _active_swap_for(*mapper_device)
            if observed is None:
                raise ProbeError("owned mapper lost swap activation during pageout")
            used_swap_kib = observed["used_kib"]
            if used_swap_kib > 0:
                break
            time.sleep(0.05)
        lower_after_pageout = _block_stat_snapshot(target)
        pageout_delta = _lower_io_delta(
            lower_before, lower_after_pageout)
        if used_swap_kib <= 0 or pageout_delta["lower_write_bytes"] <= 0:
            raise ProbeError(
                "anonymous pageout did not prove exact mapper use and backing writes")

        if worker.stdin is None:
            raise ProbeError("real-swap oracle command pipe is unavailable")
        worker.stdin.write("VERIFY\n")
        worker.stdin.flush()
        verified = _algorithm_pageout_event(
            worker, "ALGORITHM_PAGEOUT_VERIFIED=")
        if (set(verified) != {
                "pages", "bytes", "mismatches", "actual_sha256",
                "expected_sha256"} or
                verified["pages"] != expected_pages or
                verified["bytes"] != expected_bytes or
                verified["mismatches"] != 0 or
                verified["actual_sha256"] != ready["expected_sha256"] or
                verified["expected_sha256"] != ready["expected_sha256"]):
            raise ProbeError("real-swap anonymous-page readback is not byte-exact")
        if worker.wait(timeout=30) != 0:
            raise ProbeError("real-swap oracle terminated unsuccessfully")
        readback_delta = _lower_io_delta(
            lower_after_pageout, _block_stat_snapshot(target))
        if readback_delta["lower_read_bytes"] <= 0:
            raise ProbeError("anonymous-page verification did not prove lower reads")
        return {
            "status": "PASS",
            "oracle_sha256": oracle_sha256,
            "verified_pages": expected_pages,
            "verified_bytes": expected_bytes,
            "byte_mismatches": 0,
            "mapper_used_kib_after_pageout": used_swap_kib,
            "lower_write_bytes": pageout_delta["lower_write_bytes"],
            "lower_read_bytes": readback_delta["lower_read_bytes"],
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProbeError(
            "bounded anonymous swap oracle failed to execute or finish") from exc
    finally:
        if worker is not None:
            if worker.poll() is None:
                try:
                    worker.kill()
                except ProcessLookupError:
                    # A worker may exit between poll() and kill().
                    pass
            worker.wait(timeout=15)
            if worker.stdin is not None:
                worker.stdin.close()
            if worker.stdout is not None:
                worker.stdout.close()


def _operator_keep_swapz_active_after_pass():
    """Ask only after a successful real-swap oracle; default is safe teardown."""
    try:
        choice = input(
            "swapz tests passed. Keep swapz active instead of restoring "
            "ordinary swap? [y/N] ")
    except EOFError:
        return False
    return choice.strip().lower() in {"y", "yes"}


def _verify_kept_swapz_active(state, target, mapper):
    """Verify the exact successful development mapper before leaving it active."""
    _verify_target_identity(target)
    if _read_block0(target["device"], target) != target["header"]:
        raise ProbeError("ordinary SWAPSPACE2 header changed before keep-active")
    if _active_swap_for(target["major"], target["minor"]) is not None:
        raise ProbeError("raw swap partition became active while swapz mapper is kept")
    if _verify_owned_mapper(state, target) != mapper:
        raise ProbeError("owned swapz mapper changed before keep-active")
    mapper_device = block_identity(mapper)
    active = _active_swap_for(*mapper_device)
    if active is None:
        raise ProbeError("owned swapz mapper is not active swap after successful test")
    if active["priority"] != 32767:
        raise ProbeError("owned swapz mapper priority changed before keep-active")
    if (state.get("module_ownership") != "MODULE_OWNED" or
            not Path("/sys/module/dm_swapz").is_dir()):
        raise ProbeError("owned dm_swapz module is unavailable before keep-active")
    return active


def _remove_test_objects(state, state_dir):
    return recover(state_dir, state["device_arg"], state["device_arg"],
                   lock_held=True, module_owned_by_process=True)


def _final_physical_oracle_evidence_error(results, state, target,
                                          evidence, review, phases, oracle,
                                          mapper, development_only,
                                          algorithm_real_swap=False):
    """Fail closed on missing, rewritten, or unbound durable oracle evidence."""
    expected_header_sha256 = hashlib.sha256(target["header"]).hexdigest()
    if (not isinstance(mapper, str) or not mapper.startswith("/dev/mapper/") or
            not phases or len(phases[0][1]) != 2 or
            phases[0][1][0] != "--expect-dm-uuid"):
        return "internal_expected_mapper_identity_invalid"
    expected_dm_name = Path(mapper).name
    expected_dm_uuid = phases[0][1][1]
    expected_original_swap_row = ({
        "path": target["swap_path"],
        "kind": "partition",
        "size_kib": target["swap_size_kib"],
        "used_kib": target["swap_used_kib"],
        "priority": target["swap_priority"],
    } if target.get("swap_was_active") is True else None)
    bindings = {
        "source_commit_sha": evidence["source_sha"],
        "current_git_head": evidence["head"],
        "helper_git_sha": evidence["head"],
        "helper_sha256": evidence["helper_sha256"],
        "artifact_sha256": evidence["artifact_digests"],
        "live_artifact_sha256_before_run": evidence["artifact_digests"],
        "live_artifact_sha256_before_mutation": evidence["artifact_digests"],
        "run_id": review["run_id"],
        "device_uuid_path": target["device_arg"],
        "partuuid": target["partuuid"],
        "major_minor": f"{target['major']}:{target['minor']}",
        "device_size_bytes": target["size_bytes"],
        "original_header_sha256": expected_header_sha256,
        "original_swap_row": expected_original_swap_row,
        "unrelated_swapfiles": target.get("unrelated_swapfiles", []),
        "dm_name": expected_dm_name,
        "dm_uuid": expected_dm_uuid,
        "development_only": development_only,
        "schema": ("swapz-physical-development-results-v1"
                   if development_only else "swapz-physical-results-v1"),
        "scope": DEVELOPMENT_SCOPE if development_only else EXPECTED_SCOPE,
        "approval_mode": review["approval_mode"],
        "reviewer": review["reviewer"],
        "linux_swap_activation_tested": False if development_only else None,
        "physical_media_acceptance": False if development_only else None,
        "production_qualification": False if development_only else None,
        "evidence_class": ("DEVELOPMENT_ONLY_NOT_PHYSICAL_QUALIFICATION"
                           if development_only else "PHYSICAL_CORRECTNESS_SMOKE"),
    }
    if development_only:
        bindings["development_test_evidence"] = evidence.get(
            "development_evidence")
    else:
        bindings.update({
            "qualified_production_source_sha": evidence["source_sha"],
            "qualified_artifact_sha256": evidence["artifact_digests"],
            "qualification_evidence": {
                "latest_source_reports": evidence["latest_source_reports"],
                "earlier_matching_artifact_reports": evidence[
                    "prior_matching_reports"],
                "total_distinct_matching_reports": evidence["pass_reports"],
            },
        })
    if algorithm_real_swap:
        bindings["algorithm_real_swap"] = True
        bindings["linux_swap_activation_tested"] = True
    for field, expected in bindings.items():
        if results.get(field) != expected:
            return f"{field}_mismatch"
    if algorithm_real_swap:
        record = results.get("algorithm_live_swap")
        required = ("verified_pages", "verified_bytes",
                    "mapper_used_kib_after_pageout", "lower_write_bytes",
                    "lower_read_bytes")
        if (not isinstance(record, dict) or record.get("status") != "PASS" or
                record.get("byte_mismatches") != 0 or
                any(type(record.get(key)) is not int or record[key] <= 0
                    for key in required) or
                record["verified_bytes"] != record["verified_pages"] * PAGE_BYTES or
                record["verified_pages"] != 2048 or
                not isinstance(record.get("oracle_sha256"), str) or
                re.fullmatch(r"[0-9a-f]{64}", record["oracle_sha256"]) is None):
            return "algorithm_real_swap_evidence_missing_or_invalid"
    saved_bindings = {
        "device_arg": target["device_arg"],
        "device": target["device"],
        "major": target["major"],
        "minor": target["minor"],
        "parent_major_minor": target["parent_major_minor"],
        "parent_model": target["parent_model"],
        "parent_transport": target["parent_transport"],
        "parent_size_bytes": target["parent_size_bytes"],
        "parent_removable": target["parent_removable"],
        "card_identity_sha256": target["card_identity_sha256"],
        "size_bytes": target["size_bytes"],
        "partuuid": target["partuuid"],
        "header_sha256": expected_header_sha256,
        "swap_was_active": target["swap_was_active"],
        "swap_path": target["swap_path"],
        "swap_priority": target["swap_priority"],
        "swap_size_kib": target["swap_size_kib"],
        "swap_used_kib": target["swap_used_kib"],
        "unrelated_swapfiles": target.get("unrelated_swapfiles", []),
        "development_only": development_only,
        "development_scope": (
            DEVELOPMENT_SCOPE if development_only else None),
        "source_sha": evidence["source_sha"],
        "helper_git_sha": evidence["head"],
        "helper_sha256": evidence["helper_sha256"],
        "host_report_count": evidence.get("pass_reports"),
        "dm_name": expected_dm_name,
        "dm_uuid": expected_dm_uuid,
        "reviewer": review["reviewer"],
        "run_id": review["run_id"],
    }
    for field, expected in saved_bindings.items():
        if state.get(field) != expected:
            return f"saved_{field}_mismatch"
    expected_lower_parent = target["parent_major_minor"]
    expected_lower_source = (
        f"/sys/dev/block/{expected_lower_parent}/stat")
    if results.get("lower_io_source") != expected_lower_source:
        return "lower_io_source_mismatch"
    for field in ("block_stats_before", "block_stats_after"):
        snapshot = results.get(field)
        if (not isinstance(snapshot, dict) or
                snapshot.get("device_major_minor") != expected_lower_parent):
            return f"{field}_parent_mismatch"
    try:
        if not _mapper_inventory_unchanged(
                results.get("dm_inventory_before"),
                results.get("dm_inventory_after")):
            return "unrelated_mapper_inventory_changed"
    except ProbeError:
        return "invalid_mapper_inventory_evidence"
    if results.get("unrelated_mapper_inventory_unchanged") is not True:
        return "mapper_inventory_summary_mismatch"
    if results.get("oracle_suite") != "PHASES_PASS_RECOVERY_PENDING":
        return "unexpected_provisional_oracle_status"
    entries = results.get("physical_oracle_phases")
    if not isinstance(entries, list) or len(entries) != len(phases):
        return "missing_or_extra_phase"
    for index, ((phase, options), entry) in enumerate(zip(phases, entries)):
        if not isinstance(entry, dict):
            return f"phase_{index}_nonobject"
        # argv is persisted as JSON strings, while artifact snapshots may be
        # pathlib.Path objects. Compare the canonical serialized arguments.
        expected_argv = [str(value) for value in (oracle, mapper, *options)]
        if (entry.get("phase") != phase or
                entry.get("argv") != expected_argv):
            return f"phase_{index}_identity_or_arguments_mismatch"
        if (entry.get("status") != "PASS" or
                type(entry.get("return_code")) is not int or
                entry["return_code"] != 0 or
                entry.get("timed_out") is not False or
                entry.get("post_oracle_identity") != "PASS"):
            return f"phase_{index}_incomplete_or_failed"
        if (entry.get("stdout") != _expected_physical_oracle_stdout(options)
                or entry.get("stderr") != "" or
                "trace_error" in entry or "oracle_output_error" in entry):
            return f"phase_{index}_invalid_comparison_output"
        if (not _swapz_status_healthy(entry.get("dmsetup_status_before")) or
                not _swapz_status_healthy(entry.get("dmsetup_status_after"))):
            return f"phase_{index}_invalid_mapper_health"
        before_stats = entry.get("block_stats_before")
        after_stats = entry.get("block_stats_after")
        if (not isinstance(before_stats, dict) or
                not isinstance(after_stats, dict) or
                before_stats.get("device_major_minor") != expected_lower_parent or
                after_stats.get("device_major_minor") != expected_lower_parent):
            return f"phase_{index}_lower_parent_mismatch"
        try:
            lower_io_delta = _lower_io_delta(before_stats, after_stats)
        except ProbeError:
            return f"phase_{index}_invalid_lower_counters"
        if entry.get("lower_io_delta") != lower_io_delta:
            return f"phase_{index}_contradictory_lower_counters"
    if results.get("final_block0_sha256") != expected_header_sha256:
        return "restored_header_sha256_mismatch"
    if (results.get("final_mapper_present") is not False or
            results.get("final_module_present") is not False or
            results.get("active_partition_marker_present") is not False or
            results.get("run_claim_consumed") is not True):
        return "incomplete_cleanup_or_ownership"
    row = results.get("final_swap_row")
    for field in (
            "final_block0_error", "final_swap_error",
            "final_mapper_error", "dm_inventory_error"):
        if field in results:
            return f"{field}_retained"
    if development_only:
        if target.get("swap_was_active") is True:
            if (not isinstance(row, dict) or row.get("kind") != "partition"
                    or row.get("size_kib") != state.get("swap_size_kib")
                    or row.get("priority") != state.get("swap_priority")):
                return "development_original_swap_not_restored"
        elif row is not None or results.get("target_remains_inactive") is not True:
            return "development_backing_not_inactive"
    elif (not isinstance(row, dict) or row.get("kind") != "partition"
          or row.get("size_kib") != state.get("swap_size_kib")
          or row.get("priority") != state.get("swap_priority")
          or results.get("approval_consumed") is not True):
        return "production_swap_or_approval_not_restored"
    return None


def run_probe(device_arg, confirm_arg, state_dir_arg, review_path,
              development_only=False, algorithm_real_swap=False,
              algorithm_ram_evidence=None, algorithm_ram_nonce=None,
              virtual_device_only=False):
    if algorithm_real_swap and not development_only:
        raise ProbeError("real-swap algorithm mode requires development-only admission")
    if virtual_device_only and not (development_only and algorithm_real_swap):
        raise ProbeError("virtual-only mode requires development real-swap admission")
    if os.geteuid() != 0:
        raise ProbeError("run action requires root")
    start_timestamp = _utc_timestamp()
    if development_only:
        if not algorithm_real_swap:
            # Header-only development smoke retains the historical zero-row
            # contract. Real-swap mode uses a separately durable quiesce.
            require_development_formatter_inventory_clear()
        evidence = current_development_evidence(
            algorithm_ram_nonce, algorithm_ram_evidence,
            virtual_device_only=virtual_device_only)
        evidence["algorithm_real_swap"] = algorithm_real_swap
        evidence["virtual_device_only"] = virtual_device_only
        if algorithm_real_swap:
            target = inspect_target(
                device_arg, confirm_arg,
                allow_used_swap=True, allow_inactive_swap=True,
                allow_shared_root=True,
                virtual_device_only=virtual_device_only)
            _target_row, swapfiles = _development_swap_inventory_plan(target)
            target["unrelated_swapfiles"] = swapfiles
        else:
            target = inspect_target(
                device_arg, confirm_arg, allow_inactive_swap=True)
        if not algorithm_real_swap and target.get("swap_was_active") is not False:
            observed = ("missing" if "swap_was_active" not in target
                        else "active_or_invalid")
            raise ProbeError(
                "operation=inspect_target phase=preflight "
                "original_errno_or_exit=not_applicable "
                "expected=swap_was_active_false "
                f"observed={observed} "
                "safe_next_step=rerun_read_only_preflight")
    else:
        evidence = current_source_evidence()
        target = inspect_target(device_arg, confirm_arg)
        if target.get("swap_was_active") is not True:
            observed = ("missing" if "swap_was_active" not in target
                        else "inactive_or_invalid")
            raise ProbeError(
                "operation=inspect_target phase=preflight "
                "original_errno_or_exit=not_applicable "
                "expected=swap_was_active_true "
                f"observed={observed} "
                "safe_next_step=rerun_read_only_preflight")
    target["device_arg"] = device_arg
    target["development_only"] = development_only
    target["algorithm_real_swap"] = algorithm_real_swap
    _recovery_base(target)
    live_artifact_digests = _artifact_digests()
    if live_artifact_digests != evidence["artifact_digests"]:
        raise ProbeError("current build artifacts differ from admitted evidence")
    if development_only and algorithm_real_swap:
        _require_shared_root_development_plan(target, evidence)
    if development_only:
        review = {
            "reviewer": None,
            "run_id": secrets.token_hex(16),
            "approval_mode": "standing-owner-development",
        }
    else:
        review = validate_review(review_path, evidence, target)
    # The helper owns the dev run ID. Development trials use root-only /run
    # state; qualified legacy runs retain their explicit persistent directory.
    state_dir_arg = _select_run_directory(
        state_dir_arg, review["run_id"], development_only)
    _check_review_unconsumed(target, review["run_id"])
    for command in ("blockdev", "dmsetup", "insmod", "modprobe", "rmmod",
                    "swapoff", "swapon", "findmnt", "udevadm"):
        if not shutil.which(command):
            raise ProbeError(f"required command is missing: {command}")
    dm_inventory_before = _module_mapper_preflight()
    preflight_kernel = _kernel_swapz_messages(start_timestamp)
    _require_kernel_diagnostics(
        preflight_kernel, "preflight_kernel_diagnostics")
    preflight_block_stats = _block_stat_snapshot(target)
    if preflight_block_stats.get("available") is not True:
        raise ProbeError(
            "preflight_lower_io expected=available "
            f"observed={preflight_block_stats.get('error')}")

    lock_fd = _partition_lock(
        target["partuuid"], base=state_dir_arg.parent)
    try:
        # Burn the one-use run authorization before state preparation. A crash,
        # fsync failure or artifact-snapshot failure can never make it reusable.
        _burn_review(target, review["run_id"])
        state, state_dir = _prepare_state(
            target, state_dir_arg, evidence, review)
        results = {
            "schema": ("swapz-physical-development-results-v1"
                       if development_only else "swapz-physical-results-v1"),
            "evidence_class": (
                "VIRTUAL_DEVICE_ONLY_NOT_PHYSICAL_QUALIFICATION"
                if virtual_device_only else
                "DEVELOPMENT_ONLY_NOT_PHYSICAL_QUALIFICATION"
                if development_only else "PHYSICAL_CORRECTNESS_SMOKE"),
            "development_only": development_only,
            **({"virtual_device_only": True} if virtual_device_only else {}),
            "scope": (DEVELOPMENT_SCOPE if development_only else EXPECTED_SCOPE),
            "linux_swap_activation_tested": False if development_only else None,
            **({"algorithm_real_swap": True} if algorithm_real_swap else {}),
            "physical_media_acceptance": False if development_only else None,
            "production_qualification": False if development_only else None,
            "start_timestamp": start_timestamp,
            "end_timestamp": None,
            "current_git_head": evidence["head"],
            "source_commit_sha": evidence["source_sha"],
            **({"qualified_production_source_sha": evidence["source_sha"]}
               if not development_only else {}),
            "helper_git_sha": evidence["head"],
            "helper_sha256": evidence["helper_sha256"],
            "artifact_sha256": dict(evidence["artifact_digests"]),
            **({"qualified_artifact_sha256": dict(evidence["artifact_digests"])}
               if not development_only else {}),
            "live_artifact_sha256_before_run": dict(live_artifact_digests),
            "run_id": review["run_id"],
            "approval_mode": review["approval_mode"],
            "reviewer": review["reviewer"],
            "device_uuid_path": device_arg,
            "canonical_device": state["device"],
            "parent_major_minor": state["parent_major_minor"],
            "parent_model": state["parent_model"],
            "parent_transport": state["parent_transport"],
            "parent_size_bytes": state["parent_size_bytes"],
            "parent_removable": state["parent_removable"],
            "card_identity_sha256": state["card_identity_sha256"],
            "swap_was_active": state["swap_was_active"],
            "ownership_phase": state["ownership_phase"],
            "major_minor": f"{target['major']}:{target['minor']}",
            "partuuid": target["partuuid"],
            "device_size_bytes": target["size_bytes"],
            "original_header_sha256": hashlib.sha256(
                target["header"]).hexdigest(),
            "original_swap_row": ({
                "path": target["swap_path"],
                "kind": "partition",
                "size_kib": target["swap_size_kib"],
                "used_kib": target["swap_used_kib"],
                "priority": target["swap_priority"],
            } if target["swap_was_active"] else None),
            "unrelated_swapfiles": target.get("unrelated_swapfiles", []),
            "development_test_evidence": evidence.get("development_evidence"),
            "qualification_evidence": ({
                "latest_source_reports": evidence["latest_source_reports"],
                "earlier_matching_artifact_reports": evidence[
                    "prior_matching_reports"],
                "total_distinct_matching_reports": evidence["pass_reports"],
            } if not development_only else None),
            "dm_name": state["dm_name"],
            "dm_uuid": state["dm_uuid"],
            "dm_inventory_before": dm_inventory_before,
            "kernel_diagnostics_preflight": preflight_kernel,
            "block_stats_before": preflight_block_stats,
            "lower_io_source": (
                f"/sys/dev/block/{_lower_io_major_minor(target)}/stat"),
            "lower_io_claim_boundary": (
                VIRTUAL_LOWER_IO_CLAIM_BOUNDARY
                if virtual_device_only else LOWER_IO_CLAIM_BOUNDARY),
            "physical_oracle_phases": [],
            "final_recovery_state": "PREPARED",
        }
        _save_results(state_dir, results)
        failure = None
        execution_failure = False
        destructive_execution_started = False
        partition_claim_attempted = False
        try:
            artifacts = _snapshot_reviewed_artifacts(
                state_dir, evidence["artifact_digests"])
            _fsync_directory(state_dir)  # All snapshot directory entries durable.
            formatter = artifacts["formatter_sha256"]
            module = artifacts["module_sha256"]
            oracle = artifacts["oracle_sha256"]
            if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != \
                    evidence["helper_sha256"] or \
                    _git("rev-parse", "HEAD") != evidence["head"] or \
                    _git("rev-parse", "origin/main") != evidence["head"] or \
                    _git("status", "--porcelain"):
                raise ProbeError(
                    "main or the bound helper changed before physical execution")
            if development_only:
                _require_development_canonical_main(
                    evidence["head"], evidence["source_sha"])
            elif _remote_main_sha() != evidence["head"]:
                raise ProbeError(
                    "canonical main changed before physical execution")
            _verify_target_identity(target)
            current_swap = _active_swap_for(target["major"], target["minor"])
            if development_only:
                if algorithm_real_swap:
                    current_target_row, current_swapfiles = (
                        _development_swap_inventory_plan(target))
                    if target["swap_was_active"] is True and current_target_row is None:
                        raise ProbeError(
                            "selected partition became inactive before owned swapoff")
                    saved_swapfiles = target.get("unrelated_swapfiles", [])
                    if len(saved_swapfiles) != len(current_swapfiles) or any(
                            not _swapfile_identity_matches(saved, current)
                            for saved, current in zip(
                                saved_swapfiles, current_swapfiles)):
                        raise ProbeError(
                            "unrelated swapfile inventory changed after preflight")
                elif current_swap is not None:
                    raise ProbeError(
                        "selected partition became active swap after preflight")
            elif current_swap is None or current_swap["used_kib"] != 0 or (
                    current_swap["size_kib"] != target["swap_size_kib"]) or (
                    current_swap["priority"] != target["swap_priority"]):
                raise ProbeError("selected swap state changed after preflight")
            if _read_block0(target["device"], target) != target["header"]:
                raise ProbeError("original block zero changed after backup")
            live_before_swapoff = _artifact_digests()
            if live_before_swapoff != evidence["artifact_digests"]:
                raise ProbeError(
                    "qualified artifacts changed before physical execution")
            results["live_artifact_sha256_before_mutation"] = dict(
                live_before_swapoff)
            _save_results(state_dir, results)
            partition_claim_attempted = True
            _consume_review(target, review["run_id"], preburned=True)
            # Ownership binding is immutable across both JSON records. The
            # separately durable active marker is the authority that this
            # one-use run currently owns recovery, avoiding a two-file claim
            # publication window that a crash could split.
            # The consumed one-use run claim, active partition marker and\n            # read-only original-header evidence are durable before swapoff and\n            # post-header data-area mutation. New runs never mutate block zero.
            _verify_target_identity(target)
            if development_only and algorithm_real_swap:
                _quiesce_development_swap_inventory(state, target, state_dir)
            elif not development_only:
                _run(["swapoff", "--", target["device"]], timeout=120)
                if _active_swap_for(target["major"], target["minor"]) is not None:
                    raise ProbeError("swapoff returned but partition is still active")
            state["stage"] = "SWAP_OFF"
            _save_state(state_dir, state)

            # Ordinary swap backing is already formatted. Preserve all 4096
            # bytes of block zero exactly; the kernel reserves this page
            # from the mapper's physical allocator. Only the test-owned
            # mapper is formatted with mkswap, never the user partition.
            _verify_target_identity(target)
            if _active_swap_for(target["major"], target["minor"]) is not None:
                raise ProbeError("raw swap partition remained active after swapoff")
            if _read_block0(target["device"], target) != target["header"]:
                raise ProbeError("original Linux swap header changed before mapping")
            state["stage"] = "EXISTING_SWAP_READY"
            _save_state(state_dir, state)
            if development_only and algorithm_real_swap:
                _restore_development_swapfiles(state)

            _run(["modprobe", "dm_mod"], timeout=30)
            _run(["modprobe", "lz4_compress"], timeout=30)
            if Path("/sys/module/dm_swapz").exists():
                raise ProbeError("module appeared before helper-owned insertion")
            # Persist uncertainty before insmod can succeed. Pending is NEVER
            # treated as permission to unload a module during recovery.
            state["module_ownership"] = "MODULE_PENDING"
            state["stage"] = "MODULE_PENDING"
            _save_state(state_dir, state)
            loaded_ram_qualified = (not development_only) or algorithm_real_swap
            if not loaded_ram_qualified:
                raise ProbeError(
                    "physical run requires current-source loaded RAM qualification")
            _run([
                "insmod", module, "allow_physical_backing=1",
                "physical_ram_metadata_qualified=1", "async_prepare=1",
            ], timeout=30)
            parameter = Path(
                "/sys/module/dm_swapz/parameters/allow_physical_backing")
            if not parameter.is_file() or (
                    parameter.read_text().strip().lower() not in {"y", "1"}):
                raise ProbeError("loaded module did not retain physical opt-in")
            state["module_ownership"] = "MODULE_OWNED"
            state["stage"] = "MODULE_OWNED"
            _save_state(state_dir, state)

            # The first mapper/device write can now begin; the raw swap
            # header itself is never a mutation target.
            destructive_execution_started = True
            _verify_target_identity(target)
            table = _expected_dm_table(target)
            _run([
                "dmsetup", "create", state["dm_name"], "--uuid",
                state["dm_uuid"], "--table", table,
            ], timeout=30)
            _run(["udevadm", "settle", "--timeout=10"], timeout=15)
            _verify_owned_mapper(state, target)
            state["stage"] = "MAPPED"
            _save_state(state_dir, state)

            _verify_target_identity(target)
            mapper = _verify_owned_mapper(state, target)
            phases = [
                ("byte-exact-opened-dm", ("--expect-dm-uuid", state["dm_uuid"])),
                ("delta64-write-series-128-round-1",
                 ("--delta64-write-series", "128", "1")),
                ("delta64-verify-series-128-round-1",
                 ("--delta64-verify-series", "128", "1")),
                ("segmented-write-series-128-round-5",
                 ("--segmented-write-series", "128", "5")),
                ("segmented-verify-series-128-round-5",
                 ("--segmented-verify-series", "128", "5")),
                ("ordinary-verify-series-128-round-5",
                 ("--verify-series", "128", "5")),
                ("ordinary-write-series-128-round-6",
                 ("--write-series", "128", "6")),
                ("segmented-verify-series-128-round-6",
                 ("--segmented-verify-series", "128", "6")),
                ("thp-write-series-128-round-7",
                 ("--thp-write-series", "128", "7")),
                ("thp-verify-series-128-round-7",
                 ("--thp-verify-series", "128", "7")),
                ("ordinary-verify-series-128-round-7",
                 ("--verify-series", "128", "7")),
            ]
            if development_only:
                # The first card exercise is one bounded 128-page direct-I/O
                # write/flush/overwrite/readback oracle. The full positive
                # suite remains behind the exact-source qualification gate.
                phases = phases[:1]
            for phase_name, options in phases:
                _run_positive_oracle_phase(
                    oracle, mapper, state, target, state_dir, results,
                    phase_name, options)
            if algorithm_real_swap:
                results["algorithm_live_swap"] = _run_algorithm_live_swap_oracle(
                    mapper, state, target, state_dir)
                results["linux_swap_activation_tested"] = True
                _save_results(state_dir, results)
            state["stage"] = "ORACLE_PASS"
            _save_state(state_dir, state)
            # Worker success remains provisional until either verified normal
            # teardown or an explicit post-PASS operator choice keeps the exact
            # owned mapper active. Failure paths never offer this choice.
            results["oracle_suite"] = "PHASES_PASS_RECOVERY_PENDING"
            results["final_recovery_state"] = "ORACLE_PASS"
            _save_results(state_dir, results)
            if development_only and algorithm_real_swap:
                # A PASS cannot transfer module-load ownership. recover()
                # refuses to remove a module after the owning test process
                # exits. Never leave active swapz without a durable manager
                # able to verify and stop the exact mapper and module later.
                if _operator_keep_swapz_active_after_pass():
                    results["operator_choice"] = (
                        "KEEP_SWAPZ_BLOCKED_NO_DURABLE_OWNER")
                    print(
                        "KEEP_SWAPZ=BLOCKED reason=no_durable_recovery_owner "
                        "action=restore_ordinary_swap", file=sys.stderr)
                else:
                    results["operator_choice"] = "RESTORE_ORDINARY_SWAP"
                _save_results(state_dir, results)
        except BaseException as exc:
            failure = exc
            execution_failure = destructive_execution_started
        if partition_claim_attempted:
            try:
                state = _remove_test_objects(state, state_dir)
            except BaseException as cleanup_exc:
                # Preserve the worker's first recorded oracle exit even when
                # the last durable results predate its failed publication.
                worker_failed_phases = [
                    phase for phase in results.get("physical_oracle_phases", [])
                    if isinstance(phase, dict) and phase.get("status") == "FAIL"
                ]
                worker_oracle_exit = (worker_failed_phases[0].get("return_code")
                                      if worker_failed_phases else None)
                state_record_bound = False
                try:
                    saved_state = _load_unique_json(
                        (state_dir / STATE_NAME).read_bytes())
                    if _recovery_state_identity_matches(state, saved_state):
                        state = saved_state
                        state_record_bound = True
                except (OSError, ValueError):
                    pass
                binding_state = dict(state)
                if state.get("stage") != "RECOVERY_REQUIRED":
                    state["stage_before_recovery"] = state["stage"]
                    state["stage"] = "RECOVERY_REQUIRED"
                state["recovery_error"] = _bounded_text(cleanup_exc)
                state_save_failed = not state_record_bound
                state_save_errno = None
                if state_record_bound:
                    try:
                        _save_state(state_dir, state)
                    except (OSError, ProbeError) as state_exc:
                        # A replacement may be visible without a durable
                        # directory entry. Do not conceal the first failure.
                        state_save_failed = True
                        state_save_errno = getattr(state_exc, "errno", None)
                        first_error = failure if failure is not None else cleanup_exc
                        print(
                            "RECOVERY_STATE_DURABILITY=UNCERTAIN "
                            f"first_errno={_errno_text(first_error)} "
                            f"recovery_errno={_errno_text(state_exc)} "
                            "safe_next_step=inspect_owner_and_state_read_only",
                            file=sys.stderr)
                else:
                    print(
                        "RECOVERY_STATE_IDENTITY=UNVERIFIED "
                        "publication_phase=before_recovery_state_update "
                        "safe_next_step=inspect_owner_state_results_read_only",
                        file=sys.stderr)
                results["end_timestamp"] = _utc_timestamp()
                results_record_bound = state_record_bound
                if results_record_bound:
                    try:
                        saved_results = _load_unique_json(
                            (state_dir / RESULTS_NAME).read_bytes())
                        _require_recovery_results_binding(
                            binding_state, saved_results)
                        results = saved_results
                    except (OSError, ValueError, ProbeError):
                        results_record_bound = False
                if state_save_failed:
                    results["recovery_state_durability"] = "UNCERTAIN"
                    results["recovery_state_save_errno"] = state_save_errno
                first_error = failure if failure is not None else cleanup_exc
                failed_phases = [
                    phase for phase in results.get("physical_oracle_phases", [])
                    if isinstance(phase, dict) and phase.get("status") == "FAIL"
                ]
                first_exit = (failed_phases[0].get("return_code")
                              if failed_phases else None)
                results["recovery_failure_audit"] = {
                    "first_errno": _errno_text(first_error),
                    "first_oracle_exit": (worker_oracle_exit
                                          if worker_oracle_exit is not None
                                          else first_exit),
                    "recovery_errno": _errno_text(cleanup_exc),
                    "publication_phase": state.get("stage_before_recovery"),
                    "header_bytes_possibly_changed": 0,
                    "requested_recovery_state": "RECOVERY_REQUIRED",
                    "last_readable_saved_state": (
                        binding_state.get("stage") if state_record_bound
                        else "UNVERIFIED_IDENTITY"),
                    "state_durability": (
                        "UNCERTAIN" if state_save_failed else "SYNCED"),
                    "safe_next_step": "inspect_owner_state_results_header_read_only",
                }
                results["final_recovery_state"] = state["stage"]
                results["recovery_error"] = _bounded_text(cleanup_exc)
                results["end_timestamp"] = _utc_timestamp()
                if results_record_bound:
                    try:
                        _save_results(state_dir, results)
                    except (OSError, ProbeError) as results_exc:
                        first_error = failure if failure is not None else cleanup_exc
                        print(
                            "PHYSICAL_RESULTS_DURABILITY=UNCERTAIN "
                            f"first_errno={_errno_text(first_error)} "
                            f"results_errno={_errno_text(results_exc)} "
                            "safe_next_step=inspect_owner_and_state_read_only",
                            file=sys.stderr)
                else:
                    print(
                        "PHYSICAL_RESULTS_BINDING=UNVERIFIED "
                        "publication_phase=before_recovery_results_update "
                        "safe_next_step=inspect_owner_state_results_read_only",
                        file=sys.stderr)
                print(
                    "RECOVERY_REQUIRED: inspect durable owner/state at "
                    f"{state_dir}", file=sys.stderr)
                if failure is None:
                    failure = cleanup_exc
        elif failure is not None:
            state["stage"] = "PRE_DESTRUCTIVE_FAILED"
            state["recovery_error"] = str(failure)
            try:
                _save_state(state_dir, state)
            except (OSError, ProbeError) as state_exc:
                first_errno_text = _errno_text(failure)
                recovery_errno_text = _errno_text(state_exc)
                results["recovery_state_durability"] = "UNCERTAIN"
                results["recovery_state_save_errno"] = getattr(
                    state_exc, "errno", None)
                print(
                    "RECOVERY_STATE_DURABILITY=UNCERTAIN "
                    f"first_errno={first_errno_text} "
                    f"recovery_errno={recovery_errno_text} "
                    "safe_next_step=inspect_owner_and_state_read_only",
                    file=sys.stderr)
            results["final_recovery_state"] = "PRE_DESTRUCTIVE_FAILED"
            results["recovery_error"] = _bounded_text(failure)
            try:
                _final_observations(results, state_dir, state, target)
            except (OSError, ProbeError) as result_exc:
                results["results_save_error"] = _bounded_text(result_exc)
        if state.get("stage") == "COMPLETE":
            try:
                results = _load_unique_json(
                    (state_dir / RESULTS_NAME).read_bytes())
            except (OSError, ValueError) as exc:
                if failure is None:
                    failure = ProbeError(
                        f"cannot reload final physical results: {exc}")
            if not isinstance(results, dict):
                if failure is None:
                    failure = ProbeError(
                        "final physical results expected=object "
                        f"observed={type(results).__name__}")
            else:
                required_true = (
                    "original_header_matches_final",
                    "restored_swap_verified",
                    "mapper_removal_succeeded",
                    "module_cleanup_succeeded",
                    "unrelated_swapfiles_restored",
                )
                if development_only:
                    required_true += ("run_claim_consumed",)
                    if target.get("swap_was_active") is False:
                        required_true += ("target_remains_inactive",)
                else:
                    required_true += ("approval_consumed",)
                required = (
                    *((key, True) for key in required_true),
                    ("active_partition_marker_present", False),
                    ("final_recovery_state", "COMPLETE"),
                    ("unrelated_mapper_inventory_unchanged", True),
                    ("lower_io_evidence_gate", "AVAILABLE"),
                    ("kernel_diagnostics_gate", "AVAILABLE"),
                )
                failures = [
                    f"{field} expected={expected!r} observed={results.get(field)!r}"
                    for field, expected in required
                    if results.get(field) != expected
                ]
                try:
                    recomputed_lower = _lower_io_delta(
                        results.get("block_stats_before"),
                        results.get("block_stats_after"))
                    if results.get("lower_io_delta") != recomputed_lower:
                        failures.append(
                            "lower_io_delta expected="
                            f"{recomputed_lower!r} "
                            f"observed={results.get('lower_io_delta')!r}")
                except ProbeError as exc:
                    failures.append(
                        "lower_io_evidence expected=recomputable observed="
                        + _bounded_text(exc))
                diagnostics_error = _kernel_diagnostics_error(
                    results.get("kernel_swapz_messages"))
                if diagnostics_error is not None:
                    failures.append(
                        "kernel_diagnostics expected=healthy observed="
                        + diagnostics_error)
                if failure is None:
                    oracle_error = _final_physical_oracle_evidence_error(
                        results, state, target, evidence, review, phases,
                        oracle, mapper, development_only, algorithm_real_swap)
                    if oracle_error is not None:
                        failures.append(
                            "operation=validate_durable_oracle "
                            "phase=final_oracle_evidence "
                            "first_errno_or_exit=worker_exit_0 "
                            "expected=complete_exact_bound_oracle_and_recovery "
                            f"observed={oracle_error} "
                            "safe_next_step=inspect_results_read_only")
                if failures and failure is None:
                    failure = ProbeError(
                        "final physical restoration/evidence checks failed: "
                        + "; ".join(failures))
        if failure is None and state.get("stage") != "COMPLETE":
            failure = ProbeError(
                "final_recovery_state expected='COMPLETE' "
                f"observed={state.get('stage')!r}")
        if failure is not None:
            print(f"PHYSICAL_RESULTS={state_dir / RESULTS_NAME}", file=sys.stderr)
            if (state.get("stage") == "RECOVERY_REQUIRED" or
                    results.get("recovery_state_durability") == "UNCERTAIN"):
                raise RecoveryRequiredError(str(failure)) from failure
            if execution_failure:
                raise ProbeFailure(str(failure)) from failure
            raise ProbeError(str(failure)) from failure
        # Persist the final PASS only after verified recovery and the exact
        # durable oracle/source/target evidence agree.
        results["oracle_suite"] = "PASS"
        _save_results(state_dir, results)
        # A successful oracle alone cannot publish success before normal
        # mapper/module removal, swap restoration, and evidence validation.
        if development_only:
            if algorithm_real_swap:
                print("PHYSICAL_ALGORITHM_REAL_SWAP=PASS")
            if virtual_device_only:
                print("VIRTUAL_DEVICE_ONLY=PASS not_physical_qualification")
            print("PHYSICAL_DEVELOPMENT_SMOKE=PASS")
            print("EVIDENCE_CLASS=DEVELOPMENT_ONLY_NOT_PHYSICAL_QUALIFICATION")
            restored_state = (
                "swap-enabled" if target.get("swap_was_active") is True
                else "target-inactive")
            print(
                "PHYSICAL_SMOKE_RESTORED=original-header; "
                f"{restored_state} state={state_dir}")
        else:
            print("PHYSICAL_SMOKE=BOUNDED_POSITIVE_CORRECTNESS_ONLY")
            print(f"PHYSICAL_SMOKE_RESTORED=swap-enabled state={state_dir}")
        print(f"PHYSICAL_RESULTS={state_dir / RESULTS_NAME}")
    finally:
        _close_fd_preserving_active_error(lock_fd)


def plan(device_arg, confirm_arg, review_path=None):
    target = inspect_target(device_arg, confirm_arg)
    target["device_arg"] = device_arg
    lower_preflight = _block_stat_snapshot(target)
    if lower_preflight.get("available") is not True:
        raise ProbeError(
            f"preflight_lower_io expected=available "
            f"observed={lower_preflight.get('error')}")
    dm_inventory = _module_mapper_preflight()
    diagnostics = _kernel_swapz_messages(_utc_timestamp())
    _require_kernel_diagnostics(diagnostics, "preflight_kernel_diagnostics")
    try:
        _recovery_base(target)
        recovery_message = (
            "persistent recovery filesystem verified; selected swap excluded")
    except ProbeError as exc:
        recovery_message = f"recovery storage: BLOCKED ({exc})"
    evidence = None
    try:
        evidence = current_source_evidence()
        evidence_message = (
            "bare-metal latest-source owner x86_64 PASS accepted; "
            f"matching artifact reports={evidence['pass_reports']} "
            f"(latest={evidence['latest_source_reports']}, "
            f"earlier={evidence['prior_matching_reports']})")
    except ProbeError as exc:
        evidence_message = f"source qualification: BLOCKED ({exc})"
    review_message = "verbal review: missing"
    consumption_message = "one-use approval: unavailable"
    artifact_digests = None
    artifact_message = "reviewed binaries: unavailable"
    try:
        artifact_digests = _artifact_digests()
        if evidence is None:
            raise ProbeError("source qualification is not current")
        if artifact_digests != evidence["artifact_digests"]:
            raise ProbeError(
                "build artifacts differ from the qualified make-test report")
        artifact_message = (
            "reviewed binaries: live bytes match qualified report digests")
    except ProbeError as exc:
        artifact_digests = None
        artifact_message = f"reviewed binaries: BLOCKED ({exc})"
    if review_path:
        try:
            if evidence is None or artifact_digests is None:
                raise ProbeError("source qualification or binary artifacts are not current")
            review = validate_review(review_path, evidence, target)
            _check_review_unconsumed(target, review["run_id"])
            review_message = (
                f"verbal approval: present ({review['reviewer']}, "
                f"one-use run {review['run_id']})")
            consumption_message = "one-use approval: not consumed"
        except ProbeError as exc:
            review_message = f"verbal review: BLOCKED ({exc})"
            if "consumed" in str(exc).lower() or "outstanding" in str(exc).lower():
                consumption_message = f"one-use approval: BLOCKED ({exc})"
    print(f"DEVICE_PREFLIGHT=PASS major_minor={target['major']}:{target['minor']} "
          f"partuuid={target['partuuid']} bytes={target['size_bytes']} "
          f"used_kib={target['swap_used_kib']}")
    print(f"RECOVERY_GATE={recovery_message}")
    print("MODULE_MAPPER_GATE=PASS module=absent "
          f"other_mapper_count={dm_inventory['other_mapper_count']} "
          f"other_mapper_sha256={dm_inventory['other_mapper_sha256']}")
    print("KERNEL_DIAGNOSTICS_GATE=PASS source="
          f"{diagnostics.get('source')} time_filtered=true complete=true")
    print("LOWER_IO_GATE=PASS source="
          f"/sys/dev/block/{target['parent_major_minor']}/stat "
          f"fields={len(lower_preflight['values'])} sector_bytes=512")
    print(f"LOWER_IO_CLAIM_BOUNDARY={LOWER_IO_CLAIM_BOUNDARY}")
    print(f"SOURCE_GATE={evidence_message}")
    if evidence is not None:
        print(f"QUALIFIED_SOURCE_SHA={evidence['source_sha']}")
        print(f"HELPER_GIT_SHA={evidence['head']}")
        print(f"HELPER_SHA256={evidence['helper_sha256']}")
    print(f"ARTIFACT_GATE={artifact_message}")
    if artifact_digests is not None:
        for key, _, _ in PHYSICAL_ARTIFACTS:
            print(f"{key.upper()}={artifact_digests[key]}")
    print(f"REVIEW_GATE={review_message}")
    print(f"RUN_CONSUMPTION_GATE={consumption_message}")
    print("VERBAL_APPROVAL_AUTHENTICATION=PROCEDURAL_NOT_CRYPTOGRAPHIC")
    print("MAKE_TEST_PHYSICAL=NO")
    print("PHYSICAL_WRITE=NOT_PERFORMED")



def _optional_card_identity_text(path):
    field_name = Path(path).name
    field = (f"card_identity_{field_name}"
             if field_name in {"model", "serial", "wwid"} else "card_identity_field")
    try:
        value = Path(path).read_text().strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        if (field_name in {"serial", "wwid"} and exc.errno in {
                errno.EINVAL, errno.ENXIO, errno.EOPNOTSUPP}):
            # Some physical readers expose an optional identity sysfs file
            # whose read reports that the device has no such identifier.
            # The parent model, topology and geometry remain mandatory.
            return None
        # Never put sysfs paths or raw device identifiers in diagnostics.
        raise ProbeError(
            f"{field} expected=readable observed=errno_{exc.errno}"
        ) from exc
    return value or None


def _campaign_card_identity(device, parent_major_minor):
    """Fingerprint stable parent-card properties without exposing serial values."""
    if not isinstance(parent_major_minor, str) or not re.fullmatch(
            r"[0-9]+:[0-9]+", parent_major_minor):
        raise ProbeError(
            f"card_parent_major_minor expected=number:number "
            f"observed={parent_major_minor!r}")
    try:
        parent = Path(
            f"/sys/dev/block/{parent_major_minor}").resolve(strict=True)
        observed_parent = (parent / "dev").read_text().strip()
        sectors_text = (parent / "size").read_text().strip()
        removable_text = (parent / "removable").read_text().strip()
    except (OSError, RuntimeError) as exc:
        raise ProbeError(
            "card_parent_topology expected=readable "
            f"observed=unreadable_sysfs errno={getattr(exc, 'errno', None)!r}"
        ) from exc
    if observed_parent != parent_major_minor:
        raise ProbeError(
            f"card_parent_major_minor expected={parent_major_minor!r} "
            f"observed={observed_parent!r}")
    if VIRTUAL_BLOCK_PARENT_RE.fullmatch(parent.name):
        raise ProbeError(
            f"card_parent_device expected=physical observed={parent.name!r}")
    try:
        parent_sectors = int(sectors_text)
    except ValueError as exc:
        raise ProbeError(
            "card_parent_sectors expected=integer observed=noninteger"
        ) from exc
    if parent_sectors <= 0 or parent_sectors > MAX_BLOCK_COUNTER // 512:
        raise ProbeError(
            f"card_parent_sectors expected=1..uint64_max/512 "
            f"observed={parent_sectors}")
    if removable_text not in {"0", "1"}:
        raise ProbeError(
            "card_parent_removable expected=0_or_1 observed=invalid_format")
    parent_removable = removable_text == "1"
    model = _optional_card_identity_text(parent / "device/model")
    serial = _optional_card_identity_text(parent / "device/serial")
    wwid = _optional_card_identity_text(parent / "device/wwid")
    # TRAN belongs to the physical disk. Querying a partition often returns
    # an empty field even though its parent is connected over USB.
    transport = _run(
        ["lsblk", "-dnro", "TRAN", f"/dev/block/{parent_major_minor}"]
    ).stdout.strip().lower()
    if not model or not transport:
        raise ProbeError(
            "card_identity expected=nonempty_model_and_transport "
            f"observed=model_present={bool(model)},transport_present={bool(transport)}")
    canonical = {
        "parent_major_minor": parent_major_minor,
        "physical_disk": parent.name,
        "model": model,
        "transport": transport,
        "parent_size_bytes": parent_sectors * 512,
        "parent_removable": parent_removable,
        "serial": serial,
        "wwid": wwid,
    }
    digest = hashlib.sha256(json.dumps(
        canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "sha256": digest,
        "parent_major_minor": parent_major_minor,
        "physical_disk": parent.name,
        "model": model,
        "transport": transport,
        "parent_size_bytes": parent_sectors * 512,
        "parent_removable": parent_removable,
        "serial_present": serial is not None,
        "wwid_present": wwid is not None,
    }


def _normalize_expected_partuuid(value):
    normalized = value.lower() if isinstance(value, str) else None
    if (
            normalized is None or
            not 8 <= len(normalized) <= 64 or
            not re.fullmatch(r"[0-9a-f]+(?:-[0-9a-f]+)*", normalized) or
            sum(ch != "-" for ch in normalized) < 8):
        raise ProbeError(
            "expected_partuuid expected=stable_hex observed=invalid_format")
    return normalized


def _require_campaign_target_quiescent(target):
    """Campaign arms require an unchanged card and entirely inactive partition."""
    _verify_target_identity(target)
    observed_card = _campaign_card_identity(
        target["device"], target["parent_major_minor"])
    expected_removable = target.get("parent_removable")
    if (type(expected_removable) is bool and
            observed_card["parent_removable"] != expected_removable):
        raise ProbeError(
            f"campaign_parent_removable expected={expected_removable} "
            f"observed={observed_card['parent_removable']}")
    expected_card_sha = target.get("card_identity_sha256")
    if (not isinstance(expected_card_sha, str) or
            not re.fullmatch(r"[0-9a-f]{64}", expected_card_sha) or
            observed_card["sha256"] != expected_card_sha):
        raise ProbeError(
            f"campaign_card_identity expected={expected_card_sha!r} "
            f"observed={observed_card['sha256']!r}")
    try:
        holders = _holder_names(target["major"], target["minor"])
    except OSError as exc:
        raise ProbeError(
            f"campaign_holders expected=[] observed=unavailable_errno_{exc.errno}"
        ) from exc
    if holders:
        raise ProbeError(
            f"campaign_holders expected=[] observed=holder_count_{len(holders)}")
    if _mountinfo_has_device(target["major"], target["minor"]):
        raise ProbeError(
            f"campaign_mount expected=absent observed="
            f"{target['major']}:{target['minor']}")
    active = _active_swap_for(target["major"], target["minor"])
    if active is not None:
        raise ProbeError(
            "campaign_active_swap expected=absent observed="
            f"kind={active.get('kind')!r},size_kib={active.get('size_kib')!r},"
            f"used_kib={active.get('used_kib')!r},"
            f"priority={active.get('priority')!r}")


def inspect_campaign_target(device_arg, confirm_arg, expected_partuuid):
    """Read-only admission for the future physical performance campaign."""
    if not device_arg or device_arg != confirm_arg:
        raise ProbeError("--device and --confirm-device must match exactly")
    expected_partuuid = _normalize_expected_partuuid(expected_partuuid)
    prefix = "/dev/disk/by-partuuid/"
    if not device_arg.startswith(prefix):
        raise ProbeError(
            "campaign_device_path expected=by_partuuid_alias observed=other_prefix")
    if device_arg != prefix + Path(device_arg).name:
        raise ProbeError(
            "campaign_device_path expected=exact_by_partuuid_alias "
            "observed=noncanonical_alias")
    selected_partuuid = Path(device_arg).name.lower()
    if selected_partuuid != expected_partuuid:
        raise ProbeError(
            f"device_partuuid_path expected={expected_partuuid!r} "
            f"observed={selected_partuuid!r}")
    try:
        device = str(Path(device_arg).resolve(strict=True))
    except (OSError, RuntimeError) as exc:
        raise ProbeError(
            "campaign_device_path expected=resolvable "
            f"observed=unresolvable_errno_{getattr(exc, 'errno', None)!r}"
        ) from exc
    major, minor = block_identity(device)
    try:
        sys_entry = Path(
            f"/sys/dev/block/{major}:{minor}").resolve(strict=True)
        if not (sys_entry / "partition").is_file():
            raise ProbeError(
                f"campaign_device_type expected=partition "
                f"observed={sys_entry.name!r}")
        holders = sorted(path.name for path in (sys_entry / "holders").iterdir())
    except (OSError, RuntimeError) as exc:
        raise ProbeError(
            "campaign_topology expected=readable_partition "
            f"observed=unreadable_errno_{getattr(exc, 'errno', None)!r}"
        ) from exc
    parent_major_minor = _physical_parent_identity(major, minor)
    if holders:
        raise ProbeError(
            f"campaign_holders expected=[] observed=holder_count_{len(holders)}")
    if _mountinfo_has_device(major, minor):
        raise ProbeError(
            f"campaign_mount expected=absent observed={major}:{minor}")
    _require_root_not_on_target(major, minor)
    partuuid, size_bytes = _partition_identity(device)
    if partuuid != expected_partuuid:
        raise ProbeError(
            f"campaign_partuuid expected={expected_partuuid!r} "
            f"observed={partuuid!r}")
    try:
        blockdev_size = int(_run(
            ["blockdev", "--getsize64", device]).stdout.strip())
    except ValueError as exc:
        raise ProbeError(
            "campaign_geometry expected=integer_bytes observed=unparseable") from exc
    if blockdev_size != size_bytes:
        raise ProbeError(
            f"campaign_geometry expected={size_bytes} observed={blockdev_size}")
    card_identity = _campaign_card_identity(device, parent_major_minor)
    target = {
        "device": device,
        "major": major,
        "minor": minor,
        "parent_major_minor": parent_major_minor,
        "parent_model": card_identity["model"],
        "parent_transport": card_identity["transport"],
        "parent_size_bytes": card_identity["parent_size_bytes"],
        "parent_removable": card_identity["parent_removable"],
        "card_identity_sha256": card_identity["sha256"],
        "size_bytes": size_bytes,
        "partuuid": partuuid,
    }
    _require_campaign_target_quiescent(target)
    return target


def _campaign_source_artifacts(source_sha):
    """Return one exact source/artifact sample or fail closed."""
    evidence = current_source_evidence()
    if not isinstance(evidence, dict):
        raise ProbeError(
            "campaign_source_evidence expected=object observed=invalid")
    if evidence.get("head") != source_sha or evidence.get("source_sha") != source_sha:
        raise ProbeError(
            f"campaign_source_sha expected={source_sha!r} "
            f"observed_head={evidence.get('head')!r},"
            f"qualified={evidence.get('source_sha')!r}")
    live_artifacts = _artifact_digests()
    qualified_artifacts = evidence.get("artifact_digests")
    artifact_names = {name for name, _, _ in PHYSICAL_ARTIFACTS}
    if (not isinstance(live_artifacts, dict) or
            not isinstance(qualified_artifacts, dict) or
            set(live_artifacts) != artifact_names or
            set(qualified_artifacts) != artifact_names):
        raise ProbeError(
            "campaign_artifacts.keys expected=exact_qualified_artifact_set "
            "observed=missing_or_extra")
    for artifact_name, _, _ in PHYSICAL_ARTIFACTS:
        if live_artifacts[artifact_name] != qualified_artifacts[artifact_name]:
            raise ProbeError(
                f"campaign_artifacts.{artifact_name} "
                "expected=qualified_sha256 observed=changed_sha256")
    return evidence, live_artifacts


def campaign_plan(device_arg, confirm_arg, expected_partuuid, source_sha):
    """Read-only campaign admission; it never substitutes for physical arms."""
    preflight_start = _utc_timestamp()
    if not isinstance(source_sha, str) or not re.fullmatch(
            r"[0-9a-f]{40}", source_sha):
        raise ProbeError(
            "campaign_source_sha expected=40_lower_hex observed=invalid_format")
    target = inspect_campaign_target(
        device_arg, confirm_arg, expected_partuuid)
    lower_before = _block_stat_snapshot(target)
    if lower_before.get("available") is not True:
        raise ProbeError(
            "campaign_lower_io_before expected=available "
            f"observed={lower_before.get('error')}")
    dm_inventory = _module_mapper_preflight()
    evidence, live_artifacts = _campaign_source_artifacts(source_sha)
    diagnostics = _kernel_swapz_messages(preflight_start)
    _require_kernel_diagnostics(
        diagnostics, "campaign_kernel_diagnostics")
    evidence_after, live_artifacts_after = _campaign_source_artifacts(source_sha)
    if evidence_after != evidence:
        raise ProbeError(
            "campaign_source_evidence expected=stable observed=changed")
    if live_artifacts_after != live_artifacts:
        raise ProbeError(
            "campaign_artifacts expected=stable observed=changed")
    # Kernel and source checks can take time. Re-prove the selected card,
    # module/mapper inventory and lower counters last, immediately before READY.
    _require_campaign_target_quiescent(target)
    dm_inventory_after = _module_mapper_preflight()
    if dm_inventory_after != dm_inventory:
        raise ProbeError(
            "campaign_mapper_inventory expected=stable "
            f"observed_before={dm_inventory!r},observed_after={dm_inventory_after!r}")
    lower_after = _block_stat_snapshot(target)
    if lower_after.get("available") is not True:
        raise ProbeError(
            "campaign_lower_io_after expected=available "
            f"observed={lower_after.get('error')}")
    _lower_io_delta(lower_before, lower_after)

    print("CAMPAIGN_PREFLIGHT=READY_READ_ONLY "
          f"major_minor={target['major']}:{target['minor']} "
          f"parent_major_minor={target['parent_major_minor']} "
          f"partuuid={target['partuuid']} bytes={target['size_bytes']} "
          f"card_identity_sha256={target['card_identity_sha256']} "
          f"parent_model={target['parent_model']!r} "
          f"parent_transport={target['parent_transport']!r}")
    print(f"CAMPAIGN_SOURCE_SHA={source_sha}")
    print("CAMPAIGN_MODULE_MAPPER_GATE=READY module=absent "
          f"other_mapper_count={dm_inventory['other_mapper_count']} "
          f"other_mapper_sha256={dm_inventory['other_mapper_sha256']}")
    print("CAMPAIGN_KERNEL_DIAGNOSTICS_GATE=READY source="
          f"{diagnostics.get('source')} time_filtered=true complete=true")
    print("CAMPAIGN_LOWER_IO_GATE=READY source="
          f"/sys/dev/block/{target['parent_major_minor']}/stat "
          f"fields={len(lower_after['values'])} sector_bytes=512")
    print(f"LOWER_IO_CLAIM_BOUNDARY={LOWER_IO_CLAIM_BOUNDARY}")
    print("PAIRED_RAW_VS_SWAPZ=NOT_RUN")
    print("HIGH_OCCUPANCY_3600S=NOT_RUN")
    print("ANONYMOUS_LINUX_SWAP=NOT_RUN")
    print("PHYSICAL_SERVICE_EXECUTED=NO")
    print("PHYSICAL_WRITE=NOT_PERFORMED")


def _require_ram_only_metadata_for_physical_run():
    """Require the payload-only production representation before device admission."""
    try:
        source = (ROOT / "src/kernel/codec.h").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ProbeError("cannot verify RAM-only extent metadata admission") from exc
    if re.search(r"(?m)^#define SWAPZ_CODEC_METADATA_ON_MEDIA 0U$", source) is None:
        raise ProbeError(
            "physical run blocked until compressed extent metadata is RAM-only")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Private physical-swap correctness smoke and read-only campaign "\n            "preflight; the algorithm real-swap development path is entered "\n            "only after exact-source make test RAM qualification"))
    parser.add_argument(
        "action", choices=("plan", "campaign-plan", "run", "recover",
                           "recover-pending"))
    parser.add_argument("--device")
    parser.add_argument("--confirm-device")
    parser.add_argument("--partuuid")
    parser.add_argument("--source-sha")
    parser.add_argument("--state-dir")
    parser.add_argument("--review-record")
    parser.add_argument(
        "--development-only", action="store_true",
        help="run one current-source physical backing smoke; never qualifies production")
    parser.add_argument(
        "--algorithm-real-swap", action="store_true",
        help="bounded real anonymous Linux swap round-trip; development-only")
    parser.add_argument("--virtual-device-only", action="store_true",
                        help="development-only USB device in an authenticated VM")
    parser.add_argument("--algorithm-ram-evidence")
    parser.add_argument("--algorithm-ram-nonce")
    args = parser.parse_args(argv)
    if args.action in {"plan", "campaign-plan", "run", "recover"} and not args.device:
        parser.error("--device is required")
    if args.action in {"plan", "campaign-plan", "run", "recover"} and not args.confirm_device:
        parser.error("--confirm-device is required")
    if args.action == "campaign-plan" and (not args.partuuid or not args.source_sha):
        parser.error("campaign-plan requires --partuuid and --source-sha")
    if args.action == "run" and not args.state_dir and not args.development_only:
        parser.error("run requires --state-dir")
    if args.action == "run" and args.development_only and args.state_dir:
        parser.error("--development-only chooses its own fresh recovery directory")
    if args.action == "run" and not args.development_only and not args.review_record:
        parser.error("qualified run requires --review-record")
    if args.action == "run" and args.development_only and args.review_record:
        parser.error("--development-only does not accept a review record")
    if args.action != "run" and args.development_only:
        parser.error("--development-only is available only for run")
    if args.algorithm_real_swap and (args.action != "run" or
                                     not args.development_only):
        parser.error("--algorithm-real-swap requires run --development-only")
    if args.virtual_device_only and not (
            args.action == "run" and args.development_only and
            args.algorithm_real_swap):
        parser.error("--virtual-device-only requires development real-swap run")
    if args.action == "recover-pending" and any((
            args.device, args.confirm_device, args.state_dir,
            args.review_record, args.partuuid, args.source_sha,
            args.algorithm_ram_evidence, args.algorithm_ram_nonce)):
        parser.error("recover-pending takes no target or evidence overrides")
    if bool(args.algorithm_ram_evidence) != bool(args.algorithm_ram_nonce):
        parser.error("algorithm RAM evidence path and nonce are paired")
    if args.algorithm_ram_evidence and not (
            args.action == "run" and args.development_only and
            args.algorithm_real_swap):
        parser.error(
            "--algorithm-ram-evidence is only valid for the development real-swap run")
    if (args.algorithm_ram_nonce and
            re.fullmatch(r"[0-9a-f]{32}", args.algorithm_ram_nonce) is None):
        parser.error("--algorithm-ram-nonce must be 32 lowercase hex characters")
    if args.action == "recover" and not args.state_dir:
        parser.error("recover requires --state-dir")
    if args.action == "plan":
        plan(args.device, args.confirm_device, args.review_record)
        return 0
    if args.action == "campaign-plan":
        campaign_plan(
            args.device, args.confirm_device, args.partuuid, args.source_sha)
        return 0
    if args.action == "recover-pending":
        if os.geteuid() != 0:
            raise ProbeError("automatic recovery requires root")
        try:
            recover_pending_algorithm_trial()
        except OSError as exc:
            # Journal I/O uncertainty is not evidence that recovery finished.
            # Keep existing ProbeError classifications: an unprovisioned
            # recovery directory is BLOCKED, not RECOVERY_REQUIRED.
            raise RecoveryRequiredError(
                "automatic recovery journal inspection failed") from exc
        return 0
    if args.action == "recover":
        if os.geteuid() != 0:
            raise ProbeError("recover action requires root")
        try:
            state = recover(args.state_dir, args.device, args.confirm_device)
        except ProbeError as exc:
            raise RecoveryRequiredError(str(exc)) from exc
        except OSError as exc:
            raise RecoveryRequiredError(
                "recovery operation failed "
                f"original_errno={_errno_text(exc)} "
                "safe_next_step=inspect_owner_and_state_read_only") from exc
        print(f"PHYSICAL_RECOVERY=COMPLETE stage={state['stage']}")
        return 0
    # Reject before run_probe can claim a device or call swapoff. Read-only
    # plan/recovery paths remain available even during codec migration.
    _require_ram_only_metadata_for_physical_run()

    def handle_sigterm(signum, frame):
        del signum, frame
        raise ProbeError("received SIGTERM; attempting safe recovery")

    signal.signal(signal.SIGTERM, handle_sigterm)
    run_probe(args.device, args.confirm_device, args.state_dir,
              args.review_record, development_only=args.development_only,
              algorithm_real_swap=args.algorithm_real_swap,
              algorithm_ram_evidence=args.algorithm_ram_evidence,
              algorithm_ram_nonce=args.algorithm_ram_nonce,
              virtual_device_only=args.virtual_device_only)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProbeError as exc:
        status, exit_code = _terminal_error_status(exc)
        print(f"{status}: {exc}", file=sys.stderr)
        raise SystemExit(exit_code)
