#!/usr/bin/env python3
"""Private, opt-in physical swap-partition correctness smoke and recovery.

This is not part of make test and produces no performance qualification.
Before any write it requires an explicitly repeated stable device path, an
unused active swap partition, two current-source PASS reports from this host,
and an independent review record bound to the source, helper and device.
"""
import argparse
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
SWAPZ_HEADER_MAGIC = b"SWAPZ001"
SWAPZ_HEADER_VERSION = 1


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


def _read_block0(device):
    try:
        fd = os.open(device, os.O_RDONLY | os.O_CLOEXEC)
    except OSError as exc:
        raise ProbeError(f"cannot open selected block device for reading: {exc}") from exc
    try:
        data = os.pread(fd, PAGE_BYTES, 0)
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
        if not isinstance(partuuid, str) or not re.fullmatch(
                r"[0-9A-Fa-f-]{8,64}", partuuid):
            raise ProbeError("partition lacks a stable PARTUUID")
        size = row.get("size")
        if type(size) is not int or size <= 0:
            raise ProbeError("partition lacks a valid size")
        # Filesystem UUID links disappear when the original swap header is
        # replaced. The partition-table UUID must survive that transition.
        by_partuuid = Path("/dev/disk/by-partuuid") / partuuid.lower()
        if block_identity(by_partuuid) != block_identity(device):
            raise ProbeError("PARTUUID link does not identify the selected partition")
        return partuuid.lower(), size
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
        raise ProbeError("selected partition persistent identity changed")


def inspect_target(device_arg, confirm_arg):
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
    if not row.get("uuid") or not isinstance(size_bytes, int):
        raise ProbeError("selected swap partition lacks stable identity or size")
    partuuid, partition_size = _partition_identity(device)
    if partition_size != size_bytes:
        raise ProbeError("selected partition inventory has inconsistent size")
    if size_bytes < 3 * 1024 * 1024 + PAGE_BYTES:
        raise ProbeError("selected swap partition is too small for swapz")

    swaps = parse_swap_rows(Path("/proc/swaps").read_text())
    matching = []
    for swap in swaps:
        try:
            if block_identity(swap["path"]) == (major, minor):
                matching.append(swap)
        except ProbeError:
            continue
    if len(matching) != 1:
        raise ProbeError("selected partition must be exactly one active system swap")
    active = matching[0]
    if active["used_kib"] != 0:
        raise ProbeError("selected swap partition is in use; require zero used KiB")
    header = _read_block0(device)
    if not swap_signature_valid(header, os.sysconf("SC_PAGE_SIZE")):
        raise ProbeError("selected partition does not have a supported SWAPSPACE2 header")
    return {
        "device": device,
        "major": major,
        "minor": minor,
        "size_bytes": size_bytes,
        "uuid": row["uuid"],
        "partuuid": partuuid,
        "header": header,
        "swap_path": active["path"],
        "swap_priority": active["priority"],
        "swap_size_kib": active["size_kib"],
        "swap_used_kib": active["used_kib"],
    }


def _git(*args, check=True):
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=8")
    result = _run(["git", *args], timeout=20, check=check, cwd=ROOT, env=env)
    return result.stdout.strip()


def _remote_main_sha():
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=8")
    git_args = ["git", "-C", str(ROOT), "ls-remote", "origin",
                "refs/heads/main"]
    sudo_user = os.environ.get("SUDO_USER")
    if os.geteuid() == 0 and sudo_user and sudo_user != "root":
        runuser = shutil.which("runuser")
        if not runuser:
            raise ProbeError("runuser is required to verify origin as the operator")
        git_args = [
            runuser, "--user", sudo_user, "--", *git_args,
        ]
    result = _run(git_args, timeout=20, check=False, env=env)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ProbeError(f"cannot verify origin/main: {detail}")
    rows = [line.split() for line in result.stdout.splitlines()]
    if len(rows) != 1 or len(rows[0]) != 2 or \
            rows[0][1] != "refs/heads/main":
        raise ProbeError("origin did not return exactly one main ref")
    return rows[0][0]


