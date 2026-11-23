#!/usr/bin/env python3
"""Round080 Agent7: pristine Linux LZO1X -> actual dormant import decoder HOST only.

Run with a pristine sparse original Linux checkout separate from swapz.
Mutants alter the *actual product guard source* in ephemeral staged copies;
every one is separately compiled, linked and run with GCC and Clang ASan/UBSan.
A compile failure or sanitizer abort never qualifies as a semantic kill.
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

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/runtime/native/fixtures/round080-original-lzo1x-independent-decoder.c"
PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
ORIGINAL = {
    "mm/zswap.c": "ae19e301fced7e357a4c7587dfdd6abb890b9163",
    "crypto/lzo.c": "d43242b24b4e831e7e0d26f38d2f263877d5748e",
    "include/linux/lzo.h": "4d30e3624acd237290dbfeaefdb9c710e4f85f56",
    "lib/lzo/lzo1x_compress.c": "01586af2347f5e2f8c8528b94e02622fc8b262c8",
    "lib/lzo/lzo1x_compress_safe.c": "371c9f849492814afed88a443acb2262dcf35dfe",
    "lib/lzo/lzo1x_decompress_safe.c": "318abb82c63d2c27c0d5497b7cf4e21d87d13154",
    "lib/lzo/lzodefs.h": "b60851fcf6ce54b57e87d04e917deaa2b6cf62cc",
}
PRODUCT = {
    "src/kernel/zswap-import-codec.h": "0d888fe4c74115ab2388f1df1dc0b86ae4b9b6c6",
    "src/kernel/zswap-import-decoder-owner.c": "8e0c8f4d2085af7f2e17df412f3a1af654063571",
    "src/kernel/zswap-import-decoder-owner.h": "e1b4b903567070e2307f7d05f8e48c14e0bb3768",
    "src/kernel/codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    "src/kernel/codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "src/kernel/zswap-direct-handoff.h": "864abf9a12071b98f5c157a44f4ed0c04d4a594c",
    "src/kernel/authority.h": "3bb5bab5a5bdb2aa087f5793fc8b5e90d6636031",
}

# Test fixture performs every negative unmutated. Mutants change the actual
# product source guard and MUST die at the *named* matching C runtime check.
# Each anchor is unique in the one targeted product file, not a Python oracle.
MUTANTS = (
    ("representation", "zswap-import-codec.h",
     "record->representation != SWAPZ_ZSWAP_IMPORT_REPRESENTATION", "0"),
    ("positive_dormant_product_lzo_decode", "zswap-import-codec.h",
     "original_lzo1x = record->codec == SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC;",
     "original_lzo1x = 0;"),
    ("version", "zswap-import-codec.h",
     "record->version != SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION", "0"),
    ("dictionary", "zswap-import-codec.h",
     "record->dictionary_id != 0U", "0"),
    ("not_original_stored_eviction", "zswap-import-codec.h",
     "!record->stored_eviction", "0"),
    ("no_owned_copy", "zswap-import-codec.h",
     "!record->immutable_owned_copy", "0"),
    ("decoded_4095", "zswap-import-codec.h",
     "record->decoded_length != SWAPZ_BLOCK_BYTES", "0"),
    ("3569_rejected_not_truncated", "zswap-import-codec.h",
     "record->compressed_length > SWAPZ_MAX_COMPRESSED", "0"),
    ("capacity_short", "zswap-import-codec.h",
     "compressed_capacity < record->compressed_length", "0"),
    ("stale_generation", "zswap-import-codec.h",
     "authority->generation != record->generation", "0"),
    ("not_exactly_once_upper_write_ack", "zswap-import-codec.h",
     "authority->upper_write_ack_count != 1U", "0"),
    ("partial_lower_read", "zswap-import-codec.h",
     "authority->actual_lower_read_bytes != record->compressed_length", "0"),
    ("lower_io_error", "zswap-import-codec.h",
     "if (authority->lower_read_error)", "if (0 && authority->lower_read_error)"),
    ("corrupt_compressed_crc", "zswap-import-codec.h",
     "if (swapz_crc32c_bytes(compressed_bytes, record->compressed_length) !=",
     "if (0 && swapz_crc32c_bytes(compressed_bytes, record->compressed_length) !="),
    ("corrupt_original_sha", "zswap-import-codec.h",
     "if (digest_difference || (independent_original_page &&",
     "if (0 && digest_difference || (independent_original_page &&"),
    ("overlap_scratch_output", "zswap-import-codec.h",
     "swapz_zswap_import_ranges_overlap(scratch, SWAPZ_BLOCK_BYTES,\n\t\t\toutput, SWAPZ_BLOCK_BYTES)",
     "0"),
    ("retired_decoder_refuses_new_reader", "zswap-import-decoder-owner.c",
     "if (owner->closing)", "if (0 && owner->closing)"),
    ("duplicate_put", "zswap-import-decoder-owner.c",
     "return -EALREADY;", "return 0;"),
)

# Only kernel dependencies required by exact Linux lib/lzo C objects. These
# are ABI shims for host compilation, not a native Linux kernel execution.
SHIM = {
    "linux/kernel.h": r"""#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#if __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "Original Linux LZO1X host shim supports only little endian"
