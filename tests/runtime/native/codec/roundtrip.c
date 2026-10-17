// SPDX-License-Identifier: GPL-2.0-only
/*
 * Execute the EXACT src/kernel/codec.c in userspace with Werror.
 * The same production functions are linked by the research .ko.
 */
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "codec.h"

#define CHECK(expression) do { \
	if (!(expression)) { \
		fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, \
			__LINE__, #expression); \
		return 1; \
	} \
} while (0)

static uint8_t extent[SWAPZ_MAX_EXTENT_BYTES];
static uint8_t payload[SWAPZ_MAX_COMPRESSED];

static void set_payload(unsigned int length, unsigned int salt)
{
	unsigned int index;

	for (index = 0; index < length; ++index)
		payload[index] = (uint8_t)((index * 13U + salt * 17U) & 255U);
}

static int test_crc_known_vector(void)
{
	CHECK(swapz_crc32c_bytes("123456789", 9) == 0xe3069283U);
	CHECK(swapz_crc32c_bytes("", 0) == 0);
	return 0;
}

static int test_class(unsigned int bytes, unsigned int count)
{
	struct swapz_builder b;
	struct swapz_decoded d;
	const uint8_t *readable;
	uint8_t inputs[7][2072];
	unsigned int index;

	CHECK(swapz_begin(&b, extent, bytes, 23) == 0);
	for (index = 0; index < count; ++index) {
		set_payload(2072, index);
		memcpy(inputs[index], payload, 2072);
		CHECK(swapz_append(&b, 100 + index, 200 + index, payload, 2072) == 0);
	}
	set_payload(2072, 99);
	CHECK(swapz_append(&b, 999, 1, payload, 2072) == -ENOSPC);
	CHECK(swapz_seal(&b) == 0);
	CHECK(swapz_seal(&b) == -EINVAL);
	CHECK(swapz_validate(extent, bytes) == 0);
	CHECK(swapz_validate(extent, bytes / 2) == -EUCLEAN ||
	      bytes == SWAPZ_BLOCK_BYTES);
	for (index = 0; index < count; ++index) {
		CHECK(swapz_lookup(extent, bytes, index, &d, &readable) == 0);
		CHECK(d.logical_page == 100 + index);
		CHECK(d.generation == 200 + index);
		CHECK(d.payload_length == 2072);
		CHECK(memcmp(readable, inputs[index], 2072) == 0);
	}
	CHECK(swapz_lookup(extent, bytes, count, &d, &readable) == -ERANGE);
	CHECK(readable == NULL);
	return 0;
}

static int test_seal_clears_only_unwritten_gap(void)
{
	struct swapz_builder b;
	unsigned int metadata_end, index;

	memset(extent, 0xa5, sizeof(extent));
	set_payload(2072, 1);
	CHECK(swapz_begin(&b, extent, 8192, 19) == 0);
	CHECK(swapz_append(&b, 7, 3, payload, 2072) == 0);
	metadata_end = sizeof(struct swapz_header) +
		b.count * sizeof(struct swapz_record);
	CHECK(swapz_seal(&b) == 0);
	CHECK(metadata_end < b.payload_start);
	for (index = metadata_end; index < b.payload_start; ++index)
		CHECK(extent[index] == 0);
	CHECK(swapz_validate(extent, 8192) == 0);
	CHECK(extent[8192] == 0xa5);
	return 0;
}

static int test_bad_inputs(void)
{
	struct swapz_builder b;

	CHECK(swapz_begin(NULL, extent, 8192, 1) == -EINVAL);
	CHECK(swapz_begin(&b, NULL, 8192, 1) == -EINVAL);
	CHECK(swapz_begin(&b, extent, 12288, 1) == -EINVAL);
	CHECK(swapz_begin(&b, extent, 8192, 0) == -EINVAL);
	CHECK(swapz_begin(&b, extent, 8192, 1) == 0);
	CHECK(swapz_seal(&b) == -EINVAL);
	CHECK(swapz_append(&b, 0, 0, payload, 2072) == -EINVAL);
	CHECK(swapz_append(&b, 0, 1, NULL, 2072) == -EINVAL);
	CHECK(swapz_append(&b, 0, 1, payload, 0) == -EINVAL);
	CHECK(swapz_append(&b, 0, 1, payload, 3569) == -EINVAL);
	CHECK(swapz_append(&b, 5, 1, payload, 2072) == 0);
	CHECK(swapz_append(&b, 5, 2, payload, 2072) == -EEXIST);
	CHECK(swapz_seal(&b) == 0);
	CHECK(swapz_append(&b, 6, 1, payload, 2072) == -EINVAL);
	return 0;
}

