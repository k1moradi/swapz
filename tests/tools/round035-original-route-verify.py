#!/usr/bin/env python3
"""Original booted UML JSON + KTAP exactly 17 old/v1 + 4 route negative cases.

Independently checks actual 2-suite source output; a matched C object, a
synthetic suite string, skipped test, panic, duplicated case or a missing
original source case never qualifies as an executed KUnit result.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent
ORIGINAL = ROOT / "round034-original-v1-kunit-verify.py"
SPEC = importlib.util.spec_from_file_location("round034_exact_verifier", ORIGINAL)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

SUITE = "swapz_round035_original_mm_route_no_authority"
NEW = frozenset((
    "swapz_round035_route_type_kunit",
    "swapz_round035_route_epoch_kunit",
    "swapz_round035_route_geometry_kunit",
    "swapz_round035_route_no_authority_kunit",
))
CASE_OK = re.compile(r"^ok\s+\d+\s+(?:-\s+)?([A-Za-z0-9_]+)(?:\s+#.*)?$")
STAMP = re.compile(r"^\[\s*\d+\.\d+\]\s*")


class RouteEvidenceError(ValueError):
    """Fail-closed original two-suite execution proof."""


def verify(document: object, kernel_log: str) -> None:
    try:
        module.verify(document, kernel_log)  # Exact 17 original old + v1
    except module.EvidenceRefusal as error:
        raise RouteEvidenceError("original_17:" + str(error)) from error
    if not isinstance(document, dict) or "KTAP version 1" not in kernel_log:
        raise RouteEvidenceError("not_original_uml_ktap")
    if "# Subtest: " + SUITE not in kernel_log:
        raise RouteEvidenceError("missing_original_mm_route_subtest")
    pending = [document]
    found: list[dict] = []
    inspected = 0
    while pending:
        group = pending.pop()
        inspected += 1
        if inspected > 1000 or not isinstance(group, dict):
            raise RouteEvidenceError("invalid_json_tree")
        if group.get("name") == SUITE:
            found.append(group)
        children = group.get("sub_groups", [])
        if not isinstance(children, list) or len(children) > 200:
            raise RouteEvidenceError("invalid_json_subgroups")
        pending.extend(children)
    if len(found) != 1:
        raise RouteEvidenceError("missing_duplicate_route_suite")
    cases = found[0].get("test_cases")
    if not isinstance(cases, list) or len(cases) != len(NEW):
        raise RouteEvidenceError("missing_or_extra_new_cases")
    seen: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise RouteEvidenceError("malformed_route_case")
        name = case.get("name")
        if name not in NEW or name in seen or case.get("status") != "PASS":
            raise RouteEvidenceError("failed_skipped_duplicate_or_unknown_case")
        seen.add(name)
    if seen != NEW:
        raise RouteEvidenceError("incomplete_route_cases")
    counts = found[0].get("misc")
    if not isinstance(counts, dict):
        raise RouteEvidenceError("no_route_counts")
    for key, expected in {
        "tests": len(NEW), "passed": len(NEW),
        "failed": 0, "skipped": 0, "crashed": 0, "errors": 0,
    }.items():
        if type(counts.get(key)) is not int or counts[key] != expected:
            raise RouteEvidenceError("route_count:" + key)

    traces: dict[str, int] = {}
    for line in kernel_log.splitlines():
        stripped = STAMP.sub("", line).strip()
        matched = CASE_OK.fullmatch(stripped)
        if matched and matched.group(1) in NEW:
            name = matched.group(1)
            traces[name] = traces.get(name, 0) + 1
    if set(traces) != NEW or any(amount != 1 for amount in traces.values()):
        raise RouteEvidenceError("missing_or_duplicate_original_kernel_ktap")


def sample() -> tuple[dict, str]:
    document, log = module.sample()
    cases = sorted(NEW)
    document["sub_groups"].append({
        "name": SUITE, "sub_groups": [],
        "test_cases": [{"name": case, "status": "PASS"} for case in cases],
        "misc": {
            "tests": len(NEW), "passed": len(NEW),
            "failed": 0, "skipped": 0, "crashed": 0, "errors": 0,
        },
    })
    log += ("[    0.004] # Subtest: " + SUITE + "\n" +
            "".join(f"[    0.005]     ok {index} {case}\n"
                    for index, case in enumerate(cases, 1)))
    return document, log


class HostileSelfTest(unittest.TestCase):
    def test_two_original_suites_complete(self) -> None:
        verify(*sample())

    def test_reject_failure_skips_omission_and_invented_metadata(self) -> None:
        original, trace = sample()
        corrupt: list[tuple[object, str]] = []
        for status in ("SKIP", "ERROR", "FAIL"):
            document = copy.deepcopy(original)
            document["sub_groups"][1]["test_cases"][0]["status"] = status
            corrupt.append((document, trace))
        for key, value in (
            ("tests", 17), ("passed", 3), ("skipped", 1),
            ("failed", 1), ("crashed", 1), ("errors", 1),
        ):
            document = copy.deepcopy(original)
            document["sub_groups"][1]["misc"][key] = value
            corrupt.append((document, trace))
        document = copy.deepcopy(original)
        document["sub_groups"][1]["test_cases"][0]["name"] = "fake_route"
        corrupt.append((document, trace))
        document = copy.deepcopy(original)
        document["sub_groups"].append(copy.deepcopy(document["sub_groups"][1]))
        corrupt.append((document, trace))
        document = copy.deepcopy(original)
        document["sub_groups"][0]["test_cases"][0]["status"] = "SKIP"
        corrupt.append((document, trace))
        for changed in (
            trace.replace("# Subtest: " + SUITE, "# Subtest: fake", 1),
            trace.replace("ok 1 swapz_round035_", "not ok 1 swapz_round035_", 1),
            trace + "Kernel panic - not syncing\n",
            trace + "BUG: KASAN: use-after-free\n",
            trace + "UBSAN: out-of-bounds\n",
            trace + next(line for line in trace.splitlines()
                         if "ok 1 swapz_round035_" in line) + "\n",
        ):
            corrupt.append((copy.deepcopy(original), changed))
        for index, (document, log) in enumerate(corrupt):
            with self.subTest(index=index):
                with self.assertRaises(RouteEvidenceError):
                    verify(document, log)


def bounded(path: Path, maximum: int) -> str:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise RouteEvidenceError("missing_symlink_or_oversized_evidence")
    return path.read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--result", type=Path)
    parser.add_argument("--kernel-log", type=Path)
    args = parser.parse_args()
    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(HostileSelfTest)
        ran = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if ran.wasSuccessful() else 1
    if not args.result or not args.kernel_log:
        parser.error("--result and --kernel-log are required")
    try:
        verify(json.loads(bounded(args.result, 512 * 1024)),
               bounded(args.kernel_log, 2 * 1024 * 1024))
    except (RouteEvidenceError, OSError, ValueError, UnicodeError) as error:
        print(f"ROUND035_ORIGINAL_ROUTE_KUNIT_BLOCKED first_cause={error}")
        return 2
    print("ROUND035_ORIGINAL_MM_ROUTE_GENUINE_UML_KUNIT_PASS old_v1=17 route_negative=4 total=21")
    print("ROUTING_AUTHORITY=NO_AUTHORITY ORIGINAL_MM_PRESSURE_EVICTION=NOT_RUN "
          "PHASE_A=BLOCKED DIRECT_COMPRESSED=DISABLED PHYSICAL=NOT_RUN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
