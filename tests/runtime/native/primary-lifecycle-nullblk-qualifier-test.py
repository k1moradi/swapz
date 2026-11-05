#!/usr/bin/env python3
"""Canonical rootless contracts for the native owned-null_blk qualifier.

Finalizer safety standard: retain creation and power-inode identity, refuse
same-name replacement and unobservable/foreign state before recovery, bind
the destructive power write to the pinned original inode without creation,
keep partial-setup cleanup nounset-safe, preserve the first error, and redact
private cleanup diagnostics.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import os
import re
import shlex
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tests/tools/qualify-primary-lifecycle-nullblk.sh"
SHIM = ROOT / "tests/tools/primary-lifecycle-fault-shim.c"
SHIM_HARNESS = ROOT / "tests/runtime/native/primary-lifecycle-fault-shim-harness.c"
PRIMARY = ROOT / "src/userspace/swapz-primary.c"
ROOT_MAKEFILE = ROOT / "Makefile"


class PrimaryLifecycleNullblkQualifierContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = SCRIPT.read_text(encoding="utf-8")
        cls.shim = SHIM.read_text(encoding="utf-8")
        cls.primary = PRIMARY.read_text(encoding="utf-8")

    def test_fault_boundary_is_private_and_noninstalled(self):
        self.assertIn('FAULT_FIXTURE="tests/tools/primary-lifecycle-fault-shim.c"',
                      self.script)
        for option in ("--wrap=syscall", "--wrap=open", "--wrap=fsync"):
            self.assertIn(option, self.script)
        self.assertNotIn("primary-lifecycle-fault-shim", ROOT_MAKEFILE.read_text())
        self.assertNotIn("SWAPZ_PRIMARY_TEST_FAULT", self.primary)
        self.assertNotIn(
            "SWAPZ_PRIMARY_TEST_FSYNC_FAIL_DIRECTORY_CALL", self.primary)

    def test_all_native_interruption_and_negative_cases_are_declared(self):
        for phase in (
            "start-starting",
            "start-header-written",
            "start-module-inserted",
            "start-module-loaded",
            "start-mapper-inactive",
            "start-mapper-resumed",
            "start-mkswap",
            "start-swapon",
            "stop-stopping",
            "stop-swapoff",
            "stop-mapper-removed",
            "stop-module-unloaded",
            "stop-restored",
            "recover-recovering",
            "recover-swapoff",
            "recover-mapper-removed",
            "recover-module-unloaded",
            "recover-restored",
        ):
            self.assertIn(phase, self.script)
            self.assertIn(
                f'SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("{phase}")',
                self.primary)
        self.assertIn(
            "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION_RECOVERY=cases:18",
            self.script)
        for case in (
            "swapon-eintr-applied",
            "swapon-eintr-noeffect",
            "swapon-eio-noeffect",
            "post-swapon-inventory-eio",
            "swapoff-eintr-applied",
            "swapoff-eintr-noeffect",
            "swapoff-eio-noeffect",
            "swapoff-ebusy-noeffect",
            "post-swapoff-inventory-eio",
            "state-dir-fsync",
            "stale-run-id",
            "lost-state-provenance",
            "wrong-mapper-identity",
        ):
            self.assertIn(case, self.script)
        self.assertIn(
            "PASS_LOADED_PRIMARY_NULLBLK_NEGATIVE_RECOVERY=cases:13",
            self.script)
        self.assertIn("definite_io_error:true", self.script)

    def test_interruption_oracle_proves_exact_mapper_and_repeat_recovery(self):
        self.assertIn('[[ "$mapper_uuid" == "SWAPZ-PRIMARY-$RUN_ID" ]]', self.script)
        self.assertIn('dmsetup table --inactive "$DMNAME"', self.script)
        self.assertIn('"$table_target" == swapz', self.script)
        self.assertIn('"$table_lower" == "$PART_DEVNO"', self.script)
        self.assertIn("assert_unrelated_host_swap_identity", self.script)
        self.assertIn("assert_repeat_recovery_is_safe", self.script)
        self.assertIn('[[ "$rc" -ne 0 ]]', self.script)
        self.assertIn('[[ "$after_state" == "$before_state"', self.script)

    def test_wrong_mapper_case_never_forces_removal(self):
        self.assertNotRegex(self.script, r"dmsetup\s+remove\s+--force")
        self.assertNotRegex(self.script, r"\brmmod\b")
        self.assertIn('[[ "$open_count" == 0 ]]', self.script)
        self.assertIn('[[ "$(mapper_swap_entry_count)" == 0 ]]', self.script)
        self.assertIn('dmsetup remove "$DMNAME"', self.script)

    def test_qualifier_never_targets_the_authorized_physical_card(self):
        for forbidden in ("/dev/sda", "/dev/mmcblk", "/dev/nvme"):
            self.assertNotIn(forbidden, self.script)
        self.assertIn("memory_backed", self.script)
        self.assertIn("nullb-swapz-$TOKEN", self.script)

    def test_partuuid_alias_comes_from_udev_for_verified_owned_partition(self):
        partuuid_proof = self.script.index(
            'grep -Fxq "PARTUUID=$PARTUUID" "$PART_SYSFS/uevent"')
        trigger = self.script.index(
            'udevadm trigger --action=add --subsystem-match=block')
        trigger_settle = self.script.index(
            'udevadm settle --timeout=10', trigger)
        trigger_command = self.script[trigger:trigger_settle]
        alias_wait = self.script.index(
            'if [[ ! -e "$BY_PARTUUID" && ! -L "$BY_PARTUUID" ]]; then')
        alias_verifier = self.script.index('udev_alias_verified() {')
        self.assertIn('"$PART_SYSFS"', trigger_command)
        self.assertLess(partuuid_proof, trigger)
        self.assertLess(trigger, alias_wait)
        self.assertLess(partuuid_proof, alias_verifier)
        self.assertIn('DEVPATH=="%s"', self.script)
        uuid_import = self.script.index('IMPORT{builtin}="blkid"')
        uuid_match = self.script.index('ENV{ID_PART_ENTRY_UUID}=="%s"')
        self.assertLess(uuid_import, uuid_match)
        self.assertIn('\\nACTION=="add"', self.script)
        self.assertIn('SYMLINK+="disk/by-partuuid/$env{ID_PART_ENTRY_UUID}"',
                      self.script)
        self.assertIn('udevadm info --query=property --path="$PART_SYSFS"',
                      self.script)
        self.assertIn('udevadm control --reload-rules', self.script)
        self.assertIn('udev_alias_remains_after_device_removal', self.script)
        self.assertIn('UDEV_PARTUUID_DIAGNOSTIC=', self.script)
        self.assertIn(
            'udevadm test --verbose --action=add "$PART_SYSFS"', self.script)
        self.assertNotRegex(self.script, r"(?m)^\s*ln\s+-s\b")

    def test_owned_nullblk_nodes_match_sysfs_devno_before_mutation(self):
        lower_sysfs = self.script.index(
            'DEVNO="$(cat "/sys/block/$DISK/dev")"')
        lower_node = self.script.index(
            'LOWER_NODE_DEVNO="$(block_node_devno "$LOWER")"', lower_sysfs)
        partition_write = self.script.index(
            'if ! sfdisk --lock --wipe always "$LOWER"', lower_node)
        self.assertLess(lower_sysfs, lower_node)
        self.assertLess(lower_node, partition_write)
        self.assertIn(
            '[[ "$LOWER_NODE_DEVNO" == "$DEVNO" ]] ||\n'
            '\tfail "owned null_blk device node major/minor differs from sysfs"',
            self.script[lower_node:partition_write])

        partition_sysfs = self.script.index(
            'PART_DEVNO="$(cat "$PART_SYSFS/dev")"', partition_write)
        partition_node = self.script.index(
            'PARTITION_NODE_DEVNO="$(block_node_devno "$PARTITION")"',
            partition_sysfs)
        partuuid_read = self.script.index(
            'PARTUUID="$(blkid -s PARTUUID -o value "$PARTITION"', partition_node)
        mkswap = self.script.index('mkswap "$PARTITION" >/dev/null',
                                   partuuid_read)
        self.assertLess(partition_sysfs, partition_node)
        self.assertLess(partition_node, partuuid_read)
        self.assertLess(partuuid_read, mkswap)
        self.assertIn(
            '[[ "$PARTITION_NODE_DEVNO" == "$PART_DEVNO" ]] ||\n'
            '\tfail "owned null_blk partition node major/minor differs from sysfs"',
            self.script[partition_node:partuuid_read])

        alias_start = self.script.index('udev_alias_verified() {', partuuid_read)
        alias_end = self.script.index('\n}', alias_start)
        alias_verifier = self.script[alias_start:alias_end]
        self.assertIn('block_node_devno "$BY_PARTUUID"', alias_verifier)
        self.assertIn('block_node_devno "$PARTITION"', alias_verifier)
        self.assertIn('"$alias_dev" == "$PART_DEVNO"', alias_verifier)
        self.assertIn('"$partition_dev" == "$PART_DEVNO"', alias_verifier)

    def test_udev_claim_requires_exact_published_alias_token(self):
        start = self.script.index("udev_alias_verified() {")
        end = self.script.index("\n}", start)
        verifier = self.script[start:end]
        self.assertIn("sed -n 's/^DEVLINKS=//p'", verifier)
        self.assertIn('read -r -a published_links <<< "$devlinks"',
                      verifier)
        self.assertIn('[[ "$published_link" == "$BY_PARTUUID" ]]',
                      verifier)
        self.assertNotIn('grep -Fq -- "$BY_PARTUUID"', verifier)

    def test_mapper_table_requires_exact_manifest_geometry_and_parameters(self):
        start = self.script.index("assert_exact_owned_mapper() {")
        end = self.script.index("\n}", start)
        verifier = self.script[start:end]
        self.assertIn(
            '''expected_table="$(sed -n 's/^dm_table=//p' '''
            '''"$RECOVERY_BASE/primary-manifest-$RUN_ID.txt")"''',
            verifier)
        self.assertIn(
            '[[ -n "$expected_table" && "$mapper_table" == "$expected_table" ]]',
            verifier)

    def test_partition_reread_is_locked_and_not_duplicated_after_sfdisk(self):
        partition_write = self.script.index(
            'if ! sfdisk --lock --wipe always "$LOWER"')
        partition_settle = self.script.index(
            'udevadm settle --timeout=10 || blocked "udev did not settle owned null_blk partition"',
            partition_write,
        )
        self.assertLess(partition_write, partition_settle)
        self.assertNotIn('blockdev --rereadpt "$LOWER"', self.script)

    def test_swap_signature_setup_uses_portable_mkswap_defaults(self):
        self.assertIn('mkswap "$PARTITION" >/dev/null', self.script)
        self.assertNotIn('mkswap --no-discard', self.script)

    def test_qualifier_shell_syntax_is_valid(self):
        subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            cwd=ROOT,
            check=True,
        )

    def test_normal_start_proves_swap_and_durable_identity_fail_closed(self):
        start = self.script.index(
            'note "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=start"')
        stop = self.script.index(
            'note "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=stop"', start)
        positive_path = self.script[start:stop]
        unique_active_guard = (
            '[[ "$active_mapper_entries" == 1 ]] ||\n'
            '\tfail "manager-created mapper is not the unique active swap identity"'
        )
        proof_steps = (
            'assert_exact_owned_mapper 1',
            '[[ "$mapper_node_dev" == "$mapper_dev" ]] ||\n'
            '\tfail "published mapper node identity differs from Device Mapper control"',
            'active_mapper_entries="$(mapper_swap_entry_count)" ||\n'
            '\tfail "cannot resolve every /proc/swaps device identity after start"',
            unique_active_guard,
            'assert_lifecycle_state "$RUN_ID" ACTIVE null ||\n'
            '\tfail "start did not persist exact durable ACTIVE transaction"',
            'assert_owned_transaction_records 1 ||\n'
            '\tfail "start did not retain canonical run-bound consumed/active ownership"',
            'assert_unrelated_host_swap_identity "normal start"',
            'active_backing_header_sha256=',
        )
        # Exact-once matching prevents a stale correct guard elsewhere in the
        # section from masking a broken or misbound fail-closed operator.
        for proof_step in proof_steps:
            self.assertEqual(positive_path.count(proof_step), 1)
        for earlier, later in zip(proof_steps, proof_steps[1:]):
            self.assertLess(positive_path.index(earlier),
                            positive_path.index(later))
        self.assertNotIn('|| ! -e "$swap_path"', positive_path)
        # The shared swap oracle must abort on a missing inventory path,
        # rather than interpreting it as proof of inactivity.
        self.assertIn('[[ -e "$swap_path" ]] || return 1', self.script)

    def test_normal_stop_proves_backing_header_preservation(self):
        self.assertIn("block0_sha256() {", self.script)
        before_stop = self.script.index(
            'active_backing_header_sha256="$(block0_sha256 "$PARTITION")"')
        stop = self.script.index(
            'note "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=stop"',
            before_stop)
        after_stop = self.script.index(
            'stopped_backing_header_sha256="$(block0_sha256 "$PARTITION")"',
            stop)
        comparison = self.script.index(
            '[[ "$stopped_backing_header_sha256" == '
            '"$active_backing_header_sha256" ]]',
            after_stop)
        lifecycle_pass = self.script.index(
            'note "PASS_LOADED_PRIMARY_NULLBLK_LIFECYCLE=',
            comparison)
        self.assertLess(before_stop, stop)
        self.assertLess(stop, after_stop)
        self.assertLess(after_stop, comparison)
        self.assertLess(comparison, lifecycle_pass)

    def test_prepare_failure_emits_read_only_gate_plan(self):
        self.assertIn('"$CONTROL" primary plan', self.script)
        self.assertIn(')" || true', self.script)
        self.assertIn('PRIMARY_PREPARE_DIAGNOSTIC_PLAN=', self.script)


    def test_preparation_phase_matches_each_explicit_refusal_gate(self):
        prepare = self.primary[
            self.primary.index("static int swapz_primary_prepare_metadata("):
            self.primary.index("static int swapz_primary_unload_owned_module(", 
                               self.primary.index("static int swapz_primary_prepare_metadata("))]
        owner_claim = prepare.index("swapz_primary_claim_partition_owner_at(")
        # Every early refusal must precede durable claim or target mutation.
        for phase in (
            "recovery-directory-safety",
            "recovery-filesystem-persistence",
            "recovery-target-device-separation",
            "recovery-physical-parent-identity",
            "prior-active-marker",
            "qualification-source-identity",
            "qualified-artifact-identity",
            "target-geometry-identity",
            "original-header-rollback-proof",
            "target-physical-parent-identity",
            "target-recovery-parent-separation",
            "target-mounted-in-visible-namespace",
            "root-device-parent-identity",
            "target-root-device-parent-separation",
            "repeated-target-physical-parent-identity",
            "repeated-target-recovery-parent-separation",
            "repeated-target-mounted-in-visible-namespace",
            "repeated-root-device-parent-identity",
            "repeated-target-root-parent-separation",
        ):
            with self.subTest(phase=phase):
                index = prepare.index('failure_phase = "' + phase + '";')
                self.assertLess(index, owner_claim)
                gate = prepare[index:prepare.index("goto out;", index)]
                self.assertIn("errno = EPERM;", gate)

        for phase, helper in (
            ("qualification-report-read", "swapz_primary_read_qualification_report"),
            ("qualified-artifact-hash-readback", "swapz_primary_live_artifact_hashes"),
            ("raw-target-swap-inventory", "swapz_primary_original_swap_is_quiescent"),
            ("cross-namespace-mount-inventory", "swapz_primary_read_mount_facts"),
            ("repeated-raw-target-swap-inventory", "swapz_primary_original_swap_is_quiescent"),
            ("repeated-cross-namespace-mount-inventory", "swapz_primary_read_mount_facts"),
            ("physical-parent-swap-inventory", "swapz_primary_swap_device_active"),
            ("final-raw-target-swap-inventory", "swapz_primary_original_swap_is_quiescent"),
        ):
            with self.subTest(phase=phase):
                index = prepare.index('failure_phase = "' + phase + '";')
                self.assertLess(index, owner_claim)
                self.assertIn(helper, prepare[index:prepare.index("goto out;", index)])

        for mutation in ("swapon(", "swapoff(", "swapz_primary_dm_create_mapper(",
                         "swapz_primary_write_header_checked_fd("):
            self.assertNotIn(mutation, prepare)

    def test_prepare_preclaim_revalidation_has_distinct_failure_phases(self):
        prepare = self.primary[
            self.primary.index("static int swapz_primary_prepare_metadata("):
            self.primary.index("static int swapz_primary_unload_owned_module(",
                               self.primary.index("static int swapz_primary_prepare_metadata("))]
        final_check = prepare[
            prepare.index('failure_phase = "final-raw-target-swap-inventory";'):
            prepare.index('failure_phase = "run-id-and-header-construction";')]
        # A stale source, parent, mount, or recovery readback is not a raw-swap
        # inventory error. Likewise, an active parent swap is not ESTALE.
        identity_check = final_check[:final_check.index(
            "if (swapz_primary_target_preflight(")]
        self.assertIn('failure_phase = "final-preclaim-identity-revalidation";',
                      identity_check)
        identity_phase = final_check.index(
            'failure_phase = "final-preclaim-identity-revalidation";')
        identity_gate = final_check[
            identity_phase:final_check.index("goto out;", identity_phase)]
        self.assertIn("errno = ESTALE;", identity_gate)

        # The parent-swap phase must be selected before invoking the reader,
        # so an unreadable inventory keeps its own errno and diagnostic.
        parent_phase = final_check.index(
            'failure_phase = "final-physical-parent-swap-inventory";')
        parent_call = final_check.index(
            "int verified_parent_swap_active =", parent_phase)
        parent_gate = final_check[
            parent_phase:final_check.index("goto out;", parent_call)]
        self.assertLess(parent_phase, parent_call)
        self.assertIn("if (verified_parent_swap_active > 0)", parent_gate)
        self.assertIn("errno = EBUSY;", parent_gate)

    def test_preparation_failure_formats_do_not_expose_transaction_ids(self):
        preparation = self.primary[
            self.primary.index("static int swapz_primary_prepare_metadata("):
            self.primary.index("static int swapz_primary_unload_owned_module(",
                               self.primary.index("static int swapz_primary_prepare_metadata("))]
        failure_format = preparation[preparation.index("if (result < 0 && claimed)"):
                                     preparation.index("if (result < 0)\n\t\terrno = saved_errno;")]
        # Recovery claims can be retained, but their 32-hex IDs belong in
        # durable private metadata, not in public diagnostic records.
        self.assertIn("claim=retained target_unchanged=true", failure_format)
        self.assertIn("claim=none", failure_format)
        self.assertNotIn("run_id=%s", failure_format)
        self.assertNotIn("target=%s", failure_format)

    def test_prepare_global_lock_close_has_phase_specific_diagnostic(self):
        action_start = self.primary.index(
            "static int swapz_primary_run_mutating_action(")
        action_end = self.primary.index(
            "static int swapz_primary_qualification_import_serialized(",
            action_start)
        action = self.primary[action_start:action_end]
        close_gate_start = action.index(
            "if (close(mutation_lock_fd) < 0 && result == 0) {")
        close_gate = action[
            close_gate_start:action.index("return result;", close_gate_start)]
        close_gate = re.sub(r'"\s*"', "", close_gate)
        self.assertIn(
            "PRIMARY_PREPARE=FAILED phase=global-mutation-lock-close ",
            close_gate)
        self.assertIn("claim=retained target_unchanged=true", close_gate)
        self.assertGreater(
            action.index('printf("PRIMARY_PREPARE=READY'),
            action.index("if (close(mutation_lock_fd) < 0 && result == 0) {"))

        # A successful inner prepare must not publish a run ID before the
        # outer global mutation lock is known to have closed successfully.
        prepare_start = self.primary.index(
            "static int swapz_primary_prepare_metadata(")
        prepare_end = self.primary.index(
            "static int swapz_primary_unload_owned_module(", prepare_start)
        prepare = self.primary[prepare_start:prepare_end]
        self.assertNotIn("PRIMARY_PREPARE=READY", prepare)

    def test_rootless_prepare_diagnostic_verifier_rejects_leaks_and_ambiguity(self):
        begin = self.script.index("verify_prepare_failure_diagnostic() {")
        end = self.script.index("\n}", begin) + 2
        verifier = self.script[begin:end]
        program = ("fail() { printf '%s\\n' FAIL >&2; exit 1; }\n" +
                   verifier + '\nverify_prepare_failure_diagnostic "$1"\n')

        def command_output(diagnostic, error_text):
            return (
                diagnostic + "\n"
                "BLOCKED: primary-swap preparation failed: " + error_text
            )

        def check(output, should_pass):
            result = subprocess.run(
                ["bash", "-c", program, "synthetic-prepare", output],
                capture_output=True, text=True, timeout=5, check=False,
                cwd=ROOT)
            self.assertEqual(result.returncode == 0, should_pass,
                             result.stdout + result.stderr)
            if should_pass:
                expected = next(
                    line for line in output.splitlines()
                    if line.startswith("PRIMARY_PREPARE=FAILED "))
                self.assertEqual(result.stderr.strip(), expected)
            else:
                self.assertEqual(result.stderr.strip(), "FAIL")
            self.assertEqual(result.stdout, "")

        permitted = "Operation not permitted"
        busy = "Device or resource busy"
        source_mismatch = (
            "PRIMARY_PREPARE=FAILED phase=qualification-source-identity "
            f"errno=1 error={permitted} claim=none"
        )
        retained_manifest = (
            "PRIMARY_PREPARE=FAILED phase=manifest-write "
            f"errno=1 error={permitted} claim=retained target_unchanged=true"
        )
        package_busy = (
            "PRIMARY_PREPARE=FAILED phase=package-transaction-preflight "
            f"errno=16 error={busy}"
        )
        close_error = "Input/output error"
        lock_close = (
            "PRIMARY_PREPARE=FAILED phase=global-mutation-lock-close "
            f"errno=5 error={close_error} "
            "claim=retained target_unchanged=true"
        )
        check(command_output(source_mismatch, permitted), True)
        check(command_output(retained_manifest, permitted), True)
        check(command_output(package_busy, busy), True)
        check(command_output(lock_close, close_error), True)

        for output in (
            "",
            "PRIMARY_PREPARE=FAILED",
            source_mismatch,
            command_output(source_mismatch, busy),
            command_output(source_mismatch, permitted) + "\n/private/secret",
            command_output(source_mismatch, permitted) + "\nsecret=private",
            command_output(source_mismatch, permitted) + "\ntransaction_id=private",
            command_output(source_mismatch, permitted) + "\nswap=/unrelated",
            command_output(source_mismatch, permitted) + "\n"
            "PRIMARY_PREPARE=READY run_id=" + "a" * 32 +
            " source=" + "b" * 40,
            command_output(source_mismatch, permitted) + "\n"
            "BLOCKED: primary-swap preparation failed: " + permitted,
            command_output(
                "PRIMARY_PREPARE=FAILED phase=raw-target-swap-inventory "
                "errno=0 error=Success claim=none", "Success"),
            command_output(
                "PRIMARY_PREPARE=FAILED phase=raw-target-swap-inventory "
                f"errno=1 error={busy} claim=none", busy),
            command_output(
                "PRIMARY_PREPARE=FAILED phase=raw-target-swap-inventory "
                f"errno=1 error={permitted} claim=none path=/private/secret",
                permitted),
            command_output(
                "PRIMARY_PREPARE=FAILED phase=raw-target-swap-inventory "
                f"errno=1 error={permitted} "
                "claim=retained target_unchanged=true", permitted),
            command_output(
                "PRIMARY_PREPARE=FAILED phase=manifest-write "
                f"errno=1 error={permitted} claim=none", permitted),
            command_output(
                "PRIMARY_PREPARE=FAILED phase=invented-unsafe-phase "
                f"errno=1 error={permitted} claim=none", permitted),
            command_output(
                "PRIMARY_PREPARE=FAILED phase=raw-target-swap-inventory "
                f"errno=1 error={permitted} run_id=" + "a" * 32 +
                " claim=retained target_unchanged=true", permitted),
            command_output(
                "PRIMARY_PREPARE=FAILED phase=raw-target-swap-inventory "
                f"errno=1 error={permitted} claim=none swap=/unrelated",
                permitted),
            command_output(
                "PRIMARY_PREPARE=FAILED phase=package-transaction-preflight "
                f"errno=16 error={busy} transaction_id=private", busy),
            command_output(
                "PRIMARY_PREPARE=FAILED phase=qualification-source-identity "
                "errno=4095 error=Unknown error 4095 claim=none",
                "Unknown error 4095"),
            command_output(source_mismatch, permitted) + "\n" +
            command_output(
                "PRIMARY_PREPARE=FAILED phase=qualified-artifact-identity "
                f"errno=1 error={permitted} claim=none", permitted),
        ):
            with self.subTest(output=output):
                check(output, False)
        failure_path = self.script[
            self.script.index('note "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=prepare"'):
            self.script.index('RUN_ID="$(printf', self.script.index(
                'note "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=prepare"'))]
        self.assertIn('verify_prepare_failure_diagnostic "$prepare_output"',
                      failure_path)
        self.assertIn('PRIMARY_PREPARE_DIAGNOSTIC_PLAN=available', failure_path)
        self.assertNotIn('printf \'%s\\n\' "$prepare_output" >&2', failure_path)

    def test_private_qualification_report_binds_running_kernel_release(self):
        self.assertIn('"kernel_release": os.uname().release', self.script)

    def test_fault_results_require_exact_hit_evidence(self):
        self.assertIn("report_fault_hit", self.shim)
        self.assertIn("SWAPZ_PRIMARY_TEST_FAULT_HIT", self.shim)
        self.assertIn("SWAPZ_PRIMARY_TEST_FSYNC_DIRECTORY_HIT", self.shim)
        self.assertIn(
            'grep -Fxq "SWAPZ_PRIMARY_TEST_FAULT_HIT=$fault"',
            self.script)
        for name in ("swapon-eintr-applied", "swapoff-eintr-applied"):
            self.assertIn(f"SWAPZ_PRIMARY_TEST_FAULT_HIT={name}", self.script)
        self.assertIn(
            "SWAPZ_PRIMARY_TEST_FSYNC_DIRECTORY_HIT=2", self.script)
        self.assertIn("S_ISDIR(info.st_mode)", self.shim)

    def test_stale_run_mutation_preserves_canonical_serialization(self):
        self.assertIn('original.count(needle) != 1', self.script)
        self.assertIn("payload = original.replace(needle, replacement, 1)",
                      self.script)
        self.assertNotIn('json.dumps(state, sort_keys=True', self.script)

    def test_source_head_uses_parent_validation_and_build_provenance(self):
        self.assertIn('--validated-source <40-hex-sha>', self.script)
        self.assertIn('SWAPZ_BUILD_SOURCE_SHA', self.script)
        self.assertIn('SWAPZ_BUILD_SOURCE_CLEAN 1', self.script)
        self.assertNotIn('git rev-parse', self.script)
        self.assertNotRegex(self.script, r"(?m)^\s*git\s")
        self.assertNotIn("$(git ", self.script)



    def test_partial_owned_setup_cleanup_is_nounset_safe(self):
        initialization = self.script[
            self.script.index("OWN_NULL=0"):
            self.script.index('[[ ! -e "$TEST_BASE"', self.script.index("OWN_NULL=0"))]
        for variable in (
                "INDEX", "DEVNO", "NULL_MAJOR", "LOWER_NODE_DEVNO",
                "PART_NAME", "PARTITION_NODE_DEVNO"):
            with self.subTest(variable=variable):
                self.assertRegex(initialization, rf"(?m)^{variable}=$")

        def shell_function(name):
            begin = self.script.index(name + "() {")
            end = self.script.index("\n}", begin) + 2
            return self.script[begin:end]

        helpers = "\n".join(shell_function(name) for name in (
            "owned_nullblk_config_identity_unchanged",
            "owned_nullblk_live_identity_unchanged",
        ))
        cleanup = shell_function("cleanup")

        with TemporaryDirectory(
                prefix="swapz-primary-partial-cleanup-") as directory:
            fixture = Path(directory)
            configfs = fixture / "configfs"
            configfs.mkdir()
            name = "nullb-swapz-" + "f" * 16
            config = configfs / name
            config.mkdir()
            for attribute, value in (
                    ("index", "7\n"),
                    ("memory_backed", "1\n"),
                    ("size", "256\n"),
                    ("blocksize", "4096\n"),
                    ("power", "1\n")):
                (config / attribute).write_text(value, encoding="ascii")
            config_identity = config.stat()
            power_identity = (config / "power").stat()
            action_log = fixture / "actions"

            fixture_cleanup = cleanup.replace(
                "/sys/module/dm_swapz", str(fixture / "absent-module"))
            settings = {
                "CONFIGFS": configfs,
                "CONFIGNAME": name,
                "CONFIG": config,
                "CONFIG_IDENTITY": (
                    f"{config_identity.st_dev}:"
                    f"{config_identity.st_ino}:"
                    f"{config_identity.st_uid}"
                ),
                "CONFIG_POWER_IDENTITY": (
                    f"{power_identity.st_dev}:"
                    f"{power_identity.st_ino}:"
                    f"{power_identity.st_uid}"
                ),
                "NULLBLK_SIZE_MIB": "256",
                "INDEX": "",
                "DISK": "",
                "DEVNO": "",
                "NULL_MAJOR": "",
                "LOWER": "",
                "LOWER_NODE_DEVNO": "",
                "PART_SYSFS": "",
                "PART_NAME": "",
                "PARTITION": "",
                "PARTUUID": "",
                "PART_DEVNO": "",
                "PARTITION_NODE_DEVNO": "",
                "DMNAME": "swapz-primary",
                "RUN_ID": "",
                "RECOVERY_BASE": fixture / "missing-recovery",
                "CONTROL": fixture / "missing-control",
                "SWAPS_ID_BEFORE": "unchanged",
                "OWN_NULL": "1",
                "QUARANTINE": "0",
                "UDEV_RULE_CREATED": "0",
                "UDEV_RULES_DIR_CREATED": "0",
                "TEST_BASE_CREATED": "0",
                "TEST_BASE": fixture / "private-evidence",
                "BY_PARTUUID": "",
                "ACTION_LOG": action_log,
            }
            setup = "\n".join(
                f"{key}={shlex.quote(str(value))}"
                for key, value in settings.items())
            fake_commands = r'''
note() { printf '%s\n' "$*"; }
mapper_absence_proven() { return 0; }
swapz_swap_inventory_identity() { printf 'unchanged\n'; }
rmdir() {
    printf 'rmdir\n' >> "$ACTION_LOG"
    command rmdir "$@"
}
'''
            program = (
                "set -u\n" + setup + "\n" + fake_commands + helpers +
                "\n" + fixture_cleanup +
                "\ntrap cleanup EXIT\nexit 73\n")
            result = subprocess.run(
                ["bash", "-c", program], cwd=ROOT,
                capture_output=True, text=True, timeout=10, check=False)

            self.assertEqual(result.returncode, 73,
                             result.stdout + result.stderr)
            self.assertNotIn("unbound variable", result.stderr)
            self.assertEqual(
                (config / "power").read_text(encoding="ascii"), "1\n")
            self.assertTrue(config.is_dir())
            self.assertFalse(action_log.exists())
            self.assertIn(
                "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE="
                "config_or_mapper_identity_uncertain", result.stdout)
            self.assertIn(
                "PRIMARY_NULLBLK_LIFECYCLE_EVIDENCE_RETAINED=private",
                result.stdout)
            self.assertNotIn(name, result.stdout + result.stderr)
            self.assertNotIn(str(fixture), result.stdout + result.stderr)

    def test_finalizer_revalidates_identity_before_every_mutation(self):
        cleanup = self.script[
            self.script.index("cleanup() {"):
            self.script.index("trap cleanup EXIT")]
        recovery = cleanup.index('if (( OWN_NULL && ! QUARANTINE )) &&')
        first_proof = cleanup.index('! owned_nullblk_live_identity_unchanged')
        power = cleanup.index("owned_nullblk_power_off_pinned")
        post_power_mapper_check = cleanup.index(
            'elif ! mapper_absence_proven', power)
        post_power_proof = cleanup.index(
            'elif ! owned_nullblk_post_power_identity_unchanged', power)
        removal = cleanup.index('elif ! rmdir -- "$CONFIG"')
        self.assertLess(first_proof, recovery)
        self.assertLess(recovery, power)
        self.assertLess(power, post_power_mapper_check)
        self.assertLess(post_power_mapper_check, post_power_proof)
        self.assertLess(post_power_proof, removal)
        self.assertIn('! owned_nullblk_mapper_identity_unchanged', cleanup)
        self.assertIn('! mapper_absence_proven', cleanup)
        self.assertNotIn('> "$CONFIG/power"', cleanup)
        self.assertIn('QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=config_identity_uncertain',
                      cleanup)
        self.assertIn('PRIMARY_NULLBLK_LIFECYCLE_EVIDENCE_RETAINED=private',
                      cleanup)
        self.assertNotIn('EVIDENCE_RETAINED=$TEST_BASE', cleanup)
        self.assertNotIn('RETAINED_PRIMARY_NULLBLK_UDEV_RULE=$UDEV_RULE',
                         cleanup)
        self.assertIn('(( original_rc == 0 )) && original_rc=1', cleanup)
        self.assertIn('exit "$original_rc"', cleanup)
        self.assertIn('CONFIG_IDENTITY="$(stat -c', self.script)
        power_capture = self.script.index(
            'CONFIG_POWER_IDENTITY="$(stat -Lc')
        first_config_write = self.script.index(
            'echo "$NULLBLK_SIZE_MIB" > "$CONFIG/size"', power_capture)
        self.assertLess(power_capture, first_config_write)
        self.assertIn(
            '"$observed_power_identity" == "$CONFIG_POWER_IDENTITY"',
            self.script)
        power_helper_start = self.script.index(
            "owned_nullblk_power_off_pinned() {")
        power_helper_end = self.script.index("\n}", power_helper_start)
        power_helper = self.script[power_helper_start:power_helper_end]
        self.assertIn("os.O_WRONLY", power_helper)
        self.assertIn("os.O_NOFOLLOW", power_helper)
        self.assertIn("os.O_NONBLOCK", power_helper)
        self.assertNotIn("os.O_CREAT", power_helper)
        self.assertIn("identity = os.fstat(fd)", power_helper)
        self.assertIn('os.write(fd, b"0\\n")', power_helper)
        self.assertIn("pending_exception = sys.exc_info()[0]", power_helper)
        self.assertLess(
            power_helper.index("pending_exception = sys.exc_info()[0]"),
            power_helper.index("os.close(fd)"),
        )

    def test_rootless_pinned_power_refuses_unobservable_path_without_blocking(self):
        begin = self.script.index("owned_nullblk_power_off_pinned() {")
        end = self.script.index("\n}", begin) + 2
        helper = self.script[begin:end]

        with TemporaryDirectory(
                prefix="swapz-primary-pinned-power-") as directory:
            fixture = Path(directory)
            config = fixture / ("nullb-swapz-" + "e" * 16)
            config.mkdir()
            power = config / "power"
            power.write_text("1\n", encoding="ascii")
            identity = power.stat()
            expected_identity = (
                f"{identity.st_dev}:{identity.st_ino}:{identity.st_uid}"
            )

            def run_helper():
                program = (
                    f"CONFIG={shlex.quote(str(config))}\n"
                    f"CONFIG_POWER_IDENTITY={shlex.quote(expected_identity)}\n"
                    + helper + "\nowned_nullblk_power_off_pinned\n"
                )
                return subprocess.run(
                    ["bash", "-c", program], cwd=ROOT,
                    capture_output=True, text=True, timeout=5, check=False)

            exact = run_helper()
            self.assertEqual(exact.returncode, 0, exact.stderr)
            self.assertEqual(power.read_text(encoding="ascii"), "0\n")
            self.assertEqual(exact.stdout, "")
            self.assertEqual(exact.stderr, "")

            power.unlink()
            os.mkfifo(power, 0o600)
            fifo = run_helper()
            self.assertEqual(fifo.returncode, 1, fifo.stderr)
            self.assertTrue(power.is_fifo())
            self.assertEqual(fifo.stdout, "")
            self.assertEqual(fifo.stderr, "")

            power.unlink()
            missing = run_helper()
            self.assertEqual(missing.returncode, 1, missing.stderr)
            self.assertFalse(power.exists())
            self.assertEqual(missing.stdout, "")
            self.assertEqual(missing.stderr, "")

    def test_rootless_postproof_replacement_cannot_redirect_power_write(self):
        def shell_function(name):
            begin = self.script.index(name + "() {")
            end = self.script.index("\n}", begin) + 2
            return self.script[begin:end]

        helpers = "\n".join(shell_function(name) for name in (
            "owned_nullblk_config_identity_unchanged",
            "owned_nullblk_live_identity_unchanged",
            "owned_nullblk_mapper_identity_unchanged",
            "owned_nullblk_power_off_pinned",
            "owned_nullblk_post_power_identity_unchanged",
        ))
        cleanup = shell_function("cleanup")
        block_marker = (
            '\tif (( OWN_NULL )) && (( ! QUARANTINE )); then\n'
            '\t\tlocal power_off_status=0'
        )
        current_start = cleanup.index(block_marker)
        current_end = cleanup.index(
            '\n\tif (( OWN_NULL )) && (( ! QUARANTINE )); then\n'
            '\t\tudevadm settle',
            current_start,
        )
        current_power_step = cleanup[current_start:current_end]

        # This is the previous agent's final power/removal block. The fixture
        # switches the configfs pathname only after all pre-power proof calls.
        previous_agent_power_step = r'''
if (( OWN_NULL )) && (( ! QUARANTINE )); then
    if ! owned_nullblk_live_identity_unchanged ||
       ! owned_nullblk_mapper_identity_unchanged ||
       ! mapper_absence_proven || [[ -d "$MODULE_PATH" ]]; then
        QUARANTINE=1
        note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=config_identity_uncertain"
    elif ! printf '0\n' 2>/dev/null > "$CONFIG/power"; then
        QUARANTINE=1
        note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=nullblk_cleanup_failed"
    elif ! owned_nullblk_post_power_identity_unchanged ||
         ! mapper_absence_proven || [[ -d "$MODULE_PATH" ]]; then
        QUARANTINE=1
        note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=config_identity_uncertain"
    elif ! rmdir -- "$CONFIG" 2>/dev/null; then
        QUARANTINE=1
        note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=nullblk_cleanup_failed"
    fi
fi
'''

        def run_step(step):
            with TemporaryDirectory(
                    prefix="swapz-primary-postproof-replacement-") as directory:
                fixture = Path(directory)
                configfs = fixture / "configfs"
                configfs.mkdir()
                name = "nullb-swapz-" + "c" * 16
                config = configfs / name
                config.mkdir()
                attributes = {
                    "index": "7\n",
                    "memory_backed": "1\n",
                    "size": "256\n",
                    "blocksize": "4096\n",
                    "power": "1\n",
                }
                for attribute, value in attributes.items():
                    (config / attribute).write_text(value, encoding="ascii")
                config_identity = config.stat()
                power_identity = (config / "power").stat()

                sysblock = fixture / "sys/block"
                disk = sysblock / "nullb7"
                partition = disk / "nullb7p1"
                partition.mkdir(parents=True)
                (disk / "dev").write_text("240:7\n", encoding="ascii")
                (partition / "dev").write_text("240:8\n", encoding="ascii")
                sysdev = fixture / "sys/dev/block"
                sysdev.mkdir(parents=True)
                (sysdev / "240:8").symlink_to(
                    partition, target_is_directory=True)
                devices = fixture / "devices"
                devices.mkdir()
                (devices / "nullb7").write_text("240:7\n", encoding="ascii")
                (devices / "nullb7p1").write_text(
                    "240:8\n", encoding="ascii")
                action_log = fixture / "actions"
                module_path = fixture / "absent-module"

                fixture_helpers = helpers
                for before, after in (
                    ("/sys/dev/block", str(sysdev)),
                    ("/sys/block", str(sysblock)),
                    ('"/dev/$DISK"', '"$FAKE_DEV/$DISK"'),
                    ('"/dev/$PART_NAME"', '"$FAKE_DEV/$PART_NAME"'),
                ):
                    fixture_helpers = fixture_helpers.replace(before, after)
                fixture_step = step.replace(
                    "/sys/module/dm_swapz", str(module_path))

                settings = {
                    "CONFIGFS": configfs,
                    "CONFIGNAME": name,
                    "CONFIG": config,
                    "CONFIG_IDENTITY": (
                        f"{config_identity.st_dev}:"
                        f"{config_identity.st_ino}:"
                        f"{config_identity.st_uid}"
                    ),
                    "CONFIG_POWER_IDENTITY": (
                        f"{power_identity.st_dev}:"
                        f"{power_identity.st_ino}:"
                        f"{power_identity.st_uid}"
                    ),
                    "NULLBLK_SIZE_MIB": "256",
                    "INDEX": "7",
                    "DISK": "nullb7",
                    "PART_NAME": "nullb7p1",
                    "PART_SYSFS": partition,
                    "PARTITION": devices / "nullb7p1",
                    "PART_DEVNO": "240:8",
                    "PARTITION_NODE_DEVNO": "240:8",
                    "LOWER": devices / "nullb7",
                    "DEVNO": "240:7",
                    "LOWER_NODE_DEVNO": "240:7",
                    "NULL_MAJOR": "240",
                    "FAKE_DEV": devices,
                    "DMNAME": "swapz-primary",
                    "RUN_ID": "d" * 32,
                    "RECOVERY_BASE": fixture / "private-evidence",
                    "OWN_NULL": "1",
                    "QUARANTINE": "0",
                    "MAPPER_ABSENCE_CALLS": "0",
                    "ACTION_LOG": action_log,
                    "MODULE_PATH": module_path,
                }
                setup = "\n".join(
                    f"{key}={shlex.quote(str(value))}"
                    for key, value in settings.items())
                fake_commands = r'''
note() { printf '%s\n' "$*"; }
swapz_resolve_owned_disk() {
    [[ "$1" == "$CONFIGNAME" && "$2" == "$INDEX" &&
       -f "$3/$DISK/dev" ]] || return 1
    printf '%s\n' "$DISK"
}
block_node_devno() { cat -- "$1"; }
blockdev() {
    [[ "$1" == --getsize64 && "$2" == "$LOWER" ]] || return 1
    printf '268435456\n'
}
dmsetup() { return 1; }
mapper_absence_proven() {
    MAPPER_ABSENCE_CALLS=$((MAPPER_ABSENCE_CALLS + 1))
    if [[ "$MAPPER_ABSENCE_CALLS" == 2 ]]; then
        mv -- "$CONFIG" "$CONFIGFS/retained-original" || return 1
        mkdir -- "$CONFIG" || return 1
        printf '7\n' > "$CONFIG/index"
        printf '1\n' > "$CONFIG/memory_backed"
        printf '256\n' > "$CONFIG/size"
        printf '4096\n' > "$CONFIG/blocksize"
        printf '1\n' > "$CONFIG/power"
    fi
    return 0
}
rmdir() {
    printf 'rmdir\n' >> "$ACTION_LOG"
    rm -rf -- "$CONFIG"
}
'''
                program = (
                    "set +e\n" + setup + "\n" + fake_commands +
                    fixture_helpers + "\nrun_power_step() {\n" +
                    fixture_step + "\n}\nrun_power_step\n")
                result = subprocess.run(
                    ["bash", "-c", program], cwd=ROOT,
                    capture_output=True, text=True, timeout=10, check=False)
                self.assertEqual(result.returncode, 0,
                                 result.stdout + result.stderr)
                self.assertNotIn(name, result.stdout + result.stderr)
                self.assertNotIn(str(fixture),
                                 result.stdout + result.stderr)
                self.assertTrue(config.is_dir())
                return (
                    (config / "power").read_text(encoding="ascii").strip(),
                    action_log.read_text(encoding="ascii").splitlines()
                    if action_log.exists() else [],
                    result.stdout,
                )

        previous_power, previous_actions, _ = run_step(
            previous_agent_power_step)
        self.assertEqual(previous_power, "0")
        self.assertEqual(previous_actions, [])

        current_power, current_actions, current_output = run_step(
            current_power_step)
        self.assertEqual(current_power, "1")
        self.assertEqual(current_actions, [])
        self.assertIn(
            "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE="
            "config_identity_uncertain", current_output)

    def test_rootless_configfs_replacement_and_failure_preserve_ownership(self):
        # Only temporary regular files stand in for configfs and block nodes.
        # Fake power and rmdir operations never access actual host devices.
        def shell_function(name):
            begin = self.script.index(name + "() {")
            end = self.script.index("\n}", begin) + 2
            return self.script[begin:end]

        helpers = "\n".join(shell_function(name) for name in (
            "owned_nullblk_config_identity_unchanged",
            "owned_nullblk_live_identity_unchanged",
            "owned_nullblk_mapper_identity_unchanged",
            "owned_nullblk_power_off_pinned",
            "owned_nullblk_post_power_identity_unchanged",
        ))
        cleanup = shell_function("cleanup")

        # This is the original pathname-only guard, reproduced verbatim to
        # establish its unsafe same-name/different-inode behavior.
        previous_guard = r'''
if (( OWN_NULL )) && (( ! QUARANTINE )); then
    if [[ ! "$CONFIGNAME" =~ ^nullb-swapz-[a-f0-9]{16}$ ||
          "$CONFIG" != "$CONFIGFS/$CONFIGNAME" ||
          ! -d "$CONFIG" || -L "$CONFIG" ]]; then
        QUARANTINE=1
        note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=config_identity_uncertain"
    else
        echo 0 > "$CONFIG/power" 2>/dev/null || QUARANTINE=1
        rmdir -- "$CONFIG" 2>/dev/null || QUARANTINE=1
        (( QUARANTINE )) &&
            note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=nullblk_cleanup_failed"
    fi
fi
exit 0
'''

        def run_fixture(scenario, original_status=0, legacy=False):
            with TemporaryDirectory(prefix="swapz-owned-nullblk-guard-") as directory:
                fixture = Path(directory)
                configfs = fixture / "configfs"
                configfs.mkdir()
                name = "nullb-swapz-" + "a" * 16
                config = configfs / name
                config.mkdir()
                attributes = {
                    "index": "7\n",
                    "memory_backed": "1\n",
                    "size": "256\n",
                    "blocksize": "4096\n",
                    "power": "1\n",
                }
                for attribute, value in attributes.items():
                    (config / attribute).write_text(value, encoding="ascii")
                identity = config.stat()
                captured_identity = (
                    f"{identity.st_dev}:{identity.st_ino}:{identity.st_uid}"
                )
                power_identity = (config / "power").stat()
                captured_power_identity = (
                    f"{power_identity.st_dev}:"
                    f"{power_identity.st_ino}:"
                    f"{power_identity.st_uid}"
                )
                sysblock = fixture / "sys/block"
                disk = sysblock / "nullb7"
                partition = disk / "nullb7p1"
                partition.mkdir(parents=True)
                (disk / "dev").write_text("240:7\n", encoding="ascii")
                (partition / "dev").write_text("240:8\n", encoding="ascii")
                sysdev = fixture / "sys/dev/block"
                sysdev.mkdir(parents=True)
                (sysdev / "240:8").symlink_to(partition, target_is_directory=True)
                devices = fixture / "devices"
                devices.mkdir()
                (devices / "nullb7").write_text("240:7\n", encoding="ascii")
                (devices / "nullb7p1").write_text("240:8\n", encoding="ascii")
                actions = fixture / "actions"
                control = fixture / "control"
                control.write_text(
                    '#!/bin/sh\nprintf "recover\\n" >> "$ACTION_LOG"\n',
                    encoding="ascii")
                control.chmod(0o700)

                if scenario == "replacement":
                    config.rename(configfs / "retained-original")
                    config.mkdir()
                    for attribute, value in attributes.items():
                        (config / attribute).write_text(value, encoding="ascii")
                    self.assertNotEqual(config.stat().st_ino, identity.st_ino)
                elif scenario == "missing_index":
                    (config / "index").unlink()
                elif scenario == "wrong_index":
                    (config / "index").write_text("8\n", encoding="ascii")
                elif scenario == "wrong_sysfs_devno":
                    (disk / "dev").write_text("240:9\n", encoding="ascii")
                elif scenario == "wrong_block_devno":
                    (devices / "nullb7").write_text("240:9\n", encoding="ascii")
                elif scenario == "wrong_partition_devno":
                    (partition / "dev").write_text("240:9\n", encoding="ascii")
                elif scenario == "wrong_size":
                    (config / "size").write_text("128\n", encoding="ascii")
                elif scenario == "foreign_memory":
                    (config / "memory_backed").write_text("0\n", encoding="ascii")

                replacements = (
                    ("/sys/dev/block", str(sysdev)),
                    ("/sys/block", str(sysblock)),
                    ('"/dev/$DISK"', '"$FAKE_DEV/$DISK"'),
                    ('"/dev/$PART_NAME"', '"$FAKE_DEV/$PART_NAME"'),
                )
                fixture_helpers = helpers
                for before, after in replacements:
                    fixture_helpers = fixture_helpers.replace(before, after)
                fixture_cleanup = cleanup.replace(
                    "/sys/module/dm_swapz", str(fixture / "absent-module"))
                fixture_cleanup = fixture_cleanup.replace("/sys/block", str(sysblock))

                settings = {
                    "CONFIGFS": configfs,
                    "CONFIGNAME": name,
                    "CONFIG": config,
                    "CONFIG_IDENTITY": captured_identity,
                    "CONFIG_POWER_IDENTITY": captured_power_identity,
                    "NULLBLK_SIZE_MIB": "256",
                    "INDEX": "7",
                    "DISK": "nullb7",
                    "PART_NAME": "nullb7p1",
                    "PART_SYSFS": partition,
                    "PARTITION": devices / "nullb7p1",
                    "PART_DEVNO": "240:8",
                    "PARTITION_NODE_DEVNO": "240:8",
                    "LOWER": devices / "nullb7",
                    "DEVNO": "240:7",
                    "LOWER_NODE_DEVNO": "240:7",
                    "NULL_MAJOR": "240",
                    "FAKE_DEV": devices,
                    "DMNAME": "swapz-primary",
                    "RUN_ID": "b" * 32,
                    "RECOVERY_BASE": fixture / "private-evidence",
                    "CONTROL": control,
                    "SWAPS_ID_BEFORE": "unchanged",
                    "ACTION_LOG": actions,
                    "OWN_NULL": "1",
                    "QUARANTINE": "0",
                    "UDEV_RULE_CREATED": "0",
                    "UDEV_RULES_DIR_CREATED": "0",
                    "TEST_BASE_CREATED": "0",
                    "TEST_BASE": fixture / "private-evidence",
                    "BY_PARTUUID": "",
                    "RMDIR_FAIL": "1" if scenario == "rmdir_failure" else "0",
                    "MAPPER_FOREIGN": "1" if scenario == "foreign_mapper" else "0",
                }
                setup = "\n".join(
                    f"{key}={shlex.quote(str(value))}"
                    for key, value in settings.items())
                fake_commands = r'''
note() { printf '%s\n' "$*"; }
state_stage() { return 0; }
swapz_swap_inventory_identity() { printf 'unchanged\n'; }
mapper_absence_proven() { return 0; }
findmnt() { return 1; }
udevadm() { return 0; }
swapz_resolve_owned_disk() {
    [[ "$1" == "$CONFIGNAME" && "$2" == "$INDEX" &&
       -f "$3/$DISK/dev" ]] || return 1
    printf '%s\n' "$DISK"
}
block_node_devno() { cat -- "$1"; }
blockdev() {
    [[ "$1" == --getsize64 && "$2" == "$LOWER" ]] || return 1
    printf '268435456\n'
}
dmsetup() {
    if [[ "$MAPPER_FOREIGN" == 1 ]]; then
        [[ "$1" == info ]] || return 1
        if [[ "$2" == "$DMNAME" ]]; then
            return 0
        fi
        printf 'FOREIGN\n'
        return 0
    fi
    return 1
}
rmdir() {
    printf 'rmdir\n' >> "$ACTION_LOG"
    [[ "$RMDIR_FAIL" != 1 ]] || return 1
    rm -rf -- "$CONFIG"
}
'''
                if legacy:
                    program = setup + "\n" + fake_commands + previous_guard
                else:
                    program = (
                        setup + "\n" + fake_commands + fixture_helpers +
                        "\n" + fixture_cleanup +
                        "\ntrap cleanup EXIT\nexit " + str(original_status) + "\n")
                result = subprocess.run(
                    ["bash", "-c", program], cwd=ROOT,
                    capture_output=True, text=True, timeout=10, check=False)
                changed_power = ((config / "power").read_text(
                    encoding="ascii").strip() if config.exists() else None)
                action_lines = (
                    actions.read_text(encoding="ascii").splitlines()
                    if actions.exists() else [])
                self.assertNotIn(name, result.stdout + result.stderr)
                self.assertNotIn(str(fixture), result.stdout + result.stderr)
                return result, changed_power, config.exists(), action_lines

        before, power, exists, actions = run_fixture("replacement", legacy=True)
        self.assertEqual(before.returncode, 0, before.stderr)
        self.assertIsNone(power)
        self.assertFalse(exists)
        self.assertIn("rmdir", actions)

        success, power, exists, actions = run_fixture("owned")
        self.assertEqual(success.returncode, 0, success.stdout + success.stderr)
        self.assertIsNone(power)
        self.assertFalse(exists)
        self.assertEqual(actions, ["rmdir"])

        for scenario in ("replacement", "missing_index", "wrong_index",
                         "wrong_sysfs_devno", "wrong_block_devno",
                         "wrong_partition_devno", "wrong_size",
                         "foreign_memory", "foreign_mapper"):
            with self.subTest(scenario=scenario):
                result, power, exists, actions = run_fixture(scenario)
                self.assertEqual(result.returncode, 1,
                                 result.stdout + result.stderr)
                self.assertEqual(power, "1")
                self.assertTrue(exists)
                self.assertEqual(actions, [])
                self.assertIn(
                    "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE="
                    "config_or_mapper_identity_uncertain", result.stdout)

        original_failure, power, exists, actions = run_fixture(
            "replacement", original_status=73)
        self.assertEqual(original_failure.returncode, 73)
        self.assertEqual(power, "1")
        self.assertTrue(exists)
        self.assertEqual(actions, [])

        cleanup_failure, power, exists, actions = run_fixture(
            "rmdir_failure", original_status=73)
        self.assertEqual(cleanup_failure.returncode, 73)
        self.assertEqual(power, "0")
        self.assertTrue(exists)
        self.assertEqual(actions, ["rmdir"])
        self.assertIn("nullblk_cleanup_failed", cleanup_failure.stdout)

    def test_cleanup_quarantines_unfinished_durable_state(self):
        self.assertIn("unfinished_or_ambiguous_durable_state", self.script)
        self.assertIn("unresolved_owner_record", self.script)
        self.assertIn("actual_bytes == canonical_bytes", self.script)
        self.assertIn("payload != canonical_bytes", self.script)

    def test_cleanup_state_verifier_rejects_fifo_without_blocking(self):
        cleanup = self.script[
            self.script.index("cleanup() {"):
            self.script.index("trap cleanup EXIT")]
        marker = 'python3 - "$state_file" "$RUN_ID" <<\'PY\'\n'
        start = cleanup.index(marker) + len(marker)
        end = cleanup.index("\nPY\n", start)
        verifier = cleanup[start:end] + "\n"

        self.assertIn("os.O_NOFOLLOW", verifier)
        self.assertIn("os.O_NONBLOCK", verifier)
        self.assertIn("named_identity = os.lstat(sys.argv[1])", verifier)
        self.assertIn("opened_identity = os.fstat(state_fd)", verifier)
        self.assertIn("after_identity = os.lstat(sys.argv[1])", verifier)
        self.assertIn("stat.S_ISREG(identity.st_mode)", verifier)
        self.assertIn("stat.S_IMODE(identity.st_mode) == 0o600", verifier)
        self.assertIn("identity.st_nlink == 1", verifier)
        self.assertIn("0 < identity.st_size <= 4096", verifier)
        self.assertIn(
            "opened_identity.st_ino != named_identity.st_ino", verifier)
        self.assertIn(
            "after_identity.st_ino != opened_identity.st_ino", verifier)
        self.assertLess(verifier.index("named_identity = os.lstat"),
                        verifier.index("state_fd = os.open"))
        self.assertLess(verifier.index("opened_identity = os.fstat(state_fd)"),
                        verifier.index("json.loads(actual_bytes.decode"))
        self.assertLess(verifier.index("after_identity = os.lstat"),
                        verifier.index("json.loads(actual_bytes.decode"))
        self.assertNotIn('with open(sys.argv[1]', verifier)

        with TemporaryDirectory(prefix="swapz-primary-state-fifo-") as directory:
            fifo = Path(directory) / "primary-state.json"
            os.mkfifo(fifo, 0o600)
            result = subprocess.run(
                ["python3", "-", str(fifo), "a" * 32],
                input=verifier,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            self.assertEqual(result.returncode, 1,
                             result.stdout + result.stderr)

    def test_interruption_evidence_is_durable_and_unique(self):
        self.assertIn("capture_interruption_evidence() {", self.script)
        self.assertIn('capture_interruption_evidence "$phase"', self.script)
        self.assertIn('snapshot_name = f"{run_id}-{phase}-{name}"', self.script)
        self.assertIn("os.fsync(snapshot_fd)", self.script)
        self.assertIn("os.fsync(evidence_fd)", self.script)
        self.assertIn('QUARANTINE=1\n\t\tfail "$phase could not preserve', self.script)

    def test_missing_swap_path_cannot_be_counted_as_absent(self):
        self.assertIn('[[ -e "$swap_path" ]] || return 1', self.script)

    def test_dmsetup_failure_is_not_mapper_absence_evidence(self):
        oracle_start = self.script.index("mapper_absence_proven() {")
        oracle_end = self.script.index("\n}", oracle_start)
        oracle = self.script[oracle_start:oracle_end]
        self.assertIn('dmsetup info "$DMNAME"', oracle)
        self.assertIn('for mapper_sysfs in /sys/class/block/dm-*; do', oracle)
        self.assertIn('[[ -r "$mapper_sysfs/dm/name" ]] || return 1', oracle)
        self.assertIn('[[ "$observed_name" != "$DMNAME" ]] || return 1',
                      oracle)
        self.assertIn('mapper_absence_proven || return 1', self.script)
        cleanup = self.script[self.script.index("cleanup() {"):]
        self.assertIn('if ! mapper_absence_proven ||', cleanup)
        self.assertNotIn(
            'if dmsetup info "$DMNAME" >/dev/null 2>&1 || '
            '[[ -d /sys/module/dm_swapz ]]', cleanup)

    def test_cleanup_preserves_noncanonical_and_orphaned_owner_records(self):
        cleanup = self.script[
            self.script.index("cleanup() {"):
            self.script.index("trap cleanup EXIT")]
        claim_check = cleanup.index(
            '! assert_owned_transaction_records 0 >/dev/null 2>&1')
        quarantine = cleanup.index(
            'QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE='
            'noncanonical_consumed_owner_record')
        deletion = cleanup.index('rm -rf --one-file-system -- "$TEST_BASE"')
        self.assertLess(claim_check, quarantine)
        self.assertLess(quarantine, deletion)
        for orphan in ("consumed-*.json", "primary-manifest-*.txt",
                       "primary-module-load-*.json"):
            self.assertIn(orphan, cleanup)

    def test_privileged_qualifier_does_not_touch_git_metadata(self):
        self.assertNotIn("git diff --quiet --exit-code", self.script)
        self.assertNotIn("git diff --cached --quiet --exit-code", self.script)
        self.assertIn(
            "Branch/source/cleanliness are proved by the unprivileged "
            "loaded-test parent", self.script)

    def test_fault_shim_is_warning_clean(self):
        subprocess.run(
            [
                "cc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
                "-fsyntax-only", str(SHIM),
            ],
            cwd=ROOT,
            check=True,
        )

    def test_fault_shim_executes_ten_injected_faults_plus_passthrough(self):
        # The harness provides fake syscall/open/fsync implementations: no
        # loaded kernel, swap device or privileged host action is touched.
        with TemporaryDirectory(prefix="swapz-primary-fault-") as directory:
            binary = Path(directory) / "fault-shim-test"
            subprocess.run([
                "cc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
                str(SHIM), str(SHIM_HARNESS),
                "-Wl,--wrap=syscall", "-Wl,--wrap=open", "-Wl,--wrap=fsync",
                "-o", str(binary),
            ], cwd=ROOT, check=True)
            for fault in (
                "passthrough",
                "swapon-eintr-applied",
                "swapon-eintr-noeffect",
                "swapon-eio-noeffect",
                "post-swapon-inventory-eio",
                "swapoff-eintr-applied",
                "swapoff-eintr-noeffect",
                "swapoff-eio-noeffect",
                "swapoff-ebusy-noeffect",
                "post-swapoff-inventory-eio",
                "state-dir-fsync",
            ):
                with self.subTest(fault=fault):
                    result = subprocess.run(
                        [str(binary), fault], cwd=ROOT,
                        capture_output=True, text=True, check=False,
                        timeout=15)
                    self.assertEqual(result.returncode, 0,
                                     result.stdout + result.stderr)
                    expected_marker = (
                        "" if fault == "passthrough" else
                        "SWAPZ_PRIMARY_TEST_FSYNC_DIRECTORY_HIT=2"
                        if fault == "state-dir-fsync" else
                        "SWAPZ_PRIMARY_TEST_FAULT_HIT=" + fault)
                    self.assertEqual(result.stderr.strip(), expected_marker)

    def test_fault_shim_forwards_real_kernel_boundaries(self):
        for syscall in ("SYS_swapon", "SYS_swapoff",
                        "SYS_finit_module", "SYS_delete_module"):
            self.assertIn(syscall, self.shim)
        self.assertGreaterEqual(self.shim.count("__real_syscall("), 5)
        self.assertIn('__real_open(path, flags', self.shim)
        self.assertIn("__real_fsync(fd)", self.shim)
        self.assertIn('!strcmp(path, "/proc/swaps")', self.shim)


if __name__ == "__main__":
    unittest.main(verbosity=2)
