#!/usr/bin/env python3
"""Round038: source-extract actual guarded production DM fake async lower READ.

Reuse all Round030..037 real C and the exact Round037 fixture, then append
only the new Round038 C region. No independently reimplemented read algorithm
and no source provider, DM map, or physical-device I/O authority is admitted.
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
PREVIOUS = ROOT / "tests/tools/round037-dm-async-verify.py"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round038-dm-async-read-host.c"
NEW_GUARD = "SWAPZ_ROUND038_DM_ASYNC_READ_GC_TEST"


def compose_actual_production_c() -> str:
    text = TARGET.read_text(encoding="utf-8")
    begin = "/* ROUND038_DM_ASYNC_READ_GC_EXACT_START */"
    end = "/* ROUND038_DM_ASYNC_READ_GC_EXACT_END */"
    if text.count(begin) != 1 or text.count(end) != 1:
        raise AssertionError("Round038 exact actual production C markers")
    before, tail = text.split(begin, 1)
    new_section, after = tail.split(end, 1)
    if before.count("#if defined(" + NEW_GUARD + ")") != 1:
        raise AssertionError("Round038 default-OFF guard not unique")
    if "SWAPZ_ROUND037_DM_ASYNC_LOWER_LIFETIME_TEST" not in (
        before.rsplit("/* ROUND037_DM_ASYNC_LOWER_EXACT_END */", 1)[-1]
        + after.split("#endif /* SWAPZ_ROUND037_", 1)[0]
    ):
        # Exact ordering is additionally checked below.
        pass
    if "#endif /* SWAPZ_ROUND038_DM_ASYNC_READ_GC_TEST */" not in after:
        raise AssertionError("Round038 guard missing")
    if "#endif /* SWAPZ_ROUND037_DM_ASYNC_LOWER_LIFETIME_TEST */" not in after:
        raise AssertionError("Round038 must remain inside all older guards")
    if before.rfind("#if defined(SWAPZ_ROUND038_DM_ASYNC_READ_GC_TEST)") < (
        before.rfind("/* ROUND037_DM_ASYNC_LOWER_EXACT_END */")
    ):
        raise AssertionError("Round038 section not following Round037 C")
    for required in (
        "SWAPZ_ROUND038_SOURCE_MAPPED_AUTHENTICATED 0U",
        "swapz_round038_dm_read_snapshot_write(",
        "swapz_round038_dm_read_revalidate(",
        "swapz_round038_dm_read_prepare(",
        "swapz_round038_dm_read_submit(",
        "swapz_round038_dm_read_fake_callback(",
        "swapz_round038_dm_read_verify_private(",
        "swapz_round038_dm_read_finish(",
        "swapz_round038_dm_read_cancel(",
        "spin_lock_irqsave(&mailbox->callback_lock",
        "lockdep_assert_held(&ctx->ordered_owner)",
        "mailbox->callback_references",
        "mailbox->cancellation_epoch++",
        "LZ4_decompress_safe(",
        "swapz_crc32c_bytes(",
        "swapz_zswap_import_sha256(",
        "memcpy(mock_upper_read_destination, mailbox->verified_original,",
        "memzero_explicit(mailbox->fake_lower_image,",
    ):
        if required not in new_section:
            raise AssertionError("missing real guarded production C operation " +
                                 required)
    code = "\n".join(line.split("/*", 1)[0]
                     for line in new_section.splitlines()
                     if not line.lstrip().startswith("*"))
    for forbidden in ("bio_endio(", "swapz_map(", "swapz_lower_write(",
                      "swapz_lower_read(", "swapz_finish(",
                      "get_swap_device(", "submit_bio("):
        if forbidden in code:
            raise AssertionError("live original/DM side effect in READ: " +
                                 forbidden)
    if "return -EOPNOTSUPP;" not in text:
        raise AssertionError("disabled live source admission was removed")
    previous_compose = runpy.run_path(
        str(PREVIOUS), run_name="round037_source_import")[
            "compose_actual_production_c"]
    old_source = previous_compose()
    if old_source.count("int main(void)") != 1:
        raise AssertionError("expected one Round037 real source fixture main")
    old_source = old_source.replace(
        "int main(void)", "int round037_fixture_main(void)", 1)
    fixture = FIXTURE.read_text(encoding="utf-8")
    for marker, replacement in (
        ("/* ROUND038_EXTRACT_ALL_PRIOR_SOURCE */", old_source),
        ("/* ROUND038_EXTRACT_NEW_PRODUCTION_C */", new_section),
    ):
        if fixture.count(marker) != 1:
            raise AssertionError("missing/duplicate host extraction marker " +
                                 marker)
        fixture = fixture.replace(marker, replacement, 1)
    return fixture


class Round038ActualProductionSourceTests(unittest.TestCase):
    def test_gcc_clang_actual_dm_c_async_read_asan_ubsan(self) -> None:
        source = compose_actual_production_c()
        for compiler in ("gcc", "clang"):
            self.assertIsNotNone(shutil.which(compiler), compiler)
        with tempfile.TemporaryDirectory(prefix="round038-dm-async-read-") as work:
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
                    self.assertEqual(codec.returncode, 0,
                                     "FIRST legacy codec compile failure:\n" +
                                     codec.stderr[-14000:])
                    compiled = subprocess.run(
                        [*strict, str(source_file), str(codec_object),
                         "-llz4", "-lcrypto", "-o", str(executable)],
                        capture_output=True, text=True, timeout=90)
                    self.assertEqual(compiled.returncode, 0,
                                     "FIRST real production C compile failure:\n" +
                                     compiled.stderr[-16000:])
                    ran = subprocess.run(
                        [str(executable)], capture_output=True, text=True,
                        timeout=150, env={
                            **os.environ,
                            "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                            "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
                        })
                    self.assertEqual(
                        ran.returncode, 0,
                        "FIRST real production DM async READ C sanitizer/assert:\n" +
                        ran.stdout[-3500:] + ran.stderr[-16000:])
                    self.assertIn(
                        "ROUND038_ACTUAL_PRODUCTION_DM_ASYNC_READ_4096_SHA_GC_ABA_OUTPUT_ATOMIC_NO_GO_PASS",
                        ran.stdout)
                    print("ROUND038_ORIGINAL_DM_ASYNC_READ_SOURCE_" +
                          compiler.upper() + "_STRICT_ASAN_UBSAN_PASS")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("host-test",))
    parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        Round038ActualProductionSourceTests)
    raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(
        suite).wasSuccessful() else 1)
