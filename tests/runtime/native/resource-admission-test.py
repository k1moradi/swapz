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
        self.assertNotIn("PASS_ID36_RESOURCE_PRESSURE=", result.stdout)
        self.assertNotIn("PASS_ID36_RESOURCE_PRESSURE=", result.stderr)

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
        self.assert_blocked(
            self.run_shell(script, self.root / "absent-meminfo"),
            "MemAvailable unavailable")
        unreadable = self.root / "unreadable-meminfo"
        unreadable.mkdir()
        result = self.run_shell(script, unreadable)
        self.assert_blocked(result, "MemAvailable unavailable")
        self.assertIn("/proc/meminfo must be readable", result.stderr)

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

    def test_host_inventory_changes_and_noncanonical_fields_block(self):
        valid = meminfo(FLOOR_KIB)
        invalid_cases = (
            valid.replace("MemTotal:", "Unexpected:"),
            valid + "MemFree: 1 kB\n",
            valid.replace("Cached:         1048576 kB", "Cached:         1048576 MB"),
            valid.replace(f"MemAvailable:   {FLOOR_KIB}",
                          "MemAvailable:   True"),
            valid.replace(f"MemAvailable:   {FLOOR_KIB}",
                          "MemAvailable:   01048576"),
            valid.replace(f"MemAvailable:   {FLOOR_KIB}",
                          "MemAvailable:   18446744073709551616"),
        )
        for sample in invalid_cases:
            with self.subTest(sample=sample[-75:]):
                result = self.host_samples([sample])
                self.assert_blocked(result, "MemAvailable unavailable or malformed")
                self.assertIn(f"required:{FLOOR_KIB} kB", result.stderr)

        # A first sufficient observation is not permission to skip a second
        # readable snapshot. The synthetic source never touches host /proc.
        for second in (invalid_cases[0], invalid_cases[-1]):
            with self.subTest(second=second[-40:]):
                result = self.host_samples([valid, second])
                self.assert_blocked(result, "MemAvailable unavailable or malformed")
                self.assertNotIn("PASS_ID36_RESOURCE_PRESSURE=", result.stdout)

    def test_controller_admission_distinguishes_absence_from_unavailability(self):
        cgroup_root = self.root / "cgroup"
        cgroup_root.mkdir()
        controllers = cgroup_root / "cgroup.controllers"
        subtree = cgroup_root / "cgroup.subtree_control"
        source = QUALIFIER.read_text(encoding="utf-8")
        begin = source.index("[[ -f $CGROUP_ROOT/cgroup.controllers &&")
        end = source.index("\n[[ -r $PRESSURE_SCRIPT", begin)
        controller_gate = source[begin:end]
        script = (
            "CGROUP_ROOT=$1\n"
            + controller_gate
            + "\nprintf 'SYNTHETIC_CONTROLLER_GATE_ADMITTED\\n'\n"
        )

        controllers.write_text("cpu memory\n", encoding="ascii")
        subtree.write_text("cpu memory\n", encoding="ascii")
        admitted = self.run_shell(script, cgroup_root)
        self.assertEqual(admitted.returncode, 0, admitted.stderr)
        self.assertEqual(admitted.stdout, "SYNTHETIC_CONTROLLER_GATE_ADMITTED\n")

        refusal_cases = (
            (controllers, "cpu\n",
             "cgroup v2 memory controller unavailable"),
            (controllers, "memory\n",
             "cgroup v2 CPU controller unavailable"),
            (subtree, "cpu\n",
             "parent cgroup has no delegated memory controller"),
            (subtree, "memory\n",
             "parent cgroup has no delegated CPU controller"),
        )
        for telemetry_path, contents, expected in refusal_cases:
            with self.subTest(telemetry=telemetry_path.name, expected=expected):
                controllers.write_text("cpu memory\n", encoding="ascii")
                subtree.write_text("cpu memory\n", encoding="ascii")
                telemetry_path.write_text(contents, encoding="ascii")
                result = self.run_shell(script, cgroup_root)
                self.assert_blocked(result, expected)
                self.assertNotIn("SYNTHETIC_CONTROLLER_GATE_ADMITTED",
                                 result.stdout)

        controllers.unlink()
        missing = self.run_shell(script, cgroup_root)
        self.assert_blocked(
            missing,
            "requires a cgroup v2 hierarchy with controller delegation support")
        self.assertNotIn("telemetry unavailable", missing.stderr)
        controllers.write_text("cpu memory\n", encoding="ascii")

        # Keep the production file predicates true and inject only the read
        # failure, so unavailable telemetry is not confused with absence.
        for unavailable_name in ("cgroup.controllers", "cgroup.subtree_control"):
            with self.subTest(unavailable=unavailable_name):
                injected = (
                    "CGROUP_ROOT=$1\n"
                    "grep() {\n"
                    f'    if [[ ${{3:-}} == "$CGROUP_ROOT/{unavailable_name}" ]]; then\n'
                    "        return 2\n"
                    "    fi\n"
                    '    command grep "$@"\n'
                    "}\n"
                    + controller_gate
                )
                result = self.run_shell(injected, cgroup_root)
                expected = (
                    "cgroup.controllers telemetry unavailable"
                    if unavailable_name == "cgroup.controllers"
                    else "cgroup.subtree_control telemetry unavailable"
                )
                self.assert_blocked(result, expected)
                self.assertNotIn("SYNTHETIC_CONTROLLER_GATE_ADMITTED",
                                 result.stdout)

    def test_parent_mount_provenance_and_boolean_counters_are_not_authority(self):
        directory = self.root / "parent-cgroup"
        self.assertEqual(self.parent_inventory().returncode, 0)
        mountinfo = directory / "mountinfo"
        script = (
            "CGROUP_ROOT=$1\nCGROUP_MOUNTINFO=$1/mountinfo\n"
            f"MIN_AVAILABLE_BYTES={FLOOR_BYTES}\n"
            + shell_function(QUALIFIER, "cgroup_root_exemption_proven")
            + shell_function(QUALIFIER, "read_cgroup_root_memory_inventory")
            + parent_gate()
        )
        for mount_observation in (
                "",
                f"7 1 0:7 /other {directory} rw - cgroup2 cgroup rw\n",
                f"7 1 0:7 / {directory} rw - tmpfs tmpfs rw\n"):
            with self.subTest(mount_observation=mount_observation):
                mountinfo.write_text(mount_observation, encoding="ascii")
                refusal = self.run_shell(script, directory)
                self.assert_blocked(
                    refusal, "parent cgroup memory.max and memory.current absent")
                self.assertIn("observed:absent", refusal.stderr)
                self.assertIn("required:finite parent controls or true cgroup v2 root",
                              refusal.stderr)
        mountinfo.unlink()
        self.assert_blocked(
            self.run_shell(script, directory),
            "parent cgroup memory.max and memory.current absent")
        for maximum, current in (("True", 0), ("max", "False"),
                                 (FLOOR_BYTES, "01"), (FLOOR_BYTES, "-1")):
            with self.subTest(maximum=maximum, current=current):
                result = self.parent_inventory(maximum, current)
                self.assert_blocked(result, "parent cgroup memory.max/current invalid")
                self.assertIn("canonical u64", result.stderr)

    def test_memory_events_inventory_rejects_each_missing_or_false_counter(self):
        directory = self.root / "events"
        directory.mkdir()
        events_file = directory / "memory.events"
        script = ('CGROUP=$1\n'
                  + shell_function(QUALIFIER, "read_memory_event_inventory")
                  + 'read_memory_event_inventory\n')
        canonical = "high 0\noom 0\noom_kill 0\n"
        events_file.write_text(canonical + "low 4\n", encoding="ascii")
        admitted = self.run_shell(script, directory)
        self.assertEqual(admitted.returncode, 0, admitted.stderr)
        self.assertEqual(admitted.stdout, "0 0 0\n")
        for counter in ("high", "oom", "oom_kill"):
            with self.subTest(counter=counter):
                missing = canonical.replace(f"{counter} 0\n", "")
                events_file.write_text(missing, encoding="ascii")
                result = self.run_shell(script, directory)
                self.assert_blocked(
                    result, f"memory.events counter {counter} missing")
                self.assertIn("observed:missing", result.stderr)
                for invalid_value in ("True", "01", "-1",
                                      "18446744073709551616"):
                    events_file.write_text(canonical.replace(
                        f"{counter} 0\n", f"{counter} {invalid_value}\n"),
                        encoding="ascii")
                    result = self.run_shell(script, directory)
                    self.assert_blocked(
                        result, f"memory.events counter {counter} malformed")
                    self.assertIn("expected:one canonical nonnegative counter",
                                  result.stderr)
        events_file.unlink()
        result = self.run_shell(script, directory)
        self.assert_blocked(result, "memory.events telemetry unreadable")
        self.assertIn("expected:readable cgroup v2 high/oom/oom_kill",
                      result.stderr)

    def test_cpu_psi_rejects_absent_and_changed_uncertain_observations(self):
        directory = self.root / "psi"
        directory.mkdir()
        psi_file = directory / "cpu.pressure"
        script = ('CGROUP=$1\n'
                  + shell_function(QUALIFIER, "cpu_some_total")
                  + 'cpu_some_total\n')
        valid = "some avg10=0.00 avg60=0.00 avg300=0.00 total=42\n"
        psi_file.write_text(valid, encoding="ascii")
        self.assertEqual(self.run_shell(script, directory).stdout, "42\n")
        for invalid, expected in (
                ("full avg10=0 avg60=0 avg300=0 total=42\n",
                 "some telemetry missing"),
                (valid + valid, "some telemetry malformed"),
                (valid.replace("total=42", "total=True"),
                 "some telemetry malformed"),
                (valid.replace("total=42", "total=18446744073709551616"),
                 "some telemetry malformed"),
                (valid.replace("avg60=0.00", "avg60=True"),
                 "some telemetry malformed"),
                (valid.replace("avg300=0.00", "avg300=100.01"),
                 "some avg300 outside percentage range")):
            with self.subTest(observation=invalid[-65:]):
                psi_file.write_text(invalid, encoding="ascii")
                result = self.run_shell(script, directory)
                self.assert_blocked(result, f"cpu.pressure {expected}")
                self.assertIn("observed:", result.stderr)
        psi_file.unlink()
        missing = self.run_shell(script, directory)
        self.assert_blocked(missing, "cpu.pressure some telemetry unreadable")
        self.assertIn("observed:unavailable", missing.stderr)

    def test_changed_pressure_observations_use_production_parser_and_first_failure(self):
        source = QUALIFIER.read_text(encoding="utf-8")
        parser = shell_function(QUALIFIER, "read_memory_event_inventory")
        counter_guard = shell_function(QUALIFIER, "require_monotonic_counter")
        cgroup = self.root / "pressure-gates"
        cgroup.mkdir()
        events = cgroup / "memory.events"

        gate_cases = (
            (
                'memory_events_ready="$(read_memory_event_inventory)" || exit 2',
                "# Base memory.high",
                "oom_start=2\noom_kill_start=3\n",
                (
                    ("high 0\noom 2\noom_kill 3\n", 0, ""),
                    ("high 0\noom 3\noom_kill 3\n", 1,
                     "pressure startup encountered OOM events"),
                    ("high 0\noom 2\noom_kill 4\n", 1,
                     "pressure startup encountered OOM events"),
                    ("high 0\noom 1\noom_kill 3\n", 2,
                     "memory.events oom counter regressed"),
                ),
            ),
            (
                'memory_events_before="$(read_memory_event_inventory)" || exit 2',
                "printf 'START_ID36_RESOURCE_PRESSURE=",
                "oom_ready=2\noom_kill_ready=3\n",
                (
                    ("high 5\noom 2\noom_kill 3\n", 0, ""),
                    ("high 5\noom 3\noom_kill 3\n", 1,
                     "pressure-boundary setup encountered OOM events"),
                    ("high 5\noom 2\noom_kill 4\n", 1,
                     "pressure-boundary setup encountered OOM events"),
                    ("high 5\noom 1\noom_kill 3\n", 2,
                     "memory.events oom counter regressed"),
                ),
            ),
            (
                'memory_events_active="$(read_memory_event_inventory)" || exit 2',
                "# CPU PSI qualification",
                "high_before=5\noom_before=2\noom_kill_before=3\n",
                (
                    ("high 6\noom 2\noom_kill 3\n", 0, ""),
                    ("high 5\noom 2\noom_kill 3\n", 1,
                     "controlled pressure ramp did not trigger memory.high"),
                    ("high 6\noom 3\noom_kill 3\n", 1,
                     "staged pressure encountered OOM events"),
                    ("high 4\noom 2\noom_kill 3\n", 2,
                     "memory.events high counter regressed"),
                ),
            ),
        )
        for begin_marker, end_marker, baseline, observations in gate_cases:
            start = source.index(begin_marker)
            end = source.index(end_marker, start)
            gate = source[start:end]
            for observation, exit_status, reason in observations:
                with self.subTest(gate=begin_marker, observation=observation):
                    events.write_text(observation, encoding="ascii")
                    script = (
                        "CGROUP=$1\n"
                        + parser
                        + counter_guard
                        + baseline
                        + gate
                        + "\nprintf 'SYNTHETIC_PRESSURE_GATE_ADMITTED\\n'\n"
                    )
                    result = self.run_shell(script, cgroup)
                    self.assertEqual(result.returncode, exit_status,
                                     (result.stdout, result.stderr))
                    if exit_status:
                        self.assertIn(reason, result.stderr)
                        self.assertNotIn("SYNTHETIC_PRESSURE_GATE_ADMITTED",
                                         result.stdout)
                        self.assertNotIn("PASS_ID36_RESOURCE_PRESSURE=",
                                         result.stdout + result.stderr)
                    else:
                        self.assertEqual(
                            result.stdout, "SYNTHETIC_PRESSURE_GATE_ADMITTED\n")
                        self.assertEqual(result.stderr, "")

    def test_ready_memory_pressure_thresholds_are_exact_and_bounded(self):
        source = QUALIFIER.read_text(encoding="utf-8")
        cgroup = self.root / "pressure-thresholds"
        cgroup.mkdir()
        current_path = cgroup / "memory.current"

        ready_begin = source.index(
            'pressure_current="$(cat "$CGROUP/memory.current" 2>/dev/null)"')
        ready_end = source.index(
            'memory_events_ready="$(read_memory_event_inventory)"', ready_begin)
        ready_gate = source[ready_begin:ready_end]
        ready_constants = (
            "PRESSURE_MIB=576\n"
            "PRESSURE_RAMP_MIB=80\n"
            "READY_PRESSURE_MIB=$((PRESSURE_MIB - PRESSURE_RAMP_MIB))\n"
        )
        required_ready = (576 - 80) * 1024 * 1024
        for observed, exit_status, reason in (
                (required_ready, 0, ""),
                (required_ready - 1, 1,
                 "ready-stage resident pressure too small"),
                ("True", 2, "ready-stage memory.current malformed"),
                ("01", 2, "ready-stage memory.current malformed"),
                ("9999999999999999999", 2,
                 "ready-stage memory.current malformed")):
            with self.subTest(observed=observed):
                current_path.write_text(f"{observed}\n", encoding="ascii")
                script = (
                    "CGROUP=$1\n"
                    + ready_constants
                    + ready_gate
                    + "\nprintf 'SYNTHETIC_READY_THRESHOLD_ADMITTED\\n'\n"
                )
                result = self.run_shell(script, cgroup)
                self.assertEqual(result.returncode, exit_status,
                                 (result.stdout, result.stderr))
                if exit_status:
                    self.assertIn(reason, result.stderr)
                    self.assertNotIn("SYNTHETIC_READY_THRESHOLD_ADMITTED",
                                     result.stdout)
                    if observed == required_ready - 1:
                        self.assertIn(f"observed:{observed}", result.stderr)
                        self.assertIn(f"required:{required_ready}", result.stderr)
                else:
                    self.assertEqual(
                        result.stdout, "SYNTHETIC_READY_THRESHOLD_ADMITTED\n")
                    self.assertEqual(result.stderr, "")

        current_path.unlink()
        current_path.mkdir()
        unreadable = self.run_shell(
            "CGROUP=$1\n" + ready_constants + ready_gate, cgroup)
        self.assert_blocked(unreadable, "ready-stage memory.current unreadable")

        boundary_begin = source.index(
            "MEMORY_HIGH_BYTES=$((pressure_current + MEMORY_HEADROOM_BYTES))")
        boundary_end = source.index(
            "\n# Establish high-pressure evidence deliberately", boundary_begin)
        boundary_gate = source[boundary_begin:boundary_end]
        memory_max = 896 * 1024 * 1024
        ramp = 80 * 1024 * 1024
        headroom = 64 * 1024 * 1024
        boundary_constants = (
            f"MEMORY_MAX_BYTES={memory_max}\n"
            f"PRESSURE_RAMP_BYTES={ramp}\n"
            f"MEMORY_HEADROOM_BYTES={headroom}\n"
            "write_cgroup_control() { :; }\n"
        )
        for observed, exit_status, reason in (
                (memory_max - ramp - 1, 0, ""),
                (memory_max - ramp, 2,
                 "staged pressure would exceed memory.max safety bound"),
                (memory_max - headroom, 2,
                 "ready-state charge cannot fit the memory.high boundary")):
            with self.subTest(boundary_observed=observed):
                script = (
                    boundary_constants
                    + f"pressure_current={observed}\n"
                    + boundary_gate
                    + "\nprintf 'SYNTHETIC_BOUNDARY_ADMITTED\\n'\n"
                )
                result = self.run_shell(script)
                self.assertEqual(result.returncode, exit_status,
                                 (result.stdout, result.stderr))
                if exit_status:
                    self.assertIn(reason, result.stderr)
                    self.assertIn(f"observed:{observed}", result.stderr)
                    self.assertIn(f"memory.max:{memory_max}", result.stderr)
                    self.assertNotIn("SYNTHETIC_BOUNDARY_ADMITTED",
                                     result.stdout)
                    if observed == memory_max - headroom:
                        self.assertNotIn("staged pressure would exceed",
                                         result.stderr)
                else:
                    self.assertEqual(
                        result.stdout, "SYNTHETIC_BOUNDARY_ADMITTED\n")
                    self.assertEqual(result.stderr, "")

    def test_admission_stream_identifies_cleanup_attempt_state_by_gate_order(self):
        source = QUALIFIER.read_text(encoding="utf-8")
        start = source.index("START_ID36_RESOURCE_PRESSURE=admission")
        controller = source.index(
            'require_cgroup_word "$CGROUP_ROOT/cgroup.controllers"')
        cleanup_call = source.index("swapz_clear_tmp_before_memory_check ||")
        cleanup_complete = source.index(
            "ID36_TMP_CLEANUP=completed-owned-only")
        host_gate = source.index("sample_host_memory_admission || exit 2")
        parent_gate_start = source.index(
            'if ! parent_memory_inventory="$(read_cgroup_root_memory_inventory)"; then')
        pressure_ready = source.index(
            'pressure_current="$(cat "$CGROUP/memory.current" 2>/dev/null)"')
        self.assertLess(start, controller)
        self.assertLess(controller, cleanup_call)
        self.assertLess(cleanup_call, cleanup_complete)
        self.assertLess(cleanup_complete, host_gate)
        self.assertLess(host_gate, parent_gate_start)
        self.assertLess(parent_gate_start, pressure_ready)
        self.assertEqual(
            source.count("ID36_TMP_CLEANUP=completed-owned-only"), 1)
        self.assertIn(
            "completed-owned /tmp cleanup refused; verify session completion "
            "proofs, ownership, mounts and helper availability "
            "(no broad cleanup attempted)",
            source)

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

    def test_nested_pair_barrier_resumes_only_the_captured_stopped_child(self):
        functions = "".join(
            shell_function(QUALIFIER, name)
            for name in (
                "direct_owned_child_running",
                "capture_direct_child_identity",
                "nested_pair_identity_action",
                "nested_pair_identity_status_category",
                "capture_nested_child_identity",
                "wait_nested_child_stopped",
                "signal_nested_owned_child",
            )
        )
        script = functions + r'''
tmp=$1
ready=$tmp/ready
go=$tmp/go
timeout --signal=TERM --kill-after=1s 10s bash -c '
    printf "pid=%s\n" "$$" > "$1"
    kill -STOP "$$"
    [[ -f $2 ]]
' _ "$ready" "$go" &
parent=$!
parent_start="$(capture_direct_child_identity "$parent")" || exit 20
for _ in {1..100}; do
    [[ -s $ready ]] && break
    direct_owned_child_running "$parent" || exit 21
    sleep 0.01
done
child="$(awk -F= '$1 == "pid" && NF == 2 { print $2 }' "$ready")"
child_start="$(capture_nested_child_identity "$child" "$parent" "$parent_start")" || exit 22
wait_nested_child_stopped "$child" "$parent" "$parent_start" "$child_start" || exit 23
# Keep the negative control syntactically valid so it reaches the identity
# comparison rather than the earlier malformed-start-time refusal (status 2).
wrong_child_start="$((child_start + 1))"
if signal_nested_owned_child "$child" "$parent" "$parent_start" "$wrong_child_start" 18; then
    printf '%s\n' 'wrong child start time was accepted' >&2
    exit 24
else
    status=$?
    if [[ $status != 8 ]]; then
        category="$(nested_pair_identity_status_category "$status")"
        printf 'wrong child start status mismatch: expected=8(readiness-child-start-changed) observed=%s(%s)\n' \
            "$status" "$category" >&2
        exit 25
    fi
fi
wait_nested_child_stopped "$child" "$parent" "$parent_start" "$child_start" || exit 26
: > "$go"
signal_nested_owned_child "$child" "$parent" "$parent_start" "$child_start" 18 || exit 27
wait "$parent"
'''
        result = self.run_shell(script, self.root)
        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
        self.assertEqual(result.stderr, "")

    def test_nested_pair_ppid_mismatch_refuses_resume(self):
        functions = "".join(
            shell_function(QUALIFIER, name)
            for name in (
                "direct_owned_child_running",
                "capture_direct_child_identity",
                "nested_pair_identity_action",
                "nested_pair_identity_status_category",
                "capture_nested_child_identity",
                "wait_nested_child_stopped",
                "signal_nested_owned_child",
            )
        )
        ppid_mismatch_action = shell_function(
            QUALIFIER, "nested_pair_identity_action").replace(
                "nested_pair_identity_action() {",
                "nested_pair_identity_action_ppid_mismatch() {", 1)
        child_stat_read = (
            "                state, observed_parent, observed_child_start = "
            "read_stat(child_pid)\n")
        self.assertEqual(ppid_mismatch_action.count(child_stat_read), 1)
        ppid_mismatch_action = ppid_mismatch_action.replace(
            child_stat_read,
            child_stat_read + "                observed_parent = parent_pid + 1\n",
            1)
        script = functions + ppid_mismatch_action + r'''
tmp=$1
ready=$tmp/reparent.ready
go=$tmp/reparent.go
timeout --signal=TERM --kill-after=1s 10s bash -c '
    printf "pid=%s\n" "$$" > "$1"
    kill -STOP "$$"
    [[ -f $2 ]]
' _ "$ready" "$go" &
parent=$!
parent_start="$(capture_direct_child_identity "$parent")" || exit 31
for _ in {1..100}; do
    [[ -s $ready ]] && break
    direct_owned_child_running "$parent" || exit 32
    sleep 0.01
done
child="$(awk -F= '$1 == "pid" && NF == 2 { print $2 }' "$ready")"
child_start="$(capture_nested_child_identity "$child" "$parent" "$parent_start")" || exit 33
wait_nested_child_stopped "$child" "$parent" "$parent_start" "$child_start" || exit 34
if nested_pair_identity_action_ppid_mismatch signal "$child" "$parent" \
        "$parent_start" "$child_start" 18; then
    printf '%s\n' 'changed child parent was accepted for resume' >&2
    exit 35
else
    status=$?
    if [[ $status != 7 ]]; then
        category="$(nested_pair_identity_status_category "$status")"
        printf 'changed child parent status mismatch: expected=7(readiness-child-reparented) observed=%s(%s)\n' \
            "$status" "$category" >&2
        exit 36
    fi
fi
# A refused PPID mismatch must leave the exact child stopped.
wait_nested_child_stopped "$child" "$parent" "$parent_start" "$child_start" || exit 37
: > "$go"
signal_nested_owned_child "$child" "$parent" "$parent_start" "$child_start" 18 || exit 38
wait "$parent"
'''
        result = self.run_shell(script, self.root)
        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
        self.assertEqual(result.stderr, "")

    def test_nested_pair_identity_reports_unexpected_child_exit(self):
        functions = "".join(
            shell_function(QUALIFIER, name)
            for name in (
                "direct_owned_child_running",
                "capture_direct_child_identity",
                "nested_pair_identity_action",
                "nested_pair_identity_status_category",
                "capture_nested_child_identity",
                "signal_nested_owned_child",
            )
        )
        script = functions + r'''
tmp=$1
ready=$tmp/exited.ready
go=$tmp/exited.go
exited=$tmp/exited.marker
release=$tmp/exited.release
python3 -I -B - "$ready" "$go" "$exited" "$release" <<'PY' >/dev/null 2>&1 &
from pathlib import Path
import signal
import subprocess
import sys
import time

ready, go, exited, release = map(Path, sys.argv[1:])

def child_exited(_signal_number, _frame):
    exited.touch()

signal.signal(signal.SIGCHLD, child_exited)
child_source = """
from pathlib import Path
import sys
import time

go = Path(sys.argv[1])
while not go.exists():
    time.sleep(0.005)
raise SystemExit(23)
"""
child = subprocess.Popen(
    [sys.executable, "-I", "-c", child_source, str(go)],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
pending_ready = ready.with_name(ready.name + ".pending")
pending_ready.write_text(f"pid={child.pid}\n", encoding="ascii")
pending_ready.replace(ready)
deadline = time.monotonic() + 7.0
while not release.exists() and time.monotonic() < deadline:
    time.sleep(0.005)
if not release.exists():
    try:
        child.terminate()
    except ProcessLookupError:
        pass
    child.wait()
    raise SystemExit(41)
child.wait()
PY
parent=$!
if ! parent_start="$(capture_direct_child_identity "$parent")"; then
    printf '%s\n' 'fixture precondition failed: exited-child parent identity unavailable' >&2
    exit 40
fi
for _ in {1..200}; do
    [[ -s $ready ]] && break
    direct_owned_child_running "$parent" || exit 41
    sleep 0.005
done
child="$(awk -F= '$1 == "pid" && NF == 2 { print $2 }' "$ready")"
child_start="$(capture_nested_child_identity "$child" "$parent" "$parent_start")" || exit 42
: > "$go"
for _ in {1..200}; do
    [[ -e $exited ]] && break
    direct_owned_child_running "$parent" || exit 43
    sleep 0.005
done
[[ -e $exited ]] || exit 44
if signal_nested_owned_child "$child" "$parent" "$parent_start" "$child_start" 18; then
    printf '%s\n' 'exited readiness child was accepted for resume' >&2
    exit 45
else
    status=$?
    if [[ $status != 3 ]]; then
        category="$(nested_pair_identity_status_category "$status")"
        printf 'exited child status mismatch: expected=3(readiness-child-gone) observed=%s(%s)\n' \
            "$status" "$category" >&2
        exit 46
    fi
fi
direct_owned_child_running "$parent" || exit 47
: > "$release"
wait "$parent"
'''
        result = self.run_shell(script, self.root)
        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
        self.assertEqual(result.stderr, "")

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

    def test_loaded_preflight_runtime_identity_first_failure_is_specific(self):
        # Source-extracted only: fake id/uname never run full privileged preflight.
        source = PREFLIGHT.read_text(encoding="utf-8")
        helper = (shell_function(PREFLIGHT, "refuse")
                  + shell_function(PREFLIGHT, "is_uint")
                  + shell_function(PREFLIGHT, "is_kernel_release")
                  + shell_function(PREFLIGHT, "check_loaded_runtime_identity"))
        accepted_id = "id() { printf '0\n'; }\n"
        accepted_release = "uname() { printf '6.8.0-test+arm64\n'; }\n"
        probes = (
            ("id command failed", "id() { return 7; }\n"
             "uname() { return 9; }\n",
             "LOADED_PREFLIGHT=BLOCKED check=effective_uid",
             "original_errno_or_exit=7"),
            ("id output malformed", "id() { printf 'root\n'; }\n"
             + accepted_release,
             "LOADED_PREFLIGHT=BLOCKED check=effective_uid",
             "id -u returned a malformed effective UID"),
            ("nonroot", "id() { printf '1000\n'; }\n" + accepted_release,
             "LOADED_PREFLIGHT=NOT_AUTHORIZED check=effective_uid",
             "provide noninteractive root authorization"),
            ("uname command failed", accepted_id + "uname() { return 9; }\n",
             "LOADED_PREFLIGHT=BLOCKED check=running_kernel_release",
             "original_errno_or_exit=9"),
            ("uname output malformed", accepted_id
             + "uname() { printf '../other-kernel\n'; }\n",
             "LOADED_PREFLIGHT=BLOCKED check=running_kernel_release",
             "uname -r returned a malformed kernel release"),
        )
        for label, commands, check, reason in probes:
            with self.subTest(label=label):
                result = self.run_shell(
                    helper + commands + "check_loaded_runtime_identity\n"
                    + "printf 'UNEXPECTED_LOADED_ADMISSION\n'")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(check, result.stderr)
                self.assertIn(reason, result.stderr)
                self.assertEqual(result.stderr.count("LOADED_PREFLIGHT="), 1)
                self.assertNotIn("FAIL: loaded preflight internal", result.stderr)
                self.assertNotIn("unclaimed_null_blk", result.stderr)
                self.assertNotIn("host_identity", result.stderr)
                self.assertEqual(result.stdout, "")

        accepted = self.run_shell(
            helper + accepted_id + accepted_release
            + "check_loaded_runtime_identity\n"
            + "printf 'ADMITTED:%s\n' \"$running_kernel_release\"")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(accepted.stdout, "ADMITTED:6.8.0-test+arm64\n")
        self.assertEqual(accepted.stderr, "")

        release_validator = shell_function(PREFLIGHT, "is_kernel_release")
        for release, expected_status in (
                ("6.8.0-101-generic", 0),
                ("6.6.51+rpt-rpi-v8", 0),
                ("../other-kernel", 1),
                (".hidden", 1),
                ("-leading", 1),
                ("abc/def", 1),
                ("abc def", 1),
                ("é", 1),
                ("a" * 129, 1)):
            with self.subTest(release=release):
                result = self.run_shell(
                    release_validator + 'is_kernel_release "$1"\n', release)
                self.assertEqual(result.returncode, expected_status,
                                 result.stderr)

        self.assertNotIn("=~", source)
        self.assertIn("local value=\"$1\" LC_ALL=C", source)
        self.assertLess(
            source.index("\ncheck_loaded_runtime_identity\n"),
            source.index("capability_status="))
        self.assertIn('"/boot/config-$running_kernel_release"', source)
        self.assertIn('"/lib/modules/$running_kernel_release/build/.config"',
                      source)

    def test_loaded_preflight_module_probe_preserves_first_dry_run_exit(self):
        # Only a fake modprobe and disposable configfs path are consulted.
        source = PREFLIGHT.read_text(encoding="utf-8")
        helper = (shell_function(PREFLIGHT, "refuse")
                  + shell_function(PREFLIGHT,
                                   "check_null_blk_module_available"))
        absent_directory = self.root / "missing-configfs"
        existing_directory = self.root / "built-in-configfs"
        existing_directory.mkdir()

        for directory, fake_probe, expected_code, expected_reason in (
                (absent_directory, "modprobe() { return 9; }\n", 1,
                 "original_errno_or_exit=9"),
                (absent_directory, "modprobe() { return 0; }\n", 0, ""),
                (existing_directory,
                 "modprobe() { printf 'UNEXPECTED_MODULE_PROBE\n'; return 9; }\n",
                 0, "")):
            with self.subTest(directory=directory, fake_probe=fake_probe):
                result = self.run_shell(
                    helper + fake_probe
                    + 'check_null_blk_module_available "$1"\n', directory)
                self.assertEqual(result.returncode, expected_code,
                                 result.stderr)
                self.assertIn(expected_reason, result.stderr)
                self.assertNotIn("UNEXPECTED_MODULE_PROBE", result.stdout)
                self.assertEqual(
                    result.stderr.count("LOADED_PREFLIGHT="),
                    1 if expected_code else 0)
                if expected_code:
                    self.assertIn("check=null_blk_module", result.stderr)
                else:
                    self.assertEqual(result.stderr, "")
        self.assertLess(
            source.index("\ncheck_null_blk_module_available /sys/kernel/config/nullb"),
            source.index("package_journal=/var/lib/swapz-package-transactions"))

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
        wrapper = (shell_function(CLEANUP_WRAPPER, "swapz_recover_abandoned_ram_resources")
                   + shell_function(CLEANUP_WRAPPER, "swapz_clear_tmp_before_memory_check"))
        script = wrapper + '''
id() { printf '0\n'; }
timeout() { return 7; }
swapz_clear_tmp_before_memory_check
'''
        result = self.run_shell(script)
        self.assertEqual(result.returncode, 1)
        self.assertIn("BLOCKED: abandoned RAM resource recovery remains unverified", result.stderr)
        self.assertNotIn(str(self.root), result.stderr)
        # Resource recovery can succeed while the separate scratch cleaner
        # refuses. Both errors remain visible without running either helper.
        script = wrapper + '''
id() { printf '0\\n'; }
timeout() {
    case "$*" in
        *owned-ram-resources.py*) return 0 ;;
        *) return 7 ;;
    esac
}
swapz_clear_tmp_before_memory_check
'''
        result = self.run_shell(script)
        self.assertEqual(result.returncode, 1)
        self.assertIn("BLOCKED: cannot safely remove verified completed", result.stderr)
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
