#!/usr/bin/env python3
"""Exercise the private, aggregate-only anonymous page analyzer."""
import json
import struct
import subprocess
import sys
import unittest
from pathlib import Path

PAGE = 4096
ANALYZER = Path(sys.argv[1]).resolve()


class AnonymousPageAnalyzer(unittest.TestCase):
    def analyze(self, sample):
        return subprocess.run([str(ANALYZER)], input=sample,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, check=False)

    def test_aggregates_only_and_preserves_zero_policy_geometry(self):
        marker = b"SWAPZ_PRIVATE_PAGE_MARKER_38cbd917"
        counter = b"".join(struct.pack("<Q", 0x6c39 + index)
                            for index in range(PAGE // 8))
        marker_page = (marker + bytes((index * 73 + 19) & 0xff
                                      for index in range(PAGE - len(marker))))
        sample = bytes(PAGE) + bytes([0x5a]) * PAGE + counter + marker_page

        process = self.analyze(sample)
        self.assertEqual(process.returncode, 0, process.stderr.decode(errors="replace"))
        self.assertEqual(process.stderr, b"")
        self.assertNotIn(marker, process.stdout)
        self.assertNotIn(marker, process.stderr)

        report = json.loads(process.stdout)
        self.assertEqual(report["schema"], "swapz-anon-page-analysis-v1")
        self.assertEqual(report["page_bytes"], PAGE)
        self.assertEqual(report["pages"], 4)
        self.assertEqual(report["zero_pages"], 1)
        self.assertEqual(report["nonzero_same_filled_pages"], 1)
        self.assertEqual(report["predictor_backend"]["transform"],
                         report["predictor_backend"]["inverse"])
        self.assertGreater(report["lz4_version"], 0)
        self.assertEqual(report["lz4"]["acceleration"], 1)
        self.assertEqual(report["delta64_shuf8_lz4"]["acceleration"], 4)
        self.assertEqual(sum(report["lz4"]["size_buckets"].values()), 4)
        self.assertEqual(sum(report["delta64_shuf8_lz4"]["size_buckets"].values()), 4)
        self.assertEqual(report["classifier"]["eligible_pages"],
                         report["classifier"]["scored_pages"])
        self.assertGreater(report["classifier"]["transform_attempts"], 0)
        self.assertGreater(report["production_route"]["direct_adoptions"], 0)
        self.assertEqual(
            report["production_route"]["adopted_pages"],
            report["production_route"]["direct_adoptions"] +
            report["production_route"]["raw_rescues"] +
            report["production_route"]["lz4_rescues"])
        self.assertEqual(report["planner"]["windows"], 1)
        self.assertGreater(report["planner"]["baseline_lower_blocks"], 0)
        self.assertGreater(report["planner"]["production_route_lower_blocks"], 0)

    def test_planner_processes_full_and_partial_64_page_windows(self):
        page = bytes([0x3d]) * PAGE
        process = self.analyze(page * 65)
        self.assertEqual(process.returncode, 0, process.stderr.decode(errors="replace"))
        report = json.loads(process.stdout)
        self.assertEqual(report["pages"], 65)
        self.assertEqual(report["planner"]["windows"], 2)
        self.assertEqual(report["planner"]["baseline_lower_blocks"], 2)
        self.assertEqual(report["planner"]["baseline_extents"], 2)

    def test_empty_and_partial_streams_fail_without_json(self):
        for sample, diagnostic in ((b"", b"page stream is empty"),
                                   (b"partial", b"partial 4 KiB page")):
            with self.subTest(sample_length=len(sample)):
                process = self.analyze(sample)
                self.assertEqual(process.returncode, 2)
                self.assertEqual(process.stdout, b"")
                self.assertIn(diagnostic, process.stderr)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
