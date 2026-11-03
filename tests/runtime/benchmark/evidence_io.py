#!/usr/bin/env python3
"""Create-only, crash-safe JSON evidence writes for benchmark helpers."""
from __future__ import annotations

import json
import os
import secrets
import signal
import stat
import threading
from pathlib import Path


def write_new_json(path: Path, value: dict) -> None:
    """Atomically publish one new 0600 JSON object without following symlinks."""
    path = Path(path)
    if path.name in ("", ".", ".."):
        raise ValueError("evidence result path must name a file")
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)

    directory_flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
    directory_fd = os.open(parent, directory_flags)
    temporary_name = None
    previous_handlers = None
    if threading.current_thread() is threading.main_thread():
        previous_handlers = (
            signal.signal(signal.SIGINT, signal.SIG_IGN),
            signal.signal(signal.SIGTERM, signal.SIG_IGN),
        )
    try:
        directory_info = os.fstat(directory_fd)
        if not stat.S_ISDIR(directory_info.st_mode):
            raise ValueError("evidence result parent is not a directory")

        payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
        create_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            create_flags |= os.O_NOFOLLOW

        temporary_fd = None
        for _ in range(16):
            candidate = (
                f".{path.name}.swapz-tmp-{os.getpid()}-"
                f"{secrets.token_hex(8)}")
            try:
                temporary_fd = os.open(
                    candidate, create_flags, 0o600, dir_fd=directory_fd)
            except FileExistsError:
                continue
            temporary_name = candidate
            break
        if temporary_fd is None:
            raise FileExistsError("cannot allocate unique evidence temporary")

        try:
            offset = 0
            while offset < len(payload):
                written = os.write(temporary_fd, payload[offset:])
                if written <= 0:
                    raise OSError("short evidence JSON write")
                offset += written
            os.fsync(temporary_fd)
        finally:
            os.close(temporary_fd)

        # Hard-link publication is atomic and refuses an existing file or
        # symlink at the destination. The temporary inode is never exposed as
        # the requested result until its complete bytes have been fsync'd.
        os.link(
            temporary_name, path.name,
            src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
            follow_symlinks=False)
        os.unlink(temporary_name, dir_fd=directory_fd)
        temporary_name = None
        os.fsync(directory_fd)
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)
        if previous_handlers is not None:
            signal.signal(signal.SIGINT, previous_handlers[0])
            signal.signal(signal.SIGTERM, previous_handlers[1])
