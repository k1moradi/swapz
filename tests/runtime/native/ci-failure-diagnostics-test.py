#!/usr/bin/env python3
"""Hermetic regression of bounded rootless first-failure delivery to CI.

Reuse the existing real runner extraction fixture; never launch a device test.
"""
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
ATTRIBUTION_FIXTURE = ROOT / "tests/runtime/native/rootless-attribution-test.py"
PRODUCT_GOALS = ROOT / "tests/tools/product_goals.py"


def load_module(name, path):
    specification = importlib.util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise RuntimeError("source-controlled diagnostic fixture unavailable")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class FirstFailureDelivery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.attribution = load_module("rootless_diagnostic_fixture", ATTRIBUTION_FIXTURE)
        cls.attribution.RootlessAttribution.setUpClass()
        cls.diagnostics = load_module("product_goal_diagnostics", PRODUCT_GOALS)

    def setUp(self):
        self.fixture = self.attribution.RootlessAttribution(
            "test_two_ordered_failures_keep_first_assertion")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_stalled_relay_does_not_swallow_first_child_exit(self):
        # The real tee drains the failing unittest, then its owned relay
        # remains alive. The original unbounded wait hid the child exit.
        self.fixture.stub("tee", '''
"$SWAPZ_REAL_TEE" "$@"
exec sleep 30
''')
        result = self.fixture.invoke("ordered")
        private_log = self.fixture.assert_report(
            result, status=37, reason="nonzero_exit")
        self.assertIsNotNone(private_log)
        self.assertNotIn("AFTER_PACKAGE", result.stdout)
        diagnosis = self.diagnostics.diagnose_ci_failure(
            result.stderr.splitlines(), result.returncode, "native-rootless")
        self.assertEqual(diagnosis["first_exit_code"], 37)
        self.assertEqual(diagnosis["child_exit_code"], 37)
        self.assertEqual(diagnosis["phase"], "package-dkms-test.py")
        self.assertEqual(diagnosis["test"], "package-dkms-test.py")
        self.assertEqual(diagnosis["cleanup_disposition"], "relay_incomplete")
        self.assertNotIn(self.attribution.PRIVATE_SENTINEL, json.dumps(diagnosis))
        self.assertEqual(diagnosis["rootless_private_log"],
                         "build/tests/" + private_log.parent.name + "/diagnostic.log")
        self.assertIn("AssertionError: " + self.attribution.PRIVATE_SENTINEL,
                      private_log.read_text())

    def test_first_assertion_and_later_teardown_remain_separate(self):
        result = self.fixture.invoke(
            "real_dual", stage=self.attribution.PRIMARY_PHASE)
        self.fixture.assert_report(
            result, status=1, reason="unittest_assertion",
            test="test_primary", stage=self.attribution.PRIMARY_PHASE)
        diagnosis = self.diagnostics.diagnose_ci_failure(
            result.stderr.splitlines(), result.returncode, "native-rootless")
        self.assertEqual(diagnosis["category"], "RUNTIME_ASSERTION")
        self.assertEqual(diagnosis["test"], "test_primary")
        self.assertEqual(diagnosis["first_exit_code"], 1)
        self.assertIsNone(diagnosis["first_errno"])
        self.assertNotIn(self.attribution.LATER_TEARDOWN_SENTINEL,
                         json.dumps(diagnosis))

    def test_nested_errno_reaches_ci_without_private_exception_text(self):
        result = self.fixture.invoke(
            "ownership_errno", stage=self.attribution.OWNERSHIP_PHASE)
        private_log = self.fixture.assert_report(
            result, status=52, reason="unittest_error", test="test_group",
            stage=self.attribution.OWNERSHIP_PHASE)
        diagnosis = self.diagnostics.diagnose_ci_failure(
            result.stderr.splitlines(), result.returncode, "native-rootless")
        self.assertEqual(diagnosis["first_exit_code"], 52)
        self.assertEqual(diagnosis["first_errno"], 9)
        self.assertEqual(diagnosis["cleanup_disposition"],
                         "not_independently_verified")
        self.assertNotIn(self.attribution.PRIVATE_SENTINEL,
                         json.dumps(diagnosis))
        self.assertIn("OSError: [Errno 9] " + self.attribution.PRIVATE_SENTINEL,
                      private_log.read_text())

    def test_real_signal_exit_124_and_private_structured_values(self):
        signalled = self.diagnostics.diagnose_ci_failure(
            [], -11, "ci-failure-diagnostics")
        self.assertEqual(signalled["termination"], "signal SIGSEGV")
        self.assertEqual(signalled["first_exit_code"], -11)
        self.assertEqual(signalled["status"], "FAIL")
        self.assertEqual(signalled["category"], "RUNTIME_ASSERTION")
        interrupted = self.diagnostics.diagnose_ci_failure(
            [], -15, "ci-failure-diagnostics")
        self.assertEqual(interrupted["status"], "CANCELLED")
        self.assertEqual(interrupted["category"], "CANCELLATION")
        returned_124 = self.diagnostics.diagnose_ci_failure(
            [], 124, "ci-failure-diagnostics")
        self.assertIn("not proven", returned_124["reason"])
        self.assertEqual(returned_124["first_exit_code"], 124)
        self.assertEqual(returned_124["category"], "INFRASTRUCTURE")
        assertion_124 = self.diagnostics.diagnose_ci_failure(
            ["FAIL: rootless phase=package-dkms-test.py "
             "subtest=unavailable test=test_guard exit=124 "
             "reason=unittest_assertion phase_s=1 stage_s=2 line=22 "
             "log=unavailable"],
            1, "native-rootless")
        self.assertEqual(assertion_124["status"], "FAIL")
        self.assertEqual(assertion_124["category"], "RUNTIME_ASSERTION")
        self.assertEqual(assertion_124["rootless_reason"], "unittest_assertion")
        self.assertEqual(assertion_124["first_exit_code"], 124)
        self.assertNotIn("watchdog", assertion_124["reason"])
        legacy_relay = self.diagnostics.diagnose_ci_failure(
            ["FAIL: rootless phase=package-dkms-test.py "
             "subtest=unavailable test=unavailable exit=1 "
             "reason=stderr_relay_failure phase_s=1 stage_s=2 line=22 "
             "log=unavailable"],
            1, "native-rootless")
        self.assertEqual(legacy_relay["cleanup_disposition"],
                         "relay_incomplete")
        reported_errno = self.diagnostics.diagnose_ci_failure(
            ["INFRASTRUCTURE: cannot start test: errno=28 No space left on device"],
            127, "ci-failure-diagnostics")
        # Child output cannot authenticate a launch errno; _ci_run supplies
        # one only when subprocess.run actually raises OSError.
        self.assertIsNone(reported_errno["first_errno"])
        forged_errno = self.diagnostics.diagnose_ci_failure(
            ["FAIL: test_errno (__main__.Fixture)",
             "AssertionError: errno=9 attacker-supplied text"],
            1, "ci-failure-diagnostics")
        self.assertIsNone(forged_errno["first_errno"])
        private = self.diagnostics.diagnose_ci_failure(
            ["FAIL: test_private (__main__.Fixture)",
             'AssertionError: expected=/private/fixture/token actual={"id":"FORGED_ID"}'],
            1, "ci-failure-diagnostics")
        self.assertEqual(private["status"], "FAIL")
        self.assertIn("<private-path>", private["first_error"])
        self.assertIn("<structured-evidence-redacted>", private["first_error"])
        self.assertNotIn("FORGED_ID", json.dumps(private))
        self.assertNotIn("/private/fixture", json.dumps(private))
        safe = self.diagnostics._ci_safe_line(
            'AssertionError: token_path=build/private/token.json '
            'PARTUUID=PRIVATE_CARD campaign=FORGED_CAMPAIGN '
            'device_id=PRIVATE_DEVICE actual=["FORGED_ARRAY"] observed=123456')
        self.assertNotIn("build/private/token.json", safe)
        self.assertNotIn("PRIVATE_CARD", safe)
        self.assertNotIn("FORGED_CAMPAIGN", safe)
        self.assertNotIn("PRIVATE_DEVICE", safe)
        self.assertNotIn("FORGED_ARRAY", safe)
        # Unsafe mixed exception operands are discarded; standalone bounded
        # numerical assertions above remain available for diagnosis.
        self.assertNotIn("observed=123456", safe)
        self.assertIn("[private exception detail omitted]", safe)
        numeric = self.diagnostics._ci_safe_line(
            "AssertionError: expected=4096 observed=8192")
        self.assertEqual(
            numeric, "AssertionError: expected=4096 observed=8192")
        source_context = self.diagnostics._ci_safe_line(
            'self.assertEqual(aborted["category"], "RUNTIME_ASSERTION")')
        self.assertEqual(
            source_context,
            'self.assertEqual(aborted["category"], "RUNTIME_ASSERTION")')
        exception_json = self.diagnostics._ci_safe_line(
            'AssertionError: mismatch {"campaign_id":"FORGED_CAMPAIGN"}')
        self.assertNotIn("FORGED_CAMPAIGN", exception_json)
        self.assertIn("[private exception detail omitted]", exception_json)

    def test_unstructured_exceptions_and_hostile_unittest_names_stay_private(self):
        # Before the fix an arbitrary Unicode exception message survived both
        # the CI annotation and the sanitized retained log.
        failure = self.diagnostics.diagnose_ci_failure(
            ["FAIL: test_inner (__main__.Outer.Inner.test_inner)",
             "AssertionError: PRIVATE_DEVICE_ALIAS_雪☃"],
            1, "ci-failure-diagnostics")
        self.assertEqual(failure["status"], "FAIL")
        self.assertEqual(failure["category"], "RUNTIME_ASSERTION")
        self.assertEqual(failure["test"], "__main__.Outer.Inner.test_inner")
        self.assertEqual(failure["exit_code"], 1)
        self.assertEqual(failure["first_errno"], None)
        self.assertEqual(failure["first_error"],
                         "AssertionError: [private exception detail omitted]")
        self.assertEqual(failure["observed"], failure["first_error"])
        self.assertEqual(failure["expected_contract"],
                         "test assertions and runtime contracts hold")
        self.assertNotIn("PRIVATE_DEVICE_ALIAS", json.dumps(failure))

        hostile_header = (
            "FAIL: test_inner (__main__.Nested." + "x" * 160 +
            "PRIVATE_HEADER_雪.test_inner) injected_payload=PRIVATE_TAIL")
        hostile = self.diagnostics.diagnose_ci_failure(
            [hostile_header,
             'RuntimeError: PRIVATE_JSON_雪 {"nested":{"id":"PRIVATE_CHILD"}}'],
            1, "ci-failure-diagnostics")
        self.assertEqual(hostile["test"], "ci-failure-diagnostics")
        self.assertEqual(hostile["first_error"],
                         "RuntimeError: [private exception detail omitted]")
        for private_value in ("PRIVATE_HEADER", "PRIVATE_JSON", "PRIVATE_CHILD",
                              "PRIVATE_TAIL", "雪"):
            self.assertNotIn(private_value,
                             json.dumps(hostile, ensure_ascii=False))
        self.assertEqual(
            self.diagnostics._ci_safe_line(hostile_header),
            "FAIL: unittest identity withheld")
        # No exception after the rejected heading means no authenticated
        # causal class; it must not be classified as a runtime assertion.
        heading_only = self.diagnostics.diagnose_ci_failure(
            [hostile_header], 1, "ci-failure-diagnostics")
        self.assertEqual(heading_only["first_error"],
                         "FAIL: unittest identity withheld")
        self.assertEqual(heading_only["category"], "UNKNOWN_FAILURE")
        self.assertEqual(heading_only["test"], "ci-failure-diagnostics")
        # A later sanitized exception supplies the first causal category but
        # may never restore the hostile unittest identity or payload.
        hostile_cleanup = self.diagnostics.diagnose_ci_failure(
            [hostile_header,
             "RuntimeError: PRIVATE_ORIGINAL_PAYLOAD",
             "ERROR: tearDown (__main__.Other.test_later)",
             "ValueError: PRIVATE_SECONDARY_PAYLOAD"],
            1, "ci-failure-diagnostics")
        self.assertEqual(hostile_cleanup["first_error"],
                         "RuntimeError: [private exception detail omitted]")
        self.assertEqual(hostile_cleanup["category"], "RUNTIME_ASSERTION")
        self.assertEqual(hostile_cleanup["test"], "ci-failure-diagnostics")
        self.assertNotIn("PRIVATE_", json.dumps(hostile_cleanup))
        # Without an earlier exception the legitimate standalone teardown
        # error retains its fully-qualified unittest identity.
        standalone_teardown = self.diagnostics.diagnose_ci_failure(
            ["ERROR: tearDown (__main__.Single.tearDown)",
             "ValueError: PRIVATE_CLEANUP"],
            1, "ci-failure-diagnostics")
        self.assertEqual(standalone_teardown["test"],
                         "__main__.Single.tearDown")
        self.assertEqual(standalone_teardown["first_error"],
                         "ValueError: [private exception detail omitted]")
        self.assertNotIn("PRIVATE_CLEANUP", json.dumps(standalone_teardown))
        self.assertEqual(
            self.diagnostics._ci_safe_line(
                "subprocess.TimeoutExpired: PRIVATE_TIMEOUT_ARGUMENT"),
            "subprocess.TimeoutExpired: [private exception detail omitted]")

    def test_contract_classification_survives_private_root_redaction(self):
        failure = self.diagnostics.diagnose_ci_failure(
            ["FAIL: test_contract (__main__.SourceQualification.test_contract)",
             '  File "/private/checkout/tests/runtime/native/source-contract-test.py", line 42',
             "ValueError: substring not found"],
            1, "native-rootless")
        self.assertEqual(failure["category"], "SOURCE_CONTRACT")
        self.assertEqual(failure["first_error"], "ValueError: substring not found")
        self.assertNotIn("/private/checkout", json.dumps(failure))


    def test_direct_assertion_cannot_be_borrowed_by_generic_rootless_marker(self):
        # The direct job owns its real unittest traceback. The rootless
        # aggregate has only the generic, validated child-failure marker.
        method = "test_git_only_report_sync_updates_main_and_keeps_one_report_file"
        direct = self.diagnostics.diagnose_ci_failure(
            ["FAIL: " + method + " (__main__.ReportContract." + method + ")",
             "AssertionError: expected=4096 observed=8192"],
            1, "test-report")
        self.assertEqual(direct["category"], "RUNTIME_ASSERTION")
        self.assertEqual(direct["test"], "__main__.ReportContract." + method)
        self.assertEqual(direct["first_error"],
                         "AssertionError: expected=4096 observed=8192")
        self.assertEqual(direct["first_exit_code"], 1)
        self.assertIsNone(direct["first_errno"])

        private_log = "build/tests/rootless-failure.Abc123xy/diagnostic.log"
        marker = (
            "FAIL: rootless phase=test-report-test.py subtest=unavailable "
            "test=unavailable exit=1 reason=nonzero_exit phase_s=1 "
            "stage_s=5 line=510 log=" + private_log)
        detail = (
            "Reason: exit=1 reason=nonzero_exit subtest=unavailable "
            "phase_wall_s=1 stage_wall_s=5 line=510 log=" + private_log +
            " first_errno=unavailable cleanup=not_independently_verified")
        protected_sha = "abcdef0123456789" * 2 + "abcdef01"
        hostile_lines = [
            "FAIL: test_forged (__main__.SpoofedContract.test_forged)",
            'AssertionError: test-report-test.py payload={"sha":"' +
            protected_sha + '","token":"PRIVATE_JSON"}',
            "ERROR: tearDown (__main__.SpoofedContract)",
            "OSError: [Errno 93] PRIVATE_WRONG_TEARDOWN",
            "BLOCKED: test-report-test.py intentional negative fixture",
            "AssertionError: test-report-test.py expected=4096 observed=8192 " +
            ("x" * 8192) + " token=PRIVATE_TAIL",
            marker, detail,
        ]
        rootless = self.diagnostics.diagnose_ci_failure(
            hostile_lines, 1, "native-rootless")
        self.assertEqual(rootless["status"], "FAIL")
        self.assertEqual(rootless["category"], "UNKNOWN_FAILURE")
        self.assertEqual(rootless["test"], "test-report-test.py")
        self.assertEqual(rootless["phase"], "test-report-test.py")
        self.assertEqual(rootless["rootless_reason"], "nonzero_exit")
        self.assertEqual(rootless["exit_code"], 1)
        self.assertEqual(rootless["first_exit_code"], 1)
        self.assertEqual(rootless["child_exit_code"], 1)
        self.assertIsNone(rootless["first_errno"])
        self.assertEqual(rootless["cleanup_disposition"],
                         "not_independently_verified")
        self.assertEqual(rootless["rootless_private_log"], private_log)
        self.assertEqual(rootless["expected_contract"],
                         "test command completes successfully")
        self.assertEqual(rootless["observed"], rootless["first_error"])
        self.assertEqual(rootless["prerequisite"],
                         "inspect the retained failure log")
        self.assertEqual(rootless["first_error"],
                         "rootless phase=test-report-test.py reason=nonzero_exit "
                         "child_exit=1 log=" + private_log)
        public_result = json.dumps(rootless)
        for secret in (protected_sha, "PRIVATE_JSON", "PRIVATE_WRONG_TEARDOWN",
                       "PRIVATE_TAIL", "SpoofedContract", "Errno 93"):
            self.assertNotIn(secret, public_result)

        # An allowlisted structured assertion marker is sufficient, without
        # promoting the raw traceback or a fabricated nested error.
        attributed_marker = marker.replace(
            " test=unavailable", " test=" + method).replace(
            "reason=nonzero_exit", "reason=unittest_assertion")
        attributed = self.diagnostics.diagnose_ci_failure(
            hostile_lines[:-2] + [attributed_marker], 1, "native-rootless")
        self.assertEqual(attributed["category"], "RUNTIME_ASSERTION")
        self.assertEqual(attributed["test"], method)
        self.assertIsNone(attributed["first_errno"])
        self.assertNotIn("PRIVATE_JSON", json.dumps(attributed))

        malformed = self.diagnostics.diagnose_ci_failure(
            hostile_lines[:-2] +
            [marker.replace("log=" + private_log,
                            "log=/private/fake/diagnostic.log")],
            1, "native-rootless")
        self.assertEqual(malformed["category"], "UNKNOWN_FAILURE")
        self.assertNotIn("rootless_private_log", malformed)
        self.assertNotIn("SpoofedContract", json.dumps(malformed))

    def test_matched_errno_compiler_helper_and_signal_remain_distinct(self):
        marker = (
            "FAIL: rootless phase=package-dkms-test.py subtest=unavailable "
            "test=test_guard exit=52 reason=unittest_error phase_s=1 "
            "stage_s=2 line=220 "
            "log=build/tests/rootless-failure.Abc123xy/diagnostic.log")
        detail = (
            "Reason: exit=52 reason=unittest_error subtest=unavailable "
            "phase_wall_s=1 stage_wall_s=2 line=220 "
            "log=build/tests/rootless-failure.Abc123xy/diagnostic.log "
            "first_errno=9 cleanup=not_independently_verified")
        lines = ["OSError: [Errno 93] PRIVATE_WRONG_ERROR", marker]
        self.assertIsNone(self.diagnostics.diagnose_ci_failure(
            lines, 1, "native-rootless")["first_errno"])
        with_detail = self.diagnostics.diagnose_ci_failure(
            lines + [detail], 1, "native-rootless")
        self.assertEqual(with_detail["first_errno"], 9)
        self.assertEqual(with_detail["first_exit_code"], 52)
        self.assertEqual(with_detail["category"], "RUNTIME_ASSERTION")
        self.assertNotIn("PRIVATE_WRONG_ERROR", json.dumps(with_detail))
        self.assertIsNone(self.diagnostics.diagnose_ci_failure(
            lines + [detail.replace("exit=52", "exit=53")],
            1, "native-rootless")["first_errno"])

        compiler = self.diagnostics.diagnose_ci_failure(
            ["source.c:12:3: error: incompatible types"], 2, "native-compile")
        self.assertEqual(compiler["category"], "NATIVE_COMPILE")
        missing_helper = self.diagnostics.diagnose_ci_failure(
            [], 127, "native-compile")
        self.assertEqual(missing_helper["category"], "INFRASTRUCTURE")
        self.assertIn("or child returned 127", missing_helper["first_error"])
        signalled = self.diagnostics.diagnose_ci_failure(
            [], -11, "native-compile")
        self.assertEqual(signalled["category"], "RUNTIME_ASSERTION")
        self.assertEqual(signalled["termination"], "signal SIGSEGV")
        shell_signal = self.diagnostics.diagnose_ci_failure(
            ["FAIL: rootless phase=package-dkms-test.py "
             "subtest=unavailable test=unavailable exit=143 "
             "reason=signal_or_child_exit phase_s=1 stage_s=2 "
             "line=120 log=unavailable"],
            1, "native-rootless")
        self.assertEqual(shell_signal["category"], "UNKNOWN_FAILURE")
        self.assertIn("indistinguishable", shell_signal["reason"])

if __name__ == "__main__":
    unittest.main()
