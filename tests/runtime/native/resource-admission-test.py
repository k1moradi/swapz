#!/usr/bin/env python3
"""Rootless, isolated resource-admission regressions; no real cgroup or /tmp mutation."""

from pathlib import Path
import re
import subprocess
import tempfile
import unittest

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
        script = (
            "CGROUP_ROOT=$1\n"
            f"MIN_AVAILABLE_BYTES={FLOOR_BYTES}\n"
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
        (directory / "memory.events").write_text("oom 0\noom_kill 0\nhigh 0\n")
        (directory / "cpu.pressure").write_text(
            "some avg10=0.00 avg60=0.00 avg300=0.00 total=0\n")
        functions = (shell_function(QUALIFIER, "event_value") +
                     shell_function(QUALIFIER, "cpu_some_total"))
        script = 'CGROUP=$1\n' + functions
        self.assertEqual(self.run_shell(script + 'event_value oom\ncpu_some_total\n',
                                        directory).returncode, 0)
        (directory / "memory.events").write_text("oom 0\noom 1\n")
        result = self.run_shell(script + 'event_value oom\n', directory)
        self.assert_blocked(result, "memory.events counter oom")
        (directory / "cpu.pressure").write_text("some avg10=0.00 total=oops\n")
        result = self.run_shell(script + 'cpu_some_total\n', directory)
        self.assert_blocked(result, "cpu.pressure some total")

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
        self.assertLess(
            source.index("for required_command in"),
            source.index('grep -qw memory "$CGROUP_ROOT/cgroup.controllers"'))
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
        self.assertIn(
            'if ! source "$cleanup_helper"; then',
            qualifier)
        self.assertIn(
            'source "$cleanup_helper" ||',
            preflight)
        self.assertIn(
            "owned temporary-cleanup helper unavailable",
            preflight)

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
        self.assertIn("swapz_clear_tmp_before_memory_check ||", PREFLIGHT.read_text())
        self.assertIn("swapz_clear_tmp_before_memory_check ||", QUALIFIER.read_text())

    def test_no_fixture_bypasses_privileged_admission_entrypoint(self):
        source = QUALIFIER.read_text(encoding="utf-8")
        self.assertIn("CGROUP_ROOT=/sys/fs/cgroup", source)
        self.assertIn("MIN_AVAILABLE_KIB=$((1024 * 1024))", source)
        self.assertIn("sample_host_memory_admission || exit 2", source)
        self.assertIn("headroom:%s required:%s deficit:%s unit:bytes", source)
        self.assertIn(
            'write_cgroup_control memory.max "$MEMORY_MAX_BYTES" || exit 2',
            source)
        self.assertIn(
            'write_cgroup_control memory.high "$MEMORY_HIGH_BYTES" || exit 2',
            source)
        self.assertIn('rm -rf -- "$SESSION" 2>/dev/null', source)
        self.assertNotIn('rmdir "$CGROUP" 2>/dev/null || result=1', source)
        self.assertIn(
            "BLOCKED: ID36 isolated cgroup cleanup did not complete;",
            source)
        self.assertNotIn("rm -rf /tmp", source)
        self.assertNotIn("drop_caches", source)


if __name__ == "__main__":
    unittest.main()
