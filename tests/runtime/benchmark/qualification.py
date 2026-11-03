#!/usr/bin/env python3
"""Prospective dedicated-SD performance contract and result evaluator.

Private benchmark helper. It schedules no physical I/O and does not replace the
project's single supported test interface.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path

SCHEMA = "swapz-performance-qualification-v1"
PAIR_SCHEMA = "swapz-performance-pair-v1"
SUMMARY_SCHEMA = "swapz-performance-summary-v1"
T95_DF4 = 2.7764451051977987

CONTRACT = {
    "schema": SCHEMA,
    "prospective": True,
    "claim_boundary": (
        "lower-device bytes and requests are host-visible physical I/O; "
        "they are not direct NAND-wear or endurance measurements"
    ),
    "resource_measurement": {
        "replay_peak_rss_bytes": "absolute process ru_maxrss through measured completion",
        "replay_process_maxrss_bytes": "same absolute peak retained for schema clarity",
        "replay_measurement_start_maxrss_bytes": "absolute ru_maxrss at the measured boundary",
        "replay_measurement_peak_rss_growth_bytes": "diagnostic measured-boundary growth only",
    },
    "screening": {
        "pre_post_busy_fraction_max": .25,
        "pre_post_cpu_psi_some_fraction_max": .05,
        "steal_fraction_max": .01,
        "same_workload_raw_spread_max": .10,
        "retry_policy": "none; preserve failed/excluded samples and reasons",
    },
    "workloads": {
        "sd-service-balanced": {
            "evidence": "statistical_paired", "pairs": 5,
            "counterbalanced_order": ["raw-first", "swapz-first", "swapz-first", "raw-first", "raw-first"],
            "fill_content_profile": "balanced", "churn_content_profile": "balanced",
            "warmup_operations": 65536, "measure_operations": 1048576,
            "qd": 8, "read_percent": 20,
            "logical_occupancy_percent": 10, "hot_region_percent": 8,
            "arm_timeout_seconds": 1800,
        },
        "sd-service-representative": {
            "evidence": "statistical_paired", "pairs": 5,
            "counterbalanced_order": ["raw-first", "swapz-first", "swapz-first", "raw-first", "raw-first"],
            "fill_content_profile": "representative", "churn_content_profile": "representative",
            "warmup_operations": 65536, "measure_operations": 1048576,
            "qd": 8, "read_percent": 20,
            "logical_occupancy_percent": 10, "hot_region_percent": 8,
            "arm_timeout_seconds": 1800,
        },
        "sd-high-occupancy-churn": {
            "evidence": "directional_single_pair", "pairs": 1,
            "counterbalanced_order": ["raw-first"],
            "fill_content_profile": "entropy", "churn_content_profile": "balanced",
            "warmup_seconds": 60, "measure_seconds": 3600,
            "qd": 16, "read_percent": 20,
            "logical_occupancy_percent": 90, "hot_region_percent": 80,
            "arm_timeout_seconds": 14400,
        },
        "anonymous-swap": {
            "evidence": "directional_three_pair", "pairs": 3,
            "counterbalanced_order": ["raw-first", "swapz-first", "raw-first"],
            "content": "50% deterministic compressible + 50% deterministic entropy anonymous pages",
            "rounds": 3, "minimum_observed_swap_bytes": 134217728,
            "arm_timeout_seconds": 1800,
        },
    },
    "acceptance": {
        "service": {
            "useful_write_ci_lower_min": .05,
            "lower_write_bytes_ci_upper_max": -.10,
            "lower_write_requests_ci_upper_max": -.10,
            "tail_ci_upper_max": .25,
            "cpu_ci_upper_max": .50,
        },
        "sustained": {
            "useful_write_ratio_min": 1.05,
            "lower_write_bytes_ratio_max": .90,
            "lower_write_requests_ratio_max": .90,
            "tail_ratio_max": 1.25,
            "throughput_drift_ratio_min": .75,
            "p99_drift_ratio_max": 1.25,
            "gc_wall_fraction_max": .20,
            "gc_no_headroom_skips_max": 0,
            "replay_peak_rss_bytes_max": 134217728,
            "metadata_and_target_peak_ram_bytes_max": 1342177280,
            "max_no_progress_seconds": 10.0,
        },
        "anonymous": {
            "minimum_observed_swap_bytes": 134217728,
            "swapin_tail_ratio_max": 1.25,
            "useful_read_ratio_min": .80,
            "lower_write_bytes_ratio_max": .90,
            "lower_write_requests_ratio_max": .90,
            "cpu_ratio_max": 1.50,
        },
    },
    "raw_comparison": {
        "raw_offset_bytes": 4096,
        "work": "same card, source, content recipe, logical geometry and fixed work or duration",
        "accounting": "parent-device block statistics bracket only measured intervals",
    },
}


def contract() -> dict:
    return json.loads(json.dumps(CONTRACT))


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


def validate_arm(arm: dict, workload: str, label: str) -> list[str]:
    spec = CONTRACT["workloads"][workload]
    reasons = []
    if workload == "anonymous-swap":
        for field, expected in (("round_count", spec["rounds"]),
                                ("required_swap_bytes", spec["minimum_observed_swap_bytes"]),
                                ("content", spec["content"])):
            if arm.get(field) != expected:
                reasons.append(f"{label} {field} differs from prospective workload")
        if not isinstance(arm.get("swap_device_identity"), dict):
            reasons.append(f"{label} admitted swap-device identity is missing")
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
    if not identity.get("physical_partuuid") or not identity.get("physical_device_bytes"):
        reasons.append(f"{label} physical identity is missing")
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
    return reasons


def compare_pair(raw: dict, swapz: dict, workload: str, pair_id: str,
                 pair_index: int, order: str, extra_reasons=None) -> dict:
    if workload not in CONTRACT["workloads"]:
        raise ValueError("unknown qualification workload")
    if raw.get("candidate") != "raw" or swapz.get("candidate") != "swapz":
        raise ValueError("pair requires one raw and one swapz arm")
    spec = CONTRACT["workloads"][workload]
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
    for label, arm in (("raw", raw), ("swapz", swapz)):
        if arm.get("verdict") != "PASS":
            reasons.append(f"{label} arm verdict is not PASS")
        if (arm.get("oracle") or {}).get("mismatches") != 0:
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
        "status": "PASS" if not reasons else "EXCLUDED", "excluded": bool(reasons),
        "exclusion_reasons": reasons, "deltas": deltas, "raw": raw, "swapz": swapz,
    }


def quartile_ratio(rows: list[dict], field: str) -> float:
    values = [number(row.get(field), field) for row in rows]
    if len(values) < 4 or any(value <= 0 for value in values):
        raise ValueError("sustained drift needs at least four positive minute buckets")
    count = max(1, len(values) // 4)
    return statistics.fmean(values[-count:]) / statistics.fmean(values[:count])


def service_decision(pairs: list[dict]) -> dict:
    names = ("useful_write", "lower_write_bytes", "lower_write_requests",
             "read_p95", "read_p99", "write_p95", "write_p99", "cpu")
    cis = {name: paired_ci95([pair["deltas"][name] for pair in pairs]) for name in names}
    limit = CONTRACT["acceptance"]["service"]
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
        "gc_headroom": int(gc.get("no_headroom_skips", -1)) <= 0,
        "gc_relocation": int(gc.get("gc_victims", 0)) > 0 and int(gc.get("gc_pages", 0)) > 0,
        "segment_programming": int(gc.get("segment_program_sum", 0)) > 0,
        "target_not_failed": int(gc.get("failed", -1)) == 0 and int(gc.get("error", 0)) == 0,
        "forward_progress": number(swapz.get("max_no_progress_seconds"), "max_no_progress_seconds") <= limit["max_no_progress_seconds"],
        "replay_rss": int(resources.get("replay_peak_rss_bytes", -1)) <= limit["replay_peak_rss_bytes_max"],
        "target_ram": int(resources.get("metadata_and_target_peak_ram_bytes", -1)) <= limit["metadata_and_target_peak_ram_bytes_max"],
        "oracle": (swapz.get("oracle") or {}).get("mismatches") == 0,
        "cold_read": int((swapz.get("cold_read") or {}).get("pages", 0)) > 0,
        "high_occupancy": int(swapz.get("occupancy_percent", 0)) >= 90,
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
            pair_ok &= int(arm.get("observed_swap_bytes", 0)) >= limit["minimum_observed_swap_bytes"]
            pair_ok &= (arm.get("oracle") or {}).get("mismatches") == 0
        rows.append({"pair_id": pair["pair_id"], "status": "PASS" if pair_ok else "FAIL", "ratios": ratios})
        ok &= pair_ok
    return {"status": "PASS" if ok else "FAIL", "evidence": "directional_three_pair", "pairs": rows}


def evaluate(records: list[dict]) -> dict:
    preserved = []
    for pair in records:
        if pair.get("schema") != PAIR_SCHEMA or pair.get("workload") not in CONTRACT["workloads"]:
            raise ValueError("invalid qualification pair")
        saved = dict(pair)
        saved["analysis_usable"] = pair.get("status") == "PASS" and not pair.get("excluded")
        saved["analysis_exclusion_reasons"] = list(pair.get("exclusion_reasons") or [])
        preserved.append(saved)

    raw_spread = {}
    for name, spec in CONTRACT["workloads"].items():
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
    for name, spec in CONTRACT["workloads"].items():
        rows = [row for row in preserved if row["workload"] == name and row["analysis_usable"]]
        required = spec["pairs"]
        order_ok = (sorted(row.get("pair_index") for row in rows) == list(range(1, required + 1)) and
                    all(row.get("order") == spec["counterbalanced_order"][row["pair_index"] - 1] for row in rows))
        if len(rows) != required or not order_ok:
            decision = {"status": "INCOMPLETE", "accepted_pairs": len(rows),
                        "required_pairs": required, "prospective_order_complete": order_ok,
                        "raw_repeat_spread": raw_spread.get(name)}
        elif spec["evidence"] == "statistical_paired":
            decision = service_decision(rows)
        elif name == "sd-high-occupancy-churn":
            decision = sustained_decision(rows[0])
        else:
            decision = anonymous_decision(rows)
        decisions[name] = decision
        overall &= decision["status"] == "PASS"
    return {"schema": SUMMARY_SCHEMA, "contract": contract(),
            "status": "PASS" if overall else "FAIL_OR_INCOMPLETE",
            "decisions": decisions, "raw_repeat_spread": raw_spread, "records": preserved}


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
    pair = sub.add_parser("pair")
    pair.add_argument("--raw", required=True); pair.add_argument("--swapz", required=True)
    pair.add_argument("--workload", required=True); pair.add_argument("--pair-id", required=True)
    pair.add_argument("--pair-index", type=int, required=True)
    pair.add_argument("--order", choices=("raw-first", "swapz-first"), required=True)
    pair.add_argument("--exclude", action="append", default=[]); pair.add_argument("--result", required=True)
    summary = sub.add_parser("evaluate"); summary.add_argument("reports", nargs="+")
    args = parser.parse_args()
    try:
        if args.command == "contract":
            print(json.dumps(contract(), sort_keys=True))
        elif args.command == "pair":
            raw = json.loads(Path(args.raw).read_text()); swapz = json.loads(Path(args.swapz).read_text())
            record = compare_pair(raw, swapz, args.workload, args.pair_id,
                                  args.pair_index, args.order, args.exclude)
            target = Path(args.result)
            if target.exists(): raise ValueError("refusing to overwrite qualification pair")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
            print(json.dumps(record, sort_keys=True))
        else:
            print(json.dumps(evaluate(load_records(args.reports)), sort_keys=True))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, "BLOCKED/FAIL: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
