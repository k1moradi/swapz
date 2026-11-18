#!/usr/bin/env python3
"""Round035: execute actual guarded DM C lower stage/commit/read/sha, fake IO only.

The only substitutions are the bounded fake lower block-device adapter and
host-owned original BIO provider. No original MM allocation or eviction is
executed and neither mock conveys source authentication.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "src/kernel/dm-target.c"
CODEC = ROOT / "src/kernel/codec.c"
FIXTURES = ROOT / "tests/runtime/native/fixtures"
GUARDS = (
    "SWAPZ_ROUND035_DM_LZ4_LOWER_ROUNDTRIP_TEST",
    "SWAPZ_ROUND034_DM_SOURCE_SLOT_AUTHORITY_TEST",
    "SWAPZ_ROUND033_DM_ORIGINAL_BIO_GPL_LINK_TEST",
    "SWAPZ_ROUND032_DM_LZ4_VIEW_VALIDATE_TEST",
    "SWAPZ_ROUND031_DM_LZ4_SIDECAR_TEST",
    "SWAPZ_ROUND030_DM_COMPRESSED_COMMIT_TEST",
    "SWAPZ_ROUND028_DM_OWNED_READBACK_TEST",
    "SWAPZ_ROUND024_DM_IMPORT_KBUILD_PROBE",
    "SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY",
    "SWAPZ_ROUND031_MM_BIO_SOURCE",
    "SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE",
    "SWAPZ_ROUND028_SLOT_EPOCH_SOURCE",
    "SWAPZ_ROUND025_SIDEBAND_CI_ONLY",
)


def extract(entire: str, start: str, end: str) -> str:
    if entire.count(start) != 1 or entire.count(end) != 1:
        raise AssertionError("source marker missing or duplicate: " + start)
    return entire.split(start, 1)[1].split(end, 1)[0]


def replace_once(text: str, original: str, replacement: str) -> str:
    if text.count(original) != 1:
        raise AssertionError("host-only boundary drift: " + original[:90])
    return text.replace(original, replacement, 1)


def compiled_actual_source() -> str:
    target = TARGET.read_text(encoding="utf-8")
    first = "/* ROUND035_DM_OWNED_LOWER_EXACT_START */"
    last = "/* ROUND035_DM_OWNED_LOWER_EXACT_END */"
    new_c = extract(target, first, last)
    section = target[:target.index(first)]
    guard = section[section.rfind("#if defined(SWAPZ_ROUND035_DM_LZ4_LOWER_ROUNDTRIP_TEST)"):]
    for name in GUARDS:
        if guard.count(f"defined({name})") != 1:
            raise AssertionError("Round035 compiler guard absent: " + name)
    for required in (
        "swapz_round033_dm_copy_original_bio_v1_for_link(",
        "swapz_round031_dm_commit_with_sidecar(",
        "swapz_round031_dm_read_with_sidecar(",
        "swp_type(source_entry)", "swp_offset(source_entry)",
        "swapz_zswap_admission_try_live(NULL)",
        "memzero_explicit(owned_source, SWAPZ_MAX_COMPRESSED)",
        "memcpy(upper_output, candidate_page, SWAPZ_BLOCK_BYTES)",
        "return error;",
    ):
        if required not in new_c:
            raise AssertionError("missing real pipeline operation: " + required)
    for forbidden in ("bio_endio(", "swapz_map(", "get_swap_device("):
        if forbidden in new_c:
            raise AssertionError("forbidden live side effect: " + forbidden)
    if target.count("swapz_round035_dm_owned_lz4_lower_roundtrip(") != 1:
        raise AssertionError("new helper has production callsites")
    if "SWAPZ_ROUND035_DM_LZ4_LOWER_ROUNDTRIP_TEST" in target[:target.index(first)]:
        # Only the immediately preceding #if may contain the new guard.
        if target[:target.index(first)].count(
                "SWAPZ_ROUND035_DM_LZ4_LOWER_ROUNDTRIP_TEST") != 1:
            raise AssertionError("new guard leaked into ordinary path")
    if "return -EOPNOTSUPP;" not in target:
        raise AssertionError("original source admission closed")
    base = (FIXTURES / "round030-consumer-commit.c").read_text(encoding="utf-8")
    round030 = extract(target, "/* ROUND030_DM_COMMIT_EXACT_START */",
                       "/* ROUND030_DM_COMMIT_EXACT_END */")
    # Replace the older *host-only* approximations with the real production
    # Round026 owner snapshot, Round028 staging and lower readback C.
    original_begin = "static int swapz_round028_dm_stage_owned_payload("
    original_end = "/* ROUND030_EXACT_DM_COMMIT_SOURCE */"
    if base.count(original_begin) != 1 or base.count(original_end) != 1:
        raise AssertionError("Round030 mock read/stage boundaries changed")
    real_snapshot = (
        "struct swapz_round026_dm_read_snapshot {" +
        extract(target, "struct swapz_round026_dm_read_snapshot {",
                "static __used noinline int swapz_round026_dm_revalidate_and_refuse(")
    )
    real_stage = extract(target, "/* ROUND028_DM_OWNED_STAGE_START */",
                         "/* ROUND028_DM_OWNED_STAGE_END */")
    real_readback = extract(target, "/* ROUND028_DM_OWNED_STAGE_END */",
                            "#endif /* SWAPZ_ROUND028_DM_OWNED_READBACK_TEST */")
    fake_lower_read = """
