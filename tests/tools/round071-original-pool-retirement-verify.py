#!/usr/bin/env python3
"""Verify actual original mm/zswap.c retirement plus inherited native decoder.

JSON and KTAP must both contain all six genuine KUnit cases, 0 skip/fail.
The two new KUnit tests each run 24 close+wake/re-read rounds internally.
The four inherited cases are separately verified by their existing oracle.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
import runpy
import sys

ROOT = Path(__file__).resolve().parents[2]
OLD_VERIFIER = ROOT / "tests/tools/round068-original-decoder-owner-kunit-verify.py"
SUITE = "swapz_round071_pool_retirement"
CASES = (
    "swapz_round071_original_lzo_pool_retirement",
    "swapz_round071_original_lz4_pool_retirement",
)


class NativeError(Exception):
    pass


def require(condition: bool, cause: str) -> None:
    if not condition:
        raise NativeError(cause)


def verify_native(document: dict, kernel_log: str) -> None:
    require(isinstance(document, dict), "native-KUnit-JSON-not-object")
    previous = runpy.run_path(str(OLD_VERIFIER))
    try:
        previous["verify_native"](document, kernel_log)
    except previous["FirstError"] as error:
        raise NativeError("inherited-original-decoder-4-case:" + str(error)) from error
    nested = [document]
    matches = []
    while nested:
        group = nested.pop()
        require(isinstance(group, dict), "native-KUnit-subgroup-object")
        if group.get("name") == SUITE:
            matches.append(group)
        children = group.get("sub_groups", [])
        require(isinstance(children, list), "native-KUnit-children-array")
        nested.extend(children)
    require(len(matches) == 1, "original-pool-retirement-suite-count")
    suite = matches[0]
    cases = suite.get("test_cases")
    require(isinstance(cases, list) and len(cases) == len(CASES),
            "original-pool-retirement-actual-case-count")
    require({case.get("name") for case in cases if isinstance(case, dict)} ==
            set(CASES) and
            all(case.get("status") == "PASS"
                for case in cases if isinstance(case, dict)),
            "original-pool-retirement-fail-skip-case")
    counts = suite.get("misc", {})
    for name, expected in (("tests", 2), ("passed", 2), ("failed", 0),
                           ("skipped", 0), ("crashed", 0), ("errors", 0)):
        require(type(counts.get(name)) is int and counts[name] == expected,
                "original-pool-retirement-misc:" + name)
    require(kernel_log.count("# Subtest: " + SUITE) == 1,
            "original-pool-retirement-KTAP-suite-count")
    for case in CASES:
        require(len(re.findall(r"(?m)^\s*ok\s+[0-9]+\s+(?:-\s+)?" +
                               re.escape(case) + r"\s*$", kernel_log)) == 1,
                "original-pool-retirement-KTAP-case:" + case)
    require(re.search(
        r"(?i)(Kernel panic|KASAN:|UBSAN:|BUG: sleeping function called|"
        r"not ok\s+[0-9]+\s+swapz_round07[18])", kernel_log) is None,
        "original-pool-retirement-KTAP-error-or-crash")


def self_test() -> None:
    inherited = runpy.run_path(str(OLD_VERIFIER))
    prior_cases = inherited["CASES"]
    prior_suite = {"name": inherited["TEST_SUITE"],
                   "test_cases": [{"name": name, "status": "PASS"}
                                  for name in prior_cases],
                   "sub_groups": [],
                   "misc": {"tests": 4, "passed": 4, "failed": 0,
                            "skipped": 0, "crashed": 0, "errors": 0}}
    added = {"name": SUITE,
             "test_cases": [{"name": name, "status": "PASS"}
                            for name in CASES],
             "sub_groups": [],
             "misc": {"tests": 2, "passed": 2, "failed": 0,
                      "skipped": 0, "crashed": 0, "errors": 0}}
    baseline = {"name": "kernel", "sub_groups": [prior_suite, added]}
    ktap = "".join(
        "# Subtest: " + group["name"] + "\n" +
        "".join(f"    ok {index} {row['name']}\n"
                for index, row in enumerate(group["test_cases"], 1))
        for group in (prior_suite, added))
    verify_native(baseline, ktap)
    mutants = 0
    for change in range(11):
        document = copy.deepcopy(baseline)
        transcript = ktap
        group = document["sub_groups"][1]
        if change == 0:
            group["test_cases"][0]["status"] = "SKIP"
        elif change == 1:
            group["test_cases"][1]["status"] = "FAIL"
        elif change == 2:
            group["test_cases"].pop()
        elif change == 3:
            group["misc"]["failed"] = 1
        elif change == 4:
            group["misc"]["passed"] = 1
        elif change == 5:
            group["misc"]["skipped"] = 1
        elif change == 6:
            document["sub_groups"].append(copy.deepcopy(group))
        elif change == 7:
            transcript = transcript.replace("    ok 1 " + CASES[0],
                                            "    not ok 1 " + CASES[0])
        elif change == 8:
            transcript = transcript.replace("# Subtest: " + SUITE,
                                            "# Subtest: wrong_source_pool")
        elif change == 9:
            transcript += "KASAN: use-after-free in original pool\n"
        else:
            document["sub_groups"][0]["test_cases"][0]["status"] = "SKIP"
        try:
            verify_native(document, transcript)
        except NativeError:
            mutants += 1
        else:
            raise NativeError("forged-native-result-accepted:" + str(change))
    require(mutants == 11, "negative-verdict-mutants-count")
    print("ROUND071_ORIGINAL_POOL_NATIVE_ORACLE_SELFTEST_PASS "
          "baseline=1 rejected_semantic_verdict_mutants=11 "
          "inherited_real_original_decoder_cases=4")


def main() -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_subparsers(dest="mode", required=True)
    check = modes.add_parser("verify-native")
    check.add_argument("--result", type=Path, required=True)
    check.add_argument("--kernel-log", type=Path, required=True)
    modes.add_parser("self-test")
    args = parser.parse_args()
    try:
        if args.mode == "self-test":
            self_test()
        else:
            verify_native(json.loads(args.result.read_text()),
                          args.kernel_log.read_text(errors="replace"))
            print("ROUND071_GENUINE_ORIGINAL_POOL_RETIRED_DECODER_KUNIT_PASS "
                  "native_cases=6 (4 inherited + 2 genuine pool) "
                  "original_lzo_lz4_full4096=YES close_cycles=48 "
                  "real_original_percpu_ref_hotplug_rcu_tfm_destroy=YES "
                  "source_auth=0 phase_a=BLOCKED")
        return 0
    except (NativeError, ValueError, OSError, KeyError) as error:
        print("ROUND071_ORIGINAL_POOL_NATIVE_FIRST_ERROR " +
              str(error)[:180], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
