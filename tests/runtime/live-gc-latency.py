#!/usr/bin/env python3
"""Measure synchronous raw-page writes and classify each by GC counter deltas."""
import argparse
import fcntl
import json
import mmap
import os
import random
import re
import struct
import subprocess
import time

PAGE = 4096
STATUS_KEYS = ("gc_victims", "gc_pages", "rotations")


def read_status(target):
    text = subprocess.check_output(["dmsetup", "status", target], text=True)
    values = dict(re.findall(r"(gc_victims|gc_pages|rotations)=(\d+)", text))
    return {key: int(values[key]) for key in STATUS_KEYS}


def percentile(values, percent):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * percent + 0.999999))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", required=True)
    parser.add_argument("--target-name", required=True)
    parser.add_argument("--operations", type=int, default=8192)
    args = parser.parse_args()
    fd = os.open(args.device, os.O_RDWR | os.O_DIRECT | os.O_CLOEXEC)
    page = mmap.mmap(-1, PAGE)
    rng = random.Random(0x44B1A73)
    try:
        page[:] = rng.randbytes(PAGE)
        if os.pwrite(fd, page, 200 * PAGE) != PAGE:
            raise OSError("short setup write")
        os.fsync(fd)
        fcntl.ioctl(fd, 0x1277, struct.pack("QQ", 200 * PAGE, PAGE))  # BLKDISCARD
        expected = None
        previous = read_status(args.target_name)
        samples = {"steady": [], "segment_switch_no_gc": [], "empty_gc": [], "live_gc": []}
        for _ in range(args.operations):
            expected = rng.randbytes(PAGE)
            page[:] = expected
            start = time.monotonic_ns()
            if os.pwrite(fd, page, 8 * PAGE) != PAGE:
                raise OSError("short timed write")
            elapsed = time.monotonic_ns() - start
            current = read_status(args.target_name)
            victim_delta = current["gc_victims"] - previous["gc_victims"]
            page_delta = current["gc_pages"] - previous["gc_pages"]
            rotation_delta = current["rotations"] - previous["rotations"]
            if victim_delta > 0:
                category = "live_gc" if page_delta > 0 else "empty_gc"
            elif rotation_delta > 0:
                category = "segment_switch_no_gc"
            else:
                category = "steady"
            samples[category].append(elapsed)
            previous = current
        if expected is None:
            raise SystemExit("no timed writes requested")
        if os.preadv(fd, [page], 8 * PAGE) != PAGE or page[:] != expected:
            raise SystemExit("final hot-page readback mismatch")
        os.fsync(fd)
        status = subprocess.check_output(["dmsetup", "status", args.target_name], text=True).strip()
        if "failed=0" not in status:
            raise SystemExit("target failed during latency run")
        for name, values in samples.items():
            if values:
                result = {
                    "class": name,
                    "samples": len(values),
                    "average_ms": round(sum(values) / len(values) / 1_000_000, 3),
                    "p95_ms": round(percentile(values, .95) / 1_000_000, 3),
                    "p99_ms": round(percentile(values, .99) / 1_000_000, 3),
                    "max_ms": round(max(values) / 1_000_000, 3),
                }
            else:
                result = {"class": name, "samples": 0}
            print("LATENCY " + json.dumps(result, sort_keys=True))
        if len(samples["live_gc"]) + len(samples["empty_gc"]) < 25:
            raise SystemExit("fewer than 25 GC-triggering writes observed")
        if not samples["live_gc"]:
            raise SystemExit("no live-GC-triggering write was observed")
        print("LATENCY_STATUS " + status)
    finally:
        page.close()
        os.close(fd)


if __name__ == "__main__":
    main()
