#!/usr/bin/env python3
"""Synthetic-only regression cases for loaded-host RAM evidence validation.

A passing unit test is never a loaded-host or physical qualification.
"""
from __future__ import annotations

import copy
import datetime
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metadata_ram_evidence as ram

SOURCE_SHA = "a" * 40
MAPPER_UUID = "SWAPZ-synthetic-only"
BOOT_ID = "12345678-1234-1234-1234-123456789abc"
HOST_TOTAL_BYTES = 8 * 1024 * 1024 * 1024
START_UTC = datetime.datetime(2026, 11, 1, tzinfo=datetime.timezone.utc)


def synthetic_trace() -> tuple[dict, dict]:
    """Build chronologically complete, nonphysical sample-shaped objects."""
    samples = []
    phase_counts = (("baseline", 11), ("initialization", 2),
                    ("steady", 2), ("gc", 2), ("teardown", 22))
    for phase, count in phase_counts:
        for phase_index in range(count):
            mapper_present = (
                phase in ("steady", "gc") or
                (phase == "initialization" and phase_index == 1) or
                (phase == "teardown" and phase_index == 0))
            mem_available_kib = (
                4_000_000 if phase == "baseline" or
                (phase == "teardown" and not mapper_present)
                else 3_800_000)
            index = len(samples)
            timestamp = START_UTC + datetime.timedelta(
                seconds=1, milliseconds=100 * index)
            samples.append({
                "phase": phase,
                "monotonic_ns": 1_000_000_000 + index * 100_000_000,
                "timestamp_utc": timestamp.isoformat(
                    timespec="microseconds").replace("+00:00", "Z"),
                "mem_available_kib": mem_available_kib,
                "s_unreclaim_kib": 100,
                "vmalloc_used_kib": 100,
                "mapper_present": mapper_present,
            })
    trace = {
        "schema": "swapz-metadata-ram-samples-v1",
        "capture": "serialized-loaded-host",
        "scope": "whole-host-conservative-metadata-and-target-ram",
        "source_sha": SOURCE_SHA,
        "mapper_uuid": MAPPER_UUID,
        "host_boot_id": BOOT_ID,
        "sampling_interval_ns": 100_000_000,
        "meminfo_unit": "kB",
        "samples": samples,
    }
    host_binding = {
        "host_boot_id": BOOT_ID,
        "host_before_captured_at_utc": "2026-11-01T00:00:00Z",
        "host_after_captured_at_utc": "2026-11-01T00:00:06Z",
        "memory_total_bytes": HOST_TOTAL_BYTES,
    }
    return trace, host_binding


