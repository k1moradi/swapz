#!/usr/bin/env python3
"""Synthetic-only role bridge, adapter and pinned readback integration regression.

No real mapper, device, subprocess or dd worker is created. The fake service
models the wire protocol; the already separate pinned-worker regression
exercises real dd. Both parts must pass before any production migration.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent


def load(name: str, file: str):
    specification = importlib.util.spec_from_file_location(name, HERE / file)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


bridge_module = load("swapz_role_bridge_regression", "recall-control-bridge.py")
readback_module = load("swapz_role_readback_regression", "recall-readback-identity.py")
adapter_module = bridge_module.adapter_module
RoleAdapter = adapter_module.RecallRoleIPCAdapter
RoleError = adapter_module.RecallIPCError
RootlessRoleBridge = bridge_module.RootlessRoleBridge
ReadbackError = readback_module.ReadbackIdentityError
PAGE_SIZE = 4096
PAGES = {"a": 0, "b": 4, "a2": 0, "b2": 5}


class SyntheticProcess:
    def __init__(self) -> None:
        self.wait_code = 0
        self.poll_code = 0
        self.wait_count = 0

    def wait(self, timeout=None):
        assert timeout is not None and timeout <= 60
        self.wait_count += 1
        return self.wait_code

    def poll(self):
        return self.poll_code


class SyntheticRoleService:
    """Fake IPC client, with actual pinned regular-file outputs in private tmp."""

    def __init__(self, fixture: Path, directory_fd: int, expected: bytes) -> None:
        self.fixture = fixture
        self.directory_fd = directory_fd
        self.expected = expected
        self.handles: list[str] = []
        self.roles: list[str] = []
        self.events: list[tuple[str, str]] = []
        self.output_descriptors: dict[str, int] = {}
        self.output_identity = {}
        self.corrupt_role: str | None = None
        self.truncate_role: str | None = None
        self.replace_role: str | None = None
        self.bad_stop = False
        self.bad_exit = False
        self.fail_launch_role: str | None = None
        self.fail_wait_role: str | None = None
        self.duplicate_next_handle = False
        self.close_failure = False
        self.cleanup_authorized = False

    def close(self) -> None:
        if self.close_failure:
            self.cleanup_authorized = False

    def close_outputs(self) -> None:
        for descriptor in self.output_descriptors.values():
            os.close(descriptor)
        self.output_descriptors.clear()

    def verify_role(self, role: str) -> bool:
        if role not in self.output_identity:
            raise ReadbackError("missing pinned role identity")
        readback_module.verify_readback(
            self.output_identity[role],
            directory_fd=self.directory_fd,
            output_fd=self.output_descriptors[role],
            expected_page=self.expected[PAGES[role] * PAGE_SIZE:(PAGES[role] + 1) * PAGE_SIZE],
        )
        return True

    def call(self, operation: str, **fields):
        if operation == "launch":
            assert set(fields) == {"command", "role"}
            assert fields["command"] == "recall-dd"
            role = fields["role"]
            self.events.append(("launch", role))
            if role == self.fail_launch_role:
                raise ConnectionError("injected role launch channel failure")
            if role != "writer":
                descriptor = os.open(
                    "read-" + role,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600, dir_fd=self.directory_fd,
                )
                self.output_descriptors[role] = descriptor
                # This is the trusted service's pre-worker identity capture.
                self.output_identity[role] = readback_module.capture_readback_identity(
                    self.directory_fd, descriptor, role,
                )
                data = self.expected[PAGES[role] * PAGE_SIZE:(PAGES[role] + 1) * PAGE_SIZE]
                if role == self.corrupt_role:
                    data = bytes((255 - byte) for byte in data)
                if role == self.truncate_role:
                    data = data[:-1]
                os.write(descriptor, data)
                if role == self.replace_role:
                    entry = self.fixture / ("read-" + role)
                    entry.rename(self.fixture / ("original-read-" + role))
                    entry.write_bytes(data)
            handle = ("role-worker-1" if self.duplicate_next_handle
                      else f"role-worker-{len(self.handles) + 1}")
            self.handles.append(handle)
            self.roles.append(role)
            return {"status": "ready", "ok": True, "handle": handle,
                    "cleanup_allowed": False, "preserve_backing": True}
        if operation == "wait":
            self.events.append(("wait", fields["handle"]))
            assert set(fields) == {"handle", "timeout_ms"}
            role = self.roles[self.handles.index(fields["handle"])]
            result = {"handle": fields["handle"], "reaped": True, "exit_code": 0,
                      "errors": [], "escalated": False}
            if role == self.fail_wait_role:
                result["exit_code"] = 3
            return {"status": "reaped", "ok": True, "worker": result,
                    "cleanup_allowed": False, "preserve_backing": True}
        if operation == "stop_all":
            self.events.append(("stop_all", ""))
            assert fields == {"handles": self.handles}
            results = [{"handle": handle, "reaped": True, "exit_code": 0,
                        "errors": [], "escalated": False} for handle in self.handles]
            if self.bad_stop:
                results = results[:-1]
            return {"status": "complete", "ok": True, "workers": results, "errors": [],
                    "all_reaped": True, "cleanup_allowed": True, "preserve_backing": False}
        if operation == "shutdown":
            self.events.append(("shutdown", ""))
            return {"status": "shutdown", "ok": True, "all_reaped": True,
                    "cleanup_allowed": True, "preserve_backing": False}
        raise AssertionError("unexpected wire operation")

    def confirm_service_exit(self, code):
        self.events.append(("confirm-service-exit", str(code)))
        self.cleanup_authorized = bool(code == 0 and not self.bad_exit)
        return self.cleanup_authorized


class RootlessRoleBridgeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="swapz-role-bridge-rootless-")
        self.addCleanup(temporary.cleanup)
        self.fixture = Path(temporary.name) / "fixture"
        self.fixture.mkdir(mode=0o700)
        self.directory_fd = os.open(
            self.fixture, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        self.addCleanup(os.close, self.directory_fd)
        self.expected = b"".join(
            bytes(((page * 23 + index) % 256) for index in range(PAGE_SIZE))
            for page in range(9)
        )
        self.client = SyntheticRoleService(self.fixture, self.directory_fd, self.expected)
        self.addCleanup(self.client.close_outputs)
        self.process = SyntheticProcess()
        self.adapter = RoleAdapter(
            self.client, self.process, verify_role_result=self.client.verify_role
        )
        self.bridge = RootlessRoleBridge(
            client=self.client, process=self.process, adapter=self.adapter
        )
        self.ident = 0

    def request(self, operation, **fields):
        self.ident += 1
        return self.bridge.dispatch({"id": self.ident, "op": operation, **fields})

    def role(self, name):
        return self.request("LAUNCH_ROLE", role=name)["handle"]

    def verified(self, handle):
        result = self.request("WAIT", handle=handle, timeout_ms=2000)
        self.assertEqual(result["status"], "reaped")

    def complete(self):
        self.request("STOP_ALL")
        self.request("SHUTDOWN")
        response = self.request("FINALIZE")
        self.assertTrue(response["cleanup_allowed"])
        self.assertFalse(response["preserve_backing"])
        self.assertTrue(self.bridge.finalized)

    def test_five_roles_require_concurrent_launch_before_wait(self):
        writer = self.role("writer")
        a = self.role("a")
        self.verified(a)
        b = self.role("b")
        self.verified(b)
        first, second = self.role("a2"), self.role("b2")
        self.assertEqual(self.client.events[-2:], [("launch", "a2"), ("launch", "b2")])
        self.verified(first)
        self.verified(second)
        self.verified(writer)
        self.complete()
        self.assertEqual(self.process.wait_count, 1)
        self.assertEqual(self.client.roles, ["writer", "a", "b", "a2", "b2"])

    def test_no_wait_on_reader_denies_stop_and_finalization(self):
        self.role("writer")
        self.role("a")
        with self.assertRaisesRegex(RoleError, "attestation missing"):
            self.request("STOP_ALL")
        with self.assertRaises(RoleError):
            self.request("SHUTDOWN")
        self.assertFalse(self.adapter.cleanup_authorized)

    def test_corrupt_source_and_readback_consistently_still_denied(self):
        self.client.corrupt_role = "a"
        self.role("writer")
        reader = self.role("a")
        (self.fixture / "expected-a").write_bytes(
            (self.fixture / "read-a").read_bytes()
        )
        with self.assertRaisesRegex(RoleError, "readback check failed"):
            self.verified(reader)
        self.assertFalse(self.adapter.cleanup_authorized)

    def test_path_replacement_with_matching_bytes_denied(self):
        self.client.replace_role = "a"
        self.role("writer")
        reader = self.role("a")
        with self.assertRaisesRegex(RoleError, "pathname"):
            self.verified(reader)
        self.assertFalse(self.adapter.cleanup_authorized)

    def test_short_readback_denied(self):
        self.client.truncate_role = "b"
        self.role("writer")
        reader = self.role("b")
        with self.assertRaisesRegex(RoleError, "exact size"):
            self.verified(reader)

    def test_unknown_duplicate_and_out_of_order_roles_deny(self):
        for bad in ("a", "bad", "", "writer2", None, True):
            with self.subTest(role=bad):
                adapter = RoleAdapter(
                    SyntheticRoleService(self.fixture, self.directory_fd, self.expected),
                    SyntheticProcess(), verify_role_result=lambda _role: True
                )
                with self.assertRaises(RoleError):
                    adapter.launch_role(bad)
        self.role("writer")
        with self.assertRaises(RoleError):
            self.role("writer")
        self.assertFalse(self.adapter.cleanup_authorized)

    def test_duplicate_handles_and_channel_error_deny(self):
        self.role("writer")
        self.client.duplicate_next_handle = True
        with self.assertRaisesRegex(RoleError, "duplicated"):
            self.role("a")
        self.assertFalse(self.adapter.cleanup_authorized)

    def test_partial_ab_phase_missing_second_reader_denies(self):
        writer = self.role("writer")
        a2 = self.role("a2")
        self.verified(a2)
        self.verified(writer)
        self.client.fail_launch_role = "b2"
        with self.assertRaises(RoleError):
            self.role("b2")
        self.assertFalse(self.adapter.cleanup_authorized)

    def test_nonzero_worker_or_fabricated_stop_denies(self):
        self.client.fail_wait_role = "a"
        self.role("writer")
        a = self.role("a")
        with self.assertRaises(RoleError):
            self.verified(a)
        self.assertFalse(self.adapter.cleanup_authorized)

    def test_missing_stop_worker_report_denies(self):
        writer = self.role("writer")
        self.verified(writer)
        self.client.bad_stop = True
        with self.assertRaises(RoleError):
            self.request("STOP_ALL")
        self.assertFalse(self.adapter.cleanup_authorized)

    def test_unconfirmed_service_exit_denies(self):
        writer = self.role("writer")
        self.verified(writer)
        self.request("STOP_ALL")
        self.client.bad_exit = True
        with self.assertRaises(RoleError):
            self.request("SHUTDOWN")
        self.assertFalse(self.adapter.cleanup_authorized)

    def test_final_descriptor_close_failure_denies(self):
        writer = self.role("writer")
        self.verified(writer)
        self.request("STOP_ALL")
        self.request("SHUTDOWN")
        self.client.close_failure = True
        with self.assertRaises(bridge_module.BridgeError):
            self.request("FINALIZE")
        self.assertFalse(self.bridge.finalized)

    def test_normal_bridge_unchanged_and_rejects_role_requests(self):
        unconfigured = object.__new__(bridge_module.PersistentRecallBridge)
        unconfigured.failed = False
        unconfigured.finalized = False
        unconfigured.request_count = 0
        unconfigured.last_id = 0
        with self.assertRaisesRegex(bridge_module.BridgeError, "disabled"):
            unconfigured.dispatch({"id": 1, "op": "LAUNCH_ROLE", "role": "writer"})
        with self.assertRaises(bridge_module.BridgeError):
            self.request("LAUNCH_ROLE", role="a", argv=("dd",), mapper="/dev/sda")

    def test_replayed_ids_and_mixed_test_workers_rejected(self):
        self.role("writer")
        with self.assertRaises(bridge_module.BridgeError):
            self.bridge.dispatch({"id": 1, "op": "WAIT", "handle": "x", "timeout_ms": 0})
        with self.assertRaises(RoleError):
            self.request("LAUNCH_TEST", command="exit", code=0)


if __name__ == "__main__":
    unittest.main()
