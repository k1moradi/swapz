#!/usr/bin/env python3
"""Rootless IPC, lifecycle, and fail-closed tests for pidfd supervisor service."""

from __future__ import annotations

import importlib.util
import json
import socket
import struct
import subprocess
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
SERVICE_PATH = HERE / "test-child-supervisor-service.py"
SUPERVISOR_PATH = HERE / "test-child-supervisor.py"


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


supervisor_module = load_module("service_test_supervisor", SUPERVISOR_PATH)
service_module = load_module("service_test_module", SERVICE_PATH)

SupervisorError = service_module.SupervisorError
StopReport = supervisor_module.StopReport
WorkerResult = supervisor_module.WorkerResult
ChannelFailure = service_module.ChannelFailure
ProtocolFailure = service_module.ProtocolFailure
SupervisorControlClient = service_module.SupervisorControlClient
SupervisorControlService = service_module.SupervisorControlService
SupervisorUnavailable = service_module.SupervisorUnavailable
MAX_FRAME_BYTES = service_module.MAX_FRAME_BYTES
_HEADER = struct.Struct("!I")


class ServiceProcess:
    def __init__(self) -> None:
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.process = subprocess.Popen(
            [sys.executable, str(SERVICE_PATH), "--fd", str(child.fileno())],
            pass_fds=(child.fileno(),),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            close_fds=True,
        )
        child.close()
        self.client = SupervisorControlClient(parent, timeout=12.0)

    def finish(self, *, timeout: float = 8.0) -> tuple[int, str, str]:
        out, err = self.process.communicate(timeout=timeout)
        self.client.confirm_service_exit(self.process.returncode or 0)
        self.client.close()
        return self.process.returncode or 0, out, err

    def abort(self) -> None:
        if self.process.poll() is not None:
            self.client.close()
            return
        try:
            self.client.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.client.close()
        try:
            self.process.communicate(timeout=8.0)
        except subprocess.TimeoutExpired:
            # Test workers are capped to short sleeps and have already exited
            # by this point.  This signal targets only the service process
            # created by this test helper, never an unrelated process.
            self.process.terminate()
            self.process.communicate(timeout=3.0)


class FakeServiceSupervisor:
    """Service API fake; it creates no process and invokes no OS signal."""

    def __init__(self, *, stop_error: str | None = None, launch_error: bool = False) -> None:
        self.records: dict[str, SimpleNamespace] = {}
        self.calls: list[tuple[str, ...]] = []
        self.callback_count = 0
        self.stop_error = stop_error
        self.launch_error = launch_error
        self.next = 0
        self.launch_failure_error: str | None = None

    def launch(self, argv: tuple[str, ...], *, env: dict[str, str]) -> str:
        self.next += 1
        handle = f"fake-handle-{self.next}"
        self.records[handle] = SimpleNamespace(reaped=False)
        if self.launch_error:
            self.launch_failure_error = "injected post-pidfd startup failure"
            raise SupervisorError("injected post-pidfd startup failure", preserve_required=True,
                                  handle=handle, child_reaped=False)
        return handle

    def worker_for_test(self, handle: str) -> SimpleNamespace:
        if handle not in self.records:
            raise KeyError(handle)
        return self.records[handle]

    def wait(self, handle: str, timeout: float) -> WorkerResult:
        self.records[handle].reaped = True
        return WorkerResult(handle, True, 0, False, ())

    def cleanup_after_stop(self, handles: list[str] | tuple[str, ...], callback: Any) -> tuple[StopReport, object | None]:
        self.calls.append(tuple(handles))
        results = []
        for handle, record in self.records.items():
            record.reaped = self.stop_error != "wait/reap failure"
            injected = self.stop_error if self.stop_error and handle == "fake-handle-2" else None
            if self.launch_failure_error and handle == "fake-handle-1":
                injected = self.launch_failure_error
            errors = (injected,) if injected else ()
            results.append(WorkerResult(handle, record.reaped, 0 if record.reaped else None, False, errors))
        clean = all(row.reaped and not row.errors for row in results) and set(handles) == set(self.records)
        result: object | None = None
        if clean:
            self.callback_count += 1
            result = callback()
        return StopReport(tuple(results), (), clean), result


