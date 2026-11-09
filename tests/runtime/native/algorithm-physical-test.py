#!/usr/bin/env python3
"""Rootless device-discovery and consent contracts (never writes swap)."""
import importlib.util
import io
import stat
from types import SimpleNamespace
from pathlib import Path
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[2] / "tools/algorithm-physical.py"
spec = importlib.util.spec_from_file_location("algorithm_physical", SCRIPT)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


class AlgorithmPhysicalTest(unittest.TestCase):
    def setUp(self):
        self.device = {"path":"/dev/sda", "type":"disk", "tran":"usb", "children": [
            {"path":"/dev/sda1", "type":"part", "fstype":"swap",
             "uuid":"00112233-4455-6677-8899-aabbccddeeff",
             "partuuid":"example-01", "size": 128 * 1024 * 1024,
             "mountpoints": [None]}
        ]}

    def test_requires_exactly_one_swap_partition(self):
        self.assertEqual(len(subject._eligible_partitions(
            {"blockdevices":[self.device]})), 1)
        for mutation in ({"fstype":"ext4"}, {"size":16},
                         {"mountpoints":["/"]}, {"partuuid":None}):
            with self.subTest(mutation=mutation):
                changed = {**self.device, "children":[
                    {**self.device["children"][0], **mutation}]}
                self.assertEqual(subject._eligible_partitions(
                    {"blockdevices":[changed]}), [])
        self.assertEqual(subject._eligible_partitions(
            {"blockdevices":[{**self.device,"tran":"nvme"}]}), [])

    def test_declining_confirmation_never_invokes_privilege(self):
        candidate = {"path":"/dev/sda1", "parent":"/dev/sda",
                     "partuuid":"example-01", "size_bytes":128 * 1024 * 1024,
                     "selector":"/dev/disk/by-uuid/example"}
        output = io.StringIO()
        with mock.patch.object(subject.sys.stdin, "isatty", return_value=True), \
             mock.patch.object(subject.sys.stdout, "isatty", return_value=True), \
             mock.patch.object(subject, "_require_read_only_preflight", return_value=candidate), \
             mock.patch("builtins.input", return_value="n"), \
             mock.patch.object(subject.subprocess, "run") as command, \
             mock.patch("builtins.print") as printer:
            self.assertEqual(subject.main(), 2)
            command.assert_not_called()
            self.assertTrue(any("declined" in str(args) for args in printer.call_args_list))

    def test_approved_trial_invokes_one_fixed_privileged_command(self):
        candidate = {
            "path": "/dev/sda1", "parent": "/dev/sda",
            "partuuid": "example-01", "size_bytes": 128 * 1024 * 1024,
            "selector": "/dev/disk/by-uuid/example",
        }
        with mock.patch.object(subject.sys.stdin, "isatty", return_value=True), \
             mock.patch.object(subject.sys.stdout, "isatty", return_value=True), \
             mock.patch.object(subject, "_require_read_only_preflight",
                               return_value=candidate), \
             mock.patch("builtins.input", return_value="yes") as approval, \
             mock.patch.object(subject.shutil, "which",
                               return_value="/usr/bin/sudo"), \
             mock.patch.object(subject.subprocess, "run",
                               return_value=mock.Mock(returncode=0)) as command:
            self.assertEqual(subject.main(), 0)
        approval.assert_called_once()
        self.assertEqual(command.call_count, 1)
        self.assertEqual(command.call_args.args[0], [
            "/usr/bin/sudo", "-n", "--", subject.sys.executable, "-I", "-B",
            str(subject.ROOT / "tests/tools/physical-swap-probe.py"),
            "run", "--device", candidate["selector"],
            "--confirm-device", candidate["selector"],
            "--development-only", "--algorithm-real-swap",
        ])

    def test_shared_disk_is_discoverable_but_not_authorized(self):
        shared = {**self.device, "children": [
            self.device["children"][0],
            {"path": "/dev/sda2", "type": "part", "fstype": "ext4",
             "mountpoints": ["/"]},
        ]}
        candidates = subject._eligible_partitions({"blockdevices": [shared]})
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["path"], "/dev/sda1")
        self.assertTrue(candidates[0]["parent_has_other_partitions"])

    def test_shared_root_disk_discovers_only_swap_partition(self):
        disk = {"path": "/dev/sda", "type": "disk", "tran": "usb",
                "children": [
                    {"path": "/dev/sda1", "type": "part", "fstype": "vfat",
                     "mountpoints": ["/boot/efi"]},
                    {"path": "/dev/sda2", "type": "part", "fstype": "ext4",
                     "mountpoints": ["/boot"]},
                    {"path": "/dev/sda3", "type": "part", "fstype": "f2fs",
                     "mountpoints": ["/"]},
                    {**self.device["children"][0],
                     "path": "/dev/sda4", "partuuid": "7fb9401d-04",
                     "mountpoints": ["[SWAP]"]}]}
        candidates = subject._eligible_partitions({"blockdevices": [disk]})
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["path"], "/dev/sda4")
        self.assertEqual(candidates[0]["parent"], "/dev/sda")
        self.assertTrue(candidates[0]["parent_has_other_partitions"])
        self.assertTrue(candidates[0]["lsblk_active_swap"])

    def test_live_inventory_requests_lsblk_hierarchy_for_shared_root_swap(self):
        # A flat lsblk JSON result omits children[] and hides /dev/sda4.
        # Assert the actual command requests --tree, not just that synthetic
        # hierarchy fixtures happen to contain the correct partition.
        import json

        swap_uuid = "00112233-4455-6677-8899-aabbccddeeff"
        disk = {"path": "/dev/sda", "type": "disk", "tran": "usb",
                "children": [
                    {"path": "/dev/sda1", "type": "part", "fstype": "vfat",
                     "mountpoints": ["/boot/efi"]},
                    {"path": "/dev/sda2", "type": "part", "fstype": "ext4",
                     "mountpoints": ["/boot"]},
                    {"path": "/dev/sda3", "type": "part", "fstype": "f2fs",
                     "mountpoints": ["/"]},
                    {**self.device["children"][0],
                     "path": "/dev/sda4", "partuuid": "7fb9401d-04",
                     "mountpoints": ["[SWAP]"]}]}
        commands = []

        def run(command, **_kwargs):
            commands.append(command)
            if command == ["systemd-detect-virt", "--quiet"]:
                return SimpleNamespace(returncode=1)
            if command[0] == "lsblk":
                self.assertEqual(command[:4], [
                    "lsblk", "--json", "--tree", "--bytes"])
                self.assertEqual(command[-1],
                                 "PATH,TYPE,FSTYPE,UUID,PARTUUID,SIZE,TRAN,MOUNTPOINTS")
                return SimpleNamespace(returncode=0,
                                       stdout=json.dumps({"blockdevices": [disk]}))
            self.fail("unexpected subprocess invocation")

        def resolve(path):
            if str(path) == "/dev/disk/by-uuid/" + swap_uuid:
                return "/dev/sda4"
            return str(path)

        with mock.patch.object(subject.os, "geteuid", return_value=1000), \
             mock.patch.object(subject.platform, "machine",
                               return_value="x86_64"), \
             mock.patch.object(subject.subprocess, "run", side_effect=run), \
             mock.patch.object(subject.Path, "exists", return_value=False), \
             mock.patch.object(subject.Path, "read_text", return_value=(
                 "Filename Type Size Used Priority\n"
                 "/dev/sda4 partition 16777212 0 -1\n")), \
             mock.patch.object(subject.os, "stat", return_value=SimpleNamespace(
                 st_mode=stat.S_IFBLK, st_rdev=42)), \
             mock.patch.object(subject.Path, "is_symlink", return_value=True), \
             mock.patch.object(subject.os.path, "realpath", side_effect=resolve):
            selected = subject._require_read_only_preflight()

        self.assertEqual(len(commands), 2)
        self.assertEqual(selected["path"], "/dev/sda4")
        self.assertEqual(selected["partuuid"], "7fb9401d-04")
        self.assertTrue(selected["parent_has_other_partitions"])
        self.assertEqual(selected["active_swap"]["used_kib"], 0)

    def test_active_swap_usage_is_observed_not_treated_as_swapoff_proof(self):
        candidate = {"path": "/dev/sda4", "lsblk_active_swap": True}
        rows = [
            "Filename Type Size Used Priority",
            "/dev/disk/by-partuuid/7fb9401d-04 partition 16777212 329984 -1",
            "/swapfile file 524284 329984 -1",
        ]
        def block_stat(path):
            if path not in {"/dev/sda4",
                            "/dev/disk/by-partuuid/7fb9401d-04"}:
                raise AssertionError("unexpected block identity lookup")
            return SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=42)
        with mock.patch.object(subject.os, "stat", side_effect=block_stat):
            state = subject._selected_swap_inventory(candidate, rows)
        self.assertEqual(state["active_swap"]["used_kib"], 329984)
        self.assertEqual(state["active_swap"]["priority"], -1)
        self.assertEqual(state["other_active_swap_count"], 1)
        self.assertEqual(state["other_active_swapfile_count"], 1)
        self.assertEqual(state["other_active_partition_count"], 0)

    def test_shared_parent_never_reaches_consent_or_swapoff(self):
        candidate = {
            "path": "/dev/sda4", "parent": "/dev/sda",
            "partuuid": "7fb9401d-04", "size_bytes": 16 * 1024 ** 3,
            "parent_has_other_partitions": True,
            "active_swap": {"used_kib": 0, "priority": -1,
                            "capacity_kib": 16777212},
            "other_active_partition_count": 0,
        }
        with mock.patch.object(subject.sys.stdin, "isatty",
                               return_value=True), \
             mock.patch.object(subject.sys.stdout, "isatty",
                               return_value=True), \
             mock.patch.object(subject, "_require_read_only_preflight",
                               return_value=candidate), \
             mock.patch("builtins.input") as answer, \
             mock.patch.object(subject.subprocess, "run") as command, \
             mock.patch("builtins.print") as output:
            self.assertEqual(subject.main(), 2)
        answer.assert_not_called()
        command.assert_not_called()
        messages = "\n".join(str(call) for call in output.call_args_list)
        self.assertIn("/dev/sda4", messages)
        self.assertIn("shared_root_scope_and_independent_recovery_required",
                      messages)
        self.assertNotIn("active_target_swapoff_not_implemented", messages)

    def test_active_target_and_unrelated_swapfile_reach_single_consent(self):
        candidate = {
            "path": "/dev/sdb1", "parent": "/dev/sdb",
            "partuuid": "f13428f6-01", "size_bytes": 116 * 1024 ** 3,
            "selector": "/dev/disk/by-uuid/example",
            "parent_has_other_partitions": False,
            "active_swap": {"used_kib": 4, "priority": -1,
                            "capacity_kib": 121863164},
            "other_active_swap_count": 1,
            "other_active_swapfile_count": 1,
            "other_active_partition_count": 0,
        }
        with mock.patch.object(subject.sys.stdin, "isatty", return_value=True), \
             mock.patch.object(subject.sys.stdout, "isatty", return_value=True), \
             mock.patch.object(subject, "_require_read_only_preflight",
                               return_value=candidate), \
             mock.patch("builtins.input", return_value="yes") as approval, \
             mock.patch.object(subject.shutil, "which",
                               return_value="/usr/bin/sudo"), \
             mock.patch.object(subject.subprocess, "run",
                               return_value=mock.Mock(returncode=0)) as command:
            self.assertEqual(subject.main(), 0)
        approval.assert_called_once()
        self.assertEqual(command.call_count, 1)
        self.assertEqual(command.call_args.args[0][-2:],
                         ["--development-only", "--algorithm-real-swap"])

    def test_unrelated_active_partition_blocks_before_consent(self):
        candidate = {
            "path": "/dev/sdb1", "parent": "/dev/sdb",
            "partuuid": "f13428f6-01", "size_bytes": 116 * 1024 ** 3,
            "parent_has_other_partitions": False,
            "active_swap": {"used_kib": 4, "priority": -1,
                            "capacity_kib": 121863164},
            "other_active_partition_count": 1,
        }
        with mock.patch.object(subject.sys.stdin, "isatty", return_value=True), \
             mock.patch.object(subject.sys.stdout, "isatty", return_value=True), \
             mock.patch.object(subject, "_require_read_only_preflight",
                               return_value=candidate), \
             mock.patch("builtins.input") as answer, \
             mock.patch.object(subject.subprocess, "run") as command, \
             mock.patch("builtins.print") as output:
            self.assertEqual(subject.main(), 2)
        answer.assert_not_called()
        command.assert_not_called()
        self.assertTrue(any(
            "unrelated_active_partition_not_supported" in str(call)
            for call in output.call_args_list))

    def test_inconsistent_swap_identity_and_duplicate_rows_fail_closed(self):
        candidate = {"path": "/dev/sda4", "lsblk_active_swap": True}
        with mock.patch.object(subject.os, "stat", return_value=SimpleNamespace(
                st_mode=stat.S_IFBLK, st_rdev=42)):
            with self.assertRaisesRegex(ValueError, "disagrees"):
                subject._selected_swap_inventory(
                    candidate, ["Filename Type Size Used Priority"])
            with self.assertRaisesRegex(ValueError, "duplicate"):
                subject._selected_swap_inventory(candidate, [
                    "Filename Type Size Used Priority",
                    "/dev/sda4 partition 16777212 0 -1",
                    "/dev/sda4 partition 16777212 0 -1",
                ])

    def test_noninteractive_gate_skips_device_inspection(self):
        with mock.patch.object(subject.sys.stdin, "isatty", return_value=False), \
             mock.patch.object(subject, "_require_read_only_preflight") as preflight, \
             mock.patch.object(subject.subprocess, "run") as command:
            self.assertEqual(subject.main(), 2)
            preflight.assert_not_called()
            command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
