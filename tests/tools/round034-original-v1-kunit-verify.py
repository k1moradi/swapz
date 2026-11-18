#!/usr/bin/env python3
"""Fail-closed Round034 real original CONFIG_ZSWAP=y UML JSON+KTAP verifier."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
import unittest

SUITE = "swapz_round025_sideband_compiler_only"
OLD = frozenset((
    "swapz_ci_clone_lifetime_kunit",
    "swapz_ci_split_lifetime_kunit",
    "swapz_ci_reuse_and_abort_kunit",
    "swapz_ci_reject_invalid_kunit",
    "swapz_ci_invalid_clone_kunit",
    "swapz_ci_reuse_private_kunit",
    "swapz_ci_abort_dead_ref_kunit",
    "swapz_ci_constructor_copy_isolation_kunit",
    "swapz_ci_constructor_reject_invalid_kunit",
    "swapz_ci_constructor_clone_abort_kunit",
    "swapz_ci_constructor_split_reset_kunit",
))
NEW = frozenset((
    "swapz_round034_v1_owned_copy_kunit",
    "swapz_round034_v1_bio_reject_kunit",
    "swapz_round034_v1_owner_reject_kunit",
    "swapz_round034_v1_constructor_reject_kunit",
    "swapz_round034_v1_alias_kunit",
    "swapz_round034_v1_lifetime_kunit",
))
ALL = OLD | NEW
STAMP = re.compile(r"^\[\s*\d+\.\d+\]\s*")
OK = re.compile(r"^ok\s+\d+\s+(?:-\s+)?([a-zA-Z0-9_]+)(?:\s+#.*)?$")
BAD = re.compile(r"(Kernel panic|BUG: KASAN|KASAN:|UBSAN:|Oops:|^not ok\s+\d+)",
                 re.I | re.M)


class EvidenceRefusal(ValueError):
    """First verifiable independent KUnit failure."""


def read_bounded(path: Path, maximum: int) -> str:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise EvidenceRefusal("missing_symlink_or_oversize")
    return path.read_text(encoding="utf-8")


def verify(data: object, trace: str) -> None:
    if not isinstance(data, dict) or data.get("arch") != "um":
        raise EvidenceRefusal("non_uml_json")
    if "KTAP version 1" not in trace or "# Subtest: " + SUITE not in trace:
        raise EvidenceRefusal("real_ktap_or_suite_missing")
    lines = [STAMP.sub("", line).strip() for line in trace.splitlines()]
    if BAD.search("\n".join(lines)):
        raise EvidenceRefusal("real_kernel_error")
    pending = [data]
    suites: list[dict] = []
    inspected = 0
    while pending:
        group = pending.pop()
        inspected += 1
        if inspected > 1000 or not isinstance(group, dict):
            raise EvidenceRefusal("malformed_kunit_tree")
        if group.get("name") == SUITE:
            suites.append(group)
        children = group.get("sub_groups", [])
        if not isinstance(children, list) or len(children) > 200:
            raise EvidenceRefusal("malformed_kunit_subgroups")
        pending.extend(children)
    if len(suites) != 1:
        raise EvidenceRefusal("missing_or_duplicate_suite")
    suite = suites[0]
    cases = suite.get("test_cases")
    if not isinstance(cases, list) or len(cases) != len(ALL):
        raise EvidenceRefusal("not_old_11_plus_new_6")
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or case.get("name") not in ALL:
            raise EvidenceRefusal("unknown_case")
        name = case["name"]
        if name in seen or case.get("status") != "PASS":
            raise EvidenceRefusal("duplicate_skipped_or_failed:" + name)
        seen.add(name)
    if seen != ALL:
        raise EvidenceRefusal("case_set_mismatch")
    counts = suite.get("misc")
    if not isinstance(counts, dict):
        raise EvidenceRefusal("execution_counts_missing")
    for key, expected in {
        "tests": len(ALL), "passed": len(ALL), "failed": 0,
        "skipped": 0, "crashed": 0, "errors": 0,
    }.items():
        if type(counts.get(key)) is not int or counts[key] != expected:
            raise EvidenceRefusal("count_mismatch:" + key)
    ktap: dict[str, int] = {}
    for line in lines:
        match = OK.fullmatch(line)
        if match and match.group(1) in ALL:
            name = match.group(1)
            ktap[name] = ktap.get(name, 0) + 1
    if set(ktap) != ALL or any(quantity != 1 for quantity in ktap.values()):
        raise EvidenceRefusal("ktap_case_missing_or_duplicate")


def sample() -> tuple[dict, str]:
    names = sorted(ALL)
    document = {
        "arch": "um", "name": "KUnit Test Group",
        "sub_groups": [{
            "name": SUITE, "sub_groups": [],
            "test_cases": [{"name": name, "status": "PASS"} for name in names],
            "misc": {"tests": len(ALL), "passed": len(ALL),
                     "failed": 0, "crashed": 0, "skipped": 0, "errors": 0},
        }],
    }
    trace = ("[    0.001] KTAP version 1\n" +
             "[    0.002] # Subtest: " + SUITE + "\n" +
             "".join(f"[    0.003]     ok {index} {name}\n"
                     for index, name in enumerate(names, 1)))
    return document, trace


class SelfTest(unittest.TestCase):
    def test_valid_complete(self) -> None:
        verify(*sample())

    def test_unsafe_inputs(self) -> None:
        original, trace = sample()
        changes: list[tuple[object, str]] = []
        for status in ("SKIP", "FAIL", "ERROR"):
            document = copy.deepcopy(original)
            document["sub_groups"][0]["test_cases"][0]["status"] = status
            changes.append((document, trace))
        for key, value in (("tests", 11), ("passed", 11),
                           ("failed", 1), ("skipped", 1),
                           ("crashed", 1), ("errors", 1)):
            document = copy.deepcopy(original)
            document["sub_groups"][0]["misc"][key] = value
            changes.append((document, trace))
        document = copy.deepcopy(original)
        document["sub_groups"][0]["test_cases"][0]["name"] = "fabricated"
        changes.append((document, trace))
        document = copy.deepcopy(original)
        document["sub_groups"][0]["test_cases"].append(
            copy.deepcopy(document["sub_groups"][0]["test_cases"][0]))
        changes.append((document, trace))
        document = copy.deepcopy(original)
        document["arch"] = "x86_64"
        changes.append((document, trace))
        for altered in ("", trace.replace("KTAP version 1", "TAP version 14"),
                        trace.replace("ok 1 ", "not ok 1 ", 1),
                        trace + "Kernel panic - not syncing\n",
                        trace + "BUG: KASAN\n",
                        trace + "UBSAN: invalid shift\n",
                        trace + next(x for x in trace.splitlines()
                                     if "ok 1 " in x) + "\n"):
            changes.append((copy.deepcopy(original), altered))
        for index, (data, output) in enumerate(changes):
            with self.subTest(index=index):
                with self.assertRaises(EvidenceRefusal):
                    verify(data, output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--result", type=Path)
    parser.add_argument("--kernel-log", type=Path)
    args = parser.parse_args()
    if args.self_test:
        result = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(SelfTest))
        return 0 if result.wasSuccessful() else 1
    if not args.result or not args.kernel_log:
        parser.error("both --result and --kernel-log are required")
    try:
        verify(json.loads(read_bounded(args.result, 512 * 1024)),
               read_bounded(args.kernel_log, 2 * 1024 * 1024))
    except (ValueError, OSError, UnicodeError) as error:
        print(f"ROUND034_KUNIT_BLOCKED first_cause={error}")
        return 2
    print(f"ROUND034_REAL_ORIGINAL_ZSWAP_Y_KUNIT_PASS old={len(OLD)} new={len(NEW)} total={len(ALL)}")
    print("PHASE_A=BLOCKED MM_EVICTION=NOT_RUN LOADED=NOT_RUN PHYSICAL=NOT_RUN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
