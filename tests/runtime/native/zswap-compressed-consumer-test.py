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
        # Round030 is a second explicit, unreferenced CI-only gate.
        later = after.split(
            "#if defined(SWAPZ_ROUND030_DM_COMPRESSED_COMMIT_TEST)", 1)
        self.assertEqual(len(later), 2)
        guarded_round030, ordinary = later[1].split(
            "#endif /* SWAPZ_ROUND030_DM_COMPRESSED_COMMIT_TEST */", 1)
        self.assertIn("SWAPZ_ZSWAP_IMPORT_REPRESENTATION", guarded_round030)
        # Round031 is an independent further CI-only sidecar gate, never a
        # default consumer of arbitrary upper BIO or RAW_4096 bytes.
        sidecar = ordinary.split(
            "#if defined(SWAPZ_ROUND031_DM_LZ4_SIDECAR_TEST)", 1)
        self.assertEqual(len(sidecar), 2)
        guarded_round031, ordinary_tail = sidecar[1].split(
            "#endif /* SWAPZ_ROUND031_DM_LZ4_SIDECAR_TEST */", 1)
        self.assertIn("SWAPZ_ROUND031_SOURCE_LZ4_TAG", guarded_round031)
        self.assertIn("swapz_round031_dm_read_with_sidecar(", guarded_round031)
        self.assertNotIn("SWAPZ_ZSWAP_IMPORT_REPRESENTATION",
                         active[0] + later[0] + sidecar[0] + ordinary_tail)
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

    def test_round030_source_attached_dm_ordered_commit_gcc_clang(self) -> None:
        """Run exact production DM transaction body with fake lower I/O only."""
        source = TARGET.read_text(encoding="utf-8")
        start = "/* ROUND030_DM_COMMIT_EXACT_START */"
        end = "/* ROUND030_DM_COMMIT_EXACT_END */"
        self.assertEqual(source.count(start), 1)
        self.assertEqual(source.count(end), 1)
        actual = source.split(start, 1)[1].split(end, 1)[0]
        for fragment in (
            "swapz_round030_dm_commit_owned_lz4(",
            "swapz_round030_dm_read_owned_lz4(",
            "swapz_stage(&ctx->authority, &logical_page, 1U,",
            "swapz_bind_compressed_record(",
            "swapz_mark_compressed_data_only(&ctx->authority, staged)",
            "swapz_lower_write(ctx, staged->start_block, extent_blocks,",
            "swapz_finish(&ctx->authority, staged, lower_image,",
            "swapz_extent_sequence_lookup(&ctx->authority,",
            "swapz_round028_dm_owned_lower_readback(",
            "swapz_zswap_admission_try_live(NULL)",
        ):
            self.assertIn(fragment, actual)
        self.assertNotIn("\tbio_endio(", actual)
        self.assertNotIn("\tswapz_map(", actual)
        fixture = (ROOT / "tests/runtime/native/fixtures" /
                   "round030-consumer-commit.c").read_text(encoding="utf-8")
        token = "/* ROUND030_EXACT_DM_COMMIT_SOURCE */"
        self.assertEqual(fixture.count(token), 1)
        fixture = fixture.replace(token, actual, 1)
        with tempfile.TemporaryDirectory(prefix="round030-dm-commit-") as directory:
            compilers = [name for name in ("gcc", "clang") if shutil.which(name)]
            self.assertTrue(compilers)
            for compiler in compilers:
                with self.subTest(compiler=compiler):
                    output = Path(directory) / compiler
                    codec = Path(directory) / (compiler + "-codec.o")
                    source_file = Path(directory) / (compiler + ".c")
                    source_file.write_text(fixture, encoding="utf-8")
                    shared = [compiler, "-std=gnu11", "-O1", "-g", "-Wall",
                              "-Wextra", "-Wshadow", "-Werror",
                              "-fsanitize=address,undefined",
                              "-fno-sanitize-recover=all", "-I",
                              str(HEADER.parent)]
                    # codec.c has existing, independently tested conversion
                    # diagnostics; NEW extracted C is -Wconversion/-Werror.
                    codec_build = subprocess.run([
                        *shared, "-Wno-conversion", "-c", str(CODEC),
                        "-o", str(codec)], capture_output=True, text=True,
                        timeout=60, check=False)
                    self.assertEqual(codec_build.returncode, 0,
                                     codec_build.stderr)
                    build = subprocess.run([
                        *shared, "-Wconversion", str(source_file), str(codec),
                        "-llz4", "-lcrypto", "-o", str(output)],
                        capture_output=True, text=True, timeout=60, check=False)
                    self.assertEqual(build.returncode, 0, build.stderr)
                    executed = subprocess.run([str(output)], capture_output=True,
                                              text=True, timeout=60, check=False)
                    self.assertEqual(executed.returncode, 0, executed.stderr)
                    self.assertEqual(
                        executed.stdout.strip(),
                        "ROUND030_DM_SOURCE_EXTRACTED_ORDERED_COMMIT_PASS")

    def test_round031_true_dm_source_sidecar_lifetime_gcc_clang(self) -> None:
        """Compile actual guarded DM C with fake-only lower / authority stubs."""
        target = TARGET.read_text(encoding="utf-8")
        base_start = "/* ROUND030_DM_COMMIT_EXACT_START */"
        base_end = "/* ROUND030_DM_COMMIT_EXACT_END */"
        source_start = "/* ROUND031_DM_SIDECAR_EXACT_START */"
        source_end = "/* ROUND031_DM_SIDECAR_EXACT_END */"
        for marker in (base_start, base_end, source_start, source_end):
            self.assertEqual(target.count(marker), 1)
        base = target.split(base_start, 1)[1].split(base_end, 1)[0]
        real_sidecar = target.split(source_start, 1)[1].split(source_end, 1)[0]
        for symbol in (
            "swapz_round031_dm_sidecar_init(",
            "swapz_round031_dm_commit_with_sidecar(",
            "swapz_round031_dm_forget_on_overwrite(",
            "swapz_round031_dm_forget_on_discard(",
            "swapz_round031_dm_forget_on_abort(",
            "swapz_round031_dm_forget_on_gc_relocation(",
            "swapz_round031_dm_forget_on_swapoff_or_teardown(",
            "swapz_round031_dm_read_with_sidecar(",
            "swapz_round030_dm_commit_owned_lz4(",
            "swapz_round030_dm_read_owned_lz4(",
            "kvcalloc(logical_pages, sizeof(*sidecar->slots),",
            "memzero_explicit(slot, sizeof(*slot));",
            "check_mul_overflow((size_t)logical_pages,",
            "memcpy(decoded_page, verified_page, SWAPZ_BLOCK_BYTES);",
        ):
            self.assertIn(symbol, real_sidecar)
        self.assertNotIn("\tbio_endio(", real_sidecar)
        self.assertNotIn("\tswapz_map(", real_sidecar)
        self.assertIn("SWAPZ_ROUND031_DM_LZ4_SIDECAR_TEST", target)
        self.assertIn("swapz_zswap_admission_try_live(NULL)", base)
        base_fixture = (ROOT / "tests/runtime/native/fixtures" /
                        "round030-consumer-commit.c").read_text(encoding="utf-8")
        original_marker = "/* ROUND030_EXACT_DM_COMMIT_SOURCE */"
        self.assertEqual(base_fixture.count(original_marker), 1)
        base_fixture = base_fixture.replace(original_marker, base, 1)
        # The existing source fixture supplies only fake lower/authority
        # boundaries. The new test links the ORIGINAL full Round030 commit
        # source and the EXACT new Round031 per-page RAM sidecar C bodies.
        host_patch_pairs = (
            ("\tbool prepublication_fua;\n",
             "\tbool prepublication_fua;\n"
             "\tbool round031_defer_hypothetical_ack;\n"),
            ("static swapz_u32 next_sequence = 5U;",
             "static swapz_u32 next_sequence = 5U;\n"
             "static swapz_u32 fake_next_start_block = 2U;"),
            ("transaction->start_block = 2U;",
             "transaction->start_block = fake_next_start_block;"),
            ("if (block != 2U) return -ESTALE;",
             "if (block != 2U && block != 4U) return -ESTALE;"),
            ("lower_write_error = lower_read_error = "
             "injected_finish_error = stage_error = 0;",
             "lower_write_error = lower_read_error = "
             "injected_finish_error = stage_error = 0;\n"
             "\tfake_next_start_block = 2U;\n\tnext_sequence = 5U;"),
        )
        for prior, updated in host_patch_pairs:
            self.assertEqual(base_fixture.count(prior), 1)
            base_fixture = base_fixture.replace(prior, updated, 1)
        fixture = (ROOT / "tests/runtime/native/fixtures" /
                   "round031-dm-sidecar-host.c").read_text(encoding="utf-8")
        base_token = "/* ROUND031_EMBED_ROUND030_SOURCE */"
        sidecar_token = "/* ROUND031_EXACT_DM_SIDECAR_SOURCE */"
        self.assertEqual(fixture.count(base_token), 1)
        self.assertEqual(fixture.count(sidecar_token), 1)
        fixture = fixture.replace(base_token, base_fixture, 1)
        fixture = fixture.replace(sidecar_token, real_sidecar, 1)
        compilers = [name for name in ("gcc", "clang") if shutil.which(name)]
        self.assertTrue(compilers)
        with tempfile.TemporaryDirectory(prefix="round031-dm-sidecar-") as directory:
            for compiler in compilers:
                with self.subTest(compiler=compiler):
                    working_directory = Path(directory)
                    source_file = working_directory / (compiler + "-sidecar.c")
                    codec_object = working_directory / (compiler + "-codec.o")
                    executable = working_directory / (compiler + "-sidecar")
                    source_file.write_text(fixture, encoding="utf-8")
                    shared = [compiler, "-std=gnu11", "-O1", "-g",
                              "-Wall", "-Wextra", "-Werror", "-Wshadow",
                              "-fsanitize=address,undefined",
                              "-fno-sanitize-recover=all", "-I",
                              str(HEADER.parent)]
                    # Historical codec.c only: its existing conversion
                    # warnings remain isolated, never the NEW source C.
                    codec_result = subprocess.run([
                        *shared, "-Wno-conversion", "-c", str(CODEC),
                        "-o", str(codec_object)], capture_output=True,
                        text=True, timeout=60, check=False)
                    self.assertEqual(codec_result.returncode, 0,
                                     codec_result.stderr)
                    compiled = subprocess.run([
                        *shared, "-Wconversion", str(source_file),
                        str(codec_object), "-llz4", "-lcrypto", "-o",
                        str(executable)], capture_output=True, text=True,
                        timeout=60, check=False)
                    self.assertEqual(compiled.returncode, 0, compiled.stderr)
                    executed = subprocess.run([str(executable)],
                                              capture_output=True, text=True,
                                              timeout=60, check=False)
                    self.assertEqual(executed.returncode, 0, executed.stderr)
                    self.assertEqual(executed.stdout.splitlines()[-1],
                                     "ROUND031_DM_ACTUAL_SOURCE_LZ4_SIDECAR_NO_LIVE_PASS")

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
