#!/usr/bin/env python3
"""Rootless adversarial tests for session-bound backing-release evidence."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "recall_fixture_release_policy_tested", HERE / "recall-fixture-release-policy.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load fixture release policy")
policy_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = policy_module
SPEC.loader.exec_module(policy_module)


class FixtureBackingReleaseTests(unittest.TestCase):
    SESSION = "0123456789abcdef0123456789abcdef"
    KEY = b"rootless test only session HMAC key 0123456789"
    HANDLE = "worker-A"
    IDENTITY = policy_module.DMIdentity(
        "swapz-v22-recall-test", "SWAPZ-TEST-UUID", 253, 77, "a" * 64,
    )
    LOOP = "/dev/loop17"

    def setUp(self) -> None:
        self.policy = self._new_policy()
        self.payloads = self._payloads()

    def _new_policy(self):
        return policy_module.FixtureBackingReleasePolicy(
            session_id=self.SESSION, key=self.KEY, dm_identities=(self.IDENTITY,),
            loop_device=self.LOOP, mapper_name=self.IDENTITY.name,
            expected_worker_handles=(self.HANDLE,),
        )

    @staticmethod
    def _base_identity(identity):
        return {
            "name": identity.name, "uuid": identity.uuid, "major": identity.major,
            "minor": identity.minor, "table_sha256": identity.table_sha256,
            "inventory_sha256": "b" * 64,
        }

    def _payloads(self):
        identity = self.IDENTITY
        ident = self._base_identity(identity)
        worker = [self.HANDLE]
        session = self.SESSION
        payloads = [
            ("admission_closed", {
                "session_id": session, "closed": True, "no_more_roles": True,
            }),
            ("workers_reaped", {
                "session_id": session, "inventory_complete": True, "all_reaped": True,
                "errors_empty": True, "worker_service_exit_status": 0,
                "expected_handles": worker, "reaped_handles": worker,
                "role_descriptors_closed": worker, "worker_errors": [],
            }),
            ("swap_quiescent", {
                "session_id": session, "inventory_valid": True,
                "mapper_active_before": True, "swapoff_attempted": True,
                "swapoff_succeeded": True, "mapper_active_after": False,
                "swap_inventory_sha256": "c" * 64,
                "mapper_swap_identity": {"name": identity.name, "uuid": identity.uuid,
                                          "major": identity.major, "minor": identity.minor},
            }),
            ("dm_suspended", {
                "session_id": session, **ident, "ioctl_succeeded": True,
                "ordinary_flush": True, "noflush": False, "timed_out": False,
                "identity_matches": True, "suspended": True, "pending_io_drained": True,
            }),
            ("dm_descriptors_closed", {
                "session_id": session, **ident, "all_closed": True,
                "close_errors_empty": True, "descriptor_owner_session_id": session,
            }),
            ("dm_open_count_zero", {
                "session_id": session, **ident, "inventory_valid": True,
                "identity_matches": True, "open_count": 0, "holders_empty": True,
                "holders": [],
            }),
            ("dm_removed", {
                "session_id": session, **ident, "remove_succeeded": True,
                "normal_remove": True, "force": False, "deferred": False,
                "identity_matches": True,
            }),
            ("dm_absent", {
                "session_id": session, **ident, "inventory_valid": True,
                "all_rows_valid": True, "name_absent": True, "uuid_absent": True,
                "device_number_absent": True,
                "fixture_owner_release": {
                    "session_id": session, "name": identity.name, "uuid": identity.uuid,
                    "major": identity.major, "minor": identity.minor,
                    "table_sha256": identity.table_sha256, "normal_remove": True,
                    "disappearance_verified": True, "lease_released": True,
                },
            }),
            ("loop_dependencies_clear", {
                "session_id": session, "dm_stack_absent": True,
                "holder_inventory_valid": True, "holders_empty": True,
                "loop_identity_matches": True, "loop_device": self.LOOP,
                "dm_names_absent": [identity.name], "holder_inventory_sha256": "d" * 64,
            }),
            ("loop_detached", {
                "session_id": session, "detach_succeeded": True, "normal_detach": True,
                "inventory_valid": True, "exact_loop_absent": True,
                "loop_device": self.LOOP, "loop_inventory_sha256": "e" * 64,
            }),
        ]
        return payloads

    def _envelope(self, sequence: int, event: str, payload: dict, *,
                  session_id: str | None = None, mac: bytes | None = None,
                  raw_payload: bytes | None = None, sequence_override: int | None = None):
        actual_session = self.SESSION if session_id is None else session_id
        encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=True, allow_nan=False).encode("ascii")
                   if raw_payload is None else raw_payload)
        actual_sequence = sequence if sequence_override is None else sequence_override
        signature = policy_module.evidence_mac(
            self.KEY, actual_session, actual_sequence, event, encoded,
        ) if mac is None else mac
        return policy_module.AuthenticatedDrainEvidence(
            actual_session, actual_sequence, event, encoded, signature,
        )

    def _send_prefix(self, count: int) -> None:
        for sequence, (event, payload) in enumerate(self.payloads[:count]):
            self.policy.submit(self._envelope(sequence, event, payload))

    def _finish(self) -> None:
        start = len(self.policy.events)
        for sequence, (event, payload) in enumerate(self.payloads[start:], start):
            self.policy.submit(self._envelope(sequence, event, payload))

    def test_complete_authenticated_sequence_authorizes_only_backing_release(self):
        self.assertTrue(self.policy.backing_must_be_preserved)
        self._finish()
        self.assertTrue(self.policy.backing_release_authorized)
        self.assertFalse(self.policy.backing_must_be_preserved)
        self.assertFalse(hasattr(self.policy, "cleanup_allowed"))
        self.assertEqual(len(self.policy.events), len(self.payloads))

    def test_session_sequence_mac_and_canonical_json_are_mandatory(self):
        cases = ("foreign-session", "replayed-sequence", "wrong-mac", "noncanonical-json", "duplicate-json-key")
        for case in cases:
            with self.subTest(case=case):
                policy = self._new_policy()
                event, payload = self.payloads[0]
                if case == "foreign-session":
                    evidence = self._envelope(0, event, payload, session_id="f" * 32)
                elif case == "replayed-sequence":
                    evidence = self._envelope(0, event, payload)
                    policy.submit(evidence)
                    with self.assertRaises(policy_module.DrainEvidenceDenied):
                        policy.submit(evidence)
                    self.assertTrue(policy.backing_must_be_preserved)
                    continue
                elif case == "wrong-mac":
                    evidence = self._envelope(0, event, payload, mac=b"x" * 32)
                elif case == "noncanonical-json":
                    raw = json.dumps(payload, sort_keys=False, indent=1).encode()
                    evidence = self._envelope(0, event, payload, raw_payload=raw)
                else:
                    raw = b'{"session_id":"' + self.SESSION.encode() + b'","closed":true,"closed":true,"no_more_roles":true}'
                    evidence = self._envelope(0, event, payload, raw_payload=raw)
                with self.assertRaises(policy_module.DrainEvidenceDenied):
                    policy.submit(evidence)
                self.assertFalse(policy.backing_release_authorized)
                self.assertTrue(policy.backing_must_be_preserved)

    def test_wrong_event_and_missing_finalization_cannot_authorize(self):
        with self.assertRaises(policy_module.DrainEvidenceDenied):
            self.policy.submit(self._envelope(0, "workers_reaped", self.payloads[1][1]))
        self.assertFalse(self.policy.backing_release_authorized)
        self.assertTrue(self.policy.backing_must_be_preserved)
        incomplete = self._new_policy()
        for sequence, (event, payload) in enumerate(self.payloads[:-1]):
            incomplete.submit(self._envelope(sequence, event, payload))
        self.assertFalse(incomplete.backing_release_authorized)
        self.assertTrue(incomplete.backing_must_be_preserved)

    def test_adversarial_worker_swap_suspend_open_count_remove_and_owner_receipts(self):
        cases = (
            (1, "reaped_handles", []),
            (1, "role_descriptors_closed", []),
            (1, "worker_service_exit_status", 1),
            (1, "inventory_complete", False),
            (1, "all_reaped", False),
            (1, "errors_empty", False),
            (2, "inventory_valid", False),
            (2, "swapoff_attempted", False),
            (2, "swapoff_succeeded", False),
            (3, "ioctl_succeeded", False),
            (3, "ordinary_flush", False),
            (2, "mapper_active_after", True),
            (3, "timed_out", True),
            (3, "identity_matches", False),
            (3, "suspended", False),
            (3, "noflush", True),
            (3, "pending_io_drained", False),
            (4, "all_closed", False),
            (4, "close_errors_empty", False),
            (5, "inventory_valid", False),
            (5, "identity_matches", False),
            (5, "open_count", 1),
            (5, "holders", ["dm-253:80"]),
            (5, "holders_empty", False),
            (6, "remove_succeeded", False),
            (6, "normal_remove", False),
            (6, "force", True),
            (6, "deferred", True),
            (6, "identity_matches", False),
            (7, "fixture_owner_release", None),
            (7, "inventory_valid", False),
            (7, "all_rows_valid", False),
            (7, "name_absent", False),
            (7, "device_number_absent", False),
            (7, "uuid", "SWAPZ-STALE"),
            (8, "dm_stack_absent", False),
            (8, "holder_inventory_valid", False),
            (8, "holders_empty", False),
            (8, "loop_identity_matches", False),
            (9, "detach_succeeded", False),
            (9, "normal_detach", False),
            (9, "inventory_valid", False),
            (9, "exact_loop_absent", False),
        )
        for index, key, bad_value in cases:
            with self.subTest(index=index, key=key):
                policy = self._new_policy()
                for sequence, (event, payload) in enumerate(self.payloads[:index]):
                    policy.submit(self._envelope(sequence, event, payload))
                event, payload = self.payloads[index]
                changed = copy.deepcopy(payload)
                changed[key] = bad_value
                with self.assertRaises(policy_module.DrainEvidenceDenied):
                    policy.submit(self._envelope(index, event, changed))
                self.assertTrue(policy.backing_must_be_preserved)
                self.assertFalse(policy.backing_release_authorized)

    def test_unknown_identity_and_unavailable_session_key_are_rejected(self):
        with self.assertRaises(policy_module.DrainEvidenceDenied):
            self._new_policy().__class__(
                session_id=self.SESSION, key=b"x", dm_identities=(self.IDENTITY,),
                loop_device=self.LOOP, mapper_name=self.IDENTITY.name,
                expected_worker_handles=(self.HANDLE,),
            )
        with self.assertRaises(policy_module.DrainEvidenceDenied):
            policy_module.FixtureBackingReleasePolicy(
                session_id=self.SESSION, key=self.KEY,
                dm_identities=(self.IDENTITY, self.IDENTITY), loop_device=self.LOOP,
                mapper_name=self.IDENTITY.name, expected_worker_handles=(self.HANDLE,),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
