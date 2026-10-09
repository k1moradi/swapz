#!/usr/bin/env python3
"""Classify already-denied rootless recall sessions without granting authority.

The input is an untrusted offline JSONL transcription of synthetic diagnostic
records, not a service protocol or authenticated log. No worker, kernel, device,
cleanup, network, or subprocess operations are performed by this classifier.
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
import sys
from typing import Any

SCHEMA = "swapz-rootless-recall-denial-v1"
REPORT_SCHEMA = "swapz-rootless-recall-denial-report-v1"
MAX_INPUT_BYTES = 1024 * 1024
MAX_RECORDS = 2048
SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
REVISION = re.compile(r"[0-9a-f]{40}\Z")
ROLES = frozenset(("writer", "a", "b", "a2", "b2"))
PHASES = frozenset(("LAUNCH", "READY", "WAIT", "READBACK", "WRITER_READY",
                    "CHANNEL", "PIDFD", "FINALIZE", "STOP"))
DENIAL_STATUSES = frozenset((
    "launch_failure", "supervisor_contract_failure", "admission_closed",
    "lifecycle_failure", "workers_unresolved", "protocol_error",
    "shutdown_with_lifecycle_failure", "denied", "channel_failure",
    "timeout", "error",
))
REQUIRED_FIELDS = frozenset((
    "schema", "source_revision", "session_id", "role", "phase", "status",
    "error", "service_returncode", "preserve_backing", "cleanup_allowed",
))


class TelemetryDenied(ValueError):
    """Input evidence is incomplete or unsafe to summarize as a denial."""


def _deny(message: str) -> None:
    raise TelemetryDenied(message)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _deny(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _reject_nonfinite(_value: str) -> None:
    _deny("nonfinite JSON values are not allowed")


def _file_signature(metadata: os.stat_result) -> tuple[int, ...]:
    return (metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_nlink,
            metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)


def read_observations(path: Path) -> bytes:
    """Retain one regular-file descriptor; never follow a path substitution."""
    if not hasattr(os, "O_NOFOLLOW"):
        _deny("symlink-safe input opening unavailable")
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or not 0 < before.st_size <= MAX_INPUT_BYTES):
            _deny("input must be a nonempty, singly-linked, bounded regular file")
        remaining = before.st_size
        chunks: list[bytes] = []
        while remaining:
            block = os.read(descriptor, min(65536, remaining))
            if not block:
                _deny("input became truncated during read")
            chunks.append(block)
            remaining -= len(block)
        if _file_signature(before) != _file_signature(os.fstat(descriptor)):
            _deny("input metadata changed during read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _validate_record(raw: Any, index: int) -> dict[str, Any]:
    if type(raw) is not dict or raw.keys() != REQUIRED_FIELDS:
        _deny(f"row {index}: unexpected or missing diagnostic fields")
    if raw["schema"] != SCHEMA:
        _deny(f"row {index}: unknown diagnostic schema")
    source_revision = raw["source_revision"]
    session_id = raw["session_id"]
    if type(source_revision) is not str or REVISION.fullmatch(source_revision) is None:
        _deny(f"row {index}: invalid exact source revision")
    if type(session_id) is not str or SESSION_ID.fullmatch(session_id) is None:
        _deny(f"row {index}: invalid session identifier")
    phase = raw["phase"]
    role = raw["role"]
    status = raw["status"]
    error = raw["error"]
    if type(phase) is not str or phase not in PHASES:
        _deny(f"row {index}: unknown failure phase")
    if (role is not None and (type(role) is not str or role not in ROLES)):
        _deny(f"row {index}: unknown failure role")
    if phase in ("LAUNCH", "READY", "WAIT", "READBACK", "WRITER_READY") and role is None:
        _deny(f"row {index}: missing bound worker role")
    if phase == "WRITER_READY" and role != "writer":
        _deny(f"row {index}: synthetic writer readiness has a different role")
    if phase == "READBACK" and role == "writer":
        _deny(f"row {index}: writer cannot supply reader readback evidence")
    if type(status) is not str or status not in DENIAL_STATUSES:
        _deny(f"row {index}: success/unknown status cannot count as a denial")
    if (type(error) is not str or not 0 < len(error) <= 256
            or any(ord(character) < 32 or ord(character) == 127 for character in error)):
        _deny(f"row {index}: missing, oversized or control-character diagnostic")
    returncode = raw["service_returncode"]
    if returncode is not None and (type(returncode) is not int or not -255 <= returncode <= 255):
        _deny(f"row {index}: malformed service exit code")
    if raw["preserve_backing"] is not True or raw["cleanup_allowed"] is not False:
        _deny(f"row {index}: positive or contradictory cleanup assertion")
    return raw


def _classify(record: dict[str, Any]) -> str:
    """Use bounded typed failure phase; text narrows only the readback subtype."""
    phase = record["phase"]
    if phase == "READBACK":
        lower_error = record["error"].lower()
        if lower_error.startswith(("pinned readback rejected:",
                                   "pinned readback does not match",
                                   "readback attestation digest does not match")):
            return "readback_integrity_denial"
        return "readback_other_denial"
    return {
        "LAUNCH": "launch_admission_denial",
        "READY": "ready_confirmation_denial",
        "WAIT": "wait_or_reap_denial",
        "WRITER_READY": "synthetic_writer_readiness_denial",
        "CHANNEL": "channel_or_service_denial",
        "PIDFD": "pidfd_ownership_denial",
        "FINALIZE": "finalization_denial",
        "STOP": "stop_or_reap_denial",
    }[phase]


def analyze(data: bytes) -> dict[str, Any]:
    if type(data) is not bytes or not 0 < len(data) <= MAX_INPUT_BYTES:
        _deny("invalid bounded diagnostic bytes")
    if not data.endswith(b"\n") or b"\r" in data:
        _deny("diagnostics must be LF-terminated with no CR")
    lines = data.split(b"\n")[:-1]
    if not 0 < len(lines) <= MAX_RECORDS or any(not line for line in lines):
        _deny("empty lines or an invalid diagnostic count")
    sessions: set[str] = set()
    source_revision: str | None = None
    categorized: list[dict[str, str | None]] = []
    counts: Counter[str] = Counter()
    for index, line in enumerate(lines, 1):
        try:
            row = json.loads(line.decode("utf-8"), object_pairs_hook=_unique_object,
                             parse_constant=_reject_nonfinite)
        except (ValueError, UnicodeError) as error:
            raise TelemetryDenied(f"row {index}: invalid diagnostic JSON: {error}") from error
        record = _validate_record(row, index)
        if source_revision is None:
            source_revision = record["source_revision"]
        elif record["source_revision"] != source_revision:
            _deny("mixed executable source revisions")
        if record["session_id"] in sessions:
            _deny("duplicate or replayed session diagnostic")
        sessions.add(record["session_id"])
        category = _classify(record)
        counts[category] += 1
        categorized.append({
            "session_id": record["session_id"], "role": record["role"],
            "phase": record["phase"], "category": category,
        })
    categorized.sort(key=lambda item: item["session_id"])
    return {
        "schema": REPORT_SCHEMA,
        "source_revision": source_revision,
        "observations_sha256": hashlib.sha256(data).hexdigest(),
        "denied_session_count": len(sessions),
        "categories": dict(sorted(counts.items())),
        "sessions": categorized,
        "source_authenticated": False,
        "kernel_drain_proved": False,
        "physical_selection_authorized": False,
        "backing_release_authorized": False,
        "cleanup_authorized": False,
        "production_qualified": False,
        "v22_strategy_and_batch_winner": "UNDETERMINED",
        "interpretation": "synthetic failure-classification only; input assertions are not authenticated observations",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = analyze(read_observations(args.observations))
    except (TelemetryDenied, OSError) as error:
        print(f"ROOTLESS_RECALL_TELEMETRY_DENIED: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
