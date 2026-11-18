#!/usr/bin/env python3
"""Round037: strict sanitized ACTUAL production DM C async mailbox execution.

Import Round036 verbatim source-composed fixture and append an independently
scheduled callback section extracted from actual src/kernel/dm-target.c.
The fake post-header bytes and source BIO provider are the ONLY I/O boundary.
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
PREVIOUS = ROOT / "tests/tools/round036-dm-two-phase-verify.py"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round037-dm-async-lower-host.c"
NEW_GUARD = "SWAPZ_ROUND037_DM_ASYNC_LOWER_LIFETIME_TEST"


def compose_actual_production_c() -> str:
    text = TARGET.read_text(encoding="utf-8")
    begin = "/* ROUND037_DM_ASYNC_LOWER_EXACT_START */"
    end = "/* ROUND037_DM_ASYNC_LOWER_EXACT_END */"
    if text.count(begin) != 1 or text.count(end) != 1:
        raise AssertionError("Round037 exact production C extraction markers")
    before, tail = text.split(begin, 1)
    new_section, after = tail.split(end, 1)
    if before.count("#if defined(" + NEW_GUARD + ")") != 1:
        raise AssertionError("new guard must be defined once, nested in Round036")
    round036_guard = text[text.rfind(
        "#if defined(SWAPZ_ROUND036_DM_TRANSACTION_PHASE_TEST)", 0,
        text.index(begin)):text.index(begin)]
    for guard in runpy.run_path(str(PREVIOUS),
                                run_name="round036_fixture_import")[
                                    "ALL_SOURCE_GUARDS"]:
        if "defined(" + guard + ")" not in round036_guard:
            raise AssertionError("Round037 missing inherited guard: " + guard)
    if "#endif /* SWAPZ_ROUND036_DM_TRANSACTION_PHASE_TEST */" not in after:
        raise AssertionError("Round037 must live inside every prior guard")
    for actual in (
        "swapz_round036_dm_mock_prepare(",
        "swapz_round036_dm_mock_submit(",
        "swapz_round036_dm_mock_complete(",
        "swapz_round036_dm_mock_publish_once(",
        "spin_lock_irqsave(&mailbox->callback_lock",
        "lockdep_assert_held(&ctx->ordered_owner)",
        "mailbox->callback_references",
        "mailbox->cancellation_epoch++",
        "memzero_explicit(mailbox->owned_compressed,",
        "SWAPZ_ROUND037_SOURCE_MAPPED_AUTHENTICATED 0U",
    ):
        if actual not in new_section:
            raise AssertionError("missing real source ownership operation: " + actual)
    for forbidden in ("bio_endio(", "swapz_map(", "swapz_lower_write(",
                      "swapz_lower_read(", "swapz_finish(", "get_swap_device("):
        source_lines = [line.split("/*", 1)[0] for line in
                        new_section.splitlines()
                        if not line.lstrip().startswith("*")]
        if forbidden in "\n".join(source_lines):
            raise AssertionError("forbidden real block/map/ACK side effect: " +
                                 forbidden)
    if "return -EOPNOTSUPP;" not in text:
        raise AssertionError("live compressed ingress became enabled")
    old_source = runpy.run_path(str(PREVIOUS),
                                run_name="round036_fixture_import")[
                                    "compose_real_source"]()
    if "int main(void)" not in old_source:
        raise AssertionError("old real source fixture main missing")
    prior, last_main = old_source.rsplit("int main(void)", 1)
    old_source = prior + "int swapz_round036_fixture_main(void)" + last_main
    fixture = FIXTURE.read_text(encoding="utf-8")
    for marker, replacement in (
        ("/* ROUND037_EXTRACT_ALL_PRIOR_SOURCE */", old_source),
        ("/* ROUND037_EXTRACT_NEW_PRODUCTION_C */", new_section),
    ):
        if fixture.count(marker) != 1:
            raise AssertionError("host-only marker missing or duplicated " + marker)
        fixture = fixture.replace(marker, replacement, 1)
    return fixture


class Round037ActualSourceTests(unittest.TestCase):
    def test_original_dm_async_callback_gcc_clang_asan_ubsan(self) -> None:
        source = compose_actual_production_c()
        for compiler in ("gcc", "clang"):
            self.assertIsNotNone(shutil.which(compiler), compiler)
        with tempfile.TemporaryDirectory(prefix="round037-dm-async-") as work:
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
                                     "FIRST actual DM source compile failure:\n" +
                                     compiled.stderr[-16000:])
                    ran = subprocess.run(
                        [str(executable)], capture_output=True, text=True,
                        timeout=120, env={
                            **os.environ,
                            "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                            "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
                        })
                    self.assertEqual(ran.returncode, 0,
                                     "FIRST real DM C async callback sanitizer/assert:\n" +
                                     ran.stdout[-3500:] + ran.stderr[-16000:])
                    self.assertIn(
                        "ROUND037_ACTUAL_PRODUCTION_DM_ASYNC_LATER_CALLBACK_4096_SHA_GC_FENCE_NO_GO_PASS",
                        ran.stdout)
                    print("ROUND037_ORIGINAL_DM_ASYNC_SOURCE_" +
                          compiler.upper() + "_STRICT_ASAN_UBSAN_PASS")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("host-test",))
    parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        Round037ActualSourceTests)
    raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(
        suite).wasSuccessful() else 1)
