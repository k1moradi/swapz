#!/usr/bin/env python3
"""Source-only contract for the mandatory rootless safety workflows.

Prevents a tested runtime script from silently dropping out of the teardown
push triggers, and prevents critical GNU/recall/owner safety tests from being
replaced with an echo-only PASS. No devices, subprocesses or network are used.
"""

from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = (
    ".github/workflows/rootless-teardown.yml",
    ".github/workflows/rootless-combined.yml",
)
NBD_WORKFLOW = ".github/workflows/rootless-nbd.yml"
SELF_TEST = "rootless-workflow-contract-test.py"
MANDATORY_TESTS = (
    SELF_TEST,
    "recall-role-process-integration-test.py",
    "recall-dd-allowlist-test.py",
    "gnu-coreutils-qualification-test.py",
    "recall-gnu-dd-seccomp-qualification-test.py",
    "recall-io-drain-policy-test.py",
    "recall-io-drain-orchestrator-test.py",
    "recall-fixture-release-policy-test.py",
    "recall-fixture-owner-test.py",
    "recall-broker-external-contract-test.py",
    "rootless-ci-evidence-inventory-test.py",
    "recall-denial-telemetry-test.py",
    "v22-drain-plateau-analyze-test.py",
    "v22-latency-v3-test.py",
    "v22-evidence-bundle-check-test.py",
    "v22-evidence-bundle-v3-test.py",
    "swapz-kernel-range-contract-test.py",
    "swapz-gc-source-contract-test.py",
    "swapz-gc-compressed-contract-test.py",
    "swapz-generation-gc-transaction-test.py",
    "swapz-async-reap-contract-test.py",
)
RUNTIME_FILE = re.compile(r"tests/runtime/[A-Za-z0-9_.-]+\.(?:py|sh)\b")
TRIGGER_ITEM = re.compile(r"^      - '([^']+)'$")
STEP_LINE = re.compile(r"^      - name: (.+)$", re.MULTILINE)


