#!/usr/bin/env python3
"""Rootless contract checks for the Agent 7 owned-null_blk qualifier."""

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tests/tools/qualify-primary-lifecycle-nullblk.sh"
SHIM = ROOT / "tests/tools/primary-lifecycle-fault-shim.c"
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
        self.assertNotIn("SWAPZ_PRIMARY_TEST_FSYNC_FAIL_CALL", self.primary)

    def test_all_native_interruption_and_negative_cases_are_declared(self):
        for phase in (
            "start-starting",
            "start-module-loaded",
            "start-mapper-resumed",
            "start-swapon",
            "stop-stopping",
            "stop-swapoff",
        ):
            self.assertIn(phase, self.script)
        for case in (
            "swapon-eintr-applied",
            "swapon-eintr-noeffect",
            "post-swapon-inventory-eio",
            "swapoff-eintr-applied",
            "swapoff-eintr-noeffect",
            "swapoff-ebusy-noeffect",
            "post-swapoff-inventory-eio",
            "state-dir-fsync",
            "stale-run-id",
            "lost-state-provenance",
            "wrong-mapper-identity",
        ):
            self.assertIn(case, self.script)
        self.assertIn(
            "PASS_LOADED_PRIMARY_NULLBLK_NEGATIVE_RECOVERY=cases:11",
            self.script)

    def test_interruption_oracle_proves_exact_mapper_and_repeat_recovery(self):
        self.assertIn('[[ "$mapper_uuid" == "SWAPZ-PRIMARY-$RUN_ID" ]]', self.script)
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

    def test_fault_shim_is_warning_clean(self):
        subprocess.run(
            [
                "cc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
                "-fsyntax-only", str(SHIM),
            ],
            cwd=ROOT,
            check=True,
        )

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
