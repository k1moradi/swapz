#!/usr/bin/env python3
"""Rootless terminal-evidence and interrupted-readback oracle regressions."""

import contextlib
import errno
import hashlib
import importlib.util
import io
import json
import os
import signal
from pathlib import Path
import sys
import tempfile
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
    def test_source_oracle_retains_qualification_executable_permission(self):
        self.assertTrue(
            os.access(ORACLE, os.X_OK),
            "real-swap admission rejects a non-executable source oracle")

    def run_fixture(self, *, short_read=False, interrupted=False, corrupt=False,
                    corrupt_pages=(), corrupt_offsets=(), page_count=2,
                    read_errno=None, write_errno=None, report_errno=None,
                    close_fails=False, closed_output_at=None,
                    verify_command="VERIFY", verify_read_error=None):
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
                if (self.verify_started and write_errno is not None and
                        isinstance(key, int) and key == 0):
                    raise OSError(write_errno, "synthetic page write error")
                self.contents[key] = value

            def close(self):
                if close_fails:
                    raise OSError(9, "synthetic close error")
                self.closed = True

        allocation = AnonymousMemoryFixture()
        commands = iter(("FILL", verify_command))
        command_reads = 0
        standard_output = io.StringIO()
        standard_error = io.StringIO()

        def read_command():
            nonlocal command_reads
            command_reads += 1
            if command_reads == 2 and verify_read_error is not None:
                raise verify_read_error
            command = next(commands)
            if command == "VERIFY":
                allocation.verify_started = True
                if corrupt:
                    allocation.contents[9] ^= 1
                for page_index in corrupt_pages:
                    allocation.contents[page_index * oracle.PAGE_BYTES + 9] ^= 1
                for byte_offset in corrupt_offsets:
                    allocation.contents[byte_offset] ^= 1
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

    def test_invalid_memory_size_and_page_index_fail_before_allocating(self):
        invalid_memory_sizes = ("64", 64.0, True, None, 63, 513)
        for memory_mib in invalid_memory_sizes:
            with self.subTest(memory_mib=memory_mib):
                stderr = io.StringIO()
                with mock.patch.object(oracle, "_disable_dumps") as dumps, \
                        mock.patch.object(oracle, "_emit") as emit, \
                        mock.patch.object(oracle.mmap, "mmap") as allocate, \
                        contextlib.redirect_stderr(stderr):
                    status = oracle.run_workload("ab" * 16, memory_mib)
                self.assertEqual(status, 2)
                self.assertIn("FAIL: oracle memory must be", stderr.getvalue())
                dumps.assert_not_called()
                emit.assert_not_called()
                allocate.assert_not_called()

        for page_index in (-1, True, 1.5, "1", 1 << 64):
            with self.subTest(page_index=page_index), self.assertRaisesRegex(
                    ValueError, "page index must be a 64-bit unsigned integer"):
                oracle.page_pattern("ab" * 16, page_index)
        self.assertEqual(
            len(oracle.page_pattern("ab" * 16, (1 << 64) - 1)),
            oracle.PAGE_BYTES)

    def test_early_verify_command_never_emits_terminal_success(self):
        for command in ("", "STOP"):
            with self.subTest(command=command):
                status, stdout, stderr, allocation = self.run_fixture(
                    verify_command=command)
                self.assertEqual(status, 1)
                self.assertTrue(allocation.closed)
                self.assertEqual(
                    [record.partition("=")[0] for record in stdout.splitlines()],
                    ["ORACLE_WAITING", "ORACLE_FILLED"])
                self.assertIn(
                    "phase=wait_verify verified_pages=0/2 verified_bytes=0/8192",
                    stderr)
                self.assertIn("cleanup_complete=true", stderr)
                self.assertNotIn("ORACLE_VERIFIED=", stdout)

    def test_closed_command_pipe_before_verify_never_emits_terminal_success(self):
        status, stdout, stderr, allocation = self.run_fixture(
            verify_read_error=RuntimeError(
                "qualification controller closed the command pipe"))
        self.assertEqual(status, 1)
        self.assertTrue(allocation.closed)
        self.assertEqual(
            [record.partition("=")[0] for record in stdout.splitlines()],
            ["ORACLE_WAITING", "ORACLE_FILLED"])
        self.assertIn(
            "phase=wait_verify verified_pages=0/2 verified_bytes=0/8192",
            stderr)
        self.assertIn(
            "error=RuntimeError errno=none cleanup_complete=true", stderr)
        self.assertNotIn("ORACLE_VERIFIED=", stdout)

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

    def test_detected_corruption_precedes_later_read_and_cleanup_failures(self):
        for options, subsequent_failure in (
                ({"read_errno": errno.EIO}, "[Errno 5] synthetic page read error"),
                ({"short_read": True}, "short oracle page read at page 1")):
            with self.subTest(options=options):
                status, stdout, stderr, allocation = self.run_fixture(
                    corrupt=True, close_fails=True, **options)
                self.assertEqual(status, 1)
                self.assertFalse(allocation.closed)
                self.assertEqual(
                    [line.partition("=")[0] for line in stdout.splitlines()],
                    ["ORACLE_WAITING", "ORACLE_FILLED"])
                self.assertIn(
                    "phase=verify verified_pages=1/2 verified_bytes=4096/8192",
                    stderr)
                self.assertIn(
                    "expected_page_mismatches=0 observed_page_mismatches=1",
                    stderr)
                self.assertIn(
                    "expected_byte_mismatches=0 observed_byte_mismatches=1",
                    stderr)
                self.assertIn(
                    "error=byte_mismatch errno=none cleanup_complete=false",
                    stderr)
                self.assertIn(subsequent_failure, stderr)
                self.assertIn("[Errno 9] synthetic close error", stderr)
                self.assertNotIn("ab" * 16, stderr)

    def test_detected_corruption_counts_page_before_same_page_write_failure(self):
        status, stdout, stderr, allocation = self.run_fixture(
            corrupt=True, write_errno=errno.EIO, close_fails=True)
        self.assertEqual(status, 1)
        self.assertFalse(allocation.closed)
        self.assertEqual(
            [line.partition("=")[0] for line in stdout.splitlines()],
            ["ORACLE_WAITING", "ORACLE_FILLED"])
        self.assertIn(
            "phase=verify verified_pages=1/2 verified_bytes=4096/8192",
            stderr)
        self.assertIn(
            "expected_page_mismatches=0 observed_page_mismatches=1", stderr)
        self.assertIn(
            "expected_byte_mismatches=0 observed_byte_mismatches=1", stderr)
        self.assertIn(
            "error=byte_mismatch errno=none cleanup_complete=false", stderr)
        self.assertIn("[Errno 5] synthetic page write error", stderr)
        self.assertIn("[Errno 9] synthetic close error", stderr)
        self.assertNotIn("ORACLE_VERIFIED=", stdout)
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

    def test_multi_byte_tail_corruption_is_not_hidden_by_sample_cap(self):
        sample_cap = qualify.MAX_ORACLE_MISMATCH_SAMPLES
        page_count = sample_cap + 2
        corrupt_offsets = [
            page_index * oracle.PAGE_BYTES + 9
            for page_index in range(page_count)
        ]
        corrupt_offsets.extend((
            (page_count - 1) * oracle.PAGE_BYTES + 10,
            page_count * oracle.PAGE_BYTES - 1,
        ))
        status, stdout, stderr, allocation = self.run_fixture(
            page_count=page_count, corrupt_offsets=corrupt_offsets)
        self.assertEqual(status, 1)
        self.assertTrue(allocation.closed)

        terminal_lines = [line for line in stdout.splitlines()
                          if line.startswith("ORACLE_VERIFIED=")]
        self.assertEqual(len(terminal_lines), 1)
        verified = json.loads(terminal_lines[0].split("=", 1)[1])
        self.assertEqual(verified["verified_pages"], page_count)
        self.assertEqual(
            verified["verified_bytes"], page_count * oracle.PAGE_BYTES)
        self.assertEqual(verified["mismatched_pages"], page_count)
        self.assertEqual(verified["mismatches"], page_count + 2)
        self.assertEqual(
            verified["mismatch_samples"],
            [{"page": page_index, "byte": 9}
             for page_index in range(sample_cap)])
        self.assertNotEqual(verified["digest"], verified["expected_digest"])
        qualify.require_oracle_verification_details([verified])

        self.assertIn(
            f"phase=verify verified_pages={page_count}/{page_count}", stderr)
        self.assertIn(
            f"verified_bytes={page_count * oracle.PAGE_BYTES}/"
            f"{page_count * oracle.PAGE_BYTES}", stderr)
        self.assertIn(
            f"expected_page_mismatches=0 observed_page_mismatches={page_count}",
            stderr)
        self.assertIn(
            f"expected_byte_mismatches=0 observed_byte_mismatches={page_count + 2}",
            stderr)
        self.assertIn(
            "error=byte_mismatch errno=none cleanup_complete=true", stderr)
        self.assertNotIn("ab" * 16, stderr)


    def test_dump_limit_failure_blocks_before_readiness_or_allocation(self):
        for resource_error in (
                OSError(errno.EPERM, "synthetic RLIMIT_CORE failure"),
                ValueError("synthetic invalid resource limit")):
            with self.subTest(error=type(resource_error).__name__):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with mock.patch.object(
                        oracle.resource, "setrlimit",
                        side_effect=resource_error), \
                        mock.patch.object(oracle, "_emit") as emit, \
                        mock.patch.object(oracle.mmap, "mmap") as allocate, \
                        contextlib.redirect_stdout(stdout), \
                        contextlib.redirect_stderr(stderr):
                    status = oracle.run_workload("ab" * 16, oracle.MIN_MIB)
                self.assertEqual(status, 2)
                self.assertEqual(stdout.getvalue(), "")
                self.assertIn(
                    "BLOCKED: cannot disable process dumps:", stderr.getvalue())
                self.assertIn(
                    "BLOCKED: oracle phase=preflight "
                    f"verified_pages=0/{oracle.MIN_MIB * oracle.MIB // oracle.PAGE_BYTES} "
                    f"verified_bytes=0/{oracle.MIN_MIB * oracle.MIB}",
                    stderr.getvalue())
                self.assertIn(
                    f"error={type(resource_error).__name__} "
                    f"errno={resource_error.errno if isinstance(resource_error, OSError) else 'none'} "
                    "cleanup_complete=true",
                    stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())
                self.assertNotIn("ab" * 16, stderr.getvalue())
                emit.assert_not_called()
                allocate.assert_not_called()

    def test_parent_preserves_only_structured_pre_readiness_blocked_refusal(self):
        blocked_summary = (
            "BLOCKED: oracle phase=preflight verified_pages=0/16384 "
            "verified_bytes=0/67108864 expected_page_mismatches=0 "
            "observed_page_mismatches=0 expected_byte_mismatches=0 "
            "observed_byte_mismatches=0 error=PermissionError errno=1 "
            "cleanup_complete=true"
        )
        private_traceback = (
            "Traceback (most recent call last):\n"
            '  File "/private/oracle.py", line 1, in <module>\n'
        )
        cases = (
            (2, "ORACLE_WAITING=", qualify.Blocked),
            (1, "ORACLE_WAITING=", qualify.QualificationFailure),
            (2, "ORACLE_VERIFIED=", qualify.QualificationFailure),
        )
        for return_code, prefix, error_type in cases:
            with self.subTest(
                    return_code=return_code, prefix=prefix,
                    error_type=error_type.__name__):
                read_descriptor, write_descriptor = os.pipe()
                os.close(write_descriptor)
                with os.fdopen(read_descriptor, "rb", buffering=0) as output:
                    process = mock.Mock(
                        stdout=output,
                        stderr=io.StringIO(private_traceback + blocked_summary))
                    process.poll.return_value = return_code
                    with self.assertRaises(error_type) as caught:
                        qualify._oracle_event(
                            process, prefix, qualify.time.monotonic() + 1,
                            lambda: None, bytearray())
                diagnostic = str(caught.exception)
                self.assertIn(f"child_exit={return_code}", diagnostic)
                self.assertIn("evidence_complete=false", diagnostic)
                self.assertIn("phase=preflight", diagnostic)
                self.assertIn("errno=1", diagnostic)
                self.assertNotIn("Traceback", diagnostic)
                self.assertNotIn("/private/oracle.py", diagnostic)

    def test_cgroup_migration_esrch_preserves_only_structured_preflight_block(self):
        blocked_summary = (
            "BLOCKED: oracle phase=preflight verified_pages=0/16384 "
            "verified_bytes=0/67108864 expected_page_mismatches=0 "
            "observed_page_mismatches=0 expected_byte_mismatches=0 "
            "observed_byte_mismatches=0 error=PermissionError errno=1 "
            "cleanup_complete=true"
        )
        process = mock.Mock(
            pid=41999, stdin=mock.Mock(), stdout=mock.Mock(),
            stderr=io.StringIO(blocked_summary))
        process.poll.return_value = 2

        def migration_esrch(*_args, **_kwargs):
            raise OSError(errno.ESRCH, "synthetic exited worker")

        with tempfile.TemporaryDirectory() as directory:
            cgroup = Path(directory)
            with (
                    mock.patch.multiple(
                        qualify,
                        _cgroup_create=mock.Mock(return_value=cgroup),
                        _memory_events=mock.Mock(
                            return_value={"oom": 0, "oom_kill": 0}),
                        _psi_total=mock.Mock(return_value=0),
                        _trusted_executable_path=mock.Mock(
                            return_value=sys.executable),
                        _write_control=mock.Mock(),
                        read_swap_rows=mock.Mock(return_value=[]),
                        _row_for_device=mock.Mock(
                            return_value=mock.Mock(used_kib=0)),
                        _terminate_child=mock.Mock(),
                        _close_oracle_pipes=mock.Mock(),
                        _remove_cgroup=mock.Mock()),
                    mock.patch.object(
                        qualify.subprocess, "Popen", return_value=process),
                    mock.patch.object(
                        Path, "write_text", new=migration_esrch),
            ):
                with self.assertRaisesRegex(
                        qualify.Blocked,
                        "child_exit=2.*exited before dedicated cgroup migration.*"
                        "phase=preflight.*errno=1") as caught:
                    qualify._run_workload(
                        {"run_id": "terminal-contract-run"},
                        {"mapper_device": (1, 2)},
                        ORACLE,
                        workload_mib=128,
                        resident_mib=64,
                        swap_limit_mib=128,
                        timeout_seconds=1,
                    )
        self.assertNotIn("synthetic exited worker", str(caught.exception))

    def test_readiness_guard_allows_only_exited_worker_for_blocked_classification(self):
        processes = [mock.Mock(pid=42001), mock.Mock(pid=42002)]
        for process in processes:
            process.stdin = mock.Mock()
        launched_processes = []
        ownership_exit_flags = []
        # The real admitted manifest always supplies the validated backing
        # device identity. Do not let a shortened synthetic manifest hide
        # a telemetry read failure before testing the readiness policy.
        progress_snapshot = mock.Mock(return_value={
            "cgroup_io_some_usec": None, "lower_write_sectors_total": None,
        })

        def launch_process(_arguments, **_kwargs):
            process = processes[len(launched_processes)]
            launched_processes.append(process)
            return process

        def ownership_check(_cgroup, _processes, *, allow_worker_exit=False):
            ownership_exit_flags.append(allow_worker_exit)

        def oracle_event(_process, prefix, _deadline, guard, _pending):
            self.assertEqual(prefix, "ORACLE_WAITING=")
            guard()
            raise qualify.Blocked("synthetic structured pre-readiness refusal")

        with tempfile.TemporaryDirectory() as directory:
            cgroup = Path(directory)
            with mock.patch.multiple(
                    qualify,
                    _cgroup_create=mock.Mock(return_value=cgroup),
                    _memory_events=mock.Mock(
                        return_value={"oom": 0, "oom_kill": 0}),
                    _psi_total=mock.Mock(return_value=0),
                    _trusted_executable_path=mock.Mock(
                        return_value=sys.executable),
                    _write_control=mock.Mock(),
                    _read_uint=mock.Mock(return_value=0),
                    _mem_available_mib=mock.Mock(
                        return_value=qualify.MIN_AVAILABLE_MIB),
                    _pressure_progress_snapshot=progress_snapshot,
                    require_no_cgroup_oom_events=mock.Mock(),
                    require_oracle_worker_cgroup_ownership=mock.Mock(
                        side_effect=ownership_check),
                    read_swap_rows=mock.Mock(return_value=[]),
                    _row_for_device=mock.Mock(
                        return_value=mock.Mock(used_kib=0)),
                    _oracle_event=mock.Mock(side_effect=oracle_event),
                    _terminate_child=mock.Mock(),
                    _close_oracle_pipes=mock.Mock(),
                    _remove_cgroup=mock.Mock()), \
                    mock.patch.object(
                        qualify.subprocess, "Popen", side_effect=launch_process):
                with self.assertRaisesRegex(
                        qualify.Blocked, "synthetic structured pre-readiness refusal"):
                    qualify._run_workload(
                        {
                            "run_id": "terminal-contract-run",
                            "device_major_int": 1,
                            "device_minor_int": 2,
                        },
                        {"mapper_device": (1, 2)},
                        ORACLE,
                        workload_mib=128,
                        resident_mib=64,
                        swap_limit_mib=128,
                        timeout_seconds=1,
                    )
        self.assertTrue(ownership_exit_flags)
        self.assertTrue(ownership_exit_flags[0])
        self.assertEqual(progress_snapshot.call_count, 1)
        self.assertEqual(progress_snapshot.call_args.args[2], (1, 2))

    def test_parent_stall_and_killed_child_have_no_terminal_evidence(self):
        read_descriptor, write_descriptor = os.pipe()
        try:
            with os.fdopen(read_descriptor, "rb", buffering=0) as output:
                stalled = mock.Mock(stdout=output, stderr=io.StringIO())
                stalled.poll.return_value = None
                with self.assertRaisesRegex(
                        qualify.QualificationFailure,
                        "phase=terminal child_exit=running "
                        "evidence_complete=false: timed out waiting for "
                        "ORACLE_VERIFIED="):
                    qualify._oracle_event(
                        stalled, "ORACLE_VERIFIED=",
                        qualify.time.monotonic() - 1, lambda: None, bytearray())
        finally:
            os.close(write_descriptor)

        read_descriptor, write_descriptor = os.pipe()
        os.close(write_descriptor)
        with os.fdopen(read_descriptor, "rb", buffering=0) as output:
            killed = mock.Mock(stdout=output, stderr=io.StringIO())
            killed.poll.return_value = -signal.SIGKILL
            with self.assertRaisesRegex(
                    qualify.QualificationFailure,
                    "phase=terminal child_exit=-9 "
                    "evidence_complete=false: closed output before "
                    "ORACLE_VERIFIED="):
                qualify._oracle_event(
                    killed, "ORACLE_VERIFIED=",
                    qualify.time.monotonic() + 1, lambda: None, bytearray())

    def test_parent_pipe_read_failure_preserves_errno_without_raw_error(self):
        read_descriptor, write_descriptor = os.pipe()
        try:
            os.write(write_descriptor, b"x")
            with os.fdopen(read_descriptor, "rb", buffering=0) as output:
                process = mock.Mock(stdout=output, stderr=io.StringIO())
                process.poll.return_value = None
                read_error = OSError(errno.EIO, "synthetic pipe read failure")
                with mock.patch.object(
                        qualify.os, "read", side_effect=read_error), \
                        self.assertRaisesRegex(
                            qualify.QualificationFailure,
                            "phase=terminal child_exit=running "
                            "evidence_complete=false: cannot read real-swap "
                            "oracle record errno=5") as caught:
                    qualify._oracle_event(
                        process, "ORACLE_VERIFIED=",
                        qualify.time.monotonic() + 1,
                        lambda: None, bytearray())
            self.assertIs(caught.exception.__cause__, read_error)
            self.assertNotIn(
                "synthetic pipe read failure", str(caught.exception))
        finally:
            os.close(write_descriptor)

    def test_parent_pipe_wait_failure_preserves_errno_without_raw_error(self):
        read_descriptor, write_descriptor = os.pipe()
        try:
            with os.fdopen(read_descriptor, "rb", buffering=0) as output:
                process = mock.Mock(stdout=output, stderr=io.StringIO())
                process.poll.return_value = None
                wait_error = OSError(errno.EIO, "synthetic pipe wait failure")
                with mock.patch.object(
                        qualify.select, "select", side_effect=wait_error), \
                        self.assertRaisesRegex(
                            qualify.QualificationFailure,
                            "phase=terminal child_exit=running "
                            "evidence_complete=false: cannot wait for "
                            "ORACLE_VERIFIED= errno=5") as caught:
                    qualify._oracle_event(
                        process, "ORACLE_VERIFIED=",
                        qualify.time.monotonic() + 1,
                        lambda: None, bytearray())
            self.assertIs(caught.exception.__cause__, wait_error)
            self.assertNotIn(
                "synthetic pipe wait failure", str(caught.exception))
        finally:
            os.close(write_descriptor)

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

    def test_parent_rejects_malformed_terminal_json_before_any_verdict(self):
        invalid_records = (
            (b'{"verified_pages":1,"verified_pages":1}', "malformed JSON"),
            (b'{"verified_pages":NaN}', "malformed JSON"),
            (b'{"verified_pages":1e999}', "malformed JSON"),
            (b'{"verified_pages":1,\xff}', "malformed JSON"),
            (b'[]', "not an object"),
            (b'null', "not an object"),
        )
        for record, expected_error in invalid_records:
            with self.subTest(record=record):
                read_descriptor, write_descriptor = os.pipe()
                try:
                    os.write(write_descriptor, b"ORACLE_VERIFIED=" + record + b"\n")
                    os.close(write_descriptor)
                    write_descriptor = -1
                    with os.fdopen(read_descriptor, "rb", buffering=0) as output:
                        process = mock.Mock(stdout=output)
                        process.poll.return_value = 0
                        with self.assertRaisesRegex(
                                qualify.QualificationFailure, expected_error):
                            qualify._oracle_event(
                                process, "ORACLE_VERIFIED=",
                                qualify.time.monotonic() + 1,
                                lambda: None, bytearray())
                finally:
                    if write_descriptor >= 0:
                        os.close(write_descriptor)

    def test_parent_rejects_noninteger_and_unreasonable_byte_counts(self):
        valid = {
            "verified_pages": 2,
            "verified_bytes": 2 * oracle.PAGE_BYTES,
            "mismatched_pages": 0,
            "mismatches": 0,
            "mismatch_samples": [],
        }
        for mutant in (
                {"verified_pages": True},
                {"verified_pages": "2"},
                {"verified_bytes": float(2 * oracle.PAGE_BYTES)},
                {"mismatched_pages": False},
                {"mismatches": 1 << 128},
                {"mismatch_samples": [{"page": 2, "byte": 0}]}):
            with self.subTest(mutant=mutant), self.assertRaises(
                    qualify.QualificationFailure):
                qualify.require_oracle_verification_details([{**valid, **mutant}])

        # A self-consistent arbitrary-precision total is still impossible for
        # the worker's admitted memory and must fail exact worker geometry.
        unreasonable_pages = 1 << 128
        assigned_memory_mib = 64
        assigned_bytes = assigned_memory_mib * qualify.MIB
        assigned_pages = assigned_bytes // qualify.PAGE_BYTES
        with self.assertRaisesRegex(
                qualify.QualificationFailure, "worker 0 verification"):
            qualify.require_oracle_worker_geometry(
                [
                    {
                        "verified_pages": unreasonable_pages,
                        "verified_bytes": unreasonable_pages * qualify.PAGE_BYTES,
                    },
                    {
                        "verified_pages": assigned_pages,
                        "verified_bytes": assigned_bytes,
                    },
                ],
                (assigned_memory_mib, assigned_memory_mib),
                "verified_pages", "verified_bytes", "verification")

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


    def run_readiness_identity_fixture(self, identity_mutation):
        process_ids = (41001, 41002)
        worker_memory_mib = (64, 64)
        processes = []
        for process_id in process_ids:
            process = mock.Mock()
            process.pid = process_id
            process.stdin = mock.Mock()
            processes.append(process)

        launched_processes = []
        worker_seed_by_pid = {}
        cleanup_events = []

        def launch_process(arguments, **_kwargs):
            process = processes[len(launched_processes)]
            seed_argument_index = arguments.index("--seed") + 1
            worker_seed_by_pid[process.pid] = arguments[seed_argument_index]
            launched_processes.append(process)
            return process

        def oracle_event(process, prefix, _deadline, _guard, _pending):
            self.assertEqual(prefix, "ORACLE_WAITING=")
            worker_index = process_ids.index(process.pid)
            expected_bytes = worker_memory_mib[worker_index] * qualify.MIB
            record = {
                "pid": process.pid,
                "seed": worker_seed_by_pid[process.pid],
                "pages": expected_bytes // qualify.PAGE_BYTES,
                "bytes": expected_bytes,
            }
            if worker_index == 1 and identity_mutation == "duplicate_pid":
                record["pid"] = process_ids[0]
            elif worker_index == 1 and identity_mutation == "wrong_seed":
                record["seed"] = "forged-seed"
            return record

        with tempfile.TemporaryDirectory() as directory:
            cgroup = Path(directory)
            with mock.patch.multiple(
                    qualify,
                    _cgroup_create=mock.Mock(return_value=cgroup),
                    _memory_events=mock.Mock(
                        return_value={"oom": 0, "oom_kill": 0}),
                    _psi_total=mock.Mock(return_value=0),
                    _trusted_executable_path=mock.Mock(
                        return_value=sys.executable),
                    _write_control=mock.Mock(),
                    read_swap_rows=mock.Mock(return_value=[]),
                    _row_for_device=mock.Mock(
                        return_value=mock.Mock(used_kib=0)),
                    _oracle_event=mock.Mock(side_effect=oracle_event),
                    _terminate_child=mock.Mock(
                        side_effect=lambda process, _cgroup:
                            cleanup_events.append(("terminate", process.pid))),
                    _close_oracle_pipes=mock.Mock(
                        side_effect=lambda process:
                            cleanup_events.append(("close", process.pid))),
                    _remove_cgroup=mock.Mock(
                        side_effect=lambda _cgroup:
                            cleanup_events.append(("remove_cgroup", None)))), \
                    mock.patch.object(
                        qualify.subprocess, "Popen", side_effect=launch_process):
                try:
                    qualify._run_workload(
                        {"run_id": "terminal-contract-run"},
                        {"mapper_device": (1, 2)},
                        ORACLE,
                        workload_mib=sum(worker_memory_mib),
                        resident_mib=64,
                        swap_limit_mib=sum(worker_memory_mib),
                        timeout_seconds=1,
                    )
                except qualify.QualificationFailure as error:
                    return error, cleanup_events, process_ids
        self.fail("forged worker identity unexpectedly passed readiness")

    def test_parent_requires_each_workers_readiness_and_verification_geometry(self):
        worker_memory_mib = (64, 96)
        readiness = []
        verification = []
        for memory_mib in worker_memory_mib:
            expected_bytes = memory_mib * qualify.MIB
            expected_pages = expected_bytes // qualify.PAGE_BYTES
            readiness.append({"pages": expected_pages, "bytes": expected_bytes})
            verification.append({
                "verified_pages": expected_pages,
                "verified_bytes": expected_bytes,
            })

        qualify.require_oracle_worker_geometry(
            readiness, worker_memory_mib, "pages", "bytes", "readiness")
        qualify.require_oracle_worker_geometry(
            verification, worker_memory_mib,
            "verified_pages", "verified_bytes", "verification")

        compensated = [
            {
                "pages": readiness[0]["pages"] + 1,
                "bytes": readiness[0]["bytes"] + qualify.PAGE_BYTES,
            },
            {
                "pages": readiness[1]["pages"] - 1,
                "bytes": readiness[1]["bytes"] - qualify.PAGE_BYTES,
            },
        ]
        cases = (
            (
                "missing worker", readiness[:1], "pages", "bytes",
                "readiness", "record count is incomplete",
            ),
            (
                "aggregate compensation", compensated, "pages", "bytes",
                "readiness", "worker 0 readiness",
            ),
            (
                "worker one verification bytes",
                [
                    verification[0],
                    {
                        **verification[1],
                        "verified_bytes":
                            verification[1]["verified_bytes"] -
                            qualify.PAGE_BYTES,
                    },
                ],
                "verified_pages", "verified_bytes", "verification",
                "worker 1 verification",
            ),
        )
        for (description, records, page_field, byte_field,
             phase, expected_error) in cases:
            with self.subTest(description=description), self.assertRaisesRegex(
                    qualify.QualificationFailure, expected_error):
                qualify.require_oracle_worker_geometry(
                    records, worker_memory_mib, page_field, byte_field, phase)

    def test_parent_aggregates_full_expected_and_observed_worker_digests(self):
        records = (
            {
                "verified_pages": 2,
                "verified_bytes": 2 * qualify.PAGE_BYTES,
                "mismatches": 0,
                "digest": "01" * 32,
                "expected_digest": "11" * 32,
            },
            {
                "verified_pages": 3,
                "verified_bytes": 3 * qualify.PAGE_BYTES,
                "mismatches": 0,
                "digest": "02" * 32,
                "expected_digest": "22" * 32,
            },
        )
        aggregate = qualify.aggregate_oracle_verification(list(records))

        observed_digest = hashlib.sha256(
            b"".join(bytes.fromhex(record["digest"]) for record in records)
        ).hexdigest()
        expected_digest = hashlib.sha256(
            b"".join(
                bytes.fromhex(record["expected_digest"]) for record in records)
        ).hexdigest()
        self.assertEqual(aggregate["verified_pages"], 5)
        self.assertEqual(
            aggregate["verified_bytes"], 5 * qualify.PAGE_BYTES)
        self.assertEqual(aggregate["mismatches"], 0)
        self.assertEqual(aggregate["digest"], observed_digest)
        self.assertEqual(aggregate["expected_digest"], expected_digest)
        self.assertNotEqual(aggregate["digest"], aggregate["expected_digest"])

    def test_parent_requires_two_complete_reuse_rounds(self):
        complete_round = {
            "concurrent_workers": qualify.CONCURRENT_ORACLE_PROCESSES,
            "mapper_used_start_kib": 0,
            "mapper_used_delta_kib": 1,
            "release_swap_current_bytes": 0,
            "mapper_used_released_kib": 0,
        }
        with self.assertRaisesRegex(
                qualify.QualificationFailure,
                "did not complete repeated slot-reuse rounds"):
            qualify.evaluate_reuse_rounds([complete_round])

        result = qualify.evaluate_reuse_rounds([
            dict(complete_round) for _ in range(qualify.REUSE_ROUNDS)
        ])
        self.assertEqual(result["rounds"], qualify.REUSE_ROUNDS)
        self.assertEqual(
            result["concurrent_workers"], qualify.CONCURRENT_ORACLE_PROCESSES)
        self.assertTrue(result["slot_reuse_proven"])

        failed_worker_rounds = [
            dict(complete_round) for _ in range(qualify.REUSE_ROUNDS)
        ]
        failed_worker_rounds[1]["concurrent_workers"] = (
            qualify.CONCURRENT_ORACLE_PROCESSES - 1)
        with self.assertRaisesRegex(
                qualify.QualificationFailure,
                "lacked concurrent test-process activity"):
            qualify.evaluate_reuse_rounds(failed_worker_rounds)

    def test_parent_binds_worker_pid_and_seed_before_fill_and_cleans_up(self):
        for identity_mutation in ("duplicate_pid", "wrong_seed"):
            with self.subTest(identity_mutation=identity_mutation):
                error, cleanup_events, process_ids = (
                    self.run_readiness_identity_fixture(identity_mutation))
                self.assertIn(
                    "readiness PID/seed identities differ", str(error))
                self.assertNotIn("forged-seed", str(error))
                self.assertEqual(
                    cleanup_events,
                    [
                        ("terminate", process_ids[0]),
                        ("close", process_ids[0]),
                        ("terminate", process_ids[1]),
                        ("close", process_ids[1]),
                        ("remove_cgroup", None),
                    ],
                )

    def test_parent_rejects_one_failed_worker_after_valid_verified_records(self):
        verified_record = {
            "verified_pages": 1,
            "verified_bytes": qualify.PAGE_BYTES,
            "mismatched_pages": 0,
            "mismatches": 0,
            "mismatch_samples": [],
            "digest": "ab" * 32,
            "expected_digest": "ab" * 32,
        }
        outputs = []
        processes = []
        pending_buffers = []
        try:
            for exit_code in (0, 7):
                read_descriptor, write_descriptor = os.pipe()
                payload = (
                    "ORACLE_VERIFIED=" +
                    json.dumps(
                        verified_record, sort_keys=True, separators=(",", ":")) +
                    "\n"
                ).encode("ascii")
                os.write(write_descriptor, payload)
                os.close(write_descriptor)
                output = os.fdopen(read_descriptor, "rb", buffering=0)
                outputs.append(output)
                process = mock.Mock(stdout=output, stderr=io.StringIO())
                process.poll.return_value = None
                process.wait.return_value = exit_code
                processes.append(process)
                pending_buffers.append(bytearray())

            parsed = [
                qualify._oracle_event(
                    process, "ORACLE_VERIFIED=",
                    qualify.time.monotonic() + 1,
                    lambda: None, pending)
                for process, pending in zip(processes, pending_buffers)
            ]
            self.assertEqual(parsed, [verified_record, verified_record])
            qualify.require_oracle_verification_details(parsed)

            qualify._require_oracle_terminal_exit(
                processes[0], qualify.time.monotonic() + 1,
                lambda: None, pending_buffers[0])
            with self.assertRaisesRegex(
                    qualify.QualificationFailure,
                    "phase=terminal.*child_exit=7.*evidence_complete=false"):
                qualify._require_oracle_terminal_exit(
                    processes[1], qualify.time.monotonic() + 1,
                    lambda: None, pending_buffers[1])
        finally:
            for output in outputs:
                output.close()

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
            ("no cgroup occupancy", {"cgroup_swap_bytes": 0},
             "bounded cgroup never accumulated required real swap usage"),
            ("no swap peak", {"cgroup_swap_peak": 0},
             "bounded cgroup never accumulated required real swap usage"),
            ("no mapper usage", {"mapper_used_delta_kib": 0},
             "exact mapper /proc/swaps usage stayed below required real-swap floor"),
            ("no target write", {"fill_status_after": zero_counters},
             "swapz target counters stay below required swap-out WRITE activity"),
            ("no lower write", {"lower_after_fill": qualify.BlockStats(0, 0)},
             "backing partition counters show no lower WRITE activity"),
            ("undercovered lower write", {
                "lower_after_fill": qualify.BlockStats(0, 1)},
             "backing partition WRITE counters do not cover swapz target physical WRITE bytes"),
            ("no vmstat swapout", {"vm_after_fill": {"pswpout": 0}},
             "kernel vmstat shows no swap-out during admitted workload"),
            ("no target read", {"verify_status_after": fill_counters},
             "swapz target counters stay below required swap-in READ activity"),
            ("no lower read", {
                "lower_after_verify": qualify.BlockStats(0, page_bytes // 512)},
             "backing partition counters show no lower READ activity"),
            ("undercovered lower read", {
                "lower_after_verify": qualify.BlockStats(1, page_bytes // 512)},
             "backing partition READ counters do not cover swapz target physical READ bytes"),
            ("no vmstat swapin", {"vm_after_verify": {"pswpin": 0}},
             "kernel vmstat shows no swap-in during byte verification"),
            ("short oracle", {"oracle": {**verified, "verified_bytes": 0}},
             "real-swap byte oracle reported corruption or incomplete verification"),
            ("corrupt oracle", {"oracle": {**verified, "mismatches": 1}},
             "real-swap byte oracle reported corruption or incomplete verification"),
            ("wrong digest", {"oracle": {**verified, "digest": "cd" * 32}},
             "real-swap byte oracle reported corruption or incomplete verification"),
            ("kernel OOM", {"oom_delta": 1},
             "bounded real-swap workload encountered cgroup OOM"),
            ("target failed", {
                "verify_status_after": {**verify_counters, "failed": 1}},
             "swapz target entered failed state during real-swap workload"),
        )
        for description, changes, first_failure in cases:
            with self.subTest(description=description):
                with self.assertRaises(qualify.QualificationFailure) as caught:
                    qualify.evaluate_workload_evidence(**{**evidence, **changes})
                self.assertEqual(str(caught.exception), first_failure)

        precedence_cases = (
            (
                "cgroup before OOM",
                {"cgroup_swap_bytes": 0, "oom_delta": 1},
                "bounded cgroup never accumulated required real swap usage",
            ),
            (
                "OOM before mapper",
                {"oom_delta": 1, "mapper_used_delta_kib": 0},
                "bounded real-swap workload encountered cgroup OOM",
            ),
            (
                "mapper before target write",
                {"mapper_used_delta_kib": 0, "fill_status_after": zero_counters},
                "exact mapper /proc/swaps usage stayed below required real-swap floor",
            ),
            (
                "target write before lower write",
                {
                    "fill_status_after": zero_counters,
                    "lower_after_fill": qualify.BlockStats(0, 0),
                },
                "swapz target counters stay below required swap-out WRITE activity",
            ),
            (
                "kernel swap-out before target read",
                {
                    "vm_after_fill": {"pswpout": 0},
                    "verify_status_after": fill_counters,
                },
                "kernel vmstat shows no swap-out during admitted workload",
            ),
            (
                "target read before lower read",
                {
                    "verify_status_after": fill_counters,
                    "lower_after_verify":
                        qualify.BlockStats(0, page_bytes // 512),
                },
                "swapz target counters stay below required swap-in READ activity",
            ),
            (
                "kernel swap-in before byte oracle",
                {
                    "vm_after_verify": {"pswpin": 0},
                    "oracle": {**verified, "digest": "cd" * 32},
                },
                "kernel vmstat shows no swap-in during byte verification",
            ),
        )
        for description, changes, first_failure in precedence_cases:
            with self.subTest(description=description):
                with self.assertRaises(qualify.QualificationFailure) as caught:
                    qualify.evaluate_workload_evidence(**{**evidence, **changes})
                self.assertEqual(str(caught.exception), first_failure)

    def test_teardown_failure_keeps_original_oracle_reason(self):
        with self.assertRaisesRegex(
                qualify.QualificationFailure,
                "phase=verify.*errno=4.*cleanup also failed.*errno=9"):
            qualify._raise_cleanup_errors(
                qualify.QualificationFailure("phase=verify errno=4"),
                ["cgroup removal errno=9"])

if __name__ == "__main__":
    unittest.main()
