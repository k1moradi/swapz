#!/usr/bin/env python3
"""Verify staged original release-order C and distinct hostile mutations."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import runpy

HERE = Path(__file__).resolve().parent
prior = runpy.run_path(str(HERE / "round053-original-preunuse-source-verify.py"),
                      run_name="round054_original_63_dependency")
SIGNATURE = "static noinline int swapz_round054_release_refuse("
CASES = ["swapz_round054_slot_type_incarnation_kunit","swapz_round054_store_retirement_kunit","swapz_round054_close_never_dispatch_kunit"]
TOKENS = [
    "if (!snapshot)",
    "return -EINVAL;",
    "if (snapshot->terminal)",
    "return -EALREADY;",
    "snapshot->terminal = true;",
    "if (snapshot->closed)",
    "return -ESHUTDOWN;",
    "if (!snapshot->slot.val || !snapshot->incarnation ||",
    "!observed_slot.val || !observed_incarnation)",
    "return -EINVAL;",
    "if (snapshot->slot.val != observed_slot.val ||",
    "snapshot->incarnation != observed_incarnation)",
    "return -ESTALE;",
    "if (!stored_current || !folio_locked)",
    "return -ESTALE;",
    "if (!callback_dispatched)",
    "return -ENXIO;",
    "return -EOPNOTSUPP;"
]
MUTATIONS = [
    [
        "snapshot->closed",
        "false"
    ],
    [
        "!snapshot->incarnation",
        "false"
    ],
    [
        "!observed_incarnation",
        "false"
    ],
    [
        "snapshot->slot.val != observed_slot.val",
        "false"
    ],
    [
        "snapshot->incarnation != observed_incarnation",
        "false"
    ],
    [
        "!stored_current",
        "false"
    ],
    [
        "!folio_locked",
        "false"
    ],
    [
        "!callback_dispatched",
        "false"
    ],
    [
        "return -ENXIO;",
        "return 0;"
    ],
    [
        "return -EOPNOTSUPP;",
        "return 0;"
    ]
]


def verify(source: str) -> None:
    prior["verify"](source)
    start = "/* ROUND054_ORIGINAL_PREUNUSE_RELEASE_NEGATIVE_BEGIN */"
    end = "/* ROUND054_ORIGINAL_PREUNUSE_RELEASE_NEGATIVE_END */"
    if source.count(start) != 1 or source.count(end) != 1 or not (
            source.index("/* ROUND053_ORIGINAL_PREUNUSE_GATE_NEGATIVE_END */")
            < source.index(start) < source.index(end)
            < source.index("/* ROUND052_ORIGINAL_PRE_UNUSE_NEGATIVE_END */")):
        raise ValueError("new_C_NOT_INSIDE_INHERITED_DEFAULT_OFF_GUARD")
    helper = prior["function"](source, SIGNATURE)
    prior["ordered"](helper, "round054_release_order", *TOKENS)
    uncommented = re.sub(r"/\*.*?\*/", "", helper, flags=re.DOTALL)
    if "return 0;" in uncommented or any(
            name in uncommented for name in (
            "folio_dup_swap(", "folio_put_swap(", "swap_put_entries_direct(",
            "get_swap_device(", "submit_bio(", "cancel_work_sync(",
            "queue_work(", "flush_work(", "dm_get_live_table(")):
        raise ValueError("fabricated_release_or_async_authority")
    if source.count("kunit_test_suite(swapz_round054_release_negative_suite);") != 1:
        raise ValueError("new_original_KUnit_suite_missing")
    for case in CASES:
        if source.count("KUNIT_CASE(" + case + ")") != 1:
            raise ValueError("new_registered_C_case_missing:" + case)
    retire = prior["function"](source, "static void swapz_round054_store_retirement_kunit(")
    prior["ordered"](retire, "actual_kernel_object_retirement",
        "folio_alloc(GFP_KERNEL, 0)", "xa_init(&tree)",
        "xa_store(&tree, swp_offset(initial.slot)", "folio_lock(folio)",
        "folio_test_swapcache(folio)", "xa_load(&tree, swp_offset(initial.slot))",
        "-EOPNOTSUPP);", "xa_erase(&tree, swp_offset(initial.slot))",
        "xa_load(&tree, swp_offset(initial.slot))", "folio_unlock(folio);",
        "folio_put(folio);", "xa_destroy(&tree);", "-EALREADY);", "-ESTALE);")
    writer = prior["function"](source, "static int zswap_writeback_entry(struct zswap_entry *entry,")
    if "swapz_round054_release_refuse(" in writer:
        raise ValueError("normal_original_writeback_modified")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        source = prior["load_source"](args.linux_root)
        verify(source)
        region = prior["function"](source, SIGNATURE)
        for old, new in MUTATIONS:
            if region.count(old) != 1 or source.count(region) != 1:
                raise ValueError("nonunique_actual_staged_C_mutation:" + old)
            mutant = source.replace(region, region.replace(old, new, 1), 1)
            if mutant == source:
                raise ValueError("unchanged_actual_staged_C_mutation:" + old)
            try:
                verify(mutant)
            except ValueError:
                continue
            raise ValueError("surviving_actual_staged_C_mutation:" + old)
    except (OSError, ValueError) as error:
        print("ROUND054_STAGED_C_RELEASE_BLOCKED first_error=" + str(error))
        return 2
    print("ROUND054_STAGED_ORIGINAL_10_NEW_C_SOURCE_HOSTILES_PASS "
          "REGISTERED_C_KUNIT=3 ACTUAL_COUNT_OWNER=NO "
          "SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
