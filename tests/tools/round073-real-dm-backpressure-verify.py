#!/usr/bin/env python3
"""Agent11 original-DM-source-audited, compiled-header-linked HOST model.

Every mutant has a unique semantic change to the C model and is compiled and
executed separately with both GCC and Clang under ASan+UBSan. No Linux kernel
or original MM code is run. Genuine DM worker text is audited, not linked.
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
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/runtime/native/fixtures/round073-real-dm-backpressure.c"
DM = ROOT / "src/kernel/dm-target.c"
AUTHORITY = ROOT / "src/kernel/authority.h"
WINDOW = ROOT / "src/kernel/window-policy.h"
IMPORT = ROOT / "src/kernel/zswap-import-codec.h"
DIRECT = ROOT / "src/kernel/zswap-direct-handoff.h"

# Distinct from Round071 Agent6's synthetic 128-event/48-mutant baseline.
# Each independently compiled negative must fail with a model FIRST_ERROR.
MUTANTS = (
    ("external-natural-only", "if (!source->natural)", "if (false)"),
    ("source-lease", "if (!source->source_lease)", "if (false)"),
    ("source-generation", "if (source->generation != source->observed_generation)",
     "if (false)"),
    ("original-codec-identity", "source->codec != SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC)",
     "source->codec != 99U)"),
    ("compressed-byte-bound", "if (source->bytes == 0U || source->bytes > SWAPZ_MAX_COMPRESSED)",
     "if (false)"),
    ("raw-must-be-4096", "} else if (source->bytes != SWAPZ_BLOCK_BYTES || source->codec != 0U) {",
     "} else if (source->bytes > SWAPZ_BLOCK_BYTES || source->codec != 0U) {"),
    ("duplicate-owned-ticket", "if (queue_contains(queue, source->slot) ||",
     "if ((false && queue_contains(queue, source->slot)) ||"),
    ("slot-ceiling", "if (queue->count == QUEUE_SLOTS)", "if (false)"),
    ("byte-ceiling", "if (source->bytes > PENDING_LIMIT - queue->owned_bytes)",
     "if (false)"),
    ("source-copy", "memcpy(destination->payload, source->payload, source->bytes);",
     "memcpy(destination->payload, source->payload, source->bytes - 1U);"),
    ("lower-busy", "if (queue->lower_busy && item->kind != READ)", "if (false)"),
    ("fifo-service", "struct owned_item *item = &queue->pending[queue->head];",
     "struct owned_item *item = &queue->pending[(queue->head + 1U) % QUEUE_SLOTS];"),
    ("first-lower-error", "completion->status = lower_error;",
     "completion->status = 0;"),
    ("read-fairness", "if (item->kind == READ)\n        ++queue->read_completed;",
     "if (false)\n        ++queue->read_completed;"),
    ("no-secondary-pressure", "queue->secondary_pressure_calls += 0U;",
     "queue->secondary_pressure_calls += 1U;"),
    ("no-recompression", "queue->recompression_calls += 0U;",
     "queue->recompression_calls += 1U;"),
    ("teardown-closure", "if (queue->closed)", "if (false)"),
)


def require(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def run(command: list[str], *, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, input=stdin, text=True, capture_output=True, check=False,
        timeout=90, env={
            **os.environ,
            "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
            "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
        },
    )


def first_error(result: subprocess.CompletedProcess[str]) -> str:
    """Report the first actual compiler error, not merely its enclosing function."""
    lines = (result.stderr or result.stdout or "no compiler/fixture diagnostic").splitlines()
    return next((line.strip()[:300] for line in lines if "error:" in line),
                lines[0][:300])


def verify_real_sources() -> tuple[str, dict[str, str]]:
    sources = {path.name: path.read_text(encoding="utf-8")
               for path in (DM, AUTHORITY, WINDOW, IMPORT, DIRECT)}
    dm = sources[DM.name]
    anchors = (
        "#define SWAPZ_WORK_QUANTUM_BIOS 64U",
        "#define SWAPZ_WRITE_PIPELINE_DEPTH 1U",
        "struct list_head incoming;",
        "struct mutex ordered_owner;",
        "list_add_tail(&entry->list, &ctx->incoming);",
        "list_splice_init(&ctx->incoming, &local);",
        "remaining -= processed_bios;",
        "if (!ctx->accepting) {",
        "if (queue->lower_busy",  # verifier-side marker replaced below
        "drain_workqueue(ctx->workqueue);",
    )
    for anchor in anchors:
        if anchor == "if (queue->lower_busy":
            continue  # model-only lower I/O busy, never attributed to real DM
        require(anchor in dm, f"genuine DM worker/ingress anchor drift: {anchor}")
    require("SWAPZ_SOURCE_WORK_QUANTUM_BIOS" in FIXTURE.read_text(encoding="utf-8"),
            "missing compiled DM quantum binding")
    require("#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U" in sources[IMPORT.name],
            "dormant import gate changed")
    require("#define SWAPZ_DIRECT_HANDOFF_PRODUCTION_ENABLED 0U" in sources[DIRECT.name],
            "direct handoff gate changed")
    require("#define SWAPZ_LINUX_SWAP_HEADER_BLOCKS 1U" in sources[AUTHORITY.name],
            "physical first-page source guard changed")
    require("static inline int swapz_authority_capacity_window(" in sources[AUTHORITY.name],
            "genuine capacity function absent")
    require("static inline int swapz_window_read_independent(" in sources[WINDOW.name],
            "genuine independent READ predicate absent")
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
              for path in (DM, AUTHORITY, WINDOW, IMPORT, DIRECT)}
    return "64U", hashes


def compiler_standard(compiler: str) -> str:
    for standard in ("-std=c23", "-std=c2x"):
        result = run([compiler, standard, "-x", "c", "-fsyntax-only", "-"],
                     stdin="int main(void) { return 0; }\n")
        if result.returncode == 0:
            return standard
    raise RuntimeError(f"{compiler}: C23/C2x unavailable")


def compile_and_run(compiler: str, standard: str, source: Path,
                    binary: Path, include: Path) -> subprocess.CompletedProcess[str]:
    built = run([compiler, standard, "-O1", "-g", "-Wall", "-Wextra",
                 "-Wconversion", "-Wshadow", "-Werror", "-pedantic",
                 "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                 "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                 "-I", str(include), "-I", str(FIXTURE.parent), str(source), "-o", str(binary)])
    require(built.returncode == 0, f"{compiler} compile {source.name}: {first_error(built)}")
    return run([str(binary)])


def evaluate() -> dict[str, object]:
    quantum, source_hashes = verify_real_sources()
    baseline_text = FIXTURE.read_text(encoding="utf-8")
    results: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="swapz-round073-agent11-") as temporary:
        scratch = Path(temporary)
        (scratch / "round073-source-quantum.h").write_text(
            f"#ifndef SWAPZ_ROUND073_SOURCE_QUANTUM_H\n"
            f"#define SWAPZ_ROUND073_SOURCE_QUANTUM_H\n"
            f"#define SWAPZ_SOURCE_WORK_QUANTUM_BIOS {quantum}\n"
            f"#endif\n", encoding="utf-8")
        for compiler_name in ("gcc", "clang"):
            compiler = shutil.which(compiler_name)
            require(compiler is not None, f"compiler unavailable: {compiler_name}")
            standard = compiler_standard(compiler)
            baseline = compile_and_run(compiler, standard, FIXTURE,
                                       scratch / f"{compiler_name}-base", scratch)
            require(baseline.returncode == 0 and
                    baseline.stdout.startswith("PASS round073-agent11 checks=") and
                    "model_only=1" in baseline.stdout,
                    f"{compiler_name} baseline: {first_error(baseline)}")
            killed = []
            for index, (name, before, after) in enumerate(MUTANTS):
                require(baseline_text.count(before) == 1,
                        f"{name}: missing or ambiguous C semantic anchor")
                changed = baseline_text.replace(before, after, 1)
                source = scratch / f"mutant-{compiler_name}-{index:02d}.c"
                # An independent C translation unit; the source directory is
                # an include path for unchanged repository-relative headers.
                source.write_text(changed, encoding="utf-8")
                result = compile_and_run(
                    compiler, standard, source,
                    scratch / f"mutant-{compiler_name}-{index:02d}",
                    scratch)
                # Only a successfully built and EXECUTED C program returning
                # its own directed FIRST_ERROR kills a semantic mutant.
                # A compiler diagnostic or sanitizer abort is a suite failure.
                require(result.returncode == 1 and
                        result.stderr.startswith("FIRST_ERROR line=") and
                        " invariant=" in result.stderr,
                        f"{compiler_name} mutant {name} did not fail a directed "
                        f"model invariant: {first_error(result)}")
                if name == "duplicate-owned-ticket":
                    require("invariant=admit(&model, &event) == -EALREADY" in
                            result.stderr,
                            f"{compiler_name}: duplicate-ticket guard did not "
                            f"detect mutant 06: {first_error(result)}")
                killed.append(name)
            results[compiler_name] = {
                "standard": standard, "baseline": "PASS",
                "mutants_compiled": len(killed), "mutants_executed": len(killed),
                "mutants_rejected": len(killed),
                "names": killed,
                "baseline_output": baseline.stdout.strip(),
            }
    return {
        "status": "PASS_HOST_MODEL_ONLY",
        "source_claim": "original DM anchors audited; production headers compiled; scheduling model only",
        "dm_original_kernel_executed": False,
        "natural_mm_evictions_executed": False,
        "actual_compressed_handoff_executed": False,
        "model_slot_limit": 16, "model_owned_bytes_limit": 32768,
        "compilers": results, "source_sha256": source_hashes,
        "first_error": None, "phase_a": "BLOCKED",
        "source_mapped_authenticated": 0,
        "direct_compressed_handoff": "DISABLED",
        "forced_raw_bypass": "DISABLED",
        "linux_mm_pressure_owner": "external-only",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", required=True, type=Path)
    parser.add_argument("--ktap", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = evaluate()
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as failure:
        print(f"FIRST_ERROR round073-agent11: {str(failure)[:360]}", flush=True)
        return 1
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.ktap.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    args.ktap.write_text("KTAP version 1\n1..2\n"
                         "ok 1 - GCC C23/C2x ASan+UBSan baseline and 17 mutants\n"
                         "ok 2 - Clang C23/C2x ASan+UBSan baseline and 17 mutants\n",
                         encoding="utf-8")
    print("PASS HOST_MODEL_ONLY GCC=17/17 Clang=17/17 "
          "production_DM_anchors=SOURCE_AUDITED original_linux_native=NOT_RUN "
          "PHASE_A=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
