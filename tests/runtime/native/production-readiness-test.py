#!/usr/bin/env python3
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[3]
EVALUATOR_PATH = ROOT / "tests/tools/evaluate-production-readiness.py"
SPEC = importlib.util.spec_from_file_location("swapz_release_eval", EVALUATOR_PATH)
EVALUATOR = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(EVALUATOR)

SOURCE = "a" * 40
ARTIFACTS = {
    "formatter_sha256": "1" * 64,
    "module_sha256": "2" * 64,
    "oracle_sha256": "3" * 64,
}
TARGET = {"partuuid": "f13428f6-01", "size_bytes": 124787884032}


def acceptance_policy():
    return {
        "schema": "swapz-production-acceptance-v1",
        "status": "FROZEN",
        "primary_real_swap": {
            "page_bytes": 4096,
        },
        "physical_qualification": {
            "schema": "swapz-performance-qualification-v1",
            "acceptance": {
                "sustained": {
                    "metadata_and_target_peak_ram_bytes_max": 1342177280,
                },
            },
        },
    }


def encoded(value):
    return (json.dumps(
        value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def owner_report():
    return {
        "schema": "swapz-test-results-v1",
        "source_sha": SOURCE,
        "tested_commit_sha": SOURCE,
        "qualification": "RAM_BACKED_NULL_BLK_ONLY",
        "overall": "PASS",
        "qualified_artifacts": {
            "status": "AVAILABLE",
            **dict(ARTIFACTS),
        },
        "stages": [
            {"name": name, "status": "PASS"}
            for name in EVALUATOR.REQUIRED_STAGES
        ],
    }


def pass_record(**extra):
    return {
        "status": "PASS",
        "current": True,
        "source_sha": SOURCE,
        **extra,
    }


def current_evidence(report_raw, policy_raw):
    policy_digest = hashlib.sha256(policy_raw).hexdigest()
    report_digest = hashlib.sha256(report_raw).hexdigest()
    return {
        "schema": "swapz-production-readiness-v2",
        "snapshot_kind": "CURRENT",
        "repository": {
            "branch": "main",
            "local_sha": SOURCE,
            "origin_main_sha": SOURCE,
            "production_source_sha": SOURCE,
            "synchronized": True,
        },
        "authorized_target": dict(TARGET),
        "release_evidence": {
            "production_source": pass_record(),
            "clean_build_state": pass_record(clean=True),
            "qualified_artifact_hashes": pass_record(
                qualified=True, hashes=dict(ARTIFACTS)),
            "required_ci": pass_record(runs=[
                {
                    "workflow": workflow,
                    "head_sha": SOURCE,
                    "result": "PASS",
                }
                for workflow in EVALUATOR.REQUIRED_CI_WORKFLOWS
            ]),
            "exact_source_owner_make_test": pass_record(
                overall="PASS",
                tested_source_sha=SOURCE,
                report_sha256=report_digest,
                hashes=dict(ARTIFACTS)),
            "owned_nullblk_qualification": pass_record(),
            "unresolved_critical_issues": pass_record(count=0),
            "real_linux_swap": pass_record(
                policy_sha256=policy_digest,
                target=dict(TARGET),
                hashes=dict(ARTIFACTS)),
            "maximum_capacity_and_ram": pass_record(
                policy_sha256=policy_digest,
                target=dict(TARGET),
                logical_capacity_bytes=110920466432,
                peak_ram_bytes=900000000),
            "sustained_physical_performance": pass_record(
                policy_sha256=policy_digest,
                target=dict(TARGET)),
            "lifecycle_deployment_state": pass_record(
                target=dict(TARGET)),
            "installed_artifact_identity": pass_record(
                target=dict(TARGET),
                installed=True,
                hashes=dict(ARTIFACTS)),
            "cold_boot_harness": pass_record(
                target=dict(TARGET),
                armed=True),
            "owner_observed_reboot": {
                "status": "BLOCKED",
                "current": True,
                "source_sha": SOURCE,
                "target": dict(TARGET),
                "observed": False,
            },
        },
    }


def evaluate(report=None, evidence=None, policy=None):
    report = owner_report() if report is None else report
    policy = acceptance_policy() if policy is None else policy
    report_raw = encoded(report)
    policy_raw = encoded(policy)
    if evidence is None:
        evidence = current_evidence(report_raw, policy_raw)
    return EVALUATOR.evaluate_release(
        SOURCE, report, report_raw, evidence, policy, policy_raw)


class ProductionReadinessEvaluatorTest(unittest.TestCase):
    def test_complete_pre_reboot_evidence_passes_both_readiness_gates(self):
        result = evaluate()
        self.assertEqual(result["CODE_PRODUCTION_READY"], "PASS")
        self.assertEqual(result["DEPLOYMENT_PRODUCTION_READY"], "PASS")
        self.assertEqual(result["PRODUCTION_READY_FOR_OWNER_REBOOT"], "PASS")
        self.assertEqual(result["COLD_BOOT_HARNESS"], "ARMED")
        self.assertEqual(result["COLD_BOOT_OBSERVED"], "NO")
        self.assertEqual(result["code_blockers"], [])
        self.assertEqual(result["deployment_blockers"], [])

    def test_owner_reboot_is_separate_from_code_and_deployment_readiness(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        reboot = evidence["release_evidence"]["owner_observed_reboot"]
        reboot.update(status="PASS", observed=True)
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "PASS")
        self.assertEqual(result["DEPLOYMENT_PRODUCTION_READY"], "PASS")
        self.assertEqual(result["COLD_BOOT_OBSERVED"], "PASS")

        reboot.update(status="FAIL", observed=False)
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "PASS")
        self.assertEqual(result["DEPLOYMENT_PRODUCTION_READY"], "PASS")
        self.assertEqual(result["COLD_BOOT_OBSERVED"], "FAIL")

    def test_historical_or_unsynchronized_source_cannot_pass(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        evidence["snapshot_kind"] = "HISTORICAL"
        evidence["repository"]["origin_main_sha"] = "b" * 40
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "historical" in blocker for blocker in result["code_blockers"]))
        self.assertTrue(any(
            "frozen on synchronized main" in blocker
            for blocker in result["code_blockers"]))

    def test_current_owner_failure_overrides_self_declared_pass_records(self):
        report = owner_report()
        report["overall"] = "FAIL"
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "make test is not PASS" in blocker
            for blocker in result["code_blockers"]))

    def test_each_required_ci_workflow_must_pass_the_exact_source(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        runs = evidence["release_evidence"]["required_ci"]["runs"]
        runs[0]["head_sha"] = "b" * 40
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "exact-source PASS" in blocker for blocker in result["code_blockers"]))

    def test_systemd_package_workflow_is_a_required_release_gate(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        runs = evidence["release_evidence"]["required_ci"]["runs"]
        runs[:] = [
            run for run in runs
            if run["workflow"] != "Systemd and package production-readiness"
        ]
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "Systemd and package production-readiness" in blocker
            for blocker in result["code_blockers"]))

    def test_artifact_hash_mappings_are_cross_bound_independently(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        qualified = evidence["release_evidence"]["qualified_artifact_hashes"]["hashes"]
        owner = evidence["release_evidence"]["exact_source_owner_make_test"]["hashes"]
        real_swap = evidence["release_evidence"]["real_linux_swap"]["hashes"]
        installed = evidence["release_evidence"]["installed_artifact_identity"]["hashes"]
        self.assertIsNot(qualified, owner)
        self.assertIsNot(owner, real_swap)
        self.assertIsNot(real_swap, installed)

        real_swap["module_sha256"] = "4" * 64
        self.assertEqual(owner["module_sha256"], ARTIFACTS["module_sha256"])
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "installed artifact binding mismatch" in blocker
            for blocker in result["code_blockers"]))

    def test_policy_and_target_bindings_are_exact(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        evidence["release_evidence"]["maximum_capacity_and_ram"][
            "policy_sha256"] = "5" * 64
        evidence["release_evidence"]["sustained_physical_performance"][
            "target"]["size_bytes"] += 4096
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "policy binding mismatch" in blocker
            for blocker in result["code_blockers"]))
        self.assertTrue(any(
            "target binding mismatch" in blocker
            for blocker in result["code_blockers"]))

    def test_full_capacity_peak_ram_must_fit_frozen_limit(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        limit = policy["physical_qualification"]["acceptance"]["sustained"][
            "metadata_and_target_peak_ram_bytes_max"]
        evidence["release_evidence"]["maximum_capacity_and_ram"][
            "peak_ram_bytes"] = limit + 1
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "peak exceeds frozen limit" in blocker
            for blocker in result["code_blockers"]))

    def test_unresolved_critical_issue_blocks_code_readiness(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        evidence["release_evidence"]["unresolved_critical_issues"]["count"] = 1
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "critical correctness" in blocker
            for blocker in result["code_blockers"]))

    def test_deployment_evidence_does_not_backfill_code_readiness(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        evidence["release_evidence"]["owned_nullblk_qualification"]["status"] = "IN_PROGRESS"
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(result["DEPLOYMENT_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "code production-readiness" in blocker
            for blocker in result["deployment_blockers"]))

    def test_installed_bytes_and_armed_harness_are_deployment_gates(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        evidence["release_evidence"]["installed_artifact_identity"]["installed"] = False
        evidence["release_evidence"]["cold_boot_harness"]["armed"] = False
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "PASS")
        self.assertEqual(result["DEPLOYMENT_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(result["PRODUCTION_READY_FOR_OWNER_REBOOT"], "NO")
        self.assertTrue(any(
            "installed bytes" in blocker for blocker in result["deployment_blockers"]))
        self.assertTrue(any(
            "not armed" in blocker for blocker in result["deployment_blockers"]))

    def test_strict_json_rejects_duplicate_policy_keys(self):
        with TemporaryDirectory(prefix="swapz-release-json-") as directory:
            path = Path(directory) / "acceptance.json"
            path.write_text(
                '{"schema":"swapz-production-acceptance-v1",'
                '"status":"FROZEN","status":"FROZEN",'
                '"primary_real_swap":{},'
                '"physical_qualification":{}}\n')
            with self.assertRaises(EVALUATOR.EvidenceError):
                EVALUATOR.load_json_strict(path)

    def test_policy_rejects_extra_top_level_fields(self):
        policy = acceptance_policy()
        policy["unreviewed"] = True
        with self.assertRaises(EVALUATOR.EvidenceError):
            EVALUATOR.validate_acceptance_policy(policy, encoded(policy))

    def test_cli_returns_blocked_for_historical_snapshot(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        evidence["snapshot_kind"] = "HISTORICAL"
        with TemporaryDirectory(prefix="swapz-release-cli-") as directory:
            directory = Path(directory)
            report_path = directory / "test_results.json"
            evidence_path = directory / "readiness.json"
            acceptance_path = directory / "acceptance.json"
            report_path.write_bytes(encoded(report))
            evidence_path.write_bytes(encoded(evidence))
            acceptance_path.write_bytes(encoded(policy))
            command = [
                sys.executable,
                str(EVALUATOR_PATH),
                "--source-sha",
                SOURCE,
                "--test-results",
                str(report_path),
                "--evidence",
                str(evidence_path),
                "--acceptance",
                str(acceptance_path),
            ]
            result = subprocess.run(
                command, cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(payload["DEPLOYMENT_PRODUCTION_READY"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
