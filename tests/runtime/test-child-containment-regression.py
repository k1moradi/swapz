#!/usr/bin/env python3
"""Rootless process-containment and supervisor-crash regressions.

The only workers are short-lived test-created Python children.  They use no
device paths; a fake role gate supplies descriptor-pinned test executables.
"""

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import select
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SERVICE_PATH = HERE / "test-child-supervisor-service.py"


def load_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


service = load_module("child_containment_service", SERVICE_PATH)
SupervisorControlClient = service.SupervisorControlClient
ChannelFailure = service.ChannelFailure
_HEADER = service._HEADER


_HELPER = r'''import importlib.util, json, os, socket, sys, time
from pathlib import Path

service_path = Path(sys.argv[1])
sock_fd = int(sys.argv[2])
root = Path(sys.argv[3])
stage = sys.argv[4]
spec = importlib.util.spec_from_file_location("containment_service_child", service_path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
supervisor_module = module._SUPERVISOR_MODULE

def mark(name, value="ready"):
    (root / name).write_text(str(value))

def await_release():
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if (root / "release").exists():
            return
        time.sleep(0.005)
    os._exit(73)

class CrashOps(supervisor_module.LinuxPidfdOps):
    def fork(self):
        pid = super().fork()
        if pid > 0:
            mark("worker-pid", pid)
            with open(root / "worker-pids", "a", encoding="ascii") as handle:
                handle.write(str(pid) + "\n")
        return pid
    def install_process_containment(self, expected_parent_pid, expected_parent_pidfd):
        super().install_process_containment(expected_parent_pid, expected_parent_pidfd)
        mark("containment-ready")
    def pidfd_open(self, pid):
        if stage == "before-pidfd":
            mark("failure-point")
            await_release()
            os._exit(71)
        pidfd = super().pidfd_open(pid)
        if stage == "after-pidfd":
            mark("failure-point")
            await_release()
        return pidfd
    def write(self, fd, data):
        if stage == "after-pidfd" and data == b"G":
            mark("failure-point-gate-release")
            os._exit(72)
        return super().write(fd, data)

executable_fd = os.open(sys.executable, os.O_RDONLY | os.O_CLOEXEC)
worker_code = (
    "from pathlib import Path; import time; "
    f"Path({str(root / 'worker-started')!r}).write_text('started'); "
    "time.sleep(60)"
)
launch = module.PinnedDDLaunch(
    "writer", ("test-worker", "-c", worker_code), None,
    f"/proc/self/fd/{executable_fd}", executable_fd, (), None,
)

class Gate:
    def admit(self, role):
        return launch
    def close_admission(self):
        pass
    def close(self):
        try:
            os.close(executable_fd)
        except OSError:
            return ("injected or repeated executable fd close failure",)
        return ()

ops = CrashOps()
supervisor = supervisor_module.GatedPidfdSupervisor(
    ops=ops, startup_timeout=2.0, term_grace=0.2, kill_grace=0.2, escalate=True
)
control = module.SupervisorControlService(
    supervisor=supervisor, io_timeout=8.0,
    recall_dd_gate=Gate(), enable_direct_dd=True,
)
sock = socket.socket(fileno=sock_fd)
if stage == "before-ack":
    original_send = module.send_frame
    def delayed_send(target, message, timeout):
        if message.get("status") == "ready":
            mark("failure-point")
            await_release()
        return original_send(target, message, timeout)
    module.send_frame = delayed_send
outcome = control.serve(sock)
try:
    sock.close()
except OSError:
    pass
print(json.dumps({"exit_code": outcome.exit_code, "status": outcome.status,
                  "all_reaped": outcome.all_reaped,
                  "cleanup_allowed": outcome.cleanup_allowed}), flush=True)
raise SystemExit(outcome.exit_code)
'''


def wait_for_path(path: Path, timeout: float = 4.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.005)
    return path.exists()


def pidfd_ready(pidfd: int, timeout: float) -> bool:
    poller = select.poll()
    poller.register(pidfd, select.POLLIN | select.POLLHUP | select.POLLERR)
    return bool(poller.poll(int(timeout * 1000)))


