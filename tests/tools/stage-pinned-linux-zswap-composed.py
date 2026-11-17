#!/usr/bin/env python3
"""Round031 one-tree pinned original Linux MM+BIO composer, source-only.

Both predecessor producers render from the SAME verified original upstream
Git blobs. A deterministic three-way hunk merge rejects overlapping edits;
neither existing stager is ever invoked against a dirty checkout. The final
one-tree plan is authenticated, fully in memory, before any filesystem write.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
PINNED_SHA = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
ROUND031_MM_BIO_MACRO = "SWAPZ_ROUND031_MM_BIO_SOURCE"
ROUND031_ALL_FLAGS = (
    "SWAPZ_ROUND028_SLOT_EPOCH_SOURCE",
    "SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE",
    "SWAPZ_ROUND025_SIDEBAND_CI_ONLY",
    ROUND031_MM_BIO_MACRO,
)


def load_source_module(name: str, filename: str):
    source_spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    if not source_spec or not source_spec.loader:
        raise SourceCompositionError("unreadable-source-stager")
    module = importlib.util.module_from_spec(source_spec)
    sys.modules[name] = module
    source_spec.loader.exec_module(module)
    return module


class SourceCompositionError(RuntimeError):
    """Stable fail-closed first source, overlap, ownership or publication error."""


ORIGIN = load_source_module("round031_original_mm_source",
                            "stage-pinned-linux-zswap-origin.py")
BIO = load_source_module("round031_original_bio_source",
                         "stage-pinned-linux-zswap-sideband.py")

if ORIGIN.LINUX_COMMIT != PINNED_SHA or BIO.PINNED_LINUX_COMMIT != PINNED_SHA:
    raise SourceCompositionError("original-source-commit-drift")
for source_path, expected_sha in BIO.PINNED_BLOBS.items():
    if ORIGIN.ORIGINAL_BLOBS.get(source_path) != expected_sha:
        raise SourceCompositionError("overlap-original-blob-drift:" + source_path)


# Genuine original zsmalloc object only, never a freshly compressed folio or
# caller-manufactured source token. The real original locked folio/tree pins
# the entry across both this copy and following ordinary decompression.
# This is an opt-in producer of a separately owned BIO refcounted payload,
# NOT a compressed upper BIO or permission for DM to consume these bytes.
ROUND031_MM_BIO_SOURCE = r"""
#if defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY)
/* ROUND031_MM_ORIGINAL_OWNED_TRANSFER_START */
static __used noinline struct swapz_ci_owned_payload *
swapz_round031_mm_bio_create(struct zswap_entry *entry, swp_entry_t source_slot,
			     struct xarray *tree, pgoff_t offset)
{
	struct zswap_pool *source_pool;
	struct swapz_ci_owned_payload *owned = NULL;
	struct scatterlist compressed_sg[2];
	u8 *compressed_snapshot;
	u64 allocation_epoch;
	u32 source_crc32c;
	unsigned int compressed_length;

