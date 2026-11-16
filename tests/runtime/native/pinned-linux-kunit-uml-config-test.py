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
CONFIG_VALUE = re.compile(r"^(CONFIG_[A-Z0-9_]+)=(.+)$")
CONFIG_UNSET = re.compile(r"^# (CONFIG_[A-Z0-9_]+) is not set$")


class EvidenceError(ValueError):
    """Rootless or hosted evidence must fail closed."""


def read_evidence(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise EvidenceError("missing-or-symlink-evidence")
    size = path.stat().st_size
    if not 0 < size <= maximum:
        raise EvidenceError("empty-or-oversized-evidence")
    return path.read_bytes()


def parse_config(data: bytes) -> dict[str, str]:
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeError as error:
        raise EvidenceError("non-utf8-config") from error
    values = {}
    for line in lines:
        set_match = CONFIG_VALUE.fullmatch(line)
        unset_match = CONFIG_UNSET.fullmatch(line)
        if set_match:
            name, value = set_match.groups()
        elif unset_match:
            name, value = unset_match.group(1), "n"
        elif line.startswith(("CONFIG_", "# CONFIG_")):
            raise EvidenceError("malformed-config-entry")
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
    request_values = parse_config(requested)
    actual_values = parse_config(effective)
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
        if not separator or not name or (name in record and name != "result"):
            raise EvidenceError("malformed-or-duplicate-manifest")
        if name == "result":
            transitions.append(value)
            if transitions not in (["IN_PROGRESS"], ["IN_PROGRESS", "PASS"],
                                   ["IN_PROGRESS", "FAIL"]):
                raise EvidenceError("invalid-result-transition")
        record[name] = value
    return record


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
    # Record both digests even when the very next Kconfig check fails.
    with manifest_path.open("a", encoding="utf-8") as output:
        output.write("uml_config_sha256=" +
                     hashlib.sha256(effective).hexdigest() + "\n")
        output.write("uml_request_sha256=" +
                     hashlib.sha256(requested).hexdigest() + "\n")
    check_config(profile, requested, effective)


def verify_pair(evidence: Path, enabled: Path, disabled: Path) -> None:
    config_digests = set()
    tap_digests = set()
    for profile, config_path in (("enabled", enabled), ("disabled", disabled)):
        manifest = parse_manifest(read_evidence(evidence / (profile + ".txt"),
                                                CONFIG_LIMIT))
        config = read_evidence(config_path, CONFIG_LIMIT)
        tap = read_evidence(evidence / (profile + "-kunit-output.log"), TAP_LIMIT)
        config_sha = hashlib.sha256(config).hexdigest()
        tap_sha = hashlib.sha256(tap).hexdigest()
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
                            "\numl_kunit_exit=0\n")
        return request, effective, manifest

    def test_positive_y_and_n(self):
        for profile in ("enabled", "disabled"):
            request, effective, manifest = self.fixture(profile)
            verify_config(profile, request, effective, manifest)
            self.assertIn(hashlib.sha256(effective.read_bytes()).hexdigest(),
                          manifest.read_text())

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
                    "\numl_kunit_exit=0\nverify_real_tap_exit=0\n"
                    "kunit_executed=yes\nkunit_cases_passed=5\n"
                    "uml_config_sha256=" + hashlib.sha256(config.read_bytes()).hexdigest() +
                    "\nkunit_output_sha256=" + hashlib.sha256(tap.encode()).hexdigest() +
                    "\nresult=PASS\n")
            verify_pair(root, *configs)
            disabled_tap = root / "disabled-kunit-output.log"
            disabled_record = root / "disabled.txt"
            real_tap = disabled_tap.read_bytes()
            real_manifest = disabled_record.read_text()
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
