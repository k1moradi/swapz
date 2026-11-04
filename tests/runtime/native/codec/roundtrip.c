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
#include "authority.h"
#include <stddef.h>

#define CHECK(expression) do { \
	if (!(expression)) { \
		fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, \
			__LINE__, #expression); \
		return 1; \
	} \
} while (0)

static uint8_t extent[SWAPZ_MAX_EXTENT_BYTES];
static uint8_t payload[SWAPZ_MAX_COMPRESSED];
static uint8_t metadata_only[SWAPZ_BLOCK_BYTES];
_Alignas(64) static uint8_t misaligned_extent[SWAPZ_BLOCK_BYTES + 1U];
_Alignas(64) static uint8_t misaligned_payload[SWAPZ_MAX_COMPRESSED + 1U];

static void set_payload(unsigned int length, unsigned int salt)
{
	unsigned int index;

	for (index = 0; index < length; ++index)
		payload[index] = (uint8_t)((index * 13U + salt * 17U) & 255U);
}

/* Independent bitwise Castagnoli oracle; used only in the native regression. */
static swapz_u32 reference_crc32c(const swapz_u8 *bytes, swapz_u32 length)
{
	swapz_u32 state = ~0U;
	swapz_u32 byte_index;

	for (byte_index = 0; byte_index < length; ++byte_index) {
		unsigned int bit_index;

		state ^= bytes[byte_index];
		for (bit_index = 0; bit_index < 8U; ++bit_index)
			state = (state >> 1) ^ (0x82f63b78U & (0U - (state & 1U)));
	}
	return ~state;
}

static swapz_u16 reference_load_le16(const void *source)
{
	const uint8_t *bytes = source;

	return (swapz_u16)bytes[0] | ((swapz_u16)bytes[1] << 8);
}

static void reference_store_le16(void *destination, swapz_u16 value)
{
	uint8_t *bytes = destination;

	bytes[0] = (uint8_t)value;
	bytes[1] = (uint8_t)(value >> 8);
}

static void reference_store_le32(void *destination, swapz_u32 value)
{
	uint8_t *bytes = destination;

	bytes[0] = (uint8_t)value;
	bytes[1] = (uint8_t)(value >> 8);
	bytes[2] = (uint8_t)(value >> 16);
	bytes[3] = (uint8_t)(value >> 24);
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
		CHECK(d.encoding == SWAPZ_ENCODING_LZ4);
		CHECK(memcmp(readable, inputs[index], 2072) == 0);
	}
	CHECK(swapz_lookup(extent, bytes, count, &d, &readable) == -ERANGE);
	CHECK(readable == NULL);
	return 0;
}

static int test_prehashed_and_validated_lookup(void)
{
	struct swapz_builder b;
	struct swapz_decoded d;
	const uint8_t *p;
	swapz_u32 crc;

	set_payload(2072, 41);
	crc = swapz_crc32c_bytes(payload, 2072);
	CHECK(swapz_begin(&b, extent, 4096, 91) == 0);
	CHECK(swapz_append_prehashed(&b, 7, 3, payload, 2072, crc) == 0);
	CHECK(swapz_seal(&b) == 0);
	CHECK(swapz_validate(extent, 4096) == 0);
	CHECK(swapz_lookup_validated(extent, 4096, 0, &d, &p) == 0);
	CHECK(d.logical_page == 7 && d.generation == 3 && d.payload_crc32c == crc);
	CHECK(!memcmp(p, payload, 2072));
	((uint8_t *)p)[0] ^= 1;
	CHECK(swapz_lookup_validated(extent, 4096, 0, &d, &p) == -EBADMSG);
	((uint8_t *)extent)[4096 - 2072] ^= 1;

	/* A bad producer-supplied CRC can make a syntactically valid sealed
	 * image, but final payload verification must still reject publication. */
	CHECK(swapz_begin(&b, extent, 4096, 92) == 0);
	CHECK(swapz_append_prehashed(&b, 8, 4, payload, 2072, crc ^ 1U) == 0);
	CHECK(swapz_seal(&b) == 0);
	CHECK(swapz_validate(extent, 4096) == 0);
	CHECK(swapz_lookup_validated(extent, 4096, 0, &d, &p) == -EBADMSG);
	return 0;
}

