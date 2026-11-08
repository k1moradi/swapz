#!/usr/bin/env python3
"""Bounded anonymous-page swap oracle; never opens or configures a block device.

The controlling process must prove this run's exact swap mapper is active and
has positive backed swap usage after PAGEOUT and before sending VERIFY.
"""

import argparse
import ctypes
import hashlib
import json
import mmap
import re
import resource
import sys

PAGE_BYTES = 4096
ORACLE_PAGES = 2048
MADV_PAGEOUT = 21
PR_SET_DUMPABLE = 4


def page_bytes(seed: bytes, page_index: int) -> bytes:
    return hashlib.shake_256(seed + page_index.to_bytes(8, "little")).digest(PAGE_BYTES)


def verify_bytes(mapping, seed: bytes, page_count: int) -> tuple[int, str]:
    mismatches = 0
    digest = hashlib.sha256()
    for page_index in range(page_count):
        offset = page_index * PAGE_BYTES
        actual = mapping[offset:offset + PAGE_BYTES]
        if actual != page_bytes(seed, page_index):
            mismatches += 1
        digest.update(actual)
    return mismatches, digest.hexdigest()


def run_workload(seed_hex: str, page_count: int = ORACLE_PAGES) -> int:
    if (re.fullmatch(r"[0-9a-f]{32}", seed_hex) is None or
            type(page_count) is not int or not 1 <= page_count <= ORACLE_PAGES):
        return 2
    seed = bytes.fromhex(seed_hex)
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "cannot disable core dumps")
        with mmap.mmap(-1, page_count * PAGE_BYTES,
                       flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS,
                       prot=mmap.PROT_READ | mmap.PROT_WRITE) as mapping:
            expected_digest = hashlib.sha256()
            for page_index in range(page_count):
                page = page_bytes(seed, page_index)
                offset = page_index * PAGE_BYTES
                mapping[offset:offset + PAGE_BYTES] = page
                expected_digest.update(page)
            if not hasattr(mapping, "madvise"):
                raise OSError("anonymous-page eviction is unavailable")
            mapping.madvise(MADV_PAGEOUT)
            print("ALGORITHM_PAGEOUT_READY=" + json.dumps({
                "pages": page_count, "bytes": page_count * PAGE_BYTES,
                "expected_sha256": expected_digest.hexdigest(),
            }, sort_keys=True, separators=(",", ":")), flush=True)
            if sys.stdin.readline() != "VERIFY\n":
                raise ValueError("missing verification command")
            mismatches, actual_digest = verify_bytes(mapping, seed, page_count)
            print("ALGORITHM_PAGEOUT_VERIFIED=" + json.dumps({
                "pages": page_count, "bytes": page_count * PAGE_BYTES,
                "mismatches": mismatches,
                "actual_sha256": actual_digest,
                "expected_sha256": expected_digest.hexdigest(),
            }, sort_keys=True, separators=(",", ":")), flush=True)
            return 0 if mismatches == 0 and actual_digest == expected_digest.hexdigest() else 1
    except (OSError, ValueError, MemoryError, EOFError) as error:
        print("ALGORITHM_PAGEOUT_REFUSED=" + type(error).__name__, file=sys.stderr)
        return 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", required=True)
    arguments = parser.parse_args()
    return run_workload(arguments.seed)


if __name__ == "__main__":
    raise SystemExit(main())
