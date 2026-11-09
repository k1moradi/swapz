// SPDX-License-Identifier: GPL-2.0-only
/* Test the production data-only builder with separately owned volatile RAM
 * metadata. No block devices, filesystem or Linux swap state are touched.
 */
#include "codec.h"
#include <errno.h>
#include <stdio.h>
#include <string.h>

#define CHECK(condition) do { \
	if (!(condition)) { \
		fprintf(stderr, "FAIL: %s at line %d\n", #condition, __LINE__); \
		return 1; \
	} \
} while (0)

static swapz_u8 image[SWAPZ_MAX_EXTENT_BYTES];
static swapz_u8 payload[SWAPZ_MAX_COMPRESSED];
static struct swapz_decoded records[SWAPZ_MAX_RECORDS];
static union {
	struct swapz_decoded records[SWAPZ_MAX_RECORDS];
	swapz_u8 bytes[SWAPZ_MAX_EXTENT_BYTES];
} overlapping_storage;

static void set_payload(swapz_u16 length, swapz_u8 salt)
{
	swapz_u16 index;

	for (index = 0; index < length; ++index)
		payload[index] = (swapz_u8)((index * 37U + salt * 17U) & 255U);
}

static int test_class(swapz_u32 bytes_total)
{
	struct swapz_ram_extent builder;
	const swapz_u8 *readback = NULL;
	swapz_u16 index;
	swapz_u32 crc;
	const swapz_u8 old_padding = 0xa5U;

	memset(image, old_padding, sizeof(image));
	memset(records, old_padding, sizeof(records));
	set_payload(600, 3);
	CHECK(swapz_ram_extent_begin(&builder, image, bytes_total, 42,
				     records, SWAPZ_MAX_RECORDS) == 0);
	CHECK(builder.count == 0 && !builder.sealed);
	CHECK(image[0] == old_padding);
	crc = swapz_crc32c_bytes(payload, 600);
	CHECK(swapz_ram_extent_append_prehashed(&builder, 21, 7, payload, 600,
						crc, SWAPZ_ENCODING_DELTA64_SHUF8) == 0);
	CHECK(swapz_ram_extent_append(&builder, 21, 8, payload, 600,
				     SWAPZ_ENCODING_LZ4) == -EEXIST);
	CHECK(swapz_ram_extent_append(&builder, 22, 8, payload, 600,
				     SWAPZ_ENCODING_LZ4) == 0);
	CHECK(swapz_ram_extent_append(&builder, 23, 0, payload, 600,
				     SWAPZ_ENCODING_LZ4) == -EINVAL);
	CHECK(swapz_ram_extent_append(&builder, 23, 9, image + 100, 600,
				     SWAPZ_ENCODING_LZ4) == -EINVAL);
	CHECK(swapz_ram_extent_read(&builder, 0, 21, 7, &readback) == -EINVAL);
	CHECK(swapz_ram_extent_seal(&builder) == 0);
	CHECK(swapz_ram_extent_seal(&builder) == -EINVAL);
	CHECK(swapz_ram_extent_append(&builder, 23, 9, payload, 600,
				     SWAPZ_ENCODING_LZ4) == -EINVAL);
	for (index = 0; index < builder.payload_start; ++index)
		CHECK(image[index] == 0);
	CHECK(records[0].payload_crc32c == crc);
	CHECK(records[0].payload_offset == bytes_total - 600U);
	CHECK(records[1].payload_offset == bytes_total - 1200U);
	CHECK(swapz_ram_extent_read(&builder, 0, 21, 7, &readback) == 0);
	CHECK(readback == image + records[0].payload_offset);
	CHECK(memcmp(readback, payload, 600) == 0);
	CHECK(swapz_ram_extent_read(&builder, 0, 21, 8, &readback) == -EUCLEAN);
	CHECK(readback == NULL);
	CHECK(swapz_ram_extent_read(&builder, 1, 22, 8, &readback) == 0);
	CHECK(memcmp(readback, payload, 600) == 0);
	image[records[0].payload_offset] ^= 0x80U;
	CHECK(swapz_ram_extent_read(&builder, 0, 21, 7, &readback) == -EBADMSG);
	CHECK(readback == NULL);
	image[records[0].payload_offset] ^= 0x80U;
	records[0].payload_offset = 0;
	CHECK(swapz_ram_extent_read(&builder, 0, 21, 7, &readback) == -EUCLEAN);
	return 0;
}

