#!/usr/bin/env python3
"""Convert exact fio reader CLAT samples to the existing V3 RLE sidecar.

Source-only conversion, not independent proof of read provenance, lower-device
attribution, complete drain, quiescence or a qualified benchmark winner.
The live benchmark owns its per-case log and output directory.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_LOG_BYTES = 64 * 1024 * 1024
MAX_READ_SAMPLES = 500_000
MAX_LATENCY_NS = 10**13
LATENCY_RECORD = struct.Struct("!QQ")
SIDECAR_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.latbin\Z")


def _source_lines(path: Path, size_limit: int, line_limit: int):
    """Read a bounded ordinary log using a pinned non-symlink descriptor."""
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or not 0 < before.st_size <= size_limit):
            raise ValueError("input must be a bounded singly-linked regular file")
        with os.fdopen(descriptor, "r", encoding="utf-8", newline="") as stream:
            descriptor = -1  # stream now owns the descriptor
            bytes_read = 0
            while True:
                line = stream.readline(line_limit + 1)
                if not line:
                    break
                if len(line) > line_limit:
                    raise ValueError("input log line exceeds bounded length")
                bytes_read += len(line.encode("utf-8"))
                if bytes_read > size_limit:
                    raise ValueError("input grew beyond bounded size")
                yield line
            after = os.fstat(stream.fileno())
            signature = lambda state: (state.st_dev, state.st_ino, state.st_size,
                                       state.st_mtime_ns, state.st_ctime_ns,
                                       state.st_nlink, state.st_mode)
            if signature(before) != signature(after):
                raise ValueError("input changed during read")
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _fio_read_count(path: Path) -> int:
    raw = "".join(_source_lines(path, MAX_JSON_BYTES, MAX_JSON_BYTES))
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate fio JSON field")
            result[key] = value
        return result
    root = json.loads(raw, object_pairs_hook=reject_duplicates,
                      parse_constant=lambda value: (_ for _ in ()).throw(
                          ValueError(f"nonfinite fio JSON value: {value}")))
    if type(root) is not dict or type(root.get("jobs")) is not list:
        raise ValueError("fio JSON missing jobs")
    readers = [job for job in root["jobs"]
               if type(job) is dict and job.get("jobname") == "reader"]
    if len(readers) != 1 or type(readers[0].get("read")) is not dict:
        raise ValueError("fio JSON requires exactly one reader job")
    count = readers[0]["read"].get("total_ios")
    if type(count) is not int or not 1 <= count <= MAX_READ_SAMPLES:
        raise ValueError("fio reader total_ios missing or exceeds bounded sample limit")
    return count


def collect(fio_json: Path, fio_clat_log: Path, sidecar: Path) -> dict[str, object]:
    """Reject incomplete logs before publishing a unique exact-latency sidecar."""
    if SIDECAR_NAME.fullmatch(sidecar.name) is None:
        raise ValueError("V3 output filename must be a safe .latbin basename")
    expected = _fio_read_count(fio_json)
    frequencies: Counter[int] = Counter()
    observed = 0
    last_timestamp = -1
    for line in _source_lines(fio_clat_log, MAX_LOG_BYTES, 256):
        fields = line.strip().split(",")
        if not 4 <= len(fields) <= 7 or any(
                re.fullmatch(r"[0-9]+", field.strip()) is None for field in fields):
            raise ValueError("malformed or aggregated fio CLAT log entry")
        timestamp, latency, direction, block_size = map(int, fields[:4])
        if (timestamp < last_timestamp or not 0 < latency <= MAX_LATENCY_NS
                or direction != 0 or block_size != 4096):
            raise ValueError("fio CLAT entry not a monotonic positive 4 KiB read sample")
        last_timestamp = timestamp
        frequencies[latency] += 1
        observed += 1
        if observed > expected:
            raise ValueError("fio CLAT log contains more samples than fio JSON read I/Os")
    if observed != expected:
        raise ValueError("fio CLAT log sample count differs from fio JSON read I/Os")

    rank = (99 * observed + 99) // 100
    total = 0
    p99 = None
    payload = bytearray()
    for latency, count in sorted(frequencies.items()):
        total += count
        if p99 is None and total >= rank:
            p99 = latency
        payload.extend(LATENCY_RECORD.pack(latency, count))
    if p99 is None or total != observed:
        raise ValueError("invalid exact reader latency distribution")

    # Never replace a preexisting artifact; a partial new write is removed.
    descriptor = os.open(sidecar, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                         | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        sidecar.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return {
        "read_count": observed,
        "read_p99_ns": p99,
        "read_latency_sidecar": sidecar.name,
        "read_latency_sha256": hashlib.sha256(payload).hexdigest(),
        "read_latency_bytes": len(payload),
        "read_latency_source": "fio-clat-log-only-NOT-independent-attestation",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fio-json", required=True, type=Path)
    parser.add_argument("--fio-clat-log", required=True, type=Path)
    parser.add_argument("--sidecar", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(collect(args.fio_json, args.fio_clat_log, args.sidecar),
                         sort_keys=True))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
