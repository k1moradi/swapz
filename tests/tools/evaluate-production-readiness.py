#!/usr/bin/env python3
"""Strict private evaluator for swapz production release evidence.

This is test/release plumbing, not an operator interface.  It never performs
privileged actions and never upgrades historical observations into PASS.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import re
import runpy
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FROZEN_ACCEPTANCE_MANIFEST = ROOT / "docs/production-acceptance.json"
REAL_SWAP_HELPER = ROOT / "tests/tools/qualify-primary-real-swap.py"
REAL_SWAP_ORACLE = ROOT / "tests/tools/primary-real-swap-oracle.py"
PHYSICAL_CAMPAIGN_SEALER = (
    ROOT / "tests/runtime/benchmark/physical-campaign-evidence.py")
PHYSICAL_CAMPAIGN_EVALUATOR = (
    ROOT / "tests/runtime/benchmark/qualification.py")
METADATA_RAM_VALIDATOR = (
    ROOT / "tests/runtime/benchmark/metadata_ram_evidence.py")
RAM_TRACE_VALIDATOR = runpy.run_path(str(METADATA_RAM_VALIDATOR))
MAX_EVIDENCE_INPUT_BYTES = 256 * 1024 * 1024
MAX_ENV_EVIDENCE_INPUT_BYTES = 1024 * 1024
MAX_JSON_NESTING_DEPTH = 128
UNIX_EPOCH_ORDINAL = datetime.date(1970, 1, 1).toordinal()
PHYSICAL_CAMPAIGN_AMENDMENT = (
    ROOT / "tests/runtime/benchmark/physical-qualification-amendment-v2.json")
REAL_SWAP_CONTROL_INPUT_PATHS = (
    "src/kernel/VERSION",
    "src/kernel/authority.h",
    "src/kernel/codec.h",
    "src/kernel/superblock.h",
    "src/kernel/swapz-build-info.h",
    "src/userspace/swapz-primary.h",
    "src/userspace/swapz-primary.c",
    "src/userspace/swapzctl.c",
    "docs/production-acceptance.json",
    "docs/handoff/production-readiness.json",
)
REAL_SWAP_DYNAMIC_CONTROL_INPUT = "docs/handoff/production-readiness.json"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PARTUUID_RE = re.compile(r"^[0-9a-f]+(?:-[0-9a-f]+)*$")
MAJOR_MINOR_RE = re.compile(r"^[0-9]+:[0-9]+$")
KERNEL_RELEASE_RE = re.compile(r"^[A-Za-z0-9._+-]{1,127}$")
BOOT_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")
RUN_ID_DECIMAL_RE = re.compile(r"^[1-9][0-9]*$")
ENV_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
UTC_TIMESTAMP_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z$")
UTC_EVIDENCE_TIME_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?(?:Z|\+00:00)$")

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
PHYSICAL_AUDIT_KEYS = {
    "status",
    "diagnostics",
    "omitted_diagnostic_count",
    "qualification_status",
    "first_failed_phase",
    "first_failed_evidence",
    "cohort_pair_counts",
    "admitted_source_sha",
    "admitted_target_partuuid",
    "claim_boundary",
    "measurement_authority",
}
PHYSICAL_AUDIT_FIRST_FAILURE_KEYS = {
    "workload", "pair_index", "arm", "metric", "evidence_class",
}
PHYSICAL_AUDIT_COHORT_COUNT_KEYS = {
    "required_pairs", "attempted_pairs", "accepted_pairs",
}
PHYSICAL_HOST_STABILITY_CHECKS = {
    "source_sha", "source_tree_sha", "kernel_release", "kernel_machine",
    "kernel_version", "kernel_node", "kernel_boot_id",
    "capture_monotonic_increasing", "kernel_uptime_non_decreasing",
    "device_major_minor", "device_size_bytes", "device_parent_major_minor",
    "device_partuuid", "device_serial", "device_wwid", "physical_disk",
    "device_model", "device_transport", "device_scheduler", "device_queue",
    "admitted_device_quiescent_before", "admitted_device_quiescent_after",
    "cpu_model_names", "configured_cpus", "online_cpus", "affinity_cpus",
    "cpu_governors", "cpu_frequency_drivers", "cpu_scaling_min",
    "cpu_scaling_max", "memory_total_bytes", "mount_inventory",
    "swap_inventory", "module_state",
}
PHYSICAL_DEVICE_BOUNDARY_KEYS = {
    "major_minor", "swap_rows", "mount_rows", "holders", "quiescent",
}
PHYSICAL_QUALIFICATION_TARGET_BINDING_KEYS = {
    "status", "consistent", "expected", "observed",
}
PHYSICAL_QUALIFICATION_TARGET_IDENTITY_KEYS = {
    "physical_partuuid", "physical_device_bytes", "lower_major_minor",
    "parent_major_minor", "parent_model", "parent_transport",
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
    "expected_dm_uuid", "dm_uuid", "mapper_sysfs_dm_name", "dm_table",
    "dm_logical_sectors", "expected_dm_logical_sectors", "dm_logical_bytes",
    "dm_status_file", "swap_total_entries", "swap_mapper_entries",
    "swap_path", "swap_type", "swap_size_kib", "swap_used_kib",
    "swap_priority", "mapper_service_active_state",
    "mapper_service_sub_state", "mapper_service_result",
    "swap_unit_active_state", "swap_unit_sub_state", "swap_unit_result",
    "swapz_failed", "swapz_error", "swapz_flush_err",
    "swapz_segment_discards_failed", "swapz_upper_write_completed_err",
    "swapz_endio_write_seen_err", "swapz_endio_write_forced_err",
    "gc_victims", "gc_pages", "gc_no_headroom_skips",
    "gc_reserve_segments_initial", "gc_reserve_segments_current",
    "gc_destination_advances", "window_gc_pressure", "kernel_error_count",
    "kernel_error_log", "failure_reasons", "incomplete_reasons",
}
COLD_BOOT_ARM_KEYS = {
    "schema", "arm_boot_id", "arm_kernel_release", "armed_epoch",
    "expected_partuuid", "expected_target_size_bytes",
    "expected_target_model", "expected_target_serial", "expected_target_wwn",
    "expected_target_transport", "expected_target_removable",
    "expected_module_sha256", "expected_module_source_sha",
    "expected_module_source_clean",
}


class EvidenceError(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(
                f"duplicate JSON key: {key[:80]!r}"
                f"{' (truncated)' if len(key) > 80 else ''}")
        result[key] = value
    return result


def _bounded_json_integer(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if len(digits) > 20:
        raise EvidenceError(
            "JSON integer exceeds evidence bound: "
            f"metric=decimal_digits observed={len(digits)} maximum=20")
    parsed = int(value, 10)
    maximum = RAM_TRACE_VALIDATOR["MAX_UINT64"]
    if not -maximum <= parsed <= maximum:
        raise EvidenceError(
            "JSON integer exceeds evidence bound: "
            f"metric=absolute_value observed={abs(parsed)} maximum={maximum}")
    return parsed


def _finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise EvidenceError("nonfinite JSON number is not evidence")
    return parsed


def _reject_json_constant(value: str) -> None:
    raise EvidenceError(f"nonfinite JSON constant is not evidence: {value}")


def _check_json_nesting_depth(raw: bytes) -> None:
    """Bound container nesting before the standard decoder builds objects."""
    depth = 0
    in_string = False
    escaped = False
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == ord("\\"):
                escaped = True
            elif byte == ord('"'):
                in_string = False
            continue
        if byte == ord('"'):
            in_string = True
        elif byte in (ord("{"), ord("[")):
            depth += 1
            if depth > MAX_JSON_NESTING_DEPTH:
                raise ValueError(
                    "JSON evidence nesting exceeds validation depth "
                    f"{MAX_JSON_NESTING_DEPTH}")
        elif byte in (ord("}"), ord("]")):
            depth -= 1


def _parse_json_object_bytes(raw: Any, evidence_name: str) -> dict[str, Any]:
    if not isinstance(raw, bytes) or not raw:
        raise EvidenceError(f"{evidence_name}: serialized JSON evidence is empty")
    if len(raw) > MAX_EVIDENCE_INPUT_BYTES:
        raise EvidenceError(
            f"{evidence_name}: evidence exceeds "
            f"{MAX_EVIDENCE_INPUT_BYTES}-byte input bound")
    try:
        _check_json_nesting_depth(raw)
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_int=_bounded_json_integer,
            parse_float=_finite_json_float,
            parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, ValueError, OverflowError, RecursionError) as exc:
        raise EvidenceError(f"{evidence_name}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"{evidence_name}: top level must be an object")
    return value


def load_json_strict(path: Path) -> tuple[dict[str, Any], bytes]:
    with path.open("rb") as evidence_file:
        raw = evidence_file.read(MAX_EVIDENCE_INPUT_BYTES + 1)
    return _parse_json_object_bytes(raw, str(path)), raw


def sha256_bytes(raw: Any) -> str | None:
    """Hash serialized evidence without throwing on malformed direct inputs."""
    if not isinstance(raw, bytes):
        return None
    return hashlib.sha256(raw).hexdigest()


def parse_env_strict(raw: Any) -> dict[str, str]:
    """Parse bounded newline-delimited key=value evidence fail closed."""
    if not isinstance(raw, bytes) or not raw:
        raise EvidenceError("cold-boot evidence bytes are empty or invalid")
    if len(raw) > MAX_ENV_EVIDENCE_INPUT_BYTES:
        raise EvidenceError(
            "cold-boot evidence exceeds 1048576-byte input bound")
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
            raise EvidenceError(
                f"duplicate cold-boot evidence key: {key[:80]!r}"
                f"{' (truncated)' if len(key) > 80 else ''}")
        if any(ord(character) < 0x20 for character in value):
            raise EvidenceError(
                f"cold-boot evidence line {line_number} has control characters")
        result[key] = value
    return result


def load_env_strict(path: Path) -> tuple[dict[str, str], bytes]:
    with path.open("rb") as evidence_file:
        raw = evidence_file.read(MAX_ENV_EVIDENCE_INPUT_BYTES + 1)
    try:
        return parse_env_strict(raw), raw
    except EvidenceError as exc:
        raise EvidenceError(f"{path}: {exc}") from exc


def maximum_logical_sectors(device_bytes: Any) -> int | None:
    """Mirror the production boot/manager admission rule without device I/O."""
    if (
            type(device_bytes) is not int or device_bytes <= 4096 or
            device_bytes > RAM_TRACE_VALIDATOR["MAX_UINT64"] or
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


def _same_json_value(left: Any, right: Any) -> bool:
    """Compare parsed JSON without Python's bool/int or int/float coercion."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return (
            set(left) == set(right) and
            all(_same_json_value(left[key], right[key]) for key in left)
        )
    if isinstance(left, list):
        return (
            len(left) == len(right) and
            all(_same_json_value(a, b) for a, b in zip(left, right))
        )
    return left == right


def _bound_json_object(
        value: Any, raw: Any, evidence_name: str) -> dict[str, Any]:
    serialized = _parse_json_object_bytes(raw, evidence_name)
    try:
        matches_serialized = _same_json_value(serialized, value)
    except RecursionError as exc:
        raise EvidenceError(
            f"{evidence_name}: evidence nesting exceeds validation depth") from exc
    if not matches_serialized:
        raise EvidenceError(
            f"{evidence_name}: parsed object differs from serialized bytes")
    return serialized


def _bound_env_record(
        value: Any, raw: Any, evidence_name: str) -> dict[str, str]:
    if not isinstance(raw, bytes) or not raw:
        raise EvidenceError(f"{evidence_name}: serialized evidence is empty")
    serialized = parse_env_strict(raw)
    if serialized != value:
        raise EvidenceError(
            f"{evidence_name}: parsed object differs from serialized bytes")
    return serialized


def _valid_source(value: Any) -> bool:
    return isinstance(value, str) and bool(GIT_SHA_RE.fullmatch(value))


def _parse_utc_evidence_time(value: Any) -> int | None:
    """Parse canonical UTC evidence into exact integer nanoseconds."""
    if (
            not isinstance(value, str) or
            UTC_EVIDENCE_TIME_RE.fullmatch(value) is None):
        return None
    core = value[:-1] if value.endswith("Z") else value[:-6]
    fraction_ns = 0
    if len(core) > 19:
        fraction_ns = int(core[20:].ljust(9, "0"), 10)
    try:
        observed = datetime.datetime(
            int(core[0:4]), int(core[5:7]), int(core[8:10]),
            int(core[11:13]), int(core[14:16]), int(core[17:19]))
    except ValueError:
        return None
    whole_seconds = (
        (observed.toordinal() - UNIX_EPOCH_ORDINAL) * 86400 +
        observed.hour * 3600 + observed.minute * 60 + observed.second)
    return whole_seconds * 1_000_000_000 + fraction_ns


def _valid_observed_at_utc(value: Any) -> bool:
    return (
        isinstance(value, str) and
        UTC_TIMESTAMP_RE.fullmatch(value) is not None and
        _parse_utc_evidence_time(value) is not None)


def _valid_run_id(value: Any) -> bool:
    """Validate bounded canonical IDs before numeric normalization."""
    if type(value) is int:
        return 0 < value <= (1 << 63) - 1
    if not isinstance(value, str) or not 1 <= len(value) <= 19:
        return False
    return (RUN_ID_DECIMAL_RE.fullmatch(value) is not None and
            int(value) <= (1 << 63) - 1)


def _bounded_decimal_text(
        value: Any, *, maximum: int | None = None) -> int | None:
    """Parse an unsigned decimal evidence field without giant-int coercion."""
    if maximum is None:
        maximum = RAM_TRACE_VALIDATOR["MAX_UINT64"]
    maximum_digits = len(str(maximum))
    if (
            not isinstance(value, str) or
            not 1 <= len(value) <= maximum_digits or
            not value.isascii() or not value.isdecimal()):
        return None
    parsed = int(value, 10)
    return parsed if parsed <= maximum else None


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
    if (
            size_bytes <= 0 or
            size_bytes > RAM_TRACE_VALIDATOR["MAX_UINT64"]):
        return None
    return partuuid, size_bytes


def _normalize_campaign_target(value: Any) -> tuple[str, int] | None:
    if not isinstance(value, dict):
        return None
    return _normalize_target({
        "partuuid": value.get("partuuid"),
        "size_bytes": value.get("device_bytes"),
    })