static int test_full_and_reject(void)
{
	struct swapz_ram_extent builder;
	const swapz_u8 *readback = NULL;
	swapz_u32 index;

	CHECK(swapz_ram_extent_begin(NULL, image, SWAPZ_BLOCK_BYTES,
				     1, records, 1) == -EINVAL);
	CHECK(swapz_ram_extent_begin(&builder, image, SWAPZ_BLOCK_BYTES,
				     0, records, 1) == -EINVAL);
	CHECK(swapz_ram_extent_begin(&builder, image, 3 * SWAPZ_BLOCK_BYTES,
				     1, records, 1) == -EINVAL);
	CHECK(swapz_ram_extent_begin(&builder, image, SWAPZ_BLOCK_BYTES,
				     1, records, 0) == -EINVAL);
	memset(overlapping_storage.bytes, 0x6b, SWAPZ_BLOCK_BYTES);
	CHECK(swapz_ram_extent_begin(
		      &builder, overlapping_storage.bytes, SWAPZ_BLOCK_BYTES,
		      1, overlapping_storage.records, 1) == -EINVAL);
	CHECK(overlapping_storage.bytes[0] == 0x6b);
	CHECK(swapz_ram_extent_begin(&builder, image, SWAPZ_BLOCK_BYTES,
				     1, records, 1) == 0);
	CHECK(swapz_ram_extent_seal(&builder) == -EINVAL);
	set_payload(4, 5);
	CHECK(swapz_ram_extent_append(&builder, 0, 1, payload, 4,
				     SWAPZ_ENCODING_LZ4) == 0);
	CHECK(swapz_ram_extent_append(&builder, 1, 1, payload, 4,
				     SWAPZ_ENCODING_LZ4) == -ENOSPC);
	CHECK(swapz_ram_extent_seal(&builder) == 0);
	CHECK(swapz_ram_extent_read(&builder, 1, 1, 1, &readback) == -EINVAL);
	CHECK(readback == NULL);

	CHECK(swapz_ram_extent_begin(&builder, image, SWAPZ_MAX_EXTENT_BYTES,
				     1, records, SWAPZ_MAX_RECORDS) == 0);
	set_payload(1, 11);
	for (index = 0; index < SWAPZ_MAX_RECORDS; ++index)
		CHECK(swapz_ram_extent_append(&builder, index, index + 1U,
					      payload, 1,
					      SWAPZ_ENCODING_LZ4) == 0);
	CHECK(swapz_ram_extent_append(&builder, 100, 1, payload, 1,
				     SWAPZ_ENCODING_LZ4) == -ENOSPC);
	CHECK(swapz_ram_extent_seal(&builder) == 0);
	for (index = 0; index < SWAPZ_MAX_RECORDS; ++index)
		CHECK(swapz_ram_extent_read(&builder, (swapz_u8)index, index,
					    index + 1U, &readback) == 0);
	return 0;
}

int main(void)
{
	CHECK(test_class(SWAPZ_BLOCK_BYTES) == 0);
	CHECK(test_class(2U * SWAPZ_BLOCK_BYTES) == 0);
	CHECK(test_class(SWAPZ_MAX_EXTENT_BYTES) == 0);
	CHECK(test_full_and_reject() == 0);
	puts("PASS: data-only 4/8/16KiB payload packing and RAM-only metadata");
	return 0;
}