static int test_delta64_record_encoding(void)
{
	struct swapz_builder b;
	struct swapz_decoded d;
	const uint8_t *p;
	swapz_u32 crc;

	set_payload(1800, 73);
	crc = swapz_crc32c_bytes(payload, 1800);
	CHECK(swapz_begin(&b, extent, 4096, 93) == 0);
	CHECK(swapz_append_prehashed_encoded(&b, 9, 5, payload, 1800, crc,
					    SWAPZ_ENCODING_DELTA64) == 0);
	CHECK(swapz_seal(&b) == 0);
	CHECK(swapz_validate(extent, 4096) == 0);
	CHECK(swapz_lookup(extent, 4096, 0, &d, &p) == 0);
	CHECK(d.logical_page == 9 && d.generation == 5);
	CHECK(d.payload_length == 1800 && d.payload_crc32c == crc);
	CHECK(d.encoding == SWAPZ_ENCODING_DELTA64);
	CHECK(!memcmp(p, payload, 1800));
	return 0;
}

/* Recompute the metadata CRC after deliberately editing a descriptor so the
 * encoding check, not the CRC, is what rejects the extent. */
static void reseal_metadata(uint8_t *bytes, swapz_u8 records)
{
	swapz_u32 crc;
	size_t end = sizeof(struct swapz_header) +
		(size_t)records * sizeof(struct swapz_record);
	uint8_t *crc_bytes = bytes +
		offsetof(struct swapz_header, metadata_crc32c_le);

	reference_store_le32(crc_bytes, 0);
	crc = swapz_crc32c_bytes(bytes, (swapz_u32)end);
	reference_store_le32(crc_bytes, crc);
}

static int test_delta64_shuf8_record_encoding(void)
{
	struct swapz_builder b;
	struct swapz_decoded d;
	const uint8_t *p;
	swapz_u32 crc;
	swapz_u16 raw;
	size_t length_at = sizeof(struct swapz_header) +
		offsetof(struct swapz_record, payload_length_le);

	set_payload(1200, 91);
	crc = swapz_crc32c_bytes(payload, 1200);
	CHECK(swapz_begin(&b, extent, 4096, 94) == 0);
	CHECK(swapz_append_prehashed_encoded(&b, 11, 6, payload, 1200, crc,
					    SWAPZ_ENCODING_DELTA64_SHUF8) == 0);
	CHECK(swapz_seal(&b) == 0);
	raw = reference_load_le16(extent + length_at);
	CHECK(raw == (1200U | SWAPZ_RECORD_DELTA64_FLAG | SWAPZ_RECORD_SHUF8_FLAG));
	CHECK(swapz_validate(extent, 4096) == 0);
	CHECK(swapz_lookup(extent, 4096, 0, &d, &p) == 0);
	CHECK(d.logical_page == 11 && d.generation == 6);
	CHECK(d.payload_length == 1200 && d.payload_crc32c == crc);
	CHECK(d.encoding == SWAPZ_ENCODING_DELTA64_SHUF8);
	CHECK(!memcmp(p, payload, 1200));

	/* Lone bit 14 (shuffle without delta64) is reserved: fail closed. */
	raw = (swapz_u16)(1200U | SWAPZ_RECORD_SHUF8_FLAG);
	reference_store_le16(extent + length_at, raw);
	reseal_metadata(extent, 1);
	CHECK(swapz_validate_metadata_crc(extent, 4096) == 0);
	CHECK(swapz_validate(extent, 4096) == -EUCLEAN);
	CHECK(swapz_peek(extent, 4096, 0, &d) == -EUCLEAN);
	CHECK(swapz_lookup_validated_descriptor(extent, 4096, 0, &d, &p) ==
	      -EUCLEAN);
	CHECK(p == NULL && d.encoding == 0);

	/* Writers can never emit an unknown or reserved encoding. */
	CHECK(swapz_begin(&b, extent, 4096, 95) == 0);
	CHECK(swapz_append_encoded(&b, 12, 7, payload, 1200,
				   SWAPZ_ENCODING_INVALID) == -EINVAL);
	CHECK(swapz_append_prehashed_encoded(&b, 12, 7, payload, 1200, crc,
					    3U) == -EINVAL);
	return 0;
}

