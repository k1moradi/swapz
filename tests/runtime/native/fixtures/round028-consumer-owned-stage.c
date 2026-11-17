/* Strict source-extracted Round028 DM lower-image staging. No devices. */
#define SWAPZ_ZSWAP_IMPORT_HOST_TEST 1
#define SWAPZ_ZSWAP_ADMISSION_HOST_TEST 1
#include "zswap-import-admission.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define __used __attribute__((used))
#define noinline __attribute__((noinline))

/* ROUND028_DM_EXACT_STAGE_SOURCE */

static swapz_u8 original[SWAPZ_BLOCK_BYTES];
static swapz_u8 compressed[SWAPZ_MAX_COMPRESSED];
static swapz_u8 image[4U * SWAPZ_BLOCK_BYTES];
static swapz_u8 scratch[SWAPZ_BLOCK_BYTES];
static swapz_u8 output[SWAPZ_BLOCK_BYTES];

int main(void)
{
	struct swapz_zswap_admission_transaction transaction = { 0 };
	struct swapz_zswap_import_read_authority authority = { 0 };
	const swapz_u32 extent_sizes[] = {
		SWAPZ_BLOCK_BYTES, 2U * SWAPZ_BLOCK_BYTES,
		4U * SWAPZ_BLOCK_BYTES
	};
	int compressed_length;
	unsigned int extent_index;
	swapz_u32 offset;
	swapz_u32 index;

	assert(swapz_zswap_admission_try_live(&transaction) == -EOPNOTSUPP);
	for (index = 0; index < SWAPZ_BLOCK_BYTES; ++index)
		original[index] = (swapz_u8)(index % 251U);
	compressed_length = LZ4_compress_default(
		(const char *)original, (char *)compressed,
		(int)SWAPZ_BLOCK_BYTES, (int)SWAPZ_MAX_COMPRESSED);
	assert(compressed_length > 0);
	transaction.phase = SWAPZ_ZSWAP_ADMISSION_PREPARED;
	transaction.owned_compressed_bytes = compressed;
	transaction.record.compressed_length = (swapz_u32)compressed_length;
	transaction.record.compressed_crc32c =
		swapz_crc32c_bytes(compressed, (swapz_u32)compressed_length);
	transaction.record.decoded_length = SWAPZ_BLOCK_BYTES;
	transaction.record.immutable_owned_copy = 1U;
	transaction.record.stored_eviction = 1U;
	transaction.record.representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION;
	transaction.record.codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC;
	transaction.record.version = SWAPZ_ZSWAP_IMPORT_VERSION;
	transaction.record.logical_page = 5U;
	transaction.record.generation = 8U;
	transaction.record.gc_epoch = 11U;
	transaction.record.stored_entry_identity = 20U;
	transaction.record.store_generation = 30U;
	assert(SHA256(original, SWAPZ_BLOCK_BYTES,
		transaction.record.original_sha256));
	authority.logical_page = 5U;
	authority.generation = 8U;
	authority.gc_epoch = 11U;
	authority.stored_entry_identity = 20U;
	authority.store_generation = 30U;
	authority.mapping_published_after_durable_write = 1U;
	authority.foreground_write_committed_once = 1U;
	authority.upper_write_ack_count = 1U;
	authority.current_owned_ram_session = 1U;
	authority.actual_lower_read_bytes = (swapz_u32)compressed_length;
	for (extent_index = 0U; extent_index < 3U; ++extent_index) {
		transaction.physical_extent_bytes = extent_sizes[extent_index];
		offset = extent_sizes[extent_index] -
			(swapz_u32)compressed_length;
		transaction.compressed_payload_offset = offset;
		memset(image, 0xa5, sizeof(image));
		assert(swapz_round028_dm_stage_owned_payload(
			&transaction, compressed, (swapz_u32)compressed_length,
			image, extent_sizes[extent_index]) == 0);
		for (index = 0; index < extent_sizes[extent_index]; ++index) {
			const swapz_u8 expected =
				(index >= offset) ? compressed[index - offset] : 0U;
			assert(image[index] == expected);
		}
		for (; index < sizeof(image); ++index)
			assert(image[index] == 0xa5U);
		memset(output, 0xa5, sizeof(output));
		assert(swapz_zswap_import_decode(&transaction.record,
			&authority, image + offset,
			(swapz_u32)compressed_length, scratch, sizeof(scratch),
			output, sizeof(output), original) == 0);
		assert(memcmp(output, original, sizeof(output)) == 0);
	}
	memset(image, 0xa5, sizeof(image));
	assert(swapz_round028_dm_stage_owned_payload(
		&transaction, compressed, 1U, image, sizeof(image)) == -EMSGSIZE);
	assert(image[0] == 0xa5U);
	transaction.record.compressed_crc32c ^= 1U;
	assert(swapz_round028_dm_stage_owned_payload(
		&transaction, compressed, (swapz_u32)compressed_length,
		image, sizeof(image)) == -EBADMSG);
	assert(image[0] == 0xa5U);
	transaction.record.compressed_crc32c ^= 1U;
	transaction.phase = SWAPZ_ZSWAP_ADMISSION_DISCARDED;
	assert(swapz_round028_dm_stage_owned_payload(
		&transaction, compressed, (swapz_u32)compressed_length,
		image, sizeof(image)) == -EOPNOTSUPP);
	transaction.phase = SWAPZ_ZSWAP_ADMISSION_PREPARED;
	transaction.teardown_started = 1U;
	assert(swapz_round028_dm_stage_owned_payload(
		&transaction, compressed, (swapz_u32)compressed_length,
		image, sizeof(image)) == -EOPNOTSUPP);
	transaction.teardown_started = 0U;
	transaction.physical_extent_bytes = SWAPZ_BLOCK_BYTES;
	transaction.compressed_payload_offset = 0U;
	assert(swapz_round028_dm_stage_owned_payload(
		&transaction, compressed, (swapz_u32)compressed_length,
		compressed, SWAPZ_BLOCK_BYTES) == -EINVAL);
	puts("ROUND028_DM_EXACT_OWNED_STAGE_NO_LIVE_PASS");
	return 0;
}
