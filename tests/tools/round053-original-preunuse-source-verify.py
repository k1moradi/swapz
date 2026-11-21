#!/usr/bin/env python3
"""Verify real staged original mm/zswap.c closed-gate KUnit and hostile source edits.

Original Linux boot is NOT simulated here: --self-test mutates the exact
source given by --linux-root. The new gate is a DEFAULT-OFF NO_OWNER refusal.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import runpy
import unittest

HERE = Path(__file__).resolve().parent
prior = runpy.run_path(
    str(HERE / "round052-original-preunuse-source-verify.py"),
    run_name="round052_original_source_dependency")
SOURCE_FUNCTION = "static noinline int swapz_round053_preunuse_gate_refuse("
SUITE = "swapz_round053_original_preunuse_closed_gate_no_authority"
CASES = (
    "swapz_round053_unregistered_source_refused_kunit",
    "swapz_round053_closed_duplicate_cancel_refused_kunit",
    "swapz_round053_retired_late_callback_refused_kunit",
)


class OriginalGateSourceError(ValueError):
    """Real composed original C no-owner gate contract was not established."""


def function(source: str, signature: str) -> str:
    try:
        return prior["function"](source, signature)
    except prior["OriginalCPreUnuseSourceError"] as error:
        raise OriginalGateSourceError("missing_original_C:" + signature) from error


def ordered(source: str, label: str, *tokens: str) -> None:
    offset = -1
    for token in tokens:
        offset = source.find(token, offset + 1)
        if offset < 0:
            raise OriginalGateSourceError(label + ":" + token)


def verify(source: str) -> None:
    try:
        prior["verify"](source)
    except prior["OriginalCPreUnuseSourceError"] as error:
        raise OriginalGateSourceError("inherited_original_60_source:" + str(error)) from error
    start = source.find("/* ROUND053_ORIGINAL_PREUNUSE_GATE_NEGATIVE_BEGIN */")
    end = source.find("/* ROUND053_ORIGINAL_PREUNUSE_GATE_NEGATIVE_END */")
    if start < 0 or end < start or source.count(
            "/* ROUND053_ORIGINAL_PREUNUSE_GATE_NEGATIVE_BEGIN */") != 1 or \
            source.count("/* ROUND053_ORIGINAL_PREUNUSE_GATE_NEGATIVE_END */") != 1 or \
            not source.index("/* ROUND052_ORIGINAL_PRE_UNUSE_NEGATIVE_BEGIN */") < start < end < \
            source.index("/* ROUND052_ORIGINAL_PRE_UNUSE_NEGATIVE_END */"):
        raise OriginalGateSourceError("original_guarded_kernel_C_boundary")
    body = function(source, SOURCE_FUNCTION)
    ordered(body, "real_original_preunuse_noowner_gate",
            "if (!gate)", "return -EINVAL;",
            "if (gate->terminal)", "return -EALREADY;",
            "gate->terminal = true;",
            "if (gate->admission == SWAPZ_ROUND053_RETIRED_AFTER_UNUSE)",
            "return -ESTALE;",
            "if (gate->admission == SWAPZ_ROUND053_CLOSED_BEFORE_UNUSE)",
            "return -ESHUTDOWN;",
            "if (gate->admission != SWAPZ_ROUND053_OPEN_UNREGISTERED)",
            "return -EINVAL;",
            "if (!candidate)", "return -EINVAL;", "return -ENXIO;")
    if body.count("gate->terminal = true;") != 1 or \
            body.count("return -ENXIO;") != 1:
        raise OriginalGateSourceError("not_one_terminal_noowner_refusal")
    uncommented = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    for forbidden in ("folio_dup_swap", "folio_put_swap", "swap_put_entries_direct",
                      "get_swap_device", "submit_bio", "queue_work",
                      "cancel_work_sync", "flush_work", "dm_get_live_table"):
        if re.search(r"\b" + forbidden + r"\s*\(", uncommented):
            raise OriginalGateSourceError("fabricated_owner_or_blocking_wait:" + forbidden)
    writer = function(source, "static int zswap_writeback_entry(struct zswap_entry *entry,")
    if SOURCE_FUNCTION.replace("static noinline int ", "") in writer:
        raise OriginalGateSourceError("normal_original_writeback_changed")
    if source.count('"' + SUITE + '"') != 1 or \
            source.count("kunit_test_suite(swapz_round053_preunuse_gate_negative_suite);") != 1:
        raise OriginalGateSourceError("actual_original_KUnit_suite_missing")
    for name in CASES:
        if source.count("KUNIT_CASE(" + name + ")") != 1:
            raise OriginalGateSourceError("missing_registered_real_C_case:" + name)
    live = function(source, "static void swapz_round053_unregistered_source_refused_kunit(")
    ordered(live, "original_locked_uncached_folio_cleanup",
            "folio_alloc(GFP_KERNEL, 0)", "KUNIT_ASSERT_NOT_NULL(test, folio)",
            "xa_init(&tree)", "folio_lock(folio)", "swp_entry(1U, 37U)",
            "folio_test_locked(folio)", "folio_test_swapcache(folio)",
            "swapz_round053_preunuse_gate_refuse(", "-ENXIO)",
            "folio_unlock(folio)", "xa_destroy(&tree)", "folio_put(folio)")
    closed = function(source, "static void swapz_round053_closed_duplicate_cancel_refused_kunit(")
    ordered(closed, "no_cancel_after_gate_close",
            "SWAPZ_ROUND053_CLOSED_BEFORE_UNUSE",
            "swapz_round053_preunuse_gate_refuse(", "-ESHUTDOWN)",
            "KUNIT_EXPECT_TRUE(test, gate.terminal)",
            "swapz_round053_preunuse_gate_refuse(", "-EALREADY)")
    retired = function(source, "static void swapz_round053_retired_late_callback_refused_kunit(")
    ordered(retired, "late_after_original_retire_no_deref",
            "SWAPZ_ROUND053_RETIRED_AFTER_UNUSE",
            "swapz_round053_preunuse_gate_refuse(", "-ESTALE)",
            "KUNIT_EXPECT_TRUE(test, gate.terminal)",
            "swapz_round053_preunuse_gate_refuse(", "-EALREADY)")


MUTATIONS = (
    (SOURCE_FUNCTION, "if (!gate)", "if (false)"),
    (SOURCE_FUNCTION, "if (gate->terminal)", "if (false)"),
    (SOURCE_FUNCTION, "gate->terminal = true;", "gate->terminal = false;"),
    (SOURCE_FUNCTION, "if (gate->admission == SWAPZ_ROUND053_RETIRED_AFTER_UNUSE)", "if (false)"),
    (SOURCE_FUNCTION, "return -ESTALE;", "return 0;"),
    (SOURCE_FUNCTION, "if (gate->admission == SWAPZ_ROUND053_CLOSED_BEFORE_UNUSE)", "if (false)"),
    (SOURCE_FUNCTION, "return -ESHUTDOWN;", "return 0;"),
    (SOURCE_FUNCTION, "if (gate->admission != SWAPZ_ROUND053_OPEN_UNREGISTERED)", "if (false)"),
    (SOURCE_FUNCTION, "if (!candidate)", "if (false)"),
    (SOURCE_FUNCTION, "return -ENXIO;", "return 0;"),
    (None, "KUNIT_CASE(swapz_round053_unregistered_source_refused_kunit)", "/* removed */"),
    (None, "KUNIT_CASE(swapz_round053_closed_duplicate_cancel_refused_kunit)", "/* removed */"),
    (None, "KUNIT_CASE(swapz_round053_retired_late_callback_refused_kunit)", "/* removed */"),
    ("static void swapz_round053_unregistered_source_refused_kunit(",
     "folio_put(folio);", "/* leaked folio */"),
)


class SourceHostileTests(unittest.TestCase):
    source = ""

    def test_original_kernel_C_scope(self) -> None:
        verify(self.source)

    def test_fourteen_new_real_C_function_mutations(self) -> None:
        self.assertEqual(len(MUTATIONS), 14)
        for index, (signature, old, new) in enumerate(MUTATIONS):
            with self.subTest(original_C_guard_mutant=index):
                region = function(self.source, signature) if signature else self.source
                self.assertEqual(region.count(old), 1, "not unique in original C")
                mutant = self.source.replace(region, region.replace(old, new, 1), 1)
                self.assertNotEqual(mutant, self.source)
                with self.assertRaises(OriginalGateSourceError):
                    verify(mutant)


def load_source(root: Path) -> str:
    file = root / "mm/zswap.c"
    if root.is_symlink() or not root.is_dir() or file.is_symlink() or \
            not file.is_file() or not 0 < file.stat().st_size < 450_000:
        raise OriginalGateSourceError("real_staged_original_zswap_C_required")
    return file.read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        source = load_source(args.linux_root)
        if args.self_test:
            SourceHostileTests.source = source
            tests = unittest.defaultTestLoader.loadTestsFromTestCase(SourceHostileTests)
            if not unittest.TextTestRunner(verbosity=2).run(tests).wasSuccessful():
                return 1
        else:
            verify(source)
    except (OriginalGateSourceError, OSError, UnicodeError) as error:
        print("ROUND053_ORIGINAL_PREUNUSE_SOURCE_BLOCKED first_error=" + str(error))
        return 2
    print("ROUND053_ORIGINAL_STAGED_REAL_C_14_NEW_HOSTILES_PASS "
          "REGISTERED_C_KUNIT=3 COUNTED_SOURCE_OWNER=NOT_ACQUIRED "
          "SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
