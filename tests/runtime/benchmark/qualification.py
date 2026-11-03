#!/usr/bin/env python3
"""Prospective dedicated-SD performance contract and result evaluator.

Private benchmark helper. It schedules no physical I/O and does not replace the
project's single supported test interface.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
from pathlib import Path

from evidence_io import write_new_json

SCHEMA = "swapz-performance-qualification-v1"
PAIR_SCHEMA = "swapz-performance-pair-v1"
SUMMARY_SCHEMA = "swapz-performance-summary-v1"
T95_DF4 = 2.7764451051977987

ROOT = Path(__file__).resolve().parents[3]
ACCEPTANCE_MANIFEST = ROOT / "docs/production-acceptance.json"
AMENDMENT_MANIFEST = ROOT / "tests/runtime/benchmark/physical-qualification-amendment-v2.json"
AMENDMENT_SCHEMA = "swapz-performance-qualification-amendment-v2"
# A change to this blob requires a new prospectively versioned protocol.
AMENDMENT_GIT_BLOB_SHA = "eac574fd204932e630e8bb45dca66b67c135a779"
MAJOR_MINOR_RE = re.compile(r"[0-9]+:[0-9]+")
PARTUUID_RE = re.compile(r"[0-9a-f]+(?:-[0-9a-f]+)*")


def normalize_partuuid(value):
    if not isinstance(value, str):
        return None
    normalized = value.lower()
    if (
            not 8 <= len(normalized) <= 64 or
            not PARTUUID_RE.fullmatch(normalized) or
            sum(ch != "-" for ch in normalized) < 8):
        return None
    return normalized


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate acceptance-manifest key {key}")
        result[key] = value
    return result


def _load_frozen_physical_contract() -> dict:
    try:
        document = json.loads(
            ACCEPTANCE_MANIFEST.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object)
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"cannot load frozen production acceptance manifest: {exc}") from exc
    if set(document) != {
            "schema", "status", "primary_real_swap", "physical_qualification"} or \
            document.get("schema") != "swapz-production-acceptance-v1" or \
            document.get("status") != "FROZEN":
        raise ValueError(
            "production acceptance manifest is not canonical and frozen")
    contract = document.get("physical_qualification")
    if not isinstance(contract, dict) or contract.get("schema") != SCHEMA or \
            contract.get("prospective") is not True:
        raise ValueError("frozen physical qualification contract is malformed")
    return contract


CONTRACT = _load_frozen_physical_contract()


def _git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {len(data)}\0".encode("ascii"))
    digest.update(data)
    return digest.hexdigest()


def _load_frozen_amendment() -> dict:
    try:
        if _git_blob_sha(AMENDMENT_MANIFEST) != AMENDMENT_GIT_BLOB_SHA:
            raise ValueError("prospective physical amendment blob hash changed")
        document = json.loads(
            AMENDMENT_MANIFEST.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object)
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"cannot load prospective physical amendment: {exc}") from exc
    required = {
        "schema", "status", "issued_on", "parent_schema", "parent_manifest",
        "parent_manifest_git_blob_sha", "result_pooling", "workloads",
        "acceptance",
    }
    if set(document) != required or document.get("schema") != AMENDMENT_SCHEMA or \
            document.get("status") != "FROZEN_PROSPECTIVE" or \
            document.get("parent_schema") != SCHEMA or \
            document.get("parent_manifest") != "docs/production-acceptance.json":
        raise ValueError("prospective physical amendment is not canonical and frozen")
    if document.get("parent_manifest_git_blob_sha") != _git_blob_sha(ACCEPTANCE_MANIFEST):
        raise ValueError("prospective physical amendment parent manifest changed")
    workloads = document.get("workloads")
    if not isinstance(workloads, dict) or not workloads or \
            set(workloads) & set(CONTRACT["workloads"]):
        raise ValueError("prospective physical amendment workloads are malformed")
    return document


AMENDMENT = _load_frozen_amendment()
WORKLOADS = {**CONTRACT["workloads"], **AMENDMENT["workloads"]}


def acceptance_manifest_sha256() -> str:
    """Hash the exact frozen parent policy consumed by this evaluator."""
    return hashlib.sha256(ACCEPTANCE_MANIFEST.read_bytes()).hexdigest()


def contract() -> dict:
    return json.loads(json.dumps(CONTRACT))


def amendment() -> dict:
    return json.loads(json.dumps(AMENDMENT))


def workload_spec(workload: str) -> dict:
    try:
        return WORKLOADS[workload]
    except KeyError as exc:
        raise ValueError("unknown qualification workload") from exc


def service_limits(workload: str) -> dict:
    spec = workload_spec(workload)
    profile = spec.get("acceptance_profile")
    if profile in (None, "service-v1"):
        return CONTRACT["acceptance"]["service"]
    try:
        return AMENDMENT["acceptance"][profile]
    except KeyError as exc:
        raise ValueError("unknown prospective acceptance profile") from exc


def number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def metric(record: dict, path: str):
    value = record
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            raise ValueError(f"missing metric {path}")
        value = value[key]
    return value


def fractional_delta(raw, swapz, name: str) -> float:
    raw_value = number(raw, name + ".raw")
    swapz_value = number(swapz, name + ".swapz")
    if raw_value <= 0 or swapz_value < 0:
        raise ValueError(f"{name} requires positive raw and nonnegative swapz")
    return swapz_value / raw_value - 1.0


def paired_ci95(values: list[float]) -> dict:
    if len(values) != 5:
        raise ValueError("statistical qualification requires exactly five accepted pairs")
    values = [number(value, "paired delta") for value in values]
    mean = statistics.fmean(values)
    half = T95_DF4 * statistics.stdev(values) / math.sqrt(5.0)
    return {"n": 5, "mean": mean, "lower": mean - half, "upper": mean + half}


def capture_loaded_module_provenance(
        source_sha: str, expect_loaded: bool,
        parameter_base: Path = Path("/sys/module/dm_swapz/parameters")) -> dict:
    """Read and validate the exact module state used by a physical arm."""
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha or ""):
        raise ValueError("physical module provenance requires exact source SHA")
    if not parameter_base.is_dir():
        if expect_loaded:
            raise ValueError("physical swapz arm requires loaded dm_swapz")
        return {"status": "NOT_LOADED"}
    if not expect_loaded:
        raise ValueError("physical raw arm requires dm_swapz to be unloaded")

    def read_parameter(name: str) -> str:
        try:
            value = (parameter_base / name).read_text(
                encoding="ascii").strip()
        except (OSError, UnicodeError) as exc:
            raise ValueError(
                f"cannot read loaded dm_swapz {name}: {exc}") from exc
        if not value or any(ord(character) < 0x20 for character in value):
            raise ValueError(f"loaded dm_swapz {name} is malformed")
        return value

    observed = {
        "status": "LOADED",
        "build_source_sha": read_parameter("build_source_sha"),
        "build_source_clean": read_parameter("build_source_clean"),
        "allow_physical_backing": read_parameter("allow_physical_backing"),
    }
    if (observed["build_source_sha"] != source_sha or
            observed["build_source_clean"] != "1" or
            observed["allow_physical_backing"] not in {"1", "Y"}):
        raise ValueError(
            "loaded dm_swapz provenance/physical-backing parameter is not exact")
    return observed


def validate_module_provenance(arm: dict, label: str) -> list[str]:
    provenance = arm.get("loaded_module_provenance")
    if label == "raw":
        return ([] if provenance == {"status": "NOT_LOADED"} else
                ["raw arm did not prove dm_swapz was unloaded"])
    if (not isinstance(provenance, dict) or
            provenance.get("status") != "LOADED" or
            provenance.get("build_source_sha") != arm.get("source_sha") or
            provenance.get("build_source_clean") != "1" or
            provenance.get("allow_physical_backing") not in {"1", "Y"}):
        return [
            "swapz arm lacks exact clean loaded-module physical provenance"]
    return []


def validate_arm(arm: dict, workload: str, label: str) -> list[str]:
    spec = workload_spec(workload)
    reasons = validate_module_provenance(arm, label)
    if workload == "anonymous-swap":
        for field, expected in (("bytes", spec["bytes"]),
                                ("round_count", spec["rounds"]),
                                ("required_swap_bytes", spec["minimum_observed_swap_bytes"]),
                                ("content", spec["content"])):
            if arm.get(field) != expected:
                reasons.append(f"{label} {field} differs from prospective workload")
        identity = arm.get("swap_device_identity")
        if not isinstance(identity, dict):
            reasons.append(f"{label} admitted swap-device identity is missing")
        else:
            device = identity.get("device")
            if not isinstance(device, str) or not MAJOR_MINOR_RE.fullmatch(device):
                reasons.append(
                    f"{label} admitted swap-device major:minor is malformed")
            if label == "raw":
                if identity.get("dm_uuid") is not None:
                    reasons.append(
                        "raw anonymous arm unexpectedly carries a DM UUID")
                if identity.get("lower_device") != device:
                    reasons.append(
                        "raw anonymous arm lower identity differs from device")
            else:
                lower_device = identity.get("lower_device")
                if (not identity.get("dm_uuid") or
                        identity.get("dm_target") != "swapz" or
                        not isinstance(lower_device, str) or
                        not MAJOR_MINOR_RE.fullmatch(lower_device)):
                    reasons.append(
                        "swapz anonymous arm lacks exact mapper/lower identity")
        cgroup = arm.get("cgroup_before") or {}
        if cgroup.get("memory_max") != spec["memory_max_bytes"]:
            reasons.append(f"{label} cgroup memory.max differs from prospective workload")
        return reasons

    expected = {
        "qd": spec["qd"], "read_percent": spec["read_percent"],
        "occupancy_percent": spec["logical_occupancy_percent"],
        "hot_percent": spec["hot_region_percent"],
        "fill_content_profile": spec["fill_content_profile"],
        "churn_content_profile": spec["churn_content_profile"],
        "warmup_operations": spec.get("warmup_operations"),
        "measure_operations": spec.get("measure_operations"),
        "warmup_seconds": spec.get("warmup_seconds"),
        "measure_seconds_requested": spec.get("measure_seconds"),
    }
    for field, expected_value in expected.items():
        if arm.get(field) != expected_value:
            reasons.append(f"{label} {field} differs from prospective workload")
    identity = arm.get("device_identity") or {}
    partuuid = identity.get("physical_partuuid")
    device_bytes = identity.get("physical_device_bytes")
    lower_major_minor = identity.get("lower_major_minor")
    if (normalize_partuuid(partuuid) != partuuid or
            type(device_bytes) is not int or device_bytes <= 0 or
            not isinstance(lower_major_minor, str) or
            not MAJOR_MINOR_RE.fullmatch(lower_major_minor)):
        reasons.append(f"{label} physical identity is missing or malformed")
    if label == "raw" and identity.get("dm_uuid") is not None:
        reasons.append("raw arm unexpectedly carries a DM UUID")
    if label == "swapz" and not identity.get("dm_uuid"):
        reasons.append("swapz arm has no pinned DM UUID")
    resources = arm.get("resources") or {}
    rss = resources.get("replay_peak_rss_bytes")
    if type(rss) is not int or rss < 0:
        reasons.append(f"{label} replay peak RSS is missing")
    elif rss > CONTRACT["acceptance"]["sustained"]["replay_peak_rss_bytes_max"]:
        reasons.append(f"{label} replay peak RSS exceeds prospective bound")
    if label == "swapz":
        peak = resources.get("metadata_and_target_peak_ram_bytes")
        if type(peak) is not int or peak < 0:
            reasons.append("swapz metadata/target peak RAM is missing")
        elif peak > CONTRACT["acceptance"]["sustained"]["metadata_and_target_peak_ram_bytes_max"]:
            reasons.append("swapz metadata/target peak RAM exceeds prospective bound")
        if not target_health_ok(arm.get("gc")):
            reasons.append("swapz target health failed or is unavailable")
    return reasons


def compare_pair(raw: dict, swapz: dict, workload: str, pair_id: str,
                 pair_index: int, order: str, extra_reasons=None) -> dict:
    if workload not in WORKLOADS:
        raise ValueError("unknown qualification workload")
    if raw.get("candidate") != "raw" or swapz.get("candidate") != "swapz":
        raise ValueError("pair requires one raw and one swapz arm")
    spec = workload_spec(workload)
    reasons = list(extra_reasons or [])
    if not 1 <= pair_index <= spec["pairs"]:
        reasons.append("pair index is outside prospective repetition plan")
    elif order != spec["counterbalanced_order"][pair_index - 1]:
        reasons.append("pair order differs from prospective order")
    reasons += validate_arm(raw, workload, "raw")
    reasons += validate_arm(swapz, workload, "swapz")
    immutable = ("source_sha", "bytes", "pages", "round_count", "required_swap_bytes", "content") \
        if workload == "anonymous-swap" else (
            "source_sha", "logical_pages", "occupied_pages", "hot_pages", "qd", "read_percent",
            "fill_fixture_sha256", "churn_fixture_sha256", "fill_content_profile",
            "churn_content_profile", "workload_seed", "operation_recipe_sha256",
            "warmup_operations", "warmup_seconds", "measure_operations", "measure_seconds_requested")
    mismatch = [key for key in immutable if raw.get(key) != swapz.get(key)]
    if mismatch:
        reasons.append("pair provenance mismatch: " + ", ".join(mismatch))
    if workload != "anonymous-swap":
        for field in ("physical_partuuid", "physical_device_bytes", "lower_major_minor"):
            if (raw.get("device_identity") or {}).get(field) != (swapz.get("device_identity") or {}).get(field):
                reasons.append("physical pair identity mismatch: " + field)
    else:
        raw_identity = raw.get("swap_device_identity") or {}
        swapz_identity = swapz.get("swap_device_identity") or {}
        if raw_identity.get("device") != swapz_identity.get("lower_device"):
            reasons.append("anonymous pair physical lower identity mismatch")
    for label, arm in (("raw", raw), ("swapz", swapz)):
        if arm.get("verdict") != "PASS":
            reasons.append(f"{label} arm verdict is not PASS")
        oracle_mismatches = (arm.get("oracle") or {}).get("mismatches")
        if type(oracle_mismatches) is not int or oracle_mismatches != 0:
            reasons.append(f"{label} byte oracle failed or is unavailable")
        screen = arm.get("performance_screening") or {}
        if screen.get("status") != "SCREENED":
            for reason in screen.get("reasons") or ["screening not usable"]:
                reasons.append(f"{label}: {reason}")
    if raw.get("measure_operations") is not None and (
            raw.get("read_ops"), raw.get("write_ops")) != (
            swapz.get("read_ops"), swapz.get("write_ops")):
        reasons.append("fixed-work pair completed different operation counts")

    paths = ({
        "swapin_p95": "swapin_latency.p95_ns", "swapin_p99": "swapin_latency.p99_ns",
        "useful_read": "throughput.useful_read_mbps",
        "lower_write_bytes": "lower_io.lower_write_bytes_per_logical_fill_byte",
        "lower_write_requests": "lower_io.lower_write_requests_per_1000_fill_pages",
        "cpu": "cpu.measured_cpu_seconds_per_useful_byte",
    } if workload == "anonymous-swap" else {
        "useful_write": "throughput.logical_write_mbps",
        "lower_write_bytes": "lower_io.lower_write_bytes_per_logical_write_byte",
        "lower_write_requests": "lower_io.lower_write_requests_per_1000_logical_writes",
        "read_p95": "latency.read_p95_ns", "read_p99": "latency.read_p99_ns",
        "write_p95": "latency.write_p95_ns", "write_p99": "latency.write_p99_ns",
        "cpu": "cpu.measured_cpu_seconds_per_useful_byte",
    })
    deltas = {}
    for name, path in paths.items():
        try:
            deltas[name] = fractional_delta(metric(raw, path), metric(swapz, path), name)
        except ValueError as exc:
            deltas[name] = None
            reasons.append(str(exc))
    reasons = sorted(set(reasons))
    return {
        "schema": PAIR_SCHEMA, "workload": workload, "pair_id": pair_id,
        "pair_index": pair_index, "order": order, "source_sha": raw.get("source_sha"),
        "qualification_protocol": (
            AMENDMENT_SCHEMA if workload in AMENDMENT["workloads"] else SCHEMA),
        "status": "PASS" if not reasons else "EXCLUDED", "excluded": bool(reasons),
        "exclusion_reasons": reasons, "deltas": deltas, "raw": raw, "swapz": swapz,
    }


def pair_integrity_reasons(pair: dict) -> list[str]:
    """Re-derive pair evidence so stored verdicts/deltas cannot be edited open."""
    raw = pair.get("raw")
    swapz = pair.get("swapz")
    if not isinstance(raw, dict) or not isinstance(swapz, dict):
        return ["pair raw/swapz arm evidence is missing"]
    try:
        derived = compare_pair(
            raw, swapz, pair.get("workload"), pair.get("pair_id"),
            pair.get("pair_index"), pair.get("order"))
    except (KeyError, TypeError, ValueError) as exc:
        return ["pair cannot be re-derived from arm evidence: " + str(exc)]

    reasons = []
    if pair.get("deltas") != derived["deltas"]:
        reasons.append("stored pair deltas differ from recomputed arm evidence")
    if pair.get("source_sha") != derived["source_sha"]:
        reasons.append(
            "stored pair source_sha differs from recomputed arm evidence")
    recorded_protocol = pair.get("qualification_protocol")
    expected_protocol = derived["qualification_protocol"]
    if recorded_protocol != expected_protocol and (
            recorded_protocol is not None or
            pair.get("workload") in AMENDMENT["workloads"]):
        reasons.append(
            "stored pair qualification_protocol differs from recomputed arm evidence")

    recorded_reasons = pair.get("exclusion_reasons")
    if (not isinstance(recorded_reasons, list) or
            any(not isinstance(reason, str) for reason in recorded_reasons)):
        reasons.append("stored pair exclusion reasons are malformed")
        recorded_reasons = []
    intrinsic_reasons = set(derived["exclusion_reasons"])
    if not intrinsic_reasons.issubset(set(recorded_reasons)):
        reasons.append(
            "stored pair exclusions omit failures derived from arm evidence")

    status = pair.get("status")
    excluded = pair.get("excluded")
    if status == "PASS":
        if excluded is not False or recorded_reasons or derived["status"] != "PASS":
            reasons.append("stored pair PASS contradicts embedded arm evidence")
    elif status == "EXCLUDED":
        if excluded is not True or not recorded_reasons:
            reasons.append("stored pair EXCLUDED state is malformed")
    else:
        reasons.append("stored pair status is invalid")
    return sorted(set(reasons))


def pair_target_identity(pair: dict):
    """Return the physical lower identity proven by one internally matched pair."""
    raw = pair.get("raw")
    swapz = pair.get("swapz")
    if not isinstance(raw, dict) or not isinstance(swapz, dict):
        return None
    if pair.get("workload") == "anonymous-swap":
        raw_identity = raw.get("swap_device_identity") or {}
        swapz_identity = swapz.get("swap_device_identity") or {}
        raw_device = raw_identity.get("device")
        swapz_lower = swapz_identity.get("lower_device")
        if (isinstance(raw_device, str) and
                MAJOR_MINOR_RE.fullmatch(raw_device) and
                raw_device == swapz_lower):
            return {"lower_major_minor": raw_device}
        return None

    raw_identity = raw.get("device_identity") or {}
    swapz_identity = swapz.get("device_identity") or {}
    fields = (
        "physical_partuuid", "physical_device_bytes", "lower_major_minor")
    if any(raw_identity.get(field) != swapz_identity.get(field)
           for field in fields):
        return None
    partuuid = raw_identity.get("physical_partuuid")
    device_bytes = raw_identity.get("physical_device_bytes")
    lower_major_minor = raw_identity.get("lower_major_minor")
    if (normalize_partuuid(partuuid) != partuuid or
            type(device_bytes) is not int or device_bytes <= 0 or
            not isinstance(lower_major_minor, str) or
            not MAJOR_MINOR_RE.fullmatch(lower_major_minor)):
        return None
    return {
        "physical_partuuid": partuuid,
        "physical_device_bytes": device_bytes,
        "lower_major_minor": lower_major_minor,
    }


def common_campaign_target(rows: list[dict]):
    """Require every currently usable pair to resolve to one physical lower."""
    identities = []
    for row in rows:
        if not row.get("analysis_usable"):
            continue
        identity = pair_target_identity(row)
        if identity is None:
            return None, False
        identities.append(identity)
    if not identities:
        return None, False

    major_minors = {row["lower_major_minor"] for row in identities}
    if len(major_minors) != 1:
        return None, False
    complete = [
        row for row in identities if "physical_partuuid" in row]
    if not complete:
        return {"lower_major_minor": identities[0]["lower_major_minor"]}, True
    complete_keys = {
        (row["physical_partuuid"], row["physical_device_bytes"],
         row["lower_major_minor"])
        for row in complete
    }
    if len(complete_keys) != 1:
        return None, False
    canonical = dict(complete[0])
    if any(row["lower_major_minor"] != canonical["lower_major_minor"]
           for row in identities):
        return None, False
    return canonical, True


def quartile_ratio(rows: list[dict], field: str) -> float:
    values = [number(row.get(field), field) for row in rows]
    if len(values) < 4 or any(value <= 0 for value in values):
        raise ValueError("sustained drift needs at least four positive minute buckets")
    count = max(1, len(values) // 4)
    return statistics.fmean(values[-count:]) / statistics.fmean(values[:count])


def service_decision(pairs: list[dict], workload: str) -> dict:
    names = ("useful_write", "lower_write_bytes", "lower_write_requests",
             "read_p95", "read_p99", "write_p95", "write_p99", "cpu")
    cis = {name: paired_ci95([pair["deltas"][name] for pair in pairs]) for name in names}
    limit = service_limits(workload)
    checks = {
        "useful_write": cis["useful_write"]["lower"] >= limit["useful_write_ci_lower_min"],
        "lower_write_bytes": cis["lower_write_bytes"]["upper"] <= limit["lower_write_bytes_ci_upper_max"],
        "lower_write_requests": cis["lower_write_requests"]["upper"] <= limit["lower_write_requests_ci_upper_max"],
        "read_p95": cis["read_p95"]["upper"] <= limit["tail_ci_upper_max"],
        "read_p99": cis["read_p99"]["upper"] <= limit["tail_ci_upper_max"],
        "write_p95": cis["write_p95"]["upper"] <= limit["tail_ci_upper_max"],
        "write_p99": cis["write_p99"]["upper"] <= limit["tail_ci_upper_max"],
        "cpu": cis["cpu"]["upper"] <= limit["cpu_ci_upper_max"],
    }
    return {"status": "PASS" if all(checks.values()) else "FAIL",
            "evidence": "paired_t_95pct", "confidence_intervals": cis, "checks": checks}


def integer_at_least(value, minimum: int) -> bool:
    return type(value) is int and value >= minimum


def positive_counter(value) -> bool:
    return integer_at_least(value, 1)


def target_health_ok(status) -> bool:
    return (
        isinstance(status, dict) and
        type(status.get("failed")) is int and status["failed"] == 0 and
        type(status.get("error")) is int and status["error"] == 0)


def sustained_decision(pair: dict) -> dict:
    raw, swapz = pair["raw"], pair["swapz"]
    limit = CONTRACT["acceptance"]["sustained"]
    def ratio(path):
        return number(metric(swapz, path), path) / number(metric(raw, path), path)
    ratios = {
        "useful_write": ratio("throughput.logical_write_mbps"),
        "lower_write_bytes": ratio("lower_io.lower_write_bytes_per_logical_write_byte"),
        "lower_write_requests": ratio("lower_io.lower_write_requests_per_1000_logical_writes"),
        "read_p99": ratio("latency.read_p99_ns"), "write_p99": ratio("latency.write_p99_ns"),
        "cold_read_p99": ratio("cold_read.p99_ns"),
        "throughput_drift": quartile_ratio(swapz.get("minute_buckets", []), "logical_write_mbps"),
        "p99_drift": quartile_ratio(swapz.get("minute_buckets", []), "p99_ns"),
    }
    gc = swapz.get("gc") or {}
    resources = swapz.get("resources") or {}
    raw_overwrite = raw.get("overwrite") or {}
    swapz_overwrite = swapz.get("overwrite") or {}
    checks = {
        "useful_write": ratios["useful_write"] >= limit["useful_write_ratio_min"],
        "lower_write_bytes": ratios["lower_write_bytes"] <= limit["lower_write_bytes_ratio_max"],
        "lower_write_requests": ratios["lower_write_requests"] <= limit["lower_write_requests_ratio_max"],
        "read_p99": ratios["read_p99"] <= limit["tail_ratio_max"],
        "write_p99": ratios["write_p99"] <= limit["tail_ratio_max"],
        "cold_read_p99": ratios["cold_read_p99"] <= limit["tail_ratio_max"],
        "throughput_drift": ratios["throughput_drift"] >= limit["throughput_drift_ratio_min"],
        "p99_drift": ratios["p99_drift"] <= limit["p99_drift_ratio_max"],
        "gc_wall": number(gc.get("wall_fraction"), "gc.wall_fraction") <= limit["gc_wall_fraction_max"],
        "gc_headroom": (
            type(gc.get("gc_no_headroom_skips")) is int and
            0 <= gc["gc_no_headroom_skips"] <=
            limit["gc_no_headroom_skips_max"]),
        "gc_relocation": (
            positive_counter(gc.get("gc_victims")) and
            positive_counter(gc.get("gc_pages"))),
        "segment_programming": positive_counter(gc.get("segment_program_sum")),
        "target_not_failed": target_health_ok(gc),
        "forward_progress": number(swapz.get("max_no_progress_seconds"), "max_no_progress_seconds") <= limit["max_no_progress_seconds"],
        "raw_repeated_overwrite": integer_at_least(
            raw_overwrite.get("measured_hot_pages_rewritten"),
            limit["minimum_rewritten_hot_pages"]),
        "swapz_repeated_overwrite": integer_at_least(
            swapz_overwrite.get("measured_hot_pages_rewritten"),
            limit["minimum_rewritten_hot_pages"]),
        "replay_rss": (
            integer_at_least(resources.get("replay_peak_rss_bytes"), 0) and
            resources["replay_peak_rss_bytes"] <=
            limit["replay_peak_rss_bytes_max"]),
        "target_ram": (
            integer_at_least(
                resources.get("metadata_and_target_peak_ram_bytes"), 0) and
            resources["metadata_and_target_peak_ram_bytes"] <=
            limit["metadata_and_target_peak_ram_bytes_max"]),
        "oracle": (
            type((swapz.get("oracle") or {}).get("mismatches")) is int and
            (swapz.get("oracle") or {}).get("mismatches") == 0),
        "cold_read": positive_counter((swapz.get("cold_read") or {}).get("pages")),
        "high_occupancy": integer_at_least(
            swapz.get("occupancy_percent"), 90),
    }
    return {"status": "PASS" if all(checks.values()) else "FAIL",
            "evidence": "directional_single_pair", "ratios": ratios, "checks": checks}


def anonymous_decision(pairs: list[dict]) -> dict:
    limit = CONTRACT["acceptance"]["anonymous"]
    rows, ok = [], True
    for pair in pairs:
        ratios = {name: 1.0 + number(pair["deltas"][name], name) for name in
                  ("swapin_p95", "swapin_p99", "useful_read", "lower_write_bytes", "lower_write_requests", "cpu")}
        pair_ok = (
            ratios["swapin_p95"] <= limit["swapin_tail_ratio_max"] and
            ratios["swapin_p99"] <= limit["swapin_tail_ratio_max"] and
            ratios["useful_read"] >= limit["useful_read_ratio_min"] and
            ratios["lower_write_bytes"] <= limit["lower_write_bytes_ratio_max"] and
            ratios["lower_write_requests"] <= limit["lower_write_requests_ratio_max"] and
            ratios["cpu"] <= limit["cpu_ratio_max"])
        for arm in (pair["raw"], pair["swapz"]):
            pair_ok &= integer_at_least(
                arm.get("observed_swap_bytes"),
                limit["minimum_observed_swap_bytes"])
            oracle_mismatches = (arm.get("oracle") or {}).get("mismatches")
            pair_ok &= (
                type(oracle_mismatches) is int and oracle_mismatches == 0)
            attribution = arm.get("anonymous_swap_attribution") or {}
            pair_ok &= positive_counter(
                (attribution.get("vmstat") or {}).get("pswpout_pages"))
            pair_ok &= positive_counter(
                (arm.get("target_io") or {}).get("target_write_bytes"))
            pair_ok &= positive_counter(
                (arm.get("lower_io") or {}).get("lower_write_bytes"))
            rounds = arm.get("rounds") or []
            pair_ok &= len(rounds) == CONTRACT["workloads"]["anonymous-swap"]["rounds"]
            pair_ok &= all(
                positive_counter((row.get("lower_io") or {}).get("lower_read_bytes")) and
                positive_counter((row.get("target_io") or {}).get("target_read_bytes")) and
                positive_counter((row.get("vmstat") or {}).get("pswpin_pages")) and
                positive_counter(
                    ((row.get("cgroup_delta") or {}).get("memory_stat") or {})
                    .get("pgmajfault"))
                for row in rounds)
        rows.append({"pair_id": pair["pair_id"], "status": "PASS" if pair_ok else "FAIL", "ratios": ratios})
        ok &= pair_ok
    return {"status": "PASS" if ok else "FAIL", "evidence": "directional_three_pair", "pairs": rows}


def evaluate(records: list[dict], protocol: str = "auto") -> dict:
    if protocol not in ("auto", "v1", "v2"):
        raise ValueError("unsupported physical qualification protocol")
    preserved = []
    for pair in records:
        if not isinstance(pair, dict) or \
                pair.get("schema") != PAIR_SCHEMA or \
                pair.get("workload") not in WORKLOADS:
            raise ValueError("invalid qualification pair")
        saved = dict(pair)
        saved["analysis_usable"] = (
            pair.get("status") == "PASS" and pair.get("excluded") is False)
        recorded_reasons = pair.get("exclusion_reasons")
        saved["analysis_exclusion_reasons"] = (
            list(recorded_reasons) if isinstance(recorded_reasons, list)
            else [])
        integrity_reasons = pair_integrity_reasons(pair)
        if integrity_reasons:
            saved["analysis_usable"] = False
            saved["analysis_exclusion_reasons"].extend(integrity_reasons)
        workload = pair["workload"]
        expected_protocol = (
            AMENDMENT_SCHEMA if workload in AMENDMENT["workloads"] else SCHEMA)
        recorded_protocol = pair.get("qualification_protocol")
        if recorded_protocol != expected_protocol and (
                recorded_protocol is not None or workload in AMENDMENT["workloads"]):
            saved["analysis_usable"] = False
            saved["analysis_exclusion_reasons"].append(
                "qualification protocol differs from workload contract")
        preserved.append(saved)

    # Check all attempts, including failed and excluded records. No pair can
    # be promoted by pooling results from different source revisions.
    sources = [row.get("source_sha") for row in preserved]
    campaign_source_sha = (
        sources[0] if sources and type(sources[0]) is str and
        re.fullmatch(r"[0-9a-f]{40}", sources[0]) and
        all(source == sources[0] for source in sources) else None)
    for row in preserved:
        raw = row.get("raw")
        swapz = row.get("swapz")
        if (campaign_source_sha is None or
                not isinstance(raw, dict) or
                not isinstance(swapz, dict) or
                raw.get("source_sha") != campaign_source_sha or
                swapz.get("source_sha") != campaign_source_sha):
            row["analysis_usable"] = False
            row["analysis_exclusion_reasons"].append(
                "campaign requires one exact source SHA across every attempted arm")

    campaign_target_identity, campaign_target_consistent = (
        common_campaign_target(preserved))
    if any(row.get("analysis_usable") for row in preserved) and \
            not campaign_target_consistent:
        for row in preserved:
            if row.get("analysis_usable"):
                row["analysis_usable"] = False
                row["analysis_exclusion_reasons"].append(
                    "campaign requires one exact physical target across accepted pairs")

    has_amendment_records = any(
        row["workload"] in AMENDMENT["workloads"] for row in preserved)
    if protocol == "v1" and has_amendment_records:
        raise ValueError("v2 workload cannot be evaluated under v1 protocol")
    include_amendment = protocol == "v2" or has_amendment_records
    evaluation_workloads = (
        WORKLOADS if include_amendment else CONTRACT["workloads"])

    raw_spread = {}
    for name, spec in evaluation_workloads.items():
        if spec["evidence"] != "statistical_paired":
            continue
        rows = [row for row in preserved if row["workload"] == name and row["analysis_usable"]]
        rates = [number(metric(row["raw"], "throughput.logical_write_mbps"), "raw rate") for row in rows]
        if len(rates) >= 2:
            spread = (max(rates) - min(rates)) / max(rates)
            raw_spread[name] = spread
            if spread > CONTRACT["screening"]["same_workload_raw_spread_max"]:
                reason = f"raw repeat spread {spread:.6f} exceeds prospective 0.100000"
                for row in rows:
                    row["analysis_usable"] = False
                    row["analysis_exclusion_reasons"].append(reason)

    decisions, overall = {}, True
    for name, spec in evaluation_workloads.items():
        attempts = [row for row in preserved if row["workload"] == name]
        rows = [row for row in attempts if row["analysis_usable"]]
        required = spec["pairs"]
        pair_indices = [row.get("pair_index") for row in attempts]
        order_ok = (
            len(attempts) == required and
            all(type(index) is int for index in pair_indices) and
            sorted(pair_indices) == list(range(1, required + 1)) and
            all(row.get("order") == spec["counterbalanced_order"][row["pair_index"] - 1]
                for row in attempts))
        pair_ids = [row.get("pair_id") for row in attempts]
        pair_ids_unique = (
            all(type(pair_id) is str and pair_id for pair_id in pair_ids) and
            len(set(pair_ids)) == len(pair_ids))
        # A failed/excluded attempt followed by a passing replacement must
        # never qualify: count all recorded attempts, not only usable rows.
        if len(rows) != required or not order_ok or not pair_ids_unique:
            decision = {"status": "INCOMPLETE", "accepted_pairs": len(rows),
                        "attempted_pairs": len(attempts), "required_pairs": required,
                        "prospective_order_complete": order_ok,
                        "pair_ids_unique": pair_ids_unique,
                        "raw_repeat_spread": raw_spread.get(name)}
        elif spec["evidence"] == "statistical_paired":
            decision = service_decision(rows, name)
        elif name == "sd-high-occupancy-churn":
            decision = sustained_decision(rows[0])
        else:
            decision = anonymous_decision(rows)
        decisions[name] = decision
        overall &= decision["status"] == "PASS"
    return {"schema": SUMMARY_SCHEMA,
            "acceptance_manifest_sha256": acceptance_manifest_sha256(),
            "contract": contract(),
            "prospective_amendment": amendment(),
            "amendment_active": include_amendment,
            "evaluation_protocol": "v2" if include_amendment else "v1",
            "campaign_source_sha": campaign_source_sha,
            "campaign_target_identity": campaign_target_identity,
            "campaign_target_consistent": campaign_target_consistent,
            "status": "PASS" if overall else "FAIL_OR_INCOMPLETE",
            "decisions": decisions, "raw_repeat_spread": raw_spread, "records": preserved}


def write_qualification_artifact(path: Path, value: dict,
                                 description: str) -> None:
    try:
        write_new_json(path, value)
    except FileExistsError as exc:
        raise ValueError(f"refusing to overwrite {description}") from exc


def load_records(paths: list[str]) -> list[dict]:
    result = []
    for path in paths:
        value = json.loads(Path(path).read_text())
        result.extend(value if isinstance(value, list) else [value])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("contract")
    sub.add_parser("amendment")
    pair = sub.add_parser("pair")
    pair.add_argument("--raw", required=True); pair.add_argument("--swapz", required=True)
    pair.add_argument("--workload", required=True); pair.add_argument("--pair-id", required=True)
    pair.add_argument("--pair-index", type=int, required=True)
    pair.add_argument("--order", choices=("raw-first", "swapz-first"), required=True)
    pair.add_argument("--exclude", action="append", default=[]); pair.add_argument("--result", required=True)
    summary = sub.add_parser("evaluate")
    summary.add_argument("--protocol", choices=("auto", "v1", "v2"), default="auto")
    summary.add_argument("--result")
    summary.add_argument("reports", nargs="+")
    args = parser.parse_args()
    try:
        if args.command == "contract":
            print(json.dumps(contract(), sort_keys=True))
        elif args.command == "amendment":
            print(json.dumps(amendment(), sort_keys=True))
        elif args.command == "pair":
            raw = json.loads(Path(args.raw).read_text()); swapz = json.loads(Path(args.swapz).read_text())
            record = compare_pair(raw, swapz, args.workload, args.pair_id,
                                  args.pair_index, args.order, args.exclude)
            write_qualification_artifact(
                Path(args.result), record, "qualification pair")
            print(json.dumps(record, sort_keys=True))
        else:
            result = evaluate(
                load_records(args.reports), protocol=args.protocol)
            if args.result:
                write_qualification_artifact(
                    Path(args.result), result, "qualification summary")
            print(json.dumps(result, sort_keys=True))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, "BLOCKED/FAIL: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
