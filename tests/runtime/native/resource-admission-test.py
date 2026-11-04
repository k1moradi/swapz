#!/usr/bin/env python3
"""Rootless, isolated resource-admission regressions; no real cgroup or /tmp mutation."""

from pathlib import Path
import contextlib
import importlib.util
import io
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
QUALIFIER = ROOT / "tests/tools/qualify-resource-pressure.sh"
PREFLIGHT = ROOT / "tests/tools/loaded-preflight.sh"
CLEANUP_WRAPPER = ROOT / "tests/tools/clear-tmp-before-memory-check.sh"
FLOOR_KIB = 1024 * 1024
FLOOR_BYTES = FLOOR_KIB * 1024
U64_MAX = (1 << 64) - 1


def shell_function(path: Path, name: str) -> str:
    """Extract a top-level shell function without executing its privileged script."""
    source = path.read_text(encoding="utf-8")
    start = re.search(rf"^{re.escape(name)}\(\) \{{\n", source, re.MULTILINE)
    if start is None:
        raise AssertionError(f"missing function: {name}")
    end = re.search(r"^\}\n", source[start.end():], re.MULTILINE)
    if end is None:
        raise AssertionError(f"unterminated function: {name}")
    return source[start.start():start.end() + end.end()]


def parent_gate() -> str:
    source = QUALIFIER.read_text(encoding="utf-8")
    begin = source.index('if ! parent_memory_inventory="$(read_cgroup_root_memory_inventory)"; then')
    end = source.index('\nif ! token="$(od ', begin)
    return source[begin:end]


def meminfo(available_kib: int) -> str:
    return (
        "MemTotal:       4194304 kB\n"
        f"MemAvailable:   {available_kib} kB\n"
        "MemFree:        2097152 kB\n"
        "Cached:         1048576 kB\n"
        "SReclaimable:   131072 kB\n"
        "SwapTotal:      0 kB\n"
        "SwapFree:       0 kB\n"
    )


