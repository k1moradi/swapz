// SPDX-License-Identifier: GPL-2.0-only
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include "authority.h"
#include "zswap-original-extent.h"

_Static_assert(sizeof(struct swapz_map) == 20, "ordinary map");
_Static_assert(SWAPZ_ORIGINAL_EXTENT_ACTIVE == 0, "disabled");
_Static_assert(SWAPZ_MAX_COMPRESSED == 3568, "ordinary limit");

static unsigned int checks;
#define CHECK(expr) do { ++checks; if (!(expr)) { \
	fprintf(stderr, "SEMANTIC_FAIL line=%d %s\n", __LINE__, #expr); \
	exit(77); } } while (0)

static struct swapz_original_extent extent;
static struct swapz_original_extent_record records[65], planned;
static swapz_u8 image[SWAPZ_MAX_EXTENT_BYTES], payload[SWAPZ_MAX_EXTENT_BYTES];
static unsigned char old_extent[sizeof(extent)], old_records[sizeof(records)];
static unsigned char old_image[sizeof(image)], old_plan[sizeof(planned)];

static void snapshot(void)
{
	memcpy(old_extent, &extent, sizeof(extent));
	memcpy(old_records, records, sizeof(records));
	memcpy(old_image, image, sizeof(image));
	memcpy(old_plan, &planned, sizeof(planned));
}

static void unchanged(void)
{
	CHECK(!memcmp(old_extent, &extent, sizeof(extent)));
	CHECK(!memcmp(old_records, records, sizeof(records)));
	CHECK(!memcmp(old_image, image, sizeof(image)));
	CHECK(!memcmp(old_plan, &planned, sizeof(planned)));
}

static void begin(swapz_u32 bytes, swapz_u32 capacity,
		  swapz_u32 ceiling, swapz_u8 mode)
{
	memset(image, 0xa5, sizeof(image));
	memset(records, 0x96, sizeof(records));
	memset(&planned, 0x39, sizeof(planned));
	CHECK(!swapz_original_extent_begin(&extent, image, bytes, records,
		capacity * sizeof(*records), capacity, ceiling, mode));
	CHECK(extent.occupied_bytes == 0 && extent.unused_bytes == bytes);
	CHECK(image[0] == 0xa5 && records[0].reserved[0] == 0x96);
}

static struct swapz_original_extent_input input(swapz_u32 length,
						swapz_u32 logical_page)
{
	struct swapz_original_extent_input value = {
		.bytes = payload, .bytes_available = length,
		.logical_page = logical_page, .generation = 17,
		.length = length, .decoded_length = SWAPZ_BLOCK_BYTES,
		.representation = SWAPZ_ORIGINAL_EXTENT_REPRESENTATION,
		.codec = SWAPZ_ORIGINAL_EXTENT_LZ4,
		.version = SWAPZ_ORIGINAL_EXTENT_VERSION,
	};
	if (length <= sizeof(payload))
		value.crc32c = swapz_crc32c_bytes(payload, length);
	return value;
}

static void reject(struct swapz_original_extent_input value)
{
	snapshot();
	CHECK(swapz_original_extent_plan(&extent, &value, &planned) < 0);
	unchanged();
	CHECK(swapz_original_extent_append(&extent, &value) < 0);
	unchanged();
}

static void append(swapz_u32 length, swapz_u32 logical, swapz_u32 offset,
		   swapz_u32 read_blocks)
{
	struct swapz_original_extent_input value = input(length, logical);
	swapz_u32 previous = extent.occupied_bytes;
	swapz_u32 index = extent.count;

	if (logical & 1U)
		value.codec = SWAPZ_ORIGINAL_EXTENT_LZO1X;
	snapshot();
	CHECK(!swapz_original_extent_plan(&extent, &value, &planned));
	CHECK(!memcmp(old_extent, &extent, sizeof(extent)));
	CHECK(!memcmp(old_records, records, sizeof(records)));
	CHECK(!memcmp(old_image, image, sizeof(image)));
	CHECK(planned.offset == offset && planned.length == length);
	CHECK(planned.first_block == offset / SWAPZ_BLOCK_BYTES);
	CHECK(planned.read_blocks == read_blocks);
	CHECK(planned.crc32c == value.crc32c && planned.codec == value.codec);
	CHECK(planned.generation == 17 && planned.logical_page == logical);
	CHECK(planned.representation == value.representation &&
	      planned.version == value.version);
	CHECK(!swapz_original_extent_append(&extent, &value));
	CHECK(extent.count == index + 1U && extent.occupied_bytes == previous + length);
	CHECK(extent.unused_bytes == extent.image_bytes - extent.occupied_bytes);
	CHECK(records[index].offset == offset && records[index].crc32c == value.crc32c);
	CHECK(!memcmp(image + offset, payload, length));
}

