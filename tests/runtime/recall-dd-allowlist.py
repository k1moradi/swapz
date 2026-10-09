#!/usr/bin/env python3
"""Role policy and descriptor-pinned launch gate for V2.2 recall dd workers.

The path-only ``RecallDDAllowlist`` is a source-only command planner. The
separately opt-in ``RecallDDLaunchGate`` binds descriptors for a trusted
service bootstrap; policy tests provide synthetic files and fake kernel DM
identity. A separate worker integration test starts dd only against temporary
ordinary files; no mapper or device I/O is performed.
"""

from __future__ import annotations

from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import fcntl
from typing import Callable, Sequence


PAGE_SIZE = 4096
PAGES = 9
_MAPPER = re.compile(r"swapz-v22-recall-[A-Za-z0-9_-]{1,48}\Z")
_READS = {"a": 0, "b": 4, "a2": 0, "b2": 5}
_ROLES = frozenset(("writer", *_READS))
_TRUSTED_DD_TOKEN = object()
_TRUSTED_DD_FIELDS = frozenset((
    "format", "vendor", "package", "binary", "version", "executable",
    "sha256", "source_sha256", "linkage",
))


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


@dataclass(frozen=True, init=False)
class TrustedGNUCoreutilsDD:
    """Digest and provenance parsed only from a verified bootstrap manifest.

    The signature verifier is supplied by trusted bootstrap code and must be
    anchored to an independently managed key. Tests may inject a fake
    verifier, which proves parser policy only, not GNU binary provenance.
    """

    executable_path: Path
    sha256: str
    version: str
    source_sha256: str
    manifest_sha256: str
    _token: object

    def __init__(self, executable_path: Path, sha256: str, version: str,
                 source_sha256: str, manifest_sha256: str, *, _token: object):
        if _token is not _TRUSTED_DD_TOKEN:
            raise DDPolicyDenied("trusted GNU dd identities require a verified manifest")
        object.__setattr__(self, "executable_path", executable_path)
        object.__setattr__(self, "sha256", sha256)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "source_sha256", source_sha256)
        object.__setattr__(self, "manifest_sha256", manifest_sha256)
        object.__setattr__(self, "_token", _token)

    @classmethod
    def from_signed_manifest(
        cls,
        payload: bytes,
        signature: bytes,
        verifier: Callable[[bytes, bytes], bool],
    ) -> "TrustedGNUCoreutilsDD":
        """Verify and parse a strict signed manifest; never trust candidate bytes.

        ``verifier`` is part of the trusted bootstrap and must verify the
        detached signature with a separately controlled trust anchor. There
        is intentionally no default verifier or PATH/package-manager fallback.
        """
        if (not isinstance(payload, bytes) or not payload or len(payload) > 16384
                or not isinstance(signature, bytes) or not signature
                or len(signature) > 8192 or not callable(verifier)):
            raise DDPolicyDenied("trusted GNU dd manifest or verifier is invalid")
        try:
            verified = verifier(payload, signature)
        except Exception as exc:
            raise DDPolicyDenied(f"trusted GNU dd manifest verification failed: {exc}") from exc
        if verified is not True:
            raise DDPolicyDenied("trusted GNU dd manifest signature was not verified")

        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate manifest key: {key}")
                result[key] = value
            return result

        try:
            document = json.loads(payload, object_pairs_hook=unique_object)
            if not isinstance(document, dict) or set(document) != _TRUSTED_DD_FIELDS:
                raise ValueError("manifest fields do not match the required schema")
            executable = document["executable"]
            if (type(document["format"]) is not int or document["format"] != 1
                    or document["vendor"] != "GNU Project"
                    or document["package"] != "coreutils"
                    or document["binary"] != "dd"
                    or not isinstance(document["version"], str)
                    or re.fullmatch(r"[A-Za-z0-9.+_-]{1,64}", document["version"]) is None
                    or not isinstance(executable, str)
                    or not os.path.isabs(executable) or "\x00" in executable
                    or os.path.normpath(executable) != executable
                    or not isinstance(document["sha256"], str)
                    or re.fullmatch(r"[0-9a-f]{64}", document["sha256"]) is None
                    or not isinstance(document["source_sha256"], str)
                    or re.fullmatch(r"[0-9a-f]{64}", document["source_sha256"]) is None
                    or document["linkage"] != "static"):
                raise ValueError("manifest does not name a trusted static GNU coreutils dd build")
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DDPolicyDenied(f"trusted GNU dd manifest is malformed: {exc}") from exc
        return cls(
            Path(executable), document["sha256"], document["version"],
            document["source_sha256"], hashlib.sha256(payload).hexdigest(),
            _token=_TRUSTED_DD_TOKEN,
        )


