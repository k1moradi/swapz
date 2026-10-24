// SPDX-License-Identifier: GPL-2.0-only
#include "codec.h"

#ifdef __KERNEL__
#include <linux/crc32c.h>
#include <linux/errno.h>
#include <linux/stddef.h>
#include <linux/string.h>
#else
#include <errno.h>
#include <stddef.h>
#include <string.h>
#if defined(__x86_64__) && defined(__SSE4_2__)
#include <nmmintrin.h>
#elif defined(__aarch64__) && defined(__ARM_FEATURE_CRC32)
#include <arm_acle.h>
#endif
#endif

/*
 * Keep the endian conversion explicit: the wire structs hold bytes, not
 * native-endian values. GCC/Clang define BYTE_ORDER on kernel and host builds.
 */
static inline swapz_u16 swapz_le16(swapz_u16 value)
{
#if __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
	return __builtin_bswap16(value);
#else
	return value;
#endif
}

static inline swapz_u32 swapz_le32(swapz_u32 value)
{
#if __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
	return __builtin_bswap32(value);
#else
	return value;
#endif
}

static inline int swapz_valid_extent_bytes(swapz_u32 bytes_total)
{
	return bytes_total == SWAPZ_BLOCK_BYTES ||
	       bytes_total == 2U * SWAPZ_BLOCK_BYTES ||
	       bytes_total == 4U * SWAPZ_BLOCK_BYTES;
}

static swapz_u32 swapz_crc32c_state(swapz_u32 state, const void *data,
				    swapz_u32 length)
{
#ifdef __KERNEL__
	return crc32c(state, data, length);
#elif defined(__aarch64__) && defined(__ARM_FEATURE_CRC32)
	const swapz_u8 *ptr = data;

	while (length >= 8U) {
		unsigned long long val;
		memcpy(&val, ptr, sizeof(val));
		state = __crc32cd(state, val);
		ptr += 8U;
		length -= 8U;
	}
	while (length > 0U) {
		state = __crc32cb(state, *ptr);
		ptr++;
		length--;
	}
	return state;
#elif defined(__x86_64__) && defined(__SSE4_2__)
	const swapz_u8 *ptr = data;

	while (length >= 8U) {
		unsigned long long val;
		memcpy(&val, ptr, sizeof(val));
		state = (swapz_u32)_mm_crc32_u64(state, val);
		ptr += 8U;
		length -= 8U;
	}
	while (length > 0U) {
		state = _mm_crc32_u8(state, *ptr);
		ptr++;
		length--;
	}
	return state;
#else
	/*
	 * 16-entry (64-byte = single cache line) Castagnoli CRC32C nibble
	 * lookup table for userspace tests and native benchmarks.
	 */
	static const swapz_u32 crc32c_nibble_table[16] = {
		0x00000000U, 0x105ec76fU, 0x20bd8edeU, 0x30e349b1U,
		0x417b1dbcU, 0x5125dad3U, 0x61c69362U, 0x7198540dU,
		0x82f63b78U, 0x92a8fc17U, 0xa24bb5a6U, 0xb21572c9U,
		0xc38d26c4U, 0xd3d3e1abU, 0xe330a81aU, 0xf36e6f75U
	};
	const swapz_u8 *ptr = data;
	swapz_u32 index;

	for (index = 0; index < length; ++index) {
		state ^= ptr[index];
		state = (state >> 4) ^ crc32c_nibble_table[state & 0x0fU];
		state = (state >> 4) ^ crc32c_nibble_table[state & 0x0fU];
	}
	return state;
#endif
}

swapz_u32 swapz_crc32c_bytes(const void *data, swapz_u32 length)
{
	if (!data && length)
		return 0;
	return ~swapz_crc32c_state(~0U, data, length);
}

static inline void swapz_get_header(const void *bytes,
				    struct swapz_header *header)
{
	memcpy(header, bytes, sizeof(*header));
}

static inline swapz_u8 swapz_get_record_count(const void *bytes)
{
	return *((const swapz_u8 *)bytes +
		 offsetof(struct swapz_header, record_count));
}

static inline const swapz_u8 *swapz_record_ptr(const void *bytes,
					       swapz_u8 index)
{
	return (const swapz_u8 *)bytes + sizeof(struct swapz_header) +
	       (swapz_u32)index * sizeof(struct swapz_record);
}

static inline void swapz_get_record(const void *bytes, swapz_u8 index,
				    struct swapz_record *record)
{
	memcpy(record, swapz_record_ptr(bytes, index), sizeof(*record));
}

