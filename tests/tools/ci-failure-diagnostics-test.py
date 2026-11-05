"""Rootless, synthetic failure-attribution contracts for private CI diagnostics.

Run directly for focused development evidence; this does not add a new
qualification stage or alter the official suite selection.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "tests/tools/product_goals.py"


class NativeCiFailureDiagnostics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("ci_failure_contract", MODULE)
        cls.diagnostics = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.diagnostics)

    def diagnose(self, log, exit_code=1, suite="native-rootless"):
        return self.diagnostics.diagnose_ci_failure(
            log.splitlines(), exit_code, suite)

    def test_native_assertion_keeps_suite_test_and_first_diagnostic(self):
        failure = self.diagnose(
            "FAIL: test_extent (__main__.NativeCase)\n"
            "AssertionError: expected bytes=4096 observed=8192\n"
            "ERROR: tearDown (__main__.NativeCase)\n"
            "RuntimeError: cleanup failed\n")
        self.assertEqual(failure["test"], "__main__.NativeCase.test_extent")
        self.assertEqual(failure["phase"], "native-rootless")
        self.assertEqual(failure["category"], "RUNTIME_ASSERTION")
        self.assertEqual(failure["first_error"],
                         "AssertionError: expected bytes=4096 observed=8192")
        self.assertEqual(failure["exit_code"], 1)
        self.assertIn("assertions", failure["expected_contract"])
        self.assertEqual(failure["observed"], failure["first_error"])

    def test_unrecognized_first_test_cannot_borrow_cleanup_exception(self):
        failure = self.diagnose(
            "ERROR: test_nested (__main__.NestedCase)\n"
            "original test stopped without a Python traceback\n"
            "ERROR: tearDown (__main__.NestedCase)\n"
            "ValueError: secondary cleanup parser failed\n")
        self.assertEqual(failure["test"], "__main__.NestedCase.test_nested")
        self.assertEqual(failure["first_error"],
                         "ERROR: test_nested (__main__.NestedCase)")
        self.assertEqual(failure["category"], "UNKNOWN_FAILURE")
        self.assertNotIn("secondary", failure["observed"])

    def test_rootless_marker_preserves_nested_phase_and_child_status(self):
        marker = (
            "FAIL: rootless phase=package-dkms-test.py subtest=rollback-check "
            "exit=37 reason=unittest_error phase_s=2 stage_s=5 line=315 "
            "log=build/tests/rootless-failure.Abc123xy/diagnostic.log")
        failure = self.diagnose(marker, 1)
        self.assertEqual(failure["test"],
                         "package-dkms-test.py[rollback-check]")
        self.assertEqual(failure["phase"], "package-dkms-test.py")
        self.assertEqual(failure["exit_code"], 1)
        self.assertEqual(failure["child_exit_code"], 37)
        self.assertEqual(failure["rootless_reason"], "unittest_error")
        self.assertIn("phase=package-dkms-test.py", failure["first_error"])
        self.assertNotEqual(failure["status"], "PASS")

    def test_timeout_signal_and_shell_exit_remain_distinct(self):
        timeout = self.diagnose("", 124)
        self.assertEqual(timeout["category"], "INFRASTRUCTURE")
        self.assertIn("returned 124", timeout["reason"])
        self.assertIn("not proven", timeout["reason"])
        shell_exit = self.diagnose("", 143)
        self.assertEqual(shell_exit["status"], "CANCELLED")
        self.assertNotIn("termination", shell_exit)
        signalled = self.diagnose("", -11)
        self.assertEqual(signalled["status"], "FAIL")
        self.assertEqual(signalled["exit_code"], -11)
        self.assertEqual(signalled["termination"], "signal SIGSEGV")
        self.assertIn("SIGSEGV", signalled["first_error"])
        rootless_timeout = self.diagnose(
            "FAIL: rootless phase=Makefile native and metadata "
            "subtest=unavailable exit=124 reason=timeout_or_exit_124 "
            "phase_s=1 stage_s=2 line=22 log=unavailable", 1)
        self.assertEqual(rootless_timeout["child_exit_code"], 124)
        self.assertEqual(rootless_timeout["category"], "INFRASTRUCTURE")
        self.assertIn("not proof", rootless_timeout["reason"])

    def test_native_compiler_error_keeps_first_compile_failure(self):
        failure = self.diagnose(
            "src/kernel/foo.c:19:3: error: incompatible pointer type\n"
            "make: *** [Makefile:99: compile-tests] Error 2\n"
            "FAIL: rootless phase=Makefile native and metadata "
            "subtest=unavailable exit=2 reason=nonzero_exit "
            "phase_s=1 stage_s=2 line=22 log=unavailable", 2)
        self.assertEqual(failure["category"], "NATIVE_COMPILE")
        self.assertEqual(failure["phase"], "Makefile native and metadata")
        self.assertEqual(failure["first_error"],
                         "src/kernel/foo.c:19:3: error: incompatible pointer type")
        self.assertEqual(failure["child_exit_code"], 2)

    def test_redaction_and_bounded_diagnostic_contract(self):
        safe_line = self.diagnostics._ci_safe_line(
            "AssertionError: token=privatevalue " + "x" * 6000 +
            " token=tailprivate")
        self.assertNotIn("privatevalue", safe_line)
        self.assertNotIn("tailprivate", safe_line)
        self.assertLessEqual(len(safe_line), 320)
        failure = self.diagnose(
            "FAIL: test_secret (__main__.NativeCase)\n"
            "AssertionError: token=privatevalue expected 1 observed 2")
        self.assertNotIn("privatevalue", json.dumps(failure))
        self.assertIn("<redacted>", failure["first_error"])
        fake_marker = self.diagnose(
            "FAIL: rootless phase=../secret-path subtest=unavailable "
            "exit=4 reason=nonzero_exit phase_s=1 stage_s=1 "
            "line=1 log=/tmp/private.log")
        self.assertEqual(fake_marker["test"], "native-rootless")
        self.assertNotIn("child_exit_code", fake_marker)

    def test_real_synthetic_child_launch_failure_preserves_errno_and_artifact(self):
        # Only execute a deliberately absent command, never a device helper.
        source = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
            capture_output=True, text=True).stdout.strip()
        environment = os.environ.copy()
        environment.update({"GITHUB_SHA": source, "GITHUB_JOB": "synthetic",
                            "SWAPZ_CI_ARTIFACT_NAME": "project-goals-synthetic-absent"})
        suite = "ci-synthetic-absent"
        log = ROOT / "build/ci-logs" / (suite + ".log")
        self.addCleanup(log.unlink, missing_ok=True)
        log.unlink(missing_ok=True)
        failed = subprocess.run(
            [sys.executable, "-B", str(MODULE), "ci-run", "--suite", suite,
             "--", "swapz-synthetic-command-that-does-not-exist"],
            cwd=ROOT, env=environment, text=True, capture_output=True,
            timeout=12)
        self.assertEqual(failed.returncode, 127, failed.stderr)
        diagnostic = json.loads(
            failed.stdout.split("SWAPZ_CI_FAILURE=", 1)[1])
        self.assertEqual(diagnostic["launch_errno"], 2)
        self.assertEqual(diagnostic["exit_code"], 127)
        self.assertEqual(diagnostic["category"], "INFRASTRUCTURE")
        self.assertIn("No such file or directory", diagnostic["first_error"])
        self.assertEqual(diagnostic["artifact"],
                         "project-goals-synthetic-absent")
        self.assertEqual(diagnostic["log"],
                         "build/ci-logs/ci-synthetic-absent.log")
        self.assertTrue(log.exists())
        self.assertEqual(json.loads(log.read_text().splitlines()[0].split(
            "SWAPZ_CI_FAILURE=", 1)[1]), diagnostic)

    def test_retention_failure_does_not_replace_test_exit(self):
        # A synthetic mode-0600 log-write failure must not change the cause.
        source = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
            capture_output=True, text=True).stdout.strip()
        environment = os.environ.copy()
        environment["GITHUB_SHA"] = source
        with mock.patch.dict(os.environ, environment, clear=True), \
                mock.patch.object(self.diagnostics, "_ci_retain_log",
                                  side_effect=OSError(28, "no space")):
            from contextlib import redirect_stdout
            from io import StringIO
            output = StringIO()
            with redirect_stdout(output):
                exit_code = self.diagnostics._ci_run([
                    "--suite", "ci-synthetic-write-error", "--",
                    sys.executable, "-c", "raise AssertionError('first cause')"])
        self.assertEqual(exit_code, 1)
        diagnostic = json.loads(output.getvalue().split(
            "SWAPZ_CI_FAILURE=", 1)[1])
        self.assertEqual(diagnostic["first_error"], "AssertionError: first cause")
        self.assertEqual(diagnostic["log"], "unavailable")
        self.assertEqual(diagnostic["diagnostic_errno"], 28)


if __name__ == "__main__":
    unittest.main()
