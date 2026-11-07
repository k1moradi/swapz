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
import errno
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
            'if sfdisk --lock --wipe always "$LOWER"', lower_node)
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
            'if sfdisk --lock --wipe always "$LOWER"')
        partition_settle = self.script.index(
            'udevadm settle --timeout=10 >/dev/null 2>&1 || owned_setup_failed "partition-udev-settle"',
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
            "repeated-target-physical-parent-identity",
            "repeated-target-recovery-parent-separation",
            "repeated-target-mounted-in-visible-namespace",
            "repeated-root-device-parent-identity",
        ):
            with self.subTest(phase=phase):
                index = prepare.index('failure_phase = "' + phase + '";')
                self.assertLess(index, owner_claim)
                gate = prepare[index:prepare.index("goto out;", index)]
                self.assertIn("errno = EPERM;", gate)

        for phase in (
            "repeated-root-parent-identity",
            "final-root-parent-identity-revalidation",
        ):
            with self.subTest(phase=phase):
                index = prepare.index('failure_phase = "' + phase + '";')
                self.assertLess(index, owner_claim)
                gate = prepare[index:prepare.index("goto out;", index)]
                self.assertIn("errno = ESTALE;", gate)

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

    def test_shared_root_exception_is_bound_at_prepare_and_last_write_boundary(self):
        prepare = self.primary[
            self.primary.index("static int swapz_primary_prepare_metadata("):
            self.primary.index("static int swapz_primary_unload_owned_module(",
                               self.primary.index("static int swapz_primary_prepare_metadata("))]
        start = self.primary[
            self.primary.index("static int swapz_primary_start_prepared("):
            self.primary.index("static int swapz_primary_state_recoverable(",
                               self.primary.index("static int swapz_primary_start_prepared("))]
        self.assertIn("target_parent == root_parent", prepare)
        self.assertGreaterEqual(
            prepare.count("swapz_primary_shared_root_scope_record_live("), 3)
        self.assertIn("target_parent == makedev(recovery_parent_major", prepare)
        self.assertIn("failure_expected = \"exact-host-root-target-parent-layout-record\"",
                      prepare)
        self.assertIn("failure_observed = \"missing-mismatched-or-unverifiable\"",
                      prepare)
        self.assertIn("repeated-shared-root-parent-authorization", prepare)
        self.assertIn("final-shared-root-parent-authorization", prepare)
        self.assertIn("target_parent == makedev(recovery_parent_major", start)
        self.assertGreaterEqual(
            start.count("swapz_primary_shared_root_scope_record_live("), 2)
        prewrite = start.index('failure_phase = "prewrite-shared-root-parent-authorization";')
        target_write = start.index("swapz_primary_write_header_checked_fd(")
        self.assertLess(prewrite, target_write)
        self.assertRegex(
            start, r"target_fd,\s*rechecked_root_scope_sha256")

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

    def test_lifecycle_recovery_state_failure_preserves_original_errno(self):
        helper_start = self.primary.index(
            "static int swapz_primary_require_recovery_preserving_errno(")
        helper_end = self.primary.index("\n}\n", helper_start) + 3
        helper = self.primary[helper_start:helper_end]

        with TemporaryDirectory(
                prefix="swapz-primary-recovery-errno-") as directory:
            fixture = Path(directory)
            source = fixture / "recovery-errno.c"
            binary = fixture / "recovery-errno"
            source.write_text(
                r"""#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/types.h>
#include <unistd.h>

static int injected_recovery_errno;
static int injected_recovery_after_write;
static const char *recovery_state_path;
static unsigned int recovery_write_attempts;

int swapz_primary_state_require_recovery_at(
    int recovery_fd, int lock_fd, const char *run_id, uid_t expected_owner)
{
    FILE *state_file;

    (void)recovery_fd;
    (void)lock_fd;
    (void)run_id;
    (void)expected_owner;
    ++recovery_write_attempts;
    if (injected_recovery_errno != 0 && !injected_recovery_after_write) {
        errno = injected_recovery_errno;
        return -1;
    }
    state_file = fopen(recovery_state_path, "wb");
    if (state_file == NULL)
        return -1;
    if (fputs("RECOVERY_REQUIRED\n", state_file) == EOF ||
        fflush(state_file) != 0 || fsync(fileno(state_file)) != 0) {
        const int write_errno = errno;
        (void)fclose(state_file);
        errno = write_errno;
        return -1;
    }
    if (fclose(state_file) != 0)
        return -1;
    if (injected_recovery_errno != 0) {
        errno = injected_recovery_errno;
        return -1;
    }
    return 0;
}

""" + helper + r"""
int main(int argc, char **argv)
{
    int original_errno;
    int preserved_errno;

    if (argc != 6)
        return 64;
    original_errno = atoi(argv[2]);
    injected_recovery_errno = atoi(argv[3]);
    injected_recovery_after_write = atoi(argv[4]);
    recovery_state_path = argv[5];
    errno = 0;
    preserved_errno = swapz_primary_require_recovery_preserving_errno(
        7, 8, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 0,
        argv[1], original_errno);
    printf("preserved=%d errno=%d attempts=%u\n", preserved_errno,
           errno, recovery_write_attempts);
    return 0;
}
""",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    "cc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra",
                    "-Werror", "-Wpedantic", str(source), "-o", str(binary),
                ],
                cwd=ROOT,
                check=True,
            )
            cases = (
                ("START", "STARTING", errno.EIO, errno.ENOSPC),
                ("STOP", "STOPPING", errno.EBUSY, errno.EIO),
                ("RECOVER", "RECOVERING", errno.ESTALE, errno.EROFS),
            )
            for operation, initial_stage, original_errno, recovery_errno in cases:
                state_path = fixture / f"{operation.lower()}-state"
                scenarios = (
                    ("pre-write-failure", recovery_errno, 0,
                     initial_stage, True),
                    ("post-write-failure", recovery_errno, 1,
                     "RECOVERY_REQUIRED", True),
                    ("success", 0, 0, "RECOVERY_REQUIRED", False),
                )
                for (scenario, injected_errno, failure_after_write,
                     expected_stage, expect_diagnostic) in scenarios:
                    with self.subTest(operation=operation, scenario=scenario):
                        # A failed replace can occur either before the new
                        # bytes are visible or after replacement but before
                        # durable directory state is established.
                        state_path.write_text(
                            f"{initial_stage}\n", encoding="ascii")
                        result = subprocess.run(
                            [
                                str(binary), operation, str(original_errno),
                                str(injected_errno), str(failure_after_write),
                                str(state_path),
                            ],
                            cwd=ROOT,
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=5,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(
                            result.stdout,
                            f"preserved={original_errno} "
                            f"errno={original_errno} attempts=1\n",
                        )
                        self.assertEqual(
                            state_path.read_text(encoding="ascii"),
                            expected_stage + "\n",
                        )
                        self.assertLessEqual(state_path.stat().st_size, 4096)
                        self.assertNotIn(
                            str(state_path), result.stdout + result.stderr)
                        self.assertNotIn(
                            "PRIMARY_START=ACTIVE",
                            result.stdout + result.stderr)
                        self.assertNotIn(
                            "PRIMARY_STOP=COMPLETE",
                            result.stdout + result.stderr)
                        self.assertNotIn(
                            "PRIMARY_RECOVER=COMPLETE",
                            result.stdout + result.stderr)
                        self.assertNotRegex(result.stderr, r"\b[0-9a-f]{32}\b")
                        if not expect_diagnostic:
                            self.assertEqual(result.stderr, "")
                            continue
                        self.assertIn(
                            f"PRIMARY_{operation}=RECOVERY_STATE_FAILED "
                            "phase=recovery-state-persist "
                            "check=durable-recovery-state "
                            "expected_proof=RECOVERY_REQUIRED-persisted "
                            "observed_proof=write-failed "
                            f"original_errno={original_errno} "
                            f"recovery_errno={recovery_errno} "
                            "retained_resource=transaction-evidence "
                            "disposition=BLOCKED "
                            "safe_next_action=read-only-inspect-recovery-state",
                            result.stderr,
                        )
                        self.assertIn(
                            "persistence_boundary=state-file-fsync-close-rename-directory-fsync "
                            "durable=UNCERTAIN mapper=UNCERTAIN swap=UNCERTAIN",
                            result.stderr,
                        )



            # Mutation negative control: the executable harness must notice
            # a helper that wrongly substitutes a later errno for the first.
            original_source = source.read_text(encoding="utf-8")
            self.assertEqual(original_source.count(
                "errno = primary_errno;\n\treturn primary_errno;"), 1)
            mutated_source = fixture / "recovery-errno-mutant.c"
            mutated_binary = fixture / "recovery-errno-mutant"
            mutated_source.write_text(
                original_source.replace(
                    "errno = primary_errno;\n\treturn primary_errno;",
                    "errno = EINVAL;\n\treturn EINVAL;", 1),
                encoding="utf-8",
            )
            subprocess.run(
                [
                    "cc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra",
                    "-Werror", "-Wpedantic", str(mutated_source),
                    "-o", str(mutated_binary),
                ],
                cwd=ROOT,
                check=True,
            )
            mutant_state = fixture / "mutant-state"
            mutant_state.write_text("STARTING\n", encoding="ascii")
            mutant = subprocess.run(
                [
                    str(mutated_binary), "START", str(errno.EIO),
                    str(errno.ENOSPC), "0", str(mutant_state),
                ],
                cwd=ROOT, capture_output=True, text=True,
                check=False, timeout=5,
            )
            self.assertEqual(mutant.returncode, 0, mutant.stderr)
            self.assertNotEqual(
                mutant.stdout,
                f"preserved={errno.EIO} errno={errno.EIO} attempts=1\n",
            )

    def test_state_replace_observes_rename_before_directory_fsync(self):
        """Inject failures into the real source-extracted record writer."""
        start = self.primary.index("int swapz_primary_replace_record_at(")
        end = self.primary.index(
            "\nint swapz_primary_claim_partition_owner_at(", start)
        writer = self.primary[start:end]
        prefix = r"""#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define SWAPZ_PRIMARY_STATE_RECORD_MAX 4096U
static int failure_mode;

static int swapz_primary_valid_run_id(const char *value)
{
    return value != NULL && strlen(value) == 32U;
}

static int injected_fsync(int fd)
{
    struct stat info;

    if (fstat(fd, &info) < 0)
        return -1;
    if (((failure_mode == 1 || failure_mode == 6) &&
         S_ISREG(info.st_mode)) ||
        (failure_mode == 2 && S_ISDIR(info.st_mode))) {
        errno = failure_mode == 2 ? EIO : ENOSPC;
        return -1;
    }
    if ((failure_mode == 7 && S_ISREG(info.st_mode)) ||
        (failure_mode == 8 && S_ISDIR(info.st_mode))) {
        if (fsync(fd) < 0)
            return -1;
        errno = EIO;
        return -1;
    }
    return fsync(fd);
}
/* Simulate a late close error after the descriptor has been released. */
static int injected_close(int fd)
{
    struct stat info;
    int is_temporary_file = fstat(fd, &info) == 0 &&
                            S_ISREG(info.st_mode);
    int close_result = close(fd);

    if (failure_mode == 3 && is_temporary_file && close_result == 0) {
        errno = EIO;
        return -1;
    }
    return close_result;
}
static int injected_renameat(int source_fd, const char *source_name,
                             int destination_fd, const char *destination_name)
{
    if (failure_mode == 4) {
        errno = EXDEV;
        return -1;
    }
    if (renameat(source_fd, source_name, destination_fd,
                 destination_name) < 0)
        return -1;
    /* The rename side effect may be visible despite a reported error. */
    if (failure_mode == 5) {
        errno = EIO;
        return -1;
    }
    return 0;
}
static int injected_unlinkat(int directory_fd, const char *name, int flags)
{
    if (failure_mode == 6) {
        errno = EACCES;
        return -1;
    }
    return unlinkat(directory_fd, name, flags);
}
#define fsync injected_fsync
#define close injected_close
#define renameat injected_renameat
#define unlinkat injected_unlinkat
"""
        suffix = r"""
int main(int argc, char **argv)
{
    int directory_fd;
    int result;
    int operation_errno;

    if (argc != 3)
        return 64;
    failure_mode = atoi(argv[2]);
    directory_fd = open(argv[1], O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (directory_fd < 0)
        return 65;
    errno = 0;
    result = swapz_primary_replace_record_at(
        directory_fd, "primary-state.json",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "replacement\n", getuid());
    operation_errno = errno;
    if (close(directory_fd) < 0)
        return 66;
    printf("result=%d errno=%d\n", result, operation_errno);
    return 0;
}
"""
        with TemporaryDirectory(prefix="swapz-primary-record-boundary-") as temp:
            fixture = Path(temp)
            source = fixture / "record-boundary.c"
            binary = fixture / "record-boundary"
            source.write_text(prefix + writer + suffix, encoding="utf-8")
            compiler = [
                "cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                "-Wpedantic", str(source), "-o", str(binary),
            ]
            subprocess.run(compiler, check=True, cwd=ROOT)
            for scenario, mode, expected_bytes, expected_result, temp_left in (
                ("before-rename", 1, "original\n",
                 f"result=-1 errno={errno.ENOSPC}\n", False),
                ("after-rename-before-directory-fsync", 2, "replacement\n",
                 f"result=-1 errno={errno.EIO}\n", False),
                ("close-failed-after-release", 3, "original\n",
                 f"result=-1 errno={errno.EIO}\n", False),
                ("rename-before-mutation", 4, "original\n",
                 f"result=-1 errno={errno.EXDEV}\n", False),
                ("rename-after-mutation", 5, "replacement\n",
                 f"result=-1 errno={errno.EIO}\n", False),
                ("cleanup-error-retains-first-errno", 6, "original\n",
                 f"result=-1 errno={errno.ENOSPC}\n", True),
                ("file-fsync-after-effect", 7, "original\n",
                 f"result=-1 errno={errno.EIO}\n", False),
                ("directory-fsync-after-effect", 8, "replacement\n",
                 f"result=-1 errno={errno.EIO}\n", False),
                ("durable-replacement", 0, "replacement\n", None, False),
            ):
                with self.subTest(scenario=scenario):
                    state = fixture / "primary-state.json"
                    temporary = fixture / (
                        ".primary-state.json." + "a" * 32 + ".tmp")
                    temporary.unlink(missing_ok=True)
                    state.write_text("original\n", encoding="ascii")
                    state.chmod(0o600)
                    result = subprocess.run(
                        [str(binary), str(fixture), str(mode)],
                        capture_output=True, text=True, timeout=5,
                        check=False, cwd=ROOT,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(state.read_text(encoding="ascii"),
                                     expected_bytes)
                    self.assertEqual(temporary.exists(), temp_left)
                    if expected_result is None:
                        self.assertTrue(result.stdout.startswith("result=0 "))
                    else:
                        self.assertEqual(result.stdout, expected_result)
                    self.assertEqual(result.stderr, "")

            # Reject a close failure before the canonical name is replaced;
            # a close-after-rename implementation fails the synthetic case.
            self.assertLess(
                writer.index("if (close(fd) < 0) {"),
                writer.index("if (renameat(recovery_fd, temporary_name"))

            # A writer that publishes success before its directory fsync must
            # fail this fixture even when the renamed bytes are already visible.
            self.assertIn("return fsync(recovery_fd);", writer)
            premature = writer.replace(
                "return fsync(recovery_fd);", "return 0;", 1)
            self.assertNotEqual(premature, writer)
            source.write_text(prefix + premature + suffix, encoding="utf-8")
            subprocess.run(compiler, check=True, cwd=ROOT)
            state = fixture / "primary-state.json"
            state.write_text("original\n", encoding="ascii")
            state.chmod(0o600)
            mutant = subprocess.run(
                [str(binary), str(fixture), "2"],
                capture_output=True, text=True, timeout=5,
                check=False, cwd=ROOT,
            )
            self.assertEqual(mutant.returncode, 0, mutant.stderr)
            self.assertTrue(mutant.stdout.startswith("result=0 "))
            self.assertNotEqual(
                mutant.stdout, f"result=-1 errno={errno.EIO}\n")

    def test_state_temporary_reconciliation_is_owner_bound_and_durable(self):
        """Recover unpublished same-run state temps without touching stale owners."""
        helper_start = self.primary.index(
            "static int swapz_primary_reconcile_state_temporary_file_at(")
        helper_end = self.primary.index(
            "\n/*\n * READY with an exact active marker", helper_start)
        helper = self.primary[helper_start:helper_end]

        state_write_start = self.primary.index(
            "int swapz_primary_state_write_at(")
        state_write_end = self.primary.index(
            "\nint swapz_primary_state_require_recovery_at(",
            state_write_start)
        state_write = self.primary[state_write_start:state_write_end]
        self.assertLess(
            state_write.index("swapz_primary_reconcile_state_temporary_at("),
            state_write.index("swapz_primary_replace_record_at("),
        )

        metadata_start = self.primary.index(
            "\nstatic int swapz_primary_reconcile_metadata_claim_at(",
            helper_start)
        metadata_end = self.primary.index(
            "\nstatic int swapz_primary_valid_sha256(", metadata_start)
        metadata = self.primary[metadata_start:metadata_end]
        self.assertLess(
            metadata.index(
                "swapz_primary_reconcile_state_temporary_file_at("),
            metadata.index("swapz_primary_replace_record_at("),
        )

        prefix = r"""#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define SWAPZ_PRIMARY_RUN_ID_LENGTH 32U
static const char *active_run;
static int injected_fsync_errno;
static unsigned int fsync_attempts;

static int swapz_primary_valid_run_id(const char *run_id)
{
    return run_id && strlen(run_id) == SWAPZ_PRIMARY_RUN_ID_LENGTH;
}
static int swapz_primary_state_lock_valid(
    int recovery_fd, int lock_fd, uid_t expected_owner)
{
    (void)recovery_fd;
    (void)lock_fd;
    (void)expected_owner;
    return 1;
}
static int swapz_primary_owner_claim_matches_at(
    int recovery_fd, const char *run_id, uid_t expected_owner)
{
    (void)recovery_fd;
    (void)expected_owner;
    if (strcmp(run_id, active_run)) {
        errno = EPERM;
        return 0;
    }
    return 1;
}
static int injected_fsync(int fd)
{
    (void)fd;
    ++fsync_attempts;
    if (injected_fsync_errno) {
        errno = injected_fsync_errno;
        return -1;
    }
    return 0;
}
#define fsync injected_fsync
"""
        suffix = r"""
#undef fsync

static int create_temporary(
    int directory_fd, const char *run_id, const char *payload)
{
    char name[256];
    int length;
    int fd;
    ssize_t payload_length = (ssize_t)strlen(payload);

    length = snprintf(
        name, sizeof(name), ".primary-state.json.%s.tmp", run_id);
    if (length < 0 || (size_t)length >= sizeof(name))
        return -1;
    fd = openat(directory_fd, name,
                O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW,
                0600);
    if (fd < 0)
        return -1;
    if (write(fd, payload, (size_t)payload_length) != payload_length) {
        int saved_errno = errno ? errno : EIO;
        (void)close(fd);
        errno = saved_errno;
        return -1;
    }
    return close(fd);
}
static int temporary_exists(int directory_fd, const char *run_id)
{
    char name[256];
    struct stat info;
    int length = snprintf(
        name, sizeof(name), ".primary-state.json.%s.tmp", run_id);

    if (length < 0 || (size_t)length >= sizeof(name))
        return -1;
    return fstatat(directory_fd, name, &info, AT_SYMLINK_NOFOLLOW) == 0;
}
int main(int argc, char **argv)
{
    const char *run_a = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const char *run_b = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    int directory_fd;
    int result;
    int saved_errno;
    int length;
    char name[256];

    if (argc != 2)
        return 64;
    directory_fd = open(argv[1], O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (directory_fd < 0)
        return 65;
    active_run = run_a;
    if (create_temporary(directory_fd, run_a, "stale-A\n") < 0)
        return 66;

    injected_fsync_errno = EIO;
    errno = 0;
    result = swapz_primary_reconcile_state_temporary_at(
        directory_fd, 7, run_a, getuid());
    saved_errno = errno;
    printf("unlink_sync=%d/%d exists=%d syncs=%u\n",
           result, saved_errno, temporary_exists(directory_fd, run_a),
           fsync_attempts);

    injected_fsync_errno = ENOSPC;
    errno = 0;
    result = swapz_primary_reconcile_state_temporary_at(
        directory_fd, 7, run_a, getuid());
    saved_errno = errno;
    printf("retry_ready=%d/%d exists=%d syncs=%u\n",
           result, saved_errno, temporary_exists(directory_fd, run_a),
           fsync_attempts);

    if (create_temporary(directory_fd, run_a, "metadata-A\n") < 0)
        return 67;
    active_run = run_b;
    injected_fsync_errno = 0;
    errno = 0;
    result = swapz_primary_reconcile_state_temporary_file_at(
        directory_fd, run_a, getuid());
    saved_errno = errno;
    printf("metadata_no_active=%d/%d exists=%d syncs=%u\n",
           result, saved_errno, temporary_exists(directory_fd, run_a),
           fsync_attempts);
    active_run = run_a;

    if (create_temporary(directory_fd, run_b, "stale-B\n") < 0)
        return 68;
    errno = 0;
    result = swapz_primary_reconcile_state_temporary_at(
        directory_fd, 7, run_b, getuid());
    saved_errno = errno;
    printf("stale_owner=%d/%d exists=%d syncs=%u\n",
           result, saved_errno, temporary_exists(directory_fd, run_b),
           fsync_attempts);

    length = snprintf(
        name, sizeof(name), ".primary-state.json.%s.tmp", run_a);
    if (length < 0 || (size_t)length >= sizeof(name))
        return 69;
    if (symlinkat("foreign-target", directory_fd, name) < 0)
        return 70;
    errno = 0;
    result = swapz_primary_reconcile_state_temporary_at(
        directory_fd, 7, run_a, getuid());
    saved_errno = errno;
    printf("symlink=%d/%d exists=%d syncs=%u\n",
           result, saved_errno, temporary_exists(directory_fd, run_a),
           fsync_attempts);
    return close(directory_fd) < 0 ? 71 : 0;
}
"""
        run_a = "a" * 32
        run_b = "b" * 32
        with TemporaryDirectory(prefix="swapz-primary-state-temp-") as temp:
            fixture = Path(temp)
            source = fixture / "state-temp.c"
            binary = fixture / "state-temp"
            compiler = [
                "cc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra",
                "-Werror", "-Wpedantic", str(source), "-o", str(binary),
            ]
            source.write_text(prefix + helper + suffix, encoding="utf-8")
            subprocess.run(compiler, check=True, cwd=ROOT)
            outcome = subprocess.run(
                [str(binary), str(fixture)], cwd=ROOT,
                capture_output=True, text=True, check=False, timeout=5,
            )
            self.assertEqual(outcome.returncode, 0, outcome.stderr)
            self.assertEqual(
                outcome.stdout,
                f"unlink_sync=-1/{errno.EIO} exists=0 syncs=1\n"
                f"retry_ready=0/{errno.ENOENT} exists=0 syncs=1\n"
                f"metadata_no_active=0/{errno.ENOENT} exists=0 syncs=2\n"
                f"stale_owner=-1/{errno.EPERM} exists=1 syncs=2\n"
                f"symlink=-1/{errno.EPERM} exists=1 syncs=2\n",
            )
            self.assertNotIn(run_a, outcome.stdout + outcome.stderr)
            self.assertNotIn(run_b, outcome.stdout + outcome.stderr)

            sync_guard = (
                "if (fsync(recovery_fd) < 0)\n"
                "\t\treturn -1;"
            )
            self.assertIn(sync_guard, helper)
            mutant_helper = helper.replace(
                sync_guard, "(void)fsync(recovery_fd);", 1)
            self.assertNotEqual(mutant_helper, helper)
            source.write_text(
                prefix + mutant_helper + suffix, encoding="utf-8")
            subprocess.run(compiler, check=True, cwd=ROOT)
            mutant_fixture = fixture / "mutant"
            mutant_fixture.mkdir(mode=0o700)
            mutant = subprocess.run(
                [str(binary), str(mutant_fixture)],
                cwd=ROOT, capture_output=True, text=True,
                check=False, timeout=5,
            )
            self.assertEqual(mutant.returncode, 0, mutant.stderr)
            self.assertIn(
                f"unlink_sync=0/{errno.ENOENT} exists=0 syncs=1\n",
                mutant.stdout,
            )

    def test_completed_owner_release_retries_directory_durability(self):
        """A missing marker is not proof that the prior unlink was durable."""
        begin = self.primary.index(
            "if (current.stage == SWAPZ_PRIMARY_STAGE_COMPLETE) {",
            self.primary.index(
                "static int swapz_primary_reconcile_metadata_claim_at("))
        end = self.primary.index(
            "\n\tif (current.has_recovery_previous_stage)", begin)
        guard = self.primary[begin:end]
        prefix = r"""#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define SWAPZ_PRIMARY_STAGE_COMPLETE 7
struct synthetic_state {
    int stage;
    const char *run_id;
};
static int inject_directory_sync_failure;
static int sync_attempts;
static int release_attempts;

/* The skip-fsync mutant removes the only call; external linkage keeps that
 * generated negative-control translation unit warning-clean under -Werror. */
int injected_fsync(int fd)
{
    ++sync_attempts;
    if (inject_directory_sync_failure) {
        errno = EIO;
        return -1;
    }
    return fsync(fd);
}
#define fsync injected_fsync

static int swapz_primary_release_partition_owner_at(
    int recovery_fd, int lock_fd, const char *run_id, uid_t expected_owner)
{
    (void)lock_fd;
    (void)run_id;
    (void)expected_owner;
    ++release_attempts;
    return unlinkat(recovery_fd, "partition.active", 0);
}
static int reconcile_complete(int recovery_fd, int active_present)
{
    struct synthetic_state current = {
        SWAPZ_PRIMARY_STAGE_COMPLETE, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    };
    const int lock_fd = 7;
    const uid_t expected_owner = getuid();
"""
        suffix = r"""
    return -77;
}
int main(int argc, char **argv)
{
    int recovery_fd;
    int active_present;
    int result;
    int saved_errno;
    struct stat info;

    if (argc != 3)
        return 64;
    inject_directory_sync_failure = atoi(argv[2]);
    recovery_fd = open(argv[1], O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (recovery_fd < 0)
        return 65;
    active_present = fstatat(recovery_fd, "partition.active", &info,
                             AT_SYMLINK_NOFOLLOW) == 0;
    errno = 0;
    result = reconcile_complete(recovery_fd, active_present);
    saved_errno = errno;
    if (close(recovery_fd) < 0)
        return 66;
    printf("result=%d errno=%d syncs=%d releases=%d\n",
           result, saved_errno, sync_attempts, release_attempts);
    return 0;
}
"""
        with TemporaryDirectory(prefix="swapz-primary-owner-durability-") as temp:
            fixture = Path(temp)
            source = fixture / "owner-durability.c"
            binary = fixture / "owner-durability"
            compiler = [
                "cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                "-Wpedantic", str(source), "-o", str(binary),
            ]
            source.write_text(prefix + guard + suffix, encoding="utf-8")
            subprocess.run(compiler, check=True, cwd=ROOT)
            marker = fixture / "partition.active"
            for mode, marker_present, expected in (
                (1, False,
                 f"result=-1 errno={errno.EIO} syncs=1 releases=0\n"),
                (0, False, "result=0 errno=0 syncs=1 releases=0\n"),
                (0, True, "result=0 errno=0 syncs=0 releases=1\n"),
            ):
                with self.subTest(mode=mode, marker=marker_present):
                    marker.unlink(missing_ok=True)
                    if marker_present:
                        marker.write_text("synthetic\n", encoding="ascii")
                    outcome = subprocess.run(
                        [str(binary), str(fixture), str(mode)],
                        capture_output=True, text=True, timeout=5,
                        check=False, cwd=ROOT,
                    )
                    self.assertEqual(outcome.returncode, 0, outcome.stderr)
                    self.assertEqual(outcome.stdout, expected)
                    self.assertEqual(marker.exists(), False)
            # Negative control: skipping the fsync publishes success in an
            # ambiguous owner-release window and must trip the expected verdict.
            self.assertIn("return fsync(recovery_fd);", guard)
            premature = guard.replace(
                "return fsync(recovery_fd);", "return 0;", 1)
            source.write_text(prefix + premature + suffix, encoding="utf-8")
            subprocess.run(compiler, check=True, cwd=ROOT)
            mutant = subprocess.run(
                [str(binary), str(fixture), "1"],
                capture_output=True, text=True, timeout=5, check=False,
                cwd=ROOT,
            )
            self.assertEqual(mutant.returncode, 0, mutant.stderr)
            self.assertTrue(mutant.stdout.startswith("result=0 "))
            self.assertNotIn("syncs=1", mutant.stdout)


    def test_definite_swap_syscall_error_preserves_first_errno(self):
        """Definite errors return before a later inventory failure can replace them."""
        begin = self.primary.index(
            "static int swapz_primary_swap_transition_apply(")
        end = self.primary.index(
            "static int swapz_primary_mapper_node_retryable_errno(", begin)
        helper = self.primary[begin:end]
        early_failure = (
            "if (syscall_result < 0 && syscall_errno != EINTR) {")
        self.assertIn(early_failure, helper)

        prefix = r"""#define _GNU_SOURCE
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/types.h>

struct swapz_primary_swap_transition_ops {
    int (*device_active)(void *context, dev_t expected_device);
    long (*swapon)(void *context, const char *mapper_path);
    long (*swapoff)(void *context, const char *mapper_path);
    void *context;
};
"""
        suffix = r"""
struct fixture_state {
    int activate;
    int interrupted;
    int inventory_calls;
    int swapon_calls;
    int swapoff_calls;
};

static int fake_device_active(void *context, dev_t device)
{
    struct fixture_state *state = context;

    ++state->inventory_calls;
    if (state->inventory_calls == 3) {
        errno = EIO;
        return -1;
    }
    if (!state->activate && device == 123 && state->inventory_calls == 2)
        return 1;
    return 0;
}

static long fake_swapon(void *context, const char *path)
{
    struct fixture_state *state = context;

    (void)path;
    ++state->swapon_calls;
    errno = state->interrupted ? EINTR : EBUSY;
    return -1;
}

static long fake_swapoff(void *context, const char *path)
{
    struct fixture_state *state = context;

    (void)path;
    ++state->swapoff_calls;
    errno = state->interrupted ? EINTR : EBUSY;
    return -1;
}

int main(int argc, char **argv)
{
    struct fixture_state state = {0};
    int verified = 0;
    int result;

    if (argc != 3)
        return 2;
    state.activate = atoi(argv[1]);
    state.interrupted = atoi(argv[2]);
    const struct swapz_primary_swap_transition_ops ops = {
        fake_device_active, fake_swapon, fake_swapoff, &state
    };

    errno = 0;
    result = swapz_primary_swap_transition_apply(
        state.activate, 123, 456, "/proc/self/fd/9", &ops, &verified);
    printf("result=%d errno=%d inventory=%d swapon=%d swapoff=%d verified=%d\n",
           result, result < 0 ? errno : 0, state.inventory_calls,
           state.swapon_calls, state.swapoff_calls, verified);
    return 0;
}
"""
        cases = (
            ("1", "0",
             f"result=-1 errno={errno.EBUSY} inventory=2 "
             "swapon=1 swapoff=0 verified=0\n"),
            ("0", "0",
             f"result=-1 errno={errno.EBUSY} inventory=2 "
             "swapon=0 swapoff=1 verified=0\n"),
            ("1", "1",
             f"result=-1 errno={errno.EIO} inventory=3 "
             "swapon=1 swapoff=0 verified=0\n"),
            ("0", "1",
             f"result=-1 errno={errno.EIO} inventory=3 "
             "swapon=0 swapoff=1 verified=0\n"),
        )
        with TemporaryDirectory(
                prefix="swapz-primary-swap-first-errno-") as directory:
            fixture = Path(directory)
            source = fixture / "swap-transition-first-errno.c"
            binary = fixture / "swap-transition-first-errno"
            compiler = [
                "cc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
                str(source), "-o", str(binary),
            ]
            source.write_text(prefix + helper + suffix, encoding="utf-8")
            subprocess.run(compiler, check=True, cwd=ROOT)
            for activate, interrupted, expected in cases:
                with self.subTest(
                        activate=activate, interrupted=interrupted):
                    outcome = subprocess.run(
                        [str(binary), activate, interrupted],
                        capture_output=True, text=True, timeout=5,
                        check=False, cwd=ROOT)
                    self.assertEqual(outcome.returncode, 0, outcome.stderr)
                    self.assertEqual(outcome.stdout, expected)

            # Negative control: the old activation-only late check lets a
            # subsequent inventory EIO replace the definite swapon EBUSY.
            mutant = helper.replace(
                early_failure,
                "if (!activate && syscall_result < 0 && "
                "syscall_errno != EINTR) {",
                1)
            self.assertNotEqual(mutant, helper)
            source.write_text(prefix + mutant + suffix, encoding="utf-8")
            subprocess.run(compiler, check=True, cwd=ROOT)
            outcome = subprocess.run(
                [str(binary), "1", "0"], capture_output=True, text=True,
                timeout=5, check=False, cwd=ROOT)
            self.assertEqual(outcome.returncode, 0, outcome.stderr)
            self.assertEqual(
                outcome.stdout,
                f"result=-1 errno={errno.EIO} inventory=3 "
                "swapon=1 swapoff=0 verified=0\n")

    def test_definite_swapoff_blocks_mapper_removal_in_stop_and_recover(self):
        """Exercise source-extracted coordinator ordering without host syscalls."""
        functions = (
            ("STOP", "static int swapz_primary_stop_active(",
             "static int swapz_primary_recover(", "stop-mapper-removed"),
            ("RECOVER", "static int swapz_primary_recover(",
             "static int swapz_primary_read_only_plan(",
             "recover-mapper-removed"),
        )
        prefix = r"""#define _GNU_SOURCE
#include <errno.h>
#include <stdio.h>
#include <sys/types.h>

struct synthetic_manifest { int unused; };
static int mapper_attempts;
static int swapoff_attempts;
static int injected_swapoff(int recovery_fd, int lock_fd,
                            const struct synthetic_manifest *manifest,
                            int *deactivated_by_call)
{
    (void)recovery_fd;
    (void)lock_fd;
    (void)manifest;
    *deactivated_by_call = 0;
    ++swapoff_attempts;
    errno = EBUSY;
    return -1;
}
static int injected_remove(int recovery_fd, int lock_fd,
                           const struct synthetic_manifest *manifest,
                           int *removed_by_call)
{
    (void)recovery_fd;
    (void)lock_fd;
    (void)manifest;
    ++mapper_attempts;
    *removed_by_call = 1;
    return 0;
}
#define swapz_primary_deactivate_mapper_swap injected_swapoff
#define swapz_primary_dm_remove_mapper injected_remove
#define SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER(phase) ((void)0)
static int execute_transaction(void)
{
    const int recovery_fd = 7;
    const int lock_fd = 8;
    struct synthetic_manifest manifest = {0};
    int swap_deactivated_by_call = 0;
    int mapper_removed_by_call = 0;
    const char *failure_phase = "admission";
    const char *swap_observation = "UNOBSERVED";
    const char *mapper_observation = "UNOBSERVED";
    int result = -1;
"""
        suffix = r"""
    result = 0;
out:
    printf("result=%d errno=%d swapoff=%d mapper=%d phase=%s "
           "swap=%s mapper_state=%s\n",
           result, errno, swapoff_attempts, mapper_attempts, failure_phase,
           swap_observation, mapper_observation);
    return result;
}
int main(void) { return execute_transaction() < 0 ? 0 : 1; }
"""
        for operation, begin, end, final_phase in functions:
            with self.subTest(operation=operation):
                start = self.primary.index(begin)
                body = self.primary[start:self.primary.index(end, start)]
                begin_step = body.index('failure_phase = "swapoff";')
                end_step = body.index(
                    f'SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("{final_phase}");',
                    begin_step)
                snippet = body[begin_step:end_step]
                with TemporaryDirectory(
                        prefix="swapz-primary-swapoff-gate-") as temp:
                    fixture = Path(temp)
                    source = fixture / "swapoff-gate.c"
                    binary = fixture / "swapoff-gate"
                    compiler = [
                        "cc", "-std=c11", "-O2", "-Wall", "-Wextra",
                        "-Werror", "-Wpedantic", str(source), "-o",
                        str(binary),
                    ]
                    source.write_text(prefix + snippet + suffix,
                                      encoding="utf-8")
                    subprocess.run(compiler, check=True, cwd=ROOT)
                    outcome = subprocess.run(
                        [str(binary)], capture_output=True, text=True,
                        check=False, timeout=5, cwd=ROOT,
                    )
                    self.assertEqual(outcome.returncode, 0, outcome.stderr)
                    self.assertEqual(
                        outcome.stdout,
                        f"result=-1 errno={errno.EBUSY} swapoff=1 "
                        "mapper=0 phase=swapoff swap=UNCERTAIN "
                        "mapper_state=UNOBSERVED\n",
                    )
                    # Mutating the stop gate must expose a DM removal attempt.
                    mutated = snippet.replace(
                        "&swap_deactivated_by_call) < 0)",
                        "&swap_deactivated_by_call) < 0 && 0)", 1)
                    self.assertNotEqual(snippet, mutated)
                    source.write_text(prefix + mutated + suffix,
                                      encoding="utf-8")
                    subprocess.run(compiler, check=True, cwd=ROOT)
                    mutant = subprocess.run(
                        [str(binary)], capture_output=True, text=True,
                        check=False, timeout=5, cwd=ROOT,
                    )
                    self.assertNotEqual(mutant.stdout, outcome.stdout)
                    self.assertIn("mapper=1", mutant.stdout)



    def test_lifecycle_observability_tracks_completed_proof_not_by_call_flags(self):
        """OBSERVED means the proof helper completed, not merely an ioctl ran."""
        stop_recover = (
            ("STOP", "static int swapz_primary_stop_active(",
             "static int swapz_primary_recover(", "stop-mapper-removed"),
            ("RECOVER", "static int swapz_primary_recover(",
             "static int swapz_primary_read_only_plan(",
             "recover-mapper-removed"),
        )
        prefix = r"""#define _GNU_SOURCE
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/types.h>

struct synthetic_manifest { int unused; };
static int deactivate_mode;
static int remove_mode;
static int deactivate_calls;
static int remove_calls;

static int injected_deactivate(
    int recovery_fd, int lock_fd, const struct synthetic_manifest *manifest,
    int *deactivated_by_call)
{
    (void)recovery_fd;
    (void)lock_fd;
    (void)manifest;
    ++deactivate_calls;
    *deactivated_by_call = 0;
    if (deactivate_mode != 0) {
        errno = EBUSY;
        return -1;
    }
    return 0; /* Exact inventory already proved inactive. */
}

static int injected_remove(
    int recovery_fd, int lock_fd, const struct synthetic_manifest *manifest,
    int *removed_by_call)
{
    (void)recovery_fd;
    (void)lock_fd;
    (void)manifest;
    ++remove_calls;
    *removed_by_call = remove_mode == 2;
    if (remove_mode == 1 || remove_mode == 2) {
        errno = EIO;
        return -1;
    }
    return 0; /* Exact absence may be proved without a remove ioctl. */
}

#define swapz_primary_deactivate_mapper_swap injected_deactivate
#define swapz_primary_dm_remove_mapper injected_remove
#define SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER(phase) ((void)0)

static int run_case(void)
{
    const int recovery_fd = 7;
    const int lock_fd = 8;
    struct synthetic_manifest manifest = {0};
    int swap_deactivated_by_call = 0;
    int mapper_removed_by_call = 0;
    const char *failure_phase = "admission";
    const char *swap_observation = "UNOBSERVED";
    const char *mapper_observation = "UNOBSERVED";
    int result = -1;
"""
        suffix = r"""
after_steps:
out:
    printf("result=%d errno=%d deactivate=%d remove=%d "
           "phase=%s swap=%s mapper=%s by_call=%d/%d\n",
           result, errno, deactivate_calls, remove_calls, failure_phase,
           swap_observation, mapper_observation,
           swap_deactivated_by_call, mapper_removed_by_call);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc != 3)
        return 64;
    deactivate_mode = atoi(argv[1]);
    remove_mode = atoi(argv[2]);
    return run_case();
}
"""
        expected_cases = (
            # Already-inactive swap is OBSERVED even though no swapoff was
            # performed; a failed mapper proof remains UNCERTAIN.
            (0, 1, "swap=OBSERVED mapper=UNCERTAIN by_call=0/0"),
            # A remove ioctl followed by failed absence proof is not OBSERVED.
            (0, 2, "swap=OBSERVED mapper=UNCERTAIN by_call=0/1"),
            # Already-absent mapper is OBSERVED without a remove ioctl.
            (0, 0, "swap=OBSERVED mapper=OBSERVED by_call=0/0"),
            # A definite swapoff failure cannot establish post-call state and
            # must not enter mapper removal.
            (1, 0, "swap=UNCERTAIN mapper=UNOBSERVED by_call=0/0"),
        )
        for operation, begin, end, last_interrupt in stop_recover:
            body_start = self.primary.index(begin)
            body = self.primary[
                body_start:self.primary.index(end, body_start)]
            first = body.index('failure_phase = "swapoff";')
            last = body.index(
                f'SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("{last_interrupt}");',
                first)
            snippet = body[first:last]
            owner_phase = body.index('failure_phase = "owner-release";')
            owner_call = body.index(
                "swapz_primary_release_partition_owner_at(", owner_phase)
            owner_window = body[owner_phase:owner_call]
            self.assertIn(
                'persistence_boundary = "owner-unlink-directory-fsync";',
                owner_window)
            self.assertIn(
                'durable_observation = "UNCERTAIN";', owner_window)
            with TemporaryDirectory(
                    prefix=f"swapz-primary-{operation.lower()}-observability-"
            ) as directory:
                fixture = Path(directory)
                source = fixture / "observability.c"
                binary = fixture / "observability"
                compiler = [
                    "cc", "-std=c11", "-O2", "-Wall", "-Wextra",
                    "-Werror", "-Wpedantic", str(source), "-o", str(binary),
                ]
                source.write_text(
                    prefix + snippet + "\ngoto after_steps;\n" + suffix,
                    encoding="utf-8")
                subprocess.run(compiler, check=True, cwd=ROOT)
                for deactivate_mode, remove_mode, expected in expected_cases:
                    with self.subTest(
                            operation=operation,
                            deactivate=deactivate_mode,
                            remove=remove_mode):
                        result = subprocess.run(
                            [
                                str(binary), str(deactivate_mode),
                                str(remove_mode),
                            ],
                            cwd=ROOT, capture_output=True, text=True,
                            check=False, timeout=5,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertIn(expected, result.stdout)
                        if deactivate_mode != 0:
                            self.assertIn("remove=0", result.stdout)

                # Negative controls: deleting either post-success proof marker
                # must make the corresponding exact-observation case fail.
                for assignment, expected in (
                        ('swap_observation = "OBSERVED";',
                         "swap=OBSERVED mapper=UNCERTAIN by_call=0/0"),
                        ('mapper_observation = "OBSERVED";',
                         "swap=OBSERVED mapper=OBSERVED by_call=0/0")):
                    with self.subTest(
                            operation=operation, mutation=assignment):
                        mutated = snippet.replace(assignment, "", 1)
                        self.assertNotEqual(mutated, snippet)
                        source.write_text(
                            prefix + mutated + "\ngoto after_steps;\n" +
                            suffix, encoding="utf-8")
                        subprocess.run(compiler, check=True, cwd=ROOT)
                        remove_mode = 1 if assignment.startswith("swap") else 0
                        mutant = subprocess.run(
                            [str(binary), "0", str(remove_mode)],
                            cwd=ROOT, capture_output=True, text=True,
                            check=False, timeout=5,
                        )
                        self.assertEqual(mutant.returncode, 0, mutant.stderr)
                        self.assertNotIn(expected, mutant.stdout)

        start_begin = self.primary.index(
            "static int swapz_primary_start_prepared(")
        start_end = self.primary.index(
            "static int swapz_primary_state_recoverable(", start_begin)
        start = self.primary[start_begin:start_end]
        mapper_call = start.index("swapz_primary_dm_create_mapper(")
        mapper_proof = start.index(
            'mapper_observation = "OBSERVED";', mapper_call)
        swapon_call = start.index(
            "swapz_primary_activate_mapper_swap(", mapper_proof)
        swap_proof = start.index(
            'swap_observation = "OBSERVED";', swapon_call)
        active_write = start.index(
            "swapz_primary_state_write_at(", swap_proof)
        self.assertLess(mapper_call, mapper_proof)
        self.assertLess(mapper_proof, swapon_call)
        self.assertLess(swapon_call, swap_proof)
        self.assertLess(swap_proof, active_write)
        active_window = start[swap_proof:active_write]
        self.assertIn('durable_observation = "UNCERTAIN";', active_window)
        self.assertIn(
            'persistence_boundary = "state-file-fsync-close-rename-directory-fsync";',
            active_window)
        detail_begin = start.index('"PRIMARY_START=ADMISSION_DETAIL')
        detail_end = start.index(");", detail_begin)
        detail = start[detail_begin:detail_end]
        for field in (
                "original_errno=%d", "persistence_boundary=%s",
                "durable=%s", "mapper=%s", "swap=%s"):
            self.assertIn(field, detail)

    def test_stale_run_state_updates_cannot_mutate_newer_owner(self):
        """Exercise the production owner-claim gate in both state writers."""
        owner_start = self.primary.index(
            "static int swapz_primary_owner_claim_matches_at(")
        owner_end = self.primary.index(
            "\nstatic int swapz_primary_reconcile_state_temporary_file_at(",
            owner_start)
        owner_claim = self.primary[owner_start:owner_end]

        write_start = self.primary.index("int swapz_primary_state_write_at(")
        write_end = self.primary.index(
            "\nint swapz_primary_state_require_recovery_at(", write_start)
        state_write = self.primary[write_start:write_end]

        recovery_start = write_end + 1
        recovery_end = self.primary.index(
            "\n#ifndef SWAPZ_PRIMARY_ROOTLESS_TEST", recovery_start)
        require_recovery = self.primary[recovery_start:recovery_end]

        prefix = r"""#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define SWAPZ_PRIMARY_STATE_RECORD_MAX 4096U
#define SWAPZ_PRIMARY_PARTITION_NAME_BYTES 128U
#define SWAPZ_PRIMARY_RUN_ID_LENGTH 32U
#define SWAPZ_PRIMARY_STAGE_READY 0
#define SWAPZ_PRIMARY_STAGE_ACTIVE 2
#define SWAPZ_PRIMARY_STAGE_COMPLETE 7

struct swapz_primary_target {
    uint32_t device_major;
    uint32_t device_minor;
    char partuuid[37];
};
struct swapz_primary_state {
    char run_id[SWAPZ_PRIMARY_RUN_ID_LENGTH + 1U];
    int stage;
    int has_recovery_previous_stage;
    int recovery_previous_stage;
};
static struct swapz_primary_target swapz_primary_selected_target = {
    7U, 9U, "synthetic"
};
#define SWAPZ_PRIMARY_PARTUUID (swapz_primary_selected_target.partuuid)

static int unexpected_state_path_calls;
static int mutation_attempts;

static int swapz_primary_valid_run_id(const char *run_id)
{
    return run_id && strlen(run_id) == SWAPZ_PRIMARY_RUN_ID_LENGTH;
}
static int swapz_primary_state_valid(const struct swapz_primary_state *state)
{
    return state && swapz_primary_valid_run_id(state->run_id);
}
static int swapz_primary_target_valid(const struct swapz_primary_target *target)
{
    return target == &swapz_primary_selected_target;
}
static int swapz_primary_state_lock_valid(
    int recovery_fd, int lock_fd, uid_t expected_owner)
{
    (void)recovery_fd;
    (void)lock_fd;
    (void)expected_owner;
    return 1;
}
static int swapz_primary_record_read_at(
    int recovery_fd, const char *name, uid_t expected_owner,
    char *record, size_t capacity, size_t *length, struct stat *identity)
{
    int fd;
    ssize_t count;
    int saved_errno;

    (void)expected_owner;
    (void)identity;
    fd = openat(recovery_fd, name, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0)
        return -1;
    count = read(fd, record, capacity);
    saved_errno = errno;
    if (close(fd) < 0 && count >= 0)
        return -1;
    if (count < 0) {
        errno = saved_errno;
        return -1;
    }
    *length = (size_t)count;
    return 0;
}
static int swapz_primary_state_parse(
    const char *record, size_t length, struct swapz_primary_state *state)
{
    (void)record;
    (void)length;
    (void)state;
    ++unexpected_state_path_calls;
    errno = EFAULT;
    return -1;
}
static int swapz_primary_state_transition_allowed(
    const struct swapz_primary_state *current,
    const struct swapz_primary_state *next)
{
    (void)current;
    (void)next;
    ++unexpected_state_path_calls;
    return 0;
}
static int swapz_primary_state_format(
    const struct swapz_primary_state *state, char *record, size_t capacity)
{
    (void)state;
    (void)record;
    (void)capacity;
    ++unexpected_state_path_calls;
    errno = EFAULT;
    return -1;
}
static int swapz_primary_reconcile_state_temporary_at(
    int recovery_fd, int lock_fd, const char *run_id, uid_t expected_owner)
{
    (void)recovery_fd;
    (void)lock_fd;
    (void)run_id;
    (void)expected_owner;
    ++unexpected_state_path_calls;
    errno = EFAULT;
    return -1;
}
static int swapz_primary_replace_record_at(
    int recovery_fd, const char *name, const char *run_id,
    const char *record, uid_t expected_owner)
{
    (void)recovery_fd;
    (void)name;
    (void)run_id;
    (void)record;
    (void)expected_owner;
    ++mutation_attempts;
    errno = EFAULT;
    return -1;
}
static int swapz_primary_recovery_required_state(
    const struct swapz_primary_state *current,
    struct swapz_primary_state *recovery_required)
{
    (void)current;
    (void)recovery_required;
    ++unexpected_state_path_calls;
    errno = EFAULT;
    return -1;
}
"""
        suffix = r"""
static int read_exact_file(
    int directory_fd, const char *name, char *buffer, size_t capacity,
    size_t *length)
{
    int fd = openat(directory_fd, name, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    ssize_t count;
    int saved_errno;

    if (fd < 0)
        return -1;
    count = read(fd, buffer, capacity);
    saved_errno = errno;
    if (close(fd) < 0 && count >= 0)
        return -1;
    if (count < 0) {
        errno = saved_errno;
        return -1;
    }
    *length = (size_t)count;
    return 0;
}

int main(int argc, char **argv)
{
    struct swapz_primary_state stale = {0};
    char before[256];
    char after[256];
    size_t before_length;
    size_t after_length;
    int directory_fd;
    int active_result;
    int active_errno;
    int complete_result;
    int complete_errno;
    int recovery_result;
    int recovery_errno;

    if (argc != 3)
        return 64;
    directory_fd = open(argv[1], O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (directory_fd < 0)
        return 65;
    memcpy(stale.run_id, argv[2], SWAPZ_PRIMARY_RUN_ID_LENGTH + 1U);
    stale.stage = SWAPZ_PRIMARY_STAGE_ACTIVE;
    if (read_exact_file(
            directory_fd, "primary-state.json", before, sizeof(before),
            &before_length) < 0)
        return 66;

    errno = 0;
    active_result = swapz_primary_state_write_at(
        directory_fd, 7, &stale, getuid());
    active_errno = errno;
    stale.stage = SWAPZ_PRIMARY_STAGE_COMPLETE;
    errno = 0;
    complete_result = swapz_primary_state_write_at(
        directory_fd, 7, &stale, getuid());
    complete_errno = errno;
    errno = 0;
    recovery_result = swapz_primary_state_require_recovery_at(
        directory_fd, 7, argv[2], getuid());
    recovery_errno = errno;

    if (read_exact_file(
            directory_fd, "primary-state.json", after, sizeof(after),
            &after_length) < 0)
        return 67;
    if (close(directory_fd) < 0)
        return 68;
    printf("active=%d/%d complete=%d/%d recovery=%d/%d "
           "mutations=%d unexpected=%d unchanged=%d\n",
           active_result, active_errno, complete_result, complete_errno,
           recovery_result, recovery_errno, mutation_attempts,
           unexpected_state_path_calls,
           before_length == after_length &&
               memcmp(before, after, before_length) == 0);
    return 0;
}
"""
        run_a = "a" * 32
        run_b = "b" * 32
        with TemporaryDirectory(prefix="swapz-primary-stale-writer-") as temp:
            fixture = Path(temp)
            source = fixture / "stale-writer.c"
            binary = fixture / "stale-writer"
            source.write_text(
                prefix + owner_claim + state_write + require_recovery + suffix,
                encoding="utf-8")
            subprocess.run(
                [
                    "cc", "-std=c11", "-O2", "-Wall", "-Wextra",
                    "-Werror", "-Wpedantic", str(source), "-o", str(binary),
                ],
                cwd=ROOT, check=True,
            )
            expected_b = (
                '{"major":7,"minor":9,"partuuid":"synthetic",'
                f'"run_id":"{run_b}"}}\n'
            )
            expected_a = (
                '{"major":7,"minor":9,"partuuid":"synthetic",'
                f'"run_id":"{run_a}"}}\n'
            )
            active_path = fixture / "partition-synthetic.active"
            consumed_a_path = fixture / f"consumed-{run_a}.json"
            consumed_b_path = fixture / f"consumed-{run_b}.json"
            active_path.write_text(expected_b, encoding="ascii")
            consumed_a_path.write_text(expected_a, encoding="ascii")
            consumed_b_path.write_text(expected_b, encoding="ascii")
            canonical_state = (
                f'{{"run_id":"{run_b}","stage":"READY"}}\n'
            )
            state_path = fixture / "primary-state.json"
            state_path.write_text(canonical_state, encoding="ascii")
            for path in (
                    active_path, consumed_a_path, consumed_b_path, state_path):
                path.chmod(0o600)
            outcome = subprocess.run(
                [str(binary), str(fixture), run_a],
                cwd=ROOT, capture_output=True, text=True,
                check=False, timeout=5,
            )
            self.assertEqual(outcome.returncode, 0, outcome.stderr)
            self.assertIn(
                f"active=-1/{errno.EPERM} complete=-1/{errno.EPERM} "
                f"recovery=-1/{errno.EPERM} mutations=0 unexpected=0 "
                "unchanged=1",
                outcome.stdout,
            )
            self.assertTrue(
                state_path.read_text(encoding="ascii") == canonical_state,
                "stale state writer changed newer canonical state")
            self.assertTrue(
                active_path.read_text(encoding="ascii") == expected_b,
                "stale state writer changed newer owner marker")
            self.assertNotRegex(outcome.stdout + outcome.stderr,
                                r"\b[0-9a-f]{32}\b")

    def test_owner_release_failure_and_stale_run_leave_recoverable_evidence(self):
        """Exercise the actual owner-release body against synthetic files."""
        begin = self.primary.index(
            "int swapz_primary_release_partition_owner_at(")
        end = self.primary.index(
            "\nint swapz_primary_partition_lock_acquire(", begin)
        release = self.primary[begin:end]
        prefix = r"""#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define SWAPZ_PRIMARY_STATE_RECORD_MAX 4096U
#define SWAPZ_PRIMARY_PARTITION_NAME_BYTES 128U
#define SWAPZ_PRIMARY_STAGE_COMPLETE 7
#define SWAPZ_PRIMARY_PARTUUID (swapz_primary_selected_target.partuuid)
struct swapz_primary_state { int stage; char run_id[33]; };
static struct { char partuuid[37]; } swapz_primary_selected_target = {
    "synthetic"
};
static int injected_failure_mode;

static int swapz_primary_valid_run_id(const char *run_id)
{
    return run_id && strlen(run_id) == 32U;
}
static int swapz_primary_state_lock_valid(
    int recovery_fd, int lock_fd, uid_t expected_owner)
{
    (void)recovery_fd;
    (void)lock_fd;
    (void)expected_owner;
    return 1;
}
static int swapz_primary_owner_claim_matches_at(
    int recovery_fd, const char *run_id, uid_t expected_owner)
{
    char marker[64];
    ssize_t length;
    int fd;

    (void)expected_owner;
    fd = openat(recovery_fd, "partition-synthetic.active",
                O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0)
        return 0;
    length = read(fd, marker, sizeof(marker));
    if (close(fd) < 0 || length != 33 ||
        memcmp(marker, run_id, 32U) != 0 || marker[32] != '\n') {
        errno = EPERM;
        return 0;
    }
    return 1;
}
static int swapz_primary_record_read_at(
    int recovery_fd, const char *name, uid_t expected_owner,
    char *record, size_t capacity, size_t *length, struct stat *identity)
{
    int fd;
    ssize_t count;
    int saved_errno;

    (void)expected_owner;
    fd = openat(recovery_fd, name, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0)
        return -1;
    if (identity && fstat(fd, identity) < 0) {
        saved_errno = errno;
        (void)close(fd);
        errno = saved_errno;
        return -1;
    }
    count = read(fd, record, capacity - 1U);
    saved_errno = errno;
    if (close(fd) < 0 && count >= 0)
        return -1;
    if (count < 0) {
        errno = saved_errno;
        return -1;
    }
    record[count] = '\0';
    *length = (size_t)count;
    return 0;
}
static int swapz_primary_state_parse(
    const char *record, size_t length, struct swapz_primary_state *state)
{
    const char *prefix = "COMPLETE:";
    const size_t prefix_length = 9U;

    if (length != prefix_length + 32U + 1U ||
        memcmp(record, prefix, prefix_length) != 0 ||
        record[length - 1U] != '\n')
        return -1;
    memcpy(state->run_id, record + prefix_length, 32U);
    state->run_id[32] = '\0';
    state->stage = SWAPZ_PRIMARY_STAGE_COMPLETE;
    return 0;
}
static int injected_unlinkat(int directory_fd, const char *name, int flags)
{
    int result;

    if (injected_failure_mode == 1) {
        errno = EACCES;
        return -1;
    }
    result = unlinkat(directory_fd, name, flags);
    if (result == 0 && injected_failure_mode == 3) {
        errno = EIO;
        return -1;
    }
    return result;
}
static int injected_fsync(int fd)
{
    if (injected_failure_mode == 2) {
        errno = EIO;
        return -1;
    }
    return fsync(fd);
}
#define unlinkat injected_unlinkat
#define fsync injected_fsync
"""
        suffix = r"""
int main(int argc, char **argv)
{
    int recovery_fd;
    int result;
    int saved_errno;

    if (argc != 4)
        return 64;
    injected_failure_mode = atoi(argv[2]);
    recovery_fd = open(argv[1], O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (recovery_fd < 0)
        return 65;
    errno = 0;
    result = swapz_primary_release_partition_owner_at(
        recovery_fd, 7, argv[3], getuid());
    saved_errno = errno;
    if (close(recovery_fd) < 0)
        return 66;
    printf("result=%d errno=%d\n", result, saved_errno);
    return 0;
}
"""
        run_a = "a" * 32
        run_b = "b" * 32
        with TemporaryDirectory(prefix="swapz-primary-release-synthetic-") as temp:
            fixture = Path(temp)
            source = fixture / "release.c"
            binary = fixture / "release"
            compiler = [
                "cc", "-std=c11", "-O2", "-Wall", "-Wextra",
                "-Werror", "-Wpedantic", str(source), "-o", str(binary),
            ]
            source.write_text(prefix + release + suffix, encoding="utf-8")
            subprocess.run(compiler, check=True, cwd=ROOT)
            state = fixture / "primary-state.json"
            marker = fixture / "partition-synthetic.active"
            for scenario, failure_mode, owner_run, active_run, expected_errno, removed in (
                ("unlink-failed", 1, run_a, run_a, errno.EACCES, False),
                ("fsync-failed-after-unlink", 2, run_a, run_a, errno.EIO, True),
                ("unlink-failed-after-effect", 3, run_a, run_a, errno.EIO, True),
                ("stale-run-A-after-B", 0, run_a, run_b, errno.EPERM, False),
                ("released", 0, run_a, run_a, None, True),
            ):
                with self.subTest(scenario=scenario):
                    original = f"COMPLETE:{active_run}\n"
                    state.write_text(original, encoding="ascii")
                    state.chmod(0o600)
                    marker.write_text(f"{active_run}\n", encoding="ascii")
                    marker.chmod(0o600)
                    outcome = subprocess.run(
                        [str(binary), str(fixture), str(failure_mode), owner_run],
                        capture_output=True, text=True, timeout=5,
                        check=False, cwd=ROOT,
                    )
                    self.assertEqual(outcome.returncode, 0, outcome.stderr)
                    if expected_errno is not None:
                        self.assertEqual(
                            outcome.stdout,
                            f"result=-1 errno={expected_errno}\n")
                    else:
                        self.assertTrue(outcome.stdout.startswith("result=0 "))
                    self.assertEqual(marker.exists(), not removed)
                    self.assertTrue(
                        state.read_text(encoding="ascii") == original,
                        "owner-release failure changed canonical state")
                    self.assertEqual(outcome.stderr, "")

            # Mutant proves the post-unlink fsync failure cannot be treated
            # as a completed owner release merely because the marker vanished.
            original_guard = ("if (fsync(recovery_fd) < 0)\n"
                              "\t\treturn -1;")
            self.assertIn(original_guard, release)
            premature = release.replace(
                original_guard, "(void)fsync(recovery_fd);", 1)
            source.write_text(prefix + premature + suffix, encoding="utf-8")
            subprocess.run(compiler, check=True, cwd=ROOT)
            state.write_text(f"COMPLETE:{run_a}\n", encoding="ascii")
            marker.write_text(f"{run_a}\n", encoding="ascii")
            mutant = subprocess.run(
                [str(binary), str(fixture), "2", run_a],
                capture_output=True, text=True, timeout=5, check=False,
                cwd=ROOT,
            )
            self.assertEqual(mutant.returncode, 0, mutant.stderr)
            self.assertTrue(mutant.stdout.startswith("result=0 "))
            self.assertFalse(marker.exists())

    def test_start_stop_recover_share_errno_preserving_recovery_epilogue(self):
        function_ranges = (
            (
                "START",
                "static int swapz_primary_start_prepared(",
                "static int swapz_primary_state_recoverable(",
                "PRIMARY_START=ACTIVE",
            ),
            (
                "STOP",
                "static int swapz_primary_stop_active(",
                "static int swapz_primary_recover(",
                "PRIMARY_STOP=COMPLETE",
            ),
            (
                "RECOVER",
                "static int swapz_primary_recover(",
                "static int swapz_primary_read_only_plan(",
                "PRIMARY_RECOVER=COMPLETE",
            ),
        )
        for operation, begin, end, success_marker in function_ranges:
            with self.subTest(operation=operation):
                body_start = self.primary.index(begin)
                body = self.primary[
                    body_start:self.primary.index(end, body_start)]
                epilogue = body[body.index("out:"):]
                helper_call = (
                    "saved_errno = "
                    "swapz_primary_require_recovery_preserving_errno(")
                self.assertEqual(epilogue.count(helper_call), 1)
                call_start = epilogue.index(helper_call)
                call_end = epilogue.index(";", call_start)
                self.assertIn(
                    f'"{operation}"', epilogue[call_start:call_end])
                success_gate = epilogue.index("if (result == 0)", call_end)
                self.assertIn(success_marker, epilogue[success_gate:])
                self.assertLess(call_end, success_gate)
                final_errno = epilogue.index(
                    "errno = saved_errno;", success_gate)
                self.assertLess(success_gate, final_errno)
        self.assertNotIn(
            "RECOVERY_STATE_FAILED run_id=%s", self.primary)

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

    def test_private_qualification_report_uses_production_host_identity(self):
        self.assertIn("def trusted_host_record(path, byte_limit, pattern):",
                      self.script)
        self.assertIn('"/sys/class/dmi/id/product_uuid"', self.script)
        self.assertIn('rb"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"', self.script)
        self.assertIn('"/etc/machine-id"', self.script)
        self.assertIn('b"swapz-host-v2\\0"', self.script)
        self.assertIn('b"swapz-nullblk-arm64-v1\\0"', self.script)
        self.assertIn('defined(SWAPZ_PRIMARY_OWNED_NULLBLK_TEST) && '
                      'defined(__aarch64__)', self.primary)
        self.assertNotIn('b"swapz-host\\0"', self.script)
        self.assertIn(
            'static const unsigned char prefix[] = "swapz-host-v2";',
            self.primary)


    def test_rootless_private_report_host_digest_and_encoding(self):
        import hashlib
        import json

        host_marker = 'HOST_SHA="$(python3 - <<\'PY\'\n'
        host_start = self.script.index(host_marker) + len(host_marker)
        host_source = self.script[
            host_start:self.script.index('\nPY\n)" || blocked', host_start)]
        report_marker = (
            'export SOURCE_HEAD FORMATTER_SHA MODULE_SHA ORACLE_SHA HOST_SHA REPORT\n'
            "python3 - <<'PY'\n")
        report_start = self.script.index(report_marker) + len(report_marker)
        report_source = self.script[
            report_start:self.script.index("\nPY\n", report_start)]

        # Match the production C byte layout and trusted input policy.
        self.assertIn('static const unsigned char prefix[] = "swapz-host-v2";',
                      self.primary)
        self.assertIn('memcpy(identity, prefix, sizeof(prefix));', self.primary)
        self.assertIn('memcpy(identity + sizeof(prefix), product_uuid, 36U);',
                      self.primary)
        self.assertIn('identity[sizeof(prefix) + 36U + i]', self.primary)
        self.assertIn('strcmp(parsed.host_identity_sha256,', self.primary)
        self.assertIn('expected_host_identity_sha256) ||', self.primary)
        for token in (
                "expected_owner = 0",
                "os.O_NOFOLLOW",
                "os.O_NONBLOCK",
                "stat.S_ISREG(before.st_mode)",
                "before.st_nlink != 1",
                "before.st_mode & 0o022",
                '"st_mtime_ns", "st_ctime_ns"',
                'record.endswith(b"\\n")'):
            self.assertIn(token, host_source)
        self.assertNotIn("read_text(", host_source)
        self.assertNotIn(".strip(", host_source)

        with TemporaryDirectory(prefix="swapz-host-contract-") as directory:
            fixture = Path(directory)
            machine_path = fixture / "machine-id"
            dmi_path = fixture / "product_uuid"
            report_path = fixture / "qualification.json"
            host_source = host_source.replace(
                '"/etc/machine-id"', repr(str(machine_path)))
            host_source = host_source.replace(
                '"/sys/class/dmi/id/product_uuid"', repr(str(dmi_path)))
            host_source = host_source.replace(
                "expected_owner = 0", "expected_owner = os.getuid()", 1)
            machine_id = b"ABCDEF0123456789ABCDEF0123456789"
            product_uuid = b"ABCDEF12-3456-7890-ABCD-EF1234567890"
            expected_digest = hashlib.sha256(
                b"swapz-host-v2\0" + product_uuid.lower() +
                machine_id.lower()).hexdigest()

            def run_existing_records():
                environment = os.environ.copy()
                environment["HOST_ARCH"] = "x86_64"
                return subprocess.run(
                    ["python3", "-"], input=host_source, env=environment,
                    capture_output=True, text=True, timeout=5, check=False)

            def run_host_source(machine_record, dmi_record):
                machine_path.unlink(missing_ok=True)
                dmi_path.unlink(missing_ok=True)
                machine_path.write_bytes(machine_record)
                dmi_path.write_bytes(dmi_record)
                machine_path.chmod(0o600)
                dmi_path.chmod(0o600)
                return run_existing_records()

            for machine_record, dmi_record in (
                    (machine_id, product_uuid),
                    (machine_id + b"\n", product_uuid + b"\n"),
                    (machine_id.lower() + b"\n",
                     product_uuid.lower() + b"\n")):
                with self.subTest(valid=(machine_record, dmi_record)):
                    result = run_host_source(machine_record, dmi_record)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), expected_digest)

            for name, machine_record, dmi_record in (
                    ("zero-machine", b"0" * 32, product_uuid),
                    ("short-machine", machine_id[:-1], product_uuid),
                    ("bad-machine-hex", b"G" + machine_id[1:], product_uuid),
                    ("machine-crlf", machine_id + b"\r\n", product_uuid),
                    ("double-machine-newline", machine_id + b"\n\n",
                     product_uuid),
                    ("oversized-machine", machine_id + b"x" * 32,
                     product_uuid),
                    ("zero-dmi", machine_id,
                     b"00000000-0000-0000-0000-000000000000"),
                    ("bad-dmi-hex", machine_id, b"G" + product_uuid[1:]),
                    ("bad-dmi-hyphens", machine_id,
                     product_uuid.replace(b"-", b"")),
                    ("extra-dmi-group", machine_id,
                     b"ABCDEF12-3456-7890-ABCD-1234-EF1234567890"),
                    ("dmi-crlf", machine_id, product_uuid + b"\r\n"),
                    ("double-dmi-newline", machine_id,
                     product_uuid + b"\n\n"),
                    ("oversized-dmi", machine_id, product_uuid + b"xxxx")):
                with self.subTest(malformed=name):
                    result = run_host_source(machine_record, dmi_record)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(result.stderr, "")

            run_host_source(machine_id, product_uuid)
            real_machine = fixture / "real-machine-id"
            machine_path.unlink()
            real_machine.write_bytes(machine_id)
            real_machine.chmod(0o600)
            machine_path.symlink_to(real_machine)
            symlinked = run_existing_records()
            self.assertNotEqual(symlinked.returncode, 0)
            self.assertEqual(symlinked.stdout + symlinked.stderr, "")
            machine_path.unlink()
            real_machine.unlink()
            machine_path.write_bytes(machine_id)
            machine_path.chmod(0o620)
            writable = run_existing_records()
            self.assertNotEqual(writable.returncode, 0)
            self.assertEqual(writable.stdout + writable.stderr, "")
            machine_path.chmod(0o600)
            hardlink = fixture / "machine-id-hardlink"
            os.link(machine_path, hardlink)
            linked = run_existing_records()
            self.assertNotEqual(linked.returncode, 0)
            self.assertEqual(linked.stdout + linked.stderr, "")
            hardlink.unlink()
            machine_path.unlink()
            os.mkfifo(machine_path, 0o600)
            fifo = run_existing_records()
            self.assertNotEqual(fifo.returncode, 0)
            self.assertEqual(fifo.stdout + fifo.stderr, "")
            machine_path.unlink()

            source_sha = "1" * 40
            environment = os.environ.copy()
            environment.update({
                "SOURCE_HEAD": source_sha,
                "FORMATTER_SHA": "2" * 64,
                "MODULE_SHA": "3" * 64,
                "ORACLE_SHA": "4" * 64,
                "HOST_SHA": expected_digest,
                "HOST_ARCH": "x86_64",
                "REPORT": str(report_path),
            })
            generated = subprocess.run(
                ["python3", "-"], input=report_source, env=environment,
                capture_output=True, text=True, timeout=5, check=False)
            self.assertEqual(generated.returncode, 0, generated.stderr)
            payload = report_path.read_bytes()
            report = json.loads(payload)
            self.assertEqual(
                payload,
                (json.dumps(report, sort_keys=True, separators=(",", ":")) +
                 "\n").encode("utf-8"))
            self.assertEqual(report["schema"], "swapz-test-results-v1")
            self.assertEqual(report["host_identity"], {
                "schema": "swapz-host-v1",
                "architecture": "x86_64",
                "id_sha256": expected_digest,
            })
            self.assertEqual(report["kernel_release"], os.uname().release)
            self.assertEqual(report["source_sha"], source_sha)
            self.assertEqual(report["tested_commit_sha"], source_sha)
            self.assertEqual(report["overall"], "PASS")
            self.assertEqual(report["qualification"], "RAM_BACKED_NULL_BLK_ONLY")
            self.assertEqual(len(report["stages"]), 5)
            self.assertTrue(all(stage["status"] == "PASS" and
                                stage["exit_code"] == 0
                                for stage in report["stages"]))
            self.assertEqual(report["qualified_artifacts"]["status"],
                             "AVAILABLE")
            self.assertNotIn(machine_id.lower(), payload)
            self.assertNotIn(product_uuid.lower(), payload)

            parser_source = fixture / "qualification-parser.c"
            parser_binary = fixture / "qualification-parser"
            primary_path = str(PRIMARY).replace("\\", "\\\\").replace('"', '\\"')
            parser_source.write_text(
                f'''#define SWAPZ_PRIMARY_ROOTLESS_TEST 1
#include "{primary_path}"
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv)
{{
    FILE *stream;
    unsigned char *bytes;
    long file_size;
    size_t length;
    struct swapz_primary_qualification qualification;
    int parse_result;
    int parse_errno;

    if (argc != 4)
        return 64;
    stream = fopen(argv[1], "rb");
    if (!stream)
        return 65;
    if (fseek(stream, 0, SEEK_END) != 0 ||
        (file_size = ftell(stream)) <= 0 ||
        fseek(stream, 0, SEEK_SET) != 0) {{
        (void)fclose(stream);
        return 66;
    }}
    length = (size_t)file_size;
    bytes = malloc(length);
    if (!bytes) {{
        (void)fclose(stream);
        return 67;
    }}
    if (fread(bytes, 1, length, stream) != length) {{
        free(bytes);
        (void)fclose(stream);
        return 68;
    }}
    if (fclose(stream) != 0) {{
        free(bytes);
        return 69;
    }}
    errno = 0;
    parse_result = swapz_primary_qualification_parse_json(
        bytes, length, argv[2], argv[3], &qualification);
    parse_errno = errno;
    free(bytes);
    if (parse_result == 0) {{
        puts("ACCEPT");
        return 0;
    }}
    printf("REJECT errno=%d\\n", parse_errno);
    return 1;
}}
''',
                encoding="utf-8")
            # This parser-only harness includes the production translation
            # unit, so unrelated static lifecycle entrypoints are expected to
            # be unused here. Keep every other warning fatal.
            subprocess.run(
                [
                    "cc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra",
                    "-Werror", "-Wno-unused-function", str(parser_source),
                    "-o", str(parser_binary),
                ],
                cwd=ROOT, check=True)
            correct_host = subprocess.run(
                [str(parser_binary), str(report_path), source_sha,
                 expected_digest],
                cwd=ROOT, capture_output=True, text=True, timeout=5,
                check=False)
            self.assertEqual(correct_host.returncode, 0, correct_host.stderr)
            self.assertEqual(correct_host.stdout, "ACCEPT\n")
            wrong_host = subprocess.run(
                [str(parser_binary), str(report_path), source_sha, "f" * 64],
                cwd=ROOT, capture_output=True, text=True, timeout=5,
                check=False)
            self.assertEqual(wrong_host.returncode, 1, wrong_host.stderr)
            self.assertEqual(
                wrong_host.stdout, f"REJECT errno={errno.EINVAL}\n")


    def test_arm64_private_ram_host_identity_without_dmi(self):
        """A machine-only ARM64 digest cannot become physical qualification."""
        import hashlib
        import json

        host_marker = 'HOST_SHA="$(python3 - <<\'PY\'\n'
        host_start = self.script.index(host_marker) + len(host_marker)
        host_source = self.script[
            host_start:self.script.index('\nPY\n)" || blocked', host_start)]
        report_marker = (
            'export SOURCE_HEAD FORMATTER_SHA MODULE_SHA ORACLE_SHA HOST_SHA REPORT\n'
            "python3 - <<'PY'\n")
        report_start = self.script.index(report_marker) + len(report_marker)
        report_source = self.script[
            report_start:self.script.index("\nPY\n", report_start)]
        with TemporaryDirectory(prefix="swapz-arm64-private-host-") as directory:
            fixture = Path(directory)
            machine_path = fixture / "machine-id"
            missing_dmi_path = fixture / "no-dmi"
            report_path = fixture / "qualification.json"
            host_source = host_source.replace(
                '"/etc/machine-id"', repr(str(machine_path)))
            host_source = host_source.replace(
                '"/sys/class/dmi/id/product_uuid"',
                repr(str(missing_dmi_path)))
            host_source = host_source.replace(
                "expected_owner = 0", "expected_owner = os.getuid()", 1)
            machine = b"ABCDEF0123456789ABCDEF0123456789"
            digest = hashlib.sha256(
                b"swapz-nullblk-arm64-v1\0" + machine.lower()).hexdigest()
            environment = os.environ.copy()
            environment.update({
                "HOST_ARCH": "aarch64", "SOURCE_HEAD": "1" * 40,
                "FORMATTER_SHA": "2" * 64, "MODULE_SHA": "3" * 64,
                "ORACLE_SHA": "4" * 64, "HOST_SHA": digest,
                "REPORT": str(report_path),
            })
            machine_path.write_bytes(machine + b"\n")
            machine_path.chmod(0o600)
            def run_host_source():
                return subprocess.run(
                    ["python3", "-"], input=host_source, env=environment,
                    capture_output=True, text=True, timeout=5, check=False)
            accepted = run_host_source()
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertEqual(accepted.stdout, digest + "\n")
            for invalid in (b"0" * 32, machine + b"\r\n",
                            machine[:-1], machine + b"\n\n"):
                machine_path.write_bytes(invalid)
                refused = run_host_source()
                self.assertNotEqual(refused.returncode, 0)
                self.assertEqual(refused.stdout + refused.stderr, "")
            machine_path.write_bytes(machine)
            result = subprocess.run(
                ["python3", "-"], input=report_source, env=environment,
                capture_output=True, text=True, timeout=5, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(report_path.read_bytes())
            self.assertEqual(report["host_identity"], {
                "schema": "swapz-host-v1", "architecture": "aarch64",
                "id_sha256": digest,
            })
            self.assertNotIn(machine.lower(), report_path.read_bytes())

        # Production's host parser and DMI digest remain distinct.
        self.assertIn("#ifdef SWAPZ_PRIMARY_OWNED_NULLBLK_TEST\n"
                      "\t/* An ARM64 report", self.primary)
        self.assertIn('strcmp(system.machine, "x86_64")', self.primary)
        self.assertIn('static const unsigned char prefix[] = "swapz-host-v2";',
                      self.primary)

    def test_rootless_prepare_refusal_keeps_blocked_and_fail_distinct(self):
        verifier_start = self.script.index("verify_prepare_failure_diagnostic() {")
        verifier = self.script[
            verifier_start:self.script.index("\n}", verifier_start) + 2]
        prepare_start = self.script.index(
            'note "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=prepare"')
        prepare_path = self.script[
            prepare_start:self.script.index(
                'printf \'%s\\n\' "$prepare_output"', prepare_start)]
        fake_commands = r'''
set -Eeuo pipefail
fail() { printf 'FAIL_PRIMARY_NULLBLK_LIFECYCLE: %s\n' "$*" >&2; exit 1; }
blocked() { printf 'BLOCKED_PRIMARY_NULLBLK_LIFECYCLE: %s\n' "$*" >&2; exit 2; }
note() { printf '%s\n' "$*"; }
timeout() {
    if [[ "$*" == *" primary prepare" ]]; then
        printf '%s\n' "$INJECTED_PREPARE_OUTPUT"
        return 2
    fi
    if [[ "$*" == *" primary plan" ]]; then
        printf '%s\n' '{"plan":"read-only"}'
        return 0
    fi
    return 1
}
CONTROL=/private-mock-only
'''
        for phase, error_number, claim, expected_status, marker in (
                ("qualification-report-read", errno.EINVAL, "claim=none", 2,
                 "BLOCKED_PRIMARY_NULLBLK_LIFECYCLE:"),
                ("global-mutation-lock", errno.EBUSY, "", 2,
                 "BLOCKED_PRIMARY_NULLBLK_LIFECYCLE:"),
                ("manifest-write", errno.EIO,
                 "claim=retained target_unchanged=true", 1,
                 "FAIL_PRIMARY_NULLBLK_LIFECYCLE:")):
            with self.subTest(phase=phase):
                description = os.strerror(error_number)
                diagnostic = (
                    f"PRIMARY_PREPARE=FAILED phase={phase} "
                    f"errno={error_number} error={description}" +
                    (f" {claim}" if claim else ""))
                environment = os.environ.copy()
                environment["INJECTED_PREPARE_OUTPUT"] = (
                    diagnostic + "\nBLOCKED: primary-swap preparation failed: " +
                    description)
                result = subprocess.run(
                    ["bash", "-c",
                     fake_commands + verifier + "\n" + prepare_path],
                    env=environment, cwd=ROOT, capture_output=True,
                    text=True, timeout=10, check=False)
                self.assertEqual(result.returncode, expected_status,
                                 result.stdout + result.stderr)
                self.assertIn(diagnostic, result.stderr)
                self.assertIn(marker, result.stderr)
                self.assertIn("PRIMARY_PREPARE_DIAGNOSTIC_PLAN=available",
                              result.stdout)
                self.assertNotIn("PASS_", result.stdout + result.stderr)

    def test_rootless_fresh_config_does_not_adopt_foreign_and_missing_alias_blocks(self):
        creation_start = self.script.index(
            'CONFIGNAME="nullb-swapz-$TOKEN"')
        creation = self.script[
            creation_start:self.script.index(
                'CONFIG_IDENTITY="$(stat -c', creation_start)]
        self.assertIn('mkdir -- "$CONFIG" 2>/dev/null || blocked', creation)
        self.assertNotIn("rmdir", creation)
        self.assertNotIn("power", creation)
        with TemporaryDirectory(prefix="swapz-foreign-nullblk-") as directory:
            configfs = Path(directory)
            foreign_name = "nullb-swapz-" + "f" * 16
            foreign = configfs / foreign_name
            foreign.mkdir()
            sentinel = foreign / "foreign"
            sentinel.write_text("do-not-touch\n", encoding="ascii")
            original_inode = foreign.stat().st_ino

            def attempt_create(token):
                program = (
                    "set -Eeuo pipefail\n"
                    'blocked() { printf "BLOCKED_PRIMARY_NULLBLK_LIFECYCLE: %s\\n" "$*" >&2; exit 2; }\n'
                    f"CONFIGFS={shlex.quote(str(configfs))}\n"
                    f"TOKEN={token}\n" + creation)
                return subprocess.run(
                    ["bash", "-c", program], capture_output=True,
                    text=True, timeout=5, check=False)

            fresh = attempt_create("a" * 16)
            self.assertEqual(fresh.returncode, 0, fresh.stderr)
            self.assertTrue((configfs / ("nullb-swapz-" + "a" * 16)).is_dir())
            conflict = attempt_create("f" * 16)
            self.assertEqual(conflict.returncode, 2, conflict.stderr)
            self.assertIn("BLOCKED_PRIMARY_NULLBLK_LIFECYCLE:", conflict.stderr)
            self.assertNotIn(str(foreign), conflict.stderr)
            self.assertEqual(foreign.stat().st_ino, original_inode)
            self.assertEqual(sentinel.read_text(encoding="ascii"),
                             "do-not-touch\n")

            alias_start = self.script.index(
                'if [[ -e "$BY_PARTUUID" || -L "$BY_PARTUUID" ]]; then\n'
                '\tudev_alias_verified || fail "by-PARTUUID alias is not '
                'udev-recorded for the owned partition"',
                self.script.index("udev_alias_verified() {"))
            alias_check = self.script[
                alias_start:self.script.index('\nmkswap "$PARTITION"', alias_start)]
            missing_alias = configfs / "missing-by-partuuid"
            private_evidence = configfs / "private-evidence"
            private_evidence.mkdir(mode=0o700)
            private_rule = configfs / "owned-fixture.rules"
            private_rule.write_text(
                'ACTION=="add", ENV{ID_PART_ENTRY_UUID}=="7fb9401d-04"\n',
                encoding="ascii")
            program = (
                "set -Eeuo pipefail\n"
                'fail() { printf "FAIL_PRIMARY_NULLBLK_LIFECYCLE: %s\\n" "$*" >&2; exit 1; }\n'
                'blocked() { printf "BLOCKED_PRIMARY_NULLBLK_LIFECYCLE: %s\\n" "$*" >&2; exit 2; }\n'
                'note() { printf "%s\\n" "$*"; }\n'
                'udevadm() { return 1; }\n'
                f"BY_PARTUUID={shlex.quote(str(missing_alias))}\n"
                f"EVIDENCE_BASE={shlex.quote(str(private_evidence))}\n"
                f"UDEV_RULE={shlex.quote(str(private_rule))}\n"
                f"PART_SYSFS={shlex.quote(str(configfs))}\n"
                "QUARANTINE=0\nPARTUUID=7fb9401d-04\n"
                "UDEV_DEVPATH=/mock-only\n" + alias_check)
            denied = subprocess.run(
                ["bash", "-c", program], capture_output=True,
                text=True, timeout=5, check=False)
            self.assertEqual(denied.returncode, 2, denied.stderr)
            self.assertIn("BLOCKED_PRIMARY_NULLBLK_LIFECYCLE:", denied.stderr)
            self.assertIn("phase=udev-alias-publication", denied.stderr)
            self.assertIn("observed=publication-unproven", denied.stderr)
            self.assertIn("ownership=claimed", denied.stderr)
            self.assertNotIn("FAIL_PRIMARY_NULLBLK_LIFECYCLE:", denied.stderr)
            self.assertNotIn("PASS_", denied.stdout + denied.stderr)
            self.assertIn("UDEV_PARTUUID_DIAGNOSTIC=private", denied.stdout)
            retention = alias_check.index("\tRETAIN_PRIVATE_EVIDENCE=1")
            refusal = alias_check.index(
                '\tblocked "phase=udev-alias-publication')
            self.assertLess(retention, refusal)
            self.assertNotIn("\tQUARANTINE=1", alias_check)
            for identifier in ("7fb9401d-04", "/mock-only", str(configfs),
                               str(private_rule)):
                self.assertNotIn(identifier, denied.stdout + denied.stderr)
            self.assertIn("7fb9401d-04", (
                private_evidence / "udev-alias-diagnostic.log").read_text())
            self.assertFalse(missing_alias.exists())
            self.assertEqual(sentinel.read_text(encoding="ascii"),
                             "do-not-touch\n")

    def test_rootless_failed_owned_partition_write_is_fail(self):
        ownership_claim = self.script.index("OWN_NULL=1")
        start = self.script.index('if sfdisk --lock --wipe always "$LOWER"')
        self.assertLess(ownership_claim, start)
        end = self.script.index("\nfi", start) + len("\nfi")
        helper_start = self.script.index("owned_setup_failed() {")
        helper_end = self.script.index("\n}", helper_start) + len("\n}")
        # The extracted sfdisk here-document needs its synthetic disk ID;
        # otherwise nounset exits during redirection before the failure handler.
        with TemporaryDirectory(prefix="swapz-partition-first-exit-") as directory:
            fixture = Path(directory)
            owned_node = fixture / "owned-nullblk-fixture"
            foreign_node = fixture / "foreign-nullblk-fixture"
            owned_bytes = b"owned-header-unchanged\n"
            foreign_bytes = b"foreign-header-unchanged\n"
            owned_node.write_bytes(owned_bytes)
            foreign_node.write_bytes(foreign_bytes)
            shell = (
                "set -Eeuo pipefail\n"
                f"LOWER={shlex.quote(str(owned_node))}\n"
                "DISK_ID=1a2b3c4d\n"
                'fail() { printf "FAIL_PRIMARY_NULLBLK_LIFECYCLE: %s\\n" "$*" >&2; exit 1; }\n'
                'blocked() { printf "BLOCKED_PRIMARY_NULLBLK_LIFECYCLE: %s\\n" "$*" >&2; exit 2; }\n'
                'sfdisk() { [[ $# -eq 4 && "$1" == --lock && "$2" == --wipe && '
                '"$3" == always && "$4" == "$LOWER" ]] || return 37; return 11; }\n'
                + self.script[helper_start:helper_end] + "\n"
                + self.script[start:end] + "\n"
            )
            result = subprocess.run(
                ["bash", "-c", shell], capture_output=True,
                text=True, timeout=5, check=False)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn(
                "phase=partition-table-write original_errno=unavailable "
                "original_exit=11 expected=owned-setup-operation-success "
                "observed=command-failed ownership=claimed "
                "next=inspect-private-evidence", result.stderr)
            self.assertNotIn("BLOCKED_PRIMARY_NULLBLK_LIFECYCLE", result.stderr)
            self.assertNotIn(str(owned_node), result.stdout + result.stderr)
            self.assertNotIn(str(foreign_node), result.stdout + result.stderr)
            self.assertEqual(owned_node.read_bytes(), owned_bytes)
            self.assertEqual(foreign_node.read_bytes(), foreign_bytes)

        # Every other owned setup command must similarly capture its failing
        # exit at the immediate branch, not after ! or a secondary probe.
        setup_calls = re.findall(
            r'owned_setup_failed "([^"]+)"([^\n]*)', self.script)
        self.assertEqual(len(setup_calls), 9)
        for phase, arguments in setup_calls:
            with self.subTest(phase=phase):
                self.assertEqual(arguments.strip(), '"$?"')

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
                "RETAIN_PRIVATE_EVIDENCE": "0",
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
            '\t\tif ! udevadm settle',
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
            "assert_owned_transaction_records",
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
                elif scenario == "changed_power_inode":
                    (config / "power").rename(config / "retained-original-power")
                    (config / "power").write_text("1\n", encoding="ascii")
                    self.assertNotEqual(
                        (config / "power").stat().st_ino, power_identity.st_ino)
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
                elif scenario == "stale_state":
                    recovery = fixture / "private-evidence"
                    recovery.mkdir()
                    state_file = recovery / "primary-state.json"
                    state_file.write_text(
                        '{"schema":"swapz-primary-state-v1","run_id":"' +
                        "c" * 32 + '","stage":"COMPLETE",'
                        '"recovery_previous_stage":null}\n',
                        encoding="ascii")
                    state_file.chmod(0o600)
                    consumed_file = recovery / (
                        "consumed-" + "b" * 32 + ".json")
                    consumed_file.write_text(
                        '{"major":240,"minor":8,'
                        '"partuuid":"7fb9401d-04","run_id":"' +
                        "b" * 32 + '"}\n',
                        encoding="ascii")
                    consumed_file.chmod(0o600)

                replacements = (
                    ("/sys/dev/block", str(sysdev)),
                    ("/sys/block", str(sysblock)),
                    ('"/dev/$DISK"', '"$FAKE_DEV/$DISK"'),
                    ('"/dev/$PART_NAME"', '"$FAKE_DEV/$PART_NAME"'),
                )
                fixture_helpers = helpers
                for before, after in replacements:
                    fixture_helpers = fixture_helpers.replace(before, after)
                fixture_helpers = fixture_helpers.replace(
                    "identity.st_uid != 0",
                    f"identity.st_uid != {os.getuid()}")
                fixture_cleanup = cleanup.replace(
                    "/sys/module/dm_swapz", str(fixture / "absent-module"))
                fixture_cleanup = fixture_cleanup.replace("/sys/block", str(sysblock))
                fixture_cleanup = fixture_cleanup.replace(
                    "identity.st_uid == 0",
                    f"identity.st_uid == {os.getuid()}")

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
                    "PARTUUID": "7fb9401d-04",
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
                    "RETAIN_PRIVATE_EVIDENCE": "0",
                    "UDEV_RULE_CREATED": "0",
                    "UDEV_RULES_DIR_CREATED": "0",
                    "TEST_BASE_CREATED": "0",
                    "TEST_BASE": fixture / "private-evidence",
                    "BY_PARTUUID": "",
                    "RMDIR_FAIL": "1" if scenario == "rmdir_failure" else "0",
                    "STALE_STATE": "1" if scenario == "stale_state" else "0",
                    "UDEV_SETTLE_FAIL": (
                        "1" if scenario == "udev_settle_failure" else "0"),
                    "MAPPER_FOREIGN": "1" if scenario == "foreign_mapper" else "0",
                }
                setup = "\n".join(
                    f"{key}={shlex.quote(str(value))}"
                    for key, value in settings.items())
                fake_commands = r'''
note() { printf '%s\n' "$*"; }
state_stage() {
    [[ "$STALE_STATE" != 1 ]] || printf 'COMPLETE\n'
}
swapz_swap_inventory_identity() { printf 'unchanged\n'; }
mapper_absence_proven() { return 0; }
findmnt() { return 1; }
udevadm() { [[ "$1" != settle || "$UDEV_SETTLE_FAIL" != 1 ]]; }
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

        for scenario in ("replacement", "changed_power_inode", "missing_index",
                         "wrong_index",
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

        stale_state, power, exists, actions = run_fixture("stale_state")
        self.assertEqual(stale_state.returncode, 1)
        self.assertEqual(power, "1")
        self.assertTrue(exists)
        self.assertEqual(actions, [])
        self.assertIn(
            "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE="
            "unfinished_or_ambiguous_durable_state", stale_state.stdout)
        self.assertIn(
            "PRIMARY_NULLBLK_LIFECYCLE_EVIDENCE_RETAINED=private",
            stale_state.stdout)
        self.assertNotIn(
            "noncanonical_consumed_owner_record", stale_state.stdout)
        self.assertNotIn("command not found", stale_state.stderr)

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


        refused_blocked, power, exists, actions = run_fixture(
            "replacement", original_status=2)
        self.assertEqual(refused_blocked.returncode, 2)
        self.assertEqual(power, "1")
        self.assertTrue(exists)
        self.assertEqual(actions, [])

        settle_failure, power, exists, actions = run_fixture(
            "udev_settle_failure")
        self.assertEqual(settle_failure.returncode, 1)
        self.assertIsNone(power)
        self.assertFalse(exists)
        self.assertEqual(actions, ["rmdir"])
        self.assertIn(
            "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE="
            "udev_settle_failed_after_device_removal", settle_failure.stdout)
        self.assertIn(
            "PRIMARY_NULLBLK_LIFECYCLE_EVIDENCE_RETAINED=private",
            settle_failure.stdout)

    def test_cleanup_retains_private_diagnostics_without_preemptive_device_quarantine(self):
        cleanup = self.script[
            self.script.index("cleanup() {"):
            self.script.index("trap cleanup EXIT")]
        self.assertIn(
            '(( ! RETAIN_PRIVATE_EVIDENCE )); then', cleanup)
        self.assertIn(
            'if (( QUARANTINE || RETAIN_PRIVATE_EVIDENCE )); then', cleanup)
        alias_start = self.script.index(
            'if [[ -e "$BY_PARTUUID" || -L "$BY_PARTUUID" ]]; then',
            self.script.index("udev_alias_verified() {"))
        alias_end = self.script.index('\nmkswap "$PARTITION"', alias_start)
        alias_path = self.script[alias_start:alias_end]
        self.assertIn("RETAIN_PRIVATE_EVIDENCE=1", alias_path)
        self.assertNotIn("QUARANTINE=1", alias_path)

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
