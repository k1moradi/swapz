#!/usr/bin/env python3
"""Round025 default-OFF pinned Linux BIO ownership source compiler probe.

Strictly consumes the stock torvalds/linux c339f4010dea8b0d754f84ace70cd1b089878ef8
Git blobs. Only two stock BIO sources are staged into a disposable full
kernel checkout. -DSWAPZ_ROUND025_SIDEBAND_CI_ONLY is for CI compilers,
NOT a configuration option for a loaded kernel or live transport.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

PINNED_LINUX_COMMIT = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
PINNED_BLOBS = {
    "include/linux/blk_types.h": "0cc09b975d8ffbd45ca3dc47533a71f8e8164de6",
    "block/bio.c": "b0fcc69de653524479e3b328aa29a37e97945b84",
}
CI_MACRO = "SWAPZ_ROUND025_SIDEBAND_CI_ONLY"

# This struct is NOT a Linux MM/BIO transport ABI. There is no source-owned
# authentic swap-slot allocation epoch or DM generation supplied by this round.
# The pointer is separately typed and is reset/freed independently of bi_private.
CI_BIO_FIELD = r"""#ifdef SWAPZ_ROUND025_SIDEBAND_CI_ONLY
	struct swapz_ci_owned_payload *bi_swapz_ci_sideband;
#endif
"""

CI_HELPERS = r"""#ifdef SWAPZ_ROUND025_SIDEBAND_CI_ONLY
#include <linux/refcount.h>
#include <linux/crc32c.h>
#include <linux/overflow.h>
#if IS_ENABLED(CONFIG_KUNIT)
#include <kunit/test.h>
#endif

/*
 * Default-off compiler-only feasibility model. NO producer calls this,
 * no DM consumer can accept it, and bio->bi_iter.bi_size remains 4096.
 * The buffer is one immutable owned allocation, never a zpool pointer.
 * The descriptor may be examined only while an independently held source
 * BIO reference prevents final release; get alone is not an RCU lookup.
 */
struct swapz_ci_owned_payload {
	refcount_t references;
	u64 slot_epoch;
	u64 source_identity;
	u32 compressed_crc32c;
	u16 compressed_length;
	u16 owned_capacity; /* Immutable allocation size, not claimed length. */
	u16 decoded_length;
	u8 representation_version;
	u8 codec;
	u8 original_sha256[32];
	u8 compressed_bytes[];
};


/*
 * Round029: TEST-ONLY constructor for a separately owned sealed copy.
 * The caller owns a stable read-only input snapshot through this call.
 * No pointer into source/zpool memory is retained. Input metadata and the
 * purported slot epoch/SHA are untrusted, NOT source authentication.
 * No dictionary or codec negotiation is supported: LZ4 version 1 only.
 * Once returned, fields and bytes are read-only; a parent BIO reference
 * protects their lifetime across clone/split, with final put freeing once.
 */
static struct swapz_ci_owned_payload *__maybe_unused
swapz_ci_owned_create(const u8 *compressed_source, size_t input_capacity,
		      size_t compressed_length, const u8 original_sha256[32],
		      u64 slot_epoch, u64 source_identity,
		      u8 representation_version, u8 codec,
		      u32 expected_crc32c, gfp_t allocation_flags)
{
	struct swapz_ci_owned_payload *owner;
	size_t allocation_bytes;
	unsigned int index;
	u8 digest_present = 0;

	/* Check all declared bounds before touching the untrusted source. */
	if (!compressed_source || !original_sha256 ||
	    compressed_source == original_sha256 ||
	    !compressed_length || compressed_length > 3568U ||
	    input_capacity < compressed_length || input_capacity > 3568U ||
	    !slot_epoch || !source_identity ||
	    representation_version != 1U || codec != 1U)
		return NULL;
	for (index = 0; index < 32; index++)
		digest_present |= original_sha256[index];
	if (!digest_present ||
	    check_add_overflow(sizeof(*owner), compressed_length,
			       &allocation_bytes) ||
	    allocation_bytes != struct_size(owner, compressed_bytes,
					    compressed_length))
		return NULL;
	owner = kzalloc(allocation_bytes, allocation_flags);
	if (!owner)
		return NULL;

	/* Copy first; CRC is computed over the PRIVATE bytes, not the input. */
	memcpy(owner->compressed_bytes, compressed_source, compressed_length);
	memcpy(owner->original_sha256, original_sha256,
	       sizeof(owner->original_sha256));
	owner->slot_epoch = slot_epoch;
	owner->source_identity = source_identity;
	owner->compressed_length = (u16)compressed_length;
	owner->owned_capacity = (u16)compressed_length;
	owner->decoded_length = 4096U;
	owner->representation_version = representation_version;
	owner->codec = codec;
	owner->compressed_crc32c =
		~crc32c(~0U, owner->compressed_bytes, compressed_length);
	if (owner->compressed_crc32c != expected_crc32c) {
		kfree_sensitive(owner);
		return NULL;
	}
	/* Publish the ONE initial owning ref only after all checks succeed. */
	refcount_set(&owner->references, 1);
	return owner;
}

