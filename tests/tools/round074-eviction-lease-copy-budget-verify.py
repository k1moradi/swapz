#!/usr/bin/env python3
"""Round074 source-header-linked rootless source-lease/copy-budget C evidence.

No real Linux MM/zswap, source AUTH, CPU pressure, block device, or upper ACK.
Each semantic mutant is compiled and EXECUTED under GCC/Clang ASan+UBSan.
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
FIXTURE = ROOT / "tests/runtime/native/fixtures/round074-eviction-lease-copy-budget.c"
KERNEL = ROOT / "src/kernel"
IMPORT = KERNEL / "zswap-import-codec.h"
ADMISSION = KERNEL / "zswap-import-admission.h"
DIRECT = KERNEL / "zswap-direct-handoff.h"
CODEC = KERNEL / "codec.h"
ORIGINAL_MODEL = ROOT / "tests/runtime/native/fixtures/round071-natural-pressure-cooperation.c"

# Independent C source mutants, not Python-only substitutions or skipped cases.
MUTANTS = (
    ("natural-event-only", "if (!source || !source->natural_mm_eviction)",
     "if (!source)"),
    ("pool-lease", "!source->pool_lease || !source->entry_lease ||",
     "false || !source->entry_lease ||"),
    ("entry-lease", "!source->entry_lease ||", "false ||"),
    ("retired-codec", "source->codec_retired ||", "false ||"),
    ("source-erased", "!source->source_live ||", "false ||"),
    ("slot-incarnation", "source->slot_incarnation != source->current_incarnation)",
     "false)"),
    ("source-lock", "if (!source->source_lock_held)",
     "if (false && !source->source_lock_held)"),
    ("unknown-original-codec", "source->codec != SWAPZ_ZSWAP_IMPORT_LZ4_CODEC)",
     "source->codec != 0xffU)"),
    ("empty-compressed-source", "if (!source->length || source->length > SWAPZ_MAX_COMPRESSED)",
     "if (source->length > SWAPZ_MAX_COMPRESSED)"),
    ("compressed-byte-cap", "source->length > SWAPZ_MAX_COMPRESSED)",
     "source->length > SWAPZ_MAX_COMPRESSED + 1U)"),
    ("queue-capacity", "if (model.queue_count == MAX_QUEUED ||",
     "if (model.queue_count == MAX_QUEUED - 1U ||"),
    ("copy-allocation-failure", "if (model.fail_copy_allocation)",
     "if (false && model.fail_copy_allocation)"),
    ("copied-byte-identity", "memcpy(entry->bytes, source->bytes, source->length);",
     "memcpy(entry->bytes, source->bytes, source->length - 1U);"),
    ("retained-original-codec", "entry->codec = source->codec;",
     "entry->codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC;"),
    ("volatile-opaque-not-raw", "entry->representation = ORIGINAL_OPAQUE;",
     "entry->representation = ORDINARY_RAW_UNCOMPRESSED;"),
    ("no-lower-under-lock", "if (model.mm_lock_held || model.queue_lock_held || model.source_lock_held)",
     "if (model.mm_lock_held && model.queue_lock_held && model.source_lock_held)"),
    ("source-budget-limits", "model.max_copy_work_units_under_lock = source->length;",
     "model.max_copy_work_units_under_lock = SWAPZ_MAX_COMPRESSED + 1U;"),
    ("owned-queue-accounting", "model.pending_bytes += source->length;",
     "model.pending_bytes += source->length - 1U;"),
    ("copy-work-accounting", "model.copy_work_units += source->length;",
     "model.copy_work_units += source->length - 1U;"),
    ("secondary-mm-reclaim", "++model.lower_attempts;",
     "++model.external_mm_reclaim_requests; ++model.lower_attempts;"),
    ("no-recompression", "++model.lower_attempts;",
     "++model.recompress_calls; ++model.lower_attempts;"),
    ("no-hash-under-source-lock", "memcpy(entry->bytes, source->bytes, source->length);",
     "++model.source_lock_hash_calls; memcpy(entry->bytes, source->bytes, source->length);"),
    ("first-error-not-overwritten", "if (status != 0 && model.first_error == 0)",
     "if (status != 0 || model.first_error == 0)"),
    ("close-refusal", "if (model.teardown)",
     "if (false && model.teardown)"),
    ("once-only-completion", "if (completion->count == 0U) {",
     "if (completion->count < 2U) {"),
)
EXPECTED = re.compile(
    r"PASS directed=\d+ owned_copies=9 burst=8 max_owned=28544 "
    r"max_under_lock=3568 MM_ONLY=1 SECONDARY_RECLAIM=0 "
    r"RECOMPRESS=0 RAW_4096=UNCOMPRESSED AUTH=0 PHASE_A=BLOCKED HOST_ONLY=1\n"
)


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise RuntimeError(detail)


def execute(command: list[str], *, timeout: int = 90,
            stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, input=stdin, text=True, capture_output=True,
                          timeout=timeout, check=False,
                          env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
                               "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})


def diagnostic(result: subprocess.CompletedProcess[str]) -> str:
    return next(iter((result.stderr or result.stdout).splitlines()), "no diagnostic")[:260]


def check_product_contract() -> str:
    for path, anchors in {
        CODEC: ("#define SWAPZ_BLOCK_BYTES 4096U", "#define SWAPZ_MAX_COMPRESSED 3568U",
                "#define SWAPZ_CODEC_METADATA_ON_MEDIA 0U"),
        IMPORT: ("#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U",
                 "#define SWAPZ_ZSWAP_IMPORT_LZ4_CODEC 1U",
                 "#define SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC 2U"),
        ADMISSION: ("#define SWAPZ_ZSWAP_IMPORT_ADMISSION_ACTIVE 0U",
                    "static inline int swapz_zswap_admission_try_live("),
        DIRECT: ("#define SWAPZ_DIRECT_HANDOFF_PRODUCTION_ENABLED 0U",),
        ORIGINAL_MODEL: ("#define SOURCE_MAPPED_AUTHENTICATED 0",
                         "#define DIRECT_COMPRESSED_HANDOFF 0",
                         "#define FORCED_RAW_BYPASS 0"),
        FIXTURE: ("#define SOURCE_MAPPED_AUTHENTICATED 0",
                  "#define DIRECT_COMPRESSED_HANDOFF 0",
                  "#define FORCED_RAW_BYPASS 0",
                  "memcpy(entry->bytes, source->bytes, source->length);"),
    }.items():
        body = path.read_text(encoding="utf-8")
        for anchor in anchors:
            require(anchor in body, f"source contract drift: {path.relative_to(ROOT)} {anchor}")
    return FIXTURE.read_text(encoding="utf-8")


def c23(compiler: str) -> str:
    for flag in ("-std=c23", "-std=c2x"):
        if execute([compiler, flag, "-x", "c", "-fsyntax-only", "-"],
                   stdin="int main(void) { return 0; }\n").returncode == 0:
            return flag
    raise RuntimeError(f"{compiler} cannot compile C23")


def compile_c(compiler: str, standard: str, source: Path, output: Path) -> None:
    result = execute([compiler, standard, "-O1", "-g", "-Wall", "-Wextra",
                      "-Wconversion", "-Wshadow", "-Werror", "-fsanitize=address,undefined",
                      "-fno-sanitize-recover=all", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                      "-I", str(FIXTURE.parent), str(source), "-o", str(output)])
    require(result.returncode == 0,
            f"{compiler} strict C ASan+UBSan compile failed: {diagnostic(result)}")


def run() -> dict[str, object]:
    source = check_product_contract()
    observations: list[str] = []
    with tempfile.TemporaryDirectory(prefix="swapz-round074-agent6-") as directory:
        workspace = Path(directory)
        for compiler_name in ("gcc", "clang"):
            compiler = shutil.which(compiler_name)
            require(compiler is not None, f"required compiler unavailable: {compiler_name}")
            standard = c23(compiler)
            executable = workspace / f"{compiler_name}-lease"
            compile_c(compiler, standard, FIXTURE, executable)
            baseline = execute([str(executable)])
            require(baseline.returncode == 0 and not baseline.stderr and
                    EXPECTED.fullmatch(baseline.stdout) is not None,
                    f"{compiler_name} baseline exit={baseline.returncode} "
                    f"first={diagnostic(baseline)}")
            observations.append(baseline.stdout)
            print(f"PASS compiler={compiler_name} {standard} strict ASan UBSan "
                  f"{baseline.stdout.strip()}", flush=True)
            for index, (name, before, after) in enumerate(MUTANTS):
                require(source.count(before) == 1 or
                        (name == "no-hash-under-source-lock" and source.count(before) == 1) or
                        (name == "no-recompression" and source.count(before) == 1),
                        f"ambiguous mutant anchor: {name}")
                mutated = source.replace(before, after, 1)
                mutant_path = workspace / f"{compiler_name}-mutant-{index}.c"
                mutant_path.write_text(mutated, encoding="utf-8")
                compile_c(compiler, standard, mutant_path, executable)
                result = execute([str(executable)])
                require(result.returncode == 1 and not result.stdout and
                        re.fullmatch(r"FIRST_ERROR line=\d+ check=[^\n]+\n", result.stderr),
                        f"{compiler_name} SEMANTIC_MUTANT_SURVIVED {name}: "
                        f"exit={result.returncode} first={diagnostic(result)}")
            print(f"PASS compiler={compiler_name} compiled_executed_C_mutants={len(MUTANTS)}",
                  flush=True)
    require(observations[0] == observations[1], "compiler counter mismatch")
    return {"result": "PASS", "model_only": True, "native_original_linux": False,
            "source_authenticated": False, "phase_a": "BLOCKED", "direct_handoff": False,
            "forced_raw": False, "import_active": False, "physical_io": False,
            "real_pressure": False, "compiled_baselines": 2,
            "compiled_executed_semantic_mutants": 2 * len(MUTANTS),
            "model_stdout": observations[0].strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--ktap", type=Path)
    args = parser.parse_args()
    try:
        outcome = run()
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(outcome, sort_keys=True, indent=2) + "\n",
                                 encoding="utf-8")
        if args.ktap:
            args.ktap.parent.mkdir(parents=True, exist_ok=True)
            args.ktap.write_text("KTAP version 1\n1..2\n"
                                 "ok 1 - GCC source header linked host model 25/25 mutants\n"
                                 "ok 2 - Clang source header linked host model 25/25 mutants\n",
                                 encoding="utf-8")
        print("PASS round074-agent6 HOST_MODEL_ONLY source-lease-budget "
              "GCC_Clang_strict_ASan_UBSan mutants=50 AUTH=0 PHASE_A=BLOCKED",
              flush=True)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print(f"FIRST_ERROR round074-agent6 {str(error)[:350]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