static int test_map_encoding_packing(void)
{
	static const swapz_u8 encodings[] = {
		SWAPZ_ENCODING_LZ4, SWAPZ_ENCODING_DELTA64,
		SWAPZ_ENCODING_DELTA64_SHUF8,
	};
	struct swapz_map map = { 0 };
	unsigned int e;

	for (e = 0; e < sizeof(encodings); ++e) {
		map.record_index = swapz_map_pack_record_index(63, encodings[e]);
		CHECK(swapz_map_record_index(&map) == 63);
		CHECK(swapz_map_encoding(&map) == encodings[e]);
		map.record_index = swapz_map_pack_record_index(0, encodings[e]);
		CHECK(swapz_map_record_index(&map) == 0);
		CHECK(swapz_map_encoding(&map) == encodings[e]);
	}
	CHECK(swapz_map_pack_record_index(5, SWAPZ_ENCODING_DELTA64_SHUF8) ==
	      (5U | SWAPZ_MAP_DELTA64_FLAG | SWAPZ_MAP_SHUF8_FLAG));
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

static int test_alignment_and_payload_boundaries(void)
{
	struct swapz_builder b;
	struct swapz_decoded d;
	const uint8_t *readable;
	uint8_t *bytes = misaligned_extent + 1U;
	uint8_t *input = misaligned_payload + 1U;
	static const swapz_u32 crc_lengths[] = {
		0U, 1U, 7U, 8U, 9U, SWAPZ_MAX_COMPRESSED - 1U,
		SWAPZ_MAX_COMPRESSED,
	};
	unsigned int index;

	for (index = 0; index < SWAPZ_MAX_COMPRESSED; ++index)
		input[index] = (uint8_t)((index * 29U + 7U) & 255U);
	memcpy(payload, input, SWAPZ_MAX_COMPRESSED);
	for (index = 0; index < sizeof(crc_lengths) / sizeof(crc_lengths[0]);
	     ++index) {
		swapz_u32 length = crc_lengths[index];

		CHECK(swapz_crc32c_bytes(input, length) ==
		      reference_crc32c(input, length));
		CHECK(swapz_crc32c_bytes(input, length) ==
		      swapz_crc32c_bytes(payload, length));
	}

	CHECK(swapz_begin(&b, bytes, SWAPZ_BLOCK_BYTES, 101) == 0);
	CHECK(swapz_append_encoded(&b, 17, 1, input, 1,
				   SWAPZ_ENCODING_LZ4) == 0);
	CHECK(swapz_seal(&b) == 0);
	CHECK(swapz_validate(bytes, SWAPZ_BLOCK_BYTES) == 0);
	CHECK(swapz_lookup(bytes, SWAPZ_BLOCK_BYTES, 0, &d, &readable) == 0);
	CHECK(d.payload_length == 1 && readable[0] == input[0]);

	CHECK(swapz_begin(&b, bytes, SWAPZ_BLOCK_BYTES, 102) == 0);
	CHECK(swapz_append_encoded(&b, 18, 2, input, SWAPZ_MAX_COMPRESSED,
				   SWAPZ_ENCODING_DELTA64_SHUF8) == 0);
	CHECK(swapz_seal(&b) == 0);
	CHECK(swapz_validate(bytes, SWAPZ_BLOCK_BYTES) == 0);
	CHECK(swapz_lookup(bytes, SWAPZ_BLOCK_BYTES, 0, &d, &readable) == 0);
	CHECK(d.payload_length == SWAPZ_MAX_COMPRESSED);
	CHECK(d.encoding == SWAPZ_ENCODING_DELTA64_SHUF8);
	CHECK(!memcmp(readable, input, SWAPZ_MAX_COMPRESSED));
	return 0;
}

/*
 * Record-envelope oracle: payloads are arbitrary stored bytes, not valid
 * LZ4 streams. Full-page LZ4 -> SWZ -> decode -> inverse qualification lives
 * in predictor-qualification.c and uses the exact production codec.c.
 */
static swapz_u32 next_random_word(swapz_u32 *state)
{
	swapz_u32 value = *state;

	value ^= value << 13;
	value ^= value >> 17;
	value ^= value << 5;
	*state = value;
	return value;
}

static int verify_unaligned_encoded_record(swapz_u16 length,
					    swapz_u8 encoding,
					    swapz_u32 seed)
{
	struct swapz_builder builder;
	struct swapz_decoded decoded;
	const swapz_u8 *readable;
	swapz_u8 *bytes = misaligned_extent + 1U;
	swapz_u8 *input = misaligned_payload + 1U;
	swapz_u32 payload_crc32c;
	swapz_u32 random_state = seed | 1U;
	swapz_u32 index;

	for (index = 0; index < length; ++index) {
		swapz_u32 random_word = next_random_word(&random_state);

		input[index] = (swapz_u8)(random_word >> ((index & 3U) * 8U));
	}
	/* Keep every corpus member observably nonzero even if the PRNG changes. */
	input[length / 2U] |= 1U;
	payload_crc32c = reference_crc32c(input, length);

	CHECK(swapz_begin(&builder, bytes, SWAPZ_BLOCK_BYTES, seed | 1U) == 0);
	CHECK(swapz_append_prehashed_encoded(
		      &builder, seed, (seed ^ 0xa5a5a5a5U) | 1U,
		      input, length, payload_crc32c, encoding) == 0);
	CHECK(swapz_seal(&builder) == 0);
	CHECK(swapz_validate(bytes, SWAPZ_BLOCK_BYTES) == 0);
	CHECK(swapz_lookup_validated(bytes, SWAPZ_BLOCK_BYTES, 0,
				     &decoded, &readable) == 0);
	CHECK(decoded.logical_page == seed);
	CHECK(decoded.generation == ((seed ^ 0xa5a5a5a5U) | 1U));
	CHECK(decoded.payload_length == length);
	CHECK(decoded.payload_crc32c == payload_crc32c);
	CHECK(decoded.encoding == encoding);
	CHECK(readable >= bytes);
	CHECK((size_t)(readable - bytes) + length <= SWAPZ_BLOCK_BYTES);
	CHECK(!memcmp(readable, input, length));
	CHECK(swapz_crc32c_bytes(readable, length) == payload_crc32c);
	return 0;
}

static int test_randomized_unaligned_encoded_boundaries(void)
{
	static const swapz_u16 boundary_lengths[] = {
		1U, 2U, 7U, 8U, 9U, 15U, 16U, 17U,
		63U, 64U, 65U, 255U, 256U, 257U,
		511U, 512U, 513U, 1023U, 1024U, 1025U,
		2023U, 2024U, 2025U, 2047U, 2048U, 2049U,
		3071U, 3072U, 3073U,
		SWAPZ_MAX_COMPRESSED - 1U, SWAPZ_MAX_COMPRESSED,
	};
	static const swapz_u8 encodings[] = {
		SWAPZ_ENCODING_LZ4,
		SWAPZ_ENCODING_DELTA64,
		SWAPZ_ENCODING_DELTA64_SHUF8,
	};
	swapz_u32 random_state = 0x6a09e667U;
	unsigned int length_index, encoding_index, case_index;

	for (length_index = 0;
	     length_index < sizeof(boundary_lengths) / sizeof(boundary_lengths[0]);
	     ++length_index)
		for (encoding_index = 0;
		     encoding_index < sizeof(encodings) / sizeof(encodings[0]);
		     ++encoding_index) {
			swapz_u32 seed = 0x9e3779b9U ^
				((swapz_u32)length_index + 1U) * 0x85ebca6bU ^
				((swapz_u32)encoding_index + 1U) * 0xc2b2ae35U;

			CHECK(verify_unaligned_encoded_record(
				      boundary_lengths[length_index],
				      encodings[encoding_index], seed | 1U) == 0);
		}

	for (case_index = 0; case_index < 128U; ++case_index) {
		swapz_u16 length = (swapz_u16)(
			1U + next_random_word(&random_state) % SWAPZ_MAX_COMPRESSED);
		swapz_u8 encoding = encodings[
			next_random_word(&random_state) %
			(sizeof(encodings) / sizeof(encodings[0]))];
		swapz_u32 seed = next_random_word(&random_state) | 1U;

		CHECK(verify_unaligned_encoded_record(length, encoding, seed) == 0);
	}
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
	CHECK(swapz_append_encoded(&b, 4, 1, payload, 2072, 3U) == -EINVAL);
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
	CHECK(header.flags_le == 0);
	header.flags_le = 1;
	memcpy(extent, &header, sizeof(header));
	CHECK(swapz_validate(extent, 8192) == -EUCLEAN);

	CHECK(swapz_begin(&b, extent, 8192, 31) == 0);
	for (index = 0; index < 3; ++index) {
		set_payload(2072, index);
		CHECK(swapz_append(&b, index, 10, payload, 2072) == 0);
	}
	CHECK(swapz_seal(&b) == 0);
	memcpy(&header, extent, sizeof(header));
	/* Give a malformed payload descriptor a VALID metadata CRC to ensure
	 * that structural checks are independent of the checksum. */
	memcpy(&first, extent + sizeof(header), sizeof(first));
	memcpy(&second, extent + sizeof(header) + sizeof(first), sizeof(second));
	second.logical_page_le = first.logical_page_le;
	memcpy(extent + sizeof(header) + sizeof(first), &second, sizeof(second));
	reseal_metadata(extent, 3);
	CHECK(swapz_validate(extent, 8192) == -EUCLEAN); /* duplicate page */

	CHECK(swapz_begin(&b, extent, 8192, 31) == 0);
	for (index = 0; index < 3; ++index) {
		set_payload(2072, index);
		CHECK(swapz_append(&b, index, 10, payload, 2072) == 0);
	}
	CHECK(swapz_seal(&b) == 0);
	memcpy(&header, extent, sizeof(header));
	memcpy(&second, extent + sizeof(header) + sizeof(first), sizeof(second));
	reference_store_le16(&second.payload_offset_le,
			     (swapz_u16)(reference_load_le16(
				     &second.payload_offset_le) + 1U));
	/* Noncanonical gap/overlap with an otherwise valid metadata CRC. */
	memcpy(extent + sizeof(header) + sizeof(first), &second, sizeof(second));
	reseal_metadata(extent, 3);
	CHECK(swapz_validate(extent, 8192) == -EUCLEAN);
	return 0;
}

/*
 * A correct metadata CRC alone does not prove a descriptor is semantically
 * valid. Give a forged header alias its own matching payload CRC, so rejection
 * must come from the descriptor's placement rather than the checksum.
 */
static int test_authenticated_descriptor_semantic_guards(void)
{
	struct swapz_builder builder;
	struct swapz_record record;
	struct swapz_decoded decoded;
	const uint8_t *readable;
	uint8_t *record_bytes = extent + sizeof(struct swapz_header);

	set_payload(128, 17);
	CHECK(swapz_begin(&builder, extent, SWAPZ_BLOCK_BYTES, 105) == 0);
	CHECK(swapz_append_encoded(&builder, 42, 9, payload, 128,
				   SWAPZ_ENCODING_DELTA64_SHUF8) == 0);
	CHECK(swapz_seal(&builder) == 0);
	memcpy(&record, record_bytes, sizeof(record));
	reference_store_le16(&record.payload_offset_le, 0);
	reference_store_le16(&record.payload_length_le,
			     1U | SWAPZ_RECORD_DELTA64_FLAG |
			     SWAPZ_RECORD_SHUF8_FLAG);
	reference_store_le32(&record.payload_crc32c_le,
			     reference_crc32c(extent, 1));
	memcpy(record_bytes, &record, sizeof(record));
	reseal_metadata(extent, 1);
	CHECK(swapz_validate_metadata_crc(extent, SWAPZ_BLOCK_BYTES) == 0);
	CHECK(swapz_validate(extent, SWAPZ_BLOCK_BYTES) == -EUCLEAN);
	readable = payload;
	CHECK(swapz_lookup_validated_descriptor(extent, SWAPZ_BLOCK_BYTES, 0,
					       &decoded, &readable) == -EUCLEAN);
	CHECK(readable == NULL && decoded.payload_length == 0);
	readable = payload;
	CHECK(swapz_lookup_validated(extent, SWAPZ_BLOCK_BYTES, 0,
				     &decoded, &readable) == -EUCLEAN);
	CHECK(readable == NULL && decoded.payload_length == 0);

	/* Even with a valid stored payload and CRC, generation zero is invalid. */
	CHECK(swapz_begin(&builder, extent, SWAPZ_BLOCK_BYTES, 106) == 0);
	CHECK(swapz_append_encoded(&builder, 43, 10, payload, 128,
				   SWAPZ_ENCODING_LZ4) == 0);
	CHECK(swapz_seal(&builder) == 0);
	memcpy(&record, record_bytes, sizeof(record));
	record.generation_le = 0;
	memcpy(record_bytes, &record, sizeof(record));
	reseal_metadata(extent, 1);
	CHECK(swapz_validate_metadata_crc(extent, SWAPZ_BLOCK_BYTES) == 0);
	CHECK(swapz_validate(extent, SWAPZ_BLOCK_BYTES) == -EUCLEAN);
	readable = payload;
	CHECK(swapz_lookup_validated_descriptor(extent, SWAPZ_BLOCK_BYTES, 0,
					       &decoded, &readable) == -EUCLEAN);
	CHECK(readable == NULL && decoded.generation == 0);
	return 0;
}

static int test_metadata_only_validated_descriptor_lookup(void)
{
	struct swapz_builder builder;
	struct swapz_decoded decoded;

	set_payload(128, 29);
	CHECK(swapz_begin(&builder, extent, SWAPZ_MAX_EXTENT_BYTES, 107) == 0);
	CHECK(swapz_append_encoded(&builder, 44, 11, payload, 128,
				   SWAPZ_ENCODING_LZ4) == 0);
	CHECK(swapz_seal(&builder) == 0);
	CHECK(swapz_validate(extent, SWAPZ_MAX_EXTENT_BYTES) == 0);
	memcpy(metadata_only, extent, sizeof(metadata_only));
	CHECK(swapz_validate_metadata_crc(metadata_only,
					 SWAPZ_MAX_EXTENT_BYTES) == 0);
	CHECK(swapz_lookup_validated_descriptor(
		      metadata_only, SWAPZ_MAX_EXTENT_BYTES, 0, &decoded, NULL) == 0);
	CHECK(decoded.logical_page == 44 && decoded.generation == 11);
	CHECK(decoded.payload_length == 128);
	CHECK(decoded.payload_offset > sizeof(metadata_only));
	CHECK(decoded.encoding == SWAPZ_ENCODING_LZ4);
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
	CHECK(test_prehashed_and_validated_lookup() == 0); tests++;
	CHECK(test_delta64_record_encoding() == 0); tests++;
	CHECK(test_delta64_shuf8_record_encoding() == 0); tests++;
	CHECK(test_map_encoding_packing() == 0); tests++;
	CHECK(test_seal_clears_only_unwritten_gap() == 0); tests++;
	CHECK(test_alignment_and_payload_boundaries() == 0); tests++;
	CHECK(test_randomized_unaligned_encoded_boundaries() == 0); tests++;
	CHECK(test_bad_inputs() == 0); tests++;
	CHECK(test_integrity() == 0); tests++;
	CHECK(test_read_spans() == 0); tests++;
	CHECK(test_metadata_and_format_guards() == 0); tests++;
	CHECK(test_authenticated_descriptor_semantic_guards() == 0); tests++;
	CHECK(test_metadata_only_validated_descriptor_lookup() == 0); tests++;
	printf("SWAPZ_EXACT_PRODUCTION_C_TESTS_PASS=%d\n", tests);
	return 0;
}
