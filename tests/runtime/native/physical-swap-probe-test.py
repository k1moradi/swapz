#!/usr/bin/env python3
import hashlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import errno
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import struct
import stat
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/physical-swap-probe.py"
SPEC = importlib.util.spec_from_file_location("physical_swap_probe", SCRIPT)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)

REAL_RECOVERY_BASE = probe._recovery_base
REAL_PARTITION_LOCK = probe._partition_lock
REAL_PATH_READ_TEXT = Path.read_text
REAL_PATH_IS_FILE = Path.is_file


class PhysicalSwapProbeTests(unittest.TestCase):
    def setUp(self):
        # Recover-state tests use a private synthetic base, never the host's
        # real physical-recovery directory. Explicit base/lock tests override.
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.recovery_base = Path(temporary.name)
        for name, replacement in (
            ("_recovery_base", lambda target=None: self.recovery_base),
            ("_recovery_run_directory", lambda path, run_id=None: Path(path)),
            ("_partition_lock", lambda partuuid: os.open(os.devnull, os.O_RDONLY)),
        ):
            patch = mock.patch.object(probe, name, replacement)
            patch.start()
            self.addCleanup(patch.stop)

    def make_recovery_state(self, state_dir):
        state_dir.mkdir(mode=0o700)
        header = bytearray(probe.PAGE_BYTES)
        header[-len(probe.SWAP_SIGNATURE):] = probe.SWAP_SIGNATURE
        header = bytes(header)
        token = "1234567890abcdef"
        state = {
            "device_arg": "/dev/disk/by-uuid/test-swap",
            "device": "/dev/sda4",
            "major": 8,
            "minor": 4,
            "size_bytes": 16 * 1024 * 1024 * 1024,
            "partuuid": "deadbeef-04",
            "stage": "HEADER_CLEARED",
            "header_sha256": hashlib.sha256(header).hexdigest(),
            "swap_was_active": True,
            "swap_priority": -1,
            "module_ownership": "NOT_STARTED",
            "swap_size_kib": (16 * 1024 * 1024 * 1024) // 1024 - 4,
            "run_id": "0123456789abcdef0123456789abcdef",
            "module_loaded_by_us": False,
            "dm_name": f"swapz-demo-physical-{token}",
            "dm_uuid": f"SWAPZ-TEST-PHYSICAL-{token}",
        }
        (state_dir / probe.STATE_NAME).write_text(json.dumps(state))
        (state_dir / probe.BACKUP_NAME).write_bytes(header)
        marker = {"run_id": state["run_id"], "partuuid": state["partuuid"],
                  "major": state["major"], "minor": state["minor"]}
        (self.recovery_base / f"partition-{state['partuuid']}.active").write_text(
            json.dumps(marker))
        (self.recovery_base / f"consumed-{state['run_id']}.json").write_text(
            json.dumps(marker))
        return state, header

    def test_dm_inventory_accepts_canonical_empty_dmsetup_output(self):
        expected = {
            "other_mapper_count": 0,
            "other_mapper_sha256": hashlib.sha256(b"[]").hexdigest(),
        }
        for output in ("No devices found\n", "  No devices found  \n"):
            with self.subTest(output=output), mock.patch.object(
                    probe, "_run",
                    return_value=subprocess.CompletedProcess(
                        args=[], returncode=0, stdout=output, stderr="")) as run:
                self.assertEqual(probe._dm_inventory_snapshot(), expected)
                self.assertEqual(
                    probe._dm_inventory_snapshot(
                        "swapz-demo-physical-owned",
                        "SWAPZ-TEST-PHYSICAL-owned"),
                    expected)
                self.assertEqual(run.call_count, 2)
                run.assert_called_with(
                    ["dmsetup", "info", "-c", "--noheadings", "-o",
                     "name,uuid"], check=False)

    def test_dm_inventory_rejects_ambiguous_success_or_command_failure(self):
        for output in ("", "  \n", "No devices found\nother map-uuid\n",
                       "No devices found now\n", "broken too many columns\n"):
            with self.subTest(output=output), mock.patch.object(
                    probe, "_run",
                    return_value=subprocess.CompletedProcess(
                        args=[], returncode=0, stdout=output, stderr="")):
                with self.assertRaisesRegex(
                        probe.ProbeError, "Device Mapper inventory"):
                    probe._dm_inventory_snapshot()
        with mock.patch.object(
                probe, "_run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=1, stdout="No devices found\n",
                    stderr="device-mapper failure")):
            with self.assertRaisesRegex(
                    probe.ProbeError, "cannot snapshot Device Mapper inventory"):
                probe._dm_inventory_snapshot()

    def test_development_fast_test_evidence_is_fresh_exact_and_narrow(self):
        head = "a" * 40
        nonce = "b" * 32
        # Keep the fixture to the admission-critical fields. The producer may
        # append diagnostics such as errno/result_file; those do not replace
        # the nonce, clean-source, native-status or fast-test outcome gates.
        base = {
            "schema": "swapz-fast-test-development-evidence-v1",
            "head": head,
            "dirty": False,
            "nonce": nonce,
            "native_status": "PASS",
            "loaded_preflight": {"status": "PASS", "check": "complete"},
            "fast_test_status": "PASS",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "development-evidence.json"

            def write(record, mode=0o600):
                path.write_text(json.dumps(record))
                path.chmod(mode)

            write(base)
            admitted = probe._read_fast_test_development_evidence(
                path, os.getuid(), head, nonce)
            self.assertEqual(admitted["outcome"], "FAST_TEST_PASS")

            # A complete successful producer record remains valid; these extra
            # fields are telemetry, not independent authorization.
            producer_record = {
                **base,
                "loaded_preflight": {
                    "status": "PASS", "check": "complete", "errno": "0"},
                "result_file": "synthetic-fast-mixed.json",
            }
            write(producer_record)
            admitted = probe._read_fast_test_development_evidence(
                path, os.getuid(), head, nonce)
            self.assertEqual(admitted["outcome"], "FAST_TEST_PASS")

            blocked = {
                **base,
                "loaded_preflight": {
                    "status": "BLOCKED", "check": "unclaimed_null_blk",
                    "errno": "unknown",
                },
                "fast_test_status": "BLOCKED",
            }
            write(blocked)
            admitted = probe._read_fast_test_development_evidence(
                path, os.getuid(), head, nonce)
            self.assertEqual(
                admitted["outcome"],
                "LOADED_PREFLIGHT_BLOCKED_UNCLAIMED_NULL_BLK")

            rejected = (
                ({**blocked, "loaded_preflight": {
                    "status": "BLOCKED", "check": "kernel_build"}},
                 head, nonce, "other_failure"),
                ({**base, "dirty": True}, head, nonce, "mismatch"),
                ({**base, "head": "c" * 40}, head, nonce, "mismatch"),
                ({**base, "schema": "other-evidence"}, head, nonce,
                 "mismatch"),
                (base, head, "c" * 32, "mismatch"),
                ({**base, "native_status": "PENDING"}, head, nonce,
                 "mismatch"),
                ({**base, "native_status": None,
                  "result_file": "PASS", "errno": "0"}, head, nonce,
                 "mismatch"),
                ({**base, "nonce": "d" * 32,
                  "result_file": "PASS"}, head, nonce, "mismatch"),
                ({**base, "fast_test_status": None,
                  "result_file": "PASS"}, head, nonce, "other_failure"),
                ({**base, "loaded_preflight": None,
                  "diagnostics": {"status": "PASS"}}, head, nonce,
                 "other_failure"),
                ({**base, "fast_test_status": "FAIL"}, head, nonce,
                 "other_failure"),
                ({**base, "loaded_preflight": {
                    "status": "BLOCKED", "check": "unclaimed_null_blk",
                    "errno": "unknown"}}, head, nonce, "other_failure"),
            )
            for record, expected_head, expected_nonce, diagnostic in rejected:
                with self.subTest(record=record, nonce=expected_nonce):
                    write(record)
                    with self.assertRaisesRegex(probe.ProbeError, diagnostic):
                        probe._read_fast_test_development_evidence(
                            path, os.getuid(), expected_head, expected_nonce)

            write(base, 0o644)
            with self.assertRaisesRegex(probe.ProbeError, "invalid_metadata"):
                probe._read_fast_test_development_evidence(
                    path, os.getuid(), head, nonce)

            path.unlink()
            path.symlink_to("missing-target")
            with self.assertRaisesRegex(probe.ProbeError, "errno_"):
                probe._read_fast_test_development_evidence(
                    path, os.getuid(), head, nonce)

    def test_development_source_drift_before_fast_test_is_preemptive(self):
        import pwd

        pinned_head = "a" * 40
        changed_head = "c" * 40
        repository_owner = pwd.getpwuid(
            os.stat(probe.ROOT, follow_symlinks=False).st_uid).pw_name
        for drift in ("local", "origin", "remote"):
            with self.subTest(drift=drift):
                def git(*args):
                    if args[0] == "symbolic-ref":
                        return "main"
                    if args[0] == "status":
                        return ""
                    if args[:2] == ("rev-parse", "HEAD"):
                        return changed_head if drift == "local" else pinned_head
                    if args[:2] == ("rev-parse", "origin/main"):
                        return changed_head if drift == "origin" else pinned_head
                    self.fail(f"unexpected Git read: {args}")

                # Model sudo invocation by the actual checkout owner so this
                # control reaches the Git source gate instead of stopping at
                # the independent sudo-wrapper ownership prerequisite.
                with mock.patch.object(probe.platform, "machine",
                                       return_value="x86_64"), \
                        mock.patch.object(probe, "_require_physical_host"), \
                        mock.patch.object(probe.os, "geteuid", return_value=0), \
                        mock.patch.dict(os.environ,
                                        {"SUDO_USER": repository_owner}), \
                        mock.patch.object(probe, "_git", side_effect=git), \
                        mock.patch.object(
                            probe, "_remote_main_sha",
                            return_value=(changed_head if drift == "remote"
                                          else pinned_head)), \
                        mock.patch.object(probe.subprocess, "run") as fast_test, \
                        mock.patch.object(probe, "_artifact_digests") as digests:
                    with self.assertRaisesRegex(
                            probe.ProbeError, "must match before development smoke"):
                        probe.current_development_evidence("1" * 32)
                fast_test.assert_not_called()
                digests.assert_not_called()

    def test_development_recovery_restores_header_without_swapon(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            state, backup = self.make_recovery_state(state_dir)
            state.update({
                "swap_was_active": False,
                "swap_path": None,
                "swap_size_kib": None,
                "swap_priority": None,
                "swap_used_kib": None,
                "development_only": True,
                "development_scope": probe.DEVELOPMENT_SCOPE,
            })
            (state_dir / probe.STATE_NAME).write_text(json.dumps(state))
            commands = []

            def run(command, **kwargs):
                del kwargs
                commands.append(tuple(command))
                return subprocess.CompletedProcess(
                    command, 0, stdout="", stderr="")

            with mock.patch.object(probe, "_validate_state_dir"), \
                    mock.patch.object(
                        probe, "inspect_target_identity_for_recovery",
                        return_value={
                            "device": state["device"], "major": state["major"],
                            "minor": state["minor"],
                            "size_bytes": state["size_bytes"],
                            "partuuid": state["partuuid"],
                        }), \
                    mock.patch.object(probe, "_mapper_exists",
                                      return_value=False), \
                    mock.patch.object(probe, "_active_swap_for",
                                      return_value=None) as active_swap, \
                    mock.patch.object(probe, "_read_block0",
                                      return_value=backup), \
                    mock.patch.object(probe, "_holder_names", return_value=[]), \
                    mock.patch.object(probe, "_mountinfo_has_device",
                                      return_value=False), \
                    mock.patch.object(probe, "_run", side_effect=run), \
                    mock.patch.object(probe, "_save_state"), \
                    mock.patch.object(probe,
                                      "_release_partition_ownership"):
                recovered = probe.recover(
                    state_dir, state["device_arg"], state["device_arg"])

        self.assertEqual(recovered["stage"], "COMPLETE")
        self.assertEqual(active_swap.call_count, 2)
        self.assertFalse(any(command[0] == "swapon" for command in commands))
        self.assertFalse(any(command[:2] == ("dmsetup", "remove")
                             for command in commands))

    def test_development_recovery_rejects_noncanonical_inactive_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            state, _ = self.make_recovery_state(state_dir)
            state.update({
                "swap_was_active": False,
                "swap_path": None,
                "swap_size_kib": None,
                "swap_priority": None,
                "swap_used_kib": None,
                "development_only": True,
                "development_scope": "wrong scope",
            })
            (state_dir / probe.STATE_NAME).write_text(json.dumps(state))
            with mock.patch.object(probe, "_validate_state_dir"), \
                    mock.patch.object(
                        probe, "inspect_target_identity_for_recovery") as inspect, \
                    mock.patch.object(probe, "_run") as command:
                with self.assertRaisesRegex(
                        probe.ProbeError, "canonical_inactive_development_state"):
                    probe.recover(
                        state_dir, state["device_arg"], state["device_arg"])
            inspect.assert_not_called()
            command.assert_not_called()

    def test_development_run_directory_uses_its_fresh_run_id(self):
        run_id = "abcdef0123456789abcdef0123456789"
        expected = self.recovery_base / f"swapz-physical-{run_id}"
        with mock.patch.object(probe, "RECOVERY_BASE", self.recovery_base):
            self.assertEqual(
                probe._select_run_directory(None, run_id, True), expected)
            with self.assertRaisesRegex(
                    probe.ProbeError, "chooses its own fresh recovery directory"):
                probe._select_run_directory(expected, run_id, True)
            self.assertEqual(
                probe._select_run_directory(expected, run_id, False), expected)

    def test_development_final_observations_require_inactive_target(self):
        run_id = "fedcba9876543210fedcba9876543210"
        header = b"H" * probe.PAGE_BYTES
        state = {
            "partuuid": "deadbeef-01", "run_id": run_id,
            "dm_name": "swapz-demo-physical-1234567890abcdef",
            "dm_uuid": "SWAPZ-TEST-PHYSICAL-1234567890abcdef",
            "stage": "COMPLETE", "development_only": True,
            "swap_was_active": False,
        }
        target = {"device": "/dev/synthetic", "major": 8, "minor": 1}
        inventory = {
            "other_mapper_count": 0,
            "other_mapper_sha256": hashlib.sha256(b"[]").hexdigest(),
        }
        (self.recovery_base / f"consumed-{run_id}.json").write_text("{}")
        results = {
            "original_header_sha256": hashlib.sha256(header).hexdigest(),
            "start_timestamp": "2026-11-04T00:00:00Z",
            "dm_inventory_before": inventory,
        }
        healthy_kernel = {
            "available": True, "time_filter_applied": True,
            "truncated": False, "messages": "",
        }
        with mock.patch.object(probe, "_read_block0", return_value=header), \
                mock.patch.object(probe, "_active_swap_for", return_value=None), \
                mock.patch.object(probe, "_block_stat_snapshot",
                                  return_value={"available": False}), \
                mock.patch.object(probe, "_kernel_swapz_messages",
                                  return_value=healthy_kernel), \
                mock.patch.object(probe, "_mapper_exists", return_value=False), \
                mock.patch.object(probe, "_dm_inventory_snapshot",
                                  return_value=inventory), \
                mock.patch.object(probe.Path, "exists", return_value=False), \
                mock.patch.object(probe, "_save_results"):
            probe._final_observations(
                results, self.recovery_base, state, target)

        self.assertTrue(results["restored_swap_verified"])
        self.assertTrue(results["target_remains_inactive"])
        self.assertTrue(results["run_claim_consumed"])
        self.assertIsNone(results["approval_consumed"])
        self.assertFalse(results["active_partition_marker_present"])
        self.assertTrue(results["unrelated_mapper_inventory_unchanged"])

    def test_dm_inventory_still_tracks_unrelated_mappers(self):
        inventory = "swapz-physical-owned SWAPZ-TEST-PHYSICAL-owned\nother-map other-uuid\n"
        with mock.patch.object(
                probe, "_run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=inventory, stderr="")):
            actual = probe._dm_inventory_snapshot(
                "swapz-physical-owned", "SWAPZ-TEST-PHYSICAL-owned")
        expected_rows = [["other-map", "other-uuid"]]
        self.assertEqual(actual, {
            "other_mapper_count": 1,
            "other_mapper_sha256": hashlib.sha256(json.dumps(
                expected_rows, separators=(",", ":")).encode()).hexdigest(),
        })

    def test_colon_delimited_dm_info_identity_cannot_be_mistaken_for_absence(self):
        token = "88a2b96d81d81254"
        name = f"swapz-demo-physical-{token}"
        uuid = f"SWAPZ-TEST-PHYSICAL-{token}"
        state = {"dm_name": name, "dm_uuid": uuid}
        for output, present in (
            (f"{name}:{uuid}\n", True),
            (f"{name} {uuid}\n", True),
            ("No devices found\n", False),
        ):
            with self.subTest(output=output), mock.patch.object(
                    probe, "_run", return_value=subprocess.CompletedProcess(
                        args=[], returncode=0, stdout=output, stderr="")):
                self.assertEqual(probe._mapper_exists(state), present)

    def test_dm_parser_fail_closed_on_bad_fields_or_substituted_uuid(self):
        token = "88a2b96d81d81254"
        name = f"swapz-demo-physical-{token}"
        uuid = f"SWAPZ-TEST-PHYSICAL-{token}"
        state = {"dm_name": name, "dm_uuid": uuid}
        for output in (
            f"{name}:SWAPZ-TEST-PHYSICAL-ffffffffffffffff\n",
            f"unrelated:{uuid}\n",
            f"{name}:{uuid}:another-field\n",
            "No devices found\nother-map:other-uuid\n",
            "name:uuid:major:minor\n",
        ):
            with self.subTest(output=output), mock.patch.object(
                    probe, "_run", return_value=subprocess.CompletedProcess(
                        args=[], returncode=0, stdout=output, stderr="")):
                with self.assertRaises(probe.ProbeError):
                    probe._mapper_exists(state)
        with mock.patch.object(
                probe, "_run", return_value=subprocess.CompletedProcess(
                    args=[], returncode=1, stdout=f"{name}:{uuid}\n",
                    stderr="device-mapper failed")):
            with self.assertRaises(probe.ProbeError):
                probe._mapper_exists(state)

    def test_colon_delimited_unrelated_mapper_inventory_preserves_identity(self):
        token = "88a2b96d81d81254"
        name = f"swapz-demo-physical-{token}"
        uuid = f"SWAPZ-TEST-PHYSICAL-{token}"
        output = f"{name}:{uuid}\nunrelated:other-uuid\n"
        with mock.patch.object(
                probe, "_run", return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=output, stderr="")):
            result = probe._dm_inventory_snapshot(name, uuid)
        expected_rows = [["unrelated", "other-uuid"]]
        self.assertEqual(result, {
            "other_mapper_count": 1,
            "other_mapper_sha256": hashlib.sha256(json.dumps(
                expected_rows, separators=(",", ":")).encode()).hexdigest(),
        })
        with mock.patch.object(
                probe, "_run", return_value=subprocess.CompletedProcess(
                    args=[], returncode=0,
                    stdout=f"{name}:wrong-uuid\n", stderr="")):
            with self.assertRaisesRegex(probe.ProbeError, "UUID"):
                probe._dm_inventory_snapshot(name, uuid)

    def test_mapper_name_allocation_sees_colon_delimited_existing_identity(self):
        token = "88a2b96d81d81254"
        old_name = f"swapz-demo-physical-{token}"
        old_uuid = f"SWAPZ-TEST-PHYSICAL-{token}"
        output = f"{old_name}:{old_uuid}\n"
        with mock.patch.object(
                probe, "_run", return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=output, stderr="")), \
                mock.patch.object(probe.secrets, "token_hex",
                                  side_effect=[token, "abcdef0123456789"]):
            self.assertEqual(probe._allocate_dm_identity(), (
                "swapz-demo-physical-abcdef0123456789",
                "SWAPZ-TEST-PHYSICAL-abcdef0123456789"))
        with mock.patch.object(
                probe, "_run", return_value=subprocess.CompletedProcess(
                    args=[], returncode=1, stdout=output, stderr="error")):
            with self.assertRaises(probe.ProbeError):
                probe._allocate_dm_identity()

    def test_only_supported_4k_linux_swap_header_is_accepted(self):
        header = bytearray(probe.PAGE_BYTES)
        header[-len(probe.SWAP_SIGNATURE):] = probe.SWAP_SIGNATURE
        self.assertTrue(probe.swap_signature_valid(bytes(header)))
        self.assertFalse(probe.swap_signature_valid(bytes(header), 65536))
        self.assertFalse(probe.swap_signature_valid(bytes(header[:-1])))
        header[-1] ^= 1
        self.assertFalse(probe.swap_signature_valid(bytes(header)))

    def test_swap_inventory_requires_exact_header_and_numeric_fields(self):
        valid = (
            "Filename Type Size Used Priority\n"
            "/dev/test partition 16777212 0 -1\n"
        )
        self.assertEqual(probe.parse_swap_rows(valid)[0]["used_kib"], 0)
        self.assertEqual(probe.parse_swap_rows(valid)[0]["priority"], -1)
        with self.assertRaisesRegex(probe.ProbeError, "header"):
            probe.parse_swap_rows("Name Type Size Used Priority\n")
        with self.assertRaisesRegex(probe.ProbeError, "numeric"):
            probe.parse_swap_rows(
                "Filename Type Size Used Priority\n/dev/test partition x 0 -1\n")
        with self.assertRaisesRegex(probe.ProbeError, "capacity"):
            probe.parse_swap_rows(
                "Filename Type Size Used Priority\n/dev/test partition 10 -1 -1\n")

    def test_regular_files_are_never_block_devices(self):
        with tempfile.NamedTemporaryFile() as regular:
            with self.assertRaisesRegex(probe.ProbeError, "not a block device"):
                probe.block_identity(regular.name)

    def test_physical_target_requires_repeated_stable_uuid_path(self):
        with self.assertRaisesRegex(probe.ProbeError, "match exactly"):
            probe.inspect_target("/dev/disk/by-uuid/a", "/dev/disk/by-uuid/b")
        with self.assertRaisesRegex(probe.ProbeError, "by-uuid"):
            probe.inspect_target("/dev/sda4", "/dev/sda4")

    def test_review_record_is_bound_to_helper_source_and_device(self):
        artifact_digests = {key: str(index) * 64 for index, (key, _, _)
                            in enumerate(probe.PHYSICAL_ARTIFACTS, start=1)}
        evidence = {
            "source_sha": "a" * 40,
            "head": "b" * 40,
            "helper_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
            "artifact_digests": artifact_digests,
        }
        header = bytearray(probe.PAGE_BYTES)
        header[-len(probe.SWAP_SIGNATURE):] = probe.SWAP_SIGNATURE
        target = {"major": 8, "minor": 4, "partuuid": "deadbeef-04",
                  "size_bytes": 16 * 1024 * 1024 * 1024,
                  "device_arg": "/dev/disk/by-uuid/test-swap",
                  "header": bytes(header)}
        review = {
            **artifact_digests,
            "approved": True,
            "approval_mode": "verbal",
            "approval_text": probe.VERBAL_APPROVAL_TEXT,
            "reviewer": probe.VERBAL_REVIEWER,
            "scope": probe.EXPECTED_SCOPE,
            "source_sha": evidence["source_sha"],
            "helper_git_sha": evidence["head"],
            "device_major_minor": "8:4",
            "device_partuuid": "deadbeef-04",
            "device_size_bytes": target["size_bytes"],
            "original_header_sha256": hashlib.sha256(target["header"]).hexdigest(),
            "device_uuid_path": target["device_arg"],
            "run_id": "0123456789abcdef0123456789abcdef",
            "helper_sha256": evidence["helper_sha256"],
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "review.json"
            path.write_text(json.dumps(review))
            with mock.patch.dict(os.environ, {"SUDO_USER": "keivan", "USER": "root"}):
                self.assertEqual(
                    probe.validate_review(path, evidence, target),
                    {"reviewer": probe.VERBAL_REVIEWER,
                     "run_id": review["run_id"], "approval_mode": "verbal"})
                review["device_major_minor"] = "8:3"
                path.write_text(json.dumps(review))
                with self.assertRaisesRegex(probe.ProbeError, "does not match"):
                    probe.validate_review(path, evidence, target)
                review["device_major_minor"] = "8:4"
                review["device_partuuid"] = "cafebabe-04"
                path.write_text(json.dumps(review))
                with self.assertRaisesRegex(probe.ProbeError, "does not match"):
                    probe.validate_review(path, evidence, target)
                review["device_partuuid"] = "deadbeef-04"
                review["module_sha256"] = "f" * 64
                path.write_text(json.dumps(review))
                with self.assertRaisesRegex(probe.ProbeError, "binary artifacts"):
                    probe.validate_review(path, evidence, target)
                review["module_sha256"] = artifact_digests["module_sha256"]
                for field, bad_value in (
                        ("approval_mode", "ssh-signature"),
                        ("approval_text", "approval wording changed"),
                        ("reviewer", "different-reviewer"),
                        ("helper_git_sha", "c" * 40)):
                    changed = dict(review, **{field: bad_value})
                    path.write_text(json.dumps(changed))
                    with self.assertRaises(probe.ProbeError):
                        probe.validate_review(path, evidence, target)
                duplicate = json.dumps(review)[:-1] + \
                    ',"reviewer":"duplicate-reviewer"}'
                path.write_text(duplicate)
                with self.assertRaisesRegex(
                        probe.ProbeError, "duplicate JSON key"):
                    probe.validate_review(path, evidence, target)

    def test_physical_artifact_snapshot_binds_reviewed_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = {}
            with mock.patch.object(probe, "ROOT", root):
                for key, relative, executable in probe.PHYSICAL_ARTIFACTS:
                    source = root / relative
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_bytes((key + "-reviewed").encode())
                    source.chmod(0o700 if executable else 0o600)
                    sources[key] = source
                expected = probe._artifact_digests()
                first_state = root / "state-one"
                first_state.mkdir(mode=0o700)
                snapshots = probe._snapshot_reviewed_artifacts(
                    first_state, expected)
                for key, source in sources.items():
                    self.assertEqual(snapshots[key].read_bytes(),
                                     source.read_bytes())
                    self.assertEqual(snapshots[key].stat().st_mode & 0o777,
                                     0o400 if key == "module_sha256" else 0o500)

                # Mutating a build artifact after review cannot enter the trial.
                sources["module_sha256"].write_bytes(b"replaced module bytes")
                second_state = root / "state-two"
                second_state.mkdir(mode=0o700)
                with self.assertRaisesRegex(probe.ProbeError, "review"):
                    probe._snapshot_reviewed_artifacts(second_state, expected)
                self.assertFalse((second_state / "dm-swapz.ko").exists())

                # No-follow source validation also excludes symlink substitution
                # without disclosing the synthetic/private source path.
                sources["module_sha256"].unlink()
                sources["module_sha256"].symlink_to(sources["formatter_sha256"])
                with self.assertRaisesRegex(
                        probe.ProbeError,
                        "physical_artifact.module_sha256 "
                        "expected=readable_no_follow_file observed=errno_"
                        ) as blocked:
                    probe._artifact_digests()
                self.assertNotIn(directory, str(blocked.exception))

    def test_review_rejects_the_operator_as_reviewer(self):
        evidence = {"source_sha": "b" * 40, "head": "c" * 40,
                    "helper_sha256": hashlib.sha256(
                        SCRIPT.read_bytes()).hexdigest(),
                    "artifact_digests": {
                        key: str(index) * 64 for index, (key, _, _) in
                        enumerate(probe.PHYSICAL_ARTIFACTS, start=1)}}
        target = {"major": 8, "minor": 4, "partuuid": "deadbeef-04"}
        review = {
            "approved": True,
            "reviewer": "keivan",
            "approval_mode": "verbal",
            "approval_text": probe.VERBAL_APPROVAL_TEXT,
            "scope": probe.EXPECTED_SCOPE,
            "source_sha": evidence["source_sha"],
            "helper_git_sha": evidence["head"],
            "device_major_minor": "8:4",
            "device_partuuid": "deadbeef-04",
            "device_size_bytes": 1024,
            "original_header_sha256": "a" * 64,
            "device_uuid_path": "/dev/disk/by-uuid/test",
            "run_id": "0123456789abcdef0123456789abcdef",
            "helper_sha256": evidence["helper_sha256"],
            **evidence["artifact_digests"],
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "review.json"
            path.write_text(json.dumps(review))
            with mock.patch.dict(os.environ, {"SUDO_USER": "keivan", "USER": "root"}):
                with self.assertRaisesRegex(probe.ProbeError, "separate"):
                    probe.validate_review(path, evidence, target)

    def test_recovery_refuses_a_different_confirmed_partition(self):
        state = {"device_arg": "/dev/disk/by-uuid/original"}
        with self.assertRaisesRegex(probe.ProbeError, "exact originally confirmed"):
            probe.inspect_target_identity_for_recovery(
                state, "/dev/disk/by-uuid/other", "/dev/disk/by-uuid/other")

    def test_recovery_only_accepts_its_generated_mapper_identity(self):
        token = "1234567890abcdef"
        probe._validate_owned_mapper_identity({
            "dm_name": f"swapz-demo-physical-{token}",
            "dm_uuid": f"SWAPZ-TEST-PHYSICAL-{token}",
        })
        with self.assertRaisesRegex(probe.ProbeError, "owned mapper"):
            probe._validate_owned_mapper_identity({
                "dm_name": "unrelated-mapper",
                "dm_uuid": f"SWAPZ-TEST-PHYSICAL-{token}",
            })
        with self.assertRaisesRegex(probe.ProbeError, "tokens"):
            probe._validate_owned_mapper_identity({
                "dm_name": f"swapz-demo-physical-{token}",
                "dm_uuid": f"SWAPZ-TEST-PHYSICAL-{'0' * 16}",
            })

    def test_recovery_restores_header_before_reenabling_original_swap(self):
        events = []
        with tempfile.TemporaryDirectory() as temp:
            state_dir = Path(temp) / "state"
            state, backup = self.make_recovery_state(state_dir)
            active = {"path": state["device"], "priority": -1,
                      "size_kib": state["swap_size_kib"], "used_kib": 0}

            def run(args, **kwargs):
                del kwargs
                events.append(("run", tuple(args)))
                if args[:2] == ["dmsetup", "info"]:
                    return subprocess.CompletedProcess(
                        args, 0, stdout=state["dm_uuid"] + "\n", stderr="")
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

            def write_header(device, header, target, **kwargs):
                self.assertEqual(target["major"], 8)
                events.append(("write", device, header))

            with mock.patch.object(probe, "_validate_state_dir"), \
                    mock.patch.object(
                        probe, "inspect_target_identity_for_recovery",
                        return_value={"device": state["device"], "major": 8,
                                      "minor": 4, "size_bytes": state["size_bytes"]}), \
                    mock.patch.object(probe, "_run", side_effect=run), \
                    mock.patch.object(probe, "_holder_names", return_value=[]), \
                    mock.patch.object(probe, "_mountinfo_has_device", return_value=False), \
                    mock.patch.object(probe, "_read_block0",
                                      side_effect=[bytes(probe.PAGE_BYTES), backup]), \
                    mock.patch.object(probe, "_verify_target_identity"), \
                    mock.patch.object(probe, "_write_block0", side_effect=write_header), \
                    mock.patch.object(probe, "_active_swap_for",
                                      side_effect=[None, None, active]):
                recovered = probe.recover(
                    state_dir, state["device_arg"], state["device_arg"])

        self.assertEqual(recovered["stage"], "COMPLETE")
        write_event = next(i for i, event in enumerate(events)
                           if event[0] == "write")
        swapon_event = next(i for i, event in enumerate(events)
                            if event[0] == "run" and event[1][0] == "swapon")
        self.assertLess(write_event, swapon_event)
        self.assertEqual(events[write_event], ("write", state["device"], backup))
        self.assertEqual(events[swapon_event][1], ("swapon", state["device"]))

    def test_recovery_never_overwrites_a_header_while_swap_is_active(self):
        with tempfile.TemporaryDirectory() as temp:
            state_dir = Path(temp) / "state"
            state, _ = self.make_recovery_state(state_dir)
            run_calls = []
            run = mock.Mock(side_effect=lambda args, **kwargs: (
                run_calls.append(tuple(args)) or subprocess.CompletedProcess(
                    args, 0, stdout=state["dm_uuid"] + "\n" if args[:2] ==
                    ["dmsetup", "info"] else "", stderr="")))
            with mock.patch.object(probe, "_validate_state_dir"), \
                    mock.patch.object(
                        probe, "inspect_target_identity_for_recovery",
                        return_value={"device": state["device"], "major": 8,
                                      "minor": 4, "size_bytes": state["size_bytes"]}), \
                    mock.patch.object(probe, "_run", side_effect=run), \
                    mock.patch.object(probe, "_holder_names", return_value=[]), \
                    mock.patch.object(probe, "_mountinfo_has_device", return_value=False), \
                    mock.patch.object(probe, "_read_block0", return_value=bytes(probe.PAGE_BYTES)), \
                    mock.patch.object(probe, "_write_block0") as write_header, \
                    mock.patch.object(probe, "_active_swap_for", return_value={"used_kib": 0}):
                with self.assertRaisesRegex(probe.ProbeError, "active swap"):
                    probe.recover(
                        state_dir, state["device_arg"], state["device_arg"])

        write_header.assert_not_called()
        self.assertFalse(any(call[0] == "swapon" for call in run_calls))

    def test_recovery_rejects_corrupt_header_backup_before_device_access(self):
        with tempfile.TemporaryDirectory() as temp:
            state_dir = Path(temp) / "state"
            state, _ = self.make_recovery_state(state_dir)
            (state_dir / probe.BACKUP_NAME).write_bytes(b"x" * probe.PAGE_BYTES)
            with mock.patch.object(probe, "_validate_state_dir"), \
                    mock.patch.object(probe, "inspect_target_identity_for_recovery") as inspect, \
                    mock.patch.object(probe, "_run") as run, \
                    mock.patch.object(probe, "_write_block0") as write_header:
                with self.assertRaisesRegex(probe.ProbeError, "digest|header"):
                    probe.recover(
                        state_dir, state["device_arg"], state["device_arg"])

        inspect.assert_not_called()
        run.assert_not_called()
        write_header.assert_not_called()

    def test_recovery_refuses_malformed_original_swap_evidence_before_device_access(self):
        # A damaged saved active-swap flag previously skipped swapon, marked
        # COMPLETE and released ownership even with the original swap absent.
        cases = (
            ("inactive", "swap_was_active", False,
             "recovery_original_swap_active expected=true observed=false"),
            ("missing_active", "swap_was_active", None,
             "recovery_original_swap_active expected=true observed=missing"),
            ("truthy_integer", "swap_was_active", 1,
             "recovery_original_swap_active expected=true observed=invalid"),
            ("zero_size", "swap_size_kib", 0,
             "recovery_original_swap_size_kib expected=positive_integer observed=invalid"),
            ("string_size", "swap_size_kib", "16777212",
             "recovery_original_swap_size_kib expected=positive_integer observed=invalid"),
            ("missing_priority", "swap_priority", None,
             "recovery_original_swap_priority expected=integer observed=missing"),
            ("boolean_priority", "swap_priority", True,
             "recovery_original_swap_priority expected=integer observed=invalid"),
            ("oversize_capacity", "swap_size_kib", "oversize_capacity",
             "recovery_original_swap_size_kib expected=within_saved_device "
             "observed=exceeds_saved_device"),
            ("priority_above_restorable_range", "swap_priority", 32768,
             "recovery_original_swap_priority expected=-1..32767 "
             "observed=out_of_range"),
            ("priority_below_restorable_range", "swap_priority", -2,
             "recovery_original_swap_priority expected=-1..32767 "
             "observed=out_of_range"),
        )
        for case, field, value, diagnostic in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                state_dir = Path(temporary) / "state"
                state, backup = self.make_recovery_state(state_dir)
                if value is None:
                    state.pop(field)
                elif value == "oversize_capacity":
                    state[field] = state["size_bytes"] // 1024 + 1
                else:
                    state[field] = value
                state_path = state_dir / probe.STATE_NAME
                state_path.write_text(json.dumps(state))
                original_record = state_path.read_bytes()
                marker_path = (
                    self.recovery_base / f"partition-{state['partuuid']}.active")
                consumed_path = (
                    self.recovery_base / f"consumed-{state['run_id']}.json")
                original_marker = marker_path.read_bytes()
                original_consumption = consumed_path.read_bytes()
                with mock.patch.object(probe, "_validate_state_dir"), \
                        mock.patch.object(
                            probe, "inspect_target_identity_for_recovery") as inspect, \
                        mock.patch.object(probe, "_mapper_exists") as mapper, \
                        mock.patch.object(probe, "_active_swap_for") as active, \
                        mock.patch.object(probe, "_read_block0",
                                          return_value=backup) as header_read, \
                        mock.patch.object(probe, "_run") as command, \
                        mock.patch.object(probe, "_write_block0") as header_write:
                    with self.assertRaises(probe.ProbeError) as rejected:
                        probe.recover(
                            state_dir, state["device_arg"], state["device_arg"])
                    self.assertIn(diagnostic, str(rejected.exception))
                    self.assertIn(
                        "restoration_stage=not_attempted "
                        "ownership_marker_action=not_attempted; "
                        "manual recovery required", str(rejected.exception))
                    inspect.assert_not_called()
                    mapper.assert_not_called()
                    active.assert_not_called()
                    header_read.assert_not_called()
                    command.assert_not_called()
                    header_write.assert_not_called()
                self.assertEqual(state_path.read_bytes(), original_record)
                self.assertEqual(marker_path.read_bytes(), original_marker)
                self.assertEqual(consumed_path.read_bytes(), original_consumption)

    def test_recovery_refuses_to_remove_mapper_with_a_different_uuid(self):
        with tempfile.TemporaryDirectory() as temp:
            state_dir = Path(temp) / "state"
            state, _ = self.make_recovery_state(state_dir)
            calls = []

            def run(args, **kwargs):
                del kwargs
                calls.append(tuple(args))
                columns = " 253 0" if "major,minor" in args else ""
                return subprocess.CompletedProcess(
                    args, 0, stdout=state["dm_name"] +
                    " SWAPZ-TEST-PHYSICAL-ffffffffffffffff" + columns +
                    "\n", stderr="")

            with mock.patch.object(probe, "_validate_state_dir"), \
                    mock.patch.object(
                        probe, "inspect_target_identity_for_recovery",
                        return_value={"device": state["device"], "major": 8,
                                      "minor": 4, "size_bytes": state["size_bytes"]}), \
                    mock.patch.object(probe, "_run", side_effect=run), \
                    mock.patch.object(probe, "_write_block0") as write_header:
                with self.assertRaisesRegex(probe.ProbeError, "UUID|substituted|mapper"):
                    probe.recover(
                        state_dir, state["device_arg"], state["device_arg"])

        # The exact name/UUID mismatch now fails on the first inventory
        # query, before any destructive recovery command is considered.
        self.assertGreaterEqual(len(calls), 1)
        self.assertEqual(calls[0][:2], ("dmsetup", "info"))
        write_header.assert_not_called()

    def test_remote_branch_check_uses_sudo_invoking_users_ssh_identity(self):
        sha = "c" * 40
        result = subprocess.CompletedProcess(
            [], 0, stdout=f"{sha}\trefs/heads/main\n", stderr="")
        with mock.patch.dict(os.environ, {
                    "SUDO_USER": "keivan", "GIT_DIR": "/malicious",
                    "GIT_CONFIG_PARAMETERS": "url.bad.insteadOf=github.com"
                }), \
                mock.patch.object(probe.os, "geteuid", return_value=0), \
                mock.patch.object(probe.shutil, "which",
                                   return_value="/usr/sbin/runuser"), \
                mock.patch.object(probe, "_run", return_value=result) as run:
            self.assertEqual(probe._remote_main_sha(), sha)
        args = run.call_args.args[0]
        self.assertEqual(args[:4], [
            "/usr/sbin/runuser", "--user", "keivan", "--"])
        self.assertEqual(args[4:], [
            "git", "ls-remote", probe.CANONICAL_MAIN_REMOTE, "refs/heads/main"])
        self.assertEqual(run.call_args.kwargs["cwd"], "/")
        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["GIT_CONFIG_NOSYSTEM"], "1")
        self.assertEqual(environment["GIT_CONFIG_GLOBAL"], os.devnull)
        self.assertNotIn("GIT_DIR", environment)
        self.assertNotIn("GIT_CONFIG_PARAMETERS", environment)

    def test_partition_identity_uses_primary_partuuid_grammar(self):
        size_bytes = 1024 * 1024 * 1024
        for partuuid in (
                "--------", "-deadbeef", "deadbeef-",
                "deadbeef--01", "1234-567", "deadbeef.01"):
            with self.subTest(partuuid=partuuid), \
                    mock.patch.object(
                        probe, "_run",
                        return_value=subprocess.CompletedProcess(
                            args=[], returncode=0,
                            stdout=json.dumps({"blockdevices": [{
                                "type": "part", "partuuid": partuuid,
                                "size": size_bytes}]}),
                            stderr="")):
                with self.assertRaisesRegex(
                        probe.ProbeError, "stable PARTUUID"):
                    probe._partition_identity("/dev/test-partition")

        with mock.patch.object(
                probe, "_run",
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0,
                    stdout=json.dumps({"blockdevices": [{
                        "type": "part", "partuuid": "DEADBEEF-01",
                        "size": size_bytes}]}),
                    stderr="")), \
                mock.patch.object(
                    probe, "block_identity", return_value=(8, 1)):
            self.assertEqual(
                probe._partition_identity("/dev/test-partition"),
                ("deadbeef-01", size_bytes))

    def test_recovery_survives_removed_original_swap_uuid_symlink(self):
        """Formatting invalidates /dev/disk/by-uuid, not the saved PARTUUID."""
        state = {
            "device_arg": "/dev/disk/by-uuid/original-swap",
            "device": "/dev/nvme0n1p3",
            "major": 259, "minor": 3,
            "size_bytes": 1024 * 1024 * 1024,
            "partuuid": "deadbeef-03",
        }
        completed = subprocess.CompletedProcess(
            [], 0, stdout=str(state["size_bytes"]) + "\n", stderr="")
        with mock.patch.object(probe, "block_identity", return_value=(259, 3)), \
                mock.patch.object(
                    probe, "_partition_identity",
                    return_value=("deadbeef-03", state["size_bytes"])), \
                mock.patch.object(probe, "_physical_parent_identity",
                                  return_value="259:0"), \
                mock.patch.object(probe, "_run", return_value=completed), \
                mock.patch.object(
                    probe.Path, "resolve",
                    side_effect=AssertionError("old swap UUID link was removed")):
            target = probe.inspect_target_identity_for_recovery(
                state, state["device_arg"], state["device_arg"])
        self.assertEqual(target["device"], state["device"])
        self.assertEqual(target["partuuid"], state["partuuid"])

    def test_recovery_refuses_repurposed_partition(self):
        state = {
            "device_arg": "/dev/disk/by-uuid/old",
            "device": "/dev/sdb2",
            "major": 8, "minor": 18,
            "size_bytes": 1024 * 1024 * 1024,
            "partuuid": "deadbeef-02",
        }
        completed = subprocess.CompletedProcess(
            [], 0, stdout=str(state["size_bytes"]) + "\n", stderr="")
        with mock.patch.object(probe, "block_identity", return_value=(8, 18)), \
                mock.patch.object(
                    probe, "_partition_identity",
                    return_value=("cafebabe-02", state["size_bytes"])), \
                mock.patch.object(probe, "_run", return_value=completed):
            with self.assertRaisesRegex(
                    probe.ProbeError, "recovery_partuuid_size"):
                probe.inspect_target_identity_for_recovery(
                    state, state["device_arg"], state["device_arg"])

    def test_recovery_accepts_only_its_recorded_header_transitions(self):
        size = 1024 * 1024 * 1024
        original = b"O" * probe.PAGE_BYTES
        zero = bytes(probe.PAGE_BYTES)
        header = bytearray(probe.PAGE_BYTES)
        header[:8] = probe.SWAPZ_HEADER_MAGIC
        struct.pack_into("<IIQ", header, 8, 1, probe.PAGE_BYTES, size)
        header[24:40] = bytes(range(1, 17))
        formatted = bytes(header)
        digest = hashlib.sha256(formatted).hexdigest()
        state = {"stage": "HEADER_CLEARED"}
        probe._validate_recovery_header(original, original, state, size)
        probe._validate_recovery_header(zero, original, state, size)
        state["stage"] = "SWAP_OFF"
        probe._validate_recovery_header(zero, original, state, size)
        state["stage"] = "BACKED_UP"
        with self.assertRaisesRegex(probe.ProbeError, "manual review"):
            probe._validate_recovery_header(zero, original, state, size)
        with self.assertRaisesRegex(probe.ProbeError, "manual review"):
            probe._validate_recovery_header(formatted, original, state, size)
        state = {"stage": "MAPPED", "formatted_header_sha256": digest}
        probe._validate_recovery_header(formatted, original, state, size)
        with self.assertRaisesRegex(probe.ProbeError, "manual review"):
            probe._validate_recovery_header(zero, original, state, size)
        with self.assertRaisesRegex(probe.ProbeError, "manual review"):
            probe._validate_recovery_header(b"F" * probe.PAGE_BYTES, original,
                                            state, size)
        altered = bytearray(formatted)
        altered[24] ^= 1
        with self.assertRaisesRegex(probe.ProbeError, "manual review"):
            probe._validate_recovery_header(bytes(altered), original, state, size)
        state["stage"] = "RECOVERY_REQUIRED"
        state["stage_before_recovery"] = "MAPPED"
        probe._validate_recovery_header(formatted, original, state, size)

    def test_git_evidence_runs_as_the_sudo_operator(self):
        completed = subprocess.CompletedProcess([], 0, stdout="ok\n", stderr="")
        with mock.patch.object(probe.os, "geteuid", return_value=0), \
                mock.patch.dict(os.environ, {"SUDO_USER": "keivan"}), \
                mock.patch.object(probe.shutil, "which",
                                  return_value="/usr/sbin/runuser"), \
                mock.patch.object(probe, "_run",
                                  return_value=completed) as run:
            self.assertEqual(probe._git("status", "--porcelain"), "ok")
        args = run.call_args.args[0]
        self.assertEqual(
            args[:5],
            ["/usr/sbin/runuser", "--user", "keivan", "--", "git"])
        self.assertEqual(args[5:], ["status", "--porcelain"])
        self.assertEqual(run.call_args.kwargs["cwd"], probe.ROOT)

    def test_physical_host_gate_rejects_vm_container_and_unknown(self):
        with mock.patch.object(probe.shutil, "which",
                               return_value="/usr/bin/systemd-detect-virt"), \
                mock.patch.object(probe, "_run", side_effect=[
                    subprocess.CompletedProcess([], 1, stdout="none\n", stderr=""),
                    subprocess.CompletedProcess([], 1, stdout="none\n", stderr=""),
                ]) as run:
            probe._require_physical_host()
        self.assertEqual([call.args[0][1] for call in run.call_args_list],
                         ["--vm", "--container"])

        for output, code in (("kvm\n", 0), ("podman\n", 0), ("", 2)):
            with self.subTest(output=output, code=code), \
                    mock.patch.object(probe.shutil, "which",
                                      return_value="/usr/bin/systemd-detect-virt"), \
                    mock.patch.object(probe, "_run", return_value=
                                      subprocess.CompletedProcess(
                                          [], code, stdout=output,
                                          stderr="detection error")):
                with self.assertRaisesRegex(probe.ProbeError,
                                            "not allowed|cannot establish"):
                    probe._require_physical_host()

        with mock.patch.object(probe.shutil, "which", return_value=None):
            with self.assertRaisesRegex(probe.ProbeError,
                                        "systemd-detect-virt is required"):
                probe._require_physical_host()

    def test_verbal_approval_is_bound_to_exact_reviewer_wording(self):
        self.assertEqual(
            probe.VERBAL_APPROVAL_TEXT,
            "Approved for one bounded physical swap-partition correctness round-trip only, "
            "provided the exact qualified artifacts remain unchanged, the current "
            "helper-policy commit passes its non-privileged CI, the selected partition "
            "passes every read-only identity/safety check, recovery state is durably "
            "stored on persistent media, and the helper restores and verifies the "
            "original swap partition before completion. Any mismatch, unexpected state, "
            "or recovery uncertainty voids this approval and requires the run to stop.")

    def test_kernel_evidence_keeps_only_bounded_swapz_messages(self):
        output = "unrelated kernel detail\n" + "\n".join(
            f"kernel: dm-swapz warning {index}" for index in range(40))
        with mock.patch.object(probe.shutil, "which",
                               return_value="/usr/bin/journalctl"), \
                mock.patch.object(probe, "_run", return_value=
                                  subprocess.CompletedProcess(
                                      [], 0, stdout=output, stderr="")) as run:
            record = probe._kernel_swapz_messages("2026-11-02T12:00:00Z")
        self.assertTrue(record["available"])
        self.assertEqual(record["matching_line_count"], 40)
        self.assertNotIn("unrelated kernel detail", record["messages"])
        self.assertLessEqual(len(record["messages"]),
                             probe.MAX_RECORDED_OUTPUT_CHARS)
        self.assertIn("--since=2026-11-02T12:00:00Z",
                      run.call_args.args[0])

    def test_recovery_observations_use_durable_original_swap_parameters(self):
        header = b"S" * probe.PAGE_BYTES
        state = {
            "partuuid": "deadbeef-04",
            "run_id": "0123456789abcdef0123456789abcdef",
            "dm_name": "swapz-demo-physical-1234567890abcdef",
            "dm_uuid": "SWAPZ-TEST-PHYSICAL-1234567890abcdef",
            "stage": "COMPLETE",
            "swap_was_active": True,
            "swap_size_kib": 16777212,
            "swap_priority": -1,
        }
        # Standalone recovery supplies only identity fields, not swap capacity
        # or priority. Post-swapon usage may become nonzero immediately.
        target = {"device": "/dev/sda4", "major": 8, "minor": 4,
                  "size_bytes": 17179869184, "partuuid": "deadbeef-04"}
        expected_inventory = {"other_mapper_count": 0,
                              "other_mapper_sha256": hashlib.sha256(b"[]").hexdigest()}
        cases = (
            ({"kind": "partition", "size_kib": 16777212,
              "priority": -1, "used_kib": 720900}, True),
            ({"kind": "partition", "size_kib": 16777211,
              "priority": -1, "used_kib": 0}, False),
            ({"kind": "partition", "size_kib": 16777212,
              "priority": 1, "used_kib": 0}, False),
            (None, False),
        )
        with mock.patch.object(probe, "_read_block0", return_value=header), \
                mock.patch.object(probe, "_block_stat_snapshot",
                                  return_value={"available": False}), \
                mock.patch.object(probe, "_kernel_swapz_messages",
                                  return_value={"available": False}), \
                mock.patch.object(probe, "_mapper_exists",
                                  return_value=False), \
                mock.patch.object(probe, "_dm_inventory_snapshot",
                                  return_value=expected_inventory), \
                mock.patch.object(probe, "_save_results") as saved:
            for active_row, expected in cases:
                with self.subTest(row=active_row), mock.patch.object(
                        probe, "_active_swap_for", return_value=active_row):
                    results = {
                        "original_header_sha256": hashlib.sha256(
                            header).hexdigest(),
                        "start_timestamp": "2026-11-02T16:00:00Z",
                        "dm_inventory_before": expected_inventory,
                    }
                    probe._final_observations(
                        results, self.recovery_base, state, target)
                    self.assertEqual(results["restored_swap_verified"], expected)
                    self.assertEqual(results["final_swap_row"], active_row)
            self.assertEqual(saved.call_count, len(cases))
        missing_state = {**state, "swap_priority": None}
        with mock.patch.object(probe, "_read_block0", return_value=header), \
                mock.patch.object(probe, "_block_stat_snapshot",
                                  return_value={"available": False}), \
                mock.patch.object(probe, "_kernel_swapz_messages",
                                  return_value={"available": False}), \
                mock.patch.object(probe, "_mapper_exists",
                                  return_value=False), \
                mock.patch.object(probe, "_dm_inventory_snapshot",
                                  return_value=expected_inventory), \
                mock.patch.object(probe, "_active_swap_for",
                                  return_value=cases[0][0]), \
                mock.patch.object(probe, "_save_results"):
            results = {"original_header_sha256": hashlib.sha256(header).hexdigest(),
                       "dm_inventory_before": expected_inventory}
            probe._final_observations(
                results, self.recovery_base, missing_state, target)
            self.assertFalse(results["restored_swap_verified"])

    def test_kernel_log_falls_back_without_attributing_old_dmesg_to_run(self):
        def tool_path(command):
            return {"journalctl": "/usr/bin/journalctl",
                    "dmesg": "/usr/bin/dmesg"}.get(command)

        commands = []
        def run(command, **kwargs):
            del kwargs
            commands.append(tuple(command))
            if command[0] == "/usr/bin/journalctl":
                return subprocess.CompletedProcess(
                    command, 1, stdout="",
                    stderr="journalctl: journal unavailable")
            return subprocess.CompletedProcess(
                command, 0, stdout=(
                    "unrelated previous boot message\n"
                    "kernel: dm-swapz lower or mapping error -5 [old]\n"
                    "kernel: dm-swapz loaded\n"), stderr="")

        with mock.patch.object(probe.shutil, "which",
                               side_effect=tool_path), \
                mock.patch.object(probe, "_run", side_effect=run):
            record = probe._kernel_swapz_messages("2026-11-02T16:00:00Z")
        self.assertTrue(record["available"])
        self.assertEqual(record["source"], "dmesg")
        self.assertFalse(record["time_filter_applied"])
        self.assertEqual(record["matching_line_count"], 2)
        self.assertIn("journal unavailable", record["journalctl_error"])
        self.assertIn("lower or mapping error -5", record["messages"])
        self.assertEqual(len(commands), 2)
        self.assertIn("--dmesg", commands[0])
        self.assertIn("--since=2026-11-02T16:00:00Z", commands[0])
        self.assertIn("--time-format=iso", commands[1])

    def test_failed_kernel_log_fallback_is_not_reported_as_available(self):
        def tool_path(command):
            return {"journalctl": "/usr/bin/journalctl",
                    "dmesg": "/usr/bin/dmesg"}.get(command)
        with mock.patch.object(probe.shutil, "which",
                               side_effect=tool_path), \
                mock.patch.object(probe, "_run", return_value=
                    subprocess.CompletedProcess(
                        [], 1, stdout="", stderr="unsupported option")):
            record = probe._kernel_swapz_messages("2026-11-02T16:00:00Z")
        self.assertFalse(record["available"])
        self.assertEqual(record["source"], "dmesg")
        self.assertEqual(record["return_code"], 1)
        self.assertFalse(record["time_filter_applied"])
        self.assertIn("unsupported option", record["journalctl_error"])

    def test_live_host_gate_and_identical_artifact_history(self):
        source = "a" * 40
        earlier_source = "0" * 40
        head = "b" * 40
        local_host = {"schema": "swapz-host-v1", "architecture": "x86_64",
                      "id_sha256": "1" * 64}
        artifact_digests = {
            key: str(index) * 64 for index, (key, _, _) in
            enumerate(probe.PHYSICAL_ARTIFACTS, start=1)}
        changed_artifacts = {
            key: str(index + 3) * 64 for index, (key, _, _) in
            enumerate(probe.PHYSICAL_ARTIFACTS, start=1)}

        def report(report_source, *, duration=1, host=None, artifacts=None,
                   blocked=False):
            stages = [{"name": name, "status": "PASS", "exit_code": 0}
                      for name in probe.QUALIFICATION_STAGE_NAMES]
            if blocked:
                stages[-1]["status"] = "BLOCKED"
            return {
                "overall": "PASS" if not blocked else "BLOCKED",
                "tested_commit_sha": report_source,
                "source_sha": report_source,
                "host_identity": dict(host if host is not None else local_host),
                "qualified_artifacts": {
                    "status": "AVAILABLE",
                    **(artifacts if artifacts is not None else artifact_digests),
                },
                "stages": stages,
                "duration": duration,
            }

        current = report(source, duration=3)
        histories = {
            "latest": current,
            "earlier": report(earlier_source, duration=1),
            "duplicate": report(earlier_source, duration=1),
            "different-artifacts": report(
                earlier_source, duration=2, artifacts=changed_artifacts),
            "foreign-host": report(
                earlier_source, duration=4,
                host=dict(local_host, id_sha256="2" * 64)),
            "blocked": report(earlier_source, duration=5, blocked=True),
        }
        commits = ["policy-one", "policy-two"]
        changed_paths = {
            "policy-one": "tests/tools/physical-swap-probe.py",
            "policy-two": "docs/testing_standards.md",
        }
        publications = ["latest", "earlier", "duplicate",
                        "different-artifacts", "foreign-host", "blocked"]

        def git(*args, **kwargs):
            del kwargs
            if args[0] == "symbolic-ref":
                return "main"
            if args[0] == "status":
                return ""
            if args[0] == "rev-parse":
                return head
            if args[0] == "rev-list" and args[1:3] == (
                    "--reverse", "--first-parent"):
                return "\n".join(commits)
            if args[0] == "rev-list" and args[1:4] == (
                    "--parents", "-n", "1"):
                commit = args[4]
                parent = source if commit == "policy-one" else "policy-one"
                return f"{commit} {parent}"
            if args[0] == "diff-tree":
                return changed_paths[args[-1]]
            if args[0] == "log":
                self.assertIn("--first-parent", args)
                self.assertEqual(args[3], head)
                return "\n".join(publications)
            raise AssertionError(args)

        def git_result(*args, **kwargs):
            del kwargs
            if args[0] == "merge-base":
                child = args[2]
                parent = args[3]
                status = 0 if child in (source, earlier_source) and \
                    parent in (source, head) else 1
                return subprocess.CompletedProcess(args, status, stdout="", stderr="")
            if args[0] == "show":
                name = args[1].split(":")[0]
                return subprocess.CompletedProcess(
                    args, 0, stdout=json.dumps(histories[name]), stderr="")
            raise AssertionError(args)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "test_results.json").write_text(json.dumps(current))
            patches = (
                mock.patch.object(probe, "ROOT", root),
                mock.patch.object(probe.platform, "machine", return_value="x86_64"),
                mock.patch.object(probe, "_git", side_effect=git),
                mock.patch.object(probe, "_git_result", side_effect=git_result),
                mock.patch.object(probe, "_remote_main_sha", return_value=head),
                mock.patch.object(probe, "_require_physical_host"),
                mock.patch.object(probe, "live_host_identity", return_value=local_host),
            )
            with ExitStack() as stack:
                for patch in patches:
                    stack.enter_context(patch)
                evidence = probe.current_source_evidence()
                self.assertEqual(evidence["latest_source_reports"], 1)
                self.assertEqual(evidence["prior_matching_reports"], 1)
                self.assertEqual(evidence["pass_reports"], 2)
                self.assertEqual(evidence["artifact_digests"], artifact_digests)

                changed_paths["policy-two"] = "src/kernel/dm-target.c"
                with self.assertRaisesRegex(probe.ProbeError,
                                            "can affect qualified artifacts"):
                    probe.current_source_evidence()
                changed_paths["policy-two"] = "docs/testing_standards.md"
                histories["latest"] = report(source, blocked=True)
                (root / "test_results.json").write_text(
                    json.dumps(histories["latest"]))
                with self.assertRaisesRegex(probe.ProbeError, "five-stage"):
                    probe.current_source_evidence()
                histories["latest"] = report(source, duration=3)
                (root / "test_results.json").write_text(json.dumps(
                    report(source, duration=3,
                           host=dict(local_host, id_sha256="2" * 64))))
                with self.assertRaisesRegex(probe.ProbeError, "this x86_64 host"):
                    probe.current_source_evidence()

    def test_merge_after_qualified_source_blocks_physical_admission(self):
        def git(*args, **kwargs):
            del kwargs
            if args[1] == "--reverse":
                return "merge-commit"
            if args[1] == "--parents":
                return "merge-commit first-parent second-parent"
            raise AssertionError(args)

        with mock.patch.object(probe, "_git_result",
                               return_value=subprocess.CompletedProcess([], 0)), \
                mock.patch.object(probe, "_git", side_effect=git):
            with self.assertRaisesRegex(probe.ProbeError, "merge commits"):
                probe._check_post_qualification_paths("a" * 40, "b" * 40)

    def test_probe_is_not_wired_into_make_test_and_never_swapons_mapper(self):
        runner = (ROOT / "tools/run-tests.py").read_text()
        makefile = (ROOT.parent / "Makefile").read_text()
        script = SCRIPT.read_text()
        self.assertNotIn("physical-swap-probe.py", runner)
        self.assertNotIn("physical-swap-probe.py", makefile)
        self.assertIn('["swapon", target["device"]]', script)
        self.assertNotIn('["swapon", mapper]', script)
        self.assertNotIn('"--force"', script)
        self.assertNotIn("ssh-keygen", script)
        self.assertNotIn("allowed_signers", script)
        self.assertNotIn("REVIEW_NAMESPACE", script)
        self.assertIn("PROCEDURAL_NOT_CRYPTOGRAPHIC", script)



    def simulate_root_owned_directories(self, *directories):
        """Model root ownership in rootless CI; never chown host paths."""
        owned = {str(directory) for directory in directories}
        real_stat, real_lstat = probe.Path.stat, probe.Path.lstat

        def as_root(info):
            fields = list(info)
            fields[4] = 0  # st_uid in the os.stat_result tuple
            return os.stat_result(fields)

        def simulated_stat(path, *args, **kwargs):
            info = real_stat(path, *args, **kwargs)
            return as_root(info) if str(path) in owned else info

        def simulated_lstat(path, *args, **kwargs):
            info = real_lstat(path, *args, **kwargs)
            return as_root(info) if str(path) in owned else info

        stack = ExitStack()
        stack.enter_context(mock.patch.object(probe.Path, "stat", simulated_stat))
        stack.enter_context(mock.patch.object(probe.Path, "lstat", simulated_lstat))
        return stack

    def reviewed_device_fixture(self):
        """Build an immutable synthetic state to mutate verbal review fields."""
        header = bytearray(probe.PAGE_BYTES)
        header[-len(probe.SWAP_SIGNATURE):] = probe.SWAP_SIGNATURE
        target = {
            "major": 8, "minor": 4, "partuuid": "deadbeef-04",
            "size_bytes": 16 * 1024 * 1024 * 1024,
            "device_arg": "/dev/disk/by-uuid/test-swap",
            "header": bytes(header),
        }
        evidence = {
            "source_sha": "a" * 40,
            "head": "b" * 40,
            "helper_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
            "artifact_digests": {
                key: str(index) * 64 for index, (key, _, _) in
                enumerate(probe.PHYSICAL_ARTIFACTS, start=1)},
        }
        review = {
            **evidence["artifact_digests"],
            "approved": True,
            "approval_mode": "verbal",
            "approval_text": probe.VERBAL_APPROVAL_TEXT,
            "reviewer": probe.VERBAL_REVIEWER,
            "scope": probe.EXPECTED_SCOPE,
            "source_sha": evidence["source_sha"],
            "helper_git_sha": evidence["head"],
            "device_major_minor": "8:4",
            "device_partuuid": target["partuuid"],
            "device_size_bytes": target["size_bytes"],
            "original_header_sha256": hashlib.sha256(target["header"]).hexdigest(),
            "device_uuid_path": target["device_arg"],
            "run_id": "0123456789abcdef0123456789abcdef",
            "helper_sha256": evidence["helper_sha256"],
        }
        return target, evidence, review

    def test_verbal_review_rejects_changed_device_state_or_run_id(self):
        target, evidence, review = self.reviewed_device_fixture()
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.dict(os.environ, {"SUDO_USER": "operator"}):
            review_path = Path(directory) / "review.json"
            review_path.write_text(json.dumps(review))
            self.assertEqual(probe.validate_review(review_path, evidence, target),
                             {"reviewer": review["reviewer"],
                              "run_id": review["run_id"],
                              "approval_mode": "verbal"})
            for field, replacement in (
                ("device_size_bytes", target["size_bytes"] + 4096),
                ("device_major_minor", "8:5"),
                ("device_partuuid", "deadbeef-05"),
                ("helper_sha256", "f" * 64),
                ("source_sha", "f" * 40),
                ("formatter_sha256", "f" * 64),
                ("module_sha256", "f" * 64),
                ("oracle_sha256", "f" * 64),
                ("original_header_sha256", "f" * 64),
                ("device_uuid_path", "/dev/disk/by-uuid/substituted"),
                ("approval_text", "approval text was modified"),
                ("helper_git_sha", "c" * 40),
                ("run_id", "f" * 31),
                ("run_id", "A" * 32),
                ("run_id", "g" * 32),
                ("run_id", ""),
            ):
                with self.subTest(field=field, replacement=replacement):
                    changed = dict(review, **{field: replacement})
                    review_path.write_text(json.dumps(changed))
                    with self.assertRaises(probe.ProbeError):
                        probe.validate_review(review_path, evidence, target)
            for missing in ("device_size_bytes", "original_header_sha256",
                            "device_uuid_path", "run_id", "approval_text",
                            "approval_mode", "helper_git_sha",
                            "helper_sha256", "formatter_sha256",
                            "module_sha256", "oracle_sha256"):
                with self.subTest(missing=missing):
                    changed = dict(review)
                    del changed[missing]
                    review_path.write_text(json.dumps(changed))
                    with self.assertRaises(probe.ProbeError):
                        probe.validate_review(review_path, evidence, target)

    def physical_preparation_fixture(self):
        target, evidence, _ = self.reviewed_device_fixture()
        target.update({
            "device": "/dev/synthetic-physical-partition",
            "parent_major_minor": "8:0",
            "parent_model": "synthetic-card",
            "parent_transport": "usb",
            "parent_size_bytes": 128 << 20,
            "parent_removable": True,
            "card_identity_sha256": "a" * 64,
            "swap_path": target["device_arg"], "swap_priority": -1,
            "swap_size_kib": target["size_bytes"] // 1024,
            "swap_used_kib": 0,
        })
        evidence["pass_reports"] = 2
        evidence["latest_source_reports"] = 1
        evidence["prior_matching_reports"] = 1
        return target, evidence

    def test_refuses_volatile_recovery_state_before_backup(self):
        if not Path("/dev/shm").is_dir():
            self.skipTest("no known tmpfs location available")
        with tempfile.TemporaryDirectory(dir="/dev/shm") as directory:
            base = Path(directory)
            base.chmod(0o700)
            original_lstat = probe.Path.lstat

            def fake_lstat(path):
                info = original_lstat(path)
                fields = list(info)
                fields[4] = 0
                # Treat the sticky tmpfs parent as a trusted directory only
                # for this isolated filesystem-type negative control.
                if path != base:
                    fields[0] = stat.S_IFDIR | 0o755
                return os.stat_result(fields)

            def fake_run(args, **kwargs):
                del kwargs
                self.assertEqual(args[0], "findmnt")
                return subprocess.CompletedProcess(args, 0,
                    stdout="tmpfs\n", stderr="")

            with mock.patch.object(probe, "_recovery_base",
                                   REAL_RECOVERY_BASE), \
                    mock.patch.object(probe, "RECOVERY_BASE", base), \
                    mock.patch.object(probe.Path, "lstat",
                                      fake_lstat), \
                    mock.patch.object(probe, "_run", side_effect=fake_run):
                with self.assertRaisesRegex(probe.ProbeError,
                                            "nonpersistent|unverified"):
                    probe._recovery_base()

    def test_refuses_untrusted_parent_before_creating_state(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "untrusted"
            base.mkdir(mode=0o700)
            base.chmod(0o777)
            original_lstat = probe.Path.lstat

            def fake_lstat(path):
                info = original_lstat(path)
                fields = list(info)
                fields[4] = 0
                if path != base:
                    fields[0] = stat.S_IFDIR | 0o755
                return os.stat_result(fields)

            with mock.patch.object(probe, "_recovery_base",
                                   REAL_RECOVERY_BASE), \
                    mock.patch.object(probe, "RECOVERY_BASE", base), \
                    mock.patch.object(probe.Path, "lstat", fake_lstat):
                with self.assertRaisesRegex(probe.ProbeError,
                                            "root-controlled"):
                    probe._recovery_base()

    def test_missing_or_unverifiable_recovery_base_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "missing"
            with mock.patch.object(probe, "_recovery_base", REAL_RECOVERY_BASE), \
                    mock.patch.object(probe, "RECOVERY_BASE", missing):
                with self.assertRaisesRegex(probe.ProbeError, "missing"):
                    probe._recovery_base()

            base = root / "base"
            base.mkdir(mode=0o700)
            def root_owned_lstat(path):
                info = os.lstat(path)
                fields = list(info)
                fields[4] = 0
                if path != base:
                    fields[0] = stat.S_IFDIR | 0o755
                return os.stat_result(fields)

            def run(command, **kwargs):
                del kwargs
                if command[:5] == [
                        "findmnt", "--first-only", "--noheadings",
                        "--output", "FSTYPE"]:
                    return subprocess.CompletedProcess(
                        command, 0, stdout="ext4\n", stderr="")
                if command[:5] == [
                        "findmnt", "--first-only", "--noheadings",
                        "--output", "SOURCE"]:
                    return subprocess.CompletedProcess(
                        command, 0, stdout="overlay\n", stderr="")
                raise AssertionError(command)

            with mock.patch.object(probe, "_recovery_base", REAL_RECOVERY_BASE), \
                    mock.patch.object(probe, "RECOVERY_BASE", base), \
                    mock.patch.object(probe.Path, "lstat",
                                      root_owned_lstat), \
                    mock.patch.object(probe, "_run", side_effect=run):
                with self.assertRaisesRegex(
                        probe.ProbeError, "verified persistent block source"):
                    probe._recovery_base()

    def test_parent_entry_fsync_failure_prevents_state_admission(self):
        target, evidence = self.physical_preparation_fixture()
        _, _, review = self.reviewed_device_fixture()
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(probe, "_allocate_dm_identity",
                    return_value=("swapz-demo-physical-1234567890abcdef",
                                  "SWAPZ-TEST-PHYSICAL-1234567890abcdef")), \
                mock.patch.object(probe, "_verify_target_identity"), \
                mock.patch.object(probe, "_read_block0",
                                  return_value=target["header"]):
            base = Path(directory)
            state_dir = base / "attempt"
            base.chmod(0o700)
            events = []

            def directory_sync(path):
                events.append(path)
                if path == base:
                    raise OSError("injected parent-entry fsync failure")

            with self.simulate_root_owned_directories(base, state_dir), \
                    mock.patch.object(probe, "_fsync_directory",
                                      side_effect=directory_sync):
                with self.assertRaisesRegex(Exception,
                                            "parent-entry fsync failure"):
                    probe._prepare_state(target, state_dir, evidence, review)
            self.assertIn(base, events)
            self.assertFalse((state_dir / probe.STATE_NAME).exists())

    def test_original_header_read_refuses_unverified_regular_descriptor(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lookalike-partition"
            path.write_bytes(b"\0" * probe.PAGE_BYTES)
            with self.assertRaisesRegex(probe.ProbeError,
                                        "block|descriptor|identity|major:minor"):
                probe._read_block0(str(path), {"major": 8, "minor": 4,
                                              "size_bytes": probe.PAGE_BYTES})

    def simulate_physical_run(self, wrong_mapper=False, mapper_fault=None,
                              identity_failure_at=None,
                              oracle_failure_at=None,
                              missing_lower_after_at=None,
                              truncated_oracle_at=None,
                              teardown_missing_gate=False,
                              teardown_not_complete=False,
                              teardown_fabricated_lower=False,
                              development_only=False,
                              source_drift=None,
                              helper_sha_mismatch=False,
                              artifact_drift_before_mutation=False,
                              recovery_failure=False):
        """Use actual helper checks with only device/command interfaces mocked."""
        target, evidence = self.physical_preparation_fixture()
        if development_only:
            target["swap_was_active"] = False
            evidence.update({
                "source_sha": evidence["head"],
                "development_only": True,
                "scope": probe.DEVELOPMENT_SCOPE,
            })
        if helper_sha_mismatch:
            evidence["helper_sha256"] = "f" * 64
        token = "1234567890abcdef"
        fault = mapper_fault or ("uuid" if wrong_mapper else None)
        state = {
            "dm_name": f"swapz-demo-physical-{token}",
            "dm_uuid": f"SWAPZ-TEST-PHYSICAL-{token}",
            "stage": "BACKED_UP", "module_ownership": "NOT_STARTED",
        }
        review = {"reviewer": probe.VERBAL_REVIEWER,
                  "approval_mode": "verbal",
                  "run_id": "0123456789abcdef0123456789abcdef"}
        state.update({
            "run_id": review["run_id"], "partuuid": target["partuuid"],
            "major": target["major"], "minor": target["minor"],
            "device_arg": target["device_arg"],
            "device": target["device"], "size_bytes": target["size_bytes"],
            "swap_size_kib": target["swap_size_kib"],
            "swap_priority": target["swap_priority"],
            "swap_was_active": not development_only,
            "development_only": development_only,
        })
        formatted = bytearray(probe.PAGE_BYTES)
        formatted[:8] = probe.SWAPZ_HEADER_MAGIC
        struct.pack_into("<IIQ", formatted, 8,
                         probe.SWAPZ_HEADER_VERSION, probe.PAGE_BYTES,
                         target["size_bytes"])
        formatted[24:40] = bytes(range(1, 17))
        mapper = f"/dev/mapper/{state['dm_name']}"
        events = []
        # Model actual block-zero bytes, rather than inferring a write from
        # the number of reads. A second read before a write must be identical.
        observed_block_zero = target["header"]
        identity_verifications = 0
        oracle_invocations = 0
        counter_reads = 0
        artifact_samples = 0

        def checked_git(*args):
            if args[:2] == ("rev-parse", "HEAD") and source_drift == "local":
                return "c" * 40
            if args[:2] == ("rev-parse", "origin/main") and source_drift == "origin":
                return "c" * 40
            if args[0] == "status" and source_drift == "dirty":
                return " M tests/runtime/native/physical-swap-probe-test.py"
            return evidence["head"] if args[0] == "rev-parse" else ""

        def artifact_digests():
            nonlocal artifact_samples
            artifact_samples += 1
            if artifact_drift_before_mutation and artifact_samples > 1:
                return {**evidence["artifact_digests"], "oracle_sha256": "f" * 64}
            return evidence["artifact_digests"]

        def verify_target(_target):
            nonlocal identity_verifications
            identity_verifications += 1
            events.append(("verify", identity_verifications))
            if identity_failure_at == identity_verifications:
                raise probe.ProbeError(
                    f"injected identity change at boundary {identity_verifications}")

        def run(command, **kwargs):
            nonlocal oracle_invocations, observed_block_zero
            del kwargs
            arguments = tuple(str(value) for value in command)
            events.append(("command", arguments))
            if command[:2] == ["/reviewed/swapzctl", "format"]:
                observed_block_zero = bytes(formatted)
            if command[0] == "/reviewed/device-roundtrip":
                oracle_invocations += 1
                if oracle_invocations == oracle_failure_at:
                    return subprocess.CompletedProcess(
                        command, 1, stdout="FAIL injected physical phase\n",
                        stderr="injected phase failure\n")
                if oracle_invocations == truncated_oracle_at:
                    return subprocess.CompletedProcess(
                        command, 0,
                        stdout="TRACE" * probe.MAX_RECORDED_OUTPUT_CHARS,
                        stderr="")
            if command[:2] == ["dmsetup", "info"]:
                if command == ["dmsetup", "info", "-c", "--noheadings",
                               "-o", "name,uuid"]:
                    # The simulated host has no unrelated mapper devices.
                    # Match dmsetup's exact successful empty-inventory output;
                    # blank stdout is intentionally rejected by the helper.
                    output = "No devices found\n"
                    return subprocess.CompletedProcess(
                        command, 0, stdout=output, stderr="")
                if "name,uuid,major,minor" not in command:
                    return subprocess.CompletedProcess(
                        command, 0, stdout="", stderr="")
                wrong_uuid = fault == "uuid" or (fault == "substitution" and
                         sum(event[0] == "command" and
                             event[1][:2] == ("dmsetup", "info")
                             for event in events) >= 2)
                uuid = ("SWAPZ-TEST-PHYSICAL-ffffffffffffffff"
                        if wrong_uuid else state["dm_uuid"])
                output = f"{state['dm_name']}:{uuid}:253:0\n"
            elif command[:2] == ["dmsetup", "table"]:
                table = probe._expected_dm_table(target)
                if fault == "table":
                    table = table[:-1] + ("1" if table[-1] != "1" else "0")
                output = table + "\n"
            elif command[:2] == ["dmsetup", "status"]:
                output = f"0 {probe.LOGICAL_SECTORS} swapz failed=0 error=0\n"
            else:
                output = ""
            return subprocess.CompletedProcess(command, 0,
                                               stdout=output, stderr="")

        def read_text(path, *args, **kwargs):
            nonlocal counter_reads
            value = str(path)
            if value.endswith("/parameters/allow_physical_backing"):
                return "Y\n"
            if value.endswith("/dm/name"):
                return state["dm_name"] + "\n"
            if value.endswith("/dm/uuid"):
                return state["dm_uuid"] + "\n"
            if value.endswith("/size"):
                return str(probe.LOGICAL_SECTORS - (8 if fault == "size" else 0)) + "\n"
            if value.endswith("/slaves/synthetic/dev"):
                return f"{target['major']}:{target['minor'] + (1 if fault == 'lower' else 0)}\n"
            if value.endswith("/stat"):
                counter_reads += 1
                if counter_reads == missing_lower_after_at:
                    return "0 0 0\n"  # Missing required kernel counters.
                return " ".join(["0"] * probe.MIN_BLOCK_STAT_FIELDS) + "\n"
            return REAL_PATH_READ_TEXT(path, *args, **kwargs)

        def is_file(path):
            return str(path).endswith("/parameters/allow_physical_backing")

        def read_block0(_device, _target):
            return observed_block_zero

        def write_block0(_device, header, _target, **kwargs):
            nonlocal observed_block_zero
            del kwargs
            events.append(("write0",))
            observed_block_zero = bytes(header)

        def iter_directory(path):
            if str(path) == "/sys/dev/block/253:0/slaves":
                return iter([Path("/sys/dev/block/253:0/slaves/synthetic")])
            raise AssertionError(f"unexpected sysfs listing: {path}")

        def remove_test_objects(saved_state, saved_state_dir):
            nonlocal observed_block_zero

            if teardown_not_complete:
                saved_state["stage"] = "ORACLE_PASS"
            else:
                # Production recovery restores and rereads block zero before
                # marking recovery complete and releasing partition ownership.
                observed_block_zero = target["header"]
                events.append(("restore0",))
                saved_state["stage"] = "COMPLETE"
            probe._release_partition_ownership(saved_state)
            result_path = Path(saved_state_dir) / probe.RESULTS_NAME
            saved_results = json.loads(result_path.read_text())
            inventory_after = probe._dm_inventory_snapshot(
                saved_state["dm_name"], saved_state["dm_uuid"])
            inventory_before = saved_results["dm_inventory_before"]
            # Synthetic normal teardown: never invent a physical measurement.
            saved_results["block_stats_after"] = probe._block_stat_snapshot(target)
            saved_results["lower_io_delta"] = probe._lower_io_delta(
                saved_results["block_stats_before"],
                saved_results["block_stats_after"])
            saved_results["lower_io_evidence_gate"] = "AVAILABLE"
            if teardown_fabricated_lower:
                # A serialized AVAILABLE label must not override missing raw
                # counters when run_probe performs its final revalidation.
                saved_results["block_stats_after"] = {
                    "available": False, "error": "injected missing lower stat"}
            saved_results["kernel_swapz_messages"] = {
                "available": True, "time_filter_applied": True,
                "truncated": False, "matching_line_count": 0, "messages": "",
            }
            saved_results["kernel_diagnostics_gate"] = (
                "BLOCKED" if teardown_missing_gate else "AVAILABLE")
            saved_results.update({
                "final_block0_sha256": saved_results[
                    "original_header_sha256"],
                "original_header_matches_final": True,
                "final_swap_row": {
                    "kind": "partition",
                    "size_kib": target["swap_size_kib"],
                    "priority": target["swap_priority"],
                },
                "restored_swap_verified": True,
                "final_mapper_present": False,
                "final_module_present": False,
                "mapper_removal_succeeded": True,
                "module_cleanup_succeeded": True,
                "active_partition_marker_present": False,
                "approval_consumed": True,
                "final_recovery_state": saved_state["stage"],
                "dm_inventory_after": inventory_after,
                "unrelated_mapper_inventory_unchanged": (
                    inventory_before["other_mapper_count"] ==
                    inventory_after["other_mapper_count"] and
                    inventory_before["other_mapper_sha256"] ==
                    inventory_after["other_mapper_sha256"]),
                "end_timestamp": probe._utc_timestamp(),
            })
            saved_state["_test_results"] = saved_results
            probe._save_results(saved_state_dir, saved_results)
            return saved_state

        def checked_recovery(saved_state, saved_state_dir):
            events.append(("recover",))
            if recovery_failure:
                raise probe.ProbeError("injected recovery uncertainty")
            return remove_test_objects(saved_state, saved_state_dir)

        # Isolate each synthetic attempt from one-use approvals claimed earlier.
        # Otherwise, an approval-replay failure can mask a mapper-identity bug.
        # ExitStack avoids Python's limit on statically nested with-blocks.
        with tempfile.TemporaryDirectory() as directory:
            patches = (
                mock.patch.object(probe, "_recovery_base",
                                  return_value=Path(directory)),
                mock.patch.object(probe.os, "geteuid", return_value=0),
                mock.patch.object(probe, "current_source_evidence",
                                  return_value=evidence),
                mock.patch.object(probe, "current_development_evidence",
                                  return_value=evidence),
                mock.patch.object(probe,
                                  "require_development_formatter_inventory_clear"),
                mock.patch.object(probe.secrets, "token_hex",
                                  return_value=review["run_id"]),
                mock.patch.object(probe, "_git", side_effect=checked_git),
                mock.patch.object(probe, "_remote_main_sha",
                                  return_value=("c" * 40 if source_drift == "remote"
                                                else evidence["head"])),
                mock.patch.object(probe, "inspect_target", return_value=target),
                mock.patch.object(probe, "_artifact_digests",
                                  side_effect=artifact_digests),
                mock.patch.object(
                    probe, "_kernel_swapz_messages",
                    return_value={
                        "available": True, "source": "journalctl",
                        "time_filter_applied": True, "truncated": False,
                        "matching_line_count": 0, "messages": "",
                    }),
                mock.patch.object(probe, "validate_review", return_value=review),
                mock.patch.object(probe.shutil, "which", return_value="/usr/bin/mock"),
                mock.patch.object(probe.Path, "exists", return_value=False),
                mock.patch.object(probe, "_module_loaded_from_sysfs",
                                  return_value=False),
                mock.patch.object(probe.Path, "is_file", is_file),
                mock.patch.object(probe.Path, "read_text", read_text),
                mock.patch.object(probe.Path, "iterdir", iter_directory),
                mock.patch.object(probe, "block_identity",
                                  return_value=(253, 1 if fault == "node" else 0)),
                mock.patch.object(probe, "_prepare_state",
                                  return_value=(state, Path(directory))),
                mock.patch.object(probe, "_snapshot_reviewed_artifacts",
                                  return_value={
                                      "formatter_sha256": "/reviewed/swapzctl",
                                      "module_sha256": "/reviewed/dm-swapz.ko",
                                      "oracle_sha256": "/reviewed/device-roundtrip",
                                  }),
                mock.patch.object(probe, "_verify_target_identity",
                                  side_effect=verify_target),
                mock.patch.object(
                    probe, "_active_swap_for",
                    side_effect=([None, None] if development_only else [{
                        "used_kib": 0,
                        "size_kib": target["swap_size_kib"],
                        "priority": target["swap_priority"],
                    }, None])),
                mock.patch.object(probe, "_write_block0",
                                  side_effect=write_block0),
                mock.patch.object(probe, "_read_block0",
                                  side_effect=read_block0),
                mock.patch.object(probe, "_save_state",
                                  side_effect=lambda *_:
                                  events.append(("save", state["stage"]))),
                mock.patch.object(probe, "_remove_test_objects",
                                  side_effect=checked_recovery),
                mock.patch.object(probe, "_run", side_effect=run),
            )
            with ExitStack() as active_patches:
                for patch in patches:
                    active_patches.enter_context(patch)

                def execute():
                    probe.run_probe(
                        target["device_arg"], target["device_arg"],
                        None if development_only else directory,
                        None if development_only else "/reviewed/review.json",
                        development_only=development_only)

                if teardown_not_complete:
                    with self.assertRaises(probe.ProbeError) as rejected:
                        execute()
                    self.assertEqual(
                        str(rejected.exception),
                        "partition ownership release refused: "
                        "restoration_stage expected='COMPLETE' "
                        "observed='ORACLE_PASS'; "
                        "ownership_marker_action=not_attempted")
                    # Read the durable failure record, not a synthetic PASS.
                    state["_test_results"] = json.loads(
                        (Path(directory) / probe.RESULTS_NAME).read_text())
                elif fault or identity_failure_at is not None or \
                        oracle_failure_at is not None or \
                        missing_lower_after_at is not None or \
                        truncated_oracle_at is not None or \
                        teardown_missing_gate or teardown_fabricated_lower or \
                        source_drift is not None or helper_sha_mismatch or \
                        artifact_drift_before_mutation or recovery_failure:
                    with self.assertRaisesRegex(
                            probe.ProbeError,
                            "mapper|UUID|identity|table|backing|injected|phase failed|oracle phase .* failed|restoration/evidence|final_recovery_state|main or the bound helper changed|qualified artifacts changed"):
                        execute()
                else:
                    execute()
                if (source_drift is not None or helper_sha_mismatch or
                        artifact_drift_before_mutation or recovery_failure):
                    state["_test_results"] = json.loads(
                        (Path(directory) / probe.RESULTS_NAME).read_text())
        return events, state, target

    def test_development_post_evidence_drift_is_pre_destructive(self):
        # A post-fast_test source change must retain its original refusal,
        # even when final identity checks observe an unchanged synthetic header.
        for drift in ("local", "origin", "dirty", "remote"):
            with self.subTest(drift=drift):
                events, state, target = self.simulate_physical_run(
                    development_only=True, source_drift=drift)
                self.assert_pre_destructive_source_refusal(
                    events, state, target, "main or the bound helper changed")

        for failure, options, reason in (
                ("helper", {"helper_sha_mismatch": True},
                 "main or the bound helper changed"),
                ("artifact", {"artifact_drift_before_mutation": True},
                 "qualified artifacts changed")):
            with self.subTest(failure=failure):
                events, state, target = self.simulate_physical_run(
                    development_only=True, **options)
                self.assert_pre_destructive_source_refusal(
                    events, state, target, reason)

    def assert_pre_destructive_source_refusal(self, events, state, target, reason):
        results = state["_test_results"]
        self.assertEqual(state["stage"], "PRE_DESTRUCTIVE_FAILED")
        self.assertEqual(results["final_recovery_state"],
                         "PRE_DESTRUCTIVE_FAILED")
        self.assertIn(reason, results["recovery_error"])
        self.assertEqual(results["physical_oracle_phases"], [])
        self.assertNotIn("oracle_suite", results)
        self.assertEqual(
            results["original_header_sha256"],
            hashlib.sha256(target["header"]).hexdigest())
        self.assertTrue(results["original_header_matches_final"])
        self.assertNotIn(("write0",), events)
        self.assertFalse(any(event[0] == "recover" for event in events))
        commands = [event[1] for event in events if event[0] == "command"]
        self.assertFalse(any(
            command[0] in {"swapoff", "swapon", "insmod", "modprobe",
                           "/reviewed/swapzctl", "/reviewed/device-roundtrip"} or
            command[:2] == ("dmsetup", "create") for command in commands),
            f"physical command executed after source refusal: {commands}")

    def test_development_artifact_mismatch_blocks_before_recovery_or_write(self):
        # A fresh development PASS cannot authorize substituted build bytes.
        target, evidence = self.physical_preparation_fixture()
        target["swap_was_active"] = False
        evidence["development_only"] = True
        evidence["scope"] = probe.DEVELOPMENT_SCOPE
        changed_artifacts = dict(evidence["artifact_digests"])
        changed_artifacts["oracle_sha256"] = "f" * 64
        with mock.patch.object(probe.os, "geteuid", return_value=0), \
                mock.patch.object(
                    probe, "require_development_formatter_inventory_clear"), \
                mock.patch.object(
                    probe, "current_development_evidence",
                    return_value=evidence) as development, \
                mock.patch.object(
                    probe, "inspect_target", return_value=target) as inspect, \
                mock.patch.object(
                    probe, "_artifact_digests",
                    return_value=changed_artifacts), \
                mock.patch.object(probe, "_prepare_state") as prepare, \
                mock.patch.object(probe, "_write_block0") as write:
            with self.assertRaisesRegex(
                    probe.ProbeError,
                    "current build artifacts differ from admitted evidence"):
                probe.run_probe(
                    target["device_arg"], target["device_arg"], None, None,
                    development_only=True)
        # This test is about the artifact boundary, not where the helper
        # chooses to generate its fresh development nonce.
        development.assert_called_once()
        inspect.assert_called_once_with(
            target["device_arg"], target["device_arg"],
            allow_inactive_swap=True)
        prepare.assert_not_called()
        write.assert_not_called()

    def test_development_active_inventory_blocks_before_test_or_header_write(self):
        rows = (
            "/swapfile file 524284 478600 -1\n",
            "/dev/foreign-swap partition 262140 0 -2\n",
        )
        for row in rows:
            with self.subTest(row_kind=row.split()[1]):
                contents = "Filename Type Size Used Priority\n" + row

                def read_inventory(path, *args, **kwargs):
                    del args, kwargs
                    if str(path) != "/proc/swaps":
                        self.fail(f"unexpected read before inventory refusal: {path}")
                    return contents

                with mock.patch.object(probe.os, "geteuid", return_value=0), \
                        mock.patch.object(
                            probe.Path, "read_text", autospec=True,
                            side_effect=read_inventory), \
                        mock.patch.object(
                            probe, "current_development_evidence") as evidence, \
                        mock.patch.object(probe, "inspect_target") as inspect, \
                        mock.patch.object(probe, "_write_block0") as write:
                    with self.assertRaisesRegex(
                            probe.ProbeError,
                            "phase=preflight .*formatter_inventory .*"
                            "active_rows count=1 header_mutation=not_attempted"):
                        probe.run_probe(
                            "/dev/disk/by-uuid/test-swap",
                            "/dev/disk/by-uuid/test-swap", None, None,
                            development_only=True)
                evidence.assert_not_called()
                inspect.assert_not_called()
                write.assert_not_called()

    def test_development_formatter_inventory_fails_closed_without_a_full_table(self):
        with mock.patch.object(
                probe.Path, "read_text",
                return_value="Filename Type Size Used Priority\n"):
            self.assertIsNone(
                probe.require_development_formatter_inventory_clear())

        with mock.patch.object(
                probe.Path, "read_text", return_value="Filename Type\n"):
            with self.assertRaisesRegex(
                    probe.ProbeError,
                    "expected=complete_table observed=malformed"):
                probe.require_development_formatter_inventory_clear()

        with mock.patch.object(
                probe.Path, "read_text",
                side_effect=PermissionError(13, "inventory unavailable")):
            with self.assertRaisesRegex(
                    probe.ProbeError,
                    "expected=readable_complete_table observed=errno_13 "
                    "header_mutation=not_attempted"):
                probe.require_development_formatter_inventory_clear()

    def test_formatter_and_oracle_use_exact_reviewed_identity_arguments(self):
        events, state, target = self.simulate_physical_run()
        commands = [event[1] for event in events if event[0] == "command"]
        self.assertIn(("/reviewed/swapzctl", "format", target["device"],
                       "--expect-major-minor", "8:4", "--expect-bytes",
                       str(target["size_bytes"]), "--expect-partuuid",
                       target["partuuid"], "--expect-parent-major-minor",
                       target["parent_major_minor"], "--expect-parent-model",
                       target["parent_model"], "--expect-parent-transport",
                       target["parent_transport"]), commands)
        self.assertIn(("/reviewed/device-roundtrip",
                       f"/dev/mapper/{state['dm_name']}",
                       "--expect-dm-uuid", state["dm_uuid"]), commands)
        oracle = "/reviewed/device-roundtrip"
        mapper = f"/dev/mapper/{state['dm_name']}"
        oracle_commands = [command for command in commands
                           if command[0] == oracle]
        self.assertEqual(oracle_commands, [
            (oracle, mapper, "--expect-dm-uuid", state["dm_uuid"]),
            (oracle, mapper, "--delta64-write-series", "128", "1"),
            (oracle, mapper, "--delta64-verify-series", "128", "1"),
            (oracle, mapper, "--segmented-write-series", "128", "5"),
            (oracle, mapper, "--segmented-verify-series", "128", "5"),
            (oracle, mapper, "--verify-series", "128", "5"),
            (oracle, mapper, "--write-series", "128", "6"),
            (oracle, mapper, "--segmented-verify-series", "128", "6"),
            (oracle, mapper, "--thp-write-series", "128", "7"),
            (oracle, mapper, "--thp-verify-series", "128", "7"),
            (oracle, mapper, "--verify-series", "128", "7"),
        ])
        phases = state["_test_results"]["physical_oracle_phases"]
        self.assertEqual([entry["status"] for entry in phases], ["PASS"] * 11)
        empty_inventory = {
            "other_mapper_count": 0,
            "other_mapper_sha256": hashlib.sha256(b"[]").hexdigest(),
        }
        self.assertEqual(state["_test_results"]["dm_inventory_before"],
                         empty_inventory)
        self.assertEqual(state["_test_results"]["dm_inventory_after"],
                         empty_inventory)
        self.assertTrue(state["_test_results"][
            "unrelated_mapper_inventory_unchanged"])
        inventory_command = (
            "dmsetup", "info", "-c", "--noheadings", "-o", "name,uuid")
        self.assertEqual(commands.count(inventory_command), 2)
        for entry in phases:
            self.assertIn("dmsetup_status_before", entry)
            self.assertIn("dmsetup_status_after", entry)
            self.assertIn("block_stats_before", entry)
            self.assertIn("block_stats_after", entry)
        self.assertFalse(any(command[0] == "swapon" and
                             "swapz-demo" in " ".join(command)
                             for command in commands))
        self.assertFalse(any("--force" in command for command in commands))
        # An interrupted insmod must find the conservative pending state on disk.
        inserted = next(index for index, event in enumerate(events)
                        if event[0] == "command" and event[1][0] == "insmod")
        pending = events.index(("save", "MODULE_PENDING"))
        owned = events.index(("save", "MODULE_OWNED"))
        self.assertLess(pending, inserted)
        self.assertLess(inserted, owned)

    def test_failed_oracle_phase_stops_later_phases_and_recovers(self):
        events, state, _ = self.simulate_physical_run(oracle_failure_at=2)
        commands = [event[1] for event in events if event[0] == "command"]
        oracle_commands = [command for command in commands
                           if command[0] == "/reviewed/device-roundtrip"]
        self.assertEqual(len(oracle_commands), 2)
        phases = state["_test_results"]["physical_oracle_phases"]
        self.assertEqual([entry["status"] for entry in phases], ["PASS", "FAIL"])
        self.assertEqual(state["_test_results"]["final_recovery_state"],
                         "COMPLETE")
        self.assertNotEqual(state["_test_results"].get("oracle_suite"), "PASS")
        self.assertIn(("restore0",), events)

    def test_completed_byte_oracle_with_uncertain_recovery_is_not_physical_pass(self):
        # Completed synthetic mapper I/O and successful restoration are
        # independent claims. Recovery failure must never print a smoke PASS.
        events, state, _ = self.simulate_physical_run(recovery_failure=True)
        results = state["_test_results"]
        self.assertIn(("recover",), events)
        self.assertNotIn(("restore0",), events)
        self.assertEqual(state["stage"], "RECOVERY_REQUIRED")
        self.assertEqual(results["final_recovery_state"], "RECOVERY_REQUIRED")
        self.assertEqual(results["oracle_suite"], "PASS")
        self.assertEqual(len(results["physical_oracle_phases"]), 11)
        self.assertTrue(all(phase["status"] == "PASS"
                            for phase in results["physical_oracle_phases"]))
        self.assertIn("injected recovery uncertainty",
                      results["recovery_error"])

    def test_partition_identity_is_rechecked_after_clear_before_formatter(self):
        events, _, _ = self.simulate_physical_run()
        cleared = events.index(("write0",))
        formatted = next(index for index, event in enumerate(events) if
                         event[0] == "command" and
                         event[1][:2] == ("/reviewed/swapzctl", "format"))
        self.assertTrue(any(event[0] == "verify" for event in
                            events[cleared + 1:formatted]),
                        "partition was not rechecked immediately before formatter")

    def test_identity_changes_at_late_boundaries_stop_before_next_action(self):
        cases = (
            (2, "swapoff"),
            (4, "/reviewed/swapzctl"),
            (5, "dmsetup-create"),
            (6, "/reviewed/device-roundtrip"),
        )
        for boundary, forbidden in cases:
            with self.subTest(boundary=boundary):
                events, _, _ = self.simulate_physical_run(
                    identity_failure_at=boundary)
                commands = [event[1] for event in events
                            if event[0] == "command"]
                if forbidden == "dmsetup-create":
                    reached = any(command[:2] == ("dmsetup", "create")
                                  for command in commands)
                else:
                    reached = any(command[0] == forbidden
                                  for command in commands)
                self.assertFalse(
                    reached,
                    f"identity failure at boundary {boundary} reached {forbidden}")

    def test_wrong_created_mapper_identity_never_reaches_oracle(self):
        events, _, _ = self.simulate_physical_run(wrong_mapper=True)
        commands = [event[1] for event in events if event[0] == "command"]
        self.assertTrue(any(command[:2] == ("dmsetup", "info")
                            for command in commands),
                        "no post-create mapper identity query was attempted")
        self.assertFalse(any(command[0] == "/reviewed/device-roundtrip"
                             for command in commands),
                         "oracle ran after wrong mapper identity")

    def test_consumed_review_remains_consumed_after_partition_release(self):
        target, _, review = self.reviewed_device_fixture()
        probe._check_review_unconsumed(target, review["run_id"])
        probe._consume_review(target, review["run_id"])
        with self.assertRaisesRegex(probe.ProbeError, "consumed|outstanding"):
            probe._check_review_unconsumed(target, review["run_id"])
        state = {
            "stage": "COMPLETE", "run_id": review["run_id"],
            "partuuid": target["partuuid"], "major": target["major"],
            "minor": target["minor"],
        }
        probe._release_partition_ownership(state)
        self.assertFalse((self.recovery_base /
            f"partition-{target['partuuid']}.active").exists())
        with self.assertRaisesRegex(probe.ProbeError, "consumed"):
            probe._check_review_unconsumed(target, review["run_id"])
        with self.assertRaisesRegex(probe.ProbeError, "consumed"):
            probe._consume_review(target, review["run_id"])
        self.assertFalse((self.recovery_base /
            f"partition-{target['partuuid']}.active").exists())

    def test_wrong_mapper_table_size_lower_node_and_late_substitution(self):
        for mismatch in ("table", "size", "lower", "node", "substitution"):
            with self.subTest(mismatch=mismatch):
                events, _, _ = self.simulate_physical_run(mapper_fault=mismatch)
                commands = [event[1] for event in events
                            if event[0] == "command"]
                self.assertFalse(any(command[0] ==
                    "/reviewed/device-roundtrip" for command in commands),
                    "oracle reached after mapper substitution or geometry mismatch")

    def test_opened_header_fd_identity_and_geometry_checks(self):
        target = {"major": 8, "minor": 4,
                  "size_bytes": 16 * 1024 * 1024 * 1024}
        device_size = struct.pack("=Q", target["size_bytes"])

        def device_info(major, minor):
            return SimpleNamespace(st_mode=stat.S_IFBLK | 0o600,
                                   st_rdev=os.makedev(major, minor))

        with mock.patch.object(probe.os, "fstat",
                               return_value=device_info(8, 4)), \
                mock.patch.object(probe.fcntl, "ioctl",
                                  return_value=device_size):
            probe._verify_open_block_device(123, target)
        for major, minor, size in (
                (8, 5, target["size_bytes"]),
                (8, 4, target["size_bytes"] - probe.PAGE_BYTES)):
            with self.subTest(major=major, minor=minor, bytes=size), \
                    mock.patch.object(probe.os, "fstat",
                                      return_value=device_info(major, minor)), \
                    mock.patch.object(probe.fcntl, "ioctl",
                                      return_value=struct.pack("=Q", size)):
                with self.assertRaisesRegex(probe.ProbeError,
                                            "major:minor|geometry"):
                    probe._verify_open_block_device(123, target)

    def test_failed_state_file_fsync_never_publishes_recovery_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            with mock.patch.object(probe.os, "fsync",
                    side_effect=OSError("injected state fsync failure")):
                with self.assertRaisesRegex(OSError, "state fsync failure"):
                    probe._save_state(state_dir, {"stage": "BACKED_UP"})
            self.assertFalse((state_dir / probe.STATE_NAME).exists())

    def test_interrupted_module_load_requires_manual_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            state, _ = self.make_recovery_state(state_dir)
            state["module_ownership"] = "MODULE_PENDING"
            state["stage"] = "MODULE_PENDING"
            (state_dir / probe.STATE_NAME).write_text(json.dumps(state))
            with mock.patch.object(probe, "_validate_state_dir"), \
                    mock.patch.object(
                        probe, "inspect_target_identity_for_recovery",
                        return_value={"device": state["device"], "major": 8,
                                      "minor": 4, "size_bytes": state["size_bytes"]}), \
                    mock.patch.object(probe.Path, "exists", return_value=True), \
                    mock.patch.object(probe, "_write_block0") as write:
                with self.assertRaisesRegex(
                        probe.ProbeError, "module load interrupted|manual recovery"):
                    probe.recover(state_dir, state["device_arg"],
                                  state["device_arg"])
                write.assert_not_called()

    def test_recovery_removes_owned_mapper_without_force_and_swapons_partition(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            state, backup = self.make_recovery_state(state_dir)
            active = {
                "path": state["device"], "used_kib": 0,
                "size_kib": state["swap_size_kib"],
                "priority": state["swap_priority"],
            }
            commands = []

            def run(command, **kwargs):
                del kwargs
                commands.append(tuple(command))
                return subprocess.CompletedProcess(
                    command, 0, stdout="", stderr="")

            with mock.patch.object(probe, "_validate_state_dir"), \
                    mock.patch.object(
                        probe, "inspect_target_identity_for_recovery",
                        return_value={
                            "device": state["device"], "major": 8, "minor": 4,
                            "size_bytes": state["size_bytes"],
                            "partuuid": state["partuuid"],
                        }), \
                    mock.patch.object(probe.Path, "exists",
                                      return_value=False), \
                    mock.patch.object(probe, "_mapper_exists",
                                      side_effect=[True, False]), \
                    mock.patch.object(probe, "_verify_owned_mapper",
                                      return_value=f"/dev/mapper/{state['dm_name']}"), \
                    mock.patch.object(probe, "_run", side_effect=run), \
                    mock.patch.object(probe, "_holder_names", return_value=[]), \
                    mock.patch.object(probe, "_mountinfo_has_device",
                                      return_value=False), \
                    mock.patch.object(probe, "_read_block0",
                                      return_value=backup), \
                    mock.patch.object(probe, "_verify_target_identity"), \
                    mock.patch.object(
                        probe, "_active_swap_for",
                        side_effect=[None, None, active]), \
                    mock.patch.object(probe, "_save_state"), \
                    mock.patch.object(probe, "_release_partition_ownership"):
                recovered = probe.recover(
                    state_dir, state["device_arg"], state["device_arg"])

            self.assertEqual(recovered["stage"], "COMPLETE")
            self.assertIn(("dmsetup", "remove", state["dm_name"]), commands)
            self.assertFalse(any("--force" in command for command in commands))
            self.assertIn(("swapon", state["device"]), commands)
            mapper = f"/dev/mapper/{state['dm_name']}"
            self.assertFalse(any(command[0] == "swapon" and mapper in command
                                 for command in commands))


    def test_pre_destructive_failures_burn_run_and_prevent_replay(self):
        target, evidence = self.physical_preparation_fixture()
        original_exists = probe.Path.exists

        def is_present(path):
            if str(path) == "/sys/module/dm_swapz":
                return False
            return original_exists(path)

        for phase, run_id in (("prepare", "0" * 32), ("snapshot", "1" * 32)):
            with self.subTest(phase=phase):
                state_dir = self.recovery_base / f"attempt-{phase}"
                state_dir.mkdir(mode=0o700)
                review = {"reviewer": probe.VERBAL_REVIEWER,
                          "run_id": run_id, "approval_mode": "verbal"}
                state = {"stage": "BACKED_UP",
                         "dm_name": "swapz-demo-physical-1234567890abcdef",
                         "dm_uuid": "SWAPZ-TEST-PHYSICAL-1234567890abcdef",
                         "run_id": run_id,
                         "partuuid": target["partuuid"],
                         "major": target["major"],
                         "minor": target["minor"],
                         "device": target["device"],
                         "device_arg": target["device_arg"],
                         "size_bytes": target["size_bytes"],
                         "swap_size_kib": target["swap_size_kib"],
                         "swap_priority": target["swap_priority"]}
                prepare = mock.Mock(
                    return_value=(state, state_dir),
                    side_effect=(probe.ProbeError("injected prepare failure")
                                 if phase == "prepare" else None))
                snapshot = mock.Mock(
                    side_effect=probe.ProbeError("injected snapshot failure"))
                with ExitStack() as stack:
                    patches = (
                        mock.patch.object(probe.os, "geteuid", return_value=0),
                        mock.patch.object(probe.Path, "exists", autospec=True,
                                          side_effect=is_present),
                        mock.patch.object(probe, "_module_loaded_from_sysfs",
                                          return_value=False),
                        mock.patch.object(probe, "current_source_evidence",
                                          return_value=evidence),
                        mock.patch.object(probe, "inspect_target",
                                          return_value=target),
                        mock.patch.object(probe, "_artifact_digests",
                                          return_value=evidence["artifact_digests"]),
                        mock.patch.object(probe, "validate_review",
                                          return_value=review),
                        mock.patch.object(probe, "_dm_inventory_snapshot",
                                          return_value={
                                              "other_mapper_count": 0,
                                              "other_mapper_sha256": "a" * 64}),
                        mock.patch.object(
                            probe, "_block_stat_snapshot",
                            return_value={
                                "available": True,
                                "values": [0] * probe.MIN_BLOCK_STAT_FIELDS,
                                "device_major_minor":
                                    target["parent_major_minor"],
                                "sector_bytes": 512,
                            }),
                        mock.patch.object(probe, "_read_block0",
                                          return_value=target["header"]),
                        mock.patch.object(probe, "_active_swap_for",
                                          return_value={
                                              "kind": "partition",
                                              "size_kib": target["swap_size_kib"],
                                              "priority": target["swap_priority"]}),
                        mock.patch.object(probe, "_mapper_exists",
                                          return_value=False),
                        mock.patch.object(probe, "_kernel_swapz_messages",
                                          return_value={
                                              "available": True,
                                              "source": "journalctl",
                                              "time_filter_applied": True,
                                              "truncated": False,
                                              "matching_line_count": 0,
                                              "messages": ""}),
                        mock.patch.object(probe.shutil, "which",
                                          return_value="/usr/bin/mock"),
                        mock.patch.object(probe, "_prepare_state", prepare),
                        mock.patch.object(probe, "_snapshot_reviewed_artifacts",
                                          snapshot),
                        mock.patch.object(probe, "_run"),
                    )
                    for patch in patches:
                        stack.enter_context(patch)
                    external_commands = probe._run
                    for attempt in range(2):
                        with self.assertRaisesRegex(
                                probe.ProbeError,
                                "injected" if attempt == 0 else "consumed"):
                            probe.run_probe(target["device_arg"],
                                            target["device_arg"], str(state_dir),
                                            "/reviewed/signed-review.json")
                    external_commands.assert_not_called()
                    prepare.assert_called_once()
                    if phase == "prepare":
                        snapshot.assert_not_called()
                    else:
                        snapshot.assert_called_once()
                    consumed = self.recovery_base / f"consumed-{run_id}.json"
                    active = self.recovery_base / (
                        f"partition-{target['partuuid']}.active")
                    self.assertEqual(json.loads(consumed.read_text()),
                                     probe._review_consumption_record(target, run_id))
                    self.assertFalse(active.exists())
                    state_path = state_dir / probe.STATE_NAME
                    if phase == "snapshot":
                        self.assertEqual(json.loads(state_path.read_text())["stage"],
                                         "PRE_DESTRUCTIVE_FAILED")
                    else:
                        self.assertFalse(state_path.exists())

    def test_unverifiable_swap_entry_blocks_recovery(self):
        swaps = ("Filename Type Size Used Priority\n"
                 "/dev/unverifiable partition 4096 0 -1\n")
        with mock.patch.object(probe.Path, "read_text", return_value=swaps), \
                mock.patch.object(probe, "block_identity",
                                  side_effect=probe.ProbeError("unresolvable")):
            with self.assertRaisesRegex(
                    probe.ProbeError, "cannot verify active swap block identity"):
                probe._active_swap_for(8, 4)

    def test_unrelated_verified_swapfile_is_allowed(self):
        with tempfile.NamedTemporaryFile() as swapfile:
            inventory = ("Filename Type Size Used Priority\n"
                         f"{swapfile.name} file 4096 0 -1\n")
            with mock.patch.object(probe.Path, "read_text",
                                   return_value=inventory), \
                    mock.patch.object(probe, "block_identity") as block_lookup:
                self.assertIsNone(probe._active_swap_for(8, 4))
                block_lookup.assert_not_called()

    def test_module_continuity_prevents_standalone_unload(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            state, backup = self.make_recovery_state(state_dir)
            state["stage"] = "MODULE_OWNED"
            state["module_ownership"] = "MODULE_OWNED"
            (state_dir / probe.STATE_NAME).write_text(json.dumps(state))
            target = {"device": state["device"], "major": 8, "minor": 4,
                      "size_bytes": state["size_bytes"],
                      "partuuid": state["partuuid"]}
            active = {"path": state["device"], "used_kib": 0,
                      "size_kib": state["swap_size_kib"],
                      "priority": state["swap_priority"]}
            executed = []

            def run(command, **kwargs):
                del kwargs
                executed.append(tuple(command))
                if command == ["rmmod", "dm_swapz"]:
                    module_loaded[0] = False
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            module_loaded = [True]
            real_exists = Path.exists
            real_is_file = Path.is_file

            def module_exists(path):
                if str(path) == "/sys/module/dm_swapz":
                    return module_loaded[0]
                return real_exists(path)

            def module_is_file(path):
                if str(path).endswith(
                        "/parameters/allow_physical_backing"):
                    return True
                return real_is_file(path)

            with ExitStack() as stack:
                patches = (
                    mock.patch.object(probe, "_validate_state_dir"),
                    mock.patch.object(
                        probe, "inspect_target_identity_for_recovery",
                        return_value=target),
                    mock.patch.object(probe.Path, "exists", autospec=True,
                                      side_effect=module_exists),
                    mock.patch.object(probe.Path, "is_file", autospec=True,
                                      side_effect=module_is_file),
                    mock.patch.object(probe.Path, "read_text", return_value="Y"),
                    mock.patch.object(probe, "_mapper_exists", return_value=False),
                    mock.patch.object(probe, "_holder_names", return_value=[]),
                    mock.patch.object(probe, "_mountinfo_has_device",
                                      return_value=False),
                    mock.patch.object(probe, "_read_block0", return_value=backup),
                    mock.patch.object(probe, "_verify_target_identity"),
                    mock.patch.object(probe, "_active_swap_for",
                                      side_effect=[None, None, active]),
                    mock.patch.object(probe, "_save_state"),
                    mock.patch.object(probe, "_release_partition_ownership"),
                    mock.patch.object(probe, "_run", side_effect=run),
                    mock.patch.object(probe, "_write_block0"),
                )
                for patch in patches:
                    stack.enter_context(patch)
                header_write = probe._write_block0
                with self.assertRaisesRegex(
                        probe.ProbeError, "load continuity|manual recovery"):
                    probe.recover(state_dir, state["device_arg"],
                                  state["device_arg"])
                self.assertEqual(executed, [])
                header_write.assert_not_called()
                restored = probe.recover(
                    state_dir, state["device_arg"], state["device_arg"],
                    lock_held=True, module_owned_by_process=True)
                self.assertEqual(restored["stage"], "COMPLETE")
                self.assertEqual(
                    [command for command in executed if command[0] == "rmmod"],
                    [("rmmod", "dm_swapz")])
                self.assertFalse(any("--force" in command for command in executed))

    def test_recovery_rejects_wrong_restored_swap_capacity_and_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            state, backup = self.make_recovery_state(state_dir)
            state["swap_size_kib"] = state["size_bytes"] // 1024 - 4
            (state_dir / probe.STATE_NAME).write_text(json.dumps(state))
            active = {"path": state["device"], "used_kib": 0,
                      "size_kib": state["swap_size_kib"] - 8,
                      "priority": state["swap_priority"] + 1}
            commands = []

            def run(command, **kwargs):
                del kwargs
                commands.append(tuple(command))
                return subprocess.CompletedProcess(command, 0,
                    stdout=state["dm_uuid"] + "\n" if command[:2] ==
                    ["dmsetup", "info"] else "", stderr="")

            with mock.patch.object(probe, "_validate_state_dir"), \
                    mock.patch.object(probe, "inspect_target_identity_for_recovery",
                                      return_value={"device": state["device"],
                                        "major": 8, "minor": 4,
                                        "size_bytes": state["size_bytes"]}), \
                    mock.patch.object(probe, "_run", side_effect=run), \
                    mock.patch.object(probe, "_holder_names", return_value=[]), \
                    mock.patch.object(probe, "_mountinfo_has_device",
                                      return_value=False), \
                    mock.patch.object(probe, "_read_block0", return_value=backup), \
                    mock.patch.object(probe, "_active_swap_for",
                                      side_effect=[None, active, active]), \
                    mock.patch.object(probe, "_save_state") as save:
                with self.assertRaisesRegex(probe.ProbeError,
                                            "priority|capacity|size"):
                    probe.recover(state_dir, state["device_arg"],
                                  state["device_arg"])
            # Cleanup state is durably recorded before original swap geometry
            # is checked, so this path must save once before failing closed.
            save.assert_called_once()
            self.assertFalse(any(command[0] == "swapon" and
                                 "swapz-demo" in " ".join(command)
                                 for command in commands))

    def test_recovery_refuses_ambiguous_module_owner_before_header_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            state, backup = self.make_recovery_state(state_dir)
            state["module_loaded_by_us"] = False
            (state_dir / probe.STATE_NAME).write_text(json.dumps(state))
            with mock.patch.object(probe, "_validate_state_dir"), \
                    mock.patch.object(probe, "inspect_target_identity_for_recovery",
                                      return_value={"device": state["device"],
                                        "major": 8, "minor": 4,
                                        "size_bytes": state["size_bytes"]}), \
                    mock.patch.object(probe, "_run", return_value=
                                      subprocess.CompletedProcess([], 1,
                                          stdout="", stderr="")), \
                    mock.patch.object(probe.Path, "exists",
                                      return_value=True), \
                    mock.patch.object(probe, "_holder_names", return_value=[]), \
                    mock.patch.object(probe, "_mountinfo_has_device",
                                      return_value=False), \
                    mock.patch.object(probe, "_read_block0",
                                      return_value=bytes(probe.PAGE_BYTES)), \
                    mock.patch.object(probe, "_active_swap_for",
                                      return_value=None), \
                    mock.patch.object(probe, "_write_block0") as write:
                with self.assertRaisesRegex(probe.ProbeError,
                                            "module|owner|manual"):
                    probe.recover(state_dir, state["device_arg"],
                                  state["device_arg"])
            write.assert_not_called()


    def test_concurrent_attempts_cannot_claim_one_partition(self):
        """A second claim fails while another FD owns the real advisory lock."""
        target, _ = self.physical_preparation_fixture()
        real_fstat = probe.os.fstat

        def root_owned_fstat(descriptor):
            fields = list(real_fstat(descriptor))
            fields[4] = 0
            return os.stat_result(fields)

        with mock.patch.object(probe, "_partition_lock",
                               REAL_PARTITION_LOCK), \
                mock.patch.object(probe.os, "fstat",
                                  side_effect=root_owned_fstat):
            first = probe._partition_lock(target["partuuid"])
            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(probe._partition_lock,
                                             target["partuuid"])
                    with self.assertRaisesRegex(
                            probe.ProbeError, "owns this partition"):
                        future.result()
            finally:
                os.close(first)
            second = probe._partition_lock(target["partuuid"])
            os.close(second)

    def test_failed_backup_fsync_cannot_publish_saved_state(self):
        target, evidence = self.physical_preparation_fixture()
        _, _, review = self.reviewed_device_fixture()
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(probe, "_allocate_dm_identity",
                    return_value=("swapz-demo-physical-1234567890abcdef",
                                  "SWAPZ-TEST-PHYSICAL-1234567890abcdef")), \
                mock.patch.object(probe, "_verify_target_identity"), \
                mock.patch.object(probe, "_read_block0",
                                  return_value=target["header"]), \
                mock.patch.object(probe, "_fsync_directory"):
            base = Path(directory)
            state_dir = base / "attempt"
            base.chmod(0o700)
            with self.simulate_root_owned_directories(base, state_dir), \
                    mock.patch.object(probe.os, "fsync",
                        side_effect=OSError("injected backup fsync failure")):
                with self.assertRaisesRegex(Exception, "backup fsync failure"):
                    probe._prepare_state(target, state_dir, evidence, review)
            self.assertFalse((state_dir / probe.STATE_NAME).exists(),
                             "unflushed backup cannot authorize swapoff")


    def test_parent_topology_wrong_parent_and_missing_disk_are_blocked(self):
        # The fixture contains no real /dev access or sysfs dependency.
        with tempfile.TemporaryDirectory() as directory:
            disk = Path(directory) / "sdb"
            partition = disk / "sdb1"
            partition.mkdir(parents=True)
            (partition / "partition").write_text("1\n")
            (disk / "dev").write_text("8:16\n")
            (disk / "device").mkdir()
            # A real SD parent can be removable; identity must still match.
            (disk / "removable").write_text("1\n")
            original_resolve = probe.Path.resolve

            def resolve(path, *args, **kwargs):
                if str(path) == "/sys/dev/block/8:17":
                    return partition
                if str(path) == "/sys/dev/block/8:16":
                    return disk
                return original_resolve(path, *args, **kwargs)

            with mock.patch.object(probe.Path, "resolve", resolve):
                self.assertEqual(
                    probe._physical_parent_identity(8, 17), "8:16")
                (disk / "dev").write_text("8:18\n")
                with self.assertRaisesRegex(
                        probe.ProbeError,
                        "parent_topology|parent_major_minor.*expected"):
                    probe._physical_parent_identity(8, 17)
                (disk / "dev").write_text("8:16\n")
                (disk / "device").rmdir()
                with self.assertRaisesRegex(
                        probe.ProbeError,
                        "parent_topology expected=one physical disk "
                        "observed=missing_parent_device") as blocked:
                    probe._physical_parent_identity(8, 17)
                self.assertNotIn(directory, str(blocked.exception))

    def test_virtual_parent_name_is_not_physical_topology(self):
        with tempfile.TemporaryDirectory() as directory:
            disk = Path(directory) / "nbd0"
            partition = disk / "nbd0p1"
            partition.mkdir(parents=True)
            (partition / "partition").write_text("1\n")
            (disk / "dev").write_text("43:0\n")
            (disk / "device").mkdir()
            original_resolve = probe.Path.resolve

            def resolve(path, *args, **kwargs):
                if str(path) == "/sys/dev/block/43:1":
                    return partition
                if str(path) == "/sys/dev/block/43:0":
                    return disk
                return original_resolve(path, *args, **kwargs)

            with mock.patch.object(probe.Path, "resolve", resolve):
                with self.assertRaisesRegex(
                        probe.ProbeError,
                        "parent_topology expected=one physical disk"):
                    probe._physical_parent_identity(43, 1)

    def test_stale_swap_uuid_and_changed_device_block_preflight(self):
        probe._require_matching_swap_uuid(
            "/dev/disk/by-uuid/deadbeef-01", "DEADBEEF-01")
        with self.assertRaisesRegex(
                probe.ProbeError,
                "swap_uuid expected='deadbeef-01' observed='other'"):
            probe._require_matching_swap_uuid(
                "/dev/disk/by-uuid/deadbeef-01", "other")

        target = {"device": "/dev/synthetic-part", "major": 8,
                  "minor": 17, "parent_major_minor": "8:16",
                  "partuuid": "deadbeef-01", "size_bytes": 16 << 20}
        with mock.patch.object(probe, "block_identity", return_value=(8, 18)):
            with self.assertRaisesRegex(
                    probe.ProbeError,
                    "block identity changed.*selected_major_minor "
                    "expected=8:17 observed=8:18"):
                probe._verify_target_identity(target)
        with mock.patch.object(probe, "block_identity",
                               return_value=(8, 17)), \
                mock.patch.object(probe, "_run",
                    return_value=subprocess.CompletedProcess(
                        [], 0, stdout=str(target["size_bytes"]), stderr="")), \
                mock.patch.object(probe, "_partition_identity",
                    return_value=(target["partuuid"], target["size_bytes"])), \
                mock.patch.object(probe, "_physical_parent_identity",
                    return_value="8:32"):
            with self.assertRaisesRegex(
                    probe.ProbeError,
                    "parent_major_minor expected='8:16' observed='8:32'"):
                probe._verify_target_identity(target)

        # Do not substitute a partition with unchanged major:minor/geometry.
        with mock.patch.object(probe, "block_identity",
                               return_value=(8, 17)), \
                mock.patch.object(probe, "_run",
                    return_value=subprocess.CompletedProcess(
                        [], 0, stdout=str(target["size_bytes"]), stderr="")), \
                mock.patch.object(probe, "_partition_identity",
                    return_value=("changed-partuuid", target["size_bytes"])):
            with self.assertRaisesRegex(
                    probe.ProbeError,
                    "persistent_identity expected=.*observed=.*changed-partuuid"):
                probe._verify_target_identity(target)

    def test_saved_parent_card_fingerprint_is_rechecked(self):
        target = {
            "device": "/dev/synthetic-part", "major": 8, "minor": 17,
            "parent_major_minor": "8:16", "parent_model": "synthetic-card",
            "parent_transport": "usb", "card_identity_sha256": "a" * 64,
            "partuuid": "deadbeef-01", "size_bytes": 16 << 20,
        }
        with mock.patch.object(probe, "block_identity", return_value=(8, 17)), \
                mock.patch.object(
                    probe, "_run",
                    return_value=subprocess.CompletedProcess(
                        [], 0, stdout=str(target["size_bytes"]), stderr="")), \
                mock.patch.object(probe, "_partition_identity",
                                  return_value=(target["partuuid"],
                                                target["size_bytes"])), \
                mock.patch.object(probe, "_physical_parent_identity",
                                  return_value="8:16"), \
                mock.patch.object(
                    probe, "_campaign_card_identity",
                    return_value={
                        "sha256": "b" * 64,
                        "model": target["parent_model"],
                        "transport": target["parent_transport"],
                    }):
            with self.assertRaisesRegex(
                    probe.ProbeError,
                    "parent_card_identity changed during the operation"):
                probe._verify_target_identity(target)

    def test_selected_swap_usage_blocks_smoke_preflight(self):
        # This smoke requires an active but *unused* original swap; the
        # performance campaign instead requires an inactive selected card.
        device_arg = "/dev/disk/by-uuid/deadbeef-01"
        size_bytes = 64 << 20
        row = {"type": "part", "fstype": "swap", "uuid": "deadbeef-01",
               "size": size_bytes}
        lsblk = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps({"blockdevices": [row]}), stderr="")
        active = {"path": device_arg, "kind": "partition", "size_kib": 65532,
                  "used_kib": 128, "priority": -1}
        with mock.patch.object(probe.Path, "resolve",
                               return_value=Path("/dev/synthetic-part")), \
                mock.patch.object(probe.Path, "is_file", return_value=True), \
                mock.patch.object(probe.Path, "iterdir", return_value=iter(())), \
                mock.patch.object(probe, "block_identity",
                                  return_value=(8, 17)), \
                mock.patch.object(probe, "_physical_parent_identity",
                                  return_value="8:16"), \
                mock.patch.object(probe, "_mountinfo_has_device",
                                  return_value=False), \
                mock.patch.object(probe, "_require_root_not_on_target"), \
                mock.patch.object(probe, "_run", return_value=lsblk), \
                mock.patch.object(probe, "_partition_identity",
                                  return_value=("deadbeef-01", size_bytes)), \
                mock.patch.object(probe, "_active_swap_for",
                                  return_value=active):
            with self.assertRaisesRegex(
                    probe.ProbeError, "require zero used KiB"):
                probe.inspect_target(device_arg, device_arg)
            active["used_kib"] = 0
            active["priority"] = -2
            with self.assertRaisesRegex(
                    probe.ProbeError, "priority cannot be restored exactly"):
                probe.inspect_target(device_arg, device_arg)
            active["priority"] = -1
            active["size_kib"] = size_bytes // 1024 + 1
            with self.assertRaisesRegex(
                    probe.ProbeError, "capacity exceeds.*partition geometry"):
                probe.inspect_target(device_arg, device_arg)

    def test_lower_stat_parsing_is_strict_and_host_visible_only(self):
        target = {"parent_major_minor": "8:16"}
        good_values = [0] * probe.MIN_BLOCK_STAT_FIELDS
        for index, value in ((0, 4), (2, 8), (4, 5), (6, 10), (15, 2)):
            good_values[index] = value
        good = " ".join(str(value) for value in good_values) + "\n"
        with mock.patch.object(probe.Path, "read_text", return_value=good):
            snapshot = probe._block_stat_snapshot(target)
        self.assertTrue(snapshot["available"])
        self.assertEqual(snapshot["device_major_minor"], "8:16")
        self.assertEqual(snapshot["sector_bytes"], 512)
        self.assertEqual(len(snapshot["values"]), probe.MIN_BLOCK_STAT_FIELDS)

        negative = list(good_values)
        negative[2] = -1
        nonnumeric = list(good_values)
        nonnumeric[2] = "nan"
        counter_overflow = list(good_values)
        counter_overflow[0] = 2 ** 64
        sector_overflow = list(good_values)
        sector_overflow[2] = 2 ** 64 // 512
        for values, expected in (
                ([0] * 15,
                 "lower_flush_requests expected=field_16 observed=missing "
                 "field_count=15"),
                ([0] * 16, "lower_stat_fields expected=17 observed=16"),
                ([0] * 18, "lower_stat_fields expected=17 observed=18"),
                (negative, "lower_stat\\[2\\]"),
                (nonnumeric, "lower_stat\\[2\\]"),
                (counter_overflow, "uint64_max"),
                (sector_overflow, "uint64_max/512"),
        ):
            contents = " ".join(str(value) for value in values) + "\n"
            with self.subTest(contents=contents), mock.patch.object(
                    probe.Path, "read_text", return_value=contents):
                failed = probe._block_stat_snapshot(target)
                self.assertFalse(failed["available"])
                self.assertRegex(failed["error"], expected)
        self.assertFalse(probe._block_stat_snapshot({})["available"])

    def test_lower_delta_rejects_reset_wrap_substitution_and_unavailable(self):
        def snapshot(read_requests=3, read_sectors=4, write_requests=5,
                     write_sectors=6, flush_requests=7, parent="8:16"):
            values = [0] * probe.MIN_BLOCK_STAT_FIELDS
            for index, value in (
                    (0, read_requests), (2, read_sectors),
                    (4, write_requests), (6, write_sectors),
                    (15, flush_requests)):
                values[index] = value
            return {"available": True, "values": values,
                    "device_major_minor": parent, "sector_bytes": 512}
        before = snapshot()
        after = snapshot(4, 6, 8, 10, 9)
        self.assertEqual(probe._lower_io_delta(before, after), {
            "lower_read_requests": 1, "lower_read_bytes": 1024,
            "lower_write_requests": 3, "lower_write_bytes": 2048,
            "lower_flush_requests": 2,
        })
        for changed, expected in (
                (snapshot(2, 6, 8, 10, 9),
                 "lower_read_requests.*reset_or_wrap"),
                (snapshot(4, 3, 8, 10, 9),
                 "lower_read_sectors.*reset_or_wrap"),
                (snapshot(4, 6, 8, 5, 9),
                 "lower_write_sectors.*reset_or_wrap"),
                (snapshot(4, 6, 8, 10, 6),
                 "lower_flush_requests.*reset_or_wrap"),
                (snapshot(4, 6, 8, 10, 9, "8:32"), "lower_io_device"),
                ({**after, "values": [-1] + [0] * 16}, "uint64"),
                ({**after, "values": [2**64] + [0] * 16}, "uint64"),
                ({**after, "values": after["values"][:16]},
                 "expected=17_uint64_counters"),
                ({**after, "values": after["values"] + [0]},
                 "expected=17_uint64_counters"),
                ({"available": False, "error": "missing stat"},
                 "lower_io_after.*missing stat"),
        ):
            with self.subTest(expected=expected), self.assertRaisesRegex(
                    probe.ProbeError, expected):
                probe._lower_io_delta(before, changed)

    def test_unavailable_lower_io_and_truncated_oracle_cannot_pass(self):
        for argument in ("missing_lower_after_at", "truncated_oracle_at"):
            with self.subTest(argument=argument):
                injection_index = 3 if argument == "missing_lower_after_at" else 1
                events, state, _ = self.simulate_physical_run(
                    **{argument: injection_index})
                self.assertEqual(state["_test_results"]["physical_oracle_phases"][
                    0]["status"], "FAIL")
                first_phase = state["_test_results"]["physical_oracle_phases"][0]
                self.assertIn(
                    "lower_io_error" if argument == "missing_lower_after_at"
                    else "trace_error", first_phase)
                self.assertFalse(any(
                    event[0] == "command" and event[1][0] == "swapon" and
                    "swapz-demo" in " ".join(event[1]) for event in events))

    def test_normal_teardown_with_missing_diagnostics_cannot_report_success(self):
        events, state, _ = self.simulate_physical_run(
            teardown_missing_gate=True)
        self.assertEqual(state["_test_results"]["final_recovery_state"],
                         "COMPLETE")
        self.assertEqual(state["_test_results"]["kernel_diagnostics_gate"],
                         "BLOCKED")
        self.assertIn(("recover",), events)

    def test_dm_status_health_cannot_be_fabricated_from_missing_or_clipped_trace(self):
        healthy = ("0 " + str(probe.LOGICAL_SECTORS) +
                   " swapz some_counter=1 failed=0 error=0\n")
        def record(contents):
            return {"return_code": 0, "stdout": contents, "stderr": "",
                    "timed_out": False,
                    "stdout_truncated": False, "stderr_truncated": False}
        self.assertTrue(probe._swapz_status_healthy(record(healthy)))
        for contents in (
                "", "0 " + str(probe.LOGICAL_SECTORS) + " swapz\n",
                healthy.replace("failed=0", "failed=1"),
                healthy.replace("error=0", "error=-5"),
                healthy + healthy,
                healthy.replace("swapz", "linear"),
                healthy.replace("failed=0", "failed=0 failed=0"),
        ):
            with self.subTest(contents=contents):
                self.assertFalse(probe._swapz_status_healthy(record(contents)))
        self.assertFalse(probe._swapz_status_healthy({
            **record(healthy), "stdout_truncated": True}))
        with mock.patch.object(probe, "_run",
            return_value=subprocess.CompletedProcess(
                [], 0, stdout=healthy + "x" * probe.MAX_STATUS_OUTPUT_CHARS,
                stderr="")):
            truncated = probe._captured_command(["dmsetup", "status", "owned"])
        self.assertTrue(truncated["stdout_truncated"])
        self.assertFalse(probe._swapz_status_healthy(truncated))

    def test_serialized_available_lower_gate_cannot_hide_missing_counters(self):
        events, state, _ = self.simulate_physical_run(
            teardown_fabricated_lower=True)
        results = state["_test_results"]
        self.assertEqual(results["lower_io_evidence_gate"], "AVAILABLE")
        self.assertFalse(results["block_stats_after"]["available"])
        self.assertIn(("recover",), events)

    def test_incomplete_normal_teardown_never_publishes_smoke_pass(self):
        with mock.patch("builtins.print") as printed:
            events, state, _ = self.simulate_physical_run(
                teardown_not_complete=True)
        self.assertEqual(state["stage"], "RECOVERY_REQUIRED")
        self.assertEqual(state["stage_before_recovery"], "ORACLE_PASS")
        self.assertEqual(state["_test_results"]["final_recovery_state"],
                         "RECOVERY_REQUIRED")
        self.assertEqual(
            state["_test_results"]["recovery_error"],
            "partition ownership release refused: "
            "restoration_stage expected='COMPLETE' observed='ORACLE_PASS'; "
            "ownership_marker_action=not_attempted")
        self.assertIn(("recover",), events)
        self.assertIn(("save", "RECOVERY_REQUIRED"), events)
        self.assertFalse(any(
            call.args and str(call.args[0]).startswith("PHYSICAL_SMOKE=")
            for call in printed.call_args_list))

    def test_incomplete_restoration_cannot_release_partition_owner(self):
        target, _, review = self.reviewed_device_fixture()
        probe._consume_review(target, review["run_id"])
        owner_marker = (
            self.recovery_base / f"partition-{target['partuuid']}.active")
        consumed_review = (
            self.recovery_base / f"consumed-{review['run_id']}.json")
        state = {
            "run_id": review["run_id"],
            "partuuid": target["partuuid"],
            "major": target["major"],
            "minor": target["minor"],
        }
        for stage, observed in (
                ("ORACLE_PASS", "ORACLE_PASS"),
                ("/private/source/secret-" + "x" * 4096,
                 "invalid_or_unknown")):
            with self.subTest(stage=observed):
                state["stage"] = stage
                with self.assertRaises(probe.ProbeError) as rejected:
                    probe._release_partition_ownership(state)
                self.assertEqual(
                    str(rejected.exception),
                    "partition ownership release refused: "
                    "restoration_stage expected='COMPLETE' "
                    f"observed={observed!r}; "
                    "ownership_marker_action=not_attempted")
                self.assertTrue(owner_marker.is_file())
                self.assertTrue(consumed_review.is_file())

        # The stage gate runs before marker validation. Do not claim that an
        # active marker exists when damaged persisted state has already lost it.
        owner_marker.unlink()
        state["stage"] = "ORACLE_PASS"
        with self.assertRaises(probe.ProbeError) as rejected:
            probe._release_partition_ownership(state)
        self.assertEqual(
            str(rejected.exception),
            "partition ownership release refused: "
            "restoration_stage expected='COMPLETE' observed='ORACLE_PASS'; "
            "ownership_marker_action=not_attempted")
        self.assertFalse(owner_marker.exists())
        self.assertTrue(consumed_review.is_file())

    def test_read_only_plan_blocks_missing_lower_counters(self):
        target, _, _ = self.reviewed_device_fixture()
        target["parent_major_minor"] = "8:0"
        with mock.patch.object(probe, "inspect_target", return_value=target), \
                mock.patch.object(probe, "_block_stat_snapshot",
                    return_value={"available": False,
                                  "error": "lower_stat_fields expected=17 observed=0"}), \
                mock.patch.object(probe, "current_source_evidence",
                                  side_effect=AssertionError(
                                      "source evidence should not be consulted")):
            with self.assertRaisesRegex(
                    probe.ProbeError,
                    "preflight_lower_io expected=available.*lower_stat_fields"):
                probe.plan(target["device_arg"], target["device_arg"])

    def test_missing_lower_and_incomplete_kernel_evidence_block_final_gate(self):
        target = {"device": "/dev/synthetic", "major": 8, "minor": 17,
                  "size_bytes": 64 << 20, "parent_major_minor": "8:16"}
        state = {"partuuid": "deadbeef-01", "run_id": "a" * 32,
                 "stage": "COMPLETE", "swap_was_active": True,
                 "swap_size_kib": 65532, "swap_priority": -1,
                 "dm_name": "swapz-demo-physical-1234567890abcdef",
                 "dm_uuid": "SWAPZ-TEST-PHYSICAL-1234567890abcdef"}
        header = b"Z" * probe.PAGE_BYTES
        result = {"original_header_sha256": hashlib.sha256(header).hexdigest(),
                  "block_stats_before": {"available": False,
                                         "error": "counter device unavailable"}}
        with mock.patch.object(probe, "_read_block0", return_value=header), \
                mock.patch.object(probe, "_active_swap_for", return_value={
                    "kind": "partition", "size_kib": 65532,
                    "priority": -1}), \
                mock.patch.object(probe, "_block_stat_snapshot",
                                  return_value={"available": False,
                                                "error": "stat missing"}), \
                mock.patch.object(probe, "_kernel_swapz_messages",
                                  return_value={"available": True,
                                                "time_filter_applied": True,
                                                "truncated": True}), \
                mock.patch.object(probe, "_mapper_exists", return_value=False), \
                mock.patch.object(probe, "_dm_inventory_snapshot",
                                  return_value={"other_mapper_count": 0,
                                                "other_mapper_sha256": "x"}), \
                mock.patch.object(probe, "_save_results"):
            probe._final_observations(result, self.recovery_base, state, target)
        self.assertEqual(result["lower_io_evidence_gate"], "BLOCKED")
        self.assertIn("counter device unavailable",
                      result["lower_io_evidence_error"])
        self.assertEqual(result["kernel_diagnostics_gate"], "BLOCKED")
        self.assertIn("complete", result["kernel_diagnostics_error"])

    def test_final_evidence_blocker_is_sticky_across_teardown_reobservation(self):
        target = {
            "device": "/dev/synthetic", "major": 8, "minor": 17,
            "size_bytes": 64 << 20, "parent_major_minor": "8:16",
        }
        state = {
            "partuuid": "deadbeef-01", "run_id": "a" * 32,
            "stage": "COMPLETE", "swap_was_active": True,
            "swap_size_kib": 65532, "swap_priority": -1,
            "dm_name": "swapz-demo-physical-1234567890abcdef",
            "dm_uuid": "SWAPZ-TEST-PHYSICAL-1234567890abcdef",
        }
        header = b"Z" * probe.PAGE_BYTES
        values = [0] * probe.MIN_BLOCK_STAT_FIELDS
        available = {
            "available": True, "values": values,
            "device_major_minor": "8:16", "sector_bytes": 512,
        }
        unavailable = {"available": False, "error": "first stat missing",
                       "device_major_minor": "8:16"}
        truncated = {
            "available": True, "source": "journalctl",
            "time_filter_applied": True, "truncated": True,
            "matching_line_count": 0, "messages": "",
        }
        healthy = {
            "available": True, "source": "journalctl",
            "time_filter_applied": True, "truncated": False,
            "matching_line_count": 0, "messages": "",
        }
        inventory = {
            "other_mapper_count": 0,
            "other_mapper_sha256": hashlib.sha256(b"[]").hexdigest(),
        }
        result = {
            "original_header_sha256": hashlib.sha256(header).hexdigest(),
            "block_stats_before": available,
            "dm_inventory_before": inventory,
        }
        with mock.patch.object(probe, "_read_block0", return_value=header), \
                mock.patch.object(probe, "_active_swap_for", return_value={
                    "kind": "partition", "size_kib": 65532,
                    "priority": -1}), \
                mock.patch.object(
                    probe, "_block_stat_snapshot",
                    side_effect=[unavailable, available]), \
                mock.patch.object(
                    probe, "_kernel_swapz_messages",
                    side_effect=[truncated, healthy]), \
                mock.patch.object(probe, "_mapper_exists", return_value=False), \
                mock.patch.object(
                    probe, "_dm_inventory_snapshot", return_value=inventory), \
                mock.patch.object(probe.Path, "exists", return_value=False), \
                mock.patch.object(probe, "_save_results"):
            probe._final_observations(
                result, self.recovery_base, state, target)
            probe._final_observations(
                result, self.recovery_base, state, target)
        self.assertEqual(result["lower_io_evidence_gate"], "BLOCKED")
        self.assertIn("first stat missing", result["lower_io_evidence_error"])
        self.assertEqual(result["kernel_diagnostics_gate"], "BLOCKED")
        self.assertIn("complete", result["kernel_diagnostics_error"])
        self.assertIsNone(result["lower_io_delta"])
        self.assertEqual(result["block_stats_after"], unavailable)
        self.assertEqual(result["kernel_swapz_messages"], truncated)

    def test_kernel_diagnostics_rejects_failure_warning_and_unusable_trace(self):
        base = {
            "available": True, "source": "journalctl",
            "time_filter_applied": True, "truncated": False,
            "matching_line_count": 1,
        }
        self.assertIsNone(probe._kernel_diagnostics_error(
            {**base, "messages": "device-mapper: swapz alpha loaded"}))
        for changed, expected in (
                ({**base, "messages":
                  "device-mapper: swapz: terminal failure errno=-5"},
                 "no_swapz_failure_or_warning"),
                ({**base, "messages":
                  "kernel: WARNING: swapz invariant warning"},
                 "no_swapz_failure_or_warning"),
                ({**base, "truncated": True, "messages": ""},
                 "expected=complete"),
                ({**base, "time_filter_applied": False, "messages": ""},
                 "expected=time_filtered"),
                ({"available": False, "error": "journal unavailable"},
                 "expected=available"),
        ):
            with self.subTest(changed=changed):
                self.assertRegex(
                    probe._kernel_diagnostics_error(changed), expected)

    def test_campaign_quiescence_rejects_any_selected_card_active_swap(self):
        target = {
            "device": "/dev/synthetic", "major": 8, "minor": 17,
            "parent_major_minor": "8:16", "partuuid": "deadbeef-01",
            "card_identity_sha256": "a" * 64,
            "size_bytes": 64 << 20,
        }
        active = {
            "path": "/dev/disk/by-partuuid/deadbeef-01",
            "kind": "partition", "size_kib": 65532,
            "used_kib": 0, "priority": -1,
        }
        with mock.patch.object(probe, "_verify_target_identity"), \
                mock.patch.object(
                    probe, "_campaign_card_identity",
                    return_value={
                        "sha256": "a" * 64,
                        "model": "synthetic-card",
                        "transport": "usb",
                    }), \
                mock.patch.object(probe, "_holder_names", return_value=[]), \
                mock.patch.object(probe, "_mountinfo_has_device",
                                  return_value=False), \
                mock.patch.object(probe, "_active_swap_for",
                                  return_value=active):
            with self.assertRaisesRegex(
                    probe.ProbeError,
                    "campaign_active_swap expected=absent.*used_kib=0") as blocked:
                probe._require_campaign_target_quiescent(target)
            self.assertNotIn(active["path"], str(blocked.exception))

    def test_campaign_quiescence_rejects_holder_and_mount(self):
        target = {
            "device": "/dev/synthetic", "major": 8, "minor": 17,
            "parent_major_minor": "8:16", "partuuid": "deadbeef-01",
            "card_identity_sha256": "a" * 64,
            "size_bytes": 64 << 20,
        }
        card_identity = {
            "sha256": "a" * 64,
            "model": "synthetic-card",
            "transport": "usb",
        }
        cases = (
            (["dm-7"], False, "campaign_holders expected=\\[\\]"),
            ([], True, "campaign_mount expected=absent observed=8:17"),
        )
        for holders, mounted, expected in cases:
            with self.subTest(holders=holders, mounted=mounted), \
                    mock.patch.object(probe, "_verify_target_identity"), \
                    mock.patch.object(
                        probe, "_campaign_card_identity",
                        return_value=card_identity), \
                    mock.patch.object(
                        probe, "_holder_names", return_value=holders), \
                    mock.patch.object(
                        probe, "_mountinfo_has_device",
                        return_value=mounted), \
                    mock.patch.object(
                        probe, "_active_swap_for",
                        side_effect=AssertionError(
                            "holder/mount blocker must stop before swap claim")):
                with self.assertRaisesRegex(probe.ProbeError, expected) as blocked:
                    probe._require_campaign_target_quiescent(target)
                if holders:
                    self.assertIn("observed=holder_count_1", str(blocked.exception))
                    self.assertNotIn(holders[0], str(blocked.exception))

    def test_campaign_exact_partuuid_path_rejects_stale_card_identity(self):
        with self.assertRaisesRegex(
                probe.ProbeError,
                "device_partuuid_path expected='deadbeef-01' "
                "observed='cafebabe-01'"):
            probe.inspect_campaign_target(
                "/dev/disk/by-partuuid/cafebabe-01",
                "/dev/disk/by-partuuid/cafebabe-01",
                "deadbeef-01")

    def campaign_preflight_fixture(self):
        target = {
            "device": "/dev/synthetic", "major": 8, "minor": 17,
            "parent_major_minor": "8:16", "partuuid": "deadbeef-01",
            "parent_model": "synthetic-card",
            "parent_transport": "usb",
            "parent_size_bytes": 128 << 20,
            "card_identity_sha256": "c" * 64,
            "size_bytes": 64 << 20,
        }
        source_sha = "a" * 40
        evidence = {
            "head": source_sha, "source_sha": source_sha,
            "helper_sha256": "d" * 64,
            "artifact_digests": {
                key: str(index) * 64 for index, (key, _, _) in
                enumerate(probe.PHYSICAL_ARTIFACTS, start=1)},
        }
        values = [0] * probe.MIN_BLOCK_STAT_FIELDS
        lower = {
            "available": True, "values": values,
            "device_major_minor": target["parent_major_minor"],
            "sector_bytes": 512,
        }
        inventory = {
            "other_mapper_count": 0,
            "other_mapper_sha256": hashlib.sha256(b"[]").hexdigest(),
        }
        diagnostics = {
            "available": True, "source": "journalctl",
            "time_filter_applied": True, "truncated": False,
            "matching_line_count": 0, "messages": "",
        }
        return target, source_sha, evidence, lower, inventory, diagnostics

    def test_optional_serial_and_wwid_sysfs_absence_is_narrowly_tolerated(self):
        unsupported = (errno.EINVAL, errno.ENXIO, errno.EOPNOTSUPP)
        for name in ("serial", "wwid"):
            for error in unsupported:
                with self.subTest(name=name, errno=error), \
                        mock.patch.object(
                            probe.Path, "read_text",
                            side_effect=OSError(error, "unsupported sysfs id")):
                    self.assertIsNone(probe._optional_card_identity_text(
                        f"/sys/synthetic/device/{name}"))

        with mock.patch.object(
                probe.Path, "read_text",
                side_effect=OSError(errno.EIO, "sysfs read failure")):
            with self.assertRaisesRegex(
                    probe.ProbeError,
                    "card_identity_wwid expected=readable observed=errno_5"):
                probe._optional_card_identity_text(
                    "/sys/synthetic/device/wwid")

        with mock.patch.object(
                probe.Path, "read_text",
                side_effect=OSError(errno.ENXIO, "device unavailable")):
            with self.assertRaisesRegex(
                    probe.ProbeError,
                    "card_identity_model expected=readable observed=errno_6"):
                probe._optional_card_identity_text(
                    "/sys/synthetic/device/model")

    def test_campaign_card_identity_fingerprint_detects_stale_card(self):
        with tempfile.TemporaryDirectory() as directory:
            card = Path(directory) / "mmcblk0"
            (card / "device").mkdir(parents=True)
            (card / "dev").write_text("179:0\n")
            (card / "size").write_text("262144\n")
            (card / "removable").write_text("1\n")
            (card / "device/model").write_text("SD-A\n")
            (card / "device/serial").write_text("serial-a\n")
            (card / "device/wwid").write_text("wwid-a\n")
            original_resolve = probe.Path.resolve

            def resolve(path, *args, **kwargs):
                if str(path) == "/sys/dev/block/179:0":
                    return card
                return original_resolve(path, *args, **kwargs)

            lsblk = subprocess.CompletedProcess(
                [], 0, stdout="mmc\n", stderr="")
            commands = []

            def fake_run(command, **kwargs):
                del kwargs
                commands.append(tuple(command))
                return lsblk

            with mock.patch.object(probe.Path, "resolve", resolve), \
                    mock.patch.object(probe, "_run", side_effect=fake_run):
                first = probe._campaign_card_identity(
                    "/dev/synthetic", "179:0")
                self.assertEqual(first["model"], "SD-A")
                self.assertEqual(first["transport"], "mmc")
                self.assertEqual(first["parent_size_bytes"], 262144 * 512)
                self.assertTrue(first["parent_removable"])
                self.assertTrue(first["serial_present"])
                self.assertTrue(first["wwid_present"])
                (card / "removable").write_text("0\n")
                second = probe._campaign_card_identity(
                    "/dev/synthetic", "179:0")
                (card / "removable").write_text("1\n")
                (card / "device/model").write_text("SD-B\n")
                third = probe._campaign_card_identity(
                    "/dev/synthetic", "179:0")
            self.assertEqual(commands, [
                ("lsblk", "-dnro", "TRAN", "/dev/block/179:0"),
            ] * 3)
            self.assertNotEqual(first["sha256"], second["sha256"])
            self.assertNotEqual(first["sha256"], third["sha256"])

    def test_campaign_card_identity_rejects_unverifiable_removable_state(self):
        with tempfile.TemporaryDirectory() as directory:
            card = Path(directory) / "mmcblk0"
            (card / "device").mkdir(parents=True)
            (card / "dev").write_text("179:0\n")
            (card / "size").write_text("262144\n")
            (card / "removable").write_text("unknown\n")
            original_resolve = probe.Path.resolve

            def resolve(path, *args, **kwargs):
                if str(path) == "/sys/dev/block/179:0":
                    return card
                return original_resolve(path, *args, **kwargs)

            with mock.patch.object(probe.Path, "resolve", resolve):
                with self.assertRaisesRegex(
                        probe.ProbeError,
                        "card_parent_removable expected=0_or_1 "
                        "observed=invalid_format"):
                    probe._campaign_card_identity(
                        "/dev/synthetic", "179:0")

    def test_campaign_changed_removable_parent_blocks_before_quiescence(self):
        target = {
            "device": "/dev/synthetic", "major": 8, "minor": 17,
            "parent_major_minor": "8:16", "partuuid": "deadbeef-01",
            "parent_removable": True,
            "card_identity_sha256": "a" * 64,
            "size_bytes": 64 << 20,
        }
        with mock.patch.object(probe, "_verify_target_identity"), \
                mock.patch.object(
                    probe, "_campaign_card_identity",
                    return_value={
                        "sha256": "b" * 64,
                        "model": "replacement-card",
                        "transport": "usb",
                        "parent_removable": False,
                    }), \
                mock.patch.object(
                    probe, "_holder_names",
                    side_effect=AssertionError(
                        "removable-state change must block before holders")):
            with self.assertRaisesRegex(
                    probe.ProbeError,
                    "campaign_parent_removable expected=True observed=False"):
                probe._require_campaign_target_quiescent(target)

    def test_campaign_stale_card_identity_blocks_before_quiescence_claim(self):
        target = {
            "device": "/dev/synthetic", "major": 8, "minor": 17,
            "parent_major_minor": "8:16", "partuuid": "deadbeef-01",
            "card_identity_sha256": "a" * 64,
            "size_bytes": 64 << 20,
        }
        with mock.patch.object(probe, "_verify_target_identity"), \
                mock.patch.object(
                    probe, "_campaign_card_identity",
                    return_value={
                        "sha256": "b" * 64,
                        "model": "replacement-card",
                        "transport": "usb",
                    }), \
                mock.patch.object(
                    probe, "_holder_names",
                    side_effect=AssertionError(
                        "stale card must block before quiescence claim")):
            with self.assertRaisesRegex(
                    probe.ProbeError,
                    "campaign_card_identity expected='a{64}' "
                    "observed='b{64}'") as blocked:
                probe._require_campaign_target_quiescent(target)
            self.assertNotIn("replacement-card", str(blocked.exception))


    def test_campaign_alias_and_identity_errors_hide_private_paths(self):
        for alias in (
                "/dev/disk/by-partuuid/../by-partuuid/deadbeef-01",
                "/dev/disk/by-partuuid/other/deadbeef-01"):
            with self.subTest(alias=alias), self.assertRaisesRegex(
                    probe.ProbeError,
                    "campaign_device_path expected=exact_by_partuuid_alias "
                    "observed=noncanonical_alias") as blocked:
                probe.inspect_campaign_target(alias, alias, "deadbeef-01")
            self.assertNotIn(alias, str(blocked.exception))

        # Permission errors may include sysfs paths and raw identifier text.
        private = Path("/private/session/serial")
        denied = PermissionError(13, "secret-serial-contents", str(private))
        with mock.patch.object(probe.Path, "read_text", side_effect=denied):
            with self.assertRaisesRegex(
                    probe.ProbeError,
                    "card_identity_serial expected=readable observed=errno_13"
                    ) as blocked:
                probe._optional_card_identity_text(private)
        self.assertNotIn("secret-serial-contents", str(blocked.exception))
        self.assertNotIn(str(private), str(blocked.exception))

    def test_warning_rejection_does_not_echo_private_kernel_line(self):
        trace = {
            "available": True, "time_filter_applied": True,
            "truncated": False,
            "messages": "swapz WARNING: WWID=secret-wwid /private/disk",
        }
        failure = probe._kernel_diagnostics_error(trace)
        self.assertIn(
            "kernel_trace_health expected=no_swapz_failure_or_warning "
            "observed='warning'", failure)
        self.assertNotIn("secret-wwid", failure)
        self.assertNotIn("/private/disk", failure)
        unavailable = {
            "available": False,
            "error": "secret-wwid stored at /private/disk",
        }
        failure = probe._kernel_diagnostics_error(unavailable)
        self.assertEqual(
            failure, "kernel_trace expected=available observed=unavailable")
        self.assertNotIn("secret-wwid", failure)

    def test_campaign_plan_source_trace_and_lower_evidence_fail_closed(self):
        target, source_sha, evidence, lower, inventory, diagnostics = (
            self.campaign_preflight_fixture())
        cases = (
            ("source", {
                "current_source_evidence": {
                    **evidence, "head": "b" * 40},
            }, "campaign_source_sha"),
            ("truncated", {
                "kernel": {**diagnostics, "truncated": True},
            }, "campaign_kernel_diagnostics.*expected=complete"),
            ("missing-lower", {
                "lower": {"available": False, "error": "stat missing"},
            }, "campaign_lower_io_before.*stat missing"),
            ("changed-artifact", {
                "artifact_digests": {
                    **evidence["artifact_digests"],
                    "module_sha256": "f" * 64,
                },
            }, "campaign_artifacts.module_sha256 "
               "expected=qualified_sha256 observed=changed_sha256"),
        )
        for name, changes, expected in cases:
            with self.subTest(name=name):
                source_evidence = changes.get(
                    "current_source_evidence", evidence)
                kernel = changes.get("kernel", diagnostics)
                first_lower = changes.get("lower", lower)
                with mock.patch.object(
                        probe, "inspect_campaign_target",
                        return_value=target), \
                        mock.patch.object(
                            probe, "_block_stat_snapshot",
                            side_effect=[first_lower, lower]), \
                        mock.patch.object(
                            probe, "_module_mapper_preflight",
                            return_value=inventory), \
                        mock.patch.object(
                            probe, "_kernel_swapz_messages",
                            return_value=kernel), \
                        mock.patch.object(
                            probe, "current_source_evidence",
                            return_value=source_evidence), \
                        mock.patch.object(
                            probe, "_artifact_digests",
                            return_value=changes.get(
                                "artifact_digests", evidence["artifact_digests"])), \
                        mock.patch.object(
                            probe, "_require_campaign_target_quiescent"):
                    with self.assertRaisesRegex(probe.ProbeError, expected):
                        probe.campaign_plan(
                            "/dev/disk/by-partuuid/deadbeef-01",
                            "/dev/disk/by-partuuid/deadbeef-01",
                            "deadbeef-01", source_sha)

    def test_campaign_plan_rechecks_source_and_artifacts_before_ready(self):
        target, source_sha, evidence, lower, inventory, diagnostics = (
            self.campaign_preflight_fixture())
        changed_artifacts = {
            **evidence["artifact_digests"],
            "module_sha256": "f" * 64,
        }
        cases = (
            (
                "source",
                [evidence, {**evidence, "head": "b" * 40}],
                [evidence["artifact_digests"], evidence["artifact_digests"]],
                "campaign_source_sha",
            ),
            (
                "artifact",
                [evidence, evidence],
                [evidence["artifact_digests"], changed_artifacts],
                "campaign_artifacts.module_sha256 "
                "expected=qualified_sha256 observed=changed_sha256",
            ),
        )
        for name, source_samples, artifact_samples, expected in cases:
            with self.subTest(name=name), ExitStack() as stack:
                stack.enter_context(mock.patch.object(
                    probe, "inspect_campaign_target", return_value=target))
                stack.enter_context(mock.patch.object(
                    probe, "_block_stat_snapshot",
                    side_effect=[lower, lower]))
                stack.enter_context(mock.patch.object(
                    probe, "_module_mapper_preflight",
                    return_value=inventory))
                stack.enter_context(mock.patch.object(
                    probe, "_kernel_swapz_messages",
                    return_value=diagnostics))
                stack.enter_context(mock.patch.object(
                    probe, "current_source_evidence",
                    side_effect=source_samples))
                stack.enter_context(mock.patch.object(
                    probe, "_artifact_digests",
                    side_effect=artifact_samples))
                stack.enter_context(mock.patch.object(
                    probe, "_require_campaign_target_quiescent"))
                printed = stack.enter_context(mock.patch("builtins.print"))
                with self.assertRaisesRegex(probe.ProbeError, expected):
                    probe.campaign_plan(
                        "/dev/disk/by-partuuid/deadbeef-01",
                        "/dev/disk/by-partuuid/deadbeef-01",
                        "deadbeef-01", source_sha)
                self.assertFalse(any(
                    "CAMPAIGN_PREFLIGHT=READY_READ_ONLY" in str(call.args[0])
                    for call in printed.call_args_list))

    def test_campaign_plan_counter_reset_and_required_work_stay_not_run(self):
        target, source_sha, evidence, lower, inventory, diagnostics = (
            self.campaign_preflight_fixture())
        before = {**lower, "values": list(lower["values"])}
        after = {**lower, "values": list(lower["values"])}
        before["values"][0] = 2
        after["values"][0] = 1
        def campaign_patches():
            return (
                mock.patch.object(probe, "inspect_campaign_target",
                                  return_value=target),
                mock.patch.object(probe, "_module_mapper_preflight",
                                  return_value=inventory),
                mock.patch.object(probe, "_kernel_swapz_messages",
                                  return_value=diagnostics),
                mock.patch.object(probe, "current_source_evidence",
                                  return_value=evidence),
                mock.patch.object(probe, "_artifact_digests",
                                  return_value=evidence["artifact_digests"]),
                mock.patch.object(probe, "_require_campaign_target_quiescent"),
            )
        with ExitStack() as stack:
            for patch in campaign_patches():
                stack.enter_context(patch)
            stack.enter_context(mock.patch.object(
                probe, "_block_stat_snapshot",
                side_effect=[before, after]))
            with self.assertRaisesRegex(
                    probe.ProbeError,
                    "lower_read_requests reset_or_wrap expected>=2 observed=1"):
                probe.campaign_plan(
                    "/dev/disk/by-partuuid/deadbeef-01",
                    "/dev/disk/by-partuuid/deadbeef-01",
                    "deadbeef-01", source_sha)

        with ExitStack() as stack:
            for patch in campaign_patches():
                stack.enter_context(patch)
            stack.enter_context(mock.patch.object(
                probe, "_block_stat_snapshot",
                side_effect=[lower, lower]))
            printed = stack.enter_context(mock.patch("builtins.print"))
            probe.campaign_plan(
                "/dev/disk/by-partuuid/deadbeef-01",
                "/dev/disk/by-partuuid/deadbeef-01",
                "deadbeef-01", source_sha)
        output = "\n".join(
            str(call.args[0]) for call in printed.call_args_list)
        self.assertIn("CAMPAIGN_PREFLIGHT=READY_READ_ONLY", output)
        self.assertNotIn("CAMPAIGN_PREFLIGHT=PASS", output)
        self.assertNotIn("CAMPAIGN_MODULE_MAPPER_GATE=PASS", output)
        self.assertNotIn("CAMPAIGN_KERNEL_DIAGNOSTICS_GATE=PASS", output)
        self.assertNotIn("CAMPAIGN_LOWER_IO_GATE=PASS", output)
        self.assertIn("PAIRED_RAW_VS_SWAPZ=NOT_RUN", output)
        self.assertIn("HIGH_OCCUPANCY_3600S=NOT_RUN", output)
        self.assertIn("ANONYMOUS_LINUX_SWAP=NOT_RUN", output)
        self.assertIn(probe.LOWER_IO_CLAIM_BOUNDARY, output)

    def test_module_mapper_preflight_rejects_missing_module_provenance(self):
        denied = PermissionError(13, "private module inventory", "/sys/module")
        with mock.patch.object(probe.os, "scandir", side_effect=denied), \
                mock.patch.object(
                    probe, "_dm_inventory_snapshot",
                    side_effect=AssertionError(
                        "missing module provenance must stop before DM claim")):
            with self.assertRaisesRegex(
                    probe.ProbeError,
                    "module_provenance expected=readable_module_inventory "
                    "observed=unavailable_errno_13") as blocked:
                probe._module_mapper_preflight()
        self.assertNotIn("private module inventory", str(blocked.exception))
        self.assertNotIn("/sys/module", str(blocked.exception))

    def test_module_mapper_preflight_rejects_swapz_namespaced_inventory(self):
        completed = subprocess.CompletedProcess(
            [], 0,
            stdout="swapz-stale:SWAPZ-FOREIGN-0123456789abcdef\n",
            stderr="")
        with mock.patch.object(
                probe, "_module_loaded_from_sysfs", return_value=False), \
                mock.patch.object(probe, "_run", return_value=completed):
            with self.assertRaisesRegex(
                    probe.ProbeError,
                    "mapper_provenance expected=no_swapz_namespace "
                    "observed=name_namespace_collision") as blocked:
                probe._module_mapper_preflight()
            self.assertNotIn("SWAPZ-FOREIGN", str(blocked.exception))

    def test_module_and_kernel_preflight_block_before_review_or_device_write(self):
        target, evidence = self.physical_preparation_fixture()
        review = {
            "reviewer": probe.VERBAL_REVIEWER,
            "approval_mode": "verbal",
            "run_id": "0123456789abcdef0123456789abcdef",
        }
        lower_values = [0] * probe.MIN_BLOCK_STAT_FIELDS
        lower = {
            "available": True, "values": lower_values,
            "device_major_minor": target["parent_major_minor"],
            "sector_bytes": 512,
        }
        for module_error, kernel, expected in (
                (probe.ProbeError(
                    "module_provenance expected=dm_swapz_absent observed=loaded"),
                 None, "module_provenance"),
                (None, {"available": False, "error": "journal unavailable"},
                 "preflight_kernel_diagnostics.*expected=available"),
        ):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                module = mock.Mock(
                    side_effect=module_error,
                    return_value={
                        "other_mapper_count": 0,
                        "other_mapper_sha256": "a" * 64,
                    })
                kernel_record = kernel or {
                    "available": True, "source": "journalctl",
                    "time_filter_applied": True, "truncated": False,
                    "matching_line_count": 0, "messages": "",
                }
                with mock.patch.object(probe.os, "geteuid", return_value=0), \
                        mock.patch.object(probe, "current_source_evidence",
                                          return_value=evidence), \
                        mock.patch.object(probe, "inspect_target",
                                          return_value=target), \
                        mock.patch.object(probe, "_recovery_base",
                                          return_value=Path(directory)), \
                        mock.patch.object(probe, "_artifact_digests",
                                          return_value=evidence["artifact_digests"]), \
                        mock.patch.object(probe, "validate_review",
                                          return_value=review), \
                        mock.patch.object(probe, "_check_review_unconsumed"), \
                        mock.patch.object(probe.shutil, "which",
                                          return_value="/usr/bin/mock"), \
                        mock.patch.object(probe, "_module_mapper_preflight",
                                          module), \
                        mock.patch.object(probe, "_kernel_swapz_messages",
                                          return_value=kernel_record), \
                        mock.patch.object(probe, "_block_stat_snapshot",
                                          return_value=lower), \
                        mock.patch.object(probe, "_burn_review") as burn, \
                        mock.patch.object(probe, "_write_block0") as write:
                    with self.assertRaisesRegex(probe.ProbeError, expected):
                        probe.run_probe(
                            target["device_arg"], target["device_arg"],
                            directory, "/reviewed/review.json")
                burn.assert_not_called()
                write.assert_not_called()

    def test_source_sha_mismatch_never_grants_review(self):
        target, evidence, review = self.reviewed_device_fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            review["source_sha"] = "f" * 40
            path.write_text(json.dumps(review))
            with self.assertRaisesRegex(
                    probe.ProbeError, "source, helper and device"):
                probe.validate_review(path, evidence, target)


if __name__ == "__main__":
    unittest.main()