class CrashContainmentTests(unittest.TestCase):
    def start_service(self, directory: Path, stage: str):
        client_sock, server_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        process = subprocess.Popen(
            [sys.executable, "-c", _HELPER, str(SERVICE_PATH),
             str(server_sock.fileno()), str(directory), stage],
            pass_fds=(server_sock.fileno(),),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            close_fds=True,
            start_new_session=True,
        )
        server_sock.close()
        return process, client_sock

    def open_worker_pidfd(self, directory: Path) -> int:
        self.assertTrue(wait_for_path(directory / "worker-pid"), "service did not fork the test worker")
        pid = int((directory / "worker-pid").read_text())
        self.assertTrue(wait_for_path(directory / "containment-ready"),
                        "worker did not install parent-death and seccomp containment")
        return os.pidfd_open(pid)

    def open_worker_pidfds(self, directory: Path, count: int) -> list[int]:
        path = directory / "worker-pids"
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            if path.exists():
                lines = [line for line in path.read_text().splitlines() if line]
                if len(lines) >= count:
                    return [os.pidfd_open(int(line)) for line in lines[:count]]
            time.sleep(0.005)
        self.fail(f"service did not record {count} test workers")

    def assert_worker_dead_or_cleanup(self, pidfd: int) -> None:
        if not pidfd_ready(pidfd, 3.0):
            # Last-resort test cleanup targets this test-owned worker through
            # the already-retained pidfd, never a numeric PID.
            signal.pidfd_send_signal(pidfd, signal.SIGKILL)
            self.assertTrue(pidfd_ready(pidfd, 3.0), "test-owned worker could not be terminated")
            self.fail("supervisor death did not terminate its contained worker")

    def exercise_crash_stage(self, stage: str, expected_exit: int, *, kill_service: bool) -> None:
        with tempfile.TemporaryDirectory(prefix=f"swapz-contained-{stage}-") as temporary:
            directory = Path(temporary)
            process, client_sock = self.start_service(directory, stage)
            worker_pidfd = None
            try:
                client_sock.sendall(service.encode_frame(
                    {"id": 1, "op": "launch", "command": "recall-dd", "role": "writer"}
                ))
                marker_name = "failure-point"
                if stage == "after-pidfd":
                    marker_name = "failure-point"
                if stage == "before-ack":
                    self.assertTrue(wait_for_path(directory / "worker-started"),
                                    "contained worker did not start before READY delivery")
                self.assertTrue(wait_for_path(directory / marker_name),
                                f"helper missed injected failure point {stage}")
                worker_pidfd = self.open_worker_pidfd(directory)
                if stage in {"before-pidfd", "after-pidfd"}:
                    (directory / "release").touch()
                    if stage == "after-pidfd":
                        self.assertTrue(wait_for_path(directory / "failure-point-gate-release"),
                                        "pidfd stage did not reach gated release boundary")
                elif kill_service:
                    # Popen owns this isolated helper process; no host service
                    # or unrelated PID is signaled.
                    process.kill()
                self.assert_worker_dead_or_cleanup(worker_pidfd)
                stdout, stderr = process.communicate(timeout=3.0)
                self.assertEqual(process.returncode, expected_exit, (stdout, stderr))
                client_sock.settimeout(1.0)
                self.assertEqual(client_sock.recv(1), b"", "crashed supervisor sent a success response")
            finally:
                if process.poll() is None:
                    process.kill()
                    try:
                        process.wait(timeout=3.0)
                    except subprocess.TimeoutExpired:
                        pass
                if worker_pidfd is not None:
                    if not pidfd_ready(worker_pidfd, 0.5):
                        signal.pidfd_send_signal(worker_pidfd, signal.SIGKILL)
                        pidfd_ready(worker_pidfd, 2.0)
                    os.close(worker_pidfd)
                client_sock.close()

    def test_supervisor_termination_before_pidfd_acquisition_kills_gated_worker(self):
        self.exercise_crash_stage("before-pidfd", 71, kill_service=False)

    def test_supervisor_termination_after_pidfd_before_gate_release_kills_worker(self):
        self.exercise_crash_stage("after-pidfd", 72, kill_service=False)

    def test_service_termination_after_exec_before_ready_ack_kills_worker(self):
        self.exercise_crash_stage("before-ack", -signal.SIGKILL, kill_service=True)

    def test_lost_control_channel_during_active_worker_reaps_but_denies_cleanup(self):
        with tempfile.TemporaryDirectory(prefix="swapz-contained-disconnect-") as temporary:
            directory = Path(temporary)
            process, client_sock = self.start_service(directory, "disconnect")
            client = SupervisorControlClient(client_sock, service_process=process, timeout=4.0)
            worker_pidfd = None
            try:
                ready = client.call("launch", command="recall-dd", role="writer")
                self.assertEqual(ready["status"], "ready")
                worker_pidfd = self.open_worker_pidfd(directory)
                client.sock.close()
                stdout, stderr = process.communicate(timeout=4.0)
                self.assertEqual(process.returncode, 2, (stdout, stderr))
                self.assertIn('"all_reaped": true', stdout)
                self.assertIn('"cleanup_allowed": false', stdout)
                self.assertFalse(client.cleanup_authorized)
                self.assert_worker_dead_or_cleanup(worker_pidfd)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=3.0)
                if worker_pidfd is not None:
                    if not pidfd_ready(worker_pidfd, 0.5):
                        signal.pidfd_send_signal(worker_pidfd, signal.SIGKILL)
                        pidfd_ready(worker_pidfd, 2.0)
                    os.close(worker_pidfd)

    def test_malformed_control_frame_during_active_worker_denies_cleanup(self):
        with tempfile.TemporaryDirectory(prefix="swapz-contained-malformed-") as temporary:
            directory = Path(temporary)
            process, client_sock = self.start_service(directory, "success")
            worker_pidfd = None
            try:
                client_sock.sendall(service.encode_frame(
                    {"id": 1, "op": "launch", "command": "recall-dd", "role": "writer"}
                ))
                ready = service.recv_frame(client_sock, 3.0)
                self.assertEqual(ready["status"], "ready")
                worker_pidfd = self.open_worker_pidfd(directory)
                client_sock.sendall(b"\x00\x00\x00\x01{")
                error_response = service.recv_frame(client_sock, 3.0)
                self.assertEqual(error_response["status"], "protocol_error")
                self.assertFalse(error_response["cleanup_allowed"])
                self.assertTrue(error_response["preserve_backing"])
                stdout, stderr = process.communicate(timeout=4.0)
                self.assertEqual(process.returncode, 2, (stdout, stderr))
                self.assertIn("protocol failure", stderr)
                self.assert_worker_dead_or_cleanup(worker_pidfd)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=3.0)
                if worker_pidfd is not None:
                    if not pidfd_ready(worker_pidfd, 0.5):
                        signal.pidfd_send_signal(worker_pidfd, signal.SIGKILL)
                        pidfd_ready(worker_pidfd, 2.0)
                    os.close(worker_pidfd)
                client_sock.close()

    def test_two_worker_inventory_cleanup_requires_both_reaped(self):
        with tempfile.TemporaryDirectory(prefix="swapz-contained-inventory-") as temporary:
            directory = Path(temporary)
            process, client_sock = self.start_service(directory, "success")
            client = SupervisorControlClient(client_sock, service_process=process, timeout=6.0)
            worker_pidfds: list[int] = []
            try:
                first = client.call("launch", command="recall-dd", role="writer")
                second = client.call("launch", command="recall-dd", role="a")
                self.assertEqual(first["status"], "ready")
                self.assertEqual(second["status"], "ready")
                worker_pidfds = self.open_worker_pidfds(directory, 2)
                handles = [first["handle"], second["handle"]]
                report = client.call("stop_all", handles=handles)
                self.assertTrue(report["cleanup_allowed"])
                self.assertEqual({row["handle"] for row in report["workers"]}, set(handles))
                self.assertTrue(all(row["reaped"] and not row["errors"]
                                    for row in report["workers"]))
                self.assertTrue(all(pidfd_ready(pidfd, 1.0) for pidfd in worker_pidfds),
                                "both actual worker processes must be dead after stop_all")
                shutdown = client.call("shutdown")
                self.assertTrue(shutdown["cleanup_allowed"])
                stdout, stderr = process.communicate(timeout=4.0)
                self.assertEqual(process.returncode, 0, (stdout, stderr))
                self.assertTrue(client.confirm_service_exit(process.returncode))
                self.assertTrue(client.cleanup_authorized)
                client.close()
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=3.0)
                for pidfd in worker_pidfds:
                    if not pidfd_ready(pidfd, 0.5):
                        signal.pidfd_send_signal(pidfd, signal.SIGKILL)
                        pidfd_ready(pidfd, 2.0)
                    os.close(pidfd)
                if not client.sock.fileno() == -1:
                    client.sock.close()

    def test_supervisor_execs_sealed_executable_with_containment_before_cleanup(self):
        source_fd = os.open(sys.executable, os.O_RDONLY | os.O_CLOEXEC)
        snapshot_fd = None
        supervisor = service._SUPERVISOR_MODULE.GatedPidfdSupervisor(
            term_grace=0.2, kill_grace=0.2, escalate=True,
        )
        handle = None
        cleanup_complete = False
        try:
            source_size = os.fstat(source_fd).st_size
            source_bytes = os.pread(source_fd, source_size, 0)
            self.assertEqual(len(source_bytes), source_size)
            snapshot_fd = service._ALLOWLIST_MODULE.RecallDDFileOps().create_sealed_executable(
                source_fd, hashlib.sha256(source_bytes).hexdigest(), 128 * 1024 * 1024,
            )
            handle = supervisor.launch(
                ("sealed-test-worker", "-c", "raise SystemExit(0)"),
                executable=f"/proc/self/fd/{snapshot_fd}",
                executable_fd=snapshot_fd,
                strict_fds=True,
            )
            self.assertTrue(supervisor.worker_for_test(handle).containment_installed)
            result = supervisor.wait(handle, 3.0)
            self.assertTrue(result.reaped, result.errors)
            self.assertEqual(result.exit_code, 0, result.errors)
            report = supervisor.stop_all([handle])
            cleanup_complete = True
            self.assertTrue(report.cleanup_allowed, report)
            self.assertEqual(len(report.results), 1)
            self.assertTrue(report.results[0].reaped)
        finally:
            if handle is not None and not cleanup_complete:
                supervisor.cleanup_after_stop([handle], lambda: None)
            if snapshot_fd is not None:
                os.close(snapshot_fd)
            os.close(source_fd)


if __name__ == "__main__":
    unittest.main(verbosity=2)