static bool swapz_ci_owned_valid(const struct swapz_ci_owned_payload *owner)
{
	unsigned int index;
	u8 digest_nonzero = 0;

	if (!owner || !owner->slot_epoch || !owner->source_identity ||
	    owner->representation_version != 1U || owner->codec != 1U ||
	    !owner->compressed_length || owner->compressed_length > 3568U ||
	    !owner->owned_capacity || owner->owned_capacity > 3568U ||
	    owner->compressed_length > owner->owned_capacity ||
	    owner->decoded_length != 4096U)
		return false;
	for (index = 0; index < sizeof(owner->original_sha256); index++)
		digest_nonzero |= owner->original_sha256[index];
	return digest_nonzero &&
		~crc32c(~0U, owner->compressed_bytes,
			owner->compressed_length) == owner->compressed_crc32c;
}

/* Refcount acquisition requires a live parent BIO as external owner. */
static struct swapz_ci_owned_payload *
swapz_ci_owned_get(struct swapz_ci_owned_payload *owner)
{
	if (!owner || !refcount_inc_not_zero(&owner->references))
		return NULL;
	return owner;
}

static void swapz_ci_owned_put(struct swapz_ci_owned_payload *owner)
{
	if (owner && refcount_dec_and_test(&owner->references))
		kfree_sensitive(owner);
}

static void swapz_ci_bio_detach(struct bio *bio)
{
	struct swapz_ci_owned_payload *owner = bio->bi_swapz_ci_sideband;

	bio->bi_swapz_ci_sideband = NULL;
	swapz_ci_owned_put(owner);
}

/* A future merge call site MUST consult this check for *both* BIOs.
 * It is deliberately not wired into live block merging while no genuine
 * provenance/epoch to DM mapping can be sourced. Reject all sideband merges.
 */
static bool __maybe_unused swapz_ci_bio_merge_allowed(
		const struct bio *first, const struct bio *second)
{
	return first && second &&
	       !first->bi_swapz_ci_sideband && !second->bi_swapz_ci_sideband;
}

/* No implicit success from caller-supplied synthetic source generation. */
static int __maybe_unused swapz_ci_live_compressed_admit(
		const struct bio *bio, u64 caller_supplied_epoch)
{
	(void)bio;
	(void)caller_supplied_epoch;
	return -EOPNOTSUPP;
}
#endif /* SWAPZ_ROUND025_SIDEBAND_CI_ONLY */

"""

CI_KUNIT = r"""#if defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && IS_ENABLED(CONFIG_KUNIT)
/*
 * KUnit source tests compile against REAL pinned bio_init_clone/bio_reset/
 * bio_prepare_reissue/bio_uninit. Booted execution is NOT_RUN unless a
 * separate authorized KUnit kernel actually runs these cases.
 */
static struct swapz_ci_owned_payload *swapz_ci_kunit_owner(struct kunit *test)
{
	struct swapz_ci_owned_payload *owner;
	unsigned int index;

	owner = kzalloc(struct_size(owner, compressed_bytes, 16), GFP_KERNEL);
	if (!owner) {
		KUNIT_FAIL(test, "bounded owned allocation unavailable");
		return NULL;
	}
	refcount_set(&owner->references, 1);
	owner->slot_epoch = 11;
	owner->source_identity = 13;
	owner->representation_version = 1;
	owner->codec = 1;
	owner->decoded_length = 4096;
	owner->compressed_length = 16;
	owner->owned_capacity = 16;
	owner->original_sha256[0] = 1;
	for (index = 0; index < 16; index++)
		owner->compressed_bytes[index] = (u8)(index + 1);
	owner->compressed_crc32c = ~crc32c(~0U, owner->compressed_bytes, 16);
	return owner;
}

