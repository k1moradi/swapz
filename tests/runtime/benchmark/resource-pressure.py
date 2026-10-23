#!/usr/bin/env python3
"""Bounded anonymous-memory and CPU pressure for the owned ID36 qualification."""

import argparse
import multiprocessing
import os
from pathlib import Path
import signal
import sys
import time


PAGE_BYTES = 4096
MIB = 1024 * 1024


def cpu_burn(stop_event):
    value = (os.getpid() << 1) | 1
    while not stop_event.is_set():
        # Fixed integer-only work avoids optional dependencies and allocations.
        for _ in range(20000):
            value = ((value * 2862933555777941757) + 3037000493) & ((1 << 64) - 1)
            value ^= value >> 17


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory-mib", type=int, required=True)
    parser.add_argument("--cpu-workers", type=int, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--stop-file", type=Path, required=True)
    args = parser.parse_args()

    if not 64 <= args.memory_mib <= 768:
        print("FAIL: ID36 memory pressure must be 64..768 MiB", file=sys.stderr)
        return 2
    if not 1 <= args.cpu_workers <= 32:
        print("FAIL: ID36 CPU worker count must be 1..32", file=sys.stderr)
        return 2

    stopping = False

    def request_stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    try:
        pressure = bytearray(args.memory_mib * MIB)
    except MemoryError:
        print("FAIL: ID36 pressure allocation failed", file=sys.stderr)
        return 1

    # Fault every page before declaring readiness. This prevents a large virtual
    # mapping from being mislabeled as resident low-memory pressure.
    for offset in range(0, len(pressure), PAGE_BYTES):
        pressure[offset] = (offset // PAGE_BYTES) & 0xFF

    context = multiprocessing.get_context("fork")
    stop_event = context.Event()
    workers = [
        context.Process(target=cpu_burn, args=(stop_event,), daemon=True)
        for _ in range(args.cpu_workers)
    ]
    for worker in workers:
        worker.start()

    args.ready_file.write_text(
        f"memory_mib={args.memory_mib} cpu_workers={args.cpu_workers}\n",
        encoding="ascii",
    )

    try:
        sweep = 0
        while not stopping and not args.stop_file.exists():
            # Re-reference a sparse subset so reclaim pressure stays active
            # without turning the memory worker into the dominant CPU load.
            start = (sweep % 16) * PAGE_BYTES
            for offset in range(start, len(pressure), 16 * PAGE_BYTES):
                pressure[offset] ^= 1
            sweep += 1
            time.sleep(0.05)
    finally:
        stop_event.set()
        for worker in workers:
            worker.join(timeout=2.0)
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
        for worker in workers:
            worker.join(timeout=2.0)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
