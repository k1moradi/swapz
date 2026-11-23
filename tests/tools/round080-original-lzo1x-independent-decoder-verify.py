#!/usr/bin/env python3
"""Round080 Agent7: pinned original Linux LZO1X -> dormant product host lease.

No kernel boot, real selected STORED source authentication, physical lower
durability or upper completion is represented by this rootless host test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round080-original-lzo1x-independent-decoder.c"
DECODER_OWNER = ROOT / "src/kernel/zswap-import-decoder-owner.c"
PRODUCT_CODEC = ROOT / "src/kernel/codec.c"
LINUX_BLOBS = {
    "include/linux/lzo.h": "4d30e3624acd237290dbfeaefdb9c710e4f85f56",
    "lib/lzo/lzo1x_compress.c": "01586af2347f5e2f8c8528b94e02622fc8b262c8",
    "lib/lzo/lzo1x_decompress_safe.c": "318abb82c63d2c27c0d5497b7cf4e21d87d13154",
    "lib/lzo/lzodefs.h": "b60851fcf6ce54b57e87d04e917deaa2b6cf62cc",
    "mm/zswap.c": "ae19e301fced7e357a4c7587dfdd6abb890b9163",
}
PRODUCT_BLOBS = {
    "src/kernel/zswap-import-codec.h": "0d888fe4c74115ab2388f1df1dc0b86ae4b9b6c6",
    "src/kernel/zswap-import-decoder-owner.c": "8e0c8f4d2085af7f2e17df412f3a1af654063571",
    "src/kernel/zswap-import-decoder-owner.h": "e1b4b903567070e2307f7d05f8e48c14e0bb3768",
    "src/kernel/zswap-direct-handoff.h": "864abf9a12071b98f5c157a44f4ed0c04d4a594c",
    "src/kernel/codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "src/kernel/codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    "src/kernel/authority.h": "3bb5bab5a5bdb2aa087f5793fc8b5e90d6636031",
}
MUTANTS = (
    ("original-codec-namespace",
     "if (!source->genuine_original_namespace)",
     "if (false && !source->genuine_original_namespace)"),
    ("selected-source-host-witness",
     "if (!source->original_selected_source_verified)",
     "if (false && !source->original_selected_source_verified)"),
    ("preerase-owned-copy",
     "if (!source->immutable_owned_copy)",
     "if (false && !source->immutable_owned_copy)"),
    ("natural-original-eviction",
     "if (!source->original_eviction)",
     "if (false && !source->original_eviction)"),
    ("retained-original-decoder",
     "if (!source->decoder_is_retained)",
     "if (false && !source->decoder_is_retained)"),
    ("decoder-not-retired",
     "if (source->retired_original_decoder)",
     "if (false && source->retired_original_decoder)"),
    ("no-recompression",
     "if (!source->no_recompression)",
     "if (false && !source->no_recompression)"),
    ("no-secondary-reclaimer",
     "if (!source->no_secondary_reclaim)",
     "if (false && !source->no_secondary_reclaim)"),
    ("never-compressed-as-raw",
     "if (source->representation != ORIGINAL_COMPRESSED_LZO)",
     "if (false && source->representation != ORIGINAL_COMPRESSED_LZO)"),
    ("original-lzo-not-disk-or-direct-zstd",
     "if (source->original_codec != SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC)",
     "if (false && source->original_codec != SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC)"),
    ("original-lzo-version",
     "if (source->original_version != SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION)",
     "if (false && source->original_version != SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION)"),
    ("disk-shuffle-not-original-lzo",
     "if (source->swapz_disk_encoding != SWAPZ_ENCODING_INVALID)",
     "if (false && source->swapz_disk_encoding != SWAPZ_ENCODING_INVALID)"),
    ("genuine-original-logical-slot",
     "if (source->logical_page != record->logical_page)",
     "if (false && source->logical_page != record->logical_page)"),
    ("original-generation",
     "if (source->generation != record->generation)",
     "if (false && source->generation != record->generation)"),
    ("original-stored-identity",
     "if (source->stored_identity != record->stored_entry_identity)",
     "if (false && source->stored_identity != record->stored_entry_identity)"),
    ("original-store-generation",
     "if (source->store_generation != record->store_generation)",
     "if (false && source->store_generation != record->store_generation)"),
    ("gc-epoch",
     "if (source->gc_epoch != record->gc_epoch)",
     "if (false && source->gc_epoch != record->gc_epoch)"),
    ("compressed-length",
     "if (source->compressed_bytes != record->compressed_length)",
     "if (false && source->compressed_bytes != record->compressed_length)"),
    ("source-readable-capacity",
     "if (source->source_capacity < source->compressed_bytes)",
     "if (false && source->source_capacity < source->compressed_bytes)"),
    ("lower-complete-read",
     "if (source->lower_actual_bytes != source->compressed_bytes)",
     "if (false && source->lower_actual_bytes != source->compressed_bytes)"),
    ("independent-original-sha256",
     "if (memcmp(source->independent_sha256, record->original_sha256,\n               SHA256_DIGEST_LENGTH) != 0)",
     "if (false && memcmp(source->independent_sha256, record->original_sha256,\n               SHA256_DIGEST_LENGTH) != 0)"),
)
EXPECTED = re.compile(
    r"PASS round080-agent7 checks=([1-9][0-9]*) genuine_pinned_linux_LZO1X=1 "
    r"actual_product_decode_and_lease=1 original4096_sha=1 "
    r"RAW_4096=FULL_UNCOMPRESSED original_lzo_import2_not_direct_zstd2=1 "
    r"AUTH=0 PHASE_A=BLOCKED\n\Z"
)

# Host header shims used ONLY for compiling unchanged pinned Linux source.
# No original kernel source is changed, and no kernel headers are patched.
SHIMS = {
    "linux/kernel.h": r'''#ifndef ROUND080_ORIGINAL_HOST_KERNEL_H
#define ROUND080_ORIGINAL_HOST_KERNEL_H
#include <stddef.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
#define likely(value) __builtin_expect(!!(value), 1)
#define unlikely(value) __builtin_expect(!!(value), 0)
#define noinline __attribute__((noinline))
#define min(first, second) ((first) < (second) ? (first) : (second))
#define min_t(type, first, second) ((type)(first) < (type)(second) ? (type)(first) : (type)(second))
#define ALIGN(value, alignment) (((value) + (alignment) - 1U) & ~((alignment) - 1U))
#define IS_ALIGNED(value, alignment) (!((value) & ((alignment) - 1U)))
#define BUILD_BUG_ON(condition) _Static_assert(!(condition), "kernel compile-time invariant")
#endif
''',
    "linux/module.h": r'''#include <linux/kernel.h>
#define EXPORT_SYMBOL_GPL(symbol) _Static_assert(1, "host original exported symbol")
#define MODULE_LICENSE(value) _Static_assert(1, "host original module license")
#define MODULE_DESCRIPTION(value) _Static_assert(1, "host original module description")
''',
    "linux/unaligned.h": r'''#ifndef ROUND080_ORIGINAL_UNALIGNED_H
#define ROUND080_ORIGINAL_UNALIGNED_H
#include <linux/kernel.h>
static inline uint16_t get_unaligned_le16(const void *data)
{
    const unsigned char *bytes = data;
    return (uint16_t)((uint16_t)bytes[0] | ((uint16_t)bytes[1] << 8));
}
static inline uint32_t get_unaligned_le32(const void *data)
{
    const unsigned char *bytes = data;
    return (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8) |
           ((uint32_t)bytes[2] << 16) | ((uint32_t)bytes[3] << 24);
}
static inline void put_unaligned_le32(uint32_t value, void *data)
{
    unsigned char *bytes = data;
    for (unsigned int index = 0; index < 4U; ++index)
        bytes[index] = (unsigned char)((value >> (8U * index)) & 0xffU);
}
static inline uint32_t host_get_unaligned_u32(const void *data)
{
    uint32_t result;
    memcpy(&result, data, sizeof(result));
    return result;
}
static inline void host_put_unaligned_u32(uint32_t value, void *data)
{
    memcpy(data, &value, sizeof(value));
}
#define get_unaligned(pointer) host_get_unaligned_u32(pointer)
#define put_unaligned(value, pointer) host_put_unaligned_u32((uint32_t)(value), (pointer))
#endif
''',
}


def require(value: bool, error: str) -> None:
    if not value:
        raise RuntimeError(error)


def git_blob_sha(content: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(content)).encode("ascii")
                        + b"\0" + content).hexdigest()


def prepare_sources(workspace: Path) -> Path:
    original = workspace / "pinned-linux"
    for path, sha in LINUX_BLOBS.items():
        url = f"https://raw.githubusercontent.com/torvalds/linux/{PIN}/{path}"
        with urlopen(url, timeout=30) as response:
            contents = response.read()
        require(git_blob_sha(contents) == sha,
                f"original Linux SHA mismatch {path}: expected {sha}")
        target = original / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
    for path, sha in PRODUCT_BLOBS.items():
        contents = (ROOT / path).read_bytes()
        require(git_blob_sha(contents) == sha,
                f"product C/header changed {path}: expected {sha}")
    original_zswap = (original / "mm/zswap.c").read_text(encoding="utf-8")
    require("zswap_writeback_entry(" in original_zswap and
            "entry->length" in original_zswap,
            "pinned original zswap writeback source contract changed")
    for path, contents in SHIMS.items():
        target = workspace / "host-shim" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
    return original


def execute(command: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, input=input_text, capture_output=True, text=True, timeout=120,
        check=False, env={**os.environ,
                          "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
                          "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"},
    )


def diagnostic(process: subprocess.CompletedProcess[str]) -> str:
    lines = (process.stderr or process.stdout).splitlines()
    for line in lines:
        if "error:" in line:
            return line.split("error:", 1)[1].strip()[:260]
    return lines[0][:260] if lines else "no compiler/runtime diagnostic"


def standard(compiler: str) -> str:
    for mode in ("-std=c23", "-std=c2x"):
        process = execute([compiler, mode, "-x", "c", "-fsyntax-only", "-"],
                          input_text="int main(void) { return 0; }\n")
        if process.returncode == 0:
            return mode
    raise RuntimeError(f"{compiler}: missing strict C23 mode")


def compile_original_objects(compiler: str, mode: str, workspace: Path,
                             original: Path, tag: str) -> list[Path]:
    # Pinned kernel .c is compiled without altering its source or silently
    # suppressing warnings. Original kernel LZO is NOT authored with host
    # -Wconversion and -Wshadow; those stricter checks cover product/fixture.
    # Compiling unchanged original .c once per compiler avoids expensive
    # recompilation for every independent mutated host fixture.
    common = [
        compiler, mode, "-O1", "-g", "-Wall", "-Wpedantic",
        "-Werror", "-fsanitize=address,undefined",
        "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
        "-fno-pie", "-no-pie", "-DSTATIC=1",
        "-I", str(workspace / "host-shim"), "-I", str(original / "include"),
        "-include", "stddef.h", "-include", "stdint.h", "-include", "string.h",
    ]
    originals = [
        original / "lib/lzo/lzo1x_compress.c",
        original / "lib/lzo/lzo1x_decompress_safe.c",
    ]
    objects: list[Path] = []
    for index, source in enumerate(originals):
        output = workspace / f"{tag}-pinned-{index}.o"
        process = execute([*common, "-c", str(source), "-o", str(output)])
        require(process.returncode == 0,
                f"{tag}: original pinned kernel compile {source.name}: "
                f"{diagnostic(process)}")
        objects.append(output)
    return objects


def compile_product_objects(compiler: str, mode: str, workspace: Path,
                            original: Path, tag: str) -> list[Path]:
    product_objects: list[Path] = []
    for index, source in enumerate((DECODER_OWNER, PRODUCT_CODEC)):
        output = workspace / f"{tag}-product-{index}.o"
        process = execute([
            compiler, mode, "-O1", "-g", "-Wall", "-Wextra", "-Wpedantic",
            "-Wconversion", "-Wshadow", "-Werror",
            "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
            "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
            "-I", str(workspace / "host-shim"),
            "-I", str(original / "include"), "-include", "stddef.h",
            "-DSWAPZ_ZSWAP_IMPORT_HOST_TEST=1",
            "-DSWAPZ_ZSWAP_IMPORT_ORIGINAL_LZO_HOST_TEST=1",
            "-DSWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST=1",
            "-c", str(source), "-o", str(output),
        ])
        require(process.returncode == 0,
                f"{tag}: product source compile {source.name}: "
                f"{diagnostic(process)}")
        product_objects.append(output)
    return product_objects


def compile_one(compiler: str, mode: str, workspace: Path, original: Path,
                source: Path, executable: Path, shared_objects: list[Path]) -> None:
    fixture_object = workspace / (executable.name + "-mutable.o")
    compile_process = execute([
        compiler, mode, "-O1", "-g", "-Wall", "-Wextra", "-Wpedantic",
        "-Wconversion", "-Wshadow", "-Werror", "-fsanitize=address,undefined",
        "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
        "-fno-pie", "-no-pie",
        "-I", str(workspace / "host-shim"), "-I", str(original / "include"),
        "-I", str(FIXTURE.parent), "-include", "stddef.h",
        "-c", str(source), "-o", str(fixture_object),
    ])
    require(compile_process.returncode == 0,
            f"{compiler}: fixture compile {source.name}: "
            f"{diagnostic(compile_process)}")
    link_process = execute([
        compiler, "-fsanitize=address,undefined", "-fno-pie", "-no-pie",
        str(fixture_object), *(str(item) for item in shared_objects),
        "-pthread", "-llz4", "-lcrypto", "-o", str(executable),
    ])
    require(link_process.returncode == 0,
            f"{compiler}: source-linked fixture link {source.name}: "
            f"{diagnostic(link_process)}")


def run_suite() -> dict[str, object]:
    fixture = FIXTURE.read_text(encoding="utf-8")
    for gate in ("#define SOURCE_MAPPED_AUTHENTICATED 0",
                 "#define DIRECT_COMPRESSED_HANDOFF 0",
                 "#define FORCED_RAW_BYPASS 0"):
        require(gate in fixture, f"test gate removed {gate}")
    compilers: dict[str, dict[str, object]] = {}
    outputs: list[str] = []
    with tempfile.TemporaryDirectory(prefix="round080-agent7-") as folder:
        workspace = Path(folder)
        original = prepare_sources(workspace)
        for compiler_name in ("gcc", "clang"):
            compiler = shutil.which(compiler_name)
            require(compiler is not None, f"missing required {compiler_name}")
            mode = standard(compiler)
            executable = workspace / f"test-{compiler_name}"
            originals = compile_original_objects(
                compiler, mode, workspace, original, compiler_name)
            products = compile_product_objects(
                compiler, mode, workspace, original, compiler_name)
            shared_objects = [*originals, *products]
            compile_one(compiler, mode, workspace, original, FIXTURE,
                        executable, shared_objects)
            baseline = execute([str(executable)])
            match = EXPECTED.fullmatch(baseline.stdout)
            require(baseline.returncode == 0 and baseline.stderr == "" and
                    match is not None and int(match.group(1)) >= 110,
                    f"{compiler_name}: baseline exit={baseline.returncode}: "
                    f"{diagnostic(baseline)}")
            outputs.append(baseline.stdout)
            print(f"PASS {compiler_name} {mode} pinned original "
                  f"LZO compressor/decompressor+actual product owner/codec "
                  f"ASan+UBSan: {baseline.stdout.strip()}", flush=True)
            for index, (name, before, after) in enumerate(MUTANTS):
                require(fixture.count(before) == 1,
                        f"{compiler_name}: mutant {name} missing/nonunique anchor")
                mutant = workspace / f"mutant-{compiler_name}-{index}.c"
                mutant.write_text(fixture.replace(before, after, 1),
                                  encoding="utf-8")
                compile_one(compiler, mode, workspace, original, mutant,
                            executable, shared_objects)
                rejected = execute([str(executable)])
                require(rejected.returncode == 1 and rejected.stdout == "" and
                        re.fullmatch(r"FIRST_ERROR line=\d+ check=[^\n]+\n",
                                     rejected.stderr) is not None,
                        f"{compiler_name}: SEMANTIC_MUTANT_SURVIVED {name}: "
                        f"exit={rejected.returncode} {diagnostic(rejected)}")
            compilers[compiler_name] = {
                "mode": mode, "assertions": int(match.group(1)),
                "mutants_compiled_executed": len(MUTANTS),
                "mutants_semantically_killed": len(MUTANTS),
                "sanitizers": ["address", "undefined"]
            }
            print(f"PASS {compiler_name} compiled_executed_semantic_C_mutants="
                  f"{len(MUTANTS)}", flush=True)
    require(outputs[0] == outputs[1],
            "GCC/Clang original source result signature mismatch")
    return {
        "result": "PASS", "kind": "pinned-original-lzo1x-positive-product-host",
        "linux_pin": PIN, "linux_source_git_blobs": LINUX_BLOBS,
        "product_git_blobs": PRODUCT_BLOBS,
        "compilers": compilers,
        "mutants_compiled_executed": len(MUTANTS) * 2,
        "mutants_killed_by_runtime_assertion": len(MUTANTS) * 2,
        "actual_original_linux_lzo_compressor_linked": True,
        "actual_original_linux_lzo_decompressor_linked": True,
        "real_product_decoder_owner_and_codec_linked": True,
        "original_native_kunit_json_ktap": "NOT_RUN",
        "host_ktap_only": "2_of_2",
        "source_mapped_authenticated": False, "phase_a": "BLOCKED",
        "direct_compressed_handoff": False, "forced_raw_bypass": False,
        "import_active": False, "real_lower_io": False, "real_fua": False,
        "real_upper_ack": False, "secondary_reclaimer": False,
        "recompression": False,
        "ordinary_raw4096": "COMPLETE_ORIGINAL_UNCOMPRESSED_4096",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--ktap", type=Path)
    args = parser.parse_args()
    try:
        result = run_suite()
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(result, indent=2, sort_keys=True)
                                 + "\n", encoding="utf-8")
        if args.ktap:
            args.ktap.parent.mkdir(parents=True, exist_ok=True)
            args.ktap.write_text(
                "KTAP version 1\n1..2\n"
                "ok 1 - GCC pinned original LZO1X actual product host decode\n"
                "ok 2 - Clang pinned original LZO1X actual product host decode\n",
                encoding="utf-8")
        print("PASS round080-agent7 HOST_ONLY original LZO1X product "
              f"mutants={result['mutants_compiled_executed']} "
              "AUTH=0 PHASE_A=BLOCKED", flush=True)
        return 0
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"FIRST_ERROR round080-agent7 {str(error)[:320]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
