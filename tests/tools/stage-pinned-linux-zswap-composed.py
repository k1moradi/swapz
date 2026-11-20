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



# Round032 remains undefined in every default source object and must be
# explicitly combined with the original MM and independently owned BIO gates.
ROUND032_BIO_COPY_VIEW_MACRO = "SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY"
ROUND032_VIEW_CONDITION = (
    "defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && "
    "defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && "
    "defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY)"
)

# Actual original block/bio.c implementation, source-compiled only.
# Caller proves synchronous lifetime of the parent BIO; no RCU search or
# guessed source owner is permitted. The temporary extra owning reference
# makes every early-return balanced even for a late invalid immutable record.
ROUND032_BIO_COPY_VIEW_SOURCE = r"""
#if defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY)
/* ROUND032_ORIGINAL_BIO_COPY_VIEW_BEGIN */
static bool swapz_ci_view_ranges_overlap(const void *first, size_t first_size,
					   const void *second, size_t second_size)
{
	unsigned long first_start = (unsigned long)first;
	unsigned long second_start = (unsigned long)second;
	unsigned long first_end, second_end;

	/* Pointer ordering across unrelated allocations is not C defined.
	 * Reject address wrap before numeric extent comparisons.
	 */
	if (check_add_overflow(first_start, first_size, &first_end) ||
	    check_add_overflow(second_start, second_size, &second_end))
		return true;
	return first_start < second_end && second_start < first_end;
}

/*
 * CI-only original pinned BIO-owned read-only LZ4 view. The caller must
 * already own a stable live original BIO throughout this synchronous call:
 * refcount_inc_not_zero alone is NOT an unlocked lifetime acquisition.
 * No heap allocation, no zpool pointer, no authentication of DM provenance,
 * no upper compressed completion and no change to ordinary 4096 swap I/O.
 *
 * Original mm/page_io.c's embedded swap_iocb calls bio_init() with a
 * pre-populated bvec but manually sets bi_iter.bi_size. Its original bio
 * therefore has bi_vcnt == 0, not 1: this strict geometry is intentional.
 */
int swapz_ci_bio_snapshot_lz4_v1(const struct bio *source_bio,
				struct swapz_ci_lz4_owned_view_v1 *view,
				u8 *owned_destination, size_t capacity)
{
	struct swapz_ci_owned_payload *owner;
	struct swapz_ci_lz4_owned_view_v1 snapshot = {};
	int result = -EINVAL;

	if (!source_bio || !view || !owned_destination)
		return -EINVAL;
	if (bio_op(source_bio) != REQ_OP_WRITE ||
	    !(source_bio->bi_opf & REQ_SWAP) ||
	    source_bio->bi_swap_origin !=
		SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK ||
	    source_bio->bi_iter.bi_size != 4096U ||
	    bio_sectors(source_bio) != 8U ||
	    source_bio->bi_iter.bi_idx ||
	    source_bio->bi_iter.bi_offset ||
	    source_bio->bi_vcnt ||
	    (source_bio->bi_flags & (1U << BIO_CLONED)) ||
	    !source_bio->bi_io_vec ||
	    !source_bio->bi_io_vec[0].bv_page ||
	    source_bio->bi_io_vec[0].bv_len != 4096U ||
	    source_bio->bi_io_vec[0].bv_offset)
		return -EOPNOTSUPP;

	owner = swapz_ci_owned_get(source_bio->bi_swapz_ci_sideband);
	if (!owner)
		return -ESTALE;
	if (!owner->source_swap_entry || !swapz_ci_owned_valid(owner)) {
		result = -ESTALE;
		goto put_owner;
	}
	if (capacity < owner->compressed_length) {
		result = -ENOSPC;
		goto put_owner;
	}
	/* No writes whatsoever on invalid output aliases. Do not let the
	 * destination modify the immutable source bytes or metadata.
	 */
	if (swapz_ci_view_ranges_overlap(view, sizeof(*view),
					 owned_destination,
					 owner->compressed_length) ||
	    swapz_ci_view_ranges_overlap(owned_destination,
					 owner->compressed_length,
					 owner->compressed_bytes,
					 owner->compressed_length) ||
	    swapz_ci_view_ranges_overlap(view, sizeof(*view),
					 owner->compressed_bytes,
					 owner->compressed_length)) {
		result = -EINVAL;
		goto put_owner;
	}
	snapshot.source_swap_entry = owner->source_swap_entry;
	snapshot.source_slot_epoch = owner->slot_epoch;
	snapshot.stored_entry_identity = owner->source_identity;
	snapshot.compressed_crc32c = owner->compressed_crc32c;
	snapshot.compressed_length = owner->compressed_length;
	snapshot.decoded_length = owner->decoded_length;
	snapshot.representation_version = owner->representation_version;
	snapshot.codec = owner->codec;
	memcpy(snapshot.original_sha256, owner->original_sha256,
	       sizeof(snapshot.original_sha256));

	/* These are the FINAL operations. No failure point after first write.
	 * Both caller outputs are private value copies after the call.
	 */
	memcpy(owned_destination, owner->compressed_bytes,
	       owner->compressed_length);
	memcpy(view, &snapshot, sizeof(snapshot));
	result = 0;
put_owner:
	swapz_ci_owned_put(owner);
	return result;
}
/* ROUND032_ORIGINAL_BIO_COPY_VIEW_END */
EXPORT_SYMBOL_GPL(swapz_ci_bio_snapshot_lz4_v1);
#endif /* opt-in Round032 ABI copied view, no normal object export */
"""

ROUND032_BIO_VIEW_HEADER = """#if defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \\
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \\
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY)
/* CI-only source C value; not a serialized format or physical ABI. */
struct swapz_ci_lz4_owned_view_v1 {
	u64 source_swap_entry;
	u64 source_slot_epoch;
	u64 stored_entry_identity;
	u32 compressed_crc32c;
	u16 compressed_length;
	u16 decoded_length;
	u8 representation_version;
	u8 codec;
	u8 original_sha256[32];
};

/* Caller holds source_bio stable for the ENTIRE synchronous copy.
 * No borrowed owner data/pointers survive this function's return.
 */
int swapz_ci_bio_snapshot_lz4_v1(
		const struct bio *source_bio,
		struct swapz_ci_lz4_owned_view_v1 *view,
		u8 *owned_destination, size_t capacity);
struct swapz_ci_owned_payload *swapz_ci_owned_create_source_v1(
		const u8 *compressed_source, size_t input_capacity,
		size_t compressed_length, const u8 original_sha256[32],
		u64 slot_epoch, u64 source_identity, u64 source_swap_entry,
		u8 representation_version, u8 codec, u32 expected_crc32c,
		gfp_t allocation_flags);
#endif
"""

ROUND032_BIO_CORE_BEFORE = (
    "struct swapz_ci_owned_payload *\n"
    "swapz_ci_owned_create(const u8 *compressed_source, size_t input_capacity,"
)
ROUND032_BIO_CORE_AFTER = """#if defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \\
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \\
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY)
/* ROUND032_BIO_SEALED_CONSTRUCTOR_BEGIN */
static struct swapz_ci_owned_payload *
swapz_ci_owned_create_internal(const u8 *compressed_source, size_t input_capacity,
#else
struct swapz_ci_owned_payload *
swapz_ci_owned_create(const u8 *compressed_source, size_t input_capacity,
#endif
"""

ROUND032_BIO_CORE_WRAPPERS = """
#if defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \\
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \\
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY)
/* Legacy original KUnit BIO constructor stays source-compatible. Its zero
 * source slot refuses v1 snapshots, while clone/split lifetime still works.
 */
struct swapz_ci_owned_payload *
swapz_ci_owned_create(const u8 *compressed_source, size_t input_capacity,
		      size_t compressed_length, const u8 original_sha256[32],
		      u64 slot_epoch, u64 source_identity,
		      u8 representation_version, u8 codec,
		      u32 expected_crc32c, gfp_t allocation_flags)
{
	return swapz_ci_owned_create_internal(
		compressed_source, input_capacity, compressed_length,
		original_sha256, slot_epoch, source_identity, 0U,
		representation_version, codec, expected_crc32c, allocation_flags);
}

/* Genuine original locked MM supplies FULL nonzero swp_entry_t.val
 * BEFORE the initial refcount publication, not as a later metadata write.
 */
struct swapz_ci_owned_payload *
swapz_ci_owned_create_source_v1(
		const u8 *compressed_source, size_t input_capacity,
		size_t compressed_length, const u8 original_sha256[32],
		u64 slot_epoch, u64 source_identity, u64 source_swap_entry,
		u8 representation_version, u8 codec, u32 expected_crc32c,
		gfp_t allocation_flags)
{
	if (!source_swap_entry)
		return NULL;
	return swapz_ci_owned_create_internal(
		compressed_source, input_capacity, compressed_length,
		original_sha256, slot_epoch, source_identity, source_swap_entry,
		representation_version, codec, expected_crc32c, allocation_flags);
}
/* ROUND032_BIO_SEALED_CONSTRUCTOR_END */
#endif /* Round032 separate original MM-sealed constructor */
"""

def apply_round032_bio_view(path: str, composed: str) -> str:
    """Only generated exact original Linux C, never old pinned stagers."""
    if path == "include/linux/bio.h":
        return replace_once(
            composed, "void swapz_ci_owned_put(struct swapz_ci_owned_payload *owner);\n#endif\n",
            "void swapz_ci_owned_put(struct swapz_ci_owned_payload *owner);\n#endif\n" +
            ROUND032_BIO_VIEW_HEADER,
            path, "original-owned-copy-header")
    if path == "block/bio.c":
        # Add source slot solely under the new opt-in gate. The original
        # old 11-case KUnit constructor's source slot is deliberately zero.
        composed = replace_once(
            composed, "struct swapz_ci_owned_payload {\n\trefcount_t references;\n",
            """struct swapz_ci_owned_payload {
	refcount_t references;
#if defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \\
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \\
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY)
	u64 source_swap_entry; /* FULL original MM value before first ref. */
#endif
""", path, "full-original-mm-source-slot")
        composed = replace_once(
            composed, ROUND032_BIO_CORE_BEFORE,
            ROUND032_BIO_CORE_AFTER, path, "internal-sealed-owner-core")
        composed = replace_once(
            composed, "u64 slot_epoch, u64 source_identity,\n"
                      "\t\t      u8 representation_version, u8 codec,\n",
            """u64 slot_epoch, u64 source_identity,
#if defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \\
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \\
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY)
		      u64 source_swap_entry,
#endif
		      u8 representation_version, u8 codec,
""", path, "internal-source-slot-parameter")
        composed = replace_once(
            composed,
            "\t/* Publish the ONE initial owning ref only after all checks succeed. */\n"
            "\trefcount_set(&owner->references, 1);\n",
            """#if defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \\
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \\
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY)
	/* Final write to immutable metadata BEFORE the initial ref is live. */
	owner->source_swap_entry = source_swap_entry;
#endif
	/* Publish the ONE initial owning ref only after all checks succeed. */
	refcount_set(&owner->references, 1);
""", path, "slot-before-sealed-first-ref")
        composed = replace_once(
            composed, "\nstatic bool swapz_ci_owned_valid(",
            ROUND032_BIO_CORE_WRAPPERS +
            "\nstatic bool swapz_ci_owned_valid(",
            path, "source-constructor-and-legacy-kunit")
        composed = replace_once(
            composed, "\nstatic void swapz_ci_bio_detach(",
            "\n" + ROUND032_BIO_COPY_VIEW_SOURCE +
            "\nstatic void swapz_ci_bio_detach(",
            path, "original-exported-synchronous-copy")
        return composed
    if path == "mm/zswap.c":
        original_call = """\t\towned = swapz_ci_owned_create(compressed_snapshot,
					     compressed_length,
					     compressed_length,
					     entry->swapz_round028_store_sha256,
					     allocation_epoch,
					     entry->swapz_round028_stored_entry_identity,
					     1U, 1U, source_crc32c, GFP_KERNEL);"""
        new_call = """#if defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \\
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \\
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY)
		/* This is the TRUE full original MM swp_entry_t type+offset;
		 * reject unrepresentable native pointer widths before casting.
		 */
		if (source_slot.val &&
		    sizeof(source_slot.val) <= sizeof(u64))
			owned = swapz_ci_owned_create_source_v1(
				compressed_snapshot, compressed_length,
				compressed_length, entry->swapz_round028_store_sha256,
				allocation_epoch,
				entry->swapz_round028_stored_entry_identity,
				(u64)source_slot.val, 1U, 1U, source_crc32c,
				GFP_KERNEL);
#else
""" + original_call + """
#endif"""
        return replace_once(composed, original_call, new_call, path,
                            "original-mm-full-source-slot-sealed")
    return composed



# Round034 is a NEW additional guard. Old real original BIO KUnit's 11
# lifecycle cases and the original immutable upstream blobs are unchanged.
# These tests run IN original block/bio.c so they invoke the actual exported
# provider and its separately owned private C allocation, not a host mock.
ROUND034_ORIGINAL_V1_KUNIT_MACRO = "SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST"
ROUND034_KUNIT_GUARD = (
    "defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && "
    "defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && "
    "defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && "
    "defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)"
)
ROUND034_KUNIT_HEADERS = r"""
#if defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
#include <linux/lz4.h>
#include <crypto/sha2.h>
#endif
"""

ROUND034_KUNIT_SOURCE = r"""
#if defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
/*
 * KUnit SYNTHETIC PRODUCER STIMULUS; even CONFIG_ZSWAP=y does not make
 * this an MM STORE, an actual eviction, or proof of a live DM mapping.
 * The tested function and owning allocation ARE genuine original bio.c C.
 * No block device, swap area, privileged host operation or bio_endio.
 */
struct swapz_round034_v1_fixture {
	struct bio bio;
	struct bio_vec vector;
	struct page *page;
	u8 *compressed;
	u8 *destination;
	u8 *decoded;
	u8 digest[32];
	size_t compressed_length;
	bool bio_initialized;
};

static void swapz_round034_v1_fixture_release(void *argument)
{
	struct swapz_round034_v1_fixture *fixture = argument;

	if (fixture->bio_initialized)
		bio_uninit(&fixture->bio);
	if (fixture->page)
		__free_page(fixture->page);
}

/* Real original pre-populated one-bvec page_io geometry: bi_vcnt == 0. */
static struct swapz_round034_v1_fixture *
swapz_round034_v1_fixture_create(struct kunit *test)
{
	struct swapz_round034_v1_fixture *fixture;
	struct swapz_ci_owned_payload *owner;
	u8 *workspace;
	u8 *plaintext;
	int length;

	fixture = kunit_kzalloc(test, sizeof(*fixture), GFP_KERNEL);
	if (!fixture) {
		KUNIT_FAIL(test, "v1 fixture allocation refused");
		return NULL;
	}
	if (kunit_add_action_or_reset(test, swapz_round034_v1_fixture_release,
				      fixture)) {
		KUNIT_FAIL(test, "v1 cleanup registration refused");
		return NULL;
	}
	fixture->page = alloc_page(GFP_KERNEL);
	fixture->compressed = kunit_kmalloc(test, 3568U, GFP_KERNEL);
	fixture->destination = kunit_kmalloc(test, 3568U, GFP_KERNEL);
	fixture->decoded = kunit_kmalloc(test, PAGE_SIZE, GFP_KERNEL);
	workspace = kunit_kmalloc(test, LZ4_MEM_COMPRESS, GFP_KERNEL);
	if (!fixture->page || !fixture->compressed || !fixture->destination ||
	    !fixture->decoded || !workspace) {
		KUNIT_FAIL(test, "v1 bounded allocation refused");
		return NULL;
	}
	plaintext = page_address(fixture->page);
	memset(plaintext, 0x5a, PAGE_SIZE);
	/* The digest covers the original entire 4096, not compressed padding. */
	sha256(plaintext, PAGE_SIZE, fixture->digest);
	length = LZ4_compress_default((const char *)plaintext,
				      (char *)fixture->compressed, PAGE_SIZE,
				      3568, workspace);
	if (length <= 1 || length > 3568) {
		KUNIT_FAIL(test, "real dictionary-free LZ4 compressor refused");
		return NULL;
	}
	fixture->compressed_length = (size_t)length;
	owner = swapz_ci_owned_create_source_v1(
		fixture->compressed, fixture->compressed_length,
		fixture->compressed_length, fixture->digest,
		11U, 13U, 0x123456U, 1U, 1U,
		~crc32c(~0U, fixture->compressed, fixture->compressed_length),
		GFP_KERNEL);
	if (!owner) {
		KUNIT_FAIL(test, "genuine original sealed v1 owner refused");
		return NULL;
	}
	fixture->vector.bv_page = fixture->page;
	fixture->vector.bv_len = PAGE_SIZE;
	fixture->vector.bv_offset = 0;
	bio_init(&fixture->bio, NULL, &fixture->vector, 1,
		 REQ_OP_WRITE | REQ_SWAP);
	fixture->bio_initialized = true;
	fixture->bio.bi_iter.bi_size = PAGE_SIZE;
	fixture->bio.bi_swap_origin =
		SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;
	fixture->bio.bi_swapz_ci_sideband = owner;
	return fixture;
}

/* Compare both output objects to the EXACT pre-call bytes on each error. */
static void swapz_round034_v1_expect_refusal(struct kunit *test,
					   struct bio *source,
					   size_t capacity, int expected)
{
	struct swapz_ci_lz4_owned_view_v1 view;
	u8 destination[128];
	int error;

	memset(&view, 0xa5, sizeof(view));
	memset(destination, 0x6b, sizeof(destination));
	error = swapz_ci_bio_snapshot_lz4_v1(source, &view, destination,
					    capacity);
	KUNIT_EXPECT_EQ(test, error, expected);
	KUNIT_EXPECT_PTR_EQ(test, memchr_inv(&view, 0xa5, sizeof(view)), NULL);
	KUNIT_EXPECT_PTR_EQ(test, memchr_inv(destination, 0x6b,
					   sizeof(destination)), NULL);
}

static void swapz_round034_v1_owned_copy_kunit(struct kunit *test)
{
	struct swapz_round034_v1_fixture *fixture =
		swapz_round034_v1_fixture_create(test);
	struct swapz_ci_lz4_owned_view_v1 view = {};
	u8 decoded_sha[32];
	int error;

	KUNIT_ASSERT_NOT_NULL(test, fixture);
	KUNIT_EXPECT_EQ(test, fixture->bio.bi_vcnt, 0U);
	KUNIT_EXPECT_EQ(test, bio_sectors(&fixture->bio), 8U);
	KUNIT_EXPECT_EQ(test, fixture->bio.bi_iter.bi_size, 4096U);
	memset(fixture->destination, 0x6b, 3568U);
	error = swapz_ci_bio_snapshot_lz4_v1(
		&fixture->bio, &view, fixture->destination, 3568U);
	KUNIT_ASSERT_EQ(test, error, 0);
	KUNIT_EXPECT_EQ(test, view.source_swap_entry, (u64)0x123456U);
	KUNIT_EXPECT_EQ(test, view.source_slot_epoch, (u64)11U);
	KUNIT_EXPECT_EQ(test, view.stored_entry_identity, (u64)13U);
	KUNIT_EXPECT_EQ(test, view.compressed_length,
			(u16)fixture->compressed_length);
	KUNIT_EXPECT_EQ(test, view.decoded_length, (u16)4096U);
	KUNIT_EXPECT_EQ(test, view.representation_version, (u8)1);
	KUNIT_EXPECT_EQ(test, view.codec, (u8)1);
	KUNIT_EXPECT_EQ(test, view.compressed_crc32c,
			~crc32c(~0U, fixture->compressed,
				 fixture->compressed_length));
	KUNIT_EXPECT_EQ(test, memcmp(fixture->destination,
				     fixture->compressed,
				     fixture->compressed_length), 0);
	KUNIT_EXPECT_EQ(test, memcmp(view.original_sha256,
				     fixture->digest, sizeof(fixture->digest)), 0);
	error = LZ4_decompress_safe((const char *)fixture->destination,
				    (char *)fixture->decoded,
				    view.compressed_length, PAGE_SIZE);
	KUNIT_ASSERT_EQ(test, error, (int)PAGE_SIZE);
	sha256(fixture->decoded, PAGE_SIZE, decoded_sha);
	KUNIT_EXPECT_EQ(test, memcmp(decoded_sha, view.original_sha256,
				     sizeof(decoded_sha)), 0);
	/* A changed constructor input must not alter the sealed private copy. */
	fixture->compressed[0] ^= 0x80U;
	KUNIT_EXPECT_EQ(test, swapz_ci_bio_snapshot_lz4_v1(
				&fixture->bio, &view, fixture->destination,
				3568U), 0);
	KUNIT_EXPECT_EQ(test, LZ4_decompress_safe(
				(const char *)fixture->destination,
				(char *)fixture->decoded,
				view.compressed_length, PAGE_SIZE),
			(int)PAGE_SIZE);
	/* No read from freed BIO. Caller-owned output survives final uninit. */
	bio_uninit(&fixture->bio);
	KUNIT_EXPECT_EQ(test, memcmp(fixture->decoded,
				     page_address(fixture->page), PAGE_SIZE), 0);
}

static void swapz_round034_v1_bio_reject_kunit(struct kunit *test)
{
	struct swapz_round034_v1_fixture *fixture =
		swapz_round034_v1_fixture_create(test);
	struct bio *source;

	KUNIT_ASSERT_NOT_NULL(test, fixture);
	source = &fixture->bio;
	source->bi_opf = REQ_OP_READ | REQ_SWAP;
	swapz_round034_v1_expect_refusal(test, source, 128U, -EOPNOTSUPP);
	source->bi_opf = REQ_OP_WRITE;
	swapz_round034_v1_expect_refusal(test, source, 128U, -EOPNOTSUPP);
	source->bi_opf = REQ_OP_WRITE | REQ_SWAP;
	source->bi_iter.bi_size = 2048U;
	swapz_round034_v1_expect_refusal(test, source, 128U, -EOPNOTSUPP);
	source->bi_iter.bi_size = 4096U;
	source->bi_iter.bi_offset = 512U;
	swapz_round034_v1_expect_refusal(test, source, 128U, -EOPNOTSUPP);
	source->bi_iter.bi_offset = 0U;
	source->bi_vcnt = 1;
	swapz_round034_v1_expect_refusal(test, source, 128U, -EOPNOTSUPP);
	source->bi_vcnt = 0;
	source->bi_swap_origin = SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;
	swapz_round034_v1_expect_refusal(test, source, 128U, -EOPNOTSUPP);
	source->bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;
	source->bi_flags |= (1U << BIO_CLONED);
	swapz_round034_v1_expect_refusal(test, source, 128U, -EOPNOTSUPP);
	source->bi_flags &= ~(1U << BIO_CLONED);
	source->bi_iter.bi_idx = 1;
	swapz_round034_v1_expect_refusal(test, source, 128U, -EOPNOTSUPP);
	source->bi_iter.bi_idx = 0;
}

static void swapz_round034_v1_owner_reject_kunit(struct kunit *test)
{
	struct swapz_round034_v1_fixture *fixture =
		swapz_round034_v1_fixture_create(test);
	struct swapz_ci_owned_payload *owner;

	KUNIT_ASSERT_NOT_NULL(test, fixture);
	owner = fixture->bio.bi_swapz_ci_sideband;
	KUNIT_ASSERT_NOT_NULL(test, owner);
	owner->source_swap_entry = 0;
	swapz_round034_v1_expect_refusal(test, &fixture->bio, 128U, -ESTALE);
	owner->source_swap_entry = 0x123456U;
	owner->slot_epoch = 0;
	swapz_round034_v1_expect_refusal(test, &fixture->bio, 128U, -ESTALE);
	owner->slot_epoch = 11;
	owner->source_identity = 0;
	swapz_round034_v1_expect_refusal(test, &fixture->bio, 128U, -ESTALE);
	owner->source_identity = 13;
	owner->codec = 2; /* ZSTD/dictionary cannot be represented as codec1. */
	swapz_round034_v1_expect_refusal(test, &fixture->bio, 128U, -ESTALE);
	owner->codec = 1;
	owner->representation_version = 2;
	swapz_round034_v1_expect_refusal(test, &fixture->bio, 128U, -ESTALE);
	owner->representation_version = 1;
	owner->compressed_length = 0;
	swapz_round034_v1_expect_refusal(test, &fixture->bio, 128U, -ESTALE);
	owner->compressed_length = 3569;
	swapz_round034_v1_expect_refusal(test, &fixture->bio, 128U, -ESTALE);
	owner->compressed_length = (u16)fixture->compressed_length;
	owner->compressed_crc32c ^= 1U;
	swapz_round034_v1_expect_refusal(test, &fixture->bio, 128U, -ESTALE);
	owner->compressed_crc32c ^= 1U;
	memset(owner->original_sha256, 0, sizeof(owner->original_sha256));
	swapz_round034_v1_expect_refusal(test, &fixture->bio, 128U, -ESTALE);
}

static void swapz_round034_v1_constructor_reject_kunit(struct kunit *test)
{
	struct swapz_round034_v1_fixture *fixture =
		swapz_round034_v1_fixture_create(test);
	struct swapz_ci_owned_payload *owner;
	u8 absent_sha[32] = {};
	u32 checksum;

	KUNIT_ASSERT_NOT_NULL(test, fixture);
	checksum = ~crc32c(~0U, fixture->compressed,
			    fixture->compressed_length);
#define SWAPZ_ROUND034_BAD(source, capacity, length, digest, epoch, identity, slot, version, codec, crc) \
	KUNIT_EXPECT_PTR_EQ(test, swapz_ci_owned_create_source_v1( \
		source, capacity, length, digest, epoch, identity, slot, \
		version, codec, crc, GFP_KERNEL), NULL)
	SWAPZ_ROUND034_BAD(fixture->compressed, fixture->compressed_length,
			   fixture->compressed_length, fixture->digest,
			   11, 13, 0, 1, 1, checksum);
	SWAPZ_ROUND034_BAD(fixture->compressed, fixture->compressed_length,
			   fixture->compressed_length, fixture->digest,
			   0, 13, 0x123456, 1, 1, checksum);
	SWAPZ_ROUND034_BAD(fixture->compressed, fixture->compressed_length,
			   fixture->compressed_length, fixture->digest,
			   11, 0, 0x123456, 1, 1, checksum);
	SWAPZ_ROUND034_BAD(fixture->compressed, fixture->compressed_length,
			   0, fixture->digest, 11, 13, 0x123456, 1, 1, checksum);
	SWAPZ_ROUND034_BAD(fixture->compressed, fixture->compressed_length,
			   3569, fixture->digest, 11, 13, 0x123456, 1, 1, checksum);
	SWAPZ_ROUND034_BAD(fixture->compressed, fixture->compressed_length,
			   fixture->compressed_length, fixture->digest,
			   11, 13, 0x123456, 1, 2, checksum);
	SWAPZ_ROUND034_BAD(fixture->compressed, fixture->compressed_length,
			   fixture->compressed_length, absent_sha,
			   11, 13, 0x123456, 1, 1, checksum);
	SWAPZ_ROUND034_BAD(fixture->compressed, fixture->compressed_length,
			   fixture->compressed_length, fixture->digest,
			   11, 13, 0x123456, 1, 1, checksum ^ 1U);
#undef SWAPZ_ROUND034_BAD
	/* A valid BIO lifetime without any owner cannot be upgraded. */
	owner = fixture->bio.bi_swapz_ci_sideband;
	fixture->bio.bi_swapz_ci_sideband = NULL;
	swapz_round034_v1_expect_refusal(test, &fixture->bio, 128U, -ESTALE);
	fixture->bio.bi_swapz_ci_sideband = owner;
}

static void swapz_round034_v1_alias_kunit(struct kunit *test)
{
	struct swapz_round034_v1_fixture *fixture =
		swapz_round034_v1_fixture_create(test);
	struct swapz_ci_lz4_owned_view_v1 view;
	struct swapz_ci_owned_payload *owner;
	u8 *unchanged;
	int error;

	KUNIT_ASSERT_NOT_NULL(test, fixture);
	owner = fixture->bio.bi_swapz_ci_sideband;
	KUNIT_ASSERT_NOT_NULL(test, owner);
	unchanged = kunit_kmalloc(test, owner->compressed_length, GFP_KERNEL);
	KUNIT_ASSERT_NOT_NULL(test, unchanged);
	memcpy(unchanged, owner->compressed_bytes, owner->compressed_length);
	memset(&view, 0xa5, sizeof(view));
	error = swapz_ci_bio_snapshot_lz4_v1(
		&fixture->bio, &view, (u8 *)&view, sizeof(view));
	KUNIT_EXPECT_EQ(test, error, -EINVAL);
	KUNIT_EXPECT_PTR_EQ(test, memchr_inv(&view, 0xa5, sizeof(view)), NULL);
	error = swapz_ci_bio_snapshot_lz4_v1(
		&fixture->bio, &view, owner->compressed_bytes,
		owner->compressed_length);
	KUNIT_EXPECT_EQ(test, error, -EINVAL);
	KUNIT_EXPECT_PTR_EQ(test, memchr_inv(&view, 0xa5, sizeof(view)), NULL);
	KUNIT_EXPECT_EQ(test, memcmp(owner->compressed_bytes, unchanged,
				     owner->compressed_length), 0);
	swapz_round034_v1_expect_refusal(test, &fixture->bio,
					fixture->compressed_length - 1U,
					-ENOSPC);
}

static void swapz_round034_v1_lifetime_kunit(struct kunit *test)
{
	struct swapz_round034_v1_fixture *fixture =
		swapz_round034_v1_fixture_create(test);
	struct swapz_ci_lz4_owned_view_v1 view = {};
	struct swapz_ci_owned_payload *owner;
	struct bio clone = {};
	struct bio *split;
	int error;

	KUNIT_ASSERT_NOT_NULL(test, fixture);
	owner = fixture->bio.bi_swapz_ci_sideband;
	error = swapz_ci_bio_snapshot_lz4_v1(
		&fixture->bio, &view, fixture->destination, 3568U);
	KUNIT_ASSERT_EQ(test, error, 0);
	error = bio_init_clone(NULL, &clone, &fixture->bio, GFP_KERNEL);
	if (error) {
		KUNIT_FAIL(test, "real original v1 BIO clone failed");
		return;
	}
	KUNIT_EXPECT_EQ(test, refcount_read(&owner->references), 2);
#if defined(SWAPZ_ROUND043_ORIGINAL_BIO_CLONE_COPY_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && IS_ENABLED(CONFIG_KUNIT)
	/* Round034's historic refusal now checks an UNPROVEN clone marker;
	 * a separate new Round043 KUnit proves a genuinely owned full clone.
	 * Keep the one real acquired owner ref for ordinary cleanup below.
	 */
	clone.bi_swapz_ci_full_clone_owned = false;
#endif
	swapz_round034_v1_expect_refusal(test, &clone, 128U, -EOPNOTSUPP);
#if defined(SWAPZ_ROUND043_ORIGINAL_BIO_CLONE_COPY_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && IS_ENABLED(CONFIG_KUNIT)
	clone.bi_swapz_ci_full_clone_owned = true;
#endif
	bio_uninit(&fixture->bio); /* Clone retains its independent owner ref. */
	KUNIT_EXPECT_EQ(test, refcount_read(&owner->references), 1);
	KUNIT_EXPECT_EQ(test, view.source_swap_entry, (u64)0x123456U);
	KUNIT_EXPECT_EQ(test, LZ4_decompress_safe(
				(const char *)fixture->destination,
				(char *)fixture->decoded,
				view.compressed_length, PAGE_SIZE),
			(int)PAGE_SIZE);
	bio_uninit(&clone); /* Last owner reference, never use freed BIO. */
	/* Separate fresh source: original split must never yield 4096 snapshot. */
	fixture = swapz_round034_v1_fixture_create(test);
	KUNIT_ASSERT_NOT_NULL(test, fixture);
	fixture->bio.bi_vcnt = 1; /* Required only by the old split API. */
	split = bio_split(&fixture->bio, 4U, GFP_KERNEL, &fs_bio_set);
	if (IS_ERR_OR_NULL(split)) {
		KUNIT_FAIL(test, "real original v1 BIO split failed");
		return;
	}
	swapz_round034_v1_expect_refusal(test, split, 128U, -EOPNOTSUPP);
	swapz_round034_v1_expect_refusal(test, &fixture->bio, 128U,
					-EOPNOTSUPP);
	bio_put(split);
}
#endif /* Round034 real original v1 test-only, no loaded transport */
"""

