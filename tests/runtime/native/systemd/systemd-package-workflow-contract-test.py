#!/usr/bin/env python3
"""Rootless, dependency-free contract for exact-run systemd/package CI."""

import re
import unittest
from pathlib import Path


WORKFLOW = (
    Path(__file__).resolve().parents[4]
    / ".github/workflows/systemd-package-readiness.yml"
)


def top_level_block(source: str, name: str) -> str:
    """Read one unindented workflow mapping without a YAML dependency."""
    start = re.search(rf"(?m)^{re.escape(name)}:\s*\n", source)
    if start is None:
        raise AssertionError(f"missing top-level {name} mapping")
    remaining = source[start.end():]
    following = re.search(r"(?m)^[A-Za-z][\w-]*:", remaining)
    return remaining[:following.start()] if following else remaining


class SystemdPackageWorkflowContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WORKFLOW.read_text(encoding="utf-8")
        cls.jobs = top_level_block(cls.source, "jobs")

    def test_each_workflow_run_has_its_own_queue_slot(self) -> None:
        concurrency = top_level_block(self.source, "concurrency")
        group_match = re.search(r"(?m)^  group: ([^\n]+)$", concurrency)
        self.assertIsNotNone(group_match, "missing workflow concurrency group")
        group = group_match.group(1).strip()
        self.assertEqual(
            group,
            "systemd-package-readiness-${{ github.ref }}-${{ github.run_id }}",
            "a ref-only or SHA-only group can replace a pending run",
        )
        self.assertRegex(concurrency, r"(?m)^  cancel-in-progress: false$")
        self.assertNotRegex(concurrency, r"(?m)^  queue:")
        # Different pushes and manual dispatches can target the same ref/SHA.
        first_run = group.replace("${{ github.ref }}", "refs/heads/main").replace(
            "${{ github.run_id }}", "1001"
        )
        second_run = group.replace("${{ github.ref }}", "refs/heads/main").replace(
            "${{ github.run_id }}", "1002"
        )
        self.assertNotEqual(first_run, second_run)

    def test_every_job_checks_out_the_event_sha(self) -> None:
        job_headers = list(re.finditer(r"(?m)^  ([\w-]+):\s*$", self.jobs))
        self.assertEqual(len(job_headers), 1, "keep this gate in one rootless CI job")
        for index, header in enumerate(job_headers):
            job_end = (
                job_headers[index + 1].start()
                if index + 1 < len(job_headers) else len(self.jobs)
            )
            job = self.jobs[header.end():job_end]
            with self.subTest(job=header.group(1)):
                checkouts = re.findall(
                    r"(?m)^      - uses: actions/checkout@[^\s]+$", job
                )
                self.assertEqual(len(checkouts), 1, "expected one source checkout")
                self.assertRegex(
                    job,
                    r"(?m)^      - uses: actions/checkout@[^\s]+\n"
                    r"        with:\n"
                    r"          ref: \$\{\{ github\.sha \}\}$",
                    "checkout must pin github.sha, not a moving main ref",
                )
                self.assertRegex(job, r"(?m)^          persist-credentials: false$")
                self.assertNotRegex(job, r"(?m)^    concurrency:", "no shared job queue")

    def test_existing_rootless_suites_and_patch_hygiene_remain(self) -> None:
        required = (
            "command -v systemd-analyze",
            "command -v timeout",
            "bash -n \\",
            "packaging/package-dkms.sh",
            "packaging/sign-module.sh",
            "packaging/swapz-primary-generator",
            "packaging/swapz-primary-runtime-health",
            "packaging/swapz-primary-boot-verify",
            "python3 -B tests/runtime/native/package-dkms-test.py -v",
            "python3 -B tests/runtime/native/systemd/swapz-primary-systemd-test.py -v",
            "python3 -B tests/runtime/native/systemd/systemd-package-workflow-contract-test.py -v",
            "git diff --check",
        )
        for command in required:
            with self.subTest(command=command):
                self.assertIn(command, self.jobs)
        # Suite invocation lines must be executable steps, not commented strings.
        for script in (
            "tests/runtime/native/package-dkms-test.py",
            "tests/runtime/native/systemd/swapz-primary-systemd-test.py",
            "tests/runtime/native/systemd/systemd-package-workflow-contract-test.py",
        ):
            self.assertRegex(
                self.jobs,
                rf"(?m)^        run: python3 -B {re.escape(script)} -v$",
            )
        self.assertRegex(self.jobs, r"(?m)^        run: git diff --check$")
        self.assertNotRegex(
            self.jobs,
            r"(?m)^\s*(?:run:\s*)?(?:sudo|modprobe|swapon|swapoff|dmsetup|"
            r"apt-get|systemctl\s+(?:enable|start|restart))\b",
            "CI must not execute privileged operations",
        )

    def test_executed_failures_are_source_bound_and_not_queue_failures(self) -> None:
        self.assertIn("run-name: Systemd/package ${{ github.sha }}", self.source)
        self.assertIn("name: Systemd/package rootless ${{ github.sha }}", self.jobs)
        self.assertIn("if: failure()", self.jobs)
        self.assertIn("SYSTEMD_PACKAGE_ROOTLESS_FAILED", self.jobs)
        self.assertIn('"$GITHUB_SHA"', self.jobs)
        self.assertIn('"$GITHUB_RUN_ID"', self.jobs)


if __name__ == "__main__":
    unittest.main()
