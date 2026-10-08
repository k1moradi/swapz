#!/usr/bin/env python3
"""Source-only proposed allowlist for direct V2.2 recall dd workers.

This module cannot start, signal or reap processes and does not open a block
device. A future *trusted* supervisor launcher may obtain a role-scoped,
one-use argument vector from this policy. This module is NOT wired into the
IPC service or production buffer-recall.sh.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
from typing import Sequence


PAGE_SIZE = 4096
PAGES = 9
_MAPPER = re.compile(r"swapz-v22-recall-[A-Za-z0-9_-]{1,48}\Z")
_READS = {"a": 0, "b": 4, "a2": 0, "b2": 5}
_ROLES = frozenset(("writer", *_READS))


class DDPolicyDenied(ValueError):
    """No direct-I/O command may be launched after invalid admission."""


@dataclass(frozen=True)
class DirectDDCommand:
    role: str
    argv: tuple[str, ...]
    page: int | None


def _file_identity(path: Path, *, directory: bool, size: int | None = None) -> tuple[int, int]:
    """No-follow identity check, not a guarantee against later path swaps."""
    try:
        info = path.lstat()
    except OSError as exc:
        raise DDPolicyDenied(f"cannot inspect recall fixture path: {path}: {exc}") from exc
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if not kind(info.st_mode) or (not directory and info.st_nlink != 1):
        raise DDPolicyDenied(f"unsafe recall fixture path type or links: {path}")
    if size is not None and info.st_size != size:
        raise DDPolicyDenied(f"recall fixture source has wrong size: {path}")
    if path != Path(os.path.realpath(path)):
        raise DDPolicyDenied(f"fixture path uses a symlink or noncanonical ancestor: {path}")
    return info.st_dev, info.st_ino


class RecallDDAllowlist:
    """Fixed direct dd grammar, rooted in an already-owned private fixture dir.

    Role names are the only future service request input. The mapper name and
    fixture root must be bound by a trusted launcher, NOT by arbitrary clients.
    Any failed admission closes the policy permanently.
    """

    def __init__(self, fixture_dir: Path, mapper_name: str) -> None:
        self._closed = False
        self._issued: set[str] = set()
        if not isinstance(fixture_dir, Path) or not fixture_dir.is_absolute():
            raise DDPolicyDenied("fixture directory must be an absolute Path")
        if (str(fixture_dir) != os.path.normpath(str(fixture_dir))
                or not isinstance(mapper_name, str)
                or _MAPPER.fullmatch(mapper_name) is None):
            raise DDPolicyDenied("fixture root or mapper name not allowlisted")
        self.directory = fixture_dir
        self.mapper = f"/dev/mapper/{mapper_name}"
        self.source = self.directory / "pages.bin"
        self._directory_id = _file_identity(self.directory, directory=True)
        self._source_id = _file_identity(self.source, directory=False,
                                         size=PAGE_SIZE * PAGES)

    def _deny(self, reason: str) -> None:
        self._closed = True
        raise DDPolicyDenied(reason)

    def _check_identity(self) -> None:
        try:
            if (_file_identity(self.directory, directory=True) != self._directory_id
                    or _file_identity(self.source, directory=False,
                                      size=PAGE_SIZE * PAGES) != self._source_id):
                self._deny("fixture root/source identity changed")
        except (OSError, DDPolicyDenied) as exc:
            self._deny(f"fixture identity is untrustworthy: {exc}")

    def _command(self, role: str) -> DirectDDCommand:
        if role == "writer":
            return DirectDDCommand(role, (
                "dd", f"if={self.source}", f"of={self.mapper}",
                "bs=4096", "count=9", "oflag=direct", "conv=notrunc",
                "status=none",
            ), None)
        page = _READS[role]
        return DirectDDCommand(role, (
            "dd", f"if={self.mapper}",
            f"of={self.directory / ('read-' + role)}",
            "bs=4096", f"skip={page}", "count=1",
            "iflag=direct", "status=none",
        ), page)

    def admit(self, role: str, proposed_argv: Sequence[str] | None = None) -> DirectDDCommand:
        if self._closed:
            raise DDPolicyDenied("direct dd launch admission permanently closed")
        if not isinstance(role, str) or role not in _ROLES:
            self._deny("unknown recall direct dd role")
        if role in self._issued:
            self._deny("repeated recall direct dd role")
        if role != "writer" and "writer" not in self._issued:
            self._deny("reader attempted before fixture writer")
        self._check_identity()
        command = self._command(role)
        if proposed_argv is not None:
            if (not isinstance(proposed_argv, (tuple, list))
                    or any(not isinstance(v, str) for v in proposed_argv)
                    or tuple(proposed_argv) != command.argv):
                self._deny("unapproved direct dd argv or path")
        if role != "writer":
            output = self.directory / ("read-" + role)
            if os.path.lexists(output):
                self._deny("readback path already exists (including links)")
        self._issued.add(role)
        return command

    def close_admission(self) -> None:
        self._closed = True

    @property
    def roles_issued(self) -> tuple[str, ...]:
        return tuple(role for role in ("writer", "a", "b", "a2", "b2")
                     if role in self._issued)


__all__ = ["RecallDDAllowlist", "DDPolicyDenied", "DirectDDCommand"]