ROUND034_KUNIT_CASES = r"""#if defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
	KUNIT_CASE(swapz_round034_v1_owned_copy_kunit),
	KUNIT_CASE(swapz_round034_v1_bio_reject_kunit),
	KUNIT_CASE(swapz_round034_v1_owner_reject_kunit),
	KUNIT_CASE(swapz_round034_v1_constructor_reject_kunit),
	KUNIT_CASE(swapz_round034_v1_alias_kunit),
	KUNIT_CASE(swapz_round034_v1_lifetime_kunit),
#endif
"""


def apply_round034_original_v1_kunit(path: str, composed: str) -> str:
    """Append new opt-in real block/bio.c tests, never edit old 11 tests."""
    if path != "block/bio.c":
        return composed
    composed = replace_once(
        composed, '#include "blk-cgroup.h"\n',
        '#include "blk-cgroup.h"\n' + ROUND034_KUNIT_HEADERS,
        path, "v1-real-kunit-kernel-headers")
    anchor = "static struct kunit_case swapz_ci_sideband_cases[] = {\n"
    return replace_once(
        composed, anchor,
        ROUND034_KUNIT_SOURCE + "\n" + anchor + ROUND034_KUNIT_CASES,
        path, "v1-real-kunit-cases")



# Round035: diagnostic-only original MM routing observation. This is NOT a
# public provenance ABI, a current DM authorization, or an actual zswap
# pressure eviction. All previous compiler-only gates and KUnit are required.
ROUND035_ROUTE_MACRO = "SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST"
ROUND035_ROUTE_FLAGS = (
    "SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST",
    "SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST",
    "SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY",
    "SWAPZ_ROUND031_MM_BIO_SOURCE",
    "SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE",
    "SWAPZ_ROUND028_SLOT_EPOCH_SOURCE",
    "SWAPZ_ROUND025_SIDEBAND_CI_ONLY",
)
ROUND035_ROUTE_CONDITION = " && ".join(
    "defined(" + name + ")" for name in ROUND035_ROUTE_FLAGS
) + " && IS_ENABLED(CONFIG_KUNIT)"

ROUND035_ROUTE_HEADER = r"""
#if defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
/*
 * Internal-only observation while the source BIO is still independently
 * owned. Not EXPORT_SYMBOL, not part of copied view v1, not a DM API.
 */
bool swapz_round035_bio_owner_matches(const struct bio *bio,
				     u64 source_entry, u64 source_epoch);
#endif
"""

ROUND035_ROUTE_CTX = r"""
#if defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
	/* The actual original zswap writeback callback sets this ONLY after
	 * a successfully sealed MM owner. A naked caller cannot create one.
	 * This stack-local route hint never enters a published record.
	 */
	swp_entry_t swapz_round035_original_slot;
	u64 swapz_round035_original_epoch;
#endif
"""

ROUND035_ROUTE_BIO = r"""
#if defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
/*
 * Original block/bio.c owns the payload ref under the source BIO lifetime.
 * A synchronous validated comparison is permitted, NOT a pointer escape.
 * Caller must already pin BIO until this function returns; no RCU lookup.
 * A source identity check is NOT a current backing-device authorization.
 */
bool swapz_round035_bio_owner_matches(const struct bio *bio,
				      u64 source_entry, u64 source_epoch)
{
	struct swapz_ci_owned_payload *owner;
	bool matches = false;

	if (!bio || !source_entry || !source_epoch)
		return false;
	owner = swapz_ci_owned_get(bio->bi_swapz_ci_sideband);
	if (!owner)
		return false;
	if (swapz_ci_owned_valid(owner) &&
	    owner->source_swap_entry == source_entry &&
	    owner->slot_epoch == source_epoch)
		matches = true;
	swapz_ci_owned_put(owner);
	return matches;
}
#endif /* Round035 internal original BIO identity only */
"""

ROUND035_ROUTE_MM = r"""
#if defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
/* ROUND035_ORIGINAL_MM_ROUTE_C_BEGIN */
#include <kunit/test.h>

/* Real original mm/swapfile.c allocator generation, not a guessed sector. */
extern u64 swapz_round028_slot_epoch(swp_entry_t source_slot);

/*
 * Identity is typed: a packed swp_entry_t.val is NOT a DM relative page.
 * The caller-supplied source token is not authority. Neither a different
 * type with equal offsets nor a reused old epoch can match the MM slot.
 */
static int swapz_round035_route_identity(swp_entry_t actual_folio_slot,
					 swp_entry_t source_store_slot,
					 u64 original_store_epoch,
					 u64 current_allocator_epoch)
{
	if (!actual_folio_slot.val || !source_store_slot.val ||
	    !original_store_epoch || !current_allocator_epoch ||
	    swp_type(actual_folio_slot) >= MAX_SWAPFILES ||
	    swp_type(source_store_slot) >= MAX_SWAPFILES ||
	    swp_type(actual_folio_slot) != swp_type(source_store_slot) ||
	    swp_offset(actual_folio_slot) != swp_offset(source_store_slot) ||
	    original_store_epoch != current_allocator_epoch)
		return -ESTALE;
	return 0;
}

/*
 * Source-side shape only. The expected device/sector are supplied by
 * get_swap_device() + swap_folio_sector() from ORIGINAL swap_info extents.
 * No linear swapfile offset math. Block 0 is a protected swap header.
 * Geometry accepted here never authorizes any downstream transfer.
 */
static int swapz_round035_route_geometry(const struct bio *bio,
					 const struct swap_info_struct *active,
					 sector_t actual_swap_sector)
{
	if (!bio || !active || !active->bdev ||
	    bio->bi_bdev != active->bdev)
		return -ESTALE;
	if (PAGE_SIZE != 4096U || bio_op(bio) != REQ_OP_WRITE ||
	    !(bio->bi_opf & REQ_SWAP) ||
	    bio->bi_iter.bi_size != 4096U || bio_sectors(bio) != 8U ||
	    bio->bi_iter.bi_idx || bio->bi_iter.bi_offset ||
	    bio->bi_vcnt || (bio->bi_flags & (1U << BIO_CLONED)) ||
	    !bio->bi_io_vec || !bio->bi_io_vec[0].bv_page ||
	    bio->bi_io_vec[0].bv_len != 4096U ||
	    bio->bi_io_vec[0].bv_offset)
		return -EOPNOTSUPP;
	if (!actual_swap_sector || (actual_swap_sector & 7U) ||
	    actual_swap_sector > (sector_t)-1 - 7U ||
	    bio->bi_iter.bi_sector != actual_swap_sector)
		return -ERANGE;
	return 0;
}

/*
 * Called at ACTUAL original swap_bdev_submit_write() just before normal
 * submit_bio. The original folio is already UNLOCKED by __swap_writeout();
 * PG_writeback keeps the folio in swapcache until write completion, but
 * the observation cannot pin a future DM lookup or prove swapfile type
 * activation over a later consumer lifetime. The active swap-device
 * percpu_ref below protects swapoff only DURING this synchronous call.
 *
 * Do not write any outputs, accept/complete any BIO or install authority.
 * Every path, including all mechanically valid inputs, refuses live routing.
 */
static int swapz_round035_mm_route_preflight(struct swap_io_ctx *ctx,
					    const struct bio *bio,
					    struct folio *folio)
{
	struct swap_info_struct *active;
	swp_entry_t original_slot;
	sector_t mapped_sector;
	u64 current_epoch;
	int result = -ESTALE;

	if (!ctx || !ctx->sis || !bio || !folio ||
	    !bio->bi_swapz_ci_sideband ||
	    !folio_test_swapcache(folio) || !folio_test_writeback(folio))
		return -ESTALE;
	original_slot = folio_swap_entry(folio, 0);
	/* Current slot epoch checks run under ORIGINAL swap-cluster lock. */
	current_epoch = swapz_round028_slot_epoch(original_slot);
	if (swapz_round035_route_identity(
		    original_slot, ctx->swapz_round035_original_slot,
		    ctx->swapz_round035_original_epoch, current_epoch))
		return -ESTALE;
	active = get_swap_device(original_slot);
	if (IS_ERR_OR_NULL(active))
		return -ESTALE;
	if (active != ctx->sis)
		goto put_active;

	/* Real original swap extent tree; can be nonlinear swapfile. */
	mapped_sector = swap_folio_sector(folio);
	if (swapz_round035_route_geometry(bio, active, mapped_sector) ||
	    !swapz_round035_bio_owner_matches(
		    bio, (u64)original_slot.val,
		    ctx->swapz_round035_original_epoch))
		goto put_active;
	/*
	 * Mechanical identity checks passed. NO active type-to-DM target
	 * mapping and no pinned allocation incarnation survives return.
	 * An original MM route witness is NOT transferable admission.
	 */
	result = -EOPNOTSUPP;
put_active:
	put_swap_device(active);
	return result;
}

/* Hostless original KUnit cases use synthetic scalars, never fake MM STORE. */
static void swapz_round035_route_type_kunit(struct kunit *test)
{
	swp_entry_t first = swp_entry(1U, 37U);
	swp_entry_t different_type = swp_entry(2U, 37U);
	swp_entry_t different_offset = swp_entry(1U, 38U);

	KUNIT_EXPECT_EQ(test, swapz_round035_route_identity(
				first, first, 11U, 11U), 0);
	KUNIT_EXPECT_EQ(test, swapz_round035_route_identity(
				first, different_type, 11U, 11U), -ESTALE);
	KUNIT_EXPECT_EQ(test, swapz_round035_route_identity(
				first, different_offset, 11U, 11U), -ESTALE);
	KUNIT_EXPECT_EQ(test, swapz_round035_route_identity(
				first, swp_entry(MAX_SWAPFILES, 37U),
				11U, 11U), -ESTALE);
}

static void swapz_round035_route_epoch_kunit(struct kunit *test)
{
	swp_entry_t slot = swp_entry(1U, 37U);
	swp_entry_t absent = {};

	KUNIT_EXPECT_EQ(test, swapz_round035_route_identity(
				slot, slot, 11U, 12U), -ESTALE);
	KUNIT_EXPECT_EQ(test, swapz_round035_route_identity(
				slot, slot, 0U, 11U), -ESTALE);
	KUNIT_EXPECT_EQ(test, swapz_round035_route_identity(
				slot, slot, 11U, 0U), -ESTALE);
	KUNIT_EXPECT_EQ(test, swapz_round035_route_identity(
				slot, absent, 11U, 11U), -ESTALE);
	KUNIT_EXPECT_EQ(test, swapz_round035_route_identity(
				absent, slot, 11U, 11U), -ESTALE);
}

/* Fake KUnit pointers are compared ONLY, never dereferenced as real bdev. */
static void swapz_round035_route_geometry_kunit(struct kunit *test)
{
	struct block_device *device_one;
	struct block_device *device_two;
	struct swap_info_struct *area;
	struct bio *bio;
	struct bio_vec *vector;
	struct page *page;

	area = kunit_kzalloc(test, sizeof(*area), GFP_KERNEL);
	bio = kunit_kzalloc(test, sizeof(*bio), GFP_KERNEL);
	vector = kunit_kzalloc(test, sizeof(*vector), GFP_KERNEL);
	device_one = kunit_kzalloc(test, sizeof(*device_one), GFP_KERNEL);
	device_two = kunit_kzalloc(test, sizeof(*device_two), GFP_KERNEL);
	page = alloc_page(GFP_KERNEL);
	if (!area || !bio || !vector || !device_one || !device_two || !page) {
		KUNIT_FAIL(test, "bounded route fixture allocation unavailable");
		if (page)
			__free_page(page);
		return;
	}
	area->bdev = device_one;
	bio->bi_bdev = device_one;
	bio->bi_io_vec = vector;
	bio->bi_opf = REQ_OP_WRITE | REQ_SWAP;
	bio->bi_iter.bi_size = PAGE_SIZE;
	bio->bi_iter.bi_sector = 8U;
	vector->bv_page = page;
	vector->bv_len = PAGE_SIZE;
	KUNIT_EXPECT_EQ(test, swapz_round035_route_geometry(
				bio, area, 8U), 0);
	/* The same offset on a DIFFERENT backing device is never proof. */
	bio->bi_bdev = device_two;
	KUNIT_EXPECT_EQ(test, swapz_round035_route_geometry(
				bio, area, 8U), -ESTALE);
	bio->bi_bdev = device_one;
	KUNIT_EXPECT_EQ(test, swapz_round035_route_geometry(
				bio, area, 0U), -ERANGE);
	KUNIT_EXPECT_EQ(test, swapz_round035_route_geometry(
				bio, area, 9U), -ERANGE);
	KUNIT_EXPECT_EQ(test, swapz_round035_route_geometry(
				bio, area, (sector_t)-1), -ERANGE);
	KUNIT_EXPECT_EQ(test, swapz_round035_route_geometry(
				bio, area, 16U), -ERANGE);
	bio->bi_iter.bi_sector = 16U;
	KUNIT_EXPECT_EQ(test, swapz_round035_route_geometry(
				bio, area, 16U), 0);
	bio->bi_iter.bi_size = 2048U;
	KUNIT_EXPECT_EQ(test, swapz_round035_route_geometry(
				bio, area, 16U), -EOPNOTSUPP);
	bio->bi_iter.bi_size = 4096U;
	bio->bi_vcnt = 1;
	KUNIT_EXPECT_EQ(test, swapz_round035_route_geometry(
				bio, area, 16U), -EOPNOTSUPP);
	bio->bi_vcnt = 0;
	bio->bi_opf = REQ_OP_READ | REQ_SWAP;
	KUNIT_EXPECT_EQ(test, swapz_round035_route_geometry(
				bio, area, 16U), -EOPNOTSUPP);
	__free_page(page);
}

static void swapz_round035_route_no_authority_kunit(struct kunit *test)
{
	struct swap_io_ctx context = {};
	struct bio source_bio = {};
	/* No fabricated active swap_info/bdev/epoch can be accepted. */
	KUNIT_EXPECT_EQ(test, swapz_round035_mm_route_preflight(
				NULL, &source_bio, NULL), -ESTALE);
	KUNIT_EXPECT_EQ(test, swapz_round035_mm_route_preflight(
				&context, &source_bio, NULL), -ESTALE);
	KUNIT_EXPECT_EQ(test, swapz_round035_mm_route_preflight(
				&context, NULL, NULL), -ESTALE);
}

static struct kunit_case swapz_round035_route_cases[] = {
	KUNIT_CASE(swapz_round035_route_type_kunit),
	KUNIT_CASE(swapz_round035_route_epoch_kunit),
	KUNIT_CASE(swapz_round035_route_geometry_kunit),
	KUNIT_CASE(swapz_round035_route_no_authority_kunit),
	{}
};

static struct kunit_suite swapz_round035_route_suite = {
	.name = "swapz_round035_original_mm_route_no_authority",
	.test_cases = swapz_round035_route_cases,
};
kunit_test_suite(swapz_round035_route_suite);
/* ROUND035_ORIGINAL_MM_ROUTE_C_END */
#endif /* original MM route diagnostic KUnit only, live admission OFF */
"""

ROUND035_ROUTE_HOOK = r"""
#if defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
	/* Probe ACTUAL upstream MM's bdev/extent/epoch at original dispatch.
	 * Failure or success never changes decompressed 4096-byte WRITE.
	 * No logging, allocation, authority publication or extra completion.
	 */
	if (bio->bi_swapz_ci_sideband)
		(void)swapz_round035_mm_route_preflight(
			ctx, bio, bio_first_folio_all(bio));
#endif
"""

