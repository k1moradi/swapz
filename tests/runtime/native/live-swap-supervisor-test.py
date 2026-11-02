#!/usr/bin/env python3
"""Rootless lifecycle tests for the experimental live-swap supervisor."""
import hashlib
import importlib.util
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


class FakeOps:
    def __init__(self, *, fail_phase=None, stop_after_format=False,
                 bad_target_after_mapping=False, low_memory=False,
                 bad_formatted_header=False):
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

    def fallback_facts(self, _path):
        return dict(FALLBACK)

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
            if self.stop_after_format:
                self.stop_after_format = True
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


FALLBACK = {
    "path": "/synthetic/fallback.swap",
    "device": 1,
    "inode": 2,
    "mode": 0o600,
    "uid": 0,
    "major_minor": "8:3",
    "filesystem": "f2fs",
    "size_bytes": 1024 * 1024 * 1024,
    "allocated_bytes": 1024 * 1024 * 1024,
    "used_kib": 0,
    "size_kib": 1024 * 1024 - 4,
    "priority": 0,
    "same_partition": False,
    "same_physical_device": True,
    "disk_major_minors": ["8:0"],
    "free_bytes": (1024 * 1024 - 4) * 1024,
    "active": True,
    "regular_root_owned_0600": True,
}


class LiveSwapSupervisorTests(unittest.TestCase):
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
        self.assertFalse(supervisor.LIVE_SWAP_EXECUTION_ENABLED)
        with self.assertRaisesRegex(supervisor.LiveSwapError, "mutations are disabled"):
            supervisor.run_trial(
                "/unused", "/unused", confirm="LIVE-SWAP-TRIAL", ops=ops)
        with self.assertRaisesRegex(supervisor.LiveSwapError, "recovery CLI is disabled"):
            supervisor.recover_cli("/unused", confirm="RESTORE-ORIGINAL-SWAP",
                                   ops=ops)

    def test_read_only_plan_never_calls_mutation_channel_and_exposes_trace(self):
        ops = FakeOps()
        ops.host_physical = lambda: True
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            ops.recovery_base = lambda _target: base
            approval = {"fallback": {"path": FALLBACK["path"]}}
            ops.inspect_target = lambda: ops._target()
            ops.fallback_facts = lambda _path: dict(FALLBACK)
            ops.memory_facts = lambda: {
                "MemAvailable": 8 * 1024**3,
                "cgroup_headroom": None,
                "psi_some_avg10": 0.0,
                "psi_full_avg10": 0.0,
            }
            ops.read_swap_rows = lambda: [
                {"kind": "partition", "path": supervisor.DEVICE_PATH},
                {"kind": "file", "path": FALLBACK["path"]},
            ]
            with ExitStack() as stack:
                stack.enter_context(mock.patch.object(
                    supervisor, "_load_unique_json", return_value=approval))
                stack.enter_context(mock.patch.object(
                    supervisor, "validate_approval", return_value=RUN_ID))
                stack.enter_context(mock.patch.object(
                    supervisor, "_validate_target_facts", return_value=None))
                stack.enter_context(mock.patch.object(
                    supervisor.PHYSICAL, "block_identity",
                    side_effect=lambda path: (8, 4) if path == supervisor.DEVICE_PATH
                    else (8, 3)))
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
        facts["approval"]["accept_same_media_fallback"] = False
        plan = supervisor.evaluate_plan(facts)
        self.assertEqual(plan["gates"]["fallback_media_risk"]["status"], "BLOCKED")
        facts = self.positive_plan_facts()
        facts["target"]["swap_used_kib"] = 1
        plan = supervisor.evaluate_plan(facts)
        self.assertEqual(plan["gates"]["target"]["status"], "BLOCKED")
        facts = self.positive_plan_facts()
        facts["fallback"] = None
        plan = supervisor.evaluate_plan(facts)
        self.assertEqual(plan["gates"]["fallback"]["status"], "BLOCKED")
        facts = self.positive_plan_facts()
        facts["fallback"]["same_partition"] = True
        facts["fallback"]["major_minor"] = "8:4"
        plan = supervisor.evaluate_plan(facts)
        self.assertEqual(plan["gates"]["fallback"]["status"], "BLOCKED")
        facts = self.positive_plan_facts()
        facts["fallback"]["priority"] = -1
        plan = supervisor.evaluate_plan(facts)
        self.assertEqual(plan["gates"]["fallback"]["status"], "BLOCKED")
        facts = self.positive_plan_facts()
        facts["fallback"]["same_physical_device"] = False
        facts["approval"]["accept_same_media_fallback"] = False
        plan = supervisor.evaluate_plan(facts)
        self.assertEqual(plan["gates"]["fallback_media_risk"]["status"], "PASS")

    def test_active_swap_inventory_requires_exact_target_and_fallback(self):
        class Inventory:
            def __init__(self, rows):
                self.rows = rows

            def read_swap_rows(self):
                return self.rows

        with mock.patch.object(supervisor.PHYSICAL, "block_identity",
                               side_effect=lambda path: (
                                   (8, 8) if path == "/dev/other" else (8, 4))):
            self.assertTrue(supervisor._exact_active_swap_inventory(
                Inventory([
                    {"kind": "partition", "path": "/dev/sda4"},
                    {"kind": "file", "path": FALLBACK["path"]},
                ]), FALLBACK["path"]))
            with self.assertRaisesRegex(supervisor.LiveSwapError, "differs"):
                supervisor._exact_active_swap_inventory(
                    Inventory([
                        {"kind": "partition", "path": "/dev/sda4"},
                        {"kind": "file", "path": FALLBACK["path"]},
                        {"kind": "partition", "path": "/dev/other"},
                    ]), FALLBACK["path"])

    def test_actual_swap_io_requires_swapz_and_lower_device_deltas(self):
        baseline = {
            "vmstat": {"pswpin": 0, "pswpout": 0},
            "dmsetup_status": {"counters": {"logical_write": 0}},
            "block_stats": {"available": True, "values": [0] * 8},
        }
        sample = {
            "vmstat": {"pswpin": 0, "pswpout": 1},
            "dmsetup_status": {"counters": {"logical_write": 4096}},
            "swap_used_kib": 4,
            "block_stats": {"available": True,
                            "values": [0, 0, 0, 0, 1, 0, 8, 0]},
        }
        result = {"trial_baseline": baseline, "observations": [sample]}
        self.assertTrue(supervisor._actual_swap_io(result))
        sample["block_stats"] = {"available": False}
        self.assertFalse(supervisor._actual_swap_io(result))

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

    def test_memory_pressure_thresholds_fail_closed(self):
        good = {"mem_available_bytes": 4 * 1024**3,
                "cgroup_headroom_bytes": 1024**3,
                "psi_some_avg10": 0.0, "psi_full_avg10": 0.0}
        supervisor._check_memory_sample(good)
        for key, value in (
                ("mem_available_bytes", 1),
                ("cgroup_headroom_bytes", 1),
                ("psi_some_avg10", supervisor.MAX_MEMORY_SOME_AVG10),
                ("psi_full_avg10", supervisor.MAX_MEMORY_FULL_AVG10)):
            sample = dict(good)
            sample[key] = value
            with self.subTest(key=key):
                with self.assertRaisesRegex(supervisor.LiveSwapError, "pressure"):
                    supervisor._check_memory_sample(sample)

    def test_approval_requires_commit_bound_review_and_both_current_ci_workflows(self):
        record = self.approval()
        record.update({
            "approved": True,
            "approval_mode": "verbal",
            "reviewer": "openai-chatgpt-external-reviewer",
            "approval_text": supervisor.LIVE_APPROVAL_TEXT,
            "owner_authorized": True,
            "owner_approval_text": supervisor.OWNER_APPROVAL_TEXT,
            "source_policy_reviewed": True,
            "issue_number": 76,
            "review_reference": f"https://github.com/k1moradi/swapz/commit/{HEAD}",
            "reviewed_commit_sha": HEAD,
            "ci_commit_sha": HEAD,
            "ci_status": "PASS",
            "ci_workflows": list(supervisor.REQUIRED_CI_WORKFLOWS),
            "fallback": supervisor._fallback_binding(FALLBACK),
            "accept_same_media_fallback": True,
            "run_id": RUN_ID,
            "source_sha": supervisor.QUALIFIED_SOURCE,
            "helper_git_sha": HEAD,
            "helper_sha256": "a" * 64,
            "device_uuid_path": supervisor.DEVICE_UUID_PATH,
            "device": supervisor.DEVICE_PATH,
            "device_major_minor": "8:4",
            "device_partuuid": supervisor.DEVICE_PARTUUID,
            "device_size_bytes": supervisor.DEVICE_SIZE_BYTES,
            "original_header_sha256": supervisor.ORIGINAL_HEADER_SHA256,
            "logical_capacity_bytes": supervisor.LOGICAL_BYTES,
            "duration_seconds": supervisor.TRIAL_SECONDS,
            "scope": "experimental live Linux swap trial only",
            "artifact_digests": dict(supervisor.EXPECTED_ARTIFACTS),
        })
        self.assertEqual(supervisor.validate_approval(
            record, head=HEAD, helper_sha256="a" * 64,
            artifacts=supervisor.EXPECTED_ARTIFACTS,
            target=self.target(), fallback=FALLBACK), RUN_ID)
        record["ci_workflows"] = [supervisor.REQUIRED_CI_WORKFLOWS[0]]
        with self.assertRaises(supervisor.LiveSwapError):
            supervisor.validate_approval(
                record, head=HEAD, helper_sha256="a" * 64,
                artifacts=supervisor.EXPECTED_ARTIFACTS,
                target=self.target(), fallback=FALLBACK)

    def test_approval_rejects_substituted_target_identity(self):
        record = self.approval()
        record.update({
            "approved": True,
            "approval_mode": "verbal",
            "reviewer": "openai-chatgpt-external-reviewer",
            "approval_text": supervisor.LIVE_APPROVAL_TEXT,
            "owner_authorized": True,
            "owner_approval_text": supervisor.OWNER_APPROVAL_TEXT,
            "source_policy_reviewed": True,
            "issue_number": 76,
            "review_reference": f"https://github.com/k1moradi/swapz/commit/{HEAD}",
            "reviewed_commit_sha": HEAD,
            "ci_commit_sha": HEAD,
            "ci_status": "PASS",
            "ci_workflows": list(supervisor.REQUIRED_CI_WORKFLOWS),
            "fallback": supervisor._fallback_binding(FALLBACK),
            "accept_same_media_fallback": True,
            "run_id": RUN_ID,
            "source_sha": supervisor.QUALIFIED_SOURCE,
            "helper_git_sha": HEAD,
            "helper_sha256": "a" * 64,
            "device_uuid_path": supervisor.DEVICE_UUID_PATH,
            "device": supervisor.DEVICE_PATH,
            "device_major_minor": "8:4",
            "device_partuuid": supervisor.DEVICE_PARTUUID,
            "device_size_bytes": supervisor.DEVICE_SIZE_BYTES,
            "original_header_sha256": supervisor.ORIGINAL_HEADER_SHA256,
            "logical_capacity_bytes": supervisor.LOGICAL_BYTES,
            "duration_seconds": supervisor.TRIAL_SECONDS,
            "scope": "experimental live Linux swap trial only",
            "artifact_digests": dict(supervisor.EXPECTED_ARTIFACTS),
        })
        target = self.target()
        target["partuuid"] = "substituted-partuuid"
        with self.assertRaisesRegex(supervisor.LiveSwapError, "target evidence"):
            supervisor.validate_approval(
                record, head=HEAD, helper_sha256="a" * 64,
                artifacts=supervisor.EXPECTED_ARTIFACTS,
                target=target, fallback=FALLBACK)

    def test_normal_mock_trial_finishes_and_restores_original_swap(self):
        ops = FakeOps()
        result, state_dir = self.run_mock_trial(ops)
        self.assertEqual(result["live_swap_trial"], "PASS")
        self.assertEqual(result["recovery_disposition"], "COMPLETE")
        self.assertTrue(result["normal_swap_restored"])
        self.assertTrue(ops.original_active)
        self.assertFalse(ops.mapper_exists)
        self.assertFalse(ops.module)
        self.assertEqual(ops.header, ops.original)
        self.assertEqual(result["kernel_diagnostics"]["source"], "synthetic")
        self.assertTrue((state_dir / supervisor.RESULTS_NAME).is_file())

    def test_interrupted_activation_restores_without_advancing_to_mapper(self):
        ops = FakeOps(stop_after_format=True)
        with self.assertRaisesRegex(supervisor.LiveSwapError,
                                    "normal swap restored"):
            self.run_mock_trial(ops)
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
                                      phase, argv):
            result = original_record(
                state_dir, state, results, fake_ops, phase, argv)
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
                                     phase, argv):
            if phase == "load_module":
                fake_ops.mutate(argv)
                raise KeyboardInterrupt("simulated process loss after insmod")
            return original_record(
                state_dir, state, results, fake_ops, phase, argv)

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

    def test_low_memory_with_active_swap_pages_stops_before_mapper_swapoff(self):
        ops = FakeOps(low_memory=True)
        with mock.patch.object(supervisor, "_save_observation",
                               side_effect=self.observation_with_live_pages):
            with self.assertRaisesRegex(supervisor.LiveSwapError,
                                        "REQUIRES_REVIEW"):
                self.run_mock_trial(ops)
        self.assertTrue(ops.mapper_active)
        self.assertTrue(ops.mapper_exists)
        self.assertFalse(any(Path(call[0]).name == "swapoff" and
                             "/dev/mapper/" in call[-1] for call in ops.mutations))
        self.assertEqual(ops.header, ops.formatted)

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

    def observation_with_live_pages(self, state_dir, state, results, _ops,
                                    *, first=False):
        del state_dir, state
        _ops.mapper_used_kib = 64
        sample = {"timestamp": "synthetic", "swap_used_kib": 64,
                  "swap_size_kib": supervisor.LOGICAL_BYTES // 1024 - 4,
                  "swap_priority": 32767,
                  "vmstat": {"pswpin": 0, "pswpout": 1},
                  "memory": {"mem_available_bytes": 8 * 1024**3,
                             "cgroup_headroom_bytes": None,
                             "psi_some_avg10": 0.0, "psi_full_avg10": 0.0},
                  "fallback_used_kib": 0, "fallback_free_bytes": FALLBACK["free_bytes"],
                  "dmsetup_status": {"text": "synthetic", "counters": {
                      "logical_write": 4096, "logical_read": 0,
                      "physical_write": 4096, "physical_read": 0,
                      "failed": 0, "error": 0}},
                  "block_stats": {"available": True, "values": [0] * 8}}
        results.setdefault("observations", []).append(sample)
        results["max_swapz_used_kib"] = 64
        if first:
            results["trial_baseline"] = sample
        return sample

    def run_mock_trial(self, ops):
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
        fallback = dict(FALLBACK)
        plan = {"status": "PASS", "head": HEAD, "fallback": fallback}
        approval = {"run_id": RUN_ID, "fallback": {"path": fallback["path"]}}
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
            "fallback": fallback,
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

        clock = iter((0, 1000, 2000, 3000, 4000, 5000, 6000))
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
                supervisor, "_verify_fallback", return_value=fallback))
            stack.enter_context(mock.patch.object(
                supervisor, "_verify_mapper", return_value="/dev/mapper/synthetic"))
            stack.enter_context(mock.patch.object(
                supervisor, "_mapper_info", return_value=(252, 0, 0)))
            stack.enter_context(mock.patch.object(
                supervisor, "_status_snapshot", side_effect=fake_status))
            stack.enter_context(mock.patch.object(
                supervisor, "_save_observation", side_effect=self.observation_with_live_pages))
            stack.enter_context(mock.patch.object(
                supervisor, "_actual_swap_io", return_value=True))
            high_memory = {
                "mem_available_bytes": 8 * 1024**3,
                "cgroup_headroom_bytes": None,
                "psi_some_avg10": 0.0, "psi_full_avg10": 0.0,
            }
            low_memory = {
                "mem_available_bytes": 1024,
                "cgroup_headroom_bytes": 1024,
                "psi_some_avg10": 20.0, "psi_full_avg10": 10.0,
            }
            memory_patch = mock.patch.object(
                supervisor, "_memory_sample",
                side_effect=[high_memory, low_memory] if ops.low_memory else None,
                return_value=high_memory)
            stack.enter_context(memory_patch)
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
            "fallback": {
                "active": True,
                "regular_root_owned_0600": True,
                "allocated_bytes": FALLBACK["allocated_bytes"],
                "size_bytes": FALLBACK["size_bytes"],
                "free_bytes": FALLBACK["free_bytes"],
                "same_partition": False,
                "major_minor": "8:3",
                "priority": FALLBACK["priority"],
                "same_physical_device": True,
            },
            "memory": {"mem_available_bytes": 8 * 1024**3,
                       "cgroup_headroom_bytes": None,
                       "psi_some_avg10": 0.0, "psi_full_avg10": 0.0},
            "approval": {"validated": True, "run_id_unconsumed": True,
                          "state_directory_unused": True,
                          "accept_same_media_fallback": True},
        }

    @staticmethod
    def approval():
        return {}


HEAD = "c" * 40
RUN_ID = "d" * 32


if __name__ == "__main__":
    unittest.main()
