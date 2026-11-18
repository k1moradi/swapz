#!/usr/bin/env python3
"""Round031 real one-tree pinned original MM+BIO C composition regression.

Tests consume the exact source C emitted by the one-tree composer. Host mocks
are not source authentication, loaded kernel execution or device proof.
"""
from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
STAGER = ROOT / "tests/tools/stage-pinned-linux-zswap-composed.py"
MODULE_SPEC = importlib.util.spec_from_file_location("round031_composer", STAGER)
assert MODULE_SPEC and MODULE_SPEC.loader
stage = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = stage
MODULE_SPEC.loader.exec_module(stage)
FIXTURES = ROOT / "tests/runtime/native/fixtures"


class OriginalMMAndBIOComposer(unittest.TestCase):
    def test_frozen_exact_original_source_and_unmodified_stagers(self):
        self.assertEqual(stage.PINNED_SHA,
                         "c339f4010dea8b0d754f84ace70cd1b089878ef8")
        self.assertEqual(stage.ORIGIN.LINUX_COMMIT, stage.PINNED_SHA)
        self.assertEqual(stage.BIO.PINNED_LINUX_COMMIT, stage.PINNED_SHA)
        self.assertEqual(
            stage.BIO.PINNED_BLOBS["block/bio.c"],
            stage.ORIGIN.ORIGINAL_BLOBS["block/bio.c"])
        self.assertEqual(stage.ROUND031_MM_BIO_MACRO,
                         "SWAPZ_ROUND031_MM_BIO_SOURCE")
        self.assertIn("SWAPZ_ROUND025_SIDEBAND_CI_ONLY",
                      stage.ROUND031_ALL_FLAGS)
        self.assertNotIn("bio_endio(", stage.ROUND031_MM_BIO_SOURCE)
        self.assertIn("PAGE_SIZE != 4096U", stage.ROUND031_MM_BIO_SOURCE)
        self.assertIn("entry->swapz_round028_allocation_epoch",
                      stage.ROUND031_MM_BIO_SOURCE)
        self.assertIn("zs_obj_read_sg_begin(", stage.ROUND031_MM_BIO_SOURCE)
        self.assertIn("zs_obj_read_sg_end(", stage.ROUND031_MM_BIO_SOURCE)
        self.assertIn("entry->swapz_round028_store_sha256",
                      stage.ROUND031_MM_BIO_SOURCE)
        self.assertIn("swapz_ci_owned_create(", stage.ROUND031_MM_BIO_SOURCE)
        self.assertIn("kfree_sensitive(compressed_snapshot);",
                      stage.ROUND031_MM_BIO_SOURCE)
        self.assertNotIn("swapz_zswap_admission_try_live",
                         stage.ROUND031_MM_BIO_SOURCE)

    def test_diff3_distinct_insertions_identical_dedup_and_refusals(self):
        original = "alpha\nbeta\ngamma\ndelta\n"
        mm = "alpha\nMM\nbeta\ngamma\ndelta\n"
        bio = "alpha\nbeta\ngamma\nBIO\ndelta\n"
        composed = stage.merge_original_postimages(
            "block/bio.c", original, mm, bio)
        self.assertEqual(composed, "alpha\nMM\nbeta\ngamma\nBIO\ndelta\n")
        self.assertEqual(
            stage.merge_original_postimages("block/bio.c", original, mm, mm),
            mm)
        with self.assertRaisesRegex(
                stage.SourceCompositionError, r"COMPOSE_CONFLICT:block/bio.c"):
            stage.merge_original_postimages(
                "block/bio.c", original,
                "alpha\nMM\nbeta\ngamma\ndelta\n",
                "alpha\nBIO\nbeta\ngamma\ndelta\n")
        # Original upstream blob authenticity belongs to the original MM
        # stager and deliberately raises its precise StagingError before any
        # derived composer transition may be attempted.
        with self.assertRaisesRegex(stage.ORIGIN.StagingError,
                                    "original-blob-mismatch"):
            stage.compose_postimage(
                "block/bio.c", b"fake unpinned original")

    def test_original_full_source_both_postimages_from_same_preimage(self):
        linux = os.environ.get("ROUND031_PINNED_LINUX")
        if not linux:
            self.skipTest("Exact full original upstream checkout not attached")
        root = Path(linux)
        # No in-place original-source modifications during build_plan.
        expected = {path: stage.ORIGIN.ORIGINAL_BLOBS[path]
                    for path in stage.ORIGIN.EDITS}
        expected.update(stage.ORIGIN.ROUND026_ALLOCATOR_ORIGINAL_BLOBS)
        expected.update(stage.ORIGIN.KUNIT_ORIGINAL_BLOBS)
        originals = {path: (root / path).read_bytes() for path in expected}
        resulting = stage.build_plan(originals)
        self.assertEqual(
            set(resulting), set(expected) | {stage.ORIGIN.KUNIT_SOURCE_PATH})
        self.assertEqual((root / "block/bio.c").read_bytes(),
                         originals["block/bio.c"])
        for path, produced in resulting.items():
            with self.subTest(path=path):
                self.assertNotEqual(produced, originals.get(path, b""))
                if path in expected:
                    self.assertEqual(
                        stage.ORIGIN.blob_sha(originals[path]), expected[path])
        decoded_bio = resulting["block/bio.c"].decode()
        decoded_pageio = resulting["mm/page_io.c"].decode()
        decoded_zswap = resulting["mm/zswap.c"].decode()
        self.assertIn("swapz_ci_bio_detach", decoded_bio)
        self.assertIn("SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK", decoded_bio)
        self.assertIn("bio->bi_swapz_ci_sideband = ctx->swapz_round031_owned",
                      decoded_pageio)
        self.assertIn("swapz_round031_mm_bio_create(", decoded_zswap)
        self.assertIn("swapz_round030_snapshot_stored_lz4(", decoded_zswap)
        self.assertIn("swapz_round028_slot_epoch(", decoded_zswap)
        self.assertIn("swap_write_submit(&ctx);", decoded_zswap)

    def compile_and_run(self, generated: str, *, label: str,
                        libraries: tuple[str, ...]):
        compilers = [name for name in ("gcc", "clang") if shutil.which(name)]
        self.assertEqual(len(compilers), 2,
                         "GCC and Clang required for Round031 source tests")
        with tempfile.TemporaryDirectory(prefix="round031-original-mm-bio-") as tmp:
            source_path = Path(tmp) / f"{label}.c"
            source_path.write_text(generated, encoding="utf-8")
            for compiler in compilers:
                with self.subTest(compiler=compiler, source=label):
                    artifact = Path(tmp) / (compiler + "-" + label)
                    compiled = subprocess.run(
                        [compiler, "-std=gnu11", "-O1", "-g",
                         "-Wall", "-Wextra", "-Wshadow", "-Wconversion",
                         "-Werror", "-fno-omit-frame-pointer",
                         "-fsanitize=address,undefined",
                         "-fno-sanitize-recover=all",
                         str(source_path), *libraries, "-o", str(artifact)],
                        capture_output=True, text=True, timeout=60,
                        check=False)
                    self.assertEqual(
                        compiled.returncode, 0,
                        f"Original {compiler} {label} source C compile: "
                        + compiled.stderr[-6000:])
                    ran = subprocess.run(
                        [str(artifact)], capture_output=True, text=True,
                        timeout=40, check=False)
                    self.assertEqual(
                        ran.returncode, 0,
                        f"Original {compiler} {label} ASan/UBSan: "
                        + ran.stderr[-6000:])
                    if label == "round032-bio":
                        self.assertIn(
                            "ROUND032_ORIGINAL_BIO_EXACT_SOURCE_COPY_OUT_PASS",
                            ran.stdout)
                    else:
                        self.assertIn("ROUND031_REAL_", ran.stdout)

    def test_original_source_extracted_mm_zsmalloc_owned_bio(self):
        source = stage.ROUND031_MM_BIO_SOURCE
        begin = "/* ROUND031_MM_ORIGINAL_OWNED_TRANSFER_START */"
        end = "/* ROUND031_MM_ORIGINAL_OWNED_TRANSFER_END */"
        self.assertEqual(source.count(begin), 1)
        self.assertEqual(source.count(end), 1)
        real_c = begin + source.split(begin, 1)[1].split(end, 1)[0] + end
        fixture = (FIXTURES / "round031-composed-mm-owned-host.c").read_text(
            encoding="utf-8")
        anchor = "/* ROUND031_EXACT_ORIGINAL_MM_C */"
        self.assertEqual(fixture.count(anchor), 1)
        self.compile_and_run(fixture.replace(anchor, real_c, 1),
                             label="mm", libraries=("-llz4", "-lcrypto"))

    def test_original_source_extracted_pageio_move_and_bio_detach(self):
        # Extract the actual insertion body, not a re-authored test algorithm.
        origin_marker = "\tbio->bi_swap_origin = sio->swap_origin;\n"
        token = "\tbio->bi_iter.bi_size = sio->len;\n"
        original_write = (origin_marker + token +
                          "\tbio->bi_iter.bi_sector = swap_folio_sector")
        pageio_stub = stage.apply_mm_bio_source(
            "mm/page_io.c", original_write
        )
        self.assertIn(
            "bio->bi_swapz_ci_sideband = ctx->swapz_round031_owned;",
            pageio_stub)
        inserted = pageio_stub.split(token, 1)[1].split(
            "\tbio->bi_iter.bi_sector", 1)[0]
        owner_start = "static void swapz_ci_bio_detach(struct bio *bio)"
        owner_end = "/* A future merge call site MUST"
        source = stage.BIO.CI_HELPERS
        self.assertEqual(source.count(owner_start), 1)
        detached = source.split(owner_start, 1)[1].split(owner_end, 1)[0]
        real_detach = owner_start + detached
        fixture = (FIXTURES /
                   "round031-composed-bio-transfer-host.c").read_text(
                       encoding="utf-8")
        self.assertIn("/* ROUND031_EXACT_REAL_BIO_MOVE_C */", fixture)
        self.assertIn("/* ROUND031_EXACT_REAL_BIO_DETACH_C */", fixture)
        fixture = fixture.replace(
            "/* ROUND031_EXACT_REAL_BIO_MOVE_C */", inserted, 1)
        fixture = fixture.replace(
            "/* ROUND031_EXACT_REAL_BIO_DETACH_C */", real_detach, 1)
        self.compile_and_run(fixture, label="bio", libraries=())


    def test_round032_frozen_value_copy_contract_and_original_owner_source(self):
        self.assertEqual(stage.ROUND032_BIO_COPY_VIEW_MACRO,
                         "SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY")
        self.assertIn("u64 source_swap_entry;",
                      stage.ROUND032_BIO_VIEW_HEADER)
        self.assertIn("u64 source_slot_epoch;",
                      stage.ROUND032_BIO_VIEW_HEADER)
        self.assertIn("u64 stored_entry_identity;",
                      stage.ROUND032_BIO_VIEW_HEADER)
        self.assertIn("u32 compressed_crc32c;",
                      stage.ROUND032_BIO_VIEW_HEADER)
        self.assertIn("u8 original_sha256[32];",
                      stage.ROUND032_BIO_VIEW_HEADER)
        self.assertIn("struct swapz_ci_lz4_owned_view_v1",
                      stage.ROUND032_BIO_VIEW_HEADER)
        self.assertNotIn("*", stage.ROUND032_BIO_VIEW_HEADER.split(
            "struct swapz_ci_lz4_owned_view_v1 {", 1)[1].split(
            "};", 1)[0], "The copied versioned v1 struct must have NO pointer")
        self.assertIn("EXPORT_SYMBOL_GPL(swapz_ci_bio_snapshot_lz4_v1);",
                      stage.ROUND032_BIO_COPY_VIEW_SOURCE)
        self.assertIn("owner->source_swap_entry = source_swap_entry;",
                      stage.apply_round032_bio_view(
                          "block/bio.c",
                          stage.apply_mm_bio_source(
                              "block/bio.c", stage.BIO.CI_HELPERS)))
        self.assertIn(
            "source_slot.val &&",
            stage.apply_round032_bio_view(
                "mm/zswap.c", stage.ROUND031_MM_BIO_SOURCE))
        self.assertIn("sizeof(source_slot.val) <= sizeof(u64)",
                      stage.apply_round032_bio_view(
                          "mm/zswap.c", stage.ROUND031_MM_BIO_SOURCE))
        self.assertNotIn("bio_endio(",
                         stage.ROUND032_BIO_COPY_VIEW_SOURCE)

    def test_round032_original_source_full_pinned_postimage_guards(self):
        linux_name = os.environ.get("ROUND031_PINNED_LINUX")
        if not linux_name:
            self.skipTest("Full pinned original Linux available in CI only")
        linux = Path(linux_name)
        original_sources = {
            path: (linux / path).read_bytes()
            for path in set(stage.ORIGIN.EDITS) |
            set(stage.ORIGIN.ROUND026_ALLOCATOR_ORIGINAL_BLOBS) |
            set(stage.ORIGIN.KUNIT_EDITS)
        }
        produced = stage.build_plan(original_sources)
        actual_header = produced["include/linux/bio.h"].decode()
        actual_bio = produced["block/bio.c"].decode()
        actual_mm = produced["mm/zswap.c"].decode()
        actual_pageio = produced["mm/page_io.c"].decode()
        self.assertIn("swapz_ci_lz4_owned_view_v1", actual_header)
        self.assertIn("swapz_ci_bio_snapshot_lz4_v1", actual_header)
        self.assertIn("EXPORT_SYMBOL_GPL(swapz_ci_bio_snapshot_lz4_v1)",
                      actual_bio)
        self.assertIn("source_swap_entry = source_swap_entry;", actual_bio)
        self.assertIn("swapz_ci_owned_create_source_v1(", actual_mm)
        self.assertIn("(u64)source_slot.val", actual_mm)
        self.assertIn("zswap_decompress(entry, folio)", actual_mm)
        self.assertIn("bio->bi_iter.bi_size = sio->len;", actual_pageio)
        self.assertIn("REQ_OP_WRITE | REQ_SWAP", actual_pageio)
        self.assertNotIn("SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY",
                         (linux / "include/linux/bio.h").read_text())

    def test_round032_real_original_bio_source_extracted_c_sanitizers(self):
        # Both original pinned bio.c and original BIO stager are immutable.
        # Extract the existing owner refcount, bounded flexible-array LZ4
        # constructor, clone lifetime and the NEW true guarded accessor from
        # the exact composed original C. Do not rewrite the algorithm.
        original_helpers = stage.BIO.CI_HELPERS
        original_helpers = stage.apply_mm_bio_source(
            "block/bio.c", original_helpers)
        generated = stage.apply_round032_bio_view(
            "block/bio.c", original_helpers)
        begin = "struct swapz_ci_owned_payload {"
        end = "#endif /* SWAPZ_ROUND025_SIDEBAND_CI_ONLY */"
        self.assertEqual(generated.count(begin), 1)
        self.assertEqual(generated.count(end), 1)
        real_c = begin + generated.split(begin, 1)[1].split(end, 1)[0]
        self.assertIn("swapz_ci_owned_create_internal(", real_c)
        self.assertIn("swapz_ci_owned_create_source_v1(", real_c)
        self.assertIn("EXPORT_SYMBOL_GPL(swapz_ci_bio_snapshot_lz4_v1);",
                      real_c)
        header = stage.ROUND032_BIO_VIEW_HEADER
        value_type = (
            "struct swapz_ci_lz4_owned_view_v1 {" +
            header.split("struct swapz_ci_lz4_owned_view_v1 {", 1)[1]
            .split("};", 1)[0] + "};\n"
        )
        fixture = (FIXTURES / "round032-bio-copy-view-host.c").read_text(
            encoding="utf-8")
        self.assertEqual(fixture.count(
            "/* ROUND032_EXACT_HEADER_VALUE_STRUCT */"), 1)
        self.assertEqual(fixture.count(
            "/* ROUND032_EXACT_ORIGINAL_BIO_OWNER_AND_EXPORT */"), 1)
        fixture = fixture.replace(
            "/* ROUND032_EXACT_HEADER_VALUE_STRUCT */",
            value_type, 1)
        fixture = fixture.replace(
            "/* ROUND032_EXACT_ORIGINAL_BIO_OWNER_AND_EXPORT */",
            real_c, 1)
        self.compile_and_run(
            fixture, label="round032-bio", libraries=("-llz4", "-lcrypto"))


    def test_round034_actual_bio_c_v1_kunit_gate_and_case_inventory(self):
        self.assertEqual(stage.ROUND034_ORIGINAL_V1_KUNIT_MACRO,
                         "SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST")
        self.assertIn("IS_ENABLED(CONFIG_KUNIT)", stage.ROUND034_KUNIT_GUARD)
        source = stage.ROUND034_KUNIT_SOURCE
        self.assertIn("LZ4_compress_default(", source)
        self.assertIn("LZ4_decompress_safe(", source)
        self.assertIn("sha256(fixture->decoded, PAGE_SIZE, decoded_sha);",
                      source)
        self.assertIn("fixture->bio.bi_vcnt, 0U", source)
        self.assertIn("swapz_ci_bio_snapshot_lz4_v1(", source)
        self.assertIn("memchr_inv(destination, 0x6b", source)
        self.assertIn("refcount_read(&owner->references)", source)
        expected = (
            "swapz_round034_v1_owned_copy_kunit",
            "swapz_round034_v1_bio_reject_kunit",
            "swapz_round034_v1_owner_reject_kunit",
            "swapz_round034_v1_constructor_reject_kunit",
            "swapz_round034_v1_alias_kunit",
            "swapz_round034_v1_lifetime_kunit",
        )
        for case in expected:
            self.assertEqual(stage.ROUND034_KUNIT_CASES.count(
                "KUNIT_CASE(" + case + ")"), 1)
        base = '#include "blk-cgroup.h"\n' + stage.BIO.CI_KUNIT
        generated = stage.apply_round034_original_v1_kunit(
            "block/bio.c", base)
        self.assertEqual(generated.count(
            "static struct kunit_case swapz_ci_sideband_cases[] = {"), 1)
        for case in expected:
            self.assertIn("KUNIT_CASE(" + case + ")", generated)
        with self.assertRaisesRegex(
                stage.SourceCompositionError, "COMPOSE_CONFLICT:block/bio.c"):
            stage.apply_round034_original_v1_kunit("block/bio.c", generated)
        self.assertEqual(stage.apply_round034_original_v1_kunit(
            "mm/zswap.c", "original"), "original")


    def test_round035_original_mm_route_witness_guard_and_source_only(self):
        self.assertEqual(stage.ROUND035_ROUTE_MACRO,
                         "SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST")
        self.assertEqual(len(stage.ROUND035_ROUTE_FLAGS), 7)
        self.assertIn("IS_ENABLED(CONFIG_KUNIT)", stage.ROUND035_ROUTE_CONDITION)
        self.assertIn("get_swap_device(original_slot);", stage.ROUND035_ROUTE_MM)
        self.assertIn("swap_folio_sector(folio)", stage.ROUND035_ROUTE_MM)
        self.assertIn("swapz_round028_slot_epoch(original_slot)",
                      stage.ROUND035_ROUTE_MM)
        self.assertIn("folio_test_writeback(folio)", stage.ROUND035_ROUTE_MM)
        self.assertIn("swapz_round035_bio_owner_matches(", stage.ROUND035_ROUTE_MM)
        self.assertIn("return -EOPNOTSUPP;", stage.ROUND035_ROUTE_MM)
        self.assertNotIn("bio_endio(", stage.ROUND035_ROUTE_MM)
        self.assertNotIn("submit_bio(", stage.ROUND035_ROUTE_MM)
        self.assertNotIn("SOURCE_MAPPED_AUTHENTICATED=1", stage.ROUND035_ROUTE_MM)
        for case in (
            "swapz_round035_route_type_kunit",
            "swapz_round035_route_epoch_kunit",
            "swapz_round035_route_geometry_kunit",
            "swapz_round035_route_no_authority_kunit",
        ):
            self.assertEqual(stage.ROUND035_ROUTE_MM.count(
                "KUNIT_CASE(" + case + ")"), 1)
        self.assertEqual(stage.ROUND035_ROUTE_MM.count(
            'kunit_test_suite(swapz_round035_route_suite);'), 1)
        base = ("static void swap_bdev_submit_write(struct swap_io_ctx *ctx)\n"
                "HEADER\n"
                "\t\tbio->bi_swapz_ci_sideband = ctx->swapz_round031_owned;\n"
                "\t\tctx->swapz_round031_owned = NULL;\n"
                "\t}\n#endif\n"
                "\tbio->bi_iter.bi_sector = swap_folio_sector(bio_first_folio_all(bio));\n")
        rendered = stage.apply_round035_original_route("mm/page_io.c", base)
        self.assertIn("swapz_round035_mm_route_preflight(", rendered)
        with self.assertRaisesRegex(
                stage.SourceCompositionError,
                "COMPOSE_CONFLICT:mm/page_io.c"):
            stage.apply_round035_original_route("mm/page_io.c", rendered)
        self.assertEqual(stage.apply_round035_original_route(
            "mm/swapfile.c", "original"), "original")

    def test_round035_exact_original_route_C_host_compilers_sanitizers(self):
        # Extract the ACTUAL new original Linux source helper expressions.
        # The host fixture merely supplies types and addresses; it cannot
        # authorize current original swap mapping or zswap MM eviction.
        real = stage.ROUND035_ROUTE_MM
        identity = ("static int swapz_round035_route_identity" +
                    real.split("static int swapz_round035_route_identity", 1)[1]
                    .split("/*\n * Source-side shape only.", 1)[0])
        geometry = ("static int swapz_round035_route_geometry" +
                    real.split("static int swapz_round035_route_geometry", 1)[1]
                    .split("/*\n * Called at ACTUAL", 1)[0])
        template = (FIXTURES / "round035-original-route-host.c").read_text(
            encoding="utf-8")
        for marker, fragment in (
            ("/* ROUND035_EXACT_REAL_ORIGINAL_ROUTE_IDENTITY_C */", identity),
            ("/* ROUND035_EXACT_REAL_ORIGINAL_ROUTE_GEOMETRY_C */", geometry),
        ):
            self.assertEqual(template.count(marker), 1)
            template = template.replace(marker, fragment, 1)
        self.compile_and_run(template, label="round035-route", libraries=())


    def test_round036_real_original_route_lifetime_guard_and_anchor(self):
        self.assertEqual(stage.ROUND036_LIFETIME_MACRO,
                         "SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST")
        self.assertEqual(len(stage.ROUND036_LIFETIME_FLAGS), 8)
        source = stage.ROUND036_LIFETIME_C
        for prerequisite in stage.ROUND036_LIFETIME_FLAGS:
            self.assertIn("defined(" + prerequisite + ")", source)
        self.assertIn("IS_ENABLED(CONFIG_KUNIT)", source)
        for required in (
            "swapz_round028_slot_epoch(original_slot)",
            "get_swap_device(original_slot)",
            "put_swap_device(active)",
            "swap_folio_sector(folio)",
            "swapz_round035_bio_owner_matches",
            "folio_test_locked(folio)",
            "swapz_round036_route_lifetime_check",
            "source_bio->bi_vcnt",
            "(1U << BIO_CLONED)",
            "return -EOPNOTSUPP; /* NO AUTHORITY",
            "kunit_test_suite(swapz_round036_lifetime_suite);",
        ):
            self.assertIn(required, source)
        for forbidden in (
            "EXPORT_SYMBOL", "bio_endio(", "submit_bio(", "swapz_map(",
            "SOURCE_MAPPED_AUTHENTICATED=1", "swapz_lower_write",
        ):
            self.assertNotIn(forbidden, source)
        new_cases = (
            "slot_epoch_aba", "swapoff_area_reuse", "nonlinear_sector",
            "target_gc_race", "bio_clone_split_unlock",
            "no_lease_double_release",
        )
        for name in new_cases:
            self.assertEqual(source.count(
                "KUNIT_CASE(swapz_round036_" + name + "_kunit)"), 1)
        self.assertEqual(len(new_cases), 6)
        self.assertIn("if (bio->bi_swapz_ci_sideband)",
                      stage.ROUND036_LIFETIME_HOOK)
        # Original 035 registered suite remains unchanged (21 old cases).
        self.assertIn("kunit_test_suite(swapz_round035_route_suite);",
                      stage.ROUND035_ROUTE_MM)
        base = (stage.ROUND035_ROUTE_MM +
                "\nstatic void swap_bdev_submit_write(struct swap_io_ctx *ctx)\n" +
                stage.ROUND035_ROUTE_HOOK)
        rendered = stage.apply_round036_original_lifetime(
            "mm/page_io.c", base)
        self.assertIn("ROUND036_ORIGINAL_MM_LIFETIME_C_BEGIN", rendered)
        self.assertIn("swapz_round035_route_suite", rendered)
        self.assertIn("swapz_round036_original_lifetime_probe(", rendered)
        with self.assertRaisesRegex(
                stage.SourceCompositionError,
                "COMPOSE_CONFLICT:mm/page_io.c"):
            stage.apply_round036_original_lifetime("mm/page_io.c", rendered)
        self.assertEqual(stage.apply_round036_original_lifetime(
            "mm/swapfile.c", "original"), "original")

    def test_round036_exact_original_route_lifetime_host_werror_sanitizers(self):
        # Compile/execute ACTUAL extracted original MM C helper under both
        # compilers; only bounded host structs are fake, never MM authority.
        source = stage.ROUND036_LIFETIME_C
        beginning = "struct swapz_round036_route_lifetime {"
        ending = "\n/*\n * Called at the ACTUAL original swap_bdev_submit_write()"
        self.assertEqual(source.count(beginning), 1)
        self.assertEqual(source.count(ending), 1)
        extracted = beginning + source.split(beginning, 1)[1].split(
            ending, 1)[0]
        template = (FIXTURES / "round036-original-route-lifetime-host.c").read_text()
        marker = "/* ROUND036_REAL_ORIGINAL_SOURCE_LIFETIME_STRUCT_AND_HELPER */"
        self.assertEqual(template.count(marker), 1)
        self.assertIn("return -EOPNOTSUPP;", extracted)
        self.compile_and_run(template.replace(marker, extracted, 1),
                             label="round036-original-route", libraries=())

    def test_round036_original_completion_and_ref_scope_unchanged(self):
        # Inspect actual unchanged original mm/page_io.c completion and
        # zswap_writeback_entry lifetimes, not only a mock state enum.
        original_source = stage.ORIGIN
        self.assertEqual(stage.PINNED_SHA, original_source.LINUX_COMMIT)
        self.assertIn("bio_uninit()", stage.ROUND036_LIFETIME_C)
        upstream = os.environ.get("ROUND031_PINNED_LINUX")
        if upstream:
            actual = (Path(upstream) / "mm/page_io.c").read_text()
            done = actual.split("static void end_swap_bio_write(", 1)[1].split(
                "static void swap_read_end(", 1)[0]
            self.assertLess(done.index("bio_uninit(bio);"),
                            done.index("swap_write_end(sio, failed);"))
            dispatch = actual.split("void __swap_writeout(", 1)[1].split(
                "static int swap_zeromap_batch(", 1)[0]
            self.assertLess(dispatch.index("folio_unlock(folio);"),
                            dispatch.index("swap_add_folio(ctx, folio, WRITE);"))
        self.assertIn("folio_end_writeback()", stage.ROUND036_LIFETIME_C)
        self.assertIn("get_swap_device()/put_swap_device()",
                      stage.ROUND036_LIFETIME_C)
        self.assertIn("struct swapz_round036_route_lifetime consumer_sample = {}",
                      stage.ROUND036_LIFETIME_C)
        self.assertNotIn("struct swapz_round036_route_lifetime current = {}",
                         stage.ROUND036_LIFETIME_C)
        self.assertIn("original swap allocation epoch lookup", stage.ROUND036_LIFETIME_C)


    def test_round037_original_mm_scoped_real_source_default_off_and_closure(self):
        source = stage.ROUND037_MM_OWNER_C
        self.assertEqual(stage.ROUND037_MM_OWNER_MACRO,
                         "SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST")
        self.assertIn("SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST", source)
        self.assertIn("IS_ENABLED(CONFIG_KUNIT)", source)
        self.assertIn("get_swap_device(original_slot)", source)
        self.assertIn("swapz_round028_slot_epoch(original_slot)", source)
        self.assertIn("swap_folio_sector(folio)", source)
        self.assertIn("swapz_round035_bio_owner_matches(", source)
        self.assertIn("put_swap_device(active_area)", source)
        self.assertIn("swapz_round037_mm_scope_detach(&scope)", source)
        self.assertIn("return -EOPNOTSUPP;", source)
        self.assertNotIn("return 0;", source)
        # Comments may describe upstream submit_bio without calling it.
        # Enforce the actual generated statements, not documentation prose.
        executable_c = re.sub(r"/\*[\s\S]*?\*/", "", source)
        for forbidden in ("EXPORT_SYMBOL", "bio_endio(", "submit_bio(",
                          "swapz_map(", "SOURCE_MAPPED_AUTHENTICATED=1"):
            self.assertNotIn(forbidden, executable_c)
        self.assertIn("static noinline int swapz_round037_original_mm_scoped_probe(",
                      source)
        for name in ("epoch_aba", "swapoff_readd", "bio_late", "close_once"):
            self.assertEqual(source.count(
                "KUNIT_CASE(swapz_round037_scope_" + name + "_kunit)"), 1)
        base = (stage.ROUND036_LIFETIME_C + "\n" +
                "static void swap_bdev_submit_write(struct swap_io_ctx *ctx)\n"
                + stage.ROUND036_LIFETIME_HOOK)
        composed = stage.apply_round037_original_mm_owner("mm/page_io.c", base)
        self.assertIn("swapz_round037_original_mm_scoped_probe(", composed)
        with self.assertRaisesRegex(
                stage.SourceCompositionError, "COMPOSE_CONFLICT:mm/page_io.c"):
            stage.apply_round037_original_mm_owner("mm/page_io.c", composed)

    def test_round037_original_mm_scope_c_gcc_clang_werror_asan_ubsan(self):
        source = stage.ROUND037_MM_OWNER_C
        start = "/* ROUND037_MM_SCOPED_OWNER_BEGIN */"
        end = "/* ROUND037_MM_SCOPED_HELPERS_END */"
        self.assertEqual(source.count(start), 1)
        self.assertEqual(source.count(end), 1)
        c_source = source.split(start, 1)[1].split(end, 1)[0]
        fixture = (FIXTURES / "round037-original-mm-scope-host.c").read_text()
        marker = "/* ROUND037_EXACT_ORIGINAL_MM_SCOPE_C */"
        self.assertEqual(fixture.count(marker), 1)
        self.compile_and_run(fixture.replace(marker, c_source, 1),
                             label="round037-original-mm", libraries=())

if __name__ == "__main__":
    unittest.main(verbosity=2)
