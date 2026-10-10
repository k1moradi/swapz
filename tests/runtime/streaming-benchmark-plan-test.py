#!/usr/bin/env python3
"""Rootless benchmark admission planner tests, including old unsafe defaults.

All tests use pure Python, JSON or a subprocess invoking the planner. They
never invoke the privileged benchmark, kernel modules, devices, NBD or DM.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = ROOT / "tests/runtime/streaming-benchmark-plan.py"
BENCH_PATH = ROOT / "tests/runtime/streaming-benchmark.sh"
SPEC = importlib.util.spec_from_file_location("swapz_benchmark_plan", PLAN_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("missing benchmark planner source")
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class RootlessBenchmarkPlanner(unittest.TestCase):
    def build(self, **overrides):
        params = dict(backend="null_blk", bandwidth=20, latency_ns=500000,
                      strategies="immediate opportunistic staged",
                      batches="auto", repeats=3)
        params.update(overrides)
        return mod.plan(**params)

    def reject(self, expected, **overrides):
        with self.assertRaisesRegex(ValueError, expected):
            self.build(**overrides)

    def call(self, *args):
        return subprocess.run(
            [sys.executable, "-B", str(PLAN_PATH), *args],
            capture_output=True, text=True, timeout=4, check=False)

    def test_default_20mibps_admits_15_comparisons_only_through_256kib(self):
        p = self.build()
        self.assertEqual(p["null_blk_tick_budget_bytes"], 419420)
        self.assertEqual(p["batches_kib"], [4, 8, 16, 32, 64, 128, 256])
        self.assertEqual(p["cases"][0], {"strategy": "immediate", "batch_kib": 4})
        self.assertEqual(len(p["cases"]), 15)
        self.assertEqual(p["total_planned_runs"], 45)
        self.assertTrue(p["backend_runnable"])
        self.assertIsNone(p["qualified_winner"])
        self.assertEqual(p["evidence"], "PLAN_ONLY_NO_MEASUREMENTS")

    def test_oversized_512_and_1024_rejected_before_resource_creation(self):
        for batch in ("4 64 256 512", "1024", "512 1024"):
            with self.subTest(batches=batch):
                self.reject("unserviceable batch KiB", batches=batch)

    def test_default_throttled_1mibps_admits_only_4_8_16(self):
        p = self.build(bandwidth=1)
        self.assertEqual(p["null_blk_tick_budget_bytes"], 20971)
        self.assertEqual(p["batches_kib"], [4, 8, 16])
        self.reject("unserviceable batch KiB", bandwidth=1, batches="32")

    def test_unthrottled_control_admits_1mib_but_cannot_claim_bandwidth(self):
        p = self.build(bandwidth=0)
        self.assertIn(1024, p["batches_kib"])
        self.assertIn("UNTHROTTLED", p["limits"])
        self.assertIn("NOT evidence for a 20 MiB/s", p["limits"])
        self.assertIsNone(p["null_blk_tick_budget_bytes"])

    def test_high_bandwidth_can_admit_1024kib(self):
        p = self.build(bandwidth=64, batches="4 256 512 1024")
        self.assertEqual(p["batches_kib"], [4, 256, 512, 1024])

    def test_immediate_mode_is_always_single_4kib_case(self):
        p = self.build(strategies="immediate")
        self.assertEqual(p["cases"], [{"strategy": "immediate", "batch_kib": 4}])
        self.assertEqual(p["total_planned_runs"], 3)

    def test_policy_subset_and_order_are_preserved(self):
        p = self.build(strategies="staged opportunistic", batches="4 16 64")
        self.assertEqual([x["strategy"] for x in p["cases"]],
                         ["staged"]*3 + ["opportunistic"]*3)
        self.assertEqual(p["total_planned_runs"], 18)

    def test_duplicate_invalid_or_injected_policy_rejected(self):
        for raw in ("", "immediate immediate", "staged dynamic",
                    "staged;echo PWNED", "opportunistic staged untrusted"):
            with self.subTest(raw=raw):
                self.reject("strategies", strategies=raw)

    def test_duplicate_unsorted_unsupported_or_shell_like_batches_rejected(self):
        for raw in ("", "4 4", "16 4", "12", "-1", "4 8;true",
                    "4 $(touch /tmp/should-not-exist)", "4 1025", "4 4.0"):
            with self.subTest(raw=raw):
                self.reject("batches", batches=raw)

    def test_bad_numeric_bounds_rejected(self):
        for kwargs, msg in (
            ({"bandwidth": -1}, "bandwidth"),
            ({"bandwidth": 4097}, "bandwidth"),
            ({"latency_ns": -1}, "latency"),
            ({"latency_ns": 10000000001}, "latency"),
            ({"repeats": 0}, "repeats"),
            ({"repeats": 21}, "repeats"),
            ({"backend": "physical"}, "backend"),
            ({"runtime": 0}, "runtime"),
            ({"runtime": 3601}, "runtime"),
            ({"write_qd": 0}, "writer QD"),
            ({"write_qd": 1025}, "writer QD"),
            ({"compress": -1}, "compressibility"),
            ({"compress": 101}, "compressibility"),
        ):
            with self.subTest(options=kwargs):
                self.reject(msg, **kwargs)

    def test_nbd_plan_cannot_be_mistaken_for_authorized_execution(self):
        p = self.build(backend="nbd", batches="4 256 512 1024")
        self.assertFalse(p["backend_runnable"])
        self.assertIn("PLANNING ONLY", p["limits"])
        self.assertIn("pidfd-owned", p["limits"])
        self.assertEqual(p["total_planned_runs"], 27)
        self.assertIsNone(p["qualified_winner"])

    def test_cli_default_json_is_stable_and_not_performance_evidence(self):
        result = self.call()
        self.assertEqual(result.returncode, 0, result.stderr)
        p = json.loads(result.stdout)
        self.assertEqual(p["schema"], "swapz-v22-rootless-benchmark-plan-v1")
        self.assertEqual(p["total_planned_runs"], 45)
        self.assertIsNone(p["qualified_winner"])

    def test_cli_emits_only_validated_batch_sizes_for_live_bash_runner(self):
        result = self.call("--backend", "null_blk", "--mbps", "20",
                           "--batches", "auto", "--repeats", "1",
                           "--emit-batches")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "4 8 16 32 64 128 256")
        self.assertFalse(result.stderr)

    def test_cli_explicit_unserviceable_batch_returns_nonzero(self):
        result = self.call("--mbps", "20", "--batches", "4 512",
                           "--emit-batches")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("unserviceable batch KiB: 512", result.stderr)

    def test_cli_refuses_nbd_live_batch_emission(self):
        result = self.call("--backend", "nbd", "--emit-batches")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("NBD execution remains disabled", result.stderr)

    def test_live_runner_preflights_before_root_or_resource_allocation(self):
        source = BENCH_PATH.read_text(encoding="utf-8")
        planner = 'BATCHES=$(python3 -B "$ROOT/tests/runtime/streaming-benchmark-plan.py"'
        self.assertIn(planner, source)
        start = source.index(planner)
        first_root = source.index('[[ $EUID -eq 0 ]]')
        allocation = source.index("TMP=$(mktemp")
        setup = source.index("setup_nullblk()")
        self.assertLess(start, first_root)
        self.assertLess(first_root, allocation)
        self.assertLess(start, setup)
        self.assertIn('REQUESTED_BATCHES=' + '$' + '{SWAPZ_BENCH_BATCHES:-auto}', source)
        self.assertIn('exit 4', source[start:first_root])
        self.assertIn("NBD backend disabled: numeric-PID service ownership is not safe", source)
        self.assertIn('if [[ "$BACKEND_KIND" == nbd ]]; then', source)
        self.assertIn("python3 \"$ROOT/tests/runtime/streaming-benchmark-report.py\"", source)

    def test_live_runner_retains_second_guard_against_post_setup_oversized_batch(self):
        source = BENCH_PATH.read_text(encoding="utf-8")
        self.assertIn("NULLBLK_TICK_BYTES", source)
        self.assertIn("unsafe batch ceiling(s)", source)
        self.assertIn("exit 3", source)
        self.assertIn('for strategy in $STRATEGIES; do', source)
        self.assertIn('run_case immediate 4', source)

if __name__ == "__main__":
    unittest.main(verbosity=2)
