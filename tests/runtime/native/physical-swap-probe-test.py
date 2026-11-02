#!/usr/bin/env python3
import hashlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
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

                # No-follow source validation also excludes symlink substitution.
                sources["module_sha256"].unlink()
                sources["module_sha256"].symlink_to(sources["formatter_sha256"])
                with self.assertRaisesRegex(probe.ProbeError, "cannot verify"):
                    probe._artifact_digests()

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
            with self.assertRaisesRegex(probe.ProbeError, "PARTUUID"):
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
                            "approval_mode", "helper_git_sha"):
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
                              oracle_failure_at=None):
        """Use actual helper checks with only device/command interfaces mocked."""
        target, evidence = self.physical_preparation_fixture()
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
        })
        formatted = bytearray(probe.PAGE_BYTES)
        formatted[:8] = probe.SWAPZ_HEADER_MAGIC
        struct.pack_into("<IIQ", formatted, 8,
                         probe.SWAPZ_HEADER_VERSION, probe.PAGE_BYTES,
                         target["size_bytes"])
        formatted[24:40] = bytes(range(1, 17))
        mapper = f"/dev/mapper/{state['dm_name']}"
        events = []
        identity_verifications = 0
        oracle_invocations = 0

        def verify_target(_target):
            nonlocal identity_verifications
            identity_verifications += 1
            events.append(("verify", identity_verifications))
            if identity_failure_at == identity_verifications:
                raise probe.ProbeError(
                    f"injected identity change at boundary {identity_verifications}")

        def run(command, **kwargs):
            nonlocal oracle_invocations
            del kwargs
            arguments = tuple(str(value) for value in command)
            events.append(("command", arguments))
            if command[0] == "/reviewed/device-roundtrip":
                oracle_invocations += 1
                if oracle_invocations == oracle_failure_at:
                    return subprocess.CompletedProcess(
                        command, 1, stdout="FAIL injected physical phase\n",
                        stderr="injected phase failure\n")
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
            else:
                output = ""
            return subprocess.CompletedProcess(command, 0,
                                               stdout=output, stderr="")

        def read_text(path, *args, **kwargs):
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
                return "0 0 0 0 0 0 0 0 0 0 0\n"
            return REAL_PATH_READ_TEXT(path, *args, **kwargs)

        def is_file(path):
            return str(path).endswith("/parameters/allow_physical_backing")

        def iter_directory(path):
            if str(path) == "/sys/dev/block/253:0/slaves":
                return iter([Path("/sys/dev/block/253:0/slaves/synthetic")])
            raise AssertionError(f"unexpected sysfs listing: {path}")

        def remove_test_objects(saved_state, saved_state_dir):
            saved_state["stage"] = "COMPLETE"
            probe._release_partition_ownership(saved_state)
            result_path = Path(saved_state_dir) / probe.RESULTS_NAME
            saved_results = json.loads(result_path.read_text())
            inventory_after = probe._dm_inventory_snapshot(
                saved_state["dm_name"], saved_state["dm_uuid"])
            inventory_before = saved_results["dm_inventory_before"]
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
                "final_recovery_state": "COMPLETE",
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
                mock.patch.object(probe, "_git", side_effect=lambda *args:
                                  (evidence["head"] if args[0] == "rev-parse"
                                   else "")),
                mock.patch.object(probe, "_remote_main_sha",
                                  return_value=evidence["head"]),
                mock.patch.object(probe, "inspect_target", return_value=target),
                mock.patch.object(probe, "_artifact_digests",
                                  return_value=evidence["artifact_digests"]),
                mock.patch.object(probe, "validate_review", return_value=review),
                mock.patch.object(probe.shutil, "which", return_value="/usr/bin/mock"),
                mock.patch.object(probe.Path, "exists", return_value=False),
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
                mock.patch.object(probe, "_active_swap_for",
                                  side_effect=[{
                                      "used_kib": 0,
                                      "size_kib": target["swap_size_kib"],
                                      "priority": target["swap_priority"],
                                  }, None]),
                mock.patch.object(probe, "_write_block0",
                                  side_effect=lambda *_, **__:
                                  events.append(("write0",))),
                mock.patch.object(probe, "_read_block0",
                                  side_effect=[target["header"],
                                               bytes(probe.PAGE_BYTES),
                                               bytes(formatted)]),
                mock.patch.object(probe, "_save_state",
                                  side_effect=lambda *_:
                                  events.append(("save", state["stage"]))),
                mock.patch.object(probe, "_remove_test_objects",
                                  side_effect=lambda saved_state, saved_dir: (
                                      events.append(("recover",)) or
                                      remove_test_objects(saved_state, saved_dir))),
                mock.patch.object(probe, "_run", side_effect=run),
            )
            with ExitStack() as active_patches:
                for patch in patches:
                    active_patches.enter_context(patch)
                if fault or identity_failure_at is not None or \
                        oracle_failure_at is not None:
                    with self.assertRaisesRegex(
                            probe.ProbeError,
                            "mapper|UUID|identity|table|backing|injected|phase failed|oracle phase .* failed"):
                        probe.run_probe(target["device_arg"], target["device_arg"],
                                        directory, "/reviewed/review.json")
                else:
                    probe.run_probe(target["device_arg"], target["device_arg"],
                                    directory, "/reviewed/review.json")
        return events, state, target

    def test_formatter_and_oracle_use_exact_reviewed_identity_arguments(self):
        events, state, target = self.simulate_physical_run()
        commands = [event[1] for event in events if event[0] == "command"]
        self.assertIn(("/reviewed/swapzctl", "format", target["device"],
                       "--expect-major-minor", "8:4", "--expect-bytes",
                       str(target["size_bytes"])), commands)
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
                                              "available": False,
                                              "error": "mocked unavailable"}),
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


if __name__ == "__main__":
    unittest.main()