static void swapz_ci_clone_lifetime_kunit(struct kunit *test)
{
	struct bio source = {}, clone = {};
	struct swapz_ci_owned_payload *owner = swapz_ci_kunit_owner(test);
	int error;

	KUNIT_ASSERT_NOT_NULL(test, owner);
	bio_init(&source, NULL, NULL, 0, REQ_OP_WRITE | REQ_SWAP);
	source.bi_swapz_ci_sideband = owner; /* KUnit owns initial reference. */
	KUNIT_EXPECT_TRUE(test, swapz_ci_owned_valid(owner));
	error = bio_init_clone(NULL, &clone, &source, GFP_KERNEL);
	if (error) {
		KUNIT_FAIL(test, "real bio_init_clone refused source clone");
		bio_uninit(&source);
		return;
	}
	KUNIT_EXPECT_PTR_EQ(test, clone.bi_swapz_ci_sideband, owner);
	KUNIT_EXPECT_EQ(test, refcount_read(&owner->references), 2);
	KUNIT_EXPECT_FALSE(test, swapz_ci_bio_merge_allowed(&source, &clone));
	KUNIT_EXPECT_EQ(test, swapz_ci_live_compressed_admit(&clone, 11),
			-EOPNOTSUPP);
	bio_uninit(&source);
	KUNIT_EXPECT_EQ(test, refcount_read(&owner->references), 1);
	bio_uninit(&clone); /* Last reference releases exactly once. */
	bio_uninit(&clone); /* Extra uninit must not free a second time. */
}

static void swapz_ci_split_lifetime_kunit(struct kunit *test)
{
	struct bio_vec vector = {};
	struct bio source;
	struct bio *split;
	struct page *page;
	struct swapz_ci_owned_payload *owner;

	page = alloc_page(GFP_KERNEL);
	KUNIT_ASSERT_NOT_NULL(test, page);
	owner = swapz_ci_kunit_owner(test);
	if (!owner) {
		__free_page(page);
		return;
	}
	vector.bv_page = page;
	vector.bv_len = PAGE_SIZE;
	bio_init(&source, NULL, &vector, 1, REQ_OP_WRITE | REQ_SWAP);
	source.bi_vcnt = 1;
	source.bi_iter.bi_size = PAGE_SIZE;
	source.bi_swapz_ci_sideband = owner;
	/* Real pinned bio_split() uses bio_alloc_clone() and divides sectors. */
	split = bio_split(&source, PAGE_SIZE >> (SECTOR_SHIFT + 1),
			  GFP_KERNEL, &fs_bio_set);
	if (IS_ERR_OR_NULL(split)) {
		KUNIT_FAIL(test, "real bio_split failed, no ownership proof");
		goto release_source;
	}
	KUNIT_EXPECT_PTR_EQ(test, split->bi_swapz_ci_sideband, owner);
	KUNIT_EXPECT_EQ(test, refcount_read(&owner->references), 2);
	KUNIT_EXPECT_EQ(test, split->bi_iter.bi_size,
			(unsigned int)PAGE_SIZE / 2);
	KUNIT_EXPECT_EQ(test, source.bi_iter.bi_size,
			(unsigned int)PAGE_SIZE / 2);
	KUNIT_EXPECT_FALSE(test, swapz_ci_bio_merge_allowed(&source, split));
	/* Neither 2048-byte split can authenticate one original 4096 record. */
	KUNIT_EXPECT_EQ(test, swapz_ci_live_compressed_admit(split, 11),
			-EOPNOTSUPP);
	KUNIT_EXPECT_EQ(test, swapz_ci_live_compressed_admit(&source, 11),
			-EOPNOTSUPP);
	bio_put(split);
	KUNIT_EXPECT_EQ(test, refcount_read(&owner->references), 1);
release_source:
	bio_uninit(&source);
	__free_page(page);
}

