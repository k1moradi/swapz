#!/usr/bin/env python3
"""Run authenticated static GNU dd through the real recall gate and pidfd worker.

The mapper is always an owned ordinary regular file. A disposable application
key is generated in a TemporaryDirectory only to exercise the existing signed
bootstrap mechanics; it is never installed or reused as a production key.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
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
    build_record_path: Path
    output_record: Path | None = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.source_record = provenance.verify_source_archive(
            cls.source_archive, cls.source_signature, cls.gnu_keyring, "9.11",
        )
        if cls.source_record["archive_sha256"] != cls.expected_source_sha256:
            raise RuntimeError("verified source hash differs from the requested qualification input")
        cls.binary_record = provenance._inspect_binary(cls.dd_binary, "9.11")
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


def _read_build_attestation(record_path: Path, binary_path: Path,
                           source_sha256: str) -> tuple[dict, bytes, str]:
    record_bytes, _ = provenance._read_regular(record_path, maximum=1024 * 1024)

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate qualification-record key: {key}")
            result[key] = value
        return result

    record = json.loads(record_bytes, object_pairs_hook=unique_object)
    if not isinstance(record, dict):
        raise RuntimeError("build qualification record is not an object")
    comparison = record.get("rebuild_comparison")
    source = record.get("source")
    binary = record.get("binary")
    if (record.get("schema") != "swapz.gnu-coreutils-dd-build.v1"
            or not isinstance(source, dict) or source.get("release") != "9.11"
            or source.get("archive_sha256") != source_sha256
            or not isinstance(comparison, dict)
            or type(comparison.get("build_count")) is not int
            or comparison["build_count"] != 2
            or comparison.get("same_host_byte_identical") is not True
            or not isinstance(binary, dict)
            or not isinstance(binary.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", binary["sha256"]) is None):
        raise RuntimeError("build record does not attest two identical GNU 9.11 builds of the verified source")
    record_root = record_path.resolve(strict=True).parent
    expected_artifacts = {
        (record_root / f"copy-{index}" / "source" / "coreutils-9.11" / "src" / "dd").resolve(strict=True)
        for index in (1, 2)
    }
    if binary_path.resolve(strict=True) not in expected_artifacts:
        raise RuntimeError("candidate binary is not one of the recorded clean-build outputs")
    return record, record_bytes, binary["sha256"]


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
        build_record, build_bytes, expected_binary_sha256 = _read_build_attestation(
            args.build_record, args.binary, source["archive_sha256"],
        )
        binary = provenance._inspect_binary(
            args.binary, "9.11", expected_sha256=expected_binary_sha256,
        )
        AuthenticatedGNUWorkerQualification.source_archive = args.archive
        AuthenticatedGNUWorkerQualification.source_signature = args.signature
        AuthenticatedGNUWorkerQualification.gnu_keyring = args.gnu_keyring
        AuthenticatedGNUWorkerQualification.dd_binary = args.binary
        AuthenticatedGNUWorkerQualification.expected_source_sha256 = source["archive_sha256"]
        AuthenticatedGNUWorkerQualification.expected_binary_sha256 = binary["sha256"]
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
