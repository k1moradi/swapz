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

ROOT = Path(__file__).resolve().parents[2]
REAL_SWAP_HELPER = ROOT / "tests/tools/qualify-primary-real-swap.py"
REAL_SWAP_ORACLE = ROOT / "tests/tools/primary-real-swap-oracle.py"
PHYSICAL_CAMPAIGN_SEALER = (
    ROOT / "tests/runtime/benchmark/physical-campaign-evidence.py")
PHYSICAL_CAMPAIGN_EVALUATOR = (
    ROOT / "tests/runtime/benchmark/qualification.py")
PHYSICAL_CAMPAIGN_AMENDMENT = (
    ROOT / "tests/runtime/benchmark/physical-qualification-amendment-v2.json")

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PARTUUID_RE = re.compile(r"^[0-9a-f]+(?:-[0-9a-f]+)*$")
MAJOR_MINOR_RE = re.compile(r"^[0-9]+:[0-9]+$")
KERNEL_RELEASE_RE = re.compile(r"^[A-Za-z0-9._+-]{1,127}$")
BOOT_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")
ENV_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")

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
COLD_BOOT_REPORT_KEYS = {
    "schema", "status", "cold_boot_observed", "boot_id", "armed_boot_id",
    "kernel_release", "selected_partuuid", "selected_target_major_minor",
    "selected_target_size_bytes", "selected_target_parent",
    "selected_target_model", "selected_target_serial", "selected_target_wwn",
    "selected_target_transport", "selected_target_removable",
    "module_artifact", "module_artifact_sha256", "module_build_source_sha",
    "module_build_source_clean", "loaded_module_build_source_sha",
    "loaded_module_build_source_clean", "active_transaction_run_id",
    "expected_dm_uuid", "dm_uuid", "dm_table", "dm_logical_sectors",
    "expected_dm_logical_sectors", "dm_logical_bytes", "dm_status_file",
    "swap_total_entries", "swap_mapper_entries", "swap_path", "swap_type",
    "swap_size_kib", "swap_used_kib", "swap_priority",
    "mapper_service_active_state", "mapper_service_sub_state",
    "mapper_service_result", "swap_unit_active_state", "swap_unit_sub_state",
    "swap_unit_result", "swapz_failed", "swapz_error", "swapz_flush_err",
    "swapz_segment_discards_failed", "swapz_upper_write_completed_err",
    "swapz_endio_write_seen_err", "swapz_endio_write_forced_err",
    "kernel_error_count", "kernel_error_log", "failure_reasons",
    "incomplete_reasons",
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


def parse_env_strict(raw: bytes) -> dict[str, str]:
    """Parse the verifier's newline-delimited key=value evidence fail closed."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvidenceError(f"cold-boot evidence is not UTF-8: {exc}") from exc
    if not text.endswith("\n"):
        raise EvidenceError("cold-boot evidence is not newline terminated")
    result: dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line or "=" not in line:
            raise EvidenceError(
                f"cold-boot evidence line {line_number} is malformed")
        key, value = line.split("=", 1)
        if not ENV_KEY_RE.fullmatch(key):
            raise EvidenceError(
                f"cold-boot evidence line {line_number} has invalid key")
        if key in result:
            raise EvidenceError(f"duplicate cold-boot evidence key: {key}")
        if any(ord(character) < 0x20 for character in value):
            raise EvidenceError(
                f"cold-boot evidence line {line_number} has control characters")
        result[key] = value
    return result


def load_env_strict(path: Path) -> tuple[dict[str, str], bytes]:
    raw = path.read_bytes()
    return parse_env_strict(raw), raw


def maximum_logical_sectors(device_bytes: Any) -> int | None:
    """Mirror the production boot/manager admission rule without device I/O."""
    if (
            type(device_bytes) is not int or device_bytes <= 4096 or
            device_bytes % 4096):
        return None
    blocks = device_bytes // 4096
    physical_blocks = ((blocks - 1) // 256) * 256
    if physical_blocks <= 0 or physical_blocks > 0xFFFFFFFF:
        return None

    low = 0
    high = physical_blocks
    while low < high:
        candidate = low + (high - low + 1) // 2
        reserve = max((candidate + 7) // 8, 512)
        fits = False
        if reserve < physical_blocks:
            data_blocks = ((physical_blocks - reserve) // 256) * 256
            fits = data_blocks >= 256 and candidate <= data_blocks - 256
        if fits:
            low = candidate
        else:
            high = candidate - 1
    return low * 8 if low else None


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
    if (
            not 8 <= len(partuuid) <= 64 or
            not PARTUUID_RE.fullmatch(partuuid) or
            sum(ch != "-" for ch in partuuid) < 8):
        return None
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool):
        return None
    if size_bytes <= 0:
        return None
    return partuuid, size_bytes


def _normalize_campaign_target(value: Any) -> tuple[str, int] | None:
    if not isinstance(value, dict):
        return None
    return _normalize_target({
        "partuuid": value.get("partuuid"),
        "size_bytes": value.get("device_bytes"),
    })


def _valid_campaign_artifact(value: Any) -> bool:
    return (
        isinstance(value, dict) and
        isinstance(value.get("name"), str) and bool(value["name"]) and
        isinstance(value.get("size_bytes"), int) and
        not isinstance(value.get("size_bytes"), bool) and
        value["size_bytes"] > 0 and
        isinstance(value.get("sha256"), str) and
        bool(SHA256_RE.fullmatch(value["sha256"]))
    )


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


def validate_real_swap_result(
        result: dict[str, Any],
        source_sha: str,
        test_results_raw: bytes,
        policy: dict[str, Any],
        policy_sha256: str | None,
        report_artifacts: dict[str, Any] | None,
        target: tuple[str, int] | None) -> list[str]:
    issues: list[str] = []

    def reject(message: str) -> None:
        if message not in issues:
            issues.append(message)

    if result.get("schema") != "swapz-primary-real-swap-v1":
        reject("nested result schema is invalid")
    if result.get("status") != "PASS":
        reject("nested result is not PASS")
    if result.get("source_sha") != source_sha:
        reject("nested result source binding mismatch")
    if policy_sha256 is None or result.get(
            "acceptance_manifest_sha256") != policy_sha256:
        reject("nested result production policy binding mismatch")
    if result.get("qualification_report_sha256") != sha256_bytes(
            test_results_raw):
        reject("nested result owner-report digest mismatch")
    if not _same_hashes(
            result.get("qualified_installed_artifacts"), report_artifacts):
        reject("nested result installed artifact binding mismatch")

    execution_control = result.get("physical_execution_control_sha256")
    if not isinstance(execution_control, str) or not SHA256_RE.fullmatch(
            execution_control):
        reject("nested result private execution-control digest is invalid")
    elif (
            isinstance(report_artifacts, dict) and
            execution_control == report_artifacts.get("formatter_sha256")):
        reject(
            "nested result private execution control aliases installed formatter")
    if result.get("installed_control_privileged_execution_enabled") is not False:
        reject(
            "nested result installed production control was not runtime-locked")

    try:
        expected_helper = sha256_bytes(REAL_SWAP_HELPER.read_bytes())
        expected_oracle = sha256_bytes(REAL_SWAP_ORACLE.read_bytes())
    except OSError:
        expected_helper = None
        expected_oracle = None
        reject("current physical helper/oracle bytes are unreadable")
    if expected_helper is not None and result.get("helper_sha256") != expected_helper:
        reject("nested result helper digest differs from current source")
    if expected_oracle is not None and result.get("oracle_sha256") != expected_oracle:
        reject("nested result byte-oracle digest differs from current source")

    primary_policy = policy.get("primary_real_swap")
    if not isinstance(primary_policy, dict):
        reject("frozen primary real-swap policy is missing")
        primary_policy = {}
    for result_key, policy_key in (
            ("cycles_requested", "cycles"),
            ("workload_mib", "workload_mib"),
            ("resident_limit_mib", "resident_mib"),
            ("swap_limit_mib", "swap_limit_mib"),
            ("timeout_seconds", "timeout_seconds")):
        expected = primary_policy.get(policy_key)
        if not isinstance(expected, int) or isinstance(expected, bool) or expected <= 0:
            reject(f"frozen primary real-swap policy {policy_key} is invalid")
        elif result.get(result_key) != expected:
            reject(f"nested result {result_key} differs from frozen policy")

    expected_cycles = primary_policy.get("cycles")
    if isinstance(expected_cycles, int) and not isinstance(expected_cycles, bool):
        if result.get("cycles_passed") != expected_cycles:
            reject("nested result did not pass every required real-swap cycle")
    if result.get("concurrent_oracles") != 2:
        reject("nested result did not use two concurrent byte oracles")
    if result.get("reuse_rounds_per_cycle") != 2:
        reject("nested result did not complete two reuse rounds per cycle")
    if target is None or result.get("partuuid") != target[0] or \
            result.get("target_size_bytes") != target[1]:
        reject("nested result authorized target identity mismatch")
    target_device = result.get("target_device")
    if not isinstance(target_device, str) or not MAJOR_MINOR_RE.fullmatch(
            target_device):
        reject("nested result target device identity is invalid")

    cycles = result.get("cycles")
    if not isinstance(cycles, list) or (
            isinstance(expected_cycles, int) and len(cycles) != expected_cycles):
        reject("nested result cycle evidence count is invalid")
    else:
        run_ids: set[str] = set()
        swap_uuids: set[str] = set()
        run_id_re = re.compile(r"^[0-9a-f]{32}$")
        swap_uuid_re = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{12}$")
        for cycle in cycles:
            if not isinstance(cycle, dict):
                reject("nested result contains a malformed cycle")
                continue
            run_id = cycle.get("run_id")
            swap_uuid = cycle.get("linux_swap_uuid")
            if not isinstance(run_id, str) or not run_id_re.fullmatch(run_id):
                reject("nested result cycle run_id is malformed")
            elif run_id in run_ids:
                reject("nested result reused a transaction run_id")
            else:
                run_ids.add(run_id)
            if not isinstance(swap_uuid, str) or not swap_uuid_re.fullmatch(
                    swap_uuid):
                reject("nested result Linux swap UUID is malformed")
            elif swap_uuid in swap_uuids:
                reject("nested result reused a Linux swap UUID")
            else:
                swap_uuids.add(swap_uuid)
            if cycle.get("durable_final_stage") != "COMPLETE":
                reject("nested result cycle did not end in durable COMPLETE")
    return issues


def validate_real_swap_evidence(
        physical_evidence: dict[str, Any],
        raw: bytes,
        source_sha: str,
        test_results_raw: bytes,
        policy: dict[str, Any],
        policy_sha256: str | None,
        report_artifacts: dict[str, Any] | None,
        target: tuple[str, int] | None) -> list[str]:
    issues: list[str] = []

    def reject(message: str) -> None:
        if message not in issues:
            issues.append(message)

    if physical_evidence.get("schema") != "swapz-primary-real-swap-evidence-v1":
        reject("persistent evidence schema is invalid")
    if physical_evidence.get("status") != "PASS":
        reject("persistent evidence disposition is not PASS")
    if physical_evidence.get("phase") != "COMPLETE":
        reject("persistent evidence is not COMPLETE")
    attempt_id = physical_evidence.get("attempt_id")
    if not isinstance(attempt_id, str) or not re.fullmatch(
            r"[0-9a-f]{32}", attempt_id):
        reject("persistent evidence attempt ID is malformed")
    if not raw:
        reject("persistent evidence bytes are empty")

    result = physical_evidence.get("result")
    if not isinstance(result, dict):
        reject("persistent evidence final result is missing")
        return issues
    for issue in validate_real_swap_result(
            result, source_sha, test_results_raw, policy, policy_sha256,
            report_artifacts, target):
        reject(issue)

    for key in (
            "source_sha", "acceptance_manifest_sha256",
            "qualification_report_sha256", "helper_sha256", "oracle_sha256",
            "qualified_installed_artifacts", "physical_execution_control_sha256",
            "installed_control_privileged_execution_enabled",
            "partuuid", "target_size_bytes", "target_device",
            "cycles_requested", "workload_mib",
            "resident_limit_mib", "swap_limit_mib", "timeout_seconds",
            "concurrent_oracles", "reuse_rounds_per_cycle", "cycles"):
        if physical_evidence.get(key) != result.get(key):
            reject(f"persistent evidence/result mismatch for {key}")
    return issues


def validate_physical_campaign_evidence(
        campaign: dict[str, Any],
        raw: bytes,
        source_sha: str,
        policy_sha256: str | None,
        target: tuple[str, int] | None) -> list[str]:
    issues: list[str] = []

    def reject(message: str) -> None:
        if message not in issues:
            issues.append(message)

    if campaign.get("schema") != "swapz-performance-campaign-evidence-v1":
        reject("sealed campaign schema is invalid")
    if not raw:
        reject("sealed campaign evidence bytes are empty")
    if campaign.get("source_sha") != source_sha:
        reject("sealed campaign source binding mismatch")

    source_tree_sha = campaign.get("source_tree_sha")
    if (
            not isinstance(source_tree_sha, str) or
            not GIT_SHA_RE.fullmatch(source_tree_sha)):
        reject("sealed campaign source tree SHA is invalid")
    if (
            campaign.get("campaign_source_sha") != source_sha or
            campaign.get("pair_source_shas") != [source_sha] or
            campaign.get("source_consistent") is not True):
        reject("sealed campaign pair sources are not exact and consistent")
    if (
            campaign.get("campaign_status") != "PASS" or
            campaign.get("qualification_status") != "PASS"):
        reject("sealed campaign qualification is not PASS")
    if campaign.get("evaluation_protocol") != "v2":
        reject("sealed campaign did not use the required v2 protocol")
    if (
            target is None or
            _normalize_campaign_target(campaign.get("target")) != target):
        reject("sealed campaign authorized target binding mismatch")

    target_binding = campaign.get("qualification_target_binding")
    if (
            not isinstance(target_binding, dict) or
            target_binding.get("status") != "MATCH" or
            target_binding.get("consistent") is not True):
        reject("sealed campaign qualification target binding is not MATCH")
    else:
        expected = target_binding.get("expected")
        observed = target_binding.get("observed")
        expected_target = None
        expected_lower = None
        if isinstance(expected, dict):
            expected_target = _normalize_target({
                "partuuid": expected.get("physical_partuuid"),
                "size_bytes": expected.get("physical_device_bytes"),
            })
            expected_lower = expected.get("lower_major_minor")
        if (
                expected_target != target or
                not isinstance(expected_lower, str) or
                not MAJOR_MINOR_RE.fullmatch(expected_lower)):
            reject("sealed campaign qualification target binding is malformed")
        if observed != expected:
            reject("sealed campaign qualification target observations disagree")

    capacity_and_ram = campaign.get("capacity_and_ram")
    if not isinstance(capacity_and_ram, dict):
        reject("sealed campaign capacity/RAM evidence is missing")
    else:
        page_bytes = capacity_and_ram.get("page_bytes")
        logical_pages = capacity_and_ram.get("logical_pages")
        logical_capacity_bytes = capacity_and_ram.get(
            "logical_capacity_bytes")
        peak_ram_bytes = capacity_and_ram.get("peak_ram_bytes")
        if (
                page_bytes != 4096 or
                type(logical_pages) is not int or logical_pages <= 0 or
                type(logical_capacity_bytes) is not int or
                logical_capacity_bytes <= 0 or
                logical_capacity_bytes != logical_pages * 4096 or
                target is None or logical_capacity_bytes > target[1] or
                type(peak_ram_bytes) is not int or peak_ram_bytes <= 0):
            reject("sealed campaign capacity/RAM evidence is invalid")

    stability = campaign.get("host_stability")
    if not isinstance(stability, dict) or stability.get("status") != "STABLE":
        reject("sealed campaign host stability is not STABLE")
    else:
        checks = stability.get("checks")
        failed = stability.get("failed_checks")
        if (
                not isinstance(checks, dict) or not checks or
                any(value is not True for value in checks.values())):
            reject("sealed campaign host stability checks are incomplete")
        if failed != []:
            reject("sealed campaign host stability records failed checks")

    boundaries = campaign.get("admitted_device_boundary")
    if not isinstance(boundaries, dict):
        reject("sealed campaign admitted-device boundary is missing")
    else:
        for phase in ("before", "after"):
            boundary = boundaries.get(phase)
            if (
                    not isinstance(boundary, dict) or
                    boundary.get("quiescent") is not True):
                reject(
                    f"sealed campaign target was not quiescent {phase} campaign")

    policy = campaign.get("policy")
    if not isinstance(policy, dict):
        reject("sealed campaign policy provenance is missing")
    else:
        acceptance = policy.get("acceptance_manifest")
        if (
                policy_sha256 is None or
                not isinstance(acceptance, dict) or
                acceptance.get("sha256") != policy_sha256):
            reject("sealed campaign production policy binding mismatch")
        expected_files = (
            ("prospective_amendment", PHYSICAL_CAMPAIGN_AMENDMENT),
            ("evaluator", PHYSICAL_CAMPAIGN_EVALUATOR),
            ("evidence_sealer", PHYSICAL_CAMPAIGN_SEALER),
        )
        for name, path in expected_files:
            record = policy.get(name)
            try:
                expected_sha256 = sha256_bytes(path.read_bytes())
            except OSError:
                expected_sha256 = None
                reject(f"current physical campaign {name} bytes are unreadable")
            if (
                    expected_sha256 is not None and
                    (not isinstance(record, dict) or
                     record.get("sha256") != expected_sha256)):
                reject(
                    f"sealed campaign {name} digest differs from current source")

    artifacts = campaign.get("artifacts")
    if not isinstance(artifacts, dict):
        reject("sealed campaign artifact manifest is missing")
    else:
        for name in ("host_before", "host_after", "qualification_summary"):
            if not _valid_campaign_artifact(artifacts.get(name)):
                reject(f"sealed campaign {name} artifact is invalid")
        pairs = artifacts.get("pairs")
        record_count = campaign.get("record_count")
        if not isinstance(pairs, list) or not pairs:
            reject("sealed campaign pair artifact list is empty")
        elif (
                not isinstance(record_count, int) or
                isinstance(record_count, bool) or
                record_count != len(pairs)):
            reject("sealed campaign pair artifact count mismatch")
        else:
            for pair in pairs:
                if not _valid_campaign_artifact(pair):
                    reject("sealed campaign contains an invalid pair artifact")
                    break
                status = pair.get("status")
                excluded = pair.get("excluded")
                if (
                        status not in ("PASS", "EXCLUDED") or
                        not isinstance(excluded, bool) or
                        excluded != (status == "EXCLUDED")):
                    reject(
                        "sealed campaign pair disposition is inconsistent")
                    break
    return issues


def validate_cold_boot_evidence(
        cold_boot: dict[str, str],
        source_sha: str,
        target: tuple[str, int] | None,
        report_artifacts: dict[str, Any] | None,
        owner_kernel_release: Any) -> list[str]:
    """Validate the persisted boot verifier report behind a claimed reboot PASS."""
    issues: list[str] = []

    def reject(message: str) -> None:
        if message not in issues:
            issues.append(message)

    if set(cold_boot) != COLD_BOOT_REPORT_KEYS:
        reject("persistent cold-boot report field set is non-canonical")
        return issues


    if cold_boot["schema"] != "swapz-primary-cold-boot-v1":
        reject("persistent cold-boot report schema is invalid")
    if cold_boot["status"] != "PASS" or cold_boot["cold_boot_observed"] != "yes":
        reject("persistent cold-boot report is not an observed PASS")
    if (
            not BOOT_ID_RE.fullmatch(cold_boot["boot_id"]) or
            not BOOT_ID_RE.fullmatch(cold_boot["armed_boot_id"]) or
            cold_boot["boot_id"] == cold_boot["armed_boot_id"]):
        reject("persistent cold-boot boot identity is invalid")
    if (
            not isinstance(owner_kernel_release, str) or
            cold_boot["kernel_release"] != owner_kernel_release):
        reject("persistent cold-boot kernel differs from owner qualification")
    if target is None:
        reject("persistent cold-boot authorized target is unavailable")
    else:
        try:
            selected_size = int(cold_boot["selected_target_size_bytes"], 10)
        except ValueError:
            selected_size = -1
        if (
                cold_boot["selected_partuuid"] != target[0] or
                selected_size != target[1]):
            reject("persistent cold-boot authorized target identity mismatch")
    if not MAJOR_MINOR_RE.fullmatch(cold_boot["selected_target_major_minor"]):
        reject("persistent cold-boot target device identity is invalid")
    if (
            cold_boot["selected_target_removable"] != "1" or
            not re.fullmatch(r"[A-Za-z0-9._-]+",
                             cold_boot["selected_target_parent"]) or
            (cold_boot["selected_target_serial"] == "unavailable" and
             cold_boot["selected_target_wwn"] == "unavailable")):
        reject("persistent cold-boot removable parent identity is invalid")

    module_hash = (
        report_artifacts.get("module_sha256")
        if isinstance(report_artifacts, dict) else None)
    if (
            not isinstance(module_hash, str) or
            cold_boot["module_artifact_sha256"] != module_hash):
        reject("persistent cold-boot module artifact binding mismatch")
    if (
            cold_boot["module_build_source_sha"] != source_sha or
            cold_boot["module_build_source_clean"] != "1" or
            cold_boot["loaded_module_build_source_sha"] != source_sha or
            cold_boot["loaded_module_build_source_clean"] != "1"):
        reject("persistent cold-boot module source binding is invalid")

    run_id = cold_boot["active_transaction_run_id"]
    expected_uuid = f"SWAPZ-PRIMARY-{run_id}"
    if (
            not RUN_ID_RE.fullmatch(run_id) or
            cold_boot["expected_dm_uuid"] != expected_uuid or
            cold_boot["dm_uuid"] != expected_uuid):
        reject("persistent cold-boot mapper transaction identity is invalid")

    try:
        logical_sectors = int(cold_boot["dm_logical_sectors"], 10)
        expected_sectors = int(cold_boot["expected_dm_logical_sectors"], 10)
        logical_bytes = int(cold_boot["dm_logical_bytes"], 10)
        swap_size_kib = int(cold_boot["swap_size_kib"], 10)
    except ValueError:
        logical_sectors = expected_sectors = logical_bytes = swap_size_kib = -1
    authorized_sectors = (
        maximum_logical_sectors(target[1]) if target is not None else None)
    if (
            logical_sectors <= 0 or logical_sectors != expected_sectors or
            logical_bytes != logical_sectors * 512 or
            authorized_sectors is None or
            expected_sectors != authorized_sectors):
        reject(
            "persistent cold-boot mapper capacity differs from authorized target")
    table_fields = cold_boot["dm_table"].split(" ")
    expected_table = [
        "0", str(authorized_sectors), "swapz",
        cold_boot["selected_target_major_minor"],
        "0", "64", "0", "2", "0", "1", "0", "0",
    ]
    if table_fields != expected_table:
        reject("persistent cold-boot mapper table is inconsistent")
    if (
            cold_boot["swap_mapper_entries"] != "1" or
            cold_boot["swap_type"] != "partition" or
            cold_boot["swap_priority"] != "-1" or
            logical_bytes <= 4096 or
            swap_size_kib != logical_bytes // 1024 - 4):
        reject("persistent cold-boot active swap evidence is inconsistent")
    if (
            cold_boot["mapper_service_active_state"] != "active" or
            cold_boot["mapper_service_result"] != "success" or
            cold_boot["swap_unit_active_state"] != "active" or
            cold_boot["swap_unit_result"] != "success"):
        reject("persistent cold-boot service state is not healthy")

    zero_fields = (
        "swapz_failed", "swapz_error", "swapz_flush_err",
        "swapz_segment_discards_failed", "swapz_upper_write_completed_err",
        "swapz_endio_write_seen_err", "swapz_endio_write_forced_err",
        "kernel_error_count",
    )
    if any(cold_boot[field] != "0" for field in zero_fields):
        reject("persistent cold-boot report contains runtime error evidence")
    if cold_boot["failure_reasons"] or cold_boot["incomplete_reasons"]:
        reject("persistent cold-boot report contains failure/incomplete reasons")
    return issues


def evaluate_release(
        source_sha: str,
        test_results: dict[str, Any],
        test_results_raw: bytes,
        evidence: dict[str, Any],
        policy: dict[str, Any],
        policy_raw: bytes,
        real_swap_evidence: dict[str, Any] | None = None,
        real_swap_evidence_raw: bytes | None = None,
        physical_campaign_evidence: dict[str, Any] | None = None,
        physical_campaign_evidence_raw: bytes | None = None,
        cold_boot_evidence: dict[str, str] | None = None,
        cold_boot_evidence_raw: bytes | None = None) -> dict[str, Any]:
    code_blockers: list[str] = []
    deployment_blockers: list[str] = []
    cold_boot_blockers: list[str] = []

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
    owner_host = test_results.get("host_identity")
    owner_kernel_release = test_results.get("kernel_release")
    if not (
            isinstance(owner_host, dict) and
            owner_host.get("schema") == "swapz-host-v1" and
            owner_host.get("architecture") == "x86_64" and
            isinstance(owner_host.get("id_sha256"), str) and
            SHA256_RE.fullmatch(owner_host["id_sha256"])):
        block_code("owner qualification host identity is invalid")
    if not (
            isinstance(owner_kernel_release, str) and
            KERNEL_RELEASE_RE.fullmatch(owner_kernel_release)):
        block_code("owner qualification kernel release is invalid")
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
        stage_rows = [row for row in stages if isinstance(row, dict)]
        stage_names = [row.get("name") for row in stage_rows]
        if (
                len(stage_rows) != len(REQUIRED_STAGES) or
                stage_names != list(REQUIRED_STAGES)):
            block_code(
                "owner qualification stage set/order is not exactly canonical")
        elif any(
                row.get("status") != "PASS" or
                type(row.get("exit_code")) is not int or
                row.get("exit_code") != 0
                for row in stage_rows):
            block_code(
                "one or more mandatory owner qualification stages are not "
                "PASS with exit code 0")
    if not isinstance(report_hashes, dict) or             report_hashes.get("status") != "AVAILABLE":
        block_code("qualified artifact hashes are unavailable")
        report_artifacts = None
    else:
        expected_artifact_fields = {"status", *ARTIFACT_KEYS}
        if set(report_hashes) != expected_artifact_fields:
            block_code("qualified artifact hash record is non-canonical")
        report_artifacts = {
            key: report_hashes.get(key) for key in ARTIFACT_KEYS}
        if not _valid_hash_mapping(report_artifacts):
            block_code("qualified artifact hashes are malformed")

    if evidence.get("schema") != "swapz-production-readiness-v2":
        block_code("release evidence schema is invalid")
    if evidence.get("snapshot_kind") != "CURRENT":
        block_code("release evidence is historical rather than CURRENT")

    release_host = evidence.get("host")
    if not isinstance(release_host, dict):
        block_code("release host identity is missing")
    else:
        release_kernel = release_host.get("kernel_release")
        release_architecture = release_host.get("architecture")
        if release_architecture != "x86_64":
            block_code("release host architecture is unsupported")
        if not (
                isinstance(release_kernel, str) and
                KERNEL_RELEASE_RE.fullmatch(release_kernel)):
            block_code("release host kernel release is invalid")
        elif (isinstance(owner_kernel_release, str) and
              KERNEL_RELEASE_RE.fullmatch(owner_kernel_release) and
              release_kernel != owner_kernel_release):
            block_code("release host kernel does not match owner qualification")
        if release_host.get("page_size_bytes") != 4096:
            block_code("release host page size is unsupported")

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

    owned_nullblk = pass_record("owned_nullblk_qualification")
    if owned_nullblk is not None:
        if owned_nullblk.get("overall") != "PASS":
            block_code(
                "owned_nullblk_qualification: lifecycle result is not PASS")
        evidence_sha256 = owned_nullblk.get("evidence_sha256")
        if not isinstance(evidence_sha256, str) or not SHA256_RE.fullmatch(
                evidence_sha256):
            block_code(
                "owned_nullblk_qualification: evidence digest is invalid")
        lifecycle_hashes = owned_nullblk.get("hashes")
        if not _valid_hash_mapping(lifecycle_hashes):
            block_code(
                "owned_nullblk_qualification: lifecycle artifact hashes are malformed")
        elif report_artifacts is None or any(
                lifecycle_hashes.get(key) != report_artifacts.get(key)
                for key in ("module_sha256", "oracle_sha256")):
            block_code(
                "owned_nullblk_qualification: module/oracle artifact binding mismatch")

    critical = pass_record("unresolved_critical_issues")
    if critical is not None and (
            type(critical.get("count")) is not int or
            critical.get("count") != 0):
        block_code(
            "unresolved critical correctness issue count is not integer zero")

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
    if real_swap is not None:
        if real_swap_evidence is None or real_swap_evidence_raw is None:
            block_code("real_linux_swap: persistent physical evidence is missing")
        else:
            if real_swap.get("evidence_sha256") != sha256_bytes(
                    real_swap_evidence_raw):
                block_code(
                    "real_linux_swap: persistent evidence digest binding mismatch")
            for issue in validate_real_swap_evidence(
                    real_swap_evidence, real_swap_evidence_raw, source_sha,
                    test_results_raw, policy, policy_sha256,
                    report_artifacts, target):
                block_code("real_linux_swap: " + issue)

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
        if (
                physical_campaign_evidence is None or
                physical_campaign_evidence_raw is None):
            block_code(
                "maximum_capacity_and_ram: persistent campaign evidence is missing")
        else:
            if capacity.get("evidence_sha256") != sha256_bytes(
                    physical_campaign_evidence_raw):
                block_code(
                    "maximum_capacity_and_ram: campaign evidence digest binding mismatch")
            sealed_capacity = physical_campaign_evidence.get(
                "capacity_and_ram")
            if (
                    not isinstance(sealed_capacity, dict) or
                    logical != sealed_capacity.get("logical_capacity_bytes") or
                    peak != sealed_capacity.get("peak_ram_bytes")):
                block_code(
                    "maximum_capacity_and_ram: sealed campaign measurement mismatch")

    physical = pass_record("sustained_physical_performance")
    require_target("sustained_physical_performance", physical)
    require_policy("sustained_physical_performance", physical)
    if physical is not None:
        if (
                physical_campaign_evidence is None or
                physical_campaign_evidence_raw is None):
            block_code(
                "sustained_physical_performance: persistent campaign evidence is missing")
        else:
            if physical.get("evidence_sha256") != sha256_bytes(
                    physical_campaign_evidence_raw):
                block_code(
                    "sustained_physical_performance: campaign evidence digest binding mismatch")
            for issue in validate_physical_campaign_evidence(
                    physical_campaign_evidence,
                    physical_campaign_evidence_raw,
                    source_sha, policy_sha256, target):
                block_code("sustained_physical_performance: " + issue)

    lifecycle = pass_record("lifecycle_deployment_state", deployment=True)
    require_target("lifecycle_deployment_state", lifecycle, deployment=True)
    if lifecycle is not None and (
            lifecycle.get("overall") != "PASS" or
            lifecycle.get("lifecycle") != "PASS" or
            lifecycle.get("deployment") != "PASS"):
        block_deployment(
            "lifecycle_deployment_state: lifecycle/deployment result is not PASS")

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
    if isinstance(reboot, dict) and reboot.get("current") is True and \
            reboot.get("source_sha") == source_sha and \
            (target is not None and
             _normalize_target(reboot.get("target")) == target):
        if reboot.get("status") == "PASS" and reboot.get("observed") is True:
            if cold_boot_evidence is None or cold_boot_evidence_raw is None:
                cold_boot_blockers.append(
                    "owner_observed_reboot: persistent cold-boot evidence is missing")
            elif reboot.get("evidence_sha256") != sha256_bytes(
                    cold_boot_evidence_raw):
                cold_boot_blockers.append(
                    "owner_observed_reboot: persistent cold-boot evidence digest mismatch")
            else:
                for issue in validate_cold_boot_evidence(
                        cold_boot_evidence, source_sha, target,
                        report_artifacts, owner_kernel_release):
                    cold_boot_blockers.append(
                        "owner_observed_reboot: " + issue)
                if not cold_boot_blockers:
                    cold_boot_observed = "PASS"
        elif reboot.get("status") == "FAIL":
            cold_boot_observed = "FAIL"

    if not code_ready or not deployment_ready:
        release_verdict = "BLOCKED"
    elif cold_boot_observed == "PASS":
        release_verdict = "PASS"
    elif cold_boot_observed == "FAIL":
        release_verdict = "FAIL"
    else:
        release_verdict = "BLOCKED"

    return {
        "schema": "swapz-production-readiness-evaluation-v1",
        "release_verdict": release_verdict,
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
        "cold_boot_blockers": cold_boot_blockers,
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
    parser.add_argument(
        "--real-swap-evidence", type=Path,
        help="persistent primary-real-swap evidence emitted by the current qualifier")
    parser.add_argument(
        "--physical-campaign-evidence", type=Path,
        help="sealed physical performance campaign evidence for the release source")
    parser.add_argument(
        "--cold-boot-evidence", type=Path,
        help="persistent swapz-primary-cold-boot-v1 report from the owner reboot")
    args = parser.parse_args()

    try:
        test_results, test_raw = load_json_strict(args.test_results)
        evidence, _ = load_json_strict(args.evidence)
        policy, policy_raw = load_json_strict(args.acceptance)
        if args.real_swap_evidence is None:
            real_swap_evidence = None
            real_swap_evidence_raw = None
        else:
            real_swap_evidence, real_swap_evidence_raw = load_json_strict(
                args.real_swap_evidence)
        if args.physical_campaign_evidence is None:
            physical_campaign_evidence = None
            physical_campaign_evidence_raw = None
        else:
            physical_campaign_evidence, physical_campaign_evidence_raw = (
                load_json_strict(args.physical_campaign_evidence))
        if args.cold_boot_evidence is None:
            cold_boot_evidence = None
            cold_boot_evidence_raw = None
        else:
            cold_boot_evidence, cold_boot_evidence_raw = load_env_strict(
                args.cold_boot_evidence)
        result = evaluate_release(
            args.source_sha, test_results, test_raw, evidence, policy, policy_raw,
            real_swap_evidence, real_swap_evidence_raw,
            physical_campaign_evidence, physical_campaign_evidence_raw,
            cold_boot_evidence, cold_boot_evidence_raw)
    except (OSError, EvidenceError) as exc:
        result = {
            "schema": "swapz-production-readiness-evaluation-v1",
            "source_sha": args.source_sha,
            "release_verdict": "BLOCKED",
            "CODE_PRODUCTION_READY": "BLOCKED",
            "DEPLOYMENT_PRODUCTION_READY": "BLOCKED",
            "PRODUCTION_READY_FOR_OWNER_REBOOT": "NO",
            "COLD_BOOT_HARNESS": "NOT_ARMED",
            "COLD_BOOT_OBSERVED": "NO",
            "code_blockers": [str(exc)],
            "deployment_blockers": [
                "code production-readiness gates are not all PASS"],
            "cold_boot_blockers": [],
        }

    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    if result["release_verdict"] == "PASS":
        return 0
    if result["release_verdict"] == "FAIL":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