def current_source_evidence():
    if platform.machine() != "x86_64":
        raise ProbeError("physical swap smoke is currently limited to x86_64")
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
    source = report.get("source_sha")
    if report.get("overall") != "PASS" or \
            report.get("tested_commit_sha") != source or \
            not isinstance(source, str) or len(source) != 40:
        raise ProbeError("current test_results.json is not an exact-source PASS")
    ancestor = _run(["git", "merge-base", "--is-ancestor", source, head],
                    check=False, cwd=ROOT)
    if ancestor.returncode:
        raise ProbeError("qualified source is not an ancestor of main")
    for commit in _git("rev-list", f"{source}..{head}").splitlines():
        names = _git("diff-tree", "--no-commit-id", "--name-only", "-r",
                     commit).splitlines()
        if names != ["test_results.json"]:
            raise ProbeError("main has changes after the qualified source")

    host_identity = live_host_identity()
    if report.get("host_identity") != host_identity:
        raise ProbeError("current PASS report was not produced on this host")
    host_json = json.dumps(host_identity, sort_keys=True, separators=(",", ":"))
    distinct_reports = set()
    for commit in _git("log", "--all", "--format=%H", "--", "test_results.json").splitlines():
        result = _run(["git", "show", f"{commit}:test_results.json"],
                      timeout=10, check=False)
        if result.returncode:
            continue
        try:
            historical = json.loads(result.stdout)
        except ValueError:
            continue
        if historical.get("overall") != "PASS" or \
                historical.get("source_sha") != source or \
                historical.get("tested_commit_sha") != source:
            continue
        old_host = historical.get("host_identity")
        if isinstance(old_host, dict) and json.dumps(
                old_host, sort_keys=True, separators=(",", ":")) == host_json:
            # A replayed/copy-published report is not a second run.
            distinct_reports.add(hashlib.sha256(
                json.dumps(historical, sort_keys=True,
                           separators=(",", ":")).encode()).hexdigest())
    return {
        "source_sha": source,
        "host_identity": host_identity,
        "pass_reports": len(distinct_reports),
        "head": head,
    }


def validate_review(review_path, evidence, target):
    try:
        review = json.loads(Path(review_path).read_text())
    except (OSError, ValueError) as exc:
        raise ProbeError(f"cannot read independent safety review: {exc}") from exc
    reviewer = review.get("reviewer")
    operator = os.environ.get("SUDO_USER") or os.environ.get("USER") or "root"
    if review.get("approved") is not True or not isinstance(reviewer, str) or \
            reviewer.strip().lower() in {"", "root", operator.lower()}:
        raise ProbeError("review record must name a separate approving reviewer")
    if review.get("scope") != EXPECTED_SCOPE or \
            review.get("source_sha") != evidence["source_sha"] or \
            review.get("device_major_minor") != \
            f"{target['major']}:{target['minor']}" or \
            review.get("helper_sha256") != hashlib.sha256(
                Path(__file__).read_bytes()).hexdigest():
        raise ProbeError("review record does not match this source, helper and device")
    return reviewer


def _validate_state_dir(state_dir):
    state_dir = Path(state_dir)
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


def _allocate_dm_identity():
    result = _run([
        "dmsetup", "info", "-c", "--noheadings", "-o", "name,uuid",
    ])
    existing = set()
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2:
            existing.add((fields[0], fields[1]))
    existing_names = {name for name, _ in existing}
    existing_uuids = {uuid for _, uuid in existing}
    for _ in range(16):
        token = secrets.token_hex(8)
        name = f"swapz-demo-physical-{token}"
        uuid = f"SWAPZ-TEST-PHYSICAL-{token}"
        if name not in existing_names and uuid not in existing_uuids:
            return name, uuid
    raise ProbeError("cannot allocate a unique owned Device Mapper identity")


