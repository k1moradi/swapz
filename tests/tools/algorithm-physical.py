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
        # A dedicated disposable card has one partition. Refuse shared-root,
        # boot, mapper or multi-partition media instead of inferring consent
        # from the presence of a swap signature on one sibling partition.
        if not isinstance(children, list) or len(children) != 1:
            continue
        for partition in children:
            if not isinstance(partition, dict) or \
                    partition.get("type") != "part" or \
                    partition.get("fstype") != "swap":
                continue
            if partition.get("mountpoints") not in (None, [], [None]):
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
            })
    return candidates


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
            "Filename", "Type", "Size", "Used", "Priority"] or \
            len(swap_lines) != 1:
        raise ValueError("swap already active or inventory ambiguous")
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
        raise ValueError("expected exactly one inactive USB-card swap partition")
    selected = candidates[0]
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
    print("  Swap status: inactive; test will use normal swapon/swapoff")
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