ROUND035_ZSWAP_HINT = r"""
#if defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
	/* Generated from a real original MM STORE, not caller-supplied:
	 * the original zswap-entry lifetime is still pinned here.
	 */
	if (ctx.swapz_round031_owned) {
		ctx.swapz_round035_original_slot = swpentry;
		ctx.swapz_round035_original_epoch =
			entry->swapz_round028_allocation_epoch;
	}
#endif
"""


def apply_round035_original_route(path: str, composed: str) -> str:
    """Guard all new original-C checks, fail if any source anchor moves."""
    if path == "include/linux/bio.h":
        return replace_once(
            composed,
            "struct swapz_ci_lz4_owned_view_v1 {",
            ROUND035_ROUTE_HEADER + "\nstruct swapz_ci_lz4_owned_view_v1 {",
            path, "round035-internal-bio-owner-api")
    if path == "include/linux/swap_ops.h":
        return replace_once(
            composed, "struct swap_io_ctx {\n",
            "struct swap_io_ctx {\n" + ROUND035_ROUTE_CTX,
            path, "round035-private-original-io-hint")
    if path == "block/bio.c":
        anchor = "static struct kunit_case swapz_ci_sideband_cases[] = {\n"
        return replace_once(
            composed, anchor,
            ROUND035_ROUTE_BIO + "\n" + anchor,
            path, "round035-sealed-owner-identity")
    if path == "mm/page_io.c":
        anchor = "static void swap_bdev_submit_write(struct swap_io_ctx *ctx)\n"
        composed = replace_once(
            composed, anchor, ROUND035_ROUTE_MM + "\n" + anchor,
            path, "round035-actual-mm-route-test-source")
        insertion = ("\t\tbio->bi_swapz_ci_sideband = ctx->swapz_round031_owned;\n"
                     "\t\tctx->swapz_round031_owned = NULL;\n"
                     "\t}\n#endif\n"
                     "\tbio->bi_iter.bi_sector = swap_folio_sector(bio_first_folio_all(bio));\n")
        return replace_once(
            composed, insertion, insertion + ROUND035_ROUTE_HOOK,
            path, "round035-actual-mm-bdev-extent-observe")
    if path == "mm/zswap.c":
        anchor = """	ctx.swapz_round031_owned =
		swapz_round031_mm_bio_create(entry, swpentry, tree, offset);
#endif"""
        if composed.count(anchor) != 1:
            raise SourceCompositionError("COMPOSE_CONFLICT:mm/zswap.c:route-owner")
        return composed.replace(anchor,
            """	ctx.swapz_round031_owned =
		swapz_round031_mm_bio_create(entry, swpentry, tree, offset);
""" + ROUND035_ZSWAP_HINT + "#endif", 1)
    return composed



# Round036: real original C source-lifetime audit, not a live route lease.
# All older original MM/BIO gates plus CONFIG_KUNIT remain mandatory.
ROUND036_LIFETIME_MACRO = "SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST"
ROUND036_LIFETIME_FLAGS = (
    ROUND036_LIFETIME_MACRO,
    "SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST",
    "SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST",
    "SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY",
    "SWAPZ_ROUND031_MM_BIO_SOURCE",
    "SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE",
    "SWAPZ_ROUND028_SLOT_EPOCH_SOURCE",
    "SWAPZ_ROUND025_SIDEBAND_CI_ONLY",
)

ROUND036_LIFETIME_C = r"""
#if defined(SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
/* ROUND036_ORIGINAL_MM_LIFETIME_C_BEGIN */
/*
 * Values only: no borrowed swap_info, BIO, folio, zpool or mapper references
 * escape this source file or outlive the synchronous comparison. Device
 * pointers below are compared while the caller's actual swap-area percpu
 * reference remains held; retaining these values DOES NOT retain a device.
 * The original swap allocation epoch lookup holds its cluster lock only
 * during that lookup, and can change immediately after this observation.
 */
struct swapz_round036_route_lifetime {
	swp_entry_t source_slot;
	u64 allocation_epoch;
	u64 stored_identity;
	struct block_device *source_bdev;
	struct block_device *target_bdev;
	sector_t source_sector;
	u64 target_generation;
	u64 extent_generation;
	bool original_folio_unlocked;
	bool writeback_in_flight;
	bool original_bio_live;
	bool original_owner_live;
};

/*
 * Real original mm/page_io.c data path is BIO initialized with ONE bvec,
 * bi_vcnt=0, full 4096 WRITE|REQ_SWAP, then async end_swap_bio_write()
 * calls bio_uninit() and swap_write_end() before freeing the swap_iocb.
 * This helper sees NO ownership after a parent BIO is released and does
 * not assume clone/split inherits a source allocator incarnation.
 *
 * Even if caller supplies fictitious true booleans for all three leases,
 * never grant authority: the actual original MM supplies NO combined
 * original slot-epoch pin, current active DM target map-generation pin
 * and GC ref-fenced authority transferable into a later DM map callback.
 */
static int swapz_round036_route_lifetime_check(
		const struct swapz_round036_route_lifetime *original,
		const struct swapz_round036_route_lifetime *consumer,
		const struct bio *source_bio,
		bool swaparea_ref_pinned_through_consumer,
		bool allocation_ref_pinned_through_consumer,
		bool dm_mapping_ref_pinned_through_consumer)
{
	if (!original || !consumer || !source_bio)
		return -EINVAL;
	if (!original->source_slot.val || !consumer->source_slot.val ||
	    swp_type(original->source_slot) >= MAX_SWAPFILES ||
	    swp_type(consumer->source_slot) >= MAX_SWAPFILES ||
	    !original->allocation_epoch || !consumer->allocation_epoch ||
	    !original->stored_identity || !consumer->stored_identity ||
	    !original->source_bdev || !consumer->source_bdev ||
	    !original->original_folio_unlocked ||
	    !consumer->original_folio_unlocked ||
	    !original->writeback_in_flight || !consumer->writeback_in_flight ||
	    !original->original_bio_live || !consumer->original_bio_live ||
	    !original->original_owner_live || !consumer->original_owner_live)
		return -ESTALE;
	if (original->source_slot.val != consumer->source_slot.val ||
	    original->allocation_epoch != consumer->allocation_epoch ||
	    original->stored_identity != consumer->stored_identity ||
	    original->source_bdev != consumer->source_bdev ||
	    original->target_bdev != consumer->target_bdev ||
	    original->target_generation != consumer->target_generation ||
	    original->extent_generation != consumer->extent_generation)
		return -ESTALE;
	/* The original swapfile mapping may NOT be offset * eight sectors. */
	if (!original->source_sector ||
	    (original->source_sector & 7U) ||
	    original->source_sector > (sector_t)-1 - 7U ||
	    !consumer->source_sector ||
	    (consumer->source_sector & 7U) ||
	    consumer->source_sector > (sector_t)-1 - 7U)
		return -ERANGE;
	if (original->source_sector != consumer->source_sector ||
	    source_bio->bi_bdev != consumer->source_bdev ||
	    source_bio->bi_iter.bi_sector != consumer->source_sector)
		return -ESTALE;
	if (PAGE_SIZE != 4096U || bio_op(source_bio) != REQ_OP_WRITE ||
	    !(source_bio->bi_opf & REQ_SWAP) ||
	    source_bio->bi_iter.bi_size != 4096U ||
	    bio_sectors(source_bio) != 8U ||
	    source_bio->bi_iter.bi_idx ||
	    source_bio->bi_iter.bi_offset ||
	    source_bio->bi_vcnt ||
	    (source_bio->bi_flags & (1U << BIO_CLONED)) ||
	    !source_bio->bi_io_vec ||
	    !source_bio->bi_io_vec[0].bv_page ||
	    source_bio->bi_io_vec[0].bv_len != 4096U ||
	    source_bio->bi_io_vec[0].bv_offset)
		return -EOPNOTSUPP;

	/* Both original swap area and allocator-epoch references are only
	 * transient; the active DM target/GC generation ref is also absent.
	 * The observed source BIO owner is independent but cannot make
	 * mutable MM source/target routing durable across asynchronous I/O.
	 */
	if (!swaparea_ref_pinned_through_consumer ||
	    !allocation_ref_pinned_through_consumer ||
	    !dm_mapping_ref_pinned_through_consumer)
		return -EOPNOTSUPP;
	return -EOPNOTSUPP; /* NO AUTHORITY even for fabricated lease booleans. */
}

/*
 * Called at the ACTUAL original swap_bdev_submit_write() immediately before
 * normal submit_bio. No return value affects the original decompressed WRITE.
 * get_swap_device()/put_swap_device() only fences swapoff in this scope.
 * The folio was UNLOCKED by __swap_writeout, and folio_end_writeback()
 * eventually allows the swapcache ref to be removed. No slot reference is
 * captured through clone/split/reissue or a later DM callback.
 */
static int swapz_round036_original_lifetime_probe(
		struct swap_io_ctx *ctx, const struct bio *source_bio,
		struct folio *folio)
{
	struct swap_info_struct *active;
	struct swapz_round036_route_lifetime initial = {};
	struct swapz_round036_route_lifetime consumer_sample = {};
	swp_entry_t original_slot;
	u64 allocator_epoch;
	sector_t original_sector;
	int result = -ESTALE;

	if (!ctx || !ctx->sis || !source_bio || !folio ||
	    !source_bio->bi_swapz_ci_sideband ||
	    !folio_test_swapcache(folio) ||
	    !folio_test_writeback(folio) ||
	    folio_test_locked(folio))
		return -ESTALE;

	original_slot = folio_swap_entry(folio, 0);
	allocator_epoch = swapz_round028_slot_epoch(original_slot);
	if (swapz_round035_route_identity(
		    original_slot, ctx->swapz_round035_original_slot,
		    ctx->swapz_round035_original_epoch, allocator_epoch))
		return -ESTALE;

	active = get_swap_device(original_slot);
	if (IS_ERR_OR_NULL(active))
		return -ESTALE;
	if (active != ctx->sis)
		goto release_area;

	original_sector = swap_folio_sector(folio);
	if (swapz_round035_route_geometry(source_bio, active,
					   original_sector) ||
	    !swapz_round035_bio_owner_matches(source_bio,
			(u64)original_slot.val, allocator_epoch))
		goto release_area;

	initial.source_slot = original_slot;
	initial.allocation_epoch = allocator_epoch;
	initial.stored_identity = 1; /* Local existence only, never exported. */
	initial.source_bdev = active->bdev;
	initial.source_sector = original_sector;
	initial.original_folio_unlocked = true;
	initial.writeback_in_flight = true;
	initial.original_bio_live = true;
	initial.original_owner_live = true;
	consumer_sample = initial;
	/*
	 * No actual MM→DM target identity or GC generation can be read here.
	 * The transient area ref is held now, NOT at a later consumer.
	 * A second local snapshot cannot lease the slot across future ABA.
	 */
	result = swapz_round036_route_lifetime_check(
		&initial, &consumer_sample, source_bio, false, false, false);
release_area:
	put_swap_device(active);
	return result;
}

struct swapz_round036_route_fixture {
	struct swapz_round036_route_lifetime initial;
	struct swapz_round036_route_lifetime consumer;
	struct bio bio;
	struct bio_vec vector;
	struct page page;
	struct block_device *device;
};

static bool swapz_round036_fixture_init(struct kunit *test,
					struct swapz_round036_route_fixture *fixture)
{
	struct swapz_round036_route_lifetime *initial = &fixture->initial;

	fixture->device = kunit_kzalloc(test, sizeof(*fixture->device),
				       GFP_KERNEL);
	if (!fixture->device) {
		KUNIT_FAIL(test, "Round036 source-only device identity fixture");
		return false;
	}
	initial->source_slot = swp_entry(1U, 37U);
	initial->allocation_epoch = 17U;
	initial->stored_identity = 27U;
	initial->source_bdev = fixture->device;
	initial->source_sector = 4096U; /* Nonlinear: 37 * 8 is 296. */
	initial->target_generation = 31U;
	initial->extent_generation = 41U;
	initial->original_folio_unlocked = true;
	initial->writeback_in_flight = true;
	initial->original_bio_live = true;
	initial->original_owner_live = true;
	fixture->consumer = *initial;
	fixture->bio.bi_bdev = fixture->device;
	fixture->bio.bi_opf = REQ_OP_WRITE | REQ_SWAP;
	fixture->bio.bi_iter.bi_sector = 4096U;
	fixture->bio.bi_iter.bi_size = 4096U;
	fixture->bio.bi_io_vec = &fixture->vector;
	fixture->vector.bv_page = &fixture->page;
	fixture->vector.bv_len = 4096U;
	return true;
}

static int swapz_round036_fixture_check(
		const struct swapz_round036_route_fixture *fixture,
		bool area_lease, bool slot_lease, bool dm_lease)
{
	return swapz_round036_route_lifetime_check(
		&fixture->initial, &fixture->consumer, &fixture->bio,
		area_lease, slot_lease, dm_lease);
}

static void swapz_round036_slot_epoch_aba_kunit(struct kunit *test)
{
	struct swapz_round036_route_fixture fixture = {};

	if (!swapz_round036_fixture_init(test, &fixture))
		return;
	fixture.consumer.allocation_epoch++;
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, true, true), -ESTALE);
	fixture.consumer = fixture.initial;
	fixture.consumer.source_slot = swp_entry(2U, 37U);
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, true, true), -ESTALE);
	fixture.consumer = fixture.initial;
	fixture.consumer.stored_identity++;
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, true, true), -ESTALE);
}

static void swapz_round036_swapoff_area_reuse_kunit(struct kunit *test)
{
	struct swapz_round036_route_fixture fixture = {};
	struct block_device *new_area;

	if (!swapz_round036_fixture_init(test, &fixture))
		return;
	new_area = kunit_kzalloc(test, sizeof(*new_area), GFP_KERNEL);
	KUNIT_ASSERT_NOT_NULL(test, new_area);
	fixture.consumer.source_bdev = new_area; /* Same slot/new swapon. */
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, true, true), -ESTALE);
	fixture.consumer = fixture.initial;
	fixture.consumer.original_bio_live = false; /* Async parent freed. */
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, true, true), -ESTALE);
	fixture.consumer = fixture.initial;
	fixture.consumer.original_owner_live = false;
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, true, true), -ESTALE);
}

static void swapz_round036_nonlinear_sector_kunit(struct kunit *test)
{
	struct swapz_round036_route_fixture fixture = {};

	if (!swapz_round036_fixture_init(test, &fixture))
		return;
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, true, true), -EOPNOTSUPP);
	fixture.consumer.source_sector = 37U * 8U; /* Invalid guess. */
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, true, true), -ESTALE);
	fixture.consumer.source_sector = 0U; /* SWAPSPACE2 header. */
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, true, true), -ERANGE);
	fixture.consumer.source_sector = (sector_t)-1;
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, true, true), -ERANGE);
	fixture.consumer.source_sector = 9U;
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, true, true), -ERANGE);
}

static void swapz_round036_target_gc_race_kunit(struct kunit *test)
{
	struct swapz_round036_route_fixture fixture = {};
	struct block_device *new_mapper;

	if (!swapz_round036_fixture_init(test, &fixture))
		return;
	new_mapper = kunit_kzalloc(test, sizeof(*new_mapper), GFP_KERNEL);
	KUNIT_ASSERT_NOT_NULL(test, new_mapper);
	fixture.consumer.target_bdev = new_mapper;
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, true, true), -ESTALE);
	fixture.consumer = fixture.initial;
	fixture.consumer.target_generation++;
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, true, true), -ESTALE);
	fixture.consumer = fixture.initial;
	fixture.consumer.extent_generation++;
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, true, true), -ESTALE);
}

static void swapz_round036_bio_clone_split_unlock_kunit(struct kunit *test)
{
	struct swapz_round036_route_fixture fixture = {};

	if (!swapz_round036_fixture_init(test, &fixture))
		return;
	fixture.bio.bi_flags |= (1U << BIO_CLONED);
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, true, true), -EOPNOTSUPP);
	fixture.bio.bi_flags = 0;
	fixture.bio.bi_iter.bi_size = 2048U;
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, true, true), -EOPNOTSUPP);
	fixture.bio.bi_iter.bi_size = 4096U;
	fixture.bio.bi_vcnt = 1; /* Original must have prepopulated 0. */
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, true, true), -EOPNOTSUPP);
	fixture.bio.bi_vcnt = 0;
	fixture.bio.bi_opf = REQ_OP_READ | REQ_SWAP;
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, true, true), -EOPNOTSUPP);
	fixture.bio.bi_opf = REQ_OP_WRITE | REQ_SWAP;
	fixture.consumer.original_folio_unlocked = false;
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, true, true), -ESTALE);
	fixture.consumer.original_folio_unlocked = true;
	fixture.consumer.writeback_in_flight = false;
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, true, true), -ESTALE);
}

static void swapz_round036_no_lease_double_release_kunit(struct kunit *test)
{
	struct swapz_round036_route_fixture fixture = {};
	struct swapz_round036_route_lifetime previous;

	if (!swapz_round036_fixture_init(test, &fixture))
		return;
	previous = fixture.consumer;
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, false, false, false), -EOPNOTSUPP);
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, false, true), -EOPNOTSUPP);
	/* A fabricated positive lease cannot grant consumer authority. */
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, true, true), -EOPNOTSUPP);
	KUNIT_EXPECT_EQ(test, swapz_round036_route_lifetime_check(
				&fixture.initial, &fixture.consumer, NULL,
				true, true, true), -EINVAL);
	/* No mutation or release of input owner, BIO, GC or map state. */
	KUNIT_EXPECT_EQ(test, memcmp(&previous, &fixture.consumer,
				     sizeof(previous)), 0);
	KUNIT_EXPECT_EQ(test, swapz_round036_fixture_check(
				&fixture, true, true, true), -EOPNOTSUPP);
}

static struct kunit_case swapz_round036_lifetime_cases[] = {
	KUNIT_CASE(swapz_round036_slot_epoch_aba_kunit),
	KUNIT_CASE(swapz_round036_swapoff_area_reuse_kunit),
	KUNIT_CASE(swapz_round036_nonlinear_sector_kunit),
	KUNIT_CASE(swapz_round036_target_gc_race_kunit),
	KUNIT_CASE(swapz_round036_bio_clone_split_unlock_kunit),
	KUNIT_CASE(swapz_round036_no_lease_double_release_kunit),
	{}
};

static struct kunit_suite swapz_round036_lifetime_suite = {
	.name = "swapz_round036_original_mm_route_lifetime_no_authority",
	.test_cases = swapz_round036_lifetime_cases,
};
kunit_test_suite(swapz_round036_lifetime_suite);
/* ROUND036_ORIGINAL_MM_LIFETIME_C_END */
#endif /* Round036 original MM source-only ref/lifetime KUnit; no admission */
"""

ROUND036_LIFETIME_HOOK = r"""
#if defined(SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
	/* Read-only actual original MM→BIO handoff; no new IO or auth ref. */
	if (bio->bi_swapz_ci_sideband)
		(void)swapz_round036_original_lifetime_probe(
			ctx, bio, bio_first_folio_all(bio));
#endif
"""


def apply_round036_original_lifetime(path: str, composed: str) -> str:
    """Add original-only CI C helper and true MM dispatch hook fail-closed."""
    if path != "mm/page_io.c":
        return composed
    original_handler = "static void swap_bdev_submit_write(struct swap_io_ctx *ctx)\n"
    composed = replace_once(
        composed, original_handler, ROUND036_LIFETIME_C + "\n" + original_handler,
        path, "round036-original-mm-lifetime-kunit")
    return replace_once(
        composed, ROUND035_ROUTE_HOOK,
        ROUND035_ROUTE_HOOK + ROUND036_LIFETIME_HOOK,
        path, "round036-actual-original-mm-dispatch")



