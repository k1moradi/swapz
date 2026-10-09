#!/usr/bin/env python3
"""Rootless adversarial tests of a SYNTHETIC (non-device) drain controller."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import os
import stat
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "swapz_mock_drain_controller", HERE / "recall-io-drain-orchestrator.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
Session = module.RootlessMockDrainSession
Ops = module.SyntheticFixtureOps
Denied = module.DrainDenied

NAMES = ("swapz-v22-recall-mock-upper", "swapz-v22-recall-mock-lower")
LOOP = "/dev/loop777"


class MockDrainLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swapz-mock-drain-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.marker = self.root / "synthetic-backing.marker"
        self.marker.write_text("keep synthetic marker unless fully attested", encoding="utf-8")
        self.marker.chmod(0o600)

    def session(self, *, faults=None, handles=None):
        ops = Ops(NAMES, LOOP, faults=faults, handles=handles)
        return Session(NAMES, LOOP, self.marker, ops=ops)

    def assert_preserved(self, session):
        with self.assertRaises((Denied, OSError)):
            session.run()
        self.assertTrue(self.marker.exists())
        self.assertFalse(session.policy.cleanup_allowed or session.completed)
        self.assertTrue(session.failed)
        previous_trace = tuple(session.ops.trace)
        with self.assertRaises(Denied):
            session.run()
        self.assertEqual(tuple(session.ops.trace), previous_trace)

    def test_full_mock_lifecycle_only_removes_synthetic_marker_at_end(self):
        session = self.session()
        self.assertTrue(self.marker.exists())
        self.assertTrue(session.run())
        self.assertFalse(self.marker.exists())
        self.assertTrue(session.completed)
        self.assertTrue(session.policy.cleanup_allowed)
        self.assertEqual(session.ops.trace, [
            "admission_closed", "workers_reaped", "swap_quiescent",
            "dm_suspended:" + NAMES[0],
            "dm_descriptors_closed:" + NAMES[0],
            "dm_open_count_zero:" + NAMES[0],
            "dm_removed:" + NAMES[0],
            "dm_absent:" + NAMES[0],
            "dm_suspended:" + NAMES[1],
            "dm_descriptors_closed:" + NAMES[1],
            "dm_open_count_zero:" + NAMES[1],
            "dm_removed:" + NAMES[1],
            "dm_absent:" + NAMES[1],
            "loop_dependencies_clear", "loop_detached",
        ])
        with self.assertRaises(Denied):
            session.run()

    def test_failure_at_every_stage_permanently_preserves_backing(self):
        for key in ("admission_closed", "workers_reaped", "swap_quiescent",
                    *(name + ":" + label for label in NAMES for name in (
                        "dm_suspended", "dm_descriptors_closed",
                        "dm_open_count_zero", "dm_removed", "dm_absent")),
                    "loop_dependencies_clear", "loop_detached"):
            with self.subTest(stage=key):
                self.marker.write_bytes(b"unchanged synthetic backing")
                fixture = self.session(faults={key: "mock timeout"})
                self.assert_preserved(fixture)
                self.assertEqual(fixture.ops.trace[-1], key)

    def test_missing_duplicate_or_extra_worker_inventory_denies(self):
        valid = {role: "handle-" + role for role in module.ROLES}
        for modified in (
            {key: value for key, value in valid.items() if key != "b2"},
            {**valid, "b2": valid["a"]},
            {**valid, "other": "handle-other"},
            {**valid, "b2": ""},
        ):
            with self.subTest(modified=modified):
                self.assert_preserved(self.session(handles=modified))

    def test_failed_swapoff_and_corrupt_swap_inventory_preserve(self):
        for change in (
            {"swapoff_succeeded": False}, {"swapoff_attempted": False},
            {"mapper_active_after": True}, {"inventory_valid": False},
            {"unexpected": True},
        ):
            with self.subTest(change=change):
                self.assert_preserved(self.session(faults={"swap_quiescent": change}))

    def test_missing_normal_suspend_and_noflush_are_denied(self):
        stage = "dm_suspended:" + NAMES[0]
        for change in (
            {"ioctl_succeeded": False}, {"ordinary_flush": False},
            {"noflush": True}, {"timed_out": True},
            {"identity_matches": False}, {"suspended": False},
        ):
            with self.subTest(change=change):
                self.assert_preserved(self.session(faults={stage: change}))

    def test_bad_descriptor_closure_open_count_and_holders_are_denied(self):
        cases = [
            ("dm_descriptors_closed:" + NAMES[0], {"all_closed": False}),
            ("dm_descriptors_closed:" + NAMES[0], {"close_errors_empty": False}),
            ("dm_open_count_zero:" + NAMES[0], {"open_count": 1}),
            ("dm_open_count_zero:" + NAMES[1], {"holders_empty": False}),
            ("dm_open_count_zero:" + NAMES[1], {"inventory_valid": False}),
        ]
        for stage, fault in cases:
            with self.subTest(stage=stage, fault=fault):
                self.assert_preserved(self.session(faults={stage: fault}))

    def test_force_deferred_false_remove_and_changed_dm_identity_denied(self):
        for stage, change in [
            ("dm_removed:" + NAMES[0], {"force": True}),
            ("dm_removed:" + NAMES[1], {"deferred": True}),
            ("dm_removed:" + NAMES[1], {"remove_succeeded": False}),
            ("dm_removed:" + NAMES[0], {"identity_matches": False}),
            ("dm_absent:" + NAMES[0], {"name_absent": False}),
            ("dm_absent:" + NAMES[1], {"uuid_absent": False}),
            ("dm_absent:" + NAMES[1], {"device_number_absent": False}),
            ("dm_absent:" + NAMES[0], {"all_rows_valid": False}),
        ]:
            with self.subTest(stage=stage, change=change):
                self.assert_preserved(self.session(faults={stage: change}))

    def test_upper_removed_but_lower_busy_leaves_marker(self):
        session = self.session()
        session.ops.dm[NAMES[1]]["open"] = 1
        self.assert_preserved(session)
        self.assertFalse(session.ops.dm[NAMES[0]]["present"])
        self.assertTrue(session.ops.dm[NAMES[1]]["present"])
        self.assertNotIn("loop_detached", session.ops.trace)

    def test_failed_loop_holder_inventory_and_detach_preserve(self):
        for stage, change in [
            ("loop_dependencies_clear", {"holder_inventory_valid": False}),
            ("loop_dependencies_clear", {"holders_empty": False}),
            ("loop_dependencies_clear", {"loop_identity_matches": False}),
            ("loop_detached", {"detach_succeeded": False}),
            ("loop_detached", {"exact_loop_absent": False}),
        ]:
            with self.subTest(stage=stage, change=change):
                self.assert_preserved(self.session(faults={stage: change}))

    def test_wrong_policy_identity_and_untrusted_operations_denied(self):
        ops = Ops(NAMES, LOOP)
        with self.assertRaises(Denied):
            Session(NAMES[::-1], LOOP, self.marker, ops=ops)
        with self.assertRaises(Denied):
            Session(NAMES, "/dev/loop123", self.marker, ops=ops)
        with self.assertRaises(Denied):
            Session(NAMES, LOOP, self.marker, ops=object())

    def test_backing_symlink_rejected_before_operation(self):
        replacement = self.root / "other"
        replacement.write_text("marker", encoding="utf-8")
        replacement.chmod(0o600)
        self.marker.unlink()
        self.marker.symlink_to(replacement)
        with self.assertRaises(Denied):
            self.session()
        self.assertTrue(self.marker.is_symlink())
        self.assertEqual(replacement.read_text(), "marker")

    def test_marker_replacement_after_binding_does_not_unlink(self):
        session = self.session()
        self.marker.rename(self.root / "previous")
        self.marker.write_bytes(b"replacement")
        self.marker.chmod(0o600)
        self.assert_preserved(session)
        self.assertTrue((self.root / "previous").exists())

    def test_unprivate_directory_and_multilink_marker_rejected(self):
        self.root.chmod(0o755)
        with self.assertRaises(Denied):
            self.session()
        self.root.chmod(0o700)
        os.link(self.marker, self.root / "other-hardlink")
        with self.assertRaises(Denied):
            self.session()

    def test_bool_and_missing_evidence_never_authorize(self):
        for value in (1, "true", None):
            with self.subTest(value=value):
                self.assert_preserved(self.session(
                    faults={"admission_closed": {"closed": value}}
                ))
        self.assert_preserved(self.session(
            faults={"dm_suspended:" + NAMES[0]: {"unexpected": True}}
        ))

    def test_no_live_device_interfaces_present(self):
        text = (HERE / "recall-io-drain-orchestrator.py").read_text(encoding="utf-8")
        for banned in ("subprocess", "dmsetup(", "losetup(", "swapon(", "swapoff(",
                       "ioctl(", "os.system(", "os.kill("):
            self.assertNotIn(banned, text)


if __name__ == "__main__":
    unittest.main()