static int swapz_lower_read(void *opaque, swapz_u32 block, swapz_u8 blocks,
                            swapz_u8 *destination)
{
    (void)opaque;
    ++lower_reads;
    if (lower_read_error || !destination || block < 1U ||
        blocks == 0U || block + blocks > 8U)
        return -EIO;
    memcpy(destination, disk_data + (size_t)block * SWAPZ_BLOCK_BYTES,
           (size_t)blocks * SWAPZ_BLOCK_BYTES);
    return 0;
}
"""
    first_index = base.index(original_begin)
    last_index = base.index(original_end)
    base = (base[:first_index] + fake_lower_read + real_snapshot +
            real_stage + real_readback + base[last_index:])
    base = replace_once(base, original_end, round030)
    for before, after in (
        ("\tbool prepublication_fua;\n",
         "\tbool prepublication_fua;\n\tbool round031_defer_hypothetical_ack;\n"),
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
        ("struct swapz_dm {\n",
         "struct dm_target { uint64_t len; };\n"
         "struct swapz_dm {\n\tstruct dm_target *target;\n"),
        ("ctx->authority.logical_pages = 32U;",
         "ctx->authority.logical_pages = 32U;\n"
         "\tctx->authority.physical_blocks = 8U;"),
    ):
        base = replace_once(base, before, after)
    sidecar_host = (FIXTURES / "round031-dm-sidecar-host.c").read_text(
        encoding="utf-8")
    sidecar_host = replace_once(sidecar_host,
                               "/* ROUND031_EMBED_ROUND030_SOURCE */", base)
    sidecar_host = replace_once(
        sidecar_host, "/* ROUND031_EXACT_DM_SIDECAR_SOURCE */",
        extract(target, "/* ROUND031_DM_SIDECAR_EXACT_START */",
                "/* ROUND031_DM_SIDECAR_EXACT_END */"))
    sidecar_host = replace_once(sidecar_host, "int main(void)",
                                "int swapz_round031_fixture_main(void)")
    fixture = (FIXTURES / "round035-dm-lower-host.c").read_text(
        encoding="utf-8")
    fixture = replace_once(fixture, "/* ROUND035_EMBED_PRIOR_ACTUAL_DM */",
                           sidecar_host)
    fixture = replace_once(
        fixture, "/* ROUND033_ACTUAL_PRODUCTION_COPY */",
        extract(target, "/* ROUND033_DM_ORIGINAL_GPL_IMPORT_EXACT_START */",
                "/* ROUND033_DM_ORIGINAL_GPL_IMPORT_EXACT_END */"))
    return replace_once(fixture, "/* ROUND035_ACTUAL_PRODUCTION_LOWER */",
                        new_c)


class Round035SourceTests(unittest.TestCase):
    def test_compile_and_execute_gcc_clang_strict_sanitized_original_source(self) -> None:
        source = compiled_actual_source()
        for compiler in ("gcc", "clang"):
            self.assertTrue(shutil.which(compiler), compiler)
        with tempfile.TemporaryDirectory(prefix="round035-owned-lower-") as work:
            for compiler in ("gcc", "clang"):
                with self.subTest(compiler=compiler):
                    c_file = Path(work) / (compiler + ".c")
                    codec_object = Path(work) / (compiler + "-codec.o")
                    executable = Path(work) / compiler
                    c_file.write_text(source, encoding="utf-8")
                    flags = [compiler, "-std=gnu11", "-O1", "-g", "-Wall",
                             "-Wextra", "-Wconversion", "-Wshadow", "-Werror",
                             "-fsanitize=address,undefined",
                             "-fno-sanitize-recover=all",
                             "-fno-omit-frame-pointer", "-I",
                             str(CODEC.parent)]
                    old_codec = subprocess.run(
                        [*flags, "-Wno-conversion", "-c", str(CODEC),
                         "-o", str(codec_object)], capture_output=True,
                        text=True, timeout=90)
                    self.assertEqual(old_codec.returncode, 0,
                                     old_codec.stderr[-9000:])
                    built = subprocess.run(
                        [*flags, str(c_file), str(codec_object),
                         "-llz4", "-lcrypto", "-o", str(executable)],
                        capture_output=True, text=True, timeout=90)
                    self.assertEqual(
                        built.returncode, 0,
                        "FIRST Round035 real DM source C compiler error:\n"
                        + built.stderr[-12000:])
                    result = subprocess.run(
                        [str(executable)], text=True, capture_output=True,
                        timeout=90, env={
                            **os.environ,
                            "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                            "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
                        })
                    self.assertEqual(
                        result.returncode, 0,
                        "FIRST Round035 fake-lower C sanitizer/assert error:\n"
                        + result.stderr[-12000:])
                    self.assertIn(
                        "ROUND035_ACTUAL_ORIGINAL_GPL_OWNED_LZ4_FAKE_LOWER_4096_SHA_NO_GO_PASS",
                        result.stdout)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("host-test",))
    options = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        Round035SourceTests)
    raise SystemExit(
        0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful()
        else 1
    )
