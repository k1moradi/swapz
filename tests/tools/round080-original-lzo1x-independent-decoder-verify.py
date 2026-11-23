#!/usr/bin/env python3
"""Round080 Agent7 rootless exact original Linux LZO1X host decoder regression.

This harness compiles the pinned Linux LZO1X decompressor C source as a
host object using only a minimal test-only Linux include shim. It links the
unchanged real product import decoder/decoder-owner and codec C, with
liblzo2's ABI-compatible LZO1X_1 compressor supplying actual compressed bytes.
All authority/lease/DM values here are HOST-asserted, NOT kernel-authenticated.
Each mutant must separately compile and execute with semantic FIRST_ERROR.
"""
from __future__ import annotations

import argparse
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
PRODUCT_OWNER = ROOT / "src/kernel/zswap-import-decoder-owner.c"
PRODUCT_CODEC = ROOT / "src/kernel/codec.c"
PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
PINNED_ORIGINAL_BLOBS = {
    "include/linux/lzo.h": "4d30e3624acd237290dbfeaefdb9c710e4f85f56",
    "lib/lzo/lzo1x_decompress_safe.c": "318abb82c63d2c27c0d5497b7cf4e21d87d13154",
    "lib/lzo/lzodefs.h": "b60851fcf6ce54b57e87d04e917deaa2b6cf62cc",
    "mm/zswap.c": "ae19e301fced7e357a4c7587dfdd6abb890b9163",
}
PRODUCT_BLOBS = {
    "src/kernel/zswap-import-codec.h": "0d888fe4c74115ab2388f1df1dc0b86ae4b9b6c6",
    "src/kernel/zswap-import-decoder-owner.c": "8e0c8f4d2085af7f2e17df412f3a1af654063571",
    "src/kernel/zswap-import-decoder-owner.h": "e1b4b903567070e2307f7d05f8e48c14e0bb3768",
    "src/kernel/zswap-direct-handoff.h": "864abf9a12071b98f5c157a44f4ed0c04d4a594c",
}
ANCHORS = {
    "src/kernel/zswap-import-codec.h": (
        "#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U",
        "#define SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC 2U",
        "#define SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION 1U",
        "defined(SWAPZ_ZSWAP_IMPORT_ORIGINAL_LZO_HOST_TEST)",
        "lzo1x_decompress_safe(compressed_bytes,",
        "result != LZO_E_OK",
        "original_decoded_bytes != SWAPZ_BLOCK_BYTES",
    ),
    "src/kernel/zswap-import-decoder-owner.c": (
        "record->codec != lease->codec",
        "record->version != lease->version",
        "swapz_zswap_import_decode(record, authority,",
        "int swapz_zswap_import_decoder_owner_close_and_drain(",
    ),
    "src/kernel/zswap-direct-handoff.h": (
        "SWAPZ_DIRECT_ZSWAP_ZSTD = 2,",
        "#define SWAPZ_DIRECT_HANDOFF_PRODUCTION_ENABLED 0U",
    ),
    "src/kernel/codec.h": (
        "#define SWAPZ_BLOCK_BYTES 4096U",
        "#define SWAPZ_MAX_COMPRESSED 3568U",
        "#define SWAPZ_CODEC_METADATA_ON_MEDIA 0U",
    ),
    "src/kernel/authority.h": (
        "_Static_assert(sizeof(struct swapz_map) == 20",
        "#define SWAPZ_LINUX_SWAP_HEADER_BLOCKS 1U",
    ),
}
MUTANTS = (
    ("untagged-direct-zstd2",
     "if (source->codec_namespace != SOURCE_ORIGINAL_LZO1X)",
     "if (false && source->codec_namespace != SOURCE_ORIGINAL_LZO1X)"),
    ("compressed-original-representation",
     "if (source->representation != HOST_ORIGINAL_LZO1X_COMPRESSED)",
     "if (false && source->representation != HOST_ORIGINAL_LZO1X_COMPRESSED)"),
    ("cross-abi-direct-tag2",
     "if (source->direct_handoff_codec != SWAPZ_DIRECT_CODEC_UNKNOWN)",
     "if (false && source->direct_handoff_codec != SWAPZ_DIRECT_CODEC_UNKNOWN)"),
    ("independent-selected-source-proof",
     "if (!source->host_selected_source_assertion)",
     "if (false && !source->host_selected_source_assertion)"),
    ("current-selected-dm",
     "if (!source->selected_dm_witness)",
     "if (false && !source->selected_dm_witness)"),
    ("owned-original-compressed-copy",
     "if (!source->owns_original_bytes)",
     "if (false && !source->owns_original_bytes)"),
    ("retained-original-decoder",
     "if (!source->original_decoder_retained)",
     "if (false && !source->original_decoder_retained)"),
    ("original-unframed-codec",
     "if (!source->original_stream_is_unframed)",
     "if (false && !source->original_stream_is_unframed)"),
    ("linux-mm-natural-eviction",
     "if (!source->natural_eviction_only)",
     "if (false && !source->natural_eviction_only)"),
    ("no-original-compressed-raw-disguise",
     "if (source->original_entry_is_uncompressed)",
     "if (false && source->original_entry_is_uncompressed)"),
    ("valid-current-source-lease",
     "if (!source->source_lease_current)",
     "if (false && !source->source_lease_current)"),
    ("no-extra-recompression",
     "if (source->requests_recompression)",
     "if (false && source->requests_recompression)"),
    ("no-secondary-pressure-shrinker",
     "if (source->requests_second_reclaimer)",
     "if (false && source->requests_second_reclaimer)"),
    ("original-codec2-not-raw-lz4",
     "if (source->record.codec != SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC)",
     "if (false && source->record.codec != SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC)"),
    ("original-codec-version",
     "if (source->record.version != SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION)",
     "if (false && source->record.version != SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION)"),
    ("original-slot",
     "if (source->selected_logical_page != source->record.logical_page)",
     "if (false && source->selected_logical_page != source->record.logical_page)"),
    ("selected-generation",
     "if (source->selected_generation != source->record.generation)",
     "if (false && source->selected_generation != source->record.generation)"),
    ("original-record-identity",
     "if (source->selected_record_identity != source->record.stored_entry_identity)",
     "if (false && source->selected_record_identity != source->record.stored_entry_identity)"),
    ("original-store-epoch",
     "if (source->selected_store_generation != source->record.store_generation)",
     "if (false && source->selected_store_generation != source->record.store_generation)"),
    ("source-buffer-capacity",
     "if (source->source_readable_capacity < source->record.compressed_length)",
     "if (false && source->source_readable_capacity < source->record.compressed_length)"),
    ("owned-copy-length",
     "if (source->source_copy_length != source->record.compressed_length)",
     "if (false && source->source_copy_length != source->record.compressed_length)"),
    ("actual-short-lower-read",
     "if (source->actual_lower_read_bytes != source->record.compressed_length)",
     "if (false && source->actual_lower_read_bytes != source->record.compressed_length)"),
    ("independent-original-page-SHA256",
     "if (memcmp(source->independent_page_digest, source->record.original_sha256,\n"
     "               SHA256_DIGEST_LENGTH) != 0)",
     "if (false && memcmp(source->independent_page_digest, source->record.original_sha256,\n"
     "               SHA256_DIGEST_LENGTH) != 0)"),
    ("raw-not-original-compressed",
     "if (source->representation != HOST_COMPLETE_RAW_UNCOMPRESSED)",
     "if (false && source->representation != HOST_COMPLETE_RAW_UNCOMPRESSED)"),
    ("raw-no-original-compressed-codec",
     "if (source->codec != 0U)",
     "if (false && source->codec != 0U)"),
    ("raw-exact-original-4096",
     "if (source->logical_length != SWAPZ_BLOCK_BYTES)",
     "if (false && source->logical_length != SWAPZ_BLOCK_BYTES)"),
    ("raw-4096-readable-bytes",
     "if (source->readable_capacity < SWAPZ_BLOCK_BYTES)",
     "if (false && source->readable_capacity < SWAPZ_BLOCK_BYTES)"),
    ("raw-no-short-lower-io",
     "if (source->actual_lower_read_bytes != SWAPZ_BLOCK_BYTES)",
     "if (false && source->actual_lower_read_bytes != SWAPZ_BLOCK_BYTES)"),
    ("raw-original-page-sha",
     "if (memcmp(source->independent_page_digest, actual_digest,\n"
     "               SHA256_DIGEST_LENGTH) != 0)",
     "if (false && memcmp(source->independent_page_digest, actual_digest,\n"
     "               SHA256_DIGEST_LENGTH) != 0)"),
)
EXPECTED = re.compile(
    r"PASS round080-agent7 assertions=([1-9]\d*) "
    r"original_lzo1x=REAL_PINNED_LINUX_DECOMPRESS_4096 "
    r"original_codec2=LZO1X direct_codec2=ZSTD "
    r"original_lease=RETAINED_AND_DRAINED "
    r"raw4096=FULL_ORIGINAL_UNCOMPRESSED "
    r"AUTH=0 PHASE_A=BLOCKED\n\Z"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def invoke(command: list[str], *, stdin: str | None = None,
           cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, input=stdin, text=True, capture_output=True,
        check=False, timeout=150, cwd=cwd, env={
            **os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
            "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
        },
    )


def diagnostic(process: subprocess.CompletedProcess[str]) -> str:
    lines = (process.stderr or process.stdout).splitlines()
    for line in lines:
        if "error:" in line or "FIRST_ERROR" in line:
            return line.strip()[:320]
    return lines[0][:320] if lines else "no compiler or runtime diagnostic"


def source_hash(path: Path) -> str:
    result = invoke(["git", "hash-object", str(path)])
    require(result.returncode == 0,
            f"cannot source-pin {path}: {diagnostic(result)}")
    return result.stdout.strip()


def standard(compiler: str) -> str:
    for flag in ("-std=c23", "-std=c2x"):
        result = invoke([compiler, flag, "-x", "c", "-fsyntax-only", "-"],
                        stdin="int main(void) { return 0; }\n")
        if result.returncode == 0:
            return flag
    raise RuntimeError(f"{compiler}: no C23/C2x support")


def make_minimal_original_kernel_host_shims(workspace: Path) -> Path:
    """Only unaligned access + likely macros; original lzo.h/lzodefs stay pinned."""
    shim = workspace / "shims"
    (shim / "linux").mkdir(parents=True, exist_ok=True)
    (shim / "linux/unaligned.h").write_text(
        "#ifndef ROUND080_HOST_UNALIGNED_H\n"
        "#define ROUND080_HOST_UNALIGNED_H\n"
        "#include <stdint.h>\n"
        "static inline uint16_t get_unaligned_le16(const void *address)\n"
        "{\n"
        "    const unsigned char *bytes = (const unsigned char *)address;\n"
        "    return (uint16_t)((uint16_t)bytes[0] | ((uint16_t)bytes[1] << 8U));\n"
        "}\n"
        "#endif\n",
        encoding="utf-8",
    )
    (shim / "host-compat.h").write_text(
        "#include <stddef.h>\n#include <stdint.h>\n#include <string.h>\n"
        "#define likely(expression) __builtin_expect(!!(expression), 1)\n"
        "#define unlikely(expression) __builtin_expect(!!(expression), 0)\n",
        encoding="utf-8",
    )
    return shim


def compile_link(compiler: str, flag: str, source: Path,
                 original_linux: Path, shims: Path, output: Path) -> None:
    command = [
        compiler, flag, "-O1", "-g", "-Wall", "-Wextra", "-Wpedantic",
        "-Wconversion", "-Wshadow", "-Werror",
        "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
        "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
        "-DSTATIC=1",
        "-DSWAPZ_ZSWAP_IMPORT_HOST_TEST=1",
        "-DSWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST=1",
        "-DSWAPZ_ZSWAP_IMPORT_ORIGINAL_LZO_HOST_TEST=1",
        "-I", str(shims), "-I", str(original_linux / "include"),
        "-I", str(FIXTURE.parent),
        "-include", str(shims / "host-compat.h"),
        str(source), str(PRODUCT_OWNER), str(PRODUCT_CODEC),
        str(original_linux / "lib/lzo/lzo1x_decompress_safe.c"),
        "-pthread", "-llzo2", "-llz4", "-lcrypto", "-o", str(output),
    ]
    result = invoke(command)
    require(result.returncode == 0,
            f"{compiler}: compile {source.name}: {diagnostic(result)}")


def run(original_linux: Path) -> dict[str, object]:
    require(original_linux.is_dir(), "missing pinned pristine original Linux directory")
    git_head = invoke(["git", "-C", str(original_linux), "rev-parse", "HEAD"])
    require(git_head.returncode == 0 and git_head.stdout.strip() == PIN,
            f"original Linux HEAD mismatch: {diagnostic(git_head)}")
    for relative, expected_hash in PINNED_ORIGINAL_BLOBS.items():
        path = original_linux / relative
        require(path.is_file(), f"pinned original file missing: {relative}")
        require(source_hash(path) == expected_hash,
                f"pinned original blob mismatch: {relative}")
    for relative, expected_hash in PRODUCT_BLOBS.items():
        require(source_hash(ROOT / relative) == expected_hash,
                f"product codec/owner source drift: {relative}")
    for relative, anchors in ANCHORS.items():
        source = (ROOT / relative).read_text(encoding="utf-8")
        for anchor in anchors:
            require(anchor in source,
                    f"actual product source anchor changed {relative}: {anchor}")
    fixture = FIXTURE.read_text(encoding="utf-8")
    for gate in (
        "#define SOURCE_MAPPED_AUTHENTICATED 0",
        "#define DIRECT_COMPRESSED_HANDOFF 0",
        "#define FORCED_RAW_BYPASS 0",
    ):
        require(gate in fixture, f"fixture gate drift: {gate}")
    for name, anchor, replacement in MUTANTS:
        require(fixture.count(anchor) == 1 and anchor != replacement,
                f"mutant {name} missing or nonunique C anchor")
    require(len(MUTANTS) >= 12, "insufficient executed semantic mutants")

    baseline_outputs: list[str] = []
    compiler_results: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="swapz-R080-agent7-") as name:
        temp = Path(name)
        shims = make_minimal_original_kernel_host_shims(temp)
        for compiler_name in ("gcc", "clang"):
            executable_path = temp / f"{compiler_name}-lzo"
            compiler = shutil.which(compiler_name)
            require(compiler is not None, f"missing {compiler_name}")
            dialect = standard(compiler)
            compile_link(compiler, dialect, FIXTURE, original_linux,
                         shims, executable_path)
            baseline = invoke([str(executable_path)])
            result = EXPECTED.fullmatch(baseline.stdout)
            require(baseline.returncode == 0 and not baseline.stderr and
                    result is not None and int(result.group(1)) >= 110,
                    f"{compiler_name}: baseline exit={baseline.returncode} "
                    f"{diagnostic(baseline)}")
            baseline_outputs.append(baseline.stdout)
            print(f"PASS {compiler_name} {dialect} pinned Linux original LZO1X "
                  f"+ product lease ASan+UBSan: {baseline.stdout.strip()}",
                  flush=True)
            for index, (mutant_name, anchor, replacement) in enumerate(MUTANTS):
                mutant = temp / f"mutant-{compiler_name}-{index}.c"
                mutant.write_text(fixture.replace(anchor, replacement, 1),
                                  encoding="utf-8")
                compile_link(compiler, dialect, mutant, original_linux,
                             shims, executable_path)
                negative = invoke([str(executable_path)])
                require(
                    negative.returncode == 1 and not negative.stdout and
                    re.fullmatch(r"FIRST_ERROR line=\d+ check=[^\n]+\n",
                                 negative.stderr) is not None,
                    f"{compiler_name}: SEMANTIC_MUTANT_SURVIVED "
                    f"{mutant_name} exit={negative.returncode}: "
                    f"{diagnostic(negative)}",
                )
            compiler_results[compiler_name] = {
                "standard": dialect[5:],
                "sanitizers": ["address", "undefined"],
                "baseline_assertions": int(result.group(1)),
                "compiled_executed_mutants": len(MUTANTS),
                "semantic_mutants_rejected": len(MUTANTS),
            }
            print(f"PASS {compiler_name} independently_compiled_executed_"
                  f"semantic_C_mutants={len(MUTANTS)}", flush=True)
    require(baseline_outputs[0] == baseline_outputs[1],
            "GCC/Clang baseline assertion counts diverged")
    return {
        "result": "PASS", "kind": "source-linked-pinned-original-LZO1X-host",
        "original_linux_pin": PIN,
        "original_linux_blobs": PINNED_ORIGINAL_BLOBS,
        "product_blobs": PRODUCT_BLOBS,
        "compiler_results": compiler_results,
        "compiled_executed_semantic_mutants": len(MUTANTS) * 2,
        "original_input": "GENUINE_LZO1X_1_LIBLZO2_COMPRESSED_4096",
        "original_decoder": "PRISTINE_PINNED_LINUX_LZO1X_DECOMPRESS_SAFE_C",
        "product_decoder_and_owner": "REAL_SOURCE_LINKED",
        "original_native_kunit": "NOT_RUN",
        "original_stored_source_authenticated": False,
        "selected_real_dm_identity": False,
        "real_lower_fua_and_upper_ack": False,
        "source_mapped_authenticated": False,
        "phase_a": "BLOCKED",
        "direct_compressed_handoff": False,
        "forced_raw_bypass": False,
        "import_active": False,
        "raw_4096": "FULL_ORIGINAL_UNCOMPRESSED_4096",
        "second_reclaimer": False,
        "recompression": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-linux", required=True, type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--ktap", type=Path)
    args = parser.parse_args()
    try:
        result = run(args.original_linux)
        if args.json is not None:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                                 encoding="utf-8")
        if args.ktap is not None:
            args.ktap.parent.mkdir(parents=True, exist_ok=True)
            args.ktap.write_text(
                "KTAP version 1\n1..2\n"
                "ok 1 - GCC pinned original LZO1X product host decoder lease\n"
                "ok 2 - Clang pinned original LZO1X product host decoder lease\n",
                encoding="utf-8",
            )
        print("PASS round080-agent7 original_LZO1X_decode HOST_ONLY "
              f"mutants={result['compiled_executed_semantic_mutants']} "
              "AUTH=0 PHASE_A=BLOCKED", flush=True)
        return 0
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"FIRST_ERROR round080-agent7 {str(error)[:400]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
