#!/usr/bin/env python3
"""Rootless negative controls for the private kernel-debug qualification lane."""
from __future__ import annotations

import contextlib
import gzip
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
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
PASS_LOADED_COMPOUND_BIO=written_pages:384 verified_pages:384 segs_gt1:2 failed:0
PASS_LOADED_LIVE_GC=victims:2 rotations:2 verified_pages:4096
PASS_LOADED_DISCARD_TRIM=pages:256 immediate_discards:1 verified_pages:4096
PASS_LOADED_SUSPEND_DRAIN=retain_ms:64 observed_open:1 verified_pages:128
PASS_RETAINED_SYNTHETIC_WRITE_FAULT=retain_ms:2 injected:1 syscall_errno:EIO lower_write_delta:0
PASS_LOADED_SYNTHETIC_READ_FAULT=page:2048 injected:1 syscall_errno:EIO lower_read_delta:0 submitted_delta:0
PASS_RETAINED_SYNTHETIC_FLUSH_FAULT=retain_ms:2 injected:1 data_write_reached_lower:1
PASS_LOADED_CODEC_ERROR_PATHS=owners:3 injected:3 inline_lower_write_delta:0
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
               runtime_after: str | None = None) -> tuple[str, str]:
        return qualification.verify_owned_run(
            required, self.features(), baseline, final, execution,
            runtime_before or self.runtime_snapshot(required),
            runtime_after or self.runtime_snapshot(required),
            SOURCE_SHA,
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
        self.assertEqual(self.verify(execution=GOOD_LOG + "\nQUARANTINED: teardown uncertain")[0], "FAIL")

    def test_log_truncation_and_unavailable_dmesg_block(self) -> None:
        self.assertEqual(self.verify(baseline="", final="new\n")[0], "BLOCKED")
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
        )
        for diagnostic in diagnostics:
            with self.subTest(diagnostic=diagnostic):
                self.assertEqual(self.verify(final="old\n" + diagnostic)[0], "FAIL")

    def test_static_warning_classes_and_no_false_clean_pass(self) -> None:
        output = ("  CHECK /build/dm-target.c\n"
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

    def test_static_checker_requires_actual_check_and_zero_warnings(self) -> None:
        with mock.patch.object(qualification.shutil, "which", return_value="/usr/bin/sparse"), \
             mock.patch.object(qualification.subprocess, "run") as runner:
            runner.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="  CC /build/dm-target.o\n",
            )
            expected_failure_log = io.StringIO()
            with contextlib.redirect_stderr(expected_failure_log):
                self.assertEqual(
                    qualification.run_static(
                        Path("/repo"), Path("/headers"), "sparse")[0],
                    "FAIL",
                )
            self.assertIn("FAIL_KERNEL_STATIC_SPARSE", expected_failure_log.getvalue())
            runner.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=(
                    "  CHECK /build/dm-target.c\n"
                    "  CHECK /build/codec.c\n"
                    "  CHECK /build/authority.c\n"
                    "  CHECK /build/engine.c\n"
                    "  CHECK /build/predictor.c\n"
                ),
            )
            self.assertEqual(qualification.run_static(Path("/repo"), Path("/headers"), "sparse")[0], "PASS")
            command = runner.call_args.args[0]
            self.assertIn("C=2", command)
            self.assertIn("W=1", command)
            self.assertIn("CHECK=sparse", command)
        with mock.patch.object(qualification.shutil, "which", return_value=None):
            self.assertEqual(qualification.run_static(Path("/repo"), Path("/headers"), "smatch")[0], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
