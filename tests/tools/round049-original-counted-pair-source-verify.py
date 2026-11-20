#!/usr/bin/env python3
"""Reject counterfeit original Linux counted folio pair in staged C source.

This is genuine source-location evidence and hostile mutation rejection, NOT
an executed ref in a real pressure eviction or external source-to-DM AUTH.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import runpy
import unittest

HERE = Path(__file__).resolve().parent
original = runpy.run_path(
    str(HERE / "round047-original-slot-incarnation-source-audit.py"),
    run_name="round047_only_for_function_parser")
FUNCTION_BODY = original["function_body"]
SOURCE_MACRO = "SWAPZ_ROUND049_ORIGINAL_LOCKED_FOLIO_COUNT_PAIR_TEST"
PAIR_SIGNATURE = "static noinline int swapz_round049_original_locked_folio_counted_pair("
WRITEBACK_SIGNATURE = "static int zswap_writeback_entry(struct zswap_entry *entry,"
SUITE = "swapz_round049_original_locked_folio_counted_pair_no_authority"


class OriginalCountPairSourceError(ValueError):
    """Real original guarded source owner check failed."""


def required(body: str, name: str, *tokens: str) -> None:
    previous = -1
    for token in tokens:
        position = body.find(token, previous + 1)
        if position < 0:
            raise OriginalCountPairSourceError("original_counted_owner:" + name + ":" + token)
        previous = position


def function(source: str, signature: str) -> str:
    try:
        return FUNCTION_BODY(source, signature)
    except original["OriginalSlotAuditError"] as error:
        raise OriginalCountPairSourceError("original_function:" + signature) from error


def verify(source: str) -> None:
    if not source or SOURCE_MACRO not in source:
        raise OriginalCountPairSourceError("guard_not_present")
    guards = (
        "#if defined(" + SOURCE_MACRO + ") && IS_ENABLED(CONFIG_KUNIT)",
    )
    if source.count(guards[0]) != 2:
        raise OriginalCountPairSourceError("guard_missing_or_unintended_default")
    pair = function(source, PAIR_SIGNATURE)
    required(pair, "real_locked_folio_count_acquire_put",
             "if (!folio || !stored || !tree || !original_slot.val)",
             "!folio_test_locked(folio)", "!folio_test_swapcache(folio)",
             "folio->swap.val != original_slot.val",
             "xa_load(tree, swp_offset(original_slot)) != stored",
             "result = folio_dup_swap(folio, NULL);",
             "if (result)", "return result;",
             "folio_put_swap(folio, NULL);", "return 0;")
    if pair.count("folio_dup_swap(folio, NULL);") != 1 or \
            pair.count("folio_put_swap(folio, NULL);") != 1:
        raise OriginalCountPairSourceError("double_count_or_double_put")
    if any(x in pair for x in (
        "swap_dup_entry_direct(", "swap_put_entries_direct(",
        "submit_bio(", "dm_get_live_table(", "percpu_ref_get(",
    )):
        raise OriginalCountPairSourceError("unsupported_external_counted_owner")
    writer = function(source, WRITEBACK_SIGNATURE)
    required(writer, "original_current_zswap_source_scope",
             "si = get_swap_device(swpentry);",
             "__swap_cache_alloc_folio(", "put_swap_device(si);",
             "if (entry != xa_load(tree, offset)) {",
             "if (!zswap_decompress(entry, folio)) {",
             "ret = swapz_round049_original_locked_folio_counted_pair(",
             "if (ret)", "goto err;", "xa_erase(tree, offset);",
             "zswap_entry_free(entry);", "folio_put(folio);",
             "__swap_writeout(&ctx, folio);", "swap_write_submit(&ctx);")
    required(writer, "original_existing_failure_unwind",
             "err:", "swap_cache_del_folio(folio);",
             "folio_unlock(folio);", "folio_put(folio);", "return ret;")
    if writer.count("ret = swapz_round049_original_locked_folio_counted_pair(") != 1:
        raise OriginalCountPairSourceError("duplicate_original_probe_call")
    for case in (
        "swapz_round049_missing_original_owner_kunit",
        "swapz_round049_unlocked_uncached_folio_kunit",
    ):
        if source.count("KUNIT_CASE(" + case + ")") != 1:
            raise OriginalCountPairSourceError("genuine_kernel_case_not_registered:" + case)
    if source.count("kunit_test_suite(swapz_round049_original_counted_pair_suite);") != 1 or \
            source.count('"' + SUITE + '"') != 1:
        raise OriginalCountPairSourceError("kernel_suite_not_unique")


class SourceHostileControlTests(unittest.TestCase):
    source: str = ""

    def test_genuine_current_original_c(self) -> None:
        verify(self.source)

    def test_12_actual_c_function_scoped_mutants(self) -> None:
        mutations = (
            (PAIR_SIGNATURE, "if (!folio || !stored || !tree || !original_slot.val)", "if (false)"),
            (PAIR_SIGNATURE, "!folio_test_locked(folio)", "false"),
            (PAIR_SIGNATURE, "!folio_test_swapcache(folio)", "false"),
            (PAIR_SIGNATURE, "folio->swap.val != original_slot.val", "false"),
            (PAIR_SIGNATURE, "xa_load(tree, swp_offset(original_slot)) != stored", "false"),
            (PAIR_SIGNATURE, "result = folio_dup_swap(folio, NULL);", "result = 0;"),
            (PAIR_SIGNATURE, "if (result)", "if (false)"),
            (PAIR_SIGNATURE, "folio_put_swap(folio, NULL);", "/* lost counted release */"),
            (WRITEBACK_SIGNATURE, "ret = swapz_round049_original_locked_folio_counted_pair(",
             "ret = fake_original_counted_pair("),
            (WRITEBACK_SIGNATURE, "if (ret)\n\t\tgoto err;\n#endif",
             "if (ret)\n\t\tgoto bad_original_error;\n#endif"),
            (None, "KUNIT_CASE(swapz_round049_missing_original_owner_kunit)",
             "/* removed missing owner KUnit */"),
            (None, "KUNIT_CASE(swapz_round049_unlocked_uncached_folio_kunit)",
             "/* removed unlocked folio KUnit */"),
        )
        self.assertEqual(len(mutations), 12)
        for index, (signature, old, new) in enumerate(mutations):
            with self.subTest(mutant=index):
                region = function(self.source, signature) if signature else self.source
                self.assertEqual(region.count(old), 1,
                                 "hostile mutation MUST target unique genuine original C")
                changed_region = region.replace(old, new, 1)
                changed = self.source.replace(region, changed_region, 1)
                self.assertNotEqual(changed, self.source, "mutant was unchanged")
                with self.assertRaises(OriginalCountPairSourceError):
                    verify(changed)


def load_staged(root: Path) -> str:
    path = root / "mm/zswap.c"
    if root.is_symlink() or not root.is_dir() or path.is_symlink() or \
            not path.is_file() or not 0 < path.stat().st_size < 400_000:
        raise OriginalCountPairSourceError("no_actual_staged_original_zswap_source")
    return path.read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        source = load_staged(args.linux_root)
        if args.self_test:
            SourceHostileControlTests.source = source
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(
                SourceHostileControlTests)
            if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
                return 1
        else:
            verify(source)
    except (OriginalCountPairSourceError, OSError, UnicodeError) as error:
        print("ROUND049_ORIGINAL_COUNTED_SOURCE_BLOCKED first_error=" + str(error))
        return 2
    print("ROUND049_REAL_ORIGINAL_STAGED_C_12_HOSTILE_NEGATIVES_PASS "
          "LOCAL_COUNTED_PAIR_GUARDED=TRUE EXTERNAL_REF_TRANSFER=NO_AUTH")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
