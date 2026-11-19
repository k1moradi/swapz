#!/usr/bin/env python3
"""Round041: execute ACTUAL production DM target-sector/GC/teardown NO_AUTH C.

Inherit the full Round040..030 real source-extracted host and source C. Only
extend its HOST-ONLY dm_target/ctx stub to represent ti->begin/private and the
original product's postheader/backing conversion; never emulate a new codec,
mapping publisher or a production Linux swap/DM lease.
"""
from __future__ import annotations

import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "src/kernel/dm-target.c"
CODEC = ROOT / "src/kernel/codec.c"
PREVIOUS = ROOT / "tests/tools/round040-dm-reissue-verify.py"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round041-dm-target-host.c"
NEW_GUARD = "SWAPZ_ROUND041_DM_TARGET_INTERVAL_MAP_NONAUTHORITY_TEST"
EXPECTED = "ROUND041_ACTUAL_DM_TARGET_INTERVAL_TABLE_GC_TEARDOWN_150_NO_AUTHORITY_PASS"


def replace_once(content: str, original: str, replacement: str) -> str:
    if content.count(original) != 1:
        raise AssertionError("Round041 source/host boundary drift: " + original[:90])
    return content.replace(original, replacement, 1)


def validate_round042_host_fixture(fixture: str) -> None:
    """Fail closed on a shadowed compressor or a fake WRITE in read fault 20."""
    original_local = "swapz_u8 compressed[SWAPZ_MAX_COMPRESSED];"
    distinct_local = "swapz_u8 compressed_page_data[SWAPZ_MAX_COMPRESSED];"
    if original_local in fixture or fixture.count(distinct_local) != 1:
        raise AssertionError("Round042 source fixture still shadows compressor")
    for required in (
        "(char *)compressed_page_data,",
        "swapz_crc32c_bytes(compressed_page_data, compressed_length)",
        "record.payload_offset, compressed_page_data, compressed_length);",
        "memzero_explicit(compressed_page_data, sizeof(compressed_page_data));",
    ):
        if fixture.count(required) != 1:
            raise AssertionError("Round042 compressed source owner drift: " + required)
    if fixture.count("case 20U:") != 1 or fixture.count("case 21U:") != 1:
        raise AssertionError("Round042 original hostile read fault removed")
    read_fault = fixture.split("case 20U:", 1)[1].split("case 21U:", 1)[0]
    if (read_fault.count("upper.bi_opf = REQ_SWAP;") != 1 or
            read_fault.count("assert(bio_op(&upper) != REQ_OP_WRITE);") != 1 or
            "upper.bi_opf = REQ_OP_WRITE" in read_fault or
            "upper.bi_opf = REQ_OP_READ" in read_fault):
        raise AssertionError("Round042 hostile read became WRITE or unverified")
    if (fixture.count("fault < 50U") != 1 or
            "ROUND041_ACTUAL_DM_TARGET_INTERVAL_TABLE_GC_TEARDOWN_150_NO_AUTHORITY_PASS"
            not in fixture):
        raise AssertionError("Round042 inherited 150-case matrix weakened")