# Round037: original MM's actual get_swap_device lifetime is scoped, not
# transferable across async BIO / allocator ABA / target GC. CI only.
ROUND037_MM_OWNER_MACRO = "SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST"
ROUND037_MM_OWNER_FLAGS = (ROUND037_MM_OWNER_MACRO,) + ROUND036_LIFETIME_FLAGS
ROUND037_MM_OWNER_C = r"""
#if defined(SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST) && \
    defined(SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
/* ROUND037_MM_SCOPED_OWNER_BEGIN */
/*
 * Scope boundary: the only real area reference is acquired by original
 * get_swap_device() below, after the original folio has been unlocked and
 * before submit_bio(). No pointer, owner ref, or token escapes this function.
 * A swap-area users percpu_ref fences swapoff only while actually held; it
 * does not pin an allocated slot's incarnation, a later BIO clone/split or
 * any DM target/extent/GC generation. Both cluster-locked allocator-epoch
 * reads are momentary and do not convert this scope to an async lease.
 */
struct swapz_round037_mm_owner_scope {
	swp_entry_t original_slot;
	u64 initial_epoch;
	u64 final_epoch;
	struct swap_info_struct *active_area;
	struct block_device *source_device;
	sector_t original_sector;
	bool area_ref_held;
	bool source_bio_live;
	bool owner_live;
	bool folio_unlocked;
};

/* ROUND037_MM_SCOPED_HELPERS_BEGIN */
/*
 * Detach one genuinely acquired ORIGINAL get_swap_device() reference.
 * Transfer only to the local synchronous cleanup site for exactly one put.
 * KUnit may exercise detach with an unreferenced fake area, but MUST NOT
 * call put_swap_device() on such fake state.
 */
static struct swap_info_struct *swapz_round037_mm_scope_detach(
		struct swapz_round037_mm_owner_scope *scope)
{
	struct swap_info_struct *active_area;

	if (!scope || !scope->area_ref_held)
		return NULL;
	active_area = scope->active_area;
	scope->active_area = NULL;
	scope->area_ref_held = false;
	return active_area;
}

/*
 * Evaluates ORIGINAL source-owned observations only while the real area
 * ref and the original source BIO are held by this synchronous caller.
 * Consumer arguments are negative-test stimuli, never signed authority.
 * Even forged positive lease booleans cannot make this return success:
 * neither the current allocation epoch nor the downstream DM map/GC target
 * can be atomically ref-pinned through source BIO async completion here.
 */
static int swapz_round037_mm_scope_check(
		const struct swapz_round037_mm_owner_scope *scope,
		const struct bio *source_bio, swp_entry_t consumer_slot,
		u64 consumer_epoch, struct swap_info_struct *consumer_area,
		sector_t consumer_sector, bool genuine_source_owner,
		bool async_allocation_lease, bool dm_target_gc_lease)
{
	if (!scope || !source_bio || !consumer_area)
		return -EINVAL;
	if (!scope->area_ref_held || !scope->active_area ||
	    !scope->source_device || !scope->original_slot.val ||
	    !scope->initial_epoch || !scope->final_epoch ||
	    !scope->source_bio_live || !scope->owner_live ||
	    !scope->folio_unlocked || !consumer_epoch ||
	    swp_type(scope->original_slot) >= MAX_SWAPFILES ||
	    swp_type(consumer_slot) >= MAX_SWAPFILES)
		return -ESTALE;
	if (!scope->original_sector || (scope->original_sector & 7U) ||
	    scope->original_sector > (sector_t)-1 - 7U ||
	    !consumer_sector || (consumer_sector & 7U) ||
	    consumer_sector > (sector_t)-1 - 7U)
		return -ERANGE;
	if (scope->original_slot.val != consumer_slot.val ||
	    scope->initial_epoch != scope->final_epoch ||
	    scope->final_epoch != consumer_epoch ||
	    scope->active_area != consumer_area ||
	    scope->active_area->bdev != scope->source_device ||
	    scope->original_sector != consumer_sector ||
	    source_bio->bi_bdev != scope->source_device ||
	    source_bio->bi_iter.bi_sector != consumer_sector)
		return -ESTALE;
	/* This real original MM BIO has one prepopulated vector: bi_vcnt=0. */
	if (PAGE_SIZE != 4096U || bio_op(source_bio) != REQ_OP_WRITE ||
	    !(source_bio->bi_opf & REQ_SWAP) ||
	    source_bio->bi_iter.bi_size != 4096U ||
	    bio_sectors(source_bio) != 8U ||
	    source_bio->bi_iter.bi_idx || source_bio->bi_iter.bi_offset ||
	    source_bio->bi_vcnt ||
	    (source_bio->bi_flags & (1U << BIO_CLONED)) ||
	    !source_bio->bi_io_vec || !source_bio->bi_io_vec[0].bv_page ||
	    source_bio->bi_io_vec[0].bv_len != 4096U ||
	    source_bio->bi_io_vec[0].bv_offset)
		return -EOPNOTSUPP;
	if (!genuine_source_owner)
		return -ESTALE;
	if (!async_allocation_lease || !dm_target_gc_lease)
		return -EOPNOTSUPP;
	return -EOPNOTSUPP; /* Fabricated leases are never real authority. */
}
/* ROUND037_MM_SCOPED_HELPERS_END */

/*
 * ACTUAL original mm/page_io.c REQ_SWAP WRITE BIO dispatch boundary.
 * Original folio unlock already happened in __swap_writeout(). Acquire the
 * real active-area ref BEFORE the first allocator read, compare the true
 * nonlinear source swapfile sector and source-sealed BIO owner, read epoch
 * again, then close the ref exactly once BEFORE later asynchronous submit.
 * Even two matching epochs can suffer ABA after the cluster lock releases.
 */
static noinline int swapz_round037_original_mm_scoped_probe(
		struct swap_io_ctx *ctx, const struct bio *source_bio,
		struct folio *folio)
{
	struct swapz_round037_mm_owner_scope scope = {};
	struct swap_info_struct *active_area;
	swp_entry_t original_slot;
	bool genuine_owner;
	int result = -ESTALE;

	if (!ctx || !ctx->sis || !source_bio || !folio ||
	    !source_bio->bi_swapz_ci_sideband ||
	    !folio_test_swapcache(folio) ||
	    !folio_test_writeback(folio) || folio_test_locked(folio))
		return -ESTALE;

	original_slot = folio_swap_entry(folio, 0);
	active_area = get_swap_device(original_slot);
	if (IS_ERR_OR_NULL(active_area))
		return -ESTALE;

	scope.active_area = active_area;
	scope.area_ref_held = true;
	if (active_area != ctx->sis)
		goto release_area;
	scope.original_slot = original_slot;
	scope.initial_epoch = swapz_round028_slot_epoch(original_slot);
	if (swapz_round035_route_identity(
		    original_slot, ctx->swapz_round035_original_slot,
		    ctx->swapz_round035_original_epoch, scope.initial_epoch))
		goto release_area;

	scope.source_device = active_area->bdev;
	scope.original_sector = swap_folio_sector(folio);
	scope.source_bio_live = true; /* Caller owns BIO until submit_bio. */
	scope.owner_live = true; /* Independently refcounted sealed owner. */
	scope.folio_unlocked = true;
	genuine_owner = swapz_round035_bio_owner_matches(
		source_bio, (u64)original_slot.val, scope.initial_epoch);
	scope.final_epoch = swapz_round028_slot_epoch(original_slot);
	/*
	 * No current slot-incarnation lease and no exact downstream DM
	 * target/GC lease exist; the only current area ref is released below.
	 * A source BIO clone never inherits these scoped privileges.
	 */
	result = swapz_round037_mm_scope_check(
		&scope, source_bio, original_slot, scope.final_epoch,
		active_area, scope.original_sector, genuine_owner, false, false);
release_area:
	active_area = swapz_round037_mm_scope_detach(&scope);
	if (active_area)
		put_swap_device(active_area);
	return result;
}

/* All KUnit area/device objects below are synthetic, never swap-activated. */
struct swapz_round037_mm_fixture {
	struct swapz_round037_mm_owner_scope scope;
	struct swap_info_struct *area;
	struct block_device *device;
	struct bio bio;
	struct bio_vec vector;
	struct page *page;
};

static bool swapz_round037_mm_fixture_init(
		struct kunit *test, struct swapz_round037_mm_fixture *fixture)
{
	fixture->area = kunit_kzalloc(test, sizeof(*fixture->area), GFP_KERNEL);
	fixture->device = kunit_kzalloc(test, sizeof(*fixture->device), GFP_KERNEL);
	fixture->page = kunit_kzalloc(test, sizeof(*fixture->page), GFP_KERNEL);
	if (!fixture->area || !fixture->device || !fixture->page) {
		KUNIT_FAIL(test, "Round037 synthetic original MM fixture allocation");
		return false;
	}
	fixture->area->bdev = fixture->device;
	fixture->scope.original_slot = swp_entry(1U, 37U);
	fixture->scope.initial_epoch = 17U;
	fixture->scope.final_epoch = 17U;
	fixture->scope.active_area = fixture->area;
	fixture->scope.source_device = fixture->device;
	fixture->scope.original_sector = 4096U; /* Nonlinear: 37*8 is 296. */
	fixture->scope.area_ref_held = true; /* KUnit simulation, NOT real ref. */
	fixture->scope.source_bio_live = true;
	fixture->scope.owner_live = true;
	fixture->scope.folio_unlocked = true;
	fixture->vector.bv_page = fixture->page;
	fixture->vector.bv_len = 4096U;
	fixture->bio.bi_bdev = fixture->device;
	fixture->bio.bi_io_vec = &fixture->vector;
	fixture->bio.bi_opf = REQ_OP_WRITE | REQ_SWAP;
	fixture->bio.bi_iter.bi_size = 4096U;
	fixture->bio.bi_iter.bi_sector = 4096U;
	return true;
}

static int swapz_round037_mm_fixture_check(
		const struct swapz_round037_mm_fixture *fixture)
{
	return swapz_round037_mm_scope_check(
		&fixture->scope, &fixture->bio, swp_entry(1U, 37U),
		17U, fixture->area, 4096U, true, true, true);
}

static void swapz_round037_scope_epoch_aba_kunit(struct kunit *test)
{
	struct swapz_round037_mm_fixture fixture = {};

	if (!swapz_round037_mm_fixture_init(test, &fixture))
		return;
	KUNIT_EXPECT_EQ(test, swapz_round037_mm_fixture_check(&fixture),
			-EOPNOTSUPP);
	fixture.scope.final_epoch = 18U; /* Reallocated same slot. */
	KUNIT_EXPECT_EQ(test, swapz_round037_mm_fixture_check(&fixture),
			-ESTALE);
	fixture.scope.final_epoch = 17U;
	fixture.scope.original_slot = swp_entry(2U, 37U);
	KUNIT_EXPECT_EQ(test, swapz_round037_mm_fixture_check(&fixture),
			-ESTALE);
	fixture.scope.original_slot = swp_entry(1U, 37U);
	fixture.scope.owner_live = false; /* Older sealed owner released. */
	KUNIT_EXPECT_EQ(test, swapz_round037_mm_fixture_check(&fixture),
			-ESTALE);
}

static void swapz_round037_scope_swapoff_readd_kunit(struct kunit *test)
{
	struct swapz_round037_mm_fixture fixture = {};
	struct block_device *replacement;

	if (!swapz_round037_mm_fixture_init(test, &fixture))
		return;
	replacement = kunit_kzalloc(test, sizeof(*replacement), GFP_KERNEL);
	KUNIT_ASSERT_NOT_NULL(test, replacement);
	fixture.area->bdev = replacement; /* Same packed slot; different area. */
	KUNIT_EXPECT_EQ(test, swapz_round037_mm_fixture_check(&fixture),
			-ESTALE);
	fixture.area->bdev = fixture.device;
	fixture.scope.original_sector = 37U * 8U; /* Wrong linear guess. */
	KUNIT_EXPECT_EQ(test, swapz_round037_mm_fixture_check(&fixture),
			-ESTALE);
	fixture.scope.original_sector = 0U; /* Protected SWAPSPACE2 header. */
	KUNIT_EXPECT_EQ(test, swapz_round037_mm_fixture_check(&fixture),
			-ERANGE);
	fixture.scope.original_sector = (sector_t)-1;
	KUNIT_EXPECT_EQ(test, swapz_round037_mm_fixture_check(&fixture),
			-ERANGE);
}

static void swapz_round037_scope_bio_late_kunit(struct kunit *test)
{
	struct swapz_round037_mm_fixture fixture = {};

	if (!swapz_round037_mm_fixture_init(test, &fixture))
		return;
	fixture.bio.bi_flags |= 1U << BIO_CLONED;
	KUNIT_EXPECT_EQ(test, swapz_round037_mm_fixture_check(&fixture),
			-EOPNOTSUPP);
	fixture.bio.bi_flags = 0;
	fixture.bio.bi_iter.bi_size = 2048U; /* Split clone, half page. */
	KUNIT_EXPECT_EQ(test, swapz_round037_mm_fixture_check(&fixture),
			-EOPNOTSUPP);
	fixture.bio.bi_iter.bi_size = 4096U;
	fixture.scope.source_bio_live = false; /* Parent uninit already ran. */
	KUNIT_EXPECT_EQ(test, swapz_round037_mm_fixture_check(&fixture),
			-ESTALE);
	fixture.scope.source_bio_live = true;
	fixture.scope.folio_unlocked = false; /* Unexpected unlock state. */
	KUNIT_EXPECT_EQ(test, swapz_round037_mm_fixture_check(&fixture),
			-ESTALE);
}

static void swapz_round037_scope_close_once_kunit(struct kunit *test)
{
	struct swapz_round037_mm_fixture fixture = {};
	struct swap_info_struct *borrowed_area;
	struct swapz_round037_mm_owner_scope unchanged;

	if (!swapz_round037_mm_fixture_init(test, &fixture))
		return;
	unchanged = fixture.scope;
	KUNIT_EXPECT_EQ(test, swapz_round037_mm_fixture_check(&fixture),
			-EOPNOTSUPP);
	KUNIT_EXPECT_EQ(test, memcmp(&unchanged, &fixture.scope,
				     sizeof(unchanged)), 0);
	KUNIT_EXPECT_EQ(test, swapz_round037_mm_scope_check(
		&fixture.scope, NULL, fixture.scope.original_slot, 17U,
		fixture.area, 4096U, true, true, true), -EINVAL);
	/* Synthetic detaches verify once-only control, NOT an actual put. */
	borrowed_area = swapz_round037_mm_scope_detach(&fixture.scope);
	KUNIT_EXPECT_PTR_EQ(test, borrowed_area, fixture.area);
	KUNIT_EXPECT_PTR_EQ(test,
		swapz_round037_mm_scope_detach(&fixture.scope), NULL);
	KUNIT_EXPECT_EQ(test, swapz_round037_mm_fixture_check(&fixture),
			-ESTALE);
}

static struct kunit_case swapz_round037_scope_cases[] = {
	KUNIT_CASE(swapz_round037_scope_epoch_aba_kunit),
	KUNIT_CASE(swapz_round037_scope_swapoff_readd_kunit),
	KUNIT_CASE(swapz_round037_scope_bio_late_kunit),
	KUNIT_CASE(swapz_round037_scope_close_once_kunit),
	{}
};

static struct kunit_suite swapz_round037_scope_suite = {
	.name = "swapz_round037_original_mm_area_scoped_no_authority",
	.test_cases = swapz_round037_scope_cases,
};
kunit_test_suite(swapz_round037_scope_suite);
/* ROUND037_MM_SCOPED_OWNER_END */
#endif /* Original MM scoped KUnit observation; NO async authority */
"""
ROUND037_MM_OWNER_HOOK = r"""
#if defined(SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST) && \
    defined(SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
	/* Synchronous original-area ownership observation; never redirects IO. */
	if (bio->bi_swapz_ci_sideband)
		(void)swapz_round037_original_mm_scoped_probe(
			ctx, bio, bio_first_folio_all(bio));
#endif
"""


def apply_round037_original_mm_owner(path: str, composed: str) -> str:
    """Inject only private genuine original page_io.c C and dispatch probe."""
    if path != "mm/page_io.c":
        return composed
    handler = "static void swap_bdev_submit_write(struct swap_io_ctx *ctx)\n"
    composed = replace_once(composed, handler, ROUND037_MM_OWNER_C + "\n" + handler,
                            path, "round037-original-mm-scoped-owner")
    return replace_once(composed, ROUND036_LIFETIME_HOOK,
                        ROUND036_LIFETIME_HOOK + ROUND037_MM_OWNER_HOOK,
                        path, "round037-original-mm-dispatch-probe")


# Round038 original zswap STORE-time CRC capture and already-stored owned
# writeback provenance: diagnostic only, default never compiled.
ROUND038_STORE_PROVENANCE_MACRO = "SWAPZ_ROUND038_ORIGINAL_STORE_PROVENANCE_TEST"
ROUND038_STORE_PROVENANCE_C = r"""#if defined(SWAPZ_ROUND038_ORIGINAL_STORE_PROVENANCE_TEST) && \
    defined(SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST) && \
    defined(SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
/* ROUND038_ORIGINAL_STORE_PROVENANCE_BEGIN */
#include <kunit/test.h>

/*
 * A diagnostic value COPY, not an authenticated allocation/DM authority.
 * STORE's SHA is taken from the ORIGINAL full 4096 locked folio before
 * compression; STORE CRC is taken from original compressor dst, AFTER the
 * real zsmalloc write and BEFORE the compressor mutex is dropped.
 * At eviction the owned CRC is independently recomputed over a copy of
 * that very same zsmalloc object, NEVER the decompressed 4096 BIO.
 */
struct swapz_round038_store_observation {
	u64 source_swap_entry;
	u64 allocation_epoch;
	u64 stored_identity;
	u32 compressed_crc32c;
	u16 compressed_length;
	u16 decoded_length;
	u8 representation_version;
	u8 codec;
	u8 original_sha256[SHA256_DIGEST_SIZE];
	bool stored_in_original_tree;
	bool source_owner_live;
	bool folio_locked;
	bool original_bio_full_4096;
	bool current_slot_ref_held;
	bool current_dm_gc_ref_held;
};

/* ROUND038_ORIGINAL_STORE_PURE_C_BEGIN */
static int swapz_round038_store_observation_check(
		const struct swapz_round038_store_observation *store,
		const struct swapz_round038_store_observation *writeback)
{
	u8 digest_present = 0;
	unsigned int digest_index;

	if (!store || !writeback)
		return -EINVAL;
	if (!store->source_swap_entry || !store->allocation_epoch ||
	    !store->stored_identity || !store->stored_in_original_tree ||
	    !writeback->stored_in_original_tree ||
	    !writeback->source_owner_live || !writeback->folio_locked)
		return -ESTALE;
	if (store->source_swap_entry != writeback->source_swap_entry ||
	    store->allocation_epoch != writeback->allocation_epoch ||
	    store->stored_identity != writeback->stored_identity)
		return -ESTALE;
	if (!store->compressed_length || store->compressed_length > 3568U ||
	    !writeback->compressed_length ||
	    writeback->compressed_length > 3568U ||
	    store->compressed_length != writeback->compressed_length ||
	    store->decoded_length != 4096U ||
	    writeback->decoded_length != 4096U ||
	    store->representation_version != 1U ||
	    writeback->representation_version != 1U ||
	    store->codec != 1U || writeback->codec != 1U ||
	    !writeback->original_bio_full_4096)
		return -EOPNOTSUPP;
	for (digest_index = 0; digest_index < SHA256_DIGEST_SIZE;
	     digest_index++)
		digest_present |= store->original_sha256[digest_index];
	if (!digest_present)
		return -ENODATA;
	if (store->compressed_crc32c != writeback->compressed_crc32c ||
	    memcmp(store->original_sha256, writeback->original_sha256,
		   SHA256_DIGEST_SIZE))
		return -EBADMSG;
	/*
	 * Even a real original zswap STORE and true matching CRC+SHA do NOT
	 * pin a current slot incarnation and current downstream DM map/GC
	 * across asynchronous original BIO clone/split/endio/swapoff.
	 * Forged TRUE booleans in synthetic KUnit cannot mint either lease.
	 */
	return -EOPNOTSUPP;
}
/* ROUND038_ORIGINAL_STORE_PURE_C_END */

/* Called ONLY from actual pinned zswap STORE acceptance or writeback. */
static noinline int swapz_round038_actual_store_provenance_probe(
		struct zswap_entry *entry, swp_entry_t original_slot,
		struct xarray *tree, pgoff_t offset,
		bool writeback_phase, bool original_owned_bio)
{
	struct swapz_round038_store_observation store = {};
	struct swapz_round038_store_observation observed = {};
	struct zswap_pool *pool;
	u64 epoch;

	if (!entry || !tree || xa_load(tree, offset) != entry ||
	    entry->swpentry.val != original_slot.val ||
	    !entry->swapz_round028_store_bound ||
	    !entry->swapz_round038_store_compressed ||
	    !entry->swapz_round028_stored_entry_identity ||
	    !entry->swapz_round028_allocation_epoch)
		return -ESTALE;
	pool = zswap_entry_pool(entry);
	if (!pool || !pool->zs_pool || strcmp(pool->tfm_name, "lz4"))
		return -EOPNOTSUPP;
	epoch = swapz_round028_slot_epoch(original_slot);
	if (!epoch || epoch != entry->swapz_round028_allocation_epoch)
		return -ESTALE;
	store.source_swap_entry = (u64)original_slot.val;
	store.allocation_epoch = epoch;
	store.stored_identity = entry->swapz_round028_stored_entry_identity;
	store.compressed_crc32c = entry->swapz_round038_store_crc32c;
	store.compressed_length = (u16)entry->length;
	store.decoded_length = 4096U;
	store.representation_version = 1U;
	store.codec = 1U;
	memcpy(store.original_sha256, entry->swapz_round028_store_sha256,
	       sizeof(store.original_sha256));
	store.stored_in_original_tree = true;
	observed = store;
	/* The original locked folio pins the entry only during observation. */
	observed.folio_locked = true;
	observed.source_owner_live = writeback_phase && original_owned_bio;
	observed.original_bio_full_4096 = writeback_phase && original_owned_bio;
	return swapz_round038_store_observation_check(&store, &observed);
}

/* Internal KUnit inputs below are SYNTHETIC, not actual zswap STORE. */
static void swapz_round038_store_fixture(
		struct swapz_round038_store_observation *sample)
{
	memset(sample, 0, sizeof(*sample));
	sample->source_swap_entry = (u64)swp_entry(1U, 37U).val;
	sample->allocation_epoch = 17U;
	sample->stored_identity = 31U;
	sample->compressed_crc32c = 0x4badb002U;
	sample->compressed_length = 312U;
	sample->decoded_length = 4096U;
	sample->representation_version = 1U;
	sample->codec = 1U;
	sample->original_sha256[0] = 1U;
	sample->original_sha256[31] = 2U;
	sample->stored_in_original_tree = true;
	sample->source_owner_live = true;
	sample->folio_locked = true;
	sample->original_bio_full_4096 = true;
}

static void swapz_round038_store_provenance_identity_kunit(struct kunit *test)
{
	struct swapz_round038_store_observation source, consumer;

	swapz_round038_store_fixture(&source);
	consumer = source;
	KUNIT_EXPECT_EQ(test,
		swapz_round038_store_observation_check(&source, &consumer),
		-EOPNOTSUPP);
	consumer.allocation_epoch++;
	KUNIT_EXPECT_EQ(test,
		swapz_round038_store_observation_check(&source, &consumer),
		-ESTALE);
	consumer = source;
	consumer.stored_identity++;
	KUNIT_EXPECT_EQ(test,
		swapz_round038_store_observation_check(&source, &consumer),
		-ESTALE);
	consumer = source;
	consumer.source_swap_entry = (u64)swp_entry(2U, 37U).val;
	KUNIT_EXPECT_EQ(test,
		swapz_round038_store_observation_check(&source, &consumer),
		-ESTALE);
}

static void swapz_round038_store_provenance_crc_sha_kunit(struct kunit *test)
{
	struct swapz_round038_store_observation source, consumer;

	swapz_round038_store_fixture(&source);
	consumer = source;
	consumer.compressed_crc32c ^= 1U;
	KUNIT_EXPECT_EQ(test,
		swapz_round038_store_observation_check(&source, &consumer),
		-EBADMSG);
	consumer = source;
	consumer.original_sha256[31] ^= 1U;
	KUNIT_EXPECT_EQ(test,
		swapz_round038_store_observation_check(&source, &consumer),
		-EBADMSG);
	memset(source.original_sha256, 0, sizeof(source.original_sha256));
	KUNIT_EXPECT_EQ(test,
		swapz_round038_store_observation_check(&source, &source),
		-ENODATA);
}

static void swapz_round038_store_provenance_format_kunit(struct kunit *test)
{
	struct swapz_round038_store_observation source, consumer;

	swapz_round038_store_fixture(&source);
	consumer = source;
	consumer.compressed_length = 0;
	KUNIT_EXPECT_EQ(test,
		swapz_round038_store_observation_check(&source, &consumer),
		-EOPNOTSUPP);
	consumer.compressed_length = 3569U;
	KUNIT_EXPECT_EQ(test,
		swapz_round038_store_observation_check(&source, &consumer),
		-EOPNOTSUPP);
	consumer = source;
	consumer.codec = 2U;
	KUNIT_EXPECT_EQ(test,
		swapz_round038_store_observation_check(&source, &consumer),
		-EOPNOTSUPP);
	consumer = source;
	consumer.decoded_length = 2048U;
	KUNIT_EXPECT_EQ(test,
		swapz_round038_store_observation_check(&source, &consumer),
		-EOPNOTSUPP);
}

static void swapz_round038_store_provenance_retired_kunit(struct kunit *test)
{
	struct swapz_round038_store_observation source, consumer;

	swapz_round038_store_fixture(&source);
	consumer = source;
	consumer.stored_in_original_tree = false;
	KUNIT_EXPECT_EQ(test,
		swapz_round038_store_observation_check(&source, &consumer),
		-ESTALE);
	consumer = source;
	consumer.source_owner_live = false;
	KUNIT_EXPECT_EQ(test,
		swapz_round038_store_observation_check(&source, &consumer),
		-ESTALE);
	consumer = source;
	consumer.folio_locked = false;
	KUNIT_EXPECT_EQ(test,
		swapz_round038_store_observation_check(&source, &consumer),
		-ESTALE);
	consumer = source;
	consumer.original_bio_full_4096 = false;
	KUNIT_EXPECT_EQ(test,
		swapz_round038_store_observation_check(&source, &consumer),
		-EOPNOTSUPP);
}

static void swapz_round038_store_provenance_no_authority_kunit(struct kunit *test)
{
	struct swapz_round038_store_observation source, consumer, unchanged;

	swapz_round038_store_fixture(&source);
	consumer = source;
	unchanged = consumer;
	consumer.current_slot_ref_held = true;
	consumer.current_dm_gc_ref_held = true;
	KUNIT_EXPECT_EQ(test,
		swapz_round038_store_observation_check(&source, &consumer),
		-EOPNOTSUPP);
	KUNIT_EXPECT_EQ(test, memcmp(&source, &unchanged, sizeof(source)), 0);
	KUNIT_EXPECT_EQ(test,
		swapz_round038_store_observation_check(NULL, &consumer),
		-EINVAL);
}

static struct kunit_case swapz_round038_store_cases[] = {
	KUNIT_CASE(swapz_round038_store_provenance_identity_kunit),
	KUNIT_CASE(swapz_round038_store_provenance_crc_sha_kunit),
	KUNIT_CASE(swapz_round038_store_provenance_format_kunit),
	KUNIT_CASE(swapz_round038_store_provenance_retired_kunit),
	KUNIT_CASE(swapz_round038_store_provenance_no_authority_kunit),
	{}
};

static struct kunit_suite swapz_round038_store_suite = {
	.name = "swapz_round038_original_store_provenance_no_authority",
	.test_cases = swapz_round038_store_cases,
};
kunit_test_suite(swapz_round038_store_suite);
/* ROUND038_ORIGINAL_STORE_PROVENANCE_END */
#endif /* CI-only original STORE provenance; never live authority */
"""

