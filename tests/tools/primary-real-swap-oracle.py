#!/usr/bin/env python3
"""Bounded deterministic anonymous-memory oracle for primary real-swap qualification.

This helper never configures swap or Device Mapper. The parent qualification
process places it in a dedicated cgroup before sending FILL, then relaxes the
resident limit before sending VERIFY. Every allocated page carries a
run-specific deterministic 4 KiB pattern and is compared byte-for-byte.
"""

import argparse
import ctypes
import hashlib
import json
import mmap
import os
import resource
import sys
import time

PAGE_BYTES = 4096
MIB = 1024 * 1024
MIN_MIB = 64
MAX_MIB = 512
PR_SET_DUMPABLE = 4


def _disable_dumps() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "prctl(PR_SET_DUMPABLE) failed")
    except (AttributeError, OSError) as exc:
        raise RuntimeError(f"cannot disable process dumps: {exc}") from exc


def page_pattern(seed_hex: str, page_index: int) -> bytes:
    if len(seed_hex) != 32 or any(character not in "0123456789abcdef" for character in seed_hex):
        raise ValueError("seed must be exactly 32 lowercase hexadecimal characters")
    if page_index < 0:
        raise ValueError("page index must be nonnegative")
    seed = bytes.fromhex(seed_hex)
    digest = hashlib.blake2s(seed + page_index.to_bytes(8, "little"), digest_size=32).digest()
    return digest * (PAGE_BYTES // len(digest))


def _read_command() -> str:
    line = sys.stdin.readline()
    if not line:
        raise RuntimeError("qualification controller closed the command pipe")
    return line.strip()


def _emit(prefix: str, payload: dict) -> None:
    print(prefix + json.dumps(payload, sort_keys=True, separators=(",", ":")), flush=True)


def run_workload(seed_hex: str, memory_mib: int) -> int:
    if not MIN_MIB <= memory_mib <= MAX_MIB:
        print(f"FAIL: oracle memory must be {MIN_MIB}..{MAX_MIB} MiB", file=sys.stderr)
        return 2
    if memory_mib * MIB % PAGE_BYTES:
        print("FAIL: oracle memory is not page aligned", file=sys.stderr)
        return 2
    try:
        _disable_dumps()
    except RuntimeError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2

    pages = memory_mib * MIB // PAGE_BYTES
    _emit("ORACLE_WAITING=", {
        "pid": os.getpid(),
        "pages": pages,
        "bytes": pages * PAGE_BYTES,
        "seed": seed_hex,
    })
    try:
        if _read_command() != "FILL":
            raise RuntimeError("expected FILL command")
        allocation = mmap.mmap(
            -1,
            pages * PAGE_BYTES,
            flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS,
            prot=mmap.PROT_READ | mmap.PROT_WRITE,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"FAIL: oracle allocation/start failed: {exc}", file=sys.stderr)
        return 1

    expected_digest = hashlib.blake2b(digest_size=32)
    fill_started = time.monotonic()
    try:
        for page_index in range(pages):
            expected = page_pattern(seed_hex, page_index)
            offset = page_index * PAGE_BYTES
            allocation[offset:offset + PAGE_BYTES] = expected
            expected_digest.update(expected)
        _emit("ORACLE_FILLED=", {
            "pages": pages,
            "bytes": pages * PAGE_BYTES,
            "digest": expected_digest.hexdigest(),
            "elapsed_seconds": round(time.monotonic() - fill_started, 6),
        })

        if _read_command() != "VERIFY":
            raise RuntimeError("expected VERIFY command")
        verify_started = time.monotonic()
        observed_digest = hashlib.blake2b(digest_size=32)
        mismatches = []
        for page_index in range(pages):
            expected = page_pattern(seed_hex, page_index)
            offset = page_index * PAGE_BYTES
            observed = allocation[offset:offset + PAGE_BYTES]
            observed_digest.update(observed)
            if observed != expected and len(mismatches) < 16:
                first_difference = next(
                    (index for index, (left, right) in enumerate(zip(observed, expected))
                     if left != right),
                    -1,
                )
                mismatches.append({
                    "page": page_index,
                    "byte": first_difference,
                    "observed": observed[first_difference] if first_difference >= 0 else None,
                    "expected": expected[first_difference] if first_difference >= 0 else None,
                })
            # An explicit same-value store makes every verified page writable
            # again after swap-in without altering the deterministic oracle.
            allocation[offset] = observed[0]
        actual_digest = observed_digest.hexdigest()
        expected_hex = expected_digest.hexdigest()
        _emit("ORACLE_VERIFIED=", {
            "verified_pages": pages,
            "verified_bytes": pages * PAGE_BYTES,
            "mismatches": len(mismatches),
            "mismatch_samples": mismatches,
            "digest": actual_digest,
            "expected_digest": expected_hex,
            "elapsed_seconds": round(time.monotonic() - verify_started, 6),
        })
        return 0 if not mismatches and actual_digest == expected_hex else 1
    except (OSError, RuntimeError) as exc:
        print(f"FAIL: oracle workload failed: {exc}", file=sys.stderr)
        return 1
    finally:
        allocation.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--memory-mib", required=True, type=int)
    arguments = parser.parse_args()
    return run_workload(arguments.seed, arguments.memory_mib)


if __name__ == "__main__":
    raise SystemExit(main())