	/* The original evictor's locked folio and current xarray equality
	 * MUST precede every dereference. This code is never a BIO-ingress
	 * authenticator in the default build.
	 */
	if (!entry || !tree || entry != xa_load(tree, offset) ||
	    entry->swpentry.val != source_slot.val ||
	    PAGE_SIZE != 4096U || !entry->swapz_round028_store_bound ||
	    !entry->swapz_round028_allocation_epoch ||
	    !entry->swapz_round028_stored_entry_identity ||
	    !entry->length || entry->length > 3568U)
		return NULL;
	source_pool = zswap_entry_pool(entry);
	if (!source_pool || !source_pool->zs_pool ||
	    strcmp(source_pool->tfm_name, "lz4"))
		return NULL;
	allocation_epoch = swapz_round028_slot_epoch(source_slot);
	if (!allocation_epoch ||
	    allocation_epoch != entry->swapz_round028_allocation_epoch)
		return NULL;
	compressed_length = entry->length;
	/* No MM spinlock is held over GFP_KERNEL allocation or the SG read.
	 * The original folio and xarray match hold the stored entry stable.
	 */
	compressed_snapshot = kmalloc(compressed_length, GFP_KERNEL);
	if (!compressed_snapshot)
		return NULL;
	zs_obj_read_sg_begin(source_pool->zs_pool, entry->handle,
			     compressed_sg, compressed_length);
	memcpy_from_sglist(compressed_snapshot, compressed_sg, 0,
			   compressed_length);
	zs_obj_read_sg_end(source_pool->zs_pool, entry->handle);
	source_crc32c = ~crc32c(~0U, compressed_snapshot, compressed_length);
	if (entry == xa_load(tree, offset) &&
	    entry->swapz_round028_store_bound &&
	    source_pool == zswap_entry_pool(entry) &&
	    allocation_epoch == swapz_round028_slot_epoch(source_slot) &&
	    allocation_epoch == entry->swapz_round028_allocation_epoch &&
	    entry->length == compressed_length) {
		/* The constructor owns its *own* copy, independently refcounted
		 * for original BIO clone/split/uninit/reissue/abort. It rejects
		 * a missing STORE full-4096 SHA, bad codec/capacity or CRC.
		 */
		owned = swapz_ci_owned_create(compressed_snapshot,
					     compressed_length,
					     compressed_length,
					     entry->swapz_round028_store_sha256,
					     allocation_epoch,
					     entry->swapz_round028_stored_entry_identity,
					     1U, 1U, source_crc32c, GFP_KERNEL);
	}
	kfree_sensitive(compressed_snapshot);
	return owned;
}
/* ROUND031_MM_ORIGINAL_OWNED_TRANSFER_END */
#endif /* Round031 original MM to owned BIO source-only */
"""


def replace_once(text: str, before: str, after: str, path: str, label: str) -> str:
    if not before or before == after or text.count(before) != 1 or (
        after in text and after not in before
    ):
        raise SourceCompositionError(f"COMPOSE_CONFLICT:{path}:{label}")
    return text.replace(before, after, 1)


def changed_hunks(original: list[str], postimage: list[str], label: str):
    matcher = difflib.SequenceMatcher(
        None, original, postimage, autojunk=False)
    hunks = []
    for operation, start, finish, new_start, new_finish in matcher.get_opcodes():
        if operation == "equal":
            continue
        hunks.append((start, finish, postimage[new_start:new_finish], label))
    return hunks


def merge_original_postimages(path: str, original: str,
                              origin_postimage: str,
                              bio_postimage: str) -> str:
    """Diff3 on exact original preimage; no guessing overlapping patch order."""
    original_lines = original.splitlines(keepends=True)
    hunks = changed_hunks(original_lines,
                          origin_postimage.splitlines(keepends=True), "MM")
    hunks += changed_hunks(original_lines,
                           bio_postimage.splitlines(keepends=True), "BIO")
    hunks.sort(key=lambda item: (item[0], item[1], item[3]))
    accepted = []
    for hunk in hunks:
        if accepted:
            prior = accepted[-1]
            overlaps = (
                hunk[0] < prior[1] or
                (hunk[0] == prior[0] and hunk[1] == prior[1]) or
                (hunk[0] == hunk[1] == prior[0] == prior[1]))
            if overlaps:
                if hunk[:3] == prior[:3]:
                    continue  # exactly identical postimage, once only
                raise SourceCompositionError(
                    f"COMPOSE_CONFLICT:{path}:overlap:{prior[3]}:{hunk[3]}"
                )
        accepted.append(hunk)
    result = list(original_lines)
    for start, finish, insertion, _label in reversed(accepted):
        result[start:finish] = insertion
    merged = "".join(result)
    if merged == original:
        raise SourceCompositionError(f"COMPOSE_CONFLICT:{path}:empty-postimage")
    return merged


def apply_mm_bio_source(path: str, composed: str) -> str:
    if path == "include/linux/bio.h":
        return replace_once(
            composed, "struct queue_limits;\n",
            """struct queue_limits;
#if defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \\
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY)
/* Real original MM provides epoch, STORE SHA and zsmalloc copy.
 * Only the BIO owns this independently allocated reference.
 * These symbols are absent in a default production build.
 */
struct swapz_ci_owned_payload *swapz_ci_owned_create(
		const u8 *source, size_t capacity, size_t compressed_length,
		const u8 original_sha256[32], u64 source_epoch,
		u64 source_identity, u8 version, u8 codec,
		u32 expected_crc32c, gfp_t gfp);
