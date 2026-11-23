#!/usr/bin/env python3
"""Round077 Agent7 typed codec ABI boundary: actual source-linked C and mutants.

Compile original-import-decoder-owner.c and codec.c, call the real inline
direct-handoff and original import-decode contracts. Neither source AUTH nor
original-Linux KUnit or real physical durability can be proved on this host.
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
FIXTURE = ROOT / "tests/runtime/native/fixtures/round077-original-codec-tag-cross-abi.c"
DECODER = ROOT / "src/kernel/zswap-import-decoder-owner.c"
CODEC = ROOT / "src/kernel/codec.c"
SOURCE_ANCHORS = {
    "src/kernel/zswap-direct-handoff.h": (
        "#define SWAPZ_DIRECT_HANDOFF_PRODUCTION_ENABLED 0U",
        "SWAPZ_DIRECT_ZSWAP_LZ4 = 1,",
        "SWAPZ_DIRECT_ZSWAP_ZSTD = 2,",
        "static inline int swapz_direct_validate(",
        "static inline int swapz_direct_readback(",
    ),
    "src/kernel/zswap-import-codec.h": (
        "#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U",
        "#define SWAPZ_ZSWAP_IMPORT_LZ4_CODEC 1U",
        "#define SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC 2U",
        "static inline int swapz_zswap_import_decode(",
    ),
    "src/kernel/zswap-import-decoder-owner.c": (
        "int swapz_zswap_import_decoder_owner_init(",
        "int swapz_zswap_import_decoder_owner_get(",
        "int swapz_zswap_import_decoder_owner_decode(",
        "int swapz_zswap_import_decoder_owner_close_and_drain(",
        "record->codec != lease->codec",
    ),
    "src/kernel/codec.h": (
        "#define SWAPZ_BLOCK_BYTES 4096U",
        "#define SWAPZ_CODEC_METADATA_ON_MEDIA 0U",
        "#define SWAPZ_ENCODING_DELTA64_SHUF8 2U",
    ),
    "src/kernel/authority.h": (
        "_Static_assert(sizeof(struct swapz_map) == 20",
        "#define SWAPZ_LINUX_SWAP_HEADER_BLOCKS 1U",
    ),
}
# Every mutant compiles as a standalone C executable linked with the real
# product codec.c and original decoder owner. The original baseline executes
# every negative. A mutant is killed ONLY by semantic FIRST_ERROR on execute.
MUTANTS = (
    ("typed-original-codec-namespace",
     "if (source->codec_namespace != SOURCE_ORIGINAL_IMPORT)",
     "if (false && source->codec_namespace != SOURCE_ORIGINAL_IMPORT)"),
    ("original-compressed-representation",
     "if (source->representation != SOURCE_ORIGINAL_COMPRESSED)",
     "if (false && source->representation != SOURCE_ORIGINAL_COMPRESSED)"),
    ("independent-original-source-proof",
     "if (!source->original_source_witness)",
     "if (false && !source->original_source_witness)"),
    ("linux-mm-natural-eviction",
     "if (!source->original_eviction)",
     "if (false && !source->original_eviction)"),
    ("immutable-original-copy",
     "if (!source->owns_immutable_copy)",
     "if (false && !source->owns_immutable_copy)"),
    ("independently-retained-decoder",
     "if (!source->original_decoder_retained)",
     "if (false && !source->original_decoder_retained)"),
    ("retired-original-decoder",
     "if (source->decoder_retired)",
     "if (false && source->decoder_retired)"),
    ("lzo1x-as-direct-lz4-not-allowed",
     "if (source->original_codec != SWAPZ_ZSWAP_IMPORT_LZ4_CODEC)",
     "if (false && source->original_codec != SWAPZ_ZSWAP_IMPORT_LZ4_CODEC)"),
    ("original-codec-version",
     "if (source->original_version != SWAPZ_ZSWAP_IMPORT_VERSION)",
     "if (false && source->original_version != SWAPZ_ZSWAP_IMPORT_VERSION)"),
    ("direct-zstd2-as-original-lzo2-not-allowed",
     "if (descriptor->codec != SWAPZ_DIRECT_ZSWAP_LZ4)",
     "if (false && descriptor->codec != SWAPZ_DIRECT_ZSWAP_LZ4)"),
    ("independently-leased-original-codec",
     "if (!original_lease->owner ||\n        original_lease->codec != SWAPZ_ZSWAP_IMPORT_LZ4_CODEC)",
     "if (!original_lease->owner)"),
    ("independently-leased-version",
     "if (original_lease->version != SWAPZ_ZSWAP_IMPORT_VERSION)",
     "if (false && original_lease->version != SWAPZ_ZSWAP_IMPORT_VERSION)"),
    ("raw-lz4-block-not-framed",
     "if (!source->raw_lz4_unframed)",
     "if (false && !source->raw_lz4_unframed)"),
    ("swapz-disk-codec-namespace",
     "if (source->disk_encoding != SWAPZ_ENCODING_INVALID)",
     "if (false && source->disk_encoding != SWAPZ_ENCODING_INVALID)"),
    ("no-second-recompression",
     "if (source->requests_recompression)",
     "if (false && source->requests_recompression)"),
    ("no-secondary-pressure-reclaimer",
     "if (source->requests_secondary_reclaim)",
     "if (false && source->requests_secondary_reclaim)"),
    ("original-logical-slot",
     "if (source->logical_page != descriptor->logical_page)",
     "if (false && source->logical_page != descriptor->logical_page)"),
    ("original-generation",
     "if (source->generation != descriptor->generation)",
     "if (false && source->generation != descriptor->generation)"),
    ("original-record-identity",
     "if (source->record_identity != descriptor->source_record_identity)",
     "if (false && source->record_identity != descriptor->source_record_identity)"),
    ("original-pool-identity",
     "if (source->pool_identity != descriptor->pool_identity)",
     "if (false && source->pool_identity != descriptor->pool_identity)"),
    ("original-dictionary-identity",
     "if (source->dictionary_identity != descriptor->dictionary_identity)",
     "if (false && source->dictionary_identity != descriptor->dictionary_identity)"),
    ("original-codec-generation",
     "if (source->codec_generation != descriptor->codec_generation)",
     "if (false && source->codec_generation != descriptor->codec_generation)"),
    ("original-compressed-length",
     "if (source->compressed_length != descriptor->compressed_length)",
     "if (false && source->compressed_length != descriptor->compressed_length)"),
    ("original-readable-capacity",
     "if (source->readable_capacity < descriptor->compressed_length)",
     "if (false && source->readable_capacity < descriptor->compressed_length)"),
    ("short-original-lower-read",
     "if (source->actual_lower_read_bytes != descriptor->compressed_length)",
     "if (false && source->actual_lower_read_bytes != descriptor->compressed_length)"),
    ("independent-original-sha",
     "if (memcmp(source->independent_original_sha256,\n               descriptor->expected_page_sha256, SHA256_DIGEST_LENGTH) != 0)",
     "if (false && memcmp(source->independent_original_sha256,\n               descriptor->expected_page_sha256, SHA256_DIGEST_LENGTH) != 0)"),
    ("raw-never-original-compressed",
     "if (source->representation != SOURCE_FULL_UNCOMPRESSED)",
     "if (false && source->representation != SOURCE_FULL_UNCOMPRESSED)"),
    ("raw-must-have-zero-original-codec",
     "if (source->original_codec != 0U)",
     "if (false && source->original_codec != 0U)"),
    ("raw-full-4096-length",
     "if (source->input_length != SWAPZ_BLOCK_BYTES)",
     "if (false && source->input_length != SWAPZ_BLOCK_BYTES)"),
    ("raw-readable-full-capacity",
     "if (source->readable_capacity < SWAPZ_BLOCK_BYTES)",
     "if (false && source->readable_capacity < SWAPZ_BLOCK_BYTES)"),
    ("raw-short-lower-read",
     "if (source->actual_lower_read_bytes != SWAPZ_BLOCK_BYTES)",
     "if (false && source->actual_lower_read_bytes != SWAPZ_BLOCK_BYTES)"),
    ("raw-independent-sha",
     "if (memcmp(digest, source->independent_original_sha256,\n               SHA256_DIGEST_LENGTH) != 0)",
     "if (false && memcmp(digest, source->independent_original_sha256,\n               SHA256_DIGEST_LENGTH) != 0)"),
)
OUTPUT_PATTERN = re.compile(
    r"PASS round077-agent7 assertions=([1-9][0-9]*) "
    r"direct2=ZSTD import2=LZO1X "
    r"typed_cross_abi_refused=1 raw4096=FULL_ORIGINAL_UNCOMPRESSED "
    r"actual_import_decoder_lease=1 original_lzo_decode=NOT_RUN "
    r"AUTH=0 PHASE_A=BLOCKED\n\Z"
)


def require(condition: bool, description: str) -> None:
    if not condition:
        raise RuntimeError(description)


def execute(command: list[str], input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, input=input_text, capture_output=True, text=True, timeout=120,
        check=False, env={
            **os.environ,
            "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
            "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
        },
    )


def first_diagnostic(process: subprocess.CompletedProcess[str]) -> str:
    lines = (process.stderr or process.stdout).splitlines()
    for line in lines:
        if "error:" in line:
            return line.split("error:", 1)[1].strip()[:240]
    return lines[0][:240] if lines else "no compiler or runtime diagnostic"


def compiler_mode(compiler: str) -> str:
    for mode in ("-std=c23", "-std=c2x"):
        process = execute([compiler, mode, "-x", "c", "-fsyntax-only", "-"],
                          "int main(void) { return 0; }\n")
        if process.returncode == 0:
            return mode
    raise RuntimeError(f"{compiler}: C23 compiler standard unsupported")


def compile_test(compiler: str, mode: str, source: Path, output: Path) -> None:
    process = execute([
        compiler, mode, "-O1", "-g", "-Wall", "-Wextra", "-Wpedantic",
        "-Wconversion", "-Wshadow", "-Werror", "-fsanitize=address,undefined",
        "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
        "-fno-pie", "-no-pie",
        "-DSWAPZ_ZSWAP_IMPORT_HOST_TEST=1",
        "-DSWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST=1",
        "-I", str(FIXTURE.parent),
        str(source), str(DECODER), str(CODEC),
        "-pthread", "-llz4", "-lcrypto", "-o", str(output),
    ])
    require(process.returncode == 0,
            f"{compiler}: compile {source.name}: {first_diagnostic(process)}")


def run() -> dict[str, object]:
    source = FIXTURE.read_text(encoding="utf-8")
    for filename, anchors in SOURCE_ANCHORS.items():
        contents = (ROOT / filename).read_text(encoding="utf-8")
        for anchor in anchors:
            require(anchor in contents,
                    f"exact source contract drift {filename}: {anchor}")
    for gate in (
        "#define SOURCE_MAPPED_AUTHENTICATED 0",
        "#define DIRECT_COMPRESSED_HANDOFF 0",
        "#define FORCED_RAW_BYPASS 0",
    ):
        require(gate in source, f"fixture source gate changed: {gate}")

    outputs: list[str] = []
    per_compiler: dict[str, dict[str, object]] = {}
    with tempfile.TemporaryDirectory(prefix="swapz-round077-agent7-") as directory:
        workspace = Path(directory)
        for compiler_name in ("gcc", "clang"):
            compiler = shutil.which(compiler_name)
            require(compiler is not None, f"compiler missing: {compiler_name}")
            mode = compiler_mode(compiler)
            executable = workspace / f"{compiler_name}-codec"
            compile_test(compiler, mode, FIXTURE, executable)
            baseline = execute([str(executable)])
            match = OUTPUT_PATTERN.fullmatch(baseline.stdout)
            require(baseline.returncode == 0 and not baseline.stderr and
                    match is not None and int(match.group(1)) >= 100,
                    f"{compiler_name}: baseline exit={baseline.returncode}: "
                    f"{first_diagnostic(baseline)}")
            outputs.append(baseline.stdout)
            print(f"PASS {compiler_name} {mode} strict ASan+UBSan "
                  f"{baseline.stdout.strip()}", flush=True)
            for mutant_index, (name, anchor, replacement) in enumerate(MUTANTS):
                require(source.count(anchor) == 1,
                        f"{compiler_name}: mutant {name} missing/nonunique anchor")
                mutated = workspace / f"{compiler_name}-mutant-{mutant_index}.c"
                mutated.write_text(source.replace(anchor, replacement, 1),
                                   encoding="utf-8")
                compile_test(compiler, mode, mutated, executable)
                negative = execute([str(executable)])
                require(
                    negative.returncode == 1 and not negative.stdout and
                    re.fullmatch(r"FIRST_ERROR line=\d+ check=[^\n]+\n",
                                 negative.stderr) is not None,
                    f"{compiler_name}: SEMANTIC_MUTANT_SURVIVED {name} "
                    f"exit={negative.returncode}: {first_diagnostic(negative)}",
                )
            per_compiler[compiler_name] = {
                "standard": mode[5:],
                "directed_assertions": int(match.group(1)),
                "compiled_executed_mutants": len(MUTANTS),
                "mutants_rejected": len(MUTANTS),
                "sanitizers": "address,undefined",
            }
            print(f"PASS {compiler_name} compiled_executed_semantic_mutants="
                  f"{len(MUTANTS)}", flush=True)
    require(outputs[0] == outputs[1], "GCC/Clang assertion counts diverged")
    return {
        "kind": "source-linked-host-only-original-vs-direct-codec-namespace",
        "result": "PASS",
        "compilers": per_compiler,
        "compiled_executed_C_mutants": len(MUTANTS) * 2,
        "mutants_rejected": len(MUTANTS) * 2,
        "host_ktap_tests": 2,
        "source_headers": list(SOURCE_ANCHORS),
        "real_product_sources_linked": [
            "src/kernel/zswap-import-decoder-owner.c",
            "src/kernel/codec.c",
        ],
        "direct_tag2": "ZSTD",
        "original_import_tag2": "LZO1X",
        "original_lzo_positive_decode": "NOT_RUN",
        "real_original_linux_kunit_ktap_json": "NOT_RUN",
        "source_mapped_authenticated": False,
        "phase_a": "BLOCKED",
        "direct_compressed_handoff": False,
        "forced_raw_bypass": False,
        "import_active": False,
        "ordinary_raw_4096": "FULL_ORIGINAL_UNCOMPRESSED_4096",
        "real_lower_io": False,
        "real_fua": False,
        "real_upper_ack": False,
        "second_reclaimer": False,
        "recompression": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--ktap", type=Path)
    arguments = parser.parse_args()
    try:
        result = run()
        if arguments.json is not None:
            arguments.json.parent.mkdir(parents=True, exist_ok=True)
            arguments.json.write_text(json.dumps(result, indent=2, sort_keys=True)
                                      + "\n", encoding="utf-8")
        if arguments.ktap is not None:
            arguments.ktap.parent.mkdir(parents=True, exist_ok=True)
            arguments.ktap.write_text(
                "KTAP version 1\n1..2\n"
                "ok 1 - GCC real source-linked original versus direct codec ABI\n"
                "ok 2 - Clang real source-linked original versus direct codec ABI\n",
                encoding="utf-8",
            )
        print(
            "PASS round077-agent7 HOST_ONLY typed_codec_tag2 "
            f"mutants={result['compiled_executed_C_mutants']} "
            "AUTH=0 PHASE_A=BLOCKED",
            flush=True,
        )
        return 0
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"FIRST_ERROR round077-agent7 {str(error)[:300]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