static inline void swapz_put_record(void *bytes, swapz_u8 index,
				    const struct swapz_record *record)
{
	memcpy((swapz_u8 *)bytes + sizeof(struct swapz_header) +
	       (swapz_u32)index * sizeof(*record), record, sizeof(*record));
}

static inline swapz_u32 swapz_record_logical_le(const void *bytes,
						swapz_u8 index)
{
	swapz_u32 logical_le;

	memcpy(&logical_le,
	       swapz_record_ptr(bytes, index) +
		       offsetof(struct swapz_record, logical_page_le),
	       sizeof(logical_le));
	return logical_le;
}

static inline void swapz_decode_record(const struct swapz_record *record,
				       struct swapz_decoded *out)
{
	swapz_u16 raw_length = swapz_le16(record->payload_length_le);

	*out = (struct swapz_decoded){
		.logical_page = swapz_le32(record->logical_page_le),
		.generation = swapz_le32(record->generation_le),
		.payload_crc32c = swapz_le32(record->payload_crc32c_le),
		.payload_offset = swapz_le16(record->payload_offset_le),
		.payload_length = raw_length & SWAPZ_RECORD_LENGTH_MASK,
		.encoding = (raw_length & SWAPZ_RECORD_DELTA64_FLAG) ?
			SWAPZ_ENCODING_DELTA64 : SWAPZ_ENCODING_LZ4,
	};
}

int swapz_begin(struct swapz_builder *builder, void *bytes,
		swapz_u32 bytes_total, swapz_u32 sequence)
{
	struct swapz_header header = { 0 };

	if (!builder || !bytes || !sequence ||
	    !swapz_valid_extent_bytes(bytes_total))
		return -EINVAL;

	*builder = (struct swapz_builder){
		.bytes = bytes,
		.bytes_total = bytes_total,
		.payload_start = (swapz_u16)bytes_total,
		.extent_blocks = (swapz_u8)(bytes_total / SWAPZ_BLOCK_BYTES),
		.sequence = sequence,
	};
	header.magic_le = swapz_le32(SWAPZ_MAGIC);
	header.extent_blocks = builder->extent_blocks;
	header.sequence_le = swapz_le32(sequence);
	memcpy(bytes, &header, sizeof(header));
	return 0;
}

static int swapz_append_crc(struct swapz_builder *builder,
			    swapz_u32 logical_page, swapz_u32 generation,
			    const void *payload, swapz_u16 length,
			    swapz_u32 payload_crc32c, swapz_u8 encoding)
{
	struct swapz_record record;
	swapz_u32 logical_page_le;
	swapz_u32 metadata_end;
	swapz_u16 offset;
	swapz_u8 index;

	if (!builder || !builder->bytes || builder->sealed ||
	    !payload || !length || length > SWAPZ_MAX_COMPRESSED ||
	    !generation ||
	    (encoding != SWAPZ_ENCODING_LZ4 &&
	     encoding != SWAPZ_ENCODING_DELTA64))
		return -EINVAL;
	if (builder->count >= SWAPZ_MAX_RECORDS)
		return -ENOSPC;
	metadata_end = sizeof(struct swapz_header) +
		((swapz_u32)builder->count + 1U) * sizeof(struct swapz_record);
	if (builder->payload_start < length ||
	    (swapz_u32)builder->payload_start - length < metadata_end)
		return -ENOSPC;

	logical_page_le = swapz_le32(logical_page);
	/* One authoritative record per logical slot in any single extent. */
	for (index = 0; index < builder->count; ++index) {
		if (swapz_record_logical_le(builder->bytes, index) ==
		    logical_page_le)
			return -EEXIST;
	}

	offset = builder->payload_start - length;
	record = (struct swapz_record){
		.logical_page_le = logical_page_le,
		.generation_le = swapz_le32(generation),
		.payload_offset_le = swapz_le16(offset),
		.payload_length_le = swapz_le16(length |
			(encoding == SWAPZ_ENCODING_DELTA64 ?
			 SWAPZ_RECORD_DELTA64_FLAG : 0U)),
		.payload_crc32c_le = swapz_le32(payload_crc32c),
	};
	memcpy(builder->bytes + offset, payload, length);
	swapz_put_record(builder->bytes, builder->count, &record);
	builder->count++;
	builder->payload_start = offset;
	return 0;
}

