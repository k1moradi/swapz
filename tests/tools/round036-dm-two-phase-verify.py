#!/usr/bin/env python3
"""Round036: host-execute actual guarded production DM two-phase C, never fake it.

Reuse Round035's exact composed source extractor and mock kernel boundary.
Only fake original BIO provider and post-header lower copying are modeled;
actual production DM stage, LZ4 decoder/CRC/SHA and new ledger are extracted.
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
FIXTURE = ROOT / "tests/runtime/native/fixtures/round036-dm-two-phase-host.c"
PREVIOUS = ROOT / "tests/tools/round035-dm-lower-verify.py"
ALL_SOURCE_GUARDS = (
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


def compose_real_source() -> str:
    source_text = TARGET.read_text(encoding="utf-8")
    begin = "/* ROUND036_DM_TRANSACTION_PHASE_EXACT_START */"
    end = "/* ROUND036_DM_TRANSACTION_PHASE_EXACT_END */"
    if source_text.count(begin) != 1 or source_text.count(end) != 1:
        raise AssertionError("new actual production DM C markers missing")
    earlier, tail = source_text.split(begin, 1)
    new_section, _ = tail.split(end, 1)
    guard = earlier[earlier.rfind(
        "#if defined(SWAPZ_ROUND036_DM_TRANSACTION_PHASE_TEST)"):]
    for flag in ALL_SOURCE_GUARDS:
        if guard.count("defined(" + flag + ")") != 1:
            raise AssertionError("incorrect default-off original DM source guard: " + flag)
    for actual_operation in (
        "swapz_round033_dm_copy_original_bio_v1_for_link(",
        "swapz_round028_dm_stage_owned_payload(",
        "LZ4_decompress_safe(",
        "swapz_zswap_import_sha256(",
        "swapz_crc32c_bytes(",
        "swapz_zswap_admission_lower_write_done(",
        "swapz_zswap_admission_publish_ram_mapping(",
        "swapz_zswap_admission_upper_write_ack(",
        "lockdep_assert_held(&ctx->ordered_owner)",
        "SWAPZ_ROUND036_SOURCE_MAPPED_AUTHENTICATED 0U",
        "memzero_explicit(ledger->private_compressed, SWAPZ_MAX_COMPRESSED)",
    ):
        if actual_operation not in new_section:
            raise AssertionError("actual production phase operation missing: " + actual_operation)
    for forbidden in ("bio_endio(", "swapz_map(", "swapz_lower_write(",
                      "swapz_lower_read(", "swapz_finish(", "get_swap_device("):
        if forbidden in new_section:
            # Comments may mention forbidden identifiers: test C invocation.
            actual_lines = [line.split("/*", 1)[0] for line in new_section.splitlines()
                            if not line.strip().startswith("*")]
            if forbidden in "\n".join(actual_lines):
                raise AssertionError("live I/O or map side effect leaked: " + forbidden)
    if "return -EOPNOTSUPP;" not in source_text:
        raise AssertionError("original real source admission not disabled")
    old_source = runpy.run_path(str(PREVIOUS),
                                run_name="round035_fixture_import")[
                                    "compiled_actual_source"]()
    if old_source.count("int main(void)") != 2:
        raise AssertionError("nested Round030/035 exact source main drift")
    prefix, old_main = old_source.rsplit("int main(void)", 1)
    old_source = prefix + "int swapz_round035_fixture_main(void)" + old_main
    fixture = FIXTURE.read_text(encoding="utf-8")
    for marker, replacement in (
        ("/* ROUND036_EXTRACT_ALL_PRIOR_SOURCE */", old_source),
        ("/* ROUND036_EXTRACT_NEW_PRODUCTION_C */", new_section),
    ):
        if fixture.count(marker) != 1:
            raise AssertionError("source fixture missing one marker: " + marker)
        fixture = fixture.replace(marker, replacement, 1)
    return fixture


class Round036SourceTests(unittest.TestCase):
    def test_actual_production_c_gcc_clang_strict_asan_ubsan(self) -> None:
        source = compose_real_source()
        for compiler in ("gcc", "clang"):
            self.assertIsNotNone(shutil.which(compiler), compiler)
        with tempfile.TemporaryDirectory(prefix="round036-dm-phases-") as work:
            for compiler in ("gcc", "clang"):
                with self.subTest(compiler=compiler):
                    c_path = Path(work) / (compiler + ".c")
                    codec_object = Path(work) / (compiler + "-codec.o")
                    executable = Path(work) / compiler
                    c_path.write_text(source, encoding="utf-8")
                    strict = [
                        compiler, "-std=gnu11", "-O1", "-g",
                        "-Wall", "-Wextra", "-Wconversion", "-Wshadow",
                        "-Werror", "-fsanitize=address,undefined",
                        "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                        "-I", str(CODEC.parent),
                    ]
                    codec = subprocess.run(
                        [*strict, "-Wno-conversion", "-c", str(CODEC),
                         "-o", str(codec_object)], capture_output=True,
                        text=True, timeout=90)
                    self.assertEqual(codec.returncode, 0,
                                     "FIRST real legacy codec compiler error:\n" +
                                     codec.stderr[-12000:])
                    compiled = subprocess.run(
                        [*strict, str(c_path), str(codec_object),
                         "-llz4", "-lcrypto", "-o", str(executable)],
                        capture_output=True, text=True, timeout=90)
                    self.assertEqual(compiled.returncode, 0,
                                     "FIRST actual Round036 DM C source compiler error:\n" +
                                     compiled.stderr[-14000:])
                    ran = subprocess.run(
                        [str(executable)], capture_output=True, text=True,
                        timeout=90, env={
                            **os.environ,
                            "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                            "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
                        })
                    self.assertEqual(ran.returncode, 0,
                                     "FIRST Round036 DM source ASan/UBSan/assert:\n" +
                                     ran.stdout[-2000:] + ran.stderr[-14000:])
                    self.assertIn(
                        "ROUND036_REAL_DM_C_FAKE_LOWER_TWO_PHASE_LZ4_4096_SHA_ONE_MOCK_ACK_NO_GO_PASS",
                        ran.stdout)
                    print("ROUND036_REAL_DM_TWO_PHASE_SOURCE_" +
                          compiler.upper() + "_STRICT_ASAN_UBSAN_PASS")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("host-test",))
    parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Round036SourceTests)
    raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(
        suite).wasSuccessful() else 1)
