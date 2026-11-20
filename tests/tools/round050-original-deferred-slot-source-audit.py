#!/usr/bin/env python3
"""Audit real pristine original Linux deferred swap-count lifetime (NO_AUTH).

A current locked swapcache folio can mint a count. This audit proves why
no independently deferred external owner/put is established by the actual
zswap STORED writer. It never acquires counts, activates swap or tests MM
pressure. Hostile controls mutate real named pinned upstream C functions.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import runpy
import unittest

HERE = Path(__file__).resolve().parent
PREVIOUS = runpy.run_path(
    str(HERE / "round048-original-counted-slot-source-audit.py"),
    run_name="round048_deferred_slot_dependency")
ORIGINAL_BLOBS: dict[str, str] = {
    **PREVIOUS["ORIGINAL_BLOBS"],
    "mm/swap.h": "d5bf21f517dceae58eb94fb0ce5f4e1fdc679409",
}
PREVIOUS_AUDIT = PREVIOUS["audit"]
PREVIOUS_ERROR = PREVIOUS["CountedSlotOwnerEvidenceError"]
SOURCE_FUNCTION = PREVIOUS["source_function"]


class DeferredSwapSlotAuditError(ValueError):
    """The genuine original swapoff/deferred-put source contract drifted."""


def function(sources: dict[str, str], path: str, signature: str) -> str:
    try:
        return SOURCE_FUNCTION(sources, path, signature)
    except (KeyError, PREVIOUS_ERROR) as error:
        raise DeferredSwapSlotAuditError(
            "original_function:" + path + ":" + signature) from error


def in_order(body: str, name: str, *tokens: str) -> None:
    previous = -1
    for token in tokens:
        position = body.find(token, previous + 1)
        if position < 0:
            raise DeferredSwapSlotAuditError(
                "original_deferred_lifetime:" + name + ":" + token)
        previous = position


def audit(sources: dict[str, str]) -> None:
    if set(sources) != set(ORIGINAL_BLOBS):
        raise DeferredSwapSlotAuditError("seven_pristine_original_sources_required")
    try:
        PREVIOUS_AUDIT({
            path: sources[path] for path in PREVIOUS["ORIGINAL_BLOBS"]
        })
    except PREVIOUS_ERROR as error:
        raise DeferredSwapSlotAuditError(
            "inherited_48_source_lifetime:" + str(error)) from error

    swapfile = sources["mm/swapfile.c"]
    swap_header = sources["include/linux/swap.h"]
    private_header = sources["mm/swap.h"]

    # A private original locked-swapcache helper is not an externally
    # available stable direct-counted reference with a deferred release API.
    for token in (
        "int folio_dup_swap(struct folio *folio, struct page *page);",
        "void folio_put_swap(struct folio *folio, struct page *page);",
    ):
        if private_header.count(token) != 1:
            raise DeferredSwapSlotAuditError("missing_original_private_api:" + token)
    if swap_header.count("void swap_put_entries_direct(swp_entry_t entry, int nr);") != 1:
        raise DeferredSwapSlotAuditError("missing_original_direct_put_api")
    if "percpu_ref_put(&si->users);" not in swap_header:
        raise DeferredSwapSlotAuditError("missing_original_area_put")

    # Original swapoff is ALREADY removing mapped/shmem entries and cached
    # folios before killing area users. An untracked external counted slot
    # can keep inuse_pages nonzero; try_to_unuse retries while that count
    # remains, with no external async owner completion tied to this pass.
    unuse = function(sources, "mm/swapfile.c",
                     "static int try_to_unuse(unsigned int type)")
    in_order(unuse, "untracked_count_blocks_swapoff",
             "if (!swap_usage_in_pages(si))", "retry:",
             "retval = shmem_unuse(type);",
             "retval = unuse_mm(mm, type);",
             "folio = swap_cache_get_folio(entry);",
             "folio_lock(folio);", "folio_wait_writeback(folio);",
             "folio_free_swap(folio);",
             "if (swap_usage_in_pages(si)) {",
             "goto retry;", "return -EINTR;")
    if "swap_put_entries_direct(" in unuse:
        raise DeferredSwapSlotAuditError("unexpected_unuse_external_direct_owner_put")
    swapoff = function(sources, "mm/swapfile.c",
                       "SYSCALL_DEFINE1(swapoff, const char __user *, specialfile)")
    in_order(swapoff, "swapoff_waits_before_kill_and_reuse",
             "wait_for_allocation(p);", "err = try_to_unuse(p->type);",
             "if (err) {", "reinsert_swap_info(p);",
             "percpu_ref_kill(&p->users);", "synchronize_rcu();",
             "wait_for_completion(&p->comp);",
             "destroy_swap_extents(p, p->swap_file);",
             "p->cluster_info = NULL;",
             "zswap_swapoff(p->type);",
             "p->flags = 0;")

    # Area users are live-tryget references, NOT perpetual authority: after
    # the kill, an unrelated late copied-slot lookup cannot obtain a new
    # area users reference; this put API is VOID and returns without a put
    # if the area cannot be looked up. No "put succeeded" receipt exists.
    get_info = function(sources, "mm/swapfile.c",
                        "static bool get_swap_device_info(struct swap_info_struct *si)")
    in_order(get_info, "area_live_only",
             "if (!percpu_ref_tryget_live(&si->users))",
             "return false;", "smp_rmb();", "return true;")
    direct_put = function(sources, "mm/swapfile.c",
                          "void swap_put_entries_direct(swp_entry_t entry, int nr)")
    in_order(direct_put, "unacknowledged_direct_put",
             "si = get_swap_device(entry);",
             "if (WARN_ON_ONCE(IS_ERR_OR_NULL(si)))",
             "return;", "swap_put_entries_cluster(si, offset, cluster_end - offset, true);",
             "put_swap_device(si);")
    if "return 0;" in direct_put or "folio_put_swap(" in direct_put:
        raise DeferredSwapSlotAuditError("unexpected_deferred_put_semantics")

    # The counted acquisition is legal ONLY from the same locked, current
    # swapcache folio, and its synchronous local put requires that folio
    # STILL exist and remain locked/in swapcache.
    dup = function(sources, "mm/swapfile.c",
                   "int folio_dup_swap(struct folio *folio, struct page *page)")
    in_order(dup, "acquire_from_current_folio",
             "VM_WARN_ON_FOLIO(!folio_test_locked(folio), folio);",
             "VM_WARN_ON_FOLIO(!folio_test_swapcache(folio), folio);",
             "return swap_dup_entries_cluster(swap_entry_to_info(entry),")
    locked_put = function(sources, "mm/swapfile.c",
                          "void folio_put_swap(struct folio *folio, struct page *page)")
    in_order(locked_put, "local_only_put_requires_locked_folio",
             "VM_WARN_ON_FOLIO(!folio_test_locked(folio), folio);",
             "VM_WARN_ON_FOLIO(!folio_test_swapcache(folio), folio);",
             "swap_put_entries_cluster(si, swp_offset(entry), nr_pages, false);")
    duplicate_range = function(sources, "mm/swapfile.c",
                                "static int swap_dup_entries_cluster(struct swap_info_struct *si,")
    in_order(duplicate_range, "atomic_extension_retry_rollback",
             "ci = swap_cluster_lock(si, offset);",
             "err = __swap_cluster_dup_entry(ci, ci_off);",
             "spin_unlock(&ci->lock);",
             "err = swap_extend_table_alloc(si, ci, ci_off, GFP_ATOMIC);",
             "spin_lock(&ci->lock);", "goto restart;",
             "__swap_cluster_put_entry(ci, ci_off);")

    # Once original folio leaves swapcache, retaining a bare folio pointer
    # is unsafe; its slot may be freed when no actual count exists.
    delete = function(sources, "mm/swap_state.c",
                      "static void __swap_cache_do_del_folio(struct swap_cluster_info *ci,")
    in_order(delete, "deleted_folio_cannot_serve_late_put",
             "if (__swp_tb_get_count(old_tb))",
             "folio_swapped = true;",
             "folio->swap.val = 0;",
             "folio_clear_swapcache(folio);",
             "if (!folio_swapped) {",
             "__swap_cluster_free_entries(si, ci, ci_start, nr_pages);")

    # This REAL original zswap path owns the folio and STORED entry until
    # erase; it holds NO further independently transferrable slot count.
    writeback = function(sources, "mm/zswap.c",
                         "static int zswap_writeback_entry(struct zswap_entry *entry,")
    in_order(writeback, "source_return_unretained",
             "si = get_swap_device(swpentry);",
             "__swap_cache_alloc_folio(", "put_swap_device(si);",
             "if (entry != xa_load(tree, offset)) {",
             "zswap_decompress(entry, folio)",
             "xa_erase(tree, offset);", "zswap_entry_free(entry);",
             "folio_put(folio);", "__swap_writeout(&ctx, folio);",
             "swap_write_submit(&ctx);", "return 0;")
    for forbidden in (
        "folio_dup_swap(", "folio_put_swap(", "swap_dup_entry_direct(",
        "swap_put_entries_direct(",
    ):
        if forbidden in writeback:
            raise DeferredSwapSlotAuditError(
                "original_writer_changed_external_ref_without_owner:" + forbidden)
    callback = function(sources, "mm/page_io.c",
                        "static void end_swap_bio_write(struct bio *bio)")
    in_order(callback, "bio_callback_no_external_count_put",
             "bio_uninit(bio);", "swap_write_end(sio, failed);")
    completion = function(sources, "mm/page_io.c",
                          "static void swap_write_end(struct swap_iocb *sio, bool failed)")
    in_order(completion, "folio_only_completion",
             "folio_end_writeback(folio);", "mempool_free(sio, sio_pool);")
    for forbidden in ("swap_put_entries_direct(", "folio_put_swap("):
        if forbidden in callback or forbidden in completion:
            raise DeferredSwapSlotAuditError(
                "unexpected_callback_count_ownership:" + forbidden)


def pristine_original(root: Path) -> dict[str, str]:
    sources = PREVIOUS["pristine_original"](root)
    path = root / "mm/swap.h"
    if root.is_symlink() or path.is_symlink() or not path.is_file() or \
            not 0 < path.stat().st_size < 100_000:
        raise DeferredSwapSlotAuditError("missing_pristine_private_mm_swap_header")
    data = path.read_bytes()
    git_blob = b"blob " + str(len(data)).encode("ascii") + b"\0" + data
    if hashlib.sha1(git_blob).hexdigest() != ORIGINAL_BLOBS["mm/swap.h"]:
        raise DeferredSwapSlotAuditError("wrong_pristine_private_mm_swap_header_sha")
    try:
        sources["mm/swap.h"] = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DeferredSwapSlotAuditError("invalid_original_private_header") from error
    return sources


class GenuineOriginalDeferredHostileTests(unittest.TestCase):
    sources: dict[str, str] = {}

    def test_pristine_original_swapoff_and_counted_release(self) -> None:
        audit(self.sources)

    def test_sixteen_function_scoped_real_original_hostile_mutations(self) -> None:
        changes = (
            ("mm/swapfile.c", "static int try_to_unuse(unsigned int type)",
             "if (!swap_usage_in_pages(si))"),
            ("mm/swapfile.c", "static int try_to_unuse(unsigned int type)",
             "retval = shmem_unuse(type);"),
            ("mm/swapfile.c", "static int try_to_unuse(unsigned int type)",
             "retval = unuse_mm(mm, type);"),
            ("mm/swapfile.c", "static int try_to_unuse(unsigned int type)",
             "folio = swap_cache_get_folio(entry);"),
            ("mm/swapfile.c", "static int try_to_unuse(unsigned int type)",
             "goto retry;"),
            ("mm/swapfile.c", "SYSCALL_DEFINE1(swapoff, const char __user *, specialfile)",
             "err = try_to_unuse(p->type);"),
            ("mm/swapfile.c", "SYSCALL_DEFINE1(swapoff, const char __user *, specialfile)",
             "percpu_ref_kill(&p->users);"),
            ("mm/swapfile.c", "static bool get_swap_device_info(struct swap_info_struct *si)",
             "if (!percpu_ref_tryget_live(&si->users))"),
            ("mm/swapfile.c", "void swap_put_entries_direct(swp_entry_t entry, int nr)",
             "si = get_swap_device(entry);"),
            ("mm/swapfile.c", "void swap_put_entries_direct(swp_entry_t entry, int nr)",
             "if (WARN_ON_ONCE(IS_ERR_OR_NULL(si)))"),
            ("mm/swapfile.c", "void swap_put_entries_direct(swp_entry_t entry, int nr)",
             "swap_put_entries_cluster(si, offset, cluster_end - offset, true);"),
            ("mm/swapfile.c", "int folio_dup_swap(struct folio *folio, struct page *page)",
             "VM_WARN_ON_FOLIO(!folio_test_locked(folio), folio);"),
            ("mm/swapfile.c", "void folio_put_swap(struct folio *folio, struct page *page)",
             "VM_WARN_ON_FOLIO(!folio_test_swapcache(folio), folio);"),
            ("mm/swap_state.c", "static void __swap_cache_do_del_folio(struct swap_cluster_info *ci,",
             "folio_clear_swapcache(folio);"),
            ("mm/zswap.c", "static int zswap_writeback_entry(struct zswap_entry *entry,",
             "put_swap_device(si);"),
            ("mm/page_io.c", "static void swap_write_end(struct swap_iocb *sio, bool failed)",
             "folio_end_writeback(folio);"),
        )
        self.assertEqual(len(changes), 16)
        for index, (path, signature, anchor) in enumerate(changes):
            with self.subTest(mutant=index, original_file=path):
                pristine = self.sources[path]
                region = function(self.sources, path, signature)
                self.assertEqual(region.count(anchor), 1,
                                 "real original C anchor must be unique in function")
                self.assertEqual(pristine.count(region), 1,
                                 "original C function region must be unique")
                mutated_region = region.replace(
                    anchor, "/* hostile removed original ownership transition */", 1)
                changed = pristine.replace(region, mutated_region, 1)
                self.assertNotEqual(changed, pristine, "hostile mutant was a no-op")
                altered = dict(self.sources)
                altered[path] = changed
                with self.assertRaises(DeferredSwapSlotAuditError):
                    audit(altered)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", type=Path, required=True)
    parser.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args()
    try:
        sources = pristine_original(arguments.linux_root)
        if arguments.self_test:
            GenuineOriginalDeferredHostileTests.sources = sources
            tests = unittest.defaultTestLoader.loadTestsFromTestCase(
                GenuineOriginalDeferredHostileTests)
            if not unittest.TextTestRunner(verbosity=2).run(tests).wasSuccessful():
                return 1
        else:
            audit(sources)
    except (DeferredSwapSlotAuditError, PREVIOUS_ERROR, OSError) as error:
        print("ROUND050_ORIGINAL_DEFERRED_SLOT_BLOCKED first_error=" + str(error))
        return 2
    print("ROUND050_PRISTINE_ORIGINAL_DEFERRED_COUNTED_SLOT_16_HOSTILE_FAIL_CLOSED_PASS "
          "HELD_EXTERNAL_ASYNC_SLOT_REF=0 POST_RETURN_RELEASE_PROVEN=0 "
          "SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
