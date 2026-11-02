#!/usr/bin/env python3
"""Rootless lifecycle tests for the owner-authorized live-swap supervisor."""
import argparse
import time
import hashlib
import importlib.util
import itertools
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/live-swap-supervisor.py"
SPEC = importlib.util.spec_from_file_location("live_swap_supervisor", SCRIPT)
supervisor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(supervisor)

HEAD = "c" * 40
RUN_ID = "d" * 32
REAL_MKDIR = os.mkdir
PRESSURE_OK = json.dumps({"verified_pages": supervisor.PRESSURE_PAGES,
                          "mismatches": 0})
HIGH_MEMORY = {
    "mem_available_bytes": 8 * 1024**3,
    "mem_total_bytes": 16 * 1024**3,
    "ram_used_percent": 30.0,
    "cgroup_headroom_bytes": None,
    "psi_some_avg10": 0.0,
    "psi_full_avg10": 0.0,
}
LOW_MEMORY = {
    "mem_available_bytes": 1024,
    "mem_total_bytes": 16 * 1024**3,
    "ram_used_percent": 99.0,
    "cgroup_headroom_bytes": 1024,
    "psi_some_avg10": 20.0,
    "psi_full_avg10": 10.0,
}


class FakeChild:
    """Stands in for subprocess.Popen in pressure-workload orchestration tests."""

    def __init__(self, returncode, stdout="", stderr="", running=False):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._running = running
        self.killed = False

    def poll(self):
        return None if self._running else self.returncode

    def kill(self):
        self.killed = True
        self._running = False
        self.returncode = -9

    def communicate(self, timeout=None):
        del timeout
        return self._stdout, self._stderr


class FakeOps:
    def __init__(self, *, fail_phase=None, stop_after_format=False,
                 bad_target_after_mapping=False, low_memory=False,
                 bad_formatted_header=False, pressure_mode="pass"):
        self.original = b"O" * supervisor.PAGE_BYTES
        self.formatted = b"S" * supervisor.PAGE_BYTES
        self.header = self.original
        self.original_active = True
        self.mapper_active = False
        self.mapper_exists = False
        self.module = False
        self.mapper_name = None
        self.mapper_uuid = None
        self.mapper_used_kib = 0
        self.fail_phase = fail_phase
        self.stop_after_format = stop_after_format
        self.bad_target_after_mapping = bad_target_after_mapping
        self.low_memory = low_memory
        self.bad_formatted_header = bad_formatted_header
        self.pressure_mode = pressure_mode
        self.pressure_calls = 0
        self.observations_taken = 0
        self.target_valid = True
        self.mutations = []

    def _target(self):
        return {
            "device": supervisor.DEVICE_PATH,
            "major": supervisor.DEVICE_MAJOR,
            "minor": supervisor.DEVICE_MINOR,
            "partuuid": supervisor.DEVICE_PARTUUID,
            "size_bytes": supervisor.DEVICE_SIZE_BYTES,
            "swap_path": supervisor.DEVICE_PATH,
            "swap_size_kib": supervisor.DEVICE_SIZE_BYTES // 1024 - 4,
            "swap_priority": -1,
            "swap_used_kib": 0,
            "header": self.header,
        }

    def inspect_target(self):
        return self._target()

    def target_descriptor(self, _state):
        if not self.target_valid:
            raise supervisor.LiveSwapError("synthetic substituted target")
        return self._target()

    def recheck_target(self, state, *, expected_header=None,
                       require_active=False, require_zero=False):
        if not self.target_valid:
            raise supervisor.LiveSwapError("synthetic target changed")
        if expected_header and hashlib.sha256(self.header).hexdigest() != expected_header:
            raise supervisor.LiveSwapError("synthetic header changed")
        if require_active and not self.original_active:
            raise supervisor.LiveSwapError("synthetic original swap inactive")
        if require_zero and self.original_active and state.get("swap_used_kib", 0):
            raise supervisor.LiveSwapError("synthetic original swap used")

    def read_header(self, _target):
        return self.header

    def write_header(self, _target, data, expected_current=None):
        if expected_current is not None and self.header != expected_current:
            raise supervisor.LiveSwapError("synthetic checked write mismatch")
        self.header = data

    def read_swap_rows(self):
        rows = []
        if self.original_active:
            rows.append({"kind": "partition", "path": supervisor.DEVICE_PATH,
                         "size_kib": supervisor.DEVICE_SIZE_BYTES // 1024 - 4,
                         "used_kib": 0, "priority": -1})
        if self.mapper_active:
            rows.append({"kind": "partition",
                         "path": f"/dev/mapper/{self.mapper_name}",
                         "size_kib": supervisor.LOGICAL_BYTES // 1024 - 4,
                         "used_kib": self.mapper_used_kib, "priority": 32767})
        return rows

    def active_swap_for(self, major, minor):
        if (major, minor) == (supervisor.DEVICE_MAJOR, supervisor.DEVICE_MINOR):
            if not self.original_active:
                return None
            return {"path": supervisor.DEVICE_PATH, "kind": "partition",
                    "size_kib": supervisor.DEVICE_SIZE_BYTES // 1024 - 4,
                    "used_kib": 0, "priority": -1}
        if (major, minor) == (252, 0) and self.mapper_active:
            return {"path": f"/dev/mapper/{self.mapper_name}",
                    "kind": "partition",
                    "size_kib": supervisor.LOGICAL_BYTES // 1024 - 4,
                    "used_kib": self.mapper_used_kib,
                    "priority": 32767}
        return None

    def artifact_digests(self):
        return dict(supervisor.EXPECTED_ARTIFACTS)

    def repo_snapshot(self):
        return {"branch": "main", "clean": True, "head": HEAD,
                "origin_main": HEAD, "canonical_main": HEAD}

    def verify_module(self, _path):
        if not self.module:
            raise supervisor.LiveSwapError("synthetic module absent")

    def module_loaded(self):
        return self.module

    def module_refcount(self):
        return 0

    def kernel_diagnostics(self, _start_timestamp, _state):
        return {
            "available": True,
            "source": "synthetic",
            "time_filter_applied": True,
            "matching_line_count": 0,
            "messages": "",
        }

    def dm_rows(self):
        if self.mapper_exists:
            return [(self.mapper_name, self.mapper_uuid)]
        return []

    def verify_mapper(self, _state, *, allow_open=False):
        del allow_open
        if not self.mapper_exists:
            raise supervisor.LiveSwapError("synthetic mapper absent")
        return f"/dev/mapper/{self.mapper_name}"

    def verify_mapper_swap_signature(self, _state, _mapper):
        return True

    def target_holders(self, _major, _minor):
        return []

    def stop_requested(self):
        return self.stop_after_format and self.header == self.formatted

    def pressure_workload(self, state, *, cgroup_name, guard, stop_requested, timeout):
        del stop_requested, timeout
        self.pressure_calls += 1
        if state["run_id"] != RUN_ID:
            raise supervisor.LiveSwapError("pressure seed differs from run id")
        self.mapper_used_kib = 0 if self.pressure_mode == "no_mapper_use" else 64
        guard()
        outcome = {"cgroup": f"/synthetic/{cgroup_name}",
                   "timed_out": False, "stopped": False, "exit_code": 0,
                   "stdout": PRESSURE_OK, "stderr": "",
                   "memory_events": {"oom_kill": 0},
                   "swap_peak_bytes": 0 if self.pressure_mode == "no_swap_peak"
                   else 1048576,
                   "zswap_peak_bytes": 0}
        if self.pressure_mode == "mismatch":
            outcome.update(exit_code=1, stdout=json.dumps({
                "verified_pages": supervisor.PRESSURE_PAGES - 3,
                "mismatches": 3}))
        elif self.pressure_mode == "oom":
            outcome.update(exit_code=-9, stdout="",
                           memory_events={"oom_kill": 1})
        elif self.pressure_mode == "stop":
            outcome.update(exit_code=-15, stdout="", stopped=True)
        elif self.pressure_mode == "timeout":
            outcome.update(exit_code=-9, stdout="", timed_out=True)
        return outcome

    def release_pressure_cgroup(self, state):
        del state
        return False

    def swapoff_processes(self):
        return []

    def ci_status(self, head):
        return {"status": "PASS", "commit_sha": head,
                "workflows": list(supervisor.REQUIRED_CI_WORKFLOWS)}

    def mutate(self, argv, *, timeout=120):
        del timeout
        argv = list(map(str, argv))
        self.mutations.append(argv)
        name = Path(argv[0]).name
        if name == "swapoff" and argv[-1] == supervisor.DEVICE_PATH:
            if self.fail_phase == "original_swapoff":
                return subprocess.CompletedProcess(argv, 1, "", "injected failure")
            self.original_active = False
        elif name == "swapzctl":
            if self.bad_formatted_header:
                self.header = b"?" * supervisor.PAGE_BYTES
            else:
                self.header = self.formatted
        elif name == "mkswap" and self.fail_phase == "mkswap":
            return subprocess.CompletedProcess(argv, 1, "", "injected failure")
        elif name == "insmod":
            self.module = True
        elif name == "dmsetup" and argv[1] == "create":
            self.mapper_name, self.mapper_uuid = argv[2], argv[4]
            self.mapper_exists = True
            if self.bad_target_after_mapping:
                self.target_valid = False
        elif name == "swapon" and "--priority" in argv:
            if self.fail_phase == "mapper_swapon":
                return subprocess.CompletedProcess(argv, 1, "", "injected failure")
            self.mapper_active = True
        elif name == "swapoff" and "/dev/mapper/" in argv[-1]:
            if self.fail_phase == "mapper_swapoff":
                return subprocess.CompletedProcess(argv, 1, "", "injected failure")
            self.mapper_active = False
        elif name == "dmsetup" and argv[1] == "remove":
            if self.fail_phase == "remove_mapper":
                return subprocess.CompletedProcess(argv, 1, "", "injected failure")
            self.mapper_exists = False
        elif name == "rmmod":
            self.module = False
        elif name == "swapon" and argv[-1] == supervisor.DEVICE_PATH:
            self.original_active = True
        return subprocess.CompletedProcess(argv, 0, "ok\n", "")


