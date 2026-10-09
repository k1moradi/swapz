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
import base64
import contextlib
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import threading
from typing import Callable, Sequence


PAGE_SIZE = 4096
PAGES = 9
_MAPPER = re.compile(r"swapz-v22-recall-[A-Za-z0-9_-]{1,48}\Z")
_READS = {"a": 0, "b": 4, "a2": 0, "b2": 5}
_ROLES = frozenset(("writer", *_READS))
_TRUSTED_DD_TOKEN = object()
_TRUSTED_DD_BOOTSTRAP_DIR = Path("/etc/swapz/trust/gnu-coreutils-dd")
_TRUSTED_DD_PUBLIC_KEY_PATH = Path("/usr/share/swapz/trust/swapz-gnu-dd-manifest-ed25519.pub")
_TRUSTED_DD_OWNER_UID = 0
_TRUSTED_DD_OPENSSL_PATH = Path("/usr/bin/openssl")
_TRUSTED_DD_REVOKED_MARKER = "REVOKED"
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
    """Digest and provenance parsed only through the fixed trust bootstrap.

    No caller verifier, key, manifest, digest, or path is accepted. Tests use
    disposable signing keys to exercise the real detached-signature adapter;
    their signatures do not establish GNU binary provenance.
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
    def from_trusted_bootstrap(cls) -> "TrustedGNUCoreutilsDD":
        """Load only the fixed root-owned bootstrap and verify Ed25519 offline.

        No verifier, manifest, digest, key, or path is accepted as an argument.
        The fixed bootstrap directory is provisioned by a trusted administrator;
        the ordinary worker IPC surface cannot change it. Missing or invalid
        configuration is a hard denial.
        """
        payload, signature = _read_trusted_gnu_bootstrap()
        public_key = _read_trusted_gnu_public_key()
        _verify_ed25519_manifest(payload, signature, public_key)
        if not isinstance(payload, bytes) or not payload or len(payload) > 16384:
            raise DDPolicyDenied("trusted GNU dd manifest is invalid")
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

    def assert_held(self) -> None:
        """Fail unless this exact lease descriptor remains exclusively locked."""
        if self._closed or self._lock_fd is None:
            raise DDPolicyDenied("mapper lifecycle lease is closed")
        try:
            info = self.ops.fstat(self._lock_fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_nlink != 1 or info.st_mode & 0o077
                    or self.ops.inheritable(self._lock_fd)):
                raise DDPolicyDenied("mapper lifecycle lock identity changed")
            self._verify_owner_lock_held()
        except DDPolicyDenied:
            raise
        except Exception as exc:
            raise DDPolicyDenied(f"cannot verify exclusive fixture owner lock: {exc}") from exc

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



def _trusted_stat_identity(info) -> tuple[int, int, int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _validate_trusted_file(info, label: str, *, executable: bool = False) -> None:
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != _TRUSTED_DD_OWNER_UID
            or info.st_nlink != 1 or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or info.st_mode & (stat.S_ISUID | stat.S_ISGID)
            or (executable and not info.st_mode & 0o111)):
        raise DDPolicyDenied(f"trusted bootstrap {label} has unsafe owner, type, or mode")


def _validate_root_owned_directory(info, label: str) -> None:
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != _TRUSTED_DD_OWNER_UID
            or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
        raise DDPolicyDenied(f"trusted bootstrap directory {label} is not root-controlled")


def _open_root_owned_directory(path: Path, ops: RecallDDFileOps) -> tuple[int, list[int]]:
    if not isinstance(path, Path) or not path.is_absolute() or str(path) != os.path.normpath(str(path)):
        raise DDPolicyDenied("trusted bootstrap directory must be a normalized absolute Path")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    opened: list[int] = []
    try:
        current = ops.open("/", flags)
        opened.append(current)
        _validate_root_owned_directory(ops.fstat(current), "/")
        for component in path.parts[1:]:
            current = ops.open(component, flags, dir_fd=current)
            opened.append(current)
            _validate_root_owned_directory(ops.fstat(current), component)
        return current, opened
    except Exception as exc:
        close_failure = None
        for fd in reversed(opened):
            try:
                ops.close(fd)
            except Exception as close_exc:
                close_failure = close_exc
        if close_failure is not None:
            raise DDPolicyDenied(
                f"trusted bootstrap path inspection failed ({exc}); directory close failed ({close_failure})"
            ) from exc
        if isinstance(exc, DDPolicyDenied):
            raise
        raise DDPolicyDenied(f"cannot inspect trusted bootstrap path: {exc}") from exc


def _close_directory_chain(opened: list[int], failure: Exception | None,
                           label: str, ops: RecallDDFileOps) -> Exception | None:
    for fd in reversed(opened):
        try:
            ops.close(fd)
        except Exception as exc:
            failure = DDPolicyDenied(
                f"{label} directory descriptor close failed"
                + (f" after {failure}; close error: {exc}" if failure else f": {exc}")
            )
    return failure


def _read_trusted_file(dir_fd: int, name: str, maximum: int,
                       ops: RecallDDFileOps) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        fd = ops.open(name, flags, dir_fd=dir_fd)
    except Exception as exc:
        raise DDPolicyDenied(f"cannot open trusted bootstrap {name}: {exc}") from exc
    failure: Exception | None = None
    result: bytes | None = None
    try:
        before = ops.fstat(fd)
        _validate_trusted_file(before, name)
        if ops.inheritable(fd) or before.st_size <= 0 or before.st_size > maximum:
            raise DDPolicyDenied(f"trusted bootstrap {name} has invalid descriptor or size")
        entry = ops.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        if (entry.st_dev, entry.st_ino) != (before.st_dev, before.st_ino):
            raise DDPolicyDenied(f"trusted bootstrap {name} path identity changed")
        chunks: list[bytes] = []
        offset = 0
        while offset < before.st_size:
            part = ops.pread(fd, min(4096, before.st_size - offset), offset)
            if not part or len(part) > before.st_size - offset:
                raise DDPolicyDenied(f"trusted bootstrap {name} was truncated while reading")
            chunks.append(part)
            offset += len(part)
        after = ops.fstat(fd)
        after_entry = ops.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        if (_trusted_stat_identity(before) != _trusted_stat_identity(after)
                or (after_entry.st_dev, after_entry.st_ino) != (before.st_dev, before.st_ino)):
            raise DDPolicyDenied(f"trusted bootstrap {name} changed while reading")
        result = b"".join(chunks)
    except Exception as exc:
        failure = exc
    try:
        ops.close(fd)
    except Exception as exc:
        failure = DDPolicyDenied(
            f"trusted bootstrap {name} descriptor close failed"
            + (f" after {failure}; close error: {exc}" if failure
               else f": {exc}")
        )
    if failure is not None:
        if isinstance(failure, DDPolicyDenied):
            raise failure
        raise DDPolicyDenied(f"cannot read trusted bootstrap {name}: {failure}") from failure
    assert result is not None
    return result


def _read_trusted_gnu_bootstrap() -> tuple[bytes, bytes]:
    ops = RecallDDFileOps()
    directory_fd, opened_directories = _open_root_owned_directory(
        _TRUSTED_DD_BOOTSTRAP_DIR, ops,
    )
    file_contents: dict[str, bytes] = {}
    failure: Exception | None = None
    try:
        names = set(os.listdir(directory_fd))
        if _TRUSTED_DD_REVOKED_MARKER in names:
            raise DDPolicyDenied("trusted GNU coreutils signing configuration is revoked")
        required = {"manifest.json", "manifest.sig"}
        if not required <= names or names - required - {_TRUSTED_DD_REVOKED_MARKER}:
            raise DDPolicyDenied("trusted GNU bootstrap has missing or unexpected entries")
        dir_info = ops.fstat(directory_fd)
        _validate_root_owned_directory(dir_info, str(_TRUSTED_DD_BOOTSTRAP_DIR))
        for name in sorted(required):
            file_contents[name] = _read_trusted_file(
                directory_fd, name,
                {"manifest.json": 16384, "manifest.sig": 64}[name],
                ops,
            )
        if len(file_contents["manifest.sig"]) != 64:
            raise DDPolicyDenied("trusted GNU manifest signature is not an Ed25519 signature")
    except Exception as exc:
        failure = exc
    failure = _close_directory_chain(
        opened_directories, failure, "trusted GNU bootstrap", ops,
    )
    if failure is not None:
        if isinstance(failure, DDPolicyDenied):
            raise failure
        raise DDPolicyDenied(f"cannot read trusted GNU bootstrap: {failure}") from failure
    return file_contents["manifest.json"], file_contents["manifest.sig"]


def _read_trusted_gnu_public_key() -> bytes:
    """Read a separately provisioned root-controlled Ed25519 trust anchor."""
    ops = RecallDDFileOps()
    parent_fd, opened_directories = _open_root_owned_directory(
        _TRUSTED_DD_PUBLIC_KEY_PATH.parent, ops,
    )
    result: bytes | None = None
    failure: Exception | None = None
    try:
        result = _read_trusted_file(parent_fd, _TRUSTED_DD_PUBLIC_KEY_PATH.name, 4096, ops)
        if not _is_ed25519_public_key_pem(result):
            raise DDPolicyDenied("trusted GNU public-key file is not an Ed25519 SubjectPublicKeyInfo")
    except Exception as exc:
        failure = exc
    failure = _close_directory_chain(
        opened_directories, failure, "trusted GNU public key", ops,
    )
    if failure is not None:
        if isinstance(failure, DDPolicyDenied):
            raise failure
        raise DDPolicyDenied(f"cannot read trusted GNU public key: {failure}") from failure
    assert result is not None
    return result


def _is_ed25519_public_key_pem(data: bytes) -> bool:
    """Accept only the canonical 32-byte Ed25519 SubjectPublicKeyInfo form."""
    prefix = b"-----BEGIN PUBLIC KEY-----\n"
    suffix = b"\n-----END PUBLIC KEY-----\n"
    if not data.startswith(prefix) or not data.endswith(suffix):
        return False
    encoded = data[len(prefix):-len(suffix)]
    if not encoded or any(line.startswith(b"-") for line in encoded.splitlines()):
        return False
    try:
        der = base64.b64decode(b"".join(encoded.split()), validate=True)
    except Exception:
        return False
    return len(der) == 44 and der[:12] == bytes.fromhex("302a300506032b6570032100")


def _sealed_data_memfd(name: str, data: bytes) -> int:
    if not callable(getattr(os, "memfd_create", None)):
        raise OSError(errno.ENOSYS, "memfd_create is unavailable for signature verification")
    fd = os.memfd_create(
        name, getattr(os, "MFD_CLOEXEC", 0x0001) | getattr(os, "MFD_ALLOW_SEALING", 0x0002),
    )
    try:
        offset = 0
        while offset < len(data):
            count = os.write(fd, data[offset:])
            if count <= 0:
                raise OSError(errno.EIO, "short write to signature verification memfd")
            offset += count
        seals = (getattr(fcntl, "F_SEAL_WRITE", 0x0008)
                 | getattr(fcntl, "F_SEAL_GROW", 0x0004)
                 | getattr(fcntl, "F_SEAL_SHRINK", 0x0002)
                 | getattr(fcntl, "F_SEAL_SEAL", 0x0001))
        fcntl.fcntl(fd, getattr(fcntl, "F_ADD_SEALS", 1033), seals)
        if fcntl.fcntl(fd, getattr(fcntl, "F_GET_SEALS", 1034)) & seals != seals:
            raise OSError(errno.EPERM, "signature verification data is not sealed")
        if os.get_inheritable(fd):
            raise OSError(errno.EBADF, "signature verification descriptor is inheritable")
        return fd
    except Exception as original:
        try:
            os.close(fd)
        except Exception as close_error:
            raise OSError(
                errno.EIO,
                f"signature input memfd setup failed ({original}); close failed ({close_error})",
            ) from original
        raise


def _verify_ed25519_manifest(payload: bytes, signature: bytes, public_key: bytes) -> None:
    if (not payload or len(payload) > 16384 or len(signature) != 64
            or not public_key or len(public_key) > 4096
            or not _is_ed25519_public_key_pem(public_key)):
        raise DDPolicyDenied("trusted GNU signature inputs are invalid")
    ops = RecallDDFileOps()
    executable_fd: int | None = None
    data_fds: list[int] = []
    failure: Exception | None = None
    try:
        if not _TRUSTED_DD_OPENSSL_PATH.is_absolute():
            raise DDPolicyDenied("trusted signature verifier path is not absolute")
        executable_fd = ops.open(
            str(_TRUSTED_DD_OPENSSL_PATH), os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
        )
        info = ops.fstat(executable_fd)
        _validate_trusted_file(info, "OpenSSL verifier", executable=True)
        if ops.inheritable(executable_fd) or ops.pread(executable_fd, 4, 0) != b"\x7fELF":
            raise DDPolicyDenied("trusted signature verifier is not a pinned ELF executable")
        path_info = ops.path_stat(_TRUSTED_DD_OPENSSL_PATH, follow_symlinks=False)
        if (path_info.st_dev, path_info.st_ino) != (info.st_dev, info.st_ino):
            raise DDPolicyDenied("trusted signature verifier path changed")
        try:
            caps = ops.getxattr(executable_fd, "security.capability")
        except OSError as exc:
            if exc.errno not in {getattr(errno, "ENODATA", 61), getattr(errno, "ENOATTR", 61)}:
                raise DDPolicyDenied(f"cannot inspect signature verifier capabilities: {exc}") from exc
        else:
            if caps:
                raise DDPolicyDenied("signature verifier has file capabilities")
        data_fds = [
            _sealed_data_memfd("swapz-dd-manifest", payload),
            _sealed_data_memfd("swapz-dd-signature", signature),
            _sealed_data_memfd("swapz-dd-public-key", public_key),
        ]
        manifest_fd, signature_fd, key_fd = data_fds
        executable = f"/proc/self/fd/{executable_fd}"
        result = subprocess.run(
            [executable, "pkeyutl", "-verify", "-pubin", "-inkey",
             f"/proc/self/fd/{key_fd}", "-rawin", "-in",
             f"/proc/self/fd/{manifest_fd}", "-sigfile", f"/proc/self/fd/{signature_fd}"],
            executable=executable,
            pass_fds=(executable_fd, manifest_fd, signature_fd, key_fd),
            close_fds=True,
            env={"LC_ALL": "C", "OPENSSL_CONF": "/dev/null"},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=5, check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or b"").decode("utf-8", errors="replace")[:512]
            raise DDPolicyDenied(f"trusted GNU manifest Ed25519 signature failed: {detail}")
        after_info = ops.fstat(executable_fd)
        after_path = ops.path_stat(_TRUSTED_DD_OPENSSL_PATH, follow_symlinks=False)
        if (_trusted_stat_identity(info) != _trusted_stat_identity(after_info)
                or (after_path.st_dev, after_path.st_ino) != (info.st_dev, info.st_ino)):
            raise DDPolicyDenied("trusted signature verifier changed during verification")
    except Exception as exc:
        failure = exc
    for fd in reversed(data_fds + ([executable_fd] if executable_fd is not None else [])):
        try:
            ops.close(fd)
        except Exception as exc:
            failure = DDPolicyDenied(
                "signature verification descriptor close failed"
                + (f" after {failure}; close error: {exc}" if failure
                   else f": {exc}")
            )
    if failure is not None:
        if isinstance(failure, DDPolicyDenied):
            raise failure
        if isinstance(failure, subprocess.TimeoutExpired):
            raise DDPolicyDenied("trusted GNU signature verification timed out") from failure
        raise DDPolicyDenied(f"trusted GNU signature verification failed: {failure}") from failure



@dataclass(frozen=True)
class MapperInventory:
    valid: bool
    entries: tuple[MapperIdentity, ...]


class MapperOwnerDenied(RuntimeError):
    """The fixture owner cannot prove one safe mapper lifecycle."""


class MapperLifecycleOwner:
    """Injected single-mapping lifecycle controller for a trusted fixture owner.

    This state controller does not create DM devices itself. Its operations
    object is a trusted privileged fixture implementation; the rootless tests
    provide a fake implementation. The controller requires a pre-held lease,
    binds one exact identity, revalidates before each role, and holds the lease
    until exact normal removal and independently observed absence.
    """

    NEW = "new"
    ACTIVE = "active"
    ADMISSION_CLOSED = "admission_closed"
    RELEASED = "released"
    DENIED = "denied"

    def __init__(self, identity: MapperIdentity, lease: MapperLifecycleLease,
                 operations, *, file_ops: RecallDDFileOps | None = None) -> None:
        if type(identity) is not MapperIdentity or type(lease) is not MapperLifecycleLease:
            raise MapperOwnerDenied("mapper owner needs one exact identity and lifecycle lease")
        if lease.expected != identity:
            raise MapperOwnerDenied("mapper owner and lifecycle lease identities differ")
        for method in ("owner_alive", "inventory", "create_mapping", "remove_mapping"):
            if not callable(getattr(operations, method, None)):
                raise MapperOwnerDenied(f"mapper owner operation {method} is unavailable")
        self.identity = identity
        self.lease = lease
        self.operations = operations
        self.file_ops = file_ops if file_ops is not None else RecallDDFileOps()
        self.state = self.NEW
        self._denial: str | None = None
        self._mapper_fd: int | None = None
        self._operation_lock = threading.Lock()

    @property
    def cleanup_allowed(self) -> bool:
        return self.state == self.RELEASED and self._denial is None

    @property
    def preserve_backing(self) -> bool:
        return not self.cleanup_allowed

    @property
    def denial(self) -> str | None:
        return self._denial

    @property
    def mapper_fd(self) -> int | None:
        return self._mapper_fd

    @contextlib.contextmanager
    def _operation(self, required_state: str):
        if not self._operation_lock.acquire(blocking=False):
            self._latch("concurrent mapper lifecycle operation")
            raise MapperOwnerDenied(self._denial)
        try:
            if self._denial is not None:
                raise MapperOwnerDenied(f"mapper owner is permanently denied: {self._denial}")
            if self.state != required_state:
                self._deny(f"mapper owner operation invalid in state {self.state}")
            yield
            if self._denial is not None:
                raise MapperOwnerDenied(f"mapper owner is permanently denied: {self._denial}")
        finally:
            self._operation_lock.release()

    def _latch(self, reason: str) -> None:
        if self._denial is None:
            self._denial = reason
        self.state = self.DENIED

    def _deny(self, reason: str) -> None:
        self._latch(reason)
        raise MapperOwnerDenied(reason)

    def _check_owner_and_lease(self) -> None:
        if self._denial is not None:
            self._deny(f"mapper owner is permanently denied: {self._denial}")
        try:
            alive = self.operations.owner_alive()
        except Exception as exc:
            self._deny(f"cannot inspect privileged fixture owner: {exc}")
        if alive is not True:
            self._deny("privileged fixture owner is absent or unconfirmed")
        try:
            self.lease.assert_held()
        except Exception as exc:
            self._deny(f"fixture lifecycle lease is not held: {exc}")

    def _inventory(self, *, present: bool) -> MapperInventory:
        self._check_owner_and_lease()
        try:
            inventory = self.operations.inventory()
        except Exception as exc:
            self._deny(f"cannot inspect complete DM inventory: {exc}")
        self._check_owner_and_lease()
        if (type(inventory) is not MapperInventory or inventory.valid is not True
                or type(inventory.entries) is not tuple
                or any(type(item) is not MapperIdentity for item in inventory.entries)):
            self._deny("DM inventory is invalid, ambiguous, or malformed")
        names = [item.name for item in inventory.entries]
        uuids = [item.uuid for item in inventory.entries]
        devices = [(item.major, item.minor) for item in inventory.entries]
        if (len(set(names)) != len(names) or len(set(uuids)) != len(uuids)
                or len(set(devices)) != len(devices)):
            self._deny("DM inventory contains duplicate mapper identities")
        matches = [item for item in inventory.entries if (
            item.name == self.identity.name or item.uuid == self.identity.uuid
            or (item.major, item.minor) == (self.identity.major, self.identity.minor)
        )]
        if present:
            if matches != [self.identity]:
                self._deny("DM inventory does not contain exactly the bound mapper identity")
        elif matches:
            self._deny("stale or conflicting DM identity exists before mapper creation")
        return inventory

    def _verify_descriptor(self, fd: int) -> None:
        if self._mapper_fd is None:
            self._deny("owner has no retained mapper descriptor")
        try:
            owned = self.file_ops.fstat(self._mapper_fd)
            observed = self.file_ops.fstat(fd)
            if (not stat.S_ISBLK(owned.st_mode) or not stat.S_ISBLK(observed.st_mode)
                    or (os.major(owned.st_rdev), os.minor(owned.st_rdev))
                    != (self.identity.major, self.identity.minor)
                    or (os.major(observed.st_rdev), os.minor(observed.st_rdev))
                    != (self.identity.major, self.identity.minor)
                    or (owned.st_dev, owned.st_ino, owned.st_rdev)
                    != (observed.st_dev, observed.st_ino, observed.st_rdev)
                    or self.file_ops.inheritable(fd)):
                self._deny("mapper descriptor is not the retained exact DM object")
            verified = _verify_dm_descriptor(
                fd, self.identity.name, self.file_ops, self.lease,
            )
            if verified is not True:
                self._deny("mapper descriptor identity was not positively verified")
        except MapperOwnerDenied:
            raise
        except Exception as exc:
            self._deny(f"mapper descriptor inspection failed: {exc}")

    def create(self) -> int:
        with self._operation(self.NEW):
            self._check_owner_and_lease()
            self._inventory(present=False)
            self._check_owner_and_lease()
            try:
                fd = self.operations.create_mapping(self.identity)
            except Exception as exc:
                self._deny(f"exact test mapping creation failed: {exc}")
            if isinstance(fd, bool) or not isinstance(fd, int) or fd < 0:
                self._deny("mapping creation returned an invalid descriptor")
            self._mapper_fd = fd
            self._check_owner_and_lease()
            self._verify_descriptor(fd)
            self._inventory(present=True)
            self._check_owner_and_lease()
            self.state = self.ACTIVE
            return fd

    def verify_role(self, mapper_fd: int) -> bool:
        with self._operation(self.ACTIVE):
            self._check_owner_and_lease()
            self._verify_descriptor(mapper_fd)
            self._inventory(present=True)
            self._check_owner_and_lease()
            return True

    def close_admission(self) -> None:
        with self._operation(self.ACTIVE):
            self._check_owner_and_lease()
            assert self._mapper_fd is not None
            self._verify_descriptor(self._mapper_fd)
            self._inventory(present=True)
            self._check_owner_and_lease()
            self.state = self.ADMISSION_CLOSED

    def finalize_teardown(self, *, workers_reaped: bool,
                           descriptors_closed: bool) -> None:
        with self._operation(self.ADMISSION_CLOSED):
            if workers_reaped is not True or descriptors_closed is not True:
                self._deny("workers or role descriptors are not positively quiesced")
            self._check_owner_and_lease()
            self._inventory(present=True)
            self._check_owner_and_lease()
            if self._mapper_fd is None:
                self._deny("retained mapper descriptor disappeared before teardown")
            fd, self._mapper_fd = self._mapper_fd, None
            try:
                self.file_ops.close(fd)
            except Exception as exc:
                self._deny(f"retained mapper descriptor close failed: {exc}")
            self._check_owner_and_lease()
            try:
                removed = self.operations.remove_mapping(self.identity)
            except Exception as exc:
                self._deny(f"normal exact mapper removal failed: {exc}")
            if removed is not True:
                self._deny("normal exact mapper removal was not confirmed")
            self._check_owner_and_lease()
            self._inventory(present=False)
            self._check_owner_and_lease()
            try:
                self.lease.close()
            except Exception as exc:
                self._deny(f"lease release failed after verified mapper absence: {exc}")
            self.state = self.RELEASED


def _verify_dm_descriptor(fd: int, mapper_name: str, ops: RecallDDFileOps,
                          lifecycle_lease: MapperLifecycleLease | None = None) -> bool:
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
        mapper_owner: MapperLifecycleOwner | None = None,
        ops: RecallDDFileOps | None = None,
        mapper_verifier=None,
    ) -> None:
        self.ops = ops if ops is not None else RecallDDFileOps()
        if trusted_executable is not None and type(trusted_executable) is not TrustedGNUCoreutilsDD:
            raise DDPolicyDenied("direct dd identity must come from a verified GNU manifest")
        if mapper_lifecycle_lease is not None and type(mapper_lifecycle_lease) is not MapperLifecycleLease:
            raise DDPolicyDenied("mapper lifecycle proof must come from the trusted fixture owner")
        if mapper_owner is not None and type(mapper_owner) is not MapperLifecycleOwner:
            raise DDPolicyDenied("mapper lifecycle owner must use the checked fixture controller")
        if mapper_owner is not None:
            if mapper_lifecycle_lease is not None and mapper_lifecycle_lease is not mapper_owner.lease:
                raise DDPolicyDenied("mapper gate and lifecycle owner have different leases")
            mapper_lifecycle_lease = mapper_owner.lease
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
        if self._mapper_is_block and mapper_owner is None:
            raise DDPolicyDenied(
                "block-mapper launch requires an active exclusive fixture owner session"
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
        if self._mapper_is_block and (
            mapper_owner.identity != mapper_lifecycle_lease.expected
            or mapper_owner.state != MapperLifecycleOwner.ACTIVE
        ):
            raise DDPolicyDenied("mapper owner is not active for the exact trusted identity")
        self._mapper_owner = mapper_owner
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
                assert self._mapper_owner is not None
                mapper_verified = self._mapper_owner.verify_role(self._mapper_fd)
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
            if self._trusted_executable is not None:
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
        supported_machines = {"x86_64": 62, "amd64": 62, "aarch64": 183, "arm64": 183}
        expected_machine = supported_machines.get(platform.machine().lower())
        machine = int.from_bytes(header[18:20], "little")
        if expected_machine is None or machine != expected_machine:
            raise DDPolicyDenied("trusted GNU dd ELF architecture is unsupported on this supervisor")
        if phnum == 0:
            return True
        if (phentsize < minimum_phdr or phnum > 1024
                or phoff > size or phentsize * phnum > size - phoff):
            raise DDPolicyDenied("trusted dd ELF program-header table is malformed")
        for index in range(phnum):
            raw_type = self.ops.pread(fd, 4, phoff + index * phentsize)
            if len(raw_type) != 4:
                raise DDPolicyDenied("trusted dd ELF program-header table is truncated")
            if int.from_bytes(raw_type, "little") in {2, 3}:  # PT_DYNAMIC, PT_INTERP
                return False
        return True

    def _verify_executable_source(self, fd: int) -> None:
        info = self.ops.fstat(fd)
        self._validate_executable_stat(info)
        self._verify_no_file_capabilities(fd)
        if self.ops.pread(fd, 4, 0) != b"\x7fELF" or self.ops.inheritable(fd):
            raise DDPolicyDenied("dd executable identity is not trusted ELF")
        if self._trusted_executable is not None:
            if self._mapper_is_block and info.st_uid != 0:
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
        if self._trusted_executable is not None:
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
        if self._trusted_executable is not None:
            assert self._expected_executable_sha256 is not None
            assert self._sealed_executable_identity is not None
            if ((self._mapper_is_block and info.st_uid != os.geteuid())
                    or self._sealed_executable_identity != (
                info.st_dev, info.st_ino, info.st_size
            )):
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
        if (self._mapper_owner is not None
                and self._mapper_owner.state == MapperLifecycleOwner.ACTIVE):
            try:
                self._mapper_owner.close_admission()
            except Exception as exc:
                raise DDPolicyDenied(f"fixture owner could not close mapper admission: {exc}") from exc

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
                assert self._mapper_owner is not None
                mapper_verified = self._mapper_owner.verify_role(self._mapper_fd)
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
        if (self._mapper_owner is not None
                and self._mapper_owner.state == MapperLifecycleOwner.ACTIVE):
            try:
                self._mapper_owner.close_admission()
            except Exception as exc:
                errors.append(f"close mapper role admission: {exc}")
        for fd in reversed(self._owned_fds):
            try:
                self.ops.close(fd)
            except Exception as exc:
                errors.append(f"close direct dd descriptor {fd}: {exc}")
        self._owned_fds.clear()
        if self._mapper_lifecycle_lease is not None and self._mapper_owner is None:
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
    "MapperInventory", "MapperLifecycleOwner", "MapperOwnerDenied",
]
