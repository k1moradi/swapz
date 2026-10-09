#!/usr/bin/env python3
"""Read-only, deliberately NON-qualifying V2.2 single-sweep diagnostics.

Consumes streaming-benchmark.sh's JSONL observations after that script has
verified each target teardown. No device access, shell commands, counter
collection, benchmarking, threshold optimization, or winner nomination.
The collector's sysfs counters may include unrelated backend I/O and do not
independently establish full kernel I/O quiescence.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import re

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 128
MIB = 1024 * 1024
SECTOR_SIZE = 512
BATCHES = {4, 8, 16, 32, 64, 128, 256, 512, 1024}
STRATEGIES = {"immediate", "opportunistic", "staged"}
REQUIRED = {
    "backend", "strategy", "batch_kib", "logical_write_bytes",
    "upper_write_mib_s", "logical_flush_window_mib_s",
    "lower_counter_window_mib_s", "drain_window_s",
    "lower_write_sectors", "lower_write_ios", "read_count",
    "read_p99_ms", "read_max_ms", "status", "staged_early",
}


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError(f"nonfinite JSON value: {value}")


def _int(row: dict[str, object], key: str) -> int:
    value = row[key]
    if type(value) is not int or value < 0:
        raise ValueError(f"{key}: expected nonnegative integer")
    return value


def _float(row: dict[str, object], key: str) -> float:
    value = row[key]
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{key}: expected finite nonnegative number")
    return float(value)


def validate(row: object, line: int) -> dict[str, object]:
    if not isinstance(row, dict) or not REQUIRED.issubset(row):
        raise ValueError(f"line {line}: incomplete streaming-benchmark observation")
    backend = row["backend"]
    if type(backend) is not str or not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", backend):
        raise ValueError(f"line {line}: malformed backend identity")
    if row["strategy"] not in STRATEGIES:
        raise ValueError(f"line {line}: unsupported strategy")
    batch = _int(row, "batch_kib")
    if batch not in BATCHES or (row["strategy"] == "immediate" and batch != 4):
        raise ValueError(f"line {line}: invalid batch for strategy")
    if not isinstance(row["status"], dict) or row["status"].get("failed") != "0":
        raise ValueError(f"line {line}: benchmark status did not attest failed=0")
    for key in ("logical_write_bytes", "lower_write_sectors", "lower_write_ios",
                "read_count", "staged_early"):
        _int(row, key)
    elapsed = _float(row, "drain_window_s")
    if elapsed <= 0 or elapsed > 86400:
        raise ValueError(f"line {line}: invalid positive monotonic duration")
    for key in ("upper_write_mib_s", "logical_flush_window_mib_s",
                "lower_counter_window_mib_s", "read_p99_ms", "read_max_ms"):
        _float(row, key)
    if row["read_count"] == 0 or row["logical_write_bytes"] == 0:
        raise ValueError(f"line {line}: workload did not record writes and reads")
    if row["read_p99_ms"] > row["read_max_ms"]:
        raise ValueError(f"line {line}: p99 exceeds measured maximum")
    # Explicitly cross-check that the diagnostic lower counter rate came
    # from sectors, not fio's logical bytes or upper completion bandwidth.
    check_rates = (
        ("lower_counter_window_mib_s", row["lower_write_sectors"] * SECTOR_SIZE),
        ("logical_flush_window_mib_s", row["logical_write_bytes"]),
    )
    for field, numerator in check_rates:
        expected = numerator / MIB / elapsed
        if not math.isclose(row[field], expected, rel_tol=1e-6, abs_tol=1e-7):
            raise ValueError(f"line {line}: inconsistent {field} numerator")
    return row


def read_rows(path: Path) -> list[dict[str, object]]:
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("JSONL input missing, not a regular file or oversized")
    rows: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as stream:
        for number, raw in enumerate(stream, start=1):
            if number > MAX_ROWS:
                raise ValueError("too many benchmark observations")
            if not raw.strip():
                raise ValueError(f"line {number}: blank observation")
            try:
                row = json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"line {number}: malformed JSON: {exc}") from exc
            rows.append(validate(row, number))
    if not rows:
        raise ValueError("empty benchmark observations")
    keys = [(row["strategy"], row["batch_kib"]) for row in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate strategy/batch observation in single-run sweep")
    if len({row["backend"] for row in rows}) != 1:
        raise ValueError("different backend identities cannot share single sweep")
    return rows


def report(rows: list[dict[str, object]]) -> str:
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[row["strategy"]].append(row)
    out = [
        "=== V2.2 SINGLE-RUN DIAGNOSTICS: NO QUALIFIED WINNER ===",
        "lower_counter_window_mib_s = sysfs lower-write sectors / timed window; "
        "backend attribution and complete I/O drain NOT independently attested",
        "logical_flush_window_mib_s = fio logical bytes / flush-inclusive window; "
        "NOT lower-device drain bandwidth",
    ]
    for strategy in sorted(groups):
        out.append(f"strategy={strategy} (unqualified; only one observation per batch)")
        for row in sorted(groups[strategy], key=lambda value: value["batch_kib"]):
            out.append(
                f"  {row['batch_kib']:4d}KiB "
                f"upper={row['upper_write_mib_s']:.3f}MiB/s "
                f"logical_flush_window={row['logical_flush_window_mib_s']:.3f}MiB/s "
                f"lower_counter_window={row['lower_counter_window_mib_s']:.3f}MiB/s "
                f"lower_wios={row['lower_write_ios']} "
                f"read_p99={row['read_p99_ms']:.3f}ms "
                f"read_count={row['read_count']}"
            )
    out.extend([
        "PLATEAU NOT REACHED: no same-configuration independent repeats, "
        "no authenticated lower-device drain, and no qualified p99.",
        "Use v22-drain-plateau-analyze.py only on independently collected "
        "full-sweep observations satisfying its stricter schema.",
    ])
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True,
                        help="existing JSONL from a completed authorized streaming sweep")
    args = parser.parse_args()
    try:
        result = report(read_rows(args.results))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
