#!/usr/bin/env python3
"""Verify actual booted original 63 inherited + 3 NEW registered C KUnit.

Only --result and --kernel-log from original UML are genuine kernel evidence.
--self-test uses fake JSON/KTAP solely as hostile verifier controls.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
import runpy
import unittest

HERE = Path(__file__).resolve().parent
prior = runpy.run_path(
    str(HERE / "round053-original-preunuse-kunit-verify.py"),
    run_name="round053_original_63_verifier_dependency")
SUITE = "swapz_round054_original_release_order_no_authority"
CASES = frozenset((
    "swapz_round054_slot_type_incarnation_kunit",
    "swapz_round054_store_retirement_kunit",
    "swapz_round054_close_never_dispatch_kunit",
))
STAMP = re.compile(r"^\[\s*\d+\.\d+\]\s*")
SUCCESS = re.compile(r"^ok\s+\d+\s+(?:-\s+)?([A-Za-z0-9_]+)(?:\s+#.*)?$")


class OriginalReleaseKUnitError(ValueError):
    """Actual original kernel 66-case C evidence has not been verified."""


def verify(document: object, log: str) -> None:
    try:
        prior["verify"](document, log)
    except prior["OriginalGateKUnitError"] as error:
        raise OriginalReleaseKUnitError("inherited_genuine_original_63:" + str(error)) from error
    if not isinstance(document, dict) or log.count("# Subtest: " + SUITE) != 1:
        raise OriginalReleaseKUnitError("original_new_suite_ktap_not_unique")
    groups = [document]
    matched = []
    visited = 0
    while groups:
        current = groups.pop()
        visited += 1
        if visited > 1000 or not isinstance(current, dict):
            raise OriginalReleaseKUnitError("invalid_original_json_tree")
        if current.get("name") == SUITE:
            matched.append(current)
        children = current.get("sub_groups", [])
        if not isinstance(children, list) or len(children) > 200:
            raise OriginalReleaseKUnitError("invalid_original_subgroups")
        groups.extend(children)
    if len(matched) != 1:
        raise OriginalReleaseKUnitError("missing_or_duplicate_original_new_suite")
    cases = matched[0].get("test_cases")
    if not isinstance(cases, list) or len(cases) != 3:
        raise OriginalReleaseKUnitError("new_original_C_case_count_not_three")
    observed = set()
    for case in cases:
        if not isinstance(case, dict) or case.get("name") not in CASES or \
                case["name"] in observed or case.get("status") != "PASS":
            raise OriginalReleaseKUnitError("new_actual_kernel_C_case_not_pass")
        observed.add(case["name"])
    if observed != CASES:
        raise OriginalReleaseKUnitError("incomplete_new_original_C_cases")
    totals = matched[0].get("misc")
    for name, expected in {
        "tests": 3, "passed": 3, "failed": 0, "skipped": 0,
        "crashed": 0, "errors": 0,
    }.items():
        if not isinstance(totals, dict) or type(totals.get(name)) is not int or \
                totals[name] != expected:
            raise OriginalReleaseKUnitError("original_new_suite_total:" + name)
    counts = {}
    for raw in log.splitlines():
        line = STAMP.sub("", raw).strip()
        match = SUCCESS.fullmatch(line)
        if match and match.group(1) in CASES:
            if "#" in line:
                raise OriginalReleaseKUnitError("new_original_C_case_KTAP_directive")
            counts[match.group(1)] = counts.get(match.group(1), 0) + 1
    if set(counts) != CASES or any(value != 1 for value in counts.values()):
        raise OriginalReleaseKUnitError("real_original_ktap_case_missing_duplicate")
    if re.search(r"(?i)(?:kernel panic|BUG: KASAN:|UBSAN:|not ok\s+\d+\s+(?:-\s+)?swapz_round054)", log):
        raise OriginalReleaseKUnitError("original_boot_kernel_negative_marker")


def sample() -> tuple[dict, str]:
    document, log = prior["sample"]()  # SYNTHETIC verifier self-test only.
    ordered_names = sorted(CASES)
    document["sub_groups"].append({
        "name": SUITE, "sub_groups": [],
        "test_cases": [{"name": name, "status": "PASS"} for name in ordered_names],
        "misc": {"tests": 3, "passed": 3, "failed": 0, "skipped": 0,
                 "crashed": 0, "errors": 0},
    })
    log += "[    0.091] # Subtest: " + SUITE + "\n"
    log += "".join(
        f"[    0.092]     ok {index} {name}\n"
        for index, name in enumerate(ordered_names, 1)
    )
    return document, log


class KUnitHostileTests(unittest.TestCase):
    def test_synthetic_baseline_is_verifier_only(self) -> None:
        verify(*sample())

    def test_independent_new_json_ktap_hostiles(self) -> None:
        document, log = sample()
        corrupt = []
        for status in ("FAIL", "SKIP", "ERROR", "CRASHED"):
            mutant = copy.deepcopy(document)
            mutant["sub_groups"][-1]["test_cases"][0]["status"] = status
            corrupt.append((mutant, log))
        for key, value in (("tests", 4), ("passed", 2), ("failed", 1),
                           ("skipped", 1), ("crashed", 1), ("errors", 1)):
            mutant = copy.deepcopy(document)
            mutant["sub_groups"][-1]["misc"][key] = value
            corrupt.append((mutant, log))
        mutant = copy.deepcopy(document)
        mutant["sub_groups"][-1]["test_cases"].pop()
        corrupt.append((mutant, log))
        mutant = copy.deepcopy(document)
        mutant["sub_groups"][-1]["test_cases"][0]["name"] = "fabricated_source_owner"
        corrupt.append((mutant, log))
        mutant = copy.deepcopy(document)
        mutant["sub_groups"].append(copy.deepcopy(mutant["sub_groups"][-1]))
        corrupt.append((mutant, log))
        mutant = copy.deepcopy(document)
        mutant["sub_groups"][0]["test_cases"][0]["status"] = "FAIL"
        corrupt.append((mutant, log))
        first = sorted(CASES)[0]
        exact = next(line for line in log.splitlines() if "ok 1 " + first in line)
        corrupt.extend((
            (copy.deepcopy(document), log.replace(exact, "", 1)),
            (copy.deepcopy(document), log + exact + "\n"),
            (copy.deepcopy(document), log.replace("ok 1 " + first, "not ok 1 " + first, 1)),
            (copy.deepcopy(document), log.replace("ok 1 " + first, "ok 1 fabricated_", 1)),
            (copy.deepcopy(document), log + "Kernel panic - not syncing\n"),
        ))
        corrupt.append((copy.deepcopy(document), log.replace(exact, exact + " # SKIP forged", 1)))
        self.assertEqual(len(corrupt), 20)
        for index, (tree, trace) in enumerate(corrupt):
            with self.subTest(hostile=index):
                self.assertNotEqual((tree, trace), (document, log))
                with self.assertRaises(OriginalReleaseKUnitError):
                    verify(tree, trace)


def bounded(path: Path, maximum: int) -> str:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise OriginalReleaseKUnitError("real_original_uml_evidence_missing_or_oversized")
    return path.read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--result", type=Path)
    parser.add_argument("--kernel-log", type=Path)
    args = parser.parse_args()
    if args.self_test:
        tests = unittest.defaultTestLoader.loadTestsFromTestCase(KUnitHostileTests)
        return 0 if unittest.TextTestRunner(verbosity=2).run(tests).wasSuccessful() else 1
    if args.result is None or args.kernel_log is None:
        parser.error("REAL ORIGINAL --result and --kernel-log required")
    try:
        verify(json.loads(bounded(args.result, 512 * 1024)),
               bounded(args.kernel_log, 2 * 1024 * 1024))
    except (OriginalReleaseKUnitError, OSError, UnicodeError, ValueError) as error:
        print("ROUND054_REAL_ORIGINAL_66_KUNIT_BLOCKED first_error=" + str(error))
        return 2
    print("ROUND054_ORIGINAL_UML_66_REGISTERED_C_KUNIT_JSON_KTAP_PASS "
          "INHERITED_63=PASS NEW_C_RELEASE_3=PASS "
          "ORIGINAL_COUNTED_SLOT_HELD_ACROSS_ASYNC=NO "
          "SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
