#!/usr/bin/env python3
"""Rootless negative controls for the private kernel-debug qualification lane."""
from __future__ import annotations

import contextlib
import gzip
import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[2] / "tools/kernel-debug-qualify.py"
WRAPPER = Path(__file__).resolve().parents[2] / "tools/qualify-kernel-debug-owned.sh"
DEPLOY_HELPER = Path(__file__).resolve().parents[2] / "tools/deploy-nullblk.sh"
SPEC = importlib.util.spec_from_file_location("swapz_kernel_debug_qualification", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
qualification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualification)

CONFIG = """
CONFIG_KASAN=y
CONFIG_KCSAN=y
CONFIG_PROVE_LOCKING=y
CONFIG_LOCKDEP=y
CONFIG_DEBUG_LOCK_ALLOC=y
"""
SOURCE_SHA = "a" * 40
GOOD_LOG = f"""
SOURCE_HEAD={SOURCE_SHA}
PASS_LOADED_CONSTRUCTOR_FAILURE_CLEANUP=stages:8 lower_io_delta:0
PASS_LOADED_COMPOUND_BIO=written_pages:384 verified_pages:384 segs_gt1:2 segs_max:3 nonzero_off:1 compound_pages:128 copy_fallbacks:1 failed:0
PASS_LOADED_LIVE_GC=victims:2 rotations:2 pages:64 read_bytes:262144 write_bytes:131072 read_reqs:64 write_reqs:32 distinct:3 victim_min:1 victim_max:2 last:1->2 discards:2 discard_sectors:4096 discard_unsupported:0 discard_failed:0 verified_pages:4096
PASS_LOADED_DISCARD_TRIM=pages:256 immediate_discards:1 immediate_sectors:2048 reuse_skips:1 verified_pages:4096
PASS_LOADED_SUSPEND_DRAIN=retain_ms:64 observed_open:1 verified_pages:128
PASS_RETAINED_SYNTHETIC_WRITE_FAULT=retain_ms:2 injected:1 syscall_errno:EIO lower_write_delta:0
PASS_LOADED_SYNTHETIC_READ_FAULT=page:2048 injected:1 syscall_errno:EIO lower_read_delta:0 submitted_delta:0
PASS_RETAINED_SYNTHETIC_FLUSH_FAULT=retain_ms:2 injected:1 data_write_reached_lower:1
PASS_LOADED_CODEC_ERROR_PATHS=owners:3 injected:3 inline_lower_write_delta:0 submitter_lower_write_delta:0 background_error_completions:1
PASS_LOADED_COMPLETION_HANDOFF=offloaded:2 verified_pages:128 completed_writes:16512 active_after:0 fault_offloaded:1 fault_injected:1 post_failure_eio:1
PASS: loaded isolated swapz byte-exact I/O, clean teardown
""".strip()


class KernelDebugQualificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        directory = Path(self.temporary_directory.name)
        self.configuration = directory / "config"
        self.cmdline = directory / "cmdline"
        self.configuration.write_text(CONFIG, encoding="utf-8")
        self.cmdline.write_text("quiet splash\n", encoding="utf-8")

    def features(self) -> dict[str, str]:
        return qualification.probe(self.configuration, self.cmdline)

    @staticmethod
    def runtime_snapshot(
            required: tuple[str, ...], *,
            kcsan_enabled: bool = True,
            kcsan_filter_default: bool = True,
            lockdep_debug_locks: bool = True,
            lockdep_prove_locking: bool = True) -> str:
        snapshot: dict[str, object] = {
            "schema": qualification.RUNTIME_SCHEMA,
            "required": list(required),
            "boot_id": qualification.DEFAULT_BOOT_ID.read_text(
                encoding="utf-8").strip(),
            "observed_monotonic_ns": time.monotonic_ns(),
        }
        if "kcsan" in required:
            snapshot["kcsan_enabled"] = kcsan_enabled
            snapshot["kcsan_filter_default"] = kcsan_filter_default
        if "lockdep" in required:
            snapshot["lockdep_debug_locks"] = lockdep_debug_locks
            snapshot["lockdep_prove_locking"] = lockdep_prove_locking
        return json.dumps(snapshot)

    def verify(self, execution: str = GOOD_LOG, final: str = "old\nnew\n",
               required: tuple[str, ...] = ("kasan", "lockdep"),
               baseline: str = "old\n", runtime_before: str | None = None,
               runtime_after: str | None = None,
               module_evidence: dict[str, str] | None = None) -> tuple[str, str]:
        if runtime_before is None and runtime_after is not None:
            # Callers construct an explicit after-snapshot before entering this
            # helper. Give the synthetic before-snapshot an earlier timestamp
            # so order validation tests the intended state, not Python argument
            # evaluation timing.
            after_state = json.loads(runtime_after)
            before_state = json.loads(self.runtime_snapshot(required))
            after_time = after_state.get("observed_monotonic_ns")
            if type(after_time) is int and after_time > 1:
                before_state["observed_monotonic_ns"] = after_time - 1
            runtime_before = json.dumps(before_state)
        elif runtime_before is None:
            runtime_before = self.runtime_snapshot(required)
        if runtime_after is None:
            runtime_after = self.runtime_snapshot(required)
        if module_evidence is None:
            # Synthetic evidence exercises only the pure verifier. The CLI
            # inspects real module metadata and never accepts this shortcut.
            module_evidence = {
                "source_sha": SOURCE_SHA, "source_clean": "1",
                "symbols": "__asan_load8 __tsan_read8",
            }
        return qualification.verify_owned_run(
            required, self.features(), baseline, final, execution,
            runtime_before, runtime_after, SOURCE_SHA,
            module_evidence=module_evidence,
            configuration=qualification.load_config(self.configuration),
        )

    def test_detected_is_not_executed(self) -> None:
        self.assertEqual(self.features()["kasan"], "DETECTED")
        self.assertEqual(self.features()["lockdep"], "DETECTED")
        self.assertTrue(qualification.check_features(self.features(), ("kasan", "lockdep")))
        self.assertFalse(qualification.check_features({"kasan": "UNKNOWN"}, ("kasan",)))

    def test_missing_config_and_disabled_boot_are_not_available(self) -> None:
        self.assertEqual(qualification.probe(None, self.cmdline)["kasan"], "UNKNOWN")
        self.configuration.write_text(CONFIG.replace("CONFIG_LOCKDEP=y", "# CONFIG_LOCKDEP is not set"))
        self.assertEqual(self.features()["lockdep"], "UNAVAILABLE")
        self.configuration.write_text(CONFIG)
        self.cmdline.write_text("kasan=off kcsan.enabled=0 lockdep=off\n")
        features = self.features()
        self.assertEqual(features["kasan"], "DISABLED_AT_BOOT")
        self.assertEqual(features["kcsan"], "DETECTED")
        self.assertEqual(features["lockdep"], "DETECTED")

    def test_gzipped_config_and_unreadable_cmdline(self) -> None:
        compressed = self.configuration.with_suffix(".gz")
        with gzip.open(compressed, "wt", encoding="utf-8") as stream:
            stream.write(CONFIG)
        self.assertEqual(qualification.probe(compressed, self.cmdline)["kcsan"], "DETECTED")
        unreadable_cmdline = qualification.probe(
            compressed, self.cmdline.parent / "not-present")
        self.assertEqual(unreadable_cmdline["kasan"], "UNKNOWN")
        self.assertEqual(unreadable_cmdline["kcsan"], "DETECTED")
        self.assertEqual(unreadable_cmdline["lockdep"], "DETECTED")

    def test_separate_kcsan_lane(self) -> None:
        self.assertEqual(qualification.required_features("kcsan"), ("kcsan",))
        for invalid in ("kasan,kcsan", "lockdep,kcsan", "kasan,kasan", "unknown"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                qualification.required_features(invalid)

    def test_valid_owned_evidence(self) -> None:
        self.assertEqual(self.verify()[0], "PASS")
        self.assertEqual(self.verify(required=("kcsan",))[0], "PASS")

    def test_runtime_state_must_be_active_before_and_after(self) -> None:
        required = ("kcsan",)
        self.assertEqual(
            self.verify(
                required=required,
                runtime_before=self.runtime_snapshot(required, kcsan_enabled=False),
            )[0],
            "BLOCKED",
        )
        self.assertEqual(
            self.verify(
                required=required,
                runtime_after=self.runtime_snapshot(required, kcsan_enabled=False),
            )[0],
            "FAIL",
        )
        self.assertEqual(
            self.verify(
                required=required,
                runtime_before=self.runtime_snapshot(
                    required, kcsan_filter_default=False),
            )[0],
            "BLOCKED",
        )
        required = ("kasan", "lockdep")
        self.assertEqual(
            self.verify(
                required=required,
                runtime_before=self.runtime_snapshot(
                    required, lockdep_debug_locks=False),
            )[0],
            "BLOCKED",
        )
        self.assertEqual(
            self.verify(
                required=required,
                runtime_after=self.runtime_snapshot(
                    required, lockdep_prove_locking=False),
            )[0],
            "FAIL",
        )
        self.assertEqual(
            self.verify(
                required=required,
                baseline="",
                final="",
                runtime_after=self.runtime_snapshot(
                    required, lockdep_debug_locks=False),
            )[0],
            "FAIL",
        )

    def test_runtime_snapshot_parser_and_capture(self) -> None:
        directory = Path(self.temporary_directory.name)
        kcsan = directory / "kcsan"
        lockdep = directory / "lockdep_stats"
        prove = directory / "prove_locking"
        kcsan.write_text(
            "enabled: 1\nwatchpoints: 0\n\nblacklisted functions: none\n",
            encoding="utf-8")
        lockdep.write_text(" lock-classes: 4\n debug_locks: 1\n", encoding="utf-8")
        prove.write_text("1\n", encoding="utf-8")
        required = ("kasan", "lockdep")
        snapshot = qualification.capture_runtime_snapshot(
            required, kcsan, lockdep, prove)
        self.assertTrue(qualification.runtime_features_active(snapshot, required))
        parsed = qualification.parse_runtime_snapshot(
            json.dumps(snapshot), required)
        self.assertEqual(parsed, snapshot)
        kcsan_snapshot = qualification.capture_runtime_snapshot(
            ("kcsan",), kcsan, lockdep, prove)
        self.assertTrue(
            qualification.runtime_features_active(kcsan_snapshot, ("kcsan",)))
        prove.write_text("0\n", encoding="utf-8")
        disabled = qualification.capture_runtime_snapshot(
            required, kcsan, lockdep, prove)
        self.assertFalse(
            qualification.runtime_features_active(disabled, required))
        with self.assertRaises(ValueError):
            qualification.parse_runtime_snapshot("{}", required)

    def test_owned_source_marker_is_bound_to_validated_source(self) -> None:
        self.assertEqual(
            self.verify(execution=GOOD_LOG.replace(
                f"SOURCE_HEAD={SOURCE_SHA}", "SOURCE_HEAD=" + "b" * 40))[0],
            "FAIL",
        )

    def test_no_pass_without_required_debug_feature(self) -> None:
        self.configuration.write_text(CONFIG.replace("CONFIG_KASAN=y", "# CONFIG_KASAN is not set"))
        self.assertEqual(self.verify()[0], "BLOCKED")
        self.assertEqual(self.verify(required=())[0], "BLOCKED")

    def test_missing_repeated_or_fabricated_marker_fails(self) -> None:
        self.assertEqual(self.verify(execution=GOOD_LOG.replace("PASS_LOADED_LIVE_GC=", "SKIPPED="))[0], "FAIL")
        self.assertEqual(self.verify(execution=GOOD_LOG + "\n" + GOOD_LOG.splitlines()[0])[0], "FAIL")
        self.assertEqual(self.verify(execution=GOOD_LOG.replace("active_after:0", "active_after:1"))[0], "FAIL")
        self.assertEqual(
            self.verify(execution=GOOD_LOG.replace(
                "segs_gt1:2", "segs_gt1:2 failed:1"))[0],
            "FAIL",
        )
        self.assertEqual(
            self.verify(execution=GOOD_LOG.replace(
                "victims:2", "victims:2 contradiction:1"))[0],
            "FAIL",
        )
        self.assertEqual(self.verify(execution=GOOD_LOG + "\nQUARANTINED: teardown uncertain")[0], "FAIL")

    def test_log_truncation_and_unavailable_dmesg_block(self) -> None:
        self.assertEqual(self.verify(baseline="", final="new\n")[0], "BLOCKED")
        self.assertEqual(
            self.verify(baseline="", final="WARNING: historical warning\n")[0],
            "BLOCKED",
        )
        self.assertEqual(self.verify(final="different\n")[0], "BLOCKED")

    def test_strong_failure_evidence_precedes_late_observation_gap(self) -> None:
        malformed_runtime = "{}"
        self.assertEqual(
            self.verify(
                final="old\nWARNING: synthetic post-run warning\n",
                runtime_after=malformed_runtime,
            )[0],
            "FAIL",
        )
        self.assertEqual(
            self.verify(runtime_after=malformed_runtime)[0],
            "BLOCKED",
        )

    def test_verify_cli_preserves_fail_vs_blocked_exit_status(self) -> None:
        directory = Path(self.temporary_directory.name)
        baseline = directory / "baseline"
        final = directory / "final"
        execution = directory / "execution"
        runtime_before = directory / "runtime-before"
        runtime_after = directory / "runtime-after"
        baseline.write_text("old\n", encoding="utf-8")
        execution.write_text(GOOD_LOG + "\n", encoding="utf-8")
        required = ("kasan", "lockdep")
        runtime_before.write_text(
            self.runtime_snapshot(required), encoding="utf-8")
        runtime_after.write_text(
            self.runtime_snapshot(required), encoding="utf-8")
        common = [
            sys.executable, "-B", str(SCRIPT), "verify",
            "--config", str(self.configuration),
            "--cmdline", str(self.cmdline),
            "--require", "kasan,lockdep",
            "--source-sha", SOURCE_SHA,
            "--module", str(directory / "unbuilt.ko"),
            "--baseline", str(baseline),
            "--final", str(final),
            "--execution", str(execution),
            "--runtime-before", str(runtime_before),
            "--runtime-after", str(runtime_after),
        ]
        final.write_text("old\nWARNING: synthetic kernel warning\n", encoding="utf-8")
        failed = subprocess.run(
            common, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=False)
        self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
        final.write_text("old\n", encoding="utf-8")
        runtime_before.write_text(
            self.runtime_snapshot(
                required, lockdep_debug_locks=False),
            encoding="utf-8")
        blocked = subprocess.run(
            common, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=False)
        self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
        runtime_before.write_text(
            self.runtime_snapshot(required), encoding="utf-8")
        runtime_after.write_text(
            self.runtime_snapshot(required), encoding="utf-8")
        missing_module = subprocess.run(
            common, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=False)
        self.assertEqual(
            missing_module.returncode, 2,
            missing_module.stdout + missing_module.stderr)
        self.assertIn("module artifact missing", missing_module.stdout)

    def test_kernel_fault_categories_fail(self) -> None:
        diagnostics = (
            "BUG: KASAN: slab-use-after-free",
            "BUG: KCSAN: data-race",
            "BUG: scheduling while atomic",
            "Oops: 0000",
            "possible circular locking dependency detected",
            "refcount_t: underflow",
            "WARNING: CPU: 0 at dm_swapz",
            "workqueue: swapz invoked after free",
            "KASAN: slab-out-of-bounds Read",
            "KCSAN: data-race in dm_swapz",
            "refcount_warn_saturate: saturated",
            "INFO: task kworker blocked for more than 120 seconds",
            "rcu: INFO: rcu_preempt detected stalls on CPUs/tasks",
            "kernel panic - not syncing: unrecoverable",
            "use-after-free detected in dm_swapz",
        )
        for diagnostic in diagnostics:
            with self.subTest(diagnostic=diagnostic):
                self.assertEqual(self.verify(final="old\n" + diagnostic)[0], "FAIL")

    def test_error_reasons_name_configuration_and_boot_disables(self) -> None:
        self.configuration.write_text(
            CONFIG.replace("CONFIG_KCSAN=y", "# CONFIG_KCSAN is not set"),
            encoding="utf-8")
        status, reason = self.verify(required=("kcsan",))
        self.assertEqual(status, "BLOCKED")
        self.assertIn("CONFIG_KCSAN=n", reason)
        self.configuration.write_text(
            CONFIG.replace("CONFIG_LOCKDEP=y", "# CONFIG_LOCKDEP is not set"),
            encoding="utf-8")
        status, reason = self.verify()
        self.assertEqual(status, "BLOCKED")
        self.assertIn("CONFIG_LOCKDEP=n", reason)
        self.configuration.write_text(CONFIG, encoding="utf-8")
        self.cmdline.write_text("kasan=off\n", encoding="utf-8")
        self.assertIn("kasan=off", self.verify()[1])

    def test_missing_duplicate_and_mismatched_run_markers_identified(self) -> None:
        cases = (
            (GOOD_LOG.replace("PASS_LOADED_LIVE_GC=", "SKIPPED="),
             "missing loaded run marker: PASS_LOADED_LIVE_GC"),
            (GOOD_LOG + "\n" + GOOD_LOG.splitlines()[2],
             "duplicated loaded run marker: PASS_LOADED_COMPOUND_BIO"),
            (GOOD_LOG.replace("segs_gt1:2", "segs_gt1:2 invalid:1"),
             "malformed loaded run marker: PASS_LOADED_COMPOUND_BIO"),
            (GOOD_LOG.replace("SOURCE_HEAD=", "OLD_SOURCE="),
             "missing source run marker: SOURCE_HEAD="),
            (GOOD_LOG.replace(f"SOURCE_HEAD={SOURCE_SHA}",
                              "SOURCE_HEAD=" + "b" * 40),
             "source run marker mismatch:"),
            (GOOD_LOG + "\nSOURCE_HEAD=" + SOURCE_SHA,
             "duplicated SOURCE_HEAD run marker"),
        )
        for execution, explanation in cases:
            with self.subTest(explanation=explanation):
                status, reason = self.verify(execution=execution)
                self.assertEqual(status, "FAIL")
                self.assertIn(explanation, reason)

    def test_bounded_fault_diagnostics_and_historical_warning(self) -> None:
        baseline = "WARNING: historical boot warning\nold\n"
        self.assertEqual(self.verify(
            baseline=baseline, final=baseline + "clean\n")[0], "PASS")
        for fault in ("BUG: KCSAN: data-race in swapz",
                      "possible circular locking dependency detected",
                      "BUG: KASAN: use-after-free"):
            with self.subTest(fault=fault):
                status, reason = self.verify(
                    baseline=baseline, final=baseline + fault + "\n")
                self.assertEqual(status, "FAIL")
                self.assertIn(fault, reason)
        status, reason = self.verify(baseline=baseline, final="old\n")
        self.assertEqual(status, "BLOCKED")
        self.assertIn("dmesg truncated or overwritten", reason)
        # A shared character prefix or half a final record is not continuity.
        self.assertEqual(
            self.verify(baseline="old", final="older\n")[0], "BLOCKED")
        status, reason = self.verify(baseline="old\n", final="old\nclean")
        self.assertEqual(status, "BLOCKED")
        self.assertIn("truncated mid-line", reason)
        self.assertEqual(self.verify(
            baseline="", final="WARNING: old warning\n")[0], "BLOCKED")

    def test_precise_runtime_identity_and_instrumentation_reasons(self) -> None:
        required = ("kcsan",)
        status, reason = self.verify(
            required=required, runtime_before=self.runtime_snapshot(
                required, kcsan_enabled=False))
        self.assertEqual(status, "BLOCKED")
        self.assertIn("KCSAN debugfs enabled=0", reason)
        status, reason = self.verify(
            required=required, runtime_after=self.runtime_snapshot(
                required, kcsan_enabled=False))
        self.assertEqual(status, "FAIL")
        self.assertIn("KCSAN debugfs enabled=0", reason)
        state = json.loads(self.runtime_snapshot(required))
        state["boot_id"] = "00000000-0000-0000-0000-000000000000"
        for key, label in (("runtime_before", "runtime-before"),
                           ("runtime_after", "runtime-after")):
            with self.subTest(key=key):
                status, reason = self.verify(
                    required=required, **{key: json.dumps(state)})
                self.assertEqual(status, "BLOCKED")
                self.assertIn(label + " boot mismatch", reason)
        self.assertIn(
            "lockdep prove_locking=0",
            self.verify(runtime_after=self.runtime_snapshot(
                ("kasan", "lockdep"), lockdep_prove_locking=False))[1])

    def test_bad_or_missing_module_provenance_blocks_clean_claim(self) -> None:
        clean = {
            "source_sha": SOURCE_SHA, "source_clean": "1",
            "symbols": "__asan_load8 __tsan_read8",
        }
        cases = (
            ({"error": "module artifact missing: dm-swapz.ko"},
             "module artifact missing"),
            ({}, "module source SHA mismatch"),
            ({**clean, "source_sha": "b" * 40}, "module source SHA mismatch"),
            ({**clean, "source_clean": "0"}, "clean validated source"),
            ({**clean, "symbols": "__tsan_read8"}, "KASAN instrumentation"),
        )
        for evidence, explanation in cases:
            with self.subTest(explanation=explanation):
                status, reason = self.verify(module_evidence=evidence)
                self.assertEqual(status, "BLOCKED")
                self.assertIn(explanation, reason)
        status, reason = self.verify(
            required=("kcsan",),
            module_evidence={**clean, "symbols": "__asan_load8"})
        self.assertEqual(status, "BLOCKED")
        self.assertIn("KCSAN instrumentation", reason)
        status, reason = self.verify(
            module_evidence={"error": "module artifact missing"},
            final="old\nBUG: KASAN: use-after-free\n")
        self.assertEqual(status, "FAIL")
        self.assertIn("KASAN", reason)

    def test_rootless_module_inspection_and_tool_unavailability(self) -> None:
        module = Path(self.temporary_directory.name) / "dm-swapz.ko"
        self.assertIn("module artifact missing",
                      qualification.inspect_module_provenance(module)["error"])
        module.write_bytes(b"synthetic module, never loaded")
        with mock.patch.object(qualification.shutil, "which", return_value=None):
            self.assertIn("tool unavailable: modinfo",
                          qualification.inspect_module_provenance(module)["error"])
        with mock.patch.object(qualification.shutil, "which", return_value="/usr/bin/tool"), \
             mock.patch.object(qualification.subprocess, "run") as runner:
            runner.side_effect = [
                subprocess.CompletedProcess([], 0, SOURCE_SHA + "\n", ""),
                subprocess.CompletedProcess([], 0, "1\n", ""),
                subprocess.CompletedProcess([], 0, "U __asan_load8\nU __tsan_read8\n", ""),
            ]
            observed = qualification.inspect_module_provenance(module)
            self.assertEqual(observed["source_sha"], SOURCE_SHA)
            self.assertEqual(observed["source_clean"], "1")
            self.assertIn("__tsan_read8", observed["symbols"])
            self.assertEqual(runner.call_count, 3)
            runner.side_effect = None
            runner.return_value = subprocess.CompletedProcess([], 1, "", "bad")
            self.assertIn("query failed",
                          qualification.inspect_module_provenance(module)["error"])

    def test_sparse_source_warnings_vs_infrastructure_absence(self) -> None:
        headers = Path(self.temporary_directory.name) / "sparse-headers"
        headers.mkdir()
        (headers / ".config").write_text("CONFIG_X86_64=y\n", encoding="utf-8")
        with mock.patch.object(qualification.shutil, "which", return_value="/usr/bin/sparse"), \
             mock.patch.object(qualification.subprocess, "run") as runner, \
             contextlib.redirect_stderr(io.StringIO()):
            runner.return_value = subprocess.CompletedProcess(
                [], 1, "sparse: unsupported compiler flags\n")
            status, checks, warnings = qualification.run_static(
                Path("/repo"), headers, "sparse")
            self.assertEqual((status, checks, warnings), ("BLOCKED", 0, {}))
            runner.return_value = subprocess.CompletedProcess(
                [], 1, "  CHECK /repo/build/kernel/w1/dm-target.c\n"
                "dm-target.c:20:3: warning: incorrect type in argument\n")
            status, checks, warnings = qualification.run_static(
                Path("/repo"), headers, "sparse")
            self.assertEqual(status, "FAIL")
            self.assertEqual(warnings["locking_or_type"], 1)

    def test_static_warning_classes_and_no_false_clean_pass(self) -> None:
        output = ("  CHECK /repo/build/kernel/w1/dm-target.c\n"
                  "dm-target.c:20:3: warning: incorrect type in argument\n"
                  "dm-target.c:30:4: warning: incorrect address space __user\n"
                  "dm-target.c:40:4: warning: restricted __le32 degrades\n")
        count, warnings = qualification.scan_static(output)
        self.assertEqual(count, 1)
        self.assertEqual(warnings, {
            "locking_or_type": 1, "address_space": 1, "endian_or_bitwise": 1,
        })
        self.assertEqual(qualification.scan_static("module built\n")[0], 0)
        self.assertEqual(qualification.scan_static("warning: compiler differs\n")[1], {})
        self.assertEqual(
            qualification.classify_warning(
                "predictor-shuffle.h:60:22: error: undefined identifier '__builtin_shuffle'"
            ),
            "unsupported_simd_builtin",
        )
        self.assertEqual(
            qualification.classify_warning(
                "predictor-avx512.c:87:38: error: invalid initializer"
            ),
            "simd_initializer",
        )
        self.assertEqual(
            qualification.classify_warning(
                "dm-target.c:30:11: error: invalid initializer"
            ),
            "other",
        )
        self.assertEqual(
            qualification.classify_warning(
                "dm-target.c:99:4: error: undefined identifier '__builtin_shuffle'"
            ),
            "other",
        )

    def test_static_inventory_tracks_module_kbuild_and_rejects_arch_drift(self) -> None:
        directory = Path(self.temporary_directory.name)
        headers = directory / "configured-headers"
        (headers / "include/config").mkdir(parents=True)
        configuration = headers / ".config"
        auto_config = headers / "include/config/auto.conf"
        configuration.write_text("CONFIG_X86_64=y\n", encoding="utf-8")
        auto_config.write_text("CONFIG_ARM64=y\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "contradict"):
            qualification.static_required_sources(headers)
        auto_config.write_text("CONFIG_X86_64=y\n", encoding="utf-8")

        original = (Path(__file__).resolve().parents[3] /
                    "src/kernel/Makefile").read_text(encoding="utf-8")
        modified = directory / "Makefile"
        suffix = "predictor-sse2.o predictor-avx2.o predictor-avx512.o"
        self.assertIn(suffix, original)
        modified.write_text(original.replace(
            suffix, suffix + " predictor-future.o"), encoding="utf-8")
        self.assertIn(
            "predictor-future.c",
            qualification.static_required_sources(headers, modified),
        )
        modified.write_text(original.replace(
            suffix, suffix + "\nifeq ($(UNMODELLED),y)\n"
            "dm-swapz-y += predictor-future.o\nendif"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "unsupported"):
            qualification.static_required_sources(headers, modified)
        modified.write_text(original.replace(
            suffix, suffix + "\n"
            "dm-swapz-$(CONFIG_X86_64) += predictor-future.o"),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "unsupported"):
            qualification.static_required_sources(headers, modified)

        configuration.write_text("CONFIG_X86_64=y\nCONFIG_ARM64=y\n",
                                 encoding="utf-8")
        auto_config.write_text(configuration.read_text(encoding="utf-8"),
                               encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "contradictory"):
            qualification.static_required_sources(headers)
        configuration.write_text("CONFIG_SMP=y\n", encoding="utf-8")
        auto_config.write_text("CONFIG_SMP=y\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not identifiable"):
            qualification.static_required_sources(headers)

    def test_static_rejects_partial_stale_and_duplicate_check_records(self) -> None:
        headers = Path(self.temporary_directory.name) / "checked-headers"
        headers.mkdir()
        (headers / ".config").write_text("CONFIG_X86_64=y\n",
                                         encoding="utf-8")
        sources = (
            "dm-target", "codec", "authority", "engine", "predictor",
            "predictor-sse2", "predictor-avx2", "predictor-avx512",
        )
        complete = "".join(
            f"  CHECK /repo/build/kernel/w1/{name}.c\n" for name in sources)
        basename_only = "".join(
            f"  CHECK {name}.c\n" for name in sources)
        relative_from_module = "".join(
            f"  CHECK ../../build/kernel/w1/{name}.c\n" for name in sources)
        with mock.patch.object(qualification.shutil, "which", return_value="/usr/bin/sparse"), \
             mock.patch.object(qualification.subprocess, "run") as runner, \
             contextlib.redirect_stderr(io.StringIO()):
            def verdict(output: str, status: int = 0) -> str:
                runner.return_value = subprocess.CompletedProcess(
                    args=[], returncode=status, stdout=output)
                return qualification.run_static(Path("/repo"), headers, "sparse")[0]

            self.assertEqual(verdict(complete), "PASS")
            self.assertEqual(verdict(basename_only), "PASS")
            self.assertEqual(verdict(relative_from_module), "PASS")
            self.assertEqual(verdict(complete.replace(
                "  CHECK /repo/build/kernel/w1/predictor-avx512.c\n", "")),
                "BLOCKED")
            self.assertEqual(verdict(complete + (
                "  CHECK /repo/build/kernel/w1/predictor-sse2.c\n")),
                "BLOCKED")
            self.assertEqual(verdict(complete.replace(
                "/repo/build/kernel/w1/predictor-avx2.c",
                "/other/build/kernel/w1/predictor-avx2.c")), "BLOCKED")
            self.assertEqual(verdict(complete + (
                "predictor-avx512.c:17:4: error: invalid initializer\n")),
                "FAIL")
            self.assertEqual(verdict(complete + (
                "predictor-shuffle.h:61:12: error: "
                "undefined identifier '__builtin_shuffle'\n")), "FAIL")
            self.assertEqual(verdict(complete, 2), "BLOCKED")
            runner.side_effect = subprocess.TimeoutExpired(
                cmd=["make"], timeout=900)
            self.assertEqual(
                qualification.run_static(
                    Path("/repo"), headers, "sparse")[0],
                "BLOCKED",
            )
            runner.side_effect = None

    def test_runtime_capture_rejects_contradictory_live_status(self) -> None:
        directory = Path(self.temporary_directory.name)
        kcsan = directory / "kcsan-status"
        lockdep = directory / "lockdep-status"
        prove = directory / "prove-locking"
        prove.write_text("1\n", encoding="utf-8")
        kcsan.write_text(
            "enabled: 1\nblacklisted functions: none\n"
            "blacklisted functions: swapz\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "blacklist"):
            qualification.capture_runtime_snapshot(
                ("kcsan",), kcsan, lockdep, prove)
        kcsan.write_text(
            "enabled: 1\nenabled: disabled\n"
            "blacklisted functions: none\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "enabled"):
            qualification.capture_runtime_snapshot(
                ("kcsan",), kcsan, lockdep, prove)
        lockdep.write_text("debug_locks: 1\ndebug_locks: invalid\n",
                           encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "debug_locks"):
            qualification.capture_runtime_snapshot(
                ("lockdep",), kcsan, lockdep, prove)

    def test_runtime_json_must_have_unique_current_ordered_observations(self) -> None:
        required = ("kcsan",)
        good = self.runtime_snapshot(required)
        state = json.loads(good)
        for malformed in (
            good.replace('"kcsan_enabled": true',
                         '"kcsan_enabled": false, "kcsan_enabled": true'),
            good.replace('"observed_monotonic_ns":',
                         '"unexpected": 1, "observed_monotonic_ns":'),
            good.replace('"observed_monotonic_ns":',
                         '"observed_monotonic_ns": NaN, "observed_monotonic_ns":'),
            "{}",
        ):
            with self.subTest(malformed=malformed[:64]), self.assertRaises(ValueError):
                qualification.parse_runtime_snapshot(malformed, required)
        self.assertEqual(
            self.verify(required=required, runtime_before=good,
                        runtime_after=good)[0], "BLOCKED")
        stale = dict(state)
        stale["observed_monotonic_ns"] -= qualification.MAX_RUNTIME_AGE_NS + 1_000_000_000
        self.assertEqual(
            self.verify(required=required,
                        runtime_before=json.dumps(stale))[0], "BLOCKED")
        other_boot = dict(state)
        other_boot["boot_id"] = "00000000-0000-0000-0000-000000000000"
        self.assertEqual(
            self.verify(required=required,
                        runtime_before=json.dumps(other_boot))[0], "BLOCKED")
        future = dict(state)
        future["observed_monotonic_ns"] += qualification.MAX_RUNTIME_AGE_NS
        self.assertEqual(
            self.verify(required=required,
                        runtime_after=json.dumps(future))[0], "BLOCKED")

    def test_contradictory_and_malformed_success_claims_fail(self) -> None:
        for execution in (
            GOOD_LOG + "\nSOURCE_HEAD=" + "b" * 40,
            GOOD_LOG + "\nSOURCE_HEAD=broken",
            GOOD_LOG + "\nPASS_LOADED_LIVE_GC=victims:0 verified_pages:0",
            GOOD_LOG + "\nPASS_LOADED_LIVE_GC invalid",
            GOOD_LOG + "\nPASS_LOADED_LIVE_GC_EXTRA=stale",
            GOOD_LOG + "\nPASS: loaded isolated swapz byte-exact I/O, clean teardown",
        ):
            with self.subTest(execution=execution.splitlines()[-1]):
                self.assertEqual(self.verify(execution=execution)[0], "FAIL")
        self.assertEqual(
            self.verify(execution=GOOD_LOG + "\nFAIL: lower device damaged",
                        baseline="", final="", runtime_after="{}")[0], "FAIL")
        self.assertEqual(
            self.verify(final="WARNING: late ring-buffer warning",
                        baseline="", runtime_after="{}")[0], "BLOCKED")
        self.configuration.write_text(
            CONFIG.replace("CONFIG_LOCKDEP=y", "# CONFIG_LOCKDEP is not set"),
            encoding="utf-8",
        )
        self.assertEqual(
            self.verify(execution=GOOD_LOG + "\nQUARANTINED: teardown uncertain",
                        baseline="", final="")[0], "FAIL")

    def test_missing_late_cli_files_cannot_hide_prior_failure(self) -> None:
        directory = Path(self.temporary_directory.name)
        baseline = directory / "baseline"
        final = directory / "final"
        execution = directory / "execution"
        before = directory / "before"
        after = directory / "after"
        baseline.write_text("old\n", encoding="utf-8")
        execution.write_text(GOOD_LOG + "\nFAIL: helper failed\n",
                             encoding="utf-8")
        command = [
            sys.executable, "-B", str(SCRIPT), "verify",
            "--config", str(self.configuration), "--cmdline", str(self.cmdline),
            "--require", "kasan,lockdep", "--source-sha", SOURCE_SHA,
            "--baseline", str(baseline), "--final", str(final),
            "--execution", str(execution),
            "--runtime-before", str(before), "--runtime-after", str(after),
        ]
        failed = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
        execution.unlink()
        final.write_text("old\nBUG: kernel memory corruption\n",
                         encoding="utf-8")
        failed = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
        final.unlink()
        blocked = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)

    def test_static_cli_distinguishes_defects_from_missing_tools(self) -> None:
        headers = Path(self.temporary_directory.name) / "cli-headers"
        headers.mkdir()
        (headers / "Makefile").write_text("all:\n\t@true\n",
                                          encoding="utf-8")
        argv = [str(SCRIPT), "static", "--kdir", str(headers)]
        for statuses, expected_exit in (
            ((("FAIL", 8, {"locking_or_type": 1}),
              ("UNAVAILABLE", 0, {})), 1),
            ((("PASS", 8, {}), ("FAIL", 8, {"other": 1})), 1),
            ((("BLOCKED", 7, {}), ("UNAVAILABLE", 0, {})), 2),
            ((("PASS", 8, {}), ("BLOCKED", 3, {})), 2),
            ((("UNAVAILABLE", 0, {}), ("UNAVAILABLE", 0, {})), 2),
            ((("PASS", 8, {}), ("UNAVAILABLE", 0, {})), 0),
        ):
            with self.subTest(statuses=statuses), \
                 mock.patch.object(sys, "argv", argv), \
                 mock.patch.object(qualification, "run_static",
                                   side_effect=statuses), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(qualification.main(), expected_exit)

    def test_hosted_static_workflow_does_not_run_loaded_debug_lanes(self) -> None:
        workflow = (Path(__file__).resolve().parents[3] /
                    ".github/workflows/kernel-debug.yml").read_text(encoding="utf-8")
        self.assertIn("KERNEL_DEBUG_LOADED_KASAN_LOCKDEP=NOT_RUN", workflow)
        self.assertIn("KERNEL_DEBUG_LOADED_KCSAN=NOT_RUN", workflow)
        self.assertIn("KERNEL_DEBUG_STATIC_COMPILE_ONLY_NO_MODULE_LOADING", workflow)
        self.assertNotIn("modprobe ", workflow)

    def test_owned_wrapper_binds_runtime_state_and_artifact_provenance(self) -> None:
        source = WRAPPER.read_text(encoding="utf-8")
        self.assertIn("SWAPZ_SIGN_NONINTERACTIVE=1 make", source)
        self.assertIn("modinfo -F swapz_build_source_sha", source)
        self.assertIn("modinfo -F swapz_build_source_clean", source)
        self.assertIn('nm -u "$module"', source)
        self.assertIn("module lacks observable KASAN instrumentation references", source)
        self.assertIn("module lacks observable KCSAN instrumentation references", source)
        self.assertGreaterEqual(source.count("runtime-snapshot"), 1)
        self.assertIn('--runtime-before "$session/runtime-before.json"', source)
        self.assertIn('--runtime-after "$session/runtime-after.json"', source)
        self.assertIn("verify_rc=$?", source)
        self.assertIn("runtime_after_rc=$?", source)
        self.assertNotIn("kcsan.enabled=0", source)
        self.assertNotIn("lockdep=off", source)
        instrumentation = source.index('undefined_symbols="$(nm -u "$module"')
        runtime_before = source.index(
            'capture_runtime_snapshot "$session/runtime-before.json"')
        baseline = source.index(
            'dmesg --color=never --notime > "$session/baseline.log"')
        helper = source.index(
            'tests/tools/deploy-nullblk.sh --validated-source "$source_sha"')
        runtime_after = source.index(
            'capture_runtime_snapshot "$session/runtime-after.json"')
        verifier = source.index(
            'tests/tools/kernel-debug-qualify.py verify')
        self.assertLess(instrumentation, runtime_before)
        self.assertLess(runtime_before, baseline)
        self.assertLess(baseline, helper)
        self.assertLess(helper, runtime_after)
        self.assertLess(runtime_after, verifier)

    def test_loaded_helper_exposes_required_debug_evidence_markers(self) -> None:
        source = DEPLOY_HELPER.read_text(encoding="utf-8")
        labels = (
            "PASS_LOADED_CONSTRUCTOR_FAILURE_CLEANUP",
            "PASS_LOADED_COMPOUND_BIO",
            "PASS_LOADED_LIVE_GC",
            "PASS_LOADED_DISCARD_TRIM",
            "PASS_LOADED_SUSPEND_DRAIN",
            "PASS_RETAINED_SYNTHETIC_WRITE_FAULT",
            "PASS_LOADED_SYNTHETIC_READ_FAULT",
            "PASS_RETAINED_SYNTHETIC_FLUSH_FAULT",
            "PASS_LOADED_CODEC_ERROR_PATHS",
            "PASS_LOADED_COMPLETION_HANDOFF",
            "PASS: loaded isolated swapz byte-exact I/O, clean teardown",
        )
        for label in labels:
            with self.subTest(label=label):
                self.assertEqual(source.count(label), 1)
        for marker, expected_keys in qualification.REQUIRED_RECORD_KEYS.items():
            with self.subTest(marker=marker):
                matches = re.findall(
                    r'note "' + re.escape(marker) + r'=([^"]+)"', source)
                self.assertEqual(len(matches), 1)
                observed_keys = tuple(
                    token.split(":", 1)[0] for token in matches[0].split())
                self.assertEqual(observed_keys, expected_keys)

    def test_sparse_simd_checker_seams_preserve_production_paths(self) -> None:
        root = Path(__file__).resolve().parents[3]
        shuffle = (root / "src/kernel/predictor-shuffle.h").read_text(
            encoding="utf-8")
        self.assertIn("#if defined(__CHECKER__)", shuffle)
        self.assertIn("swapz_checker_shuffle16", shuffle)
        self.assertIn("__builtin_shuffle((a), (b)", shuffle)
        self.assertLess(
            shuffle.index("swapz_checker_shuffle16"),
            shuffle.index("__builtin_shuffle((a), (b)"),
        )

        sse2 = (root / "src/kernel/predictor-sse2.c").read_text(
            encoding="utf-8")
        avx2 = (root / "src/kernel/predictor-avx2.c").read_text(
            encoding="utf-8")
        avx512 = (root / "src/kernel/predictor-avx512.c").read_text(
            encoding="utf-8")
        for source in (sse2, avx2, avx512):
            self.assertIn("#if defined(__CHECKER__)", source)
        self.assertIn("swapz_u64x2 base = { 0ULL, 0ULL };", sse2)
        self.assertIn(
            "const swapz_u64x4 upper_mask = {0ULL, 0ULL, ~0ULL, ~0ULL};",
            avx2,
        )
        self.assertIn("step0 = (swapz_u64x8){", avx512)
        self.assertIn("step1 = (swapz_u64x8){", avx512)

    def test_static_required_sources_follow_kernel_architecture(self) -> None:
        headers = Path(self.temporary_directory.name) / "headers"
        headers.mkdir()
        config = headers / ".config"
        config.write_text("CONFIG_X86_64=y\n", encoding="utf-8")
        self.assertEqual(
            qualification.static_required_sources(headers),
            {
                "dm-target.c", "codec.c", "authority.c", "engine.c",
                "predictor.c", "predictor-sse2.c", "predictor-avx2.c",
                "predictor-avx512.c",
            },
        )
        config.write_text(
            "CONFIG_ARM64=y\nCONFIG_KERNEL_MODE_NEON=y\n",
            encoding="utf-8",
        )
        self.assertEqual(
            qualification.static_required_sources(headers),
            {
                "dm-target.c", "codec.c", "authority.c", "engine.c",
                "predictor.c", "predictor-neon.c",
            },
        )

    def test_static_checker_requires_actual_check_and_zero_warnings(self) -> None:
        headers = Path(self.temporary_directory.name) / "static-headers"
        headers.mkdir()
        (headers / ".config").write_text("CONFIG_X86_64=y\n", encoding="utf-8")
        with mock.patch.object(qualification.shutil, "which", return_value="/usr/bin/sparse"), \
             mock.patch.object(qualification.subprocess, "run") as runner:
            runner.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="  CC /build/dm-target.o\n",
            )
            expected_failure_log = io.StringIO()
            with contextlib.redirect_stderr(expected_failure_log):
                self.assertEqual(
                    qualification.run_static(
                        Path("/repo"), headers, "sparse")[0],
                    "BLOCKED",
                )
            self.assertIn("BLOCKED_KERNEL_STATIC_SPARSE",
                          expected_failure_log.getvalue())
            runner.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=(
                    "  CHECK /repo/build/kernel/w1/dm-target.c\n"
                    "  CHECK /repo/build/kernel/w1/codec.c\n"
                    "  CHECK /repo/build/kernel/w1/authority.c\n"
                    "  CHECK /repo/build/kernel/w1/engine.c\n"
                    "  CHECK /repo/build/kernel/w1/predictor.c\n"
                    "  CHECK /repo/build/kernel/w1/predictor-sse2.c\n"
                    "  CHECK /repo/build/kernel/w1/predictor-avx2.c\n"
                    "  CHECK /repo/build/kernel/w1/predictor-avx512.c\n"
                ),
            )
            self.assertEqual(
                qualification.run_static(
                    Path("/repo"), headers, "sparse")[0],
                "PASS",
            )
            command = runner.call_args.args[0]
            self.assertIn("C=2", command)
            self.assertIn("W=1", command)
            self.assertIn("CHECK=sparse", command)
        with mock.patch.object(qualification.shutil, "which", return_value=None):
            self.assertEqual(
                qualification.run_static(
                    Path("/repo"), Path("/headers"), "smatch")[0],
                "UNAVAILABLE",
            )


if __name__ == "__main__":
    unittest.main()
