#!/usr/bin/env python3
"""Validate flush-inclusive swapz status versus owned lower-device I/O deltas.

Rootless parser only. The privileged runner owns lifecycle and captures snapshots;
this module never executes dmsetup, reads sysfs, or initiates I/O itself.
"""

import argparse
import json
from pathlib import Path

COUNTERS = (
    "logical_write", "physical_write", "compressed_payload",
    "compressed_pages", "raw_pages", "gc_write", "gc_victims",
    "physical_write_reqs",
)
IDENTITY = ("strategy", "batch_kib")


def parse_status(value):
    lines = value.strip().splitlines()
    if len(lines) != 1:
        raise ValueError("expected exactly one swapz status line")
    parts = lines[0].split()
    if len(parts) < 4 or parts[2] != "swapz":
        raise ValueError("expected '<start> <length> swapz key=value ...'")
    try:
        start, length = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError("invalid DM table geometry") from exc
    if start < 0 or length <= 0:
        raise ValueError("invalid DM table geometry")
    status = {"_geometry": (start, length)}
    for token in parts[3:]:
        if token.count("=") != 1:
            raise ValueError("malformed status token")
        key, raw = token.split("=", 1)
        if not key or not raw or key in status:
            raise ValueError("duplicate or empty status field: " + key)
        status[key] = raw
    for key in (*COUNTERS, "batch_kib", "failed"):
        if key not in status or not status[key].isascii() or not status[key].isdecimal():
            raise ValueError("missing/nondecimal status counter: " + key)
        status[key] = int(status[key])
    for key in IDENTITY:
        if key not in status:
            raise ValueError("missing status identity: " + key)
    if status["batch_kib"] <= 0 or status["failed"] != 0:
        raise ValueError("invalid batch size or failed swapz target")
    return status


def parse_lower_stat(value):
    """Read the runner's four-field subset: read_ios read_sectors write_ios write_sectors."""
    parts = value.split()
    if len(parts) != 4 or any(not p.isascii() or not p.isdecimal() for p in parts):
        raise ValueError("expected four nonnegative integer lower-device counters")
    return tuple(map(int, parts))


def compute(pre_status, post_status, pre_lower, post_lower, elapsed_ns, expected_logical=None):
    pre = parse_status(pre_status)
    post = parse_status(post_status)
    if pre["_geometry"] != post["_geometry"]:
        raise ValueError("DM target geometry changed during measurement")
    for key in IDENTITY:
        if pre[key] != post[key]:
            raise ValueError("swapz target identity changed: " + key)
    if not isinstance(elapsed_ns, int) or elapsed_ns <= 0:
        raise ValueError("nonpositive/noninteger monotonic counter interval")
    a, b = parse_lower_stat(pre_lower), parse_lower_stat(post_lower)
    if any(y < x for x, y in zip(a, b)):
        raise ValueError("lower-device counter decreased")
    delta = {key: post[key] - pre[key] for key in COUNTERS}
    if any(number < 0 for number in delta.values()):
        raise ValueError("swapz cumulative counter decreased")
    logical = delta["logical_write"]
    physical = delta["physical_write"]
    gc = delta["gc_write"]
    if logical <= 0 or physical <= 0:
        raise ValueError("logical or physical byte delta is zero")
    if gc > physical:
        raise ValueError("GC write bytes exceed all physical write bytes")
    if expected_logical is not None and logical != expected_logical:
        raise ValueError("fio completed writer bytes disagree with swapz logical writes")
    lower_bytes = (b[3] - a[3]) * 512
    if lower_bytes <= 0:
        raise ValueError("lower device recorded no write sectors")
    discrepancy = abs(lower_bytes - physical) / physical
    if discrepancy > 0.05:
        raise ValueError("kernel and dedicated lower-device write bytes differ by >5%")
    comp_pages = delta["compressed_pages"]
    raw_pages = delta["raw_pages"]
    payload = delta["compressed_payload"]
    if (comp_pages == 0) != (payload == 0):
        raise ValueError("compressed payload and page counters disagree")
    processed = comp_pages + raw_pages
    return {
        "measurement_scope": "fio plus successful flush; single owned null_blk only",
        "counter_window_seconds": elapsed_ns / 1e9,
        "logical_write_bytes": logical,
        "physical_write_bytes": physical,
        "lower_sysfs_write_bytes": lower_bytes,
        "lower_sysfs_discrepancy_fraction": discrepancy,
        "effective_io_reduction": logical / physical,
        "physical_write_reqs": delta["physical_write_reqs"],
        "gc_write_bytes": gc,
        "gc_fraction_of_lower_bytes": gc / physical,
        "compressed_payload_bytes": payload,
        "compressed_page_operations": comp_pages,
        "raw_page_operations": raw_pages,
        "raw_fallback_fraction_of_compression_operations": (
            raw_pages / processed if processed else None
        ),
        "lz4_payload_ratio_for_compression_operations": (
            comp_pages * 4096 / payload if payload else None
        ),
        "gc_victim_segments": delta["gc_victims"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pre_status", "post_status", "pre_lower", "post_lower"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    parser.add_argument("--elapsed-ns", type=int, required=True)
    parser.add_argument("--expected-logical-bytes", type=int, required=True)
    args = parser.parse_args()
    result = compute(args.pre_status.read_text(), args.post_status.read_text(),
                     args.pre_lower.read_text(), args.post_lower.read_text(),
                     args.elapsed_ns, args.expected_logical_bytes)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
