#!/usr/bin/env python3
"""Round022 source-only imported-zswap decoder C regression; NEVER loaded proof."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
HEADER = ROOT / "src/kernel/zswap-import-codec.h"
CODEC = ROOT / "src/kernel/codec.c"
CODEC_HEADER = ROOT / "src/kernel/codec.h"
TARGET = ROOT / "src/kernel/dm-target.c"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round022-consumer-codec.c"


class ImportedZswapLz4SourceOnly(unittest.TestCase):
    def test_distinct_ram_only_record_is_not_live_raw(self) -> None:
        header = HEADER.read_text(encoding="utf-8")
        codec = CODEC_HEADER.read_text(encoding="utf-8")
        target = TARGET.read_text(encoding="utf-8")
        self.assertIn("#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U", header)
        self.assertIn("#define SWAPZ_ZSWAP_IMPORT_REPRESENTATION 0x5aU", header)
        self.assertIn("SWAPZ_ZSWAP_IMPORT_LZ4_CODEC 1U", header)
        self.assertIn("SWAPZ_MAX_COMPRESSED", header)
        self.assertIn("#define SWAPZ_MAX_COMPRESSED 3568U", codec)
        self.assertIn("#define SWAPZ_CODEC_METADATA_ON_MEDIA 0U", codec)
        self.assertNotIn('"zswap-import-codec.h"', target)
        self.assertNotIn("SWAPZ_ZSWAP_IMPORT_REPRESENTATION", target)
        self.assertIn("swapz_crc32c_bytes", CODEC.read_text(encoding="utf-8"))
        self.assertIn("LZ4_decompress_safe", header)
        self.assertIn("original_sha256", header)
        self.assertIn("actual_lower_read_bytes", header)
        self.assertIn("upper_write_ack_count != 1U", header)
        self.assertIn("memcpy(output, scratch, SWAPZ_BLOCK_BYTES);", header)
        self.assertIn("SWAPZ_BLOCK_BYTES", target)

    def test_exact_production_crc32c_and_real_lz4_decoder_gcc_clang(self) -> None:
        compilers = [compiler for compiler in ("gcc", "clang") if shutil.which(compiler)]
        self.assertTrue(compilers, "a real C compiler is required")
        with tempfile.TemporaryDirectory() as directory:
            for compiler in compilers:
                with self.subTest(compiler=compiler):
                    executable = Path(directory) / compiler
                    command = [compiler, "-std=gnu11", "-O1", "-g", "-Wall",
                               "-Wextra", "-Werror", "-Wconversion", "-Wshadow",
                               "-fsanitize=address,undefined",
                               "-fno-sanitize-recover=all", "-I", str(HEADER.parent),
                               str(FIXTURE), str(CODEC), "-llz4", "-lcrypto",
                               "-o", str(executable)]
                    built = subprocess.run(command, capture_output=True,
                                           text=True, timeout=60, check=False)
                    self.assertEqual(built.returncode, 0,
                                     f"{compiler} compile: {built.stderr}")
                    executed = subprocess.run([str(executable)], capture_output=True,
                                              text=True, timeout=40, check=False)
                    self.assertEqual(executed.returncode, 0,
                                     f"{compiler} execute: {executed.stderr}")
                    self.assertEqual(executed.stdout.strip(),
                                     "ROUND022_CONSUMER_ROOTLESS_SOURCE_ONLY_PASS")


if __name__ == "__main__":
    unittest.main(verbosity=2)
