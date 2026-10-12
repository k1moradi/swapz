// SPDX-License-Identifier: GPL-2.0-only
#include "engine.h"

#ifdef __KERNEL__
#include <linux/errno.h>
#include <linux/string.h>
#else
#include <errno.h>
#include <string.h>
#endif

static int sv3_page_valid(const struct sv3_compressed_page *page)
{
	return page && page->payload && page->length > 0 &&
		page->length <= SV3_MAX_COMPRESSED;
}

/* How many *ordered* records fit the size class, without duplicate slots. */
static sv3_u8 sv3_fit_count(const struct sv3_compressed_page *pages,
			   sv3_u8 count, sv3_u8 start, sv3_u8 blocks,
			   sv3_u32 *read_blocks)
{
	sv3_u32 payload_start = (sv3_u32)blocks * SV3_BLOCK_BYTES;
	sv3_u8 included = 0;
	sv3_u8 index;

	*read_blocks = 0;
	for (index = start; index < count; ++index) {
		sv3_u8 earlier;
		sv3_u32 offset;
		sv3_u32 first, last;
		const struct sv3_compressed_page *page = &pages[index];

		if (included == SV3_MAX_RECORDS)
			break;
		for (earlier = start; earlier < index; ++earlier) {
			if (page->logical_page == pages[earlier].logical_page)
				return included;
		}
		if (payload_start < page->length)
			break;
		offset = payload_start - page->length;
		if (offset < sizeof(struct sv3_header) +
			     ((sv3_u32)included + 1U) *
			     sizeof(struct sv3_record))
			break;
		first = offset / SV3_BLOCK_BYTES;
		last = (payload_start - 1U) / SV3_BLOCK_BYTES;
		*read_blocks += last - first + 1U + (first ? 1U : 0U);
		payload_start = offset;
		included++;
	}
	return included;
}

int sv3_engine_plan(const struct sv3_compressed_page *pages, sv3_u8 count,
		    sv3_u8 *classes, sv3_u8 *records_per_extent,
		    sv3_u8 *extent_count)
{
	sv3_u32 costs[SV3_MAX_RECORDS + 1U];
	sv3_u32 reads[SV3_MAX_RECORDS + 1U];
	sv3_u8 batches[SV3_MAX_RECORDS + 1U];
	sv3_u8 selected_class[SV3_MAX_RECORDS];
	sv3_u8 selected_count[SV3_MAX_RECORDS];
	int index;
	sv3_u8 out = 0;
	sv3_u8 position = 0;

	if (!pages || !classes || !records_per_extent || !extent_count ||
	    !count || count > SV3_MAX_RECORDS)
		return -EINVAL;
	*extent_count = 0;
	for (index = 0; index < count; ++index) {
		if (!sv3_page_valid(&pages[index]))
			return -EOPNOTSUPP; /* raw fallback belongs to later I/O path */
	}
	costs[count] = 0;
	reads[count] = 0;
	batches[count] = 0;
	for (index = (int)count - 1; index >= 0; --index) {
		sv3_u8 class_index;

		costs[index] = ~(sv3_u32)0;
		reads[index] = ~(sv3_u32)0;
		batches[index] = SV3_MAX_RECORDS;
		selected_count[index] = 0;
		for (class_index = 0; class_index < 3; ++class_index) {
			sv3_u8 blocks = (sv3_u8)(1U << class_index);
			sv3_u32 local_read_blocks;
			sv3_u8 take = sv3_fit_count(pages, count, index, blocks,
						   &local_read_blocks);
			sv3_u32 candidate_bytes, candidate_reads;
			sv3_u8 candidate_batches;

			if (!take)
				continue;
			candidate_bytes = (sv3_u32)blocks * SV3_BLOCK_BYTES +
				costs[index + take];
			candidate_reads = local_read_blocks + reads[index + take];
			candidate_batches = batches[index + take] + 1U;
			if (candidate_bytes < costs[index] ||
			    (candidate_bytes == costs[index] &&
			     candidate_reads < reads[index]) ||
			    (candidate_bytes == costs[index] &&
			     candidate_reads == reads[index] &&
			     candidate_batches < batches[index])) {
				costs[index] = candidate_bytes;
				reads[index] = candidate_reads;
				batches[index] = candidate_batches;
				selected_class[index] = blocks;
				selected_count[index] = take;
			}
		}
		if (!selected_count[index])
			return -E2BIG;
	}
	while (position < count) {
		classes[out] = selected_class[position];
		records_per_extent[out] = selected_count[position];
		position += selected_count[position];
		out++;
	}
	*extent_count = out;
	return 0;
}

