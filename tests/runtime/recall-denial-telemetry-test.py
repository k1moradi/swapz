#!/usr/bin/env python3
"""Adversarial offline telemetry qualification; no live device or worker I/O."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "swapz_recall_denial_telemetry", HERE / "recall-denial-telemetry.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load offline telemetry analyzer")
analyzer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = analyzer
SPEC.loader.exec_module(analyzer)
REVISION = "a" * 40


def denied_session(session_id="session-01", *, role="writer", phase="READY",
                   status="launch_failure", error="READY handshake was unconfirmed"):
    return {
        "schema": analyzer.SCHEMA,
        "source_revision": REVISION,
        "session_id": session_id,
        "role": role,
        "phase": phase,
        "status": status,
        "error": error,
        "service_returncode": None,
        "preserve_backing": True,
        "cleanup_allowed": False,
    }


def rows_bytes(*rows):
    return b"".join(json.dumps(row, separators=(",", ":")).encode() + b"\n" for row in rows)


class RecallDenialTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.item = denied_session()
        self.temporary = tempfile.TemporaryDirectory(prefix="swapz-recall-denial-")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "synthetic-denials.jsonl"

    def reject(self, expected):
        with self.assertRaisesRegex(analyzer.TelemetryDenied, expected):
            analyzer.analyze(rows_bytes(self.item))

    def test_positive_ready_denial(self):
        report = analyzer.analyze(rows_bytes(self.item))
        self.assertEqual(report["denied_session_count"], 1)
        self.assertEqual(report["categories"], {"ready_confirmation_denial": 1})
        self.assertEqual(report["source_revision"], REVISION)
        self.assertFalse(report["cleanup_authorized"])
        self.assertFalse(report["backing_release_authorized"])
        self.assertFalse(report["kernel_drain_proved"])
        self.assertFalse(report["production_qualified"])
        self.assertEqual(report["v22_strategy_and_batch_winner"], "UNDETERMINED")

    def test_all_typed_denial_categories(self):
        cases = (
            ("LAUNCH", "writer", "launch_admission_denial"),
            ("READY", "a", "ready_confirmation_denial"),
            ("WAIT", "a2", "wait_or_reap_denial"),
            ("READBACK", "b", "readback_other_denial"),
            ("WRITER_READY", "writer", "synthetic_writer_readiness_denial"),
            ("CHANNEL", None, "channel_or_service_denial"),
            ("PIDFD", None, "pidfd_ownership_denial"),
            ("FINALIZE", None, "finalization_denial"),
            ("STOP", None, "stop_or_reap_denial"),
        )
        for index, (phase, role, category) in enumerate(cases):
            with self.subTest(phase=phase):
                row = denied_session(f"s{index}", role=role, phase=phase)
                report = analyzer.analyze(rows_bytes(row))
                self.assertEqual(report["sessions"][0]["category"], category)

    def test_known_pinned_readback_mismatch_is_distinguished(self):
        for error in ("pinned readback rejected: byte mismatch",
                      "pinned readback does not match trusted 4096-byte page",
                      "readback attestation digest does not match immutable reference"):
            with self.subTest(error=error):
                row = denied_session(phase="READBACK", role="a", error=error)
                self.assertEqual(analyzer.analyze(rows_bytes(row))["categories"],
                                 {"readback_integrity_denial": 1})

    def test_error_text_does_not_reclassify_non_readback_phases(self):
        self.item["error"] = "pinned readback rejected: forged wording"
        self.assertEqual(analyzer.analyze(rows_bytes(self.item))["categories"],
                         {"ready_confirmation_denial": 1})

    def test_deterministic_category_summary_and_session_order(self):
        other = denied_session("session-00", role="b", phase="WAIT")
        a = analyzer.analyze(rows_bytes(self.item, other))
        b = analyzer.analyze(rows_bytes(other, self.item))
        self.assertEqual(a["categories"], b["categories"])
        self.assertEqual(a["sessions"], b["sessions"])
        self.assertNotEqual(a["observations_sha256"], b["observations_sha256"])

    def test_unrecognized_error_keeps_negative_permission(self):
        self.item["error"] = "completely new failure reason"
        report = analyzer.analyze(rows_bytes(self.item))
        self.assertFalse(report["cleanup_authorized"])
        self.assertFalse(report["source_authenticated"])

    def test_denied_with_zero_service_returncode_does_not_become_success(self):
        self.item["service_returncode"] = 0
        self.assertEqual(analyzer.analyze(rows_bytes(self.item))["denied_session_count"], 1)

    def test_reject_early_or_positive_ready_status(self):
        self.item["status"] = "ready"
        self.reject("success/unknown")

    def test_reject_successful_reap_status(self):
        self.item["status"] = "reaped"
        self.reject("success/unknown")

    def test_reject_positive_cleanup_assertion(self):
        self.item["cleanup_allowed"] = True
        self.reject("positive or contradictory")

    def test_reject_false_preserve_flag(self):
        self.item["preserve_backing"] = False
        self.reject("positive or contradictory")

    def test_reject_non_boolean_verdict(self):
        self.item["preserve_backing"] = "True"
        self.reject("positive or contradictory")

    def test_reject_unknown_role(self):
        self.item["role"] = "admin"
        self.reject("unknown failure role")

    def test_reject_missing_worker_role(self):
        self.item["role"] = None
        self.reject("missing bound worker role")

    def test_reject_wrong_writer_readiness_role(self):
        self.item["phase"] = "WRITER_READY"
        self.item["role"] = "a2"
        self.reject("different role")

    def test_reject_writer_readback_receipt(self):
        self.item["phase"] = "READBACK"
        self.reject("writer cannot supply")

    def test_reject_unknown_phase(self):
        self.item["phase"] = "CLEANUP"
        self.reject("unknown failure phase")

    def test_reject_extra_authorization_field(self):
        self.item["kernel_drain_proved"] = True
        self.reject("unexpected or missing")

    def test_reject_missing_error(self):
        del self.item["error"]
        self.reject("unexpected or missing")

    def test_reject_empty_or_oversized_error(self):
        for value in ("", "x" * 257):
            with self.subTest(length=len(value)):
                self.item["error"] = value
                self.reject("oversized or control-character")

    def test_reject_control_characters(self):
        for value in ("failure\nboom", "failure\tboom", "failure\x7fboom"):
            with self.subTest(repr=repr(value)):
                self.item["error"] = value
                self.reject("control-character")

    def test_reject_noncanonical_revision(self):
        self.item["source_revision"] = "A" * 40
        self.reject("invalid exact source revision")

    def test_reject_invalid_session_identifier(self):
        self.item["session_id"] = "../unsafe"
        self.reject("invalid session identifier")

    def test_reject_boolean_service_returncode(self):
        self.item["service_returncode"] = True
        self.reject("malformed service exit code")

    def test_reject_oversized_service_returncode(self):
        self.item["service_returncode"] = 9999
        self.reject("malformed service exit code")

    def test_reject_duplicate_session(self):
        with self.assertRaisesRegex(analyzer.TelemetryDenied, "duplicate or replayed"):
            analyzer.analyze(rows_bytes(self.item, self.item))

    def test_reject_mixed_revision(self):
        other = denied_session("session-02")
        other["source_revision"] = "b" * 40
        with self.assertRaisesRegex(analyzer.TelemetryDenied, "mixed executable"):
            analyzer.analyze(rows_bytes(self.item, other))

    def test_reject_missing_terminal_lf(self):
        with self.assertRaisesRegex(analyzer.TelemetryDenied, "LF-terminated"):
            analyzer.analyze(rows_bytes(self.item)[:-1])

    def test_reject_empty_line(self):
        with self.assertRaisesRegex(analyzer.TelemetryDenied, "empty lines"):
            analyzer.analyze(rows_bytes(self.item) + b"\n")

    def test_reject_CRLF(self):
        with self.assertRaisesRegex(analyzer.TelemetryDenied, "no CR"):
            analyzer.analyze(rows_bytes(self.item).replace(b"\n", b"\r\n"))

    def test_reject_duplicate_json_keys(self):
        data = rows_bytes(self.item).replace(b'"error":', b'"error":"fake","error":', 1)
        with self.assertRaisesRegex(analyzer.TelemetryDenied, "duplicate JSON field"):
            analyzer.analyze(data)

    def test_reject_nonfinite_json(self):
        data = rows_bytes(self.item).replace(b'"service_returncode":null', b'"service_returncode":NaN')
        with self.assertRaisesRegex(analyzer.TelemetryDenied, "nonfinite"):
            analyzer.analyze(data)

    def test_reject_more_than_max_records(self):
        with self.assertRaisesRegex(analyzer.TelemetryDenied, "invalid diagnostic count"):
            analyzer.analyze(b"{}\n" * (analyzer.MAX_RECORDS + 1))

    def test_reject_input_larger_than_byte_cap(self):
        with self.assertRaisesRegex(analyzer.TelemetryDenied, "bounded diagnostic"):
            analyzer.analyze(b"a" * (analyzer.MAX_INPUT_BYTES + 1))

    def test_read_regular_file_and_hash_exact_original_bytes(self):
        data = rows_bytes(self.item)
        self.path.write_bytes(data)
        report = analyzer.analyze(analyzer.read_observations(self.path))
        self.assertEqual(report["observations_sha256"], __import__("hashlib").sha256(data).hexdigest())

    def test_reject_symlink_input(self):
        original = Path(self.temporary.name) / "original.jsonl"
        original.write_bytes(rows_bytes(self.item))
        self.path.symlink_to(original)
        with self.assertRaises(OSError):
            analyzer.read_observations(self.path)

    def test_reject_hardlink_input(self):
        original = Path(self.temporary.name) / "original.jsonl"
        original.write_bytes(rows_bytes(self.item))
        os.link(original, self.path)
        with self.assertRaisesRegex(analyzer.TelemetryDenied, "singly-linked"):
            analyzer.read_observations(self.path)

    def test_reject_directory(self):
        with self.assertRaisesRegex(analyzer.TelemetryDenied, "regular file"):
            analyzer.read_observations(Path(self.temporary.name))

    def test_cli_succeeds_with_negative_authorization_only(self):
        self.path.write_bytes(rows_bytes(self.item))
        process = subprocess.run((sys.executable, "-B", str(HERE / "recall-denial-telemetry.py"),
                                  "--observations", str(self.path)), check=False,
                                 capture_output=True, text=True, timeout=4)
        self.assertEqual(process.returncode, 0, process.stderr)
        report = json.loads(process.stdout)
        self.assertFalse(report["backing_release_authorized"])
        self.assertFalse(report["cleanup_authorized"])
        self.assertFalse(report["kernel_drain_proved"])

    def test_cli_does_not_emit_positive_output_on_error(self):
        self.path.write_bytes(b'{"schema":"invalid"}\n')
        process = subprocess.run((sys.executable, "-B", str(HERE / "recall-denial-telemetry.py"),
                                  "--observations", str(self.path)), check=False,
                                 capture_output=True, text=True, timeout=4)
        self.assertEqual(process.returncode, 1)
        self.assertEqual(process.stdout, "")
        self.assertIn("ROOTLESS_RECALL_TELEMETRY_DENIED:", process.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
