#!/usr/bin/env python3
"""Synthetic, rootless-only tests of offline V2.2 evidence consistency.

Fabricated observations and manifests; no physical evidence, device, swap,
kernel drain, or destructive cleanup. No network access is required.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "v22-evidence-bundle-check.py"
_spec = importlib.util.spec_from_file_location("swapz_v22_bundle_tests", SCRIPT)
assert _spec is not None and _spec.loader is not None
bundle = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = bundle
_spec.loader.exec_module(bundle)


def observation(run_id: str, *, evidence: str = "synthetic",
                source: str = "a" * 40, schema: str | None = None) -> dict:
    version = schema or bundle.plateau.SCHEMA_V2
    row = {
        "schema": version, "evidence": evidence, "backend": "synthetic",
        "profile": "fixed-profile", "strategy": "staged", "batch_kib": 64,
        "run_id": run_id, "source_revision": source, "clock": "monotonic",
        "duration_ns": 1_000_000_000,
        "lower_write_sectors_before": 5000,
        "lower_write_sectors_after": 5000 + 40960,
        "lower_write_ios_before": 100,
        "lower_write_ios_after": 150, "logical_write_bytes": 64 * 1024 * 1024,
        "read_count": 10000, "read_p99_ns": 1000000,
        "integrity_ok": True, "quiescence_ok": True, "flush_ok": True,
        "all_reaped": True, "source_kind": "lower-device-counters",
    }
    if version == bundle.plateau.SCHEMA_V2:
        row["read_latency_counts"] = [[1000000, 10000]]
    return row


def payload(rows: list[dict], *, session: str = "synthetic-session") -> tuple[bytes, dict]:
    data = b"".join(
        (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
        for row in rows
    )
    manifest = {
        "schema": bundle.SCHEMA,
        "source_revision": "a" * 40,
        "session_id": session,
        "collector_id": "fake-offline-collector",
        "lower_device_id": "fixture-device-253:9",
        "backend": "synthetic",
        "profile": "fixed-profile",
        "evidence": "synthetic",
        "observations_sha256": hashlib.sha256(data).hexdigest(),
        "runs": [],
    }
    for line, row in zip(data.splitlines(keepends=True), rows):
        manifest["runs"].append({
            "run_id": row["run_id"],
            "line_sha256": hashlib.sha256(line).hexdigest(),
            **{key: manifest[key] for key in bundle.BINDINGS},
        })
    return data, manifest


def encoded(manifest: dict) -> bytes:
    return json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()


class EvidenceBundleTests(unittest.TestCase):
    def setUp(self):
        self.rows = [observation("trial-01"), observation("trial-02")]
        self.data, self.manifest = payload(self.rows)

    def check(self, *, data: bytes | None = None, manifest: dict | None = None):
        return bundle.check_bytes(data if data is not None else self.data,
                                  encoded(manifest if manifest is not None else self.manifest))

    def test_exact_two_run_bundle_is_consistent_but_not_physical_evidence(self):
        report = self.check()
        self.assertEqual(report["observation_count"], 2)
        self.assertEqual(report["source_revision"], "a" * 40)
        self.assertIn("NOT AUTHENTICATED", report["status"])
        for field in ("authenticated_collector", "independent_device_identity_proved",
                      "kernel_drain_proved", "physical_selection_authorized",
                      "backing_release_authorized"):
            self.assertIs(report[field], False)

    def test_even_self_labeled_physical_v2_evidence_is_never_authenticated(self):
        rows = [observation("trial-01", evidence="physical")]
        data, manifest = payload(rows)
        manifest["evidence"] = "physical"
        for item in manifest["runs"]:
            item["evidence"] = "physical"
        report = self.check(data=data, manifest=manifest)
        self.assertFalse(report["physical_selection_authorized"])

    def test_v3_synthetic_sidecar_is_not_verified_by_jsonl_only_manifest(self):
        rows = [observation("trial-v3", schema=bundle.plateau.SCHEMA_V3)]
        rows[0]["read_latency_sidecar"] = "trial-v3.latbin"
        rows[0]["read_latency_sha256"] = "a" * 64
        data, manifest = payload(rows)
        with self.assertRaisesRegex(ValueError, "V3 sidecar evidence is not bound"):
            self.check(data=data, manifest=manifest)

    def test_v3_physical_sidecar_cannot_claim_bundle_provenance(self):
        rows = [observation("trial-v3", evidence="physical",
                            schema=bundle.plateau.SCHEMA_V3)]
        rows[0]["read_latency_sidecar"] = "trial-v3.latbin"
        rows[0]["read_latency_sha256"] = "a" * 64
        data, manifest = payload(rows)
        manifest["evidence"] = "physical"
        manifest["runs"][0]["evidence"] = "physical"
        with self.assertRaisesRegex(ValueError, "V3 sidecar evidence is not bound"):
            self.check(data=data, manifest=manifest)

    def test_old_self_reported_p99_cannot_enter_measured_bundle(self):
        rows = [observation("trial-01", evidence="kernel",
                            schema=bundle.plateau.SCHEMA)]
        data, manifest = payload(rows)
        manifest["evidence"] = "kernel"
        manifest["runs"][0]["evidence"] = "kernel"
        with self.assertRaisesRegex(ValueError, "exact-latency v2"):
            self.check(data=data, manifest=manifest)

    def test_mixed_git_revisions_rejected_even_when_digests_updated(self):
        rows = copy.deepcopy(self.rows)
        rows[1]["source_revision"] = "b" * 40
        data, manifest = payload(rows)
        with self.assertRaisesRegex(ValueError, "source_revision"):
            self.check(data=data, manifest=manifest)

    def test_mixed_collector_sessions_rejected(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["runs"][1]["session_id"] = "other-session"
        with self.assertRaisesRegex(ValueError, "session_id"):
            self.check(manifest=manifest)

    def test_mixed_collectors_rejected(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["runs"][1]["collector_id"] = "other-collector"
        with self.assertRaisesRegex(ValueError, "collector_id"):
            self.check(manifest=manifest)

    def test_mixed_device_identities_rejected(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["runs"][1]["lower_device_id"] = "unrelated-device"
        with self.assertRaisesRegex(ValueError, "lower_device_id"):
            self.check(manifest=manifest)

    def test_mixed_backend_profile_and_evidence_rejected(self):
        for key, value in (("backend", "other-backend"),
                           ("profile", "other-profile"),
                           ("evidence", "kernel")):
            with self.subTest(field=key):
                manifest = copy.deepcopy(self.manifest)
                manifest["runs"][0][key] = value
                with self.assertRaisesRegex(ValueError, key):
                    self.check(manifest=manifest)

    def test_missing_and_extra_run_manifest_entries_rejected(self):
        for extra in (False, True):
            with self.subTest(extra=extra):
                manifest = copy.deepcopy(self.manifest)
                if extra:
                    manifest["runs"].append(copy.deepcopy(manifest["runs"][0]))
                else:
                    manifest["runs"].pop()
                with self.assertRaisesRegex(ValueError, "inventory count"):
                    self.check(manifest=manifest)

    def test_duplicate_run_id_rejected_despite_updated_hash(self):
        rows = copy.deepcopy(self.rows)
        rows[1]["run_id"] = rows[0]["run_id"]
        data, manifest = payload(rows)
        with self.assertRaisesRegex(ValueError, "duplicate run ID"):
            self.check(data=data, manifest=manifest)

    def test_reordered_manifest_run_inventory_is_denied(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["runs"].reverse()
        with self.assertRaisesRegex(ValueError, "run_id"):
            self.check(manifest=manifest)

    def test_modified_artifact_bytes_denied_before_row_validation(self):
        altered = self.data.replace(b'"batch_kib":64', b'"batch_kib":32', 1)
        with self.assertRaisesRegex(ValueError, "manifest SHA-256"):
            self.check(data=altered)

    def test_per_run_hash_mismatch_denied(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["runs"][0]["line_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "run digest"):
            self.check(manifest=manifest)

    def test_corrupt_latency_distribution_denied_even_when_rehashed(self):
        rows = copy.deepcopy(self.rows)
        rows[1]["read_latency_counts"] = [[1000001, 10000]]
        data, manifest = payload(rows)
        with self.assertRaisesRegex(ValueError, "nearest-rank p99"):
            self.check(data=data, manifest=manifest)

    def test_duplicate_fields_and_nan_in_manifest_are_denied(self):
        raw = encoded(self.manifest)
        corrupted = raw.replace(b'"schema":', b'"schema":"oops","schema":', 1)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            bundle.check_bytes(self.data, corrupted)
        corrupted = raw.replace(b'"runs":', b'"unexpected":NaN,"runs":', 1)
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            bundle.check_bytes(self.data, corrupted)

    def test_extra_manifest_key_and_invalid_source_sha_denied(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["says_approved"] = True
        with self.assertRaisesRegex(ValueError, "extra fields"):
            self.check(manifest=manifest)
        manifest.pop("says_approved")
        manifest["source_revision"] = "not-a-commit"
        with self.assertRaisesRegex(ValueError, "source_revision"):
            self.check(manifest=manifest)

    def test_lf_terminated_exact_jsonl_is_required(self):
        for data in (self.data.rstrip(b"\n"), self.data.replace(b"\n", b"\r\n")):
            with self.subTest(data=data[-3:]):
                manifest = copy.deepcopy(self.manifest)
                manifest["observations_sha256"] = hashlib.sha256(data).hexdigest()
                with self.assertRaisesRegex(ValueError, "LF-terminated"):
                    self.check(data=data, manifest=manifest)

    def test_symlink_source_rejected_before_read(self):
        with tempfile.TemporaryDirectory(prefix="swapz-evidence-bundle-") as root:
            directory = Path(root)
            real = directory / "real.jsonl"
            real.write_bytes(self.data)
            link = directory / "alias.jsonl"
            link.symlink_to(real)
            manifest_path = directory / "manifest.json"
            manifest_path.write_bytes(encoded(self.manifest))
            with self.assertRaises(OSError):
                bundle.check_paths(link, manifest_path)

    def test_cli_accepts_synthetic_file_but_refuses_elevation(self):
        with tempfile.TemporaryDirectory(prefix="swapz-evidence-bundle-") as root:
            directory = Path(root)
            source = directory / "measurements.jsonl"
            source.write_bytes(self.data)
            manifest_path = directory / "manifest.json"
            manifest_path.write_bytes(encoded(self.manifest))
            process = subprocess.run(
                [sys.executable, "-B", str(SCRIPT),
                 "--observations", str(source), "--manifest", str(manifest_path)],
                capture_output=True, text=True, timeout=10, check=False,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            report = json.loads(process.stdout)
            self.assertFalse(report["physical_selection_authorized"])
            self.assertFalse(report["backing_release_authorized"])

    def test_cli_rejects_tampered_artifact_without_producing_verdict(self):
        with tempfile.TemporaryDirectory(prefix="swapz-evidence-bundle-") as root:
            directory = Path(root)
            source = directory / "measurements.jsonl"
            source.write_bytes(self.data + b" ")
            manifest_path = directory / "manifest.json"
            manifest_path.write_bytes(encoded(self.manifest))
            process = subprocess.run(
                [sys.executable, "-B", str(SCRIPT),
                 "--observations", str(source), "--manifest", str(manifest_path)],
                capture_output=True, text=True, timeout=10, check=False,
            )
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(process.stdout.strip(), "")
            self.assertIn("manifest SHA-256", process.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
