#!/usr/bin/env python3
"""Rootless filesystem safety regressions for the private /tmp memory gate."""

import errno
import importlib.util
import io
import os
from pathlib import Path
import select
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
        self.evidence(directory)
        return directory

    def evidence(self, directory, *, source_sha=None, passed=True):
        source_sha = self.source_sha if source_sha is None else source_sha
        content = (f"SOURCE_HEAD={source_sha} MODULE_SHA256=not-a-secret\n"
                   f"EVIDENCE_DIR={directory}\n"
                   + ("PASS: isolated pair and ordinary teardown\n" if passed else
                      "BLOCKED: device teardown incomplete\n")
                   + f"EVIDENCE={directory / 'session.log'}\n")
        (directory / "session.log").write_text(content)
        (directory / "session.log").chmod(0o600)

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
        expected_reclaimed_bytes = sum(file.stat().st_size for file in owned.rglob("*")
                                       if file.is_file())
        incomplete = self.session("Bcde1234", complete=False)
        conflicting = self.session("Cdef1234", identity=self.record.replace("a" * 40, "b" * 40))
        unrelated_prefix = self.root / "swapz-id36.DeadBeef"
        unrelated_prefix.mkdir()
        (unrelated_prefix / "pressure.log").write_text("pressure evidence")
        symlink = self.root / "swapz-benchmark.DeadBeef"
        symlink.symlink_to(foreign_directory, target_is_directory=True)

        result = self.run_cleanup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("removed:1 retained:3", result.stdout)
        self.assertIn(f"reclaimed_logical_bytes:{expected_reclaimed_bytes}", result.stdout)
        self.assertIn("retained_unproved:2 retained_identity:1 retained_active:0",
                      result.stdout)
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
        self.assertIn("category=unsafe-type", result.stderr)
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
        self.assertIn("phase=root-validation category=root-identity", blocked.stderr)
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
        oversized_pid = f"pid={'9' * 30}\nsource_sha={self.source_sha}\n"
        for marker in (".swapz-benchmark-owner", ".swapz-benchmark-complete"):
            (owned / marker).write_text(oversized_pid)
        self.assertEqual(self.run_cleanup().returncode, 0)
        self.assertTrue(owned.exists())

    def test_exited_owner_with_live_same_owner_session_fd_is_retained(self):
        owned = self.session("Abcd1234")
        child = subprocess.Popen(
            [sys.executable, "-I", "-B", "-c",
             "import os, sys\n"
             "descriptor = os.open(sys.argv[1], os.O_RDONLY)\n"
             "print('ready', flush=True)\n"
             "sys.stdin.buffer.read(1)\n"
             "os.close(descriptor)\n",
             str(owned / "fixture.bin")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "ready")
            result = self.run_cleanup()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("removed:0 retained:1", result.stdout)
            self.assertIn("retained_active:1", result.stdout)
            self.assertEqual((owned / "fixture.bin").read_bytes(), b"owned payload")
        finally:
            if child.poll() is None:
                child.stdin.write("x")
                child.stdin.flush()
            child.wait(timeout=5)
        result = self.run_cleanup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(owned.exists())

    def test_inaccessible_proc_links_do_not_hide_live_session_descriptor(self):
        owned = self.session("Abcd1234")
        child = subprocess.Popen(
            [sys.executable, "-I", "-B", "-c",
             "import os, sys\n"
             "descriptor = os.open(sys.argv[1], os.O_RDONLY)\n"
             "print('ready', flush=True)\n"
             "sys.stdin.buffer.read(1)\n"
             "os.close(descriptor)\n",
             str(owned / "fixture.bin")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        original_stat = cleanup_module.os.stat

        def deny_proc_directory_links(path, *args, **kwargs):
            if (isinstance(path, str) and path.startswith("/proc/")
                    and path.endswith(("/cwd", "/root"))):
                raise PermissionError(errno.EACCES, "synthetic protected proc link")
            return original_stat(path, *args, **kwargs)

        try:
            self.assertEqual(child.stdout.readline().strip(), "ready")
            state = cleanup_module.CleanupState()
            with mock.patch.object(cleanup_module.os, "stat",
                                   side_effect=deny_proc_directory_links):
                self.assertEqual(
                    cleanup_module.cleanup(str(self.root), self.owner_uid, 0o700, state),
                    0)
            self.assertEqual(state.removed, 0)
            self.assertEqual(state.retained_active, 1)
            self.assertEqual((owned / "fixture.bin").read_bytes(), b"owned payload")
        finally:
            if child.poll() is None:
                child.stdin.write("x")
                child.stdin.flush()
            child.wait(timeout=5)

    def test_fd_closed_but_live_mmap_retains_completed_session(self):
        owned = self.session("Abcd1234")
        expected_logical_bytes = sum(file.stat().st_size for file in owned.rglob("*")
                                     if file.is_file())
        # libc mmap does not retain the duplicate fd that Python's mmap object
        # normally keeps open; only the live file-backed mapping remains.
        child_code = (
            "import ctypes, mmap, os, sys\n"
            "libc = ctypes.CDLL(None, use_errno=True)\n"
            "libc.mmap.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, "
            "ctypes.c_int, ctypes.c_int, ctypes.c_long)\n"
            "libc.mmap.restype = ctypes.c_void_p\n"
            "libc.munmap.argtypes = (ctypes.c_void_p, ctypes.c_size_t)\n"
            "descriptor = os.open(sys.argv[1], os.O_RDONLY)\n"
            "mapped = libc.mmap(None, 1, mmap.PROT_READ, mmap.MAP_PRIVATE, descriptor, 0)\n"
            "assert mapped != ctypes.c_void_p(-1).value\n"
            "os.close(descriptor)\n"
            "assert ctypes.string_at(mapped, 1) == b'o'\n"
            "print('ready', flush=True)\n"
            "sys.stdin.buffer.read(1)\n"
            "libc.munmap(mapped, 1)\n"
        )
        child = subprocess.Popen(
            [sys.executable, "-I", "-B", "-c", child_code, str(owned / "fixture.bin")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            ready, _, _ = select.select([child.stdout], [], [], 5)
            self.assertTrue(ready, "mapped-file fixture did not become ready")
            self.assertEqual(child.stdout.readline().strip(), "ready")

            result = self.run_cleanup()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("removed:0 retained:1", result.stdout)
            self.assertIn("retained_active:1", result.stdout)
            self.assertEqual((owned / "fixture.bin").read_bytes(), b"owned payload")

            original_open = open

            def deny_mapping_inventory(path, *args, **kwargs):
                if path == f"/proc/{child.pid}/maps":
                    raise PermissionError(errno.EACCES, "synthetic mapping visibility failure")
                return original_open(path, *args, **kwargs)

            state = cleanup_module.CleanupState()
            with mock.patch("builtins.open", side_effect=deny_mapping_inventory):
                with self.assertRaises(PermissionError) as caught:
                    cleanup_module.cleanup(str(self.root), self.owner_uid, 0o700, state)
            self.assertEqual(caught.exception.errno, errno.EACCES)
            self.assertEqual(state.phase, "session-activity")
            self.assertFalse(state.partial)
            self.assertTrue(owned.exists())

            with mock.patch("builtins.open", side_effect=deny_mapping_inventory), \
                 mock.patch.object(sys, "argv", [str(HELPER), str(self.root),
                                                str(self.owner_uid), "700"]), \
                 mock.patch.object(sys, "stderr", new_callable=io.StringIO) as diagnostics, \
                 mock.patch.object(sys, "stdout", new_callable=io.StringIO) as output:
                self.assertEqual(cleanup_module.main(), 2)
            self.assertEqual(output.getvalue(), "")
            self.assertIn("phase=session-activity category=filesystem-error", diagnostics.getvalue())
            self.assertIn("original_errno=EACCES(13)", diagnostics.getvalue())
            self.assertIn("retained=unexamined-or-unproved removed=0", diagnostics.getvalue())
            self.assertIn("session_class=swapz-benchmark ownership_identity=proven",
                          diagnostics.getvalue())
            self.assertIn("safe_next_action=inspect-retained-evidence-read-only",
                          diagnostics.getvalue())
        finally:
            child.stdin.close()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
                raise
            child.stdout.close()

        result = self.run_cleanup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("removed:1 retained:0", result.stdout)
        self.assertIn(f"reclaimed_logical_bytes:{expected_logical_bytes}", result.stdout)
        self.assertFalse(owned.exists())

    def test_unreadable_same_owner_process_inventory_blocks_before_unlink(self):
        owned = self.session("Abcd1234")
        state = cleanup_module.CleanupState()
        with mock.patch.object(
                cleanup_module, "session_referenced_by_same_owner_process",
                side_effect=OSError(errno.EACCES, "synthetic proc visibility failure")):
            with self.assertRaises(OSError) as caught:
                cleanup_module.cleanup(str(self.root), self.owner_uid, 0o700, state)
        self.assertEqual(caught.exception.errno, errno.EACCES)
        self.assertEqual(state.phase, "session-activity")
        self.assertFalse(state.partial)
        self.assertEqual((owned / "fixture.bin").read_bytes(), b"owned payload")

    def test_pid_and_matching_markers_without_teardown_evidence_are_not_authority(self):
        owned = self.session("Abcd1234")
        (owned / "session.log").unlink()
        result = self.run_cleanup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("removed:0 retained:1", result.stdout)
        self.assertTrue(owned.exists())
        self.evidence(owned, passed=False)
        self.assertIn("removed:0 retained:1", self.run_cleanup().stdout)
        self.assertTrue(owned.exists())
        self.evidence(owned, source_sha="b" * 40)
        self.assertIn("removed:0 retained:1", self.run_cleanup().stdout)
        self.assertTrue(owned.exists())
        self.evidence(owned)
        self.assertEqual(self.run_cleanup().returncode, 0)
        self.assertFalse(owned.exists())

    def test_same_source_pass_log_from_other_session_is_not_provenance(self):
        source = self.session("Abcd1234", complete=False)
        candidate = self.session("Bcde1234")
        (candidate / "session.log").write_bytes((source / "session.log").read_bytes())
        result = self.run_cleanup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("removed:0 retained:2", result.stdout)
        self.assertTrue(source.exists())
        self.assertTrue(candidate.exists())

    def test_marker_change_during_read_retains_session(self):
        owned = self.session("Abcd1234")
        complete = owned / ".swapz-benchmark-complete"
        original_read = cleanup_module.os.read
        changed = False

        def rewrite_after_read(descriptor, length):
            nonlocal changed
            contents = original_read(descriptor, length)
            if not changed and os.fstat(descriptor).st_ino == complete.stat().st_ino:
                changed = True
                complete.write_text(self.record)
                complete.chmod(0o600)
            return contents

        with mock.patch.object(cleanup_module.os, "read", side_effect=rewrite_after_read):
            self.assertEqual(cleanup_module.cleanup(str(self.root), self.owner_uid, 0o700), 0)
        self.assertTrue(changed)
        self.assertTrue(owned.exists())

    def test_log_symlink_hardlink_and_non_private_log_retained(self):
        owned = self.session("Abcd1234")
        outside = self.root / "other-evidence"
        outside.write_text("foreign")
        evidence = owned / "session.log"
        for variant in ("symlink", "hardlink", "mode"):
            with self.subTest(variant=variant):
                evidence.unlink()
                if variant == "symlink":
                    evidence.symlink_to(outside)
                elif variant == "hardlink":
                    os.link(outside, evidence)
                else:
                    evidence.write_bytes(b"SOURCE_HEAD=" + self.source_sha.encode() +
                                         b" MODULE_SHA256=x\nPASS: isolated pair and ordinary teardown\n")
                    evidence.chmod(0o644)
                result = self.run_cleanup()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(owned.exists())
                self.assertEqual(outside.read_text(), "foreign")
        evidence.unlink()

    def test_replaced_log_fd_or_modified_log_retains_session(self):
        owned = self.session("Abcd1234")
        original_open = cleanup_module.os.open
        evidence = owned / "session.log"
        replaced = False

        def replace_on_open(path, flags, *args, **kwargs):
            nonlocal replaced
            if path == "session.log" and not replaced:
                replaced = True
                evidence.rename(self.root / "moved-log")
                self.evidence(owned)
            return original_open(path, flags, *args, **kwargs)

        with mock.patch.object(cleanup_module.os, "open", side_effect=replace_on_open):
            self.assertEqual(cleanup_module.cleanup(str(self.root), self.owner_uid, 0o700), 0)
        self.assertTrue(owned.exists())

    def test_failed_unlink_reports_original_errno_without_path_or_pass(self):
        owned = self.session("Abcd1234")
        original_unlink = cleanup_module.os.unlink

        def deny_unlink(path, *args, **kwargs):
            if path == "fixture.bin":
                raise OSError(errno.EACCES, "synthetic path may be sensitive", "/private/secret")
            return original_unlink(path, *args, **kwargs)

        state = cleanup_module.CleanupState()
        with mock.patch.object(cleanup_module.os, "unlink", side_effect=deny_unlink):
            with self.assertRaises(OSError) as caught:
                cleanup_module.cleanup(str(self.root), self.owner_uid, 0o700, state)
        self.assertEqual(caught.exception.errno, errno.EACCES)
        self.assertEqual(state.phase, "session-removal")
        self.assertTrue(state.partial)
        self.assertTrue(owned.exists())
        # Main formats only bounded metadata; no private path or PID inventory.
        with mock.patch.object(cleanup_module.os, "unlink", side_effect=deny_unlink):
            with mock.patch.object(sys, "argv", [str(HELPER), str(self.root), str(self.owner_uid), "700"]):
                with mock.patch.object(sys, "stderr", new_callable=io.StringIO) as diagnostics:
                    with mock.patch.object(sys, "stdout", new_callable=io.StringIO) as output:
                        self.assertEqual(cleanup_module.main(), 2)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("phase=session-removal category=filesystem-error", diagnostics.getvalue())
        self.assertIn("original_errno=EACCES(13)", diagnostics.getvalue())
        self.assertIn("retained=partial-or-uncertain", diagnostics.getvalue())
        self.assertIn("exit_code=2", diagnostics.getvalue())
        self.assertNotIn("/private", diagnostics.getvalue())
        self.assertNotIn("99999999", diagnostics.getvalue())

    def test_failed_rmdir_preserves_first_errno_and_reports_partial_state(self):
        owned = self.session("Abcd1234")
        original_rmdir = cleanup_module.os.rmdir

        def fail_final_rmdir(path, *args, **kwargs):
            if path == owned.name:
                raise OSError(errno.EBUSY, "synthetic busy fs")
            return original_rmdir(path, *args, **kwargs)

        state = cleanup_module.CleanupState()
        with mock.patch.object(cleanup_module.os, "rmdir", side_effect=fail_final_rmdir):
            with self.assertRaises(OSError) as caught:
                cleanup_module.cleanup(str(self.root), self.owner_uid, 0o700, state)
        self.assertEqual(caught.exception.errno, errno.EBUSY)
        self.assertEqual(state.phase, "session-finalization")
        self.assertTrue(state.partial)
        self.assertTrue(owned.exists())
        self.assertFalse((owned / ".swapz-benchmark-complete").exists())
        self.assertEqual(self.run_cleanup().returncode, 0)
        self.assertTrue(owned.exists())  # No proof remains: fail-closed, not resumable.

    def test_close_failure_does_not_hide_unlink_error(self):
        owned = self.session("Abcd1234")
        original_close = cleanup_module.os.close
        original_unlink = cleanup_module.os.unlink
        unlink_failed = False

        def fail_unlink(path, *args, **kwargs):
            nonlocal unlink_failed
            if path == "fixture.bin":
                unlink_failed = True
                raise OSError(errno.EIO, "original unlink failure")
            return original_unlink(path, *args, **kwargs)

        def fail_close(descriptor):
            original_close(descriptor)
            if unlink_failed:
                raise OSError(errno.EBADF, "secondary close failure")

        with mock.patch.object(cleanup_module.os, "unlink", side_effect=fail_unlink), \
             mock.patch.object(cleanup_module.os, "close", side_effect=fail_close):
            with self.assertRaises(OSError) as caught:
                cleanup_module.cleanup(str(self.root), self.owner_uid, 0o700)
        self.assertEqual(caught.exception.errno, errno.EIO)
        self.assertTrue(owned.exists())

    def test_unreadable_log_read_failure_is_blocking_not_silent(self):
        owned = self.session("Abcd1234")
        original_pread = cleanup_module.os.pread

        def fail_pread(descriptor, length, offset):
            if os.fstat(descriptor).st_ino == (owned / "session.log").stat().st_ino:
                raise OSError(errno.EIO, "path must not be in diagnostics", "/top-secret")
            return original_pread(descriptor, length, offset)

        state = cleanup_module.CleanupState()
        with mock.patch.object(cleanup_module.os, "pread", side_effect=fail_pread):
            with self.assertRaises(OSError) as caught:
                cleanup_module.cleanup(str(self.root), self.owner_uid, 0o700, state)
        self.assertEqual(caught.exception.errno, errno.EIO)
        self.assertEqual(state.phase, "session-provenance")
        self.assertTrue(owned.exists())


    def test_unreadable_session_entry_blocks_before_unlink(self):
        owned = self.session("Abcd1234")
        original_stat = cleanup_module.os.stat

        def deny_stat(path, *args, **kwargs):
            if path == "plan" and kwargs.get("dir_fd") is not None:
                raise OSError(errno.EACCES, "no access", "/private/secret")
            return original_stat(path, *args, **kwargs)

        state = cleanup_module.CleanupState()
        with mock.patch.object(cleanup_module.os, "stat", side_effect=deny_stat):
            with self.assertRaises(OSError) as caught:
                cleanup_module.cleanup(str(self.root), self.owner_uid, 0o700, state)
        self.assertEqual(caught.exception.errno, errno.EACCES)
        self.assertEqual(state.phase, "session-inspection")
        self.assertFalse(state.partial)
        self.assertTrue((owned / "fixture.bin").exists())

    def test_session_mode_change_while_opening_blocks_before_deletion(self):
        owned = self.session("Abcd1234")
        original_open = cleanup_module.os.open
        changed = False

        def make_session_public_after_open(path, flags, *args, **kwargs):
            nonlocal changed
            descriptor = original_open(path, flags, *args, **kwargs)
            if (path == owned.name and kwargs.get("dir_fd") is not None
                    and not changed):
                changed = True
                owned.chmod(0o777)
            return descriptor

        try:
            with mock.patch.object(cleanup_module.os, "open",
                                   side_effect=make_session_public_after_open):
                with self.assertRaisesRegex(cleanup_module.CleanupBlocked,
                                            "session directory changed"):
                    cleanup_module.cleanup(str(self.root), self.owner_uid, 0o700)
        finally:
            owned.chmod(0o700)
        self.assertTrue(changed)
        self.assertTrue((owned / "fixture.bin").exists())

    def test_regular_file_change_after_inspection_blocks_before_unlink(self):
        owned = self.session("Abcd1234")
        fixture = owned / "fixture.bin"
        original_remove_tree = cleanup_module.remove_tree
        changed = False

        def grow_after_inspection(directory, entries, mount_id, preserve_markers=False):
            nonlocal changed
            if preserve_markers and not changed:
                changed = True
                with fixture.open("ab") as output:
                    output.write(b" changed after inspection")
            return original_remove_tree(directory, entries, mount_id, preserve_markers)

        with mock.patch.object(cleanup_module, "remove_tree",
                               side_effect=grow_after_inspection):
            with self.assertRaisesRegex(cleanup_module.CleanupBlocked, "replaced"):
                cleanup_module.cleanup(str(self.root), self.owner_uid, 0o700)
        self.assertTrue(changed)
        self.assertTrue(fixture.exists())
        self.assertTrue((owned / ".swapz-benchmark-complete").exists())

    def test_session_directory_substitution_before_final_rmdir_is_blocked(self):
        owned = self.session("Abcd1234")
        original_remove_tree = cleanup_module.remove_tree
        moved = self.root / "original-retained"

        def replace_after_cleanup(directory, entries, mount_id, preserve_markers=False):
            original_remove_tree(directory, entries, mount_id, preserve_markers)
            if preserve_markers:
                owned.rename(moved)
                owned.mkdir(mode=0o700)
                (owned / "foreign.txt").write_text("DO NOT DELETE")

        state = cleanup_module.CleanupState()
        with mock.patch.object(cleanup_module, "remove_tree", side_effect=replace_after_cleanup):
            with self.assertRaisesRegex(cleanup_module.CleanupBlocked, "substituted"):
                cleanup_module.cleanup(str(self.root), self.owner_uid, 0o700, state)
        self.assertEqual(state.phase, "session-finalization")
        self.assertTrue(state.partial)
        self.assertEqual((owned / "foreign.txt").read_text(), "DO NOT DELETE")
        self.assertTrue(moved.exists())

    def test_session_renamed_during_inspection_blocks_before_any_unlink(self):
        owned = self.session("Abcd1234")
        moved = self.root / "moved-original"
        original_inspect = cleanup_module.inspect

        def rename_after_inspection(*args, **kwargs):
            entries = original_inspect(*args, **kwargs)
            if args[-1] == 0:
                owned.rename(moved)
                owned.mkdir(mode=0o700)
                (owned / "foreign.txt").write_bytes(b"DO NOT DELETE")
            return entries

        state = cleanup_module.CleanupState()
        with mock.patch.object(cleanup_module, "inspect", side_effect=rename_after_inspection):
            with self.assertRaisesRegex(cleanup_module.CleanupBlocked,
                                        "substituted before removal"):
                cleanup_module.cleanup(str(self.root), self.owner_uid, 0o700, state)
        self.assertEqual(state.phase, "session-removal")
        self.assertFalse(state.partial)
        self.assertEqual((moved / "fixture.bin").read_bytes(), b"owned payload")
        self.assertEqual((owned / "foreign.txt").read_bytes(), b"DO NOT DELETE")

    def test_root_renamed_during_inspection_blocks_before_any_unlink(self):
        owned = self.session("Abcd1234")
        moved_root = self.root.with_name(self.root.name + "-moved")
        original_inspect = cleanup_module.inspect

        def rename_after_inspection(*args, **kwargs):
            entries = original_inspect(*args, **kwargs)
            if args[-1] == 0:
                self.root.rename(moved_root)
                self.root.mkdir(mode=0o700)
            return entries

        try:
            with mock.patch.object(cleanup_module, "inspect",
                                   side_effect=rename_after_inspection):
                with self.assertRaisesRegex(cleanup_module.CleanupBlocked,
                                            "root changed before session removal"):
                    cleanup_module.cleanup(str(self.root), self.owner_uid, 0o700)
            self.assertEqual((moved_root / owned.name / "fixture.bin").read_bytes(),
                             b"owned payload")
        finally:
            if moved_root.exists():
                self.root.rmdir()
                moved_root.rename(self.root)

    def test_session_mount_change_before_removal_blocks_before_unlink(self):
        owned = self.session("Abcd1234")
        original_mount_id = cleanup_module.mount_id
        session_mount_checks = 0

        def substitute_mount(descriptor):
            nonlocal session_mount_checks
            if os.fstat(descriptor).st_ino == owned.stat().st_ino:
                session_mount_checks += 1
                if session_mount_checks == 2:
                    return "999999999"
            return original_mount_id(descriptor)

        state = cleanup_module.CleanupState()
        with mock.patch.object(cleanup_module, "mount_id", side_effect=substitute_mount):
            with self.assertRaisesRegex(cleanup_module.CleanupBlocked,
                                        "mount changed before removal"):
                cleanup_module.cleanup(str(self.root), self.owner_uid, 0o700, state)
        self.assertFalse(state.partial)
        self.assertEqual((owned / "fixture.bin").read_bytes(), b"owned payload")


if __name__ == "__main__":
    unittest.main()