class ResourceAdmissionFixtures(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="swapz-resource-admission-fixture-")
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)

    def run_shell(self, script: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-c", "set -Eeuo pipefail\n" + script, "fixture", *map(str, arguments)],
            capture_output=True, text=True, timeout=8, check=False,
        )

    def host_samples(self, samples: list[str]) -> subprocess.CompletedProcess[str]:
        paths = []
        for index, sample in enumerate(samples):
            path = self.root / f"meminfo-{index}"
            path.write_text(sample, encoding="ascii")
            paths.append(path)
        count_file = self.root / "sample-count"
        parse_memory = shell_function(QUALIFIER, "read_host_memory_inventory").replace(
            "read_host_memory_inventory() {", "parse_fixture_meminfo() {", 1)
        sample_memory = shell_function(QUALIFIER, "sample_host_memory_admission")
        script = parse_memory + sample_memory + r'''
MIN_AVAILABLE_KIB=1048576
counter_file=$1
shift
samples=("$@")
printf '0\n' > "$counter_file"
read_host_memory_inventory() {
    local index
    index="$(cat "$counter_file")"
    printf '%s\n' "$((index + 1))" > "$counter_file"
    parse_fixture_meminfo "${samples[index]}"
}
sleep() { :; }
sample_host_memory_admission
'''
        return self.run_shell(script, count_file, *paths)

    def parent_inventory(self, maximum=None, current=None, *, gate=True):
        directory = self.root / "parent-cgroup"
        directory.mkdir(exist_ok=True)
        for name, value in (("memory.max", maximum), ("memory.current", current)):
            path = directory / name
            if path.is_file():
                path.unlink()
            if path.is_dir():
                path.rmdir()
            if value is not None:
                path.write_text(str(value) + "\n", encoding="ascii")
        # A synthetic mountinfo record is required for the two-absent-files
        # root exemption. Fixture paths never inspect host mount provenance.
        (directory / "mountinfo").write_text(
            f"7 1 0:7 / {directory} rw - cgroup2 cgroup rw\n",
            encoding="ascii",
        )
        script = (
            "CGROUP_ROOT=$1\nCGROUP_MOUNTINFO=$1/mountinfo\n"
            f"MIN_AVAILABLE_BYTES={FLOOR_BYTES}\n"
            + shell_function(QUALIFIER, "cgroup_root_exemption_proven")
            + shell_function(QUALIFIER, "read_cgroup_root_memory_inventory")
            + (parent_gate() + "\nprintf 'ADMITTED\\n'\n" if gate else
               "read_cgroup_root_memory_inventory\n")
        )
        return self.run_shell(script, directory)

    def assert_blocked(self, result: subprocess.CompletedProcess[str], gate: str):
        self.assertEqual(result.returncode, 2, (result.stdout, result.stderr))
        self.assertIn("BLOCKED: ID36 " + gate, result.stderr)
        self.assertNotIn(str(self.root), result.stderr)
        self.assertNotIn("ADMITTED", result.stdout)

    def test_exact_1_gib_host_boundary_admits_two_stable_samples(self):
        result = self.host_samples([meminfo(FLOOR_KIB)] * 2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")

    def test_one_kib_below_host_floor_blocks_and_reports_observed_values(self):
        result = self.host_samples([meminfo(FLOOR_KIB - 1)] * 5)
        self.assert_blocked(result, "host lacks 1 GiB MemAvailable")
        self.assertIn(f"last:{FLOOR_KIB - 1}", result.stderr)
        self.assertIn(f"required:{FLOOR_KIB}", result.stderr)
        self.assertIn("samples:5", result.stderr)

    def test_unstable_samples_cannot_pass_on_a_single_high_reading(self):
        result = self.host_samples([meminfo(value) for value in (
            FLOOR_KIB, FLOOR_KIB - 1, FLOOR_KIB, FLOOR_KIB - 1, FLOOR_KIB)])
        self.assert_blocked(result, "host lacks 1 GiB MemAvailable")
        self.assertIn(f"minimum:{FLOOR_KIB - 1}", result.stderr)
        self.assertIn(f"maximum:{FLOOR_KIB}", result.stderr)

    def test_consecutive_recovery_can_admit_within_bounded_retries(self):
        result = self.host_samples([
            meminfo(FLOOR_KIB - 1), meminfo(FLOOR_KIB), meminfo(FLOOR_KIB)])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_and_malformed_meminfo_are_never_sufficient(self):
        incomplete = meminfo(FLOOR_KIB).replace("MemAvailable:", "OtherField:")
        duplicated = meminfo(FLOOR_KIB) + f"MemAvailable: {FLOOR_KIB} kB\n"
        overflow = meminfo(FLOOR_KIB).replace(
            f"MemAvailable:   {FLOOR_KIB}", "MemAvailable:   9999999999999999999")
        for sample in (incomplete, duplicated, overflow):
            with self.subTest(sample=sample[:30]):
                self.assert_blocked(self.host_samples([sample]), "MemAvailable unavailable")
        # The temporary source path is intentionally absent; awk errors must
        # not escape into an owner-facing diagnostic.
        original = shell_function(QUALIFIER, "read_host_memory_inventory")
        admission = shell_function(QUALIFIER, "sample_host_memory_admission")
        script = f"MIN_AVAILABLE_KIB={FLOOR_KIB}\n" + original + admission + (
            'sample_host_memory_admission "$1"\n')
        self.assert_blocked(self.run_shell(script, self.root / "unreadable"), "MemAvailable unavailable")

    def test_finite_parent_high_u64_exact_boundary(self):
        current = U64_MAX - FLOOR_BYTES
        result = self.parent_inventory(U64_MAX, current)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "ADMITTED\n")
        inventory = self.parent_inventory(U64_MAX, current, gate=False)
        self.assertEqual(inventory.stdout.strip(),
                         f"{U64_MAX} {current} sufficient")

    def test_finite_parent_one_byte_short_reports_exact_deficit(self):
        current = U64_MAX - FLOOR_BYTES + 1
        result = self.parent_inventory(U64_MAX, current)
        self.assert_blocked(result, "cgroup root lacks 1 GiB effective memory headroom")
        for expected in (f"memory.max:{U64_MAX}", f"memory.current:{current}",
                         f"headroom:{FLOOR_BYTES - 1}", "deficit:1", "unit:bytes"):
            self.assertIn(expected, result.stderr)

    def test_parent_unsigned_overflow_and_noncanonical_counters_block(self):
        for maximum, current in ((U64_MAX + 1, 0), (U64_MAX, U64_MAX + 1),
                                 ("001", 0), (100, 101), ("invalid", 1)):
            with self.subTest(maximum=maximum, current=current):
                self.assert_blocked(self.parent_inventory(maximum, current),
                                    "parent cgroup")

    def test_unbounded_parent_still_validates_its_current_counter(self):
        result = self.parent_inventory("max", U64_MAX)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.parent_inventory("max", U64_MAX, gate=False).stdout.strip(),
                         f"max {U64_MAX} unbounded")
        self.assert_blocked(self.parent_inventory("max", U64_MAX + 1),
                            "parent cgroup")

    def test_only_true_root_exempt_pair_can_omit_memory_controls(self):
        self.assertEqual(self.parent_inventory().returncode, 0)
        self.assertEqual(self.parent_inventory(gate=False).stdout.strip(),
                         "root-exempt root-exempt unbounded")
        self.assert_blocked(self.parent_inventory("max", None), "parent cgroup")
        self.assert_blocked(self.parent_inventory(None, 0), "parent cgroup")

    def test_absent_parent_controls_need_verified_mount_root(self):
        directory = self.root / "parent-cgroup"
        self.assertEqual(self.parent_inventory().returncode, 0)
        mountinfo = directory / "mountinfo"
        mountinfo.write_text(
            f"7 1 0:7 /other {directory} rw - cgroup2 cgroup rw\n",
            encoding="ascii",
        )
        # Use the same readonly helper, but do not regenerate the mount fixture.
        script = ("CGROUP_ROOT=$1\nCGROUP_MOUNTINFO=$1/mountinfo\n"
                  f"MIN_AVAILABLE_BYTES={FLOOR_BYTES}\n"
                  + shell_function(QUALIFIER, "cgroup_root_exemption_proven")
                  + shell_function(QUALIFIER, "read_cgroup_root_memory_inventory")
                  + parent_gate())
        result = self.run_shell(script, directory)
        self.assert_blocked(result, "parent cgroup memory.max and memory.current absent")
        self.assertIn("observed:absent", result.stderr)
        self.assertIn("required:finite parent controls or true cgroup v2 root", result.stderr)

    def test_unreadable_parent_file_blocks(self):
        directory = self.root / "parent-cgroup"
        directory.mkdir()
        (directory / "memory.max").write_text("max\n")
        (directory / "memory.current").mkdir()
        script = (f"CGROUP_ROOT=$1\nMIN_AVAILABLE_BYTES={FLOOR_BYTES}\n"
                  + shell_function(QUALIFIER, "read_cgroup_root_memory_inventory")
                  + parent_gate())
        self.assert_blocked(self.run_shell(script, directory), "parent cgroup")

    def test_oom_and_psi_missing_or_malformed_counter_blocks(self):
        directory = self.root / "pressure"
        directory.mkdir()
        memory_events = directory / "memory.events"
        cpu_pressure = directory / "cpu.pressure"
        memory_events.write_text("high 0\noom 0\noom_kill 0\n", encoding="ascii")
        cpu_pressure.write_text(
            "some avg10=0.00 avg60=0.00 avg300=0.00 total=0\n",
            encoding="ascii")
        functions = (shell_function(QUALIFIER, "read_memory_event_inventory") +
                     shell_function(QUALIFIER, "cpu_some_total"))
        script = 'CGROUP=$1\n' + functions

        result = self.run_shell(
            script + 'read_memory_event_inventory\ncpu_some_total\n', directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "0 0 0\n0\n")

        memory_events.write_text(
            "high 0\noom 0\noom 1\noom_kill 0\n", encoding="ascii")
        result = self.run_shell(
            script + 'read_memory_event_inventory\n', directory)
        self.assert_blocked(result, "memory.events counter oom malformed")
        self.assertIn("observed:malformed", result.stderr)

        memory_events.write_text("high 0\noom 0\n", encoding="ascii")
        result = self.run_shell(
            script + 'read_memory_event_inventory\n', directory)
        self.assert_blocked(result, "memory.events counter oom_kill missing")
        self.assertIn("observed:missing", result.stderr)

        memory_events.unlink()
        result = self.run_shell(
            script + 'read_memory_event_inventory\n', directory)
        self.assert_blocked(result, "memory.events telemetry unreadable")
        self.assertIn("observed:unavailable", result.stderr)

        memory_events.mkdir()
        result = self.run_shell(
            script + 'read_memory_event_inventory\n', directory)
        self.assert_blocked(result, "memory.events telemetry unreadable")
        self.assertIn("observed:unavailable", result.stderr)
        memory_events.rmdir()
        memory_events.write_text("high 0\noom 0\noom_kill 0\n",
                                 encoding="ascii")

        for invalid, expected in (
                ("some avg10=-0.01 avg60=0.00 avg300=0.00 total=0\n",
                 "cpu.pressure some avg10 negative"),
                ("some avg10=0.00 avg60=0.00 avg300=0.00 total=-1\n",
                 "cpu.pressure some total negative"),
                ("some avg10=0.00 avg60=0.00 avg300=0.00 total=-oops\n",
                 "cpu.pressure some telemetry malformed: observed:malformed prerequisite:total"),
                ("some avg10=101 avg60=0.00 avg300=0.00 total=0\n",
                 "cpu.pressure some avg10 outside percentage range"),
                ("some avg10=0.00 avg60=0.00 total=0\n",
                 "cpu.pressure some telemetry missing: observed:missing prerequisite:avg300")):
            with self.subTest(invalid=invalid.strip()):
                cpu_pressure.write_text(invalid, encoding="ascii")
                result = self.run_shell(script + 'cpu_some_total\n', directory)
                self.assert_blocked(result, expected)

        # Ignore future unrelated PSI key/value extensions while retaining the
        # required known fields and their ranges.
        cpu_pressure.write_text(
            "some avg10=0.00 avg60=0.00 avg300=0.00 total=7 future=1\n",
            encoding="ascii")
        result = self.run_shell(script + 'cpu_some_total\n', directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "7\n")

        cpu_pressure.unlink()
        result = self.run_shell(script + 'cpu_some_total\n', directory)
        self.assert_blocked(result, "cpu.pressure some telemetry unreadable")
        self.assertIn("observed:unavailable", result.stderr)

        cpu_pressure.mkdir()
        result = self.run_shell(script + 'cpu_some_total\n', directory)
        self.assert_blocked(result, "cpu.pressure some telemetry unreadable")
        self.assertIn("observed:unavailable", result.stderr)

    def test_bounded_child_diagnostics_preserve_reason_without_private_paths(self):
        directory = self.root / "logs"
        directory.mkdir()
        log = directory / "pair.log"
        helper = shell_function(QUALIFIER, "bounded_safe_log_reason")
        script = helper + 'bounded_safe_log_reason "$1" "$2"\n'

        log.write_text(
            "BLOCKED: ID36 allocation-bounded native replay helper missing\n",
            encoding="ascii")
        result = self.run_shell(script, log, "BLOCKED: ")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "ID36 allocation-bounded native replay helper missing")

        log.write_text(
            "BLOCKED: prerequisite failed under /private/host/path\n",
            encoding="ascii")
        result = self.run_shell(script, log, "BLOCKED: ")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "diagnostic details withheld for privacy")
        self.assertNotIn("/private/host/path", result.stdout)

        log.write_text(
            ("noise\n" * 128) + "BLOCKED: too late to expose\n",
            encoding="ascii")
        result = self.run_shell(script, log, "BLOCKED: ")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_bounded_child_diagnostic_unavailable_returns_status_two(self):
        helper = shell_function(QUALIFIER, "bounded_safe_log_reason")
        script = helper + 'bounded_safe_log_reason "$1" "FAIL: "\n'
        missing = self.root / "missing-private-log"
        result = self.run_shell(script, missing)
        self.assertEqual(result.returncode, 2, (result.stdout, result.stderr))
        self.assertEqual(result.stdout, "")
        self.assertNotIn(str(missing), result.stderr)

    def test_cgroup_word_distinguishes_absent_from_unreadable_telemetry(self):
        helper = shell_function(QUALIFIER, "require_cgroup_word")
        source = self.root / "controllers"
        script = (
            helper +
            'require_cgroup_word "$1" cgroup.controllers memory '
            '"memory controller unavailable; enable it"\n'
        )

        source.write_text("cpu memory\n", encoding="ascii")
        result = self.run_shell(script, source)
        self.assertEqual(result.returncode, 0, result.stderr)

        source.write_text("cpu\n", encoding="ascii")
        result = self.run_shell(script, source)
        self.assertEqual(result.returncode, 2, (result.stdout, result.stderr))
        self.assertIn(
            "BLOCKED: ID36 memory controller unavailable; enable it",
            result.stderr)

        source.unlink()
        source.mkdir()
        result = self.run_shell(script, source)
        self.assertEqual(result.returncode, 2, (result.stdout, result.stderr))
        self.assertIn(
            "BLOCKED: ID36 cgroup.controllers telemetry unavailable while checking memory",
            result.stderr)
        self.assertNotIn(str(source), result.stderr)

    def test_pair_ready_pid_requires_one_canonical_bounded_value(self):
        helper = shell_function(QUALIFIER, "read_pair_ready_pid")
        ready = self.root / "pair.ready"
        script = helper + 'read_pair_ready_pid "$1"\n'

        ready.write_text("pid=123\n", encoding="ascii")
        result = self.run_shell(script, ready)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "123")

        for contents in (
                "pid=0\n",
                "pid=0123\n",
                "pid=-1\n",
                "pid=123\npid=124\n",
                "pid=1000000000000000000\n",
                "pid=4194305\n",
                "other=123\n"):
            with self.subTest(contents=contents):
                ready.write_text(contents, encoding="ascii")
                result = self.run_shell(script, ready)
                self.assertNotEqual(result.returncode, 0)

        ready.unlink()
        result = self.run_shell(script, ready)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(str(ready), result.stderr)

    def test_cgroup_control_write_failure_is_blocked_without_path_leak(self):
        directory = self.root / "cgroup"
        directory.mkdir()
        (directory / "memory.max").mkdir()
        helper = shell_function(QUALIFIER, "write_cgroup_control")
        script = 'CGROUP=$1\n' + helper + 'write_cgroup_control memory.max 1\n'
        result = self.run_shell(script, directory)
        self.assertEqual(result.returncode, 2, (result.stdout, result.stderr))
        self.assertIn(
            "BLOCKED: ID36 cannot set cgroup control memory.max",
            result.stderr)
        self.assertNotIn(str(directory), result.stderr)

    def test_oom_and_psi_counter_regression_refuses_named_bound(self):
        helper = shell_function(QUALIFIER, "require_monotonic_counter")
        script = helper + 'require_monotonic_counter "$1" "$2" "$3" "$4"\n'
        for name, unit in (("memory.events oom", "events"),
                           ("memory.events oom_kill", "events"),
                           ("cpu.pressure some total", "usec")):
            with self.subTest(name=name):
                result = self.run_shell(script, name, 100, 99, unit)
                self.assert_blocked(result, name)
                self.assertIn("observed:99 expected_min:100", result.stderr)
                self.assertEqual(
                    self.run_shell(script, name, 100, 100, unit).returncode, 0)

    def test_pair_cgroup_membership_is_exact_and_bounded(self):
        directory = self.root / "membership"
        directory.mkdir()
        procfile = directory / "cgroup.procs"
        script = ('CGROUP=$1\n'
                  + shell_function(QUALIFIER, "verify_pair_cgroup_membership")
                  + 'verify_pair_cgroup_membership 123\n')
        procfile.write_text("123\n", encoding="ascii")
        self.assertEqual(self.run_shell(script, directory).returncode, 0)
        for content, expected_code, label in (
                ("", 1, "FAIL: ID36 readiness PID absent"),
                ("456\n", 2, "BLOCKED: ID36 readiness PID inventory prerequisite"),
                ("123\n456\n", 2,
                 "BLOCKED: ID36 readiness PID inventory prerequisite"),
                ("123\n123\n", 2, "BLOCKED: ID36 cgroup.procs"),
                ("123\n-1\n", 2, "BLOCKED: ID36 cgroup.procs"),
                ("123\n" * 129, 2, "BLOCKED: ID36 cgroup.procs")):
            with self.subTest(content=content[:25]):
                procfile.write_text(content, encoding="ascii")
                result = self.run_shell(script, directory)
                self.assertEqual(result.returncode, expected_code, result.stderr)
                self.assertIn(label, result.stderr)
                self.assertNotIn(str(directory), result.stderr)
        procfile.unlink()
        self.assert_blocked(self.run_shell(script, directory), "cgroup.procs")

    def test_foreign_pair_cgroup_member_retains_cleanup_resources(self):
        cgroup_directory = self.root / "contaminated-cgroup"
        cgroup_directory.mkdir()
        (cgroup_directory / "cgroup.procs").write_text(
            "123\n456\n", encoding="ascii")
        cgroup_kill = cgroup_directory / "cgroup.kill"
        cgroup_kill.write_text("unchanged\n", encoding="ascii")
        session_directory = self.root / "retained-session"
        session_directory.mkdir()
        script = (
            'CGROUP=$1\nSESSION=$2\nSTOP=$2/stop\n'
            'PAIR_PID=""\nPRESSURE_PID=""\nPASS_EVIDENCE=""\n'
            'RETAIN_CGROUP_AND_SESSION_FOR_INVESTIGATION=0\n'
            + shell_function(QUALIFIER, "verify_pair_cgroup_membership")
            + shell_function(QUALIFIER, "cleanup")
            + 'set +e\n'
            + 'verify_pair_cgroup_membership 123\n'
            + 'cleanup\n')
        result = self.run_shell(script, cgroup_directory, session_directory)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("observed:foreign process present", result.stderr)
        self.assertIn(
            "retained cleanup: private child cgroup and scratch retained",
            result.stderr)
        self.assertTrue(cgroup_directory.is_dir())
        self.assertTrue(session_directory.is_dir())
        self.assertEqual(cgroup_kill.read_text(encoding="ascii"), "unchanged\n")
        self.assertNotIn(str(cgroup_directory), result.stderr)
        self.assertNotIn(str(session_directory), result.stderr)

    def test_observed_pair_failure_precedes_blocked_log_and_telemetry(self):
        log_path = self.root / "pair.log"
        script = (shell_function(QUALIFIER, "bounded_safe_log_reason")
                  + shell_function(QUALIFIER, "pair_blocked_is_prerequisite")
                  + shell_function(QUALIFIER, "preserve_pair_failure_before_telemetry")
                  + 'preserve_pair_failure_before_telemetry "$1" "$2"\n')
        log_path.write_text(
            "BLOCKED: kernel LZ4 compressor unavailable\n"
            "FAIL: byte-exact replay mismatch\n", encoding="ascii")
        result = self.run_shell(script, 1, log_path)
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL: ID36 owned-RAM pair failed: byte-exact replay mismatch",
                      result.stderr)
        self.assertNotIn(str(log_path), result.stderr)
        log_path.write_text("BLOCKED: kernel LZ4 compressor unavailable\n",
                            encoding="ascii")
        self.assertEqual(self.run_shell(script, 1, log_path).returncode, 0)

        log_path.write_text("BLOCKED: pair verification rejected\n",
                            encoding="ascii")
        result = self.run_shell(script, 2, log_path)
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "FAIL: ID36 owned-RAM pair failed: pair verification rejected",
            result.stderr)

        result = self.run_shell(script, 143, log_path)
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL: ID36 owned-RAM pair exited rc:143", result.stderr)
        log_path.unlink()
        result = self.run_shell(script, 1, log_path)
        self.assertEqual(result.returncode, 1)
        self.assertIn("private failure log unavailable", result.stderr)

    def test_cleanup_failure_preserves_fail_and_suppresses_pass(self):
        helper = shell_function(QUALIFIER, "cleanup")
        environment = ('SESSION=$1\nSTOP=$1/stop\nCGROUP=$1/absent\n'
                       'PAIR_PID=""\nPRESSURE_PID=""\n'
                       'RETAIN_CGROUP_AND_SESSION_FOR_INVESTIGATION=0\n'
                       'PASS_EVIDENCE="PASS_ID36_RESOURCE_PRESSURE=synthetic"\n'
                       'rm() { return 1; }\n'
                       + helper)
        for earlier_failure, expected_code, label in (
                (False, 2, "BLOCKED: ID36 private scratch cleanup"),
                (True, 1, "FAIL: ID36 private scratch cleanup")):
            with self.subTest(earlier_failure=earlier_failure):
                script = (environment + "\nset +e\n"
                          + ("false\n" if earlier_failure else "true\n")
                          + "cleanup\n")
                result = self.run_shell(script, self.root)
                self.assertEqual(result.returncode, expected_code, result.stderr)
                self.assertIn(label, result.stderr)
                self.assertNotIn("PASS_ID36_RESOURCE_PRESSURE=", result.stdout)

    def test_pressure_helper_reaps_partial_startup_and_dead_worker(self):
        pressure_path = ROOT / "tests/runtime/benchmark/resource-pressure.py"
        spec = importlib.util.spec_from_file_location(
            "swapz_id36_pressure_test", pressure_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        class FakeEvent:
            stopped = False
            def set(self):
                self.stopped = True

        class FakeWorker:
            def __init__(self, fail_start=False, die_after_start=False,
                         ignore_cleanup=False):
                self.fail_start = fail_start
                self.die_after_start = die_after_start
                self.ignore_cleanup = ignore_cleanup
                self.started = False
                self.alive = False
                self.join_count = 0
                self.terminated = False
            def start(self):
                if self.fail_start:
                    raise OSError("injected fork failure")
                self.started = True
                self.alive = not self.die_after_start
            def is_alive(self):
                return self.alive
            def join(self, timeout):
                self.join_count += 1
            def terminate(self):
                self.terminated = True
                if not self.ignore_cleanup:
                    self.alive = False
            def kill(self):
                if not self.ignore_cleanup:
                    self.alive = False

        class FakeMapping:
            def __len__(self):
                return 64 * 1024 * 1024
            def __setitem__(self, offset, value):
                pass
            def close(self):
                pass

        class FakeContext:
            def __init__(self, workers):
                self.workers = iter(workers)
                self.event = FakeEvent()
            def Event(self):
                return self.event
            def Process(self, **kwargs):
                return next(self.workers)

        for workers, diagnostic in (
                ([FakeWorker(), FakeWorker(fail_start=True)],
                 "worker startup failed"),
                ([FakeWorker(die_after_start=True), FakeWorker()],
                 "worker exited before readiness")):
            with self.subTest(diagnostic=diagnostic):
                context = FakeContext(workers)
                stderr = io.StringIO()
                argv = ["pressure", "--memory-mib", "64",
                        "--cpu-workers", "2",
                        "--ready-file", str(self.root / "helper.ready"),
                        "--stop-file", str(self.root / "helper.stop")]
                with mock.patch.object(module.multiprocessing, "get_context",
                                       return_value=context), \
                     mock.patch.object(module.mmap, "mmap",
                                       return_value=FakeMapping()), \
                     mock.patch.object(module.signal, "signal"), \
                     mock.patch.object(sys, "argv", argv), \
                     contextlib.redirect_stderr(stderr):
                    result = module.main()
                self.assertEqual(result, 1, stderr.getvalue())
                self.assertIn("FAIL: ID36", stderr.getvalue())
                self.assertIn(diagnostic, stderr.getvalue())
                self.assertTrue(context.event.stopped)
                self.assertTrue(workers[0].started)
                self.assertGreater(workers[0].join_count, 0)
                self.assertFalse(workers[0].is_alive())
                if workers[1].fail_start:
                    self.assertEqual(workers[1].join_count, 0)
                self.assertFalse((self.root / "helper.ready").exists())

        # A child that survives both owned TERM and KILL escalation is a
        # cleanup failure, never a successful or merely blocked helper exit.
        workers = [FakeWorker(ignore_cleanup=True), FakeWorker(fail_start=True)]
        context = FakeContext(workers)
        stderr = io.StringIO()
        argv = ["pressure", "--memory-mib", "64",
                "--cpu-workers", "2",
                "--ready-file", str(self.root / "helper.ready"),
                "--stop-file", str(self.root / "helper.stop")]
        with mock.patch.object(module.multiprocessing, "get_context",
                               return_value=context), \
             mock.patch.object(module.signal, "signal"), \
             mock.patch.object(sys, "argv", argv), \
             contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                module.main()
        self.assertEqual(raised.exception.code, 1)
        self.assertIn("CPU pressure child could not be reaped", stderr.getvalue())
        self.assertTrue(workers[0].is_alive())
        self.assertGreaterEqual(workers[0].join_count, 3)

    def test_prerequisite_command_failures_are_explicitly_guarded(self):
        source = QUALIFIER.read_text(encoding="utf-8")
        self.assertIn(
            'BLOCKED: ID36 missing required command %s;', source)
        self.assertLess(
            source.index("START_ID36_RESOURCE_PRESSURE=admission"),
            source.index("for required_command in"))
        self.assertLess(
            source.index("for required_command in"),
            source.index("[[ $(id -u) == 0 ]]"))
        self.assertIn("require_cgroup_word() {", source)
        self.assertIn(
            "cgroup v2 controller telemetry unreadable;",
            source)
        self.assertLess(
            source.index("for required_command in"),
            source.index("require_cgroup_word() {"))
        self.assertIn(
            'if ! token="$(od -An -N8 -tx1 /dev/urandom', source)
        self.assertIn(
            'if ! SESSION="$(mktemp -d "', source)
        self.assertIn(
            'mktemp -d "/tmp/swapz-id36.XXXXXXXX"', source)
        self.assertNotIn(
            '${TMPDIR:-/tmp}/swapz-id36.XXXXXXXX', source)
        self.assertIn(
            'if ! online_cpus="$(getconf _NPROCESSORS_ONLN 2>/dev/null)"; then',
            source)
        self.assertIn(
            "BLOCKED: ID36 pressure-helper prerequisite before readiness:",
            source)
        self.assertIn(
            "BLOCKED: ID36 owned-RAM pair prerequisite before prewarm:",
            source)
        self.assertIn(
            "BLOCKED: ID36 owned-RAM pair prerequisite after prewarm:",
            source)
        self.assertIn(
            'if pair_blocked_is_prerequisite "$pair_blocked_reason"; then',
            source)
        self.assertIn(
            "FAIL: ID36 owned-RAM pair failed: %s",
            source)
        self.assertIn(
            "BLOCKED: ID36 pressure helper could not enter isolated cgroup",
            source)
        self.assertIn(
            'printf "%s\\\\n" "$$" > "$cgroup/cgroup.procs"',
            source)
        self.assertNotIn(
            'printf "%s\\\\n" "$BASHPID" > "$cgroup/cgroup.procs"',
            source)

    def test_post_prewarm_blocked_diagnostics_are_classified_explicitly(self):
        helper = shell_function(QUALIFIER, "pair_blocked_is_prerequisite")
        script = helper + 'pair_blocked_is_prerequisite "$1"\n'
        for reason in (
                "kernel LZ4 compressor unavailable",
                "shared immutable replay plan missing or outside owned build root",
                "retain all remaining resources for read-only investigation"):
            with self.subTest(reason=reason):
                result = self.run_shell(script, reason)
                self.assertEqual(result.returncode, 0, result.stderr)

        for reason in (
                "swapz module insertion rejected",
                "swapz target registration missing",
                "pair verification rejected",
                "loaded target ordinary LZ4 policy is not fixed at acceleration 1",
                "diagnostic details withheld for privacy"):
            with self.subTest(reason=reason):
                result = self.run_shell(script, reason)
                self.assertNotEqual(result.returncode, 0)

    def test_bootstrap_helpers_are_guarded_without_external_dirname(self):
        qualifier = QUALIFIER.read_text(encoding="utf-8")
        preflight = PREFLIGHT.read_text(encoding="utf-8")
        self.assertNotIn('dirname -- "${BASH_SOURCE[0]}"', qualifier)
        self.assertNotIn('dirname -- "${BASH_SOURCE[0]}"', preflight)
        self.assertIn(
            "BLOCKED: ID36 owned temporary-cleanup helper unavailable",
            qualifier)
        self.assertLess(
            qualifier.index("START_ID36_RESOURCE_PRESSURE=admission"),
            qualifier.index('script_source="${BASH_SOURCE[0]}"'))
        self.assertLess(
            qualifier.index('cleanup_helper="$ROOT/tests/tools/clear-tmp-before-memory-check.sh"'),
            qualifier.index("[[ -r $cleanup_helper ]]"))
        self.assertLess(
            qualifier.index("[[ -r $cleanup_helper ]]"),
            qualifier.index('source "$cleanup_helper" 2>/dev/null'))
        self.assertIn(
            'if ! source "$cleanup_helper" 2>/dev/null; then',
            qualifier)
        self.assertLess(
            qualifier.index("START_ID36_RESOURCE_PRESSURE=admission"),
            qualifier.index('if ! source "$cleanup_helper" 2>/dev/null; then'))
        self.assertIn(
            'source "$cleanup_helper" 2>/dev/null ||',
            preflight)
        self.assertEqual(
            preflight.count(
                'refuse BLOCKED completed_owned_tmp_cleanup_helper unavailable'),
            2)
        self.assertLess(
            preflight.index('cleanup_helper="$SCRIPT_DIR/clear-tmp-before-memory-check.sh"'),
            preflight.index('[[ -r $cleanup_helper ]] ||'))
        self.assertLess(
            preflight.index('[[ -r $cleanup_helper ]] ||'),
            preflight.index('source "$cleanup_helper" 2>/dev/null ||'))
        self.assertIn(
            'cd "$ROOT" 2>/dev/null || {',
            qualifier)
        self.assertIn(
            'SCRIPT_DIR="$(cd -- "$script_directory" 2>/dev/null && pwd -P)" ||',
            preflight)

    def test_loaded_preflight_bootstrap_refuses_unavailable_cleanup(self):
        preflight = PREFLIGHT.read_text(encoding="utf-8")
        # Exercise only the bootstrap prefix, never the privileged preflight.
        bootstrap = preflight[:preflight.index("note() {")]
        bootstrap_path = self.root / "loaded-preflight.sh"
        bootstrap_path.write_text(bootstrap, encoding="utf-8")
        helper_path = self.root / "clear-tmp-before-memory-check.sh"
        retained_path = self.root / "unowned-sentinel"
        retained_path.write_text("keep", encoding="ascii")

        for helper_source in (None, "return 7\n"):
            with self.subTest(helper_source=helper_source):
                if helper_source is None:
                    helper_path.unlink(missing_ok=True)
                else:
                    helper_path.write_text(helper_source, encoding="ascii")
                result = subprocess.run(
                    ["bash", str(bootstrap_path)], capture_output=True,
                    text=True, timeout=8, check=False)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(
                    "BLOCKED: LOADED_PREFLIGHT=BLOCKED "
                    "check=completed_owned_tmp_cleanup_helper "
                    "errno=unavailable", result.stderr)
                self.assertNotIn(str(self.root), result.stderr)
                self.assertEqual(
                    retained_path.read_text(encoding="ascii"), "keep")

    def test_cleanup_helper_error_is_propagated_without_touching_tmp(self):
        # Override timeout and id inside an isolated process. The original
        # wrapper is never allowed to invoke its /tmp cleaner.
        wrapper = shell_function(CLEANUP_WRAPPER, "swapz_clear_tmp_before_memory_check")
        script = wrapper + '''
id() { printf '0\n'; }
timeout() { return 7; }
swapz_clear_tmp_before_memory_check
'''
        result = self.run_shell(script)
        self.assertEqual(result.returncode, 1)
        self.assertIn("BLOCKED: cannot safely remove verified completed", result.stderr)
        self.assertNotIn(str(self.root), result.stderr)
        preflight = PREFLIGHT.read_text(encoding="utf-8")
        self.assertIn("if swapz_clear_tmp_before_memory_check; then", preflight)
        self.assertIn("cleanup_status=$?", preflight)
        self.assertIn(
            'refuse BLOCKED completed_owned_tmp_cleanup unavailable',
            preflight)
        self.assertIn("helper_status=$cleanup_status", preflight)
        self.assertLess(
            preflight.index("if swapz_clear_tmp_before_memory_check; then"),
            preflight.index("cleanup_status=$?"))
        self.assertLess(
            preflight.index("cleanup_status=$?"),
            preflight.index(
                'refuse BLOCKED completed_owned_tmp_cleanup unavailable'))
        self.assertLess(
            preflight.index(
                'refuse BLOCKED completed_owned_tmp_cleanup unavailable'),
            preflight.index(
                'note "LOADED_PREFLIGHT_TMP_CLEANUP=completed-owned-only"'))
        self.assertIn("swapz_clear_tmp_before_memory_check ||", QUALIFIER.read_text())

    def test_no_fixture_bypasses_privileged_admission_entrypoint(self):
        source = QUALIFIER.read_text(encoding="utf-8")
        self.assertIn("CGROUP_ROOT=/sys/fs/cgroup", source)
        self.assertIn("CGROUP_MOUNTINFO=/proc/self/mountinfo", source)
        self.assertIn("MIN_AVAILABLE_KIB=$((1024 * 1024))", source)
        self.assertIn("sample_host_memory_admission || exit 2", source)
        self.assertIn("headroom:%s required:%s deficit:%s unit:bytes", source)
        self.assertIn(
            'write_cgroup_control memory.max "$MEMORY_MAX_BYTES" || exit 2',
            source)
        self.assertIn(
            'write_cgroup_control memory.high "$MEMORY_HIGH_BYTES" || exit 2',
            source)
        self.assertNotIn("event_value() {", source)
        self.assertEqual(source.count('="$(read_memory_event_inventory)" || exit 2'), 5)
        self.assertIn(
            "FAIL: ID36 pressure-boundary setup encountered OOM events",
            source)
        self.assertLess(
            source.index('memory_events_ready="$(read_memory_event_inventory)"'),
            source.index('memory_events_before="$(read_memory_event_inventory)"'))
        self.assertLess(
            source.index('memory_events_before="$(read_memory_event_inventory)"'),
            source.index(
                "FAIL: ID36 pressure-boundary setup encountered OOM events"))
        self.assertIn('rm -rf -- "$SESSION" 2>/dev/null', source)
        self.assertIn('printf -v PASS_EVIDENCE', source)
        self.assertIn('if (( result == 0 )) && [[ -n $PASS_EVIDENCE ]]; then', source)
        self.assertNotIn('rmdir "$CGROUP" 2>/dev/null || result=1', source)
        self.assertIn(
            'local phase="$1" observed="$2" original_exit="$3" '
            "severity=BLOCKED",
            source)
        self.assertIn(
            "(( original_exit == 0 || original_exit == 2 )) || severity=FAIL",
            source)
        self.assertIn(
            "ID36 isolated cgroup cleanup did not complete; phase:%s "
            "required:exclusive empty canonical membership and removable "
            "cgroup observed:%s original_exit:%s "
            "retained_cleanup:child-cgroup-and-private-session",
            source)
        self.assertNotIn("rm -rf /tmp", source)
        self.assertNotIn("drop_caches", source)


if __name__ == "__main__":
    unittest.main()
