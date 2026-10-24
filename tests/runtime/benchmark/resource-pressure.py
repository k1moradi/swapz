#!/usr/bin/env python3
"""Bounded anonymous-memory and CPU pressure for the owned ID36 qualification."""

import argparse
import mmap
import multiprocessing
import os
from pathlib import Path
import signal
import sys
import time


PAGE_BYTES = 4096
MIB = 1024 * 1024


def cpu_burn(stop_event):
    # Preserve CPU contention without starving dmsetup/io-replay control paths.
    os.nice(10)
    value = (os.getpid() << 1) | 1
    while not stop_event.is_set():
        # Fixed integer-only work avoids optional dependencies and allocations.
        for _ in range(20000):
            value = ((value * 2862933555777941757) + 3037000493) & ((1 << 64) - 1)
            value ^= value >> 17


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory-mib", type=int, required=True)
    parser.add_argument("--ready-memory-mib", type=int)
    parser.add_argument("--cpu-workers", type=int, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--activate-file", type=Path)
    parser.add_argument("--active-file", type=Path)
    parser.add_argument("--stop-file", type=Path, required=True)
    args = parser.parse_args()

    if not 64 <= args.memory_mib <= 768:
        print("FAIL: ID36 memory pressure must be 64..768 MiB", file=sys.stderr)
        return 2
    ready_memory_mib = (
        args.memory_mib if args.ready_memory_mib is None
        else args.ready_memory_mib
    )
    if not 64 <= ready_memory_mib <= args.memory_mib:
        print("FAIL: ID36 ready memory must be 64..final memory MiB",
              file=sys.stderr)
        return 2
    staged = ready_memory_mib < args.memory_mib
    if staged and (args.activate_file is None or args.active_file is None):
        print("FAIL: ID36 staged pressure requires activate/active files",
              file=sys.stderr)
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

    # Fork CPU burners before the large resident mapping exists. Otherwise each
    # burner inherits the faulted mapping's COW page tables and consumes memory
    # that was intended as benchmark working headroom.
    context = multiprocessing.get_context("fork")
    stop_event = context.Event()
    workers = [
        context.Process(target=cpu_burn, args=(stop_event,), daemon=True)
        for _ in range(args.cpu_workers)
    ]
    for worker in workers:
        worker.start()

    pressure = None
    try:
        try:
            # Keep the unfaulted tail genuinely uncharged so the controller can
            # install memory.high between the ready baseline and the final
            # working set. bytearray(size) may eagerly zero pages and therefore
            # cannot provide this two-stage residency boundary reliably.
            pressure = mmap.mmap(
                -1, args.memory_mib * MIB,
                flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS,
                prot=mmap.PROT_READ | mmap.PROT_WRITE,
            )
        except (BufferError, OSError, ValueError):
            print("FAIL: ID36 pressure mapping failed", file=sys.stderr)
            return 1

        ready_bytes = ready_memory_mib * MIB
        for offset in range(0, ready_bytes, PAGE_BYTES):
            pressure[offset] = (offset // PAGE_BYTES) & 0xFF

        if any(not worker.is_alive() for worker in workers):
            print("FAIL: ID36 CPU pressure worker exited before readiness",
                  file=sys.stderr)
            return 1

        args.ready_file.write_text(
            f"memory_mib={args.memory_mib} "
            f"ready_memory_mib={ready_memory_mib} "
            f"cpu_workers={args.cpu_workers}\n",
            encoding="ascii",
        )

        if staged:
            while (not stopping and not args.stop_file.exists() and
                   not args.activate_file.exists()):
                if any(not worker.is_alive() for worker in workers):
                    print("FAIL: ID36 CPU pressure worker exited before activation",
                          file=sys.stderr)
                    return 1
                time.sleep(0.01)
            if stopping or args.stop_file.exists():
                return 0

            # The controller has installed memory.high at the ready-state charge.
            # Fault the remaining bounded tail now so crossing the high watermark
            # is deliberate and independent of benchmark allocation behavior.
            for offset in range(ready_bytes, len(pressure), PAGE_BYTES):
                pressure[offset] = (offset // PAGE_BYTES) & 0xFF

            args.active_file.write_text(
                f"memory_mib={args.memory_mib} "
                f"ready_memory_mib={ready_memory_mib}\n",
                encoding="ascii",
            )

        sweep = 0
        while not stopping and not args.stop_file.exists():
            if any(not worker.is_alive() for worker in workers):
                print("FAIL: ID36 CPU pressure worker exited early", file=sys.stderr)
                return 1
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
        if pressure is not None:
            pressure.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
