#!/usr/bin/env python3
"""Fully rootless fabricated three-case comparison tests; NO measured performance."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


compare = load("swapz_fast_comparison_tested", "v22-fast-compare.py")
fixtures = load("swapz_fast_screen_mock_fixtures", "v22-fast-screen-test.py")


class ThreeCaseComparison(unittest.TestCase):
    def setUp(self):
        # Reuse the established, deliberately fabricated fixture generator:
        # each row includes an exact RLE sidecar and runner completion marker.
        self.fixture = fixtures.ThreeCaseScreenTests(
            "test_fast_profile_is_exactly_three_no_execution")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tmp.cleanup)
        self.root = self.fixture.root
        self.results = self.fixture.path

    def test_pinned_finalized_fabricated_result_compares_all_cases(self):
        result = compare.compare(self.results)
        self.assertEqual([c["strategy"] for c in result["cases"]],
                         ["immediate", "opportunistic", "staged"])
        self.assertEqual([c["exact_read_p95_ms"] for c in result["cases"]],
                         [1.0, 1.1, 1.2])
        self.assertEqual(result["cases"][0]["relative_to_immediate"][
            "lower_write_ios_ratio"], 1.0)
        self.assertIsNone(result["qualified_winner"])
        self.assertFalse(result["independent_kernel_quiescence_or_device_attribution"])
        formatted = compare.markdown(result)
        self.assertIn("NO QUALIFIED WINNER", formatted)
        self.assertIn("Exact p95", formatted)
        self.assertIn("Staged (64 KiB)", formatted)
        self.assertIn("source-reported teardown-marker", formatted)

    def test_relative_lower_requests_and_sectors_are_not_confused(self):
        self.fixture.rows[1]["lower_write_ios"] = 5
        self.fixture.rows[1]["lower_write_sectors"] = 2048
        self.fixture.rows[2]["lower_write_ios"] = 20
        self.fixture.rows[2]["lower_write_sectors"] = 8192
        self.fixture.save()
        self.fixture.seal()
        result = compare.compare(self.results)
        self.assertEqual([round(c["relative_to_immediate"][
            "lower_write_ios_ratio"], 1) for c in result["cases"]],
            [1.0, 0.5, 2.0])
        self.assertEqual([round(c["relative_to_immediate"][
            "lower_write_sectors_ratio"], 1) for c in result["cases"]],
            [1.0, 0.5, 2.0])

    def test_missing_marker_or_mutated_latency_sidecar_refuses_report(self):
        self.fixture.marker.unlink()
        with self.assertRaises((ValueError, FileNotFoundError, OSError)):
            compare.compare(self.results)
        self.fixture.seal()
        name = self.fixture.rows[0]["exact_read_latency"]["read_latency_sidecar"]
        (self.root / name).write_bytes(b"x"*16)
        with self.assertRaises(ValueError):
            compare.compare(self.results)

    def test_corrupt_input_and_modified_rows_never_produce_a_winner(self):
        self.fixture.rows[1]["read_count"] = 20
        self.fixture.save()
        self.fixture.seal()
        with self.assertRaises(ValueError):
            compare.compare(self.results)
        self.fixture.rows[1]["read_count"] = 1200
        self.fixture.rows[2]["strategy"] = "immediate"
        self.fixture.save()
        self.fixture.seal()
        with self.assertRaises(ValueError):
            compare.compare(self.results)

    def test_cli_markdown_and_json_are_unqualified_and_read_only(self):
        for format in ("json", "markdown"):
            process = subprocess.run([
                sys.executable, "-B", str(HERE / "v22-fast-compare.py"),
                "--results", str(self.results), "--format", format,
            ], capture_output=True, text=True, timeout=5)
            self.assertEqual(process.returncode, 0, process.stderr)
            if format == "json":
                self.assertIsNone(json.loads(process.stdout)["qualified_winner"])
            else:
                self.assertIn("NO QUALIFIED WINNER", process.stdout)
        self.assertEqual(len(list(self.root.glob("*.latbin"))), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
