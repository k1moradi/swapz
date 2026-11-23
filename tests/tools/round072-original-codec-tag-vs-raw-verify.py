#!/usr/bin/env python3
"""Round072 source-linked rootless codec-family/RAW ABI host execution.

Host LZ4-compressed input is NOT an authenticated kernel zswap source.
Actual original-Linux KUnit, LZO decode, physical FUA and upper ACK are NOT_RUN.
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
FIXTURE = ROOT / "tests/runtime/native/fixtures/round072-original-codec-tag-vs-raw.c"
HEADERS = {
    "src/kernel/codec.h": (
        "#define SWAPZ_BLOCK_BYTES 4096U",
        "#define SWAPZ_CODEC_METADATA_ON_MEDIA 0U",
        "#define SWAPZ_MAX_COMPRESSED 3568U",
    ),
    "src/kernel/zswap-import-codec.h": (
        "#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U",
        "#define SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC 2U",
        "#define SWAPZ_ZSWAP_IMPORT_LZ4_CODEC 1U",
    ),
    "src/kernel/zswap-direct-handoff.h": (
        "#define SWAPZ_DIRECT_HANDOFF_PRODUCTION_ENABLED 0U",
        "SWAPZ_DIRECT_ZSWAP_ZSTD = 2",
    ),
    "src/kernel/zswap-import-admission.h": (
        "#define SWAPZ_ZSWAP_IMPORT_ADMISSION_ACTIVE 0U",
    ),
    "src/kernel/authority.h": (
        "_Static_assert(sizeof(struct swapz_map) == 20",
        "#define SWAPZ_LINUX_SWAP_HEADER_BLOCKS 1U",
    ),
}
MUTANTS = (
    ("natural-eviction", "if (!source->natural_eviction)",
     "if (false && !source->natural_eviction)"),
    ("owned-source-lease", "if (!source->source_lock_held || !source->immutable_owned_copy)",
     "if (false && !source->source_lock_held || !source->immutable_owned_copy)"),
    ("source-epoch", "source->source_epoch != source->observed_epoch)",
     "false && source->source_epoch != source->observed_epoch)"),
    ("codec-family", "source->codec != SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC)",
     "source->codec != 0xffU)"),
    ("codec-version", "if (source->codec_version != SWAPZ_ZSWAP_IMPORT_VERSION)",
     "if (false && source->codec_version != SWAPZ_ZSWAP_IMPORT_VERSION)"),
    ("max-original-compressed", "source->length > SWAPZ_MAX_COMPRESSED)",
     "false && source->length > SWAPZ_MAX_COMPRESSED)"),
    ("swapz-disk-codec-confusion", "if (source->disk_encoding != SWAPZ_ENCODING_INVALID)",
     "if (false && source->disk_encoding != SWAPZ_ENCODING_INVALID)"),
    ("raw-full-page", "if (source->length != SWAPZ_BLOCK_BYTES || source->codec != 0U ||",
     "if (false && source->length != SWAPZ_BLOCK_BYTES || source->codec != 0U ||"),
    ("decoder-codec-lease", "if (tag.original_codec != expected_codec ||",
     "if (false && tag.original_codec != expected_codec ||"),
    ("read-source-epoch", "tag.source_epoch != expected_epoch)",
     "false && tag.source_epoch != expected_epoch)"),
    ("short-lower-copy", "if (actual_lower_bytes != tag.length)",
     "if (false && actual_lower_bytes != tag.length)"),
    ("nonzero-extent-padding", "if (lower_image[SWAPZ_BLOCK_BYTES + offset] != 0U)",
     "if (false && lower_image[SWAPZ_BLOCK_BYTES + offset] != 0U)"),
    ("protected-header", "if (memcmp(lower_image, protected_header, sizeof(protected_header)) != 0)",
     "if (false && memcmp(lower_image, protected_header, sizeof(protected_header)) != 0)"),
    ("lzo-as-zstd", "if (record->original_codec == SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC)",
     "if (false && record->original_codec == SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC)"),
)
EXPECTED = re.compile(
    r"PASS directed=([1-9][0-9]*) extents=4,8,16KiB original_lz4=decoded_4096 "
    r"original_lzo=opaque_unsupported RAW_4096=FULL_UNCOMPRESSED "
    r"AUTH=0 PHASE_A=BLOCKED no_recompression=1\n\Z"
)


def require(value: bool, failure: str) -> None:
    if not value:
        raise RuntimeError(failure)


def invoke(command: list[str], *, source: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, input=source, capture_output=True, text=True,
        check=False, timeout=90, env={**os.environ,
            "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
            "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"},
    )


def diagnostic(process: subprocess.CompletedProcess[str]) -> str:
    messages = (process.stderr or process.stdout).splitlines()
    return messages[0][:240] if messages else "no diagnostic"


def compiler_standard(compiler: str) -> str:
    for mode in ("-std=c23", "-std=c2x"):
        process = invoke([compiler, mode, "-x", "c", "-fsyntax-only", "-"],
                         source="int main(void) { return 0; }\n")
        if process.returncode == 0:
            return mode
    raise RuntimeError(f"{compiler}: no C23 compiler mode")


def compile_c(compiler: str, mode: str, fixture: Path, binary: Path) -> None:
    command = [compiler, mode, "-O1", "-g", "-Wall", "-Wextra", "-Wconversion",
               "-Wshadow", "-Werror", "-fsanitize=address,undefined",
               "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
               "-fno-pie", "-no-pie", str(fixture), str(ROOT / "src/kernel/codec.c"),
               "-llz4", "-lcrypto", "-o", str(binary)]
    process = invoke(command)
    require(process.returncode == 0,
            f"{compiler} compile {fixture.name}: {diagnostic(process)}")


def run() -> dict[str, object]:
    code = FIXTURE.read_text(encoding="utf-8")
    for filename, anchors in HEADERS.items():
        contents = (ROOT / filename).read_text(encoding="utf-8")
        for anchor in anchors:
            require(anchor in contents, f"product source drift {filename}: {anchor}")
    require("#define SOURCE_MAPPED_AUTHENTICATED 0" in code,
            "fixture source authentication drift")
    outputs: list[str] = []
    with tempfile.TemporaryDirectory(prefix="swapz-round072-agent7-") as directory:
        workspace = Path(directory)
        for compiler_name in ("gcc", "clang"):
            compiler = shutil.which(compiler_name)
            require(compiler is not None, f"missing compiler {compiler_name}")
            mode = compiler_standard(compiler)
            binary = workspace / f"{compiler_name}-test"
            compile_c(compiler, mode, FIXTURE, binary)
            baseline = invoke([str(binary)])
            found = EXPECTED.fullmatch(baseline.stdout)
            require(baseline.returncode == 0 and not baseline.stderr and
                    found is not None and int(found.group(1)) >= 40,
                    f"{compiler_name} baseline: exit={baseline.returncode} "
                    f"{diagnostic(baseline)}")
            outputs.append(baseline.stdout)
            print(f"PASS {compiler_name} {mode} ASan+UBSan: "
                  f"{baseline.stdout.strip()}", flush=True)
            for index, (name, original, replacement) in enumerate(MUTANTS):
                require(code.count(original) == 1,
                        f"mutant {name} non-unique source anchor")
                mutant = workspace / f"mutant-{compiler_name}-{index}.c"
                # Include paths in C are relative to its original repository
                # directory; temporary copies therefore need an explicit -I.
                mutant.write_text(code.replace(original, replacement, 1),
                                  encoding="utf-8")
                command = [compiler, mode, "-O1", "-g", "-Wall", "-Wextra",
                           "-Wconversion", "-Wshadow", "-Werror",
                           "-fsanitize=address,undefined",
                           "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                           "-fno-pie", "-no-pie", "-I", str(FIXTURE.parent),
                           str(mutant), str(ROOT / "src/kernel/codec.c"),
                           "-llz4", "-lcrypto", "-o", str(binary)]
                built = invoke(command)
                require(built.returncode == 0,
                        f"{compiler_name} mutant {name} compile: {diagnostic(built)}")
                rejected = invoke([str(binary)])
                require(rejected.returncode == 1 and not rejected.stdout and
                        re.fullmatch(r"FIRST_ERROR line=\d+ check=[^\n]+\n",
                                     rejected.stderr) is not None,
                        f"{compiler_name} SEMANTIC_MUTANT_SURVIVED {name}: "
                        f"exit={rejected.returncode} {diagnostic(rejected)}")
            print(f"PASS {compiler_name} compiled_executed_mutants={len(MUTANTS)}",
                  flush=True)
    require(outputs[0] == outputs[1], "compiler baseline outputs disagree")
    return {
        "result": "PASS", "kind": "source-linked-rootless-host-contract",
        "compiler_baselines": 2,
        "compiled_executed_semantic_mutants": len(MUTANTS) * 2,
        "directed_assertions_per_baseline": int(EXPECTED.fullmatch(outputs[0]).group(1)),
        "original_linux_kunit": "NOT_RUN", "lzo_positive_decode": "NOT_RUN",
        "original_source_authenticated": False, "native_kernel": False,
        "real_lower_io": False, "real_fua": False, "real_upper_ack": False,
        "phase_a": "BLOCKED", "source_mapped_authenticated": False,
        "direct_compressed_handoff": False, "forced_raw_bypass": False,
        "import_active": False, "ordinary_raw_4096": "FULL_UNCOMPRESSED",
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
            arguments.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
        if arguments.ktap is not None:
            arguments.ktap.parent.mkdir(parents=True, exist_ok=True)
            arguments.ktap.write_text(
                "KTAP version 1\n1..2\n"
                "ok 1 - GCC source-linked host sanitizers and semantic mutants (NOT KUnit)\n"
                "ok 2 - Clang source-linked host sanitizers and semantic mutants (NOT KUnit)\n",
                encoding="utf-8")
        print("PASS round072-agent7 source-header-linked HOST_ONLY "
              f"mutants={result['compiled_executed_semantic_mutants']} "
              "AUTH=0 PHASE_A=BLOCKED", flush=True)
        return 0
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"FIRST_ERROR round072-agent7 {str(error)[:280]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
