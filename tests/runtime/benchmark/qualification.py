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
DM_UUID_RE = re.compile(r"SWAPZ-(?:PRIMARY|BENCH)-[a-f0-9]{32}")


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
            raise ValueError(f"duplicate JSON key {key}")
        result[key] = value
    return result


def _reject_json_constant(value):
    raise ValueError(f"non-finite JSON number {value}")


def _load_json_path(path: str | Path):
    return json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_reject_json_constant)


def _load_frozen_physical_contract() -> dict:
    try:
        document = json.loads(
            ACCEPTANCE_MANIFEST.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant)
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
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant)
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


def exact_json_value(value, expected) -> bool:
    """JSON scalar comparisons must not coerce bools to ints or omit nulls."""
    return type(value) is type(expected) and value == expected


LATENCY_SUB_BUCKETS = 16
LATENCY_EXPONENTS = 65
LATENCY_BIN_COUNT = LATENCY_SUB_BUCKETS * LATENCY_EXPONENTS


def latency_bin_index(value: int) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("latency sample must be a positive integer")
    exponent = min(LATENCY_EXPONENTS - 1, max(0, value.bit_length() - 1))
    base = 1 << exponent
    sub_bucket = min(
        LATENCY_SUB_BUCKETS - 1,
        ((value - base) * LATENCY_SUB_BUCKETS) // base)
    return exponent * LATENCY_SUB_BUCKETS + sub_bucket


def latency_bin_upper(index: int) -> int:
    if type(index) is not int or not 0 <= index < LATENCY_BIN_COUNT:
        raise ValueError("latency histogram bin index is invalid")
    exponent, sub_bucket = divmod(index, LATENCY_SUB_BUCKETS)
    base = 1 << exponent
    return base + (
        (sub_bucket + 1) * base + LATENCY_SUB_BUCKETS - 1
    ) // LATENCY_SUB_BUCKETS


def latency_histogram_summary(evidence, label: str,
                              expected_count: int | None = None) -> dict:
    if not isinstance(evidence, dict) or set(evidence) != {
            "count", "max_ns", "bins"}:
        raise ValueError(f"{label} latency histogram fields are incomplete")
    count = evidence["count"]
    maximum = evidence["max_ns"]
    bins = evidence["bins"]
    if (type(count) is not int or count <= 0 or
            type(maximum) is not int or maximum <= 0 or
            not isinstance(bins, list) or not bins):
        raise ValueError(f"{label} latency histogram is malformed")
    if expected_count is not None and count != expected_count:
        raise ValueError(f"{label} latency histogram count differs from measured operations")
    parsed = []
    total = 0
    previous_index = -1
    for row in bins:
        if (not isinstance(row, list) or len(row) != 2 or
                type(row[0]) is not int or type(row[1]) is not int or
                not 0 <= row[0] < LATENCY_BIN_COUNT or row[1] <= 0 or
                row[0] <= previous_index):
            raise ValueError(f"{label} latency histogram bins are malformed")
        previous_index = row[0]
        total += row[1]
        parsed.append((row[0], row[1]))
    if total != count or latency_bin_index(maximum) != parsed[-1][0]:
        raise ValueError(f"{label} latency histogram count/max is inconsistent")

    def percentile(fraction: float) -> int:
        target = max(1, math.ceil(count * fraction))
        seen = 0
        for index, bin_count in parsed:
            seen += bin_count
            if seen >= target:
                return latency_bin_upper(index)
        raise ValueError(f"{label} latency histogram percentile is incomplete")

    return {
        "count": count,
        "p50_ns": percentile(.50),
        "p95_ns": percentile(.95),
        "p99_ns": percentile(.99),
        "max_ns": maximum,
    }


def latency_histogram_reasons(summary, evidence, label: str,
                              expected_count: int | None = None) -> list[str]:
    try:
        derived = latency_histogram_summary(
            evidence, label, expected_count=expected_count)
        if not isinstance(summary, dict):
            raise ValueError("latency summary is missing")
        for field in ("count", "p50_ns", "p95_ns", "p99_ns", "max_ns"):
            if metric(summary, field) != derived[field]:
                raise ValueError(
                    f"{field} differs from serialized latency histogram")
        return []
    except (TypeError, ValueError) as exc:
        return [f"{label} latency evidence: {exc}"]


def block_geometry_reasons(arm: dict, label: str) -> list[str]:
    """Recompute derived logical geometry and deterministic recipe provenance."""
    reasons = []
    try:
        logical = metric(arm, "logical_pages")
        occupied = metric(arm, "occupied_pages")
        hot = metric(arm, "hot_pages")
        occupancy_percent = metric(arm, "occupancy_percent")
        hot_percent = metric(arm, "hot_percent")
        seed = metric(arm, "workload_seed")
        if (type(logical) is not int or logical <= 0 or
                type(occupied) is not int or occupied <= 0 or
                type(hot) is not int or hot <= 0 or
                type(occupancy_percent) is not int or
                type(hot_percent) is not int or type(seed) is not int):
            raise ValueError("logical geometry/seed is missing or mistyped")
        if occupied != logical * occupancy_percent // 100:
            raise ValueError("occupied_pages differs from logical occupancy")
        if hot != logical * hot_percent // 100 or hot >= occupied:
            raise ValueError("hot_pages differs from logical hot region")
        fill_sha = metric(arm, "fill_fixture_sha256")
        churn_sha = metric(arm, "churn_fixture_sha256")
        if (not isinstance(fill_sha, str) or
                not re.fullmatch(r"[0-9a-f]{64}", fill_sha) or
                not isinstance(churn_sha, str) or
                not re.fullmatch(r"[0-9a-f]{64}", churn_sha)):
            raise ValueError("fixture SHA-256 is malformed")
        recipe = hashlib.sha256(json.dumps({
            "seed": seed, "logical": logical, "occupied": occupied,
            "hot": hot, "qd": metric(arm, "qd"),
            "read": metric(arm, "read_percent"),
            "fill": fill_sha, "churn": churn_sha,
        }, sort_keys=True).encode()).hexdigest()
        if metric(arm, "operation_recipe_sha256") != recipe:
            raise ValueError("operation recipe digest differs from arm geometry")
    except (TypeError, ValueError) as exc:
        reasons.append(f"{label} block geometry: {exc}")
    return reasons


def anonymous_accounting_reasons(arm: dict, label: str) -> list[str]:
    """Recompute anonymous throughput, lower-I/O and attributed CPU columns."""
    reasons = []
    try:
        byte_count = metric(arm, "bytes")
        pages = metric(arm, "pages")
        rounds = metric(arm, "rounds")
        if (type(byte_count) is not int or byte_count <= 0 or
                type(pages) is not int or pages != byte_count // 4096 or
                not isinstance(rounds, list)):
            raise ValueError("byte/page/round accounting is malformed")
        expected_rounds = workload_spec("anonymous-swap")["rounds"]
        if len(rounds) != expected_rounds:
            raise ValueError("round count differs from workload contract")
        round_seconds = []
        for index, row in enumerate(rounds):
            seconds = number(metric(row, "seconds"), f"round[{index}].seconds")
            if seconds <= 0:
                raise ValueError("round duration must be positive")
            round_seconds.append(seconds)
            reasons += latency_histogram_reasons(
                row.get("latency"),
                (row.get("latency") or {}).get("histogram"),
                f"{label} round[{index}]", expected_count=pages)

        useful_read_bytes = byte_count * expected_rounds
        recorded_useful = metric(arm, "throughput.useful_read_bytes")
        read_seconds = number(
            metric(arm, "throughput.read_seconds"), "throughput.read_seconds")
        useful_read_mbps = number(
            metric(arm, "throughput.useful_read_mbps"),
            "throughput.useful_read_mbps")
        if type(recorded_useful) is not int or recorded_useful != useful_read_bytes:
            raise ValueError("useful read byte count is inconsistent")
        if not math.isclose(
                read_seconds, math.fsum(round_seconds),
                rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("read_seconds differs from round durations")
        if not math.isclose(
                useful_read_mbps,
                useful_read_bytes / read_seconds / 1_000_000,
                rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError("useful read throughput differs from measured work")

        lower_bytes = metric(arm, "lower_io.lower_write_bytes")
        lower_requests = metric(arm, "lower_io.lower_write_requests")
        lower_reads = metric(arm, "lower_io.lower_read_bytes")
        if (type(lower_bytes) is not int or lower_bytes <= 0 or
                type(lower_requests) is not int or lower_requests <= 0 or
                type(lower_reads) is not int or lower_reads <= 0):
            raise ValueError("lower-device counters are missing or nonpositive")
        expected_lower = {
            "lower_io.lower_write_bytes_per_logical_fill_byte":
                lower_bytes / byte_count,
            "lower_io.lower_write_requests_per_1000_fill_pages":
                lower_requests * 1000 / pages,
            "lower_io.lower_read_bytes_per_logical_read_byte":
                lower_reads / useful_read_bytes,
        }
        for path, calculated in expected_lower.items():
            if not math.isclose(
                    number(metric(arm, path), path), calculated,
                    rel_tol=1e-9, abs_tol=1e-12):
                raise ValueError(f"{path} differs from lower-device counters")

        process_user = number(
            metric(arm, "cpu.workload_process_user_seconds"),
            "cpu.workload_process_user_seconds")
        process_system = number(
            metric(arm, "cpu.workload_process_system_seconds"),
            "cpu.workload_process_system_seconds")
        process_total = number(
            metric(arm, "cpu.workload_process_cpu_seconds"),
            "cpu.workload_process_cpu_seconds")
        worker = number(
            metric(arm, "cpu.exported_swapz_worker_cpu_seconds"),
            "cpu.exported_swapz_worker_cpu_seconds")
        attributed = number(
            metric(arm, "cpu.attributed_cpu_seconds"),
            "cpu.attributed_cpu_seconds")
        observed_cpu = number(
            metric(arm, "cpu.measured_cpu_seconds_per_useful_byte"),
            "cpu.measured_cpu_seconds_per_useful_byte")
        if min(process_user, process_system, process_total, worker, attributed) < 0:
            raise ValueError("CPU components must be nonnegative")
        if label == "raw" and worker != 0:
            raise ValueError("raw arm unexpectedly reports swapz worker CPU")
        if (not math.isclose(process_total, process_user + process_system,
                             rel_tol=1e-12, abs_tol=1e-12) or
                not math.isclose(attributed, process_total + worker,
                                 rel_tol=1e-12, abs_tol=1e-12) or
                not math.isclose(
                    observed_cpu,
                    attributed / (byte_count + useful_read_bytes),
                    rel_tol=1e-9, abs_tol=1e-15)):
            raise ValueError("attributed CPU columns are inconsistent")

        verified_pages = metric(arm, "oracle.verified_pages")
        if (type(verified_pages) is not int or
                verified_pages != pages * expected_rounds):
            raise ValueError("byte oracle coverage differs from workload pages")
        reasons += latency_histogram_reasons(
            arm.get("swapin_latency"),
            (arm.get("swapin_latency") or {}).get("histogram"),
            f"{label} aggregate swap-in",
            expected_count=pages * expected_rounds)
    except (TypeError, ValueError) as exc:
        reasons.append(f"{label} anonymous accounting: {exc}")
    return reasons


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


def measured_block_accounting_reasons(arm: dict, workload: str,
                                      label: str) -> list[str]:
    """Do not trust normalized columns detached from completed I/O counters."""
    if workload == "anonymous-swap":
        return anonymous_accounting_reasons(arm, label)
    reasons = []
    try:
        reads = metric(arm, "read_ops")
        writes = metric(arm, "write_ops")
        seconds = number(metric(arm, "seconds"), "seconds")
        if (type(reads) is not int or type(writes) is not int or
                reads <= 0 or writes <= 0 or seconds <= 0):
            raise ValueError("read/write operation counts and seconds must be positive")
        requested = workload_spec(workload).get("measure_operations")
        if requested is not None and reads + writes != requested:
            raise ValueError("measured operation count differs from fixed work")
        useful_bytes = (reads + writes) * 4096
        useful_write_bytes = writes * 4096
        lower_bytes = metric(arm, "lower_io.lower_write_bytes")
        lower_requests = metric(arm, "lower_io.lower_write_requests")
        if (type(lower_bytes) is not int or type(lower_requests) is not int or
                lower_bytes <= 0 or lower_requests <= 0):
            raise ValueError("independent lower WRITE counters are missing or nonpositive")
        expected = {
            "throughput.logical_write_mbps": useful_write_bytes / seconds / 1_000_000,
            "lower_io.lower_write_bytes_per_logical_write_byte":
                lower_bytes / useful_write_bytes,
            "lower_io.lower_write_requests_per_1000_logical_writes":
                lower_requests * 1000 / writes,
        }
        for path, calculated in expected.items():
            observed = number(metric(arm, path), path)
            if not math.isclose(observed, calculated, rel_tol=1e-9, abs_tol=1e-12):
                raise ValueError(f"{path} differs from independent measured counters")
        replay_user = number(metric(arm, "cpu.replay_user_seconds"), "cpu.replay_user_seconds")
        replay_system = number(metric(arm, "cpu.replay_system_seconds"), "cpu.replay_system_seconds")
        worker = number(
            metric(arm, "cpu.exported_swapz_worker_cpu_seconds"),
            "cpu.exported_swapz_worker_cpu_seconds")
        if min(replay_user, replay_system, worker) < 0 or (label == "raw" and worker != 0):
            raise ValueError("measured CPU component is invalid")
        observed_cpu = number(
            metric(arm, "cpu.measured_cpu_seconds_per_useful_byte"),
            "cpu.measured_cpu_seconds_per_useful_byte")
        if not math.isclose(
                observed_cpu, (replay_user + replay_system + worker) / useful_bytes,
                rel_tol=1e-9, abs_tol=1e-15):
            raise ValueError("normalized CPU differs from measured CPU components")
        resources = metric(arm, "resources")
        rss = metric(arm, "resources.replay_peak_rss_bytes")
        process_rss = metric(arm, "resources.replay_process_maxrss_bytes")
        start_rss = metric(arm, "resources.replay_measurement_start_maxrss_bytes")
        growth = metric(arm, "resources.replay_measurement_peak_rss_growth_bytes")
        if (not isinstance(resources, dict) or
                any(type(value) is not int for value in
                    (rss, process_rss, start_rss, growth)) or
                not 0 <= start_rss <= rss or process_rss != rss or
                growth != rss - start_rss):
            raise ValueError("replay absolute RSS evidence is inconsistent")
    except (ValueError, TypeError) as exc:
        reasons.append(f"{label} measured accounting: {exc}")
    return reasons


def sustained_coverage_reasons(arm: dict, label: str) -> list[str]:
    """Prove the hour of occupied, progressing work was actually measured."""
    spec = CONTRACT["workloads"]["sd-high-occupancy-churn"]
    reasons = []
    try:
        seconds = number(metric(arm, "seconds"), "seconds")
        if seconds < spec["measure_seconds"]:
            raise ValueError("one-hour measured duration not completed")
        minutes = metric(arm, "minute_buckets")
        if (not isinstance(minutes, list) or len(minutes) != 60 or
                any(not isinstance(row, dict) or
                    type(row.get("minute")) is not int or
                    row["minute"] != index or
                    not positive_counter(row.get("operations")) or
                    not integer_at_least(row.get("read_operations"), 0) or
                    not integer_at_least(row.get("write_operations"), 0) or
                    row["read_operations"] + row["write_operations"] != row["operations"]
                    for index, row in enumerate(minutes)) or
                sum(row["read_operations"] for row in minutes) != arm.get("read_ops") or
                sum(row["write_operations"] for row in minutes) != arm.get("write_ops")):
            raise ValueError("minute bucket coverage or operation conservation is invalid")
        for row in minutes:
            duration = number(
                metric(row, "duration_seconds"), "minute.duration_seconds")
            throughput = number(
                metric(row, "logical_write_mbps"),
                "minute.logical_write_mbps")
            p95 = number(metric(row, "p95_ns"), "minute.p95_ns")
            p99 = number(metric(row, "p99_ns"), "minute.p99_ns")
            histogram = latency_histogram_summary(
                metric(row, "latency_histogram"), "minute combined",
                expected_count=row["operations"])
            if (not math.isclose(duration, 60.0, abs_tol=1e-6) or
                    not math.isclose(
                        throughput,
                        row["write_operations"] * 4096 /
                        duration / 1_000_000,
                        rel_tol=1e-9, abs_tol=1e-12) or
                    p95 != histogram["p95_ns"] or
                    p99 != histogram["p99_ns"]):
                raise ValueError(
                    "minute throughput/duration or tail latency is inconsistent")
        intervals = metric(arm, "sustained_intervals")
        arm_started = arm.get("arm_started_monotonic_ns")
        measured_started = arm.get("measured_start_monotonic_ns")
        measured_finished = arm.get("measured_end_monotonic_ns")
        arm_finished = arm.get("arm_finished_monotonic_ns")
        if (not isinstance(intervals, list) or not intervals or
                type(arm_started) is not int or arm_started <= 0 or
                type(measured_started) is not int or
                measured_started < arm_started or
                type(measured_finished) is not int or
                measured_finished <= measured_started or
                type(arm_finished) is not int or
                arm_finished < measured_finished or
                not math.isclose(
                    (measured_finished - measured_started) / 1e9, seconds,
                    rel_tol=1e-9, abs_tol=1e-6)):
            raise ValueError(
                "one-hour telemetry intervals or measured-arm chronology are absent")
        previous_end = 0.0
        previous_monotonic_end = None
        positive_gc_interval = False
        for index, row in enumerate(intervals):
            if not isinstance(row, dict) or type(row.get("interval")) is not int or row["interval"] != index:
                raise ValueError("telemetry interval indexing is invalid")
            start = number(metric(row, "start_seconds"), "interval.start_seconds")
            end = number(metric(row, "end_seconds"), "interval.end_seconds")
            duration = number(metric(row, "duration_seconds"), "interval.duration_seconds")
            gap = number(metric(row, "max_no_progress_seconds"), "interval.max_no_progress_seconds")
            monotonic_start = row.get("start_monotonic_ns")
            monotonic_end = row.get("end_monotonic_ns")
            if (type(monotonic_start) is not int or
                    type(monotonic_end) is not int or
                    monotonic_start < arm_started or
                    monotonic_end <= monotonic_start or
                    monotonic_end > arm_finished or
                    (previous_monotonic_end is not None and
                     monotonic_start != previous_monotonic_end) or
                    not math.isclose(
                        (monotonic_end - monotonic_start) / 1e9, duration,
                        rel_tol=1e-9, abs_tol=1e-6) or
                    start < 0 or
                    (start > 1.0 if index == 0 else
                     not math.isclose(start, previous_end, abs_tol=1e-6)) or
                    duration <= 0 or
                    not math.isclose(end - start, duration, rel_tol=1e-9, abs_tol=1e-6) or
                    gap < 0 or gap > CONTRACT["acceptance"]["sustained"]["max_no_progress_seconds"]):
                raise ValueError(
                    "telemetry has invalid absolute chronology, a gap, "
                    "negative duration or stalled forward progress")
            if label == "swapz":
                gc = row.get("gc")
                if (not target_health_ok(gc) or
                        type(gc.get("gc_no_headroom_skips")) is not int or
                        gc["gc_no_headroom_skips"] != 0):
                    raise ValueError("interval target failure or GC no-headroom skip")
                for field in ("gc_wall_ns", "gc_victims", "gc_pages"):
                    if type(gc.get(field)) is not int or gc[field] < 0:
                        raise ValueError(
                            "interval GC activity counters are missing or malformed")
                positive_gc_interval = positive_gc_interval or (
                    monotonic_start >= measured_started and
                    monotonic_end <= measured_finished and
                    gc["gc_victims"] > 0 and gc["gc_pages"] > 0)
            previous_end = end
            previous_monotonic_end = monotonic_end
        if (intervals[0]["start_monotonic_ns"] > measured_started or
                intervals[-1]["end_monotonic_ns"] < measured_finished):
            raise ValueError(
                "telemetry intervals do not cover the measured monotonic window")
        if previous_end < spec["measure_seconds"]:
            raise ValueError("telemetry does not cover the full measured hour")
        if label == "swapz" and not positive_gc_interval:
            raise ValueError(
                "telemetry contains no fully measured interval with GC relocation")
        occupancy = metric(arm, "occupancy_transitions")
        required_phases = ("initial", "post-fill", "post-warmup", "measured-end")
        occupied = metric(arm, "occupied_pages")
        if (type(occupied) is not int or occupied <= 0 or
                type(arm.get("logical_pages")) is not int or
                occupied != arm["logical_pages"] * spec["logical_occupancy_percent"] // 100 or
                not isinstance(occupancy, list) or
                len(occupancy) != len(required_phases) or
                any(not isinstance(row, dict) or row.get("phase") != phase or
                    type(row.get("occupied_pages")) is not int or
                    row["occupied_pages"] != (0 if index == 0 else occupied)
                    for index, (row, phase) in enumerate(zip(occupancy, required_phases))) or
                not integer_at_least((arm.get("oracle") or {}).get("verified_pages"), occupied)):
            raise ValueError("90% occupancy or final oracle coverage is missing")
    except (ValueError, TypeError) as exc:
        reasons.append(f"{label} sustained evidence: {exc}")
    return reasons


def validate_arm(arm: dict, workload: str, label: str) -> list[str]:
    spec = workload_spec(workload)
    reasons = validate_module_provenance(arm, label)
    # Monotonic timestamps bind physical arm order; the campaign sealer pins boot ID.
    started = arm.get("arm_started_monotonic_ns")
    finished = arm.get("arm_finished_monotonic_ns")
    boot_id = arm.get("arm_boot_id")
    if (type(started) is not int or type(finished) is not int or
            started <= 0 or finished <= started or
            not isinstance(boot_id, str) or
            not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", boot_id)):
        reasons.append(f"{label} arm chronology/boot identity is missing or malformed")
    reasons += measured_block_accounting_reasons(arm, workload, label)
    if workload == "anonymous-swap":
        for field, expected in (("bytes", spec["bytes"]),
                                ("round_count", spec["rounds"]),
                                ("required_swap_bytes", spec["minimum_observed_swap_bytes"]),
                                ("content", spec["content"])):
            if field not in arm or not exact_json_value(arm[field], expected):
                reasons.append(
                    f"{label} {field} is missing, mistyped or differs from prospective workload")
        if (not isinstance(arm.get("source_sha"), str) or
                not re.fullmatch(r"[0-9a-f]{40}", arm["source_sha"])):
            reasons.append(f"{label} source SHA is missing or malformed")
        identity = arm.get("swap_device_identity")
        if not isinstance(identity, dict):
            reasons.append(f"{label} admitted swap-device identity is missing")
        else:
            device = identity.get("device")
            if not isinstance(device, str) or not MAJOR_MINOR_RE.fullmatch(device):
                reasons.append(
                    f"{label} admitted swap-device major:minor is malformed")
            lower_device = identity.get("lower_device")
            if label == "raw":
                if identity.get("dm_uuid") is not None:
                    reasons.append(
                        "raw anonymous arm unexpectedly carries a DM UUID")
                if lower_device != device:
                    reasons.append(
                        "raw anonymous arm lower identity differs from device")
            else:
                if (not isinstance(identity.get("dm_uuid"), str) or
                        not DM_UUID_RE.fullmatch(identity["dm_uuid"]) or
                        identity.get("dm_target") != "swapz" or
                        not isinstance(lower_device, str) or
                        not MAJOR_MINOR_RE.fullmatch(lower_device)):
                    reasons.append(
                        "swapz anonymous arm lacks exact mapper/lower identity")
            partuuid = identity.get("physical_partuuid")
            device_bytes = identity.get("physical_device_bytes")
            parent_device = identity.get("parent_major_minor")
            if (normalize_partuuid(partuuid) != partuuid or
                    type(device_bytes) is not int or device_bytes <= 0 or
                    not isinstance(parent_device, str) or
                    not MAJOR_MINOR_RE.fullmatch(parent_device) or
                    any(not isinstance(identity.get(key), str) or
                        not identity[key] for key in
                        ("parent_model", "parent_transport"))):
                reasons.append(
                    f"{label} anonymous physical lower identity is missing or malformed")
        cgroup = arm.get("cgroup_before") or {}
        if (not isinstance(cgroup, dict) or
                "memory_max" not in cgroup or
                not exact_json_value(cgroup["memory_max"],
                                     spec["memory_max_bytes"])):
            reasons.append(
                f"{label} cgroup memory.max is missing, mistyped or differs from prospective workload")
        required_swap_headroom = spec["bytes"] - spec["memory_max_bytes"]
        swap_max = cgroup.get("memory_swap_max") if isinstance(cgroup, dict) else None
        if swap_max != "max" and (
                type(swap_max) is not int or swap_max < required_swap_headroom):
            reasons.append(
                f"{label} cgroup memory.swap.max cannot cover prospective working-set excess")
        after_cgroup = arm.get("cgroup_after")
        if (not isinstance(after_cgroup, dict) or
                cgroup.get("path") != after_cgroup.get("path")):
            reasons.append(f"{label} cgroup identity changed during arm")
        for inventory_name in ("swap_inventory_before", "swap_inventory_after"):
            inventory = arm.get(inventory_name)
            if (not isinstance(inventory, list) or len(inventory) != 1 or
                    not isinstance(inventory[0], dict) or
                    inventory[0].get("device") != identity.get("device")):
                reasons.append(
                    f"{label} {inventory_name} does not contain exactly the admitted swap target")
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
    duration_fields = {"warmup_seconds", "measure_seconds_requested"}
    for field, expected_value in expected.items():
        valid = field in arm
        if valid and expected_value is None:
            valid = arm[field] is None
        elif valid and field in duration_fields:
            try:
                valid = number(arm[field], field) == float(expected_value)
            except ValueError:
                valid = False
        elif valid:
            valid = exact_json_value(arm[field], expected_value)
        if not valid:
            reasons.append(
                f"{label} {field} is missing, mistyped or differs from prospective workload")
    reasons += block_geometry_reasons(arm, label)
    latency = arm.get("latency")
    if isinstance(latency, dict):
        for operation in ("read", "write"):
            summary = {
                "count": latency.get(f"{operation}_count"),
                "p50_ns": latency.get(f"{operation}_p50_ns"),
                "p95_ns": latency.get(f"{operation}_p95_ns"),
                "p99_ns": latency.get(f"{operation}_p99_ns"),
                "max_ns": latency.get(f"{operation}_max_ns"),
            }
            reasons += latency_histogram_reasons(
                summary, latency.get(f"{operation}_histogram"),
                f"{label} {operation}",
                expected_count=arm.get(f"{operation}_ops"))
    else:
        reasons.append(f"{label} latency summary is missing")
    identity = arm.get("device_identity")
    if not isinstance(identity, dict):
        reasons.append(f"{label} physical identity is missing or malformed")
        identity = {}
    partuuid = identity.get("physical_partuuid")
    device_bytes = identity.get("physical_device_bytes")
    lower_major_minor = identity.get("lower_major_minor")
    if (not isinstance(arm.get("source_sha"), str) or
            not re.fullmatch(r"[0-9a-f]{40}", arm["source_sha"])):
        reasons.append(f"{label} source SHA is missing or malformed")
    if (normalize_partuuid(partuuid) != partuuid or
            type(device_bytes) is not int or device_bytes <= 0 or
            not isinstance(lower_major_minor, str) or
            not MAJOR_MINOR_RE.fullmatch(lower_major_minor)):
        reasons.append(f"{label} physical identity is missing or malformed")
    if label == "raw" and identity.get("dm_uuid") is not None:
        reasons.append("raw arm unexpectedly carries a DM UUID")
    if label == "swapz" and (
            not isinstance(identity.get("dm_uuid"), str) or
            not DM_UUID_RE.fullmatch(identity["dm_uuid"])):
        reasons.append("swapz arm has no valid pinned DM UUID")
    if (not isinstance(identity.get("parent_major_minor"), str) or
            not MAJOR_MINOR_RE.fullmatch(identity["parent_major_minor"]) or
            not isinstance(identity.get("parent_model"), str) or
            not identity["parent_model"] or
            not isinstance(identity.get("parent_transport"), str) or
            not identity["parent_transport"]):
        reasons.append(f"{label} physical parent identity is missing or malformed")
    if workload == "sd-high-occupancy-churn":
        reasons += sustained_coverage_reasons(arm, label)
        elapsed = arm.get("seconds")
        if (type(elapsed) not in (int, float) or
                not math.isfinite(elapsed) or
                elapsed < spec["measure_seconds"]):
            reasons.append(f"{label} sustained measured duration is shorter than one hour")
    if workload == "sd-high-occupancy-churn":
        cold = arm.get("cold_read")
        if not isinstance(cold, dict):
            reasons.append(f"{label} cold-read evidence is missing or malformed")
            cold = {}
        reasons += latency_histogram_reasons(
            cold, cold.get("histogram"), f"{label} cold read",
            expected_count=cold.get("pages"))
    resources = arm.get("resources")
    if not isinstance(resources, dict):
        reasons.append(f"{label} resource evidence is missing or malformed")
        resources = {}
    rss = resources.get("replay_peak_rss_bytes")
    if type(rss) is not int or rss < 0:
        reasons.append(f"{label} replay peak RSS is missing")
    elif rss > CONTRACT["acceptance"]["sustained"]["replay_peak_rss_bytes_max"]:
        reasons.append(f"{label} replay peak RSS exceeds prospective bound")
    if label == "swapz":
        # The replay finishes before safe mapper teardown, so it cannot own the
        # qualifying metadata/target RAM result. A legacy scalar may remain as
        # a nonnegative diagnostic; the campaign sealer derives the actual
        # frozen RAM gate from the separate post-teardown host trace.
        peak = resources.get("metadata_and_target_peak_ram_bytes")
        if peak is not None and (type(peak) is not int or peak < 0):
            reasons.append("swapz metadata/target RAM diagnostic is malformed")
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
    if type(pair_index) is not int or not 1 <= pair_index <= spec["pairs"]:
        reasons.append("pair index is outside prospective repetition plan")
    elif order != spec["counterbalanced_order"][pair_index - 1]:
        reasons.append("pair order differs from prospective order")
    reasons += validate_arm(raw, workload, "raw")
    reasons += validate_arm(swapz, workload, "swapz")
    if raw.get("arm_boot_id") != swapz.get("arm_boot_id"):
        reasons.append("physical pair arm boot identity mismatch")
    first, second = ((raw, swapz) if order == "raw-first" else
                     (swapz, raw))
    if (type(first.get("arm_finished_monotonic_ns")) is int and
            type(second.get("arm_started_monotonic_ns")) is int and
            first["arm_finished_monotonic_ns"] >=
            second["arm_started_monotonic_ns"]):
        reasons.append("physical pair arms overlap or violate counterbalanced order")
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
        raw_identity = raw.get("device_identity")
        swapz_identity = swapz.get("device_identity")
        if not isinstance(raw_identity, dict):
            reasons.append("raw physical pair identity is missing or malformed")
            raw_identity = {}
        if not isinstance(swapz_identity, dict):
            reasons.append("swapz physical pair identity is missing or malformed")
            swapz_identity = {}
        for field in ("physical_partuuid", "physical_device_bytes", "lower_major_minor",
                      "parent_major_minor", "parent_model", "parent_transport"):
            if raw_identity.get(field) != swapz_identity.get(field):
                reasons.append("physical pair identity mismatch: " + field)
    else:
        raw_identity = raw.get("swap_device_identity")
        swapz_identity = swapz.get("swap_device_identity")
        if not isinstance(raw_identity, dict):
            reasons.append("raw anonymous pair identity is missing or malformed")
            raw_identity = {}
        if not isinstance(swapz_identity, dict):
            reasons.append("swapz anonymous pair identity is missing or malformed")
            swapz_identity = {}
        if raw_identity.get("device") != swapz_identity.get("lower_device"):
            reasons.append("anonymous pair physical lower identity mismatch")
        for field in (
                "physical_partuuid", "physical_device_bytes",
                "parent_major_minor", "parent_model", "parent_transport"):
            if raw_identity.get(field) != swapz_identity.get(field):
                reasons.append(
                    "anonymous pair physical lower identity mismatch: " + field)
    for label, arm in (("raw", raw), ("swapz", swapz)):
        if arm.get("verdict") != "PASS":
            reasons.append(f"{label} arm verdict is not PASS")
        oracle = arm.get("oracle")
        if not isinstance(oracle, dict):
            reasons.append(f"{label} byte oracle evidence is malformed")
            oracle = {}
        oracle_mismatches = oracle.get("mismatches")
        if type(oracle_mismatches) is not int or oracle_mismatches != 0:
            reasons.append(f"{label} byte oracle failed or is unavailable")
        screen = arm.get("performance_screening")
        if not isinstance(screen, dict):
            reasons.append(f"{label} performance screening is malformed")
            screen = {}
        if screen.get("status") != "SCREENED":
            screen_reasons = screen.get("reasons")
            if (not isinstance(screen_reasons, list) or
                    any(not isinstance(reason, str)
                        for reason in screen_reasons)):
                screen_reasons = ["screening not usable"]
            for reason in screen_reasons or ["screening not usable"]:
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
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
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
        raw_lower = raw_identity.get("lower_device")
        swapz_lower = swapz_identity.get("lower_device")
        physical_fields = (
            "physical_partuuid", "physical_device_bytes",
            "parent_major_minor", "parent_model", "parent_transport")
        if (not isinstance(raw_device, str) or
                not MAJOR_MINOR_RE.fullmatch(raw_device) or
                raw_device != raw_lower or raw_lower != swapz_lower or
                any(raw_identity.get(field) != swapz_identity.get(field)
                    for field in physical_fields)):
            return None
        partuuid = raw_identity.get("physical_partuuid")
        device_bytes = raw_identity.get("physical_device_bytes")
        parent_device = raw_identity.get("parent_major_minor")
        if (normalize_partuuid(partuuid) != partuuid or
                type(device_bytes) is not int or device_bytes <= 0 or
                not isinstance(parent_device, str) or
                not MAJOR_MINOR_RE.fullmatch(parent_device) or
                any(not isinstance(raw_identity.get(key), str) or
                    not raw_identity[key] for key in
                    ("parent_model", "parent_transport"))):
            return None
        return {
            "physical_partuuid": partuuid,
            "physical_device_bytes": device_bytes,
            "lower_major_minor": raw_lower,
            "parent_major_minor": parent_device,
            "parent_model": raw_identity["parent_model"],
            "parent_transport": raw_identity["parent_transport"],
        }

    raw_identity = raw.get("device_identity") or {}
    swapz_identity = swapz.get("device_identity") or {}
    fields = (
        "physical_partuuid", "physical_device_bytes", "lower_major_minor",
        "parent_major_minor", "parent_model", "parent_transport")
    if any(raw_identity.get(field) != swapz_identity.get(field)
           for field in fields):
        return None
    partuuid = raw_identity.get("physical_partuuid")
    device_bytes = raw_identity.get("physical_device_bytes")
    lower_major_minor = raw_identity.get("lower_major_minor")
    if (normalize_partuuid(partuuid) != partuuid or
            type(device_bytes) is not int or device_bytes <= 0 or
            not isinstance(lower_major_minor, str) or
            not MAJOR_MINOR_RE.fullmatch(lower_major_minor) or
            not isinstance(raw_identity.get("parent_major_minor"), str) or
            not MAJOR_MINOR_RE.fullmatch(raw_identity["parent_major_minor"]) or
            any(not isinstance(raw_identity.get(key), str) or
                not raw_identity[key] for key in
                ("parent_model", "parent_transport"))):
        return None
    return {
        "physical_partuuid": partuuid,
        "physical_device_bytes": device_bytes,
        "lower_major_minor": lower_major_minor,
        "parent_major_minor": raw_identity["parent_major_minor"],
        "parent_model": raw_identity["parent_model"],
        "parent_transport": raw_identity["parent_transport"],
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
         row["lower_major_minor"], row["parent_major_minor"],
         row["parent_model"], row["parent_transport"])
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
        value = _load_json_path(path)
        if isinstance(value, list):
            if any(not isinstance(item, dict) for item in value):
                raise ValueError("qualification report list contains non-object evidence")
            result.extend(value)
        elif isinstance(value, dict):
            result.append(value)
        else:
            raise ValueError("qualification report must be one object or an object list")
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
            raw = _load_json_path(args.raw)
            swapz = _load_json_path(args.swapz)
            if not isinstance(raw, dict) or not isinstance(swapz, dict):
                raise ValueError("qualification pair arms must be JSON objects")
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
