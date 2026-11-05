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
    """Extract a top-level shell function without running the privileged script."""
    source = QUALIFIER.read_text(encoding="utf-8")
    beginning = re.search(rf"^{re.escape(name)}\(\) \{{\n", source, re.MULTILINE)
    if beginning is None:
        raise AssertionError(f"missing production helper: {name}")

    # Production helpers embed Python here-docs, whose dictionary braces can
    # look like a shell function terminator. Skip each complete here-doc before
    # accepting the function's standalone closing brace.
    here_doc = re.compile(r"<<(?P<strip>-)?\s*(?P<quote>['\"]?)(?P<word>[A-Za-z_][A-Za-z0-9_]*)(?P=quote)")
    offset = beginning.end()
    delimiter = None
    strip_tabs = False
    for line in source[beginning.end():].splitlines(keepends=True):
        if delimiter is not None:
            candidate = line.lstrip("\t") if strip_tabs else line
            if candidate.rstrip("\r\n") == delimiter:
                delimiter = None
                strip_tabs = False
            offset += len(line)
            continue
        if re.fullmatch(r"\}\r?\n?", line):
            return source[beginning.start():offset + len(line)]
        match = here_doc.search(line)
        if match is not None:
            delimiter = match.group("word")
            strip_tabs = match.group("strip") is not None
        offset += len(line)
    raise AssertionError(f"unterminated production helper: {name}")


class CleanupOwnershipFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.functions = "\n".join(shell_function(name) for name in (
            "read_owned_directory_identity", "read_open_directory_identity",
            "direct_owned_child_running", "capture_direct_child_identity",
            "signal_direct_owned_child", "signal_owned_child_if_running",
            "stop_direct_owned_child", "classify_cleanup_cgroup_membership",
            "classify_cleanup_session_entries", "report_cleanup_refusal",
            "cleanup"))
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
        # Separate synthetic invocations share one fixture only within a test;
        # discard the previous invocation's owned stop marker first.
        stop_path = self.session / "pressure.stop"
        if stop_path.is_file() and not stop_path.is_symlink():
            stop_path.unlink()

        # This stub models the kernel's refusal to remove an occupied cgroup;
        # ordinary directories contain fake control files, unlike kernfs.
        rmdir_stub = '''
rmdir() {
    if [[ $1 == "$CGROUP" ]]; then
        if [[ -f $CGROUP/cgroup.procs && ! -s $CGROUP/cgroup.procs ]]; then
            command rm -f -- "$CGROUP/cgroup.procs" "$CGROUP/cgroup.kill"
            command rmdir -- "$CGROUP"
        else
            return 1
        fi
    else
        command rmdir "$@"
    fi
}
'''
        script = (
            'set -Eeuo pipefail\n'
            'CGROUP=$1\nSESSION=$2\n'
            'READY=$2/pressure.ready\nPRESSURE_ACTIVATE=$2/pressure.activate\n'
            'PRESSURE_ACTIVE=$2/pressure.active\nSTOP=$2/pressure.stop\n'
            'PAIR_READY=$2/pair.ready\nPAIR_GO=$2/pair.go\n'
            'PRESSURE_LOG=$2/pressure.log\nPAIR_LOG=$2/pair.log\n'
            'PAIR_PID=""\nPRESSURE_PID=""\n'
            'PAIR_PROCESS_IDENTITY=""\nPRESSURE_PROCESS_IDENTITY=""\n'
            'PAIR_CGROUP_PROCESS_PID=""\nPAIR_CGROUP_PROCESS_IDENTITY=""\n'
            'PAIR_RESUME_UNCERTAIN=0\n'
            'SESSION_DIRECTORY_FD=""\nCGROUP_DIRECTORY_FD=""\n'
            'pair_cgroup_pid="123"\nCGROUP_WAS_CREATED=1\n'
            f'RETAIN_CGROUP_AND_SESSION_FOR_INVESTIGATION={int(retain)}\n'
            'PASS_EVIDENCE="PASS_ID36_RESOURCE_PRESSURE=synthetic"\n'
            + self.functions + '\n'
            + 'exec {SESSION_DIRECTORY_FD}<"$SESSION"\n'
            + 'exec {CGROUP_DIRECTORY_FD}<"$CGROUP"\n'
            + 'SESSION_IDENTITY="$(read_owned_directory_identity "$SESSION")"\n'
            + 'CGROUP_IDENTITY="$(read_owned_directory_identity "$CGROUP")"\n'
            + rmdir_stub + preamble + '\n'
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

    def test_function_extractor_keeps_heredoc_dictionary_body(self):
        function = shell_function("classify_cleanup_session_entries")
        self.assertIn("allowed = {", function)
        self.assertIn("for name in names:", function)
        self.assertIn("for name in sorted(names):", function)
        self.assertIn('output_mode="${1:-category}"', function)
        self.assertIn("\nPY\n    )\"; then", function)
        self.assertTrue(function.rstrip().endswith("}"))

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

    def test_reaped_direct_child_pid_is_stale_cleanup_membership(self):
        # A reaped child's numeric PID is no longer termination authority,
        # even if synthetic cgroup membership still reports that PID.
        preamble = '''
sleep 0.3 >/dev/null 2>&1 &
PAIR_PID=$!
PAIR_PROCESS_IDENTITY="$(capture_direct_child_identity "$PAIR_PID")"
# Preserve the admitted readiness identity after reaping.
pair_cgroup_pid="$PAIR_PID"
wait "$PAIR_PID"
printf '%s\\n' "$PAIR_PID" > "$CGROUP/cgroup.procs"
'''
        result = self.execute(preamble=preamble)
        self.assert_retained(result, "stale")
        self.assertIn("phase:membership", result.stderr)

    def test_delayed_cgroup_departure_after_stale_snapshot_can_clean(self):
        self.membership.write_text("123\n", encoding="ascii")
        # The first observation is stale; the child departs before the next.
        # The bounded grace period never grants numeric-PID signal authority.
        preamble = '''
awk() {
    command awk "$@"
    if [[ ! -e $SESSION/pressure.active ]]; then
        : > "$SESSION/pressure.active"
        : > "$CGROUP/cgroup.procs"
    fi
}
'''
        result = self.execute(preamble=preamble)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "PASS_ID36_RESOURCE_PRESSURE=synthetic\n")
        self.assertEqual(result.stderr, "")
        self.assertFalse(self.cgroup.exists())
        self.assertFalse(self.session.exists())

    def test_foreign_member_entering_after_initial_admission_is_retained(self):
        # The recorded readiness PID was accepted earlier; membership changed
        # while the pressure pair ran, and cleanup must not reuse that proof.
        self.membership.write_text("123\n456\n", encoding="ascii")
        self.assert_retained(self.execute(), "foreign")

    def test_malformed_duplicate_overflow_and_unreadable_inventory(self):
        for member_content in ("123\n123\n", "123\n-1\n", "000123\n",
                               "4194305\n", "123\n" * 129, "bad\n"):
            with self.subTest(content=member_content[:20]):
                self.membership.write_text(member_content, encoding="ascii")
                self.assert_retained(self.execute(), "malformed")
        self.membership.unlink()
        self.assert_retained(self.execute(), "unreadable")
        self.membership.mkdir()
        self.assert_retained(self.execute(), "unreadable")
        self.membership.rmdir()
        self.membership.symlink_to(self.root / "missing")
        self.assert_retained(self.execute(), "unreadable")

    def test_process_arriving_between_membership_snapshots_is_never_signaled(self):
        foreign = subprocess.Popen(["sleep", "30"], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: self.stop_foreign(foreign))
        # Stop one positively identified Bash child first. Then make the live
        # foreign process appear only after the first empty membership read.
        # The signal log must contain only the owned child, never the newcomer.
        preamble = f'''
sleep 30 >/dev/null 2>&1 &
PAIR_PID=$!
PAIR_PROCESS_IDENTITY="$(capture_direct_child_identity "$PAIR_PID")"
awk() {{
    command awk "$@"
    if [[ ! -e $SESSION/snapshot-seen ]]; then
        : > "$SESSION/snapshot-seen"
        printf '%s\\n' {foreign.pid} > "$CGROUP/cgroup.procs"
    fi
}}
signal_direct_owned_child() {{
    printf '%s\\n' "$1" >> "$SESSION/pair.log"
    command kill -TERM -- "$1"
}}
'''
        result = self.execute(preamble=preamble)
        self.assert_retained(result, "foreign")
        self.assertIn("phase:pre-rmdir", result.stderr)
        self.assertIsNone(foreign.poll(), "late foreign member must survive cleanup")
        signaled_pids = (self.session / "pair.log").read_text(
            encoding="ascii").splitlines()
        self.assertEqual(len(signaled_pids), 1, result.stderr)
        self.assertNotEqual(signaled_pids[0], str(foreign.pid))
        self.assertNotIn(str(foreign.pid), result.stderr)

    def test_arrival_during_rmdir_preserves_evidence(self):
        preamble = '''
rmdir() {
    if [[ $1 == "$CGROUP" ]]; then
        printf '%s\\n' 456 > "$CGROUP/cgroup.procs"
        return 1
    fi
    command rmdir "$@"
}
'''
        result = self.execute(preamble=preamble)
        self.assert_retained(result, "occupied-or-unremovable")
        self.assertIn("phase:rmdir", result.stderr)

    def test_reappearing_cgroup_path_after_rmdir_preserves_session(self):
        preamble = '''
rmdir() {
    if [[ $1 == "$CGROUP" ]]; then
        command rm -f -- "$CGROUP/cgroup.procs" "$CGROUP/cgroup.kill"
        command rmdir -- "$CGROUP" || return 1
        command mkdir -- "$CGROUP"
        return 0
    fi
    command rmdir "$@"
}
'''
        result = self.execute(preamble=preamble)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("phase:post-rmdir", result.stderr)
        self.assertTrue(self.cgroup.exists())
        self.assertTrue(self.session.exists())
        self.assertNotIn("PASS_ID36_RESOURCE_PRESSURE=", result.stdout)

    def test_session_replacement_after_cgroup_removal_retains_only_session(self):
        # A post-rmdir replacement cannot redirect pinned scratch ownership.
        preamble = '''
rmdir() {
    if [[ $1 == "$CGROUP" ]]; then
        command rm -f -- "$CGROUP/cgroup.procs" "$CGROUP/cgroup.kill"
        command rmdir -- "$CGROUP" || return 1
        command mv -- "$SESSION" "$SESSION.original"
        command mkdir -- "$SESSION"
        return 0
    fi
    command rmdir "$@"
}
'''
        result = self.execute(preamble=preamble)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(self.cgroup.exists())
        self.assertTrue(self.session.exists())
        self.assertTrue((self.root / "private-session.original").exists())
        self.assertIn("phase:session-identity", result.stderr)
        self.assertIn("observed:stale", result.stderr)
        self.assertIn("original_exit:0", result.stderr)
        self.assertIn("retained_cleanup:private-session", result.stderr)
        self.assertNotIn(str(self.root), result.stderr)
        self.assertNotIn("PASS_ID36_RESOURCE_PRESSURE=", result.stdout)

    def test_cgroup_replacement_before_cleanup_is_stale(self):
        preamble = '''
command rm -f -- "$CGROUP/cgroup.procs" "$CGROUP/cgroup.kill"
command rmdir -- "$CGROUP"
command mkdir -- "$CGROUP"
: > "$CGROUP/cgroup.procs"
printf '%s\\n' untouched > "$CGROUP/cgroup.kill"
'''
        result = self.execute(preamble=preamble)
        self.assert_retained(result, "stale")
        self.assertIn("phase:cgroup-identity", result.stderr)

    def test_session_replacement_cannot_be_signaled_or_deleted(self):
        target = self.root / "foreign-target"
        target.write_text("secret\n", encoding="ascii")
        preamble = '''
command rmdir -- "$SESSION"
command mkdir -- "$SESSION"
printf '%s\\n' foreign > "$SESSION/foreign.keep"
ln -s "${SESSION%/*}/foreign-target" "$STOP"
'''
        result = self.execute(preamble=preamble)
        self.assert_retained(result, "stale")
        self.assertIn("phase:session-signal", result.stderr)
        self.assertIn("retained_cleanup:child-cgroup-and-private-session",
                      result.stderr)
        self.assertEqual(target.read_text(encoding="ascii"), "secret\n")
        self.assertEqual((self.session / "foreign.keep").read_text(encoding="ascii"),
                         "foreign\n")

    def test_existing_regular_stop_marker_is_accepted(self):
        result = self.execute(preamble=': > "$STOP"\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "PASS_ID36_RESOURCE_PRESSURE=synthetic\n")
        self.assertFalse(self.cgroup.exists())
        self.assertFalse(self.session.exists())

    def test_existing_stop_symlink_is_never_followed(self):
        target = self.root / "foreign-target"
        target.write_text("secret\n", encoding="ascii")
        preamble = 'ln -s "${SESSION%/*}/foreign-target" "$STOP"\n'
        result = self.execute(preamble=preamble)
        self.assert_retained(result, "stale")
        self.assertIn("phase:session-signal", result.stderr)
        self.assertEqual(target.read_text(encoding="ascii"), "secret\n")

    def test_unknown_session_entry_blocks_nonrecursive_cleanup(self):
        result = self.execute(preamble="printf '%s\\n' foreign > \"$SESSION/foreign.keep\"\n")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(self.cgroup.exists())
        self.assertTrue(self.session.exists())
        self.assertEqual((self.session / "foreign.keep").read_text(encoding="ascii"),
                         "foreign\n")
        self.assertTrue((self.session / "pressure.stop").is_file())
        self.assertIn("phase:session-inventory", result.stderr)
        self.assertIn("observed:unexpected", result.stderr)
        self.assertIn("original_exit:0", result.stderr)
        self.assertIn("retained_cleanup:private-session", result.stderr)
        self.assertNotIn("retained_cleanup:child-cgroup-and-private-session",
                         result.stderr)
        self.assertNotIn("PASS_ID36_RESOURCE_PRESSURE=", result.stdout)

    def test_known_session_entry_arriving_after_inventory_is_retained(self):
        # The former bulk rm listed every canonical name, so this late file was
        # created after inventory and then erased by that same rm invocation.
        # Snapshot-only deletion must leave it for the final rmdir refusal.
        preamble = '''
SESSION_RM_INJECTED=0
rm() {
    if [[ $# -ge 2 && $1 == -f && $2 == -- &&
          $SESSION_RM_INJECTED == 0 ]]; then
        SESSION_RM_INJECTED=1
        printf '%s\\n' late > "$SESSION/pair.log"
    fi
    command rm "$@"
}
'''
        result = self.execute(preamble=preamble)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(self.cgroup.exists())
        self.assertTrue(self.session.exists())
        self.assertEqual((self.session / "pair.log").read_text(encoding="ascii"),
                         "late\n")
        self.assertIn("phase:session-remove", result.stderr)
        self.assertIn("observed:occupied-or-unremovable", result.stderr)
        self.assertIn("original_exit:0", result.stderr)
        self.assertIn("retained_cleanup:private-session", result.stderr)
        self.assertNotIn(str(self.root), result.stderr)
        self.assertNotIn("PASS_ID36_RESOURCE_PRESSURE=", result.stdout)

    def test_final_private_session_rmdir_failure_preserves_signal_exit(self):
        # An identity-validated, emptied session can still fail its final
        # rmdir. The already removed cgroup must not be reported as retained.
        preamble = '''
rmdir() {
    if [[ $1 == "$SESSION" ]]; then
        printf x >> "$SESSION/../session-rmdir-attempts"
        return 16
    fi
    if [[ $1 == "$CGROUP" ]]; then
        if [[ -f $CGROUP/cgroup.procs && ! -s $CGROUP/cgroup.procs ]]; then
            command rm -f -- "$CGROUP/cgroup.procs" "$CGROUP/cgroup.kill"
            command rmdir -- "$CGROUP"
        else
            return 1
        fi
    else
        command rmdir "$@"
    fi
}
'''
        original_session_identity = (
            self.session.stat().st_dev, self.session.stat().st_ino)
        result = self.execute(preamble=preamble, status=143)
        self.assertEqual(result.returncode, 143, result.stderr)
        self.assertFalse(self.cgroup.exists())
        self.assertTrue(self.session.exists())
        retained_session_identity = (
            self.session.stat().st_dev, self.session.stat().st_ino)
        self.assertEqual(retained_session_identity, original_session_identity)
        self.assertEqual(tuple(self.session.iterdir()), ())
        self.assertEqual(
            (self.root / "session-rmdir-attempts").read_text(encoding="ascii"),
            "x")
        self.assertIn("FAIL: ID36 private scratch cleanup did not complete",
                      result.stderr)
        self.assertIn("phase:session-remove", result.stderr)
        self.assertIn("required:same created removable private session with only known entries",
                      result.stderr)
        self.assertIn("observed:occupied-or-unremovable", result.stderr)
        self.assertIn("original_exit:143", result.stderr)
        self.assertIn("retained_cleanup:private-session", result.stderr)
        self.assertNotIn("retained_cleanup:child-cgroup-and-private-session",
                         result.stderr)
        self.assertEqual(result.stderr.count("phase:"), 1, result.stderr)
        self.assertNotIn(str(self.root), result.stderr)
        self.assertNotIn("PASS_ID36_RESOURCE_PRESSURE=", result.stdout)

    def test_private_session_replacement_after_final_rmdir_is_retained(self):
        # A successful rmdir does not authorize a new session at the old path.
        # The pinned descriptor keeps the original identity distinguishable.
        preamble = '''
rmdir() {
    if [[ $1 == "$CGROUP" ]]; then
        if [[ -f $CGROUP/cgroup.procs && ! -s $CGROUP/cgroup.procs ]]; then
            command rm -f -- "$CGROUP/cgroup.procs" "$CGROUP/cgroup.kill"
            command rmdir -- "$CGROUP"
        else
            return 1
        fi
    elif [[ $1 == "$SESSION" ]]; then
        command rmdir -- "$SESSION" || return 1
        command mkdir -- "$SESSION"
    else
        command rmdir "$@"
    fi
}
'''
        original_session_identity = (
            self.session.stat().st_dev, self.session.stat().st_ino)
        result = self.execute(preamble=preamble)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertFalse(self.cgroup.exists())
        self.assertTrue(self.session.exists())
        replacement_session_identity = (
            self.session.stat().st_dev, self.session.stat().st_ino)
        self.assertNotEqual(replacement_session_identity, original_session_identity)
        self.assertEqual(tuple(self.session.iterdir()), ())
        self.assertIn("phase:session-post-rmdir", result.stderr)
        self.assertIn("observed:stale", result.stderr)
        self.assertIn("original_exit:0", result.stderr)
        self.assertIn("retained_cleanup:private-session", result.stderr)
        self.assertNotIn("retained_cleanup:child-cgroup-and-private-session",
                         result.stderr)
        self.assertEqual(result.stderr.count("phase:"), 1, result.stderr)
        self.assertNotIn(str(self.root), result.stderr)
        self.assertNotIn("PASS_ID36_RESOURCE_PRESSURE=", result.stdout)

    def test_interrupted_session_unlink_keeps_original_failure_and_evidence(self):
        # Model an interrupted unlink after one known file was removed.
        # Earlier FAIL wins, and the remaining session is still quarantined.
        preamble = '''
: > "$SESSION/pair.log"
rm() {
    if [[ $# -ge 2 && $1 == -f && $2 == -- ]]; then
        command rm -f -- "$SESSION/pair.log"
        return 130
    fi
    command rm "$@"
}
'''
        result = self.execute(preamble=preamble, status=1)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(self.cgroup.exists())
        self.assertTrue(self.session.exists())
        self.assertFalse((self.session / "pair.log").exists())
        self.assertTrue((self.session / "pressure.stop").exists())
        self.assertIn("FAIL: ID36 private scratch cleanup did not complete",
                      result.stderr)
        self.assertIn("phase:session-remove", result.stderr)
        self.assertIn("observed:unremovable-known-entry", result.stderr)
        self.assertIn("original_exit:1", result.stderr)
        self.assertIn("retained_cleanup:private-session", result.stderr)
        self.assertNotIn(str(self.root), result.stderr)
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
        preamble = '''
command rm -f -- "$CGROUP/cgroup.procs" "$CGROUP/cgroup.kill"
command rmdir -- "$CGROUP"
'''
        result = self.execute(preamble=preamble)
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
        preamble = '''
sleep 30 >/dev/null 2>&1 &
PAIR_PID=$!
PAIR_PROCESS_IDENTITY="$(capture_direct_child_identity "$PAIR_PID")"
'''
        result = self.execute(preamble=preamble)
        self.assert_retained(result, "foreign")
        self.assertIsNone(foreign.poll(), "foreign cgroup member must survive")

    def test_pinned_directory_identity_detects_same_path_replacement(self):
        helpers = (shell_function("read_owned_directory_identity") +
                   shell_function("read_open_directory_identity"))
        directory = self.root / "pinned"
        directory.mkdir()
        script = helpers + r'''
directory=$1
exec {directory_fd}<"$directory"
before="$(read_owned_directory_identity "$directory")"
pinned="$(read_open_directory_identity "$directory_fd")"
rmdir "$directory"
mkdir "$directory"
after="$(read_owned_directory_identity "$directory")"
[[ $before == "$pinned" ]]
[[ $after != "$pinned" ]]
'''
        result = self.run_simple_shell(script, directory)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_pidfd_identity_mismatch_refuses_signal(self):
        helpers = "\n".join(shell_function(name) for name in (
            "direct_owned_child_running", "capture_direct_child_identity",
            "signal_direct_owned_child"))
        script = helpers + r'''
sleep 30 >/dev/null 2>&1 &
tracked_pid=$!
identity="$(capture_direct_child_identity "$tracked_pid")"
bad_identity=$((identity + 1))
set +e
signal_direct_owned_child "$tracked_pid" "$bad_identity" 15
signal_status=$?
set -e
kill -0 "$tracked_pid"
kill -TERM "$tracked_pid"
wait "$tracked_pid" 2>/dev/null || true
printf '%s\n' "$signal_status"
'''
        result = subprocess.run(
            ["bash", "-c", "set -Eeuo pipefail\n" + script],
            capture_output=True, text=True, timeout=8, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "3\n")

    @staticmethod
    def run_simple_shell(script: str, *arguments: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-c", "set -Eeuo pipefail\n" + script, "fixture",
             *map(str, arguments)],
            capture_output=True, text=True, timeout=8, check=False,
        )

    @staticmethod
    def stop_foreign(process: subprocess.Popen):
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

    def test_source_never_uses_ambiguous_group_or_pid_termination(self):
        executable_source = "\n".join(
            line for line in self.source.splitlines()
            if not line.lstrip().startswith("#"))
        self.assertNotIn('> "$CGROUP/cgroup.kill"', executable_source)
        self.assertNotIn('kill -TERM -- "$tracked_pid"', executable_source)
        self.assertNotIn('kill -KILL -- "$tracked_pid"', executable_source)
        self.assertNotIn('rm -rf -- "$SESSION"', executable_source)
        self.assertIn("os.pidfd_open(pid)", self.source)
        self.assertIn("signal.pidfd_send_signal(pidfd, signal_number)", self.source)
        self.assertIn('CGROUP_IDENTITY="$(read_owned_directory_identity "$CGROUP")"',
                      self.source)
        self.assertIn('SESSION_IDENTITY="$(read_owned_directory_identity "$SESSION")"',
                      self.source)
        self.assertIn('local membership_path="/proc/self/fd/$CGROUP_DIRECTORY_FD/cgroup.procs"',
                      self.source)
        cleanup = shell_function("cleanup")
        self.assertIn("local current_identity child_cleanup_status session_fd_path",
                      cleanup)
        session_path_assignment = (
            'session_fd_path="/proc/self/fd/$SESSION_DIRECTORY_FD"')
        self.assertIn(session_path_assignment, cleanup)
        self.assertLess(
            cleanup.index("if [[ -z ${SESSION_DIRECTORY_FD:-}"),
            cleanup.index(session_path_assignment))
        self.assertIn("classify_cleanup_session_entries", self.source)
        self.assertIn("classify_cleanup_session_entries snapshot", cleanup)
        self.assertIn('rm -f -- "$session_fd_path/$session_entry"', cleanup)
        self.assertNotIn('rm -f -- "$session_fd_path/pressure.ready"', cleanup)
        self.assertIn("read_open_directory_identity", self.source)
        self.assertIn("report_cleanup_refusal", self.source)


if __name__ == "__main__":
    unittest.main()
