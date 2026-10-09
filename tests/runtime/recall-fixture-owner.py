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
import socket
import struct
import sys
import threading
import time
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
WorkerRoleResult = _ALLOWLIST.WorkerRoleResult
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
_IPC_MAX_FRAME = 1024
_IPC_TIMEOUT_SECONDS = 3.0
_STARTUP_TIMEOUT_SECONDS = 3.0
_MAX_DM_LAYERS = 8


@dataclass(frozen=True)
class AdmissionGateObservation:
    session_id: str
    broker_state: str
    closed: bool
    request_inflight: int
    registered_handles: tuple[str, ...]
    expected_roles: tuple[str, ...]
    registered_roles: tuple[str, ...]
    launch_ambiguous: bool
    gated_roles: tuple[str, ...]


@dataclass(frozen=True)
class SessionProfile:
    """Immutable worker/dependency contract selected by trusted bootstrap."""

    name: str
    expected_roles: tuple[str, ...]
    concurrent_groups: tuple[tuple[str, ...], ...]
    nbd_required: bool = False


FIXED_RECALL_PROFILE = SessionProfile(
    "v22-recall-five-role", _ROLES, (("a2", "b2"),), False,
)
FIXED_RECALL_NBD_PROFILE = SessionProfile(
    "v22-recall-five-role-nbd", _ROLES, (("a2", "b2"),), True,
)


@dataclass(frozen=True)
class PeerCredentials:
    pid: int
    uid: int
    gid: int

    def __post_init__(self) -> None:
        if (type(self.pid) is not int or self.pid <= 0
                or type(self.uid) is not int or self.uid < 0
                or type(self.gid) is not int or self.gid < 0):
            raise FixtureOwnerDenied("expected peer credentials are malformed")


@dataclass(frozen=True)
class WorkerLaunchReceipt:
    """Launcher attestation: a pidfd-owned worker is READY but still gated."""

    handle: str
    role: str
    ready: bool
    pidfd_owned: bool
    startup_within_deadline: bool
    gate_held: bool


@dataclass(frozen=True)
class WorkerStopReport:
    all_reaped: bool
    errors: tuple[str, ...]


@dataclass(frozen=True)
class LayerObservation:
    identity: DMIdentity
    inventory_valid: bool
    identity_matches: bool
    suspend_succeeded: bool
    ordinary_flush: bool
    noflush: bool
    pending_io_drained: bool
    descriptors_closed: bool
    open_count: int
    holders: tuple[str, ...]
    remove_succeeded: bool
    normal_remove: bool
    force: bool
    deferred: bool
    exact_name_absent: bool
    exact_uuid_absent: bool
    exact_device_absent: bool


