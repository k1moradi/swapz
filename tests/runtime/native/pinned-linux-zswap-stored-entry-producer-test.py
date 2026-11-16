#!/usr/bin/env python3
"""Exact pinned zswap stored-entry C writeback causality, ROOTLESS/NOT LOADED.

The source is copied from the authenticated torvalds/linux Git commit below,
and its exact Git-blob sections are checked by the real staging verifier.
Only external kernel services and decoding are mocked by dedicated host shims.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


STAGER_PATH = Path(__file__).resolve().parents[2] / "tools/stage-pinned-linux-zswap-origin.py"
loader = importlib.util.spec_from_file_location("round020_zswap_stager", STAGER_PATH)
assert loader and loader.loader
stager = importlib.util.module_from_spec(loader)
sys.modules[loader.name] = stager
loader.loader.exec_module(stager)

# Original upstream producer functions: torvalds/linux
# c339f4010dea8b0d754f84ace70cd1b089878ef8, not synthetic tagged BIOs.
PINNED_DECOMPRESS = "static bool zswap_decompress(struct zswap_entry *entry, struct folio *folio)\n{\n\tstruct zswap_pool *pool = zswap_entry_pool(entry);\n\tstruct scatterlist input[2]; /* zsmalloc returns an SG list 1-2 entries */\n\tstruct scatterlist output;\n\tstruct crypto_acomp_ctx *acomp_ctx;\n\tint ret = 0, dlen;\n\n\tif (WARN_ON_ONCE(!pool))\n\t\treturn false;\n\n\tacomp_ctx = raw_cpu_ptr(pool->acomp_ctx);\n\tmutex_lock(&acomp_ctx->mutex);\n\tzs_obj_read_sg_begin(pool->zs_pool, entry->handle, input, entry->length);\n\n\t/* zswap entries of length PAGE_SIZE are not compressed. */\n\tif (entry->length == PAGE_SIZE) {\n\t\tvoid *dst;\n\n\t\tWARN_ON_ONCE(input->length != PAGE_SIZE);\n\n\t\tdst = kmap_local_folio(folio, 0);\n\t\tmemcpy_from_sglist(dst, input, 0, PAGE_SIZE);\n\t\tdlen = PAGE_SIZE;\n\t\tkunmap_local(dst);\n\t\tflush_dcache_folio(folio);\n\t} else {\n\t\tsg_init_table(&output, 1);\n\t\tsg_set_folio(&output, folio, PAGE_SIZE, 0);\n\t\tacomp_request_set_params(acomp_ctx->req, input, &output,\n\t\t\t\t\t entry->length, PAGE_SIZE);\n\t\tret = crypto_acomp_decompress(acomp_ctx->req);\n\t\tret = crypto_wait_req(ret, &acomp_ctx->wait);\n\t\tdlen = acomp_ctx->req->dlen;\n\t}\n\n\tzs_obj_read_sg_end(pool->zs_pool, entry->handle);\n\tmutex_unlock(&acomp_ctx->mutex);\n\n\tif (!ret && dlen == PAGE_SIZE)\n\t\treturn true;\n\n\tzswap_decompress_fail++;\n\tpr_alert_ratelimited(\"Decompression error from zswap (%d:%lu %s %u->%d)\\n\",\n\t\t\t\t\t\tswp_type(entry->swpentry),\n\t\t\t\t\t\tswp_offset(entry->swpentry),\n\t\t\t\t\t\tpool->tfm_name,\n\t\t\t\t\t\tentry->length, dlen);\n\treturn false;\n}\n\n"
PINNED_WRITEBACK = "static int zswap_writeback_entry(struct zswap_entry *entry,\n\t\t\t\t swp_entry_t swpentry)\n{\n\tstruct xarray *tree;\n\tpgoff_t offset = swp_offset(swpentry);\n\tstruct folio *folio;\n\tstruct mempolicy *mpol;\n\tstruct swap_info_struct *si;\n\tstruct swap_io_ctx ctx = {};\n\tint ret = 0;\n\n\t/* try to allocate swap cache folio */\n\tsi = get_swap_device(swpentry);\n\tif (IS_ERR_OR_NULL(si))\n\t\treturn -ENOENT;\n\n\tmpol = get_task_policy(current);\n\tfolio = __swap_cache_alloc_folio(swpentry, GFP_KERNEL, BIT(0), NULL, mpol,\n\t\t\t\t\t NO_INTERLEAVE_INDEX);\n\tput_swap_device(si);\n\n\t/*\n\t * Swap cache allocation might fail due to OOM, or the entry\n\t * may already be cached due to concurrent swapin or have been\n\t * freed. If already cached, a concurrent swapin made the folio\n\t * hot, so skip it. For the unlikely concurrent shrinker case,\n\t * it will be unlinked and freed when invalidated anyway.\n\t */\n\tif (IS_ERR(folio))\n\t\treturn PTR_ERR(folio);\n\n\tfolio_clear_active(folio);\n\n\t/*\n\t * folio is locked, and the swapcache is now secured against\n\t * concurrent swapping to and from the slot, and concurrent\n\t * swapoff so we can safely dereference the zswap tree here.\n\t * Verify that the swap entry hasn't been invalidated and recycled\n\t * behind our backs, to avoid overwriting a new swap folio with\n\t * old compressed data. Only when this is successful can the entry\n\t * be dereferenced.\n\t */\n\ttree = swap_zswap_tree(swpentry);\n\tif (entry != xa_load(tree, offset)) {\n\t\tret = -ENOMEM;\n\t\tgoto err;\n\t}\n\n\tif (!zswap_decompress(entry, folio)) {\n\t\tret = -EIO;\n\t\tgoto err;\n\t}\n\n\txa_erase(tree, offset);\n\n\tcount_vm_event(ZSWPWB);\n\tif (entry->objcg)\n\t\tcount_objcg_events(entry->objcg, ZSWPWB, 1);\n\n\tzswap_entry_free(entry);\n\n\t/* folio is up to date */\n\tfolio_mark_uptodate(folio);\n\n\tfolio_set_dropbehind(folio);\n\n\t/*\n\t * Drop our reference before starting writeback so the swap cache holds\n\t * the only one: the drop in folio_end_writeback() needs that for\n\t * remove_mapping_set_shadow() to succeed, otherwise the folio is\n\t * handed back to reclaim instead.\n\t *\n\t * Nothing can free the folio in the meantime: we hold the folio lock\n\t * until writeback starts, PG_writeback then blocks swap cache removal,\n\t * and folio_end_writeback() takes its own reference before clearing\n\t * PG_writeback and donates it to the drop.\n\t */\n\tfolio_put(folio);\n\n\t/* start writeback */\n\t__swap_writeout(&ctx, folio);\n\tswap_write_submit(&ctx);\n\n\treturn 0;\n\nerr:\n\tswap_cache_del_folio(folio);\n\tfolio_unlock(folio);\n\tfolio_put(folio);\n\treturn ret;\n}\n\n"
PINNED_SHRINKER = "static enum lru_status shrink_memcg_cb(struct list_head *item, struct list_lru_one *l,\n\t\t\t\t       void *arg)\n{\n\tstruct zswap_entry *entry = container_of(item, struct zswap_entry, lru);\n\tbool *encountered_page_in_swapcache = (bool *)arg;\n\tswp_entry_t swpentry;\n\tenum lru_status ret = LRU_REMOVED_RETRY;\n\tint writeback_result;\n\n\t/*\n\t * Second chance algorithm: if the entry has its referenced bit set, give it\n\t * a second chance. Only clear the referenced bit and rotate it in the\n\t * zswap's LRU list.\n\t */\n\tif (entry->referenced) {\n\t\tentry->referenced = false;\n\t\treturn LRU_ROTATE;\n\t}\n\n\t/*\n\t * As soon as we drop the LRU lock, the entry can be freed by\n\t * a concurrent invalidation. This means the following:\n\t *\n\t * 1. We extract the swp_entry_t to the stack, allowing\n\t *    zswap_writeback_entry() to pin the swap entry and\n\t *    then validate the zswap entry against that swap entry's\n\t *    tree using pointer value comparison. Only when that\n\t *    is successful can the entry be dereferenced.\n\t *\n\t * 2. Usually, objects are taken off the LRU for reclaim. In\n\t *    this case this isn't possible, because if reclaim fails\n\t *    for whatever reason, we have no means of knowing if the\n\t *    entry is alive to put it back on the LRU.\n\t *\n\t *    So rotate it before dropping the lock. If the entry is\n\t *    written back or invalidated, the free path will unlink\n\t *    it. For failures, rotation is the right thing as well.\n\t *\n\t *    Temporary failures, where the same entry should be tried\n\t *    again immediately, almost never happen for this shrinker.\n\t *    We don't do any trylocking; -ENOMEM comes closest,\n\t *    but that's extremely rare and doesn't happen spuriously\n\t *    either. Don't bother distinguishing this case.\n\t */\n\tlist_move_tail(item, &l->list);\n\n\t/*\n\t * Once the lru lock is dropped, the entry might get freed. The\n\t * swpentry is copied to the stack, and entry isn't deref'd again\n\t * until the entry is verified to still be alive in the tree.\n\t */\n\tswpentry = entry->swpentry;\n\n\t/*\n\t * It's safe to drop the lock here because we return either\n\t * LRU_REMOVED_RETRY, LRU_RETRY or LRU_STOP.\n\t */\n\tspin_unlock(&l->lock);\n\n\twriteback_result = zswap_writeback_entry(entry, swpentry);\n\n\tif (writeback_result) {\n\t\tzswap_reject_reclaim_fail++;\n\t\tret = LRU_RETRY;\n\n\t\t/*\n\t\t * Encountering a page already in swap cache is a sign that we are shrinking\n\t\t * into the warmer region. We should terminate shrinking (if we're in the dynamic\n\t\t * shrinker context).\n\t\t */\n\t\tif (writeback_result == -EEXIST && encountered_page_in_swapcache) {\n\t\t\tret = LRU_STOP;\n\t\t\t*encountered_page_in_swapcache = true;\n\t\t}\n\t} else {\n\t\tzswap_written_back_pages++;\n\t}\n\n\treturn ret;\n}\n\nstatic unsigned long zswap_shrinker_scan(struct shrinker *shrinker,\n\t\tstruct shrink_control *sc)\n{\n\tunsigned long shrink_ret;\n\tbool encountered_page_in_swapcache = false;\n\n\tif (!zswap_shrinker_enabled ||\n\t\t\t!mem_cgroup_zswap_writeback_enabled(sc->memcg)) {\n\t\tsc->nr_scanned = 0;\n\t\treturn SHRINK_STOP;\n\t}\n\n\tshrink_ret = list_lru_shrink_walk(&zswap_list_lru, sc, &shrink_memcg_cb,\n\t\t&encountered_page_in_swapcache);\n\n\tif (encountered_page_in_swapcache)\n\t\treturn SHRINK_STOP;\n\n\treturn shrink_ret ? shrink_ret : SHRINK_STOP;\n}\n\n"
PINNED_STORE = "static bool zswap_store_page(struct folio *folio, long index,\n\t\t\t     struct obj_cgroup *objcg,\n\t\t\t     struct zswap_pool *pool)\n{\n\tswp_entry_t page_swpentry = folio_swap_entry(folio, index);\n\tstruct zswap_entry *entry, *old;\n\n\t/* allocate entry */\n\tentry = zswap_entry_cache_alloc(GFP_KERNEL, folio_nid(folio));\n\tif (!entry) {\n\t\tzswap_reject_kmemcache_fail++;\n\t\treturn false;\n\t}\n\n\tif (!zswap_compress(folio, index, entry, pool))\n\t\tgoto compress_failed;\n\n\t/*\n\t * Set pool_idx before the xa_store() below publishes the entry, or a\n\t * concurrent reader could resolve a stale pool_idx left by slab reuse\n\t * to an unrelated live pool.\n\t */\n\tentry->pool_idx = pool->idx;\n\n\told = xa_store(swap_zswap_tree(page_swpentry),\n\t\t       swp_offset(page_swpentry),\n\t\t       entry, GFP_KERNEL);\n\tif (xa_is_err(old)) {\n\t\tint err = xa_err(old);\n\n\t\tWARN_ONCE(err != -ENOMEM, \"unexpected xarray error: %d\\n\", err);\n\t\tzswap_reject_alloc_fail++;\n\t\tgoto store_failed;\n\t}\n\n\t/*\n\t * We may have had an existing entry that became stale when\n\t * the folio was redirtied and now the new version is being\n\t * swapped out. Get rid of the old.\n\t */\n\tif (old)\n\t\tzswap_entry_free(old);\n\n\t/*\n\t * The entry is successfully compressed and stored in the tree, there is\n\t * no further possibility of failure. Grab refs to the pool and objcg,\n\t * charge zswap memory, and increment zswap_stored_pages.\n\t * The opposite actions will be performed by zswap_entry_free()\n\t * when the entry is removed from the tree.\n\t */\n\tzswap_pool_get(pool);\n\tif (objcg) {\n\t\tobj_cgroup_get(objcg);\n\t\tobj_cgroup_charge_zswap(objcg, entry->length);\n\t}\n\tatomic_long_inc(&zswap_stored_pages);\n\tif (entry->length == PAGE_SIZE)\n\t\tatomic_long_inc(&zswap_stored_incompressible_pages);\n\n\t/*\n\t * We finish initializing the entry while it's already in xarray.\n\t * This is safe because:\n\t *\n\t * 1. Concurrent stores and invalidations are excluded by folio lock.\n\t *\n\t * 2. Writeback is excluded by the entry not being on the LRU yet.\n\t *    The publishing order matters to prevent writeback from seeing\n\t *    an incoherent entry.\n\t */\n\tentry->swpentry = page_swpentry;\n\tentry->objcg = objcg;\n\tentry->referenced = true;\n\tif (entry->length) {\n\t\tINIT_LIST_HEAD(&entry->lru);\n\t\tzswap_lru_add(entry);\n\t}\n\n\treturn true;\n\nstore_failed:\n\tzs_free(pool->zs_pool, entry->handle);\ncompress_failed:\n\tzswap_entry_cache_free(entry);\n\treturn false;\n}\n\n"

ORIGINAL_SECTION_BLOBS = {
    "decompress": "c0e1a14325e1bbee09e65cf6028cd68c68016af8",
    "writeback": "f34f99e03d763133a8b0f4e7565dbb815fccdf3a",
    "shrinker": "d24dacab8099ff5ca81ba2f04a3ccba2968b5b33",
    "store": "3628dacfe6c56773e8703e35bb6126c4a4ab136d",
}
EXTRACTED_SOURCE_LIMIT = 1024 * 1024


def original_pinned_source_excerpt() -> str:
    """Join original function extents with noncompiled structural sentinels.

    The inserted comments replace only unrelated upstream code between the
    independently hashed functions; the function bodies are unmodified.
    """
    return (
        PINNED_DECOMPRESS +
        stager.COMPRESSED_HANDOFF_ANCHOR + "\n" +
        "/* Unrelated upstream writeback documentation omitted. */\n" +
        PINNED_WRITEBACK +
        "/*********************************\n* shrinker functions\n**********************************/\n" +
        PINNED_SHRINKER +
        "static unsigned long zswap_shrinker_count(struct shrinker *s, void *c);\n" +
        PINNED_STORE +
        "bool zswap_store(struct folio *folio);\n"
    )


def staged_pinned_source(*, compressed_handoff: bool = False) -> str:
    source = stager.render_source(
        "mm/zswap.c", original_pinned_source_excerpt(),
        compressed_handoff=compressed_handoff,
    )
    stager.verify_pinned_zswap_producer(source)
    return source


def producer_writeback_body(source: str) -> str:
    beginning = "static int zswap_writeback_entry("
    ending = "/*********************************\n* shrinker functions"
    start = source.index(beginning)
    end = source.index(ending, start)
    return source[start:end]


def authentic_bio_predicate() -> str:
    source = stager.EDITS["include/linux/bio.h"][0].after
    start = source.index("static inline bool bio_is_zswap_stored_writeback(")
    end = source.index("static inline bool bio_flagged(", start)
    return source[start:end]


class PinnedProducerCausalityTests(unittest.TestCase):
    def test_original_pinned_source_and_staged_identity(self) -> None:
        self.assertEqual(stager.LINUX_COMMIT,
                         "c339f4010dea8b0d754f84ace70cd1b089878ef8")
        self.assertEqual(stager.ORIGINAL_BLOBS["mm/zswap.c"],
                         "ae19e301fced7e357a4c7587dfdd6abb890b9163")
        for name, original in (
            ("decompress", PINNED_DECOMPRESS),
            ("writeback", PINNED_WRITEBACK),
            ("shrinker", PINNED_SHRINKER),
            ("store", PINNED_STORE),
        ):
            with self.subTest(section=name):
                self.assertEqual(stager.blob_sha(original.encode("utf-8")),
                                 ORIGINAL_SECTION_BLOBS[name])
        source = staged_pinned_source()
        self.assertLess(source.index("static bool zswap_decompress("),
                        source.index("static int zswap_writeback_entry("))
        self.assertLess(source.index("static int zswap_writeback_entry("),
                        source.index("static enum lru_status shrink_memcg_cb("))
        self.assertLess(source.index("static enum lru_status shrink_memcg_cb("),
                        source.index("static bool zswap_store_page("))
        self.assertIn("if (entry != xa_load(tree, offset))", source)
        self.assertIn("if (!zswap_decompress(entry, folio))", source)
        self.assertIn("if (entry->referenced)", source)
        self.assertIn("zswap_lru_add(entry);", source)
        self.assertIn("zswap_entry_free(entry);", source)
        self.assertIn("ctx.swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;", source)
        self.assertNotIn("REQ_ZSWAP_WRITEBACK", source)

    def test_failed_or_forged_original_producer_causality_refuses(self) -> None:
        source = staged_pinned_source()
        invalid = (
            ("stale-entry-accepted",
             "if (entry != xa_load(tree, offset))",
             "if (entry == xa_load(tree, offset))"),
            ("failed-decompress-promoted",
             "if (!zswap_decompress(entry, folio))",
             "if (zswap_decompress(entry, folio))"),
            ("drop-decompress-length",
             "if (!ret && dlen == PAGE_SIZE)",
             "if (!ret)"),
            ("drop-xarray-erasure",
             "xa_erase(tree, offset);",
             "/* suppressed xa_erase */"),
            ("preemptive-tag",
             "ctx.swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;",
             "ctx.swap_origin = SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;"),
            ("no-write-issue",
             "__swap_writeout(&ctx, folio);",
             "/* suppressed real writeout */"),
            ("no-submit",
             "swap_write_submit(&ctx);",
             "/* suppressed submit */"),
            ("accept-compress-rejection",
             "if (!zswap_compress(folio, index, entry, pool))",
             "if (zswap_compress(folio, index, entry, pool))"),
            ("skip-xarray-publish",
             "old = xa_store(swap_zswap_tree(page_swpentry),",
             "old = xa_load(swap_zswap_tree(page_swpentry),"),
            ("skip-stored-lru",
             "zswap_lru_add(entry);",
             "/* suppressed entry admission */"),
            ("skip-shrinker-second-chance",
             "if (entry->referenced)",
             "if (!entry->referenced)"),
        )
        for name, old, replacement in invalid:
            with self.subTest(mutation=name):
                self.assertIn(old, source)
                altered = source.replace(old, replacement, 1)
                with self.assertRaises(stager.StagingError):
                    stager.verify_pinned_zswap_producer(altered)
        for name, altered in (
            ("missing-store", source.replace("static bool zswap_store_page(", "static bool removed_store(", 1)),
            ("duplicate-writeback", source + producer_writeback_body(source)),
            ("swapped-source", source.replace("static bool zswap_decompress(", "static bool overwritten(", 1)),
            ("oversized", source + "x" * EXTRACTED_SOURCE_LIMIT),
        ):
            with self.subTest(mutation=name):
                with self.assertRaises(stager.StagingError):
                    stager.verify_pinned_zswap_producer(altered)

    def test_disabled_prototype_does_not_define_live_compressed_bio(self) -> None:
        source = staged_pinned_source(compressed_handoff=True)
        self.assertIn("#if 0 /* SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI */",
                      source)
        self.assertIn("#endif /* SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI */",
                      source)
        # Round 022 v1 deliberately rejects the older CRC32 prototype.
        self.assertIn("crc32c(0, owned_bytes, entry->length)", source)
        self.assertNotIn("crc32(0,", stager.COMPRESSED_HANDOFF_SOURCE)
        self.assertIn("ctx.swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;",
                      source)
        malicious = source.replace(
            "#if 0 /* SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI */",
            "#if 1 /* SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI */",
        )
        with self.assertRaises(stager.StagingError):
            stager.verify_pinned_zswap_producer(malicious)

    def test_compiler_executes_real_pinned_writeback_not_manual_tag(self) -> None:
        """Host mocks supply failures; the production function body is real C.

        Decompression helper and BIO submit are mocked: this is NOT a genuine
        kernel codec, zswap pressure eviction, loaded device or swap-in.
        """
        source = staged_pinned_source()
        fixture_directory = Path(__file__).parent / "fixtures"
        header = (fixture_directory / "round020-zswap-producer-prologue.h").read_text(
            encoding="utf-8")
        footer = (fixture_directory / "round020-zswap-producer-epilogue.h").read_text(
            encoding="utf-8")
        harness = (header + "\n" + producer_writeback_body(source) + "\n" +
                   authentic_bio_predicate() + "\n" + footer)
        compilers = [name for name in ("gcc", "clang") if shutil.which(name)]
        self.assertTrue(compilers, "at least one supported C compiler is required")
        with tempfile.TemporaryDirectory(prefix="round020-zswap-producer-") as temporary:
            directory = Path(temporary)
            c_file = directory / "producer.c"
            c_file.write_text(harness, encoding="utf-8")
            for compiler in compilers:
                with self.subTest(compiler=compiler):
                    executable = directory / ("producer-" + compiler)
                    command = [
                        compiler, "-std=c11", "-O1", "-g", "-Wall", "-Wextra",
                        "-Werror", "-Wconversion", "-Wshadow",
                        "-fsanitize=undefined", "-fno-sanitize-recover=all",
                        str(c_file), "-o", str(executable),
                    ]
                    built = subprocess.run(command, capture_output=True,
                                           text=True, timeout=90, check=False)
                    self.assertEqual(built.returncode, 0,
                                     (built.stderr or built.stdout)[-2200:])
                    run = subprocess.run([str(executable)], capture_output=True,
                                         text=True, timeout=30, check=False)
                    self.assertEqual(run.returncode, 0,
                                     (run.stderr or run.stdout)[-2200:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