static void swapz_ci_reuse_and_abort_kunit(struct kunit *test)
{
	struct bio source = {};
	struct swapz_ci_owned_payload *owner = swapz_ci_kunit_owner(test);

	KUNIT_ASSERT_NOT_NULL(test, owner);
	bio_init(&source, NULL, NULL, 0, REQ_OP_WRITE | REQ_SWAP);
	source.bi_swapz_ci_sideband = owner;
	bio_prepare_reissue(&source, NULL); /* Drop stale epoch before retry. */
	KUNIT_EXPECT_PTR_EQ(test, source.bi_swapz_ci_sideband, NULL);
	KUNIT_EXPECT_EQ(test, swapz_ci_live_compressed_admit(&source, 1),
			-EOPNOTSUPP);
	bio_uninit(&source);
	owner = swapz_ci_kunit_owner(test);
	KUNIT_ASSERT_NOT_NULL(test, owner);
	source.bi_swapz_ci_sideband = owner;
	bio_reset(&source, NULL, REQ_OP_WRITE | REQ_SWAP);
	KUNIT_EXPECT_PTR_EQ(test, source.bi_swapz_ci_sideband, NULL);
	bio_uninit(&source);
}

static void swapz_ci_reject_invalid_kunit(struct kunit *test)
{
	struct swapz_ci_owned_payload *owner = swapz_ci_kunit_owner(test);

	KUNIT_ASSERT_NOT_NULL(test, owner);
	KUNIT_EXPECT_TRUE(test, swapz_ci_owned_valid(owner));
	owner->slot_epoch = 0;
	KUNIT_EXPECT_FALSE(test, swapz_ci_owned_valid(owner));
	owner->slot_epoch = 11;
	owner->codec = 2; /* ZSTD != stored LZ4. */
	KUNIT_EXPECT_FALSE(test, swapz_ci_owned_valid(owner));
	owner->codec = 1;
	owner->compressed_crc32c ^= 1;
	KUNIT_EXPECT_FALSE(test, swapz_ci_owned_valid(owner));
	owner->compressed_crc32c ^= 1;
	owner->compressed_length = 3569; /* Must refuse before CRC read. */
	KUNIT_EXPECT_FALSE(test, swapz_ci_owned_valid(owner));
	owner->compressed_length = 16;
	owner->owned_capacity = 8; /* Claim within 3568, beyond allocation. */
	KUNIT_EXPECT_FALSE(test, swapz_ci_owned_valid(owner));
	swapz_ci_owned_put(owner);
}

/*
 * Real __bio_clone must reject an invalid owner BEFORE acquiring a ref;
 * bio_init_clone then bio_uninit's the destination on failure.
 */
static void swapz_ci_invalid_clone_kunit(struct kunit *test)
{
	struct bio source = {}, clone = {};
	struct swapz_ci_owned_payload *owner = swapz_ci_kunit_owner(test);
	int error;

	KUNIT_ASSERT_NOT_NULL(test, owner);
	bio_init(&source, NULL, NULL, 0, REQ_OP_WRITE | REQ_SWAP);
	source.bi_swapz_ci_sideband = owner;
	owner->compressed_crc32c ^= 1U;
	error = bio_init_clone(NULL, &clone, &source, GFP_KERNEL);
	KUNIT_EXPECT_EQ(test, error, -EOPNOTSUPP);
	KUNIT_EXPECT_PTR_EQ(test, clone.bi_swapz_ci_sideband, NULL);
	KUNIT_EXPECT_EQ(test, refcount_read(&owner->references), 1);
	bio_uninit(&source);
}

/*
 * bio_reuse() must preserve unrelated endio/bi_private state and clear
 * the old compressed owner, not leak/refcount it across source epochs.
 */
static void swapz_ci_reuse_private_kunit(struct kunit *test)
{
	struct bio source = {};
	struct swapz_ci_owned_payload *owner = swapz_ci_kunit_owner(test);
	unsigned int endio_token = 42;

	KUNIT_ASSERT_NOT_NULL(test, owner);
	bio_init(&source, NULL, NULL, 0, REQ_OP_WRITE | REQ_SWAP);
	source.bi_swapz_ci_sideband = owner;
	source.bi_private = &endio_token;
	bio_reuse(&source, REQ_OP_WRITE | REQ_SWAP);
	KUNIT_EXPECT_PTR_EQ(test, source.bi_swapz_ci_sideband, NULL);
	KUNIT_EXPECT_PTR_EQ(test, source.bi_private, &endio_token);
	KUNIT_EXPECT_EQ(test, endio_token, 42U);
	KUNIT_EXPECT_EQ(test, swapz_ci_live_compressed_admit(&source, 11),
			-EOPNOTSUPP);
	bio_uninit(&source);
}