class SyntheticRamEvidenceTest(unittest.TestCase):
    def validate_trace(self, trace: dict, *, expected_peak_ram_bytes=None) -> dict:
        return ram.validate_metadata_ram_trace(
            trace, source_sha=SOURCE_SHA, mapper_uuid=MAPPER_UUID,
            expected_peak_ram_bytes=expected_peak_ram_bytes)

    def test_consistent_synthetic_control_is_not_host_qualification(self) -> None:
        trace, host = synthetic_trace()
        derived = self.validate_trace(trace)
        self.assertEqual(derived["peak_ram_bytes"], 200_000 * 1024)
        self.assertEqual(derived["steady_peak_ram_bytes"], derived["peak_ram_bytes"])
        ram.validate_metadata_ram_host_binding(trace, host)

    def test_physically_impossible_unreclaim_was_false_acceptance(self) -> None:
        trace, host = synthetic_trace()
        index = 13  # First synthetic steady-state sample.
        trace["samples"][index]["s_unreclaim_kib"] = (
            HOST_TOTAL_BYTES // 1024 + 1)
        # This independently well-formed trace used to pass both validators.
        self.assertEqual(self.validate_trace(trace)["peak_ram_bytes"],
                         200_000 * 1024)
        with self.assertRaisesRegex(
                ValueError,
                r"metric=samples\[13\]\.s_unreclaim_kib.*"
                r"observed=8388609.*maximum=8388608"):
            ram.validate_metadata_ram_host_binding(trace, host)

    def test_host_meminfo_estimates_are_not_additive(self) -> None:
        trace, host = synthetic_trace()
        sample = trace["samples"][13]  # Active synthetic steady-state target.
        sample["mem_available_kib"] = 7_000_000
        sample["s_unreclaim_kib"] = 2_000_000
        # Both counters remain individually within the 8 GiB host. Linux
        # MemAvailable is a derived estimate, not an additive partition of
        # MemTotal, so their sum alone must not make valid evidence unusable.
        self.assertEqual(self.validate_trace(trace)["peak_ram_bytes"],
                         200_000 * 1024)
        ram.validate_metadata_ram_host_binding(trace, host)

    def test_rejects_wrong_unit_and_duplicate_meminfo(self) -> None:
        trace, _ = synthetic_trace()
        trace["meminfo_unit"] = "bytes"
        with self.assertRaisesRegex(ValueError, "metric=meminfo_unit"):
            self.validate_trace(trace)
        counters = (
            "MemAvailable: 2000 kB\nSUnreclaim: 100 kB\n"
            "VmallocUsed: 100 kB\n  SUnreclaim: 200 kB\n")
        with self.assertRaisesRegex(ValueError, "SUnreclaim"):
            ram.parse_meminfo_counters(counters)

    def test_mapper_mismatch_diagnostic_names_field(self) -> None:
        trace, _ = synthetic_trace()
        trace["mapper_uuid"] = "SWAPZ-foreign-mapper"
        with self.assertRaisesRegex(ValueError, "metric=mapper_uuid"):
            self.validate_trace(trace)

    def test_steady_and_gc_samples_may_interleave(self) -> None:
        trace, _ = synthetic_trace()
        trace["samples"][14]["phase"] = "gc"
        trace["samples"][15]["phase"] = "steady"
        derived = self.validate_trace(trace)
        self.assertEqual(derived["steady_samples"], 2)
        self.assertEqual(derived["gc_samples"], 2)
        ram.validate_metadata_ram_arm_binding(trace, {
            "arm_started_monotonic_ns": 2_200_000_000,
            "arm_finished_monotonic_ns": 2_700_000_000,
            "gc_activity_intervals": [
                {
                    "start_monotonic_ns": 2_350_000_000,
                    "end_monotonic_ns": 2_450_000_000,
                    "gc_wall_ns": 1,
                    "gc_victims": 1,
                    "gc_pages": 1,
                },
                {
                    "start_monotonic_ns": 2_550_000_000,
                    "end_monotonic_ns": 2_650_000_000,
                    "gc_wall_ns": 1,
                    "gc_victims": 1,
                    "gc_pages": 1,
                },
            ],
        })

    def test_host_memory_total_rejects_sub_kib_false_precision(self) -> None:
        trace, host = synthetic_trace()
        host["memory_total_bytes"] += 1
        with self.assertRaisesRegex(
                ValueError,
                r"metric=memory_total_bytes.*observed=8589934593.*multiple=1024"):
            ram.validate_metadata_ram_host_binding(trace, host)

    def test_rejects_reported_peak_contradiction(self) -> None:
        trace, _ = synthetic_trace()
        peak = self.validate_trace(trace)["steady_peak_ram_bytes"]
        with self.assertRaisesRegex(ValueError, "metric=peak_ram_bytes"):
            self.validate_trace(trace, expected_peak_ram_bytes=peak - 1024)

    def test_rejects_missing_duplicate_and_gapped_samples(self) -> None:
        trace, _ = synthetic_trace()
        for mutation in ("missing", "duplicate", "gap"):
            changed = copy.deepcopy(trace)
            if mutation == "missing":
                del changed["samples"][0]["s_unreclaim_kib"]
            elif mutation == "duplicate":
                changed["samples"][12]["monotonic_ns"] = (
                    changed["samples"][11]["monotonic_ns"])
            else:
                changed["samples"][12]["monotonic_ns"] += 200_000_000
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):
                    self.validate_trace(changed)

    def test_boot_mismatch_and_secret_string_redaction(self) -> None:
        trace, host = synthetic_trace()
        host["host_boot_id"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        with self.assertRaisesRegex(ValueError, "metric=host_boot_id"):
            ram.validate_metadata_ram_host_binding(trace, host)
        trace["samples"][0]["timestamp_utc"] = "PRIVATE-TRACE-PAYLOAD"
        with self.assertRaises(ValueError) as caught:
            self.validate_trace(trace)
        self.assertNotIn("PRIVATE-TRACE-PAYLOAD", str(caught.exception))
        self.assertIn("metric=timestamp_utc", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