int swapz_append_prehashed(struct swapz_builder *builder,
			   swapz_u32 logical_page, swapz_u32 generation,
			   const void *payload, swapz_u16 length,
			   swapz_u32 payload_crc32c)
{
	return swapz_append_crc(builder, logical_page, generation, payload,
				length, payload_crc32c, SWAPZ_ENCODING_LZ4);
}

int swapz_append_prehashed_encoded(struct swapz_builder *builder,
				   swapz_u32 logical_page, swapz_u32 generation,
				   const void *payload, swapz_u16 length,
				   swapz_u32 payload_crc32c, swapz_u8 encoding)
{
	return swapz_append_crc(builder, logical_page, generation, payload,
				length, payload_crc32c, encoding);
}

int swapz_append_encoded(struct swapz_builder *builder,
			 swapz_u32 logical_page, swapz_u32 generation,
			 const void *payload, swapz_u16 length,
			 swapz_u8 encoding)
{
	if (!builder || !builder->bytes || builder->sealed ||
	    !payload || !length || length > SWAPZ_MAX_COMPRESSED ||
	    !generation ||
	    (encoding != SWAPZ_ENCODING_LZ4 &&
	     encoding != SWAPZ_ENCODING_DELTA64))
		return -EINVAL;
	return swapz_append_crc(builder, logical_page, generation, payload,
				length, swapz_crc32c_bytes(payload, length),
				encoding);
}

int swapz_append(struct swapz_builder *builder, swapz_u32 logical_page,
		 swapz_u32 generation, const void *payload, swapz_u16 length)
{
	/*
	 * Validate every field that can reject the call before inspecting the
	 * payload. In particular, an oversized length may describe more bytes than
	 * the caller actually owns; hashing first would read beyond that buffer.
	 * swapz_append_crc() retains the authoritative validation for prehashed
	 * callers and rechecks these cheap invariants before mutation.
	 */
	if (!builder || !builder->bytes || builder->sealed ||
	    !payload || !length || length > SWAPZ_MAX_COMPRESSED ||
	    !generation)
		return -EINVAL;

	return swapz_append_crc(builder, logical_page, generation, payload,
				length, swapz_crc32c_bytes(payload, length),
				SWAPZ_ENCODING_LZ4);
}

int swapz_seal(struct swapz_builder *builder)
{
	swapz_u32 metadata_end;
	swapz_u32 zero_crc = 0;
	swapz_u32 crc_le;

	if (!builder || !builder->bytes || builder->sealed || !builder->count)
		return -EINVAL;
	if (builder->count > SWAPZ_MAX_RECORDS)
		return -EUCLEAN;
	metadata_end = sizeof(struct swapz_header) +
		(swapz_u32)builder->count * sizeof(struct swapz_record);
	if (metadata_end > builder->payload_start)
		return -EUCLEAN;

	/*
	 * Header, descriptors and payloads are all written explicitly. Clear
	 * only the unused gap before the complete extent can reach lower I/O;
	 * stale scratch bytes must never escape to media.
	 */
	if (metadata_end < builder->payload_start)
		memset(builder->bytes + metadata_end, 0,
		       builder->payload_start - metadata_end);

	builder->bytes[offsetof(struct swapz_header, record_count)] =
		builder->count;
	memcpy(builder->bytes +
		       offsetof(struct swapz_header, metadata_crc32c_le),
	       &zero_crc, sizeof(zero_crc));
	crc_le = swapz_le32(swapz_crc32c_bytes(builder->bytes, metadata_end));
	memcpy(builder->bytes +
		       offsetof(struct swapz_header, metadata_crc32c_le),
	       &crc_le, sizeof(crc_le));
	builder->sealed = 1;
	return 0;
}

