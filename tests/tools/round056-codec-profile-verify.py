#!/usr/bin/env python3
"""Round056: execute exact pinned ORIGINAL Linux lib/lzo LZO1X and crypto/lzo
wrapper with a minimal host-kernel shim, plus default-OFF codec-profile fixture.

No source-slot/DM ownership, live pool, loaded kernel, real pressure, physical
storage, actual runtime selected driver, or compressed handoff is qualified.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/runtime/native/fixtures/round056-codec-profile.c"
CODEC = ROOT / "src/kernel/codec.c"
ORIGINAL = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
ORIGINAL_BLOBS = {
    "crypto/lzo.c": "d43242b24b4e831e7e0d26f38d2f263877d5748e",
    "include/linux/lzo.h": "4d30e3624acd237290dbfeaefdb9c710e4f85f56",
    "lib/lzo/lzo1x_compress.c": "01586af2347f5e2f8c8528b94e02622fc8b262c8",
    "lib/lzo/lzo1x_compress_safe.c": "371c9f849492814afed88a443acb2262dcf35dfe",
    "lib/lzo/lzo1x_decompress_safe.c": "318abb82c63d2c27c0d5497b7cf4e21d87d13154",
    "lib/lzo/lzodefs.h": "b60851fcf6ce54b57e87d04e917deaa2b6cf62cc",
}
FIXTURE_MUTATIONS = (
    ("crc-corruption", "swapz_crc32c_bytes(compressed, record->compressed_length) !=",
     "swapz_crc32c_bytes(compressed, record->compressed_length) =="),
    ("full-page-sha", "sizeof(actual_sha256)) != 0",
     "sizeof(actual_sha256)) == 0"),
    ("unknown-codec", "record->codec != PROFILE_LZO1X_V0)",
     "record->codec == PROFILE_LZO1X_V0)"),
    ("over-3568", "record->compressed_length > SWAPZ_MAX_COMPRESSED ||",
     "record->compressed_length > SWAPZ_BLOCK_BYTES ||"),
    ("wrong-lzo-dispatch", "if (record->codec == PROFILE_LZO1X_V0) {",
     "if (record->codec == PROFILE_LZ4_V1) {"),
)
TRAILING_ORIGINAL = "ip <  ip_end ? LZO_E_INPUT_NOT_CONSUMED : LZO_E_INPUT_OVERRUN"
TRAILING_MUTATED = "ip <  ip_end ? LZO_E_OK : LZO_E_INPUT_OVERRUN"

# Narrow HOST-only kernel header adaptor. The pristine upstream C functions
# and lzodefs.h are compiled byte-identically, in their real original directory.
# No CONFIG_HAVE_EFFICIENT_UNALIGNED_ACCESS fast memory-copy assumption:
# use the conservative byte-safe default code path for ASan/UBSan.
KERNEL = r'''
#ifndef ROUND056_HOST_LINUX_KERNEL_H
#define ROUND056_HOST_LINUX_KERNEL_H
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#if __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "Round056 host adaptation is little-endian only"
#endif
#ifndef __LITTLE_ENDIAN
#define __LITTLE_ENDIAN 1
#endif
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
#define likely(value) __builtin_expect(!!(value), 1)
#define unlikely(value) __builtin_expect(!!(value), 0)
#define noinline __attribute__((noinline))
#define min(first, second) ((first) < (second) ? (first) : (second))
#define min_t(type, first, second) \
    ((type)(first) < (type)(second) ? (type)(first) : (type)(second))
#define ALIGN(value, alignment) \
    (((value) + (alignment) - 1U) & ~((alignment) - 1U))
#define IS_ALIGNED(value, alignment) (((value) & ((alignment) - 1U)) == 0U)
#define BUILD_BUG_ON(condition) _Static_assert(!(condition), "original width")
#endif
'''
MODULE = r'''
#ifndef ROUND056_HOST_LINUX_MODULE_H
#define ROUND056_HOST_LINUX_MODULE_H
#include <linux/kernel.h>
#define EXPORT_SYMBOL_GPL(symbol)
#define MODULE_LICENSE(value)
#define MODULE_DESCRIPTION(value)
#endif
'''
UNALIGNED = r'''
#ifndef ROUND056_HOST_LINUX_UNALIGNED_H
#define ROUND056_HOST_LINUX_UNALIGNED_H
#include <linux/kernel.h>
#define get_unaligned(pointer) ({ \
    __typeof__(*(pointer) + 0) copied; \
    memcpy(&copied, (pointer), sizeof(copied)); \
    copied; \
})
#define put_unaligned(value, pointer) do { \
    __typeof__(*(pointer) + 0) copied = (value); \
    memcpy((pointer), &copied, sizeof(copied)); \
} while (0)
static inline u16 get_unaligned_le16(const void *source)
{
    const u8 *bytes = source;
    return (u16)((u16)bytes[0] | (u16)((u16)bytes[1] << 8U));
}
static inline u32 get_unaligned_le32(const void *source)
{
    const u8 *bytes = source;
    return (u32)bytes[0] | ((u32)bytes[1] << 8U) |
           ((u32)bytes[2] << 16U) | ((u32)bytes[3] << 24U);
}
static inline void put_unaligned_le32(u32 value, void *destination)
{
    u8 *bytes = destination;
    bytes[0] = (u8)(value & 0xffU);
    bytes[1] = (u8)((value >> 8U) & 0xffU);
    bytes[2] = (u8)((value >> 16U) & 0xffU);
    bytes[3] = (u8)((value >> 24U) & 0xffU);
}
#endif
'''


def require(source: str, anchor: str, description: str) -> None:
    if anchor not in source:
        raise AssertionError(f"ROUND056_CODEC_FIRST_ERROR source-drift {description}: {anchor!r}")


def run_checked(command: list[str], description: str, *, semantic_mutant: bool = False) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
    stderr = completed.stderr
    sanitizer = any(marker in stderr for marker in
                    ("AddressSanitizer", "UndefinedBehaviorSanitizer",
                     "LeakSanitizer", "runtime error:"))
    semantically_rejected = (completed.returncode == 1 and
                             "ROUND056_CODEC_FIRST_ERROR line=" in stderr and not sanitizer)
    passed = ((semantically_rejected if semantic_mutant else completed.returncode == 0)
              and not sanitizer and (semantic_mutant or not stderr))
    if not passed:
        tail = "\n".join((completed.stdout + "\n" + stderr).splitlines()[-35:])
        raise AssertionError(f"ROUND056_CODEC_FIRST_ERROR {description}: "
                             f"exit={completed.returncode} semantic={semantically_rejected} "
                             f"sanitizer={sanitizer}\n{tail}")
    return completed.stdout.strip()


def original_function(source: str, function_name: str) -> str:
    expression = re.compile(r"static\s+int\s+" + re.escape(function_name) + r"\s*\(")
    matches = list(expression.finditer(source))
    if len(matches) != 1:
        raise AssertionError(f"ROUND056_CODEC_FIRST_ERROR source-function {function_name}")
    opening = source.find("{", matches[0].end())
    depth = 0
    for offset in range(opening, len(source)):
        if source[offset] == "{":
            depth += 1
        elif source[offset] == "}":
            depth -= 1
            if depth == 0:
                return source[matches[0].start():offset + 1]
    raise AssertionError(f"ROUND056_CODEC_FIRST_ERROR unterminated {function_name}")


def mutate_decoder_function(source: str, before: str, after: str) -> str:
    signature = "static int round056_decode_profile("
    start = source.find(signature)
    if start < 0:
        raise AssertionError("ROUND056_CODEC_FIRST_ERROR missing test-only decoder")
    end = source.find("\nstatic void fill_page(", start)
    if end < 0:
        raise AssertionError("ROUND056_CODEC_FIRST_ERROR missing decoder boundary")
    function_body = source[start:end]
    if function_body.count(before) != 1 or before == after:
        raise AssertionError(f"ROUND056_CODEC_FIRST_ERROR nonunique mutation: {before}")
    return source[:start] + function_body.replace(before, after) + source[end:]


def verify_pristine_original(linux: Path) -> str:
    revision = subprocess.check_output(["git", "-C", str(linux), "rev-parse", "HEAD"],
                                       text=True).strip()
    if revision != ORIGINAL:
        raise AssertionError(f"ROUND056_CODEC_FIRST_ERROR upstream HEAD {revision}")
    if subprocess.check_output(["git", "-C", str(linux), "status", "--porcelain"],
                               text=True).strip():
        raise AssertionError("ROUND056_CODEC_FIRST_ERROR upstream checkout dirty")
    for path, expected_sha in ORIGINAL_BLOBS.items():
        actual_sha = subprocess.check_output(["git", "-C", str(linux),
                                              "hash-object", str(linux / path)],
                                             text=True).strip()
        if actual_sha != expected_sha:
            raise AssertionError(f"ROUND056_CODEC_FIRST_ERROR {path} SHA {actual_sha}")
    crypto = (linux / "crypto/lzo.c").read_text()
    require(crypto, "lzo1x_1_compress_safe(src, slen, dst, &tmp_len, ctx);",
            "original lzo-scomp compressor")
    require(crypto, "lzo1x_decompress_safe(src, slen, dst, &tmp_len);",
            "original lzo-scomp decompressor")
    require(crypto, '.cra_driver_name = "lzo-scomp"', "pinned selected implementation")
    compress = original_function(crypto, "__lzo_compress")
    decompress = original_function(crypto, "__lzo_decompress")
    require(compress, "*dlen = tmp_len;", "original compressor size_t ABI")
    require(decompress, "*dlen = tmp_len;", "original decompressor size_t ABI")
    return compress + "\n\n" + decompress + "\n"


def prepare_host_shim(root: Path, linux: Path, original_wrapper: str) -> None:
    include_root = root / "host-shim" / "linux"
    include_root.mkdir(parents=True)
    (include_root / "kernel.h").write_text(KERNEL)
    (include_root / "module.h").write_text(MODULE)
    (include_root / "unaligned.h").write_text(UNALIGNED)
    # Preserve EXACT upstream header bytes after one host-only stddef include.
    (include_root / "lzo.h").write_text("#include <stddef.h>\n" +
                                        (linux / "include/linux/lzo.h").read_text())
    (root / "round056-original-crypto-lzo-wrapper.inc").write_text(original_wrapper)


def compile_and_execute(compiler: str, root: Path, linux: Path,
                        fixture: str, lzo_decompress: str, label: str,
                        semantic_mutant: bool) -> str:
    case_root = root / label / compiler
    case_root.mkdir(parents=True, exist_ok=True)
    fixture_source = case_root / "fixture.c"
    fixture_source.write_text(fixture)
    decompressor = case_root / "original-lzo1x-decompress-safe.c"
    decompressor.write_text(lzo_decompress)
    stub = root / "host-shim"
    linux_lzo = linux / "lib/lzo"
    include_original = root / "round056-original-crypto-lzo-wrapper.inc"
    shutil.copy2(include_original, case_root / include_original.name)
    common_flags = ["-std=gnu11", "-O1", "-g", "-Wall", "-Wextra",
                    "-Werror", "-fno-omit-frame-pointer",
                    "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                    "-I", str(stub), "-I", str(linux_lzo),
                    "-I", str(ROOT / "src/kernel")]
    sources = (
        ("test-only-profile", fixture_source, ["-Wshadow", "-Wconversion"]),
        ("actual-product-codec", ROOT / "src/kernel/codec.c",
         ["-Wshadow", "-Wconversion"]),
        ("pinned-original-compressor", linux_lzo / "lzo1x_compress_safe.c", []),
        ("pinned-original-decompressor", decompressor, []),
    )
    objects: list[str] = []
    for component_name, path, strict_flags in sources:
        obj = case_root / (component_name + ".o")
        run_checked([compiler, *common_flags, *strict_flags,
                     "-c", str(path), "-o", str(obj)],
                    f"{compiler}/{label}/compile/{component_name}")
        objects.append(str(obj))
    binary = case_root / "run"
    # The exact unchanged upstream Linux lib/lzo implementation uses its
    # native -Wall -Wextra -Werror warning policy; the project/test-only C
    # stays independently strict under -Wconversion and -Wshadow too.
    run_checked([compiler, *objects, "-fsanitize=address,undefined",
                 "-llz4", "-lcrypto", "-o", str(binary)],
                f"{compiler}/{label}/link")
    return run_checked([str(binary)], f"{compiler}/{label}/C-execution",
                       semantic_mutant=semantic_mutant)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--linux-root", type=Path, required=True)
    args = parser.parse_args()
    linux = args.linux_root.resolve()
    wrapper = verify_pristine_original(linux)
    fixture = FIXTURE.read_text()
    require(fixture, "SWAPZ_CODEC_METADATA_ON_MEDIA == 0U",
            "current product code no metadata on media")
    require(CODEC.read_text(), "size_t expected_bytes;",
            "Round054 real codec conversion correction")
    for compiler in ("gcc", "clang"):
        if not shutil.which(compiler):
            raise AssertionError(f"ROUND056_CODEC_FIRST_ERROR compiler missing {compiler}")

    original_decompress = (linux / "lib/lzo/lzo1x_decompress_safe.c").read_text()
    require(original_decompress, TRAILING_ORIGINAL,
            "original LZO decoder input-not-consumed gate")
    with tempfile.TemporaryDirectory(prefix="round056-original-lzo-host-") as temporary:
        root = Path(temporary)
        prepare_host_shim(root, linux, wrapper)
        for compiler in ("gcc", "clang"):
            marker = compile_and_execute(compiler, root, linux, fixture,
                                         original_decompress, "baseline", False)
            require(marker, "ROUND056_ORIGINAL_LZO1X_AND_RAW_LZ4_HOST_PROFILE_PASS",
                    f"{compiler} baseline execution")
            print(f"ROUND056_CODEC_BASELINE compiler={compiler} {marker}", flush=True)
            for name, before, after in FIXTURE_MUTATIONS:
                mutant = mutate_decoder_function(fixture, before, after)
                compile_and_execute(compiler, root, linux, mutant,
                                    original_decompress, name, True)
                print(f"ROUND056_REAL_CODEC_PROFILE_MUTANT_KILLED compiler={compiler} "
                      f"name={name}", flush=True)
            mutated_original = original_decompress.replace(
                TRAILING_ORIGINAL, TRAILING_MUTATED, 1)
            if original_decompress.count(TRAILING_ORIGINAL) != 1:
                raise AssertionError("ROUND056_CODEC_FIRST_ERROR trailing original ambiguous")
            compile_and_execute(compiler, root, linux, fixture, mutated_original,
                                "original-lzo-input-not-consumed", True)
            print("ROUND056_REAL_ORIGINAL_LZO_SOURCE_MUTANT_KILLED "
                  f"compiler={compiler} name=input-not-consumed", flush=True)
    print("ROUND056_CODEC_C_PASS baseline=2 decoded_full_page_C_tests=GCC_CLANG "
          "semantic_C_mutants=12 pinned_original_lzo_source=YES "
          "upstream_original_checkout=PRISTINE "
          "source_authenticated=0 active=0 live_zswap_pool=NOT_RUN "
          "physical_io=0", flush=True)


if __name__ == "__main__":
    main()
