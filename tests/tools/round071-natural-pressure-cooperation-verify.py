#!/usr/bin/env python3
"""Round071 rootless, deterministic natural-MM cooperation model/negative C controls.

Every compiler builds and executes the original fixture and independently
compiled semantic-mutant C programs under ASan+UBSan. This is an original
*swapz-header*-linked policy simulation, not Linux MM, original KUnit, or IO.
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
FIXTURE = ROOT / "tests/runtime/native/fixtures/round071-natural-pressure-cooperation.c"
CODEC = ROOT / "src/kernel/codec.h"
IMPORT = ROOT / "src/kernel/zswap-import-codec.h"
DIRECT = ROOT / "src/kernel/zswap-direct-handoff.h"
PREVIOUS = ROOT / "tests/runtime/native/fixtures/round052-natural-pressure-scheduling.c"

# Every changed C file is compiled and executed; no Python-only mock mutation.
MUTANTS = (
    ("natural-mm-only", "if (!source || !source->natural_mm_eviction)",
     "if (!source)"),
    ("retired-original", "!source->source_live || source->codec_retired ||",
     "!source->source_live || false ||"),
    ("codec-generation", "source->codec_generation != source->observed_codec_generation)",
     "(false && source->codec_generation != source->observed_codec_generation))"),
    ("source-copy-lease", "if (!source->source_lock_held)",
     "if (false && !source->source_lock_held)"),
    ("compressed-byte-bound", "source->length > SWAPZ_MAX_COMPRESSED)",
     "source->length > SWAPZ_BLOCK_BYTES)"),
    ("original-codec-identity", "source->codec != SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC)",
     "source->codec != 0xffU)"),
    ("raw-is-full-uncompressed", "source->length != SWAPZ_BLOCK_BYTES || source->codec != 0U)",
     "source->length > SWAPZ_BLOCK_BYTES || source->codec != 0U)"),
    ("duplicate-pending", "if (model.queue[index].ticket == source->ticket)",
     "if (false && model.queue[index].ticket == source->ticket)"),
    ("bounded-queue", "if (model.queue_count == MAX_QUEUE ||",
     "if (model.queue_count == MAX_QUEUE - 1U ||"),
    ("immutable-owned-copy", "memcpy(entry->bytes, source->bytes, source->length);",
     "memcpy(entry->bytes, source->bytes, source->length - 1U);"),
    ("codec-retained-on-disk", "entry->codec = source->codec;",
     "entry->codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC;"),
    ("raw-not-relabelled", "entry->kind = source->kind;",
     "entry->kind = ORIGINAL_COMPRESSED;"),
    ("no-IO-under-lock", "if (model.worker_lock_held || model.mm_lock_held)",
     "if (false && (model.worker_lock_held || model.mm_lock_held))"),
    ("durability-first", "if (lower_status != 0 || !durable_fua)",
     "if (lower_status != 0 && !durable_fua)"),
    ("GC-reader-pin", "if (model.reader_pins)",
     "if (false && model.reader_pins)"),
    ("FIFO-pack", "while (count < model.queue_count &&",
     "while (false && count < model.queue_count &&"),
    ("no-secondary-reclaim", "++model.write_attempts;",
     "++model.swapz_secondary_reclaim_calls; ++model.write_attempts;"),
    ("no-recompression", "++model.write_attempts;",
     "++model.recompress_calls; ++model.write_attempts;"),
    ("exactly-once-upper", "if (completion->count == 0U) {",
     "if (completion->count < 2U) {"),
    ("first-error-wins", "if (status != 0 && model.first_error == 0)",
     "if (status != 0 && model.first_error == -EIO)"),
    ("immutable-header", "model.allocated[0] = true; /* Entire SWAPSPACE2 physical header page. */",
     "model.allocated[0] = false; /* Invalid header reserve. */"),
    ("GC-original-bytes", "model.mappings[ticket].extent_index = replacement_index;",
     "model.mappings[ticket].extent_index = extent_index;"),
    ("allocation-backpressure", "if (model.inject_allocation_failure)",
     "if (false && model.inject_allocation_failure)"),
    ("teardown-refusal", "if (model.closed)",
     "if (false && model.closed)"),
)

EXPECTED = re.compile(
    r"PASS directed=27 burst_events=128 extents=4,8,16KiB "
    r"MM_ONLY=1 SECONDARY_RECLAIM=0 RECOMPRESS=0 "
    r"RAW_4096=UNCOMPRESSED AUTH=0 PHASE_A=BLOCKED "
    r"copy_bytes=70400 lower_padded_bytes=81920 fua=8 "
    r"upper_ack=32 queue_peak=8 owned_peak=17600 synthetic_only=1\n"
)


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def invoke(command: list[str], *, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, input=stdin, text=True, capture_output=True,
        check=False, timeout=90,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
             "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"},
    )


def first_diagnostic(result: subprocess.CompletedProcess[str]) -> str:
    lines = (result.stderr or result.stdout).splitlines()
    return (lines[0][:240] if lines else "no diagnostic")


def verify_policy_workflow_push_base() -> None:
    """Fail closed if the real push event's first-parent SHA stops reaching CI."""
    workflow = (ROOT / ".github/workflows/phase-a-round071-natural-pressure-cooperation-noauth.yml").read_text(
        encoding="utf-8")
    event_before = "$" + "{{ github.event.before }}"
    expected_env = "    env:\n      SWAPZ_PUSH_BEFORE_SHA: " + event_before + "\n"
    require(expected_env in workflow and
            workflow.count("SWAPZ_PUSH_BEFORE_SHA:") == 1,
            "exact main-push base missing, ambiguous or fabricated")
    for required in ("on:\n", "  push:\n", "    branches: [main]\n",
                     "  workflow_dispatch:\n",
                     "python3 -B tests/runtime/native/repository-policy-test.py\n",
                     "python3 -B tests/runtime/native/repository-policy-test.py --enforce"):
        require(required in workflow,
                f"source CI push/dispatch first-parent policy guard absent: {required!r}")


