#!/usr/bin/env python3
"""Normalize preserved PR #57 loaded benchmark records into CSV/JSON summaries.

This tool does not run tests. It accepts only trials whose runner returned zero,
target status stayed healthy, the helper reported no errors/mismatches, and its
separate full-image verification passed.
"""

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path


MATRIX_FILES = (
    "sustained-matrix.jsonl",
    "qdepth-matrix.jsonl",
    "mix-ratio-matrix.jsonl",
    "rate-matrix.jsonl",
    "uniform-class-matrix.jsonl",
    "coalesce-matrix.jsonl",
)


def maybe_json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


def load_rows(root):
    trials = []
    rejected = []
    for filename in MATRIX_FILES:
        path = root / filename
        if not path.exists():
            continue
        for line_no, line in enumerate(path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            source = json.loads(line)
            out = maybe_json(source.get("output"))
            measure = maybe_json(out.get("measure"))
            lower = maybe_json(out.get("lower_delta"))
            verify = maybe_json(out.get("verification"))
            label = out.get("label", "")
            trial_path = root / "trials" / label / "trial.json" if label else None
            detail = {}
            if trial_path and trial_path.exists():
                try:
                    detail = json.loads(trial_path.read_text())
                except (OSError, json.JSONDecodeError):
                    detail = {}
            profile = detail.get("profile", {})
            target = detail.get("target_counter_deltas", {})
            status_fields = detail.get("target_status_fields_after_measurement", {})
            # Several V2.2 status keys do not exist at all; the common parser
            # fills their deltas with zero. Preserve absence instead of
            # presenting those synthetic zeros as measured counters.
            if status_fields:
                for key in tuple(target):
                    if key not in status_fields:
                        target[key] = None
            valid = (
                source.get("rc") == 0
                and out.get("phase") == "PASS"
                and str(out.get("target_failed", "0")) == "0"
                and measure.get("errors") == 0
                and measure.get("mismatches") == 0
                and verify.get("result") == "PASS"
                and verify.get("pages") == 4096
            )
            class_name = source.get("class", "")
            row = {
                "matrix": filename,
                "label": label,
                "candidate": source.get("candidate", ""),
                "class": class_name,
                "qd": source.get("qd", measure.get("qd", profile.get("qd", ""))),
                "read_pct": source.get("read_pct", measure.get("read_pct", profile.get("read_pct", ""))),
                "coalesce_ms": source.get("coalesce_ms", profile.get("coalesce_ms", "")),
                "offered_iops": source.get("offered_iops", ""),
                "rep": source.get("rep", ""),
                "valid": valid,
                "rc": source.get("rc", ""),
                "seconds": measure.get("seconds", ""),
                "writes": measure.get("writes", ""),
                "reads": measure.get("reads", ""),
                "total_ops_s": ((measure.get("writes", 0) + measure.get("reads", 0)) / measure.get("seconds", 1)) if measure else "",
                "write_iops": (measure.get("writes", 0) / measure.get("seconds", 1)) if measure else "",
                "read_iops": (measure.get("reads", 0) / measure.get("seconds", 1)) if measure else "",
                "lower_write_bytes": lower.get("write_bytes", ""),
                "lower_write_requests": lower.get("write_requests", ""),
                "lower_read_bytes": lower.get("read_bytes", ""),
                "lower_read_requests": lower.get("read_requests", ""),
                "lower_write_bytes_per_useful_write": (lower.get("write_bytes", 0) / measure.get("writes", 1)) if measure.get("writes") else "",
                "lower_write_requests_per_useful_write": (lower.get("write_requests", 0) / measure.get("writes", 1)) if measure.get("writes") else "",
                "lower_read_bytes_per_useful_read": (lower.get("read_bytes", 0) / measure.get("reads", 1)) if measure.get("reads") else "",
                "lower_read_requests_per_useful_read": (lower.get("read_requests", 0) / measure.get("reads", 1)) if measure.get("reads") else "",
                "flush_requests": lower.get("flush_requests", ""),
                "write_p50_ns": measure.get("write_p50_ns", ""),
                "write_p95_ns": measure.get("write_p95_ns", ""),
                "write_p99_ns": measure.get("write_p99_ns", ""),
                "read_p50_ns": measure.get("read_p50_ns", ""),
                "read_p95_ns": measure.get("read_p95_ns", ""),
                "read_p99_ns": measure.get("read_p99_ns", ""),
                "write_samples": measure.get("write_samples", ""),
                "read_samples": measure.get("read_samples", ""),
                "helper_cpu_s": measure.get("process_cpu_s", ""),
                "helper_peak_rss_kb": measure.get("peak_rss_kb", ""),
                "window_records": target.get("window_records", ""),
                "windows": target.get("windows", ""),
                "one_page_windows": target.get("one_page_windows", ""),
                "win1": target.get("win1", ""),
                "win2": target.get("win2", ""),
                "win3_4": target.get("win3_4", ""),
                "win5_8": target.get("win5_8", ""),
                "win9_16": target.get("win9_16", ""),
                "win17_64": target.get("win17_64", ""),
                "coalesce_deferred": target.get("coalesce_deferred", ""),
                "coalesce_urgent": target.get("coalesce_urgent", ""),
                "gc_rotations": target.get("gc_role_rotations", ""),
                "gc_read_bytes": target.get("gc_read", ""),
                "gc_write_bytes": target.get("gc_write", ""),
                "gc_read_requests": target.get("gc_read_reqs", ""),
                "gc_write_requests": target.get("gc_write_reqs", ""),
                "target_write_bytes": target.get("physical_write", ""),
                "target_write_requests": target.get("physical_write_reqs", ""),
                "target_read_bytes": target.get("physical_read", ""),
                "target_read_requests": target.get("physical_read_reqs", ""),
                "target_bulk_io": target.get("bulk_io", ""),
                "target_bulk_mixed_io": target.get("bulk_mixed_io", ""),
                "target_bulk_raw_only_io": target.get("bulk_raw_only_io", ""),
                "target_bulk_padding": target.get("bulk_padding", ""),
                "window_histogram_reconciles": (
                    target.get("windows") == sum((target.get(k) or 0) for k in ("win1", "win2", "win3_4", "win5_8", "win9_16", "win17_64"))
                    if target.get("windows") is not None else ""
                ),
                "backing_target_write_bytes_delta": (
                    lower.get("write_bytes", 0) - target.get("physical_write", 0)
                    if "write_bytes" in lower and target.get("physical_write") is not None else ""
                ),
                "backing_target_write_requests_delta": (
                    lower.get("write_requests", 0) - target.get("physical_write_reqs", 0)
                    if "write_requests" in lower and target.get("physical_write_reqs") is not None else ""
                ),
                "backing_target_read_bytes_delta": (
                    lower.get("read_bytes", 0) - target.get("physical_read", 0)
                    if "read_bytes" in lower and target.get("physical_read") is not None else ""
                ),
                "backing_target_read_requests_delta": (
                    lower.get("read_requests", 0) - target.get("physical_read_reqs", 0)
                    if "read_requests" in lower and target.get("physical_read_reqs") is not None else ""
                ),
                "verified_pages": verify.get("pages", ""),
                "verification": verify.get("result", ""),
                "trial_record": str(trial_path) if trial_path else "",
            }
            if valid:
                trials.append(row)
            else:
                row["reason"] = {
                    "runner_rc": source.get("rc"),
                    "phase": out.get("phase"),
                    "target_failed": out.get("target_failed"),
                    "errors": measure.get("errors"),
                    "mismatches": measure.get("mismatches"),
                    "verification": verify,
                }
                rejected.append(row)
    return trials, rejected


def med(values):
    return statistics.median(values) if values else ""


def write_csv(path, rows):
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True, help="sustained evidence directory")
    parser.add_argument("--output", type=Path, required=True, help="writable output directory")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows, rejected = load_rows(args.evidence)
    write_csv(args.output / "sustained-trials.csv", rows)
    write_csv(args.output / "rejected-trials.csv", rejected)
    groups = defaultdict(list)
    for row in rows:
        key = (row["matrix"], row["candidate"], str(row["class"]), str(row["qd"]), str(row["read_pct"]), str(row["coalesce_ms"]), str(row["offered_iops"]))
        groups[key].append(row)
    summary = []
    metrics = (
        "total_ops_s", "write_iops", "read_iops", "lower_write_bytes", "lower_write_requests",
        "lower_read_bytes", "lower_read_requests", "lower_write_bytes_per_useful_write",
        "lower_write_requests_per_useful_write", "lower_read_bytes_per_useful_read",
        "lower_read_requests_per_useful_read", "write_p50_ns", "write_p95_ns", "write_p99_ns",
        "read_p50_ns", "read_p95_ns", "read_p99_ns", "helper_cpu_s", "helper_peak_rss_kb",
        "windows", "one_page_windows", "win1", "win2", "win3_4", "win5_8", "win9_16", "win17_64",
        "coalesce_deferred", "coalesce_urgent", "gc_rotations", "gc_read_bytes", "gc_write_bytes",
        "gc_read_requests", "gc_write_requests",
    )
    for key, samples in sorted(groups.items()):
        entry = {
            "matrix": key[0], "candidate": key[1], "class": key[2], "qd": key[3],
            "read_pct": key[4], "coalesce_ms": key[5], "offered_iops": key[6], "n_valid": len(samples),
            "all_full_verifications": all(r["verified_pages"] == 4096 and r["verification"] == "PASS" for r in samples),
        }
        for metric in metrics:
            vals = [float(r[metric]) for r in samples if r[metric] not in ("", None)]
            entry[metric + "_median"] = med(vals)
            entry[metric + "_min"] = min(vals) if vals else ""
            entry[metric + "_max"] = max(vals) if vals else ""
        summary.append(entry)
    write_csv(args.output / "sustained-summary.csv", summary)
    (args.output / "sustained-summary.json").write_text(json.dumps({"valid_trial_count": len(rows), "rejected_trial_count": len(rejected), "groups": summary}, indent=2) + "\n")
    print(json.dumps({"valid_trials": len(rows), "rejected_trials": len(rejected), "groups": len(summary), "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
