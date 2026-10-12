#!/usr/bin/env python3
"""Rootless tests for the exact-C V3 benchmark and deterministic fixtures."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "research/extent-v3-bench/engine-bench.c"


class ExtentV3EngineBenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="sv3-bench-test-")
        cls.directory = Path(cls.temp.name)
        cls.binary = cls.directory / "engine-bench"
        command = [
            "cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            "-I", str(ROOT / "kernel/extent-v3"), str(SOURCE),
            str(ROOT / "kernel/extent-v3/engine.c"),
            str(ROOT / "kernel/extent-v3/authority.c"),
            str(ROOT / "kernel/extent-v3/codec.c"), "-llz4", "-o",
            str(cls.binary),
        ]
        subprocess.run(command, cwd=ROOT, check=True, capture_output=True,
                       text=True, timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_rows(self, *args):
        result = subprocess.run([str(self.binary), *args], cwd=ROOT,
                                check=True, capture_output=True, text=True,
                                timeout=30)
        return [json.loads(line) for line in result.stdout.splitlines()
                if line.strip()]

    def test_uniform_2072_geometry_control(self):
        artifacts = self.directory / "control"
        artifacts.mkdir(exist_ok=True)
        rows = self.run_rows(
            "--synthetic", "--scenario", "control2072", "--window", "16",
            "--reps", "1", "--warmups", "0", "--seed", "12345",
            "--artifact-dir", str(artifacts))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertTrue(row["correct"])
        self.assertEqual(row["records"], 16)
        self.assertEqual(row["ordered4_model_bytes"], 65536)
        self.assertEqual(row["v3_written_bytes"], 40960)
        self.assertEqual(row["modeled_ordered_over_v3"], 1.6)
        self.assertEqual(row["completed_blocks"], row["v3_written_blocks"])
        self.assertEqual(row["physical_read_blocks"], 30)
        self.assertTrue((artifacts /
                         "control2072-window-16-seed-12345.input").is_file())

    def test_mixed_size_clustered_and_alternating_controls(self):
        clustered = self.run_rows(
            "--synthetic", "--scenario", "clustered", "--window", "16",
            "--reps", "1", "--warmups", "0", "--seed", "12345")[0]
        alternating = self.run_rows(
            "--synthetic", "--scenario", "alternating", "--window", "16",
            "--reps", "1", "--warmups", "0", "--seed", "12345")[0]
        self.assertTrue(clustered["correct"])
        self.assertTrue(alternating["correct"])
        self.assertLessEqual(clustered["v3_written_blocks"],
                             clustered["ordered4_model_blocks"])
        self.assertEqual(alternating["v3_written_blocks"],
                         alternating["ordered4_model_blocks"])

    def test_actual_lz4_payloads_and_raw_fallback(self):
        artifacts = self.directory / "lz4"
        artifacts.mkdir(exist_ok=True)
        rows = self.run_rows(
            "--lz4", "--reps", "1", "--warmups", "0", "--seed", "12345",
            "--artifact-dir", str(artifacts))
        distributions = {r["workload"]: r for r in rows
                         if r["kind"] == "lz4_distribution"}
        engine = [r for r in rows if r["kind"] == "engine"]
        raw = [r for r in rows if r["kind"] == "lz4_raw_fallback"]
        self.assertEqual(len(distributions), 5)
        self.assertEqual(len(engine), 5)
        self.assertTrue(all(r["correct"] and r["error"] == 0 for r in engine))
        self.assertEqual(distributions["lz4_uniform2072"]["lengths"],
                         [2072] * 16)
        self.assertEqual(distributions["lz4_uniform1048"]["lengths"],
                         [1048] * 16)
        self.assertEqual(distributions["lz4_clustered"]["lengths"],
                         [2200] * 8 + [1600] * 8)
        self.assertEqual(distributions["lz4_alternating"]["lengths"],
                         [2200, 1600] * 8)
        self.assertEqual(len(raw), 1)
        self.assertEqual(raw[0]["compressed_with_3568_cap"], 0)
        self.assertEqual(raw[0]["engine_plan_rc"], -95)
        self.assertTrue(raw[0]["expected_unsupported"])
        for name in distributions:
            self.assertTrue((artifacts / f"{name}-raw-pages.bin").is_file())
            self.assertTrue((artifacts / f"{name}-lz4-blocks.bin").is_file())
        self.assertTrue((artifacts / "lz4-raw-fallback-page.bin").is_file())

    def test_fault_injection_and_counter_reconciliation(self):
        rows = self.run_rows("--faults")
        self.assertEqual(len(rows), 4)
        by_name = {r["fault"]: r for r in rows}
        for name in ("fail_before_write", "partial_lower_extent",
                     "overreported_completion"):
            self.assertLess(by_name[name]["engine_rc"], 0)
            self.assertEqual(by_name[name]["published_maps"], 0)
            self.assertEqual(by_name[name]["committed_pages"], 0)
        self.assertEqual(by_name["partial_lower_extent"]
                         ["actual_written_blocks"], 1)
        self.assertEqual(by_name["partial_lower_extent"]
                         ["validated_completed_blocks"], 1)
        self.assertEqual(by_name["overreported_completion"]
                         ["validated_completed_blocks"], 0)
        corruption = by_name["post_write_payload_corruption"]
        self.assertEqual(corruption["engine_rc"], 0)
        self.assertEqual(corruption["read_rc"], -74)
        self.assertEqual(corruption["committed_pages"], 3)

    def test_randomized_latest_value_oracle(self):
        rows = self.run_rows("--randomized", "--cases", "2048",
                             "--seed", "12345")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["verified_latest_pages"])
        self.assertEqual(rows[0]["operations"], 2048)
        self.assertEqual(rows[0]["error"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
