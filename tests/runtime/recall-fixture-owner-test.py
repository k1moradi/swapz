#!/usr/bin/env python3
"""Adversarial rootless tests for the fixture-owner and evidence producer.

All mapper/swap/loop observations are in-memory fakes. The only real files are
private temporary regular files used to exercise descriptor and flock lifetime
in the existing MapperLifecycleOwner. No device node or privileged operation
is opened or invoked.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import select
import signal
import stat
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import dataclasses
import ctypes
from types import SimpleNamespace


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "recall_fixture_owner_tested", HERE / "recall-fixture-owner.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load fixture owner")
owner_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = owner_module
SPEC.loader.exec_module(owner_module)

allow = owner_module._ALLOWLIST
MapperIdentity = allow.MapperIdentity
MapperInventory = allow.MapperInventory
MapperLifecycleLease = allow.MapperLifecycleLease
MapperLifecycleOwner = allow.MapperLifecycleOwner
MapperOpenersObservation = allow.MapperOpenersObservation
MapperSuspendObservation = allow.MapperSuspendObservation
MapperRemovalObservation = allow.MapperRemovalObservation
WorkerCompletionEvidence = allow.WorkerCompletionEvidence
WorkerRoleResult = allow.WorkerRoleResult
worker_completion_payload = allow.worker_completion_payload
FixtureOwnerBroker = owner_module.FixtureOwnerBroker
FixtureOwnerDenied = owner_module.FixtureOwnerDenied
SwapInventoryObservation = owner_module.SwapInventoryObservation
SwapoffObservation = owner_module.SwapoffObservation
LowerDependencyObservation = owner_module.LowerDependencyObservation
LoopDetachObservation = owner_module.LoopDetachObservation
LoopInventoryObservation = owner_module.LoopInventoryObservation
WorkerLaunchReceipt = owner_module.WorkerLaunchReceipt
WorkerStopReport = owner_module.WorkerStopReport


class FakeMapperFileOps(allow.RecallDDFileOps):
    def __init__(self, mapper_fd: int, identity: MapperIdentity):
        self.mapper_fds = {mapper_fd}
        self.identity = identity
        self.closed_mapper_fds: list[int] = []

    def fstat(self, fd):
        if fd in self.mapper_fds:
            return SimpleNamespace(
                st_mode=stat.S_IFBLK | 0o600, st_rdev=os.makedev(self.identity.major, self.identity.minor),
                st_uid=os.geteuid(), st_dev=1, st_ino=self.identity.minor,
                st_size=0, st_mtime_ns=0, st_ctime_ns=0, st_nlink=1,
            )
        return super().fstat(fd)

    def read_dm_sysfs_attr(self, major, minor, attribute):
        values = {"name": self.identity.name, "uuid": self.identity.uuid,
                  "dev": f"{major}:{minor}"}
        if (major, minor) != (self.identity.major, self.identity.minor):
            raise OSError("unexpected synthetic DM device number")
        return values[attribute]

    def close(self, fd):
        if fd in self.mapper_fds:
            self.mapper_fds.remove(fd)
            self.closed_mapper_fds.append(fd)
        return super().close(fd)


class FakeMapperOperations:
    def __init__(self, identity: MapperIdentity, mapper_fd: int, worker_key: bytes):
        self.identity = identity
        self.mapper_fd = mapper_fd
        self.worker_key = worker_key
        self.entries: tuple[MapperIdentity, ...] = ()
        self.alive = True
        self.trace: list[str] = []
        self.fail: set[str] = set()
        self.suspend_result = MapperSuspendObservation(
            True, True, False, False, True, True, True,
        )
        self.openers_result = MapperOpenersObservation(True, True, 0, ())

    def owner_alive(self):
        self.trace.append("owner_alive")
        if "owner_alive" in self.fail:
            raise OSError("injected owner inspection error")
        return self.alive

    def inventory(self):
        self.trace.append("dm_inventory")
        if "dm_inventory" in self.fail:
            return MapperInventory(False, self.entries)
        return MapperInventory(True, self.entries)

    def create_mapping(self, identity):
        self.trace.append("dm_create")
        if identity != self.identity or self.entries:
            raise AssertionError("unexpected or duplicate synthetic mapper creation")
        self.entries = (identity,)
        return self.mapper_fd

    def verify_worker_completion(self, evidence):
        self.trace.append("worker_attestation")
        expected = hmac.new(
            self.worker_key, worker_completion_payload(evidence), hashlib.sha256,
        ).digest()
        return hmac.compare_digest(evidence.authenticator, expected)

    def suspend_mapping(self, identity, *, noflush):
        self.trace.append("dm_suspend")
        if identity != self.identity or noflush is not False:
            raise AssertionError("only ordinary suspend of the exact synthetic mapper is allowed")
        if "dm_suspend" in self.fail:
            return MapperSuspendObservation(False, True, False, False, True, False, False)
        return self.suspend_result

    def inspect_openers(self, identity):
        self.trace.append("dm_openers")
        if identity != self.identity:
            raise AssertionError("unexpected synthetic mapper open-count query")
        if "dm_openers" in self.fail:
            raise OSError("injected holder inventory failure")
        return self.openers_result

    def remove_mapping(self, identity):
        self.trace.append("dm_remove_normal")
        if identity != self.identity:
            raise AssertionError("unexpected synthetic mapper removal")
        if "dm_remove" in self.fail:
            return MapperRemovalObservation(False, True, False, False, True)
        self.entries = ()
        return MapperRemovalObservation(True, True, False, False, True)


class FakeOwnedWorkerLauncher:
    """Models a gated pidfd supervisor; no actual worker process is started."""

    def __init__(self, handles, stop_calls):
        self.handles = handles
        self.stop_calls = stop_calls
        self.pending: list[str] = []
        self.release_calls: list[tuple[str, ...]] = []
        self.unconfirmed_stop_calls = 0
        self.fail: set[str] = set()

    def launch(self, role, *, startup_timeout):
        if startup_timeout <= 0:
            raise AssertionError("startup handshake must be bounded")
        handle = f"owned-{role}-{len(self.handles) + 1}"
        self.handles.append(handle)
        self.pending.append(handle)
        if "launch_after_child" in self.fail:
            raise OSError("injected lost READY after child creation")
        if "duplicate_handle" in self.fail:
            handle = self.handles[0]
        if "missing_ready" in self.fail:
            return WorkerLaunchReceipt(handle, role, False, True, True, True)
        return WorkerLaunchReceipt(handle, role, True, True, True, True)

    def release_group(self, handles):
        if "release" in self.fail:
            raise OSError("injected gate release failure")
        if any(handle not in self.pending for handle in handles):
            raise AssertionError("only known gated handles can be released")
        self.release_calls.append(tuple(handles))
        for handle in handles:
            self.pending.remove(handle)

    def stop_unconfirmed(self):
        self.unconfirmed_stop_calls += 1
        if "stop_unconfirmed" in self.fail:
            return WorkerStopReport(False, ("unconfirmed child remains",))
        self.pending.clear()
        return WorkerStopReport(True, ())

    def stop_all(self, handles):
        self.stop_calls.append(tuple(handles))
        if "stop_all" in self.fail:
            return WorkerStopReport(False, ("worker remains",))
        return WorkerStopReport(True, ())


class SyntheticPidfdWorkerLauncher:
    """Real, bounded test children; the only work is a regular-file marker."""

    CHILD_CODE = (
        "import ctypes,os,signal,sys; gate=int(sys.argv[1]); out=int(sys.argv[2]); "
        "role=sys.argv[3]; hold=sys.argv[4]=='1'; expected_parent=int(sys.argv[5]); "
        "libc=ctypes.CDLL(None,use_errno=True); "
        "(os._exit(90) if libc.prctl(1,signal.SIGTERM,0,0,0)!=0 or os.getppid()!=expected_parent else None); "
        "first=os.read(gate,1); "
        "(os.write(1,b'R') if first==b'P' else os._exit(91)); "
        "second=os.read(gate,1); "
        "(os.write(out,(role+'\\n').encode()) if second==b'G' else os._exit(92)); "
        "os.close(out); "
        "(signal.pause() if hold else None); os.close(gate); os._exit(0)"
    )

    def __init__(self, output_dir: Path, *, fail: str | None = None, hold_roles=()):
        self.output_dir = output_dir
        self.fail = fail
        self.hold_roles = frozenset(hold_roles)
        self.children: dict[str, dict[str, object]] = {}
        self.pending: set[str] = set()
        self.handles: list[str] = []
        self.releases: list[tuple[str, ...]] = []
        self.pidfd_close_counts: dict[str, int] = {}
        self.signal_calls: list[tuple[str, int, int]] = []
        self._counter = 0
        self.worker_results: tuple[WorkerRoleResult, ...] = ()

    def launch(self, role, *, startup_timeout):
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            raise OSError("pidfd APIs unavailable; refusing numeric-PID fallback")
        if not 0 < startup_timeout <= 10:
            raise AssertionError("startup handshake timeout must be bounded")
        self._counter += 1
        handle = f"pidfd-owned-{role}-{self._counter}"
        output = self.output_dir / f"worker-{self._counter}.out"
        gate_r, gate_w = os.pipe2(os.O_CLOEXEC)
        output_fd = os.open(
            output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        proc = None
        record = {
            "role": role, "handle": handle, "output": output,
            "pidfd": None, "gate_w": gate_w, "gate_open": True,
            "control_open": True,
            "proc": None, "reaped": False, "pidfd_closed": False,
        }
        try:
            proc = subprocess.Popen(
                [sys.executable, "-c", self.CHILD_CODE, str(gate_r), str(output_fd), role,
                 "1" if role in self.hold_roles else "0", str(os.getpid())],
                close_fds=True, pass_fds=(gate_r, output_fd),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            record["proc"] = proc
            # Retain ownership before any gate byte can let worker code run.
            self.children[handle] = record
            self.handles.append(handle)
            self.pending.add(handle)
            os.close(output_fd)
            output_fd = -1
            os.close(gate_r)
            gate_r = -1
            if self.fail == "pidfd" and self._counter == 1:
                raise OSError("injected pidfd acquisition failure")
            pidfd = os.pidfd_open(proc.pid, 0)
            record["pidfd"] = pidfd
            if self.fail == "lost_ready" and self._counter == 1:
                os.write(gate_w, b"P")
                raise TimeoutError("injected lost READY after child creation")
            os.write(gate_w, b"P")
            ready_fd = proc.stdout.fileno()
            ready, _, _ = select.select((ready_fd,), (), (), startup_timeout)
            if not ready or os.read(ready_fd, 1) != b"R":
                raise TimeoutError("synthetic worker did not send READY before deadline")
            return WorkerLaunchReceipt(handle, role, True, True, True, True)
        except Exception:
            if proc is None:
                os.close(gate_w)
                record["gate_open"] = False
            raise
        finally:
            if output_fd >= 0:
                os.close(output_fd)
            if gate_r >= 0:
                os.close(gate_r)

    def release_group(self, handles):
        handles = tuple(handles)
        if not handles or any(handle not in self.pending for handle in handles):
            raise FixtureOwnerDenied("test launcher release references an unknown or started child")
        # Validate every pidfd before releasing any member of the cohort.
        for handle in handles:
            record = self.children[handle]
            if type(record["pidfd"]) is not int or record["pidfd_closed"]:
                raise FixtureOwnerDenied("test worker has no retained pidfd")
        released = []
        try:
            for handle in handles:
                record = self.children[handle]
                os.write(record["gate_w"], b"G")
                record["gate_open"] = False
                if record["role"] not in self.hold_roles:
                    os.close(record["gate_w"])
                    record["control_open"] = False
                self.pending.remove(handle)
                released.append(handle)
            self.releases.append(handles)
        except Exception:
            # Partial release is ambiguous; owner denial and preservation are
            # mandatory. The launcher still retains every child pidfd.
            raise

    def stop_unconfirmed(self):
        errors = []
        for handle in tuple(self.pending):
            record = self.children[handle]
            try:
                if record["gate_open"]:
                    os.write(record["gate_w"], b"A")
                    os.close(record["gate_w"])
                    record["gate_open"] = False
                    record["control_open"] = False
                self._wait_reap(record, 1.0)
                self.pending.discard(handle)
            except Exception as exc:
                errors.append(f"{handle}: {exc}")
        return WorkerStopReport(not errors and not self.pending, tuple(errors))

    def stop_all(self, handles):
        errors = []
        for handle in tuple(handles):
            record = self.children.get(handle)
            if record is None:
                errors.append(f"unknown child handle {handle}")
                continue
            try:
                if record["gate_open"]:
                    os.write(record["gate_w"], b"A")
                    os.close(record["gate_w"])
                    record["gate_open"] = False
                    record["control_open"] = False
                proc = record["proc"]
                if proc.poll() is None and not record["gate_open"]:
                    pidfd = record["pidfd"]
                    if type(pidfd) is not int:
                        raise OSError("active child has no retained pidfd")
                    self.signal_calls.append((handle, signal.SIGCONT, pidfd))
                    signal.pidfd_send_signal(pidfd, signal.SIGCONT)
                    self.signal_calls.append((handle, signal.SIGTERM, pidfd))
                    signal.pidfd_send_signal(pidfd, signal.SIGTERM)
                    try:
                        proc.wait(timeout=0.3)
                    except subprocess.TimeoutExpired:
                        self.signal_calls.append((handle, signal.SIGKILL, pidfd))
                        signal.pidfd_send_signal(pidfd, signal.SIGKILL)
                self._wait_reap(record, 1.0)
                self.pending.discard(handle)
            except Exception as exc:
                errors.append(f"{handle}: {exc}")
        return WorkerStopReport(not errors and all(
            self.children.get(handle, {}).get("reaped") is True for handle in handles
        ), tuple(errors))

    def _wait_reap(self, record, timeout):
        proc = record["proc"]
        if proc.poll() is None:
            proc.wait(timeout=timeout)
        record["reaped"] = proc.returncode is not None
        if not record["reaped"]:
            raise TimeoutError("synthetic child was not reaped")
        # Drain bounded output and retain the process result before closing pidfd.
        stdout_tail = proc.stdout.read() if proc.stdout is not None else b""
        stderr_tail = proc.stderr.read() if proc.stderr is not None else b""
        record["stdout_tail"] = stdout_tail
        record["stderr_tail"] = stderr_tail
        if record["control_open"]:
            os.close(record["gate_w"])
            record["control_open"] = False
        pidfd = record["pidfd"]
        if type(pidfd) is int and not record["pidfd_closed"]:
            os.close(pidfd)
            record["pidfd_closed"] = True
            handle = record["handle"]
            self.pidfd_close_counts[handle] = self.pidfd_close_counts.get(handle, 0) + 1

    def wait_for_all(self, handles):
        for handle in handles:
            record = self.children[handle]
            self._wait_reap(record, 1.0)
        self.worker_results = tuple(
            WorkerRoleResult(
                self.children[handle]["role"], handle,
                self.children[handle]["proc"].returncode,
                self.children[handle]["reaped"], self.children[handle]["pidfd_closed"], (),
            )
            for handle in handles
        )
        return self.worker_results

    def close(self):
        pending = self.stop_unconfirmed()
        active = tuple(handle for handle, record in self.children.items()
                       if record.get("reaped") is not True)
        stopped = self.stop_all(active)
        if not pending.all_reaped or not stopped.all_reaped:
            raise AssertionError("test cleanup could not reap its own synthetic worker")


class FakeDrainOperations:
    """Synthetic typed results that model operations, never kernel state."""

    def __init__(self, identity: MapperIdentity, worker_key: bytes, loop: str):
        self.identity = identity
        self.worker_key = worker_key
        self.loop = loop
        self.owner = None
        self.swap_active = True
        self.loop_present = True
        self.nbd_present = True
        self.worker_results: tuple[WorkerRoleResult, ...] | None = None
        self.fail: set[str] = set()
        self.trace: list[str] = []

    def bind_owner(self, owner):
        self.owner = owner

    def collect_worker_completion(self, handles):
        self.trace.append("worker_report")
        if "worker_report" in self.fail:
            return object()
        session = self.owner.lease.session_id
        reaped = handles[:-1] if "worker_incomplete" in self.fail else handles
        roles = tuple(self.owner._worker_roles)
        role_results = (self.worker_results if self.worker_results is not None else tuple(
            WorkerRoleResult(role, handle, 0, True, True, ())
            for role, handle in zip(roles, handles)
        ))
        if "role_result_failure" in self.fail and role_results:
            role_results = (WorkerRoleResult(roles[0], handles[0], 1, True, True, ("failed",)),) + role_results[1:]
        provisional = WorkerCompletionEvidence(
            session, handles, reaped, handles, 0, (), bytes(32), role_results,
        )
        authenticator = hmac.new(
            self.worker_key, worker_completion_payload(provisional), hashlib.sha256,
        ).digest()
        if "worker_bad_mac" in self.fail:
            authenticator = b"x" * 32
        return WorkerCompletionEvidence(
            session, handles, reaped, handles, 0, (), authenticator, role_results,
        )

    def inspect_swap(self, identity):
        self.trace.append("swap_inventory")
        if "swap_inventory" in self.fail:
            raise OSError("injected swap inventory failure")
        if identity != self.identity:
            return SwapInventoryObservation(True, self.swap_active, None, "c" * 64)
        return SwapInventoryObservation(
            True, self.swap_active, identity if self.swap_active else None,
            ("c" if self.swap_active else "d") * 64,
        )

    def swapoff(self, identity):
        self.trace.append("swapoff_exact_mapper")
        if "swapoff" in self.fail:
            return SwapoffObservation(True, False, identity == self.identity)
        if identity != self.identity:
            return SwapoffObservation(True, False, False)
        self.swap_active = False
        return SwapoffObservation(True, True, True)

    def inspect_lower_dependencies(self, identity, loop_device):
        self.trace.append("lower_dependencies")
        if "lower_inventory" in self.fail:
            return object()
        if identity != self.identity or loop_device != self.loop:
            return LowerDependencyObservation(False, False, (), False, (), "0" * 64)
        entries = self.owner.operations.entries
        return LowerDependencyObservation(
            True, not entries, (), True, (identity.name,) if not entries else (), "e" * 64,
        )

    def detach_loop(self, loop_device):
        self.trace.append("loop_detach_normal")
        if loop_device != self.loop or "loop_detach" in self.fail:
            return LoopDetachObservation(False, True, loop_device == self.loop)
        self.loop_present = False
        return LoopDetachObservation(True, True, True)

    def inspect_loop(self, loop_device):
        self.trace.append("loop_inventory")
        if "loop_inventory" in self.fail:
            raise OSError("injected loop inventory failure")
        return LoopInventoryObservation(
            loop_device == self.loop, self.loop_present, "f" * 64,
        )

    def disconnect_nbd(self, server, device):
        self.trace.append("nbd_disconnect_normal")
        if "nbd_disconnect" in self.fail:
            return owner_module.NBDDisconnectObservation(
                False, True, True, server.handle, True, True, True,
                device, server.major, server.minor,
            )
        self.nbd_present = False
        return owner_module.NBDDisconnectObservation(
            True, True, True, server.handle, True, True, True,
            device, server.major, server.minor,
        )

    def inspect_nbd(self, server, device):
        self.trace.append("nbd_inventory")
        if "nbd_inventory" in self.fail:
            return object()
        return owner_module.NBDInventoryObservation(
            True, self.nbd_present, server.handle, device,
            server.major, server.minor, "9" * 64,
        )


class FixtureOwnerBrokerTests(unittest.TestCase):
    IDENTITY = MapperIdentity("swapz-v22-recall-owner-test", "SWAPZ-OWNER-TEST", 253, 91, "a" * 64)
    LOOP = "/dev/loop91"
    WORKER_KEY = b"fixture worker attestation key used only by this rootless test"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swapz-fixture-owner-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        mapper_path = self.root / "synthetic-mapper-descriptor"
        mapper_path.write_bytes(b"temporary regular file; no device is opened")
        mapper_path.chmod(0o600)
        self.mapper_fd = os.open(mapper_path, os.O_RDONLY | os.O_CLOEXEC)
        self.addCleanup(lambda: os.close(self.mapper_fd) if self._fd_open(self.mapper_fd) else None)
        self.file_ops = FakeMapperFileOps(self.mapper_fd, self.IDENTITY)

        self.lock_path = self.root / "fixture-owner.lock"
        self.lock_path.touch(mode=0o600)
        self.lock_path.chmod(0o600)
        self.lock_fd = os.open(self.lock_path, os.O_RDWR | os.O_CLOEXEC)
        fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(lambda: os.close(self.lock_fd) if self._fd_open(self.lock_fd) else None)
        lease = MapperLifecycleLease(
            self.lock_fd, self.lock_path, self.IDENTITY,
            lambda _fd, _name, _ops: self.IDENTITY, ops=self.file_ops,
        )
        self.lease = lease
        self.addCleanup(self.lease.close)
        self.mapper_ops = FakeMapperOperations(self.IDENTITY, self.mapper_fd, self.WORKER_KEY)
        self.owner = MapperLifecycleOwner(
            self.IDENTITY, lease, self.mapper_ops, file_ops=self.file_ops,
        )
        self.drain_ops = FakeDrainOperations(self.IDENTITY, self.WORKER_KEY, self.LOOP)
        self.drain_ops.bind_owner(self.owner)
        self.worker_peer = object()
        self.stop_calls: list[tuple[str, ...]] = []
        self.handles: list[str] = []

        def authenticate(peer):
            return "worker" if peer is self.worker_peer else None

        self.launcher = FakeOwnedWorkerLauncher(self.handles, self.stop_calls)

        self.broker = FixtureOwnerBroker(
            self.owner, self.drain_ops, self.LOOP,
            peer_authenticator=authenticate, worker_launcher=self.launcher,
        )

    @staticmethod
    def _fd_open(fd: int) -> bool:
        try:
            os.fstat(fd)
            return True
        except OSError:
            return False

    def _request(self, request_id: str, role: str) -> dict[str, object]:
        return self.broker.worker_request(self.worker_peer, {
            "request_id": request_id, "operation": "launch_role", "role": role,
        })

    @staticmethod
    def _recv_exact_socket(sock, length):
        chunks = bytearray()
        sock.settimeout(3.0)
        while len(chunks) < length:
            part = sock.recv(length - len(chunks))
            if not part:
                raise AssertionError("test client saw a truncated broker response")
            chunks.extend(part)
        return bytes(chunks)

    def _new_case(self):
        case = FixtureOwnerBrokerTests("runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def _start_workers(self, roles=("writer", "a", "b", "a2", "b2")):
        self.broker.owner_create()
        for index, role in enumerate(roles):
            result = self._request(f"req-{index}", role)
            self.assertIn(result["status"], ("launched", "ready_gated"))
        return tuple(self.handles)

    def test_end_to_end_owner_broker_and_producer_sequence(self):
        handles = self._start_workers()
        self.assertTrue(self.broker.finalize())
        self.assertEqual(self.broker.state, self.broker.RELEASED)
        self.assertTrue(self.broker.mapping_released)
        self.assertTrue(self.broker.backing_release_authorized)
        self.assertFalse(self.broker.backing_must_be_preserved)
        self.assertEqual(self.owner.registered_worker_handles, handles)
        self.assertEqual(self.owner._worker_roles, ["writer", "a", "b", "a2", "b2"])
        self.assertEqual(self.launcher.release_calls[-1], (handles[3], handles[4]))
        self.assertEqual(self.launcher.release_calls[:3], [(handles[0],), (handles[1],), (handles[2],)])
        self.assertEqual(self.broker.evidence_events, (
            "admission_closed", "workers_reaped", "swap_quiescent",
            "dm_suspended:swapz-v22-recall-owner-test",
            "dm_descriptors_closed:swapz-v22-recall-owner-test",
            "dm_open_count_zero:swapz-v22-recall-owner-test",
            "dm_removed:swapz-v22-recall-owner-test", "dm_absent:swapz-v22-recall-owner-test",
            "loop_dependencies_clear", "loop_detached",
        ))
        self.assertLess(self.mapper_ops.trace.index("worker_attestation"),
                        self.mapper_ops.trace.index("dm_suspend"))
        self.assertLess(self.mapper_ops.trace.index("dm_suspend"),
                        self.mapper_ops.trace.index("dm_openers"))
        self.assertLess(self.mapper_ops.trace.index("dm_openers"),
                        self.mapper_ops.trace.index("dm_remove_normal"))
        self.assertLess(self.drain_ops.trace.index("swap_inventory"),
                        self.drain_ops.trace.index("swapoff_exact_mapper"))
        self.assertLess(self.drain_ops.trace.index("lower_dependencies"),
                        self.drain_ops.trace.index("loop_detach_normal"))
        self.assertLess(self.drain_ops.trace.index("loop_detach_normal"),
                        self.drain_ops.trace.index("loop_inventory"))
        self.assertTrue(self.owner.backing_must_be_preserved,
                        "mapper-only owner must not itself authorize backing release")

    def test_incomplete_role_inventories_never_reach_worker_or_drain_evidence(self):
        cases = ((), ("writer",), ("writer", "a", "b"),
                 ("writer", "a", "b", "a2"))
        for roles in cases:
            with self.subTest(roles=roles):
                case = self._new_case()
                case.broker.owner_create()
                for index, role in enumerate(roles):
                    case._request(f"partial-{index}", role)
                with self.assertRaises(FixtureOwnerDenied):
                    case.broker.finalize()
                self.assertFalse(case.broker.backing_release_authorized)
                self.assertNotIn("worker_report", case.drain_ops.trace)
                self.assertNotIn("swap_inventory", case.drain_ops.trace)
                self.assertNotIn("dm_remove_normal", case.mapper_ops.trace)

        case = self._new_case()
        case._start_workers(("writer", "a", "b"))
        with self.assertRaises(FixtureOwnerDenied):
            case._request("missing-a2-substituted-by-b2", "b2")
        self.assertEqual(case.broker._issued_roles, ["writer", "a", "b"])
        self.assertFalse(case.broker.backing_release_authorized)

    def test_duplicate_role_unknown_handle_and_role_result_mismatch_deny(self):
        case = self._new_case()
        case._start_workers(("writer",))
        with self.assertRaises(FixtureOwnerDenied):
            case._request("duplicated-role", "writer")
        self.assertNotIn("dm_remove_normal", case.mapper_ops.trace)

        case = self._new_case()
        case._start_workers(("writer",))
        case.launcher.fail.add("duplicate_handle")
        with self.assertRaises(FixtureOwnerDenied):
            case._request("duplicate-handle", "a")
        self.assertEqual(case.launcher.pending, [])
        self.assertFalse(case.broker.backing_release_authorized)

        case = self._new_case()
        case.broker.owner_create()
        with self.assertRaises(FixtureOwnerDenied):
            case._request("unexpected-role", "a")
        self.assertEqual(case.broker._issued_handles, [])
        self.assertFalse(case.broker.backing_release_authorized)

        case = self._new_case()
        case._start_workers()
        case.drain_ops.fail.add("role_result_failure")
        with self.assertRaises(FixtureOwnerDenied):
            case.broker.finalize()
        self.assertNotIn("swapoff_exact_mapper", case.drain_ops.trace)
        self.assertFalse(case.broker.backing_release_authorized)

    def test_ready_and_pidfd_ownership_are_required_before_role_ack(self):
        for failure in ("missing_ready", "launch_after_child", "release"):
            with self.subTest(failure=failure):
                case = self._new_case()
                case.broker.owner_create()
                case.launcher.fail.add(failure)
                with self.assertRaises(FixtureOwnerDenied):
                    case._request("failed-ready", "writer")
                self.assertFalse(case.broker.backing_release_authorized)
                self.assertEqual(case.launcher.pending, [])
                self.assertGreater(case.launcher.unconfirmed_stop_calls, 0)
                self.assertNotIn("swapoff_exact_mapper", case.drain_ops.trace)

    def test_unconfirmed_stop_failure_does_not_skip_registered_stop_attempt(self):
        case = self._new_case()
        case.broker.owner_create()
        case.launcher.fail.update({"launch_after_child", "stop_unconfirmed"})
        with self.assertRaises(FixtureOwnerDenied):
            case._request("lost-ready-and-stop-failed", "writer")
        self.assertEqual(case.launcher.unconfirmed_stop_calls, 1)
        self.assertEqual(case.stop_calls, [()],
                         "registered worker cleanup must still be attempted independently")
        self.assertFalse(case.broker.backing_release_authorized)
        self.assertNotIn("swapoff_exact_mapper", case.drain_ops.trace)
        # The mock has no real child; discard its bookkeeping after asserting
        # that the broker correctly refused to treat it as reaped.
        case.launcher.pending.clear()

    def test_launch_request_accounting_and_finalization_are_serialized(self):
        self.broker.owner_create()
        entered = threading.Event()
        release = threading.Event()

        def slow_launch(role, *, startup_timeout):
            self.assertGreater(startup_timeout, 0)
            self.assertEqual(self.broker.request_inflight, 1)
            entered.set()
            release.wait(timeout=1.0)
            handle = f"owned-{role}-slow"
            self.handles.append(handle)
            self.launcher.pending.append(handle)
            return WorkerLaunchReceipt(handle, role, True, True, True, True)

        self.launcher.launch = slow_launch
        result: list[object] = []
        def launch_and_capture():
            try:
                result.append(self._request("slow-request", "writer"))
            except Exception as exc:
                result.append(exc)
        thread = threading.Thread(
            target=launch_and_capture,
            daemon=True,
        )
        thread.start()
        self.assertTrue(entered.wait(timeout=1.0))
        self.assertEqual(self.broker.request_inflight, 1)
        with self.assertRaises(FixtureOwnerDenied):
            self.broker.finalize()
        release.set()
        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.broker.request_inflight, 0)
        self.assertFalse(self.broker.backing_release_authorized)
        self.assertEqual(self.launcher.pending, [])

    def test_real_unix_socket_uses_kernel_peer_credentials_and_one_connection(self):
        self.broker.owner_create()
        server, client = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        self.addCleanup(client.close)
        expected = owner_module.PeerCredentials(os.getpid(), os.geteuid(), os.getegid())
        outcomes: list[object] = []

        def serve():
            try:
                outcomes.append(self.broker.serve_worker_connection(server, expected))
            except Exception as exc:
                outcomes.append(exc)

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        for index, role in enumerate(("writer", "a", "b", "a2", "b2")):
            request = {"request_id": f"socket-{index}", "operation": "launch_role", "role": role}
            payload = json.dumps(request, separators=(",", ":")).encode()
            client.sendall(struct.pack("!I", len(payload)) + payload)
            header = self._recv_exact_socket(client, 4)
            size = struct.unpack("!I", header)[0]
            response = json.loads(self._recv_exact_socket(client, size))
            self.assertEqual(response["request_id"], request["request_id"])
        client.shutdown(socket.SHUT_WR)
        thread.join(timeout=4.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcomes, [5])
        self.assertEqual(self.broker.peer_credentials, expected)
        self.assertTrue(self.broker._peer_closed)
        self.assertTrue(self.broker.finalize())

    def test_unix_listener_binds_distinct_client_pid_from_so_peercred(self):
        self.broker.owner_create()
        path = str(self.root / "role-broker.sock")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        listener.bind(path)
        listener.listen(1)
        listener.settimeout(3.0)
        client_code = r'''
import json, socket, struct, sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect(sys.argv[1])
def exact(n):
    out = bytearray()
    while len(out) < n:
        part = s.recv(n - len(out))
        if not part:
            raise SystemExit(11)
        out.extend(part)
    return bytes(out)
for i, role in enumerate(("writer", "a", "b", "a2", "b2")):
    request = {"request_id": f"child-{i}", "operation": "launch_role", "role": role}
    payload = json.dumps(request, separators=(",", ":")).encode()
    s.sendall(struct.pack("!I", len(payload)) + payload)
    size = struct.unpack("!I", exact(4))[0]
    response = json.loads(exact(size))
    if response.get("request_id") != request["request_id"]:
        raise SystemExit(12)
s.shutdown(socket.SHUT_WR)
s.close()
'''
        child = subprocess.Popen(
            [sys.executable, "-c", client_code, path],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            close_fds=True,
        )
        connection, _ = listener.accept()
        expected = owner_module.PeerCredentials(child.pid, os.geteuid(), os.getegid())
        try:
            self.assertEqual(self.broker.serve_worker_connection(connection, expected), 5)
        finally:
            connection.close()
        stdout, stderr = child.communicate(timeout=4.0)
        self.assertEqual(child.returncode, 0, (stdout, stderr))
        self.assertEqual(self.broker.peer_credentials.pid, child.pid)
        self.assertNotEqual(self.broker.peer_credentials.pid, os.getpid())
        self.assertTrue(self.broker.finalize())

    def test_socket_rejects_wrong_peer_replacement_malformed_and_replay(self):
        for kind in ("wrong_pid", "wrong_uid", "wrong_gid", "replacement",
                     "malformed", "oversized", "early_eof", "replay"):
            with self.subTest(kind=kind):
                case = self._new_case()
                case.broker.owner_create()
                server, client = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
                expected = owner_module.PeerCredentials(os.getpid(), os.geteuid(), os.getegid())
                if kind in ("wrong_pid", "wrong_uid", "wrong_gid"):
                    pid = os.getpid() + 1 if kind == "wrong_pid" else os.getpid()
                    uid = os.geteuid() + 1 if kind == "wrong_uid" else os.geteuid()
                    gid = os.getegid() + 1 if kind == "wrong_gid" else os.getegid()
                    expected = owner_module.PeerCredentials(pid, uid, gid)
                    with self.assertRaises(FixtureOwnerDenied):
                        case.broker.serve_worker_connection(server, expected)
                elif kind in ("malformed", "oversized", "early_eof", "replay"):
                    def send_frame(value):
                        data = value if isinstance(value, bytes) else json.dumps(value).encode()
                        client.sendall(struct.pack("!I", len(data)) + data)
                    if kind == "malformed":
                        send_frame(b'{"request_id":"x","request_id":"x","operation":"launch_role","role":"writer"}')
                    elif kind == "oversized":
                        client.sendall(struct.pack("!I", owner_module._IPC_MAX_FRAME + 1))
                    elif kind == "early_eof":
                        client.shutdown(socket.SHUT_WR)
                    else:
                        req = {"request_id": "same", "operation": "launch_role", "role": "writer"}
                        send_frame(req)
                    outcome: list[object] = []
                    def serve_one():
                        try:
                            outcome.append(case.broker.serve_worker_connection(server, expected))
                        except Exception as exc:
                            outcome.append(exc)
                    thread = threading.Thread(target=serve_one, daemon=True)
                    thread.start()
                    if kind == "replay":
                        h = self._recv_exact_socket(client, 4)
                        self._recv_exact_socket(client, struct.unpack("!I", h)[0])
                        send_frame(req)
                    if kind != "early_eof":
                        client.shutdown(socket.SHUT_WR)
                    thread.join(timeout=4.0)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(len(outcome), 1)
                    self.assertIsInstance(outcome[0], FixtureOwnerDenied)
                else:
                    # A complete first connection claims the only session peer.
                    outcome = []
                    def serve_all():
                        try:
                            outcome.append(case.broker.serve_worker_connection(server, expected))
                        except Exception as exc:
                            outcome.append(exc)
                    thread = threading.Thread(target=serve_all, daemon=True)
                    thread.start()
                    for index, role in enumerate(("writer", "a", "b", "a2", "b2")):
                        req = {"request_id": f"first-{index}", "operation": "launch_role", "role": role}
                        data = json.dumps(req).encode()
                        client.sendall(struct.pack("!I", len(data)) + data)
                        h = self._recv_exact_socket(client, 4)
                        self._recv_exact_socket(client, struct.unpack("!I", h)[0])
                    client.shutdown(socket.SHUT_WR)
                    thread.join(timeout=4.0)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(outcome, [5])
                    other_server, other_client = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
                    with self.assertRaises(FixtureOwnerDenied):
                        case.broker.serve_worker_connection(other_server, expected)
                    other_server.close()
                    other_client.close()
                server.close()
                client.close()
                self.assertFalse(case.broker.backing_release_authorized)

    def test_partial_socket_frame_has_one_absolute_deadline(self):
        case = self._new_case()
        case.broker.owner_create()
        server, client = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        expected = owner_module.PeerCredentials(os.getpid(), os.geteuid(), os.getegid())
        original_timeout = owner_module._IPC_TIMEOUT_SECONDS
        owner_module._IPC_TIMEOUT_SECONDS = 0.05
        outcome: list[object] = []
        def serve_partial():
            try:
                outcome.append(case.broker.serve_worker_connection(server, expected))
            except Exception as exc:
                outcome.append(exc)
        thread = threading.Thread(target=serve_partial, daemon=True)
        try:
            thread.start()
            client.sendall(struct.pack("!I", 100) + b"{")
            thread.join(timeout=1.0)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(outcome), 1)
            self.assertIsInstance(outcome[0], FixtureOwnerDenied)
            self.assertFalse(case.broker.backing_release_authorized)
        finally:
            owner_module._IPC_TIMEOUT_SECONDS = original_timeout
            server.close()
            client.close()

    def test_layered_dm_model_releases_exact_upper_to_lower_stack_only(self):
        upper = owner_module.DMIdentity("upper", "UUID-UP", 253, 101, "1" * 64)
        lower = owner_module.DMIdentity("lower", "UUID-LOW", 253, 102, "2" * 64)
        model = owner_module.LayeredDMReleaseModel((upper, lower))
        seen = []

        def observe(identity):
            seen.append(identity.name)
            return owner_module.LayerObservation(
                identity, True, True, True, True, False, True, True, 0, (),
                True, True, False, False, True, True, True,
            )

        self.assertEqual(model.release_layers(observe), ("upper", "lower"))
        self.assertEqual(seen, ["upper", "lower"])
        self.assertTrue(model.mapper_dependencies_released)
        self.assertTrue(model.backing_must_be_preserved)
        oversized = tuple(
            owner_module.DMIdentity(f"layer-{index}", f"UUID-{index}", 253,
                                    index, f"{index:064x}")
            for index in range(owner_module._MAX_DM_LAYERS + 1)
        )
        with self.assertRaises(FixtureOwnerDenied):
            owner_module.LayeredDMReleaseModel(oversized)

    def test_layered_dm_model_denies_false_drain_holders_and_disappearance(self):
        identity = owner_module.DMIdentity("upper", "UUID-UP", 253, 101, "1" * 64)
        for change in ("drain", "holders", "remove", "absent"):
            with self.subTest(change=change):
                model = owner_module.LayeredDMReleaseModel((identity,))
                observation = owner_module.LayerObservation(
                    identity, True, True, True, True, False, True, True, 0, (),
                    True, True, False, False, True, True, True,
                )
                if change == "drain":
                    observation = dataclasses.replace(observation, pending_io_drained=False)
                elif change == "holders":
                    observation = dataclasses.replace(observation, holders=("holder",))
                elif change == "remove":
                    observation = dataclasses.replace(observation, force=True)
                else:
                    observation = dataclasses.replace(observation, exact_uuid_absent=False)
                with self.assertRaises(FixtureOwnerDenied):
                    model.release_layers(lambda _identity: observation)
                self.assertFalse(model.mapper_dependencies_released)
                self.assertTrue(model.backing_must_be_preserved)

    def test_optional_nbd_profile_requires_pidfd_identity_disconnect_and_absence(self):
        case = self._new_case()
        server = owner_module.NBDServerIdentity(
            case.lease.session_id, "nbd-server-owned", True, True,
            "/dev/nbd17", 43, 17,
        )
        release = owner_module.NBDReleaseModel(case.lease.session_id, server, "/dev/nbd17")
        case.broker = FixtureOwnerBroker(
            case.owner, case.drain_ops, case.LOOP,
            peer_authenticator=lambda peer: "worker" if peer is case.worker_peer else None,
            worker_launcher=case.launcher,
            session_profile=owner_module.FIXED_RECALL_NBD_PROFILE,
            nbd_release=release,
        )
        case.drain_ops.bind_owner(case.owner)
        case._start_workers()
        case.broker.finalize()
        self.assertTrue(release.nbd_released)
        self.assertEqual(release.events, ["nbd_disconnected", "nbd_absent"])
        self.assertLess(case.drain_ops.trace.index("nbd_disconnect_normal"),
                        case.drain_ops.trace.index("nbd_inventory"))
        self.assertLess(case.drain_ops.trace.index("nbd_inventory"),
                        case.drain_ops.trace.index("lower_dependencies"))

        bad_cases = (
            (owner_module.NBDDisconnectObservation(
                False, True, True, "server", True, True, True, "/dev/nbd17", 43, 17,
            ), owner_module.NBDInventoryObservation(
                True, False, "server", "/dev/nbd17", 43, 17, "9" * 64,
            )),
            (owner_module.NBDDisconnectObservation(
                True, True, True, "server", False, True, True, "/dev/nbd17", 43, 17,
            ), owner_module.NBDInventoryObservation(
                True, False, "server", "/dev/nbd17", 43, 17, "9" * 64,
            )),
            (owner_module.NBDDisconnectObservation(
                True, True, True, "server", True, True, True, "/dev/nbd17", 43, 17,
            ), owner_module.NBDInventoryObservation(
                True, True, "server", "/dev/nbd17", 43, 17, "9" * 64,
            )),
            (owner_module.NBDDisconnectObservation(
                True, True, True, "server", True, True, True, "/dev/nbd17", 44, 17,
            ), owner_module.NBDInventoryObservation(
                True, False, "server", "/dev/nbd17", 43, 17, "9" * 64,
            )),
        )
        for disconnect_result, inventory_result in bad_cases:
            model = owner_module.NBDReleaseModel(case.lease.session_id, server, "/dev/nbd17")
            with self.assertRaises(FixtureOwnerDenied):
                model.disconnect_and_verify(
                    lambda _server, _device, result=disconnect_result: result,
                    lambda _server, _device, result=inventory_result: result,
                )
            self.assertFalse(model.nbd_released)

        case = self._new_case()
        server = owner_module.NBDServerIdentity(
            case.lease.session_id, "nbd-server-owned", False, True,
            "/dev/nbd17", 43, 17,
        )
        with self.assertRaises(FixtureOwnerDenied):
            owner_module.NBDReleaseModel(case.lease.session_id, server, "/dev/nbd17")
        with self.assertRaises(FixtureOwnerDenied):
            owner_module.NBDReleaseModel("not-a-session", server, "/dev/nbd17")

    def test_real_pidfd_gated_workers_are_owned_before_ready_and_reaped(self):
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            self.skipTest("kernel/Python pidfd API is unavailable; no PID fallback is permitted")
        case = self._new_case()
        launcher = SyntheticPidfdWorkerLauncher(case.root)
        case.launcher = launcher
        case.handles = launcher.handles
        case.broker = FixtureOwnerBroker(
            case.owner, case.drain_ops, case.LOOP,
            peer_authenticator=lambda peer: "worker" if peer is case.worker_peer else None,
            worker_launcher=launcher,
        )
        self.addCleanup(launcher.close)
        case.broker.owner_create()
        handles = []
        for index, role in enumerate(("writer", "a", "b", "a2")):
            response = case._request(f"pidfd-{index}", role)
            handles.append(response["handle"])
        a2_output = launcher.children[handles[-1]]["output"]
        self.assertEqual(Path(a2_output).stat().st_size, 0,
                         "a2 must remain gated until its concurrent peer is READY")
        self.assertEqual(launcher.releases, [(handles[0],), (handles[1],), (handles[2],)])
        response = case._request("pidfd-4", "b2")
        handles.append(response["handle"])
        self.assertEqual(launcher.releases[-1], (handles[3], handles[4]))

        results = launcher.wait_for_all(tuple(handles))
        case.drain_ops.worker_results = results
        for role, handle, result in zip(case.broker.session_profile.expected_roles, handles, results):
            self.assertEqual((result.role, result.handle, result.exit_status), (role, handle, 0))
            self.assertTrue(result.reaped)
            self.assertTrue(result.descriptor_closed)
            self.assertEqual(Path(launcher.children[handle]["output"]).read_bytes(),
                             (role + "\n").encode())
            self.assertEqual(launcher.pidfd_close_counts[handle], 1)
            self.assertFalse(launcher.children[handle]["gate_open"])
        self.assertTrue(case.broker.finalize())
        self.assertTrue(case.broker.backing_release_authorized)

    def test_real_unconfirmed_children_are_aborted_and_reaped_without_ack(self):
        if not hasattr(os, "pidfd_open"):
            self.skipTest("pidfd_open is unavailable; acquisition failure remains fail-closed")
        for failure in ("pidfd", "lost_ready"):
            with self.subTest(failure=failure):
                case = self._new_case()
                launcher = SyntheticPidfdWorkerLauncher(case.root, fail=failure)
                case.launcher = launcher
                case.handles = launcher.handles
                case.broker = FixtureOwnerBroker(
                    case.owner, case.drain_ops, case.LOOP,
                    peer_authenticator=lambda peer: "worker" if peer is case.worker_peer else None,
                    worker_launcher=launcher,
                )
                self.addCleanup(launcher.close)
                case.broker.owner_create()
                with self.assertRaises(FixtureOwnerDenied):
                    case._request("unconfirmed", "writer")
                self.assertEqual(case.broker._issued_handles, [])
                self.assertFalse(case.broker.backing_release_authorized)
                self.assertEqual(case.drain_ops.trace, [])
                self.assertEqual(len(launcher.children), 1)
                record = next(iter(launcher.children.values()))
                self.assertTrue(record["reaped"], "launcher must reap the child that never received a handle")
                self.assertFalse(case.broker.backing_release_authorized)

    def test_abrupt_supervisor_exit_terminates_only_its_gated_test_child(self):
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            self.skipTest("pidfd APIs unavailable; no numeric-PID fallback is permitted")
        libc = ctypes.CDLL(None, use_errno=True)
        old_subreaper = ctypes.c_int(0)
        self.assertEqual(libc.prctl(37, ctypes.byref(old_subreaper), 0, 0, 0), 0)
        self.assertEqual(libc.prctl(36, 1, 0, 0, 0), 0)  # PR_SET_CHILD_SUBREAPER

        notify_r, notify_w = os.pipe2(os.O_CLOEXEC)
        crash_r, crash_w = os.pipe2(os.O_CLOEXEC)
        marker = self.root / "crash-worker.out"
        supervisor_pid = os.fork()
        if supervisor_pid == 0:
            try:
                os.close(notify_r)
                os.close(crash_w)
                gate_r, gate_w = os.pipe2(os.O_CLOEXEC)
                output_fd = os.open(
                    marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                    0o600,
                )
                proc = subprocess.Popen(
                    [sys.executable, "-c", SyntheticPidfdWorkerLauncher.CHILD_CODE,
                     str(gate_r), str(output_fd), "writer", "1", str(os.getpid())],
                    close_fds=True, pass_fds=(gate_r, output_fd),
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                os.close(gate_r)
                os.close(output_fd)
                worker_pidfd = os.pidfd_open(proc.pid, 0)
                os.write(notify_w, struct.pack("!i", proc.pid))
                os.write(gate_w, b"P")
                ready, _, _ = select.select((proc.stdout.fileno(),), (), (), 2.0)
                if not ready or os.read(proc.stdout.fileno(), 1) != b"R":
                    os._exit(96)
                os.write(gate_w, b"G")
                os.read(crash_r, 1)
                # Abruptly exit without stopping/reaping the active child.
                os._exit(0)
            except BaseException:
                os._exit(97)

        os.close(notify_w)
        os.close(crash_r)
        worker_pidfd = None
        worker_pid = None
        supervisor_pidfd = os.pidfd_open(supervisor_pid, 0)
        supervisor_reaped = False
        worker_reaped = False
        try:
            ready, _, _ = select.select((notify_r,), (), (), 4.0)
            self.assertTrue(ready, "test supervisor did not report its owned child")
            raw_pid = os.read(notify_r, 4)
            self.assertEqual(len(raw_pid), 4)
            worker_pid = struct.unpack("!i", raw_pid)[0]
            worker_pidfd = os.pidfd_open(worker_pid, 0)
            deadline = time.monotonic() + 2.0
            while (not marker.exists() or marker.stat().st_size == 0) and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertEqual(marker.read_bytes(), b"writer\n")
            os.write(crash_w, b"X")
            os.close(crash_w)
            crash_w = -1
            _, supervisor_status = os.waitpid(supervisor_pid, 0)
            supervisor_reaped = True
            self.assertEqual(os.waitstatus_to_exitcode(supervisor_status), 0)
            ready, _, _ = select.select((worker_pidfd,), (), (), 2.0)
            self.assertTrue(ready, "parent-death signal did not terminate direct worker")
            waited_pid, worker_status = os.waitpid(worker_pid, 0)
            self.assertEqual(waited_pid, worker_pid)
            self.assertTrue(os.WIFSIGNALED(worker_status))
            self.assertEqual(os.WTERMSIG(worker_status), signal.SIGTERM)
            worker_reaped = True
        finally:
            if crash_w >= 0:
                try:
                    os.write(crash_w, b"X")
                except OSError:
                    pass
                os.close(crash_w)
            if not supervisor_reaped:
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    try:
                        waited, _ = os.waitpid(supervisor_pid, os.WNOHANG)
                    except ChildProcessError:
                        waited = supervisor_pid
                    if waited == supervisor_pid:
                        supervisor_reaped = True
                        break
                    time.sleep(0.005)
                if not supervisor_reaped:
                    signal.pidfd_send_signal(supervisor_pidfd, signal.SIGTERM)
                    os.waitpid(supervisor_pid, 0)
                    supervisor_reaped = True
            if worker_pid is not None and not worker_reaped:
                # Once the owning supervisor is gone, confirm the direct child
                # exited from PDEATHSIG; otherwise terminate only via its pidfd.
                if worker_pidfd is not None:
                    ready, _, _ = select.select((worker_pidfd,), (), (), 1.0)
                    if not ready:
                        signal.pidfd_send_signal(worker_pidfd, signal.SIGTERM)
                        ready, _, _ = select.select((worker_pidfd,), (), (), 1.0)
                    if not ready:
                        signal.pidfd_send_signal(worker_pidfd, signal.SIGKILL)
                try:
                    os.waitpid(worker_pid, 0)
                    worker_reaped = True
                except ChildProcessError:
                    pass
            if worker_pidfd is not None:
                os.close(worker_pidfd)
            os.close(supervisor_pidfd)
            os.close(notify_r)
            # Restore the caller's prior subreaper setting.
            libc.prctl(36, old_subreaper.value, 0, 0, 0)

    def test_real_stopped_or_blocked_worker_uses_same_pidfd_for_cont_term(self):
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            self.skipTest("pidfd APIs unavailable; no numeric-PID fallback is permitted")
        case = self._new_case()
        launcher = SyntheticPidfdWorkerLauncher(case.root, hold_roles=("b2",))
        case.launcher = launcher
        case.handles = launcher.handles
        case.broker = FixtureOwnerBroker(
            case.owner, case.drain_ops, case.LOOP,
            peer_authenticator=lambda peer: "worker" if peer is case.worker_peer else None,
            worker_launcher=launcher,
        )
        self.addCleanup(launcher.close)
        handles = case._start_workers()
        held = launcher.children[handles[-1]]
        self.assertIsNone(held["proc"].poll())
        pidfd = held["pidfd"]
        report = launcher.stop_all(handles)
        self.assertTrue(report.all_reaped, report.errors)
        self.assertEqual(held["proc"].returncode, -signal.SIGTERM)
        self.assertEqual(
            [(sig, fd) for handle, sig, fd in launcher.signal_calls if handle == handles[-1]],
            [(signal.SIGCONT, pidfd), (signal.SIGTERM, pidfd)],
        )
        self.assertEqual(launcher.pidfd_close_counts[handles[-1]], 1)
        self.assertTrue(held["reaped"])

    def test_worker_ipc_cannot_supply_authority_identity_key_or_raw_commands(self):
        self.broker.owner_create()
        request = {"request_id": "r1", "operation": "launch_role", "role": "writer",
                   "key": b"attacker", "mapper": "/dev/dm-0", "argv": ["dd"]}
        with self.assertRaises(FixtureOwnerDenied):
            self.broker.worker_request(self.worker_peer, request)
        self.assertEqual(self.handles, [])
        self.assertEqual(self.mapper_ops.trace.count("dm_create"), 1,
                         "only trusted owner bootstrap may create the mapping")
        self.assertNotIn("dm_remove_normal", self.mapper_ops.trace)
        self.assertFalse(self.broker.backing_release_authorized)

    def test_worker_operations_cannot_mutate_mapper_or_mint_receipts(self):
        for operation in ("create", "reload", "rename", "suspend", "remove", "mint_receipt"):
            with self.subTest(operation=operation):
                case = self._new_case()
                case._start_workers(("writer",))
                with self.assertRaises(FixtureOwnerDenied):
                    case.broker.worker_request(case.worker_peer, {
                        "request_id": "bad-op", "operation": operation,
                        "role": "writer",
                    })
                self.assertFalse(case.broker.backing_release_authorized)
                self.assertNotIn("dm_remove_normal", case.mapper_ops.trace)
                with self.assertRaises(FixtureOwnerDenied):
                    case.broker.finalize()
                self.assertNotIn("dm_remove_normal", case.mapper_ops.trace)

    def test_reader_first_repeated_role_and_request_replay_latch_denial(self):
        self.broker.owner_create()
        with self.assertRaises(FixtureOwnerDenied):
            self._request("reader-first", "a")
        self.assertEqual(self.handles, [])

        case = self._new_case()
        case._start_workers(("writer",))
        with self.assertRaises(FixtureOwnerDenied):
            case._request("second-writer", "writer")
        self.assertEqual(len(case.handles), 1)

        case = self._new_case()
        case._start_workers(("writer",))
        with self.assertRaises(FixtureOwnerDenied):
            case._request("req-0", "a")
        self.assertFalse(case.broker.backing_release_authorized)

    def test_credential_ambiguity_owner_loss_and_control_eof_preserve(self):
        self.broker.owner_create()
        with self.assertRaises(FixtureOwnerDenied):
            self.broker.worker_request(object(), {
                "request_id": "bad-peer", "operation": "launch_role", "role": "writer",
            })
        self.assertFalse(self.broker.backing_release_authorized)

        case = self._new_case()
        case._start_workers(("writer",))
        with self.assertRaises(FixtureOwnerDenied):
            case.broker.owner_control_eof()
        self.assertFalse(case.broker.backing_release_authorized)
        self.assertEqual(case.broker.state, case.broker.DENIED)
        self.assertEqual(case.stop_calls, [tuple(case.handles)])

        case = self._new_case()
        case._start_workers(("writer",))
        with self.assertRaises(FixtureOwnerDenied):
            case.broker.producer_died()
        self.assertTrue(case.broker.backing_must_be_preserved)

    def test_worker_channel_eof_blocks_release(self):
        self._start_workers(("writer",))
        with self.assertRaises(FixtureOwnerDenied):
            self.broker.worker_control_eof(self.worker_peer)
        self.assertFalse(self.broker.backing_release_authorized)
        self.assertNotIn("dm_remove_normal", self.mapper_ops.trace)

    def test_incomplete_worker_inventory_or_bad_worker_mac_blocks_swapoff(self):
        for failure in ("worker_report", "worker_incomplete", "worker_bad_mac"):
            with self.subTest(failure=failure):
                case = self._new_case()
                case._start_workers()
                case.drain_ops.fail.add(failure)
                with self.assertRaises(FixtureOwnerDenied):
                    case.broker.finalize()
                self.assertNotIn("swapoff_exact_mapper", case.drain_ops.trace)
                self.assertNotIn("dm_suspend", case.mapper_ops.trace)
                self.assertFalse(case.broker.backing_release_authorized)

    def test_swap_inventory_and_swapoff_failures_preserve_mapper(self):
        for failure in ("swap_inventory", "swapoff"):
            with self.subTest(failure=failure):
                case = self._new_case()
                case._start_workers()
                case.drain_ops.fail.add(failure)
                with self.assertRaises(FixtureOwnerDenied):
                    case.broker.finalize()
                self.assertNotIn("dm_suspend", case.mapper_ops.trace)
                self.assertNotIn("dm_remove_normal", case.mapper_ops.trace)
                self.assertTrue(case.broker.backing_must_be_preserved)

    def test_false_drain_ack_skipped_holder_inventory_and_remove_failure_deny(self):
        failures = ("drain", "holders", "remove")
        for failure in failures:
            with self.subTest(failure=failure):
                case = self._new_case()
                case._start_workers()
                if failure == "drain":
                    case.mapper_ops.suspend_result = MapperSuspendObservation(
                        True, True, False, False, True, True, False,
                    )
                elif failure == "holders":
                    case.mapper_ops.fail.add("dm_openers")
                else:
                    case.mapper_ops.fail.add("dm_remove")
                with self.assertRaises(FixtureOwnerDenied):
                    case.broker.finalize()
                self.assertFalse(case.broker.backing_release_authorized)
                if failure != "remove":
                    self.assertNotIn("dm_remove_normal", case.mapper_ops.trace)

    def test_missing_lower_inventory_or_failed_detach_denies_after_mapper_release(self):
        for failure in ("lower_inventory", "loop_detach", "loop_inventory"):
            with self.subTest(failure=failure):
                case = self._new_case()
                case._start_workers()
                case.drain_ops.fail.add(failure)
                with self.assertRaises(FixtureOwnerDenied):
                    case.broker.finalize()
                self.assertTrue(case.broker.mapping_released)
                self.assertFalse(case.broker.backing_release_authorized)
                self.assertTrue(case.broker.backing_must_be_preserved)

    def test_changed_inventory_or_owner_loss_denies_before_removal(self):
        self._start_workers()
        self.mapper_ops.alive = False
        with self.assertRaises(FixtureOwnerDenied):
            self.broker.finalize()
        self.assertNotIn("dm_remove_normal", self.mapper_ops.trace)
        self.assertFalse(self.broker.backing_release_authorized)

    def test_mapper_identity_lock_and_inventory_changes_deny_next_role(self):
        changed = MapperIdentity(
            self.IDENTITY.name, "SWAPZ-OWNER-REPLACED", self.IDENTITY.major,
            self.IDENTITY.minor, "b" * 64,
        )
        self._start_workers(("writer",))
        self.owner.lease.identity_reader = lambda _fd, _name, _ops: changed
        with self.assertRaisesRegex(FixtureOwnerDenied, "fingerprint"):
            self._request("after-identity-change", "a")
        self.assertEqual(len(self.handles), 1)
        self.assertFalse(self.broker.backing_release_authorized)

        case = self._new_case()
        case._start_workers(("writer",))
        case.mapper_ops.entries = (case.IDENTITY, case.IDENTITY)
        with self.assertRaisesRegex(FixtureOwnerDenied, "duplicate mapper identities"):
            case._request("after-ambiguous-inventory", "a")
        self.assertEqual(len(case.handles), 1)

        case = self._new_case()
        case._start_workers(("writer",))
        case.lock_path.unlink()
        case.lock_path.write_text("replacement owner lock")
        case.lock_path.chmod(0o600)
        with self.assertRaises(FixtureOwnerDenied):
            case._request("after-lease-replacement", "a")
        self.assertEqual(len(case.handles), 1)
        self.assertFalse(case.broker.backing_release_authorized)

    def test_latched_denial_cannot_be_cleared_by_a_later_positive_fixture(self):
        self.broker.owner_create()
        with self.assertRaises(FixtureOwnerDenied):
            self.broker.worker_request(self.worker_peer, {
                "request_id": "bad", "operation": "remove", "role": "writer",
            })
        with self.assertRaises(FixtureOwnerDenied):
            self.broker.finalize()
        self.assertFalse(self.broker.backing_release_authorized)
        self.assertTrue(self.broker.backing_must_be_preserved)

    def test_invalid_roles_and_extra_handles_cannot_be_admitted(self):
        self.broker.owner_create()
        with self.assertRaises(FixtureOwnerDenied):
            self.broker.worker_request(self.worker_peer, {
                "request_id": "arbitrary", "operation": "launch_role", "role": "bash",
            })
        self.assertEqual(self.handles, [])
        self.assertFalse(self.broker.backing_release_authorized)

    def test_concurrent_lifecycle_request_denies_even_if_first_launch_returns(self):
        self.broker.owner_create()
        entered = threading.Event()
        release = threading.Event()
        launched: list[object] = []

        def slow_launch(role, *, startup_timeout):
            self.assertGreater(startup_timeout, 0)
            entered.set()
            release.wait(timeout=1.0)
            handle = f"owned-{role}-thread"
            self.handles.append(handle)
            self.launcher.pending.append(handle)
            return WorkerLaunchReceipt(handle, role, True, True, True, True)

        self.launcher.launch = slow_launch
        def launch_one():
            try:
                launched.append(self._request("one", "writer"))
            except Exception as exc:
                launched.append(exc)

        thread = threading.Thread(target=launch_one, daemon=True)
        thread.start()
        self.assertTrue(entered.wait(timeout=1.0))
        with self.assertRaises(FixtureOwnerDenied):
            self._request("two", "a")
        release.set()
        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive())
        self.assertFalse(self.broker.backing_release_authorized)
        self.assertEqual(self.stop_calls, [("owned-writer-thread",)])
        with self.assertRaises(FixtureOwnerDenied):
            self.broker.finalize()


if __name__ == "__main__":
    unittest.main(verbosity=2)
