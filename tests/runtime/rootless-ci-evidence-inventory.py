#!/usr/bin/env python3
"""Fail-closed offline consistency inventory for GitHub rootless workflow metadata.

Input is caller-supplied, unauthenticated metadata. Success does not prove that
GitHub, the workflow runner, kernel operations, or benchmark data are genuine.
No network, subprocess, device, or cleanup operation occurs in this analyzer.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

SCHEMA = "swapz-rootless-ci-evidence-input-v1"
REPORT_SCHEMA = "swapz-rootless-ci-evidence-inventory-v1"
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_RUNS = 3
MAX_STEPS = 128
MAX_JOBS = 1
SOURCE_REVISION_HEX = re.compile(r"[0-9a-f]{40}\Z")

JOINT_STEPS = (
    "Guard rootless workflow safety gates and push-trigger coverage",
    "Separate-process pinned direct dd recall and attested readback",
    "Repeated separate-process readback admission qualification",
    "Strict fixture-bound direct dd role allowlist regression",
    "GNU provenance and worker build-record binding unit tests (synthetic only)",
    "Rootless authenticated fixture-release policy regression",
    "Rootless fixture-owner broker and evidence producer policy suite",
    "Independent rootless five-role broker and ambiguous-child contracts",
    "Rootless offline physical drain plateau evidence regression",
    "Offline V2.2 evidence bundle identity and artifact integrity policy",
)
WORKFLOWS = {
    "Rootless combined source qualification": (
        *JOINT_STEPS,
        "Refuse captured syscalls before running NBD selftest",
        "Recheck NBD selftest race in 25 separate processes",
    ),
    "Rootless teardown safety": (
        *JOINT_STEPS,
        "Rootless NBD and streaming fail-closed teardown mocks",
    ),
    "Rootless NBD source safety": (
        "Guard standalone rootless NBD source and syscall/stress gates",
        "Static syscall isolation gate (before any selftest)",
        "Run rootless NBD selftest",
        "Repeat rootless NBD selftest 25 times to catch socket races",
        "Rootless pidfd-owned NBD mock server lifecycle",
        "Rootless NBD teardown mock",
        "Rootless streaming teardown mock",
    ),
}
REQUIRED_WORKFLOW_NAMES = frozenset(WORKFLOWS)
UNQUALIFIED_CLAIMS = (
    "authenticated_collector",
    "independent_device_identity_proved",
    "kernel_drain_proved",
    "physical_selection_authorized",
    "backing_release_authorized",
    "production_qualified",
)


class EvidenceDenied(ValueError):
    """Offline data is malformed, incomplete, or self-contradictory."""


def _deny(message: str) -> None:
    raise EvidenceDenied(message)


def _exact_object(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        _deny(f"{label}: expected exact fields {sorted(keys)}")
    return value


def _positive_integer(value: Any, label: str) -> int:
    if type(value) is not int or not 0 < value < (1 << 63):
        _deny(f"{label}: expected positive signed 63-bit integer")
    return value


def _source_revision(value: Any, label: str) -> str:
    if type(value) is not str or SOURCE_REVISION_HEX.fullmatch(value) is None:
        _deny(f"{label}: expected 40 lowercase hex characters")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            _deny(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_bundle(path: Path) -> Any:
    """Read a bounded regular file by its retained descriptor; never follow links."""
    if not hasattr(os, "O_NOFOLLOW"):
        _deny("O_NOFOLLOW is required for file identity protection")
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_size <= 0 or before.st_size > MAX_INPUT_BYTES):
            _deny("input must be a bounded singly-linked regular file")
        remaining = before.st_size
        parts = []
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                _deny("unexpected input EOF")
            parts.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        signature = lambda value: (value.st_dev, value.st_ino, value.st_mode,
                                   value.st_nlink, value.st_size, value.st_mtime_ns,
                                   value.st_ctime_ns)
        if signature(before) != signature(after):
            _deny("input metadata changed during read")
        # Pinning a descriptor is not an authenticated immutable-file snapshot.
        try:
            return json.loads(b"".join(parts).decode("utf-8"),
                              object_pairs_hook=_unique_object,
                              parse_constant=lambda _: _deny("nonfinite JSON number"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise EvidenceDenied(f"invalid UTF-8 JSON: {error}") from error
    finally:
        os.close(descriptor)


def inventory(bundle: Any) -> dict[str, Any]:
    """Validate exact-source metadata with no privilege or trust elevation."""
    source = _exact_object(bundle, {"schema", "repository", "source_revision", "runs"}, "bundle")
    if source["schema"] != SCHEMA or source["repository"] != "k1moradi/swapz":
        _deny("unexpected schema or repository")
    source_revision = _source_revision(source["source_revision"], "source_revision")
    runs = source["runs"]
    if type(runs) is not list or len(runs) != MAX_RUNS:
        _deny("exactly three independent workflow runs are required")
    seen_run_ids: set[int] = set()
    seen_job_ids: set[int] = set()
    seen_names: set[str] = set()
    common_event: str | None = None
    recorded = []
    for run_index, raw_run in enumerate(runs):
        run = _exact_object(raw_run, {"id", "name", "head_sha", "run_attempt", "event",
                                      "status", "conclusion", "jobs"}, f"run[{run_index}]")
        name = run["name"]
        if type(name) is not str or name not in REQUIRED_WORKFLOW_NAMES or name in seen_names:
            _deny("unknown or duplicate workflow name")
        seen_names.add(name)
        run_id = _positive_integer(run["id"], "run.id")
        if run_id in seen_run_ids:
            _deny("duplicate workflow run ID")
        seen_run_ids.add(run_id)
        attempt = _positive_integer(run["run_attempt"], "run.run_attempt")
        if _source_revision(run["head_sha"], "run.head_sha") != source_revision:
            _deny("workflow source revision mismatch")
        if run["status"] != "completed" or run["conclusion"] != "success":
            _deny("workflow did not complete successfully")
        event = run["event"]
        if type(event) is not str or event not in ("push", "pull_request", "workflow_dispatch"):
            _deny("unknown workflow event")
        if common_event is None:
            common_event = event
        elif common_event != event:
            _deny("mixed workflow events")
        jobs = run["jobs"]
        if type(jobs) is not list or len(jobs) != MAX_JOBS:
            _deny("expected exactly one recorded qualification job")
        job = _exact_object(jobs[0], {"id", "run_id", "head_sha", "run_attempt", "name",
                                          "status", "conclusion", "steps"}, "job")
        job_id = _positive_integer(job["id"], "job.id")
        if job_id in seen_job_ids:
            _deny("duplicate job ID")
        seen_job_ids.add(job_id)
        if (_positive_integer(job["run_id"], "job.run_id") != run_id
                or _positive_integer(job["run_attempt"], "job.run_attempt") != attempt
                or _source_revision(job["head_sha"], "job.head_sha") != source_revision):
            _deny("job and workflow identity/attempt conflict")
        job_name = "one-revision" if name == "Rootless combined source qualification" else "source-only"
        if job["name"] != job_name or job["status"] != "completed" or job["conclusion"] != "success":
            _deny("unexpected or unsuccessful qualification job")
        steps = job["steps"]
        if type(steps) is not list or not steps or len(steps) > MAX_STEPS:
            _deny("missing or excessive job steps")
        completed_steps = {}
        for step_index, raw_step in enumerate(steps):
            step = _exact_object(raw_step, {"number", "name", "status", "conclusion"}, "step")
            if _positive_integer(step["number"], "step.number") != step_index + 1:
                _deny("job steps are missing, duplicated, or out of sequence")
            step_name = step["name"]
            if (type(step_name) is not str or not step_name or len(step_name) > 160
                    or step_name in completed_steps):
                _deny("duplicate or malformed job step name")
            if step["status"] != "completed":
                _deny(f"uncompleted job step: {step_name}")
            if step["conclusion"] not in ("success", "skipped"):
                _deny(f"failed or canceled job step: {step_name}")
            completed_steps[step_name] = step["conclusion"]
        mandatory = WORKFLOWS[name]
        if any(completed_steps.get(step_name) != "success" for step_name in mandatory):
            _deny(f"missing, skipped, or failed mandatory safety step: {name}")
        recorded.append({"name": name, "run_id": run_id, "job_id": job_id,
                         "attempt": attempt, "event": event,
                         "mandatory_steps_succeeded": len(mandatory),
                         "step_metadata_consistent": True})
    if seen_names != REQUIRED_WORKFLOW_NAMES:
        _deny("missing required workflow")
    return {
        "schema": REPORT_SCHEMA,
        "repository": "k1moradi/swapz",
        "source_revision": source_revision,
        "workflow_metadata_consistent": True,
        "source_authenticated": False,
        "step_execution_independently_attested": False,
        "repeat_counts_independently_attested": False,
        "limitations": "Caller-supplied GitHub-shaped metadata: no authenticated runner, logs, or production evidence",
        "qualification": {key: False for key in UNQUALIFIED_CLAIMS},
        "v22_strategy_and_batch_winner": "UNDETERMINED",
        "workflows": sorted(recorded, key=lambda item: item["name"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True,
                        help="Offline GitHub-shaped run/job/step JSON bundle")
    arguments = parser.parse_args()
    try:
        report = inventory(read_bundle(arguments.bundle))
    except (EvidenceDenied, OSError) as error:
        print(f"CI_EVIDENCE_INVENTORY_DENIED: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
