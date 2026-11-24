// SPDX-License-Identifier: GPL-2.0-only
#include "zswap-original-extent.h"

#ifdef SWAPZ_ORIGINAL_EXTENT_TEST
#ifdef __KERNEL__
#include <linux/errno.h>
#include <linux/string.h>
#else
#include <errno.h>
#include <string.h>
#endif

_Static_assert(SWAPZ_MAX_EXTENT_BYTES <= 65535U, "offset width");
_Static_assert(SWAPZ_MAX_RECORDS <= 64U, "record capacity");
_Static_assert(SWAPZ_MAX_COMPRESSED == 3568U, "ordinary limit unchanged");
_Static_assert(sizeof(struct swapz_original_extent_record) == 24U,
	       "bounded volatile record");

static int valid_span(const void *pointer, unsigned long length)
{
	return pointer && length &&
	       length - 1U <= ~0UL - (unsigned long)pointer;
}

/* No relational comparisons of unrelated C object pointers or end overflow. */
static int overlaps(const void *first, unsigned long first_length,
		    const void *second, unsigned long second_length)
{
	unsigned long a = (unsigned long)first;
	unsigned long b = (unsigned long)second;

	return a <= b ? b - a < first_length : a - b < second_length;
}

static int valid_geometry(swapz_u32 bytes, swapz_u32 capacity,
			  swapz_u32 ceiling, swapz_u8 mode)
{
	if (bytes != SWAPZ_BLOCK_BYTES && bytes != 2U * SWAPZ_BLOCK_BYTES &&
	    bytes != SWAPZ_MAX_EXTENT_BYTES)
		return 0;
	if (!capacity || capacity > SWAPZ_MAX_RECORDS)
		return 0;
	if (ceiling != SWAPZ_ORIGINAL_EXTENT_CONSERVATIVE &&
	    ceiling != SWAPZ_ORIGINAL_EXTENT_EXPERIMENTAL)
		return 0;
	if (mode == SWAPZ_ORIGINAL_EXTENT_DEDICATED)
		return bytes == SWAPZ_BLOCK_BYTES && capacity == 1U;
	return mode == SWAPZ_ORIGINAL_EXTENT_PACKED;
}

static int valid_profile(swapz_u8 representation, swapz_u8 codec,
			 swapz_u8 version)
{
	return representation == SWAPZ_ORIGINAL_EXTENT_REPRESENTATION &&
	       (codec == SWAPZ_ORIGINAL_EXTENT_LZ4 ||
		codec == SWAPZ_ORIGINAL_EXTENT_LZO1X) &&
	       version == SWAPZ_ORIGINAL_EXTENT_VERSION;
}

static int valid_storage(const struct swapz_original_extent *extent,
			 const void *image, swapz_u32 bytes,
			 const struct swapz_original_extent_record *records,
			 swapz_u32 record_bytes)
{
	return valid_span(extent, sizeof(*extent)) &&
	       valid_span(image, bytes) && valid_span(records, record_bytes) &&
	       !overlaps(extent, sizeof(*extent), image, bytes) &&
	       !overlaps(extent, sizeof(*extent), records, record_bytes) &&
	       !overlaps(image, bytes, records, record_bytes);
}

static int valid_builder(const struct swapz_original_extent *extent)
{
	if (!extent || !valid_geometry(extent->image_bytes, extent->capacity,
				       extent->ceiling, extent->mode) ||
	    extent->sealed || extent->count > extent->capacity ||
	    extent->occupied_bytes > extent->image_bytes ||
	    extent->unused_bytes != extent->image_bytes - extent->occupied_bytes ||
	    (!extent->count && extent->occupied_bytes) ||
	    (extent->count && !extent->occupied_bytes))
		return 0;
	return valid_storage(extent, extent->image, extent->image_bytes,
			     extent->records,
			     extent->capacity * sizeof(*extent->records));
}

static int outside_storage(const struct swapz_original_extent *extent,
			   const void *pointer, swapz_u32 bytes)
{
	return valid_span(pointer, bytes) &&
	       !overlaps(pointer, bytes, extent, sizeof(*extent)) &&
	       !overlaps(pointer, bytes, extent->image, extent->image_bytes) &&
	       !overlaps(pointer, bytes, extent->records,
			 extent->capacity * sizeof(*extent->records));
}

int swapz_original_extent_begin(struct swapz_original_extent *extent,
	void *image, swapz_u32 image_bytes,
	struct swapz_original_extent_record *records, swapz_u32 record_bytes,
	swapz_u32 capacity, swapz_u32 ceiling, swapz_u8 mode)
{
	if (!valid_geometry(image_bytes, capacity, ceiling, mode) ||
	    record_bytes != capacity * sizeof(*records) ||
	    !valid_storage(extent, image, image_bytes, records, record_bytes))
		return -EINVAL;

	*extent = (struct swapz_original_extent) {
		.image = image,
		.records = records,
		.image_bytes = image_bytes,
		.unused_bytes = image_bytes,
		.ceiling = ceiling,
		.capacity = capacity,
		.mode = mode,
	};
	return 0;
}

