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


def arm(candidate, timestamp, run_id, workload="sd-service-balanced"):
    result = {
        "candidate": candidate, "source_sha": SOURCE, "verdict": "PASS",
        "workload_id": run_id, "arm_boot_id": BOOT,
        "arm_started_monotonic_ns": timestamp,
        "arm_finished_monotonic_ns": timestamp + 100,
        "read_ops": 1, "write_ops": 1,
        "throughput": {
            "logical_write_mbps": 1.0,
            "useful_read_bytes": 4096,
        },
        "lower_io": {"lower_write_bytes": 4096,
                     "lower_write_requests": 1},
        "cpu": {"measured_cpu_seconds_per_useful_byte": 1e-9},
        "latency": {"read_p95_ns": 100, "read_p99_ns": 200,
                    "write_p95_ns": 100, "write_p99_ns": 200},
        "swapin_latency": {"p95_ns": 100, "p99_ns": 200},
        "measurement_snapshots": {
            "lower_before": [0] * 17, "lower_after": [1] * 17},
    }
    if workload == "sd-high-occupancy-churn":
        result.update(
            cold_read={"p99_ns": 200},
            minute_buckets=[], occupancy_transitions=[])
        if candidate == "swapz":
            result["gc"] = {"wall_fraction": 0.01, "gc_wall_ns": 10}
    return result


def pair(index, timestamp, run_id=None, workload="sd-service-balanced"):
    identifier = run_id or f"physical-run-{workload}-{index}"
    order = QUALIFICATION.WORKLOADS[workload][
        "counterbalanced_order"][index - 1]
    return {
        "schema": QUALIFICATION.PAIR_SCHEMA, "workload": workload,
        "pair_id": f"pair-{workload}-{index}", "pair_index": index,
        "order": order,
        "source_sha": SOURCE, "status": "PASS",
        "excluded": False, "analysis_usable": True,
        # Synthetic chronology must honor the prospective order, not merely
        # print its label. These are not physical measurements.
        "raw": arm("raw", timestamp + (200 if order == "swapz-first" else 0),
                   identifier, workload),
        "swapz": arm("swapz", timestamp + (0 if order == "swapz-first" else 200),
                     identifier, workload),
    }


def host_snapshots():
    return (
        {"source_sha": SOURCE, "captured_monotonic_ns": 500,
         "kernel": {"boot_id": BOOT}},
        {"source_sha": SOURCE, "captured_monotonic_ns": 10000,
         "kernel": {"boot_id": BOOT}},
    )


def inspect(rows, before=None, after=None, decisions=None,
            summary_status="PASS", raw_repeat_spread=None):
    baseline, finished = host_snapshots()
    result = EVIDENCE.audit_physical_pairs(
        {"status": summary_status, "records": rows,
         "decisions": decisions or {},
         "raw_repeat_spread": raw_repeat_spread or {}},
        baseline if before is None else before,
        finished if after is None else after)
    return result, {d["metric"] for d in result["diagnostics"]}


