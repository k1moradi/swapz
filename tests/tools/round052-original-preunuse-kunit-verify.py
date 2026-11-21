#!/usr/bin/env python3
"""Require TRUE original booted 57+3 kernel C KUnit JSON AND KTAP.

Self-test builds only synthetic negative-control fixtures. It is not a
real counted swap slot or evidence of swapoff cancellation under pressure.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import re
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "round049_actual_original_57_verifier",
    HERE / "round049-original-counted-pair-kunit-verify.py")
assert SPEC and SPEC.loader
previous = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(previous)

SUITE = "swapz_round052_original_preunuse_cancel_negative_no_authority"
CASES = frozenset((
    "swapz_round052_no_registered_source_owner_kunit",
    "swapz_round052_actual_uncached_folio_refused_kunit",
    "swapz_round052_duplicate_late_cancel_refused_kunit",
))
STAMP = re.compile(r"^\[\s*\d+\.\d+\]\s*")
SUCCESS = re.compile(r"^ok\s+\d+\s+(?:-\s+)?([A-Za-z0-9_]+)(?:\s+#.*)?$")


class ActualOriginalPreUnuseKUnitError(ValueError):
    """True original kernel 60-case KUnit source evidence was not established."""


def verify(document: object, log: str) -> None:
    try:
        previous.verify(document, log)
    except previous.OriginalCountedPairKUnitError as error:
        raise ActualOriginalPreUnuseKUnitError(
            "inherited_genuine_booted_57:" + str(error)) from error
    if not isinstance(document, dict) or log.count("# Subtest: " + SUITE) != 1:
        raise ActualOriginalPreUnuseKUnitError("real_original_new_suite_ktap_not_unique")
    groups = [document]
    matched: list[dict] = []
    visited = 0
    while groups:
        group = groups.pop()
        visited += 1
        if visited > 1000 or not isinstance(group, dict):
            raise ActualOriginalPreUnuseKUnitError("invalid_original_json_tree")
        if group.get("name") == SUITE:
            matched.append(group)
        nested = group.get("sub_groups", [])
        if not isinstance(nested, list) or len(nested) > 200:
            raise ActualOriginalPreUnuseKUnitError("invalid_original_json_subgroups")
        groups.extend(nested)
    if len(matched) != 1:
        raise ActualOriginalPreUnuseKUnitError("new_suite_missing_or_duplicate")
    cases = matched[0].get("test_cases")
    if not isinstance(cases, list) or len(cases) != len(CASES):
        raise ActualOriginalPreUnuseKUnitError("new_original_case_count_not_three")
    observed: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or case.get("name") not in CASES or \
                case.get("name") in observed or case.get("status") != "PASS":
            raise ActualOriginalPreUnuseKUnitError("new_real_original_case_not_pass")
        observed.add(case["name"])
    if observed != CASES:
        raise ActualOriginalPreUnuseKUnitError("new_real_original_case_identity")
    counters = matched[0].get("misc")
    if not isinstance(counters, dict):
        raise ActualOriginalPreUnuseKUnitError("new_original_case_totals_missing")
    for field, expected in {
        "tests": 3, "passed": 3, "failed": 0, "skipped": 0,
        "crashed": 0, "errors": 0,
    }.items():
        if type(counters.get(field)) is not int or counters[field] != expected:
            raise ActualOriginalPreUnuseKUnitError("original_case_totals:" + field)
    ktap_counts: dict[str, int] = {}
    for raw in log.splitlines():
        line = STAMP.sub("", raw).strip()
        matched_line = SUCCESS.fullmatch(line)
        if matched_line and matched_line.group(1) in CASES:
            case_name = matched_line.group(1)
            ktap_counts[case_name] = ktap_counts.get(case_name, 0) + 1
    if set(ktap_counts) != CASES or any(n != 1 for n in ktap_counts.values()):
        raise ActualOriginalPreUnuseKUnitError("genuine_ktap_case_missing_or_duplicate")
    if re.search(
        r"(?i)(?:kernel panic|BUG: KASAN:|UBSAN:|not ok\s+\d+\s+(?:-\s+)?swapz_round052)",
        log,
    ):
        raise ActualOriginalPreUnuseKUnitError("real_original_kernel_negative_marker")


def sample() -> tuple[dict, str]:
    document, log = previous.sample()  # SELF-TEST ONLY; never kernel evidence.
    names = sorted(CASES)
    document["sub_groups"].append({
        "name": SUITE,
        "sub_groups": [],
        "test_cases": [{"name": name, "status": "PASS"} for name in names],
        "misc": {"tests": 3, "passed": 3, "failed": 0, "skipped": 0,
                 "crashed": 0, "errors": 0},
    })
    log += "[    0.080] # Subtest: " + SUITE + "\n"
    log += "".join(
        f"[    0.081]     ok {index} {name}\n"
        for index, name in enumerate(names, 1)
    )
    return document, log


class NewSourceVerifierHostiles(unittest.TestCase):
    def test_synthetic_baseline_rejected_as_only_real_evidence(self) -> None:
        # The generated sample is used only inside --self-test, NEVER as
        # the --result/--kernel-log files in actual original UML job.
        verify(*sample())

    def test_twenty_distinct_corrupt_actual_case_controls(self) -> None:
        document, log = sample()
        changed: list[tuple[dict, str]] = []
        for status in ("FAIL", "SKIP", "ERROR", "CRASHED"):
            mutant = copy.deepcopy(document)
            mutant["sub_groups"][-1]["test_cases"][0]["status"] = status
            changed.append((mutant, log))
        for field, value in (
            ("tests", 4), ("passed", 2), ("failed", 1),
            ("skipped", 1), ("crashed", 1), ("errors", 1),
        ):
            mutant = copy.deepcopy(document)
            mutant["sub_groups"][-1]["misc"][field] = value
            changed.append((mutant, log))
        mutant = copy.deepcopy(document)
        mutant["sub_groups"][-1]["test_cases"].append(
            copy.deepcopy(mutant["sub_groups"][-1]["test_cases"][0]))
        changed.append((mutant, log))
        mutant = copy.deepcopy(document)
        mutant["sub_groups"][-1]["test_cases"][0]["name"] = "fabricated_owner"
        changed.append((mutant, log))
        mutant = copy.deepcopy(document)
        mutant["sub_groups"].append(copy.deepcopy(mutant["sub_groups"][-1]))
        changed.append((mutant, log))
        mutant = copy.deepcopy(document)
        mutant["sub_groups"].pop()
        changed.append((mutant, log))
        first = sorted(CASES)[0]
        first_line = next(line for line in log.splitlines() if "ok 1 " + first in line)
        changed.extend((
            (copy.deepcopy(document), log.replace(first_line, "", 1)),
            (copy.deepcopy(document), log + first_line + "\n"),
            (copy.deepcopy(document), log.replace("ok 1 " + first,
                                                   "ok 1 fake_", 1)),
            (copy.deepcopy(document), log.replace("ok 1 " + first,
                                                   "not ok 1 " + first, 1)),
            (copy.deepcopy(document), log + "Kernel panic - not syncing\n"),
        ))
        mutant = copy.deepcopy(document)
        mutant["sub_groups"][0]["test_cases"][0]["status"] = "FAIL"
        changed.append((mutant, log))
        self.assertEqual(len(changed), 20)
        for number, (tree, trace) in enumerate(changed):
            with self.subTest(hostile=number):
                self.assertNotEqual((tree, trace), (document, log))
                with self.assertRaises(ActualOriginalPreUnuseKUnitError):
                    verify(tree, trace)


def bounded(path: Path, max_bytes: int) -> str:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= max_bytes:
        raise ActualOriginalPreUnuseKUnitError("real_original_evidence_missing")
    return path.read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--result", type=Path)
    parser.add_argument("--kernel-log", type=Path)
    args = parser.parse_args()
    if args.self_test:
        tests = unittest.defaultTestLoader.loadTestsFromTestCase(NewSourceVerifierHostiles)
        return 0 if unittest.TextTestRunner(verbosity=2).run(tests).wasSuccessful() else 1
    if args.result is None or args.kernel_log is None:
        parser.error("--result and --kernel-log required for REAL ORIGINAL boot evidence")
    try:
        verify(json.loads(bounded(args.result, 512 * 1024)),
               bounded(args.kernel_log, 2 * 1024 * 1024))
    except (ActualOriginalPreUnuseKUnitError, OSError, UnicodeError, ValueError) as error:
        print("ROUND052_REAL_ORIGINAL_60_KUNIT_BLOCKED first_error=" + str(error))
        return 2
    print("ROUND052_GENUINE_ORIGINAL_UML_60_C_KUNIT_JSON_KTAP_PASS "
          "inherited_57=PASS new_negative_3=PASS "
          "TRUE_COUNTED_SOURCE_OWNER=NOT_ACQUIRED PREUNUSE_HOOK=ABSENT "
          "SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
