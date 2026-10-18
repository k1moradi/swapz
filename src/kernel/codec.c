// SPDX-License-Identifier: GPL-2.0-only
#include "codec.h"

#ifdef __KERNEL__
#include <linux/crc32c.h>
#include <linux/errno.h>
#include <linux/string.h>
#else
#include <errno.h>
#include <string.h>
#endif

/*
 * Keep the endian conversion explicit: the wire structs hold bytes, not
 * native-endian values. GCC/Clang define BYTE_ORDER on kernel and host builds.
 */
static swapz_u16 swapz_le16(swapz_u16 value)
{
#if __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
	return __builtin_bswap16(value);
#else
	return value;
#endif
}

static swapz_u32 swapz_le32(swapz_u32 value)
{
#if __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
	return __builtin_bswap32(value);
#else
	return value;
#endif
}

static swapz_u32 swapz_crc32c_state(swapz_u32 state, const void *data,
				swapz_u32 length)
{
#ifdef __KERNEL__
	return crc32c(state, data, length);
#else
	const swapz_u8 *ptr = data;
	swapz_u32 index;

	for (index = 0; index < length; ++index) {
		unsigned int bit;

		state ^= ptr[index];
		for (bit = 0; bit < 8; ++bit)
			state = (state >> 1) ^
				((state & 1U) ? 0x82f63b78U : 0U);
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

static void swapz_get_header(const void *bytes, struct swapz_header *header)
{
	memcpy(header, bytes, sizeof(*header));
}

static void swapz_get_record(const void *bytes, swapz_u8 index,
			   struct swapz_record *record)
{
	memcpy(record, (const swapz_u8 *)bytes + sizeof(struct swapz_header) +
	       (swapz_u32)index * sizeof(*record), sizeof(*record));
}

static void swapz_put_record(void *bytes, swapz_u8 index,
			   const struct swapz_record *record)
{
	memcpy((swapz_u8 *)bytes + sizeof(struct swapz_header) +
	       (swapz_u32)index * sizeof(*record), record, sizeof(*record));
}

int swapz_begin(struct swapz_builder *builder, void *bytes,
	      swapz_u32 bytes_total, swapz_u32 sequence)
{
	struct swapz_header header = { 0 };

	if (!builder || !bytes || !sequence ||
	    (bytes_total != SWAPZ_BLOCK_BYTES &&
	     bytes_total != 2U * SWAPZ_BLOCK_BYTES &&
	     bytes_total != 4U * SWAPZ_BLOCK_BYTES))
		return -EINVAL;

	memset(builder, 0, sizeof(*builder));
	builder->bytes = bytes;
	builder->bytes_total = bytes_total;
	builder->payload_start = (swapz_u16)bytes_total;
	builder->extent_blocks = (swapz_u8)(bytes_total / SWAPZ_BLOCK_BYTES);
	builder->sequence = sequence;
	header.magic_le = swapz_le32(SWAPZ_MAGIC);
	header.version_le = swapz_le16(SWAPZ_VERSION);
	header.extent_blocks = builder->extent_blocks;
	header.sequence_le = swapz_le32(sequence);
	memcpy(bytes, &header, sizeof(header));
	return 0;
}

static int swapz_append_crc(struct swapz_builder *builder,
			    swapz_u32 logical_page, swapz_u32 generation,
			    const void *payload, swapz_u16 length,
			    swapz_u32 payload_crc32c)
{
	struct swapz_record record = { 0 };
	struct swapz_record previous;
	swapz_u32 metadata_end;
	swapz_u16 offset;
	swapz_u8 index;

	if (!builder || !builder->bytes || builder->sealed ||
	    !payload || !length || length > SWAPZ_MAX_COMPRESSED ||
	    !generation)
		return -EINVAL;
	if (builder->count >= SWAPZ_MAX_RECORDS)
		return -ENOSPC;
	metadata_end = sizeof(struct swapz_header) +
		((swapz_u32)builder->count + 1U) * sizeof(struct swapz_record);
	if (builder->payload_start < length ||
	    (swapz_u32)builder->payload_start - length < metadata_end)
		return -ENOSPC;

	/* One authoritative record per logical slot in any single extent. */
	for (index = 0; index < builder->count; ++index) {
		swapz_get_record(builder->bytes, index, &previous);
		if (swapz_le32(previous.logical_page_le) == logical_page)
			return -EEXIST;
	}

	offset = builder->payload_start - length;
	record.logical_page_le = swapz_le32(logical_page);
	record.generation_le = swapz_le32(generation);
	record.payload_offset_le = swapz_le16(offset);
	record.payload_length_le = swapz_le16(length);
	record.payload_crc32c_le = swapz_le32(payload_crc32c);
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
				length, payload_crc32c);
}

int swapz_append(struct swapz_builder *builder, swapz_u32 logical_page,
	       swapz_u32 generation, const void *payload, swapz_u16 length)
{
	return swapz_append_crc(builder, logical_page, generation, payload,
				length, swapz_crc32c_bytes(payload, length));
}

int swapz_seal(struct swapz_builder *builder)
{
	struct swapz_header header;
	swapz_u32 metadata_end;

	if (!builder || !builder->bytes || builder->sealed || !builder->count)
		return -EINVAL;
	if (builder->count > SWAPZ_MAX_RECORDS)
		return -EUCLEAN;
	metadata_end = sizeof(header) +
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

	swapz_get_header(builder->bytes, &header);
	header.record_count = builder->count;
	header.metadata_crc32c_le = 0;
	memcpy(builder->bytes, &header, sizeof(header));
	header.metadata_crc32c_le = swapz_le32(
		swapz_crc32c_bytes(builder->bytes, metadata_end));
	memcpy(builder->bytes, &header, sizeof(header));
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

	if (!bytes || (bytes_total != SWAPZ_BLOCK_BYTES &&
		       bytes_total != 2U * SWAPZ_BLOCK_BYTES &&
		       bytes_total != 4U * SWAPZ_BLOCK_BYTES))
		return -EINVAL;

	swapz_get_header(bytes, &header);
	if (swapz_le32(header.magic_le) != SWAPZ_MAGIC ||
	    swapz_le16(header.version_le) != SWAPZ_VERSION ||
	    header.extent_blocks != bytes_total / SWAPZ_BLOCK_BYTES ||
	    !header.record_count || header.record_count > SWAPZ_MAX_RECORDS ||
	    !swapz_le32(header.sequence_le))
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
		swapz_u32 start, length, slot;
		swapz_u8 earlier;

		swapz_get_record(bytes, index, &record);
		start = swapz_le16(record.payload_offset_le);
		length = swapz_le16(record.payload_length_le);
		slot = swapz_le32(record.logical_page_le);
		if (!swapz_le32(record.generation_le) ||
		    !length || length > SWAPZ_MAX_COMPRESSED ||
		    start < metadata_end ||
		    start > bytes_total || length > bytes_total - start ||
		    start + length != previous_end)
			return -EUCLEAN;
		previous_end = start;
		for (earlier = 0; earlier < index; ++earlier) {
			struct swapz_record existing;

			swapz_get_record(bytes, earlier, &existing);
			if (swapz_le32(existing.logical_page_le) == slot)
				return -EUCLEAN;
		}
	}
	return 0;
}

