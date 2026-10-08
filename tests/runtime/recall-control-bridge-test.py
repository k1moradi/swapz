#!/usr/bin/env python3
"""Rootless persistent bridge regression: short-lived IPC service test workers."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent
BRIDGE = ROOT / "recall-control-bridge.py"


def load_bridge():
    spec = importlib.util.spec_from_file_location("bridge_regression_module", BRIDGE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bridge_module = load_bridge()


class BridgeSession:
    """Subprocess spawned by this test only; never signal a numeric worker PID."""

    def __init__(self):
        self.proc = subprocess.Popen(
            [sys.executable, str(BRIDGE)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
            close_fds=True,
        )
        self.request_id = 0
        ready = self.receive()
        assert ready["status"] == "bridge_ready", ready
        assert ready["preserve_backing"] is True

    def receive(self, timeout=8.0):
        assert self.proc.stdout is not None
        readable, _, _ = select.select([self.proc.stdout], [], [], timeout)
        if not readable:
            raise AssertionError("bridge response deadline exceeded")
        raw = self.proc.stdout.readline()
        if not raw:
            raise AssertionError("bridge closed before sending response")
        assert len(raw) <= 2048, raw[:150]
        return json.loads(raw)

    def raw(self, data: bytes):
        assert self.proc.stdin is not None
        self.proc.stdin.write(data)
        self.proc.stdin.flush()
        return self.receive()

    def send(self, op: str, **fields):
        self.request_id += 1
        return self.raw(json.dumps({"id": self.request_id, "op": op, **fields},
                                   separators=(",", ":")).encode() + b"\n")

    def finish(self, timeout=12.0):
        assert self.proc.stdin is not None
        self.proc.stdin.close()
        return self.proc.wait(timeout=timeout)

    def abandon(self):
        if self.proc.poll() is None:
            try:
                assert self.proc.stdin is not None
                self.proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            try:
                self.proc.wait(timeout=12.0)
            except subprocess.TimeoutExpired:
                # No process signal; the test owns the bridge and test workers.
                raise AssertionError("test-owned bridge did not exit after controller EOF")
        for stream in (self.proc.stdout, self.proc.stderr):
            if stream is not None:
                stream.close()


class BridgeRootlessTests(unittest.TestCase):
    def session(self):
        s = BridgeSession()
        self.addCleanup(s.abandon)
        return s

    @staticmethod
    def denied(response):
        assert response["cleanup_allowed"] is False
        assert response["preserve_backing"] is True

    def test_empty_session_cleanup_requires_stop_shutdown_finalization(self):
        s = self.session()
        self.denied(s.send("STOP_ALL"))
        self.denied(s.send("SHUTDOWN"))
        result = s.send("FINALIZE")
        self.assertEqual(result["status"], "cleanup_authorized")
        self.assertTrue(result["cleanup_allowed"])
        self.assertFalse(result["preserve_backing"])
        self.assertEqual(s.finish(), 0)

    def test_three_workers_have_opaque_handles_and_persistent_session(self):
        s = self.session()
        writer = s.send("LAUNCH_TEST", command="sleep", duration_ms=90)
        a = s.send("LAUNCH_TEST", command="sleep", duration_ms=90)
        b = s.send("LAUNCH_TEST", command="sleep", duration_ms=90)
        handles = [r["handle"] for r in (writer, a, b)]
        self.assertEqual(len(set(handles)), 3)
        self.assertTrue(all(h.startswith("w") or not h.isdecimal() for h in handles))
        self.assertTrue(all(r["status"] == "ready" for r in (writer, a, b)))
        for handle in handles:
            result = s.send("WAIT", handle=handle, timeout_ms=2000)
            self.assertEqual(result["handle"], handle)
            self.assertEqual(result["status"], "reaped")
            self.assertEqual(result["exit_code"], 0)
        stopped = s.send("STOP_ALL")
        self.denied(stopped)
        self.assertEqual({r["handle"] for r in stopped["workers"]}, set(handles))
        self.assertTrue(all(row["reaped"] for row in stopped["workers"]))
        self.denied(s.send("SHUTDOWN"))
        self.assertTrue(s.send("FINALIZE")["cleanup_allowed"])
        self.assertEqual(s.finish(), 0)

    def test_two_launches_are_before_any_wait(self):
        s = self.session()
        a = s.send("LAUNCH_TEST", command="sleep", duration_ms=50)["handle"]
        b = s.send("LAUNCH_TEST", command="sleep", duration_ms=50)["handle"]
        self.assertNotEqual(a, b)
        self.assertEqual(s.send("WAIT", handle=a, timeout_ms=2000)["status"], "reaped")
        self.assertEqual(s.send("WAIT", handle=b, timeout_ms=2000)["status"], "reaped")
        s.send("STOP_ALL")
        s.send("SHUTDOWN")
        self.assertTrue(s.send("FINALIZE")["cleanup_allowed"])
        self.assertEqual(s.finish(), 0)

    def test_nonzero_worker_exit_preserves_backing(self):
        s = self.session()
        handle = s.send("LAUNCH_TEST", command="exit", code=7)["handle"]
        denied = s.send("WAIT", handle=handle, timeout_ms=2000)
        self.denied(denied)
        self.assertEqual(denied["status"], "preserve_backing")
        self.assertEqual(s.finish(), 2)

    def test_finalization_before_stop_denied(self):
        s = self.session()
        self.denied(s.send("FINALIZE"))
        self.assertEqual(s.finish(), 2)

    def test_shutdown_before_stop_denied(self):
        s = self.session()
        self.denied(s.send("SHUTDOWN"))
        self.assertEqual(s.finish(), 2)

    def test_launch_after_stop_denied(self):
        s = self.session()
        self.denied(s.send("STOP_ALL"))
        self.denied(s.send("LAUNCH_TEST", command="exit", code=0))
        self.assertEqual(s.finish(), 2)

    def test_unknown_wait_handle_denied(self):
        s = self.session()
        s.send("LAUNCH_TEST", command="exit", code=0)
        self.denied(s.send("WAIT", handle="opaque-other", timeout_ms=0))
        self.assertEqual(s.finish(), 2)

    def test_duplicate_or_replayed_request_id_denied(self):
        s = self.session()
        self.denied(s.raw(b'{"id":1,"op":"STOP_ALL"}\n') if False else
                    s.raw(b'{"id":1,"op":"STOP_ALL","op":"FINALIZE"}\n'))
        self.assertEqual(s.finish(), 2)

    def test_malformed_message_never_reuses_a_prior_request_id(self):
        s = self.session()
        s.send("LAUNCH_TEST", command="exit", code=0)
        response = s.raw(b'not valid JSON\n')
        self.denied(response)
        self.assertIsNone(response["id"])
        self.assertEqual(s.finish(), 2)

    def test_caller_supplied_cleanup_handles_rejected(self):
        s = self.session()
        s.send("LAUNCH_TEST", command="sleep", duration_ms=40)
        self.denied(s.send("STOP_ALL", handles=[]))
        self.assertEqual(s.finish(), 2)

    def test_duplicate_request_after_valid_launch_denied(self):
        s = self.session()
        s.send("LAUNCH_TEST", command="sleep", duration_ms=40)
        self.denied(s.raw(b'{"id":1,"op":"STOP_ALL"}\n'))
        self.assertEqual(s.finish(), 2)

    def test_malformed_request_or_oversized_request_denied(self):
        for raw in (b'{"id":1,"op":\n', b"{" + b"x" * 2500 + b"}\n",
                    b'{"id":1,"op":"LAUNCH_TEST","command":"dd","argv":["/dev/sda"]}\n',
                    b'{"id":1,"op":"STOP_ALL","pid":42}\n'):
            with self.subTest(raw=raw[:25]):
                s = self.session()
                self.denied(s.raw(raw))
                self.assertEqual(s.finish(), 2)

    def test_numeric_pid_and_unsafe_direct_dd_worker_rejected(self):
        s = self.session()
        result = s.send("LAUNCH_TEST", command="dd", argv=["dd", "of=/dev/sda"])
        self.denied(result)
        self.assertEqual(s.finish(), 2)

    def test_unexpected_controller_eof_before_stop_preserves(self):
        s = self.session()
        s.send("LAUNCH_TEST", command="sleep", duration_ms=100)
        self.assertEqual(s.finish(), 2)

    def test_controller_disconnect_after_stop_before_shutdown_preserves(self):
        s = self.session()
        s.send("LAUNCH_TEST", command="sleep", duration_ms=70)
        stopped = s.send("STOP_ALL")
        self.denied(stopped)
        self.assertEqual(s.finish(), 2)

    def test_controller_disconnect_after_shutdown_before_finalize_preserves(self):
        s = self.session()
        self.denied(s.send("STOP_ALL"))
        self.denied(s.send("SHUTDOWN"))
        self.assertEqual(s.finish(), 2)

    def test_sticky_denial_closes_session(self):
        s = self.session()
        self.denied(s.send("WAIT", handle="unknown", timeout_ms=0))
        self.assertEqual(s.finish(), 2)

    def test_bridge_static_no_pid_signal_or_device_commands(self):
        source = BRIDGE.read_text()
        tree = __import__("ast").parse(source)
        banned = {"kill", "terminate", "send_signal", "swapon", "swapoff",
                  "dmsetup", "losetup", "ioctl", "system", "execvp", "fork"}
        for node in __import__("ast").walk(tree):
            if isinstance(node, __import__("ast").Call):
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                self.assertNotIn(name, banned)
        self.assertNotIn("kill -CONT", source)
        self.assertNotIn("kill -TERM", source)

    def test_invalid_response_never_contains_numeric_worker_pid(self):
        s = self.session()
        ready = s.send("LAUNCH_TEST", command="exit", code=0)
        self.assertNotIn("pid", ready)
        self.assertNotIn("argv", ready)
        self.assertFalse(ready["handle"].isdecimal())
        s.send("STOP_ALL")
        s.send("SHUTDOWN")
        s.send("FINALIZE")
        self.assertEqual(s.finish(), 0)


class BridgeMockedServiceTests(unittest.TestCase):
    def test_exit_rejection_is_preserved_at_bridge_boundary(self):
        # Exercise actual bridge dispatch but no service or worker created.
        bridge = object.__new__(bridge_module.PersistentRecallBridge)
        bridge.failed = False
        bridge.finalized = False
        bridge.finished = False
        bridge.request_count = 0
        bridge.last_id = 0
        class StubAdapter:
            cleanup_authorized = False
            def stop_all(self):
                raise RuntimeError("injected incomplete supervisor report")
        bridge.adapter = StubAdapter()
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            bridge.dispatch({"id": 1, "op": "STOP_ALL"})
        self.assertFalse(bridge.finalized)

    def test_failed_control_descriptor_close_denies_finalization(self):
        bridge = object.__new__(bridge_module.PersistentRecallBridge)
        bridge.failed = False
        bridge.finalized = False
        bridge.finished = False
        bridge.request_count = 0
        bridge.last_id = 0
        class FakeClient:
            cleanup_authorized = True
            def close(self):
                self.cleanup_authorized = False
        bridge.adapter = type("Ready", (), {"cleanup_authorized": True})()
        bridge.client = FakeClient()
        with self.assertRaisesRegex(bridge_module.BridgeError, "descriptor"):
            bridge.dispatch({"id": 1, "op": "FINALIZE"})
        self.assertFalse(bridge.finalized)

    def test_unconfirmed_exit_prevents_bridge_finalization(self):
        bridge = object.__new__(bridge_module.PersistentRecallBridge)
        bridge.failed = False
        bridge.finalized = False
        bridge.finished = False
        bridge.request_count = 0
        bridge.last_id = 0
        bridge.adapter = type("Denied", (), {"cleanup_authorized": False})()
        with self.assertRaises(bridge_module.BridgeError):
            bridge.dispatch({"id": 1, "op": "FINALIZE"})
        self.assertFalse(bridge.finalized)


if __name__ == "__main__":
    unittest.main()