/*
 * Cancel/double cleanup: detaching clears the pointer before last put;
 * no new ref may be acquired from a deliberately zero-count test owner.
 * Never dereference a previously freed owner in this test.
 */
static void swapz_ci_abort_dead_ref_kunit(struct kunit *test)
{
	struct bio source = {};
	struct swapz_ci_owned_payload *owner = swapz_ci_kunit_owner(test);

	KUNIT_ASSERT_NOT_NULL(test, owner);
	bio_init(&source, NULL, NULL, 0, REQ_OP_WRITE | REQ_SWAP);
	source.bi_swapz_ci_sideband = owner;
	swapz_ci_bio_detach(&source);
	KUNIT_EXPECT_PTR_EQ(test, source.bi_swapz_ci_sideband, NULL);
	swapz_ci_bio_detach(&source);
	bio_uninit(&source);
	bio_reset(&source, NULL, REQ_OP_WRITE | REQ_SWAP);
	KUNIT_EXPECT_PTR_EQ(test, source.bi_swapz_ci_sideband, NULL);
	bio_uninit(&source);

	owner = swapz_ci_kunit_owner(test);
	KUNIT_ASSERT_NOT_NULL(test, owner);
	refcount_set(&owner->references, 0);
	KUNIT_EXPECT_PTR_EQ(test, swapz_ci_owned_get(owner), NULL);
	refcount_set(&owner->references, 1);
	swapz_ci_owned_put(owner);
}


/* Constructor copies exact independently owned bytes, not a borrowed zpool. */
static void swapz_ci_constructor_copy_isolation_kunit(struct kunit *test)
{
	u8 compressed[24], digest[32] = { 0x5a };
	struct swapz_ci_owned_payload *owner;
	u32 crc;
	unsigned int index;

	for (index = 0; index < sizeof(compressed); index++)
		compressed[index] = (u8)(index + 1);
	crc = ~crc32c(~0U, compressed, sizeof(compressed));
	owner = swapz_ci_owned_create(compressed, sizeof(compressed),
				      sizeof(compressed), digest, 11, 13,
				      1, 1, crc, GFP_KERNEL);
	KUNIT_ASSERT_NOT_NULL(test, owner);
	KUNIT_EXPECT_TRUE(test, swapz_ci_owned_valid(owner));
	KUNIT_EXPECT_EQ(test, owner->compressed_length, (u16)24);
	KUNIT_EXPECT_EQ(test, owner->owned_capacity, (u16)24);
	KUNIT_EXPECT_EQ(test, owner->decoded_length, (u16)4096);
	KUNIT_EXPECT_EQ(test, owner->compressed_crc32c, crc);
	KUNIT_EXPECT_NE(test, owner->compressed_bytes, compressed);
	compressed[0] ^= 0xff;
	digest[0] ^= 0xff;
	KUNIT_EXPECT_EQ(test, owner->compressed_bytes[0], (u8)1);
	KUNIT_EXPECT_EQ(test, owner->original_sha256[0], (u8)0x5a);
	KUNIT_EXPECT_TRUE(test, swapz_ci_owned_valid(owner));
	swapz_ci_owned_put(owner);
}