int sv3_engine_write_window(struct sv3_engine *engine,
			    const struct sv3_compressed_page *pages,
			    sv3_u8 count, sv3_u8 *committed_pages)
{
	struct sv3_tx *tx;
	sv3_u8 extent_count, entry = 0, group;
	int error;

	if (!engine || !engine->authority || !engine->write_scratch ||
	    !engine->io.write_extent || !committed_pages)
		return -EINVAL;
	*committed_pages = 0;
	error = sv3_engine_plan(pages, count, engine->plan_classes,
				engine->plan_takes, &extent_count);
	if (error)
		return error;

	for (group = 0; group < extent_count; ++group) {
		struct sv3_builder builder;
		sv3_u8 completed = 0;
		sv3_u8 j;
		const sv3_u8 blocks = engine->plan_classes[group];
		const sv3_u8 take = engine->plan_takes[group];
		const sv3_u32 bytes = (sv3_u32)blocks * SV3_BLOCK_BYTES;

		tx = &engine->pending;
		for (j = 0; j < take; ++j)
			engine->logical_scratch[j] = pages[entry + j].logical_page;
		error = sv3_stage(engine->authority, engine->logical_scratch,
				  take, blocks, tx);
		if (error)
			return error;
		error = sv3_begin(&builder, engine->write_scratch,
				  bytes, tx->sequence);
		if (error)
			goto abort_transaction;
		for (j = 0; j < take; ++j) {
			const struct sv3_compressed_page *page = &pages[entry + j];

			error = sv3_append(&builder, page->logical_page,
					   tx->records[j].generation,
					   page->payload, page->length);
			if (error)
				goto abort_transaction;
		}
		error = sv3_seal(&builder);
		if (error)
			goto abort_transaction;

		/*
		 * Synchronous and completion-confirmed lower I/O. The on-media
		 * region may be torn if the lower callback fails; never publish
		 * mappings unless ALL blocks completed.
		 */
		engine->submitted_blocks += blocks;
		error = engine->io.write_extent(engine->io.opaque,
						tx->start_block, blocks,
						engine->write_scratch, &completed);
		if (completed > blocks) {
			completed = blocks;
			error = -EUCLEAN;
		}
		engine->completed_blocks += completed;
		error = sv3_finish(engine->authority, tx,
				   engine->write_scratch, bytes,
				   completed, error);
		if (error)
			return error;
		entry += take;
		*committed_pages = entry;
		continue;
abort_transaction:
		sv3_abort(engine->authority, tx);
		return error;
	}
	return 0;
}

int sv3_engine_read_page(struct sv3_engine *engine, sv3_u32 logical_page,
			 sv3_u8 *payload, sv3_u16 payload_capacity,
			 sv3_u16 *payload_length)
{
	struct sv3_decoded peek, decoded;
	struct sv3_map observed;
	const sv3_u8 *stored;
	sv3_u32 bytes, first, last, start, count;
	int error;

	if (!engine || !engine->authority || !engine->read_scratch ||
	    !engine->io.read_blocks || !payload || !payload_length ||
	    logical_page >= engine->authority->logical_pages)
		return -EINVAL;
	*payload_length = 0;
	observed = engine->authority->maps[logical_page];
	if (!observed.valid || !observed.extent_blocks ||
	    observed.extent_blocks > SV3_MAX_BLOCKS ||
	    observed.start_block >= engine->authority->physical_blocks ||
	    observed.extent_blocks >
			engine->authority->physical_blocks - observed.start_block)
		return -ESTALE;
	bytes = (sv3_u32)observed.extent_blocks * SV3_BLOCK_BYTES;
	memset(engine->read_scratch, 0, bytes);
	error = engine->io.read_blocks(engine->io.opaque,
				       observed.start_block, 1,
				       engine->read_scratch);
	if (error)
		return error;
	engine->physical_read_blocks++;
	error = sv3_peek(engine->read_scratch, bytes,
			 observed.record_index, &peek);
	if (error)
		return error;
	if (peek.logical_page != logical_page ||
	    peek.generation != observed.generation)
		return -EUCLEAN;
	first = peek.payload_offset / SV3_BLOCK_BYTES;
	last = ((sv3_u32)peek.payload_offset +
		peek.payload_length - 1U) / SV3_BLOCK_BYTES;
	/* Block zero is already in memory from metadata validation. */
	start = first ? first : 1U;
	if (last >= start) {
		count = last - start + 1U;
		if (start + count > observed.extent_blocks)
			return -EUCLEAN;
		error = engine->io.read_blocks(engine->io.opaque,
			observed.start_block + start, count,
			engine->read_scratch + start * SV3_BLOCK_BYTES);
		if (error)
			return error;
		engine->physical_read_blocks += count;
	}
	error = sv3_read_authoritative(engine->authority, logical_page,
				       &observed, engine->read_scratch,
				       bytes, &decoded, &stored);
	if (error)
		return error;
	if (decoded.payload_length > payload_capacity)
		return -ENOSPC;
	memcpy(payload, stored, decoded.payload_length);
	*payload_length = decoded.payload_length;
	return 0;
}
