#!/usr/bin/env python3
"""Independent rootless broker admission/containment contracts.

This suite intentionally imports Codex's synthetic fixture without editing its
implementation. No real DM, swap, loop, NBD, or device operations are executed.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import threading
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "swapz_independent_broker_fixture", HERE / "recall-fixture-owner-test.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load the rootless broker fixture")
fixture_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fixture_module
SPEC.loader.exec_module(fixture_module)


class IndependentBrokerContractTests(unittest.TestCase):
    """Exercise public broker calls against independent negative scenarios."""

    def _new_fixture(self):
        fixture = fixture_module.FixtureOwnerBrokerTests("runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    @staticmethod
    def _assert_no_teardown(fixture):
        forbidden = ("worker_report", "swapoff_exact_mapper",
                     "loop_detach_normal", "nbd_disconnect_normal")
        for operation in forbidden:
            if operation in fixture.drain_ops.trace:
                raise AssertionError(f"unexpected drain operation: {operation}")
        if "dm_remove_normal" in fixture.mapper_ops.trace:
            raise AssertionError("unexpected mapper removal")

    def test_every_strict_five_role_prefix_denies_before_drain(self):
        roles = ("writer", "a", "b", "a2", "b2")
        for count in range(len(roles)):
            with self.subTest(admitted_role_count=count):
                fixture = self._new_fixture()
                fixture._start_workers(roles[:count])
                with self.assertRaises(fixture_module.FixtureOwnerDenied):
                    fixture.broker.finalize()
                self.assertTrue(fixture.broker.backing_must_be_preserved)
                self.assertFalse(fixture.broker.mapping_released)
                self._assert_no_teardown(fixture)

    def test_first_concurrent_reader_stays_gated_until_both_ready(self):
        fixture = self._new_fixture()
        fixture._start_workers(("writer", "a", "b"))
        gated = fixture._request("reader-a2", "a2")
        self.assertEqual(gated["status"], "ready_gated")
        self.assertIs(gated["started"], False)
        self.assertNotIn(gated["handle"], sum(fixture.launcher.release_calls, ()))
        with self.assertRaises(fixture_module.FixtureOwnerDenied):
            fixture.broker.finalize()
        self.assertTrue(fixture.broker.backing_must_be_preserved)
        self._assert_no_teardown(fixture)

    def test_unconfirmed_spawn_exception_is_stopped_and_cannot_finalize(self):
        fixture = self._new_fixture()
        fixture.broker.owner_create()
        fixture.launcher.fail.add("launch_after_child")
        with self.assertRaises(fixture_module.FixtureOwnerDenied):
            fixture._request("spawn-ambiguous", "writer")
        self.assertGreaterEqual(fixture.launcher.unconfirmed_stop_calls, 1)
        self.assertEqual(fixture.launcher.pending, [])
        self.assertEqual(fixture.stop_calls, [()])
        self.assertTrue(fixture.broker.backing_must_be_preserved)
        with self.assertRaises(fixture_module.FixtureOwnerDenied):
            fixture.broker.finalize()
        self._assert_no_teardown(fixture)

    def test_last_reader_launch_failure_stops_all_known_children(self):
        fixture = self._new_fixture()
        fixture._start_workers(("writer", "a", "b", "a2"))
        fixture.launcher.fail.add("launch_after_child")
        with self.assertRaises(fixture_module.FixtureOwnerDenied):
            fixture._request("reader-b2", "b2")
        self.assertGreaterEqual(fixture.launcher.unconfirmed_stop_calls, 1)
        self.assertEqual(fixture.launcher.pending, [])
        self.assertEqual(fixture.stop_calls, [tuple(fixture.handles[:4])])
        self.assertTrue(fixture.broker.backing_must_be_preserved)
        self._assert_no_teardown(fixture)

    def test_concurrent_denial_while_finalizing_never_authorizes_backing(self):
        """Current negative-authorization invariant; finalization return is under review.

        A second request can latch denial while the trusted finalizer holds its
        lock. This test proves the exposed backing permission stays false, not
        that in-flight teardown is canceled. See independent review documentation.
        """
        fixture = self._new_fixture()
        fixture._start_workers()
        entered = threading.Event()
        proceed = threading.Event()
        original_collect = fixture.drain_ops.collect_worker_completion
        outcomes = []

        def blocked_collect(handles):
            entered.set()
            if not proceed.wait(timeout=2):
                raise RuntimeError("bounded synthetic finalization barrier expired")
            return original_collect(handles)

        def finalize_in_thread():
            try:
                outcomes.append(fixture.broker.finalize())
            except Exception as exception:
                outcomes.append(exception)

        fixture.drain_ops.collect_worker_completion = blocked_collect
        finalizer = threading.Thread(target=finalize_in_thread, daemon=True)
        finalizer.start()
        try:
            self.assertTrue(entered.wait(timeout=1))
            with self.assertRaises(fixture_module.FixtureOwnerDenied):
                fixture._request("contended", "writer")
        finally:
            proceed.set()
            finalizer.join(timeout=3)
        self.assertFalse(finalizer.is_alive())
        self.assertEqual(len(outcomes), 1)
        self.assertIsNotNone(fixture.broker.denial)
        self.assertFalse(fixture.broker.backing_release_authorized)
        self.assertTrue(fixture.broker.backing_must_be_preserved)


if __name__ == "__main__":
    unittest.main(verbosity=2)