int swapz_validate(const void *bytes, swapz_u32 bytes_total)
{
	struct swapz_header header;
	struct swapz_record record;
	swapz_u32 saved_crc;
	swapz_u32 metadata_end;
	swapz_u32 computed_crc;
	swapz_u32 previous_end = bytes_total;
	swapz_u32 crc_state;
	swapz_u8 index;

	if (!bytes || !swapz_valid_extent_bytes(bytes_total))
		return -EINVAL;

	swapz_get_header(bytes, &header);
	if (swapz_le32(header.magic_le) != SWAPZ_MAGIC ||
	    header.flags_le != 0 ||
	    header.extent_blocks != bytes_total / SWAPZ_BLOCK_BYTES ||
	    !header.record_count || header.record_count > SWAPZ_MAX_RECORDS ||
	    !header.sequence_le)
		return -EUCLEAN;
	metadata_end = sizeof(header) +
		(swapz_u32)header.record_count * sizeof(struct swapz_record);
	if (metadata_end > bytes_total)
		return -EUCLEAN;

	saved_crc = swapz_le32(header.metadata_crc32c_le);
	header.metadata_crc32c_le = 0;
	crc_state = swapz_crc32c_state(~0U, &header, sizeof(header));
	crc_state = swapz_crc32c_state(crc_state,
				       (const swapz_u8 *)bytes + sizeof(header),
				       metadata_end - sizeof(header));
	computed_crc = ~crc_state;
	if (saved_crc != computed_crc)
		return -EBADMSG;

	for (index = 0; index < header.record_count; ++index) {
		swapz_u32 start, length;
		swapz_u8 earlier;

		swapz_get_record(bytes, index, &record);
		start = swapz_le16(record.payload_offset_le);
		length = swapz_le16(record.payload_length_le) &
			SWAPZ_RECORD_LENGTH_MASK;
		if (!record.generation_le ||
		    !length || length > SWAPZ_MAX_COMPRESSED ||
		    start < metadata_end ||
		    start > bytes_total || length > bytes_total - start ||
		    start + length != previous_end)
			return -EUCLEAN;
		previous_end = start;
		for (earlier = 0; earlier < index; ++earlier)
			if (swapz_record_logical_le(bytes, earlier) ==
			    record.logical_page_le)
				return -EUCLEAN;
	}
	return 0;
}

int swapz_peek(const void *bytes, swapz_u32 bytes_total, swapz_u8 index,
	       struct swapz_decoded *out)
{
	struct swapz_record record;
	int error;

	if (!out)
		return -EINVAL;
	error = swapz_validate(bytes, bytes_total);
	if (error) {
		*out = (struct swapz_decoded){ 0 };
		return error;
	}
	if (index >= swapz_get_record_count(bytes)) {
		*out = (struct swapz_decoded){ 0 };
		return -ERANGE;
	}
	swapz_get_record(bytes, index, &record);
	swapz_decode_record(&record, out);
	return 0;
}

int swapz_lookup_validated_descriptor(const void *bytes,
				      swapz_u32 bytes_total, swapz_u8 index,
				      struct swapz_decoded *out,
				      const swapz_u8 **payload)
{
	struct swapz_record record;
	swapz_u8 record_count;

	if (!bytes || !out || !payload || !swapz_valid_extent_bytes(bytes_total)) {
		if (out)
			*out = (struct swapz_decoded){ 0 };
		if (payload)
			*payload = NULL;
		return -EINVAL;
	}
	*payload = NULL;
	record_count = swapz_get_record_count(bytes);
	if (!record_count || record_count > SWAPZ_MAX_RECORDS ||
	    index >= record_count) {
		*out = (struct swapz_decoded){ 0 };
		return -ERANGE;
	}
	swapz_get_record(bytes, index, &record);
	swapz_decode_record(&record, out);
	if (!out->payload_length || out->payload_length > SWAPZ_MAX_COMPRESSED ||
	    out->payload_offset >= bytes_total ||
	    out->payload_length > bytes_total - out->payload_offset) {
		*out = (struct swapz_decoded){ 0 };
		return -EUCLEAN;
	}
	*payload = (const swapz_u8 *)bytes + out->payload_offset;
	return 0;
}

int swapz_lookup_validated(const void *bytes, swapz_u32 bytes_total,
			   swapz_u8 index, struct swapz_decoded *out,
			   const swapz_u8 **payload)
{
	const swapz_u8 *stored;
	int error;

	if (!out || !payload)
		return -EINVAL;
	*payload = NULL;
	error = swapz_lookup_validated_descriptor(bytes, bytes_total, index,
						  out, &stored);
	if (error)
		return error;
	if (swapz_crc32c_bytes(stored, out->payload_length) !=
	    out->payload_crc32c) {
		*out = (struct swapz_decoded){ 0 };
		return -EBADMSG;
	}
	*payload = stored;
	return 0;
}

int swapz_lookup(const void *bytes, swapz_u32 bytes_total, swapz_u8 index,
		 struct swapz_decoded *out, const swapz_u8 **payload)
{
	int error;

	if (!out || !payload)
		return -EINVAL;
	*payload = NULL;
	error = swapz_validate(bytes, bytes_total);
	if (error) {
		*out = (struct swapz_decoded){ 0 };
		return error;
	}
	return swapz_lookup_validated(bytes, bytes_total, index, out, payload);
}
