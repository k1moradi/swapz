#!/usr/bin/env python3
"""Adversarial physical-campaign audit fixtures: rootless and synthetic only."""
from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def import_helper(filename):
    spec = importlib.util.spec_from_file_location(
        filename.replace("-", "_").replace(".", "_"), HERE / filename)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper


EVIDENCE = import_helper("physical-campaign-evidence.py")
QUALIFICATION = import_helper("qualification.py")
BOOT = "11111111-2222-3333-4444-555555555555"
SOURCE = "a" * 40


def arm(candidate, timestamp, run_id):
    return {
        "candidate": candidate, "source_sha": SOURCE,
        "workload_id": run_id, "arm_boot_id": BOOT,
        "arm_started_monotonic_ns": timestamp,
        "arm_finished_monotonic_ns": timestamp + 100,
        "read_ops": 1, "write_ops": 1,
        "throughput": {"logical_write_mbps": 1.0},
        "lower_io": {"lower_write_bytes": 4096,
                     "lower_write_requests": 1},
        "cpu": {"measured_cpu_seconds_per_useful_byte": 1e-9},
        "latency": {"read_p95_ns": 100, "read_p99_ns": 200,
                    "write_p95_ns": 100, "write_p99_ns": 200},
        "measurement_snapshots": {
            "lower_before": [0] * 17, "lower_after": [1] * 17},
    }


def pair(index, timestamp, run_id=None):
    workload = "sd-service-balanced"
    identifier = run_id or f"physical-run-{index}"
    return {
        "schema": QUALIFICATION.PAIR_SCHEMA, "workload": workload,
        "pair_id": f"pair-{index}", "pair_index": index,
        "order": QUALIFICATION.CONTRACT["workloads"][workload][
            "counterbalanced_order"][index - 1],
        "source_sha": SOURCE, "status": "PASS",
        "excluded": False, "analysis_usable": True,
        "raw": arm("raw", timestamp, identifier),
        "swapz": arm("swapz", timestamp + 200, identifier),
    }


def host_snapshots():
    return (
        {"source_sha": SOURCE, "captured_monotonic_ns": 500,
         "kernel": {"boot_id": BOOT}},
        {"source_sha": SOURCE, "captured_monotonic_ns": 10000,
         "kernel": {"boot_id": BOOT}},
    )


def inspect(rows, before=None, after=None, decisions=None):
    baseline, finished = host_snapshots()
    result = EVIDENCE.audit_physical_pairs(
        {"status": "PASS", "records": rows,
         "decisions": decisions or {}, "raw_repeat_spread": {}},
        baseline if before is None else before,
        finished if after is None else after)
    return result, {d["metric"] for d in result["diagnostics"]}


