#!/usr/bin/env python3
"""Audit genuine pinned Linux counted swap-slot acquisition and release (NO_AUTH).

Requires an exact pristine upstream tree. Source anchors and hostile mutations
are negative evidence, not a transferred reference, booted KUnit or live I/O.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import runpy
import unittest

HERE = Path(__file__).resolve().parent
PREVIOUS = runpy.run_path(str(HERE / "round047-original-slot-incarnation-source-audit.py"),
                          run_name="round047_source_import")
ORIGINAL_BLOBS: dict[str, str] = {
    **PREVIOUS["ORIGINAL_BLOBS"],
    "mm/swap_state.c": "d9e36c505398f97ce64021cf181a9434c9faaddf",
}
PRIOR_AUDIT = PREVIOUS["audit"]
PRIOR_ERROR = PREVIOUS["OriginalSlotAuditError"]
FUNCTION_BODY = PREVIOUS["function_body"]


class CountedSlotOwnerEvidenceError(ValueError):
    """An original kernel counted-slot precondition/negative boundary drifted."""


def require_ordered(body: str, label: str, *tokens: str) -> None:
    previous = -1
    for token in tokens:
        position = body.find(token, previous + 1)
        if position < 0:
            raise CountedSlotOwnerEvidenceError("counted_slot_boundary:" + label + ":" + token)
        previous = position


def source_function(sources: dict[str, str], path: str, signature: str) -> str:
    try:
        return FUNCTION_BODY(sources[path], signature)
    except (KeyError, PRIOR_ERROR) as error:
        raise CountedSlotOwnerEvidenceError("original_function:" + path + ":" + signature) from error


def source_contract(source: str, signature: str, *tokens: str) -> None:
    if source.count(signature) != 1:
        raise CountedSlotOwnerEvidenceError("ambiguous_original_contract:" + signature)
    function_start = source.index(signature)
    comment_start = source.rfind("/*", 0, function_start)
    if comment_start < 0:
        raise CountedSlotOwnerEvidenceError("missing_original_contract:" + signature)
    require_ordered(source[comment_start:function_start], signature, *tokens)


def audit(sources: dict[str, str]) -> None:
    if set(sources) != set(ORIGINAL_BLOBS):
        raise CountedSlotOwnerEvidenceError("missing_pristine_original_source")
    swapfile = sources["mm/swapfile.c"]
    swapstate = sources["mm/swap_state.c"]

    # A counted PTE owner under PTL is not the swapcache folio pin.
    source_contract(swapfile, "int swap_dup_entry_direct(swp_entry_t entry)",
                    "Caller must ensure there is no race condition on the reference",
                    "locking the PTL of a PTE", "swap entry must have a count >= 1")
    direct = source_function(sources, "mm/swapfile.c",
                             "int swap_dup_entry_direct(swp_entry_t entry)")
    require_ordered(direct, "direct_needs_preowned_count",
                    "swap_entry_to_info(entry)",
                    "VM_WARN_ON_ONCE(!swap_entry_swapped(si, entry));",
                    "return swap_dup_entries_cluster(si, swp_offset(entry), 1);")
    lookup = source_function(sources, "mm/swapfile.c",
                             "bool swap_entry_swapped(struct swap_info_struct *si, swp_entry_t entry)")
    require_ordered(lookup, "count_lookup_not_retained_lock",
                    "ci = swap_cluster_lock(si, offset);",
                    "swap_cluster_unlock(ci);", "return swp_tb_get_count(swp_tb) > 0;")

    # Unlike the direct helper, folio_dup_swap can duplicate the counted slot
    # from a CURRENT locked swapcache folio, but is NOT called at writeback.
    source_contract(swapfile, "int folio_dup_swap(struct folio *folio, struct page *page)",
                    "Swap entries allocated to a folio has count == 0 and pinned",
                    "Context: Caller must ensure the folio is locked and in the swap cache.",
                    "swap_put_entries_direct")
    duplicate = source_function(sources, "mm/swapfile.c",
                                "int folio_dup_swap(struct folio *folio, struct page *page)")
    require_ordered(duplicate, "folio_count_acquire",
                    "VM_WARN_ON_FOLIO(!folio_test_locked(folio), folio);",
                    "VM_WARN_ON_FOLIO(!folio_test_swapcache(folio), folio);",
                    "return swap_dup_entries_cluster(swap_entry_to_info(entry),")
    count_one = source_function(sources, "mm/swapfile.c",
                                "static int __swap_cluster_dup_entry(struct swap_cluster_info *ci,")
    require_ordered(count_one, "slot_count_under_cluster_lock",
                    "lockdep_assert_held(&ci->lock);",
                    "count = __swp_tb_get_count(swp_tb);",
                    "if (WARN_ON_ONCE(!count && !swp_tb_is_folio(swp_tb)))",
                    "__swap_table_set(ci, ci_off, __swp_tb_mk_count(swp_tb, count + 1));")
    duplicate_range = source_function(sources, "mm/swapfile.c",
                                      "static int swap_dup_entries_cluster(struct swap_info_struct *si,")
    require_ordered(duplicate_range, "counted_dup_error_and_rollback",
                    "ci = swap_cluster_lock(si, offset);",
                    "err = __swap_cluster_dup_entry(ci, ci_off);",
                    "spin_unlock(&ci->lock);",
                    "err = swap_extend_table_alloc(si, ci, ci_off, GFP_ATOMIC);",
                    "spin_lock(&ci->lock);", "goto restart;",
                    "__swap_cluster_put_entry(ci, ci_off);")
    put_folio = source_function(sources, "mm/swapfile.c",
                                "void folio_put_swap(struct folio *folio, struct page *page)")
    require_ordered(put_folio, "internal_folio_slot_count_put",
                    "VM_WARN_ON_FOLIO(!folio_test_locked(folio), folio);",
                    "VM_WARN_ON_FOLIO(!folio_test_swapcache(folio), folio);",
                    "swap_put_entries_cluster(si, swp_offset(entry), nr_pages, false);")
    put_direct = source_function(sources, "mm/swapfile.c",
                                 "void swap_put_entries_direct(swp_entry_t entry, int nr)")
    require_ordered(put_direct, "independent_count_put_requires_owner",
                    "si = get_swap_device(entry);",
                    "swap_put_entries_cluster(si, offset, cluster_end - offset, true);",
                    "put_swap_device(si);")

    # The real initial/revalidation checks each hold ci->lock, and allocation
    # happens AFTER releasing that spinlock. These checks are not an external
    # retained owner of the slot after the folio is unlocked.
    slot_check = source_function(sources, "mm/swap_state.c",
                                 "static int __swap_cache_add_check(struct swap_cluster_info *ci,")
    require_ordered(slot_check, "cache_count_or_recycled_conflict",
                    "lockdep_assert_held(&ci->lock);", "if (swp_tb_is_folio(old_tb))",
                    "return -EEXIST;", "if (!__swp_tb_get_count(old_tb))",
                    "return -ENOENT;")
    source_contract(swapstate,
                    "struct folio *__swap_cache_alloc_folio(swp_entry_t targ_entry, gfp_t gfp,",
                    "The swap slot indicated by", "must have a non-zero swap count",
                    "The returned folio is locked", "Caller must protect the swap device")
    allocation = source_function(sources, "mm/swap_state.c",
                                 "static struct folio *__swap_cache_alloc(struct swap_cluster_info *ci,")
    require_ordered(allocation, "two_count_checks_no_sleep_under_cluster_spinlock",
                    "spin_lock(&ci->lock);",
                    "err = __swap_cache_add_check(ci, targ_entry, nr_pages, NULL, NULL);",
                    "spin_unlock(&ci->lock);",
                    "folio = folio_alloc_mpol(gfp, order, mpol, ilx, numa_node_id());",
                    "spin_lock(&ci->lock);",
                    "err = __swap_cache_add_check(ci, targ_entry, nr_pages, &shadow, &memcg_id);",
                    "__folio_set_locked(folio);", "__swap_cache_do_add_folio(ci, folio, entry);",
                    "spin_unlock(&ci->lock);")
    add = source_function(sources, "mm/swap_state.c",
                          "static void __swap_cache_do_add_folio(struct swap_cluster_info *ci,")
    require_ordered(add, "cache_stores_current_folio_identity",
                    "folio_ref_add(folio, nr_pages);", "folio_set_swapcache(folio);",
                    "folio->swap = entry;")
    delete = source_function(sources, "mm/swap_state.c",
                             "static void __swap_cache_do_del_folio(struct swap_cluster_info *ci,")
    require_ordered(delete, "cache_remove_blocks_writeback_and_can_release_slot",
                    "VM_WARN_ON_ONCE_FOLIO(folio_test_writeback(folio), folio);",
                    "folio_clear_swapcache(folio);",
                    "__swap_cluster_free_entries(si, ci, ci_start, nr_pages);")

    # The real zswap source internally owns the locked folio, then destroys its
    # STORED object, and proceeds with original full uncompressed swap WRITE.
    # It does NOT call the counted ref acquisition or callback owner release.
    writeback = source_function(sources, "mm/zswap.c",
                                "static int zswap_writeback_entry(struct zswap_entry *entry,")
    require_ordered(writeback, "last_original_locked_owner_scope",
                    "si = get_swap_device(swpentry);", "__swap_cache_alloc_folio(",
                    "put_swap_device(si);", "if (IS_ERR(folio))",
                    "if (entry != xa_load(tree, offset)) {",
                    "zswap_decompress(entry, folio)", "xa_erase(tree, offset);",
                    "zswap_entry_free(entry);", "folio_put(folio);",
                    "__swap_writeout(&ctx, folio);", "swap_write_submit(&ctx);")
    for forbidden in ("folio_dup_swap(", "swap_dup_entry_direct(",
                      "swap_put_entries_direct("):
        if forbidden in writeback:
            raise CountedSlotOwnerEvidenceError("not_proved_external_counted_owner:" + forbidden)
    require_ordered(writeback, "error_cannot_transfer_source_owner",
                    "err:", "swap_cache_del_folio(folio);",
                    "folio_unlock(folio);", "folio_put(folio);", "return ret;")
    start_write = source_function(sources, "mm/page_io.c",
                                  "void __swap_writeout(struct swap_io_ctx *ctx, struct folio *folio)")
    require_ordered(start_write, "handoff_unlocks_folio_without_external_count",
                    "folio_start_writeback(folio);", "folio_unlock(folio);",
                    "swap_add_folio(ctx, folio, WRITE);")
    dropbehind = source_function(sources, "mm/swap_state.c",
                                  "void swap_writeback_dropbehind_folio(struct folio *folio)")
    require_ordered(dropbehind, "async_writeback_dropbehind_may_find_recycled_cache",
                    "folio_lock(folio);",
                    "if (!folio_test_swapcache(folio) || folio_test_writeback(folio) ||",
                    "folio_clear_dropbehind(folio);", "folio_add_lru(folio);",
                    "folio_unlock(folio);", "folio_put(folio);")
    end_write = source_function(sources, "mm/page_io.c",
                                "static void end_swap_bio_write(struct bio *bio)")
    require_ordered(end_write, "original_async_bio_end_not_external_count_release",
                    "bio_uninit(bio);", "swap_write_end(sio, failed);")
    finish_write = source_function(sources, "mm/page_io.c",
                                   "static void swap_write_end(struct swap_iocb *sio, bool failed)")
    require_ordered(finish_write, "original_internal_folio_completion",
                    "folio_end_writeback(folio);", "mempool_free(sio, sio_pool);")

    # All previous five-original-source lifetime checks and 18 hostile controls
    # remain separately exercised by their prior complete validator.
    try:
        PRIOR_AUDIT({name: sources[name] for name in PREVIOUS["ORIGINAL_BLOBS"]})
    except PRIOR_ERROR as error:
        raise CountedSlotOwnerEvidenceError("inherited_round047:" + str(error)) from error


def pristine_original(root: Path) -> dict[str, str]:
    sources = PREVIOUS["load_original"](root)
    path = root / "mm/swap_state.c"
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size < 200_000:
        raise CountedSlotOwnerEvidenceError("missing_original_swap_state")
    data = path.read_bytes()
    git_object = (b"blob " + str(len(data)).encode("ascii") + b"\0" + data)
    if hashlib.sha1(git_object).hexdigest() != ORIGINAL_BLOBS["mm/swap_state.c"]:
        raise CountedSlotOwnerEvidenceError("wrong_pristine_original_swap_state_blob")
    try:
        sources["mm/swap_state.c"] = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CountedSlotOwnerEvidenceError("non_utf8_original_swap_state") from error
    return sources


class CountedSlotHostileTests(unittest.TestCase):
    sources: dict[str, str] = {}

    def test_pristine_original_counted_slot_contract(self) -> None:
        audit(self.sources)

    def test_16_function_scoped_original_counted_slot_hostile_mutations(self) -> None:
        changes = (
            ("mm/swapfile.c", "int folio_dup_swap(struct folio *folio, struct page *page)",
             "VM_WARN_ON_FOLIO(!folio_test_locked(folio), folio);"),
            ("mm/swapfile.c", "int folio_dup_swap(struct folio *folio, struct page *page)",
             "VM_WARN_ON_FOLIO(!folio_test_swapcache(folio), folio);"),
            ("mm/swapfile.c", "int folio_dup_swap(struct folio *folio, struct page *page)",
             "return swap_dup_entries_cluster(swap_entry_to_info(entry),"),
            ("mm/swapfile.c", "static int __swap_cluster_dup_entry(struct swap_cluster_info *ci,",
             "if (WARN_ON_ONCE(!count && !swp_tb_is_folio(swp_tb)))"),
            ("mm/swapfile.c", "static int swap_dup_entries_cluster(struct swap_info_struct *si,",
             "err = swap_extend_table_alloc(si, ci, ci_off, GFP_ATOMIC);"),
            ("mm/swapfile.c", "static int swap_dup_entries_cluster(struct swap_info_struct *si,",
             "__swap_cluster_put_entry(ci, ci_off);"),
            ("mm/swapfile.c", "void swap_put_entries_direct(swp_entry_t entry, int nr)",
             "swap_put_entries_cluster(si, offset, cluster_end - offset, true);"),
            ("mm/swap_state.c", "static int __swap_cache_add_check(struct swap_cluster_info *ci,",
             "if (!__swp_tb_get_count(old_tb))"),
            ("mm/swap_state.c", "static struct folio *__swap_cache_alloc(struct swap_cluster_info *ci,",
             "err = __swap_cache_add_check(ci, targ_entry, nr_pages, &shadow, &memcg_id);"),
            ("mm/swap_state.c", "static void __swap_cache_do_add_folio(struct swap_cluster_info *ci,",
             "folio_set_swapcache(folio);"),
            ("mm/swap_state.c", "static void __swap_cache_do_del_folio(struct swap_cluster_info *ci,",
             "VM_WARN_ON_ONCE_FOLIO(folio_test_writeback(folio), folio);"),
            ("mm/swap_state.c", "void swap_writeback_dropbehind_folio(struct folio *folio)",
             "if (!folio_test_swapcache(folio) || folio_test_writeback(folio) ||"),
            ("mm/zswap.c", "static int zswap_writeback_entry(struct zswap_entry *entry,",
             "if (entry != xa_load(tree, offset)) {"),
            ("mm/zswap.c", "static int zswap_writeback_entry(struct zswap_entry *entry,",
             "zswap_entry_free(entry);"),
            ("mm/page_io.c", "void __swap_writeout(struct swap_io_ctx *ctx, struct folio *folio)",
             "folio_start_writeback(folio);"),
            ("mm/page_io.c", "static void end_swap_bio_write(struct bio *bio)",
             "swap_write_end(sio, failed);"),
        )
        self.assertEqual(len(changes), 16)
        for index, (name, signature, anchor) in enumerate(changes):
            with self.subTest(mutant=index, file=name):
                original = self.sources[name]
                function = source_function(self.sources, name, signature)
                self.assertEqual(function.count(anchor), 1,
                                 "original hostile target was not unique")
                self.assertEqual(original.count(function), 1,
                                 "original source function region was not unique")
                changed_function = function.replace(anchor, "/* hostile omitted counted owner */", 1)
                changed = original.replace(function, changed_function, 1)
                self.assertNotEqual(changed, original, "hostile mutation was a no-op")
                modified = dict(self.sources)
                modified[name] = changed
                with self.assertRaises(CountedSlotOwnerEvidenceError):
                    audit(modified)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        sources = pristine_original(args.linux_root)
        if args.self_test:
            CountedSlotHostileTests.sources = sources
            tests = unittest.defaultTestLoader.loadTestsFromTestCase(CountedSlotHostileTests)
            result = unittest.TextTestRunner(verbosity=2).run(tests)
            if not result.wasSuccessful():
                return 1
        else:
            audit(sources)
    except (CountedSlotOwnerEvidenceError, PRIOR_ERROR, OSError) as error:
        print("ROUND048_ORIGINAL_COUNTED_SLOT_SOURCE_BLOCKED first_error=" + str(error))
        return 2
    print("ROUND048_PRISTINE_ORIGINAL_COUNTED_SLOT_16_HOSTILE_FAIL_CLOSED_PASS "
          "EXTERNAL_COUNTED_OWNER_ACQUIRED=0 SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
