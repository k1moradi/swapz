#!/usr/bin/env python3
"""Fail-closed, read-only root checkout admission for privileged bench runner.

This protects against accidentally executing a user-owned/unreviewed live
checkout. It does not make malicious code safe if an attacker already controls
the root-run script before this admission check can execute.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import stat
import subprocess
import sys

ROOT = Path(__file__).absolute().parents[2]
SOURCE_SHA = re.compile(r"[0-9a-f]{40}\Z")
# Every root-executed runner/helper and its transitive parsing dependencies.
PATHS = (
    "kernel/dm-swapz.c",
    "tests/runtime/streaming-benchmark.sh",
    "tests/runtime/streaming-benchmark-teardown.sh",
    "tests/runtime/streaming-benchmark-quarantine.sh",
    "tests/runtime/streaming-benchmark-live-authorization.py",
    "tests/runtime/streaming-benchmark-source-preflight.py",
    "tests/runtime/streaming-benchmark-module-preflight.py",
    "tests/runtime/streaming-benchmark-plan.py",
    "tests/runtime/streaming-benchmark-read-latency.py",
    "tests/runtime/streaming-benchmark-fio-verify.py",
    "tests/runtime/streaming-benchmark-report.py",
    "tests/runtime/streaming-benchmark-finalize.py",
    "tests/runtime/v22-drain-plateau-analyze.py",
    "tests/runtime/v22-fast-screen.py",
)


def protect_metadata(path: Path, *, directory: bool | None = None) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise ValueError(f"protected checkout component unavailable: {path}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError(f"benchmark source path is not root-owned/protected: {path}")
    if directory is True and not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"benchmark checkout directory expected: {path}")
    if directory is False and not stat.S_ISREG(info.st_mode):
        raise ValueError(f"benchmark regular source file expected: {path}")


def protected_checkout(checkout: Path = ROOT) -> None:
    if not checkout.is_absolute():
        raise ValueError("live checkout must be absolute")
    for folder in (checkout, *checkout.parents):
        protect_metadata(folder, directory=True)
    protect_metadata(checkout / ".git", directory=True)
    for rel in PATHS:
        path = checkout / rel
        for parent in (path.parent, *path.parent.parents):
            if parent == checkout.parent:
                break
            protect_metadata(parent, directory=True)
        protect_metadata(path, directory=False)


def command(args: list[str]) -> str:
    try:
        r = subprocess.run(args, check=False, capture_output=True,
                           timeout=4, text=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("protected checkout identity query failed") from exc
    if r.returncode != 0:
        raise ValueError(f"protected source Git identity check failed for {args[-1]}")
    return r.stdout.strip()


def verify_blobs(sha: str, checkout: Path = ROOT, query=command) -> None:
    if SOURCE_SHA.fullmatch(sha) is None:
        raise ValueError("approved checkout source SHA must be full lowercase Git commit")
    actual = query(["git", "-C", str(checkout), "rev-parse", "HEAD"])
    if actual != sha:
        raise ValueError("protected benchmark source HEAD differs from approved SHA")
    for rel in PATHS:
        expected = query(["git", "-C", str(checkout), "rev-parse", f"{sha}:{rel}"])
        actual_blob = query(["git", "-C", str(checkout), "hash-object", rel])
        if (not re.fullmatch(r"[0-9a-f]{40}", expected) or
                actual_blob != expected):
            raise ValueError(f"protected benchmark executable/dependency changed: {rel}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    try:
        protected_checkout()
        verify_blobs(args.source_sha)
    except ValueError as exc:
        parser.error(str(exc))
    print("BENCH_SOURCE_PREFLIGHT=PASS_PROTECTED_APPROVED_CHECKOUT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
