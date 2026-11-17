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
        # Only the explicitly opt-in Round028 helpers may name compressed
        # representation constants. Ordinary production has no such ingress.
        active = target.split("#if defined(SWAPZ_ROUND028_DM_OWNED_READBACK_TEST)", 1)
        self.assertEqual(len(active), 2)
        guarded, after = active[1].split(
            "#endif /* SWAPZ_ROUND028_DM_OWNED_READBACK_TEST */", 1)
        self.assertIn("SWAPZ_ZSWAP_IMPORT_REPRESENTATION", guarded)
        self.assertNotIn("SWAPZ_ZSWAP_IMPORT_REPRESENTATION",
                         active[0] + after)
        self.assertIn("swapz_crc32c_bytes", CODEC.read_text(encoding="utf-8"))
        self.assertIn("LZ4_decompress_safe", header)
        self.assertIn("original_sha256", header)
        self.assertIn("actual_lower_read_bytes", header)
        self.assertIn("upper_write_ack_count != 1U", header)
        self.assertIn("memcpy(output, scratch, SWAPZ_BLOCK_BYTES);", header)
        self.assertIn("SWAPZ_BLOCK_BYTES", target)

    def test_round028_actual_dm_owned_lower_stage_gcc_clang(self) -> None:
        """Compile and execute the exact new DM C, never a copied algorithm."""
        source = TARGET.read_text(encoding="utf-8")
        start = "/* ROUND028_DM_OWNED_STAGE_START */"
        end = "/* ROUND028_DM_OWNED_STAGE_END */"
        self.assertEqual(source.count(start), 1)
        self.assertEqual(source.count(end), 1)
        actual = source.split(start, 1)[1].split(end, 1)[0]
        self.assertIn("swapz_round028_dm_stage_owned_payload(", actual)
        self.assertIn("memset(lower_image, 0, extent_bytes);", actual)
        self.assertIn("swapz_crc32c_bytes(", actual)
        self.assertNotIn("bio_endio(", actual)
        self.assertNotIn("swapz_lower_write(", actual)
        self.assertIn("swapz_round028_dm_owned_lower_readback(", source)
        self.assertIn("swapz_round026_dm_capture_read_snapshot(ctx, logical_page, &before)", source)
        self.assertIn("swapz_lower_read(ctx, before.mapping.start_block,", source)
        self.assertIn("before.extent_sequence != after.extent_sequence", source)
        self.assertIn("swapz_zswap_admission_read_4096(transaction, logical_page,", source)
        fixture = (ROOT / "tests/runtime/native/fixtures/"
                   "round028-consumer-owned-stage.c").read_text(encoding="utf-8")
        self.assertEqual(fixture.count("/* ROUND028_DM_EXACT_STAGE_SOURCE */"), 1)
        fixture = fixture.replace("/* ROUND028_DM_EXACT_STAGE_SOURCE */",
                                  actual, 1)
        with tempfile.TemporaryDirectory(prefix="round028-owned-stage-") as directory:
            for compiler in ("gcc", "clang"):
                if not shutil.which(compiler):
                    continue
                with self.subTest(compiler=compiler):
                    root = Path(directory)
                    codec = root / (compiler + "-codec.o")
                    executable = root / (compiler + "-owned-stage")
                    shared = [compiler, "-std=gnu11", "-O1", "-g", "-Wall",
                              "-Wextra", "-Wshadow", "-Werror",
                              "-fsanitize=address,undefined",
                              "-fno-sanitize-recover=all"]
                    compiled_codec = subprocess.run(
                        [*shared, "-Wno-conversion", "-I", str(HEADER.parent),
                         "-c", str(CODEC), "-o", str(codec)],
                        capture_output=True, text=True, timeout=60, check=False)
                    self.assertEqual(compiled_codec.returncode, 0,
                                     compiled_codec.stderr)
                    source_path = root / (compiler + "-stage.c")
                    source_path.write_text(fixture, encoding="utf-8")
                    built = subprocess.run(
                        [*shared, "-Wconversion", "-I", str(HEADER.parent),
                         str(source_path), str(codec), "-llz4", "-lcrypto",
                         "-o", str(executable)],
                        capture_output=True, text=True, timeout=60, check=False)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    executed = subprocess.run(
                        [str(executable)], capture_output=True, text=True,
                        timeout=40, check=False)
                    self.assertEqual(executed.returncode, 0, executed.stderr)
                    self.assertEqual(executed.stdout.strip(),
                                     "ROUND028_DM_EXACT_OWNED_STAGE_NO_LIVE_PASS")

    def test_exact_production_crc32c_and_real_lz4_decoder_gcc_clang(self) -> None:
        compilers = [compiler for compiler in ("gcc", "clang") if shutil.which(compiler)]
        self.assertTrue(compilers, "a real C compiler is required")
        with tempfile.TemporaryDirectory() as directory:
            for compiler in compilers:
                with self.subTest(compiler=compiler):
                    executable = Path(directory) / compiler
                    # Existing codec.c has unrelated historical
                    # -Wconversion diagnostics; keep all its other warnings
                    # fatal and require -Wconversion on the new C fixture.
                    codec_object = Path(directory) / (compiler + "-codec.o")
                    shared = [compiler, "-std=gnu11", "-O1", "-g", "-Wall",
                              "-Wextra", "-Werror", "-Wshadow",
                              "-fsanitize=address,undefined",
                              "-fno-sanitize-recover=all", "-I",
                              str(HEADER.parent)]
                    compiled_codec = subprocess.run(
                        [*shared, "-Wno-conversion", "-c", str(CODEC),
                         "-o", str(codec_object)], capture_output=True,
                        text=True, timeout=60, check=False)
                    self.assertEqual(compiled_codec.returncode, 0,
                                     f"{compiler} codec compile: {compiled_codec.stderr}")
                    command = [*shared, "-Wconversion", str(FIXTURE),
                               str(codec_object), "-llz4", "-lcrypto",
                               "-o", str(executable)]
                    built = subprocess.run(command, capture_output=True,
                                           text=True, timeout=60, check=False)
                    self.assertEqual(built.returncode, 0,
                                     f"{compiler} fixture compile: {built.stderr}")
                    executed = subprocess.run([str(executable)], capture_output=True,
                                              text=True, timeout=40, check=False)
                    self.assertEqual(executed.returncode, 0,
                                     f"{compiler} execute: {executed.stderr}")
                    self.assertEqual(executed.stdout.strip(),
                                     "ROUND022_CONSUMER_ROOTLESS_SOURCE_ONLY_PASS")


if __name__ == "__main__":
    unittest.main(verbosity=2)
