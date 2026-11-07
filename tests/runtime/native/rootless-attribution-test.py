#!/usr/bin/env python3
"""Private, bounded regressions for the real rootless unittest stderr relay."""

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
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
ROOTLESS_RUNNER = ROOT / "tests/tools/test-rootless.sh"
MAKE_PHASE = "tests/Makefile native and metadata"
LATE_RACE_TEST = "swapz-primary-late-race-test.py"
PACKAGE_PHASE = "tests/runtime/native/package-dkms-test.py"
PRIMARY_PHASE = "tests/runtime/native/primary-real-swap-test.py"
OWNERSHIP_PHASE = "tests/runtime/native/primary-real-swap-parent-ownership-test.py"
GENERATOR_PHASE = "tests/runtime/native/systemd/swapz-primary-generator-transaction-test.py"
PRIVATE_SENTINEL = "PRIVATE_ONLY_TRACEBACK_PAYLOAD"
GENERATOR_SUBTEST_SENTINEL = "PRIVATE_GENERATOR_SUBTEST_PAYLOAD"
LATER_TEARDOWN_SENTINEL = "LATER_TEARDOWN_PRIVATE_PAYLOAD"

# This runs the actual runner functions and exact captured-suite stage calls,
# not a copy of their implementation. Never execute the other rootless stages.
FIXTURE = r'''
python3() {
  [[ $# == 3 && $1 == -B && $3 == -v ]] || return 89
  case "$2" in
    tests/runtime/native/package-dkms-test.py|tests/runtime/native/primary-real-swap-test.py|tests/runtime/native/primary-real-swap-parent-ownership-test.py|tests/runtime/native/systemd/swapz-primary-generator-transaction-test.py) ;;
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
    real_dual)
      "$SWAPZ_FIXTURE_PYTHON" - <<'PY'
import unittest

class PrimaryRealSwapContracts(unittest.TestCase):
    def test_primary(self):
        self.fail("PRIVATE_ONLY_TRACEBACK_PAYLOAD")

    def tearDown(self):
        raise OSError("LATER_TEARDOWN_PRIVATE_PAYLOAD")

unittest.main(verbosity=2)
PY
      return $? ;;
    primary_ordered)
      printf '%s\n' \
        "FAIL: test_oracle_first (__main__.PrimaryRealSwapContracts.test_oracle_first)" \
        'Traceback (most recent call last):' \
        'AssertionError: PRIVATE_ONLY_TRACEBACK_PAYLOAD' \
        '======================================================================' \
        "ERROR: test_teardown (__main__.PrimaryRealSwapContracts.test_teardown)" \
        'OSError: later teardown failure must not replace the first assertion' >&2
      return 37 ;;
    ownership_errno)
      printf '%s\n' \
        "test_group (__main__.SourceAdmissionPeerOwnership.test_group) ... ERROR" \
        "ERROR: test_group (__main__.SourceAdmissionPeerOwnership.test_group)" \
        'Traceback (most recent call last):' \
        'OSError: [Errno 9] PRIVATE_ONLY_TRACEBACK_PAYLOAD' \
        'boundary=owned_process_group expected=empty observed=descendant_alive child_exit=7 errno=9 owned_cleanup=failed' >&2
      return 52 ;;
    primary_errno)
      printf '%s\n' \
        "ERROR: test_oracle_first (__main__.PrimaryRealSwapContracts.test_oracle_first)" \
        'Traceback (most recent call last):' \
        'PermissionError: [Errno 13] PRIVATE_ONLY_TRACEBACK_PAYLOAD' \
        '======================================================================' \
        "FAIL: test_teardown (__main__.PrimaryRealSwapContracts.test_teardown)" \
        'AssertionError: later cleanup failed' >&2
      return 52 ;;
    generator_subtest)
      printf '%s\n' \
        "test_manager_response_mutants_and_wrong_aliases (__main__.GeneratorPublicationTest.test_manager_response_mutants_and_wrong_aliases) (response='PRIVATE_GENERATOR_SUBTEST_PAYLOAD') ... FAIL" \
        '======================================================================' \
        "FAIL: test_manager_response_mutants_and_wrong_aliases (__main__.GeneratorPublicationTest.test_manager_response_mutants_and_wrong_aliases) (response='PRIVATE_GENERATOR_SUBTEST_PAYLOAD')" \
        'Traceback (most recent call last):' \
        'AssertionError: PRIVATE_ONLY_TRACEBACK_PAYLOAD' >&2
      return 61 ;;
    foreign_progress)
      # A passing negative fixture printed another suite's expected failure.
      printf '%s\n' \
        "test_expected (__main__.PackageLifecycle.test_expected) ... FAIL" \
        "FAIL: test_expected (__main__.PackageLifecycle.test_expected)" \
        'AssertionError: EXPECTED_NEGATIVE_FIXTURE_PAYLOAD' \
        '======================================================================' \
        "test_oracle_first (__main__.PrimaryRealSwapContracts.test_oracle_first) ... ERROR" \
        "ERROR: test_oracle_first (__main__.PrimaryRealSwapContracts.test_oracle_first)" \
        'Traceback (most recent call last):' \
        'PermissionError: [Errno 13] PRIVATE_ONLY_TRACEBACK_PAYLOAD' \
        '======================================================================' >&2
      return 52 ;;
    unmatched_progress)
      # A progress-only line is not a first failing detailed traceback.
      printf '%s\n' \
        "test_expected (__main__.PrimaryRealSwapContracts.test_expected) ... FAIL" \
        "test_oracle_first (__main__.PrimaryRealSwapContracts.test_oracle_first) ... ERROR" \
        "ERROR: test_oracle_first (__main__.PrimaryRealSwapContracts.test_oracle_first)" \
        'OSError: [Errno 9] PRIVATE_ONLY_TRACEBACK_PAYLOAD' >&2
      return 54 ;;
    mismatched_method)
      printf '%s\n' \
        "FAIL: test_forged (__main__.PrimaryRealSwapContracts.test_different)" \
        'AssertionError: EXPECTED_NEGATIVE_FIXTURE_PAYLOAD' >&2
      return 55 ;;
    near_limit)
      printf '%s\n' \
        "test_oracle_first (__main__.PrimaryRealSwapContracts.test_oracle_first) ... FAIL" \
        "FAIL: test_oracle_first (__main__.PrimaryRealSwapContracts.test_oracle_first)" \
        'Traceback (most recent call last):' \
        'AssertionError: PRIVATE_ONLY_TRACEBACK_PAYLOAD' \
        '======================================================================' >&2
      # 312-byte failure header plus 261831 bytes and newline = 256 KiB.
      head -c 261831 /dev/zero | tr '\0' 'x' >&2
      printf '\n' >&2
      return 47 ;;
    primary_oversized)
      printf '%s\n' \
        "test_oracle_first (__main__.PrimaryRealSwapContracts.test_oracle_first) ... FAIL" \
        "FAIL: test_oracle_first (__main__.PrimaryRealSwapContracts.test_oracle_first)" \
        'Traceback (most recent call last):' >&2
      head -c 98304 /dev/zero | tr '\0' 'x' >&2
      printf '\n%s\n' \
        'AssertionError: PRIVATE_ONLY_TRACEBACK_PAYLOAD' \
        '======================================================================' >&2
      head -c 307200 /dev/zero | tr '\0' 'z' >&2
      printf '\n' >&2
      return 43 ;;
    package_fixture_timeout)
      printf '%s\n' \
        "test_first (__main__.PackageLifecycle.test_first) ... ERROR" \
        "test_second (__main__.PackageLifecycle.test_second) ... ERROR" \
        "======================================================================" \
        "ERROR: test_first (__main__.PackageLifecycle.test_first)" \
        'Traceback (most recent call last):' \
        'PackageInvocationTimeout: SWAPZ_PACKAGE_TEST_TIMEOUT codec_variant=uncompressed operation=install elapsed_seconds=15.086 budget_seconds=15 budget_reason=ordinary_fixture_watchdog final_process_disposition=reaped_exit_-9 first_cause=fixture_watchdog_expired' \
        "======================================================================" \
        "ERROR: test_second (__main__.PackageLifecycle.test_second)" \
        'subprocess.TimeoutExpired: PRIVATE_ONLY_TRACEBACK_PAYLOAD' \
        "======================================================================" >&2
      return 1 ;;
    package_fixture_timeout_invalid)
      printf '%s\n' \
        "test_first (__main__.PackageLifecycle.test_first) ... ERROR" \
        "ERROR: test_first (__main__.PackageLifecycle.test_first)" \
        'Traceback (most recent call last):' \
        'PackageInvocationTimeout: SWAPZ_PACKAGE_TEST_TIMEOUT codec_variant=/private/SECRET operation=install elapsed_seconds=15.086 budget_seconds=15 budget_reason=ordinary_fixture_watchdog final_process_disposition=reaped_exit_-9 first_cause=fixture_watchdog_expired' >&2
      return 1 ;;
    ordered_timeout)
      printf '%s\n' \
        "ERROR: test_first (__main__.PackageLifecycle.test_first) (phase='prepare')" \
        'subprocess.TimeoutExpired: first real exception' \
        '======================================================================' \
        "FAIL: test_second (__main__.PackageLifecycle.test_second) (phase='cleanup')" \
        'AssertionError: should not override timeout' >&2
      return 1 ;;
    underscored_phase_ordered)
      # Real PackageLifecycle phases use underscores. Preserve verbose
      # execution order even though unittest groups ERROR details before FAIL.
      printf '%s\n' \
        "test_first (__main__.PackageLifecycle.test_first) (phase='detached_signature') ... FAIL" \
        "test_second (__main__.PackageLifecycle.test_second) (phase='cleanup') ... ERROR" \
        '======================================================================' \
        "ERROR: test_second (__main__.PackageLifecycle.test_second) (phase='cleanup')" \
        'Traceback (most recent call last):' \
        'OSError: LATER_TEARDOWN_PRIVATE_PAYLOAD' \
        '======================================================================' \
        "FAIL: test_first (__main__.PackageLifecycle.test_first) (phase='detached_signature')" \
        'Traceback (most recent call last):' \
        'AssertionError: PRIVATE_ONLY_TRACEBACK_PAYLOAD' \
        '======================================================================' >&2
      return 58 ;;
    multikey_phase_ordered)
      # PackageLifecycle also has phase plus case/field subtests. The arbitrary
      # context is private, but its progress record still owns execution order.
      printf '%s\n' \
        "test_first (__main__.PackageLifecycle.test_first) (phase='detached_signature', case='unsigned') ... FAIL" \
        "test_second (__main__.PackageLifecycle.test_second) (phase='cleanup') ... ERROR" \
        '======================================================================' \
        "ERROR: test_second (__main__.PackageLifecycle.test_second) (phase='cleanup')" \
        'Traceback (most recent call last):' \
        'OSError: LATER_TEARDOWN_PRIVATE_PAYLOAD' \
        '======================================================================' \
        "FAIL: test_first (__main__.PackageLifecycle.test_first) (phase='detached_signature', case='unsigned')" \
        'Traceback (most recent call last):' \
        'AssertionError: PRIVATE_ONLY_TRACEBACK_PAYLOAD' \
        '======================================================================' >&2
      return 59 ;;
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



# This Make-stage stub leaves the prior passing suite's expected FAIL: in
# the captured transcript; only the later matched failed target is causal.
MAKE_FIXTURE = r'''
[[ $# == 3 && $1 == -C && $2 == tests && $3 == test ]] || exit 89
printf 'MAKE_STDOUT\n'
emit_late_race_compile_failure() {
  cat >&2 <<'TRACEBACK'
Traceback (most recent call last):
  File "/private/checkout/tests/runtime/native/userspace/swapz-primary-late-race-test.py", line 1428, in <module>
    raise SystemExit(main())
  File "/private/checkout/tests/runtime/native/userspace/swapz-primary-late-race-test.py", line 1414, in main
    production = compile_and_run(source, workdir, mutant=False)
  File "/private/checkout/tests/runtime/native/userspace/swapz-primary-late-race-test.py", line 1398, in compile_and_run
    raise AssertionError(f"{c_path.name} compile failed: {compilation.stderr}")
AssertionError: production.c compile failed:
/private/source/production.c:4923:13: error: implicit declaration of function 'swapz_primary_shared_root_scope_record_live' PRIVATE_ONLY_TRACEBACK_PAYLOAD
TRACEBACK
  printf '%s\n' \
    "make[1]: *** [Makefile:${SWAPZ_TEST_USERSPACE_RECIPE_LINE}: test-userspace] Error 1" \
    "make: *** [Makefile:${SWAPZ_TEST_NATIVE_RECIPE_LINE}: test-native] Error 2" >&2
}
case "$SWAPZ_RELAY_SCENARIO" in
  pass)
    printf 'MAKE_STDERR\n' >&2
    exit 0 ;;
  compile|oversized)
    printf '%s\n' 'FAIL: test_expected (__main__.PreviouslyPassing.test_expected)' >&2
    if [[ $SWAPZ_RELAY_SCENARIO == oversized ]]; then
      head -c 307200 /dev/zero | tr '\0' 'x' >&2
      printf '\n' >&2
    fi
    emit_late_race_compile_failure
    if [[ $SWAPZ_RELAY_SCENARIO == oversized ]]; then
      # Parallel Make jobs may continue emitting after the first failed target.
      # The bounded private excerpt must still retain the compiler error.
      head -c 307200 /dev/zero | tr '\0' 'z' >&2
      printf '\n' >&2
    fi
    exit 2 ;;
  native_assertion)
    printf '%s\n' \
      'FAIL: test_expected (__main__.PreviouslyPassing.test_expected)' \
      'mapping-authority: Assertion failed: PRIVATE_ONLY_TRACEBACK_PAYLOAD' \
      'Aborted' \
      "make[1]: *** [Makefile:${SWAPZ_TEST_MAPPING_RECIPE_LINE}: test-mapping] Error 134" \
      "make: *** [Makefile:${SWAPZ_TEST_NATIVE_RECIPE_LINE}: test-native] Error 2" >&2
    exit 2 ;;
  malformed_python)
    printf '%s\n' \
      'Traceback (most recent call last):' \
      'TypeError: PRIVATE_ONLY_TRACEBACK_PAYLOAD' \
      "make[1]: *** [Makefile:${SWAPZ_TEST_USERSPACE_RECIPE_LINE}: test-userspace] Error 1" \
      "make: *** [Makefile:${SWAPZ_TEST_NATIVE_RECIPE_LINE}: test-native] Error 2" >&2
    exit 2 ;;
  forged_target)
    printf '%s\n' \
      "make[1]: *** [Makefile:${SWAPZ_TEST_GC_RECIPE_LINE}: test-mapping] Error 134" >&2
    exit 2 ;;
  forged_missing_line)
    printf '%s\n' \
      'make[1]: *** [Makefile:0: test-mapping] Error 134' >&2
    exit 2 ;;
  silent_nonzero)
    exit 2 ;;
  first_make_failure)
    printf '%s\n' \
      'FAIL: test_expected (__main__.PreviouslyPassing.test_expected)' \
      "make[1]: *** [Makefile:${SWAPZ_TEST_MAPPING_RECIPE_LINE}: test-mapping] Error 1" >&2
    emit_late_race_compile_failure
    exit 2 ;;
  unrelated)
    printf '%s\n' \
      'FAIL: test_expected (__main__.PreviouslyPassing.test_expected)' \
      "make[1]: *** [Makefile:${SWAPZ_TEST_MAPPING_RECIPE_LINE}: test-mapping] Error 1" >&2
    exit 2 ;;
  *) exit 90 ;;
