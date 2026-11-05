#!/usr/bin/env python3
"""Rootless reporting regressions; reuse the existing systemd runtime-health fixture.

Execute directly after the standard systemd/package test. No physical operations.
"""

from __future__ import annotations

import runpy
import unittest
from pathlib import Path


SYSTEMD_TEST = Path(__file__).with_name("swapz-primary-systemd-test.py")
fixture_module = runpy.run_path(str(SYSTEMD_TEST), run_name="runtime_health_fixture")
RuntimeHealthFixture = fixture_module["RuntimeHealthTests"]


class RuntimeHealthDiagnosticTests(unittest.TestCase):
    def setUp(self) -> None:
        # Reuse the currently maintained rootless mocks without changing their owner.
        self.fixture = RuntimeHealthFixture("test_healthy_snapshot_reports_capacity_and_identity")
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def assert_diagnostic(
        self, result, expected_status: int, health: str, reason: str, phase: str,
        check: str, next_action: str,
    ) -> None:
        self.assertEqual(result.returncode, expected_status, result.stderr)
        self.assertIn(f"SWAPZ_RUNTIME_HEALTH={health}", result.stderr)
        self.assertIn(reason, result.stderr)
        self.assertIn(f"phase={phase} expected=", result.stderr)
        self.assertIn(f"check={check} retained_state=unchanged", result.stderr)
        self.assertIn(f"next={next_action}", result.stderr)
        self.assertNotIn(str(self.fixture.recovery), result.stderr)
        self.assertNotIn(str(self.fixture.etc), result.stderr)
        self.assertNotIn("dmsetup remove", result.stderr)
        self.assertNotIn("swapoff", result.stderr)

    def test_success_has_no_new_failure_report(self) -> None:
        result = self.fixture.run_helper("once")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=HEALTHY", result.stderr)
        self.assertNotIn("SWAPZ_RUNTIME_OBSERVER", result.stderr)

    def test_missing_selected_device_has_presence_and_inspection_proof(self) -> None:
        partuuid = fixture_module["PARTUUID"]
        (self.fixture.dev / "disk" / "by-partuuid" / partuuid).unlink()
        result = self.fixture.run_helper("once")
        self.assert_diagnostic(result, 1, "FAIL", "backing_device_unavailable",
                               "selected_backing", "selected_device_presence",
                               "inspect_selected_partition_read_only")

    def test_incomplete_recovery_record_preserves_evidence(self) -> None:
        partuuid = fixture_module["PARTUUID"]
        (self.fixture.recovery / f"partition-{partuuid}.active").unlink()
        result = self.fixture.run_helper("once")
        self.assert_diagnostic(result, 1, "FAIL", "active_transaction_identity_invalid",
                               "active_transaction", "active_owner_claim",
                               "inspect_recovery_evidence_read_only")

    def test_missing_mapper_has_no_removal_advice(self) -> None:
        (self.fixture.dev / "mapper" / "swapz-primary").unlink()
        result = self.fixture.run_helper("once")
        self.assert_diagnostic(result, 1, "FAIL", "mapper_missing",
                               "mapper_presence", "mapper_device_presence",
                               "inspect_dmsetup_info_read_only")

    def test_stale_mapper_dm_name_has_identity_proof(self) -> None:
        (self.fixture.sys / "dev" / "block" / "253:0" / "dm" / "name").write_text(
            "stale-other-mapper\n", encoding="ascii"
        )
        result = self.fixture.run_helper("once")
        self.assert_diagnostic(result, 1, "FAIL", "mapper_device_identity_invalid",
                               "mapper_device_identity", "mapper_dm_name",
                               "inspect_dmsetup_info_read_only")

    def test_failed_unit_reports_originating_state(self) -> None:
        env = self.fixture.env.copy()
        env["MOCK_SYSTEMD_ACTIVE_STATE"] = "failed"
        result = self.fixture.run_helper("once", env)
        self.assert_diagnostic(result, 1, "FAIL", "mapper_service_not_active",
                               "mapper_service_state", "mapper_active_state",
                               "inspect_systemctl_show_read_only")
        self.assertIn("command=systemctl_show command_status=0", result.stderr)
        self.assertIn("service_state=observed", result.stderr)

    def test_failed_service_result_is_attributed(self) -> None:
        systemctl_mock = self.fixture.bin / "systemctl"
        original_mock = systemctl_mock.read_text(encoding="utf-8")
        self.assertIn("Result) echo success ;;", original_mock)
        systemctl_mock.write_text(
            original_mock.replace("Result) echo success ;;", "Result) echo failed ;;"),
            encoding="utf-8",
        )
        result = self.fixture.run_helper("once")
        self.assert_diagnostic(result, 1, "FAIL", "mapper_service_failed",
                               "mapper_service_result", "mapper_result",
                               "inspect_systemctl_show_read_only")
        self.assertIn("phase=passive_swap_unit_result expected=", result.stderr)

    def test_ambiguous_inventory_remains_degraded(self) -> None:
        existing = (self.fixture.proc / "swaps").read_text(encoding="ascii")
        (self.fixture.proc / "swaps").write_text(
            existing + "/dev/dm-7 partition 10000 500 -1\n", encoding="ascii"
        )
        result = self.fixture.run_helper("once")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=DEGRADED", result.stderr)
        self.assertIn("swap_block_identity_unavailable", result.stderr)
        self.assertIn("phase=swap_inventory expected=", result.stderr)
        self.assertIn("retained_state=unchanged", result.stderr)

    def test_incomplete_status_is_degraded_not_failed(self) -> None:
        env = self.fixture.env.copy()
        env["MOCK_DM_STATUS_UNAVAILABLE"] = "1"
        result = self.fixture.run_helper("once", env)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=DEGRADED", result.stderr)
        self.assertIn("mapper_status_unavailable", result.stderr)
        self.assertIn("phase=mapper_status expected=", result.stderr)
        self.assertIn("retained_state=unchanged", result.stderr)

    def test_kernel_warning_remains_warn(self) -> None:
        env = self.fixture.env.copy()
        env["MOCK_JOURNAL"] = "DM-SWAPZ: lower I/O error\n"
        result = self.fixture.run_helper("once", env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=WARN", result.stderr)
        self.assertIn("phase=kernel_log", result.stderr)
        self.assertIn("retained_state=unchanged", result.stderr)

    def test_invalid_mapper_table_contract_is_attributed(self) -> None:
        dmsetup_mock = self.fixture.bin / "dmsetup"
        original_mock = dmsetup_mock.read_text(encoding="utf-8")
        valid_table = "0 216641536 swapz 8:1 0 64 0 2 0 1 0 0"
        self.assertIn(valid_table, original_mock)
        dmsetup_mock.write_text(
            original_mock.replace(valid_table, valid_table[:-1] + "1"),
            encoding="utf-8",
        )
        result = self.fixture.run_helper("once")
        self.assert_diagnostic(result, 1, "FAIL", "mapper_table_invalid",
                               "mapper_table", "mapper_table_contract",
                               "inspect_dmsetup_table_read_only")

    def test_mapper_backing_identity_mismatch_is_attributed(self) -> None:
        dmsetup_mock = self.fixture.bin / "dmsetup"
        original_mock = dmsetup_mock.read_text(encoding="utf-8")
        valid_table = "0 216641536 swapz 8:1 0 64 0 2 0 1 0 0"
        self.assertIn(valid_table, original_mock)
        dmsetup_mock.write_text(
            original_mock.replace(valid_table, valid_table.replace("8:1", "8:2")),
            encoding="utf-8",
        )
        result = self.fixture.run_helper("once")
        self.assert_diagnostic(result, 1, "FAIL", "mapper_backing_identity_mismatch",
                               "mapper_backing", "mapper_backing_identity",
                               "inspect_dmsetup_table_and_selected_identity_read_only")

    def test_gc_reserve_exhaustion_is_attributed(self) -> None:
        env = self.fixture.env.copy()
        env["MOCK_DM_STATUS"] = (
            "0 216641536 swapz failed=0 error=0 flush_err=0 "
            "segment_discards_failed=0 upper_write_completed_err=0 "
            "endio_write_seen_err=0 endio_write_forced_err=0 "
            "gc_victims=5 gc_pages=20 gc_no_headroom_skips=0 "
            "gc_reserve_segments_initial=2 gc_reserve_segments_current=0 "
            "gc_destination_advances=1 window_gc_pressure=1"
        )
        result = self.fixture.run_helper("once", env)
        self.assert_diagnostic(result, 1, "FAIL", "gc_reserve_exhausted",
                               "gc_reserve", "gc_reserve_roles",
                               "inspect_dmsetup_status_read_only")

    def test_missing_primary_swap_row_is_attributed(self) -> None:
        (self.fixture.proc / "swaps").write_text(
            "Filename Type Size Used Priority\n", encoding="ascii"
        )
        result = self.fixture.run_helper("once")
        self.assert_diagnostic(result, 1, "FAIL", "mapper_swap_inventory_invalid",
                               "swap_inventory", "primary_mapper_count",
                               "inspect_proc_swaps_and_sysfs_read_only")

    def test_systemctl_probe_status_survives_degraded_observation(self) -> None:
        systemctl_mock = self.fixture.bin / "systemctl"
        original_mock = systemctl_mock.read_text(encoding="utf-8")
        active_state_line = 'ActiveState) echo "\${MOCK_SYSTEMD_ACTIVE_STATE:-active}" ;;'
        self.assertIn(active_state_line, original_mock)
        systemctl_mock.write_text(
            original_mock.replace(
                active_state_line,
                'ActiveState)\n'
                '    [ "\${MOCK_ACTIVE_STATE_EXIT:-0}" = 0 ] || '
                'exit "$MOCK_ACTIVE_STATE_EXIT"\n'
                '    echo "\${MOCK_SYSTEMD_ACTIVE_STATE:-active}" ;;',
            ),
            encoding="utf-8",
        )
        env = self.fixture.env.copy()
        env["MOCK_ACTIVE_STATE_EXIT"] = "7"
        result = self.fixture.run_helper("once", env)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=DEGRADED", result.stderr)
        self.assertIn("mapper_service_state_unavailable", result.stderr)
        self.assertIn(
            "phase=mapper_service_state expected=active_service "
            "observed=probe_failed command=systemctl_show command_status=7",
            result.stderr,
        )
        self.assertIn("retained_state=unchanged", result.stderr)
        self.assertNotIn("dmsetup remove", result.stderr)
        self.assertNotIn("swapoff", result.stderr)

    def test_swap_capacity_warning_has_read_only_inspection(self) -> None:
        primary_path = self.fixture.dev / "mapper" / "swapz-primary"
        (self.fixture.proc / "swaps").write_text(
            "Filename Type Size Used Priority\n"
            f"{primary_path} partition 108320764 100000000 -1\n",
            encoding="ascii",
        )
        result = self.fixture.run_helper("once")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=WARN", result.stderr)
        self.assertIn("swap_capacity_low", result.stderr)
        self.assertIn(
            "phase=swap_capacity expected=below_ninety_percent_occupancy "
            "observed=high_occupancy",
            result.stderr,
        )
        self.assertIn("next=inspect_proc_swaps_read_only", result.stderr)
        self.assertIn("retained_state=unchanged", result.stderr)

    def test_sustained_gc_stall_has_structured_stop_inspection(self) -> None:
        env = self.fixture.env.copy()
        env["MOCK_DM_STALL_COUNTER_FILE"] = str(self.fixture.root / "gc-stall-counter")
        env["SWAPZ_PRIMARY_TEST_MAX_POLLS"] = "4"
        env["SWAPZ_PRIMARY_TEST_STALL_POLLS"] = "3"
        result = self.fixture.run_helper("monitor", env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=FAIL", result.stderr)
        self.assertIn("failures=sustained_gc_stall", result.stderr)
        self.assertIn(
            "phase=gc_progress expected=pressure_has_forward_progress "
            "observed=sustained_stall",
            result.stderr,
        )
        self.assertIn("check=gc_stall_progress retained_state=unchanged", result.stderr)
        self.assertIn(
            "next=inspect_dmsetup_status_and_normal_primary_stop_read_only",
            result.stderr,
        )
        self.assertNotIn("dmsetup remove", result.stderr)
        self.assertNotIn("swapoff", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
