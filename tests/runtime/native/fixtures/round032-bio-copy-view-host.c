/* SPDX-License-Identifier: GPL-2.0-only */
/* Host boundary only: real emitted original block/bio.c owned C and
 * read-only GPL export are inserted, never hand-reimplemented.
 * The synthetic BIO below models pinned original Linux's embedded
 * swap_iocb: bio_init() left bi_vcnt zero, prepopulated first bvec.
 */
#define SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY 1
#define SWAPZ_ROUND031_MM_BIO_SOURCE 1
#define SWAPZ_ROUND025_SIDEBAND_CI_ONLY 1

#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <lz4.h>
#include <openssl/sha.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
typedef unsigned int gfp_t;
typedef struct { unsigned int value; } refcount_t;

#define GFP_KERNEL 0U
#define __maybe_unused __attribute__((unused))
#define EXPORT_SYMBOL_GPL(symbol) /* Only the real Linux modpost exports. */
#define struct_size(owner, member, count) (sizeof(*(owner)) + (count))
#define check_add_overflow(first, second, result) \
	__builtin_add_overflow((first), (second), (result))
#define REQ_OP_READ 0U
#define REQ_OP_WRITE 1U
#define REQ_OP_DISCARD 3U
#define REQ_SWAP (1U << 9)
#define BIO_CLONED 4U
#define SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN 0U
#define SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK 1U

struct bio_vec {
	void *bv_page;
	unsigned int bv_len;
	unsigned int bv_offset;
};
struct bio {
	unsigned int bi_opf;
	unsigned int bi_swap_origin;
	unsigned int bi_flags;
	unsigned short bi_vcnt;
	struct bio_vec *bi_io_vec;
	struct {
		unsigned int bi_size;
		unsigned int bi_idx;
		unsigned int bi_offset;
	} bi_iter;
	void *bi_private;
	struct swapz_ci_owned_payload *bi_swapz_ci_sideband;
};
#define bio_op(bio_pointer) ((bio_pointer)->bi_opf & 0xffU)
#define bio_sectors(bio_pointer) ((bio_pointer)->bi_iter.bi_size >> 9U)

/* Actual original linux/bio.h immutable C metadata definition. */
/* ROUND032_EXACT_HEADER_VALUE_STRUCT */

static unsigned int owner_allocations;
static unsigned int owner_frees;
static unsigned int owner_live_refs;
static void refcount_set(refcount_t *counter, unsigned int value)
{
	assert(counter->value == 0U);
	counter->value = value;
	owner_live_refs += value;
}
static bool refcount_inc_not_zero(refcount_t *counter)
{
	if (!counter->value)
		return false;
	++counter->value;
	++owner_live_refs;
	return true;
}
static bool refcount_dec_and_test(refcount_t *counter)
{
	assert(counter->value > 0U);
	--counter->value;
	--owner_live_refs;
	return counter->value == 0U;
}
static void *kzalloc(size_t length, gfp_t flags)
{
	void *owner;
	(void)flags;
	owner = calloc(1U, length);
	if (owner)
		++owner_allocations;
	return owner;
}
static void kfree_sensitive(void *owner)
{
	if (owner) {
		++owner_frees;
		free(owner);
	}
}
/* Runtime genuine CRC32C poly 0x82f63b78, not IEEE CRC32. */
static u32 crc32c(u32 checksum, const u8 *bytes, unsigned int count)
{
	for (unsigned int index = 0; index < count; ++index) {
		checksum ^= bytes[index];
		for (unsigned int bit = 0; bit < 8U; ++bit)
			checksum = (checksum >> 1) ^
				((checksum & 1U) ? 0x82f63b78U : 0U);
	}
	return checksum;
}

/* FULL exact emitted original linux/block/bio.c, source extracted from
 * the composer and both original prior stagers, NOT an algorithm mock.
 */
/* ROUND032_EXACT_ORIGINAL_BIO_OWNER_AND_EXPORT */

