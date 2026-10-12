#!/usr/bin/env python3
"""Validate and summarize raw JSONL from engine-bench.c."""
import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


METRICS = (
    "ordered4_model_bytes",
    "v3_written_bytes",
    "modeled_ordered_over_v3",
    "v3_logical_write_ratio",
    "read_blocks_per_page",
    "plan_wall_ns",
    "plan_cpu_ns",
    "write_wall_ns",
    "write_cpu_ns",
    "lower_callback_wall_ns",
    "read_wall_ns",
    "read_cpu_ns",
    "read_p50_ns",
    "read_p95_ns",
    "read_p99_ns",
    "read_max_ns",
    "write_window_p50_ns",
    "write_window_p95_ns",
    "write_window_p99_ns",
    "write_window_max_ns",
)


def percentile(values, percent):
    ordered = sorted(values)
    if not ordered:
        return 0
    rank = max(1, math.ceil(percent * len(ordered) / 100))
    return ordered[min(rank, len(ordered)) - 1]


def load_rows(path):
    rows = []
    for line_number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
    return rows


def summarize(input_path, output_prefix):
    rows = load_rows(input_path)
    engine = [row for row in rows if row.get("kind") == "engine"]
    distributions = [row for row in rows
                     if row.get("kind") == "lz4_distribution"]
    if not engine:
        raise ValueError("no engine result rows")
    if any(not row.get("correct") or row.get("error") for row in engine):
        raise ValueError("refusing incorrect or failed engine result")

    groups = defaultdict(list)
    for row in engine:
        groups[(row["workload"], row["window"])].append(row)
    summaries = []
    for (workload, window), group in sorted(groups.items()):
        repetitions = sorted(row["repetition"] for row in group
                             if row["repetition"] > 0)
        if len(repetitions) != len(set(repetitions)):
            raise ValueError(f"duplicate repetitions: {workload}/{window}")
        if repetitions and repetitions != list(range(1, len(repetitions) + 1)):
            raise ValueError(f"non-contiguous repetitions: {workload}/{window}")
        record = {
            "workload": workload,
            "window": window,
            "runs": len(group),
            "reader_samples": sorted(row["read_pages"] for row in group),
        }
        for metric in METRICS:
            values = [row[metric] for row in group]
            record[f"{metric}_median"] = statistics.median(values)
            record[f"{metric}_p95_across_runs"] = percentile(values, 95)
            record[f"{metric}_max_across_runs"] = max(values)
        for field in ("records", "read_pages", "logical_bytes",
                      "payload_bytes", "ordered4_model_blocks",
                      "v3_written_blocks", "physical_read_blocks",
                      "planned_4k_extents", "planned_8k_extents",
                      "planned_16k_extents", "reserve_blocks",
                      "abandoned_blocks", "alignment_gap_blocks"):
            record[field] = group[0][field]
            if any(row[field] != record[field] for row in group):
                raise ValueError(f"non-deterministic accounting: {workload}/{window}/{field}")
        record["all_run_counters_reconciled"] = all(
            row["completed_blocks"] == row["v3_written_blocks"] and
            row["submitted_blocks"] == row["completed_blocks"] and
            row["actual_4k_extents"] == row["planned_4k_extents"] and
            row["actual_8k_extents"] == row["planned_8k_extents"] and
            row["actual_16k_extents"] == row["planned_16k_extents"]
            for row in group
        )
        if not record["all_run_counters_reconciled"]:
            raise ValueError(f"counter mismatch: {workload}/{window}")
        summaries.append(record)

    lz4_stats = []
    for row in distributions:
        lengths = row["lengths"]
        pairs = sum(
            8 + 2 * 8 + lengths[i] + lengths[i + 1] <= 4096
            for i in range(len(lengths) - 1)
        )
        triples = sum(
            8 + 3 * 8 + lengths[i] + lengths[i + 1] + lengths[i + 2] <= 4096
            for i in range(len(lengths) - 2)
        )
        ordered = sorted(lengths)
        lz4_stats.append({
            "workload": row["workload"],
            "seed": row["seed"],
            "records": len(lengths),
            "min": min(lengths),
            "median": statistics.median(lengths),
            "mean": statistics.mean(lengths),
            "p95": percentile(lengths, 95),
            "max": max(lengths),
            "raw_fallbacks": row["raw_fallbacks"],
            "records_larger_than_2036": sum(length > 2036 for length in lengths),
            "pairs_fitting_ordered4_container": pairs,
            "triples_fitting_ordered4_container": triples,
            "lengths": lengths,
        })
    prefix = Path(output_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    (prefix.with_suffix(".summary.json")).write_text(
        json.dumps({"engine_runs": summaries, "lz4_distributions": lz4_stats},
                   indent=2, sort_keys=True) + "\n"
    )
    if summaries:
        with prefix.with_suffix(".summary.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(summaries[0]))
            writer.writeheader()
            writer.writerows(summaries)
    return summaries, lz4_stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-prefix", required=True)
    args = parser.parse_args()
    summaries, lz4_stats = summarize(args.input, args.output_prefix)
    print(f"engine_groups={len(summaries)}")
    print(f"lz4_distributions={len(lz4_stats)}")
    print(f"summary_json={Path(args.output_prefix).with_suffix('.summary.json')}")
    print(f"summary_csv={Path(args.output_prefix).with_suffix('.summary.csv')}")


if __name__ == "__main__":
    main()
