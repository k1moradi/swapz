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

SUPERVISOR_SPEC = importlib.util.spec_from_file_location(
    "recall_fixture_test_supervisor", HERE / "test-child-supervisor.py",
)
if SUPERVISOR_SPEC is None or SUPERVISOR_SPEC.loader is None:
    raise RuntimeError("cannot load rootless pidfd supervisor")
supervisor_module = importlib.util.module_from_spec(SUPERVISOR_SPEC)
sys.modules[SUPERVISOR_SPEC.name] = supervisor_module
SUPERVISOR_SPEC.loader.exec_module(supervisor_module)

SERVICE_SPEC = importlib.util.spec_from_file_location(
    "recall_fixture_test_service", HERE / "test-child-supervisor-service.py",
)
if SERVICE_SPEC is None or SERVICE_SPEC.loader is None:
    raise RuntimeError("cannot load rootless pidfd supervisor service")
service_module = importlib.util.module_from_spec(SERVICE_SPEC)
sys.modules[SERVICE_SPEC.name] = service_module
SERVICE_SPEC.loader.exec_module(service_module)

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
WorkerContainmentResult = owner_module.WorkerContainmentResult
WorkerContainmentObservation = owner_module.WorkerContainmentObservation
_WORKER_CONTAINMENT_PROFILE = owner_module._WORKER_CONTAINMENT_PROFILE


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
        self.containment_calls: list[tuple[str, tuple[str, ...]]] = []
        self.service_instance_id = "c" * 32
        self.supervisor_id = "d" * 32
        self.stop_request_id = 100
        self.receipts: dict[str, WorkerLaunchReceipt] = {}
        self.reaped: set[str] = set()
        self.fail: set[str] = set()
        self._stop_attempted = False
        self._stop_report: WorkerStopReport | None = None

    def launch(self, role, *, session_id, startup_timeout):
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
            return WorkerLaunchReceipt(handle, role, False, True, True, True,
                                       _WORKER_CONTAINMENT_PROFILE)
        containment = ("direct-child-only" if "uncontained_launch" in self.fail
                       else _WORKER_CONTAINMENT_PROFILE)
        receipt = WorkerLaunchReceipt(
            handle, role, True, True, True, True, containment,
            2, session_id, self.service_instance_id, self.supervisor_id,
            f"{len(self.handles):032x}", containment,
        )
        self.receipts[handle] = receipt
        return receipt

    def registered_launch_receipts(self, handles):
        handles = tuple(handles)
        if handles != tuple(self.receipts):
            raise FixtureOwnerDenied("fake launcher receipt inventory mismatch")
        return tuple(self.receipts[handle] for handle in handles)

    def release_group(self, handles):
        if "release" in self.fail:
            raise OSError("injected gate release failure")
        if any(handle not in self.pending for handle in handles):
            raise AssertionError("only known gated handles can be released")
        if "partial_release" in self.fail and len(handles) > 1:
            first = handles[0]
            self.pending.remove(first)
            self.release_calls.append((first,))
            raise OSError("injected failure after first concurrent gate release")
        self.release_calls.append(tuple(handles))
        for handle in handles:
            self.pending.remove(handle)

    def stop_unconfirmed(self):
        self.unconfirmed_stop_calls += 1
        if "stop_unconfirmed" in self.fail:
            return WorkerStopReport(False, ("unconfirmed child remains",))
        self.reaped.update(self.pending)
        self.pending.clear()
        return WorkerStopReport(True, ())

    def stop_all(self, handles):
        handles = tuple(handles)
        if self._stop_attempted:
            return self._stop_report or WorkerStopReport(
                False, ("worker stop report is unavailable after an earlier attempt",),
            )
        self._stop_attempted = True
        self.stop_calls.append(handles)
        if "stop_all" in self.fail:
            self._stop_report = WorkerStopReport(False, ("worker remains",))
            return self._stop_report
        for handle in handles:
            if handle in self.pending:
                self.pending.remove(handle)
            self.reaped.add(handle)
        self._stop_report = WorkerStopReport(True, ())
        return self._stop_report

    def containment_observation(self, session_id, handles):
        handles = tuple(handles)
        self.containment_calls.append((session_id, handles))
        if "containment_missing" in self.fail:
            return None
        results = []
        for handle in handles:
            receipt = self.receipts[handle]
            results.append(WorkerContainmentResult(
                handle, f"domain-{handle}", receipt.containment_scope,
                True, True, True, (), (), 2, session_id,
                receipt.service_instance_id, receipt.supervisor_id,
                receipt.lifecycle_id, receipt.role, handle in self.reaped, 0,
                True, receipt.containment_profile,
            ))
        if "containment_direct_only" in self.fail and results:
            results[0] = dataclasses.replace(
                results[0], scope="direct-child-only", process_creation_denied=False,
            )
        if "containment_live_descendant" in self.fail and results:
            results[0] = dataclasses.replace(
                results[0], live_descendant_handles=("orphan-test-child",),
            )
        if "containment_duplicate" in self.fail and len(results) > 1:
            results[1] = dataclasses.replace(results[1], handle=results[0].handle)
        if "containment_duplicate_domain" in self.fail and len(results) > 1:
            results[1] = dataclasses.replace(results[1], domain_id=results[0].domain_id)
        if "containment_wrong_role" in self.fail and results:
            results[0] = dataclasses.replace(results[0], role="b")
        if "containment_stale_lifecycle" in self.fail and results:
            results[0] = dataclasses.replace(results[0], lifecycle_id="9" * 32)
        if "containment_foreign_service" in self.fail and results:
            results[0] = dataclasses.replace(results[0], service_instance_id="9" * 32)
        if "containment_boolean_exit_code" in self.fail and results:
            results[0] = dataclasses.replace(results[0], exit_code=False)
        if "containment_unknown" in self.fail and results:
            results[-1] = dataclasses.replace(results[-1], handle="unknown-handle")
        if "containment_incomplete" in self.fail and results:
            results.pop()
        return WorkerContainmentObservation(
            "f" * 32 if "containment_stale" in self.fail else session_id,
            handles, "containment_incomplete" not in self.fail,
            tuple(results),
            ("injected containment inspection failure",)
            if "containment_error" in self.fail else (),
            2, self.service_instance_id, self.supervisor_id, self.stop_request_id,
            False if "containment_boolean_service_exit" in self.fail else 0,
        )


