#!/usr/bin/env python3
"""Adversarial rootless tests for the fixture-owner and evidence producer.

All mapper/swap/loop observations are in-memory fakes. The only real files are
private temporary regular files used to exercise descriptor and flock lifetime
in the existing MapperLifecycleOwner. No device node or privileged operation
is opened or invoked.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import importlib.util
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "recall_fixture_owner_tested", HERE / "recall-fixture-owner.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load fixture owner")
owner_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = owner_module
SPEC.loader.exec_module(owner_module)

allow = owner_module._ALLOWLIST
MapperIdentity = allow.MapperIdentity
MapperInventory = allow.MapperInventory
MapperLifecycleLease = allow.MapperLifecycleLease
MapperLifecycleOwner = allow.MapperLifecycleOwner
MapperOpenersObservation = allow.MapperOpenersObservation
MapperSuspendObservation = allow.MapperSuspendObservation
MapperRemovalObservation = allow.MapperRemovalObservation
WorkerCompletionEvidence = allow.WorkerCompletionEvidence
worker_completion_payload = allow.worker_completion_payload
FixtureOwnerBroker = owner_module.FixtureOwnerBroker
FixtureOwnerDenied = owner_module.FixtureOwnerDenied
SwapInventoryObservation = owner_module.SwapInventoryObservation
SwapoffObservation = owner_module.SwapoffObservation
LowerDependencyObservation = owner_module.LowerDependencyObservation
LoopDetachObservation = owner_module.LoopDetachObservation
LoopInventoryObservation = owner_module.LoopInventoryObservation


class FakeMapperFileOps(allow.RecallDDFileOps):
    def __init__(self, mapper_fd: int, identity: MapperIdentity):
        self.mapper_fds = {mapper_fd}
        self.identity = identity
        self.closed_mapper_fds: list[int] = []

    def fstat(self, fd):
        if fd in self.mapper_fds:
            return SimpleNamespace(
                st_mode=stat.S_IFBLK | 0o600, st_rdev=os.makedev(self.identity.major, self.identity.minor),
                st_uid=os.geteuid(), st_dev=1, st_ino=self.identity.minor,
                st_size=0, st_mtime_ns=0, st_ctime_ns=0, st_nlink=1,
            )
        return super().fstat(fd)

    def read_dm_sysfs_attr(self, major, minor, attribute):
        values = {"name": self.identity.name, "uuid": self.identity.uuid,
                  "dev": f"{major}:{minor}"}
        if (major, minor) != (self.identity.major, self.identity.minor):
            raise OSError("unexpected synthetic DM device number")
        return values[attribute]

    def close(self, fd):
        if fd in self.mapper_fds:
            self.mapper_fds.remove(fd)
            self.closed_mapper_fds.append(fd)
        return super().close(fd)


class FakeMapperOperations:
    def __init__(self, identity: MapperIdentity, mapper_fd: int, worker_key: bytes):
        self.identity = identity
        self.mapper_fd = mapper_fd
        self.worker_key = worker_key
        self.entries: tuple[MapperIdentity, ...] = ()
        self.alive = True
        self.trace: list[str] = []
        self.fail: set[str] = set()
        self.suspend_result = MapperSuspendObservation(
            True, True, False, False, True, True, True,
        )
        self.openers_result = MapperOpenersObservation(True, True, 0, ())

    def owner_alive(self):
        self.trace.append("owner_alive")
        if "owner_alive" in self.fail:
            raise OSError("injected owner inspection error")
        return self.alive

    def inventory(self):
        self.trace.append("dm_inventory")
        if "dm_inventory" in self.fail:
            return MapperInventory(False, self.entries)
        return MapperInventory(True, self.entries)

    def create_mapping(self, identity):
        self.trace.append("dm_create")
        if identity != self.identity or self.entries:
            raise AssertionError("unexpected or duplicate synthetic mapper creation")
        self.entries = (identity,)
        return self.mapper_fd

    def verify_worker_completion(self, evidence):
        self.trace.append("worker_attestation")
        expected = hmac.new(
            self.worker_key, worker_completion_payload(evidence), hashlib.sha256,
        ).digest()
        return hmac.compare_digest(evidence.authenticator, expected)

    def suspend_mapping(self, identity, *, noflush):
        self.trace.append("dm_suspend")
        if identity != self.identity or noflush is not False:
            raise AssertionError("only ordinary suspend of the exact synthetic mapper is allowed")
        if "dm_suspend" in self.fail:
            return MapperSuspendObservation(False, True, False, False, True, False, False)
        return self.suspend_result

    def inspect_openers(self, identity):
        self.trace.append("dm_openers")
        if identity != self.identity:
            raise AssertionError("unexpected synthetic mapper open-count query")
        if "dm_openers" in self.fail:
            raise OSError("injected holder inventory failure")
        return self.openers_result

    def remove_mapping(self, identity):
        self.trace.append("dm_remove_normal")
        if identity != self.identity:
            raise AssertionError("unexpected synthetic mapper removal")
        if "dm_remove" in self.fail:
            return MapperRemovalObservation(False, True, False, False, True)
        self.entries = ()
        return MapperRemovalObservation(True, True, False, False, True)


class FakeDrainOperations:
    """Synthetic typed results that model operations, never kernel state."""

    def __init__(self, identity: MapperIdentity, worker_key: bytes, loop: str):
        self.identity = identity
        self.worker_key = worker_key
        self.loop = loop
        self.owner = None
        self.swap_active = True
        self.loop_present = True
        self.fail: set[str] = set()
        self.trace: list[str] = []

    def bind_owner(self, owner):
        self.owner = owner

    def collect_worker_completion(self, handles):
        self.trace.append("worker_report")
        if "worker_report" in self.fail:
            return object()
        session = self.owner.lease.session_id
        reaped = handles[:-1] if "worker_incomplete" in self.fail else handles
        provisional = WorkerCompletionEvidence(
            session, handles, reaped, handles, 0, (), bytes(32),
        )
        authenticator = hmac.new(
            self.worker_key, worker_completion_payload(provisional), hashlib.sha256,
        ).digest()
        if "worker_bad_mac" in self.fail:
            authenticator = b"x" * 32
        return WorkerCompletionEvidence(
            session, handles, reaped, handles, 0, (), authenticator,
        )

    def inspect_swap(self, identity):
        self.trace.append("swap_inventory")
        if "swap_inventory" in self.fail:
            raise OSError("injected swap inventory failure")
        if identity != self.identity:
            return SwapInventoryObservation(True, self.swap_active, None, "c" * 64)
        return SwapInventoryObservation(
            True, self.swap_active, identity if self.swap_active else None,
            ("c" if self.swap_active else "d") * 64,
        )

    def swapoff(self, identity):
        self.trace.append("swapoff_exact_mapper")
        if "swapoff" in self.fail:
            return SwapoffObservation(True, False, identity == self.identity)
        if identity != self.identity:
            return SwapoffObservation(True, False, False)
        self.swap_active = False
        return SwapoffObservation(True, True, True)

    def inspect_lower_dependencies(self, identity, loop_device):
        self.trace.append("lower_dependencies")
        if "lower_inventory" in self.fail:
            return object()
        if identity != self.identity or loop_device != self.loop:
            return LowerDependencyObservation(False, False, (), False, (), "0" * 64)
        entries = self.owner.operations.entries
        return LowerDependencyObservation(
            True, not entries, (), True, (identity.name,) if not entries else (), "e" * 64,
        )

    def detach_loop(self, loop_device):
        self.trace.append("loop_detach_normal")
        if loop_device != self.loop or "loop_detach" in self.fail:
            return LoopDetachObservation(False, True, loop_device == self.loop)
        self.loop_present = False
        return LoopDetachObservation(True, True, True)

    def inspect_loop(self, loop_device):
        self.trace.append("loop_inventory")
        if "loop_inventory" in self.fail:
            raise OSError("injected loop inventory failure")
        return LoopInventoryObservation(
            loop_device == self.loop, self.loop_present, "f" * 64,
        )


class FixtureOwnerBrokerTests(unittest.TestCase):
    IDENTITY = MapperIdentity("swapz-v22-recall-owner-test", "SWAPZ-OWNER-TEST", 253, 91, "a" * 64)
    LOOP = "/dev/loop91"
    WORKER_KEY = b"fixture worker attestation key used only by this rootless test"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swapz-fixture-owner-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        mapper_path = self.root / "synthetic-mapper-descriptor"
        mapper_path.write_bytes(b"temporary regular file; no device is opened")
        mapper_path.chmod(0o600)
        self.mapper_fd = os.open(mapper_path, os.O_RDONLY | os.O_CLOEXEC)
        self.addCleanup(lambda: os.close(self.mapper_fd) if self._fd_open(self.mapper_fd) else None)
        self.file_ops = FakeMapperFileOps(self.mapper_fd, self.IDENTITY)

        self.lock_path = self.root / "fixture-owner.lock"
        self.lock_path.touch(mode=0o600)
        self.lock_path.chmod(0o600)
        self.lock_fd = os.open(self.lock_path, os.O_RDWR | os.O_CLOEXEC)
        fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(lambda: os.close(self.lock_fd) if self._fd_open(self.lock_fd) else None)
        lease = MapperLifecycleLease(
            self.lock_fd, self.lock_path, self.IDENTITY,
            lambda _fd, _name, _ops: self.IDENTITY, ops=self.file_ops,
        )
        self.lease = lease
        self.addCleanup(self.lease.close)
        self.mapper_ops = FakeMapperOperations(self.IDENTITY, self.mapper_fd, self.WORKER_KEY)
        self.owner = MapperLifecycleOwner(
            self.IDENTITY, lease, self.mapper_ops, file_ops=self.file_ops,
        )
        self.drain_ops = FakeDrainOperations(self.IDENTITY, self.WORKER_KEY, self.LOOP)
        self.drain_ops.bind_owner(self.owner)
        self.worker_peer = object()
        self.stop_calls: list[tuple[str, ...]] = []
        self.handles: list[str] = []

        def authenticate(peer):
            return "worker" if peer is self.worker_peer else None

        def launch(role):
            handle = f"owned-{role}-{len(self.handles) + 1}"
            self.handles.append(handle)
            return handle

        self.broker = FixtureOwnerBroker(
            self.owner, self.drain_ops, self.LOOP,
            peer_authenticator=authenticate, worker_launcher=launch,
            worker_stopper=lambda handles: self.stop_calls.append(tuple(handles)),
        )

    @staticmethod
    def _fd_open(fd: int) -> bool:
        try:
            os.fstat(fd)
            return True
        except OSError:
            return False

    def _request(self, request_id: str, role: str) -> dict[str, object]:
        return self.broker.worker_request(self.worker_peer, {
            "request_id": request_id, "operation": "launch_role", "role": role,
        })

    def _new_case(self):
        case = FixtureOwnerBrokerTests("runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def _start_workers(self, roles=("writer", "a", "b")):
        self.broker.owner_create()
        for index, role in enumerate(roles):
            result = self._request(f"req-{index}", role)
            self.assertEqual(result["status"], "launched")
        return tuple(self.handles)

    def test_end_to_end_owner_broker_and_producer_sequence(self):
        handles = self._start_workers()
        self.assertTrue(self.broker.finalize())
        self.assertEqual(self.broker.state, self.broker.RELEASED)
        self.assertTrue(self.broker.mapping_released)
        self.assertTrue(self.broker.backing_release_authorized)
        self.assertFalse(self.broker.backing_must_be_preserved)
        self.assertEqual(self.owner.registered_worker_handles, handles)
        self.assertEqual(self.broker.evidence_events, (
            "admission_closed", "workers_reaped", "swap_quiescent",
            "dm_suspended:swapz-v22-recall-owner-test",
            "dm_descriptors_closed:swapz-v22-recall-owner-test",
            "dm_open_count_zero:swapz-v22-recall-owner-test",
            "dm_removed:swapz-v22-recall-owner-test", "dm_absent:swapz-v22-recall-owner-test",
            "loop_dependencies_clear", "loop_detached",
        ))
        self.assertLess(self.mapper_ops.trace.index("worker_attestation"),
                        self.mapper_ops.trace.index("dm_suspend"))
        self.assertLess(self.mapper_ops.trace.index("dm_suspend"),
                        self.mapper_ops.trace.index("dm_openers"))
        self.assertLess(self.mapper_ops.trace.index("dm_openers"),
                        self.mapper_ops.trace.index("dm_remove_normal"))
        self.assertLess(self.drain_ops.trace.index("swap_inventory"),
                        self.drain_ops.trace.index("swapoff_exact_mapper"))
        self.assertLess(self.drain_ops.trace.index("lower_dependencies"),
                        self.drain_ops.trace.index("loop_detach_normal"))
        self.assertLess(self.drain_ops.trace.index("loop_detach_normal"),
                        self.drain_ops.trace.index("loop_inventory"))
        self.assertTrue(self.owner.backing_must_be_preserved,
                        "mapper-only owner must not itself authorize backing release")

    def test_worker_ipc_cannot_supply_authority_identity_key_or_raw_commands(self):
        self.broker.owner_create()
        request = {"request_id": "r1", "operation": "launch_role", "role": "writer",
                   "key": b"attacker", "mapper": "/dev/dm-0", "argv": ["dd"]}
        with self.assertRaises(FixtureOwnerDenied):
            self.broker.worker_request(self.worker_peer, request)
        self.assertEqual(self.handles, [])
        self.assertEqual(self.mapper_ops.trace.count("dm_create"), 1,
                         "only trusted owner bootstrap may create the mapping")
        self.assertNotIn("dm_remove_normal", self.mapper_ops.trace)
        self.assertFalse(self.broker.backing_release_authorized)

    def test_worker_operations_cannot_mutate_mapper_or_mint_receipts(self):
        for operation in ("create", "reload", "rename", "suspend", "remove", "mint_receipt"):
            with self.subTest(operation=operation):
                case = self._new_case()
                case._start_workers(("writer",))
                with self.assertRaises(FixtureOwnerDenied):
                    case.broker.worker_request(case.worker_peer, {
                        "request_id": "bad-op", "operation": operation,
                        "role": "writer",
                    })
                self.assertFalse(case.broker.backing_release_authorized)
                self.assertNotIn("dm_remove_normal", case.mapper_ops.trace)
                with self.assertRaises(FixtureOwnerDenied):
                    case.broker.finalize()
                self.assertNotIn("dm_remove_normal", case.mapper_ops.trace)

    def test_reader_first_repeated_role_and_request_replay_latch_denial(self):
        self.broker.owner_create()
        with self.assertRaises(FixtureOwnerDenied):
            self._request("reader-first", "a")
        self.assertEqual(self.handles, [])

        case = self._new_case()
        case._start_workers(("writer",))
        with self.assertRaises(FixtureOwnerDenied):
            case._request("second-writer", "writer")
        self.assertEqual(len(case.handles), 1)

        case = self._new_case()
        case._start_workers(("writer",))
        with self.assertRaises(FixtureOwnerDenied):
            case._request("req-0", "a")
        self.assertFalse(case.broker.backing_release_authorized)

    def test_credential_ambiguity_owner_loss_and_control_eof_preserve(self):
        self.broker.owner_create()
        with self.assertRaises(FixtureOwnerDenied):
            self.broker.worker_request(object(), {
                "request_id": "bad-peer", "operation": "launch_role", "role": "writer",
            })
        self.assertFalse(self.broker.backing_release_authorized)

        case = self._new_case()
        case._start_workers(("writer",))
        with self.assertRaises(FixtureOwnerDenied):
            case.broker.owner_control_eof()
        self.assertFalse(case.broker.backing_release_authorized)
        self.assertEqual(case.broker.state, case.broker.DENIED)
        self.assertEqual(case.stop_calls, [tuple(case.handles)])

        case = self._new_case()
        case._start_workers(("writer",))
        with self.assertRaises(FixtureOwnerDenied):
            case.broker.producer_died()
        self.assertTrue(case.broker.backing_must_be_preserved)

    def test_worker_channel_eof_blocks_release(self):
        self._start_workers(("writer",))
        with self.assertRaises(FixtureOwnerDenied):
            self.broker.worker_control_eof(self.worker_peer)
        self.assertFalse(self.broker.backing_release_authorized)
        self.assertNotIn("dm_remove_normal", self.mapper_ops.trace)

    def test_incomplete_worker_inventory_or_bad_worker_mac_blocks_swapoff(self):
        for failure in ("worker_report", "worker_incomplete", "worker_bad_mac"):
            with self.subTest(failure=failure):
                case = self._new_case()
                case._start_workers(("writer",))
                case.drain_ops.fail.add(failure)
                with self.assertRaises(FixtureOwnerDenied):
                    case.broker.finalize()
                self.assertNotIn("swapoff_exact_mapper", case.drain_ops.trace)
                self.assertNotIn("dm_suspend", case.mapper_ops.trace)
                self.assertFalse(case.broker.backing_release_authorized)

    def test_swap_inventory_and_swapoff_failures_preserve_mapper(self):
        for failure in ("swap_inventory", "swapoff"):
            with self.subTest(failure=failure):
                case = self._new_case()
                case._start_workers(("writer",))
                case.drain_ops.fail.add(failure)
                with self.assertRaises(FixtureOwnerDenied):
                    case.broker.finalize()
                self.assertNotIn("dm_suspend", case.mapper_ops.trace)
                self.assertNotIn("dm_remove_normal", case.mapper_ops.trace)
                self.assertTrue(case.broker.backing_must_be_preserved)

    def test_false_drain_ack_skipped_holder_inventory_and_remove_failure_deny(self):
        failures = ("drain", "holders", "remove")
        for failure in failures:
            with self.subTest(failure=failure):
                case = self._new_case()
                case._start_workers(("writer",))
                if failure == "drain":
                    case.mapper_ops.suspend_result = MapperSuspendObservation(
                        True, True, False, False, True, True, False,
                    )
                elif failure == "holders":
                    case.mapper_ops.fail.add("dm_openers")
                else:
                    case.mapper_ops.fail.add("dm_remove")
                with self.assertRaises(FixtureOwnerDenied):
                    case.broker.finalize()
                self.assertFalse(case.broker.backing_release_authorized)
                if failure != "remove":
                    self.assertNotIn("dm_remove_normal", case.mapper_ops.trace)

    def test_missing_lower_inventory_or_failed_detach_denies_after_mapper_release(self):
        for failure in ("lower_inventory", "loop_detach", "loop_inventory"):
            with self.subTest(failure=failure):
                case = self._new_case()
                case._start_workers(("writer",))
                case.drain_ops.fail.add(failure)
                with self.assertRaises(FixtureOwnerDenied):
                    case.broker.finalize()
                self.assertTrue(case.broker.mapping_released)
                self.assertFalse(case.broker.backing_release_authorized)
                self.assertTrue(case.broker.backing_must_be_preserved)

    def test_changed_inventory_or_owner_loss_denies_before_removal(self):
        self._start_workers(("writer",))
        self.mapper_ops.alive = False
        with self.assertRaises(FixtureOwnerDenied):
            self.broker.finalize()
        self.assertNotIn("dm_remove_normal", self.mapper_ops.trace)
        self.assertFalse(self.broker.backing_release_authorized)

    def test_mapper_identity_lock_and_inventory_changes_deny_next_role(self):
        changed = MapperIdentity(
            self.IDENTITY.name, "SWAPZ-OWNER-REPLACED", self.IDENTITY.major,
            self.IDENTITY.minor, "b" * 64,
        )
        self._start_workers(("writer",))
        self.owner.lease.identity_reader = lambda _fd, _name, _ops: changed
        with self.assertRaisesRegex(FixtureOwnerDenied, "fingerprint"):
            self._request("after-identity-change", "a")
        self.assertEqual(len(self.handles), 1)
        self.assertFalse(self.broker.backing_release_authorized)

        case = self._new_case()
        case._start_workers(("writer",))
        case.mapper_ops.entries = (case.IDENTITY, case.IDENTITY)
        with self.assertRaisesRegex(FixtureOwnerDenied, "duplicate mapper identities"):
            case._request("after-ambiguous-inventory", "a")
        self.assertEqual(len(case.handles), 1)

        case = self._new_case()
        case._start_workers(("writer",))
        case.lock_path.unlink()
        case.lock_path.write_text("replacement owner lock")
        case.lock_path.chmod(0o600)
        with self.assertRaises(FixtureOwnerDenied):
            case._request("after-lease-replacement", "a")
        self.assertEqual(len(case.handles), 1)
        self.assertFalse(case.broker.backing_release_authorized)

    def test_latched_denial_cannot_be_cleared_by_a_later_positive_fixture(self):
        self.broker.owner_create()
        with self.assertRaises(FixtureOwnerDenied):
            self.broker.worker_request(self.worker_peer, {
                "request_id": "bad", "operation": "remove", "role": "writer",
            })
        with self.assertRaises(FixtureOwnerDenied):
            self.broker.finalize()
        self.assertFalse(self.broker.backing_release_authorized)
        self.assertTrue(self.broker.backing_must_be_preserved)

    def test_invalid_roles_and_extra_handles_cannot_be_admitted(self):
        self.broker.owner_create()
        with self.assertRaises(FixtureOwnerDenied):
            self.broker.worker_request(self.worker_peer, {
                "request_id": "arbitrary", "operation": "launch_role", "role": "bash",
            })
        self.assertEqual(self.handles, [])
        self.assertFalse(self.broker.backing_release_authorized)

    def test_concurrent_lifecycle_request_denies_even_if_first_launch_returns(self):
        self.broker.owner_create()
        entered = threading.Event()
        release = threading.Event()
        launched: list[object] = []

        def slow_launch(role):
            entered.set()
            release.wait(timeout=1.0)
            handle = f"owned-{role}-thread"
            self.handles.append(handle)
            return handle

        self.broker._worker_launcher = slow_launch
        def launch_one():
            try:
                launched.append(self._request("one", "writer"))
            except Exception as exc:
                launched.append(exc)

        thread = threading.Thread(target=launch_one, daemon=True)
        thread.start()
        self.assertTrue(entered.wait(timeout=1.0))
        with self.assertRaises(FixtureOwnerDenied):
            self._request("two", "a")
        release.set()
        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive())
        self.assertFalse(self.broker.backing_release_authorized)
        self.assertEqual(self.stop_calls, [("owned-writer-thread",)])
        with self.assertRaises(FixtureOwnerDenied):
            self.broker.finalize()


if __name__ == "__main__":
    unittest.main(verbosity=2)