/* Invalid lengths, alias, digest, metadata and CRC refuse before exposure. */
static void swapz_ci_constructor_reject_invalid_kunit(struct kunit *test)
{
	u8 compressed[32] = { 0x44 }, digest[32] = { 0x55 };
	u8 absent_digest[32] = {};
	u32 crc = ~crc32c(~0U, compressed, sizeof(compressed));

#define SWAPZ_CI_CREATE_TEST(source, capacity, length, sha, epoch, identity, version, coding, checksum) \
	KUNIT_EXPECT_PTR_EQ(test, swapz_ci_owned_create(source, capacity, length, \
			sha, epoch, identity, version, coding, checksum, \
			GFP_KERNEL), NULL)
	SWAPZ_CI_CREATE_TEST(NULL, 32, 32, digest, 11, 13, 1, 1, crc);
	SWAPZ_CI_CREATE_TEST(compressed, 32, 0, digest, 11, 13, 1, 1, crc);
	SWAPZ_CI_CREATE_TEST(compressed, 32, 3569, digest, 11, 13, 1, 1, crc);
	SWAPZ_CI_CREATE_TEST(compressed, 32, (size_t)-1, digest, 11, 13, 1, 1, crc);
	SWAPZ_CI_CREATE_TEST(compressed, 8, 32, digest, 11, 13, 1, 1, crc);
	SWAPZ_CI_CREATE_TEST(compressed, 3569, 32, digest, 11, 13, 1, 1, crc);
	SWAPZ_CI_CREATE_TEST(compressed, 32, 32, NULL, 11, 13, 1, 1, crc);
	SWAPZ_CI_CREATE_TEST(compressed, 32, 32, absent_digest, 11, 13, 1, 1, crc);
	SWAPZ_CI_CREATE_TEST(digest, 32, 32, digest, 11, 13, 1, 1, crc);
	SWAPZ_CI_CREATE_TEST(compressed, 32, 32, digest, 0, 13, 1, 1, crc);
	SWAPZ_CI_CREATE_TEST(compressed, 32, 32, digest, 11, 0, 1, 1, crc);
	SWAPZ_CI_CREATE_TEST(compressed, 32, 32, digest, 11, 13, 2, 1, crc);
	SWAPZ_CI_CREATE_TEST(compressed, 32, 32, digest, 11, 13, 1, 2, crc);
	SWAPZ_CI_CREATE_TEST(compressed, 32, 32, digest, 11, 13, 1, 1, crc ^ 1U);
#undef SWAPZ_CI_CREATE_TEST
}

/* Actual original clone success and failure, then retry retires old parent. */
static void swapz_ci_constructor_clone_abort_kunit(struct kunit *test)
{
	u8 compressed[16] = { 1 }, digest[32] = { 1 };
	struct swapz_ci_owned_payload *owner;
	struct bio source = {}, clone = {}, rejected = {};
	u32 crc = ~crc32c(~0U, compressed, sizeof(compressed));
	int error;

	owner = swapz_ci_owned_create(compressed, sizeof(compressed),
				      sizeof(compressed), digest, 11, 13,
				      1, 1, crc, GFP_KERNEL);
	KUNIT_ASSERT_NOT_NULL(test, owner);
	bio_init(&source, NULL, NULL, 0, REQ_OP_WRITE | REQ_SWAP);
	source.bi_swapz_ci_sideband = owner;
	error = bio_init_clone(NULL, &clone, &source, GFP_KERNEL);
	if (error) {
		KUNIT_FAIL(test, "constructor owner could not clone");
		bio_uninit(&source);
		return;
	}
	KUNIT_EXPECT_EQ(test, refcount_read(&owner->references), 2);
	owner->compressed_crc32c ^= 1U; /* Invalid mutation must fail clone. */
	error = bio_init_clone(NULL, &rejected, &source, GFP_KERNEL);
	KUNIT_EXPECT_EQ(test, error, -EOPNOTSUPP);
	KUNIT_EXPECT_PTR_EQ(test, rejected.bi_swapz_ci_sideband, NULL);
	KUNIT_EXPECT_EQ(test, refcount_read(&owner->references), 2);
	owner->compressed_crc32c ^= 1U;
	bio_prepare_reissue(&source, NULL);
	KUNIT_EXPECT_PTR_EQ(test, source.bi_swapz_ci_sideband, NULL);
	KUNIT_EXPECT_EQ(test, refcount_read(&owner->references), 1);
	KUNIT_EXPECT_EQ(test, swapz_ci_live_compressed_admit(&clone, 11),
			-EOPNOTSUPP);
	bio_uninit(&source);
	bio_uninit(&clone); /* Last owner reference released exactly once. */
	bio_uninit(&clone); /* No resurrection on repeated uninit. */
}