def compose_actual_production_c() -> str:
    source = TARGET.read_text(encoding="utf-8")
    begin = "/* ROUND041_DM_TARGET_INTERVAL_EXACT_START */"
    end = "/* ROUND041_DM_TARGET_INTERVAL_EXACT_END */"
    if source.count(begin) != 1 or source.count(end) != 1:
        raise AssertionError("Round041 exact DM C marker drift")
    prior, tail = source.split(begin, 1)
    guarded_source, after = tail.split(end, 1)
    new_guard_start = "#if defined(" + NEW_GUARD + ")"
    if prior.count(new_guard_start) != 1:
        raise AssertionError("Round041 new default-undefined guard not unique")
    guard_text = prior.rsplit(new_guard_start, 1)[-1]
    inherited = (
        "SWAPZ_ROUND040_DM_SAME_SLOT_REISSUE_CONCURRENCY_TEST",
        "SWAPZ_ROUND039_DM_FAKE_CHAIN_WRITE_GC_READ_TEST",
        "SWAPZ_ROUND038_DM_ASYNC_READ_GC_TEST",
        "SWAPZ_ROUND037_DM_ASYNC_LOWER_LIFETIME_TEST",
        "SWAPZ_ROUND036_DM_TRANSACTION_PHASE_TEST",
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
    for flag in inherited:
        if "defined(" + flag + ")" not in guard_text:
            raise AssertionError("Round041 must nest predecessor " + flag)
    if "#endif /* " + NEW_GUARD + " */" not in after:
        raise AssertionError("Round041 default-off source guard unclosed")
    if "#endif /* SWAPZ_ROUND040_DM_SAME_SLOT_REISSUE_CONCURRENCY_TEST */" not in after:
        raise AssertionError("Round041 cannot run outside inherited Round040")
    for operation in (
        "SWAPZ_ROUND041_SOURCE_MAPPED_AUTHENTICATED 0U",
        "swapz_round041_dm_target_interval_refuse(",
        "swapz_round040_dm_same_source(",
        "swapz_backing_data_sector(",
        "target->begin", "target->len", "target->private",
        "ctx->authority.maps[logical_page]",
        "ctx->authority.gc_destination",
        "current_map->generation",
        "current_map->payload_crc32c",
        "source_swap_entry",
        "source_slot_epoch",
        "stored_entry_identity",
        "return -EOPNOTSUPP;",
    ):
        if operation not in guarded_source:
            raise AssertionError("Round041 actual DM source check missing: " + operation)
    no_comments = "\n".join(
        line.split("/*", 1)[0] for line in guarded_source.splitlines()
        if not line.lstrip().startswith("*")
    )
    for prohibited in (
        "bio_endio(", "swapz_map(", "swapz_lower_write(",
        "swapz_lower_read(", "swapz_finish(", "submit_bio(",
        "get_swap_device(", "swapz_gc(",
    ):
        if prohibited in no_comments:
            raise AssertionError("Round041 test-only witness calls live I/O: " +
                                 prohibited)
    if "return -EOPNOTSUPP;" not in source:
        raise AssertionError("normal source-to-DM admission unexpectedly enabled")
    previous_compose = runpy.run_path(
        str(PREVIOUS), run_name="round040_fixture_import"
    )["compose_actual_production_c"]
    old = previous_compose()
    if old.count("int main(void)") != 2:
        raise AssertionError("Round040 inherited composed main count drift")
    old_prefix, old_main = old.rsplit("int main(void)", 1)
    old = old_prefix + "int round040_fixture_main(void)" + old_main
    # This is HOST-ONLY type shimming. The kernel build uses the real
    # include/linux/device-mapper.h fields and src/kernel/dm-target.c ctx.
    old = replace_once(
        old, "struct dm_target { uint64_t len; };",
        "struct dm_target { uint64_t begin; uint64_t len; void *private; };"
    )
    old = replace_once(
        old, "struct swapz_dm {\n\tstruct dm_target *target;\n",
        "struct swapz_dm {\n\tstruct dm_target *target;\n"
        "\tswapz_u32 data_start_block;\n"
        "\tswapz_u32 *segment_backing_pages;\n"
    )
    # This complete helper is the ACTUAL product's physical AFTER-HEADER
    # conversion (and optional hole-map conversion), no host rewrite.
    backing_start = "static inline sector_t swapz_backing_data_sector("
    backing_end = "static int swapz_submit_inflight_write("
    if source.count(backing_start) != 1 or source.count(backing_end) != 1:
        raise AssertionError("real product lower-sector conversion drift")
    backing = (backing_start +
               source.split(backing_start, 1)[1].split(backing_end, 1)[0])
    backing = "typedef uint64_t sector_t;\n" + backing
    fixture = FIXTURE.read_text(encoding="utf-8")
    validate_round042_host_fixture(fixture)
    for marker, replacement in (
        ("/* ROUND041_EXTRACT_ALL_PRIOR_SOURCE */", old),
        ("/* ROUND041_EXTRACT_TARGET_BACKING_CONVERSION */", backing),
        ("/* ROUND041_EXTRACT_NEW_PRODUCTION_C */", guarded_source),
    ):
        fixture = replace_once(fixture, marker, replacement)
    return fixture


class Round042HostileFixtureSelfTests(unittest.TestCase):
    def test_source_fixture_rejects_corrupt_hostile_mutations(self) -> None:
        fixture = FIXTURE.read_text(encoding="utf-8")
        validate_round042_host_fixture(fixture)
        for original, hostile in (
            ("swapz_u8 compressed_page_data[SWAPZ_MAX_COMPRESSED];",
             "swapz_u8 compressed[SWAPZ_MAX_COMPRESSED];"),
            ("upper.bi_opf = REQ_SWAP;",
             "upper.bi_opf = REQ_OP_WRITE | REQ_SWAP;"),
            ("assert(bio_op(&upper) != REQ_OP_WRITE);",
             "assert(bio_op(&upper) == REQ_OP_WRITE);"),
            ("fault < 50U", "fault < 1U"),
            ("memzero_explicit(compressed_page_data, sizeof(compressed_page_data));",
             "memzero_explicit(compressed_page_data, 0U);"),
        ):
            with self.subTest(hostile=hostile):
                self.assertEqual(fixture.count(original), 1)
                mutant = fixture.replace(original, hostile, 1)
                with self.assertRaisesRegex(AssertionError, "Round042"):
                    validate_round042_host_fixture(mutant)
        print("ROUND042_DM_HOSTILE_SOURCE_FIXTURE_MUTANTS_REJECTED_PASS")


class ActualDmTargetNonAuthorityTests(unittest.TestCase):
    def test_real_dm_gcc_clang_target_interval_sanitizers(self) -> None:
        source = compose_actual_production_c()
        for compiler in ("gcc", "clang"):
            self.assertIsNotNone(shutil.which(compiler), compiler)
        with tempfile.TemporaryDirectory(prefix="round041-dm-target-") as work:
            for compiler in ("gcc", "clang"):
                with self.subTest(compiler=compiler):
                    source_path = Path(work) / (compiler + ".c")
                    codec_path = Path(work) / (compiler + "-codec.o")
                    binary = Path(work) / compiler
                    source_path.write_text(source, encoding="utf-8")
                    strict = [
                        compiler, "-std=gnu11", "-O1", "-g",
                        "-Wall", "-Wextra", "-Wconversion", "-Wshadow",
                        "-Werror", "-fsanitize=address,undefined",
                        "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                        "-pthread", "-I", str(CODEC.parent),
                    ]
                    codec = subprocess.run(
                        [*strict, "-Wno-conversion", "-c", str(CODEC),
                         "-o", str(codec_path)],
                        capture_output=True, text=True, timeout=90)
                    self.assertEqual(
                        codec.returncode, 0,
                        "FIRST inherited codec C error:\n" + codec.stderr[-14000:])
                    built = subprocess.run(
                        [*strict, str(source_path), str(codec_path), "-llz4",
                         "-lcrypto", "-o", str(binary)],
                        capture_output=True, text=True, timeout=150)
                    self.assertEqual(
                        built.returncode, 0,
                        "FIRST actual production DM C compiler error:\n" +
                        built.stderr[-18000:])
                    ran = subprocess.run(
                        [str(binary)], capture_output=True, text=True,
                        timeout=180,
                        env={**os.environ,
                             "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                             "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
                    self.assertEqual(
                        ran.returncode, 0,
                        "FIRST Round041 source C sanitizer/assertion error:\n" +
                        ran.stdout[-6000:] + ran.stderr[-18000:])
                    for marker in (
                        "ROUND040_ACTUAL_DM_SAME_SLOT_REISSUE_2_SOURCE_SHA_GC_READ_NO_GO_PASS",
                        EXPECTED,
                    ):
                        self.assertIn(marker, ran.stdout)
                    print("ROUND041_REAL_DM_TARGET_INTERVAL_" +
                          compiler.upper() + "_STRICT_ASAN_UBSAN_PASS")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("host-test", "hostile-self-test"))
    mode = parser.parse_args().mode
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        Round042HostileFixtureSelfTests)
    if mode == "host-test":
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(
            ActualDmTargetNonAuthorityTests))
    raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(
        suite).wasSuccessful() else 1)
