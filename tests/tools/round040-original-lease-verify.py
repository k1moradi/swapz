#!/usr/bin/env python3
"""Round040 genuine original ZSWAP=y UML: exact prior 36 + five new async lease negatives.

No seeded JSON or synthetic KTAP can qualify the actual kernel. An earlier
source-host fixture is never evidence of MM-pressure writeback or target map
authority. This builds on independent Round034 and Round035 verifiers.
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
PRIOR = ROOT / "round038-original-store-provenance-verify.py"
SPEC = importlib.util.spec_from_file_location("round038_exact_verifier", PRIOR)
assert SPEC and SPEC.loader
prior = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prior)

SUITE = "swapz_round040_original_mm_async_lease_no_authority"
NEW = frozenset((
    "swapz_round040_scope_put_late_callback_kunit",
    "swapz_round040_slot_swapoff_readd_aba_kunit",
    "swapz_round040_clone_split_last_ref_kunit",
    "swapz_round040_cancel_teardown_gc_unknown_kunit",
    "swapz_round040_bdev_sector_raw_geometry_kunit",
))
CASE_OK = re.compile(r"^ok\s+\d+\s+(?:-\s+)?([A-Za-z0-9_]+)(?:\s+#.*)?$")
STAMP = re.compile(r"^\[\s*\d+\.\d+\]\s*")


class OriginalAsyncLeaseEvidenceError(ValueError):
    """Reject missing, repeated, skipped, failed or fabricated kernel cases."""


def verify(document: object, kernel_log: str) -> None:
    try:
        prior.verify(document, kernel_log)  # Original 36 genuine booted original C KUnit baseline
    except prior.OriginalStoreEvidenceError as error:
        raise OriginalAsyncLeaseEvidenceError("original_36:" + str(error)) from error
    if not isinstance(document, dict) or "KTAP version 1" not in kernel_log:
        raise OriginalAsyncLeaseEvidenceError("no_genuine_original_uml_ktap")
    if kernel_log.count("# Subtest: " + SUITE) != 1:
        raise OriginalAsyncLeaseEvidenceError("missing_duplicate_suite_ktap")
    waiting = [document]
    found: list[dict] = []
    inspected = 0
    while waiting:
        group = waiting.pop()
        inspected += 1
        if inspected > 1000 or not isinstance(group, dict):
            raise OriginalAsyncLeaseEvidenceError("malformed_original_json_tree")
        if group.get("name") == SUITE:
            found.append(group)
        children = group.get("sub_groups", [])
        if not isinstance(children, list) or len(children) > 200:
            raise OriginalAsyncLeaseEvidenceError("malformed_original_subgroups")
        waiting.extend(children)
    if len(found) != 1:
        raise OriginalAsyncLeaseEvidenceError("missing_duplicate_new_suite")
    section = found[0]
    cases = section.get("test_cases")
    if not isinstance(cases, list) or len(cases) != len(NEW):
        raise OriginalAsyncLeaseEvidenceError("wrong_new_case_count")
    names: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise OriginalAsyncLeaseEvidenceError("malformed_case")
        name = case.get("name")
        if name not in NEW or name in names or case.get("status") != "PASS":
            raise OriginalAsyncLeaseEvidenceError("duplicate_unknown_or_failed_new_case")
        names.add(name)
    if names != NEW:
        raise OriginalAsyncLeaseEvidenceError("missing_new_case")
    counts = section.get("misc")
    if not isinstance(counts, dict):
        raise OriginalAsyncLeaseEvidenceError("missing_new_counts")
    for field, expected in {
        "tests": 5, "passed": 5, "failed": 0, "skipped": 0,
        "crashed": 0, "errors": 0,
    }.items():
        if type(counts.get(field)) is not int or counts[field] != expected:
            raise OriginalAsyncLeaseEvidenceError("incorrect_new_count:" + field)
    ktap_cases: dict[str, int] = {}
    for line in kernel_log.splitlines():
        cleaned = STAMP.sub("", line).strip()
        match = CASE_OK.fullmatch(cleaned)
        if match and match.group(1) in NEW:
            case_name = match.group(1)
            ktap_cases[case_name] = ktap_cases.get(case_name, 0) + 1
    if set(ktap_cases) != NEW or any(count != 1 for count in ktap_cases.values()):
        raise OriginalAsyncLeaseEvidenceError("missing_or_duplicate_new_ktap")
    if re.search(r"(?i)(?:kernel panic|KASAN:|UBSAN:|not ok\s+\d+\s+swapz_round040)", kernel_log):
        raise OriginalAsyncLeaseEvidenceError("real_kernel_failure_marker")


def sample() -> tuple[dict, str]:
    document, log = prior.sample()  # Self-test only, synthetic old 36 JSON/KTAP baseline
    ordered = sorted(NEW)
    document["sub_groups"].append({
        "name": SUITE,
        "sub_groups": [],
        "test_cases": [{"name": name, "status": "PASS"} for name in ordered],
        "misc": {
            "tests": 5, "passed": 5, "failed": 0,
            "skipped": 0, "crashed": 0, "errors": 0,
        },
    })
    log += "[    0.008] # Subtest: " + SUITE + "\n"
    log += "".join(
        f"[    0.009]     ok {number} {name}\n"
        for number, name in enumerate(ordered, 1)
    )
    return document, log


class HostileVerifierSelfTests(unittest.TestCase):
    def test_accept_complete_sample_only_as_self_test(self):
        verify(*sample())

    def test_refuse_bad_status_counts_identity_and_ktap(self):
        baseline, log = sample()
        bad: list[tuple[object, str]] = []
        for status in ("FAIL", "SKIP", "ERROR", "CRASHED"):
            doc = copy.deepcopy(baseline)
            doc["sub_groups"][-1]["test_cases"][0]["status"] = status
            bad.append((doc, log))
        for field, value in (("tests", 4), ("passed", 4), ("failed", 1),
                             ("skipped", 1), ("crashed", 1), ("errors", 1)):
            doc = copy.deepcopy(baseline)
            doc["sub_groups"][-1]["misc"][field] = value
            bad.append((doc, log))
        doc = copy.deepcopy(baseline)
        doc["sub_groups"][-1]["test_cases"].append(
            copy.deepcopy(doc["sub_groups"][-1]["test_cases"][0]))
        bad.append((doc, log))
        doc = copy.deepcopy(baseline)
        doc["sub_groups"][-1]["test_cases"][0]["name"] = "fabricated"
        bad.append((doc, log))
        doc = copy.deepcopy(baseline)
        doc["sub_groups"].append(copy.deepcopy(doc["sub_groups"][-1]))
        bad.append((doc, log))
        doc = copy.deepcopy(baseline)
        doc["sub_groups"][0]["test_cases"][0]["status"] = "SKIP"
        bad.append((doc, log))
        for changed in (
            log.replace("# Subtest: " + SUITE, "# Subtest: forged", 1),
            log.replace("ok 1 swapz_round040_", "not ok 1 swapz_round040_", 1),
            log + next(line for line in log.splitlines()
                       if "ok 1 swapz_round040_" in line) + "\n",
            log + "Kernel panic - not syncing\n",
            log + "BUG: KASAN: use-after-free\n",
            log + "UBSAN: signed-integer-overflow\n",
        ):
            bad.append((copy.deepcopy(baseline), changed))
        for index, (document, trace) in enumerate(bad):
            with self.subTest(case=index):
                with self.assertRaises(OriginalAsyncLeaseEvidenceError):
                    verify(document, trace)


def bounded(path: Path, limit: int) -> str:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise OriginalAsyncLeaseEvidenceError("missing_or_oversized_evidence")
    return path.read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--result", type=Path)
    parser.add_argument("--kernel-log", type=Path)
    args = parser.parse_args()
    if args.self_test:
        results = unittest.TextTestRunner(verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(
                HostileVerifierSelfTests))
        return 0 if results.wasSuccessful() else 1
    if not args.result or not args.kernel_log:
        parser.error("--result and --kernel-log required")
    try:
        verify(json.loads(bounded(args.result, 512 * 1024)),
               bounded(args.kernel_log, 2 * 1024 * 1024))
    except (OriginalAsyncLeaseEvidenceError, OSError, UnicodeError, ValueError) as error:
        print(f"ROUND040_REAL_ORIGINAL_ASYNC_LEASE_BLOCKED first_error={error}")
        return 2
    print("ROUND040_REAL_ORIGINAL_UML_KUNIT_PASS original_baseline=36 "
          "new_async_lease=5 total=41")
    print("ORIGINAL_STORE_EXECUTED=NO_SYNTHETIC_INPUTS_ONLY ORIGINAL_ASYNC_SLOT_LEASE=NO_AUTHORITY "
          "SOURCE_MAPPED_AUTHENTICATED=0 MM_PRESSURE_EVICTION=NOT_RUN "
          "PHASE_A=BLOCKED DIRECT_COMPRESSED_HANDOFF=DISABLED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
