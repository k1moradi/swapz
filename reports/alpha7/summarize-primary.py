#!/usr/bin/env python3
"""Validate and summarize the preserved 1024-page primary-I/O trials."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path


def status_fields(line: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for token in line.split()[3:]:
        if "=" in token:
            key, value = token.split("=", 1)
            fields[key] = value
    return fields


def load_trial(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text())
    if data.get("phase") != "PASS" or data.get("status") != "PASS":
        raise ValueError(f"not a PASS trial: {path}")
    verification = data.get("verification", {})
    if verification.get("exit_code") != 0 or "verify_pages=1024 errors=0 result=PASS" not in verification.get("stdout", ""):
        raise ValueError(f"data verification did not pass: {path}")
    stats = data["backing_deltas_after_write"]
    target = status_fields(data["status_after_write"])
    useful = int(target["logical_write"])
    write_bytes = int(stats["write_sectors_512"]) * 512
    write_reqs = int(stats["write_requests"])
    target_write_bytes = int(target["physical_write"])
    target_write_reqs = int(target["physical_write_reqs"])
    if useful != 1024 * 4096:
        raise ValueError(f"logical byte count mismatch: {path}: {useful}")
    if write_bytes != target_write_bytes or write_reqs != target_write_reqs:
        raise ValueError(
            f"backing/target write counter mismatch: {path}: "
            f"lower={write_bytes}/{write_reqs} target={target_write_bytes}/{target_write_reqs}"
        )
    verify = data["backing_deltas_verification"]
    if int(verify["read_requests"]) != 1024 or int(verify["read_sectors_512"]) * 512 != EXPECTED_VERIFY_BYTES:
        raise ValueError(f"verification read accounting mismatch: {path}: {verify}")
    if int(target.get("failed", "0")) != 0 or int(target.get("error", "0")) != 0:
        raise ValueError(f"target reported a failed run: {path}")
    return {
        "implementation": data["implementation"],
        "lower_bulk": data["lower_bulk"],
        "repetition": data["repetition"],
        "source_sha": {
            "alpha7": "0e199159cea3dd479224ce59513ee9c0a810a0d6",
            "alpha6": "4324c98497891147896ad817f4593c5cc198953b",
            "v22": "3a89ebbeba21c814dcf724e227b31d38445a3f9a",
        }[data["implementation"]],
        "module_sha256": data["module_sha256"],
        "probe_sha256": data["probe_sha256"],
        "verifier_sha256": data["verifier_sha256"],
        "logical_write_bytes": useful,
        "verified_pages": 1024,
        "lower_write_requests": write_reqs,
        "lower_write_bytes": write_bytes,
        "target_write_requests": target_write_reqs,
        "target_write_bytes": target_write_bytes,
        "lower_read_requests_during_write": int(data["backing_deltas_after_write"]["read_requests"]),
        "lower_read_bytes_during_write": int(data["backing_deltas_after_write"]["read_sectors_512"]) * 512,
        "verification_read_requests": int(data["backing_deltas_verification"]["read_requests"]),
        "verification_read_bytes": int(data["backing_deltas_verification"]["read_sectors_512"]) * 512,
        "compressed_pages": int(target.get("compressed", target.get("compressed_pages", "0"))),
        "raw_pages": int(target.get("raw", target.get("raw_pages", "0"))),
        "target_window_records": int(target.get("window_records", "0")),
        "target_windows": int(target.get("windows", "0")),
        "target_one_page_windows": int(target.get("one_page_windows", "0")),
        "target_lower_bulk": int(target.get("bulk_mode", "0")),
        "target_bulk_io": int(target.get("bulk_io", "0")),
        "target_bulk_extents": int(target.get("bulk_extents", "0")),
        "target_bulk_mixed_io": int(target.get("bulk_mixed_io", "0")),
        "target_bulk_raw_only_io": int(target.get("bulk_raw_only_io", "0")),
        "target_bulk_raw_entries": int(target.get("bulk_raw_entries", "0")),
        "trial_directory": path.parent.name,
    }


def summarize(values: list[int]) -> dict[str, float | int]:
    return {
        "n": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "mean": statistics.mean(values),
        "max": max(values),
    }


EXPECTED_VERIFY_BYTES = 1024 * 4096


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    names = [f"v22-b0-r{i}" for i in range(1, 6)]
    names += [f"alpha6-b{b}-r{i}" for b in range(3) for i in range(1, 6)]
    names += ["alpha7-b0-r1-retry2"]
    names += [f"alpha7-b0-r{i}" for i in range(2, 6)]
    names += [f"alpha7-b{b}-r{i}" for b in (1, 2) for i in range(1, 6)]
    rows = [load_trial(args.trials / name / "trial.json") for name in names]
    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = args.out / "primary-trials.csv"
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    groups: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        key = f"{row['implementation']}-b{row['lower_bulk']}"
        groups.setdefault(key, []).append(row)
    summary: dict[str, object] = {"trial_count": len(rows), "groups": {}}
    for key, group in groups.items():
        entry = {}
        for field in ("logical_write_bytes", "lower_write_bytes", "lower_write_requests",
                      "lower_read_bytes_during_write", "lower_read_requests_during_write",
                      "verification_read_bytes", "verification_read_requests",
                      "target_windows", "target_one_page_windows", "target_bulk_io"):
            entry[field] = summarize([int(row[field]) for row in group])
        entry["all_verified"] = all(row["verified_pages"] == 1024 for row in group)
        entry["counter_reconciled"] = all(
            row["lower_write_bytes"] == row["target_write_bytes"]
            and row["lower_write_requests"] == row["target_write_requests"]
            for row in group
        )
        summary["groups"][key] = entry
    (args.out / "primary-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
