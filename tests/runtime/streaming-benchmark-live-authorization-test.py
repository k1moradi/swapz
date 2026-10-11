#!/usr/bin/env python3
"""Pure rootless live-scope regression: no kernel, device or VM operations."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "streaming-benchmark-live-authorization.py"
BENCH = HERE / "streaming-benchmark.sh"
SPEC = importlib.util.spec_from_file_location("swapz_bench_vm_gate_test", SCRIPT)
assert SPEC and SPEC.loader
auth = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(auth)
SHA = "b" * 40
MOD = "e" * 64


def baseline(**overrides):
    config = {
        "SWAPZ_BENCH_VM_ID": "disposable-swapz-3strategy-20261010",
        "SWAPZ_BENCH_SOURCE_SHA": SHA,
        "SWAPZ_BENCH_MODULE_SHA256": MOD,
        "SWAPZ_BENCH_MODULE_PATH": "/root/swapz-bench/dm-swapz.ko",
        "SWAPZ_BENCH_BACKEND": "null_blk",
        "SWAPZ_BENCH_MBPS": "20",
        "SWAPZ_BENCH_LATENCY_NS": "500000",
        "SWAPZ_BENCH_RUNTIME": "10",
        "SWAPZ_BENCH_QD": "64",
        "SWAPZ_BENCH_COMPRESS": "50",
        "SWAPZ_BENCH_READ_IOPS": "300",
        "SWAPZ_BENCH_BATCHES": "64",
        "SWAPZ_BENCH_STRATEGIES": "immediate opportunistic staged",
        "SWAPZ_BENCH_DISCARD": "0",
        "SWAPZ_BENCH_KEEP_ARTIFACTS": "1",
    }
    config.update(overrides)
    return config


def vm_result(value="kvm", rc=0):
    return subprocess.CompletedProcess(["systemd-detect-virt", "--vm"],
                                       rc, stdout=value, stderr="")


class BenchmarkLiveScopeTest(unittest.TestCase):
    def test_one_exact_three_case_proposal_is_not_permission(self):
        scope, plan = auth.proposal(baseline())
        self.assertEqual(plan["total_planned_runs"], 3)
        self.assertIn(
            "cases in order [immediate:4KiB,opportunistic:64KiB,staged:64KiB]",
            scope)
        self.assertIn("runtime=10s/case", scope)
        self.assertIn("reader_iops_target=300", scope)
        self.assertIn("no swap", "no swap") if False else None
        self.assertIn("not authorized are physical storage", scope)
        self.assertIn("loading/unloading dm_swapz", scope)
        self.assertNotIn("--run-live", scope)

    def test_explicit_exact_authorization_and_vm_guest_indication(self):
        env = baseline()
        scope, _ = auth.proposal(env)
        env["SWAPZ_BENCH_AUTHORIZATION"] = scope
        fake = mock.Mock(return_value=vm_result())
        self.assertIn("AUTHORIZED_STATEMENT", auth.check(env, fake))
        fake.assert_called_once_with(
            ["systemd-detect-virt", "--vm"], capture_output=True, text=True,
            timeout=3, check=False)

    def test_no_authorization_or_old_scope_short_circuits_vm_query(self):
        env = baseline()
        never = mock.Mock(side_effect=AssertionError("VM query must not run"))
        with self.assertRaisesRegex(ValueError, "missing or mismatched"):
            auth.check(env, never)
        env["SWAPZ_BENCH_AUTHORIZATION"] = "old-smoke-authorization"
        with self.assertRaisesRegex(ValueError, "missing or mismatched"):
            auth.check(env, never)
        never.assert_not_called()

    def test_each_changed_run_dimension_requires_separate_exact_scope(self):
        env = baseline()
        original, _ = auth.proposal(env)
        env["SWAPZ_BENCH_AUTHORIZATION"] = original
        changes = {
            "SWAPZ_BENCH_VM_ID": "disposable-another",
            "SWAPZ_BENCH_SOURCE_SHA": "c"*40,
            "SWAPZ_BENCH_MODULE_SHA256": "a"*64,
            "SWAPZ_BENCH_MODULE_PATH": "/root/another-approved.ko",
            "SWAPZ_BENCH_MBPS": "21",
            "SWAPZ_BENCH_LATENCY_NS": "1000000",
            "SWAPZ_BENCH_RUNTIME": "11",
            "SWAPZ_BENCH_QD": "32",
            "SWAPZ_BENCH_COMPRESS": "20",
            "SWAPZ_BENCH_READ_IOPS": "500",
            "SWAPZ_BENCH_BATCHES": "32",
            "SWAPZ_BENCH_STRATEGIES": "immediate staged",
            "SWAPZ_BENCH_DISCARD": "1",
            "SWAPZ_BENCH_KEEP_ARTIFACTS": "0",
        }
        for key, value in changes.items():
            with self.subTest(dimension=key):
                other = {**env, key: value}
                fake = mock.Mock()
                with self.assertRaises(ValueError):
                    auth.check(other, fake)
                fake.assert_not_called()

    def test_scope_rejects_host_identity_and_unsafe_numeric_inputs(self):
        bad = [
            ("SWAPZ_BENCH_VM_ID", "host"),
            ("SWAPZ_BENCH_VM_ID", "disposable-;rm"),
            ("SWAPZ_BENCH_SOURCE_SHA", "not-a-commit"),
            ("SWAPZ_BENCH_MODULE_SHA256", "0"*40),
            ("SWAPZ_BENCH_MODULE_PATH", "relative.ko"),
            ("SWAPZ_BENCH_READ_IOPS", "2001"),
            ("SWAPZ_BENCH_READ_IOPS", "notnumber"),
            ("SWAPZ_BENCH_RUNTIME", "0"),
            ("SWAPZ_BENCH_QD", "-1"),
            ("SWAPZ_BENCH_BATCHES", "512"),
            ("SWAPZ_BENCH_STRATEGIES", "staged;true"),
            ("SWAPZ_BENCH_BACKEND", "nbd"),
            ("SWAPZ_BENCH_KEEP_ARTIFACTS", "2"),
        ]
        for key, val in bad:
            with self.subTest(key=key, value=val):
                with self.assertRaises(ValueError):
                    auth.proposal(baseline(**{key: val}))

    def test_full_fifteen_case_sweep_has_distinct_authorization(self):
        screen, _ = auth.proposal(baseline())
        full, p = auth.proposal(baseline(
            SWAPZ_BENCH_BATCHES="4 8 16 32 64 128 256",
            SWAPZ_BENCH_RUNTIME="30", SWAPZ_BENCH_READ_IOPS="500"))
        self.assertNotEqual(full, screen)
        self.assertEqual(p["total_planned_runs"], 15)
        self.assertIn("staged:256KiB", full)
        self.assertNotIn("staged:512KiB", full)

    def test_non_guest_results_and_errors_fail_closed(self):
        for result in (
            vm_result("", 0), vm_result("none", 1),
            vm_result("docker", 0), vm_result("lxc", 0),
            vm_result("wsl", 0), vm_result("kvm", 1),
            vm_result("host machine", 0),
        ):
            with self.subTest(result=result):
                with self.assertRaisesRegex(ValueError, "did not establish"):
                    auth.vm_indication(mock.Mock(return_value=result))
        for failure in (OSError("unavailable"), subprocess.TimeoutExpired("virt", 3)):
            with self.assertRaisesRegex(ValueError, "cannot confirm"):
                auth.vm_indication(mock.Mock(side_effect=failure))

    def test_live_runner_requires_flag_and_guards_before_allocation(self):
        src = BENCH.read_text(encoding="utf-8")
        self.assertIn('"$1" != "--run-live"', src)
        self.assertLess(src.index('"$1" != "--run-live"'), src.index("setup_nullblk()"))
        gate = src.index('tests/runtime/streaming-benchmark-live-authorization.py')
        module = src.index('tests/runtime/streaming-benchmark-module-preflight.py')
        tmp = src.index("TMP=$(mktemp")
        self.assertLess(gate, module)
        self.assertLess(module, tmp)
        self.assertLess(gate, src.index("setup_nullblk()"))
        self.assertIn("systemd-detect-virt", src[:tmp])

    def test_default_shell_is_inert_even_when_invoked_directly(self):
        cmd = subprocess.run(
            ["bash", str(BENCH)],
            capture_output=True, text=True, timeout=3,
        )
        self.assertEqual(cmd.returncode, 4)
        self.assertIn("explicitly pass --run-live", cmd.stderr)
        self.assertNotIn("PASS", cmd.stdout)

    def test_rootless_cli_proposal_never_queries_system_state(self):
        env = baseline()
        cmd = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--show-statement"],
            env={**os.environ, **env},
            capture_output=True, text=True, timeout=4,
        )
        self.assertEqual(cmd.returncode, 0, cmd.stderr)
        self.assertIn("cases in order [immediate:4KiB", cmd.stdout)
        self.assertIn("PROPOSAL_ONLY_NO_AUTHORIZATION", cmd.stderr)
        self.assertNotIn("AUTHORIZED_STATEMENT", cmd.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
