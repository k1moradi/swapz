#!/usr/bin/env python3
"""Rootless fixture-owner broker and drain-evidence producer model.

This module executes no privileged operations itself. ``DrainOperations`` and
the existing ``MapperLifecycleOwner`` are injected by a future separately
controlled fixture process; tests use an in-memory fake. The producer owns a
fresh session HMAC key and does not expose evidence-minting or key APIs to the
worker request interface. This Python boundary is a policy model, not an OS
credential boundary against another local process or host root.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import secrets
import sys
import threading
from typing import Any


HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_ALLOWLIST = _load("swapz_fixture_owner_allowlist", HERE / "recall-dd-allowlist.py")
_RELEASE = _load("swapz_fixture_owner_release_policy", HERE / "recall-fixture-release-policy.py")
MapperLifecycleOwner = _ALLOWLIST.MapperLifecycleOwner
MapperOwnerDenied = _ALLOWLIST.MapperOwnerDenied
MapperReleaseReport = _ALLOWLIST.MapperReleaseReport
MapperRemovalObservation = _ALLOWLIST.MapperRemovalObservation
MapperIdentity = _ALLOWLIST.MapperIdentity
WorkerCompletionEvidence = _ALLOWLIST.WorkerCompletionEvidence
worker_completion_payload = _ALLOWLIST.worker_completion_payload
DMIdentity = _RELEASE.DMIdentity
AuthenticatedDrainEvidence = _RELEASE.AuthenticatedDrainEvidence
FixtureBackingReleasePolicy = _RELEASE.FixtureBackingReleasePolicy
evidence_mac = _RELEASE.evidence_mac


class FixtureOwnerDenied(RuntimeError):
    """Fixture lifecycle or backing release cannot be positively established."""


_ROLES = ("writer", "a", "b", "a2", "b2")
_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_HANDLE = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class AdmissionGateObservation:
    session_id: str
    broker_state: str
    closed: bool
    request_inflight: int
    registered_handles: tuple[str, ...]


@dataclass(frozen=True)
class SwapInventoryObservation:
    valid: bool
    mapper_active: bool
    mapper_identity: MapperIdentity | None
    inventory_sha256: str


@dataclass(frozen=True)
class SwapoffObservation:
    attempted: bool
    succeeded: bool
    identity_matches: bool


@dataclass(frozen=True)
class LowerDependencyObservation:
    inventory_valid: bool
    dm_stack_absent: bool
    holders: tuple[str, ...]
    loop_identity_matches: bool
    dm_names_absent: tuple[str, ...]
    inventory_sha256: str


@dataclass(frozen=True)
class LoopDetachObservation:
    succeeded: bool
    normal_detach: bool
    identity_matches: bool


@dataclass(frozen=True)
class LoopInventoryObservation:
    valid: bool
    exact_loop_present: bool
    inventory_sha256: str


class FixtureDrainEvidenceProducer:
    """Collect typed operation results and validate a private signed sequence.

    The injected operations return observations, not booleans supplied by a
    controller. The key is generated here and is never returned. Envelopes are
    submitted only to the in-process validator; workers cannot call ``emit``
    or ``submit``. A positive property is an authorization result only for a
    future reviewed owner, not a command to unlink backing storage.
    """

    def __init__(self, owner: MapperLifecycleOwner, operations: Any,
                 loop_device: str, *, admission_gate) -> None:
        if type(owner) is not MapperLifecycleOwner:
            raise FixtureOwnerDenied("producer requires the exact fixture mapper owner")
        if (type(loop_device) is not str
                or re.fullmatch(r"/dev/loop[0-9]+", loop_device) is None):
            raise FixtureOwnerDenied("producer requires one exact fixture loop identity")
        for method in ("collect_worker_completion", "inspect_swap", "swapoff",
                       "inspect_lower_dependencies", "detach_loop", "inspect_loop"):
            if not callable(getattr(operations, method, None)):
                raise FixtureOwnerDenied(f"trusted drain operation {method} is unavailable")
        if not callable(getattr(admission_gate, "_admission_snapshot", None)):
            raise FixtureOwnerDenied("trusted broker admission gate is unavailable")
        self._owner = owner
        self._operations = operations
        self._loop_device = loop_device
        self._admission_gate = admission_gate
        self._session_id = owner.lease.session_id
        self._key = secrets.token_bytes(32)
        self._policy: FixtureBackingReleasePolicy | None = None
        self._denial: str | None = None
        self._completed = False

    @property
    def backing_release_authorized(self) -> bool:
        return (self._denial is None and self._completed and self._policy is not None
                and self._policy.backing_release_authorized)

    @property
    def backing_must_be_preserved(self) -> bool:
        return not self.backing_release_authorized

    @property
    def denial(self) -> str | None:
        return self._denial

    @property
    def events(self) -> tuple[str, ...]:
        return () if self._policy is None else self._policy.events

    def collect(self) -> bool:
        """Run the fixed full sequence; any exception permanently denies."""
        if self._denial is not None:
            raise FixtureOwnerDenied(f"producer denial is latched: {self._denial}")
        if self._completed:
            self._deny("drain collection cannot be replayed")
        try:
            return self._collect()
        except Exception as exc:
            self._denial = str(exc) or type(exc).__name__
            if isinstance(exc, FixtureOwnerDenied):
                raise
            raise FixtureOwnerDenied(self._denial) from exc

    def _collect(self) -> bool:
        owner = self._owner
        identity = owner.identity
        handles = owner.registered_worker_handles
        admission = self._admission_gate._admission_snapshot()
        if (type(admission) is not AdmissionGateObservation
                or admission.session_id != self._session_id
                or admission.broker_state != "finalizing"
                or type(admission.closed) is not bool or admission.closed is not True
                or type(admission.request_inflight) is not int or admission.request_inflight != 0
                or type(admission.registered_handles) is not tuple
                or admission.registered_handles != handles
                or owner.state != owner.ACTIVE
                or owner._worker_roles != owner._admitted_roles):
            self._deny("broker admission or registered worker/role inventory is not closed and complete")
        dm_identity = DMIdentity(
            identity.name, identity.uuid, identity.major, identity.minor,
            identity.table_sha256,
        )
        self._policy = FixtureBackingReleasePolicy(
            session_id=self._session_id, key=self._key,
            dm_identities=(dm_identity,), loop_device=self._loop_device,
            mapper_name=identity.name, expected_worker_handles=handles,
        )

        # The state transition is owned here; no worker request contains a
        # success flag or can submit an admission receipt.
        owner.close_admission()
        if owner.state != owner.ADMISSION_CLOSED:
            self._deny("mapper owner did not close role admission")
        self._emit("admission_closed", {
            "session_id": admission.session_id,
            "closed": admission.closed,
            "no_more_roles": admission.closed and admission.request_inflight == 0,
        })

        worker = self._operations.collect_worker_completion(handles)
        self._validate_worker(worker, handles)
        try:
            verified = owner.operations.verify_worker_completion(worker)
        except Exception as exc:
            self._deny(f"worker completion authentication failed: {exc}")
        if verified is not True:
            self._deny("worker service did not authenticate the completion inventory")
        inventory_complete = worker.expected_handles == handles
        all_reaped = worker.reaped_handles == handles
        errors_empty = worker.errors == ()
        self._emit("workers_reaped", {
            "session_id": self._session_id,
            "inventory_complete": inventory_complete,
            "all_reaped": all_reaped,
            "errors_empty": errors_empty,
            "worker_service_exit_status": worker.service_exit_status,
            "expected_handles": list(handles), "reaped_handles": list(worker.reaped_handles),
            "role_descriptors_closed": list(worker.role_descriptors_closed),
            "worker_errors": list(worker.errors),
        })

        swap_before = self._swap_snapshot(identity)
        swapoff = SwapoffObservation(False, False, True)
        if swap_before.mapper_active:
            swapoff = self._operations.swapoff(identity)
            if (type(swapoff) is not SwapoffObservation or swapoff.attempted is not True
                    or swapoff.succeeded is not True or swapoff.identity_matches is not True):
                self._deny("exact test mapper swapoff did not succeed")
        swap_after = self._swap_snapshot(identity)
        if swap_after.mapper_active:
            self._deny("fresh swap inventory still shows the test mapper active")
        self._emit("swap_quiescent", {
            "session_id": self._session_id,
            "inventory_valid": swap_before.valid and swap_after.valid,
            "mapper_active_before": swap_before.mapper_active,
            "swapoff_attempted": swapoff.attempted,
            "swapoff_succeeded": swapoff.succeeded,
            "mapper_active_after": swap_after.mapper_active,
            "swap_inventory_sha256": swap_after.inventory_sha256,
            "mapper_swap_identity": self._identity_object(identity),
        })

        # MapperLifecycleOwner executes ordinary suspend, descriptor close,
        # exact open/holder inspection, normal remove and a fresh absence scan.
        report = owner.release_mapping(worker)
        self._validate_release_report(report, identity, worker)
        absent_rows = self._inventory_rows(report.inventory_after)
        assert absent_rows is not None
        name_absent = all(item.name != identity.name for item in absent_rows)
        uuid_absent = all(item.uuid != identity.uuid for item in absent_rows)
        device_absent = all((item.major, item.minor) != (identity.major, identity.minor)
                            for item in absent_rows)
        exact_mapper_absent = name_absent and uuid_absent and device_absent
        dm_base = {
            "session_id": self._session_id,
            "name": identity.name, "uuid": identity.uuid,
            "major": identity.major, "minor": identity.minor,
            "table_sha256": identity.table_sha256,
        }
        suspended_hash = self._mapper_inventory_digest(report.inventory_after_suspend)
        remove_hash = self._mapper_inventory_digest(report.inventory_before_remove)
        after_hash = self._mapper_inventory_digest(report.inventory_after)
        suspend = report.suspend
        self._emit("dm_suspended", {
            **dm_base, "inventory_sha256": suspended_hash,
            "ioctl_succeeded": suspend.succeeded,
            "ordinary_flush": suspend.ordinary_flush, "noflush": suspend.noflush,
            "timed_out": suspend.timed_out, "identity_matches": suspend.identity_matches,
            "suspended": suspend.suspended,
            "pending_io_drained": suspend.pending_io_drained,
        })
        self._emit("dm_descriptors_closed", {
            **dm_base, "inventory_sha256": suspended_hash,
            "all_closed": report.mapper_descriptor_closed
                and report.worker_completion.role_descriptors_closed == handles,
            "close_errors_empty": report.worker_completion.errors == (),
            "descriptor_owner_session_id": report.session_id,
        })
        openers = report.openers
        self._emit("dm_open_count_zero", {
            **dm_base, "inventory_sha256": suspended_hash,
            "inventory_valid": openers.inventory_valid,
            "identity_matches": openers.identity_matches,
            "open_count": openers.open_count,
            "holders_empty": openers.holders == (), "holders": list(openers.holders),
        })
        self._emit("dm_removed", {
            **dm_base, "inventory_sha256": remove_hash,
            "remove_succeeded": report.removal.succeeded,
            "normal_remove": report.removal.normal_remove,
            "force": report.removal.force, "deferred": report.removal.deferred,
            "identity_matches": report.removal.identity_matches,
        })
        self._emit("dm_absent", {
            **dm_base, "inventory_sha256": after_hash,
            "inventory_valid": report.inventory_after.valid,
            "all_rows_valid": absent_rows is not None,
            "name_absent": name_absent, "uuid_absent": uuid_absent,
            "device_number_absent": device_absent,
            "fixture_owner_release": {
                "session_id": report.session_id, "name": identity.name,
                "uuid": identity.uuid, "major": identity.major, "minor": identity.minor,
                "table_sha256": identity.table_sha256,
                "normal_remove": report.removal.normal_remove,
                "disappearance_verified": exact_mapper_absent,
                "lease_released": report.lease_released,
            },
        })

        lower = self._operations.inspect_lower_dependencies(identity, self._loop_device)
        if (type(lower) is not LowerDependencyObservation
                or lower.inventory_valid is not True or lower.dm_stack_absent is not True
                or type(lower.holders) is not tuple or lower.holders != ()
                or lower.loop_identity_matches is not True
                or lower.dm_names_absent != (identity.name,)
                or _DIGEST.fullmatch(lower.inventory_sha256) is None):
            self._deny("lower dependency or loop holder inventory is not exactly empty")
        self._emit("loop_dependencies_clear", {
            "session_id": self._session_id, "dm_stack_absent": lower.dm_stack_absent,
            "holder_inventory_valid": lower.inventory_valid,
            "holders_empty": lower.holders == (),
            "loop_identity_matches": lower.loop_identity_matches,
            "loop_device": self._loop_device,
            "dm_names_absent": list(lower.dm_names_absent),
            "holder_inventory_sha256": lower.inventory_sha256,
        })

        detach = self._operations.detach_loop(self._loop_device)
        if (type(detach) is not LoopDetachObservation or detach.succeeded is not True
                or detach.normal_detach is not True or detach.identity_matches is not True):
            self._deny("normal exact loop detach did not succeed")
        loop_after = self._operations.inspect_loop(self._loop_device)
        if (type(loop_after) is not LoopInventoryObservation
                or loop_after.valid is not True or loop_after.exact_loop_present is not False
                or _DIGEST.fullmatch(loop_after.inventory_sha256) is None):
            self._deny("fresh loop inventory does not prove exact loop absence")
        self._emit("loop_detached", {
            "session_id": self._session_id, "detach_succeeded": detach.succeeded,
            "normal_detach": detach.normal_detach, "inventory_valid": loop_after.valid,
            "exact_loop_absent": not loop_after.exact_loop_present,
            "loop_device": self._loop_device,
            "loop_inventory_sha256": loop_after.inventory_sha256,
        })
        if not self._policy.backing_release_authorized:
            self._deny("complete evidence sequence did not authorize backing release")
        self._completed = True
        return True

    def _swap_snapshot(self, identity: MapperIdentity) -> SwapInventoryObservation:
        observation = self._operations.inspect_swap(identity)
        if (type(observation) is not SwapInventoryObservation
                or observation.valid is not True or type(observation.mapper_active) is not bool
                or _DIGEST.fullmatch(observation.inventory_sha256) is None
                or (observation.mapper_active and observation.mapper_identity != identity)
                or (not observation.mapper_active and observation.mapper_identity not in (None, identity))):
            self._deny("swap inventory is invalid, ambiguous, or not bound to the fixture mapper")
        return observation

    def _validate_worker(self, worker: WorkerCompletionEvidence,
                         handles: tuple[str, ...]) -> None:
        if (type(worker) is not WorkerCompletionEvidence
                or type(worker.session_id) is not str
                or worker.session_id != self._session_id
                or type(worker.expected_handles) is not tuple
                or type(worker.reaped_handles) is not tuple
                or type(worker.role_descriptors_closed) is not tuple
                or type(worker.errors) is not tuple
                or worker.expected_handles != handles or worker.reaped_handles != handles
                or worker.role_descriptors_closed != handles or worker.errors != ()
                or type(worker.service_exit_status) is not int or worker.service_exit_status != 0
                or type(worker.authenticator) is not bytes or len(worker.authenticator) != 32):
            self._deny("worker service returned an incomplete or contradictory inventory")

    def _validate_release_report(self, report: MapperReleaseReport,
                                 identity: MapperIdentity,
                                 worker: WorkerCompletionEvidence) -> None:
        if (type(report) is not MapperReleaseReport
                or report.session_id != self._session_id or report.identity != identity
                or report.worker_completion != worker
                or not self._inventory_has_identity(report.inventory_before, identity)
                or type(report.suspend) is not _ALLOWLIST.MapperSuspendObservation
                or any(type(value) is not bool for value in (
                    report.suspend.succeeded, report.suspend.ordinary_flush,
                    report.suspend.noflush, report.suspend.timed_out,
                    report.suspend.identity_matches, report.suspend.suspended,
                    report.suspend.pending_io_drained,
                ))
                or report.suspend != _ALLOWLIST.MapperSuspendObservation(
                    True, True, False, False, True, True, True,
                )
                or report.suspend.pending_io_drained is not True
                or type(report.mapper_descriptor_closed) is not bool
                or report.mapper_descriptor_closed is not True
                or not self._inventory_has_identity(report.inventory_after_suspend, identity)
                or type(report.openers) is not _ALLOWLIST.MapperOpenersObservation
                or type(report.openers.inventory_valid) is not bool
                or type(report.openers.identity_matches) is not bool
                or type(report.openers.open_count) is not int
                or type(report.openers.holders) is not tuple
                or report.openers != _ALLOWLIST.MapperOpenersObservation(True, True, 0, ())
                or not self._inventory_has_identity(report.inventory_before_remove, identity)
                or type(report.removal) is not MapperRemovalObservation
                or any(type(value) is not bool for value in (
                    report.removal.succeeded, report.removal.normal_remove,
                    report.removal.force, report.removal.deferred,
                    report.removal.identity_matches,
                ))
                or report.removal != MapperRemovalObservation(True, True, False, False, True)
                or not self._inventory_absent(report.inventory_after, identity)
                or type(report.lease_released) is not bool
                or report.lease_released is not True):
            self._deny("mapper owner release report is incomplete or contradicts its bound identity")

    @staticmethod
    def _inventory_rows(inventory) -> tuple[MapperIdentity, ...] | None:
        if (type(inventory) is not _ALLOWLIST.MapperInventory
                or type(inventory.valid) is not bool or inventory.valid is not True
                or type(inventory.entries) is not tuple
                or any(type(item) is not MapperIdentity for item in inventory.entries)):
            return None
        rows = inventory.entries
        if (len({item.name for item in rows}) != len(rows)
                or len({item.uuid for item in rows}) != len(rows)
                or len({(item.major, item.minor) for item in rows}) != len(rows)):
            return None
        return rows

    @classmethod
    def _inventory_has_identity(cls, inventory, identity: MapperIdentity) -> bool:
        rows = cls._inventory_rows(inventory)
        if rows is None:
            return False
        matches = [item for item in rows if item.name == identity.name
                   or item.uuid == identity.uuid
                   or (item.major, item.minor) == (identity.major, identity.minor)]
        return matches == [identity]

    @classmethod
    def _inventory_absent(cls, inventory, identity: MapperIdentity) -> bool:
        rows = cls._inventory_rows(inventory)
        return rows is not None and not any(
            item.name == identity.name or item.uuid == identity.uuid
            or (item.major, item.minor) == (identity.major, identity.minor)
            for item in rows
        )

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        assert self._policy is not None
        try:
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                 ensure_ascii=True, allow_nan=False).encode("ascii")
            sequence = len(self._policy.events)
            envelope = AuthenticatedDrainEvidence(
                self._session_id, sequence, event, encoded,
                evidence_mac(self._key, self._session_id, sequence, event, encoded),
            )
            self._policy.submit(envelope)
        except Exception as exc:
            self._deny(f"internal drain evidence validation failed: {exc}")

    @staticmethod
    def _mapper_inventory_digest(inventory) -> str:
        rows = [{"name": item.name, "uuid": item.uuid, "major": item.major,
                 "minor": item.minor, "table_sha256": item.table_sha256}
                for item in inventory.entries]
        encoded = json.dumps({"valid": inventory.valid, "entries": rows},
                             sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _identity_object(identity: MapperIdentity) -> dict[str, Any]:
        return {"name": identity.name, "uuid": identity.uuid,
                "major": identity.major, "minor": identity.minor}

    def _deny(self, message: str):
        if self._denial is None:
            self._denial = message
        raise FixtureOwnerDenied(self._denial)


class FixtureOwnerBroker:
    """Single-session worker-facing broker around MapperLifecycleOwner.

    Worker requests can launch one of five fixed roles only. The broker, not a
    worker request, supplies the handle and owns all mapper and drain methods.
    ``peer_authenticator`` must inspect transport credentials supplied by the
    accepted socket; the rootless tests use identity-bound fake peer tokens.
    """

    NEW = "new"
    ACTIVE = "active"
    FINALIZING = "finalizing"
    RELEASED = "released"
    DENIED = "denied"

    def __init__(self, mapper_owner: MapperLifecycleOwner, drain_operations: Any,
                 loop_device: str, *, peer_authenticator, worker_launcher,
                 worker_stopper=None) -> None:
        if type(mapper_owner) is not MapperLifecycleOwner:
            raise FixtureOwnerDenied("broker requires the exact mapper lifecycle owner")
        if not callable(peer_authenticator) or not callable(worker_launcher):
            raise FixtureOwnerDenied("broker peer authentication and worker launcher are required")
        self.mapper_owner = mapper_owner
        self._request_inflight = 0
        self._producer = FixtureDrainEvidenceProducer(
            mapper_owner, drain_operations, loop_device, admission_gate=self,
        )
        self._peer_authenticator = peer_authenticator
        self._worker_launcher = worker_launcher
        self._worker_stopper = worker_stopper
        self._state = self.NEW
        self._admission_open = False
        self._denial: str | None = None
        self._request_ids: set[str] = set()
        self._issued_handles: list[str] = []
        self._stop_attempted: set[str] = set()
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        return self._state

    @property
    def mapping_released(self) -> bool:
        return self.mapper_owner.mapping_released

    @property
    def backing_release_authorized(self) -> bool:
        return (self._state == self.RELEASED and self._denial is None
                and self.mapping_released and self._producer.backing_release_authorized)

    @property
    def backing_must_be_preserved(self) -> bool:
        return not self.backing_release_authorized

    @property
    def denial(self) -> str | None:
        return self._denial or self._producer.denial

    @property
    def evidence_events(self) -> tuple[str, ...]:
        return self._producer.events

    def owner_create(self) -> None:
        with self._serialized():
            if self._state != self.NEW:
                self._deny("fixture mapping creation is out of order")
            try:
                self.mapper_owner.create()
            except Exception as exc:
                self._deny(f"fixture mapping creation failed: {exc}")
            self._admission_open = True
            self._state = self.ACTIVE

    def worker_request(self, peer: object, request: object) -> dict[str, object]:
        with self._serialized():
            if self._state != self.ACTIVE or not self._admission_open:
                self._deny("worker request arrived outside open fixture admission")
            principal = self._principal(peer)
            if principal != "worker":
                self._deny("worker IPC credential is invalid or ambiguous")
            if (type(request) is not dict
                    or set(request) != {"request_id", "operation", "role"}
                    or type(request.get("request_id")) is not str
                    or _REQUEST_ID.fullmatch(request["request_id"]) is None
                    or type(request.get("operation")) is not str
                    or request["operation"] != "launch_role"
                    or type(request.get("role")) is not str
                    or request["role"] not in _ROLES):
                self._deny("worker IPC request is malformed or outside the role-only API")
            request_id = request["request_id"]
            if request_id in self._request_ids:
                self._deny("worker IPC request identifier was replayed")
            self._request_ids.add(request_id)
            role = request["role"]
            try:
                self.mapper_owner.authorize_role(role)
                handle = self._worker_launcher(role)
                if (type(handle) is not str or _HANDLE.fullmatch(handle) is None
                        or handle.isdecimal() or handle in self._issued_handles):
                    self._deny("supervisor returned an invalid or duplicate opaque handle")
                self._issued_handles.append(handle)
                if self._denial is not None:
                    self._deny("fixture was denied while role launch was in flight")
                self.mapper_owner.register_worker(handle, role)
            except Exception as exc:
                self._deny(f"fixed role launch failed: {exc}")
            return {"request_id": request_id, "status": "launched", "handle": handle}

    def finalize(self) -> bool:
        """Trusted owner event-loop entry point; never exposed on worker IPC."""
        with self._serialized():
            if self._state != self.ACTIVE or not self._admission_open:
                self._deny("fixture finalization is out of order")
            self._admission_open = False
            self._state = self.FINALIZING
            try:
                self._producer.collect()
            except Exception as exc:
                self._deny(f"fixture drain sequence failed: {exc}")
            if not self._producer.backing_release_authorized or not self.mapping_released:
                self._deny("mapper-only or drain evidence is insufficient for backing release")
            self._state = self.RELEASED
            return True

    def worker_control_eof(self, peer: object) -> None:
        with self._serialized():
            if self._principal(peer) != "worker":
                self._deny("control EOF came from an unverified worker channel")
            self._deny("worker control channel ended before owner finalization")

    def owner_control_eof(self) -> None:
        """Model lost owner/control transport; the denial is permanently sticky."""
        with self._serialized():
            self._deny("fixture owner control channel ended")

    def producer_died(self) -> None:
        """Model producer process death without a final authenticated report."""
        with self._serialized():
            self._deny("drain evidence producer disappeared before completion")

    def _principal(self, peer: object) -> str | None:
        try:
            principal = self._peer_authenticator(peer)
        except Exception as exc:
            self._deny(f"cannot authenticate worker peer credentials: {exc}")
        if principal is not None and (type(principal) is not str or principal != "worker"):
            self._deny("unexpected IPC principal")
        return principal

    def _admission_snapshot(self) -> AdmissionGateObservation:
        """Internal producer view; no worker IPC operation returns this object."""
        return AdmissionGateObservation(
            session_id=self.mapper_owner.lease.session_id,
            broker_state=self._state,
            closed=not self._admission_open,
            request_inflight=self._request_inflight,
            registered_handles=self.mapper_owner.registered_worker_handles,
        )

    class _Guard:
        def __init__(self, broker: "FixtureOwnerBroker") -> None:
            self.broker = broker

        def __enter__(self):
            if not self.broker._lock.acquire(blocking=False):
                self.broker._latch("concurrent fixture lifecycle request")
                self.broker._best_effort_stop(tuple(self.broker._issued_handles))
                raise FixtureOwnerDenied(self.broker._denial)
            if self.broker._denial is not None:
                self.broker._lock.release()
                raise FixtureOwnerDenied(self.broker._denial)
            return self.broker

        def __exit__(self, exc_type, exc, traceback):
            self.broker._lock.release()
            return False

    def _serialized(self):
        return self._Guard(self)

    def _latch(self, message: str) -> None:
        if self._denial is None:
            self._denial = message
        self._admission_open = False
        self._state = self.DENIED

    def _best_effort_stop(self, handles: tuple[str, ...]) -> None:
        pending = tuple(handle for handle in handles if handle not in self._stop_attempted)
        if not pending:
            return
        self._stop_attempted.update(pending)
        if not callable(self._worker_stopper):
            return
        try:
            self._worker_stopper(pending)
        except Exception as exc:
            if self._denial is None:
                self._denial = "best-effort worker stop failed"
            self._denial += f"; worker stop error: {exc}"

    def _deny(self, message: str):
        self._latch(message)
        # Best-effort stopping uses only opaque handles. Any failure still
        # preserves backing; this path never attempts device teardown.
        self._best_effort_stop(tuple(self._issued_handles))
        raise FixtureOwnerDenied(self._denial)


__all__ = [
    "FixtureOwnerBroker", "FixtureOwnerDenied", "FixtureDrainEvidenceProducer",
    "AdmissionGateObservation",
    "SwapInventoryObservation", "SwapoffObservation", "LowerDependencyObservation",
    "LoopDetachObservation", "LoopInventoryObservation",
]
