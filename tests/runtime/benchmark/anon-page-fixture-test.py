#!/usr/bin/env python3
"""Rootless, bounded negative regressions for the real synthetic page fixture.

A fixture PASS is not Linux anonymous swap-out/swap-in or physical qualification.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

FIXTURE_SOURCE = Path(__file__).with_name("anon-page-fixture.py")
FIXTURE_SPEC = importlib.util.spec_from_file_location("anon_page_fixture", FIXTURE_SOURCE)
if FIXTURE_SPEC is None or FIXTURE_SPEC.loader is None:
    raise RuntimeError("cannot load synthetic fixture generator")
fixture = importlib.util.module_from_spec(FIXTURE_SPEC)
FIXTURE_SPEC.loader.exec_module(fixture)

TEST_PAGES = 18
MAX_TEST_BYTES = TEST_PAGES * fixture.PAGE
MAX_MANIFEST_BYTES = 16 * 1024
ALL_PROFILE_WEIGHTS = {profile: 1 for profile in fixture.PROFILES}

# Frozen byte digests from the existing page recipes, not compression results.
PAGE_DIGESTS = {
    "zero": "ad7facb2586fc6e966c004d7d1d16b024f5805ff7cb47c7a85dabd8b48892ca7",
    "heap": "44b488952cb083df1dbc762d584d8ca045bb65bd1e2c8fe427ba5f8a11f0ab3d",
    "text": "8d2e900ff9d4162af53e96d52e8e527e8ad36f6a9b68ace49b92629dc905833c",
    "cow": "3e89bf1130ab38e692de69f182fc0a8cb2bc307778bfa7a682012525bdfb8515",
    "raster": "b5197b5071a03633d607c48382fda98815507e239fdc14ad5909693bbede43e6",
    "mixed": "ecfa35cc4293c23f9fc31524b6ce9021b0e9cbe2c27b651c454d3806ef92ee7d",
    "medium": "06269efb0cd4e3f4928b20c606ba7984c5e45469e88755b25a61d0105d42b5dd",
    "delta64": "59d23d5ff9b87ddeb91f32bbd01ab1351989ad6a726b81dd4d2cbbe4e72faf13",
    "entropy": "090b737876a8394738f4f962a1fb80382ad9b6143d3ca3291260c60e310f9086",
}


class BoundedInputRegression(unittest.TestCase):
    def test_frozen_page_recipes(self) -> None:
        for profile, expected_digest in PAGE_DIGESTS.items():
            with self.subTest(profile=profile):
                page = fixture.page_bytes(0x51A0A9, 7, profile)
                self.assertEqual(len(page), fixture.PAGE)
                self.assertEqual(hashlib.sha256(page).hexdigest(), expected_digest)

    def test_seed_types_ranges_and_oversized_lexical_input(self) -> None:
        for seed in (True, -1, fixture.UINT64_MAX + 1, 1.5, "10"):
            with self.subTest(seed_type=type(seed).__name__, seed=str(seed)[:24]):
                with self.assertRaisesRegex(ValueError, "unsigned 64-bit"):
                    fixture.require_seed(seed)
        for seed_text in ("9" * 161, "0x" + "f" * 159, "-1",
                          str(fixture.UINT64_MAX + 1)):
            with self.subTest(length=len(seed_text)):
                with self.assertRaises(argparse.ArgumentTypeError):
                    fixture.parse_seed(seed_text)
        self.assertEqual(fixture.parse_seed("0xffffffffffffffff"), fixture.UINT64_MAX)

    def test_indices_and_direct_schedule_allocation_bounds(self) -> None:
        for index in (-1, fixture.MAX_PAGES, True, 1.5):
            with self.subTest(index=index):
                with self.assertRaisesRegex(ValueError, "page index"):
                    fixture.page_bytes(1, index, "heap")
        for count in (0, -1, True, fixture.MAX_PAGES + 1, 10**100):
            with self.subTest(count=str(count)[:20]):
                with self.assertRaisesRegex(ValueError, "fixture pages"):
                    fixture.schedule(1, count, ALL_PROFILE_WEIGHTS)
        for weights in ({"heap": True}, {"heap": -1}, {"heap": 0},
                        {"unknown": 1}):
            with self.subTest(weights=weights):
                with self.assertRaisesRegex(ValueError, "profile weights"):
                    fixture.schedule(1, 1, weights)

    def test_short_page_cannot_be_compressed(self) -> None:
        with self.assertRaisesRegex(
                ValueError, "expected_size=4096 observed_size=4095"):
            fixture.measure(lambda *_: self.fail("liblz4 called for short page"),
                            bytes(fixture.PAGE - 1))


class PersistedManifestRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.compress = fixture.lz4_compressor()
        except (RuntimeError, OSError, AttributeError) as error:
            raise unittest.SkipTest(f"real liblz4 unavailable: {type(error).__name__}") from error

    def setUp(self) -> None:
        # addCleanup is run before unittest can report this case as successful;
        # a failed directory cleanup becomes a test ERROR, never a false PASS.
        temporary_directory = tempfile.TemporaryDirectory(prefix="swapz-anon-fixture-")
        self.addCleanup(temporary_directory.cleanup)
        self.fixture_path = Path(temporary_directory.name) / "fixture.bin"
        self.manifest_path = Path(temporary_directory.name) / "fixture.json"
        self.payload, self.manifest = fixture.generate(
            0x51A0A9, TEST_PAGES, ALL_PROFILE_WEIGHTS, self.compress)
        self.assertLessEqual(len(self.payload), MAX_TEST_BYTES)
        self.assertEqual(len(self.payload), TEST_PAGES * fixture.PAGE)
        self.fixture_path.write_bytes(self.payload)
        self.persist_manifest(self.manifest)

    def persist_manifest(self, manifest: dict) -> dict:
        serialized = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
        self.assertLessEqual(len(serialized.encode("utf-8")), MAX_MANIFEST_BYTES)
        self.manifest_path.write_text(serialized, encoding="utf-8")
        with self.manifest_path.open("rb") as manifest_file:
            persisted = manifest_file.read(MAX_MANIFEST_BYTES + 1)
        self.assertLessEqual(len(persisted), MAX_MANIFEST_BYTES)
        return json.loads(persisted)

    def reject_manifest(self, changed: dict, field: str) -> None:
        persisted = self.persist_manifest(changed)
        with self.assertRaisesRegex(
                ValueError,
                rf"phase=verify metadata_field={field} cause=workload-metadata-mismatch") as raised:
            fixture.verify_fixture(self.fixture_path, persisted, self.compress)
        # Do not leak any page bytes into diagnostics.
        self.assertNotIn(repr(self.payload[:32]), str(raised.exception))

    def test_all_profiles_persisted_roundtrip_and_repeated_bytes(self) -> None:
        persisted = self.persist_manifest(self.manifest)
        self.assertTrue(fixture.exact_json_value(persisted, self.manifest))
        self.assertEqual(persisted["profile_pages"],
                         {name: 2 for name in fixture.PROFILES})
        fixture.verify_fixture(self.fixture_path, persisted, self.compress)
        repeated_payload, repeated_manifest = fixture.generate(
            0x51A0A9, TEST_PAGES, ALL_PROFILE_WEIGHTS, self.compress)
        self.assertEqual(repeated_payload, self.payload)
        self.assertTrue(fixture.exact_json_value(repeated_manifest, persisted))
        with self.fixture_path.open("rb") as fixture_file:
            self.assertEqual(fixture_file.read(MAX_TEST_BYTES + 1), self.payload)

    def test_legacy_default_seed_byte_digests(self) -> None:
        # Byte hashes deliberately ignore liblz4 version-specific size buckets.
        expected = {
            0x51A0A9: "88fdab5b233580044d3f2b342743ad1411c174cbb5d728f74db14db54676193b",
            0: "3a4b886435888de764e1033fb3b02e1af54833dec313bf1956629f8c12b69eb5",
            fixture.UINT64_MAX: "fa48a2215444ca2374d53512221d5e5658619a440580051eef52c8934f172304",
        }
        default_weights = fixture.parse_weights(fixture.DEFAULT_WEIGHTS)
        for seed, expected_digest in expected.items():
            with self.subTest(seed=seed):
                payload, manifest = fixture.generate(seed, 16, default_weights, self.compress)
                self.assertEqual(hashlib.sha256(payload).hexdigest(), expected_digest)
                self.fixture_path.write_bytes(payload)
                fixture.verify_fixture(self.fixture_path,
                                       self.persist_manifest(manifest), self.compress)

    def test_rejects_boolean_profile_counts_and_incorrect_raw_accounting(self) -> None:
        for field, changed_value in (
                ("profile_pages", True),
                ("raw_pages", self.manifest["raw_pages"] + 1),
                ("raw_page_bytes", self.manifest["raw_page_bytes"] + fixture.PAGE)):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.manifest)
                if field == "profile_pages":
                    changed[field]["heap"] = changed_value
                else:
                    changed[field] = changed_value
                self.reject_manifest(changed, field)

    def test_rejects_compression_descriptor_and_profile_quota_drift(self) -> None:
        changed = copy.deepcopy(self.manifest)
        changed["compression"] = "LZ4_compress_default"
        self.reject_manifest(changed, "compression")
        changed = copy.deepcopy(self.manifest)
        changed["profile_pages"]["heap"] += 1
        self.reject_manifest(changed, "profile_pages")
        changed = copy.deepcopy(self.manifest)
        changed["requested_profile_weights"]["heap"] = 100
        self.reject_manifest(changed, "profile_pages")

    def test_rejects_each_persisted_manifest_field_type_or_value_drift(self) -> None:
        for field, value in self.manifest.items():
            if field in ("seed", "pages", "requested_profile_weights"):
                continue  # Validated separately at direct input/quotas boundary.
            with self.subTest(field=field):
                changed = copy.deepcopy(self.manifest)
                if isinstance(value, dict):
                    changed[field]["unexpected_bucket"] = True
                elif type(value) is int:
                    changed[field] = True  # bool == 1, but is not an integer.
                elif value is None:
                    changed[field] = False
                else:
                    changed[field] = value + "-changed"
                self.reject_manifest(changed, field)
        changed = copy.deepcopy(self.manifest)
        changed["profile_lz4_buckets"]["heap"]["unexpected_bucket"] = True
        self.reject_manifest(changed, "profile_lz4_buckets")
        changed = copy.deepcopy(self.manifest)
        changed["lz4_size_buckets"]["raw"] = True
        self.reject_manifest(changed, "lz4_size_buckets")
        changed = copy.deepcopy(self.manifest)
        changed["unexpected_field"] = "not permitted"
        self.reject_manifest(changed, "unexpected_field")
        changed = copy.deepcopy(self.manifest)
        del changed["fixture_sha256"]
        self.reject_manifest(changed, "fixture_sha256")

    def test_rejects_invalid_persisted_seed_and_page_count_before_allocating(self) -> None:
        for field, invalid_values, diagnostic in (
                ("seed", [True, -1, fixture.UINT64_MAX + 1], "unsigned 64-bit"),
                ("pages", [True, -1, fixture.MAX_PAGES + 1, 10**100], "fixture pages")):
            for invalid in invalid_values:
                with self.subTest(field=field, value=str(invalid)[:24]):
                    changed = copy.deepcopy(self.manifest)
                    changed[field] = invalid
                    with self.assertRaisesRegex(ValueError, diagnostic):
                        fixture.verify_fixture(
                            self.fixture_path, self.persist_manifest(changed), self.compress)

    def test_rejects_short_and_extra_persisted_records(self) -> None:
        for remaining in (0, 19, fixture.PAGE - 1):
            with self.subTest(remaining=remaining):
                with self.fixture_path.open("r+b") as fixture_file:
                    fixture_file.truncate((TEST_PAGES - 1) * fixture.PAGE + remaining)
                with self.assertRaisesRegex(
                        ValueError,
                        rf"record={TEST_PAGES - 1} expected_size=4096 "
                        rf"observed_size={remaining} cause=truncated-record"):
                    fixture.verify_fixture(self.fixture_path, self.manifest, self.compress)
                self.fixture_path.write_bytes(self.payload)
        with self.fixture_path.open("ab") as fixture_file:
            fixture_file.write(b"x")
        with self.assertRaisesRegex(
                ValueError,
                rf"record={TEST_PAGES} expected_size=0 "
                r"observed_size=nonzero cause=trailing-record"):
            fixture.verify_fixture(self.fixture_path, self.manifest, self.compress)

    def test_corrupted_first_and_last_persisted_page_hash_diagnostics(self) -> None:
        for page_index in (0, TEST_PAGES - 1):
            with self.subTest(page_index=page_index):
                offset = page_index * fixture.PAGE + 31
                with self.fixture_path.open("r+b") as fixture_file:
                    fixture_file.seek(offset)
                    original_byte = fixture_file.read(1)
                    self.assertEqual(len(original_byte), 1)
                    fixture_file.seek(offset)
                    fixture_file.write(bytes([original_byte[0] ^ 1]))
                    fixture_file.seek(page_index * fixture.PAGE)
                    observed_page = fixture_file.read(fixture.PAGE)
                expected_page = self.payload[
                    page_index * fixture.PAGE:(page_index + 1) * fixture.PAGE]
                with self.assertRaisesRegex(
                        ValueError,
                        rf"record={page_index} expected_sha256="
                        rf"{hashlib.sha256(expected_page).hexdigest()} "
                        rf"observed_sha256={hashlib.sha256(observed_page).hexdigest()} "
                        r"cause=page-hash-mismatch") as raised:
                    fixture.verify_fixture(self.fixture_path, self.manifest, self.compress)
                self.assertNotIn(repr(expected_page), str(raised.exception))
                self.fixture_path.write_bytes(self.payload)

    def test_main_does_not_report_success_after_manifest_write_failure(self) -> None:
        output_prefix = self.fixture_path.with_suffix("")
        captured_output = io.StringIO()
        arguments = [str(FIXTURE_SOURCE), "--output-prefix", str(output_prefix),
                     "--pages", "4", "--seed", "0x51a0a9"]
        with mock.patch.object(sys, "argv", arguments), \
                mock.patch.object(Path, "write_text", return_value=0), \
                contextlib.redirect_stdout(captured_output):
            with self.assertRaisesRegex(ValueError, "workload-metadata-write-mismatch"):
                fixture.main()
        self.assertEqual(captured_output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
