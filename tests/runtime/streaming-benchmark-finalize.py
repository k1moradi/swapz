#!/usr/bin/env python3
"""Bounded, rootless SOURCE-REPORTED finalization record for a benchmark sweep.

The privileged streaming benchmark alone must invoke --write, from its EXIT
handler, *after* successful reporter completion AND safe owned-resource teardown.
The record links the exact JSONL bytes and case count to that completion path.
Anyone able to edit artifacts can forge it: it is NEVER independent evidence
of kernel quiescence, device ownership, physical drain or benchmark qualification.

The --check operation reads ordinary files only, without subprocess or devices.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat

HERE = Path(__file__).resolve().parent
NAME = "completed-sweep.json"
SCHEMA = "swapz-v22-benchmark-finalization-v1"
STATE = "source-runner-reported-successful-owned-resource-teardown"
EVIDENCE = "SOURCE_REPORTED_NO_INDEPENDENT_DEVICE_ATTESTATION"
MAX_MARKER_BYTES = 2048
MAX_OBSERVATIONS = 128
MAX_RESULTS_BYTES = 2 * 1024 * 1024


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate finalization JSON key")
        out[key] = value
    return out


def _reject_constant(value: str) -> object:
    raise ValueError(f"nonfinite JSON value: {value}")


def _read_pinned_regular(fd: int, limit: int) -> bytes:
    before = os.fstat(fd)
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
            not 0 < before.st_size <= limit):
        raise ValueError("finalization input must be a nonempty singly-linked bounded file")
    raw = bytearray()
    while len(raw) < before.st_size:
        chunk = os.read(fd, min(65536, before.st_size - len(raw)))
        if not chunk:
            break
        raw.extend(chunk)
    after = os.fstat(fd)
    identity = lambda st: (st.st_dev, st.st_ino, st.st_mode, st.st_nlink,
                           st.st_size, st.st_mtime_ns, st.st_ctime_ns)
    if (len(raw) != before.st_size or os.read(fd, 1) or
            identity(before) != identity(after)):
        raise ValueError("finalization input changed during read")
    return bytes(raw)


def _read_at(dirfd: int, name: str, limit: int) -> bytes:
    if name not in ("results.jsonl", NAME):
        raise ValueError("unexpected diagnostic artifact basename")
    fd = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW |
                 os.O_CLOEXEC, dir_fd=dirfd)
    try:
        return _read_pinned_regular(fd, limit)
    finally:
        os.close(fd)


def _dirfd(directory: Path) -> int:
    return os.open(directory, os.O_RDONLY | os.O_DIRECTORY |
                   os.O_NOFOLLOW | os.O_CLOEXEC)


def _check_rows(raw: bytes, expected_count: int, expected_backend: str) -> None:
    if (type(expected_count) is not int or
            not 1 <= expected_count <= MAX_OBSERVATIONS):
        raise ValueError("invalid finalization case count")
    if (type(expected_backend) is not str or
            re.fullmatch(r"[A-Za-z0-9._-]{1,128}", expected_backend) is None):
        raise ValueError("invalid finalization backend")
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError("results.jsonl must be UTF-8") from exc
    lines = text.splitlines(keepends=True)
    if (len(lines) != expected_count or
            any(not line.endswith("\n") or not line.strip() for line in lines)):
        raise ValueError("incomplete, malformed, or unexpected sweep row count")
    for i, line in enumerate(lines, 1):
        row = json.loads(line, object_pairs_hook=_object,
                         parse_constant=_reject_constant)
        if type(row) is not dict or row.get("backend") != expected_backend:
            raise ValueError(f"line {i}: finalization backend differs from actual results")


def _payload(raw: bytes, case_count: int, backend: str) -> dict[str, object]:
    _check_rows(raw, case_count, backend)
    return {
        "schema": SCHEMA,
        "state": STATE,
        "evidence": EVIDENCE,
        "results_file": "results.jsonl",
        "results_sha256": hashlib.sha256(raw).hexdigest(),
        "results_bytes": len(raw),
        "completed_cases": case_count,
        "backend": backend,
        "qualified_winner": None,
    }


def write_marker(results_path: Path, marker_path: Path,
                 case_count: int, backend: str) -> dict[str, object]:
    """Must be called only after the runner has completed safe teardown."""
    if results_path.name != "results.jsonl" or marker_path.name != NAME:
        raise ValueError("unsafe finalization filenames")
    if results_path.parent != marker_path.parent:
        raise ValueError("finalization marker and results must share a directory")
    dirfd = _dirfd(results_path.parent)
    try:
        raw = _read_at(dirfd, "results.jsonl", MAX_RESULTS_BYTES)
        record = _payload(raw, case_count, backend)
        content = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
        if len(content) > MAX_MARKER_BYTES:
            raise ValueError("oversized finalization marker")
        fd = os.open(NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=dirfd)
        try:
            with os.fdopen(fd, "wb", closefd=False) as output:
                output.write(content)
                output.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
        return record
    finally:
        os.close(dirfd)


def check_marker(raw_results: bytes, directory_fd: int,
                 expected_cases: int, backend: str) -> dict[str, object]:
    """Only source-reported completion; NOT independently trusted cleanup."""
    raw_marker = _read_at(directory_fd, NAME, MAX_MARKER_BYTES)
    try:
        record = json.loads(raw_marker, object_pairs_hook=_object,
                            parse_constant=_reject_constant)
    except (UnicodeError, ValueError) as exc:
        raise ValueError(f"malformed finalization marker: {exc}") from exc
    if type(record) is not dict:
        raise ValueError("finalization marker is not an object")
    expected = _payload(raw_results, expected_cases, backend)
    if record != expected:
        raise ValueError("finalization marker missing, contradictory, or not bound to exact results")
    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true",
                       help="runner-only creation, after verified owned teardown")
    group.add_argument("--check", action="store_true",
                       help="read-only source-reported finalization validation")
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--marker", type=Path)
    parser.add_argument("--expected-cases", required=True, type=int)
    parser.add_argument("--backend", required=True)
    args = parser.parse_args()
    try:
        if args.results.name != "results.jsonl":
            raise ValueError("results filename must be results.jsonl")
        if args.write:
            marker = args.marker or args.results.with_name(NAME)
            record = write_marker(args.results, marker, args.expected_cases, args.backend)
        else:
            if args.marker is not None and args.marker != args.results.with_name(NAME):
                raise ValueError("unexpected finalization marker path")
            fd = _dirfd(args.results.parent)
            try:
                raw = _read_at(fd, "results.jsonl", MAX_RESULTS_BYTES)
                record = check_marker(raw, fd, args.expected_cases, args.backend)
            finally:
                os.close(fd)
        print(json.dumps(record, sort_keys=True))
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
