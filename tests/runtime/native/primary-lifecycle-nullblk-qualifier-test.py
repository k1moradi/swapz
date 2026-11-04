#!/usr/bin/env python3
"""Rootless contract checks for the Agent 7 owned-null_blk qualifier."""

from pathlib import Path
from tempfile import TemporaryDirectory
import os
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
            self.primary.index("static int swapz_primary_prepare_metadata(void)"):
            self.primary.index("static int swapz_primary_unload_owned_module(", 
                               self.primary.index("static int swapz_primary_prepare_metadata(void)"))]
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
            self.primary.index("static int swapz_primary_prepare_metadata(void)"):
            self.primary.index("static int swapz_primary_unload_owned_module(",
                               self.primary.index("static int swapz_primary_prepare_metadata(void)"))]
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
            self.primary.index("static int swapz_primary_prepare_metadata(void)"):
            self.primary.index("static int swapz_primary_unload_owned_module(",
                               self.primary.index("static int swapz_primary_prepare_metadata(void)"))]
        failure_format = preparation[preparation.index("if (result < 0 && claimed)"):
                                     preparation.index("if (result < 0)\n\t\terrno = saved_errno;")]
        # Recovery claims can be retained, but their 32-hex IDs belong in
        # durable private metadata, not in public diagnostic records.
        self.assertIn("claim=retained target_unchanged=true", failure_format)
        self.assertIn("claim=none", failure_format)
        self.assertNotIn("run_id=%s", failure_format)
        self.assertNotIn("target=%s", failure_format)

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
        check(command_output(source_mismatch, permitted), True)
        check(command_output(retained_manifest, permitted), True)
        check(command_output(package_busy, busy), True)

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
