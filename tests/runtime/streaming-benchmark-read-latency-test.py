#!/usr/bin/env python3
"""Rootless exact-reader-log conversion regressions (synthetic logs only)."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
MODULE = HERE / "streaming-benchmark-read-latency.py"
SPEC = importlib.util.spec_from_file_location("swapz_reader_clat", MODULE)
assert SPEC is not None and SPEC.loader is not None
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


V3_SPEC = importlib.util.spec_from_file_location(
    "swapz_plateau_v3_reader", HERE / "v22-drain-plateau-analyze.py")
assert V3_SPEC is not None and V3_SPEC.loader is not None
plateau = importlib.util.module_from_spec(V3_SPEC)
V3_SPEC.loader.exec_module(plateau)


class ExactReaderLatencyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.json = self.root / "fio.json"
        self.log = self.root / "reader_clat.log"
        self.sidecar = self.root / "reader.latbin"
        self.samples = [100, 200, 300, 400, 500]
        self.make_fio(len(self.samples))
        self.make_log(self.samples)

    def make_fio(self, count: int):
        self.json.write_text(json.dumps({"jobs": [
            {"jobname": "writer", "read": {"total_ios": 0}},
            {"jobname": "reader", "read": {"total_ios": count}},
        ]}), encoding="utf-8")

    def make_log(self, samples: list[int]):
        self.log.write_text("".join(f"{index}, {latency}, 0, 4096\n"
                                    for index, latency in enumerate(samples)), encoding="utf-8")

    def test_exact_repeated_values_nearest_rank_and_sha256(self):
        self.samples = [100] * 99 + [200] + [400]
        self.make_fio(len(self.samples))
        self.make_log(self.samples)
        result = collector.collect(self.json, self.log, self.sidecar)
        self.assertEqual(result["read_count"], 101)
        self.assertEqual(result["read_p99_ns"], 200)
        self.assertEqual(self.sidecar.read_bytes(),
                         b"".join(struct.pack("!QQ", *pair) for pair in (
                             (100, 99), (200, 1), (400, 1))))
        self.assertIn("NOT-independent-attestation", result["read_latency_source"])

    def test_exact_sidecar_is_readable_by_existing_v3_verifier(self):
        result = collector.collect(self.json, self.log, self.sidecar)
        row = {
            "read_latency_sidecar": result["read_latency_sidecar"],
            "read_latency_sha256": result["read_latency_sha256"],
            "read_count": result["read_count"],
            "read_p99_ns": result["read_p99_ns"],
        }
        directory_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            used = plateau._verify_v3_sidecar(row, 1, directory_fd, 4096, set())
        finally:
            os.close(directory_fd)
        self.assertEqual(used, result["read_latency_bytes"])

    def test_v3_verifier_rejects_mutated_sidecar(self):
        result = collector.collect(self.json, self.log, self.sidecar)
        self.sidecar.write_bytes(self.sidecar.read_bytes() + b"corruption")
        row = {
            "read_latency_sidecar": result["read_latency_sidecar"],
            "read_latency_sha256": result["read_latency_sha256"],
            "read_count": result["read_count"],
            "read_p99_ns": result["read_p99_ns"],
        }
        directory_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with self.assertRaisesRegex(ValueError, "length or byte budget"):
                plateau._verify_v3_sidecar(row, 1, directory_fd, 4096, set())
        finally:
            os.close(directory_fd)

    def test_mismatched_counts_fail_without_sidecar(self):
        self.make_fio(6)
        with self.assertRaisesRegex(ValueError, "sample count differs"):
            collector.collect(self.json, self.log, self.sidecar)
        self.assertFalse(self.sidecar.exists())

    def test_extra_samples_rejected(self):
        self.make_fio(4)
        with self.assertRaisesRegex(ValueError, "more samples"):
            collector.collect(self.json, self.log, self.sidecar)

    def test_non_read_direction_rejected(self):
        self.log.write_text("0, 100, 1, 4096\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not a monotonic positive 4 KiB read"):
            collector.collect(self.json, self.log, self.sidecar)

    def test_incorrect_block_size_rejected(self):
        self.log.write_text("0, 100, 0, 8192\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "4 KiB read"):
            collector.collect(self.json, self.log, self.sidecar)

    def test_zero_latency_rejected(self):
        self.make_log([1, 2, 0, 4, 5])
        with self.assertRaisesRegex(ValueError, "positive"):
            collector.collect(self.json, self.log, self.sidecar)

    def test_aggregated_latency_rejected(self):
        self.log.write_text("0, 100, 0, 4096, avg\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "malformed or aggregated"):
            collector.collect(self.json, self.log, self.sidecar)

    def test_excessive_fio_log_line_is_bounded(self):
        self.log.write_text("9" * 1024 + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "line exceeds bounded length"):
            collector.collect(self.json, self.log, self.sidecar)
        self.assertFalse(self.sidecar.exists())

    def test_timestamp_reversal_rejected(self):
        self.log.write_text("1, 100, 0, 4096\n0, 200, 0, 4096\n",
                            encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "monotonic"):
            collector.collect(self.json, self.log, self.sidecar)

    def test_duplicate_reader_jobs_rejected(self):
        self.json.write_text(json.dumps({"jobs": [
            {"jobname": "reader", "read": {"total_ios": 5}},
            {"jobname": "reader", "read": {"total_ios": 5}},
        ]}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "exactly one reader"):
            collector.collect(self.json, self.log, self.sidecar)

    def test_boolean_read_count_rejected(self):
        self.make_fio(True)
        with self.assertRaisesRegex(ValueError, "total_ios"):
            collector.collect(self.json, self.log, self.sidecar)

    def test_existing_sidecar_not_overwritten(self):
        self.sidecar.write_bytes(b"important")
        with self.assertRaises(FileExistsError):
            collector.collect(self.json, self.log, self.sidecar)
        self.assertEqual(self.sidecar.read_bytes(), b"important")

    def test_symlink_input_rejected(self):
        alias = self.root / "reader_alias.log"
        alias.symlink_to(self.log)
        with self.assertRaises(OSError):
            collector.collect(self.json, alias, self.sidecar)

    def test_hardlink_input_rejected(self):
        alias = self.root / "reader_hardlink.log"
        alias.hardlink_to(self.log)
        with self.assertRaisesRegex(ValueError, "singly-linked"):
            collector.collect(self.json, alias, self.sidecar)

    def test_invalid_sidecar_basename_rejected(self):
        with self.assertRaisesRegex(ValueError, "safe .latbin"):
            collector.collect(self.json, self.log, self.root / "bad.json")

    def test_live_runner_wires_exact_reader_log_without_evidence_promotion(self):
        runner = HERE / "streaming-benchmark.sh"
        source = runner.read_text(encoding="utf-8")
        self.assertIn("write_lat_log=$read_log_prefix", source)
        self.assertIn("log_avg_msec=0", source)
        self.assertIn("per_job_logs=0", source)
        self.assertIn("streaming-benchmark-read-latency.py", source)
        self.assertIn("NO QUALIFIED WINNER", source)
        self.assertIn("NBD backend disabled", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
