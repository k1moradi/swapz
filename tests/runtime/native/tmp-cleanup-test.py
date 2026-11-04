#!/usr/bin/env python3
"""Rootless filesystem safety regressions for the private /tmp memory gate."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "tests/tools/cleanup-owned-tmp.py"
spec = importlib.util.spec_from_file_location("swapz_tmp_cleanup", HELPER)
cleanup_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = cleanup_module
spec.loader.exec_module(cleanup_module)


class OwnedTemporaryCleanupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="swapz-tmp-cleanup-fixture-")
        self.root = Path(self.directory.name)
        self.owner_uid = os.getuid()
        self.source_sha = "a" * 40
        self.record = f"pid=99999999\nsource_sha={self.source_sha}\n"

    def tearDown(self):
        self.directory.cleanup()

    def session(self, suffix, *, complete=True, identity=None):
        directory = self.root / f"swapz-benchmark.{suffix}"
        directory.mkdir(mode=0o700)
        (directory / ".swapz-benchmark-owner").write_text(self.record)
        (directory / ".swapz-benchmark-owner").chmod(0o600)
        if complete:
            (directory / ".swapz-benchmark-complete").write_text(
                self.record if identity is None else identity)
            (directory / ".swapz-benchmark-complete").chmod(0o600)
        (directory / "fixture.bin").write_bytes(b"owned payload")
        (directory / "fixture.bin").chmod(0o600)
        (directory / "plan").mkdir(mode=0o700)
        (directory / "plan" / "trace.jsonl").write_text("one\n")
        (directory / "plan" / "trace.jsonl").chmod(0o600)
        return directory

    def run_cleanup(self):
        return subprocess.run(
            [sys.executable, "-B", str(HELPER), str(self.root),
             str(self.owner_uid), "700"],
            capture_output=True, text=True, timeout=30)

    def test_only_completed_owned_sessions_are_removed_and_foreign_survives(self):
        foreign = self.root / "some-other-application-database"
        foreign.write_bytes(b"DO NOT DELETE")
        foreign_directory = self.root / "foreign-private-state"
        foreign_directory.mkdir()
        (foreign_directory / "important").write_bytes(b"data")
        owned = self.session("Abcd1234")
        incomplete = self.session("Bcde1234", complete=False)
        conflicting = self.session("Cdef1234", identity=self.record.replace("a" * 40, "b" * 40))
        unrelated_prefix = self.root / "swapz-id36.DeadBeef"
        unrelated_prefix.mkdir()
        (unrelated_prefix / "pressure.log").write_text("pressure evidence")
        symlink = self.root / "swapz-benchmark.DeadBeef"
        symlink.symlink_to(foreign_directory, target_is_directory=True)

        result = self.run_cleanup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("removed:1", result.stdout)
        self.assertFalse(owned.exists())
        self.assertTrue(incomplete.exists())
        self.assertTrue(conflicting.exists())
        self.assertEqual(foreign.read_bytes(), b"DO NOT DELETE")
        self.assertEqual((foreign_directory / "important").read_bytes(), b"data")
        self.assertTrue(symlink.is_symlink())
        self.assertTrue(unrelated_prefix.exists())
        self.assertIn("removed:0", self.run_cleanup().stdout)

    def test_symlink_inside_owned_session_blocks_before_deletion(self):
        owned = self.session("Abcd1234")
        foreign = self.root / "foreign"
        foreign.write_bytes(b"untouched")
        (owned / "link").symlink_to(foreign)
        result = self.run_cleanup()
        self.assertEqual(result.returncode, 2)
        self.assertIn("BLOCKED:", result.stderr)
        self.assertEqual(foreign.read_bytes(), b"untouched")
        self.assertTrue((owned / "fixture.bin").exists())

    def test_nested_mount_id_change_blocks_before_deletion(self):
        owned = self.session("Abcd1234")
        real_mount_id = cleanup_module.mount_id

        def pretend_bind_mount(descriptor):
            if os.fstat(descriptor).st_ino == (owned / "plan").stat().st_ino:
                return "999999999"
            return real_mount_id(descriptor)

        with mock.patch.object(cleanup_module, "mount_id", side_effect=pretend_bind_mount):
            with self.assertRaisesRegex(cleanup_module.CleanupBlocked, "nested mount"):
                cleanup_module.cleanup(str(self.root), self.owner_uid, 0o700)
        self.assertTrue((owned / "fixture.bin").exists())
        self.assertTrue((owned / "plan" / "trace.jsonl").exists())

    def test_inode_substitution_is_detected_before_unlink(self):
        owned = self.session("Abcd1234")
        victim = owned / "fixture.bin"
        foreign = self.root / "foreign"
        foreign.write_bytes(b"keep")
        original_verify = cleanup_module.verify_entry
        substituted = False

        def substitute(directory, entry, mount_id):
            nonlocal substituted
            if entry.name == "fixture.bin" and not substituted:
                substituted = True
                victim.unlink()
                victim.symlink_to(foreign)
            return original_verify(directory, entry, mount_id)

        with mock.patch.object(cleanup_module, "verify_entry", side_effect=substitute):
            with self.assertRaisesRegex(cleanup_module.CleanupBlocked, "replaced"):
                cleanup_module.cleanup(str(self.root), self.owner_uid, 0o700)
        self.assertEqual(foreign.read_bytes(), b"keep")
        self.assertTrue(victim.is_symlink())
        self.assertTrue((owned / ".swapz-benchmark-complete").exists())

    def test_interrupted_cleanup_keeps_proof_and_can_resume(self):
        owned = self.session("Abcd1234")
        original_verify = cleanup_module.verify_entry
        interrupted = False

        def interrupt_after_first_file(directory, entry, mount_id):
            nonlocal interrupted
            if entry.name == "plan" and not interrupted:
                interrupted = True
                raise KeyboardInterrupt()
            return original_verify(directory, entry, mount_id)

        with mock.patch.object(cleanup_module, "verify_entry", side_effect=interrupt_after_first_file):
            with self.assertRaises(KeyboardInterrupt):
                cleanup_module.cleanup(str(self.root), self.owner_uid, 0o700)
        self.assertTrue((owned / ".swapz-benchmark-owner").exists())
        self.assertTrue((owned / ".swapz-benchmark-complete").exists())
        self.assertEqual(self.run_cleanup().returncode, 0)
        self.assertFalse(owned.exists())

    def test_root_or_marker_identity_must_be_proven(self):
        owned = self.session("Abcd1234")
        (self.root / "swapz-benchmark.Zzzz9999").mkdir(mode=0o700)
        (self.root / "swapz-benchmark.Zzzz9999" / "fixture.bin").write_bytes(b"foreign")
        self.assertEqual(self.run_cleanup().returncode, 0)
        self.assertTrue((self.root / "swapz-benchmark.Zzzz9999").exists())
        self.assertFalse(owned.exists())
        owned = self.session("Abcd1234")
        (owned / ".swapz-benchmark-complete").chmod(0o644)
        self.assertEqual(self.run_cleanup().returncode, 0)
        self.assertTrue(owned.exists())
        self.root.chmod(0o777)
        blocked = self.run_cleanup()
        self.assertEqual(blocked.returncode, 2)
        self.assertTrue(owned.exists())
        self.root.chmod(0o700)

    def test_hardlinks_and_budget_are_fail_closed(self):
        owned = self.session("Abcd1234")
        outside = self.root / "other-link"
        os.link(owned / "fixture.bin", outside)
        self.assertEqual(self.run_cleanup().returncode, 2)
        self.assertTrue(outside.exists())
        outside.unlink()
        with mock.patch.object(cleanup_module, "MAX_SESSION_OBJECTS", 2):
            with self.assertRaisesRegex(cleanup_module.CleanupBlocked, "entry count"):
                cleanup_module.cleanup(str(self.root), self.owner_uid, 0o700)
        self.assertTrue(owned.exists())

    def test_active_process_and_malformed_marker_are_preserved(self):
        owned = self.session("Abcd1234")
        active_record = f"pid={os.getpid()}\nsource_sha={self.source_sha}\n"
        for marker in (".swapz-benchmark-owner", ".swapz-benchmark-complete"):
            (owned / marker).write_text(active_record)
        self.assertEqual(self.run_cleanup().returncode, 0)
        self.assertTrue(owned.exists())
        for marker in (".swapz-benchmark-owner", ".swapz-benchmark-complete"):
            (owned / marker).write_text("not a valid identity\n")
        self.assertEqual(self.run_cleanup().returncode, 0)
        self.assertTrue(owned.exists())


if __name__ == "__main__":
    unittest.main()
