#!/usr/bin/env python3
"""Private, bounded regressions for the real rootless package stderr relay."""

import contextlib
import importlib.util
import io
import os
import re
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
ROOTLESS_RUNNER = ROOT / "tests/tools/test-rootless.sh"
PACKAGE_PHASE = "tests/runtime/native/package-dkms-test.py"
PRIMARY_PHASE = "tests/runtime/native/primary-real-swap-test.py"
PRIVATE_SENTINEL = "PRIVATE_ONLY_TRACEBACK_PAYLOAD"

# This runs the actual runner functions and the exact package-stage call, not a
# copy of their implementation. Never execute the rest of the rootless stages.
FIXTURE = r'''
python3() {
  [[ $# == 3 && $1 == -B && $3 == -v ]] || return 89
  case "$2" in
    tests/runtime/native/package-dkms-test.py|tests/runtime/native/primary-real-swap-test.py) ;;
    *) return 89 ;;
  esac
  printf 'SYNTHETIC_STDOUT\n'
  case "$SWAPZ_RELAY_SCENARIO" in
    pass)
      printf 'SYNTHETIC_STDERR\n' >&2
      return 0 ;;
    failure)
      printf 'PRIVATE_ONLY_TRACEBACK_PAYLOAD\n' >&2
      return 37 ;;
    exit124)
      printf 'ordinary exit 124 without a unittest exception\n' >&2
      return 124 ;;
    ordered)
      printf '%s\n' \
        "FAIL: test_first (__main__.PackageLifecycle.test_first) (phase='preflight')" \
        'Traceback (most recent call last):' \
        'AssertionError: PRIVATE_ONLY_TRACEBACK_PAYLOAD' \
        '======================================================================' \
        "ERROR: test_second (__main__.PackageLifecycle.test_second) (phase='cleanup')" \
        'subprocess.TimeoutExpired: should not override the first failure' >&2
      return 37 ;;
    primary_ordered)
      printf '%s\n' \
        "FAIL: test_oracle_first (__main__.PrimaryRealSwapContracts.test_oracle_first)" \
        'Traceback (most recent call last):' \
        'AssertionError: PRIVATE_ONLY_TRACEBACK_PAYLOAD' \
        '======================================================================' \
        "ERROR: test_teardown (__main__.PrimaryRealSwapContracts.test_teardown)" \
        'OSError: later teardown failure must not replace the first assertion' >&2
      return 37 ;;
    primary_errno)
      printf '%s\n' \
        "ERROR: test_oracle_first (__main__.PrimaryRealSwapContracts.test_oracle_first)" \
        'Traceback (most recent call last):' \
        'PermissionError: [Errno 13] PRIVATE_ONLY_TRACEBACK_PAYLOAD' \
        '======================================================================' \
        "FAIL: test_teardown (__main__.PrimaryRealSwapContracts.test_teardown)" \
        'AssertionError: later cleanup failed' >&2
      return 52 ;;
    primary_oversized)
      head -c 307200 /dev/zero | tr '\0' 'x' >&2
      printf '\n%s\n' \
        "FAIL: test_oracle_first (__main__.PrimaryRealSwapContracts.test_oracle_first)" \
        'Traceback (most recent call last):' \
        'AssertionError: PRIVATE_ONLY_TRACEBACK_PAYLOAD' \
        '======================================================================' >&2
      head -c 307200 /dev/zero | tr '\0' 'z' >&2
      printf '\n' >&2
      return 43 ;;
    ordered_timeout)
      printf '%s\n' \
        "ERROR: test_first (__main__.PackageLifecycle.test_first) (phase='prepare')" \
        'subprocess.TimeoutExpired: first real exception' \
        '======================================================================' \
        "FAIL: test_second (__main__.PackageLifecycle.test_second) (phase='cleanup')" \
        'AssertionError: should not override timeout' >&2
      return 1 ;;
    oversized)
      head -c 307200 /dev/zero | tr '\0' 'x' >&2
      printf '\n%s\n' \
        "FAIL: test_first (__main__.PackageLifecycle.test_first) (phase='preflight')" \
        'Traceback (most recent call last):' \
        'AssertionError: PRIVATE_ONLY_TRACEBACK_PAYLOAD' \
        '======================================================================' >&2
      head -c 307200 /dev/zero | tr '\0' 'z' >&2
      printf '\n' >&2
      return 43 ;;
    timeout)
      printf '%s\n' \
        "ERROR: test_timeout (__main__.PackageLifecycle.test_timeout) (phase='prepare')" >&2
      "$SWAPZ_FIXTURE_PYTHON" -c 'import subprocess, sys; subprocess.run([sys.executable, "-c", "import time; time.sleep(2)"], timeout=0.05, check=True)'
      return $? ;;
    *) return 90 ;;
  esac
}
'''


