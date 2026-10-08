#!/usr/bin/env python3
"""Rootless IPC adapter regression with fabricated replies and owned test workers."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import importlib.util
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from typing import Any


HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True


def load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


adapter_module = load("rootless_recall_adapter", HERE / "recall-ipc-adapter.py")
service_module = load("rootless_ipc_service", HERE / "test-child-supervisor-service.py")
RecallIPCAdapter = adapter_module.RecallIPCAdapter
RecallIPCError = adapter_module.RecallIPCError


def base(cleanup: bool = False, **fields: Any) -> dict[str, Any]:
    return {
        "ok": cleanup, "cleanup_allowed": cleanup,
        "preserve_backing": not cleanup, "all_reaped": False,
        **fields,
    }


def worker(handle: str, **fields: Any) -> dict[str, Any]:
    return {
        "handle": handle, "reaped": True, "exit_code": 0,
        "errors": [], "escalated": False, **fields,
    }


class FakeProcess:
    def __init__(self) -> None:
        self.exit_code = 0
        self.observed: int | None = 0
        self.raise_wait = False
        self.calls: list[str] = []

    def wait(self, timeout: float | None = None) -> int:
        assert timeout is not None and timeout <= 60
        self.calls.append("wait-process")
        if self.raise_wait:
            raise TimeoutError("service did not exit")
        return self.exit_code

    def poll(self) -> int | None:
        self.calls.append("poll-process")
        return self.observed


class FakeClient:
    def __init__(self) -> None:
        self.handles: list[str] = []
        self.calls: list[str] = []
        self.override: dict[str, Any] = {}
        self.raise_on: str | None = None
        self.allow_exit = True

    def call(self, op: str, **fields: Any) -> dict[str, Any]:
        self.calls.append(op)
        if self.raise_on == op:
            raise ConnectionError(f"injected {op} channel failure")
        if op == "launch":
            handle = f"fake-handle-{len(self.handles) + 1}"
            self.handles.append(handle)
            result = base(False, status="ready", ok=True, handle=handle)
        elif op == "wait":
            result = base(False, status="reaped", ok=True,
                          worker=worker(fields["handle"]))
        elif op == "stop_all":
            assert fields["handles"] == self.handles
            result = base(True, status="complete", all_reaped=True,
                          workers=[worker(h) for h in self.handles], errors=[])
        elif op == "shutdown":
            result = base(True, status="shutdown", all_reaped=True)
        else:
            raise ValueError("unexpected operation")
        override = self.override.get(op)
        if callable(override):
            return override(copy.deepcopy(result))
        return copy.deepcopy(override) if override is not None else result

    def confirm_service_exit(self, exit_code: int) -> bool:
        self.calls.append("confirm-service-exit")
        return self.allow_exit and exit_code == 0


class ServiceProcess:
    """Only short-lived subprocesses spawned by this exact test are managed."""

    def __init__(self) -> None:
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.process = subprocess.Popen(
            [sys.executable, str(HERE / "test-child-supervisor-service.py"),
             "--fd", str(child.fileno())],
            pass_fds=(child.fileno(),), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True,
        )
        child.close()
        self.client = service_module.SupervisorControlClient(parent, timeout=10.0)
        self.adapter = RecallIPCAdapter(self.client, self.process)

    def close(self) -> None:
        self.client.close()
        try:
            self.process.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            # This is only our own short-lived supervisor process, not a host task.
            self.process.terminate()
            self.process.communicate(timeout=3)


class AdapterFakeProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeClient()
        self.process = FakeProcess()
        self.adapter = RecallIPCAdapter(self.client, self.process)

    def two(self) -> tuple[str, str]:
        return (self.adapter.launch_test("exit", code=0),
                self.adapter.launch_test("sleep", duration_ms=10))

    def test_empty_session_requires_stop_shutdown_and_exit(self) -> None:
        with self.assertRaises(RecallIPCError):
            self.adapter.run_synthetic_cleanup(lambda: "incorrect")
        self.assertFalse(self.adapter.cleanup_authorized)

    def test_two_test_workers_and_full_stop_attestation(self) -> None:
        handles = self.two()
        self.assertEqual(self.client.calls, ["launch", "launch"])
        self.assertEqual(self.adapter.wait_reaped(handles[0]).handle, handles[0])
        self.assertEqual(self.adapter.wait_reaped(handles[1]).handle, handles[1])
        report = self.adapter.stop_all()
        self.assertEqual({r.handle for r in report.results}, set(handles))
        self.assertFalse(self.adapter.cleanup_authorized)
        self.assertTrue(self.adapter.shutdown_and_confirm_exit())
        self.assertEqual(self.adapter.run_synthetic_cleanup(lambda: "clean"), "clean")
        self.assertEqual(self.client.calls[-3:],
                         ["stop_all", "shutdown", "confirm-service-exit"])
        self.assertEqual(self.process.calls, ["wait-process", "poll-process"])

    def test_no_shell_or_generic_argv_admission(self) -> None:
        for command, params in [
            ("dd", {"duration_ms": 1}),
            ("bash", {"code": 0}),
            ("sleep", {"duration_ms": True}),
            ("sleep", {"duration_ms": -1}),
            ("sleep", {"duration_ms": 5001}),
            ("exit", {"code": 126}),
        ]:
            with self.subTest(command=command, params=params):
                adapter = RecallIPCAdapter(FakeClient(), FakeProcess())
                with self.assertRaises(RecallIPCError):
                    adapter.launch_test(command, **params)
                self.assertFalse(adapter.cleanup_authorized)

    def test_unknown_wait_handle_sticky_denial(self) -> None:
        self.two()
        with self.assertRaises(RecallIPCError):
            self.adapter.wait_reaped("unknown")
        with self.assertRaises(RecallIPCError):
            self.adapter.stop_all()

    def test_repeated_launch_handle_rejected(self) -> None:
        self.adapter.launch_test("exit", code=0)
        self.client.override["launch"] = lambda d: {**d, "handle": "fake-handle-1"}
        with self.assertRaises(RecallIPCError):
            self.adapter.launch_test("exit", code=0)
        self.assertFalse(self.adapter.cleanup_authorized)

    def test_worker_nonzero_exit_rejects_wait(self) -> None:
        handle = self.adapter.launch_test("exit", code=0)
        self.client.override["wait"] = lambda d: {**d, "worker": worker(handle, exit_code=7)}
        with self.assertRaises(RecallIPCError):
            self.adapter.wait_reaped(handle)

    def test_worker_unreaped_rejects_wait(self) -> None:
        handle = self.adapter.launch_test("exit", code=0)
        self.client.override["wait"] = lambda d: {**d, "worker": worker(handle, reaped=False)}
        with self.assertRaises(RecallIPCError):
            self.adapter.wait_reaped(handle)

    def test_malformed_wait_response_rejected(self) -> None:
        handle = self.adapter.launch_test("exit", code=0)
        self.client.override["wait"] = lambda d: {**d, "worker": {"handle": handle}}
        with self.assertRaises(RecallIPCError):
            self.adapter.wait_reaped(handle)

    def test_wait_running_is_not_reap_confirmation(self) -> None:
        handle = self.adapter.launch_test("sleep", duration_ms=50)
        self.client.override["wait"] = lambda d: {**d, "status": "running",
                                                 "worker": worker(handle, reaped=False)}
        with self.assertRaises(RecallIPCError):
            self.adapter.wait_reaped(handle)

    def test_stop_worker_inventory_forgery_denied(self) -> None:
        mutators = {
            "missing": lambda d: {**d, "workers": d["workers"][:1]},
            "extra": lambda d: {**d, "workers": d["workers"] + [worker("new-handle")]},
            "duplicate": lambda d: {**d, "workers": d["workers"][:1] * 2},
            "unreaped": lambda d: {**d, "workers": [worker("fake-handle-1", reaped=False),
                                                   worker("fake-handle-2")]},
            "worker_errors": lambda d: {**d, "workers": [worker("fake-handle-1", errors=["lost wait"]),
                                                       worker("fake-handle-2")]},
            "report_errors": lambda d: {**d, "errors": ["fd close failed"]},
            "incorrect_type": lambda d: {**d, "workers": [worker("fake-handle-1", reaped=1),
                                                         worker("fake-handle-2")]},
            "no_details": lambda d: {k: v for k, v in d.items() if k != "workers"},
            "missing_worker_key": lambda d: {**d, "workers": [{"handle": "fake-handle-1"},
                                                            worker("fake-handle-2")]},
            "false_all_reaped": lambda d: {**d, "all_reaped": False},
            "wrong_cleanup": lambda d: {**d, "cleanup_allowed": False, "preserve_backing": True},
            "contradiction": lambda d: {**d, "cleanup_allowed": True, "preserve_backing": True},
            "malformed_errors": lambda d: {**d, "errors": "not-list"},
            "worker_exit_bool": lambda d: {**d, "workers": [worker("fake-handle-1", exit_code=True),
                                                           worker("fake-handle-2")]},
        }
        for name, mutate in mutators.items():
            with self.subTest(name=name):
                client, process = FakeClient(), FakeProcess()
                adapter = RecallIPCAdapter(client, process)
                adapter.launch_test("exit", code=0)
                adapter.launch_test("exit", code=0)
                client.override["stop_all"] = mutate
                with self.assertRaises(RecallIPCError):
                    adapter.stop_all()
                with self.assertRaises(RecallIPCError):
                    adapter.shutdown_and_confirm_exit()
                self.assertFalse(adapter.cleanup_authorized)
                self.assertEqual(process.calls, [])

    def test_shutdown_forgery_denies_cleanup(self) -> None:
        cases = [
            lambda d: {**d, "ok": False},
            lambda d: {**d, "status": "workers_unresolved", "cleanup_allowed": False,
                       "preserve_backing": True},
            lambda d: {**d, "all_reaped": False},
            lambda d: {**d, "preserve_backing": True},
            lambda d: {**d, "cleanup_allowed": False, "preserve_backing": True},
        ]
        for mutate in cases:
            client, process = FakeClient(), FakeProcess()
            adapter = RecallIPCAdapter(client, process)
            adapter.launch_test("exit", code=0)
            adapter.stop_all()
            client.override["shutdown"] = mutate
            with self.assertRaises(RecallIPCError):
                adapter.shutdown_and_confirm_exit()
            self.assertFalse(adapter.cleanup_authorized)
            self.assertEqual(process.calls, [])

    def test_exit_confirmation_is_mandatory(self) -> None:
        for exit_code, observed, approved, crash in [
            (1, 1, True, False), (0, None, True, False),
            (0, 0, False, False), (0, 0, True, True),
        ]:
            with self.subTest(exit_code=exit_code, observed=observed,
                              approved=approved, crash=crash):
                client, process = FakeClient(), FakeProcess()
                adapter = RecallIPCAdapter(client, process)
                adapter.launch_test("exit", code=0)
                adapter.stop_all()
                process.exit_code = exit_code
                process.observed = observed
                process.raise_wait = crash
                client.allow_exit = approved
                with self.assertRaises(RecallIPCError):
                    adapter.shutdown_and_confirm_exit()
                self.assertFalse(adapter.cleanup_authorized)

    def test_stop_or_shutdown_socket_loss_is_sticky(self) -> None:
        for operation in ("stop_all", "shutdown"):
            client = FakeClient()
            adapter = RecallIPCAdapter(client, FakeProcess())
            adapter.launch_test("exit", code=0)
            if operation == "shutdown":
                adapter.stop_all()
            client.raise_on = operation
            with self.assertRaises(RecallIPCError):
                if operation == "stop_all":
                    adapter.stop_all()
                else:
                    adapter.shutdown_and_confirm_exit()
            with self.assertRaises(RecallIPCError):
                adapter.run_synthetic_cleanup(lambda: "unsafe")
            self.assertFalse(adapter.cleanup_authorized)

    def test_cleanup_denial_and_unknown_report_are_sticky(self) -> None:
        self.adapter.launch_test("exit", code=0)
        self.client.override["stop_all"] = {"status": "complete"}
        with self.assertRaises(RecallIPCError):
            self.adapter.stop_all()
        self.client.override.clear()
        with self.assertRaises(RecallIPCError):
            self.adapter.stop_all()
        self.assertFalse(self.adapter.cleanup_authorized)

    def test_shutdown_without_stop_report_is_denied(self) -> None:
        self.adapter.launch_test("exit", code=0)
        with self.assertRaises(RecallIPCError):
            self.adapter.shutdown_and_confirm_exit()

    def test_no_device_or_signal_actions_in_adapter(self) -> None:
        import ast
        tree = ast.parse((HERE / "recall-ipc-adapter.py").read_text())
        forbidden = {"kill", "fork", "Popen", "system", "swapon", "swapoff",
                     "losetup", "dmsetup", "ioctl", "execv", "execve"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, forbidden)
                elif isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, forbidden)


class AdapterRealServiceTests(unittest.TestCase):
    def test_two_owned_workers_before_wait_then_clean_service_exit(self) -> None:
        session = ServiceProcess()
        try:
            a = session.adapter.launch_test("sleep", duration_ms=80)
            b = session.adapter.launch_test("sleep", duration_ms=80)
            self.assertNotEqual(a, b)
            first = session.adapter.wait_reaped(a, timeout_ms=3000)
            second = session.adapter.wait_reaped(b, timeout_ms=3000)
            self.assertTrue(first.reaped and second.reaped)
            attestation = session.adapter.stop_all()
            self.assertEqual({r.handle for r in attestation.results}, {a, b})
            self.assertFalse(session.adapter.cleanup_authorized)
            self.assertTrue(session.adapter.shutdown_and_confirm_exit())
            hits: list[str] = []
            session.adapter.run_synthetic_cleanup(lambda: hits.append("clean"))
            self.assertEqual(hits, ["clean"])
            self.assertEqual(session.process.returncode, 0)
        finally:
            session.close()

    def test_service_nonzero_worker_exit_blocks_cleanup(self) -> None:
        session = ServiceProcess()
        try:
            handle = session.adapter.launch_test("exit", code=7)
            with self.assertRaises(RecallIPCError):
                session.adapter.wait_reaped(handle, timeout_ms=3000)
            with self.assertRaises(RecallIPCError):
                session.adapter.stop_all()
            self.assertFalse(session.adapter.cleanup_authorized)
        finally:
            session.close()

    def test_disconnect_before_stop_denies_synthetic_cleanup(self) -> None:
        session = ServiceProcess()
        try:
            session.adapter.launch_test("sleep", duration_ms=700)
            session.client.close()
            with self.assertRaises(RecallIPCError):
                session.adapter.stop_all()
            self.assertFalse(session.adapter.cleanup_authorized)
        finally:
            session.close()

    def test_disconnect_after_stop_denies_synthetic_cleanup(self) -> None:
        session = ServiceProcess()
        try:
            session.adapter.launch_test("sleep", duration_ms=700)
            session.adapter.stop_all()
            session.client.close()
            with self.assertRaises(RecallIPCError):
                session.adapter.shutdown_and_confirm_exit()
            self.assertFalse(session.adapter.cleanup_authorized)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
