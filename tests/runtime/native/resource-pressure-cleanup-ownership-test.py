#!/usr/bin/env python3
"""Rootless ID36 cleanup ownership tests; all cgroup files are synthetic."""

from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
QUALIFIER = ROOT / "tests/tools/qualify-resource-pressure.sh"


def shell_function(name: str) -> str:
    """Extract production Bash without running privileged admission or pressure."""
    source = QUALIFIER.read_text(encoding="utf-8")
    beginning = re.search(rf"^{re.escape(name)}\(\) \{{\n", source, re.MULTILINE)
    if beginning is None:
        raise AssertionError(f"missing production helper: {name}")
    ending = re.search(r"^\}\n", source[beginning.end():], re.MULTILINE)
    if ending is None:
        raise AssertionError(f"unterminated production helper: {name}")
    return source[beginning.start():beginning.end() + ending.end()]


class CleanupOwnershipFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.functions = "\n".join(shell_function(name) for name in (
            "direct_owned_child_running", "stop_direct_owned_child",
            "classify_cleanup_cgroup_membership", "report_cleanup_refusal", "cleanup"))
        cls.source = QUALIFIER.read_text(encoding="utf-8")

    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="swapz-id36-cleanup-rootless-")
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        self.cgroup = self.root / "cgroup"
        self.cgroup.mkdir()
        self.membership = self.cgroup / "cgroup.procs"
        self.membership.write_text("", encoding="ascii")
        self.cgroup_kill = self.cgroup / "cgroup.kill"
        self.cgroup_kill.write_text("untouched\n", encoding="ascii")
        self.session = self.root / "private-session"
        self.session.mkdir()

    def execute(self, body: str = "", *, status: int = 0,
                retain: bool = False, preamble: str = "") -> subprocess.CompletedProcess[str]:
        # This stub models the kernel's refusal to remove an occupied cgroup;
        # ordinary directories contain fake control files, unlike kernfs.
        rmdir_stub = '''
rmdir() {
    if [[ -f $CGROUP/cgroup.procs && ! -s $CGROUP/cgroup.procs ]]; then
        command rm -f -- "$CGROUP/cgroup.procs" "$CGROUP/cgroup.kill"
        command rmdir -- "$CGROUP"
    else
        return 1
    fi
}
'''
        script = (
            'set -Eeuo pipefail\n'
            'CGROUP=$1\nSESSION=$2\nSTOP=$2/stop\n'
            'PAIR_PID=""\nPRESSURE_PID=""\npair_cgroup_pid="123"\n'
            'CGROUP_WAS_CREATED=1\n'
            f'RETAIN_CGROUP_AND_SESSION_FOR_INVESTIGATION={int(retain)}\n'
            'PASS_EVIDENCE="PASS_ID36_RESOURCE_PRESSURE=synthetic"\n'
            + self.functions + '\n' + rmdir_stub + preamble + '\n'
            + body + '\nset +e\n'
            + (f'(exit {status})\n' if status else 'true\n')
            + 'cleanup\n'
        )
        return subprocess.run(
            ["bash", "-c", script, "rootless-fixture", str(self.cgroup), str(self.session)],
            capture_output=True, text=True, timeout=12, check=False,
        )

    def assert_retained(self, result: subprocess.CompletedProcess[str],
                        category: str, *, expected_status: int = 2):
        self.assertEqual(result.returncode, expected_status, result.stderr)
        self.assertIn(f"observed:{category}", result.stderr)
        self.assertIn(f"original_exit:{0 if expected_status == 2 else expected_status}",
                      result.stderr)
        self.assertIn("retained_cleanup:", result.stderr)
        self.assertTrue(self.cgroup.exists())
        self.assertTrue(self.session.exists())
        self.assertEqual(self.cgroup_kill.read_text(encoding="ascii"), "untouched\n")
        self.assertNotIn("PASS_ID36_RESOURCE_PRESSURE=", result.stdout)
        self.assertNotIn(str(self.root), result.stderr)
        self.assertNotIn(" 123", result.stderr)

    def test_preexisting_nonempty_guard_would_kill_foreign_process(self):
        # Exact former predicate: nonempty cgroup.procs was treated as authority
        # to write cgroup.kill, without comparing process identities.
        self.membership.write_text("123\n456\n", encoding="ascii")
        former = subprocess.run(
            ["bash", "-c", '''
                CGROUP=$1
                if [[ -f $CGROUP/cgroup.kill &&
                      -n $(cat "$CGROUP/cgroup.procs" 2>/dev/null) ]]; then
                    printf '%s\\n' 1 > "$CGROUP/cgroup.kill"
                fi
            ''', "former-cleanup", str(self.cgroup)],
            capture_output=True, text=True, timeout=3, check=False)
        self.assertEqual(former.returncode, 0, former.stderr)
        self.assertEqual(self.cgroup_kill.read_text(encoding="ascii"), "1\n")
        self.cgroup_kill.write_text("untouched\n", encoding="ascii")
        self.assert_retained(self.execute(), "foreign")

    def test_empty_cgroup_allows_cleanup_and_only_then_pass(self):
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "PASS_ID36_RESOURCE_PRESSURE=synthetic\n")
        self.assertFalse(self.cgroup.exists())
        self.assertFalse(self.session.exists())
        self.assertEqual(result.stderr, "")

    def test_stale_admitted_pid_is_not_cleanup_authority(self):
        self.membership.write_text("123\n", encoding="ascii")
        self.assert_retained(self.execute(), "stale")

    def test_foreign_member_entering_after_initial_admission_is_retained(self):
        # The recorded readiness PID was accepted earlier; membership changed
        # while the pressure pair ran, and cleanup must not reuse that proof.
        self.membership.write_text("123\n456\n", encoding="ascii")
        self.assert_retained(self.execute(), "foreign")

    def test_malformed_duplicate_overflow_and_unreadable_inventory(self):
        for content in ("123\n123\n", "123\n-1\n", "000123\n",
                        "4194305\n", "123\n" * 129, "bad\n"):
            with self.subTest(content=content[:20]):
                self.membership.write_text(content, encoding="ascii")
                self.assert_retained(self.execute(), "malformed")
        self.membership.unlink()
        self.assert_retained(self.execute(), "unreadable")
        self.membership.mkdir()
        self.assert_retained(self.execute(), "unreadable")
        self.membership.rmdir()
        self.membership.symlink_to(self.root / "missing")
        self.assert_retained(self.execute(), "unreadable")

    def test_post_snapshot_arrival_is_rejected_before_rmdir(self):
        # The first parser returns 'empty'; a synthetic newcomer enters before
        # the second parser. No group-wide signal or recursive removal follows.
        preamble = '''
awk() {
    command awk "$@"
    if [[ ! -e $SESSION/snapshot-seen ]]; then
        : > "$SESSION/snapshot-seen"
        printf '%s\\n' 456 > "$CGROUP/cgroup.procs"
    fi
}
'''
        self.assert_retained(self.execute(preamble=preamble), "foreign")

    def test_arrival_during_rmdir_preserves_evidence(self):
        preamble = '''
rmdir() {
    printf '%s\\n' 456 > "$CGROUP/cgroup.procs"
    return 1
}
'''
        result = self.execute(preamble=preamble)
        self.assert_retained(result, "occupied-or-unremovable")
        self.assertIn("phase:rmdir", result.stderr)

    def test_reappearing_cgroup_path_after_rmdir_preserves_session(self):
        preamble = '''
rmdir() {
    command rm -f -- "$CGROUP/cgroup.procs" "$CGROUP/cgroup.kill"
    command rmdir -- "$CGROUP" || return 1
    command mkdir -- "$CGROUP"
}
'''
        result = self.execute(preamble=preamble)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("phase:post-rmdir", result.stderr)
        self.assertTrue(self.cgroup.exists())
        self.assertTrue(self.session.exists())
        self.assertNotIn("PASS_ID36_RESOURCE_PRESSURE=", result.stdout)

    def test_prior_retention_and_original_failure_precedence(self):
        self.assert_retained(self.execute(retain=True), "foreign-or-uncertain")
        self.membership.write_text("456\n", encoding="ascii")
        result = self.execute(status=1)
        self.assert_retained(result, "foreign", expected_status=1)
        self.assertIn("FAIL: ID36 cleanup ownership refused", result.stderr)
        result = self.execute(status=143)
        self.assertEqual(result.returncode, 143, result.stderr)
        self.assertIn("original_exit:143", result.stderr)
        self.assertTrue(self.session.exists())

    def test_failed_initial_cgroup_creation_never_removes_other_cgroup(self):
        result = self.execute(preamble="CGROUP_WAS_CREATED=0\n")
        self.assert_retained(result, "unowned")

    def test_missing_previously_created_cgroup_retains_session(self):
        self.membership.unlink()
        self.cgroup_kill.unlink()
        self.cgroup.rmdir()
        result = self.execute()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("phase:cgroup-identity", result.stderr)
        self.assertTrue(self.session.exists())
        self.assertNotIn("PASS_ID36_RESOURCE_PRESSURE=", result.stdout)

    def test_untracked_live_pid_is_not_signaled(self):
        # The 'tracked' PID is actually an unrelated child of Python, never a
        # Bash background job. A forged/stale numeric PID cannot authorize kill.
        foreign = subprocess.Popen(["sleep", "30"], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: self.stop_foreign(foreign))
        self.membership.write_text(f"{foreign.pid}\n", encoding="ascii")
        result = self.execute(preamble=f"PAIR_PID={foreign.pid}\n")
        self.assert_retained(result, "foreign")
        self.assertIsNone(foreign.poll(), "cleanup must not terminate an untracked PID")

    def test_owned_direct_child_may_be_terminated_without_foreign_kill(self):
        foreign = subprocess.Popen(["sleep", "30"], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: self.stop_foreign(foreign))
        self.membership.write_text(f"{foreign.pid}\n", encoding="ascii")
        result = self.execute(preamble="sleep 30 & PAIR_PID=$!\n")
        self.assert_retained(result, "foreign")
        self.assertIsNone(foreign.poll(), "foreign cgroup member must survive")

    @staticmethod
    def stop_foreign(process: subprocess.Popen):
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

    def test_source_never_uses_cgroup_wide_termination(self):
        self.assertNotIn('> "$CGROUP/cgroup.kill"', self.source)
        self.assertIn('CGROUP_WAS_CREATED=1', self.source)
        self.assertIn('report_cleanup_refusal', self.source)


if __name__ == "__main__":
    unittest.main()
