#!/usr/bin/env python3
"""Rootless tests for deterministic mixed compressed-page fixtures."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from mixed_payloads import (
    PATTERNS,
    bestfit_container_count,
    container_count,
    make_fixture,
    verify_fixture,
    write_fixture,
)


class MixedPayloadFixtureTests(unittest.TestCase):
    def test_clustered_measures_eight_2200_then_eight_1600(self):
        payload, manifest = make_fixture("clustered", 12345)
        self.assertEqual(len(payload), 16 * 4096)
        self.assertEqual(manifest["measured_payload_lengths"], [2200] * 8 + [1600] * 8)
        self.assertEqual(manifest["ordered4_expected_containers"], 12)
        self.assertEqual(manifest["bestfit4_expected_containers"], 8)
        self.assertEqual(container_count(manifest["measured_payload_lengths"]), 12)
        self.assertEqual(bestfit_container_count(manifest["measured_payload_lengths"]), 8)

    def test_alternating_pattern_is_already_ordered_optimally(self):
        _, manifest = make_fixture("alternating", 12345)
        self.assertEqual(manifest["measured_payload_lengths"], [2200, 1600] * 8)
        self.assertEqual(manifest["ordered4_expected_containers"], 8)
        self.assertEqual(manifest["bestfit4_expected_containers"], 8)

    def test_uniform_2072_control_cannot_pair(self):
        _, manifest = make_fixture("uniform", 12345)
        self.assertEqual(manifest["measured_payload_lengths"], [2072] * 16)
        self.assertEqual(manifest["ordered4_expected_containers"], 16)
        self.assertEqual(manifest["bestfit4_expected_containers"], 16)

    def test_each_pattern_uses_exactly_the_declared_order(self):
        for pattern, expected in PATTERNS.items():
            with self.subTest(pattern=pattern):
                _, manifest = make_fixture(pattern, 12345)
                self.assertEqual(manifest["measured_payload_lengths"], list(expected))
                self.assertEqual(manifest["page_count"], 16)
                self.assertEqual(manifest["compressor"], "LZ4_compress_fast")
                self.assertEqual(manifest["acceleration"], 1)
                self.assertEqual(manifest["max_compressed_bytes"], 3568)

    def test_seed_reproduces_bytes_and_changes_payload(self):
        first, first_manifest = make_fixture("clustered", 12345)
        repeat, repeat_manifest = make_fixture("clustered", 12345)
        other, other_manifest = make_fixture("clustered", 12346)
        self.assertEqual(first, repeat)
        self.assertEqual(first_manifest["payload_file_sha256"],
                         repeat_manifest["payload_file_sha256"])
        self.assertEqual(hashlib.sha256(first).hexdigest(),
                         first_manifest["payload_file_sha256"])
        self.assertNotEqual(first, other)
        self.assertNotEqual(first_manifest["payload_file_sha256"],
                            other_manifest["payload_file_sha256"])

    def test_written_capture_remeasures_all_pages_and_binds_digest(self):
        with tempfile.TemporaryDirectory(prefix="swapz-bestfit4-") as directory:
            out = Path(directory) / "fixture"
            manifest = write_fixture("clustered", 12345, out)
            checked = verify_fixture(out / "pages.bin", out / "manifest.json")
            self.assertEqual(manifest["payload_file_sha256"],
                             checked["payload_file_sha256"])
            self.assertEqual(len((out / "pages.bin").read_bytes()), 65536)


if __name__ == "__main__":
    unittest.main(verbosity=2)
