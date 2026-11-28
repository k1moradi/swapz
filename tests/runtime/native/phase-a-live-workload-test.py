#!/usr/bin/env python3
"""Bounded rootless actual mappings; no pressure/native/device execution."""
import contextlib
import copy
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[2] / "tools/phase-a-live-workload.py"
SPEC = importlib.util.spec_from_file_location("live", SOURCE)
live = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(live)


def request(count=8, touches=3):
    return dict(schema="swapz-workload-plan-request", version=2,
                scope=dict(source="1" * 40, run_nonce="2" * 32,
                           area_epoch=41, swap_type=0, target=43),
                page_count=count, hot_page_count=1, touch_count=touches, seed=42,
                max_pages=16, max_operations=64)


def fd_count():
    return len(os.listdir("/proc/self/fd"))


class LiveWorkloadTests(unittest.TestCase):
    def setUp(self):
        self.assertNotEqual(os.geteuid(), 0, "run unprivileged")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        self.before = fd_count()

    def tearDown(self):
        self.assertEqual(fd_count(), self.before)

    def run_live(self, observe, value=None):
        return live.run_live_workload(str(self.path), request() if value is None else value, observe)

    def assert_empty(self):
        self.assertFalse(any(self.path.iterdir()))

    def test_live_identity_and_private_artifacts(self):
        escaped = []
        original = live.pressure.prepare_matched_cold_workload
        captured = []

        @contextlib.contextmanager
        def capture(**kwargs):
            # Test-only instrumentation observes owner-private resources.
            self.assertEqual(len(list(self.path.iterdir())), 2)
            with original(**kwargs) as work:
                captured.append((work, kwargs["tmpfs_fd"]))
                yield work
            self.assertTrue(work._anonymous.closed and work._shmem.closed)
            self.assertEqual(os.fstat(kwargs["tmpfs_fd"]).st_size, 0)

        def observe(handle):
            escaped.append(handle)
            work, fd = captured[0]
            self.assertFalse(work._anonymous.closed or work._shmem.closed)
            self.assertIsNot(work._anonymous, work._shmem)
            self.assertEqual(os.fstat(fd).st_size, 8 * live.PAGE_BYTES)
            commitment = json.loads((self.path / live.producer.ARTIFACT_NAME).read_bytes())
            envelope = json.loads((self.path / live.MAPPING_NAME).read_bytes())
            self.assertTrue(commitment == live.producer.build_commitment(request()))
            self.assertTrue(live.validate_mapping_plan(envelope, commitment) == handle.bindings)
            self.assertEqual(len(handle.bindings), 16)
            for binding in handle.bindings:
                self.assertTrue(handle.validate(binding, handle.run_nonce, handle.mapping_sha256))
            left, right = handle.bindings[0], handle.bindings[8]
            self.assertTrue(commitment["plan"]["pages"][0]["expected_page"] ==
                            commitment["plan"]["pages"][8]["expected_page"])
            self.assertTrue(left.object_token != right.object_token)
            for wrong in (left._replace(object_token=right.object_token),
                          left._replace(offset=4096), left._replace(logical=True),
                          left._replace(backing=right.backing), left._replace(logical=9)):
                with self.assertRaisesRegex(live.producer.PlanError, "binding_mismatch"):
                    handle.validate(wrong, handle.run_nonce, handle.mapping_sha256)
            for nonce, digest in (("3" * 32, handle.mapping_sha256),
                                  (handle.run_nonce, "3" * 64)):
                with self.assertRaisesRegex(live.producer.PlanError, "binding_scope"):
                    handle.validate(left, nonce, digest)

        with patch.object(live.pressure, "prepare_matched_cold_workload", capture):
            result = self.run_live(observe)
        self.assertEqual(result["pages"], 16)
        self.assertEqual(result["callbacks"], 1)
        self.assertEqual(result["status"], "ROOTLESS_LIVE_PREPARATION_ONLY")
        self.assertTrue(result["byte_exact"] and result["mapping_cleanup"])
        self.assertEqual(result["auth"], 0)
        self.assertEqual(result["phase_a"], "BLOCKED")
        self.assertFalse(result["authenticated"] or result["compressed_handoff"] or
                         result["forced_raw"] or result["import_enabled"])
        self.assertNotIn("scope", result)
        self.assertNotIn("mapping_sha256", result)
        self.assertNotIn("bindings", result)
        for artifact in self.path.iterdir():
            self.assertEqual(stat.S_IMODE(artifact.stat().st_mode), 0o600)
        with self.assertRaisesRegex(live.producer.PlanError, "observation_closed"):
            _ = escaped[0].bindings
        with self.assertRaises(OSError):
            os.fstat(captured[0][1])

    def test_structural_negative_plans(self):
        commitment = live.producer.build_commitment(request(2))
        envelope = live.mapping_plan(commitment, ("a" * 32, "b" * 32))
        for mutation in (
            lambda p: p["pages"][1].update(logical=1),
            lambda p: p["pages"][1].update(offset=0),
            lambda p: p["pages"][0].update(object_token="b" * 32),
            lambda p: p["pages"][0].update(offset=False),
            lambda p: p["objects"][1].update(object_token="a" * 32),
            lambda p: p["scope"].update(run_nonce="3" * 32),
            lambda p: p["scope"].update(workload_sha256="3" * 64),
        ):
            altered = copy.deepcopy(envelope)
            mutation(altered["mapping_plan"])
            altered["mapping_sha256"] = live.digest(altered["mapping_plan"])
            with self.assertRaises(live.producer.PlanError):
                live.validate_mapping_plan(altered, commitment)
        altered = dict(envelope, mapping_sha256="0" * 64)
        with self.assertRaises(live.producer.PlanError):
            live.validate_mapping_plan(altered, commitment)

    def test_parity_and_no_cold_reads_until_callback_ends(self):
        # A proxy logs bounded reads only. Real mmap objects remain owned by the
        # frozen helper and all reads/writes delegate to them.
        original = live.pressure.prepare_matched_cold_workload
        reads = []
        active = [False]

        class MappingProbe:
            def __init__(self, mapping):
                self.mapping = mapping
            @property
            def closed(self):
                return self.mapping.closed
            def __len__(self):
                return len(self.mapping)
            def __getitem__(self, key):
                start = key.start if isinstance(key, slice) else key
                reads.append((start, active[0]))
                return self.mapping[key]
            def __setitem__(self, key, value):
                self.mapping[key] = value

        @contextlib.contextmanager
        def capture(**kwargs):
            with original(**kwargs) as work:
                work._anonymous = MappingProbe(work._anonymous)
                work._shmem = MappingProbe(work._shmem)
                yield work

        for touches in (0, 1, 2, 3, 16):
            reads.clear()
            def observe(handle):
                self.assertTrue(all(offset < 4096 for offset, _ in reads))
                before = len(reads)
                active[0] = True
                try:
                    for binding in handle.bindings:
                        self.assertTrue(handle.validate(binding, handle.run_nonce, handle.mapping_sha256))
                    self.assertEqual(len(reads), before)
                finally:
                    active[0] = False
            with patch.object(live.pressure, "prepare_matched_cold_workload", capture):
                result = self.run_live(observe, request(2, touches))
            self.assertTrue(result["byte_exact"])
            self.assertTrue(any(offset >= 4096 for offset, _ in reads))
            self.assertFalse(any(during for _, during in reads))
            for artifact in self.path.iterdir():
                artifact.unlink()

    def test_callback_first_error_and_cleanup(self):
        error = RuntimeError("synthetic callback failure")
        escaped = []
        def observe(handle):
            escaped.append(handle)
            raise error
        with self.assertRaises(RuntimeError) as raised:
            self.run_live(observe)
        self.assertIs(raised.exception, error)
        self.assert_empty()
        with self.assertRaisesRegex(live.producer.PlanError, "observation_closed"):
            _ = escaped[0].run_nonce

    def test_backing_close_failure_preserves_first_error(self):
        original = tempfile.TemporaryFile
        class CloseFailure:
            def __init__(self, **kwargs):
                self.stream = original(**kwargs)
            @property
            def closed(self):
                return self.stream.closed
            def fileno(self):
                return self.stream.fileno()
            def close(self):
                self.stream.close()
                raise OSError("injected backing close failure")

        error = RuntimeError("synthetic callback failure")
        def observe(_):
            raise error
        with patch.object(live.tempfile, "TemporaryFile", CloseFailure):
            with self.assertRaises(RuntimeError) as raised:
                self.run_live(observe, request(2))
            self.assertIs(raised.exception, error)
            self.assertIn("backing_close_failed", error.__notes__)
            self.assert_empty()
            with self.assertRaisesRegex(live.producer.PlanError, "backing_close_failed"):
                self.run_live(lambda _: None, request(2))
            self.assert_empty()

    def test_stale_token_even_with_same_nonce(self):
        old = []
        def first(handle):
            old.extend((handle.bindings[0], handle.run_nonce, handle.mapping_sha256))
        self.run_live(first, request(2))
        for artifact in self.path.iterdir():
            artifact.unlink()
        def second(handle):
            self.assertEqual(handle.run_nonce, old[1])
            self.assertTrue(handle.mapping_sha256 != old[2])
            with self.assertRaisesRegex(live.producer.PlanError, "binding_scope"):
                handle.validate(*old)
            with self.assertRaisesRegex(live.producer.PlanError, "binding_mismatch"):
                handle.validate(old[0], handle.run_nonce, handle.mapping_sha256)
        self.run_live(second, request(2))

    def test_helper_corruption_and_swapped_live_objects(self):
        original = live.pressure.prepare_matched_cold_workload
        for variant in ("hot", "cold", "swap"):
            captured = []
            @contextlib.contextmanager
            def capture(**kwargs):
                with original(**kwargs) as work:
                    captured.append(work)
                    if variant != "swap":
                        work._anonymous[0 if variant == "hot" else 4096] ^= 1
                    yield work
            calls = []
            def observe(handle):
                calls.append(True)
                if variant == "swap":
                    work = captured[0]
                    work._anonymous, work._shmem = work._shmem, work._anonymous
                    with self.assertRaisesRegex(live.producer.PlanError, "mapping_not_live"):
                        _ = handle.bindings
            with patch.object(live.pressure, "prepare_matched_cold_workload", capture):
                with self.assertRaises((live.producer.PlanError, live.pressure.ColdWorkloadError)):
                    self.run_live(observe, request(2))
            self.assertEqual(len(calls), int(variant != "hot"))
            self.assertTrue(captured[0]._anonymous.closed and captured[0]._shmem.closed)
            self.assert_empty()

    def test_exclusive_artifacts_and_directory(self):
        for name in (live.producer.ARTIFACT_NAME, live.MAPPING_NAME):
            artifact = self.path / name
            artifact.write_bytes(b"owner")
            artifact.chmod(0o600)
            with self.assertRaises(FileExistsError):
                self.run_live(lambda _: self.fail("callback after collision"))
            self.assertEqual(artifact.read_bytes(), b"owner")
            self.assertEqual(len(list(self.path.iterdir())), 1)
            artifact.unlink()
        self.path.chmod(0o755)
        try:
            with self.assertRaisesRegex(live.producer.PlanError, "private_directory_required"):
                self.run_live(lambda _: self.fail("callback on nonprivate directory"))
        finally:
            self.path.chmod(0o700)
        self.assert_empty()

    def test_bounds_and_backing_rejection(self):
        for count in (1, 9, True):
            with self.assertRaises(live.producer.PlanError):
                self.run_live(lambda _: self.fail("callback outside bounds"), request(count))
        original = tempfile.TemporaryFile
        def wrong_backing(**_):
            return original(dir=str(self.path))
        with patch.object(live.tempfile, "TemporaryFile", wrong_backing):
            with self.assertRaises(live.pressure.ColdWorkloadError):
                self.run_live(lambda _: self.fail("callback with non-tmpfs backing"))
        self.assert_empty()


if __name__ == "__main__":
    unittest.main(verbosity=2)
