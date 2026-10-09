#!/usr/bin/env python3
"""Rootless validator for authenticated, session-bound backing-release evidence.

This module performs no system, swap, DM, loop, NBD, or filesystem operations.
Its HMAC key is supplied by a future trusted fixture owner; tests use a
disposable in-memory key and do not establish a production trust boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
_DRAIN_SPEC = importlib.util.spec_from_file_location(
    "swapz_fixture_release_drain_policy", HERE / "recall-io-drain-policy.py",
)
if _DRAIN_SPEC is None or _DRAIN_SPEC.loader is None:
    raise RuntimeError("cannot load the ordinary DM drain policy model")
_DRAIN_MODULE = importlib.util.module_from_spec(_DRAIN_SPEC)
sys.modules[_DRAIN_SPEC.name] = _DRAIN_MODULE
_DRAIN_SPEC.loader.exec_module(_DRAIN_MODULE)


class DrainEvidenceDenied(RuntimeError):
    """Backing release cannot be authorized from these observations."""


@dataclass(frozen=True)
class DMIdentity:
    name: str
    uuid: str
    major: int
    minor: int
    table_sha256: str


@dataclass(frozen=True)
class AuthenticatedDrainEvidence:
    session_id: str
    sequence: int
    event: str
    payload: bytes
    authenticator: bytes


def evidence_mac(key: bytes, session_id: str, sequence: int,
                 event: str, payload: bytes) -> bytes:
    """Canonical HMAC helper for the trusted fixture-owner process only."""
    if type(key) is not bytes or len(key) < 32:
        raise DrainEvidenceDenied("fixture-owner evidence key is unavailable")
    if type(payload) is not bytes:
        raise DrainEvidenceDenied("drain evidence payload must be bytes")
    head = json.dumps({"session_id": session_id, "sequence": sequence,
                       "event": event}, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")
    return hmac.new(key, head + b"\n" + payload, hashlib.sha256).digest()


class FixtureBackingReleasePolicy:
    """Require signed, ordered, exact evidence before backing-file release.

    The session key must remain inside the separately privileged fixture owner
    and must never arrive from worker IPC. This class validates a complete
    authenticated report; it does not collect or independently prove kernel
    observations. A rootless model PASS is not real DM/loop drain evidence.
    """

    def __init__(self, *, session_id: str, key: bytes,
                 dm_identities: tuple[DMIdentity, ...], loop_device: str,
                 mapper_name: str, expected_worker_handles: tuple[str, ...]) -> None:
        if (type(session_id) is not str or re.fullmatch(r"[0-9a-f]{32}", session_id) is None
                or type(key) is not bytes or len(key) < 32):
            raise DrainEvidenceDenied("trusted session identity or key is unavailable")
        if (type(dm_identities) is not tuple or not dm_identities
                or any(type(identity) is not DMIdentity for identity in dm_identities)
                or len({item.name for item in dm_identities}) != len(dm_identities)
                or len({item.uuid for item in dm_identities}) != len(dm_identities)
                or len({(item.major, item.minor) for item in dm_identities}) != len(dm_identities)
                or mapper_name not in {item.name for item in dm_identities}
                or type(loop_device) is not str
                or re.fullmatch(r"/dev/loop[0-9]+", loop_device) is None):
            raise DrainEvidenceDenied("fixture DM or loop identity is malformed")
        for identity in dm_identities:
            if (re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}", identity.name) is None
                    or type(identity.uuid) is not str or not identity.uuid
                    or type(identity.major) is not int or not 0 <= identity.major <= 4095
                    or type(identity.minor) is not int or not 0 <= identity.minor <= 1048575
                    or type(identity.table_sha256) is not str
                    or re.fullmatch(r"[0-9a-f]{64}", identity.table_sha256) is None):
                raise DrainEvidenceDenied("fixture DM identity is malformed")
        if (type(expected_worker_handles) is not tuple
                or any(type(handle) is not str
                       or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", handle) is None
                       or handle.isdecimal() for handle in expected_worker_handles)
                or len(set(expected_worker_handles)) != len(expected_worker_handles)):
            raise DrainEvidenceDenied("expected worker handle inventory is malformed")

        self.session_id = session_id
        self._key = key
        self.dm_identities = dm_identities
        self.loop_device = loop_device
        self.mapper_name = mapper_name
        self.expected_worker_handles = expected_worker_handles
        self._policy = _DRAIN_MODULE.DMIODrainPolicy(
            tuple(item.name for item in dm_identities), loop_device,
        )
        self._events: list[str] = []
        self._expected_events = ["admission_closed", "workers_reaped", "swap_quiescent"]
        for identity in dm_identities:
            self._expected_events.extend((
                f"dm_suspended:{identity.name}",
                f"dm_descriptors_closed:{identity.name}",
                f"dm_open_count_zero:{identity.name}",
                f"dm_removed:{identity.name}",
                f"dm_absent:{identity.name}",
            ))
        self._expected_events.extend(("loop_dependencies_clear", "loop_detached"))
        self._denial: str | None = None

    @property
    def backing_release_authorized(self) -> bool:
        return (self._denial is None and len(self._events) == len(self._expected_events)
                and self._policy.cleanup_allowed)

    @property
    def backing_must_be_preserved(self) -> bool:
        return not self.backing_release_authorized

    @property
    def denial(self) -> str | None:
        return self._denial

    @property
    def events(self) -> tuple[str, ...]:
        return tuple(self._events)

    def submit(self, evidence: AuthenticatedDrainEvidence) -> None:
        if self._denial is not None:
            raise DrainEvidenceDenied(f"backing preservation is latched: {self._denial}")
        try:
            self._submit(evidence)
        except Exception as exc:
            self._denial = str(exc) or type(exc).__name__
            if isinstance(exc, DrainEvidenceDenied):
                raise
            raise DrainEvidenceDenied(self._denial) from exc

    def _submit(self, evidence: AuthenticatedDrainEvidence) -> None:
        if type(evidence) is not AuthenticatedDrainEvidence:
            raise DrainEvidenceDenied("drain evidence is not the typed session envelope")
        sequence = len(self._events)
        if (type(evidence.session_id) is not str or evidence.session_id != self.session_id
                or type(evidence.sequence) is not int or evidence.sequence != sequence
                or sequence >= len(self._expected_events)
                or type(evidence.event) is not str
                or type(evidence.payload) is not bytes
                or type(evidence.authenticator) is not bytes
                or len(evidence.authenticator) != 32):
            raise DrainEvidenceDenied("evidence session, sequence, or envelope is invalid")
        expected_label = self._expected_events[sequence]
        if evidence.event != expected_label.split(":", 1)[0]:
            raise DrainEvidenceDenied("evidence event is missing, repeated, or out of order")
        expected_mac = evidence_mac(
            self._key, evidence.session_id, evidence.sequence, evidence.event, evidence.payload,
        )
        if not hmac.compare_digest(evidence.authenticator, expected_mac):
            raise DrainEvidenceDenied("drain evidence authentication failed")
        payload = json.loads(evidence.payload, object_pairs_hook=self._unique_object)
        if type(payload) is not dict:
            raise DrainEvidenceDenied("drain evidence payload must be an object")
        if json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii") != evidence.payload:
            raise DrainEvidenceDenied("drain evidence payload is not canonical JSON")
        stripped = self._validate_context(evidence.event, expected_label, payload)
        self._policy.observe(evidence.event, stripped)
        self._events.append(expected_label)

    @staticmethod
    def _unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise DrainEvidenceDenied(f"duplicate drain evidence key: {key}")
            value[key] = item
        return value

    def _validate_context(self, event: str, label: str,
                          payload: dict[str, Any]) -> dict[str, object]:
        if payload.get("session_id") != self.session_id:
            raise DrainEvidenceDenied("payload belongs to a different fixture session")
        if event == "admission_closed":
            self._exact_context(payload, {"session_id", "closed", "no_more_roles"})
            if payload["closed"] is not True or payload["no_more_roles"] is not True:
                raise DrainEvidenceDenied("worker admission is not positively closed")
            return {"closed": True}
        if event == "workers_reaped":
            self._exact_context(payload, {
                "session_id", "inventory_complete", "all_reaped", "errors_empty",
                "worker_service_exit_status", "expected_handles", "reaped_handles",
                "role_descriptors_closed", "worker_errors",
            })
            expected = list(self.expected_worker_handles)
            if (payload["worker_service_exit_status"] != 0
                    or type(payload["worker_service_exit_status"]) is not int
                    or payload["expected_handles"] != expected
                    or payload["reaped_handles"] != expected
                    or payload["role_descriptors_closed"] != expected
                    or payload["worker_errors"] != []):
                raise DrainEvidenceDenied("worker exit or complete reaped/descriptor inventory is invalid")
            return {key: payload[key] for key in (
                "inventory_complete", "all_reaped", "errors_empty",
            )}
        if event == "swap_quiescent":
            self._exact_context(payload, {
                "session_id", "inventory_valid", "mapper_active_before", "swapoff_attempted",
                "swapoff_succeeded", "mapper_active_after", "swap_inventory_sha256",
                "mapper_swap_identity",
            })
            if (type(payload["swap_inventory_sha256"]) is not str
                    or re.fullmatch(r"[0-9a-f]{64}", payload["swap_inventory_sha256"]) is None
                    or payload["mapper_swap_identity"] != self._identity_dict(
                        self._identity_for(self.mapper_name))):
                raise DrainEvidenceDenied("active-swap evidence is not bound to the fixture mapper")
            return {key: payload[key] for key in (
                "inventory_valid", "mapper_active_before", "swapoff_attempted",
                "swapoff_succeeded", "mapper_active_after",
            )}
        if event.startswith("dm_"):
            name = label.split(":", 1)[1]
            identity = self._identity_for(name)
            common = {
                "session_id", "name", "uuid", "major", "minor", "table_sha256",
                "inventory_sha256",
            }
            if (payload.get("name") != identity.name or payload.get("uuid") != identity.uuid
                    or type(payload.get("major")) is not int or payload["major"] != identity.major
                    or type(payload.get("minor")) is not int or payload["minor"] != identity.minor
                    or payload.get("table_sha256") != identity.table_sha256
                    or type(payload.get("inventory_sha256")) is not str
                    or re.fullmatch(r"[0-9a-f]{64}", payload["inventory_sha256"]) is None):
                raise DrainEvidenceDenied("DM observation is stale or belongs to another identity")
            if event == "dm_suspended":
                self._exact_context(payload, common | {
                    "ioctl_succeeded", "ordinary_flush", "noflush", "timed_out",
                    "identity_matches", "suspended", "pending_io_drained",
                })
                if payload["pending_io_drained"] is not True:
                    raise DrainEvidenceDenied("kernel DM suspend did not attest drained mapped I/O")
                return self._dm_base(payload, "suspend")
            if event == "dm_descriptors_closed":
                self._exact_context(payload, common | {
                    "all_closed", "close_errors_empty", "descriptor_owner_session_id",
                })
                if payload["descriptor_owner_session_id"] != self.session_id:
                    raise DrainEvidenceDenied("DM descriptor closure belongs to another owner session")
                return self._dm_base(payload, "descriptors")
            if event == "dm_open_count_zero":
                self._exact_context(payload, common | {
                    "inventory_valid", "identity_matches", "open_count", "holders_empty", "holders",
                })
                if payload["holders"] != []:
                    raise DrainEvidenceDenied("DM holder list is not empty")
                return self._dm_base(payload, "openers")
            if event == "dm_removed":
                self._exact_context(payload, common | {
                    "remove_succeeded", "normal_remove", "force", "deferred", "identity_matches",
                })
                return self._dm_base(payload, "removed")
            if event == "dm_absent":
                fields = common | {
                    "inventory_valid", "all_rows_valid", "name_absent", "uuid_absent", "device_number_absent",
                    "fixture_owner_release",
                }
                self._exact_context(payload, fields)
                owner_release = payload["fixture_owner_release"]
                if name == self.mapper_name:
                    expected_owner_release = {
                        "session_id": self.session_id, "name": identity.name,
                        "uuid": identity.uuid, "major": identity.major, "minor": identity.minor,
                        "table_sha256": identity.table_sha256, "normal_remove": True,
                        "disappearance_verified": True, "lease_released": True,
                    }
                    if owner_release != expected_owner_release:
                        raise DrainEvidenceDenied("mapper-only owner release receipt is missing or contradictory")
                elif owner_release is not None:
                    raise DrainEvidenceDenied("mapper owner receipt was attached to a different DM layer")
                return self._dm_base(payload, "absent")
        if event == "loop_dependencies_clear":
            self._exact_context(payload, {
                "session_id", "dm_stack_absent", "holder_inventory_valid", "holders_empty",
                "loop_identity_matches", "loop_device", "dm_names_absent", "holder_inventory_sha256",
            })
            if (payload["loop_device"] != self.loop_device
                    or payload["dm_names_absent"] != [item.name for item in self.dm_identities]
                    or type(payload["holder_inventory_sha256"]) is not str
                    or re.fullmatch(r"[0-9a-f]{64}", payload["holder_inventory_sha256"]) is None):
                raise DrainEvidenceDenied("loop holder or dependent-stack inventory is not bound")
            return {key: payload[key] for key in (
                "dm_stack_absent", "holder_inventory_valid", "holders_empty", "loop_identity_matches",
            )}
        if event == "loop_detached":
            self._exact_context(payload, {
                "session_id", "detach_succeeded", "normal_detach", "inventory_valid",
                "exact_loop_absent", "loop_device", "loop_inventory_sha256",
            })
            if (payload["loop_device"] != self.loop_device
                    or type(payload["loop_inventory_sha256"]) is not str
                    or re.fullmatch(r"[0-9a-f]{64}", payload["loop_inventory_sha256"]) is None):
                raise DrainEvidenceDenied("loop detach result is not bound to exact loop inventory")
            return {key: payload[key] for key in (
                "detach_succeeded", "normal_detach", "inventory_valid", "exact_loop_absent",
            )}
        raise DrainEvidenceDenied(f"unsupported authenticated drain event: {event}")

    def _dm_base(self, payload: dict[str, Any], kind: str) -> dict[str, object]:
        if kind == "suspend":
            keys = ("ioctl_succeeded", "ordinary_flush", "noflush", "timed_out",
                    "identity_matches", "suspended")
        elif kind == "descriptors":
            keys = ("all_closed", "close_errors_empty")
        elif kind == "openers":
            keys = ("inventory_valid", "identity_matches", "open_count", "holders_empty")
        elif kind == "removed":
            keys = ("remove_succeeded", "normal_remove", "force", "deferred", "identity_matches")
        elif kind == "absent":
            keys = ("inventory_valid", "all_rows_valid", "name_absent", "uuid_absent",
                    "device_number_absent")
        else:
            raise DrainEvidenceDenied("unsupported DM evidence type")
        result = {key: payload[key] for key in keys}
        result["name"] = payload["name"]
        return result

    @staticmethod
    def _exact_context(payload: dict[str, Any], expected: set[str]) -> None:
        if set(payload) != expected:
            raise DrainEvidenceDenied("evidence payload has missing or unexpected fields")

    def _identity_for(self, name: str) -> DMIdentity:
        matches = [identity for identity in self.dm_identities if identity.name == name]
        if len(matches) != 1:
            raise DrainEvidenceDenied("DM evidence name is not in the fixture's exact stack")
        return matches[0]

    @staticmethod
    def _identity_dict(identity: DMIdentity) -> dict[str, object]:
        return {"name": identity.name, "uuid": identity.uuid, "major": identity.major,
                "minor": identity.minor}


__all__ = [
    "AuthenticatedDrainEvidence", "DMIdentity", "DrainEvidenceDenied",
    "FixtureBackingReleasePolicy", "evidence_mac",
]
