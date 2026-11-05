#!/usr/bin/env python3
"""Rootless terminal-evidence and interrupted-readback oracle regressions."""

import contextlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
ORACLE = ROOT / "tests/tools/primary-real-swap-oracle.py"
SPEC = importlib.util.spec_from_file_location("primary_real_swap_oracle_terminal", ORACLE)
oracle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(oracle)


class TerminalEvidenceContracts(unittest.TestCase):
    def run_fixture(self, *, short_read=False, interrupted=False,
                    read_errno=None, close_fails=False):
        class AnonymousMemoryFixture:
            def __init__(self):
                self.contents = bytearray(2 * oracle.PAGE_BYTES)
                self.closed = False
                self.verify_started = False

            def __getitem__(self, key):
                if (self.verify_started and isinstance(key, slice) and
                        key.start == oracle.PAGE_BYTES):
                    if interrupted:
                        raise KeyboardInterrupt()
                    if read_errno is not None:
                        raise OSError(read_errno, "synthetic page read error")
                    if short_read:
                        return self.contents[key.start:key.stop - 1]
                return self.contents[key]

            def __setitem__(self, key, value):
                self.contents[key] = value

            def close(self):
                if close_fails:
                    raise OSError(9, "synthetic close error")
                self.closed = True

        allocation = AnonymousMemoryFixture()
        commands = iter(("FILL", "VERIFY"))
        standard_output = io.StringIO()
        standard_error = io.StringIO()

        def read_command():
            command = next(commands)
            if command == "VERIFY":
                allocation.verify_started = True
            return command

        with mock.patch.object(oracle, "MIB", 2 * oracle.PAGE_BYTES), \
                mock.patch.object(oracle, "MIN_MIB", 1), \
                mock.patch.object(oracle, "MAX_MIB", 1), \
                mock.patch.object(oracle, "_disable_dumps"), \
                mock.patch.object(oracle, "_read_command", side_effect=read_command), \
                mock.patch.object(oracle.mmap, "mmap", return_value=allocation), \
                contextlib.redirect_stdout(standard_output), \
                contextlib.redirect_stderr(standard_error):
            status = oracle.run_workload("ab" * 16, 1)
        return status, standard_output.getvalue(), standard_error.getvalue(), allocation

    def test_success_shaped_record_is_withheld_until_unmap_succeeds(self):
        status, stdout, stderr, allocation = self.run_fixture(close_fails=True)
        self.assertEqual(status, 1)
        self.assertFalse(allocation.closed)
        self.assertIn("ORACLE_FILLED=", stdout)
        self.assertNotIn("ORACLE_VERIFIED=", stdout)
        self.assertIn("phase=cleanup", stderr)
        self.assertIn("verified_pages=2/2", stderr)
        self.assertIn("cleanup_complete=false", stderr)
        self.assertNotIn("ab" * 16, stderr)

    def test_short_read_failure_precedes_failed_close_and_preserves_counts(self):
        status, stdout, stderr, allocation = self.run_fixture(
            short_read=True, close_fails=True)
        self.assertEqual(status, 1)
        self.assertNotIn("ORACLE_VERIFIED=", stdout)
        self.assertIn("short oracle page read at page 1: 4095 of 4096 bytes", stderr)
        self.assertIn("phase=verify", stderr)
        self.assertIn("verified_pages=1/2", stderr)
        self.assertIn("verified_bytes=4096/8192", stderr)
        self.assertIn("expected_mismatches=0 observed_mismatches=0", stderr)
        self.assertIn("errno=none", stderr)
        self.assertIn("cleanup_complete=false", stderr)
        self.assertNotIn("ab" * 16, stderr)
        self.assertFalse(allocation.closed)

    def test_read_errno_remains_primary_when_close_has_different_errno(self):
        status, stdout, stderr, allocation = self.run_fixture(
            read_errno=5, close_fails=True)
        self.assertEqual(status, 1)
        self.assertFalse(allocation.closed)
        self.assertNotIn("ORACLE_VERIFIED=", stdout)
        self.assertIn("phase=verify", stderr)
        self.assertIn("verified_pages=1/2", stderr)
        self.assertIn("error=OSError errno=5 cleanup_complete=false", stderr)
        self.assertIn("[Errno 9] synthetic close error", stderr)
        self.assertNotIn("ab" * 16, stderr)

    def test_interrupted_readback_cleans_up_without_reporting_verification(self):
        status, stdout, stderr, allocation = self.run_fixture(interrupted=True)
        self.assertEqual(status, 1)
        self.assertTrue(allocation.closed)
        self.assertNotIn("ORACLE_VERIFIED=", stdout)
        self.assertIn("phase=verify", stderr)
        self.assertIn("verified_pages=1/2", stderr)
        self.assertIn("cleanup_complete=true", stderr)
        self.assertIn("KeyboardInterrupt", stderr)
        self.assertNotIn("ab" * 16, stderr)


if __name__ == "__main__":
    unittest.main()