int swapz_peek(const void *bytes, swapz_u32 bytes_total, swapz_u8 index,
	     struct swapz_decoded *out)
{
	struct swapz_header header;
	struct swapz_record record;
	int error;

	if (!out)
		return -EINVAL;
	*out = (struct swapz_decoded){ 0 };
	error = swapz_validate(bytes, bytes_total);
	if (error)
		return error;
	swapz_get_header(bytes, &header);
	if (index >= header.record_count)
		return -ERANGE;
	swapz_get_record(bytes, index, &record);
	out->logical_page = swapz_le32(record.logical_page_le);
	out->generation = swapz_le32(record.generation_le);
	out->payload_offset = swapz_le16(record.payload_offset_le);
	out->payload_length = swapz_le16(record.payload_length_le);
	out->payload_crc32c = swapz_le32(record.payload_crc32c_le);
	return 0;
}

int swapz_lookup_validated(const void *bytes, swapz_u32 bytes_total,
			 swapz_u8 index, struct swapz_decoded *out,
			 const swapz_u8 **payload)
{
	struct swapz_header header;
	struct swapz_record record;
	const swapz_u8 *stored;

	if (!bytes || !out || !payload ||
	    (bytes_total != SWAPZ_BLOCK_BYTES &&
	     bytes_total != 2U * SWAPZ_BLOCK_BYTES &&
	     bytes_total != 4U * SWAPZ_BLOCK_BYTES))
		return -EINVAL;
	*out = (struct swapz_decoded){ 0 };
	*payload = NULL;
	swapz_get_header(bytes, &header);
	if (index >= header.record_count)
		return -ERANGE;
	swapz_get_record(bytes, index, &record);
	out->logical_page = swapz_le32(record.logical_page_le);
	out->generation = swapz_le32(record.generation_le);
	out->payload_offset = swapz_le16(record.payload_offset_le);
	out->payload_length = swapz_le16(record.payload_length_le);
	out->payload_crc32c = swapz_le32(record.payload_crc32c_le);
	if (!out->payload_length || out->payload_length > SWAPZ_MAX_COMPRESSED ||
	    out->payload_offset >= bytes_total ||
	    out->payload_length > bytes_total - out->payload_offset) {
		*out = (struct swapz_decoded){ 0 };
		return -EUCLEAN;
	}
	stored = (const swapz_u8 *)bytes + out->payload_offset;
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
	if (error)
		return error;
	return swapz_lookup_validated(bytes, bytes_total, index, out, payload);
}

