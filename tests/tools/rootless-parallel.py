#!/usr/bin/env python3
"""Private bounded executor for specifically reviewed, adjacent rootless phases.

The parent Bash harness remains the sole progress/verdict publisher. Workers
own separate process groups and private regular output files; no worker emits
progress markers directly. An observed failure prevents dispatch of new jobs,
but already-running jobs finish (or time out) so their cleanup is not skipped.
"""
import argparse
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
policy_spec = importlib.util.spec_from_file_location(
    "swapz_rootless_resource_policy", ROOT / "tests/tools/rootless-resource-policy.py")
if policy_spec is None or policy_spec.loader is None:
    raise RuntimeError("rootless resource policy is unavailable")
resource_policy = importlib.util.module_from_spec(policy_spec)
policy_spec.loader.exec_module(resource_policy)

# Source-controlled commands only. Arbitrary shell strings and command
# arguments from the environment must never be accepted as worker jobs.
GROUPS = {
    "initial": (
        ("tests/runtime/native/source-contract-test.py",
         ("python3", "-B", "tests/runtime/native/source-contract-test.py", "-v")),
        ("tests/runtime/native/userspace/swapzctl-active-swap-provenance-test.py",
         ("python3", "-B",
          "tests/runtime/native/userspace/swapzctl-active-swap-provenance-test.py",
          "-v")),
    ),
    "readiness": (
        ("tests/runtime/native/production-readiness-test.py",
         ("python3", "-B", "tests/runtime/native/production-readiness-test.py", "-v")),
        ("tests/runtime/native/rootless-direct-evidence-test.py",
         ("python3", "-B", "tests/runtime/native/rootless-direct-evidence-test.py",
          "-v")),
    ),
    "syntax": tuple(
        (f"bash syntax {Path(path).name}", ("bash", "-n", path))
        for path in resource_policy.SYNTAX_SCRIPTS
    ),
}

MAX_WORKER_SECONDS = 900
POLL_INTERVAL_SECONDS = 0.02


def validated_group(group_name, harness_source):
    """No execution unless the full harness and selected pairwise claims agree."""
    if not resource_policy.ROOTLESS_PARALLEL_EXECUTION_ENABLED:
        raise ValueError("parallel rootless execution is disabled")
    claims = resource_policy.audit_harness(harness_source)
    if group_name not in GROUPS:
        raise ValueError("unreviewed parallel rootless group")
    tasks = GROUPS[group_name]
    if len(tasks) < 2 or len({label for label, _ in tasks}) != len(tasks):
        raise ValueError("invalid rootless group")
    for index, (label, _) in enumerate(tasks):
        if claims[label].classification == "serial":
            raise ValueError("serial rootless phase included in worker group")
        for other_label, _ in tasks[:index]:
            if resource_policy.potential_conflicts(label, other_label, claims):
                raise ValueError("conflicting rootless worker resources")
    return tasks


def _private_file(directory, filename):
    """Create an exclusively owned output file with no symlink traversal."""
    descriptor = os.open(directory / filename,
                         os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                         0o600)
    return os.fdopen(descriptor, "wb")


def _owned_worker_group_exists(process):
    """Check the original worker group, including surviving descendants."""
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return False
    return True


def _stop_owned_worker(process):
    """Stop the entire owned group even when its leader exits before children."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        # Reap a completed leader before checking for other group members.
        process.poll()
        if not _owned_worker_group_exists(process):
            break
        time.sleep(POLL_INTERVAL_SECONDS)
    process.poll()
    if _owned_worker_group_exists(process):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=5)


def execute_group(directory, tasks, *, jobs, timeout_seconds=MAX_WORKER_SECONDS,
                  poll_seconds=POLL_INTERVAL_SECONDS):
    """Write one private, ordered status record for each launched worker.

    The coordinator owns/reaps every Popen. Failure blocks new launches, while
    active workers get their normal cleanup window unless their bound expires.
    Duration records describe *per-worker elapsed* seconds, not the group wall.
    """
    if jobs != 2 or timeout_seconds <= 0 or poll_seconds <= 0:
        raise ValueError("invalid bounded rootless worker configuration")
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("rootless output directory must be a real directory")
    active = {}
    next_index = 0
    failed = False

    def record(index, exit_code, elapsed_seconds, *, cleanup_failure=False):
        with _private_file(directory, f"worker-{index}.result") as output:
            output.write(
                f"{exit_code} {elapsed_seconds} {int(cleanup_failure)}\n".encode("ascii"))

    try:
        while next_index < len(tasks) or active:
            while not failed and next_index < len(tasks) and len(active) < jobs:
                index = next_index
                label, command = tasks[index]
                del label
                output_file = _private_file(directory, f"worker-{index}.stdout")
                try:
                    error_file = _private_file(directory, f"worker-{index}.stderr")
                except BaseException:
                    output_file.close()
                    raise
                try:
                    # A test may launch a nested Python interpreter without
                    # -B. Suppress all bytecode writes so concurrent workers
                    # never race on the inherited shared build/python-cache.
                    worker_environment = os.environ.copy()
                    worker_environment["PYTHONDONTWRITEBYTECODE"] = "1"
                    process = subprocess.Popen(
                        command, cwd=ROOT, stdin=subprocess.DEVNULL,
                        stdout=output_file, stderr=error_file,
                        env=worker_environment,
                        close_fds=True, start_new_session=True)
                finally:
                    output_file.close()
                    error_file.close()
                active[index] = (process, time.monotonic())
                next_index += 1

            for index, (process, started_at) in tuple(active.items()):
                exit_code = process.poll()
                elapsed_seconds = time.monotonic() - started_at
                timed_out = exit_code is None and elapsed_seconds >= timeout_seconds
                if timed_out:
                    _stop_owned_worker(process)
                    exit_code = 124
                if exit_code is None:
                    continue
                process.wait()
                cleanup_failure = False
                if not timed_out and _owned_worker_group_exists(process):
                    # A zero-exit worker must not advertise PASS while its
                    # process-group descendants still own live resources.
                    _stop_owned_worker(process)
                    if exit_code == 0:
                        exit_code = 125
                        cleanup_failure = True
                if exit_code < 0:
                    exit_code = 128 - exit_code
                # The Bash parent and its error reporter accept only small
                # nonnegative decimal statuses and integer timing records.
                exit_code = min(exit_code, 255)
                record(index, exit_code, max(0, int(elapsed_seconds)),
                       cleanup_failure=cleanup_failure)
                if exit_code:
                    failed = True
                del active[index]
            if active:
                time.sleep(poll_seconds)
            if failed and not active:
                break
        return 1 if failed else 0
    finally:
        for process, _ in active.values():
            _stop_owned_worker(process)
            # Propagate inability to reap rather than silently claiming safety.


def _handle_interruption(number, _frame):
    # Do not leave detached worker sessions behind when the coordinator is
    # signalled while the Bash parent is cancelling its phase.
    raise InterruptedError(f"signal_{number}")


def main():
    signal.signal(signal.SIGINT, _handle_interruption)
    signal.signal(signal.SIGTERM, _handle_interruption)
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=tuple(GROUPS), required=True)
    parser.add_argument("--jobs", choices=(2,), type=int, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        harness_source = (ROOT / "tests/tools/test-rootless.sh").read_text(
            encoding="utf-8")
        tasks = validated_group(args.group, harness_source)
        return execute_group(args.output_directory, tasks, jobs=args.jobs)
    except (OSError, ValueError, subprocess.SubprocessError,
            InterruptedError) as error:
        print(f"BLOCKED: rootless worker setup failed ({type(error).__name__})",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
