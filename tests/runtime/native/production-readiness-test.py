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
HOST_ID = "9" * 64
KERNEL_RELEASE = "6.8.0-48-generic"
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
            "cycles": 2,
            "workload_mib": 384,
            "resident_mib": 128,
            "swap_limit_mib": 384,
            "timeout_seconds": 240,
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
        "kernel_release": KERNEL_RELEASE,
        "host_identity": {
            "schema": "swapz-host-v1",
            "architecture": "x86_64",
            "id_sha256": HOST_ID,
        },
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


def real_swap_result(report_raw, policy_raw):
    policy = json.loads(policy_raw)
    primary = policy["primary_real_swap"]
    return {
        "schema": "swapz-primary-real-swap-v1",
        "status": "PASS",
        "source_sha": SOURCE,
        "acceptance_manifest_sha256": hashlib.sha256(policy_raw).hexdigest(),
        "helper_sha256": hashlib.sha256(
            EVALUATOR.REAL_SWAP_HELPER.read_bytes()).hexdigest(),
        "oracle_sha256": hashlib.sha256(
            EVALUATOR.REAL_SWAP_ORACLE.read_bytes()).hexdigest(),
        "qualification_report_sha256": hashlib.sha256(report_raw).hexdigest(),
        "qualified_installed_artifacts": dict(ARTIFACTS),
        "physical_execution_control_sha256": "4" * 64,
        "partuuid": TARGET["partuuid"],
        "target_device": "8:1",
        "cycles_requested": primary["cycles"],
        "cycles_passed": primary["cycles"],
        "workload_mib": primary["workload_mib"],
        "resident_limit_mib": primary["resident_mib"],
        "swap_limit_mib": primary["swap_limit_mib"],
        "timeout_seconds": primary["timeout_seconds"],
        "concurrent_oracles": 2,
        "reuse_rounds_per_cycle": 2,
        "evidence_path": "/var/lib/swapz/physical-recovery/test.json",
        "cycles": [
            {
                "run_id": f"{index + 1:032x}",
                "linux_swap_uuid":
                    f"00000000-0000-0000-0000-{index + 1:012x}",
                "durable_final_stage": "COMPLETE",
            }
            for index in range(primary["cycles"])
        ],
    }


def real_swap_evidence(report_raw, policy_raw):
    result = real_swap_result(report_raw, policy_raw)
    envelope_keys = (
        "source_sha", "acceptance_manifest_sha256",
        "qualification_report_sha256", "helper_sha256", "oracle_sha256",
        "qualified_installed_artifacts", "physical_execution_control_sha256",
        "partuuid", "cycles_requested", "workload_mib",
        "resident_limit_mib", "swap_limit_mib", "timeout_seconds",
        "concurrent_oracles", "reuse_rounds_per_cycle", "cycles",
    )
    return {
        "schema": "swapz-primary-real-swap-evidence-v1",
        "attempt_id": "f" * 32,
        "status": "PASS",
        "reason": None,
        "phase": "COMPLETE",
        "started_unix_ns": 1,
        "updated_unix_ns": 2,
        **{key: copy.deepcopy(result[key]) for key in envelope_keys},
        "result": result,
    }