def _write_block0(device, data, target):
    if len(data) != PAGE_BYTES:
        raise ProbeError("recovery header has the wrong length")
    try:
        fd = os.open(device, os.O_RDWR | os.O_CLOEXEC | os.O_EXCL | os.O_SYNC)
    except OSError as exc:
        raise ProbeError(f"cannot exclusively open selected partition: {exc}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISBLK(info.st_mode) or (
                os.major(info.st_rdev), os.minor(info.st_rdev)) != (
                target["major"], target["minor"]):
            raise ProbeError("partition identity changed before header write")
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
    for row in parse_swap_rows(Path("/proc/swaps").read_text()):
        try:
            if block_identity(row["path"]) == (major, minor):
                return row
        except ProbeError:
            continue
    return None


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


def _validate_recovery_header(current_header, backup, state, size_bytes):
    if current_header == backup:
        return
    stage = state.get("stage_before_recovery", state.get("stage"))
    if current_header == bytes(PAGE_BYTES) and stage in {
            "BACKED_UP", "SWAP_OFF", "HEADER_CLEARED"}:
        return
    digest = state.get("formatted_header_sha256")
    if stage in {"SWZ_FORMATTED", "MAPPED", "ORACLE_PASS"} and (
            isinstance(digest, str) and
            hashlib.sha256(current_header).hexdigest() == digest and
            swapz_header_valid(current_header, size_bytes)):
        return
    raise ProbeError(
        "partition header is not an expected recovery state; manual review required")


def recover(state_dir, device_arg, confirm_arg):
    state_dir = Path(state_dir)
    _validate_state_dir(state_dir)
    try:
        state = json.loads((state_dir / STATE_NAME).read_text())
        backup = (state_dir / BACKUP_NAME).read_bytes()
    except (OSError, ValueError) as exc:
        raise ProbeError(f"cannot load the saved physical-test recovery state: {exc}") from exc
    if len(backup) != PAGE_BYTES or hashlib.sha256(backup).hexdigest() != \
            state.get("header_sha256"):
        raise ProbeError("saved swap header is missing or does not match its digest")
    _validate_owned_mapper_identity(state)
    target = inspect_target_identity_for_recovery(
        state, device_arg, confirm_arg)

    dm_name = state.get("dm_name")
    dm_uuid = state.get("dm_uuid")
    if dm_name and dm_uuid:
        current = _run([
            "dmsetup", "info", "-c", "--noheadings", "-o", "uuid", dm_name,
        ], check=False)
        if current.returncode == 0:
            if current.stdout.strip() != dm_uuid:
                raise ProbeError("recovery refused a mapper with a different UUID")
            _run(["dmsetup", "remove", dm_name], timeout=60)
    if state.get("module_loaded_by_us") and Path("/sys/module/dm_swapz").exists():
        _run(["rmmod", "dm_swapz"], timeout=30)
    if _holder_names(target["major"], target["minor"]):
        raise ProbeError("recovery refused while the partition still has holders")
    if _mountinfo_has_device(target["major"], target["minor"]):
        raise ProbeError("recovery refused while the partition is mounted")

    try:
        current_header = _read_block0(target["device"])
    except ProbeError:
        current_header = b""
    active = _active_swap_for(target["major"], target["minor"])
    if active is not None and current_header != backup:
        raise ProbeError("recovery refused to rewrite a header while swap is active")
    _validate_recovery_header(current_header, backup, state, target["size_bytes"])
    if current_header != backup:
        _verify_target_identity(target)
        _write_block0(target["device"], backup, target)

    if state.get("swap_was_active"):
        if _active_swap_for(target["major"], target["minor"]) is None:
            if state.get("swap_priority", -1) >= 0:
                _run(["swapon", "--priority", str(state["swap_priority"]),
                      state["device"]], timeout=60)
            else:
                _run(["swapon", state["device"]], timeout=60)
        active = _active_swap_for(target["major"], target["minor"])
        if active is None:
            raise ProbeError("original swap partition did not become active again")
    state["stage"] = "COMPLETE"
    _save_state(state_dir, state)
    return state


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
        raise ProbeError("recovery partition PARTUUID or geometry changed")
    return {
        "device": device,
        "major": major,
        "minor": minor,
        "size_bytes": size,
        "partuuid": partuuid,
    }


