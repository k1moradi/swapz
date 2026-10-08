#!/usr/bin/env python3
"""Rootless regression tests for live-GC/foreground-read interval correlation."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


SOURCE = Path(__file__).with_name("live-gc-latency-analyze.py")
spec = importlib.util.spec_from_file_location("live_gc_latency_analyze", SOURCE)
assert spec and spec.loader
analyzer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analyzer)


class LiveGcAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.gc_path = Path(self.directory.name, "gc.csv")
        self.reads_path = Path(self.directory.name, "reads.csv")

    def populate(self, *, gc_rows: str, read_rows: str) -> None:
        self.gc_path.write_text("clock,start_ns,end_ns,moved_pages\n" + gc_rows,
                                encoding="utf-8")
        self.reads_path.write_text("clock,start_ns,end_ns,result\n" + read_rows,
                                   encoding="utf-8")

    def test_overlap_requires_actual_relocation(self) -> None:
        self.populate(gc_rows="monotonic,1000000,4000000,0\n"
                              "monotonic,6000000,10000000,2\n",
                      read_rows="monotonic,2000000,3000000,ok\n"
                                "monotonic,5000000,7000000,ok\n"
                                "monotonic,8000000,9000000,ok\n"
                                "monotonic,11000000,13000000,ok\n")
        report = analyzer.analyze(self.gc_path, self.reads_path, 2)
        self.assertEqual(report["live_gc_events"], 1)
        self.assertEqual(report["live_pages_moved"], 2)
        self.assertEqual(report["overlapping_live_gc"]["count"], 2)
        self.assertEqual(report["outside_live_gc"]["count"], 2)
        self.assertEqual(report["overlapping_live_gc"]["p99_ms"], 2)

    def test_zero_live_gc_rejected(self) -> None:
        self.populate(gc_rows="monotonic,100,200,0\n",
                      read_rows="monotonic,110,120,ok\n")
        with self.assertRaisesRegex(ValueError, "no GC event"):
            analyzer.analyze(self.gc_path, self.reads_path, 1)

    def test_insufficient_tail_samples_rejected(self) -> None:
        self.populate(gc_rows="monotonic,100,200,1\n",
                      read_rows="monotonic,110,120,ok\n")
        with self.assertRaisesRegex(ValueError, "insufficient"):
            analyzer.analyze(self.gc_path, self.reads_path, 10000)

    def test_failed_read_or_clock_mismatch_rejected(self) -> None:
        self.populate(gc_rows="monotonic,100,200,1\n",
                      read_rows="monotonic,110,120,eio\n")
        with self.assertRaisesRegex(ValueError, "unsuccessful"):
            analyzer.analyze(self.gc_path, self.reads_path, 1)
        self.populate(gc_rows="monotonic,100,200,1\n",
                      read_rows="monotonic_raw,110,120,ok\n")
        with self.assertRaisesRegex(ValueError, "clock domain"):
            analyzer.analyze(self.gc_path, self.reads_path, 1)

    def test_touching_boundary_is_not_overlap(self) -> None:
        self.populate(gc_rows="monotonic,100,200,1\n",
                      read_rows="monotonic,50,100,ok\n"
                                "monotonic,200,250,ok\n"
                                "monotonic,150,160,ok\n")
        report = analyzer.analyze(self.gc_path, self.reads_path, 1)
        self.assertEqual(report["overlapping_live_gc"]["count"], 1)
        self.assertEqual(report["outside_live_gc"]["count"], 2)

    def test_bad_gc_intervals_and_counts(self) -> None:
        for row in ("monotonic,-1,200,1\n",
                    "monotonic,300,200,1\n",
                    "monotonic,100,100,1\n",
                    "monotonic,100,200,-1\n",
                    "monotonic,100,200,not-an-int\n",
                    "monotonic,100,200,\n"):
            with self.subTest(row=row):
                self.populate(gc_rows=row,
                              read_rows="monotonic,120,140,ok\n")
                with self.assertRaisesRegex(ValueError, "invalid"):
                    analyzer.analyze(self.gc_path, self.reads_path, 1)

    def test_invalid_read_intervals_and_gc_clock(self) -> None:
        self.populate(gc_rows="monotonic_raw,100,200,1\n",
                      read_rows="monotonic,120,140,ok\n")
        with self.assertRaisesRegex(ValueError, "clock domain"):
            analyzer.analyze(self.gc_path, self.reads_path, 1)
        for row in ("monotonic,-1,140,ok\n",
                    "monotonic,140,120,ok\n",
                    "monotonic,120,120,ok\n"):
            with self.subTest(row=row):
                self.populate(gc_rows="monotonic,100,200,1\n",
                              read_rows=row)
                with self.assertRaisesRegex(ValueError, "invalid"):
                    analyzer.analyze(self.gc_path, self.reads_path, 1)

    def test_missing_required_gc_column(self) -> None:
        self.populate(gc_rows="monotonic,100,200,1\n",
                      read_rows="monotonic,120,140,ok\n")
        self.gc_path.write_text("clock,start_ns,end_ns\n"
                                "monotonic,100,200\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "expected CSV columns"):
            analyzer.analyze(self.gc_path, self.reads_path, 1)

    def test_exact_nearest_rank_percentiles(self) -> None:
        rows = "".join(f"monotonic,0,{millis * 1_000_000},ok\n"
                       for millis in range(1, 101))
        self.populate(gc_rows="monotonic,0,200000000,25\n",
                      read_rows=rows)
        report = analyzer.analyze(self.gc_path, self.reads_path, 100)
        observed = report["overlapping_live_gc"]
        self.assertEqual(observed["count"], 100)
        self.assertEqual(observed["p95_ms"], 95)
        self.assertEqual(observed["p99_ms"], 99)
        self.assertEqual(observed["max_ms"], 100)

    def test_overlapping_gc_windows_are_merged(self) -> None:
        self.populate(gc_rows="monotonic,100,200,1\nmonotonic,150,300,2\n",
                      read_rows="monotonic,250,350,ok\n")
        report = analyzer.analyze(self.gc_path, self.reads_path, 1)
        self.assertEqual(report["merged_live_gc_windows"], 1)
        self.assertEqual(report["overlapping_live_gc"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
