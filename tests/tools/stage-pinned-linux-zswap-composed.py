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
	swapz_round034_v1_expect_refusal(test, &clone, 128U, -EOPNOTSUPP);
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
    changed = apply_round032_bio_view(path, changed)
    if with_kunit:
        changed = apply_round034_original_v1_kunit(path, changed)
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
