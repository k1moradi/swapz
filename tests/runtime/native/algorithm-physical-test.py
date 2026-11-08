#!/usr/bin/env python3
"""Rootless device-discovery and consent contracts (never writes swap)."""
import importlib.util
import io
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

    def test_shared_disk_with_other_partition_is_refused(self):
        shared = {**self.device, "children": [
            self.device["children"][0],
            {"path": "/dev/sda2", "type": "part", "fstype": "ext4",
             "mountpoints": ["/"]},
        ]}
        self.assertEqual(subject._eligible_partitions(
            {"blockdevices": [shared]}), [])

    def test_noninteractive_gate_skips_device_inspection(self):
        with mock.patch.object(subject.sys.stdin, "isatty", return_value=False), \
             mock.patch.object(subject, "_require_read_only_preflight") as preflight, \
             mock.patch.object(subject.subprocess, "run") as command:
            self.assertEqual(subject.main(), 2)
            preflight.assert_not_called()
            command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