class SyntheticPidfdWorkerLauncher:
    """Real, bounded test children; the only work is a regular-file marker."""

    CHILD_CODE = (
        "import os,signal,sys; gate=int(sys.argv[1]); out=int(sys.argv[2]); "
        "role=sys.argv[3]; hold=sys.argv[4]=='1'; "
        "first=os.read(gate,1); "
        "(os.write(1,b'R') if first==b'P' else os._exit(91)); "
        "second=os.read(gate,1); "
        "(os.write(out,(role+'\\n').encode()) if second==b'G' else os._exit(92)); "
        "os.close(out); "
        "(signal.pause() if hold else None); os.close(gate); os._exit(0)"
    )

    @staticmethod
    def _install_containment_before_exec(expected_parent_pid, parent_pidfd,
                                         diagnostic_fd=None):
        try:
            supervisor_module.LinuxPidfdOps().install_process_containment(
                expected_parent_pid, parent_pidfd,
            )
        except BaseException as exc:
            if diagnostic_fd is not None:
                os.write(diagnostic_fd, f"{type(exc).__name__}:{exc}".encode())
            raise
        finally:
            if diagnostic_fd is not None:
                os.close(diagnostic_fd)

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
        self.session_id: str | None = None
        self.service_instance_id = "e" * 32
        self.supervisor_id = "f" * 32
        self.stop_request_id = 200
        self.receipts: dict[str, WorkerLaunchReceipt] = {}

    def launch(self, role, *, session_id, startup_timeout):
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            raise OSError("pidfd APIs unavailable; refusing numeric-PID fallback")
        if not 0 < startup_timeout <= 10:
            raise AssertionError("startup handshake timeout must be bounded")
        if self.session_id is not None and self.session_id != session_id:
            raise FixtureOwnerDenied("synthetic supervisor session changed")
        self.session_id = session_id
        self._counter += 1
        handle = f"pidfd-owned-{role}-{self._counter}"
        lifecycle_id = f"{self._counter:032x}"
        output = self.output_dir / f"worker-{self._counter}.out"
        gate_r, gate_w = os.pipe2(os.O_CLOEXEC)
        output_fd = os.open(
            output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        proc = None
        record = {
            "role": role, "handle": handle, "output": output,
            "lifecycle_id": lifecycle_id,
            "pidfd": None, "gate_w": gate_w, "gate_open": True,
            "control_open": True,
            "proc": None, "reaped": False, "pidfd_closed": False,
            "containment_installed": False,
        }
        parent_pidfd = None
        try:
            expected_parent_pid = os.getpid()
            parent_pidfd = os.pidfd_open(expected_parent_pid, 0)
            proc = subprocess.Popen(
                [sys.executable, "-c", self.CHILD_CODE, str(gate_r), str(output_fd), role,
                 "1" if role in self.hold_roles else "0"],
                close_fds=True, pass_fds=(gate_r, output_fd, parent_pidfd),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                preexec_fn=lambda: self._install_containment_before_exec(
                    expected_parent_pid, parent_pidfd,
                ),
            )
            record["proc"] = proc
            # Register the created child before any fallible parent-side close
            # or pidfd acquisition. If READY is later lost, recovery still has
            # the exact Popen child and its closed start gate.
            self.children[handle] = record
            self.handles.append(handle)
            self.pending.add(handle)
            record["containment_installed"] = True
            # Popen returns only after the pre-exec containment hook and exec
            # succeed. The fixture gate stays shut until this parent owns the
            # child pidfd below.
            inherited_parent_pidfd = parent_pidfd
            parent_pidfd = None
            os.close(inherited_parent_pidfd)
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
            record["containment_installed"] = True
            receipt = WorkerLaunchReceipt(
                handle, role, True, True, True, True, _WORKER_CONTAINMENT_PROFILE,
                2, session_id, self.service_instance_id, self.supervisor_id,
                lifecycle_id, _WORKER_CONTAINMENT_PROFILE,
            )
            self.receipts[handle] = receipt
            return receipt
        except Exception:
            if proc is None:
                os.close(gate_w)
                record["gate_open"] = False
            raise
        finally:
            if parent_pidfd is not None:
                os.close(parent_pidfd)
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

    def registered_launch_receipts(self, handles):
        handles = tuple(handles)
        if handles != tuple(self.handles) or any(handle not in self.receipts for handle in handles):
            raise FixtureOwnerDenied("synthetic pidfd launch receipt inventory mismatch")
        return tuple(self.receipts[handle] for handle in handles)

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
                self.service_instance_id, self.supervisor_id,
                self.children[handle]["lifecycle_id"], True,
                _WORKER_CONTAINMENT_PROFILE, True,
            )
            for handle in handles
        )
        return self.worker_results

    def containment_observation(self, session_id, handles):
        handles = tuple(handles)
        workers = []
        errors = []
        for handle in handles:
            record = self.children.get(handle)
            if record is None:
                errors.append(f"unknown test worker handle: {handle}")
                continue
            installed = record["containment_installed"] is True
            reaped = record["reaped"] is True
            workers.append(WorkerContainmentResult(
                handle=handle,
                domain_id=f"domain-{handle}",
                scope=_WORKER_CONTAINMENT_PROFILE if installed else "direct-child-only",
                filter_installed_before_exec=installed,
                parent_death_bound=installed,
                process_creation_denied=installed,
                live_descendant_handles=(),
                errors=() if reaped and installed else ("worker domain is not closed",),
                protocol_version=2, session_id=session_id,
                service_instance_id=self.service_instance_id,
                supervisor_id=self.supervisor_id,
                lifecycle_id=record["lifecycle_id"], role=record["role"],
                direct_child_reaped=reaped,
                exit_code=record["proc"].returncode,
                containment_installed=installed,
                containment_profile=_WORKER_CONTAINMENT_PROFILE if installed else "",
            ))
        return WorkerContainmentObservation(
            session_id, handles, len(workers) == len(handles) and not errors,
            tuple(workers), tuple(errors), 2, self.service_instance_id,
            self.supervisor_id, self.stop_request_id, 0,
        )

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
        self.launcher = None
        self.swap_active = True
        self.loop_present = True
        self.nbd_present = True
        self.worker_results: tuple[WorkerRoleResult, ...] | None = None
        self.fail: set[str] = set()
        self.trace: list[str] = []

    def bind_owner(self, owner):
        self.owner = owner

    def bind_launcher(self, launcher):
        self.launcher = launcher

    def collect_worker_completion(self, handles):
        self.trace.append("worker_report")
        if "worker_report" in self.fail:
            return object()
        session = self.owner.lease.session_id
        stop = self.launcher.stop_all(handles)
        if type(stop) is not WorkerStopReport:
            return object()
        reaped = (handles if stop.all_reaped else handles[:-1])
        if "worker_incomplete" in self.fail:
            reaped = handles[:-1]
        roles = tuple(self.owner._worker_roles)
        role_results = (self.worker_results if self.worker_results is not None else tuple(
            WorkerRoleResult(
                role, handle, 0, handle in reaped, True,
                () if stop.all_reaped else ("worker stop failed",),
                self.launcher.service_instance_id, self.launcher.supervisor_id,
                self.launcher.receipts[handle].lifecycle_id, True,
                _WORKER_CONTAINMENT_PROFILE, True,
            )
            for role, handle in zip(roles, handles)
        ))
        if "role_result_failure" in self.fail and role_results:
            role_results = (WorkerRoleResult(roles[0], handles[0], 1, True, True, ("failed",)),) + role_results[1:]
        if "completion_wrong_service" in self.fail and role_results:
            role_results = (dataclasses.replace(
                role_results[0], service_instance_id="9" * 32,
            ),) + role_results[1:]
        if "completion_wrong_role" in self.fail and role_results:
            role_results = (dataclasses.replace(role_results[0], role="a"),) + role_results[1:]
        if "completion_stale_lifecycle" in self.fail and role_results:
            role_results = (dataclasses.replace(
                role_results[0], lifecycle_id="9" * 32,
            ),) + role_results[1:]
        if "completion_direct_only" in self.fail and role_results:
            role_results = (dataclasses.replace(
                role_results[0], containment_scope="direct-child-only",
                containment_installed=False,
            ),) + role_results[1:]
        evidence_session = "f" * 32 if "completion_stale_session" in self.fail else session
        evidence_service = (
            "9" * 32 if "completion_foreign_service" in self.fail
            else self.launcher.service_instance_id
        )
        evidence_protocol = 1 if "completion_old_protocol" in self.fail else 2
        provisional = WorkerCompletionEvidence(
            evidence_session, handles, reaped, handles, 0 if stop.all_reaped else 1,
            tuple(stop.errors), bytes(32), role_results, evidence_protocol,
            evidence_service, self.launcher.supervisor_id,
            self.launcher.stop_request_id,
        )
        authenticator = hmac.new(
            self.worker_key, worker_completion_payload(provisional), hashlib.sha256,
        ).digest()
        if "worker_bad_mac" in self.fail:
            authenticator = b"x" * 32
        return WorkerCompletionEvidence(
            evidence_session, handles, reaped, handles, 0 if stop.all_reaped else 1,
            tuple(stop.errors), authenticator, role_results, evidence_protocol,
            evidence_service, self.launcher.supervisor_id,
            self.launcher.stop_request_id,
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


class ActualServiceDrainOperations(FakeDrainOperations):
    """Use the real service/client rows; only mapper and drain ops are faked."""

    def collect_worker_completion(self, handles):
        handles = tuple(handles)
        self.trace.append("worker_report")
        session = self.owner.lease.session_id
        for handle in handles:
            response = self.launcher.wait(handle, 5.0)
            row = response.get("worker")
            if (response.get("status") != "reaped" or not isinstance(row, dict)
                    or row.get("handle") != handle or row.get("exit_code") != 0
                    or row.get("direct_child_reaped") is not True
                    or row.get("errors") != []):
                raise AssertionError(
                    f"actual service worker {handle} did not finish cleanly: "
                    f"status={response.get('status')!r}, row={row!r}"
                )
        stopped = self.launcher.stop_all(handles)
        if type(stopped) is not WorkerStopReport or stopped.all_reaped is not True or stopped.errors:
            return object()
        observation = self.launcher.containment_observation(session, handles)
        receipts = self.launcher.registered_launch_receipts(handles)
        roles = tuple(self.owner._worker_roles)
        role_results = tuple(
            WorkerRoleResult(
                row.role, row.handle, row.exit_code, row.direct_child_reaped,
                row.direct_child_reaped, tuple(row.errors),
                row.service_instance_id, row.supervisor_id, row.lifecycle_id,
                receipt.pidfd_owned, row.scope, row.containment_installed,
            )
            for row, receipt in zip(observation.workers, receipts)
        )
        if tuple(row.role for row in role_results) != roles:
            return object()
        provisional = WorkerCompletionEvidence(
            session, handles, handles, handles, observation.service_exit_status,
            tuple(observation.errors), bytes(32), role_results, 2,
            observation.service_instance_id, observation.supervisor_id,
            observation.stop_request_id,
        )
        authenticator = hmac.new(
            self.worker_key, worker_completion_payload(provisional), hashlib.sha256,
        ).digest()
        return WorkerCompletionEvidence(
            session, handles, handles, handles, observation.service_exit_status,
            tuple(observation.errors), authenticator, role_results, 2,
            observation.service_instance_id, observation.supervisor_id,
            observation.stop_request_id,
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
        self.drain_ops.bind_launcher(self.launcher)

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
        self.assertEqual(self.launcher.containment_calls,
                         [(self.lease.session_id, handles)])
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

    def test_actual_supervisor_service_containment_is_bound_to_broker_roles(self):
        """Exercise a real service, actual pidfds and pinned dd on regular files.

        Mapper, swap and drain operations remain synthetic. This verifies the
        evidence path from retained supervisor records through the v2 adapter
        into broker validation; it is not kernel DM or I/O-drain qualification.
        """
        dd_path = Path("/usr/bin/dd")
        if not dd_path.is_file():
            self.skipTest("fixed /usr/bin/dd test executable is unavailable")
        with tempfile.TemporaryDirectory(prefix="swapz-service-broker-") as temporary:
            base = Path(temporary)
            fixture = base / "fixture"
            fixture.mkdir(mode=0o700)
            fixture.chmod(0o700)
            expected = bytes(range(256)) * (9 * 4096 // 256)
            (fixture / "pages.bin").write_bytes(expected)
            (fixture / "pages.bin").chmod(0o600)
            mapper_path = base / "synthetic-mapper.bin"
            mapper_path.write_bytes(bytes(len(expected)))
            mapper_path.chmod(0o600)
            mapper_fd = os.open(mapper_path, os.O_RDWR | os.O_CLOEXEC)
            parent_sock, child_sock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            session_id = self.lease.session_id
            bootstrap = r'''
import importlib.util, os, socket, stat, sys
from pathlib import Path
runtime, fixture, mapper_name, mapper_fd_text, socket_fd_text, session = sys.argv[1:]
sys.path.insert(0, runtime)
def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(runtime) / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
service_module = load("integrated_service", "test-child-supervisor-service.py")
policy = service_module._ALLOWLIST_MODULE
expected_name = mapper_name
mapper_fd = int(mapper_fd_text)
os.set_inheritable(mapper_fd, False)
def verify_mapper(fd, name, ops):
    info = ops.fstat(fd)
    return (name == expected_name and stat.S_ISREG(info.st_mode)
            and info.st_size == 9 * 4096)
gate = policy.RecallDDLaunchGate(
    Path(fixture), mapper_name, mapper_fd=mapper_fd,
    executable_path=Path("/usr/bin/dd"), mapper_verifier=verify_mapper,
)
control = socket.socket(fileno=int(socket_fd_text))
outcome = service_module.SupervisorControlService(
    io_timeout=8.0, recall_dd_gate=gate, enable_direct_dd=True,
    session_id=session,
).serve(control)
control.close()
raise SystemExit(outcome.exit_code)
'''
            process = None
            client = None
            try:
                process = subprocess.Popen(
                    [sys.executable, "-c", bootstrap, str(HERE), str(fixture),
                     "swapz-v22-recall-integration", str(mapper_fd),
                     str(child_sock.fileno()), session_id],
                    pass_fds=(mapper_fd, child_sock.fileno()), close_fds=True,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=None,
                )
                child_sock.close()
                client = service_module.SupervisorControlClient(
                    parent_sock, service_process=process, timeout=20.0,
                )
                launcher = owner_module.SupervisorServiceWorkerLauncher(client, session_id)
                drain = ActualServiceDrainOperations(
                    self.IDENTITY, self.WORKER_KEY, self.LOOP,
                )
                drain.bind_owner(self.owner)
                drain.bind_launcher(launcher)
                self.drain_ops = drain
                self.launcher = launcher
                self.handles = []
                self.broker = FixtureOwnerBroker(
                    self.owner, drain, self.LOOP,
                    peer_authenticator=lambda peer: "worker" if peer is self.worker_peer else None,
                    worker_launcher=launcher,
                )
                self.broker.owner_create()
                handles = tuple(
                    self._request(f"service-{index}", role)["handle"]
                    for index, role in enumerate(("writer", "a", "b", "a2", "b2"))
                )
                self.assertTrue(self.broker.finalize())
                self.assertTrue(client.cleanup_authorized)
                self.assertEqual(mapper_path.read_bytes(), expected)
                for role, page in (("a", 0), ("b", 4), ("a2", 0), ("b2", 5)):
                    self.assertEqual(
                        (fixture / f"read-{role}").read_bytes(),
                        expected[page * 4096:(page + 1) * 4096],
                    )
                self.assertEqual(len(launcher.registered_launch_receipts(handles)), 5)
                snapshot = launcher.containment_observation(session_id, handles)
                self.assertEqual(tuple(row.handle for row in snapshot.workers), handles)
                self.assertTrue(all(row.direct_child_reaped and row.containment_installed
                                    and row.scope == _WORKER_CONTAINMENT_PROFILE
                                    for row in snapshot.workers))
                self.assertEqual(tuple(row.role for row in snapshot.workers),
                                 ("writer", "a", "b", "a2", "b2"))
                self.assertEqual(process.wait(timeout=1.0), 0)
            finally:
                if process is not None and process.poll() is None:
                    try:
                        parent_sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    try:
                        process.wait(timeout=8.0)
                    except subprocess.TimeoutExpired:
                        # This is the exact service process created above; its
                        # own parent-death binding terminates any live worker.
                        process.kill()
                        process.wait(timeout=2.0)
                if client is not None:
                    try:
                        client.close()
                    except Exception:
                        pass
                else:
                    parent_sock.close()
                if child_sock.fileno() >= 0:
                    child_sock.close()
                os.close(mapper_fd)

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
        for failure in ("missing_ready", "uncontained_launch", "launch_after_child", "release"):
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

    def test_direct_child_completion_never_substitutes_for_tree_containment(self):
        failures = (
            "containment_missing", "containment_direct_only", "containment_live_descendant",
            "containment_incomplete", "containment_duplicate", "containment_unknown",
            "containment_duplicate_domain", "containment_wrong_role",
            "containment_stale_lifecycle", "containment_foreign_service",
            "containment_boolean_exit_code", "containment_boolean_service_exit",
            "containment_stale", "containment_error",
        )
        for failure in failures:
            with self.subTest(failure=failure):
                case = self._new_case()
                handles = case._start_workers()
                case.launcher.fail.add(failure)
                with self.assertRaises(FixtureOwnerDenied):
                    case.broker.finalize()
                self.assertEqual(case.owner.registered_worker_handles, handles)
                self.assertIn("worker_attestation", case.mapper_ops.trace,
                              "the direct-child report should be valid before the separate check")
                self.assertEqual(case.launcher.containment_calls,
                                 [(case.lease.session_id, handles)])
                self.assertFalse(case.broker.backing_release_authorized)
                self.assertTrue(case.broker.backing_must_be_preserved)
                self.assertNotIn("swap_inventory", case.drain_ops.trace)
                self.assertNotIn("swapoff_exact_mapper", case.drain_ops.trace)
                self.assertNotIn("dm_suspend", case.mapper_ops.trace)
                self.assertNotIn("dm_remove_normal", case.mapper_ops.trace)

    def test_completion_rows_must_match_the_same_supervisor_launch_receipts(self):
        failures = (
            "completion_wrong_service", "completion_wrong_role",
            "completion_stale_lifecycle", "completion_direct_only",
            "completion_stale_session", "completion_old_protocol",
        )
        for failure in failures:
            with self.subTest(failure=failure):
                case = self._new_case()
                case._start_workers()
                case.drain_ops.fail.add(failure)
                with self.assertRaises(FixtureOwnerDenied):
                    case.broker.finalize()
                self.assertEqual(case.broker.state, case.broker.DENIED)
                self.assertFalse(case.broker.backing_release_authorized)
                self.assertTrue(case.broker.backing_must_be_preserved)
                self.assertNotIn("swap_inventory", case.drain_ops.trace)
                self.assertNotIn("swapoff_exact_mapper", case.drain_ops.trace)
                self.assertNotIn("dm_suspend", case.mapper_ops.trace)
                self.assertNotIn("dm_remove_normal", case.mapper_ops.trace)

    def test_concurrent_denial_during_containment_collection_prevents_swapoff(self):
        case = self._new_case()
        case._start_workers()
        collecting = threading.Event()
        resume = threading.Event()
        original = case.launcher.containment_observation

        def blocked_containment(session_id, handles):
            collecting.set()
            if not resume.wait(timeout=3.0):
                raise TimeoutError("containment evidence barrier was not released")
            return original(session_id, handles)

        case.launcher.containment_observation = blocked_containment
        outcomes: list[object] = []

        def finalize():
            try:
                outcomes.append(case.broker.finalize())
            except Exception as exc:
                outcomes.append(exc)

        thread = threading.Thread(target=finalize, daemon=True)
        thread.start()
        self.assertTrue(collecting.wait(timeout=2.0))
        with self.assertRaises(FixtureOwnerDenied):
            case.broker.producer_died()
        self.assertFalse(case.broker.backing_release_authorized)
        resume.set()
        thread.join(timeout=4.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(outcomes), 1)
        self.assertIsInstance(outcomes[0], FixtureOwnerDenied)
        self.assertEqual(case.broker.state, case.broker.DENIED)
        self.assertFalse(case.broker.backing_release_authorized)
        self.assertNotIn("swap_inventory", case.drain_ops.trace)
        self.assertNotIn("swapoff_exact_mapper", case.drain_ops.trace)
        self.assertNotIn("dm_suspend", case.mapper_ops.trace)
        self.assertNotIn("dm_remove_normal", case.mapper_ops.trace)
        self.assertEqual(case.stop_calls, [tuple(case.handles)])

    def test_containment_observation_must_cover_all_five_live_worker_domains(self):
        case = self._new_case()
        handles = case._start_workers()
        observation = case.launcher.containment_observation(case.lease.session_id, handles)
        self.assertEqual(observation.expected_handles, handles)
        self.assertTrue(observation.inventory_complete)
        self.assertEqual(tuple(item.handle for item in observation.workers), handles)
        self.assertTrue(all(item.process_creation_denied and item.parent_death_bound
                            and item.filter_installed_before_exec
                            and item.live_descendant_handles == () and not item.errors
                            for item in observation.workers))
        self.assertTrue(case.broker.finalize())
        self.assertTrue(case.broker.backing_release_authorized,
                        "this is a rootless model result, not real backing release authority")

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

        def slow_launch(role, *, session_id, startup_timeout):
            self.assertGreater(startup_timeout, 0)
            self.assertEqual(self.broker.request_inflight, 1)
            entered.set()
            release.wait(timeout=1.0)
            handle = f"owned-{role}-slow"
            self.handles.append(handle)
            self.launcher.pending.append(handle)
            receipt = WorkerLaunchReceipt(
                handle, role, True, True, True, True, _WORKER_CONTAINMENT_PROFILE,
                2, session_id, self.launcher.service_instance_id,
                self.launcher.supervisor_id, "1" * 32, _WORKER_CONTAINMENT_PROFILE,
            )
            self.launcher.receipts[handle] = receipt
            return receipt

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
        case.drain_ops.bind_launcher(launcher)
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
                case.drain_ops.bind_launcher(launcher)
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
                expected_parent_pid = os.getpid()
                parent_pidfd = os.pidfd_open(expected_parent_pid, 0)
                proc = subprocess.Popen(
                    [sys.executable, "-c", SyntheticPidfdWorkerLauncher.CHILD_CODE,
                     str(gate_r), str(output_fd), "writer", "1"],
                    close_fds=True, pass_fds=(gate_r, output_fd, parent_pidfd, notify_w),
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    preexec_fn=lambda: SyntheticPidfdWorkerLauncher._install_containment_before_exec(
                        expected_parent_pid, parent_pidfd, notify_w,
                    ),
                )
                os.close(parent_pidfd)
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
            except BaseException as exc:
                try:
                    os.write(notify_w, b"ERR:" + repr(exc).encode("utf-8", "replace"))
                except BaseException:
                    pass
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
            raw_pid = os.read(notify_r, 4096)
            self.assertFalse(raw_pid.startswith(b"ERR:"), raw_pid.decode("utf-8", "replace"))
            self.assertEqual(len(raw_pid), 4, raw_pid.decode("utf-8", "replace"))
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
            self.assertEqual(os.WTERMSIG(worker_status), signal.SIGKILL)
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
        case.drain_ops.bind_launcher(launcher)
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

        def slow_launch(role, *, session_id, startup_timeout):
            self.assertGreater(startup_timeout, 0)
            entered.set()
            release.wait(timeout=1.0)
            handle = f"owned-{role}-thread"
            self.handles.append(handle)
            self.launcher.pending.append(handle)
            receipt = WorkerLaunchReceipt(
                handle, role, True, True, True, True, _WORKER_CONTAINMENT_PROFILE,
                2, session_id, self.launcher.service_instance_id,
                self.launcher.supervisor_id, "2" * 32, _WORKER_CONTAINMENT_PROFILE,
            )
            self.launcher.receipts[handle] = receipt
            return receipt

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
        self.assertEqual(len(launched), 1)
        self.assertIsInstance(launched[0], FixtureOwnerDenied,
                              "the in-flight launch must not receive a success acknowledgment")
        self.assertFalse(self.broker.backing_release_authorized)
        self.assertEqual(self.stop_calls, [("owned-writer-thread",)])
        self.assertEqual(self.broker.state, self.broker.DENIED)
        self.assertEqual(self.broker._issued_roles, ["writer"])
        self.assertEqual(self.owner._worker_roles, [],
                         "denial before registration cannot authorize a mapper role")
        self.assertEqual(self.launcher.release_calls, [],
                         "the role gate must not be released after the concurrent denial")
        self.assertNotIn("worker_report", self.drain_ops.trace)
        with self.assertRaises(FixtureOwnerDenied):
            self.broker.finalize()

    def test_denial_during_worker_evidence_collection_aborts_before_swap_or_dm(self):
        for denial_method in ("owner_control_eof", "producer_died"):
            with self.subTest(denial_method=denial_method):
                case = self._new_case()
                handles = case._start_workers()
                collecting = threading.Event()
                continue_collection = threading.Event()
                original = case.drain_ops.collect_worker_completion

                def blocked_collection(worker_handles):
                    collecting.set()
                    if not continue_collection.wait(timeout=3.0):
                        raise TimeoutError("test barrier did not release worker evidence collection")
                    return original(worker_handles)

                case.drain_ops.collect_worker_completion = blocked_collection
                outcomes: list[object] = []

                def finalize():
                    try:
                        outcomes.append(case.broker.finalize())
                    except Exception as exc:
                        outcomes.append(exc)

                thread = threading.Thread(target=finalize, daemon=True)
                thread.start()
                self.assertTrue(collecting.wait(timeout=2.0), "finalizer did not reach evidence barrier")
                with self.assertRaises(FixtureOwnerDenied):
                    getattr(case.broker, denial_method)()
                self.assertEqual(case.broker.state, case.broker.DENIED)
                self.assertFalse(case.broker.backing_release_authorized)
                self.assertEqual(case.stop_calls, [],
                                 "worker stop must wait until the active collector unwinds")
                continue_collection.set()
                thread.join(timeout=4.0)
                self.assertFalse(thread.is_alive(), "finalizer did not stop at next checkpoint")
                self.assertEqual(len(outcomes), 1)
                self.assertIsInstance(outcomes[0], FixtureOwnerDenied)
                self.assertEqual(case.broker.state, case.broker.DENIED)
                self.assertFalse(case.broker.backing_release_authorized)
                self.assertEqual(case.stop_calls, [handles])
                self.assertIn("worker_report", case.drain_ops.trace)
                self.assertNotIn("swap_inventory", case.drain_ops.trace)
                self.assertNotIn("swapoff_exact_mapper", case.drain_ops.trace)
                self.assertNotIn("dm_suspend", case.mapper_ops.trace)
                self.assertNotIn("dm_remove_normal", case.mapper_ops.trace)
                self.assertNotIn("lower_dependencies", case.drain_ops.trace)
                self.assertNotIn("loop_detach_normal", case.drain_ops.trace)

    def test_denial_at_each_teardown_checkpoint_prevents_the_next_operation(self):
        cases = (
            ("dm_suspend", "dm_suspend", "dm_remove_normal"),
            ("dm_remove", "dm_remove_normal", "lower_dependencies"),
            ("lower_dependencies", "lower_dependencies", "loop_detach_normal"),
            ("loop_detach", "loop_detach_normal", "loop_inventory"),
        )
        for checkpoint_name, forbidden_operation, later_operation in cases:
            with self.subTest(checkpoint=checkpoint_name):
                case = self._new_case()
                case._start_workers()
                reached = threading.Event()
                resume = threading.Event()
                original = case.broker._begin_operation

                def pause_before(name):
                    if name == checkpoint_name:
                        reached.set()
                        if not resume.wait(timeout=3.0):
                            raise TimeoutError(f"test barrier for {name} was not released")
                    return original(name)

                case.broker._begin_operation = pause_before
                outcomes: list[object] = []

                def finalize():
                    try:
                        outcomes.append(case.broker.finalize())
                    except Exception as exc:
                        outcomes.append(exc)

                thread = threading.Thread(target=finalize, daemon=True)
                thread.start()
                self.assertTrue(reached.wait(timeout=3.0),
                                f"finalizer did not reach {checkpoint_name} checkpoint")
                with self.assertRaises(FixtureOwnerDenied):
                    case.broker.owner_control_eof()
                self.assertEqual(case.broker.state, case.broker.DENIED)
                self.assertFalse(case.broker.backing_release_authorized)
                resume.set()
                thread.join(timeout=4.0)
                self.assertFalse(thread.is_alive())
                self.assertEqual(len(outcomes), 1)
                self.assertIsInstance(outcomes[0], FixtureOwnerDenied)
                self.assertNotIn(forbidden_operation,
                                 case.mapper_ops.trace + case.drain_ops.trace)
                self.assertNotIn(later_operation,
                                 case.mapper_ops.trace + case.drain_ops.trace)
                self.assertFalse(case.broker.backing_release_authorized)
                self.assertEqual(case.broker.state, case.broker.DENIED)
                self.assertEqual(case.stop_calls, [tuple(case.handles)])

    def test_partial_a2_b2_gate_release_denies_and_reaps_the_entire_inventory(self):
        case = self._new_case()
        prior = case._start_workers(("writer", "a", "b", "a2"))
        case.launcher.fail.add("partial_release")
        with self.assertRaises(FixtureOwnerDenied):
            case._request("partial-pair-release", "b2")
        all_handles = tuple(case.handles)
        self.assertEqual(len(all_handles), 5)
        self.assertEqual(case.launcher.release_calls[-1], (prior[-1],),
                         "the mock must model exactly one gate released before failure")
        self.assertEqual(case.stop_calls, [all_handles])
        self.assertEqual(case.launcher.pending, [])
        self.assertEqual(case.broker.state, case.broker.DENIED)
        self.assertFalse(case.broker.backing_release_authorized)
        self.assertNotIn("worker_report", case.drain_ops.trace)
        self.assertNotIn("dm_remove_normal", case.mapper_ops.trace)

    def test_unconfirmed_stop_failure_still_attempts_registered_workers(self):
        case = self._new_case()
        registered = case._start_workers(("writer",))
        case.launcher.fail.update({"launch_after_child", "stop_unconfirmed"})
        with self.assertRaises(FixtureOwnerDenied):
            case._request("ambiguous-second-child", "a")
        self.assertEqual(case.launcher.unconfirmed_stop_calls, 1)
        self.assertEqual(case.stop_calls, [registered],
                         "registered children need their own stop_all pass after ambiguous spawn")
        self.assertEqual(case.owner._worker_roles, ["writer"])
        self.assertEqual(case.launcher.pending, [case.handles[-1]],
                         "failed unconfirmed cleanup must remain visibly unresolved")
        self.assertEqual(case.broker.state, case.broker.DENIED)
        self.assertFalse(case.broker.backing_release_authorized)
        self.assertNotIn("swapoff_exact_mapper", case.drain_ops.trace)
        case.launcher.pending.clear()

    def test_worker_stop_failure_after_concurrent_denial_remains_sticky(self):
        case = self._new_case()
        handles = case._start_workers()
        collecting = threading.Event()
        resume = threading.Event()
        original = case.drain_ops.collect_worker_completion

        def blocked_collection(worker_handles):
            collecting.set()
            if not resume.wait(timeout=3.0):
                raise TimeoutError("worker evidence barrier was not released")
            return original(worker_handles)

        case.drain_ops.collect_worker_completion = blocked_collection
        case.launcher.fail.add("stop_all")
        outcomes: list[object] = []

        def finalize():
            try:
                outcomes.append(case.broker.finalize())
            except Exception as exc:
                outcomes.append(exc)

        thread = threading.Thread(target=finalize, daemon=True)
        thread.start()
        self.assertTrue(collecting.wait(timeout=2.0))
        with self.assertRaises(FixtureOwnerDenied):
            case.broker.producer_died()
        self.assertEqual(case.stop_calls, [], "no stop callback may race collection")
        resume.set()
        thread.join(timeout=4.0)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(outcomes[0], FixtureOwnerDenied)
        self.assertEqual(case.stop_calls, [handles])
        self.assertIn("registered worker inventory was not reaped cleanly",
                      case.broker.denial)
        self.assertEqual(case.broker.state, case.broker.DENIED)
        self.assertFalse(case.broker.backing_release_authorized)
        self.assertNotIn("swap_inventory", case.drain_ops.trace)
        self.assertNotIn("dm_remove_normal", case.mapper_ops.trace)

    def test_denial_after_last_checkpoint_wins_against_atomic_release_commit(self):
        case = self._new_case()
        case._start_workers()
        at_commit = threading.Event()
        resume = threading.Event()
        original = case.broker._begin_operation

        def pause_after_commit_checkpoint(name):
            result = original(name)
            if name == "finalization_commit":
                at_commit.set()
                if not resume.wait(timeout=3.0):
                    raise TimeoutError("release-commit barrier was not released")
            return result

        case.broker._begin_operation = pause_after_commit_checkpoint
        outcomes: list[object] = []

        def finalize():
            try:
                outcomes.append(case.broker.finalize())
            except Exception as exc:
                outcomes.append(exc)

        thread = threading.Thread(target=finalize, daemon=True)
        thread.start()
        self.assertTrue(at_commit.wait(timeout=3.0), "finalizer did not reach release commit")
        with self.assertRaises(FixtureOwnerDenied):
            case.broker.producer_died()
        resume.set()
        thread.join(timeout=4.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(outcomes), 1)
        self.assertIsInstance(outcomes[0], FixtureOwnerDenied)
        self.assertEqual(case.broker.state, case.broker.DENIED)
        self.assertFalse(case.broker.backing_release_authorized)
        self.assertTrue(case.broker.backing_must_be_preserved)
        self.assertTrue(case.broker.mapping_released,
                        "earlier synthetic mapper operations cannot be rolled back")

    def test_repeated_finalization_is_terminal_and_never_reverses_outcome(self):
        self._start_workers()
        trace_before = tuple(self.drain_ops.trace)
        self.assertTrue(self.broker.finalize())
        completed_trace = tuple(self.drain_ops.trace)
        with self.assertRaises(FixtureOwnerDenied):
            self.broker.finalize()
        self.assertGreater(len(completed_trace), len(trace_before))
        self.assertEqual(tuple(self.drain_ops.trace), completed_trace)
        self.assertEqual(self.broker.state, self.broker.RELEASED)
        self.assertTrue(self.broker.backing_release_authorized)

        case = self._new_case()
        case.broker.owner_create()
        with self.assertRaises(FixtureOwnerDenied):
            case._request("invalid-before-denied-finalize", "a")
        denial = case.broker.denial
        stop_calls = tuple(case.stop_calls)
        with self.assertRaises(FixtureOwnerDenied):
            case.broker.finalize()
        self.assertEqual(case.broker.denial, denial)
        self.assertEqual(tuple(case.stop_calls), stop_calls)
        self.assertEqual(case.broker.state, case.broker.DENIED)
        self.assertFalse(case.broker.backing_release_authorized)


if __name__ == "__main__":
    unittest.main(verbosity=2)
