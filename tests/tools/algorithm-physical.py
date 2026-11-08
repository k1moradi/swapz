#!/usr/bin/env python3
"""Single-consent physical algorithm trial, after all five RAM stages pass.

The unprivileged selector never writes devices. Only the already-hardened,
source-bound private probe receives a confirmed inactive USB-card partition.
"""
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PARTUUID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,71}")
UUID_PATTERN = re.compile(r"[a-fA-F0-9][a-fA-F0-9-]{7,71}")


def _eligible_partitions(lsblk_output: dict) -> list[dict]:
    """Classify only unmounted swap-signature partitions on USB disks."""
    disks = lsblk_output.get("blockdevices")
    if not isinstance(disks, list):
        raise ValueError("lsblk did not report canonical block devices")
    candidates = []
    for disk in disks:
        if not isinstance(disk, dict) or disk.get("type") != "disk" or \
                disk.get("tran") != "usb":
            continue
        children = disk.get("children")
        # Discovery is read-only. A shared-root USB disk may contain one
        # authorized swap partition without authorizing any sibling partition
        # or allowing the current private physical writer to use that disk.
        if (not isinstance(children, list) or not children or
                any(not isinstance(partition, dict) for partition in children)):
            continue
        child_paths = [partition.get("path") for partition in children]
        if (any(not isinstance(path, str) or not path.startswith("/dev/")
                for path in child_paths) or len(child_paths) != len(set(child_paths))):
            continue
        for partition in children:
            if not isinstance(partition, dict) or \
                    partition.get("type") != "part" or \
                    partition.get("fstype") != "swap":
                continue
            # lsblk uses [SWAP] for an active swap area; it is not a
            # filesystem mount. Cross-check it against /proc/swaps below.
            if partition.get("mountpoints") not in (
                    None, [], [None], ["[SWAP]"]):
                continue
            partuuid = partition.get("partuuid")
            swap_uuid = partition.get("uuid")
            path = partition.get("path")
            size = partition.get("size")
            if not isinstance(disk.get("path"), str) or \
                    not disk["path"].startswith("/dev/") or \
                    not isinstance(partuuid, str) or \
                    PARTUUID_PATTERN.fullmatch(partuuid) is None or \
                    not isinstance(swap_uuid, str) or \
                    UUID_PATTERN.fullmatch(swap_uuid) is None or \
                    not isinstance(path, str) or not path.startswith("/dev/") or \
                    type(size) is not int or size < 64 * 1024 * 1024:
                continue
            candidates.append({
                "path": path, "partuuid": partuuid,
                "uuid": swap_uuid, "size_bytes": size,
                "parent": disk.get("path"),
                "parent_has_other_partitions": len(children) != 1,
                "lsblk_active_swap": partition.get("mountpoints") == ["[SWAP]"],
            })
    return candidates


def _selected_swap_inventory(partition: dict, swap_lines: list[str]) -> dict:
    """Observe exact active swap identity, never authorize a swapoff.

    The root-controlled worker must recheck every observation before mutation.
    """
    try:
        selected_stat = os.stat(partition["path"])
    except OSError as error:
        raise ValueError("cannot stat selected swap partition") from error
    if not stat.S_ISBLK(selected_stat.st_mode):
        raise ValueError("selected swap partition is not a block device")
    matching = []
    unrelated = 0
    for line in swap_lines[1:]:
        fields = line.split()
        if len(fields) != 5:
            raise ValueError("swap inventory row is malformed")
        swap_path, swap_kind, capacity, used, priority = fields
        if (not swap_path.startswith("/") or
                swap_kind not in {"partition", "file"}):
            raise ValueError("swap inventory type or path is invalid")
        try:
            capacity_kib = int(capacity)
            used_kib = int(used)
            priority_number = int(priority)
        except ValueError as error:
            raise ValueError("swap inventory numeric field is invalid") from error
        if (not capacity.isdecimal() or not used.isdecimal() or
                capacity_kib < 1 or used_kib < 0 or used_kib > capacity_kib or
                not -32768 <= priority_number <= 32767):
            raise ValueError("swap inventory capacity or priority is invalid")
        if swap_kind == "file":
            unrelated += 1
            continue
        try:
            active_stat = os.stat(swap_path)
        except OSError as error:
            raise ValueError("cannot identify active block swap") from error
        if not stat.S_ISBLK(active_stat.st_mode):
            raise ValueError("active swap entry is not a block device")
        if active_stat.st_rdev == selected_stat.st_rdev:
            matching.append({"used_kib": used_kib,
                             "priority": priority_number,
                             "capacity_kib": capacity_kib})
        else:
            unrelated += 1
    if len(matching) > 1:
        raise ValueError("duplicate active swap entries for selected partition")
    active = matching[0] if matching else None
    if partition.get("lsblk_active_swap") and active is None:
        raise ValueError("lsblk swap marker disagrees with active swap inventory")
    return {"active_swap": active, "other_active_swap_count": unrelated}


