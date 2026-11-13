#!/usr/bin/env python3
"""Fail-closed rootless resource inventory for *planning*, not execution.

Phase 1 deliberately does not enable parallelism. A candidate means only that
its current source appears read-only or uses independently allocated fixtures;
it is not permission to launch workers. Phase 2 must separately verify worker
ownership, nested subprocesses, logging, failure cancellation and CPU budgets.
"""
from pathlib import PurePosixPath
import re
import shlex
from typing import NamedTuple


class PhaseResources(NamedTuple):
    classification: str
    reads: frozenset[str]
    writes: frozenset[str]
    review: str


# Every literal rootless phase in test-rootless.sh must occur exactly once in
# these three groups. An unclassified phase is never a parallel candidate.
READ_ONLY_PHASES = {
    "tests/runtime/benchmark/resource-pressure.py --help":
        "Help text only; no pressure worker is started",
    "loaded-preflight executable contract":
        "Fixed-path executable-bit check only",
    "source-contract single test runner":
        "Read-only source-runner count check",
    "static source/interface contract assertions":
        "Read-only grep assertions over fixed source paths",
}

PRIVATE_FIXTURE_PHASES = {
    "tests/runtime/native/source-contract-test.py":
        "Production-source inspections and compiler probes in fresh temp roots",
    "tests/runtime/native/userspace/swapzctl-active-swap-provenance-test.py":
        "Synthetic provenance fixture in a unique temporary directory",
    "tests/runtime/benchmark/metadata-ram-evidence-test.py":
        "Offline metadata fixtures without actual device state",
    "tests/runtime/native/production-readiness-test.py":
        "Frozen policy checks and isolated synthetic report fixtures",
    "tests/runtime/native/rootless-direct-evidence-test.py":
        "Reporter ROOT redirected to a fresh private diagnostic fixture",
    # Source-reviewed contiguous process simulations: every worker owns its
    # own temporary workspace and process children. They never operate a
    # real cgroup, block device, shared native build or global /tmp cleanup.
    "tests/runtime/native/owned-ram-resources-test.py":
        "Owned RAM identity and cleanup simulations in per-test temporary roots",
    "tests/runtime/native/resource-admission-test.py":
        "Only synthetic cgroup/proc inputs in a private per-test workspace",
    "tests/runtime/native/resource-pressure-cleanup-ownership-test.py":
        "Private cleanup fixtures and explicitly reaped owned/foreign child PIDs",
    "tests/runtime/native/nullblk-identity-test.sh":
        "Fresh build/tests/nullblk-name.XXXXXXXX fixture, not a real null_blk",
    "tests/runtime/native/quiet-lower-io-test.sh":
        "Fresh build/tests/quiet-io.XXXXXXXX fixture",
    "tests/runtime/native/swap-inventory-test.sh":
        "Fresh build/tests/swap-inventory.XXXXXXXX fixture",
    "C syntax: owned nullblk lifecycle seam":
        "Compiler -fsyntax-only; no output binary or owned device",
    "C syntax: physical lifecycle seam":
        "Compiler -fsyntax-only; no output binary or physical access",
    "C syntax: unqualified physical seam rejection":
        "Compiler -fsyntax-only negative case; no output binary",
    "C syntax: mutually exclusive lifecycle seams":
        "Compiler -fsyntax-only negative case; no output binary",
}

# The first tuple element names the *hazard to audit*, not a permission to
# access the named resource. These phases remain serial even if two hazard
# labels are disjoint: proof of independent behavior is still missing.
SERIAL_PHASES = {
    "rootless initialization":
        ("harness-progress", "Initializes shared phase and diagnostic state"),
    "tests/Makefile native and metadata":
        ("native-artifacts", "Builds/relinks shared native objects and generated metadata"),
    "tests/runtime/native/tmp-cleanup-test.py":
        ("process-cleanup", "Exercises background children and cleanup ownership"),
    "tests/runtime/native/primary-lifecycle-audit-test.py":
        ("process-cleanup", "Compiles and kills package transactions; uses private stderr relay"),
    "tests/runtime/native/primary-lifecycle-nullblk-qualifier-test.py":
        ("process-cleanup", "Extracted coordinator execution and compiled fixture lifetimes"),
    "tests/runtime/native/primary-real-swap-test.py":
        ("process-cleanup", "Nested primary lifecycle process/pipe contracts"),
    "tests/runtime/native/primary-real-swap-parent-ownership-test.py":
        ("process-cleanup", "Nested primary process and parent-ownership contracts"),
    "tests/runtime/native/primary-real-swap-oracle-terminal-test.py":
        ("process-cleanup", "Terminal oracle and subprocess ownership contracts"),
    "tests/runtime/benchmark/io-replay-test.py":
        ("native-artifacts", "Can invoke make for shared build/tests/native helper targets"),
    "tests/runtime/native/make-interface-test.py":
        ("build-fixtures", "Runs Make and synthetic repository/build fixtures"),
    "tests/runtime/native/test-report-test.py":
        ("report-fixtures", "Runs reporter/history and private diagnostic filesystem tests"),
    "tests/runtime/native/rootless-attribution-test.py":
        ("harness-diagnostics", "Extracts real relay and cancellation traps into test subprocesses"),
    "tests/runtime/native/ci-failure-diagnostics-test.py":
        ("harness-diagnostics", "Exercises actual relay child and kill/reap timeout behavior"),
    "tests/runtime/native/package-dkms-test.py":
        ("package-fixtures", "Mutable package sandbox and install/recovery process tests"),
    "tests/runtime/native/systemd/swapz-primary-systemd-test.py":
        ("service-fixtures", "Simulated systemd/boot verifier and child process behavior"),
    "tests/runtime/native/systemd/swapz-primary-generator-transaction-test.py":
        ("service-fixtures", "Simulated generator concurrency and transaction state"),
    "tests/runtime/native/physical-swap-probe-test.py":
        ("physical-admission-fixtures", "Safety-critical admission simulations remain isolated"),
    "tests/runtime/native/live-swap-supervisor-test.py":
        ("process-cleanup", "Supervisor process and signal lifecycle tests"),
    "x86_64 native SIMD disassembly contracts":
        ("native-artifacts", "Writes/removes fixed shared native disassembly paths"),
}