def verify_source_contract() -> str:
    tracked = {
        CODEC: ("#define SWAPZ_BLOCK_BYTES 4096U",
                "#define SWAPZ_MAX_BLOCKS 4U",
                "#define SWAPZ_MAX_COMPRESSED 3568U",
                "#define SWAPZ_CODEC_METADATA_ON_MEDIA 0U"),
        IMPORT: ("#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U",
                 "#define SWAPZ_ZSWAP_IMPORT_REPRESENTATION 0x5aU",
                 "#define SWAPZ_ZSWAP_IMPORT_LZ4_CODEC 1U",
                 "#define SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC 2U"),
        DIRECT: ("#define SWAPZ_DIRECT_HANDOFF_PRODUCTION_ENABLED 0U",),
        PREVIOUS: ("#define SOURCE_MAPPED_AUTHENTICATED 0",
                   "#define DIRECT_COMPRESSED_HANDOFF 0",
                   "#define FORCED_RAW_BYPASS 0"),
        FIXTURE: ("#define SOURCE_MAPPED_AUTHENTICATED 0",
                  "#define DIRECT_COMPRESSED_HANDOFF 0",
                  "#define FORCED_RAW_BYPASS 0"),
    }
    for source_file, anchors in tracked.items():
        content = source_file.read_text(encoding="utf-8")
        for anchor in anchors:
            require(anchor in content, f"source/gate drift: {source_file.relative_to(ROOT)}: {anchor}")
    return FIXTURE.read_text(encoding="utf-8")


def get_standard(compiler: str) -> str:
    for flag in ("-std=c23", "-std=c2x"):
        candidate = invoke([compiler, flag, "-x", "c", "-fsyntax-only", "-"],
                           stdin="int main(void) { return 0; }\n")
        if candidate.returncode == 0:
            return flag
    raise RuntimeError(f"{compiler}: C23 language mode unavailable")


def compile_fixture(compiler: str, standard: str, source: Path, binary: Path) -> None:
    command = [compiler, standard, "-O1", "-g", "-Wall", "-Wextra", "-Wconversion",
               "-Wshadow", "-Werror", "-fsanitize=address,undefined",
               "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
               "-fno-pie", "-no-pie", "-I", str(FIXTURE.parent),
               str(source), "-o", str(binary)]
    result = invoke(command)
    require(result.returncode == 0,
            f"{compiler}: compile failed for {source.name}: {first_diagnostic(result)}")


