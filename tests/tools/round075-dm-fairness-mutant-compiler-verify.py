#!/usr/bin/env python3
"""Round075 Agent11 rootless mutant06 strict-compiler semantic regression.

Imports the EXISTING Round073 model compiler/headers and mutation data.
Must build AND execute, then observe the duplicate-owned-ticket invariant.
A compiler error is a failure of this check, never a semantic mutant kill.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[2]
VERIFIER = ROOT / "tests/tools/round073-real-dm-backpressure-verify.py"


def qualify() -> dict[str, object]:
    existing = runpy.run_path(str(VERIFIER), run_name="round075_agent11_import")
    mutations = existing["MUTANTS"]
    if len(mutations) != 17 or mutations[6][0] != "duplicate-owned-ticket":
        raise RuntimeError("mutation list/index changed: expected 17 and mutant06")
    name, before, after = mutations[6]
    fixture_path = existing["FIXTURE"]
    source = fixture_path.read_text(encoding="utf-8")
    if source.count(before) != 1 or after != (
        "if ((false && queue_contains(queue, source->slot)) ||"):
        raise RuntimeError("mutant06 duplicate-owned condition not scoped/parenthesized")
    mutated = source.replace(before, after, 1)
    if "if (queue_contains(queue, source->slot) ||" not in source:
        raise RuntimeError("original duplicate-ticket protection unexpectedly removed")
    if source.count("REQUIRE(admit(&model, &event) == -EALREADY);") < 2:
        raise RuntimeError("duplicate pending/committed model assertions missing")
    if "event.generation = 8U;" not in source or (
        "REQUIRE(model.completions[199U].status == -ECANCELED);" not in source):
        raise RuntimeError("stale-incarnation or teardown cancellation assertion missing")
    existing["verify_real_sources"]()
    executed: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="swapz-round075-agent11-") as tempdir:
        scratch = Path(tempdir)
        (scratch / "round073-source-quantum.h").write_text(
            "#ifndef SWAPZ_ROUND073_SOURCE_QUANTUM_H\n"
            "#define SWAPZ_ROUND073_SOURCE_QUANTUM_H\n"
            "#define SWAPZ_SOURCE_WORK_QUANTUM_BIOS 64U\n"
            "#endif\n", encoding="utf-8")
        mutant_source = scratch / "mutant06.c"
        mutant_source.write_text(mutated, encoding="utf-8")
        for compiler_name in ("gcc", "clang"):
            compiler = shutil.which(compiler_name)
            if compiler is None:
                raise RuntimeError(f"compiler missing: {compiler_name}")
            standard = existing["compiler_standard"](compiler)
            baseline = existing["compile_and_run"](
                compiler, standard, fixture_path, scratch / f"{compiler_name}-base", scratch)
            if baseline.returncode != 0 or not baseline.stdout.startswith("PASS round073-agent11"):
                raise RuntimeError(
                    f"{compiler_name} baseline: {existing['first_error'](baseline)}")
            result = existing["compile_and_run"](
                compiler, standard, mutant_source,
                scratch / f"{compiler_name}-mutant06", scratch)
            expected = "invariant=admit(&model, &event) == -EALREADY"
            if result.returncode != 1 or (
                not result.stderr.startswith("FIRST_ERROR line=")
            ) or expected not in result.stderr:
                raise RuntimeError(f"{compiler_name} {name}: expected semantic "
                                   f"refusal, got {existing['first_error'](result)}")
            executed[compiler_name] = {
                "standard": standard,
                "baseline": "PASS_HOST_MODEL_ONLY",
                "mutant06_compiled": 1,
                "mutant06_executed": 1,
                "mutant06_semantic_kills": 1,
                "semantic_guard": expected,
            }
    return {
        "status": "PASS_HOST_MODEL_ONLY",
        "mutation": name,
        "compilers": executed,
        "model_not_product": True,
        "original_native": "NOT_RUN",
        "phase_a": "BLOCKED",
        "source_mapped_authenticated": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        result = qualify()
    except (RuntimeError, OSError) as failure:
        print(f"ROUND075_AGENT11_FIRST_ERROR {str(failure)[:400]}")
        return 1
    arguments.json.parent.mkdir(parents=True, exist_ok=True)
    arguments.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")
    print("PASS HOST_MODEL_ONLY mutant06 GCC=compiled/executed/semantic-kill "
          "Clang=compiled/executed/semantic-kill PHASE_A=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
