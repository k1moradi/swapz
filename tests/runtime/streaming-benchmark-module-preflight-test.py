#!/usr/bin/env python3
"""Rootless, file-only module admission tests: NO module load or device setup."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
SRC = HERE / "streaming-benchmark-module-preflight.py"
BENCH = HERE / "streaming-benchmark.sh"
SPEC = importlib.util.spec_from_file_location("swapz_bench_module_test", SRC)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)
S = "a" * 40
B = "b" * 40
DIGEST = "c" * 64


class ReadOnlyModuleAdmissionTests(unittest.TestCase):
    def good(self, **overrides):
        fields = dict(
            actual_head=S, expected_head=S, expected_source_blob=B,
            checkout_source_blob=B, actual_module_sha=DIGEST,
            expected_module_sha=DIGEST, modinfo_name="dm_swapz",
            modinfo_vermagic="7.0.0-test SMP preempt mod_unload",
            running_kernel="7.0.0-test",
            module_loaded=True, targets="swapz v1.0.0\ncrypt v1.24.0\n",
        )
        fields.update(overrides)
        return m.verify_evidence(**fields)

    def test_complete_source_reported_identity_required(self):
        result = self.good()
        self.assertEqual(result["registered_dm_target"], "swapz")
        self.assertEqual(result["selected_module_sha256"], DIGEST)
        self.assertEqual(result["loaded_module_to_selected_ko_identity"],
                         "NOT_INDEPENDENTLY_ATTESTED")

    def test_missing_wrong_or_ambiguous_target_fails(self):
        for targets in ("", "crypt v1\n", "swapzX v2\n", "swapz v1\nswapz v2\n"):
            with self.subTest(targets=targets), self.assertRaisesRegex(ValueError,
                                                                       "target"):
                self.good(targets=targets)

    def test_missing_module_and_source_mismatch_fails(self):
        for override in (
            {"module_loaded": False},
            {"actual_head": "d" * 40},
            {"expected_source_blob": "f" * 40},
            {"checkout_source_blob": "e" * 40},
            {"actual_module_sha": "0" * 64},
            {"modinfo_name": "dm_delay"},
            {"modinfo_vermagic": "6.8.0-old SMP"},
        ):
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.good(**override)

    def test_malformed_operator_pins_fail_before_queries(self):
        for sha, digest, path in (
            ("x", DIGEST, Path("/tmp/module.ko")),
            (S, "00", Path("/tmp/module.ko")),
            (S, DIGEST, Path("relative.ko")),
        ):
            with self.assertRaises(ValueError):
                m.check_inputs(sha, digest, path)

    def test_pinned_hash_rejects_symlinks_and_hardlinks(self):
        with tempfile.TemporaryDirectory(prefix="swapz-ko-rootless-") as dirname:
            directory = Path(dirname)
            file = directory / "mock-module.ko"
            file.write_bytes(b"ordinary harmless rootless fixture data")
            expected = hashlib.sha256(file.read_bytes()).hexdigest()
            self.assertEqual(m.hash_selected_module(file), expected)
            link = directory / "module-link.ko"
            link.symlink_to(file)
            with self.assertRaises(ValueError):
                m.hash_selected_module(link)
            hardlink = directory / "module-hardlink.ko"
            os.link(file, hardlink)
            with self.assertRaisesRegex(ValueError, "singly-linked"):
                m.hash_selected_module(file)
            hardlink.unlink()
            self.assertEqual(m.hash_selected_module(file), expected)

    def test_probe_commands_are_read_only_and_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix="swapz-module-check-") as dirname:
            directory = Path(dirname)
            ko = directory / "fake.ko"
            ko.write_bytes(b"not a kernel module; tests only")
            target_dir = directory / "loaded"
            target_dir.mkdir()
            sha = hashlib.sha256(ko.read_bytes()).hexdigest()
            observed = [
                S, B, B, "dm_swapz",
                "7.0.0-test SMP preempt mod_unload", "swapz v1.0.0\n",
            ]
            commands = []
            def query(args):
                commands.append(args)
                return observed[len(commands) - 1]
            with (mock.patch.object(m, "protected_module_path"),
                  mock.patch.object(m, "_query", side_effect=query),
                  mock.patch.object(m.os, "uname") as uname):
                uname.return_value.release = "7.0.0-test"
                good = m.preflight(S, sha, ko, checkout=directory,
                                   module_root=target_dir)
            self.assertEqual(good["source_sha"], S)
            self.assertEqual(len(commands), 6)
            self.assertEqual(commands[-1], ["dmsetup", "targets"])
            self.assertIn(["modinfo", "-F", "name", str(ko)], commands)
            self.assertTrue(all(c[0] in {"git", "modinfo", "dmsetup"} for c in commands))

    def test_cli_refuses_without_all_pins_before_any_device_operation(self):
        cmd = subprocess.run(
            [sys.executable, "-B", str(SRC), "--source-sha", S],
            capture_output=True, text=True, timeout=5)
        self.assertNotEqual(cmd.returncode, 0)
        self.assertIn("required", cmd.stderr)
        self.assertNotIn("BENCH_PREFLIGHT=PASS", cmd.stdout)

    def test_benchmark_shell_places_gate_before_fixture_allocation(self):
        source = BENCH.read_text(encoding="utf-8")
        gate = source.index('tests/runtime/streaming-benchmark-module-preflight.py"')
        first_tmp = source.index("TMP=$(mktemp")
        setup = source.index("setup_nullblk()")
        self.assertLess(gate, first_tmp)
        self.assertLess(gate, setup)
        for variable in ("SWAPZ_BENCH_SOURCE_SHA", "SWAPZ_BENCH_MODULE_SHA256",
                         "SWAPZ_BENCH_MODULE_PATH"):
            self.assertIn(variable, source[:first_tmp])
        self.assertNotIn('insmod "', source[:first_tmp])
        self.assertNotIn("modprobe dm_swapz", source[:first_tmp])

    def test_bash_syntax_without_invoking_any_live_benchmark(self):
        cmd = subprocess.run(["bash", "-n", str(BENCH)],
                             capture_output=True, text=True, timeout=5)
        self.assertEqual(cmd.returncode, 0, cmd.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