def apply_round038_original_store(path: str, composed: str) -> str:
    """Guard the authentic original STORE producer and writeback observer."""
    if path != "mm/zswap.c":
        return composed
    # crc32c is called inside ORIGINAL zswap_compress(), before the older
    # Round030 snapshot source's later local include. Declare it up front.
    composed = replace_once(composed,
        "#include <linux/zsmalloc.h>\n",
        "#include <linux/zsmalloc.h>\n" + """#if defined(SWAPZ_ROUND038_ORIGINAL_STORE_PROVENANCE_TEST) && \\
    defined(SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST) && \\
    defined(SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST) && \\
    defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \\
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \\
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \\
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \\
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \\
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \\
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
#include <linux/crc32c.h>
#endif
""",
        path, "round038-original-store-crc32c-before-compress")
    composed = replace_once(composed,
        "\tbool swapz_round028_store_bound;\n#endif\n",
        "\tbool swapz_round028_store_bound;\n#endif\n" + r"""#if defined(SWAPZ_ROUND038_ORIGINAL_STORE_PROVENANCE_TEST) && \
    defined(SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST) && \
    defined(SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
	/* Original dictionary-free LZ4 compressor output CRC at STORE. */
	u32 swapz_round038_store_crc32c;
	bool swapz_round038_store_compressed;
#endif
""",
        path, "store-crc-field")
    composed = replace_once(composed,
        "static int zswap_writeback_entry(struct zswap_entry *entry,\n",
        ROUND038_STORE_PROVENANCE_C + "\nstatic int zswap_writeback_entry(struct zswap_entry *entry,\n",
        path, "original-provenance-source")
    composed = replace_once(composed,
        "\tif (!zswap_compress(folio, index, entry, pool))",
        r"""#if defined(SWAPZ_ROUND038_ORIGINAL_STORE_PROVENANCE_TEST) && \
    defined(SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST) && \
    defined(SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
	entry->swapz_round038_store_crc32c = 0;
	entry->swapz_round038_store_compressed = false;
#endif
""" + "\tif (!zswap_compress(folio, index, entry, pool))",
        path, "initialize-original-store-crc")
    composed = replace_once(composed,
        "\tzs_obj_write(pool->zs_pool, handle, dst, dlen);\n",
        "\tzs_obj_write(pool->zs_pool, handle, dst, dlen);\n" + r"""#if defined(SWAPZ_ROUND038_ORIGINAL_STORE_PROVENANCE_TEST) && \
    defined(SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST) && \
    defined(SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
	/* Original compressor's dst is still valid under its own mutex;
	 * CRC exactly matches original zs_obj_write input, not recompressed data.
	 */
	if (dlen >= 1U && dlen <= 3568U &&
	    !strcmp(pool->tfm_name, "lz4") &&
	    entry->swapz_round028_store_bound) {
		entry->swapz_round038_store_crc32c = ~crc32c(~0U, dst, dlen);
		entry->swapz_round038_store_compressed = true;
	}
#endif
""",
        path, "capture-real-compressor-stored-crc")
    composed = replace_once(composed,
        "\treturn true;\n\nstore_failed:",
        r"""#if defined(SWAPZ_ROUND038_ORIGINAL_STORE_PROVENANCE_TEST) && \
    defined(SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST) && \
    defined(SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
	/* A REAL original xa_store + LRU publication and original STORE SHA;
	 * diagnostic only, never an authorized downstream route token.
	 */
	(void)swapz_round038_actual_store_provenance_probe(
		entry, page_swpentry, swap_zswap_tree(page_swpentry),
		swp_offset(page_swpentry), false, false);
#endif
""" + "\treturn true;\n\nstore_failed:",
        path, "real-accepted-store-after-xarray")
    composed = replace_once(composed,
        "\tctx.swapz_round031_owned =\n\t\tswapz_round031_mm_bio_create(entry, swpentry, tree, offset);\n",
        "\tctx.swapz_round031_owned =\n\t\tswapz_round031_mm_bio_create(entry, swpentry, tree, offset);\n" + r"""#if defined(SWAPZ_ROUND038_ORIGINAL_STORE_PROVENANCE_TEST) && \
    defined(SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST) && \
    defined(SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
	/* Original locked folio and current xarray still pin the real
	 * zsmalloc entry; the separately owned BIO copy must match STORE CRC.
	 */
	(void)swapz_round038_actual_store_provenance_probe(
		entry, swpentry, tree, offset, true,
		ctx.swapz_round031_owned != NULL);
#endif
""",
        path, "real-original-writeback-ownership")
    # Compare original STORE's compressor CRC to real later zsmalloc copy
    # BEFORE the independently refcounted BIO owner is constructed.
    composed = replace_once(composed,
        "    entry->length == compressed_length) {",
        "    entry->length == compressed_length\n" + r"""
#if defined(SWAPZ_ROUND038_ORIGINAL_STORE_PROVENANCE_TEST) && \
    defined(SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST) && \
    defined(SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
	    && entry->swapz_round038_store_compressed &&
	    entry->swapz_round038_store_crc32c == source_crc32c
#endif
""" + ") {",
        path, "sealed-store-vs-owned-copy-crc")
    return composed


# Round040 original MM asynchronous source-area/slot lifetime falsification:
# original KUnit source only. No authorization exported to downstream DM.
ROUND040_ORIGINAL_ASYNC_LEASE_MACRO = "SWAPZ_ROUND040_ORIGINAL_ASYNC_SLOT_LEASE_NEGATIVE_TEST"
ROUND040_ORIGINAL_ASYNC_LEASE_C = r"""#if defined(SWAPZ_ROUND040_ORIGINAL_ASYNC_SLOT_LEASE_NEGATIVE_TEST) && \
    defined(SWAPZ_ROUND038_ORIGINAL_STORE_PROVENANCE_TEST) && \
    defined(SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST) && \
    defined(SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
/* ROUND040_ORIGINAL_ASYNC_LEASE_C_BEGIN */
/*
 * Negative proof ONLY: this is a VALUE snapshot of the real original
 * synchronous area observation, never a pin or permission. The genuine
 * get_swap_device() area users percpu_ref in Round037 was put BEFORE this
 * dispatch observation and BEFORE the original asynchronous submit_bio().
 * A folio lock/allocated-swap epoch read cannot be retained by a later
 * clone, split, endio, swapoff/re-add or target DM GC map generation.
 * No positive transfer path, hardware operation or raw BIO mutation exists.
 */
struct swapz_round040_async_lease_evidence {
	u64 source_swap_entry;
	u64 candidate_swap_entry;
	u64 source_slot_epoch;
	u64 candidate_slot_epoch;
	u64 original_area_generation;
	u64 candidate_area_generation;
	u64 expected_dm_map_generation;
	u64 expected_dm_gc_generation;
	const void *original_bdev;
	const void *candidate_bdev;
	u64 original_sector;
	u64 candidate_sector;
	u32 original_bio_bytes;
	u32 candidate_bio_bytes;
	bool area_ref_was_scoped;
	bool area_ref_released_before_submit;
	bool source_bio_live;
	bool original_owner_live;
	bool folio_unlocked_for_writeback;
	bool async_endio_pending;
	bool bio_cloned;
	bool bio_split;
	bool canceled_or_teardown;
	bool source_allocation_lease_held;
	bool current_dm_gc_lease_held;
};

/* ROUND040_ORIGINAL_ASYNC_LEASE_PURE_C_BEGIN */
static int swapz_round040_async_lease_refuse(
		const struct swapz_round040_async_lease_evidence *evidence)
{
	if (!evidence)
		return -EINVAL;
	if (!evidence->source_swap_entry ||
	    !evidence->candidate_swap_entry ||
	    evidence->source_swap_entry != evidence->candidate_swap_entry ||
	    !evidence->source_slot_epoch || !evidence->candidate_slot_epoch ||
	    evidence->source_slot_epoch != evidence->candidate_slot_epoch)
		return -ESTALE;
	/* Area generation is UNKNOWN (zero) on real original dispatch.
	 * A matching synthetic generation never becomes an actual ref.
	 */
	if (evidence->original_area_generation &&
	    evidence->candidate_area_generation &&
	    evidence->original_area_generation !=
		    evidence->candidate_area_generation)
		return -ESTALE;
	if (!evidence->original_bdev || !evidence->candidate_bdev ||
	    evidence->original_bdev != evidence->candidate_bdev)
		return -ESTALE;
	if (!evidence->original_sector || !evidence->candidate_sector ||
	    (evidence->original_sector & 7U) ||
	    (evidence->candidate_sector & 7U) ||
	    evidence->original_sector != evidence->candidate_sector)
		return -ERANGE;
	if (evidence->original_bio_bytes != 4096U ||
	    evidence->candidate_bio_bytes != 4096U)
		return -EOPNOTSUPP;
	if (!evidence->area_ref_was_scoped ||
	    !evidence->area_ref_released_before_submit ||
	    !evidence->source_bio_live ||
	    !evidence->original_owner_live ||
	    !evidence->folio_unlocked_for_writeback)
		return -ESTALE;
	/* Released area ref cannot survive original asynchronous callback.
	 * Neither cloned/split children nor canceled/late endio inherit it.
	 */
	if (!evidence->async_endio_pending || evidence->bio_cloned ||
	    evidence->bio_split || evidence->canceled_or_teardown)
		return -EOPNOTSUPP;
	if (!evidence->source_allocation_lease_held ||
	    !evidence->current_dm_gc_lease_held ||
	    !evidence->expected_dm_map_generation ||
	    !evidence->expected_dm_gc_generation)
		return -EOPNOTSUPP;
	/*
	 * Even fabricated all-positive future-generation flags do NOT
	 * establish an allocator-incarnation lease or a current active
	 * downstream DM target/extent/GC ref through async submission.
	 */
	return -EOPNOTSUPP;
}
/* ROUND040_ORIGINAL_ASYNC_LEASE_PURE_C_END */

/*
 * This actual original mm/page_io.c call occurs AFTER the existing
 * Round037 synchronous scope's real users ref has ALREADY been put.
 * Acquire a NEW ORIGINAL get_swap_device() area users ref ONLY while
 * reading the original bdev/nonlinear sector, full packed slot, cluster
 * epoch and genuinely owned BIO, then put THAT REF EXACTLY ONCE before
 * checking any proposed async source/DM lease. No area pointer escapes,
 * and no freed swap_info_struct is dereferenced after its reference put.
 * This does NOT issue IO or mutate the original uncompressed 4096 WRITE.
 */
static noinline int swapz_round040_original_mm_post_put_lease_probe(
		const struct swap_io_ctx *ctx, const struct bio *source_bio,
		struct folio *folio)
{
	struct swapz_round040_async_lease_evidence evidence = {};
	struct swap_info_struct *active_area;
	swp_entry_t original_slot;

	if (!ctx || !ctx->sis || !source_bio || !folio ||
	    !source_bio->bi_swapz_ci_sideband ||
	    !folio_test_swapcache(folio) ||
	    !folio_test_writeback(folio) || folio_test_locked(folio))
		return -ESTALE;
	original_slot = folio_swap_entry(folio, 0);
	if (!original_slot.val || swp_type(original_slot) >= MAX_SWAPFILES)
		return -ESTALE;
	active_area = get_swap_device(original_slot);
	if (IS_ERR_OR_NULL(active_area))
		return -ESTALE;
	if (active_area != ctx->sis || !active_area->bdev)
		goto release_area;

	evidence.source_swap_entry = (u64)original_slot.val;
	evidence.candidate_swap_entry =
		(u64)ctx->swapz_round035_original_slot.val;
	evidence.source_slot_epoch = swapz_round028_slot_epoch(original_slot);
	evidence.candidate_slot_epoch =
		ctx->swapz_round035_original_epoch;
	evidence.original_bdev = active_area->bdev;
	evidence.candidate_bdev = source_bio->bi_bdev;
	evidence.original_sector = (u64)swap_folio_sector(folio);
	evidence.candidate_sector = (u64)source_bio->bi_iter.bi_sector;
	evidence.original_bio_bytes = 4096U;
	evidence.candidate_bio_bytes = source_bio->bi_iter.bi_size;
	evidence.area_ref_was_scoped = true;
	evidence.source_bio_live = true;
	evidence.original_owner_live = swapz_round035_bio_owner_matches(
		source_bio, (u64)original_slot.val, evidence.source_slot_epoch);
	evidence.folio_unlocked_for_writeback = true;
	evidence.async_endio_pending = true;
release_area:
	/* A second genuine, locally held ref: never forwarded to BIO/DM. */
	put_swap_device(active_area);
	if (!evidence.area_ref_was_scoped)
		return -ESTALE;
	evidence.area_ref_released_before_submit = true;
	/* No ORIGINAL lease API exists for slot reuse/swapoff or DM GC.
	 * Map+GC generation and both real async ownership pins stay ZERO.
	 */
	return swapz_round040_async_lease_refuse(&evidence);
}

/* KUnit fixtures below are synthetic values, no active swapon/swapoff/IO. */
static void swapz_round040_async_lease_fixture(
		struct swapz_round040_async_lease_evidence *evidence)
{
	memset(evidence, 0, sizeof(*evidence));
	evidence->source_swap_entry = (u64)swp_entry(1U, 37U).val;
	evidence->candidate_swap_entry = evidence->source_swap_entry;
	evidence->source_slot_epoch = 17U;
	evidence->candidate_slot_epoch = 17U;
	evidence->original_area_generation = 3U; /* Synthetic only. */
	evidence->candidate_area_generation = 3U;
	/* Nonlinear original swapfile extent: 4096 != 37*8. */
	evidence->original_sector = 4096U;
	evidence->candidate_sector = 4096U;
	evidence->original_bdev = evidence;
	evidence->candidate_bdev = evidence;
	evidence->original_bio_bytes = 4096U;
	evidence->candidate_bio_bytes = 4096U;
	evidence->area_ref_was_scoped = true;
	evidence->area_ref_released_before_submit = true;
	evidence->source_bio_live = true;
	evidence->original_owner_live = true;
	evidence->folio_unlocked_for_writeback = true;
	evidence->async_endio_pending = true;
}

static void swapz_round040_scope_put_late_callback_kunit(struct kunit *test)
{
	struct swapz_round040_async_lease_evidence evidence;

	swapz_round040_async_lease_fixture(&evidence);
	KUNIT_EXPECT_EQ(test, swapz_round040_async_lease_refuse(&evidence),
			-EOPNOTSUPP);
	evidence.area_ref_released_before_submit = false;
	KUNIT_EXPECT_EQ(test, swapz_round040_async_lease_refuse(&evidence),
			-ESTALE);
	evidence.area_ref_released_before_submit = true;
	evidence.source_bio_live = false;
	KUNIT_EXPECT_EQ(test, swapz_round040_async_lease_refuse(&evidence),
			-ESTALE);
}

static void swapz_round040_slot_swapoff_readd_aba_kunit(struct kunit *test)
{
	struct swapz_round040_async_lease_evidence evidence;

	swapz_round040_async_lease_fixture(&evidence);
	evidence.candidate_slot_epoch++;
	KUNIT_EXPECT_EQ(test, swapz_round040_async_lease_refuse(&evidence),
			-ESTALE);
	evidence.candidate_slot_epoch = evidence.source_slot_epoch;
	evidence.candidate_swap_entry = (u64)swp_entry(2U, 37U).val;
	KUNIT_EXPECT_EQ(test, swapz_round040_async_lease_refuse(&evidence),
			-ESTALE);
	evidence.candidate_swap_entry = evidence.source_swap_entry;
	evidence.candidate_area_generation++;
	KUNIT_EXPECT_EQ(test, swapz_round040_async_lease_refuse(&evidence),
			-ESTALE);
}

static void swapz_round040_clone_split_last_ref_kunit(struct kunit *test)
{
	struct swapz_round040_async_lease_evidence evidence;

	swapz_round040_async_lease_fixture(&evidence);
	evidence.bio_cloned = true;
	KUNIT_EXPECT_EQ(test, swapz_round040_async_lease_refuse(&evidence),
			-EOPNOTSUPP);
	evidence.bio_cloned = false;
	evidence.bio_split = true;
	KUNIT_EXPECT_EQ(test, swapz_round040_async_lease_refuse(&evidence),
			-EOPNOTSUPP);
	evidence.bio_split = false;
	evidence.original_owner_live = false;
	KUNIT_EXPECT_EQ(test, swapz_round040_async_lease_refuse(&evidence),
			-ESTALE);
}

static void swapz_round040_cancel_teardown_gc_unknown_kunit(struct kunit *test)
{
	struct swapz_round040_async_lease_evidence evidence, unchanged;

	swapz_round040_async_lease_fixture(&evidence);
	evidence.canceled_or_teardown = true;
	KUNIT_EXPECT_EQ(test, swapz_round040_async_lease_refuse(&evidence),
			-EOPNOTSUPP);
	evidence.canceled_or_teardown = false;
	evidence.async_endio_pending = false;
	KUNIT_EXPECT_EQ(test, swapz_round040_async_lease_refuse(&evidence),
			-EOPNOTSUPP);
	evidence.async_endio_pending = true;
	evidence.expected_dm_map_generation = 7U;
	evidence.expected_dm_gc_generation = 9U;
	evidence.source_allocation_lease_held = true;
	evidence.current_dm_gc_lease_held = true;
	unchanged = evidence;
	KUNIT_EXPECT_EQ(test, swapz_round040_async_lease_refuse(&evidence),
			-EOPNOTSUPP);
	KUNIT_EXPECT_EQ(test, memcmp(&evidence, &unchanged,
				    sizeof(evidence)), 0);
}

static void swapz_round040_bdev_sector_raw_geometry_kunit(struct kunit *test)
{
	struct swapz_round040_async_lease_evidence evidence;

	swapz_round040_async_lease_fixture(&evidence);
	evidence.candidate_bdev = (const void *)test;
	KUNIT_EXPECT_EQ(test, swapz_round040_async_lease_refuse(&evidence),
			-ESTALE);
	evidence.candidate_bdev = evidence.original_bdev;
	evidence.candidate_sector = 296U; /* Packed slot != original sector. */
	KUNIT_EXPECT_EQ(test, swapz_round040_async_lease_refuse(&evidence),
			-ERANGE);
	evidence.candidate_sector = evidence.original_sector;
	evidence.candidate_bio_bytes = 2048U;
	KUNIT_EXPECT_EQ(test, swapz_round040_async_lease_refuse(&evidence),
			-EOPNOTSUPP);
	KUNIT_EXPECT_EQ(test, swapz_round040_async_lease_refuse(NULL),
			-EINVAL);
}

static struct kunit_case swapz_round040_async_lease_cases[] = {
	KUNIT_CASE(swapz_round040_scope_put_late_callback_kunit),
	KUNIT_CASE(swapz_round040_slot_swapoff_readd_aba_kunit),
	KUNIT_CASE(swapz_round040_clone_split_last_ref_kunit),
	KUNIT_CASE(swapz_round040_cancel_teardown_gc_unknown_kunit),
	KUNIT_CASE(swapz_round040_bdev_sector_raw_geometry_kunit),
	{}
};

static struct kunit_suite swapz_round040_async_lease_suite = {
	.name = "swapz_round040_original_mm_async_lease_no_authority",
	.test_cases = swapz_round040_async_lease_cases,
};
kunit_test_suite(swapz_round040_async_lease_suite);
/* ROUND040_ORIGINAL_ASYNC_LEASE_C_END */
#endif /* Round040 original MM source lifetime negative, no live authority */
"""
ROUND040_ORIGINAL_ASYNC_LEASE_HOOK = r"""#if defined(SWAPZ_ROUND040_ORIGINAL_ASYNC_SLOT_LEASE_NEGATIVE_TEST) && \
    defined(SWAPZ_ROUND038_ORIGINAL_STORE_PROVENANCE_TEST) && \
    defined(SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST) && \
    defined(SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
	/* Round037 ALREADY released the real scoped area users ref.
	 * No area/slot/DM generation authority survives original async IO.
	 */
	if (bio->bi_swapz_ci_sideband)
		(void)swapz_round040_original_mm_post_put_lease_probe(
			ctx, bio, bio_first_folio_all(bio));
#endif
"""


def apply_round040_original_async_lease(path: str, composed: str) -> str:
    """Add real original dispatch witness plus synthetic original C KUnit negatives."""
    if path != "mm/page_io.c":
        return composed
    handler = "static void swap_bdev_submit_write(struct swap_io_ctx *ctx)\n"
    composed = replace_once(
        composed, handler, ROUND040_ORIGINAL_ASYNC_LEASE_C + "\n" + handler,
        path, "round040-original-post-put-lease-negative")
    return replace_once(
        composed, ROUND037_MM_OWNER_HOOK,
        ROUND037_MM_OWNER_HOOK + ROUND040_ORIGINAL_ASYNC_LEASE_HOOK,
        path, "round040-original-post-put-dispatch-hook")


