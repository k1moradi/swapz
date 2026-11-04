#!/usr/bin/env python3
"""Adversarial physical-campaign audit fixtures: rootless and synthetic only."""
from __future__ import annotations

import copy
import datetime
import hashlib
import importlib.util
import json
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent


def import_helper(filename):
    spec = importlib.util.spec_from_file_location(
        filename.replace("-", "_").replace(".", "_"), HERE / filename)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper


EVIDENCE = import_helper("physical-campaign-evidence.py")
QUALIFICATION = import_helper("qualification.py")
RAM_FIXTURES = import_helper("metadata-ram-evidence-test.py")
READINESS = runpy.run_path(str(
    HERE.parents[1] / "tools" / "evaluate-production-readiness.py"))
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

    def test_sustained_gc_evidence_is_swapz_only(self):
        record = pair(1, 1100)
        record["workload"] = "sd-high-occupancy-churn"
        record["order"] = "raw-first"
        for label in ("raw", "swapz"):
            record[label]["cold_read"] = {"p99_ns": 200}
            record[label]["minute_buckets"] = []
            record[label]["occupancy_transitions"] = []
        # The raw producer deliberately emits no target-status/GC object.
        record["swapz"]["gc"] = {"wall_fraction": 0.01, "gc_wall_ns": 10}
        audited, _ = inspect([record])
        self.assertEqual(audited["status"], "PASS", audited["diagnostics"])
        self.assertFalse(any(
            item["arm"] == "raw" and item["metric"].startswith("gc.")
            for item in audited["diagnostics"]))

        del record["swapz"]["gc"]
        audited, _ = inspect([record])
        self.assertTrue(any(
            item["arm"] == "swapz" and item["metric"] == "gc.wall_fraction"
            and item["status"] == "UNAVAILABLE"
            for item in audited["diagnostics"]))

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



