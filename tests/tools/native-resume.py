#!/usr/bin/env python3
"""Development-only native-suite PASS checkpoints; native compilation stays in Make.

Each Make target owns a distinct checkpoint file. It runs with the same test
order and inherits the rootless reporter's stdout/stderr; no device is touched
by this driver. A missing/mismatched context always executes the full suite.
"""
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "build/tests/native"
SUITES = {
    "mapping": (
        "zero-write-elision", "mapping-authority", "authority-throughput",
        "transaction-publication", "write-verification",
        "dead-segment-reclamation", "raw-discard", "online-packing",
        "randomized-authority"),
    "lower-io": (
        "flush-ordering", "lower-write-aggregation", "window-policy",
        "preparation-slots", "preparation-codec-result",
        "preparation-publication-lifetime", "lane-gap"),
}
MAX_NATIVE_FILE_BYTES = 512 * 1024 * 1024


def verified_native_sha256(path, *, executable):
    """Hash the owned regular file without following links or directory swaps."""
    try:
        for directory in (ROOT / "build", ROOT / "build/tests", NATIVE):
            metadata = directory.lstat()
            if (not stat.S_ISDIR(metadata.st_mode) or
                    metadata.st_uid != os.geteuid()):
                return None
        descriptor = os.open(
            path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or
                before.st_uid != os.geteuid() or
                before.st_nlink != 1 or
                not 0 < before.st_size <= MAX_NATIVE_FILE_BYTES or
                (executable and before.st_mode & 0o111 == 0)):
            return None
        digest = hashlib.sha256()
        remaining = before.st_size
        while remaining:
            block = os.read(descriptor, min(256 * 1024, remaining))
            if not block:
                return None
            digest.update(block)
            remaining -= len(block)
        after = os.fstat(descriptor)
        if ((before.st_ino, before.st_dev, before.st_size,
             before.st_mode, before.st_mtime_ns, before.st_ctime_ns) !=
            (after.st_ino, after.st_dev, after.st_size,
             after.st_mode, after.st_mtime_ns, after.st_ctime_ns)):
            return None
        return digest.hexdigest()
    except OSError:
        return None
    finally:
        os.close(descriptor)