def raw_frame(value: dict[str, Any]) -> bytes:
    payload = json.dumps(value, separators=(",", ":")).encode()
    return _HEADER.pack(len(payload)) + payload


def run_in_process(raw: bytes, service: SupervisorControlService | None = None) -> tuple[Any, list[dict[str, Any]]]:
    peer, server = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    peer.settimeout(1.0)
    responses: list[dict[str, Any]] = []
    try:
        peer.sendall(raw)
        peer.shutdown(socket.SHUT_WR)
        outcome = (service or SupervisorControlService(io_timeout=0.5)).serve(server)
        server.close()
        while True:
            try:
                response = service_module.recv_frame(peer, 1.0, allow_clean_eof=True)
            except service_module.ProtocolError:
                break
            if response is None:
                break
            responses.append(response)
        return outcome, responses
    finally:
        server.close()
        peer.close()


class SupervisorServiceProtocolTests(unittest.TestCase):
    def test_empty_service_requires_stop_all_shutdown_and_clean_exit(self) -> None:
        session = ServiceProcess()
        try:
            stop = session.client.call("stop_all", handles=[])
            self.assertEqual(stop["status"], "complete")
            self.assertTrue(stop["cleanup_allowed"])
            self.assertFalse(session.client.cleanup_authorized)
            shutdown = session.client.call("shutdown")
            self.assertEqual(shutdown["status"], "shutdown")
            code, _, _ = session.finish()
            self.assertEqual(code, 0)
            self.assertTrue(session.client.cleanup_authorized)
        finally:
            session.abort()

    def test_two_opaque_launches_before_either_wait_and_full_shutdown(self) -> None:
        session = ServiceProcess()
        try:
            first = session.client.call("launch", command="sleep", duration_ms=4000)
            second = session.client.call("launch", command="sleep", duration_ms=4000)
            third = session.client.call("launch", command="sleep", duration_ms=4000)
            self.assertEqual([first["status"], second["status"], third["status"]], ["ready"] * 3)
            handles = [first["handle"], second["handle"], third["handle"]]
            self.assertTrue(all(isinstance(value, str) and not value.isdecimal() for value in handles))
            self.assertNotEqual(handles[0], handles[1])
            first_wait = session.client.call("wait", handle=handles[0], timeout_ms=1)
            self.assertEqual(first_wait["status"], "running")
            stopped = session.client.call("stop_all", handles=handles)
            self.assertTrue(stopped["all_reaped"])
            self.assertTrue(stopped["cleanup_allowed"])
            self.assertEqual(len(stopped["workers"]), 3)
            self.assertTrue(all(worker["reaped"] for worker in stopped["workers"]))
            shutdown = session.client.call("shutdown")
            self.assertEqual(shutdown["status"], "shutdown")
            code, _, err = session.finish()
            self.assertEqual(code, 0, err)
            self.assertTrue(session.client.cleanup_authorized)
        finally:
            session.abort()

    def test_wait_timeout_then_natural_success_is_cached_and_cleanup_is_explicit(self) -> None:
        session = ServiceProcess()
        try:
            started = session.client.call("launch", command="sleep", duration_ms=1000)
            handle = started["handle"]
            early = session.client.call("wait", handle=handle, timeout_ms=0)
            self.assertEqual(early["status"], "running")
            done = session.client.call("wait", handle=handle, timeout_ms=3000)
            self.assertEqual(done["status"], "reaped")
            self.assertEqual(done["worker"]["exit_code"], 0)
            again = session.client.call("wait", handle=handle, timeout_ms=0)
            self.assertEqual(again["status"], "reaped")
            stopped = session.client.call("stop_all", handles=[handle])
            self.assertTrue(stopped["cleanup_allowed"])
            session.client.call("shutdown")
            code, _, _ = session.finish()
            self.assertEqual(code, 0)
            self.assertTrue(session.client.cleanup_authorized)
        finally:
            session.abort()

    def test_nonzero_natural_exit_is_reported_and_denies_cleanup(self) -> None:
        session = ServiceProcess()
        try:
            started = session.client.call("launch", command="exit", code=7)
            handle = started["handle"]
            result = session.client.call("wait", handle=handle, timeout_ms=3000)
            self.assertEqual(result["status"], "lifecycle_failure")
            self.assertEqual(result["worker"]["exit_code"], 7)
            stopped = session.client.call("stop_all", handles=[handle])
            self.assertFalse(stopped["cleanup_allowed"])
            self.assertTrue(stopped["all_reaped"])
            shutdown = session.client.call("shutdown")
            self.assertEqual(shutdown["status"], "shutdown_with_lifecycle_failure")
            code, _, _ = session.finish()
            self.assertNotEqual(code, 0)
            self.assertFalse(session.client.cleanup_authorized)
        finally:
            session.abort()

    def test_shutdown_rejection_is_recoverable_then_stop_all_succeeds(self) -> None:
        session = ServiceProcess()
        try:
            started = session.client.call("launch", command="sleep", duration_ms=4000)
            handle = started["handle"]
            rejected = session.client.call("shutdown")
            self.assertEqual(rejected["status"], "workers_unresolved")
            self.assertFalse(rejected["all_reaped"])
            stopped = session.client.call("stop_all", handles=[handle])
            self.assertTrue(stopped["cleanup_allowed"])
            session.client.call("shutdown")
            code, _, _ = session.finish()
            self.assertEqual(code, 0)
            self.assertTrue(session.client.cleanup_authorized)
        finally:
            session.abort()

    def test_launch_after_stop_all_is_rejected_and_sticky(self) -> None:
        session = ServiceProcess()
        try:
            stopped = session.client.call("stop_all", handles=[])
            self.assertTrue(stopped["cleanup_allowed"])
            denied = session.client.call("launch", command="exit", code=0)
            self.assertEqual(denied["status"], "admission_closed")
            shutdown = session.client.call("shutdown")
            self.assertEqual(shutdown["status"], "shutdown_with_lifecycle_failure")
            code, _, _ = session.finish()
            self.assertNotEqual(code, 0)
            self.assertFalse(session.client.cleanup_authorized)
        finally:
            session.abort()

    def test_lost_connection_before_launch_denies_cleanup(self) -> None:
        session = ServiceProcess()
        session.client.close()
        _, err = session.process.communicate(timeout=5.0)
        code = session.process.returncode
        self.assertEqual(code, 2)
        self.assertIn("controller disconnected", err)
        self.assertIn("external_cleanup_allowed=false", err)
        self.assertFalse(session.client.cleanup_authorized)

    def test_lost_connection_while_worker_runs_reaps_but_caller_must_preserve(self) -> None:
        session = ServiceProcess()
        started = session.client.call("launch", command="sleep", duration_ms=4000)
        session.client.close()
        _, err = session.process.communicate(timeout=8.0)
        code = session.process.returncode
        self.assertEqual(code, 2)
        self.assertIn("internal_all_reaped=true", err)
        self.assertIn("external_cleanup_allowed=false", err)
        self.assertFalse(session.client.cleanup_authorized)
        self.assertEqual(started["status"], "ready")

    def test_lost_stop_all_response_denies_cleanup_after_internal_reap(self) -> None:
        session = ServiceProcess()
        started = session.client.call("launch", command="sleep", duration_ms=4000)
        service_module.send_frame(
            session.client.sock,
            {"id": 2, "op": "stop_all", "handles": [started["handle"]]},
            1.0,
        )
        session.client.close()
        _, err = session.process.communicate(timeout=8.0)
        code = session.process.returncode
        self.assertEqual(code, 2)
        self.assertIn("response delivery failed", err)
        self.assertIn("internal_all_reaped=true", err)
        self.assertIn("external_cleanup_allowed=false", err)
        self.assertFalse(session.client.cleanup_authorized)

    def test_unknown_wait_handle_fails_closed_and_stops_registered_workers(self) -> None:
        session = ServiceProcess()
        try:
            started = session.client.call("launch", command="sleep", duration_ms=4000)
            bad = session.client.call("wait", handle="unknown-token", timeout_ms=0)
            self.assertEqual(bad["status"], "protocol_error")
            self.assertFalse(session.client.cleanup_authorized)
            session.client.close()
            _, err = session.process.communicate(timeout=8.0)
            code = session.process.returncode
            self.assertEqual(code, 2)
            self.assertIn("internal_all_reaped=true", err)
            self.assertNotEqual(started["handle"], "unknown-token")
        finally:
            session.abort()

    def test_omitted_and_duplicate_handles_deny_cleanup_after_all_attempts(self) -> None:
        for supplied in ([], ["duplicate-placeholder", "duplicate-placeholder"]):
            with self.subTest(supplied=supplied):
                session = ServiceProcess()
                try:
                    started = session.client.call("launch", command="sleep", duration_ms=4000)
                    handles = supplied if supplied else []
                    if supplied:
                        handles = [started["handle"], started["handle"]]
                    stopped = session.client.call("stop_all", handles=handles)
                    self.assertEqual(stopped["status"], "lifecycle_failure")
                    self.assertTrue(stopped["all_reaped"])
                    self.assertFalse(stopped["cleanup_allowed"])
                    session.client.call("shutdown")
                    code, _, _ = session.finish()
                    self.assertNotEqual(code, 0)
                    self.assertFalse(session.client.cleanup_authorized)
                finally:
                    session.abort()

    def test_unknown_fields_numeric_pid_and_arbitrary_commands_are_rejected(self) -> None:
        fake = FakeServiceSupervisor()
        service = SupervisorControlService(supervisor=fake, io_timeout=0.5)
        requests = [
            {"id": 1, "op": "launch", "command": "arbitrary", "argv": ["/bin/touch", "/tmp/no"]},
        ]
        outcome, responses = run_in_process(b"".join(raw_frame(row) for row in requests), service)
        self.assertEqual(outcome.exit_code, 2)
        self.assertEqual(responses[0]["status"], "protocol_error")
        self.assertEqual(fake.next, 0)
        self.assertEqual(fake.callback_count, 1)  # In-memory authorization marker only.

        service2 = SupervisorControlService(supervisor=FakeServiceSupervisor(), io_timeout=0.5)
        outcome2, responses2 = run_in_process(raw_frame({"id": 1, "op": "signal", "pid": 1234,
                                                         "signal": 9}), service2)
        self.assertEqual(outcome2.exit_code, 2)
        self.assertEqual(responses2[0]["status"], "protocol_error")

    def test_numeric_supervisor_token_is_never_exposed_or_authorized(self) -> None:
        class NumericHandleSupervisor(FakeServiceSupervisor):
            def launch(self, argv: tuple[str, ...], *, env: dict[str, str]) -> str:
                self.records["424242"] = SimpleNamespace(reaped=False)
                raise SupervisorError("injected invalid token", preserve_required=True,
                                      handle="424242", child_reaped=False)

        fake = NumericHandleSupervisor()
        service = SupervisorControlService(supervisor=fake, io_timeout=0.5)
        requests = [
            {"id": 1, "op": "launch", "command": "sleep", "duration_ms": 1},
            {"id": 2, "op": "stop_all", "handles": []},
            {"id": 3, "op": "shutdown"},
        ]
        outcome, responses = run_in_process(b"".join(raw_frame(row) for row in requests), service)
        self.assertIsNone(responses[0].get("handle"))
        self.assertFalse(responses[1]["cleanup_allowed"])
        self.assertFalse(responses[1]["all_reaped"])
        self.assertNotIn("424242", json.dumps(responses))
        self.assertEqual(responses[2]["status"], "workers_unresolved")
        self.assertEqual(outcome.exit_code, 2)

    def test_protocol_rejects_replayed_ids_duplicate_json_keys_and_unknown_operations(self) -> None:
        cases = [
            raw_frame({"id": 1, "op": "launch", "command": "sleep", "duration_ms": 0})
            + raw_frame({"id": 1, "op": "launch", "command": "sleep", "duration_ms": 0}),
            _HEADER.pack(len(b'{"id":1,"id":2}')) + b'{"id":1,"id":2}',
            raw_frame({"id": 1, "op": "not-supported"}),
        ]
        expected_ids = [1, None, 1]
        for raw, expected_id in zip(cases, expected_ids):
            with self.subTest(expected_id=expected_id):
                outcome, responses = run_in_process(raw, SupervisorControlService(io_timeout=0.5))
                self.assertEqual(outcome.exit_code, 2)
                self.assertTrue(responses)
                self.assertEqual(responses[-1]["status"], "protocol_error")
                self.assertEqual(responses[-1]["id"], expected_id)

    def test_requests_queued_after_shutdown_are_not_processed(self) -> None:
        fake = FakeServiceSupervisor()
        raw = raw_frame({"id": 1, "op": "shutdown"}) + raw_frame(
            {"id": 2, "op": "launch", "command": "exit", "code": 0}
        )
        outcome, responses = run_in_process(raw, SupervisorControlService(supervisor=fake, io_timeout=0.5))
        self.assertEqual(outcome.exit_code, 0)
        self.assertEqual([row["status"] for row in responses], ["shutdown"])
        self.assertEqual(fake.next, 0)

    def test_protocol_rejects_oversized_malformed_and_partial_frames(self) -> None:
        malformed_json = b"nope"
        cases = [
            _HEADER.pack(MAX_FRAME_BYTES + 1),
            _HEADER.pack(len(malformed_json)) + malformed_json,
            _HEADER.pack(100) + b"{\"id\":1",
            _HEADER.pack(0),
        ]
        for raw in cases:
            with self.subTest(raw=raw[:12]):
                outcome, responses = run_in_process(raw, SupervisorControlService(io_timeout=0.5))
                self.assertEqual(outcome.exit_code, 2)
                self.assertEqual(len(responses), 1)
                self.assertEqual(responses[0]["status"], "protocol_error")
                self.assertFalse(responses[0]["cleanup_allowed"])

    def test_partial_frame_timeout_is_finite_and_preserves(self) -> None:
        peer, server = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        peer.sendall(_HEADER.pack(4))
        start = time.monotonic()
        outcome = SupervisorControlService(io_timeout=0.05).serve(server)
        elapsed = time.monotonic() - start
        server.close()
        peer.close()
        self.assertEqual(outcome.exit_code, 2)
        self.assertLess(elapsed, 1.0)
        self.assertFalse(outcome.cleanup_allowed)

    def test_client_timeout_and_malformed_response_fail_closed(self) -> None:
        client_socket, silent_peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        client = SupervisorControlClient(client_socket, timeout=0.05)
        with self.assertRaises(SupervisorUnavailable):
            client.call("shutdown")
        self.assertFalse(client.cleanup_authorized)
        client.close()
        silent_peer.close()

        client_socket2, peer2 = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        client2 = SupervisorControlClient(client_socket2, timeout=0.5)
        service_module.send_frame(peer2, {"id": 99, "ok": True, "status": "shutdown",
                                          "cleanup_allowed": True, "preserve_backing": False,
                                          "all_reaped": True}, 0.5)
        with self.assertRaises(ProtocolFailure):
            client2.call("shutdown")
        self.assertFalse(client2.cleanup_authorized)
        client2.close()
        peer2.close()

    def test_write_deadline_is_finite_and_reserved_client_fields_are_denied(self) -> None:
        sender, receiver = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        sender.setblocking(False)
        sender.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)
        start = time.monotonic()
        with self.assertRaises(service_module.ProtocolError):
            service_module._send_all(sender, b"x" * (1024 * 1024), time.monotonic() + 0.05)
        self.assertLess(time.monotonic() - start, 1.0)
        sender.close()
        receiver.close()

        client_socket, peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        client = SupervisorControlClient(client_socket, timeout=0.5)
        with self.assertRaises(ValueError):
            client.call("launch", id=99, command="exit", code=0)
        self.assertFalse(client.cleanup_authorized)
        client.close()
        peer.close()

    def test_service_unavailability_after_stop_response_denies_final_authorization(self) -> None:
        client_socket, peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        client = SupervisorControlClient(client_socket, timeout=0.5)
        service_module.send_frame(peer, {"id": 1, "ok": True, "status": "complete",
                                         "cleanup_allowed": True, "preserve_backing": False,
                                         "all_reaped": True}, 0.5)
        response = client.call("stop_all", handles=[])
        self.assertEqual(response["status"], "complete")
        peer.close()
        with self.assertRaises(ChannelFailure):
            client.call("shutdown")
        self.assertFalse(client.confirm_service_exit(0))
        client.close()

    def test_three_worker_failure_denies_authorization_but_accounts_for_all(self) -> None:
        fake = FakeServiceSupervisor(stop_error="injected pidfd signal failure")
        service = SupervisorControlService(supervisor=fake, io_timeout=0.5)
        requests = [
            {"id": 1, "op": "launch", "command": "sleep", "duration_ms": 1},
            {"id": 2, "op": "launch", "command": "sleep", "duration_ms": 1},
            {"id": 3, "op": "launch", "command": "sleep", "duration_ms": 1},
            {"id": 4, "op": "stop_all", "handles": ["fake-handle-1", "fake-handle-2", "fake-handle-3"]},
            {"id": 5, "op": "shutdown"},
        ]
        outcome, responses = run_in_process(b"".join(raw_frame(row) for row in requests), service)
        self.assertEqual([row["status"] for row in responses[:3]], ["ready"] * 3)
        stop = responses[3]
        self.assertEqual(stop["status"], "lifecycle_failure")
        self.assertTrue(stop["all_reaped"])
        self.assertFalse(stop["cleanup_allowed"])
        self.assertEqual(fake.calls, [("fake-handle-1", "fake-handle-2", "fake-handle-3")])
        self.assertEqual(fake.callback_count, 0)
        self.assertEqual(outcome.exit_code, 3)

    def test_wait_reap_failure_and_post_pidfd_launch_failure_deny_cleanup(self) -> None:
        fake = FakeServiceSupervisor(stop_error="wait/reap failure")
        service = SupervisorControlService(supervisor=fake, io_timeout=0.5)
        requests = [
            {"id": 1, "op": "launch", "command": "sleep", "duration_ms": 1},
            {"id": 2, "op": "stop_all", "handles": ["fake-handle-1"]},
            {"id": 3, "op": "shutdown"},
        ]
        outcome, responses = run_in_process(b"".join(raw_frame(row) for row in requests), service)
        self.assertFalse(responses[1]["all_reaped"])
        self.assertFalse(responses[1]["cleanup_allowed"])
        self.assertEqual(responses[2]["status"], "workers_unresolved")
        self.assertEqual(fake.callback_count, 0)
        self.assertEqual(outcome.exit_code, 2)  # EOF with an unreaped worker is preserve-backing.

        launch_fake = FakeServiceSupervisor(launch_error=True)
        launch_service = SupervisorControlService(supervisor=launch_fake, io_timeout=0.5)
        launch_requests = [
            {"id": 1, "op": "launch", "command": "sleep", "duration_ms": 1},
            {"id": 2, "op": "stop_all", "handles": ["fake-handle-1"]},
            {"id": 3, "op": "shutdown"},
        ]
        outcome2, responses2 = run_in_process(b"".join(raw_frame(row) for row in launch_requests), launch_service)
        self.assertEqual(responses2[0]["status"], "launch_failure")
        self.assertTrue(responses2[0]["preserve_required"])
        self.assertFalse(responses2[1]["cleanup_allowed"])
        self.assertFalse(responses2[2]["cleanup_allowed"])
        self.assertEqual(launch_fake.callback_count, 0)
        self.assertEqual(outcome2.exit_code, 3)

    def test_no_numeric_pid_signal_or_arbitrary_worker_argv_interface(self) -> None:
        source = SERVICE_PATH.read_text()
        self.assertNotIn("os.kill(", source)
        self.assertNotIn("pidfd_send_signal", source)
        self.assertIn("cleanup_after_stop", source)
        self.assertIn('"sleep"', source)
        self.assertIn('"exit"', source)
        self.assertNotIn("request.get(\"pid\")", source)
        self.assertNotIn("request.get(\"argv\")", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