class WorkflowContractError(ValueError):
    """A mandatory workflow has lost a source-only safety qualification."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise WorkflowContractError(message)


def _push_paths(source: str) -> frozenset[str]:
    lines = source.splitlines()
    _require("  push:" in lines, "missing push trigger")
    push = lines.index("  push:")
    try:
        paths = lines.index("    paths:", push + 1)
    except ValueError as exc:
        raise WorkflowContractError("push trigger has no path filter") from exc
    _require(paths > push and all(not row.startswith("  pull_request:")
                                  for row in lines[push + 1:paths]),
             "push path filter is not within push trigger")
    result: list[str] = []
    for row in lines[paths + 1:]:
        match = TRIGGER_ITEM.fullmatch(row)
        if match is None:
            break
        result.append(match.group(1))
    _require(bool(result), "empty or invalid push trigger path list")
    return frozenset(result)


def _job_body(source: str) -> str:
    _require("\njobs:\n" in source, "missing workflow jobs")
    return source.split("\njobs:\n", 1)[1]


def _step(body: str, name: str) -> str:
    steps = list(STEP_LINE.finditer(body))
    matches = [idx for idx, match in enumerate(steps) if match.group(1) == name]
    _require(len(matches) == 1, f"missing or duplicate workflow step: {name}")
    idx = matches[0]
    end = steps[idx + 1].start() if idx + 1 < len(steps) else len(body)
    return body[steps[idx].end():end]


def _python_test_executed(body: str, filename: str) -> bool:
    # Test must execute under a deadline, not merely be mentioned in
    # comments, py_compile, grep/echo output or the trigger list.
    target = re.escape("tests/runtime/" + filename)
    command = (r"(?m)^\s*(?:if ! )?timeout [1-9][0-9]*s "
               r"python3 (?:-B )?" + target + r"\s+-v(?:\s|$)")
    return re.search(command, body) is not None


def check_workflow(name: str, source: str) -> None:
    _require(name in WORKFLOWS, "unexpected workflow name")
    _require("permissions:\n  contents: read\n" in source,
             f"{name}: missing read-only GITHUB_TOKEN policy")
    body = _job_body(source)
    paths = _push_paths(source)
    _require(".github/workflows/rootless-teardown.yml" in paths,
             f"{name}: teardown workflow changes cannot trigger the gate")
    _require(".github/workflows/rootless-combined.yml" in paths,
             f"{name}: combined workflow changes cannot trigger the gate")
    _require(".github/workflows/rootless-nbd.yml" in paths,
             f"{name}: standalone NBD workflow edits must trigger the joint safety gate")
    _require("kernel/dm-swapz.c" in paths,
             f"{name}: kernel source changes must trigger the rootless range contract")

    # Unlike combined, teardown enumerates each runtime path explicitly.
    # Account for every actual runtime script referred to by the job,
    # including syntax-only shell scripts and freshly added tests.
    referenced = frozenset(RUNTIME_FILE.findall(body))
    _require(bool(referenced), f"{name}: no runtime sources found in job")
    if "tests/runtime/**" not in paths:
        missing = sorted(referenced - paths)
        _require(not missing,
                 f"{name}: runtime sources omitted from push path filter: {missing}")

    for filename in MANDATORY_TESTS:
        _require(_python_test_executed(body, filename),
                 f"{name}: missing bounded executable safety gate: {filename}")

    owner = _step(body, "Rootless fixture-owner broker and evidence producer policy suite")
    _require("for attempt in {1..3}; do" in owner,
             f"{name}: missing 3 independent fixture-owner repetitions")
    _require(re.search(
        r"if ! timeout 25s python3 -B "
        r"tests/runtime/recall-fixture-owner-test\.py -q", owner) is not None,
        f"{name}: broker repeat cannot fail fast")
    _require('echo "FIXTURE_OWNER_BROKER_REPEAT $attempt/3: PASS"' in owner
             and "exit 1" in owner,
             f"{name}: broker repeat failure or success signal missing")

    readers = _step(body, "Repeated separate-process readback admission qualification")
    _require("for attempt in {1..6}; do" in readers,
             f"{name}: missing six independent five-role repetitions")
    _require(re.search(
        r"if ! timeout 20s python3 -B "
        r"tests/runtime/recall-role-process-integration-test\.py"
        r"\s+ActualServiceAndDirectDDTests"
        r"\.test_real_service_process_five_pinned_workers_and_exact_readback"
        r"\s+-q", readers) is not None,
        f"{name}: full five-role repeat is not fail-fast")
    _require('echo "RECALL_DIRECT_ROLE_REPEAT $attempt/6: PASS"' in readers
             and "exit 1" in readers,
             f"{name}: five-role repeat failure or success signal missing")



def check_nbd_workflow(source: str) -> None:
    """Audit the separately triggered rootless NBD source-only gate."""
    name = NBD_WORKFLOW
    _require("permissions:\n  contents: read\n" in source,
             f"{name}: missing read-only GITHUB_TOKEN policy")
    paths = _push_paths(source)
    _require(name in paths and "tests/runtime/" + SELF_TEST in paths,
             f"{name}: missing source or workflow push trigger")
    for joint in WORKFLOWS:
        _require(joint in paths,
                 f"{name}: edits to dependent workflow {joint} must trigger NBD contract")
    body = _job_body(source)
    referenced = frozenset(RUNTIME_FILE.findall(body))
    _require(bool(referenced), f"{name}: no runtime sources discovered")
    _require(not (referenced - paths),
             f"{name}: runtime sources omitted from push path filter: {sorted(referenced - paths)}")
    _require(_python_test_executed(body, SELF_TEST),
             f"{name}: workflow contract regression is not a bounded executed test")

    static = _step(body, "Static syscall isolation gate (before any selftest)")
    for token in ("shutdown_kernel_session", "selftest_failure_gates",
                  "fake_fd", "fcntl.ioctl", "os.close"):
        _require(token in static,
                 f"{name}: missing static syscall isolation check: {token}")

    selftest = _step(body, "Run rootless NBD selftest")
    _require("run: python3 tests/runtime/size-aware-nbd.py selftest" in selftest,
             f"{name}: missing real rootless selftest command")

    repeats = _step(body, "Repeat rootless NBD selftest 25 times to catch socket races")
    _require("for i in {1..25}; do" in repeats,
             f"{name}: 25 independent NBD repeats are missing")
    _require("if ! timeout 15s python3 tests/runtime/size-aware-nbd.py selftest" in repeats
             and "exit 1" in repeats
             and 'echo "NBD rootless selftest repetition $i/25: PASS"' in repeats,
             f"{name}: NBD stress repetitions must be bounded and fail-fast")

    _require(_python_test_executed(body, "nbd-pidfd-owned-session-test.py"),
             f"{name}: pidfd-owned NBD mock lifecycle test is not executed")


class RootlessWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = {
            name: (ROOT / name).read_text(encoding="utf-8")
            for name in WORKFLOWS
        }
        cls.nbd_source = (ROOT / NBD_WORKFLOW).read_text(encoding="utf-8")

    def test_both_workflows_retain_source_only_qualification_contract(self):
        for name, source in self.sources.items():
            with self.subTest(workflow=name):
                check_workflow(name, source)

    def test_missing_teardown_source_trigger_is_rejected(self):
        name = WORKFLOWS[0]
        source = self.sources[name]
        trigger = "      - 'tests/runtime/no-discard-livegc.sh'\n"
        self.assertIn(trigger, source)
        with self.assertRaisesRegex(WorkflowContractError, "omitted from push"):
            check_workflow(name, source.replace(trigger, "", 1))

    def test_teardown_must_recheck_standalone_nbd_workflow_changes(self):
        name = WORKFLOWS[0]
        source = self.sources[name]
        path = "      - '.github/workflows/rootless-nbd.yml'\n"
        self.assertIn(path, source)
        with self.assertRaisesRegex(WorkflowContractError, "standalone NBD workflow edits"):
            check_workflow(name, source.replace(path, "", 1))

    def test_kernel_source_change_must_trigger_both_joint_workflows(self):
        for name, source in self.sources.items():
            with self.subTest(workflow=name):
                path = "      - 'kernel/dm-swapz.c'\n"
                self.assertIn(path, source)
                with self.assertRaisesRegex(WorkflowContractError, "kernel source changes"):
                    check_workflow(name, source.replace(path, "", 1))

    def test_removed_async_reap_execution_is_rejected(self):
        for name, source in self.sources.items():
            with self.subTest(workflow=name):
                command = "timeout 25s python3 -B tests/runtime/swapz-async-reap-contract-test.py -v"
                self.assertIn(command, source)
                with self.assertRaisesRegex(WorkflowContractError, "missing bounded executable safety gate"):
                    check_workflow(name, source.replace(command, "echo 'async reaper skipped'", 1))

    def test_removed_generation_gc_transaction_execution_is_rejected(self):
        for name, source in self.sources.items():
            with self.subTest(workflow=name):
                command = "timeout 25s python3 -B tests/runtime/swapz-generation-gc-transaction-test.py -v"
                self.assertIn(command, source)
                with self.assertRaisesRegex(WorkflowContractError, "missing bounded executable safety gate"):
                    check_workflow(name, source.replace(command, "echo 'generation check omitted'", 1))

    def test_removed_gc_compressed_payload_safety_execution_is_rejected(self):
        for name, source in self.sources.items():
            with self.subTest(workflow=name):
                command = "timeout 25s python3 -B tests/runtime/swapz-gc-compressed-contract-test.py -v"
                self.assertIn(command, source)
                with self.assertRaisesRegex(WorkflowContractError, "missing bounded executable safety gate"):
                    check_workflow(name, source.replace(command, "echo 'GC compressed alias skipped'", 1))

    def test_removed_gc_source_snapshot_execution_is_rejected(self):
        for name, source in self.sources.items():
            with self.subTest(workflow=name):
                command = "timeout 25s python3 -B tests/runtime/swapz-gc-source-contract-test.py -v"
                self.assertIn(command, source)
                with self.assertRaisesRegex(WorkflowContractError, "missing bounded executable safety gate"):
                    check_workflow(name, source.replace(command, "echo 'GC source safety not executed'", 1))

    def test_removed_kernel_range_execution_is_rejected(self):
        for name, source in self.sources.items():
            with self.subTest(workflow=name):
                command = "timeout 25s python3 -B tests/runtime/swapz-kernel-range-contract-test.py -v"
                self.assertIn(command, source)
                with self.assertRaisesRegex(WorkflowContractError, "missing bounded executable safety gate"):
                    check_workflow(name, source.replace(command, "echo 'kernel range skipped'", 1))

    def test_removed_v3_bundle_binding_execution_is_rejected(self):
        for name, source in self.sources.items():
            with self.subTest(workflow=name):
                command = "timeout 35s python3 -B tests/runtime/v22-evidence-bundle-v3-test.py -v"
                self.assertIn(command, source)
                with self.assertRaisesRegex(WorkflowContractError, "missing bounded executable safety gate"):
                    check_workflow(name, source.replace(command, "echo 'V3 bundle not executed'", 1))

    def test_removed_v3_latency_sidecar_execution_is_rejected(self):
        for name, source in self.sources.items():
            with self.subTest(workflow=name):
                command = "timeout 35s python3 -B tests/runtime/v22-latency-v3-test.py -v"
                self.assertIn(command, source)
                with self.assertRaisesRegex(WorkflowContractError, "missing bounded executable safety gate"):
                    check_workflow(name, source.replace(command, "echo 'V3 not executed'", 1))

    def test_removed_denial_telemetry_execution_is_rejected(self):
        for name, source in self.sources.items():
            with self.subTest(workflow=name):
                command = "timeout 25s python3 -B tests/runtime/recall-denial-telemetry-test.py -v"
                self.assertIn(command, source)
                with self.assertRaisesRegex(WorkflowContractError, "missing bounded executable safety gate"):
                    check_workflow(name, source.replace(command, "echo 'telemetry skipped'", 1))

    def test_removed_ci_inventory_execution_is_rejected(self):
        for name, source in self.sources.items():
            with self.subTest(workflow=name):
                command = "timeout 25s python3 -B tests/runtime/rootless-ci-evidence-inventory-test.py -v"
                self.assertIn(command, source)
                with self.assertRaisesRegex(WorkflowContractError, "missing bounded executable safety gate"):
                    check_workflow(name, source.replace(command, "echo 'inventory was skipped'", 1))

    def test_removed_broker_primary_execution_is_rejected(self):
        for name, source in self.sources.items():
            with self.subTest(workflow=name):
                command = ("timeout 45s python3 -B "
                           "tests/runtime/recall-fixture-owner-test.py -v")
                self.assertIn(command, source)
                with self.assertRaisesRegex(WorkflowContractError, "recall-fixture-owner-test"):
                    check_workflow(name, source.replace(command, "true", 1))

    def test_unconditional_broker_repeat_is_rejected(self):
        for name, source in self.sources.items():
            with self.subTest(workflow=name):
                command = ("if ! timeout 25s python3 -B "
                           "tests/runtime/recall-fixture-owner-test.py -q")
                self.assertIn(command, source)
                with self.assertRaisesRegex(WorkflowContractError, "repeat cannot fail fast"):
                    check_workflow(name, source.replace(command, command[5:], 1))

    def test_missing_gnu_provenance_unit_test_is_rejected(self):
        for name, source in self.sources.items():
            with self.subTest(workflow=name):
                command = ("timeout 30s python3 -B "
                           "tests/runtime/gnu-coreutils-qualification-test.py -v")
                self.assertIn(command, source)
                with self.assertRaisesRegex(WorkflowContractError, "gnu-coreutils"):
                    check_workflow(name, source.replace(command, "true", 1))


    def test_standalone_nbd_gate_retains_static_syscall_and_stress_checks(self):
        check_nbd_workflow(self.nbd_source)

    def test_nbd_must_recheck_joint_workflow_source_changes(self):
        for joint in WORKFLOWS:
            with self.subTest(workflow=joint):
                path = f"      - '{joint}'\n"
                self.assertIn(path, self.nbd_source)
                with self.assertRaisesRegex(WorkflowContractError, "dependent workflow"):
                    check_nbd_workflow(self.nbd_source.replace(path, "", 1))

    def test_nbd_missing_runtime_source_trigger_is_rejected(self):
        item = "      - 'tests/runtime/nbd-pidfd-owned-session-test.py'\n"
        self.assertIn(item, self.nbd_source)
        with self.assertRaisesRegex(WorkflowContractError, "omitted from push"):
            check_nbd_workflow(self.nbd_source.replace(item, "", 1))

    def test_nbd_unbounded_stress_is_rejected(self):
        command = "if ! timeout 15s python3 tests/runtime/size-aware-nbd.py selftest"
        self.assertIn(command, self.nbd_source)
        with self.assertRaisesRegex(WorkflowContractError, "fail-fast"):
            check_nbd_workflow(self.nbd_source.replace(command, command[5:], 1))

    def test_nbd_missing_static_syscall_gate_is_rejected(self):
        step = "      - name: Static syscall isolation gate (before any selftest)"
        self.assertIn(step, self.nbd_source)
        with self.assertRaisesRegex(WorkflowContractError, "Static syscall isolation"):
            check_nbd_workflow(self.nbd_source.replace(step, "      - name: Empty gate", 1))

    def test_missing_workflow_contract_execution_is_rejected(self):
        for name, source in self.sources.items():
            with self.subTest(workflow=name):
                command = ("timeout 20s python3 -B "
                           "tests/runtime/rootless-workflow-contract-test.py -v")
                self.assertIn(command, source)
                with self.assertRaisesRegex(WorkflowContractError, SELF_TEST):
                    check_workflow(name, source.replace(command, "true", 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
