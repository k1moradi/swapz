#!/usr/bin/env python3
"""Round040: execute REAL guarded production DM C same-slot A/B reissue.

The inherited Round039, Round038 and all earlier source-only tests execute
unchanged in the same sanitized binary. This adds only exact production C
extraction plus host-owned fake lower bytes and independent callback threads.
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
PREVIOUS = ROOT / "tests/tools/round039-dm-chain-verify.py"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round040-dm-reissue-host.c"
NEW_GUARD = "SWAPZ_ROUND040_DM_SAME_SLOT_REISSUE_CONCURRENCY_TEST"
EXPECTED = "ROUND040_ACTUAL_DM_SAME_SLOT_REISSUE_2_SOURCE_SHA_GC_READ_NO_GO_PASS"


def compose_actual_production_c() -> str:
    source = TARGET.read_text(encoding="utf-8")
    begin = "/* ROUND040_DM_REISSUE_EXACT_START */"
    end = "/* ROUND040_DM_REISSUE_EXACT_END */"
    if source.count(begin) != 1 or source.count(end) != 1:
        raise AssertionError("Round040 guarded source extraction boundaries")
    before, tail = source.split(begin, 1)
    guarded_source, after = tail.split(end, 1)
    if before.count("#if defined(" + NEW_GUARD + ")") != 1:
        raise AssertionError("Round040 undefined-by-default guard not unique")
    guard = before.rsplit("#if defined(" + NEW_GUARD + ")", 1)[-1]
    for required_guard in (
        "SWAPZ_ROUND039_DM_FAKE_CHAIN_WRITE_GC_READ_TEST",
        "SWAPZ_ROUND038_DM_ASYNC_READ_GC_TEST",
        "SWAPZ_ROUND037_DM_ASYNC_LOWER_LIFETIME_TEST",
        "SWAPZ_ROUND036_DM_TRANSACTION_PHASE_TEST",
        "SWAPZ_ROUND033_DM_ORIGINAL_BIO_GPL_LINK_TEST",
        "SWAPZ_ROUND024_DM_IMPORT_KBUILD_PROBE",
    ):
        if "defined(" + required_guard + ")" not in guard:
            raise AssertionError("missing predecessor source guard " +
                                 required_guard)
    if "#endif /* SWAPZ_ROUND040_DM_SAME_SLOT_REISSUE_CONCURRENCY_TEST */" not in after:
        raise AssertionError("Round040 test-only gate not closed")
    if "#endif /* SWAPZ_ROUND039_DM_FAKE_CHAIN_WRITE_GC_READ_TEST */" not in after:
        raise AssertionError("Round040 not nested under Round039")
    for operation in (
        "SWAPZ_ROUND040_SOURCE_MAPPED_AUTHENTICATED 0U",
        "swapz_round040_dm_reissue_initialize(",
        "swapz_round040_dm_reissue_arm(",
        "swapz_round040_dm_reissue_current(",
        "swapz_round040_dm_reissue_finish_write(",
        "swapz_round040_dm_reissue_gc_finish(",
        "swapz_round040_dm_reissue_read_finish(",
        "swapz_round040_dm_reissue_retire(",
        "swapz_round040_dm_same_source(",
        "swapz_round037_dm_async_finish(",
        "swapz_round039_dm_chain_gc_finish(",
        "swapz_round039_dm_chain_read_finish(",
        "source_swap_entry",
        "source_slot_epoch",
        "stored_entry_identity",
        "original_sha256",
        "compressed_crc32c",
        "memzero_explicit(witness->record",
    ):
        if operation not in guarded_source:
            raise AssertionError("missing real source arbitration " + operation)
    code = "\n".join(
        line.split("/*", 1)[0] for line in guarded_source.splitlines()
        if not line.lstrip().startswith("*")
    )
    for forbidden in (
        "bio_endio(", "swapz_map(", "swapz_lower_write(",
        "swapz_lower_read(", "swapz_finish(", "submit_bio(",
        "get_swap_device(", "swapz_gc(",
    ):
        if forbidden in code:
            raise AssertionError("live side effect in CI-only reissue: " +
                                 forbidden)
    if "return -EOPNOTSUPP;" not in source:
        raise AssertionError("original production source admission enabled")
    previous_compose = runpy.run_path(
        str(PREVIOUS), run_name="round039_source_import"
    )["compose_actual_production_c"]
    previous_source = previous_compose()
    if previous_source.count("int main(void)") != 2:
        raise AssertionError("Round039 nested two-main source drift")
    prefix, last_main = previous_source.rsplit("int main(void)", 1)
    previous_source = prefix + "int round039_fixture_main(void)" + last_main
    fixture = FIXTURE.read_text(encoding="utf-8")
    for marker, replacement in (
        ("/* ROUND040_EXTRACT_ALL_PRIOR_SOURCE */", previous_source),
        ("/* ROUND040_EXTRACT_NEW_PRODUCTION_C */", guarded_source),
    ):
        if fixture.count(marker) != 1:
            raise AssertionError("Round040 source insertion marker drift " +
                                 marker)
        fixture = fixture.replace(marker, replacement, 1)
    return fixture


class Round040ActualProductionReissueTests(unittest.TestCase):
    def test_gcc_clang_same_slot_reissue_asan_ubsan(self) -> None:
        source = compose_actual_production_c()
        for compiler in ("gcc", "clang"):
            self.assertIsNotNone(shutil.which(compiler), compiler)
        with tempfile.TemporaryDirectory(prefix="round040-dm-reissue-") as work:
            for compiler in ("gcc", "clang"):
                with self.subTest(compiler=compiler):
                    source_file = Path(work) / (compiler + ".c")
                    codec_object = Path(work) / (compiler + "-codec.o")
                    executable = Path(work) / compiler
                    source_file.write_text(source, encoding="utf-8")
                    strict = [
                        compiler, "-std=gnu11", "-O1", "-g",
                        "-Wall", "-Wextra", "-Wconversion", "-Wshadow",
                        "-Werror", "-fsanitize=address,undefined",
                        "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                        "-pthread", "-I", str(CODEC.parent),
                    ]
                    codec = subprocess.run(
                        [*strict, "-Wno-conversion", "-c", str(CODEC),
                         "-o", str(codec_object)], capture_output=True,
                        text=True, timeout=90)
                    self.assertEqual(
                        codec.returncode, 0,
                        "FIRST inherited codec compiler failure:\n" +
                        codec.stderr[-12000:])
                    compiled = subprocess.run(
                        [*strict, str(source_file), str(codec_object),
                         "-llz4", "-lcrypto", "-o", str(executable)],
                        capture_output=True, text=True, timeout=150)
                    self.assertEqual(
                        compiled.returncode, 0,
                        "FIRST actual production DM source compiler failure:\n" +
                        compiled.stderr[-18000:])
                    ran = subprocess.run(
                        [str(executable)], capture_output=True, text=True,
                        timeout=180,
                        env={**os.environ,
                             "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                             "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
                    self.assertEqual(
                        ran.returncode, 0,
                        "FIRST same-slot reissue source assertion/sanitizer:\n" +
                        ran.stdout[-5000:] + ran.stderr[-18000:])
                    for marker in (
                        "ROUND039_ACTUAL_DM_WRITE_GC_READ_ORIGINAL_4096_SHA_NO_DUPLICATE_ACK_NO_GO_PASS",
                        EXPECTED,
                    ):
                        self.assertIn(marker, ran.stdout)
                    print("ROUND040_REAL_DM_SAME_SLOT_" + compiler.upper() +
                          "_STRICT_ASAN_UBSAN_PASS")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("host-test",))
    parser.parse_args()
    tests = unittest.defaultTestLoader.loadTestsFromTestCase(
        Round040ActualProductionReissueTests)
    raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(
        tests).wasSuccessful() else 1)
