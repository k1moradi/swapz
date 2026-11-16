#!/usr/bin/env python3
"""Round023 unintegrated DM admission/4096 decode exact-source host regression."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
DM = ROOT / "src/kernel/dm-target.c"
ADMISSION = ROOT / "src/kernel/zswap-import-admission.h"
IMPORTER = ROOT / "src/kernel/zswap-import-codec.h"
CODEC = ROOT / "src/kernel/codec.c"
CODEC_HEADER = ROOT / "src/kernel/codec.h"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round023-consumer-admission.c"


class Round023DisabledConsumerAdmission(unittest.TestCase):
    def test_actual_production_dm_remains_disabled(self) -> None:
        dm = DM.read_text(encoding="utf-8")
        gate = ("#if 0 /* "
                "SWAPZ_ROUND023_COMPRESSED_DM_IMPORT_DISABLED_NO_AUTHENTIC_CARRIER */")
        self.assertEqual(dm.count(gate), 1)
        self.assertEqual(dm.count('#include "zswap-import-admission.h"'), 1)
        self.assertIn("return -EOPNOTSUPP;", dm)
        # The actual importer decoder is not included or used by the DM.
        self.assertNotIn('#include "zswap-import-codec.h"', dm)
        importer = IMPORTER.read_text(encoding="utf-8")
        admission = ADMISSION.read_text(encoding="utf-8")
        self.assertIn("#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U", importer)
        self.assertIn("#define SWAPZ_ZSWAP_IMPORT_ADMISSION_ACTIVE 0U",
                      admission)
        self.assertIn("swapz_zswap_admission_try_live(", admission)
        self.assertIn("swapz_zswap_admission_read_4096(", admission)
        self.assertIn("swapz_zswap_import_decode(", admission)
        self.assertIn("SWAPZ_ZSWAP_ADMISSION_HOST_TEST", admission)
        self.assertIn("SWAPZ_ZSWAP_ADMISSION_ACKED", admission)
        self.assertIn("physical_extent_bytes", admission)
        self.assertIn("post_header_extent_authorized", admission)
        self.assertIn("deterministic_zero_padding", admission)
        self.assertIn("#define SWAPZ_MAX_COMPRESSED 3568U",
                      CODEC_HEADER.read_text(encoding="utf-8"))
        self.assertIn("SWAPZ_CODEC_METADATA_ON_MEDIA 0U",
                      CODEC_HEADER.read_text(encoding="utf-8"))
        self.assertIn("swapz_crc32c_bytes", CODEC.read_text(encoding="utf-8"))

    def test_actual_crc32c_lz4_sha256_and_transaction_gcc_clang(self) -> None:
        compilers = [name for name in ("gcc", "clang") if shutil.which(name)]
        self.assertTrue(compilers, "C compiler is required")
        with tempfile.TemporaryDirectory() as temp:
            for compiler in compilers:
                with self.subTest(compiler=compiler):
                    root = Path(temp)
                    codec_object = root / f"codec-{compiler}.o"
                    executable = root / f"admission-{compiler}"
                    shared = ["-std=gnu11", "-O1", "-g", "-Wall",
                              "-Wextra", "-Werror", "-Wshadow",
                              "-fsanitize=address,undefined",
                              "-fno-sanitize-recover=all"]
                    # Pre-existing codec.c has -Wconversion warnings unrelated
                    # to import; maintain -Werror on all its other warnings.
                    codec_command = [
                        compiler, *shared, "-Wno-conversion",
                        "-I", str(CODEC_HEADER.parent), "-c", str(CODEC),
                        "-o", str(codec_object)]
                    codec_built = subprocess.run(
                        codec_command, capture_output=True, text=True,
                        timeout=60, check=False)
                    self.assertEqual(codec_built.returncode, 0,
                                     codec_built.stderr)
                    fixture_command = [
                        compiler, *shared, "-Wconversion",
                        "-I", str(ADMISSION.parent),
                        str(FIXTURE), str(codec_object), "-llz4", "-lcrypto",
                        "-o", str(executable)]
                    fixture_built = subprocess.run(
                        fixture_command, capture_output=True, text=True,
                        timeout=60, check=False)
                    self.assertEqual(fixture_built.returncode, 0,
                                     fixture_built.stderr)
                    result = subprocess.run(
                        [str(executable)], capture_output=True, text=True,
                        env=dict(os.environ, ASAN_OPTIONS="detect_leaks=1"),
                        timeout=40, check=False)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("ROUND023_DM_ADMISSION_SOURCE_ONLY_PASS",
                                  result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
