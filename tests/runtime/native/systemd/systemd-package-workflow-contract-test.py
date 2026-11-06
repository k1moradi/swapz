#!/usr/bin/env python3
"""Rootless, dependency-free contract for exact-run systemd/package CI."""

import os
import re
import subprocess
import sys
import tempfile
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
                self.assertRegex(job, r"(?m)^          fetch-depth: 2$")
                self.assertRegex(job, r"(?m)^          persist-credentials: false$")
                self.assertNotRegex(job, r"(?m)^    concurrency:", "no shared job queue")

    def test_existing_rootless_suites_remain(self) -> None:
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
        self.assertNotRegex(
            self.jobs,
            r"(?m)^\s*(?:run:\s*)?(?:sudo|modprobe|swapon|swapoff|dmsetup|"
            r"apt-get|systemctl\s+(?:enable|start|restart))\b",
            "CI must not execute privileged operations",
        )

    def test_patch_hygiene_checks_commit_and_workspace(self) -> None:
        self.assertRegex(self.jobs, r"(?m)^          git diff --check HEAD\^ HEAD$")
        self.assertRegex(self.jobs, r"(?m)^          git diff --check$")
        self.assertNotRegex(
            self.jobs,
            r"(?m)^        run: git diff --check$",
            "a clean checkout alone does not check the committed patch",
        )

    def test_executed_failures_are_source_bound_and_not_queue_failures(self) -> None:
        self.assertIn("run-name: Systemd/package ${{ github.sha }}", self.source)
        self.assertIn("name: Systemd/package rootless ${{ github.sha }}", self.jobs)
        self.assertIn("if: failure()", self.jobs)
        self.assertIn("SYSTEMD_PACKAGE_ROOTLESS_FAILED", self.jobs)
        self.assertIn('"$GITHUB_SHA"', self.jobs)
        self.assertIn('"$GITHUB_RUN_ID"', self.jobs)

    def test_passive_swap_cannot_be_activated_by_dependency(self) -> None:
        # No systemd job is started: verify the packaged unit and evaluate the
        # always-false condition independently in a rootless sandbox.
        passive = (WORKFLOW.parents[2] / "packaging/swapz-primary.swap").read_text(
            encoding="utf-8"
        )
        self.assertIn("RefuseManualStart=yes", passive)
        self.assertIn("RefuseManualStop=yes", passive)
        self.assertRegex(passive, r"(?m)^ConditionPathExists=!/$")
        self.assertNotIn("[Install]", passive)
        with tempfile.TemporaryDirectory(prefix="swapz-passive-unit-") as location:
            staged = Path(location) / r"dev-mapper-swapz\x2dprimary.swap"
            staged.write_text(passive, encoding="utf-8")
            verified = subprocess.run(
                ["systemd-analyze", "verify", str(staged)],
                capture_output=True, text=True, check=False, timeout=30,
            )
            self.assertEqual(verified.returncode, 0, verified.stderr)
        checked = subprocess.run(
            ["systemd-analyze", "condition", "ConditionPathExists=!/"],
            capture_output=True, text=True, check=False, timeout=30,
        )
        self.assertEqual(checked.returncode, 1, checked.stdout + checked.stderr)


    def test_passive_swap_guard_survives_normal_generator_shadow(self) -> None:
        repo_root = WORKFLOW.parents[2]
        unit_name = r"dev-mapper-swapz\x2dprimary.swap"
        with tempfile.TemporaryDirectory(prefix="swapz-passive-shadow-") as location:
            root = Path(location)
            normal = root / "normal"
            early = root / "early"
            late = root / "late"
            vendor = root / "vendor"
            sbin = root / "sbin"
            for directory in (normal, early, late, vendor, sbin):
                directory.mkdir()

            # Model systemd-fstab-generator output in normal-dir. It outranks
            # the packaged /usr unit and therefore hides its false condition.
            generated = normal / unit_name
            generated.write_text(
                "[Unit]\nSourcePath=/etc/fstab\n\n"
                "[Swap]\nWhat=/dev/mapper/swapz-primary\n",
                encoding="utf-8",
            )
            (vendor / unit_name).write_text(
                (repo_root / "packaging/swapz-primary.swap").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["SYSTEMD_UNIT_PATH"] = f"{normal}:{vendor}"
            unguarded = subprocess.run(
                ["systemd-analyze", "condition", f"--unit={unit_name}"],
                capture_output=True, text=True, check=False, timeout=30,
                env=environment,
            )
            self.assertEqual(
                unguarded.returncode, 0,
                "normal generator output did not shadow the vendor condition: "
                + unguarded.stdout + unguarded.stderr,
            )

            manager = sbin / "swapzctl"
            manager.write_text(
                "#!/bin/sh\n"
                "[ \"$1\" = primary ] && [ \"$2\" = systemd-units ] || exit 2\n"
                "printf 'dev-disk-by\\\\x2dpartuuid-01234567.device "
                "dev-disk-by\\\\x2dpartuuid-01234567.swap\\n'\n",
                encoding="ascii",
            )
            manager.chmod(0o755)
            generator = root / "swapz-primary-generator"
            generator.write_text(
                (repo_root / "packaging/swapz-primary-generator").read_text(
                    encoding="utf-8"
                ).replace("@SWAPZ_SBINDIR@", str(sbin)),
                encoding="utf-8",
            )
            generator.chmod(0o755)
            completed = subprocess.run(
                [str(generator), str(normal), str(early), str(late)],
                capture_output=True, text=True, check=False, timeout=30,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

            guard = early / (unit_name + ".d") / "50-swapz-passive.conf"
            self.assertEqual(
                guard.read_text(encoding="ascii"),
                "[Unit]\nRefuseManualStart=yes\nRefuseManualStop=yes\n"
                "ConditionPathExists=!/\n",
            )
            environment["SYSTEMD_UNIT_PATH"] = f"{early}:{normal}:{vendor}"
            guarded = subprocess.run(
                ["systemd-analyze", "condition", f"--unit={unit_name}"],
                capture_output=True, text=True, check=False, timeout=30,
                env=environment,
            )
            self.assertEqual(guarded.returncode, 1, guarded.stdout + guarded.stderr)

    def test_generator_transaction_fixture_runs_in_rootless_stage(self) -> None:
        # Keep this separate from the concurrent primary-systemd fixture owner.
        # The official systemd package workflow already executes this contract.
        fixture = (
            WORKFLOW.parents[2]
            / "tests/runtime/native/systemd/swapz-primary-generator-transaction-test.py"
        )
        completed = subprocess.run(
            [sys.executable, "-B", str(fixture), "-v"],
            text=True,
            capture_output=True,
            check=False,
            timeout=240,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
