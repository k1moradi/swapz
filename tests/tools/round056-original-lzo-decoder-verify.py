#!/usr/bin/env python3
"""Execute pristine original Linux LZO1X C with a narrow rootless Linux header shim."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/runtime/native/codec/round056-original-lzo1x-profile.c"
PRODUCT = ROOT / "src/kernel/codec.c"
MUTANTS = (
 ("compressed-crc", "if (swapz_crc32c_bytes(source, record->compressed_length) != record->crc32c)", "if (0 && swapz_crc32c_bytes(source, record->compressed_length) != record->crc32c)"),
 ("original-sha", "if (memcmp(hash, record->sha256, 32U) != 0)", "if (0 && memcmp(hash, record->sha256, 32U) != 0)"),
 ("format-version", "record->version != 1U", "record->version != 2U"),
 ("complete-input", "!= LZO_E_OK ||", "== -999 ||"),
)
HEADERS = {
 "linux/kernel.h": """#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>
typedef uint32_t u32;
typedef uint64_t u64;
#define likely(x) __builtin_expect(!!(x), 1)
#define unlikely(x) __builtin_expect(!!(x), 0)
#define noinline __attribute__((noinline))
#define BUILD_BUG_ON(condition) _Static_assert(!(condition), "original invariant")
#define min(a,b) ({ __typeof__(a) first = (a); __typeof__(b) second = (b); first < second ? first : second; })
#define min_t(type,a,b) ({ type first = (a); type second = (b); first < second ? first : second; })
#define ALIGN(value,alignment) (((value) + (alignment) - 1U) & ~((alignment) - 1U))
#define IS_ALIGNED(value,alignment) (((value) & ((alignment) - 1U)) == 0U)
""",
 "linux/unaligned.h": """#pragma once
#include <stdint.h>
#include <string.h>
#define get_unaligned(pointer) ({ __typeof__(*(pointer) + 0) value; memcpy(&value, (const void *)(pointer), sizeof(value)); value; })
#define put_unaligned(value,pointer) do { __typeof__(*(pointer)) value_copy = (value); memcpy((void *)(pointer), &value_copy, sizeof(value_copy)); } while (0)
static inline uint16_t get_unaligned_le16(const void *pointer) { uint16_t value; memcpy(&value,pointer,sizeof(value)); return value; }
static inline uint32_t get_unaligned_le32(const void *pointer) { uint32_t value; memcpy(&value,pointer,sizeof(value)); return value; }
static inline void put_unaligned_le32(uint32_t value, void *pointer) { memcpy(pointer,&value,sizeof(value)); }
""",
 "linux/module.h": """#pragma once
