#!/usr/bin/env python3
"""Round074: compile real swapz authority.c/codec.c and separate HOST raw guard.

No authenticated original Linux STORED source, FUA, physical I/O or upper ACK.
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
FIXTURE = ROOT / "tests/runtime/native/fixtures/round074-real-raw-fallback-source.c"
AUTHORITY_C = ROOT / "src/kernel/authority.c"
CODEC_C = ROOT / "src/kernel/codec.c"
PRODUCT_ANCHORS = {
    "src/kernel/authority.c": (
        "int swapz_stage(",
        "int swapz_finish_raw(",
        "int swapz_verify_raw(",
        "swapz_publish_crc32c(a, raw_page, SWAPZ_BLOCK_BYTES)",
    ),
    "src/kernel/authority.h": ("_Static_assert(sizeof(struct swapz_map) == 20",),
    "src/kernel/codec.c": ("swapz_crc32c_bytes(",),
    "src/kernel/codec.h": (
        "#define SWAPZ_BLOCK_BYTES 4096U",
        "#define SWAPZ_CODEC_METADATA_ON_MEDIA 0U",
        "#define SWAPZ_ENCODING_DELTA64 1U",
        "#define SWAPZ_ENCODING_DELTA64_SHUF8 2U",
    ),
    "src/kernel/zswap-import-codec.h": (
        "#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U",
        "#define SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC 2U",
        "#define SWAPZ_ZSWAP_IMPORT_LZ4_CODEC 1U",
    ),
    "src/kernel/zswap-direct-handoff.h": (
        "#define SWAPZ_DIRECT_HANDOFF_PRODUCTION_ENABLED 0U",),
}
# Each negative is an independently built and executed C mutant. Missing
# anchors, syntax errors, sanitizers or unexpected exits are NOT mutant kills.
MUTANTS = (
    ("original-compressed-never-raw",
     "if (source->kind != FULL_UNCOMPRESSED)",
     "if (false && source->kind != FULL_UNCOMPRESSED)"),
    ("native-codec-never-disk",
     "if (source->original_codec != 0U)",
     "if (false && source->original_codec != 0U)"),
    ("native-version-separate",
     "if (source->original_codec_version != 0U)",
     "if (false && source->original_codec_version != 0U)"),
    ("swapz-disk-encoding-separate",
     "if (source->disk_encoding != SWAPZ_ENCODING_INVALID)",
     "if (false && source->disk_encoding != SWAPZ_ENCODING_INVALID)"),
    ("trusted-original-full",
     "if (!source->full_page_authenticated)",
     "if (false && !source->full_page_authenticated)"),
    ("immutable-copy",
     "if (!source->immutable_owned)",
     "if (false && !source->immutable_owned)"),
    ("retired-original",
     "if (source->codec_retired)",
     "if (false && source->codec_retired)"),
    ("source-epoch",
     "if (source->original_epoch != source->expected_epoch)",
     "if (false && source->original_epoch != source->expected_epoch)"),
    ("source-identity",
     "if (source->original_identity != source->expected_identity)",
     "if (false && source->original_identity != source->expected_identity)"),
    ("entire-original-4096",
     "if (source->length != SWAPZ_BLOCK_BYTES)",
     "if (false && source->length != SWAPZ_BLOCK_BYTES)"),
    ("readable-original-capacity",
     "if (source->readable_capacity < SWAPZ_BLOCK_BYTES)",
     "if (false && source->readable_capacity < SWAPZ_BLOCK_BYTES)"),
    ("no-recompression",
     "if (source->wants_recompression)",
     "if (false && source->wants_recompression)"),
    ("once-only-upper-ack",
     "if (source->duplicate_upper_ack)",
     "if (false && source->duplicate_upper_ack)"),
    ("full-lower-write",
     "if (!source->lower_write_complete)",
     "if (false && !source->lower_write_complete)"),
    ("modeled-durable-flush",
     "if (!source->lower_flush_complete)",
     "if (false && !source->lower_flush_complete)"),
    ("independent-original-digest",
     "if (memcmp(digest, source->independent_sha256, sizeof(digest)) != 0)",
     "if (false && memcmp(digest, source->independent_sha256, sizeof(digest)) != 0)"),
    ("short-raw-lower-read",
     "if (actual_lower_bytes != SWAPZ_BLOCK_BYTES)",
     "if (false && actual_lower_bytes != SWAPZ_BLOCK_BYTES)"),
)
EXPECTED = re.compile(
    r"PASS round074-agent7 assertions=([1-9][0-9]*) "
    r"actual_product_RAW=FULL_UNCOMPRESSED_4096 "
    r"source_linked_authority=1 codec_confusion_refused=1 "
    r"host_receipts_only=1 AUTH=0 PHASE_A=BLOCKED\n\Z"
)


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def invoke(args: list[str], *, standard_input: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, input=standard_input, text=True, capture_output=True,
        check=False, timeout=120,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
             "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"},
    )


def diagnostic(result: subprocess.CompletedProcess[str]) -> str:
    for line in (result.stderr or result.stdout).splitlines():
        if "error:" in line:
            return line.split("error:", 1)[1].strip()[:240]
    lines = (result.stderr or result.stdout).splitlines()
    return lines[0][:240] if lines else "no diagnostic"


def compiler_mode(compiler: str) -> str:
    for mode in ("-std=c23", "-std=c2x"):
        trial = invoke([compiler, mode, "-x", "c", "-fsyntax-only", "-"],
                       standard_input="int main(void) { return 0; }\n")
        if trial.returncode == 0:
            return mode
    raise RuntimeError(f"{compiler}: C23 mode unavailable")


def build(compiler: str, mode: str, source: Path, target: Path) -> None:
    result = invoke([
        compiler, mode, "-O1", "-g", "-Wall", "-Wextra", "-Wconversion",
        "-Wshadow", "-Werror", "-fsanitize=address,undefined",
        "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
        "-fno-pie", "-no-pie", "-I", str(FIXTURE.parent),
        str(source), str(AUTHORITY_C), str(CODEC_C),
        "-llz4", "-lcrypto", "-o", str(target),
    ])
    require(result.returncode == 0,
            f"{compiler}: mutant/source compilation {source.name}: {diagnostic(result)}")


def run_suite() -> dict[str, object]:
    source = FIXTURE.read_text(encoding="utf-8")
    for path, anchors in PRODUCT_ANCHORS.items():
        body = (ROOT / path).read_text(encoding="utf-8")
        for anchor in anchors:
            require(anchor in body, f"product source changed {path}: {anchor}")
    for gate in ("#define SOURCE_MAPPED_AUTHENTICATED 0",
                 "#define DIRECT_COMPRESSED_HANDOFF 0",
                 "#define FORCED_RAW_BYPASS 0"):
        require(gate in source, f"source fixture gate changed {gate}")

    baseline_output: list[str] = []
    with tempfile.TemporaryDirectory(prefix="swapz-round074-agent7-") as temp:
        workspace = Path(temp)
        for compiler_name in ("gcc", "clang"):
            compiler = shutil.which(compiler_name)
            require(compiler is not None, f"missing compiler {compiler_name}")
            mode = compiler_mode(compiler)
            executable = workspace / f"{compiler_name}-raw"
            build(compiler, mode, FIXTURE, executable)
            baseline = invoke([str(executable)])
            match = EXPECTED.fullmatch(baseline.stdout)
            require(baseline.returncode == 0 and not baseline.stderr and
                    match is not None and int(match.group(1)) >= 100,
                    f"{compiler_name}: baseline failed exit={baseline.returncode} "
                    f"{diagnostic(baseline)}")
            baseline_output.append(baseline.stdout)
            print(f"PASS {compiler_name} {mode} strict ASan+UBSan "
                  f"{baseline.stdout.strip()}", flush=True)
            for index, (name, before, after) in enumerate(MUTANTS):
                require(source.count(before) == 1,
                        f"mutant {name}: missing/ambiguous product C anchor")
                changed = workspace / f"{compiler_name}-mutant-{index}.c"
                changed.write_text(source.replace(before, after, 1),
                                   encoding="utf-8")
                build(compiler, mode, changed, executable)
                negative = invoke([str(executable)])
                require(negative.returncode == 1 and not negative.stdout and
                        re.fullmatch(r"FIRST_ERROR line=\d+ check=[^\n]+\n",
                                     negative.stderr) is not None,
                        f"{compiler_name}: SEMANTIC_MUTANT_SURVIVED {name} "
                        f"exit={negative.returncode} {diagnostic(negative)}")
            print(f"PASS {compiler_name} compiled_and_executed_mutants="
                  f"{len(MUTANTS)}", flush=True)
    require(baseline_output[0] == baseline_output[1],
            "GCC and Clang baseline counts disagree")
    match = EXPECTED.fullmatch(baseline_output[0])
    require(match is not None, "baseline signature changed")
    return {
        "result": "PASS", "kind": "actual-product-raw-with-host-guard",
        "actual_product_sources": ["src/kernel/authority.c", "src/kernel/codec.c"],
        "compiler_baselines": 2,
        "directed_assertions_per_compiler": int(match.group(1)),
        "compiled_executed_semantic_mutants": len(MUTANTS) * 2,
        "semantic_mutants_rejected": len(MUTANTS) * 2,
        "host_only_ktap": "2_of_2", "original_native_ktap": "NOT_RUN",
        "original_native_kunit": "NOT_RUN", "source_mapped_authenticated": False,
        "phase_a": "BLOCKED", "direct_compressed_handoff": False,
        "forced_raw_bypass": False, "import_active": False,
        "actual_lower_io": False, "actual_fua": False, "real_upper_ack": False,
        "second_reclaimer": False, "recompression": False,
        "ordinary_raw_4096": "FULL_ORIGINAL_UNCOMPRESSED_4096",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--ktap", type=Path)
    args = parser.parse_args()
    try:
        result = run_suite()
        if args.json is not None:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                                 encoding="utf-8")
        if args.ktap is not None:
            args.ktap.parent.mkdir(parents=True, exist_ok=True)
            args.ktap.write_text(
                "KTAP version 1\n1..2\n"
                "ok 1 - GCC product-linked RAW HOST sanitizers/mutants\n"
                "ok 2 - Clang product-linked RAW HOST sanitizers/mutants\n",
                encoding="utf-8")
        print("PASS round074-agent7 product-RAW HOST_ONLY "
              f"mutants={result['compiled_executed_semantic_mutants']} "
              "AUTH=0 PHASE_A=BLOCKED", flush=True)
        return 0
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"FIRST_ERROR round074-agent7 {str(error)[:280]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
