#!/usr/bin/env python3
"""Rootless adversarial verification for V3 binary-sidecar bundle consistency."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "swapz_v3_bundle_tests", HERE / "v22-evidence-bundle-v3.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("offline V3 bundle verifier missing")
bundle = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bundle
SPEC.loader.exec_module(bundle)
PAIR = struct.Struct("!QQ")
REVISION = "a" * 40


def row_for(run_id: str, evidence: str = "synthetic", schema: str | None = None) -> dict:
    return {
        "schema": schema or bundle.plateau.SCHEMA_V3,
        "evidence": evidence,
        "backend": "test-backend", "profile": "test-profile",
        "strategy": "staged", "batch_kib": 64,
        "run_id": run_id, "source_revision": REVISION,
        "clock": "monotonic", "duration_ns": 1_000_000_000,
        "lower_write_sectors_before": 5000,
        "lower_write_sectors_after": 45000,
        "lower_write_ios_before": 100, "lower_write_ios_after": 150,
        "logical_write_bytes": 64 * 1024 * 1024,
        "read_count": 10000, "read_p99_ns": 1000000,
        "integrity_ok": True, "quiescence_ok": True,
        "flush_ok": True, "all_reaped": True,
        "source_kind": "lower-device-counters",
    }


def manifest_for(rows: list[dict], observation_bytes: bytes, evidence: str = "synthetic") -> dict:
    manifest = {
        "schema": bundle.SCHEMA, "source_revision": REVISION,
        "session_id": "synthetic-session",
        "collector_id": "untrusted-test-collector",
        "lower_device_id": "test-device-253:9",
        "backend": "test-backend", "profile": "test-profile", "evidence": evidence,
        "observations_sha256": hashlib.sha256(observation_bytes).hexdigest(), "runs": [],
    }
    for original, row in zip(observation_bytes.splitlines(keepends=True), rows):
        manifest["runs"].append({
            "run_id": row["run_id"], "line_sha256": hashlib.sha256(original).hexdigest(),
            **{key: manifest[key] for key in bundle.legacy.BINDINGS},
            "read_latency_sidecar": row["read_latency_sidecar"],
            "read_latency_sha256": row["read_latency_sha256"],
            "read_latency_bytes": (Path(_fixture_folder) / row["read_latency_sidecar"]).stat().st_size,
        })
    return manifest


_fixture_folder = ""


class V3BundleTests(unittest.TestCase):
    def setUp(self):
        global _fixture_folder
        temp = tempfile.TemporaryDirectory(prefix="swapz-v3-bundle-")
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        _fixture_folder = str(self.directory)
        self.observations = self.directory / "observations.jsonl"
        self.manifest_file = self.directory / "manifest.json"
        self.rows = [row_for("run-a"), row_for("run-b")]
        for row in self.rows:
            self.sidecar(row, [(1000000, 10000)])
        self.refresh()

    def sidecar(self, row, values, *, label: str | None = None) -> Path:
        raw = b"".join(PAIR.pack(latency, count) for latency, count in values)
        label = label or row["run_id"] + ".latbin"
        path = self.directory / label
        path.write_bytes(raw)
        row["read_latency_sidecar"] = label
        row["read_latency_sha256"] = hashlib.sha256(raw).hexdigest()
        row["read_count"] = sum(count for _latency, count in values)
        rank = (99 * row["read_count"] + 99) // 100
        cumulative = 0
        for latency, count in values:
            cumulative += count
            if cumulative >= rank:
                row["read_p99_ns"] = latency
                break
        return path

    def refresh(self):
        self.observations.write_bytes(b"".join(
            (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
            for row in self.rows
        ))
        raw = self.observations.read_bytes()
        self.manifest = manifest_for(self.rows, raw)
        self.write_manifest()

    def write_manifest(self):
        self.manifest_file.write_text(
            json.dumps(self.manifest, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    def check(self):
        self.write_manifest()
        return bundle.check_paths(self.observations, self.manifest_file)

    def rejects(self, pattern: str):
        with self.assertRaisesRegex((ValueError, OSError), pattern):
            self.check()

    def test_two_run_bundle_binds_original_jsonl_and_sidecar_bytes(self):
        result = self.check()
        self.assertEqual(result["observation_count"], 2)
        self.assertEqual(result["sidecar_bytes_verified"], 32)
        self.assertEqual(result["source_revision"], REVISION)
        self.assertEqual(result["schema"], bundle.REPORT_SCHEMA)
        self.assertEqual({r["read_count_verified"] for r in result["runs"]}, {10000})

    def test_all_qualification_flags_remain_false(self):
        report = self.check()
        for name in ("authenticated_collector", "independent_device_identity_proved",
                     "kernel_drain_proved", "physical_selection_authorized",
                     "backing_release_authorized", "production_qualified"):
            self.assertIs(report[name], False)
        self.assertEqual(report["v22_strategy_and_batch_winner"], "UNDETERMINED")

    def test_physical_label_is_not_authentication(self):
        self.rows = [row_for("run-physical", evidence="physical")]
        self.sidecar(self.rows[0], [(1000000, 10000)])
        self.refresh()
        self.manifest["evidence"] = "physical"
        self.manifest["runs"][0]["evidence"] = "physical"
        report = self.check()
        self.assertEqual(report["evidence"], "physical")
        self.assertFalse(report["physical_selection_authorized"])
        self.assertFalse(report["authenticated_collector"])

    def test_10000_distinct_exact_timestamps_and_p99(self):
        row = self.rows[0]
        self.sidecar(row, [(value, 1) for value in range(1, 10001)])
        self.refresh()
        report = self.check()
        self.assertEqual(report["runs"][0]["exact_p99_ns_verified"], 9900)
        self.assertEqual(report["runs"][0]["read_latency_bytes"], 160000)

    def test_equal_values_as_exact_rle_and_p99_boundary(self):
        self.sidecar(self.rows[0], [(10, 9900), (20, 100)])
        self.refresh()
        self.assertEqual(self.check()["runs"][0]["exact_p99_ns_verified"], 10)

    def test_reject_wrong_sidecar_contents_even_if_metadata_not_changed(self):
        (self.directory / self.rows[0]["read_latency_sidecar"]).write_bytes(PAIR.pack(1000001, 10000))
        self.rejects("p99 mismatch|SHA-256 mismatch")

    def test_reject_wrong_digest_claim(self):
        self.manifest["runs"][0]["read_latency_sha256"] = "0" * 64
        self.rejects("digest binding mismatch")

    def test_reject_wrong_sidecar_size_claim(self):
        self.manifest["runs"][0]["read_latency_bytes"] += 16
        self.rejects("byte-length binding mismatch")

    def test_reject_boolean_size_claim(self):
        self.manifest["runs"][0]["read_latency_bytes"] = True
        self.rejects("invalid sidecar byte-length claim")

    def test_reject_missing_sidecar_claim(self):
        del self.manifest["runs"][0]["read_latency_bytes"]
        self.rejects("invalid V3 sidecar manifest fields")

    def test_reject_extra_run_authorization_claim(self):
        self.manifest["runs"][0]["cleanup_allowed"] = True
        self.rejects("invalid V3 sidecar manifest fields")

    def test_reject_extra_top_level_authorization_claim(self):
        self.manifest["production_qualified"] = True
        self.rejects("missing or extra fields")

    def test_reject_sidecar_substitution_even_with_valid_existing_file(self):
        self.manifest["runs"][0]["read_latency_sidecar"] = self.rows[1]["read_latency_sidecar"]
        self.rejects("sidecar filename or digest binding mismatch")

    def test_reject_duplicate_sidecar_between_distinct_runs(self):
        self.rows[1]["read_latency_sidecar"] = self.rows[0]["read_latency_sidecar"]
        self.rows[1]["read_latency_sha256"] = self.rows[0]["read_latency_sha256"]
        self.refresh()
        self.rejects("sidecar filename reused")

    def test_reject_different_source_revision(self):
        self.rows[1]["source_revision"] = "b" * 40
        self.refresh()
        self.rejects("row contradicts source_revision")

    def test_reject_different_manifest_run_session(self):
        self.manifest["runs"][1]["session_id"] = "another-session"
        self.rejects("conflicting session_id")

    def test_reject_different_claimed_collector(self):
        self.manifest["runs"][1]["collector_id"] = "unexpected-collector"
        self.rejects("conflicting collector_id")

    def test_reject_different_claimed_lower_device(self):
        self.manifest["runs"][0]["lower_device_id"] = "unrelated-device"
        self.rejects("conflicting lower_device_id")

    def test_reject_wrong_claimed_backend(self):
        self.manifest["runs"][1]["backend"] = "mismatched-backend"
        self.rejects("conflicting backend")

    def test_reject_wrong_claimed_evidence_class(self):
        self.manifest["runs"][1]["evidence"] = "kernel"
        self.rejects("conflicting evidence")

    def test_reject_reordered_manifest_run_entries(self):
        self.manifest["runs"].reverse()
        self.rejects("row contradicts run_id")

    def test_reject_duplicate_run_ids(self):
        self.rows[1]["run_id"] = self.rows[0]["run_id"]
        self.refresh()
        self.rejects("repeated run identity")

    def test_reject_modified_jsonl_without_manifest_rehash(self):
        self.observations.write_bytes(self.observations.read_bytes() + b" ")
        self.rejects("observation bytes do not match manifest SHA-256")

    def test_reject_wrong_observation_line_digest(self):
        self.manifest["runs"][0]["line_sha256"] = "0" * 64
        self.rejects("original record SHA-256 mismatch")

    def test_reject_duplicate_JSON_keys_in_manifest(self):
        self.write_manifest()
        raw = self.manifest_file.read_bytes()
        self.manifest_file.write_bytes(raw.replace(b'"schema":', b'"schema":"bogus","schema":', 1))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            bundle.check_paths(self.observations, self.manifest_file)

    def test_reject_nan_in_manifest(self):
        self.write_manifest()
        raw = self.manifest_file.read_bytes()
        self.manifest_file.write_bytes(raw.replace(b'"schema":', b'"unused":NaN,"schema":', 1))
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            bundle.check_paths(self.observations, self.manifest_file)

    def test_reject_duplicate_JSON_keys_in_observations(self):
        raw = self.observations.read_bytes()
        self.observations.write_bytes(raw.replace(b'"schema":', b'"schema":"duplicate","schema":', 1))
        self.manifest["observations_sha256"] = hashlib.sha256(self.observations.read_bytes()).hexdigest()
        self.rejects("duplicate")

    def test_reject_legacy_bundle_schema(self):
        self.manifest["schema"] = bundle.legacy.SCHEMA
        self.rejects("unsupported V3 bundle schema")

    def test_reject_legacy_V2_observation_in_V3_bundle(self):
        row = self.rows[0]
        row["schema"] = bundle.plateau.SCHEMA_V2
        row["read_latency_counts"] = [[1000000, 10000]]
        del row["read_latency_sidecar"]
        del row["read_latency_sha256"]
        # Rehash the observations and manifest, retaining stale entry fields,
        # to verify the format gate rather than a hash mismatch.
        self.observations.write_bytes(b"".join(
            (json.dumps(x, sort_keys=True, separators=(",", ":")) + "\n").encode()
            for x in self.rows
        ))
        raw = self.observations.read_bytes()
        self.manifest["observations_sha256"] = hashlib.sha256(raw).hexdigest()
        self.manifest["runs"][0]["line_sha256"] = hashlib.sha256(raw.splitlines(keepends=True)[0]).hexdigest()
        self.rejects("V3 sidecar evidence is mandatory")

    def test_reject_symlink_to_sidecar(self):
        target = self.directory / self.rows[0]["read_latency_sidecar"]
        actual = self.directory / "actual.latbin"
        target.rename(actual)
        target.symlink_to(actual)
        self.rejects("cannot be pinned")

    def test_reject_hardlinked_sidecar(self):
        path = self.directory / self.rows[0]["read_latency_sidecar"]
        os.link(path, self.directory / "hardlink.latbin")
        self.rejects("singly-linked regular file")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX FIFO")
    def test_reject_fifo_sidecar_without_blocking(self):
        path = self.directory / self.rows[0]["read_latency_sidecar"]
        path.unlink()
        os.mkfifo(path, 0o600)
        self.rejects("singly-linked regular file")

    def test_reject_symlinked_manifest(self):
        real = self.directory / "manifest-data.json"
        self.manifest_file.rename(real)
        self.manifest_file.symlink_to(real)
        with self.assertRaisesRegex(ValueError, "cannot be pinned"):
            bundle.check_paths(self.observations, self.manifest_file)

    def test_reject_hardlinked_observation(self):
        os.link(self.observations, self.directory / "observations-alias.jsonl")
        self.rejects("singly-linked regular")

    def test_reject_distinct_manifest_directory(self):
        with tempfile.TemporaryDirectory() as other:
            path = Path(other) / "manifest.json"
            path.write_text(json.dumps(self.manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "share an exact directory"):
                bundle.check_paths(self.observations, path)

    def test_reject_reused_observation_and_manifest_name(self):
        with self.assertRaisesRegex(ValueError, "different files"):
            bundle.check_paths(self.observations, self.observations)

    def test_reject_sidecar_path_traversal(self):
        self.rows[0]["read_latency_sidecar"] = "../outside.latbin"
        raw = b"".join((json.dumps(row) + "\n").encode() for row in self.rows)
        self.observations.write_bytes(raw)
        self.manifest["observations_sha256"] = hashlib.sha256(raw).hexdigest()
        self.manifest["runs"][0]["line_sha256"] = hashlib.sha256(raw.splitlines(keepends=True)[0]).hexdigest()
        self.manifest["runs"][0]["read_latency_sidecar"] = "../outside.latbin"
        self.rejects("invalid V3 sidecar basename")

    def test_reject_malformed_sidecar_record(self):
        path = self.directory / self.rows[0]["read_latency_sidecar"]
        path.write_bytes(b"\x00" * 12)
        self.rejects("sidecar length")

    def test_reject_false_nearest_rank_p99_even_with_renewed_hash(self):
        self.rows[0]["read_p99_ns"] = 999999
        self.refresh()
        self.rejects("nearest-rank p99 mismatch")

    def test_reject_record_count_inconsistency(self):
        self.rows[0]["read_count"] = 10001
        self.refresh()
        self.rejects("exact count")

    def test_reject_global_byte_budget(self):
        previous = bundle.plateau.MAX_TOTAL_SIDECAR_BYTES
        bundle.plateau.MAX_TOTAL_SIDECAR_BYTES = 16
        try:
            self.rejects("invalid sidecar byte-length claim")
        finally:
            bundle.plateau.MAX_TOTAL_SIDECAR_BYTES = previous

    def test_cli_rootless_success_never_grants_cleanup(self):
        result = subprocess.run(
            (sys.executable, "-B", str(HERE / "v22-evidence-bundle-v3.py"),
             "--observations", str(self.observations),
             "--manifest", str(self.manifest_file)),
            capture_output=True, text=True, timeout=8, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["backing_release_authorized"])
        self.assertFalse(report["production_qualified"])

    def test_cli_failure_prints_no_success_report(self):
        self.manifest["observations_sha256"] = "0" * 64
        self.write_manifest()
        result = subprocess.run(
            (sys.executable, "-B", str(HERE / "v22-evidence-bundle-v3.py"),
             "--observations", str(self.observations),
             "--manifest", str(self.manifest_file)),
            capture_output=True, text=True, timeout=8, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("manifest SHA-256", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