/* The public plan output is disjoint from input, bytes and all builder
 * storage. append uses a private stack result and the same checked plan. */
int swapz_original_extent_plan(const struct swapz_original_extent *extent,
	const struct swapz_original_extent_input *input,
	struct swapz_original_extent_record *result)
{
	swapz_u32 offset, first, last, index, crc;

	if (!valid_builder(extent) ||
	    !outside_storage(extent, input, sizeof(*input)) ||
	    !outside_storage(extent, result, sizeof(*result)) ||
	    overlaps(result, sizeof(*result), input, sizeof(*input)))
		return -EINVAL;
	if (!valid_profile(input->representation, input->codec, input->version) ||
	    input->dictionary_id || input->decoded_length != SWAPZ_BLOCK_BYTES ||
	    !input->generation)
		return -EINVAL;
	if (!input->length || input->length >= SWAPZ_BLOCK_BYTES ||
	    input->length > extent->ceiling ||
	    input->bytes_available != input->length)
		return -EMSGSIZE;
	if (!outside_storage(extent, input->bytes, input->length) ||
	    overlaps(input->bytes, input->length, input, sizeof(*input)) ||
	    overlaps(input->bytes, input->length, result, sizeof(*result)))
		return -EINVAL;
	if (extent->count >= extent->capacity ||
	    input->length > extent->unused_bytes)
		return -ENOSPC;
	for (index = 0; index < extent->count; ++index)
		if (extent->records[index].logical_page == input->logical_page)
			return -EEXIST;
	crc = swapz_crc32c_bytes(input->bytes, input->length);
	if (crc != input->crc32c)
		return -EBADMSG;

	offset = extent->mode == SWAPZ_ORIGINAL_EXTENT_DEDICATED ? 0U :
		 extent->unused_bytes - input->length;
	first = offset >> SWAPZ_BLOCK_SHIFT;
	last = (offset + input->length - 1U) >> SWAPZ_BLOCK_SHIFT;
	*result = (struct swapz_original_extent_record) {
		.logical_page = input->logical_page,
		.generation = input->generation,
		.crc32c = crc,
		.offset = (swapz_u16)offset,
		.length = (swapz_u16)input->length,
		.representation = input->representation,
		.codec = input->codec,
		.version = input->version,
		.first_block = (swapz_u8)first,
		.read_blocks = (swapz_u8)(last - first + 1U),
	};
	return 0;
}

int swapz_original_extent_append(struct swapz_original_extent *extent,
	const struct swapz_original_extent_input *input)
{
	struct swapz_original_extent_record planned;
	int error = swapz_original_extent_plan(extent, input, &planned);

	if (error)
		return error;
	memcpy(extent->image + planned.offset, input->bytes, planned.length);
	extent->records[extent->count++] = planned;
	extent->occupied_bytes += planned.length;
	extent->unused_bytes -= planned.length;
	return 0;
}

int swapz_original_extent_seal(struct swapz_original_extent *extent)
{
	swapz_u32 index, earlier, remaining;

	if (!valid_builder(extent) || !extent->count)
		return -EINVAL;
	remaining = extent->image_bytes;
	/* Validate the complete descriptor chain and CRC before touching padding.
	 * A damaged cursor/descriptor must not erase live data. */
	for (index = 0; index < extent->count; ++index) {
		const struct swapz_original_extent_record *record =
			&extent->records[index];
		swapz_u32 offset, first, last;

		if (!record->generation || !record->length ||
		    record->length > extent->ceiling ||
		    record->length >= SWAPZ_BLOCK_BYTES ||
		    record->length > remaining ||
		    !valid_profile(record->representation, record->codec,
				   record->version) ||
		    record->reserved[0] || record->reserved[1] ||
		    record->reserved[2])
			return -EUCLEAN;
		remaining -= record->length;
		offset = extent->mode == SWAPZ_ORIGINAL_EXTENT_DEDICATED ?
			 0U : remaining;
		first = offset >> SWAPZ_BLOCK_SHIFT;
		last = (offset + record->length - 1U) >> SWAPZ_BLOCK_SHIFT;
		if (record->offset != offset || record->first_block != first ||
		    record->read_blocks != last - first + 1U)
			return -EUCLEAN;
		for (earlier = 0; earlier < index; ++earlier)
			if (extent->records[earlier].logical_page ==
			    record->logical_page)
				return -EUCLEAN;
		if (swapz_crc32c_bytes(extent->image + offset, record->length) !=
		    record->crc32c)
			return -EBADMSG;
	}
	if (remaining != extent->unused_bytes)
		return -EUCLEAN;
	if (extent->mode == SWAPZ_ORIGINAL_EXTENT_DEDICATED)
		memset(extent->image + extent->occupied_bytes, 0, remaining);
	else
		memset(extent->image, 0, remaining);
	extent->sealed = 1;
	return 0;
}
#endif