#endif
#ifndef __LITTLE_ENDIAN
#define __LITTLE_ENDIAN 1
#endif
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
    "linux/unaligned.h": r"""#pragma once
#include <stdint.h>
#include <string.h>
#define get_unaligned(pointer) ({ __typeof__(*(pointer) + 0) value; memcpy(&value, (const void *)(pointer), sizeof(value)); value; })
#define put_unaligned(value,pointer) do { __typeof__(*(pointer)) value_copy = (value); memcpy((void *)(pointer), &value_copy, sizeof(value_copy)); } while (0)
static inline uint16_t get_unaligned_le16(const void *pointer) { uint16_t value; memcpy(&value,pointer,sizeof(value)); return value; }
static inline uint32_t get_unaligned_le32(const void *pointer) { uint32_t value; memcpy(&value,pointer,sizeof(value)); return value; }
static inline void put_unaligned_le32(uint32_t value, void *pointer) { memcpy(pointer,&value,sizeof(value)); }
""",
    "linux/module.h": r"""#pragma once
#define EXPORT_SYMBOL_GPL(...)
#define MODULE_LICENSE(...)
#define MODULE_DESCRIPTION(...)
""",
}
SUCCESS = re.compile(
    r"PASS round080-agent7 source_original_lzo1x_to_product_decode=1 "
    r"retained_lease=1 original_4096=1 AUTH=0 PHASE_A=BLOCKED checks=(\d+)\n\Z"
)
FIRST_ERROR = re.compile(r"FIRST_ERROR check=([a-z0-9_]+) line=\d+ observed=-?\d+\n\Z")
SANITIZER = ("AddressSanitizer", "LeakSanitizer", "UndefinedBehaviorSanitizer",
             "runtime error:", "SUMMARY: UndefinedBehaviorSanitizer")


def require(value: bool, message: str) -> None:
    if not value:
        raise RuntimeError(message)


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def run_command(command: list[str], label: str, *, stdin: str | None = None,
                timeout: int = 120) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command, input=stdin, text=True, capture_output=True, timeout=timeout,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
             "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"},
        check=False,
    )
    return result


def first_diagnostic(result: subprocess.CompletedProcess[str]) -> str:
    lines = (result.stderr or result.stdout or "no diagnostics").splitlines()
    return next((line[:330] for line in lines if "error:" in line), lines[0][:330])


def checked(command: list[str], label: str) -> str:
    result = run_command(command, label)
    require(result.returncode == 0 and not result.stderr,
            f"{label} exit={result.returncode}: {first_diagnostic(result)}")
    return result.stdout.strip()


def compiler_standard(compiler: str) -> str:
    for standard in ("-std=c23", "-std=c2x"):
        result = run_command([compiler, standard, "-x", "c", "-fsyntax-only", "-"],
                             "std", stdin="int main(void) { return 0; }\n")
        if result.returncode == 0:
            return standard
    raise RuntimeError(f"{compiler}: C23/c2x unsupported")


