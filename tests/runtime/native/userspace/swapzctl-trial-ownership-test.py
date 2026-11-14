#!/usr/bin/env python3
"""Rootless adversarial fixtures for the existing private trial helper.

All privileged and DM/swap operations are mocked. These tests do not grant
swapzctl a lifecycle API or certify live-device ownership.
"""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[3] / "tools/physical-swap-probe.py"
SPEC = importlib.util.spec_from_file_location("swapz_trial_helper", SOURCE)
assert SPEC is not None and SPEC.loader is not None
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


class TrialOwnershipTest(unittest.TestCase):
    """Model an owned /run journal without any real device or root access."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="swapz-trial-fixture-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.partuuid = "a" * 32
        self.run_id = "b" * 32
        self.state_dir = self.base / f"swapz-physical-{self.run_id}"
        self.state_dir.mkdir(mode=0o700)
        self.marker = self.base / f"partition-{self.partuuid}.active"
        self.state = {
            "run_id": self.run_id,
            "partuuid": self.partuuid,
            "major": 8,
            "minor": 4,
            "development_only": True,
            "algorithm_real_swap": True,
            "ownership_phase": helper.RUNTIME_OWNERSHIP_PHASE,
            "device_arg": f"/dev/disk/by-partuuid/{self.partuuid}",
        }
        self.save_state()
        self.save_marker()

        # The fixture uses a temporary directory owned by the current user.
        # Fake only its marker's stat UID to model a root-owned 0600 record.
        actual_lstat = Path.lstat

        def marker_lstat(path):
            info = actual_lstat(path)
            if Path(path) == self.marker:
                return SimpleNamespace(st_mode=info.st_mode, st_uid=0,
                                       st_nlink=info.st_nlink)
            return info

        for patcher in (
            mock.patch.object(helper, "ALGORITHM_RUNTIME_BASE", self.base),
            mock.patch.object(helper, "_algorithm_runtime_base", return_value=self.base),
            mock.patch.object(helper, "_validate_state_dir", return_value=None),
            mock.patch.object(Path, "lstat", marker_lstat),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.recover = mock.Mock(return_value={"stage": "COMPLETE"})
        patcher = mock.patch.object(helper, "recover", self.recover)
        patcher.start()
        self.addCleanup(patcher.stop)

    def save_state(self):
        (self.state_dir / "state.json").write_text(json.dumps(self.state))

    def save_marker(self, marker=None):
        record = marker if marker is not None else {
            "run_id": self.run_id,
            "partuuid": self.partuuid,
            "major": 8,
            "minor": 4,
        }
        self.marker.write_text(json.dumps(record))
        os.chmod(self.marker, stat.S_IRUSR | stat.S_IWUSR)

    def invoke(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return helper.recover_pending_algorithm_trial()

    def test_exact_journal_delegates_only_to_existing_recover(self):
        self.assertTrue(self.invoke())
        self.recover.assert_called_once_with(
            self.state_dir, self.state["device_arg"], self.state["device_arg"])

    def test_absent_or_multiple_markers_never_adopts_a_mapper(self):
        self.marker.unlink()
        self.assertFalse(self.invoke())
        self.recover.assert_not_called()
        self.save_marker()
        (self.base / ("partition-" + "c" * 32 + ".active")).write_text("{}")
        with self.assertRaises(helper.RecoveryRequiredError):
            self.invoke()
        self.recover.assert_not_called()

    def test_symlink_marker_is_refused(self):
        self.marker.unlink()
        self.marker.symlink_to(self.state_dir / "state.json")
        with self.assertRaises(helper.RecoveryRequiredError):
            self.invoke()
        self.recover.assert_not_called()

    def test_marker_or_journal_mismatch_fails_closed(self):
        for changed_field, changed_value in (
            ("run_id", "c" * 32),
            ("partuuid", "d" * 32),
            ("major", 9),
            ("development_only", False),
            ("algorithm_real_swap", False),
            ("ownership_phase", "UNKNOWN"),
            ("device_arg", "/dev/mapper/fake"),
        ):
            with self.subTest(field=changed_field):
                original = self.state[changed_field]
                self.state[changed_field] = changed_value
                self.save_state()
                with self.assertRaises(helper.RecoveryRequiredError):
                    self.invoke()
                self.state[changed_field] = original
                self.save_state()
        self.recover.assert_not_called()

    def test_failed_or_incomplete_delegate_is_not_success(self):
        self.recover.side_effect = helper.ProbeError("swapoff failed: ENOMEM")
        with self.assertRaises(helper.RecoveryRequiredError):
            self.invoke()
        self.recover.side_effect = None
        self.recover.return_value = {"stage": "RECOVERY_REQUIRED"}
        with self.assertRaises(helper.RecoveryRequiredError):
            self.invoke()

    def test_immutable_recovery_binding_rejects_mapper_and_source_drift(self):
        original = {key: "fixed" for key, _ in helper.RECOVERY_RECORD_BINDINGS}
        original["raw_header_preservation_required"] = True
        self.assertTrue(helper._recovery_state_identity_matches(original, dict(original)))
        for key in ("dm_name", "dm_uuid", "partuuid", "header_sha256",
                    "source_sha", "helper_sha256", "parent_major_minor"):
            with self.subTest(field=key):
                substituted = dict(original)
                substituted[key] = "substituted"
                self.assertFalse(helper._recovery_state_identity_matches(
                    original, substituted))
        old_header = dict(original)
        old_header.pop("raw_header_preservation_required")
        self.assertFalse(helper._recovery_state_identity_matches(
            original, old_header))

    def test_mapper_name_or_uuid_collision_blocks_adoption(self):
        state = {"dm_name": "swapz-demo-physical-" + "1" * 16,
                 "dm_uuid": "SWAPZ-TEST-PHYSICAL-" + "1" * 16}
        substituted = f"{state['dm_name']} SWAPZ-TEST-PHYSICAL-{'2' * 16}\n"
        with mock.patch.object(helper, "_run", return_value=SimpleNamespace(
                returncode=0, stdout=substituted)):
            with self.assertRaises(helper.ProbeError):
                helper._mapper_exists(state)

    def test_failed_swapoff_never_advances_to_mapper_removal(self):
        mapper = "/dev/mapper/swapz-demo-physical-" + "1" * 16
        state = {"algorithm_real_swap": True, "development_only": True}
        with (mock.patch.object(helper, "_verify_owned_mapper", return_value=mapper),
              mock.patch.object(helper, "block_identity", return_value=(253, 5)),
              mock.patch.object(helper, "_active_swap_for", return_value={"used_kib": 4}),
              mock.patch.object(helper, "_run", side_effect=helper.ProbeError(
                  "swapoff failed: ENOMEM")) as commands):
            with self.assertRaises(helper.ProbeError):
                helper._prepare_owned_mapper_removal(state, {})
            commands.assert_called_once_with(
                ["swapoff", "--", mapper], timeout=120)

    def test_swapoff_success_without_drained_observation_is_refused(self):
        mapper = "/dev/mapper/swapz-demo-physical-" + "1" * 16
        with (mock.patch.object(helper, "_verify_owned_mapper", return_value=mapper),
              mock.patch.object(helper, "block_identity", return_value=(253, 5)),
              mock.patch.object(helper, "_active_swap_for", return_value={"used_kib": 0}),
              mock.patch.object(helper, "_run", return_value=SimpleNamespace(
                  returncode=0)) as commands):
            with self.assertRaises(helper.ProbeError):
                helper._prepare_owned_mapper_removal(
                    {"algorithm_real_swap": True, "development_only": True}, {})
            self.assertEqual(commands.call_count, 1)

    def test_post_udev_mapping_substitution_blocks_removal(self):
        mapper = "/dev/mapper/swapz-demo-physical-" + "1" * 16
        with (mock.patch.object(helper, "_verify_owned_mapper", side_effect=(
                  mapper, "/dev/mapper/replaced")),
              mock.patch.object(helper, "block_identity", return_value=(253, 5)),
              mock.patch.object(helper, "_active_swap_for", return_value=None),
              mock.patch.object(helper, "_run", return_value=SimpleNamespace(
                  returncode=0)) as commands):
            with self.assertRaises(helper.ProbeError):
                helper._prepare_owned_mapper_removal(
                    {"algorithm_real_swap": True, "development_only": True}, {})
            commands.assert_called_once_with(
                ["udevadm", "settle", "--timeout=10"], timeout=15, check=False)


    def test_duplicate_json_marker_and_state_records_fail_closed(self):
        marker = self.marker.read_text()
        self.marker.write_text(marker[:-1] + ', "run_id": "' + self.run_id + '"}')
        with self.assertRaises(helper.RecoveryRequiredError):
            self.invoke()
        self.recover.assert_not_called()

        self.save_marker()
        (self.state_dir / "state.json").write_text(
            json.dumps(self.state)[:-1] + ', "run_id": "' + self.run_id + '"}')
        with self.assertRaises(helper.RecoveryRequiredError):
            self.invoke()
        self.recover.assert_not_called()

    def test_hardlinked_or_overpermissive_marker_is_not_accepted(self):
        hardlink = self.base / "marker-hardlink"
        os.link(self.marker, hardlink)
        with self.assertRaises(helper.RecoveryRequiredError):
            self.invoke()
        self.recover.assert_not_called()

        hardlink.unlink()
        self.marker.chmod(0o644)
        with self.assertRaises(helper.RecoveryRequiredError):
            self.invoke()
        self.recover.assert_not_called()

    def test_unverifiable_state_directory_never_delegates(self):
        with mock.patch.object(helper, "_validate_state_dir",
                               side_effect=helper.ProbeError(
                                   "state directory identity drift")):
            with self.assertRaises(helper.RecoveryRequiredError):
                self.invoke()
        self.recover.assert_not_called()

    def test_state_record_fsync_failure_preserves_previous_record(self):
        previous = (self.state_dir / "state.json").read_bytes()
        updated = {**self.state, "stage": "SWAP_OFF"}
        with mock.patch.object(helper.os, "fsync",
                               side_effect=OSError(5, "injected file fsync")):
            with self.assertRaises(OSError):
                helper._save_state(self.state_dir, updated)
        self.assertEqual((self.state_dir / "state.json").read_bytes(), previous)
        self.assertEqual(list(self.state_dir.glob(".state-*")), [])
        self.assertTrue(self.marker.exists())

    def test_state_record_replace_failure_preserves_previous_record(self):
        previous = (self.state_dir / "state.json").read_bytes()
        updated = {**self.state, "stage": "MAPPED"}
        with mock.patch.object(helper.os, "replace",
                               side_effect=OSError(5, "injected rename")):
            with self.assertRaises(OSError):
                helper._save_state(self.state_dir, updated)
        self.assertEqual((self.state_dir / "state.json").read_bytes(), previous)
        self.assertEqual(list(self.state_dir.glob(".state-*")), [])
        self.assertTrue(self.marker.exists())

    def test_post_replace_directory_fsync_failure_is_not_a_commit(self):
        previous_fsync = os.fsync
        fsync_calls = 0

        def fail_directory_sync(fd):
            nonlocal fsync_calls
            fsync_calls += 1
            if fsync_calls == 2:
                raise OSError(5, "injected directory fsync")
            return previous_fsync(fd)

        with mock.patch.object(helper.os, "fsync", side_effect=fail_directory_sync):
            with self.assertRaises(OSError):
                helper._save_state(
                    self.state_dir, {**self.state, "stage": "MAPPED"})
        self.assertEqual(fsync_calls, 2)
        # The rename can be visible even when its durability is unknown.
        self.assertEqual(
            json.loads((self.state_dir / "state.json").read_text())["stage"],
            "MAPPED")
        self.assertTrue(self.marker.exists())
        self.assertEqual(list(self.state_dir.glob(".state-*")), [])

    def test_noncomplete_state_cannot_release_partition_marker(self):
        with self.assertRaisesRegex(helper.ProbeError, "COMPLETE"):
            helper._release_partition_ownership({"stage": "RECOVERY_REQUIRED"})
        self.assertTrue(self.marker.exists())

    def test_release_directory_fsync_error_recreates_owner_marker(self):
        consumed = self.base / f"consumed-{self.run_id}.json"
        consumed.write_bytes(self.marker.read_bytes())
        complete = {
            **self.state,
            "stage": "COMPLETE",
        }
        directory_syncs = 0

        def fail_first_directory_sync(_directory):
            nonlocal directory_syncs
            directory_syncs += 1
            if directory_syncs == 1:
                raise OSError(5, "injected directory fsync")

        with (mock.patch.object(helper, "_runtime_state_base",
                                return_value=self.base),
              mock.patch.object(helper, "_fsync_directory",
                                side_effect=fail_first_directory_sync)):
            with self.assertRaisesRegex(helper.ProbeError,
                                        "owner_marker=retained"):
                helper._release_partition_ownership(complete)
        self.assertEqual(directory_syncs, 2)
        self.assertEqual(
            json.loads(self.marker.read_text()),
            json.loads(consumed.read_text()))

    def test_release_marker_recreation_error_is_explicitly_uncertain(self):
        consumed = self.base / f"consumed-{self.run_id}.json"
        consumed.write_bytes(self.marker.read_bytes())
        with (mock.patch.object(helper, "_runtime_state_base",
                                return_value=self.base),
              mock.patch.object(helper, "_fsync_directory",
                                side_effect=OSError(5, "injected directory fsync")),
              mock.patch.object(helper, "_durable_exclusive_record",
                                side_effect=OSError(5, "injected marker retention"))):
            with self.assertRaisesRegex(helper.ProbeError,
                                        "owner_marker=uncertain"):
                helper._release_partition_ownership(
                    {**self.state, "stage": "COMPLETE"})
        # The error prohibits a completed-cleanup claim; a vanished path alone
        # cannot grant a different caller ownership of the original partition.
        self.assertFalse(self.marker.exists())

    def test_duplicate_mapper_identity_in_inventory_is_not_adopted(self):
        name = "swapz-demo-physical-" + "1" * 16
        uuid = "SWAPZ-TEST-PHYSICAL-" + "1" * 16
        with mock.patch.object(helper, "_run", return_value=SimpleNamespace(
                returncode=0, stdout=f"{name} {uuid}\n{name} {uuid}\n")):
            with self.assertRaises(helper.ProbeError):
                helper._mapper_exists({"dm_name": name, "dm_uuid": uuid})


if __name__ == "__main__":
    unittest.main()