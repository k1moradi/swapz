#!/usr/bin/env python3
"""Rootless negative tests for protected reviewed live benchmark source."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import stat
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
SRC = HERE / "streaming-benchmark-source-preflight.py"
BENCH = HERE / "streaming-benchmark.sh"
SPEC = importlib.util.spec_from_file_location("swapz_bench_protected_source_test", SRC)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
SHA = "a" * 40
BLOB = "b" * 40


class ProtectedBenchmarkSourceTests(unittest.TestCase):
    def test_reject_wrong_owner_writable_symlink_missing_and_type(self):
        cases = (
            (stat.S_IFREG | 0o600, 1000, None, "root-owned"),
            (stat.S_IFREG | 0o662, 0, None, "root-owned"),
            (stat.S_IFLNK | 0o777, 0, None, "root-owned"),
            (stat.S_IFDIR | 0o700, 0, False, "regular"),
            (stat.S_IFREG | 0o600, 0, True, "directory"),
        )
        for mode, uid, directory, error in cases:
            with self.subTest(mode=mode, uid=uid, directory=directory):
                with mock.patch.object(Path, "lstat",
                                       return_value=SimpleNamespace(
                                           st_mode=mode, st_uid=uid)):
                    with self.assertRaisesRegex(ValueError, error):
                        m.protect_metadata(Path("/tmp/example"), directory=directory)

    def test_positive_protected_metadata_requires_correct_type(self):
        for directory, kind in ((True, stat.S_IFDIR), (False, stat.S_IFREG)):
            with mock.patch.object(Path, "lstat",
                                   return_value=SimpleNamespace(
                                       st_mode=kind | 0o700, st_uid=0)):
                m.protect_metadata(Path("/root/source"), directory=directory)

    def test_digest_binds_all_executable_and_transitive_source_dependencies(self):
        requested = []
        def query(args):
            requested.append(args)
            if args[-1] == "HEAD":
                return SHA
            if args[-2] == "rev-parse" or args[-2] == "hash-object":
                return BLOB
            raise AssertionError(args)
        m.verify_blobs(SHA, Path("/protected"), query)
        self.assertEqual(len(requested), 1 + len(m.PATHS) * 2)
        expected = [req[-1] for req in requested if req[-2] == "hash-object"]
        self.assertEqual(expected, list(m.PATHS))
        self.assertIn("tests/runtime/streaming-benchmark-quarantine.sh", expected)
        self.assertIn("tests/runtime/streaming-benchmark-teardown.sh", expected)
        self.assertIn("tests/runtime/streaming-benchmark-writer-verify.py", expected)

    def test_wrong_sha_or_modified_helper_is_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "full lowercase"):
            m.verify_blobs("wrong", query=lambda _: SHA)
        with self.assertRaisesRegex(ValueError, "HEAD differs"):
            m.verify_blobs(SHA, query=lambda _: "c"*40)
        def query(args):
            last = args[-1]
            if last == "HEAD":
                return SHA
            if last.startswith(SHA + ":"):
                return BLOB
            return "f"*40 if last.endswith("streaming-benchmark-teardown.sh") else BLOB
        with self.assertRaisesRegex(ValueError, "teardown.sh"):
            m.verify_blobs(SHA, query=query)

    def test_unprotected_user_checkout_rejected_no_privileges(self):
        with tempfile.TemporaryDirectory(prefix="swapz-untrusted-runner-") as dirname:
            with self.assertRaisesRegex(ValueError, "root-owned/protected|unavailable"):
                m.protected_checkout(Path(dirname))

    def test_shell_admission_precedes_module_and_fixture_allocation(self):
        src = BENCH.read_text(encoding="utf-8")
        auth = src.index('tests/runtime/streaming-benchmark-live-authorization.py')
        protected = src.index('tests/runtime/streaming-benchmark-source-preflight.py')
        module = src.index('tests/runtime/streaming-benchmark-module-preflight.py')
        fixture = src.index("TMP=$(mktemp")
        self.assertLess(auth, protected)
        self.assertLess(protected, module)
        self.assertLess(module, fixture)
        self.assertIn('TARGET_UUID="SWAPZ-V22-$TAG"', src)
        self.assertIn('NULL_CFG_OWNED=0', src)
        syntax = subprocess.run(["bash", "-n", str(BENCH)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def test_cli_rejects_invalid_sha_rootlessly(self):
        process = subprocess.run(
            [sys.executable, "-B", str(SRC), "--source-sha", "bad"],
            capture_output=True, text=True, timeout=5)
        self.assertNotEqual(process.returncode, 0)
        self.assertNotIn("PASS_PROTECTED", process.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
