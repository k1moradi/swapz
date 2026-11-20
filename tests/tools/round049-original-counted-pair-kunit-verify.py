#!/usr/bin/env python3
"""Verify actual booted original 55+2 KUnit JSON AND KTAP (NO_AUTH).

Self-test samples are synthetic and NEVER substitute for original UML boot.
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
    "round045_original_genuine_verifier",
    HERE / "round045-original-stored-bio-scope-verify.py")
assert SPEC and SPEC.loader
prior = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prior)

SUITE = "swapz_round049_original_locked_folio_counted_pair_no_authority"
CASES = frozenset((
    "swapz_round049_missing_original_owner_kunit",
    "swapz_round049_unlocked_uncached_folio_kunit",
))
STAMP = re.compile(r"^\[\s*\d+\.\d+\]\s*")
SUCCESS = re.compile(r"^ok\s+\d+\s+(?:-\s+)?([A-Za-z0-9_]+)(?:\s+#.*)?$")


class OriginalCountedPairKUnitError(ValueError):
    """The actual original C KUnit evidence is missing or inconsistent."""


def verify(document: object, log: str) -> None:
    try:
        prior.verify(document, log)
    except prior.OriginalStoredBioScopeEvidenceError as error:
        raise OriginalCountedPairKUnitError("inherited_real_original_55:" + str(error)) from error
    if not isinstance(document, dict) or log.count("# Subtest: " + SUITE) != 1:
        raise OriginalCountedPairKUnitError("missing_or_duplicate_real_original_suite_ktap")
    groups = [document]
    found: list[dict] = []
    checked = 0
    while groups:
        current = groups.pop()
        checked += 1
        if checked > 1000 or not isinstance(current, dict):
            raise OriginalCountedPairKUnitError("malformed_original_json_tree")
        if current.get("name") == SUITE:
            found.append(current)
        children = current.get("sub_groups", [])
        if not isinstance(children, list) or len(children) > 200:
            raise OriginalCountedPairKUnitError("malformed_original_json_groups")
        groups.extend(children)
    if len(found) != 1:
        raise OriginalCountedPairKUnitError("missing_or_duplicate_original_counted_suite")
    cases = found[0].get("test_cases")
    if not isinstance(cases, list) or len(cases) != 2:
        raise OriginalCountedPairKUnitError("new_real_original_cases_not_two")
    names: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or case.get("name") not in CASES or \
                case.get("name") in names or case.get("status") != "PASS":
            raise OriginalCountedPairKUnitError("new_original_case_failed_or_forged")
        names.add(case["name"])
    if names != CASES:
        raise OriginalCountedPairKUnitError("new_original_case_set_incomplete")
    totals = found[0].get("misc")
    if not isinstance(totals, dict):
        raise OriginalCountedPairKUnitError("new_real_original_suite_counts_missing")
    for key, expected in {
        "tests": 2, "passed": 2, "failed": 0, "skipped": 0,
        "crashed": 0, "errors": 0,
    }.items():
        if type(totals.get(key)) is not int or totals[key] != expected:
            raise OriginalCountedPairKUnitError("new_original_suite_count:" + key)
    occurred: dict[str, int] = {}
    for raw in log.splitlines():
        line = STAMP.sub("", raw).strip()
        match = SUCCESS.fullmatch(line)
        if match and match.group(1) in CASES:
            name = match.group(1)
            occurred[name] = occurred.get(name, 0) + 1
    if set(occurred) != CASES or any(count != 1 for count in occurred.values()):
        raise OriginalCountedPairKUnitError("new_actual_original_ktap_missing_duplicate")
    if re.search(
        r"(?i)(?:kernel panic|BUG: KASAN:|UBSAN:|not ok\s+\d+\s+(?:-\s+)?swapz_round049)",
        log,
    ):
        raise OriginalCountedPairKUnitError("original_kernel_negative_failure_marker")


def sample() -> tuple[dict, str]:
    document, log = prior.sample()  # SELF-TEST ONLY, not real kernel evidence.
    ordered = sorted(CASES)
    document["sub_groups"].append({
        "name": SUITE, "sub_groups": [],
        "test_cases": [{"name": name, "status": "PASS"} for name in ordered],
        "misc": {"tests": 2, "passed": 2, "failed": 0, "skipped": 0,
                 "crashed": 0, "errors": 0},
    })
    log += "[    0.050] # Subtest: " + SUITE + "\n"
    log += "".join(
        f"[    0.051]     ok {index} {name}\n"
        for index, name in enumerate(ordered, 1)
    )
    return document, log


class SourceHostileVerifierTests(unittest.TestCase):
    def test_known_self_test_sample(self) -> None:
        verify(*sample())

    def test_23_genuinely_changed_hostile_controls(self) -> None:
        baseline, log = sample()
        hostile: list[tuple[dict, str]] = []
        for status in ("FAIL", "SKIP", "ERROR", "CRASHED"):
            document = copy.deepcopy(baseline)
            document["sub_groups"][-1]["test_cases"][0]["status"] = status
            hostile.append((document, log))
        for key, value in (
            ("tests", 3), ("passed", 1), ("failed", 1),
            ("skipped", 1), ("crashed", 1), ("errors", 1),
        ):
            document = copy.deepcopy(baseline)
            document["sub_groups"][-1]["misc"][key] = value
            hostile.append((document, log))
        document = copy.deepcopy(baseline)
        document["sub_groups"][-1]["test_cases"].append(
            copy.deepcopy(document["sub_groups"][-1]["test_cases"][0]))
        hostile.append((document, log))
        document = copy.deepcopy(baseline)
        document["sub_groups"][-1]["test_cases"][0]["name"] = "fabricated_original"
        hostile.append((document, log))
        document = copy.deepcopy(baseline)
        document["sub_groups"].append(copy.deepcopy(document["sub_groups"][-1]))
        hostile.append((document, log))
        document = copy.deepcopy(baseline)
        document["sub_groups"][0]["test_cases"][0]["status"] = "FAIL"
        hostile.append((document, log))
        first = sorted(CASES)[0]
        for mutated in (
            log.replace("# Subtest: " + SUITE, "# Subtest: substituted", 1),
            log.replace("ok 1 " + first, "not ok 1 " + first, 1),
            log.replace("ok 1 " + first, "ok 1 fabricated_case", 1),
            log + next(line for line in log.splitlines() if "ok 1 " + first in line) + "\n",
            log + "Kernel panic - not syncing\n",
            log + "BUG: KASAN: use-after-free\n",
            log + "UBSAN: signed-integer-overflow\n",
            log.replace("ok 2 swapz_round049_", "not ok 2 swapz_round049_", 1),
            log.replace("ok 2 swapz_round049_", "ok 2 forged_", 1),
        ):
            hostile.append((copy.deepcopy(baseline), mutated))
        self.assertEqual(len(hostile), 23)
        for index, (document, trace) in enumerate(hostile):
            with self.subTest(index=index):
                self.assertNotEqual((document, trace), (baseline, log),
                                    "hostile verifier fixture was unchanged")
                with self.assertRaises(OriginalCountedPairKUnitError):
                    verify(document, trace)


def bounded(path: Path, max_bytes: int) -> str:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= max_bytes:
        raise OriginalCountedPairKUnitError("original_evidence_missing_or_oversized")
    return path.read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--result", type=Path)
    parser.add_argument("--kernel-log", type=Path)
    args = parser.parse_args()
    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(SourceHostileVerifierTests)
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    if args.result is None or args.kernel_log is None:
        parser.error("--result and --kernel-log are required")
    try:
        verify(json.loads(bounded(args.result, 512 * 1024)),
               bounded(args.kernel_log, 2 * 1024 * 1024))
    except (OriginalCountedPairKUnitError, OSError, UnicodeError, ValueError) as error:
        print("ROUND049_GENUINE_ORIGINAL_COUNTED_PAIR_KUNIT_BLOCKED first_error=" + str(error))
        return 2
    print("ROUND049_REAL_ORIGINAL_UML_KUNIT_PASS inherited_original=55 "
          "new_real_refusal_cases=2 total_original=57 "
          "REAL_COUNTED_PAIR_IN_PRESSURE=NOT_RUN EXTERNAL_SLOT_OWNER=NO_AUTH")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
