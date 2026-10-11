#!/usr/bin/env python3
"""Rootless lifecycle and fail-closed contracts for virtual-smoke.py."""

from __future__ import annotations

import importlib.util
import ast
import hashlib
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tests/runtime/virtual-smoke.py"
SPEC = importlib.util.spec_from_file_location("swapz_virtual_smoke", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
SMOKE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SMOKE
SPEC.loader.exec_module(SMOKE)


GOOD_STATUS = {
    "staged_hits": 0,
    "staged_early": 1,
    "inflight_blocks": 1,
    "async_cb": 1,
    "failed": 0,
    "pack_records": 0,
    "fill_blocks": 0,
    "buf0_blocks": 1,
    "buf1_blocks": 0,
}

# The actual STATUSTYPE_INFO DMEMIT layout in kernel/dm-swapz.c: this is
# intentionally NOT a fabricated dictionary of already-parsed counters.
REAL_KERNEL_STATUS = (
    "0 8 swapz strategy=staged batch_kib=64 fill_id=1 inflight_id=0 "
    "inflight_blocks=1 fill_blocks=0 pack_records=0 async_cb=1 "
    "buf0_state=2 buf0_blocks=1 buf1_state=0 buf1_blocks=0 "
    "segment=0/32 head_blocks=4 free_segments=30 live_blocks=1 "
    "logical_write=4096 physical_write=0 physical_write_reqs=1 "
    "multi_write_reqs=0 max_write_batch=1 stream_submit=4096 "
    "async_timeouts=0 staged_hits=0 staged_early=1 staged_cancel=0 "
    "staged_cancel_blocks=0 logical_read=0 physical_read=0 "
    "compressed_payload=128 compressed_pages=1 raw_pages=0 "
    "upper_discards=0 rotations=0 segment_cycle_min=0 segment_cycle_max=0 "
    "gc_victims=0 gc_scanned=0 gc_pages=0 gc_read=0 gc_write=0 "
    "lower_discard=on discard_bytes=0 discard_failures=0 failed=0"
)


def production_status(**overrides):
    """Keep every real-kernel mixed-type field while adjusting mock counters."""
    parts = REAL_KERNEL_STATUS.split()
    changes = {name: str(value) for name, value in overrides.items()}
    observed = set()
    for index, token in enumerate(parts):
        if "=" not in token:
            continue
        key, _ = token.split("=", 1)
        if key in changes:
            parts[index] = key + "=" + changes[key]
            observed.add(key)
    if set(changes) != observed:
        raise AssertionError(f"unknown production status overrides: {set(changes) - observed}")
    return " ".join(parts)


class FakeOps:
    def __init__(self, fail_at: str | None = None, timeout_at: str | None = None,
                 uncertainty_at: str | None = None, bad_pre_read: bool = False):
        self.fail_at = fail_at
        self.timeout_at = timeout_at
        self.uncertainty_at = uncertainty_at
        self.bad_pre_read = bad_pre_read
        self.open_target = False
        self.actions: list[tuple] = []
        self.created: dict[str, tuple[str, str]] = {}
        self.loaded = False
        self.suspended = False
        self.status_calls = 0
        self.preflight_calls = 0
        self.quarantine: dict | None = None
        self.page = bytes([0xA5]) * SMOKE.PAGE_BYTES
        self.read_number = 0

    def preflight(self, config, names):
        self.preflight_calls += 1
        self.actions.append(("preflight", names))
        return 30000

    def make_run_dir(self, run_id):
        self.actions.append(("mkdir", run_id))
        return Path("/dev/shm/swapz-v22-smoke-test")

    def make_page_and_backing(self, run_dir):
        self.actions.append(("fixture",))
        return run_dir / "payload", run_dir / "backing", self.page

    def load_module(self, module):
        self.actions.append(("insmod", str(module)))
        if self.fail_at == "module":
            raise SMOKE.SetupFailure("injected confirmed module load failure")
        if self.timeout_at == "module":
            raise SMOKE.CommandTimeout("injected module timeout")
        self.loaded = True

    def module_loaded(self):
        return self.loaded

    def targets(self):
        return {"delay", "swapz"} if self.loaded else {"delay"}

    def attach_loop(self, image):
        self.actions.append(("losetup-create", str(image)))
        if self.fail_at == "loop":
            raise SMOKE.SetupFailure("injected confirmed loop setup failure")
        if self.timeout_at == "loop":
            raise SMOKE.CommandTimeout("injected loop timeout")
        return "/dev/loop-test"

    def verify_loop(self, loop, image):
        self.actions.append(("verify-loop", loop, str(image)))
        return loop == "/dev/loop-test"

    def device_number(self, path):
        if path == "/dev/loop-test":
            return "7:0"
        if path.startswith("/dev/mapper/swapz-smoke-delay-"):
            return "253:0"
        raise AssertionError(f"unexpected device number request: {path}")

    def loop_holders_empty(self, loop):
        self.actions.append(("loop-holders", loop))
        return True

    def detach_loop(self, loop):
        self.actions.append(("losetup-detach", loop))

    def loop_exists(self, loop):
        self.actions.append(("loop-exists", loop))
        return False

    def dm_create(self, name, uuid, table):
        self.actions.append(("dm-create", name, uuid, table))
        if self.fail_at == name.split("-")[-1]:
            raise SMOKE.SetupFailure(f"injected confirmed {name} create failure")
        if self.timeout_at == name.split("-")[-1]:
            raise SMOKE.CommandTimeout(f"injected ambiguous {name} create timeout")
        if self.fail_at == "delay" and "-delay-" in name:
            raise SMOKE.SetupFailure("injected confirmed delay create failure")
        if self.fail_at == "target" and "-target-" in name:
            raise SMOKE.SetupFailure("injected confirmed target create failure")
        self.created[name] = (uuid, table)

    def dm_exists(self, name):
        return name in self.created

    def dm_uuid(self, name):
        return self.created[name][0]

    def dm_open_count(self, name):
        return 1 if self.open_target and "-target-" in name else 0

    def dm_table(self, name):
        table = self.created[name][1].split()
        if table[2] == "swapz":
            table[3] = "253:0"
        self.actions.append(("dm-table", name, tuple(table)))
        return table

    def dm_status(self, name):
        self.actions.append(("status", name))
        if self.uncertainty_at == "status":
            raise SMOKE.QuarantineRequired("injected callback/status uncertainty")
        self.status_calls += 1
        status = dict(GOOD_STATUS)
        if self.status_calls == 1:
            status["inflight_blocks"] = 1
            status["async_cb"] = 1
        elif self.status_calls == 2:
            status["staged_hits"] = 1
            status["inflight_blocks"] = 1
            status["async_cb"] = 1
        else:
            status["staged_hits"] = 1
            status["inflight_blocks"] = 0
            status["async_cb"] = 0
            status["buf0_blocks"] = 0
        return status

    def dm_is_suspended(self, name):
        self.actions.append(("suspended-query", name))
        if self.suspended and self.uncertainty_at == "suspended-query":
            raise SMOKE.QuarantineRequired("injected suspended-state query uncertainty")
        return self.suspended

    def dm_suspend(self, name):
        self.actions.append(("suspend", name))
        if self.timeout_at == "suspend":
            raise SMOKE.CommandTimeout("injected suspend timeout")
        self.suspended = True

    def dm_resume(self, name):
        self.actions.append(("resume", name))
        self.suspended = False

    def dm_remove(self, name):
        self.actions.append(("dm-remove", name))
        if self.fail_at == "remove-target" and "-target-" in name:
            raise SMOKE.QuarantineRequired("injected remove failure")
        self.created.pop(name, None)

    def dm_holders_empty(self, name):
        self.actions.append(("dm-holders", name))
        return True

    def write_page(self, target, payload):
        self.actions.append(("write-4k", target, str(payload)))
        if self.timeout_at == "write":
            raise SMOKE.CommandTimeout("injected write timeout")

    def read_page(self, target, output):
        self.read_number += 1
        self.actions.append(("read-4k", target, str(output)))
        if self.bad_pre_read and self.read_number == 1:
            return bytes([0]) * SMOKE.PAGE_BYTES
        return self.page

    def new_kernel_messages(self):
        if self.uncertainty_at == "kernel-warning":
            return ["dm-swapz: WARNING: injected warning"]
        return []

    def sleep(self, seconds):
        # The normal successful mock always reaches the first in-flight poll.
        raise SMOKE.QuarantineRequired("mock unexpectedly needed a delayed poll")

    def unload_module(self):
        self.actions.append(("rmmod",))
        self.loaded = False

    def remove_run_dir(self, run_dir):
        self.actions.append(("remove-run-dir", str(run_dir)))

    def quarantine_record(self, owned, reason, latest_status, messages):
        self.actions.append(("quarantine", reason))
        self.quarantine = {
            "reason": reason,
            "status": latest_status,
            "messages": messages,
            "owned": dict(vars(owned)),
        }


def good_config(**overrides):
    values = dict(
        vm_id="disposable-test-vm",
        source_sha="a" * 40,
        module_path=Path("/root/dm-swapz.ko"),
        module_sha256="b" * 64,
        live=True,
    )
    values.update(overrides)
    return SMOKE.Config(**values)


class VirtualSmokeContracts(unittest.TestCase):
    def test_missing_live_authorization_is_rejected_before_preflight(self):
        ops = FakeOps()
        config = good_config(live=False)
        with self.assertRaisesRegex(SMOKE.SmokeFailure, "--run-live"):
            SMOKE.SmokeRunner(config, ops).run()
        self.assertEqual(ops.preflight_calls, 0)
        self.assertEqual(ops.actions, [])

    def test_approval_phrase_not_needed_but_vm_and_module_identity_required(self):
        config = good_config(vm_id="workstation")
        with self.assertRaisesRegex(SMOKE.SmokeFailure, "disposable-"):
            SMOKE.validate_cli_config(config)
        config = good_config()
        SMOKE.validate_cli_config(config)
        self.assertFalse(hasattr(config, "authorization"))
        for value, error in (("invalid", "--source-sha"),
                             ("a" * 39, "--source-sha")):
            with self.subTest(source=value):
                with self.assertRaisesRegex(SMOKE.SmokeFailure, error):
                    SMOKE.validate_cli_config(SMOKE.Config(
                        **{**vars(config), "source_sha": value}))
        with self.assertRaisesRegex(SMOKE.SmokeFailure, "--module-sha256"):
            SMOKE.validate_cli_config(SMOKE.Config(
                **{**vars(config), "module_sha256": "bad"}))
        # Legacy pasted phrases no longer have a CLI entry point.
        self.assertNotIn("--authorization", SMOKE.build_parser().format_help())

    def test_baremetal_scope_is_separate_and_pins_exact_host_identity(self):
        mid_sha = hashlib.sha256(b"0123456789abcdef0123456789abcdef").hexdigest()
        host = SMOKE.Config(
            vm_id="", host_id="devpc-Inspiron1564Linux",
            host_machine_id_sha256=mid_sha,
            source_sha="a"*40, module_path=Path("/root/dm-swapz.ko"),
            module_sha256="b"*64, live=True)
        SMOKE.validate_cli_config(host)
        with self.assertRaisesRegex(SMOKE.SmokeFailure, "machine-id SHA-256"):
            SMOKE.validate_cli_config(SMOKE.Config(
                **{**vars(host), "host_machine_id_sha256": "bad"}))
        with self.assertRaisesRegex(SMOKE.SmokeFailure, "devpc-"):
            SMOKE.validate_cli_config(SMOKE.Config(
                **{**vars(host), "host_id": "production"}))
        with self.assertRaisesRegex(SMOKE.SmokeFailure, "no VM ID"):
            SMOKE.validate_cli_config(SMOKE.Config(
                **{**vars(host), "vm_id": "disposable-any"}))

    def test_baremetal_detection_rejects_virtualized_or_container_host(self):
        machine = "0123456789abcdef0123456789abcdef"
        digest = hashlib.sha256(machine.encode("ascii")).hexdigest()
        op = SMOKE.SystemOperations()
        def result(argv, rc=1, output=""):
            return SMOKE.CommandResult(tuple(argv), rc, output, "")
        with mock.patch.object(SMOKE.Path, "read_text", return_value=machine):
            with mock.patch.object(op, "run", side_effect=[
                    result(["systemd-detect-virt", "--vm"]),
                    result(["systemd-detect-virt", "--container"])]):
                op._verify_baremetal_identity(digest)
            with self.assertRaisesRegex(SMOKE.SmokeFailure, "machine identity"):
                op._verify_baremetal_identity("e"*64)
            for flag, observations in (
                ("--vm", [result(["systemd-detect-virt", "--vm"], 0, "kvm")]),
                ("--container", [result(["systemd-detect-virt", "--vm"]),
                                  result(["systemd-detect-virt", "--container"], 0, "docker")]),
            ):
                with self.subTest(flag=flag), mock.patch.object(
                        op, "run", side_effect=observations):
                    with self.assertRaisesRegex(SMOKE.SmokeFailure,
                                                "virtualization indicator"):
                        op._verify_baremetal_identity(digest)

    def test_real_host_smoke_uses_same_tmpfs_loop_and_two_reads(self):
        digest = hashlib.sha256(b"0123456789abcdef0123456789abcdef").hexdigest()
        config = SMOKE.Config(
            vm_id="", host_id="devpc-test", host_machine_id_sha256=digest,
            source_sha="a"*40, module_path=Path("/root/dm-swapz.ko"),
            module_sha256="b"*64, live=True)
        ops = FakeOps()
        SMOKE.SmokeRunner(config, ops).run()
        self.assertEqual(sum(x[0] == "write-4k" for x in ops.actions), 1)
        self.assertEqual(sum(x[0] == "read-4k" for x in ops.actions), 2)
        self.assertEqual(sum(x[0] == "losetup-create" for x in ops.actions), 1)
        self.assertEqual(sum(x[0] == "rmmod" for x in ops.actions), 1)
        unsafe = FakeOps(timeout_at="write")
        with self.assertRaises(SMOKE.QuarantineRequired):
            SMOKE.SmokeRunner(config, unsafe).run()
        self.assertTrue(unsafe.quarantine["owned"]["host_mode"])
        self.assertNotIn("rmmod", [x[0] for x in unsafe.actions])
        self.assertNotIn("losetup-detach", [x[0] for x in unsafe.actions])

    def test_user_owned_checkout_is_refused_for_privileged_live_execution(self):
        # CI/worktree paths are intentionally not trusted as root execution
        # locations; live use requires a separately protected full checkout.
        with self.assertRaisesRegex(SMOKE.SmokeFailure, "root-owned"):
            SMOKE.SystemOperations._require_protected_source_tree()

    def test_run_directory_collision_preserves_preexisting_empty_directory(self):
        run_id = "collision-test"
        with tempfile.TemporaryDirectory(prefix="swapz-smoke-mock-") as temporary:
            run_root = Path(temporary)
            preexisting = run_root / f"swapz-v22-smoke-{run_id}"
            preexisting.mkdir()
            with mock.patch.object(SMOKE, "RUN_DIR_ROOT", run_root):
                with self.assertRaisesRegex(SMOKE.SmokeFailure, "cannot create owned"):
                    SMOKE.SystemOperations().make_run_dir(run_id)
            self.assertTrue(preexisting.is_dir())
            self.assertEqual(list(preexisting.iterdir()), [])

    def test_success_proves_staged_hit_then_drains_and_cleans_owned_stack(self):
        ops = FakeOps()
        SMOKE.SmokeRunner(good_config(), ops).run()
        create_calls = [a for a in ops.actions if a[0] == "dm-create"]
        self.assertEqual(len(create_calls), 2)
        target_table = next(a[3] for a in create_calls if "-target-" in a[1])
        self.assertEqual(target_table.split()[1:3], ["8", "swapz"])
        self.assertEqual(target_table.split()[-2:], ["staged", "64"])
        self.assertIn("/dev/mapper/swapz-smoke-delay-", target_table)
        verified_target_table = next(
            a[2] for a in ops.actions
            if a[0] == "dm-table" and "-target-" in a[1])
        self.assertEqual(verified_target_table[3], "253:0")
        events = [a[0] for a in ops.actions]
        self.assertLess(events.index("write-4k"), events.index("read-4k"))
        self.assertEqual(events.count("read-4k"), 2)
        self.assertLess(events.index("read-4k"), events.index("suspend"))
        self.assertLess(events.index("suspend"), events.index("resume"))
        read_indices = [index for index, event in enumerate(events) if event == "read-4k"]
        self.assertLess(events.index("resume"), read_indices[1])
        self.assertLess(events.index("dm-remove"), events.index("losetup-detach"))
        self.assertLess(events.index("losetup-detach"), events.index("rmmod"))
        self.assertNotIn("quarantine", events)
        self.assertFalse(ops.loaded)
        self.assertFalse(ops.created)

    def test_confirmed_partial_delay_creation_failure_cleans_only_owned_resources(self):
        ops = FakeOps(fail_at="delay")
        with self.assertRaisesRegex(SMOKE.SetupFailure, "delay create failure"):
            SMOKE.SmokeRunner(good_config(), ops).run()
        events = [a[0] for a in ops.actions]
        self.assertIn("losetup-detach", events)
        self.assertIn("rmmod", events)
        self.assertIn("remove-run-dir", events)
        self.assertNotIn("quarantine", events)
        self.assertFalse(ops.created)

    def test_confirmed_partial_target_creation_failure_removes_owned_delay_first(self):
        ops = FakeOps(fail_at="target")
        with self.assertRaisesRegex(SMOKE.SetupFailure, "target create failure"):
            SMOKE.SmokeRunner(good_config(), ops).run()
        removed = [a[1] for a in ops.actions if a[0] == "dm-remove"]
        self.assertEqual(len(removed), 1)
        self.assertIn("-delay-", removed[0])
        self.assertIn("losetup-detach", [a[0] for a in ops.actions])
        self.assertNotIn("quarantine", [a[0] for a in ops.actions])

    def test_write_timeout_marks_quarantine_and_preserves_all_kernel_resources(self):
        ops = FakeOps(timeout_at="write")
        with self.assertRaises(SMOKE.CommandTimeout):
            SMOKE.SmokeRunner(good_config(), ops).run()
        events = [a[0] for a in ops.actions]
        self.assertIn("quarantine", events)
        self.assertNotIn("dm-remove", events)
        self.assertNotIn("losetup-detach", events)
        self.assertNotIn("rmmod", events)
        self.assertTrue(ops.quarantine["owned"]["target_owned"])

    def test_callback_uncertainty_marks_quarantine_without_teardown(self):
        ops = FakeOps(uncertainty_at="status")
        with self.assertRaises(SMOKE.QuarantineRequired):
            SMOKE.SmokeRunner(good_config(), ops).run()
        events = [a[0] for a in ops.actions]
        self.assertIn("quarantine", events)
        self.assertNotIn("dm-remove", events)
        self.assertNotIn("losetup-detach", events)
        self.assertNotIn("rmmod", events)

    def test_warning_or_bad_data_preserves_the_live_stack(self):
        ops = FakeOps(bad_pre_read=True)
        with self.assertRaisesRegex(SMOKE.QuarantineRequired, "pre-drain staged read"):
            SMOKE.SmokeRunner(good_config(), ops).run()
        events = [a[0] for a in ops.actions]
        self.assertIn("quarantine", events)
        self.assertNotIn("dm-remove", events)
        self.assertNotIn("rmmod", events)

        ops = FakeOps(uncertainty_at="kernel-warning")
        with self.assertRaisesRegex(SMOKE.QuarantineRequired, "unexpected kernel warning"):
            SMOKE.SmokeRunner(good_config(), ops).run()
        self.assertIn("quarantine", [a[0] for a in ops.actions])
        self.assertNotIn("dm-remove", [a[0] for a in ops.actions])

    def test_failed_owned_target_removal_stops_before_lower_teardown(self):
        ops = FakeOps(fail_at="remove-target")
        with self.assertRaisesRegex(SMOKE.QuarantineRequired, "remove failure"):
            SMOKE.SmokeRunner(good_config(), ops).run()
        events = [a[0] for a in ops.actions]
        self.assertIn("quarantine", events)
        target_remove_index = next(i for i, a in enumerate(ops.actions)
                                   if a[:1] == ("dm-remove",))
        self.assertNotIn("losetup-detach", events[target_remove_index + 1:])
        self.assertNotIn("rmmod", events[target_remove_index + 1:])

    def test_suspend_timeout_preserves_the_owned_stack(self):
        ops = FakeOps(timeout_at="suspend")
        with self.assertRaises(SMOKE.CommandTimeout):
            SMOKE.SmokeRunner(good_config(), ops).run()
        events = [a[0] for a in ops.actions]
        self.assertIn("quarantine", events)
        self.assertNotIn("dm-remove", events)
        self.assertNotIn("losetup-detach", events)
        self.assertNotIn("rmmod", events)

        ops = FakeOps(uncertainty_at="suspended-query")
        with self.assertRaisesRegex(
                SMOKE.QuarantineRequired, "suspended-state query uncertainty"):
            SMOKE.SmokeRunner(good_config(), ops).run()
        events = [a[0] for a in ops.actions]
        self.assertLess(events.index("suspend"), events.index("suspended-query"))
        self.assertIn("quarantine", events)
        self.assertNotIn("dm-remove", events)
        self.assertNotIn("losetup-detach", events)
        self.assertNotIn("rmmod", events)

    def test_unexpected_target_open_reference_prevents_teardown(self):
        ops = FakeOps()
        ops.open_target = True
        with self.assertRaisesRegex(SMOKE.QuarantineRequired, "open reference"):
            SMOKE.SmokeRunner(good_config(), ops).run()
        events = [a[0] for a in ops.actions]
        self.assertIn("quarantine", events)
        self.assertNotIn("dm-remove", events)
        self.assertNotIn("losetup-detach", events)
        self.assertNotIn("rmmod", events)

    def test_status_parser_accepts_real_mixed_type_kernel_dm_status(self):
        inflight = SMOKE.parse_status(REAL_KERNEL_STATUS)
        self.assertEqual(inflight["inflight_id"], 0)
        self.assertEqual(inflight["inflight_blocks"], 1)
        self.assertEqual(inflight["async_cb"], 1)
        self.assertEqual(inflight["batch_kib"], 64)
        self.assertNotIn("strategy", inflight)
        self.assertNotIn("lower_discard", inflight)

        drained_text = production_status(
            inflight_id=-1, inflight_blocks=0, async_cb=0,
            buf0_blocks=0, staged_hits=1, physical_write=4096)
        drained = SMOKE.parse_status(drained_text)
        self.assertEqual(drained["inflight_id"], -1)
        self.assertEqual(drained["inflight_blocks"], 0)
        self.assertEqual(drained["staged_hits"], 1)

        # Exercise actual host command parsing, mocking only subprocess.
        operations = SMOKE.SystemOperations()
        cmd = ["dmsetup", "status", "owned-target"]
        with mock.patch.object(operations, "_checked", return_value=drained_text) as checked:
            self.assertEqual(operations.dm_status("owned-target")["inflight_id"], -1)
            checked.assert_called_once_with(cmd, SMOKE.STATUS_TIMEOUT_MS)

    def test_status_parser_rejects_bad_real_kernel_fields(self):
        failures = (
            ("strategy=staged", "strategy=opportunistic", "wrong smoke strategy"),
            ("batch_kib=64", "batch_kib=4", "wrong smoke batch"),
            ("lower_discard=on", "lower_discard=unknown", "lower_discard"),
            ("inflight_id=0", "inflight_id=-2", "inflight_id"),
            ("inflight_id=0", "inflight_id=unknown", "inflight_id"),
            ("segment=0/32", "segment=1/1", "segment index"),
            ("segment=0/32", "segment=1/0", "segment index"),
            ("segment=0/32", "segment=-1/32", "segment index"),
            ("segment=0/32", "segment=garbage", "segment index"),
            ("async_cb=1", "async_cb=bogus", "non-numeric"),
            ("failed=0", "failed=2", "invalid failed"),
            ("staged_hits=0", "staged_hits=-1", "non-numeric"),
            ("staged_hits=0", "staged_hits=0 staged_hits=0", "duplicate"),
        )
        for original, altered, error in failures:
            with self.subTest(replacement=altered):
                with self.assertRaisesRegex(SMOKE.QuarantineRequired, error):
                    SMOKE.parse_status(REAL_KERNEL_STATUS.replace(original, altered, 1))
        with self.assertRaisesRegex(SMOKE.QuarantineRequired, "lacks required"):
            SMOKE.parse_status(REAL_KERNEL_STATUS.replace("async_cb=1", ""))
        with self.assertRaisesRegex(SMOKE.QuarantineRequired, "malformed"):
            SMOKE.parse_status(REAL_KERNEL_STATUS + " =bad")

    def test_full_lifecycle_parses_production_status_via_system_operations(self):
        class ProductionTextOps(FakeOps):
            def __init__(self):
                super().__init__()
                self.raw_operations = SMOKE.SystemOperations()
                self.taint_delivered = False

            def new_kernel_messages(self):
                if self.loaded and not self.taint_delivered:
                    self.taint_delivered = True
                    return [SMOKE.EXPECTED_MODULE_LOAD_TAINT]
                return []

            def dm_status(self, name):
                current = super().dm_status(name)
                raw = production_status(
                    inflight_id=(0 if current["inflight_blocks"] else -1),
                    **current)
                with mock.patch.object(
                        self.raw_operations, "_checked", return_value=raw):
                    return self.raw_operations.dm_status(name)

        ops = ProductionTextOps()
        SMOKE.SmokeRunner(good_config(), ops).run()
        events = [x[0] for x in ops.actions]
        self.assertEqual(events.count("read-4k"), 2)
        self.assertLess(events.index("suspend"), events.index("resume"))
        self.assertNotIn("quarantine", events)
        self.assertFalse(ops.loaded)

    def test_expected_taint_only_allowed_immediately_after_owned_module_load(self):
        taint = SMOKE.EXPECTED_MODULE_LOAD_TAINT

        class TaintOps(FakeOps):
            def __init__(self, messages):
                super().__init__()
                self.messages = messages
                self.delivered = False

            def new_kernel_messages(self):
                if not self.delivered and self.loaded:
                    self.delivered = True
                    return list(self.messages)
                return []

        good = TaintOps([taint])
        SMOKE.SmokeRunner(good_config(), good).run()
        self.assertFalse(good.loaded)

        warning = "dm-swapz: WARNING: lower I/O callback ownership invalid"
        mixed = TaintOps([taint, warning])
        with self.assertRaisesRegex(SMOKE.QuarantineRequired, "unexpected kernel warning"):
            SMOKE.SmokeRunner(good_config(), mixed).run()
        self.assertIn(warning, mixed.quarantine["messages"])
        self.assertNotIn("dm-remove", [event[0] for event in mixed.actions])

        near_match = TaintOps([taint + " unexpected"])
        with self.assertRaisesRegex(SMOKE.QuarantineRequired, "unexpected kernel warning"):
            SMOKE.SmokeRunner(good_config(), near_match).run()
        # Delayed same text is not ignored after the privileged load phase.
        later = SMOKE.SmokeRunner(good_config(), TaintOps([]))
        later.owned.module_owned = True
        with mock.patch.object(later.ops, "new_kernel_messages", return_value=[taint]):
            with self.assertRaisesRegex(SMOKE.QuarantineRequired, "unexpected kernel warning"):
                later._check_messages("pre-drain staged read")

    def test_dm_attr_parser_accepts_only_documented_layout(self):
        operations = SMOKE.SystemOperations()
        command = ["dmsetup", "info", "--columns", "--noheadings", "-o",
                   "attr", "owned-target"]
        for attr, suspended in (("L--w", False), ("L-sw", True)):
            with mock.patch.object(operations, "_checked", return_value=attr) as checked:
                self.assertIs(operations.dm_is_suspended("owned-target"), suspended)
                checked.assert_called_once_with(command, 2000)
        for malformed in ("", "L--", "L--w extra", "L-Iw", "L-sr", "----"):
            with mock.patch.object(operations, "_checked", return_value=malformed):
                with self.subTest(attr=malformed), self.assertRaises(
                        SMOKE.QuarantineRequired):
                    operations.dm_is_suspended("owned-target")
        with mock.patch.object(
                operations, "_checked", side_effect=SMOKE.SmokeFailure("query failed")):
            with self.assertRaisesRegex(SMOKE.QuarantineRequired, "cannot establish"):
                operations.dm_is_suspended("owned-target")

    def test_raw_rejected_dm_status_preserved_in_quarantine_forensics(self):
        from contextlib import redirect_stderr, redirect_stdout
        import io
        import json
        op = SMOKE.SystemOperations()
        malformed = REAL_KERNEL_STATUS.replace(
            "strategy=staged", "strategy=broken", 1)
        valid = production_status(inflight_id=-1, inflight_blocks=0,
                                  async_cb=0, buf0_blocks=0)
        with mock.patch.object(op, "_checked", side_effect=[malformed, valid]):
            with self.assertRaisesRegex(SMOKE.QuarantineRequired, "wrong smoke strategy"):
                op.dm_status("swapz-owned-test")
            self.assertEqual(op.dm_status("swapz-owned-test")["inflight_id"], -1)
        with tempfile.TemporaryDirectory(prefix="swapz-status-raw-rootless-") as tmp:
            owned = SMOKE.Owned(
                host_mode=True, run_dir=Path(tmp), target_name="swapz-owned-test",
                quarantined=True)
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                op.quarantine_record(owned, "status parser failure", None, [])
            body = json.loads((Path(tmp) / "QUARANTINED.json").read_text())
            self.assertEqual(body["first_rejected_dm_status_raw"], malformed)
            self.assertEqual(body["last_raw_dm_status"], valid)
            self.assertIsNone(body["last_status"])
            self.assertFalse(body["raw_dm_status_truncated"])
            self.assertEqual(body["status"], "QUARANTINED_HOST_DO_NOT_FORCE_CLEANUP")

    def test_raw_status_capture_is_bounded_even_with_untrusted_long_text(self):
        op = SMOKE.SystemOperations()
        broken = REAL_KERNEL_STATUS + (" unexpected=1" * 10000)
        with mock.patch.object(op, "_checked", return_value=broken):
            with self.assertRaises(SMOKE.QuarantineRequired):
                op.dm_status("swapz-owned-test")
        self.assertEqual(len(op._first_rejected_dm_status_raw),
                         SMOKE.MAX_RAW_STATUS_CHARS)
        self.assertTrue(op._raw_status_truncated)

    def test_unsigned_module_notice_is_not_kernel_warning_at_notice_priority(self):
        unsigned = ("dm_swapz: module verification failed: signature "
                    "and/or required key missing - tainting kernel")
        # Upstream prints via pr_notice_once (severity 5). Preserve the
        # record's priority classification instead of globally exempting
        # module-signature text from true kernel warning severity 0..4.
        for priority, expected in ((5, False), (4, True), (3, True)):
            with self.subTest(priority=priority):
                flag, text = SMOKE.SystemOperations._kernel_record_is_warning(
                    f"{priority},31,1000,-;" + unsigned)
                self.assertEqual(flag, expected)
                self.assertEqual(text, unsigned)
        # A true DM error must still fail even when adjacent to a notice.
        err, _ = SMOKE.SystemOperations._kernel_record_is_warning(
            "3,32,1001,-;device-mapper: swapz: backing I/O failed (-5)")
        self.assertTrue(err)

    def test_staged_hit_and_logical_read_are_kernel_completions_not_byte_proof(self):
        # A resumed/recovered mapping may have been probed by udev or other
        # readers, so cumulative counters must not be equated with the two
        # controlled payload readback files. Prove the staged hit must
        # INCREASE after the test's own byte-equal first read.
        class AlreadyReadOps(FakeOps):
            def dm_status(self, name):
                current = super().dm_status(name)
                # Simulates a pre-existing staged hit from a reader that
                # raced target creation; no controlled-read increment.
                current["staged_hits"] = 1
                return current
        ops = AlreadyReadOps()
        with self.assertRaisesRegex(
                SMOKE.QuarantineRequired, "staged_hits= did not increase"):
            SMOKE.SmokeRunner(good_config(), ops).run()
        self.assertTrue(ops.quarantine["owned"]["quarantined"])
        self.assertNotIn("dm-remove", [event[0] for event in ops.actions])

    def test_kernel_log_gate_uses_printk_priority_for_device_mapper_errors(self):
        warning, message = SMOKE.SystemOperations._kernel_record_is_warning(
            "4,101,2000,-;device-mapper: swapz: ownership warning")
        self.assertTrue(warning)
        self.assertIn("device-mapper: swapz", message)
        error, _ = SMOKE.SystemOperations._kernel_record_is_warning(
            "3,102,2001,-;device-mapper: swapz: backing I/O failed (-5)")
        self.assertTrue(error)
        info, _ = SMOKE.SystemOperations._kernel_record_is_warning(
            "6,103,2002,-;device-mapper: swapz: target registered")
        self.assertFalse(info)
        with self.assertRaisesRegex(SMOKE.QuarantineRequired, "unrecognized /dev/kmsg"):
            SMOKE.SystemOperations._kernel_record_is_warning("unstructured message")

    def test_live_script_contains_no_force_or_host_device_operation(self):
        source = SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source)
        wrapper = (ROOT / "tests/runtime/virtual-smoke.sh").read_text(encoding="utf-8")
        self.assertIn("swapz /dev/mapper/{self.delay_name} staged 64", source)
        self.assertIn('latest["inflight_blocks"] > 0 and latest["async_cb"] > 0', source)
        self.assertIn('after["staged_hits"] > hits_before', source)
        self.assertIn('"dmsetup", "suspend", name', source)
        self.assertIn('"dmsetup", "resume", name', source)
        command_names = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "run" and node.args
                    and isinstance(node.args[0], ast.List)):
                argv = node.args[0].elts
                values = [item.value if isinstance(item, ast.Constant) else None
                          for item in argv]
                if values and isinstance(values[0], str):
                    command_names.add(values[0])
                if values[:2] == ["dmsetup", "remove"]:
                    self.assertEqual(len(values), 3, "dmsetup remove must stay ordinary and named")
                if values and values[0] == "rmmod":
                    self.assertEqual(values, ["rmmod", "dm_swapz"],
                                     "only ordinary unload of the owned module is allowed")
        self.assertTrue(command_names.isdisjoint({"swapon", "swapoff", "mount", "reboot", "sysrq"}))
        self.assertIn("exec python3 -B", wrapper)
        kernel_source = (ROOT / "kernel/dm-swapz.c").read_text(encoding="utf-8")
        self.assertIn('DMEMIT("%s %s %u", context->backing->name', kernel_source)
        self.assertIn("expected_target[3] = self.delay_devno", source)
        match = re.search(r"^#define\s+SWAPZ_ASYNC_WATCHDOG_MS\s+(\d+)U\s*$",
                          kernel_source, re.MULTILINE)
        self.assertIsNotNone(match)
        watchdog = int(match.group(1))
        self.assertLess(SMOKE.WRITE_DELAY_MS + 1000, watchdog)
        self.assertGreater(SMOKE.SUSPEND_TIMEOUT_MS, SMOKE.WRITE_DELAY_MS)
        self.assertNotIn("bounded_window", source)

    def test_operator_handoff_names_privileged_prerequisites_and_capacity(self):
        handoff = (ROOT / "docs/virtual-smoke.md").read_text(encoding="utf-8")
        self.assertIn("modprobe dm-delay", handoff)
        self.assertIn("No approval phrase", handoff)
        self.assertIn("65,536 sectors", handoff)
        self.assertIn("32 complete 1 MiB segments", handoff)
        self.assertIn("the larger of 25% of the one-page logical size or two segments", handoff)
        self.assertRegex(
            handoff,
            r"Only the swapz\s+logical table is one page \(`0 8` sectors\)\.",
        )
        self.assertRegex(handoff, r"cannot\s+authenticate the operator-supplied VM label")
        self.assertIn("forensic cleanup or VM reset needs a new", handoff)
        self.assertIn("two separate aligned 4 KiB reads", handoff)
        self.assertIn("while the lower write is outstanding", handoff)
        self.assertIn("after ordinary suspend/resume drain", handoff)
        self.assertNotIn('--authorization "$AUTH"', handoff)
        self.assertNotIn('AUTH="I AUTHORIZE', handoff)


if __name__ == "__main__":
    unittest.main(verbosity=2)