int main(void)
{
	u8 original_page[4096] = { 0 };
	u8 actual_lz4[3568] = { 0 };
	u8 private_copy[3568];
	u8 expected_copy[3568];
	u8 guard_copy[3568];
	u8 guard_view[sizeof(struct swapz_ci_lz4_owned_view_v1)];
	u8 full_sha256[32] = { 0 };
	struct swapz_ci_lz4_owned_view_v1 view;
	struct swapz_ci_owned_payload *owner;
	struct swapz_ci_owned_payload *legacy_owner;
	struct bio_vec vec = { .bv_page = original_page,
			       .bv_len = 4096U, .bv_offset = 0U };
	struct bio source_bio = {
		.bi_opf = REQ_OP_WRITE | REQ_SWAP,
		.bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK,
		.bi_iter = { .bi_size = 4096U, .bi_idx = 0U, .bi_offset = 0U },
		.bi_io_vec = &vec,
	};
	size_t length;
	int encoded_length;
	u32 proper_crc;
	unsigned int saved_refcounts;

	for (size_t i = 0; i < sizeof(original_page); ++i)
		original_page[i] = (u8)(i % 27U);
	assert(SHA256(original_page, sizeof(original_page), full_sha256));
	encoded_length = LZ4_compress_default((const char *)original_page,
					   (char *)actual_lz4,
					   (int)sizeof(original_page),
					   (int)sizeof(actual_lz4));
	assert(encoded_length > 0 && encoded_length <= 3568);
	length = (size_t)encoded_length;
	proper_crc = ~crc32c(~0U, actual_lz4, (unsigned int)length);
	assert(~crc32c(~0U, (const u8 *)"123456789", 9U) == 0xe3069283U);
	owner = swapz_ci_owned_create_source_v1(
		actual_lz4, length, length, full_sha256,
		24U, 25U, 0x0000000100000005ULL,
		1U, 1U, proper_crc, GFP_KERNEL);
	assert(owner != NULL && owner->references.value == 1U);
	assert(owner->source_swap_entry == 0x0000000100000005ULL);
	assert(owner_live_refs == 1U);
	source_bio.bi_swapz_ci_sideband = owner;
	memset(private_copy, 0x7a, sizeof(private_copy));
	memset(&view, 0x5b, sizeof(view));
	assert(swapz_ci_bio_snapshot_lz4_v1(&source_bio, &view,
					   private_copy, length) == 0);
	assert(owner_live_refs == 1U);
	assert(view.source_swap_entry == 0x0000000100000005ULL);
	assert(view.source_slot_epoch == 24U);
	assert(view.stored_entry_identity == 25U);
	assert(view.compressed_length == length);
	assert(view.decoded_length == 4096U);
	assert(view.representation_version == 1U && view.codec == 1U);
	assert(view.compressed_crc32c == proper_crc);
	assert(memcmp(private_copy, actual_lz4, length) == 0);
	assert(memcmp(view.original_sha256, full_sha256, 32U) == 0);
	/* Both value outputs are independently owned; no borrowed pointers. */
	memcpy(expected_copy, private_copy, length);
	memset(actual_lz4, 0, sizeof(actual_lz4));
	assert(swapz_ci_bio_snapshot_lz4_v1(&source_bio, &view,
					   private_copy, length) == 0);
	assert(memcmp(expected_copy, private_copy, length) == 0);
	{
		u8 decoded[4096];
		u8 decoded_sha[32] = { 0 };
		int count = LZ4_decompress_safe(
			(const char *)private_copy, (char *)decoded,
			(int)length, (int)sizeof(decoded));
		assert(count == 4096);
		assert(SHA256(decoded, sizeof(decoded), decoded_sha));
		assert(memcmp(decoded_sha, view.original_sha256, 32U) == 0);
	}
	/* Every failure must preserve BOTH metadata and full destination. */
	memset(&view, 0x5b, sizeof(view));
	memset(private_copy, 0x7a, sizeof(private_copy));
	memcpy(guard_view, &view, sizeof(view));
	memcpy(guard_copy, private_copy, sizeof(private_copy));
#define REFUSE_UNCHANGED(expected_error) do { \
	assert(swapz_ci_bio_snapshot_lz4_v1( \
		&source_bio, &view, private_copy, length) == (expected_error)); \
	assert(memcmp(&view, guard_view, sizeof(view)) == 0); \
	assert(memcmp(private_copy, guard_copy, sizeof(private_copy)) == 0); \
	assert(owner_live_refs == 1U); \
} while (0)
	source_bio.bi_opf = REQ_OP_READ | REQ_SWAP;
	REFUSE_UNCHANGED(-EOPNOTSUPP);
	source_bio.bi_opf = REQ_OP_DISCARD | REQ_SWAP;
	REFUSE_UNCHANGED(-EOPNOTSUPP);
	source_bio.bi_opf = REQ_OP_WRITE;
	REFUSE_UNCHANGED(-EOPNOTSUPP);
	source_bio.bi_opf = REQ_OP_WRITE | REQ_SWAP;
	source_bio.bi_swap_origin = SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;
	REFUSE_UNCHANGED(-EOPNOTSUPP);
	source_bio.bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;
	source_bio.bi_iter.bi_size = 2048U;
	REFUSE_UNCHANGED(-EOPNOTSUPP);
	source_bio.bi_iter.bi_size = 8192U;
	REFUSE_UNCHANGED(-EOPNOTSUPP);
	source_bio.bi_iter.bi_size = 4096U;
	source_bio.bi_vcnt = 1U;
	REFUSE_UNCHANGED(-EOPNOTSUPP);
	source_bio.bi_vcnt = 0U;
	source_bio.bi_flags = 1U << BIO_CLONED;
	REFUSE_UNCHANGED(-EOPNOTSUPP);
	source_bio.bi_flags = 0U;
	source_bio.bi_iter.bi_idx = 1U;
	REFUSE_UNCHANGED(-EOPNOTSUPP);
	source_bio.bi_iter.bi_idx = 0U;
	source_bio.bi_iter.bi_offset = 1U;
	REFUSE_UNCHANGED(-EOPNOTSUPP);
	source_bio.bi_iter.bi_offset = 0U;
	vec.bv_len = 2048U;
	REFUSE_UNCHANGED(-EOPNOTSUPP);
	vec.bv_len = 4096U;
	vec.bv_offset = 1U;
	REFUSE_UNCHANGED(-EOPNOTSUPP);
	vec.bv_offset = 0U;
	saved_refcounts = owner_live_refs;
	assert(swapz_ci_bio_snapshot_lz4_v1(
		&source_bio, &view, private_copy, length - 1U) == -ENOSPC);
	assert(owner_live_refs == saved_refcounts);
	assert(memcmp(&view, guard_view, sizeof(view)) == 0);
	assert(memcmp(private_copy, guard_copy, sizeof(private_copy)) == 0);
	owner->source_swap_entry = 0U;
	REFUSE_UNCHANGED(-ESTALE);
	owner->source_swap_entry = 0x0000000100000005ULL;
	owner->slot_epoch = 0U;
	REFUSE_UNCHANGED(-ESTALE);
	owner->slot_epoch = 24U;
	owner->source_identity = 0U;
	REFUSE_UNCHANGED(-ESTALE);
	owner->source_identity = 25U;
	owner->codec = 2U;
	REFUSE_UNCHANGED(-ESTALE);
	owner->codec = 1U;
	owner->representation_version = 2U;
	REFUSE_UNCHANGED(-ESTALE);
	owner->representation_version = 1U;
	owner->compressed_length = 3569U;
	REFUSE_UNCHANGED(-ESTALE);
	owner->compressed_length = (u16)length;
	owner->compressed_length = 0U;
	REFUSE_UNCHANGED(-ESTALE);
	owner->compressed_length = (u16)length;
	owner->compressed_bytes[0] ^= 0x80U;
	REFUSE_UNCHANGED(-ESTALE);
	owner->compressed_bytes[0] ^= 0x80U;
	owner->original_sha256[0] ^= 0xaaU;
	/* A nonzero SHA cannot be reauthenticated against a synthetic BIO.
	 * Metadata value alone is not end-to-end original STORE proof.
	 * Snapshot checks SHA presence; original MM STORE performed capture.
	 */
	assert(swapz_ci_bio_snapshot_lz4_v1(&source_bio, &view,
					   private_copy, length) == 0);
	owner->original_sha256[0] ^= 0xaaU;
	assert(memcmp(&view, guard_view, sizeof(view)) != 0);
	memcpy(&view, guard_view, sizeof(view));
	memset(private_copy, 0x7a, sizeof(private_copy));
	assert(swapz_ci_bio_snapshot_lz4_v1(
		&source_bio, &view, owner->compressed_bytes, length) == -EINVAL);
	assert(memcmp(&view, guard_view, sizeof(view)) == 0);
	assert(memcmp(private_copy, guard_copy, sizeof(private_copy)) == 0);
	assert(swapz_ci_bio_snapshot_lz4_v1(
		&source_bio, &view, (u8 *)&view, length) == -EINVAL);
	assert(memcmp(&view, guard_view, sizeof(view)) == 0);
	assert(swapz_ci_bio_snapshot_lz4_v1(
		&source_bio, &view, private_copy, length) == 0);
	assert(owner_live_refs == 1U);
	legacy_owner = swapz_ci_owned_create(
		expected_copy, length, length, full_sha256,
		24U, 25U, 1U, 1U, proper_crc, GFP_KERNEL);
	assert(legacy_owner && legacy_owner->source_swap_entry == 0U);
	source_bio.bi_swapz_ci_sideband = legacy_owner;
	memset(&view, 0x5b, sizeof(view));
	memset(private_copy, 0x7a, sizeof(private_copy));
	memcpy(guard_view, &view, sizeof(view));
	memcpy(guard_copy, private_copy, sizeof(private_copy));
	assert(swapz_ci_bio_snapshot_lz4_v1(
		&source_bio, &view, private_copy, length) == -ESTALE);
	assert(memcmp(&view, guard_view, sizeof(view)) == 0);
	assert(memcmp(private_copy, guard_copy, sizeof(private_copy)) == 0);
	swapz_ci_bio_detach(&source_bio);
	assert(source_bio.bi_swapz_ci_sideband == NULL);
	assert(owner_live_refs == 1U);
	source_bio.bi_swapz_ci_sideband = owner;
	swapz_ci_bio_detach(&source_bio);
	assert(source_bio.bi_swapz_ci_sideband == NULL);
	assert(owner_live_refs == 0U);
	assert(swapz_ci_bio_snapshot_lz4_v1(
		&source_bio, &view, private_copy, length) == -ESTALE);
	assert(memcmp(&view, guard_view, sizeof(view)) == 0);
	assert(memcmp(private_copy, guard_copy, sizeof(private_copy)) == 0);
	assert(owner_allocations == owner_frees);
	assert(owner_live_refs == 0U);
	puts("ROUND032_ORIGINAL_BIO_EXACT_SOURCE_COPY_OUT_PASS");
	return 0;
}
