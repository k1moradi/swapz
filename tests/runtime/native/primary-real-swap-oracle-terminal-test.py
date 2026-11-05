#!/usr/bin/env python3
"""Rootless terminal-evidence and interrupted-readback oracle regressions."""

import contextlib
import errno
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
ORACLE = ROOT / "tests/tools/primary-real-swap-oracle.py"
SPEC = importlib.util.spec_from_file_location("primary_real_swap_oracle_terminal", ORACLE)
oracle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(oracle)

QUALIFIER = ROOT / "tests/tools/qualify-primary-real-swap.py"
QUALIFIER_SPEC = importlib.util.spec_from_file_location(
    "qualify_primary_real_swap_terminal", QUALIFIER)
qualify = importlib.util.module_from_spec(QUALIFIER_SPEC)
sys.modules[QUALIFIER_SPEC.name] = qualify
QUALIFIER_SPEC.loader.exec_module(qualify)


class TerminalEvidenceContracts(unittest.TestCase):
    def run_fixture(self, *, short_read=False, interrupted=False, corrupt=False,
                    corrupt_pages=(), page_count=2, read_errno=None,
                    report_errno=None, close_fails=False, closed_output_at=None):
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
            if prefix == closed_output_at:
                # A closed text stream raises ValueError, not BrokenPipeError.
                closed_stream = io.StringIO()
                closed_stream.close()
                print(prefix, file=closed_stream, flush=True)
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

    def test_eintr_page_read_precedes_teardown_errno(self):
        status, stdout, stderr, allocation = self.run_fixture(
            read_errno=errno.EINTR, close_fails=True)
        self.assertEqual(status, 1)
        self.assertFalse(allocation.closed)
        self.assertNotIn("ORACLE_VERIFIED=", stdout)
        self.assertIn("phase=verify verified_pages=1/2", stderr)
        self.assertIn("verified_bytes=4096/8192", stderr)
        self.assertIn("observed_page_mismatches=0", stderr)
        self.assertIn("observed_byte_mismatches=0", stderr)
        self.assertIn("error=InterruptedError errno=4 cleanup_complete=false", stderr)
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

    def test_clean_readback_matches_parent_terminal_contract(self):
        status, stdout, stderr, allocation = self.run_fixture()
        self.assertEqual(status, 0)
        self.assertTrue(allocation.closed)
        self.assertEqual(stderr, "")

        expected_pages = 2
        expected_bytes = expected_pages * oracle.PAGE_BYTES
        records = stdout.splitlines()
        self.assertEqual(
            [record.partition("=")[0] for record in records],
            ["ORACLE_WAITING", "ORACLE_FILLED", "ORACLE_VERIFIED"])
        waiting, filled, verified = [
            json.loads(record.partition("=")[2]) for record in records
        ]
        self.assertEqual(
            (waiting["pages"], waiting["bytes"]),
            (expected_pages, expected_bytes))
        self.assertEqual(
            (filled["pages"], filled["bytes"]),
            (expected_pages, expected_bytes))
        self.assertEqual(
            (verified["verified_pages"], verified["verified_bytes"]),
            (expected_pages, expected_bytes))
        self.assertEqual(verified["mismatched_pages"], 0)
        self.assertEqual(verified["mismatches"], 0)
        self.assertEqual(verified["mismatch_samples"], [])
        self.assertEqual(verified["digest"], verified["expected_digest"])
        self.assertEqual(filled["digest"], verified["expected_digest"])
        qualify.require_oracle_verification_details([verified])

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
        self.assertIn(
            "error=BrokenPipeError errno=32 cleanup_complete=true", stderr)
        self.assertNotIn("ab" * 16, stderr)

    def test_closed_fill_stream_preserves_bounded_failure_and_unmaps(self):
        status, stdout, stderr, allocation = self.run_fixture(
            closed_output_at="ORACLE_FILLED=")
        self.assertEqual(status, 1)
        self.assertTrue(allocation.closed)
        self.assertIn("ORACLE_WAITING=", stdout)
        self.assertNotIn("ORACLE_FILLED=", stdout)
        self.assertNotIn("ORACLE_VERIFIED=", stdout)
        self.assertIn("phase=fill verified_pages=0/2 verified_bytes=0/8192", stderr)
        self.assertIn("observed_page_mismatches=0", stderr)
        self.assertIn("observed_byte_mismatches=0", stderr)
        self.assertIn("error=ValueError errno=none cleanup_complete=true", stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertNotIn("ab" * 16, stderr)

    def test_closed_verified_stream_preserves_bounded_failure_and_unmaps(self):
        status, stdout, stderr, allocation = self.run_fixture(
            closed_output_at="ORACLE_VERIFIED=")
        self.assertEqual(status, 1)
        self.assertTrue(allocation.closed)
        self.assertIn("ORACLE_FILLED=", stdout)
        self.assertNotIn("ORACLE_VERIFIED=", stdout)
        self.assertIn("phase=report verified_pages=2/2 verified_bytes=8192/8192", stderr)
        self.assertIn("observed_page_mismatches=0", stderr)
        self.assertIn("observed_byte_mismatches=0", stderr)
        self.assertIn("error=ValueError errno=none cleanup_complete=true", stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertNotIn("ab" * 16, stderr)

    def test_parent_rejects_forged_mismatch_totals_and_bad_samples(self):
        verified_pages = 17
        verified_bytes = verified_pages * oracle.PAGE_BYTES
        valid_record = {
            "verified_pages": verified_pages,
            "verified_bytes": verified_bytes,
            "mismatched_pages": 0,
            "mismatches": 0,
            "mismatch_samples": [],
        }
        qualify.require_oracle_verification_details([valid_record])

        capped_record = {
            **valid_record,
            "mismatched_pages": verified_pages,
            "mismatches": verified_pages,
            "mismatch_samples": [
                {"page": page_index, "byte": 9}
                for page_index in range(qualify.MAX_ORACLE_MISMATCH_SAMPLES)
            ],
        }
        qualify.require_oracle_verification_details([capped_record])

        mutants = (
            {**valid_record, "mismatched_pages": 1},
            {**valid_record, "mismatches": 1},
            {
                **valid_record,
                "mismatched_pages": 1,
                "mismatches": 1,
                "mismatch_samples": [],
            },
            {
                **valid_record,
                "mismatched_pages": 1,
                "mismatches": 1,
                "mismatch_samples": [{"page": verified_pages, "byte": 0}],
            },
            {
                **valid_record,
                "mismatched_pages": 1,
                "mismatches": 1,
                "mismatch_samples": [{"page": 0, "byte": oracle.PAGE_BYTES}],
            },
        )
        for forged_record in mutants:
            with self.subTest(forged_record=forged_record), self.assertRaises(
                    qualify.QualificationFailure):
                qualify.require_oracle_verification_details([forged_record])

    def test_parent_rejects_duplicate_or_trailing_terminal_bytes(self):
        pending_tails = (
            bytearray(b'ORACLE_VERIFIED={"verified_pages":2}\n'),
            bytearray(b'ORACLE_VERIFIED={"verified_pages":2'),
        )
        for pending_tail in pending_tails:
            with self.subTest(pending_tail=bytes(pending_tail)):
                read_descriptor, write_descriptor = os.pipe()
                os.close(write_descriptor)
                with os.fdopen(read_descriptor, "rb", buffering=0) as output:
                    process = mock.Mock(stdout=output, stderr=io.StringIO())
                    process.wait.return_value = 0
                    with self.assertRaisesRegex(
                            qualify.QualificationFailure,
                            "phase=terminal.*child_exit=0.*evidence_complete=false"):
                        qualify._require_oracle_terminal_exit(
                            process, qualify.time.monotonic() + 1,
                            lambda: None, pending_tail)

        read_descriptor, write_descriptor = os.pipe()
        try:
            os.write(write_descriptor, b"unexpected-terminal-tail")
            os.close(write_descriptor)
            write_descriptor = -1
            with os.fdopen(read_descriptor, "rb", buffering=0) as output:
                process = mock.Mock(stdout=output, stderr=io.StringIO())
                process.wait.return_value = 0
                with self.assertRaisesRegex(
                        qualify.QualificationFailure,
                        "phase=terminal.*child_exit=0.*evidence_complete=false"):
                    qualify._require_oracle_terminal_exit(
                        process, qualify.time.monotonic() + 1,
                        lambda: None, bytearray())
        finally:
            if write_descriptor >= 0:
                os.close(write_descriptor)

    def test_parent_rejects_reordered_or_truncated_terminal_record(self):
        cases = (
            (
                b'ORACLE_FILLED={"pages":2}\n',
                "unexpected or oversized record",
            ),
            (
                b'ORACLE_VERIFIED={"verified_pages":2',
                "closed output before ORACLE_VERIFIED",
            ),
        )
        for payload, expected_error in cases:
            with self.subTest(payload=payload):
                read_descriptor, write_descriptor = os.pipe()
                try:
                    os.write(write_descriptor, payload)
                    os.close(write_descriptor)
                    write_descriptor = -1
                    with os.fdopen(read_descriptor, "rb", buffering=0) as output:
                        process = mock.Mock(stdout=output)
                        process.poll.return_value = None
                        with self.assertRaisesRegex(
                                qualify.QualificationFailure, expected_error):
                            qualify._oracle_event(
                                process, "ORACLE_VERIFIED=",
                                qualify.time.monotonic() + 1,
                                lambda: None, bytearray())
                finally:
                    if write_descriptor >= 0:
                        os.close(write_descriptor)

    def test_parent_requires_zero_exit_and_observed_terminal_eof(self):
        read_descriptor, write_descriptor = os.pipe()
        os.close(write_descriptor)
        with os.fdopen(read_descriptor, "rb", buffering=0) as output:
            process = mock.Mock(stdout=output, stderr=None)
            process.wait.return_value = 0
            qualify._require_oracle_terminal_exit(
                process, qualify.time.monotonic() + 1,
                lambda: None, bytearray())

        read_descriptor, write_descriptor = os.pipe()
        try:
            with os.fdopen(read_descriptor, "rb", buffering=0) as output:
                process = mock.Mock(stdout=output, stderr=None)
                process.wait.return_value = 0
                with self.assertRaisesRegex(
                        qualify.QualificationFailure,
                        "cannot confirm terminal EOF"):
                    qualify._require_oracle_terminal_exit(
                        process, qualify.time.monotonic() + 1,
                        lambda: None, bytearray())
        finally:
            os.close(write_descriptor)

    def test_parent_preserves_bounded_nonzero_child_diagnostic(self):
        read_descriptor, write_descriptor = os.pipe()
        os.close(write_descriptor)
        oracle_failure = (
            "FAIL: oracle phase=verify verified_pages=1/2 "
            "verified_bytes=4096/8192 expected_page_mismatches=0 "
            "observed_page_mismatches=0 expected_byte_mismatches=0 "
            "observed_byte_mismatches=0 error=OSError errno=5 "
            "cleanup_complete=true"
        )
        private_traceback = (
            "Traceback (most recent call last):\n"
            '  File "/private/oracle.py", line 1, in <module>\n'
        )
        with os.fdopen(read_descriptor, "rb", buffering=0) as output:
            process = mock.Mock(
                stdout=output,
                stderr=io.StringIO(private_traceback + oracle_failure))
            process.wait.return_value = 7
            with self.assertRaisesRegex(
                    qualify.QualificationFailure,
                    "phase=terminal.*child_exit=7.*evidence_complete=false.*"
                    "phase=verify.*errno=5.*cleanup_complete=true") as caught:
                qualify._require_oracle_terminal_exit(
                    process, qualify.time.monotonic() + 1,
                    lambda: None, bytearray())
        self.assertNotIn("Traceback", str(caught.exception))
        self.assertNotIn("/private/oracle.py", str(caught.exception))

    def test_exit_zero_and_partial_child_diagnostic_cannot_replace_verified(self):
        read_descriptor, write_descriptor = os.pipe()
        try:
            os.write(write_descriptor, b'ORACLE_VERIFIED={"verified_pages":2')
            os.close(write_descriptor)
            write_descriptor = -1
            partial_diagnostic = io.StringIO("FAIL: oracle phase=verify")
            with os.fdopen(read_descriptor, "rb", buffering=0) as output:
                process = mock.Mock(stdout=output, stderr=partial_diagnostic)
                process.poll.return_value = 0
                with self.assertRaisesRegex(
                        qualify.QualificationFailure,
                        "phase=terminal.*child_exit=0.*evidence_complete=false.*"
                        "closed output before ORACLE_VERIFIED") as caught:
                    qualify._oracle_event(
                        process, "ORACLE_VERIFIED=",
                        qualify.time.monotonic() + 1,
                        lambda: None, bytearray())
            self.assertNotIn(
                "FAIL: oracle phase=verify", str(caught.exception))
            self.assertNotIn("verified_pages=", str(caught.exception))
        finally:
            if write_descriptor >= 0:
                os.close(write_descriptor)

    def test_preverified_nonzero_exit_preserves_only_structured_summary(self):
        read_descriptor, write_descriptor = os.pipe()
        os.close(write_descriptor)
        oracle_failure = (
            "FAIL: oracle phase=verify verified_pages=1/2 "
            "verified_bytes=4096/8192 expected_page_mismatches=0 "
            "observed_page_mismatches=0 expected_byte_mismatches=0 "
            "observed_byte_mismatches=0 error=InterruptedError errno=4 "
            "cleanup_complete=false"
        )
        private_traceback = (
            "Traceback (most recent call last):\n"
            '  File "/private/oracle.py", line 1, in <module>\n'
        )
        with os.fdopen(read_descriptor, "rb", buffering=0) as output:
            process = mock.Mock(
                stdout=output,
                stderr=io.StringIO(private_traceback + oracle_failure))
            process.poll.return_value = 7
            with self.assertRaisesRegex(
                    qualify.QualificationFailure,
                    "phase=terminal.*child_exit=7.*evidence_complete=false.*"
                    "phase=verify.*verified_pages=1/2.*verified_bytes=4096/8192.*"
                    "errno=4.*cleanup_complete=false") as caught:
                qualify._oracle_event(
                    process, "ORACLE_VERIFIED=",
                    qualify.time.monotonic() + 1,
                    lambda: None, bytearray())
        self.assertNotIn("Traceback", str(caught.exception))
        self.assertNotIn("/private/oracle.py", str(caught.exception))

    def test_byte_exact_report_without_independent_swap_traffic_is_rejected(self):
        page_bytes = oracle.PAGE_BYTES
        zero_counters = {
            "logical_write": 0, "physical_write": 0,
            "logical_read": 0, "physical_read": 0,
            "failed": 0, "error": 0,
        }
        fill_counters = {**zero_counters,
                         "logical_write": page_bytes, "physical_write": page_bytes}
        verify_counters = {**fill_counters,
                           "logical_read": page_bytes, "physical_read": page_bytes}
        verified = {"verified_pages": 1, "verified_bytes": page_bytes,
                    "mismatches": 0, "digest": "ab" * 32,
                    "expected_digest": "ab" * 32}
        evidence = {
            "cgroup_swap_bytes": page_bytes,
            "cgroup_swap_peak": page_bytes,
            "min_swap_bytes": page_bytes,
            "expected_verified_pages": 1,
            "oom_delta": 0, "oom_kill_delta": 0,
            "mapper_used_delta_kib": page_bytes // 1024,
            "fill_status_before": zero_counters,
            "fill_status_after": fill_counters,
            "verify_status_before": fill_counters,
            "verify_status_after": verify_counters,
            "lower_before": qualify.BlockStats(0, 0),
            "lower_after_fill": qualify.BlockStats(0, page_bytes // 512),
            "lower_before_verify": qualify.BlockStats(0, page_bytes // 512),
            "lower_after_verify": qualify.BlockStats(page_bytes // 512, page_bytes // 512),
            "vm_before": {"pswpout": 0}, "vm_after_fill": {"pswpout": 1},
            "vm_before_verify": {"pswpin": 0},
            "vm_after_verify": {"pswpin": 1},
            "oracle": verified,
        }
        qualify.evaluate_workload_evidence(**evidence)
        cases = (
            ("no cgroup occupancy", {"cgroup_swap_bytes": 0}),
            ("no swap peak", {"cgroup_swap_peak": 0}),
            ("no mapper usage", {"mapper_used_delta_kib": 0}),
            ("no target write", {"fill_status_after": zero_counters}),
            ("no lower write", {"lower_after_fill": qualify.BlockStats(0, 0)}),
            ("no vmstat swapout", {"vm_after_fill": {"pswpout": 0}}),
            ("no target read", {"verify_status_after": fill_counters}),
            ("no lower read", {"lower_after_verify": qualify.BlockStats(0, page_bytes // 512)}),
            ("no vmstat swapin", {"vm_after_verify": {"pswpin": 0}}),
            ("short oracle", {"oracle": {**verified, "verified_bytes": 0}}),
            ("corrupt oracle", {"oracle": {**verified, "mismatches": 1}}),
            ("wrong digest", {"oracle": {**verified, "digest": "cd" * 32}}),
            ("kernel OOM", {"oom_delta": 1}),
            ("target failed", {"verify_status_after": {**verify_counters, "failed": 1}}),
        )
        for description, changes in cases:
            with self.subTest(description=description), self.assertRaises(
                    qualify.QualificationFailure):
                qualify.evaluate_workload_evidence(**{**evidence, **changes})

    def test_teardown_failure_keeps_original_oracle_reason(self):
        with self.assertRaisesRegex(
                qualify.QualificationFailure,
                "phase=verify.*errno=4.*cleanup also failed.*errno=9"):
            qualify._raise_cleanup_errors(
                qualify.QualificationFailure("phase=verify errno=4"),
                ["cgroup removal errno=9"])

if __name__ == "__main__":
    unittest.main()