static int test_integrity(void)
{
	struct swapz_builder b;
	struct swapz_decoded d;
	const uint8_t *p;
	uint8_t *metadata = extent + sizeof(struct swapz_header);
	unsigned int index;

	CHECK(swapz_begin(&b, extent, 8192, 77) == 0);
	for (index = 0; index < 3; ++index) {
		set_payload(2072, index);
		CHECK(swapz_append(&b, index, index + 1, payload, 2072) == 0);
	}
	CHECK(swapz_seal(&b) == 0);
	CHECK(swapz_validate(extent, 8192) == 0);
	CHECK(swapz_lookup(extent, 8192, 2, &d, &p) == 0);

	/* A payload outside the metadata changes no header bytes. */
	extent[d.payload_offset] ^= 0x80;
	CHECK(swapz_validate(extent, 8192) == 0);
	CHECK(swapz_lookup(extent, 8192, 2, &d, &p) == -EBADMSG);
	/* A failed lookup intentionally zeros the output; rebuild below. */
	/* Rebuild rather than rely on a failed lookup's wiped output. */
	CHECK(swapz_begin(&b, extent, 8192, 77) == 0);
	for (index = 0; index < 3; ++index) {
		set_payload(2072, index);
		CHECK(swapz_append(&b, index, index + 1, payload, 2072) == 0);
	}
	CHECK(swapz_seal(&b) == 0);
	CHECK(swapz_lookup(extent, 8192, 2, &d, &p) == 0);

	/* Metadata CRC gates *all* descriptor fields. */
	metadata[3] ^= 0x80;
	CHECK(swapz_validate(extent, 8192) == -EBADMSG);
	CHECK(swapz_lookup(extent, 8192, 0, &d, &p) == -EBADMSG);
	metadata[3] ^= 0x80;
	CHECK(swapz_validate(extent, 8192) == 0);

	extent[0] ^= 1; /* Magic check catches this before CRC. */
	CHECK(swapz_validate(extent, 8192) == -EUCLEAN);
	extent[0] ^= 1;
	extent[6] = 4; /* 8 KiB class is two physical blocks. */
	CHECK(swapz_validate(extent, 8192) == -EUCLEAN);
	extent[6] = 2;
	CHECK(swapz_validate(extent, 8192) == 0);
	return 0;
}

static int test_read_spans(void)
{
	struct swapz_builder b;
	struct swapz_decoded d;
	const uint8_t *p;
	unsigned int index;

	CHECK(swapz_begin(&b, extent, SWAPZ_MAX_EXTENT_BYTES, 11) == 0);
	for (index = 0; index < 7; ++index) {
		set_payload(2072, index);
		CHECK(swapz_append(&b, index, 1, payload, 2072) == 0);
	}
	CHECK(swapz_seal(&b) == 0);
	CHECK(swapz_lookup(extent, SWAPZ_MAX_EXTENT_BYTES, 0, &d, &p) == 0);
	CHECK(d.payload_offset == 14312);
	CHECK(swapz_lookup(extent, SWAPZ_MAX_EXTENT_BYTES, 1, &d, &p) == 0);
	CHECK(d.payload_offset == 12240);
	CHECK(swapz_lookup(extent, SWAPZ_MAX_EXTENT_BYTES, 5, &d, &p) == 0);
	CHECK(d.payload_offset == 3952);
	CHECK(swapz_lookup(extent, SWAPZ_MAX_EXTENT_BYTES, 6, &d, &p) == 0);
	CHECK(d.payload_offset == 1880);
	return 0;
}

static int test_metadata_and_format_guards(void)
{
	struct swapz_builder b;
	struct swapz_header header;
	struct swapz_record first;
	struct swapz_record second;
	unsigned int index;

	CHECK(swapz_begin(&b, extent, 8192, 31) == 0);
	for (index = 0; index < 3; ++index) {
		set_payload(2072, index);
		CHECK(swapz_append(&b, index, 10, payload, 2072) == 0);
	}
	CHECK(swapz_seal(&b) == 0);
	memcpy(&header, extent, sizeof(header));
	CHECK(header.record_count == 3);
	/* Give a malformed payload descriptor a VALID metadata CRC to ensure
	 * that structural checks are independent of the checksum. */
	memcpy(&first, extent + sizeof(header), sizeof(first));
	memcpy(&second, extent + sizeof(header) + sizeof(first), sizeof(second));
	second.logical_page_le = first.logical_page_le;
	memcpy(extent + sizeof(header) + sizeof(first), &second, sizeof(second));
	header.metadata_crc32c_le = 0;
	memcpy(extent, &header, sizeof(header));
	header.metadata_crc32c_le = swapz_crc32c_bytes(
		extent, sizeof(header) + 3 * sizeof(first));
	memcpy(extent, &header, sizeof(header));
	CHECK(swapz_validate(extent, 8192) == -EUCLEAN); /* duplicate page */

	CHECK(swapz_begin(&b, extent, 8192, 31) == 0);
	for (index = 0; index < 3; ++index) {
		set_payload(2072, index);
		CHECK(swapz_append(&b, index, 10, payload, 2072) == 0);
	}
	CHECK(swapz_seal(&b) == 0);
	memcpy(&header, extent, sizeof(header));
	memcpy(&second, extent + sizeof(header) + sizeof(first), sizeof(second));
	second.payload_offset_le++; /* noncanonical, gap/overlap */
	memcpy(extent + sizeof(header) + sizeof(first), &second, sizeof(second));
	header.metadata_crc32c_le = 0;
	memcpy(extent, &header, sizeof(header));
	header.metadata_crc32c_le = swapz_crc32c_bytes(
		extent, sizeof(header) + 3 * sizeof(first));
	memcpy(extent, &header, sizeof(header));
	CHECK(swapz_validate(extent, 8192) == -EUCLEAN);
	return 0;
}

int main(void)
{
	int tests = 0;

	CHECK(sizeof(struct swapz_header) == 16);
	CHECK(sizeof(struct swapz_record) == 16);
	CHECK(test_crc_known_vector() == 0); tests++;
	CHECK(test_class(4096, 1) == 0); tests++;
	CHECK(test_class(8192, 3) == 0); tests++;
	CHECK(test_class(16384, 7) == 0); tests++;
	CHECK(test_seal_clears_only_unwritten_gap() == 0); tests++;
	CHECK(test_bad_inputs() == 0); tests++;
	CHECK(test_integrity() == 0); tests++;
	CHECK(test_read_spans() == 0); tests++;
	CHECK(test_metadata_and_format_guards() == 0); tests++;
	printf("SWAPZ_EXACT_PRODUCTION_C_TESTS_PASS=%d\n", tests);
	return 0;
}
