#!/usr/bin/env python3
"""Compare source-pinned SWAPZ RAM qualification runs on three development hosts.

This tool reads snapshots only. It never invokes make, Git, privileged helpers,
physical devices, or changes the qualification result.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys

MANIFEST_SCHEMA = "swapz-optimization-validation-v1"
REPORT_SCHEMA = "swapz-test-results-v1"
HOST_PROFILES = {"x86_64-v2": "x86_64", "x86_64-v4": "x86_64", "aarch64": "aarch64"}
STAGE_NAMES = (
    "Build module and helpers", "Native and rootless contracts",
    "Kernel warnings W=1", "Kernel warnings W=2",
    "Owned RAM smoke + mixed/QD pilot",
)
PAIR_PHASES = ("setup", "fixture", "replay", "verification", "teardown")
MAX_INPUT_BYTES = 16 * 1024 * 1024
SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
HOST_ID_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
MIN_STATISTICAL_PAIRS = 5


class InvalidEvidence(ValueError):
    """A source, host, coverage, workload, or input integrity check failed."""


def require(condition, message):
    if not condition:
        raise InvalidEvidence(message)


def finite_number(value, label, *, nonnegative=True):
    require(isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and (value >= 0 if nonnegative else True),
            f"{label}: invalid finite number")
    return value


def read_json(path, *, maximum=MAX_INPUT_BYTES):
    try:
        with path.open("rb") as stream:
            data = stream.read(maximum + 1)
        require(len(data) <= maximum, f"{path}: input too large")
        return json.loads(data)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InvalidEvidence(f"{path}: cannot read JSON: {error}") from error


def workload_fingerprint(benchmarks):
    """Hash fixture/trace/configuration identity; exclude dynamic measurements."""
    projection = []
    fields = ("regime", "qd", "order", "async_prepare", "device_model",
              "fixture_sha256", "trace_sha256", "retained_burst_target",
              "replay_mode", "cap_mib_s", "envelope", "offered_qd",
              "delta64_rescue")
    for category in ("sessions", "storage_envelope_sessions", "write_saturation_sessions"):
        sessions = benchmarks.get(category)
        require(isinstance(sessions, list) and sessions,
                f"missing benchmark {category}")
        category_rows = []
        for session in sessions:
            require(isinstance(session, dict) and session.get("status") == "PASS",
                    f"{category}: non-PASS benchmark session")
            identity = {key: session[key] for key in fields if key in session}
            for key in ("fixture_sha256", "trace_sha256"):
                if key in identity:
                    require(isinstance(identity[key], str) and
                            HOST_ID_PATTERN.fullmatch(identity[key]) is not None,
                            f"{category}: malformed {key}")
            category_rows.append(identity)
        projection.append((category, category_rows))
    canonical = json.dumps(projection, sort_keys=True, separators=(",", ":"),
                           allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def summarize_report(path, *, source_sha, host_id, architecture):
    report = read_json(path)
    require(isinstance(report, dict) and report.get("schema") == REPORT_SCHEMA,
            f"{path}: unexpected report schema")
    require(report.get("tested_commit_sha") == source_sha and
            report.get("source_sha") == source_sha,
            f"{path}: source SHA differs from pinned experiment source")
    kernel = report.get("kernel_release")
    require(isinstance(kernel, str) and kernel and len(kernel) <= 128,
            f"{path}: kernel release unavailable")
    identity = report.get("host_identity")
    require(isinstance(identity, dict) and identity.get("schema") == "swapz-host-v1"
            and identity.get("id_sha256") == host_id
            and identity.get("architecture") == architecture,
            f"{path}: host identity mismatch")
    require(report.get("overall") in ("PASS", "INCOMPLETE") and
            report.get("qualification") == "RAM_BACKED_NULL_BLK_ONLY",
            f"{path}: failed or wrong-scope qualification")
    stages = report.get("stages")
    require(isinstance(stages, list) and len(stages) == len(STAGE_NAMES),
            f"{path}: five RAM stages required")
    require(all(isinstance(stage, dict) and stage.get("name") == STAGE_NAMES[i]
                and stage.get("status") == "PASS" and stage.get("exit_code") == 0
                for i, stage in enumerate(stages)),
            f"{path}: RAM stage failed, skipped, or changed")
    stage_seconds = [finite_number(stage.get("elapsed_s"), "stage elapsed seconds")
                     for stage in stages]
    rootless_phases = stages[1].get("phase_elapsed_s")
    loaded_phases = stages[4].get("phase_elapsed_s")
    require(isinstance(rootless_phases, list) and len(rootless_phases) == 52 and
            isinstance(loaded_phases, list) and len(loaded_phases) == 25,
            f"{path}: incomplete rootless/loaded phase scope")
    for phase in rootless_phases + loaded_phases:
        require(isinstance(phase, dict) and isinstance(phase.get("name"), str)
                and phase["name"] and len(phase["name"]) <= 160,
                f"{path}: malformed phase label")
        finite_number(phase.get("elapsed_s"), "phase elapsed seconds")
    coverage = stages[1].get("primary_lifecycle_case_timing_coverage")
    cases = stages[1].get("primary_lifecycle_case_elapsed_ms")
    require(isinstance(coverage, dict) and coverage.get("status") == "COMPLETE"
            and coverage.get("expected_cases") == 50
            and coverage.get("accepted_cases") == 50
            and coverage.get("observed_records") == 50
            and isinstance(cases, list) and len(cases) == 50,
            f"{path}: missing lifecycle case timings")
    for case in cases:
        require(isinstance(case, dict) and isinstance(case.get("class"), str)
                and isinstance(case.get("method"), str),
                f"{path}: malformed lifecycle case")
        finite_number(case.get("elapsed_ms"), "lifecycle elapsed milliseconds")
    benchmarks = report.get("benchmarks")
    require(isinstance(benchmarks, dict), f"{path}: missing benchmarks")
    correctness = benchmarks.get("loaded_correctness")
    verdicts = benchmarks.get("verdicts")
    saturation = benchmarks.get("write_saturation")
    require(isinstance(correctness, dict) and correctness.get("overall") == "PASS"
            and isinstance(verdicts, dict) and
            verdicts.get("overall") == "PASS_BOUNDED_RAM_MATRIX"
            and isinstance(saturation, dict) and
            saturation.get("overall") == "PASS_WRITE_SATURATION_EVIDENCE",
            f"{path}: lost loaded/benchmark correctness")
    pair_coverage = benchmarks.get("owned_pair_timing_coverage")
    pairs = benchmarks.get("owned_pair_phase_timings")
    require(isinstance(pair_coverage, dict) and
            pair_coverage.get("status") == "COLLECTED" and
            pair_coverage.get("complete_pairs") == 89 and
            pair_coverage.get("observed_records") == 445 and
            isinstance(pairs, list) and len(pairs) == 89,
            f"{path}: incomplete benchmark phase coverage")
    phase_totals = dict.fromkeys(PAIR_PHASES, 0)
    for index, pair in enumerate(pairs):
        require(isinstance(pair, dict) and pair.get("pair_index") == index,
                f"{path}: reordered benchmark pair")
        times = pair.get("phase_elapsed_ms")
        require(isinstance(times, list) and
                [item.get("phase") for item in times if isinstance(item, dict)]
                == list(PAIR_PHASES), f"{path}: malformed benchmark phases")
        for item in times:
            ms = finite_number(item.get("elapsed_ms"), "pair phase milliseconds")
            phase_totals[item["phase"]] += ms
    fingerprint = workload_fingerprint(benchmarks)
    artifacts = report.get("qualified_artifacts")
    require(isinstance(artifacts, dict) and artifacts.get("status") == "AVAILABLE",
            f"{path}: unavailable qualified artifacts")
    # These are scoped replay observations, NOT whole-make peak RSS/CPU.
    replay_rss = []
    host_busy = []
    host_psi = []
    for category in ("sessions", "write_saturation_sessions"):
        for session in benchmarks[category]:
            require(session.get("source_sha") == source_sha,
                    f"{path}: {category} session source drift")
            for arm in (session.get("arms") or {}).values():
                require(isinstance(arm, dict) and arm.get("source_sha") == source_sha,
                        f"{path}: {category} arm source drift")
            for arm in (session.get("arms") or {}).values():
                if not isinstance(arm, dict):
                    continue
                rss = arm.get("mixed_replay_peak_rss_kb", arm.get("peak_rss_kb"))
                if rss is not None:
                    replay_rss.append(finite_number(rss, "replay RSS"))
                cpu = arm.get("host_cpu")
                if isinstance(cpu, dict) and cpu.get("status") == "AVAILABLE":
                    for field, values in (("busy_fraction", host_busy),
                                          ("pressure_some_fraction", host_psi)):
                        if cpu.get(field) is not None:
                            values.append(finite_number(cpu[field], "host CPU metric"))
    return {
        "kernel_release": kernel,
        "stage_total_s": sum(stage_seconds), "rootless_s": stage_seconds[1],
        "loaded_s": stage_seconds[4],
        "rootless_phase_names": [phase["name"] for phase in rootless_phases],
        "loaded_phase_names": [phase["name"] for phase in loaded_phases],
        "lifecycle_names": [[case["class"], case["method"]] for case in cases],
        "workload_sha256": fingerprint, "pair_phase_ms": phase_totals,
        "replay_peak_rss_kib": max(replay_rss) if replay_rss else None,
        "peak_host_busy_fraction": max(host_busy) if host_busy else None,
        "peak_host_cpu_psi_fraction": max(host_psi) if host_psi else None,
        "id36_memory_peak_bytes": correctness.get("id36_memory_peak_bytes"),
    }


def one_sided_sign_probability(differences):
    positives = sum(item > 0 for item in differences)
    negatives = sum(item < 0 for item in differences)
    trials = positives + negatives
    if not trials:
        return 1.0
    return sum(math.comb(trials, k) for k in range(positives, trials + 1)) / (2 ** trials)


def compare(manifest_path):
    manifest = read_json(manifest_path, maximum=128 * 1024)
    require(isinstance(manifest, dict) and manifest.get("schema") == MANIFEST_SCHEMA,
            "unsupported Phase 5 manifest")
    source = (manifest.get("baseline_sha"), manifest.get("candidate_sha"))
    require(all(isinstance(sha, str) and SHA_PATTERN.fullmatch(sha)
                for sha in source), "pin both complete 40-character source SHAs")
    hosts = manifest.get("hosts")
    require(isinstance(hosts, list) and len(hosts) == 3 and
            {entry.get("profile") for entry in hosts if isinstance(entry, dict)}
            == set(HOST_PROFILES), "require three distinct declared host profiles")
    output = []
    for host in hosts:
        label = host["profile"]
        host_id = host.get("host_id_sha256")
        require(isinstance(host_id, str) and HOST_ID_PATTERN.fullmatch(host_id),
                f"{label}: valid host ID required")
        samples = host.get("pairs")
        require(isinstance(samples, list) and 1 <= len(samples) <= 20,
                f"{label}: provide 1 to 20 paired reports")
        observed = []
        frozen_scope = None
        for index, pair in enumerate(samples):
            require(isinstance(pair, dict) and set(pair) == {"baseline", "candidate"},
                    f"{label} pair {index}: expected baseline and candidate paths")
            entries = []
            for arm, source_sha in zip(("baseline", "candidate"), source):
                relative_path = pair[arm]
                require(isinstance(relative_path, str) and relative_path,
                        f"{label} pair {index}: missing {arm} path")
                path = (manifest_path.parent / relative_path).resolve()
                entries.append(summarize_report(
                    path, source_sha=source_sha, host_id=host_id,
                    architecture=HOST_PROFILES[label]))
            left, right = entries
            for summary in entries:
                scope = (summary["kernel_release"],
                         summary["rootless_phase_names"],
                         summary["loaded_phase_names"],
                         summary["lifecycle_names"], summary["workload_sha256"])
                if frozen_scope is None:
                    frozen_scope = scope
                require(scope == frozen_scope,
                        f"{label} pair {index}: test scope or workload changed")
            observed.append((left, right))
        improvements = [before["stage_total_s"] - after["stage_total_s"]
                        for before, after in observed]
        baselines = [before["stage_total_s"] for before, _ in observed]
        candidates = [after["stage_total_s"] for _, after in observed]
        probability = one_sided_sign_probability(improvements)
        phase_changes = {}
        for stage in ("rootless_s", "loaded_s"):
            phase_changes[stage] = {
                "baseline_median_s": statistics.median(a[stage] for a, _ in observed),
                "candidate_median_s": statistics.median(b[stage] for _, b in observed),
            }
        phase_changes["pair_phases"] = {
            phase: {"baseline_median_ms": statistics.median(
                        before["pair_phase_ms"][phase] for before, _ in observed),
                    "candidate_median_ms": statistics.median(
                        after["pair_phase_ms"][phase] for _, after in observed)}
            for phase in PAIR_PHASES
        }
        resources = {}
        for key in ("replay_peak_rss_kib", "peak_host_busy_fraction",
                    "peak_host_cpu_psi_fraction", "id36_memory_peak_bytes"):
            values = [[item[key] for item in pair] for pair in observed]
            resources[key] = (None if any(value is None for pair in values for value in pair)
                              else {"baseline_median": statistics.median(pair[0] for pair in values),
                                    "candidate_median": statistics.median(pair[1] for pair in values)})
        output.append({
            "profile": label, "host_id_sha256": host_id, "paired_runs": len(observed),
            "baseline_median_ram_stage_s": statistics.median(baselines),
            "candidate_median_ram_stage_s": statistics.median(candidates),
            "paired_median_saved_s": statistics.median(improvements),
            "one_sided_sign_p": probability,
            "statistical_status": (
                "INSUFFICIENT_REPEATS" if len(observed) < MIN_STATISTICAL_PAIRS
                else "EVIDENCE_OF_REDUCTION" if probability <= 0.05 and
                statistics.median(improvements) > 0 else "NOT_DEMONSTRATED"),
            "phase_comparison": phase_changes,
            "observed_resource_diagnostics": resources,
        })
    statuses = [host["statistical_status"] for host in output]
    status = ("CONSISTENT_REDUCTION_SIGNAL" if all(
        s == "EVIDENCE_OF_REDUCTION" for s in statuses) else
        "INSUFFICIENT_REPEATS" if "INSUFFICIENT_REPEATS" in statuses else
        "REDUCTION_NOT_DEMONSTRATED")
    return {"schema": MANIFEST_SCHEMA, "status": status,
            "baseline_sha": source[0], "candidate_sha": source[1],
            "scope": "FIVE_RAM_STAGE_SUM_NOT_FULL_MAKE_TEST_OR_PHYSICAL_QUALIFICATION",
            "statistical_method": "exact_one_sided_paired_sign_test_per_host_p_le_0.05",
            "caveat": "Host load, repeat order and resource contention require owner review; "
                      "replay RSS/CPU diagnostics are not whole-test process maxima.",
            "hosts": output}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True,
                        help="Three-host source-pinned paired report manifest")
    parser.add_argument("--output", type=Path,
                        help="Optional new output JSON; input reports are never modified")
    args = parser.parse_args(argv)
    try:
        result = compare(args.manifest.resolve())
        serialized = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output:
            output = args.output.resolve()
            require(output != args.manifest.resolve(), "refusing to overwrite manifest")
            require(not output.exists(), "refusing to overwrite existing output")
            output.write_text(serialized, encoding="utf-8")
        print(serialized, end="")
        return 0 if result["status"] == "CONSISTENT_REDUCTION_SIGNAL" else 2
    except InvalidEvidence as error:
        print(f"INVALID_PHASE5_EVIDENCE: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())