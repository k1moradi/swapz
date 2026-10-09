#!/usr/bin/env python3
"""Test-only pidfd ownership gate for a synthetic NBD-like service process.

This helper NEVER attaches an NBD device or authorizes backing removal.
It only proves that a directly launched, fixed synthetic child is signaled
through a retained pidfd, reaped via its owning Popen, and denied on errors.
The production streaming NBD benchmark remains disabled.
"""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import signal
import socket
import stat
import subprocess
import sys

HERE = Path(__file__).resolve().parent
CHILD = HERE / "nbd-pidfd-owned-mock-child.py"
MODES = frozenset(("normal", "wrong-ready", "exit-before-ready",
                   "exit-after-ready", "ignore-term", "fail-term",
                   "slow-ready", "silent"))


class OwnedServerDenied(RuntimeError):
    """No trustworthy server-process lifecycle completion was observed."""


class RootlessOwnedServer:
    """Manage exactly one fixed, test-only subprocess and one kernel pidfd."""

    def __init__(self, directory: Path, *, mode: str = "normal",
                 start_timeout: float = 0.4, stop_timeout: float = 0.3):
        if (type(mode) is not str or mode not in MODES
                or not isinstance(directory, Path) or not directory.is_absolute()
                or type(start_timeout) not in (float, int)
                or type(stop_timeout) not in (float, int)
                or not 0.05 <= start_timeout <= 5.0
                or not 0.05 <= stop_timeout <= 5.0):
            raise OwnedServerDenied("invalid synthetic service session parameters")
        self.directory = directory
        self.mode = mode
        self.start_timeout = float(start_timeout)
        self.stop_timeout = float(stop_timeout)
        self.process: subprocess.Popen[bytes] | None = None
        self.pidfd: int | None = None
        self.sock: socket.socket | None = None
        self.state = "new"
        self.signal_log: list[str] = []
        self.clean_exit = False
        self.cleanup_allowed = False  # A reaped server is NOT verified NBD/DM drain.

    def _preflight(self) -> None:
        if os.geteuid() == 0:
            raise OwnedServerDenied("rootless synthetic server may not run as root")
        if not callable(getattr(os, "pidfd_open", None)):
            raise OwnedServerDenied("kernel pidfd_open is required; no PID fallback")
        if not callable(getattr(signal, "pidfd_send_signal", None)):
            raise OwnedServerDenied("pidfd_send_signal is required; no PID fallback")
        probe = os.pidfd_open(os.getpid(), 0)
        os.close(probe)
        info = os.stat(self.directory, follow_symlinks=False)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077):
            raise OwnedServerDenied("synthetic fixture directory must be private and owned")
        if not CHILD.is_file():
            raise OwnedServerDenied("fixed test worker source is missing")

    def start(self) -> None:
        if self.state != "new":
            raise OwnedServerDenied("service cannot be started more than once")
        try:
            self._preflight()
            parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            self.sock = parent
            logfd = os.open(str(self.directory / "server.log"),
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
                            | os.O_NOFOLLOW, 0o600)
            try:
                try:
                    self.process = subprocess.Popen(
                        [sys.executable, "-B", str(CHILD), str(child.fileno()), self.mode],
                        cwd=self.directory, pass_fds=(child.fileno(),),
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=logfd, close_fds=True,
                    )
                finally:
                    child.close()
            finally:
                os.close(logfd)
            # The child remains a zombie until the controller explicitly reaps
            # it, so its numeric PID cannot be recycled during pidfd_open.
            # No numeric-PID signal or external process adoption is supported.
            self.pidfd = os.pidfd_open(self.process.pid, 0)
            parent.settimeout(self.start_timeout)
            nonce = secrets.token_hex(16)
            parent.sendall(("HELLO " + nonce).encode("ascii"))
            received = parent.recv(128)
            if received != ("READY " + nonce).encode("ascii"):
                raise OwnedServerDenied("incorrect, missing, or truncated fixed-server readiness")
            if self.process.poll() is not None:
                raise OwnedServerDenied("owned mock server exited during readiness")
            self.state = "running"
        except BaseException as exc:
            self.state = "denied"
            self._abort_owned()
            if isinstance(exc, OwnedServerDenied):
                raise
            raise OwnedServerDenied(f"synthetic startup denied: {type(exc).__name__}") from exc

    def _signal(self, signum: signal.Signals) -> None:
        if self.pidfd is None or self.process is None:
            raise OwnedServerDenied("no retained stable pidfd for the exact owned server")
        if self.process.poll() is not None:
            raise OwnedServerDenied("owned server already exited before the requested shutdown")
        # No process.pid signal, subprocess.terminate, or PID-reuse fallback.
        signal.pidfd_send_signal(self.pidfd, signum, None, 0)
        self.signal_log.append(signum.name)

    def _abort_owned(self) -> None:
        """Best-effort pidfd-only termination, never an authorization path."""
        if self.process is not None:
            if self.pidfd is not None and self.process.poll() is None:
                try:
                    self._signal(signal.SIGKILL)
                except (OSError, OwnedServerDenied):
                    pass
            try:
                self.process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                # No numeric-PID rescue; caller must retain diagnostics.
                pass
        self._release_descriptors()

    def _release_descriptors(self) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None
        if self.pidfd is not None:
            os.close(self.pidfd)
            self.pidfd = None

    def shutdown(self) -> dict[str, bool]:
        if self.state != "running" or self.process is None:
            raise OwnedServerDenied("unstarted, stopped, or denied server cannot be stopped")
        try:
            self._signal(signal.SIGTERM)
            try:
                observed = self.process.wait(timeout=self.stop_timeout)
            except subprocess.TimeoutExpired as exc:
                raise OwnedServerDenied("owned server did not exit within the bounded grace period") from exc
            if observed != 0:
                raise OwnedServerDenied(f"owned server exited unsuccessfully: {observed}")
            self.clean_exit = True
            self.state = "stopped"
            self._release_descriptors()
            return {
                "exact_owned_process_reaped": True,
                "zero_exit": True,
                "kernel_nbd_disconnected": False,
                "dm_io_drained": False,
                "backing_cleanup_authorized": False,
            }
        except BaseException as exc:
            self.state = "denied"
            self.clean_exit = False
            self._abort_owned()
            if isinstance(exc, OwnedServerDenied):
                raise
            raise OwnedServerDenied(f"owned server shutdown denied: {type(exc).__name__}") from exc

    def close(self) -> None:
        """Close the test session; an unfinished session is always denied."""
        if self.state == "running":
            self.state = "denied"
            self._abort_owned()
        else:
            self._release_descriptors()

    def __enter__(self) -> "RootlessOwnedServer":
        self.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


__all__ = ["RootlessOwnedServer", "OwnedServerDenied", "MODES"]
