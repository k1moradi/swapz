#!/usr/bin/env python3
"""Rootless adversarial tests for GNU worker build-record binding.

All binary outputs are private ordinary files containing synthetic bytes.
These cases test record reconciliation only; they are not GNU binaries and
are never executed or accepted as production artifacts.
"""

from __future__ import annotations

import hashlib
import copy
import importlib.util
import json
import os
from pathlib import Path
import platform
import stat
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "recall_gnu_dd_seccomp_qualification_tested", HERE / "recall-gnu-dd-seccomp-qualification.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load GNU worker qualification runner")
qualification_runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = qualification_runner
SPEC.loader.exec_module(qualification_runner)


class BuildRecordBindingTests(unittest.TestCase):
    SOURCE_SHA = "394024eda0a5955217ceda9cd1201e65dc8fa3aa29c2951135a49521d57c3cc3"

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="swapz-gnu-build-record-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "build"
        self.output.mkdir(mode=0o700)
        self.paths = []
        self.record_path = self.output / "qualification-record.json"
        self.record = self._record()
        self.baseline_record = copy.deepcopy(self.record)
        self._write_record()

    def _write_record(self, payload: str | None = None) -> None:
        data = payload if payload is not None else json.dumps(self.record, sort_keys=True)
        self.record_path.write_text(data)
        self.record_path.chmod(0o600)

    def _tool(self, name: str) -> dict:
        return {
            "requested_path": f"/usr/bin/{name}", "resolved_path": f"/usr/bin/{name}",
            "sha256": "a" * 64, "size": 100, "mode": "0755",
            "owner_uid": os.geteuid(), "version": f"test-only {name} identity",
        }

    def _source(self) -> dict:
        release = qualification_runner.provenance.RELEASES["9.11"]
        return {
            "schema": "swapz.gnu-coreutils-source.v1", "release": "9.11",
            "archive_name": release["archive_name"], "archive_sha256": self.SOURCE_SHA,
            "signature_sha256": "b" * 64, "gnu_keyring_sha256": "c" * 64,
            "gpg_verifier": {
                "requested_path": "/usr/bin/gpg", "resolved_path": "/usr/bin/gpg",
                "sha256": "d" * 64, "size": 100, "mode": "0755",
                "owner_uid": os.geteuid(), "version": "test-only gpg identity",
            },
            "published_sha256_base64": release["archive_sha256_b64"],
            "release_signer_fingerprint": release["signer_fingerprint"],
            "release_signature_epoch": release["signature_epoch"],
            "release_commit": release["release_commit"],
            "source_authentication": "GNU detached signature verified; full key fingerprint pinned",
            "archive_layout": {
                "top_level_directory": "coreutils-9.11",
                "configure_identity": "GNU coreutils 9.11",
            },
            "release_announcement": release["announcement"],
            "archive_url": release["archive_url"], "signature_url": release["signature_url"],
            "trust_note": (
                "This authenticates the GNU release source archive, not any locally built binary or production application key."
            ),
        }

    def _binary_record(self, path: Path) -> dict:
        info = path.stat(follow_symlinks=False)
        return {
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": info.st_size, "mode": format(stat.S_IMODE(info.st_mode), "04o"),
            "owner_uid": info.st_uid, "link_count": info.st_nlink,
            "device": info.st_dev, "inode": info.st_ino,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns,
            "elf": {
                "elf_class": "ELF64", "endianness": "little",
                "machine": platform.machine(), "elf_type": "ET_EXEC", "static": True,
            },
            "candidate_executed_during_inspection": False,
            "setid_bits": False, "file_capabilities": False,
            "pinned_descriptor_path_rechecked": True,
        }

    def _record(self) -> dict:
        outputs = []
        for index, relative in enumerate(qualification_runner._OUTPUT_PATHS, 1):
            path = self.output / relative
            path.parent.mkdir(mode=0o700, parents=True)
            path.write_bytes(b"synthetic fixture bytes, never execute\n")
            path.chmod(0o755)
            self.paths.append(path)
            outputs.append({"path": relative, "binary": self._binary_record(path)})
        digests = [item["binary"]["sha256"] for item in outputs]
        release = qualification_runner.provenance.RELEASES["9.11"]
        tools = {key: self._tool(name) for key, name in (
            ("gcc", "gcc"), ("make", "make"), ("linker", "ld"),
            ("assembler", "as"), ("archiver", "ar"), ("ranlib", "ranlib"), ("tar", "tar"),
        )}
        return {
            "schema": "swapz.gnu-coreutils-dd-build.v1",
            "qualification": "source authenticated; two same-host clean builds compared",
            "source": self._source(),
            "build_recipe": {
                "configure": ["./configure", "--disable-nls", "--disable-acl", "--without-selinux"],
                "make": ["/usr/bin/make", "-j2"],
                "environment": {
                    "CC": "/usr/bin/gcc", "CFLAGS": "-O2 -g0 -ffile-prefix-map=<source-tree>=.",
                    "LDFLAGS": "-static", "LC_ALL": "C", "LANG": "C", "TZ": "UTC",
                    "SOURCE_DATE_EPOCH": str(release["source_date_epoch"]),
                },
                "install_or_system_changes": False,
            },
            "toolchain": {
                "python": "3.test-only", "architecture": platform.machine(),
                "host_platform": "Linux-test-only", "kernel_release": "test-only",
                **tools, "compiler_target": "test-only", "static_libc_archive": "/test/libc.a",
            },
            "binary": outputs[0]["binary"], "outputs": outputs,
            "rebuild_comparison": {
                "build_count": 2, "sha256_by_build": digests,
                "same_host_byte_identical": digests[0] == digests[1],
                "independent_builder_reproduction": "not performed",
            },
            "build_logs": [
                {"configure_log_sha256": "e" * 64, "build_log_sha256": "f" * 64},
                {"configure_log_sha256": "1" * 64, "build_log_sha256": "2" * 64},
            ],
            "worker_seccomp_execution": "NOT RUN by build command",
            "production_manifest_or_key_installed": False,
        }

    def _read(self, candidate: Path | None = None):
        return qualification_runner._read_build_attestation(
            self.record_path, candidate or self.paths[0], self.SOURCE_SHA,
        )

    def test_both_output_descriptors_are_hashed_and_matching_record_is_accepted(self) -> None:
        record, _bytes, digest, identity = self._read()
        self.assertEqual(record["schema"], "swapz.gnu-coreutils-dd-build.v1")
        self.assertEqual(digest, hashlib.sha256(self.paths[0].read_bytes()).hexdigest())
        self.assertEqual(identity["inode"], self.paths[0].stat().st_ino)

    def test_arbitrary_candidate_path_is_rejected(self) -> None:
        candidate = self.root / "unrelated-dd"
        candidate.write_text("not executable code")
        with self.assertRaisesRegex(RuntimeError, "not one of the two"):
            self._read(candidate)

    def test_missing_second_build_output_is_rejected(self) -> None:
        self.paths[1].unlink()
        with self.assertRaises(OSError):
            self._read()

    def test_real_bytes_must_match_forged_recorded_digest_array(self) -> None:
        forged = "9" * 64
        self.record["binary"]["sha256"] = forged
        self.record["outputs"][0]["binary"]["sha256"] = forged
        self.record["outputs"][1]["binary"]["sha256"] = forged
        self.record["rebuild_comparison"]["sha256_by_build"] = [forged, forged]
        self._write_record()
        with self.assertRaisesRegex(RuntimeError, "bytes do not match"):
            self._read()

    def test_second_output_symlink_is_rejected(self) -> None:
        self.paths[1].unlink()
        self.paths[1].symlink_to(self.paths[0])
        with self.assertRaises(OSError):
            self._read()

    def test_output_metadata_mutation_is_rejected(self) -> None:
        os.utime(self.paths[0], ns=(self.paths[0].stat().st_atime_ns,
                                    self.paths[0].stat().st_mtime_ns + 1_000_000))
        with self.assertRaisesRegex(RuntimeError, "metadata differs"):
            self._read()

    def test_forged_digest_array_and_rebuild_claims_are_rejected(self) -> None:
        self.record["rebuild_comparison"]["sha256_by_build"] = ["0" * 64, "0" * 64]
        self._write_record()
        with self.assertRaisesRegex(RuntimeError, "rebuild comparison"):
            self._read()
        self.record = copy.deepcopy(self.baseline_record)
        self.record["rebuild_comparison"]["independent_builder_reproduction"] = "verified"
        self._write_record()
        with self.assertRaisesRegex(RuntimeError, "rebuild comparison"):
            self._read()

    def test_substituted_output_path_and_malformed_shapes_are_rejected(self) -> None:
        self.record["outputs"][1]["path"] = qualification_runner._OUTPUT_PATHS[0]
        self._write_record()
        with self.assertRaisesRegex(RuntimeError, "path is missing"):
            self._read()
        self.record = copy.deepcopy(self.baseline_record)
        self.record["outputs"][1]["binary"]["size"] = True
        self._write_record()
        with self.assertRaisesRegex(RuntimeError, "metadata is malformed"):
            self._read()
        self.record = copy.deepcopy(self.baseline_record)
        self.record["unexpected"] = "extra"
        self._write_record()
        with self.assertRaisesRegex(RuntimeError, "missing, extra"):
            self._read()

    def test_duplicate_json_keys_and_wrong_source_are_rejected(self) -> None:
        self._write_record('{"schema":"bad","schema":"swapz.gnu-coreutils-dd-build.v1"}')
        with self.assertRaisesRegex(ValueError, "duplicate qualification-record key"):
            self._read()
        self.record = copy.deepcopy(self.baseline_record)
        self._write_record()
        with self.assertRaisesRegex(RuntimeError, "source identity"):
            qualification_runner._read_build_attestation(
                self.record_path, self.paths[0], "a" * 64,
            )

    def test_same_host_builds_are_not_upgraded_to_independent_reproduction(self) -> None:
        self.assertEqual(self.record["rebuild_comparison"]["build_count"], 2)
        self.assertEqual(self.record["rebuild_comparison"]["independent_builder_reproduction"],
                         "not performed")
        self.assertFalse(self.record["production_manifest_or_key_installed"])
        self._read()


if __name__ == "__main__":
    unittest.main(verbosity=2)
