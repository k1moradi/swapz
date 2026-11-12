#!/usr/bin/env python3
"""Rootless device-discovery and consent contracts (never writes swap)."""
import contextlib
import importlib.util
import io
import json
import stat
import tempfile
import subprocess
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

    def test_physical_development_linux_abi_rejects_unsupported_geometry(self):
        # Architecture is not host authorization: the privileged probe still
        # verifies bare metal, source, device topology, and durable recovery.
        for machine in ("x86_64", "aarch64"):
            with self.subTest(machine=machine), \
                 mock.patch.object(subject.platform, "system",
                                   return_value="Linux"), \
                 mock.patch.object(subject.platform, "machine",
                                   return_value=machine), \
                 mock.patch.object(subject.struct, "calcsize", return_value=8), \
                 mock.patch.object(subject.os, "sysconf", return_value=4096):
                subject._require_development_linux_abi()
        for system, machine, pointer_bytes, page_bytes in (
                ("Darwin", "aarch64", 8, 4096),
                ("Linux", "armv7l", 4, 4096),
                ("Linux", "aarch64", 8, 16384),
                ("Linux", "aarch64", 4, 4096)):
            with self.subTest(system=system, machine=machine,
                              pointer_bytes=pointer_bytes, page_bytes=page_bytes), \
                 mock.patch.object(subject.platform, "system",
                                   return_value=system), \
                 mock.patch.object(subject.platform, "machine",
                                   return_value=machine), \
                 mock.patch.object(subject.struct, "calcsize",
                                   return_value=pointer_bytes), \
                 mock.patch.object(subject.os, "sysconf",
                                   return_value=page_bytes):
                with self.assertRaisesRegex(ValueError, "physical trial requires"):
                    subject._require_development_linux_abi()

    def test_big_endian_partition_trial_is_rejected(self):
        with mock.patch.object(subject.platform, "system", return_value="Linux"), \
             mock.patch.object(subject.platform, "machine", return_value="aarch64"), \
             mock.patch.object(subject.struct, "calcsize", return_value=8), \
             mock.patch.object(subject.os, "sysconf", return_value=4096), \
             mock.patch.object(subject.sys, "byteorder", "big"):
            with self.assertRaisesRegex(ValueError, "little-endian"):
                subject._require_development_linux_abi()

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
        for transport, disk_path in (
                ("sata", "/dev/sda"), ("nvme", "/dev/nvme0n1"),
                (None, "/dev/sdb")):
            with self.subTest(transport=transport):
                fixed_disk = {**self.device, "path": disk_path,
                              "tran": transport}
                matched = subject._eligible_partitions(
                    {"blockdevices": [fixed_disk]})
                self.assertEqual(len(matched), 1)
                self.assertEqual(matched[0]["parent_transport"], transport)
        nvme = {**self.device, "path": "/dev/nvme0n1", "tran": "nvme"}
        cleared_uuid = {**self.device, "children": [
            {**self.device["children"][0], "uuid": None}]}
        self.assertEqual(len(subject._eligible_partitions(
            {"blockdevices": [cleared_uuid]})), 1)
        virtual = subject._eligible_partitions(
            {"blockdevices": [nvme]}, virtual_device_only=True)
        self.assertEqual(len(virtual), 1)
        self.assertTrue(virtual[0]["virtual_device_only"])
        self.assertEqual(virtual[0]["parent_transport"], "nvme")

    def test_multiple_candidates_require_explicit_selection_before_confirmation(self):
        first = {
            "path": "/dev/sdb1", "parent": "/dev/sdb",
            "partuuid": "deadbeef-01", "uuid": "aaaaaaaa-0000",
            "size_bytes": 128 * 1024 * 1024,
        }
        second = {
            "path": "/dev/sdc1", "parent": "/dev/sdc",
            "partuuid": "cafebabe-01", "uuid": "bbbbbbbb-0000",
            "size_bytes": 256 * 1024 * 1024,
        }
        with mock.patch("builtins.input", return_value="2") as response, \
             mock.patch("builtins.print") as output:
            self.assertIs(subject._select_swap_partition([first, second]),
                          second)
        response.assert_called_once()
        self.assertTrue(any("Identifiable Swap partitions" in str(call)
                            for call in output.call_args_list))
        for answer in ("", "0", "3", "yes", "-1", " 2", "２"):
            with self.subTest(answer=answer), \
                 mock.patch("builtins.input", return_value=answer), \
                 mock.patch("builtins.print"):
                if answer == "":
                    self.assertIsNone(
                        subject._select_swap_partition([first, second]))
                else:
                    with self.assertRaisesRegex(ValueError, "selection is invalid"):
                        subject._select_swap_partition([first, second])
        with mock.patch("builtins.input", side_effect=EOFError), \
             mock.patch("builtins.print"):
            self.assertIsNone(subject._select_swap_partition([first, second]))
        with mock.patch("builtins.input") as response:
            self.assertIs(subject._select_swap_partition([first]), first)
            response.assert_not_called()
        for field in ("path", "partuuid"):
            with self.subTest(field=field):
                duplicated = {**second, field: first[field]}
                with self.assertRaisesRegex(ValueError, "duplicate.*identity"):
                    subject._select_swap_partition([first, duplicated])

    def test_cancelled_partition_selection_never_prompts_or_calls_sudo(self):
        with mock.patch.object(subject.sys.stdin, "isatty",
                               return_value=True), \
             mock.patch.object(subject.sys.stdout, "isatty",
                               return_value=True), \
             mock.patch.object(subject, "_require_read_only_preflight",
                               return_value=None), \
             mock.patch("builtins.input") as confirmation, \
             mock.patch.object(subject.subprocess, "run") as command, \
             mock.patch("builtins.print") as output:
            self.assertEqual(subject.main(), 2)
        confirmation.assert_not_called()
        command.assert_not_called()
        self.assertTrue(any("selection_declined" in str(call)
                            for call in output.call_args_list))

    def test_loaded_preflight_recognizes_physical_shape_without_cleanup(self):
        # Execute the exact bash admission fragment with fake dmsetup output.
        # No host devices, module commands or privileged cleanup are executed.
        preflight = (SCRIPT.parent / "loaded-preflight.sh").read_text(
            encoding="utf-8")
        separator = "\n"
        self.assertEqual(preflight.count('case "$owned_map" in' + separator), 1)
        token_function = ("is_hex16() {" + separator +
                          preflight.split("is_hex16() {" + separator, 1)[1].split(
                              "is_kernel_release() {", 1)[0])
        mapper_admission = ('case "$owned_map" in' + separator +
                            preflight.split('case "$owned_map" in' + separator, 1)[1].split(
                                "assert_not_mounted() {", 1)[0])
        mocked_shell = (
            token_function + separator +
            'refuse() { printf "BLOCKED_CHECK=%s\\n" "$2"; exit 1; }' + separator +
            'dmsetup() { printf "%s\\n" "$mock_uuid"; }' + separator +
            'owned_map="$1"; mock_uuid="$2"' + separator +
            mapper_admission + separator + 'printf "RAM_MAPPER_ADMITTED\\n"' + separator)
        run_token = "a" * 16
        cases = (
            (f"swapz-demo-physical-{run_token}",
             f"SWAPZ-TEST-PHYSICAL-{run_token}",
             1, "BLOCKED_CHECK=physical_trial_mapper_present"),
            (f"swapz-demo-physical-{run_token}",
             "SWAPZ-TEST-PHYSICAL-" + "b" * 16,
             1, "BLOCKED_CHECK=stale_run_token"),
            ("swapz-demo-physical-malformed",
             f"SWAPZ-TEST-PHYSICAL-{run_token}",
             1, "BLOCKED_CHECK=stale_run_token"),
            (f"swapz-demo-{run_token}",
             f"SWAPZ-TEST-{run_token}",
             0, "RAM_MAPPER_ADMITTED"),
        )
        for name, uuid, expected_exit, expected_message in cases:
            with self.subTest(expected_message=expected_message):
                completed = subprocess.run(
                    ["bash", "--noprofile", "--norc", "-c", mocked_shell,
                     "fixture", name, uuid],
                    text=True, capture_output=True, check=False, timeout=10)
                self.assertEqual(completed.returncode, expected_exit,
                                 completed.stderr)
                self.assertIn(expected_message, completed.stdout)
                self.assertNotIn(run_token, completed.stdout)
                self.assertNotIn("/dev/", completed.stdout)

    def test_make_test_evidence_is_forwarded_only_as_exact_private_pair(self):
        expected = str(subject.ROOT / "build/tests/algorithm-ram-evidence.json")
        with mock.patch.dict(subject.os.environ, {
                "SWAPZ_ALGORITHM_RAM_EVIDENCE": expected,
                "SWAPZ_ALGORITHM_RAM_NONCE": "a" * 32}, clear=False):
            self.assertEqual(subject._algorithm_ram_evidence_arguments(), [
                "--algorithm-ram-evidence", expected,
                "--algorithm-ram-nonce", "a" * 32])
        with mock.patch.dict(subject.os.environ, {
                "SWAPZ_ALGORITHM_RAM_EVIDENCE": "/tmp/other",
                "SWAPZ_ALGORITHM_RAM_NONCE": "a" * 32}, clear=False):
            with self.assertRaisesRegex(ValueError, "malformed"):
                subject._algorithm_ram_evidence_arguments()

    def test_untracked_inventory_is_owner_only_and_never_changes_admission(self):
        # Exact paths are retained locally, not printed or sent to GitHub.
        with tempfile.TemporaryDirectory() as directory:
            temporary_root = Path(directory)
            private_directory = temporary_root / "build/tests"
            private_directory.mkdir(parents=True)
            private_name = "private/owner file\nwith newline.txt"
            untracked_names = [private_name] + [
                f"owner-file-{index}" for index in range(68)]
            probe = mock.Mock()
            probe._git_result.return_value = SimpleNamespace(
                stdout="\0".join(untracked_names) + "\0")
            console = io.StringIO()
            with mock.patch.object(subject, "ROOT", temporary_root), \
                    contextlib.redirect_stdout(console):
                subject._emit_private_untracked_checkout_inventory(probe)
            inventory_files = list(private_directory.glob(
                "source-untracked-*.private.json"))
            self.assertEqual(len(inventory_files), 1)
            self.assertEqual(inventory_files[0].stat().st_mode & 0o777, 0o600)
            record = json.loads(inventory_files[0].read_text())
            self.assertEqual(record["schema"],
                             "swapz-private-untracked-inventory-v1")
            self.assertEqual(record["total_count"], len(untracked_names))
            self.assertEqual(record["paths"], untracked_names[:64])
            self.assertTrue(record["truncated"])
            self.assertIn("owner-only mode 0600", console.getvalue())
            self.assertNotIn("private/owner", console.getvalue())
            self.assertNotIn(private_name, console.getvalue())
            probe._git_result.assert_called_once_with(
                "ls-files", "--others", "--exclude-standard", "-z")
            # An invalid inventory cannot manufacture a new source PASS.
            probe._git_result.return_value = SimpleNamespace(stdout="invalid")
            missing_console = io.StringIO()
            with mock.patch.object(subject, "ROOT", temporary_root), \
                    contextlib.redirect_stdout(missing_console):
                subject._emit_private_untracked_checkout_inventory(probe)
            self.assertIn("inventory unavailable", missing_console.getvalue())
            self.assertEqual(len(list(private_directory.glob(
                "source-untracked-*.private.json"))), 1)

    def test_preconsent_canonical_drift_reuses_probe_source_gate(self):
        """The authoritative remote comparison must happen before consent."""
        expected_head = "a" * 40
        qualified_source = "a" * 40
        probe = mock.Mock()
        probe._git.side_effect = lambda *args: (
            "main" if args[0] == "symbolic-ref" else
            "" if args[0] == "status" else expected_head)
        probe._has_non_report_worktree_changes.return_value = False
        probe._development_code_source_sha.return_value = qualified_source
        probe._require_development_canonical_main.side_effect = RuntimeError(
            "canonical main contains changed source after qualification")
        specification = SimpleNamespace(loader=mock.Mock())
        arguments = [
            "--algorithm-ram-evidence",
            str(subject.ROOT / "build/tests/algorithm-ram-evidence.json"),
            "--algorithm-ram-nonce", "f" * 32,
        ]
        with mock.patch.object(
                subject.importlib.util, "spec_from_file_location",
                return_value=specification), \
             mock.patch.object(subject.importlib.util, "module_from_spec",
                               return_value=probe):
            self.assertEqual(
                subject._canonical_source_preflight(arguments),
                "canonical_source_advanced")
            probe._read_algorithm_ram_development_evidence.assert_called_once_with(
                Path(arguments[1]), subject.os.getuid(), expected_head,
                qualified_source, "f" * 32)
            probe._require_development_canonical_main.assert_called_once_with(
                expected_head, qualified_source)
            probe._require_development_canonical_main.side_effect = None
            self.assertIsNone(subject._canonical_source_preflight(arguments))
            probe._git.side_effect = lambda *args: (
                "main" if args[0] == "symbolic-ref" else
                " M tests/source.c" if args[0] == "status" else expected_head)
            probe._has_non_report_worktree_changes.return_value = True
            probe._development_dirty_worktree_kinds.return_value = "tracked_source"
            self.assertEqual(
                subject._canonical_source_preflight(arguments),
                "local_checkout_changed_kind_tracked_source")
            probe._development_dirty_worktree_kinds.return_value = (
                "tracked_source,generated_report,untracked")
            self.assertEqual(
                subject._canonical_source_preflight(arguments),
                "local_checkout_changed_kind_tracked_source_generated_report_untracked")
            # The generated report does not block source admission by itself.
            probe._has_non_report_worktree_changes.return_value = False
            probe._development_dirty_worktree_kinds.return_value = "generated_report"
            self.assertIsNone(subject._canonical_source_preflight(arguments))
            probe._git.side_effect = lambda *args: (
                "main" if args[0] == "symbolic-ref" else
                "" if args[0] == "status" else
                "b" * 40 if args[:2] == ("rev-parse", "origin/main")
                else expected_head)
            self.assertEqual(
                subject._canonical_source_preflight(arguments),
                "local_tracking_main_mismatch")
            probe._git.side_effect = lambda *args: (
                "other-branch" if args[0] == "symbolic-ref" else expected_head)
            self.assertEqual(
                subject._canonical_source_preflight(arguments),
                "local_checkout_not_main")
            probe._git.side_effect = lambda *args: (
                "main" if args[0] == "symbolic-ref" else
                "?? private-file" if args[0] == "status" else expected_head)
            probe._has_non_report_worktree_changes.return_value = True
            probe._development_dirty_worktree_kinds.return_value = "untracked"
            with mock.patch.object(
                    subject, "_emit_private_untracked_checkout_inventory"
                    ) as inventory:
                self.assertEqual(
                    subject._canonical_source_preflight(arguments),
                    "local_checkout_changed_kind_untracked")
                inventory.assert_called_once_with(probe)

    def test_canonical_drift_blocks_before_prompt_or_new_privileged_run(self):
        candidate = {
            "path": "/dev/sda1", "parent": "/dev/sda",
            "partuuid": "example-01", "size_bytes": 128 * 1024 * 1024,
            "selector": "/dev/disk/by-partuuid/example-01",
        }
        for reason, next_step in (
                ("canonical_source_advanced", "rerun make test"),
                ("local_checkout_changed_kind_generated_report",
                 "generated report"),
                ("local_tracking_main_mismatch", "reconcile local main")):
            with self.subTest(reason=reason), mock.patch.dict(subject.os.environ, {
                        "SWAPZ_ALGORITHM_RAM_EVIDENCE": str(
                            subject.ROOT / "build/tests/algorithm-ram-evidence.json"),
                        "SWAPZ_ALGORITHM_RAM_NONCE": "f" * 32}), \
                 mock.patch.object(subject.sys.stdin, "isatty", return_value=True), \
                 mock.patch.object(subject.sys.stdout, "isatty", return_value=True), \
                 mock.patch.object(subject, "_require_read_only_preflight",
                                   return_value=candidate), \
                 mock.patch.object(subject, "_canonical_source_preflight",
                                   return_value=reason) as verify, \
                 mock.patch("builtins.input") as consent, \
                 mock.patch.object(subject.subprocess, "run") as privileged, \
                 mock.patch("builtins.print") as printer:
                self.assertEqual(subject.main(), 2)
                verify.assert_called_once()
                consent.assert_not_called()
                privileged.assert_not_called()
                output = " ".join(str(call) for call in printer.call_args_list)
                self.assertIn(f"reason={reason}", output)
                self.assertIn(
                    f"PHYSICAL_ALGORITHM_SOURCE_ADMISSION={reason}", output)
                self.assertIn("phase=before_consent", output)
                self.assertIn("new trial NOT RUN", output)
                self.assertIn(next_step, output)

    def test_virtualization_gate_reports_vm_without_device_discovery(self):
        with mock.patch.object(subject.shutil, "which",
                               return_value="/usr/bin/systemd-detect-virt"), \
             mock.patch.object(
                 subject.subprocess, "run",
                 return_value=SimpleNamespace(
                     returncode=0, stdout="vmware\n", stderr="")):
            with self.assertRaisesRegex(ValueError, "vm: vmware"):
                subject._require_bare_metal_host()

    def test_vm_development_requires_explicit_mode_and_no_container(self):
        def detect(command, **_kwargs):
            virtual = command[-1] == "--vm"
            return SimpleNamespace(
                returncode=0 if virtual else 1,
                stdout="vmware\n" if virtual else "none\n", stderr="")
        with mock.patch.object(subject.shutil, "which",
                               return_value="/usr/bin/systemd-detect-virt"), \
             mock.patch.object(subject.subprocess, "run",
                               side_effect=detect):
            self.assertTrue(subject._require_bare_metal_host(
                allow_virtual=True))
            with self.assertRaisesRegex(ValueError, "vm: vmware"):
                subject._require_bare_metal_host()
        with mock.patch.object(subject.shutil, "which",
                               return_value="/usr/bin/systemd-detect-virt"), \
             mock.patch.object(subject.subprocess, "run",
                               return_value=SimpleNamespace(
                                   returncode=0, stdout="docker\n", stderr="")):
            with self.assertRaisesRegex(ValueError, "container"):
                subject._require_bare_metal_host(allow_virtual=True)

    def test_recovery_precedes_swap_partition_discovery(self):
        with mock.patch.object(subject.os, "geteuid", return_value=1000), \
             mock.patch.object(subject, "_require_development_linux_abi"), \
             mock.patch.object(subject, "_require_bare_metal_host",
                               return_value=False), \
             mock.patch.object(subject, "_recover_pending_algorithm_trial",
                               side_effect=subject.PendingRecoveryError(
                                   "recovery unresolved")) as recovery, \
             mock.patch.object(subject.subprocess, "run") as device_discovery:
            with self.assertRaises(subject.PendingRecoveryError):
                subject._require_read_only_preflight()
        recovery.assert_called_once()
        device_discovery.assert_not_called()

    def test_unsupported_arch_recovers_pending_trial_but_refuses_new_partition_trial(self):
        with mock.patch.object(subject.os, "geteuid", return_value=1000), \
             mock.patch.object(subject, "_require_development_linux_abi"), \
             mock.patch.object(subject.platform, "machine", return_value="riscv64"), \
             mock.patch.object(subject, "_require_bare_metal_host", return_value=True), \
             mock.patch.object(subject, "_recover_pending_algorithm_trial") as recovery, \
             mock.patch.object(subject.subprocess, "run") as discovery, \
             mock.patch("builtins.input") as consent:
            with self.assertRaisesRegex(ValueError, "kernel.*x86_64"):
                subject._require_read_only_preflight()
        recovery.assert_called_once()
        discovery.assert_not_called()
        consent.assert_not_called()

    def test_auto_recovery_is_one_fixed_root_command(self):
        with mock.patch.object(subject.shutil, "which",
                               return_value="/usr/bin/sudo"), \
             mock.patch.object(subject.subprocess, "run",
                               return_value=SimpleNamespace(returncode=0)) as run:
            subject._recover_pending_algorithm_trial()
        self.assertEqual(run.call_args.args[0], [
            "/usr/bin/sudo", "--", subject.sys.executable, "-I", "-B",
            str(subject.ROOT / "tests/tools/physical-swap-probe.py"),
            "recover-pending"])
        with mock.patch.object(subject.shutil, "which",
                               return_value="/usr/bin/sudo"), \
             mock.patch.object(subject.subprocess, "run",
                               return_value=SimpleNamespace(returncode=3)):
            with self.assertRaises(subject.PendingRecoveryError):
                subject._recover_pending_algorithm_trial()

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

    def test_confirmation_question_is_visible_and_flushed_before_input(self):
        """A line-oriented SSH log must show the exact target and safe default."""
        candidate = {
            "path": "/dev/sda4", "parent": "/dev/sda",
            "partuuid": "7fb9401d-04", "size_bytes": 16 * 1024 ** 3,
            "selector": "/dev/disk/by-partuuid/7fb9401d-04",
            "parent_has_other_partitions": True,
        }
        question = (
            "  Run bounded swapz Linux swap trial on /dev/sda4 "
            "(PARTUUID 7fb9401d-04)? [y/N]\n")
        instructions = (
            "  Enter y/yes to authorize; n/no or Enter declines:\n")

        class OperatorTerminal(io.StringIO):
            def __init__(self):
                super().__init__()
                self.flushed_output = []

            def isatty(self):
                return True

            def flush(self):
                self.flushed_output.append(self.getvalue())
                super().flush()

        for answer, approved in (("", False), ("n", False),
                                 ("no", False), ("yes", True)):
            with self.subTest(answer=answer):
                terminal = OperatorTerminal()

                def read_answer():
                    # The complete question must reach a line-based observer
                    # before input() is invoked, not after the response.
                    self.assertTrue(terminal.flushed_output)
                    self.assertIn(
                        question + instructions,
                        terminal.flushed_output[-1])
                    self.assertTrue(
                        terminal.flushed_output[-1].endswith(instructions))
                    return answer

                with mock.patch.object(
                        subject.sys, "stdout", terminal), \
                     mock.patch.object(
                         subject.sys.stdin, "isatty", return_value=True), \
                     mock.patch.object(
                         subject, "_require_read_only_preflight",
                         return_value=candidate), \
                     mock.patch.object(
                         subject, "_algorithm_ram_evidence_arguments",
                         return_value=[]), \
                     mock.patch.object(
                         subject, "_canonical_source_preflight",
                         return_value=None), \
                     mock.patch("builtins.input",
                                side_effect=read_answer) as consent, \
                     mock.patch.object(
                         subject.shutil, "which",
                         return_value="/usr/bin/sudo"), \
                     mock.patch.object(
                         subject.subprocess, "run",
                         return_value=SimpleNamespace(returncode=0)) as privileged:
                    self.assertEqual(subject.main(), 0 if approved else 2)
                consent.assert_called_once_with()
                self.assertEqual(privileged.call_count, int(approved))
                self.assertEqual(terminal.getvalue().count(question), 1)
                if not approved:
                    self.assertIn(
                        "PHYSICAL_ALGORITHM_REAL_SWAP=NOT_RUN reason=declined",
                        terminal.getvalue())

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
            "/usr/bin/sudo", "--", subject.sys.executable, "-I", "-B",
            str(subject.ROOT / "tests/tools/physical-swap-probe.py"),
            "run", "--device", candidate["selector"],
            "--confirm-device", candidate["selector"],
            "--development-only", "--algorithm-real-swap",
        ])

    def test_vm_confirmation_passes_explicit_flag_to_privileged_helper(self):
        candidate = {
            "path": "/dev/sdc1", "parent": "/dev/sdc",
            "partuuid": "deadbeef-01", "size_bytes": 128 * 1024 * 1024,
            "selector": "/dev/disk/by-uuid/example",
            "virtual_device_only": True,
        }
        with mock.patch.object(subject.sys.stdin, "isatty",
                               return_value=True), \
             mock.patch.object(subject.sys.stdout, "isatty",
                               return_value=True), \
             mock.patch.object(subject, "_require_read_only_preflight",
                               return_value=candidate), \
             mock.patch("builtins.input", return_value="yes"), \
             mock.patch.object(subject.shutil, "which",
                               return_value="/usr/bin/sudo"), \
             mock.patch.object(subject.subprocess, "run",
                               return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(subject.main(), 0)
        command = run.call_args.args[0]
        self.assertEqual(command[-3:], [
            "--development-only", "--algorithm-real-swap",
            "--virtual-device-only",
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
        disk = {"path": "/dev/sda", "type": "disk", "tran": "sata",
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
        self.assertEqual(candidates[0]["parent_transport"], "sata")
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
            if command in (
                    ["/usr/bin/systemd-detect-virt", "--vm"],
                    ["/usr/bin/systemd-detect-virt", "--container"]):
                return SimpleNamespace(returncode=1, stdout="none\n")
            if command[0] == "lsblk":
                self.assertEqual(command[:4], [
                    "lsblk", "--json", "--tree", "--bytes"])
                self.assertEqual(command[-1],
                                 "PATH,TYPE,FSTYPE,UUID,PARTUUID,SIZE,TRAN,MOUNTPOINTS")
                return SimpleNamespace(returncode=0,
                                       stdout=json.dumps({"blockdevices": [disk]}))
            self.fail("unexpected subprocess invocation")

        def resolve(path):
            if str(path) == "/dev/disk/by-partuuid/7fb9401d-04":
                return "/dev/sda4"
            return str(path)

        with mock.patch.object(subject.os, "geteuid", return_value=1000), \
             mock.patch.object(subject.platform, "machine",
                               return_value="x86_64"), \
             mock.patch.object(subject.shutil, "which",
                               return_value="/usr/bin/systemd-detect-virt"), \
             mock.patch.object(subject.subprocess, "run", side_effect=run), \
             mock.patch.object(subject, "_recover_pending_algorithm_trial"), \
             mock.patch.object(subject.Path, "exists", return_value=False), \
             mock.patch.object(subject.Path, "read_text", return_value=(
                 "Filename Type Size Used Priority\n"
                 "/dev/sda4 partition 16777212 0 -1\n")), \
             mock.patch.object(subject.os, "stat", return_value=SimpleNamespace(
                 st_mode=stat.S_IFBLK, st_rdev=42)), \
             mock.patch.object(subject.Path, "is_symlink", return_value=True), \
             mock.patch.object(subject.os.path, "realpath", side_effect=resolve):
            selected = subject._require_read_only_preflight()

        self.assertEqual(len(commands), 3)
        self.assertEqual(selected["path"], "/dev/sda4")
        self.assertEqual(selected["partuuid"], "7fb9401d-04")
        self.assertEqual(
            selected["selector"], "/dev/disk/by-partuuid/7fb9401d-04")
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

    def test_shared_parent_reaches_only_privileged_fail_closed_gate(self):
        candidate = {
            "path": "/dev/sda4", "parent": "/dev/sda",
            "partuuid": "7fb9401d-04", "size_bytes": 16 * 1024 ** 3,
            "selector": "/dev/disk/by-uuid/example",
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
             mock.patch("builtins.input", return_value="yes") as answer, \
             mock.patch.object(subject.shutil, "which",
                               return_value="/usr/bin/sudo"), \
             mock.patch.object(subject.subprocess, "run",
                               return_value=mock.Mock(returncode=2)) as command, \
             mock.patch("builtins.print") as output:
            self.assertEqual(subject.main(), 2)
        answer.assert_called_once()
        command.assert_called_once()
        self.assertEqual(command.call_args.args[0][-2:],
                         ["--development-only", "--algorithm-real-swap"])
        messages = "\n".join(str(call) for call in output.call_args_list)
        self.assertIn("Shared-root candidate", messages)
        self.assertIn("protected host-scope record", messages)

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