def _require_read_only_preflight() -> dict:
    if os.geteuid() == 0:
        raise ValueError("algorithm confirmation must run unprivileged")
    if platform.machine() != "x86_64":
        raise ValueError("the existing physical probe is x86_64-only")
    virtual = subprocess.run(
        ["systemd-detect-virt", "--quiet"],
        check=False, capture_output=True, timeout=10)
    if virtual.returncode != 1:
        raise ValueError("virtual or unverifiable host is not admitted")
    if Path("/sys/module/dm_swapz").exists():
        raise ValueError("dm_swapz is already loaded; foreign module ownership")
    try:
        swap_lines = Path("/proc/swaps").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ValueError("cannot read current swap inventory") from error
    if not swap_lines or swap_lines[0].split() != [
            "Filename", "Type", "Size", "Used", "Priority"]:
        raise ValueError("swap inventory header is malformed")
    block_info = subprocess.run([
        "lsblk", "--json", "--bytes", "--output",
        "PATH,TYPE,FSTYPE,UUID,PARTUUID,SIZE,TRAN,MOUNTPOINTS"],
        capture_output=True, text=True, check=False, timeout=15)
    if block_info.returncode != 0 or len(block_info.stdout) > 1024 * 1024:
        raise ValueError("cannot identify an exact candidate partition")
    try:
        candidates = _eligible_partitions(json.loads(block_info.stdout))
    except (ValueError, TypeError, RecursionError) as error:
        raise ValueError("invalid or ambiguous block inventory") from error
    if len(candidates) != 1:
        raise ValueError("expected exactly one identifiable USB swap partition")
    selected = candidates[0]
    selected.update(_selected_swap_inventory(selected, swap_lines))
    selector = Path("/dev/disk/by-uuid") / selected["uuid"]
    if not selector.is_symlink() or \
            os.path.realpath(selector) != os.path.realpath(selected["path"]):
        raise ValueError("partition swap UUID link does not match the candidate")
    return {**selected, "selector": str(selector)}


def main() -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("PHYSICAL_ALGORITHM_REAL_SWAP=NOT_RUN reason=noninteractive")
        return 2
    try:
        selected = _require_read_only_preflight()
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        print("PHYSICAL_ALGORITHM_REAL_SWAP=BLOCKED " + str(error))
        return 2
    print("Physical algorithm trial (disposable swap data):")
    print(f"  Partition: {selected['path']}  Parent: {selected['parent']}")
    print(f"  PARTUUID: {selected['partuuid']}  Bytes: {selected['size_bytes']}")
    active_swap = selected.get("active_swap")
    if active_swap is not None:
        print(f"  Swap status: ACTIVE; used={active_swap['used_kib']} KiB, "
              f"priority={active_swap['priority']}")
    else:
        print("  Swap status: inactive")
    blockers = []
    if selected.get("parent_has_other_partitions"):
        blockers.append("shared_root_scope_and_independent_recovery_required")
    if active_swap is not None:
        blockers.append("active_target_swapoff_not_implemented")
    if selected.get("other_active_swap_count", 0):
        blockers.append("formatter_rejects_other_active_swap")
    if blockers:
        # A Yes/No answer must never bypass a missing privileged safety gate.
        print("PHYSICAL_ALGORITHM_REAL_SWAP=BLOCKED reason=" +
              ",".join(blockers))
        return 2
    print("  Existing swap header is restored after successful teardown")
    try:
        confirmed = input("Run bounded swapz Linux swap trial on this partition? [y/N] ")
    except EOFError:
        confirmed = ""
    if confirmed.lower() not in {"y", "yes"}:
        print("PHYSICAL_ALGORITHM_REAL_SWAP=NOT_RUN reason=declined")
        return 2
    sudo = shutil.which("sudo")
    if sudo is None:
        print("PHYSICAL_ALGORITHM_REAL_SWAP=BLOCKED reason=no_sudo")
        return 2
    command = [
        sudo, "-n", "--", sys.executable, "-I", "-B",
        str(ROOT / "tests/tools/physical-swap-probe.py"),
        "run", "--device", selected["selector"],
        "--confirm-device", selected["selector"],
        "--development-only", "--algorithm-real-swap",
    ]
    # The root helper owns recovery and its own bounded child timeouts. Do not
    # SIGKILL it merely because this unprivileged parent reached a wall clock.
    try:
        result = subprocess.run(command, cwd=ROOT, check=False)
    except OSError:
        print("PHYSICAL_ALGORITHM_REAL_SWAP=BLOCKED reason=helper_unavailable")
        return 2
    return result.returncode if result.returncode in (0, 1, 2, 3) else 2


if __name__ == "__main__":
    raise SystemExit(main())
