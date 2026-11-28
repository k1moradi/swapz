#!/usr/bin/env python3
"""Run the actual kernel-debug push guard in disposable main-only Git repos."""
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


WORKFLOW = Path(__file__).resolve().parents[3] / ".github/workflows/kernel-debug.yml"
GUARD_NAME = "Verify exact direct-main range and complete standards prefix"
STANDARD = Path("docs/testing_standards.md")
ORIGINAL = b"# Testing rules\nHistorical invariant.\n"
SUFFIX = b"\nNew invariant.\n"


def guard_script(workflow, name=GUARD_NAME):
    # Extract the actual run block, rather than maintaining a second guard.
    step = workflow.split(f"      - name: {name}\n", 1)[1]
    step = step.split("\n      - name: ", 1)[0]
    return textwrap.dedent(step.split("        run: |\n", 1)[1])


class MainRangeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="swapz-range-fixture-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "--quiet", "-b", "main")
        self.git("config", "user.name", "Range fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.write(STANDARD, ORIGINAL)
        self.base = self.commit("base")
        self.workflow = WORKFLOW.read_text(encoding="utf-8")
        self.script = guard_script(self.workflow)

    def git(self, *args, cwd=None):
        result = subprocess.run(("git", *args), cwd=cwd or self.repo,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def write(self, name, content):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "--quiet", "-m", message)
        return self.git("rev-parse", "HEAD")

    def change(self, content=b"ordinary change\n", standards=None):
        self.write("tracked.txt", content)
        if standards is not None:
            self.write(STANDARD, standards)
        return self.commit("fixture transition")

    def guard(self, before, source, *, ref="refs/heads/main", cwd=None):
        env = os.environ.copy()
        for key, value in (("BEFORE", before), ("SOURCE", source), ("PUSH_REF", ref)):
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return subprocess.run(("bash", "-c", self.script), cwd=cwd or self.repo,
                              env=env, capture_output=True, text=True, timeout=25)

    def accept(self, before, source):
        result = self.guard(before, source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout + result.stderr, "")

    def refuse(self, before, source, reason, *, commit=None, **kwargs):
        result = self.guard(before, source, **kwargs)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn(f"first_error={reason}\n", result.stderr)
        self.assertEqual(result.stderr.count("first_error="), 1)
        self.assertIn("corrective_action=", result.stderr)
        if commit is not None:
            self.assertIn(f"commit={commit} ", result.stderr)
        self.assertNotIn(str(self.root), result.stderr)
        self.assertNotIn("PRIVATE_MARKER", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_actual_workflow_wiring(self):
        rootless = self.workflow.split("  sparse-compile-only:", 1)[0]
        self.assertIn("branches: [main]", rootless)
        self.assertIn("          fetch-depth: 0\n", rootless)
        self.assertNotIn("fetch-depth: 2", rootless)
        self.assertIn("if: github.event_name == 'push'", rootless)
        self.assertIn("BEFORE: ${{ github.event.before }}", rootless)
        self.assertIn("SOURCE: ${{ github.sha }}", rootless)
        self.assertIn("PUSH_REF: ${{ github.ref }}", rootless)
        test_path = "tests/runtime/native/kernel-debug-main-range-test.py"
        self.assertIn(f"- '{test_path}'", rootless)
        self.assertIn(f"python3 -B {test_path} -v", rootless)
        self.assertIn("python3 -B tests/runtime/native/kernel-debug-qualification-test.py -v", rootless)
        self.assertIn("python3 -B tests/runtime/native/round093-native-evidence-collector-test.py -v", rootless)
        self.assertIn("set -euo pipefail", self.script)
        self.assertIn("python3 -B - <<'PY'", self.script)

    def test_single_direct_commit_unchanged_or_appended_standards(self):
        first = self.change()
        self.accept(self.base, first)
        last = self.change(b"second\n", ORIGINAL + SUFFIX)
        self.accept(first, last)

    def test_three_commit_direct_main_push(self):
        first = self.change(standards=ORIGINAL + SUFFIX)
        second = self.change(b"second\n")
        last = self.change(b"third\n", ORIGINAL + SUFFIX + b"Final suffix.\n")
        self.assertEqual(self.git("rev-list", "--count", f"{self.base}..{last}"), "3")
        self.assertEqual(self.git("rev-list", "--parents", "-n", "1", last), f"{last} {second}")
        self.assertNotEqual(first, last)
        self.accept(self.base, last)

    def test_invalid_or_missing_source_and_before(self):
        source = self.change()
        invalid = (None, "", "0" * 40, "a" * 39, "A" * 40,
                   "PRIVATE_MARKER\n", "--help", source + "\n")
        for value in invalid:
            with self.subTest(field="SOURCE", value=repr(value)):
                self.refuse(self.base, value, "invalid_source")
            with self.subTest(field="BEFORE", value=repr(value)):
                self.refuse(value, source, "invalid_before")
        self.refuse(self.base, self.base, "source_checkout_mismatch")
        self.refuse(source, source, "invalid_range")
        self.refuse("f" * 40, source, "commit_unavailable")
        self.refuse(self.git("rev-parse", f"{source}^{{tree}}"), source,
                    "commit_object_required")
        for ref in (None, "refs/tags/main", "refs/heads/PRIVATE_MARKER"):
            self.refuse(self.base, source, "not_main_push", ref=ref)
        self.git("checkout", "--quiet", "--detach", source)
        self.refuse(self.base, source, "not_main_checkout")

    def test_shallow_and_missing_history(self):
        first = self.change()
        self.change(b"second\n")
        source = self.change(b"third\n")
        shallow = self.root / "shallow"
        self.git("clone", "--quiet", "--depth=2", "--branch", "main",
                 self.repo.as_uri(), str(shallow), cwd=self.root)
        self.assertEqual(self.git("rev-parse", "--is-shallow-repository", cwd=shallow), "true")
        self.refuse(self.base, source, "shallow_history", cwd=shallow)
        # A non-shallow repository with a missing intermediate commit must
        # also refuse; do not repair or fetch anything from within the guard.
        (self.repo / ".git/objects" / first[:2] / first[2:]).unlink()
        self.refuse(self.base, source, "before_not_ancestor_or_history_missing")

    def test_nonancestor_merge_and_side_parent_base(self):
        first = self.change()
        tree = self.git("rev-parse", f"{first}^{{tree}}")
        # Create a synthetic divergent commit object without another branch.
        side = self.git("commit-tree", tree, "-p", self.base, "-m", "side")
        self.refuse(side, first, "before_not_ancestor_or_history_missing")
        merge = self.git("commit-tree", tree, "-p", first, "-p", side, "-m", "merge")
        self.git("update-ref", "refs/heads/main", merge, first)
        self.refuse(self.base, merge, "nonlinear_or_discontinuous_range", commit=merge)
        self.refuse(side, merge, "nonlinear_or_discontinuous_range", commit=first)

    def test_intermediate_whitespace_error_cannot_be_restored(self):
        bad = self.change(b"PRIVATE_MARKER trailing whitespace \n")
        source = self.change(b"clean\n", ORIGINAL + SUFFIX)
        self.git("diff", "--check", self.base, source)  # net diff is clean
        self.refuse(self.base, source, "commit_diff_check_failed", commit=bad)

    def test_intermediate_standards_deletion_cannot_be_restored(self):
        bad = self.change(standards=b"# Testing rules\n")
        source = self.change(b"clean\n", ORIGINAL + SUFFIX)
        self.git("diff", "--check", self.base, source)
        self.refuse(self.base, source, "historical_standards_prefix_changed", commit=bad)

    def test_removed_standards_file_cannot_be_restored(self):
        (self.repo / STANDARD).unlink()
        bad = self.commit("remove standards")
        source = self.change(standards=ORIGINAL + SUFFIX)
        self.refuse(self.base, source, "standards_regular_blob_required", commit=bad)

    def test_standards_prefix_is_per_transition_and_byte_exact(self):
        first = self.change(standards=ORIGINAL + SUFFIX)
        source = self.change(b"second\n", ORIGINAL + b"Different suffix.\n")
        self.refuse(first, source, "historical_standards_prefix_changed", commit=source)
        self.refuse(self.base, source, "historical_standards_prefix_changed", commit=source)

    def test_checkout_standards_must_match_exact_source(self):
        source = self.change(standards=ORIGINAL + SUFFIX)
        self.write(STANDARD, ORIGINAL + SUFFIX + b"Uncommitted extra text.\n")
        self.refuse(self.base, source, "checkout_standards_mismatch", commit=source)


if __name__ == "__main__":
    unittest.main()
