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

        makefile_lines = (
            ROOT / "tests/suites/Makefile").read_text().splitlines()

        def recipe_line(target):
            target_index = next(
                index for index, line in enumerate(makefile_lines)
                if line.startswith(target + ":"))
            for index in range(target_index + 1, len(makefile_lines)):
                line = makefile_lines[index]
                if line.startswith("\t"):
                    return index + 1
                if line and not line[0].isspace() and ":" in line:
                    break
            raise AssertionError(f"missing recipe line for {target}")

        cls.mapping_recipe_line = recipe_line("test-mapping")
        cls.gc_recipe_line = recipe_line("test-gc")
        cls.userspace_recipe_line = recipe_line("test-userspace")

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
            "FAIL: rootless phase=package-dkms-test.py subtest=rollback-check test=unavailable "
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


    def test_nested_make_target_preserves_exit_and_hides_private_evidence(self):
        marker = (
            "FAIL: rootless phase=Makefile native and metadata "
            "subtest=test-mapping test=unavailable exit=2 reason=nonzero_exit "
            "phase_s=1 stage_s=2 line=476 "
            "log=build/tests/rootless-failure.Abc123xy/diagnostic.log")
        failure = self.diagnose(
            "FAIL: test_expected (__main__.EarlierPassingCase)\n"
            "AssertionError: unrelated expected negative fixture\n"
            "mapping-authority: Assertion failed: PRIVATE_RESOURCE_IDENTIFIER\n"
            f"make[1]: *** [Makefile:{self.mapping_recipe_line}: "
            "test-mapping] Error 134\n"
            f"make[1]: *** [Makefile:{self.userspace_recipe_line}: "
            "test-userspace] Error 1\n"
            + marker, 1)
        self.assertEqual(failure["status"], "FAIL")
        self.assertEqual(failure["category"], "RUNTIME_ASSERTION")
        self.assertEqual(failure["phase"], "Makefile native and metadata")
        self.assertEqual(failure["test"],
                         "Makefile native and metadata[test-mapping]")
        self.assertEqual(failure["exit_code"], 1)
        self.assertEqual(failure["child_exit_code"], 2)
        self.assertEqual(failure["rootless_reason"], "nonzero_exit")
        self.assertEqual(
            failure["first_error"],
            f"make[1]: *** [Makefile:{self.mapping_recipe_line}: "
            "test-mapping] Error 134")
        self.assertEqual(failure["observed"], failure["first_error"])
        self.assertEqual(failure["expected_contract"],
                         "test assertions and runtime contracts hold")
        self.assertEqual(
            failure["rootless_private_log"],
            "build/tests/rootless-failure.Abc123xy/diagnostic.log")
        self.assertNotIn("diagnostic.log", failure["first_error"])
        self.assertNotIn("PRIVATE_RESOURCE_IDENTIFIER", json.dumps(failure))
        self.assertNotIn("EarlierPassingCase", json.dumps(failure))
        self.assertNotIn("test-userspace", json.dumps(failure))


    def test_first_make_error_survives_later_abort_and_bad_final_marker(self):
        marker = (
            "FAIL: rootless phase=Makefile native and metadata "
            "subtest=test-mapping test=unavailable exit=2 reason=nonzero_exit "
            "phase_s=1 stage_s=2 line=476 "
            "log=build/tests/rootless-failure.Abc123xy/diagnostic.log")
        first = (
            f"make[1]: *** [Makefile:{self.mapping_recipe_line}: "
            "test-mapping] Error 1")
        later = (
            f"make[1]: *** [Makefile:{self.userspace_recipe_line}: "
            "test-userspace] Error 134")
        failure = self.diagnose(first + "\n" + later + "\n" + marker, 1)
        self.assertEqual(failure["category"], "UNKNOWN_FAILURE")
        self.assertEqual(failure["test"],
                         "Makefile native and metadata[test-mapping]")
        self.assertEqual(failure["first_error"], first)
        self.assertEqual(failure["child_exit_code"], 2)
        self.assertEqual(
            failure["rootless_private_log"],
            "build/tests/rootless-failure.Abc123xy/diagnostic.log")
        self.assertNotIn(later, json.dumps(failure))

        # A later compiler error cannot displace the first failed target.
        later_compile = (
            "/private/source.c:12: error: PRIVATE_RESOURCE_IDENTIFIER")
        compiled = self.diagnose(
            first + "\n" + later_compile + "\n" + marker, 1)
        self.assertEqual(compiled["first_error"], first)
        self.assertEqual(compiled["category"], "UNKNOWN_FAILURE")
        self.assertNotIn("PRIVATE_RESOURCE_IDENTIFIER", json.dumps(compiled))

        # A source recipe owned by another target cannot authenticate the
        # marker's target even when the text itself claims test-mapping.
        wrong_owner = (
            f"make[1]: *** [Makefile:{self.gc_recipe_line}: "
            "test-mapping] Error 134")
        rejected = self.diagnose(wrong_owner + "\n" + marker, 1)
        self.assertEqual(rejected["category"], "UNKNOWN_FAILURE")
        self.assertIn("rootless phase=Makefile", rejected["first_error"])
        self.assertNotIn(wrong_owner, json.dumps(rejected))
        self.assertEqual(
            rejected["rootless_private_log"],
            "build/tests/rootless-failure.Abc123xy/diagnostic.log")

        # An unrelated target cannot donate its abort to the validated target.
        unmatched = self.diagnose(later + "\n" + marker, 1)
        self.assertEqual(unmatched["category"], "UNKNOWN_FAILURE")
        self.assertIn("rootless phase=Makefile", unmatched["first_error"])
        self.assertEqual(unmatched["child_exit_code"], 2)

        # A final malformed marker invalidates earlier marker and raw child
        # attribution, including otherwise valid Make-shaped failure text.
        stale = self.diagnose(
            first + "\n" + marker + "\nFAIL: rootless phase=../private "
            "subtest=unavailable test=unavailable exit=99 "
            "reason=nonzero_exit phase_s=1 stage_s=2 line=1 "
            "log=/tmp/private.log", 1)
        self.assertEqual(stale["phase"], "native-rootless")
        self.assertEqual(stale["test"], "native-rootless")
        self.assertEqual(
            stale["first_error"],
            "rootless failure marker malformed or unverified")
        self.assertNotIn("child_exit_code", stale)
        self.assertNotIn("rootless_private_log", stale)
        self.assertNotIn("test-mapping", json.dumps(stale))
        self.assertNotIn("private.log", json.dumps(stale))

    def test_unittest_error_heading_is_not_compiler_error(self):
        reporter_spec = importlib.util.spec_from_file_location(
            "swapz_ci_native_failure_reporter",
            ROOT / "tests/tools/run-tests.py")
        reporter = importlib.util.module_from_spec(reporter_spec)
        reporter_spec.loader.exec_module(reporter)
        phase, diagnostic = reporter.failure_context(
            "ERROR: tearDown (__main__.SyntheticCase)\n",
            loaded=False, default_phase="Native and rootless contracts",
            child_exit_code=1)
        self.assertEqual(phase, "Native and rootless contracts")
        self.assertNotIn("Native build error", diagnostic)
        self.assertNotIn("SyntheticCase", diagnostic)

        _, compiler_diagnostic = reporter.failure_context(
            "src/fixture.c:42:8: error: incompatible pointer type\n",
            loaded=False, default_phase="Native and rootless contracts",
            child_exit_code=2)
        self.assertIn("Native build error", compiler_diagnostic)

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
            "subtest=unavailable test=unavailable exit=124 reason=timeout_or_exit_124 "
            "phase_s=1 stage_s=2 line=22 log=unavailable", 1)
        self.assertEqual(rootless_timeout["child_exit_code"], 124)
        self.assertEqual(rootless_timeout["category"], "INFRASTRUCTURE")
        self.assertIn("watchdog not proven", rootless_timeout["reason"])
        self.assertNotIn("termination", rootless_timeout)

    def test_native_compiler_error_keeps_first_compile_failure(self):
        failure = self.diagnose(
            "src/kernel/foo.c:19:3: error: incompatible pointer type\n"
            "make: *** [Makefile:99: compile-tests] Error 2\n"
            "FAIL: rootless phase=Makefile native and metadata "
            "subtest=unavailable test=unavailable exit=2 reason=nonzero_exit "
            "phase_s=1 stage_s=2 line=22 log=unavailable", 2)
        self.assertEqual(failure["category"], "NATIVE_COMPILE")
        self.assertEqual(failure["phase"], "Makefile native and metadata")
        self.assertEqual(failure["first_error"],
                         "src/kernel/foo.c:19:3: error: incompatible pointer type")
        self.assertEqual(failure["child_exit_code"], 2)

    def test_authenticated_rootless_fixture_compile_stays_private(self):
        marker = (
            "FAIL: rootless phase=Makefile native and metadata "
            "subtest=compile test=swapz-primary-late-race-test.py "
            "exit=2 reason=native_compile phase_s=1 stage_s=2 line=441 "
            "log=build/tests/rootless-failure.Abc123xy/diagnostic.log")
        failure = self.diagnose(
            "/private/source/production.c:4923:13: error: implicit declaration "
            "of function PRIVATE_DECLARATION\n" + marker, 2)
        self.assertEqual(failure["status"], "FAIL")
        self.assertEqual(failure["category"], "NATIVE_COMPILE")
        self.assertEqual(failure["phase"], "Makefile native and metadata")
        self.assertEqual(failure["test"], "swapz-primary-late-race-test.py")
        self.assertEqual(failure["exit_code"], 2)
        self.assertEqual(failure["child_exit_code"], 2)
        self.assertEqual(failure["rootless_reason"], "native_compile")
        self.assertIn("reason=native_compile", failure["first_error"])
        self.assertIn("swapz-primary-late-race-test.py",
                      failure["first_error"])
        self.assertIn("build/tests/rootless-failure.Abc123xy/diagnostic.log",
                      failure["first_error"])
        self.assertNotIn("PRIVATE_DECLARATION", failure["first_error"])
        self.assertNotIn("/private/", failure["first_error"])
        self.assertNotIn("PRIVATE_DECLARATION", json.dumps(failure))
        self.assertNotIn("/private/", json.dumps(failure))

        unauthenticated = self.diagnose(
            marker.replace("subtest=compile", "subtest=unavailable"), 2)
        self.assertEqual(unauthenticated["category"], "UNKNOWN_FAILURE")
        self.assertEqual(unauthenticated["test"],
                         "Makefile native and metadata")
        self.assertIn("did not authenticate", unauthenticated["reason"])
        self.assertNotIn("swapz-primary-late-race-test.py",
                         unauthenticated["first_error"])
        self.assertNotIn("swapz-primary-late-race-test.py",
                         json.dumps(unauthenticated))

        wrong_reason = self.diagnose(
            marker.replace("reason=native_compile",
                           "reason=unittest_assertion"), 2)
        self.assertEqual(wrong_reason["category"], "UNKNOWN_FAILURE")
        self.assertEqual(wrong_reason["test"], "Makefile native and metadata")
        self.assertIn("did not authenticate", wrong_reason["reason"])
        self.assertNotIn("swapz-primary-late-race-test.py",
                         wrong_reason["first_error"])
        self.assertNotIn("swapz-primary-late-race-test.py",
                         json.dumps(wrong_reason))
        self.assertNotIn("[compile]", json.dumps(wrong_reason))

        forged_nonzero = self.diagnose(
            "/private/source/production.c:4923:13: error: "
            "PRIVATE_DECLARATION\n" +
            marker.replace("reason=native_compile", "reason=nonzero_exit")
                  .replace("subtest=compile", "subtest=unavailable"), 2)
        self.assertEqual(forged_nonzero["category"], "UNKNOWN_FAILURE")
        self.assertEqual(forged_nonzero["test"],
                         "Makefile native and metadata")
        self.assertIn("did not authenticate", forged_nonzero["reason"])
        self.assertNotIn("PRIVATE_DECLARATION", json.dumps(forged_nonzero))
        self.assertNotIn("/private/", json.dumps(forged_nonzero))
        self.assertNotIn("swapz-primary-late-race-test.py",
                         json.dumps(forged_nonzero))

        forged_timeout = self.diagnose(
            marker.replace("reason=native_compile", "reason=timeout_or_exit_124")
                  .replace("exit=2 ", "exit=124 "), 1)
        self.assertEqual(forged_timeout["status"], "FAIL")
        self.assertEqual(forged_timeout["category"], "UNKNOWN_FAILURE")
        self.assertEqual(forged_timeout["test"],
                         "Makefile native and metadata")
        self.assertIn("did not authenticate", forged_timeout["reason"])
        self.assertNotIn("[compile]", json.dumps(forged_timeout))

        forged_interrupt = self.diagnose(
            marker.replace("reason=native_compile", "reason=received_TERM")
                  .replace("exit=2 ", "exit=143 "), 1)
        self.assertEqual(forged_interrupt["status"], "FAIL")
        self.assertEqual(forged_interrupt["category"], "UNKNOWN_FAILURE")
        self.assertEqual(forged_interrupt["test"],
                         "Makefile native and metadata")
        self.assertIn("did not authenticate", forged_interrupt["reason"])
        self.assertNotIn("[compile]", json.dumps(forged_interrupt))

    def test_rootless_signal_style_exit_remains_ambiguous(self):
        marker = (
            "FAIL: rootless phase=package-dkms-test.py subtest=unavailable test=unavailable "
            "exit=143 reason=signal_or_child_exit phase_s=1 stage_s=2 "
            "line=302 log=unavailable")
        failure = self.diagnose(marker, 1)
        self.assertEqual(failure["status"], "FAIL")
        self.assertEqual(failure["category"], "UNKNOWN_FAILURE")
        self.assertEqual(failure["child_exit_code"], 143)
        self.assertEqual(failure["phase"], "package-dkms-test.py")
        self.assertIn("indistinguishable", failure["reason"])

    def test_current_rootless_relay_and_colon_phase_markers_are_recognized(self):
        relay = self.diagnose(
            "FAIL: rootless phase=package-dkms-test.py subtest=unavailable test=unavailable "
            "exit=1 reason=stderr_relay_failure phase_s=2 stage_s=5 "
            "line=303 log=unavailable", 1)
        self.assertEqual(relay["category"], "INFRASTRUCTURE")
        self.assertEqual(relay["phase"], "package-dkms-test.py")
        self.assertEqual(relay["child_exit_code"], 1)
        self.assertEqual(relay["rootless_reason"], "stderr_relay_failure")

        syntax = self.diagnose(
            "FAIL: rootless phase=C syntax: physical lifecycle seam "
            "subtest=unavailable test=unavailable exit=9 reason=nonzero_exit "
            "phase_s=1 stage_s=6 line=351 log=unavailable", 1)
        self.assertEqual(syntax["phase"], "C syntax: physical lifecycle seam")
        self.assertEqual(syntax["child_exit_code"], 9)
        self.assertIn("rootless phase=C syntax:", syntax["first_error"])

    def test_rootless_marker_is_native_suite_scoped_path_safe_and_last_wins(self):
        unsafe = self.diagnose(
            "FAIL: rootless phase=../secret-path subtest=unavailable test=unavailable "
            "exit=4 reason=nonzero_exit phase_s=1 stage_s=1 "
            "line=1 log=unavailable", 4)
        self.assertEqual(unsafe["phase"], "native-rootless")
        self.assertNotIn("child_exit_code", unsafe)
        self.assertNotIn("secret-path", unsafe["first_error"])

        out_of_suite = self.diagnostics.diagnose_ci_failure(
            ["FAIL: rootless phase=package-dkms-test.py subtest=unavailable test=unavailable "
             "exit=37 reason=nonzero_exit phase_s=1 stage_s=2 "
             "line=303 log=unavailable"],
            37, "make-interface")
        self.assertEqual(out_of_suite["phase"], "make-interface")
        self.assertNotIn("child_exit_code", out_of_suite)

        last = self.diagnose(
            "FAIL: rootless phase=fake-child subtest=unavailable test=unavailable "
            "exit=99 reason=nonzero_exit phase_s=1 stage_s=1 "
            "line=1 log=unavailable\n"
            "FAIL: rootless phase=package-dkms-test.py subtest=preflight test=unavailable "
            "exit=37 reason=unittest_error phase_s=2 stage_s=3 "
            "line=303 log=unavailable", 1)
        self.assertEqual(last["phase"], "package-dkms-test.py")
        self.assertEqual(last["child_exit_code"], 37)
        self.assertEqual(last["test"], "package-dkms-test.py[preflight]")

    def test_unrelated_earlier_negative_output_cannot_replace_silent_phase(self):
        log = (
            "BLOCKED: expected negative fixture: Permission denied\n" +
            "\n".join("ordinary successful output" for _ in range(20)) +
            "\nFAIL: rootless phase=interface contract assertions "
            "subtest=unavailable test=unavailable exit=1 reason=nonzero_exit "
            "phase_s=1 stage_s=7 line=432 log=unavailable")
        failure = self.diagnose(log, 1)
        self.assertEqual(
            failure["phase"], "interface contract assertions")
        self.assertNotIn("expected negative fixture", failure["first_error"])
        self.assertIn("rootless phase=interface contract", failure["first_error"])

    def test_validated_shell_syntax_check_explains_exit_two_without_guessing(self):
        marker = (
            "FAIL: rootless phase=bash syntax loaded-preflight.sh "
            "subtest=unavailable test=unavailable exit=2 reason=nonzero_exit "
            "phase_s=1 stage_s=516 line=531 "
            "log=build/tests/rootless-failure.Abc123xy/diagnostic.log")
        failure = self.diagnose(
            "FAIL: test_expected_negative (__main__.PreviousPassingCase)\n"
            "AssertionError: unrelated passing-suite fixture\n"
            "BLOCKED: loaded-preflight.sh permission denied in prior fixture\n"
            + marker, 2)
        self.assertEqual(failure["category"], "SOURCE_CONTRACT")
        self.assertEqual(failure["phase"], "bash syntax loaded-preflight.sh")
        self.assertEqual(failure["test"], "bash syntax loaded-preflight.sh")
        self.assertEqual(failure["exit_code"], 2)
        self.assertEqual(failure["child_exit_code"], 2)
        self.assertEqual(failure["rootless_reason"], "nonzero_exit")
        self.assertIn("bash -n", failure["reason"])
        self.assertIn("bash -n", failure["expected_contract"])
        self.assertIn("build/tests/rootless-failure.Abc123xy/diagnostic.log",
                      failure["first_error"])
        self.assertEqual(failure["observed"], failure["first_error"])
        self.assertNotIn("permission denied", failure["first_error"])
        self.assertNotIn("unrelated", failure["first_error"])

        extensionless = self.diagnose(
            marker.replace("loaded-preflight.sh",
                           "swapz-primary-boot-verify"), 2)
        self.assertEqual(extensionless["category"], "SOURCE_CONTRACT")
        self.assertEqual(
            extensionless["phase"], "bash syntax swapz-primary-boot-verify")
        self.assertEqual(
            extensionless["test"], "bash syntax swapz-primary-boot-verify")
        self.assertEqual(extensionless["child_exit_code"], 2)
        self.assertIn("bash -n", extensionless["expected_contract"])

    def test_unknown_or_malformed_syntax_evidence_stays_generic(self):
        marker = (
            "FAIL: rootless phase=bash syntax loaded-preflight.sh "
            "subtest=unavailable test=unavailable exit=2 reason=nonzero_exit "
            "phase_s=1 stage_s=516 line=531 log=unavailable")
        malformed = self.diagnose(
            marker.replace(" test=unavailable ", " "), 2)
        self.assertEqual(malformed["category"], "UNKNOWN_FAILURE")
        self.assertEqual(malformed["phase"], "native-rootless")
        self.assertNotIn("child_exit_code", malformed)
        wrong_exit = self.diagnose(marker.replace("exit=2 ", "exit=3 "), 2)
        self.assertEqual(wrong_exit["category"], "UNKNOWN_FAILURE")
        self.assertEqual(wrong_exit["child_exit_code"], 3)
        nested = self.diagnose(
            marker.replace("subtest=unavailable", "subtest=preflight"), 2)
        self.assertEqual(nested["category"], "UNKNOWN_FAILURE")
        self.assertEqual(nested["child_exit_code"], 2)
        identified = self.diagnose(
            marker.replace(" test=unavailable ",
                           " test=test_unexpected "), 2)
        self.assertEqual(identified["category"], "UNKNOWN_FAILURE")
        self.assertEqual(identified["test"], "test_unexpected")
        self.assertEqual(identified["child_exit_code"], 2)
        missing = self.diagnose("", 2)
        self.assertEqual(missing["category"], "UNKNOWN_FAILURE")

    def test_unittest_and_phase_bound_blocked_remain_distinct(self):
        unittest_marker = (
            "FAIL: rootless phase=package-dkms-test.py subtest=preflight "
            "test=test_package_guard exit=1 reason=unittest_assertion "
            "phase_s=2 stage_s=8 line=442 log=unavailable")
        assertion = self.diagnose(unittest_marker, 1)
        self.assertEqual(assertion["category"], "RUNTIME_ASSERTION")
        self.assertEqual(assertion["test"], "test_package_guard")
        self.assertEqual(assertion["child_exit_code"], 1)
        blocked_marker = (
            "FAIL: rootless phase=package-dkms-test.py subtest=unavailable "
            "test=unavailable exit=1 reason=nonzero_exit "
            "phase_s=2 stage_s=8 line=442 log=unavailable")
        producer_blocked = "BLOCKED: package-dkms-test.py permission denied"
        blocked = self.diagnose(producer_blocked + "\n" + blocked_marker, 1)
        self.assertEqual(blocked["category"], "HOST_PERMISSION")
        self.assertEqual(blocked["first_error"], producer_blocked)
        self.assertEqual(blocked["phase"], "package-dkms-test.py")
        self.assertEqual(blocked["child_exit_code"], 1)

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
            "FAIL: rootless phase=../secret-path subtest=unavailable test=unavailable "
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
             "--", "swapz-private-command-name-that-does-not-exist"],
            cwd=ROOT, env=environment, text=True, capture_output=True,
            timeout=12)
        self.assertEqual(failed.returncode, 127, failed.stderr)
        diagnostic = json.loads(
            failed.stdout.split("SWAPZ_CI_FAILURE=", 1)[1])
        self.assertEqual(diagnostic["tested_sha"], source)
        self.assertEqual(diagnostic["job"], "synthetic")
        self.assertEqual(diagnostic["suite"], suite)
        self.assertEqual(diagnostic["phase"], suite)
        self.assertEqual(diagnostic["launch_errno"], 2)
        self.assertEqual(diagnostic["exit_code"], 127)
        self.assertEqual(diagnostic["category"], "INFRASTRUCTURE")
        self.assertIn("No such file or directory", diagnostic["first_error"])
        self.assertNotIn("swapz-private-command-name", failed.stdout)
        self.assertNotIn("swapz-private-command-name", log.read_text())
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