def _prepare_state(target, state_dir, evidence, reviewer):
    dm_name, dm_uuid = _allocate_dm_identity()
    state_dir = Path(state_dir).expanduser()
    if not state_dir.is_absolute():
        raise ProbeError("--state-dir must be an absolute durable path")
    state_dir = state_dir.resolve()
    if ROOT == state_dir or ROOT in state_dir.parents:
        raise ProbeError("--state-dir must be outside the repository")
    if state_dir.exists():
        raise ProbeError("--state-dir already exists; use recover for saved state")
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        os.chmod(state_dir, 0o700)
        if state_dir.stat().st_uid != 0 or \
                stat.S_IMODE(state_dir.stat().st_mode) != 0o700:
            raise ProbeError("--state-dir must be root-owned with mode 0700")
        if state_dir.stat().st_dev == os.makedev(target["major"], target["minor"]):
            raise ProbeError("--state-dir is on the selected swap partition")
        backup_fd = os.open(
            state_dir / BACKUP_NAME,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
            0o600)
        try:
            _write_all(backup_fd, target["header"])
            os.fsync(backup_fd)
        finally:
            os.close(backup_fd)

        state = {
            "device_arg": target["device_arg"],
            "device": target["device"],
            "major": target["major"],
            "minor": target["minor"],
            "size_bytes": target["size_bytes"],
            "partuuid": target["partuuid"],
            "header_sha256": hashlib.sha256(target["header"]).hexdigest(),
            "swap_was_active": True,
            "swap_path": target["swap_path"],
            "swap_priority": target["swap_priority"],
            "swap_size_kib": target["swap_size_kib"],
            "swap_used_kib": target["swap_used_kib"],
            "source_sha": evidence["source_sha"],
            "host_report_count": evidence["pass_reports"],
            "reviewer": reviewer,
            "module_loaded_by_us": False,
            "dm_name": dm_name,
            "dm_uuid": dm_uuid,
            "stage": "BACKED_UP",
        }
        _save_state(state_dir, state)
        return state, state_dir
    except BaseException:
        try:
            (state_dir / BACKUP_NAME).unlink()
        except FileNotFoundError:
            pass
        try:
            state_dir.rmdir()
        except OSError:
            pass
        raise


def _remove_test_objects(state, state_dir):
    recover(state_dir, state["device_arg"], state["device_arg"])