def _capacity_index_prediction(
        target: tuple[str, int] | None) -> dict[str, Any]:
    """Return allocation arithmetic only; never infer loaded-host success."""
    unavailable = {
        "status": "NOT_AVAILABLE",
        "logical_pages": None,
        "logical_mapper_bytes": None,
        "physical_blocks": None,
        "segment_count": None,
        "array_count": None,
        "payload_bytes": None,
        "page_rounded_bytes": None,
    }
    if target is None:
        return unavailable
    partition_bytes = target[1]
    logical_pages = RAM_TRACE_VALIDATOR[
        "maximum_logical_pages_for_partition"](
            partition_bytes, size_t_max=RAM_TRACE_VALIDATOR["MAX_UINT64"])
    if logical_pages is None:
        return unavailable
    block_bytes = RAM_TRACE_VALIDATOR["BLOCK_BYTES"]
    segment_blocks = RAM_TRACE_VALIDATOR["SEGMENT_BLOCKS"]
    total_blocks = partition_bytes // block_bytes
    physical_blocks = (
        (total_blocks - 1) // segment_blocks) * segment_blocks
    logical_mapper_bytes = RAM_TRACE_VALIDATOR["_checked_product"](
        logical_pages, block_bytes, RAM_TRACE_VALIDATOR["MAX_UINT64"])
    estimate = RAM_TRACE_VALIDATOR["capacity_index_estimate"](
        logical_pages, physical_blocks,
        size_t_max=RAM_TRACE_VALIDATOR["MAX_UINT64"])
    if (
            logical_mapper_bytes is None or estimate is None or
            estimate.get("array_count") != 17):
        return unavailable
    return {
        "status": "PREDICTED_ONLY",
        "logical_pages": logical_pages,
        "logical_mapper_bytes": logical_mapper_bytes,
        "physical_blocks": physical_blocks,
        "segment_count": physical_blocks // segment_blocks,
        **estimate,
    }


def _valid_campaign_artifact(value: Any) -> bool:
    return (
        isinstance(value, dict) and
        isinstance(value.get("name"), str) and bool(value["name"]) and
        isinstance(value.get("size_bytes"), int) and
        not isinstance(value.get("size_bytes"), bool) and
        0 < value["size_bytes"] <= RAM_TRACE_VALIDATOR["MAX_UINT64"] and
        isinstance(value.get("sha256"), str) and
        bool(SHA256_RE.fullmatch(value["sha256"]))
    )


def _physical_host_stability_is_valid(value: Any) -> bool:
    """Require the complete current sealer host-stability witness."""
    if not isinstance(value, dict) or set(value) != {
            "status", "checks", "failed_checks"}:
        return False
    checks = value.get("checks")
    return (
        value.get("status") == "STABLE" and
        isinstance(checks, dict) and
        set(checks) == PHYSICAL_HOST_STABILITY_CHECKS and
        all(check is True for check in checks.values()) and
        value.get("failed_checks") == []
    )


def _physical_device_boundary_is_quiescent(
        value: Any, expected_lower_major_minor: Any) -> bool:
    """Require the complete current sealer quiescent target boundary."""
    return (
        isinstance(value, dict) and
        set(value) == PHYSICAL_DEVICE_BOUNDARY_KEYS and
        isinstance(expected_lower_major_minor, str) and
        MAJOR_MINOR_RE.fullmatch(expected_lower_major_minor) is not None and
        value.get("major_minor") == expected_lower_major_minor and
        value.get("swap_rows") == [] and
        value.get("mount_rows") == [] and
        value.get("holders") == [] and
        value.get("quiescent") is True
    )


def _physical_qualification_target_binding_is_valid(
        value: Any, target: tuple[str, int] | None) -> bool:
    """Require the complete current sealer target and parent identity."""
    if (
            not isinstance(value, dict) or
            set(value) != PHYSICAL_QUALIFICATION_TARGET_BINDING_KEYS or
            value.get("status") != "MATCH" or
            value.get("consistent") is not True):
        return False
    expected = value.get("expected")
    if (
            not isinstance(expected, dict) or
            set(expected) != PHYSICAL_QUALIFICATION_TARGET_IDENTITY_KEYS or
            _normalize_target({
                "partuuid": expected.get("physical_partuuid"),
                "size_bytes": expected.get("physical_device_bytes"),
            }) != target or
            not isinstance(expected.get("lower_major_minor"), str) or
            MAJOR_MINOR_RE.fullmatch(expected["lower_major_minor"]) is None or
            not isinstance(expected.get("parent_major_minor"), str) or
            MAJOR_MINOR_RE.fullmatch(expected["parent_major_minor"]) is None or
            not isinstance(expected.get("parent_model"), str) or
            not expected["parent_model"] or
            not isinstance(expected.get("parent_transport"), str) or
            not expected["parent_transport"]):
        return False
    return _same_json_value(value.get("observed"), expected)


def _malformed_physical_evidence_issue(
        phase: str, field: str, expected_type: str, observed: Any) -> str:
    """Describe malformed nested evidence without echoing its raw value."""
    return (
        "sealed campaign nested evidence is malformed: "
        f"phase={phase} failed_evidence_field={field} "
        f"expected_type={expected_type} "
        f"observed_type={type(observed).__name__} "
        "original_error=unavailable verdict=BLOCKED "
        "safe_action=recapture_and_reseal_campaign"
    )


def _physical_audit_binding_is_valid(
        audit: Any,
        source_sha: str,
        target: tuple[str, int] | None,
        physical_policy: Any,
        producer_workloads: dict[str, Any],
        pairs: Any,
        qualification_status: Any,
        failure_count_workload: str | None = None) -> bool:
    """Bind the producer audit; a proven FAIL may scope count validation."""
    if (
            not isinstance(audit, dict) or set(audit) != PHYSICAL_AUDIT_KEYS or
            not isinstance(audit.get("diagnostics"), list) or
            type(audit.get("omitted_diagnostic_count")) is not int or
            audit["omitted_diagnostic_count"] < 0 or
            audit.get("qualification_status") != qualification_status or
            audit.get("admitted_source_sha") != source_sha or
            target is None or
            audit.get("admitted_target_partuuid") != target[0] or
            not isinstance(physical_policy, dict) or
            audit.get("claim_boundary") != physical_policy.get(
                "claim_boundary") or
            audit.get("measurement_authority") !=
            "host-visible lower I/O, not NAND wear" or
            not isinstance(pairs, list)):
        return False

    counts = audit.get("cohort_pair_counts")
    if not isinstance(counts, dict):
        return False
    if failure_count_workload is None:
        if set(counts) != set(producer_workloads):
            return False
    elif failure_count_workload not in producer_workloads:
        return False
    observed_counts = {workload: 0 for workload in producer_workloads}
    observed_pass_pair_counts = {
        workload: 0 for workload in producer_workloads}
    observed_indices = {workload: set() for workload in producer_workloads}
    pair_identifiers = set()
    artifact_names = set()
    artifact_digests = set()
    for pair in pairs:
        if not _valid_campaign_artifact(pair):
            return False
        workload = pair.get("workload")
        if (
                not isinstance(workload, str) or
                workload not in observed_counts):
            return False
        specification = producer_workloads[workload]
        pair_index = pair.get("pair_index")
        pair_id = pair.get("pair_id")
        if (
                type(pair_index) is not int or
                not 1 <= pair_index <= specification["pairs"] or
                pair_index in observed_indices[workload] or
                not isinstance(pair_id, str) or not pair_id or
                (workload, pair_id) in pair_identifiers or
                pair.get("order") != specification["counterbalanced_order"][
                    pair_index - 1] or
                not (
                    (pair.get("status") == "PASS" and
                     pair.get("excluded") is False) or
                    (pair.get("status") == "EXCLUDED" and
                     pair.get("excluded") is True)) or
                pair["name"] in artifact_names or
                pair["sha256"] in artifact_digests):
            return False
        observed_indices[workload].add(pair_index)
        pair_identifiers.add((workload, pair_id))
        artifact_names.add(pair["name"])
        artifact_digests.add(pair["sha256"])
        observed_counts[workload] += 1
        if pair["status"] == "PASS":
            observed_pass_pair_counts[workload] += 1
    for workload, specification in producer_workloads.items():
        if (
                failure_count_workload is not None and
                workload != failure_count_workload):
            continue
        count = counts.get(workload)
        if (
                not isinstance(count, dict) or
                set(count) != PHYSICAL_AUDIT_COHORT_COUNT_KEYS or
                type(count.get("required_pairs")) is not int or
                type(count.get("attempted_pairs")) is not int or
                type(count.get("accepted_pairs")) is not int or
                count["required_pairs"] != specification["pairs"] or
                count["attempted_pairs"] != observed_counts[workload] or
                count["accepted_pairs"] >
                observed_pass_pair_counts[workload] or
                count["accepted_pairs"] < 0 or
                count["accepted_pairs"] > count["attempted_pairs"]):
            return False
    return True


def _physical_producer_failure_diagnostic_is_valid(
        audit: dict[str, Any], first_failure: dict[str, Any]) -> bool:
    """Bind an arm FAIL to the producer's bounded retained diagnostic."""
    phase = audit.get("first_failed_phase")
    if (
            first_failure.get("metric") != "arm.verdict" or
            not isinstance(phase, str) or
            re.fullmatch(
                r"(?:measure|steady|gc|"
                r"round-[1-9][0-9]*(?:-verify)?)", phase) is None):
        return False
    return any(
        isinstance(diagnostic, dict) and
        diagnostic.get("status") == "FAIL" and
        diagnostic.get("metric") == "arm.verdict" and
        diagnostic.get("workload") == first_failure.get("workload") and
        diagnostic.get("pair_index") == first_failure.get("pair_index") and
        diagnostic.get("arm") == first_failure.get("arm") and
        diagnostic.get("producer_status") == "FAIL" and
        diagnostic.get("failure_phase") == phase and
        diagnostic.get("expected") == "PASS" and
        diagnostic.get("observed") is None and
        diagnostic.get("reason") ==
        "authenticated physical producer terminal measurement failure"
        for diagnostic in audit.get("diagnostics", ())
    )


def _physical_audit_failure_witness_is_valid(
        audit: dict[str, Any],
        producer_workloads: dict[str, Any],
        pairs: list[Any]) -> bool:
    """Require the retained first FAIL to agree with the pair manifest."""
    first_failure = audit.get("first_failed_evidence")
    if (
            not isinstance(first_failure, dict) or
            set(first_failure) != PHYSICAL_AUDIT_FIRST_FAILURE_KEYS or
            first_failure.get("evidence_class") != "FAIL"):
        return False
    workload = first_failure.get("workload")
    if (
            not isinstance(workload, str) or
            workload not in producer_workloads):
        return False
    metric = first_failure.get("metric")
    pair_index = first_failure.get("pair_index")
    arm = first_failure.get("arm")
    matching_diagnostics = [
        diagnostic for diagnostic in audit["diagnostics"]
        if isinstance(diagnostic, dict) and
        diagnostic.get("status") == "FAIL" and
        diagnostic.get("metric") == metric and
        diagnostic.get("workload") == workload and
        diagnostic.get("pair_index") == pair_index and
        diagnostic.get("arm") == arm
    ]
    if not matching_diagnostics:
        return False

    if metric == "arm.verdict":
        phase = audit.get("first_failed_phase")
        if (
                type(pair_index) is not int or
                not 1 <= pair_index <= producer_workloads[workload]["pairs"] or
                arm not in ("raw", "swapz") or
                not isinstance(phase, str) or
                re.fullmatch(
                    r"(?:measure|steady|gc|"
                    r"round-[1-9][0-9]*(?:-verify)?)", phase) is None or
                not _physical_producer_failure_diagnostic_is_valid(
                    audit, first_failure)):
            return False
        witnesses = [
            pair for pair in pairs
            if isinstance(pair, dict) and
            pair.get("workload") == workload and
            pair.get("pair_index") == pair_index
        ]
        witness = witnesses[0] if len(witnesses) == 1 else None
        return (
            isinstance(witness, dict) and
            _valid_campaign_artifact(witness) and
            isinstance(witness.get("pair_id"), str) and
            bool(witness["pair_id"]) and
            witness.get("order") ==
            producer_workloads[workload]["counterbalanced_order"][
                pair_index - 1] and
            witness.get("status") == "EXCLUDED" and
            witness.get("excluded") is True)

    if metric == "qualification.decision_status":
        count = audit["cohort_pair_counts"][workload]
        specification = producer_workloads[workload]
        required = specification["pairs"]
        workload_pairs = [
            pair for pair in pairs
            if isinstance(pair, dict) and pair.get("workload") == workload
        ]
        indices = [
            pair.get("pair_index") for pair in workload_pairs
            if isinstance(pair, dict)]
        pair_ids = [
            pair.get("pair_id") for pair in workload_pairs
            if isinstance(pair, dict)]
        names = [
            pair.get("name") for pair in workload_pairs
            if isinstance(pair, dict)]
        digests = [
            pair.get("sha256") for pair in workload_pairs
            if isinstance(pair, dict)]
        return (
            pair_index is None and arm is None and
            audit.get("first_failed_phase") == "qualification" and
            count["attempted_pairs"] == required and
            count["accepted_pairs"] == required and
            len(workload_pairs) == required and
            all(type(index) is int for index in indices) and
            sorted(indices) == list(range(1, required + 1)) and
            all(isinstance(pair_id, str) and bool(pair_id)
                for pair_id in pair_ids) and
            len(set(pair_ids)) == required and
            all(isinstance(name, str) and bool(name) for name in names) and
            len(set(names)) == required and
            all(isinstance(digest, str) and SHA256_RE.fullmatch(digest)
                for digest in digests) and
            len(set(digests)) == required and
            all(
                _valid_campaign_artifact(pair) and
                type(pair.get("pair_index")) is int and
                1 <= pair["pair_index"] <= required and
                isinstance(pair.get("pair_id"), str) and bool(pair["pair_id"]) and
                pair.get("order") == specification["counterbalanced_order"][
                    pair["pair_index"] - 1] and
                pair.get("status") == "PASS" and
                pair.get("excluded") is False
                for pair in workload_pairs))

    return False


def _physical_campaign_workloads(
        policy: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return frozen release workloads and the complete current v2 producer map."""
    physical = policy.get("physical_qualification")
    frozen_workloads = (
        physical.get("workloads") if isinstance(physical, dict) else None)

    def validate_workloads(value: Any, label: str) -> dict[str, Any]:
        if not isinstance(value, dict) or not value:
            raise EvidenceError(f"{label} workload contract is unavailable")
        for workload, specification in value.items():
            if (
                    not isinstance(workload, str) or not workload or
                    not isinstance(specification, dict) or
                    type(specification.get("pairs")) is not int or
                    specification["pairs"] <= 0 or
                    not isinstance(
                        specification.get("counterbalanced_order"), list) or
                    len(specification["counterbalanced_order"]) !=
                    specification["pairs"] or
                    any(order not in ("raw-first", "swapz-first")
                        for order in specification["counterbalanced_order"])):
                raise EvidenceError(f"{label} workload contract is malformed")
        return value

    frozen_workloads = validate_workloads(
        frozen_workloads, "sealed campaign frozen")
    try:
        amendment, amendment_raw = load_json_strict(
            PHYSICAL_CAMPAIGN_AMENDMENT)
        frozen_raw = FROZEN_ACCEPTANCE_MANIFEST.read_bytes()
    except (OSError, EvidenceError) as exc:
        raise EvidenceError(
            "sealed campaign prospective amendment is unavailable") from exc
    expected_amendment_keys = {
        "schema", "status", "issued_on", "parent_schema", "parent_manifest",
        "parent_manifest_git_blob_sha", "result_pooling", "workloads",
        "acceptance",
    }
    git_blob = hashlib.sha1(usedforsecurity=False)
    git_blob.update(f"blob {len(frozen_raw)}\0".encode("ascii"))
    git_blob.update(frozen_raw)
    if (
            set(amendment) != expected_amendment_keys or
            amendment.get("schema") !=
            "swapz-performance-qualification-amendment-v2" or
            amendment.get("status") != "FROZEN_PROSPECTIVE" or
            amendment.get("parent_schema") !=
            physical.get("schema") or
            amendment.get("parent_manifest") !=
            "docs/production-acceptance.json" or
            amendment.get("parent_manifest_git_blob_sha") !=
            git_blob.hexdigest()):
        raise EvidenceError(
            "sealed campaign prospective amendment contract is invalid")
    amendment_workloads = validate_workloads(
        amendment.get("workloads"), "sealed campaign prospective")
    if set(frozen_workloads) & set(amendment_workloads):
        raise EvidenceError(
            "sealed campaign prospective workloads overlap frozen workloads")
    # Keep the exact serialized amendment read as part of the authority check.
    if not amendment_raw:
        raise EvidenceError(
            "sealed campaign prospective amendment bytes are empty")
    return frozen_workloads, {**frozen_workloads, **amendment_workloads}


def _tracked_frozen_peak_ram_limit() -> int | None:
    """Return the repository-frozen RAM bound for diagnostics only."""
    try:
        frozen_policy, _ = load_json_strict(FROZEN_ACCEPTANCE_MANIFEST)
    except (OSError, EvidenceError):
        return None
    physical = frozen_policy.get("physical_qualification")
    acceptance = (
        physical.get("acceptance") if isinstance(physical, dict) else None)
    sustained = (
        acceptance.get("sustained") if isinstance(acceptance, dict) else None)
    memory_limit = (
        sustained.get("metadata_and_target_peak_ram_bytes_max")
        if isinstance(sustained, dict) else None)
    if (
            type(memory_limit) is not int or
            not 0 < memory_limit <= RAM_TRACE_VALIDATOR["MAX_UINT64"]):
        return None
    return memory_limit


def validate_acceptance_policy(
        policy: dict[str, Any], raw: bytes) -> tuple[str, int]:
    policy = _bound_json_object(
        policy, raw, "production acceptance policy")
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
    if (type(memory_limit) is not int or
            not 0 < memory_limit <= RAM_TRACE_VALIDATOR["MAX_UINT64"]):
        raise EvidenceError("missing positive production RAM limit")
    # The word FROZEN in an input is not authority to replace the tracked
    # acceptance manifest. Compare exact JSON types/values, retaining the
    # supplied bytes for cross-artifact SHA binding.
    try:
        frozen_policy, frozen_raw = load_json_strict(
            FROZEN_ACCEPTANCE_MANIFEST)
    except (OSError, EvidenceError) as exc:
        raise EvidenceError(
            "tracked frozen production acceptance manifest is unavailable") from exc
    if not _same_json_value(policy, frozen_policy) or raw != frozen_raw:
        raise EvidenceError(
            "production acceptance policy differs from tracked frozen manifest: "
            "metric=acceptance_manifest required=exact_typed_frozen_bytes")
    return sha256_bytes(raw), memory_limit



def validate_real_swap_workload(
        workload: Any, primary_policy: dict[str, Any],
        cycle_index: int) -> list[str]:
    """Require the producer's independent Linux and lower-device observations."""
    issues: list[str] = []

    def reject(metric: str, required: Any, observed: Any) -> None:
        # Keep only the first bounded diagnostic metrics, never raw evidence.
        message = (
            f"cycle={cycle_index} workload.{metric} "
            f"required={required} observed={observed}")
        if len(issues) < 24 and message not in issues:
            issues.append(message)

    minimum_mib = primary_policy.get("minimum_swap_traffic_mib")
    workload_mib = primary_policy.get("workload_mib")
    page_bytes = primary_policy.get("page_bytes")
    if (type(minimum_mib) is not int or minimum_mib <= 0 or
            type(workload_mib) is not int or workload_mib <= 0 or
            type(page_bytes) is not int or page_bytes <= 0 or
            workload_mib * 1048576 % page_bytes):
        reject("frozen_policy", "positive traffic/page geometry", "invalid")
        return issues
    minimum_bytes = minimum_mib * 1048576
    verified_pages = workload_mib * 1048576 // page_bytes
    verified_bytes = verified_pages * page_bytes
    if not isinstance(workload, dict):
        reject("evidence", "producer workload object", "missing")
        return issues

    def counter(record: dict[str, Any], metric: str, minimum: int,
                location: str) -> int | None:
        observed = record.get(metric)
        if type(observed) is not int:
            reject(f"{location}.{metric}", f">={minimum}", "invalid")
            return None
        if observed < minimum:
            reject(f"{location}.{metric}", f">={minimum}", observed)
        return observed

    def exact(record: dict[str, Any], metric: str, required: Any,
              location: str) -> None:
        observed = record.get(metric)
        if type(observed) is not type(required) or observed != required:
            reject(f"{location}.{metric}", required,
                   observed if type(observed) in (bool, int) else "invalid")

    exact(workload, "concurrent_workers", 2, "summary")
    exact(workload, "reuse_rounds", 2, "summary")
    exact(workload, "slot_reuse_proven", True, "summary")
    counter(workload, "cgroup_memory_pressure_some_usec", 0, "summary")
    rounds = workload.get("rounds")
    if not isinstance(rounds, list) or len(rounds) != 2:
        reject("rounds", 2, len(rounds) if isinstance(rounds, list)
               else "invalid")
        return issues

    sum_fields = (
        "mapper_used_delta_kib",
        "swapz_logical_write_delta", "swapz_physical_write_delta",
        "swapz_logical_read_delta", "swapz_physical_read_delta",
        "lower_write_sector_delta", "lower_write_bytes_delta",
        "lower_read_sector_delta", "lower_read_bytes_delta",
        "pswpout_delta", "pswpin_delta", "oom_delta", "oom_kill_delta",
    )
    sums = {name: 0 for name in sum_fields}
    peaks: list[int] = []
    for index, round_evidence in enumerate(rounds, 1):
        location = f"round={index}"
        if not isinstance(round_evidence, dict):
            reject(location, "producer round object", "invalid")
            continue
        exact(round_evidence, "round", index, location)
        exact(round_evidence, "concurrent_workers", 2, location)
        exact(round_evidence, "mapper_used_start_kib", 0, location)
        exact(round_evidence, "mapper_used_released_kib", 0, location)
        exact(round_evidence, "release_swap_current_bytes", 0, location)
        for metric, minimum in (
                ("cgroup_swap_current_bytes_after_fill", minimum_bytes),
                ("cgroup_swap_peak_bytes", minimum_bytes),
                ("mapper_used_delta_kib", (minimum_bytes + 1023) // 1024),
                ("swapz_logical_write_delta", minimum_bytes),
                ("swapz_physical_write_delta", 1),
                ("swapz_logical_read_delta", minimum_bytes),
                ("swapz_physical_read_delta", 1),
                ("lower_write_sector_delta", 1),
                ("lower_read_sector_delta", 1),
                ("pswpout_delta", 1), ("pswpin_delta", 1),
                ("lower_write_bytes_delta", 1),
                ("lower_read_bytes_delta", 1)):
            counter(round_evidence, metric, minimum, location)
        exact(round_evidence, "oom_delta", 0, location)
        exact(round_evidence, "oom_kill_delta", 0, location)
        swap_current = round_evidence.get("cgroup_swap_current_bytes_after_fill")
        swap_peak = round_evidence.get("cgroup_swap_peak_bytes")
        mapper_used = round_evidence.get("mapper_used_delta_kib")
        if (type(swap_current) is int and type(mapper_used) is int and
                swap_current != mapper_used * 1024):
            reject(f"{location}.mapper_used_delta_kib",
                   "exact cgroup-to-mapper swap charge", "inconsistent")
        if (type(swap_current) is int and type(swap_peak) is int and
                swap_peak < swap_current):
            reject(f"{location}.cgroup_swap_peak_bytes",
                   "at least cgroup swap current", "inconsistent")
        for direction in ("write", "read"):
            sectors = round_evidence.get(f"lower_{direction}_sector_delta")
            lower_bytes = round_evidence.get(f"lower_{direction}_bytes_delta")
            physical_bytes = round_evidence.get(
                f"swapz_physical_{direction}_delta")
            if all(type(value) is int and value >= 0 for value in (
                    sectors, lower_bytes, physical_bytes)):
                if lower_bytes != sectors * 512 or lower_bytes < physical_bytes:
                    reject(f"{location}.lower_{direction}_bytes_delta",
                           "sectors*512 and >=physical", "inconsistent")
        workers = round_evidence.get("oracle_verified")
        filled = round_evidence.get("oracle_filled")
        worker_pids = round_evidence.get("worker_pids")
        worker_memory_mib = round_evidence.get("worker_memory_mib")
        if (not isinstance(workers, list) or len(workers) != 2 or
                not isinstance(filled, list) or len(filled) != 2 or
                not isinstance(worker_pids, list) or len(worker_pids) != 2 or
                any(type(pid) is not int or pid <= 0 for pid in worker_pids) or
                len(set(worker_pids)) != 2 or
                not isinstance(worker_memory_mib, list) or
                len(worker_memory_mib) != 2 or
                any(type(mib) is not int or mib < 64
                    for mib in worker_memory_mib) or
                sum(worker_memory_mib) != workload_mib):
            reject(f"{location}.oracle_workers", "two owned verified workers",
                   "invalid")
        else:
            worker_digests = []
            expected_digests = []
            worker_pages = 0
            worker_bytes = 0
            worker_mismatches = 0
            for worker_index, worker in enumerate(workers):
                fill = filled[worker_index]
                if not isinstance(worker, dict) or not isinstance(fill, dict):
                    reject(f"{location}.oracle_workers", "verified records", "invalid")
                    continue
                pages = worker.get("verified_pages")
                byte_count = worker.get("verified_bytes")
                mismatches = worker.get("mismatches")
                digest = worker.get("digest")
                expected_digest = worker.get("expected_digest")
                expected_worker_pages = (
                    worker_memory_mib[worker_index] * 1048576 // page_bytes)
                if (worker.get("pid") != worker_pids[worker_index] or
                        fill.get("pid") != worker_pids[worker_index] or
                        type(pages) is not int or
                        pages != expected_worker_pages or
                        type(byte_count) is not int or
                        byte_count != pages * page_bytes or
                        type(mismatches) is not int or mismatches != 0 or
                        not isinstance(digest, str) or
                        not SHA256_RE.fullmatch(digest) or
                        not isinstance(expected_digest, str) or
                        not SHA256_RE.fullmatch(expected_digest) or
                        digest != expected_digest or
                        fill.get("digest") != expected_digest):
                    reject(f"{location}.oracle_workers",
                           "matched byte-exact worker verification", "invalid")
                    continue
                worker_pages += pages
                worker_bytes += byte_count
                worker_mismatches += mismatches
                worker_digests.append(bytes.fromhex(digest))
                expected_digests.append(bytes.fromhex(expected_digest))
            aggregate = round_evidence.get("aggregate_verified")
            if len(worker_digests) == 2 and isinstance(aggregate, dict):
                for metric, expected in (
                        ("verified_pages", worker_pages),
                        ("verified_bytes", worker_bytes),
                        ("mismatches", worker_mismatches),
                        ("digest", hashlib.sha256(
                            b"".join(worker_digests)).hexdigest()),
                        ("expected_digest", hashlib.sha256(
                            b"".join(expected_digests)).hexdigest())):
                    if aggregate.get(metric) != expected:
                        reject(f"{location}.aggregate_verified.{metric}",
                               "matching worker sum/digest", "inconsistent")
        verified = round_evidence.get("aggregate_verified")
        if not isinstance(verified, dict):
            reject(f"{location}.aggregate_verified",
                   "byte-exact oracle totals", "missing")
        else:
            exact(verified, "verified_pages", verified_pages, location)
            exact(verified, "verified_bytes", verified_bytes, location)
            exact(verified, "mismatches", 0, location)
            digest = verified.get("digest")
            if (not isinstance(digest, str) or
                    not SHA256_RE.fullmatch(digest) or
                    digest != verified.get("expected_digest")):
                reject(f"{location}.aggregate_verified.digest",
                       "matching SHA-256 digests", "invalid")
        for name in sum_fields:
            value = round_evidence.get(name)
            if type(value) is int:
                sums[name] += value
        peak = round_evidence.get("cgroup_swap_peak_bytes")
        if type(peak) is int:
            peaks.append(peak)
    for name, expected in sums.items():
        exact(workload, name, expected, "summary")
    if len(peaks) == len(rounds):
        exact(workload, "cgroup_swap_peak_bytes", max(peaks), "summary")
    return issues


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

    authorization_snapshot_sha256 = result.get("authorization_snapshot_sha256")
    if (
            not isinstance(authorization_snapshot_sha256, str) or
            not SHA256_RE.fullmatch(authorization_snapshot_sha256)):
        reject("nested result authorization-snapshot digest is invalid")
    control_inputs = result.get("physical_control_inputs_sha256")
    if (
            not isinstance(control_inputs, dict) or
            set(control_inputs) != set(REAL_SWAP_CONTROL_INPUT_PATHS)):
        reject("nested result physical control-input inventory is incomplete")
    else:
        for relative_path in REAL_SWAP_CONTROL_INPUT_PATHS:
            observed_digest = control_inputs.get(relative_path)
            if (
                    not isinstance(observed_digest, str) or
                    not SHA256_RE.fullmatch(observed_digest)):
                reject(
                    "nested result physical control-input digest is malformed: "
                    f"artifact={relative_path}")
                continue
            if relative_path == "docs/production-acceptance.json":
                expected_digest = policy_sha256
            else:
                try:
                    expected_digest = sha256_bytes(
                        (ROOT / relative_path).read_bytes())
                except OSError:
                    expected_digest = None
                    reject(
                        "current physical control source input is unreadable: "
                        f"artifact={relative_path}")
            if (
                    relative_path == REAL_SWAP_DYNAMIC_CONTROL_INPUT and
                    observed_digest != authorization_snapshot_sha256):
                reject(
                    "nested result authorization snapshot/control-input "
                    "digest binding mismatch")
            if (
                    expected_digest is not None and
                    observed_digest != expected_digest):
                reject(
                    "nested result physical control-input digest differs from "
                    f"current source: artifact={relative_path}")

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
        observed = result.get(result_key)
        if type(expected) is not int or expected <= 0:
            reject(f"frozen primary real-swap policy {policy_key} is invalid")
        elif type(observed) is not int:
            reject(f"nested result {result_key} is not an exact integer")
        elif observed != expected:
            reject(f"nested result {result_key} differs from frozen policy")

    expected_cycles = primary_policy.get("cycles")
    cycles_passed = result.get("cycles_passed")
    if type(expected_cycles) is int:
        if type(cycles_passed) is not int:
            reject("nested result cycles_passed is not an exact integer")
        elif cycles_passed != expected_cycles:
            reject("nested result did not pass every required real-swap cycle")
    if type(result.get("concurrent_oracles")) is not int or \
            result.get("concurrent_oracles") != 2:
        reject("nested result did not use two concurrent byte oracles")
    if type(result.get("reuse_rounds_per_cycle")) is not int or \
            result.get("reuse_rounds_per_cycle") != 2:
        reject("nested result did not complete two reuse rounds per cycle")
    target_size_bytes = result.get("target_size_bytes")
    if (
            target is None or result.get("partuuid") != target[0] or
            type(target_size_bytes) is not int or
            target_size_bytes != target[1]):
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
        for cycle_index, cycle in enumerate(cycles, 1):
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
            if type(cycle.get("cycle")) is not int or cycle["cycle"] != cycle_index:
                reject(f"nested result cycle identity required={cycle_index} observed=invalid")
            if (isinstance(run_id, str) and RUN_ID_RE.fullmatch(run_id) and
                    cycle.get("mapper_uuid") != f"SWAPZ-PRIMARY-{run_id}"):
                reject(f"nested result cycle={cycle_index} mapper UUID binding mismatch")
            mapper_device = cycle.get("mapper_device")
            if (not isinstance(mapper_device, str) or
                    not MAJOR_MINOR_RE.fullmatch(mapper_device) or
                    mapper_device == target_device):
                reject(f"nested result cycle={cycle_index} exact mapper device identity is invalid")
            if type(cycle.get("swap_priority")) is not int or (
                    cycle["swap_priority"] != -1):
                reject(f"nested result cycle={cycle_index} swap priority is not -1")
            if type(cycle.get("fresh_mapper_used_kib")) is not int or (
                    cycle["fresh_mapper_used_kib"] != 0):
                reject(f"nested result cycle={cycle_index} did not start fresh")
            loaded_module = cycle.get("loaded_module")
            if (
                    not isinstance(loaded_module, dict) or
                    set(loaded_module) != {
                        "build_source_sha", "build_source_clean",
                        "allow_physical_backing"} or
                    loaded_module.get("build_source_sha") != source_sha or
                    loaded_module.get("build_source_clean") != "1" or
                    loaded_module.get("allow_physical_backing") not in (
                        "1", "Y")):
                reject(
                    f"nested result cycle={cycle_index} loaded module "
                    "provenance is not exact")
            telemetry = cycle.get("cycle_telemetry")
            minimum_available = primary_policy.get(
                "minimum_mem_available_mib")
            if (
                    not isinstance(telemetry, dict) or
                    type(telemetry.get("samples")) is not int or
                    telemetry["samples"] <= 0 or
                    type(telemetry.get("started_monotonic_ns")) is not int or
                    type(telemetry.get("ended_monotonic_ns")) is not int or
                    not 0 < telemetry["started_monotonic_ns"] <
                    telemetry["ended_monotonic_ns"] or
                    type(minimum_available) is not int or
                    type(telemetry.get("minimum_mem_available_mib")) is not int or
                    telemetry["minimum_mem_available_mib"] <
                    minimum_available or
                    any(type(telemetry.get(key)) is not int or
                        telemetry[key] < 0 for key in (
                            "memory_psi_some_usec_delta",
                            "pswpin_delta", "pswpout_delta"))):
                reject(
                    f"nested result cycle={cycle_index} cycle telemetry "
                    "is incomplete or below the frozen safety floor")
            stop_order = cycle.get("stop_order")
            if (not isinstance(stop_order, dict) or
                    any(stop_order.get(key) is not True for key in (
                        "initial_active", "swapoff_before_remove_witness",
                        "final_absent")) or
                    type(stop_order.get("samples")) is not int or
                    stop_order["samples"] <= 0):
                reject(f"nested result cycle={cycle_index} normal stop-order proof is missing")
            for issue in validate_real_swap_workload(
                    cycle.get("workload"), primary_policy, cycle_index):
                reject("nested result " + issue)
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

    try:
        physical_evidence = _bound_json_object(
            physical_evidence, raw, "persistent real-swap evidence")
    except EvidenceError as exc:
        reject(str(exc))
        return issues

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
            "authorization_snapshot_sha256", "qualification_report_sha256",
            "helper_sha256", "oracle_sha256",
            "qualified_installed_artifacts", "physical_execution_control_sha256",
            "physical_control_inputs_sha256",
            "installed_control_privileged_execution_enabled",
            "partuuid", "target_size_bytes", "target_device",
            "cycles_requested", "workload_mib",
            "resident_limit_mib", "swap_limit_mib", "timeout_seconds",
            "concurrent_oracles", "reuse_rounds_per_cycle", "cycles"):
        if not _same_json_value(
                physical_evidence.get(key), result.get(key)):
            reject(f"persistent evidence/result mismatch for {key}")
    return issues



def _real_swap_failure_is_proven(
        physical_evidence: Any,
        raw: Any,
        source_sha: str,
        test_results_raw: bytes,
        policy: dict[str, Any],
        policy_sha256: str | None,
        report_artifacts: dict[str, Any] | None,
        target: tuple[str, int] | None) -> bool:
    """Authenticate a terminal producer FAIL without treating gaps as failure."""
    if not _valid_source(source_sha):
        return False
    try:
        record = _bound_json_object(
            physical_evidence, raw, "persistent real-swap failure evidence")
    except EvidenceError:
        return False
    if (
            record.get("schema") != "swapz-primary-real-swap-evidence-v1" or
            record.get("status") != "FAIL" or
            record.get("phase") != "COMPLETE" or
            "result" in record or
            not isinstance(record.get("reason"), str) or
            not record["reason"] or
            not isinstance(record.get("attempt_id"), str) or
            not RUN_ID_RE.fullmatch(record["attempt_id"]) or
            record.get("source_sha") != source_sha or
            policy_sha256 is None or
            record.get("acceptance_manifest_sha256") != policy_sha256 or
            record.get("qualification_report_sha256") !=
            sha256_bytes(test_results_raw) or
            not _same_hashes(
                record.get("qualified_installed_artifacts"),
                report_artifacts)):
        return False
    execution_control = record.get("physical_execution_control_sha256")
    if (
            not isinstance(execution_control, str) or
            not SHA256_RE.fullmatch(execution_control) or
            not isinstance(report_artifacts, dict) or
            execution_control == report_artifacts.get("formatter_sha256") or
            record.get("installed_control_privileged_execution_enabled")
            is not False):
        return False
    try:
        if (
                record.get("helper_sha256") !=
                sha256_bytes(REAL_SWAP_HELPER.read_bytes()) or
                record.get("oracle_sha256") !=
                sha256_bytes(REAL_SWAP_ORACLE.read_bytes())):
            return False
    except OSError:
        return False
    target_size = record.get("target_size_bytes")
    target_device = record.get("target_device")
    if (
            target is None or record.get("partuuid") != target[0] or
            type(target_size) is not int or target_size != target[1] or
            not isinstance(target_device, str) or
            not MAJOR_MINOR_RE.fullmatch(target_device)):
        return False
    primary = policy.get("primary_real_swap")
    if not isinstance(primary, dict):
        return False
    for record_key, policy_key in (
            ("cycles_requested", "cycles"),
            ("workload_mib", "workload_mib"),
            ("resident_limit_mib", "resident_mib"),
            ("swap_limit_mib", "swap_limit_mib"),
            ("timeout_seconds", "timeout_seconds")):
        if (
                type(primary.get(policy_key)) is not int or
                type(record.get(record_key)) is not int or
                record[record_key] != primary[policy_key]):
            return False
    if (
            type(record.get("concurrent_oracles")) is not int or
            record["concurrent_oracles"] != 2 or
            type(record.get("reuse_rounds_per_cycle")) is not int or
            record["reuse_rounds_per_cycle"] != 2 or
            not isinstance(record.get("cycles"), list) or
            len(record["cycles"]) > record["cycles_requested"]):
        return False
    authorization_digest = record.get("authorization_snapshot_sha256")
    control_inputs = record.get("physical_control_inputs_sha256")
    if (
            not isinstance(authorization_digest, str) or
            not SHA256_RE.fullmatch(authorization_digest) or
            not isinstance(control_inputs, dict) or
            set(control_inputs) != set(REAL_SWAP_CONTROL_INPUT_PATHS)):
        return False
    for relative_path in REAL_SWAP_CONTROL_INPUT_PATHS:
        observed_digest = control_inputs.get(relative_path)
        if (
                not isinstance(observed_digest, str) or
                not SHA256_RE.fullmatch(observed_digest)):
            return False
        if relative_path == "docs/production-acceptance.json":
            expected_digest = policy_sha256
        else:
            try:
                expected_digest = sha256_bytes(
                    (ROOT / relative_path).read_bytes())
            except OSError:
                return False
        if (
                relative_path == REAL_SWAP_DYNAMIC_CONTROL_INPUT and
                observed_digest != authorization_digest):
            return False
        if observed_digest != expected_digest:
            return False
    return True


def validate_physical_campaign_evidence(
        campaign: dict[str, Any],
        raw: bytes,
        source_sha: str,
        policy_sha256: str | None,
        target: tuple[str, int] | None,
        policy: dict[str, Any] | None = None) -> list[str]:
    issues: list[str] = []

    def reject(message: str) -> None:
        if message not in issues:
            issues.append(message)

    # Existing direct-validator callers supply five arguments. They must
    # still get the tracked frozen cohort, never a caller-invented plan.
    # Five-argument callers predate release-completeness enforcement and are
    # retained for structural/measurement validation only. evaluate_release()
    # supplies its validated policy object as a sixth argument to select strict
    # release validation. Workload authority always comes from tracked bytes,
    # never from the caller's object.
    release_validation = policy is not None
    try:
        tracked_policy, _ = load_json_strict(FROZEN_ACCEPTANCE_MANIFEST)
        frozen_workloads, producer_workloads = _physical_campaign_workloads(
            tracked_policy)
    except (OSError, EvidenceError) as exc:
        reject(
            "sealed campaign tracked workload policy unavailable: "
            f"{type(exc).__name__}")
        return issues

    physical_policy = tracked_policy.get("physical_qualification")

    if not isinstance(campaign, dict):
        reject("sealed campaign evidence object is invalid")
        return issues
    if campaign.get("schema") != "swapz-performance-campaign-evidence-v1":
        reject("sealed campaign schema is invalid")
    if not isinstance(raw, bytes):
        reject("sealed campaign evidence bytes are invalid")
        return issues
    if not raw:
        reject("sealed campaign evidence bytes are empty")
        return issues
    if len(raw) > MAX_EVIDENCE_INPUT_BYTES:
        reject("sealed campaign evidence bytes exceed input bound")
        return issues
    # The digest belongs to these exact serialized bytes, not a separate
    # mutable Python object supplied by a caller.
    try:
        _check_json_nesting_depth(raw)
        serialized_campaign = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_int=_bounded_json_integer,
            parse_float=_finite_json_float,
            parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, ValueError, OverflowError, RecursionError) as exc:
        reject(f"sealed campaign evidence bytes are malformed: {exc}")
        return issues
    if not isinstance(serialized_campaign, dict):
        reject("sealed campaign evidence bytes have invalid top level")
        return issues
    try:
        matches_serialized = _same_json_value(serialized_campaign, campaign)
    except RecursionError:
        reject("sealed campaign evidence nesting exceeds validation depth")
        return issues
    if not matches_serialized:
        reject("sealed campaign object differs from artifact bytes")
    campaign = serialized_campaign
    if _parse_utc_evidence_time(campaign.get("sealed_at_utc")) is None:
        reject(
            "sealed campaign seal timestamp is invalid: "
            "metric=sealed_at_utc required=canonical_UTC")
    campaign_source_sha = campaign.get("source_sha")
    if campaign_source_sha != source_sha:
        if (
                isinstance(campaign_source_sha, str) and
                GIT_SHA_RE.fullmatch(campaign_source_sha)):
            reject(
                "sealed campaign source binding mismatch: "
                f"metric=source_sha observed={campaign_source_sha} "
                f"expected={source_sha}")
        else:
            reject(
                "sealed campaign source binding mismatch: "
                "metric=source_sha observed=invalid "
                f"expected={source_sha}")

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
    # The sealer derives this from the admitted host boot and every raw/swapz
    # arm, independently of the RAM trace's own host-boot assertion.
    if campaign.get("arm_boot_consistent") is not True:
        reject(
            "sealed campaign arm boot binding mismatch: "
            "metric=arm_boot_consistent required=true_same_admitted_boot")
    # Campaign/performance disposition is a release-performance gate. The
    # five-argument structural path deliberately keeps independently sealed
    # capacity/RAM measurements available even when performance failed.
    if release_validation and (
            campaign.get("campaign_status") != "PASS" or
            campaign.get("qualification_status") != "PASS"):
        reject("sealed campaign qualification is not PASS")
    physical_audit = campaign.get("physical_evidence_audit")
    if release_validation:
        if not isinstance(physical_audit, dict):
            reject(_malformed_physical_evidence_issue(
                "physical_evidence_audit", "physical_evidence_audit",
                "dict", physical_audit))
        else:
            audit_diagnostics = physical_audit.get("diagnostics")
            if not isinstance(audit_diagnostics, list):
                reject(_malformed_physical_evidence_issue(
                    "physical_evidence_audit",
                    "physical_evidence_audit.diagnostics",
                    "list", audit_diagnostics))
            else:
                for diagnostic in audit_diagnostics:
                    if not isinstance(diagnostic, dict):
                        reject(_malformed_physical_evidence_issue(
                            "physical_evidence_audit",
                            "physical_evidence_audit.diagnostics[]",
                            "dict", diagnostic))
                        break

            first_failure = physical_audit.get("first_failed_evidence")
            if first_failure is not None:
                if not isinstance(first_failure, dict):
                    reject(_malformed_physical_evidence_issue(
                        "physical_evidence_audit",
                        "physical_evidence_audit.first_failed_evidence",
                        "dict", first_failure))
                else:
                    failure_workload = first_failure.get("workload")
                    if (
                            not isinstance(failure_workload, str) or
                            failure_workload not in producer_workloads):
                        reject(_malformed_physical_evidence_issue(
                            "physical_evidence_audit",
                            "physical_evidence_audit."
                            "first_failed_evidence.workload",
                            "str", failure_workload))
                    elif (
                            first_failure.get("metric") == "arm.verdict" and
                            not _physical_producer_failure_diagnostic_is_valid(
                                physical_audit, first_failure)):
                        reject(
                            "sealed campaign physical evidence producer FAIL "
                            "diagnostic cannot authenticate the first failure: "
                            "phase=physical_evidence_audit "
                            "failed_evidence_field=physical_evidence_audit."
                            "diagnostics[].producer_failure_binding "
                            "expected_schema_class=current_authenticated_"
                            "terminal_measurement_FAIL "
                            "observed_schema_class=missing_or_contradictory "
                            "verdict=BLOCKED "
                            "reason=producer_diagnostic_cannot_authenticate_"
                            "measurement_failure "
                            "safe_action=recapture_and_reseal_campaign")

            audit_counts = physical_audit.get("cohort_pair_counts")
            if (
                    not isinstance(audit_counts, dict) or
                    set(audit_counts) != set(producer_workloads)):
                reject(_malformed_physical_evidence_issue(
                    "physical_evidence_audit",
                    "physical_evidence_audit.cohort_pair_counts",
                    "dict", audit_counts))
            else:
                malformed_count = False
                for count in audit_counts.values():
                    if not isinstance(count, dict):
                        reject(_malformed_physical_evidence_issue(
                            "physical_evidence_audit",
                            "physical_evidence_audit."
                            "cohort_pair_counts[].count",
                            "dict", count))
                        malformed_count = True
                        break
                    for field in (
                            "required_pairs", "attempted_pairs",
                            "accepted_pairs"):
                        if type(count.get(field)) is not int:
                            reject(_malformed_physical_evidence_issue(
                                "physical_evidence_audit",
                                "physical_evidence_audit."
                                f"cohort_pair_counts[].{field}",
                                "int", count.get(field)))
                            malformed_count = True
                            break
                    if malformed_count:
                        break
    if campaign.get("evaluation_protocol") != "v2":
        reject("sealed campaign did not use the required v2 protocol")
    if (
            target is None or
            _normalize_campaign_target(campaign.get("target")) != target):
        reject("sealed campaign authorized target binding mismatch")

    target_binding = campaign.get("qualification_target_binding")
    if not _physical_qualification_target_binding_is_valid(
            target_binding, target):
        reject(
            "sealed campaign qualification target binding cannot authenticate "
            "target/parent identity: phase=qualification_target_binding "
            "failed_evidence_field=qualification_target_binding "
            "expected_schema_class=current_physical_target_parent_exact "
            "observed_schema_class=invalid_incomplete_or_mismatched "
            "expected_identity_class=authorized_target_and_parent "
            "observed_identity_class=unverifiable verdict=BLOCKED "
            "reason=target_parent_identity_cannot_authenticate "
            "safe_action=recapture_and_reseal_campaign")

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
                type(page_bytes) is not int or page_bytes != 4096 or
                type(logical_pages) is not int or logical_pages <= 0 or
                type(logical_capacity_bytes) is not int or
                logical_capacity_bytes <= 0 or
                logical_pages > RAM_TRACE_VALIDATOR["MAX_UINT32"] or
                logical_capacity_bytes > RAM_TRACE_VALIDATOR["MAX_UINT64"] or
                RAM_TRACE_VALIDATOR["_checked_product"](
                    logical_pages, page_bytes,
                    RAM_TRACE_VALIDATOR["MAX_UINT64"]) != logical_capacity_bytes or
                target is None or logical_capacity_bytes > target[1] or
                logical_pages != RAM_TRACE_VALIDATOR[
                    "maximum_logical_pages_for_partition"](
                        target[1] if target is not None else None,
                        size_t_max=RAM_TRACE_VALIDATOR["MAX_UINT64"]) or
                type(peak_ram_bytes) is not int or
                not 0 < peak_ram_bytes <= RAM_TRACE_VALIDATOR["MAX_UINT64"]):
            reject("sealed campaign capacity/RAM evidence is invalid")
        else:
            try:
                ram_summary = RAM_TRACE_VALIDATOR[
                    "validate_metadata_ram_trace"](
                        capacity_and_ram.get("metadata_ram_trace"),
                        source_sha=source_sha,
                        mapper_uuid=capacity_and_ram.get("mapper_uuid"),
                        expected_peak_ram_bytes=peak_ram_bytes)
                if not _same_json_value(
                        capacity_and_ram.get("metadata_ram_summary"),
                        ram_summary):
                    reject(
                        "sealed campaign RAM trace summary does not match "
                        "raw samples")
                RAM_TRACE_VALIDATOR["validate_metadata_ram_arm_binding"](
                    capacity_and_ram.get("metadata_ram_trace"),
                    capacity_and_ram.get("metadata_ram_arm_binding"))
                RAM_TRACE_VALIDATOR["validate_metadata_ram_host_binding"](
                    capacity_and_ram.get("metadata_ram_trace"),
                    capacity_and_ram.get("metadata_ram_host_binding"))
                # Seal time must follow the host-after snapshot; an older
                # seal cannot authenticate a later loaded-host capture.
                sealed_at = campaign.get("sealed_at_utc")
                host_after = capacity_and_ram[
                    "metadata_ram_host_binding"]["host_after_captured_at_utc"]
                sealed_time = _parse_utc_evidence_time(sealed_at)
                captured_time = _parse_utc_evidence_time(host_after)
                if sealed_time is None:
                    raise ValueError(
                        "metric=sealed_at_utc observed=invalid "
                        "required=UTC_after_host_capture")
                if captured_time is None:
                    raise ValueError(
                        "metric=host_after_captured_at_utc observed=invalid "
                        "required=canonical_loaded_host_UTC")
                if sealed_time < captured_time:
                    raise ValueError(
                        "metric=sealed_at_utc "
                        f"observed={sealed_at[:80]!r} "
                        f"minimum={host_after[:80]!r} "
                        "required=not_before_host_after_capture")
            except ValueError as exc:
                reject(f"sealed campaign RAM trace is invalid: {exc}")

    stability = campaign.get("host_stability")
    if not _physical_host_stability_is_valid(stability):
        reject(
            "sealed campaign host stability is not STABLE or complete")

    expected_lower_major_minor = None
    if isinstance(target_binding, dict):
        boundary_expected = target_binding.get("expected")
        if isinstance(boundary_expected, dict):
            expected_lower_major_minor = boundary_expected.get(
                "lower_major_minor")
    boundaries = campaign.get("admitted_device_boundary")
    if (
            not isinstance(boundaries, dict) or
            set(boundaries) != {"before", "after"}):
        reject("sealed campaign admitted-device boundary is missing")
    else:
        for phase in ("before", "after"):
            if not _physical_device_boundary_is_quiescent(
                    boundaries.get(phase), expected_lower_major_minor):
                reject(
                    f"sealed campaign target was not quiescent {phase} campaign "
                    "with complete lower-device inventory")

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
            ("metadata_ram_validator", METADATA_RAM_VALIDATOR),
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
        # The separately captured post-teardown trace is an immutable evidence
        # input, not a scalar reconstructed by the replay process. Its bytes
        # must match the embedded sealed trace under the canonical writer.
        if isinstance(capacity_and_ram, dict):
            trace = capacity_and_ram.get("metadata_ram_trace")
            trace_artifact = artifacts.get("metadata_ram_trace")
            if not isinstance(trace, dict) or not _valid_campaign_artifact(
                    trace_artifact):
                reject("sealed campaign RAM trace artifact is missing")
            else:
                canonical = (
                    json.dumps(trace, indent=2, sort_keys=True) + "\n").encode()
                if (trace_artifact["size_bytes"] != len(canonical) or
                        trace_artifact["sha256"] != sha256_bytes(canonical)):
                    reject("sealed campaign RAM trace artifact digest mismatch")
        pairs = artifacts.get("pairs")
        record_count = campaign.get("record_count")
        if not isinstance(pairs, list) or not pairs:
            reject("sealed campaign pair artifact list is empty")
        elif type(record_count) is not int or record_count != len(pairs):
            reject("sealed campaign pair artifact count mismatch")
        if isinstance(pairs, list):
            # Preserve the pre-existing five-argument structural contract.
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

        if release_validation:
            # The current producer audit is evidence, not a trusted summary.
            # Bind its exact schema, admitted source/target and pair counts
            # before either PASS or FAIL can affect release disposition.
            audit_binding_valid = _physical_audit_binding_is_valid(
                physical_audit, source_sha, target, physical_policy,
                producer_workloads, pairs, campaign.get("qualification_status"))
            audit_counts = (
                physical_audit.get("cohort_pair_counts")
                if isinstance(physical_audit, dict) else None)
            producer_required_pairs = sum(
                specification["pairs"]
                for specification in producer_workloads.values())
            # The audit counts analyzer-usable attempts, never an EXCLUDED
            # artifact. Screening may lower accepted_pairs below retained PASS.
            if (isinstance(audit_counts, dict) and isinstance(pairs, list) and
                    len(pairs) <= producer_required_pairs):
                for workload, specification in producer_workloads.items():
                    count = audit_counts.get(workload)
                    if not isinstance(count, dict):
                        continue
                    if set(count) != PHYSICAL_AUDIT_COHORT_COUNT_KEYS:
                        reject(
                            "sealed campaign physical evidence audit count "
                            "schema contradiction: phase=physical_evidence_audit "
                            "failed_evidence_field=physical_evidence_audit."
                            "cohort_pair_counts[] "
                            f"workload={workload} "
                            "expected_schema_class=required_attempted_accepted_exact "
                            "observed_schema_class=missing_or_extra_fields "
                            "original_error=unavailable verdict=BLOCKED "
                            "reason=count_schema_cannot_authenticate_cohort "
                            "safe_action=recapture_and_reseal_campaign")
                    count_fields = (
                        "required_pairs", "attempted_pairs", "accepted_pairs")
                    if any(type(count.get(field)) is not int
                           for field in count_fields):
                        continue
                    observed_pair_count = sum(
                        isinstance(pair, dict) and
                        pair.get("workload") == workload
                        for pair in pairs)
                    retained_pass_count = sum(
                        isinstance(pair, dict) and
                        pair.get("workload") == workload and
                        pair.get("status") == "PASS" and
                        pair.get("excluded") is False
                        for pair in pairs)
                    required_count = specification["pairs"]
                    if count["required_pairs"] != required_count:
                        reject(
                            "sealed campaign physical evidence audit count "
                            "contradiction: phase=physical_evidence_audit "
                            "failed_evidence_field=physical_evidence_audit."
                            "cohort_pair_counts[].required_pairs "
                            f"workload={workload} "
                            "expected_count_class=producer_policy_exact "
                            f"expected_count={required_count} "
                            f"observed_count={count['required_pairs']} "
                            "original_error=unavailable verdict=BLOCKED "
                            "reason=required_count_cannot_authenticate_policy "
                            "safe_action=recapture_and_reseal_campaign")
                    if count["attempted_pairs"] != observed_pair_count:
                        reject(
                            "sealed campaign physical evidence audit count "
                            "contradiction: phase=physical_evidence_audit "
                            "failed_evidence_field=physical_evidence_audit."
                            "cohort_pair_counts[].attempted_pairs "
                            f"workload={workload} "
                            "expected_count_class=retained_pair_manifest_exact "
                            f"expected_count={observed_pair_count} "
                            f"observed_count={count['attempted_pairs']} "
                            "original_error=unavailable verdict=BLOCKED "
                            "reason=attempted_count_cannot_authenticate_manifest "
                            "safe_action=recapture_and_reseal_campaign")
                    accepted_count = count["accepted_pairs"]
                    if not 0 <= accepted_count <= retained_pass_count:
                        reject(
                            "sealed campaign physical evidence audit count "
                            "contradiction: phase=physical_evidence_audit "
                            "failed_evidence_field=physical_evidence_audit."
                            "cohort_pair_counts[].accepted_pairs "
                            f"workload={workload} "
                            "expected_count_class=analysis_usable_within_"
                            "retained_PASS_nonexcluded "
                            f"expected_range=0..{retained_pass_count} "
                            f"observed_count={accepted_count} "
                            "original_error=unavailable verdict=BLOCKED "
                            "reason=count_cannot_authenticate_retained_pairs "
                            "safe_action=recapture_and_reseal_campaign")
            audit_pass_counts = (
                isinstance(audit_counts, dict) and
                all(
                    isinstance(audit_counts.get(workload), dict) and
                    audit_counts[workload].get("attempted_pairs") ==
                    specification["pairs"] and
                    audit_counts[workload].get("accepted_pairs") ==
                    specification["pairs"]
                    for workload, specification in producer_workloads.items()))
            if (
                    not audit_binding_valid or
                    physical_audit.get("status") != "PASS" or
                    physical_audit.get("diagnostics") != [] or
                    physical_audit.get("omitted_diagnostic_count") != 0 or
                    physical_audit.get("first_failed_phase") is not None or
                    physical_audit.get("first_failed_evidence") is not None or
                    not audit_pass_counts):
                required_pairs = sum(
                    specification["pairs"]
                    for specification in producer_workloads.values())
                observed_pairs = (
                    len(pairs) if isinstance(pairs, list) else "invalid")
                observed_audit_source = (
                    physical_audit.get("admitted_source_sha")
                    if isinstance(physical_audit, dict) else None)
                observed_audit_source_class = (
                    "match" if observed_audit_source == source_sha else
                    "mismatch" if _valid_source(observed_audit_source) else
                    "invalid")
                observed_audit_target = (
                    physical_audit.get("admitted_target_partuuid")
                    if isinstance(physical_audit, dict) else None)
                observed_audit_target_class = (
                    "match"
                    if target is not None and observed_audit_target == target[0]
                    else "mismatch"
                    if isinstance(observed_audit_target, str) and
                    bool(observed_audit_target)
                    else "invalid")
                reject(
                    "sealed campaign physical evidence audit is not a complete "
                    "PASS: phase=physical_evidence_audit "
                    "failed_evidence_field=physical_evidence_audit "
                    "expected_schema_class=current_complete_PASS_audit "
                    "observed_schema_class=incomplete_or_contradictory "
                    "expected_source_identity_class=release_source "
                    f"observed_source_identity_class="
                    f"{observed_audit_source_class} "
                    "expected_target_identity_class=authorized_target "
                    f"observed_target_identity_class="
                    f"{observed_audit_target_class} "
                    f"expected_pair_count={required_pairs} "
                    f"observed_pair_count={observed_pairs} "
                    "verdict=BLOCKED reason=audit_cannot_authenticate_campaign "
                    "safe_action=recapture_and_reseal_campaign")

            # A matching record_count only authenticates the supplied list. The
            # independent frozen workload plan defines the complete cohort.
            # The frozen release policy requires 14 pairs, while the current
            # v2 producer also carries separately evaluated amendment cohorts.
            # Amendment pairs never substitute for any frozen workload.
            frozen_required_pairs = sum(
                item["pairs"] for item in frozen_workloads.values())
            observed_pairs = len(pairs) if isinstance(pairs, list) else 0
            observed_frozen_pairs = sum(
                1 for pair in pairs
                if isinstance(pair, dict) and
                isinstance(pair.get("workload"), str) and
                pair.get("workload") in frozen_workloads
            ) if isinstance(pairs, list) else 0
            if observed_frozen_pairs != frozen_required_pairs:
                reject(
                    "sealed campaign frozen pair completeness mismatch: "
                    f"metric=frozen_pairs required={frozen_required_pairs} "
                    f"observed={observed_frozen_pairs} original_status="
                    f"{'PASS' if campaign.get('campaign_status') == 'PASS' else 'non_PASS'}")
            if observed_pairs != producer_required_pairs:
                reject(
                    "sealed campaign producer pair completeness mismatch: "
                    f"metric=total_v2_pairs required={producer_required_pairs} "
                    f"observed={observed_pairs} original_status="
                    f"{'PASS' if campaign.get('campaign_status') == 'PASS' else 'non_PASS'}")
            observed_indices: dict[str, set[int]] = {
                workload: set() for workload in producer_workloads}
            pair_identifiers: set[tuple[str, str]] = set()
            artifact_names: set[str] = set()
            artifact_digests: set[str] = set()
            # Inspect no more than the frozen cohort plus one excess artifact.
            # An oversized list has already failed the independent count gate.
            # The current producer cohort includes frozen plus v2 amendment
            # workloads, so the bounded scan uses that complete producer count.
            # Inspect no more than the complete v2 cohort plus one excess item.
            for pair in (pairs[:producer_required_pairs + 1]
                         if isinstance(pairs, list) else ()):
                if not _valid_campaign_artifact(pair):
                    continue
                if pair["name"] in artifact_names:
                    reject(
                        "sealed campaign contains duplicate pair artifact names")
                artifact_names.add(pair["name"])
                if pair["sha256"] in artifact_digests:
                    reject(
                        "sealed campaign contains duplicate pair artifact digests")
                artifact_digests.add(pair["sha256"])
                workload = pair.get("workload")
                if (
                        not isinstance(workload, str) or
                        workload not in producer_workloads):
                    # Nested JSON evidence is untrusted even when its parent
                    # artifact has valid name, size and digest fields.
                    reject(_malformed_physical_evidence_issue(
                        "pair_manifest", "artifacts.pairs[].workload",
                        "str", workload))
                    continue
                workload_spec = producer_workloads[workload]
                pair_index = pair.get("pair_index")
                pair_id = pair.get("pair_id")
                order = pair.get("order")
                required_count = workload_spec["pairs"]
                if (type(pair_index) is not int or
                        not 1 <= pair_index <= required_count or
                        pair_index in observed_indices[workload]):
                    reject(
                        f"sealed campaign workload={workload} pair identity "
                        f"required=unique_indices_1..{required_count} "
                        "observed=missing_duplicate_or_out_of_range")
                    continue
                observed_indices[workload].add(pair_index)
                if not isinstance(pair_id, str) or not pair_id:
                    reject(_malformed_physical_evidence_issue(
                        "pair_manifest", "artifacts.pairs[].pair_id",
                        "str", pair_id))
                elif (workload, pair_id) in pair_identifiers:
                    reject(
                        f"sealed campaign workload={workload} pair_id "
                        "required=unique_nonempty "
                        "observed=duplicate")
                else:
                    pair_identifiers.add((workload, pair_id))
                if order != workload_spec[
                        "counterbalanced_order"][pair_index - 1]:
                    reject(
                        f"sealed campaign workload={workload} "
                        f"pair_index={pair_index} order differs from "
                        "producer counterbalance")
                if (
                        pair.get("status") != "PASS" or
                        pair.get("excluded") is not False):
                    reject(
                        f"sealed campaign workload={workload} "
                        f"pair_index={pair_index} "
                        "required=PASS_excluded_false "
                        "observed=nonqualifying "
                        f"original_status="
                        f"{'PASS' if pair.get('status') == 'PASS' else 'non_PASS'}")
            for workload, workload_spec in producer_workloads.items():
                required_count = workload_spec["pairs"]
                observed_count = len(observed_indices[workload])
                if observed_count != required_count:
                    evidence_class = (
                        "frozen" if workload in frozen_workloads
                        else "prospective_v2")
                    reject(
                        f"sealed campaign workload={workload} "
                        f"evidence_class={evidence_class} pair completeness "
                        f"required={required_count} observed={observed_count}")
    return issues



def _physical_campaign_failure_is_proven(
        campaign: Any,
        raw: Any,
        source_sha: str,
        policy: dict[str, Any],
        policy_sha256: str | None,
        target: tuple[str, int] | None) -> bool:
    """Authenticate an exact-source producer audit FAIL, not incompleteness."""
    if not _valid_source(source_sha):
        return False
    try:
        record = _bound_json_object(
            campaign, raw, "sealed physical campaign failure evidence")
    except EvidenceError:
        return False
    if (
            record.get("schema") != "swapz-performance-campaign-evidence-v1" or
            record.get("source_sha") != source_sha or
            record.get("campaign_source_sha") != source_sha or
            record.get("pair_source_shas") != [source_sha] or
            record.get("source_consistent") is not True or
            record.get("evaluation_protocol") != "v2" or
            record.get("campaign_status") != "FAIL_OR_INCOMPLETE" or
            record.get("qualification_status") != "FAIL_OR_INCOMPLETE" or
            target is None or
            _normalize_campaign_target(record.get("target")) != target):
        return False
    source_tree_sha = record.get("source_tree_sha")
    if (
            not isinstance(source_tree_sha, str) or
            not GIT_SHA_RE.fullmatch(source_tree_sha) or
            record.get("arm_boot_consistent") is not True):
        return False

    # A producer's failed measurement must still be sealed after any included
    # loaded-host RAM capture. Missing capacity/RAM is an independent gate and
    # does not erase an otherwise authenticated performance failure.
    sealed_time = _parse_utc_evidence_time(record.get("sealed_at_utc"))
    if sealed_time is None:
        return False
    capacity_and_ram = record.get("capacity_and_ram")
    if capacity_and_ram is not None and not isinstance(capacity_and_ram, dict):
        return False
    if isinstance(capacity_and_ram, dict):
        host_binding = capacity_and_ram.get("metadata_ram_host_binding")
        host_after = (
            host_binding.get("host_after_captured_at_utc")
            if isinstance(host_binding, dict) else None)
        host_after_time = _parse_utc_evidence_time(host_after)
        if host_after_time is None or sealed_time < host_after_time:
            return False

    target_binding = record.get("qualification_target_binding")
    if not _physical_qualification_target_binding_is_valid(
            target_binding, target):
        return False
    expected = target_binding["expected"]

    if not _physical_host_stability_is_valid(record.get("host_stability")):
        return False
    boundaries = record.get("admitted_device_boundary")
    expected_lower_major_minor = expected.get("lower_major_minor")
    if (
            not isinstance(boundaries, dict) or
            set(boundaries) != {"before", "after"} or
            any(not _physical_device_boundary_is_quiescent(
                    boundaries.get(phase), expected_lower_major_minor)
                for phase in ("before", "after"))):
        return False

    audit = record.get("physical_evidence_audit")
    artifacts = record.get("artifacts")
    pairs = artifacts.get("pairs") if isinstance(artifacts, dict) else None
    if (
            not isinstance(artifacts, dict) or
            not _valid_campaign_artifact(artifacts.get("host_before")) or
            not _valid_campaign_artifact(artifacts.get("host_after")) or
            not _valid_campaign_artifact(
                artifacts.get("qualification_summary")) or
            not isinstance(pairs, list) or
            type(record.get("record_count")) is not int or
            record["record_count"] != len(pairs)):
        return False
    physical_policy = policy.get("physical_qualification")
    try:
        _, producer_workloads = _physical_campaign_workloads(policy)
    except EvidenceError:
        return False
    first_failure = (
        audit.get("first_failed_evidence")
        if isinstance(audit, dict) else None)
    failure_count_workload = (
        first_failure.get("workload")
        if isinstance(first_failure, dict) else None)
    if (
            not isinstance(failure_count_workload, str) or
            failure_count_workload not in producer_workloads or
            not _physical_audit_binding_is_valid(
                audit, source_sha, target, physical_policy,
                producer_workloads, pairs, record.get("qualification_status"),
                failure_count_workload) or
            audit.get("status") != "FAIL" or
            audit.get("qualification_status") != "FAIL_OR_INCOMPLETE" or
            not _physical_audit_failure_witness_is_valid(
                audit, producer_workloads, pairs)):
        return False
    provenance = record.get("policy")
    if not isinstance(provenance, dict) or policy_sha256 is None:
        return False
    acceptance = provenance.get("acceptance_manifest")
    if (
            not isinstance(acceptance, dict) or
            acceptance.get("sha256") != policy_sha256):
        return False
    for name, path in (
            ("prospective_amendment", PHYSICAL_CAMPAIGN_AMENDMENT),
            ("evaluator", PHYSICAL_CAMPAIGN_EVALUATOR),
            ("evidence_sealer", PHYSICAL_CAMPAIGN_SEALER),
            ("metadata_ram_validator", METADATA_RAM_VALIDATOR)):
        entry = provenance.get(name)
        try:
            expected_digest = sha256_bytes(path.read_bytes())
        except OSError:
            return False
        if (
                not isinstance(entry, dict) or
                entry.get("sha256") != expected_digest):
            return False
    return True


def validate_cold_boot_arm_evidence(
        arm: dict[str, str],
        source_sha: str,
        target: tuple[str, int] | None,
        report_artifacts: dict[str, Any] | None,
        owner_kernel_release: Any) -> list[str]:
    """Validate the durable pre-reboot arm record."""
    issues: list[str] = []

    def reject(message: str) -> None:
        if message not in issues:
            issues.append(message)

    if set(arm) != COLD_BOOT_ARM_KEYS:
        reject("cold-boot arm record field set is non-canonical")
        return issues
    if arm["schema"] != "swapz-primary-boot-arm-v1":
        reject("cold-boot arm record schema is invalid")
    if not BOOT_ID_RE.fullmatch(arm["arm_boot_id"]):
        reject("cold-boot arm boot identity is invalid")
    if arm["arm_kernel_release"] != owner_kernel_release:
        reject("cold-boot arm kernel differs from owner qualification")
    armed_epoch = _bounded_decimal_text(arm["armed_epoch"])
    if armed_epoch is None or armed_epoch <= 0:
        reject("cold-boot arm epoch is invalid")

    size = _bounded_decimal_text(arm["expected_target_size_bytes"])
    if size is None:
        size = -1
    if (
            target is None or arm["expected_partuuid"] != target[0] or
            size != target[1]):
        reject("cold-boot arm authorized target identity mismatch")
    if (
            arm["expected_target_removable"] != "1" or
            (arm["expected_target_serial"] == "unavailable" and
             arm["expected_target_wwn"] == "unavailable")):
        reject("cold-boot arm stable removable-parent identity is invalid")

    module_hash = (
        report_artifacts.get("module_sha256")
        if isinstance(report_artifacts, dict) else None)
    if arm["expected_module_sha256"] != module_hash:
        reject("cold-boot arm module artifact binding mismatch")
    if (
            arm["expected_module_source_sha"] != source_sha or
            arm["expected_module_source_clean"] != "1"):
        reject("cold-boot arm module source binding is invalid")
    return issues


def validate_cold_boot_evidence(
        cold_boot: dict[str, str],
        source_sha: str,
        target: tuple[str, int] | None,
        report_artifacts: dict[str, Any] | None,
        owner_kernel_release: Any,
        cold_boot_arm: dict[str, str] | None = None) -> list[str]:
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
    if cold_boot_arm is None:
        reject("persistent cold-boot report has no validated arm record")
    else:
        if cold_boot["armed_boot_id"] != cold_boot_arm.get("arm_boot_id"):
            reject("persistent cold-boot report is not bound to the arm boot")
        for observed_key, armed_key in (
                ("selected_partuuid", "expected_partuuid"),
                ("selected_target_size_bytes", "expected_target_size_bytes"),
                ("selected_target_model", "expected_target_model"),
                ("selected_target_serial", "expected_target_serial"),
                ("selected_target_wwn", "expected_target_wwn"),
                ("selected_target_transport", "expected_target_transport"),
                ("selected_target_removable", "expected_target_removable")):
            if cold_boot[observed_key] != cold_boot_arm.get(armed_key):
                reject(
                    "persistent cold-boot selected target differs from arm record")
                break
    if (
            not isinstance(owner_kernel_release, str) or
            cold_boot["kernel_release"] != owner_kernel_release):
        reject("persistent cold-boot kernel differs from owner qualification")
    if target is None:
        reject("persistent cold-boot authorized target is unavailable")
    else:
        selected_size = _bounded_decimal_text(
            cold_boot["selected_target_size_bytes"])
        if selected_size is None:
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
    observed_source = cold_boot["loaded_module_build_source_sha"]
    observed_module = cold_boot["module_artifact_sha256"]
    evidence_identity_diagnostic = (
        f"required_source_sha={source_sha} "
        f"observed_source_sha={observed_source if _valid_source(observed_source) else 'invalid'} "
        f"required_module_sha256={module_hash if isinstance(module_hash, str) and SHA256_RE.fullmatch(module_hash) else 'invalid'} "
        f"observed_module_sha256={observed_module if SHA256_RE.fullmatch(observed_module) else 'invalid'} "
    )

    run_id = cold_boot["active_transaction_run_id"]
    expected_uuid = f"SWAPZ-PRIMARY-{run_id}"
    if (
            not RUN_ID_RE.fullmatch(run_id) or
            cold_boot["expected_dm_uuid"] != expected_uuid or
            cold_boot["dm_uuid"] != expected_uuid):
        reject("persistent cold-boot mapper transaction identity is invalid")
    mapper_sysfs_name = cold_boot["mapper_sysfs_dm_name"]
    if mapper_sysfs_name != "swapz-primary":
        safe_mapper_sysfs_name = (
            mapper_sysfs_name
            if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", mapper_sysfs_name)
            else "invalid")
        reject(
            "persistent cold-boot mapper sysfs identity is invalid: "
            "evidence_class=persistent_cold_boot "
            "first_failed_phase=mapper_identity "
            "required_mapper_sysfs_dm_name=swapz-primary "
            f"observed_mapper_sysfs_dm_name={safe_mapper_sysfs_name} "
            f"{evidence_identity_diagnostic}"
            "verdict=BLOCKED reason=wrong_mapper_sysfs_identity")

    logical_sectors = _bounded_decimal_text(cold_boot["dm_logical_sectors"])
    expected_sectors = _bounded_decimal_text(
        cold_boot["expected_dm_logical_sectors"])
    logical_bytes = _bounded_decimal_text(cold_boot["dm_logical_bytes"])
    swap_size_kib = _bounded_decimal_text(cold_boot["swap_size_kib"])
    if any(value is None for value in (
            logical_sectors, expected_sectors, logical_bytes, swap_size_kib)):
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
    swap_total_entries = _bounded_decimal_text(cold_boot["swap_total_entries"])
    swap_used_kib = _bounded_decimal_text(cold_boot["swap_used_kib"])
    if (
            swap_total_entries is None or swap_total_entries < 1 or
            swap_used_kib is None or swap_used_kib > swap_size_kib or
            cold_boot["swap_mapper_entries"] != "1" or
            cold_boot["swap_type"] != "partition" or
            cold_boot["swap_priority"] != "-1" or
            logical_bytes <= 4096 or
            swap_size_kib != logical_bytes // 1024 - 4):
        reject(
            "persistent cold-boot active swap evidence is inconsistent: "
            "evidence_class=persistent_cold_boot first_failed_phase=active_swap "
            "required_total_entries>=1 "
            f"observed_total_entries={swap_total_entries if swap_total_entries is not None else 'invalid'} "
            f"required_used_kib=0..{swap_size_kib if swap_size_kib >= 0 else 'invalid'} "
            f"observed_used_kib={swap_used_kib if swap_used_kib is not None else 'invalid'} "
            f"{evidence_identity_diagnostic}"
            "verdict=BLOCKED reason=contradictory_or_malformed_swap_inventory")
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

    gc_counter_fields = (
        "gc_victims", "gc_pages", "gc_no_headroom_skips",
        "gc_reserve_segments_initial", "gc_reserve_segments_current",
        "gc_destination_advances", "window_gc_pressure",
    )
    gc_counter_maximum = 10**18 - 1
    gc_counters = {}
    for field in gc_counter_fields:
        counter_text = cold_boot[field]
        counter_value = _bounded_decimal_text(
            counter_text, maximum=gc_counter_maximum)
        gc_counters[field] = (
            counter_value
            if counter_value is not None and str(counter_value) == counter_text
            else None)
    invalid_gc_counters = [
        field for field, value in gc_counters.items() if value is None]
    if invalid_gc_counters:
        reject(
            "persistent cold-boot GC telemetry is malformed: "
            "evidence_class=persistent_cold_boot "
            "first_failed_phase=gc_telemetry "
            "required_counter_format=canonical_unsigned_decimal_0..999999999999999999 "
            f"observed_invalid_counter_count={len(invalid_gc_counters)} "
            f"{evidence_identity_diagnostic}"
            "verdict=BLOCKED reason=malformed_gc_progress_telemetry")
    else:
        reserve_initial = gc_counters["gc_reserve_segments_initial"]
        reserve_current = gc_counters["gc_reserve_segments_current"]
        if (
                reserve_initial == 0 or reserve_current == 0 or
                reserve_current > reserve_initial):
            reject(
                "persistent cold-boot GC reserve telemetry is inconsistent: "
                "evidence_class=persistent_cold_boot "
                "first_failed_phase=gc_telemetry "
                "required_reserve=initial>0,current>0,current<=initial "
                f"observed_initial={reserve_initial} "
                f"observed_current={reserve_current} "
                f"{evidence_identity_diagnostic}"
                "verdict=BLOCKED reason=invalid_gc_reserve_telemetry")
    if cold_boot["failure_reasons"] or cold_boot["incomplete_reasons"]:
        reject("persistent cold-boot report contains failure/incomplete reasons")
    return issues


def validate_cold_boot_failure_evidence(
        cold_boot: dict[str, str],
        source_sha: str,
        target: tuple[str, int] | None,
        report_artifacts: dict[str, Any] | None,
        owner_kernel_release: Any,
        cold_boot_arm: dict[str, str] | None = None) -> list[str]:
    """Authenticate a complete exact-source retained cold-boot FAIL."""
    issues: list[str] = []

    def reject(message: str) -> None:
        if message not in issues:
            issues.append(message)

    if set(cold_boot) != COLD_BOOT_REPORT_KEYS:
        reject(
            "persistent cold-boot failure report field set is non-canonical: "
            "evidence_class=persistent_cold_boot "
            "first_failed_phase=failure_authentication "
            f"required_field_count={len(COLD_BOOT_REPORT_KEYS)} "
            f"observed_field_count={len(cold_boot)} "
            "verdict=BLOCKED reason=malformed_failure_report")
        return issues
    if cold_boot["schema"] != "swapz-primary-cold-boot-v1":
        reject(
            "persistent cold-boot failure report schema is invalid: "
            "evidence_class=persistent_cold_boot "
            "first_failed_phase=failure_authentication "
            "verdict=BLOCKED reason=malformed_failure_report")
    if cold_boot["status"] != "FAIL" or cold_boot["cold_boot_observed"] != "yes":
        reject(
            "persistent cold-boot failure report is not an observed FAIL: "
            "evidence_class=persistent_cold_boot "
            "first_failed_phase=failure_authentication "
            "required_status=FAIL required_cold_boot_observed=yes "
            f"observed_status={cold_boot['status'] if cold_boot['status'] in ('FAIL', 'PASS', 'INCOMPLETE') else 'invalid'} "
            "verdict=BLOCKED reason=nonterminal_or_inconclusive_failure")
    if (
            not BOOT_ID_RE.fullmatch(cold_boot["boot_id"]) or
            not BOOT_ID_RE.fullmatch(cold_boot["armed_boot_id"]) or
            cold_boot["boot_id"] == cold_boot["armed_boot_id"]):
        reject(
            "persistent cold-boot failure boot identity is invalid: "
            "evidence_class=persistent_cold_boot "
            "first_failed_phase=failure_authentication "
            "verdict=BLOCKED reason=invalid_boot_identity")
    if cold_boot_arm is None:
        reject(
            "persistent cold-boot failure report has no validated arm record: "
            "evidence_class=persistent_cold_boot "
            "first_failed_phase=failure_authentication "
            "verdict=BLOCKED reason=missing_arm_authentication")
    else:
        if cold_boot["armed_boot_id"] != cold_boot_arm.get("arm_boot_id"):
            reject(
                "persistent cold-boot failure report is not bound to the arm boot: "
                "evidence_class=persistent_cold_boot "
                "first_failed_phase=failure_authentication "
                "verdict=BLOCKED reason=arm_boot_mismatch")
        for observed_key, armed_key in (
                ("selected_partuuid", "expected_partuuid"),
                ("selected_target_size_bytes", "expected_target_size_bytes"),
                ("selected_target_model", "expected_target_model"),
                ("selected_target_serial", "expected_target_serial"),
                ("selected_target_wwn", "expected_target_wwn"),
                ("selected_target_transport", "expected_target_transport"),
                ("selected_target_removable", "expected_target_removable")):
            if cold_boot[observed_key] != cold_boot_arm.get(armed_key):
                reject(
                    "persistent cold-boot failure target differs from arm record: "
                    "evidence_class=persistent_cold_boot "
                    "first_failed_phase=failure_authentication "
                    "verdict=BLOCKED reason=wrong_target_identity")
                break

    if (
            not isinstance(owner_kernel_release, str) or
            cold_boot["kernel_release"] != owner_kernel_release):
        reject(
            "persistent cold-boot failure kernel differs from owner qualification: "
            "evidence_class=persistent_cold_boot "
            "first_failed_phase=failure_authentication "
            "verdict=BLOCKED reason=wrong_kernel_identity")

    selected_size = _bounded_decimal_text(cold_boot["selected_target_size_bytes"])
    if (
            target is None or selected_size is None or
            cold_boot["selected_partuuid"] != target[0] or
            selected_size != target[1] or
            not MAJOR_MINOR_RE.fullmatch(
                cold_boot["selected_target_major_minor"]) or
            cold_boot["selected_target_removable"] != "1" or
            not re.fullmatch(
                r"[A-Za-z0-9._-]+", cold_boot["selected_target_parent"]) or
            (cold_boot["selected_target_serial"] == "unavailable" and
             cold_boot["selected_target_wwn"] == "unavailable")):
        reject(
            "persistent cold-boot failure target identity is not exact: "
            "evidence_class=persistent_cold_boot "
            "first_failed_phase=failure_authentication "
            f"required_target={target if target is not None else 'invalid'} "
            "observed_target=invalid_or_mismatched "
            "verdict=BLOCKED reason=wrong_target_identity")

    module_hash = (
        report_artifacts.get("module_sha256")
        if isinstance(report_artifacts, dict) else None)
    observed_source = cold_boot["loaded_module_build_source_sha"]
    observed_module = cold_boot["module_artifact_sha256"]
    if (
            not isinstance(module_hash, str) or
            not SHA256_RE.fullmatch(module_hash) or
            cold_boot["module_artifact_sha256"] != module_hash or
            cold_boot["module_build_source_sha"] != source_sha or
            cold_boot["module_build_source_clean"] != "1" or
            observed_source != source_sha or
            cold_boot["loaded_module_build_source_clean"] != "1"):
        reject(
            "persistent cold-boot failure source/artifact identity is not exact: "
            "evidence_class=persistent_cold_boot "
            "first_failed_phase=failure_authentication "
            f"required_source_sha={source_sha} "
            f"observed_source_sha={observed_source if _valid_source(observed_source) else 'invalid'} "
            f"required_module_sha256={module_hash if isinstance(module_hash, str) and SHA256_RE.fullmatch(module_hash) else 'invalid'} "
            f"observed_module_sha256={observed_module if SHA256_RE.fullmatch(observed_module) else 'invalid'} "
            "verdict=BLOCKED reason=wrong_source_or_artifact_identity")

    failure_reasons = cold_boot["failure_reasons"]
    if (
            not failure_reasons or
            re.fullmatch(r"[a-z0-9_]+(?:,[a-z0-9_]+)*",
                         failure_reasons) is None):
        reject(
            "persistent cold-boot failure reason set is missing or malformed: "
            "evidence_class=persistent_cold_boot "
            "first_failed_phase=failure_authentication "
            "required_failure_reason_count>=1 observed_failure_reason_count=0_or_invalid "
            "verdict=BLOCKED reason=unauthenticated_failure_disposition")
    if cold_boot["incomplete_reasons"]:
        reject(
            "persistent cold-boot failure report is also incomplete: "
            "evidence_class=persistent_cold_boot "
            "first_failed_phase=failure_authentication "
            "required_incomplete_reason_count=0 observed_incomplete_reason_count>=1 "
            "verdict=BLOCKED reason=inconclusive_failure_evidence")
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
        cold_boot_evidence_raw: bytes | None = None,
        cold_boot_arm_evidence: dict[str, str] | None = None,
        cold_boot_arm_evidence_raw: bytes | None = None) -> dict[str, Any]:
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
    if not isinstance(evidence, dict):
        block_code("release evidence object is missing or invalid")
        evidence = {}

    try:
        test_results = _bound_json_object(
            test_results, test_results_raw, "owner qualification report")
    except EvidenceError as exc:
        block_code(str(exc))
        try:
            test_results = _parse_json_object_bytes(
                test_results_raw, "owner qualification report")
        except EvidenceError:
            test_results = {}

    frozen_peak_ram_limit = _tracked_frozen_peak_ram_limit()
    try:
        policy = _bound_json_object(
            policy, policy_raw, "production acceptance policy")
        policy_sha256, peak_ram_limit = validate_acceptance_policy(
            policy, policy_raw)
    except EvidenceError as exc:
        policy_sha256 = None
        peak_ram_limit = None
        block_code(str(exc))
        try:
            policy = _parse_json_object_bytes(
                policy_raw, "production acceptance policy")
        except EvidenceError:
            policy = {}

    owner_failure_proven = False
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
        observed_source = test_results.get("source_sha")
        block_code(
            "owner qualification: evidence_class=owner_make_test "
            f"metric=source_sha required={source_sha} "
            f"observed={observed_source if _valid_source(observed_source) else 'invalid'}")
    if test_results.get("qualification") != "RAM_BACKED_NULL_BLK_ONLY":
        block_code("owner qualification scope is unexpected")
    stages = test_results.get("stages")
    if not isinstance(stages, list):
        block_code("owner qualification stages are missing")
    else:
        stage_rows = [row for row in stages if isinstance(row, dict)]
        stage_names = [row.get("name") for row in stage_rows]
        exact_stage_set = (
            len(stage_rows) == len(REQUIRED_STAGES) and
            len(stage_rows) == len(stages) and
            stage_names == list(REQUIRED_STAGES))
        if not exact_stage_set:
            block_code(
                "owner qualification stage set/order is not exactly canonical")
        first_failed = next((
            row for row in stage_rows
            if row.get("status") != "PASS" or
            type(row.get("exit_code")) is not int or
            row.get("exit_code") != 0), None)
        if first_failed is not None:
            block_code(
                "one or more mandatory owner qualification stages are not "
                "PASS with exit code 0")
            failed_phase = first_failed.get("failed_phase")
            safe_phase = (
                failed_phase if isinstance(failed_phase, str) and
                re.fullmatch(r"[A-Za-z0-9_. -]{1,64}", failed_phase)
                else "unavailable")
            original_status = first_failed.get("status")
            safe_status = (
                original_status if isinstance(original_status, str) and
                original_status in ("PASS", "FAIL", "BLOCKED", "INCOMPLETE")
                else "invalid")
            block_code(
                "owner qualification: evidence_class=owner_make_test "
                f"first_failed_phase={safe_phase} "
                f"original_status={safe_status} required=PASS "
                f"observed={safe_status}")
            canonical_prefix = (
                0 < len(stage_rows) <= len(REQUIRED_STAGES) and
                len(stage_rows) == len(stages) and
                stage_names == list(REQUIRED_STAGES[:len(stage_rows)]))
            owner_failure_proven = (
                _valid_source(source_sha) and
                canonical_prefix and
                test_results.get("overall") == "FAIL" and
                test_results.get("source_sha") == source_sha and
                test_results.get("tested_commit_sha") == source_sha and
                first_failed.get("status") == "FAIL" and
                type(first_failed.get("exit_code")) is int and
                first_failed["exit_code"] != 0)
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
        page_size_bytes = release_host.get("page_size_bytes")
        if type(page_size_bytes) is not int or page_size_bytes != 4096:
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
    capacity_prediction = _capacity_index_prediction(target)

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
        if not _valid_observed_at_utc(record.get("observed_at_utc")):
            blocker(f"{name}: observation timestamp is missing or invalid")
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
            required_hashes = qualified.get("hashes")
            for artifact_key in ARTIFACT_KEYS:
                required_hash = (
                    required_hashes.get(artifact_key)
                    if isinstance(required_hashes, dict) else None)
                observed_hash = (
                    report_artifacts.get(artifact_key)
                    if isinstance(report_artifacts, dict) else None)
                if (required_hash != observed_hash and
                        all(isinstance(value, str) and
                            SHA256_RE.fullmatch(value)
                            for value in (required_hash, observed_hash))):
                    block_code(
                        "owner qualification: evidence_class=qualified_artifacts "
                        f"metric={artifact_key} required={required_hash} "
                        f"observed={observed_hash}")

    ci = pass_record("required_ci")
    if ci is not None:
        runs = ci.get("runs")
        valid_runs = {}
        if isinstance(runs, list):
            if (len(runs) != len(REQUIRED_CI_WORKFLOWS) or
                    any(not isinstance(run, dict) or
                        run.get("workflow") not in REQUIRED_CI_WORKFLOWS
                        for run in runs)):
                block_code("required_ci: workflow run set has extra or malformed entries")
            # An Actions run ID is globally unique, not reusable across jobs.
            run_ids = [int(run["run_id"]) for run in runs
                       if isinstance(run, dict) and
                       _valid_run_id(run.get("run_id"))]
            if len(run_ids) != len(set(run_ids)):
                block_code("required_ci: duplicate GitHub workflow run IDs")
            for run in runs:
                if not isinstance(run, dict):
                    continue
                workflow = run.get("workflow")
                if workflow in REQUIRED_CI_WORKFLOWS:
                    valid_runs.setdefault(workflow, []).append(run)
        for workflow in REQUIRED_CI_WORKFLOWS:
            rows = valid_runs.get(workflow, [])
            if (
                    len(rows) != 1 or
                    rows[0].get("head_sha") != source_sha or
                    rows[0].get("result") != "PASS" or
                    rows[0].get("status") != "completed" or
                    rows[0].get("conclusion") != "success" or
                    not _valid_run_id(rows[0].get("run_id"))):
                block_code(
                    f"required_ci: {workflow} is not an exact-source "
                    "completed-success PASS with a concrete run ID")
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
            critical.get("count") != 0 or
            critical.get("issues") != []):
        block_code(
            "unresolved critical correctness issue count/list is inconsistent")

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

    real_swap_failure_proven = False
    real_swap_receipt = release.get("real_linux_swap")
    if (
            isinstance(real_swap_receipt, dict) and
            real_swap_receipt.get("status") in ("PASS", "FAIL", "BLOCKED") and
            real_swap_receipt.get("current") is True and
            real_swap_receipt.get("source_sha") == source_sha and
            _valid_observed_at_utc(real_swap_receipt.get("observed_at_utc")) and
            target is not None and
            _normalize_target(real_swap_receipt.get("target")) == target and
            policy_sha256 is not None and
            real_swap_receipt.get("policy_sha256") == policy_sha256 and
            real_swap_evidence is not None and
            real_swap_evidence_raw is not None and
            real_swap_receipt.get("evidence_sha256") ==
            sha256_bytes(real_swap_evidence_raw)):
        real_swap_failure_proven = _real_swap_failure_is_proven(
            real_swap_evidence, real_swap_evidence_raw, source_sha,
            test_results_raw, policy, policy_sha256, report_artifacts, target)
        if real_swap_failure_proven:
            block_code(
                "real_linux_swap: exact-source terminal qualification "
                "execution is FAIL")

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
            swap_issues = validate_real_swap_evidence(
                real_swap_evidence, real_swap_evidence_raw, source_sha,
                test_results_raw, policy, policy_sha256,
                report_artifacts, target)
            if swap_issues:
                original_status = (
                    real_swap_evidence.get("status")
                    if isinstance(real_swap_evidence, dict) else None)
                safe_status = (
                    original_status if original_status in (
                        "PASS", "FAIL", "BLOCKED") else "invalid")
                artifact_digest = (
                    sha256_bytes(real_swap_evidence_raw)
                    if isinstance(real_swap_evidence_raw, bytes) else "invalid")
                observed_source = (
                    real_swap_evidence.get("source_sha")
                    if isinstance(real_swap_evidence, dict) else None)
                safe_observed_source = (
                    observed_source if _valid_source(observed_source)
                    else "invalid")
                evidence_phase = (
                    real_swap_evidence.get("phase")
                    if isinstance(real_swap_evidence, dict) else None)
                safe_phase = (
                    evidence_phase if isinstance(evidence_phase, str) and
                    re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", evidence_phase)
                    else "cycle_validation")
                required_artifact = (
                    real_swap_receipt.get("evidence_sha256")
                    if isinstance(real_swap_receipt, dict) and
                    isinstance(real_swap_receipt.get("evidence_sha256"), str) and
                    SHA256_RE.fullmatch(real_swap_receipt["evidence_sha256"])
                    else "invalid")
                block_code(
                    "real_linux_swap: evidence_class=persistent_real_swap "
                    f"first_failed_phase={safe_phase} "
                    f"original_status={safe_status} "
                    f"required_source_sha={source_sha} "
                    f"observed_source_sha={safe_observed_source} "
                    f"required_artifact_sha256={required_artifact} "
                    f"observed_artifact_sha256={artifact_digest}")
            for issue in swap_issues:
                block_code("real_linux_swap: " + issue)

    capacity = pass_record("maximum_capacity_and_ram")
    require_target("maximum_capacity_and_ram", capacity)
    require_policy("maximum_capacity_and_ram", capacity)
    # A page-rounded index estimate is an admission calculation, never proof
    # of full-capacity loaded construction or the measured host RAM peak.
    memory_measurement = {
        "status": "NOT_MEASURED",
        "observed_peak_ram_bytes": None,
        "limit_bytes": (
            peak_ram_limit
            if peak_ram_limit is not None else frozen_peak_ram_limit),
        "initialization_peak_ram_bytes": None,
        "initialization_samples": None,
        "steady_peak_ram_bytes": None,
        "steady_samples": None,
        "gc_peak_ram_bytes": None,
        "gc_samples": None,
        "teardown_recovery": "NOT_MEASURED",
        "teardown_recovery_samples": None,
        "teardown_recovery_span_ns": None,
    }
    campaign_issues = None
    campaign_structural_issues = None
    campaign_sealed_at = None
    campaign_sealed_time = None
    physical_campaign_failure_proven = False
    physical_campaign_failure_receipt_issue = None
    physical_campaign_receipt = release.get("sustained_physical_performance")
    receipt_source = (
        physical_campaign_receipt.get("source_sha")
        if isinstance(physical_campaign_receipt, dict) else None)
    receipt_target = (
        _normalize_target(physical_campaign_receipt.get("target"))
        if isinstance(physical_campaign_receipt, dict) else None)
    receipt_observed_at = (
        physical_campaign_receipt.get("observed_at_utc")
        if isinstance(physical_campaign_receipt, dict) else None)
    receipt_binding_valid = (
        isinstance(physical_campaign_receipt, dict) and
        physical_campaign_receipt.get("status") in (
            "PASS", "FAIL", "BLOCKED") and
        physical_campaign_receipt.get("current") is True and
        receipt_source == source_sha and
        _valid_observed_at_utc(receipt_observed_at) and
        target is not None and receipt_target == target and
        policy_sha256 is not None and
        physical_campaign_receipt.get("policy_sha256") == policy_sha256 and
        physical_campaign_evidence is not None and
        physical_campaign_evidence_raw is not None and
        physical_campaign_receipt.get("evidence_sha256") ==
        sha256_bytes(physical_campaign_evidence_raw))
    if (
            physical_campaign_evidence is not None and
            physical_campaign_evidence_raw is not None):
        if not receipt_binding_valid:
            physical_campaign_failure_receipt_issue = (
                "campaign_receipt_binding")
        else:
            receipt_time = _parse_utc_evidence_time(receipt_observed_at)
            failure_sealed_at = (
                physical_campaign_evidence.get("sealed_at_utc")
                if isinstance(physical_campaign_evidence, dict) else None)
            failure_sealed_time = _parse_utc_evidence_time(failure_sealed_at)
            if (
                    failure_sealed_time is not None and
                    receipt_time is not None and
                    receipt_time < failure_sealed_time):
                physical_campaign_failure_receipt_issue = (
                    "campaign_receipt_chronology")
            else:
                physical_campaign_failure_proven = (
                    _physical_campaign_failure_is_proven(
                        physical_campaign_evidence,
                        physical_campaign_evidence_raw,
                        source_sha, policy, policy_sha256, target))
                if physical_campaign_failure_proven:
                    block_code(
                        "sustained_physical_performance: exact-source campaign "
                        "contains producer-proven FAIL execution evidence")
    if (physical_campaign_evidence is not None and
            physical_campaign_evidence_raw is not None):
        # Capacity/RAM is an independent measured gate. Release-performance
        # completeness must block the release without erasing valid sealed
        # capacity/RAM samples from the same artifact.
        campaign_structural_issues = validate_physical_campaign_evidence(
            physical_campaign_evidence, physical_campaign_evidence_raw,
            source_sha, policy_sha256, target)
        campaign_issues = validate_physical_campaign_evidence(
            physical_campaign_evidence, physical_campaign_evidence_raw,
            source_sha, policy_sha256, target, policy)
        if campaign_issues:
            original_status = (
                physical_campaign_evidence.get("campaign_status")
                if isinstance(physical_campaign_evidence, dict) else None)
            safe_status = (
                original_status if original_status in (
                    "PASS", "FAIL", "BLOCKED",
                    "BLOCKED_PHYSICAL_EVIDENCE", "FAIL_OR_INCOMPLETE")
                else "invalid")
            artifact_digest = (
                sha256_bytes(physical_campaign_evidence_raw)
                if isinstance(physical_campaign_evidence_raw, bytes) else None)
            required_artifact_digest = (
                physical_campaign_receipt.get("evidence_sha256")
                if isinstance(physical_campaign_receipt, dict) and
                isinstance(
                    physical_campaign_receipt.get("evidence_sha256"), str) and
                SHA256_RE.fullmatch(
                    physical_campaign_receipt["evidence_sha256"])
                else None)
            artifact_binding_class = (
                "match"
                if artifact_digest is not None and
                required_artifact_digest == artifact_digest
                else "mismatch"
                if artifact_digest is not None and
                required_artifact_digest is not None
                else "invalid")
            observed_source = (
                physical_campaign_evidence.get("source_sha")
                if isinstance(physical_campaign_evidence, dict) else None)
            observed_source_class = (
                "match" if observed_source == source_sha else
                "mismatch" if _valid_source(observed_source) else "invalid")
            audit = (
                physical_campaign_evidence.get("physical_evidence_audit")
                if isinstance(physical_campaign_evidence, dict) else None)
            target_binding = (
                physical_campaign_evidence.get("qualification_target_binding")
                if isinstance(physical_campaign_evidence, dict) else None)
            expected_binding = (
                target_binding.get("expected")
                if isinstance(target_binding, dict) else None)
            observed_binding = (
                target_binding.get("observed")
                if isinstance(target_binding, dict) else None)
            observed_binding_target = (
                _normalize_target({
                    "partuuid": observed_binding.get("physical_partuuid"),
                    "size_bytes": observed_binding.get("physical_device_bytes"),
                }) if isinstance(observed_binding, dict) else None)
            binding_objects_valid = (
                isinstance(target_binding, dict) and
                isinstance(expected_binding, dict) and
                isinstance(observed_binding, dict))
            qualification_binding_class = (
                "invalid" if not binding_objects_valid else
                "match"
                if target_binding.get("status") == "MATCH" and
                target_binding.get("consistent") is True and
                _same_json_value(expected_binding, observed_binding)
                else "mismatch")
            qualification_target_identity_class = (
                "match"
                if target is not None and observed_binding_target == target
                else "mismatch"
                if observed_binding_target is not None else "invalid")
            receipt_source_identity_class = (
                "match" if receipt_source == source_sha else
                "mismatch" if _valid_source(receipt_source) else "invalid")
            receipt_target_identity_class = (
                "match" if target is not None and receipt_target == target else
                "mismatch" if receipt_target is not None else "invalid")
            receipt_time_class = (
                "valid" if _valid_observed_at_utc(receipt_observed_at)
                else "invalid")
            failed_phase = (
                physical_campaign_failure_receipt_issue
                if physical_campaign_failure_receipt_issue is not None
                else "qualification_target_binding"
                if any(issue.startswith(
                    "sealed campaign qualification target")
                    for issue in campaign_issues)
                else "sealed_at_utc"
                if any("sealed_at_utc" in issue for issue in campaign_issues)
                else "host_stability"
                if any("host stability" in issue for issue in campaign_issues)
                else "admitted_device_boundary"
                if any("not quiescent" in issue for issue in campaign_issues)
                else "physical_evidence_audit"
                if (
                    (isinstance(audit, dict) and
                     audit.get("status") != "PASS") or
                    any(issue.startswith(
                        "sealed campaign physical evidence audit")
                        for issue in campaign_issues))
                else "campaign_validation")
            block_code(
                "physical_campaign: evidence_class=sealed_physical_campaign "
                f"first_failed_phase={failed_phase} "
                f"original_status={safe_status} "
                "expected_source_identity_class=release_source "
                f"observed_source_identity_class={observed_source_class} "
                f"artifact_binding_class={artifact_binding_class} "
                "expected_target_identity_class=authorized_target "
                f"qualification_target_binding_class="
                f"{qualification_binding_class} "
                f"observed_qualification_target_identity_class="
                f"{qualification_target_identity_class} "
                "expected_receipt_source_identity_class=release_source "
                f"observed_receipt_source_identity_class="
                f"{receipt_source_identity_class} "
                "expected_receipt_target_identity_class=authorized_target "
                f"observed_receipt_target_identity_class="
                f"{receipt_target_identity_class} "
                f"observed_receipt_time_class={receipt_time_class} "
                f"verdict={'FAIL' if physical_campaign_failure_proven else 'BLOCKED'} "
                f"reason={'authenticated_producer_failure' if physical_campaign_failure_proven else 'missing_or_contradictory_campaign_proof'} "
                "safe_action=recapture_and_reseal_campaign")
        if isinstance(physical_campaign_evidence, dict):
            campaign_sealed_at = physical_campaign_evidence.get(
                "sealed_at_utc")
            campaign_sealed_time = _parse_utc_evidence_time(
                campaign_sealed_at)

    def require_campaign_chronology(
            name: str, record: dict[str, Any] | None,
            validation_issues: list[str] | None) -> bool:
        if (
                record is None or validation_issues != [] or
                campaign_sealed_time is None or
                not isinstance(campaign_sealed_at, str)):
            return False
        observed_text = record.get("observed_at_utc")
        observed_time = _parse_utc_evidence_time(observed_text)
        if observed_time is None:
            return False
        if observed_time < campaign_sealed_time:
            block_code(
                f"{name}: observation predates sealed campaign "
                f"(metric=observed_at_utc observed={observed_text} "
                f"minimum={campaign_sealed_at})")
            return False
        return True

    capacity_chronology_valid = require_campaign_chronology(
        "maximum_capacity_and_ram", capacity, campaign_structural_issues)
    if capacity is not None:
        logical = capacity.get("logical_capacity_bytes")
        peak = capacity.get("peak_ram_bytes")
        valid_logical = (
            type(logical) is int and
            0 < logical <= RAM_TRACE_VALIDATOR["MAX_UINT64"])
        valid_peak = (
            type(peak) is int and
            0 < peak <= RAM_TRACE_VALIDATOR["MAX_UINT64"])
        if not valid_logical:
            block_code("maximum_capacity_and_ram: logical capacity is invalid")
        if not valid_peak:
            block_code("maximum_capacity_and_ram: peak RAM is invalid")
        elif peak_ram_limit is not None and peak > peak_ram_limit:
            block_code(
                "maximum_capacity_and_ram: claimed peak exceeds frozen limit "
                f"(metric=metadata_and_target_peak_ram_bytes "
                f"observed={peak} limit={peak_ram_limit})")
        if campaign_structural_issues is None:
            block_code(
                "maximum_capacity_and_ram: NOT_MEASURED; "
                "persistent loaded-host campaign evidence is missing")
        else:
            if capacity.get("evidence_sha256") != sha256_bytes(
                    physical_campaign_evidence_raw):
                block_code(
                    "maximum_capacity_and_ram: campaign evidence digest binding mismatch")
            sealed_capacity = (
                physical_campaign_evidence.get("capacity_and_ram")
                if isinstance(physical_campaign_evidence, dict) else None)
            matches_campaign = (
                isinstance(sealed_capacity, dict) and
                valid_logical and valid_peak and
                logical == sealed_capacity.get("logical_capacity_bytes") and
                peak == sealed_capacity.get("peak_ram_bytes"))
            if not matches_campaign:
                block_code(
                    "maximum_capacity_and_ram: sealed campaign measurement mismatch")
            for issue in campaign_structural_issues:
                block_code("maximum_capacity_and_ram: " + issue)
            # Only actual, sealed, source-bound samples can set a measured
            # verdict. An interrupted/missing trace cannot inherit PASS from
            # calculated capacity or a self-declared scalar report.
            if (not campaign_structural_issues and matches_campaign and
                    peak_ram_limit is not None and
                    capacity_chronology_valid and
                    capacity.get("policy_sha256") == policy_sha256 and
                    _normalize_target(capacity.get("target")) == target and
                    capacity.get("evidence_sha256") ==
                    sha256_bytes(physical_campaign_evidence_raw)):
                summary = sealed_capacity["metadata_ram_summary"]
                memory_measurement.update({
                    "status": (
                        "MEASURED_WITHIN_LIMIT" if peak <= peak_ram_limit
                        else "MEASURED_OVER_LIMIT"),
                    "observed_peak_ram_bytes": peak,
                    "initialization_peak_ram_bytes":
                        summary["initialization_peak_ram_bytes"],
                    "initialization_samples":
                        summary["initialization_samples"],
                    "steady_peak_ram_bytes": summary["steady_peak_ram_bytes"],
                    "steady_samples": summary["steady_samples"],
                    "gc_peak_ram_bytes": summary["gc_peak_ram_bytes"],
                    "gc_samples": summary["gc_samples"],
                    "teardown_recovery": "MEASURED_RECOVERED",
                    "teardown_recovery_samples": summary["recovery_samples"],
                    "teardown_recovery_span_ns": summary["recovery_span_ns"],
                })

    if memory_measurement["status"] == "NOT_MEASURED":
        block_code(
            "maximum_capacity_and_ram: loaded-host peak unavailable; "
            "metric=metadata_and_target_peak_ram_bytes observed=unavailable "
            f"limit={frozen_peak_ram_limit} "
            "required=sealed source/boot/artifact-bound constructor, steady, "
            "GC and verified teardown host samples")

    physical = pass_record("sustained_physical_performance")
    require_target("sustained_physical_performance", physical)
    require_policy("sustained_physical_performance", physical)
    require_campaign_chronology(
        "sustained_physical_performance", physical, campaign_issues)
    if physical is not None:
        if campaign_issues is None:
            block_code(
                "sustained_physical_performance: persistent campaign evidence is missing")
        else:
            if physical.get("evidence_sha256") != sha256_bytes(
                    physical_campaign_evidence_raw):
                block_code(
                    "sustained_physical_performance: campaign evidence digest binding mismatch")
            for issue in campaign_issues:
                block_code("sustained_physical_performance: " + issue)

    lifecycle = pass_record("lifecycle_deployment_state", deployment=True)
    require_target("lifecycle_deployment_state", lifecycle, deployment=True)
    if lifecycle is not None:
        if (
                lifecycle.get("overall") != "PASS" or
                lifecycle.get("lifecycle") != "PASS" or
                lifecycle.get("deployment") != "PASS"):
            block_deployment(
                "lifecycle_deployment_state: lifecycle/deployment result is not PASS")
        evidence_sha256 = lifecycle.get("evidence_sha256")
        if not isinstance(evidence_sha256, str) or not SHA256_RE.fullmatch(
                evidence_sha256):
            block_deployment(
                "lifecycle_deployment_state: evidence digest is invalid")

    installed = pass_record("installed_artifact_identity", deployment=True)
    require_target("installed_artifact_identity", installed, deployment=True)
    if installed is not None:
        if installed.get("installed") is not True or not _same_hashes(
                installed.get("hashes"), report_artifacts):
            block_deployment(
                "installed_artifact_identity: installed bytes do not match release artifacts")

    harness = pass_record("cold_boot_harness", deployment=True)
    require_target("cold_boot_harness", harness, deployment=True)
    harness_armed = False
    bound_cold_boot_arm_evidence = None
    if harness is not None:
        if harness.get("armed") is not True:
            block_deployment("cold_boot_harness: harness is not armed")
        elif cold_boot_arm_evidence is None or cold_boot_arm_evidence_raw is None:
            block_deployment(
                "cold_boot_harness: persistent arm evidence is missing")
        elif harness.get("evidence_sha256") != sha256_bytes(
                cold_boot_arm_evidence_raw):
            block_deployment(
                "cold_boot_harness: arm evidence digest mismatch")
        else:
            try:
                bound_cold_boot_arm_evidence = _bound_env_record(
                    cold_boot_arm_evidence, cold_boot_arm_evidence_raw,
                    "cold-boot arm evidence")
            except EvidenceError as exc:
                block_deployment("cold_boot_harness: " + str(exc))
            else:
                arm_issues = validate_cold_boot_arm_evidence(
                    bound_cold_boot_arm_evidence, source_sha, target,
                    report_artifacts, owner_kernel_release)
                for issue in arm_issues:
                    block_deployment("cold_boot_harness: " + issue)
                harness_armed = not arm_issues

    code_ready = not code_blockers
    if not code_ready:
        deployment_blockers.insert(
            0, "code production-readiness gates are not all PASS")
    deployment_ready = not deployment_blockers

    reboot = release.get("owner_observed_reboot")
    cold_boot_observed = "NO"
    if _valid_source(source_sha) and isinstance(reboot, dict) and \
            reboot.get("current") is True and \
            reboot.get("source_sha") == source_sha and \
            _valid_observed_at_utc(reboot.get("observed_at_utc")) and \
            (target is not None and
             _normalize_target(reboot.get("target")) == target):
        if (
                reboot.get("status") == "PASS" and
                reboot.get("observed") is True and
                reboot.get("overall") == "PASS"):
            if cold_boot_evidence is None or cold_boot_evidence_raw is None:
                cold_boot_blockers.append(
                    "owner_observed_reboot: persistent cold-boot evidence is missing")
            elif reboot.get("evidence_sha256") != sha256_bytes(
                    cold_boot_evidence_raw):
                cold_boot_blockers.append(
                    "owner_observed_reboot: persistent cold-boot evidence digest mismatch")
            else:
                try:
                    bound_cold_boot_evidence = _bound_env_record(
                        cold_boot_evidence, cold_boot_evidence_raw,
                        "cold-boot evidence")
                except EvidenceError as exc:
                    cold_boot_blockers.append(
                        "owner_observed_reboot: " + str(exc))
                else:
                    validated_cold_boot_arm = (
                        bound_cold_boot_arm_evidence
                        if harness_armed else None)
                    for issue in validate_cold_boot_evidence(
                            bound_cold_boot_evidence, source_sha, target,
                            report_artifacts, owner_kernel_release,
                            validated_cold_boot_arm):
                        cold_boot_blockers.append(
                            "owner_observed_reboot: " + issue)
                    if not cold_boot_blockers:
                        cold_boot_observed = "PASS"
        elif (
                reboot.get("status") == "FAIL" and
                reboot.get("observed") is True and
                reboot.get("overall") == "FAIL"):
            if cold_boot_evidence is None or cold_boot_evidence_raw is None:
                cold_boot_blockers.append(
                    "owner_observed_reboot: persistent cold-boot failure "
                    "evidence is missing; first_failed_phase="
                    "failure_authentication verdict=BLOCKED")
            elif reboot.get("evidence_sha256") != sha256_bytes(
                    cold_boot_evidence_raw):
                cold_boot_blockers.append(
                    "owner_observed_reboot: persistent cold-boot failure "
                    "evidence digest mismatch; first_failed_phase="
                    "failure_authentication verdict=BLOCKED")
            elif not harness_armed or bound_cold_boot_arm_evidence is None:
                cold_boot_blockers.append(
                    "owner_observed_reboot: persistent cold-boot failure "
                    "evidence has no validated arm record; first_failed_phase="
                    "failure_authentication verdict=BLOCKED")
            else:
                try:
                    bound_cold_boot_evidence = _bound_env_record(
                        cold_boot_evidence, cold_boot_evidence_raw,
                        "cold-boot failure evidence")
                except EvidenceError as exc:
                    cold_boot_blockers.append(
                        "owner_observed_reboot: " + str(exc))
                else:
                    failure_issues = validate_cold_boot_failure_evidence(
                        bound_cold_boot_evidence, source_sha, target,
                        report_artifacts, owner_kernel_release,
                        bound_cold_boot_arm_evidence)
                    for issue in failure_issues:
                        cold_boot_blockers.append(
                            "owner_observed_reboot: " + issue)
                    if not failure_issues:
                        cold_boot_observed = "FAIL"

    # Only a failed execution bound to this exact source is a FAIL.
    # Missing, malformed or previous-source evidence remains BLOCKED.
    if (
            cold_boot_observed == "FAIL" or
            owner_failure_proven or
            real_swap_failure_proven or
            physical_campaign_failure_proven):
        release_verdict = "FAIL"
    elif not code_ready or not deployment_ready:
        release_verdict = "BLOCKED"
    elif cold_boot_observed == "PASS":
        release_verdict = "PASS"
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
        "METADATA_RAM_MEASUREMENT": memory_measurement,
        "FULL_CAPACITY_LOADED_CONSTRUCTION": (
            "SAMPLED_LOADED_HOST"
            if memory_measurement["status"] != "NOT_MEASURED"
            else "NOT_MEASURED"),
        "CAPACITY_INDEX_ESTIMATE": capacity_prediction,
        "ALLOCATION_FAILURE_COVERAGE": "SEPARATE_NOT_CONSTRUCTION_EVIDENCE",
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
        "--cold-boot-arm-evidence", type=Path,
        help="durable swapz-primary-boot-arm-v1 record created before reboot")
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
        if args.cold_boot_arm_evidence is None:
            cold_boot_arm_evidence = None
            cold_boot_arm_evidence_raw = None
        else:
            cold_boot_arm_evidence, cold_boot_arm_evidence_raw = load_env_strict(
                args.cold_boot_arm_evidence)
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
            cold_boot_evidence, cold_boot_evidence_raw,
            cold_boot_arm_evidence, cold_boot_arm_evidence_raw)
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
            "METADATA_RAM_MEASUREMENT": {
                "status": "NOT_MEASURED", "observed_peak_ram_bytes": None,
                "limit_bytes": None, "initialization_peak_ram_bytes": None,
                "initialization_samples": None,
                "steady_peak_ram_bytes": None,
                "steady_samples": None,
                "gc_peak_ram_bytes": None,
                "gc_samples": None,
                "teardown_recovery": "NOT_MEASURED",
                "teardown_recovery_samples": None,
                "teardown_recovery_span_ns": None,
            },
            "FULL_CAPACITY_LOADED_CONSTRUCTION": "NOT_MEASURED",
            "CAPACITY_INDEX_ESTIMATE": {
                "status": "NOT_AVAILABLE",
                "logical_pages": None,
                "logical_mapper_bytes": None,
                "physical_blocks": None,
                "segment_count": None,
                "array_count": None,
                "payload_bytes": None,
                "page_rounded_bytes": None,
            },
            "ALLOCATION_FAILURE_COVERAGE":
                "SEPARATE_NOT_CONSTRUCTION_EVIDENCE",
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
