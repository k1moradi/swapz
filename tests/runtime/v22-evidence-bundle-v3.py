#!/usr/bin/env python3
"""Offline V3 sidecar-aware bundle consistency, never trusted attestation.

Validates a versioned manifest, exact JSONL bytes, and every referenced exact
latency sidecar using the V3 analyzer's bounded streaming verifier. The whole
bundle is user-supplied and unauthenticated; no device or privileged operation.
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
import sys

HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location(
    "swapz_v3_bundle_legacy", HERE / "v22-evidence-bundle-check.py",
)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("legacy bundle contract unavailable")
legacy = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = legacy
_SPEC.loader.exec_module(legacy)
plateau = legacy.plateau

SCHEMA = "swapz-v22-evidence-bundle-v2"
REPORT_SCHEMA = "swapz-v22-evidence-bundle-assessment-v2"
RUN_FIELDS = legacy.RUN_FIELDS | frozenset((
    "read_latency_sidecar", "read_latency_sha256", "read_latency_bytes",
))
BASENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
HASH_BYTES = 64 * 1024


def _signature(st: os.stat_result) -> tuple[int, ...]:
    return (st.st_dev, st.st_ino, st.st_mode, st.st_nlink,
            st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _safe_basename(path: Path, label: str) -> str:
    name = path.name
    if not isinstance(name, str) or BASENAME.fullmatch(name) is None or name in (".", ".."):
        raise ValueError(f"{label}: invalid exact-file basename")
    return name


def _read_file_at(directory_fd: int, name: str, limit: int) -> bytes:
    """Read a pinned bounded ordinary file without following a final symlink."""
    try:
        fd = os.open(name, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
                     | os.O_NOFOLLOW, dir_fd=directory_fd)
    except OSError as exc:
        raise ValueError(f"bundle file cannot be pinned: {exc}") from exc
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or not 0 < before.st_size <= limit):
            raise ValueError("bundle file must be bounded singly-linked regular input")
        remaining = before.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(fd, min(HASH_BYTES, remaining))
            if not chunk:
                raise ValueError("bundle file truncated during read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if (os.read(fd, 1) or _signature(before) != _signature(os.fstat(fd))):
            raise ValueError("bundle file grew or changed during pinned read")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _manifest(raw: object) -> dict[str, object]:
    if type(raw) is not dict or set(raw) != legacy.ROOT_FIELDS:
        raise ValueError("V3 bundle manifest has missing or extra fields")
    if raw["schema"] != SCHEMA:
        raise ValueError("unsupported V3 bundle schema")
    legacy._identity(raw["source_revision"], "source_revision", legacy.SOURCE_SHA)
    legacy._identity(raw["observations_sha256"], "observations_sha256", legacy.DIGEST)
    for key in legacy.BINDINGS[1:-1]:
        legacy._identity(raw[key], key)
    if type(raw["evidence"]) is not str or raw["evidence"] not in plateau.EVIDENCE:
        raise ValueError("invalid V3 evidence classification")
    if (type(raw["runs"]) is not list
            or not 1 <= len(raw["runs"]) <= plateau.MAX_OBSERVATIONS):
        raise ValueError("V3 bundle run inventory missing or oversized")
    return raw


def _verify(observation_data: bytes, manifest_data: bytes, directory_fd: int,
            protected_names: frozenset[str]) -> dict[str, object]:
    if not 0 < len(observation_data) <= plateau.MAX_INPUT_BYTES:
        raise ValueError("V3 observation artifact empty or oversized")
    if not 0 < len(manifest_data) <= legacy.MAX_MANIFEST_BYTES:
        raise ValueError("V3 manifest empty or oversized")
    metadata = _manifest(legacy._parse_json(manifest_data))
    observation_digest = hashlib.sha256(observation_data).hexdigest()
    if metadata["observations_sha256"] != observation_digest:
        raise ValueError("V3 observation bytes do not match manifest SHA-256")
    if not observation_data.endswith(b"\n") or b"\r" in observation_data:
        raise ValueError("V3 observation JSONL must be LF-terminated without CR")
    raw_lines = observation_data.split(b"\n")[:-1]
    if len(raw_lines) != len(metadata["runs"]) or any(not line for line in raw_lines):
        raise ValueError("V3 run inventory count or record framing mismatch")

    run_names: set[str] = set()
    record_hashes: set[str] = set()
    sidecar_names = set(protected_names)
    remaining_budget = plateau.MAX_TOTAL_SIDECAR_BYTES
    summary = []
    for index, (raw_line, entry) in enumerate(zip(raw_lines, metadata["runs"]), 1):
        if type(entry) is not dict or set(entry) != RUN_FIELDS:
            raise ValueError(f"run {index}: invalid V3 sidecar manifest fields")
        run_id = legacy._identity(entry["run_id"], "run_id")
        original_hash = legacy._identity(entry["line_sha256"], "line_sha256", legacy.DIGEST)
        if run_id in run_names:
            raise ValueError(f"run {index}: repeated run identity")
        run_names.add(run_id)
        for key in legacy.BINDINGS:
            if entry[key] != metadata[key]:
                raise ValueError(f"run {index}: conflicting {key} binding")
        row = plateau.validate(legacy._parse_json(raw_line), index)
        if row["schema"] != plateau.SCHEMA_V3:
            raise ValueError(f"run {index}: V3 sidecar evidence is mandatory")
        for key in ("source_revision", "backend", "profile", "evidence", "run_id"):
            expected = run_id if key == "run_id" else metadata[key]
            if row[key] != expected:
                raise ValueError(f"run {index}: row contradicts {key} manifest binding")
        digest = hashlib.sha256(raw_line + b"\n").hexdigest()
        if digest != original_hash:
            raise ValueError(f"run {index}: original record SHA-256 mismatch")
        if digest in record_hashes:
            raise ValueError(f"run {index}: duplicate original observation bytes")
        record_hashes.add(digest)
        sidecar = row["read_latency_sidecar"]
        if (entry["read_latency_sidecar"] != sidecar
                or entry["read_latency_sha256"] != row["read_latency_sha256"]):
            raise ValueError(f"run {index}: sidecar filename or digest binding mismatch")
        byte_count = entry["read_latency_bytes"]
        if (type(byte_count) is not int or byte_count <= 0
                or byte_count % 16 != 0 or byte_count > remaining_budget
                or byte_count > plateau.MAX_READ_COUNT * 16):
            raise ValueError(f"run {index}: invalid sidecar byte-length claim")
        actual_size = plateau._verify_v3_sidecar(
            row, index, directory_fd, remaining_budget, sidecar_names,
        )
        if actual_size != byte_count:
            raise ValueError(f"run {index}: sidecar byte-length binding mismatch")
        remaining_budget -= actual_size
        summary.append({
            "run_id": run_id,
            "line_sha256": digest,
            "read_latency_sidecar": sidecar,
            "read_latency_sha256": row["read_latency_sha256"],
            "read_latency_bytes": actual_size,
            "read_count_verified": row["read_count"],
            "exact_p99_ns_verified": row["read_p99_ns"],
        })
    return {
        "schema": REPORT_SCHEMA,
        "status": "OFFLINE V3 SIDECAR CONSISTENCY VERIFIED - NOT AUTHENTICATED",
        "source_revision": metadata["source_revision"],
        "session_id": metadata["session_id"],
        "collector_id": metadata["collector_id"],
        "lower_device_id": metadata["lower_device_id"],
        "backend": metadata["backend"],
        "profile": metadata["profile"],
        "evidence": metadata["evidence"],
        "observations_sha256": observation_digest,
        "observation_count": len(summary),
        "sidecar_bytes_verified": plateau.MAX_TOTAL_SIDECAR_BYTES - remaining_budget,
        "runs": summary,
        "authenticated_collector": False,
        "independent_device_identity_proved": False,
        "kernel_drain_proved": False,
        "physical_selection_authorized": False,
        "backing_release_authorized": False,
        "production_qualified": False,
        "v22_strategy_and_batch_winner": "UNDETERMINED",
        "warning": ("Caller-supplied hashes and identities are not signatures; "
                    "no independently authenticated collector or kernel evidence"),
    }


def check_paths(observations: Path, manifest: Path) -> dict[str, object]:
    """Both artifacts and their sidecars must reside in one pinned directory."""
    if observations.parent != manifest.parent:
        raise ValueError("V3 observation and manifest must share an exact directory")
    obs_name = _safe_basename(observations, "observations")
    manifest_name = _safe_basename(manifest, "manifest")
    if obs_name == manifest_name:
        raise ValueError("V3 observation and manifest must be different files")
    if not all(hasattr(os, name) for name in ("O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC")):
        raise ValueError("required POSIX directory pinning unavailable")
    try:
        fd = os.open(observations.parent, os.O_RDONLY | os.O_CLOEXEC
                     | os.O_NOFOLLOW | os.O_DIRECTORY)
    except OSError as exc:
        raise ValueError(f"V3 evidence directory cannot be pinned: {exc}") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISDIR(st.st_mode):
            raise ValueError("V3 evidence directory descriptor is not a directory")
        source = _read_file_at(fd, obs_name, plateau.MAX_INPUT_BYTES)
        metadata = _read_file_at(fd, manifest_name, legacy.MAX_MANIFEST_BYTES)
        return _verify(source, metadata, fd, frozenset((obs_name, manifest_name)))
    finally:
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        assessment = check_paths(args.observations, args.manifest)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(assessment, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
