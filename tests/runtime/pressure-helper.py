#!/usr/bin/env python3
"""Bounded pressure workload; checkpoints release by private file tokens.

Importing this module does not allocate memory or touch any devices.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from pressure_checkpoint import wait_checkpoint


PAGE_SIZE = 4096


def page_data(seed: int, page: int, page_size: int = PAGE_SIZE) -> bytes:
    return random.Random(seed ^ (page * 0x9E3779B1)).randbytes(page_size)


def verify_pages(view: memoryview, pages: int, seed: int, *,
                 page_size: int = PAGE_SIZE, passes: int = 4) -> None:
    order = list(range(pages))
    for pass_number in range(passes):
        random.Random(seed + pass_number).shuffle(order)
        for page in order:
            start = page * page_size
            if view[start:start + page_size] != page_data(seed, page, page_size):
                raise ValueError(
                    f"readback mismatch at pass={pass_number} page={page}")


def run_workload(size_mib: int, marker_dir: Path, token: str, *,
                 checkpoint_timeout: float = 90.0) -> None:
    if size_mib <= 0:
        raise ValueError("pressure test size must be positive")
    size = size_mib * 1024 * 1024
    pages = size // PAGE_SIZE
    seed = 0x5A7A2026 + size_mib
    buf = bytearray(size)
    view = memoryview(buf)
    for page in range(pages):
        start = page * PAGE_SIZE
        view[start:start + PAGE_SIZE] = page_data(seed, page)
    # Keep both the buffer and memoryview alive during each checkpoint.
    wait_checkpoint(marker_dir, token, "filled", timeout_seconds=checkpoint_timeout)
    verify_pages(view, pages, seed)
    wait_checkpoint(marker_dir, token, "verified", timeout_seconds=checkpoint_timeout)
    print(f"bounded swap pressure readback: PASS size_mib={size_mib} "
          f"pages={pages} passes=4", flush=True)


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("usage: pressure-helper.py SIZE_MIB PRIVATE_DIR TOKEN")
    run_workload(int(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
