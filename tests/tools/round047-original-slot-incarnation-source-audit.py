#!/usr/bin/env python3
"""Verify pristine pinned Linux swap-slot lifetime boundaries (NO AUTH).

These source checks do not grant a transferable slot-incarnation lease, replace
genuine booted KUnit, or exercise actual zswap pressure or physical swap.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess
import unittest

PINNED = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
ORIGINAL_BLOBS = {
    "mm/swapfile.c": "254ce86fa923e6b5f1fefda88c39315c4cc00642",
    "mm/zswap.c": "ae19e301fced7e357a4c7587dfdd6abb890b9163",
    "mm/page_io.c": "c6824fcd483e0aa2c412e14dae0d2a356b17c373",
    "include/linux/swap.h": "4f686709d71f005dc43b2f751012b5f61d6b007a",
    "block/bio.c": "b0fcc69de653524479e3b328aa29a37e97945b84",
}


class OriginalSlotAuditError(ValueError):
    """Pristine original ownership evidence was changed or is missing."""


def function_body(source: str, signature: str) -> str:
    if source.count(signature) != 1:
        raise OriginalSlotAuditError("function_not_unique:" + signature)
    start = source.find("{", source.index(signature) + len(signature))
    if start < 0:
        raise OriginalSlotAuditError("function_body_missing:" + signature)
    depth = 0
    for end in range(start, len(source)):
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
            if depth == 0:
                return source[start:end + 1]
    raise OriginalSlotAuditError("function_unterminated:" + signature)


def in_order(body: str, name: str, *tokens: str) -> None:
    previous = -1
    for token in tokens:
        position = body.find(token, previous + 1)
        if position < 0 or position <= previous:
            raise OriginalSlotAuditError("original_boundary:" + name + ":" + token)
        previous = position


def audit(sources: dict[str, str]) -> None:
    if set(sources) != set(ORIGINAL_BLOBS):
        raise OriginalSlotAuditError("missing_original_source")
    sf = sources["mm/swapfile.c"]
    zs = sources["mm/zswap.c"]
    io = sources["mm/page_io.c"]
    header = sources["include/linux/swap.h"]
    bio = sources["block/bio.c"]

    get_area = function_body(sf, "struct swap_info_struct *get_swap_device(swp_entry_t entry)")
    in_order(get_area, "area_scope", "get_swap_device_info(si)",
             "offset = swp_offset(entry);", "offset >= si->max", "return si;")
    if "swap_cluster_lock(" in get_area or "swap_dup_entries_cluster(" in get_area:
        raise OriginalSlotAuditError("area_ref_is_not_slot_ref")
    in_order(function_body(sf, "static bool get_swap_device_info(struct swap_info_struct *si)"),
             "area_percpu", "percpu_ref_tryget_live(&si->users)", "smp_rmb();")
    in_order(header, "area_put", "struct swap_info_struct {",
             "struct percpu_ref users;", "static inline void put_swap_device(",
             "percpu_ref_put(&si->users);")
    in_order(function_body(sf, "void __swap_cluster_free_entries(struct swap_info_struct *si,"),
             "real_slot_release", "ci->count -= nr_pages;",
             "__swap_table_set(ci, ci_off, null_to_swp_tb());",
             "swap_range_free(si, ci_head + ci_start, nr_pages);")
    in_order(function_body(sf, "static void swap_range_free(struct swap_info_struct *si,"),
             "invalidate_before_free",
             "zswap_invalidate(si->type, offset, nr_entries);",
             "swap_usage_sub(si, nr_entries);")
    in_order(function_body(sf, "int swap_dup_entry_direct(swp_entry_t entry)"),
             "direct_slot_existing_owner", "swap_entry_to_info(entry)",
             "swap_entry_swapped(si, entry)",
             "swap_dup_entries_cluster(si, swp_offset(entry), 1);")
    doc_start = sf.find("/*\n * swap_dup_entry_direct()")
    direct_start = sf.find("int swap_dup_entry_direct(swp_entry_t entry)")
    if doc_start < 0 or direct_start <= doc_start or \
            "Caller must ensure there is no race condition" not in sf[doc_start:direct_start]:
        raise OriginalSlotAuditError("direct_dup_caller_owner_missing")
    in_order(function_body(sf, "sector_t swap_folio_sector(struct folio *folio)"),
             "original_absolute_non_linear_sector",
             "offset_to_swap_extent(sis, offset)",
             "se->start_block + (offset - se->start_page)",
             "return sector << (PAGE_SHIFT - 9);")
    in_order(function_body(sf, "SYSCALL_DEFINE1(swapoff,"),
             "swapoff_area_drain", "percpu_ref_kill(&p->users);",
             "synchronize_rcu();", "wait_for_completion(&p->comp);")

    writeback = function_body(zs, "static int zswap_writeback_entry(struct zswap_entry *entry,")
    in_order(writeback, "original_zswap_writeback_before_async",
             "si = get_swap_device(swpentry);",
             "__swap_cache_alloc_folio(", "put_swap_device(si);",
             "entry != xa_load(tree, offset)",
             "zswap_decompress(entry, folio)", "xa_erase(tree, offset);",
             "zswap_entry_free(entry);", "folio_put(folio);",
             "__swap_writeout(&ctx, folio);", "swap_write_submit(&ctx);")
    in_order(writeback, "writeback_error_unwind", "err:",
             "swap_cache_del_folio(folio);",
             "folio_unlock(folio);", "folio_put(folio);")
    in_order(function_body(zs, "void zswap_invalidate(int type, pgoff_t offset,"),
             "recycled_slot_invalidates_old_store",
             "xa_erase(tree, offset + i);", "zswap_entry_free(entry);")
    in_order(function_body(zs, "static void zswap_entry_free(struct zswap_entry *entry)"),
             "zswap_store_owner_freed", "zs_free(pool->zs_pool, entry->handle);",
             "zswap_entry_cache_free(entry);")

    in_order(function_body(io, "void __swap_writeout(struct swap_io_ctx *ctx, struct folio *folio)"),
             "swapcache_writeback", "folio_start_writeback(folio);",
             "folio_unlock(folio);", "swap_add_folio(ctx, folio, WRITE);")
    in_order(function_body(io, "static void swap_bdev_submit_write(struct swap_io_ctx *ctx)"),
             "actual_original_bdev_sector_and_async",
             "bio_init(bio, ctx->sis->bdev,", "REQ_OP_WRITE | REQ_SWAP",
             "bio->bi_iter.bi_size = sio->len;",
             "bio->bi_iter.bi_sector = swap_folio_sector(",
             "submit_bio_wait(bio);",
             "bio->bi_end_io = end_swap_bio_write;", "submit_bio(bio);")
    in_order(function_body(io, "static void end_swap_bio_write(struct bio *bio)"),
             "actual_bio_end_io", "bio_uninit(bio);", "swap_write_end(sio, failed);")
    in_order(function_body(io, "static void swap_write_end(struct swap_iocb *sio, bool failed)"),
             "actual_writeback_complete", "folio_end_writeback(folio);",
             "mempool_free(sio, sio_pool);")
    in_order(function_body(bio, "static int __bio_clone(struct bio *bio, struct bio *bio_src, gfp_t gfp)"),
             "bio_clone_not_slot_owner", "bio_set_flag(bio, BIO_CLONED);",
             "bio->bi_iter = bio_src->bi_iter;",
             "bio->bi_io_vec = bio_src->bi_io_vec;")
    in_order(function_body(bio, "void bio_endio(struct bio *bio)"),
             "bio_callback_not_slot_owner",
             "bio_remaining_done(bio)", "bio->bi_end_io(bio);")


def load_original(root: Path) -> dict[str, str]:
    if root.is_symlink() or not root.is_dir():
        raise OriginalSlotAuditError("missing_original_tree")
    try:
        commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                check=True, capture_output=True, text=True, timeout=10)
        status = subprocess.run(["git", "-C", str(root), "status",
                                 "--porcelain", "--untracked-files=all"],
                                check=True, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise OriginalSlotAuditError("original_git_unavailable") from exc
    if commit.stdout.strip() != PINNED or status.stdout.strip():
        raise OriginalSlotAuditError("original_source_not_pristine_or_wrong_commit")
    sources: dict[str, str] = {}
    for name, expected in ORIGINAL_BLOBS.items():
        path = root / name
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size < 200_000:
            raise OriginalSlotAuditError("original_source_missing_or_oversized:" + name)
        data = path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
        if blob != expected:
            raise OriginalSlotAuditError("original_source_git_blob_mismatch:" + name)
        try:
            sources[name] = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise OriginalSlotAuditError("original_source_not_utf8:" + name) from exc
    return sources


class OriginalSlotHostileSourceTests(unittest.TestCase):
    sources: dict[str, str] = {}

    def test_real_original_source(self) -> None:
        audit(self.sources)

    def test_18_real_original_source_hostile_mutants(self) -> None:
        changes = (
            ("mm/swapfile.c", "percpu_ref_tryget_live(&si->users)", "false"),
            ("mm/swapfile.c", "__swap_table_set(ci, ci_off, null_to_swp_tb());", "/* lost slot release */"),
            ("mm/swapfile.c", "zswap_invalidate(si->type, offset, nr_entries);", "/* lost invalidate */"),
            ("mm/swapfile.c", "VM_WARN_ON_ONCE(!swap_entry_swapped(si, entry));", "/* lost counted owner */"),
            ("mm/swapfile.c", "return sector << (PAGE_SHIFT - 9);", "return offset;"),
            ("mm/swapfile.c", "percpu_ref_kill(&p->users);", "/* lost swapoff drain */"),
            ("mm/zswap.c", "si = get_swap_device(swpentry);", "si = NULL;"),
            ("mm/zswap.c", "put_swap_device(si);", "/* lost area release */"),
            ("mm/zswap.c", "if (entry != xa_load(tree, offset)) {", "if (false) {"),
            ("mm/zswap.c", "xa_erase(tree, offset);", "/* lost xarray erase */"),
            ("mm/zswap.c", "zswap_entry_cache_free(entry);", "/* lost owner retirement */"),
            ("mm/page_io.c", "folio_start_writeback(folio);", "/* no writeback protection */"),
            ("mm/page_io.c", "bio->bi_iter.bi_sector = swap_folio_sector(",
             "bio->bi_iter.bi_sector = 0 * swap_folio_sector("),
            ("mm/page_io.c", "bio->bi_end_io = end_swap_bio_write;", "/* lost async callback */"),
            ("mm/page_io.c", "bio_uninit(bio);", "/* lost bio uninit */"),
            ("block/bio.c", "bio->bi_iter = bio_src->bi_iter;", "/* lost cloned iterator */"),
            ("block/bio.c", "bio->bi_end_io(bio);", "/* lost callback */"),
            ("include/linux/swap.h", "percpu_ref_put(&si->users);", "/* lost area put */"),
        )
        # Scope each hostile mutation to the exact genuine original C owner.
        # Repeated tokens in other functions cannot make the control vacuous.
        signatures = (
            "static bool get_swap_device_info(struct swap_info_struct *si)",
            "void __swap_cluster_free_entries(struct swap_info_struct *si,",
            "static void swap_range_free(struct swap_info_struct *si,",
            "int swap_dup_entry_direct(swp_entry_t entry)",
            "sector_t swap_folio_sector(struct folio *folio)",
            "SYSCALL_DEFINE1(swapoff,",
            "static int zswap_writeback_entry(struct zswap_entry *entry,",
            "static int zswap_writeback_entry(struct zswap_entry *entry,",
            "static int zswap_writeback_entry(struct zswap_entry *entry,",
            "static int zswap_writeback_entry(struct zswap_entry *entry,",
            "static void zswap_entry_free(struct zswap_entry *entry)",
            "void __swap_writeout(struct swap_io_ctx *ctx, struct folio *folio)",
            "static void swap_bdev_submit_write(struct swap_io_ctx *ctx)",
            "static void swap_bdev_submit_write(struct swap_io_ctx *ctx)",
            "static void end_swap_bio_write(struct bio *bio)",
            "static int __bio_clone(struct bio *bio, struct bio *bio_src, gfp_t gfp)",
            "void bio_endio(struct bio *bio)",
            None,  # Unique area put in CONFIG_SWAP header; CONFIG_SWAP=n has a stub.
        )
        self.assertEqual(len(changes), len(signatures))
        for number, ((name, old, new), signature) in enumerate(zip(changes, signatures)):
            with self.subTest(mutant=number, file=name):
                source = self.sources[name]
                region = function_body(source, signature) if signature else source
                self.assertEqual(region.count(old), 1,
                                 "hostile token not unique inside original owner")
                changed_region = region.replace(old, new, 1)
                changed = source.replace(region, changed_region, 1)
                self.assertNotEqual(changed, source, "hostile mutant was unchanged")
                modified = dict(self.sources)
                modified[name] = changed
                with self.assertRaises(OriginalSlotAuditError):
                    audit(modified)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", required=True, type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        sources = load_original(args.linux_root)
        if args.self_test:
            OriginalSlotHostileSourceTests.sources = sources
            result = unittest.TextTestRunner(verbosity=2).run(
                unittest.defaultTestLoader.loadTestsFromTestCase(OriginalSlotHostileSourceTests))
            if not result.wasSuccessful():
                return 1
        else:
            audit(sources)
    except (OriginalSlotAuditError, OSError) as exc:
        print("ROUND047_ORIGINAL_SLOT_LIFETIME_SOURCE_AUDIT_BLOCKED first_error=" + str(exc))
        return 2
    print("ROUND047_PRISTINE_ORIGINAL_SLOT_LIFETIME_18_HOSTILE_REJECTED_PASS "
          "NO_TRANSFERABLE_SLOT_LEASE=TRUE SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
