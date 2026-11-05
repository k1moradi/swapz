#!/usr/bin/env python3
"""Rootless terminal-evidence and interrupted-readback oracle regressions."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
ORACLE = ROOT / "tests/tools/primary-real-swap-oracle.py"
SPEC = importlib.util.spec_from_file_location("primary_real_swap_oracle_terminal", ORACLE)
oracle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(oracle)


class TerminalEvidenceContracts(unittest.TestCase):
    def run_fixture(self, *, short_read=False, interrupted=False, corrupt=False,
                    corrupt_pages=(), page_count=2, read_errno=None,
                    report_errno=None, close_fails=False):
        class AnonymousMemoryFixture:
            def __init__(self):
                self.contents = bytearray(page_count * oracle.PAGE_BYTES)
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
                if corrupt:
                    allocation.contents[9] ^= 1
                for page_index in corrupt_pages:
                    allocation.contents[page_index * oracle.PAGE_BYTES + 9] ^= 1
            return command

        original_emit = oracle._emit

        def emit_record(prefix, payload):
            if prefix == "ORACLE_VERIFIED=" and report_errno is not None:
                raise OSError(report_errno, "synthetic evidence report error")
            original_emit(prefix, payload)

        with mock.patch.object(oracle, "MIB", page_count * oracle.PAGE_BYTES), \
                mock.patch.object(oracle, "MIN_MIB", 1), \
                mock.patch.object(oracle, "MAX_MIB", 1), \
                mock.patch.object(oracle, "_disable_dumps"), \
                mock.patch.object(oracle, "_emit", side_effect=emit_record), \
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
        self.assertIn(
            "expected_page_mismatches=0 observed_page_mismatches=0", stderr)
        self.assertIn(
            "expected_byte_mismatches=0 observed_byte_mismatches=0", stderr)
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

    def test_integrity_mismatch_remains_primary_after_unmap_failure(self):
        status, stdout, stderr, allocation = self.run_fixture(
            corrupt=True, close_fails=True)
        self.assertEqual(status, 1)
        self.assertFalse(allocation.closed)
        self.assertNotIn("ORACLE_VERIFIED=", stdout)
        self.assertIn("phase=verify", stderr)
        self.assertIn(
            "expected_page_mismatches=0 observed_page_mismatches=1", stderr)
        self.assertIn(
            "expected_byte_mismatches=0 observed_byte_mismatches=1", stderr)
        self.assertIn("error=byte_mismatch errno=none cleanup_complete=false", stderr)
        self.assertIn("[Errno 9] synthetic close error", stderr)
        self.assertNotIn("ab" * 16, stderr)

    def test_integrity_mismatch_remains_primary_after_reporting_failure(self):
        status, stdout, stderr, allocation = self.run_fixture(
            corrupt=True, report_errno=32)
        self.assertEqual(status, 1)
        self.assertTrue(allocation.closed)
        self.assertNotIn("ORACLE_VERIFIED=", stdout)
        self.assertIn("phase=verify", stderr)
        self.assertIn(
            "expected_page_mismatches=0 observed_page_mismatches=1", stderr)
        self.assertIn(
            "expected_byte_mismatches=0 observed_byte_mismatches=1", stderr)
        self.assertIn("error=byte_mismatch errno=none cleanup_complete=true", stderr)
        self.assertIn("[Errno 32] synthetic evidence report error", stderr)
        self.assertNotIn("ab" * 16, stderr)

    def test_mismatch_page_count_is_not_truncated_with_diagnostic_samples(self):
        status, stdout, stderr, allocation = self.run_fixture(
            corrupt_pages=range(17), page_count=17)
        self.assertEqual(status, 1)
        self.assertTrue(allocation.closed)
        verified_lines = [
            line for line in stdout.splitlines()
            if line.startswith("ORACLE_VERIFIED=")
        ]
        self.assertEqual(len(verified_lines), 1)
        verified = json.loads(verified_lines[0].split("=", 1)[1])
        self.assertEqual(verified["mismatched_pages"], 17)
        self.assertEqual(verified["mismatches"], 17)
        self.assertEqual(len(verified["mismatch_samples"]), 16)
        self.assertIn(
            "expected_page_mismatches=0 observed_page_mismatches=17", stderr)
        self.assertIn(
            "expected_byte_mismatches=0 observed_byte_mismatches=17", stderr)
        self.assertNotIn("ab" * 16, stderr)

    def test_interrupt_before_fill_returns_bounded_failure_without_allocating(self):
        stderr = io.StringIO()
        mmap_call = mock.Mock()
        with mock.patch.object(oracle, "_disable_dumps"), \
                mock.patch.object(oracle, "_emit"), \
                mock.patch.object(oracle, "_read_command",
                                  side_effect=KeyboardInterrupt()), \
                mock.patch.object(oracle.mmap, "mmap", mmap_call), \
                contextlib.redirect_stderr(stderr):
            status = oracle.run_workload("ab" * 16, oracle.MIN_MIB)
        self.assertEqual(status, 1)
        mmap_call.assert_not_called()
        self.assertIn("phase=wait_fill", stderr.getvalue())
        self.assertIn("verified_pages=0/", stderr.getvalue())
        self.assertIn("observed_page_mismatches=0", stderr.getvalue())
        self.assertIn("observed_byte_mismatches=0", stderr.getvalue())
        self.assertIn("error=KeyboardInterrupt", stderr.getvalue())
        self.assertIn("cleanup_complete=true", stderr.getvalue())
        self.assertNotIn("ab" * 16, stderr.getvalue())

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


    def test_clean_readback_has_exactly_one_ordered_terminal_record(self):
        status, stdout, stderr, allocation = self.run_fixture()
        self.assertEqual(status, 0)
        self.assertTrue(allocation.closed)
        self.assertEqual(stderr, "")
        records = stdout.splitlines()
        self.assertEqual(
            [record.partition("=")[0] for record in records],
            ["ORACLE_WAITING", "ORACLE_FILLED", "ORACLE_VERIFIED"])
        waiting, filled, verified = [
            json.loads(record.partition("=")[2]) for record in records
        ]
        self.assertEqual((waiting["pages"], waiting["bytes"]), (2, 8192))
        self.assertEqual((filled["pages"], filled["bytes"]), (2, 8192))
        self.assertEqual(
            (verified["verified_pages"], verified["verified_bytes"]), (2, 8192))
        self.assertEqual(verified["mismatched_pages"], 0)
        self.assertEqual(verified["mismatches"], 0)
        self.assertEqual(verified["mismatch_samples"], [])
        self.assertEqual(verified["digest"], verified["expected_digest"])
        self.assertEqual(filled["digest"], verified["expected_digest"])

    def test_clean_readback_report_failure_keeps_original_errno(self):
        status, stdout, stderr, allocation = self.run_fixture(report_errno=32)
        self.assertEqual(status, 1)
        self.assertTrue(allocation.closed)
        self.assertIn("ORACLE_FILLED=", stdout)
        self.assertNotIn("ORACLE_VERIFIED=", stdout)
        self.assertEqual(
            [record.partition("=")[0] for record in stdout.splitlines()],
            ["ORACLE_WAITING", "ORACLE_FILLED"])
        self.assertIn("phase=report", stderr)
        self.assertIn("verified_pages=2/2 verified_bytes=8192/8192", stderr)
        self.assertIn(
            "expected_page_mismatches=0 observed_page_mismatches=0", stderr)
        self.assertIn(
            "expected_byte_mismatches=0 observed_byte_mismatches=0", stderr)
        self.assertIn("error=OSError errno=32 cleanup_complete=true", stderr)
        self.assertNotIn("ab" * 16, stderr)


if __name__ == "__main__":
    unittest.main()