class AdversarialPhysicalCampaign(unittest.TestCase):
    def test_positive_timing_does_not_replace_real_physical_evidence(self):
        rows = [pair(index, 1100 + 500 * index) for index in range(1, 6)]
        self.assertEqual(inspect(rows)[0]["status"], "PASS")
        self.assertNotEqual(
            QUALIFICATION.evaluate(rows, protocol="v2")["status"], "PASS")

    def test_duplicate_pair_and_run_identifiers(self):
        records = [pair(1, 1100, "duplicate"),
                   pair(2, 1600, "duplicate")]
        self.assertIn("arm.workload_id", inspect(records)[1])
        records[1]["pair_id"] = records[0]["pair_id"]
        self.assertIn("pair.pair_id", inspect(records)[1])

    def test_mixed_boot_and_changed_source(self):
        records = [pair(1, 1100)]
        records[0]["swapz"]["arm_boot_id"] = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        self.assertIn("arm.arm_boot_id", inspect(records)[1])
        records[0]["swapz"]["arm_boot_id"] = BOOT
        records[0]["swapz"]["source_sha"] = "b" * 40
        self.assertIn("arm.source_sha", inspect(records)[1])

    def test_cached_records_and_reversed_chronology(self):
        records = [pair(1, 1100), pair(2, 1100)]
        metrics = inspect(records)[1]
        self.assertIn("arm.monotonic_window_ns", metrics)
        self.assertIn("pair.prospective_chronology_ns", metrics)
        before, after = host_snapshots()
        before["captured_monotonic_ns"] = 1200
        self.assertIn("arm.monotonic_window_ns",
                      inspect([pair(1, 1100)], before, after)[1])
        del before["captured_monotonic_ns"]
        self.assertIn("host.captured_monotonic_ns",
                      inspect([pair(1, 1100)], before, after)[1])

    def test_changed_parent_and_reverse_host_counters(self):
        before, after = host_snapshots()
        before["kernel"]["uptime_seconds"] = 100.0
        after["kernel"]["uptime_seconds"] = 110.0
        before["device"] = {"parent_major_minor": "8:0"}
        after["device"] = {"parent_major_minor": "8:16"}
        self.assertIn("device_parent_major_minor",
                      EVIDENCE.host_stability(before, after)["failed_checks"])
        after["captured_monotonic_ns"] = 1
        self.assertIn("capture_monotonic_increasing",
                      EVIDENCE.host_stability(before, after)["failed_checks"])

    def test_reversed_diskstats_and_overflow(self):
        record = arm("raw", 1100, "counters")
        starts, ends = [20] * 17, [21] * 17
        record["measurement_snapshots"] = {
            "lower_before": starts, "lower_after": ends}
        ends[1] = 19  # Linux diskstats merged-READ count (cumulative).
        reasons = QUALIFICATION.measurement_snapshot_reasons(
            record, "sd-service-balanced", "raw")
        self.assertTrue(any("counters reset" in r for r in reasons))
        ends[1] = 21
        ends[6] = (1 << 64) + 1
        reasons = QUALIFICATION.measurement_snapshot_reasons(
            record, "sd-service-balanced", "raw")
        self.assertTrue(any("counter snapshots are malformed" in r
                            for r in reasons))
        ends[6] = (1 << 64) - 1
        reasons = QUALIFICATION.measurement_snapshot_reasons(
            record, "sd-service-balanced", "raw")
        self.assertTrue(any("sector-to-byte counter overflow" in r
                            for r in reasons))

    def test_missing_tail_mismatched_fixture_and_fabrication(self):
        record = pair(1, 1100)
        del record["raw"]["latency"]["read_p95_ns"]
        self.assertIn("latency.read_p95_ns", inspect([record])[1])
        record["raw"]["fill_fixture_sha256"] = "a" * 64
        record["swapz"]["fill_fixture_sha256"] = "b" * 64
        paired = QUALIFICATION.compare_pair(
            record["raw"], record["swapz"], "sd-service-balanced",
            "pair-1", 1, "raw-first")
        self.assertTrue(any("pair provenance mismatch" in r
                            for r in paired["exclusion_reasons"]))
        forged = copy.deepcopy(record)
        forged["exclusion_reasons"] = []
        forged["deltas"] = {"useful_write": 100.0}
        evaluated = QUALIFICATION.evaluate([forged], protocol="v2")
        self.assertNotEqual(evaluated["status"], "PASS")
        self.assertFalse(evaluated["records"][0]["analysis_usable"])

    def test_failed_attempts_and_95_percent_bound(self):
        records = [pair(i, 1100 + 500 * i) for i in range(1, 6)]
        records[1]["status"] = "EXCLUDED"
        records[1]["excluded"] = True
        records[1]["analysis_usable"] = False
        self.assertIn("qualification.accepted_pairs",
                      inspect(records, decisions={
                          "sd-service-balanced": {"status": "INCOMPLETE"}})[1])
        keys = ("useful_write", "lower_write_bytes",
                "lower_write_requests", "read_p95", "read_p99",
                "write_p95", "write_p99", "cpu")
        samples = [{"deltas": {name: 0.0 for name in keys}}
                   for _ in range(5)]
        decision = QUALIFICATION.service_decision(
            samples, "sd-service-balanced")
        self.assertEqual(decision["status"], "FAIL")
        audited, metrics = inspect(records, decisions={
            "sd-service-balanced": decision})
        self.assertIn("useful_write.paired_95pct_ci_lower", metrics)
        observed = next(
            item for item in audited["diagnostics"]
            if item["metric"] == "useful_write.paired_95pct_ci_lower")
        self.assertEqual(observed["expected"]["value"],
                         QUALIFICATION.CONTRACT["acceptance"]["service"][
                             "useful_write_ci_lower_min"])

    def test_no_read_only_promotion_or_private_diagnostic(self):
        self.assertNotEqual(
            EVIDENCE.campaign_status("READY_READ_ONLY", True, True, "STABLE"),
            "PASS")
        self.assertEqual(
            EVIDENCE.campaign_status("PASS", True, True, "STABLE",
                                     physical_audit_ok=False),
            "BLOCKED_PHYSICAL_EVIDENCE")
        records = [pair(1, 1100)]
        records[0]["raw"]["arm_boot_id"] = None
        records[0]["raw"]["fill_fixture_sha256"] = "d" * 64
        audit, metrics = inspect(records)
        self.assertNotEqual(audit["status"], "PASS")
        self.assertIn("arm.arm_boot_id", metrics)
        self.assertNotIn("d" * 64, str(audit["diagnostics"]))
        self.assertLessEqual(
            len(audit["diagnostics"]), EVIDENCE.MAX_EVIDENCE_DIAGNOSTICS)
        self.assertIn("not direct NAND-wear", audit["claim_boundary"])


if __name__ == "__main__":
    unittest.main()