# Round041 original source backing/typed slot/nonlinear swapfile sector versus
# UNKNOWN current downstream DM target logical interval. ORIGINAL C negative only.
ROUND041_ORIGINAL_SECTOR_DOMAIN_MACRO = "SWAPZ_ROUND041_ORIGINAL_SECTOR_TO_DM_NONAUTHORITY_TEST"
ROUND041_ORIGINAL_SECTOR_DOMAIN_C = r"""#if defined(SWAPZ_ROUND041_ORIGINAL_SECTOR_TO_DM_NONAUTHORITY_TEST) && \
    defined(SWAPZ_ROUND040_ORIGINAL_ASYNC_SLOT_LEASE_NEGATIVE_TEST) && \
    defined(SWAPZ_ROUND038_ORIGINAL_STORE_PROVENANCE_TEST) && \
    defined(SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST) && \
    defined(SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
/* ROUND041_ORIGINAL_SECTOR_DOMAIN_C_BEGIN */
/*
 * All source measurements are ORIGINAL MM-only, one synchronous area-users
 * ref scope. A packed typed swap entry is not a sector. The original
 * nonlinear swapfile sector is not a downstream DM-relative sector,
 * DM target table identity, GC ownership or allocation-incarnation lease.
 * No real DM target is available to the source-only diagnostic.
 * The check must fail closed even for a fully fabricated positive witness.
 */
struct swapz_round041_sector_domain_evidence {
	u64 source_swap_entry;
	u64 candidate_swap_entry;
	u64 source_slot_offset;
	u64 candidate_slot_offset;
	u64 source_slot_epoch;
	u64 candidate_slot_epoch;
	u64 source_area_generation;
	u64 candidate_area_generation;
	const void *source_area_identity;
	const void *candidate_area_identity;
	const void *source_bdev_identity;
	const void *candidate_source_bdev_identity;
	u64 original_backing_sector;
	u64 original_bio_sector;
	u64 candidate_original_backing_sector;
	u64 dm_target_begin;
	u64 dm_target_length;
	u64 claimed_dm_relative_sector;
	const void *current_dm_target_identity;
	const void *claimed_dm_target_identity;
	u64 current_dm_map_generation;
	u64 claimed_dm_map_generation;
	u64 current_dm_gc_generation;
	u64 claimed_dm_gc_generation;
	u32 original_upper_bio_bytes;
	u32 original_upper_bvec_bytes;
	u32 original_upper_bvec_offset;
	u32 original_upper_bi_vcnt;
	bool original_upper_req_swap_write;
	bool genuine_source_bio_owner;
	bool area_ref_released_before_submit;
	bool current_allocation_incarnation_ref_held;
	bool current_dm_target_ref_held;
	bool current_dm_gc_ref_held;
	bool target_tearing_down;
};

/* ROUND041_ORIGINAL_SECTOR_DOMAIN_PURE_C_BEGIN */
static int swapz_round041_sector_domain_refuse(
		const struct swapz_round041_sector_domain_evidence *evidence)
{
	/* Exact 4096-byte original upper page, 512-byte Linux BIO sectors. */
	const u64 sectors_per_page = 4096U / 512U;
	const u64 maximum_sector = (u64)-1;
	u64 swap_offset_linear_sector;
	u64 target_end;

	if (!evidence)
		return -EINVAL;
	if (!evidence->source_swap_entry || !evidence->candidate_swap_entry ||
	    evidence->source_swap_entry != evidence->candidate_swap_entry ||
	    !evidence->source_slot_epoch || !evidence->candidate_slot_epoch ||
	    evidence->source_slot_epoch != evidence->candidate_slot_epoch ||
	    evidence->source_slot_offset != evidence->candidate_slot_offset)
		return -ESTALE;
	if (evidence->source_slot_offset > maximum_sector / sectors_per_page)
		return -ERANGE;
	/*
	 * This checked calculation is intentionally NOT an actual physical
	 * extent lookup: swap_folio_sector() uses original swap_extents,
	 * where start_block + (offset - start_page) may be NONLINEAR.
	 * It is never a DM target relative sector or an authority token.
	 */
	swap_offset_linear_sector =
		evidence->source_slot_offset * sectors_per_page;
	if (evidence->source_area_generation &&
	    evidence->candidate_area_generation &&
	    evidence->source_area_generation !=
		    evidence->candidate_area_generation)
		return -ESTALE;
	if (!evidence->source_area_identity ||
	    evidence->source_area_identity != evidence->candidate_area_identity ||
	    !evidence->source_bdev_identity ||
	    evidence->source_bdev_identity !=
		    evidence->candidate_source_bdev_identity)
		return -ESTALE;
	if (!evidence->original_backing_sector ||
	    (evidence->original_backing_sector & (sectors_per_page - 1U)) ||
	    evidence->original_backing_sector >
		    maximum_sector - sectors_per_page)
		return -ERANGE;
	if (evidence->original_backing_sector != evidence->original_bio_sector ||
	    evidence->original_backing_sector !=
		    evidence->candidate_original_backing_sector)
		return -ESTALE;
	/*
	 * ORIGINAL upper single prepopulated bvec can have bi_vcnt == 0.
	 * Its logical WRITE is still eight sectors of UNCOMPRESSED 4096.
	 */
	if (evidence->original_upper_bio_bytes != 4096U ||
	    evidence->original_upper_bvec_bytes != 4096U ||
	    evidence->original_upper_bvec_offset != 0U ||
	    evidence->original_upper_bi_vcnt != 0U ||
	    !evidence->original_upper_req_swap_write)
		return -EOPNOTSUPP;
	if (!evidence->genuine_source_bio_owner ||
	    !evidence->area_ref_released_before_submit)
		return -ESTALE;
	/*
	 * Original MM has NO real DM target reference or relative begin/len.
	 * Even an original sector numerically EQUAL to a fake DM sector is
	 * a comparison across unrelated address-space and lifetime domains.
	 */
	if (!evidence->current_dm_target_identity ||
	    !evidence->claimed_dm_target_identity)
		return -EOPNOTSUPP;
	if (evidence->current_dm_target_identity !=
	    evidence->claimed_dm_target_identity)
		return -ESTALE;
	if (!evidence->dm_target_length ||
	    evidence->dm_target_begin >
		    maximum_sector - evidence->dm_target_length)
		return -ERANGE;
	target_end = evidence->dm_target_begin + evidence->dm_target_length;
	if (evidence->dm_target_length < sectors_per_page ||
	    (evidence->claimed_dm_relative_sector &
	     (sectors_per_page - 1U)) ||
	    evidence->claimed_dm_relative_sector <
		    evidence->dm_target_begin ||
	    evidence->claimed_dm_relative_sector >
		    target_end - sectors_per_page)
		return -ERANGE;
	if ((evidence->current_dm_map_generation &&
	     evidence->claimed_dm_map_generation &&
	     evidence->current_dm_map_generation !=
		     evidence->claimed_dm_map_generation) ||
	    (evidence->current_dm_gc_generation &&
	     evidence->claimed_dm_gc_generation &&
	     evidence->current_dm_gc_generation !=
		     evidence->claimed_dm_gc_generation))
		return -ESTALE;
	if (evidence->target_tearing_down ||
	    !evidence->current_allocation_incarnation_ref_held ||
	    !evidence->current_dm_target_ref_held ||
	    !evidence->current_dm_gc_ref_held ||
	    !evidence->current_dm_map_generation ||
	    !evidence->current_dm_gc_generation)
		return -EOPNOTSUPP;
	/*
	 * A checked linear swap-offset sector, nonlinear original backing
	 * sector and forged current DM target LBA CAN coincide numerically.
	 * None is the same ownership domain. Never emit a positive lease.
	 */
	(void)swap_offset_linear_sector;
	return -EOPNOTSUPP;
}
/* ROUND041_ORIGINAL_SECTOR_DOMAIN_PURE_C_END */

/*
 * This is actual pristine-original mm/page_io.c WRITE dispatch, nested
 * behind the prior 040 + older original CI guards. All area fields are
 * read only WHILE a newly acquired real get_swap_device() users ref lives.
 * On EVERY successful acquisition, put_swap_device() executes EXACTLY
 * ONCE before the value-only negative check. No pointer dereference
 * after put; no source swapentry->DM map or token is exported.
 */
static noinline int swapz_round041_original_mm_sector_domain_probe(
		const struct swap_io_ctx *ctx, const struct bio *source_bio,
		struct folio *folio)
{
	struct swapz_round041_sector_domain_evidence evidence = {};
	struct swap_info_struct *active_area;
	swp_entry_t original_slot;

	if (!ctx || !ctx->sis || !source_bio || !folio ||
	    !source_bio->bi_swapz_ci_sideband ||
	    !folio_test_swapcache(folio) || !folio_test_writeback(folio) ||
	    folio_test_locked(folio))
		return -ESTALE;
	original_slot = folio_swap_entry(folio, 0);
	if (!original_slot.val || swp_type(original_slot) >= MAX_SWAPFILES)
		return -ESTALE;
	active_area = get_swap_device(original_slot);
	if (IS_ERR_OR_NULL(active_area))
		return -ESTALE;
	if (active_area != ctx->sis || !active_area->bdev ||
	    !source_bio->bi_io_vec ||
	    !source_bio->bi_io_vec[0].bv_page)
		goto put_area;

	evidence.source_swap_entry = (u64)original_slot.val;
	evidence.candidate_swap_entry =
		(u64)ctx->swapz_round035_original_slot.val;
	evidence.source_slot_offset = (u64)swp_offset(original_slot);
	evidence.candidate_slot_offset =
		(u64)swp_offset(ctx->swapz_round035_original_slot);
	evidence.source_slot_epoch =
		swapz_round028_slot_epoch(original_slot);
	evidence.candidate_slot_epoch =
		ctx->swapz_round035_original_epoch;
	evidence.source_area_identity = active_area;
	evidence.candidate_area_identity = ctx->sis;
	evidence.source_bdev_identity = active_area->bdev;
	evidence.candidate_source_bdev_identity = source_bio->bi_bdev;
	evidence.original_backing_sector = (u64)swap_folio_sector(folio);
	evidence.original_bio_sector = (u64)source_bio->bi_iter.bi_sector;
	evidence.candidate_original_backing_sector =
		(u64)source_bio->bi_iter.bi_sector;
	evidence.original_upper_bio_bytes = source_bio->bi_iter.bi_size;
	evidence.original_upper_bvec_bytes =
		source_bio->bi_io_vec[0].bv_len;
	evidence.original_upper_bvec_offset =
		source_bio->bi_io_vec[0].bv_offset;
	evidence.original_upper_bi_vcnt = source_bio->bi_vcnt;
	evidence.original_upper_req_swap_write =
		bio_op(source_bio) == REQ_OP_WRITE &&
		(source_bio->bi_opf & REQ_SWAP) != 0U;
	evidence.genuine_source_bio_owner =
		swapz_round035_bio_owner_matches(
			source_bio, (u64)original_slot.val,
			evidence.source_slot_epoch);
put_area:
	/* No original swap_info_struct dereference after this real put. */
	put_swap_device(active_area);
	if (!evidence.source_area_identity)
		return -ESTALE;
	evidence.area_ref_released_before_submit = true;
	/* Real original MM C has NO current DM target begin/len/GC lease:
	 * all fake target identity/generation/refs stay ZERO.
	 */
	return swapz_round041_sector_domain_refuse(&evidence);
}

/* All mock source+DM area values in KUnit are SYNTHETIC; no live target. */
static void swapz_round041_sector_domain_fixture(
		struct swapz_round041_sector_domain_evidence *evidence)
{
	memset(evidence, 0, sizeof(*evidence));
	evidence->source_swap_entry = (u64)swp_entry(1U, 37U).val;
	evidence->candidate_swap_entry = evidence->source_swap_entry;
	evidence->source_slot_offset = 37U;
	evidence->candidate_slot_offset = 37U;
	evidence->source_slot_epoch = 17U;
	evidence->candidate_slot_epoch = 17U;
	evidence->source_area_generation = 3U; /* MOCK only. */
	evidence->candidate_area_generation = 3U;
	evidence->source_area_identity = evidence;
	evidence->candidate_area_identity = evidence;
	evidence->source_bdev_identity = &evidence->original_backing_sector;
	evidence->candidate_source_bdev_identity =
		&evidence->original_backing_sector;
	evidence->original_backing_sector = 4096U;
	evidence->original_bio_sector = 4096U;
	evidence->candidate_original_backing_sector = 4096U;
	evidence->dm_target_begin = 128U;
	evidence->dm_target_length = 512U;
	evidence->claimed_dm_relative_sector = 296U;
	evidence->current_dm_target_identity = &evidence->dm_target_begin;
	evidence->claimed_dm_target_identity = &evidence->dm_target_begin;
	evidence->current_dm_map_generation = 4U;
	evidence->claimed_dm_map_generation = 4U;
	evidence->current_dm_gc_generation = 5U;
	evidence->claimed_dm_gc_generation = 5U;
	evidence->original_upper_bio_bytes = 4096U;
	evidence->original_upper_bvec_bytes = 4096U;
	evidence->original_upper_req_swap_write = true;
	evidence->genuine_source_bio_owner = true; /* Synthetic claim. */
	evidence->area_ref_released_before_submit = true;
	evidence->current_allocation_incarnation_ref_held = true; /* Forged. */
	evidence->current_dm_target_ref_held = true; /* Forged. */
	evidence->current_dm_gc_ref_held = true; /* Forged. */
}

static void swapz_round041_nonlinear_swapfile_sector_kunit(struct kunit *test)
{
	struct swapz_round041_sector_domain_evidence evidence;

	swapz_round041_sector_domain_fixture(&evidence);
	KUNIT_EXPECT_NE(test, evidence.original_backing_sector,
			evidence.source_slot_offset * 8U);
	KUNIT_EXPECT_NE(test, evidence.original_backing_sector,
			evidence.claimed_dm_relative_sector);
	KUNIT_EXPECT_EQ(test, swapz_round041_sector_domain_refuse(&evidence),
			-EOPNOTSUPP);
	evidence.original_bio_sector = evidence.source_slot_offset * 8U;
	KUNIT_EXPECT_EQ(test, swapz_round041_sector_domain_refuse(&evidence),
			-ESTALE);
}

static void swapz_round041_same_numeric_different_bdev_target_kunit(
		struct kunit *test)
{
	struct swapz_round041_sector_domain_evidence evidence;

	swapz_round041_sector_domain_fixture(&evidence);
	evidence.dm_target_begin = 4000U;
	evidence.dm_target_length = 512U;
	evidence.claimed_dm_relative_sector = 4096U;
	KUNIT_EXPECT_EQ(test, swapz_round041_sector_domain_refuse(&evidence),
			-EOPNOTSUPP); /* Same number NEVER grants authority. */
	evidence.candidate_source_bdev_identity = test;
	KUNIT_EXPECT_EQ(test, swapz_round041_sector_domain_refuse(&evidence),
			-ESTALE);
	evidence.candidate_source_bdev_identity = evidence.source_bdev_identity;
	evidence.claimed_dm_target_identity = test;
	KUNIT_EXPECT_EQ(test, swapz_round041_sector_domain_refuse(&evidence),
			-ESTALE);
}

static void swapz_round041_typed_slot_swapoff_area_aba_kunit(struct kunit *test)
{
	struct swapz_round041_sector_domain_evidence evidence;

	swapz_round041_sector_domain_fixture(&evidence);
	evidence.candidate_swap_entry = (u64)swp_entry(2U, 37U).val;
	KUNIT_EXPECT_EQ(test, swapz_round041_sector_domain_refuse(&evidence),
			-ESTALE);
	evidence.candidate_swap_entry = evidence.source_swap_entry;
	evidence.candidate_slot_epoch++;
	KUNIT_EXPECT_EQ(test, swapz_round041_sector_domain_refuse(&evidence),
			-ESTALE);
	evidence.candidate_slot_epoch = evidence.source_slot_epoch;
	evidence.candidate_area_generation++;
	KUNIT_EXPECT_EQ(test, swapz_round041_sector_domain_refuse(&evidence),
			-ESTALE);
	evidence.candidate_area_generation = evidence.source_area_generation;
	evidence.area_ref_released_before_submit = false;
	KUNIT_EXPECT_EQ(test, swapz_round041_sector_domain_refuse(&evidence),
			-ESTALE);
}

static void swapz_round041_single_bvec_interval_overflow_kunit(struct kunit *test)
{
	struct swapz_round041_sector_domain_evidence evidence;

	swapz_round041_sector_domain_fixture(&evidence);
	evidence.dm_target_begin = 256U;
	evidence.dm_target_length = 8U;
	evidence.claimed_dm_relative_sector = 256U; /* End-exclusive 264. */
	/* bi_vcnt==0 is VALID for original prepopulated single bvec. */
	KUNIT_EXPECT_EQ(test, evidence.original_upper_bi_vcnt, 0U);
	KUNIT_EXPECT_EQ(test, swapz_round041_sector_domain_refuse(&evidence),
			-EOPNOTSUPP);
	evidence.dm_target_length = 7U;
	KUNIT_EXPECT_EQ(test, swapz_round041_sector_domain_refuse(&evidence),
			-ERANGE);
	evidence.dm_target_length = 8U;
	evidence.dm_target_begin = (u64)-4;
	KUNIT_EXPECT_EQ(test, swapz_round041_sector_domain_refuse(&evidence),
			-ERANGE);
	evidence.dm_target_begin = 256U;
	evidence.claimed_dm_relative_sector = (u64)-8;
	KUNIT_EXPECT_EQ(test, swapz_round041_sector_domain_refuse(&evidence),
			-ERANGE);
	evidence.claimed_dm_relative_sector = 256U;
	evidence.original_upper_bvec_bytes = 2048U;
	KUNIT_EXPECT_EQ(test, swapz_round041_sector_domain_refuse(&evidence),
			-EOPNOTSUPP);
	evidence.original_upper_bvec_bytes = 4096U;
	evidence.source_slot_offset = (u64)-1;
	evidence.candidate_slot_offset = (u64)-1;
	KUNIT_EXPECT_EQ(test, swapz_round041_sector_domain_refuse(&evidence),
			-ERANGE);
}

static void swapz_round041_wrong_partition_gc_teardown_kunit(struct kunit *test)
{
	struct swapz_round041_sector_domain_evidence evidence;
	struct swapz_round041_sector_domain_evidence unchanged;

	swapz_round041_sector_domain_fixture(&evidence);
	evidence.candidate_area_identity = test;
	KUNIT_EXPECT_EQ(test, swapz_round041_sector_domain_refuse(&evidence),
			-ESTALE);
	evidence.candidate_area_identity = evidence.source_area_identity;
	evidence.claimed_dm_gc_generation++;
	KUNIT_EXPECT_EQ(test, swapz_round041_sector_domain_refuse(&evidence),
			-ESTALE);
	evidence.claimed_dm_gc_generation = evidence.current_dm_gc_generation;
	evidence.target_tearing_down = true;
	KUNIT_EXPECT_EQ(test, swapz_round041_sector_domain_refuse(&evidence),
			-EOPNOTSUPP);
	evidence.target_tearing_down = false;
	evidence.current_dm_target_identity = NULL; /* Real original source. */
	KUNIT_EXPECT_EQ(test, swapz_round041_sector_domain_refuse(&evidence),
			-EOPNOTSUPP);
	evidence.current_dm_target_identity = &evidence.dm_target_begin;
	unchanged = evidence;
	KUNIT_EXPECT_EQ(test, swapz_round041_sector_domain_refuse(&evidence),
			-EOPNOTSUPP);
	KUNIT_EXPECT_EQ(test, memcmp(&evidence, &unchanged,
				    sizeof(evidence)), 0);
	KUNIT_EXPECT_EQ(test, swapz_round041_sector_domain_refuse(NULL),
			-EINVAL);
}

static struct kunit_case swapz_round041_sector_domain_cases[] = {
	KUNIT_CASE(swapz_round041_nonlinear_swapfile_sector_kunit),
	KUNIT_CASE(swapz_round041_same_numeric_different_bdev_target_kunit),
	KUNIT_CASE(swapz_round041_typed_slot_swapoff_area_aba_kunit),
	KUNIT_CASE(swapz_round041_single_bvec_interval_overflow_kunit),
	KUNIT_CASE(swapz_round041_wrong_partition_gc_teardown_kunit),
	{}
};

static struct kunit_suite swapz_round041_sector_domain_suite = {
	.name = "swapz_round041_original_sector_domain_no_authority",
	.test_cases = swapz_round041_sector_domain_cases,
};
kunit_test_suite(swapz_round041_sector_domain_suite);
/* ROUND041_ORIGINAL_SECTOR_DOMAIN_C_END */
#endif /* Guarded ORIGINAL source 041 sector/target negative, NO LIVE AUTH */
"""
ROUND041_ORIGINAL_SECTOR_DOMAIN_HOOK = r"""#if defined(SWAPZ_ROUND041_ORIGINAL_SECTOR_TO_DM_NONAUTHORITY_TEST) && \
    defined(SWAPZ_ROUND040_ORIGINAL_ASYNC_SLOT_LEASE_NEGATIVE_TEST) && \
    defined(SWAPZ_ROUND038_ORIGINAL_STORE_PROVENANCE_TEST) && \
    defined(SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST) && \
    defined(SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
	/* Previous Round037+040 original scoped area refs were already put.
	 * This private source-only probe also releases its OWN real area ref
	 * before any asynchronous submission, without source->DM authority.
	 */
	if (bio->bi_swapz_ci_sideband)
		(void)swapz_round041_original_mm_sector_domain_probe(
			ctx, bio, bio_first_folio_all(bio));
#endif
"""


def apply_round041_original_sector_domain(path: str, composed: str) -> str:
    """Introduce actual original page_io.c guarded source-sector negative tests."""
    if path != "mm/page_io.c":
        return composed
    handler = "static void swap_bdev_submit_write(struct swap_io_ctx *ctx)\n"
    composed = replace_once(
        composed, handler, ROUND041_ORIGINAL_SECTOR_DOMAIN_C + "\n" + handler,
        path, "round041-original-source-sector-no-dm-authority")
    return replace_once(
        composed, ROUND040_ORIGINAL_ASYNC_LEASE_HOOK,
        ROUND040_ORIGINAL_ASYNC_LEASE_HOOK + ROUND041_ORIGINAL_SECTOR_DOMAIN_HOOK,
        path, "round041-original-after-area-put-dispatch-hook")


