#!/usr/bin/env python3
"""Rootless negative controls for the private kernel-debug qualification lane."""
from __future__ import annotations

import contextlib
import gzip
import hashlib
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
KERNEL_RELEASE = "test-debug-kernel"
BOOT_ID = qualification.DEFAULT_BOOT_ID.read_text(encoding="utf-8").strip()
MODULE_BYTES = b"synthetic module, never loaded"
MODULE_SHA256 = hashlib.sha256(MODULE_BYTES).hexdigest()
GOOD_LOG = f"""
SOURCE_HEAD={SOURCE_SHA}
RUNNING_KERNEL={KERNEL_RELEASE}
MODULE_SHA256={MODULE_SHA256}  /repo/build/kernel/experimental/dm-swapz.ko
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
BOOT_ID={BOOT_ID}
PASS: loaded isolated swapz byte-exact I/O, clean teardown
""".strip() + "\n"


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
               module_evidence: dict[str, str] | None = None,
               preflight_block_reason: str | None = None) -> tuple[str, str]:
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
                "source_sha": SOURCE_SHA,
                "source_clean": "1",
                "sha256": MODULE_SHA256,
                "vermagic": KERNEL_RELEASE + " SMP preempt mod_unload",
                "symbols": "__asan_load8 __tsan_read8",
            }
        return qualification.verify_owned_run(
            required, self.features(), baseline, final, execution,
            runtime_before, runtime_after, SOURCE_SHA,
            module_evidence=module_evidence,
            configuration=qualification.load_config(self.configuration),
            kernel_release=KERNEL_RELEASE,
            preflight_block_reason=preflight_block_reason,
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

    def test_partial_lane_cannot_claim_loaded_pass(self) -> None:
        # These full synthetic PASS records previously qualified a lockdep-only
        # lane with no KASAN symbols, or KASAN with no lockdep runtime checks.
        clean_module = {
            "source_sha": SOURCE_SHA,
            "source_clean": "1",
            "sha256": MODULE_SHA256,
            "vermagic": KERNEL_RELEASE + " SMP preempt mod_unload",
        }
        for required, symbols in (
            (("lockdep",), ""),
            (("kasan",), "__asan_load8"),
            (("lockdep", "kasan"), "__asan_load8"),
        ):
            with self.subTest(required=required):
                status, reason = self.verify(
                    required=required,
                    module_evidence={**clean_module, "symbols": symbols},
                )
                self.assertEqual(status, "BLOCKED", reason)
                self.assertIn("required instrumentation lane incomplete", reason)
                self.assertIn("expected kasan,lockdep or kcsan", reason)
                self.assertIn("next: collect", reason)
        self.assertIsNone(qualification.incomplete_loaded_lane_reason(
            ("kasan", "lockdep")))
        self.assertIsNone(qualification.incomplete_loaded_lane_reason(
            ("kcsan",)))

    def test_execution_boot_marker_binds_loaded_evidence(self) -> None:
        without_boot = "\n".join(
            line for line in GOOD_LOG.splitlines()
            if not line.startswith("BOOT_ID=")
        ) + "\n"
        status, reason = self.verify(execution=without_boot)
        self.assertEqual(status, "BLOCKED")
        self.assertIn(f"expected BOOT_ID={BOOT_ID}", reason)
        self.assertIn("observed missing", reason)
        self.assertIn("next:", reason)

        other_boot = "00000000-0000-0000-0000-000000000000"
        status, reason = self.verify(execution=GOOD_LOG.replace(
            f"BOOT_ID={BOOT_ID}", f"BOOT_ID={other_boot}"))
        self.assertEqual(status, "BLOCKED")
        self.assertIn("observed different valid boot ID", reason)
        self.assertNotIn(other_boot, reason)
        self.assertIn("next:", reason)

        status, reason = self.verify(
            execution=GOOD_LOG + f"\nBOOT_ID={BOOT_ID}")
        self.assertEqual(status, "BLOCKED")
        self.assertIn("observed duplicate markers", reason)


    def test_terminal_publication_rejects_mixed_and_failed_sessions(self) -> None:
        # Match the actual producer: the BOOT_ID/PASS pair is published only
        # after successful teardown, not alongside the initial source markers.
        lines = GOOD_LOG.splitlines()
        boot_marker = f"BOOT_ID={BOOT_ID}"
        terminal_pass = "PASS: loaded isolated swapz byte-exact I/O, clean teardown"
        self.assertEqual(lines[-2:], [boot_marker, terminal_pass])
        self.assertEqual(self.verify()[0], "PASS")
        self.assertEqual(
            self.verify(execution=GOOD_LOG +
                        "EVIDENCE=/synthetic/swapz-deploy.abcdefgh/session.log\n")[0],
            "PASS")

        # Even a unique, individually valid record set must not qualify when
        # a terminal success pair is pasted ahead of unfinished loaded work.
        unfinished_prefix = lines[:-2]
        stitched_execution = "\n".join(
            unfinished_prefix[:5] + lines[-2:] + unfinished_prefix[5:]) + "\n"
        reordered_records = lines.copy()
        reordered_records[3], reordered_records[4] = (
            reordered_records[4], reordered_records[3])
        private_detail = "/private/owner/teardown-evidence"
        cases = (
            (GOOD_LOG.rstrip("\n"), "field=terminal newline"),
            (stitched_execution, "observed=reordered or combined-session markers"),
            ("\n".join(reordered_records) + "\n", "field=marker order"),
            (GOOD_LOG.replace(
                boot_marker, f"TEARDOWN_FAILED=1\n{boot_marker}"),
             "observed=unknown failure marker"),
            (GOOD_LOG.replace(
                boot_marker, f"FAILURE: {private_detail}\n{boot_marker}"),
             "observed=unknown failure marker"),
            (GOOD_LOG.replace(
                boot_marker, f"ERROR: {private_detail}\n{boot_marker}"),
             "observed=unknown failure marker"),
            (GOOD_LOG + f"TEARDOWN_FAILED={private_detail}\n",
             "field=terminal tail"),
            (GOOD_LOG + GOOD_LOG, "duplicate"),
        )
        for execution, explanation in cases:
            with self.subTest(explanation=explanation):
                status, reason = self.verify(execution=execution)
                self.assertEqual(status, "BLOCKED", reason)
                self.assertIn(explanation, reason)
                self.assertNotIn(private_detail, reason)
                self.assertLess(len(reason), 512)
        status, reason = self.verify(execution=GOOD_LOG.replace(
            boot_marker, f"TEARDOWN_FAILED=1\n{boot_marker}"))
        self.assertEqual(status, "BLOCKED")
        self.assertIn("phase=teardown", reason)
        self.assertIn(f"source=SOURCE_HEAD:{SOURCE_SHA}", reason)
        self.assertIn(f"artifact=MODULE_SHA256:{MODULE_SHA256}", reason)
        self.assertIn("next:", reason)

    def test_execution_boot_marker_producer_rootless(self) -> None:
        """Execute the real boot reader and EXIT cleanup without host devices."""
        import os

        source = DEPLOY_HELPER.read_text(encoding="utf-8")

        def shell_function(function_name: str) -> str:
            start = source.index(f"{function_name}() {{\n")
            return source[start:source.index("\n}\n", start) + 2]

        reader = shell_function("swapz_read_session_boot_id")
        cleanup = shell_function("cleanup")
        session_marker = (
            "printf 'BOOT_ID=%s\\n%s\\n' "
            '"$SESSION_BOOT_ID" "$terminal_success" >> "$SESSION/session.log"')
        execution_marker = (
            "printf 'BOOT_ID=%s\\n%s\\n' "
            '"$SESSION_BOOT_ID" "$terminal_success" >&"$SESSION_OUTPUT_FD"')
        self.assertEqual(cleanup.count(session_marker), 1)
        self.assertEqual(cleanup.count(execution_marker), 1)
        self.assertLess(cleanup.index('if (( QUARANTINE )); then'),
                        cleanup.index('BOOT_ID_PRODUCER_PHASE="publication_capture"'))
        self.assertLess(cleanup.index('wait "$SESSION_TEE_PID"'),
                        cleanup.index(session_marker))
        self.assertLess(cleanup.index(session_marker), cleanup.index(execution_marker))
        self.assertEqual(source.count("SESSION_TEE_PID=$!"), 1)
        identity_path = "/proc/sys/kernel/random/boot_id"
        self.assertEqual(cleanup.count(identity_path), 1)
        self.assertEqual(source.count(
            "swapz_read_session_boot_id " + identity_path), 2)
        # Only this in-memory test copy redirects the immutable production
        # procfs path. Ownership flags disable every real teardown operation.
        cleanup = cleanup.replace(identity_path, '"$TEST_BOOT_ID_FILE"')
        shell = "set -Eeuo pipefail\n" + reader + "\n" + cleanup + r"""
note() { printf '%s\n' "$*"; }
fail() { printf 'BLOCKED: %s\n' "$*" >&2; exit 1; }
cat() {
    [[ "$1" == /proc/swaps ]] || return 91
    printf 'Filename\tType\tSize\tUsed\tPriority\n'
}
swapz_swap_inventory_identity() { printf 'stable\n'; }
# Delay the fanout deliberately. With stdout redirected to a regular file, a
# helper that fails to join this tee can return before terminal evidence lands.
tee() {
    if [[ "$SCENARIO" == evidence_flush_failure ]]; then
        command cat
        return 23
    fi
    sleep 0.05
    command tee "$@"
    local rc=$?
    if (( rc == 0 )) && [[ "$SCENARIO" == evidence_commit_failure ]]; then
        chmod 400 "$SESSION/session.log"
    fi
    return "$rc"
}
SESSION="$TEST_SESSION_DIR"
SWAPS_ID_BEFORE="stable"
OWN_DM=0
OWN_NULL=0
OWN_MODULE=0
QUARANTINE=0
SUSPENDED=0
MAX_BOUNDARY_PROBE=0
GC_RECOVERY_FAULT_PROBE=0
SESSION_BOOT_ID=""
BOOT_ID_PRODUCER_PHASE="session_capture"
BOOT_ID_PRODUCER_OBSERVED="withheld"
exec {SESSION_OUTPUT_FD}>&1
exec > >(tee -a "$SESSION/session.log" >&"$SESSION_OUTPUT_FD") 2>&1
SESSION_TEE_PID=$!
trap cleanup EXIT
trap 'exit 143' TERM
if [[ "$SCENARIO" == capture_interrupted ]]; then
    kill -TERM "$$"
fi
if ! swapz_read_session_boot_id "$TEST_BOOT_ID_FILE"; then
    BOOT_ID_PRODUCER_OBSERVED="$BOOT_ID_OBSERVED_CATEGORY"
    fail "kernel boot identity unavailable for owned session"
fi
SESSION_BOOT_ID="$BOOT_ID_READ"
BOOT_ID_PRODUCER_PHASE="owned_execution"
BOOT_ID_PRODUCER_OBSERVED="withheld"
case "$SCENARIO" in
    publication_missing) : > "$TEST_BOOT_ID_FILE" ;;
    publication_malformed) printf 'not-a-uuid\n' > "$TEST_BOOT_ID_FILE" ;;
    publication_duplicate)
        printf '%s\n%s\n' "$SESSION_BOOT_ID" "$SESSION_BOOT_ID" > "$TEST_BOOT_ID_FILE" ;;
    stale_boot) printf '%s\n' "$STALE_BOOT_ID" > "$TEST_BOOT_ID_FILE" ;;
    interrupted) kill -TERM "$$" ;;
    unfinished) exit 19 ;;
    quarantine) QUARANTINE=1 ;;
esac
exit 0
"""
        other_boot = "00000000-0000-0000-0000-000000000000"
        scenarios = (
            ("clean", BOOT_ID + "\n", 0, "", "", ""),
            ("capture_missing", "", 1, "session_capture", "missing", "yes"),
            ("capture_malformed", "not-a-uuid\n", 1,
             "session_capture", "malformed", "yes"),
            ("capture_duplicate", BOOT_ID + "\n" + BOOT_ID + "\n",
             1, "session_capture", "duplicate_or_extra", "yes"),
            ("capture_interrupted", BOOT_ID + "\n", 143,
             "session_capture", "withheld", "yes"),
            ("publication_missing", BOOT_ID + "\n", 1,
             "publication_capture", "missing", "yes"),
            ("publication_malformed", BOOT_ID + "\n", 1,
             "publication_capture", "malformed", "yes"),
            ("publication_duplicate", BOOT_ID + "\n", 1,
             "publication_capture", "duplicate_or_extra", "yes"),
            ("stale_boot", BOOT_ID + "\n", 1,
             "publication_match", "different_valid_boot", "yes"),
            ("interrupted", BOOT_ID + "\n", 143,
             "owned_execution", "withheld", "yes"),
            ("unfinished", BOOT_ID + "\n", 19,
             "owned_execution", "withheld", "yes"),
            ("quarantine", BOOT_ID + "\n", 1,
             "teardown", "quarantined", "yes"),
            ("evidence_flush_failure", BOOT_ID + "\n", 1,
             "evidence_flush", "retention_flush_failed", "unknown"),
            ("evidence_commit_failure", BOOT_ID + "\n", 1,
             "evidence_commit", "retention_write_failed", "partial"),
        )
        synthetic_records = "\n".join(
            line for line in GOOD_LOG.splitlines()
            if not line.startswith("BOOT_ID=")
            and not line.startswith("PASS: loaded isolated"))
        for (scenario, initial_identity, expected_exit, phase, category,
             retained_state) in scenarios:
            with self.subTest(scenario=scenario):
                directory = Path(self.temporary_directory.name) / scenario
                directory.mkdir()
                session_directory = directory / "session"
                session_directory.mkdir()
                identity_file = directory / "boot-id"
                identity_file.write_text(initial_identity, encoding="utf-8")
                output_file = directory / "execution.log"
                with output_file.open("w", encoding="utf-8") as output_stream:
                    completed = subprocess.run(
                        ["bash", "-c", shell],
                        env={**os.environ, "SCENARIO": scenario,
                             "TEST_BOOT_ID_FILE": str(identity_file),
                             "TEST_SESSION_DIR": str(session_directory),
                             "STALE_BOOT_ID": other_boot},
                        cwd=directory, stdout=output_stream,
                        stderr=subprocess.STDOUT, text=True,
                        timeout=4, check=False)
                output = output_file.read_text(encoding="utf-8")
                retained_path = session_directory / "session.log"
                retained = (retained_path.read_text(encoding="utf-8")
                            if retained_path.exists() else "")
                self.assertEqual(completed.returncode, expected_exit, output)
                published = [
                    line for line in output.splitlines()
                    if line.startswith("BOOT_ID=")]
                status, reason = self.verify(
                    execution=synthetic_records + "\n" + output)
                if not phase:
                    self.assertEqual(published, [f"BOOT_ID={BOOT_ID}"])
                    self.assertEqual(status, "PASS", reason)
                    self.assertIn("PASS: loaded isolated swapz byte-exact I/O", output)
                    self.assertIn(f"EVIDENCE={session_directory}/session.log", output)
                    self.assertIn(f"BOOT_ID={BOOT_ID}", retained)
                    self.assertIn("PASS: loaded isolated swapz byte-exact I/O", retained)
                    self.assertNotIn("BLOCKED_KERNEL_DEBUG_PRODUCER", output)
                else:
                    self.assertEqual(published, [])
                    self.assertEqual(
                        status,
                        "BLOCKED" if phase in {
                            "teardown", "evidence_flush", "evidence_commit"
                        } else "FAIL",
                        reason)
                    diagnostics = [line for line in output.splitlines()
                                   if line.startswith("BLOCKED_KERNEL_DEBUG_PRODUCER")]
                    self.assertEqual(len(diagnostics), 1, output)
                    expected_marker = (f"BOOT_ID={BOOT_ID}"
                                       if phase != "session_capture"
                                       else "BOOT_ID=<uuid>")
                    self.assertIn(
                        f"phase={phase} expected={expected_marker} "
                        f"observed={category} evidence_retained={retained_state}",
                        diagnostics[0])
                    if retained_state == "yes":
                        self.assertIn(diagnostics[0], retained)
                    else:
                        self.assertNotIn(diagnostics[0], retained)
                    self.assertNotIn(str(session_directory), output)
                    self.assertNotIn(other_boot, output)
                    self.assertNotIn("PASS: loaded isolated", output)

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
        status, reason = self.verify(execution=GOOD_LOG.replace(
            f"SOURCE_HEAD={SOURCE_SHA}", "SOURCE_HEAD=" + "b" * 40))
        self.assertEqual(status, "BLOCKED")
        self.assertIn("source run marker mismatch", reason)

    def test_no_pass_without_required_debug_feature(self) -> None:
        self.configuration.write_text(CONFIG.replace("CONFIG_KASAN=y", "# CONFIG_KASAN is not set"))
        self.assertEqual(self.verify()[0], "BLOCKED")
        self.assertEqual(self.verify(required=())[0], "BLOCKED")

    def test_missing_repeated_or_fabricated_marker_blocks(self) -> None:
        self.assertEqual(self.verify(execution=GOOD_LOG.replace(
            "PASS_LOADED_LIVE_GC=", "SKIPPED="))[0], "BLOCKED")
        self.assertEqual(self.verify(
            execution=GOOD_LOG + "\n" + GOOD_LOG.splitlines()[0])[0], "BLOCKED")
        self.assertEqual(self.verify(execution=GOOD_LOG.replace(
            "active_after:0", "active_after:1"))[0], "BLOCKED")
        self.assertEqual(
            self.verify(execution=GOOD_LOG.replace(
                "segs_gt1:2", "segs_gt1:2 failed:1"))[0],
            "BLOCKED",
        )
        self.assertEqual(
            self.verify(execution=GOOD_LOG.replace(
                "victims:2", "victims:2 contradiction:1"))[0],
            "BLOCKED",
        )
        self.assertEqual(self.verify(
            execution=GOOD_LOG + "\nQUARANTINED: teardown uncertain")[0],
            "BLOCKED")
        self.assertEqual(self.verify(
            execution=GOOD_LOG + "\nBLOCKED: helper precondition unavailable")[0],
            "BLOCKED")

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

    def test_preflight_blocker_never_hides_independent_failure(self) -> None:
        status, reason = self.verify(
            final="old\nBUG: KASAN: synthetic use-after-free\n",
            preflight_block_reason="kernel configuration unreadable: synthetic",
        )
        self.assertEqual(status, "FAIL")
        self.assertIn("KASAN", reason)

        status, reason = self.verify(
            preflight_block_reason="kernel configuration unreadable: synthetic",
        )
        self.assertEqual(status, "BLOCKED")
        self.assertIn("kernel configuration unreadable", reason)

        status, reason = self.verify(
            execution=GOOD_LOG + "\nFAIL: helper detected corruption",
            baseline="", final="", runtime_after="{}",
            preflight_block_reason="running kernel release unavailable",
        )
        self.assertEqual(status, "FAIL")
        self.assertIn("helper defect", reason)
        self.assertNotIn("helper detected corruption", reason)

    def test_cli_malformed_config_does_not_demote_bounded_kernel_failure(self) -> None:
        directory = Path(self.temporary_directory.name)
        malformed_config = directory / "duplicate-config"
        malformed_config.write_text(
            CONFIG + "\nCONFIG_KASAN=y\n", encoding="utf-8")
        baseline = directory / "preflight-baseline"
        final = directory / "preflight-final"
        execution = directory / "preflight-execution"
        runtime_before = directory / "preflight-runtime-before"
        runtime_after = directory / "preflight-runtime-after"
        baseline.write_text("old\n", encoding="utf-8")
        final.write_text(
            "old\nBUG: KASAN: synthetic bounded failure\n",
            encoding="utf-8")
        execution.write_text(GOOD_LOG + "\n", encoding="utf-8")
        required = ("kasan", "lockdep")
        runtime_before.write_text(
            self.runtime_snapshot(required), encoding="utf-8")
        runtime_after.write_text(
            self.runtime_snapshot(required), encoding="utf-8")
        command = [
            sys.executable, "-B", str(SCRIPT), "verify",
            "--config", str(malformed_config),
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
        failed = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=False)
        self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
        self.assertIn("KASAN", failed.stdout)
        self.assertNotIn("synthetic bounded failure", failed.stdout)

        final.write_text("old\nclean\n", encoding="utf-8")
        blocked = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, check=False)
        self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
        self.assertIn("duplicate symbol: CONFIG_KASAN", blocked.stdout)

    def test_verify_cli_preserves_fail_vs_blocked_exit_status(self) -> None:
        directory = Path(self.temporary_directory.name)
        baseline = directory / "baseline"
        final = directory / "final"
        execution = directory / "execution"
        runtime_before = directory / "runtime-before"
        runtime_after = directory / "runtime-after"
        baseline.write_text("old\n", encoding="utf-8")
        cli_log = GOOD_LOG.replace(
            f"RUNNING_KERNEL={KERNEL_RELEASE}",
            f"RUNNING_KERNEL={qualification.running_kernel_release()}",
        )
        execution.write_text(cli_log + "\n", encoding="utf-8")
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

    def test_duplicate_debug_config_symbol_is_ambiguous(self) -> None:
        self.configuration.write_text(
            CONFIG + "\n# CONFIG_KCSAN is not set\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate symbol: CONFIG_KCSAN"):
            qualification.load_config(self.configuration)
        with self.assertRaisesRegex(ValueError, "duplicate symbol: CONFIG_KCSAN"):
            self.features()

    def test_missing_duplicate_and_mismatched_run_markers_identified(self) -> None:
        compound_record = next(
            line for line in GOOD_LOG.splitlines()
            if line.startswith("PASS_LOADED_COMPOUND_BIO="))
        cases = (
            (GOOD_LOG.replace("PASS_LOADED_LIVE_GC=", "SKIPPED="),
             "missing loaded run marker: PASS_LOADED_LIVE_GC"),
            (GOOD_LOG + "\n" + compound_record,
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
                self.assertEqual(status, "BLOCKED")
                self.assertIn(explanation, reason)

    def test_kernel_and_module_hash_markers_bind_execution(self) -> None:
        without_kernel = "\n".join(
            line for line in GOOD_LOG.splitlines()
            if not line.startswith("RUNNING_KERNEL=")) + "\n"
        without_module_hash = "\n".join(
            line for line in GOOD_LOG.splitlines()
            if not line.startswith("MODULE_SHA256=")) + "\n"
        cases = (
            (without_kernel, "missing running-kernel marker"),
            (GOOD_LOG + f"\nRUNNING_KERNEL={KERNEL_RELEASE}",
             "duplicated RUNNING_KERNEL marker"),
            (GOOD_LOG.replace(
                f"RUNNING_KERNEL={KERNEL_RELEASE}",
                "RUNNING_KERNEL=other-kernel"),
             "running-kernel marker mismatch"),
            (without_module_hash, "missing module SHA256 run marker"),
            (GOOD_LOG + f"\nMODULE_SHA256={MODULE_SHA256}  /duplicate/module",
             "duplicated MODULE_SHA256 run marker"),
            (GOOD_LOG.replace(
                f"MODULE_SHA256={MODULE_SHA256}",
                "MODULE_SHA256=broken"),
             "malformed MODULE_SHA256 run marker"),
            (GOOD_LOG.replace(
                f"MODULE_SHA256={MODULE_SHA256}",
                "MODULE_SHA256=" + "b" * 64),
             "module SHA256 mismatch"),
        )
        for execution, explanation in cases:
            with self.subTest(explanation=explanation):
                status, reason = self.verify(execution=execution)
                self.assertEqual(status, "BLOCKED")
                self.assertIn(explanation, reason)

    def test_verified_failure_precedes_incomplete_evidence(self) -> None:
        incomplete = GOOD_LOG.replace("PASS_LOADED_LIVE_GC=", "SKIPPED=")
        status, reason = self.verify(
            execution=incomplete,
            final="old\nBUG: KCSAN: data-race in swapz\n",
        )
        self.assertEqual(status, "FAIL")
        self.assertIn("KCSAN", reason)
        status, reason = self.verify(
            execution=incomplete,
            runtime_after=self.runtime_snapshot(
                ("kasan", "lockdep"), lockdep_debug_locks=False),
        )
        self.assertEqual(status, "FAIL")
        self.assertIn("lockdep debug_locks=0", reason)
        status, reason = self.verify(
            execution=incomplete + "\nBLOCKED: helper uncertainty"
                       "\nFAIL: byte verification failed",
            baseline="", final="", runtime_after="{}",
        )
        self.assertEqual(status, "FAIL")
        self.assertIn("helper defect", reason)
        self.assertNotIn("byte verification failed", reason)

    def test_bounded_fault_diagnostics_and_historical_warning(self) -> None:
        baseline = "WARNING: historical boot warning\nold\n"
        self.assertEqual(self.verify(
            baseline=baseline, final=baseline + "clean\n")[0], "PASS")
        for fault, category in (
            ("BUG: KCSAN: data-race in swapz", "KCSAN"),
            ("possible circular locking dependency detected", "lockdep"),
            ("BUG: KASAN: use-after-free", "KASAN"),
        ):
            with self.subTest(fault=fault):
                status, reason = self.verify(
                    baseline=baseline, final=baseline + fault + "\n")
                self.assertEqual(status, "FAIL")
                self.assertIn(category, reason)
                self.assertNotIn(fault, reason)
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

    def test_private_kernel_text_and_paths_are_not_reported(self) -> None:
        private_detail = "/private/kernel/debug/owner-only-log"
        status, reason = self.verify(
            final=f"old\nWARNING: {private_detail} private diagnostic\n")
        self.assertEqual(status, "FAIL")
        self.assertIn("WARNING", reason)
        self.assertNotIn(private_detail, reason)
        self.assertNotIn("private diagnostic", reason)
        status, reason = self.verify(
            execution=GOOD_LOG + f"\nBLOCKED: {private_detail}")
        self.assertEqual(status, "BLOCKED")
        self.assertNotIn(private_detail, reason)
        missing_module = Path(self.temporary_directory.name) / "private.ko"
        evidence = qualification.inspect_module_provenance(missing_module)
        self.assertNotIn(str(missing_module), evidence["error"])
        with self.assertRaises(ValueError) as failure:
            qualification._read_runtime_text(
                Path(self.temporary_directory.name) / "private-boot-id",
                "kernel boot identity")
        self.assertNotIn(self.temporary_directory.name, str(failure.exception))
        for evidence in (
            GOOD_LOG.replace(f"SOURCE_HEAD={SOURCE_SHA}",
                             f"SOURCE_HEAD={private_detail}"),
            GOOD_LOG.replace(f"RUNNING_KERNEL={KERNEL_RELEASE}",
                             f"RUNNING_KERNEL={private_detail}"),
        ):
            with self.subTest(evidence=evidence.splitlines()[0]):
                status, reason = self.verify(execution=evidence)
                self.assertEqual(status, "BLOCKED")
                self.assertNotIn(private_detail, reason)
        for field, value in (
            ("source_sha", private_detail),
            ("sha256", private_detail),
            ("vermagic", private_detail),
        ):
            with self.subTest(field=field):
                module_evidence = {
                    "source_sha": SOURCE_SHA,
                    "source_clean": "1",
                    "sha256": MODULE_SHA256,
                }
                module_evidence[field] = value
                status, reason = self.verify(module_evidence=module_evidence)
                self.assertEqual(status, "BLOCKED")
                self.assertNotIn(private_detail, reason)
        duplicate_private_key = json.dumps({
            private_detail: 1,
        })[:-1] + f', "{private_detail}": 2}}'
        with self.assertRaises(ValueError) as malformed:
            qualification.parse_runtime_snapshot(
                duplicate_private_key, ("kcsan",))
        self.assertNotIn(private_detail, str(malformed.exception))
        with self.assertRaisesRegex(ValueError, "bounded parser input"):
            qualification.parse_runtime_snapshot(
                " " * (qualification.MAX_RUNTIME_SNAPSHOT_CHARS + 1),
                ("kcsan",))

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
        other_boot_id = "00000000-0000-0000-0000-000000000000"
        state = json.loads(self.runtime_snapshot(required))
        state["boot_id"] = other_boot_id
        status, reason = self.verify(
            required=required, runtime_before=json.dumps(state))
        self.assertEqual(status, "BLOCKED")
        self.assertIn("observed different valid boot ID", reason)
        self.assertNotIn(other_boot_id, reason)
        self.assertIn("next:", reason)

    def test_bad_or_missing_module_provenance_blocks_clean_claim(self) -> None:
        clean = {
            "source_sha": SOURCE_SHA,
            "source_clean": "1",
            "sha256": MODULE_SHA256,
            "vermagic": KERNEL_RELEASE + " SMP preempt mod_unload",
            "symbols": "__asan_load8 __tsan_read8",
        }
        cases = (
            ({"error": "module artifact missing: dm-swapz.ko"},
             "module artifact missing"),
            ({}, "module source SHA mismatch"),
            ({**clean, "source_sha": "b" * 40}, "module source SHA mismatch"),
            ({**clean, "source_clean": "0"}, "clean validated source"),
            ({**clean, "sha256": "b" * 64}, "module SHA256 mismatch"),
            ({**clean, "vermagic": "other-kernel SMP"},
             "module vermagic kernel mismatch"),
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
        module.write_bytes(MODULE_BYTES)
        with mock.patch.object(qualification.shutil, "which", return_value=None):
            self.assertIn("tool unavailable: modinfo",
                          qualification.inspect_module_provenance(module)["error"])
        with mock.patch.object(qualification.shutil, "which", return_value="/usr/bin/tool"), \
             mock.patch.object(qualification.subprocess, "run") as runner:
            runner.side_effect = [
                subprocess.CompletedProcess([], 0, SOURCE_SHA + "\n", ""),
                subprocess.CompletedProcess([], 0, "1\n", ""),
                subprocess.CompletedProcess(
                    [], 0, KERNEL_RELEASE + " SMP preempt mod_unload\n", ""),
                subprocess.CompletedProcess(
                    [], 0, "U __asan_load8\nU __tsan_read8\n", ""),
            ]
            observed = qualification.inspect_module_provenance(module)
            self.assertEqual(observed["source_sha"], SOURCE_SHA)
            self.assertEqual(observed["source_clean"], "1")
            self.assertEqual(observed["sha256"], MODULE_SHA256)
            self.assertEqual(observed["vermagic"].split()[0], KERNEL_RELEASE)
            self.assertIn("__tsan_read8", observed["symbols"])
            self.assertEqual(runner.call_count, 4)
            runner.side_effect = None
            runner.return_value = subprocess.CompletedProcess([], 1, "", "bad")
            self.assertIn("query failed",
                          qualification.inspect_module_provenance(module)["error"])

        valid_queries = [
            subprocess.CompletedProcess([], 0, SOURCE_SHA + "\n", ""),
            subprocess.CompletedProcess([], 0, "1\n", ""),
            subprocess.CompletedProcess(
                [], 0, KERNEL_RELEASE + " SMP preempt mod_unload\n", ""),
            subprocess.CompletedProcess(
                [], 0, "U __asan_load8\nU __tsan_read8\n", ""),
        ]
        with mock.patch.object(
                qualification, "_module_sha256",
                side_effect=[MODULE_SHA256, "b" * 64]), \
             mock.patch.object(
                 qualification.shutil, "which", return_value="/usr/bin/tool"), \
             mock.patch.object(
                 qualification.subprocess, "run",
                 side_effect=valid_queries):
            changed = qualification.inspect_module_provenance(module)
            self.assertIn(
                "changed during provenance inspection", changed["error"])

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

            # An independent Kbuild inventory problem must not hide an actual
            # source diagnostic emitted by this analyzer invocation.
            (headers / ".config").write_text(
                "CONFIG_SMP=y\n", encoding="utf-8")
            runner.return_value = subprocess.CompletedProcess(
                [], 1, "dm-target.c:20:3: warning: incorrect type in argument\n")
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
                "  CHECK /other/build/kernel/w1/dm-target.c\n")), "BLOCKED")
            self.assertEqual(verdict(complete + (
                "  CHECK /repo/build/kernel/w1/predictor-neon.c\n")), "BLOCKED")
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

    def test_contradictory_and_malformed_success_claims_block(self) -> None:
        for execution in (
            GOOD_LOG + "\nSOURCE_HEAD=" + "b" * 40,
            GOOD_LOG + "\nSOURCE_HEAD=broken",
            GOOD_LOG + "\nPASS_LOADED_LIVE_GC=victims:0 verified_pages:0",
            GOOD_LOG + "\nPASS_LOADED_LIVE_GC invalid",
            GOOD_LOG + "\nPASS_LOADED_LIVE_GC_EXTRA=stale",
            GOOD_LOG + "\nPASS: loaded isolated swapz byte-exact I/O, clean teardown",
        ):
            with self.subTest(execution=execution.splitlines()[-1]):
                self.assertEqual(self.verify(execution=execution)[0], "BLOCKED")
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
                        baseline="", final="")[0], "BLOCKED")

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
        root_guard = '(( EUID != 0 )) || fail "invoke from an unprivileged main checkout"'
        self.assertIn(root_guard, source)
        self.assertLess(
            source.index(root_guard),
            source.index('if [[ "${SWAPZ_KERNEL_DEBUG_REPLAY_ONLY:-}"'),
        )
        self.assertNotIn("id -u", source)
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
        self.assertEqual(source.count('note "RUNNING_KERNEL=$(uname -r)"'), 1)
        self.assertEqual(
            source.count('note "MODULE_SHA256=$(sha256sum "$MODULE")"'), 1)
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


    def test_runtime_snapshot_check_blocks_before_helper_admission(self) -> None:
        directory = Path(self.temporary_directory.name)
        boot_id = directory / "boot-id"
        boot_id.write_text("01234567-89ab-cdef-0123-456789abcdef\n")
        snapshot_file = directory / "runtime-before.json"
        snapshot = {
            "schema": qualification.RUNTIME_SCHEMA,
            "required": ["kcsan"],
            "boot_id": boot_id.read_text().strip(),
            "observed_monotonic_ns": time.monotonic_ns(),
            "kcsan_enabled": False,
            "kcsan_filter_default": True,
        }
        snapshot_file.write_text(json.dumps(snapshot))
        argv = [str(SCRIPT), "snapshot-check", "--require", "kcsan",
                "--snapshot", str(snapshot_file)]
        errors = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(qualification, "DEFAULT_BOOT_ID", boot_id), \
             contextlib.redirect_stderr(errors):
            self.assertEqual(qualification.main(), 2)
        self.assertIn("KCSAN debugfs enabled=0", errors.getvalue())
        snapshot["kcsan_enabled"] = True
        snapshot_file.write_text(json.dumps(snapshot))
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(qualification, "DEFAULT_BOOT_ID", boot_id), \
             mock.patch.object(
                 Path, "read_text",
                 side_effect=AssertionError("snapshot-check used unbounded read_text"),
             ):
            self.assertEqual(qualification.main(), 0)

        snapshot_file.write_text(
            " " * (qualification.MAX_RUNTIME_SNAPSHOT_CHARS + 1),
            encoding="utf-8",
        )
        errors = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(qualification, "DEFAULT_BOOT_ID", boot_id), \
             contextlib.redirect_stderr(errors):
            self.assertEqual(qualification.main(), 2)
        self.assertIn("exceeds bounded parser input", errors.getvalue())

    def test_owned_wrapper_rootless_replay_matrix(self) -> None:
        """Exercise the actual Bash control flow with inert commands and bounded children."""
        import os
        import textwrap

        self.assertNotEqual(
            os.geteuid(), 0,
            "ROOTLESS_VALIDATOR_ONLY replay requires an unprivileged EUID",
        )

        # One executable acts as all fake external commands. Only the existing
        # verifier's pure evidence parser is used; no sudo, load, dmesg or
        # device command from the host is ever invoked.
        mock_program = textwrap.dedent(r'''
            import importlib.util
            import json
            import os
            from pathlib import Path
            import signal
            import sys
            import time

            state = Path(os.environ["SWAPZ_REPLAY_STATE"])
            scenario = os.environ["SWAPZ_REPLAY_SCENARIO"]
            source_sha = os.environ["SWAPZ_REPLAY_SOURCE_SHA"]
            module_sha = os.environ["SWAPZ_REPLAY_MODULE_SHA"]
            kernel_release = os.environ["SWAPZ_REPLAY_KERNEL_RELEASE"]
            boot_id = "01234567-89ab-cdef-0123-456789abcdef"
            program = Path(sys.argv[0]).name
            arguments = sys.argv[1:]

            def qualification_module():
                spec = importlib.util.spec_from_file_location(
                    "rootless_kernel_debug_verifier",
                    os.environ["SWAPZ_REPLAY_VERIFIER"])
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.DEFAULT_BOOT_ID = state / "boot-id"
                return module

            if program == "git":
                if arguments[:1] == ["branch"]:
                    print("main")
                elif arguments[:1] == ["rev-parse"]:
                    print(source_sha)
                elif arguments[:1] != ["status"]:
                    sys.exit(97)
            elif program == "make":
                pass
            elif program == "modinfo":
                field = arguments[1]
                if (scenario == "module_source_query_failure" and
                        field == "swapz_build_source_sha"):
                    sys.exit(23)
                if (scenario == "module_clean_query_failure" and
                        field == "swapz_build_source_clean"):
                    sys.exit(25)
                if field == "swapz_build_source_sha":
                    print("b" * 40 if scenario == "wrong_module_build_sha" else source_sha)
                elif field == "swapz_build_source_clean":
                    print("1")
                else:
                    sys.exit(97)
            elif program == "nm":
                if scenario == "instrumentation_query_failure":
                    sys.exit(24)
                print("__asan_load8 __tsan_read8")
            elif program == "sudo":
                if arguments[:2] == ["-n", "true"]:
                    pass
                elif arguments[:2] == ["-n", "dmesg"]:
                    counter = state / "dmesg-count"
                    count = int(counter.read_text()) if counter.exists() else 0
                    counter.write_text(str(count + 1))
                    if scenario == "final_capture_failure" and count:
                        sys.exit(5)
                    if count == 0:
                        print("synthetic baseline")
                    elif scenario == "truncated_dmesg":
                        print("overwritten ring buffer")
                    else:
                        print("synthetic baseline")
                        if scenario in {"lockdep_splat", "lockdep_with_preflight_gap"}:
                            print("WARNING: possible circular locking dependency detected")
                        elif scenario == "kasan_report":
                            print("BUG: KASAN: synthetic use-after-free")
                        else:
                            print("synthetic normal completion")
                elif arguments[:3] == ["-n", "python3", "-B"]:
                    if scenario == "runtime_snapshot_failure":
                        sys.exit(19)
                    required = arguments[arguments.index("--require") + 1].split(",")
                    snapshot = {
                        "schema": "swapz-kernel-debug-runtime-v2",
                        "required": required,
                        "boot_id": boot_id,
                        "observed_monotonic_ns": time.monotonic_ns(),
                    }
                    if "kcsan" in required:
                        snapshot.update(kcsan_enabled=(
                            scenario != "kcsan_disabled_runtime"),
                            kcsan_filter_default=True)
                    if "lockdep" in required:
                        snapshot.update(lockdep_debug_locks=True,
                                        lockdep_prove_locking=True)
                    count_file = state / "runtime-count"
                    count = int(count_file.read_text()) if count_file.exists() else 0
                    count_file.write_text(str(count + 1))
                    if scenario == "changed_boot_id" and count:
                        snapshot["boot_id"] = "00000000-0000-0000-0000-000000000000"
                    print(json.dumps(snapshot))
                elif arguments[:2] == ["-n", "bash"]:
                    (state / "helper.pid").write_text(str(os.getpid()))
                    if scenario == "timeout":
                        time.sleep(10)
                    elif scenario == "abnormal_child_exit":
                        os.kill(os.getpid(), signal.SIGKILL)
                    elif scenario == "helper_failure":
                        sys.exit(17)
                    else:
                        execution = (state / "good.log").read_text()
                        if scenario == "missing_run_marker":
                            execution = execution.replace(
                                "PASS_LOADED_LIVE_GC=", "SKIPPED_LIVE_GC=")
                        if scenario == "changed_execution_boot":
                            execution = execution.replace(
                                f"BOOT_ID={boot_id}",
                                "BOOT_ID=00000000-0000-0000-0000-000000000000",
                            )
                        print(execution, end="")
                else:
                    sys.exit(98)
            elif program == "python3":
                if arguments[:1] == ["-B"]:
                    arguments = arguments[1:]
                action = arguments[1]
                qualifier = qualification_module()
                required_names = arguments[arguments.index("--require") + 1]
                required = qualifier.required_features(required_names)
                config = state / "config"
                cmdline = state / "cmdline"
                features = qualifier.probe(config, cmdline)
                if action == "probe":
                    print("KERNEL_DEBUG_PROBE=" + json.dumps(features, sort_keys=True))
                    sys.exit(0 if qualifier.check_features(features, required) else 2)
                if action == "snapshot-check":
                    observed = Path(arguments[arguments.index("--snapshot") + 1])
                    snapshot = qualifier.parse_runtime_snapshot(
                        observed.read_text(), required)
                    inactive = qualifier.inactive_runtime_reason(snapshot, required)
                    if inactive:
                        print("BLOCKED_KERNEL_DEBUG_RUNTIME: " + inactive,
                              file=sys.stderr)
                        sys.exit(2)
                    sys.exit(0)
                if action != "verify":
                    sys.exit(99)
                def read_argument(flag):
                    return Path(arguments[arguments.index(flag) + 1]).read_text()
                module_evidence = {
                    "source_sha": source_sha,
                    "source_clean": "1",
                    "sha256": "b" * 64 if scenario == "module_hash_mismatch" else module_sha,
                    "vermagic": kernel_release + " SMP",
                    "symbols": "__asan_load8 __tsan_read8",
                }
                preflight_gap = (
                    "running kernel config unavailable (synthetic)"
                    if scenario == "lockdep_with_preflight_gap" else None)
                status, reason = qualifier.verify_owned_run(
                    required, features,
                    read_argument("--baseline"), read_argument("--final"),
                    read_argument("--execution"), read_argument("--runtime-before"),
                    read_argument("--runtime-after"), source_sha,
                    module_evidence=module_evidence,
                    configuration=qualifier.load_config(config),
                    kernel_release=kernel_release,
                    preflight_block_reason=preflight_gap,
                )
                print(f"{status}_KERNEL_DEBUG_OWNED=features:{required_names} reason:{reason}")
                sys.exit({"PASS": 0, "FAIL": 1, "BLOCKED": 2}[status])
            else:
                sys.exit(99)
        ''').lstrip()

        cases = (
            ("missing_kconfig_option", "kasan-lockdep", 2, "kasan"),
            ("kcsan_unavailable_config", "kcsan", 2, "kcsan"),
            ("kcsan_disabled_runtime", "kcsan", 2, "KCSAN"),
            ("lockdep_splat", "kasan-lockdep", 1, "kernel diagnostic in bounded dmesg: lockdep"),
            ("kasan_report", "kasan-lockdep", 1, "KASAN"),
            ("helper_failure", "kasan-lockdep", 1, "helper exit=17"),
            ("runtime_snapshot_failure", "kasan-lockdep", 2, "exit=19"),
            ("final_capture_failure", "kasan-lockdep", 2, "exit=5"),
            ("wrong_module_build_sha", "kasan-lockdep", 2, "module build source"),
            ("module_source_query_failure", "kasan-lockdep", 2, "module build source metadata query failed (exit=23)"),
            ("module_clean_query_failure", "kasan-lockdep", 2, "module clean-source metadata query failed (exit=25)"),
            ("instrumentation_query_failure", "kasan-lockdep", 2, "module kasan-lockdep instrumentation query failed (exit=24)"),
            ("module_hash_mismatch", "kasan-lockdep", 2, "module SHA256 mismatch"),
            ("changed_boot_id", "kasan-lockdep", 2, "runtime-after boot mismatch"),
            ("changed_execution_boot", "kasan-lockdep", 2,
             "execution boot marker mismatch"),
            ("truncated_dmesg", "kasan-lockdep", 2, "dmesg truncated"),
            ("missing_run_marker", "kasan-lockdep", 2, "missing loaded run marker"),
            ("timeout", "kasan-lockdep", 1, "helper exit=124"),
            ("abnormal_child_exit", "kasan-lockdep", 1, "helper exit=137"),
            ("lockdep_with_preflight_gap", "kasan-lockdep", 1, "kernel diagnostic in bounded dmesg: lockdep"),
            ("clean", "kasan-lockdep", 0, "ROOTLESS_VALIDATOR_ONLY=PASS"),
            ("clean_kcsan", "kcsan", 0, "ROOTLESS_VALIDATOR_ONLY=PASS"),
        )
        for scenario, lane, expected_exit, expected_message in cases:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as root:
                directory = Path(root)
                fake_bin = directory / "bin"
                fake_bin.mkdir()
                (fake_bin / "ROOTLESS_VALIDATOR_ONLY").write_text("no host commands\n")
                program = fake_bin / "fake-command"
                program.write_text(f"#!{sys.executable}\n" + mock_program,
                                   encoding="utf-8")
                program.chmod(0o755)
                for name in ("sudo", "python3", "git", "make", "modinfo", "nm"):
                    (fake_bin / name).symlink_to(program.name)
                (directory / "build/tests").mkdir(parents=True)
                replay_boot_id = "01234567-89ab-cdef-0123-456789abcdef"
                (directory / "boot-id").write_text(replay_boot_id + "\n")
                replay_log = GOOD_LOG.replace(
                    f"BOOT_ID={BOOT_ID}", f"BOOT_ID={replay_boot_id}")
                configuration = CONFIG
                if scenario == "missing_kconfig_option":
                    configuration = configuration.replace("CONFIG_KASAN=y\n", "")
                if scenario == "kcsan_unavailable_config":
                    configuration = configuration.replace(
                        "CONFIG_KCSAN=y", "# CONFIG_KCSAN is not set")
                (directory / "config").write_text(configuration)
                (directory / "cmdline").write_text("quiet\n")
                (directory / "good.log").write_text(replay_log)
                environment = {
                    **os.environ,
                    "PATH": str(fake_bin) + os.pathsep + os.defpath,
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "SWAPZ_KERNEL_DEBUG_REPLAY_ONLY": "ROOTLESS_VALIDATOR_ONLY",
                    "SWAPZ_KERNEL_DEBUG_REPLAY_BIN": str(fake_bin),
                    "SWAPZ_DEBUG_OWNED_COORDINATED": "YES_OWNED_NULLBLK_ONLY",
                    "SWAPZ_REPLAY_STATE": str(directory),
                    "SWAPZ_REPLAY_SCENARIO": scenario,
                    "SWAPZ_REPLAY_SOURCE_SHA": SOURCE_SHA,
                    "SWAPZ_REPLAY_MODULE_SHA": MODULE_SHA256,
                    "SWAPZ_REPLAY_KERNEL_RELEASE": KERNEL_RELEASE,
                    "SWAPZ_REPLAY_VERIFIER": str(SCRIPT),
                }
                completed = subprocess.run(
                    ["bash", str(WRAPPER), "--validated-source", SOURCE_SHA,
                     "--lane", lane],
                    cwd=directory, env=environment, capture_output=True,
                    text=True, timeout=8, check=False)
                output = completed.stdout + completed.stderr
                self.assertEqual(completed.returncode, expected_exit, output)
                self.assertIn(expected_message, output)
                self.assertIn("ROOTLESS_VALIDATOR_ONLY=ACTIVE", output)
                self.assertIn("LOADED_HOST_CHECKLIST", output)
                self.assertIn("boot_id=pre/post-same-boot", output)
                self.assertIn("SOURCE_HEAD,RUNNING_KERNEL,MODULE_SHA256", output)
                self.assertNotIn("LOADED_KERNEL_PASS=PASS", output)
                self.assertNotIn("PASS_KERNEL_DEBUG_OWNED=", output)
                self.assertNotIn(str(directory), output)
                helper_pid = directory / "helper.pid"
                preflight_cases = {
                    "missing_kconfig_option", "kcsan_unavailable_config",
                    "kcsan_disabled_runtime", "runtime_snapshot_failure",
                    "wrong_module_build_sha", "module_source_query_failure",
                    "module_clean_query_failure", "instrumentation_query_failure",
                }
                self.assertEqual(helper_pid.exists(),
                                 scenario not in preflight_cases)
                if helper_pid.exists():
                    pid = int(helper_pid.read_text())
                    # timeout must reap the mocked sudo child, even when it
                    # is terminated by a signal rather than exiting normally.
                    for _ in range(40):
                        try:
                            os.kill(pid, 0)
                        except ProcessLookupError:
                            break
                        time.sleep(0.01)
                    else:
                        self.fail(f"unreaped replay child for {scenario}")
            self.assertFalse(Path(root).exists(), "replay evidence not cleaned")


if __name__ == "__main__":
    unittest.main()