def reject_mutation(source: str, name: str, before: str, after: str) -> str:
    occurrences = source.count(before)
    require(occurrences >= 1, f"mutant {name}: missing source anchor")
    # The shared lock guard appears in service and GC: mutate service only.
    require(occurrences == 1 or
            (name == "no-IO-under-lock" and occurrences == 2),
            f"mutant {name}: ambiguous source anchor ({occurrences})")
    return source.replace(before, after, 1)


def run_suite() -> dict[str, object]:
    verify_policy_workflow_push_base()
    original = verify_source_contract()
    outputs: list[str] = []
    with tempfile.TemporaryDirectory(prefix="swapz-round071-agent6-") as directory:
        workspace = Path(directory)
        for name in ("gcc", "clang"):
            compiler = shutil.which(name)
            require(compiler is not None, f"missing required compiler: {name}")
            standard = get_standard(compiler)
            binary = workspace / f"{name}-test"
            compile_fixture(compiler, standard, FIXTURE, binary)
            baseline = invoke([str(binary)])
            require(baseline.returncode == 0 and not baseline.stderr and
                    EXPECTED.fullmatch(baseline.stdout) is not None,
                    f"{name}: baseline failed exit={baseline.returncode} "
                    f"diagnostic={first_diagnostic(baseline)}")
            outputs.append(baseline.stdout)
            print(f"PASS {name} {standard} strict ASan+UBSan: {baseline.stdout.strip()}",
                  flush=True)
            for mutant_index, (mutant_name, original_text, changed_text) in enumerate(MUTANTS):
                mutated = reject_mutation(original, mutant_name, original_text, changed_text)
                mutant_file = workspace / f"{name}-mutant-{mutant_index}.c"
                mutant_file.write_text(mutated, encoding="utf-8")
                compile_fixture(compiler, standard, mutant_file, binary)
                rejected = invoke([str(binary)])
                require(rejected.returncode == 1 and not rejected.stdout and
                        re.fullmatch(r"FIRST_ERROR line=\d+ check=[^\n]+\n", rejected.stderr)
                        is not None,
                        f"{name}: SEMANTIC_MUTANT_SURVIVED {mutant_name} "
                        f"exit={rejected.returncode} diagnostic={first_diagnostic(rejected)}")
            print(f"PASS {name} compiled_executed_mutants={len(MUTANTS)}", flush=True)
    require(outputs[0] == outputs[1], "GCC/Clang result counters disagree")
    return {"phase_a": "BLOCKED", "source_mapped_authenticated": False,
            "direct_compressed_handoff": False, "forced_raw_bypass": False,
            "native_kernel": False, "physical_pressure": False,
            "real_lower_io": False, "actual_upper_ack": False,
            "model_only": True, "compiler_baselines": 2,
            "compiled_executed_semantic_mutants": len(MUTANTS) * 2,
            "model_stdout": outputs[0].strip(), "result": "PASS"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="Optional deterministic host-only JSON result")
    parser.add_argument("--ktap", type=Path, help="Optional HOST model KTAP (not kernel KUnit)")
    arguments = parser.parse_args()
    try:
        result = run_suite()
        if arguments.json is not None:
            arguments.json.parent.mkdir(parents=True, exist_ok=True)
            arguments.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8")
        if arguments.ktap is not None:
            arguments.ktap.parent.mkdir(parents=True, exist_ok=True)
            arguments.ktap.write_text(
                "KTAP version 1\n1..2\n"
                "ok 1 - GCC strict ASan UBSan and compiled C mutants (HOST MODEL)\n"
                "ok 2 - Clang strict ASan UBSan and compiled C mutants (HOST MODEL)\n",
                encoding="utf-8")
        print("PASS round071-agent6 source-header-linked rootless HOST_POLICY_ONLY "
              f"C_mutants={len(MUTANTS) * 2} AUTH=0 PHASE_A=BLOCKED", flush=True)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"FIRST_ERROR round071-agent6 {str(error)[:280]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
