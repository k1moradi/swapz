#!/usr/bin/env python3
"""Round039: extract REAL guarded DM C write -> fake GC -> async READ chain.

The Round038 real source composer and its 135 hostile read tests remain intact.
Only the last Round038 fixture main is renamed. No independent codec or
production path is emulated here; all real C source fragments are extracted.
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
PREVIOUS = ROOT / "tests/tools/round038-dm-async-read-verify.py"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round039-dm-chain-host.c"
NEW_GUARD = "SWAPZ_ROUND039_DM_FAKE_CHAIN_WRITE_GC_READ_TEST"
EXPECTED = "ROUND039_ACTUAL_DM_WRITE_GC_READ_ORIGINAL_4096_SHA_NO_DUPLICATE_ACK_NO_GO_PASS"


def compose_actual_production_c() -> str:
    source = TARGET.read_text(encoding="utf-8")
    begin = "/* ROUND039_DM_CHAIN_EXACT_START */"
    end = "/* ROUND039_DM_CHAIN_EXACT_END */"
    if source.count(begin) != 1 or source.count(end) != 1:
        raise AssertionError("Round039 actual guarded source markers not unique")
    before, tail = source.split(begin, 1)
    guarded_source, after = tail.split(end, 1)
    if before.count("#if defined(" + NEW_GUARD + ")") != 1:
        raise AssertionError("Round039 must have exactly one default-OFF guard")
    if "defined(SWAPZ_ROUND038_DM_ASYNC_READ_GC_TEST)" not in before.rsplit(
            "#if defined(" + NEW_GUARD + ")", 1)[-1]:
        raise AssertionError("Round039 guard must depend on Round038")
    if "#endif /* SWAPZ_ROUND039_DM_FAKE_CHAIN_WRITE_GC_READ_TEST */" not in after:
        raise AssertionError("Round039 default-OFF guard not closed")
    if "#endif /* SWAPZ_ROUND037_DM_ASYNC_LOWER_LIFETIME_TEST */" not in after:
        raise AssertionError("Round039 not inside existing previous guards")
    for operation in (
        "SWAPZ_ROUND039_SOURCE_MAPPED_AUTHENTICATED 0U",
        "swapz_round039_dm_chain_initialize(",
        "swapz_round039_dm_chain_accept_write(",
        "swapz_round039_dm_chain_gc_prepare(",
        "swapz_round039_dm_chain_gc_fake_callback(",
        "swapz_round039_dm_chain_gc_finish(",
        "swapz_round039_dm_chain_read_prepare(",
        "swapz_round039_dm_chain_read_finish(",
        "swapz_round039_dm_chain_cancel_gc(",
        "swapz_round038_dm_read_revalidate(",
        "swapz_round038_dm_read_verify_private(",
        "swapz_round038_dm_read_prepare(",
        "swapz_round038_dm_read_finish(",
        "spin_lock_irqsave(&chain->gc_callback_lock",
        "memzero_explicit(chain->staged_relocation",
        "chain->hypothetical_write_acks = 1U",
    ):
        if operation not in guarded_source:
            raise AssertionError("missing actual guarded DM operation: " + operation)
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
            raise AssertionError("live side effect forbidden in CI chain: " + forbidden)
    if "return -EOPNOTSUPP;" not in source:
        raise AssertionError("default live original source admission unexpectedly enabled")
    old_source = runpy.run_path(
        str(PREVIOUS), run_name="round038_source_import"
    )["compose_actual_production_c"]()
    # The inherited Round030 source has its own textual main. Only the
    # final real Round038 host entry is renamed; earlier source is retained.
    if old_source.count("int main(void)") != 2:
        raise AssertionError("expected previous nested TWO textual mains")
    earlier_source, previous_main = old_source.rsplit("int main(void)", 1)
    old_source = (
        earlier_source + "int round038_fixture_main(void)" + previous_main
    )
    fixture = FIXTURE.read_text(encoding="utf-8")
    for marker, replacement in (
        ("/* ROUND039_EXTRACT_ALL_PRIOR_SOURCE */", old_source),
        ("/* ROUND039_EXTRACT_NEW_PRODUCTION_C */", guarded_source),
    ):
        if fixture.count(marker) != 1:
            raise AssertionError("missing or repeated new fixture source marker " +
                                 marker)
        fixture = fixture.replace(marker, replacement, 1)
    return fixture


class Round039ActualProductionChainTests(unittest.TestCase):
    def test_gcc_clang_real_dm_write_gc_async_read_asan_ubsan(self) -> None:
        source = compose_actual_production_c()
        for compiler in ("gcc", "clang"):
            self.assertIsNotNone(shutil.which(compiler), compiler)
        with tempfile.TemporaryDirectory(prefix="round039-dm-chain-") as directory:
            for compiler in ("gcc", "clang"):
                with self.subTest(compiler=compiler):
                    source_file = Path(directory) / (compiler + ".c")
                    codec_object = Path(directory) / (compiler + "-codec.o")
                    executable = Path(directory) / compiler
                    source_file.write_text(source, encoding="utf-8")
                    strict = [
                        compiler, "-std=gnu11", "-O1", "-g",
                        "-Wall", "-Wextra", "-Wconversion", "-Wshadow",
                        "-Werror", "-fsanitize=address,undefined",
                        "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                        "-pthread", "-I", str(CODEC.parent),
                    ]
                    # Existing codec.c has its own pre-existing source-policy
                    # exception, identical to the verified Round038 fixture.
                    codec = subprocess.run(
                        [*strict, "-Wno-conversion", "-c", str(CODEC),
                         "-o", str(codec_object)], capture_output=True,
                        text=True, timeout=90)
                    self.assertEqual(
                        codec.returncode, 0,
                        "FIRST existing codec compile failure:\n" +
                        codec.stderr[-14000:])
                    compiled = subprocess.run(
                        [*strict, str(source_file), str(codec_object),
                         "-llz4", "-lcrypto", "-o", str(executable)],
                        capture_output=True, text=True, timeout=120)
                    self.assertEqual(
                        compiled.returncode, 0,
                        "FIRST real guarded production DM C compile failure:\n" +
                        compiled.stderr[-16000:])
                    ran = subprocess.run(
                        [str(executable)], capture_output=True, text=True,
                        timeout=180,
                        env={**os.environ,
                             "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                             "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
                    self.assertEqual(
                        ran.returncode, 0,
                        "FIRST actual product-C write GC READ assertion/sanitizer:\n" +
                        ran.stdout[-5000:] + ran.stderr[-16000:])
                    for marker in (
                        "ROUND038_ACTUAL_PRODUCTION_DM_ASYNC_READ_4096_SHA_GC_ABA_OUTPUT_ATOMIC_NO_GO_PASS",
                        EXPECTED,
                    ):
                        self.assertIn(marker, ran.stdout)
                    print("ROUND039_REAL_DM_CHAIN_" + compiler.upper() +
                          "_STRICT_ASAN_UBSAN_PASS")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("host-test",))
    parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        Round039ActualProductionChainTests)
    raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(
        suite).wasSuccessful() else 1)
