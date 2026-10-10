#!/usr/bin/env python3
"""Rootless V3 exact latency sidecar boundary and selection regression.

All samples and lower-device counters are fabricated. No kernel/devices,
workers, network connections, elevated privileges, or cleanup operations.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
import tracemalloc
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "swapz_v22_sidecar_analyzer", HERE / "v22-drain-plateau-analyze.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load offline analyzer")
analyzer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = analyzer
SPEC.loader.exec_module(analyzer)
PACK = struct.Struct("!QQ")


def observation(*, batch=64, repetition=0, evidence="synthetic",
                schema=analyzer.SCHEMA_V3, strategy="staged"):
    return {
        "schema": schema,
        "evidence": evidence, "backend": "synthetic-private",
        "profile": "rootless", "strategy": strategy,
        "batch_kib": batch, "run_id": f"run-{batch}-{repetition}-{schema[-2:]}",
        "source_revision": "a" * 40, "clock": "monotonic",
        "duration_ns": 1_000_000_000,
        "lower_write_sectors_before": 1024,
        "lower_write_sectors_after": 1024 + 40960,
        "lower_write_ios_before": 100, "lower_write_ios_after": 160,
        "logical_write_bytes": 64 * 1024 * 1024,
        "read_count": 10000, "read_p99_ns": 1_000_000,
        "integrity_ok": True, "quiescence_ok": True,
        "flush_ok": True, "all_reaped": True,
        "source_kind": "lower-device-counters",
    }


class ExactV3SidecarTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="swapz-v3-sidecar-")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.input = self.folder / "observations.jsonl"
        self.row = observation()
        self.sidecar = self.folder / "latency-0.latbin"
        self._set_records(self.row, [(1_000_000, 10000)])

    def _set_records(self, row, records, *, name=None, endian="!"):
        # The test fixture builds a finite synthetic distribution before
        # serializing it; the production verifier itself remains streaming.
        records = tuple(records)
        path = self.folder / (name or f"{row['run_id']}.latbin")
        with path.open("wb") as stream:
            for latency, count in records:
                stream.write(struct.pack(endian + "QQ", latency, count))
        row["schema"] = analyzer.SCHEMA_V3
        row["read_latency_sidecar"] = path.name
        row["read_latency_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        row["read_count"] = sum(count for _latency, count in records)
        rank = (99 * row["read_count"] + 99) // 100
        running = 0
        for latency, count in records:
            running += count
            if running >= rank:
                row["read_p99_ns"] = latency
                break
        return path

    def _write_rows(self, rows):
        self.input.write_text("".join(json.dumps(row, sort_keys=True) + "\n"
                                      for row in rows), encoding="utf-8")
        return self.input

    def _load(self, rows=None):
        return analyzer.load_rows(self._write_rows([self.row] if rows is None else rows))

    def _reject(self, pattern):
        with self.assertRaisesRegex(ValueError, pattern):
            self._load()

    def test_one_valid_v3_sidecar(self):
        rows = self._load()
        self.assertEqual(rows[0]["read_count"], 10000)
        self.assertEqual(rows[0]["read_p99_ns"], 1_000_000)

    def test_10000_distinct_nanosecond_samples_exact_p99(self):
        self._set_records(self.row, ((x, 1) for x in range(1, 10001)))
        self.assertEqual(self._load()[0]["read_p99_ns"], 9900)

    def test_10001_distinct_samples_ceiling_rank(self):
        self._set_records(self.row, ((x, 1) for x in range(1, 10002)))
        self.assertEqual(self._load()[0]["read_p99_ns"], 9901)

    def test_100000_distinct_sample_streaming_and_memory(self):
        self._set_records(self.row, ((x, 1) for x in range(1, 100001)))
        tracemalloc.start()
        start = time.perf_counter()
        try:
            self.assertEqual(self._load()[0]["read_p99_ns"], 99000)
            elapsed = time.perf_counter() - start
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak_bytes, 8 * 1024 * 1024,
                        "V3 verifier should not materialize 100000 sample records")
        print(f"V3_STREAM_BENCH 100000_unique records=1600000 "
              f"seconds={elapsed:.4f} python_peak_bytes={peak_bytes}")

    def test_repeated_sample_count_exact_boundary(self):
        self._set_records(self.row, [(100, 9899), (200, 101)])
        self.assertEqual(self._load()[0]["read_p99_ns"], 200)

    def test_9900th_sample_remains_first_latency(self):
        self._set_records(self.row, [(100, 9900), (200, 100)])
        self.assertEqual(self._load()[0]["read_p99_ns"], 100)

    def test_reject_wrong_p99_with_exact_counts(self):
        self.row["read_p99_ns"] += 1
        self._reject("nearest-rank p99 mismatch")

    def test_reject_wrong_declared_read_count(self):
        self.row["read_count"] += 1
        self._reject("exact count")

    def test_reject_wrong_sha256(self):
        self.row["read_latency_sha256"] = "0" * 64
        self._reject("SHA-256 mismatch")

    def test_reject_uppercase_sha256(self):
        self.row["read_latency_sha256"] = "A" * 64
        self._reject("basename or SHA-256")

    def test_reject_16bit_or_32bit_short_record(self):
        path = self.folder / self.row["read_latency_sidecar"]
        path.write_bytes(b"\x00" * 12)
        self._reject("sidecar length")

    def test_reject_empty_sidecar(self):
        (self.folder / self.row["read_latency_sidecar"]).write_bytes(b"")
        self._reject("sidecar length")

    def test_reject_little_endian_records(self):
        self._set_records(self.row, [(100, 10000)], endian="<")
        self._reject("V3 latency unsorted")

    def test_reject_unsorted_latency_records(self):
        self._set_records(self.row, [(200, 5000), (100, 5000)])
        self._reject("V3 latency unsorted")

    def test_reject_duplicate_latency_records(self):
        self._set_records(self.row, [(100, 5000), (100, 5000)])
        self._reject("V3 latency unsorted")

    def test_reject_zero_latency(self):
        self._set_records(self.row, [(0, 10000)])
        self._reject("V3 latency unsorted")

    def test_reject_zero_count(self):
        self._set_records(self.row, [(100, 0), (200, 10000)])
        self._reject("V3 latency unsorted")

    def test_reject_count_larger_than_global_limit(self):
        self._set_records(self.row, [(100, analyzer.MAX_READ_COUNT + 1)])
        self._reject("insufficient p99 samples")

    def test_reject_latency_larger_than_global_limit(self):
        self._set_records(self.row, [(analyzer.MAX_NS + 1, 10000)])
        self._reject("insufficient p99 samples")

    def test_reject_wrong_record_count_too_many_bins(self):
        self._set_records(self.row, [(1, 10000)])
        target = self.folder / self.row["read_latency_sidecar"]
        with target.open("ab") as stream:
            stream.write(PACK.pack(2, 1))
        self._reject("exceeds declared sample count|sidecar length")

    def test_reject_missing_sidecar(self):
        (self.folder / self.row["read_latency_sidecar"]).unlink()
        self._reject("cannot be pinned")

    def test_reject_traversal_sidecar_name(self):
        self.row["read_latency_sidecar"] = "../outside.latbin"
        self._reject("basename or SHA-256")

    def test_reject_absolute_sidecar_name(self):
        self.row["read_latency_sidecar"] = "/tmp/other.latbin"
        self._reject("basename or SHA-256")

    def test_reject_sidecar_without_required_extension(self):
        self.row["read_latency_sidecar"] = "anything.bin"
        self._reject("basename or SHA-256")

    def test_reject_duplicate_sidecar_file_claimed_for_different_run(self):
        second = dict(self.row, run_id="second")
        with self.assertRaisesRegex(ValueError, "sidecar filename reused"):
            self._load([self.row, second])

    def test_reject_symlinked_sidecar(self):
        path = self.folder / self.row["read_latency_sidecar"]
        external = self.folder / "real.latbin"
        path.rename(external)
        path.symlink_to(external)
        self._reject("cannot be pinned")

    def test_reject_hardlinked_sidecar(self):
        target = self.folder / self.row["read_latency_sidecar"]
        os.link(target, self.folder / "hardlink.latbin")
        self._reject("singly-linked regular")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX named pipes")
    def test_reject_fifo_without_blocking(self):
        target = self.folder / self.row["read_latency_sidecar"]
        target.unlink()
        os.mkfifo(target, 0o600)
        self._reject("singly-linked regular")

    def test_reject_sparse_oversized_sidecar_before_scanning(self):
        target = self.folder / self.row["read_latency_sidecar"]
        with target.open("r+b") as handle:
            handle.truncate(self.row["read_count"] * PACK.size + PACK.size)
        self._reject("sidecar length")

    def test_reject_global_sidecar_byte_budget(self):
        previous = analyzer.MAX_TOTAL_SIDECAR_BYTES
        analyzer.MAX_TOTAL_SIDECAR_BYTES = PACK.size - 1
        try:
            self._reject("byte budget")
        finally:
            analyzer.MAX_TOTAL_SIDECAR_BYTES = previous

    def test_reject_changed_same_inode_during_read(self):
        target = self.folder / self.row["read_latency_sidecar"]
        real_read = os.read
        mutated = [False]

        def mutate(fd, size):
            data = real_read(fd, size)
            # The parser opens the JSONL before the sidecar. Inject the
            # mutation only after the exact sidecar FD has been read.
            if data and not mutated[0] and os.fstat(fd).st_size == PACK.size:
                mutated[0] = True
                with target.open("ab") as writer:
                    writer.write(PACK.pack(2_000_000, 1))
            return data

        with mock.patch.object(analyzer.os, "read", side_effect=mutate):
            self._reject("changed during read|incomplete")
        self.assertTrue(mutated[0])

    def test_v1_v2_v3_are_not_grouped_together(self):
        legacy = observation(schema=analyzer.SCHEMA)
        v2 = observation(schema=analyzer.SCHEMA_V2)
        v2["read_latency_counts"] = [[1_000_000, 10000]]
        rows = self._load([legacy, v2, self.row])
        report = analyzer.analyze(rows)
        self.assertEqual(len(report["series"]), 3)
        self.assertEqual({x["schema"] for x in report["series"]},
                         {analyzer.SCHEMA, analyzer.SCHEMA_V2, analyzer.SCHEMA_V3})

    def test_v3_complete_synthetic_sweep_never_claims_winner(self):
        rows = []
        for batch in analyzer.BATCHES:
            for repetition in range(3):
                row = observation(batch=batch, repetition=repetition)
                self._set_records(row, [(1_000_000, 10000)])
                rows.append(row)
        report = analyzer.analyze(self._load(rows))
        group = report["series"][0]
        self.assertEqual(group["schema"], analyzer.SCHEMA_V3)
        self.assertIn("SYNTHETIC ONLY", group["qualification"])
        self.assertEqual(group["candidate_batch_kib"], 4)
        self.assertIsNone(group["provisional_selection_kib"])

    def test_v3_self_labeled_kernel_remains_provisional(self):
        rows = []
        for batch in analyzer.BATCHES:
            for repetition in range(3):
                row = observation(batch=batch, repetition=repetition, evidence="kernel")
                self._set_records(row, [(1_000_000, 10000)])
                rows.append(row)
        group = analyzer.analyze(self._load(rows))["series"][0]
        self.assertIn("INDEPENDENT EVIDENCE REVIEW", group["qualification"])
        self.assertEqual(group["provisional_selection_kib"], 4)

    def test_missing_sidecar_fields_fails_closed(self):
        self.row.pop("read_latency_sidecar")
        self._reject("missing or unexpected")

    def test_disallow_v2_histogram_field_in_v3(self):
        self.row["read_latency_counts"] = [[1000000, 10000]]
        self._reject("missing or unexpected")

    def test_false_positive_raw_sample_truncation_fails(self):
        path = self.folder / self.row["read_latency_sidecar"]
        path.write_bytes(PACK.pack(1_000_000, 9999))
        self._reject("exact count")

    def test_invalid_observation_input_symlink_rejected(self):
        self._write_rows([self.row])
        redirected = self.folder / "redirect.jsonl"
        redirected.symlink_to(self.input)
        with self.assertRaisesRegex(ValueError, "cannot be pinned"):
            analyzer.load_rows(redirected)

    def test_cli_from_subprocess_succeeds_without_device_access(self):
        self._write_rows([self.row])
        result = subprocess.run(
            [sys.executable, "-B", str(HERE / "v22-drain-plateau-analyze.py"),
             "--observations", str(self.input)],
            capture_output=True, text=True, timeout=8, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "OFFLINE ANALYSIS - NO DEVICE ACCESS")
        self.assertEqual(report["series"][0]["read_p99_integrity"],
                         "RECOMPUTED FROM EXACT LATENCY SIDECAR")


if __name__ == "__main__":
    unittest.main(verbosity=2)
