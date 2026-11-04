#!/usr/bin/env python3
"""Rootless negative controls for the private kernel-debug qualification lane."""
from __future__ import annotations

import gzip
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[2] / "tools/kernel-debug-qualify.py"
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
GOOD_LOG = """
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

    def verify(self, execution: str = GOOD_LOG, final: str = "old\nnew\n",
               required: tuple[str, ...] = ("kasan", "lockdep"),
               baseline: str = "old\n") -> tuple[str, str]:
        return qualification.verify_owned_run(
            required, self.features(), baseline, final, execution,
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
        self.assertEqual(set(self.features().values()), {"DISABLED_AT_BOOT"})

    def test_gzipped_config_and_unreadable_cmdline(self) -> None:
        compressed = self.configuration.with_suffix(".gz")
        with gzip.open(compressed, "wt", encoding="utf-8") as stream:
            stream.write(CONFIG)
        self.assertEqual(qualification.probe(compressed, self.cmdline)["kcsan"], "DETECTED")
        self.assertEqual(
            qualification.probe(compressed, self.cmdline.parent / "not-present")["kcsan"],
            "UNKNOWN",
        )

    def test_separate_kcsan_lane(self) -> None:
        self.assertEqual(qualification.required_features("kcsan"), ("kcsan",))
        for invalid in ("kasan,kcsan", "lockdep,kcsan", "kasan,kasan", "unknown"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                qualification.required_features(invalid)

    def test_valid_owned_evidence(self) -> None:
        self.assertEqual(self.verify()[0], "PASS")
        self.assertEqual(self.verify(required=("kcsan",))[0], "PASS")

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

    def test_kernel_fault_categories_fail(self) -> None:
        diagnostics = (
            "BUG: KASAN: slab-use-after-free",
            "BUG: KCSAN: data-race",
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

    def test_static_checker_requires_actual_check_and_zero_warnings(self) -> None:
        with mock.patch.object(qualification.shutil, "which", return_value="/usr/bin/sparse"), \
             mock.patch.object(qualification.subprocess, "run") as runner:
            runner.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="  CC /build/dm-target.o\n",
            )
            self.assertEqual(qualification.run_static(Path("/repo"), Path("/headers"), "sparse")[0], "FAIL")
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