def open_owned_native_executable(path):
    """Pin the owned native inode before executing it; never follow links.

    The caller owns the returned descriptor and must close it. Executing
    /proc/self/fd/<descriptor> with pass_fds prevents a pathname swap between
    the ownership check and exec from launching a different binary.
    """
    descriptor = -1
    try:
        for directory in (ROOT / "build", ROOT / "build/tests", NATIVE):
            metadata = directory.lstat()
            if (not stat.S_ISDIR(metadata.st_mode) or
                    metadata.st_uid != os.geteuid()):
                return -1
        descriptor = os.open(
            path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        metadata = os.fstat(descriptor)
        if (not stat.S_ISREG(metadata.st_mode) or
                metadata.st_uid != os.geteuid() or
                metadata.st_nlink != 1 or
                metadata.st_mode & 0o111 == 0):
            os.close(descriptor)
            return -1
        return descriptor
    except OSError:
        if descriptor >= 0:
            os.close(descriptor)
        return -1


def current_native_context(suite, tested_source, kdir, runner):
    """Bind source/host + Make-built executable bytes and compiler stamp."""
    if (re.fullmatch(r"[0-9a-f]{40}", tested_source or "") is None or
            not isinstance(kdir, str) or not kdir or
            runner.git_sha() != tested_source or
            runner.tracked_source_checkout_preflight() is not None):
        return None
    report = {
        "tested_commit_sha": tested_source,
        "host_identity": runner.report_host_identity(),
        "kernel_release": os.uname().release,
    }
    context = runner.development_resume_context(report, kdir)
    if context is None:
        return None
    identities = {}
    for binary in SUITES[suite]:
        digest = verified_native_sha256(NATIVE / binary, executable=True)
        if digest is None:
            return None
        identities[binary] = digest
    configuration = verified_native_sha256(
        NATIVE / "native-compiler-configuration", executable=False)
    if configuration is None:
        return None
    return {"parent": context, "suite": suite,
            "compiler_configuration_sha256": configuration,
            "executables_sha256": identities}


def run_native_suite(suite, executables, *, mode=None,
                     tested_source=None, kdir=None, runner=None):
    """Run every target in original order, unless private PASS matches bytes."""
    context = None
    if mode in ("record", "resume") and runner is not None:
        context = current_native_context(suite, tested_source, kdir, runner)
    if mode == "resume" and context is not None:
        if (runner.read_development_resume_checkpoint(
                context, native_suite=suite) == [suite] and
                # Revalidate after opening the checkpoint: a concurrent
                # rebuild must not change the executable bytes while the
                # PASS record is being consulted and still be skipped.
                context == current_native_context(
                    suite, tested_source, kdir, runner)):
            # Only this source-controlled marker is accepted by the parent.
            print("ROOTLESS_NATIVE_RESUME suite=" + suite + " state=REUSED",
                  flush=True)
            return 0

    # No selector is inherited by child tests which may create nested Make.
    child_env = os.environ.copy()
    for variable in ("SWAPZ_NATIVE_CACHE_MODE", "SWAPZ_NATIVE_CACHE_KDIR",
                     "RESUME"):
        child_env.pop(variable, None)
    for binary in executables:
        descriptor = open_owned_native_executable(Path(binary))
        if descriptor < 0:
            print(f"FAIL: native test-{suite} binary={Path(binary).name} "
                  "reason=untrusted_executable", file=sys.stderr, flush=True)
            return 126
        try:
            try:
                # Preserve the tests/suites cwd and original argv[0]. Run
                # the checked inode, not a pathname that could be replaced
                # between the ownership check and subprocess execution.
                completed = subprocess.run(
                    [binary], executable=f"/proc/self/fd/{descriptor}",
                    pass_fds=(descriptor,), env=child_env, check=False)
                exit_code = completed.returncode
            except OSError as error:
                # Shell-compatible exit classes without exporting an
                # arbitrary host path or exception to the operator.
                failure_exit = (
                    127 if isinstance(error, FileNotFoundError) else
                    126 if isinstance(error, PermissionError) else 1)
                print(f"FAIL: native test-{suite} binary={Path(binary).name} "
                      f"reason=execution_unavailable exit={failure_exit}",
                      file=sys.stderr, flush=True)
                return failure_exit
        finally:
            os.close(descriptor)
        if exit_code:
            public_exit = 128 - exit_code if exit_code < 0 else exit_code
            print(f"FAIL: native test-{suite} binary={Path(binary).name} "
                  f"exit={public_exit}", file=sys.stderr, flush=True)
            return public_exit

    if context is not None and context == current_native_context(
            suite, tested_source, kdir, runner):
        # Best-effort development cache: an unwritable checkpoint must not
        # downgrade a passing fresh test into a qualification failure.
        runner.write_development_resume_checkpoint(
            context, [suite], native_suite=suite)
    return 0


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments or arguments[0] not in SUITES:
        print("FAIL: unrecognized native test suite", file=sys.stderr)
        return 2
    suite = arguments[0]
    expected = tuple(str(NATIVE / name) for name in SUITES[suite])
    if tuple(arguments[1:]) != expected:
        print("FAIL: native suite program inventory mismatch", file=sys.stderr)
        return 2
    mode = os.environ.get("SWAPZ_NATIVE_CACHE_MODE")
    runner = None
    if mode in ("record", "resume"):
        specification = importlib.util.spec_from_file_location(
            "swapz_native_development_runner", ROOT / "tests/tools/run-tests.py")
        runner = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(runner)
    return run_native_suite(
        suite, expected, mode=mode, runner=runner,
        tested_source=os.environ.get("SWAPZ_TESTED_SOURCE_SHA"),
        kdir=os.environ.get("SWAPZ_NATIVE_CACHE_KDIR"))


if __name__ == "__main__":
    raise SystemExit(main())