#define EXPORT_SYMBOL_GPL(...)
#define MODULE_LICENSE(...)
#define MODULE_DESCRIPTION(...)
""",
}
ORIGINAL_BLOBS = {
 "crypto/lzo.c": "d43242b24b4e831e7e0d26f38d2f263877d5748e",
 "include/linux/lzo.h": "4d30e3624acd237290dbfeaefdb9c710e4f85f56",
 "lib/lzo/lzo1x_compress.c": "01586af2347f5e2f8c8528b94e02622fc8b262c8",
 "lib/lzo/lzo1x_compress_safe.c": "371c9f849492814afed88a443acb2262dcf35dfe",
 "lib/lzo/lzo1x_decompress_safe.c": "318abb82c63d2c27c0d5497b7cf4e21d87d13154",
 "lib/lzo/lzodefs.h": "b60851fcf6ce54b57e87d04e917deaa2b6cf62cc",
}
ORIGINAL = {
 "crypto/lzo.c": ["__lzo_compress(", "lzo1x_1_compress_safe(", "__lzo_decompress(", "lzo1x_decompress_safe(", 'cra_driver_name = "lzo-scomp"'],
 "lib/lzo/lzo1x_compress.c": ["lzo1x_1_do_compress", "lzogeneric1x_1_compress"],
 "lib/lzo/lzo1x_compress_safe.c": ["#define LZO_SAFE(name) name##_safe"],
 "lib/lzo/lzo1x_decompress_safe.c": ["LZO_E_INPUT_NOT_CONSUMED", "ip == ip_end"],
 "lib/lzo/lzodefs.h": ["LZO_VERSION 1", "M4_MARKER"],
 "include/linux/lzo.h": ["LZO1X_1_MEM_COMPRESS", "LZO_E_INPUT_NOT_CONSUMED"],
}

def checked(command: list[str], label: str, mutant: bool = False) -> str:
    proc = subprocess.run(command, capture_output=True, text=True, timeout=90,
                          env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
                               "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
    sanitizer = any(x in proc.stderr for x in ("AddressSanitizer", "LeakSanitizer",
                                                 "UndefinedBehaviorSanitizer", "runtime error:"))
    semantic = "ROUND056_FIRST_ERROR line=" in proc.stderr
    ok = (proc.returncode == 1 and semantic and not sanitizer) if mutant else (
         proc.returncode == 0 and not proc.stderr and not sanitizer)
    if not ok:
        details = "\n".join((proc.stdout + "\n" + proc.stderr).splitlines()[-24:])
        raise AssertionError(f"ROUND056_DECODER_FIRST_ERROR {label} exit={proc.returncode} "
                             f"semantic={semantic} sanitizer={sanitizer}\n{details}")
    return proc.stdout.strip()

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--linux-root", type=Path, required=True)
    linux = parser.parse_args().linux_root.resolve()
    if checked(["git", "-C", str(linux), "rev-parse", "HEAD"], "pin") != PIN:
        raise AssertionError("ROUND056_DECODER_FIRST_ERROR wrong original SHA")
    if checked(["git", "-C", str(linux), "status", "--porcelain"], "clean"):
        raise AssertionError("ROUND056_DECODER_FIRST_ERROR dirty original")
    for path, expected_blob in ORIGINAL_BLOBS.items():
        actual_blob = checked(["git", "-C", str(linux), "hash-object",
                               str(linux / path)], f"original-blob/{path}")
        if actual_blob != expected_blob:
            raise AssertionError(f"ROUND056_DECODER_FIRST_ERROR original blob SHA {path}: {actual_blob}")
    for path, anchors in ORIGINAL.items():
        contents = (linux / path).read_text()
        for anchor in anchors:
            if anchor not in contents:
                raise AssertionError(f"ROUND056_DECODER_FIRST_ERROR original anchor {path}: {anchor}")
    source = FIXTURE.read_text()
    for name, before, after in MUTANTS:
        if source.count(before) != 1 or before == after:
            raise AssertionError(f"ROUND056_DECODER_FIRST_ERROR non-vacuous source mutant: {name}")
    if not PRODUCT.is_file() or not shutil.which("gcc") or not shutil.which("clang"):
        raise AssertionError("ROUND056_DECODER_FIRST_ERROR missing product or compiler")
    with tempfile.TemporaryDirectory(prefix="round056-pinned-lzo-") as temporary:
        scratch = Path(temporary)
        for path, contents in HEADERS.items():
            target = scratch / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents)
        (scratch / "linux/lzo.h").write_text((linux / "include/linux/lzo.h").read_text())
        units = [linux / "lib/lzo/lzo1x_compress_safe.c",
                 linux / "lib/lzo/lzo1x_decompress_safe.c"]
        for compiler in ("gcc", "clang"):
            for name, modified, mutant in [("baseline",source,False)] + [
                    (name, source.replace(before, after, 1),True)
                    for name, before, after in MUTANTS]:
                modified_path = scratch / f"{compiler}-{name}.c"
                executable = scratch / f"{compiler}-{name}"
                modified_path.write_text(modified)
                common_flags = [compiler, "-std=gnu11", "-O1", "-g", "-Wall",
                                "-Wextra", "-Werror", "-fsanitize=address,undefined",
                                "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                                "-I", str(scratch), "-I", str(ROOT / "src/kernel")]
                # Pristine upstream C uses native warnings only. Actual swapz
                # and owned fixture C retain the full strict project flags.
                components = (
                    ("host-profile", modified_path, ("-Wconversion", "-Wshadow")),
                    ("actual-product-codec", PRODUCT, ("-Wconversion", "-Wshadow")),
                    ("original-lzo-compressor", units[0], ()),
                    ("original-lzo-decompressor", units[1], ()),
                )
                objects = []
                for component, path, extra_warnings in components:
                    object_path = scratch / f"{compiler}-{name}-{component}.o"
                    checked([*common_flags, *extra_warnings, "-c", str(path),
                             "-o", str(object_path)],
                            f"{compiler}/{name}/compile/{component}")
                    objects.append(str(object_path))
                checked([compiler, *objects, "-fsanitize=address,undefined",
                         "-lcrypto", "-o", str(executable)],
                        f"{compiler}/{name}/link")
                output = checked([str(executable)], f"{compiler}/{name}/execute", mutant)
                if not mutant:
                    if "ROUND056_PINNED_ORIGINAL_LZO1X_HOST_PASS" not in output:
                        raise AssertionError("ROUND056_DECODER_FIRST_ERROR missing executed C marker")
                    print(f"ROUND056_ORIGINAL_LZO_BASELINE compiler={compiler} {output}", flush=True)
                else:
                    print(f"ROUND056_ORIGINAL_LZO_MUTANT_SEMANTIC compiler={compiler} name={name}", flush=True)
    print("ROUND056_ORIGINAL_LZO_C_EXECUTED_PASS original_pin=" + PIN +
          " baselines=2 genuine_source_mutants=8 source_authenticated=0", flush=True)

if __name__ == "__main__":
    main()