def current_evidence(report_raw, policy_raw, physical_raw=None):
    policy_digest = hashlib.sha256(policy_raw).hexdigest()
    report_digest = hashlib.sha256(report_raw).hexdigest()
    if physical_raw is None:
        physical_raw = encoded(real_swap_evidence(report_raw, policy_raw))
    return {
        "schema": "swapz-production-readiness-v2",
        "snapshot_kind": "CURRENT",
        "host": {
            "architecture": "x86_64",
            "kernel_release": KERNEL_RELEASE,
            "page_size_bytes": 4096,
        },
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
            "owned_nullblk_qualification": pass_record(
                overall="PASS", evidence_sha256="5" * 64,
                hashes=dict(ARTIFACTS)),
            "unresolved_critical_issues": pass_record(count=0),
            "real_linux_swap": pass_record(
                policy_sha256=policy_digest,
                target=dict(TARGET),
                hashes=dict(ARTIFACTS),
                evidence_sha256=hashlib.sha256(physical_raw).hexdigest()),
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


def evaluate(report=None, evidence=None, policy=None, physical=None):
    report = owner_report() if report is None else report
    policy = acceptance_policy() if policy is None else policy
    report_raw = encoded(report)
    policy_raw = encoded(policy)
    physical = (
        real_swap_evidence(report_raw, policy_raw)
        if physical is None else physical)
    physical_raw = encoded(physical)
    if evidence is None:
        evidence = current_evidence(report_raw, policy_raw, physical_raw)
    return EVALUATOR.evaluate_release(
        SOURCE, report, report_raw, evidence, policy, policy_raw,
        physical, physical_raw)


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

    def test_release_kernel_must_match_owner_qualification(self):
        report = owner_report()
        report["kernel_release"] = "6.8.0-49-generic"
        result = evaluate(report=report)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertIn(
            "release host kernel does not match owner qualification",
            result["code_blockers"])

    def test_release_host_platform_is_fail_closed(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        evidence["host"]["page_size_bytes"] = 65536
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertIn(
            "release host page size is unsupported", result["code_blockers"])

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

    def test_owned_nullblk_pass_requires_lifecycle_result_digest_and_production_bytes(self):
        report = owner_report()
        policy = acceptance_policy()
        evidence = current_evidence(encoded(report), encoded(policy))
        nullblk = evidence["release_evidence"]["owned_nullblk_qualification"]

        nullblk["evidence_sha256"] = "not-a-digest"
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "owned_nullblk_qualification: evidence digest is invalid" in blocker
            for blocker in result["code_blockers"]))

        nullblk["evidence_sha256"] = "5" * 64
        nullblk["hashes"]["formatter_sha256"] = "4" * 64
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "PASS", result)

        nullblk["hashes"]["module_sha256"] = "6" * 64
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "owned_nullblk_qualification: module/oracle artifact binding mismatch"
            in blocker for blocker in result["code_blockers"]))

        nullblk["hashes"] = dict(ARTIFACTS)
        nullblk["overall"] = "FAIL"
        result = evaluate(report, evidence, policy)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "owned_nullblk_qualification: lifecycle result is not PASS" in blocker
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

    def test_real_swap_requires_persistent_evidence_and_exact_digest_binding(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        raw = encoded(physical)
        evidence = current_evidence(report_raw, policy_raw, raw)

        missing = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw)
        self.assertEqual(missing["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "persistent physical evidence is missing" in blocker
            for blocker in missing["code_blockers"]))

        evidence["release_evidence"]["real_linux_swap"]["evidence_sha256"] = (
            "9" * 64)
        mismatched = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, raw)
        self.assertEqual(mismatched["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "persistent evidence digest binding mismatch" in blocker
            for blocker in mismatched["code_blockers"]))

    def test_real_swap_persistent_evidence_binds_nested_result_and_helpers(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        for name, key, value in (
                ("execution-control", "physical_execution_control_sha256", "bad"),
                ("helper", "helper_sha256", "5" * 64),
                ("oracle", "oracle_sha256", "6" * 64),
                ("cycles", "cycles_passed", 1),
                ("owner-report", "qualification_report_sha256", "7" * 64)):
            with self.subTest(name=name):
                physical = real_swap_evidence(report_raw, policy_raw)
                physical["result"][key] = value
                raw = encoded(physical)
                evidence = current_evidence(report_raw, policy_raw, raw)
                result = EVALUATOR.evaluate_release(
                    SOURCE, report, report_raw, evidence, policy, policy_raw,
                    physical, raw)
                self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")

    def test_real_swap_persistent_evidence_requires_fresh_ids_and_matching_envelope(self):
        report = owner_report()
        policy = acceptance_policy()
        report_raw = encoded(report)
        policy_raw = encoded(policy)
        physical = real_swap_evidence(report_raw, policy_raw)
        nested = physical["result"]
        nested["cycles"][1]["run_id"] = nested["cycles"][0]["run_id"]
        nested["cycles"][1]["linux_swap_uuid"] = nested["cycles"][0][
            "linux_swap_uuid"]
        physical["cycles"] = copy.deepcopy(nested["cycles"])
        raw = encoded(physical)
        evidence = current_evidence(report_raw, policy_raw, raw)
        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, raw)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "reused a transaction run_id" in blocker
            for blocker in result["code_blockers"]))
        self.assertTrue(any(
            "reused a Linux swap UUID" in blocker
            for blocker in result["code_blockers"]))

        physical = real_swap_evidence(report_raw, policy_raw)
        physical["workload_mib"] += 1
        raw = encoded(physical)
        evidence = current_evidence(report_raw, policy_raw, raw)
        result = EVALUATOR.evaluate_release(
            SOURCE, report, report_raw, evidence, policy, policy_raw,
            physical, raw)
        self.assertEqual(result["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertTrue(any(
            "persistent evidence/result mismatch for workload_mib" in blocker
            for blocker in result["code_blockers"]))

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
