#!/usr/bin/env python3
"""Unprivileged first-error retention regressions for direct rootless phases."""

import contextlib
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
reporter_spec = importlib.util.spec_from_file_location(
    "swapz_direct_rootless_diagnostics", ROOT / "tests/tools/run-tests.py")
assert reporter_spec is not None and reporter_spec.loader is not None
reporter = importlib.util.module_from_spec(reporter_spec)
reporter_spec.loader.exec_module(reporter)


class DirectRootlessEvidence(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="swapz-direct-evidence-")
        self.addCleanup(temporary.cleanup)
        previous_root = reporter.ROOT
        self.addCleanup(setattr, reporter, "ROOT", previous_root)
        reporter.ROOT = Path(temporary.name)
        self.directory = (reporter.ROOT / "build/tests" /
                          "rootless-failure.ABC12345")
        self.directory.mkdir(parents=True, mode=0o700)
        self.directory.chmod(0o700)
        self.log = self.directory / "diagnostic.log"

    def invoke(self, phase, transcript, *, later_marker="", exit_code=37):
        self.log.write_text(
            "\n--- swapz rootless attribution ---\n"
            f"phase={phase}\nexit_code={exit_code}\n")
        self.log.chmod(0o600)
        marker = (
            f"FAIL: rootless phase={phase} "
            "subtest=unavailable test=unavailable "
            f"exit={exit_code} reason=nonzero_exit phase_s=1 stage_s=2 "
            "line=545 log=build/tests/"
            "rootless-failure.ABC12345/diagnostic.log\n")
        report = {"stages": []}
        with patch.object(
                reporter.subprocess, "run",
                return_value=SimpleNamespace(
                    stdout=transcript + marker + later_marker,
                    returncode=exit_code)), \
                contextlib.redirect_stdout(io.StringIO()):
            status = reporter.run_stage(
                "Native and rootless contracts",
                ["python3", "-c", "pass"], report)
        return status, report["stages"][0], self.log.read_text()

    def test_first_failure_survives_later_unittest_error_and_large_tail(self):
        for phase, test_class in (
                ("test-report-test.py", "ReportContract"),
                ("primary-lifecycle-audit-test.py",
                 "PrimaryLifecycleBehaviorTest")):
            with self.subTest(phase=phase):
                transcript = (
                    "FAIL: expected negative control from passing suite\n"
                    f"test_first (__main__.{test_class}.test_first) ... FAIL\n"
                    f"test_teardown (__main__.{test_class}.test_teardown) "
                    "... ERROR\n"
                    "======================================================================\n"
                    f"ERROR: test_teardown (__main__.{test_class}.test_teardown)\n"
                    "RuntimeError: LATER_TEARDOWN\n"
                    "======================================================================\n"
                    f"FAIL: test_first (__main__.{test_class}.test_first)\n"
                    "Traceback (most recent call last):\n"
                    "AssertionError: PRIVATE_FIRST_CAUSE\n"
                    "======================================================================\n"
                    + "x" * 300000 + "\n")
                code, record, evidence = self.invoke(phase, transcript)
                self.assertEqual((code, record["status"], record["exit_code"]),
                                 (37, "FAIL", 37))
                self.assertIn("AssertionError: PRIVATE_FIRST_CAUSE", evidence)
                self.assertIn("first matched direct rootless", evidence)
                selected = evidence.split("first matched direct rootless", 1)[1]
                self.assertNotIn("LATER_TEARDOWN",
                                 selected.split("official stage merged", 1)[0])
                self.assertNotIn("PRIVATE_FIRST_CAUSE", record["diagnostic"])
                self.assertIn("test=unavailable", record["diagnostic"])
                self.assertLessEqual(self.log.stat().st_size, 262144)
                self.assertEqual(self.log.stat().st_mode & 0o777, 0o600)

    def test_unknown_phase_retains_context_not_guessed_identity(self):
        status, record, evidence = self.invoke(
            "source-contract-test.py",
            "Traceback (most recent call last):\n"
            "RuntimeError: PRIVATE_UNKNOWN_CAUSE\n")
        self.assertEqual((status, record["exit_code"]), (37, 37))
        self.assertIn("PRIVATE_UNKNOWN_CAUSE", evidence)
        self.assertIn("private context only", evidence)
        self.assertNotIn("first matched", evidence)
        self.assertIn("test=unavailable", record["diagnostic"])

    def test_silent_failure_does_not_claim_a_traceback(self):
        status, record, evidence = self.invoke("test-report-test.py", "")
        self.assertEqual((status, record["exit_code"]), (37, 37))
        self.assertNotIn("first matched", evidence)
        self.assertNotIn("official stage merged", evidence)

    def test_captured_log_is_never_appended_twice(self):
        self.log.write_text("PRE_CAPTURED_CHILD_STDERR\n")
        self.log.chmod(0o600)
        marker = (
            "FAIL: rootless phase=package-dkms-test.py "
            "subtest=unavailable test=unavailable exit=37 "
            "reason=nonzero_exit phase_s=1 stage_s=2 line=545 "
            "log=build/tests/rootless-failure.ABC12345/diagnostic.log\n")
        record = {"stages": []}
        with patch.object(
                reporter.subprocess, "run",
                return_value=SimpleNamespace(
                    stdout="PRIVATE_RAW_TRACEBACK\n" + marker,
                    returncode=37)), contextlib.redirect_stdout(io.StringIO()):
            reporter.run_stage(
                "Native and rootless contracts", ["python3", "-c", "pass"],
                record)
        self.assertEqual(self.log.read_text(), "PRE_CAPTURED_CHILD_STDERR\n")

    def test_later_marker_refuses_stale_failure_evidence(self):
        marker = (
            "FAIL: rootless phase=another-suite.py "
            "subtest=unavailable test=unavailable exit=37 "
            "reason=nonzero_exit phase_s=2 stage_s=3 line=548 "
            "log=unavailable\n")
        _, _, evidence = self.invoke(
            "test-report-test.py", "AssertionError: PRIVATE_CAUSE\n",
            later_marker=marker)
        self.assertNotIn("official stage merged", evidence)

    def test_unsafe_log_permissions_refuse_append(self):
        self.log.write_text("\n--- swapz rootless attribution ---\n")
        self.log.chmod(0o644)
        marker = (
            "FAIL: rootless phase=test-report-test.py "
            "subtest=unavailable test=unavailable exit=37 "
            "reason=nonzero_exit phase_s=1 stage_s=2 line=545 "
            "log=build/tests/rootless-failure.ABC12345/diagnostic.log\n")
        report = {"stages": []}
        with patch.object(
                reporter.subprocess, "run",
                return_value=SimpleNamespace(
                    stdout="AssertionError: PRIVATE_CAUSE\n" + marker,
                    returncode=37)), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(reporter.run_stage(
                "Native and rootless contracts", ["python3", "-c", "pass"],
                report), 37)
        self.assertNotIn("PRIVATE_CAUSE", self.log.read_text())


if __name__ == "__main__":
    unittest.main()
