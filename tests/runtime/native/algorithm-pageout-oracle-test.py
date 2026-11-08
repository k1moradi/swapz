#!/usr/bin/env python3
"""Rootless byte-exact and fail-closed pageout-oracle contracts."""
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest import mock

ORACLE = (Path(__file__).resolve().parents[2] / "tools" /
          "algorithm-pageout-oracle.py")
spec = importlib.util.spec_from_file_location("algorithm_pageout_oracle", ORACLE)
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


class AlgorithmPageoutOracleTest(unittest.TestCase):
    def test_page_patterns_cover_entire_pages_and_differ(self):
        seed = bytes.fromhex("0123456789abcdef0123456789abcdef")
        first = subject.page_bytes(seed, 0)
        second = subject.page_bytes(seed, 1)
        self.assertEqual(len(first), 4096)
        self.assertNotEqual(first[:32], first[-32:])
        self.assertNotEqual(first, second)

    def test_byte_exact_verification_and_corruption_detection(self):
        seed = bytes.fromhex("0123456789abcdef0123456789abcdef")
        buffer = bytearray(subject.page_bytes(seed, 0) +
                           subject.page_bytes(seed, 1))
        mismatch_count, _digest = subject.verify_bytes(buffer, seed, 2)
        self.assertEqual(mismatch_count, 0)
        buffer[4095] ^= 1
        mismatches, _digest = subject.verify_bytes(buffer, seed, 2)
        self.assertEqual(mismatches, 1)

    def test_invalid_inputs_fail_before_allocating(self):
        for seed, pages in (("bad", 1), ("0" * 32, 0),
                            ("0" * 32, subject.ORACLE_PAGES + 1)):
            with self.subTest(seed=seed, pages=pages), \
                 mock.patch.object(subject.mmap, "mmap") as allocation:
                self.assertEqual(subject.run_workload(seed, pages), 2)
                allocation.assert_not_called()

    def test_positive_protocol_does_not_claim_unobserved_device_io(self):
        class FakeMapping:
            def __init__(self):
                self.buffer = bytearray(2 * subject.PAGE_BYTES)
                self.advice = []
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def __setitem__(self, key, value):
                self.buffer[key] = value
            def __getitem__(self, key):
                return self.buffer[key]
            def madvise(self, advice):
                self.advice.append(advice)
        mapping = FakeMapping()
        output = io.StringIO()
        with mock.patch.object(subject.resource, "setrlimit"), \
             mock.patch.object(subject.ctypes, "CDLL") as libc, \
             mock.patch.object(subject.mmap, "mmap", return_value=mapping), \
             mock.patch.object(subject.sys, "stdin", io.StringIO("VERIFY\n")), \
             mock.patch.object(subject.sys, "stdout", output):
            libc.return_value.prctl.return_value = 0
            self.assertEqual(subject.run_workload("0" * 32, 2), 0)
        self.assertEqual(mapping.advice, [subject.MADV_PAGEOUT])
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        ready = json.loads(lines[0].removeprefix("ALGORITHM_PAGEOUT_READY="))
        verified = json.loads(lines[1].removeprefix("ALGORITHM_PAGEOUT_VERIFIED="))
        self.assertEqual(ready["bytes"], 2 * subject.PAGE_BYTES)
        self.assertEqual(verified["mismatches"], 0)
        self.assertEqual(verified["actual_sha256"], ready["expected_sha256"])
        self.assertNotIn("device", output.getvalue())

    def test_madvise_refusal_cannot_print_success(self):
        class FakeMapping:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def __setitem__(self, *_):
                pass
            def madvise(self, _):
                raise OSError("page eviction unsupported")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(subject.resource, "setrlimit"), \
             mock.patch.object(subject.ctypes, "CDLL") as libc, \
             mock.patch.object(subject.mmap, "mmap", return_value=FakeMapping()), \
             mock.patch.object(subject.sys, "stdout", stdout), \
             mock.patch.object(subject.sys, "stderr", stderr):
            libc.return_value.prctl.return_value = 0
            self.assertEqual(subject.run_workload("0" * 32, 2), 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("ALGORITHM_PAGEOUT_REFUSED=OSError", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
