#!/usr/bin/env python3
"""Rootless adversarial tests for the offline DM I/O-drain policy model."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "recall_io_drain_policy", HERE / "recall-io-drain-policy.py",
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)
DMIODrainPolicy = module.DMIODrainPolicy
DrainDenied = module.DrainDenied


class DMIODrainPolicyTests(unittest.TestCase):
    names = ("swapz-v22-recall-upper", "swapz-v22-recall-lower")
    loop = "/dev/loop77"

    def events(self):
        result = [
            ("admission_closed", {"closed": True}),
            ("workers_reaped", {
                "inventory_complete": True, "all_reaped": True, "errors_empty": True,
            }),
            ("swap_quiescent", {
                "inventory_valid": True, "mapper_active_before": False,
                "swapoff_attempted": False, "swapoff_succeeded": False,
                "mapper_active_after": False,
            }),
        ]
        for name in self.names:
            result.extend((
                ("dm_suspended", {
                    "name": name, "ioctl_succeeded": True, "ordinary_flush": True,
                    "noflush": False, "timed_out": False,
                    "identity_matches": True, "suspended": True,
                }),
                ("dm_descriptors_closed", {
                    "name": name, "all_closed": True, "close_errors_empty": True,
                }),
                ("dm_open_count_zero", {
                    "name": name, "inventory_valid": True,
                    "identity_matches": True, "open_count": 0, "holders_empty": True,
                }),
                ("dm_removed", {
                    "name": name, "remove_succeeded": True, "normal_remove": True,
                    "force": False, "deferred": False, "identity_matches": True,
                }),
                ("dm_absent", {
                    "name": name, "inventory_valid": True, "all_rows_valid": True,
                    "name_absent": True, "uuid_absent": True,
                    "device_number_absent": True,
                }),
            ))
        result.extend((
            ("loop_dependencies_clear", {
                "dm_stack_absent": True, "holder_inventory_valid": True,
                "holders_empty": True, "loop_identity_matches": True,
            }),
            ("loop_detached", {
                "detach_succeeded": True, "normal_detach": True,
                "inventory_valid": True, "exact_loop_absent": True,
            }),
        ))
        return result

    def test_positive_upper_to_lower_drain_permits_cleanup_only_at_end(self):
        policy = DMIODrainPolicy(self.names, self.loop)
        for index, (event, evidence) in enumerate(self.events()):
            self.assertFalse(policy.cleanup_allowed, f"early authorization before {event} #{index}")
            self.assertTrue(policy.preserve_backing)
            policy.observe(event, evidence)
        self.assertTrue(policy.cleanup_allowed)
        self.assertFalse(policy.preserve_backing)
        self.assertEqual(policy.events[3], "dm_suspended:" + self.names[0])
        self.assertEqual(policy.events[7], "dm_absent:" + self.names[0])
        self.assertEqual(policy.events[-1], "loop_detached")
        with self.assertRaises(DrainDenied):
            policy.observe("loop_detached", dict(self.events()[-1][1]))
        self.assertFalse(policy.cleanup_allowed)

    def test_every_stage_failure_is_sticky_and_never_authorizes_later_cleanup(self):
        positive = self.events()
        for failed_index, (event, evidence) in enumerate(positive):
            with self.subTest(event=event, index=failed_index):
                policy = DMIODrainPolicy(self.names, self.loop)
                for previous_event, previous_evidence in positive[:failed_index]:
                    policy.observe(previous_event, previous_evidence)
                broken = dict(evidence)
                candidates = [key for key, value in broken.items()
                              if key != "name" and type(value) is bool and value is True]
                if candidates:
                    broken[candidates[0]] = False
                elif "open_count" in broken:
                    broken["open_count"] = 1
                else:
                    broken.pop(next(key for key in broken if key != "name"))
                with self.assertRaises(DrainDenied):
                    policy.observe(event, broken)
                self.assertFalse(policy.cleanup_allowed)
                self.assertTrue(policy.preserve_backing)
                with self.assertRaisesRegex(DrainDenied, "permanently denied"):
                    policy.observe(*positive[-1])
                self.assertFalse(policy.cleanup_allowed)

    def test_swapoff_must_succeed_and_active_swap_must_be_absent(self):
        policy = DMIODrainPolicy((self.names[0],), self.loop)
        policy.observe("admission_closed", {"closed": True})
        policy.observe("workers_reaped", {
            "inventory_complete": True, "all_reaped": True, "errors_empty": True,
        })
        with self.assertRaisesRegex(DrainDenied, "disabled"):
            policy.observe("swap_quiescent", {
                "inventory_valid": True, "mapper_active_before": True,
                "swapoff_attempted": True, "swapoff_succeeded": False,
                "mapper_active_after": False,
            })

    def test_swap_inventory_error_or_contradictory_state_denies(self):
        for evidence in (
            {"inventory_valid": False, "mapper_active_before": False,
             "swapoff_attempted": False, "swapoff_succeeded": False,
             "mapper_active_after": False},
            {"inventory_valid": True, "mapper_active_before": False,
             "swapoff_attempted": True, "swapoff_succeeded": True,
             "mapper_active_after": False},
            {"inventory_valid": True, "mapper_active_before": False,
             "swapoff_attempted": False, "swapoff_succeeded": False,
             "mapper_active_after": True},
        ):
            policy = DMIODrainPolicy((self.names[0],), self.loop)
            policy.observe("admission_closed", {"closed": True})
            policy.observe("workers_reaped", {
                "inventory_complete": True, "all_reaped": True, "errors_empty": True,
            })
            with self.subTest(evidence=evidence), self.assertRaises(DrainDenied):
                policy.observe("swap_quiescent", evidence)

    def test_wrong_order_unknown_missing_and_extra_evidence_fail_closed(self):
        for event, evidence in (
            ("workers_reaped", {"inventory_complete": True,
                                 "all_reaped": True, "errors_empty": True}),
            ("admission_closed", {}),
            ("admission_closed", {"closed": True, "pid": 101}),
        ):
            policy = DMIODrainPolicy((self.names[0],), self.loop)
            with self.subTest(event=event, evidence=evidence), self.assertRaises(DrainDenied):
                policy.observe(event, evidence)
            with self.assertRaises(DrainDenied):
                policy.observe("admission_closed", {"closed": True})

    def test_malformed_stack_and_loop_identities_are_rejected(self):
        for dm_names, loop in (("swapz-upper", self.loop), ((), self.loop),
                               (("swapz-upper", "swapz-upper"), self.loop),
                               (("../mapper",), self.loop), (("swapz-upper",), "/dev/sda")):
            with self.subTest(dm_names=dm_names, loop=loop), self.assertRaises(DrainDenied):
                DMIODrainPolicy(dm_names, loop)

    def test_noflush_force_deferred_and_timeout_are_rejected(self):
        for key, value in (("noflush", True), ("timed_out", True)):
            policy = DMIODrainPolicy((self.names[0],), self.loop)
            for event, evidence in self.events()[:3]:
                policy.observe(event, evidence)
            evidence = {
                "name": self.names[0], "ioctl_succeeded": True,
                "ordinary_flush": True, "noflush": False,
                "timed_out": False, "identity_matches": True, "suspended": True,
            }
            evidence[key] = value
            with self.subTest(key=key), self.assertRaises(DrainDenied):
                policy.observe("dm_suspended", evidence)

        for key in ("force", "deferred"):
            policy = DMIODrainPolicy((self.names[0],), self.loop)
            for event, evidence in self.events()[:6]:
                policy.observe(event, evidence)
            evidence = {
                "name": self.names[0], "remove_succeeded": True,
                "normal_remove": True, "force": False,
                "deferred": False, "identity_matches": True,
            }
            evidence[key] = True
            with self.subTest(key=key), self.assertRaises(DrainDenied):
                policy.observe("dm_removed", evidence)

    def test_missing_mapping_inventory_or_loop_holder_inspection_denies(self):
        events = self.events()
        # Stop after the upper mapping's successful remove and inject a malformed
        # inventory; no lower mapping or loop release can then be authorized.
        policy = DMIODrainPolicy(self.names, self.loop)
        for event, evidence in events[:7]:
            policy.observe(event, evidence)
        bad_absence = dict(events[7][1])
        bad_absence["all_rows_valid"] = False
        with self.assertRaises(DrainDenied):
            policy.observe("dm_absent", bad_absence)
        self.assertFalse(policy.cleanup_allowed)

        policy = DMIODrainPolicy((self.names[0],), self.loop)
        for event, evidence in self.events()[:8]:
            if event == "dm_absent":
                evidence = dict(evidence, name_absent=False)
                with self.assertRaises(DrainDenied):
                    policy.observe(event, evidence)
                break
            else:
                policy.observe(event, evidence)


if __name__ == "__main__":
    unittest.main()
