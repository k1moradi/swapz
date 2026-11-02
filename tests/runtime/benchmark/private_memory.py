#!/usr/bin/env python3
"""Fail-closed protection for owner-supplied representative anonymous pages.

The caller must opt in before reading content. Locking lasts for the process
lifetime; all child processes accessing pages independently protect themselves.
"""
import argparse
import ctypes
import json
import os
import resource
import stat
import sys
from pathlib import Path


def fixture_is_representative(fixture_path):
    """Read nonsensitive fixture metadata before opening sample content."""
    metadata_path = Path(fixture_path).parent / "fixture.json"
    try:
        metadata_info = metadata_path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ValueError("invalid fixture privacy metadata") from exc
    if not stat.S_ISREG(metadata_info.st_mode):
        raise ValueError("fixture privacy metadata must be a regular file")
    try:
        metadata = json.loads(metadata_path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError("invalid fixture privacy metadata") from exc
    if not isinstance(metadata, dict):
        raise ValueError("invalid fixture privacy metadata")
    return metadata.get("content_profile") == "representative"


def protect_private_memory():
    """Disable core dumps and lock existing and future mappings or fail closed."""
    if sys.platform != "linux":
        raise ValueError("representative page protection requires Linux")
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        libc = ctypes.CDLL(None, use_errno=True)
        set_dumpable = libc.prctl
        set_dumpable.argtypes = (ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong,
                                 ctypes.c_ulong, ctypes.c_ulong)
        set_dumpable.restype = ctypes.c_int
        if set_dumpable(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE
            raise OSError(ctypes.get_errno(), "PR_SET_DUMPABLE")
        lock_memory = libc.mlockall
        lock_memory.argtypes = (ctypes.c_int,)
        lock_memory.restype = ctypes.c_int
        if lock_memory(1 | 2) != 0:  # MCL_CURRENT | MCL_FUTURE
            raise OSError(ctypes.get_errno(), "mlockall")
    except (OSError, ValueError, AttributeError) as exc:
        raise ValueError(
            "representative page protection unavailable (core/dump/mlockall)"
        ) from exc



def copy_fixture(source_path, destination_path):
    """Create one stable private fixture snapshot; protect first if representative."""
    source_path = Path(source_path)
    destination_path = Path(destination_path)
    representative = fixture_is_representative(source_path)
    if representative:
        protect_private_memory()

    source_flags = (os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) |
                    getattr(os, "O_NOFOLLOW", 0))
    destination_flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         getattr(os, "O_CLOEXEC", 0) |
                         getattr(os, "O_NOFOLLOW", 0))
    source_fd = destination_fd = -1
    try:
        source_fd = os.open(os.fspath(source_path), source_flags)
        before = os.fstat(source_fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
            raise ValueError("fixture snapshot source must be a nonempty regular file")
        destination_fd = os.open(
            os.fspath(destination_path), destination_flags, 0o600)
        os.fchmod(destination_fd, 0o600)

        remaining = before.st_size
        while remaining:
            chunk = os.read(source_fd, min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("fixture snapshot source changed while copying")
            view = memoryview(chunk)
            while view:
                written = os.write(destination_fd, view)
                if written <= 0:
                    raise OSError("short fixture snapshot write")
                view = view[written:]
            remaining -= len(chunk)
        if os.read(source_fd, 1):
            raise ValueError("fixture snapshot source changed while copying")

        after = os.fstat(source_fd)
        before_identity = (before.st_dev, before.st_ino, before.st_size,
                           before.st_mtime_ns, before.st_ctime_ns)
        after_identity = (after.st_dev, after.st_ino, after.st_size,
                          after.st_mtime_ns, after.st_ctime_ns)
        if before_identity != after_identity:
            raise ValueError("fixture snapshot source changed while copying")
        os.fsync(destination_fd)
        return representative
    except BaseException:
        try:
            destination_path.unlink()
        except FileNotFoundError:
            pass
        raise
    finally:
        if destination_fd >= 0:
            os.close(destination_fd)
        if source_fd >= 0:
            os.close(source_fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    copy_parser = subparsers.add_parser(
        "copy-fixture", help="create a stable private fixture snapshot")
    copy_parser.add_argument("--source", required=True)
    copy_parser.add_argument("--destination", required=True)
    args = parser.parse_args(argv)
    if args.command == "copy-fixture":
        copy_fixture(args.source, args.destination)
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
