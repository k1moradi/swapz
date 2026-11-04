#!/usr/bin/env python3
"""Private, opt-in physical swap-partition correctness smoke and recovery.

This is not part of make test and produces no performance qualification.
Before any write it requires an explicitly repeated stable device path, an
unused active swap partition, a latest-source owner PASS and identical
qualified-artifact evidence, plus a verbal review record bound to source,
helper and device.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import secrets
import shutil
import signal
import stat
import struct
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
PAGE_BYTES = 4096
SWAP_SIGNATURE = b"SWAPSPACE2"
LOGICAL_SECTORS = 32768
EXPECTED_SCOPE = "physical swap backing correctness smoke only"
STATE_NAME = "state.json"
BACKUP_NAME = "block0.bin"
RESULTS_NAME = "results.json"
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
# The swapz DM status ABI contains many named counters. Preserve a bounded
# complete status line rather than certifying a clipped prefix as healthy.
MAX_STATUS_OUTPUT_CHARS = 32768
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
SWAPZ_HEADER_MAGIC = b"SWAPZ001"
SWAPZ_HEADER_VERSION = 1
BLKGETSIZE64 = 0x80081272  # Linux x86_64 _IOR(0x12, 114, size_t).
RECOVERY_BASE = Path("/var/lib/swapz/physical-recovery")
PERSISTENT_RECOVERY_FILESYSTEMS = frozenset({
    "ext2", "ext3", "ext4", "xfs", "btrfs", "f2fs",
})


class ProbeError(RuntimeError):
    pass


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


def block_identity(path):
    try:
        info = os.stat(path)
    except OSError as exc:
        raise ProbeError(f"cannot stat selected block device: {exc}") from exc
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


def _require_root_not_on_target(major, minor):
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


def _read_block0(device, target):
    try:
        fd = os.open(device, os.O_RDONLY | os.O_CLOEXEC | os.O_NOCTTY)
    except OSError as exc:
        raise ProbeError(f"cannot open selected block device for reading: {exc}") from exc
    try:
        _verify_open_block_device(fd, target)
        data = os.pread(fd, PAGE_BYTES, 0)
    except OSError as exc:
        raise ProbeError("failed to read selected partition header") from exc
    finally:
        os.close(fd)
    if len(data) != PAGE_BYTES:
        raise ProbeError("short read of the selected partition header")
    return data


def swapz_header_valid(header, size_bytes):
    """Recognize only the exact v1 SWZ formatter header geometry."""
    return (
        len(header) == PAGE_BYTES
        and header[:8] == SWAPZ_HEADER_MAGIC
        and struct.unpack_from("<IIQ", header, 8) ==
        (SWAPZ_HEADER_VERSION, PAGE_BYTES, size_bytes)
        and any(header[24:40])
        and not any(header[40:])
    )


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
        if block_identity(by_partuuid) != block_identity(device):
            raise ProbeError("PARTUUID link does not identify the selected partition")
        return normalized_partuuid, size
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise ProbeError("cannot verify stable partition identity") from exc


def live_host_identity():
    """Mirror the canonical make-test machine-id digest, not report metadata."""
    try:
        machine_id = Path("/etc/machine-id").read_text().strip()
        if not re.fullmatch(r"[0-9a-fA-F]{32}", machine_id) or (
                int(machine_id, 16) == 0):
            raise ValueError("invalid machine-id")
        return {
            "schema": "swapz-host-v1",
            "architecture": platform.machine(),
            "id_sha256": hashlib.sha256(
                b"swapz-host\0" + machine_id.lower().encode()).hexdigest(),
        }
    except (OSError, ValueError) as exc:
        raise ProbeError("cannot identify the current host for physical smoke") from exc


def _require_physical_host():
    """Reject VM and container execution; unknown detection fails closed."""
    detector = shutil.which("systemd-detect-virt")
    if not detector:
        raise ProbeError("systemd-detect-virt is required to verify a physical host")
    for mode in ("--vm", "--container"):
        result = _run([detector, mode], check=False)
        detected = result.stdout.strip()
        if result.returncode == 0:
            raise ProbeError(
                f"physical swap smoke is not allowed in a {mode[2:]}: "
                f"{detected or 'virtualized environment'}")
        if result.returncode != 1 or detected not in {"", "none"}:
            raise ProbeError(
                f"cannot establish a physical host with {mode}: "
                f"{_bounded_text(result.stderr or detected)}")


def _physical_parent_identity(major, minor):
    """Prove one sysfs partition-to-physical-disk parent, never a DM fallback."""
    try:
        partition = Path(f"/sys/dev/block/{major}:{minor}").resolve(strict=True)
        parent = partition.parent
        parent_identity = (parent / "dev").read_text().strip()
        if not re.fullmatch(r"[0-9]+:[0-9]+", parent_identity):
            raise ProbeError(
                f"parent_major_minor expected=number:number observed={parent_identity!r}")
        if (not (partition / "partition").is_file()
                or Path(f"/sys/dev/block/{parent_identity}").resolve(
                    strict=True) != parent
                or not (parent / "device").exists()
                or re.fullmatch(r"(?:dm-|loop|ram|zram|nullb)[0-9]+",
                                parent.name)):
            raise ProbeError(
                f"parent_topology expected=one physical disk observed={parent}")
        return parent_identity
    except (OSError, RuntimeError) as exc:
        raise ProbeError(
            f"parent_topology expected=one verifiable physical disk "
            f"observed={_bounded_text(exc)}") from exc


def _require_matching_swap_uuid(device_arg, observed_uuid):
    """A stale by-uuid alias must not approve another swap signature."""
    selected_uuid = Path(device_arg).name
    if not isinstance(observed_uuid, str) or (
            selected_uuid.lower() != observed_uuid.lower()):
        raise ProbeError(
            f"swap_uuid expected={selected_uuid!r} observed={observed_uuid!r}")


def _verify_target_identity(target):
    if block_identity(target["device"]) != (target["major"], target["minor"]):
        raise ProbeError("selected block identity changed during the operation")
    try:
        size = int(_run([
            "blockdev", "--getsize64", target["device"],
        ]).stdout.strip())
    except ValueError as exc:
        raise ProbeError("cannot verify selected partition size") from exc
    if size != target["size_bytes"]:
        raise ProbeError("selected partition size changed during the operation")
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


def inspect_target(device_arg, confirm_arg, *, allow_used_swap=False):
    """Identify the selected partition; the live trial may allow drainable use."""
    if not device_arg or device_arg != confirm_arg:
        raise ProbeError("--device and --confirm-device must match exactly")
    if not device_arg.startswith("/dev/disk/by-uuid/"):
        raise ProbeError("select the partition through /dev/disk/by-uuid/")
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
    _require_root_not_on_target(major, minor)

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
    _require_matching_swap_uuid(device_arg, row.get("uuid"))
    partuuid, partition_size = _partition_identity(device)
    if partition_size != size_bytes:
        raise ProbeError("selected partition inventory has inconsistent size")
    if size_bytes < 3 * 1024 * 1024 + PAGE_BYTES:
        raise ProbeError("selected swap partition is too small for swapz")

    active = _active_swap_for(major, minor)
    if active is None:
        raise ProbeError("selected partition must be exactly one active system swap")
    if not 0 <= active["used_kib"] <= active["size_kib"]:
        raise ProbeError("selected swap usage is outside its capacity")
    if active["used_kib"] != 0 and not allow_used_swap:
        raise ProbeError("selected swap partition is in use; require zero used KiB")
    header = _read_block0(device, {
        "major": major, "minor": minor, "size_bytes": size_bytes,
    })
    if not swap_signature_valid(header, os.sysconf("SC_PAGE_SIZE")):
        raise ProbeError("selected partition does not have a supported SWAPSPACE2 header")
    return {
        "device": device,
        "major": major,
        "minor": minor,
        "parent_major_minor": parent_major_minor,
        "size_bytes": size_bytes,
        "uuid": row["uuid"],
        "partuuid": partuuid,
        "header": header,
        "swap_path": active["path"],
        "swap_priority": active["priority"],
        "swap_size_kib": active["size_kib"],
        "swap_used_kib": active["used_kib"],
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
                raise ProbeError(f"physical artifact is not a usable regular file: {path.name}")
            digest = hashlib.sha256()
            while chunk := os.read(descriptor, 1024 * 1024):
                digest.update(chunk)
            after = os.fstat(descriptor)
            if (before.st_dev, before.st_ino, before.st_size,
                    before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_dev, after.st_ino, after.st_size,
                    after.st_mtime_ns, after.st_ctime_ns):
                raise ProbeError(f"physical artifact changed while hashing: {path.name}")
            digests[key] = digest.hexdigest()
        except OSError as exc:
            raise ProbeError(f"cannot verify physical artifact {path.name}: {exc}") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    return digests


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
            raise ProbeError(f"cannot snapshot physical artifact {source_path.name}: {exc}") from exc
        finally:
            if destination_fd >= 0:
                os.close(destination_fd)
            if source_fd >= 0:
                os.close(source_fd)
            if destination_created and not succeeded:
                try:
                    destination.unlink()
                except FileNotFoundError:
                    pass
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
        os.close(fd)


def _recovery_base(target=None):
    """Require an operator-provisioned, non-symlink, root-controlled location."""
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
    if target is not None and f"{target['major']}:{target['minor']}" in {
            row[0] for row in devices}:
        raise ProbeError("recovery storage is on the selected swap partition")
    return base


def _recovery_run_directory(state_dir, run_id=None):
    base = _recovery_base()
    directory = Path(state_dir)
    if not directory.is_absolute() or directory.parent != base:
        raise ProbeError("recovery run directory must be a direct child of the fixed base")
    if run_id is not None:
        if directory.name != f"swapz-physical-{run_id}":
            raise ProbeError("run directory must match the one-use approval run_id")
    elif not re.fullmatch(r"swapz-physical-[0-9a-f]{32}", directory.name):
        raise ProbeError("invalid recovery run directory name")
    return directory


def _partition_lock(partuuid):
    """Permanent lock inode; never unlink it, including after a crash."""
    base = _recovery_base()
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
        os.close(fd)
        raise


def _durable_exclusive_record(path, record):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        _write_all(fd, (json.dumps(record, sort_keys=True) + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)
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
    if state.get("stage") != "COMPLETE":
        raise ProbeError("cannot release ownership before full restoration")
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
        raise ProbeError("one-use verbal approval consumption is missing") from exc
    if used != marker:
        raise ProbeError("consumed review identity does not match partition owner")
    active_path.unlink()
    _fsync_directory(base)


def _validate_state_dir(state_dir):
    state_dir = _recovery_run_directory(state_dir)
    try:
        info = state_dir.lstat()
    except OSError as exc:
        raise ProbeError(f"cannot inspect saved state directory: {exc}") from exc
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or \
            stat.S_IMODE(info.st_mode) != 0o700:
        raise ProbeError("saved state directory must be a root-owned 0700 directory")
    for name in (STATE_NAME, BACKUP_NAME):
        try:
            entry = (state_dir / name).lstat()
        except OSError as exc:
            raise ProbeError(f"missing saved recovery file {name}: {exc}") from exc
        if not stat.S_ISREG(entry.st_mode) or entry.st_uid != 0 or \
                stat.S_IMODE(entry.st_mode) != 0o600:
            raise ProbeError(f"saved recovery file {name} must be root-owned mode 0600")


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
        os.close(fd)
        fd = -1
        os.replace(temp_name, state_dir / STATE_NAME)
        dir_fd = os.open(state_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


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


def _save_results(state_dir, results):
    """Atomically persist bounded metadata/output and its directory entry."""
    state_dir = Path(state_dir)
    fd, temp_name = tempfile.mkstemp(prefix=".results-", dir=state_dir)
    try:
        os.fchmod(fd, 0o600)
        payload = (json.dumps(results, sort_keys=True, indent=2) + "\n").encode()
        _write_all(fd, payload)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(temp_name, state_dir / RESULTS_NAME)
        _fsync_directory(state_dir)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


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
MAX_BLOCK_COUNTER = (1 << 64) - 1
LOWER_COUNTER_FIELDS = (
    ("lower_read_requests", 0),
    ("lower_read_sectors", 2),
    ("lower_write_requests", 4),
    ("lower_write_sectors", 6),
)


def _block_stat_snapshot(target):
    parent = target.get("parent_major_minor")
    if not isinstance(parent, str) or not re.fullmatch(
            r"[0-9]+:[0-9]+", parent):
        return {"available": False,
                "error": f"lower_parent_major_minor expected=number:number "
                         f"observed={parent!r}"}
    path = Path(f"/sys/dev/block/{parent}/stat")
    try:
        tokens = path.read_text().split()
        if len(tokens) < 11:
            raise ValueError(
                f"lower_stat_fields expected>=11 observed={len(tokens)}")
        fields = []
        for index, token in enumerate(tokens):
            if not token.isascii() or not token.isdecimal():
                raise ValueError(
                    f"lower_stat[{index}] expected=unsigned_integer "
                    f"observed={token!r}")
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
                "device_major_minor": parent, "sector_bytes": 512}
    except (OSError, ValueError) as exc:
        return {"available": False, "error": _bounded_text(exc),
                "device_major_minor": parent}


def _lower_io_delta(before, after):
    """Fail closed on missing, invalid, substituted, or reset lower counters."""
    for label, snapshot in (("before", before), ("after", after)):
        if not isinstance(snapshot, dict) or snapshot.get("available") is not True:
            detail = (snapshot.get("error") if isinstance(snapshot, dict)
                      else repr(snapshot))
            raise ProbeError(
                f"lower_io_{label} expected=available observed={_bounded_text(detail)}")
        values = snapshot.get("values")
        if not isinstance(values, list) or len(values) < 11 or any(
                type(value) is not int or value < 0 or value > MAX_BLOCK_COUNTER
                for value in values):
            raise ProbeError(
                f"lower_io_{label}.values expected>=11_uint64_counters "
                f"observed={_bounded_text(values)}")
        for field, index in LOWER_COUNTER_FIELDS:
            if "sectors" in field and values[index] > MAX_BLOCK_COUNTER // 512:
                raise ProbeError(
                    f"{label}.{field} expected<=uint64_max/512 "
                    f"observed={values[index]}")
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
        command = [journalctl, "--boot", "--kernel", "--no-pager",
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


def _dm_inventory_snapshot(owned_name=None, owned_uuid=None):
    result = _run([
        "dmsetup", "info", "-c", "--noheadings", "-o", "name,uuid",
    ], check=False)
    if result.returncode:
        raise ProbeError("cannot snapshot Device Mapper inventory")
    rows = []
    for name, uuid in _dm_info_rows(result.stdout, 2):
        if name == owned_name or uuid == owned_uuid:
            if (name, uuid) != (owned_name, owned_uuid):
                raise ProbeError("owned mapper name or UUID changed in inventory")
            continue
        rows.append([name, uuid])
    rows.sort()
    digest = hashlib.sha256(json.dumps(
        rows, separators=(",", ":")).encode()).hexdigest()
    return {"other_mapper_count": len(rows), "other_mapper_sha256": digest}


def _final_observations(results, state_dir, state, target):
    """Collect final identity-only observations; never read test page contents."""
    try:
        header = _read_block0(target["device"], target)
        results["final_block0_sha256"] = hashlib.sha256(header).hexdigest()
        results["original_header_matches_final"] = (
            results["final_block0_sha256"] == results.get(
                "original_header_sha256"))
    except ProbeError as exc:
        results["final_block0_sha256"] = None
        results["original_header_matches_final"] = False
        results["final_block0_error"] = _bounded_text(exc)
    try:
        results["final_swap_row"] = _active_swap_for(
            target["major"], target["minor"])
    except ProbeError as exc:
        results["final_swap_row"] = None
        results["final_swap_error"] = _bounded_text(exc)
    results["block_stats_after"] = _block_stat_snapshot(target)
    try:
        results["lower_io_delta"] = _lower_io_delta(
            results.get("block_stats_before"), results["block_stats_after"])
        results["lower_io_evidence_gate"] = "AVAILABLE"
    except ProbeError as exc:
        results["lower_io_delta"] = None
        results["lower_io_evidence_gate"] = "BLOCKED"
        results["lower_io_evidence_error"] = _bounded_text(exc)
    results["kernel_swapz_messages"] = _kernel_swapz_messages(
        results.get("start_timestamp", "now"))
    diagnostics = results["kernel_swapz_messages"]
    results["kernel_diagnostics_gate"] = (
        "AVAILABLE" if diagnostics.get("available") is True
        and diagnostics.get("time_filter_applied") is True
        and diagnostics.get("truncated") is False else "BLOCKED")
    if results["kernel_diagnostics_gate"] == "BLOCKED":
        results["kernel_diagnostics_error"] = (
            "kernel_trace expected=available,time_filtered,complete "
            f"observed={_bounded_text(diagnostics)}")
    row = results.get("final_swap_row")
    # The identity-only recovery target omits original swap parameters.
    # Compare with the durable saved state, including after standalone recovery.
    results["restored_swap_verified"] = (
        state.get("swap_was_active") is True
        and isinstance(row, dict)
        and row.get("kind") == "partition"
        and type(state.get("swap_size_kib")) is int
        and type(state.get("swap_priority")) is int
        and row.get("size_kib") == state["swap_size_kib"]
        and row.get("priority") == state["swap_priority"])
    try:
        results["final_mapper_present"] = _mapper_exists(state)
    except ProbeError as exc:
        results["final_mapper_present"] = None
        results["final_mapper_error"] = _bounded_text(exc)
    results["final_module_present"] = Path("/sys/module/dm_swapz").exists()
    active = _recovery_base(target) / f"partition-{state['partuuid']}.active"
    results["active_partition_marker_present"] = active.exists()
    consumed = _recovery_base(target) / f"consumed-{state['run_id']}.json"
    results["approval_consumed"] = consumed.is_file()
    results["final_recovery_state"] = state.get("stage")
    results["mapper_removal_succeeded"] = (
        results["final_mapper_present"] is False)
    results["module_cleanup_succeeded"] = (
        results["final_module_present"] is False)
    try:
        results["dm_inventory_after"] = _dm_inventory_snapshot(
            state.get("dm_name"), state.get("dm_uuid"))
        before = results.get("dm_inventory_before")
        after = results["dm_inventory_after"]
        results["unrelated_mapper_inventory_unchanged"] = (
            isinstance(before, dict)
            and before.get("other_mapper_count") == after["other_mapper_count"]
            and before.get("other_mapper_sha256") == after["other_mapper_sha256"])
    except ProbeError as exc:
        results["dm_inventory_after"] = None
        results["unrelated_mapper_inventory_unchanged"] = None
        results["dm_inventory_error"] = _bounded_text(exc)
    results["end_timestamp"] = _utc_timestamp()
    _save_results(state_dir, results)


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
    try:
        fd = os.open(device, os.O_RDWR | os.O_CLOEXEC | os.O_EXCL | os.O_SYNC)
    except OSError as exc:
        raise ProbeError(f"cannot exclusively open selected partition: {exc}") from exc
    try:
        _verify_open_block_device(fd, target)
        if expected_current is not None and os.pread(
                fd, PAGE_BYTES, 0) != expected_current:
            raise ProbeError("partition header changed before exclusive update")
        written = os.pwrite(fd, data, 0)
        if written != PAGE_BYTES:
            raise ProbeError("short write while updating partition header")
        os.fsync(fd)
        verify = os.pread(fd, PAGE_BYTES, 0)
        if verify != data:
            raise ProbeError("partition header readback did not match")
    finally:
        os.close(fd)


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

    passed = (
        entry["return_code"] == 0
        and entry.get("post_oracle_identity") == "PASS"
        and _swapz_status_healthy(after_status)
        and entry["lower_io_delta"] is not None
        and "trace_error" not in entry
    )
    entry["status"] = "PASS" if passed else "FAIL"
    _save_results(state_dir, results)
    if not passed:
        raise ProbeError(
            f"physical oracle phase {phase} failed; later phases stopped")


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


def _validate_recovery_header(current_header, backup, state, size_bytes):
    if current_header == backup:
        return
    stage = state.get("stage_before_recovery", state.get("stage"))
    if current_header == bytes(PAGE_BYTES) and stage in {
            "SWAP_OFF", "HEADER_CLEARED"}:
        return
    digest = state.get("formatted_header_sha256")
    if stage in {"SWZ_FORMATTED", "MODULE_PENDING", "MODULE_OWNED",
                 "MAPPED", "ORACLE_PASS"} and (
            isinstance(digest, str) and
            hashlib.sha256(current_header).hexdigest() == digest and
            swapz_header_valid(current_header, size_bytes)):
        return
    raise ProbeError(
        "partition header is not an expected recovery state; manual review required")


def recover(state_dir, device_arg, confirm_arg, lock_held=False,
            module_owned_by_process=False):
    state_dir = Path(state_dir)
    _validate_state_dir(state_dir)
    try:
        state = _load_unique_json((state_dir / STATE_NAME).read_bytes())
        backup = (state_dir / BACKUP_NAME).read_bytes()
    except (OSError, ValueError) as exc:
        raise ProbeError("cannot load unambiguous saved physical recovery state") from exc
    if not isinstance(state, dict) or not re.fullmatch(
            r"[0-9a-f]{32}", str(state.get("run_id", ""))):
        raise ProbeError("saved recovery state lacks one-use run identity")
    _recovery_run_directory(state_dir, state["run_id"])
    if len(backup) != PAGE_BYTES or hashlib.sha256(backup).hexdigest() != (
            state.get("header_sha256")):
        raise ProbeError("saved original header is missing or digest-mismatched")
    if state.get("module_ownership") not in {
            "NOT_STARTED", "MODULE_PENDING", "MODULE_OWNED"}:
        raise ProbeError("saved module ownership is unknown; manual review required")
    _validate_owned_mapper_identity(state)
    lock_fd = None if lock_held else _partition_lock(state["partuuid"])
    try:
        base = _recovery_base()
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
            _verify_owned_mapper(state, target)
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
        if _holder_names(target["major"], target["minor"]):
            raise ProbeError("recovery refused while partition has holders")
        if _mountinfo_has_device(target["major"], target["minor"]):
            raise ProbeError("recovery refused while partition is mounted")

        current_header = _read_block0(target["device"], target)
        active = _active_swap_for(target["major"], target["minor"])
        if active is not None and current_header != backup:
            raise ProbeError("recovery refused to rewrite active swap")
        _validate_recovery_header(
            current_header, backup, state, target["size_bytes"])
        if current_header != backup:
            if active is not None:
                raise ProbeError("cannot restore header while swap is active")
            _verify_target_identity(target)
            _write_block0(target["device"], backup, target,
                          expected_current=current_header)
        if _read_block0(target["device"], target) != backup:
            raise ProbeError("original 4 KiB header not restored exactly")
        state["final_block0_sha256"] = hashlib.sha256(backup).hexdigest()

        if state.get("swap_was_active"):
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
        state["stage"] = "COMPLETE"
        _save_state(state_dir, state)
        results_path = state_dir / RESULTS_NAME
        if results_path.is_file():
            try:
                results = _load_unique_json(results_path.read_bytes())
            except (OSError, ValueError) as exc:
                raise ProbeError("saved physical results record is unreadable") from exc
            if not isinstance(results, dict):
                raise ProbeError("saved physical results record is not an object")
            _final_observations(results, state_dir, state, target)
        _release_partition_ownership(state)
        if results_path.is_file():
            _final_observations(results, state_dir, state, target)
        return state
    finally:
        if lock_fd is not None:
            os.close(lock_fd)


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
    return {
        "device": device,
        "major": major,
        "minor": minor,
        "parent_major_minor": parent,
        "size_bytes": size,
        "partuuid": partuuid,
    }


def _prepare_state(target, state_dir, evidence, review):
    """Create and sync the full recovery record before any destructive action."""
    dm_name, dm_uuid = _allocate_dm_identity()
    state_dir = _recovery_run_directory(state_dir, review["run_id"])
    if state_dir.exists() or state_dir.is_symlink():
        raise ProbeError("one-use recovery run directory already exists")
    _verify_target_identity(target)
    if _read_block0(target["device"], target) != target["header"]:
        raise ProbeError("original header changed since device review")
    state_dir.mkdir(mode=0o700)  # Deliberately no recursive parent creation.
    _fsync_directory(state_dir.parent)
    info = state_dir.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or (
            stat.S_IMODE(info.st_mode) != 0o700):
        raise ProbeError("recovery run directory is not root-owned mode 0700")
    # Failure at any point leaves the directory for explicit inspection rather
    # than deleting a potentially durable backup or claim.
    backup_fd = os.open(
        state_dir / BACKUP_NAME,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600)
    try:
        _write_all(backup_fd, target["header"])
        os.fsync(backup_fd)
    finally:
        os.close(backup_fd)
    _fsync_directory(state_dir)
    state = {
        "device_arg": target["device_arg"],
        "device": target["device"],
        "major": target["major"],
        "minor": target["minor"],
        "parent_major_minor": target.get("parent_major_minor"),
        "size_bytes": target["size_bytes"],
        "partuuid": target["partuuid"],
        "header_sha256": hashlib.sha256(target["header"]).hexdigest(),
        "swap_was_active": True,
        "swap_path": target["swap_path"],
        "swap_priority": target["swap_priority"],
        "swap_size_kib": target["swap_size_kib"],
        "swap_used_kib": target["swap_used_kib"],
        "source_sha": evidence["source_sha"],
        "helper_git_sha": evidence["head"],
        "helper_sha256": evidence["helper_sha256"],
        "host_report_count": evidence["pass_reports"],
        "reviewer": review["reviewer"],
        "run_id": review["run_id"],
        "module_ownership": "NOT_STARTED",
        "dm_name": dm_name,
        "dm_uuid": dm_uuid,
        "stage": "BACKED_UP",
    }
    _save_state(state_dir, state)
    return state, state_dir


def _remove_test_objects(state, state_dir):
    return recover(state_dir, state["device_arg"], state["device_arg"],
                   lock_held=True, module_owned_by_process=True)


def run_probe(device_arg, confirm_arg, state_dir_arg, review_path):
    if os.geteuid() != 0:
        raise ProbeError("run action requires root")
    start_timestamp = _utc_timestamp()
    evidence = current_source_evidence()
    target = inspect_target(device_arg, confirm_arg)
    target["device_arg"] = device_arg
    _recovery_base(target)
    live_artifact_digests = _artifact_digests()
    if live_artifact_digests != evidence["artifact_digests"]:
        raise ProbeError(
            "current build artifacts differ from the qualified make-test report")
    review = validate_review(review_path, evidence, target)
    state_dir_arg = _recovery_run_directory(state_dir_arg, review["run_id"])
    _check_review_unconsumed(target, review["run_id"])
    if Path("/sys/module/dm_swapz").exists():
        raise ProbeError("dm_swapz already loaded; ambiguous module ownership")
    for command in ("blockdev", "dmsetup", "insmod", "modprobe", "rmmod",
                    "swapoff", "swapon", "findmnt", "udevadm"):
        if not shutil.which(command):
            raise ProbeError(f"required command is missing: {command}")
    dm_inventory_before = _dm_inventory_snapshot()
    preflight_block_stats = _block_stat_snapshot(target)
    if preflight_block_stats.get("available") is not True:
        raise ProbeError(
            "preflight_lower_io expected=available "
            f"observed={preflight_block_stats.get('error')}")

    lock_fd = _partition_lock(target["partuuid"])
    try:
        # Burn the one-use verbal approval before state preparation. A crash,
        # fsync failure or artifact-snapshot failure can never make it reusable.
        _burn_review(target, review["run_id"])
        state, state_dir = _prepare_state(
            target, state_dir_arg, evidence, review)
        results = {
            "schema": "swapz-physical-results-v1",
            "start_timestamp": start_timestamp,
            "end_timestamp": None,
            "current_git_head": evidence["head"],
            "qualified_production_source_sha": evidence["source_sha"],
            "helper_git_sha": evidence["head"],
            "helper_sha256": evidence["helper_sha256"],
            "qualified_artifact_sha256": dict(evidence["artifact_digests"]),
            "live_artifact_sha256_before_run": dict(live_artifact_digests),
            "run_id": review["run_id"],
            "approval_mode": "verbal",
            "reviewer": review["reviewer"],
            "device_uuid_path": device_arg,
            "major_minor": f"{target['major']}:{target['minor']}",
            "partuuid": target["partuuid"],
            "device_size_bytes": target["size_bytes"],
            "original_header_sha256": hashlib.sha256(
                target["header"]).hexdigest(),
            "original_swap_row": {
                "path": target["swap_path"],
                "kind": "partition",
                "size_kib": target["swap_size_kib"],
                "used_kib": target["swap_used_kib"],
                "priority": target["swap_priority"],
            },
            "qualification_evidence": {
                "latest_source_reports": evidence["latest_source_reports"],
                "earlier_matching_artifact_reports": evidence[
                    "prior_matching_reports"],
                "total_distinct_matching_reports": evidence["pass_reports"],
            },
            "dm_name": state["dm_name"],
            "dm_uuid": state["dm_uuid"],
            "dm_inventory_before": dm_inventory_before,
            "block_stats_before": preflight_block_stats,
            "lower_io_source": (
                f"/sys/dev/block/{target['parent_major_minor']}/stat"),
            "lower_io_claim_boundary": (
                "512-byte sectors and requests are host-visible parent-device "
                "I/O; not direct NAND wear, flash write amplification or endurance"),
            "physical_oracle_phases": [],
            "final_recovery_state": "BACKED_UP",
        }
        _save_results(state_dir, results)
        failure = None
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
                    _git("status", "--porcelain") or \
                    _remote_main_sha() != evidence["head"]:
                raise ProbeError(
                    "main or the bound helper changed before physical execution")
            _verify_target_identity(target)
            current_swap = _active_swap_for(target["major"], target["minor"])
            if current_swap is None or current_swap["used_kib"] != 0 or (
                    current_swap["size_kib"] != target["swap_size_kib"]) or (
                    current_swap["priority"] != target["swap_priority"]):
                raise ProbeError("selected swap state changed after preflight")
            if _read_block0(target["device"], target) != target["header"]:
                raise ProbeError("original block zero changed after backup")
            live_before_swapoff = _artifact_digests()
            if live_before_swapoff != evidence["artifact_digests"]:
                raise ProbeError(
                    "qualified artifacts changed before physical execution")
            results["live_artifact_sha256_before_swapoff"] = dict(
                live_before_swapoff)
            _save_results(state_dir, results)
            partition_claim_attempted = True
            _consume_review(target, review["run_id"], preburned=True)
            # The consumed review, active partition claim and backup are durable.
            _verify_target_identity(target)
            _run(["swapoff", "--", target["device"]], timeout=120)
            if _active_swap_for(target["major"], target["minor"]) is not None:
                raise ProbeError("swapoff returned but partition is still active")
            state["stage"] = "SWAP_OFF"
            _save_state(state_dir, state)

            _verify_target_identity(target)
            _write_block0(target["device"], bytes(PAGE_BYTES), target,
                          expected_current=target["header"])
            state["stage"] = "HEADER_CLEARED"
            _save_state(state_dir, state)
            _verify_target_identity(target)
            if _read_block0(target["device"], target) != bytes(PAGE_BYTES):
                raise ProbeError("partition block zero changed before formatter")
            _run([
                formatter, "format", target["device"], "--expect-major-minor",
                f"{target['major']}:{target['minor']}", "--expect-bytes",
                str(target["size_bytes"]),
            ], timeout=30)
            formatted_header = _read_block0(target["device"], target)
            if not swapz_header_valid(formatted_header, target["size_bytes"]):
                raise ProbeError("formatter did not produce the expected SWZ header")
            state["formatted_header_sha256"] = hashlib.sha256(
                formatted_header).hexdigest()
            state["stage"] = "SWZ_FORMATTED"
            _save_state(state_dir, state)

            _run(["modprobe", "dm_mod"], timeout=30)
            _run(["modprobe", "lz4_compress"], timeout=30)
            if Path("/sys/module/dm_swapz").exists():
                raise ProbeError("module appeared before helper-owned insertion")
            # Persist uncertainty before insmod can succeed. Pending is NEVER
            # treated as permission to unload a module during recovery.
            state["module_ownership"] = "MODULE_PENDING"
            state["stage"] = "MODULE_PENDING"
            _save_state(state_dir, state)
            _run(["insmod", module, "allow_physical_backing=1",
                  "async_prepare=1"], timeout=30)
            parameter = Path(
                "/sys/module/dm_swapz/parameters/allow_physical_backing")
            if not parameter.is_file() or (
                    parameter.read_text().strip().lower() not in {"y", "1"}):
                raise ProbeError("loaded module did not retain physical opt-in")
            state["module_ownership"] = "MODULE_OWNED"
            state["stage"] = "MODULE_OWNED"
            _save_state(state_dir, state)

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
            for phase_name, options in phases:
                _run_positive_oracle_phase(
                    oracle, mapper, state, target, state_dir, results,
                    phase_name, options)
            state["stage"] = "ORACLE_PASS"
            _save_state(state_dir, state)
            results["oracle_suite"] = "PASS"
            results["final_recovery_state"] = "ORACLE_PASS"
            _save_results(state_dir, results)
        except BaseException as exc:
            failure = exc
        if partition_claim_attempted:
            try:
                state = _remove_test_objects(state, state_dir)
            except BaseException as cleanup_exc:
                try:
                    saved_state = _load_unique_json(
                        (state_dir / STATE_NAME).read_bytes())
                    if isinstance(saved_state, dict):
                        state = saved_state
                except (OSError, ValueError):
                    pass
                if state.get("stage") != "RECOVERY_REQUIRED":
                    state["stage_before_recovery"] = state["stage"]
                    state["stage"] = "RECOVERY_REQUIRED"
                state["recovery_error"] = str(cleanup_exc)
                _save_state(state_dir, state)
                results["end_timestamp"] = _utc_timestamp()
                try:
                    saved_results = _load_unique_json(
                        (state_dir / RESULTS_NAME).read_bytes())
                    if isinstance(saved_results, dict):
                        results = saved_results
                except (OSError, ValueError):
                    pass
                results["final_recovery_state"] = state["stage"]
                results["recovery_error"] = _bounded_text(cleanup_exc)
                results["end_timestamp"] = _utc_timestamp()
                try:
                    _save_results(state_dir, results)
                except ProbeError:
                    pass
                print(f"RECOVERY_REQUIRED: state preserved at {state_dir}",
                      file=sys.stderr)
                if failure is None:
                    failure = cleanup_exc
        elif failure is not None:
            state["stage"] = "PRE_DESTRUCTIVE_FAILED"
            state["recovery_error"] = str(failure)
            _save_state(state_dir, state)
            results["final_recovery_state"] = "PRE_DESTRUCTIVE_FAILED"
            results["recovery_error"] = _bounded_text(failure)
            try:
                _final_observations(results, state_dir, state, target)
            except ProbeError as result_exc:
                results["results_save_error"] = _bounded_text(result_exc)
        if state.get("stage") == "COMPLETE":
            try:
                results = _load_unique_json(
                    (state_dir / RESULTS_NAME).read_bytes())
            except (OSError, ValueError) as exc:
                if failure is None:
                    failure = ProbeError(
                        f"cannot reload final physical results: {exc}")
            if isinstance(results, dict):
                required_true = (
                    "original_header_matches_final",
                    "restored_swap_verified",
                    "mapper_removal_succeeded",
                    "module_cleanup_succeeded",
                    "approval_consumed",
                )
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
            raise ProbeError(str(failure)) from failure
        # A successful oracle alone cannot publish success before normal
        # mapper/module removal, swap restoration, and evidence validation.
        print("PHYSICAL_SMOKE=BOUNDED_POSITIVE_CORRECTNESS_ONLY")
        print(f"PHYSICAL_SMOKE_RESTORED=swap-enabled state={state_dir}")
        print(f"PHYSICAL_RESULTS={state_dir / RESULTS_NAME}")
    finally:
        os.close(lock_fd)


def plan(device_arg, confirm_arg, review_path=None):
    target = inspect_target(device_arg, confirm_arg)
    target["device_arg"] = device_arg
    lower_preflight = _block_stat_snapshot(target)
    if lower_preflight.get("available") is not True:
        raise ProbeError(
            f"preflight_lower_io expected=available "
            f"observed={lower_preflight.get('error')}")
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


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Private physical-swap correctness smoke; never part of make test")
    parser.add_argument("action", choices=("plan", "run", "recover"))
    parser.add_argument("--device")
    parser.add_argument("--confirm-device")
    parser.add_argument("--state-dir")
    parser.add_argument("--review-record")
    args = parser.parse_args(argv)
    if args.action in {"plan", "run"} and not args.device:
        parser.error("--device is required")
    if args.action in {"plan", "run", "recover"} and not args.device:
        parser.error("--device is required")
    if args.action in {"plan", "run", "recover"} and not args.confirm_device:
        parser.error("--confirm-device is required")
    if args.action == "run" and (not args.state_dir or not args.review_record):
        parser.error("run requires --state-dir and --review-record")
    if args.action == "recover" and not args.state_dir:
        parser.error("recover requires --state-dir")
    if args.action == "plan":
        plan(args.device, args.confirm_device, args.review_record)
        return 0
    if args.action == "recover":
        if os.geteuid() != 0:
            raise ProbeError("recover action requires root")
        state = recover(args.state_dir, args.device, args.confirm_device)
        print(f"PHYSICAL_RECOVERY=COMPLETE stage={state['stage']}")
        return 0
    def handle_sigterm(signum, frame):
        del signum, frame
        raise ProbeError("received SIGTERM; attempting safe recovery")

    signal.signal(signal.SIGTERM, handle_sigterm)
    run_probe(args.device, args.confirm_device, args.state_dir, args.review_record)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProbeError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        raise SystemExit(2)