static void seal(void)
{
	swapz_u32 index, start, end;

	CHECK(!swapz_original_extent_seal(&extent));
	CHECK(extent.sealed == 1);
	start = extent.mode == SWAPZ_ORIGINAL_EXTENT_DEDICATED ?
		extent.occupied_bytes : 0U;
	end = start + extent.unused_bytes;
	for (index = start; index < end; ++index)
		CHECK(image[index] == 0);
	for (index = 0; index < extent.count; ++index) {
		const struct swapz_original_extent_record *record = &records[index];
		CHECK(!memcmp(image + record->offset, payload, record->length));
		CHECK(record->crc32c == swapz_crc32c_bytes(image + record->offset,
							 record->length));
	}
	snapshot();
	CHECK(swapz_original_extent_seal(&extent) < 0);
	unchanged();
	reject(input(1, 200));
}

static void bad_begin(swapz_u32 bytes, swapz_u32 capacity,
		      swapz_u32 ceiling, swapz_u8 mode, swapz_u32 record_bytes)
{
	snapshot();
	CHECK(swapz_original_extent_begin(&extent, image, bytes, records,
		record_bytes, capacity, ceiling, mode) < 0);
	unchanged();
}

int main(void)
{
	struct swapz_original_extent_input value;
	struct swapz_ram_extent ordinary;
	struct swapz_decoded ordinary_record;
	const swapz_u32 lengths[] = {1, 3568, 3569, 4095};
	swapz_u32 index, i;

	for (index = 0; index < sizeof(payload); ++index)
		payload[index] = (swapz_u8)(index * 31U + 17U);
	CHECK(swapz_crc32c_bytes("123456789", 9) == 0xe3069283U);
	begin(4096, 1, 3568, SWAPZ_ORIGINAL_EXTENT_DEDICATED);
	reject(input(3569, 1));
	append(3568, 0, 0, 1);
	reject(input(1, 1));
	seal();
	for (i = 0; i < sizeof(lengths) / sizeof(lengths[0]); ++i) {
		begin(4096, 1, 4095, SWAPZ_ORIGINAL_EXTENT_DEDICATED);
		append(lengths[i], i, 0, 1);
		seal();
	}
	begin(4096, 64, 4095, SWAPZ_ORIGINAL_EXTENT_PACKED);
	reject(input(0, 0));
	reject(input(4096, 0));
	reject(input(~(swapz_u32)0, 0));
	value = input(5, 1); value.representation = 0; reject(value);
	value = input(5, 1); value.codec = 3; reject(value);
	value = input(5, 1); value.version = 2; reject(value);
	value = input(5, 1); value.dictionary_id = 1; reject(value);
	value = input(5, 1); value.decoded_length = 4095; reject(value);
	value = input(5, 1); value.generation = 0; reject(value);
	value = input(5, 1); value.bytes_available = 4; reject(value);
	value = input(5, 1); value.bytes_available = 6; reject(value);
	value = input(5, 1); value.crc32c ^= 1U; reject(value);
	value = input(5, 1); value.bytes = NULL; reject(value);
	value = input(5, 1); value.bytes = image + 4;
	value.crc32c = swapz_crc32c_bytes(value.bytes, 5); reject(value);
	value = input(5, 1); value.bytes = (const swapz_u8 *)records;
	value.crc32c = swapz_crc32c_bytes(value.bytes, 5); reject(value);
	value = input(5, 1); value.bytes = (const swapz_u8 *)&extent;
	value.crc32c = swapz_crc32c_bytes(value.bytes, 5); reject(value);
	value = input(5, 1);
	snapshot();
	CHECK(swapz_original_extent_plan(&extent, &value, records) < 0);
	unchanged();
	CHECK(swapz_original_extent_plan(&extent, &value,
		(struct swapz_original_extent_record *)(void *)&value) < 0);
	unchanged();
	CHECK(swapz_original_extent_seal(&extent) < 0);
	unchanged();

	append(4095, 0, 1, 1);
	reject(input(1, 0));
	reject(input(2, 1));
	append(1, 1, 0, 1);
	seal();
	begin(4096, 64, 4095, SWAPZ_ORIGINAL_EXTENT_PACKED);
	append(3569, 1, 527, 1);
	append(527, 2, 0, 1);
	seal();
	begin(8192, 64, 4095, SWAPZ_ORIGINAL_EXTENT_PACKED);
	append(4095, 1, 4097, 1);
	append(4095, 2, 2, 2);
	append(1, 3, 1, 1);
	append(1, 4, 0, 1);
	seal();
	begin(16384, 64, 4095, SWAPZ_ORIGINAL_EXTENT_PACKED);
	append(3277, 1, 13107, 1);
	append(3277, 2, 9830, 2);
	append(3277, 3, 6553, 2);
	append(3277, 4, 3276, 2);
	reject(input(3277, 5));
	seal();
	begin(4096, 64, 4095, SWAPZ_ORIGINAL_EXTENT_PACKED);
	for (index = 0; index < 64; ++index)
		append(1, index, 4095U - index, 1);
	reject(input(1, 64));
	seal();

	begin(8192, 4, 4095, SWAPZ_ORIGINAL_EXTENT_PACKED);
	append(20, 1, 8172, 1);
	append(9, 2, 8163, 1);
	records[0].offset++;
	snapshot(); CHECK(swapz_original_extent_seal(&extent) < 0); unchanged();
	records[0].offset--;
	records[1].read_blocks++;
	snapshot(); CHECK(swapz_original_extent_seal(&extent) < 0); unchanged();
	records[1].read_blocks--;
	records[1].logical_page = 1;
	snapshot(); CHECK(swapz_original_extent_seal(&extent) < 0); unchanged();
	records[1].logical_page = 2;
	image[8172] ^= 1;
	snapshot(); CHECK(swapz_original_extent_seal(&extent) < 0); unchanged();
	image[8172] ^= 1;
	extent.occupied_bytes--; extent.unused_bytes++;
	snapshot(); CHECK(swapz_original_extent_seal(&extent) < 0); unchanged();
	extent.occupied_bytes++; extent.unused_bytes--;
	seal();

	bad_begin(4095, 1, 4095, 2, sizeof(*records));
	bad_begin(12288, 1, 4095, 2, sizeof(*records));
	bad_begin(~(swapz_u32)0, 1, 4095, 2, sizeof(*records));
	bad_begin(4096, 0, 4095, 2, 0);
	bad_begin(4096, 65, 4095, 2, 65U * sizeof(*records));
	bad_begin(4096, 1, 4096, 2, sizeof(*records));
	bad_begin(8192, 1, 4095, 1, sizeof(*records));
	bad_begin(4096, 2, 4095, 1, 2U * sizeof(*records));
	bad_begin(4096, 1, 4095, 0, sizeof(*records));
	bad_begin(4096, 1, 4095, 2, sizeof(*records) - 1U);
	snapshot();
	CHECK(swapz_original_extent_begin(&extent, records, 4096, records,
		sizeof(*records), 1, 4095, 2) < 0);
	unchanged();
	CHECK(swapz_original_extent_begin(&extent, image, 4096,
		(struct swapz_original_extent_record *)(void *)&extent,
		sizeof(*records), 1, 4095, 2) < 0);
	unchanged();

	CHECK(!swapz_ram_extent_begin(&ordinary, image, 4096, 1,
				      &ordinary_record, 1));
	CHECK(swapz_ram_extent_append(&ordinary, 1, 1, payload, 3569,
				       SWAPZ_ENCODING_LZ4) < 0);
	CHECK(!swapz_ram_extent_append(&ordinary, 1, 1, payload, 3568,
					SWAPZ_ENCODING_LZ4));
	CHECK(!swapz_ram_extent_seal(&ordinary));
	printf("PASS ROUND084_AGENT5 checks=%u record_bytes=%zu builder_bytes=%zu map_bytes=%zu\n",
	       checks, sizeof(*records), sizeof(extent), sizeof(struct swapz_map));
	return 0;
}
