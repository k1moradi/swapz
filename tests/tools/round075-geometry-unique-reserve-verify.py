#!/usr/bin/env python3
"""Regression for two *different* actual authority GC minimum statements.

Run before source-linked C execution. The regression is Python source-scope
validation only and is not counted as a compiled/executed semantic C mutant.
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = ROOT / "tests/tools/round073-swapspace2-geometry-verify.py"
AUTHORITY_PATH = ROOT / "src/kernel/authority.h"

ASSIGNMENT = "reserve = 2U * SWAPZ_SEGMENT_BLOCKS;"
ONE_SEGMENT_ASSIGNMENT = "reserve = 1U * SWAPZ_SEGMENT_BLOCKS;"
COMPARISON = "if (reserve < 2U * SWAPZ_SEGMENT_BLOCKS)"
ONE_SEGMENT_COMPARISON = "if (reserve < 1U * SWAPZ_SEGMENT_BLOCKS)"


def check(condition: bool, context: str) -> None:
    if not condition:
        raise RuntimeError("ROUND075_GEOMETRY_REGRESSION_FIRST_ERROR " + context)


def must_refuse(verifier: object, source: str, anchor: str,
                changed: str, label: str) -> None:
    try:
        verifier.mutate_capacity_statement(source, anchor, changed)
    except RuntimeError as error:
        check(str(error).startswith("ROUND073_GEOMETRY_FIRST_ERROR "), label)
    else:
        check(False, label + ":unexpectedly-admitted")


def main() -> None:
    spec = importlib.util.spec_from_file_location("geometry_source_verifier",
                                                   VERIFIER_PATH)
    check(spec is not None and spec.loader is not None, "source-loader")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = AUTHORITY_PATH.read_text()
    scope = module.extract_function(original, module.CAPACITY_SIGNATURE)
    check(scope.count("2U * SWAPZ_SEGMENT_BLOCKS") == 2,
          "actual-two-reserve-sites")
    check(scope.count(COMPARISON) == 1 and scope.count(ASSIGNMENT) == 1,
          "two-distinct-real-capacity-statements")
    check(len(module.MUTANTS) == 18, "expected-eighteen-semantic-C-mutants")
    check(len({label for label, *_ in module.MUTANTS}) == len(module.MUTANTS),
          "unique-mutant-labels")

    # Both source alterations are exactly one statement, reversible and
    # independently preserve the other legitimate expression.
    for anchor, changed, unrelated, label in (
        (ASSIGNMENT, ONE_SEGMENT_ASSIGNMENT, COMPARISON, "gc-assignment"),
        (COMPARISON, ONE_SEGMENT_COMPARISON, ASSIGNMENT, "gc-comparison"),
    ):
        modified = module.mutate_capacity_statement(original, anchor, changed)
        check(modified != original and modified.count(changed) == 1,
              label + ":one-real-change")
        check(modified.count(unrelated) == 1,
              label + ":other-statement-unaltered")
        check(modified.replace(changed, anchor, 1) == original,
              label + ":source-rest-bit-exact")
        check(module.extract_function(modified, module.CAPACITY_SIGNATURE)
              .count("1U * SWAPZ_SEGMENT_BLOCKS") == 1,
              label + ":one-mutated-constant")

    must_refuse(module, original, "reserve = 9U * SWAPZ_SEGMENT_BLOCKS;",
                ONE_SEGMENT_ASSIGNMENT, "missing-anchor")
    must_refuse(module, original, ASSIGNMENT, ASSIGNMENT,
                "identical-mutation-not-a-test")
    must_refuse(module, original.replace(ASSIGNMENT, ASSIGNMENT + "\n\t" + ASSIGNMENT, 1),
                ASSIGNMENT, ONE_SEGMENT_ASSIGNMENT, "duplicate-actual-statement")
    must_refuse(module, original.replace(COMPARISON, ONE_SEGMENT_COMPARISON, 1),
                ASSIGNMENT, ONE_SEGMENT_ASSIGNMENT, "changed-comparison-source-drift")

    print("ROUND075_GEOMETRY_UNIQUE_GC_RESERVE_SCOPE_PASS "
          "actual_source_occurrences=2 independent_statement_mutations=2 "
          "fail_closed_regression_cases=4 C_mutants_planned=18 "
          "compiler_executions=0_python_scope_only")
    print("ROUND075_GEOMETRY_AUTHORITY_SHA256 "
          + hashlib.sha256(AUTHORITY_PATH.read_bytes()).hexdigest())


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError) as error:
        print(str(error) if str(error).startswith(
            "ROUND075_GEOMETRY_REGRESSION_FIRST_ERROR ") else
            "ROUND075_GEOMETRY_REGRESSION_FIRST_ERROR " + str(error)[:220],
            file=sys.stderr)
        raise SystemExit(1) from None