def verify_source(linux: Path) -> None:
    require(checked(["git", "-C", str(linux), "rev-parse", "HEAD"], "original pin") == PIN,
            "wrong pristine original Linux commit")
    require(not checked(["git", "-C", str(linux), "status", "--porcelain",
                         "--untracked-files=all"], "original status"),
            "original Linux checkout modified")
    for relative, expected in ORIGINAL.items():
        path = linux / relative
        require(path.is_file() and git_blob(path.read_bytes()) == expected,
                f"original whole Git blob SHA drift {relative} expected={expected}")
    for relative, expected in PRODUCT.items():
        path = ROOT / relative
        require(path.is_file() and git_blob(path.read_bytes()) == expected,
                f"product whole Git blob SHA drift {relative} expected={expected}")
    original_zswap = (linux / "mm/zswap.c").read_text(encoding="utf-8")
    original_crypto = (linux / "crypto/lzo.c").read_text(encoding="utf-8")
    actual_decoder = (ROOT / "src/kernel/zswap-import-codec.h").read_text()
    require("zswap_writeback_entry(" in original_zswap and
            "lzo1x_1_compress_safe(" in original_crypto and
            "lzo1x_decompress_safe(" in original_crypto and
            'cra_driver_name = "lzo-scomp"' in original_crypto and
            "#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U" in actual_decoder and
            "lzo1x_decompress_safe(compressed_bytes," in actual_decoder and
            "result != LZO_E_OK" in actual_decoder,
            "original zswap LZO API / dormant decoder source anchor drift")
    fixture = FIXTURE.read_text(encoding="utf-8")
    require("SOURCE_MAPPED_AUTHENTICATED 0" in fixture and
            "DIRECT_COMPRESSED_HANDOFF 0" in fixture and
            "FORCED_RAW_BYPASS 0" in fixture,
            "fixture authority or activation gate modified")
    require(len(MUTANTS) >= 12, "too few source C semantic mutants")
    for name, file, before, after in MUTANTS:
        source = (ROOT / "src/kernel" / file).read_text()
        require(source.count(before) == 1 and before != after,
                f"nonunique/vacuous product source mutant {name}")


def compile_object(compiler: str, standard: str, source: Path, target: Path,
                   includes: list[str], *, original: bool = False) -> None:
    flags = [
        standard, "-O1", "-g", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
        "-fno-omit-frame-pointer", "-fno-pie",
    ]
    if not original:
        flags.extend(["-Wpedantic", "-Wconversion", "-Wshadow",
                      "-DSWAPZ_ZSWAP_IMPORT_HOST_TEST=1",
                      "-DSWAPZ_ZSWAP_IMPORT_ORIGINAL_LZO_HOST_TEST=1",
                      "-DSWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST=1",
                      "-D_POSIX_C_SOURCE=200809L", "-include", "stddef.h"])
    checked([compiler, *flags, *includes, "-c", str(source), "-o", str(target)],
            f"{Path(compiler).name} compile {source.name}")


def compile_and_execute(compiler: str, standard: str, linux: Path,
                        workspace: Path) -> dict[str, object]:
    name = Path(compiler).name
    include_root = workspace / "shim"
    include_root.mkdir()
    for relative, contents in SHIM.items():
        path = include_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    (include_root / "linux/lzo.h").write_bytes(
        (linux / "include/linux/lzo.h").read_bytes())
    original_objects = []
    for part in ("lzo1x_compress_safe.c", "lzo1x_decompress_safe.c"):
        source = linux / "lib/lzo" / part
        output = workspace / (part + ".o")
        compile_object(compiler, "-std=gnu11", source, output,
                       ["-I", str(include_root)], original=True)
        original_objects.append(output)

    names: list[str] = []
    baseline_assertions = 0
    for index, mutation in enumerate((None, *MUTANTS)):
        case_directory = workspace / f"case-{index:02d}"
        case_directory.mkdir()
        product_paths = {}
        for relative in PRODUCT:
            source = ROOT / relative
            target = case_directory / source.name
            target.write_bytes(source.read_bytes())
            product_paths[source.name] = target
        if mutation is not None:
            mutant_name, filename, before, after = mutation
            target = product_paths[filename]
            target.write_text(target.read_text().replace(before, after, 1))
        includes = ["-I", str(include_root), "-I", str(case_directory)]
        executable = case_directory / "original-product-lzo"
        fixture_object = case_directory / "fixture.o"
        owner_object = case_directory / "owner.o"
        codec_object = case_directory / "codec.o"
        compile_object(compiler, standard, FIXTURE, fixture_object, includes)
        compile_object(compiler, standard, product_paths["zswap-import-decoder-owner.c"],
                       owner_object, includes)
        compile_object(compiler, standard, product_paths["codec.c"],
                       codec_object, includes)
        checked([compiler, "-fsanitize=address,undefined", "-fno-pie", "-no-pie",
                 str(fixture_object), str(owner_object), str(codec_object),
                 *(str(path) for path in original_objects),
                 "-pthread", "-llz4", "-lcrypto", "-o", str(executable)],
                f"{name} link case-{index:02d}")
        execution = run_command([str(executable)], f"{name} case-{index:02d}", timeout=30)
        sanitizer = any(token in execution.stderr for token in SANITIZER)
        if mutation is None:
            match = SUCCESS.fullmatch(execution.stdout)
            require(execution.returncode == 0 and not execution.stderr and
                    not sanitizer and match is not None,
                    f"{name} baseline exit={execution.returncode}: "
                    f"{first_diagnostic(execution)}")
            baseline_assertions = int(match.group(1))
            require(baseline_assertions >= 30, "baseline insufficient directed assertions")
            print(f"PASS {name} {standard} original-LZO+product-dormant"
                  f" ASan+UBSan baseline directed_checks={baseline_assertions}", flush=True)
        else:
            match = FIRST_ERROR.fullmatch(execution.stderr)
            require(execution.returncode == 1 and not execution.stdout and
                    not sanitizer and match is not None and
                    match.group(1) == mutant_name,
                    f"{name} SEMANTIC_MUTANT_SURVIVED_OR_WRONG_FIRST_ERROR "
                    f"{mutant_name} exit={execution.returncode}: "
                    f"{first_diagnostic(execution)}")
            names.append(mutant_name)
    print(f"PASS {name} independently_compiled_executed_semantic_mutants="
          f"{len(names)}/{len(MUTANTS)}", flush=True)
    return {
        "standard": standard[5:],
        "sanitizers": ["address", "undefined"],
        "real_original_compatible_baseline": "PASS",
        "actual_dormant_product_decode": "PASS",
        "directed_assertions": baseline_assertions,
        "mutants_compiled": len(names),
        "mutants_executed": len(names),
        "semantic_mutants_killed": len(names),
        "mutants": names,
    }


