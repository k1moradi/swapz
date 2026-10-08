#!/usr/bin/env python3
"""Role policy and descriptor-pinned launch gate for V2.2 recall dd workers.

The path-only ``RecallDDAllowlist`` is a source-only command planner. The
separately opt-in ``RecallDDLaunchGate`` binds descriptors for a trusted
service bootstrap; tests provide an ordinary synthetic file as the mapper
descriptor and a fake supervisor. No test starts dd or performs device I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
import fcntl
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


@dataclass(frozen=True)
class PinnedDDLaunch:
    """One fixed dd command whose inputs are pinned by inherited descriptors."""

    role: str
    argv: tuple[str, ...]
    page: int | None
    executable: str
    executable_fd: int
    pass_fds: tuple[int, ...]
    output_path: Path | None = None


class RecallDDFileOps:
    """Replaceable filesystem boundary for launch-policy regression tests."""

    def open(self, path: str, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        return os.open(path, flags, mode, dir_fd=dir_fd)

    def close(self, fd: int) -> None:
        os.close(fd)

    def fstat(self, fd: int) -> os.stat_result:
        return os.fstat(fd)

    def stat(self, path: str, *, dir_fd: int, follow_symlinks: bool) -> os.stat_result:
        return os.stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)

    def dup_cloexec(self, fd: int) -> int:
        return fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 3)

    def inheritable(self, fd: int) -> bool:
        return os.get_inheritable(fd)

    def pread(self, fd: int, count: int, offset: int) -> bytes:
        return os.pread(fd, count, offset)

    def access(self, path: str, mode: int) -> bool:
        return os.access(path, mode, effective_ids=True)


def _verify_dm_descriptor(fd: int, mapper_name: str, ops: RecallDDFileOps) -> None:
    info = ops.fstat(fd)
    if not stat.S_ISBLK(info.st_mode):
        raise DDPolicyDenied("trusted mapper descriptor is not a block device")
    major, minor = os.major(info.st_rdev), os.minor(info.st_rdev)
    dm_name = Path(f"/sys/dev/block/{major}:{minor}/dm/name")
    try:
        with dm_name.open("r", encoding="ascii") as handle:
            actual = handle.read(256)
    except OSError as exc:
        raise DDPolicyDenied(f"cannot verify DM identity for mapper descriptor: {exc}") from exc
    if actual != mapper_name + "\n":
        raise DDPolicyDenied("mapper descriptor does not identify the bound test mapping")


def open_test_mapper_fd(mapper_name: str, *, ops: RecallDDFileOps | None = None) -> int:
    """Open and verify only the trusted, grammar-checked test mapper name.

    This helper is for a trusted service bootstrap, never an IPC operation.
    It performs no read or write I/O.  Callers must close the returned fd after
    constructing ``RecallDDLaunchGate``.
    """
    if not isinstance(mapper_name, str) or _MAPPER.fullmatch(mapper_name) is None:
        raise DDPolicyDenied("test mapper name not allowlisted")
    file_ops = ops if ops is not None else RecallDDFileOps()
    path = f"/dev/mapper/{mapper_name}"
    try:
        fd = file_ops.open(path, os.O_RDWR | os.O_CLOEXEC | os.O_NONBLOCK)
    except OSError as exc:
        raise DDPolicyDenied(f"cannot open bound test mapper: {exc}") from exc
    try:
        if file_ops.inheritable(fd):
            raise DDPolicyDenied("mapper descriptor is not close-on-exec")
        _verify_dm_descriptor(fd, mapper_name, file_ops)
        return fd
    except Exception as original:
        try:
            file_ops.close(fd)
        except Exception as close_error:
            raise DDPolicyDenied(
                f"mapper identity failed and descriptor close also failed: {close_error}"
            ) from original
        raise


class RecallDDLaunchGate:
    """Trusted, descriptor-bound admission for the five recall dd roles.

    This is deliberately separate from ``RecallDDAllowlist`` and is disabled
    unless an explicitly configured service is constructed with an instance.
    The mapper fd must come from ``open_test_mapper_fd`` or another trusted
    bootstrap that verified the exact test mapping.  IPC callers provide only
    a role string; they can never choose a path, executable, fd, or argv.
    """

    def __init__(
        self,
        fixture_dir: Path,
        mapper_name: str,
        *,
        mapper_fd: int,
        executable_path: Path = Path("/usr/bin/dd"),
        ops: RecallDDFileOps | None = None,
        mapper_verifier=None,
    ) -> None:
        self.ops = ops if ops is not None else RecallDDFileOps()
        self._closed = False
        self._close_attempted = False
        self._close_errors: tuple[str, ...] = ()
        self._issued: set[str] = set()
        self._owned_fds: list[int] = []
        self._output_fds: dict[str, int] = {}
        self._mapper_name = mapper_name
        self._directory_path = fixture_dir
        self._directory_identity: tuple[int, int] | None = None
        self._source_identity: tuple[int, int] | None = None
        self._source_fd: int | None = None
        self._mapper_fd: int | None = None
        self._executable_fd: int | None = None

        if not isinstance(fixture_dir, Path) or not fixture_dir.is_absolute():
            raise DDPolicyDenied("fixture directory must be an absolute Path")
        if (str(fixture_dir) != os.path.normpath(str(fixture_dir))
                or not isinstance(mapper_name, str)
                or _MAPPER.fullmatch(mapper_name) is None):
            raise DDPolicyDenied("fixture root or mapper name not allowlisted")
        if isinstance(mapper_fd, bool) or not isinstance(mapper_fd, int) or mapper_fd < 0:
            raise DDPolicyDenied("trusted mapper descriptor is invalid")
        if self.ops.inheritable(mapper_fd):
            raise DDPolicyDenied("trusted mapper descriptor must be close-on-exec")
        if not isinstance(executable_path, Path) or not executable_path.is_absolute():
            raise DDPolicyDenied("pinned dd executable path must be absolute")

        verify_mapper = _verify_dm_descriptor if mapper_verifier is None else mapper_verifier
        self._mapper_verifier = verify_mapper
        try:
            self._directory_fd = self._open_directory_chain(fixture_dir)
            self._owned_fds.append(self._directory_fd)
            directory_stat = self.ops.fstat(self._directory_fd)
            if (not stat.S_ISDIR(directory_stat.st_mode)
                    or directory_stat.st_uid != os.geteuid()
                    or directory_stat.st_mode & 0o077
                    or self.ops.inheritable(self._directory_fd)):
                raise DDPolicyDenied("fixture directory must be private and owned by the service")
            self._directory_identity = (directory_stat.st_dev, directory_stat.st_ino)

            self._source_fd = self.ops.open(
                "pages.bin", os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=self._directory_fd,
            )
            self._owned_fds.append(self._source_fd)
            source_stat = self.ops.fstat(self._source_fd)
            if self.ops.inheritable(self._source_fd):
                raise DDPolicyDenied("source descriptor is not close-on-exec")
            self._validate_source_stat(source_stat)
            self._source_identity = (source_stat.st_dev, source_stat.st_ino)
            self._verify_source_entry()

            self._mapper_fd = self.ops.dup_cloexec(mapper_fd)
            self._owned_fds.append(self._mapper_fd)
            if self.ops.inheritable(self._mapper_fd):
                raise DDPolicyDenied("retained mapper descriptor is not close-on-exec")
            mapper_verified = verify_mapper(self._mapper_fd, mapper_name, self.ops)
            if mapper_verified is False:
                raise DDPolicyDenied("trusted mapper descriptor identity was rejected")

            self._executable_fd = self.ops.open(
                str(executable_path), os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK,
            )
            self._owned_fds.append(self._executable_fd)
            self._verify_executable()
            try:
                proc_fd = self.ops.stat("/proc/self/fd", dir_fd=self._directory_fd,
                                        follow_symlinks=True)
            except OSError as exc:
                raise DDPolicyDenied(f"/proc/self/fd is unavailable for pinned exec: {exc}") from exc
            if not stat.S_ISDIR(proc_fd.st_mode):
                raise DDPolicyDenied("/proc/self/fd is not a directory")
        except Exception as exc:
            close_errors = self.close()
            detail = "; ".join(close_errors)
            if isinstance(exc, DDPolicyDenied):
                message = str(exc)
            else:
                message = f"cannot bind direct dd launch descriptors: {exc}"
            if detail:
                message += f"; descriptor cleanup failed: {detail}"
            raise DDPolicyDenied(message) from exc

    def _open_directory_chain(self, path: Path) -> int:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        current = self.ops.open("/", flags)
        for component in path.parts[1:]:
            try:
                next_fd = self.ops.open(component, flags, dir_fd=current)
            except Exception as open_error:
                try:
                    self.ops.close(current)
                except Exception as close_error:
                    raise DDPolicyDenied(
                        f"fixture traversal failed ({open_error}); directory close failed ({close_error})"
                    ) from open_error
                raise
            try:
                self.ops.close(current)
            except Exception as exc:
                try:
                    self.ops.close(next_fd)
                except Exception as close_error:
                    raise DDPolicyDenied(
                        f"traversed directory close failed ({exc}); next descriptor close failed ({close_error})"
                    ) from exc
                raise DDPolicyDenied(f"cannot close traversed fixture directory descriptor: {exc}") from exc
            current = next_fd
        return current

    def _validate_source_stat(self, info: os.stat_result) -> None:
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_size != PAGE_SIZE * PAGES or info.st_uid != os.geteuid()
                or info.st_mode & 0o022):
            raise DDPolicyDenied("source must be an owned, single-link, exact-size regular file")

    def _verify_source_entry(self) -> None:
        assert self._source_fd is not None and self._directory_fd is not None
        self._verify_directory_path()
        entry = self.ops.stat("pages.bin", dir_fd=self._directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(entry.st_mode) or (entry.st_dev, entry.st_ino) != self._source_identity:
            raise DDPolicyDenied("fixture source entry or pinned identity changed")
        current = self.ops.fstat(self._source_fd)
        identity = (current.st_dev, current.st_ino)
        if identity != self._source_identity:
            raise DDPolicyDenied("fixture source entry or pinned identity changed")
        self._validate_source_stat(current)

    def _verify_directory_path(self) -> None:
        assert self._directory_identity is not None
        try:
            current_fd = self._open_directory_chain(self._directory_path)
        except Exception as exc:
            raise DDPolicyDenied(f"fixture directory path cannot be revalidated: {exc}") from exc
        try:
            info = self.ops.fstat(current_fd)
            if (info.st_dev, info.st_ino) != self._directory_identity:
                raise DDPolicyDenied("fixture directory path identity changed")
        finally:
            try:
                self.ops.close(current_fd)
            except Exception as exc:
                raise DDPolicyDenied(f"fixture path descriptor close failed: {exc}") from exc

    def _verify_executable(self) -> None:
        assert self._executable_fd is not None
        info = self.ops.fstat(self._executable_fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid not in {0, os.geteuid()}
                or info.st_mode & 0o022 or not info.st_mode & 0o111
                or self.ops.pread(self._executable_fd, 4, 0) != b"\x7fELF"
                or self.ops.inheritable(self._executable_fd)):
            raise DDPolicyDenied("dd executable identity is not trusted ELF")
        if not self.ops.access(f"/proc/self/fd/{self._executable_fd}", os.X_OK):
            raise DDPolicyDenied("pinned dd executable is not executable by the service")

    def _deny(self, reason: str) -> None:
        self._closed = True
        raise DDPolicyDenied(reason)

    def close_admission(self) -> None:
        self._closed = True

    def admit(self, role: str) -> PinnedDDLaunch:
        if self._closed or self._close_attempted:
            raise DDPolicyDenied("direct dd launch admission permanently closed")
        if not isinstance(role, str) or role not in _ROLES:
            self._deny("unknown recall direct dd role")
        if role in self._issued:
            self._deny("repeated recall direct dd role")
        if role != "writer" and "writer" not in self._issued:
            self._deny("reader attempted before fixture writer")
        try:
            self._verify_source_entry()
            assert self._mapper_fd is not None and self._executable_fd is not None
            mapper_info = self.ops.fstat(self._mapper_fd)
            if self.ops.inheritable(self._mapper_fd):
                self._deny("retained mapper descriptor became inheritable")
            if (not stat.S_ISREG(mapper_info.st_mode) and not stat.S_ISBLK(mapper_info.st_mode)):
                self._deny("retained mapper descriptor type changed")
            mapper_verified = self._mapper_verifier(self._mapper_fd, self._mapper_name, self.ops)
            if mapper_verified is False:
                self._deny("retained mapper descriptor identity no longer matches")
            self._verify_executable()
        except DDPolicyDenied:
            self._closed = True
            raise
        except Exception as exc:
            self._deny(f"cannot verify pinned launch identity: {exc}")

        page: int | None = None
        output_path: Path | None = None
        fds = [self._source_fd, self._mapper_fd]
        if role == "writer":
            assert self._source_fd is not None and self._mapper_fd is not None
            argv = (
                "dd", f"if=/proc/self/fd/{self._source_fd}",
                f"of=/proc/self/fd/{self._mapper_fd}", "bs=4096", "count=9",
                "oflag=direct", "conv=notrunc", "status=none",
            )
        else:
            page = _READS[role]
            assert self._directory_fd is not None and self._mapper_fd is not None
            output_name = "read-" + role
            try:
                output_fd = self.ops.open(
                    output_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW |
                    os.O_CLOEXEC | os.O_NONBLOCK,
                    0o600,
                    dir_fd=self._directory_fd,
                )
            except Exception as exc:
                self._deny(f"readback output path already exists or cannot be created: {exc}")
            self._owned_fds.append(output_fd)
            self._output_fds[role] = output_fd
            try:
                info = self.ops.fstat(output_fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                        or info.st_uid != os.geteuid() or self.ops.inheritable(output_fd)):
                    self._deny("new readback output descriptor is not a private regular file")
                output_entry = self.ops.stat(output_name, dir_fd=self._directory_fd,
                                             follow_symlinks=False)
                if ((output_entry.st_dev, output_entry.st_ino) != (info.st_dev, info.st_ino)
                        or not stat.S_ISREG(output_entry.st_mode)):
                    self._deny("readback output entry changed during exclusive creation")
            except DDPolicyDenied:
                raise
            except Exception as exc:
                self._deny(f"cannot verify newly created output descriptor: {exc}")
            output_path = self._directory_path / output_name
            argv = (
                "dd", f"if=/proc/self/fd/{self._mapper_fd}",
                f"of=/proc/self/fd/{output_fd}", "bs=4096", f"skip={page}",
                "count=1", "iflag=direct", "status=none",
            )
            fds.append(output_fd)

        assert self._executable_fd is not None
        self._issued.add(role)
        return PinnedDDLaunch(
            role, argv, page, f"/proc/self/fd/{self._executable_fd}", self._executable_fd,
            tuple(fd for fd in fds if fd is not None), output_path,
        )

    def close(self) -> tuple[str, ...]:
        if self._close_attempted:
            return self._close_errors
        self._close_attempted = True
        self._closed = True
        errors: list[str] = []
        for fd in reversed(self._owned_fds):
            try:
                self.ops.close(fd)
            except Exception as exc:
                errors.append(f"close direct dd descriptor {fd}: {exc}")
        self._owned_fds.clear()
        self._close_errors = tuple(errors)
        return self._close_errors

    @property
    def roles_issued(self) -> tuple[str, ...]:
        return tuple(role for role in ("writer", "a", "b", "a2", "b2")
                     if role in self._issued)


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


__all__ = [
    "RecallDDAllowlist", "RecallDDLaunchGate", "PinnedDDLaunch", "RecallDDFileOps",
    "open_test_mapper_fd", "DDPolicyDenied", "DirectDDCommand",
]