@dataclass(frozen=True)
class MapperIdentity:
    """Expected kernel-visible identity from a trusted fixture owner."""

    name: str
    uuid: str
    major: int
    minor: int
    table_sha256: str

    def __post_init__(self) -> None:
        if (not isinstance(self.name, str) or _MAPPER.fullmatch(self.name) is None
                or not isinstance(self.uuid, str) or not self.uuid
                or len(self.uuid) > 128 or any(ord(c) < 0x21 or ord(c) > 0x7e for c in self.uuid)
                or isinstance(self.major, bool) or not isinstance(self.major, int)
                or isinstance(self.minor, bool) or not isinstance(self.minor, int)
                or not 0 <= self.major <= 4095 or not 0 <= self.minor <= 1048575
                or not isinstance(self.table_sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", self.table_sha256) is None):
            raise DDPolicyDenied("trusted mapper identity is malformed")


class MapperLifecycleLease:
    """Cooperative exclusive lifecycle lock plus exact identity revalidation.

    The trusted fixture owner must acquire this lock *before* creating the DM
    mapping and keep exclusive control of every table/name lifecycle operation.
    A fingerprint comparison detects change; the lock is only a guarantee when
    every privileged fixture operation obeys this owner protocol.
    """

    def __init__(self, lock_fd: int, lock_path: Path, expected: MapperIdentity,
                 identity_reader: Callable[[int, str, "RecallDDFileOps"], MapperIdentity],
                 *, ops: "RecallDDFileOps") -> None:
        if type(expected) is not MapperIdentity or not callable(identity_reader):
            raise DDPolicyDenied("mapper lifecycle identity provider is unavailable")
        if (not isinstance(lock_path, Path) or not lock_path.is_absolute()
                or str(lock_path) != os.path.normpath(str(lock_path))):
            raise DDPolicyDenied("fixture mapper lifecycle lock path is invalid")
        self.ops = ops
        self._expected = expected
        self.identity_reader = identity_reader
        self._lock_path = lock_path
        self._closed = False
        self._lock_fd: int | None = None
        try:
            if self.ops.inheritable(lock_fd):
                raise DDPolicyDenied("fixture owner lock descriptor must be close-on-exec")
            self._lock_fd = self.ops.dup_cloexec(lock_fd)
            info = self.ops.fstat(self._lock_fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_nlink != 1 or info.st_mode & 0o077
                    or self.ops.inheritable(self._lock_fd)):
                raise DDPolicyDenied("mapper lifecycle lock is not a private owned file")
            self._verify_owner_lock_held()
        except Exception as exc:
            try:
                self.close()
            except Exception as close_error:
                raise DDPolicyDenied(
                    f"mapper lifecycle lease acquisition failed ({exc}); descriptor close failed ({close_error})"
                ) from exc
            if isinstance(exc, DDPolicyDenied):
                raise
            raise DDPolicyDenied(f"cannot verify exclusive fixture owner lock: {exc}") from exc

    def verify(self, mapper_fd: int, mapper_name: str,
               ops: "RecallDDFileOps") -> None:
        if self._closed or self._lock_fd is None:
            raise DDPolicyDenied("mapper lifecycle lease is closed")
        if mapper_name != self.expected.name:
            raise DDPolicyDenied("mapper name does not match trusted lifecycle lease")
        try:
            lock_info = ops.fstat(self._lock_fd)
            if (not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.geteuid()
                    or lock_info.st_nlink != 1 or lock_info.st_mode & 0o077
                    or ops.inheritable(self._lock_fd)):
                raise DDPolicyDenied("mapper lifecycle lock identity changed")
            self._verify_owner_lock_held(ops)
            observed = self.identity_reader(mapper_fd, mapper_name, ops)
        except DDPolicyDenied:
            raise
        except Exception as exc:
            raise DDPolicyDenied(f"cannot verify mapper lifecycle identity: {exc}") from exc
        if type(observed) is not MapperIdentity or observed != self.expected:
            raise DDPolicyDenied("DM name, UUID, device number, or table fingerprint changed")

    @property
    def expected(self) -> MapperIdentity:
        return self._expected

    def _verify_owner_lock_held(self, ops: "RecallDDFileOps" | None = None) -> None:
        file_ops = self.ops if ops is None else ops
        if self._lock_fd is None:
            raise DDPolicyDenied("fixture mapper owner lock descriptor is closed")
        owner_info = file_ops.fstat(self._lock_fd)
        try:
            probe_fd = file_ops.open(
                str(self._lock_path), os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW,
            )
        except Exception as exc:
            raise DDPolicyDenied(f"cannot independently inspect fixture owner lock: {exc}") from exc
        try:
            probe_info = file_ops.fstat(probe_fd)
            if (not stat.S_ISREG(probe_info.st_mode)
                    or (probe_info.st_dev, probe_info.st_ino)
                    != (owner_info.st_dev, owner_info.st_ino)
                    or probe_info.st_uid != os.geteuid() or probe_info.st_nlink != 1
                    or probe_info.st_mode & 0o077 or file_ops.inheritable(probe_fd)):
                raise DDPolicyDenied("fixture owner lock pathname or metadata changed")
            try:
                fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno not in {errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK}:
                    raise DDPolicyDenied(f"cannot verify fixture owner lock: {exc}") from exc
            else:
                fcntl.flock(probe_fd, fcntl.LOCK_UN)
                raise DDPolicyDenied("fixture owner does not hold the exclusive lifecycle lock")
        finally:
            try:
                file_ops.close(probe_fd)
            except Exception as exc:
                raise DDPolicyDenied(f"cannot close fixture owner lock probe: {exc}") from exc

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._lock_fd is not None:
            fd, self._lock_fd = self._lock_fd, None
            self.ops.close(fd)


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

    def path_stat(self, path: Path, *, follow_symlinks: bool) -> os.stat_result:
        return os.stat(path, follow_symlinks=follow_symlinks)

    def dup_cloexec(self, fd: int) -> int:
        return fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 3)

    def inheritable(self, fd: int) -> bool:
        return os.get_inheritable(fd)

    def pread(self, fd: int, count: int, offset: int) -> bytes:
        return os.pread(fd, count, offset)

    def access(self, path: str, mode: int) -> bool:
        return os.access(path, mode, effective_ids=True)

    def getxattr(self, fd: int, name: str) -> bytes:
        return os.getxattr(fd, name)

    def read_dm_sysfs_attr(self, major: int, minor: int, attribute: str) -> str:
        if attribute not in {"name", "uuid", "dev"}:
            raise ValueError("unsupported Device Mapper sysfs attribute")
        path = Path(f"/sys/dev/block/{major}:{minor}/dm/{attribute}") if attribute != "dev" else Path(
            f"/sys/dev/block/{major}:{minor}/dev")
        with path.open("r", encoding="ascii") as handle:
            value = handle.read(256)
        if not value.endswith("\n") or len(value) > 256:
            raise OSError(errno.EIO, "malformed Device Mapper sysfs identity")
        return value[:-1]

    def create_sealed_executable(self, source_fd: int, expected_sha256: str,
                                 maximum_size: int) -> int:
        """Copy verified bytes into an executable, write-sealed memfd.

        This closes the in-place modification window between hashing a pinned
        package executable and the worker's execve. Older kernels or hosts
        whose memfd policy disallows executable memfds fail closed.
        """
        if not callable(getattr(os, "memfd_create", None)):
            raise OSError(errno.ENOSYS, "memfd_create is unavailable")
        info = os.fstat(source_fd)
        if info.st_size <= 0 or info.st_size > maximum_size:
            raise OSError(errno.EINVAL, "executable size is outside the verification bound")
        # MFD_EXEC is Linux UAPI 0x0010. Python versions may not expose the
        # constant even when the running kernel supports it.
        flags = (getattr(os, "MFD_CLOEXEC", 0x0001)
                 | getattr(os, "MFD_ALLOW_SEALING", 0x0002)
                 | getattr(os, "MFD_EXEC", 0x0010))
        snapshot_fd = os.memfd_create("swapz-pinned-dd", flags)
        try:
            digest = hashlib.sha256()
            offset = 0
            while offset < info.st_size:
                chunk = os.pread(source_fd, min(1024 * 1024, info.st_size - offset), offset)
                if not chunk or len(chunk) > info.st_size - offset:
                    raise OSError(errno.EIO, "trusted executable changed or truncated while snapshotting")
                digest.update(chunk)
                written_offset = 0
                while written_offset < len(chunk):
                    written = os.write(snapshot_fd, chunk[written_offset:])
                    if written <= 0:
                        raise OSError(errno.EIO, "short write while snapshotting trusted executable")
                    written_offset += written
                offset += len(chunk)
            after = os.fstat(source_fd)
            before_identity = (info.st_dev, info.st_ino, info.st_size,
                               info.st_mtime_ns, info.st_ctime_ns)
            after_identity = (after.st_dev, after.st_ino, after.st_size,
                              after.st_mtime_ns, after.st_ctime_ns)
            if (before_identity != after_identity
                    or digest.hexdigest() != expected_sha256):
                raise OSError(errno.EPERM, "pinned executable does not match trusted SHA-256 identity")

            os.fchmod(snapshot_fd, 0o500)
            required_seals = (getattr(fcntl, "F_SEAL_WRITE", 0x0008)
                              | getattr(fcntl, "F_SEAL_GROW", 0x0004)
                              | getattr(fcntl, "F_SEAL_SHRINK", 0x0002)
                              | getattr(fcntl, "F_SEAL_SEAL", 0x0001)
                              | getattr(fcntl, "F_SEAL_EXEC", 0x0020))
            fcntl.fcntl(snapshot_fd, getattr(fcntl, "F_ADD_SEALS", 1033), required_seals)
            actual_seals = fcntl.fcntl(snapshot_fd, getattr(fcntl, "F_GET_SEALS", 1034))
            if actual_seals & required_seals != required_seals:
                raise OSError(errno.EPERM, "executable memfd is missing required write seals")
            if os.get_inheritable(snapshot_fd):
                raise OSError(errno.EBADF, "executable memfd is unexpectedly inheritable")
            return snapshot_fd
        except Exception as exc:
            try:
                os.close(snapshot_fd)
            except Exception as close_error:
                raise OSError(errno.EIO, f"sealed executable snapshot failed ({exc}); close failed ({close_error})") from exc
            raise


def _verify_dm_descriptor(fd: int, mapper_name: str, ops: RecallDDFileOps,
                          lifecycle_lease: MapperLifecycleLease | None = None) -> None:
    info = ops.fstat(fd)
    if not stat.S_ISBLK(info.st_mode):
        raise DDPolicyDenied("trusted mapper descriptor is not a block device")
    if lifecycle_lease is None:
        raise DDPolicyDenied("trusted exclusive mapper lifecycle lease is required")
    major, minor = os.major(info.st_rdev), os.minor(info.st_rdev)
    expected = lifecycle_lease.expected
    if (major, minor) != (expected.major, expected.minor):
        raise DDPolicyDenied("mapper descriptor device number differs from trusted identity")
    try:
        actual_name = ops.read_dm_sysfs_attr(major, minor, "name")
        actual_uuid = ops.read_dm_sysfs_attr(major, minor, "uuid")
        actual_dev = ops.read_dm_sysfs_attr(major, minor, "dev")
    except OSError as exc:
        raise DDPolicyDenied(f"cannot verify DM identity for mapper descriptor: {exc}") from exc
    if (actual_name != mapper_name or actual_uuid != expected.uuid
            or actual_dev != f"{major}:{minor}"):
        raise DDPolicyDenied("mapper descriptor does not identify the bound test mapping")
    lifecycle_lease.verify(fd, mapper_name, ops)
    return True


def open_test_mapper_fd(mapper_name: str, *,
                        lifecycle_lease: MapperLifecycleLease | None = None,
                        ops: RecallDDFileOps | None = None) -> int:
    """Open and verify only the trusted, grammar-checked test mapper name.

    This helper is for a trusted service bootstrap, never an IPC operation.
    It performs no read or write I/O.  Callers must close the returned fd after
    constructing ``RecallDDLaunchGate``.
    """
    if not isinstance(mapper_name, str) or _MAPPER.fullmatch(mapper_name) is None:
        raise DDPolicyDenied("test mapper name not allowlisted")
    if (type(lifecycle_lease) is not MapperLifecycleLease
            or lifecycle_lease.expected.name != mapper_name):
        raise DDPolicyDenied("trusted fixture mapper lifecycle identity is required")
    file_ops = ops if ops is not None else RecallDDFileOps()
    path = f"/dev/mapper/{mapper_name}"
    try:
        fd = file_ops.open(path, os.O_RDWR | os.O_CLOEXEC | os.O_NONBLOCK)
    except Exception as exc:
        raise DDPolicyDenied(f"cannot open bound test mapper: {exc}") from exc
    try:
        if file_ops.inheritable(fd):
            raise DDPolicyDenied("mapper descriptor is not close-on-exec")
        _verify_dm_descriptor(fd, mapper_name, file_ops, lifecycle_lease)
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
    A real block mapper requires a signed GNU static executable manifest and a
    pre-held fixture-owner lifecycle lease. The mapper fd must come from
    ``open_test_mapper_fd`` or another trusted bootstrap that verified the
    exact test mapping. IPC callers provide only a role string; they can never
    choose a path, executable, fd, or argv.
    """

    def __init__(
        self,
        fixture_dir: Path,
        mapper_name: str,
        *,
        mapper_fd: int,
        executable_path: Path = Path("/usr/bin/dd"),
        expected_executable_sha256: str | None = None,
        trusted_executable: TrustedGNUCoreutilsDD | None = None,
        mapper_lifecycle_lease: MapperLifecycleLease | None = None,
        ops: RecallDDFileOps | None = None,
        mapper_verifier=None,
    ) -> None:
        self.ops = ops if ops is not None else RecallDDFileOps()
        if trusted_executable is not None and type(trusted_executable) is not TrustedGNUCoreutilsDD:
            raise DDPolicyDenied("direct dd identity must come from a verified GNU manifest")
        if mapper_lifecycle_lease is not None and type(mapper_lifecycle_lease) is not MapperLifecycleLease:
            raise DDPolicyDenied("mapper lifecycle proof must come from the trusted fixture owner")
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
        self._synthetic_mapper_identity: tuple[int, int] | None = None
        self._executable_fd: int | None = None
        self._executable_source_fd: int | None = None
        self._sealed_executable_identity: tuple[int, int, int] | None = None
        self._trusted_executable = trusted_executable
        self._expected_executable_sha256 = (
            trusted_executable.sha256 if trusted_executable is not None
            else expected_executable_sha256
        )
        self._mapper_lifecycle_lease = mapper_lifecycle_lease
        self._executable_path = executable_path
        self._executable_source_identity: tuple[int, int] | None = None

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
        mapper_stat = self.ops.fstat(mapper_fd)
        self._mapper_is_block = stat.S_ISBLK(mapper_stat.st_mode)
        if not self._mapper_is_block:
            if (not stat.S_ISREG(mapper_stat.st_mode)
                    or mapper_stat.st_uid != os.geteuid()
                    or mapper_stat.st_nlink != 1
                    or mapper_verifier is None):
                raise DDPolicyDenied(
                    "non-DM mapper descriptor requires an owned regular test file and explicit synthetic verifier"
                )
            self._synthetic_mapper_identity = (mapper_stat.st_dev, mapper_stat.st_ino)
        if trusted_executable is not None:
            if executable_path != trusted_executable.executable_path:
                raise DDPolicyDenied("dd executable path differs from verified trust manifest")
            if expected_executable_sha256 is not None:
                raise DDPolicyDenied("do not combine a trusted manifest with a caller digest")
        if expected_executable_sha256 is not None and re.fullmatch(
            r"[0-9a-f]{64}", expected_executable_sha256
        ) is None:
            raise DDPolicyDenied("trusted executable SHA-256 must be 64 lowercase hexadecimal characters")
        if self._mapper_is_block and trusted_executable is None:
            raise DDPolicyDenied(
                "block-mapper launch requires a signed GNU coreutils trust manifest"
            )
        if self._mapper_is_block and mapper_lifecycle_lease is None:
            raise DDPolicyDenied(
                "block-mapper launch requires a trusted exclusive lifecycle lease"
            )
        if not isinstance(executable_path, Path) or not executable_path.is_absolute():
            raise DDPolicyDenied("pinned dd executable path must be absolute")

        verify_mapper = _verify_dm_descriptor if mapper_verifier is None else mapper_verifier
        if self._mapper_is_block and mapper_verifier is not None:
            # A caller-supplied boolean verifier must not replace the identity
            # checks and lifecycle lock required for a real mapped device.
            verify_mapper = _verify_dm_descriptor
        self._mapper_verifier = verify_mapper
        if self._mapper_is_block and mapper_lifecycle_lease.expected.name != mapper_name:
            raise DDPolicyDenied("mapper lifecycle lease name does not match requested mapping")
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
            if self._mapper_is_block:
                mapper_verified = verify_mapper(
                    self._mapper_fd, mapper_name, self.ops, mapper_lifecycle_lease,
                )
            else:
                mapper_verified = verify_mapper(self._mapper_fd, mapper_name, self.ops)
            if mapper_verified is not True:
                raise DDPolicyDenied("trusted mapper descriptor identity was not positively verified")

            executable_source_fd = self.ops.open(
                str(executable_path), os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK,
            )
            self._executable_source_fd = executable_source_fd
            self._owned_fds.append(executable_source_fd)
            self._verify_executable_source(executable_source_fd)
            source_info = self.ops.fstat(executable_source_fd)
            self._executable_source_identity = (source_info.st_dev, source_info.st_ino)
            if self._mapper_is_block:
                assert self._trusted_executable is not None
                self._executable_fd = self.ops.create_sealed_executable(
                    executable_source_fd, self._trusted_executable.sha256,
                    128 * 1024 * 1024,
                )
                self._owned_fds.append(self._executable_fd)
                snapshot = self.ops.fstat(self._executable_fd)
                self._sealed_executable_identity = (snapshot.st_dev, snapshot.st_ino, snapshot.st_size)
            else:
                self._executable_fd = executable_source_fd
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

    @staticmethod
    def _validate_executable_stat(info) -> None:
        if (not stat.S_ISREG(info.st_mode)
                or info.st_uid not in {0, os.geteuid()}
                or info.st_mode & 0o022
                or not info.st_mode & 0o111
                or info.st_mode & (stat.S_ISUID | stat.S_ISGID)):
            raise DDPolicyDenied("dd executable identity is not trusted ELF")

    def _verify_no_file_capabilities(self, fd: int) -> None:
        try:
            value = self.ops.getxattr(fd, "security.capability")
        except OSError as exc:
            if exc.errno in {getattr(errno, "ENODATA", 61), getattr(errno, "ENOATTR", 61)}:
                return
            raise DDPolicyDenied(f"cannot inspect dd file capabilities: {exc}") from exc
        if value:
            raise DDPolicyDenied("dd executable has file capabilities")

    def _is_static_elf(self, fd: int, size: int) -> bool:
        ident = self.ops.pread(fd, 16, 0)
        if (len(ident) != 16 or ident[:4] != b"\x7fELF"
                or ident[4] not in (1, 2) or ident[5] != 1 or ident[6] != 1):
            raise DDPolicyDenied("trusted GNU dd must be a valid little-endian ELF")
        if ident[4] == 1:
            header = self.ops.pread(fd, 52, 0)
            if len(header) != 52:
                raise DDPolicyDenied("trusted dd ELF header is truncated")
            phoff = int.from_bytes(header[28:32], "little")
            phentsize = int.from_bytes(header[42:44], "little")
            phnum = int.from_bytes(header[44:46], "little")
            minimum_phdr = 32
        else:
            header = self.ops.pread(fd, 64, 0)
            if len(header) != 64:
                raise DDPolicyDenied("trusted dd ELF header is truncated")
            phoff = int.from_bytes(header[32:40], "little")
            phentsize = int.from_bytes(header[54:56], "little")
            phnum = int.from_bytes(header[56:58], "little")
            minimum_phdr = 56
        if phnum == 0:
            return True
        if (phentsize < minimum_phdr or phnum > 1024
                or phoff > size or phentsize * phnum > size - phoff):
            raise DDPolicyDenied("trusted dd ELF program-header table is malformed")
        for index in range(phnum):
            raw_type = self.ops.pread(fd, 4, phoff + index * phentsize)
            if len(raw_type) != 4:
                raise DDPolicyDenied("trusted dd ELF program-header table is truncated")
            if int.from_bytes(raw_type, "little") == 3:  # PT_INTERP
                return False
        return True

    def _verify_executable_source(self, fd: int) -> None:
        info = self.ops.fstat(fd)
        self._validate_executable_stat(info)
        self._verify_no_file_capabilities(fd)
        if self.ops.pread(fd, 4, 0) != b"\x7fELF" or self.ops.inheritable(fd):
            raise DDPolicyDenied("dd executable identity is not trusted ELF")
        if self._mapper_is_block:
            if info.st_uid != 0:
                raise DDPolicyDenied("block-mapper executable must be root-owned")
            assert self._expected_executable_sha256 is not None
            if info.st_size <= 0 or info.st_size > 128 * 1024 * 1024:
                raise DDPolicyDenied("trusted dd executable size is outside the verification bound")
            digest = hashlib.sha256()
            offset = 0
            while offset < info.st_size:
                chunk = self.ops.pread(fd, min(1024 * 1024, info.st_size - offset), offset)
                if not chunk or len(chunk) > info.st_size - offset:
                    raise DDPolicyDenied("trusted dd executable changed or truncated during hashing")
                digest.update(chunk)
                offset += len(chunk)
            after = self.ops.fstat(fd)
            before_identity = (info.st_dev, info.st_ino, info.st_size,
                               info.st_mtime_ns, info.st_ctime_ns)
            after_identity = (after.st_dev, after.st_ino, after.st_size,
                              after.st_mtime_ns, after.st_ctime_ns)
            if (before_identity != after_identity
                    or digest.hexdigest() != self._expected_executable_sha256):
                raise DDPolicyDenied("pinned dd executable does not match trusted SHA-256 identity")
            if not self._is_static_elf(fd, info.st_size):
                raise DDPolicyDenied(
                    "dynamic dd is not admitted; its interpreter and shared-library closure are not pinned"
                )

    def _verify_executable(self) -> None:
        assert self._executable_fd is not None
        if self._mapper_is_block:
            assert self._executable_source_fd is not None
            self._verify_executable_source(self._executable_source_fd)
            source_info = self.ops.fstat(self._executable_source_fd)
            if self._executable_source_identity != (source_info.st_dev, source_info.st_ino):
                raise DDPolicyDenied("pinned GNU dd source pathname identity changed")
            path_info = self.ops.path_stat(self._executable_path, follow_symlinks=False)
            if self._executable_source_identity != (path_info.st_dev, path_info.st_ino):
                raise DDPolicyDenied("GNU dd executable pathname was replaced")
        info = self.ops.fstat(self._executable_fd)
        self._validate_executable_stat(info)
        if self.ops.pread(self._executable_fd, 4, 0) != b"\x7fELF":
            raise DDPolicyDenied("dd executable identity is not trusted ELF")
        if self.ops.inheritable(self._executable_fd):
            raise DDPolicyDenied("dd executable descriptor is not close-on-exec")
        if self._mapper_is_block:
            assert self._expected_executable_sha256 is not None
            assert self._sealed_executable_identity is not None
            if info.st_uid != os.geteuid() or self._sealed_executable_identity != (
                info.st_dev, info.st_ino, info.st_size
            ):
                raise DDPolicyDenied("sealed executable identity changed")
            required_seals = (getattr(fcntl, "F_SEAL_WRITE", 0x0008)
                              | getattr(fcntl, "F_SEAL_GROW", 0x0004)
                              | getattr(fcntl, "F_SEAL_SHRINK", 0x0002)
                              | getattr(fcntl, "F_SEAL_SEAL", 0x0001)
                              | getattr(fcntl, "F_SEAL_EXEC", 0x0020))
            try:
                seals = fcntl.fcntl(self._executable_fd, getattr(fcntl, "F_GET_SEALS", 1034))
            except OSError as exc:
                raise DDPolicyDenied(f"cannot inspect executable memfd seals: {exc}") from exc
            if seals & required_seals != required_seals:
                raise DDPolicyDenied("executable memfd is not fully write-sealed")
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
            if self._mapper_is_block:
                if not stat.S_ISBLK(mapper_info.st_mode):
                    self._deny("retained mapper descriptor type changed")
            elif (not stat.S_ISREG(mapper_info.st_mode)
                    or (mapper_info.st_dev, mapper_info.st_ino) != self._synthetic_mapper_identity
                    or mapper_info.st_uid != os.geteuid() or mapper_info.st_nlink != 1):
                self._deny("synthetic mapper file identity or ownership changed")
            if self._mapper_is_block:
                assert self._mapper_lifecycle_lease is not None
                mapper_verified = self._mapper_verifier(
                    self._mapper_fd, self._mapper_name, self.ops,
                    self._mapper_lifecycle_lease,
                )
            else:
                mapper_verified = self._mapper_verifier(
                    self._mapper_fd, self._mapper_name, self.ops,
                )
            if mapper_verified is not True:
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
        if self._mapper_lifecycle_lease is not None:
            try:
                self._mapper_lifecycle_lease.close()
            except Exception as exc:
                errors.append(f"close mapper lifecycle lease: {exc}")
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
    "TrustedGNUCoreutilsDD", "MapperIdentity", "MapperLifecycleLease",
]