esac
'''

class RootlessAttribution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = ROOTLESS_RUNNER.read_text()

        def recipe_line(lines, target, required_text=None):
            target_prefix = target + ":"
            try:
                target_index = next(
                    index for index, line in enumerate(lines)
                    if line.startswith(target_prefix))
            except StopIteration as error:
                raise AssertionError(f"missing Make target {target}") from error
            for index in range(target_index + 1, len(lines)):
                line = lines[index]
                if line.startswith("\t"):
                    if required_text is None or required_text in line:
                        return index + 1
                    continue
                if line and not line[0].isspace() and ":" in line:
                    break
            raise AssertionError(
                f"missing recipe line for {target} containing {required_text!r}")

        suites_makefile_lines = (
            ROOT / "tests/suites/Makefile").read_text().splitlines()
        tests_makefile_lines = (
            ROOT / "tests/Makefile").read_text().splitlines()
        cls.mapping_recipe_line = recipe_line(
            suites_makefile_lines, "test-mapping")
        cls.gc_recipe_line = recipe_line(
            suites_makefile_lines, "test-gc")
        cls.userspace_recipe_line = recipe_line(
            suites_makefile_lines, "test-userspace",
            "swapz-primary-late-race-test.py")
        cls.native_recipe_line = recipe_line(
            tests_makefile_lines, "test-native")

        functions_begin = source.index("# Bash's built-in SECONDS attributes")
        functions_end = source.index("trap 'rootless_unexpected_error", functions_begin)
        package_begin = source.index(f"rootless_phase='{PACKAGE_PHASE}'")
        package_end = source.index(
            "rootless_phase='tests/runtime/native/systemd/", package_begin)
        cls.functions = source[functions_begin:functions_end]
        make_begin = source.index(f"rootless_phase='{MAKE_PHASE}'")
        make_end = source.index(
            "rootless_phase='tests/runtime/native/source-contract-test.py'",
            make_begin)
        cls.make_stage = source[make_begin:make_end]
        assert cls.make_stage.count('"${make_args[@]}" -C tests test') == 1
        cls.package_stage = source[package_begin:package_end]
        primary_begin = source.index(f"rootless_phase='{PRIMARY_PHASE}'")
        primary_end = source.index(f"rootless_phase='{OWNERSHIP_PHASE}'",
                                   primary_begin)
        cls.primary_stage = source[primary_begin:primary_end]
        ownership_end = source.index(
            "rootless_phase='tests/runtime/native/primary-real-swap-oracle-terminal-test.py'",
            primary_end)
        cls.ownership_stage = source[primary_end:ownership_end]
        generator_begin = source.index(f"rootless_phase='{GENERATOR_PHASE}'")
        generator_end = source.index(
            "rootless_phase='tests/runtime/native/physical-swap-probe-test.py'",
            generator_begin)
        cls.generator_stage = source[generator_begin:generator_end]
        assert source.count(f"python3 -B {OWNERSHIP_PHASE} -v") == 1
        assert cls.ownership_stage.count(
            f"python3 -B {OWNERSHIP_PHASE} -v") == 1
        assert source.count(f"python3 -B {GENERATOR_PHASE} -v") == 1
        assert cls.generator_stage.count(
            f"python3 -B {GENERATOR_PHASE} -v") == 1
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
        suites_directory = self.root / "tests/suites"
        suites_directory.mkdir(parents=True)
        shutil.copyfile(
            ROOT / "tests/suites/Makefile", suites_directory / "Makefile")
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

        if stage == MAKE_PHASE:
            self.stub("make", MAKE_FIXTURE)

        fixture = (
            "#!/usr/bin/env bash\nset -Eeuo pipefail\n"
            f"ROOT={shlex.quote(str(self.root))}\n"
            'cd "$ROOT"\n'
            + self.functions + "\n" + FIXTURE + "\n"
            + ("make_args=(make)\n" if stage == MAKE_PHASE else "")
            + {MAKE_PHASE: self.make_stage,
               PACKAGE_PHASE: self.package_stage,
               PRIMARY_PHASE: self.primary_stage,
               OWNERSHIP_PHASE: self.ownership_stage,
               GENERATOR_PHASE: self.generator_stage}[stage]
            + "printf 'AFTER_PACKAGE\\n'\n"
        )
        environment = dict(os.environ)
        environment.update(
            PATH=str(self.bin) + os.pathsep + environment.get("PATH", ""),
            SWAPZ_RELAY_SCENARIO=scenario,
            SWAPZ_FIXTURE_PYTHON=sys.executable,
            SWAPZ_REAL_TEE=self.real_tee,
            SWAPZ_REAL_RM=self.real_rm,
            SWAPZ_TEST_MAPPING_RECIPE_LINE=str(self.mapping_recipe_line),
            SWAPZ_TEST_GC_RECIPE_LINE=str(self.gc_recipe_line),
            SWAPZ_TEST_USERSPACE_RECIPE_LINE=str(self.userspace_recipe_line),
            SWAPZ_TEST_NATIVE_RECIPE_LINE=str(self.native_recipe_line),
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
                         rf"subtest={re.escape(subtest)} test={re.escape(test)} "
                         rf"exit={status} reason={reason} "
                         r"phase_s=[0-9]+ stage_s=[0-9]+ line=[0-9]+ log=")
        self.assertNotIn(PRIVATE_SENTINEL, "\n".join(markers))
        self.assertNotIn(str(self.root), "\n".join(markers))
        self.assertNotIn("Traceback", "\n".join(markers))
        self.assertNotIn("subprocess.TimeoutExpired", "\n".join(markers))
        self.assertNotIn(LATER_TEARDOWN_SENTINEL, "\n".join(markers))
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


    def test_make_pass_preserves_streams_and_removes_capture(self):
        result = self.invoke("pass", stage=MAKE_PHASE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "MAKE_STDOUT\nAFTER_PACKAGE\n")
        self.assertEqual(result.stderr, "MAKE_STDERR\n")
        self.assertEqual(list(self.root.glob("build/tests/rootless-failure.*")), [])

    def test_make_compiler_failure_identifies_only_authenticated_fixture(self):
        result = self.invoke("compile", stage=MAKE_PHASE)
        log = self.assert_report(
            result, status=2, reason="native_compile", subtest="compile",
            test=LATE_RACE_TEST, stage=MAKE_PHASE)
        self.assertIn("implicit declaration of function", log.read_text())
        self.assertIn("swapz_primary_shared_root_scope_record_live", log.read_text())
        self.assertIn(PRIVATE_SENTINEL, log.read_text())
        marker = next(line for line in result.stderr.splitlines()
                      if line.startswith("FAIL: rootless "))
        self.assertNotIn("test_expected", marker)
        self.assertNotIn("AFTER_PACKAGE", result.stdout)

    def test_make_does_not_inherit_earlier_expected_fail(self):
        result = self.invoke("unrelated", stage=MAKE_PHASE)
        log = self.assert_report(
            result, status=2, reason="nonzero_exit", subtest="test-mapping",
            stage=MAKE_PHASE)
        self.assertIn("FAIL: test_expected", log.read_text())
        self.assertNotIn("AFTER_PACKAGE", result.stdout)

    def test_make_first_failed_target_precedes_later_compile(self):
        result = self.invoke("first_make_failure", stage=MAKE_PHASE)
        log = self.assert_report(
            result, status=2, reason="nonzero_exit", subtest="test-mapping",
            stage=MAKE_PHASE)
        evidence = log.read_text()
        self.assertLess(evidence.index("test-mapping"),
                        evidence.index("swapz-primary-late-race-test.py"))
        marker = next(line for line in result.stderr.splitlines()
                      if line.startswith("FAIL: rootless "))
        self.assertIn("test=unavailable", marker)
        self.assertNotIn(LATE_RACE_TEST, marker)


    def test_make_native_assertion_identifies_first_target_not_later_cleanup(self):
        result = self.invoke("native_assertion", stage=MAKE_PHASE)
        log = self.assert_report(
            result, status=2, reason="nonzero_exit", subtest="test-mapping",
            stage=MAKE_PHASE)
        evidence = log.read_text()
        self.assertIn("Assertion failed: " + PRIVATE_SENTINEL, evidence)
        self.assertIn(
            f"Makefile:{self.mapping_recipe_line}: test-mapping", evidence)
        marker = next(line for line in result.stderr.splitlines()
                      if line.startswith("FAIL: rootless "))
        self.assertIn("test=unavailable", marker)
        self.assertNotIn("test-userspace", marker)
        self.assertNotIn("test_expected", marker)
        self.assertNotIn(PRIVATE_SENTINEL, marker)

    def test_make_malformed_python_evidence_retains_nested_target(self):
        result = self.invoke("malformed_python", stage=MAKE_PHASE)
        log = self.assert_report(
            result, status=2, reason="nonzero_exit", subtest="test-userspace",
            stage=MAKE_PHASE)
        self.assertIn("TypeError: " + PRIVATE_SENTINEL, log.read_text())
        self.assertIn("unittest_kind=unavailable", log.read_text())

    def test_make_target_line_must_belong_to_reported_target(self):
        result = self.invoke("forged_target", stage=MAKE_PHASE)
        log = self.assert_report(
            result, status=2, reason="nonzero_exit", stage=MAKE_PHASE)
        evidence = log.read_text()
        self.assertIn(
            f"Makefile:{self.gc_recipe_line}: test-mapping", evidence)
        marker = next(line for line in result.stderr.splitlines()
                      if line.startswith("FAIL: rootless "))
        self.assertIn("subtest=unavailable", marker)
        self.assertNotIn("subtest=test-mapping", marker)

    def test_make_missing_recipe_line_cannot_authenticate_target(self):
        result = self.invoke("forged_missing_line", stage=MAKE_PHASE)
        log = self.assert_report(
            result, status=2, reason="nonzero_exit", stage=MAKE_PHASE)
        self.assertIn(
            "Makefile:0: test-mapping", log.read_text())
        marker = next(line for line in result.stderr.splitlines()
                      if line.startswith("FAIL: rootless "))
        self.assertIn("subtest=unavailable", marker)

    def test_make_silent_nonzero_does_not_invent_a_cause(self):
        result = self.invoke("silent_nonzero", stage=MAKE_PHASE)
        log = self.assert_report(
            result, status=2, reason="nonzero_exit", stage=MAKE_PHASE)
        self.assertNotIn("Traceback (most recent call last):", log.read_text())
        self.assertIn("test=unavailable", log.read_text())

    def test_make_oversized_stderr_retains_first_compiler_error(self):
        result = self.invoke("oversized", stage=MAKE_PHASE)
        log = self.assert_report(
            result, status=2, reason="native_compile", subtest="compile",
            test=LATE_RACE_TEST, stage=MAKE_PHASE)
        self.assertLessEqual(log.stat().st_size, 262144)
        self.assertIn("swapz_primary_shared_root_scope_record_live",
                      log.read_text())

    def test_make_failed_relay_cannot_authenticate_child_output(self):
        self.stub("tee", '"$SWAPZ_REAL_TEE" "$@"\nexit 68\n')
        result = self.invoke("compile", stage=MAKE_PHASE)
        self.assert_report(
            result, status=2, reason="nonzero_exit", stage=MAKE_PHASE)
        self.assertNotIn("AFTER_PACKAGE", result.stdout)

    def test_make_unavailable_capture_preserves_child_exit(self):
        result = self.invoke("compile", stage=MAKE_PHASE, storage="unwritable")
        self.assert_report(
            result, status=2, reason="nonzero_exit", stage=MAKE_PHASE,
            log_available=False)

    def test_ci_wrapper_uses_make_fixture_identity_not_prior_fail(self):
        diagnostic_spec = importlib.util.spec_from_file_location(
            "swapz_rootless_ci_make_diagnostic",
            ROOT / "tests/tools/product_goals.py")
        self.assertIsNotNone(diagnostic_spec.loader)
        diagnostics = importlib.util.module_from_spec(diagnostic_spec)
        diagnostic_spec.loader.exec_module(diagnostics)
        result = self.invoke("compile", stage=MAKE_PHASE)
        diagnostic = diagnostics.diagnose_ci_failure(
            result.stderr.splitlines(), result.returncode, "native-rootless")
        self.assertEqual(diagnostic["category"], "NATIVE_COMPILE")
        self.assertEqual(diagnostic["child_exit_code"], 2)
        self.assertEqual(diagnostic["rootless_reason"], "native_compile")
        self.assertEqual(diagnostic["phase"], "Makefile native and metadata")
        self.assertEqual(diagnostic["test"], LATE_RACE_TEST)
        self.assertNotIn("test_expected", diagnostic["first_error"])
        self.assertNotIn(PRIVATE_SENTINEL, diagnostic["first_error"])
        self.assertNotIn("/private/", diagnostic["first_error"])
        self.assertIn("build/tests/rootless-failure.",
                      diagnostic["first_error"])

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

    def test_underscored_phase_progress_keeps_first_assertion(self):
        result = self.invoke("underscored_phase_ordered")
        log = self.assert_report(
            result, status=58, reason="unittest_assertion",
            test="test_first")
        evidence = log.read_text()
        self.assertLess(
            evidence.index("test_first (__main__.PackageLifecycle.test_first)"),
            evidence.index("test_second (__main__.PackageLifecycle.test_second)"))
        self.assertLess(evidence.index("ERROR: test_second"),
                        evidence.index("FAIL: test_first"))
        self.assertIn("AssertionError: " + PRIVATE_SENTINEL, evidence)
        self.assertIn("OSError: " + LATER_TEARDOWN_SENTINEL, evidence)
        self.assertIn("unittest_kind=FAIL\n", evidence)
        marker = next(line for line in result.stderr.splitlines()
                      if line.startswith("FAIL: rootless "))
        self.assertIn("subtest=unavailable test=test_first", marker)
        self.assertNotIn("detached_signature", marker)

    def test_multikey_subtest_progress_keeps_first_assertion(self):
        result = self.invoke("multikey_phase_ordered")
        log = self.assert_report(
            result, status=59, reason="unittest_assertion",
            test="test_first")
        evidence = log.read_text()
        self.assertLess(evidence.index("ERROR: test_second"),
                        evidence.index("FAIL: test_first"))
        self.assertIn("case='unsigned'", evidence)
        self.assertIn("AssertionError: " + PRIVATE_SENTINEL, evidence)
        self.assertIn("unittest_kind=FAIL\n", evidence)
        marker = next(line for line in result.stderr.splitlines()
                      if line.startswith("FAIL: rootless "))
        self.assertIn("subtest=unavailable test=test_first", marker)
        self.assertNotIn("case=", marker)
        self.assertNotIn("detached_signature", marker)

    def test_package_fixture_watchdog_classifies_only_fixed_first_exception(self):
        valid = self.invoke("package_fixture_timeout")
        evidence = self.assert_report(
            valid, status=1, reason="unittest_timeout", test="test_first")
        self.assertIn("PackageInvocationTimeout:", evidence.read_text())
        self.assertIn("PRIVATE_ONLY_TRACEBACK_PAYLOAD", evidence.read_text())
        # Both cases intentionally fail and retain diagnostics. Remove only the
        # first fully asserted, fixture-owned log so the next case's single-log
        # ownership assertion cannot count unrelated earlier evidence.
        evidence.unlink()
        evidence.parent.rmdir()
        # The standalone relay intentionally preserves private stderr. Only
        # Bash's fixed public markers and the official make test summary
        # must exclude it.
        invalid = self.invoke("package_fixture_timeout_invalid")
        self.assert_report(
            invalid, status=1, reason="unittest_error", test="test_first")
        invalid_markers = "\n".join(
            line for line in invalid.stderr.splitlines()
            if line.startswith(("FAIL: rootless ", "Failed during: ",
                                "Reason: ", "NEXT: ")))
        self.assertNotIn("/private/SECRET", invalid_markers)

    def test_real_subprocess_timeout_expired_is_classified(self):
        result = self.invoke("timeout")
        log = self.assert_report(result, status=1,
                                 reason="unittest_timeout", subtest="prepare",
                                 test="test_timeout")
        self.assertIn("subprocess.TimeoutExpired:", log.read_text())

    def test_real_unittest_teardown_order_keeps_primary_assertion(self):
        result = self.invoke("real_dual", stage=PRIMARY_PHASE)
        log = self.assert_report(
            result, status=1, reason="unittest_assertion",
            test="test_primary", stage=PRIMARY_PHASE)
        evidence = log.read_text()
        # unittest groups detailed ERROR blocks before FAIL blocks even though
        # verbose progress records preserve the execution order.
        self.assertLess(evidence.index("ERROR: test_primary"),
                        evidence.index("FAIL: test_primary"))
        self.assertIn("AssertionError: " + PRIVATE_SENTINEL, evidence)
        self.assertIn("OSError: " + LATER_TEARDOWN_SENTINEL, evidence)
        self.assertIn("unittest_kind=FAIL\n", evidence)

    def test_generator_nonphase_subtest_reports_method_without_public_details(self):
        result = self.invoke("generator_subtest", stage=GENERATOR_PHASE)
        log = self.assert_report(
            result, status=61, reason="unittest_assertion",
            test="test_manager_response_mutants_and_wrong_aliases",
            stage=GENERATOR_PHASE)
        markers = "\n".join(
            line for line in result.stderr.splitlines()
            if line.startswith(("FAIL: rootless ", "Failed during: ",
                                "Reason: ", "NEXT: ")))
        self.assertNotIn(GENERATOR_SUBTEST_SENTINEL, markers)
        evidence = log.read_text()
        self.assertIn(GENERATOR_SUBTEST_SENTINEL, evidence)
        self.assertIn("unittest_kind=FAIL\n", evidence)

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

    def test_ownership_errno_preserves_boundary_and_private_traceback(self):
        result = self.invoke("ownership_errno", stage=OWNERSHIP_PHASE)
        log = self.assert_report(
            result, status=52, reason="unittest_error",
            test="test_group", stage=OWNERSHIP_PHASE)
        evidence = log.read_text()
        self.assertIn("OSError: [Errno 9] " + PRIVATE_SENTINEL, evidence)
        self.assertIn(
            "boundary=owned_process_group expected=empty "
            "observed=descendant_alive child_exit=7 errno=9 "
            "owned_cleanup=failed", evidence)
        self.assertIn("unittest_kind=ERROR\n", evidence)
        self.assertNotIn("AFTER_PACKAGE", result.stdout)

    def test_foreign_expected_failure_cannot_claim_primary_phase(self):
        result = self.invoke("foreign_progress", stage=PRIMARY_PHASE)
        log = self.assert_report(
            result, status=52, reason="unittest_error",
            test="test_oracle_first", stage=PRIMARY_PHASE)
        evidence = log.read_text()
        self.assertLess(evidence.index("FAIL: test_expected"),
                        evidence.index("ERROR: test_oracle_first"))
        self.assertIn("PermissionError: [Errno 13] " + PRIVATE_SENTINEL,
                      evidence)
        self.assertIn("first_errno=13\n", evidence)
        marker = next(line for line in result.stderr.splitlines()
                      if line.startswith("FAIL: rootless "))
        self.assertNotIn("test_expected", marker)
        self.assertNotIn("EXPECTED_NEGATIVE_FIXTURE_PAYLOAD", marker)

    def test_progress_without_matching_detail_cannot_claim_first_failure(self):
        result = self.invoke("unmatched_progress", stage=PRIMARY_PHASE)
        log = self.assert_report(
            result, status=54, reason="nonzero_exit", stage=PRIMARY_PHASE)
        self.assertIn("OSError: [Errno 9] " + PRIVATE_SENTINEL, log.read_text())
        self.assertIn("unittest_kind=unavailable\n", log.read_text())
        self.assertIn("first_errno=unavailable\n", log.read_text())

    def test_mismatched_unittest_method_cannot_claim_first_failure(self):
        result = self.invoke("mismatched_method", stage=PRIMARY_PHASE)
        log = self.assert_report(
            result, status=55, reason="nonzero_exit", stage=PRIMARY_PHASE)
        self.assertIn("EXPECTED_NEGATIVE_FIXTURE_PAYLOAD", log.read_text())
        self.assertIn("unittest_kind=unavailable\n", log.read_text())

    def test_capture_near_byte_limit_reserves_space_for_attribution(self):
        result = self.invoke("near_limit", stage=PRIMARY_PHASE)
        log = self.assert_report(
            result, status=47, reason="unittest_assertion",
            test="test_oracle_first", stage=PRIMARY_PHASE)
        self.assertLessEqual(log.stat().st_size, 262144)
        self.assertIn("AssertionError: " + PRIVATE_SENTINEL, log.read_text())
        self.assertIn("unittest_kind=FAIL\n", log.read_text())

    def test_primary_oversized_stderr_keeps_first_traceback(self):
        result = self.invoke("primary_oversized", stage=PRIMARY_PHASE)
        log = self.assert_report(
            result, status=43, reason="unittest_assertion",
            test="test_oracle_first", stage=PRIMARY_PHASE)
        self.assertLessEqual(log.stat().st_size, 262144)
        evidence = log.read_text()
        self.assertIn("AssertionError: " + PRIVATE_SENTINEL, evidence)
        self.assertIn("unittest_kind=FAIL\n", evidence)


    def test_direct_rootless_zero_tail_budget_and_duplicate_capture(self):
        reporter_spec = importlib.util.spec_from_file_location(
            "swapz_direct_failure_budget_reporter", ROOT / "tests/tools/run-tests.py")
        reporter = importlib.util.module_from_spec(reporter_spec)
        reporter_spec.loader.exec_module(reporter)
        capture_directory = self.root / "build/tests/rootless-failure.Abc123xy"
        capture_directory.mkdir(parents=True, mode=0o700)
        private_log = capture_directory / "diagnostic.log"
        first_label = (
            b"\n--- first matched tmp-cleanup unittest failure "
            b"(private; not a public test identity) ---\n")
        tail_label = (
            b"\n--- official stage merged stdout/stderr tail "
            b"(context only) ---\n")
        initial_bytes = b"\n--- swapz rootless attribution ---\n"
        initial_bytes += b"x" * (
            262144 - len(first_label) - len(tail_label) - 1 -
            len(initial_bytes))
        private_log.write_bytes(initial_bytes)
        private_log.chmod(0o600)
        marker = (
            "FAIL: rootless phase=tmp-cleanup-test.py "
            "subtest=unavailable test=unavailable exit=37 "
            "reason=nonzero_exit phase_s=1 stage_s=2 line=9 "
            "log=build/tests/rootless-failure.Abc123xy/diagnostic.log")
        transcript = (
            "test_first (__main__.OwnedTemporaryCleanupTests.test_first) ... FAIL\n"
            "FAIL: test_first (__main__.OwnedTemporaryCleanupTests.test_first)\n"
            "Traceback (most recent call last):\n"
            "AssertionError: " + PRIVATE_SENTINEL + "\n"
            + "=" * 70 + "\n" + marker)
        with mock.patch.object(reporter, "ROOT", self.root):
            reporter.retain_direct_rootless_first_failure(transcript, 37)
            evidence = private_log.read_bytes()
            self.assertEqual(len(evidence), 262144)
            # With one byte for the first block, no tail bytes remain.
            # A [-0:] slice would accidentally duplicate the transcript.
            self.assertEqual(evidence[len(initial_bytes):],
                             first_label + b"\n" + tail_label)
            self.assertNotIn(PRIVATE_SENTINEL.encode(), evidence)

            # A pre-captured log must never get a second stderr transcript.
            private_log.write_bytes(b"PRECAPTURED_STDERR\n")
            reporter.retain_direct_rootless_first_failure(transcript, 37)
            self.assertEqual(private_log.read_bytes(), b"PRECAPTURED_STDERR\n")

            # Without a matching block, do not invent a first traceback.
            private_log.write_bytes(b"\n--- swapz rootless attribution ---\n")
            missing = transcript.replace(
                "FAIL: test_first (__main__.OwnedTemporaryCleanupTests.test_first)\n"
                "Traceback (most recent call last):\n"
                "AssertionError: " + PRIVATE_SENTINEL + "\n",
                "ERROR: test_cleanup (__main__.UnrelatedTest.test_cleanup)\n"
                "TypeError: " + LATER_TEARDOWN_SENTINEL + "\n")
            reporter.retain_direct_rootless_first_failure(missing, 37)
            evidence = private_log.read_text()
            self.assertIn("no authenticated direct unittest traceback", evidence)
            self.assertNotIn("first matched direct rootless unittest failure",
                             evidence)

    def test_official_native_stage_reports_make_fixture_compile_safely(self):
        reporter_spec = importlib.util.spec_from_file_location(
            "swapz_rootless_make_compile_reporter", ROOT / "tests/tools/run-tests.py")
        self.assertIsNotNone(reporter_spec.loader)
        reporter = importlib.util.module_from_spec(reporter_spec)
        reporter_spec.loader.exec_module(reporter)
        fixture_code = (
            "import sys\n"
            "sys.stderr.write("
            "'/private/source/production.c:4923:13: error: implicit declaration "
            "of function PRIVATE_ONLY_TRACEBACK_PAYLOAD\\n'"
            "'FAIL: rootless phase=Makefile native and metadata "
            "subtest=compile test=swapz-primary-late-race-test.py exit=2 "
            "reason=native_compile phase_s=1 stage_s=2 line=441 "
            "log=build/tests/rootless-failure.ABCD1234/diagnostic.log\\n'"
            "'Failed during: tests/Makefile native and metadata subtest compile\\n'"
            "'Reason: exit=2 reason=native_compile subtest=compile "
            "phase_wall_s=1 stage_wall_s=2 line=441 "
            "log=build/tests/rootless-failure.ABCD1234/diagnostic.log\\n')\n"
            "sys.exit(2)\n"
        )
        report = {"stages": []}
        with contextlib.redirect_stdout(io.StringIO()):
            status = reporter.run_stage(
                "Native and rootless contracts",
                [sys.executable, "-c", fixture_code], report)
        self.assertEqual(status, 2)
        diagnostic = report["stages"][0]["diagnostic"]
        self.assertEqual(report["stages"][0]["failed_phase"], Path(MAKE_PHASE).name)
        self.assertEqual(report["stages"][0]["exit_code"], 2)
        # The authenticated child fields must survive in the public record;
        # compiler details and private source paths belong only in evidence.
        self.assertEqual(
            diagnostic,
            "Native fixture compile failed: swapz-primary-late-race-test.py; "
            "child_exit=2 reason=native_compile subtest=compile "
            "test=swapz-primary-late-race-test.py "
            "log=build/tests/rootless-failure.ABCD1234/diagnostic.log")
        self.assertNotIn(PRIVATE_SENTINEL, diagnostic)
        self.assertNotIn("/private/", diagnostic)

        malformed_report = {"stages": []}
        malformed_fixture_code = fixture_code.replace(
            "reason=native_compile", "reason=unittest_assertion")
        with contextlib.redirect_stdout(io.StringIO()):
            malformed_status = reporter.run_stage(
                "Native and rootless contracts",
                [sys.executable, "-c", malformed_fixture_code],
                malformed_report)
        self.assertEqual(malformed_status, 2)
        malformed_diagnostic = malformed_report["stages"][0]["diagnostic"]
        self.assertEqual(
            malformed_diagnostic,
            "Rootless late-race failure identity was not authenticated; "
            "child_exit=2 reason=unittest_assertion subtest=unavailable "
            "test=unavailable "
            "log=build/tests/rootless-failure.ABCD1234/diagnostic.log")
        self.assertEqual(malformed_report["stages"][0]["exit_code"], 2)
        self.assertNotIn(PRIVATE_SENTINEL, malformed_diagnostic)
        self.assertNotIn("/private/", malformed_diagnostic)
        self.assertNotIn(LATE_RACE_TEST, malformed_diagnostic)

        # Wrong child exits and unsafe pointers must not authenticate a
        # compile identity or copy untrusted text into the public diagnostic.
        for unsafe_fixture_code in (
                fixture_code.replace("test=swapz-primary-late-race-test.py exit=2 ",
                                     "test=swapz-primary-late-race-test.py exit=3 "),
                fixture_code.replace(
                    "log=build/tests/rootless-failure.ABCD1234/diagnostic.log",
                    "log=/private/unsafe/diagnostic.log")):
            unsafe_report = {"stages": []}
            with contextlib.redirect_stdout(io.StringIO()):
                unsafe_status = reporter.run_stage(
                    "Native and rootless contracts",
                    [sys.executable, "-c", unsafe_fixture_code], unsafe_report)
            self.assertEqual(unsafe_status, 2)
            unsafe_stage = unsafe_report["stages"][0]
            self.assertEqual(unsafe_stage["exit_code"], 2)
            self.assertEqual(unsafe_stage["diagnostic"],
                             "Rootless failure marker malformed or unverified")
            self.assertNotIn(PRIVATE_SENTINEL, unsafe_stage["diagnostic"])
            self.assertNotIn("/private/", unsafe_stage["diagnostic"])
            self.assertNotIn(LATE_RACE_TEST, unsafe_stage["diagnostic"])

    def test_official_native_stage_keeps_first_unittest_failure(self):
        reporter_spec = importlib.util.spec_from_file_location(
            "swapz_rootless_attribution_reporter", ROOT / "tests/tools/run-tests.py")
        self.assertIsNotNone(reporter_spec.loader)
        reporter = importlib.util.module_from_spec(reporter_spec)
        reporter_spec.loader.exec_module(reporter)
        fixture_code = (
            "import sys\n"
            "sys.stderr.write("
            "'test_a_primary (__main__.PrimaryRealSwapContracts.test_a_primary) ... FAIL\\n'"
            "'test_b_later (__main__.PrimaryRealSwapContracts.test_b_later) ... ERROR\\n'"
            "'======================================================================\\n'"
            "'ERROR: test_b_later (__main__.PrimaryRealSwapContracts.test_b_later)\\n'"
            "'OSError: LATER_TEARDOWN_PRIVATE_PAYLOAD\\n'"
            "'======================================================================\\n'"
            "'FAIL: test_a_primary (__main__.PrimaryRealSwapContracts.test_a_primary)\\n'"
            "'AssertionError: PRIVATE_ONLY_TRACEBACK_PAYLOAD\\n'"
            "'FAIL: rootless phase=primary-real-swap-test.py subtest=unavailable "
            "test=test_a_primary exit=37 reason=unittest_assertion "
            "phase_s=1 stage_s=2 line=332 "
            "log=build/tests/rootless-failure.ABCD1234/diagnostic.log\\n'"
            "'Failed during: tests/runtime/native/primary-real-swap-test.py\\n'"
            "'Reason: exit=37 reason=unittest_assertion subtest=unavailable "
            "phase_wall_s=1 stage_wall_s=2 line=332 "
            "log=build/tests/rootless-failure.ABCD1234/diagnostic.log\\n')\n"
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
        diagnostic = report["stages"][0]["diagnostic"]
        self.assertEqual(report["stages"][0]["failed_phase"], Path(PRIMARY_PHASE).name)
        self.assertEqual(
            diagnostic,
            "Unit test failed: test_a_primary; "
            "child_exit=37 reason=unittest_assertion "
            "subtest=unavailable test=test_a_primary "
            "log=build/tests/rootless-failure.ABCD1234/diagnostic.log")
        for private_detail in (
                "test_b_later", LATER_TEARDOWN_SENTINEL, PRIVATE_SENTINEL,
                "OSError:", "/private/"):
            self.assertNotIn(private_detail, diagnostic)

        # Reverse failure kinds: a first ERROR must also take precedence over
        # a later unittest FAIL and its private cleanup details.
        first_error_fixture_code = (
            fixture_code
            .replace("test_a_primary) ... FAIL", "test_a_primary) ... ERROR")
            .replace("FAIL: test_a_primary", "ERROR: test_a_primary")
            .replace("AssertionError: PRIVATE_ONLY_TRACEBACK_PAYLOAD",
                     "PermissionError: PRIVATE_ONLY_TRACEBACK_PAYLOAD")
            .replace("test_b_later) ... ERROR", "test_b_later) ... FAIL")
            .replace("ERROR: test_b_later", "FAIL: test_b_later")
            .replace("OSError: LATER_TEARDOWN_PRIVATE_PAYLOAD",
                     "AssertionError: LATER_TEARDOWN_PRIVATE_PAYLOAD")
            .replace("reason=unittest_assertion", "reason=unittest_error"))
        first_error_report = {"stages": []}
        with contextlib.redirect_stdout(io.StringIO()):
            first_error_status = reporter.run_stage(
                "Native and rootless contracts",
                [sys.executable, "-c", first_error_fixture_code],
                first_error_report)
        self.assertEqual(first_error_status, 37)
        first_error_stage = first_error_report["stages"][0]
        self.assertEqual(first_error_stage["status"], "FAIL")
        self.assertEqual(first_error_stage["exit_code"], 37)
        self.assertEqual(first_error_stage["failed_phase"],
                         Path(PRIMARY_PHASE).name)
        self.assertEqual(
            first_error_stage["diagnostic"],
            "Unit test failed: test_a_primary; "
            "child_exit=37 reason=unittest_error "
            "subtest=unavailable test=test_a_primary "
            "log=build/tests/rootless-failure.ABCD1234/diagnostic.log")
        for private_detail in (
                "test_b_later", LATER_TEARDOWN_SENTINEL, PRIVATE_SENTINEL,
                "AssertionError:", "/private/"):
            self.assertNotIn(private_detail, first_error_stage["diagnostic"])

    def test_ci_wrapper_accepts_authoritative_rootless_marker(self):
        diagnostic_spec = importlib.util.spec_from_file_location(
            "swapz_rootless_ci_diagnostic", ROOT / "tests/tools/product_goals.py")
        self.assertIsNotNone(diagnostic_spec.loader)
        diagnostics = importlib.util.module_from_spec(diagnostic_spec)
        diagnostic_spec.loader.exec_module(diagnostics)
        lines = [
            "ERROR: test_b_later "
            "(__main__.PrimaryRealSwapContracts.test_b_later)",
            "OSError: " + LATER_TEARDOWN_SENTINEL,
            "FAIL: test_a_primary "
            "(__main__.PrimaryRealSwapContracts.test_a_primary)",
            "AssertionError: " + PRIVATE_SENTINEL,
            "FAIL: rootless phase=primary-real-swap-test.py "
            "subtest=unavailable test=test_a_primary exit=37 "
            "reason=unittest_assertion phase_s=1 stage_s=2 line=332 "
            "log=build/tests/rootless-failure.ABCD1234/diagnostic.log",
        ]
        diagnostic = diagnostics.diagnose_ci_failure(
            lines, 1, "native-rootless")
        self.assertEqual(diagnostic["status"], "FAIL")
        self.assertEqual(diagnostic["category"], "RUNTIME_ASSERTION")
        self.assertEqual(diagnostic["exit_code"], 1)
        self.assertEqual(diagnostic["child_exit_code"], 37)
        self.assertEqual(diagnostic["rootless_reason"], "unittest_assertion")
        self.assertEqual(diagnostic["phase"], "primary-real-swap-test.py")
        self.assertEqual(diagnostic["test"], "test_a_primary")
        self.assertIn(
            "build/tests/rootless-failure.ABCD1234/diagnostic.log",
            diagnostic["reason"])
        self.assertNotIn(LATER_TEARDOWN_SENTINEL, diagnostic["reason"])
        self.assertNotIn(PRIVATE_SENTINEL, diagnostic["reason"])

    def test_ordinary_exit_124_is_not_claimed_as_timeout(self):
        result = self.invoke("exit124")
        self.assert_report(result, status=124,
                           reason="timeout_or_exit_124")


if __name__ == "__main__":
    unittest.main()
