#!/usr/bin/env python3
"""Validate fio's full writer-range CRC32C readback report (ROOTLESS).

The caller, not this script, runs fio against an explicitly authorized
device. This verifier only reads a bounded JSON regular file. It requires
a complete 4 KiB sequential read pass with fio error=0, and never
promotes the result to independent kernel I/O provenance.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_WRITER_BYTES = 1024 * 1024 * 1024
PAGE = 4096


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate fio verify JSON field")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"nonfinite fio verify JSON value {value}")


def validate(path: Path, expected_bytes: int) -> dict[str, object]:
    if (type(expected_bytes) is not int or
            not PAGE <= expected_bytes <= MAX_WRITER_BYTES or
            expected_bytes % PAGE):
        raise ValueError("writer bytes must be positive, 4 KiB aligned and bounded")
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC |
                         os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
                not 0 < before.st_size <= MAX_JSON_BYTES):
            raise ValueError("fio verification report must be a bounded regular file")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            raw = stream.read(MAX_JSON_BYTES + 1)
            after = os.fstat(stream.fileno())
            if (len(raw) != before.st_size or len(raw) > MAX_JSON_BYTES or
                    (before.st_dev, before.st_ino, before.st_size,
                     before.st_mtime_ns, before.st_ctime_ns, before.st_nlink) !=
                    (after.st_dev, after.st_ino, after.st_size,
                     after.st_mtime_ns, after.st_ctime_ns, after.st_nlink)):
                raise ValueError("fio verification report changed or exceeded bound")
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    root = json.loads(raw, object_pairs_hook=_object,
                      parse_constant=_reject_constant)
    if type(root) is not dict or type(root.get("jobs")) is not list or len(root["jobs"]) != 1:
        raise ValueError("fio verification requires exactly one job")
    job = root["jobs"][0]
    if type(job) is not dict or job.get("jobname") != "writer-verify":
        raise ValueError("unexpected fio verification job identity")
    if type(job.get("error")) is not int or job["error"] != 0:
        raise ValueError("fio verification job reported an error")
    read = job.get("read")
    if type(read) is not dict:
        raise ValueError("fio verification missing read report")
    if (type(read.get("io_bytes")) is not int or
            read["io_bytes"] != expected_bytes or
            type(read.get("total_ios")) is not int or
            read["total_ios"] != expected_bytes // PAGE):
        raise ValueError("fio verification did not read the complete writer range")
    write = job.get("write")
    if type(write) is not dict or type(write.get("io_bytes")) is not int or write["io_bytes"] != 0:
        raise ValueError("fio verification unexpectedly wrote data")
    return {
        "full_writer_readback_ok": True,
        "writer_verified_bytes": expected_bytes,
        "writer_verified_pages": expected_bytes // PAGE,
        "writer_verify_method": "fio-crc32c-sequential-read-diagnostic",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fio-json", required=True, type=Path)
    parser.add_argument("--expected-bytes", required=True, type=int)
    args = parser.parse_args()
    try:
        print(json.dumps(validate(args.fio_json, args.expected_bytes), sort_keys=True))
    except (OSError, ValueError, UnicodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
