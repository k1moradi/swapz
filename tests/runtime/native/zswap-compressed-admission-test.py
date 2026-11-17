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
        self.assertEqual(dm.count('#include "zswap-import-admission.h"'), 2)
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

    def test_round024_kbuild_ingress_is_unreferenced_and_fails_closed(self) -> None:
        dm = DM.read_text(encoding="utf-8")
        probe_start = "#if defined(SWAPZ_ROUND024_DM_IMPORT_KBUILD_PROBE)"
        probe_end = "#endif /* SWAPZ_ROUND024_DM_IMPORT_KBUILD_PROBE */"
        # Round026 adds a third isolated, default-off source snapshot gate.
        self.assertEqual(dm.count(probe_start), 3)
        self.assertEqual(dm.count(probe_end), 1)
        body = dm.split(probe_start, 1)[1].split(probe_end, 1)[0]
        self.assertIn("static __used noinline int "
                      "swapz_round024_dm_import_kbuild_probe(", body)
        self.assertIn("swapz_zswap_admission_read_4096(", body)
        self.assertIn("swapz_zswap_admission_try_live(NULL)", body)
        self.assertTrue(body.rstrip().endswith("}"))
        self.assertIn("return -EOPNOTSUPP;", body)
        self.assertNotIn("submit_bio(", body)
        self.assertNotIn("bio_endio(", body)
        self.assertNotIn("swapz_zswap_admission_begin_mock(", body)
        self.assertEqual(dm.count("swapz_round024_dm_import_kbuild_probe("), 1)
        # Compilation is selected by KCFLAGS in a separate module build. The
        # ordinary default module still compiles without the new header.
        workflow = (ROOT / ".github/workflows/product-codec.yml").read_text(
            encoding="utf-8")
        self.assertIn("KCFLAGS=-DSWAPZ_ROUND024_DM_IMPORT_KBUILD_PROBE=1",
                      workflow)
        self.assertIn("nm -a", workflow)
        self.assertIn("swapz_round024_dm_import_kbuild_probe", workflow)

    def test_round025_real_dm_authority_source_compiler_negative(self) -> None:
        """Compile the exact opt-in dm-target body, not a rewritten mock."""
        dm = DM.read_text(encoding="utf-8")
        start = "static __used noinline int swapz_round025_dm_authority_kbuild_probe("
        end = "#endif /* SWAPZ_ROUND025_DM_AUTHORITY_KBUILD_PROBE */"
        self.assertEqual(dm.count(start), 1)
        self.assertEqual(dm.count(end), 1)
        body = dm.split(start, 1)[1].split(end, 1)[0]
        self.assertIn("ctx->authority.maps[logical_page]", body)
        self.assertIn("current_map->generation != transaction->record.generation",
                      body)
        self.assertIn("observed_gc_epoch != transaction->record.gc_epoch",
                      body)
        self.assertIn("transaction->upper_write_ack_count", body)
        self.assertEqual(body.count("return -EOPNOTSUPP;"), 4)
        self.assertNotIn("bio_endio(", body)
        self.assertNotIn("swapz_finish(", body)
        fixture = (ROOT / "tests/runtime/native/fixtures/"
                   "round025-consumer-dm-authority.c").read_text(encoding="utf-8")
        marker = "/* ROUND025_EXACT_DM_PROBE_SOURCE */"
        self.assertEqual(fixture.count(marker), 1)
        source = fixture.replace(marker, start + body, 1)
        with tempfile.TemporaryDirectory() as temporary:
            source_file = Path(temporary) / "round025-dm.c"
            source_file.write_text(source, encoding="utf-8")
            for compiler in ("gcc", "clang"):
                if not shutil.which(compiler):
                    continue
                with self.subTest(compiler=compiler):
                    executable = Path(temporary) / compiler
                    command = [compiler, "-std=gnu11", "-O1", "-g",
                               "-Wall", "-Wextra", "-Wconversion", "-Wshadow",
                               "-Werror", "-fsanitize=address,undefined",
                               "-fno-sanitize-recover=all", str(source_file),
                               "-o", str(executable)]
                    built = subprocess.run(command, capture_output=True,
                                           text=True, timeout=60, check=False)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    result = subprocess.run([str(executable)], capture_output=True,
                                            text=True, timeout=40, check=False)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("ROUND025_REAL_DM_SOURCE_NEGATIVE_ONLY_PASS",
                                  result.stdout)
        workflow = (ROOT / ".github/workflows/product-codec.yml").read_text(
            encoding="utf-8")
        self.assertIn("swapz_round025_dm_authority_kbuild_probe", workflow)
        self.assertIn("round025-dm-authority", workflow)


    def test_round026_real_dm_snapshot_fence_gcc_clang_no_go(self) -> None:
        """Actually compile source-extracted worker-owned map recheck."""
        dm = DM.read_text(encoding="utf-8")
        begin = "/* ROUND026_DM_SNAPSHOT_START */"
        end = "/* ROUND026_DM_SNAPSHOT_END */"
        self.assertEqual(dm.count(begin), 1)
        self.assertEqual(dm.count(end), 1)
        source_body = dm.split(begin, 1)[1].split(end, 1)[0]
        self.assertIn("lockdep_assert_held(&ctx->ordered_owner)", source_body)
        self.assertIn("ctx->authority.maps[logical_page]", source_body)
        self.assertIn("swapz_extent_sequence_lookup(", source_body)
        self.assertIn("ctx->authority.gc_destination", source_body)
        self.assertIn("ctx->gc_recovery.active", source_body)
        self.assertIn("before_read->mapping.start_block !=", source_body)
        self.assertIn("before_read->mapping.record_index !=", source_body)
        self.assertIn("transaction->upper_write_ack_count != 1U",
                      source_body)
        self.assertIn("return -EOPNOTSUPP;", source_body)
        self.assertNotIn("return 1;", source_body)
        self.assertNotIn("bio_endio(", source_body)
        self.assertNotIn("swapz_finish(", source_body)
        self.assertNotIn("swapz_zswap_admission_begin_mock(", source_body)
        # These functions are unreferenced in the live DM code.
        self.assertEqual(dm.count("swapz_round026_dm_capture_read_snapshot("),
                         2)  # one definition, one gated internal call
        self.assertEqual(dm.count("swapz_round026_dm_revalidate_and_refuse("),
                         1)
        fixture = (ROOT / "tests/runtime/native/fixtures" /
                   "round026-consumer-dm-snapshot.c").read_text(encoding="utf-8")
        marker = "/* ROUND026_DM_EXACT_FUNCTIONS */"
        self.assertEqual(fixture.count(marker), 1)
        compilation = fixture.replace(marker, source_body, 1)
        with tempfile.TemporaryDirectory() as temporary:
            compiled_file = Path(temporary) / "round026-source.c"
            compiled_file.write_text(compilation, encoding="utf-8")
            compilers = [compiler for compiler in ("gcc", "clang")
                         if shutil.which(compiler)]
            self.assertTrue(compilers)
            for compiler in compilers:
                with self.subTest(compiler=compiler):
                    executable = Path(temporary) / compiler
                    command = [
                        compiler, "-std=gnu11", "-O1", "-g",
                        "-Wall", "-Wextra", "-Wconversion", "-Wshadow",
                        "-Werror", "-fsanitize=address,undefined",
                        "-fno-sanitize-recover=all", str(compiled_file),
                        "-o", str(executable)]
                    compiled = subprocess.run(
                        command, capture_output=True, text=True,
                        timeout=60, check=False)
                    self.assertEqual(compiled.returncode, 0, compiled.stderr)
                    result = subprocess.run(
                        [str(executable)], capture_output=True, text=True,
                        env=dict(os.environ, ASAN_OPTIONS="detect_leaks=1"),
                        timeout=40, check=False)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(
                        "ROUND026_DM_EXACT_SNAPSHOT_STALE_AND_NO_GO_PASS",
                        result.stdout)
        workflow = (ROOT / ".github/workflows/product-codec.yml").read_text(
            encoding="utf-8")
        self.assertIn("swapz_round026_dm_capture_read_snapshot", workflow)
        self.assertIn("swapz_round026_dm_revalidate_and_refuse", workflow)


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
