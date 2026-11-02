#!/usr/bin/env python3
"""Fail-closed protection for owner-supplied representative anonymous pages.

The caller must opt in before reading content. Locking lasts for the process
lifetime; all child processes accessing pages independently protect themselves.
"""
import ctypes
import json
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
