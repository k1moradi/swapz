/* Round033 source-extracted ORIGINAL-GPL-BIO consumer mechanical copy.
 * Only the original exported provider and stable BIO boundary are faked.
 * The consumer function body is injected verbatim from dm-target.c, while
 * the real pinned original Kernel build independently proves actual modpost.
 * NO loaded kernel or authentic MM->DM source slot proof.
 */
#define SWAPZ_ZSWAP_IMPORT_HOST_TEST 1
#include "zswap-import-codec.h"
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stddef.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
#define __used __attribute__((used))
#define noinline __attribute__((noinline))
#define BUILD_BUG_ON(condition) _Static_assert(!(condition), "original v1 ABI mismatch")
#define memzero_explicit(destination, length) memset((destination), 0, (length))

struct bio {
	bool lifetime_pinned;
	bool full_uncompressed_4096_swap_write;
};
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
struct swapz_round032_dm_owned_view_v1 {
	swapz_u64 source_swap_entry;
	swapz_u64 source_slot_epoch;
	swapz_u64 stored_entry_identity;
	swapz_u32 compressed_crc32c;
	swapz_u16 compressed_length;
	swapz_u16 decoded_length;
	swapz_u8 representation_version;
	swapz_u8 codec;
	swapz_u8 original_sha256[32];
};

/* Mock ONLY the original kernel exported BIO boundary. The production
 * wrapper always contains the real source call and never a local stub.
 */
static struct swapz_ci_lz4_owned_view_v1 original_provider_view;
static u8 source_lz4_bytes[SWAPZ_MAX_COMPRESSED];
static u16 source_lz4_length;
static int injected_provider_errno, provider_calls;

static int swapz_ci_bio_snapshot_lz4_v1(
		const struct bio *source_bio,
		struct swapz_ci_lz4_owned_view_v1 *view,
		u8 *owned_destination, size_t capacity)
{
	++provider_calls;
	if (!source_bio || !source_bio->lifetime_pinned ||
	    !source_bio->full_uncompressed_4096_swap_write)
		return -ESTALE;
	if (injected_provider_errno)
		return injected_provider_errno;
	if (!view || !owned_destination || capacity < source_lz4_length)
		return -ENOSPC;
	memcpy(owned_destination, source_lz4_bytes, source_lz4_length);
	*view = original_provider_view;
	return 0;
}

/* ROUND033_DM_ORIGINAL_GPL_IMPORT_HOST_EXACT */

int main(void)
{
	struct bio pinned_bio = {
		.lifetime_pinned = true,
		.full_uncompressed_4096_swap_write = true
	};
	struct swapz_round032_dm_owned_view_v1 copied_view = { 0 };
	struct swapz_round032_dm_owned_view_v1 untouched_view = { 0 };
	swapz_u8 original_page[SWAPZ_BLOCK_BYTES];
	swapz_u8 copied_lz4[SWAPZ_MAX_COMPRESSED];
	swapz_u8 owned_scratch[SWAPZ_MAX_COMPRESSED];
	swapz_u8 copied_before[SWAPZ_MAX_COMPRESSED];
	const size_t buffer_capacity = SWAPZ_MAX_COMPRESSED;
	int compressed_length;
	int result;
	unsigned int index;

	memset(original_page, 0x1e, sizeof(original_page));
	original_page[0] = 0x42;
	original_page[1024] = 0xc3;
	compressed_length = LZ4_compress_default(
		(const char *)original_page, (char *)source_lz4_bytes,
		(int)SWAPZ_BLOCK_BYTES, (int)SWAPZ_MAX_COMPRESSED);
	assert(compressed_length > 0 && compressed_length <= SWAPZ_MAX_COMPRESSED);
	source_lz4_length = (u16)compressed_length;
	original_provider_view.source_swap_entry = 0x110025U; /* FULL packed, not DM page */
	original_provider_view.source_slot_epoch = 1001U;
	original_provider_view.stored_entry_identity = 3003U;
	original_provider_view.compressed_crc32c = swapz_crc32c_bytes(
		source_lz4_bytes, source_lz4_length);
	original_provider_view.compressed_length = source_lz4_length;
	original_provider_view.decoded_length = SWAPZ_BLOCK_BYTES;
	original_provider_view.representation_version = 1U;
	original_provider_view.codec = 1U;
	assert(SHA256(original_page, SWAPZ_BLOCK_BYTES,
		      original_provider_view.original_sha256) != NULL);
	memset(copied_lz4, 0xa5, sizeof(copied_lz4));
	memset(owned_scratch, 0xa6, sizeof(owned_scratch));
	memset(&copied_view, 0x7b, sizeof(copied_view));

#define COPY() swapz_round033_dm_copy_original_bio_v1_for_link( \
	&pinned_bio, &copied_view, copied_lz4, buffer_capacity, \
	owned_scratch, buffer_capacity)
