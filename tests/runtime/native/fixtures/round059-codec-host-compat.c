// SPDX-License-Identifier: GPL-2.0-only
/*
 * Actual dormant imported decoder C in GENERIC LZ4-only host mode.
 * Do NOT include original Linux LZO headers or link its decoder. The
 * separate selected LZO profile is covered by pristine pinned Linux C.
 */
#define SWAPZ_ZSWAP_IMPORT_HOST_TEST 1
#include "zswap-import-codec.h"
#include <stdio.h>

#define CHECK(condition) do { \
	if (!(condition)) { \
		fprintf(stderr, "ROUND059_CODEC_HOST_FIRST_ERROR line=%u %s\n", \
			(unsigned int)__LINE__, #condition); \
		return 1; \
	} \
} while (0)

static int output_is_unchanged(const swapz_u8 *output)
{
	unsigned int index;

	for (index = 0; index < SWAPZ_BLOCK_BYTES; ++index)
		if (output[index] != 0xa5U)
			return 0;
	return 1;
}

static void fill_page(swapz_u8 *page, unsigned int pattern)
{
	unsigned int index;

	for (index = 0; index < SWAPZ_BLOCK_BYTES; ++index)
		page[index] = (swapz_u8)((index / (32U + pattern * 8U) +
					  pattern) % (8U + pattern));
}

int main(void)
{
	swapz_u8 original_buffer[SWAPZ_BLOCK_BYTES + 8U];
	swapz_u8 compressed_buffer[SWAPZ_BLOCK_BYTES * 2U + 8U];
	swapz_u8 scratch_buffer[SWAPZ_BLOCK_BYTES + 8U];
	swapz_u8 output_buffer[SWAPZ_BLOCK_BYTES + 8U];
	unsigned int pattern;
	unsigned int alignment;
	unsigned int accepted = 0U;
	unsigned int lzo_rejected = 0U;

	CHECK(SWAPZ_ZSWAP_IMPORT_ACTIVE == 0U);
	CHECK(SWAPZ_CODEC_METADATA_ON_MEDIA == 0U);

	for (pattern = 0; pattern < 4U; ++pattern) {
		for (alignment = 0; alignment < 8U; ++alignment) {
			swapz_u8 *original = original_buffer + alignment;
			swapz_u8 *compressed = compressed_buffer + alignment;
			swapz_u8 *scratch = scratch_buffer + (7U - alignment);
			swapz_u8 *output = output_buffer + alignment;
			struct swapz_zswap_import_record record = {
				.logical_page = 9U,
				.generation = 2U,
				.stored_entry_identity = 3U,
				.store_generation = 4U,
				.gc_epoch = 5U,
				.decoded_length = SWAPZ_BLOCK_BYTES,
				.representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION,
				.codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC,
				.version = SWAPZ_ZSWAP_IMPORT_VERSION,
				.stored_eviction = 1U,
				.immutable_owned_copy = 1U,
			};
			struct swapz_zswap_import_read_authority authority = {
				.logical_page = 9U,
				.generation = 2U,
				.stored_entry_identity = 3U,
				.store_generation = 4U,
				.gc_epoch = 5U,
				.mapping_published_after_durable_write = 1U,
				.foreground_write_committed_once = 1U,
				.upper_write_ack_count = 1U,
				.current_owned_ram_session = 1U,
			};
			int compressed_length;

			fill_page(original, pattern);
			compressed_length = LZ4_compress_default(
				(const char *)original, (char *)compressed,
				(int)SWAPZ_BLOCK_BYTES, (int)sizeof(compressed_buffer) - 8);
			CHECK(compressed_length > 0);
			CHECK((unsigned int)compressed_length <= SWAPZ_MAX_COMPRESSED);
			record.compressed_length = (swapz_u32)compressed_length;
			authority.actual_lower_read_bytes = record.compressed_length;
			record.compressed_crc32c = swapz_crc32c_bytes(
				compressed, record.compressed_length);
			CHECK(SHA256(original, SWAPZ_BLOCK_BYTES,
				     record.original_sha256) != NULL);

#define READ_BACK() swapz_zswap_import_decode( \
				&record, &authority, compressed, \
				(swapz_u32)(sizeof(compressed_buffer) - 8U), \
				scratch, SWAPZ_BLOCK_BYTES, output, \
				SWAPZ_BLOCK_BYTES, original)
#define EXPECT_REJECT(expected) do { \
				memset(output, 0xa5, SWAPZ_BLOCK_BYTES); \
				CHECK(READ_BACK() == (expected)); \
				CHECK(output_is_unchanged(output)); \
			} while (0)

			memset(output, 0xa5, SWAPZ_BLOCK_BYTES);
			CHECK(READ_BACK() == 0);
			CHECK(memcmp(output, original, SWAPZ_BLOCK_BYTES) == 0);
			accepted++;

			/* A selected LZO record cannot execute or link LZO here. */
			record.codec = SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC;
			EXPECT_REJECT(-EOPNOTSUPP);
			lzo_rejected++;
			record.codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC;

			record.compressed_crc32c ^= 1U;
			EXPECT_REJECT(-EBADMSG);
			record.compressed_crc32c ^= 1U;

			record.original_sha256[0] ^= 1U;
			EXPECT_REJECT(-EBADMSG);
			record.original_sha256[0] ^= 1U;

			record.dictionary_id = 1U;
			EXPECT_REJECT(-EOPNOTSUPP);
			record.dictionary_id = 0U;

			record.compressed_length = SWAPZ_MAX_COMPRESSED + 1U;
			EXPECT_REJECT(-EMSGSIZE);
			record.compressed_length = authority.actual_lower_read_bytes;

			authority.upper_write_ack_count = 2U;
			EXPECT_REJECT(-ESTALE);
			authority.upper_write_ack_count = 1U;

			authority.teardown_started = 1U;
			EXPECT_REJECT(-ESTALE);
			authority.teardown_started = 0U;

			/* Even with correct CRC+SHA the input must remain disjoint. */
			memset(output, 0xa5, SWAPZ_BLOCK_BYTES);
			CHECK(swapz_zswap_import_decode(
				&record, &authority, compressed,
				(swapz_u32)(sizeof(compressed_buffer) - 8U),
				output, SWAPZ_BLOCK_BYTES, output,
				SWAPZ_BLOCK_BYTES, original) == -EINVAL);
			CHECK(output_is_unchanged(output));
#undef READ_BACK
#undef EXPECT_REJECT
		}
	}
	CHECK(accepted == 32U && lzo_rejected == 32U);
	printf("ROUND059_GENERIC_LZ4_ONLY_HOST_PASS full_original_4096=%u "
	       "selected_lzo_unsupported=%u offsets=8 no_linux_lzo_header=YES "
	       "no_lzo_symbol=YES crc_sha=YES immutable_failure=YES "
	       "source_authenticated=0 active=0 physical_io=0\n",
	       accepted, lzo_rejected);
	return 0;
}
