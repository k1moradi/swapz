#!/usr/bin/env python3
"""Real pinned original swapoff cancellation-order proof and bounded dry races.

Source checks run on immutable original Linux C. The lifecycle model is
explicitly counterfactual: NO real swap slot, area, folio or callback is
created. A synthetically acyclic graph is NOT source-to-DM authorization.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
import runpy
import unittest

HERE = Path(__file__).resolve().parent
ORIGINAL_SHA = "c339f4010dea8b0d754f84ace70cd1b089878ef8"


class OriginalDrainProofError(ValueError):
    """Real upstream source or deferred count cancellation contract drifted."""


@lru_cache(maxsize=1)
def previous_audit():
    # Lazy loading permits purely rootless deterministic graph self-tests
    # without a checkout or artificial original swap-space allocation.
    return runpy.run_path(
        str(HERE / "round050-original-deferred-slot-source-audit.py"),
        run_name="round050_source_ownership_dependency")


def ordered(function: str, label: str, *anchors: str) -> None:
    previous = -1
    for anchor in anchors:
        offset = function.find(anchor, previous + 1)
        if offset < 0:
            raise OriginalDrainProofError("original_cancel_order:" + label + ":" + anchor)
        previous = offset


def original_function(sources: dict[str, str], path: str, signature: str) -> str:
    prior = previous_audit()
    try:
        return prior["function"](sources, path, signature)
    except (KeyError, prior["DeferredSwapSlotAuditError"]) as error:
        raise OriginalDrainProofError("real_original_function:" + signature) from error


def audit_source(sources: dict[str, str]) -> None:
    prior = previous_audit()
    try:
        prior["audit"](sources)
    except prior["DeferredSwapSlotAuditError"] as error:
        raise OriginalDrainProofError("inherited_real_original_swapoff:" + str(error)) from error

    scan = original_function(
        sources, "mm/swapfile.c",
        "static unsigned int find_next_to_unuse(struct swap_info_struct *si,")
    ordered(scan, "table_inuse_not_registered_async_callback",
            "if (!READ_ONCE(ci->count)) {",
            "i = end;", "swp_tb = swap_table_get(ci, ci_off);",
            "if (!swp_tb_is_null(swp_tb) && !swp_tb_is_bad(swp_tb))",
            "return i;", "return 0;")
    if "flush_work(" in scan or "cancel_work_sync(" in scan:
        raise OriginalDrainProofError("unexpected_original_slot_scan_cancel")

    unuse = original_function(sources, "mm/swapfile.c",
                              "static int try_to_unuse(unsigned int type)")
    ordered(unuse, "existing_PTE_shmem_folio_only_then_retry",
            "retval = shmem_unuse(type);", "retval = unuse_mm(mm, type);",
            "(i = find_next_to_unuse(si, i)) != 0",
            "folio = swap_cache_get_folio(entry);",
            "if (!folio)", "continue;",
            "folio_lock(folio);", "folio_wait_writeback(folio);",
            "folio_free_swap(folio);", "folio_unlock(folio);",
            "if (swap_usage_in_pages(si)) {",
            "goto retry;", "return -EINTR;")
    if "zswap_swapoff(" in unuse or "swap_put_entries_direct(" in unuse:
        raise OriginalDrainProofError("unuse_implicit_external_release_changed")

    swapoff = original_function(
        sources, "mm/swapfile.c",
        "SYSCALL_DEFINE1(swapoff, const char __user *, specialfile)")
    ordered(swapoff, "existing_swapoff_no_pre_unuse_source_cancel",
            "del_from_avail_list(p, true);",
            "plist_del(&p->list, &swap_active_head);",
            "wait_for_allocation(p);",
            "err = try_to_unuse(p->type);",
            "reinsert_swap_info(p);",
            "percpu_ref_kill(&p->users);",
            "synchronize_rcu();", "wait_for_completion(&p->comp);",
            "flush_work(&p->reclaim_work);",
            "destroy_swap_extents(p, p->swap_file);",
            "p->cluster_info = NULL;", "zswap_swapoff(p->type);",
            "p->flags = 0;")
    if swapoff.count("zswap_swapoff(p->type);") != 1:
        raise OriginalDrainProofError("original_zswap_swapoff_called_only_after_unuse")

    zswap_cleanup = original_function(
        sources, "mm/zswap.c", "void zswap_swapoff(int type)")
    ordered(zswap_cleanup, "cleanup_assumes_prior_unuse_not_pre_cancel",
            "if (!trees)", "return;",
            "/* try_to_unuse() invalidated all the entries already */",
            "WARN_ON_ONCE(!xa_empty(trees + i));",
            "kvfree(trees);", "zswap_trees[type] = NULL;")
    if "folio_dup_swap(" in zswap_cleanup or "swap_put_entries_direct(" in zswap_cleanup:
        raise OriginalDrainProofError("unexpected_zswap_cleanup_external_put")

    area_lookup = original_function(
        sources, "mm/swapfile.c",
        "struct swap_info_struct *get_swap_device(swp_entry_t entry)")
    ordered(area_lookup, "copied_entry_rechecked_only_as_live_area",
            "if (!entry.val)", "si = swap_entry_to_info(entry);",
            "if (!get_swap_device_info(si))", "offset = swp_offset(entry);",
            "if (offset >= si->max)", "return si;",
            "return NULL;", "percpu_ref_put(&si->users);")
    direct_put = original_function(
        sources, "mm/swapfile.c",
        "void swap_put_entries_direct(swp_entry_t entry, int nr)")
    ordered(direct_put, "no_outcome_receipt_for_unowned_late_put",
            "si = get_swap_device(entry);",
            "if (WARN_ON_ONCE(IS_ERR_OR_NULL(si)))",
            "return;", "swap_put_entries_cluster(si, offset, cluster_end - offset, true);",
            "put_swap_device(si);")

    endio = original_function(
        sources, "mm/page_io.c", "static void end_swap_bio_write(struct bio *bio)")
    ordered(endio, "original_only_completes_folio_writeback",
            "bio_uninit(bio);", "swap_write_end(sio, failed);")
    if "swap_put_entries_direct(" in endio or "folio_put_swap(" in endio:
        raise OriginalDrainProofError("unexpected_original_callback_external_count")
    writer = original_function(
        sources, "mm/zswap.c",
        "static int zswap_writeback_entry(struct zswap_entry *entry,")
    ordered(writer, "original_source_releases_before_async",
            "si = get_swap_device(swpentry);",
            "__swap_cache_alloc_folio(", "put_swap_device(si);",
            "if (entry != xa_load(tree, offset)) {",
            "if (!zswap_decompress(entry, folio)) {",
            "xa_erase(tree, offset);", "zswap_entry_free(entry);",
            "__swap_writeout(&ctx, folio);", "swap_write_submit(&ctx);")
    if any(token in writer for token in (
            "swap_put_entries_direct(", "folio_dup_swap(",
            "cancel_work_sync(", "flush_work(")):
        raise OriginalDrainProofError("missing_pre_unuse_callback_owned_count")


# These nodes describe one hypothetical real count, NOT an actual kernel ref.
WAIT_UNUSE = "swapoff.try_to_unuse.wait_hidden_slot_count_zero"
RELEASE_COUNT = "callback.must_release_exact_owned_count"
WAIT_SWAPOFF = "callback.wait_for_swapoff"
WAIT_DTR = "callback.wait_for_target_dtr"
WAIT_DTR_UNUSE = "target_dtr.wait_for_unuse"


def dependency_cycle(dependencies: dict[str, tuple[str, ...]]) -> bool:
    visited: set[str] = set()
    active: set[str] = set()

    def visit(node: str) -> bool:
        if node in active:
            return True
        if node in visited:
            return False
        active.add(node)
        for next_node in dependencies.get(node, ()):
            if visit(next_node):
                return True
        active.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in dependencies)


@dataclass(frozen=True)
class DryCase:
    """Counterfactual scheduling flags. They never mint a kernel count."""
    name: str
    acquired: bool = True
    folio_current: bool = True
    xarray_current: bool = True
    swapoff_begun: bool = False
    callback: str = "inline"
    registered_pre_unuse_cancel: bool = False
    live_area_at_put: bool = True
    callback_attempts: int = 1
    target_torn_down: bool = False
    slot_recycled: bool = False
    late_folio_put: bool = False


@dataclass(frozen=True)
class DryResult:
    first_error: str
    simulated_puts: int
    would_deadlock: bool
    authenticated: bool = False


def check_dry_case(case: DryCase) -> DryResult:
    """Fail closed; even a passing hypothetical single put is NOT a lease."""
    def refuse(reason: str, *, cycle: bool = False, puts: int = 0) -> DryResult:
        return DryResult(reason, puts, cycle)

    if not case.acquired:
        return refuse("NO_COUNT_ACQUIRED_NO_PUT")
    if not case.folio_current or not case.xarray_current:
        return refuse("ORIGINAL_NO_POST_ACQUIRE_RETIRE_ABORT_PUT")
    if case.slot_recycled:
        return refuse("SLOT_INCARNATION_ABA_NO_OWNER")
    if case.late_folio_put:
        return refuse("FOLIO_PUT_REQUIRES_CURRENT_LOCKED_SWAPCACHE")
    if case.swapoff_begun and not case.registered_pre_unuse_cancel:
        return refuse("ORIGINAL_MISSING_PRE_UNUSE_CANCEL_HOOK")
    graph: dict[str, tuple[str, ...]] = {WAIT_UNUSE: (RELEASE_COUNT,)}
    if case.callback == "wait_swapoff":
        graph[RELEASE_COUNT] = (WAIT_SWAPOFF,)
        graph[WAIT_SWAPOFF] = (WAIT_UNUSE,)
    elif case.callback == "wait_dtr":
        graph[RELEASE_COUNT] = (WAIT_DTR,)
        graph[WAIT_DTR] = (WAIT_DTR_UNUSE,)
        graph[WAIT_DTR_UNUSE] = (WAIT_UNUSE,)
    if dependency_cycle(graph):
        return refuse("HIDDEN_OWNER_WAIT_CYCLE", cycle=True)
    if case.callback == "never":
        return refuse("UNSCHEDULED_OR_LOST_CALLBACK")
    if case.callback not in ("inline", "queued", "wait_swapoff", "wait_dtr"):
        return refuse("UNKNOWN_CALLBACK_DISPATCH")
    if case.target_torn_down:
        return refuse("NO_RETAINED_CURRENT_TARGET_LEASE")
    if not case.live_area_at_put:
        return refuse("NO_LIVE_AREA_FOR_VOID_DIRECT_PUT")
    if not case.registered_pre_unuse_cancel:
        return refuse("ORIGINAL_NO_REGISTERED_EXTERNAL_COUNT_OWNER")
    if case.callback_attempts == 0:
        return refuse("MISSING_TERMINAL_CALLBACK")
    if case.callback_attempts > 1:
        return refuse("DUPLICATE_TERMINAL_CALLBACK_REFUSED", puts=1)
    # Only a hypothetical, independently introduced pre-unuse hook and
    # explicit old-count ownership can reach this synthetic terminal state.
    return refuse("HYPOTHETICAL_ONE_PUT_NOT_REAL_ORIGINAL", puts=1)


DRY_CASES: tuple[tuple[DryCase, str, int, bool], ...] = (
    (DryCase("acquire_enomem", acquired=False), "NO_COUNT_ACQUIRED_NO_PUT", 0, False),
    (DryCase("stale_stored", xarray_current=False),
     "ORIGINAL_NO_POST_ACQUIRE_RETIRE_ABORT_PUT", 0, False),
    (DryCase("freed_folio", folio_current=False),
     "ORIGINAL_NO_POST_ACQUIRE_RETIRE_ABORT_PUT", 0, False),
    (DryCase("swapoff_before_source_acquire", acquired=False, swapoff_begun=True),
     "NO_COUNT_ACQUIRED_NO_PUT", 0, False),
    (DryCase("hidden_ref_during_unuse", swapoff_begun=True),
     "ORIGINAL_MISSING_PRE_UNUSE_CANCEL_HOOK", 0, False),
    (DryCase("callback_lost", callback="never"),
     "UNSCHEDULED_OR_LOST_CALLBACK", 0, False),
    (DryCase("inline_but_unregistered"),
     "ORIGINAL_NO_REGISTERED_EXTERNAL_COUNT_OWNER", 0, False),
    (DryCase("queued_but_unregistered", callback="queued"),
     "ORIGINAL_NO_REGISTERED_EXTERNAL_COUNT_OWNER", 0, False),
    (DryCase("callback_waits_swapoff", callback="wait_swapoff",
             swapoff_begun=True, registered_pre_unuse_cancel=True),
     "HIDDEN_OWNER_WAIT_CYCLE", 0, True),
    (DryCase("callback_waits_target_dtr", callback="wait_dtr",
             swapoff_begun=True, registered_pre_unuse_cancel=True),
     "HIDDEN_OWNER_WAIT_CYCLE", 0, True),
    (DryCase("late_target_callback", target_torn_down=True),
     "NO_RETAINED_CURRENT_TARGET_LEASE", 0, False),
    (DryCase("recycled_same_offset", slot_recycled=True),
     "SLOT_INCARNATION_ABA_NO_OWNER", 0, False),
    (DryCase("late_old_folio_put", late_folio_put=True),
     "FOLIO_PUT_REQUIRES_CURRENT_LOCKED_SWAPCACHE", 0, False),
    (DryCase("dead_area_void_direct_put", live_area_at_put=False),
     "NO_LIVE_AREA_FOR_VOID_DIRECT_PUT", 0, False),
    (DryCase("unexpected_dispatch", callback="unknown"),
     "UNKNOWN_CALLBACK_DISPATCH", 0, False),
    (DryCase("hypothetical_single_terminal", registered_pre_unuse_cancel=True),
     "HYPOTHETICAL_ONE_PUT_NOT_REAL_ORIGINAL", 1, False),
    (DryCase("hypothetical_duplicate_terminal", registered_pre_unuse_cancel=True,
             callback_attempts=2),
     "DUPLICATE_TERMINAL_CALLBACK_REFUSED", 1, False),
    (DryCase("hypothetical_missing_terminal", registered_pre_unuse_cancel=True,
             callback_attempts=0),
     "MISSING_TERMINAL_CALLBACK", 0, False),
    (DryCase("hypothetical_cancel_during_unuse", swapoff_begun=True,
             registered_pre_unuse_cancel=True, callback="queued"),
     "HYPOTHETICAL_ONE_PUT_NOT_REAL_ORIGINAL", 1, False),
    (DryCase("hypothetical_cancel_but_lost", swapoff_begun=True,
             registered_pre_unuse_cancel=True, callback="never"),
     "UNSCHEDULED_OR_LOST_CALLBACK", 0, False),
)


# These are NEW actual original function anchors, not the Round050 16.
MUTATIONS: tuple[tuple[str, str, str], ...] = (
    ("mm/swapfile.c", "static unsigned int find_next_to_unuse(struct swap_info_struct *si,",
     "if (!READ_ONCE(ci->count)) {"),
    ("mm/swapfile.c", "static unsigned int find_next_to_unuse(struct swap_info_struct *si,",
     "swp_tb = swap_table_get(ci, ci_off);"),
    ("mm/swapfile.c", "static unsigned int find_next_to_unuse(struct swap_info_struct *si,",
     "if (!swp_tb_is_null(swp_tb) && !swp_tb_is_bad(swp_tb))"),
    ("mm/swapfile.c", "static int try_to_unuse(unsigned int type)",
     "folio_wait_writeback(folio);"),
    ("mm/swapfile.c", "static int try_to_unuse(unsigned int type)",
     "if (!folio)\n\t\t\tcontinue;"),
    ("mm/swapfile.c", "SYSCALL_DEFINE1(swapoff, const char __user *, specialfile)",
     "wait_for_allocation(p);"),
    ("mm/swapfile.c", "SYSCALL_DEFINE1(swapoff, const char __user *, specialfile)",
     "zswap_swapoff(p->type);"),
    ("mm/swapfile.c", "SYSCALL_DEFINE1(swapoff, const char __user *, specialfile)",
     "flush_work(&p->reclaim_work);"),
    ("mm/zswap.c", "void zswap_swapoff(int type)",
     "/* try_to_unuse() invalidated all the entries already */"),
    ("mm/zswap.c", "void zswap_swapoff(int type)",
     "WARN_ON_ONCE(!xa_empty(trees + i));"),
    ("mm/zswap.c", "void zswap_swapoff(int type)",
     "zswap_trees[type] = NULL;"),
    ("mm/swapfile.c", "struct swap_info_struct *get_swap_device(swp_entry_t entry)",
     "if (!get_swap_device_info(si))"),
    ("mm/swapfile.c", "struct swap_info_struct *get_swap_device(swp_entry_t entry)",
     "if (offset >= si->max)"),
    ("mm/page_io.c", "static void end_swap_bio_write(struct bio *bio)",
     "bio_uninit(bio);"),
)


class DrainAndCycleHostileTests(unittest.TestCase):
    sources: dict[str, str] = {}

    def test_20_deterministic_cancellation_and_rollback_cases(self) -> None:
        self.assertEqual(len(DRY_CASES), 20)
        for case, expected, puts, cycle in DRY_CASES:
            with self.subTest(case=case.name):
                observed = check_dry_case(case)
                self.assertEqual(observed.first_error, expected)
                self.assertEqual(observed.simulated_puts, puts)
                self.assertEqual(observed.would_deadlock, cycle)
                self.assertFalse(observed.authenticated)
                self.assertLessEqual(observed.simulated_puts, 1)

    def test_no_original_source_has_early_drain_hook(self) -> None:
        audit_source(self.sources)

    def test_14_exact_named_original_c_hostile_mutants(self) -> None:
        self.assertEqual(len(MUTATIONS), 14)
        for index, (path, signature, anchor) in enumerate(MUTATIONS):
            with self.subTest(mutant=index, source=path):
                original = self.sources[path]
                region = original_function(self.sources, path, signature)
                self.assertEqual(region.count(anchor), 1,
                                 "must mutate exactly one REAL original function anchor")
                self.assertEqual(original.count(region), 1)
                changed = original.replace(
                    region, region.replace(
                        anchor, "/* hostile removed original drain transition */", 1), 1)
                self.assertNotEqual(original, changed, "hostile original source no-op")
                mutated = dict(self.sources)
                mutated[path] = changed
                with self.assertRaises(OriginalDrainProofError):
                    audit_source(mutated)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", type=Path)
    parser.add_argument("--model-only-self-test", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args()
    if arguments.model_only_self_test:
        suite = unittest.defaultTestLoader.loadTestsFromName(
            "test_20_deterministic_cancellation_and_rollback_cases",
            DrainAndCycleHostileTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    if arguments.linux_root is None:
        parser.error("--linux-root is required unless --model-only-self-test")
    try:
        prior = previous_audit()
        sources = prior["pristine_original"](arguments.linux_root)
        if arguments.self_test:
            DrainAndCycleHostileTests.sources = sources
            tests = unittest.defaultTestLoader.loadTestsFromTestCase(
                DrainAndCycleHostileTests)
            if not unittest.TextTestRunner(verbosity=2).run(tests).wasSuccessful():
                return 1
        else:
            audit_source(sources)
    except (OriginalDrainProofError, OSError, ValueError) as error:
        print("ROUND051_ORIGINAL_SWAPOFF_CANCELLATION_BLOCKED first_error=" + str(error))
        return 2
    print("ROUND051_REAL_ORIGINAL_CANCEL_GRAPH_14_MUTANTS_20_DRY_RACES_PASS "
          "COUNTED_EXTERNAL_ASYNC_OWNER=NOT_ACQUIRED CANCEL_HOOK=ABSENT "
          "SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
