#!/usr/bin/env python3
"""Rootless actual-Git first-parent regressions for authority CI push metadata."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
POLICY_SCRIPT = REPOSITORY_ROOT / "tests/runtime/native/repository-policy-test.py"
AUTHORITY_WORKFLOW = (
    REPOSITORY_ROOT / ".github/workflows/phase-a-round060-authority-conversion-noauth.yml"
)
CANONICAL_STANDARDS = (
    "docs/coding_standards.md",
    "docs/testing_standards.md",
    "docs/compile.md",
    "docs/benchmark.md",
)


class AuthorityPushMetadataTests(unittest.TestCase):
    """Execute the unchanged production policy against real local Git objects."""

    def setUp(self):
        temporary_repository = tempfile.TemporaryDirectory(prefix="swapz-round061-policy-")
        self.addCleanup(temporary_repository.cleanup)
        self.repository = Path(temporary_repository.name) / "repository"
        self.repository.mkdir()
        self.run_git("init", "--quiet", "-b", "main")
        self.run_git("config", "user.name", "Policy Fixture")
        self.run_git("config", "user.email", "policy@example.invalid")
        for standard in CANONICAL_STANDARDS:
            self.write_file(standard, "# Canonical rule\nExisting invariant.\n")
        self.base_sha = self.commit("original canonical standards")

    def run_git(self, *arguments):
        completed = subprocess.run(
            ("git", *arguments), cwd=self.repository, capture_output=True,
            text=True, check=False, timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr[:300])
        return completed.stdout.strip()

    def write_file(self, path, content):
        destination = self.repository / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")

    def commit(self, message):
        self.run_git("add", "-A")
        self.run_git("commit", "--quiet", "-m", message)
        return self.run_git("rev-parse", "HEAD")

    def change_workflow_and_standards(self, *, with_standards=True):
        self.write_file(
            ".github/workflows/phase-a-round060-authority-conversion-noauth.yml",
            "name: actual authority semantic regression\n",
        )
        if with_standards:
            self.write_file(
                "docs/testing_standards.md",
                "# Canonical rule\nExisting invariant.\n"
                "Authority push-base must match the GitHub push event.\n",
            )
        return self.commit("authority source and testing standard" if with_standards
                           else "authority source without required standard")

    def enforce(self, *, event_name="push", before_sha=None, expected_sha=None):
        environment = os.environ.copy()
        environment.update(
            GITHUB_EVENT_NAME=event_name,
            GITHUB_SHA=expected_sha or self.run_git("rev-parse", "HEAD"),
        )
        # Missing push metadata must really be absent, not auto-filled by a
        # synthetic fixture or inherited from the host environment.
        environment.pop("SWAPZ_PUSH_BEFORE_SHA", None)
        if before_sha is not None:
            environment["SWAPZ_PUSH_BEFORE_SHA"] = before_sha
        return subprocess.run(
            (sys.executable, "-B", str(POLICY_SCRIPT), "--enforce"),
            cwd=self.repository, env=environment, capture_output=True,
            text=True, check=False, timeout=10,
        )

    def assert_policy_rejected(self, result, expected_message):
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SOURCE_CONTRACT_MISMATCH", result.stderr)
        self.assertIn(expected_message, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(len(result.stderr.splitlines()), 2)
        self.assertTrue(all(len(line) <= 512 for line in result.stderr.splitlines()))
        self.assertNotIn(str(self.repository), result.stderr)

    def test_workflow_uses_unmodified_real_push_event_before(self):
        workflow_text = AUTHORITY_WORKFLOW.read_text(encoding="utf-8")
        self.assertRegex(
            workflow_text,
            r"(?m)^\s+SWAPZ_PUSH_BEFORE_SHA:\s*\$\{\{ github\.event\.before \}\}\s*$",
        )
        self.assertEqual(workflow_text.count("SWAPZ_PUSH_BEFORE_SHA:"), 1)
        self.assertIn("fetch-depth: 0", workflow_text)
        self.assertIn("persist-credentials: false", workflow_text)
        self.assertIn('test "$GITHUB_REF" = refs/heads/main', workflow_text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', workflow_text)
        self.assertIn(
            "python3 -B tests/runtime/native/repository-policy-test.py --enforce",
            workflow_text,
        )
        self.assertIn(
            "python3 -B tests/tools/round061-authority-push-metadata-verify.py",
            workflow_text,
        )
        self.assertNotRegex(workflow_text, r"(?m)^\s*continue-on-error:\s*true")

    def test_real_push_before_first_parent_accepts_qualified_workflow_source(self):
        committed_sha = self.change_workflow_and_standards()
        result = self.enforce(before_sha=self.base_sha)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout + result.stderr, "")
        self.assertEqual(self.run_git("rev-parse", "HEAD"), committed_sha)

    def test_multiple_first_parent_commits_each_require_own_standard(self):
        self.change_workflow_and_standards()
        self.write_file("tests/runtime/native/authority-check.py", "assert True\n")
        self.write_file(
            "docs/testing_standards.md",
            "# Canonical rule\nExisting invariant.\n"
            "Authority push-base must match the GitHub push event.\n"
            "Runtime test changes require the same commit standard.\n",
        )
        self.commit("second qualified source commit")
        result = self.enforce(before_sha=self.base_sha)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_malformed_and_zero_before_remain_rejected(self):
        self.change_workflow_and_standards()
        for missing_or_invalid in (None, "", "not-a-sha", "0" * 40):
            with self.subTest(before_sha=missing_or_invalid):
                self.assert_policy_rejected(
                    self.enforce(before_sha=missing_or_invalid),
                    "push base SHA unavailable or invalid",
                )

    def test_unrelated_existing_commit_and_empty_push_range_are_rejected(self):
        self.change_workflow_and_standards()
        # Write an unreachable sibling commit without creating a branch or a
        # merge; the genuine commit object exists but is not an ancestor.
        sibling_sha = self.run_git(
            "commit-tree", self.run_git("rev-parse", "HEAD^{tree}"),
            "-p", self.base_sha, "-m", "unrelated sibling",
        )
        self.assert_policy_rejected(
            self.enforce(before_sha=sibling_sha),
            "Git metadata command failed",
        )
        self.assert_policy_rejected(
            self.enforce(before_sha=self.run_git("rev-parse", "HEAD")),
            "invalid pushed first-parent range",
        )

    def test_workflow_only_without_same_commit_testing_standards_fails(self):
        offending_sha = self.change_workflow_and_standards(with_standards=False)
        self.assert_policy_rejected(
            self.enforce(before_sha=self.base_sha),
            "missing applicable canonical standards update",
        )
        self.assertIn(offending_sha, self.enforce(before_sha=self.base_sha).stderr)

    def test_docs_only_followup_cannot_repair_previous_bad_source_commit(self):
        self.change_workflow_and_standards(with_standards=False)
        self.write_file("docs/testing_standards.md",
                        "# Canonical rule\nExisting invariant.\nLate documentation.\n")
        self.commit("unqualified docs-only followup")
        self.assert_policy_rejected(
            self.enforce(before_sha=self.base_sha),
            "missing applicable canonical standards update",
        )
        self.assert_policy_rejected(
            self.enforce(event_name="workflow_dispatch"),
            "missing applicable canonical standards update",
        )

    def test_manual_dispatch_preserves_separate_nonpush_mode_without_fake_sha(self):
        self.change_workflow_and_standards()
        result = self.enforce(event_name="workflow_dispatch")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout + result.stderr, "")

    def test_wrong_checkout_sha_still_fails_closed(self):
        self.change_workflow_and_standards()
        self.assert_policy_rejected(
            self.enforce(before_sha=self.base_sha, expected_sha=self.base_sha),
            "checkout SHA mismatch",
        )


if __name__ == "__main__":
    unittest.main()
