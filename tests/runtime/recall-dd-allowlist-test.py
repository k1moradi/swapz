#!/usr/bin/env python3
"""Offline safety tests for proposed fixture-bound direct dd worker allowlist."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest


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
plan_module = load("recall_io_plan_allowlist_contract", HERE / "recall-io-plan.py")


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
        banned = {"kill", "fork", "Popen", "run", "system", "execv",
                  "execve", "posix_spawn", "ioctl", "swapon", "swapoff"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                self.assertNotIn(name, banned)
        self.assertFalse(hasattr(self.policy, "launch"))
        self.assertFalse(hasattr(self.policy, "stop_all"))


class PinnedDDLaunchGateTests(unittest.TestCase):
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

    def test_block_mapper_requires_trusted_root_owned_executable_digest(self):
        mapper_path = self.base / "synthetic-block-mapper"
        mapper_path.write_bytes(b"synthetic block descriptor")
        mapper_fd = os.open(mapper_path, os.O_RDONLY | os.O_CLOEXEC)

        class BlockDescriptorOps(RecallDDFileOps):
            def __init__(self):
                self.block_fds = {mapper_fd}

            def dup_cloexec(self, fd):
                duplicate = super().dup_cloexec(fd)
                self.block_fds.add(duplicate)
                return duplicate

            def fstat(self, fd):
                if fd in self.block_fds:
                    return SimpleNamespace(
                        st_mode=stat.S_IFBLK | 0o600,
                        st_rdev=os.makedev(253, 17),
                        st_uid=0,
                    )
                return super().fstat(fd)

        ops = BlockDescriptorOps()
        try:
            with self.assertRaisesRegex(DDPolicyDenied, "independently trusted"):
                RecallDDLaunchGate(
                    self.root, self.name, mapper_fd=mapper_fd,
                    executable_path=Path("/usr/bin/dd"), ops=ops,
                    mapper_verifier=lambda *_: True,
                )

            digest = hashlib.sha256(Path("/usr/bin/dd").read_bytes()).hexdigest()
            with self.assertRaisesRegex(DDPolicyDenied, "trusted SHA-256"):
                RecallDDLaunchGate(
                    self.root, self.name, mapper_fd=mapper_fd,
                    executable_path=Path("/usr/bin/dd"),
                    expected_executable_sha256="0" * 64, ops=ops,
                    mapper_verifier=lambda *_: True,
                )

            gate = RecallDDLaunchGate(
                self.root, self.name, mapper_fd=mapper_fd,
                executable_path=Path("/usr/bin/dd"),
                expected_executable_sha256=digest, ops=ops,
                mapper_verifier=lambda *_: True,
            )
            self.addCleanup(gate.close)
            self.assertEqual(gate.admit("writer").role, "writer")
        finally:
            os.close(mapper_fd)

    def test_block_mapper_launch_uses_immutable_digest_verified_snapshot(self):
        executable_path = self.base / "trusted-executable-copy"
        executable_path.write_bytes(Path(sys.executable).read_bytes())
        executable_path.chmod(0o755)
        expected_bytes = executable_path.read_bytes()
        expected_digest = hashlib.sha256(expected_bytes).hexdigest()
        mapper_path = self.base / "synthetic-block-mapper-snapshot"
        mapper_path.write_bytes(b"synthetic block descriptor")
        mapper_fd = os.open(mapper_path, os.O_RDONLY | os.O_CLOEXEC)

        class BlockDescriptorOps(RecallDDFileOps):
            def __init__(self):
                self.block_fds = {mapper_fd}
                self.root_owned_executable_fds = set()

            def open(self, path, flags, mode=0o777, *, dir_fd=None):
                fd = super().open(path, flags, mode, dir_fd=dir_fd)
                if path == str(executable_path):
                    self.root_owned_executable_fds.add(fd)
                return fd

            def fstat(self, fd):
                if fd in self.block_fds:
                    return SimpleNamespace(
                        st_mode=stat.S_IFBLK | 0o600,
                        st_rdev=os.makedev(253, 18),
                        st_uid=0,
                    )
                info = super().fstat(fd)
                if fd in self.root_owned_executable_fds:
                    return SimpleNamespace(
                        st_mode=info.st_mode, st_uid=0, st_size=info.st_size,
                        st_dev=info.st_dev, st_ino=info.st_ino,
                        st_mtime_ns=info.st_mtime_ns, st_ctime_ns=info.st_ctime_ns,
                        st_nlink=info.st_nlink, st_gid=info.st_gid,
                    )
                return info

        ops = BlockDescriptorOps()
        try:
            gate = RecallDDLaunchGate(
                self.root, self.name, mapper_fd=mapper_fd,
                executable_path=executable_path,
                expected_executable_sha256=expected_digest,
                ops=ops, mapper_verifier=lambda *_: True,
            )
            self.addCleanup(gate.close)
            launch = gate.admit("writer")
            snapshot_fd = launch.executable_fd
            self.assertTrue(launch.executable.endswith(f"/fd/{snapshot_fd}"))
            self.assertFalse(os.get_inheritable(snapshot_fd))
            self.assertEqual(hashlib.sha256(os.pread(snapshot_fd, len(expected_bytes), 0)).hexdigest(),
                             expected_digest)

            with self.assertRaises(OSError):
                os.pwrite(snapshot_fd, b"tamper", 0)
            with self.assertRaises(OSError):
                os.fchmod(snapshot_fd, 0o600)
            completed = subprocess.run(
                [launch.executable, "-c", "pass"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                pass_fds=(snapshot_fd,),
                timeout=3.0,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
            mutable_fd = os.open(executable_path, os.O_WRONLY | os.O_CLOEXEC)
            try:
                self.assertEqual(os.pwrite(mutable_fd, b"MUTATE", 0), 6)
            finally:
                os.close(mutable_fd)
            self.assertEqual(hashlib.sha256(os.pread(snapshot_fd, len(expected_bytes), 0)).hexdigest(),
                             expected_digest)
            self.assertEqual(gate.admit("a").executable_fd, snapshot_fd)
        finally:
            os.close(mapper_fd)

    def test_missing_executable_memfd_support_denies_block_mapper_launch(self):
        mapper_path = self.base / "synthetic-block-mapper-no-memfd"
        mapper_path.write_bytes(b"synthetic block descriptor")
        mapper_fd = os.open(mapper_path, os.O_RDONLY | os.O_CLOEXEC)
        executable_path = Path("/usr/bin/dd")

        class BlockDescriptorOps(RecallDDFileOps):
            def __init__(self):
                self.block_fds = {mapper_fd}
                self.root_owned_executable_fds = set()

            def open(self, path, flags, mode=0o777, *, dir_fd=None):
                fd = super().open(path, flags, mode, dir_fd=dir_fd)
                if path == str(executable_path):
                    self.root_owned_executable_fds.add(fd)
                return fd

            def fstat(self, fd):
                if fd in self.block_fds:
                    return SimpleNamespace(st_mode=stat.S_IFBLK | 0o600,
                                           st_rdev=os.makedev(253, 19), st_uid=0)
                info = super().fstat(fd)
                if fd in self.root_owned_executable_fds:
                    return SimpleNamespace(
                        st_mode=info.st_mode, st_uid=0, st_size=info.st_size,
                        st_dev=info.st_dev, st_ino=info.st_ino,
                        st_mtime_ns=info.st_mtime_ns, st_ctime_ns=info.st_ctime_ns,
                        st_nlink=info.st_nlink, st_gid=info.st_gid,
                    )
                return info

            def create_sealed_executable(self, source_fd, expected_sha256, maximum_size):
                raise OSError(38, "injected executable memfd unsupported")

        try:
            digest = hashlib.sha256(executable_path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(DDPolicyDenied, "cannot bind direct dd"):
                RecallDDLaunchGate(
                    self.root, self.name, mapper_fd=mapper_fd,
                    executable_path=executable_path,
                    expected_executable_sha256=digest,
                    ops=BlockDescriptorOps(), mapper_verifier=lambda *_: True,
                )
        finally:
            os.close(mapper_fd)

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
