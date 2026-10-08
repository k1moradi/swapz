#!/usr/bin/env python3
"""Rootless readback attestation for descriptor-pinned V2.2 recall workers.

The trusted launcher retains directory/output descriptors until every direct
worker is reaped and comparison finishes.  The returned identity is bound
*before* the worker launches; callers must never derive identity from a
potentially replaced pathname after I/O.  No mapper or device is opened here.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import stat


PAGE_SIZE = 4096
_READ_ROLES = frozenset(("a", "b", "a2", "b2"))


class ReadbackIdentityError(RuntimeError):
    """Untrustworthy output or reference: preserve backing."""


@dataclass(frozen=True)
class PinnedReadbackIdentity:
    role: str
    directory_device: int
    directory_inode: int
    output_device: int
    output_inode: int


def _checked_objects(directory_fd: int, output_fd: int, role: str) -> tuple[os.stat_result, os.stat_result]:
    if (type(directory_fd) is not int or directory_fd < 0
            or type(output_fd) is not int or output_fd < 0
            or type(role) is not str or role not in _READ_ROLES):
        raise ReadbackIdentityError("invalid pinned readback descriptors or role")
    directory = os.fstat(directory_fd)
    output = os.fstat(output_fd)
    if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.geteuid()
            or directory.st_mode & 0o077):
        raise ReadbackIdentityError("pinned readback directory is not private")
    if (not stat.S_ISREG(output.st_mode) or output.st_nlink != 1
            or output.st_uid != os.geteuid() or output.st_mode & 0o022):
        raise ReadbackIdentityError("pinned readback output is not an owned single-link regular file")
    entry = os.stat("read-" + role, dir_fd=directory_fd, follow_symlinks=False)
    if (not stat.S_ISREG(entry.st_mode)
            or (entry.st_dev, entry.st_ino) != (output.st_dev, output.st_ino)):
        raise ReadbackIdentityError("readback pathname no longer identifies pinned output")
    return directory, output


def capture_readback_identity(directory_fd: int, output_fd: int, role: str) -> PinnedReadbackIdentity:
    """Capture the already exclusively created readback inode before launch.

    Descriptors are borrowed, not consumed or closed.  A caller must retain
    both until the worker is reaped and verify_readback() returns.
    """
    try:
        directory, output = _checked_objects(directory_fd, output_fd, role)
        if output.st_size != 0:
            raise ReadbackIdentityError("new readback output must initially be empty")
        return PinnedReadbackIdentity(
            role, directory.st_dev, directory.st_ino, output.st_dev, output.st_ino
        )
    except (OSError, ReadbackIdentityError) as exc:
        raise ReadbackIdentityError(f"cannot capture pinned readback: {exc}; preserve backing") from exc


def verify_readback(identity: PinnedReadbackIdentity, *,
                    directory_fd: int, output_fd: int, expected_page: bytes) -> None:
    """Compare the *pinned* output object against immutable expected bytes.

    A worker is required to have been successfully reaped by its pidfd owner
    before this function is called. Reopen the retained O_WRONLY output via
    procfs as O_RDONLY and verify the exact underlying device/inode. Do not
    silently fall back to opening the potentially replaced output pathname.
    File/path identity is checked both before and after the bounded read.
    """
    if (not isinstance(identity, PinnedReadbackIdentity)
            or type(expected_page) is not bytes or len(expected_page) != PAGE_SIZE):
        raise ReadbackIdentityError("invalid trusted readback identity or expected page")
    try:
        directory, output = _checked_objects(directory_fd, output_fd, identity.role)
        if ((directory.st_dev, directory.st_ino)
                != (identity.directory_device, identity.directory_inode)
                or (output.st_dev, output.st_ino)
                != (identity.output_device, identity.output_inode)
                or output.st_size != PAGE_SIZE):
            raise ReadbackIdentityError("pinned readback identity or exact size changed")

        # The gate originally opens the output O_WRONLY, so os.dup() would
        # inherit write-only access. Reopen by held descriptor, never name.
        read_fd = os.open(
            f"/proc/self/fd/{output_fd}",
            os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK,
        )
        try:
            rebound = os.fstat(read_fd)
            if ((rebound.st_dev, rebound.st_ino)
                    != (identity.output_device, identity.output_inode)
                    or not stat.S_ISREG(rebound.st_mode) or rebound.st_size != PAGE_SIZE):
                raise ReadbackIdentityError("reopened descriptor has wrong readback identity")
            contents = os.pread(read_fd, PAGE_SIZE + 1, 0)
            if contents != expected_page:
                raise ReadbackIdentityError("pinned readback does not match trusted 4096-byte page")
            rebound = os.fstat(read_fd)
            if ((rebound.st_dev, rebound.st_ino)
                    != (identity.output_device, identity.output_inode)
                    or rebound.st_size != PAGE_SIZE):
                raise ReadbackIdentityError("readback changed during verification")
        finally:
            os.close(read_fd)

        checked_dir, checked_output = _checked_objects(directory_fd, output_fd, identity.role)
        if ((checked_dir.st_dev, checked_dir.st_ino)
                != (identity.directory_device, identity.directory_inode)
                or (checked_output.st_dev, checked_output.st_ino)
                != (identity.output_device, identity.output_inode)
                or checked_output.st_size != PAGE_SIZE):
            raise ReadbackIdentityError("readback changed after comparison")
    except (OSError, ReadbackIdentityError) as exc:
        raise ReadbackIdentityError(f"cannot attest pinned readback: {exc}; preserve backing") from exc