/* Real original split retains an owner ref but cannot promote half pages. */
static void swapz_ci_constructor_split_reset_kunit(struct kunit *test)
{
	struct bio_vec vector = {};
	struct bio source;
	struct bio *split;
	struct page *page;
	u8 compressed[16] = { 1 }, digest[32] = { 1 };
	struct swapz_ci_owned_payload *owner;
	u32 crc = ~crc32c(~0U, compressed, sizeof(compressed));

	page = alloc_page(GFP_KERNEL);
	KUNIT_ASSERT_NOT_NULL(test, page);
	owner = swapz_ci_owned_create(compressed, sizeof(compressed),
				      sizeof(compressed), digest, 11, 13,
				      1, 1, crc, GFP_KERNEL);
	if (!owner) {
		KUNIT_FAIL(test, "constructor allocation failed");
		__free_page(page);
		return;
	}
	vector.bv_page = page;
	vector.bv_len = PAGE_SIZE;
	bio_init(&source, NULL, &vector, 1, REQ_OP_WRITE | REQ_SWAP);
	source.bi_vcnt = 1;
	source.bi_iter.bi_size = PAGE_SIZE;
	source.bi_swapz_ci_sideband = owner;
	KUNIT_EXPECT_EQ(test, source.bi_iter.bi_size, (unsigned int)4096);
	split = bio_split(&source, PAGE_SIZE >> (SECTOR_SHIFT + 1),
			  GFP_KERNEL, &fs_bio_set);
	if (IS_ERR_OR_NULL(split)) {
		KUNIT_FAIL(test, "constructor owner could not split");
		bio_uninit(&source);
		__free_page(page);
		return;
	}
	KUNIT_EXPECT_PTR_EQ(test, split->bi_swapz_ci_sideband, owner);
	KUNIT_EXPECT_EQ(test, refcount_read(&owner->references), 2);
	KUNIT_EXPECT_EQ(test, split->bi_iter.bi_size, (unsigned int)2048);
	KUNIT_EXPECT_EQ(test, source.bi_iter.bi_size, (unsigned int)2048);
	KUNIT_EXPECT_EQ(test, swapz_ci_live_compressed_admit(split, 11),
			-EOPNOTSUPP);
	bio_put(split);
	KUNIT_EXPECT_EQ(test, refcount_read(&owner->references), 1);
	bio_reset(&source, NULL, REQ_OP_WRITE | REQ_SWAP);
	KUNIT_EXPECT_PTR_EQ(test, source.bi_swapz_ci_sideband, NULL);
	bio_uninit(&source);
	__free_page(page);
}

static struct kunit_case swapz_ci_sideband_cases[] = {
	KUNIT_CASE(swapz_ci_constructor_copy_isolation_kunit),
	KUNIT_CASE(swapz_ci_constructor_reject_invalid_kunit),
	KUNIT_CASE(swapz_ci_constructor_clone_abort_kunit),
	KUNIT_CASE(swapz_ci_constructor_split_reset_kunit),
	KUNIT_CASE(swapz_ci_clone_lifetime_kunit),
	KUNIT_CASE(swapz_ci_split_lifetime_kunit),
	KUNIT_CASE(swapz_ci_reuse_and_abort_kunit),
	KUNIT_CASE(swapz_ci_reject_invalid_kunit),
	KUNIT_CASE(swapz_ci_invalid_clone_kunit),
	KUNIT_CASE(swapz_ci_reuse_private_kunit),
	KUNIT_CASE(swapz_ci_abort_dead_ref_kunit),
	{}
};

static struct kunit_suite swapz_ci_sideband_suite = {
	.name = "swapz_round025_sideband_compiler_only",
	.test_cases = swapz_ci_sideband_cases,
};
kunit_test_suite(swapz_ci_sideband_suite);
#endif /* CI_ONLY && KUNIT */

