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


def _parse_seed(seed_hex: str) -> bytes:
    if not isinstance(seed_hex, str) or len(seed_hex) != 32 or any(
            character not in "0123456789abcdef" for character in seed_hex):
        raise ValueError("seed must be exactly 32 lowercase hexadecimal characters")
    return bytes.fromhex(seed_hex)


def _page_pattern_from_seed(seed: bytes, page_index: int) -> bytes:
    # Expand the run/page seed into position-distinct bytes across all 4 KiB.
    # Repeating one 32-byte digest would miss within-page block transpositions.
    return hashlib.shake_256(
        seed + page_index.to_bytes(8, "little")).digest(PAGE_BYTES)


def page_pattern(seed_hex: str, page_index: int) -> bytes:
    if page_index < 0:
        raise ValueError("page index must be nonnegative")
    return _page_pattern_from_seed(_parse_seed(seed_hex), page_index)


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
    allocation_bytes = memory_mib * MIB
    if allocation_bytes % PAGE_BYTES:
        print("FAIL: oracle memory is not page aligned", file=sys.stderr)
        return 2
    try:
        seed = _parse_seed(seed_hex)
    except ValueError as exc:
        print(f"FAIL: oracle seed is invalid: {exc}", file=sys.stderr)
        return 2
    try:
        _disable_dumps()
    except RuntimeError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2

    pages = allocation_bytes // PAGE_BYTES
    _emit("ORACLE_WAITING=", {
        "pid": os.getpid(),
        "pages": pages,
        "bytes": allocation_bytes,
        "seed": seed_hex,
    })
    try:
        if _read_command() != "FILL":
            raise RuntimeError("expected FILL command")
        allocation = mmap.mmap(
            -1,
            allocation_bytes,
            flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS,
            prot=mmap.PROT_READ | mmap.PROT_WRITE,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"FAIL: oracle allocation/start failed: {exc}", file=sys.stderr)
        return 1

    expected_digest = hashlib.blake2b(digest_size=32)
    fill_started = time.monotonic()
    result = 1
    phase = "fill"
    verified_pages = 0
    byte_mismatches = 0
    verification_record = None
    original_error = None
    cleanup_error = None
    try:
        for page_index in range(pages):
            expected = _page_pattern_from_seed(seed, page_index)
            offset = page_index * PAGE_BYTES
            allocation[offset:offset + PAGE_BYTES] = expected
            expected_digest.update(expected)
        _emit("ORACLE_FILLED=", {
            "pages": pages,
            "bytes": allocation_bytes,
            "digest": expected_digest.hexdigest(),
            "elapsed_seconds": round(time.monotonic() - fill_started, 6),
        })

        phase = "wait_verify"
        if _read_command() != "VERIFY":
            raise RuntimeError("expected VERIFY command")
        phase = "verify"
        verify_started = time.monotonic()
        observed_digest = hashlib.blake2b(digest_size=32)
        mismatches = []
        for page_index in range(pages):
            expected = _page_pattern_from_seed(seed, page_index)
            offset = page_index * PAGE_BYTES
            observed = allocation[offset:offset + PAGE_BYTES]
            if len(observed) != PAGE_BYTES:
                raise RuntimeError(
                    f"short oracle page read at page {page_index}: "
                    f"{len(observed)} of {PAGE_BYTES} bytes")
            observed_digest.update(observed)
            if observed != expected:
                differences = [
                    index for index, (left, right) in enumerate(zip(observed, expected))
                    if left != right
                ]
                byte_mismatches += len(differences)
                if len(mismatches) < 16:
                    # Only offsets enter evidence; never disclose page contents.
                    mismatches.append({
                        "page": page_index,
                        "byte": differences[0],
                    })
            # Store the expected value after reading the entire page: this
            # forces a writable fault after swap-in without hiding corruption.
            allocation[offset] = expected[0]
            verified_pages += 1
        actual_digest = observed_digest.hexdigest()
        expected_hex = expected_digest.hexdigest()
        verification_record = {
            "verified_pages": verified_pages,
            "verified_bytes": verified_pages * PAGE_BYTES,
            "mismatches": byte_mismatches,
            "mismatch_samples": mismatches,
            "digest": actual_digest,
            "expected_digest": expected_hex,
            "elapsed_seconds": round(time.monotonic() - verify_started, 6),
        }
        result = (
            0 if byte_mismatches == 0 and actual_digest == expected_hex else 1)
    except (OSError, RuntimeError, MemoryError, KeyboardInterrupt) as exc:
        original_error = exc
        result = 1
    finally:
        try:
            allocation.close()
        except (OSError, BufferError, ValueError, KeyboardInterrupt) as exc:
            cleanup_error = exc
            result = 1

    # Complete-looking evidence is terminal only after unmapping succeeded.
    # Preserve the first verification error even if cleanup or reporting fails.
    if cleanup_error is None and verification_record is not None:
        try:
            _emit("ORACLE_VERIFIED=", verification_record)
        except (OSError, RuntimeError, KeyboardInterrupt) as exc:
            original_error = exc
            phase = "report"
            result = 1
    if original_error is not None:
        print(f"FAIL: oracle workload failed: {original_error}", file=sys.stderr)
    if cleanup_error is not None:
        print(f"FAIL: oracle allocation cleanup failed: {cleanup_error}",
              file=sys.stderr)
    if result != 0:
        failure_phase = phase
        if (cleanup_error is not None and original_error is None and
                byte_mismatches == 0):
            failure_phase = "cleanup"
        failure_error = original_error if original_error is not None else cleanup_error
        original_errno = getattr(failure_error, "errno", None)
        failure_type = (type(failure_error).__name__ if failure_error is not None else
                        "byte_mismatch" if byte_mismatches else "digest_mismatch")
        print(
            f"FAIL: oracle phase={failure_phase} "
            f"verified_pages={verified_pages}/{pages} "
            f"verified_bytes={verified_pages * PAGE_BYTES}/{allocation_bytes} "
            f"expected_mismatches=0 observed_mismatches={byte_mismatches} "
            f"error={failure_type} "
            f"errno={original_errno if original_errno is not None else 'none'} "
            f"cleanup_complete={str(cleanup_error is None).lower()}",
            file=sys.stderr)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--memory-mib", required=True, type=int)
    arguments = parser.parse_args()
    return run_workload(arguments.seed, arguments.memory_mib)


if __name__ == "__main__":
    raise SystemExit(main())
