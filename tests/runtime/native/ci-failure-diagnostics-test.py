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
        self.assertEqual(reported_errno["first_errno"], 28)
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
        self.assertIn("observed=123456", safe)
        self.assertIn("<structured-evidence-redacted>", safe)
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
        self.assertIn("<structured-evidence-redacted>", exception_json)

    def test_contract_classification_survives_private_root_redaction(self):
        failure = self.diagnostics.diagnose_ci_failure(
            ["FAIL: test_contract (__main__.SourceQualification.test_contract)",
             '  File "/private/checkout/tests/runtime/native/source-contract-test.py", line 42',
             "ValueError: substring not found"],
            1, "native-rootless")
        self.assertEqual(failure["category"], "SOURCE_CONTRACT")
        self.assertEqual(failure["first_error"], "ValueError: substring not found")
        self.assertNotIn("/private/checkout", json.dumps(failure))


if __name__ == "__main__":
    unittest.main()