def verify(linux: Path) -> dict[str, object]:
    verify_source(linux)
    results: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="swapz-round080-original-lzo1x-") as temporary:
        for compiler_name in ("gcc", "clang"):
            compiler = shutil.which(compiler_name)
            require(compiler is not None, f"missing compiler {compiler_name}")
            workspace = Path(temporary) / compiler_name
            workspace.mkdir()
            results[compiler_name] = compile_and_execute(
                compiler, compiler_standard(compiler), linux, workspace)
    return {
        "status": "PASS_HOST_ONLY",
        "original_pin": PIN,
        "original_whole_blob_sha": ORIGINAL,
        "product_whole_blob_sha": PRODUCT,
        "compilers": results,
        "semantic_mutants_compiled_and_executed_total": 2 * len(MUTANTS),
        "original_lzo1x_positive": "PASS_SOURCE_LINKED_PRODUCT_DORMANT",
        "original_decoder_owner_retained_through_old_reader": True,
        "original_linux_native": "NOT_RUN",
        "original_live_stored_slot_authenticated": False,
        "host_shim_scope": "source Linux lib/lzo C objects with minimal ABI headers, not a kernel build",
        "lower_io_real": False,
        "upper_ack_real": False,
        "source_mapped_authenticated": 0,
        "phase_a": "BLOCKED",
        "direct_compressed_handoff": False,
        "forced_raw_bypass": False,
        "import_active": False,
        "ordinary_raw_4096": "FULL_ORIGINAL_UNCOMPRESSED_4096",
        "current_dormant_original_lzo_max": 3568,
        "original_lzo_3569_through_4095": "REJECT_NO_TRUNCATION",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", type=Path, required=True)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--ktap", type=Path)
    arguments = parser.parse_args()
    try:
        result = verify(arguments.linux_root.resolve())
        if arguments.json:
            arguments.json.parent.mkdir(parents=True, exist_ok=True)
            arguments.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        if arguments.ktap:
            arguments.ktap.parent.mkdir(parents=True, exist_ok=True)
            arguments.ktap.write_text(
                "KTAP version 1\n1..2\n"
                "ok 1 - GCC exact original LZO1X to dormant product host decoder\n"
                "ok 2 - Clang exact original LZO1X to dormant product host decoder\n")
        print(f"PASS_HOST_ONLY round080-agent7 original LZO1X decoded by dormant "
              f"product with retained lease GCC={len(MUTANTS)} "
              f"Clang={len(MUTANTS)} independent compiled/executed C semantic mutants "
              "AUTH=0 PHASE_A=BLOCKED", flush=True)
        return 0
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"FIRST_ERROR round080-agent7 {str(error)[:600]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
