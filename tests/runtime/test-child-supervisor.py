#!/usr/bin/env python3
"""Rootless, gated pidfd process supervisor prototype.

This prototype is not wired into the swapz runtime fixtures.  It supervises
direct child processes only and never falls back to a numeric-PID signal.
"""

from __future__ import annotations

import errno
import ctypes
import math
import os
import platform
import secrets
import select
import signal
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence


_START = b"G"
_ABORT = b"A"
_ERROR_SIZE = struct.calcsize("!I")
_POLL_EXIT = select.POLLIN | select.POLLHUP | select.POLLERR


class SupervisorError(RuntimeError):
    """A launch/cleanup error, with an explicit preservation decision."""

    def __init__(
        self,
        message: str,
        *,
        preserve_required: bool,
        handle: str | None = None,
        child_reaped: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.preserve_required = preserve_required
        self.handle = handle
        self.child_reaped = child_reaped


class PidfdUnavailable(SupervisorError):
    """The host or Python runtime cannot provide the required pidfd APIs."""


@dataclass
class Worker:
    handle: str
    pid: int
    pidfd: int | None
    exec_error_fd: int | None = None
    gate_write_fd: int | None = None
    reaped: bool = False
    raw_wait_status: int | None = None
    exit_code: int | None = None
    close_attempted: bool = False
    stop_requested: bool = False
    errors: list[str] = field(default_factory=list)
    escalated: bool = False
    containment_required: bool = False
    containment_installed: bool = False


@dataclass(frozen=True)
class WorkerResult:
    handle: str
    reaped: bool
    exit_code: int | None
    escalated: bool
    errors: tuple[str, ...]

    @property
    def worker_succeeded(self) -> bool:
        return self.reaped and self.exit_code == 0


@dataclass(frozen=True)
class StopReport:
    results: tuple[WorkerResult, ...]
    errors: tuple[str, ...]
    cleanup_allowed: bool

    @property
    def all_reaped(self) -> bool:
        return all(result.reaped for result in self.results)

    @property
    def workers_succeeded(self) -> bool:
        return all(result.worker_succeeded for result in self.results)


class LinuxPidfdOps:
    """Small syscall boundary, replaceable by deterministic rootless mocks."""

    def pidfd_api_available(self) -> bool:
        return callable(getattr(os, "pidfd_open", None)) and callable(
            getattr(signal, "pidfd_send_signal", None)
        )

    def pipe(self) -> tuple[int, int]:
        return os.pipe2(os.O_CLOEXEC)

    def fork(self) -> int:
        return os.fork()

    def install_process_containment(self, expected_parent_pid: int) -> None:
        """Bind the worker to its parent lifetime and deny process creation.

        The pidfd supervisor owns one direct worker.  PR_SET_PDEATHSIG kills
        that worker if the supervisor exits, while seccomp prevents the
        worker from creating untracked fork/clone descendants.  Unknown
        architectures or unavailable kernel support fail before the startup
        gate is released.
        """
        machine = platform.machine().lower()
        if machine in {"x86_64", "amd64"}:
            audit_arch = 0xC000003E  # AUDIT_ARCH_X86_64
            clone_number, fork_number, vfork_number = 56, 57, 58
            prctl_number = 157
            restricted_numbers = (
                105, 106, 113, 114, 116, 117, 119, 122, 123, 126, 272, 308,
                206, 209, 425,
            )
            reject_x32 = True
        elif machine in {"aarch64", "arm64"}:
            audit_arch = 0xC00000B7  # AUDIT_ARCH_AARCH64
            clone_number, fork_number, vfork_number = 220, None, None
            prctl_number = 167
            restricted_numbers = (
                143, 144, 145, 146, 147, 149, 151, 152, 159, 91, 97, 268,
                0, 2, 425,
            )
            reject_x32 = False
        else:
            raise OSError(errno.ENOSYS, f"process containment unsupported on {machine}")

        class SockFilter(ctypes.Structure):
            _fields_ = [
                ("code", ctypes.c_ushort),
                ("jt", ctypes.c_ubyte),
                ("jf", ctypes.c_ubyte),
                ("k", ctypes.c_uint),
            ]

        class SockFprog(ctypes.Structure):
            _fields_ = [("len", ctypes.c_ushort),
                        ("filter", ctypes.POINTER(SockFilter))]

        # Set the death signal first.  If the supervisor died between fork
        # and this call, the parent identity check below refuses to proceed.
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl.restype = ctypes.c_int
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
            error_number = ctypes.get_errno()
            raise OSError(error_number, os.strerror(error_number))
        if os.getppid() != expected_parent_pid:
            raise OSError(errno.ESRCH, "supervisor exited before parent-death binding")

        # classic BPF: require the native audit arch, then return EPERM for
        # process creation syscalls and ALLOW for all other worker operations.
        instructions = [
            SockFilter(0x20, 0, 0, 4),  # BPF_LD | BPF_W | BPF_ABS: arch
            SockFilter(0x15, 1, 0, audit_arch),  # BPF_JMP | BPF_JEQ | BPF_K
            SockFilter(0x06, 0, 0, 0x80000000),  # SECCOMP_RET_KILL_PROCESS
            SockFilter(0x20, 0, 0, 0),  # BPF_LD | BPF_W | BPF_ABS: syscall number
        ]
        if reject_x32:
            instructions.extend((
                SockFilter(0x54, 0, 0, 0x40000000),  # BPF_ALU | BPF_AND | BPF_K
                SockFilter(0x15, 1, 0, 0),  # native ABI continues; x32 is killed
                SockFilter(0x06, 0, 0, 0x80000000),
                SockFilter(0x20, 0, 0, 0),  # reload syscall number
            ))
        deny_errno = 0x00050000 | errno.EPERM
        if fork_number is not None:
            instructions.extend((
                SockFilter(0x15, 0, 1, fork_number), SockFilter(0x06, 0, 0, deny_errno),
                SockFilter(0x15, 0, 1, vfork_number), SockFilter(0x06, 0, 0, deny_errno),
            ))
        # The worker must not clear PR_SET_PDEATHSIG after exec. Credential
        # changes can also clear that setting on Linux. Namespace changes and
        # asynchronous AIO context creation are unnecessary for the fixed
        # synchronous dd roles, so deny those too; they could otherwise make
        # worker identity or I/O lifetime harder to attest.
        instructions.extend((
            SockFilter(0x15, 0, 3, prctl_number),  # not prctl: continue
            SockFilter(0x20, 0, 0, 16),  # prctl operation, seccomp_data.args[0]
            SockFilter(0x15, 0, 1, 1),  # PR_SET_PDEATHSIG
            SockFilter(0x06, 0, 0, deny_errno),
        ))
        for syscall_number in restricted_numbers:
            instructions.extend((
                SockFilter(0x15, 0, 1, syscall_number),
                SockFilter(0x06, 0, 0, deny_errno),
            ))
        # A clone that creates a new process is denied.  CLONE_THREAD is
        # allowed so a pinned utility may use threads; those threads remain
        # in the same thread group and pidfd lifetime.  clone3's pointed-to
        # flags cannot be inspected by classic BPF, so ENOSYS requests the
        # runtime's clone fallback, which is checked above.
        instructions.extend((
            SockFilter(0x15, 0, 5, clone_number),  # not clone: continue at clone3
            SockFilter(0x20, 0, 0, 16),  # seccomp_data.args[0], low word
            SockFilter(0x54, 0, 0, 0x00010000),  # CLONE_THREAD
            SockFilter(0x15, 1, 0, 0x00010000),
            SockFilter(0x06, 0, 0, deny_errno),
            SockFilter(0x06, 0, 0, 0x7FFF0000),  # thread clone: SECCOMP_RET_ALLOW
            SockFilter(0x15, 0, 1, 435),  # clone3
            SockFilter(0x06, 0, 0, 0x00050000 | errno.ENOSYS),
            SockFilter(0x06, 0, 0, 0x7FFF0000),  # SECCOMP_RET_ALLOW
        ))
        filter_array = (SockFilter * len(instructions))(*instructions)
        program = SockFprog(len(instructions), filter_array)

        if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
            error_number = ctypes.get_errno()
            raise OSError(error_number, os.strerror(error_number))
        if libc.prctl(22, 2, ctypes.byref(program), 0, 0) != 0:  # PR_SET_SECCOMP/FILTER
            error_number = ctypes.get_errno()
            raise OSError(error_number, os.strerror(error_number))

    def read(self, fd: int, size: int) -> bytes:
        return os.read(fd, size)

    def write(self, fd: int, data: bytes) -> int:
        return os.write(fd, data)

    def close(self, fd: int) -> None:
        os.close(fd)

    def pidfd_open(self, pid: int) -> int:
        opener = getattr(os, "pidfd_open", None)
        if not callable(opener):
            raise OSError(errno.ENOSYS, "os.pidfd_open is unavailable")
        return opener(pid, 0)

    def pidfd_send_signal(self, pidfd: int, sig: int) -> None:
        sender = getattr(signal, "pidfd_send_signal", None)
        if not callable(sender):
            raise OSError(errno.ENOSYS, "signal.pidfd_send_signal is unavailable")
        sender(pidfd, sig, None, 0)

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def poll(self, fd: int, timeout_ms: int) -> bool:
        poller = select.poll()
        poller.register(fd, _POLL_EXIT)
        return bool(poller.poll(timeout_ms))

    def pidfd_exited(self, pidfd: int) -> bool:
        return self.poll(pidfd, 0)

    def waitpid_nonblocking(self, pid: int) -> int | None:
        while True:
            try:
                got, status = os.waitpid(pid, os.WNOHANG)
                break
            except InterruptedError:
                continue
        if got == 0:
            return None
        if got != pid:
            raise ChildProcessError(errno.ECHILD, "waitpid returned a different child")
        return status

    def wait_reap(self, pid: int, pidfd: int, timeout: float) -> int | None:
        deadline = self.monotonic() + max(0.0, timeout)
        while True:
            status = self.waitpid_nonblocking(pid)
            if status is not None:
                return status
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                return None
            self.poll(pidfd, max(1, min(50, int(remaining * 1000))))

    def wait_reap_without_pidfd(self, pid: int, timeout: float) -> int | None:
        deadline = self.monotonic() + max(0.0, timeout)
        while True:
            status = self.waitpid_nonblocking(pid)
            if status is not None:
                return status
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                return None
            self.sleep(min(0.01, remaining))

    def wait_for_exec(self, error_fd: int, pidfd: int, timeout: float) -> tuple[str, bytes]:
        """Return exec, child-exit, timeout, or an errno payload."""
        deadline = self.monotonic() + timeout
        error_data = bytearray()
        poller = select.poll()
        poller.register(error_fd, _POLL_EXIT)
        poller.register(pidfd, _POLL_EXIT)

        while True:
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                return "timeout", bytes(error_data)
            events = poller.poll(max(1, min(1000, int(remaining * 1000))))
            if not events:
                return "timeout", bytes(error_data)
            event_map = {fd: mask for fd, mask in events}

            if error_fd in event_map:
                while True:
                    try:
                        chunk = self.read(error_fd, _ERROR_SIZE - len(error_data))
                        break
                    except InterruptedError:
                        continue
                if chunk:
                    error_data.extend(chunk)
                    if len(error_data) >= _ERROR_SIZE:
                        return "exec-error", bytes(error_data[:_ERROR_SIZE])
                    continue
                if self.pidfd_exited(pidfd):
                    return "child-exit", bytes(error_data)
                return "exec", bytes(error_data)

            if pidfd in event_map:
                return "child-exit", bytes(error_data)


def _status_to_exit_code(raw_status: int) -> int:
    if os.WIFEXITED(raw_status):
        return os.WEXITSTATUS(raw_status)
    if os.WIFSIGNALED(raw_status):
        return 128 + os.WTERMSIG(raw_status)
    return 255


def _child_wait_for_gate(ops: LinuxPidfdOps, fd: int) -> bytes:
    while True:
        try:
            return ops.read(fd, 1)
        except InterruptedError:
            continue


def _child_report_exec_error(ops: LinuxPidfdOps, fd: int, error_number: int) -> None:
    payload = struct.pack("!I", max(1, error_number))
    offset = 0
    while offset < len(payload):
        try:
            written = ops.write(fd, payload[offset:])
        except InterruptedError:
            continue
        except OSError:
            break
        if written <= 0:
            break
        offset += written


class GatedPidfdSupervisor:
    """Own direct children from gated launch through pidfd signaling and reap."""

    def __init__(
        self,
        *,
        ops: LinuxPidfdOps | None = None,
        startup_timeout: float = 2.0,
        term_grace: float = 0.5,
        kill_grace: float = 0.5,
        escalate: bool = True,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        if (not math.isfinite(startup_timeout) or not math.isfinite(term_grace)
                or not math.isfinite(kill_grace) or startup_timeout <= 0
                or term_grace < 0 or kill_grace < 0):
            raise ValueError("timeouts must be positive or nonnegative")
        self.ops = ops if ops is not None else LinuxPidfdOps()
        self.startup_timeout = startup_timeout
        self.term_grace = term_grace
        self.kill_grace = kill_grace
        self.escalate = escalate
        self.token_factory = token_factory or (lambda: secrets.token_urlsafe(24))
        self._workers: dict[str, Worker] = {}
        self._closing = False
        self._containment_failure_latched = False

    def _require_pidfd_support(self) -> None:
        if threading.current_thread() is not threading.main_thread() or threading.active_count() != 1:
            raise PidfdUnavailable(
                "fork-based supervisor requires the sole Python main thread",
                preserve_required=False,
            )
        try:
            child_signal = signal.getsignal(signal.SIGCHLD)
        except Exception as exc:
            raise PidfdUnavailable(
                f"cannot inspect SIGCHLD disposition: {exc}", preserve_required=False
            ) from exc
        if child_signal != signal.SIG_DFL:
            raise PidfdUnavailable(
                "fork-based supervisor requires default SIGCHLD disposition",
                preserve_required=False,
            )
        supported = getattr(self.ops, "pidfd_api_available", None)
        if callable(supported) and not supported():
            raise PidfdUnavailable(
                "required pidfd APIs are unavailable; no worker was created",
                preserve_required=False,
            )
        if not callable(getattr(self.ops, "pidfd_open", None)):
            raise PidfdUnavailable("pidfd_open unavailable", preserve_required=False)
        if not callable(getattr(self.ops, "pidfd_send_signal", None)):
            raise PidfdUnavailable("pidfd_send_signal unavailable", preserve_required=False)

    def _new_handle(self) -> str:
        """Allocate a non-PID public token before creating a child."""
        for _ in range(16):
            try:
                handle = self.token_factory()
            except Exception as exc:
                raise SupervisorError(
                    f"worker handle creation failed: {exc}", preserve_required=False
                ) from exc
            if (isinstance(handle, str) and handle and not handle.isdecimal()
                    and handle not in self._workers):
                return handle
        raise SupervisorError(
            "worker handle factory did not produce a unique opaque token",
            preserve_required=False,
        )

    def _close_fd(self, fd: int | None, errors: list[str], label: str) -> None:
        if fd is None:
            return
        try:
            self.ops.close(fd)
        except Exception as exc:  # cleanup errors must remain visible
            errors.append(f"close {label}: {exc}")

    def _close_worker_pidfd(self, worker: Worker) -> None:
        if worker.close_attempted or worker.pidfd is None:
            return
        worker.close_attempted = True
        try:
            self.ops.close(worker.pidfd)
        except Exception as exc:
            worker.errors.append(f"close pidfd: {exc}")
        finally:
            # Never retry close(): after an error the descriptor number may be
            # reusable, and retrying could close an unrelated descriptor.
            worker.pidfd = None

    def _wait_unpidfd_child(self, pid: int, timeout: float) -> int | None:
        waiter = getattr(self.ops, "wait_reap_without_pidfd", None)
        if not callable(waiter):
            raise RuntimeError("backend lacks direct-child wait support")
        return waiter(pid, timeout)

    def _abort_gated_child(self, pid: int, gate_write_fd: int) -> tuple[bool, list[str]]:
        errors: list[str] = []
        try:
            self._write_all(gate_write_fd, _ABORT)
        except Exception as exc:
            errors.append(f"deliver gate abort: {exc}")
        try:
            self.ops.close(gate_write_fd)
        except Exception as exc:
            errors.append(f"close startup gate: {exc}")
        try:
            status = self._wait_unpidfd_child(pid, self.startup_timeout)
        except Exception as exc:
            errors.append(f"wait for gated child: {exc}")
            status = None
        return status is not None, errors

    def _write_all(self, fd: int, data: bytes) -> None:
        offset = 0
        while offset < len(data):
            try:
                count = self.ops.write(fd, data[offset:])
            except InterruptedError:
                continue
            if count <= 0:
                raise OSError(errno.EIO, "short write to startup gate")
            offset += count

    def _child_exec(
        self,
        gate_read_fd: int,
        gate_write_fd: int,
        error_read_fd: int,
        error_write_fd: int,
        argv: tuple[str, ...],
        env: dict[str, str],
        cwd: str | None,
        executable: str | None,
        executable_fd: int | None,
        pass_fds: tuple[int, ...],
        strict_fds: bool,
        contain_process_tree: bool,
        expected_parent_pid: int,
    ) -> None:
        # This path runs only in the forked, single-threaded child.  The worker
        # cannot run until the parent writes the start byte after pidfd_open.
        try:
            if contain_process_tree:
                self.ops.install_process_containment(expected_parent_pid)
            self.ops.close(gate_write_fd)
            self.ops.close(error_read_fd)
            token = _child_wait_for_gate(self.ops, gate_read_fd)
            self.ops.close(gate_read_fd)
            if token != _START:
                os._exit(125)
            if cwd is not None:
                os.chdir(cwd)
            if strict_fds:
                # Direct-I/O role launches may inherit only their pinned
                # descriptors.  Enumerate in this single-threaded fork child;
                # any inspection/close error aborts exec and is reported over
                # the existing CLOEXEC error pipe.
                keep = {0, 1, 2, error_write_fd}
                keep.update(pass_fds)
                if executable_fd is not None:
                    keep.add(executable_fd)
                try:
                    inherited = os.listdir("/proc/self/fd")
                except OSError as exc:
                    raise OSError(errno.EIO, f"cannot inspect child descriptors: {exc}") from exc
                for entry in inherited:
                    if not entry.isdecimal():
                        continue
                    fd = int(entry)
                    if fd < 3 or fd in keep:
                        continue
                    try:
                        os.close(fd)
                    except OSError as exc:
                        # listdir's own fd can already have closed when its
                        # returned entries are processed. EBADF is harmless.
                        if exc.errno != errno.EBADF:
                            raise
            # File descriptors are close-on-exec by default.  Only explicitly
            # selected descriptors cross this exec boundary.  This mutation
            # occurs in the forked child, so the supervisor's own descriptor
            # flags remain unchanged.
            for fd in pass_fds:
                os.set_inheritable(fd, True)
            if executable is None:
                os.execvpe(argv[0], argv, env)
            # The caller may provide a descriptor-pinned path such as
            # /proc/self/fd/N.  os.execve does no PATH lookup in this mode.
            os.execve(executable, argv, env)
        except BaseException as exc:
            number = getattr(exc, "errno", None) or errno.EFAULT
            try:
                _child_report_exec_error(self.ops, error_write_fd, int(number))
            finally:
                os._exit(127)

    def launch(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        executable: str | None = None,
        executable_fd: int | None = None,
        pass_fds: Sequence[int] = (),
        strict_fds: bool = False,
        contain_process_tree: bool | None = None,
    ) -> str:
        required = (executable_fd is not None if contain_process_tree is None
                    else contain_process_tree is True)
        try:
            return self._launch_impl(
                argv, env=env, cwd=cwd, executable=executable,
                executable_fd=executable_fd, pass_fds=pass_fds,
                strict_fds=strict_fds, contain_process_tree=contain_process_tree,
            )
        except Exception:
            if required:
                self._containment_failure_latched = True
            raise

    def _launch_impl(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        executable: str | None = None,
        executable_fd: int | None = None,
        pass_fds: Sequence[int] = (),
        strict_fds: bool = False,
        contain_process_tree: bool | None = None,
    ) -> str:
        """Start argv behind a gate and return only after pidfd-backed exec."""
        if self._closing:
            raise SupervisorError(
                "worker launch rejected after cleanup began",
                preserve_required=any(not worker.reaped for worker in self._workers.values()),
            )
        if not isinstance(argv, Sequence) or isinstance(argv, (str, bytes)) or not argv:
            raise ValueError("argv must be a nonempty sequence of strings")
        command = tuple(argv)
        if any(not isinstance(arg, str) or "\x00" in arg for arg in command):
            raise ValueError("argv entries must be NUL-free strings")
        if not command[0]:
            raise ValueError("argv[0] must be nonempty")
        if not isinstance(pass_fds, Sequence) or isinstance(pass_fds, (str, bytes)):
            raise ValueError("pass_fds must be a sequence of file descriptors")
        inherited_fds = tuple(pass_fds)
        if any(isinstance(fd, bool) or not isinstance(fd, int) or fd < 0 for fd in inherited_fds):
            raise ValueError("pass_fds must contain nonnegative integer descriptors")
        if len(inherited_fds) != len(set(inherited_fds)):
            raise ValueError("pass_fds must not contain duplicates")
        if executable is not None and (
            not isinstance(executable, str) or not executable.startswith("/")
            or "\x00" in executable
        ):
            raise ValueError("executable must be an absolute NUL-free path")
        if type(strict_fds) is not bool:
            raise ValueError("strict_fds must be a boolean")
        if contain_process_tree is not None and type(contain_process_tree) is not bool:
            raise ValueError("contain_process_tree must be a boolean or None")
        if contain_process_tree is None:
            contain_process_tree = executable_fd is not None
        if contain_process_tree and (executable_fd is None or not strict_fds):
            raise ValueError("process containment requires a pinned executable and strict descriptors")
        if executable_fd is not None and not contain_process_tree:
            raise ValueError("pinned worker launches cannot disable process containment")
        if executable_fd is not None:
            if (isinstance(executable_fd, bool) or not isinstance(executable_fd, int)
                    or executable_fd < 0 or executable is None):
                raise ValueError("executable_fd requires a valid pinned executable path")
            os.fstat(executable_fd)
            if (os.get_inheritable(executable_fd)
                    or executable != f"/proc/self/fd/{executable_fd}"):
                raise ValueError("pinned executable must use its close-on-exec procfd path")
            if executable_fd in inherited_fds:
                raise ValueError("pinned executable descriptor must remain close-on-exec")
            if not strict_fds:
                raise ValueError("pinned executable launches require strict descriptor isolation")
        for fd in inherited_fds:
            # Validate in the parent before creating a child.  The descriptor
            # stays CLOEXEC here and is made inheritable only in the gated
            # child immediately before exec.
            os.fstat(fd)
            if os.get_inheritable(fd):
                raise ValueError("pass_fds must be close-on-exec in the supervisor")
        child_env = dict(os.environ if env is None else env)
        if any(not isinstance(k, str) or not isinstance(v, str) or "\x00" in k or "\x00" in v
               for k, v in child_env.items()):
            raise ValueError("environment keys and values must be NUL-free strings")
        self._require_pidfd_support()
        handle = self._new_handle()

        gate_read_fd: int | None = None
        gate_write_fd: int | None = None
        error_read_fd: int | None = None
        error_write_fd: int | None = None
        try:
            gate_read_fd, gate_write_fd = self.ops.pipe()
            error_read_fd, error_write_fd = self.ops.pipe()
        except Exception as exc:
            cleanup_errors: list[str] = []
            self._close_fd(gate_read_fd, cleanup_errors, "gate reader")
            self._close_fd(gate_write_fd, cleanup_errors, "gate writer")
            self._close_fd(error_read_fd, cleanup_errors, "exec-error reader")
            self._close_fd(error_write_fd, cleanup_errors, "exec-error writer")
            suffix = "; ".join(cleanup_errors)
            raise SupervisorError(
                f"startup gate creation failed: {exc}" + (f"; {suffix}" if suffix else ""),
                preserve_required=bool(cleanup_errors),
            ) from exc

        expected_parent_pid = os.getpid()
        try:
            pid = self.ops.fork()
        except Exception as exc:
            cleanup_errors: list[str] = []
            for fd, label in ((gate_read_fd, "gate reader"), (gate_write_fd, "gate writer"),
                              (error_read_fd, "exec-error reader"), (error_write_fd, "exec-error writer")):
                self._close_fd(fd, cleanup_errors, label)
            suffix = "; ".join(cleanup_errors)
            raise SupervisorError(
                f"child creation failed: {exc}" + (f"; {suffix}" if suffix else ""),
                preserve_required=bool(cleanup_errors),
            ) from exc

        if pid == 0:
            self._child_exec(
                gate_read_fd, gate_write_fd, error_read_fd, error_write_fd,
                command, child_env, cwd, executable, executable_fd, inherited_fds, strict_fds,
                contain_process_tree, expected_parent_pid,
            )
            os._exit(127)

        # The direct child is blocked in the gate read.  Until this point it
        # cannot execute argv and the parent has not sent it any signal.
        parent_close_errors: list[str] = []
        self._close_fd(gate_read_fd, parent_close_errors, "child gate reader")
        self._close_fd(error_write_fd, parent_close_errors, "child exec-error writer")
        gate_read_fd = None
        error_write_fd = None
        if parent_close_errors:
            reaped, abort_errors = self._abort_gated_child(pid, gate_write_fd)
            self._close_fd(error_read_fd, abort_errors, "exec-error reader")
            raise SupervisorError(
                "; ".join(parent_close_errors + abort_errors),
                preserve_required=not reaped or bool(parent_close_errors + abort_errors),
                child_reaped=reaped,
            )

        try:
            pidfd = self.ops.pidfd_open(pid)
            if not isinstance(pidfd, int) or pidfd < 0:
                raise OSError(errno.EBADF, "pidfd_open returned an invalid descriptor")
        except Exception as exc:
            reaped, abort_errors = self._abort_gated_child(pid, gate_write_fd)
            self._close_fd(error_read_fd, abort_errors, "exec-error reader")
            detail = "; ".join(abort_errors)
            raise PidfdUnavailable(
                f"pidfd acquisition failed: {exc}" + (f"; {detail}" if detail else ""),
                preserve_required=not reaped or bool(abort_errors),
                child_reaped=reaped,
            ) from exc

        worker = Worker(
            handle=handle,
            pid=pid,
            pidfd=pidfd,
            exec_error_fd=error_read_fd,
            gate_write_fd=gate_write_fd,
            containment_required=contain_process_tree,
        )
        self._workers[handle] = worker

        try:
            self._write_all(gate_write_fd, _START)
            self.ops.close(gate_write_fd)
            worker.gate_write_fd = None
        except Exception as exc:
            worker.errors.append(f"startup gate release failed: {exc}")
            self._abort_worker_gate(worker)
            self._stop_records((worker,))
            raise SupervisorError(
                f"startup gate release failed: {exc}",
                preserve_required=not worker.reaped,
                handle=handle,
                child_reaped=worker.reaped,
            ) from exc

        try:
            outcome, payload = self.ops.wait_for_exec(error_read_fd, pidfd, self.startup_timeout)
        except Exception as exc:
            worker.errors.append(f"READY inspection failed: {exc}")
            self._close_exec_error_fd(worker)
            self._stop_records((worker,))
            raise SupervisorError(
                f"READY inspection failed: {exc}",
                preserve_required=not worker.reaped,
                handle=handle,
                child_reaped=worker.reaped,
            ) from exc
        if outcome == "exec":
            worker.containment_installed = contain_process_tree
            self._close_exec_error_fd(worker)
            return handle

        if outcome == "exec-error":
            number = struct.unpack("!I", payload)[0] if len(payload) == _ERROR_SIZE else errno.EIO
            reason = OSError(number, os.strerror(number))
        elif outcome == "child-exit":
            reason = RuntimeError("child exited before READY")
        else:
            reason = TimeoutError("worker did not reach READY before startup timeout")
        worker.errors.append(f"startup failed: {reason}")
        self._close_exec_error_fd(worker)
        self._stop_records((worker,))
        raise SupervisorError(
            f"worker startup failed: {reason}",
            preserve_required=not worker.reaped,
            handle=handle,
            child_reaped=worker.reaped,
        )

    def _abort_worker_gate(self, worker: Worker) -> None:
        if worker.gate_write_fd is None:
            return
        try:
            self._write_all(worker.gate_write_fd, _ABORT)
        except Exception as exc:
            worker.errors.append(f"deliver gate abort: {exc}")
        try:
            self.ops.close(worker.gate_write_fd)
        except Exception as exc:
            worker.errors.append(f"close startup gate: {exc}")
        finally:
            worker.gate_write_fd = None

    def _close_exec_error_fd(self, worker: Worker) -> None:
        if worker.exec_error_fd is None:
            return
        try:
            self.ops.close(worker.exec_error_fd)
        except Exception as exc:
            worker.errors.append(f"close exec-error pipe: {exc}")
        finally:
            worker.exec_error_fd = None

    def _record_reap(self, worker: Worker, raw_status: int) -> None:
        worker.reaped = True
        worker.raw_wait_status = raw_status
        worker.exit_code = _status_to_exit_code(raw_status)
        if worker.exit_code != 0 and not worker.stop_requested:
            worker.errors.append(
                f"worker exited unsuccessfully before stop request: {worker.exit_code}"
            )
        self._close_worker_pidfd(worker)
        self._close_exec_error_fd(worker)
        if worker.gate_write_fd is not None:
            self._abort_worker_gate(worker)

    def _wait_worker(self, worker: Worker, timeout: float) -> int | None:
        if worker.pidfd is None:
            raise RuntimeError("cannot wait on worker without retained pidfd")
        return self.ops.wait_reap(worker.pid, worker.pidfd, timeout)

    def _stop_records(self, workers: Sequence[Worker]) -> list[WorkerResult]:
        results: list[WorkerResult] = []
        for worker in workers:
            if not worker.reaped:
                if worker.pidfd is None:
                    worker.errors.append("missing retained pidfd; no PID fallback attempted")
                else:
                    try:
                        exited = self.ops.pidfd_exited(worker.pidfd)
                    except Exception as exc:
                        worker.errors.append(f"pidfd exit inspection failed: {exc}")
                        exited = False

                    raw_status: int | None = None
                    if exited:
                        try:
                            raw_status = self._wait_worker(worker, 0.0)
                        except Exception as exc:
                            worker.errors.append(f"wait/reap failed: {exc}")
                    else:
                        worker.stop_requested = True
                        for sig, name in ((signal.SIGCONT, "SIGCONT"), (signal.SIGTERM, "SIGTERM")):
                            try:
                                self.ops.pidfd_send_signal(worker.pidfd, sig)
                            except Exception as exc:
                                worker.errors.append(f"{name} via pidfd failed: {exc}")

                        try:
                            raw_status = self._wait_worker(worker, self.term_grace)
                        except Exception as exc:
                            worker.errors.append(f"wait/reap after SIGTERM failed: {exc}")

                        if raw_status is None and self.escalate:
                            worker.escalated = True
                            try:
                                self.ops.pidfd_send_signal(worker.pidfd, signal.SIGKILL)
                            except Exception as exc:
                                worker.errors.append(f"SIGKILL via pidfd failed: {exc}")
                            try:
                                raw_status = self._wait_worker(worker, self.kill_grace)
                            except Exception as exc:
                                worker.errors.append(f"wait/reap after SIGKILL failed: {exc}")

                    if raw_status is not None:
                        self._record_reap(worker, raw_status)
                    elif not worker.reaped:
                        worker.errors.append("worker exit and reap not confirmed; preserve backing")

            if worker.containment_required and not worker.containment_installed:
                worker.errors.append("process containment was not confirmed before exec")
            results.append(self._result(worker))
        return results

    def _result(self, worker: Worker) -> WorkerResult:
        return WorkerResult(
            handle=worker.handle,
            reaped=worker.reaped,
            exit_code=worker.exit_code,
            escalated=worker.escalated,
            errors=tuple(worker.errors),
        )

    def wait(self, handle: str, timeout: float) -> WorkerResult:
        """Wait for natural worker completion and reap it, without signaling."""
        worker = self._workers.get(handle)
        if worker is None:
            raise KeyError("unknown worker handle")
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("timeout must be finite and nonnegative")
        if not worker.reaped:
            if worker.pidfd is None:
                worker.errors.append("missing retained pidfd while waiting")
            else:
                try:
                    status = self._wait_worker(worker, timeout)
                except Exception as exc:
                    worker.errors.append(f"wait/reap failed: {exc}")
                else:
                    if status is not None:
                        self._record_reap(worker, status)
        return self._result(worker)

    def stop_all(self, worker_handles: Sequence[str]) -> StopReport:
        """Resume, terminate, wait and reap every registered direct child.

        Every registered worker is attempted, even if a handle is omitted or
        an earlier worker fails.  Omitted, duplicate, and unknown handles are
        report errors and deny cleanup.  Any signal, wait, reap, inspection or
        descriptor-close error also denies cleanup.
        """
        report_errors: list[str] = []
        seen: set[str] = set()
        for handle in worker_handles:
            if not isinstance(handle, str):
                report_errors.append(f"invalid worker handle: {handle!r}")
                continue
            if handle in seen:
                report_errors.append(f"duplicate worker handle: {handle}")
                continue
            seen.add(handle)
            if handle not in self._workers:
                report_errors.append(f"unknown worker handle: {handle}")

        missing = set(self._workers) - seen
        if missing:
            report_errors.append(
                "omitted registered worker handles: " + ", ".join(sorted(missing))
            )

        if self._containment_failure_latched:
            report_errors.append("a process-contained launch failed; preserve backing")

        # Never let an incomplete caller list leave a registered worker alive.
        workers = tuple(self._workers.values())
        results = tuple(self._stop_records(workers))
        cleanup_allowed = (
            all(result.reaped for result in results)
            and not report_errors
            and all(not result.errors for result in results)
        )
        return StopReport(results, tuple(report_errors), cleanup_allowed)

    def cleanup_after_stop(
        self,
        worker_handles: Sequence[str],
        cleanup: Callable[[], object],
    ) -> tuple[StopReport, object | None]:
        """Call cleanup only after every worker is reaped without lifecycle errors."""
        self._closing = True
        report = self.stop_all(worker_handles)
        if not report.cleanup_allowed:
            return report, None
        return report, cleanup()

    def worker_for_test(self, handle: str) -> Worker:
        """Expose read-only test inspection; handles remain the public API."""
        try:
            return self._workers[handle]
        except KeyError:
            raise KeyError("unknown worker handle") from None


__all__ = [
    "GatedPidfdSupervisor",
    "LinuxPidfdOps",
    "PidfdUnavailable",
    "StopReport",
    "SupervisorError",
    "WorkerResult",
]
