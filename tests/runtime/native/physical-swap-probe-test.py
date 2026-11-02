#!/usr/bin/env python3
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import struct
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/physical-swap-probe.py"
SPEC = importlib.util.spec_from_file_location("physical_swap_probe", SCRIPT)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class PhysicalSwapProbeTests(unittest.TestCase):
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
            "module_loaded_by_us": False,
            "dm_name": f"swapz-demo-physical-{token}",
            "dm_uuid": f"SWAPZ-TEST-PHYSICAL-{token}",
        }
        (state_dir / probe.STATE_NAME).write_text(json.dumps(state))
        (state_dir / probe.BACKUP_NAME).write_bytes(header)
        return state, header

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
        evidence = {"source_sha": "a" * 40}
        target = {"major": 8, "minor": 4, "partuuid": "deadbeef-04"}
        review = {
            "approved": True,
            "reviewer": "independent-reviewer",
            "scope": probe.EXPECTED_SCOPE,
            "source_sha": evidence["source_sha"],
            "device_major_minor": "8:4",
            "device_partuuid": "deadbeef-04",
            "helper_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "review.json"
            path.write_text(json.dumps(review))
            with mock.patch.dict(os.environ, {"SUDO_USER": "keivan", "USER": "root"}):
                self.assertEqual(
                    probe.validate_review(path, evidence, target),
                    "independent-reviewer")
                review["device_major_minor"] = "8:3"
                path.write_text(json.dumps(review))
                with self.assertRaisesRegex(probe.ProbeError, "does not match"):
                    probe.validate_review(path, evidence, target)
                review["device_major_minor"] = "8:4"
                review["device_partuuid"] = "cafebabe-04"
                path.write_text(json.dumps(review))
                with self.assertRaisesRegex(probe.ProbeError, "does not match"):
                    probe.validate_review(path, evidence, target)

    def test_review_rejects_the_operator_as_reviewer(self):
        evidence = {"source_sha": "b" * 40}
        target = {"major": 8, "minor": 4, "partuuid": "deadbeef-04"}
        review = {
            "approved": True,
            "reviewer": "keivan",
            "scope": probe.EXPECTED_SCOPE,
            "source_sha": evidence["source_sha"],
            "device_major_minor": "8:4",
            "device_partuuid": "deadbeef-04",
            "helper_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
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
            active = {"path": state["device"], "priority": -1}

            def run(args, **kwargs):
                del kwargs
                events.append(("run", tuple(args)))
                if args[:2] == ["dmsetup", "info"]:
                    return subprocess.CompletedProcess(
                        args, 0, stdout=state["dm_uuid"] + "\n", stderr="")
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

            def write_header(device, header, target):
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
                    mock.patch.object(probe, "_read_block0", return_value=bytes(probe.PAGE_BYTES)), \
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
                with self.assertRaisesRegex(probe.ProbeError, "while swap is active"):
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
                with self.assertRaisesRegex(probe.ProbeError, "does not match its digest"):
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
                return subprocess.CompletedProcess(
                    args, 0, stdout="SWAPZ-TEST-PHYSICAL-ffffffffffffffff\n",
                    stderr="")

            with mock.patch.object(probe, "_validate_state_dir"), \
                    mock.patch.object(
                        probe, "inspect_target_identity_for_recovery",
                        return_value={"device": state["device"], "major": 8,
                                      "minor": 4, "size_bytes": state["size_bytes"]}), \
                    mock.patch.object(probe, "_run", side_effect=run), \
                    mock.patch.object(probe, "_write_block0") as write_header:
                with self.assertRaisesRegex(probe.ProbeError, "different UUID"):
                    probe.recover(
                        state_dir, state["device_arg"], state["device_arg"])

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:2], ("dmsetup", "info"))
        write_header.assert_not_called()

    def test_remote_branch_check_uses_sudo_invoking_users_ssh_identity(self):
        sha = "c" * 40
        result = subprocess.CompletedProcess(
            [], 0, stdout=f"{sha}\trefs/heads/main\n", stderr="")
        with mock.patch.dict(os.environ, {"SUDO_USER": "keivan"}), \
                mock.patch.object(probe.os, "geteuid", return_value=0), \
                mock.patch.object(probe.shutil, "which",
                                   return_value="/usr/sbin/runuser"), \
                mock.patch.object(probe, "_run", return_value=result) as run:
            self.assertEqual(probe._remote_main_sha(), sha)
        args = run.call_args.args[0]
        self.assertEqual(args[:4], [
            "/usr/sbin/runuser", "--user", "keivan", "--"])
        self.assertIn("ls-remote", args)

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

    def test_live_host_gate_and_distinct_reports(self):
        source = "a" * 40
        head = "b" * 40
        local_host = {
            "schema": "swapz-host-v1",
            "architecture": "x86_64",
            "id_sha256": "1" * 64,
        }
        current = {
            "overall": "PASS", "tested_commit_sha": source,
            "source_sha": source, "host_identity": dict(local_host),
        }
        history = {
            "first": dict(current, duration=1),
            "second": dict(current, duration=1),
        }

        def git(*args, **kwargs):
            del kwargs
            operation = args[0]
            if operation == "symbolic-ref":
                return "main"
            if operation == "status":
                return ""
            if operation == "rev-parse":
                return head
            if operation == "rev-list":
                return "first\nsecond"
            if operation == "diff-tree":
                return "test_results.json"
            if operation == "log":
                return "first\nsecond"
            raise AssertionError(args)

        def run(args, **kwargs):
            del kwargs
            if args[:2] == ["git", "merge-base"]:
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            if args[:2] == ["git", "show"]:
                return subprocess.CompletedProcess(
                    args, 0, stdout=json.dumps(
                        history[args[2].split(":")[0]]), stderr="")
            raise AssertionError(args)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "test_results.json").write_text(json.dumps(current))
            with mock.patch.object(probe, "ROOT", root), \
                    mock.patch.object(probe, "_git", side_effect=git), \
                    mock.patch.object(probe, "_run", side_effect=run), \
                    mock.patch.object(probe, "_remote_main_sha", return_value=head), \
                    mock.patch.object(probe, "live_host_identity",
                                      return_value=local_host):
                self.assertEqual(probe.current_source_evidence()["pass_reports"], 1)
                history["second"] = dict(current, duration=2)
                self.assertEqual(probe.current_source_evidence()["pass_reports"], 2)
                current["host_identity"] = dict(local_host, id_sha256="2" * 64)
                (root / "test_results.json").write_text(json.dumps(current))
                with self.assertRaisesRegex(probe.ProbeError, "not produced on this host"):
                    probe.current_source_evidence()

    def test_probe_is_not_wired_into_make_test_and_never_swapons_mapper(self):
        runner = (ROOT / "tools/run-tests.py").read_text()
        makefile = (ROOT.parent / "Makefile").read_text()
        script = SCRIPT.read_text()
        self.assertNotIn("physical-swap-probe.py", runner)
        self.assertNotIn("physical-swap-probe.py", makefile)
        self.assertIn('["swapon", state["device"]]', script)
        self.assertNotIn('["swapon", mapper]', script)
        self.assertNotIn('"--force"', script)


if __name__ == "__main__":
    unittest.main()
