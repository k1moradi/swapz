#!/usr/bin/env python3
"""Run authenticated static GNU dd through the real recall gate and pidfd worker.

The mapper is always an owned ordinary regular file. A disposable application
key is generated in a TemporaryDirectory only to exercise the existing signed
bootstrap mechanics; it is never installed or reused as a production key.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import platform
import re
import signal
import stat
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock


HERE = Path(__file__).resolve().parent


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


policy = load_module("recall_gnu_dd_qualification_policy", "recall-dd-allowlist.py")
supervisor_module = load_module("recall_gnu_dd_qualification_supervisor", "test-child-supervisor.py")
provenance = load_module("recall_gnu_dd_qualification_provenance", "gnu-coreutils-qualification.py")


class _RootOwnedBootstrapOps(policy.RecallDDFileOps):
    """Test-only root metadata shim for the ephemeral signed bootstrap."""

    def __init__(self):
        self.directory_fds: set[int] = set()
        self.trust_fds: set[int] = set()

    def open(self, path, flags, mode=0o777, *, dir_fd=None):
        fd = super().open(path, flags, mode, dir_fd=dir_fd)
        if flags & os.O_DIRECTORY:
            self.directory_fds.add(fd)
        elif dir_fd in self.directory_fds:
            self.trust_fds.add(fd)
        return fd

    def fstat(self, fd):
        info = super().fstat(fd)
        if fd in self.directory_fds:
            return SimpleNamespace(
                # The bootstrap code intentionally requires each path element
                # to be root-controlled. This test-only shim models that
                # provisioning property for a private directory under /tmp.
                st_mode=stat.S_IFDIR | 0o700, st_uid=0, st_nlink=info.st_nlink,
                st_dev=info.st_dev, st_ino=info.st_ino, st_size=info.st_size,
                st_mtime_ns=info.st_mtime_ns, st_ctime_ns=info.st_ctime_ns,
            )
        if fd in self.trust_fds:
            return SimpleNamespace(
                st_mode=info.st_mode, st_uid=0, st_nlink=info.st_nlink,
                st_dev=info.st_dev, st_ino=info.st_ino, st_size=info.st_size,
                st_mtime_ns=info.st_mtime_ns, st_ctime_ns=info.st_ctime_ns,
            )
        return info

    def close(self, fd):
        self.directory_fds.discard(fd)
        self.trust_fds.discard(fd)
        return super().close(fd)


class AuthenticatedGNUWorkerQualification(unittest.TestCase):
    source_archive: Path
    source_signature: Path
    gnu_keyring: Path
    dd_binary: Path
    expected_source_sha256: str
    expected_binary_sha256: str
    expected_output_identity: dict[str, int]
    build_record_path: Path
    output_record: Path | None = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.source_record = provenance.verify_source_archive(
            cls.source_archive, cls.source_signature, cls.gnu_keyring, "9.11",
        )
        if cls.source_record["archive_sha256"] != cls.expected_source_sha256:
            raise RuntimeError("verified source hash differs from the requested qualification input")
        cls.binary_record = provenance._inspect_binary(
            cls.dd_binary, expected_sha256=cls.expected_binary_sha256,
            expected_identity=cls.expected_output_identity,
        )
        if cls.binary_record["sha256"] != cls.expected_binary_sha256:
            raise RuntimeError("pinned GNU dd binary hash differs from the requested qualification input")
        cls.temp = tempfile.TemporaryDirectory(prefix="swapz-gnu-dd-seccomp-")
        cls.temp_root = Path(cls.temp.name)
        cls.test_key = cls.temp_root / "test-only-private.pem"
        cls.test_public_key = cls.temp_root / "test-only-public.pem"
        subprocess.run(
            ["/usr/bin/openssl", "genpkey", "-algorithm", "ED25519", "-out", str(cls.test_key)],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
        )
        subprocess.run(
            ["/usr/bin/openssl", "pkey", "-in", str(cls.test_key), "-pubout",
             "-out", str(cls.test_public_key)],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
        )
        cls.bootstrap_root = cls.temp_root / "bootstrap"
        cls.bootstrap_root.mkdir(mode=0o700)
        cls.key_root = cls.temp_root / "key"
        cls.key_root.mkdir(mode=0o700)
        cls.public_key_path = cls.key_root / "swapz-gnu-dd-manifest-ed25519.pub"
        cls.public_key_path.write_bytes(cls.test_public_key.read_bytes())
        cls.public_key_path.chmod(0o600)

        manifest = {
            "format": 1, "vendor": "GNU Project", "package": "coreutils", "binary": "dd",
            "version": "9.11", "executable": str(cls.dd_binary.resolve()),
            "sha256": cls.binary_record["sha256"],
            "source_sha256": cls.source_record["archive_sha256"], "linkage": "static",
        }
        cls.manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        manifest_path = cls.bootstrap_root / "manifest.json"
        signature_path = cls.bootstrap_root / "manifest.sig"
        manifest_path.write_bytes(cls.manifest_bytes)
        manifest_path.chmod(0o600)
        subprocess.run(
            ["/usr/bin/openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(cls.test_key),
             "-in", str(manifest_path), "-out", str(signature_path)],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
        )
        signature_path.chmod(0o600)
        with mock.patch.object(policy, "_TRUSTED_DD_BOOTSTRAP_DIR", cls.bootstrap_root), \
                mock.patch.object(policy, "_TRUSTED_DD_PUBLIC_KEY_PATH", cls.public_key_path), \
                mock.patch.object(policy, "RecallDDFileOps", _RootOwnedBootstrapOps):
            cls.trusted_executable = policy.TrustedGNUCoreutilsDD.from_trusted_bootstrap()

        cls.mapper_name = "swapz-v22-recall-gnu-qual"
        cls.page_data = bytes(range(256)) * (9 * 4096 // 256)

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "temp"):
            cls.temp.cleanup()

    def setUp(self) -> None:
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            self.skipTest("Linux pidfd APIs are required for real worker-boundary qualification")
        self.temporary = tempfile.TemporaryDirectory(prefix="swapz-gnu-dd-roles-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.fixture = self.base / "fixture"
        self.fixture.mkdir(mode=0o700)
        self.source = self.fixture / "pages.bin"
        self.source.write_bytes(self.page_data)
        self.source.chmod(0o600)
        self.mapper_path = self.base / "synthetic-mapper-regular-file"
        self.mapper_path.write_bytes(bytes(len(self.page_data)))
        self.mapper_path.chmod(0o600)
        self.mapper_fd = os.open(self.mapper_path, os.O_RDWR | os.O_CLOEXEC)

        def verify_synthetic_mapper(fd, name, ops):
            info = ops.fstat(fd)
            return (name == self.mapper_name and stat.S_ISREG(info.st_mode)
                    and info.st_size == len(self.page_data))

        self.gate = policy.RecallDDLaunchGate(
            self.fixture, self.mapper_name, mapper_fd=self.mapper_fd,
            executable_path=self.dd_binary.resolve(), trusted_executable=self.trusted_executable,
            mapper_verifier=verify_synthetic_mapper,
        )
        self.addCleanup(self._close_gate)
        self.supervisor = supervisor_module.GatedPidfdSupervisor(
            startup_timeout=3.0, term_grace=1.0, kill_grace=1.0, escalate=True,
        )
        self.handles: list[str] = []
        self.addCleanup(self._stop_all)

    def _launch_approved(self, approved) -> str:
        self.assertFalse(os.get_inheritable(approved.executable_fd))
        for fd in approved.pass_fds:
            self.assertFalse(os.get_inheritable(fd))
        handle = self.supervisor.launch(
            approved.argv, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "TZ": "UTC"},
            executable=approved.executable, executable_fd=approved.executable_fd,
            pass_fds=approved.pass_fds, strict_fds=True,
        )
        self.handles.append(handle)
        worker = self.supervisor.worker_for_test(handle)
        self.assertTrue(worker.containment_required)
        self.assertTrue(worker.containment_installed)
        self.assertIsNotNone(worker.pidfd)
        return handle

    def _wait_success(self, handle: str) -> None:
        result = self.supervisor.wait(handle, 10.0)
        self.assertTrue(result.reaped, result.errors)
        self.assertEqual(result.exit_code, 0, result.errors)
        self.assertFalse(result.errors)

    def _stop_all(self) -> None:
        report = self.supervisor.stop_all(tuple(self.handles))
        self.assertTrue(report.all_reaped, report.errors)
        self.assertFalse(report.errors)

    def _close_gate(self) -> None:
        errors = self.gate.close()
        self.assertEqual(errors, ())
        os.close(self.mapper_fd)

    def test_real_static_gnu_dd_five_roles_under_pidfd_seccomp(self) -> None:
        writer = self._launch_approved(self.gate.admit("writer"))
        self._wait_success(writer)
        self.assertEqual(self.mapper_path.read_bytes(), self.page_data)

        for role in ("a", "b"):
            self._wait_success(self._launch_approved(self.gate.admit(role)))
        concurrent = [self._launch_approved(self.gate.admit(role)) for role in ("a2", "b2")]
        for handle in concurrent:
            self._wait_success(handle)

        for role, page in (("a", 0), ("b", 4), ("a2", 0), ("b2", 5)):
            output = (self.fixture / f"read-{role}").read_bytes()
            self.assertEqual(len(output), 4096)
            self.assertEqual(output, self.page_data[page * 4096:(page + 1) * 4096])
        self.assertEqual(self.gate.roles_issued, ("writer", "a", "b", "a2", "b2"))

    def test_gnu_worker_descriptor_isolation_and_pidfd_cancellation(self) -> None:
        worker_fd = self.gate._executable_fd
        self.assertIsNotNone(worker_fd)
        # A large sparse ordinary file keeps the actual static dd busy long
        # enough to inspect the child descriptor set and cancel through pidfd.
        large_source = self.fixture / "long-source.bin"
        large_output = self.fixture / "long-output.bin"
        large_in = os.open(large_source, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        large_out = os.open(large_output, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
        try:
            total = 512 * 1024 * 1024
            os.ftruncate(large_in, total)
            launch_handle = self.supervisor.launch(
                ("dd", f"if=/proc/self/fd/{large_in}", f"of=/proc/self/fd/{large_out}",
                 "bs=1048576", "count=512", "status=none"),
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "TZ": "UTC"},
                executable=f"/proc/self/fd/{worker_fd}", executable_fd=worker_fd,
                pass_fds=(large_in, large_out), strict_fds=True,
            )
            self.handles.append(launch_handle)
            worker = self.supervisor.worker_for_test(launch_handle)
            self.assertTrue(worker.containment_installed)
            self.assertFalse(self.supervisor.ops.pidfd_exited(worker.pidfd))
            proc_fd_dir = Path(f"/proc/{worker.pid}/fd")
            observed = {}
            for entry in proc_fd_dir.iterdir():
                if entry.name.isdecimal() and int(entry.name) >= 3:
                    observed[int(entry.name)] = os.readlink(entry)
            allowed = {str(large_source), str(large_output)}
            self.assertTrue(observed, "worker had no inherited file descriptors to audit")
            self.assertTrue(set(observed.values()).issubset(allowed), observed)

            report = self.supervisor.stop_all(tuple(self.handles))
            self.assertTrue(report.cleanup_allowed, (report.errors, report.results))
            result = next(item for item in report.results if item.handle == launch_handle)
            self.assertTrue(result.reaped, result.errors)
            self.assertNotEqual(result.exit_code, 0, "large dd completed naturally; cancellation was not proven")
            self.assertLess(large_output.stat().st_size, total,
                            "output reached full size, so cancellation was not demonstrated")
        finally:
            os.close(large_in)
            os.close(large_out)


_BUILD_RECORD_KEYS = {
    "schema", "qualification", "source", "build_recipe", "toolchain", "binary",
    "outputs", "rebuild_comparison", "build_logs", "worker_seccomp_execution",
    "production_manifest_or_key_installed",
}
_SOURCE_RECORD_KEYS = {
    "schema", "release", "archive_name", "archive_sha256", "signature_sha256",
    "gnu_keyring_sha256", "gpg_verifier", "published_sha256_base64",
    "release_signer_fingerprint", "release_signature_epoch", "release_commit",
    "source_authentication", "archive_layout", "release_announcement", "archive_url",
    "signature_url", "trust_note",
}
_BINARY_RECORD_KEYS = {
    "sha256", "size", "mode", "owner_uid", "link_count", "device", "inode",
    "mtime_ns", "ctime_ns", "elf", "candidate_executed_during_inspection",
    "setid_bits", "file_capabilities", "pinned_descriptor_path_rechecked",
}
_BINARY_IDENTITY_KEYS = {
    "device", "inode", "size", "mode_bits", "owner_uid", "link_count",
    "mtime_ns", "ctime_ns",
}
_OUTPUT_PATHS = (
    "copy-1/source/coreutils-9.11/src/dd",
    "copy-2/source/coreutils-9.11/src/dd",
)


def _object(value, fields: set[str], context: str) -> dict:
    if type(value) is not dict or set(value) != fields:
        raise RuntimeError(f"{context} has missing, extra, or invalidly typed fields")
    return value


def _is_sha256(value) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _open_directory_chain(path: Path) -> int:
    if (not path.is_absolute() or str(path) != os.path.normpath(str(path))):
        raise RuntimeError("build record parent directory path is not canonical")
    text = os.path.abspath(path)
    if text != os.path.normpath(text) or not text.startswith("/"):
        raise RuntimeError("build record parent directory path is not canonical")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open("/", flags)
    try:
        for component in Path(text).parts[1:]:
            next_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except Exception:
        os.close(fd)
        raise


def _open_relative_regular(root_fd: int, relative: str) -> int:
    parts = PurePosixPath(relative).parts
    if (not parts or PurePosixPath(relative).is_absolute()
            or any(part in {"", ".", ".."} for part in parts)
            or PurePosixPath(relative).as_posix() != relative):
        raise RuntimeError("build output path is not a canonical relative path")
    current_fd = os.dup(root_fd)
    directory_flags = (os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
                       | getattr(os, "O_NOFOLLOW", 0))
    try:
        for component in parts[:-1]:
            next_fd = os.open(component, directory_flags, dir_fd=current_fd)
            info = os.fstat(next_fd)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
                os.close(next_fd)
                raise RuntimeError("build output parent is not an owner-controlled directory")
            os.close(current_fd)
            current_fd = next_fd
        return os.open(parts[-1], os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
                       dir_fd=current_fd)
    finally:
        os.close(current_fd)


def _read_pinned_json(root_fd: int, filename: str) -> bytes:
    fd = os.open(filename, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
                 dir_fd=root_fd)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_size <= 0
                or before.st_size > 1024 * 1024 or before.st_uid != os.geteuid()
                or before.st_nlink != 1 or before.st_mode & 0o077):
            raise RuntimeError("build record is not a private owned regular file")
        data = bytearray()
        while len(data) < before.st_size:
            chunk = os.pread(fd, min(65536, before.st_size - len(data)), len(data))
            if not chunk:
                raise RuntimeError("build record changed or truncated while being read")
            data.extend(chunk)
        after = os.fstat(fd)
        if _stable_stat(before) != _stable_stat(after):
            raise RuntimeError("build record metadata changed while being read")
        return bytes(data)
    finally:
        os.close(fd)


def _stable_stat(info) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, stat.S_IMODE(info.st_mode),
            info.st_uid, info.st_nlink, info.st_mtime_ns, info.st_ctime_ns)


def _hash_attested_output(root_fd: int, output: dict, context: str) -> dict[str, int]:
    binary = _object(output.get("binary"), _BINARY_RECORD_KEYS, f"{context} binary")
    elf = _object(binary["elf"], {
        "elf_class", "endianness", "machine", "elf_type", "static",
    }, f"{context} ELF")
    metadata = {
        "device": binary["device"], "inode": binary["inode"], "size": binary["size"],
        "mode": binary["mode"], "owner_uid": binary["owner_uid"],
        "link_count": binary["link_count"], "mtime_ns": binary["mtime_ns"],
        "ctime_ns": binary["ctime_ns"],
    }
    if (not _is_sha256(binary["sha256"]) or type(binary["size"]) is not int
            or binary["size"] <= 0 or type(binary["owner_uid"]) is not int
            or binary["owner_uid"] != os.geteuid()
            or type(binary["link_count"]) is not int or binary["link_count"] != 1
            or type(binary["mode"]) is not str or binary["mode"] != "0755"
            or any(type(binary[key]) is not int or binary[key] < 0 for key in
                   ("device", "inode", "mtime_ns", "ctime_ns"))
            or type(binary["candidate_executed_during_inspection"]) is not bool
            or binary["candidate_executed_during_inspection"] is not False
            or type(binary["setid_bits"]) is not bool or binary["setid_bits"] is not False
            or type(binary["file_capabilities"]) is not bool or binary["file_capabilities"] is not False
            or type(binary["pinned_descriptor_path_rechecked"]) is not bool
            or binary["pinned_descriptor_path_rechecked"] is not True
            or elf != {
                "elf_class": "ELF64", "endianness": "little",
                "machine": platform.machine(), "elf_type": "ET_EXEC", "static": True,
            }):
        raise RuntimeError(f"{context} output metadata is malformed or unsafe")
    fd = _open_relative_regular(root_fd, output["path"])
    try:
        before = os.fstat(fd)
        actual = {
            "device": before.st_dev, "inode": before.st_ino, "size": before.st_size,
            "mode": format(stat.S_IMODE(before.st_mode), "04o"),
            "owner_uid": before.st_uid, "link_count": before.st_nlink,
            "mtime_ns": before.st_mtime_ns, "ctime_ns": before.st_ctime_ns,
        }
        if actual != metadata or not stat.S_ISREG(before.st_mode):
            raise RuntimeError(f"{context} output metadata differs from its pinned build record")
        digest = hashlib.sha256()
        offset = 0
        while offset < before.st_size:
            chunk = os.pread(fd, min(1024 * 1024, before.st_size - offset), offset)
            if not chunk:
                raise RuntimeError(f"{context} output was truncated while being hashed")
            digest.update(chunk)
            offset += len(chunk)
        after = os.fstat(fd)
        if _stable_stat(before) != _stable_stat(after):
            raise RuntimeError(f"{context} output metadata changed while being hashed")
        if digest.hexdigest() != binary["sha256"]:
            raise RuntimeError(f"{context} output bytes do not match the recorded SHA-256")
        path_fd = _open_relative_regular(root_fd, output["path"])
        try:
            if _stable_stat(os.fstat(path_fd)) != _stable_stat(before):
                raise RuntimeError(f"{context} path was substituted while being hashed")
        finally:
            os.close(path_fd)
        return {
            "device": before.st_dev, "inode": before.st_ino, "size": before.st_size,
            "mode_bits": stat.S_IMODE(before.st_mode), "owner_uid": before.st_uid,
            "link_count": before.st_nlink, "mtime_ns": before.st_mtime_ns,
            "ctime_ns": before.st_ctime_ns,
        }
    finally:
        os.close(fd)


def _validate_build_record_shape(record: dict, source_sha256: str) -> None:
    _object(record, _BUILD_RECORD_KEYS, "build record")
    if (record["schema"] != "swapz.gnu-coreutils-dd-build.v1"
            or record["qualification"] != "source authenticated; two same-host clean builds compared"
            or record["worker_seccomp_execution"] != "NOT RUN by build command"
            or type(record["production_manifest_or_key_installed"]) is not bool
            or record["production_manifest_or_key_installed"] is not False):
        raise RuntimeError("build record qualification claims are contradictory")
    source = _object(record["source"], _SOURCE_RECORD_KEYS, "source record")
    release = provenance.RELEASES["9.11"]
    _object(source["archive_layout"], {"top_level_directory", "configure_identity"}, "source layout")
    _object(source["gpg_verifier"], {
        "requested_path", "resolved_path", "sha256", "size", "mode", "owner_uid", "version",
    }, "GPG verifier identity")
    if (source["schema"] != "swapz.gnu-coreutils-source.v1" or source["release"] != "9.11"
            or source["archive_name"] != release["archive_name"]
            or source["archive_sha256"] != source_sha256
            or source["archive_sha256"] != base64.b64decode(
                release["archive_sha256_b64"], validate=True).hex()
            or source["release_signer_fingerprint"] != release["signer_fingerprint"]
            or source["release_signature_epoch"] != release["signature_epoch"]
            or source["release_commit"] != release["release_commit"]
            or source["source_authentication"] != "GNU detached signature verified; full key fingerprint pinned"
            or source["published_sha256_base64"] != release["archive_sha256_b64"]
            or source["release_announcement"] != release["announcement"]
            or source["archive_url"] != release["archive_url"]
            or source["signature_url"] != release["signature_url"]
            or source["trust_note"] != (
                "This authenticates the GNU release source archive, not any locally built binary or production application key."
            )
            or source["archive_layout"] != {
                "top_level_directory": "coreutils-9.11",
                "configure_identity": "GNU coreutils 9.11",
            }
            or not all(_is_sha256(source[key]) for key in (
                "archive_sha256", "signature_sha256", "gnu_keyring_sha256",
            ))
            or not _is_sha256(source["gpg_verifier"]["sha256"])
            or type(source["gpg_verifier"]["size"]) is not int
            or source["gpg_verifier"]["size"] <= 0
            or type(source["gpg_verifier"]["owner_uid"]) is not int
            or type(source["gpg_verifier"]["requested_path"]) is not str
            or source["gpg_verifier"]["requested_path"] != "/usr/bin/gpg"
            or type(source["gpg_verifier"]["resolved_path"]) is not str
            or not source["gpg_verifier"]["resolved_path"].startswith("/")
            or type(source["gpg_verifier"]["mode"]) is not str
            or type(source["gpg_verifier"]["version"]) is not str
            or not source["gpg_verifier"]["version"]
            or type(source["release_signature_epoch"]) is not int
            or type(source["release_signer_fingerprint"]) is not str
            or type(source["release_commit"]) is not str):
        raise RuntimeError("build record source identity is missing or contradictory")
    toolchain = record["toolchain"]
    toolchain_keys = {
        "python", "architecture", "host_platform", "kernel_release", "gcc", "make",
        "linker", "assembler", "archiver", "ranlib", "tar", "compiler_target",
        "static_libc_archive",
    }
    _object(toolchain, toolchain_keys, "toolchain")
    for key in ("python", "architecture", "host_platform", "kernel_release",
                "compiler_target", "static_libc_archive"):
        if type(toolchain[key]) is not str or not toolchain[key]:
            raise RuntimeError(f"build record toolchain {key} has the wrong type")
    for key in ("gcc", "make", "linker", "assembler", "archiver", "ranlib", "tar"):
        tool = _object(toolchain[key], {
            "requested_path", "resolved_path", "sha256", "size", "mode", "owner_uid", "version",
        }, f"toolchain {key}")
        if (type(tool["requested_path"]) is not str or not tool["requested_path"].startswith("/")
                or type(tool["resolved_path"]) is not str or not tool["resolved_path"].startswith("/")
                or not _is_sha256(tool["sha256"]) or type(tool["size"]) is not int or tool["size"] <= 0
                or type(tool["mode"]) is not str or tool["mode"] != "0755"
                or type(tool["owner_uid"]) is not int or tool["owner_uid"] < 0
                or type(tool["version"]) is not str or not tool["version"]):
            raise RuntimeError(f"build record toolchain {key} is malformed")
    recipe = _object(record["build_recipe"], {
        "configure", "make", "environment", "install_or_system_changes",
    }, "build recipe")
    environment = _object(recipe["environment"], {
        "CC", "CFLAGS", "LDFLAGS", "LC_ALL", "LANG", "TZ", "SOURCE_DATE_EPOCH",
    }, "build environment")
    if (recipe["configure"] != ["./configure", "--disable-nls", "--disable-acl", "--without-selinux"]
            or recipe["make"] != ["/usr/bin/make", "-j2"]
            or recipe["install_or_system_changes"] is not False
            or environment != {
                "CC": "/usr/bin/gcc", "CFLAGS": "-O2 -g0 -ffile-prefix-map=<source-tree>=.",
                "LDFLAGS": "-static", "LC_ALL": "C", "LANG": "C", "TZ": "UTC",
                "SOURCE_DATE_EPOCH": str(release["source_date_epoch"]),
            }):
        raise RuntimeError("build recipe differs from the reviewed static GNU recipe")
    logs = record["build_logs"]
    if type(logs) is not list or len(logs) != 2:
        raise RuntimeError("build record does not contain exactly two build-log records")
    for index, item in enumerate(logs, 1):
        item = _object(item, {"configure_log_sha256", "build_log_sha256"}, f"build log {index}")
        if not all(_is_sha256(item[key]) for key in item):
            raise RuntimeError(f"build log {index} digest is malformed")
    if toolchain["architecture"] != platform.machine():
        raise RuntimeError("build record architecture differs from this qualification host")


def _read_build_attestation(record_path: Path, binary_path: Path,
                           source_sha256: str) -> tuple[dict, bytes, str, dict[str, int]]:
    if (not record_path.is_absolute() or str(record_path) != os.path.normpath(str(record_path))
            or record_path.name != "qualification-record.json"
            or not binary_path.is_absolute() or str(binary_path) != os.path.normpath(str(binary_path))
            or not _is_sha256(source_sha256)):
        raise RuntimeError("build-record and candidate paths must be absolute and canonical")
    root_fd = _open_directory_chain(record_path.parent)
    try:
        root_info = os.fstat(root_fd)
        if (not stat.S_ISDIR(root_info.st_mode) or root_info.st_uid != os.geteuid()
                or root_info.st_mode & 0o077):
            raise RuntimeError("build output directory is not private and owned by this builder")
        record_bytes = _read_pinned_json(root_fd, record_path.name)

        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate qualification-record key: {key}")
                result[key] = value
            return result

        record = json.loads(record_bytes, object_pairs_hook=unique_object)
        if type(record) is not dict:
            raise RuntimeError("build qualification record is not an object")
        _validate_build_record_shape(record, source_sha256)
        outputs = record["outputs"]
        if type(outputs) is not list or len(outputs) != 2:
            raise RuntimeError("build record must describe exactly two concrete output files")
        selected_metadata: dict[str, int] | None = None
        output_digests = []
        selected_index = None
        root_text = os.path.abspath(str(record_path.parent))
        candidate_text = os.path.abspath(str(binary_path))
        for index, expected_path in enumerate(_OUTPUT_PATHS):
            if candidate_text == os.path.abspath(str(Path(root_text) / expected_path)):
                selected_index = index
                break
        if selected_index is None:
            raise RuntimeError("candidate binary is not one of the two recorded clean-build outputs")
        for index, expected_path in enumerate(_OUTPUT_PATHS):
            output = _object(outputs[index], {"path", "binary"}, f"build output {index + 1}")
            if output["path"] != expected_path:
                raise RuntimeError("build output path is missing, reordered, or substituted")
            selected_identity = _hash_attested_output(root_fd, output, f"build output {index + 1}")
            output_digests.append(output["binary"]["sha256"])
            if index == selected_index:
                selected_metadata = selected_identity
        comparison = _object(record["rebuild_comparison"], {
            "build_count", "sha256_by_build", "same_host_byte_identical",
            "independent_builder_reproduction",
        }, "rebuild comparison")
        if (type(comparison["build_count"]) is not int or comparison["build_count"] != 2
                or type(comparison["sha256_by_build"]) is not list
                or comparison["sha256_by_build"] != output_digests
                or type(comparison["same_host_byte_identical"]) is not bool
                or comparison["same_host_byte_identical"] is not (output_digests[0] == output_digests[1])
                or comparison["same_host_byte_identical"] is not True
                or comparison["independent_builder_reproduction"] != "not performed"):
            raise RuntimeError("two same-host output hashes contradict the rebuild comparison")
        first_binary = outputs[0]["binary"]
        _object(record["binary"], _BINARY_RECORD_KEYS, "primary binary record")
        if record["binary"] != first_binary:
            raise RuntimeError("primary binary record differs from the first concrete build output")
        if selected_index is None or selected_metadata is None:
            raise RuntimeError("candidate binary is not one of the two recorded clean-build outputs")
        return record, record_bytes, output_digests[selected_index], selected_metadata
    finally:
        os.close(root_fd)


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--signature", type=Path, required=True)
    parser.add_argument("--gnu-keyring", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--build-record", type=Path, required=True,
                        help="record emitted by gnu-coreutils-qualification.py build-static")
    parser.add_argument("--record", type=Path)
    args, unittest_args = parser.parse_known_args()
    try:
        source = provenance.verify_source_archive(args.archive, args.signature, args.gnu_keyring, "9.11")
        build_record, build_bytes, expected_binary_sha256, expected_output_identity = _read_build_attestation(
            args.build_record, args.binary, source["archive_sha256"],
        )
        binary = provenance._inspect_binary(
            args.binary, expected_sha256=expected_binary_sha256,
            expected_identity=expected_output_identity,
        )
        AuthenticatedGNUWorkerQualification.source_archive = args.archive
        AuthenticatedGNUWorkerQualification.source_signature = args.signature
        AuthenticatedGNUWorkerQualification.gnu_keyring = args.gnu_keyring
        AuthenticatedGNUWorkerQualification.dd_binary = args.binary
        AuthenticatedGNUWorkerQualification.expected_source_sha256 = source["archive_sha256"]
        AuthenticatedGNUWorkerQualification.expected_binary_sha256 = binary["sha256"]
        AuthenticatedGNUWorkerQualification.expected_output_identity = expected_output_identity
        AuthenticatedGNUWorkerQualification.build_record_path = args.build_record
        AuthenticatedGNUWorkerQualification.output_record = args.record
        unittest_args = [arg for arg in unittest_args if arg not in {"--verbose", "-v"}]
        result = unittest.main(argv=[sys.argv[0], *unittest_args], exit=False, verbosity=2)
        if args.record is not None and result.result.wasSuccessful():
            record = {
                "schema": "swapz.gnu-dd-seccomp-execution.v1",
                "source": source,
                "build_record_sha256": hashlib.sha256(build_bytes).hexdigest(),
                "binary": binary,
                "execution": "actual authenticated GNU static dd ran through RecallDDLaunchGate, sealed memfd, strict pass_fds, pidfd supervisor, parent-death containment, and existing seccomp filter",
                "roles": ["writer", "a", "b", "a2", "b2"],
                "mapper": "temporary ordinary regular file only; synthetic verifier; no DM device",
                "cancellation": "actual short-lived dd copy cancelled and reaped via retained pidfd",
                "test_key": "ephemeral application manifest key; test-only; deleted with temporary directory",
                "production_manifest_or_key_installed": False,
            }
            provenance._write_json(args.record, record)
        return 0 if result.result.wasSuccessful() else 1
    except Exception as exc:
        print(f"GNU worker qualification NOT RUN/PASS: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())
