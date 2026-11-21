// SPDX-License-Identifier: GPL-2.0-only
/*
 * ROOTLESS source-only imported original codec read contract.
 * Link actual pristine Linux lib/lzo source, actual swapz codec.c CRC32C,
 * and existing independent raw LZ4. This never publishes production maps,
 * completes BIOs, owns a live source pool, or touches a swap device.
 */
#define SWAPZ_ZSWAP_IMPORT_HOST_TEST 1
/* Only this fixture stages pristine pinned Linux LZO headers and objects. */
#define SWAPZ_ZSWAP_IMPORT_ORIGINAL_LZO_HOST_TEST 1
#include "zswap-import-codec.h"
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define CHECK(condition) do { \
	if (!(condition)) { \
		fprintf(stderr, "ROUND058_IMPORT_CODEC_FIRST_ERROR line=%u %s\n", \
			(unsigned int)__LINE__, #condition); \
		return 1; \
	} \
} while (0)

#define SOURCE_OFFSETS 8U
#define PATTERN_COUNT 16U

static void fill_original(swapz_u8 original[SWAPZ_BLOCK_BYTES],
			  unsigned int seed)
{
	swapz_u32 state = 0x9e3779b9U ^ seed;
	unsigned int index;

	for (index = 0; index < SWAPZ_BLOCK_BYTES; ++index) {
		state = state * 1664525U + 1013904223U;
		switch (seed % 4U) {
		case 0U:
			original[index] = 0U;
			break;
		case 1U:
			original[index] = (swapz_u8)(seed & 0xffU);
			break;
		case 2U:
			original[index] = (swapz_u8)((index / 64U + seed) & 0x0fU);
			break;
		default:
			original[index] = (swapz_u8)(state >> 24U);
			break;
		}
	}
}

static int output_is_sentinel(const swapz_u8 output[SWAPZ_BLOCK_BYTES])
{
	unsigned int index;

	for (index = 0; index < SWAPZ_BLOCK_BYTES; ++index)
		if (output[index] != 0xa5U)
			return 0;
	return 1;
}

static void fill_read_authority(
	struct swapz_zswap_import_read_authority *authority,
	const struct swapz_zswap_import_record *record)
{
	*authority = (struct swapz_zswap_import_read_authority) {
		.logical_page = record->logical_page,
		.generation = record->generation,
		.stored_entry_identity = record->stored_entry_identity,
		.store_generation = record->store_generation,
		.gc_epoch = record->gc_epoch,
		.actual_lower_read_bytes = record->compressed_length,
		.mapping_published_after_durable_write = 1U,
		.foreground_write_committed_once = 1U,
		.upper_write_ack_count = 1U,
		.current_owned_ram_session = 1U,
	};
}

int main(void)
{
	swapz_u8 original_storage[SWAPZ_BLOCK_BYTES + SOURCE_OFFSETS];
	swapz_u8 compressed_storage[SWAPZ_BLOCK_BYTES * 2U + SOURCE_OFFSETS];
	swapz_u8 scratch_storage[SWAPZ_BLOCK_BYTES + SOURCE_OFFSETS];
	swapz_u8 output_storage[SWAPZ_BLOCK_BYTES + SOURCE_OFFSETS];
	_Alignas(unsigned short) swapz_u8 workspace[LZO1X_1_MEM_COMPRESS];
	unsigned int decoded_pages[2] = { 0U, 0U };
	unsigned int codec_index;
	unsigned int seed;
	unsigned int alignment;

	CHECK(SWAPZ_ZSWAP_IMPORT_ACTIVE == 0U);
	CHECK(SWAPZ_CODEC_METADATA_ON_MEDIA == 0U);
	CHECK(SWAPZ_MAX_COMPRESSED == 3568U);
	for (codec_index = 0; codec_index < 2U; ++codec_index) {
		for (seed = 0; seed < PATTERN_COUNT; ++seed) {
			for (alignment = 0; alignment < SOURCE_OFFSETS; ++alignment) {
				struct swapz_zswap_import_record record = {
					.logical_page = (swapz_u64)seed + 1U,
					.generation = 11U,
					.stored_entry_identity = 31U,
					.store_generation = 47U,
					.gc_epoch = 53U,
					.decoded_length = SWAPZ_BLOCK_BYTES,
					.representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION,
					.codec = codec_index == 0U ?
						SWAPZ_ZSWAP_IMPORT_LZ4_CODEC :
						SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC,
					.version = codec_index == 0U ?
						SWAPZ_ZSWAP_IMPORT_VERSION :
						SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION,
					.stored_eviction = 1U,
					.immutable_owned_copy = 1U,
				};
				struct swapz_zswap_import_read_authority authority;
				swapz_u8 *original = original_storage + alignment;
				swapz_u8 *compressed = compressed_storage + alignment;
				swapz_u8 *scratch = scratch_storage +
					(SOURCE_OFFSETS - 1U - alignment);
				swapz_u8 *output = output_storage + alignment;
				size_t lzo_length = sizeof(compressed_storage) -
					SOURCE_OFFSETS;
				int lz4_length;

				fill_original(original, seed);
				if (record.codec == SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC) {
					CHECK(lzo1x_1_compress_safe(
						original, SWAPZ_BLOCK_BYTES, compressed,
						&lzo_length, workspace) == LZO_E_OK);
					CHECK(lzo_length <= UINT32_MAX);
					record.compressed_length = (swapz_u32)lzo_length;
				} else {
					lz4_length = LZ4_compress_default(
						(const char *)original, (char *)compressed,
						(int)SWAPZ_BLOCK_BYTES,
						(int)sizeof(compressed_storage) -
							(int)SOURCE_OFFSETS);
					CHECK(lz4_length > 0);
					record.compressed_length = (swapz_u32)lz4_length;
				}
				/* Excluded incompressible pages keep normal full RAW. */
				if (!record.compressed_length ||
				    record.compressed_length > SWAPZ_MAX_COMPRESSED)
					continue;
				CHECK(SHA256(original, SWAPZ_BLOCK_BYTES,
					     record.original_sha256) != NULL);
				record.compressed_crc32c = swapz_crc32c_bytes(
					compressed, record.compressed_length);
				fill_read_authority(&authority, &record);

#define READ_BACK() swapz_zswap_import_decode( \
				&record, &authority, compressed, \
				(swapz_u32)(sizeof(compressed_storage) - SOURCE_OFFSETS), \
				scratch, SWAPZ_BLOCK_BYTES, output, \
				SWAPZ_BLOCK_BYTES, original)
#define REJECT(expected) do { \
				memset(output, 0xa5, SWAPZ_BLOCK_BYTES); \
				CHECK(READ_BACK() == (expected)); \
				CHECK(output_is_sentinel(output)); \
			} while (0)
				memset(output, 0xa5, SWAPZ_BLOCK_BYTES);
				CHECK(READ_BACK() == 0);
				CHECK(memcmp(output, original, SWAPZ_BLOCK_BYTES) == 0);
				decoded_pages[codec_index]++;

				record.original_sha256[0] ^= 1U;
				REJECT(-EBADMSG);
				record.original_sha256[0] ^= 1U;

				record.compressed_crc32c ^= 1U;
				REJECT(-EBADMSG);
				record.compressed_crc32c ^= 1U;

				record.dictionary_id = 1U;
				REJECT(-EOPNOTSUPP);
				record.dictionary_id = 0U;
				record.codec = 0xffU;
				REJECT(-EOPNOTSUPP);
				record.codec = codec_index == 0U ?
					SWAPZ_ZSWAP_IMPORT_LZ4_CODEC :
					SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC;
				record.version = 2U;
				REJECT(-EOPNOTSUPP);
				record.version = SWAPZ_ZSWAP_IMPORT_VERSION;

				record.compressed_length = SWAPZ_MAX_COMPRESSED + 1U;
				REJECT(-EMSGSIZE);
				record.compressed_length = authority.actual_lower_read_bytes;

				authority.upper_write_ack_count = 2U;
				REJECT(-ESTALE);
				authority.upper_write_ack_count = 1U;
				authority.teardown_started = 1U;
				REJECT(-ESTALE);
				authority.teardown_started = 0U;
				authority.actual_lower_read_bytes--;
				REJECT(-EIO);
				authority.actual_lower_read_bytes++;
				authority.lower_read_error = -EIO;
				REJECT(-EIO);
				authority.lower_read_error = 0;
				authority.store_generation++;
				REJECT(-ESTALE);
				authority.store_generation--;

				/* The original LZO implementation has a strict EOF gate:
				 * successful full-page output plus any extra byte is
				 * LZO_E_INPUT_NOT_CONSUMED, not a valid imported read. */
				if (record.codec == SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC &&
				    record.compressed_length < SWAPZ_MAX_COMPRESSED) {
					const swapz_u32 original_length =
						record.compressed_length;
					const swapz_u32 original_crc =
						record.compressed_crc32c;

					compressed[original_length] = 0x7dU;
					record.compressed_length++;
					record.compressed_crc32c = swapz_crc32c_bytes(
						compressed, record.compressed_length);
					authority.actual_lower_read_bytes++;
					REJECT(-EBADMSG);
					authority.actual_lower_read_bytes--;
					record.compressed_length = original_length;
					record.compressed_crc32c = original_crc;
				}
#undef REJECT
#undef READ_BACK
			}
		}
	}
	CHECK(decoded_pages[0] >= 80U);
	CHECK(decoded_pages[1] >= 80U);
	printf("ROUND058_ORIGINAL_IMPORTED_READ_4096_PASS lz4_pages=%u "
	       "lzo_pages=%u offsets=8 immutable_output=YES "
	       "original_source=PINNED full_crc_sha=YES "
	       "source_authenticated=0 phase_a=BLOCKED active=0 physical_io=0\n",
	       decoded_pages[0], decoded_pages[1]);
	return 0;
}
