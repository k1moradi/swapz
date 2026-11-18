#!/usr/bin/env python3
"""Round033 original pinned kernel source-extracted DM host and real ELF audit."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "src/kernel/dm-target.c"
CODEC = ROOT / "src/kernel/codec.c"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round033-dm-original-import-host.c"
COMPOSER = ROOT / "tests/tools/stage-pinned-linux-zswap-composed.py"
SYMBOL = b"swapz_ci_bio_snapshot_lz4_v1"
SOURCE_START = "/* ROUND033_DM_ORIGINAL_GPL_IMPORT_EXACT_START */"
SOURCE_END = "/* ROUND033_DM_ORIGINAL_GPL_IMPORT_EXACT_END */"
GUARDS = (
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


def exact_production_c() -> str:
    entire = TARGET.read_text(encoding="utf-8")
    if entire.count(SOURCE_START) != 1 or entire.count(SOURCE_END) != 1:
        raise AssertionError("original source extraction delimiters missing or duplicate")
    prefix, remainder = entire.split(SOURCE_START, 1)
    extracted, tail = remainder.split(SOURCE_END, 1)
    guard_start = prefix.rfind("#if defined(SWAPZ_ROUND033_DM_ORIGINAL_BIO_GPL_LINK_TEST)")
    if guard_start < 0:
        raise AssertionError("source not gated")
    block = prefix[guard_start:]
    for gate in GUARDS:
        if block.count(f"defined({gate})") != 1:
            raise AssertionError("required source guard missing: " + gate)
    if "swapz_ci_bio_snapshot_lz4_v1(source_bio, &original_view," not in extracted:
        raise AssertionError("not a real call to public original GPL BIO export")
    if "return -EOPNOTSUPP;" not in extracted.split(
        "swapz_round033_dm_try_live_original_bio_v1(", 1)[1]:
        raise AssertionError("new live entrypoint not fail-closed")
    if any(name in extracted for name in (
        "bio_endio(", "swapz_lower_write(", "swapz_finish(", "swapz_stage(")):
        raise AssertionError("unexpected real lower/map/upper side effects")
    if tail.count("#endif /* SWAPZ_ROUND033_DM_ORIGINAL_BIO_GPL_LINK_TEST */") != 1:
        raise AssertionError("original-only source guard incorrectly terminated")
    if "swapz_ci_bio_snapshot_lz4_v1(" in tail:
        raise AssertionError("unprotected original GPL symbol")
    return extracted


def real_symvers_row(raw: bytes) -> bytes:
    matching = [row for row in raw.splitlines()
                if len(row.split(b"\t")) >= 2 and row.split(b"\t")[1] == SYMBOL]
    if len(matching) != 1:
        raise ValueError("original-symvers-unique-GPL-export-not-proven")
    row = matching[0]
    fields = row.split(b"\t")
    if (len(fields) != 5 or
        not re.fullmatch(rb"0x[0-9a-fA-F]{8}", fields[0]) or
        fields[1] != SYMBOL or fields[2] != b"vmlinux" or
        fields[3] != b"EXPORT_SYMBOL_GPL" or fields[4]):
        raise ValueError("original-symvers-real-vmlinux-GPL-byte-fields-invalid")
    return row


class RealOriginalConsumerTests(unittest.TestCase):
    def test_exact_original_v1_header_and_guards(self) -> None:
        source = exact_production_c()
        composer = COMPOSER.read_text(encoding="utf-8")
        marker = 'ROUND032_BIO_VIEW_HEADER = """'
        self.assertEqual(composer.count(marker), 1)
        header = composer.split(marker, 1)[1].split('"""', 1)[0]
        for field in (
            "u64 source_swap_entry;", "u64 source_slot_epoch;",
            "u64 stored_entry_identity;", "u32 compressed_crc32c;",
            "u16 compressed_length;", "u16 decoded_length;",
            "u8 representation_version;", "u8 codec;",
            "u8 original_sha256[32];"):
            self.assertIn(field, header)
        self.assertIn("EXPORT_SYMBOL_GPL(swapz_ci_bio_snapshot_lz4_v1);", composer)
        self.assertIn("BUILD_BUG_ON(sizeof(struct swapz_ci_lz4_owned_view_v1)", source)
        self.assertIn("memzero_explicit(private_scratch, SWAPZ_MAX_COMPRESSED);",
                      source)
        self.assertIn("return -EOPNOTSUPP;", source)
        self.assertNotIn("struct swapz_ci_owned_payload", source)
        self.assertEqual(TARGET.read_text(encoding="utf-8").count(
            "swapz_ci_bio_snapshot_lz4_v1("), 1)

    def test_original_modpost_export_strict_negative_rows(self) -> None:
        valid = b"0x00000000\t" + SYMBOL + b"\tvmlinux\tEXPORT_SYMBOL_GPL\t\n"
        self.assertEqual(real_symvers_row(valid), valid.rstrip(b"\n"))
        for invalid in (
            b"", valid + valid,
            valid.replace(b"EXPORT_SYMBOL_GPL", b"EXPORT_SYMBOL"),
            valid.replace(b"vmlinux", b"other-module"),
            valid.replace(b"0x00000000", b"00000000"),
            valid.replace(b"\t", b" "),
            valid.rstrip(b"\t\n") + b"\n",
            valid.rstrip(b"\n") + b"private\n",
        ):
            with self.subTest(bad=invalid[:100]), self.assertRaises(ValueError):
                real_symvers_row(invalid)

    def test_actual_production_dm_c_gcc_clang_sanitizers(self) -> None:
        fixture = FIXTURE.read_text(encoding="utf-8")
        placeholder = "/* ROUND033_DM_ORIGINAL_GPL_IMPORT_HOST_EXACT */"
        self.assertEqual(fixture.count(placeholder), 1)
        fixture = fixture.replace(placeholder, exact_production_c(), 1)
        for compiler in ("gcc", "clang"):
            self.assertTrue(shutil.which(compiler), compiler)
        with tempfile.TemporaryDirectory(prefix="round033-original-dm-") as tmp:
            for compiler in ("gcc", "clang"):
                with self.subTest(compiler=compiler):
                    executable = Path(tmp) / (compiler + "-original-consumer")
                    source = Path(tmp) / (compiler + "-source.c")
                    codec = Path(tmp) / (compiler + "-codec.o")
                    source.write_text(fixture, encoding="utf-8")
                    common = [
                        compiler, "-std=gnu11", "-O1", "-g", "-Wall",
                        "-Wextra", "-Wconversion", "-Wshadow", "-Werror",
                        "-fsanitize=address,undefined",
                        "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                        "-I", str(CODEC.parent)]
                    codec_build = subprocess.run([
                        *common, "-Wno-conversion", "-c", str(CODEC), "-o",
                        str(codec)], text=True, capture_output=True, timeout=60)
                    self.assertEqual(codec_build.returncode, 0,
                                     codec_build.stderr[-8000:])
                    built = subprocess.run([
                        *common, str(source), str(codec), "-llz4", "-lcrypto",
                        "-o", str(executable)], text=True, capture_output=True,
                        timeout=60)
                    self.assertEqual(built.returncode, 0, built.stderr[-8000:])
                    executed = subprocess.run(
                        [str(executable)], text=True, capture_output=True,
                        timeout=60, env={**os.environ,
                            "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                            "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
                    self.assertEqual(executed.returncode, 0,
                                     executed.stderr[-8000:])
                    self.assertIn(
                        "ROUND033_ACTUAL_DM_ORIGINAL_GPL_COPY_SOURCE_HOST_GCC_CLANG_LIVE_NO_GO_PASS",
                        executed.stdout)


def verify_link(args: argparse.Namespace) -> None:
    original_row = real_symvers_row(args.symvers.read_bytes())
    symbol = SYMBOL.decode("ascii")
    def symbols(binary: Path) -> list[str]:
        result = subprocess.run(["nm", "-u", str(binary)], check=True,
                                capture_output=True, text=True, timeout=30)
        return [line.split()[-1] for line in result.stdout.splitlines()
                if line.split()]

    if symbols(args.guarded).count(symbol) != 1:
        raise ValueError("real-guarded-dm-module-ELF-missing-original-GPL-undefined")
    if symbol in symbols(args.default):
        raise ValueError("ordinary-dm-module-illegal-original-GPL-import")
    if args.guarded.read_bytes() == args.default.read_bytes():
        raise ValueError("guarded-and-default-ELF-identical")
    for binary in (args.guarded, args.default):
        vermagic = subprocess.run(["modinfo", "-F", "vermagic", str(binary)],
                                 check=True, capture_output=True, text=True,
                                 timeout=30).stdout
        if not vermagic.startswith(args.kernel_release + " "):
            raise ValueError("original-kernel-ELF-vermagic-mismatch")
        elf = subprocess.run(["readelf", "-h", str(binary)], check=True,
                             capture_output=True, text=True, timeout=30).stdout
        if not re.search(r"Type:\s+REL\b", elf):
            raise ValueError("not-real-relocatable-kernel-module-ELF")
    print("ROUND033_GENUINE_SAME_ORIGINAL_KERNEL_MODULE_SYMVERS_GPL_MODPOST_PASS")
    print("ORIGINAL_MODULE_SYMVERS_ROW_HEX=" + original_row.hex())
    print("DM_REAL_GPL_UNDEFINED_RESOLVED=1 DM_DEFAULT_IMPORT_ABSENT=1")
    print("PHASE_A_BLOCKED=1 DIRECT_COMPRESSED=NO_GO LOADED_PHYSICAL=NOT_RUN")


def main() -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_subparsers(dest="mode", required=True)
    modes.add_parser("host-test")
    standalone = modes.add_parser("verify-symvers")
    standalone.add_argument("--symvers", type=Path, required=True)
    link = modes.add_parser("verify-link")
    link.add_argument("--symvers", type=Path, required=True)
    link.add_argument("--guarded", type=Path, required=True)
    link.add_argument("--default", type=Path, required=True)
    link.add_argument("--kernel-release", required=True)
    args = parser.parse_args()
    if args.mode == "host-test":
        tests = unittest.defaultTestLoader.loadTestsFromTestCase(
            RealOriginalConsumerTests)
        result = unittest.TextTestRunner(verbosity=2).run(tests)
        return 0 if result.wasSuccessful() else 1
    try:
        if args.mode == "verify-symvers":
            row = real_symvers_row(args.symvers.read_bytes())
            print("ROUND033_ORIGINAL_VMLINUX_GPL_SYMBOL_ROW_EXACT_ONE_HEX=" + row.hex())
            return 0
        verify_link(args)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print("ROUND033_GENUINE_SAME_KERNEL_LINK_BLOCKED first_cause=" + str(error))
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
