#!/usr/bin/env python3
"""Read-only, fail-closed source/selected-module/loaded-target benchmark gate.

No root, device, module or DM mutation is ever performed by this helper.
This preflight cannot prove that the selected .ko bytes are *the same bytes*
previously loaded into the kernel. An authorized VM operator must separately
attest load provenance. Do not use output as independent kernel attestation.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

SOURCE_SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
MODULE_LIMIT = 64 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[2]


def check_inputs(source_sha: str, digest: str, module: Path) -> None:
    if SOURCE_SHA.fullmatch(source_sha) is None:
        raise ValueError("source SHA must be a pinned full lowercase Git commit")
    if DIGEST.fullmatch(digest) is None:
        raise ValueError("selected module digest must be a full lowercase SHA-256")
    if not module.is_absolute():
        raise ValueError("selected module path must be absolute")


def verify_evidence(*, actual_head: str, expected_head: str,
                    expected_source_blob: str, checkout_source_blob: str,
                    actual_module_sha: str, expected_module_sha: str,
                    modinfo_name: str, modinfo_vermagic: str,
                    running_kernel: str, module_loaded: bool,
                    targets: str) -> dict[str, str]:
    """Pure rootless contract. All inputs are observations, never test commands."""
    if actual_head != expected_head:
        raise ValueError("benchmark source HEAD differs from approved source SHA")
    if (not re.fullmatch(r"[0-9a-f]{40}", expected_source_blob) or
            expected_source_blob != checkout_source_blob):
        raise ValueError("kernel/dm-swapz.c content differs from approved commit")
    if actual_module_sha != expected_module_sha:
        raise ValueError("selected module SHA-256 differs from approved digest")
    if modinfo_name.strip().replace("-", "_") != "dm_swapz":
        raise ValueError("selected module has an unexpected modinfo name")
    if not modinfo_vermagic.split() or modinfo_vermagic.split()[0] != running_kernel:
        raise ValueError("selected module vermagic does not match running kernel")
    if not module_loaded:
        raise ValueError("dm_swapz is not loaded; stop before device setup")
    names = [line.split()[0] for line in targets.splitlines() if line.split()]
    if names.count("swapz") != 1:
        raise ValueError("Device Mapper swapz target is absent or ambiguous")
    return {
        "source_sha": actual_head,
        "kernel_blob": checkout_source_blob,
        "selected_module_sha256": actual_module_sha,
        "module_name": "dm_swapz",
        "running_kernel": running_kernel,
        "registered_dm_target": "swapz",
        "loaded_module_to_selected_ko_identity": "NOT_INDEPENDENTLY_ATTESTED",
    }


def protected_module_path(path: Path) -> None:
    """Fail closed on symlinks and non-root-owned/writable module parent paths."""
    parts = (path, *path.parents)
    for item in parts:
        try:
            st = item.lstat()
        except OSError as exc:
            raise ValueError(f"selected module path component inaccessible: {item}: {exc}") from exc
        if stat.S_ISLNK(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
            raise ValueError(f"selected module path is not root-protected: {item}")
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("selected module is not a regular file")


def hash_selected_module(path: Path) -> str:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as exc:
        raise ValueError(f"cannot pin selected module: {exc}") from exc
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
                not 0 < before.st_size <= MODULE_LIMIT):
            raise ValueError("selected module must be nonempty bounded singly-linked file")
        sha = hashlib.sha256()
        size = 0
        while True:
            block = os.read(fd, 65536)
            if not block:
                break
            size += len(block)
            if size > MODULE_LIMIT:
                raise ValueError("selected module exceeded allowed size")
            sha.update(block)
        after = os.fstat(fd)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_nlink,
                              s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if size != before.st_size or identity(before) != identity(after):
            raise ValueError("selected module changed during digest read")
        return sha.hexdigest()
    finally:
        os.close(fd)


def _query(args: list[str]) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True,
                                timeout=4, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"read-only preflight command failed: {args[0]}: {exc}") from exc
    if result.returncode != 0:
        raise ValueError(
            f"read-only preflight command failed ({args[0]}, rc={result.returncode}): "
            f"{result.stderr[-250:]}")
    return result.stdout.strip()


def preflight(source_sha: str, digest: str, module: Path,
              checkout: Path = ROOT, module_root: Path = Path("/sys/module/dm_swapz")
              ) -> dict[str, str]:
    check_inputs(source_sha, digest, module)
    protected_module_path(module)
    actual_sha = hash_selected_module(module)
    evidence = verify_evidence(
        actual_head=_query(["git", "-C", str(checkout), "rev-parse", "HEAD"]),
        expected_head=source_sha,
        expected_source_blob=_query([
            "git", "-C", str(checkout), "rev-parse",
            f"{source_sha}:kernel/dm-swapz.c"]),
        checkout_source_blob=_query([
            "git", "-C", str(checkout), "hash-object",
            "kernel/dm-swapz.c"]),
        actual_module_sha=actual_sha,
        expected_module_sha=digest,
        modinfo_name=_query(["modinfo", "-F", "name", str(module)]),
        modinfo_vermagic=_query(["modinfo", "-F", "vermagic", str(module)]),
        running_kernel=os.uname().release,
        module_loaded=module_root.is_dir(),
        targets=_query(["dmsetup", "targets"]),
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--module-sha256", required=True)
    parser.add_argument("--module", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = preflight(args.source_sha, args.module_sha256, args.module)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    for key, value in result.items():
        print(f"{key}={value}")
    print("BENCH_PREFLIGHT=PASS_SOURCE_REPORTED_ONLY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