class LiveSwapSupervisorTests(unittest.TestCase):
    def setUp(self):
        """Pin device identity: rootless tests must not depend on host block devices."""
        patcher = mock.patch.object(supervisor.PHYSICAL, "block_identity",
                                    side_effect=self._synthetic_block_identity)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _synthetic_block_identity(path):
        text_path = str(path)
        if text_path == supervisor.DEVICE_PATH:
            return (supervisor.DEVICE_MAJOR, supervisor.DEVICE_MINOR)
        if text_path.startswith("/dev/mapper/") or "swapz-live" in text_path:
            return (252, 0)
        raise supervisor.PHYSICAL.ProbeError(f"synthetic test has no device {text_path}")

    def test_supervisor_capacity_matches_kernel_maximum_for_full_partition(self):
        self.assertEqual(supervisor.MAX_PHYSICAL_BLOCKS, 4194048)
        self.assertEqual(supervisor.MAX_LOGICAL_PAGES, 3355136)
        self.assertEqual(supervisor.LOGICAL_BYTES, 13742637056)
        self.assertEqual(supervisor.LOGICAL_SECTORS, 26841088)
        reserve = max(
            (supervisor.MAX_LOGICAL_PAGES + 3) // 4,
            supervisor.SWAPZ_MIN_RESERVE_BLOCKS)
        admitted_blocks = (
            (supervisor.MAX_PHYSICAL_BLOCKS - reserve) //
            supervisor.SWAPZ_SEGMENT_BLOCKS
        ) * supervisor.SWAPZ_SEGMENT_BLOCKS
        self.assertLessEqual(supervisor.MAX_LOGICAL_PAGES, admitted_blocks)
        next_reserve = max(
            (supervisor.MAX_LOGICAL_PAGES + 1 + 3) // 4,
            supervisor.SWAPZ_MIN_RESERVE_BLOCKS)
        next_admitted = (
            (supervisor.MAX_PHYSICAL_BLOCKS - next_reserve) //
            supervisor.SWAPZ_SEGMENT_BLOCKS
        ) * supervisor.SWAPZ_SEGMENT_BLOCKS
        self.assertGreater(supervisor.MAX_LOGICAL_PAGES + 1, next_admitted)

    def test_drain_headroom_is_only_surplus_ram_after_current_swap(self):
        used_kib = 3977 * 1024
        memory = {"mem_available_bytes": 10439 * 1024 * 1024}
        headroom = supervisor._drain_headroom_bytes(used_kib, memory)
        self.assertEqual(
            headroom,
            memory["mem_available_bytes"] - supervisor.MIN_AVAILABLE_BYTES -
            used_kib * 1024)
        self.assertGreaterEqual(headroom, supervisor.MIN_DRAIN_HEADROOM_BYTES)
        with self.assertRaisesRegex(supervisor.SafeStop, "evacuate") as caught:
            supervisor._check_drain_headroom(
                used_kib, {"mem_available_bytes":
                           supervisor.MIN_AVAILABLE_BYTES + used_kib * 1024 +
                           supervisor.MIN_DRAIN_HEADROOM_BYTES - 4096})
        self.assertEqual(caught.exception.reason, "drain_headroom")

    def test_drain_headroom_rejects_malformed_or_negative_inputs(self):
        with self.assertRaisesRegex(supervisor.LiveSwapError, "malformed"):
            supervisor._drain_headroom_bytes(
                -1, {"mem_available_bytes": 4 * 1024**3})
        with self.assertRaisesRegex(supervisor.LiveSwapError, "malformed"):
            supervisor._drain_headroom_bytes(0, {"mem_available_bytes": "4G"})

    def test_kernel_diagnostics_are_time_filtered_and_bounded(self):
        ops = supervisor.LinuxOps()
        journal = subprocess.CompletedProcess(
            ["journalctl"], 0,
            "2026-11-02T10:00:00Z kernel: swapz: WARNING: test warning\n"
            "2026-11-02T10:00:01Z kernel: sda: I/O error\n"
            "2026-11-02T10:00:02Z kernel: unrelated informational message\n",
            "")
        with mock.patch.object(supervisor.shutil, "which",
                               side_effect=lambda name: f"/usr/bin/{name}"), \
                mock.patch.object(ops, "command", return_value=journal) as command:
            evidence = ops.kernel_diagnostics(
                "2026-11-02T09:59:00Z",
                {"device": supervisor.DEVICE_PATH,
                 "dm_name": "swapz-live-0123456789abcdef"})
        self.assertTrue(evidence["time_filter_applied"])
        self.assertEqual(evidence["source"], "journalctl")
        self.assertEqual(evidence["matching_line_count"], 2)
        self.assertIn("WARNING", evidence["messages"])
        self.assertIn("I/O error", evidence["messages"])
        self.assertNotIn("unrelated informational", evidence["messages"])
        argv = command.call_args.args[0]
        self.assertEqual(argv[-1], "--since=2026-11-02T09:59:00Z")
        self.assertTrue(supervisor.LinuxOps._read_only_command_allowed(argv))

    def test_kernel_diagnostics_marks_dmesg_fallback_unfiltered(self):
        ops = supervisor.LinuxOps()
        journal = subprocess.CompletedProcess(
            ["journalctl"], 1, "", "journal access unavailable")
        dmesg = subprocess.CompletedProcess(
            ["dmesg"], 0,
            "[Mon Nov  2 10:00:00 2026] swapz: OOM warning\n"
            "[Mon Nov  2 10:00:01 2026] unrelated message\n", "")
        with mock.patch.object(supervisor.shutil, "which",
                               side_effect=lambda name: f"/usr/bin/{name}"), \
                mock.patch.object(ops, "command", side_effect=[journal, dmesg]) as command:
            evidence = ops.kernel_diagnostics(
                "2026-11-02T09:59:00Z", {"device": supervisor.DEVICE_PATH})
        self.assertTrue(evidence["available"])
        self.assertEqual(evidence["source"], "dmesg")
        self.assertFalse(evidence["time_filter_applied"])
        self.assertIn("journal access unavailable", evidence["journalctl_error"])
        self.assertEqual(evidence["matching_line_count"], 1)
        self.assertIn("OOM warning", evidence["messages"])
        self.assertEqual(command.call_count, 2)
        self.assertTrue(supervisor.LinuxOps._read_only_command_allowed(
            command.call_args.args[0]))

    def test_mutating_command_allowlist_is_exact_and_plan_commands_reject_mutation(self):
        allowed = [
            ["swapoff", "--", "/dev/sda4"],
            ["swapon", "--priority", "32767", "--",
             "/dev/mapper/swapz-live-0123456789abcdef"],
            ["mkswap", "--", "/dev/mapper/swapz-live-0123456789abcdef"],
            ["dmsetup", "remove", "--", "swapz-live-0123456789abcdef"],
        ]
        for command in allowed:
            with self.subTest(command=command):
                self.assertTrue(supervisor.LinuxOps._mutation_allowed(command))
        denied = [
            ["swapoff", "-a"],
            ["swapon", "--", "/dev/sda3"],
            ["dmsetup", "remove", "--force", "unrelated"],
            ["dmsetup", "remove", "--deferred", "swapz-live-0123456789abcdef"],
            ["mkswap", "--force", "/dev/sda4"],
            ["mkswap", "--", "/dev/sda4"],
            ["rmmod", "-f", "dm_swapz"],
            ["swapon", "--discard=pages", "--",
             "/dev/mapper/swapz-live-0123456789abcdef"],
        ]
        for command in denied:
            with self.subTest(command=command):
                self.assertFalse(supervisor.LinuxOps._mutation_allowed(command))
        ops = supervisor.LinuxOps()
        with self.assertRaises(supervisor.LiveSwapError):
            ops.command(["swapoff", "-a"])
        with self.assertRaises(supervisor.LiveSwapError):
            ops.command(["blockdev", "--setro", "/dev/sda4"])
        with self.assertRaises(supervisor.LiveSwapError):
            ops.command(["blkid", "--update", "all"])

    def test_execution_requires_root_and_exact_confirmation(self):
        self.assertTrue(supervisor.LIVE_SWAP_EXECUTION_ENABLED)
        ops = FakeOps()
        with mock.patch.object(supervisor.os, "geteuid", return_value=1000):
            with self.assertRaisesRegex(supervisor.LiveSwapError, "requires root"):
                supervisor.run_trial("/unused", "/unused",
                                     confirm="LIVE-SWAP-TRIAL", ops=ops)
            with self.assertRaisesRegex(supervisor.LiveSwapError, "requires root"):
                supervisor.recover_cli("/unused",
                                       confirm="RESTORE-ORIGINAL-SWAP", ops=ops)
        with mock.patch.object(supervisor.os, "geteuid", return_value=0):
            with self.assertRaisesRegex(supervisor.LiveSwapError, "confirmation"):
                supervisor.run_trial("/unused", "/unused",
                                     confirm="yes", ops=ops)

    def test_read_only_plan_never_calls_mutation_channel_and_exposes_trace(self):
        ops = FakeOps()
        ops.host_physical = lambda: True
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            ops.recovery_base = lambda _target: base
            ops.inspect_target = lambda: ops._target()
            ops.memory_facts = lambda: {
                "MemAvailable": 8 * 1024**3,
                "MemTotal": 16 * 1024**3,
                "ram_used_percent": 30.0,
                "cgroup_headroom": None,
                "psi_some_avg10": 0.0,
                "psi_full_avg10": 0.0,
            }
            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(
                    supervisor, "_load_unique_json",
                    return_value={"run_id": RUN_ID}))
                stack.enter_context(mock.patch.object(
                    supervisor, "validate_approval", return_value=RUN_ID))
                stack.enter_context(mock.patch.object(
                    supervisor, "_validate_target_facts", return_value=None))
                stack.enter_context(mock.patch.object(
                    supervisor.PHYSICAL, "block_identity",
                    side_effect=lambda path: (8, 4)))
                plan = supervisor.read_only_plan("/synthetic/approval", ops=ops)
        self.assertTrue(plan["read_only"])
        self.assertEqual(ops.mutations, [])
        self.assertEqual(plan["operation_trace"],
                         list(supervisor.PLANNED_MUTATION_TRACE))

    def test_plan_gate_evaluation_blocks_policy_and_risk_mismatches(self):
        facts = self.positive_plan_facts()
        plan = supervisor.evaluate_plan(facts)
        self.assertEqual(plan["status"], "PASS")
        self.assertTrue(plan["read_only"])
        facts["repo"]["changed_paths"] = ["src/kernel/dm-target.c"]
        plan = supervisor.evaluate_plan(facts)
        self.assertEqual(plan["gates"]["post_qualification_path_policy"]["status"],
                         "BLOCKED")
        facts = self.positive_plan_facts()
        facts["target"]["swap_used_kib"] = supervisor.DEVICE_SIZE_BYTES // 1024 + 1
        plan = supervisor.evaluate_plan(facts)
        self.assertEqual(plan["gates"]["target"]["status"], "BLOCKED")
        facts = self.positive_plan_facts()
        facts["fallback"] = {"path": "/synthetic/fallback.swap"}
        plan = supervisor.evaluate_plan(facts)
        self.assertEqual(plan["gates"]["fallback"]["status"], "BLOCKED")
        facts = self.positive_plan_facts()
        facts["approval"]["fallback_mode"] = "same-usb"
        plan = supervisor.evaluate_plan(facts)
        self.assertEqual(plan["gates"]["fallback"]["status"], "BLOCKED")
        facts = self.positive_plan_facts()
        facts["swap_inventory_exact"] = False
        plan = supervisor.evaluate_plan(facts)
        self.assertEqual(plan["gates"]["swap_inventory"]["status"], "BLOCKED")
        facts = self.positive_plan_facts()
        facts["memory"]["ram_used_percent"] = 50.0
        plan = supervisor.evaluate_plan(facts)
        self.assertEqual(plan["gates"]["memory"]["status"], "BLOCKED")
        facts = self.positive_plan_facts()
        facts["memory"]["psi_full_avg10"] = supervisor.MAX_MEMORY_FULL_AVG10
        plan = supervisor.evaluate_plan(facts)
        self.assertEqual(plan["gates"]["memory"]["status"], "BLOCKED")
        facts = self.positive_plan_facts()
        facts["memory"]["mem_available_bytes"] = (
            supervisor.MIN_AVAILABLE_BYTES + supervisor.TRIAL_HEADROOM_BYTES - 1)
        facts["target"]["swap_used_kib"] = 0
        plan = supervisor.evaluate_plan(facts)
        self.assertEqual(plan["gates"]["memory"]["status"], "BLOCKED")

    def test_active_swap_inventory_requires_only_the_original_partition(self):
        class Inventory:
            def __init__(self, rows):
                self.rows = rows

            def read_swap_rows(self):
                return self.rows

        with mock.patch.object(supervisor.PHYSICAL, "block_identity",
                               side_effect=lambda path: (
                                   (8, 8) if path == "/dev/other" else (8, 4))):
            self.assertTrue(supervisor._exact_active_swap_inventory(
                Inventory([{"kind": "partition", "path": "/dev/sda4"}])))
            with self.assertRaisesRegex(supervisor.LiveSwapError, "differs"):
                supervisor._exact_active_swap_inventory(
                    Inventory([
                        {"kind": "partition", "path": "/dev/sda4"},
                        {"kind": "partition", "path": "/dev/other"},
                    ]))
            with self.assertRaisesRegex(supervisor.LiveSwapError, "differs"):
                supervisor._exact_active_swap_inventory(
                    Inventory([
                        {"kind": "file", "path": "/synthetic/fallback.swap"},
                        {"kind": "partition", "path": "/dev/sda4"},
                    ]))

    def test_actual_swap_io_requires_swap_out_swap_in_and_lower_writes(self):
        baseline = {
            "vmstat": {"pswpin": 0, "pswpout": 0},
            "dmsetup_status": {"counters": {"logical_write": 0,
                                            "logical_read": 0}},
            "block_stats": {"available": True, "values": [0] * 8},
        }
        sample = {
            "vmstat": {"pswpin": 3, "pswpout": 9},
            "dmsetup_status": {"counters": {"logical_write": 4096,
                                            "logical_read": 4096}},
            "swap_used_kib": 0,
            "block_stats": {"available": True,
                            "values": [0, 0, 0, 0, 1, 0, 8, 0]},
        }
        result = {"trial_baseline": baseline, "observations": [sample],
                  "pressure_phase": {"status": "PASS",
                                     "peak_mapper_used_kib": 196608}}
        self.assertTrue(supervisor._actual_swap_io(result))
        no_swap_in = json.loads(json.dumps(result))
        no_swap_in["observations"][0]["vmstat"]["pswpin"] = 0
        self.assertFalse(supervisor._actual_swap_io(no_swap_in))
        no_pressure = json.loads(json.dumps(result))
        no_pressure["pressure_phase"] = {"status": "FAIL",
                                         "peak_mapper_used_kib": 196608}
        self.assertFalse(supervisor._actual_swap_io(no_pressure))
        no_mapper_use = json.loads(json.dumps(result))
        no_mapper_use["pressure_phase"]["peak_mapper_used_kib"] = 0
        self.assertFalse(supervisor._actual_swap_io(no_mapper_use))
        blind = json.loads(json.dumps(result))
        blind["observations"][0]["block_stats"] = {"available": False}
        self.assertFalse(supervisor._actual_swap_io(blind))

    def test_pressure_pattern_is_deterministic_incompressible_and_verified(self):
        seed = RUN_ID.encode("ascii")
        first = supervisor._pressure_page(seed, 0)
        self.assertEqual(len(first), supervisor.PAGE_BYTES)
        self.assertEqual(first, supervisor._pressure_page(seed, 0))
        self.assertNotEqual(first, supervisor._pressure_page(seed, 1))
        working_set = bytearray()
        for index in range(4):
            working_set += supervisor._pressure_page(seed, index)
        self.assertEqual(supervisor._pressure_verify(working_set, seed, 4), 0)
        working_set[4096 * 2 + 17] ^= 0x40
        self.assertEqual(supervisor._pressure_verify(working_set, seed, 4), 1)

    def test_pressure_run_counts_verified_pages_without_touching_disk(self):
        report = supervisor._pressure_run(RUN_ID, 4)
        self.assertEqual(report["verified_pages"], 4)
        self.assertEqual(report["mismatches"], 0)

    def test_pressure_guard_records_mapper_use_and_stops_on_floor_or_headroom(self):
        ops = FakeOps()
        ops.mapper_active = True
        ops.mapper_used_kib = 2048
        state = {"dm_major": 252, "dm_minor": 0}
        progress = {"peak_mapper_used_kib": 0}
        with mock.patch.object(supervisor, "_memory_sample", return_value=HIGH_MEMORY):
            self.assertEqual(supervisor._pressure_guard(ops, state, progress), 2048)
        self.assertEqual(progress["peak_mapper_used_kib"], 2048)
        with mock.patch.object(supervisor, "_memory_sample", return_value=LOW_MEMORY):
            with self.assertRaises(supervisor.SafeStop) as caught:
                supervisor._pressure_guard(ops, state, progress)
        self.assertEqual(caught.exception.reason, "memory_floor")
        tight = {"mem_available_bytes": supervisor.MIN_AVAILABLE_BYTES +
                 supervisor.TRIAL_HEADROOM_BYTES - 4096,
                 "mem_total_bytes": 16 * 1024**3, "ram_used_percent": 30.0,
                 "cgroup_headroom_bytes": None, "psi_some_avg10": 0.0,
                 "psi_full_avg10": 0.0}
        with mock.patch.object(supervisor, "_memory_sample", return_value=tight):
            with self.assertRaises(supervisor.SafeStop) as caught:
                supervisor._pressure_guard(ops, state, progress)
        self.assertEqual(caught.exception.reason, "mapper_drain_headroom_low")

    def test_ci_status_requires_both_required_workflows_for_head(self):
        runs = [{"headSha": HEAD, "name": name, "status": "completed",
                 "conclusion": "success"}
                for name in supervisor.REQUIRED_CI_WORKFLOWS]
        ops = supervisor.LinuxOps()
        with mock.patch.object(ops, "command", return_value=subprocess.CompletedProcess(
                ["gh"], 0, json.dumps(runs), "")):
            self.assertEqual(ops.ci_status(HEAD)["status"], "PASS")
        with mock.patch.object(ops, "command", return_value=subprocess.CompletedProcess(
                ["gh"], 0, json.dumps(runs[:1]), "")):
            self.assertEqual(ops.ci_status(HEAD)["status"], "BLOCKED")
        other = [dict(run, headSha="e" * 40) for run in runs]
        with mock.patch.object(ops, "command", return_value=subprocess.CompletedProcess(
                ["gh"], 0, json.dumps(other), "")):
            self.assertEqual(ops.ci_status(HEAD)["status"], "BLOCKED")

    def test_ci_query_runs_as_the_operator_under_sudo(self):
        ops = supervisor.LinuxOps()
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(supervisor.os, "geteuid", return_value=0))
            stack.enter_context(mock.patch.dict(os.environ, {"SUDO_USER": "keivan"}))
            stack.enter_context(mock.patch.object(
                supervisor.shutil, "which", return_value="/usr/sbin/runuser"))
            command = stack.enter_context(mock.patch.object(
                ops, "command", return_value=subprocess.CompletedProcess(
                    ["gh"], 0, "[]", "")))
            ops.ci_status(HEAD)
        argv = command.call_args.args[0]
        self.assertEqual(argv[:4], ["/usr/sbin/runuser", "--user", "keivan", "--"])
        self.assertTrue(supervisor.LinuxOps._read_only_command_allowed(argv))
        self.assertFalse(supervisor.LinuxOps._read_only_command_allowed(
            ["/usr/sbin/runuser", "--user", "root", "--", *supervisor.GH_RUN_LIST_ARGS]))
        self.assertFalse(supervisor.LinuxOps._read_only_command_allowed(
            ["gh", "run", "rerun", "1"]))

    def test_mutations_run_in_their_own_session(self):
        completed = subprocess.CompletedProcess(["swapoff"], 0, "", "")
        with mock.patch.object(supervisor.subprocess, "run", return_value=completed) as run:
            supervisor._run_isolated(["swapoff", "--", supervisor.DEVICE_PATH], timeout=5)
        self.assertTrue(run.call_args.kwargs["start_new_session"])

    def test_mapper_zero_open_check_retries_transient_udev_probes(self):
        ops = FakeOps()
        attempts = [supervisor.LiveSwapError("owned mapper has unexpected open references"),
                    "/dev/mapper/synthetic"]
        with mock.patch.object(supervisor, "_verify_mapper_once",
                               side_effect=attempts) as once, \
                mock.patch.object(supervisor.time, "sleep", return_value=None):
            self.assertEqual(supervisor._verify_mapper(ops, {}), "/dev/mapper/synthetic")
        self.assertEqual(once.call_count, 2)

    def test_reconcile_follows_the_kernel_for_mapper_and_orphaned_swapoff(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            ops = FakeOps()
            state = {"run_id": RUN_ID, "stage": "LIVE_SWAP_ACTIVE",
                     "active_mapper_swap": True, "original_swapoff_complete": True,
                     "dm_name": "swapz-live-0123456789abcdef",
                     "dm_uuid": "SWAPZ-LIVE-0123456789abcdef",
                     "major": supervisor.DEVICE_MAJOR,
                     "minor": supervisor.DEVICE_MINOR}
            supervisor._reconcile_trial_state(state_dir, state, ops)
            self.assertFalse(state["active_mapper_swap"])
            ops.mapper_exists = True
            ops.mapper_active = True
            ops.mapper_name = "swapz-live-0123456789abcdef"
            ops.mapper_uuid = "SWAPZ-LIVE-0123456789abcdef"
            state["active_mapper_swap"] = False
            with mock.patch.object(supervisor, "_mapper_info", return_value=(252, 0, 0)):
                supervisor._reconcile_trial_state(state_dir, state, ops)
            self.assertTrue(state["active_mapper_swap"])
            orphan = {"run_id": RUN_ID, "stage": "ORIGINAL_SWAPOFF_PENDING",
                      "original_swapoff_complete": False,
                      "major": supervisor.DEVICE_MAJOR,
                      "minor": supervisor.DEVICE_MINOR}
            idle = FakeOps()
            idle.original_active = False
            idle.swapoff_processes = lambda: []
            supervisor._reconcile_trial_state(state_dir, orphan, idle)
            self.assertTrue(orphan["original_swapoff_complete"])
            busy = FakeOps()
            busy.original_active = False
            busy.swapoff_processes = lambda: [4242]
            orphan["original_swapoff_complete"] = False
            with self.assertRaisesRegex(supervisor.LiveSwapError, "orphaned swapoff"):
                supervisor._reconcile_trial_state(state_dir, orphan, busy)

    def test_recovery_refusal_is_recorded_as_requires_review(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            state = {"run_id": RUN_ID, "stage": "LIVE_SWAP_ACTIVE"}
            supervisor._save_state(state_dir, state)
            error = supervisor._recovery_refusal(state_dir, state, "mapper still exists")
            self.assertIsInstance(error, supervisor.LiveSwapError)
            saved = json.loads((state_dir / supervisor.STATE_NAME).read_text())
            self.assertEqual(saved["stage"], "RECOVERY_REQUIRED")
            results = json.loads((state_dir / supervisor.RESULTS_NAME).read_text())
            self.assertEqual(results["recovery_disposition"], "REQUIRES_REVIEW")

    def test_review_commit_reference_must_name_the_reviewed_head(self):
        with self.assertRaisesRegex(supervisor.LiveSwapError, "reviewed HEAD"):
            self.validate(self.approval_record(
                review_reference="https://github.com/k1moradi/swapz/commit/" + "e" * 40))

    def test_run_refuses_an_approval_changed_after_the_plan(self):
        ops = FakeOps()
        approval = {"run_id": RUN_ID}
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(supervisor.os, "geteuid", return_value=0))
            stack.enter_context(mock.patch.object(
                supervisor.PHYSICAL, "_partition_lock",
                side_effect=lambda _partuuid: os.open(os.devnull, os.O_RDONLY)))
            stack.enter_context(mock.patch.object(
                supervisor, "read_only_plan",
                return_value={"status": "PASS", "head": HEAD,
                              "approval_sha256": "f" * 64}))
            stack.enter_context(mock.patch.object(
                supervisor, "_load_unique_json", return_value=approval))
            with self.assertRaisesRegex(supervisor.LiveSwapError, "changed after"):
                supervisor.run_trial("/synthetic/approval.json", "/synthetic/state",
                                     confirm="LIVE-SWAP-TRIAL", ops=ops)

    def test_plan_treats_unreadable_memory_as_blocked_not_as_a_crash(self):
        facts = self.positive_plan_facts()
        facts["memory"] = {"mem_available_bytes": None, "mem_total_bytes": None,
                           "ram_used_percent": None, "psi_some_avg10": None,
                           "psi_full_avg10": None, "cgroup_headroom_bytes": None}
        plan = supervisor.evaluate_plan(facts)
        self.assertEqual(plan["gates"]["memory"]["status"], "BLOCKED")

    def test_allowlist_accepts_only_the_exact_ci_query(self):
        self.assertTrue(supervisor.LinuxOps._read_only_command_allowed(
            list(supervisor.GH_RUN_LIST_ARGS)))
        self.assertFalse(supervisor.LinuxOps._read_only_command_allowed(
            ["gh", "run", "list", "--repo", "someone/else"]))

    def test_pressure_workload_runs_forked_child_in_bounded_cgroup_and_cleans_up(self):
        ops = supervisor.LinuxOps()
        state = {"run_id": RUN_ID}
        guard_calls = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def fake_mkdir(path, _mode=0o755):
                REAL_MKDIR(path)
                (Path(path) / "memory.events").write_text("oom_kill 0\n")
                (Path(path) / "memory.max").write_text("max\n")
                (Path(path) / "memory.zswap.max").write_text("max\n")
                (Path(path) / "memory.swap.peak").write_text("1048576\n")

            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(
                    supervisor, "PRESSURE_CGROUP_ROOT", root))
                stack.enter_context(mock.patch.object(supervisor, "PRESSURE_PAGES", 16))
                stack.enter_context(mock.patch.object(
                    supervisor.os, "mkdir", side_effect=fake_mkdir))
                stack.enter_context(mock.patch.object(
                    supervisor, "_remove_empty_cgroup", return_value=None))
                outcome = ops.pressure_workload(
                    state, cgroup_name="swapz-live-0123456789abcdef",
                    guard=lambda: guard_calls.append(1),
                    stop_requested=lambda: False, timeout=120)
            cgroup = root / "swapz-live-0123456789abcdef"
            self.assertEqual(outcome["exit_code"], 0)
            self.assertFalse(outcome["timed_out"])
            report = json.loads(outcome["stdout"].strip().splitlines()[-1])
            self.assertEqual(report["verified_pages"], 16)
            self.assertEqual(report["mismatches"], 0)
            self.assertEqual(outcome["memory_events"], {"oom_kill": 0})
            self.assertEqual(outcome["swap_peak_bytes"], 1048576)
            self.assertIsNone(outcome["zswap_peak_bytes"])
            self.assertEqual((cgroup / "memory.max").read_text(),
                             f"{supervisor.PRESSURE_MEMORY_MAX_BYTES}\n")
            self.assertEqual((cgroup / "memory.zswap.max").read_text(), "0\n")

    def test_pressure_workload_timeout_kills_the_child_and_reports_it(self):
        ops = supervisor.LinuxOps()

        def slow_run(_run_id, _pages):
            time.sleep(30)
            return {"verified_pages": 0, "mismatches": 0, "elapsed_seconds": 30}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def fake_mkdir(path, _mode=0o755):
                REAL_MKDIR(path)
                (Path(path) / "memory.events").write_text("oom_kill 0\n")
                (Path(path) / "memory.max").write_text("max\n")
                (Path(path) / "memory.zswap.max").write_text("max\n")

            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(
                    supervisor, "PRESSURE_CGROUP_ROOT", root))
                stack.enter_context(mock.patch.object(supervisor, "PRESSURE_PAGES", 16))
                stack.enter_context(mock.patch.object(
                    supervisor, "_pressure_run", side_effect=slow_run))
                stack.enter_context(mock.patch.object(
                    supervisor.os, "mkdir", side_effect=fake_mkdir))
                stack.enter_context(mock.patch.object(
                    supervisor, "_remove_empty_cgroup", return_value=None))
                outcome = ops.pressure_workload(
                    {"run_id": RUN_ID}, cgroup_name="swapz-live-0123456789abcdef",
                    guard=lambda: None, stop_requested=lambda: False, timeout=0.5)
        self.assertTrue(outcome["timed_out"])
        self.assertLess(outcome["exit_code"], 0)

    def test_pressure_phase_accepts_only_verified_bounded_child(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory)
            base_state = {"run_id": RUN_ID, "dm_major": 252, "dm_minor": 0,
                          "dm_name": "swapz-live-0123456789abcdef",
                          "stage": "LIVE_SWAP_ACTIVE"}

            def phase(mode):
                ops = FakeOps(pressure_mode=mode)
                ops.mapper_active = True
                results = {"schema": "swapz-live-swap-results-v1"}
                with mock.patch.object(supervisor, "_memory_sample",
                                       return_value=HIGH_MEMORY):
                    value = supervisor._run_pressure_phase(
                        state_dir, dict(base_state), results, ops)
                return value, results

            passed, results = phase("pass")
            self.assertEqual(passed["status"], "PASS")
            self.assertEqual(results["pressure_phase"]["status"], "PASS")
            self.assertGreater(results["pressure_phase"]["peak_mapper_used_kib"], 0)
            for mode in ("mismatch", "oom", "timeout", "no_swap_peak", "no_mapper_use"):
                with self.subTest(mode=mode):
                    with self.assertRaises(supervisor.LiveSwapError):
                        phase(mode)
            with self.assertRaises(supervisor.SafeStop) as caught:
                phase("stop")
            self.assertEqual(caught.exception.reason, "operator_stop")

    def test_live_inspection_permits_used_swap_only_through_helper_flag(self):
        header = b"O" * supervisor.PAGE_BYTES
        target = {"device": supervisor.DEVICE_PATH,
                  "major": supervisor.DEVICE_MAJOR,
                  "minor": supervisor.DEVICE_MINOR,
                  "partuuid": supervisor.DEVICE_PARTUUID,
                  "size_bytes": supervisor.DEVICE_SIZE_BYTES,
                  "header": header,
                  "swap_used_kib": 3977 * 1024}
        with mock.patch.object(supervisor, "ORIGINAL_HEADER_SHA256",
                               hashlib.sha256(header).hexdigest()), \
                mock.patch.object(supervisor.PHYSICAL, "inspect_target",
                                  return_value=target) as inspect:
            result = supervisor.LinuxOps().inspect_target()
        inspect.assert_called_once_with(
            supervisor.DEVICE_UUID_PATH, supervisor.DEVICE_UUID_PATH,
            allow_used_swap=True)
        self.assertEqual(result["swap_used_kib"], 3977 * 1024)

    def test_remove_empty_cgroup_refuses_populated_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            cgroup = Path(directory) / "swapz-live-0123456789abcdef"
            cgroup.mkdir()
            (cgroup / "memory.max").write_text("max\n")
            with self.assertRaisesRegex(supervisor.LiveSwapError, "manual review"):
                supervisor._remove_empty_cgroup(cgroup)

    def test_dm_info_colon_rows_and_mapper_uuid_substitution(self):
        name = "swapz-live-0123456789abcdef"
        uuid = "SWAPZ-LIVE-0123456789abcdef"

        class InfoOps:
            def __init__(self, output):
                self.output = output

            def command(self, _argv, *, check=False):
                del check
                return subprocess.CompletedProcess(
                    [], 0, self.output, "")

        state = {"dm_name": name, "dm_uuid": uuid}
        self.assertEqual(supervisor._mapper_info(
            InfoOps(f"{name}:{uuid}:252:9:0\n"), state), (252, 9, 0))
        with self.assertRaisesRegex(supervisor.LiveSwapError, "substituted"):
            supervisor._mapper_info(
                InfoOps(f"{name}:SWAPZ-LIVE-substituted:252:9:0\n"), state)

    def test_mapper_observation_rejects_wrong_backing_size_uuid_and_table(self):
        state = {
            "dm_name": "swapz-live-0123456789abcdef",
            "dm_uuid": "SWAPZ-LIVE-0123456789abcdef",
            "device": supervisor.DEVICE_PATH,
            "major": supervisor.DEVICE_MAJOR,
            "minor": supervisor.DEVICE_MINOR,
        }
        good = (state["dm_name"], state["dm_uuid"],
                supervisor.LOGICAL_SECTORS,
                [f"{supervisor.DEVICE_MAJOR}:{supervisor.DEVICE_MINOR}"])
        table = supervisor._mapper_table(state)
        self.assertTrue(supervisor._validate_mapper_observation(
            state, sysfs_identity=good, table_output=table,
            open_count=0))
        bad_observations = [
            (state["dm_name"], "SWAPZ-LIVE-substituted",
             supervisor.LOGICAL_SECTORS,
             [f"{supervisor.DEVICE_MAJOR}:{supervisor.DEVICE_MINOR}"]),
            (state["dm_name"], state["dm_uuid"],
             supervisor.LOGICAL_SECTORS - 1,
             [f"{supervisor.DEVICE_MAJOR}:{supervisor.DEVICE_MINOR}"]),
            (state["dm_name"], state["dm_uuid"],
             supervisor.LOGICAL_SECTORS, ["8:3"]),
        ]
        for observation in bad_observations:
            with self.subTest(observation=observation):
                with self.assertRaises(supervisor.LiveSwapError):
                    supervisor._validate_mapper_observation(
                        state, sysfs_identity=observation,
                        table_output=table, open_count=0)
        wrong_table = table.replace("/dev/sda4", "/dev/sda3")
        with self.assertRaisesRegex(supervisor.LiveSwapError, "table"):
            supervisor._validate_mapper_observation(
                state, sysfs_identity=good, table_output=wrong_table,
                open_count=0)
        with self.assertRaisesRegex(supervisor.LiveSwapError, "open references"):
            supervisor._validate_mapper_observation(
                state, sysfs_identity=good, table_output=table,
                open_count=1)

    def test_atomic_state_replacement_preserves_last_durable_commit_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text('{"stage":"PREPARED"}\n')
            with mock.patch.object(supervisor.os, "replace",
                                   side_effect=OSError("injected commit failure")):
                with self.assertRaises(OSError):
                    supervisor._atomic_json(path, {"stage": "HEADER_CLEARED"})
            self.assertEqual(json.loads(path.read_text()), {"stage": "PREPARED"})
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_consumed_run_id_cannot_be_reused(self):
        target = {"partuuid": supervisor.DEVICE_PARTUUID,
                  "major": supervisor.DEVICE_MAJOR,
                  "minor": supervisor.DEVICE_MINOR}
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / f"consumed-{RUN_ID}.json").write_text("{}\n")
            with mock.patch.object(supervisor.PHYSICAL, "_recovery_base",
                                   return_value=base):
                with self.assertRaisesRegex(
                        supervisor.PHYSICAL.ProbeError, "consumed"):
                    supervisor.PHYSICAL._check_review_unconsumed(target, RUN_ID)

    def test_memory_pressure_thresholds_fail_closed_as_safe_stops(self):
        good = {"mem_available_bytes": 4 * 1024**3,
                "cgroup_headroom_bytes": 1024**3,
                "psi_some_avg10": 0.0, "psi_full_avg10": 0.0,
                "ram_used_percent": 30.0}
        supervisor._check_memory_sample(good, require_low_ram=True)
        for key, value in (
                ("mem_available_bytes", 1),
                ("cgroup_headroom_bytes", 1),
                ("psi_some_avg10", supervisor.MAX_MEMORY_SOME_AVG10),
                ("psi_full_avg10", supervisor.MAX_MEMORY_FULL_AVG10)):
            sample = dict(good)
            sample[key] = value
            with self.subTest(key=key):
                with self.assertRaisesRegex(supervisor.SafeStop, "pressure"):
                    supervisor._check_memory_sample(sample)
        high_ram = dict(good, ram_used_percent=50.0)
        with self.assertRaises(supervisor.SafeStop) as caught:
            supervisor._check_memory_sample(high_ram, require_low_ram=True)
        self.assertEqual(caught.exception.reason, "ram_not_low")

    def approval_record(self, **overrides):
        record = {
            "approved": True,
            "approval_text": supervisor.LIVE_APPROVAL_TEXT,
            "owner_authorized": True,
            "owner_approval_text": supervisor.OWNER_APPROVAL_TEXT,
            "issue_number": 76,
            "review_reference": f"https://github.com/k1moradi/swapz/commit/{HEAD}",
            "reviewed_commit_sha": HEAD,
            "ci_commit_sha": HEAD,
            "ci_status": "PASS",
            "ci_workflows": list(supervisor.REQUIRED_CI_WORKFLOWS),
            "run_id": RUN_ID,
            "source_sha": supervisor.QUALIFIED_SOURCE,
            "helper_git_sha": HEAD,
            "helper_sha256": "a" * 64,
            "physical_helper_sha256": supervisor.PHYSICAL_HELPER_SHA256,
            "device_uuid_path": supervisor.DEVICE_UUID_PATH,
            "device": supervisor.DEVICE_PATH,
            "device_major_minor": "8:4",
            "device_partuuid": supervisor.DEVICE_PARTUUID,
            "device_size_bytes": supervisor.DEVICE_SIZE_BYTES,
            "original_header_sha256": supervisor.ORIGINAL_HEADER_SHA256,
            "logical_capacity_bytes": supervisor.LOGICAL_BYTES,
            "duration_seconds": supervisor.TRIAL_SECONDS,
            "pressure_pages": supervisor.PRESSURE_PAGES,
            "pressure_memory_max_bytes": supervisor.PRESSURE_MEMORY_MAX_BYTES,
            "scope": "experimental live Linux swap trial only",
            "artifact_digests": dict(supervisor.EXPECTED_ARTIFACTS),
            "fallback": None,
            "fallback_mode": "none",
            "accept_no_fallback_risk": True,
            "approval_mode": "owner_waiver",
            "reviewer": None,
            "external_review": "waived_by_owner",
            "external_review_waiver": supervisor.OWNER_WAIVER_TEXT,
        }
        record.update(overrides)
        return record

    def validate(self, record, *, target=None):
        return supervisor.validate_approval(
            record, head=HEAD, helper_sha256="a" * 64,
            artifacts=supervisor.EXPECTED_ARTIFACTS,
            target=target or self.target())

    def test_owner_waiver_binds_exact_waiver_without_reviewer_claim(self):
        self.assertEqual(self.validate(self.approval_record()), RUN_ID)
        for override in ({"external_review_waiver": "approved by reviewer"},
                         {"reviewer": "openai-chatgpt-external-reviewer"},
                         {"external_review": "verbal"}):
            with self.subTest(override=override):
                with self.assertRaises(supervisor.LiveSwapError):
                    self.validate(self.approval_record(**override))

    def test_verbal_approval_requires_the_named_reviewer_and_current_ci(self):
        record = self.approval_record(
            approval_mode="verbal",
            reviewer="openai-chatgpt-external-reviewer",
            source_policy_reviewed=True)
        for key in ("external_review", "external_review_waiver"):
            record.pop(key)
        self.assertEqual(self.validate(record), RUN_ID)
        record["ci_workflows"] = [supervisor.REQUIRED_CI_WORKFLOWS[0]]
        with self.assertRaises(supervisor.LiveSwapError):
            self.validate(record)
        unnamed = self.approval_record(approval_mode="verbal")
        with self.assertRaisesRegex(supervisor.LiveSwapError, "named external"):
            self.validate(unnamed)

    def test_approval_rejects_substituted_target_identity(self):
        record = self.approval_record()
        target = self.target()
        target["partuuid"] = "substituted-partuuid"
        with self.assertRaisesRegex(supervisor.LiveSwapError, "target evidence"):
            self.validate(record, target=target)

    def test_approval_rejects_any_fallback_or_unbound_pressure_parameter(self):
        with self.assertRaisesRegex(supervisor.LiveSwapError, "no-fallback"):
            self.validate(self.approval_record(
                fallback={"path": "/synthetic/fallback.swap"}))
        with self.assertRaisesRegex(supervisor.LiveSwapError, "exact live-swap"):
            self.validate(self.approval_record(pressure_pages=1))

    def test_normal_mock_trial_finishes_and_restores_original_swap(self):
        ops = FakeOps()
        result, state_dir = self.run_mock_trial(ops)
        self.assertEqual(result["live_swap_trial"], "PASS")
        self.assertEqual(result["stop_reason"], "duration_complete")
        self.assertEqual(result["pressure_phase"]["status"], "PASS")
        self.assertEqual(ops.pressure_calls, 1)
        self.assertEqual(result["recovery_disposition"], "COMPLETE")
        self.assertTrue(result["normal_swap_restored"])
        self.assertTrue(ops.original_active)
        self.assertFalse(ops.mapper_exists)
        self.assertFalse(ops.module)
        self.assertEqual(ops.header, ops.original)
        self.assertEqual(result["kernel_diagnostics"]["source"], "synthetic")
        self.assertTrue((state_dir / supervisor.RESULTS_NAME).is_file())

    def test_low_drain_headroom_stops_early_and_reports_safe_stop(self):
        ops = FakeOps()

        def low_headroom(state_dir, state, results, fake_ops, *, first=False):
            sample = self.observation_with_live_pages(
                state_dir, state, results, fake_ops, first=first)
            if len(results["observations"]) >= 2:
                sample["drain_headroom_bytes"] = (
                    supervisor.TRIAL_HEADROOM_BYTES - 1)
            return sample

        result, _state_dir = self.run_mock_trial(
            ops, observation_fn=low_headroom)
        self.assertEqual(result["stop_reason"], "mapper_drain_headroom_low")
        self.assertEqual(result["live_swap_trial"], "SAFE_STOP")
        self.assertTrue(result["normal_swap_restored"])
        self.assertTrue(ops.original_active)
        self.assertFalse(ops.mapper_exists)

    def test_memory_pressure_during_trial_is_a_safe_stop_and_restores(self):
        ops = FakeOps()

        def pressure_after_first(state_dir, state, results, fake_ops, *, first=False):
            if len(results.get("observations", [])) >= 2:
                raise supervisor.SafeStop(
                    "memory_pressure",
                    "memory pressure reached the conservative stop threshold")
            return self.observation_with_live_pages(
                state_dir, state, results, fake_ops, first=first)

        result, _state_dir = self.run_mock_trial(
            ops, observation_fn=pressure_after_first)
        self.assertEqual(result["live_swap_trial"], "SAFE_STOP")
        self.assertEqual(result["stop_reason"], "memory_pressure")
        self.assertTrue(ops.original_active)
        self.assertFalse(ops.mapper_exists)

    def test_failed_pressure_verification_fails_and_restores_original_swap(self):
        ops = FakeOps(pressure_mode="mismatch")
        with self.assertRaisesRegex(supervisor.LiveSwapError,
                                    "normal swap restored"):
            self.run_mock_trial(ops)
        self.assertTrue(ops.original_active)
        self.assertFalse(ops.mapper_exists)
        self.assertFalse(ops.module)
        self.assertEqual(ops.header, ops.original)

    def test_operator_stop_during_pressure_is_safe_stop(self):
        ops = FakeOps(pressure_mode="stop")
        result, _state_dir = self.run_mock_trial(ops)
        self.assertEqual(result["live_swap_trial"], "SAFE_STOP")
        self.assertEqual(result["stop_reason"], "operator_stop")
        self.assertTrue(ops.original_active)
        self.assertFalse(ops.mapper_exists)

    def test_pressure_oom_is_a_failed_trial_that_still_restores(self):
        ops = FakeOps(pressure_mode="oom")
        with self.assertRaisesRegex(supervisor.LiveSwapError,
                                    "normal swap restored"):
            self.run_mock_trial(ops)
        self.assertTrue(ops.original_active)
        self.assertFalse(ops.mapper_exists)

    def test_cleanup_with_insufficient_drain_capacity_preserves_active_mapper(self):
        ops = FakeOps(low_memory=True)
        with self.assertRaisesRegex(supervisor.LiveSwapError, "REQUIRES_REVIEW"):
            self.run_mock_trial(ops)
        self.assertTrue(ops.mapper_exists)
        self.assertTrue(ops.mapper_active)
        self.assertFalse(ops.original_active)
        self.assertEqual(ops.header, ops.formatted)
        self.assertFalse(any(Path(call[0]).name == "swapoff" and
                             "/dev/mapper/" in call[-1]
                             for call in ops.mutations))

    def test_interrupted_activation_restores_without_advancing_to_mapper(self):
        ops = FakeOps(stop_after_format=True)
        result, _state_dir = self.run_mock_trial(ops)
        self.assertEqual(result["live_swap_trial"], "SAFE_STOP")
        self.assertTrue(ops.original_active)
        self.assertFalse(ops.mapper_exists)
        self.assertFalse(ops.module)
        self.assertEqual(ops.header, ops.original)
        self.assertFalse(any(Path(call[0]).name == "dmsetup" and
                             call[1] == "create" for call in ops.mutations))

    def test_format_completed_before_durable_header_commit_is_not_guessed(self):
        ops = FakeOps()
        original_record = supervisor._record_phase

        def interrupt_after_formatter(state_dir, state, results, fake_ops,
                                      phase, argv, **kwargs):
            result = original_record(
                state_dir, state, results, fake_ops, phase, argv, **kwargs)
            if phase == "format_swz":
                raise KeyboardInterrupt("simulated crash before header digest commit")
            return result

        with mock.patch.object(supervisor, "_record_phase",
                               side_effect=interrupt_after_formatter):
            with self.assertRaisesRegex(supervisor.LiveSwapError,
                                        "REQUIRES_REVIEW"):
                self.run_mock_trial(ops)
        self.assertFalse(ops.original_active)
        self.assertEqual(ops.header, ops.formatted)
        self.assertFalse(ops.module)
        self.assertFalse(any(Path(call[0]).name == "swapon" and
                             call[-1] == supervisor.DEVICE_PATH
                             for call in ops.mutations))

    def test_mapper_mkswap_failure_restores_normal_swap(self):
        ops = FakeOps(fail_phase="mkswap")
        with self.assertRaisesRegex(supervisor.LiveSwapError,
                                    "normal swap restored"):
            self.run_mock_trial(ops)
        self.assertTrue(ops.original_active)
        self.assertFalse(ops.mapper_exists)
        self.assertFalse(ops.module)
        self.assertEqual(ops.header, ops.original)
        self.assertTrue(any(Path(call[0]).name == "mkswap" and
                            call[-1].startswith("/dev/mapper/")
                            for call in ops.mutations))

    def test_mapper_swapon_failure_restores_normal_swap_without_retry(self):
        ops = FakeOps(fail_phase="mapper_swapon")
        with self.assertRaisesRegex(supervisor.LiveSwapError,
                                    "normal swap restored"):
            self.run_mock_trial(ops)
        mapper_swapon = [call for call in ops.mutations
                         if Path(call[0]).name == "swapon" and
                         "--priority" in call]
        self.assertEqual(len(mapper_swapon), 1)
        self.assertTrue(ops.original_active)
        self.assertFalse(ops.mapper_exists)
        self.assertFalse(ops.module)
        self.assertEqual(ops.header, ops.original)

    def test_lost_module_provenance_stops_before_unload_or_header_restore(self):
        ops = FakeOps()
        original_record = supervisor._record_phase

        def fail_after_module_insert(state_dir, state, results, fake_ops,
                                     phase, argv, **kwargs):
            if phase == "load_module":
                fake_ops.mutate(argv)
                raise KeyboardInterrupt("simulated process loss after insmod")
            return original_record(
                state_dir, state, results, fake_ops, phase, argv, **kwargs)

        with mock.patch.object(supervisor, "_record_phase",
                               side_effect=fail_after_module_insert):
            with self.assertRaisesRegex(supervisor.LiveSwapError,
                                        "REQUIRES_REVIEW"):
                self.run_mock_trial(ops)
        self.assertTrue(ops.module)
        self.assertFalse(ops.original_active)
        self.assertEqual(ops.header, ops.formatted)
        self.assertFalse(any(Path(call[0]).name == "rmmod"
                             for call in ops.mutations))

    def test_partial_mapper_removal_preserves_formatted_backing_and_module(self):
        ops = FakeOps(fail_phase="remove_mapper")
        with self.assertRaisesRegex(supervisor.LiveSwapError,
                                    "REQUIRES_REVIEW"):
            self.run_mock_trial(ops)
        self.assertTrue(ops.mapper_exists)
        self.assertFalse(ops.mapper_active)
        self.assertTrue(ops.module)
        self.assertEqual(ops.header, ops.formatted)
        self.assertFalse(any(Path(call[0]).name == "swapon" and
                             call[-1] == supervisor.DEVICE_PATH
                             for call in ops.mutations))

    def test_original_swapoff_failure_is_not_retried(self):
        ops = FakeOps(fail_phase="original_swapoff")
        with self.assertRaisesRegex(supervisor.LiveSwapError,
                                    "normal swap restored"):
            self.run_mock_trial(ops)
        attempts = [call for call in ops.mutations
                    if Path(call[0]).name == "swapoff" and call[-1] == supervisor.DEVICE_PATH]
        self.assertEqual(len(attempts), 1)
        self.assertTrue(ops.original_active)
        self.assertEqual(ops.header, ops.original)

    def test_mapper_swapoff_failure_with_live_pages_keeps_mapper_and_header(self):
        ops = FakeOps(fail_phase="mapper_swapoff")
        with mock.patch.object(supervisor, "_save_observation",
                               side_effect=self.observation_with_live_pages):
            with self.assertRaisesRegex(supervisor.LiveSwapError,
                                        "REQUIRES_REVIEW"):
                self.run_mock_trial(ops)
        self.assertTrue(ops.mapper_exists)
        self.assertTrue(ops.mapper_active)
        self.assertFalse(ops.original_active)
        self.assertEqual(ops.header, ops.formatted)
        self.assertFalse(any(Path(call[0]).name == "dmsetup" and
                             call[1] == "remove" for call in ops.mutations))
        self.assertFalse(any(Path(call[0]).name == "swapon" and
                             call[-1] == supervisor.DEVICE_PATH for call in ops.mutations))

    def test_substituted_target_stops_cleanup_without_removing_mapper(self):
        ops = FakeOps(bad_target_after_mapping=True)
        with self.assertRaisesRegex(supervisor.LiveSwapError,
                                    "REQUIRES_REVIEW"):
            self.run_mock_trial(ops)
        self.assertTrue(ops.mapper_exists)
        self.assertTrue(ops.mapper_active)
        self.assertEqual(ops.header, ops.formatted)
        self.assertFalse(any(Path(call[0]).name == "dmsetup" and
                             call[1] == "remove" for call in ops.mutations))

    def test_ambiguous_header_is_not_overwritten_during_recovery(self):
        ops = FakeOps(bad_formatted_header=True)
        with self.assertRaisesRegex(supervisor.LiveSwapError,
                                    "REQUIRES_REVIEW"):
            self.run_mock_trial(ops)
        self.assertFalse(ops.original_active)
        self.assertEqual(ops.header, b"?" * supervisor.PAGE_BYTES)
        self.assertFalse(any(Path(call[0]).name == "swapon" and
                             call[-1] == supervisor.DEVICE_PATH for call in ops.mutations))

    def test_canonical_header_classifier_rejects_torn_or_unrecognized_bytes(self):
        state = {"original_header_sha256": "0" * 64,
                 "formatted_header_sha256": "1" * 64,
                 "size_bytes": supervisor.DEVICE_SIZE_BYTES,
                 "stage": "RECOVERY_REQUIRED",
                 "recovery_previous_stage": "SWZ_FORMATTED"}
        with mock.patch.object(supervisor.PHYSICAL, "swapz_header_valid",
                               return_value=False):
            with self.assertRaisesRegex(supervisor.LiveSwapError, "ambiguous"):
                supervisor._recognized_current_header(b"?" * 4096, state)

    def test_standalone_recovery_unwraps_prior_failed_cleanup(self):
        """Retrying supervised cleanup must not hide the original SWZ stage."""
        ops = FakeOps()
        original = ops.original
        ops.header = ops.formatted
        ops.original_active = False
        state = {
            "schema": "swapz-live-swap-state-v1",
            "run_id": RUN_ID,
            "stage": "RECOVERY_REQUIRED",
            "recovery_previous_stage": "SWZ_FORMATTED",
            "original_swapoff_complete": True,
            "device": supervisor.DEVICE_PATH,
            "major": supervisor.DEVICE_MAJOR,
            "minor": supervisor.DEVICE_MINOR,
            "partuuid": supervisor.DEVICE_PARTUUID,
            "size_bytes": supervisor.DEVICE_SIZE_BYTES,
            "original_header_sha256": hashlib.sha256(original).hexdigest(),
            "formatted_header_sha256": hashlib.sha256(ops.formatted).hexdigest(),
            "swap_path": supervisor.DEVICE_PATH,
            "swap_size_kib": supervisor.DEVICE_SIZE_BYTES // 1024 - 4,
            "swap_priority": -1,
            "dm_name": None,
            "dm_uuid": None,
        }
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / f"swapz-live-{RUN_ID}"
            state_dir.mkdir()
            (state_dir / supervisor.STATE_NAME).write_text(json.dumps(state))
            (state_dir / supervisor.BACKUP_NAME).write_bytes(original)
            (state_dir / supervisor.RESULTS_NAME).write_text(json.dumps({
                "schema": "swapz-live-swap-results-v1",
                "run_id": RUN_ID, "commands": [], "phases": [],
                "observations": [],
            }))
            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(
                    supervisor, "ORIGINAL_HEADER_SHA256",
                    hashlib.sha256(original).hexdigest()))
                stack.enter_context(mock.patch.object(
                    supervisor, "_read_recovery_file",
                    side_effect=lambda path, **_kw: Path(path).read_bytes()))
                stack.enter_context(mock.patch.object(
                    supervisor, "_validate_state"))
                stack.enter_context(mock.patch.object(
                    supervisor, "_assert_recovery_ownership", return_value=True))
                released = stack.enter_context(mock.patch.object(
                    supervisor, "_release_marker"))
                stack.enter_context(mock.patch.object(
                    supervisor.PHYSICAL, "swapz_header_valid",
                    side_effect=lambda header, _size: header == ops.formatted))
                result = supervisor.recover_state(state_dir, ops=ops)
            self.assertEqual(result["status"], "COMPLETE")
            self.assertTrue(ops.original_active)
            self.assertFalse(ops.module)
            self.assertEqual(ops.header, original)
            self.assertEqual(result["state"]["stage"], "COMPLETE")
            self.assertEqual(
                json.loads((state_dir / supervisor.STATE_NAME).read_text())[
                    "stage"], "COMPLETE")
            self.assertEqual(
                [call for call in ops.mutations if call[0] == "swapon"],
                [["swapon", "--", supervisor.DEVICE_PATH]])
            released.assert_called_once()

    def test_header_recovery_rejects_cyclic_or_missing_stage_provenance(self):
        header = b"S" * supervisor.PAGE_BYTES
        state = {
            "original_header_sha256": hashlib.sha256(b"O" * 4096).hexdigest(),
            "formatted_header_sha256": hashlib.sha256(header).hexdigest(),
            "size_bytes": supervisor.DEVICE_SIZE_BYTES,
            "stage": "TRIAL_STOPPING",
            "stage_before_trial_stopping": "RECOVERY_REQUIRED",
            "recovery_previous_stage": "TRIAL_STOPPING",
        }
        with mock.patch.object(supervisor.PHYSICAL, "swapz_header_valid",
                               return_value=True):
            with self.assertRaisesRegex(supervisor.LiveSwapError,
                                        "provenance is ambiguous"):
                supervisor._recognized_current_header(header, state)
            del state["recovery_previous_stage"]
            with self.assertRaisesRegex(supervisor.LiveSwapError,
                                        "provenance is ambiguous"):
                supervisor._recognized_current_header(header, state)

    def test_complete_recovery_observation_is_idempotent(self):
        original = b"O" * supervisor.PAGE_BYTES
        original_digest = hashlib.sha256(original).hexdigest()
        state = {
            "schema": "swapz-live-swap-state-v1", "run_id": RUN_ID,
            "stage": "COMPLETE", "device": supervisor.DEVICE_PATH,
            "major": supervisor.DEVICE_MAJOR, "minor": supervisor.DEVICE_MINOR,
            "partuuid": supervisor.DEVICE_PARTUUID,
            "size_bytes": supervisor.DEVICE_SIZE_BYTES,
            "original_header_sha256": original_digest,
            "swap_size_kib": supervisor.DEVICE_SIZE_BYTES // 1024 - 4,
            "swap_priority": -1, "dm_name": None, "dm_uuid": None,
        }

        class CompleteOps:
            def target_descriptor(self, _state):
                return {"device": supervisor.DEVICE_PATH,
                        "major": supervisor.DEVICE_MAJOR,
                        "minor": supervisor.DEVICE_MINOR,
                        "partuuid": supervisor.DEVICE_PARTUUID,
                        "size_bytes": supervisor.DEVICE_SIZE_BYTES,
                        "header": original}

            def active_swap_for(self, _major, _minor):
                return {"size_kib": state["swap_size_kib"],
                        "priority": -1}

            def read_header(self, _target):
                return original

            def module_loaded(self):
                return False

            def dm_rows(self):
                return []

            def target_holders(self, _major, _minor):
                return []

        fake_ops = CompleteOps()
        encoded_state = json.dumps(state).encode()
        with mock.patch.object(supervisor, "_read_recovery_file",
                               side_effect=[encoded_state, original,
                                            encoded_state, original]), \
                mock.patch.object(supervisor, "_validate_state"), \
                mock.patch.object(supervisor, "_assert_recovery_ownership",
                                  return_value=False), \
                mock.patch.object(supervisor, "ORIGINAL_HEADER_SHA256",
                                  original_digest):
            first = supervisor.recover_state(
                "/synthetic/swapz-live-" + RUN_ID, ops=fake_ops)
            second = supervisor.recover_state(
                "/synthetic/swapz-live-" + RUN_ID, ops=fake_ops)
        self.assertEqual(first["status"], "COMPLETE")
        self.assertEqual(second["status"], "COMPLETE")

    def observation_with_live_pages(self, state_dir, state, results, ops,
                                    *, first=False):
        del state_dir, state
        ops.observations_taken += 1
        count = ops.observations_taken
        ops.mapper_used_kib = 64
        sample = {
            "timestamp": "synthetic",
            "swap_used_kib": 64,
            "swap_size_kib": supervisor.LOGICAL_BYTES // 1024 - 4,
            "swap_priority": 32767,
            "vmstat": {"pswpin": 4 * count, "pswpout": 8 * count},
            "memory": dict(HIGH_MEMORY),
            "drain_headroom_bytes": supervisor._drain_headroom_bytes(
                64, dict(HIGH_MEMORY)),
            "dmsetup_status": {"text": "synthetic", "counters": {
                "logical_write": 4096 * count, "logical_read": 4096 * count,
                "physical_write": 4096 * count, "physical_read": 0,
                "failed": 0, "error": 0}},
            "block_stats": {"available": True,
                            "values": [0, 0, 0, 0, count, 0, 8 * count, 0]},
        }
        results.setdefault("observations", []).append(sample)
        results["max_swapz_used_kib"] = 64
        if first:
            results["trial_baseline"] = sample
        return sample

    def run_mock_trial(self, ops, *, observation_fn=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        state_dir = Path(temporary.name) / f"swapz-live-{RUN_ID}"
        state_dir.mkdir(mode=0o700)
        original = b"O" * supervisor.PAGE_BYTES
        formatted = b"S" * supervisor.PAGE_BYTES
        artifacts = dict(supervisor.EXPECTED_ARTIFACTS)
        target = ops.inspect_target()
        target["header"] = original
        target["swap_size_kib"] = supervisor.DEVICE_SIZE_BYTES // 1024 - 4
        target["swap_priority"] = -1
        target["swap_used_kib"] = 0
        approval = {"run_id": RUN_ID}
        plan = {"status": "PASS", "head": HEAD,
                "approval_sha256": supervisor._approval_digest(approval)}
        fake_state = {
            "schema": "swapz-live-swap-state-v1",
            "run_id": RUN_ID,
            "stage": "PREPARED",
            "created_at": "synthetic",
            "updated_at": "synthetic",
            **supervisor._target_state(target),
            "head": HEAD,
            "qualified_source": supervisor.QUALIFIED_SOURCE,
            "helper_sha256": "a" * 64,
            "artifact_digests": artifacts,
            "artifact_snapshots": {},
            "original_header_sha256": hashlib.sha256(original).hexdigest(),
            "formatted_header_sha256": None,
            "dm_name": None,
            "dm_uuid": None,
            "module_loaded_by_process": False,
            "active_mapper_swap": False,
            "fallback_mode": "none",
            "fallback": None,
            "authorization_sha256": "b" * 64,
        }
        snapshots = {
            "formatter_sha256": Path("/synthetic/swapzctl"),
            "module_sha256": Path("/synthetic/dm-swapz.ko"),
            "oracle_sha256": Path("/synthetic/device-roundtrip"),
        }

        def create_state(_approval, _target, _plan, path, _ops):
            Path(path).mkdir(mode=0o700, exist_ok=True)
            (Path(path) / supervisor.BACKUP_NAME).write_bytes(original)
            return fake_state, original, snapshots

        def fake_status(_ops, _state):
            return {"text": "synthetic", "counters": {
                "logical_write": 0, "logical_read": 0,
                "physical_write": 0, "physical_read": 0,
                "failed": 0, "error": 0, "flush_err": 0,
                "segment_discards_failed": 0}}

        clock = itertools.count(0, 400)
        memory_side_effect = [HIGH_MEMORY, HIGH_MEMORY, LOW_MEMORY] if ops.low_memory else None
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(
                supervisor, "ORIGINAL_HEADER_SHA256",
                hashlib.sha256(original).hexdigest()))
            stack.enter_context(mock.patch.object(
                supervisor, "LIVE_SWAP_EXECUTION_ENABLED", True))
            stack.enter_context(mock.patch.object(supervisor.os, "geteuid", return_value=0))
            stack.enter_context(mock.patch.object(
                supervisor, "read_only_plan", return_value=plan))
            stack.enter_context(mock.patch.object(
                supervisor, "_load_unique_json", return_value=approval))
            stack.enter_context(mock.patch.object(
                supervisor, "validate_approval", return_value=RUN_ID))
            stack.enter_context(mock.patch.object(
                supervisor, "_validate_target_facts", return_value=None))
            stack.enter_context(mock.patch.object(
                supervisor, "_exact_active_swap_inventory", return_value=True))
            stack.enter_context(mock.patch.object(
                supervisor.PHYSICAL, "block_identity",
                side_effect=lambda path: (252, 0) if "mapper" in path else (8, 4)))
            stack.enter_context(mock.patch.object(
                supervisor, "_create_durable_state", side_effect=create_state))
            stack.enter_context(mock.patch.object(
                supervisor.PHYSICAL, "_partition_lock",
                side_effect=lambda _partuuid: os.open(os.devnull, os.O_RDONLY)))
            stack.enter_context(mock.patch.object(
                supervisor.PHYSICAL, "_consume_review", return_value=None))
            stack.enter_context(mock.patch.object(
                supervisor, "_release_marker", return_value=None))
            stack.enter_context(mock.patch.object(
                supervisor, "_verify_artifacts", return_value=artifacts))
            stack.enter_context(mock.patch.object(
                supervisor, "_verify_snapshots", return_value=None))
            stack.enter_context(mock.patch.object(
                supervisor, "_verify_mapper", return_value="/dev/mapper/synthetic"))
            stack.enter_context(mock.patch.object(
                supervisor, "_mapper_info", return_value=(252, 0, 0)))
            stack.enter_context(mock.patch.object(
                supervisor, "_status_snapshot", side_effect=fake_status))
            stack.enter_context(mock.patch.object(
                supervisor, "_save_observation",
                side_effect=observation_fn or self.observation_with_live_pages))
            stack.enter_context(mock.patch.object(
                supervisor, "_memory_sample",
                side_effect=memory_side_effect, return_value=HIGH_MEMORY))
            stack.enter_context(mock.patch.object(
                supervisor, "_read_recovery_file",
                side_effect=lambda path, **_kw: Path(path).read_bytes()))
            stack.enter_context(mock.patch.object(
                supervisor.PHYSICAL, "swapz_header_valid",
                side_effect=lambda data, _size: data == formatted))
            result = supervisor.run_trial(
                "/synthetic/approval.json", state_dir,
                confirm="LIVE-SWAP-TRIAL", ops=ops,
                monotonic=lambda: next(clock), sleep=lambda _seconds: None)
        return result, state_dir

    @staticmethod
    def target():
        return {"device": supervisor.DEVICE_PATH,
                "major": supervisor.DEVICE_MAJOR,
                "minor": supervisor.DEVICE_MINOR,
                "partuuid": supervisor.DEVICE_PARTUUID,
                "size_bytes": supervisor.DEVICE_SIZE_BYTES}

    @staticmethod
    def positive_plan_facts():
        return {
            "repo": {
                "branch": "main", "clean": True, "head": HEAD,
                "origin_main": HEAD, "canonical_main": HEAD,
                "source_ancestor": True, "no_post_qualification_merges": True,
                "production_diff": [], "changed_paths": [],
            },
            "physical_x86_64": True,
            "target": {
                "device": supervisor.DEVICE_PATH,
                "major": supervisor.DEVICE_MAJOR,
                "minor": supervisor.DEVICE_MINOR,
                "partuuid": supervisor.DEVICE_PARTUUID,
                "size_bytes": supervisor.DEVICE_SIZE_BYTES,
                "swap_size_kib": supervisor.DEVICE_SIZE_BYTES // 1024 - 4,
                "swap_used_kib": 0, "swap_priority": -1,
                "header_sha256": supervisor.ORIGINAL_HEADER_SHA256,
                "mounted": False, "holders": [],
                "root_chain_contains_target": False,
            },
            "swap_inventory_exact": True,
            "artifacts": dict(supervisor.EXPECTED_ARTIFACTS),
            "qualification_matches": True,
            "ci": {"status": "PASS", "commit_sha": HEAD,
                   "workflows": list(supervisor.REQUIRED_CI_WORKFLOWS)},
            "recovery": {"persistent": True, "outside_target": True,
                         "root_owned_0700": True, "active_marker": False,
                         "other_unresolved_markers": []},
            "module_loaded": False,
            "owned_mapper_present": False,
            "fallback": None,
            "memory": {"mem_available_bytes": 8 * 1024**3,
                       "mem_total_bytes": 16 * 1024**3,
                       "ram_used_percent": 30.0,
                       "cgroup_headroom_bytes": None,
                       "psi_some_avg10": 0.0, "psi_full_avg10": 0.0},
            "approval": {"validated": True, "run_id_unconsumed": True,
                         "state_directory_unused": True,
                         "fallback_mode": "none",
                         "accept_no_fallback_risk": True},
        }


if __name__ == "__main__":
    unittest.main()