"""

class SourceGateError(RuntimeError):
    """First source-object mismatch or unsafe compiler gate."""


def blob_sha(content: bytes) -> str:
    header = b"blob " + str(len(content)).encode("ascii") + b"\x00"
    return hashlib.sha1(header + content).hexdigest()


def replace_once(original: str, before: str, after: str, path: str) -> str:
    if original.count(before) != 1 or before == after:
        raise SourceGateError(f"anchor_missing_or_duplicated:{path}")
    if after in original:
        raise SourceGateError(f"already_staged:{path}")
    return original.replace(before, after, 1)


def render_source(path: str, source: bytes) -> bytes:
    if path not in PINNED_BLOBS:
        raise SourceGateError(f"outside_own_paths:{path}")
    if blob_sha(source) != PINNED_BLOBS[path]:
        raise SourceGateError(f"original_git_blob_mismatch:{path}")
    text = source.decode("utf-8")
    if CI_MACRO in text:
        raise SourceGateError(f"already_staged:{path}")
    if path == "include/linux/blk_types.h":
        text = replace_once(text, "struct bio_integrity_payload;\n",
                            "struct bio_integrity_payload;\n"
                            "#ifdef SWAPZ_ROUND025_SIDEBAND_CI_ONLY\n"
                            "struct swapz_ci_owned_payload;\n"
                            "#endif\n", path)
        text = replace_once(text, "\tbio_end_io_t\t\t*bi_end_io;\n\tvoid\t\t\t*bi_private;\n",
                            "\tbio_end_io_t\t\t*bi_end_io;\n\tvoid\t\t\t*bi_private;\n"
                            + CI_BIO_FIELD, path)
    else:
        text = replace_once(text, '#include "blk-cgroup.h"\n',
                            '#include "blk-cgroup.h"\n' + CI_HELPERS, path)
        text = replace_once(text, "\tbio_crypt_free_ctx(bio);\n",
                            "\tbio_crypt_free_ctx(bio);\n"
                            "#ifdef SWAPZ_ROUND025_SIDEBAND_CI_ONLY\n"
                            "\tswapz_ci_bio_detach(bio);\n#endif\n", path)
        text = replace_once(text,
                            "\tbio->bi_end_io = NULL;\n\tbio->bi_private = NULL;\n",
                            "\tbio->bi_end_io = NULL;\n\tbio->bi_private = NULL;\n"
                            "#ifdef SWAPZ_ROUND025_SIDEBAND_CI_ONLY\n"
                            "\tbio->bi_swapz_ci_sideband = NULL;\n#endif\n", path)
        text = replace_once(text,
                            "void bio_prepare_reissue(struct bio *bio, struct block_device *bdev)\n{\n",
                            "void bio_prepare_reissue(struct bio *bio, struct block_device *bdev)\n{\n"
                            "#ifdef SWAPZ_ROUND025_SIDEBAND_CI_ONLY\n"
                            "\t/* Never replay a stale source slot epoch on retry. */\n"
                            "\tswapz_ci_bio_detach(bio);\n#endif\n", path)
        text = replace_once(text,
                            "\telse\n\t\tbio->bi_io_vec = bio_src->bi_io_vec;\n",
                            "\telse\n\t\tbio->bi_io_vec = bio_src->bi_io_vec;\n"
                            "#ifdef SWAPZ_ROUND025_SIDEBAND_CI_ONLY\n"
                            "\t/* This opt-in CI clone owns a separate reference. */\n"
                            "\tif (bio_src->bi_swapz_ci_sideband) {\n"
                            "\t\tstruct swapz_ci_owned_payload *owner =\n"
                            "\t\t\tbio_src->bi_swapz_ci_sideband;\n"
                            "\t\tif (!swapz_ci_owned_valid(owner))\n"
                            "\t\t\treturn -EOPNOTSUPP;\n"
                            "\t\tbio->bi_swapz_ci_sideband = swapz_ci_owned_get(owner);\n"
                            "\t\tif (!bio->bi_swapz_ci_sideband)\n"
                            "\t\t\treturn -ESTALE;\n"
                            "\t}\n#endif\n", path)
        text = replace_once(text, "EXPORT_SYMBOL(bio_init_clone);\n",
                            "EXPORT_SYMBOL(bio_init_clone);\n" + CI_KUNIT, path)
    return text.encode("utf-8")


def stage_all(linux_root: Path) -> None:
    plans: list[tuple[Path, bytes]] = []
    for path in PINNED_BLOBS:
        destination = linux_root / path
        if not destination.is_file() or destination.is_symlink():
            raise SourceGateError(f"missing_or_symlink:{path}")
        original = destination.read_bytes()
        if len(original) > 1_048_576:
            raise SourceGateError(f"oversized_pinned_source:{path}")
        plans.append((destination, render_source(path, original)))
    # All source preimages and anchor positions are checked before any write.
    for destination, updated in plans:
        destination.write_bytes(updated)
    print("ROUND025_SIDEBAND_STAGED_CI_ONLY exact_pinned_blobs=2")
    print("LIVE_COMPRESSED=DISABLED LOADED_4096=NOT_RUN PHYSICAL=NOT_RUN")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", type=Path, required=True)
    arguments = parser.parse_args()
    stage_all(arguments.linux_root.resolve())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, SourceGateError, UnicodeError) as error:
        print(f"BLOCKED first_cause={error}")
        raise SystemExit(2) from error
