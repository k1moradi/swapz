#!/usr/bin/env python3
"""Synthetic-only regression cases for loaded-host RAM evidence validation.

A passing unit test is never a loaded-host or physical qualification.
"""
from __future__ import annotations

import copy
import datetime
import json
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

    def test_frozen_full_card_geometry_is_not_a_ram_measurement(self) -> None:
        partition_bytes = 124_787_884_032
        self.assertEqual(
            ram.maximum_logical_pages_for_partition(partition_bytes),
            27_080_192)
        self.assertEqual(
            ram.capacity_index_estimate(27_080_192, 30_465_536),
            {"array_count": 17, "payload_bytes": 776_070_968,
             "page_rounded_bytes": 776_114_176})
        policy_path = Path(__file__).resolve().parents[3] / (
            "docs/production-acceptance.json")
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        self.assertEqual(
            policy["physical_qualification"]["acceptance"]["sustained"][
                "metadata_and_target_peak_ram_bytes_max"],
            1_342_177_280)

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

    def test_malformed_required_meminfo_duplicate_was_false_acceptance(self) -> None:
        # Previously the malformed duplicate was ignored and 2000 kB won.
        valid = (
            "MemAvailable: 2000 kB\nSUnreclaim: 100 kB\n"
            "VmallocUsed: 100 kB\n")
        self.assertEqual(
            ram.parse_meminfo_counters(valid + "MemAvailableExtra: 1 kB\n")[
                "mem_available_kib"], 2000)
        for malformed in ("MemAvailable : 1 kB", "  MemAvailable\t: 1 kB",
                          "MemAvailable"):
            with self.subTest(malformed=malformed):
                with self.assertRaisesRegex(
                        ValueError, "malformed meminfo counter: MemAvailable"):
                    ram.parse_meminfo_counters(valid + malformed + "\n")

    def test_rejects_explicit_synthetic_capture_scope(self) -> None:
        for field, invalid in (
                ("capture", "rootless-synthetic"),
                ("scope", "synthetic-only")):
            with self.subTest(field=field):
                trace, _ = synthetic_trace()
                trace[field] = invalid
                with self.assertRaisesRegex(
                        ValueError,
                        f"metric={field}.*first_failed_phase=provenance"):
                    self.validate_trace(trace)

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

    def test_missing_peak_sample_cannot_claim_lower_peak(self) -> None:
        trace, host = synthetic_trace()
        # Preserve valid phase counts after dropping one high-water sample.
        samples = trace["samples"]
        samples.insert(14, copy.deepcopy(samples[14]))
        for sample_index, sample in enumerate(samples):
            sample["monotonic_ns"] = (
                1_000_000_000 + sample_index * ram.SAMPLING_INTERVAL_NS)
            timestamp = START_UTC + datetime.timedelta(
                seconds=1, milliseconds=100 * sample_index)
            sample["timestamp_utc"] = timestamp.isoformat(
                timespec="microseconds").replace("+00:00", "Z")
        samples[14]["mem_available_kib"] = 3_200_000
        self.assertEqual(
            self.validate_trace(trace)["peak_ram_bytes"], 800_000 * 1024)
        ram.validate_metadata_ram_host_binding(trace, host)

        del samples[14]
        self.assertEqual(sum(sample["phase"] == "steady" for sample in samples), 2)
        with self.assertRaisesRegex(
                ValueError,
                r"metric=monotonic_interval_ns.*"
                r"first_failed_phase=steady missing_samples_minimum=1"):
            self.validate_trace(trace)

    def test_cadence_gap_reports_only_provable_missing_minimum(self) -> None:
        trace, _ = synthetic_trace()
        # The previous diagnostic claimed two missing samples here. Under the
        # unchanged 50-150 ms policy, two 150 ms intervals prove only that at
        # least one observation is absent.
        trace["samples"][14]["monotonic_ns"] += 200_000_000
        with self.assertRaisesRegex(
                ValueError,
                r"observed=300000000.*maximum=150000000.*"
                r"first_failed_phase=steady missing_samples_minimum=1"):
            self.validate_trace(trace)

    def test_cadence_gap_at_phase_boundary_names_earliest_affected_phase(self) -> None:
        trace, _ = synthetic_trace()
        # Hide the last baseline sample behind a surplus 50 ms observation
        # so all phase counts still meet their minimums. The remaining
        # 200 ms gap crosses the baseline/initialization boundary.
        del trace["samples"][10]
        extra = copy.deepcopy(trace["samples"][1])
        extra["monotonic_ns"] += 50_000_000
        timestamp = START_UTC + datetime.timedelta(
            seconds=1, milliseconds=150)
        extra["timestamp_utc"] = timestamp.isoformat(
            timespec="microseconds").replace("+00:00", "Z")
        trace["samples"].insert(2, extra)
        self.assertEqual(len(trace["samples"]), 39)
        self.assertEqual(
            sum(sample["phase"] == "baseline" for sample in trace["samples"]),
            11)
        with self.assertRaisesRegex(
                ValueError,
                r"metric=monotonic_interval_ns observed=200000000.*"
                r"first_failed_phase=baseline missing_samples_minimum=1.*"
                r"next_observed_phase=initialization "
                r"peak_ram_bytes=unavailable"):
            self.validate_trace(trace)

    def test_invalid_trace_never_advertises_a_peak(self) -> None:
        original, _ = synthetic_trace()
        for defect, first_failure in (
                ("missing_counter", "metric=samples[0].fields missing=s_unreclaim_kib"),
                ("short_teardown", "metric=sample_count"),
                ("source_mismatch", "metric=source_sha"),
                ("unrecovered", "metric=MemAvailable_median_twice_kib"),
                ("boundary_gap", "metric=monotonic_interval_ns")):
            trace = copy.deepcopy(original)
            if defect == "missing_counter":
                del trace["samples"][0]["s_unreclaim_kib"]
            elif defect == "short_teardown":
                del trace["samples"][-1]
            elif defect == "source_mismatch":
                trace["source_sha"] = "b" * 40
            elif defect == "unrecovered":
                for sample in trace["samples"][-21:]:
                    sample["mem_available_kib"] = 3_900_000
            else:
                trace["samples"][14]["monotonic_ns"] += 200_000_000
            with self.subTest(defect=defect):
                with self.assertRaises(ValueError) as caught:
                    self.validate_trace(trace)
                diagnostic = str(caught.exception)
                self.assertIn(first_failure, diagnostic)
                self.assertEqual(
                    diagnostic.count("peak_ram_bytes=unavailable"), 1)

    def test_short_baseline_does_not_qualify_a_peak(self) -> None:
        trace, _ = synthetic_trace()
        # Keep all individual intervals legal and the whole-trace average
        # within 10%, while making the eleven baseline samples span 900 ms.
        for sample_index, sample in enumerate(trace["samples"]):
            adjusted_offset_ns = (
                sample_index * ram.SAMPLING_INTERVAL_NS -
                min(sample_index, 10) * 10_000_000)
            sample["monotonic_ns"] = 1_000_000_000 + adjusted_offset_ns
            timestamp = START_UTC + datetime.timedelta(
                seconds=1, microseconds=adjusted_offset_ns // 1000)
            sample["timestamp_utc"] = timestamp.isoformat(
                timespec="microseconds").replace("+00:00", "Z")
        with self.assertRaisesRegex(
                ValueError, "metadata RAM baseline is shorter than one second"
                ) as caught:
            self.validate_trace(trace)
        self.assertEqual(
            str(caught.exception).count("peak_ram_bytes=unavailable"), 1)

    def test_invalid_host_and_arm_bindings_revoke_peak(self) -> None:
        with self.assertRaisesRegex(
                ValueError, "arm chronology is missing") as caught:
            ram.metadata_ram_arm_binding({})
        self.assertEqual(
            str(caught.exception).count("peak_ram_bytes=unavailable"), 1)

        trace, host = synthetic_trace()
        host["host_boot_id"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        with self.assertRaisesRegex(ValueError, "metric=host_boot_id"
                                    ) as caught:
            ram.validate_metadata_ram_host_binding(trace, host)
        self.assertEqual(
            str(caught.exception).count("peak_ram_bytes=unavailable"), 1)

        arm_binding = {
            "arm_started_monotonic_ns": 2_350_000_000,
            "arm_finished_monotonic_ns": 2_700_000_000,
            "gc_activity_intervals": [{
                "start_monotonic_ns": 2_450_000_000,
                "end_monotonic_ns": 2_650_000_000,
                "gc_wall_ns": 1, "gc_victims": 1, "gc_pages": 1,
            }],
        }
        with self.assertRaisesRegex(ValueError, "phases do not bind"
                                    ) as caught:
            ram.validate_metadata_ram_arm_binding(trace, arm_binding)
        self.assertEqual(
            str(caught.exception).count("peak_ram_bytes=unavailable"), 1)

    def test_truncated_phase_and_host_window_fail_closed(self) -> None:
        trace, host = synthetic_trace()
        del trace["samples"][-1]
        with self.assertRaisesRegex(
                ValueError,
                r"metric=sample_count.*missing_samples_minimum=1.*"
                r"first_failed_phase=teardown"):
            self.validate_trace(trace)
        trace, host = synthetic_trace()
        host["host_after_captured_at_utc"] = "2026-11-01T00:00:04Z"
        with self.assertRaisesRegex(ValueError, "outside host snapshot window"):
            ram.validate_metadata_ram_host_binding(trace, host)

    def test_sustained_arm_and_utc_clock_binding_fail_closed(self) -> None:
        trace, _ = synthetic_trace()
        with self.assertRaisesRegex(ValueError, "phases do not bind"):
            ram.validate_metadata_ram_arm_binding(trace, {
                "arm_started_monotonic_ns": 2_350_000_000,
                "arm_finished_monotonic_ns": 2_700_000_000,
                "gc_activity_intervals": [{
                    "start_monotonic_ns": 2_450_000_000,
                    "end_monotonic_ns": 2_650_000_000,
                    "gc_wall_ns": 1, "gc_victims": 1, "gc_pages": 1,
                }],
            })
        trace, _ = synthetic_trace()
        trace["samples"][13]["timestamp_utc"] = (
            trace["samples"][12]["timestamp_utc"])
        with self.assertRaisesRegex(ValueError, "clocks disagree"):
            self.validate_trace(trace)

    def test_backward_utc_sample_is_order_failure_with_unavailable_peak(self) -> None:
        trace, _ = synthetic_trace()
        # A reversed wall-clock sample is not a missing cadence observation.
        trace["samples"][13]["timestamp_utc"] = (
            trace["samples"][11]["timestamp_utc"])
        with self.assertRaisesRegex(
                ValueError,
                r"metric=utc_sample_order.*"
                r"observed_utc_interval_ns=-100000000.*"
                r"monotonic_interval_ns=100000000.*"
                r"first_failed_phase=steady peak_ram_bytes=unavailable") as caught:
            self.validate_trace(trace)
        self.assertNotIn("missing_samples_minimum=", str(caught.exception))

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
