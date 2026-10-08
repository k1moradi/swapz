#!/usr/bin/env python3
"""Offline safety tests for proposed fixture-bound direct dd worker allowlist."""

from __future__ import annotations

import ast
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
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


if __name__ == "__main__":
    unittest.main()
