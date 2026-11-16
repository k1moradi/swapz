#!/usr/bin/env python3
"""Independent Round023 source-extracted C producer/consumer interoperability.

Both original C fragments come from this checkout. The adapter is explicit
MOCK/UNTRUSTED: a passing fixture is NOT a live MM->BIO->DM transport.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
STAGER = ROOT / "tests/tools/stage-pinned-linux-zswap-origin.py"
PRODUCER_TEST = ROOT / "tests/runtime/native/pinned-linux-zswap-compressed-handoff-test.py"
CONSUMER_HEADER = ROOT / "src/kernel/zswap-import-codec.h"
PRODUCTION_CRC32C = ROOT / "src/kernel/codec.c"
DM_TARGET = ROOT / "src/kernel/dm-target.c"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round023-cross-abi-producer-consumer.c"
DISABLED_BEGIN = "#if 0 /* SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI */"
DISABLED_END = "#endif /* SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI */"


def load_source_module(path: Path, unique_name: str):
    specification = importlib.util.spec_from_file_location(unique_name, path)
    if specification is None or specification.loader is None:
        raise AssertionError("source_module_unavailable")
    module = importlib.util.module_from_spec(specification)
    sys.modules[unique_name] = module
    specification.loader.exec_module(module)
    return module


def original_source_c() -> str:
    producer = load_source_module(STAGER, "round023_cross_source_stager")
    producer_test = load_source_module(PRODUCER_TEST, "round023_cross_source_fixture")
    actual = producer.COMPRESSED_HANDOFF_SOURCE
    if (actual.count(DISABLED_BEGIN) != 1 or
            actual.count(DISABLED_END) != 1 or
            actual.count("~crc32c(~0U, owned_bytes, entry->length)") != 1):
        raise AssertionError("producer_source_disabled_or_crc32c_drift")
    body = actual.split(DISABLED_BEGIN, 1)[1].split(DISABLED_END, 1)[0]
    for include in ("#include <linux/crc32c.h>", "#include <crypto/sha2.h>"):
        if body.count(include) != 1:
            raise AssertionError("linux_staged_header_drift: " + include)
        body = body.replace(include, "")
    return producer_test.HOST_SHIMS + "\n" + body + "\n" + FIXTURE.read_text()


class Round023IndependentCrossAbi(unittest.TestCase):
    def test_frozen_disabled_source_identity(self) -> None:
        importer = CONSUMER_HEADER.read_text(encoding="utf-8")
        dm = DM_TARGET.read_text(encoding="utf-8")
        producer = STAGER.read_text(encoding="utf-8")
        self.assertIn("#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U", importer)
        self.assertIn("swapz_zswap_import_decode(", importer)
        self.assertIn("~crc32c(~0U, owned_bytes, entry->length)", producer)
        self.assertIn(DISABLED_BEGIN, producer)
        self.assertNotIn('"zswap-import-codec.h"', dm)
        self.assertIn("SWAPZ_CODEC_METADATA_ON_MEDIA 0U",
                      (ROOT / "src/kernel/codec.h").read_text(encoding="utf-8"))
        self.assertIn("swapz_crc32c_bytes", PRODUCTION_CRC32C.read_text())
        self.assertIn("MOCK/UNTRUSTED", FIXTURE.read_text())

    def test_real_staged_producer_and_production_decoder_gcc_clang(self) -> None:
        compilers = [compiler for compiler in ("gcc", "clang")
                     if shutil.which(compiler)]
        self.assertTrue(compilers, "gcc/clang unavailable")
        with tempfile.TemporaryDirectory() as directory:
            c_file = Path(directory) / "round023-cross-abi.c"
            c_file.write_text(original_source_c(), encoding="utf-8")
            for compiler in compilers:
                with self.subTest(compiler=compiler):
                    binary = Path(directory) / ("round023-" + compiler)
                    compile_command = [
                        compiler, "-std=gnu11", "-O1", "-g", "-Wall",
                        "-Wextra", "-Werror", "-Wconversion", "-Wshadow",
                        "-fsanitize=address,undefined",
                        "-fno-sanitize-recover=all",
                        "-pthread", "-I", str(CONSUMER_HEADER.parent),
                        str(c_file), str(PRODUCTION_CRC32C),
                        "-llz4", "-lcrypto", "-o", str(binary)]
                    compile_run = subprocess.run(
                        compile_command, text=True, capture_output=True,
                        timeout=70, check=False)
                    self.assertEqual(compile_run.returncode, 0,
                                     f"{compiler} compile: {compile_run.stderr}")
                    environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=1")
                    executed = subprocess.run(
                        [str(binary)], text=True, capture_output=True,
                        env=environment, timeout=45, check=False)
                    self.assertEqual(executed.returncode, 0,
                                     f"{compiler} execute: {executed.stderr}")
                    self.assertIn("ROUND023_CROSS_ABI_SOURCE_ONLY_PASS",
                                  executed.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
