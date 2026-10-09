#!/usr/bin/env python3
"""Offline adversarial tests for the GNU source/build qualification helper.

GPG status and synthetic ELF fixtures here are mocked test mechanics only.
They are not GNU release provenance and never enter production trust paths.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import os
from pathlib import Path
import platform
import stat
import sys
import tarfile
import tempfile
import unittest
from unittest import mock


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "swapz_gnu_coreutils_qualification", HERE / "gnu-coreutils-qualification.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load GNU qualification helper")
qualification = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = qualification
SPEC.loader.exec_module(qualification)


EXPECTED_FINGERPRINT = "6C37DC12121A5006BC1DB804DF6FD971306037D9"


def synthetic_elf(*, machine: int | None = None, interpreter: bool = False,
                  dynamic_segment: bool = False) -> bytes:
    if machine is None:
        machine = {"x86_64": 62, "aarch64": 183}.get(platform.machine().lower(), 62)
    header = bytearray(64)
    header[:16] = b"\x7fELF\x02\x01\x01" + bytes(9)
    header[16:18] = (2).to_bytes(2, "little")
    header[18:20] = machine.to_bytes(2, "little")
    header[20:24] = (1).to_bytes(4, "little")
    header[32:40] = (64).to_bytes(8, "little")
    header[52:54] = (64).to_bytes(2, "little")
    header[54:56] = (56).to_bytes(2, "little")
    header[56:58] = (1 if interpreter or dynamic_segment else 0).to_bytes(2, "little")
    body = b""
    if interpreter or dynamic_segment:
        segment_type = 3 if interpreter else 2
        body = segment_type.to_bytes(4, "little") + bytes(52)
    return bytes(header) + body


class GNUQualificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="swapz-gnu-qualification-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _test_tarball(self, version: str) -> bytes:
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w:xz") as archive:
            files = {
                f"coreutils-{version}/configure.ac": b"AC_INIT([GNU coreutils],\n",
                f"coreutils-{version}/.tarball-version": version.encode() + b"\n",
                f"coreutils-{version}/NEWS": f"release {version} (test)\n".encode(),
            }
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o600
                archive.addfile(info, io.BytesIO(data))
        return payload.getvalue()

    def test_valid_signature_status_requires_exact_primary_release_key(self) -> None:
        status = ("[GNUPG:] GOODSIG DF6FD971306037D9 P\u00e1draig\n"
                  f"[GNUPG:] VALIDSIG {EXPECTED_FINGERPRINT} 2026-04-20 1776693733 "
                  f"0 4 0 1 10 00 {EXPECTED_FINGERPRINT}\n")
        result = qualification._parse_valid_signature(status, EXPECTED_FINGERPRINT)
        self.assertEqual(result["primary_fingerprint"], EXPECTED_FINGERPRINT)
        self.assertEqual(result["signature_epoch"], "1776693733")

    def test_wrong_or_ambiguous_signer_is_rejected(self) -> None:
        wrong = "A" * 40
        cases = (
            f"[GNUPG:] VALIDSIG {wrong} 2026-04-20 1776693733 0 4 0 1 10 00 {wrong}\n",
            "[GNUPG:] GOODSIG DF6FD971306037D9 signer\n",
            (f"[GNUPG:] VALIDSIG {EXPECTED_FINGERPRINT} 2026-04-20 1776693733 "
             f"0 4 0 1 10 00 {wrong}\n"),
            (f"[GNUPG:] VALIDSIG {EXPECTED_FINGERPRINT} 2026-04-20 1776693733 "
             f"0 4 0 1 10 00 {EXPECTED_FINGERPRINT}\n" * 2),
        )
        for status in cases:
            with self.subTest(status=status), self.assertRaises(qualification.QualificationError):
                qualification._parse_valid_signature(status, EXPECTED_FINGERPRINT)

    def test_source_verifier_binds_release_checksum_signature_and_archive_identity(self) -> None:
        version = "unit"
        archive = self._test_tarball(version)
        archive_path = self.root / "unit.tar.xz"
        signature_path = self.root / "unit.tar.xz.sig"
        keyring_path = self.root / "gnu-keyring.gpg"
        archive_path.write_bytes(archive)
        signature_path.write_bytes(b"test signature")
        keyring_path.write_bytes(b"test public keyring")
        test_spec = {
            "archive_name": "unit.tar.xz",
            "archive_sha256_b64": __import__("base64").b64encode(
                hashlib.sha256(archive).digest()).decode(),
            "signer_fingerprint": EXPECTED_FINGERPRINT,
            "signer_keyid": EXPECTED_FINGERPRINT[-16:],
            "release_commit": "test-only", "signature_epoch": 12345,
            "source_date_epoch": 12345,
            "announcement": "https://example.invalid/test-only",
            "archive_url": "https://example.invalid/test-only.tar.xz",
            "signature_url": "https://example.invalid/test-only.tar.xz.sig",
        }
        mocked_status = {"signer_fingerprint": EXPECTED_FINGERPRINT,
                         "primary_fingerprint": EXPECTED_FINGERPRINT,
                         "signature_epoch": "12345"}
        mocked_gpg = {"requested_path": "/usr/bin/gpg", "resolved_path": "/usr/bin/gpg",
                      "sha256": "f" * 64, "version": "GPG test double"}
        with mock.patch.dict(qualification.RELEASES, {version: test_spec}), \
                mock.patch.object(qualification, "_run_gpg", return_value=mocked_status), \
                mock.patch.object(qualification, "_tool_identity", return_value=mocked_gpg):
            record = qualification.verify_source_archive(
                archive_path, signature_path, keyring_path, version)
        self.assertEqual(record["archive_sha256"], hashlib.sha256(archive).hexdigest())
        self.assertEqual(record["signature_sha256"], hashlib.sha256(b"test signature").hexdigest())
        self.assertEqual(record["gpg_verifier"], mocked_gpg)
        self.assertEqual(record["release"], version)
        self.assertIn("not any locally built binary", record["trust_note"])

    def test_source_verifier_rejects_tampering_and_symlink_inputs(self) -> None:
        version = "unit"
        archive = self._test_tarball(version)
        archive_path = self.root / "unit.tar.xz"
        signature_path = self.root / "unit.tar.xz.sig"
        keyring_path = self.root / "gnu-keyring.gpg"
        archive_path.write_bytes(archive + b"tamper")
        signature_path.write_bytes(b"signature")
        keyring_path.write_bytes(b"keyring")
        test_spec = {
            "archive_name": "unit.tar.xz", "archive_sha256_b64": "AA==",
            "signer_fingerprint": EXPECTED_FINGERPRINT,
            "signer_keyid": EXPECTED_FINGERPRINT[-16:], "release_commit": "test",
            "signature_epoch": 12345, "source_date_epoch": 12345,
            "announcement": "https://example.invalid", "archive_url": "https://example.invalid",
            "signature_url": "https://example.invalid",
        }
        with mock.patch.dict(qualification.RELEASES, {version: test_spec}), \
                self.assertRaisesRegex(qualification.QualificationError, "SHA-256"):
            qualification.verify_source_archive(archive_path, signature_path, keyring_path, version)
        symlink = self.root / "archive-link"
        symlink.symlink_to(archive_path)
        with self.assertRaisesRegex(qualification.QualificationError, "cannot open regular"):
            qualification._read_regular(symlink, maximum=1024 * 1024)

    def _candidate(self, content: bytes, *, mode: int = 0o700) -> Path:
        candidate = self.root / "candidate-dd"
        candidate.write_bytes(content)
        candidate.chmod(mode)
        return candidate

    def test_inspection_never_executes_candidate_and_only_checks_static_elf(self) -> None:
        candidate = self._candidate(synthetic_elf())
        marker = self.root / "untrusted-payload-ran"

        def malicious_exec_attempt(*_args, **_kwargs):
            marker.write_text("candidate executed")
            raise AssertionError("candidate execution must not be attempted")

        # Synthetic ELF bytes model an untrusted candidate that passed the
        # structural stage. If qualification tries --version, the mock
        # records that attempted execution as a payload side effect.
        with mock.patch.object(qualification.subprocess, "run",
                               side_effect=malicious_exec_attempt) as execute:
            record = qualification._inspect_binary(candidate)
        execute.assert_not_called()
        self.assertFalse(marker.exists())
        self.assertTrue(record["elf"]["static"])
        self.assertFalse(record["candidate_executed_during_inspection"])

        with mock.patch.object(qualification.subprocess, "run") as execute:
            with self.assertRaisesRegex(qualification.QualificationError, "differs from its build record"):
                qualification._inspect_binary(candidate, expected_sha256="f" * 64)
        execute.assert_not_called()

        dynamic = self._candidate(synthetic_elf(interpreter=True))
        with self.assertRaisesRegex(qualification.QualificationError, "PT_INTERP"):
            qualification._inspect_binary(dynamic)

        dynamic_without_interpreter = self._candidate(synthetic_elf(dynamic_segment=True))
        with self.assertRaisesRegex(qualification.QualificationError, "PT_DYNAMIC"):
            qualification._inspect_binary(dynamic_without_interpreter)

        wrong_arch = self._candidate(synthetic_elf(machine=3))
        with self.assertRaisesRegex(qualification.QualificationError, "architecture"):
            qualification._inspect_binary(wrong_arch)

    def test_candidate_rejects_setid_capability_and_path_replace(self) -> None:
        setid = self._candidate(synthetic_elf(), mode=0o4700)
        with self.assertRaisesRegex(qualification.QualificationError, "metadata"):
            qualification._inspect_binary(setid)

        writable = self._candidate(synthetic_elf(), mode=0o770)
        with self.assertRaisesRegex(qualification.QualificationError, "metadata"):
            qualification._inspect_binary(writable)

        candidate = self._candidate(synthetic_elf())
        with mock.patch.object(qualification.os, "getxattr", return_value=b"capability"):
            with self.assertRaisesRegex(qualification.QualificationError, "capabilities"):
                qualification._inspect_binary(candidate)

        replacement = self.root / "replacement"
        replacement.write_bytes(synthetic_elf())
        original_stat = qualification.os.stat
        replaced = False

        def replace_path(path, *args, **kwargs):
            nonlocal replaced
            if Path(path) == candidate and not replaced:
                replaced = True
                candidate.unlink()
                replacement.rename(candidate)
            return original_stat(path, *args, **kwargs)
        with mock.patch.object(qualification.os, "stat", side_effect=replace_path):
            with self.assertRaisesRegex(qualification.QualificationError, "changed during"):
                qualification._inspect_binary(candidate)

    def test_build_tool_identity_requires_nonwritable_uncapable_file(self) -> None:
        tool = self.root / "test-build-tool"
        tool.write_text("#!/bin/sh\necho test-build-tool 1.0\n")
        tool.chmod(0o755)
        with mock.patch.object(qualification.os, "getxattr", side_effect=OSError(61, "no data")):
            identity = qualification._tool_identity(str(tool))
        self.assertEqual(identity["version"], "test-build-tool 1.0")
        self.assertEqual(identity["mode"], "0755")

        tool.chmod(0o775)
        with self.assertRaisesRegex(qualification.QualificationError, "owner-controlled"):
            qualification._tool_identity(str(tool))

        tool.chmod(0o755)
        with mock.patch.object(qualification.os, "getxattr", return_value=b"file capability"):
            with self.assertRaisesRegex(qualification.QualificationError, "file capabilities"):
                qualification._tool_identity(str(tool))


if __name__ == "__main__":
    unittest.main(verbosity=2)