class RootlessAttribution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = ROOTLESS_RUNNER.read_text()
        functions_begin = source.index("# Bash's built-in SECONDS attributes")
        functions_end = source.index("trap 'rootless_unexpected_error", functions_begin)
        package_begin = source.index(f"rootless_phase='{PACKAGE_PHASE}'")
        package_end = source.index(
            "rootless_phase='tests/runtime/native/systemd/", package_begin)
        cls.functions = source[functions_begin:functions_end]
        cls.package_stage = source[package_begin:package_end]
        primary_begin = source.index(f"rootless_phase='{PRIMARY_PHASE}'")
        primary_end = source.index(
            "rootless_phase='tests/runtime/native/primary-real-swap-oracle-terminal-test.py'",
            primary_begin)
        cls.primary_stage = source[primary_begin:primary_end]
        assert cls.primary_stage.count(
            "python3 -B tests/runtime/native/primary-real-swap-test.py -v") == 1
        # Keep the rootless invocation tied to the real registered test.
        assert cls.package_stage.count(
            "python3 -B tests/runtime/native/package-dkms-test.py -v") == 1

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swapz-rootless-attribution-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "sandbox"
        self.root.mkdir()
        self.bin = Path(self.temp.name) / "bin"
        self.bin.mkdir()
        self.real_tee = shutil.which("tee")
        self.real_rm = shutil.which("rm")
        self.assertIsNotNone(self.real_tee)
        self.assertIsNotNone(self.real_rm)

    def stub(self, executable, body):
        path = self.bin / executable
        path.write_text("#!/usr/bin/env bash\n" + body)
        path.chmod(0o755)

    def invoke(self, scenario, *, storage="normal", stage=PACKAGE_PHASE):
        if storage == "symlink":
            alternate = Path(self.temp.name) / "untrusted"
            alternate.mkdir()
            (self.root / "build").mkdir()
            (self.root / "build/tests").symlink_to(alternate, target_is_directory=True)
        elif storage == "unwritable":
            # Permission-independent failure injection also works as root.
            self.stub("mktemp", "exit 72\n")

        fixture = (
            "#!/usr/bin/env bash\nset -Eeuo pipefail\n"
            f"ROOT={shlex.quote(str(self.root))}\n"
            'cd "$ROOT"\n'
            + self.functions + "\n" + FIXTURE + "\n"
            + (self.primary_stage if stage == PRIMARY_PHASE else self.package_stage)
            + "printf 'AFTER_PACKAGE\\n'\n"
        )
        environment = dict(os.environ)
        environment.update(
            PATH=str(self.bin) + os.pathsep + environment.get("PATH", ""),
            SWAPZ_RELAY_SCENARIO=scenario,
            SWAPZ_FIXTURE_PYTHON=sys.executable,
            SWAPZ_REAL_TEE=self.real_tee,
            SWAPZ_REAL_RM=self.real_rm,
        )
        return subprocess.run(
            ["bash", "-c", fixture], cwd=self.root, env=environment,
            capture_output=True, text=True, timeout=12,
        )

    def assert_report(self, result, *, status, reason, subtest="unavailable",
                      test="unavailable", stage=PACKAGE_PHASE, log_available=True):
        self.assertEqual(result.returncode, status, result.stderr[-3000:])
        markers = [line for line in result.stderr.splitlines()
                   if line.startswith(("FAIL: rootless ", "Failed during: ",
                                       "Reason: ", "NEXT: "))]
        self.assertEqual(len([line for line in markers
                              if line.startswith("FAIL: rootless ")]), 1)
        self.assertTrue(any(line.startswith(
            f"Failed during: {stage}") for line in markers))
        header = next(line for line in markers if line.startswith("FAIL: rootless "))
        self.assertRegex(header,
                         rf"^FAIL: rootless phase={re.escape(Path(stage).name)} "
                         rf"subtest={subtest} test={test} exit={status} reason={reason} "
                         r"phase_s=[0-9]+ stage_s=[0-9]+ line=[0-9]+ log=")
        self.assertNotIn(PRIVATE_SENTINEL, "\n".join(markers))
        self.assertNotIn(str(self.root), "\n".join(markers))
        self.assertNotIn("Traceback", "\n".join(markers))
        self.assertNotIn("subprocess.TimeoutExpired", "\n".join(markers))
        logs = list(self.root.glob("build/tests/rootless-failure.*/diagnostic.log"))
        if not log_available:
            self.assertIn("log=unavailable", header)
            self.assertEqual(logs, [])
            return None
        self.assertEqual(len(logs), 1)
        log = logs[0]
        self.assertEqual(
            set(self.root.glob("build/tests/rootless-failure.*")),
            {log.parent})
        self.assertIn(
            f"log=build/tests/{log.parent.name}/diagnostic.log", header)
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)
        self.assertEqual(log.parent.stat().st_mode & 0o777, 0o700)
        self.assertIn(f"exit_code={status}", log.read_text())
        self.assertIn(f"test={test}\n", log.read_text())
        return log

    def test_pass_preserves_streams_and_removes_private_capture(self):
        result = self.invoke("pass")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "SYNTHETIC_STDOUT\nAFTER_PACKAGE\n")
        self.assertEqual(result.stderr, "SYNTHETIC_STDERR\n")
        self.assertEqual(list(self.root.glob("build/tests/rootless-failure.*")), [])

    def test_failed_relay_cannot_turn_pass_into_success(self):
        self.stub("tee", 'printf "TEE_PRIVATE_PATH %s\n" "$1" >&2\n'
                        '"$SWAPZ_REAL_TEE" "$@"\nexit 68\n')
        result = self.invoke("pass")
        self.assert_report(result, status=1, reason="stderr_relay_failure")
        self.assertNotIn("AFTER_PACKAGE", result.stdout)
        self.assertNotIn("TEE_PRIVATE_PATH", result.stderr)

    def test_pass_cleanup_failure_is_reported(self):
        self.stub("rm", '''
if [[ "$*" == *"/diagnostic.log"* ]]; then
  exit 69
fi
exec "$SWAPZ_REAL_RM" "$@"
''')
        result = self.invoke("pass")
        log = self.assert_report(
            result, status=1, reason="stderr_relay_cleanup_failure")
        self.assertIn("SYNTHETIC_STDERR", log.read_text())

    def test_first_child_failure_survives_relay_and_cleanup_failures(self):
        self.stub("tee", '"$SWAPZ_REAL_TEE" "$@"\nexit 68\n')
        self.stub("rm", '''
if [[ "$*" == *"/diagnostic.log"* ]]; then
  exit 69
fi
exec "$SWAPZ_REAL_RM" "$@"
''')
        result = self.invoke("ordered")
        log = self.assert_report(result, status=37, reason="nonzero_exit")
        self.assertIn(PRIVATE_SENTINEL, log.read_text())
        self.assertIn("FAIL: test_first", log.read_text())
        self.assertNotIn("AFTER_PACKAGE", result.stdout)

    def test_symlinked_private_storage_never_receives_log(self):
        result = self.invoke("failure", storage="symlink")
        self.assert_report(result, status=37, reason="nonzero_exit",
                           log_available=False)
        self.assertEqual(list((Path(self.temp.name) / "untrusted").iterdir()), [])

    def test_unwritable_private_storage_preserves_failure(self):
        result = self.invoke("failure", storage="unwritable")
        self.assert_report(result, status=37, reason="nonzero_exit",
                           log_available=False)

    def test_oversized_stderr_keeps_first_traceback_and_bound(self):
        result = self.invoke("oversized")
        log = self.assert_report(result, status=43,
                                 reason="unittest_assertion", subtest="preflight",
                                 test="test_first")
        self.assertLessEqual(log.stat().st_size, 262144)
        self.assertIn(PRIVATE_SENTINEL, log.read_text())
        self.assertIn("FAIL: test_first", log.read_text())

    def test_two_ordered_failures_keep_first_assertion(self):
        result = self.invoke("ordered")
        log = self.assert_report(result, status=37,
                                 reason="unittest_assertion", subtest="preflight",
                                 test="test_first")
        self.assertIn("ERROR: test_second", log.read_text())

    def test_two_ordered_failures_keep_first_timeout(self):
        result = self.invoke("ordered_timeout")
        self.assert_report(result, status=1,
                           reason="unittest_timeout", subtest="prepare",
                           test="test_first")

    def test_real_subprocess_timeout_expired_is_classified(self):
        result = self.invoke("timeout")
        log = self.assert_report(result, status=1,
                                 reason="unittest_timeout", subtest="prepare",
                                 test="test_timeout")
        self.assertIn("subprocess.TimeoutExpired:", log.read_text())

    def test_primary_pass_preserves_streams_and_removes_capture(self):
        result = self.invoke("pass", stage=PRIMARY_PHASE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "SYNTHETIC_STDOUT\nAFTER_PACKAGE\n")
        self.assertEqual(result.stderr, "SYNTHETIC_STDERR\n")
        self.assertEqual(list(self.root.glob("build/tests/rootless-failure.*")), [])

    def test_primary_first_traceback_survives_later_teardown_failure(self):
        result = self.invoke("primary_ordered", stage=PRIMARY_PHASE)
        log = self.assert_report(
            result, status=37, reason="unittest_assertion",
            test="test_oracle_first", stage=PRIMARY_PHASE)
        evidence = log.read_text()
        self.assertLess(evidence.index("FAIL: test_oracle_first"),
                        evidence.index("ERROR: test_teardown"))
        self.assertIn("AssertionError: " + PRIVATE_SENTINEL, evidence)
        self.assertIn("OSError: later teardown failure", evidence)
        self.assertNotIn("AFTER_PACKAGE", result.stdout)

    def test_primary_errno_and_original_exit_survive_cleanup_failure(self):
        result = self.invoke("primary_errno", stage=PRIMARY_PHASE)
        log = self.assert_report(
            result, status=52, reason="unittest_error",
            test="test_oracle_first", stage=PRIMARY_PHASE)
        self.assertIn("PermissionError: [Errno 13] " + PRIVATE_SENTINEL,
                      log.read_text())
        self.assertIn("AssertionError: later cleanup failed", log.read_text())

    def test_primary_oversized_stderr_keeps_first_traceback(self):
        result = self.invoke("primary_oversized", stage=PRIMARY_PHASE)
        log = self.assert_report(
            result, status=43, reason="unittest_assertion",
            test="test_oracle_first", stage=PRIMARY_PHASE)
        self.assertLessEqual(log.stat().st_size, 262144)
        self.assertIn("AssertionError: " + PRIVATE_SENTINEL, log.read_text())

    def test_official_native_stage_keeps_first_unittest_failure(self):
        reporter_spec = importlib.util.spec_from_file_location(
            "swapz_rootless_attribution_reporter", ROOT / "tests/tools/run-tests.py")
        self.assertIsNotNone(reporter_spec.loader)
        reporter = importlib.util.module_from_spec(reporter_spec)
        reporter_spec.loader.exec_module(reporter)
        fixture_code = (
            "import sys\n"
            "sys.stderr.write("
            "'FAIL: test_oracle_first (__main__.PrimaryRealSwapContracts.test_oracle_first)\\n'"
            "'AssertionError: first checkpoint\\n'"
            "'ERROR: test_teardown (__main__.PrimaryRealSwapContracts.test_teardown)\\n'"
            "'OSError: later teardown failure\\n')\n"
            "sys.exit(37)\n"
        )
        report = {"stages": []}
        with contextlib.redirect_stdout(io.StringIO()):
            status = reporter.run_stage(
                "Native and rootless contracts",
                [sys.executable, "-c", fixture_code], report)
        self.assertEqual(status, 37)
        self.assertEqual(report["stages"][0]["status"], "FAIL")
        self.assertEqual(report["stages"][0]["exit_code"], 37)
        self.assertIn("test_oracle_first", report["stages"][0]["diagnostic"])
        self.assertNotIn("test_teardown", report["stages"][0]["diagnostic"])

    def test_ordinary_exit_124_is_not_claimed_as_timeout(self):
        result = self.invoke("exit124")
        self.assert_report(result, status=124,
                           reason="timeout_or_exit_124")


if __name__ == "__main__":
    unittest.main()
