#!/usr/bin/env python3
"""Rootless pressure token protocol and small-buffer workload regression."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from pressure_checkpoint import publish_release, wait_checkpoint, _expected

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("pressure_helper", HERE / "pressure-helper.py")
assert spec is not None and spec.loader is not None
pressure_helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pressure_helper)
TOKEN = "0123456789abcdef0123456789abcdef"
OTHER_TOKEN = "abcdef0123456789abcdef0123456789"


class PressureCheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def wait_for(self, name: str, seconds: float = 2.0) -> None:
        deadline = time.monotonic() + seconds
        while not (self.directory / name).exists():
            self.assertLess(time.monotonic(), deadline, f"{name} marker not published")
            time.sleep(0.01)

    def worker(self, operation) -> tuple[threading.Thread, list[BaseException]]:
        failures: list[BaseException] = []

        def run() -> None:
            try:
                operation()
            except BaseException as exc:
                failures.append(exc)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread, failures

    def test_both_phases_wait_for_distinct_release_tokens(self) -> None:
        thread, errors = self.worker(lambda: pressure_helper.run_workload(
            1, self.directory, TOKEN, checkpoint_timeout=2))
        self.wait_for("filled")
        self.assertEqual((self.directory / "filled").read_bytes(),
                         _expected(TOKEN, "filled"))
        self.assertFalse((self.directory / "verified").exists())
        self.assertTrue(thread.is_alive())
        with self.assertRaises(FileNotFoundError):
            publish_release(self.directory, TOKEN, "verified")
        with self.assertRaises(ValueError):
            publish_release(self.directory, OTHER_TOKEN, "filled")
        self.assertFalse((self.directory / "release-filled").exists())
        publish_release(self.directory, TOKEN, "filled")
        self.wait_for("verified")
        self.assertEqual((self.directory / "verified").read_bytes(),
                         _expected(TOKEN, "verified"))
        self.assertTrue(thread.is_alive(), "verified release was bypassed")
        publish_release(self.directory, TOKEN, "verified")
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def test_wrong_phase_and_unit_tokens_cannot_release(self) -> None:
        second_dir = self.directory / "other-unit"
        second_dir.mkdir()
        thread, errors = self.worker(lambda: wait_checkpoint(
            self.directory, TOKEN, "filled", timeout_seconds=2))
        self.wait_for("filled")
        with self.assertRaises(FileNotFoundError):
            publish_release(second_dir, TOKEN, "filled")
        with self.assertRaises(ValueError):
            publish_release(self.directory, OTHER_TOKEN, "filled")
        with self.assertRaises(ValueError):
            publish_release(self.directory, TOKEN, "verified")
        self.assertTrue(thread.is_alive())
        publish_release(self.directory, TOKEN, "filled")
        with self.assertRaises(FileExistsError):
            publish_release(self.directory, TOKEN, "filled")
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def test_malformed_or_stale_release_fails_closed(self) -> None:
        (self.directory / "release-filled").write_text("filled:wrong-token\n")
        with self.assertRaises(ValueError):
            wait_checkpoint(self.directory, TOKEN, "filled",
                            timeout_seconds=0.2, poll_seconds=0.01)
        with self.assertRaises(FileExistsError):
            publish_release(self.directory, TOKEN, "filled")
        self.assertEqual((self.directory / "release-filled").read_text(),
                         "filled:wrong-token\n")

    def test_timeout_does_not_advance_phase(self) -> None:
        with self.assertRaisesRegex(TimeoutError, "filled.*timed out"):
            wait_checkpoint(self.directory, TOKEN, "filled",
                            timeout_seconds=0.05, poll_seconds=0.01)
        self.assertFalse((self.directory / "verified").exists())

    def test_interruption_does_not_complete(self) -> None:
        with mock.patch("pressure_checkpoint.time.sleep",
                        side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                wait_checkpoint(self.directory, TOKEN, "filled",
                                timeout_seconds=2)
        self.assertFalse((self.directory / "verified").exists())
        self.assertFalse((self.directory / "release-filled").exists())

    def test_readback_mismatch_cannot_publish_verified(self) -> None:
        def mismatch(*_args, **_kwargs):
            raise ValueError("readback mismatch at pass=0 page=0")

        with mock.patch.object(pressure_helper, "verify_pages",
                               side_effect=mismatch):
            thread, errors = self.worker(lambda: pressure_helper.run_workload(
                1, self.directory, TOKEN, checkpoint_timeout=2))
            self.wait_for("filled")
            publish_release(self.directory, TOKEN, "filled")
            thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIn("readback mismatch", str(errors[0]))
        self.assertFalse((self.directory / "verified").exists())

    def test_actual_corrupted_page_detected(self) -> None:
        seed = 0x5A7A2026 + 1
        buf = bytearray(pressure_helper.page_data(seed, 0))
        view = memoryview(buf)
        pressure_helper.verify_pages(view, 1, seed, passes=2)
        buf[0] ^= 0x01
        with self.assertRaisesRegex(ValueError, "readback mismatch"):
            pressure_helper.verify_pages(view, 1, seed, passes=2)

    def test_nonce_phase_and_static_no_numeric_signal_contract(self) -> None:
        for bad in ("", "../bad", "0" * 31, "Z" * 32):
            with self.assertRaises(ValueError):
                _expected(bad, "filled")
        with self.assertRaises(ValueError):
            _expected(TOKEN, "unexpected")
        fixture = (HERE / "pressure.sh").read_text()
        cleanup = (HERE / "pressure-teardown.sh").read_text()
        helper = (HERE / "pressure-helper.py").read_text()
        self.assertNotIn("kill -CONT", fixture)
        self.assertNotIn("kill -CONT", cleanup)
        self.assertNotIn("SIGSTOP", helper)
        self.assertIn('release "$dir" "$token" filled', fixture)
        self.assertIn('release "$dir" "$token" verified', fixture)
        self.assertIn('systemctl stop --no-block "$unit"', cleanup)


if __name__ == "__main__":
    unittest.main()
