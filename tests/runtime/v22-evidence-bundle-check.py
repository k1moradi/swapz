#!/usr/bin/env python3
"""Offline, fail-closed V2.2 measurement bundle consistency gate.

Checks one bounded JSONL artifact and its separately supplied manifest. This
does NOT authenticate a collector, a Git revision, a physical device, a kernel
drain, or a latency sample. Matching self-reported SHA-256 digests are not a
signature. No system/device access, benchmark, or side effect is performed.
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
_spec = importlib.util.spec_from_file_location(
    "swapz_v22_bundle_plateau", HERE / "v22-drain-plateau-analyze.py")
assert _spec is not None and _spec.loader is not None
plateau = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = plateau
_spec.loader.exec_module(plateau)

SCHEMA = "swapz-v22-evidence-bundle-v1"
MAX_MANIFEST_BYTES = 256 * 1024
SOURCE_SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
IDENTITY = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
ROOT_FIELDS = frozenset({
    "schema", "source_revision", "session_id", "collector_id",
    "lower_device_id", "backend", "profile", "evidence",
    "observations_sha256", "runs",
})
RUN_FIELDS = frozenset({
    "run_id", "line_sha256", "source_revision", "session_id",
    "collector_id", "lower_device_id", "backend", "profile", "evidence",
})
BINDINGS = (
    "source_revision", "session_id", "collector_id",
    "lower_device_id", "backend", "profile", "evidence",
)
# Note: session/collector/device ID are manifest assertions, not measurements
# embedded in the preexisting observation schema.
UNAUTHENTICATED = (
    "SELF-REPORTED OFFLINE METADATA ONLY; SHA-256 detects mismatches "
    "but does not authenticate collector, physical device or kernel drain"
)


def _read_regular(path: Path, limit: int) -> bytes:
    """Pin a no-symlink regular file and read at most limit+1 bytes."""
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_CLOEXEC"):
        raise ValueError("secure offline source descriptor pinning unavailable")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise ValueError("missing, empty, oversized or nonregular evidence file")
        chunks = []
        total = 0
        while total <= limit:
            chunk = os.read(fd, min(65536, limit + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        data = b"".join(chunks)
        after = os.fstat(fd)
        if (len(data) != before.st_size or len(data) > limit
                or (before.st_dev, before.st_ino, before.st_size,
                    before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size,
                    after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError("evidence file changed or exceeded its bounded length")
        return data
    finally:
        os.close(fd)


def _parse_json(raw: bytes) -> object:
    try:
        return json.loads(raw.decode("utf-8"),
                          object_pairs_hook=plateau._unique_object,
                          parse_constant=plateau._reject_constant)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ValueError(f"malformed or duplicate-field JSON: {exc}") from exc


def _identity(value: object, name: str, pattern=IDENTITY) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ValueError(f"invalid or unbound {name}")
    return value


def _check_metadata(manifest: object) -> dict[str, object]:
    if type(manifest) is not dict or set(manifest) != ROOT_FIELDS:
        raise ValueError("manifest has missing or extra fields")
    if manifest["schema"] != SCHEMA:
        raise ValueError("unsupported bundle schema")
    _identity(manifest["source_revision"], "source_revision", SOURCE_SHA)
    _identity(manifest["observations_sha256"], "observations_sha256", DIGEST)
    for key in BINDINGS[1:-1]:
        _identity(manifest[key], key)
    if type(manifest["evidence"]) is not str or manifest["evidence"] not in plateau.EVIDENCE:
        raise ValueError("invalid evidence classification")
    runs = manifest["runs"]
    if (type(runs) is not list or not 1 <= len(runs) <= plateau.MAX_OBSERVATIONS):
        raise ValueError("missing or oversized run inventory")
    return manifest


def check_bytes(observations: bytes, manifest_raw: bytes) -> dict[str, object]:
    """Validate exact artifact bytes, every run and one shared identity profile.

    This check is entirely offline. In particular it cannot corroborate the
    declared Git SHA against a trusted repo or prove that a collector actually
    measured the named lower device.
    """
    if not 0 < len(observations) <= plateau.MAX_INPUT_BYTES:
        raise ValueError("observation artifact is empty or oversized")
    if not 0 < len(manifest_raw) <= MAX_MANIFEST_BYTES:
        raise ValueError("manifest is empty or oversized")
    manifest = _check_metadata(_parse_json(manifest_raw))
    digest = hashlib.sha256(observations).hexdigest()
    if digest != manifest["observations_sha256"]:
        raise ValueError("observation bytes do not match manifest SHA-256")

    # Require exact LF-delimited JSONL. Each per-run digest covers the full
    # original record including its newline, never a reserialized object.
    if not observations.endswith(b"\n") or b"\r" in observations:
        raise ValueError("observation JSONL requires LF-terminated records")
    lines = observations.split(b"\n")[:-1]
    runs = manifest["runs"]
    if len(lines) != len(runs):
        raise ValueError("manifest inventory count differs from observation records")
    seen: set[str] = set()
    seen_digests: set[str] = set()
    for index, (line, run) in enumerate(zip(lines, runs), start=1):
        if not line or type(run) is not dict or set(run) != RUN_FIELDS:
            raise ValueError(f"run {index}: missing, blank or unexpected inventory fields")
        _identity(run["run_id"], "run_id")
        _identity(run["line_sha256"], "line_sha256", DIGEST)
        if run["run_id"] in seen:
            raise ValueError(f"run {index}: duplicate run ID")
        seen.add(run["run_id"])
        for key in BINDINGS:
            if run[key] != manifest[key]:
                raise ValueError(f"run {index}: conflicting {key} metadata")
        row = plateau.validate(_parse_json(line), index)
        if row["schema"] != plateau.SCHEMA_V2 and row["evidence"] != "synthetic":
            raise ValueError(f"run {index}: measured evidence requires exact-latency v2")
        for key in ("source_revision", "backend", "profile", "evidence", "run_id"):
            if row[key] != (run["run_id"] if key == "run_id" else manifest[key]):
                raise ValueError(f"run {index}: observation conflicts with bound {key}")
        actual = hashlib.sha256(line + b"\n").hexdigest()
        if run["line_sha256"] != actual:
            raise ValueError(f"run {index}: record bytes differ from manifest run digest")
        # Identical records cannot represent independent repeats even when
        # a manifest duplicates metadata. Distinct IDs are checked above.
        if actual in seen_digests:
            raise ValueError(f"run {index}: duplicate original record bytes")
        seen_digests.add(actual)

    return {
        "schema": "swapz-v22-evidence-bundle-assessment-v1",
        "status": "OFFLINE CONSISTENCY VERIFIED - NOT AUTHENTICATED",
        "source_revision": manifest["source_revision"],
        "session_id": manifest["session_id"],
        "collector_id": manifest["collector_id"],
        "lower_device_id": manifest["lower_device_id"],
        "observation_count": len(lines),
        "observations_sha256": digest,
        "authenticated_collector": False,
        "independent_device_identity_proved": False,
        "kernel_drain_proved": False,
        "physical_selection_authorized": False,
        "backing_release_authorized": False,
        "warning": UNAUTHENTICATED,
    }


def check_paths(observations: Path, manifest: Path) -> dict[str, object]:
    if observations == manifest:
        raise ValueError("manifest and observation files must be distinct")
    return check_bytes(_read_regular(observations, plateau.MAX_INPUT_BYTES),
                       _read_regular(manifest, MAX_MANIFEST_BYTES))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = check_paths(args.observations, args.manifest)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
