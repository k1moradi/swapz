#!/usr/bin/env python3
"""Real separate-service and direct-worker rootless recall integration.

The exact subprocess and its direct pinned dd workers operate ONLY on private
temporary regular files. No mapper, loop, NBD, swap, module or physical device.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
FIXTURE_PATH = HERE / "recall-role-process-fixture.py"


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


fixture = load("swapz_separate_process_fixture_tests", "recall-role-process-fixture.py")
bridge_module = load("swapz_separate_process_bridge_tests", "recall-control-bridge.py")
RoleAdapter = bridge_module.adapter_module.RecallRoleIPCAdapter
RoleError = bridge_module.adapter_module.RecallIPCError
RootlessRoleBridge = bridge_module.RootlessRoleBridge


class RootlessDirectProcessSession:
    """Own an exact service process, socket, all fixtures and cleanup."""

    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="swapz-process-role-")
        self.root = Path(self.temp.name)
        self.directory = self.root / "fixture"
        self.directory.mkdir(mode=0o700)
        self.expected = fixture.source_bytes()
        source = self.directory / "pages.bin"
        source.write_bytes(self.expected)
        source.chmod(0o600)
        mapper = self.root / "synthetic-mapper.bin"
        mapper.write_bytes(bytes(len(self.expected)))
        mapper.chmod(0o600)
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        mapper_fd = os.open(mapper, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            self.process = subprocess.Popen(
                [sys.executable, "-B", str(FIXTURE_PATH),
                 str(child.fileno()), str(mapper_fd)],
                cwd=self.directory, pass_fds=(child.fileno(), mapper_fd),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=None, close_fds=True,
            )
        except BaseException:
            parent.close()
            raise
        finally:
            child.close()
            os.close(mapper_fd)

        self.client = fixture.AttestedClient(
            parent, service_process=self.process, timeout=8.0
        )
        self.adapter = RoleAdapter(
            self.client, self.process, verify_role_result=self._verify_role,
            exit_timeout=8.0,
        )
        self.bridge = RootlessRoleBridge(
            client=self.client, process=self.process, adapter=self.adapter
        )
        self.request_id = 0
        self.cleanup_marker = self.root / "synthetic-backing.marker"
        self.cleanup_marker.write_text("preserve until explicitly finalized")

    def _verify_role(self, role: str) -> bool:
        matches = [handle for handle, known in self.adapter._role_by_handle.items()
                   if known == role]
        return (len(matches) == 1 and self.client.verified_role(role, matches[0]))

    def dispatch(self, op: str, **data):
        self.request_id += 1
        return self.bridge.dispatch({"id": self.request_id, "op": op, **data})

    def launch(self, role: str) -> str:
        try:
            result = self.dispatch("LAUNCH_ROLE", role=role)
        except (RoleError, bridge_module.BridgeError) as exc:
            # Preserve the original fail-closed error type and add only
            # bounded *rootless test* evidence for fast-child READY races.
            diagnostic = self.client.last_launch_diagnostic
            raise type(exc)(
                f"{exc}; synthetic_launch_role={role}; "
                f"service_launch={diagnostic!r}; "
                f"service_returncode={self.process.poll()!r}"
            ) from exc
        assert result["status"] == "ready"
        return result["handle"]

    def wait(self, handle: str) -> None:
        result = self.dispatch("WAIT", handle=handle, timeout_ms=5000)
        assert result["status"] == "reaped", result

    def run_five(self) -> tuple[str, ...]:
        writer = self.launch("writer")
        first = self.launch("a")
        self.wait(first)
        second = self.launch("b")
        self.wait(second)
        a2 = self.launch("a2")
        b2 = self.launch("b2")
        self.wait(a2)
        self.wait(b2)
        self.wait(writer)
        return (writer, first, second, a2, b2)

    def finalize_synthetic_cleanup(self) -> None:
        stopped = self.dispatch("STOP_ALL")
        assert stopped["status"] == "stopped"
        assert len(stopped["workers"]) == 5
        shutdown = self.dispatch("SHUTDOWN")
        assert shutdown["status"] == "shutdown_verified"
        result = self.dispatch("FINALIZE")
        assert result["status"] == "cleanup_authorized" and result["cleanup_allowed"] is True
        assert self.client.cleanup_authorized is True
        assert self.process.returncode == 0
        # This is the ONLY cleanup action allowed in this rootless fixture.
        self.cleanup_marker.unlink()

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            # Kill only the test-owned exact service via its stable pidfd;
            # never send a numeric-PID signal to an unrelated host process.
            if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
                pidfd = os.pidfd_open(self.process.pid)
                try:
                    signal.pidfd_send_signal(pidfd, signal.SIGKILL)
                finally:
                    os.close(pidfd)
                self.process.wait(timeout=5)
            else:
                raise AssertionError("owned service did not exit; no pidfd fallback")
        finally:
            self.temp.cleanup()


class ActualServiceAndDirectDDTests(unittest.TestCase):
    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("fixture is intentionally prohibited under root")
        if not Path("/usr/bin/dd").exists():
            self.skipTest("pinned local test dd unavailable")
        self.session = RootlessDirectProcessSession()
        self.addCleanup(self.session.close)

    def test_real_service_process_five_pinned_workers_and_exact_readback(self):
        handles = self.session.run_five()
        self.assertEqual(len(set(handles)), 5)
        self.assertEqual(set(self.session.client.receipts),
                         {"writer", "a", "b", "a2", "b2"})
        self.assertTrue(self.session.cleanup_marker.exists())
        self.session.finalize_synthetic_cleanup()
        self.assertFalse(self.session.cleanup_marker.exists())
        self.assertFalse(self.session.bridge.failed)

    def test_replaced_readback_path_cannot_fake_verified_output(self):
        self.session.launch("writer")
        reader = self.session.launch("a")
        original = self.session.directory / "read-a"
        original.rename(self.session.directory / "displaced-a")
        # The attacker supplies the correct bytes, but NOT the pinned inode.
        original.write_bytes(fixture.reference_page(0))
        with self.assertRaises((RoleError, bridge_module.BridgeError)):
            self.session.wait(reader)
        self.assertFalse(self.session.adapter.cleanup_authorized)
        self.assertTrue(self.session.cleanup_marker.exists())

    def test_immutable_reference_rejects_source_corruption(self):
        source = self.session.directory / "pages.bin"
        mutated = bytearray(self.session.expected)
        mutated[4096 * 4] ^= 0xFF
        source.write_bytes(mutated)
        self.session.launch("writer")
        # A very short-lived 4 KiB dd can finish before the supervisor
        # confirms READY. Such unconfirmed admission is itself an
        # acceptable, sticky failure and must preserve backing. If launch
        # is confirmed, the corrupted page must be rejected on WAIT.
        with self.assertRaises((RoleError, bridge_module.BridgeError)):
            reader = self.session.launch("b")
            self.session.wait(reader)
        self.assertTrue(self.session.cleanup_marker.exists())
        self.assertFalse(self.session.adapter.cleanup_authorized)

    def test_unconfirmed_startup_receipt_cannot_authorize_synthetic_cleanup(self):
        # Fully rootless fault injection. No actual worker is admitted by
        # the forged launch response, and the unrelated test-owned service
        # is closed by the fixture's normal teardown.
        refused = {
            "status": "launch_failure", "ok": False,
            "cleanup_allowed": False, "preserve_backing": True,
            "all_reaped": False,
            "error": "child-exit before verified exec READY",
        }
        with mock.patch.object(self.session.client, "call", return_value=refused):
            with self.assertRaisesRegex(RoleError, "unconfirmed or duplicated"):
                self.session.launch("writer")
        self.assertTrue(self.session.bridge.failed)
        self.assertTrue(self.session.cleanup_marker.exists())
        self.assertFalse(self.session.adapter.cleanup_authorized)
        self.assertFalse(self.session.client.cleanup_authorized)

    def test_missing_or_malformed_ready_handle_fails_closed(self):
        # Test bad READY receipts without launching any real dd worker.
        for handle in (None, "", 17, "!!!"):
            with self.subTest(handle=handle):
                session = RootlessDirectProcessSession()
                try:
                    forged = {
                        "status": "ready", "ok": True, "cleanup_allowed": False,
                        "preserve_backing": True, "all_reaped": False,
                        "handle": handle,
                    }
                    with mock.patch.object(session.client, "call", return_value=forged):
                        with self.assertRaises(RoleError):
                            session.launch("writer")
                    self.assertTrue(session.cleanup_marker.exists())
                    self.assertFalse(session.adapter.cleanup_authorized)
                    self.assertTrue(session.bridge.failed)
                finally:
                    session.close()

    def test_duplicate_ready_handle_fails_closed_and_preserves_backing(self):
        # Even if a trusted IPC client erroneously forwarded a duplicate
        # READY handle, the role adapter must reject it locally.
        token = "synthetic-duplicate-role-handle"
        self.assertTrue(self.session.adapter._valid_handle(token))
        self.session.adapter.handles.append(token)
        forged = {
            "status": "ready", "ok": True, "cleanup_allowed": False,
            "preserve_backing": True, "all_reaped": False,
            "handle": token,
        }
        with mock.patch.object(self.session.client, "call", return_value=forged):
            with self.assertRaisesRegex(RoleError, "unconfirmed or duplicated"):
                self.session.launch("writer")
        self.assertTrue(self.session.cleanup_marker.exists())
        self.assertFalse(self.session.adapter.cleanup_authorized)
        self.assertTrue(self.session.bridge.failed)

    def test_premature_writer_wait_and_missing_phase_preserve_backing(self):
        writer = self.session.launch("writer")
        with self.assertRaisesRegex(RoleError, "writer must remain"):
            self.session.wait(writer)
        self.assertTrue(self.session.cleanup_marker.exists())
        with self.assertRaises(bridge_module.BridgeError):
            self.session.dispatch("FINALIZE")

    def test_service_crash_denies_cleanup_even_when_worker_exits(self):
        if not (hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal")):
            self.skipTest("pidfd_send_signal unavailable; no numeric PID fallback")
        self.session.launch("writer")
        fd = os.pidfd_open(self.session.process.pid)
        try:
            signal.pidfd_send_signal(fd, signal.SIGKILL)
        finally:
            os.close(fd)
        self.session.process.wait(timeout=5)
        with self.assertRaises((RoleError, bridge_module.BridgeError)):
            self.session.launch("a")
        self.assertNotEqual(self.session.process.returncode, 0)
        self.assertTrue(self.session.cleanup_marker.exists())
        self.assertFalse(self.session.adapter.cleanup_authorized)

    def test_aborted_session_and_socket_eof_preserves_backing(self):
        self.session.launch("writer")
        self.session.client.sock.close()
        self.session.process.wait(timeout=8)
        self.assertNotEqual(self.session.process.returncode, 0)
        self.assertTrue(self.session.cleanup_marker.exists())
        self.assertFalse(self.session.adapter.cleanup_authorized)

    def test_a2_wait_before_b2_admission_denied(self):
        self.session.launch("writer")
        a2 = self.session.launch("a2")
        with self.assertRaisesRegex(RoleError, "both concurrent"):
            self.session.wait(a2)
        self.assertTrue(self.session.cleanup_marker.exists())


if __name__ == "__main__":
    unittest.main()
