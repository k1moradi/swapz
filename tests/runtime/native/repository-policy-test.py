#!/usr/bin/env python3
"""Exact-SHA standards-applicability guard and rootless synthetic CI regression."""

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/project-goals.yml"
STANDARDS = ("docs/coding_standards.md", "docs/testing_standards.md",
             "docs/compile.md", "docs/benchmark.md")
SOURCE_PATHS = ("src", "tests", "packaging", ".github/workflows",
                "Makefile", "dkms.conf")
COMPILE_WORKFLOWS = frozenset({
    ".github/workflows/kernel-debug.yml",
    ".github/workflows/product-codec.yml",
    ".github/workflows/systemd-package-readiness.yml",
})
SHA = re.compile(r"[0-9a-f]{40}\Z")


class PolicyError(Exception):
    """Nonqualifying repository metadata; do not print Git's raw stderr."""


def git(*arguments: str) -> bytes:
    try:
        result = subprocess.run(("git", *arguments), stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=15,
                                check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PolicyError("Git metadata unavailable") from error
    if result.returncode:
        raise PolicyError("Git metadata command failed")
    return result.stdout


def git_status(*arguments: str) -> int:
    """Return a bounded Git status without leaking process/runner details."""
    try:
        result = subprocess.run(("git", *arguments), stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=15,
                                check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PolicyError("Git metadata unavailable") from error
    return result.returncode


def standard_has_nonwhitespace_text_change(
        parent: str, commit_sha: str, standard: str) -> bool:
    """Require changed standards text; metadata-only diffs cannot qualify."""
    return_code = git_status(
        "diff", "--ignore-all-space", "--ignore-blank-lines", "--no-renames",
        "--quiet", parent, commit_sha, "--", standard)
    if return_code not in (0, 1):
        raise PolicyError("canonical standards diff unavailable")
    if return_code == 0:
        return False

    statistics = git(
        "diff", "--ignore-all-space", "--ignore-blank-lines", "--no-renames",
        "--numstat", parent, commit_sha, "--", standard).decode(
            "utf-8", errors="surrogateescape").splitlines()
    if len(statistics) != 1:
        raise PolicyError("canonical standards diff metadata malformed")
    fields = statistics[0].split("\t", 2)
    if len(fields) != 3 or fields[2] != standard:
        raise PolicyError("canonical standards diff metadata malformed")
    try:
        additions = int(fields[0])
        deletions = int(fields[1])
    except ValueError:
        return False
    return additions > 0 or deletions > 0


def applicable_standard_indexes(path: str) -> tuple[int, ...]:
    # Build metadata is source-controlled implementation, but its governing
    # operational contract also lives in compile.md. Keep these exceptions
    # narrow so an unrelated compile edit cannot qualify arbitrary source/CI.
    if path in ("src/kernel/Makefile", "src/kernel/VERSION"):
        return (0, 1, 2)
    if path.startswith("src/"):
        return (0, 1)
    if path.startswith("tests/runtime/benchmark/"):
        return (1, 3)
    if path.startswith("tests/"):
        return (1,)
    if path in COMPILE_WORKFLOWS:
        return (1, 2)
    if path.startswith(".github/workflows/"):
        return (1,)
    if path.startswith("packaging/"):
        return (1, 2)
    if path in ("Makefile", "dkms.conf"):
        return (2,)
    return ()


def emit_failure(commit_sha: str, path: str, required: str, reason: str) -> int:
    # Only repository metadata is printed, with a bounded escaped path.
    quoted_path = ascii(path[:64])
    if len(quoted_path) > 96:
        quoted_path = quoted_path[:93] + "..."
    print(f"SOURCE_CONTRACT_MISMATCH: commit={commit_sha} path={quoted_path} "
          f"required_policy={required} first_error={reason}", file=sys.stderr)
    print(f"SOURCE_CONTRACT_MISMATCH: commit={commit_sha} "
          "corrective_action=do not amend/force-push published commits or "
          "use docs-only repair; make a new source commit with a meaningful "
          "applicable standards co-change and qualify exact-SHA CI on main",
          file=sys.stderr)
    return 1


def audit_commit(commit_sha: str) -> int:
    if SHA.fullmatch(commit_sha) is None:
        raise PolicyError("invalid first-parent commit SHA")
    parent = git("rev-parse", "--verify", f"{commit_sha}^1^{{commit}}").decode().strip()
    changed = git("diff", "--name-only", "--no-renames", "-z", parent,
                  commit_sha, "--")
    if changed and not changed.endswith(b"\0"):
        raise PolicyError("truncated NUL-delimited changeset")
    standards_changed = [
        standard_has_nonwhitespace_text_change(parent, commit_sha, standard)
        for standard in STANDARDS
    ]
    for raw_path in changed.split(b"\0")[:-1]:
        if not raw_path:
            raise PolicyError("empty changed-path metadata")
        path = raw_path.decode("utf-8", errors="surrogateescape")
        indexes = applicable_standard_indexes(path)
        if indexes and not any(standards_changed[index] for index in indexes):
            allowed = " or ".join(STANDARDS[index] for index in indexes)
            return emit_failure(
                commit_sha, path,
                f"same-commit non-whitespace update to ({allowed})",
                "missing applicable canonical standards update")
    return 0


def enforce_policy() -> int:
    expected = os.environ.get("GITHUB_SHA", "")
    try:
        checked_out = git("rev-parse", "--verify", "HEAD^{commit}").decode().strip()
        if SHA.fullmatch(expected) is None or expected != checked_out:
            return emit_failure(checked_out, "<checkout>", "exact GITHUB_SHA",
                                "checkout SHA mismatch")
        if git("symbolic-ref", "--quiet", "--short", "HEAD").decode().strip() != "main":
            return emit_failure(checked_out, "<checkout>", "main-only checkout",
                                "checkout is not on main")
        if os.environ.get("GITHUB_EVENT_NAME") == "push":
            before = os.environ.get("SWAPZ_PUSH_BEFORE_SHA", "")
            if SHA.fullmatch(before) is None or before == "0" * 40:
                raise PolicyError("push base SHA unavailable or invalid")
            git("merge-base", "--is-ancestor", before, checked_out)
            commits = git("rev-list", "--first-parent", "--reverse",
                          f"{before}..{checked_out}").decode().splitlines()
            if not commits or git("rev-parse", "--verify",
                                  f"{commits[0]}^1^{{commit}}").decode().strip() != before:
                raise PolicyError("invalid pushed first-parent range")
        else:
            commits = [checked_out]
        if not commits or commits[-1] != checked_out:
            raise PolicyError("pushed first-parent range omitted checkout SHA")
        latest_source = git("log", "-1", "--first-parent", "--format=%H",
                            checked_out, "--", *SOURCE_PATHS).decode().strip()
        # A later docs/report-only commit cannot qualify a bad code-bearing SHA.
        if latest_source and latest_source != checked_out and latest_source not in commits:
            commits.append(latest_source)
        for commit_sha in commits:
            result = audit_commit(commit_sha)
            if result:
                return result
    except PolicyError as error:
        safe_sha = expected if SHA.fullmatch(expected) else "<unavailable>"
        return emit_failure(safe_sha, "<git-metadata>",
                            "exact first-parent Git metadata", str(error))
    return 0


class SyntheticRepositoryPolicy(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="swapz-ci-policy-")
        self.addCleanup(temporary.cleanup)
        self.repository = Path(temporary.name) / "repo"
        self.repository.mkdir()
        self.git("init", "--quiet", "-b", "main")
        self.git("config", "user.name", "CI Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        for standard in STANDARDS:
            self.write(standard, "# Rules\nOriginal invariant.\n")
        self.initial = self.commit("synthetic base")

    def git(self, *arguments):
        result = subprocess.run(("git", *arguments), cwd=self.repository,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def write(self, path, text):
        target = self.repository / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "--quiet", "-m", message)
        return self.git("rev-parse", "HEAD")

    def audit(self, base=None, expected=None, event="push"):
        environment = os.environ.copy()
        environment.update(GITHUB_SHA=expected or self.git("rev-parse", "HEAD"),
                           GITHUB_EVENT_NAME=event,
                           SWAPZ_PUSH_BEFORE_SHA=base or self.initial)
        return subprocess.run((sys.executable, "-B", str(Path(__file__).resolve()),
                               "--enforce"), cwd=self.repository, env=environment,
                              text=True, capture_output=True, timeout=5)

    def test_missing_replay_standard_has_bounded_causal_diagnostic(self):
        self.write("tests/runtime/benchmark/io-replay-test.py", "assert True\n")
        offending_sha = self.commit("invalid replay fixture")
        result = self.audit()
        self.assertNotEqual(result.returncode, 0)
        self.assertLessEqual(len(result.stderr.splitlines()[0]), 320)
        for expected in (offending_sha, "io-replay-test.py",
                         "docs/testing_standards.md or docs/benchmark.md",
                         "first_error=missing applicable", "corrective_action="):
            self.assertIn(expected, result.stderr)

    def test_valid_replay_and_benchmark_standard_pass(self):
        self.write("tests/runtime/benchmark/io-replay-test.py", "assert True\n")
        self.write("docs/benchmark.md", "# Rules\nOriginal invariant.\nNew replay invariant.\n")
        self.commit("valid replay co-change")
        result = self.audit()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(result.stdout or result.stderr)

    def test_unrelated_standard_fails_workflow_change(self):
        self.write(".github/workflows/verify.yml", "name: synthetic\n")
        self.write("docs/benchmark.md", "# Rules\nOriginal invariant.\nOther benchmark rule.\n")
        self.commit("unrelated standard")
        result = self.audit()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(".github/workflows/verify.yml", result.stderr)
        self.assertIn("docs/testing_standards.md", result.stderr)

    def test_whitespace_only_standard_does_not_qualify(self):
        self.write("tests/runtime/native/check.py", "assert True\n")
        self.write("docs/testing_standards.md", "# Rules   \nOriginal invariant.\n\n")
        self.commit("whitespace only")
        result = self.audit()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tests/runtime/native/check.py", result.stderr)

    def test_mode_only_standard_change_does_not_qualify(self):
        self.write("tests/runtime/native/check.py", "assert True\n")
        (self.repository / "docs/testing_standards.md").chmod(0o755)
        offending_sha = self.commit("mode-only standards metadata")
        result = self.audit()
        self.assertNotEqual(result.returncode, 0)
        for expected in (offending_sha, "tests/runtime/native/check.py",
                         "docs/testing_standards.md",
                         "first_error=missing applicable"):
            self.assertIn(expected, result.stderr)

    def test_compile_standard_is_applicable_to_kernel_build_metadata(self):
        self.write("src/kernel/Makefile", "obj-m += dm-swapz.o\n")
        self.write("docs/compile.md", "# Rules\nOriginal invariant.\nKbuild rule.\n")
        self.commit("kernel build metadata and compile standard")
        result = self.audit()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_compile_standard_is_applicable_to_compile_workflow(self):
        self.write(".github/workflows/product-codec.yml", "name: synthetic\n")
        self.write("docs/compile.md", "# Rules\nOriginal invariant.\nCI compile rule.\n")
        self.commit("compile workflow and compile standard")
        result = self.audit()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_compile_standard_cannot_qualify_project_goals_workflow(self):
        self.write(".github/workflows/project-goals.yml", "name: synthetic\n")
        self.write("docs/compile.md", "# Rules\nOriginal invariant.\nUnrelated compile rule.\n")
        self.commit("project goals and unrelated compile standard")
        result = self.audit()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("docs/testing_standards.md", result.stderr)

    def test_diagnostic_escapes_and_bounds_unusual_repository_path(self):
        unusual = "tests/runtime/native/\n" + ("é" * 80) + ".py"
        self.write(unusual, "assert True\n")
        self.commit("unusual test path")
        result = self.audit()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("\\n", result.stderr)
        self.assertEqual(len(result.stderr.splitlines()), 2)
        self.assertTrue(all(len(line) <= 512 for line in result.stderr.splitlines()))

    def test_multidomain_change_requires_applicable_policy(self):
        self.write("src/kernel/check.c", "int check;\n")
        self.write("tests/runtime/benchmark/io-replay-test.py", "assert True\n")
        self.write("docs/coding_standards.md", "# Rules\nOriginal invariant.\nKernel rule.\n")
        self.commit("two domains")
        result = self.audit()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("io-replay-test.py", result.stderr)

    def test_doc_only_followup_cannot_repair_invalid_published_sha(self):
        self.write("tests/runtime/benchmark/io-replay-test.py", "assert True\n")
        invalid_sha = self.commit("invalid source")
        self.write("docs/benchmark.md", "# Rules\nOriginal invariant.\nLate policy note.\n")
        self.commit("docs-only followup")
        for base, event in ((self.initial, "push"), (invalid_sha, "push"),
                            (None, "workflow_dispatch")):
            with self.subTest(base=base, event=event):
                result = self.audit(base=base, event=event)
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertIn(invalid_sha, result.stderr)

    def test_new_valid_code_commit_can_follow_invalid_history(self):
        self.write("tests/runtime/benchmark/io-replay-test.py", "assert True\n")
        invalid_sha = self.commit("invalid source")
        self.write("tests/runtime/benchmark/io-replay-test.py", "assert False\n")
        self.write("docs/benchmark.md", "# Rules\nOriginal invariant.\nNew replay rule.\n")
        self.commit("new qualified candidate")
        result = self.audit(base=invalid_sha)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_exact_sha_mismatch_and_empty_push_fail(self):
        self.write("docs/benchmark.md", "# Rules\nOriginal invariant.\nNote.\n")
        self.commit("documentation followup")
        self.assertIn("checkout SHA mismatch",
                      self.audit(expected=self.initial).stderr)
        self.assertIn("invalid pushed first-parent range",
                      self.audit(base=self.git("rev-parse", "HEAD")).stderr)

    def test_aggregation_is_race_safe_and_rejects_skipped_jobs(self):
        workflow = WORKFLOW.read_text()
        enforcement = ("python3 -B tests/runtime/native/repository-policy-test.py "
                       "--enforce")
        legacy = "- name: Require standards co-change for implementation work"
        self.assertIn(enforcement, workflow)
        self.assertLess(workflow.index(enforcement), workflow.index(legacy))
        self.assertIn("group: project-goals-" + "$" + "{{ github.ref }}-" +
                      "$" + "{{ github.run_id }}", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertIn("needs: [native-rootless, make-contract, focused-rootless, repository-policy]", workflow)
        expression = (r"^      - name: Reject failed, skipped, or cancelled prerequisite jobs\n"
                      r"        shell: bash\n        run: \|\n"
                      r"(?P<script>(?:^          .*\n)*)")
        match = re.search(expression, workflow, re.MULTILINE)
        self.assertIsNotNone(match)
        script = textwrap.dedent(match.group("script"))
        environment = os.environ.copy()
        environment.update(GITHUB_SHA=self.initial, GITHUB_RUN_ID="1",
                           NATIVE_RESULT="success", MAKE_RESULT="success",
                           FOCUSED_RESULT="success", POLICY_RESULT="success")
        for changes in ({"POLICY_RESULT": "skipped"},
                        {"NATIVE_RESULT": "cancelled"},
                        {"SWAPZ_SKIP_CI_HEAD": "1"}):
            result = subprocess.run(("bash", "-c", script),
                                    env=environment | changes, capture_output=True,
                                    text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not PASS", result.stdout + result.stderr)
        result = subprocess.run(("bash", "-c", script), env=environment,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    if sys.argv[1:] == ["--enforce"]:
        raise SystemExit(enforce_policy())
    unittest.main()