# Exact paths in the sole dynamic syntax loop. Enforce path and basename
# identity; an added or replaced script cannot silently become schedulable.
SYNTAX_SCRIPTS = (
    "tests/tools/test-rootless.sh",
    "tests/tools/test-loaded.sh",
    "tests/tools/qualify-resource-pressure.sh",
    "tests/tools/qualify-logical-open-balance.sh",
    "packaging/package-dkms.sh",
    "packaging/swapz-primary-boot-verify",
    "packaging/sign-module.sh",
    "tests/tools/deploy-nullblk.sh",
    "tests/tools/qualify-primary-lifecycle-nullblk.sh",
    "tests/tools/qualify-owned-ram-recovery.sh",
    "tests/tools/loaded-preflight.sh",
    "tests/tools/swap-inventory.sh",
    "tests/tools/quiet-lower-io.sh",
    "tests/tools/benchmark-owned-pair.sh",
    "tests/tools/benchmark-striped-owned.sh",
    "tests/tools/nullblk-identity.sh",
    "tests/runtime/native/nullblk-identity-test.sh",
    "tests/runtime/native/quiet-lower-io-test.sh",
    "tests/runtime/native/swap-inventory-test.sh",
)

# These three simulated integration suites are absent from make test's
# algorithm tier and remain serial under make test_full.
FULL_ONLY_PHASES = frozenset({
    "tests/runtime/native/package-dkms-test.py",
    "tests/runtime/native/systemd/swapz-primary-systemd-test.py",
    "tests/runtime/native/systemd/swapz-primary-generator-transaction-test.py",
})


# Only the exact adjacent, resource-audited groups in rootless-parallel.py
# are authorized for CPU-aware execution. The three identity fixtures create
# disjoint mktemp directories and only simulate /sys, /proc and DM commands.
# The three reviewed resource-fixture suites use independent temporary roots
# and own/reap their process children; every other process-lifecycle, package
# and hardware-dependent suite remains serial.
ROOTLESS_PARALLEL_EXECUTION_ENABLED = True


def resource_claims():
    """Return an exact, duplicate-checked inventory; never infer unknown suites."""
    claims = {}

    def add(label, classification, reads, writes, review):
        if label in claims or not review:
            raise ValueError("duplicate or unreviewed rootless phase")
        claims[label] = PhaseResources(
            classification, frozenset(reads), frozenset(writes), review)

    for label, review in READ_ONLY_PHASES.items():
        add(label, "read-only", ("checkout",), (), review)
    for label, review in PRIVATE_FIXTURE_PHASES.items():
        add(label, "private-fixtures", ("checkout", "native-artifacts"),
            (f"private:{label}",), review)
    for label, (hazard, review) in SERIAL_PHASES.items():
        add(label, "serial", ("checkout", "native-artifacts"),
            (hazard,), review)
    for path in SYNTAX_SCRIPTS:
        add(f"bash syntax {PurePosixPath(path).name}", "read-only",
            ("checkout",), (), f"bash -n reads only {path}")
    return claims


def declared_harness_phases(source):
    """Extract the literal phase labels and exact dynamic bash -n loop."""
    literal = re.findall(
        r"(?m)^rootless_phase='([^'\r\n]{1,128})'$", source)
    if len(literal) != len(set(literal)):
        raise ValueError("duplicate literal rootless phase")
    loop_prefix = "for script in "
    loop_suffix = '; do\n  rootless_phase="bash syntax ${script##*/}"'
    if source.count(loop_prefix) != 1 or source.count(loop_suffix) != 1:
        raise ValueError("unrecognized rootless syntax loop")
    body = source.split(loop_prefix, 1)[1].split(loop_suffix, 1)[0]
    paths = tuple(shlex.split(body.replace("\\\n", " ")))
    if paths != SYNTAX_SCRIPTS or len(paths) != len(set(paths)):
        raise ValueError("unreviewed rootless syntax script")
    if any(not path.startswith(("tests/", "packaging/")) or
           ".." in PurePosixPath(path).parts for path in paths):
        raise ValueError("unsafe rootless syntax path")
    dynamic = [f"bash syntax {PurePosixPath(path).name}" for path in paths]
    if len(dynamic) != len(set(dynamic)):
        raise ValueError("duplicate rootless syntax phase")
    return frozenset((*literal, *dynamic))


def audit_harness(source):
    """Require an exact classification of every rootless progress phase."""
    discovered = declared_harness_phases(source)
    claims = resource_claims()
    if discovered != claims.keys():
        raise ValueError("rootless resource inventory/harness drift")
    return claims


def potential_conflicts(first, second, claims=None):
    """Planning-only hazards; an empty result is NOT approval to parallelize."""
    profiles = resource_claims() if claims is None else claims
    if first not in profiles or second not in profiles:
        raise ValueError("unclassified rootless phase")
    if first == second:
        return ("same-phase",)
    left, right = profiles[first], profiles[second]
    if left.classification == "serial" or right.classification == "serial":
        return ("serial-barrier",)
    shared = (left.writes & (right.reads | right.writes) |
              right.writes & left.reads)
    return tuple(f"shared:{resource}" for resource in sorted(shared))