#define PREPARE_REFUSAL() do { \
	memset(copied_lz4, 0xa5, sizeof(copied_lz4)); \
	memset(&copied_view, 0x7b, sizeof(copied_view)); \
	memcpy(copied_before, copied_lz4, sizeof(copied_before)); \
	memcpy(&untouched_view, &copied_view, sizeof(untouched_view)); \
} while (0)
#define ASSERT_REFUSED_UNCHANGED() do { \
	assert(COPY() < 0); \
	assert(memcmp(copied_lz4, copied_before, sizeof(copied_lz4)) == 0); \
	assert(memcmp(&copied_view, &untouched_view, sizeof(copied_view)) == 0); \
	for (index = 0U; index < sizeof(owned_scratch); ++index) \
		assert(owned_scratch[index] == 0U); \
} while (0)

	assert(COPY() == 0);
	assert(memcmp(copied_lz4, source_lz4_bytes, source_lz4_length) == 0);
	assert(copied_view.source_swap_entry == 0x110025U);
	assert(copied_view.source_slot_epoch == 1001U);
	assert(copied_view.stored_entry_identity == 3003U);
	assert(copied_view.compressed_length == source_lz4_length);
	assert(copied_view.compressed_crc32c ==
	       swapz_crc32c_bytes(copied_lz4, copied_view.compressed_length));
	assert(memcmp(copied_view.original_sha256,
		      original_provider_view.original_sha256, 32U) == 0);
	for (index = 0U; index < sizeof(owned_scratch); ++index)
		assert(owned_scratch[index] == 0U);
	assert(swapz_round033_dm_try_live_original_bio_v1(&pinned_bio) == -EOPNOTSUPP);
	/* Source original private owner can retire; successful DM-owned value
	 * and byte-copy persist independently with no pointer to it.
	 */
	pinned_bio.lifetime_pinned = false;
	assert(copied_view.source_swap_entry == 0x110025U);
	assert(memcmp(copied_lz4, source_lz4_bytes, source_lz4_length) == 0);
	PREPARE_REFUSAL();
	ASSERT_REFUSED_UNCHANGED(); /* Late BIO completion */
	pinned_bio.lifetime_pinned = true;
	pinned_bio.full_uncompressed_4096_swap_write = false;
	PREPARE_REFUSAL();
	ASSERT_REFUSED_UNCHANGED(); /* Normal WRITE/READ/non-swap */
	pinned_bio.full_uncompressed_4096_swap_write = true;
	injected_provider_errno = -EIO;
	PREPARE_REFUSAL();
	ASSERT_REFUSED_UNCHANGED(); /* Lower/provider error */
	injected_provider_errno = 0;

	original_provider_view.source_swap_entry = 0U;
	PREPARE_REFUSAL();
	ASSERT_REFUSED_UNCHANGED();
	original_provider_view.source_swap_entry = 0x110025U;
	original_provider_view.source_slot_epoch = 0U;
	PREPARE_REFUSAL();
	ASSERT_REFUSED_UNCHANGED();
	original_provider_view.source_slot_epoch = 1001U;
	original_provider_view.stored_entry_identity = 0U;
	PREPARE_REFUSAL();
	ASSERT_REFUSED_UNCHANGED();
	original_provider_view.stored_entry_identity = 3003U;
	original_provider_view.representation_version = 2U;
	PREPARE_REFUSAL();
	ASSERT_REFUSED_UNCHANGED();
	original_provider_view.representation_version = 1U;
	original_provider_view.codec = 2U; /* not stored LZ4 */
	PREPARE_REFUSAL();
	ASSERT_REFUSED_UNCHANGED();
	original_provider_view.codec = 1U;
	original_provider_view.decoded_length = 4095U;
	PREPARE_REFUSAL();
	ASSERT_REFUSED_UNCHANGED();
	original_provider_view.decoded_length = SWAPZ_BLOCK_BYTES;
	original_provider_view.compressed_length = 0U;
	PREPARE_REFUSAL();
	ASSERT_REFUSED_UNCHANGED();
	original_provider_view.compressed_length = 3569U;
	PREPARE_REFUSAL();
	ASSERT_REFUSED_UNCHANGED();
	original_provider_view.compressed_length = source_lz4_length;
	original_provider_view.compressed_crc32c ^= 1U;
	PREPARE_REFUSAL();
	ASSERT_REFUSED_UNCHANGED();
	original_provider_view.compressed_crc32c ^= 1U;
	source_lz4_bytes[0] ^= 1U;
	PREPARE_REFUSAL();
	ASSERT_REFUSED_UNCHANGED();
	source_lz4_bytes[0] ^= 1U;
	original_provider_view.original_sha256[0] = 0U;
	for (index = 1U; index < sizeof(original_provider_view.original_sha256);
	     ++index)
		original_provider_view.original_sha256[index] = 0U;
	PREPARE_REFUSAL();
	ASSERT_REFUSED_UNCHANGED();
	assert(SHA256(original_page, SWAPZ_BLOCK_BYTES,
		      original_provider_view.original_sha256) != NULL);
	assert(COPY() == 0);

	/* No mutable destination view overlap or source alias accepted. */
	assert(swapz_round033_dm_copy_original_bio_v1_for_link(
		&pinned_bio, &copied_view, copied_lz4, buffer_capacity,
		copied_lz4, buffer_capacity) == -EINVAL);
	assert(swapz_round033_dm_copy_original_bio_v1_for_link(
		&pinned_bio, &copied_view, copied_lz4, buffer_capacity,
		owned_scratch, buffer_capacity - 1U) == -EMSGSIZE);
	assert(swapz_round033_dm_copy_original_bio_v1_for_link(
		&pinned_bio, &copied_view, copied_lz4, 20U,
		owned_scratch, buffer_capacity) == -EMSGSIZE);
	assert(provider_calls > 10);
	assert(swapz_round033_dm_try_live_original_bio_v1(NULL) == -EOPNOTSUPP);
#undef COPY
#undef PREPARE_REFUSAL
#undef ASSERT_REFUSED_UNCHANGED
	puts("ROUND033_ACTUAL_DM_ORIGINAL_GPL_COPY_SOURCE_HOST_GCC_CLANG_LIVE_NO_GO_PASS");
	return 0;
}
