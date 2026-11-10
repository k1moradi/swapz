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
#elif defined(__aarch64__) && defined(__ARM_FEATURE_CRC32) && \
	__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
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

/* Reject an append source anywhere inside the builder-owned extent. Compare
 * address differences instead of forming potentially wrapping end addresses;
 * unrelated C object pointers must not be ordered or subtracted directly. */
static inline int swapz_payload_overlaps_storage(const void *extent,
						 swapz_u32 extent_bytes,
						 const void *payload,
						 swapz_u32 length)
{
	const unsigned long extent_address = (unsigned long)extent;
	const unsigned long payload_address = (unsigned long)payload;

	if (payload_address >= extent_address)
		return payload_address - extent_address < extent_bytes;
	return extent_address - payload_address < length;
}

/* The legacy detach/reattach path also validates overlap against an extent.
 * Keep its established name while both migration paths coexist. */
static inline int swapz_payload_overlaps_extent(
			const struct swapz_builder *builder,
			const void *payload, swapz_u16 length)
{
	return swapz_payload_overlaps_storage(builder->bytes, builder->bytes_total,
					      payload, length);
}

static swapz_u32 swapz_crc32c_state(swapz_u32 state, const void *data,
				    swapz_u32 length)
{
#ifdef __KERNEL__
	return crc32c(state, data, length);
#elif defined(__aarch64__) && defined(__ARM_FEATURE_CRC32) && \
	__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
	/* CRC32CD consumes a numeric doubleword. Restrict the wide native path
	 * to little-endian hosts so its byte order matches the CRC byte stream. */
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

static inline swapz_u8 swapz_length_encoding(swapz_u16 raw_length)
{
	switch (raw_length & (SWAPZ_RECORD_DELTA64_FLAG | SWAPZ_RECORD_SHUF8_FLAG)) {
	case 0:
		return SWAPZ_ENCODING_LZ4;
	case SWAPZ_RECORD_DELTA64_FLAG:
		return SWAPZ_ENCODING_DELTA64;
	case SWAPZ_RECORD_DELTA64_FLAG | SWAPZ_RECORD_SHUF8_FLAG:
		return SWAPZ_ENCODING_DELTA64_SHUF8;
	default:
		return SWAPZ_ENCODING_INVALID;
	}
}

static inline swapz_u16 swapz_encoding_length_flags(swapz_u8 encoding)
{
	return encoding == SWAPZ_ENCODING_DELTA64 ? SWAPZ_RECORD_DELTA64_FLAG :
		encoding == SWAPZ_ENCODING_DELTA64_SHUF8 ?
		SWAPZ_RECORD_DELTA64_FLAG | SWAPZ_RECORD_SHUF8_FLAG : 0U;
}

static inline int swapz_encoding_valid(swapz_u8 encoding)
{
	return encoding == SWAPZ_ENCODING_LZ4 ||
		encoding == SWAPZ_ENCODING_DELTA64 ||
		encoding == SWAPZ_ENCODING_DELTA64_SHUF8;
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
		.encoding = swapz_length_encoding(raw_length),
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

/*
 * Shared append preflight. It checks builder state, payload bounds/overlap,
 * encoding and available extent space without reading payload bytes.
 */
static int swapz_append_validate(struct swapz_builder *builder,
				 swapz_u32 generation,
				 const void *payload, swapz_u16 length,
				 swapz_u8 encoding, swapz_u16 *payload_offset)
{
	swapz_u32 metadata_end;

	if (!builder || !builder->bytes || builder->sealed ||
	    !payload || !length || length > SWAPZ_MAX_COMPRESSED ||
	    !generation || !swapz_encoding_valid(encoding) ||
	    swapz_payload_overlaps_storage(builder->bytes, builder->bytes_total,
					   payload, length))
		return -EINVAL;
	if (builder->count >= SWAPZ_MAX_RECORDS)
		return -ENOSPC;
	metadata_end = sizeof(struct swapz_header) +
		((swapz_u32)builder->count + 1U) * sizeof(struct swapz_record);
	if (builder->payload_start < length ||
	    (swapz_u32)builder->payload_start - length < metadata_end)
		return -ENOSPC;

	*payload_offset = builder->payload_start - length;
	return 0;
}

/* Generic append paths retain duplicate protection. The production unique
 * paths may skip only this bounded quadratic scan after proving uniqueness. */
static int swapz_append_validate_logical_page(
	const struct swapz_builder *builder, swapz_u32 logical_page)
{
	const swapz_u32 logical_page_le = swapz_le32(logical_page);
	swapz_u8 index;

	for (index = 0; index < builder->count; ++index)
		if (swapz_record_logical_le(builder->bytes, index) ==
		    logical_page_le)
			return -EEXIST;
	return 0;
}

/* Commit is infallible only after append preflight succeeds; callers hold the
 * builder exclusively until both descriptor and payload are stored. */
static void swapz_append_record(struct swapz_builder *builder,
				swapz_u32 logical_page, swapz_u32 generation,
				const void *payload, swapz_u16 length,
				swapz_u32 payload_crc32c, swapz_u8 encoding,
				swapz_u16 payload_offset)
{
	const struct swapz_record record = {
		.logical_page_le = swapz_le32(logical_page),
		.generation_le = swapz_le32(generation),
		.payload_offset_le = swapz_le16(payload_offset),
		.payload_length_le = swapz_le16(length |
			swapz_encoding_length_flags(encoding)),
		.payload_crc32c_le = swapz_le32(payload_crc32c),
	};

	memcpy(builder->bytes + payload_offset, payload, length);
	swapz_put_record(builder->bytes, builder->count, &record);
	builder->last_payload_crc32c = payload_crc32c;
	builder->last_payload_offset = payload_offset;
	builder->last_payload_length = length;
	builder->last_encoding = encoding;
	builder->count++;
	builder->payload_start = payload_offset;
}

static int swapz_append_crc(struct swapz_builder *builder,
			    swapz_u32 logical_page, swapz_u32 generation,
			    const void *payload, swapz_u16 length,
			    swapz_u32 payload_crc32c, swapz_u8 encoding,
			    int logical_page_unique)
{
	swapz_u16 payload_offset;
	int error;

	error = swapz_append_validate(builder, generation, payload, length,
				      encoding, &payload_offset);
	if (error)
		return error;
	if (!logical_page_unique) {
		error = swapz_append_validate_logical_page(builder, logical_page);
		if (error)
			return error;
	}
	swapz_append_record(builder, logical_page, generation, payload, length,
			    payload_crc32c, encoding, payload_offset);
	return 0;
}

int swapz_append_prehashed(struct swapz_builder *builder,
			   swapz_u32 logical_page, swapz_u32 generation,
			   const void *payload, swapz_u16 length,
			   swapz_u32 payload_crc32c)
{
	return swapz_append_crc(builder, logical_page, generation, payload,
				length, payload_crc32c, SWAPZ_ENCODING_LZ4, 0);
}

int swapz_append_prehashed_encoded(struct swapz_builder *builder,
				   swapz_u32 logical_page, swapz_u32 generation,
				   const void *payload, swapz_u16 length,
				   swapz_u32 payload_crc32c, swapz_u8 encoding)
{
	return swapz_append_crc(builder, logical_page, generation, payload,
				length, payload_crc32c, encoding, 0);
}

int swapz_append_prehashed_encoded_unique(struct swapz_builder *builder,
				   swapz_u32 logical_page, swapz_u32 generation,
				   const void *payload, swapz_u16 length,
				   swapz_u32 payload_crc32c, swapz_u8 encoding)
{
	return swapz_append_crc(builder, logical_page, generation, payload,
				length, payload_crc32c, encoding, 1);
}

static int swapz_append_encoded_checked(struct swapz_builder *builder,
				       swapz_u32 logical_page,
				       swapz_u32 generation,
				       const void *payload, swapz_u16 length,
				       swapz_u8 encoding, int logical_page_unique)
{
	swapz_u16 payload_offset;
	int error;

	error = swapz_append_validate(builder, generation, payload, length,
				      encoding, &payload_offset);
	if (error)
		return error;
	if (!logical_page_unique) {
		error = swapz_append_validate_logical_page(builder, logical_page);
		if (error)
			return error;
	}
	/* Hash once, after every possible rejection, before writing bytes. */
	swapz_append_record(builder, logical_page, generation, payload, length,
			    swapz_crc32c_bytes(payload, length), encoding,
			    payload_offset);
	return 0;
}

int swapz_append_encoded(struct swapz_builder *builder,
			 swapz_u32 logical_page, swapz_u32 generation,
			 const void *payload, swapz_u16 length,
			 swapz_u8 encoding)
{
	return swapz_append_encoded_checked(builder, logical_page, generation,
					    payload, length, encoding, 0);
}

int swapz_append_encoded_unique(struct swapz_builder *builder,
				swapz_u32 logical_page, swapz_u32 generation,
				const void *payload, swapz_u16 length,
				swapz_u8 encoding)
{
	return swapz_append_encoded_checked(builder, logical_page, generation,
					    payload, length, encoding, 1);
}

int swapz_append(struct swapz_builder *builder, swapz_u32 logical_page,
		 swapz_u32 generation, const void *payload, swapz_u16 length)
{
	swapz_u16 payload_offset;
	int error;

	/*
	 * A bad caller-provided length may exceed its actual source allocation.
	 * The shared gate then checks overlap, builder capacity and duplicates
	 * before the one CRC read. Rejected calls never inspect payload bytes.
	 */
	if (!payload || !length || length > SWAPZ_MAX_COMPRESSED)
		return -EINVAL;
	error = swapz_append_validate(builder, generation, payload, length,
				      SWAPZ_ENCODING_LZ4, &payload_offset);
	if (error)
		return error;
	error = swapz_append_validate_logical_page(builder, logical_page);
	if (error)
		return error;
	swapz_append_record(builder, logical_page, generation, payload, length,
			    swapz_crc32c_bytes(payload, length),
			    SWAPZ_ENCODING_LZ4, payload_offset);
	return 0;
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


/*
 * Transitional RAM-only descriptor transport for the existing extent codec.
 * This primitive does not enable physical backing: the serialized write,
 * selective/parallel read, GC relocation, and mapping commit paths must all
 * establish RAM snapshot ownership before the physical interlock can change.
 *
 * A successful detach has a zero-filled descriptor prefix. Compressed payload
 * bytes, offsets and extent geometry remain bit-for-bit identical, including
 * payload bytes stored later in the first 4096-byte block.
 */
int swapz_detach_extent_metadata(
	struct swapz_builder *builder, struct swapz_ram_extent_metadata *metadata)
{
	swapz_u32 metadata_bytes;
	int error;

	if (!builder || !metadata || !builder->bytes || !builder->sealed ||
	    !builder->count || builder->count > SWAPZ_MAX_RECORDS ||
	    !swapz_valid_extent_bytes(builder->bytes_total) ||
	    swapz_payload_overlaps_extent(
		    builder, metadata, (swapz_u32)sizeof(*metadata)))
		return -EINVAL;
	metadata_bytes = sizeof(struct swapz_header) +
		(swapz_u32)builder->count * sizeof(struct swapz_record);
	if (metadata_bytes > sizeof(metadata->bytes) ||
	    metadata_bytes > builder->payload_start)
		return -EUCLEAN;
	error = swapz_validate(builder->bytes, builder->bytes_total);
	if (error)
		return error;

	/* Success-only mutation: metadata remains caller-owned RAM and its
	 * unused tail is initialized, preventing stale descriptors from escaping
	 * through a recycled snapshot. No allocator or heap ownership involved.
	 */
	memset(metadata, 0, sizeof(*metadata));
	memcpy(metadata->bytes, builder->bytes, metadata_bytes);
	metadata->length = (swapz_u16)metadata_bytes;
	memset(builder->bytes, 0, metadata_bytes);
	return 0;
}

int swapz_attach_extent_metadata(
	void *extent, swapz_u32 bytes_total,
	const struct swapz_ram_extent_metadata *metadata)
{
	const swapz_u8 *prefix;
	swapz_u32 expected_bytes;
	swapz_u32 index;
	struct swapz_builder overlap_check;
	int error;

	if (!extent || !metadata || !swapz_valid_extent_bytes(bytes_total) ||
	    metadata->length < sizeof(struct swapz_header) ||
	    metadata->length > sizeof(metadata->bytes))
		return -EINVAL;
	overlap_check = (struct swapz_builder){
		.bytes = extent, .bytes_total = bytes_total,
	};
	if (swapz_payload_overlaps_extent(
		    &overlap_check, metadata, (swapz_u32)sizeof(*metadata)))
		return -EINVAL;

	/* Reject malformed or substituted snapshots before touching scratch.
	 * The legacy validator accesses only the count-bounded metadata prefix,
	 * not the remainder of the stated extent geometry.
	 */
	prefix = metadata->bytes;
	expected_bytes = sizeof(struct swapz_header) +
		(swapz_u32)prefix[offsetof(struct swapz_header, record_count)] *
		sizeof(struct swapz_record);
	if (expected_bytes != metadata->length)
		return -EUCLEAN;
	error = swapz_validate(prefix, bytes_total);
	if (error)
		return error;
	for (index = 0; index < metadata->length; ++index)
		if (((swapz_u8 *)extent)[index] != 0)
			return -ESTALE;
	memcpy(extent, prefix, metadata->length);
	return 0;
}

int swapz_validate_metadata_crc(const void *bytes, swapz_u32 bytes_total)
{
	struct swapz_header header;
	swapz_u32 saved_crc;
	swapz_u32 metadata_end;
	swapz_u32 computed_crc;
	swapz_u32 crc_state;

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
	return saved_crc == computed_crc ? 0 : -EBADMSG;
}

int swapz_validate(const void *bytes, swapz_u32 bytes_total)
{
	struct swapz_record record;
	swapz_u32 metadata_end;
	swapz_u32 previous_end = bytes_total;
	swapz_u8 record_count;
	swapz_u8 index;
	int error;

	error = swapz_validate_metadata_crc(bytes, bytes_total);
	if (error)
		return error;
	record_count = swapz_get_record_count(bytes);
	metadata_end = sizeof(struct swapz_header) +
		(swapz_u32)record_count * sizeof(struct swapz_record);

	for (index = 0; index < record_count; ++index) {
		swapz_u32 start, length;
		swapz_u8 earlier;

		swapz_get_record(bytes, index, &record);
		start = swapz_le16(record.payload_offset_le);
		length = swapz_le16(record.payload_length_le) &
			SWAPZ_RECORD_LENGTH_MASK;
		if (start + length != previous_end ||
		    !swapz_encoding_valid(swapz_length_encoding(
			    swapz_le16(record.payload_length_le))) ||
		    !record.generation_le ||
		    !length || length > SWAPZ_MAX_COMPRESSED ||
		    start < metadata_end)
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
	swapz_u32 metadata_end;
	swapz_u8 record_count;

	if (!bytes || !out || !swapz_valid_extent_bytes(bytes_total)) {
		if (out)
			*out = (struct swapz_decoded){ 0 };
		if (payload)
			*payload = NULL;
		return -EINVAL;
	}
	if (payload)
		*payload = NULL;
	record_count = swapz_get_record_count(bytes);
	if (!record_count || record_count > SWAPZ_MAX_RECORDS) {
		*out = (struct swapz_decoded){ 0 };
		return -EUCLEAN;
	}
	if (index >= record_count) {
		*out = (struct swapz_decoded){ 0 };
		return -ERANGE;
	}
	metadata_end = sizeof(struct swapz_header) +
		(swapz_u32)record_count * sizeof(struct swapz_record);
	swapz_get_record(bytes, index, &record);
	swapz_decode_record(&record, out);
	/* A metadata CRC authenticates the record bytes, not their semantics.
	 * Never expose a payload pointer into the authenticated metadata area. */
	if (!out->generation || out->payload_offset < metadata_end ||
	    !out->payload_length || out->payload_length > SWAPZ_MAX_COMPRESSED ||
	    !swapz_encoding_valid(out->encoding) ||
	    out->payload_offset >= bytes_total ||
	    out->payload_length > bytes_total - out->payload_offset) {
		*out = (struct swapz_decoded){ 0 };
		return -EUCLEAN;
	}
	if (payload)
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

/*
 * The production builder is deliberately independent of the legacy in-band
 * codec. All descriptor bytes live in caller-owned RAM; only packed payload
 * bytes and zero padding can enter a lower write. SWAPZ_CODEC_METADATA_ON_MEDIA
 * must remain zero: serialized extent metadata is fixture-only compatibility,
 * never a production lower-image format.
 */
static int swapz_ram_extent_begin_checked(
	struct swapz_ram_extent *builder, void *bytes, swapz_u32 bytes_total,
	swapz_u32 sequence, struct swapz_decoded *records,
	swapz_u8 record_capacity, int logical_pages_unique)
{
	swapz_u32 record_bytes = 0;

	if (!builder || !bytes || !sequence ||
	    !swapz_valid_extent_bytes(bytes_total) ||
	    !record_capacity || record_capacity > SWAPZ_MAX_RECORDS ||
	    (!logical_pages_unique && !records))
		return -EINVAL;
	if (records)
		record_bytes = (swapz_u32)record_capacity * sizeof(*records);
	/* RAM descriptors and the exact lower-write image are exclusive
	 * ownership domains. Aliasing would make descriptor mutation observable
	 * as backing bytes or let seal() erase authoritative metadata. */
	if ((records && swapz_payload_overlaps_storage(
			    bytes, bytes_total, records, record_bytes)) ||
	    swapz_payload_overlaps_storage(bytes, bytes_total,
					   builder, sizeof(*builder)) ||
	    (records && swapz_payload_overlaps_storage(
			    records, record_bytes, builder, sizeof(*builder))))
		return -EINVAL;

	*builder = (struct swapz_ram_extent) {
		.bytes = bytes,
		.records = records,
		.bytes_total = bytes_total,
		.sequence = sequence,
		.payload_start = (swapz_u16)bytes_total,
		.record_capacity = record_capacity,
		.extent_blocks = (swapz_u8)(bytes_total / SWAPZ_BLOCK_BYTES),
		.logical_pages_unique = logical_pages_unique != 0,
	};
	/* Do not touch the lower image until all individual appends succeed.
	 * seal() clears every byte not covered by a packed payload. */
	return 0;
}

int swapz_ram_extent_begin(struct swapz_ram_extent *builder, void *bytes,
			   swapz_u32 bytes_total, swapz_u32 sequence,
			   struct swapz_decoded *records, swapz_u8 record_capacity)
{
	return swapz_ram_extent_begin_checked(
		builder, bytes, bytes_total, sequence, records, record_capacity, 0);
}

int swapz_ram_extent_begin_unique(struct swapz_ram_extent *builder, void *bytes,
				  swapz_u32 bytes_total, swapz_u32 sequence,
				  swapz_u8 record_capacity)
{
	return swapz_ram_extent_begin_checked(
		builder, bytes, bytes_total, sequence, NULL, record_capacity, 1);
}

static int swapz_ram_extent_append_checked(struct swapz_ram_extent *builder,
					    swapz_u32 logical_page,
					    swapz_u32 generation,
					    const void *payload,
					    swapz_u16 payload_length,
					    swapz_u32 precomputed_crc32c,
					    swapz_u8 encoding,
					    int crc_precomputed)
{
	swapz_u16 payload_offset;
	swapz_u8 record_index;
	swapz_u32 payload_crc32c;

	if (!builder || !builder->bytes ||
	    (!builder->logical_pages_unique && !builder->records) ||
	    !builder->sequence || builder->sealed ||
	    !builder->record_capacity ||
	    builder->record_capacity > SWAPZ_MAX_RECORDS ||
	    !swapz_valid_extent_bytes(builder->bytes_total) ||
	    builder->extent_blocks != builder->bytes_total / SWAPZ_BLOCK_BYTES ||
	    !payload || !payload_length ||
	    payload_length > SWAPZ_MAX_COMPRESSED || !generation ||
	    !swapz_encoding_valid(encoding) ||
	    swapz_payload_overlaps_storage(builder->bytes, builder->bytes_total,
					   payload, payload_length) ||
	    /* The builder holds transient descriptor metadata and pointers.
	     * Those RAM control bytes must never become lower payload data. */
	    swapz_payload_overlaps_storage(builder, sizeof(*builder),
					   payload, payload_length) ||
	    (builder->records && swapz_payload_overlaps_storage(
		builder->records,
		(swapz_u32)builder->record_capacity * sizeof(*builder->records),
		payload, payload_length)))
		return -EINVAL;
	if (builder->count >= builder->record_capacity)
		return -ENOSPC;
	if (builder->payload_start > builder->bytes_total ||
	    builder->payload_start < payload_length)
		return -ENOSPC;
	/* Generic callers retain duplicate protection. Unique mode is reserved
	 * for an ordered production owner that proved the extent's page set. */
	if (!builder->logical_pages_unique)
		for (record_index = 0; record_index < builder->count; ++record_index)
			if (builder->records[record_index].logical_page == logical_page)
				return -EEXIST;
	payload_offset = builder->payload_start - payload_length;
	payload_crc32c = crc_precomputed ? precomputed_crc32c :
		swapz_crc32c_bytes(payload, payload_length);
	memcpy(builder->bytes + payload_offset, payload, payload_length);
	builder->last_record = (struct swapz_decoded) {
		.logical_page = logical_page,
		.generation = generation,
		.payload_crc32c = payload_crc32c,
		.payload_offset = payload_offset,
		.payload_length = payload_length,
		.encoding = encoding,
	};
	if (builder->records)
		builder->records[builder->count] = builder->last_record;
	builder->count++;
	builder->payload_start = payload_offset;
	return 0;
}

int swapz_ram_extent_append(struct swapz_ram_extent *builder,
			    swapz_u32 logical_page, swapz_u32 generation,
			    const void *payload, swapz_u16 payload_length,
			    swapz_u8 encoding)
{
	return swapz_ram_extent_append_checked(builder, logical_page,
					       generation, payload,
					       payload_length, 0, encoding, 0);
}

int swapz_ram_extent_append_prehashed(struct swapz_ram_extent *builder,
				      swapz_u32 logical_page,
				      swapz_u32 generation, const void *payload,
				      swapz_u16 payload_length,
				      swapz_u32 payload_crc32c, swapz_u8 encoding)
{
	return swapz_ram_extent_append_checked(builder, logical_page,
					       generation, payload,
					       payload_length, payload_crc32c,
					       encoding, 1);
}

int swapz_ram_extent_seal(struct swapz_ram_extent *builder)
{
	if (!builder || !builder->bytes ||
	    (!builder->logical_pages_unique && !builder->records) ||
	    !swapz_valid_extent_bytes(builder->bytes_total) ||
	    builder->extent_blocks != builder->bytes_total / SWAPZ_BLOCK_BYTES ||
	    !builder->record_capacity ||
	    builder->record_capacity > SWAPZ_MAX_RECORDS ||
	    builder->sealed || !builder->count ||
	    builder->count > builder->record_capacity ||
	    builder->payload_start > builder->bytes_total ||
	    /*
	     * The last appended payload begins at payload_start. Reject a
	     * damaged cursor before zero-padding could erase live payload bytes
	     * or leave stale staging bytes in an otherwise sealed lower image.
	     */
	    builder->last_record.payload_offset != builder->payload_start ||
	    !builder->last_record.payload_length ||
	    builder->last_record.payload_length > SWAPZ_MAX_COMPRESSED ||
	    builder->last_record.payload_length >
		    builder->bytes_total - builder->payload_start)
		return -EINVAL;

	/* No header or descriptor publication to the physical data area. */
	memset(builder->bytes, 0, builder->payload_start);
	builder->sealed = 1;
	return 0;
}

int swapz_ram_extent_read(const struct swapz_ram_extent *builder,
			  swapz_u8 record_index, swapz_u32 logical_page,
			  swapz_u32 generation, const swapz_u8 **payload)
{
	const struct swapz_decoded *record;
	const swapz_u8 *stored;

	if (!payload)
		return -EINVAL;
	*payload = NULL;
	if (!builder || !builder->bytes || !builder->records ||
	    !builder->sealed || !builder->sequence ||
	    !swapz_valid_extent_bytes(builder->bytes_total) ||
	    !builder->record_capacity ||
	    builder->record_capacity > SWAPZ_MAX_RECORDS ||
	    !builder->count || builder->count > builder->record_capacity ||
	    record_index >= builder->count)
		return -EINVAL;
	record = &builder->records[record_index];
	if (record->logical_page != logical_page ||
	    record->generation != generation || !generation ||
	    !record->payload_length ||
	    record->payload_length > SWAPZ_MAX_COMPRESSED ||
	    !swapz_encoding_valid(record->encoding) ||
	    record->payload_offset < builder->payload_start ||
	    record->payload_offset >= builder->bytes_total ||
	    record->payload_length >
		builder->bytes_total - record->payload_offset)
		return -EUCLEAN;
	stored = builder->bytes + record->payload_offset;
	if (swapz_crc32c_bytes(stored, record->payload_length) !=
	    record->payload_crc32c)
		return -EBADMSG;
	*payload = stored;
	return 0;
}
