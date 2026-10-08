#!/usr/bin/env python3
"""True IPC service/client role protocol with rootless synthetic worker I/O.

The actual service and descriptor gate run in a thread behind a private UNIX
socket. Only the pidfd supervisor is replaced with a non-forking fake that
writes private regular files. No real dd, device, mapper or child process runs.
The separate pinned-worker regression runs actual GNU dd.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import threading
import unittest


HERE = Path(__file__).resolve().parent


def load(name: str, filename: str):
    specification = importlib.util.spec_from_file_location(name, HERE / filename)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


service_module = load("swapz_live_role_protocol_service", "test-child-supervisor-service.py")
adapter_module = load("swapz_live_role_protocol_adapter", "recall-ipc-adapter.py")
readback_module = load("swapz_live_role_protocol_readback", "recall-readback-identity.py")
bridge_module = load("swapz_live_role_protocol_bridge", "recall-control-bridge.py")

PAGES = {"a": 0, "b": 4, "a2": 0, "b2": 5}
PAGE_SIZE = 4096


class TrustedSyntheticGate:
    """Wrap the *real* role gate to snapshot readback FD identity before launch."""

    def __init__(self, gate, directory_fd: int):
        self.gate = gate
        self.directory_fd = directory_fd
        self.pending_role = None
        self.output_identities = {}

    def admit(self, role):
        approved = self.gate.admit(role)
        if role in PAGES:
            descriptor = self.gate._output_fds[role]
            self.output_identities[role] = readback_module.capture_readback_identity(
                self.directory_fd, descriptor, role
            )
        self.pending_role = role
        return approved

    def close_admission(self):
        self.gate.close_admission()

    def close(self):
        return self.gate.close()


class SyntheticDirectSupervisor:
    """Test-owned, non-forking supervisor, NEVER a device/production worker."""

    def __init__(self, gate: TrustedSyntheticGate, reference: bytes):
        self.gate = gate
        self.reference = reference
        self.workers = {}
        self.next_number = 0
        self.events = []

    def launch(self, argv, *, env, **options):
        role = self.gate.pending_role
        self.events.append(("launch", role))
        assert role in ("writer", *PAGES)
        assert options.get("strict_fds") is True
        assert options.get("executable_fd") is not None
        assert "argv" not in options and "PATH" in env
        self.next_number += 1
        handle = f"trusted-role-{self.next_number}"
        self.workers[handle] = False
        if role in PAGES:
            offset = PAGES[role] * PAGE_SIZE
            data = self.reference[offset:offset + PAGE_SIZE]
            descriptor = self.gate.gate._output_fds[role]
            assert os.write(descriptor, data) == PAGE_SIZE
        return handle

    def worker_for_test(self, handle):
        return type("WorkerView", (), {"reaped": self.workers[handle]})()

    def wait(self, handle, timeout):
        self.events.append(("wait", handle))
        self.workers[handle] = True
        return service_module.WorkerResult(handle, True, 0, False, ())

    def cleanup_after_stop(self, handles, callback):
        self.events.append(("stop_all", ""))
        matches = set(handles) == set(self.workers) and len(handles) == len(self.workers)
        records = []
        for handle in self.workers:
            self.workers[handle] = True
            records.append(service_module.WorkerResult(handle, True, 0, False, ()))
        return service_module.StopReport(tuple(records), (), matches), (
            callback() if matches else None
        )


class InProcessServiceOutcome:
    """The exact threaded service's outcome; not an OS process-exit proof."""

    def __init__(self, thread, outcomes):
        self.thread = thread
        self.outcomes = outcomes

    def wait(self, timeout=None):
        self.thread.join(timeout)
        if self.thread.is_alive() or len(self.outcomes) != 1:
            raise TimeoutError("trusted synthetic IPC service did not exit")
        return self.outcomes[0].exit_code

    def poll(self):
        return self.outcomes[0].exit_code if not self.thread.is_alive() and self.outcomes else None


class RoleServiceWireTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="swapz-role-service-wire-")
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name) / "fixture"
        self.directory.mkdir(mode=0o700)
        self.reference = b"".join(
            bytes(((page * 11 + offset) % 256) for offset in range(PAGE_SIZE))
            for page in range(9)
        )
        (self.directory / "pages.bin").write_bytes(self.reference)
        (self.directory / "pages.bin").chmod(0o600)
        mapper = Path(temp.name) / "synthetic-mapper-regular-file"
        mapper.write_bytes(bytes(len(self.reference)))
        mapper_fd = os.open(mapper, os.O_RDWR | os.O_CLOEXEC)
        directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY |
                              os.O_NOFOLLOW | os.O_CLOEXEC)
        self.addCleanup(os.close, directory_fd)
        try:
            gate = service_module.RecallDDLaunchGate(
                self.directory, "swapz-v22-recall-wiretest",
                mapper_fd=mapper_fd, executable_path=Path("/usr/bin/dd"),
                mapper_verifier=lambda fd, name, ops: (
                    name == "swapz-v22-recall-wiretest"
                    and stat.S_ISREG(ops.fstat(fd).st_mode)
                ),
            )
        finally:
            os.close(mapper_fd)
        self.addCleanup(gate.close)
        self.gate = TrustedSyntheticGate(gate, directory_fd)
        self.supervisor = SyntheticDirectSupervisor(self.gate, self.reference)
        self.service = service_module.SupervisorControlService(
            supervisor=self.supervisor, recall_dd_gate=self.gate,
            enable_direct_dd=True, io_timeout=1.0
        )
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.client = service_module.SupervisorControlClient(parent, timeout=3.0)
        self.addCleanup(self._close_connection)
        self.outcomes = []

        def run_service():
            try:
                self.outcomes.append(self.service.serve(child))
            finally:
                child.close()

        self.thread = threading.Thread(target=run_service, name="rootless-role-wire")
        self.thread.start()
        self.process = InProcessServiceOutcome(self.thread, self.outcomes)

        def verify_role(role):
            readback_module.verify_readback(
                self.gate.output_identities[role],
                directory_fd=directory_fd,
                output_fd=self.gate.gate._output_fds[role],
                expected_page=self.reference[PAGES[role] * PAGE_SIZE:(PAGES[role] + 1) * PAGE_SIZE],
            )
            return True

        self.adapter = adapter_module.RecallRoleIPCAdapter(
            self.client, self.process, verify_role_result=verify_role, exit_timeout=3.0
        )
        self.bridge = bridge_module.RootlessRoleBridge(
            client=self.client, process=self.process, adapter=self.adapter
        )
        self.ident = 0

    def _close_connection(self):
        try:
            self.client.close()
        except OSError:
            pass
        self.thread.join(timeout=4.0)
        self.assertFalse(self.thread.is_alive(), "test-only service worker leaked")

    def send(self, op, **fields):
        self.ident += 1
        return self.bridge.dispatch({"id": self.ident, "op": op, **fields})

    def run_all(self):
        writer = self.send("LAUNCH_ROLE", role="writer")["handle"]
        a = self.send("LAUNCH_ROLE", role="a")["handle"]
        self.send("WAIT", handle=a, timeout_ms=1500)
        b = self.send("LAUNCH_ROLE", role="b")["handle"]
        self.send("WAIT", handle=b, timeout_ms=1500)
        a2 = self.send("LAUNCH_ROLE", role="a2")["handle"]
        b2 = self.send("LAUNCH_ROLE", role="b2")["handle"]
        self.send("WAIT", handle=a2, timeout_ms=1500)
        self.send("WAIT", handle=b2, timeout_ms=1500)
        self.send("WAIT", handle=writer, timeout_ms=1500)
        return writer, a, b, a2, b2

    def test_actual_ipc_protocol_and_all_five_pinned_roles(self):
        handles = self.run_all()
        self.assertEqual(len(set(handles)), 5)
        events = self.supervisor.events
        self.assertLess(events.index(("launch", "a2")), events.index(("wait", handles[3])))
        self.assertLess(events.index(("launch", "b2")), events.index(("wait", handles[3])))
        stopped = self.send("STOP_ALL")
        self.assertFalse(stopped["cleanup_allowed"])
        self.assertEqual({r["handle"] for r in stopped["workers"]}, set(handles))
        self.assertFalse(self.send("SHUTDOWN")["cleanup_allowed"])
        final = self.send("FINALIZE")
        self.assertTrue(final["cleanup_allowed"])
        self.assertFalse(final["preserve_backing"])
        self.assertEqual(self.process.poll(), 0)
        self.assertEqual(self.gate.gate.close(), ())

    def test_swapped_readback_entry_denies_before_cleanup(self):
        self.send("LAUNCH_ROLE", role="writer")
        reader = self.send("LAUNCH_ROLE", role="a")["handle"]
        entry = self.directory / "read-a"
        entry.rename(self.directory / "original-a")
        entry.write_bytes(self.reference[:PAGE_SIZE])
        with self.assertRaisesRegex(adapter_module.RecallIPCError, "pathname"):
            self.send("WAIT", handle=reader, timeout_ms=1500)
        self.assertFalse(self.adapter.cleanup_authorized)

    def test_unknown_role_and_wrong_request_fields_fail_closed(self):
        with self.assertRaises(adapter_module.RecallIPCError):
            self.send("LAUNCH_ROLE", role="a")
        self.assertFalse(self.adapter.cleanup_authorized)


if __name__ == "__main__":
    unittest.main()