void swapz_ci_owned_put(struct swapz_ci_owned_payload *owner);
#endif
""", path, "owned-api")
    if path == "include/linux/swap_ops.h":
        return replace_once(
            composed, "struct swap_io_ctx {\n",
            """struct swap_io_ctx {
#if defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \\
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY)
	/* Original evictor moves this ONE initial owned reference into BIO
	 * before synchronous/async submit. Caller puts it on every fallback.
	 */
	struct swapz_ci_owned_payload *swapz_round031_owned;
#endif
""", path, "io-owner")
    if path == "block/bio.c":
        composed = replace_once(
            composed,
            "static struct swapz_ci_owned_payload *__maybe_unused\nswapz_ci_owned_create(",
            "struct swapz_ci_owned_payload *\nswapz_ci_owned_create(",
            path, "owned-create-global")
        composed = replace_once(
            composed,
            "static void swapz_ci_owned_put(struct swapz_ci_owned_payload *owner)",
            "void swapz_ci_owned_put(struct swapz_ci_owned_payload *owner)",
            path, "owned-put-global")
        composed = replace_once(
            composed,
            "static bool swapz_ci_owned_valid(const struct swapz_ci_owned_payload *owner)",
            "static bool swapz_ci_owned_valid(const struct swapz_ci_owned_payload *owner)",
            path, "no-op-not-allowed") if False else composed
        return composed
    if path == "mm/page_io.c":
        return replace_once(
            composed,
            "\tbio->bi_swap_origin = sio->swap_origin;\n\tbio->bi_iter.bi_size = sio->len;\n\tbio->bi_iter.bi_sector = swap_folio_sector",
            """	bio->bi_swap_origin = sio->swap_origin;
	bio->bi_iter.bi_size = sio->len;
#if defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \\
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY)
	/* This exact original BLOCK write is one 4096-page replacement.
	 * Move ONE independently owned ref into the bio lifecycle. No
	 * compressed bytes are ever submitted as ordinary swap payload.
	 * A merge/multi-page/other backing keeps the normal RAW fallback.
	 */
	if (ctx->swapz_round031_owned && sio->nr_bvecs == 1 &&
	    bio->bi_iter.bi_size == 4096U) {
		bio->bi_swapz_ci_sideband = ctx->swapz_round031_owned;
		ctx->swapz_round031_owned = NULL;
	}
#endif
	bio->bi_iter.bi_sector = swap_folio_sector""",
            path, "bdev-single-4096-attachment")
    if path == "mm/zswap.c":
        composed = replace_once(
            composed,
            "#include <linux/zsmalloc.h>\n",
            """#include <linux/zsmalloc.h>
#if defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \\
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY)
#include <linux/bio.h>
#endif
""", path, "real-bio-api-inclusion")
        composed = replace_once(
            composed,
            "static int zswap_writeback_entry(struct zswap_entry *entry,\n",
            ROUND031_MM_BIO_SOURCE +
            "static int zswap_writeback_entry(struct zswap_entry *entry,\n",
            path, "original-evictor-source")
        composed = replace_once(
            composed,
            "\t(void)swapz_round030_snapshot_stored_lz4(entry, swpentry, tree, offset);\n",
            """#if defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \\
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY)
	/* Source-only LIVE ORIGINAL MM call. Allocate while the folio,
	 * original swapcache and stored zswap pool remain owned; do not
	 * manufacture a copied or caller-supplied source epoch.
	 */
	ctx.swapz_round031_owned =
		swapz_round031_mm_bio_create(entry, swpentry, tree, offset);
#endif
	(void)swapz_round030_snapshot_stored_lz4(entry, swpentry, tree, offset);
""", path, "original-eviction-call")
        composed = replace_once(
            composed,
            "\tswap_write_submit(&ctx);\n\n\treturn 0;\n\nerr:\n",
            """	swap_write_submit(&ctx);
#if defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \\
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY)
	/* If no block BIO accepted the owner, release it here. Otherwise
	 * bio_uninit/bio_reset/bio_prepare_reissue/final clone put owns it.
	 */
	swapz_ci_owned_put(ctx.swapz_round031_owned);
	ctx.swapz_round031_owned = NULL;
#endif

	return 0;

err:
#if defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \\
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY)
	swapz_ci_owned_put(ctx.swapz_round031_owned);
	ctx.swapz_round031_owned = NULL;