# Round042 genuine ORIGINAL zswap_writeback_entry source before xa_erase/free.
# All guards are default UNDEFINED. No live source/DM positive authority.
ROUND042_ORIGINAL_STORED_WRITEBACK_MACRO = "SWAPZ_ROUND042_ORIGINAL_STORED_WRITEBACK_LIFETIME_TEST"
ROUND042_ORIGINAL_STORED_WRITEBACK_C = r"""#if defined(SWAPZ_ROUND042_ORIGINAL_STORED_WRITEBACK_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND041_ORIGINAL_SECTOR_TO_DM_NONAUTHORITY_TEST) && \
    defined(SWAPZ_ROUND040_ORIGINAL_ASYNC_SLOT_LEASE_NEGATIVE_TEST) && \
    defined(SWAPZ_ROUND038_ORIGINAL_STORE_PROVENANCE_TEST) && \
    defined(SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST) && \
    defined(SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
/* ROUND042_ORIGINAL_STORED_WRITEBACK_C_BEGIN */
/*
 * ORIGINAL mm/zswap.c C only. Entries are legal to dereference ONLY while
 * original locked swapcache folio and xarray identity still pin the current
 * zswap entry. A separately refcounted copied BIO owner is not an allocation
 * incarnation or live downstream DM target/extent/GC ownership lease.
 * All post-erase/free observations contain values ONLY, not zpool pointers.
 */
struct swapz_round042_stored_writeback_observation {
	u64 source_swap_entry;
	u64 current_swap_entry;
	u64 source_allocation_epoch;
	u64 current_allocation_epoch;
	u64 source_stored_identity;
	u64 current_stored_identity;
	u32 original_store_crc32c;
	u32 copied_source_crc32c;
	u32 compressed_length;
	u32 decoded_length;
	bool original_xarray_matches;
	bool folio_locked;
	bool folio_swapcache;
	bool original_decompressed_to_folio;
	bool copied_payload_independently_owned;
	bool original_entry_erased;
	bool original_entry_freed;
	bool original_folio_writeback_started;
	bool delayed_bio_completion;
	bool original_swap_area_ref_held;
	bool allocation_incarnation_ref_held;
	bool current_dm_target_gc_ref_held;
};

/* ROUND042_ORIGINAL_STORED_WRITEBACK_PURE_C_BEGIN */
static int swapz_round042_stored_writeback_refuse(
		const struct swapz_round042_stored_writeback_observation *observation)
{
	if (!observation)
		return -EINVAL;
	if (!observation->source_swap_entry ||
	    observation->source_swap_entry != observation->current_swap_entry ||
	    !observation->source_allocation_epoch ||
	    observation->source_allocation_epoch !=
		    observation->current_allocation_epoch ||
	    !observation->source_stored_identity ||
	    observation->source_stored_identity !=
		    observation->current_stored_identity ||
	    !observation->original_xarray_matches)
		return -ESTALE;
	/* Original STORE SHA remains in an independently owned original BIO
	 * byte-view; CRC binds original STORE compressed bytes, not current
	 * allocation incarnation or current DM map lifetime.
	 */
	if (!observation->original_store_crc32c ||
	    observation->original_store_crc32c !=
		    observation->copied_source_crc32c)
		return -ESTALE;
	if (!observation->compressed_length ||
	    observation->compressed_length > 3568U ||
	    observation->decoded_length != 4096U)
		return -ERANGE;
	if (!observation->folio_locked ||
	    !observation->folio_swapcache ||
	    !observation->original_decompressed_to_folio)
		return -ESTALE;
	/* After xa_erase / zswap_entry_free, no source entry pointer or
	 * zpool handle may be borrowed, regardless of copied BIO refcount.
	 */
	if (observation->original_entry_erased !=
	    observation->original_entry_freed)
		return -ESTALE;
	if (!observation->copied_payload_independently_owned ||
	    observation->delayed_bio_completion ||
	    observation->original_entry_freed ||
	    observation->original_folio_writeback_started)
		return -EOPNOTSUPP;
	/* Even every manufactured ref would lack a real authenticated
	 * original allocation+current DM target/extent/GC joined lease.
	 */
	return -EOPNOTSUPP;
}
/* ROUND042_ORIGINAL_STORED_WRITEBACK_PURE_C_END */

/* The ORIGINAL evictor invokes this only before xa_erase and free, while
 * the genuine locked folio and current xarray make entry dereference safe.
 * No GFP allocation, borrowed pointer escape, new ref, export, BIO mutation,
 * extra reclaim policy or IO; mark all downstream identity as UNKNOWN.
 */
static noinline int swapz_round042_original_stored_writeback_probe(
		struct zswap_entry *entry, swp_entry_t original_slot,
		struct xarray *tree, pgoff_t offset, struct folio *folio,
		const struct swap_io_ctx *ctx,
		struct swapz_round042_stored_writeback_observation *observation)
{
	if (!entry || !tree || !folio || !ctx || !observation ||
	    entry != xa_load(tree, offset) ||
	    entry->swpentry.val != original_slot.val ||
	    !folio_test_locked(folio) || !folio_test_swapcache(folio))
		return -ESTALE;
	observation->source_swap_entry = (u64)entry->swpentry.val;
	observation->current_swap_entry = (u64)original_slot.val;
	observation->source_allocation_epoch =
		entry->swapz_round028_allocation_epoch;
	observation->current_allocation_epoch =
		swapz_round028_slot_epoch(original_slot);
	observation->source_stored_identity =
		entry->swapz_round028_stored_entry_identity;
	observation->current_stored_identity =
		entry->swapz_round028_stored_entry_identity;
	observation->original_store_crc32c =
		entry->swapz_round038_store_crc32c;
	observation->copied_source_crc32c =
		ctx->swapz_round031_owned &&
		entry->swapz_round038_store_compressed ?
		entry->swapz_round038_store_crc32c : 0U;
	observation->compressed_length = (u32)entry->length;
	observation->decoded_length = 4096U;
	observation->original_xarray_matches = true;
	observation->folio_locked = true;
	observation->folio_swapcache = true;
	observation->original_decompressed_to_folio = true;
	observation->copied_payload_independently_owned =
		ctx->swapz_round031_owned != NULL;
	/* A real independent owner exists for payload bytes only; the
	 * original temporary swap AREA users ref was ALREADY put.
	 * No real current slot-incarnation or DM target/GC lease exists.
	 */
	return swapz_round042_stored_writeback_refuse(observation);
}

static void swapz_round042_writeback_fixture(
		struct swapz_round042_stored_writeback_observation *observation)
{
	memset(observation, 0, sizeof(*observation));
	observation->source_swap_entry = (u64)swp_entry(1U, 37U).val;
	observation->current_swap_entry = observation->source_swap_entry;
	observation->source_allocation_epoch = 17U;
	observation->current_allocation_epoch = 17U;
	observation->source_stored_identity = 29U;
	observation->current_stored_identity = 29U;
	observation->original_store_crc32c = 0xa19be32fU;
	observation->copied_source_crc32c = 0xa19be32fU;
	observation->compressed_length = 912U;
	observation->decoded_length = 4096U;
	observation->original_xarray_matches = true;
	observation->folio_locked = true;
	observation->folio_swapcache = true;
	observation->original_decompressed_to_folio = true;
	observation->copied_payload_independently_owned = true;
}

/* These four KUnit scenarios are SYNTHETIC value-only, NOT real pressure. */
static void swapz_round042_xarray_stale_typed_slot_kunit(struct kunit *test)
{
	struct swapz_round042_stored_writeback_observation observation;

	swapz_round042_writeback_fixture(&observation);
	observation.original_xarray_matches = false;
	KUNIT_EXPECT_EQ(test, swapz_round042_stored_writeback_refuse(&observation),
			-ESTALE);
	observation.original_xarray_matches = true;
	observation.current_swap_entry = (u64)swp_entry(2U, 37U).val;
	KUNIT_EXPECT_EQ(test, swapz_round042_stored_writeback_refuse(&observation),
			-ESTALE);
}

static void swapz_round042_store_identity_epoch_crc_kunit(struct kunit *test)
{
	struct swapz_round042_stored_writeback_observation observation;

	swapz_round042_writeback_fixture(&observation);
	observation.current_stored_identity++;
	KUNIT_EXPECT_EQ(test, swapz_round042_stored_writeback_refuse(&observation),
			-ESTALE);
	observation.current_stored_identity = observation.source_stored_identity;
	observation.current_allocation_epoch++;
	KUNIT_EXPECT_EQ(test, swapz_round042_stored_writeback_refuse(&observation),
			-ESTALE);
	observation.current_allocation_epoch = observation.source_allocation_epoch;
	observation.copied_source_crc32c++;
	KUNIT_EXPECT_EQ(test, swapz_round042_stored_writeback_refuse(&observation),
			-ESTALE);
}

static void swapz_round042_owned_copy_after_free_kunit(struct kunit *test)
{
	struct swapz_round042_stored_writeback_observation observation;
	struct swapz_round042_stored_writeback_observation original;

	swapz_round042_writeback_fixture(&observation);
	original = observation;
	KUNIT_EXPECT_EQ(test, swapz_round042_stored_writeback_refuse(&observation),
			-EOPNOTSUPP);
	KUNIT_EXPECT_EQ(test, memcmp(&observation, &original,
				    sizeof(observation)), 0);
	observation.original_entry_erased = true;
	KUNIT_EXPECT_EQ(test, swapz_round042_stored_writeback_refuse(&observation),
			-ESTALE);
	observation.original_entry_freed = true;
	KUNIT_EXPECT_EQ(test, swapz_round042_stored_writeback_refuse(&observation),
			-EOPNOTSUPP);
	observation.copied_payload_independently_owned = false;
	KUNIT_EXPECT_EQ(test, swapz_round042_stored_writeback_refuse(&observation),
			-EOPNOTSUPP);
}

static void swapz_round042_post_erase_late_completion_kunit(struct kunit *test)
{
	struct swapz_round042_stored_writeback_observation observation;

	swapz_round042_writeback_fixture(&observation);
	observation.original_entry_erased = true;
	observation.original_entry_freed = true;
	observation.original_folio_writeback_started = true;
	observation.delayed_bio_completion = true;
	KUNIT_EXPECT_EQ(test, swapz_round042_stored_writeback_refuse(&observation),
			-EOPNOTSUPP);
	observation.original_swap_area_ref_held = true;
	observation.allocation_incarnation_ref_held = true;
	observation.current_dm_target_gc_ref_held = true;
	KUNIT_EXPECT_EQ(test, swapz_round042_stored_writeback_refuse(&observation),
			-EOPNOTSUPP);
	observation.current_swap_entry = 0U;
	KUNIT_EXPECT_EQ(test, swapz_round042_stored_writeback_refuse(&observation),
			-ESTALE);
	KUNIT_EXPECT_EQ(test, swapz_round042_stored_writeback_refuse(NULL),
			-EINVAL);
}

static struct kunit_case swapz_round042_stored_writeback_cases[] = {
	KUNIT_CASE(swapz_round042_xarray_stale_typed_slot_kunit),
	KUNIT_CASE(swapz_round042_store_identity_epoch_crc_kunit),
	KUNIT_CASE(swapz_round042_owned_copy_after_free_kunit),
	KUNIT_CASE(swapz_round042_post_erase_late_completion_kunit),
	{}
};
static struct kunit_suite swapz_round042_stored_writeback_suite = {
	.name = "swapz_round042_original_stored_writeback_no_authority",
	.test_cases = swapz_round042_stored_writeback_cases,
};
kunit_test_suite(swapz_round042_stored_writeback_suite);
/* ROUND042_ORIGINAL_STORED_WRITEBACK_C_END */
#endif /* Original source only, no REAL compressed handoff */
"""


def apply_round042_original_stored_writeback(path: str, composed: str) -> str:
    """Add original zswap eviction ownership-boundary observation, no IO."""
    if path != "mm/zswap.c":
        return composed
    declaration = "\tstruct swap_io_ctx ctx = {};\n"
    composed = replace_once(composed, declaration, declaration + r"""#if defined(SWAPZ_ROUND042_ORIGINAL_STORED_WRITEBACK_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND041_ORIGINAL_SECTOR_TO_DM_NONAUTHORITY_TEST) && \
    defined(SWAPZ_ROUND040_ORIGINAL_ASYNC_SLOT_LEASE_NEGATIVE_TEST) && \
    defined(SWAPZ_ROUND038_ORIGINAL_STORE_PROVENANCE_TEST) && \
    defined(SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST) && \
    defined(SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
	struct swapz_round042_stored_writeback_observation
		swapz_round042_source_observation = {};
#endif
""", path, "round042-original-eviction-owned-scalar")
    before_entry = "static int zswap_writeback_entry(struct zswap_entry *entry,\n"
    composed = replace_once(composed, before_entry,
                            ROUND042_ORIGINAL_STORED_WRITEBACK_C +
                            "\n" + before_entry,
                            path, "round042-original-eviction-source-c")
    erase = "\txa_erase(tree, offset);\n\n\tcount_vm_event(ZSWPWB);"
    composed = replace_once(composed, erase, r"""#if defined(SWAPZ_ROUND042_ORIGINAL_STORED_WRITEBACK_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND041_ORIGINAL_SECTOR_TO_DM_NONAUTHORITY_TEST) && \
    defined(SWAPZ_ROUND040_ORIGINAL_ASYNC_SLOT_LEASE_NEGATIVE_TEST) && \
    defined(SWAPZ_ROUND038_ORIGINAL_STORE_PROVENANCE_TEST) && \
    defined(SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST) && \
    defined(SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
	/* The TRUE ORIGINAL folio remains locked and xarray still matches.
	 * Only COPY observed scalars while original zswap_entry is valid.
	 */
	(void)swapz_round042_original_stored_writeback_probe(
		entry, swpentry, tree, offset, folio, &ctx,
		&swapz_round042_source_observation);
#endif
""" + erase, path, "round042-original-before-xarray-erase")
    freed = "\tzswap_entry_free(entry);\n\n\t/* folio is up to date */"
    composed = replace_once(composed, freed, "\tzswap_entry_free(entry);\n" +
                            r"""#if defined(SWAPZ_ROUND042_ORIGINAL_STORED_WRITEBACK_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND041_ORIGINAL_SECTOR_TO_DM_NONAUTHORITY_TEST) && \
    defined(SWAPZ_ROUND040_ORIGINAL_ASYNC_SLOT_LEASE_NEGATIVE_TEST) && \
    defined(SWAPZ_ROUND038_ORIGINAL_STORE_PROVENANCE_TEST) && \
    defined(SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST) && \
    defined(SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
	/* AFTER REAL zswap_entry_free(): NO entry/zpool dereference.
	 * Only local scalar evidence, no ref transfer or positive route.
	 */
	swapz_round042_source_observation.original_entry_erased = true;
	swapz_round042_source_observation.original_entry_freed = true;
	(void)swapz_round042_stored_writeback_refuse(
		&swapz_round042_source_observation);
#endif
""" + "\n\t/* folio is up to date */",
                            path, "round042-original-post-free-scalar-only")
    return composed


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



# Round043 actual pinned original BIO clone owner: copy-only, default undefined.
ROUND043_ORIGINAL_BIO_CLONE_MACRO = "SWAPZ_ROUND043_ORIGINAL_BIO_CLONE_COPY_TEST"
ROUND043_ORIGINAL_BIO_CLONE_SOURCE = r"""#if defined(SWAPZ_ROUND043_ORIGINAL_BIO_CLONE_COPY_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
/* ROUND043_ORIGINAL_BIO_CLONE_COPY_C_BEGIN */
/* Copy-only observation. This bit is published exclusively after the real
 * __bio_clone() acquired its own immutable LZ4 owner ref, not from a
 * caller-supplied BIO_CLONED flag, a sector, or a guessed target identity.
 */
/* ROUND043_ORIGINAL_BIO_CLONE_PURE_C_BEGIN */
static noinline bool
swapz_round043_bio_clone_owner_is_independent(const struct bio *source_bio)
{
	if (!source_bio)
		return false;
	if (!(source_bio->bi_flags & (1U << BIO_CLONED)))
		return !source_bio->bi_swapz_ci_full_clone_owned;
	return source_bio->bi_swapz_ci_full_clone_owned &&
	       source_bio->bi_swapz_ci_sideband != NULL &&
	       source_bio->bi_vcnt == 0U &&
	       source_bio->bi_iter.bi_size == 4096U &&
	       source_bio->bi_iter.bi_idx == 0U &&
	       source_bio->bi_iter.bi_offset == 0U;
}
/* ROUND043_ORIGINAL_BIO_CLONE_PURE_C_END */
/* ROUND043_ORIGINAL_BIO_CLONE_COPY_C_END */
#endif
"""
ROUND043_ORIGINAL_BIO_CLONE_KUNIT = r"""#if defined(SWAPZ_ROUND043_ORIGINAL_BIO_CLONE_COPY_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
/* All inputs are SYNTHETIC, but these calls execute REAL pinned original
 * BIO clone/split/reset and sealed original LZ4 copy code in booted KUnit.
 * No source MM pressure, real DM target, lower IO or production authority.
 */
static void swapz_round043_full_clone_owned_lz4_copy_kunit(struct kunit *test)
{
	struct swapz_round034_v1_fixture *fixture =
		swapz_round034_v1_fixture_create(test);
	struct swapz_ci_lz4_owned_view_v1 view = {};
	struct swapz_ci_owned_payload *owner;
	struct bio clone = {};
	u8 decoded_sha[32];
	int error;

	KUNIT_ASSERT_NOT_NULL(test, fixture);
	owner = fixture->bio.bi_swapz_ci_sideband;
	KUNIT_ASSERT_NOT_NULL(test, owner);
	error = bio_init_clone(NULL, &clone, &fixture->bio, GFP_KERNEL);
	if (error) {
		KUNIT_FAIL(test, "real original clone acquisition failed");
		return;
	}
	KUNIT_EXPECT_EQ(test, refcount_read(&owner->references), 2);
	KUNIT_EXPECT_TRUE(test, clone.bi_swapz_ci_full_clone_owned);
	KUNIT_EXPECT_EQ(test, clone.bi_iter.bi_size, 4096U);
	KUNIT_EXPECT_EQ(test, clone.bi_vcnt, 0U);
	KUNIT_EXPECT_EQ(test, swapz_ci_bio_snapshot_lz4_v1(
		&clone, &view, fixture->destination, 3568U), 0);
	KUNIT_EXPECT_EQ(test, view.source_swap_entry, (u64)0x123456U);
	KUNIT_EXPECT_EQ(test, view.source_slot_epoch, (u64)11U);
	KUNIT_EXPECT_EQ(test, view.stored_entry_identity, (u64)13U);
	KUNIT_EXPECT_EQ(test, view.compressed_crc32c,
			~crc32c(~0U, fixture->compressed,
				fixture->compressed_length));
	KUNIT_EXPECT_EQ(test, memcmp(view.original_sha256, fixture->digest,
				     sizeof(fixture->digest)), 0);
	KUNIT_EXPECT_EQ(test, memcmp(fixture->destination, fixture->compressed,
				     fixture->compressed_length), 0);
	/* Fixture retains the shared original bvec memory after parent uninit. */
	bio_uninit(&fixture->bio);
	fixture->bio_initialized = false;
	KUNIT_EXPECT_EQ(test, refcount_read(&owner->references), 1);
	KUNIT_EXPECT_EQ(test, swapz_ci_bio_snapshot_lz4_v1(
		&clone, &view, fixture->destination, 3568U), 0);
	error = LZ4_decompress_safe((const char *)fixture->destination,
				    (char *)fixture->decoded,
				    view.compressed_length, PAGE_SIZE);
	KUNIT_EXPECT_EQ(test, error, (int)PAGE_SIZE);
	if (error == PAGE_SIZE) {
		sha256(fixture->decoded, PAGE_SIZE, decoded_sha);
		KUNIT_EXPECT_EQ(test, memcmp(decoded_sha, view.original_sha256,
					     sizeof(decoded_sha)), 0);
	}
	bio_uninit(&clone);
	bio_uninit(&clone);
}

static void swapz_round043_split_or_consumed_clone_refused_kunit(struct kunit *test)
{
	struct swapz_round034_v1_fixture *fixture =
		swapz_round034_v1_fixture_create(test);
	struct swapz_ci_owned_payload *owner;
	struct swapz_ci_lz4_owned_view_v1 view;
	struct bio *split;
	u8 *destination;
	int error;

	KUNIT_ASSERT_NOT_NULL(test, fixture);
	/* Test-scoped heap scratch: never reserve 3568 bytes on kernel stack. */
	destination = kunit_kmalloc(test, 3568U, GFP_KERNEL);
	KUNIT_ASSERT_NOT_NULL(test, destination);
	owner = fixture->bio.bi_swapz_ci_sideband;
	KUNIT_ASSERT_NOT_NULL(test, owner);
	fixture->bio.bi_vcnt = 1; /* Original bio_split bvec walker. */
	split = bio_split(&fixture->bio, 4, GFP_KERNEL, &fs_bio_set);
	if (IS_ERR_OR_NULL(split)) {
		KUNIT_FAIL(test, "real original bio_split failed");
		return;
	}
	KUNIT_EXPECT_TRUE(test, split->bi_swapz_ci_full_clone_owned);
	KUNIT_EXPECT_EQ(test, refcount_read(&owner->references), 2);
	KUNIT_EXPECT_EQ(test, split->bi_iter.bi_size, 2048U);
	KUNIT_EXPECT_EQ(test, fixture->bio.bi_iter.bi_size, 2048U);
	memset(&view, 0xa5, sizeof(view));
	memset(destination, 0x6b, 3568U);
	error = swapz_ci_bio_snapshot_lz4_v1(
		split, &view, destination, 3568U);
	KUNIT_EXPECT_EQ(test, error, -EOPNOTSUPP);
	KUNIT_EXPECT_PTR_EQ(test, memchr_inv(&view, 0xa5, sizeof(view)), NULL);
	KUNIT_EXPECT_PTR_EQ(test, memchr_inv(destination, 0x6b,
					    3568U), NULL);
	error = swapz_ci_bio_snapshot_lz4_v1(
		&fixture->bio, &view, destination, 3568U);
	KUNIT_EXPECT_EQ(test, error, -EOPNOTSUPP);
	bio_put(split); /* Actual split uninit: ref 2 -> 1. */
	KUNIT_EXPECT_EQ(test, refcount_read(&owner->references), 1);
}

static void swapz_round043_reset_reissue_and_forged_clone_kunit(struct kunit *test)
{
	struct swapz_round034_v1_fixture *fixture =
		swapz_round034_v1_fixture_create(test);
	struct swapz_ci_owned_payload *owner;
	struct swapz_ci_lz4_owned_view_v1 view;
	struct bio clone = {};
	u8 *destination;
	int error;

	KUNIT_ASSERT_NOT_NULL(test, fixture);
	/* Test-scoped heap scratch: never reserve 3568 bytes on kernel stack. */
	destination = kunit_kmalloc(test, 3568U, GFP_KERNEL);
	KUNIT_ASSERT_NOT_NULL(test, destination);
	owner = fixture->bio.bi_swapz_ci_sideband;
	KUNIT_ASSERT_NOT_NULL(test, owner);
	error = bio_init_clone(NULL, &clone, &fixture->bio, GFP_KERNEL);
	if (error) {
		KUNIT_FAIL(test, "real original first clone failed");
		return;
	}
	KUNIT_EXPECT_EQ(test, refcount_read(&owner->references), 2);
	memset(&view, 0xa5, sizeof(view));
	memset(destination, 0x6b, 3568U);
	clone.bi_swapz_ci_full_clone_owned = false;
	KUNIT_EXPECT_EQ(test, swapz_ci_bio_snapshot_lz4_v1(
		&clone, &view, destination, 3568U),
			-EOPNOTSUPP);
	KUNIT_EXPECT_PTR_EQ(test, memchr_inv(&view, 0xa5, sizeof(view)), NULL);
	KUNIT_EXPECT_PTR_EQ(test, memchr_inv(destination, 0x6b,
					    3568U), NULL);
	clone.bi_swapz_ci_full_clone_owned = true;
	KUNIT_EXPECT_EQ(test, swapz_ci_bio_snapshot_lz4_v1(
		&clone, &view, destination, 3568U), 0);
	bio_prepare_reissue(&clone, NULL);
	KUNIT_EXPECT_PTR_EQ(test, clone.bi_swapz_ci_sideband, NULL);
	KUNIT_EXPECT_FALSE(test, clone.bi_swapz_ci_full_clone_owned);
	KUNIT_EXPECT_EQ(test, refcount_read(&owner->references), 1);
	bio_uninit(&clone);
	bio_uninit(&clone);
	error = bio_init_clone(NULL, &clone, &fixture->bio, GFP_KERNEL);
	if (error) {
		KUNIT_FAIL(test, "real original second clone failed");
		return;
	}
	KUNIT_EXPECT_EQ(test, refcount_read(&owner->references), 2);
	bio_reset(&clone, NULL, REQ_OP_WRITE | REQ_SWAP);
	KUNIT_EXPECT_PTR_EQ(test, clone.bi_swapz_ci_sideband, NULL);
	KUNIT_EXPECT_FALSE(test, clone.bi_swapz_ci_full_clone_owned);
	KUNIT_EXPECT_EQ(test, refcount_read(&owner->references), 1);
	bio_uninit(&clone);
}

static struct kunit_case swapz_round043_clone_copy_cases[] = {
	KUNIT_CASE(swapz_round043_full_clone_owned_lz4_copy_kunit),
	KUNIT_CASE(swapz_round043_split_or_consumed_clone_refused_kunit),
	KUNIT_CASE(swapz_round043_reset_reissue_and_forged_clone_kunit),
	{}
};
static struct kunit_suite swapz_round043_clone_copy_suite = {
	.name = "swapz_round043_original_bio_clone_copy_only",
	.test_cases = swapz_round043_clone_copy_cases,
};
kunit_test_suite(swapz_round043_clone_copy_suite);
#endif /* Source-only copy, never source-to-DM lease. */
"""


def apply_round043_original_bio_clone(path: str, composed: str) -> str:
    """Only original BIO clone owner ref and v1 copy; no map/IO semantics."""
    guard = """#if defined(SWAPZ_ROUND043_ORIGINAL_BIO_CLONE_COPY_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)"""
    if path == "include/linux/blk_types.h":
        return replace_once(
            composed, "\tstruct swapz_ci_owned_payload *bi_swapz_ci_sideband;\n",
            "\tstruct swapz_ci_owned_payload *bi_swapz_ci_sideband;\n" +
            guard + "\n\tbool bi_swapz_ci_full_clone_owned;\n#endif\n",
            path, "round043-clone-owner-state")
    if path != "block/bio.c":
        return composed
    # The actual original bio_init always explicitly resets both fields.
    init_anchor = ("\tbio->bi_private = NULL;\n"
                   "#ifdef SWAPZ_ROUND025_SIDEBAND_CI_ONLY\n"
                   "\tbio->bi_swapz_ci_sideband = NULL;\n#endif\n")
    composed = replace_once(
        composed, init_anchor,
        "\tbio->bi_private = NULL;\n"
        "#ifdef SWAPZ_ROUND025_SIDEBAND_CI_ONLY\n"
        "\tbio->bi_swapz_ci_sideband = NULL;\n" +
        guard + "\n\tbio->bi_swapz_ci_full_clone_owned = false;\n#endif\n"
        "#endif\n", path, "round043-bio-init-owner-clear")
    detach_anchor = ("\tbio->bi_swapz_ci_sideband = NULL;\n"
                     "\tswapz_ci_owned_put(owner);")
    composed = replace_once(
        composed, detach_anchor,
        "\tbio->bi_swapz_ci_sideband = NULL;\n" +
        guard + "\n\tbio->bi_swapz_ci_full_clone_owned = false;\n#endif\n"
        "\tswapz_ci_owned_put(owner);",
        path, "round043-uninit-reset-reissue-owner-clear")
    clone_anchor = ("\t\tbio->bi_swapz_ci_sideband = swapz_ci_owned_get(owner);\n"
                    "\t\tif (!bio->bi_swapz_ci_sideband)\n"
                    "\t\t\treturn -ESTALE;")
    composed = replace_once(
        composed, clone_anchor, clone_anchor + "\n" + guard +
        "\n\t\t/* Exact new owning ref is live before publishing marker. */\n"
        "\t\tbio->bi_swapz_ci_full_clone_owned = true;\n#endif",
        path, "round043-real-clone-acquired-ref")
    composed = replace_once(
        composed, "int swapz_ci_bio_snapshot_lz4_v1(const struct bio *source_bio,",
        ROUND043_ORIGINAL_BIO_CLONE_SOURCE + "\n" +
        "int swapz_ci_bio_snapshot_lz4_v1(const struct bio *source_bio,",
        path, "round043-clone-only-v1-private-checker")
    geometry = ("\t    source_bio->bi_vcnt ||\n"
                "\t    (source_bio->bi_flags & (1U << BIO_CLONED)) ||\n"
                "\t    !source_bio->bi_io_vec ||")
    replacement = ("\t    source_bio->bi_vcnt ||\n" + guard +
                   "\n\t    !swapz_round043_bio_clone_owner_is_independent("
                   "source_bio) ||\n"
                   "#else\n"
                   "\t    (source_bio->bi_flags & (1U << BIO_CLONED)) ||\n"
                   "#endif\n"
                   "\t    !source_bio->bi_io_vec ||")
    composed = replace_once(composed, geometry, replacement, path,
                            "round043-existing-v1-geometry-copy-only")
    return replace_once(
        composed, "static struct kunit_case swapz_ci_sideband_cases[] = {\n",
        ROUND043_ORIGINAL_BIO_CLONE_KUNIT + "\n" +
        "static struct kunit_case swapz_ci_sideband_cases[] = {\n",
        path, "round043-original-genuine-clone-kunit")