class LayeredDMReleaseModel:
    """Rootless upper-to-lower dependency sequence; operation results are faked."""

    def __init__(self, identities: tuple[DMIdentity, ...]) -> None:
        if (type(identities) is not tuple or not identities
                or len(identities) > _MAX_DM_LAYERS
                or any(type(item) is not DMIdentity for item in identities)
                or any(type(item.name) is not str
                       or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}", item.name) is None
                       or type(item.uuid) is not str or not item.uuid or len(item.uuid) > 128
                       or any(ord(char) < 0x21 or ord(char) > 0x7e for char in item.uuid)
                       or type(item.major) is not int or not 0 <= item.major <= 4095
                       or type(item.minor) is not int or not 0 <= item.minor <= 1048575
                       or type(item.table_sha256) is not str
                       or _DIGEST.fullmatch(item.table_sha256) is None
                       for item in identities)
                or len({item.name for item in identities}) != len(identities)
                or len({item.uuid for item in identities}) != len(identities)
                or len({(item.major, item.minor) for item in identities}) != len(identities)):
            raise FixtureOwnerDenied("layered DM inventory must be fixed, ordered and unique")
        self.identities = identities  # explicit upper-to-lower order
        self.events: list[tuple[str, str]] = []
        self._denial: str | None = None
        self._released: tuple[str, ...] = ()

    @property
    def mapper_dependencies_released(self) -> bool:
        return self._denial is None and self._released == tuple(
            item.name for item in self.identities
        )

    @property
    def backing_must_be_preserved(self) -> bool:
        # Mapper disappearance never authorizes release of backing dependencies.
        return True

    def release_layers(self, observe_layer) -> tuple[str, ...]:
        if self._denial is not None or self._released:
            raise FixtureOwnerDenied("layer release is denied or already completed")
        if not callable(observe_layer):
            self._deny("layer operation collector is unavailable")
        released: list[str] = []
        try:
            for identity in self.identities:
                observation = observe_layer(identity)
                if (type(observation) is not LayerObservation
                        or observation.identity != identity
                        or any(type(value) is not bool for value in (
                            observation.inventory_valid, observation.identity_matches,
                            observation.suspend_succeeded, observation.ordinary_flush,
                            observation.noflush, observation.pending_io_drained,
                            observation.descriptors_closed, observation.remove_succeeded,
                            observation.normal_remove, observation.force, observation.deferred,
                            observation.exact_name_absent, observation.exact_uuid_absent,
                            observation.exact_device_absent,
                        ))
                        or observation.inventory_valid is not True
                        or observation.identity_matches is not True
                        or observation.suspend_succeeded is not True
                        or observation.ordinary_flush is not True
                        or observation.noflush is not False
                        or observation.pending_io_drained is not True):
                    self._deny(f"layer {identity.name} suspend or identity evidence is invalid")
                self.events.append(("suspended", identity.name))
                if (observation.descriptors_closed is not True
                        or type(observation.open_count) is not int or observation.open_count != 0
                        or type(observation.holders) is not tuple or observation.holders != ()):
                    self._deny(f"layer {identity.name} descriptor/openers evidence is invalid")
                self.events.append(("descriptors_closed", identity.name))
                self.events.append(("openers_empty", identity.name))
                if (observation.remove_succeeded is not True
                        or observation.normal_remove is not True
                        or observation.force is not False or observation.deferred is not False):
                    self._deny(f"layer {identity.name} was not normally removed")
                self.events.append(("removed", identity.name))
                if not (observation.exact_name_absent and observation.exact_uuid_absent
                        and observation.exact_device_absent):
                    self._deny(f"layer {identity.name} exact disappearance was not verified")
                self.events.append(("absent", identity.name))
                released.append(identity.name)
            self._released = tuple(released)
            return self._released
        except FixtureOwnerDenied:
            raise
        except Exception as exc:
            self._deny(f"layered DM observation failed: {exc}")

    def _deny(self, message: str):
        if self._denial is None:
            self._denial = message
        raise FixtureOwnerDenied(self._denial)


@dataclass(frozen=True)
class NBDServerIdentity:
    session_id: str
    handle: str
    pidfd_owned: bool
    descriptor_retained: bool
    device: str
    major: int
    minor: int


@dataclass(frozen=True)
class NBDDisconnectObservation:
    succeeded: bool
    normal_disconnect: bool
    identity_matches: bool
    server_handle: str
    server_reaped: bool
    server_pidfd_retained: bool
    server_descriptor_closed: bool
    device: str
    major: int
    minor: int


@dataclass(frozen=True)
class NBDInventoryObservation:
    valid: bool
    exact_device_present: bool
    server_handle: str
    device: str
    major: int
    minor: int
    inventory_sha256: str


