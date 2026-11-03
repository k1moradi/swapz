#!/usr/bin/env python3
"""Rootless contract checks for the Agent 7 owned-null_blk qualifier."""

from pathlib import Path
from tempfile import TemporaryDirectory
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
            "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION_RECOVERY=cases:15",
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

    def test_interruption_evidence_is_durable_and_unique(self):
        self.assertIn("capture_interruption_evidence() {", self.script)
        self.assertIn('capture_interruption_evidence "$phase"', self.script)
        self.assertIn('snapshot_name = f"{run_id}-{phase}-{name}"', self.script)
        self.assertIn("os.fsync(snapshot_fd)", self.script)
        self.assertIn("os.fsync(evidence_fd)", self.script)
        self.assertIn('QUARANTINE=1\n\t\tfail "$phase could not preserve', self.script)

    def test_missing_swap_path_cannot_be_counted_as_absent(self):
        self.assertIn('[[ -e "$swap_path" ]] || return 1', self.script)

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

    def test_fault_shim_executes_eleven_rootless_boundary_cases(self):
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