class CapacityRamPropagation(unittest.TestCase):
    """Synthetic RAM traces exercise the sealer and release consumers, not RAM."""

    LIMIT = QUALIFICATION.CONTRACT["acceptance"]["sustained"][
        "metadata_and_target_peak_ram_bytes_max"]
    DEVICE_BYTES = 8 * 1024 * 1024 * 1024
    PARTUUID = "12345678-aaaa"

    def synthetic_capacity(self, peak_bytes):
        self.assertEqual(self.LIMIT, 1_342_177_280)
        self.assertEqual(peak_bytes % 1024, 0)
        trace, _ = RAM_FIXTURES.synthetic_trace()
        trace["host_boot_id"] = BOOT
        for sample in trace["samples"]:
            if sample["mapper_present"]:
                sample["mem_available_kib"] = 4_000_000 - peak_bytes // 1024

        record = pair(1, 1100)
        record["workload"] = "sd-high-occupancy-churn"
        swapz = record["swapz"]
        swapz["logical_pages"] = EVIDENCE.RAM_VALIDATOR[
            "maximum_logical_pages_for_partition"](self.DEVICE_BYTES)
        swapz["device_identity"] = {"dm_uuid": trace["mapper_uuid"]}
        swapz["resources"] = {"metadata_and_target_peak_ram_bytes": 0}
        swapz["arm_started_monotonic_ns"] = 2_200_000_000
        swapz["arm_finished_monotonic_ns"] = 2_700_000_000
        swapz["sustained_intervals"] = [{
            "start_monotonic_ns": 2_450_000_000,
            "end_monotonic_ns": 2_650_000_000,
            "gc": {"gc_wall_ns": 1, "gc_victims": 1, "gc_pages": 1},
        }]
        return record, trace

    def test_measured_below_at_and_over_frozen_limit(self):
        for offset, expected in ((-1024, "PASS"), (0, "PASS"),
                                 (1024, "FAIL")):
            with self.subTest(offset=offset):
                record, trace = self.synthetic_capacity(self.LIMIT + offset)
                capacity = EVIDENCE.campaign_capacity_and_ram(
                    [record], self.DEVICE_BYTES, SOURCE, trace)
                self.assertIsNotNone(capacity)
                self.assertEqual(capacity["ram_acceptance_status"], expected)
                self.assertEqual(capacity["ram_limit_bytes"], self.LIMIT)
                self.assertEqual(capacity["peak_ram_bytes"],
                                 self.LIMIT + offset)
                self.assertEqual(
                    capacity["logical_pages"],
                    EVIDENCE.RAM_VALIDATOR[
                        "maximum_logical_pages_for_partition"](
                            self.DEVICE_BYTES))
                self.assertEqual(
                    capacity["metadata_ram_summary"]["peak_ram_bytes"],
                    self.LIMIT + offset)

    def test_unverified_or_inconsistent_trace_is_never_measured_pass(self):
        record, trace = self.synthetic_capacity(self.LIMIT + 1024)
        def capacity(row=record, samples=trace, device_bytes=self.DEVICE_BYTES):
            return EVIDENCE.campaign_capacity_and_ram(
                [row], device_bytes, SOURCE, samples)
        self.assertIsNone(capacity(samples=None))
        self.assertIsNone(capacity(device_bytes=True))
        self.assertIsNone(capacity(device_bytes=1 << 80))
        for change in ("nonmaximum", "boolean_pages", "mapper",
                       "source", "boot", "replay_bool", "replay_float",
                       "replay_contradiction", "missing_gc"):
            with self.subTest(change=change):
                changed_record, changed_trace = copy.deepcopy((record, trace))
                swapz = changed_record["swapz"]
                if change == "nonmaximum":
                    swapz["logical_pages"] -= 1
                elif change == "boolean_pages":
                    swapz["logical_pages"] = True
                elif change == "mapper":
                    changed_trace["mapper_uuid"] = "SWAPZ-foreign"
                elif change == "source":
                    changed_trace["source_sha"] = "b" * 40
                elif change == "boot":
                    changed_trace["host_boot_id"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
                elif change == "replay_bool":
                    swapz["resources"]["metadata_and_target_peak_ram_bytes"] = False
                elif change == "replay_float":
                    swapz["resources"]["metadata_and_target_peak_ram_bytes"] = 0.0
                elif change == "replay_contradiction":
                    swapz["resources"]["metadata_and_target_peak_ram_bytes"] = 1
                else:
                    swapz["sustained_intervals"] = []
                if change == "boot":
                    # The arm validator is independent of the host snapshot.
                    before, after = self.synthetic_hosts()
                    checked = capacity(changed_record, changed_trace)
                    self.assertIsNotNone(checked)
                    self.assertFalse(EVIDENCE.metadata_ram_trace_within_host_window(
                        checked, before, after))
                else:
                    self.assertIsNone(capacity(changed_record, changed_trace))

    def synthetic_hosts(self):
        snapshot = {
            "source_sha": SOURCE, "source_tree_sha": "b" * 40,
            "captured_at_utc": "2026-11-01T00:00:00Z",
            "kernel": {"boot_id": BOOT},
            "memory": {"total_bytes": self.DEVICE_BYTES},
            "device": {
                "partuuid": self.PARTUUID,
                "size_bytes": self.DEVICE_BYTES, "major_minor": "8:17",
                "parent_major_minor": "8:16", "model": "synthetic",
                "transport": "usb", "holders": [],
            },
            "swap_inventory": [], "mount_inventory": "",
        }
        after = copy.deepcopy(snapshot)
        after["captured_at_utc"] = "2026-11-01T00:00:06Z"
        return snapshot, after

    def synthetic_seal(self, peak_bytes, *, include_trace=True,
                       conflicting_host_boot=False):
        record, trace = self.synthetic_capacity(peak_bytes)
        before, after = self.synthetic_hosts()
        if conflicting_host_boot:
            trace["host_boot_id"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        policy = json.loads(EVIDENCE.ACCEPTANCE_MANIFEST.read_text())
        amendment = json.loads(EVIDENCE.AMENDMENT_MANIFEST.read_text())
        workload_names = (
            set(policy["physical_qualification"]["workloads"]) |
            set(amendment["workloads"]))
        summary = {
            "schema": EVIDENCE.SUMMARY_SCHEMA,
            "acceptance_manifest_sha256": EVIDENCE.sha256_bytes(
                EVIDENCE.ACCEPTANCE_MANIFEST.read_bytes()),
            "contract": policy["physical_qualification"],
            "prospective_amendment": amendment,
            "evaluation_protocol": "v2", "amendment_active": True,
            "decisions": {
                workload: {"status": "PASS"} for workload in workload_names},
            "status": "PASS", "records": [record],
            "campaign_source_sha": SOURCE,
            "campaign_target_identity":
                EVIDENCE.qualification_target_identity(before),
            "campaign_target_consistent": True,
        }

        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in (
                "before.json", "after.json", "summary.json",
                "pair.json", "ram.json")]
            for path, value in zip(paths, (before, after, summary, record, trace)):
                path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
            stability = {"status": "STABLE",
                         "checks": {"same_boot": True}, "failed_checks": []}
            with (
                mock.patch.object(EVIDENCE, "require_clean_source"),
                mock.patch.object(EVIDENCE, "source_tree_sha",
                                  return_value="b" * 40),
                mock.patch.object(EVIDENCE, "validate_host_snapshot"),
                mock.patch.object(EVIDENCE, "host_stability",
                                  return_value=stability),
                mock.patch.object(EVIDENCE, "audit_physical_pairs",
                                  return_value={"status": "PASS",
                                                "diagnostics": []}),
                mock.patch.dict(EVIDENCE.QUALIFICATION, {
                    "evaluate": lambda records, protocol: summary}),
            ):
                return EVIDENCE.seal_campaign(
                    SOURCE, *paths[:3], [paths[3]],
                    paths[4] if include_trace else None)

    def test_sealer_preserves_measured_fail_and_blocks_unverified(self):
        campaign = self.synthetic_seal(self.LIMIT + 1024)
        self.assertEqual(campaign["campaign_status"], "PASS")
        self.assertEqual(
            campaign["capacity_and_ram"]["ram_acceptance_status"], "FAIL")
        self.assertEqual(
            campaign["capacity_and_ram"]["peak_ram_bytes"], self.LIMIT + 1024)
        for kwargs in ({"include_trace": False},
                       {"conflicting_host_boot": True}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError) as caught:
                    self.synthetic_seal(self.LIMIT + 1024, **kwargs)
                message = str(caught.exception)
                for field in (
                        "BLOCKED", "phase=seal_campaign",
                        "metric=metadata_and_target_peak_ram_bytes",
                        f"limit={self.LIMIT}",
                        "observed=invalid_or_unavailable",
                        "next_prerequisite="):
                    self.assertIn(field, message)

    def test_report_and_verdict_rederive_measured_over_limit(self):
        policy_raw = EVIDENCE.ACCEPTANCE_MANIFEST.read_bytes()
        policy = json.loads(policy_raw)
        policy_digest = hashlib.sha256(policy_raw).hexdigest()
        target = {"partuuid": self.PARTUUID, "size_bytes": self.DEVICE_BYTES}
        for offset, expected in ((0, "MEASURED_WITHIN_LIMIT"),
                                 (1024, "MEASURED_OVER_LIMIT")):
            with self.subTest(offset=offset):
                campaign = self.synthetic_seal(self.LIMIT + offset)
                campaign_bytes = (json.dumps(
                    campaign, sort_keys=True) + "\n").encode()
                self.assertEqual(READINESS[
                    "validate_physical_campaign_evidence"](
                        campaign, campaign_bytes, SOURCE, policy_digest,
                        (self.PARTUUID, self.DEVICE_BYTES)), [])
                observed = (
                    datetime.datetime.fromisoformat(
                        campaign["sealed_at_utc"]) +
                    datetime.timedelta(seconds=2)).strftime(
                        "%Y-%m-%dT%H:%M:%SZ")
                # PASS here means the release receipt was supplied; the
                # independently measured over-limit RAM gate must still fail.
                capacity = campaign["capacity_and_ram"]
                release_record = {
                    "status": "PASS", "current": True, "source_sha": SOURCE,
                    "observed_at_utc": observed, "target": target,
                    "policy_sha256": policy_digest,
                    "evidence_sha256": hashlib.sha256(
                        campaign_bytes).hexdigest(),
                    "logical_capacity_bytes": capacity["logical_capacity_bytes"],
                    "peak_ram_bytes": capacity["peak_ram_bytes"],
                }
                evidence = {
                    "schema": "swapz-production-readiness-v2",
                    "snapshot_kind": "CURRENT",
                    "authorized_target": target,
                    "release_evidence": {
                        "maximum_capacity_and_ram": release_record},
                }
                verdict = READINESS["evaluate_release"](
                    SOURCE, {}, b"{}\n", evidence, policy, policy_raw,
                    physical_campaign_evidence=campaign,
                    physical_campaign_evidence_raw=campaign_bytes)
                self.assertEqual(
                    verdict["METADATA_RAM_MEASUREMENT"]["status"], expected)
                self.assertEqual(
                    verdict["METADATA_RAM_MEASUREMENT"][
                        "observed_peak_ram_bytes"], self.LIMIT + offset)
                self.assertEqual(verdict["release_verdict"], "BLOCKED")
                if offset:
                    self.assertTrue(any(
                        "claimed peak exceeds frozen limit" in message
                        for message in verdict["code_blockers"]))
                else:
                    self.assertFalse(any(
                        "claimed peak exceeds frozen limit" in message
                        for message in verdict["code_blockers"]))


if __name__ == "__main__":
    unittest.main()
