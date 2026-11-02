#!/usr/bin/env python3
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
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
        target = {"major": 8, "minor": 4}
        review = {
            "approved": True,
            "reviewer": "independent-reviewer",
            "scope": probe.EXPECTED_SCOPE,
            "source_sha": evidence["source_sha"],
            "device_major_minor": "8:4",
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

    def test_review_rejects_the_operator_as_reviewer(self):
        evidence = {"source_sha": "b" * 40}
        target = {"major": 8, "minor": 4}
        review = {
            "approved": True,
            "reviewer": "keivan",
            "scope": probe.EXPECTED_SCOPE,
            "source_sha": evidence["source_sha"],
            "device_major_minor": "8:4",
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

            def write_header(device, header):
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
