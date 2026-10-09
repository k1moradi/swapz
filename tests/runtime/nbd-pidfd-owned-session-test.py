#!/usr/bin/env python3
"""Rootless, device-free stable-pidfd ownership and shutdown regression.

No test opens /dev/nbd*, creates DM/loop devices, runs fio, starts a real NBD
service or signals an unrelated process. All children are fixed local test
scripts created by this test case and bounded by the session controller.
"""

from __future__ import annotations

import importlib.util
from array import array
import os
import select
import socket
import subprocess
from pathlib import Path
import signal
import stat
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "swapz_owned_nbd_synthetic", HERE / "nbd-pidfd-owned-session.py"
)
assert spec is not None and spec.loader is not None
owner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = owner
spec.loader.exec_module(owner)
Session = owner.RootlessOwnedServer
Denied = owner.OwnedServerDenied


@unittest.skipIf(os.geteuid() == 0, "rootless mock process tests forbid root")
class OwnedSyntheticServerTests(unittest.TestCase):
    def setUp(self) -> None:
        if not callable(getattr(os, "pidfd_open", None)):
            self.skipTest("Linux pidfd_open unavailable")
        if not callable(getattr(signal, "pidfd_send_signal", None)):
            self.skipTest("Linux pidfd_send_signal unavailable")
        self.temp = tempfile.TemporaryDirectory(prefix="swapz-owned-nbd-mock-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.counter = 0
        self.marker = self.root / "synthetic-backing.marker"
        self.marker.write_text("never release on process proof alone", encoding="utf-8")
        self.marker.chmod(0o600)

    def build(self, mode: str = "normal", *, timeout: float = 0.4,
              grace: float = 0.25) -> Session:
        self.counter += 1
        directory = self.root / f"case-{self.counter}"
        directory.mkdir(mode=0o700)
        session = Session(directory, mode=mode, start_timeout=timeout,
                          stop_timeout=grace)
        self.addCleanup(session.close)
        return session

    def assert_backing_retained(self, session: Session) -> None:
        self.assertTrue(self.marker.exists())
        self.assertFalse(session.cleanup_allowed)

    def test_clean_pidfd_owned_stop_is_only_process_proof(self) -> None:
        session = self.build()
        session.start()
        self.assertEqual(session.state, "running")
        self.assertIsNotNone(session.pidfd)
        self.assertIsNone(session.process.poll())
        result = session.shutdown()
        self.assertEqual(session.state, "stopped")
        self.assertTrue(session.clean_exit)
        self.assertEqual(session.process.returncode, 0)
        self.assertIsNone(session.pidfd)
        self.assertTrue(result["exact_owned_process_reaped"])
        self.assertTrue(result["zero_exit"])
        self.assertFalse(result["kernel_nbd_disconnected"])
        self.assertFalse(result["dm_io_drained"])
        self.assertFalse(result["backing_cleanup_authorized"])
        self.assertEqual(session.signal_log, ["SIGTERM"])
        self.assert_backing_retained(session)

    def test_one_session_cannot_launch_twice(self) -> None:
        session = self.build()
        session.start()
        with self.assertRaises(Denied):
            session.start()
        self.assertTrue(session.shutdown()["exact_owned_process_reaped"])
        with self.assertRaises(Denied):
            session.start()
        with self.assertRaises(Denied):
            session.shutdown()
        self.assert_backing_retained(session)

    def test_context_exit_without_shutdown_is_denied_and_reaped(self) -> None:
        session = self.build()
        with session:
            self.assertIsNone(session.process.poll())
        self.assertEqual(session.state, "denied")
        self.assertIsNotNone(session.process.returncode)
        self.assertIn("SIGKILL", session.signal_log)
        self.assert_backing_retained(session)

    def test_mismatched_readiness_rejected_and_owned_child_reaped(self) -> None:
        session = self.build("wrong-ready")
        with self.assertRaisesRegex(Denied, "readiness"):
            session.start()
        self.assertEqual(session.state, "denied")
        self.assertIsNotNone(session.process.returncode)
        self.assertIsNone(session.pidfd)
        self.assert_backing_retained(session)

    def test_eof_before_readiness_rejected_and_reaped(self) -> None:
        session = self.build("exit-before-ready")
        with self.assertRaisesRegex(Denied, "readiness"):
            session.start()
        self.assertEqual(session.state, "denied")
        self.assertIsNotNone(session.process.returncode)
        self.assert_backing_retained(session)

    def test_startup_timeout_rejected_and_reaped(self) -> None:
        session = self.build("slow-ready", timeout=0.08)
        with self.assertRaises(Denied):
            session.start()
        self.assertEqual(session.state, "denied")
        self.assertIsNotNone(session.process.returncode)
        self.assertIn("SIGKILL", session.signal_log)
        self.assert_backing_retained(session)

    def test_silent_server_never_produces_readiness(self) -> None:
        session = self.build("silent", timeout=0.1)
        with self.assertRaises(Denied):
            session.start()
        self.assertIsNotNone(session.process.returncode)
        self.assert_backing_retained(session)

    def test_sigterm_ignored_escalates_via_pidfd_only(self) -> None:
        session = self.build("ignore-term", grace=0.08)
        session.start()
        with self.assertRaisesRegex(Denied, "grace period"):
            session.shutdown()
        self.assertEqual(session.state, "denied")
        self.assertFalse(session.clean_exit)
        self.assertEqual(session.signal_log, ["SIGTERM", "SIGKILL"])
        self.assertIsNotNone(session.process.returncode)
        self.assert_backing_retained(session)

    def test_nonzero_exit_denies_even_after_reap(self) -> None:
        session = self.build("fail-term")
        session.start()
        with self.assertRaisesRegex(Denied, "unsuccessfully"):
            session.shutdown()
        self.assertEqual(session.process.returncode, 7)
        self.assertEqual(session.signal_log, ["SIGTERM"])
        self.assertEqual(session.state, "denied")
        self.assert_backing_retained(session)

    def test_spontaneous_exit_does_not_count_as_graceful_shutdown(self) -> None:
        session = self.build("exit-after-ready")
        try:
            session.start()
        except Denied:
            self.assertEqual(session.state, "denied")
        else:
            # Wait for the fixed child to exit after READY before checking
            # that an unsolicited successful exit cannot authorize shutdown.
            time.sleep(0.12)
            with self.assertRaises(Denied):
                session.shutdown()
        self.assertIsNotNone(session.process.returncode)
        self.assertEqual(session.state, "denied")
        self.assertFalse(session.clean_exit)
        self.assert_backing_retained(session)

    def test_pidfd_send_failure_denies_and_kills_exact_owned_child(self) -> None:
        session = self.build()
        session.start()
        genuine = owner.signal.pidfd_send_signal
        injected = []

        def faulty(fd, sig, siginfo=None, flags=0):
            injected.append(sig)
            if sig == signal.SIGTERM:
                raise OSError("simulated pidfd send failure")
            return genuine(fd, sig, siginfo, flags)

        with mock.patch.object(owner.signal, "pidfd_send_signal", side_effect=faulty):
            with self.assertRaises(Denied):
                session.shutdown()
        self.assertEqual(injected, [signal.SIGTERM, signal.SIGKILL])
        self.assertEqual(session.state, "denied")
        self.assertIsNotNone(session.process.returncode)
        self.assert_backing_retained(session)

    def test_failed_term_and_kill_retain_pidfd_until_later_verified_reap(self) -> None:
        session = self.build("ignore-eof")
        session.start()

        def fail_all_signals(*_args, **_kwargs):
            raise OSError("injected untrusted pidfd send failure")

        with mock.patch.object(owner.signal, "pidfd_send_signal",
                               side_effect=fail_all_signals):
            with self.assertRaises(Denied):
                session.shutdown()
        self.assertEqual(session.state, "denied")
        self.assertIsNone(session.process.poll())
        # SIGKILL was also injected as failing, so the stable pidfd must be
        # retained; a failed wait must not discard our only identity token.
        self.assertIsNotNone(session.pidfd)
        self.assertFalse(session.cleanup_allowed)
        session.close()  # now real pidfd SIGKILL is again available
        self.assertIsNotNone(session.process.returncode)
        self.assertIsNone(session.pidfd)
        self.assertIn("SIGKILL", session.signal_log)
        self.assert_backing_retained(session)

    def test_missing_pidfd_support_denies_before_spawning(self) -> None:
        session = self.build()
        with mock.patch.object(owner.os, "pidfd_open", None):
            with self.assertRaisesRegex(Denied, "pidfd_open"):
                session.start()
        self.assertIsNone(session.process)
        self.assertEqual(session.state, "denied")
        self.assert_backing_retained(session)

    def test_pidfd_acquisition_failure_after_spawn_closes_channel_and_reaps(self) -> None:
        session = self.build()
        real_open = owner.os.pidfd_open
        calls = []

        def fail_second(pid, flags=0):
            calls.append(pid)
            if len(calls) == 2:
                raise OSError("synthetic post-spawn pidfd acquisition failed")
            return real_open(pid, flags)

        with mock.patch.object(owner.os, "pidfd_open", side_effect=fail_second):
            with self.assertRaisesRegex(Denied, "synthetic startup denied"):
                session.start()
        self.assertEqual(len(calls), 2)
        self.assertEqual(session.state, "denied")
        self.assertIsNotNone(session.process)
        self.assertIsNotNone(session.process.returncode)
        self.assertIsNone(session.pidfd)
        self.assert_backing_retained(session)

    def test_missing_pidfd_signal_support_denies_before_spawning(self) -> None:
        session = self.build()
        with mock.patch.object(owner.signal, "pidfd_send_signal", None):
            with self.assertRaisesRegex(Denied, "pidfd_send_signal"):
                session.start()
        self.assertIsNone(session.process)
        self.assertEqual(session.state, "denied")
        self.assert_backing_retained(session)

    def test_unsafe_worker_modes_and_input_are_rejected(self) -> None:
        private = self.root / "private"
        private.mkdir(mode=0o700)
        for value in ("/bin/sh", "serve", "nbd", "--device=/dev/nbd0", 0, None):
            with self.subTest(value=value), self.assertRaises(Denied):
                Session(private, mode=value)
        with self.assertRaises(Denied):
            Session(Path("relative"), mode="normal")
        with self.assertRaises(Denied):
            Session(private, mode="normal", start_timeout=0)
        self.assertTrue(self.marker.exists())

    def test_nonprivate_or_symlinked_fixture_denied(self) -> None:
        session = self.build()
        session.directory.chmod(0o755)
        with self.assertRaisesRegex(Denied, "private"):
            session.start()
        self.assertIsNone(session.process)
        self.assert_backing_retained(session)
        target = self.root / "real"
        target.mkdir(mode=0o700)
        link = self.root / "link"
        link.symlink_to(target, target_is_directory=True)
        replacement = Session(link)
        self.addCleanup(replacement.close)
        with self.assertRaisesRegex(Denied, "private"):
            replacement.start()
        self.assertIsNone(replacement.process)

    def test_process_log_is_private_and_kept_for_diagnosis(self) -> None:
        session = self.build("fail-term")
        session.start()
        with self.assertRaises(Denied):
            session.shutdown()
        log = session.directory / "server.log"
        info = log.stat()
        self.assertTrue(stat.S_ISREG(info.st_mode))
        self.assertEqual(info.st_nlink, 1)
        self.assertEqual(info.st_mode & 0o077, 0)
        self.assert_backing_retained(session)

    def test_close_is_idempotent_and_never_authorizes_cleanup(self) -> None:
        session = self.build()
        session.start()
        session.close()
        session.close()
        self.assertEqual(session.state, "denied")
        self.assertIsNone(session.pidfd)
        self.assertIsNotNone(session.process.returncode)
        self.assert_backing_retained(session)

    def test_control_socket_eof_revokes_owner_readiness(self) -> None:
        session = self.build()
        session.start()
        # The exact synthetic child must not survive owner channel closure
        # even while the controller process itself is still alive.
        session.sock.close()
        session.sock = None
        self.assertEqual(session.process.wait(timeout=1.0), 0)
        with self.assertRaises(Denied):
            session.shutdown()
        self.assertEqual(session.state, "denied")
        self.assert_backing_retained(session)

    def test_parent_death_guard_failure_never_announces_ready(self) -> None:
        session = self.build("pdeath-fail")
        with self.assertRaises(Denied):
            session.start()
        self.assertEqual(session.state, "denied")
        self.assertIsNotNone(session.process.returncode)
        self.assert_backing_retained(session)

    def test_post_ready_descendant_and_exec_attempts_denied_by_seccomp(self) -> None:
        session = self.build("attempt-spawn")
        session.start()
        self.assertEqual(session.sock.recv(128), b"FORK_DENIED")
        self.assertEqual(session.sock.recv(128), b"EXEC_DENIED")
        self.assertTrue(session.shutdown()["exact_owned_process_reaped"])
        self.assert_backing_retained(session)

    def test_unexpected_controller_death_reaps_exact_child_by_pidfd(self) -> None:
        if not hasattr(socket, "SCM_RIGHTS"):
            self.skipTest("SCM_RIGHTS unavailable")
        helper = HERE / "nbd-pidfd-crash-owner.py"
        cases = (
            ("pre-ready", b"PRE_READY"),
            ("post-ready", b"READY"),
            ("idle", b"READY"),
            ("ignore-term-idle", b"READY"),
            ("pdeath-only", b"READY"),
        )
        for stage, expected in cases:
            with self.subTest(stage=stage):
                self.counter += 1
                base = self.root / f"crash-case-{self.counter}"
                base.mkdir(mode=0o700)
                monitor, controller = socket.socketpair(
                    socket.AF_UNIX, socket.SOCK_SEQPACKET
                )
                monitor.settimeout(3.0)
                observer_fd = None
                try:
                    owner_proc = subprocess.Popen(
                        [sys.executable, "-B", str(helper),
                         str(controller.fileno()), stage, str(base)],
                        pass_fds=(controller.fileno(),), close_fds=True,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        # The mock child keeps its own private server.log.
                        # A never-consumed stderr pipe leaks a test descriptor.
                        stderr=subprocess.DEVNULL,
                    )
                    controller.close()
                    payload, ancillary, msgflags, _ = monitor.recvmsg(
                        64, socket.CMSG_SPACE(array("i", [0]).itemsize))
                    self.assertEqual(payload, expected)
                    self.assertFalse(msgflags & socket.MSG_CTRUNC)
                    fds = []
                    for level, kind, value in ancillary:
                        if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                            received = array("i")
                            received.frombytes(value[:len(value) - (len(value) % received.itemsize)])
                            fds.extend(received)
                    self.assertEqual(len(fds), 1)
                    observer_fd = fds[0]
                    if stage in ("idle", "ignore-term-idle", "pdeath-only"):
                        monitor.sendall(b"CRASH")
                    controller_rc = owner_proc.wait(timeout=2.0)
                    self.assertNotEqual(controller_rc, 0)
                    poller = select.poll()
                    poller.register(observer_fd, select.POLLIN | select.POLLHUP | select.POLLERR)
                    self.assertTrue(
                        poller.poll(2000),
                        "exact synthetic child did not exit after owner crash",
                    )
                    self.assert_backing_retained(self.build())
                finally:
                    if observer_fd is not None:
                        # If the test fails, still direct recovery to the
                        # exact kernel pidfd. Never use a recyclable PID.
                        try:
                            if not select.select([observer_fd], [], [], 0)[0]:
                                signal.pidfd_send_signal(observer_fd, signal.SIGKILL, None, 0)
                        except OSError:
                            pass
                        os.close(observer_fd)
                    controller.close()
                    monitor.close()
                    if "owner_proc" in locals() and owner_proc.poll() is None:
                        try:
                            owner_proc.wait(timeout=0.2)
                        except subprocess.TimeoutExpired:
                            # The helper has no production side effects;
                            # numeric PID signaling is forbidden here too.
                            self.fail("test-owned crash helper failed to exit")

    def test_source_forbids_numeric_pid_signal_fallback_or_nbd_attachment(self) -> None:
        source = (HERE / "nbd-pidfd-owned-session.py").read_text(encoding="utf-8")
        child = (HERE / "nbd-pidfd-owned-mock-child.py").read_text(encoding="utf-8")
        for word in ("os.kill(", ".terminate(", ".send_signal(", "dmsetup(",
                     "losetup(", "fcntl.ioctl(", '"/dev/nbd', "NBD_SET_SOCK"):
            with self.subTest(word=word):
                self.assertNotIn(word, source + child)
        self.assertIn("signal.pidfd_send_signal(", source)
        self.assertIn("subprocess.Popen(", source)
        self.assertNotIn("os.unlink(", source)
        self.assert_backing_retained(self.build())


if __name__ == "__main__":
    unittest.main()