class AdversarialPhysicalCampaign(unittest.TestCase):
    def test_positive_timing_does_not_replace_real_physical_evidence(self):
        rows = [pair(index, 1100 + 500 * index) for index in range(1, 6)]
        self.assertEqual(inspect(rows)[0]["status"], "PASS")
        self.assertNotEqual(
            QUALIFICATION.evaluate(rows, protocol="v2")["status"], "PASS")

    def test_incomplete_v2_cohort_is_blocked_without_measured_fail(self):
        # The producer must not turn an omitted frozen or amendment pair into
        # a physical FAIL merely because an evaluator summary is incomplete.
        records = [pair(1, 1600)]
        decisions = {
            workload: {"status": "INCOMPLETE"}
            for workload in QUALIFICATION.WORKLOADS
        }
        omitted_workload = next(iter(QUALIFICATION.AMENDMENT["workloads"]))
        for reported_status in ("FAIL_OR_INCOMPLETE", "PASS"):
            for omit_decision in (False, True):
                with self.subTest(reported_status=reported_status,
                                  omit_decision=omit_decision):
                    before, after = host_snapshots()
                    supplied_decisions = dict(decisions)
                    if omit_decision:
                        del supplied_decisions[omitted_workload]
                    audit = EVIDENCE.audit_physical_pairs({
                        "status": reported_status, "evaluation_protocol": "v2",
                        "records": records, "decisions": supplied_decisions,
                    }, before, after)
                    self.assertEqual(audit["status"], "BLOCKED",
                                     audit["diagnostics"])
                    self.assertEqual(audit["qualification_status"],
                                     reported_status)
                    self.assertIsNone(audit["first_failed_phase"])
                    missing = {
                        item["workload"]: (
                            item["expected"]["value"], item["observed"])
                        for item in audit["diagnostics"]
                        if item["metric"] == "qualification.attempted_pairs"
                    }
                    self.assertEqual(len(missing), len(QUALIFICATION.WORKLOADS))
                    self.assertEqual(
                        sum(expected for expected, _ in missing.values()), 24)
                    self.assertEqual(
                        sum(observed for _, observed in missing.values()), 1)
                    first_failure = audit["first_failed_evidence"]
                    self.assertEqual(first_failure["workload"],
                                     "sd-service-balanced")
                    self.assertEqual(first_failure["evidence_class"], "BLOCKED")
                    self.assertEqual(audit["admitted_source_sha"], SOURCE)
                    counts = audit["cohort_pair_counts"][omitted_workload]
                    self.assertEqual(counts["required_pairs"],
                                     QUALIFICATION.WORKLOADS[omitted_workload]["pairs"])
                    self.assertEqual(counts["attempted_pairs"], 0)
                    self.assertEqual(counts["accepted_pairs"], 0)
                    for workload in QUALIFICATION.AMENDMENT["workloads"]:
                        self.assertEqual(missing[workload][1], 0)
                    if omit_decision:
                        self.assertTrue(any(
                            item["metric"] == "qualification.decision" and
                            item["workload"] == omitted_workload
                            for item in audit["diagnostics"]))
                    self.assertFalse(any(
                        item["status"] == "FAIL" for item in audit["diagnostics"]))

    def test_unusable_cohort_cannot_claim_measured_decision_failure(self):
        # A numerically failing check is not a terminal measurement when one
        # of the frozen attempts was screened out of the accepted cohort.
        records = [pair(index, 1100 + 500 * index)
                   for index in range(1, 6)]
        records[1]["status"] = "EXCLUDED"
        records[1]["excluded"] = True
        records[1]["analysis_usable"] = False
        names = ("useful_write", "lower_write_bytes",
                 "lower_write_requests", "read_p95", "read_p99",
                 "write_p95", "write_p99", "cpu")
        decision = QUALIFICATION.service_decision(
            [{"deltas": {name: 0.0 for name in names}} for _ in range(5)],
            "sd-service-balanced")
        self.assertEqual(decision["status"], "FAIL")
        audit, _ = inspect(records, decisions={
            "sd-service-balanced": decision},
            summary_status="FAIL_OR_INCOMPLETE")
        self.assertEqual(audit["status"], "BLOCKED", audit["diagnostics"])
        self.assertIsNone(audit["first_failed_phase"])
        self.assertFalse(any(
            item["status"] == "FAIL" for item in audit["diagnostics"]))

    def test_unbound_producer_fail_does_not_claim_terminal_measurement(self):
        record = pair(1, 1100)
        record["status"] = "EXCLUDED"
        record["excluded"] = True
        record["analysis_usable"] = False
        record["raw"]["verdict"] = "FAIL"
        record["raw"]["source_sha"] = "b" * 40
        audit, _ = inspect([record], summary_status="FAIL_OR_INCOMPLETE")
        self.assertEqual(audit["status"], "BLOCKED", audit["diagnostics"])
        self.assertIsNone(audit["first_failed_phase"])
        self.assertFalse(any(
            item["status"] == "FAIL" for item in audit["diagnostics"]))

    def test_foreign_target_blocks_terminal_producer_claim(self):
        record = pair(1, 1100)
        record["status"] = "EXCLUDED"
        record["excluded"] = True
        record["analysis_usable"] = False
        record["raw"]["verdict"] = "FAIL"
        before, after = host_snapshots()
        for snapshot in (before, after):
            snapshot["device"] = {
                "partuuid": "12345678-aaaa", "size_bytes": 8 * 1024**3,
                "major_minor": "8:1", "parent_major_minor": "8:0",
                "model": "synthetic", "transport": "usb",
            }
        claimed = EVIDENCE.qualification_target_identity(before)
        claimed["physical_partuuid"] = "ffffffff-bbbb"
        audit = EVIDENCE.audit_physical_pairs({
            "status": "FAIL_OR_INCOMPLETE", "records": [record],
            "decisions": {}, "campaign_target_consistent": True,
            "campaign_target_identity": claimed,
        }, before, after)
        self.assertEqual(audit["status"], "BLOCKED", audit["diagnostics"])
        self.assertIsNone(audit["first_failed_phase"])
        self.assertEqual(audit["admitted_source_sha"], SOURCE)
        self.assertEqual(audit["admitted_target_partuuid"], "12345678-aaaa")
        self.assertIn("qualification.campaign_target_identity", {
            item["metric"] for item in audit["diagnostics"]})
        self.assertFalse(any(
            item["status"] == "FAIL" for item in audit["diagnostics"]))

    def test_authenticated_producer_keeps_phase_and_redacts_private_error(self):
        record = pair(1, 1100)
        record["status"] = "EXCLUDED"
        record["excluded"] = True
        record["analysis_usable"] = False
        record["raw"]["verdict"] = "FAIL"
        record["raw"]["stage"] = "measure"
        record["raw"]["failure_reason"] = "/private/host/error"
        audit, _ = inspect([record], summary_status="FAIL_OR_INCOMPLETE")
        self.assertEqual(audit["status"], "FAIL")
        self.assertEqual(audit["first_failed_phase"], "measure")
        self.assertEqual(audit["first_failed_evidence"]["workload"],
                         "sd-service-balanced")
        self.assertEqual(audit["first_failed_evidence"]["pair_index"], 1)
        self.assertEqual(audit["first_failed_evidence"]["evidence_class"],
                         "FAIL")
        self.assertEqual(audit["admitted_source_sha"], SOURCE)
        self.assertNotIn("/private/host", str(audit))
        self.assertEqual(record["raw"]["failure_reason"], "/private/host/error")

    def test_missing_or_unknown_producer_phase_is_blocked(self):
        # A FAIL verdict without the producer's real measurement phase cannot
        # be promoted by inventing a generic audit phase.
        for stage in (
                None, "unknown-private-phase", "preflight", "fill", "warmup",
                "teardown", "publish"):
            with self.subTest(stage=stage):
                record = pair(1, 1100)
                record["status"] = "EXCLUDED"
                record["excluded"] = True
                record["analysis_usable"] = False
                record["raw"]["verdict"] = "FAIL"
                if stage is not None:
                    record["raw"]["stage"] = stage
                audit, _ = inspect(
                    [record], summary_status="FAIL_OR_INCOMPLETE")
                self.assertEqual(
                    audit["status"], "BLOCKED", audit["diagnostics"])
                self.assertIsNone(audit["first_failed_phase"])
                self.assertFalse(any(
                    item["status"] == "FAIL"
                    for item in audit["diagnostics"]))

    def test_duplicate_identity_invalidates_both_failure_witnesses(self):
        def failed_pair(run_id):
            record = pair(1, 1100, run_id=run_id)
            record["status"] = "EXCLUDED"
            record["excluded"] = True
            record["analysis_usable"] = False
            record["raw"]["verdict"] = "FAIL"
            record["raw"]["stage"] = "measure"
            return record

        first = failed_pair("first-run")
        duplicate_pair = pair(2, 1800, run_id="second-run")
        duplicate_pair["pair_id"] = first["pair_id"]
        audit, metrics = inspect(
            [first, duplicate_pair], summary_status="FAIL_OR_INCOMPLETE")
        self.assertEqual(audit["status"], "BLOCKED", audit["diagnostics"])
        self.assertIn("pair.pair_id", metrics)
        self.assertFalse(any(
            item["status"] == "FAIL" for item in audit["diagnostics"]))

        first = failed_pair("duplicate-run")
        duplicate_run = pair(2, 1800, run_id="duplicate-run")
        audit, metrics = inspect(
            [first, duplicate_run], summary_status="FAIL_OR_INCOMPLETE")
        self.assertEqual(audit["status"], "BLOCKED", audit["diagnostics"])
        self.assertIn("arm.workload_id", metrics)
        self.assertFalse(any(
            item["status"] == "FAIL" for item in audit["diagnostics"]))

    def test_duplicate_pair_index_invalidates_first_failure_witness(self):
        first = pair(1, 1100, run_id="first-run")
        first["status"] = "EXCLUDED"
        first["excluded"] = True
        first["analysis_usable"] = False
        first["raw"]["verdict"] = "FAIL"
        first["raw"]["stage"] = "measure"
        duplicate = pair(1, 1800, run_id="second-run")
        duplicate["pair_id"] = "different-pair-id"
        audit, metrics = inspect(
            [first, duplicate], summary_status="FAIL_OR_INCOMPLETE")
        self.assertEqual(audit["status"], "BLOCKED", audit["diagnostics"])
        self.assertIn("pair.pair_index", metrics)
        self.assertIsNone(audit["first_failed_phase"])
        self.assertFalse(any(
            item["status"] == "FAIL" for item in audit["diagnostics"]))

    def test_nested_overlap_invalidates_nonadjacent_failure_witness(self):
        first = pair(1, 1100)
        first["raw"]["arm_finished_monotonic_ns"] = 2000
        middle = pair(2, 1200)
        failed = pair(3, 1600)
        failed["status"] = "EXCLUDED"
        failed["excluded"] = True
        failed["analysis_usable"] = False
        failed["swapz"]["verdict"] = "FAIL"
        failed["swapz"]["stage"] = "measure"
        audit, metrics = inspect(
            [first, middle, failed], summary_status="FAIL_OR_INCOMPLETE")
        self.assertEqual(audit["status"], "BLOCKED", audit["diagnostics"])
        self.assertIn("arm.monotonic_window_ns", metrics)
        self.assertIsNone(audit["first_failed_phase"])
        self.assertFalse(any(
            item["status"] == "FAIL" for item in audit["diagnostics"]))

    def test_overlap_invalidates_both_physical_failure_witnesses(self):
        first = pair(1, 1100)
        first["status"] = "EXCLUDED"
        first["excluded"] = True
        first["analysis_usable"] = False
        first["raw"]["verdict"] = "FAIL"
        first["raw"]["stage"] = "measure"
        # Pair 2 overlaps both pair-1 arms. The later diagnostic must also
        # invalidate the earlier arm as an authenticated physical witness.
        second = pair(2, 1150)
        audit, metrics = inspect(
            [first, second], summary_status="FAIL_OR_INCOMPLETE")
        self.assertEqual(audit["status"], "BLOCKED", audit["diagnostics"])
        self.assertIn("arm.monotonic_window_ns", metrics)
        self.assertFalse(any(
            item["status"] == "FAIL" for item in audit["diagnostics"]))

    def test_explicit_v2_failure_requires_campaign_target_binding(self):
        record = pair(1, 1100)
        record["status"] = "EXCLUDED"
        record["excluded"] = True
        record["analysis_usable"] = False
        record["raw"]["verdict"] = "FAIL"
        record["raw"]["stage"] = "measure"
        decisions = {
            workload: {"status": "INCOMPLETE"}
            for workload in QUALIFICATION.WORKLOADS
        }
        before, after = host_snapshots()
        audit = EVIDENCE.audit_physical_pairs({
            "status": "FAIL_OR_INCOMPLETE",
            "evaluation_protocol": "v2",
            "records": [record],
            "decisions": decisions,
        }, before, after)
        self.assertEqual(audit["status"], "BLOCKED", audit["diagnostics"])
        self.assertIsNone(audit["first_failed_phase"])
        self.assertFalse(any(
            item["status"] == "FAIL" for item in audit["diagnostics"]))

    def test_invalid_host_source_or_boot_cannot_authenticate_failure(self):
        for binding in ("source", "boot"):
            with self.subTest(binding=binding):
                record = pair(1, 1100)
                record["status"] = "EXCLUDED"
                record["excluded"] = True
                record["analysis_usable"] = False
                record["raw"]["verdict"] = "FAIL"
                record["raw"]["stage"] = "measure"
                before, after = host_snapshots()
                if binding == "source":
                    for snapshot in (before, after):
                        snapshot["source_sha"] = "not-a-source-sha"
                    record["source_sha"] = "not-a-source-sha"
                    for label in ("raw", "swapz"):
                        record[label]["source_sha"] = "not-a-source-sha"
                else:
                    for snapshot in (before, after):
                        snapshot["kernel"]["boot_id"] = None
                    for label in ("raw", "swapz"):
                        record[label]["arm_boot_id"] = None
                audit, _ = inspect(
                    [record], before=before, after=after,
                    summary_status="FAIL_OR_INCOMPLETE")
                self.assertEqual(
                    audit["status"], "BLOCKED", audit["diagnostics"])
                self.assertIsNone(audit["first_failed_phase"])
                self.assertFalse(any(
                    item["status"] == "FAIL"
                    for item in audit["diagnostics"]))

    def test_summary_pass_cannot_authenticate_failed_decision(self):
        records = [pair(index, 1100 + 500 * index)
                   for index in range(1, 6)]
        names = ("useful_write", "lower_write_bytes",
                 "lower_write_requests", "read_p95", "read_p99",
                 "write_p95", "write_p99", "cpu")
        decision = QUALIFICATION.service_decision(
            [{"deltas": {name: 0.0 for name in names}} for _ in range(5)],
            "sd-service-balanced")
        self.assertEqual(decision["status"], "FAIL")
        audit, _ = inspect(
            records, decisions={"sd-service-balanced": decision},
            summary_status="PASS")
        self.assertEqual(audit["status"], "BLOCKED", audit["diagnostics"])
        self.assertIsNone(audit["first_failed_phase"])
        self.assertFalse(any(
            item["status"] == "FAIL" for item in audit["diagnostics"]))

    def test_producer_fail_requires_excluded_pair_disposition_and_schema(self):
        for mutation in ("pass-disposition", "wrong-schema"):
            with self.subTest(mutation=mutation):
                record = pair(1, 1100)
                record["raw"]["verdict"] = "FAIL"
                record["raw"]["stage"] = "measure"
                if mutation == "pass-disposition":
                    # A producer FAIL cannot coexist with an evaluator-usable
                    # PASS pair and still become authenticated failure evidence.
                    pass
                else:
                    record["status"] = "EXCLUDED"
                    record["excluded"] = True
                    record["analysis_usable"] = False
                    record["schema"] = "not-the-physical-pair-schema"
                audit, metrics = inspect(
                    [record], summary_status="FAIL_OR_INCOMPLETE")
                self.assertEqual(
                    audit["status"], "BLOCKED", audit["diagnostics"])
                if mutation == "wrong-schema":
                    self.assertIn("pair.schema", metrics)
                self.assertIsNone(audit["first_failed_phase"])
                self.assertFalse(any(
                    item["status"] == "FAIL"
                    for item in audit["diagnostics"]))

    def test_release_failure_witness_rejects_invented_arm_phase(self):
        workload = "sd-service-balanced"
        specification = QUALIFICATION.WORKLOADS[workload]
        pair_artifact = {
            "name": "pair.json", "size_bytes": 1, "sha256": "0" * 64,
            "workload": workload, "pair_id": "pair-1", "pair_index": 1,
            "order": specification["counterbalanced_order"][0],
            "status": "EXCLUDED", "excluded": True,
        }
        audit = {
            "diagnostics": [{
                "status": "FAIL", "metric": "arm.verdict",
                "workload": workload, "pair_index": 1, "arm": "raw",
                "producer_status": "FAIL",
            }],
            "first_failed_phase": "arm",
            "first_failed_evidence": {
                "workload": workload, "pair_index": 1, "arm": "raw",
                "metric": "arm.verdict", "evidence_class": "FAIL",
            },
        }
        self.assertFalse(READINESS[
            "_physical_audit_failure_witness_is_valid"](
                audit, {workload: specification}, [pair_artifact]))

    def test_release_audit_binding_rejects_duplicate_artifact_identity(self):
        workload = "sd-service-balanced"
        specification = QUALIFICATION.WORKLOADS[workload]
        target_partuuid = "12345678-aaaa"
        target_bytes = 8 * 1024**3
        pairs = [{
            "name": f"pair-{index}.json",
            "size_bytes": 1,
            "sha256": f"{index:064x}",
            "workload": workload,
            "pair_id": f"pair-{index}",
            "pair_index": index,
            "order": specification["counterbalanced_order"][index - 1],
            "status": "PASS",
            "excluded": False,
        } for index in range(1, specification["pairs"] + 1)]
        audit = {
            "status": "FAIL",
            "diagnostics": [],
            "omitted_diagnostic_count": 0,
            "qualification_status": "FAIL_OR_INCOMPLETE",
            "first_failed_phase": "qualification",
            "first_failed_evidence": {
                "workload": workload, "pair_index": None, "arm": None,
                "metric": "qualification.decision_status",
                "evidence_class": "FAIL",
            },
            "cohort_pair_counts": {
                workload: {
                    "required_pairs": specification["pairs"],
                    "attempted_pairs": specification["pairs"],
                    "accepted_pairs": specification["pairs"],
                },
            },
            "admitted_source_sha": SOURCE,
            "admitted_target_partuuid": target_partuuid,
            "claim_boundary": QUALIFICATION.CONTRACT["claim_boundary"],
            "measurement_authority": "host-visible lower I/O, not NAND wear",
        }
        validator = READINESS["_physical_audit_binding_is_valid"]
        arguments = (
            audit, SOURCE, (target_partuuid, target_bytes),
            QUALIFICATION.CONTRACT, {workload: specification})
        self.assertTrue(validator(*arguments, pairs, "FAIL_OR_INCOMPLETE"))

        mutations = {
            "name": lambda rows: rows[1].__setitem__(
                "name", rows[0]["name"]),
            "digest": lambda rows: rows[1].__setitem__(
                "sha256", rows[0]["sha256"]),
            "pair-id": lambda rows: rows[1].__setitem__(
                "pair_id", rows[0]["pair_id"]),
            "pair-index": lambda rows: rows[1].__setitem__(
                "pair_index", rows[0]["pair_index"]),
            "order": lambda rows: rows[1].__setitem__("order", "raw-first"),
            "disposition": lambda rows: rows[1].update(
                status="PASS", excluded=True),
            "disposition-type": lambda rows: rows[1].update(
                status="PASS", excluded=0),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(pairs)
                mutate(changed)
                self.assertFalse(validator(
                    *arguments, changed, "FAIL_OR_INCOMPLETE"))

    def test_counterbalanced_order_and_duplicate_indices_block_audit(self):
        record = pair(1, 1100)
        record["order"] = "swapz-first"
        audit, metrics = inspect([record])
        self.assertEqual(audit["status"], "BLOCKED", audit["diagnostics"])
        self.assertIn("pair.order", metrics)

        first = pair(1, 1100)
        second = pair(1, 1600, run_id="second-attempt")
        second["pair_id"] = "different-id"
        audit, metrics = inspect([first, second])
        self.assertEqual(audit["status"], "BLOCKED", audit["diagnostics"])
        self.assertIn("pair.pair_index", metrics)

    def test_duplicate_pair_and_run_identifiers(self):
        records = [pair(1, 1100, "duplicate"),
                   pair(2, 1600, "duplicate")]
        self.assertIn("arm.workload_id", inspect(records)[1])
        records[1]["pair_id"] = records[0]["pair_id"]
        self.assertIn("pair.pair_id", inspect(records)[1])

    def test_mismatched_paired_run_identity(self):
        record = pair(1, 1100)
        record["swapz"]["workload_id"] = "different-physical-run"
        audit, metrics = inspect([record])
        self.assertEqual(audit["status"], "BLOCKED")
        self.assertIn("pair.workload_id", metrics)
        problem = next(
            item for item in audit["diagnostics"]
            if item["metric"] == "pair.workload_id")
        self.assertEqual(
            problem["expected"], "matching raw/swapz physical run identity")
        self.assertIsNone(problem["observed"])
        self.assertEqual(problem["pair_index"], 1)
        self.assertIsNone(problem["arm"])
        self.assertEqual(
            problem["reason"], "paired raw/swapz run identity mismatch")

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
        # Use a fully accepted synthetic cohort to exercise the numeric
        # diagnostic. The excluded attempt above is screening evidence only.
        accepted_records = [pair(i, 1100 + 500 * i) for i in range(1, 6)]
        audited, metrics = inspect(accepted_records, decisions={
            "sd-service-balanced": decision}, summary_status="FAIL_OR_INCOMPLETE")
        self.assertEqual(audited["status"], "FAIL")
        self.assertIn("useful_write.paired_95pct_ci_lower", metrics)
        observed = next(
            item for item in audited["diagnostics"]
            if item["metric"] == "useful_write.paired_95pct_ci_lower")
        self.assertEqual(observed["expected"]["value"],
                         QUALIFICATION.CONTRACT["acceptance"]["service"][
                             "useful_write_ci_lower_min"])

    def test_truncated_diagnostics_preserve_blocked_status(self):
        # Twelve missing measured fields per arm fill the 96-entry cap before
        # the last arm's foreign boot is visited. The classification must not
        # depend on which diagnostics fit into the public result.
        records = [pair(index, 1100 + 500 * index)
                   for index in range(1, 6)]
        for record in records:
            for label in ("raw", "swapz"):
                candidate = record[label]
                for field in ("read_ops", "write_ops"):
                    candidate.pop(field)
                for field in ("lower_io", "throughput", "cpu",
                              "latency", "measurement_snapshots"):
                    candidate[field] = {}
        # Model a rejected evaluator result followed by three late identity
        # blocks after unavailable measurements have filled the public cap.
        records[0]["status"] = "EXCLUDED"
        records[0]["excluded"] = True
        records[0]["analysis_usable"] = False
        # EXCLUDED alone is incomplete evidence. Preserve one genuine producer
        # failure so the diagnostic-cap test still exercises FAIL precedence.
        records[0]["raw"]["verdict"] = "FAIL"
        records[0]["raw"]["stage"] = "measure"
        records[-1]["swapz"]["workload_id"] = records[0]["swapz"]["workload_id"]
        records[-1]["swapz"]["source_sha"] = "b" * 40
        records[-1]["swapz"]["arm_boot_id"] = (
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        audit, _ = inspect(
            records, summary_status="FAIL_OR_INCOMPLETE")
        # FAIL is authoritative once a producer arm failure is known;
        # later prerequisite blocks and unavailable observations stay distinct.
        self.assertEqual(audit["status"], "FAIL")
        self.assertEqual(len(audit["diagnostics"]),
                         EVIDENCE.MAX_EVIDENCE_DIAGNOSTICS)
        self.assertGreater(audit["omitted_diagnostic_count"], 0)
        self.assertEqual(
            {item["status"] for item in audit["diagnostics"]},
            {"FAIL", "BLOCKED", "UNAVAILABLE"})
        self.assertTrue(any(
            item["status"] == "FAIL" and item["metric"] == "arm.verdict" and
            item["pair_index"] == 1 and item.get("producer_status") == "FAIL"
            for item in audit["diagnostics"]))
        self.assertEqual(audit["first_failed_phase"], "measure")
        self.assertTrue(any(
            item["status"] == "BLOCKED" and
            item["metric"] in {
                "arm.workload_id", "arm.source_sha", "arm.arm_boot_id"} and
            item["pair_index"] == 5 and item["arm"] == "swapz"
            for item in audit["diagnostics"]))

    def test_distinct_evidence_failure_classifications(self):
        baseline = pair(1, 1100)
        missing = copy.deepcopy(baseline)
        missing["raw"]["latency"].pop("read_p95_ns")
        unavailable, _ = inspect([missing])
        # UNAVAILABLE describes the field; missing required evidence must have
        # a BLOCKED campaign disposition, never a measured FAIL.
        self.assertEqual(unavailable["status"], "BLOCKED")
        self.assertIn("UNAVAILABLE", {
            entry["status"] for entry in unavailable["diagnostics"]})
        blocked = copy.deepcopy(baseline)
        blocked["raw"]["source_sha"] = "b" * 40
        # Match the evaluator consequence of stale provenance. This must not
        # turn a prerequisite/identity problem into producer-proven failure.
        blocked["analysis_usable"] = False
        blocked_audit, _ = inspect(
            [blocked], summary_status="FAIL_OR_INCOMPLETE")
        self.assertEqual(blocked_audit["status"], "BLOCKED")
        self.assertIsNone(blocked_audit["first_failed_phase"])
        self.assertFalse(any(
            item["status"] == "FAIL"
            for item in blocked_audit["diagnostics"]))
        problem = next(item for item in blocked_audit["diagnostics"]
                       if item["metric"] == "arm.source_sha")
        self.assertEqual(problem["expected"], "admitted source")
        self.assertEqual(problem["observed"], None)
        self.assertEqual(problem["pair_index"], 1)
        self.assertEqual(problem["arm"], "raw")
        self.assertIn("stale source", problem["reason"])
        excluded = copy.deepcopy(baseline)
        excluded["status"] = "EXCLUDED"
        excluded["excluded"] = True
        excluded["analysis_usable"] = False
        incomplete, _ = inspect(
            [excluded], summary_status="FAIL_OR_INCOMPLETE")
        self.assertEqual(incomplete["status"], "BLOCKED")
        self.assertIsNone(incomplete["first_failed_phase"])

        drift_records = [pair(index, 1100 + 500 * index)
                         for index in range(1, 6)]
        drift_bound = QUALIFICATION.CONTRACT["screening"][
            "same_workload_raw_spread_max"]
        drift, _ = inspect(
            drift_records,
            decisions={"sd-service-balanced": {"status": "INCOMPLETE"}},
            summary_status="FAIL_OR_INCOMPLETE",
            raw_repeat_spread={"sd-service-balanced": drift_bound + 0.01})
        self.assertEqual(drift["status"], "BLOCKED")
        self.assertIsNone(drift["first_failed_phase"])
        self.assertFalse(any(
            item["status"] == "FAIL" for item in drift["diagnostics"]))
        self.assertTrue(any(
            item["metric"] == "raw_repeat_spread" and
            item["status"] == "BLOCKED"
            for item in drift["diagnostics"]))

        producer_failed = copy.deepcopy(excluded)
        producer_failed["raw"]["verdict"] = "FAIL"
        producer_failed["raw"]["stage"] = "measure"
        failed, _ = inspect(
            [producer_failed], summary_status="FAIL_OR_INCOMPLETE")
        self.assertEqual(failed["status"], "FAIL")
        producer_failure = next(
            item for item in failed["diagnostics"]
            if item["metric"] == "arm.verdict")
        self.assertEqual(producer_failure["producer_status"], "FAIL")
        self.assertEqual(failed["first_failed_phase"], "measure")

    def test_different_workload_trace_excludes_pair(self):
        record = pair(1, 1100)
        record["raw"]["operation_recipe_sha256"] = "a" * 64
        record["swapz"]["operation_recipe_sha256"] = "b" * 64
        compared = QUALIFICATION.compare_pair(
            record["raw"], record["swapz"], record["workload"],
            record["pair_id"], record["pair_index"], record["order"])
        self.assertEqual(compared["status"], "EXCLUDED")
        self.assertTrue(any(
            "pair provenance mismatch" in reason and
            "operation_recipe_sha256" in reason
            for reason in compared["exclusion_reasons"]))

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

        record = pair(
            1, 2_100_000_000, workload="sd-high-occupancy-churn")
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
        for offset in (-1024, 0, 1024):
            with self.subTest(offset=offset):
                record, trace = self.synthetic_capacity(self.LIMIT + offset)
                capacity = EVIDENCE.campaign_capacity_and_ram(
                    [record], self.DEVICE_BYTES, SOURCE, trace)
                self.assertIsNotNone(capacity)
                self.assertNotIn("ram_acceptance_status", capacity)
                self.assertNotIn("ram_limit_bytes", capacity)
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
            "captured_monotonic_ns": 2_000_000_000,
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
        after["captured_monotonic_ns"] = 10_000_000_000
        return snapshot, after

    def synthetic_seal(self, peak_bytes, *, include_trace=True,
                       conflicting_host_boot=False, summary_mutation=None):
        capacity_record, trace = self.synthetic_capacity(peak_bytes)
        before, after = self.synthetic_hosts()
        if conflicting_host_boot:
            trace["host_boot_id"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        policy = json.loads(EVIDENCE.ACCEPTANCE_MANIFEST.read_text())
        amendment = json.loads(EVIDENCE.AMENDMENT_MANIFEST.read_text())
        workload_specs = dict(policy["physical_qualification"]["workloads"])
        workload_specs.update(amendment["workloads"])
        workload_names = set(workload_specs)
        records = []
        timestamp = 3_000_000_000
        for workload, specification in workload_specs.items():
            if workload == "sd-high-occupancy-churn":
                records.append(capacity_record)
                continue
            for index in range(1, specification["pairs"] + 1):
                records.append(pair(
                    index, timestamp,
                    run_id=f"synthetic-{workload}-{index}",
                    workload=workload))
                timestamp += 50_000_000
        self.assertEqual(
            len(records), sum(item["pairs"] for item in workload_specs.values()))
        summary = {
            "schema": EVIDENCE.SUMMARY_SCHEMA,
            "acceptance_manifest_sha256": EVIDENCE.sha256_bytes(
                EVIDENCE.ACCEPTANCE_MANIFEST.read_bytes()),
            "contract": policy["physical_qualification"],
            "prospective_amendment": amendment,
            "evaluation_protocol": "v2", "amendment_active": True,
            "decisions": {
                workload: {"status": "PASS"} for workload in workload_names},
            "status": "PASS", "records": records,
            "campaign_source_sha": SOURCE,
            "campaign_target_identity":
                EVIDENCE.qualification_target_identity(before),
            "campaign_target_consistent": True,
        }

        # Retain the evaluator output before corrupting the serialized
        # summary; the sealer must catch every type drift.
        regenerated_summary = copy.deepcopy(summary)
        if summary_mutation is not None:
            summary = copy.deepcopy(summary)
            summary_mutation(summary)

        with tempfile.TemporaryDirectory() as directory:
            pair_paths = [
                Path(directory) /
                f"pair-{index:02d}-{record['workload']}.json"
                for index, record in enumerate(records, 1)]
            paths = [
                Path(directory) / "before.json",
                Path(directory) / "after.json",
                Path(directory) / "summary.json",
                *pair_paths,
                Path(directory) / "ram.json",
            ]
            values = [before, after, summary, *records, trace]
            for path, value in zip(paths, values):
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
                mock.patch.dict(EVIDENCE.QUALIFICATION, {
                    "evaluate": lambda records, protocol: regenerated_summary}),
            ):
                return EVIDENCE.seal_campaign(
                    SOURCE, *paths[:3], pair_paths,
                    paths[-1] if include_trace else None)

    def test_sealer_rejects_type_coerced_evaluator_summary(self):
        # Python compares numeric 1 == True and 0 == False. These mutations
        # previously sealed PASS while changing the original pair, frozen
        # policy or regenerated evaluator result.
        def change_arm_count(summary):
            summary["records"][0]["raw"]["read_ops"] = True

        def change_arm_count_float(summary):
            summary["records"][0]["raw"]["read_ops"] = 1.0

        def change_frozen_limit(summary):
            summary["contract"]["acceptance"]["sustained"][
                "gc_no_headroom_skips_max"] = False

        def change_frozen_limit_float(summary):
            summary["contract"]["acceptance"]["sustained"][
                "gc_no_headroom_skips_max"] = 0.0

        def change_evaluator_flag(summary):
            summary["campaign_target_consistent"] = 1

        for mutation, rejected_field in (
                (change_arm_count, "summary changed original pair field raw"),
                (change_arm_count_float,
                 "summary changed original pair field raw"),
                (change_frozen_limit, "contract differs from frozen policy"),
                (change_frozen_limit_float,
                 "contract differs from frozen policy"),
                (change_evaluator_flag, "does not exactly match supplied pair")):
            with self.subTest(field=rejected_field):
                with self.assertRaisesRegex(ValueError, rejected_field):
                    self.synthetic_seal(self.LIMIT, summary_mutation=mutation)

    def test_sealer_preserves_measured_fail_and_blocks_unverified(self):
        campaign = self.synthetic_seal(self.LIMIT + 1024)
        self.assertEqual(campaign["campaign_status"], "PASS")
        capacity = campaign["capacity_and_ram"]
        self.assertNotIn("ram_acceptance_status", capacity)
        self.assertNotIn("ram_limit_bytes", capacity)
        self.assertEqual(capacity["peak_ram_bytes"], self.LIMIT + 1024)
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