#endif
""", path, "source-failure-and-final-release")
        return composed
    return composed


def compose_postimage(path: str, original_bytes: bytes, *,
                      with_kunit: bool = True) -> bytes:
    """In-memory exactly pinned original source -> deterministic combined C."""
    expected = dict(ORIGIN.ORIGINAL_BLOBS)
    expected.update(ORIGIN.ROUND026_ALLOCATOR_ORIGINAL_BLOBS)
    if with_kunit:
        expected.update(ORIGIN.KUNIT_ORIGINAL_BLOBS)
    editable_paths = set(ORIGIN.EDITS) | set(ORIGIN.ROUND026_ALLOCATOR_ORIGINAL_BLOBS)
    if with_kunit:
        editable_paths |= set(ORIGIN.KUNIT_EDITS)
    if path not in editable_paths:
        raise SourceCompositionError(f"COMPOSE_CONFLICT:{path}:foreign-path")
    ORIGIN.check_preimage(path, original_bytes, expected[path])
    preimage = original_bytes.decode("utf-8")
    original_changed = ORIGIN.render_source(
        path, preimage,
        round026_allocator_probe=path == "mm/swapfile.c",
        round028_slot_epoch_source=path in ("mm/swapfile.c", "mm/zswap.c"))
    if path in BIO.PINNED_BLOBS:
        sideband_changed = BIO.render_source(path, original_bytes).decode("utf-8")
        changed = merge_original_postimages(
            path, preimage, original_changed, sideband_changed)
    else:
        changed = original_changed
    changed = apply_mm_bio_source(path, changed)
    if path == "mm/zswap.c":
        for required in (
            "swapz_round028_slot_epoch(swpentry)",
            "swapz_round030_snapshot_stored_lz4",
            "swapz_round031_mm_bio_create(entry, swpentry, tree, offset)",
            "zs_obj_read_sg_begin(", "swapz_ci_owned_create(",
            "__swap_writeout(&ctx, folio);", "swap_write_submit(&ctx);",
            "zswap_decompress(entry, folio)", "kfree_sensitive(compressed_snapshot);",
        ):
            if required not in changed:
                raise SourceCompositionError(
                    "COMPOSE_CONFLICT:mm/zswap.c:missing:" + required)
    if path == "block/bio.c" and not all(token in changed for token in (
        "swapz_ci_owned_get(owner)", "swapz_ci_owned_put(owner)",
        "swapz_ci_owned_create(", "bi_swap_origin =",
        "SWAPZ_ROUND025_SIDEBAND_CI_ONLY",
    )):
        raise SourceCompositionError("COMPOSE_CONFLICT:block/bio.c:owner-or-origin")
    if path == "mm/page_io.c" and not all(token in changed for token in (
        "bio->bi_swap_origin = sio->swap_origin;",
        "bio->bi_swapz_ci_sideband = ctx->swapz_round031_owned;",
        "bio->bi_iter.bi_size = sio->len;",
    )):
        raise SourceCompositionError("COMPOSE_CONFLICT:mm/page_io.c:bio-size")
    if changed == preimage:
        raise SourceCompositionError("COMPOSE_CONFLICT:" + path + ":unchanged")
    return changed.encode("utf-8")


def build_plan(originals: dict[str, bytes], *,
               with_kunit: bool = True) -> dict[str, bytes]:
    expected = dict(ORIGIN.ORIGINAL_BLOBS)
    expected.update(ORIGIN.ROUND026_ALLOCATOR_ORIGINAL_BLOBS)
    if with_kunit:
        expected.update(ORIGIN.KUNIT_ORIGINAL_BLOBS)
    editable_paths = set(ORIGIN.EDITS) | set(ORIGIN.ROUND026_ALLOCATOR_ORIGINAL_BLOBS)
    if with_kunit:
        editable_paths |= set(ORIGIN.KUNIT_EDITS)
    if set(originals) != editable_paths:
        raise SourceCompositionError(
            "COMPOSE_CONFLICT:original-source-set:missing-or-extra")
    planned = {
        path: compose_postimage(path, originals[path], with_kunit=with_kunit)
        for path in sorted(editable_paths)
    }
    if with_kunit:
        ORIGIN.validate_kunit_source(ORIGIN.KUNIT_SOURCE)
        planned[ORIGIN.KUNIT_SOURCE_PATH] = ORIGIN.KUNIT_SOURCE.encode("utf-8")
    return planned


def stage_composed(original_root: Path, manifest: Path, *,
                   with_kunit: bool = True) -> dict[str, object]:
    try:
        root = original_root.resolve(strict=True)
    except OSError as error:
        raise SourceCompositionError("complete-original-linux-checkout-required") from error
    if manifest.resolve(strict=False) == root or root in manifest.resolve(strict=False).parents:
        raise SourceCompositionError("manifest-inside-original-linux-checkout")
    if root.is_symlink():
        raise SourceCompositionError("symlink-checkout-refused")
    ORIGIN.validate_checkout(
        root, with_kunit=with_kunit, with_round026_allocator_probe=True)
    original_paths = set(ORIGIN.EDITS)
    original_paths.update(ORIGIN.ROUND026_ALLOCATOR_ORIGINAL_BLOBS)
    if with_kunit:
        original_paths.update(ORIGIN.KUNIT_EDITS)
    originals = {path: (root / path).read_bytes() for path in sorted(original_paths)}
    staged = build_plan(originals, with_kunit=with_kunit)
    if with_kunit and (root / ORIGIN.KUNIT_SOURCE_PATH).exists():
        raise SourceCompositionError("COMPOSE_CONFLICT:block/swap-bio-origin-kunit.c:present")
    # All original preimages have strict blob identity and clean-index proof.
    # No mutation until EVERY original-side render and all conflicts pass.
    before = dict(originals)
    if with_kunit:
        before[ORIGIN.KUNIT_SOURCE_PATH] = None
    for path, expected in before.items():
        target = root / path
        if target.is_symlink() or (
            expected is not None and target.read_bytes() != expected
        ) or (expected is None and target.exists()):
            raise SourceCompositionError("COMPOSE_CONFLICT:" + path + ":late-preimage")
    published = []
    try:
        for path in sorted(staged):
            ORIGIN.write_atomic(root / path, staged[path])
            published.append(path)
        items = [
            {"path": path, "original_git_sha1":
             (ORIGIN.blob_sha(before[path]) if before[path] is not None else None),
             "staged_git_sha1": ORIGIN.blob_sha(staged[path]),
             "staged_sha256": hashlib.sha256(staged[path]).hexdigest(),
             "bytes": len(staged[path])}
            for path in sorted(staged)
        ]
        result = {
            "schema": "swapz-pinned-linux-mm-bio-composed-source-v1",
            "source_repository": "torvalds/linux", "source_sha": PINNED_SHA,
            "original_source_verified": True, "source_manifest_complete": True,
            "changed_paths": items, "actual_original_mm_bio_composed": True,
            "source_ownership": "REAL_ORIGINAL_MM_TO_BIO_CI_ONLY_NOT_DM",
            "round031_macro": ROUND031_MM_BIO_MACRO,
            "compiled": False, "kunit_executed": False,
            "phase_a_qualified": False, "phase_b_enabled": False,
            "direct_compressed_handoff_enabled": False,
        }
        serialized = (json.dumps(result, sort_keys=True, indent=2) + "\n").encode()
        # Manifest is outside upstream Linux; output cannot predate staging.
        manifest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=manifest.parent, delete=False,
                                         prefix=".round031-composed-") as output:
            temporary = Path(output.name)
            output.write(serialized)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.replace(temporary, manifest)
        finally:
            temporary.unlink(missing_ok=True)
        return result
    except (OSError, ORIGIN.StagingError, SourceCompositionError) as error:
        # All original files restored, or loudly report rollback failure.
        errors = ORIGIN.rollback_sources(root, before, staged, published)
        if errors:
            raise SourceCompositionError(
                "COMPOSE_ROLLBACK_INCOMPLETE:" + ",".join(errors)) from error
        raise SourceCompositionError("COMPOSE_PUBLICATION_ROLLED_BACK") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--without-kunit", action="store_true")
    args = parser.parse_args()
    result = stage_composed(args.linux_root, args.manifest,
                            with_kunit=not args.without_kunit)
    print("ROUND031_ORIGINAL_MM_BIO_COMPOSED_SOURCE_ONLY " +
          "source=" + result["source_sha"] +
          " paths=" + str(len(result["changed_paths"])))
    print("LIVE_COMPRESSED=DISABLED LOADED_4096=NOT_RUN PHYSICAL=NOT_RUN")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, UnicodeError, SourceCompositionError,
            ORIGIN.StagingError, BIO.SourceGateError) as error:
        print("BLOCKED first_cause=" + str(error))
        raise SystemExit(2) from error