def run_probe(device_arg, confirm_arg, state_dir_arg, review_path):
    if os.geteuid() != 0:
        raise ProbeError("run action requires root")
    evidence = current_source_evidence()
    if evidence["pass_reports"] < 2:
        raise ProbeError(
            "requires two current-source PASS reports from this computer; "
            f"found {evidence['pass_reports']}")
    target = inspect_target(device_arg, confirm_arg)
    target["device_arg"] = device_arg
    reviewer = validate_review(review_path, evidence, target)
    if Path("/sys/module/dm_swapz").exists():
        raise ProbeError("dm_swapz is already loaded; refusing an ambiguous module owner")
    for command in ("blockdev", "dmsetup", "insmod", "modprobe", "rmmod",
                    "swapoff", "swapon"):
        if not shutil.which(command):
            raise ProbeError(f"required command is missing: {command}")
    formatter = ROOT / "build/userspace/swapzctl"
    module = ROOT / "build/kernel/experimental/dm-swapz.ko"
    oracle = ROOT / "build/tests/device-roundtrip"
    for path in (formatter, module, oracle):
        if not path.is_file() or (path == oracle and not os.access(path, os.X_OK)):
            raise ProbeError(f"required tested build artifact is missing: {path.name}")
    state, state_dir = _prepare_state(
        target, state_dir_arg, evidence, reviewer)
    failure = None
    try:
        _verify_target_identity(target)
        current_swap = _active_swap_for(target["major"], target["minor"])
        if current_swap is None or current_swap["used_kib"] != 0:
            raise ProbeError("selected swap state changed after preflight")
        _run(["swapoff", "--", target["device"]], timeout=120)
        if _active_swap_for(target["major"], target["minor"]) is not None:
            raise ProbeError("swapoff returned but selected partition is still active")
        state["stage"] = "SWAP_OFF"
        _save_state(state_dir, state)

        _verify_target_identity(target)
        _write_block0(target["device"], bytes(PAGE_BYTES), target)
        state["stage"] = "HEADER_CLEARED"
        _save_state(state_dir, state)
        _run([formatter, "format", target["device"]], timeout=30)
        formatted_header = _read_block0(target["device"])
        if not swapz_header_valid(formatted_header, target["size_bytes"]):
            raise ProbeError("formatter did not produce the expected SWZ header")
        state["formatted_header_sha256"] = hashlib.sha256(
            formatted_header).hexdigest()
        state["stage"] = "SWZ_FORMATTED"
        _save_state(state_dir, state)

        _run(["modprobe", "dm_mod"], timeout=30)
        _run(["modprobe", "lz4_compress"], timeout=30)
        _run(["insmod", module, "allow_physical_backing=1", "async_prepare=1"],
             timeout=30)
        state["module_loaded_by_us"] = True
        _save_state(state_dir, state)
        parameter = Path("/sys/module/dm_swapz/parameters/allow_physical_backing")
        if not parameter.exists() or parameter.read_text().strip().lower() not in {
                "y", "1"}:
            raise ProbeError("loaded module did not retain physical-backing opt-in")

        table = (f"0 {LOGICAL_SECTORS} swapz {target['device']} "
                 "0 64 0 2 0 1 0 0")
        _verify_target_identity(target)
        _save_state(state_dir, state)
        _run(["dmsetup", "create", state["dm_name"], "--uuid", state["dm_uuid"],
              "--table", table], timeout=30)
        state["stage"] = "MAPPED"
        _save_state(state_dir, state)
        mapper = f"/dev/mapper/{state['dm_name']}"
        _run([oracle, mapper], timeout=180)
        state["stage"] = "ORACLE_PASS"
        _save_state(state_dir, state)
        print("PHYSICAL_SMOKE=BYTE_EXACT_CORRECTNESS_ONLY")
    except BaseException as exc:
        failure = exc
    try:
        _remove_test_objects(state, state_dir)
    except BaseException as cleanup_exc:
        state["stage_before_recovery"] = state["stage"]
        state["stage"] = "RECOVERY_REQUIRED"
        state["recovery_error"] = str(cleanup_exc)
        _save_state(state_dir, state)
        print(f"RECOVERY_REQUIRED: state preserved at {state_dir}", file=sys.stderr)
        if failure is None:
            failure = cleanup_exc
    if failure is not None:
        raise ProbeError(str(failure)) from failure
    print(f"PHYSICAL_SMOKE_RESTORED=swap-enabled state={state_dir}")


def plan(device_arg, confirm_arg, review_path=None):
    target = inspect_target(device_arg, confirm_arg)
    evidence = None
    try:
        evidence = current_source_evidence()
        evidence_message = (
            f"same-host current-source PASS reports: {evidence['pass_reports']}/2")
    except ProbeError as exc:
        evidence_message = f"source qualification: BLOCKED ({exc})"
    review_message = "independent review: missing"
    if review_path:
        try:
            if evidence is None:
                raise ProbeError("source qualification is not current")
            reviewer = validate_review(review_path, evidence, target)
            review_message = f"independent review: present ({reviewer})"
        except ProbeError as exc:
            review_message = f"independent review: BLOCKED ({exc})"
    print(f"DEVICE_PREFLIGHT=PASS major_minor={target['major']}:{target['minor']} "
          f"bytes={target['size_bytes']} used_kib={target['swap_used_kib']}")
    print(f"SOURCE_GATE={evidence_message}")
    if evidence is not None:
        helper_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        print(f"QUALIFIED_SOURCE_SHA={evidence['source_sha']}")
        print(f"HELPER_SHA256={helper_sha}")
    print(f"REVIEW_GATE={review_message}")
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