# Round049 guarded source-only counted slot immediate pair (NO_AUTH).
# Both acquisition and release occur BEFORE original folio unlock.
ROUND049_COUNTED_PAIR_MACRO = "SWAPZ_ROUND049_ORIGINAL_LOCKED_FOLIO_COUNT_PAIR_TEST"
ROUND049_COUNTED_PAIR_C = r"""#if defined(SWAPZ_ROUND049_ORIGINAL_LOCKED_FOLIO_COUNT_PAIR_TEST) && IS_ENABLED(CONFIG_KUNIT)
/* ROUND049_ORIGINAL_COUNTED_PAIR_BEGIN */
/* This CI-only local pair owns NO reference on return. */
static noinline int swapz_round049_original_locked_folio_counted_pair(
		struct folio *folio, const struct zswap_entry *stored,
		swp_entry_t original_slot, struct xarray *tree)
{
	int result;

	if (!folio || !stored || !tree || !original_slot.val)
		return -EINVAL;
	if (!folio_test_locked(folio) || !folio_test_swapcache(folio))
		return -ESTALE;
	if (folio->swap.val != original_slot.val ||
	    xa_load(tree, swp_offset(original_slot)) != stored)
		return -ESTALE;

	/*
	 * Original folio_dup_swap owns a counted slot only while a real
	 * locked cache folio pins that incarnation. The original cluster
	 * lock, extension allocation retry and rollback stay in the helper.
	 */
	result = folio_dup_swap(folio, NULL);
	if (result)
		return result;

	/*
	 * Balance the EXACT count before unlocking this SAME folio.
	 * folio_put_swap needs no new swap-area get, so no release races
	 * with percpu_ref_tryget_live after original get_swap_device put.
	 * NEVER transfer any counted ref to an external callback.
	 */
	folio_put_swap(folio, NULL);
	return 0;
}

static void swapz_round049_missing_original_owner_kunit(struct kunit *test)
{
	struct zswap_entry fake_store = {};
	struct xarray tree;
	swp_entry_t original_slot = { .val = 1 };

	xa_init(&tree);
	KUNIT_EXPECT_EQ(test, swapz_round049_original_locked_folio_counted_pair(
			NULL, &fake_store, original_slot, &tree), -EINVAL);
	KUNIT_EXPECT_EQ(test, swapz_round049_original_locked_folio_counted_pair(
			NULL, NULL, original_slot, &tree), -EINVAL);
	KUNIT_EXPECT_EQ(test, swapz_round049_original_locked_folio_counted_pair(
			NULL, &fake_store, original_slot, NULL), -EINVAL);
	original_slot.val = 0;
	KUNIT_EXPECT_EQ(test, swapz_round049_original_locked_folio_counted_pair(
			NULL, &fake_store, original_slot, &tree), -EINVAL);
	xa_destroy(&tree);
}

static void swapz_round049_unlocked_uncached_folio_kunit(struct kunit *test)
{
	struct zswap_entry fake_store = {};
	struct xarray tree;
	struct folio *folio;
	swp_entry_t original_slot = { .val = 1 };

	folio = folio_alloc(GFP_KERNEL, 0);
	KUNIT_ASSERT_NOT_NULL(test, folio);
	xa_init(&tree);
	/* Neither a borrowed unlocked page nor a locked uncached page owns
	 * the original allocation incarnation.
	 */
	KUNIT_EXPECT_FALSE(test, folio_test_locked(folio));
	KUNIT_EXPECT_FALSE(test, folio_test_swapcache(folio));
	KUNIT_EXPECT_EQ(test, swapz_round049_original_locked_folio_counted_pair(
			folio, &fake_store, original_slot, &tree), -ESTALE);
	folio_lock(folio);
	KUNIT_EXPECT_TRUE(test, folio_test_locked(folio));
	KUNIT_EXPECT_FALSE(test, folio_test_swapcache(folio));
	KUNIT_EXPECT_EQ(test, swapz_round049_original_locked_folio_counted_pair(
			folio, &fake_store, original_slot, &tree), -ESTALE);
	folio_unlock(folio);
	xa_destroy(&tree);
	folio_put(folio);
}

static struct kunit_case swapz_round049_original_counted_pair_cases[] = {
	KUNIT_CASE(swapz_round049_missing_original_owner_kunit),
	KUNIT_CASE(swapz_round049_unlocked_uncached_folio_kunit),
	{}
};
static struct kunit_suite swapz_round049_original_counted_pair_suite = {
	.name = "swapz_round049_original_locked_folio_counted_pair_no_authority",
	.test_cases = swapz_round049_original_counted_pair_cases,
};
kunit_test_suite(swapz_round049_original_counted_pair_suite);
/* ROUND049_ORIGINAL_COUNTED_PAIR_END */
#endif /* CI-only, DEFAULT UNDEFINED; NO external slot lease */
"""
ROUND049_COUNTED_PAIR_HOOK = r"""#if defined(SWAPZ_ROUND049_ORIGINAL_LOCKED_FOLIO_COUNT_PAIR_TEST) && IS_ENABLED(CONFIG_KUNIT)
	/* Only after the genuine source xarray identity/decompression check,
	 * while the current folio remains locked, BEFORE STORED erase.
	 */
	ret = swapz_round049_original_locked_folio_counted_pair(
		folio, entry, swpentry, tree);
	if (ret)
		goto err;
#endif
"""


def apply_round049_original_counted_pair(path: str, composed: str) -> str:
    """No default behavior: original C synchronous counted pair only."""
    if path != "mm/zswap.c":
        return composed
    declaration = "static int zswap_writeback_entry(struct zswap_entry *entry,\n"
    composed = replace_once(composed, declaration,
                            ROUND049_COUNTED_PAIR_C + "\n" + declaration,
                            path, "round049-genuine-original-locked-folio")
    erase = "\txa_erase(tree, offset);\n\n\tcount_vm_event(ZSWPWB);"
    return replace_once(composed, erase, ROUND049_COUNTED_PAIR_HOOK + erase,
                        path, "round049-after-original-store-verification")


# Round045 observation is private original Linux C, default UNDEFINED, and
# establishes no real current allocation or DM target/GC ownership lease.
ROUND045_ORIGINAL_STORED_BIO_SCOPE_MACRO = "SWAPZ_ROUND045_ORIGINAL_STORED_BIO_SOURCE_SCOPE_TEST"
ROUND045_ORIGINAL_STORED_BIO_SCOPE_C = r"""#if defined(SWAPZ_ROUND045_ORIGINAL_STORED_BIO_SOURCE_SCOPE_TEST) && \
    defined(SWAPZ_ROUND043_ORIGINAL_BIO_CLONE_COPY_TEST) && \
    defined(SWAPZ_ROUND042_ORIGINAL_STORED_WRITEBACK_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND041_ORIGINAL_SECTOR_TO_DM_NONAUTHORITY_TEST) && \
    defined(SWAPZ_ROUND040_ORIGINAL_ASYNC_SLOT_LEASE_NEGATIVE_TEST) && \
    defined(SWAPZ_ROUND038_ORIGINAL_STORE_PROVENANCE_TEST) && \
    defined(SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST) && \
    defined(SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
/* ROUND045_ORIGINAL_STORED_BIO_SOURCE_SCOPE_BEGIN */
/* ROUND045_ORIGINAL_STORED_BIO_SOURCE_SCOPE_PURE_C_BEGIN */
struct swapz_round045_stored_bio_scope_evidence {
	u64 original_typed_slot;
	u64 source_typed_slot;
	u64 original_slot_offset;
	u64 original_slot_epoch;
	u64 current_slot_epoch;
	const void *original_area_identity;
	const void *bio_area_identity;
	const void *original_backing_bdev;
	const void *bio_backing_bdev;
	u64 original_backing_sector;
	u64 original_bio_sector;
	u64 claimed_dm_relative_sector;
	u32 original_bio_bytes;
	u32 original_bvec_bytes;
	u32 original_bvec_offset;
	u32 original_bio_vec_count;
	bool original_swap_write;
	bool original_stored_lz4_owner_checked;
	bool area_ref_acquired_for_source_observation;
	bool area_ref_released_before_submit;
	bool source_entry_erased_and_freed;
	bool source_slot_incarnation_ref_held_across_async;
	bool current_dm_table_extent_gc_ref_held;
	bool cloned_split_or_reissued;
};

/* Original typed-slot+area and nonlinear sector are data, NOT a lease. */
static int swapz_round045_stored_bio_scope_refuse(
		const struct swapz_round045_stored_bio_scope_evidence *evidence)
{
	const u64 sectors_per_page = 4096U / 512U;

	if (!evidence)
		return -EINVAL;
	if (!evidence->original_typed_slot ||
	    evidence->original_typed_slot != evidence->source_typed_slot ||
	    !evidence->original_slot_epoch ||
	    evidence->original_slot_epoch != evidence->current_slot_epoch)
		return -ESTALE;
	if (!evidence->original_area_identity ||
	    evidence->original_area_identity != evidence->bio_area_identity ||
	    !evidence->original_backing_bdev ||
	    evidence->original_backing_bdev != evidence->bio_backing_bdev)
		return -ESTALE;
	if (!evidence->original_backing_sector ||
	    (evidence->original_backing_sector & (sectors_per_page - 1U)) ||
	    evidence->original_backing_sector > (u64)-1 - sectors_per_page)
		return -ERANGE;
	if (evidence->original_backing_sector != evidence->original_bio_sector)
		return -ESTALE;
	if (!evidence->original_bio_bytes ||
	    evidence->original_bio_bytes != 4096U ||
	    evidence->original_bvec_bytes != 4096U ||
	    evidence->original_bvec_offset ||
	    evidence->original_bio_vec_count ||
	    !evidence->original_swap_write)
		return -EOPNOTSUPP;
	if (!evidence->original_stored_lz4_owner_checked ||
	    !evidence->area_ref_acquired_for_source_observation ||
	    !evidence->area_ref_released_before_submit ||
	    !evidence->source_entry_erased_and_freed)
		return -ESTALE;
	if (evidence->cloned_split_or_reissued)
		return -EOPNOTSUPP;
	/* Even an original sector numerically identical to a DM relative
	 * sector cannot pin a current target, allocation, GC or destructor.
	 * Here the original users ref is ALREADY put, and no allocation
	 * incarnation ref exists across the async completion. Fabricating
	 * the last two bools can never produce authorization either.
	 */
	(void)evidence->original_slot_offset;
	(void)evidence->claimed_dm_relative_sector;
	(void)evidence->source_slot_incarnation_ref_held_across_async;
	(void)evidence->current_dm_table_extent_gc_ref_held;
	return -EOPNOTSUPP;
}
/* ROUND045_ORIGINAL_STORED_BIO_SOURCE_SCOPE_PURE_C_END */

/*
 * ORIGINAL mm/page_io.c single-bvec swap_bdev_submit_write() after the
 * preexisting Round031 owned STORED sideband was attached and ORIGINAL
 * zswap_writeback_entry() erased/freed the source zpool entry. The original
 * folio is UNLOCKED and PG_writeback, retained by swapcache only.
 * Acquire a NEW original swap-area users ref for the synchronous read of
 * ctx->sis->bdev, typed swp_entry_t, allocation epoch and mapped swapfile
 * extent. Drop this specific ref exactly once BEFORE returning, BEFORE
 * the unchanged synchronous/async submit_bio(). Do not retain a raw
 * swap_info_struct, bdev, slot, extent or folio pointer for later use.
 * No owner of a current downstream DM table/extent GC lifetime is present.
 */
static noinline int swapz_round045_original_stored_bio_scope_probe(
		const struct swap_io_ctx *ctx, const struct bio *source_bio,
		struct folio *folio)
{
	struct swapz_round045_stored_bio_scope_evidence evidence = {};
	struct swap_info_struct *active_area;
	swp_entry_t original_slot;

	if (!ctx || !ctx->sis || !source_bio || !folio ||
	    !source_bio->bi_swapz_ci_sideband ||
	    !folio_test_swapcache(folio) ||
	    !folio_test_writeback(folio) || folio_test_locked(folio))
		return -ESTALE;
	original_slot = folio_swap_entry(folio, 0);
	if (!original_slot.val || swp_type(original_slot) >= MAX_SWAPFILES)
		return -ESTALE;
	active_area = get_swap_device(original_slot);
	if (IS_ERR_OR_NULL(active_area))
		return -ESTALE;

	if (active_area != ctx->sis || !active_area->bdev ||
	    !source_bio->bi_io_vec || !source_bio->bi_io_vec[0].bv_page)
		goto release_original_area;

	evidence.original_typed_slot = (u64)original_slot.val;
	evidence.source_typed_slot =
		(u64)ctx->swapz_round035_original_slot.val;
	evidence.original_slot_offset = (u64)swp_offset(original_slot);
	evidence.original_slot_epoch =
		ctx->swapz_round035_original_epoch;
	evidence.current_slot_epoch =
		swapz_round028_slot_epoch(original_slot);
	evidence.original_area_identity = active_area;
	evidence.bio_area_identity = ctx->sis;
	evidence.original_backing_bdev = active_area->bdev;
	evidence.bio_backing_bdev = source_bio->bi_bdev;
	evidence.original_backing_sector = (u64)swap_folio_sector(folio);
	evidence.original_bio_sector =
		(u64)source_bio->bi_iter.bi_sector;
	evidence.original_bio_bytes = source_bio->bi_iter.bi_size;
	evidence.original_bvec_bytes =
		source_bio->bi_io_vec[0].bv_len;
	evidence.original_bvec_offset =
		source_bio->bi_io_vec[0].bv_offset;
	evidence.original_bio_vec_count = source_bio->bi_vcnt;
	evidence.original_swap_write =
		bio_op(source_bio) == REQ_OP_WRITE &&
		(source_bio->bi_opf & REQ_SWAP) != 0U &&
		!source_bio->bi_iter.bi_idx &&
		!source_bio->bi_iter.bi_offset &&
		!(source_bio->bi_flags & (1U << BIO_CLONED));
	evidence.original_stored_lz4_owner_checked =
		swapz_round035_bio_owner_matches(
			source_bio, (u64)original_slot.val,
			evidence.current_slot_epoch);
	evidence.area_ref_acquired_for_source_observation = true;
	/* The original entry was freed in zswap_writeback_entry() before
	 * __swap_writeout(), before this original page-IO BIO construction.
	 */
	evidence.source_entry_erased_and_freed = true;
release_original_area:
	put_swap_device(active_area);
	if (!evidence.area_ref_acquired_for_source_observation)
		return -ESTALE;
	evidence.area_ref_released_before_submit = true;
	/* No pointer in evidence is dereferenced after this release.
	 * Current slot allocation and DM target/GC leases remain UNKNOWN.
	 */
	return swapz_round045_stored_bio_scope_refuse(&evidence);
}

static void swapz_round045_stored_bio_scope_fixture(
		struct swapz_round045_stored_bio_scope_evidence *evidence)
{
	memset(evidence, 0, sizeof(*evidence));
	evidence->original_typed_slot = (u64)swp_entry(1U, 37U).val;
	evidence->source_typed_slot = evidence->original_typed_slot;
	evidence->original_slot_offset = 37U;
	evidence->original_slot_epoch = 17U;
	evidence->current_slot_epoch = 17U;
	evidence->original_area_identity = evidence;
	evidence->bio_area_identity = evidence;
	evidence->original_backing_bdev = &evidence->original_backing_sector;
	evidence->bio_backing_bdev = &evidence->original_backing_sector;
	evidence->original_backing_sector = 4096U; /* Nonlinear: 37*8=296. */
	evidence->original_bio_sector = 4096U;
	evidence->claimed_dm_relative_sector = 4096U; /* MOCK coincidence. */
	evidence->original_bio_bytes = 4096U; /* ORIGINAL uncompressed RAW. */
	evidence->original_bvec_bytes = 4096U;
	evidence->original_swap_write = true;
	evidence->original_stored_lz4_owner_checked = true;
	evidence->area_ref_acquired_for_source_observation = true;
	evidence->area_ref_released_before_submit = true;
	evidence->source_entry_erased_and_freed = true;
}

static void swapz_round045_nonlinear_bdev_dm_collision_kunit(
		struct kunit *test)
{
	struct swapz_round045_stored_bio_scope_evidence evidence;

	swapz_round045_stored_bio_scope_fixture(&evidence);
	KUNIT_EXPECT_NE(test, evidence.original_backing_sector,
			evidence.original_slot_offset * 8U);
	KUNIT_EXPECT_EQ(test, evidence.original_backing_sector,
			evidence.claimed_dm_relative_sector);
	KUNIT_EXPECT_EQ(test, swapz_round045_stored_bio_scope_refuse(&evidence),
			-EOPNOTSUPP);
	evidence.bio_backing_bdev = test;
	KUNIT_EXPECT_EQ(test, swapz_round045_stored_bio_scope_refuse(&evidence),
			-ESTALE);
	evidence.bio_backing_bdev = evidence.original_backing_bdev;
	evidence.original_bio_sector = evidence.original_slot_offset * 8U;
	KUNIT_EXPECT_EQ(test, swapz_round045_stored_bio_scope_refuse(&evidence),
			-ESTALE);
	evidence.original_bio_sector = evidence.original_backing_sector;
	evidence.original_bio_bytes = 2048U;
	KUNIT_EXPECT_EQ(test, swapz_round045_stored_bio_scope_refuse(&evidence),
			-EOPNOTSUPP);
}

static void swapz_round045_source_ref_aba_clone_reissue_kunit(
		struct kunit *test)
{
	struct swapz_round045_stored_bio_scope_evidence evidence;

	swapz_round045_stored_bio_scope_fixture(&evidence);
	/* Independently copied STORED bytes outlive erased zswap entry but
	 * do not keep a typed slot, original area, or DM map alive.
	 */
	evidence.source_slot_incarnation_ref_held_across_async = true;
	evidence.current_dm_table_extent_gc_ref_held = true;
	KUNIT_EXPECT_EQ(test, swapz_round045_stored_bio_scope_refuse(&evidence),
			-EOPNOTSUPP);
	evidence.current_slot_epoch++;
	KUNIT_EXPECT_EQ(test, swapz_round045_stored_bio_scope_refuse(&evidence),
			-ESTALE);
	evidence.current_slot_epoch = evidence.original_slot_epoch;
	evidence.source_typed_slot = (u64)swp_entry(2U, 37U).val;
	KUNIT_EXPECT_EQ(test, swapz_round045_stored_bio_scope_refuse(&evidence),
			-ESTALE);
	evidence.source_typed_slot = evidence.original_typed_slot;
	evidence.cloned_split_or_reissued = true;
	KUNIT_EXPECT_EQ(test, swapz_round045_stored_bio_scope_refuse(&evidence),
			-EOPNOTSUPP);
	evidence.cloned_split_or_reissued = false;
	evidence.area_ref_released_before_submit = false;
	KUNIT_EXPECT_EQ(test, swapz_round045_stored_bio_scope_refuse(&evidence),
			-ESTALE);
	KUNIT_EXPECT_EQ(test, swapz_round045_stored_bio_scope_refuse(NULL),
			-EINVAL);
}

static struct kunit_case swapz_round045_stored_bio_scope_cases[] = {
	KUNIT_CASE(swapz_round045_nonlinear_bdev_dm_collision_kunit),
	KUNIT_CASE(swapz_round045_source_ref_aba_clone_reissue_kunit),
	{}
};
static struct kunit_suite swapz_round045_stored_bio_scope_suite = {
	.name = "swapz_round045_original_stored_bio_source_scope_no_authority",
	.test_cases = swapz_round045_stored_bio_scope_cases,
};
kunit_test_suite(swapz_round045_stored_bio_scope_suite);
/* ROUND045_ORIGINAL_STORED_BIO_SOURCE_SCOPE_END */
#endif /* REAL original MM scope values only, never source-to-DM AUTH */
"""
ROUND045_ORIGINAL_STORED_BIO_SCOPE_HOOK = r"""#if defined(SWAPZ_ROUND045_ORIGINAL_STORED_BIO_SOURCE_SCOPE_TEST) && \
    defined(SWAPZ_ROUND043_ORIGINAL_BIO_CLONE_COPY_TEST) && \
    defined(SWAPZ_ROUND042_ORIGINAL_STORED_WRITEBACK_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND041_ORIGINAL_SECTOR_TO_DM_NONAUTHORITY_TEST) && \
    defined(SWAPZ_ROUND040_ORIGINAL_ASYNC_SLOT_LEASE_NEGATIVE_TEST) && \
    defined(SWAPZ_ROUND038_ORIGINAL_STORE_PROVENANCE_TEST) && \
    defined(SWAPZ_ROUND037_ORIGINAL_MM_LIFETIME_OWNER_TEST) && \
    defined(SWAPZ_ROUND036_ORIGINAL_ROUTE_LIFETIME_TEST) && \
    defined(SWAPZ_ROUND035_ORIGINAL_MM_ROUTE_WITNESS_TEST) && \
    defined(SWAPZ_ROUND034_ORIGINAL_V1_KUNIT_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
	/* TRUE original STORED->ordinary BIO source, immediately after the
	 * sideband transfer; source bytes remain independent of RAW_4096.
	 */
	if (bio->bi_swapz_ci_sideband)
		(void)swapz_round045_original_stored_bio_scope_probe(
			ctx, bio, bio_first_folio_all(bio));
#endif
"""


def apply_round045_original_stored_bio_scope(path: str,
                                             composed: str) -> str:
    """Observe the genuine original page_io BIO source only; no owner escape."""
    if path != "mm/page_io.c":
        return composed
    handler = "static void swap_bdev_submit_write(struct swap_io_ctx *ctx)\n"
    composed = replace_once(
        composed, handler,
        ROUND045_ORIGINAL_STORED_BIO_SCOPE_C + "\n" + handler,
        path, "round045-original-stored-bio-source-scope")
    return replace_once(
        composed, ROUND041_ORIGINAL_SECTOR_DOMAIN_HOOK,
        ROUND041_ORIGINAL_SECTOR_DOMAIN_HOOK +
        ROUND045_ORIGINAL_STORED_BIO_SCOPE_HOOK,
        path, "round045-original-page-io-actual-dispatch-scope")


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
    changed = apply_round032_bio_view(path, changed)
    if with_kunit:
        changed = apply_round034_original_v1_kunit(path, changed)
    if with_kunit:
        changed = apply_round035_original_route(path, changed)
    if with_kunit:
        changed = apply_round036_original_lifetime(path, changed)
    if with_kunit:
        changed = apply_round037_original_mm_owner(path, changed)
    if with_kunit:
        changed = apply_round038_original_store(path, changed)
    if with_kunit:
        changed = apply_round040_original_async_lease(path, changed)
    if with_kunit:
        changed = apply_round041_original_sector_domain(path, changed)
    if with_kunit:
        changed = apply_round042_original_stored_writeback(path, changed)
    if with_kunit:
        changed = apply_round043_original_bio_clone(path, changed)
    if with_kunit:
        changed = apply_round045_original_stored_bio_scope(path, changed)
    if with_kunit:
        changed = apply_round049_original_counted_pair(path, changed)
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
        "swapz_round045_original_stored_bio_scope_probe(",
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
