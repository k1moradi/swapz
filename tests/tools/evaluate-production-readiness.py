#!/usr/bin/env python3
"""Strict private evaluator for swapz production release evidence.

This is test/release plumbing, not an operator interface.  It never performs
privileged actions and never upgrades historical observations into PASS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PARTUUID_RE = re.compile(r"^[0-9a-f][0-9a-f-]*$")

REQUIRED_STAGES = (
    "Build module and helpers",
    "Native and rootless contracts",
    "Kernel warnings W=1",
    "Kernel warnings W=2",
    "Owned RAM smoke + mixed/QD pilot",
)
REQUIRED_CI_WORKFLOWS = (
    "Native kernel-C project-goal regressions",
    "Experimental swapz production C qualification",
    "Systemd and package production-readiness",
)
ARTIFACT_KEYS = (
    "formatter_sha256",
    "module_sha256",
    "oracle_sha256",
)
POLICY_TOP_LEVEL_KEYS = {
    "schema",
    "status",
    "primary_real_swap",
    "physical_qualification",
}


class EvidenceError(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_strict(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, EvidenceError) as exc:
        raise EvidenceError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"{path}: top level must be an object")
    return value, raw


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _valid_hash_mapping(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == set(ARTIFACT_KEYS) and all(
        isinstance(value.get(key), str) and SHA256_RE.fullmatch(value[key])
        for key in ARTIFACT_KEYS)


def _same_hashes(left: Any, right: Any) -> bool:
    return _valid_hash_mapping(left) and _valid_hash_mapping(right) and all(
        left[key] == right[key] for key in ARTIFACT_KEYS)


def _valid_source(value: Any) -> bool:
    return isinstance(value, str) and bool(GIT_SHA_RE.fullmatch(value))


def _normalize_target(value: Any) -> tuple[str, int] | None:
    if not isinstance(value, dict):
        return None
    partuuid = value.get("partuuid")
    size_bytes = value.get("size_bytes")
    if not isinstance(partuuid, str) or partuuid != partuuid.lower():
        return None
    if not PARTUUID_RE.fullmatch(partuuid):
        return None
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool):
        return None
    if size_bytes <= 0:
        return None
    return partuuid, size_bytes


def validate_acceptance_policy(
        policy: dict[str, Any], raw: bytes) -> tuple[str, int]:
    if set(policy) != POLICY_TOP_LEVEL_KEYS:
        raise EvidenceError(
            "production acceptance policy has non-canonical top-level fields")
    if policy.get("schema") != "swapz-production-acceptance-v1":
        raise EvidenceError("unexpected production acceptance schema")
    if policy.get("status") != "FROZEN":
        raise EvidenceError("production acceptance policy is not FROZEN")
    physical = policy.get("physical_qualification")
    if not isinstance(physical, dict) or             physical.get("schema") != "swapz-performance-qualification-v1":
        raise EvidenceError("invalid physical qualification contract")
    acceptance = physical.get("acceptance")
    sustained = acceptance.get("sustained") if isinstance(acceptance, dict) else None
    memory_limit = (
        sustained.get("metadata_and_target_peak_ram_bytes_max")
        if isinstance(sustained, dict) else None)
    if not isinstance(memory_limit, int) or isinstance(memory_limit, bool) or             memory_limit <= 0:
        raise EvidenceError("missing positive production RAM limit")
    return sha256_bytes(raw), memory_limit


def evaluate_release(
        source_sha: str,
        test_results: dict[str, Any],
        test_results_raw: bytes,
        evidence: dict[str, Any],
        policy: dict[str, Any],
        policy_raw: bytes) -> dict[str, Any]:
    code_blockers: list[str] = []
    deployment_blockers: list[str] = []

    def block_code(message: str) -> None:
        if message not in code_blockers:
            code_blockers.append(message)

    def block_deployment(message: str) -> None:
        if message not in deployment_blockers:
            deployment_blockers.append(message)

    if not _valid_source(source_sha):
        block_code("source SHA is not a lowercase 40-hex Git commit")

    try:
        policy_sha256, peak_ram_limit = validate_acceptance_policy(
            policy, policy_raw)
    except EvidenceError as exc:
        policy_sha256 = None
        peak_ram_limit = None
        block_code(str(exc))

    report_hashes = test_results.get("qualified_artifacts")
    if test_results.get("overall") != "PASS":
        block_code("exact-source owner make test is not PASS")
    if test_results.get("source_sha") != source_sha or             test_results.get("tested_commit_sha") != source_sha:
        block_code("owner make test is not bound to the release source")
    if test_results.get("qualification") != "RAM_BACKED_NULL_BLK_ONLY":
        block_code("owner qualification scope is unexpected")
    stages = test_results.get("stages")
    if not isinstance(stages, list):
        block_code("owner qualification stages are missing")
    else:
        by_name = {
            row.get("name"): row.get("status")
            for row in stages if isinstance(row, dict)
        }
        if any(by_name.get(name) != "PASS" for name in REQUIRED_STAGES):
            block_code("one or more mandatory owner qualification stages are not PASS")
    if not isinstance(report_hashes, dict) or             report_hashes.get("status") != "AVAILABLE":
        block_code("qualified artifact hashes are unavailable")
        report_artifacts = None
    else:
        report_artifacts = {
            key: report_hashes.get(key) for key in ARTIFACT_KEYS}
        if not _valid_hash_mapping(report_artifacts):
            block_code("qualified artifact hashes are malformed")

    if evidence.get("schema") != "swapz-production-readiness-v2":
        block_code("release evidence schema is invalid")
    if evidence.get("snapshot_kind") != "CURRENT":
        block_code("release evidence is historical rather than CURRENT")

    repository = evidence.get("repository")
    if not isinstance(repository, dict):
        block_code("release repository identity is missing")
    else:
        synchronized = repository.get("synchronized") is True
        repo_values = (
            repository.get("local_sha"),
            repository.get("origin_main_sha"),
            repository.get("production_source_sha"),
        )
        if repository.get("branch") != "main" or not synchronized or                 any(value != source_sha for value in repo_values):
            block_code("release candidate is not frozen on synchronized main")

    target = _normalize_target(evidence.get("authorized_target"))
    if target is None:
        block_code("canonical authorized target identity is invalid")

    release = evidence.get("release_evidence")
    if not isinstance(release, dict):
        block_code("release evidence records are missing")
        release = {}

    def pass_record(name: str, *, deployment: bool = False) -> dict[str, Any] | None:
        record = release.get(name)
        blocker = block_deployment if deployment else block_code
        if not isinstance(record, dict):
            blocker(f"{name}: evidence record is missing")
            return None
        if record.get("status") != "PASS" or record.get("current") is not True:
            blocker(f"{name}: current PASS evidence is missing")
            return None
        if record.get("source_sha") != source_sha:
            blocker(f"{name}: source binding mismatch")
            return None
        return record

    pass_record("production_source")

    clean = pass_record("clean_build_state")
    if clean is not None and clean.get("clean") is not True:
        block_code("clean_build_state: build is not clean")

    qualified = pass_record("qualified_artifact_hashes")
    if qualified is not None:
        if qualified.get("qualified") is not True or                 not _same_hashes(qualified.get("hashes"), report_artifacts):
            block_code("qualified_artifact_hashes: owner artifact binding mismatch")

    ci = pass_record("required_ci")
    if ci is not None:
        runs = ci.get("runs")
        valid_runs = {}
        if isinstance(runs, list):
            for run in runs:
                if not isinstance(run, dict):
                    continue
                workflow = run.get("workflow")
                if workflow in REQUIRED_CI_WORKFLOWS:
                    valid_runs.setdefault(workflow, []).append(run)
        for workflow in REQUIRED_CI_WORKFLOWS:
            rows = valid_runs.get(workflow, [])
            if len(rows) != 1 or rows[0].get("head_sha") != source_sha or                     rows[0].get("result") != "PASS":
                block_code(f"required_ci: {workflow} is not an exact-source PASS")
        if set(valid_runs) != set(REQUIRED_CI_WORKFLOWS):
            block_code("required_ci: workflow set is incomplete")

    owner = pass_record("exact_source_owner_make_test")
    if owner is not None:
        if owner.get("overall") != "PASS" or                 owner.get("tested_source_sha") != source_sha:
            block_code("exact_source_owner_make_test: report identity mismatch")
        if owner.get("report_sha256") != sha256_bytes(test_results_raw):
            block_code("exact_source_owner_make_test: report digest mismatch")
        if not _same_hashes(owner.get("hashes"), report_artifacts):
            block_code("exact_source_owner_make_test: artifact binding mismatch")

    pass_record("owned_nullblk_qualification")

    critical = pass_record("unresolved_critical_issues")
    if critical is not None and critical.get("count") != 0:
        block_code("unresolved critical correctness issues remain")

    def require_target(name: str, record: dict[str, Any] | None,
                       *, deployment: bool = False) -> None:
        if record is None:
            return
        if target is None or _normalize_target(record.get("target")) != target:
            (block_deployment if deployment else block_code)(
                f"{name}: authorized target binding mismatch")

    def require_policy(name: str, record: dict[str, Any] | None) -> None:
        if record is None:
            return
        if policy_sha256 is None or record.get("policy_sha256") != policy_sha256:
            block_code(f"{name}: production acceptance policy binding mismatch")

    real_swap = pass_record("real_linux_swap")
    require_target("real_linux_swap", real_swap)
    require_policy("real_linux_swap", real_swap)
    if real_swap is not None and not _same_hashes(
            real_swap.get("hashes"), report_artifacts):
        block_code("real_linux_swap: installed artifact binding mismatch")

    capacity = pass_record("maximum_capacity_and_ram")
    require_target("maximum_capacity_and_ram", capacity)
    require_policy("maximum_capacity_and_ram", capacity)
    if capacity is not None:
        logical = capacity.get("logical_capacity_bytes")
        peak = capacity.get("peak_ram_bytes")
        if not isinstance(logical, int) or isinstance(logical, bool) or logical <= 0:
            block_code("maximum_capacity_and_ram: logical capacity is invalid")
        if not isinstance(peak, int) or isinstance(peak, bool) or peak <= 0:
            block_code("maximum_capacity_and_ram: peak RAM is invalid")
        elif peak_ram_limit is not None and peak > peak_ram_limit:
            block_code("maximum_capacity_and_ram: measured peak exceeds frozen limit")

    physical = pass_record("sustained_physical_performance")
    require_target("sustained_physical_performance", physical)
    require_policy("sustained_physical_performance", physical)

    lifecycle = pass_record("lifecycle_deployment_state", deployment=True)
    require_target("lifecycle_deployment_state", lifecycle, deployment=True)

    installed = pass_record("installed_artifact_identity", deployment=True)
    require_target("installed_artifact_identity", installed, deployment=True)
    if installed is not None:
        if installed.get("installed") is not True or not _same_hashes(
                installed.get("hashes"), report_artifacts):
            block_deployment(
                "installed_artifact_identity: installed bytes do not match release artifacts")

    harness = pass_record("cold_boot_harness", deployment=True)
    require_target("cold_boot_harness", harness, deployment=True)
    harness_armed = harness is not None and harness.get("armed") is True
    if harness is not None and not harness_armed:
        block_deployment("cold_boot_harness: harness is not armed")

    code_ready = not code_blockers
    if not code_ready:
        deployment_blockers.insert(
            0, "code production-readiness gates are not all PASS")
    deployment_ready = not deployment_blockers

    reboot = release.get("owner_observed_reboot")
    cold_boot_observed = "NO"
    if isinstance(reboot, dict) and reboot.get("current") is True and             reboot.get("source_sha") == source_sha and             (target is not None and _normalize_target(reboot.get("target")) == target):
        if reboot.get("status") == "PASS" and reboot.get("observed") is True:
            cold_boot_observed = "PASS"
        elif reboot.get("status") == "FAIL":
            cold_boot_observed = "FAIL"

    return {
        "schema": "swapz-production-readiness-evaluation-v1",
        "source_sha": source_sha,
        "production_acceptance_sha256": policy_sha256,
        "CODE_PRODUCTION_READY": "PASS" if code_ready else "BLOCKED",
        "DEPLOYMENT_PRODUCTION_READY": (
            "PASS" if deployment_ready else "BLOCKED"),
        "PRODUCTION_READY_FOR_OWNER_REBOOT": (
            "PASS" if deployment_ready and harness_armed else "NO"),
        "COLD_BOOT_HARNESS": "ARMED" if harness_armed else "NOT_ARMED",
        "COLD_BOOT_OBSERVED": cold_boot_observed,
        "code_blockers": code_blockers,
        "deployment_blockers": deployment_blockers,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate exact-source swapz production release evidence")
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--test-results", type=Path, default=Path("test_results.json"))
    parser.add_argument(
        "--evidence", type=Path,
        default=Path("docs/handoff/production-readiness.json"))
    parser.add_argument(
        "--acceptance", type=Path,
        default=Path("docs/production-acceptance.json"))
    args = parser.parse_args()

    try:
        test_results, test_raw = load_json_strict(args.test_results)
        evidence, _ = load_json_strict(args.evidence)
        policy, policy_raw = load_json_strict(args.acceptance)
        result = evaluate_release(
            args.source_sha, test_results, test_raw, evidence, policy, policy_raw)
    except (OSError, EvidenceError) as exc:
        result = {
            "schema": "swapz-production-readiness-evaluation-v1",
            "source_sha": args.source_sha,
            "CODE_PRODUCTION_READY": "BLOCKED",
            "DEPLOYMENT_PRODUCTION_READY": "BLOCKED",
            "PRODUCTION_READY_FOR_OWNER_REBOOT": "NO",
            "COLD_BOOT_HARNESS": "NOT_ARMED",
            "COLD_BOOT_OBSERVED": "NO",
            "code_blockers": [str(exc)],
            "deployment_blockers": [
                "code production-readiness gates are not all PASS"],
        }

    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["CODE_PRODUCTION_READY"] == "PASS" and         result["DEPLOYMENT_PRODUCTION_READY"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
