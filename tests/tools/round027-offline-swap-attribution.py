#!/usr/bin/env python3
"""Round027 rootless, READ-ONLY offline physical swap attribution triage.

Never probes /proc, sysfs, cgroups, kernel, swap or devices. Only a strictly
named, bounded local JSON input and the committed original evaluator source
are read. A coherent synthetic fixture is NOT a physical success.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

SOURCE = Path(__file__).resolve().with_name("qualify-primary-real-swap.py")
SCHEMA = "swapz-round027-offline-swap-attribution-v1"
UNKNOWN = "UNKNOWN_MISSING_EVIDENCE"
FAIL = "FAIL_WITH_EVIDENCE"
SYNTHETIC = "SYNTHETIC_SOURCE_CONSISTENT_NOT_PHYSICAL_PASS"
MAX_BYTES = 128 * 1024
MAX_UINT = (1 << 64) - 1
PAGE_BYTES = 4096
SECTOR_BYTES = 512
MIN_SWAP_BYTES = 128 * 1024 * 1024
RECHECK_WINDOW_USEC = 3_000_000
PHASES = ("baseline", "after_fill", "before_verify", "after_verify")
SOURCE_ARGUMENTS = (
    "cgroup_swap_bytes", "cgroup_swap_peak", "min_swap_bytes",
    "expected_verified_pages", "oom_delta", "oom_kill_delta",
    "mapper_used_delta_kib", "fill_status_before", "fill_status_after",
    "verify_status_before", "verify_status_after", "lower_before",
    "lower_after_fill", "lower_before_verify", "lower_after_verify",
    "vm_before", "vm_after_fill", "vm_before_verify", "vm_after_verify",
    "oracle",
)
STATUS_KEYS = ("logical_write", "physical_write", "logical_read",
               "physical_read", "failed", "error")
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
SOURCE_SHA = re.compile(r"[0-9a-f]{40}\Z")
HEX_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
INPUT_FILE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}\.json\Z")
CATEGORIES = (
    "cgroup_swap_below_floor",
    "cgroup_oom",
    "mapper_swap_below_floor",
    "target_write_below_floor",
    "lower_write_absent",
    "lower_write_insufficient",
    "vmstat_swapout_absent",
    "target_read_below_floor",
    "lower_read_absent",
    "lower_read_insufficient",
    "vmstat_swapin_absent",
    "original_page_oracle_mismatch",
    "target_failed",
)


class InvalidEvidence(ValueError):
    """Bounded code-only reason; never leak owner identity or arbitrary JSON."""


class OriginalQualificationFailure(RuntimeError):
    """Exact committed production evaluator threw on an offline snapshot."""


@dataclass(frozen=True)
class BlockStats:
    read_sectors: int
    write_sectors: int


@dataclass(frozen=True)
class Verdict:
    classification: str
    first_error: str
    evidence_class: str


def require(value: bool, category: str) -> None:
    if not value:
        raise InvalidEvidence(category)


def unsigned(value: object, category: str) -> int:
    require(type(value) is int and 0 <= value <= MAX_UINT, category)
    return value


def fields(record: object, names: set[str], category: str) -> dict:
    require(type(record) is dict and set(record) == names, category)
    return record


def read_json(root: Path, filename: str) -> object:
    """Use dirfd + O_NOFOLLOW: symlinks/../non-regular evidence are forbidden."""
    require(INPUT_FILE.fullmatch(filename) is not None, "input_filename")
    require(root.is_absolute() and not root.is_symlink() and
            root.resolve() == root and root.is_dir() and
            not any(part in ("proc", "sys", "dev") for part in root.parts),
            "input_directory")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        directory_fd = os.open(root, directory_flags)
        try:
            file_fd = os.open(filename, file_flags, dir_fd=directory_fd)
            try:
                info = os.fstat(file_fd)
                require(stat.S_ISREG(info.st_mode) and
                        0 < info.st_size <= MAX_BYTES, "input_size_or_type")
                with os.fdopen(file_fd, "rb", closefd=False) as evidence_file:
                    contents = evidence_file.read(MAX_BYTES + 1)
                require(len(contents) == info.st_size, "input_changed")
            finally:
                os.close(file_fd)
        finally:
            os.close(directory_fd)
    except OSError as error:
        raise InvalidEvidence("input_unavailable_or_unsafe") from error

    def no_duplicate(pairs: list[tuple[str, object]]) -> dict:
        result: dict = {}
        for name, value in pairs:
            require(name not in result, "duplicate_json_key")
            result[name] = value
        return result

    def no_nonfinite(_: str) -> object:
        raise InvalidEvidence("nonfinite_json_number")

    try:
        return json.loads(contents, object_pairs_hook=no_duplicate,
                          parse_constant=no_nonfinite)
    except (UnicodeError, ValueError) as error:
        if isinstance(error, InvalidEvidence):
            raise
        raise InvalidEvidence("malformed_json") from error


def load_original_evaluator():
    """Compile ONLY the real original source function, not an imitation.

    Its trusted C/Python thresholds, check order, 512-byte sectors and 4096-byte
    byte-oracle predicates are preserved verbatim; no live caller is imported.
    """
    source_text = SOURCE.read_text(encoding="utf-8")
    original = ast.parse(source_text, filename=SOURCE.name)
    functions = [node for node in original.body
                 if isinstance(node, ast.FunctionDef) and
                 node.name == "evaluate_workload_evidence"]
    require(len(functions) == 1, "original_evaluator_missing")
    function = functions[0]
    require(tuple(arg.arg for arg in function.args.kwonlyargs) ==
            SOURCE_ARGUMENTS, "original_evaluator_signature")
    source_function = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(source_function)
    namespace = {
        "__builtins__": {"dict": dict, "int": int, "str": str,
                         "isinstance": isinstance},
        "QualificationFailure": OriginalQualificationFailure,
        "BlockStats": BlockStats, "PAGE_BYTES": PAGE_BYTES,
        "SECTOR_BYTES": SECTOR_BYTES, "re": re,
    }
    exec(compile(source_function, SOURCE.name, "exec"), namespace)
    return namespace["evaluate_workload_evidence"]


def normalize_snapshot(snapshot: object, expected_identity: dict) -> dict:
    names = {"phase", "monotonic_us", "source_sha", "boot_key",
             "mapper_key", "lower_key", "cgroup_key", "cgroup",
             "mapper", "target", "lower", "vm"}
    entry = fields(snapshot, names, "snapshot_fields")
    for key in ("source_sha", "boot_key", "mapper_key",
                "lower_key", "cgroup_key"):
        require(entry[key] == expected_identity[key], "snapshot_identity_mismatch")
    normalized = dict(entry)
    normalized["monotonic_us"] = unsigned(entry["monotonic_us"],
                                          "snapshot_monotonic")
    cgroup = fields(entry["cgroup"],
                    {"swap_current", "swap_peak", "swap_max", "oom", "oom_kill"},
                    "cgroup_fields")
    mapper = fields(entry["mapper"], {"active", "used_kib"}, "mapper_fields")
    target = fields(entry["target"], set(STATUS_KEYS), "target_fields")
    lower = fields(entry["lower"], {"read_sectors", "write_sectors"},
                   "lower_fields")
    vm = fields(entry["vm"], {"pswpin", "pswpout"}, "vm_fields")
    require(mapper["active"] is True, "mapper_inactive")
    for section, names in ((cgroup, cgroup), (mapper, {"used_kib": 0}),
                           (target, target), (lower, lower), (vm, vm)):
        for name in names:
            unsigned(section[name], "invalid_counter")
    require(cgroup["swap_peak"] >= cgroup["swap_current"] and
            cgroup["swap_max"] >= cgroup["swap_peak"],
            "cgroup_peak_limit")
    return normalized


def checked_delta(new: int, old: int, category: str) -> int:
    require(new >= old, category)
    return new - old


def counter_monotonic(previous: dict, current: dict) -> None:
    for group, names in (("target", STATUS_KEYS), ("lower",
                         ("read_sectors", "write_sectors")),
                         ("vm", ("pswpin", "pswpout")),
                         ("cgroup", ("oom", "oom_kill"))):
        for key in names:
            checked_delta(current[group][key], previous[group][key],
                          "counter_regression")


def attribution(fill: dict, baseline: dict, rechecks: list[dict],
                recheck_complete: bool, verify_start_us: int,
                identity: dict) -> tuple[int, int] | Verdict:
    base_used = baseline["mapper"]["used_kib"]
    first_used = fill["mapper"]["used_kib"]
    require(first_used >= base_used, "mapper_below_baseline")
    used_delta_kib = first_used - base_used
    require(used_delta_kib <= MAX_UINT // 1024, "mapper_byte_overflow")
    first_swap = fill["cgroup"]["swap_current"]
    if used_delta_kib * 1024 == first_swap:
        require(not rechecks, "unexpected_recheck")
        return first_swap, used_delta_kib
    if not recheck_complete:
        return Verdict(UNKNOWN, "attribution_recheck_missing", identity["class"])
    previous_pair: tuple[int, int] | None = None
    previous = fill
    for raw_sample in rechecks:
        sample = normalize_snapshot(raw_sample, identity)
        require(sample["phase"] == "attribution_recheck", "recheck_phase")
        elapsed = checked_delta(sample["monotonic_us"],
                                fill["monotonic_us"], "recheck_order")
        require(0 < elapsed < RECHECK_WINDOW_USEC and
                sample["monotonic_us"] < verify_start_us,
                "recheck_deadline")
        require(sample["monotonic_us"] > previous["monotonic_us"],
                "recheck_nonmonotonic")
        counter_monotonic(previous, sample)
        require(sample["mapper"]["used_kib"] >= base_used, "mapper_below_baseline")
        new_delta = sample["mapper"]["used_kib"] - base_used
        require(new_delta <= MAX_UINT // 1024, "mapper_byte_overflow")
        pair = (sample["cgroup"]["swap_current"], sample["mapper"]["used_kib"])
        if new_delta * 1024 == pair[0]:
            if pair == previous_pair:
                return pair[0], new_delta
            previous_pair = pair
        else:
            previous_pair = None
        previous = sample
    if not rechecks:
        return Verdict(UNKNOWN, "attribution_recheck_missing", identity["class"])
    final_delta = previous["mapper"]["used_kib"] - base_used
    gap = final_delta * 1024 - previous["cgroup"]["swap_current"]
    first_delta = used_delta_kib * 1024 - first_swap
    category = ("unconfirmed_matching_pair" if gap == 0 else
                "sign_changed" if first_delta * gap < 0 else
                "mapper_excess" if gap > 0 else "cgroup_excess")
    return Verdict(FAIL, "swap_attribution_" + category, identity["class"])


def analyze(document: object, expected_source_sha: str) -> Verdict:
    """Return no physical PASS. Do not print or retain any private IDs."""
    require(SOURCE_SHA.fullmatch(expected_source_sha) is not None,
            "expected_source_sha")
    if type(document) is not dict or not document:
        return Verdict(UNKNOWN, "historical_counters_missing", "UNKNOWN")
    necessary = {"schema", "evidence_class", "source_sha", "boot_key",
                 "mapper_key", "lower_key", "cgroup_key",
                 "min_swap_bytes", "expected_verified_pages", "ownership",
                 "snapshots", "attribution_rechecks", "recheck_complete",
                 "oracle"}
    # Incomplete owner's historical report is UNKNOWN, never a failure claim.
    if not necessary.issubset(document):
        return Verdict(UNKNOWN, "historical_counters_missing", "UNKNOWN")
    fields(document, necessary, "unexpected_evidence_field")
    require(document["schema"] == SCHEMA and
            document["evidence_class"] in
            ("SYNTHETIC_TEST_ONLY", "OWNER_REDACTED_OFFLINE"),
            "evidence_schema")
    source_sha = document["source_sha"]
    require(type(source_sha) is str and
            SOURCE_SHA.fullmatch(source_sha) is not None and
            source_sha == expected_source_sha, "source_sha_mismatch")
    identity = {"class": document["evidence_class"],
                "source_sha": source_sha}
    for name in ("boot_key", "mapper_key", "lower_key", "cgroup_key"):
        value = document[name]
        require(type(value) is str and TOKEN.fullmatch(value) is not None,
                "unredacted_or_invalid_identity")
        identity[name] = value
    owner = fields(document["ownership"],
                   {"source_loaded_matches", "boot_matches",
                    "mapper_matches", "lower_matches", "cgroup_unique",
                    "worker_identity", "cleanup_completed",
                    "oracle_exit_zero"}, "ownership_fields")
    require(all(value is True for value in owner.values()),
            "owner_or_cleanup_not_proven")
    require(unsigned(document["min_swap_bytes"], "swap_floor") ==
            MIN_SWAP_BYTES, "source_swap_floor")
    pages = unsigned(document["expected_verified_pages"], "page_count")
    require(0 < pages <= 512 * 1024 * 1024 // PAGE_BYTES,
            "page_count_bounds")
    originals = document["snapshots"]
    require(type(originals) is list and len(originals) == 4, "snapshot_count")
    snapshots = [normalize_snapshot(item, identity) for item in originals]
    require(tuple(item["phase"] for item in snapshots) == PHASES,
            "snapshot_order")
    require(all(snapshots[index + 1]["monotonic_us"] >
                snapshots[index]["monotonic_us"] for index in range(3)),
            "snapshot_time_order")
    for earlier, later in zip(snapshots, snapshots[1:]):
        counter_monotonic(earlier, later)
    baseline, fill, before_verify, after_verify = snapshots
    require(type(document["recheck_complete"]) is bool, "recheck_complete")
    rechecks = document["attribution_rechecks"]
    require(type(rechecks) is list and len(rechecks) <= 60, "recheck_count")
    result = attribution(fill, baseline, rechecks,
                         document["recheck_complete"],
                         before_verify["monotonic_us"], identity)
    if isinstance(result, Verdict):
        return result
    cgroup_bytes, mapper_delta = result
    require(fill["cgroup"]["swap_peak"] >= cgroup_bytes,
            "cgroup_peak_limit")
    # 512-byte kernel sectors are NOT 4096-byte device physical blocks.
    for group_a, group_b, key in (("lower", "lower", "write_sectors"),
                                 ("lower", "lower", "read_sectors")):
        for entry in (baseline, fill, before_verify, after_verify):
            require(entry[group_a][key] <= MAX_UINT // SECTOR_BYTES,
                    "lower_sector_byte_overflow")
    for entry in snapshots:
        require(entry["mapper"]["used_kib"] <= MAX_UINT // 1024,
                "mapper_byte_overflow")
    oracle = fields(document["oracle"],
                    {"verified_pages", "verified_bytes", "mismatches",
                     "digest", "expected_digest", "full_page_bytes"},
                    "oracle_fields")
    for name in ("verified_pages", "verified_bytes", "mismatches",
                 "full_page_bytes"):
        unsigned(oracle[name], "oracle_number")
    require(oracle["full_page_bytes"] == PAGE_BYTES,
            "original_page_size")
    for name in ("digest", "expected_digest"):
        require(type(oracle[name]) is str and
                HEX_DIGEST.fullmatch(oracle[name]) is not None,
                "oracle_digest")
    values = {
        "cgroup_swap_bytes": cgroup_bytes,
        "cgroup_swap_peak": fill["cgroup"]["swap_peak"],
        "min_swap_bytes": MIN_SWAP_BYTES,
        "expected_verified_pages": pages,
        "oom_delta": checked_delta(after_verify["cgroup"]["oom"],
                                   baseline["cgroup"]["oom"], "oom_regression"),
        "oom_kill_delta": checked_delta(
            after_verify["cgroup"]["oom_kill"], baseline["cgroup"]["oom_kill"],
            "oom_regression"),
        "mapper_used_delta_kib": mapper_delta,
        "fill_status_before": baseline["target"],
        "fill_status_after": fill["target"],
        "verify_status_before": before_verify["target"],
        "verify_status_after": after_verify["target"],
        "lower_before": BlockStats(**baseline["lower"]),
        "lower_after_fill": BlockStats(**fill["lower"]),
        "lower_before_verify": BlockStats(**before_verify["lower"]),
        "lower_after_verify": BlockStats(**after_verify["lower"]),
        "vm_before": baseline["vm"],
        "vm_after_fill": fill["vm"],
        "vm_before_verify": before_verify["vm"],
        "vm_after_verify": after_verify["vm"],
        "oracle": {key: oracle[key] for key in
                   ("verified_pages", "verified_bytes", "mismatches",
                    "digest", "expected_digest")},
    }
    try:
        load_original_evaluator()(**values)
    except OriginalQualificationFailure as error:
        original_message = str(error)
        # The source function's own error ordering is authoritative;
        # never interpolate owner private counters into public messages.
        source_messages = {
            "bounded cgroup never accumulated required real swap usage":
                CATEGORIES[0],
            "bounded real-swap workload encountered cgroup OOM": CATEGORIES[1],
            "exact mapper /proc/swaps usage stayed below required real-swap floor":
                CATEGORIES[2],
            "swapz target counters stay below required swap-out WRITE activity":
                CATEGORIES[3],
            "backing partition counters show no lower WRITE activity":
                CATEGORIES[4],
            "backing partition WRITE counters do not cover swapz target physical WRITE bytes":
                CATEGORIES[5],
            "kernel vmstat shows no swap-out during admitted workload":
                CATEGORIES[6],
            "swapz target counters stay below required swap-in READ activity":
                CATEGORIES[7],
            "backing partition counters show no lower READ activity":
                CATEGORIES[8],
            "backing partition READ counters do not cover swapz target physical READ bytes":
                CATEGORIES[9],
            "kernel vmstat shows no swap-in during byte verification":
                CATEGORIES[10],
            "real-swap byte oracle reported corruption or incomplete verification":
                CATEGORIES[11],
            "swapz target entered failed state during real-swap workload":
                CATEGORIES[12],
        }
        return Verdict(FAIL, source_messages.get(
            original_message, "original_evaluator_refused"), identity["class"])
    if document["evidence_class"] != "SYNTHETIC_TEST_ONLY":
        return Verdict(UNKNOWN, "owner_report_not_live_authenticated",
                       document["evidence_class"])
    return Verdict(SYNTHETIC, "none", document["evidence_class"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--file", required=True,
                        help="one safe basename, not an absolute path")
    parser.add_argument("--expected-source-sha", required=True)
    arguments = parser.parse_args()
    try:
        evidence = read_json(arguments.evidence_root, arguments.file)
        verdict = analyze(evidence, arguments.expected_source_sha)
    except (OSError, InvalidEvidence, SyntaxError) as error:
        category = str(error) if isinstance(error, InvalidEvidence) else "source_unavailable"
        print("ROUND027_OFFLINE_INVALID first_error=" + category)
        print("PHYSICAL=NOT_RUN LOADED=NOT_RUN DIRECT_COMPRESSED=DISABLED")
        return 2
    print("ROUND027_OFFLINE_CLASSIFICATION=" + verdict.classification)
    print("FIRST_ERROR=" + verdict.first_error)
    print("EVIDENCE_CLASS=" + verdict.evidence_class)
    print("PHYSICAL=NOT_RUN LOADED=NOT_RUN PHASE_A=BLOCKED "
          "FORCED_RAW_BYPASS=DISABLED DIRECT_COMPRESSED=DISABLED")
    return 0 if verdict.classification == SYNTHETIC else 1


if __name__ == "__main__":
    raise SystemExit(main())
