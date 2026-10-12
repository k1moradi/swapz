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
static sv3_u16 sv3_le16(sv3_u16 value)
{
#if __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
	return __builtin_bswap16(value);
#else
	return value;
#endif
}

static sv3_u32 sv3_le32(sv3_u32 value)
{
#if __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
	return __builtin_bswap32(value);
#else
	return value;
#endif
}

static sv3_u32 sv3_crc32c_state(sv3_u32 state, const void *data,
				sv3_u32 length)
{
#ifdef __KERNEL__
	return crc32c(state, data, length);
#else
	const sv3_u8 *ptr = data;
	sv3_u32 index;

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

sv3_u32 sv3_crc32c_bytes(const void *data, sv3_u32 length)
{
	if (!data && length)
		return 0;
	return ~sv3_crc32c_state(~0U, data, length);
}

static void sv3_get_header(const void *bytes, struct sv3_header *header)
{
	memcpy(header, bytes, sizeof(*header));
}

static void sv3_get_record(const void *bytes, sv3_u8 index,
			   struct sv3_record *record)
{
	memcpy(record, (const sv3_u8 *)bytes + sizeof(struct sv3_header) +
	       (sv3_u32)index * sizeof(*record), sizeof(*record));
}

static void sv3_put_record(void *bytes, sv3_u8 index,
			   const struct sv3_record *record)
{
	memcpy((sv3_u8 *)bytes + sizeof(struct sv3_header) +
	       (sv3_u32)index * sizeof(*record), record, sizeof(*record));
}

int sv3_begin(struct sv3_builder *builder, void *bytes,
	      sv3_u32 bytes_total, sv3_u32 sequence)
{
	struct sv3_header header = { 0 };

	if (!builder || !bytes || !sequence ||
	    (bytes_total != SV3_BLOCK_BYTES &&
	     bytes_total != 2U * SV3_BLOCK_BYTES &&
	     bytes_total != 4U * SV3_BLOCK_BYTES))
		return -EINVAL;

	memset(builder, 0, sizeof(*builder));
	memset(bytes, 0, bytes_total);
	builder->bytes = bytes;
	builder->bytes_total = bytes_total;
	builder->payload_start = (sv3_u16)bytes_total;
	builder->extent_blocks = (sv3_u8)(bytes_total / SV3_BLOCK_BYTES);
	builder->sequence = sequence;
	header.magic_le = sv3_le32(SV3_MAGIC);
	header.version_le = sv3_le16(SV3_VERSION);
	header.extent_blocks = builder->extent_blocks;
	header.sequence_le = sv3_le32(sequence);
	memcpy(bytes, &header, sizeof(header));
	return 0;
}

int sv3_append(struct sv3_builder *builder, sv3_u32 logical_page,
	       sv3_u32 generation, const void *payload, sv3_u16 length)
{
	struct sv3_record record = { 0 };
	struct sv3_record previous;
	sv3_u32 metadata_end;
	sv3_u16 offset;
	sv3_u8 index;

	if (!builder || !builder->bytes || builder->sealed ||
	    !payload || !length || length > SV3_MAX_COMPRESSED ||
	    !generation)
		return -EINVAL;
	if (builder->count >= SV3_MAX_RECORDS)
		return -ENOSPC;
	metadata_end = sizeof(struct sv3_header) +
		((sv3_u32)builder->count + 1U) * sizeof(struct sv3_record);
	if (builder->payload_start < length ||
	    (sv3_u32)builder->payload_start - length < metadata_end)
		return -ENOSPC;

	/* One authoritative record per logical slot in any single extent. */
	for (index = 0; index < builder->count; ++index) {
		sv3_get_record(builder->bytes, index, &previous);
		if (sv3_le32(previous.logical_page_le) == logical_page)
			return -EEXIST;
	}

	offset = builder->payload_start - length;
	record.logical_page_le = sv3_le32(logical_page);
	record.generation_le = sv3_le32(generation);
	record.payload_offset_le = sv3_le16(offset);
	record.payload_length_le = sv3_le16(length);
	record.payload_crc32c_le = sv3_le32(sv3_crc32c_bytes(payload, length));
	memcpy(builder->bytes + offset, payload, length);
	sv3_put_record(builder->bytes, builder->count, &record);
	builder->count++;
	builder->payload_start = offset;
	return 0;
}

int sv3_seal(struct sv3_builder *builder)
{
	struct sv3_header header;
	sv3_u32 metadata_end;

	if (!builder || !builder->bytes || builder->sealed || !builder->count)
		return -EINVAL;
	if (builder->count > SV3_MAX_RECORDS)
		return -EUCLEAN;
	metadata_end = sizeof(header) +
		(sv3_u32)builder->count * sizeof(struct sv3_record);
	if (metadata_end > builder->payload_start)
		return -EUCLEAN;

	sv3_get_header(builder->bytes, &header);
	header.record_count = builder->count;
	header.metadata_crc32c_le = 0;
	memcpy(builder->bytes, &header, sizeof(header));
	header.metadata_crc32c_le = sv3_le32(
		sv3_crc32c_bytes(builder->bytes, metadata_end));
	memcpy(builder->bytes, &header, sizeof(header));
	builder->sealed = 1;
	return 0;
}

int sv3_validate(const void *bytes, sv3_u32 bytes_total)
{
	struct sv3_header header;
	struct sv3_record record;
	sv3_u32 saved_crc;
	sv3_u32 metadata_end;
	sv3_u32 computed_crc;
	sv3_u32 previous_end = bytes_total;
	sv3_u32 crc_state;
	sv3_u8 index;

	if (!bytes || (bytes_total != SV3_BLOCK_BYTES &&
		       bytes_total != 2U * SV3_BLOCK_BYTES &&
		       bytes_total != 4U * SV3_BLOCK_BYTES))
		return -EINVAL;

	sv3_get_header(bytes, &header);
	if (sv3_le32(header.magic_le) != SV3_MAGIC ||
	    sv3_le16(header.version_le) != SV3_VERSION ||
	    header.extent_blocks != bytes_total / SV3_BLOCK_BYTES ||
	    !header.record_count || header.record_count > SV3_MAX_RECORDS ||
	    !sv3_le32(header.sequence_le))
		return -EUCLEAN;
	metadata_end = sizeof(header) +
		(sv3_u32)header.record_count * sizeof(struct sv3_record);
	if (metadata_end > bytes_total)
		return -EUCLEAN;

	saved_crc = sv3_le32(header.metadata_crc32c_le);
	header.metadata_crc32c_le = 0;
	crc_state = sv3_crc32c_state(~0U, &header, sizeof(header));
	crc_state = sv3_crc32c_state(crc_state,
				    (const sv3_u8 *)bytes + sizeof(header),
				    metadata_end - sizeof(header));
	computed_crc = ~crc_state;
	if (saved_crc != computed_crc)
		return -EBADMSG;

	for (index = 0; index < header.record_count; ++index) {
		sv3_u32 start, length, slot;
		sv3_u8 earlier;

		sv3_get_record(bytes, index, &record);
		start = sv3_le16(record.payload_offset_le);
		length = sv3_le16(record.payload_length_le);
		slot = sv3_le32(record.logical_page_le);
		if (!sv3_le32(record.generation_le) ||
		    !length || length > SV3_MAX_COMPRESSED ||
		    start < metadata_end ||
		    start > bytes_total || length > bytes_total - start ||
		    start + length != previous_end)
			return -EUCLEAN;
		previous_end = start;
		for (earlier = 0; earlier < index; ++earlier) {
			struct sv3_record existing;

			sv3_get_record(bytes, earlier, &existing);
			if (sv3_le32(existing.logical_page_le) == slot)
				return -EUCLEAN;
		}
	}
	return 0;
}

int sv3_lookup(const void *bytes, sv3_u32 bytes_total, sv3_u8 index,
	       struct sv3_decoded *out, const sv3_u8 **payload)
{
	struct sv3_header header;
	struct sv3_record record;
	sv3_u16 start, length;
	sv3_u32 checksum;
	int error;

	if (!out || !payload)
		return -EINVAL;
	*out = (struct sv3_decoded){ 0 };
	*payload = NULL;
	error = sv3_validate(bytes, bytes_total);
	if (error)
		return error;
	sv3_get_header(bytes, &header);
	if (index >= header.record_count)
		return -ERANGE;
	sv3_get_record(bytes, index, &record);
	start = sv3_le16(record.payload_offset_le);
	length = sv3_le16(record.payload_length_le);
	checksum = sv3_le32(record.payload_crc32c_le);
	if (sv3_crc32c_bytes((const sv3_u8 *)bytes + start, length) != checksum)
		return -EBADMSG;
	out->logical_page = sv3_le32(record.logical_page_le);
	out->generation = sv3_le32(record.generation_le);
	out->payload_offset = start;
	out->payload_length = length;
	out->payload_crc32c = checksum;
	*payload = (const sv3_u8 *)bytes + start;
	return 0;
}

int sv3_record_read_blocks(const struct sv3_decoded *record)
{
	sv3_u32 first, last;

	if (!record || !record->payload_length ||
	    record->payload_length > SV3_MAX_COMPRESSED ||
	    record->payload_offset >= SV3_MAX_EXTENT_BYTES ||
	    record->payload_length > SV3_MAX_EXTENT_BYTES -
				     record->payload_offset)
		return -EINVAL;
	first = record->payload_offset / SV3_BLOCK_BYTES;
	last = ((sv3_u32)record->payload_offset +
		record->payload_length - 1U) / SV3_BLOCK_BYTES;
	/* Uncached metadata always costs physical 4KiB block zero. */
	return (int)(last - first + 1U + (first ? 1U : 0U));
}
