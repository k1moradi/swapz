#!/usr/bin/env python3
"""Rootless adversarial tests for GNU worker build-record binding."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
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
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="swapz-gnu-build-record-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "build"
        self.binary = self.output / "copy-1/source/coreutils-9.11/src/dd"
        self.binary.parent.mkdir(parents=True)
        self.binary.write_bytes(b"test fixture only; never executed")
        second = self.output / "copy-2/source/coreutils-9.11/src/dd"
        second.parent.mkdir(parents=True)
        second.write_bytes(b"test fixture only; never executed")
        self.record_path = self.output / "qualification-record.json"
        self.source_sha256 = "a" * 64
        self.binary_sha256 = "b" * 64
        self.record = {
            "schema": "swapz.gnu-coreutils-dd-build.v1",
            "source": {"release": "9.11", "archive_sha256": self.source_sha256},
            "rebuild_comparison": {"build_count": 2, "same_host_byte_identical": True},
            "binary": {"sha256": self.binary_sha256},
        }
        self._write_record()

    def _write_record(self, payload: str | None = None) -> None:
        data = payload if payload is not None else json.dumps(self.record)
        self.record_path.write_text(data)

    def test_matching_authenticated_source_and_recorded_output_are_accepted(self) -> None:
        record, _bytes, digest = qualification_runner._read_build_attestation(
            self.record_path, self.binary, self.source_sha256,
        )
        self.assertEqual(record["schema"], "swapz.gnu-coreutils-dd-build.v1")
        self.assertEqual(digest, self.binary_sha256)

    def test_arbitrary_binary_path_is_rejected_before_candidate_execution(self) -> None:
        candidate = self.root / "unrelated-dd"
        candidate.write_text("this is not executable code")
        with self.assertRaisesRegex(RuntimeError, "not one of the recorded"):
            qualification_runner._read_build_attestation(
                self.record_path, candidate, self.source_sha256,
            )

    def test_wrong_source_digest_and_nonreproducible_record_are_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "verified source"):
            qualification_runner._read_build_attestation(
                self.record_path, self.binary, "c" * 64,
            )
        self.record["rebuild_comparison"]["same_host_byte_identical"] = False
        self._write_record()
        with self.assertRaisesRegex(RuntimeError, "two identical GNU"):
            qualification_runner._read_build_attestation(
                self.record_path, self.binary, self.source_sha256,
            )

    def test_duplicate_keys_and_invalid_binary_digest_are_rejected(self) -> None:
        self._write_record('{"schema":"bad","schema":"swapz.gnu-coreutils-dd-build.v1"}')
        with self.assertRaisesRegex(ValueError, "duplicate qualification-record key"):
            qualification_runner._read_build_attestation(
                self.record_path, self.binary, self.source_sha256,
            )
        self.record["binary"]["sha256"] = "not-a-digest"
        self._write_record()
        with self.assertRaisesRegex(RuntimeError, "two identical GNU"):
            qualification_runner._read_build_attestation(
                self.record_path, self.binary, self.source_sha256,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
