#!/usr/bin/env python3
"""Offline safety tests for proposed fixture-bound direct dd worker allowlist."""

from __future__ import annotations

import ast
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


policy_module = load("recall_dd_allowlist", HERE / "recall-dd-allowlist.py")
RecallDDAllowlist = policy_module.RecallDDAllowlist
RecallDDLaunchGate = policy_module.RecallDDLaunchGate
RecallDDFileOps = policy_module.RecallDDFileOps
DDPolicyDenied = policy_module.DDPolicyDenied
TrustedGNUCoreutilsDD = policy_module.TrustedGNUCoreutilsDD
MapperIdentity = policy_module.MapperIdentity
MapperLifecycleLease = policy_module.MapperLifecycleLease
MapperLifecycleOwner = policy_module.MapperLifecycleOwner
MapperInventory = policy_module.MapperInventory
MapperOwnerDenied = policy_module.MapperOwnerDenied
RealRecallDDFileOps = RecallDDFileOps
plan_module = load("recall_io_plan_allowlist_contract", HERE / "recall-io-plan.py")


class RootOwnedBootstrapTestOps(RealRecallDDFileOps):
    """Fake root-owned metadata for disposable files under a test trust root."""

    def __init__(self):
        self.directory_fds: set[int] = set()
        self.trust_file_fds: set[int] = set()

    def open(self, path, flags, mode=0o777, *, dir_fd=None):
        fd = super().open(path, flags, mode, dir_fd=dir_fd)
        if flags & os.O_DIRECTORY:
            self.directory_fds.add(fd)
        elif dir_fd in self.directory_fds:
            self.trust_file_fds.add(fd)
        return fd

    def fstat(self, fd):
        info = super().fstat(fd)
        if fd in self.directory_fds:
            return SimpleNamespace(
                st_mode=stat.S_IFDIR | (stat.S_IMODE(info.st_mode) & ~0o022),
                st_uid=0, st_nlink=info.st_nlink, st_dev=info.st_dev,
                st_ino=info.st_ino, st_size=info.st_size,
                st_mtime_ns=info.st_mtime_ns, st_ctime_ns=info.st_ctime_ns,
            )
        if fd in self.trust_file_fds:
            return SimpleNamespace(
                st_mode=stat.S_IFREG | (stat.S_IMODE(info.st_mode) & ~0o022),
                st_uid=0, st_nlink=info.st_nlink, st_dev=info.st_dev,
                st_ino=info.st_ino, st_size=info.st_size,
                st_mtime_ns=info.st_mtime_ns, st_ctime_ns=info.st_ctime_ns,
            )
        return info

    def close(self, fd):
        self.directory_fds.discard(fd)
        self.trust_file_fds.discard(fd)
        return super().close(fd)


class DummySupervisor:
    def __init__(self):
        self.commands = []
    def launch(self, argv):
        self.commands.append(tuple(argv))
        return f"handle-{len(self.commands)}"


class DDAllowlistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "fixture"
        self.root.mkdir()
        self.source = self.root / "pages.bin"
        self.source.write_bytes(bytes(range(256)) * (4096 * 9 // 256))
        self.source.chmod(0o600)
        self.name = "swapz-v22-recall-safe-42"
        self.policy = RecallDDAllowlist(self.root, self.name)

    def test_exact_writer_command_and_one_use(self):
        cmd = self.policy.admit("writer")
        self.assertEqual(cmd.role, "writer")
        self.assertIsNone(cmd.page)
        self.assertEqual(cmd.argv, (
            "dd", f"if={self.source}", f"of=/dev/mapper/{self.name}",
            "bs=4096", "count=9", "oflag=direct", "conv=notrunc", "status=none"))
        self.assertEqual(self.policy.roles_issued, ("writer",))
        with self.assertRaisesRegex(DDPolicyDenied, "repeated"):
            self.policy.admit("writer")
        with self.assertRaisesRegex(DDPolicyDenied, "closed"):
            self.policy.admit("a")

    def test_exact_four_read_commands(self):
        self.policy.admit("writer")
        for role, page in (("a", 0), ("b", 4), ("a2", 0), ("b2", 5)):
            with self.subTest(role=role):
                cmd = self.policy.admit(role)
                self.assertEqual(cmd.page, page)
                self.assertEqual(cmd.argv, (
                    "dd", f"if=/dev/mapper/{self.name}",
                    f"of={self.root / ('read-' + role)}", "bs=4096",
                    f"skip={page}", "count=1", "iflag=direct", "status=none"))
        self.assertEqual(self.policy.roles_issued,
                         ("writer", "a", "b", "a2", "b2"))

    def test_commands_match_existing_fixture_neutral_io_plan(self):
        fake = DummySupervisor()
        plan = plan_module.RecallIOPlan(
            source=self.source, output_dir=self.root,
            mapper=f"/dev/mapper/{self.name}", supervisor=fake)
        writer = self.policy.admit("writer")
        plan.launch_writer()
        self.assertEqual(writer.argv, fake.commands[0])
        for role, page in (("a", 0), ("b", 4), ("a2", 0), ("b2", 5)):
            cmd = self.policy.admit(role)
            self.assertEqual(cmd.argv, plan._read_argv(page, self.root / ("read-" + role)))

    def test_exact_matching_proposal_is_admitted(self):
        proposed = self.policy._command("writer").argv
        self.assertEqual(self.policy.admit("writer", proposed).argv, proposed)

    def test_rejects_tampered_dd_arguments_and_permanent_denial(self):
        original = self.policy._command("writer").argv
        changes = (
            {1: "if=/etc/passwd"}, {2: "of=/dev/sda"}, {3: "bs=512"},
            {4: "count=10"}, {5: "oflag=append"}, {6: "conv=fsync"},
            {7: "status=progress"},
        )
        for offsets in changes:
            with self.subTest(change=offsets):
                policy = RecallDDAllowlist(self.root, self.name)
                proposal = list(original)
                for index, replacement in offsets.items():
                    proposal[index] = replacement
                with self.assertRaisesRegex(DDPolicyDenied, "unapproved"):
                    policy.admit("writer", proposal)
                self.assertEqual(policy.roles_issued, ())
                with self.assertRaises(DDPolicyDenied):
                    policy.admit("writer", original)

    def test_rejects_extra_options_or_shell_injection_arguments(self):
        original = self.policy._command("writer").argv
        for proposed in (original + ("of=/dev/sdb",), ("sh", "-c", "dd"),
                         original + ("; rm -rf /",), "dd if=x"):
            with self.subTest(proposed=proposed):
                policy = RecallDDAllowlist(self.root, self.name)
                with self.assertRaises(DDPolicyDenied):
                    policy.admit("writer", proposed)

    def test_reader_offset_and_output_redirect_rejected(self):
        self.policy.admit("writer")
        original = self.policy._command("b").argv
        for index, replacement in ((1, "if=/dev/mapper/other"),
                                   (2, "of=/tmp/bad"), (4, "skip=0"),
                                   (5, "count=9"), (6, "iflag=none")):
            with self.subTest(index=index):
                p = RecallDDAllowlist(self.root, self.name)
                p.admit("writer")
                args = list(original)
                args[index] = replacement
                with self.assertRaises(DDPolicyDenied):
                    p.admit("b", args)

    def test_unknown_role_fails_closed(self):
        with self.assertRaises(DDPolicyDenied):
            self.policy.admit("../sdb")
        with self.assertRaises(DDPolicyDenied):
            self.policy.admit("writer")

    def test_reader_cannot_precede_writer(self):
        with self.assertRaisesRegex(DDPolicyDenied, "before"):
            self.policy.admit("a")
        self.assertEqual(self.policy.roles_issued, ())

    def test_replayed_reader_denies_future_admission(self):
        self.policy.admit("writer")
        self.policy.admit("a")
        with self.assertRaises(DDPolicyDenied):
            self.policy.admit("a")
        with self.assertRaises(DDPolicyDenied):
            self.policy.admit("b")

    def test_explicit_close_admission(self):
        self.policy.admit("writer")
        self.policy.close_admission()
        with self.assertRaisesRegex(DDPolicyDenied, "closed"):
            self.policy.admit("a")

    def test_wrong_mapper_grammar_rejected(self):
        for name in ("sda", "swapz-v22-recall-../sda",
                     "swapz-v22-recall-a/b", "swapz-v22-recall-",
                     "swapz-v22-recall-a b", "swapz-v22-recall-a\x00",
                     "swapz-v22-recall-" + "a" * 90):
            with self.subTest(name=name), self.assertRaises(DDPolicyDenied):
                RecallDDAllowlist(self.root, name)

    def test_relative_or_traversal_fixture_root_rejected(self):
        for root in (Path("fixture"), self.root / "..",
                     self.root / "nonexistent"):
            with self.subTest(root=root), self.assertRaises(DDPolicyDenied):
                RecallDDAllowlist(root, self.name)

    def test_fixture_root_symlink_rejected(self):
        link = self.base / "fixture-link"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(DDPolicyDenied):
            RecallDDAllowlist(link, self.name)

    def test_symlinked_parent_rejected(self):
        parent = self.base / "alias"
        parent.symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(DDPolicyDenied):
            RecallDDAllowlist(parent / "fixture", self.name)

    def test_source_symlink_rejected(self):
        real = self.root / "real-pages.bin"
        self.source.rename(real)
        self.source.symlink_to(real)
        with self.assertRaises(DDPolicyDenied):
            RecallDDAllowlist(self.root, self.name)

    def test_source_hardlink_rejected(self):
        os.link(self.source, self.root / "second-pages")
        with self.assertRaises(DDPolicyDenied):
            RecallDDAllowlist(self.root, self.name)

    def test_source_fifo_rejected_without_opening_fifo(self):
        self.source.unlink()
        os.mkfifo(self.source)
        with self.assertRaises(DDPolicyDenied):
            RecallDDAllowlist(self.root, self.name)

    def test_source_wrong_size_rejected(self):
        for size in (0, 1, 4096, 9 * 4096 + 1):
            with self.subTest(size=size):
                self.source.write_bytes(b"x" * size)
                with self.assertRaisesRegex(DDPolicyDenied, "wrong size"):
                    RecallDDAllowlist(self.root, self.name)

    def test_source_replaced_same_size_between_init_and_admission(self):
        replacement = self.root / "replacement"
        replacement.write_bytes(b"y" * (4096 * 9))
        self.source.unlink()
        replacement.rename(self.source)
        with self.assertRaisesRegex(DDPolicyDenied, "identity"):
            self.policy.admit("writer")
        self.assertEqual(self.policy.roles_issued, ())

    def test_source_changed_size_between_init_and_admission(self):
        self.source.write_bytes(b"x" * 4096)
        with self.assertRaisesRegex(DDPolicyDenied, "identity"):
            self.policy.admit("writer")

    def test_fixture_root_replaced_between_init_and_admission(self):
        old = self.base / "old-fixture"
        self.root.rename(old)
        self.root.mkdir()
        (self.root / "pages.bin").write_bytes(bytes(4096 * 9))
        with self.assertRaisesRegex(DDPolicyDenied, "identity"):
            self.policy.admit("writer")

    def test_existing_readback_symlink_denies_and_preserves_target(self):
        victim = self.base / "victim"
        victim.write_text("unchanged")
        (self.root / "read-a").symlink_to(victim)
        self.policy.admit("writer")
        with self.assertRaisesRegex(DDPolicyDenied, "already exists"):
            self.policy.admit("a")
        self.assertEqual(victim.read_text(), "unchanged")

    def test_dangling_output_symlink_denies(self):
        (self.root / "read-a").symlink_to(self.root / "missing-target")
        self.policy.admit("writer")
        with self.assertRaisesRegex(DDPolicyDenied, "already exists"):
            self.policy.admit("a")

    def test_existing_regular_output_or_fifo_denies(self):
        for kind in ("regular", "fifo"):
            with self.subTest(kind=kind):
                output = self.root / "read-a"
                if kind == "regular":
                    output.write_text("old")
                else:
                    os.mkfifo(output)
                policy = RecallDDAllowlist(self.root, self.name)
                policy.admit("writer")
                with self.assertRaisesRegex(DDPolicyDenied, "already exists"):
                    policy.admit("a")
                output.unlink()

    def test_does_not_expose_numeric_pid_or_launch_processes(self):
        tree = ast.parse((HERE / "recall-dd-allowlist.py").read_text())
        allowlist = next(node for node in tree.body
                         if isinstance(node, ast.ClassDef)
                         and node.name == "RecallDDAllowlist")
        banned = {"kill", "fork", "Popen", "run", "system", "execv",
                  "execve", "posix_spawn", "ioctl", "swapon", "swapoff"}
        for node in ast.walk(allowlist):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                self.assertNotIn(name, banned)
        self.assertFalse(hasattr(self.policy, "launch"))
        self.assertFalse(hasattr(self.policy, "stop_all"))


class PinnedDDLaunchGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.test_key_dir = tempfile.TemporaryDirectory(prefix="swapz-test-ed25519-")
        cls.test_key_root = Path(cls.test_key_dir.name)
        cls.test_private_key = cls.test_key_root / "test-only-private.pem"
        cls.test_public_key = cls.test_key_root / "test-only-public.pem"
        subprocess.run(
            ["/usr/bin/openssl", "genpkey", "-algorithm", "ED25519",
             "-out", str(cls.test_private_key)],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["/usr/bin/openssl", "pkey", "-in", str(cls.test_private_key),
             "-pubout", "-out", str(cls.test_public_key)],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.test_key_dir.cleanup()

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "private-fixture"
        self.root.mkdir(mode=0o700)
        self.source = self.root / "pages.bin"
        self.original = bytes(range(256)) * (4096 * 9 // 256)
        self.source.write_bytes(self.original)
        self.source.chmod(0o600)
        self.name = "swapz-v22-recall-source-only"
        self.trust_root = self.base / "trusted-bootstrap"
        self.trust_root.mkdir(mode=0o700)
        self.trust_root.chmod(0o700)
        self.trust_key_root = self.base / "separately-provisioned-trust-anchor"
        self.trust_key_root.mkdir(mode=0o700)
        self.trust_key_root.chmod(0o700)
        self.trust_public_key_path = self.trust_key_root / "swapz-gnu-dd-manifest-ed25519.pub"
        shutil.copyfile(self.test_public_key, self.trust_public_key_path)
        self.trust_public_key_path.chmod(0o600)

    def make_gate(self, *, executable: Path | None = None,
                  ops: RecallDDFileOps | None = None):
        map_path = self.base / "synthetic-mapper-fd"
        map_path.write_bytes(b"fake block mapping descriptor")
        map_path.chmod(0o600)
        map_fd = os.open(map_path, os.O_RDONLY | os.O_CLOEXEC)
        try:
            gate = RecallDDLaunchGate(
                self.root, self.name, mapper_fd=map_fd,
                executable_path=Path(sys.executable) if executable is None else executable,
                ops=ops,
                mapper_verifier=lambda fd, name, file_ops: (
                    name == self.name and stat.S_ISREG(file_ops.fstat(fd).st_mode)
                ),
            )
        finally:
            os.close(map_fd)
        self.addCleanup(gate.close)
        return gate

    @staticmethod
    def static_elf_fixture() -> bytes:
        header = bytearray(64)
        header[:16] = b"\x7fELF\x02\x01\x01" + bytes(9)
        header[16:18] = (2).to_bytes(2, "little")
        machine = {"x86_64": 62, "amd64": 62, "aarch64": 183,
                   "arm64": 183}.get(platform.machine().lower(), 62)
        header[18:20] = machine.to_bytes(2, "little")
        header[20:24] = (1).to_bytes(4, "little")
        header[52:54] = (64).to_bytes(2, "little")
        header[54:56] = (56).to_bytes(2, "little")
        header[56:58] = (0).to_bytes(2, "little")
        header[58:60] = (64).to_bytes(2, "little")
        return bytes(header)

    def trusted_manifest(self, executable: Path, contents: bytes,
                         *, vendor: str = "GNU Project", linkage: str = "static",
                         signing_key: Path | None = None):
        document = {
            "format": 1, "vendor": vendor, "package": "coreutils", "binary": "dd",
            "version": "9.7", "executable": str(executable),
            "sha256": hashlib.sha256(contents).hexdigest(),
            "source_sha256": "a" * 64, "linkage": linkage,
        }
        payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        self.install_signed_payload(payload, signing_key=signing_key)
        return self.load_trusted_manifest()

    def install_signed_payload(self, payload: bytes, *, signing_key: Path | None = None):
        manifest_path = self.trust_root / "manifest.json"
        signature_path = self.trust_root / "manifest.sig"
        manifest_path.write_bytes(payload)
        manifest_path.chmod(0o600)
        subprocess.run(
            ["/usr/bin/openssl", "pkeyutl", "-sign", "-rawin", "-inkey",
             str(signing_key or self.test_private_key), "-in", str(manifest_path),
             "-out", str(signature_path)],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        signature_path.chmod(0o600)

    def load_trusted_manifest(self):
        with mock.patch.object(policy_module, "_TRUSTED_DD_BOOTSTRAP_DIR", self.trust_root), \
                mock.patch.object(policy_module, "_TRUSTED_DD_PUBLIC_KEY_PATH",
                                  self.trust_public_key_path), \
                mock.patch.object(policy_module, "RecallDDFileOps", RootOwnedBootstrapTestOps):
            return TrustedGNUCoreutilsDD.from_trusted_bootstrap()

    def block_fixture(self, executable: Path, *, identity_reader=None,
                      expected_override=None,
                      fail_snapshot: bool = False):
        mapper_path = self.base / "synthetic-block-mapper"
        mapper_path.write_bytes(b"synthetic descriptor only")
        mapper_fd = os.open(mapper_path, os.O_RDONLY | os.O_CLOEXEC)
        expected = expected_override or MapperIdentity(
            self.name, "SWAPZ-TEST-IDENTITY", 253, 17, "b" * 64,
        )

        class BlockDescriptorOps(RecallDDFileOps):
            def __init__(self):
                self.block_fds = {mapper_fd}
                self.executable_fds = set()
                self.closed_block_fds = set()

            def close(self, fd):
                if fd in self.block_fds:
                    self.closed_block_fds.add(fd)
                    self.block_fds.discard(fd)
                return super().close(fd)

            def dup_cloexec(self, fd):
                duplicate = super().dup_cloexec(fd)
                if fd in self.block_fds:
                    self.block_fds.add(duplicate)
                return duplicate

            def open(self, path, flags, mode=0o777, *, dir_fd=None):
                fd = super().open(path, flags, mode, dir_fd=dir_fd)
                if path == str(executable):
                    self.executable_fds.add(fd)
                return fd

            def fstat(self, fd):
                if fd in self.block_fds:
                    return SimpleNamespace(
                        st_mode=stat.S_IFBLK | 0o600, st_rdev=os.makedev(253, 17),
                        st_uid=0, st_dev=0, st_ino=17, st_size=0,
                        st_mtime_ns=0, st_ctime_ns=0, st_nlink=1,
                    )
                info = super().fstat(fd)
                if fd in self.executable_fds:
                    return SimpleNamespace(
                        st_mode=info.st_mode, st_uid=0, st_size=info.st_size,
                        st_dev=info.st_dev, st_ino=info.st_ino,
                        st_mtime_ns=info.st_mtime_ns, st_ctime_ns=info.st_ctime_ns,
                        st_nlink=info.st_nlink, st_gid=info.st_gid,
                    )
                return info

            def read_dm_sysfs_attr(self, major, minor, attribute):
                return {"name": expected.name, "uuid": expected.uuid,
                        "dev": f"{major}:{minor}"}[attribute]

            def create_sealed_executable(self, source_fd, expected_sha256, maximum_size):
                if fail_snapshot:
                    raise OSError(38, "injected executable memfd unsupported")
                return super().create_sealed_executable(
                    source_fd, expected_sha256, maximum_size,
                )

        ops = BlockDescriptorOps()
        lock_path = self.base / ("mapper-lifecycle-" + executable.stem + ".lock")
        lock_path.touch(mode=0o600)
        lock_path.chmod(0o600)
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CLOEXEC)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        reader = identity_reader or (lambda _fd, _name, _ops: expected)
        lease = MapperLifecycleLease(
            lock_fd, lock_path, expected, reader, ops=ops,
        )
        os.close(lock_fd)

        class FakeOwnerOperations:
            def __init__(self):
                self.alive = True
                self.entries: tuple[MapperIdentity, ...] = ()
                self.events: list[str] = []
                self.inventory_valid = True
                self.remove_result = True
                self.after_inventory = None

            def owner_alive(self):
                return self.alive

            def inventory(self):
                self.events.append("inventory")
                inventory = MapperInventory(self.inventory_valid, self.entries)
                if self.after_inventory is not None:
                    self.after_inventory()
                return inventory

            def create_mapping(self, identity):
                self.events.append("create")
                if identity != expected or self.entries:
                    raise AssertionError("owner attempted unexpected or duplicate mapping creation")
                self.entries = (identity,)
                return mapper_fd

            def remove_mapping(self, identity):
                self.events.append("remove")
                if identity != expected:
                    raise AssertionError("owner attempted unexpected mapping removal")
                if self.remove_result:
                    self.entries = ()
                return self.remove_result

        owner_operations = FakeOwnerOperations()
        owner = MapperLifecycleOwner(
            expected, lease, owner_operations, file_ops=ops,
        )
        owner.create()
        self.addCleanup(lease.close)
        self.addCleanup(
            lambda: os.close(mapper_fd) if mapper_fd not in ops.closed_block_fds else None,
        )
        return mapper_fd, ops, expected, lease, owner

    def test_all_five_roles_have_exact_fd_bound_argv_and_cloexec_parent(self):
        gate = self.make_gate()
        writer = gate.admit("writer")
        source_fd = gate._source_fd
        mapper_fd = gate._mapper_fd
        executable_fd = gate._executable_fd
        self.assertEqual(writer.argv, (
            "dd", f"if=/proc/self/fd/{source_fd}", f"of=/proc/self/fd/{mapper_fd}",
            "bs=4096", "count=9", "oflag=direct", "conv=notrunc", "status=none",
        ))
        self.assertEqual(writer.executable, f"/proc/self/fd/{executable_fd}")
        self.assertEqual(writer.pass_fds, (source_fd, mapper_fd))
        expected = {"a": 0, "b": 4, "a2": 0, "b2": 5}
        for role, page in expected.items():
            launch = gate.admit(role)
            output_fd = gate._output_fds[role]
            self.assertEqual(launch.argv, (
                "dd", f"if=/proc/self/fd/{mapper_fd}", f"of=/proc/self/fd/{output_fd}",
                "bs=4096", f"skip={page}", "count=1", "iflag=direct", "status=none",
            ))
            self.assertEqual(launch.page, page)
            self.assertEqual(launch.output_path, self.root / ("read-" + role))
            self.assertEqual(launch.pass_fds, (source_fd, mapper_fd, output_fd))
        self.assertEqual(gate.roles_issued, ("writer", "a", "b", "a2", "b2"))
        for fd in (gate._directory_fd, source_fd, mapper_fd, executable_fd,
                   *gate._output_fds.values()):
            self.assertFalse(os.get_inheritable(fd), f"parent fd {fd} must remain CLOEXEC")

    def test_gate_is_one_use_and_reader_before_writer_closes_admission(self):
        gate = self.make_gate()
        with self.assertRaisesRegex(DDPolicyDenied, "before"):
            gate.admit("a")
        with self.assertRaisesRegex(DDPolicyDenied, "permanently closed"):
            gate.admit("writer")
        gate2 = self.make_gate()
        gate2.admit("writer")
        gate2.admit("a")
        with self.assertRaisesRegex(DDPolicyDenied, "repeated"):
            gate2.admit("a")
        with self.assertRaises(DDPolicyDenied):
            gate2.admit("b")

    def test_default_mapper_verification_requires_exact_block_dm_name(self):
        fake = self.base / "not-a-block-device"
        fake.write_bytes(b"ordinary file")
        fd = os.open(fake, os.O_RDONLY | os.O_CLOEXEC)
        try:
            with self.assertRaisesRegex(DDPolicyDenied, "not a block device"):
                policy_module._verify_dm_descriptor(fd, self.name, RecallDDFileOps())
        finally:
            os.close(fd)

    def test_trusted_mapper_descriptor_must_be_close_on_exec(self):
        mapper_path = self.base / "synthetic-inheritable-mapper"
        mapper_path.write_bytes(b"synthetic mapper identity")
        mapper_fd = os.open(mapper_path, os.O_RDONLY)
        try:
            os.set_inheritable(mapper_fd, True)
            with self.assertRaisesRegex(DDPolicyDenied, "close-on-exec"):
                RecallDDLaunchGate(
                    self.root, self.name, mapper_fd=mapper_fd,
                    executable_path=Path(sys.executable),
                    mapper_verifier=lambda *_: True,
                )
        finally:
            os.close(mapper_fd)

    def test_character_and_nonfixture_mapper_descriptors_are_rejected(self):
        mapper_path = self.base / "synthetic-not-block"
        mapper_path.write_bytes(b"test descriptor")
        mapper_fd = os.open(mapper_path, os.O_RDONLY | os.O_CLOEXEC)

        class CharacterDeviceOps(RecallDDFileOps):
            def fstat(self, fd):
                if fd == mapper_fd:
                    return SimpleNamespace(
                        st_mode=stat.S_IFCHR | 0o666, st_rdev=os.makedev(1, 3),
                        st_uid=os.geteuid(), st_nlink=1,
                    )
                return super().fstat(fd)

        try:
            with self.assertRaisesRegex(DDPolicyDenied, "non-DM mapper descriptor"):
                RecallDDLaunchGate(
                    self.root, self.name, mapper_fd=mapper_fd,
                    executable_path=Path(sys.executable), ops=CharacterDeviceOps(),
                )
        finally:
            os.close(mapper_fd)

        regular_fd = os.open(mapper_path, os.O_RDONLY | os.O_CLOEXEC)
        try:
            with self.assertRaisesRegex(DDPolicyDenied, "not positively verified"):
                RecallDDLaunchGate(
                    self.root, self.name, mapper_fd=regular_fd,
                    executable_path=Path(sys.executable),
                    mapper_verifier=lambda *_: None,
                )
        finally:
            os.close(regular_fd)

    def test_missing_or_replaced_source_denies_before_launch(self):
        self.source.unlink()
        with self.assertRaises(DDPolicyDenied):
            self.make_gate()
        self.source.write_bytes(self.original)
        self.source.chmod(0o600)
        gate = self.make_gate()
        replacement = self.root / "replacement.bin"
        replacement.write_bytes(self.original)
        replacement.chmod(0o600)
        replacement.replace(self.source)
        with self.assertRaisesRegex(DDPolicyDenied, "identity"):
            gate.admit("writer")
        self.assertEqual(gate.roles_issued, ())

    def test_private_directory_and_exact_source_shape_are_required(self):
        for kind in ("mode", "wrong-size", "hardlink", "symlink"):
            with self.subTest(kind=kind):
                if kind == "mode":
                    self.root.chmod(0o755)
                elif kind == "wrong-size":
                    self.source.write_bytes(b"short")
                    self.source.chmod(0o600)
                elif kind == "hardlink":
                    os.link(self.source, self.base / "second-source-link")
                else:
                    real = self.root / "real-pages.bin"
                    self.source.replace(real)
                    self.source.symlink_to(real)
                with self.assertRaises(DDPolicyDenied):
                    self.make_gate()
                if kind == "mode":
                    self.root.chmod(0o700)
                elif kind == "hardlink":
                    (self.base / "second-source-link").unlink()
                elif kind == "symlink":
                    self.source.unlink()
                    (self.root / "real-pages.bin").replace(self.source)
                    self.source.chmod(0o600)
                elif kind == "wrong-size":
                    self.source.write_bytes(self.original)
                    self.source.chmod(0o600)

    def test_symlink_parent_and_mutable_source_type_are_rejected(self):
        alias = self.base / "fixture-link"
        alias.symlink_to(self.root, target_is_directory=True)
        map_path = self.base / "synthetic-map"
        map_path.write_bytes(b"fake")
        map_fd = os.open(map_path, os.O_RDONLY | os.O_CLOEXEC)
        try:
            with self.assertRaises(DDPolicyDenied):
                RecallDDLaunchGate(
                    alias, self.name, mapper_fd=map_fd,
                    executable_path=Path(sys.executable),
                    mapper_verifier=lambda *_: True,
                )
        finally:
            os.close(map_fd)

        gate = self.make_gate()
        source = self.root / "pages.bin"
        source.unlink()
        os.mkfifo(source)
        with self.assertRaisesRegex(DDPolicyDenied, "identity"):
            gate.admit("writer")

    def test_replaced_fixture_directory_path_is_rejected(self):
        gate = self.make_gate()
        moved = self.base / "original-fixture"
        self.root.rename(moved)
        self.root.mkdir(mode=0o700)
        replacement = self.root / "pages.bin"
        replacement.write_bytes(self.original)
        replacement.chmod(0o600)
        with self.assertRaisesRegex(DDPolicyDenied, "directory path identity"):
            gate.admit("writer")

    def test_output_creation_rejects_regular_fifo_hardlink_and_symlink_entries(self):
        for kind in ("regular", "fifo", "hardlink", "symlink", "dangling"):
            with self.subTest(kind=kind):
                gate = self.make_gate()
                gate.admit("writer")
                output = self.root / "read-a"
                if kind == "regular":
                    output.write_bytes(b"old")
                elif kind == "fifo":
                    os.mkfifo(output)
                elif kind == "hardlink":
                    hardlink_target = self.base / "hardlink-target"
                    hardlink_target.write_text("private test target")
                    os.link(hardlink_target, output)
                elif kind == "symlink":
                    victim = self.base / "victim"
                    victim.write_text("safe")
                    output.symlink_to(victim)
                else:
                    output.symlink_to(self.base / "missing")
                with self.assertRaisesRegex(DDPolicyDenied, "already exists"):
                    gate.admit("a")
                if kind == "symlink":
                    self.assertEqual(victim.read_text(), "safe")
                output.unlink()

    def test_replacement_after_admission_cannot_redirect_pinned_source(self):
        gate = self.make_gate()
        launch = gate.admit("writer")
        source_fd = gate._source_fd
        original_identity = (os.fstat(source_fd).st_dev, os.fstat(source_fd).st_ino)
        moved = self.root / "renamed-pages.bin"
        self.source.replace(moved)
        self.source.write_bytes(b"replacement" * (4096 * 9 // 11))
        self.source.chmod(0o600)
        self.assertIn(f"if=/proc/self/fd/{source_fd}", launch.argv)
        self.assertEqual(os.pread(source_fd, len(self.original), 0), self.original)
        self.assertEqual((os.fstat(source_fd).st_dev, os.fstat(source_fd).st_ino),
                         original_identity)

    def test_output_path_replacement_after_admission_cannot_redirect_pinned_fd(self):
        gate = self.make_gate()
        gate.admit("writer")
        launch = gate.admit("a")
        output_fd = gate._output_fds["a"]
        output_path = self.root / "read-a"
        moved = self.root / "read-a-original"
        victim = self.base / "victim"
        victim.write_bytes(b"unchanged")
        identity = (os.fstat(output_fd).st_dev, os.fstat(output_fd).st_ino)
        output_path.replace(moved)
        output_path.symlink_to(victim)
        self.assertIn(f"of=/proc/self/fd/{output_fd}", launch.argv)
        os.write(output_fd, b"synthetic worker output")
        self.assertEqual(victim.read_bytes(), b"unchanged")
        self.assertEqual(moved.read_bytes(), b"synthetic worker output")
        self.assertEqual((os.fstat(output_fd).st_dev, os.fstat(output_fd).st_ino), identity)

    def test_mapper_identity_is_rechecked_at_each_role_launch(self):
        mapper_path = self.base / "synthetic-map-changing"
        mapper_path.write_bytes(b"synthetic fd")
        mapper_path.chmod(0o600)
        mapper_fd = os.open(mapper_path, os.O_RDONLY | os.O_CLOEXEC)
        checks = iter((True, True, False))
        try:
            gate = RecallDDLaunchGate(
                self.root, self.name, mapper_fd=mapper_fd,
                executable_path=Path(sys.executable),
                mapper_verifier=lambda *_: next(checks),
            )
        finally:
            os.close(mapper_fd)
        self.addCleanup(gate.close)
        gate.admit("writer")
        with self.assertRaisesRegex(DDPolicyDenied, "identity no longer matches"):
            gate.admit("a")

    def test_block_mapper_rejects_candidate_digest_without_signed_manifest(self):
        executable_path = self.base / "candidate-dd"
        executable_path.write_bytes(self.static_elf_fixture())
        executable_path.chmod(0o755)
        mapper_fd, ops, _identity, lease, owner = self.block_fixture(executable_path)
        digest = hashlib.sha256(executable_path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(DDPolicyDenied, "signed GNU coreutils trust manifest"):
            RecallDDLaunchGate(
                self.root, self.name, mapper_fd=mapper_fd,
                executable_path=executable_path,
                expected_executable_sha256=digest,
                mapper_lifecycle_lease=lease, mapper_owner=owner, ops=ops,
            )

    def test_signed_manifest_is_strict_and_binds_static_gnu_identity(self):
        path = self.base / "candidate-dd"
        data = self.static_elf_fixture()
        path.write_bytes(data)
        path.chmod(0o755)
        trusted = self.trusted_manifest(path, data)
        self.assertEqual(trusted.executable_path, path)
        self.assertEqual(trusted.sha256, hashlib.sha256(data).hexdigest())
        payload = (self.trust_root / "manifest.json").read_bytes()
        signature_path = self.trust_root / "manifest.sig"
        signature = bytearray(signature_path.read_bytes())
        signature[-1] ^= 1
        signature_path.write_bytes(signature)
        with self.assertRaisesRegex(DDPolicyDenied, "signature"):
            self.load_trusted_manifest()
        with self.assertRaisesRegex(DDPolicyDenied, "GNU coreutils"):
            self.trusted_manifest(path, data, vendor="uutils")
        with self.assertRaisesRegex(DDPolicyDenied, "GNU coreutils"):
            self.trusted_manifest(path, data, linkage="dynamic")
        duplicate = b'{"format":1,"format":1}'
        self.install_signed_payload(duplicate)
        with self.assertRaisesRegex(DDPolicyDenied, "duplicate"):
            self.load_trusted_manifest()

    def test_detached_signature_rejects_wrong_key_and_untrusted_api_arguments(self):
        path = self.base / "signature-test-dd"
        data = self.static_elf_fixture()
        path.write_bytes(data)
        path.chmod(0o755)
        wrong_private = self.base / "wrong-private.pem"
        subprocess.run(
            ["/usr/bin/openssl", "genpkey", "-algorithm", "ED25519",
             "-out", str(wrong_private)],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        document = {
            "format": 1, "vendor": "GNU Project", "package": "coreutils",
            "binary": "dd", "version": "9.7", "executable": str(path),
            "sha256": hashlib.sha256(data).hexdigest(),
            "source_sha256": "a" * 64, "linkage": "static",
        }
        payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        self.install_signed_payload(payload, signing_key=wrong_private)
        with self.assertRaisesRegex(DDPolicyDenied, "signature"):
            self.load_trusted_manifest()
        with self.assertRaises(TypeError):
            TrustedGNUCoreutilsDD.from_trusted_bootstrap(lambda *_: True)
        self.assertFalse(hasattr(TrustedGNUCoreutilsDD, "from_signed_manifest"))
        self.assertFalse(hasattr(TrustedGNUCoreutilsDD, "_from_verified_manifest"))

    def test_revoked_missing_and_unavailable_trust_configuration_denies(self):
        path = self.base / "revocation-test-dd"
        data = self.static_elf_fixture()
        path.write_bytes(data)
        path.chmod(0o755)
        self.trusted_manifest(path, data)
        (self.trust_root / "REVOKED").write_text("revoked by trusted administrator\n")
        with self.assertRaisesRegex(DDPolicyDenied, "revoked"):
            self.load_trusted_manifest()
        (self.trust_root / "REVOKED").unlink()
        self.trust_public_key_path.unlink()
        with self.assertRaisesRegex(DDPolicyDenied, "cannot open trusted bootstrap"):
            self.load_trusted_manifest()

    def test_non_ed25519_trust_key_is_rejected(self):
        path = self.base / "wrong-key-type-dd"
        data = self.static_elf_fixture()
        path.write_bytes(data)
        path.chmod(0o755)
        self.trusted_manifest(path, data)
        rsa_private = self.base / "not-ed25519-private.pem"
        rsa_public = self.base / "not-ed25519-public.pem"
        subprocess.run(
            ["/usr/bin/openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt",
             "rsa_keygen_bits:1024", "-out", str(rsa_private)],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        subprocess.run(
            ["/usr/bin/openssl", "pkey", "-in", str(rsa_private), "-pubout",
             "-out", str(rsa_public)],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        shutil.copyfile(rsa_public, self.trust_public_key_path)
        self.trust_public_key_path.chmod(0o600)
        with self.assertRaisesRegex(DDPolicyDenied, "not an Ed25519"):
            self.load_trusted_manifest()

    def test_bootstrap_metadata_and_close_failures_deny(self):
        path = self.base / "bootstrap-fault-dd"
        data = self.static_elf_fixture()
        path.write_bytes(data)
        path.chmod(0o755)
        self.trusted_manifest(path, data)

        original_fstat = RootOwnedBootstrapTestOps.fstat

        def fail_trust_file_stat(ops, fd):
            if fd in ops.trust_file_fds:
                raise OSError("injected trusted-file metadata EIO")
            return original_fstat(ops, fd)

        with mock.patch.object(RootOwnedBootstrapTestOps, "fstat", fail_trust_file_stat):
            with self.assertRaisesRegex(DDPolicyDenied, "cannot read trusted bootstrap"):
                self.load_trusted_manifest()

        original_close = RootOwnedBootstrapTestOps.close

        def fail_trust_file_close(ops, fd):
            is_trust_file = fd in ops.trust_file_fds
            original_close(ops, fd)
            if is_trust_file:
                raise OSError("injected trusted-file close EIO")

        with mock.patch.object(RootOwnedBootstrapTestOps, "close", fail_trust_file_close):
            with self.assertRaisesRegex(DDPolicyDenied, "descriptor close failed"):
                self.load_trusted_manifest()

    def test_bootstrap_directory_and_file_symlinks_are_rejected(self):
        path = self.base / "bootstrap-symlink-dd"
        data = self.static_elf_fixture()
        path.write_bytes(data)
        path.chmod(0o755)
        self.trusted_manifest(path, data)

        alias = self.base / "bootstrap-alias"
        alias.symlink_to(self.trust_root, target_is_directory=True)
        with mock.patch.object(policy_module, "_TRUSTED_DD_BOOTSTRAP_DIR", alias), \
                mock.patch.object(policy_module, "_TRUSTED_DD_PUBLIC_KEY_PATH",
                                  self.trust_public_key_path), \
                mock.patch.object(policy_module, "RecallDDFileOps", RootOwnedBootstrapTestOps):
            with self.assertRaisesRegex(DDPolicyDenied, "cannot inspect trusted bootstrap path"):
                TrustedGNUCoreutilsDD.from_trusted_bootstrap()

        manifest = self.trust_root / "manifest.json"
        saved_manifest = self.base / "manifest.saved"
        manifest.rename(saved_manifest)
        manifest.symlink_to(saved_manifest)
        with self.assertRaisesRegex(DDPolicyDenied, "cannot open trusted bootstrap manifest"):
            self.load_trusted_manifest()
        manifest.unlink()
        saved_manifest.rename(manifest)

        real_key = self.base / "real-trust-key.pem"
        shutil.copyfile(self.trust_public_key_path, real_key)
        self.trust_public_key_path.unlink()
        self.trust_public_key_path.symlink_to(real_key)
        with self.assertRaisesRegex(DDPolicyDenied, "cannot open trusted bootstrap"):
            self.load_trusted_manifest()

    def test_bootstrap_directory_and_file_symlinks_are_rejected(self):
        path = self.base / "bootstrap-symlink-dd"
        data = self.static_elf_fixture()
        path.write_bytes(data)
        path.chmod(0o755)
        self.trusted_manifest(path, data)

        alias = self.base / "bootstrap-alias"
        alias.symlink_to(self.trust_root, target_is_directory=True)
        with mock.patch.object(policy_module, "_TRUSTED_DD_BOOTSTRAP_DIR", alias), \
                mock.patch.object(policy_module, "_TRUSTED_DD_PUBLIC_KEY_PATH",
                                  self.trust_public_key_path), \
                mock.patch.object(policy_module, "RecallDDFileOps", RootOwnedBootstrapTestOps):
            with self.assertRaisesRegex(DDPolicyDenied, "cannot inspect trusted bootstrap path"):
                TrustedGNUCoreutilsDD.from_trusted_bootstrap()

        manifest = self.trust_root / "manifest.json"
        saved_manifest = self.base / "manifest.saved"
        manifest.rename(saved_manifest)
        manifest.symlink_to(saved_manifest)
        with self.assertRaisesRegex(DDPolicyDenied, "cannot open trusted bootstrap manifest"):
            self.load_trusted_manifest()
        manifest.unlink()
        saved_manifest.rename(manifest)

        real_key = self.base / "real-trust-key.pem"
        shutil.copyfile(self.trust_public_key_path, real_key)
        self.trust_public_key_path.unlink()
        self.trust_public_key_path.symlink_to(real_key)
        with self.assertRaisesRegex(DDPolicyDenied, "cannot open trusted bootstrap"):
            self.load_trusted_manifest()

    def test_signed_digest_mismatch_and_unknown_candidate_are_rejected(self):
        path = self.base / "manifest-mismatch-dd"
        trusted_bytes = self.static_elf_fixture()
        candidate_bytes = trusted_bytes[:-1] + bytes([trusted_bytes[-1] ^ 1])
        path.write_bytes(candidate_bytes)
        path.chmod(0o755)
        trusted = self.trusted_manifest(path, trusted_bytes)
        mapper_fd, ops, _identity, lease, owner = self.block_fixture(path)
        with self.assertRaisesRegex(DDPolicyDenied, "does not match trusted SHA-256"):
            RecallDDLaunchGate(
                self.root, self.name, mapper_fd=mapper_fd,
                executable_path=path, trusted_executable=trusted,
                mapper_lifecycle_lease=lease, mapper_owner=owner, ops=ops,
            )

        # A canonical path does not make the candidate a trusted GNU build.
        with self.assertRaisesRegex(DDPolicyDenied, "signed GNU coreutils trust manifest"):
            RecallDDLaunchGate(
                self.root, self.name, mapper_fd=mapper_fd,
                executable_path=Path("/usr/bin/dd"), mapper_lifecycle_lease=lease,
                ops=ops,
            )

    def test_trusted_static_manifest_uses_sealed_snapshot_and_checks_mapper_lease(self):
        executable_path = self.base / "trusted-static-dd"
        expected_bytes = self.static_elf_fixture()
        executable_path.write_bytes(expected_bytes)
        executable_path.chmod(0o755)
        trusted = self.trusted_manifest(executable_path, expected_bytes)
        mapper_fd, ops, _identity, lease, owner = self.block_fixture(executable_path)
        gate = RecallDDLaunchGate(
            self.root, self.name, mapper_fd=mapper_fd,
            executable_path=executable_path, trusted_executable=trusted,
            mapper_lifecycle_lease=lease, mapper_owner=owner, ops=ops,
        )
        self.addCleanup(gate.close)
        launch = gate.admit("writer")
        snapshot_fd = launch.executable_fd
        self.assertTrue(launch.executable.endswith(f"/fd/{snapshot_fd}"))
        self.assertFalse(os.get_inheritable(snapshot_fd))
        self.assertEqual(hashlib.sha256(os.pread(snapshot_fd, len(expected_bytes), 0)).hexdigest(),
                         trusted.sha256)
        with self.assertRaises(OSError):
            os.pwrite(snapshot_fd, b"tamper", 0)
        with self.assertRaises(OSError):
            os.fchmod(snapshot_fd, 0o600)
        self.assertEqual(gate.admit("a").executable_fd, snapshot_fd)

    def test_mapper_identity_change_denies_future_roles(self):
        executable_path = self.base / "trusted-static-dd-change"
        contents = self.static_elf_fixture()
        executable_path.write_bytes(contents)
        executable_path.chmod(0o755)
        trusted = self.trusted_manifest(executable_path, contents)
        expected = MapperIdentity(self.name, "SWAPZ-TEST-IDENTITY", 253, 17, "b" * 64)
        changed = MapperIdentity(self.name, "SWAPZ-TEST-IDENTITY", 253, 17, "c" * 64)
        observations = iter((expected, expected, expected, changed))
        mapper_fd, ops, _identity, lease, owner = self.block_fixture(
            executable_path, identity_reader=lambda *_: next(observations),
        )
        gate = RecallDDLaunchGate(
            self.root, self.name, mapper_fd=mapper_fd,
            executable_path=executable_path, trusted_executable=trusted,
            mapper_lifecycle_lease=lease, mapper_owner=owner, ops=ops,
        )
        self.addCleanup(gate.close)
        gate.admit("writer")
        with self.assertRaisesRegex(DDPolicyDenied, "table fingerprint changed"):
            gate.admit("a")
        with self.assertRaises(DDPolicyDenied):
            gate.admit("b")

    def test_mapper_kernel_name_uuid_and_dev_mismatches_deny_admission(self):
        for attribute, wrong in (("name", "swapz-v22-recall-other"),
                                  ("uuid", "SWAPZ-OTHER"),
                                  ("dev", "253:18")):
            with self.subTest(attribute=attribute):
                executable = self.base / ("mismatch-dd-" + attribute)
                data = self.static_elf_fixture()
                executable.write_bytes(data)
                executable.chmod(0o755)
                trusted = self.trusted_manifest(executable, data)
                mapper_fd, ops, _identity, lease, owner = self.block_fixture(executable)
                original = ops.read_dm_sysfs_attr
                ops.read_dm_sysfs_attr = lambda major, minor, key, orig=original, attr=attribute, value=wrong: (
                    value if key == attr else orig(major, minor, key)
                )
                with self.assertRaises(DDPolicyDenied):
                    RecallDDLaunchGate(
                        self.root, self.name, mapper_fd=mapper_fd,
                        executable_path=executable, trusted_executable=trusted,
                        mapper_lifecycle_lease=lease, mapper_owner=owner, ops=ops,
                    )

    def test_mapper_major_minor_mismatch_denies_before_executable_open(self):
        executable = self.base / "device-mismatch-dd"
        data = self.static_elf_fixture()
        executable.write_bytes(data)
        executable.chmod(0o755)
        trusted = self.trusted_manifest(executable, data)
        mapper_fd, ops, _identity, lease, owner = self.block_fixture(executable)
        original_fstat = ops.fstat

        def changed_major_minor(fd):
            info = original_fstat(fd)
            if fd in ops.block_fds:
                return SimpleNamespace(
                    st_mode=info.st_mode, st_rdev=os.makedev(254, 17),
                    st_uid=info.st_uid, st_dev=info.st_dev, st_ino=info.st_ino,
                    st_size=info.st_size, st_mtime_ns=info.st_mtime_ns,
                    st_ctime_ns=info.st_ctime_ns, st_nlink=info.st_nlink,
                )
            return info

        ops.fstat = changed_major_minor
        with self.assertRaisesRegex(DDPolicyDenied, "exact DM object"):
            RecallDDLaunchGate(
                self.root, self.name, mapper_fd=mapper_fd,
                executable_path=executable, trusted_executable=trusted,
                mapper_lifecycle_lease=lease, mapper_owner=owner, ops=ops,
            )

    def test_missing_owner_and_mapper_lease_fail_closed(self):
        path = self.base / "owner-dd"
        data = self.static_elf_fixture()
        path.write_bytes(data)
        path.chmod(0o755)
        mapper_fd, ops, expected, lease, owner = self.block_fixture(path)
        unlocked_path = self.base / "unlocked-owner-lock"
        unlocked_path.touch(mode=0o600)
        unlocked_path.chmod(0o600)
        unlocked_fd = os.open(unlocked_path, os.O_RDWR | os.O_CLOEXEC)
        try:
            with self.assertRaisesRegex(DDPolicyDenied, "does not hold"):
                MapperLifecycleLease(
                    unlocked_fd, unlocked_path, expected, lambda *_: expected, ops=ops,
                )
        finally:
            os.close(unlocked_fd)
        with self.assertRaisesRegex(DDPolicyDenied, "exclusive lifecycle lease"):
            RecallDDLaunchGate(
                self.root, self.name, mapper_fd=mapper_fd,
                executable_path=path, trusted_executable=self.trusted_manifest(path, data),
                ops=ops,
            )

    def test_mapper_owner_releases_only_after_exact_remove_and_absence(self):
        path = self.base / "owner-lifecycle-dd"
        data = self.static_elf_fixture()
        path.write_bytes(data)
        path.chmod(0o755)
        mapper_fd, _file_ops, identity, lease, owner = self.block_fixture(path)
        operations = owner.operations
        self.assertEqual(owner.state, MapperLifecycleOwner.ACTIVE)
        self.assertFalse(owner.cleanup_allowed)

        owner.close_admission()
        self.assertEqual(owner.state, MapperLifecycleOwner.ADMISSION_CLOSED)
        owner.finalize_teardown(workers_reaped=True, descriptors_closed=True)

        self.assertEqual(owner.state, MapperLifecycleOwner.RELEASED)
        self.assertTrue(owner.cleanup_allowed)
        self.assertFalse(owner.preserve_backing)
        self.assertIsNone(owner.mapper_fd)
        self.assertTrue(lease._closed)
        self.assertEqual(operations.entries, ())
        remove_index = operations.events.index("remove")
        self.assertEqual(operations.events[remove_index + 1:], ["inventory"])
        self.assertEqual(identity, owner.identity)
        self.assertIsInstance(mapper_fd, int)

    def test_mapper_owner_missing_worker_or_descriptor_evidence_permanently_denies(self):
        path = self.base / "owner-incomplete-shutdown-dd"
        data = self.static_elf_fixture()
        path.write_bytes(data)
        path.chmod(0o755)
        _mapper_fd, _file_ops, _identity, _lease, owner = self.block_fixture(path)
        operations = owner.operations
        owner.close_admission()
        with self.assertRaisesRegex(MapperOwnerDenied, "not positively quiesced"):
            owner.finalize_teardown(workers_reaped=False, descriptors_closed=True)
        self.assertEqual(owner.state, MapperLifecycleOwner.DENIED)
        self.assertFalse(owner.cleanup_allowed)
        self.assertTrue(owner.preserve_backing)
        self.assertNotIn("remove", operations.events)

    def test_mapper_owner_rejects_duplicate_or_out_of_order_lifecycle_calls(self):
        path = self.base / "owner-duplicate-operation-dd"
        path.write_bytes(b"owner policy fixture")
        _mapper_fd, _file_ops, _identity, _lease, owner = self.block_fixture(path)
        operations = owner.operations
        create_count = operations.events.count("create")
        with self.assertRaisesRegex(MapperOwnerDenied, "invalid in state active"):
            owner.create()
        self.assertEqual(operations.events.count("create"), create_count)
        self.assertTrue(owner.preserve_backing)

    def test_failed_mapping_removal_preserves_backing_and_denies_cleanup(self):
        path = self.base / "owner-remove-failure-dd"
        path.write_bytes(b"owner policy fixture")
        _mapper_fd, _file_ops, _identity, _lease, owner = self.block_fixture(path)
        operations = owner.operations
        operations.remove_result = False
        owner.close_admission()
        with self.assertRaisesRegex(MapperOwnerDenied, "not confirmed"):
            owner.finalize_teardown(workers_reaped=True, descriptors_closed=True)
        self.assertEqual(owner.state, MapperLifecycleOwner.DENIED)
        self.assertTrue(owner.preserve_backing)
        self.assertFalse(owner.cleanup_allowed)
        self.assertEqual(operations.entries, (owner.identity,))

    def test_mapper_owner_rejects_bad_inventory_and_owner_loss(self):
        for failure_kind in ("invalid", "duplicate", "owner-lost-during-inventory",
                             "owner-inspection-error"):
            with self.subTest(failure_kind=failure_kind):
                path = self.base / ("owner-inventory-" + failure_kind)
                data = self.static_elf_fixture()
                path.write_bytes(data)
                path.chmod(0o755)
                _mapper_fd, _file_ops, identity, _lease, owner = self.block_fixture(path)
                operations = owner.operations
                if failure_kind == "invalid":
                    operations.inventory_valid = False
                elif failure_kind == "duplicate":
                    operations.entries = (identity, identity)
                elif failure_kind == "owner-lost-during-inventory":
                    operations.after_inventory = lambda: setattr(operations, "alive", False)
                else:
                    operations.owner_alive = lambda: (_ for _ in ()).throw(
                        OSError("injected owner status EIO"),
                    )
                with self.assertRaises(MapperOwnerDenied):
                    owner.verify_role(owner.mapper_fd)
                self.assertEqual(owner.state, MapperLifecycleOwner.DENIED)
                self.assertFalse(owner.cleanup_allowed)
                self.assertNotIn("remove", operations.events)

    def test_mapper_owner_rejects_replaced_lock_and_table_identity_change(self):
        path = self.base / "owner-replacement-dd"
        data = self.static_elf_fixture()
        path.write_bytes(data)
        path.chmod(0o755)
        mapper_fd, _file_ops, identity, lease, owner = self.block_fixture(path)
        lock_path = lease._lock_path
        lock_path.unlink()
        lock_path.touch(mode=0o600)
        lock_path.chmod(0o600)
        with self.assertRaisesRegex(MapperOwnerDenied, "lock identity changed"):
            owner.verify_role(mapper_fd)
        self.assertTrue(owner.preserve_backing)

        changed_path = self.base / "owner-table-change-dd"
        changed_path.write_bytes(data)
        changed_path.chmod(0o755)
        changed = MapperIdentity(identity.name, identity.uuid, identity.major,
                                 identity.minor, "c" * 64)
        observations = iter((identity, changed))
        changed_fd, _changed_ops, _identity, _changed_lease, changed_owner = self.block_fixture(
            changed_path, identity_reader=lambda *_: next(observations),
        )
        with self.assertRaisesRegex(MapperOwnerDenied, "table fingerprint changed"):
            changed_owner.verify_role(changed_fd)
        self.assertFalse(changed_owner.cleanup_allowed)

    def test_mapper_owner_rejects_name_uuid_and_device_inventory_changes(self):
        for changed_identity in ("name", "uuid", "device"):
            with self.subTest(changed_identity=changed_identity):
                path = self.base / ("owner-inventory-change-" + changed_identity)
                data = self.static_elf_fixture()
                path.write_bytes(data)
                path.chmod(0o755)
                _mapper_fd, _file_ops, identity, _lease, owner = self.block_fixture(path)
                if changed_identity == "name":
                    replacement = MapperIdentity(
                        "swapz-v22-recall-other", identity.uuid, identity.major,
                        identity.minor, identity.table_sha256,
                    )
                elif changed_identity == "uuid":
                    replacement = MapperIdentity(
                        identity.name, "SWAPZ-OTHER-UUID", identity.major,
                        identity.minor, identity.table_sha256,
                    )
                else:
                    replacement = MapperIdentity(
                        identity.name, identity.uuid, identity.major + 1,
                        identity.minor, identity.table_sha256,
                    )
                owner.operations.entries = (replacement,)
                with self.assertRaises(MapperOwnerDenied):
                    owner.verify_role(owner.mapper_fd)
                self.assertTrue(owner.preserve_backing)

    def test_mapper_owner_rejects_incomplete_operations_interface(self):
        path = self.base / "owner-incomplete-operations-dd"
        path.write_bytes(b"owner policy fixture")
        mapper_fd, _file_ops, identity, lease, _owner = self.block_fixture(path)

        class IncompleteOwnerOperations:
            def owner_alive(self):
                return True

            def inventory(self):
                return MapperInventory(True, ())

            def create_mapping(self, _identity):
                return mapper_fd

        with self.assertRaisesRegex(MapperOwnerDenied, "remove_mapping is unavailable"):
            MapperLifecycleOwner(identity, lease, IncompleteOwnerOperations())

    def test_mapper_owner_descriptor_close_failure_denies_removal(self):
        path = self.base / "owner-close-failure-dd"
        data = self.static_elf_fixture()
        path.write_bytes(data)
        path.chmod(0o755)
        _mapper_fd, file_ops, _identity, _lease, owner = self.block_fixture(path)
        owner.close_admission()
        original_close = file_ops.close
        mapper_fd = owner.mapper_fd

        def fail_mapper_close(fd):
            if fd == mapper_fd:
                raise OSError("injected mapper descriptor close failure")
            original_close(fd)

        file_ops.close = fail_mapper_close
        with self.assertRaisesRegex(MapperOwnerDenied, "descriptor close failed"):
            owner.finalize_teardown(workers_reaped=True, descriptors_closed=True)
        self.assertFalse(owner.cleanup_allowed)
        self.assertNotIn("remove", owner.operations.events)

    def test_concurrent_mapper_owner_operation_sticks_denial(self):
        path = self.base / "owner-concurrent-dd"
        data = self.static_elf_fixture()
        path.write_bytes(data)
        path.chmod(0o755)
        mapper_fd, _file_ops, _identity, _lease, owner = self.block_fixture(path)
        entered = threading.Event()
        release = threading.Event()
        errors = []

        def blocked_owner_check():
            entered.set()
            return release.wait(2) is True

        owner.operations.owner_alive = blocked_owner_check

        def first_operation():
            try:
                owner.verify_role(mapper_fd)
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=first_operation)
        worker.start()
        self.assertTrue(entered.wait(1), "first owner operation did not enter its gate")
        with self.assertRaisesRegex(MapperOwnerDenied, "concurrent"):
            owner.verify_role(mapper_fd)
        release.set()
        worker.join(2)
        self.assertFalse(worker.is_alive(), "mapper-owner test thread failed to stop")
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], MapperOwnerDenied)
        self.assertFalse(owner.cleanup_allowed)

    def test_static_elf_architecture_mismatch_is_rejected(self):
        path = self.base / "wrong-machine-dd"
        data = bytearray(self.static_elf_fixture())
        data[18:20] = (3).to_bytes(2, "little")
        path.write_bytes(data)
        path.chmod(0o755)
        trusted = self.trusted_manifest(path, bytes(data))
        mapper_fd, ops, _identity, lease, owner = self.block_fixture(path)
        with self.assertRaisesRegex(DDPolicyDenied, "architecture is unsupported"):
            RecallDDLaunchGate(
                self.root, self.name, mapper_fd=mapper_fd,
                executable_path=path, trusted_executable=trusted,
                mapper_lifecycle_lease=lease, mapper_owner=owner, ops=ops,
            )

    def test_dynamic_interpreter_is_not_admitted_for_mapper_io(self):
        for program_type in (3, 2):  # PT_INTERP and PT_DYNAMIC
            with self.subTest(program_type=program_type):
                executable_path = self.base / f"dynamic-dd-{program_type}"
                dynamic = bytearray(self.static_elf_fixture())
                dynamic[32:40] = (64).to_bytes(8, "little")
                dynamic[54:56] = (56).to_bytes(2, "little")
                dynamic[56:58] = (1).to_bytes(2, "little")
                dynamic.extend(program_type.to_bytes(4, "little") + bytes(52))
                executable_path.write_bytes(dynamic)
                executable_path.chmod(0o755)
                trusted = self.trusted_manifest(executable_path, bytes(dynamic))
                mapper_fd, ops, _identity, lease, owner = self.block_fixture(executable_path)
                with self.assertRaisesRegex(DDPolicyDenied, "dynamic dd"):
                    RecallDDLaunchGate(
                        self.root, self.name, mapper_fd=mapper_fd,
                        executable_path=executable_path, trusted_executable=trusted,
                        mapper_lifecycle_lease=lease, mapper_owner=owner, ops=ops,
                    )

    def test_missing_executable_memfd_support_denies_mapper_launch(self):
        executable_path = self.base / "memfd-unavailable-dd"
        data = self.static_elf_fixture()
        executable_path.write_bytes(data)
        executable_path.chmod(0o755)
        trusted = self.trusted_manifest(executable_path, data)
        mapper_fd, ops, _identity, lease, owner = self.block_fixture(
            executable_path, fail_snapshot=True,
        )
        with self.assertRaisesRegex(DDPolicyDenied, "cannot bind direct dd"):
            RecallDDLaunchGate(
                self.root, self.name, mapper_fd=mapper_fd,
                executable_path=executable_path, trusted_executable=trusted,
                mapper_lifecycle_lease=lease, mapper_owner=owner, ops=ops,
            )

    def test_memfd_seal_verification_failure_denies_mapper_launch(self):
        executable = self.base / "seal-verification-dd"
        data = self.static_elf_fixture()
        executable.write_bytes(data)
        executable.chmod(0o755)
        trusted = self.trusted_manifest(executable, data)
        mapper_fd, ops, _identity, lease, owner = self.block_fixture(executable)
        original_fcntl = policy_module.fcntl.fcntl
        get_seals = getattr(policy_module.fcntl, "F_GET_SEALS", 1034)

        def fail_seal_verify(fd, command, *args):
            if command == get_seals:
                return 0
            return original_fcntl(fd, command, *args)

        with mock.patch.object(policy_module.fcntl, "fcntl", side_effect=fail_seal_verify):
            with self.assertRaisesRegex(DDPolicyDenied, "cannot bind direct dd"):
                RecallDDLaunchGate(
                    self.root, self.name, mapper_fd=mapper_fd,
                    executable_path=executable, trusted_executable=trusted,
                    mapper_lifecycle_lease=lease, mapper_owner=owner, ops=ops,
                )

    def test_mapper_sysfs_inspection_failure_is_sticky_denial(self):
        executable = self.base / "sysfs-failure-dd"
        data = self.static_elf_fixture()
        executable.write_bytes(data)
        executable.chmod(0o755)
        trusted = self.trusted_manifest(executable, data)
        mapper_fd, ops, _identity, lease, owner = self.block_fixture(executable)
        ops.read_dm_sysfs_attr = lambda *_: (_ for _ in ()).throw(OSError("injected sysfs EIO"))
        with self.assertRaisesRegex(DDPolicyDenied, "cannot verify DM identity"):
            RecallDDLaunchGate(
                self.root, self.name, mapper_fd=mapper_fd,
                executable_path=executable, trusted_executable=trusted,
                mapper_lifecycle_lease=lease, mapper_owner=owner, ops=ops,
            )

    def test_released_fixture_lifecycle_lock_denies_future_role(self):
        executable = self.base / "released-lock-dd"
        data = self.static_elf_fixture()
        executable.write_bytes(data)
        executable.chmod(0o755)
        trusted = self.trusted_manifest(executable, data)
        mapper_fd, ops, _identity, lease, owner = self.block_fixture(executable)
        gate = RecallDDLaunchGate(
            self.root, self.name, mapper_fd=mapper_fd,
            executable_path=executable, trusted_executable=trusted,
            mapper_lifecycle_lease=lease, mapper_owner=owner, ops=ops,
        )
        self.addCleanup(gate.close)
        lease.close()
        with self.assertRaises(DDPolicyDenied):
            gate.admit("writer")
        self.assertTrue(gate._closed)

    def test_invalid_executable_identity_and_descriptor_acquisition_fail_closed(self):
        bad_exe = self.base / "not-elf-dd"
        bad_exe.write_bytes(b"#!/bin/sh\nexit 0\n")
        bad_exe.chmod(0o755)
        with self.assertRaisesRegex(DDPolicyDenied, "trusted ELF"):
            self.make_gate(executable=bad_exe)

        class FailingOps(RecallDDFileOps):
            def open(self, path, flags, mode=0o777, *, dir_fd=None):
                if path == "pages.bin":
                    raise OSError("injected source fd acquisition failure")
                return super().open(path, flags, mode, dir_fd=dir_fd)

        with self.assertRaisesRegex(DDPolicyDenied, "cannot bind direct dd"):
            self.make_gate(ops=FailingOps())

        wrapper = self.base / "signed-shell-wrapper-dd"
        wrapper_bytes = b"#!/bin/sh\nexec /bin/busybox dd \"$@\"\n"
        wrapper.write_bytes(wrapper_bytes)
        wrapper.chmod(0o755)
        trusted = self.trusted_manifest(wrapper, wrapper_bytes)
        mapper_fd, block_ops, _identity, lease, owner = self.block_fixture(wrapper)
        with self.assertRaisesRegex(DDPolicyDenied, "trusted ELF"):
            RecallDDLaunchGate(
                self.root, self.name, mapper_fd=mapper_fd,
                executable_path=wrapper, trusted_executable=trusted,
                mapper_lifecycle_lease=lease, mapper_owner=owner, ops=block_ops,
            )

    def test_executable_path_replacement_cannot_change_pinned_executable(self):
        pinned_path = self.base / "trusted-dd"
        shutil.copyfile(sys.executable, pinned_path)
        pinned_path.chmod(0o700)
        gate = self.make_gate(executable=pinned_path)
        executable_fd = gate._executable_fd
        identity = (os.fstat(executable_fd).st_dev, os.fstat(executable_fd).st_ino)
        moved = self.base / "trusted-dd-original"
        pinned_path.replace(moved)
        pinned_path.write_text("#!/bin/sh\nexit 1\n")
        pinned_path.chmod(0o755)
        launch = gate.admit("writer")
        self.assertEqual(launch.executable, f"/proc/self/fd/{executable_fd}")
        self.assertEqual((os.fstat(executable_fd).st_dev, os.fstat(executable_fd).st_ino), identity)
        self.assertEqual(os.pread(executable_fd, 4, 0), b"\x7fELF")

    def test_signed_mapper_launch_denies_executable_replacement_and_in_place_mutation(self):
        for mutation in ("replace", "in-place"):
            with self.subTest(mutation=mutation):
                executable = self.base / ("trusted-" + mutation)
                contents = self.static_elf_fixture()
                executable.write_bytes(contents)
                executable.chmod(0o755)
                trusted = self.trusted_manifest(executable, contents)
                mapper_fd, ops, _identity, lease, owner = self.block_fixture(executable)
                gate = RecallDDLaunchGate(
                    self.root, self.name, mapper_fd=mapper_fd,
                    executable_path=executable, trusted_executable=trusted,
                    mapper_lifecycle_lease=lease, mapper_owner=owner, ops=ops,
                )
                self.addCleanup(gate.close)
                gate.admit("writer")
                if mutation == "replace":
                    executable.rename(self.base / ("original-" + mutation))
                    executable.write_bytes(contents)
                    executable.chmod(0o755)
                else:
                    mutable_fd = os.open(executable, os.O_WRONLY | os.O_CLOEXEC)
                    try:
                        os.pwrite(mutable_fd, b"changed", 0)
                    finally:
                        os.close(mutable_fd)
                with self.assertRaises(DDPolicyDenied):
                    gate.admit("a")
                self.assertTrue(gate._closed)

    def test_setid_and_file_capabilities_are_rejected(self):
        for mode in (0o4755, 0o2755):
            with self.subTest(setid_mode=oct(mode)):
                setid = self.base / ("setid-dd-" + oct(mode))
                setid.write_bytes(b"\x7fELF" + bytes(60))
                setid.chmod(mode)
                with self.assertRaisesRegex(DDPolicyDenied, "trusted ELF"):
                    self.make_gate(executable=setid)

        executable = self.base / "capability-dd"
        shutil.copyfile(sys.executable, executable)
        executable.chmod(0o755)

        class CapabilityOps(RecallDDFileOps):
            def getxattr(self, fd, name):
                if name == "security.capability":
                    return b"injected-capability"
                return super().getxattr(fd, name)

        with self.assertRaisesRegex(DDPolicyDenied, "file capabilities"):
            self.make_gate(executable=executable, ops=CapabilityOps())

    def test_capability_inspection_failure_is_not_treated_as_absence(self):
        executable = self.base / "uninspectable-capability-dd"
        shutil.copyfile(sys.executable, executable)
        executable.chmod(0o755)

        class CapabilityInspectionFailure(RecallDDFileOps):
            def getxattr(self, fd, name):
                raise PermissionError("injected xattr read denial")

        with self.assertRaisesRegex(DDPolicyDenied, "cannot inspect dd file capabilities"):
            self.make_gate(executable=executable, ops=CapabilityInspectionFailure())

    def test_mapper_lease_rejects_invalid_and_changed_identity(self):
        expected = MapperIdentity(self.name, "SWAPZ-TEST-IDENTITY", 253, 17, "b" * 64)
        with self.assertRaisesRegex(DDPolicyDenied, "malformed"):
            MapperIdentity(self.name, "", 253, 17, "b" * 64)
        lock_path = self.base / "untrusted-owner-lock"
        lock_path.touch(mode=0o600)
        lock_path.chmod(0o600)
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CLOEXEC)
        try:
            with self.assertRaisesRegex(DDPolicyDenied, "does not hold"):
                MapperLifecycleLease(
                    lock_fd, lock_path, expected, lambda *_: expected,
                    ops=RecallDDFileOps(),
                )
        finally:
            os.close(lock_fd)

    def test_mapper_open_requires_explicit_trusted_lifecycle_binding(self):
        class NoOpenOps(RecallDDFileOps):
            opened = False
            def open(self, path, flags, mode=0o777, *, dir_fd=None):
                self.opened = True
                raise AssertionError("device open must not happen without trust binding")

        ops = NoOpenOps()
        with self.assertRaisesRegex(DDPolicyDenied, "lifecycle identity"):
            policy_module.open_test_mapper_fd(self.name, ops=ops)
        self.assertFalse(ops.opened)

    def test_mapper_open_checks_name_uuid_device_and_table_with_fake_sysfs(self):
        executable = self.base / "unused-dd"
        mapper_path = self.base / "fake-device-node"
        mapper_path.write_bytes(b"synthetic block node")
        mapper_fd = os.open(mapper_path, os.O_RDONLY | os.O_CLOEXEC)
        expected = MapperIdentity(self.name, "SWAPZ-TEST-IDENTITY", 253, 17, "b" * 64)

        class FakeMapperOps(RecallDDFileOps):
            def fstat(self, fd):
                if fd in (mapper_fd, self.opened_fd):
                    info = os.fstat(mapper_fd)
                    return SimpleNamespace(
                        st_mode=stat.S_IFBLK | 0o600, st_rdev=os.makedev(253, 17),
                        st_uid=os.geteuid(), st_dev=info.st_dev, st_ino=info.st_ino,
                        st_size=info.st_size, st_mtime_ns=info.st_mtime_ns,
                        st_ctime_ns=info.st_ctime_ns, st_nlink=info.st_nlink,
                    )
                return super().fstat(fd)

            def open(self, path, flags, mode=0o777, *, dir_fd=None):
                if path == f"/dev/mapper/{self_name}":
                    self.opened_fd = os.dup(mapper_fd)
                    os.set_inheritable(self.opened_fd, False)
                    return self.opened_fd
                return super().open(path, flags, mode, dir_fd=dir_fd)

            def read_dm_sysfs_attr(self, major, minor, attribute):
                return {"name": self_name, "uuid": expected.uuid,
                        "dev": f"{major}:{minor}"}[attribute]

        self_name = self.name
        ops = FakeMapperOps()
        ops.opened_fd = -1
        lock_path = self.base / "fake-open-lifecycle.lock"
        lock_path.touch(mode=0o600)
        lock_path.chmod(0o600)
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CLOEXEC)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lease = MapperLifecycleLease(
            lock_fd, lock_path, expected, lambda *_: expected, ops=ops,
        )
        os.close(lock_fd)
        try:
            result_fd = policy_module.open_test_mapper_fd(
                self.name, lifecycle_lease=lease, ops=ops,
            )
            self.assertEqual(result_fd, ops.opened_fd)
            os.close(result_fd)
            lease.close()
        finally:
            if ops.opened_fd >= 0:
                try:
                    os.close(ops.opened_fd)
                except OSError:
                    pass
            os.close(mapper_fd)

    def test_close_failure_is_reported_once_and_denies_followup(self):
        class CloseFailOps(RecallDDFileOps):
            def __init__(self):
                self.fail_fd = None
                self.attempts = []
            def close(self, fd):
                self.attempts.append(fd)
                if fd == self.fail_fd:
                    raise OSError("injected close failure")
                return super().close(fd)

        ops = CloseFailOps()
        gate = self.make_gate(ops=ops)
        ops.fail_fd = gate._source_fd
        errors = gate.close()
        self.assertEqual(len(errors), 1)
        self.assertIn("injected close failure", errors[0])
        attempts = list(ops.attempts)
        self.assertEqual(gate.close(), errors)
        self.assertEqual(ops.attempts, attempts)
        with self.assertRaisesRegex(DDPolicyDenied, "closed"):
            gate.admit("writer")
        # The fake close failure intentionally leaves the descriptor open;
        # close it directly as test-fixture cleanup after the assertion.
        os.close(ops.fail_fd)


if __name__ == "__main__":
    unittest.main()
