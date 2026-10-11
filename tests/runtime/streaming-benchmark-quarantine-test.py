#!/usr/bin/env python3
"""Pure rootless failure/quarantine tests. Never opens any block device."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
BENCH = HERE / "streaming-benchmark.sh"
HELPER = HERE / "streaming-benchmark-quarantine.sh"
TEARDOWN = HERE / "streaming-benchmark-teardown.sh"
ROOT = HERE.parents[1]


def bash(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", "-c", code], capture_output=True,
                          text=True, timeout=5)


class QuarantineRegression(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix="swapz-quarantine-rootless-")
        self.addCleanup(self.work.cleanup)
        self.directory = Path(self.work.name)
        self.script = BENCH.read_text(encoding="utf-8")
        self.prefix = (
            "set -u\n"
            f"source '{HELPER}'\n"
            f"TMP='{self.directory}'\n"
            "TARGET='swapz-owned-test'\n"
            "BACKING='/dev/test-owned-nullb'\n"
            "NULL_CFG='/sys/kernel/config/nullb/owned-test'\n"
            "TARGET_ACTIVE=1\nTARGET_CANDIDATE=0\nNULL_CFG_CANDIDATE=0\nIO_STARTED=1\n"
            "BENCH_QUARANTINE=0\nBENCH_QUARANTINE_REASON=''\n"
        )

    def test_bash_syntax_all_three_production_paths(self):
        for file in (BENCH, HELPER, TEARDOWN):
            with self.subTest(file=file.name):
                result = subprocess.run(["bash", "-n", str(file)],
                                        capture_output=True, text=True, timeout=4)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_hang_and_nonzero_result_never_look_like_success(self):
        for code in (124, 137, 5):
            with self.subTest(exit_code=code):
                script = self.prefix + (
                    f"timeout() {{ return {code}; }}\n"
                    "swapz_benchmark_bounded 'reader/writer fio' 2s true\n"
                    "result=$?\n"
                    'printf "RESULT:%s:QUARANTINE:%s:%s\n" '
                    '"$result" "$BENCH_QUARANTINE" "$BENCH_QUARANTINE_REASON"\n'
                )
                result = bash(script)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"RESULT:{code}:QUARANTINE:1:", result.stdout)
                self.assertIn("preserving test resources", result.stderr)

    def test_successful_mocked_bounded_command_does_not_quarantine(self):
        result = bash(self.prefix +
                      "timeout() { return 0; }\n"
                      "swapz_benchmark_bounded 'noop' 2s true\n"
                      'test "$BENCH_QUARANTINE" -eq 0\n')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dm_inventory_requires_successful_complete_query(self):
        commands = (
            (0, "  swapz-owned-test  ", 0, 0),
            (0, "other-target", 1, 0),
            (0, "", 1, 0),
            (124, "", 2, 1),
            (2, "not a complete inventory", 2, 1),
        )
        for rc, names, expected, quarantined in commands:
            with self.subTest(rc=rc, names=names):
                code = self.prefix + (
                    "timeout() {\n"
                    f"  printf '%s\\n' {names!r}\n"
                    f"  return {rc}\n"
                    "}\n"
                    "swapz_benchmark_target_exists\n"
                    "result=$?\n"
                    'printf "%s:%s\n" "$result" "$BENCH_QUARANTINE"\n'
                )
                r = bash(code)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn(f"{expected}:{quarantined}", r.stdout)

    def test_only_correct_uuid_allows_target_removal(self):
        for observed, rc, expected in (
            ("SWAPZ-V22-our-case", 0, 0),
            ("SWAPZ-V22-foreign-case", 0, 1),
            ("", 0, 1),
            ("SWAPZ-V22-our-case", 124, 1),
        ):
            with self.subTest(observed=observed, rc=rc):
                trace = self.directory / "dm-remove-attempt"
                trace.unlink(missing_ok=True)
                script = (self.prefix +
                    f"TARGET_UUID='SWAPZ-V22-our-case'\n"
                    f"timeout() {{ printf '%s\\n' {observed!r}; return {rc}; }}\n"
                    "swapz_benchmark_verify_owned_target\n"
                    "code=$?\n"
                    "printf '%s:%s\\n' \"$code\" \"$BENCH_QUARANTINE\"\n")
                result = bash(script)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"{expected}:{expected}", result.stdout)

    def test_mismatched_uuid_never_calls_dm_remove(self):
        trace = self.directory / "dm-removed"
        script = (self.prefix +
            f"source '{TEARDOWN}'\n"
            "TARGET_UUID='SWAPZ-V22-our-case'\n"
            "timeout() { printf 'SWAPZ-V22-foreign-case\\n'; return 0; }\n"
            "dmsetup() { printf 'UNSAFE' > \"$TMP/dm-removed\"; return 0; }\n"
            "swapz_benchmark_remove_target\n"
            "rc=$?\n"
            'printf "%s:%s\\n" "$rc" "$BENCH_QUARANTINE"\n')
        result = bash(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1:1", result.stdout)
        self.assertFalse(trace.exists())
        self.assertIn("refusing to remove", result.stderr)

    def test_verified_target_removed_by_uuid_not_reusable_name(self):
        trace = self.directory / "verified-remove"
        script = (self.prefix +
            f"source '{TEARDOWN}'\n"
            "TARGET_UUID='SWAPZ-V22-our-case'\n"
            'timeout() {\n'
            '  case "$*" in\n'
            '    *"-o uuid "* ) printf "%s\\n" "$TARGET_UUID" ;;\n'
            '    *" remove --retry SWAPZ-V22-our-case"* )\n'
            '      printf "%s\\n" "REMOVE_UUID" > "$TMP/verified-remove" ;;\n'
            '    *"-o name"* ) : ;;\n'
            '    * ) return 99 ;;\n'
            '  esac\n'
            '}\n'
            'swapz_benchmark_remove_target\n'
            'printf "RC:%s:ACTIVE:%s\\n" "$?" "$TARGET_ACTIVE"\n')
        r = bash(script)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("RC:0:ACTIVE:0", r.stdout)
        self.assertEqual(trace.read_text(), "REMOVE_UUID\n")

    def test_foreign_nullblk_config_is_never_powered_off(self):
        config = self.directory / "foreign-nullblk"
        config.mkdir()
        (config / "power").write_text("1\n")
        script = (
            "set -u\n"
            f"source '{TEARDOWN}'\n"
            f"NULL_CFG='{config}'\n"
            "NULL_CFG_OWNED=0\n"
            "TARGET='swapz-owned-test'\n"
            "TARGET_ACTIVE=0\nCONFIGFS_MOUNTED_BY_US=0\n"
            "BACKEND_KIND=null_blk\n"
            "dmsetup() { return 1; }\n"
            "swapz_benchmark_cleanup_resources\n"
            "printf 'RC:%s\\n' \"$?\"\n")
        result = bash(script)
        self.assertEqual(result.returncode, 0)
        self.assertIn("RC:1", result.stdout)
        self.assertEqual((config / "power").read_text(), "1\n")
        self.assertIn("not positively owned", result.stderr)

    def test_conditional_setup_cannot_ignore_config_attribute_failure(self):
        import re
        source = self.script
        calls = re.findall(
            r'swapz_benchmark_bounded "null_blk config [^"]+" 12s \\\n'
            r'[^\n]+', source)
        self.assertEqual(len(calls), 9)
        self.assertTrue(all(c.endswith("|| return 1") for c in calls),
                        "conditional ! setup_nullblk disables Bash errexit")
        self.assertIn("NULL_CFG_CANDIDATE=1", source)
        self.assertIn("NULL_CFG_OWNED=1", source)
        self.assertIn('swapz_benchmark_verify_owned_target || return 1', source)
        self.assertIn('--uuid "$TARGET_UUID"', source)

    def _cleanup_function(self) -> str:
        return "cleanup() {" + self.script.split("cleanup() {", 1)[1].split(
            "\n}\ntrap cleanup EXIT", 1)[0] + "\n}"

    def _cleanup(self, *, rc: int, target: bool, quarantine: bool = False,
                 teardown_success: bool = True):
        marker = self.directory / "QUARANTINED.json"
        if marker.exists():
            marker.unlink()
        cleanup_trace = self.directory / "attempted-cleanup"
        if cleanup_trace.exists():
            cleanup_trace.unlink()
        state = self.prefix + (
            f"TARGET_ACTIVE={int(target)}\n"
            "KEEP_ARTIFACTS=1\nREPORT_COMPLETE=0\nCASES_COMPLETED=0\n"
            "RESULTS=\"$TMP/results.jsonl\"\nBACKEND_KIND=null_blk\n"
            "BACKEND='null_blk-20MiBps-500000ns-QD1'\nNBD_STATS=''\n"
            "NBD_LOG=''\nCONFIGFS_MOUNTED_BY_US=0\n"
            f"ROOT='{ROOT}'\n"
            f"BENCH_QUARANTINE={int(quarantine)}\n"
            f"BENCH_QUARANTINE_REASON='injected uncertainty'\n"
            "swapz_benchmark_cleanup_resources() {\n"
            '  printf "unsafe teardown attempt" > "$TMP/attempted-cleanup"\n'
            f"  return {0 if teardown_success else 1}\n"
            "}\n"
            + self._cleanup_function() + "\n" +
            (f"(exit {rc})\n" if rc else "true\n") +
            "cleanup\n"
        )
        # cleanup() captures $? at entry. A simple false command provides the
        # initial nonzero status; avoid subshell exit-code masking.
        if rc:
            state = state.replace(f"(exit {rc})\ncleanup\n", f"false\ncleanup\n")
        completed = bash(state)
        return completed, marker, cleanup_trace

    def test_failed_active_io_skips_all_cleanup_and_records_quarantine(self):
        result, marker, attempted = self._cleanup(rc=1, target=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(attempted.exists(), "target cleanup was incorrectly attempted")
        self.assertTrue(marker.is_file())
        record = json.loads(marker.read_text())
        self.assertEqual(record["state"], "QUARANTINED_NO_AUTOMATIC_CLEANUP")
        self.assertTrue(record["target_active_source_reported"])
        self.assertFalse(record["independent_device_attestation"])
        self.assertNotEqual(record["exit_status"], 0)
        self.assertIn("BENCHMARK_QUARANTINED", result.stderr)
        self.assertFalse((self.directory / "completed-sweep.json").exists())

    def test_target_create_uncertainty_skips_cleanup_before_io(self):
        script = self.prefix + (
            "TARGET_ACTIVE=0\nTARGET_CANDIDATE=1\nIO_STARTED=0\n"
            "timeout() { return 124; }\n"
            "swapz_benchmark_bounded 'dm-create' 1s true || :\n"
            'test "$BENCH_QUARANTINE" -eq 1\n'
        )
        self.assertEqual(bash(script).returncode, 0)
        result, marker, attempted = self._cleanup(rc=1, target=True)
        self.assertFalse(attempted.exists())
        self.assertTrue(marker.is_file())
        self.assertNotEqual(result.returncode, 0)

    def test_failed_ordinary_teardown_creates_failure_marker_not_success(self):
        result, marker, attempted = self._cleanup(
            rc=0, target=False, teardown_success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(attempted.exists())
        self.assertTrue(marker.exists())
        self.assertNotEqual(json.loads(marker.read_text())["exit_status"], 0)

    def test_exclusive_marker_refuses_symlink_replacement(self):
        link = self.directory / "QUARANTINED.json"
        other = self.directory / "valuable"
        other.write_text("untouched")
        link.symlink_to(other)
        script = self.prefix + "swapz_benchmark_record_quarantine 'test' 1\n"
        result = bash(script)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(other.read_text(), "untouched")

    def test_no_explicit_quarantine_after_no_device_setup(self):
        # Validated bad input and no target/device allocation can safely
        # return nonzero without a misleading quarantined-host marker.
        self.assertLess(self.script.index("SWAPZ_BENCH_READ_IOPS must"),
                        self.script.index("TMP=$(mktemp"))
        self.assertIn("BENCH_QUARANTINE", self.script)


if __name__ == "__main__":
    unittest.main(verbosity=2)