class NBDReleaseModel:
    """Separate optional NBD server/disconnect model; does not imply loop absence."""

    def __init__(self, session_id: str, server: NBDServerIdentity, device: str) -> None:
        if (type(session_id) is not str or re.fullmatch(r"[0-9a-f]{32}", session_id) is None
                or type(server) is not NBDServerIdentity
                or type(server.session_id) is not str or server.session_id != session_id
                or type(server.handle) is not str
                or _HANDLE.fullmatch(server.handle) is None or server.handle.isdecimal()
                or server.pidfd_owned is not True or server.descriptor_retained is not True
                or type(device) is not str or re.fullmatch(r"/dev/nbd[0-9]+", device) is None
                or server.device != device
                or type(server.major) is not int or not 0 <= server.major <= 4095
                or type(server.minor) is not int or not 0 <= server.minor <= 1048575):
            raise FixtureOwnerDenied("NBD profile lacks exact session-bound pidfd server identity")
        self.session_id, self.server, self.device = session_id, server, device
        self._denial: str | None = None
        self._released = False
        self.events: list[str] = []

    @property
    def nbd_released(self) -> bool:
        return self._denial is None and self._released

    def disconnect_and_verify(self, disconnect, inspect) -> bool:
        if self._denial is not None or self._released:
            raise FixtureOwnerDenied("NBD release is denied or already completed")
        try:
            outcome = disconnect(self.server, self.device)
            if (type(outcome) is not NBDDisconnectObservation
                    or outcome.succeeded is not True or outcome.normal_disconnect is not True
                    or outcome.identity_matches is not True
                    or outcome.server_handle != self.server.handle
                    or outcome.server_reaped is not True
                    or outcome.server_pidfd_retained is not True
                    or outcome.server_descriptor_closed is not True
                    or outcome.device != self.device
                    or (outcome.major, outcome.minor) != (self.server.major, self.server.minor)):
                self._deny("normal NBD disconnect did not match the owned server")
            self.events.append("nbd_disconnected")
            inventory = inspect(self.server, self.device)
            if (type(inventory) is not NBDInventoryObservation
                    or inventory.valid is not True or inventory.exact_device_present is not False
                    or inventory.server_handle != self.server.handle
                    or inventory.device != self.device
                    or (inventory.major, inventory.minor) != (self.server.major, self.server.minor)
                    or _DIGEST.fullmatch(inventory.inventory_sha256) is None):
                self._deny("fresh NBD inventory does not prove exact device absence")
            self.events.append("nbd_absent")
            self._released = True
            return True
        except FixtureOwnerDenied:
            raise
        except Exception as exc:
            self._deny(f"NBD disconnect or inventory failed: {exc}")

    def _deny(self, message: str):
        if self._denial is None:
            self._denial = message
        raise FixtureOwnerDenied(self._denial)


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
                 loop_device: str, *, admission_gate,
                 nbd_release: NBDReleaseModel | None = None) -> None:
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
        profile = getattr(admission_gate, "session_profile", None)
        if type(profile) is not SessionProfile:
            raise FixtureOwnerDenied("immutable session role profile is unavailable")
        if profile.nbd_required != (type(nbd_release) is NBDReleaseModel):
            raise FixtureOwnerDenied("NBD session profile and retained server identity disagree")
        if nbd_release is not None and nbd_release.session_id != owner.lease.session_id:
            raise FixtureOwnerDenied("NBD server identity belongs to another session")
        self._owner = owner
        self._operations = operations
        self._loop_device = loop_device
        self._admission_gate = admission_gate
        self._profile = profile
        self._nbd_release = nbd_release
        self._session_id = owner.lease.session_id
        self._key = secrets.token_bytes(32)
        self._policy: FixtureBackingReleasePolicy | None = None
        self._denial: str | None = None
        self._completed = False

    @property
    def backing_release_authorized(self) -> bool:
        return (self._denial is None and self._completed and self._policy is not None
                and self._policy.backing_release_authorized
                and (not self._profile.nbd_required
                     or (self._nbd_release is not None and self._nbd_release.nbd_released)))

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
                or admission.expected_roles != self._profile.expected_roles
                or admission.registered_roles != self._profile.expected_roles
                or admission.launch_ambiguous is not False
                or admission.gated_roles != ()
                or owner.state != owner.ACTIVE
                or owner._worker_roles != list(self._profile.expected_roles)
                or owner._admitted_roles != list(self._profile.expected_roles)):
            self._deny("broker admission or registered worker/role inventory is not closed and complete")
        dm_identity = DMIdentity(
            identity.name, identity.uuid, identity.major, identity.minor,
            identity.table_sha256,
        )
        self._policy = FixtureBackingReleasePolicy(
            session_id=self._session_id, key=self._key,
            dm_identities=(dm_identity,), loop_device=self._loop_device,
            mapper_name=identity.name, expected_worker_handles=handles,
            expected_worker_roles=self._profile.expected_roles,
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
        self._validate_worker(worker, handles, self._profile.expected_roles)
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
            "expected_roles": list(self._profile.expected_roles),
            "role_results": [
                {"role": result.role, "handle": result.handle,
                 "exit_status": result.exit_status, "reaped": result.reaped,
                 "descriptor_closed": result.descriptor_closed,
                 "errors": list(result.errors)}
                for result in worker.role_results
            ],
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

        if self._profile.nbd_required:
            assert self._nbd_release is not None
            for method in ("disconnect_nbd", "inspect_nbd"):
                if not callable(getattr(self._operations, method, None)):
                    self._deny(f"NBD operation {method} is unavailable")
            self._nbd_release.disconnect_and_verify(
                self._operations.disconnect_nbd, self._operations.inspect_nbd,
            )

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
                         handles: tuple[str, ...], roles: tuple[str, ...]) -> None:
        role_results = getattr(worker, "role_results", None)
        if (type(worker) is not WorkerCompletionEvidence
                or type(worker.session_id) is not str
                or worker.session_id != self._session_id
                or type(worker.expected_handles) is not tuple
                or type(worker.reaped_handles) is not tuple
                or type(worker.role_descriptors_closed) is not tuple
                or type(worker.errors) is not tuple
                or type(role_results) is not tuple
                or len(role_results) != len(roles)
                or worker.expected_handles != handles or worker.reaped_handles != handles
                or worker.role_descriptors_closed != handles or worker.errors != ()
                or type(worker.service_exit_status) is not int or worker.service_exit_status != 0
                or type(worker.authenticator) is not bytes or len(worker.authenticator) != 32):
            self._deny("worker service returned an incomplete or contradictory inventory")
        for role, handle, result in zip(roles, handles, role_results):
            if (type(result) is not WorkerRoleResult
                    or result.role != role or result.handle != handle
                    or type(result.exit_status) is not int or result.exit_status != 0
                    or type(result.reaped) is not bool or result.reaped is not True
                    or type(result.descriptor_closed) is not bool
                    or result.descriptor_closed is not True
                    or type(result.errors) is not tuple or result.errors != ()):
                self._deny("worker role result inventory is missing, reordered, or unsuccessful")

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
    Production callers must use ``serve_worker_connection``. It binds one
    Unix-stream connection to kernel ``SO_PEERCRED``. ``worker_request`` is a
    direct injected seam retained for unit tests only.
    """

    NEW = "new"
    ACTIVE = "active"
    FINALIZING = "finalizing"
    RELEASED = "released"
    DENIED = "denied"

    def __init__(self, mapper_owner: MapperLifecycleOwner, drain_operations: Any,
                 loop_device: str, *, peer_authenticator, worker_launcher,
                 session_profile: SessionProfile = FIXED_RECALL_PROFILE,
                 nbd_release: NBDReleaseModel | None = None) -> None:
        if type(mapper_owner) is not MapperLifecycleOwner:
            raise FixtureOwnerDenied("broker requires the exact mapper lifecycle owner")
        if (not callable(peer_authenticator)
                or any(not callable(getattr(worker_launcher, method, None))
                       for method in ("launch", "release_group", "stop_unconfirmed", "stop_all"))):
            raise FixtureOwnerDenied("broker peer authentication and worker launcher are required")
        if (type(session_profile) is not SessionProfile
                or session_profile not in (FIXED_RECALL_PROFILE, FIXED_RECALL_NBD_PROFILE)):
            raise FixtureOwnerDenied("broker profile is not one of the immutable recall sessions")
        if session_profile.nbd_required != (type(nbd_release) is NBDReleaseModel):
            raise FixtureOwnerDenied("NBD profile must bind one exact retained server identity")
        self.mapper_owner = mapper_owner
        self.session_profile = session_profile
        self._request_inflight = 0
        self._producer = FixtureDrainEvidenceProducer(
            mapper_owner, drain_operations, loop_device, admission_gate=self,
            nbd_release=nbd_release,
        )
        self._peer_authenticator = peer_authenticator
        self._worker_launcher = worker_launcher
        self._state = self.NEW
        self._admission_open = False
        self._denial: str | None = None
        self._request_ids: set[str] = set()
        self._issued_handles: list[str] = []
        self._issued_roles: list[str] = []
        self._role_handles: dict[str, str] = {}
        self._gated_roles: set[str] = set()
        self._stop_attempted = False
        self._launch_ambiguous = False
        self._connection_claimed = False
        self._connection_required_close = False
        self._peer_closed = False
        self._peer_credentials: PeerCredentials | None = None
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

    @property
    def peer_credentials(self) -> PeerCredentials | None:
        return self._peer_credentials

    @property
    def request_inflight(self) -> int:
        return self._request_inflight

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
        """Injected unit-test entry; live callers use SO_PEERCRED socket API."""
        with self._serialized():
            principal = self._principal(peer)
            return self._worker_request_principal(principal, request)

    def serve_worker_connection(self, connection: socket.socket,
                                expected_peer: PeerCredentials) -> int:
        """Serve one bounded AF_UNIX stream, authenticating actual SO_PEERCRED.

        The exact peer PID/UID/GID must have been obtained by trusted owner
        bootstrap when it launched the bridge. No credential is read from JSON.
        A connection can only be claimed once for this session.
        """
        if (type(expected_peer) is not PeerCredentials or not isinstance(connection, socket.socket)
                or connection.family != socket.AF_UNIX
                or connection.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM):
            with self._serialized():
                self._deny("worker transport is not the expected Unix stream")
        try:
            connection.set_inheritable(False)
            connection.settimeout(_IPC_TIMEOUT_SECONDS)
            raw = connection.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"),
            )
            credentials = PeerCredentials(*struct.unpack("3i", raw))
        except Exception as exc:
            with self._serialized():
                self._deny(f"cannot obtain kernel worker peer credentials: {exc}")
        with self._serialized():
            if self._connection_claimed:
                self._deny("worker control connection was replaced or replayed")
            self._connection_claimed = True
            self._connection_required_close = True
            self._peer_credentials = credentials
            if credentials != expected_peer:
                self._deny("kernel Unix peer credentials differ from trusted bridge identity")
        processed = 0
        try:
            while True:
                frame = self._recv_frame(
                    connection, allow_initial_eof=True,
                    deadline=time.monotonic() + _IPC_TIMEOUT_SECONDS,
                )
                if frame is None:
                    with self._serialized():
                        if (self._issued_roles != list(self.session_profile.expected_roles)
                                or self._request_inflight != 0):
                            self._deny("worker control EOF arrived before the exact role inventory")
                        self._peer_closed = True
                    return processed
                with self._serialized():
                    response = self._worker_request_principal("worker", frame)
                self._send_frame(connection, response)
                processed += 1
        except Exception as exc:
            with self._serialized():
                self._deny(f"worker control protocol failed: {exc}")

    def _worker_request_principal(self, principal: str | None,
                                  request: object) -> dict[str, object]:
        if self._state != self.ACTIVE or not self._admission_open:
            self._deny("worker request arrived outside open fixture admission")
        if principal != "worker":
            self._deny("worker IPC credential is invalid or ambiguous")
        if (type(request) is not dict
                or set(request) != {"request_id", "operation", "role"}
                or type(request.get("request_id")) is not str
                or _REQUEST_ID.fullmatch(request["request_id"]) is None
                or type(request.get("operation")) is not str
                or request["operation"] != "launch_role"
                or type(request.get("role")) is not str
                or request["role"] not in self.session_profile.expected_roles):
            self._deny("worker IPC request is malformed or outside the role-only API")
        request_id, role = request["request_id"], request["role"]
        if request_id in self._request_ids:
            self._deny("worker IPC request identifier was replayed")
        if len(self._issued_roles) >= len(self.session_profile.expected_roles):
            self._deny("fixed role inventory already complete")
        expected_role = self.session_profile.expected_roles[len(self._issued_roles)]
        if role != expected_role:
            self._deny(f"role order violation: expected {expected_role}, received {role}")
        self._request_ids.add(request_id)
        self._request_inflight += 1
        try:
            self.mapper_owner.authorize_role(role)
            self._launch_ambiguous = True
            launch_started = time.monotonic()
            receipt = self._worker_launcher.launch(
                role, startup_timeout=_STARTUP_TIMEOUT_SECONDS,
            )
            if time.monotonic() - launch_started > _STARTUP_TIMEOUT_SECONDS:
                self._deny("pidfd-owned READY handshake exceeded its fixed deadline")
            if (type(receipt) is not WorkerLaunchReceipt
                    or type(receipt.handle) is not str
                    or _HANDLE.fullmatch(receipt.handle) is None
                    or receipt.handle.isdecimal() or receipt.handle in self._issued_handles
                    or receipt.role != role
                    or type(receipt.ready) is not bool or receipt.ready is not True
                    or type(receipt.pidfd_owned) is not bool or receipt.pidfd_owned is not True
                    or type(receipt.startup_within_deadline) is not bool
                    or receipt.startup_within_deadline is not True
                    or type(receipt.gate_held) is not bool or receipt.gate_held is not True):
                self._deny("launcher did not prove a unique pidfd-owned gated READY child")
            handle = receipt.handle
            # Retain the handle before owner registration or gate release. If
            # either operation fails, denial recovery still addresses it.
            self._issued_handles.append(handle)
            self._issued_roles.append(role)
            self._role_handles[role] = handle
            self.mapper_owner.register_worker(handle, role)
            self._launch_ambiguous = False
            if self._denial is not None:
                self._deny("fixture was denied while role launch was in flight")
            group = next((item for item in self.session_profile.concurrent_groups
                          if role in item), None)
            if group is not None and not all(item in self._role_handles for item in group):
                self._gated_roles.add(role)
                return {"request_id": request_id, "status": "ready_gated",
                        "handle": handle, "started": False}
            release_roles = group if group is not None else (role,)
            release_handles = tuple(self._role_handles[item] for item in release_roles)
            self._worker_launcher.release_group(release_handles)
            self._gated_roles.difference_update(release_roles)
            self._launch_ambiguous = False
            return {"request_id": request_id, "status": "launched",
                    "handle": handle, "started": True}
        except FixtureOwnerDenied:
            raise
        except Exception as exc:
            self._launch_ambiguous = True
            self._deny(f"fixed role launch failed or became ambiguous: {exc}")
        finally:
            self._request_inflight -= 1
            if self._request_inflight == 0 and self._denial is not None:
                self._best_effort_stop()

    def finalize(self) -> bool:
        """Trusted owner event-loop entry point; never exposed on worker IPC."""
        with self._serialized():
            if self._state != self.ACTIVE or not self._admission_open:
                self._deny("fixture finalization is out of order")
            if self._issued_roles != list(self.session_profile.expected_roles):
                self._deny("fixed recall session is missing one or more required roles")
            if self._request_inflight != 0:
                self._deny("fixture finalization overlaps an unresolved worker request")
            if self._connection_required_close and not self._peer_closed:
                self._deny("worker control connection has not closed after complete admission")
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
            if (self._issued_roles != list(self.session_profile.expected_roles)
                    or self._request_inflight != 0):
                self._deny("worker control channel ended before the exact role inventory")
            self._peer_closed = True

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
            expected_roles=self.session_profile.expected_roles,
            registered_roles=tuple(self._issued_roles),
            launch_ambiguous=self._launch_ambiguous,
            gated_roles=tuple(role for role in self.session_profile.expected_roles
                              if role in self._gated_roles),
        )

    @staticmethod
    def _json_unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise FixtureOwnerDenied("worker frame contains duplicate JSON fields")
            result[key] = value
        return result

    @classmethod
    def _recv_frame(cls, connection: socket.socket, *, allow_initial_eof: bool,
                    deadline: float) -> dict[str, object] | None:
        header = cls._recv_exact(
            connection, 4, allow_initial_eof=allow_initial_eof, deadline=deadline,
        )
        if header is None:
            return None
        size = struct.unpack("!I", header)[0]
        if size < 2 or size > _IPC_MAX_FRAME:
            raise FixtureOwnerDenied("worker frame length is outside the fixed bound")
        payload = cls._recv_exact(
            connection, size, allow_initial_eof=False, deadline=deadline,
        )
        assert payload is not None
        try:
            request = json.loads(payload.decode("utf-8"), object_pairs_hook=cls._json_unique_object)
        except Exception as exc:
            raise FixtureOwnerDenied(f"worker frame is not valid unique-key JSON: {exc}") from exc
        if type(request) is not dict:
            raise FixtureOwnerDenied("worker frame must contain one JSON object")
        return request

    @staticmethod
    def _recv_exact(connection: socket.socket, length: int, *,
                    allow_initial_eof: bool, deadline: float) -> bytes | None:
        chunks: list[bytes] = []
        remaining = length
        while remaining:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                raise TimeoutError("worker frame exceeded its absolute read deadline")
            connection.settimeout(timeout)
            block = connection.recv(remaining)
            if not block:
                if allow_initial_eof and not chunks:
                    return None
                raise FixtureOwnerDenied("worker frame ended before its declared length")
            chunks.append(block)
            remaining -= len(block)
        return b"".join(chunks)

    @staticmethod
    def _send_frame(connection: socket.socket, response: dict[str, object]) -> None:
        payload = json.dumps(response, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode("ascii")
        if len(payload) > _IPC_MAX_FRAME:
            raise FixtureOwnerDenied("broker response exceeds the fixed IPC bound")
        connection.settimeout(_IPC_TIMEOUT_SECONDS)
        connection.sendall(struct.pack("!I", len(payload)) + payload)

    class _Guard:
        def __init__(self, broker: "FixtureOwnerBroker") -> None:
            self.broker = broker

        def __enter__(self):
            if not self.broker._lock.acquire(blocking=False):
                self.broker._latch("concurrent fixture lifecycle request")
                self.broker._best_effort_stop()
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

    def _best_effort_stop(self) -> None:
        if self._request_inflight:
            return
        if self._stop_attempted:
            return
        self._stop_attempted = True
        # The launcher owns every child from fork until a confirmed READY
        # receipt. This call is mandatory even when no handle was registered.
        errors = []
        try:
            unconfirmed = self._worker_launcher.stop_unconfirmed()
            if (type(unconfirmed) is not WorkerStopReport
                    or unconfirmed.all_reaped is not True or unconfirmed.errors != ()):
                errors.append("unconfirmed child inventory was not reaped cleanly")
        except Exception as exc:
            errors.append(f"unconfirmed child stop failed: {exc}")
        # Continue with registered identities even if the launcher reports a
        # failure for an unconfirmed child. This is best effort only: either
        # error still latches denial and backing preservation.
        try:
            stopped = self._worker_launcher.stop_all(tuple(self._issued_handles))
            if (type(stopped) is not WorkerStopReport
                    or stopped.all_reaped is not True or stopped.errors != ()):
                errors.append("registered worker inventory was not reaped cleanly")
        except Exception as exc:
            errors.append(f"registered worker stop failed: {exc}")
        if errors:
            self._denial = ((self._denial or "worker stop/reap failed")
                            + "; worker stop error: " + "; ".join(errors))

    def _deny(self, message: str):
        self._latch(message)
        # Best-effort stopping uses only opaque handles. Any failure still
        # preserves backing; this path never attempts device teardown.
        self._best_effort_stop()
        raise FixtureOwnerDenied(self._denial)


__all__ = [
    "FixtureOwnerBroker", "FixtureOwnerDenied", "FixtureDrainEvidenceProducer",
    "AdmissionGateObservation",
    "SwapInventoryObservation", "SwapoffObservation", "LowerDependencyObservation",
    "LoopDetachObservation", "LoopInventoryObservation",
    "SessionProfile", "FIXED_RECALL_PROFILE", "FIXED_RECALL_NBD_PROFILE",
    "PeerCredentials", "WorkerLaunchReceipt", "WorkerStopReport",
    "LayerObservation", "LayeredDMReleaseModel", "NBDServerIdentity",
    "NBDDisconnectObservation", "NBDInventoryObservation", "NBDReleaseModel",
]
