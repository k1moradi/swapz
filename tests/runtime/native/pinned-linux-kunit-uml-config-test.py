#!/usr/bin/env python3
"""Fail-closed pinned UML KUnit config and two-profile evidence verifier.

The default invocation runs rootless negative tests. --verify and
--verify-pair consume hosted modified-Linux config and real TAP evidence.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


CONFIG_LIMIT = 1024 * 1024
TAP_LIMIT = 8 * 1024 * 1024
LINUX_SHA = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
REQUIRED = {
    "CONFIG_BLOCK": "y",
    "CONFIG_SWAP": "y",
    "CONFIG_KUNIT": "y",
    "CONFIG_SWAP_BIO_ORIGIN_KUNIT_TEST": "y",
    "CONFIG_CGROUPS": "n",
    "CONFIG_BLK_CGROUP": "n",
}
CONFIG_VALUE = re.compile(r"^(CONFIG_[A-Za-z0-9_]+)=(.+)$")
CONFIG_UNSET = re.compile(r"^# (CONFIG_[A-Za-z0-9_]+) is not set$")
MANIFEST_KEY = re.compile(r"^[a-z][a-z0-9_]*$")
OBJECT_LINE = re.compile(r"^([a-z][a-z0-9_-]*/[a-z][a-z0-9_-]*\.o) sha256=([0-9a-f]{64})$")
COMMON_OBJECTS = frozenset((
    "block/bio.o", "block/swap-bio-origin-kunit.o", "mm/page_io.o",
))
KNOWN_OBJECTS = COMMON_OBJECTS | {"mm/zswap.o"}



class EvidenceError(ValueError):
    """Rootless or hosted evidence must fail closed."""


def read_evidence(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise EvidenceError("missing-or-symlink-evidence")
    size = path.stat().st_size
    if not 0 < size <= maximum:
        raise EvidenceError("empty-or-oversized-evidence")
    return path.read_bytes()


def parse_config(data: bytes, *, source_kind: str = "config") -> dict[str, str]:
    """Parse real Kconfig names, including lowercase suffixes, fail closed.

    Preserve first malformed line and a SHA-256 fingerprint without printing
    possible secret values, full configs, runner paths or unbounded content.
    """
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeError as error:
        raise EvidenceError("non-utf8-config") from error
    values = {}
    for line_number, line in enumerate(lines, 1):
        set_match = CONFIG_VALUE.fullmatch(line)
        unset_match = CONFIG_UNSET.fullmatch(line)
        if set_match:
            name, value = set_match.groups()
        elif unset_match:
            name, value = unset_match.group(1), "n"
        elif line.lstrip().startswith(("CONFIG_", "# CONFIG_")):
            suspicious_line = line.lstrip()
            suspect_name = (suspicious_line[2:].split(" ", 1)[0]
                            if suspicious_line.startswith("# CONFIG_")
                            else suspicious_line.partition("=")[0])
            safe_name = re.sub(r"[^A-Za-z0-9_.-]", "?",
                               suspect_name[:80])
            fingerprint = hashlib.sha256(line.encode("utf-8")).hexdigest()
            raise EvidenceError(
                "malformed-config-entry:source=" + source_kind +
                ":line=" + str(line_number) + ":option=" + safe_name +
                ":line_sha256=" + fingerprint)
        else:
            continue
        if name in values:
            raise EvidenceError("duplicate-config-option:" + name)
        values[name] = value
    return values


def expected_config(profile: str) -> dict[str, str]:
    if profile not in ("enabled", "disabled"):
        raise EvidenceError("invalid-profile")
    return {**REQUIRED, "CONFIG_ZSWAP": "y" if profile == "enabled" else "n"}


def check_config(profile: str, requested: bytes, effective: bytes) -> None:
    expected = expected_config(profile)
    request_values = parse_config(requested, source_kind="request")
    actual_values = parse_config(effective, source_kind="effective")
    for name, value in expected.items():
        request_value = request_values.get(name)
        if request_value != value:
            raise EvidenceError("request-" + name + ":expected=" + value +
                                ":actual=" + str(request_value or "MISSING"))
        actual_value = actual_values.get(name)
        if actual_value != value:
            raise EvidenceError("effective-" + name + ":expected=" + value +
                                ":actual=" + str(actual_value or "MISSING"))


def parse_manifest(data: bytes) -> dict[str, str]:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeError as error:
        raise EvidenceError("invalid-manifest-encoding") from error
    record = {}
    transitions = []
    for line in lines:
        name, separator, value = line.partition("=")
        if not separator or not MANIFEST_KEY.fullmatch(name) or not value:
            raise EvidenceError("malformed-or-duplicate-manifest")
        if name == "object":
            # Multiple records are legitimate, but each object identity has
            # exactly one bounded digest and is never an ordinary text key.
            match = OBJECT_LINE.fullmatch(value)
            if match is None:
                raise EvidenceError("invalid-object-record")
            object_path, digest = match.groups()
            if object_path not in KNOWN_OBJECTS:
                raise EvidenceError("unknown-object-identity")
            name, value = "object:" + object_path, digest
            if name in record:
                raise EvidenceError("duplicate-object-identity")
        elif name in record and name != "result":
            raise EvidenceError("malformed-or-duplicate-manifest")
        if name == "result":
            transitions.append(value)
            if transitions not in (["IN_PROGRESS"], ["IN_PROGRESS", "PASS"],
                                   ["IN_PROGRESS", "FAIL"]):
                raise EvidenceError("invalid-result-transition")
        record[name] = value
    return record


def verify_object_inventory(profile: str, record: dict[str, str]) -> None:
    """Require all and only the objects compiled for the given zswap profile."""
    expected_config(profile)
    expected = COMMON_OBJECTS | ({"mm/zswap.o"} if profile == "enabled" else set())
    observed = {name.removeprefix("object:") for name in record
                if name.startswith("object:")}
    if observed != expected:
        raise EvidenceError("invalid-object-inventory:" + profile)


def object_inventory_digest(record: dict[str, str]) -> str:
    """Bind the first-pass object SHA inventory to the final pair gate."""
    canonical = "".join(name + " sha256=" + record[name] + "\n"
                        for name in sorted(record) if name.startswith("object:"))
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def verify_config(profile: str, request_path: Path,
                  effective_path: Path, manifest_path: Path) -> None:
    expected_config(profile)
    requested = read_evidence(request_path, CONFIG_LIMIT)
    effective = read_evidence(effective_path, CONFIG_LIMIT)
    manifest = parse_manifest(read_evidence(manifest_path, CONFIG_LIMIT))
    if (manifest.get("result") != "IN_PROGRESS" or
        manifest.get("requested_zswap") != ("y" if profile == "enabled" else "n") or
        manifest.get("uml_kunit_exit") != "0" or
        "kunit_cases_passed" in manifest):
        raise EvidenceError("invalid-uml-execution-precondition")
    verify_object_inventory(profile, manifest)
    if ("uml_config_sha256" in manifest or "uml_request_sha256" in manifest or
        "uml_objects_sha256" in manifest):
        raise EvidenceError("already-recorded-uml-config-digest")
    # Record both digests even when the very next Kconfig check fails.
    with manifest_path.open("a", encoding="utf-8") as output:
        output.write("uml_config_sha256=" +
                     hashlib.sha256(effective).hexdigest() + "\n")
        output.write("uml_request_sha256=" +
                     hashlib.sha256(requested).hexdigest() + "\n")
        output.write("uml_objects_sha256=" + object_inventory_digest(manifest) + "\n")
    check_config(profile, requested, effective)


def verify_pair(evidence: Path, enabled: Path, disabled: Path) -> None:
    config_digests = set()
    tap_digests = set()
    for profile, config_path in (("enabled", enabled), ("disabled", disabled)):
        manifest = parse_manifest(read_evidence(evidence / (profile + ".txt"),
                                                CONFIG_LIMIT))
        config = read_evidence(config_path, CONFIG_LIMIT)
        tap = read_evidence(evidence / (profile + "-kunit-output.log"), TAP_LIMIT)
        verify_object_inventory(profile, manifest)
        config_sha = hashlib.sha256(config).hexdigest()
        tap_sha = hashlib.sha256(tap).hexdigest()
        if manifest.get("uml_objects_sha256") != object_inventory_digest(manifest):
            raise EvidenceError("object-digest-drift:" + profile)
        if (manifest.get("result") != "PASS" or
            manifest.get("linux_sha") != LINUX_SHA or
            manifest.get("source_modified") != "yes" or
            manifest.get("requested_zswap") != ("y" if profile == "enabled" else "n") or
            manifest.get("uml_kunit_exit") != "0" or
            manifest.get("verify_real_tap_exit") != "0" or
            manifest.get("kunit_executed") != "yes" or
            manifest.get("kunit_cases_passed") != "5" or
            manifest.get("uml_config_sha256") != config_sha or
            manifest.get("kunit_output_sha256") != tap_sha):
            raise EvidenceError("invalid-profile-evidence:" + profile)
        for name, value in expected_config(profile).items():
            if parse_config(config).get(name) != value:
                raise EvidenceError("profile-config-drift:" + profile + ":" + name)
        if config_sha in config_digests or tap_sha in tap_digests:
            raise EvidenceError("reused-profile-config-or-tap:" + profile)
        # Revalidate the actual bytes, not merely a copied PASS marker.
        # The existing strict parser requires all five distinct TAP cases.
        try:
            completed = subprocess.run(
                [sys.executable, "-B",
                 str(Path(__file__).with_name(
                     "pinned-linux-zswap-origin-stage-test.py")),
                 "--verify-kunit-tap",
                 str(evidence / (profile + "-kunit-output.log"))],
                capture_output=True, text=True, check=False, timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise EvidenceError("tap-verifier-unavailable") from error
        if completed.returncode:
            raise EvidenceError("invalid-real-tap:" + profile)
        config_digests.add(config_sha)
        tap_digests.add(tap_sha)


class RootlessConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    @staticmethod
    def object_fixture_lines(profile: str) -> str:
        """Only synthetic digest values; not a claim of compiled objects."""
        names = sorted(COMMON_OBJECTS | ({"mm/zswap.o"} if profile == "enabled"
                                        else set()))
        return "".join("object=" + name + " sha256=" +
                       hashlib.sha256((profile + ":" + name).encode()).hexdigest() +
                       "\n" for name in names)

    def fixture(self, profile="enabled"):
        values = expected_config(profile)
        contents = "\n".join("# " + key + " is not set" if value == "n"
                             else key + "=" + value
                             for key, value in values.items()) + "\n"
        request = self.root / "request"
        effective = self.root / "effective"
        manifest = self.root / "manifest"
        request.write_text(contents)
        effective.write_text(contents)
        manifest.write_text("result=IN_PROGRESS\nrequested_zswap=" +
                            ("y" if profile == "enabled" else "n") +
                            "\numl_kunit_exit=0\n" +
                            self.object_fixture_lines(profile))
        return request, effective, manifest

    def test_positive_y_and_n(self):
        for profile in ("enabled", "disabled"):
            request, effective, manifest = self.fixture(profile)
            verify_config(profile, request, effective, manifest)
            self.assertIn(hashlib.sha256(effective.read_bytes()).hexdigest(),
                          manifest.read_text())

    def test_original_hosted_four_object_records_and_digest_values(self):
        # Actual object records from #43834985711 artifact #14209984320.
        hosted_objects = (
            "object=block/bio.o sha256=37915d334a6ce06969a794458f49e0a4e2fb749693068a5cd7d548bcea8c8fcd\n"
            "object=block/swap-bio-origin-kunit.o sha256=b07a5deff230d99f8fe33404a34518c811dfa64fb51ee1e4edd41f6ef7231dce\n"
            "object=mm/page_io.o sha256=9fde29f1c5de63d4ea50e3129ba11ef8fce4d183f06bff267155d4f6585ea267\n"
            "object=mm/zswap.o sha256=5c5b8c1d8cbc3a977c5900f1f32e22f2d856636434255aff17db2648b09196c2\n"
        )
        request, effective, manifest_path = self.fixture()
        manifest_path.write_text(
            "result=IN_PROGRESS\nrequested_zswap=y\numl_kunit_exit=0\n" +
            hosted_objects)
        record = parse_manifest(manifest_path.read_bytes())
        verify_object_inventory("enabled", record)
        self.assertEqual(len([key for key in record if key.startswith("object:")]), 4)
        self.assertEqual(record["object:mm/zswap.o"],
                         "5c5b8c1d8cbc3a977c5900f1f32e22f2d856636434255aff17db2648b09196c2")
        verify_config("enabled", request, effective, manifest_path)
        self.assertIn("uml_config_sha256=", manifest_path.read_text())

    def test_object_identity_digest_and_profile_mutation_refusals(self):
        valid = self.object_fixture_lines("enabled")
        lines = valid.splitlines(keepends=True)
        mutations = (
            ("duplicate-identity", valid + lines[0], "duplicate-object-identity"),
            ("duplicate-with-different-hash", valid + lines[0].replace(
                lines[0].split("sha256=")[1].strip(), "f" * 64), "duplicate-object-identity"),
            ("unknown-path", valid + "object=block/foreign.o sha256=" + "a" * 64 + "\n",
             "unknown-object-identity"),
            ("short-digest", valid.replace("sha256=" + lines[0].split("sha256=")[1].strip(),
                                           "sha256=1234", 1), "invalid-object-record"),
            ("uppercase-digest", valid.replace("sha256=" + lines[0].split("sha256=")[1].strip(),
                                               "sha256=" + "A" * 64, 1),
             "invalid-object-record"),
            ("malformed-object-token", valid + "object=block/bio.o bad_sha=0\n",
             "invalid-object-record"),
            ("empty-object-record", valid + "object=\n",
             "malformed-or-duplicate-manifest"),
            ("duplicate-ordinary", valid + "requested_zswap=y\nrequested_zswap=n\n",
             "malformed-or-duplicate-manifest"),
            ("invalid-key", valid + "object:mm/zswap.o=not-a-record\n",
             "malformed-or-duplicate-manifest"),
        )
        for name, text, expected_error in mutations:
            with self.subTest(name=name), self.assertRaisesRegex(EvidenceError,
                                                                   expected_error):
                parse_manifest(("result=IN_PROGRESS\n" + text).encode())
        for profile in ("enabled", "disabled"):
            request, effective, manifest_path = self.fixture(profile)
            original = manifest_path.read_text()
            for name, content in (
                ("missing", original.replace(self.object_fixture_lines(profile).splitlines(
                    keepends=True)[0], "", 1)),
                ("incompatible", original + "object=mm/zswap.o sha256=" + "a" * 64 + "\n"
                 if profile == "disabled" else original.replace(
                     "object=mm/zswap.o sha256=", "object=mm/foreign.o sha256=", 1)),
            ):
                with self.subTest(profile=profile, mutation=name):
                    manifest_path.write_text(content)
                    with self.assertRaises(EvidenceError):
                        verify_config(profile, request, effective, manifest_path)
            manifest_path.write_text(original)
            verify_config(profile, request, effective, manifest_path)
            unchanged = manifest_path.read_bytes()
            with self.assertRaisesRegex(EvidenceError,
                                        "already-recorded-uml-config-digest"):
                verify_config(profile, request, effective, manifest_path)
            self.assertEqual(manifest_path.read_bytes(), unchanged)

    def test_pinned_linux_mixed_case_symbol_grammar(self):
        """Pinned Linux Kconfig really defines SCSI_DC395x and I2C_MUX_PCA954x."""
        legitimate = ("CONFIG_SCSI_DC395x=m\n"
                      "# CONFIG_I2C_MUX_PCA954x is not set\n")
        expected = {"CONFIG_SCSI_DC395x": "m",
                    "CONFIG_I2C_MUX_PCA954x": "n"}
        for profile in ("enabled", "disabled"):
            with self.subTest(profile=profile):
                request, effective, manifest = self.fixture(profile)
                request.write_text(request.read_text() + legitimate)
                effective.write_text(effective.read_text() + legitimate)
                self.assertEqual({name: parse_config(effective.read_bytes())[name]
                                  for name in expected}, expected)
                verify_config(profile, request, effective, manifest)
                self.assertIn("uml_config_sha256=", manifest.read_text())
                self.assertNotIn("kunit_cases_passed=5", manifest.read_text())

    def test_malformed_config_identifies_first_line_without_values_or_paths(self):
        """A real first failure is actionable without exposing config secrets."""
        malformed_lines = (
            "CONFIG_SCSI_DC395x",
            "CONFIG_SCSI_DC395x=",
            "CONFIG_SCSI-DC395x=y",
            "# CONFIG_I2C_MUX_PCA954x is maybe set",
            " CONFIG_KUNIT=y",
            "CONFIG_KUNIT =y",
            "CONFIG_PRIVATE_VALUE:raw-secret=supersecret",
        )
        for invalid in malformed_lines:
            with self.subTest(line=invalid.partition("=")[0]):
                request, effective, manifest = self.fixture()
                original_lines = effective.read_text().splitlines()
                effective.write_text(effective.read_text() + invalid + "\n" +
                                     "CONFIG_LATE_INVALID=\n")
                with self.assertRaisesRegex(EvidenceError,
                        "malformed-config-entry:source=effective:line=" +
                        str(len(original_lines) + 1)) as failure:
                    verify_config("enabled", request, effective, manifest)
                message = str(failure.exception)
                fingerprint = hashlib.sha256(invalid.encode("utf-8")).hexdigest()
                self.assertIn("line_sha256=" + fingerprint, message)
                self.assertIn("option=CONFIG_", message)
                self.assertNotIn("supersecret", message)
                self.assertNotIn(str(self.root), message)
                self.assertIn("uml_config_sha256=", manifest.read_text())
                self.assertNotIn("kunit_cases_passed=", manifest.read_text())

    def test_mixed_case_duplicate_and_profile_mismatch_still_fail(self):
        for invalid in (
            "CONFIG_SCSI_DC395x=m\nCONFIG_SCSI_DC395x=y\n",
            "CONFIG_SCSI_DC395x=m\n# CONFIG_SCSI_DC395x is not set\n",
        ):
            with self.subTest(kind=invalid.splitlines()[-1]):
                with self.assertRaisesRegex(EvidenceError,
                                            "duplicate-config-option:CONFIG_SCSI_DC395x"):
                    parse_config(invalid.encode("utf-8"))
        request, effective, manifest = self.fixture("disabled")
        effective.write_text(effective.read_text().replace(
            "# CONFIG_ZSWAP is not set", "CONFIG_ZSWAP=m"))
        with self.assertRaisesRegex(EvidenceError,
                                    "effective-CONFIG_ZSWAP:expected=n:actual=m"):
            verify_config("disabled", request, effective, manifest)


    def test_missing_wrong_and_forced_options(self):
        for name in REQUIRED:
            request, effective, manifest = self.fixture()
            effective.write_text("\n".join(line for line in effective.read_text().splitlines()
                                           if name not in line) + "\n")
            with self.subTest(name=name), self.assertRaisesRegex(EvidenceError, name):
                verify_config("enabled", request, effective, manifest)
        request, effective, manifest = self.fixture()
        effective.write_text(effective.read_text().replace("CONFIG_KUNIT=y",
                                                           "CONFIG_KUNIT=m"))
        with self.assertRaisesRegex(EvidenceError, "CONFIG_KUNIT:expected=y:actual=m"):
            verify_config("enabled", request, effective, manifest)
        request, effective, manifest = self.fixture()
        effective.write_text(effective.read_text().replace(
            "# CONFIG_BLK_CGROUP is not set", "CONFIG_BLK_CGROUP=y"))
        with self.assertRaisesRegex(EvidenceError, "CONFIG_BLK_CGROUP"):
            verify_config("enabled", request, effective, manifest)

    def test_wrong_profile_and_bad_request(self):
        request, effective, manifest = self.fixture("disabled")
        with self.assertRaisesRegex(EvidenceError, "request-CONFIG_ZSWAP"):
            check_config("enabled", request.read_bytes(), effective.read_bytes())
        request, effective, manifest = self.fixture()
        request.write_text(request.read_text().replace("# CONFIG_CGROUPS is not set\n", ""))
        with self.assertRaisesRegex(EvidenceError, "request-CONFIG_CGROUPS"):
            verify_config("enabled", request, effective, manifest)

    def test_duplicates_and_malformed_config(self):
        request, effective, manifest = self.fixture()
        effective.write_text(effective.read_text() + "CONFIG_KUNIT=y\n")
        with self.assertRaisesRegex(EvidenceError, "duplicate-config-option"):
            verify_config("enabled", request, effective, manifest)
        request, effective, manifest = self.fixture()
        effective.write_text(effective.read_text() + "CONFIG_KUNIT\n")
        with self.assertRaisesRegex(EvidenceError, "malformed-config-entry"):
            verify_config("enabled", request, effective, manifest)

    def test_missing_or_nonexecuted(self):
        request, effective, manifest = self.fixture()
        effective.unlink()
        with self.assertRaisesRegex(EvidenceError, "missing-or-symlink-evidence"):
            verify_config("enabled", request, effective, manifest)
        request, effective, manifest = self.fixture()
        manifest.write_text(manifest.read_text().replace("uml_kunit_exit=0",
                                                        "uml_kunit_exit=1"))
        with self.assertRaisesRegex(EvidenceError, "invalid-uml-execution-precondition"):
            verify_config("enabled", request, effective, manifest)

    def test_pair_never_accepts_missing_or_forged_pass(self):
        self.root.joinpath("enabled.txt").write_text(
            "result=IN_PROGRESS\nresult=PASS\nkunit_cases_passed=5\n")
        with self.assertRaisesRegex(EvidenceError, "missing-or-symlink-evidence"):
            verify_pair(self.root, self.root / "absent_enabled",
                        self.root / "absent_disabled")
        with self.assertRaisesRegex(EvidenceError, "invalid-result-transition"):
            parse_manifest(b"result=PASS\n")
        with self.assertRaisesRegex(EvidenceError, "malformed-or-duplicate-manifest"):
            parse_manifest(b"result=IN_PROGRESS\nkunit_cases_passed=5\n"
                           b"kunit_cases_passed=5\n")


    def test_both_profiles_reject_reused_tap_hash_drift_and_forged_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            configs = []
            case_names = (
                "swap_bio_origin_authentication_test",
                "swap_bio_origin_reset_reuse_reissue_test",
                "swap_bio_origin_clone_test",
                "swap_bio_origin_split_test",
                "swap_bio_origin_merge_reject_test",
            )
            for profile in ("enabled", "disabled"):
                config = root / (profile + ".config")
                config.write_text("\n".join(
                    "# " + name + " is not set" if value == "n"
                    else name + "=" + value
                    for name, value in expected_config(profile).items()) + "\n")
                configs.append(config)
                tap = ("TAP version 14\n1..1\n# Subtest: swap_bio_origin\n1..5\n" +
                       "".join("ok " + str(i) + " - " + name + "\n"
                               for i, name in enumerate(case_names, 1)) +
                       "ok 1 - swap_bio_origin\n# " + profile + "\n")
                output = root / (profile + "-kunit-output.log")
                output.write_text(tap)
                (root / (profile + ".txt")).write_text(
                    "result=IN_PROGRESS\nlinux_sha=" + LINUX_SHA +
                    "\nsource_modified=yes\nrequested_zswap=" +
                    ("y" if profile == "enabled" else "n") +
                    "\numl_kunit_exit=0\nverify_real_tap_exit=0\n" +
                    self.object_fixture_lines(profile) +
                    "uml_objects_sha256=" + object_inventory_digest(parse_manifest(
                        self.object_fixture_lines(profile).encode())) + "\n"
                    "kunit_executed=yes\nkunit_cases_passed=5\n"
                    "uml_config_sha256=" + hashlib.sha256(config.read_bytes()).hexdigest() +
                    "\nkunit_output_sha256=" + hashlib.sha256(tap.encode()).hexdigest() +
                    "\nresult=PASS\n")
            verify_pair(root, *configs)
            disabled_tap = root / "disabled-kunit-output.log"
            disabled_record = root / "disabled.txt"
            real_tap = disabled_tap.read_bytes()
            real_manifest = disabled_record.read_text()
            object_hash = re.search(r"(?m)^object=block/bio\.o sha256=([0-9a-f]{64})$",
                                    real_manifest)
            self.assertIsNotNone(object_hash)
            drifted = real_manifest.replace(object_hash.group(1), "f" * 64, 1)
            disabled_record.write_text(drifted)
            with self.assertRaisesRegex(EvidenceError, "object-digest-drift"):
                verify_pair(root, *configs)
            disabled_record.write_text(real_manifest)
            disabled_tap.write_bytes((root / "enabled-kunit-output.log").read_bytes())
            copied_hash = hashlib.sha256(disabled_tap.read_bytes()).hexdigest()
            disabled_record.write_text(re.sub(
                r"kunit_output_sha256=[0-9a-f]{64}",
                "kunit_output_sha256=" + copied_hash, real_manifest))
            with self.assertRaisesRegex(EvidenceError, "reused-profile-config-or-tap"):
                verify_pair(root, *configs)
            disabled_tap.write_bytes(real_tap)
            disabled_record.write_text(real_manifest)
            disabled_tap.write_bytes(real_tap.replace(b"ok 3 -", b"not ok 3 -"))
            damaged_hash = hashlib.sha256(disabled_tap.read_bytes()).hexdigest()
            disabled_record.write_text(re.sub(
                r"kunit_output_sha256=[0-9a-f]{64}",
                "kunit_output_sha256=" + damaged_hash, real_manifest))
            with self.assertRaisesRegex(EvidenceError, "invalid-real-tap"):
                verify_pair(root, *configs)
            disabled_record.write_text(real_manifest)
            with self.assertRaisesRegex(EvidenceError, "invalid-profile-evidence"):
                verify_pair(root, *configs)
            disabled_tap.write_bytes(real_tap)
            disabled_record.unlink()
            with self.assertRaisesRegex(EvidenceError, "missing-or-symlink"):
                verify_pair(root, *configs)



def main() -> int:
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--verify", action="store_true")
    arguments.add_argument("--verify-pair", action="store_true")
    arguments.add_argument("--request", type=Path)
    arguments.add_argument("--effective", type=Path)
    arguments.add_argument("--manifest", type=Path)
    arguments.add_argument("--profile", choices=("enabled", "disabled"))
    arguments.add_argument("--evidence", type=Path)
    arguments.add_argument("--enabled-config", type=Path)
    arguments.add_argument("--disabled-config", type=Path)
    options = arguments.parse_args()
    if options.verify or options.verify_pair:
        try:
            if options.verify and not options.verify_pair and all((
                options.request, options.effective, options.manifest, options.profile)):
                verify_config(options.profile, options.request,
                              options.effective, options.manifest)
            elif options.verify_pair and not options.verify and all((
                options.evidence, options.enabled_config, options.disabled_config)):
                verify_pair(options.evidence, options.enabled_config,
                            options.disabled_config)
            else:
                raise EvidenceError("invalid-cli-arguments")
        except (OSError, UnicodeError, EvidenceError) as error:
            print("FAIL: pinned-uml-config " + str(error), file=sys.stderr)
            return 1
        return 0
    unittest.main(argv=[sys.argv[0]], verbosity=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
