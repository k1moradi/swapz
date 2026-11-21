#!/usr/bin/env python3
"""Fail closed on actual staged pristine original kernel C KUnit cancellation.

This is source negative only. It explicitly rejects every attempt to
transform a copied typed slot or KUnit-only terminal bit into a live count.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import runpy
import unittest

HERE = Path(__file__).resolve().parent
previous = runpy.run_path(
    str(HERE / "round049-original-counted-pair-source-verify.py"),
    run_name="round049_staged_actual_original_source_dependency")
VERIFY_INHERITED = previous["verify"]
SOURCE_SIGNATURE = "static noinline int swapz_round052_original_preunuse_cancel_refusal("
SOURCE_GUARD = "#if defined(SWAPZ_ROUND052_ORIGINAL_PRE_UNUSE_CANCEL_TEST) && IS_ENABLED(CONFIG_KUNIT)"
SUITE = "swapz_round052_original_preunuse_cancel_negative_no_authority"
CASES = (
    "swapz_round052_no_registered_source_owner_kunit",
    "swapz_round052_actual_uncached_folio_refused_kunit",
    "swapz_round052_duplicate_late_cancel_refused_kunit",
)


class OriginalCPreUnuseSourceError(ValueError):
    """The genuine original source-negative refusal changed."""


def function(source: str, signature: str) -> str:
    try:
        return previous["function"](source, signature)
    except previous["OriginalCountPairSourceError"] as error:
        raise OriginalCPreUnuseSourceError("missing_original_C_function:" + signature) from error


def ordered(function_body: str, label: str, *tokens: str) -> None:
    previous_position = -1
    for token in tokens:
        index = function_body.find(token, previous_position + 1)
        if index < 0:
            raise OriginalCPreUnuseSourceError("original_C_owner:" + label + ":" + token)
        previous_position = index


def verify(source: str) -> None:
    try:
        VERIFY_INHERITED(source)
    except previous["OriginalCountPairSourceError"] as error:
        raise OriginalCPreUnuseSourceError("inherited_49_real_C:" + str(error)) from error
    if source.count(SOURCE_GUARD) != 1:
        raise OriginalCPreUnuseSourceError("default_off_guard_absent_or_duplicate")
    if source.count("/* ROUND052_ORIGINAL_PRE_UNUSE_NEGATIVE_BEGIN */") != 1 or \
            source.count("/* ROUND052_ORIGINAL_PRE_UNUSE_NEGATIVE_END */") != 1:
        raise OriginalCPreUnuseSourceError("genuine_original_C_test_boundary_missing")
    body = function(source, SOURCE_SIGNATURE)
    ordered(body, "original_KUnit_only_no_external_source_owner",
            "if (!candidate)", "return -EINVAL;",
            "if (candidate->terminal)", "return -EALREADY;",
            "candidate->terminal = true;",
            "if (!candidate->folio || !candidate->stored || !candidate->tree ||",
            "!candidate->original_slot.val)",
            "if (!folio_test_locked(candidate->folio) ||",
            "!folio_test_swapcache(candidate->folio))",
            "if (candidate->folio->swap.val != candidate->original_slot.val ||",
            "xa_load(candidate->tree, swp_offset(candidate->original_slot)) !=",
            "candidate->stored)", "return -ESTALE;", "return -EOPNOTSUPP;")
    if body.count("candidate->terminal = true;") != 1 or \
            body.count("return -EOPNOTSUPP;") != 1:
        raise OriginalCPreUnuseSourceError("not_single_final_refusal")
    for prohibited in (
        "folio_dup_swap", "folio_put_swap", "swap_dup_entry_direct",
        "swap_put_entries_direct", "submit_bio", "dm_get_live_table",
        "queue_work", "cancel_work_sync", "flush_work",
    ):
        # Strip C comments: negative design commentary is not a live call.
        stripped = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
        if re.search(r"\b" + prohibited + r"\s*\(", stripped):
            raise OriginalCPreUnuseSourceError(
                "unowned_original_ref_or_unregistered_async:" + prohibited)
    writer = function(source, "static int zswap_writeback_entry(struct zswap_entry *entry,")
    if "swapz_round052_original_preunuse_cancel_refusal(" in writer:
        raise OriginalCPreUnuseSourceError("default_kernel_runtime_writeback_modified")
    if "kunit_test_suite(swapz_round052_original_preunuse_negative_suite);" not in source or \
            source.count('"' + SUITE + '"') != 1:
        raise OriginalCPreUnuseSourceError("real_negative_original_KUnit_suite_missing")
    for case in CASES:
        if source.count("KUNIT_CASE(" + case + ")") != 1:
            raise OriginalCPreUnuseSourceError("real_original_KUnit_case_missing:" + case)
    uncached = function(source,
                        "static void swapz_round052_actual_uncached_folio_refused_kunit(")
    ordered(uncached, "real_kernel_uncached_folio_allocation_and_cleanup",
            "folio_alloc(GFP_KERNEL, 0);",
            "KUNIT_ASSERT_NOT_NULL(test, folio);",
            "xa_init(&tree);", "folio_test_swapcache(folio)",
            "swapz_round052_original_preunuse_cancel_refusal(",
            "candidate.terminal = false;", "folio_lock(folio);",
            "folio_test_locked(folio)", "folio_test_swapcache(folio)",
            "swapz_round052_original_preunuse_cancel_refusal(",
            "folio_unlock(folio);", "xa_destroy(&tree);", "folio_put(folio);")
    duplicate = function(source,
                         "static void swapz_round052_duplicate_late_cancel_refused_kunit(")
    ordered(duplicate, "single_thread_local_KUnit_terminal_never_a_count",
            ".terminal = true,", "swapz_round052_original_preunuse_cancel_refusal(",
            "-EALREADY);", "candidate.terminal = false;",
            "swapz_round052_original_preunuse_cancel_refusal(",
            "-EINVAL);", "swapz_round052_original_preunuse_cancel_refusal(",
            "-EALREADY);")


MUTATIONS: tuple[tuple[str | None, str, str], ...] = (
    (SOURCE_SIGNATURE, "if (!candidate)", "if (false)"),
    (SOURCE_SIGNATURE, "if (candidate->terminal)", "if (false)"),
    (SOURCE_SIGNATURE, "candidate->terminal = true;", "candidate->terminal = false;"),
    (SOURCE_SIGNATURE,
     "if (!candidate->folio || !candidate->stored || !candidate->tree ||",
     "if (false && !candidate->folio || !candidate->stored || !candidate->tree ||"),
    (SOURCE_SIGNATURE, "!folio_test_locked(candidate->folio)", "false"),
    (SOURCE_SIGNATURE, "!folio_test_swapcache(candidate->folio)", "false"),
    (SOURCE_SIGNATURE, "candidate->folio->swap.val != candidate->original_slot.val",
     "false"),
    (SOURCE_SIGNATURE, "xa_load(candidate->tree, swp_offset(candidate->original_slot)) !=",
     "NULL !="),
    (SOURCE_SIGNATURE, "return -EOPNOTSUPP;", "return 0;"),
    (None, "KUNIT_CASE(swapz_round052_no_registered_source_owner_kunit)",
     "/* removed no-owner C case */"),
    (None, "KUNIT_CASE(swapz_round052_actual_uncached_folio_refused_kunit)",
     "/* removed uncached C case */"),
    (None, "KUNIT_CASE(swapz_round052_duplicate_late_cancel_refused_kunit)",
     "/* removed duplicate C case */"),
    ("static void swapz_round052_actual_uncached_folio_refused_kunit(",
     "folio_unlock(folio);", "/* leaked folio lock */"),
    ("static void swapz_round052_actual_uncached_folio_refused_kunit(",
     "folio_put(folio);", "/* leaked original kernel folio */"),
)


class OriginalSourceMutantTests(unittest.TestCase):
    source: str = ""

    def test_actual_original_C_noauth_source(self) -> None:
        verify(self.source)

    def test_fourteen_function_scoped_original_C_mutants(self) -> None:
        self.assertEqual(len(MUTATIONS), 14)
        for number, (signature, before, after) in enumerate(MUTATIONS):
            with self.subTest(original_C_mutant=number):
                region = function(self.source, signature) if signature else self.source
                self.assertEqual(region.count(before), 1,
                                 "actual original C mutation anchor must be unique")
                revised = self.source.replace(
                    region, region.replace(before, after, 1), 1)
                self.assertNotEqual(self.source, revised, "hostile mutant no-op")
                with self.assertRaises(OriginalCPreUnuseSourceError):
                    verify(revised)


def load_original_staged(root: Path) -> str:
    zswap = root / "mm/zswap.c"
    if root.is_symlink() or not root.is_dir() or zswap.is_symlink() or \
            not zswap.is_file() or not 0 < zswap.stat().st_size < 450_000:
        raise OriginalCPreUnuseSourceError("no_true_staged_original_zswap_C")
    return zswap.read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        source = load_original_staged(args.linux_root)
        if args.self_test:
            OriginalSourceMutantTests.source = source
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(
                OriginalSourceMutantTests)
            if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
                return 1
        else:
            verify(source)
    except (OriginalCPreUnuseSourceError, OSError, UnicodeError) as error:
        print("ROUND052_ORIGINAL_KERNEL_C_CANCEL_REFUSAL_BLOCKED first_error=" + str(error))
        return 2
    print("ROUND052_REAL_ORIGINAL_STAGED_C_14_HOSTILES_PASS "
          "GUARDED_NEGATIVE_KUNIT_REGISTERED=3 "
          "GENUINE_EXTERNAL_SOURCE_REF=NOT_ACQUIRED "
          "SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
