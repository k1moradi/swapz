#!/usr/bin/env python3
"""Rootless lifecycle and failure-injection tests for the pidfd prototype."""

from __future__ import annotations

import errno
import importlib.util
import os
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
MODULE_PATH = Path(__file__).with_name("test-child-supervisor.py")
SPEC = importlib.util.spec_from_file_location("test_child_supervisor", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not import supervisor prototype")
supervisor_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = supervisor_module
SPEC.loader.exec_module(supervisor_module)

GatedPidfdSupervisor = supervisor_module.GatedPidfdSupervisor
LinuxPidfdOps = supervisor_module.LinuxPidfdOps
PidfdUnavailable = supervisor_module.PidfdUnavailable
SupervisorError = supervisor_module.SupervisorError
Worker = supervisor_module.Worker


class RecordingOps(LinuxPidfdOps):
    def __init__(self) -> None:
        self.parent_pid = os.getpid()
        self.events: list[tuple[object, ...]] = []
        self.last_pidfd: int | None = None

    def pidfd_open(self, pid: int) -> int:
        fd = super().pidfd_open(pid)
        self.last_pidfd = fd
        self.events.append(("pidfd_open", fd))
        return fd

    def write(self, fd: int, data: bytes) -> int:
        result = super().write(fd, data)
        if os.getpid() == self.parent_pid and data == b"G":
            self.events.append(("gate_release", fd))
        return result

    def pidfd_send_signal(self, pidfd: int, sig: int) -> None:
        self.events.append(("signal", pidfd, sig))
        super().pidfd_send_signal(pidfd, sig)


class FaultOps(RecordingOps):
    def __init__(
        self,
        *,
        fail_pipe_at: int | None = None,
        fail_fork: bool = False,
        pidfd_error: int | None = None,
        fail_gate_start: bool = False,
        kill_after_gate: bool = False,
        wait_for_exit_before_ready: bool = False,
        fail_exec_wait: bool = False,
    ) -> None:
        super().__init__()
        self.pipe_count = 0
        self.fail_pipe_at = fail_pipe_at
        self.fail_fork = fail_fork
        self.pidfd_error = pidfd_error
        self.fail_gate_start = fail_gate_start
        self.kill_after_gate = kill_after_gate
        self.wait_for_exit_before_ready = wait_for_exit_before_ready
        self.fail_exec_wait = fail_exec_wait
        self.gate_writes: list[bytes] = []

    def pipe(self) -> tuple[int, int]:
        self.pipe_count += 1
        if self.pipe_count == self.fail_pipe_at:
            raise OSError(errno.EMFILE, "injected pipe creation failure")
        return super().pipe()

    def fork(self) -> int:
        if self.fail_fork:
            raise OSError(errno.EAGAIN, "injected fork failure")
        return super().fork()

    def pidfd_open(self, pid: int) -> int:
        if self.pidfd_error is not None:
            raise OSError(self.pidfd_error, os.strerror(self.pidfd_error))
        return super().pidfd_open(pid)

    def write(self, fd: int, data: bytes) -> int:
        if os.getpid() == self.parent_pid:
            self.gate_writes.append(data)
            if data == b"G" and self.fail_gate_start:
                raise OSError(errno.EIO, "injected gate delivery failure")
        result = super().write(fd, data)
        if os.getpid() == self.parent_pid and data == b"G" and self.kill_after_gate:
            assert self.last_pidfd is not None
            self.events.append(("injected_child_kill", self.last_pidfd))
            # This pidfd targets only the direct child created by this test.
            LinuxPidfdOps.pidfd_send_signal(self, self.last_pidfd, signal.SIGKILL)
        return result

    def wait_for_exec(self, error_fd: int, pidfd: int, timeout: float) -> tuple[str, bytes]:
        if self.fail_exec_wait:
            raise OSError(errno.EIO, "injected READY inspection failure")
        if self.wait_for_exit_before_ready:
            deadline = time.monotonic() + timeout
            while not self.pidfd_exited(pidfd) and time.monotonic() < deadline:
                self.poll(pidfd, 10)
            if not self.pidfd_exited(pidfd):
                raise TimeoutError("injected child did not exit before READY")
        return super().wait_for_exec(error_fd, pidfd, timeout)


class FakeProcess:
    def __init__(self, pid: int, token: str, status: int = 0) -> None:
        self.pid = pid
        self.token = token
        self.exited = False
        self.reaped = False
        self.status = status
        self.term_exits = True
        self.kill_exits = True
        self.signal_errors: set[int] = set()
        self.wait_error = False
        self.close_count = 0
        self.close_error = False


class FakePidfdOps:
    """A syscall-level model; it never delivers a host process signal."""

    def __init__(self) -> None:
        self.by_fd: dict[int, FakeProcess] = {}
        self.by_pid: dict[int, FakeProcess] = {}
        self.current_pid_owner: dict[int, str] = {}
        self.signal_log: list[tuple[int, int, str]] = []
        self.numeric_signal_calls = 0
        self.closed_fds: list[int] = []
        self.lifecycle_events: list[tuple[str, int]] = []

    def add(self, pid: int, fd: int, token: str, *, status: int = 0) -> FakeProcess:
        process = FakeProcess(pid, token, status)
        self.by_fd[fd] = process
        self.by_pid[pid] = process
        self.current_pid_owner[pid] = token
        return process

    def pidfd_api_available(self) -> bool:
        return True

    def pidfd_exited(self, pidfd: int) -> bool:
        return self.by_fd[pidfd].exited

    def pidfd_send_signal(self, pidfd: int, sig: int) -> None:
        process = self.by_fd[pidfd]
        if sig in process.signal_errors:
            raise OSError(errno.EPERM, "injected pidfd signal failure")
        if process.exited:
            raise ProcessLookupError(errno.ESRCH, "original process exited")
        self.signal_log.append((pidfd, sig, process.token))
        if sig == signal.SIGTERM and process.term_exits:
            process.exited = True
        if sig == signal.SIGKILL and process.kill_exits:
            process.exited = True

    def wait_reap(self, pid: int, pidfd: int, timeout: float) -> int | None:
        process = self.by_fd[pidfd]
        if process.wait_error:
            raise OSError(errno.ECHILD, "injected wait/reap failure")
        if process.exited and not process.reaped:
            process.reaped = True
            self.lifecycle_events.append(("reaped", pidfd))
            return process.status
        return None

    def close(self, fd: int) -> None:
        self.closed_fds.append(fd)
        if fd in self.by_fd:
            self.by_fd[fd].close_count += 1
            self.lifecycle_events.append(("closed", fd))
            if self.by_fd[fd].close_error:
                raise OSError(errno.EIO, "injected pidfd close failure")


def make_fake_supervisor(
    ops: FakePidfdOps,
    rows: list[tuple[str, int, int]],
) -> tuple[GatedPidfdSupervisor, list[str]]:
    supervisor = GatedPidfdSupervisor(ops=ops, term_grace=0, kill_grace=0)
    handles: list[str] = []
    for token, pid, fd in rows:
        handle = f"opaque-{token}"
        ops.add(pid, fd, token)
        supervisor._workers[handle] = Worker(handle=handle, pid=pid, pidfd=fd)
        handles.append(handle)
    return supervisor, handles


def process_state(pid: int) -> str | None:
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return None
    return text.rsplit(")", 1)[1].split()[0]


def wait_for_state(pid: int, expected: str, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process_state(pid) == expected:
            return True
        time.sleep(0.005)
    return False


def wait_for_file(path: Path, timeout: float = 2.0) -> bool:
    """Wait for worker code; READY only confirms the exec handshake."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.005)
    return path.exists()


def worker_command(code: str) -> tuple[str, ...]:
    return (sys.executable, "-c", code)


class SupervisorRootlessTests(unittest.TestCase):
    def cleanup_test_worker(self, supervisor: GatedPidfdSupervisor, handle: str) -> None:
        report = supervisor.stop_all([handle])
        self.assertTrue(report.all_reaped, f"test worker could not be reaped: {report}")

    def test_identity_precedes_gate_and_ready(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swapz-pidfd-") as tmp:
            marker = Path(tmp) / "worker-ran"
            class CheckGateOrderingOps(RecordingOps):
                def pidfd_open(self, pid: int) -> int:
                    self.assert_worker_not_run = not marker.exists()
                    return super().pidfd_open(pid)

            ops = CheckGateOrderingOps()
            supervisor = GatedPidfdSupervisor(ops=ops)
            code = (
                "from pathlib import Path; import time; "
                f"Path({str(marker)!r}).write_text('ran'); "
                "time.sleep(3)"
            )
            handle = supervisor.launch(worker_command(code))
            self.addCleanup(self.cleanup_test_worker, supervisor, handle)
            self.assertIsInstance(handle, str)
            self.assertFalse(handle.isdecimal(), "public handle must not be a PID")
            self.assertTrue(wait_for_file(marker), "worker did not run after READY")
            names = [event[0] for event in ops.events]
            self.assertLess(names.index("pidfd_open"), names.index("gate_release"))
            self.assertTrue(ops.assert_worker_not_run,
                            "pidfd must be acquired before worker code runs")
            opened = next(event for event in ops.events if event[0] == "pidfd_open")
            self.assertEqual(opened[1], ops.last_pidfd)
            report = supervisor.stop_all([handle])
            self.assertTrue(report.all_reaped)
            self.assertEqual([event[2] for event in ops.events if event[0] == "signal"],
                             [signal.SIGCONT, signal.SIGTERM])
            signals = [event for event in ops.events if event[0] == "signal"]
            self.assertEqual({event[1] for event in signals}, {opened[1]})
            self.assertEqual(supervisor.worker_for_test(handle).close_attempted, True)

    def test_explicit_exec_and_pass_fds_are_pinned_and_parent_stays_cloexec(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.bin"
            source.write_bytes(b"pinned-source")
            source_fd = os.open(source, os.O_RDONLY | os.O_CLOEXEC)
            unpassed_fd = os.open(source, os.O_RDONLY | os.O_CLOEXEC)
            executable_fd = os.open(sys.executable, os.O_RDONLY | os.O_CLOEXEC)
            try:
                # Simulate an unrelated inheritable descriptor in the service.
                # Strict direct mode must close it in the worker child only.
                os.set_inheritable(unpassed_fd, True)
                code = (
                    "import os,sys,time; "
                    "fd=int(sys.argv[1]); other=int(sys.argv[2]); "
                    "data=os.read(fd,64); time.sleep(.05); "
                    "ok=data==b'pinned-source'; "
                    "exec(\"try: os.fstat(other); ok=False\\nexcept OSError: pass\"); "
                    "raise SystemExit(0 if ok else 9)"
                )
                supervisor = GatedPidfdSupervisor(term_grace=.2, kill_grace=.2)
                handle = supervisor.launch(
                    ("pinned-python", "-c", code, str(source_fd), str(unpassed_fd)),
                    executable=f"/proc/self/fd/{executable_fd}",
                    executable_fd=executable_fd,
                    pass_fds=(source_fd,),
                    strict_fds=True,
                )
                self.assertFalse(os.get_inheritable(source_fd))
                self.assertTrue(os.get_inheritable(unpassed_fd),
                                "fork-child isolation must not mutate parent fd flags")
                self.assertFalse(os.get_inheritable(executable_fd))
                result = supervisor.wait(handle, 3.0)
                self.assertTrue(result.reaped)
                self.assertEqual(result.exit_code, 0, result.errors)
                self.assertFalse(result.errors)
            finally:
                os.set_inheritable(unpassed_fd, False)
                os.close(source_fd)
                os.close(unpassed_fd)
                os.close(executable_fd)

    def test_invalid_pass_fds_fail_before_pipe_or_child_creation(self) -> None:
        ops = FaultOps()
        supervisor = GatedPidfdSupervisor(ops=ops)
        with tempfile.TemporaryFile() as handle:
            fd = handle.fileno()
            os.set_inheritable(fd, True)
            with self.assertRaisesRegex(ValueError, "close-on-exec"):
                supervisor.launch((sys.executable, "-c", "pass"), pass_fds=(fd,))
            os.set_inheritable(fd, False)
            with self.assertRaisesRegex(ValueError, "duplicates"):
                supervisor.launch((sys.executable, "-c", "pass"), pass_fds=(fd, fd))
            with self.assertRaisesRegex(ValueError, "nonnegative integer"):
                supervisor.launch((sys.executable, "-c", "pass"), pass_fds=(True,))
        self.assertEqual(ops.pipe_count, 0)

    def test_stopped_child_gets_cont_then_term_through_one_pidfd(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swapz-pidfd-stopped-") as tmp:
            marker = Path(tmp) / "stopped"
            ops = RecordingOps()
            supervisor = GatedPidfdSupervisor(ops=ops)
            code = (
                "import os, signal; from pathlib import Path; "
                f"Path({str(marker)!r}).write_text('ready'); "
                "os.kill(os.getpid(), signal.SIGSTOP)"
            )
            handle = supervisor.launch(worker_command(code))
            self.addCleanup(self.cleanup_test_worker, supervisor, handle)
            worker = supervisor.worker_for_test(handle)
            self.assertTrue(wait_for_file(marker))
            self.assertTrue(wait_for_state(worker.pid, "T"), "worker did not self-stop")
            report = supervisor.stop_all([handle])
            self.assertTrue(report.all_reaped)
            signals = [event for event in ops.events if event[0] == "signal"]
            self.assertEqual([event[2] for event in signals], [signal.SIGCONT, signal.SIGTERM])
            self.assertEqual(len({event[1] for event in signals}), 1)
            self.assertEqual(report.results[0].exit_code, 128 + signal.SIGTERM)

    def test_already_exited_worker_is_reaped_without_signal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swapz-pidfd-exit-") as tmp:
            marker = Path(tmp) / "exit"
            ops = RecordingOps()
            supervisor = GatedPidfdSupervisor(ops=ops)
            code = (
                "import sys, time; from pathlib import Path; "
                f"Path({str(marker)!r}).write_text('ready'); "
                "time.sleep(0.05); sys.exit(0)"
            )
            handle = supervisor.launch(worker_command(code))
            self.addCleanup(self.cleanup_test_worker, supervisor, handle)
            self.assertTrue(wait_for_file(marker))
            result = supervisor.wait(handle, 2.0)
            self.assertTrue(result.reaped)
            self.assertEqual(result.exit_code, 0)
            report = supervisor.stop_all([handle])
            self.assertTrue(report.cleanup_allowed)
            self.assertFalse([event for event in ops.events if event[0] == "signal"])
            worker = supervisor.worker_for_test(handle)
            self.assertTrue(worker.close_attempted)

    def test_worker_nonzero_exit_is_reported(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swapz-pidfd-nonzero-") as tmp:
            marker = Path(tmp) / "exit-seven"
            supervisor = GatedPidfdSupervisor()
            code = (
                "import sys, time; from pathlib import Path; "
                f"Path({str(marker)!r}).write_text('ready'); "
                "time.sleep(0.05); sys.exit(7)"
            )
            handle = supervisor.launch(worker_command(code))
            self.addCleanup(self.cleanup_test_worker, supervisor, handle)
            self.assertTrue(wait_for_file(marker))
            result = supervisor.wait(handle, 2.0)
            self.assertTrue(result.reaped)
            self.assertEqual(result.exit_code, 7)
            self.assertFalse(result.worker_succeeded)

    def test_worker_exception_exit_is_reported(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swapz-pidfd-exception-") as tmp:
            marker = Path(tmp) / "exception"
            supervisor = GatedPidfdSupervisor()
            code = (
                "import time; from pathlib import Path; "
                f"Path({str(marker)!r}).write_text('ready'); "
                "time.sleep(0.05); raise RuntimeError('intentional worker error')"
            )
            handle = supervisor.launch(worker_command(code))
            self.addCleanup(self.cleanup_test_worker, supervisor, handle)
            self.assertTrue(wait_for_file(marker))
            result = supervisor.wait(handle, 2.0)
            self.assertTrue(result.reaped)
            self.assertNotEqual(result.exit_code, 0)
            self.assertFalse(result.worker_succeeded)

    def test_exec_failure_is_reaped_and_never_returns_ready(self) -> None:
        supervisor = GatedPidfdSupervisor()
        with self.assertRaises(SupervisorError) as caught:
            supervisor.launch(("/definitely/not/a/swapz-worker",))
        error = caught.exception
        self.assertFalse(error.preserve_required)
        self.assertIsNotNone(error.handle)
        self.assertTrue(error.child_reaped)
        worker = supervisor.worker_for_test(error.handle)
        self.assertTrue(worker.reaped)
        self.assertTrue(any("startup failed" in item for item in worker.errors))

    def test_unexpected_exit_after_gate_but_before_ready_is_reaped(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swapz-pidfd-before-ready-") as tmp:
            marker = Path(tmp) / "must-not-run"
            ops = FaultOps(kill_after_gate=True, wait_for_exit_before_ready=True)
            supervisor = GatedPidfdSupervisor(ops=ops)
            release = Path(tmp) / "never-released"
            code = (
                "import time\nfrom pathlib import Path\n"
                f"release=Path({str(release)!r})\nmarker=Path({str(marker)!r})\n"
                "deadline=time.monotonic()+3\n"
                "while not release.exists() and time.monotonic()<deadline:\n"
                "    time.sleep(.005)\n"
                "marker.write_text('ran')"
            )
            with self.assertRaises(SupervisorError) as caught:
                supervisor.launch(worker_command(code))
            self.assertFalse(caught.exception.preserve_required)
            self.assertTrue(caught.exception.child_reaped)
            self.assertFalse(marker.exists())
            self.assertEqual(ops.gate_writes, [b"G"])
            self.assertTrue(any(event[0] == "injected_child_kill" for event in ops.events))

    def test_child_creation_and_partial_gate_creation_fail_closed(self) -> None:
        for ops in (FaultOps(fail_pipe_at=1), FaultOps(fail_pipe_at=2), FaultOps(fail_fork=True)):
            with self.subTest(ops=ops):
                supervisor = GatedPidfdSupervisor(ops=ops)
                with self.assertRaises(SupervisorError) as caught:
                    supervisor.launch(worker_command("pass"))
                self.assertFalse(caught.exception.preserve_required)
                self.assertEqual(ops.gate_writes, [])

    def test_handle_factory_failure_happens_before_child_creation(self) -> None:
        ops = FaultOps()
        supervisor = GatedPidfdSupervisor(
            ops=ops, token_factory=lambda: (_ for _ in ()).throw(OSError(errno.EIO, "entropy"))
        )
        with self.assertRaises(SupervisorError) as caught:
            supervisor.launch(worker_command("pass"))
        self.assertFalse(caught.exception.preserve_required)
        self.assertEqual(ops.pipe_count, 0)
        self.assertEqual(ops.events, [])

        duplicate = GatedPidfdSupervisor(ops=ops, token_factory=lambda: "opaque")
        duplicate._workers["opaque"] = Worker(handle="opaque", pid=1, pidfd=None)
        with self.assertRaises(SupervisorError):
            duplicate.launch(worker_command("pass"))
        self.assertEqual(ops.pipe_count, 0)

    def test_supervisor_grace_and_startup_timeouts_must_be_finite(self) -> None:
        for kwargs in (
            {"startup_timeout": float("nan")},
            {"startup_timeout": float("inf")},
            {"term_grace": float("nan")},
            {"kill_grace": float("inf")},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    GatedPidfdSupervisor(**kwargs)

    def test_supervisor_refuses_nondefault_sigchld_or_nonmain_thread(self) -> None:
        ops = FaultOps()
        supervisor = GatedPidfdSupervisor(ops=ops)
        with patch.object(supervisor_module.signal, "getsignal", return_value=signal.SIG_IGN):
            with self.assertRaises(PidfdUnavailable):
                supervisor.launch(worker_command("pass"))
        self.assertEqual(ops.pipe_count, 0)

        with patch.object(supervisor_module.threading, "current_thread", return_value=object()):
            with self.assertRaises(PidfdUnavailable):
                supervisor.launch(worker_command("pass"))
        self.assertEqual(ops.pipe_count, 0)

    def test_pidfd_api_missing_or_acquisition_errors_never_release_gate(self) -> None:
        class NoPidfdOps(RecordingOps):
            def pidfd_api_available(self) -> bool:
                return False

            def fork(self) -> int:
                raise AssertionError("fork must not happen without pidfd API")

        supervisor = GatedPidfdSupervisor(ops=NoPidfdOps())
        with self.assertRaises(PidfdUnavailable) as caught:
            supervisor.launch(worker_command("pass"))
        self.assertFalse(caught.exception.preserve_required)

        for code in (errno.ENOSYS, errno.EPERM, errno.EMFILE):
            with self.subTest(errno=code):
                ops = FaultOps(pidfd_error=code)
                supervisor = GatedPidfdSupervisor(ops=ops)
                with self.assertRaises(PidfdUnavailable) as caught:
                    supervisor.launch(worker_command("raise SystemExit(91)"))
                self.assertFalse(caught.exception.preserve_required)
                self.assertTrue(caught.exception.child_reaped)
                self.assertNotIn(b"G", ops.gate_writes)
                self.assertIn(b"A", ops.gate_writes)

    def test_gate_delivery_failure_aborts_and_reaps_without_running_worker(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swapz-pidfd-gate-fail-") as tmp:
            marker = Path(tmp) / "must-not-run"
            ops = FaultOps(fail_gate_start=True)
            supervisor = GatedPidfdSupervisor(ops=ops)
            code = f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')"
            with self.assertRaises(SupervisorError) as caught:
                supervisor.launch(worker_command(code))
            self.assertFalse(caught.exception.preserve_required)
            self.assertTrue(caught.exception.child_reaped)
            self.assertFalse(marker.exists())
            self.assertEqual(ops.gate_writes, [b"G", b"A"])

    def test_ready_inspection_failure_stops_and_reaps_by_pidfd(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swapz-pidfd-ready-fail-") as tmp:
            marker = Path(tmp) / "started"
            ops = FaultOps(fail_exec_wait=True)
            supervisor = GatedPidfdSupervisor(ops=ops)
            code = f"from pathlib import Path; import time; Path({str(marker)!r}).write_text('ran'); time.sleep(3)"
            with self.assertRaises(SupervisorError) as caught:
                supervisor.launch(worker_command(code))
            self.assertFalse(caught.exception.preserve_required)
            self.assertTrue(caught.exception.child_reaped)
            worker = supervisor.worker_for_test(caught.exception.handle)
            self.assertTrue(worker.reaped)
            self.assertIn("READY inspection failed", " ".join(worker.errors))
            self.assertTrue([event for event in ops.events if event[0] == "signal"])


class FakeSupervisorTests(unittest.TestCase):
    def test_hypothetical_pid_reuse_cannot_retarget_retained_pidfd(self) -> None:
        ops = FakePidfdOps()
        supervisor, handles = make_fake_supervisor(ops, [("original", 424242, 701)])
        original = ops.by_fd[701]
        original.exited = True
        ops.current_pid_owner[424242] = "replacement"
        report = supervisor.stop_all(handles)
        self.assertTrue(report.cleanup_allowed)
        self.assertTrue(original.reaped)
        self.assertEqual(ops.signal_log, [])
        self.assertEqual(ops.current_pid_owner[424242], "replacement")
        self.assertEqual(ops.numeric_signal_calls, 0)
        self.assertEqual(original.close_count, 1)

    def test_cont_and_term_use_the_same_retained_pidfd(self) -> None:
        ops = FakePidfdOps()
        supervisor, handles = make_fake_supervisor(ops, [("worker", 424242, 702)])
        report = supervisor.stop_all(handles)
        self.assertTrue(report.cleanup_allowed)
        self.assertEqual([(fd, sig) for fd, sig, _ in ops.signal_log], [
            (702, signal.SIGCONT), (702, signal.SIGTERM),
        ])
        self.assertEqual({token for _, _, token in ops.signal_log}, {"worker"})
        self.assertEqual(ops.by_fd[702].close_count, 1)

    def test_already_exited_fake_worker_is_not_signaled(self) -> None:
        ops = FakePidfdOps()
        supervisor, handles = make_fake_supervisor(ops, [("exited", 424242, 703)])
        ops.by_fd[703].exited = True
        report = supervisor.stop_all(handles)
        self.assertTrue(report.cleanup_allowed)
        self.assertEqual(ops.signal_log, [])
        self.assertTrue(ops.by_fd[703].reaped)
        self.assertEqual(ops.by_fd[703].close_count, 1)

    def test_timeout_escalation_stays_on_same_pidfd(self) -> None:
        ops = FakePidfdOps()
        supervisor, handles = make_fake_supervisor(ops, [("slow", 424242, 704)])
        process = ops.by_fd[704]
        process.term_exits = False
        report = supervisor.stop_all(handles)
        self.assertTrue(report.cleanup_allowed)
        self.assertTrue(report.results[0].escalated)
        self.assertEqual([(fd, sig) for fd, sig, _ in ops.signal_log], [
            (704, signal.SIGCONT), (704, signal.SIGTERM), (704, signal.SIGKILL),
        ])
        self.assertEqual(process.close_count, 1)

    def test_signal_failure_denies_cleanup_even_if_escalation_reaps(self) -> None:
        ops = FakePidfdOps()
        supervisor, handles = make_fake_supervisor(ops, [("fault", 424242, 705)])
        process = ops.by_fd[705]
        process.signal_errors.add(signal.SIGTERM)
        callbacks: list[str] = []
        report, result = supervisor.cleanup_after_stop(handles, lambda: callbacks.append("cleanup"))
        self.assertTrue(report.all_reaped)
        self.assertFalse(report.cleanup_allowed)
        self.assertIsNone(result)
        self.assertEqual(callbacks, [])
        self.assertTrue(any("SIGTERM via pidfd failed" in item for item in report.results[0].errors))
        self.assertIn((705, signal.SIGKILL, "fault"), ops.signal_log)
        self.assertEqual(process.close_count, 1)

    def test_wait_reap_failure_preserves_pidfd_and_blocks_cleanup(self) -> None:
        ops = FakePidfdOps()
        supervisor, handles = make_fake_supervisor(ops, [("unreapable", 424242, 706)])
        ops.by_fd[706].wait_error = True
        callbacks: list[str] = []
        report, result = supervisor.cleanup_after_stop(handles, lambda: callbacks.append("cleanup"))
        self.assertFalse(report.all_reaped)
        self.assertFalse(report.cleanup_allowed)
        self.assertIsNone(result)
        self.assertEqual(callbacks, [])
        self.assertFalse(ops.by_fd[706].reaped)
        self.assertNotIn(706, ops.closed_fds)
        self.assertTrue(any("wait/reap" in item for item in report.results[0].errors))

    def test_pidfd_close_failure_after_reap_blocks_cleanup(self) -> None:
        ops = FakePidfdOps()
        supervisor, handles = make_fake_supervisor(ops, [("close-fault", 424244, 708)])
        ops.by_fd[708].close_error = True
        callbacks: list[str] = []
        report, result = supervisor.cleanup_after_stop(handles, lambda: callbacks.append("cleanup"))
        self.assertTrue(report.all_reaped)
        self.assertFalse(report.cleanup_allowed)
        self.assertIsNone(result)
        self.assertEqual(callbacks, [])
        self.assertEqual(ops.by_fd[708].close_count, 1)
        self.assertEqual(ops.closed_fds.count(708), 1)
        self.assertEqual(ops.lifecycle_events, [("reaped", 708), ("closed", 708)])
        self.assertTrue(any("close pidfd" in item for item in report.results[0].errors))

    def test_three_workers_all_attempted_but_one_failure_blocks_cleanup(self) -> None:
        ops = FakePidfdOps()
        supervisor, handles = make_fake_supervisor(
            ops,
            [("first", 41001, 711), ("second", 41002, 712), ("third", 41003, 713)],
        )
        ops.by_fd[712].signal_errors.add(signal.SIGTERM)
        callbacks: list[str] = []
        report, result = supervisor.cleanup_after_stop(handles, lambda: callbacks.append("cleanup"))
        self.assertTrue(report.all_reaped)
        self.assertFalse(report.cleanup_allowed)
        self.assertIsNone(result)
        self.assertEqual(callbacks, [])
        self.assertEqual({fd for fd, _, _ in ops.signal_log}, {711, 712, 713})
        self.assertTrue(all(ops.by_fd[fd].close_count == 1 for fd in (711, 712, 713)))

    def test_three_worker_success_reaps_and_closes_before_cleanup_callback(self) -> None:
        ops = FakePidfdOps()
        supervisor, handles = make_fake_supervisor(
            ops,
            [("first", 42001, 721), ("second", 42002, 722), ("third", 42003, 723)],
        )
        callback_observation: list[tuple[bool, tuple[int, ...]]] = []

        def cleanup() -> str:
            records = [supervisor.worker_for_test(handle) for handle in handles]
            callback_observation.append((all(w.reaped for w in records), tuple(ops.closed_fds)))
            return "mock-cleanup-complete"

        report, result = supervisor.cleanup_after_stop(handles, cleanup)
        self.assertTrue(report.cleanup_allowed)
        self.assertTrue(report.all_reaped)
        self.assertEqual(result, "mock-cleanup-complete")
        self.assertEqual(callback_observation, [(True, (721, 722, 723))])
        self.assertTrue(all(ops.by_fd[fd].close_count == 1 for fd in (721, 722, 723)))
        for fd in (721, 722, 723):
            self.assertLess(ops.lifecycle_events.index(("reaped", fd)),
                            ops.lifecycle_events.index(("closed", fd)))

    def test_supervisor_has_no_numeric_signal_fallback(self) -> None:
        source = MODULE_PATH.read_text()
        self.assertNotIn("os.kill(", source)
        self.assertIn("signal.pidfd_send_signal", source)

    def test_unknown_and_duplicate_handles_deny_cleanup(self) -> None:
        ops = FakePidfdOps()
        supervisor, handles = make_fake_supervisor(ops, [("worker", 43001, 731)])
        report = supervisor.stop_all([handles[0], handles[0], "unknown"])
        self.assertFalse(report.cleanup_allowed)
        self.assertTrue(any("duplicate worker handle" in item for item in report.errors))
        self.assertTrue(any("unknown worker handle" in item for item in report.errors))

    def test_omitted_registered_worker_is_stopped_but_blocks_cleanup(self) -> None:
        ops = FakePidfdOps()
        supervisor, handles = make_fake_supervisor(
            ops, [("included", 43002, 732), ("omitted", 43003, 733)]
        )
        callbacks: list[str] = []
        report, result = supervisor.cleanup_after_stop(
            [handles[0]], lambda: callbacks.append("cleanup")
        )
        self.assertTrue(report.all_reaped)
        self.assertFalse(report.cleanup_allowed)
        self.assertIsNone(result)
        self.assertEqual(callbacks, [])
        self.assertEqual({fd for fd, _, _ in ops.signal_log}, {732, 733})
        self.assertTrue(any("omitted registered worker" in item for item in report.errors))

    def test_cleanup_callback_runs_with_worker_launches_closed(self) -> None:
        ops = FakePidfdOps()
        supervisor, handles = make_fake_supervisor(ops, [("closing", 43004, 734)])
        rejected: list[str] = []

        def cleanup() -> str:
            with self.assertRaises(SupervisorError) as caught:
                supervisor.launch(worker_command("pass"))
            rejected.append(str(caught.exception))
            return "cleanup-called"

        report, result = supervisor.cleanup_after_stop(handles, cleanup)
        self.assertTrue(report.cleanup_allowed)
        self.assertEqual(result, "cleanup-called")
        self.assertEqual(len(rejected), 1)
        self.assertIn("cleanup began", rejected[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
