// SPDX-License-Identifier: GPL-2.0-only
#include "engine.h"

#ifdef __KERNEL__
#include <linux/errno.h>
#include <linux/ktime.h>
#include <linux/string.h>
#else
#include <errno.h>
#include <string.h>
#endif

static unsigned long long swapz_engine_now_ns(void)
{
#ifdef __KERNEL__
	return ktime_get_ns();
#else
	return 0;
#endif
}

static unsigned long long swapz_engine_elapsed_ns(unsigned long long start,
						  unsigned long long end)
{
	return end >= start ? end - start : 0;
}

static int swapz_append_page(struct swapz_engine *engine,
			    struct swapz_builder *builder,
			    const struct swapz_compressed_page *page,
			    swapz_u32 generation)
{
	int error;

	if (!page->payload_crc32c_valid)
		return swapz_append(builder, page->logical_page, generation,
				    page->payload, page->length);
	error = swapz_append_prehashed(builder, page->logical_page, generation,
				      page->payload, page->length,
				      page->payload_crc32c);
	if (!error)
		engine->prehashed_records++;
	return error;
}

static int swapz_page_valid(const struct swapz_compressed_page *page)
{
	return page && !page->raw && page->payload && page->length > 0 &&
		page->length <= SWAPZ_MAX_COMPRESSED;
}

/*
 * Check a complete logical page only after the caller's cheap LZ4 size
 * admission (<64B). A merely compressible/patterned page is NOT zero;
 * missing even a single nonzero byte would corrupt authoritative data.
 * Fixed-width memcpy keeps unaligned callers and the shared userspace build
 * defined while reducing the scan loop from 4096 byte tests to 512 words.
 */
int swapz_page_is_zero(const swapz_u8 *page)
{
	unsigned long long word;
	swapz_u32 offset;

	if (!page)
		return 0;
	for (offset = 0; offset < SWAPZ_BLOCK_BYTES; offset += sizeof(word)) {
		memcpy(&word, page + offset, sizeof(word));
		if (word)
			return 0;
	}
	return 1;
}

/* How many *ordered* records fit the size class, without duplicate slots. */
static swapz_u8 swapz_fit_count(const struct swapz_compressed_page *pages,
			   swapz_u8 count, swapz_u8 start, swapz_u8 blocks,
			   swapz_u8 max_read_blocks, swapz_u32 *read_blocks)
{
	swapz_u32 payload_start = (swapz_u32)blocks * SWAPZ_BLOCK_BYTES;
	swapz_u8 included = 0;
	swapz_u8 index;

	*read_blocks = 0;
	for (index = start; index < count; ++index) {
		swapz_u8 earlier;
		swapz_u32 offset;
		swapz_u32 first, last, record_reads;
		const struct swapz_compressed_page *page = &pages[index];

		if (included == SWAPZ_MAX_RECORDS)
			break;
		for (earlier = start; earlier < index; ++earlier) {
			if (page->logical_page == pages[earlier].logical_page)
				return included;
		}
		if (payload_start < page->length)
			break;
		offset = payload_start - page->length;
		if (offset < sizeof(struct swapz_header) +
			     ((swapz_u32)included + 1U) *
			     sizeof(struct swapz_record))
			break;
		first = offset / SWAPZ_BLOCK_BYTES;
		last = (payload_start - 1U) / SWAPZ_BLOCK_BYTES;
		record_reads = last - first + 1U + (first ? 1U : 0U);
		/*
		 * Full logical record must fit both geometry and read budget.
		 * Because we preserve arrival order, we cannot skip this record
		 * and pick a later one without making an explicit new extent.
		 */
		if (max_read_blocks && record_reads > max_read_blocks)
			break;
		*read_blocks += record_reads;
		payload_start = offset;
		included++;
	}
	return included;
}

static int swapz_engine_plan_bounded_policy(
			    const struct swapz_compressed_page *pages,
			    swapz_u8 count, swapz_u8 max_read_blocks,
			    swapz_u8 *classes, swapz_u8 *records_per_extent,
			    swapz_u8 *extent_count, int prefer_large_ties,
			    swapz_u32 alignment_cursor)
{
	swapz_u32 costs[SWAPZ_MAX_RECORDS + 1U];
	swapz_u32 reads[SWAPZ_MAX_RECORDS + 1U];
	swapz_u8 batches[SWAPZ_MAX_RECORDS + 1U];
	swapz_u8 selected_class[SWAPZ_MAX_RECORDS];
	swapz_u8 selected_count[SWAPZ_MAX_RECORDS];
	int index;
	swapz_u8 out = 0;
	swapz_u8 position = 0;

	if (!pages || !classes || !records_per_extent || !extent_count ||
	    !count || count > SWAPZ_MAX_RECORDS || max_read_blocks > 3U)
		return -EINVAL;
	*extent_count = 0;
	for (index = 0; index < count; ++index) {
		if (!swapz_page_valid(&pages[index]))
			return -EOPNOTSUPP; /* raw fallback belongs to later I/O path */
	}
	costs[count] = 0;
	reads[count] = 0;
	batches[count] = 0;
	for (index = (int)count - 1; index >= 0; --index) {
		swapz_u8 class_index;

		costs[index] = ~(swapz_u32)0;
		reads[index] = ~(swapz_u32)0;
		batches[index] = SWAPZ_MAX_RECORDS;
		selected_count[index] = 0;
		for (class_index = 0; class_index < 3; ++class_index) {
			swapz_u8 blocks = (swapz_u8)(1U << class_index);
			swapz_u32 local_read_blocks;
			swapz_u8 take = swapz_fit_count(pages, count, index, blocks,
						   max_read_blocks,
						   &local_read_blocks);
			swapz_u32 candidate_bytes, candidate_reads;
			swapz_u8 candidate_batches;

			if (!take)
				continue;
			candidate_bytes = (swapz_u32)blocks * SWAPZ_BLOCK_BYTES +
				costs[index + take];
			candidate_reads = local_read_blocks + reads[index + take];
			candidate_batches = batches[index + take] + 1U;
			if (candidate_bytes < costs[index] ||
			    (candidate_bytes == costs[index] &&
			     candidate_reads < reads[index]) ||
			    (candidate_bytes == costs[index] &&
			     candidate_reads == reads[index] &&
			     candidate_batches < batches[index]) ||
			    /*
			     * When bytes, cold-read cost and extent count are
			     * identical, prefer the larger existing extent class.
			     * Packed placement has no intra-segment alignment gap;
			     * reconstruction below only needs to avoid crossing a
			     * real segment edge.
			     */
			    (prefer_large_ties &&
			     candidate_bytes == costs[index] &&
			     candidate_reads == reads[index] &&
			     candidate_batches == batches[index] &&
			     blocks > selected_class[index])) {
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
		swapz_u8 chosen_class = selected_class[position];
		swapz_u8 chosen_count = selected_count[position];

		/*
		 * Primary DP objectives are already fixed. The adjacent writer may
		 * reconstruct only among exactly equivalent candidates using the
		 * live allocator cursor, so logical/staging/publication order stays
		 * unchanged and a later failure still describes a true prefix.
		 */
		if (prefer_large_ties) {
			swapz_u32 best_hole = ~(swapz_u32)0;
			swapz_u8 class_index;

			chosen_class = 0;
			chosen_count = 0;
			for (class_index = 0; class_index < 3; ++class_index) {
				swapz_u8 blocks = (swapz_u8)(1U << class_index);
				swapz_u32 local_read_blocks;
				swapz_u8 take = swapz_fit_count(pages, count, position,
							   blocks, max_read_blocks,
							   &local_read_blocks);
				swapz_u32 candidate_bytes, candidate_reads;
				swapz_u8 candidate_batches;
				swapz_u32 hole;

				if (!take)
					continue;
				candidate_bytes =
					(swapz_u32)blocks * SWAPZ_BLOCK_BYTES +
					costs[position + take];
				candidate_reads =
					local_read_blocks + reads[position + take];
				candidate_batches = batches[position + take] + 1U;
				if (candidate_bytes != costs[position] ||
				    candidate_reads != reads[position] ||
				    candidate_batches != batches[position])
					continue;
				{
					swapz_u32 offset =
						alignment_cursor % SWAPZ_SEGMENT_BLOCKS;

					hole = offset + blocks > SWAPZ_SEGMENT_BLOCKS ?
						SWAPZ_SEGMENT_BLOCKS - offset : 0;
				}
				if (hole < best_hole ||
				    (hole == best_hole && blocks > chosen_class)) {
					best_hole = hole;
					chosen_class = blocks;
					chosen_count = take;
				}
			}
			if (!chosen_count)
				return -EUCLEAN;
		}
		classes[out] = chosen_class;
		records_per_extent[out] = chosen_count;
		{
			swapz_u32 offset =
				alignment_cursor % SWAPZ_SEGMENT_BLOCKS;

			if (offset + chosen_class > SWAPZ_SEGMENT_BLOCKS)
				alignment_cursor += SWAPZ_SEGMENT_BLOCKS - offset;
			alignment_cursor += chosen_class;
		}
		position += chosen_count;
		out++;
	}
	*extent_count = out;
	return 0;
}

int swapz_engine_plan_bounded(const struct swapz_compressed_page *pages,
			    swapz_u8 count, swapz_u8 max_read_blocks,
			    swapz_u8 *classes, swapz_u8 *records_per_extent,
			    swapz_u8 *extent_count)
{
	return swapz_engine_plan_bounded_policy(pages, count, max_read_blocks,
					      classes, records_per_extent,
					      extent_count, 0, 0);
}

static swapz_u16 swapz_read_metadata_front_bucket(swapz_u32 start_block,
						 swapz_u8 extent_blocks)
{
	swapz_u32 mixed = start_block ^ (start_block >> 9) ^
		((swapz_u32)extent_blocks * 0x9e3779b9U);

	return (swapz_u16)(mixed & (SWAPZ_READ_METADATA_FRONT_ENTRIES - 1U));
}

static int swapz_read_metadata_lru_lookup(const struct swapz_engine *engine,
					swapz_u32 start_block,
					swapz_u8 extent_blocks)
{
	swapz_u16 bucket, encoded, index, slot;

	if (!engine->read_metadata_cache)
		return -1;
	bucket = swapz_read_metadata_front_bucket(start_block, extent_blocks);
	encoded = engine->read_metadata_front_slots[bucket];
	if (encoded) {
		slot = encoded - 1U;
		if (slot < SWAPZ_READ_METADATA_CACHE_ENTRIES &&
		    engine->read_metadata_lru_valid[slot] &&
		    engine->read_metadata_lru_start_blocks[slot] == start_block &&
		    engine->read_metadata_lru_extent_blocks[slot] == extent_blocks)
			return slot;
	}
	for (index = 0; index < SWAPZ_READ_METADATA_CACHE_ENTRIES; ++index)
		if (engine->read_metadata_lru_valid[index] &&
		    engine->read_metadata_lru_start_blocks[index] == start_block &&
		    engine->read_metadata_lru_extent_blocks[index] == extent_blocks)
			return index;
	return -1;
}

static void swapz_read_metadata_lru_commit(struct swapz_engine *engine,
					swapz_u32 start_block,
					swapz_u8 extent_blocks,
					int hit_slot,
					const swapz_u8 *metadata)
{
	swapz_u32 oldest_age = ~(swapz_u32)0;
	swapz_u16 index, slot = 0;
	int have_slot = 0;

	if (!engine->read_metadata_cache || !metadata)
		return;
	engine->read_metadata_lru_clock++;
	if (!engine->read_metadata_lru_clock) {
		/* Preserve exact age ordering across wrap by starting a fresh epoch.
		 * Current validated metadata is inserted below. */
		memset(engine->read_metadata_lru_valid, 0,
		       sizeof(engine->read_metadata_lru_valid));
		memset(engine->read_metadata_front_slots, 0,
		       sizeof(engine->read_metadata_front_slots));
		engine->read_metadata_lru_clock = 1;
		hit_slot = -1;
	}
	if (hit_slot >= 0) {
		slot = (swapz_u16)hit_slot;
		have_slot = 1;
	} else {
		for (index = 0; index < SWAPZ_READ_METADATA_CACHE_ENTRIES; ++index) {
			if (!engine->read_metadata_lru_valid[index]) {
				slot = index;
				have_slot = 1;
				break;
			}
			if (engine->read_metadata_lru_ages[index] < oldest_age) {
				oldest_age = engine->read_metadata_lru_ages[index];
				slot = index;
				have_slot = 1;
			}
		}
	}
	if (!have_slot)
		return;
	if (hit_slot < 0)
		memcpy(engine->read_metadata_cache +
		       (size_t)slot * SWAPZ_BLOCK_BYTES,
		       metadata, SWAPZ_BLOCK_BYTES);
	engine->read_metadata_lru_start_blocks[slot] = start_block;
	engine->read_metadata_lru_extent_blocks[slot] = extent_blocks;
	engine->read_metadata_lru_ages[slot] = engine->read_metadata_lru_clock;
	engine->read_metadata_lru_valid[slot] = 1;
	engine->read_metadata_front_slots[
		swapz_read_metadata_front_bucket(start_block, extent_blocks)] =
		slot + 1U;
}

static int swapz_read_extent_lru_lookup(const struct swapz_engine *engine,
				      swapz_u32 start_block,
				      swapz_u8 extent_blocks)
{
	swapz_u8 index;

	if (!engine->read_extent_cache)
		return -1;
	for (index = 0; index < SWAPZ_READ_EXTENT_CACHE_ENTRIES; ++index)
		if (engine->read_extent_lru_valid[index] &&
		    engine->read_extent_lru_start_blocks[index] == start_block &&
		    engine->read_extent_lru_extent_blocks[index] == extent_blocks)
			return index;
	return -1;
}

static void swapz_read_extent_lru_commit(struct swapz_engine *engine,
					 swapz_u32 start_block,
					 swapz_u8 extent_blocks,
					 swapz_u8 block_mask,
					 const swapz_u8 *bytes)
{
	swapz_u32 oldest_age = ~(swapz_u32)0;
	swapz_u8 index, slot = 0, block;
	int hit_slot, have_slot = 0;

	if (!engine->read_extent_cache || !bytes || !block_mask ||
	    !extent_blocks || extent_blocks > SWAPZ_MAX_BLOCKS)
		return;
	hit_slot = swapz_read_extent_lru_lookup(engine, start_block,
						   extent_blocks);
	engine->read_extent_lru_clock++;
	if (!engine->read_extent_lru_clock) {
		memset(engine->read_extent_lru_valid, 0,
		       sizeof(engine->read_extent_lru_valid));
		engine->read_extent_lru_clock = 1;
		hit_slot = -1;
	}
	if (hit_slot >= 0) {
		slot = (swapz_u8)hit_slot;
		have_slot = 1;
	} else {
		for (index = 0; index < SWAPZ_READ_EXTENT_CACHE_ENTRIES; ++index) {
			if (!engine->read_extent_lru_valid[index]) {
				slot = index;
				have_slot = 1;
				break;
			}
			if (engine->read_extent_lru_ages[index] < oldest_age) {
				oldest_age = engine->read_extent_lru_ages[index];
				slot = index;
				have_slot = 1;
			}
		}
	}
	if (!have_slot)
		return;
	if (hit_slot < 0)
		engine->read_extent_lru_block_masks[slot] = 0;
	for (block = 0; block < extent_blocks; ++block)
		if (block_mask & (1U << block))
			memcpy(engine->read_extent_cache +
			       (size_t)slot * SWAPZ_MAX_EXTENT_BYTES +
			       (size_t)block * SWAPZ_BLOCK_BYTES,
			       bytes + (size_t)block * SWAPZ_BLOCK_BYTES,
			       SWAPZ_BLOCK_BYTES);
	engine->read_extent_lru_start_blocks[slot] = start_block;
	engine->read_extent_lru_extent_blocks[slot] = extent_blocks;
	engine->read_extent_lru_block_masks[slot] |= block_mask;
	engine->read_extent_lru_ages[slot] = engine->read_extent_lru_clock;
	engine->read_extent_lru_valid[slot] = 1;
}

void swapz_engine_invalidate_read_cache(struct swapz_engine *engine)
{
	if (engine) {
		engine->read_cache_valid = 0;
		engine->read_cached_full = 0;
		engine->read_cached_block_mask = 0;
		engine->read_coalesced_block_mask = 0;
		/*
		 * clock==0 is the canonical empty-LRU state. Writes commonly hit
		 * this fence more than once (process-level mutation plus physical
		 * lower WRITE), so do not rescan/clear 512 validity bytes when the
		 * previous invalidation already made every slot unreachable.
		 */
		if (engine->read_metadata_lru_clock) {
			memset(engine->read_metadata_lru_valid, 0,
			       sizeof(engine->read_metadata_lru_valid));
			memset(engine->read_metadata_front_slots, 0,
			       sizeof(engine->read_metadata_front_slots));
			engine->read_metadata_lru_clock = 0;
		}
		if (engine->read_extent_lru_clock) {
			memset(engine->read_extent_lru_valid, 0,
			       sizeof(engine->read_extent_lru_valid));
			engine->read_extent_lru_clock = 0;
		}
	}
}

void swapz_engine_merge_read_telemetry(struct swapz_engine *destination,
				       struct swapz_engine *source)
{
	if (!destination || !source || destination == source)
		return;
#define SWAPZ_MERGE_READ_COUNTER(field) do { \
		destination->field += source->field; \
		source->field = 0; \
	} while (0)
	SWAPZ_MERGE_READ_COUNTER(physical_read_blocks);
	SWAPZ_MERGE_READ_COUNTER(read_metadata_requests);
	SWAPZ_MERGE_READ_COUNTER(read_payload_requests);
	SWAPZ_MERGE_READ_COUNTER(read_payload_blocks);
	SWAPZ_MERGE_READ_COUNTER(read_metadata_cache_hits);
	SWAPZ_MERGE_READ_COUNTER(read_metadata_lru_hits);
	SWAPZ_MERGE_READ_COUNTER(read_full_extent_requests);
	SWAPZ_MERGE_READ_COUNTER(read_full_extent_cache_hits);
	SWAPZ_MERGE_READ_COUNTER(read_two_block_skips);
#undef SWAPZ_MERGE_READ_COUNTER
}

void swapz_engine_prime_read_slot(const struct swapz_engine *master,
				  struct swapz_engine *slot,
				  swapz_u32 start_block,
				  swapz_u8 extent_blocks)
{
	swapz_u8 mask = 0, block;
	int cache_slot, metadata_slot;

	if (!master || !slot || !slot->read_scratch || !extent_blocks ||
	    extent_blocks > SWAPZ_MAX_BLOCKS)
		return;
	slot->read_cache_valid = 0;
	slot->read_cached_full = 0;
	slot->read_cached_block_mask = 0;
	slot->read_coalesced_block_mask = 0;
	if (!master->read_cache_valid && !master->read_extent_lru_clock &&
	    !master->read_metadata_lru_clock)
		return;
	if (master->read_cache_valid &&
	    master->read_cached_start_block == start_block &&
	    master->read_cached_extent_blocks == extent_blocks) {
		swapz_u8 current_mask = master->read_cached_block_mask;

		mask |= current_mask;
		for (block = 0; block < extent_blocks; ++block)
			if (current_mask & (1U << block))
				memcpy(slot->read_scratch +
				       (size_t)block * SWAPZ_BLOCK_BYTES,
				       master->read_scratch +
				       (size_t)block * SWAPZ_BLOCK_BYTES,
				       SWAPZ_BLOCK_BYTES);
	}
	cache_slot = master->read_extent_lru_clock ?
		swapz_read_extent_lru_lookup(master, start_block, extent_blocks) : -1;
	if (cache_slot >= 0) {
		swapz_u8 extent_mask = master->read_extent_lru_block_masks[cache_slot];

		for (block = 0; block < extent_blocks; ++block)
			if (extent_mask & (1U << block))
				memcpy(slot->read_scratch +
				       (size_t)block * SWAPZ_BLOCK_BYTES,
				       master->read_extent_cache +
				       (size_t)cache_slot * SWAPZ_MAX_EXTENT_BYTES +
				       (size_t)block * SWAPZ_BLOCK_BYTES,
				       SWAPZ_BLOCK_BYTES);
		mask |= extent_mask;
	}
	if (!(mask & 1U)) {
		metadata_slot = master->read_metadata_lru_clock ?
			swapz_read_metadata_lru_lookup(master, start_block,
						       extent_blocks) : -1;
		if (metadata_slot >= 0) {
			memcpy(slot->read_scratch,
			       master->read_metadata_cache +
			       (size_t)metadata_slot * SWAPZ_BLOCK_BYTES,
			       SWAPZ_BLOCK_BYTES);
			mask |= 1U;
		}
	}
	if (!mask)
		return;
	slot->read_cached_start_block = start_block;
	slot->read_cached_extent_blocks = extent_blocks;
	slot->read_cached_block_mask = mask;
	slot->read_cached_full =
		mask == (swapz_u8)((1U << extent_blocks) - 1U);
	slot->read_cache_valid = 1;
}

void swapz_engine_absorb_read_slot(struct swapz_engine *master,
				   struct swapz_engine *slot)
{
	int metadata_slot;

	if (!master || !slot || master == slot)
		return;
	swapz_engine_merge_read_telemetry(master, slot);
	/* Never publish lower-read seed bytes that were not validated through
	 * a constituent record. Successful grouped batches consume this mask. */
	if (slot->read_coalesced_block_mask ||
	    !slot->read_cache_valid || !slot->read_cached_block_mask)
		return;
	if (master->read_extent_cache &&
	    master->max_read_blocks_per_record != 1 &&
	    slot->read_cached_extent_blocks > 1)
		swapz_read_extent_lru_commit(master,
			slot->read_cached_start_block,
			slot->read_cached_extent_blocks,
			slot->read_cached_block_mask, slot->read_scratch);
	if (!(slot->read_cached_block_mask & 1U))
		return;
	metadata_slot = swapz_read_metadata_lru_lookup(
		master, slot->read_cached_start_block,
		slot->read_cached_extent_blocks);
	swapz_read_metadata_lru_commit(master,
		slot->read_cached_start_block,
		slot->read_cached_extent_blocks,
		metadata_slot, slot->read_scratch);
}

static swapz_u8 swapz_block_range_mask(swapz_u8 first, swapz_u8 blocks)
{
	return blocks ? (swapz_u8)(((1U << blocks) - 1U) << first) : 0;
}

static int swapz_engine_required_read_range_resident(
				     const struct swapz_engine *engine,
				     const swapz_u32 *logical_pages,
				     swapz_u8 count,
				     swapz_u32 start_block,
				     swapz_u8 extent_blocks,
				     swapz_u8 resident,
				     swapz_u8 *first_block,
				     swapz_u8 *blocks)
{
	swapz_u8 required = 0, missing;
	swapz_u8 first, last, index;

	if (!engine || !engine->authority || !logical_pages || !count ||
	    count > SWAPZ_MAX_RECORDS || !first_block || !blocks ||
	    !extent_blocks || extent_blocks > SWAPZ_MAX_BLOCKS ||
	    start_block >= engine->authority->physical_blocks ||
	    extent_blocks > engine->authority->physical_blocks - start_block)
		return -EINVAL;
	resident &= (swapz_u8)((1U << extent_blocks) - 1U);
	for (index = 0; index < count; ++index) {
		const struct swapz_map *map;
		swapz_u32 logical = logical_pages[index];
		swapz_u32 payload_first, payload_last, block;

		if (logical >= engine->authority->logical_pages)
			return -ERANGE;
		map = &engine->authority->maps[logical];
		if (!map->valid || map->raw ||
		    map->start_block != start_block ||
		    map->extent_blocks != extent_blocks ||
		    !map->payload_length ||
		    map->payload_offset >=
			(swapz_u32)extent_blocks * SWAPZ_BLOCK_BYTES ||
		    map->payload_length >
			(swapz_u32)extent_blocks * SWAPZ_BLOCK_BYTES -
			map->payload_offset)
			return -ESTALE;
		required |= 1U;
		payload_first = map->payload_offset / SWAPZ_BLOCK_BYTES;
		payload_last = ((swapz_u32)map->payload_offset +
				map->payload_length - 1U) / SWAPZ_BLOCK_BYTES;
		for (block = payload_first; block <= payload_last; ++block)
			required |= (swapz_u8)(1U << block);
	}
	missing = required & (swapz_u8)~resident;
	if (!missing) {
		*first_block = 0;
		*blocks = 0;
		return 0;
	}
	for (first = 0; first < extent_blocks; ++first)
		if (missing & (1U << first))
			break;
	for (last = extent_blocks; last > 0; --last)
		if (missing & (1U << (last - 1U))) {
			last--;
			break;
		}
	*first_block = first;
	*blocks = last - first + 1U;
	if (swapz_block_range_mask(*first_block, *blocks) != missing)
		return -EOPNOTSUPP;
	return 0;
}

int swapz_engine_required_read_range(const struct swapz_engine *engine,
				     const swapz_u32 *logical_pages,
				     swapz_u8 count,
				     swapz_u32 start_block,
				     swapz_u8 extent_blocks,
				     swapz_u8 *first_block,
				     swapz_u8 *blocks)
{
	swapz_u8 resident = 0;

	if (engine && engine->read_cache_valid &&
	    engine->read_cached_start_block == start_block &&
	    engine->read_cached_extent_blocks == extent_blocks)
		resident = engine->read_cached_block_mask;
	return swapz_engine_required_read_range_resident(
		engine, logical_pages, count, start_block, extent_blocks,
		resident, first_block, blocks);
}

int swapz_engine_required_read_range_cached(
				     const struct swapz_engine *engine,
				     const swapz_u32 *logical_pages,
				     swapz_u8 count,
				     swapz_u32 start_block,
				     swapz_u8 extent_blocks,
				     swapz_u8 *first_block,
				     swapz_u8 *blocks)
{
	swapz_u8 resident = 0;
	int cache_slot = -1, metadata_slot = -1;

	if (!engine)
		return -EINVAL;
	if (engine->read_cache_valid &&
	    engine->read_cached_start_block == start_block &&
	    engine->read_cached_extent_blocks == extent_blocks)
		resident |= engine->read_cached_block_mask;
	if (engine->read_extent_lru_clock)
		cache_slot = swapz_read_extent_lru_lookup(
			engine, start_block, extent_blocks);
	if (cache_slot >= 0)
		resident |= engine->read_extent_lru_block_masks[cache_slot];
	if (!(resident & 1U) && engine->read_metadata_lru_clock)
		metadata_slot = swapz_read_metadata_lru_lookup(
			engine, start_block, extent_blocks);
	if (metadata_slot >= 0)
		resident |= 1U;
	return swapz_engine_required_read_range_resident(
		engine, logical_pages, count, start_block, extent_blocks,
		resident, first_block, blocks);
}

int swapz_engine_coalesced_span(swapz_u32 start0, swapz_u8 extent0,
				swapz_u8 first0, swapz_u8 blocks0,
				swapz_u32 start1, swapz_u8 extent1,
				swapz_u8 first1, swapz_u8 blocks1,
				swapz_u32 *combined_start,
				swapz_u8 *combined_blocks)
{
	swapz_u32 phys0, phys1, low, high;
	swapz_u16 total;

	if (!combined_start || !combined_blocks || !extent0 || !extent1 ||
	    extent0 > SWAPZ_MAX_BLOCKS || extent1 > SWAPZ_MAX_BLOCKS ||
	    !blocks0 || !blocks1 ||
	    first0 >= extent0 || blocks0 > extent0 - first0 ||
	    first1 >= extent1 || blocks1 > extent1 - first1 ||
	    (start0 == start1 && extent0 == extent1) ||
	    start0 > ~(swapz_u32)0 - first0 ||
	    start1 > ~(swapz_u32)0 - first1)
		return -EINVAL;
	phys0 = start0 + first0;
	phys1 = start1 + first1;
	if (phys0 > ~(swapz_u32)0 - blocks0 ||
	    phys1 > ~(swapz_u32)0 - blocks1)
		return -EINVAL;
	total = (swapz_u16)blocks0 + blocks1;
	if (total > 2U * SWAPZ_MAX_BLOCKS)
		return -EOPNOTSUPP;
	if (phys0 + blocks0 == phys1) {
		low = phys0;
		high = phys1 + blocks1;
	} else if (phys1 + blocks1 == phys0) {
		low = phys1;
		high = phys0 + blocks0;
	} else {
		return -EOPNOTSUPP;
	}
	if (low / SWAPZ_SEGMENT_BLOCKS !=
	    (high - 1U) / SWAPZ_SEGMENT_BLOCKS)
		return -EOPNOTSUPP;
	*combined_start = low;
	*combined_blocks = (swapz_u8)total;
	return 0;
}

static int swapz_engine_seed_coalesced_range(struct swapz_engine *engine,
					     swapz_u32 start_block,
					     swapz_u8 extent_blocks,
					     swapz_u8 first_block,
					     swapz_u8 blocks,
					     const swapz_u8 *bytes)
{
	swapz_u8 block_mask;

	if (!engine || !engine->read_scratch || !bytes ||
	    !extent_blocks || extent_blocks > SWAPZ_MAX_BLOCKS ||
	    !blocks || first_block >= extent_blocks ||
	    blocks > extent_blocks - first_block)
		return -EINVAL;
	if (engine->read_cache_valid &&
	    (engine->read_cached_start_block != start_block ||
	     engine->read_cached_extent_blocks != extent_blocks))
		return -ESTALE;
	memcpy(engine->read_scratch + (size_t)first_block * SWAPZ_BLOCK_BYTES,
	       bytes, (size_t)blocks * SWAPZ_BLOCK_BYTES);
	block_mask = swapz_block_range_mask(first_block, blocks);
	engine->read_cached_start_block = start_block;
	engine->read_cached_extent_blocks = extent_blocks;
	engine->read_cached_block_mask |= block_mask;
	engine->read_coalesced_block_mask |= block_mask;
	engine->read_cached_full = engine->read_cached_block_mask ==
		(swapz_u8)((1U << extent_blocks) - 1U);
	engine->read_cache_valid = 1;
	engine->physical_read_blocks += blocks;
	return 0;
}

int swapz_engine_coalesce_read_pair(struct swapz_engine *first,
				    struct swapz_engine *second,
				    swapz_u32 start0, swapz_u8 extent0,
				    swapz_u8 first0, swapz_u8 blocks0,
				    swapz_u32 start1, swapz_u8 extent1,
				    swapz_u8 first1, swapz_u8 blocks1,
				    swapz_u8 *scratch,
				    swapz_u8 scratch_blocks)
{
	swapz_u32 combined_start, phys0, phys1;
	swapz_u8 combined_blocks;
	const swapz_u8 *bytes0, *bytes1;
	int error;

	if (!first || !second || first == second || !scratch ||
	    !first->io.read_blocks || first->authority != second->authority)
		return -EINVAL;
	error = swapz_engine_coalesced_span(start0, extent0, first0, blocks0,
					   start1, extent1, first1, blocks1,
					   &combined_start, &combined_blocks);
	if (error)
		return error;
	if (combined_blocks > scratch_blocks)
		return -ENOSPC;
	error = first->io.read_blocks(first->io.opaque, combined_start,
				      combined_blocks, scratch);
	if (error)
		return error;
	phys0 = start0 + first0;
	phys1 = start1 + first1;
	bytes0 = scratch + (size_t)(phys0 - combined_start) * SWAPZ_BLOCK_BYTES;
	bytes1 = scratch + (size_t)(phys1 - combined_start) * SWAPZ_BLOCK_BYTES;
	error = swapz_engine_seed_coalesced_range(first, start0, extent0,
						  first0, blocks0, bytes0);
	if (error)
		return error;
	return swapz_engine_seed_coalesced_range(second, start1, extent1,
						 first1, blocks1, bytes1);
}

static int swapz_engine_write_window_planned(struct swapz_engine *engine,
			    const struct swapz_compressed_page *pages,
			    swapz_u8 count, swapz_u8 *committed_pages,
			    swapz_u8 plan_read_blocks)
{
	struct swapz_tx *tx;
	swapz_u8 extent_count, entry = 0, group;
	unsigned long long phase_start;
	int error;

	if (!engine || !engine->authority || !engine->write_scratch ||
	    !engine->io.write_extent || !committed_pages)
		return -EINVAL;
	*committed_pages = 0;
	/* Even a failed/torn write must never leave reusable old metadata. */
	swapz_engine_invalidate_read_cache(engine);
	/*
	 * Never stage or submit a potentially destructive extent if the
	 * requested read-after-write guard cannot run with isolated scratch.
	 */
	if (engine->verify_after_write &&
	    (!engine->read_scratch || !engine->io.read_blocks ||
	     engine->read_scratch == engine->write_scratch))
		return -EINVAL;
	if (plan_read_blocks > 3U)
		return -EINVAL;
	phase_start = swapz_engine_now_ns();
	error = swapz_engine_plan_bounded(pages, count, plan_read_blocks,
					engine->plan_classes,
					engine->plan_takes, &extent_count);
	engine->plan_wall_ns += swapz_engine_elapsed_ns(
		phase_start, swapz_engine_now_ns());
	if (error)
		return error;

	for (group = 0; group < extent_count; ++group) {
		struct swapz_builder builder;
		swapz_u8 completed = 0;
		swapz_u8 j;
		const swapz_u8 blocks = engine->plan_classes[group];
		const swapz_u8 take = engine->plan_takes[group];
		const swapz_u32 bytes = (swapz_u32)blocks * SWAPZ_BLOCK_BYTES;

		tx = &engine->pending;
		for (j = 0; j < take; ++j)
			engine->logical_scratch[j] = pages[entry + j].logical_page;
		error = swapz_stage(engine->authority, engine->logical_scratch,
				  take, blocks, tx);
		if (error)
			return error;
		phase_start = swapz_engine_now_ns();
		error = swapz_begin(&builder, engine->write_scratch,
				  bytes, tx->sequence);
		if (error) {
			engine->pack_wall_ns += swapz_engine_elapsed_ns(
				phase_start, swapz_engine_now_ns());
			goto abort_transaction;
		}
		for (j = 0; j < take; ++j) {
			const struct swapz_compressed_page *page = &pages[entry + j];

			error = swapz_append_page(engine, &builder, page,
					       tx->records[j].generation);
			if (error) {
				engine->pack_wall_ns += swapz_engine_elapsed_ns(
					phase_start, swapz_engine_now_ns());
				goto abort_transaction;
			}
		}
		error = swapz_seal(&builder);
		engine->pack_wall_ns += swapz_engine_elapsed_ns(
			phase_start, swapz_engine_now_ns());
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
			/*
			 * A lower callback claiming impossible completion counts
			 * is not trustworthy: do not count any validated blocks.
			 * swapz_finish() quarantines the whole allocated extent.
			 */
			completed = 0;
			error = -EUCLEAN;
		}
		engine->completed_blocks += completed;
		if (engine->verify_after_write && !error &&
		    completed == blocks) {
			/*
			 * Full write completion does not guarantee the lower media
			 * actually retained the intended bytes. Optional direct
			 * readback verifies the exact COMPLETE extent, including
			 * header, descriptors, padding and sibling payloads.
			 * Failures abort/quarantine BEFORE any mapping publication.
			 */
			error = engine->io.read_blocks(
				engine->io.opaque, tx->start_block,
				blocks, engine->read_scratch);
			if (!error) {
				engine->write_verify_read_blocks += blocks;
				if (memcmp(engine->write_scratch,
					   engine->read_scratch, bytes))
					error = -EBADMSG;
			}
		}
		phase_start = swapz_engine_now_ns();
		error = swapz_finish(engine->authority, tx,
				   engine->write_scratch, bytes,
				   completed, error);
		engine->publish_wall_ns += swapz_engine_elapsed_ns(
			phase_start, swapz_engine_now_ns());
		if (error)
			return error;
		entry += take;
		*committed_pages = entry;
		continue;
abort_transaction:
		swapz_abort(engine->authority, tx);
		return error;
	}
	return 0;
}

/*
 * Bounded lower request aggregation (up to 64 adjacent physical 4KiB
 * blocks), WITHOUT changing the independent on-disk SWZ3 extents.
 *
 * Stage each extent and leave its mapping UNPUBLISHED. Consecutive
 * transaction snapshots are replayed through the original swapz_finish()
 * only after the ONE combined lower I/O has completed successfully.
 * This preserves the original committed-prefix semantics on a failed
 * group, and prevents false acknowledgement of durable media.
 */
static int swapz_bulk_abort(struct swapz_engine *e,
				  const struct swapz_io_run *run,
				  swapz_u8 first)
{
	swapz_u8 i;
	int error;

	for (i = first; i < run->extent_count; ++i) {
		error = swapz_batch_resume(e->authority, &run->txs[i]);
		if (error)
			return error;
		error = swapz_abort(e->authority, &run->txs[i]);
		if (error)
			return error;
	}
	return 0;
}

static int swapz_validate_batched_pages(struct swapz_engine *e,
					const struct swapz_compressed_page *pages,
					swapz_u8 count,
					swapz_u8 *compressed_count,
					swapz_u8 *raw_count)
{
	swapz_u8 group;

	*compressed_count = 0;
	*raw_count = 0;
	for (group = 0; group < count; ++group) {
		swapz_u8 j;

		if (pages[group].logical_page >= e->authority->logical_pages)
			return -ERANGE;
		if (e->authority->maps[pages[group].logical_page].generation ==
		    ~(swapz_u32)0)
			return -EOVERFLOW;
		if (pages[group].raw) {
			if (!pages[group].payload ||
			    pages[group].length != SWAPZ_BLOCK_BYTES)
				return -EINVAL;
			(*raw_count)++;
		} else {
			if (*raw_count || !swapz_page_valid(&pages[group]))
				return -EINVAL;
			(*compressed_count)++;
		}
		for (j = 0; j < group; ++j)
			if (pages[group].logical_page == pages[j].logical_page)
				return -EEXIST;
	}
	return 0;
}

int swapz_engine_prepare_batched_run(struct swapz_engine *e,
				   const struct swapz_compressed_page *pages,
				   swapz_u8 count, struct swapz_io_run *run,
				   swapz_u8 *prepared_pages,
				   swapz_u8 plan_read_blocks)
{
	swapz_u8 extent_count = 0, compressed_count = 0, raw_count = 0;
	swapz_u8 entry = 0, group, staged = 0;
	swapz_u32 run_start = 0;
	swapz_u16 run_blocks = 0;
	swapz_u8 *run_bytes;
	struct swapz_tx *run_txs;
	unsigned long long phase_start;
	int error;

	if (!e || !e->authority || !pages || !count ||
	    count > SWAPZ_MAX_RECORDS || !run || !run->bytes || !run->txs ||
	    !prepared_pages || plan_read_blocks > 3U)
		return -EINVAL;
	*prepared_pages = 0;
	if (!e->bulk_enabled || e->verify_after_write)
		return -EOPNOTSUPP;
	error = swapz_validate_batched_pages(e, pages, count,
					     &compressed_count, &raw_count);
	if (error)
		return error;

	run_bytes = run->bytes;
	run_txs = run->txs;
	memset(run, 0, sizeof(*run));
	run->bytes = run_bytes;
	run->txs = run_txs;
	swapz_engine_invalidate_read_cache(e);

	if (compressed_count) {
		phase_start = swapz_engine_now_ns();
		error = swapz_engine_plan_bounded_policy(pages, compressed_count,
						plan_read_blocks,
						e->plan_classes, e->plan_takes,
						&extent_count, 1,
						e->authority->next_block);
		e->plan_wall_ns += swapz_engine_elapsed_ns(
			phase_start, swapz_engine_now_ns());
		if (error)
			return error;
	}

	for (group = 0; group < extent_count + raw_count; ++group) {
		struct swapz_builder builder;
		struct swapz_tx *tx;
		const swapz_u8 raw = group >= extent_count;
		swapz_u8 blocks = raw ? 1 : e->plan_classes[group];
		swapz_u8 take = raw ? 1 : e->plan_takes[group], j;
		swapz_u32 placed, run_end;

		/*
		 * A prepared run is immutable once returned. Stop before the next
		 * extent would require another physical run; the caller can submit
		 * this prefix and prepare the remainder only after completion.
		 */
		if (staged) {
			placed = e->authority->next_block;
			run_end = run_start + run_blocks;
			if (placed / SWAPZ_SEGMENT_BLOCKS !=
					run_start / SWAPZ_SEGMENT_BLOCKS ||
			    placed % SWAPZ_SEGMENT_BLOCKS + blocks >
					SWAPZ_SEGMENT_BLOCKS ||
			    placed < run_start ||
			    (e->bulk_enabled == 1 && placed != run_end) ||
			    placed - run_start + blocks > SWAPZ_BULK_BLOCKS) {
				if (e->bulk_enabled == 1 && placed > run_end &&
				    placed / SWAPZ_SEGMENT_BLOCKS ==
					run_start / SWAPZ_SEGMENT_BLOCKS &&
				    placed - run_start + blocks <= SWAPZ_BULK_BLOCKS)
					e->run_splits_by_hole++;
				break;
			}
		}

		tx = &run->txs[staged];
		for (j = 0; j < take; ++j)
			e->logical_scratch[j] = pages[entry + j].logical_page;
		error = swapz_stage_batch(e->authority, e->logical_scratch,
					 take, blocks, tx);
		if (error) {
			/*
			 * If a valid prefix is already staged, preserve the old
			 * committed-prefix contract: return that immutable run now.
			 * The same remaining input is retried after publication.
			 */
			if (staged)
				break;
			return error;
		}
		if (!staged) {
			run_start = tx->start_block;
			run_blocks = 0;
		}
		if (tx->start_block < run_start ||
		    (e->bulk_enabled == 1 && staged &&
		     tx->start_block != run_start + run_blocks) ||
		    tx->start_block - run_start + blocks > SWAPZ_BULK_BLOCKS ||
		    tx->start_block / SWAPZ_SEGMENT_BLOCKS !=
						run_start / SWAPZ_SEGMENT_BLOCKS) {
			swapz_abort(e->authority, tx);
			error = -EUCLEAN;
			goto abort_run;
		}
		{
			swapz_u16 offset = tx->start_block - run_start;
			swapz_u16 end = offset + blocks;
			swapz_u8 *image = run->bytes +
					 (size_t)offset * SWAPZ_BLOCK_BYTES;

			if (offset > run_blocks)
				memset(run->bytes +
				       (size_t)run_blocks * SWAPZ_BLOCK_BYTES, 0,
				       (size_t)(offset - run_blocks) *
				       SWAPZ_BLOCK_BYTES);

			phase_start = swapz_engine_now_ns();
			if (raw) {
				memcpy(image, pages[entry].payload, SWAPZ_BLOCK_BYTES);
			} else {
				error = swapz_begin(&builder, image,
					    (swapz_u32)blocks * SWAPZ_BLOCK_BYTES,
					    tx->sequence);
				if (error) {
					e->pack_wall_ns += swapz_engine_elapsed_ns(
						phase_start, swapz_engine_now_ns());
					goto abort_current;
				}
				for (j = 0; j < take; ++j) {
					const struct swapz_compressed_page *p =
							 &pages[entry + j];

					error = swapz_append_page(
						e, &builder, p,
						tx->records[j].generation);
					if (error) {
						e->pack_wall_ns +=
							swapz_engine_elapsed_ns(
								phase_start,
								swapz_engine_now_ns());
						goto abort_current;
					}
				}
				error = swapz_seal(&builder);
				if (error) {
					e->pack_wall_ns += swapz_engine_elapsed_ns(
						phase_start, swapz_engine_now_ns());
					goto abort_current;
				}
			}
			e->pack_wall_ns += swapz_engine_elapsed_ns(
				phase_start, swapz_engine_now_ns());
			error = swapz_batch_pause(e->authority, tx);
			if (error)
				goto abort_current;
			run->offsets[staged] = offset;
			run->takes[staged] = take;
			run->raw[staged] = raw;
			e->bulk_padding_blocks += offset > run_blocks ?
						      offset - run_blocks : 0;
			run_blocks = end;
			staged++;
			entry += take;
		}
		continue;

abort_current:
		swapz_abort(e->authority, tx);
abort_run:
		if (staged) {
			run->extent_count = staged;
			{
				int cleanup = swapz_bulk_abort(e, run, 0);

				if (cleanup)
					return cleanup;
			}
		}
		return error;
	}

	if (!staged || !entry || !run_blocks)
		return -EUCLEAN;
	run->start_block = run_start;
	run->blocks = run_blocks;
	run->extent_count = staged;
	run->page_count = entry;
	*prepared_pages = entry;
	return 0;
}

int swapz_engine_complete_batched_run(struct swapz_engine *e,
				    const struct swapz_io_run *run,
				    swapz_u16 completed_blocks, int io_error,
				    swapz_u8 *committed_pages)
{
	swapz_u8 i, raw_entries = 0;
	int error = io_error;

	if (!e || !e->authority || !run || !run->bytes || !run->txs ||
	    !run->extent_count || !run->page_count || !run->blocks ||
	    run->blocks > SWAPZ_BULK_BLOCKS || !committed_pages)
		return -EINVAL;
	*committed_pages = 0;
	if (completed_blocks > run->blocks) {
		completed_blocks = 0;
		error = -EUCLEAN;
	}
	if (!error && completed_blocks != run->blocks)
		error = -EIO;
	if (error) {
		int cleanup = swapz_bulk_abort(e, run, 0);

		return cleanup ? cleanup : error;
	}

	e->completed_blocks += completed_blocks;
	e->bulk_writes++;
	e->bulk_extents += run->extent_count;
	for (i = 0; i < run->extent_count; ++i) {
		const struct swapz_tx *tx = &run->txs[i];
		swapz_u16 offset = run->offsets[i];
		unsigned long long publish_start = swapz_engine_now_ns();

		error = swapz_batch_resume(e->authority, tx);
		if (error) {
			int cleanup;

			e->publish_wall_ns += swapz_engine_elapsed_ns(
				publish_start, swapz_engine_now_ns());
			cleanup = swapz_bulk_abort(e, run, i);
			return cleanup ? cleanup : error;
		}
		if (run->raw[i])
			error = swapz_finish_raw(
				e->authority, tx,
				run->bytes + (size_t)offset * SWAPZ_BLOCK_BYTES,
				tx->extent_blocks, 0);
		else
			error = swapz_finish(
				e->authority, tx,
				run->bytes + (size_t)offset * SWAPZ_BLOCK_BYTES,
				(swapz_u32)tx->extent_blocks * SWAPZ_BLOCK_BYTES,
				tx->extent_blocks, 0);
		e->publish_wall_ns += swapz_engine_elapsed_ns(
			publish_start, swapz_engine_now_ns());
		if (error) {
			int cleanup = swapz_bulk_abort(e, run, i + 1);

			return cleanup ? cleanup : error;
		}
		*committed_pages += run->takes[i];
		if (run->raw[i])
			raw_entries++;
	}
	if (*committed_pages != run->page_count)
		return -EUCLEAN;
	e->bulk_raw_entries += raw_entries;
	if (raw_entries == run->extent_count)
		e->bulk_raw_only_runs++;
	else if (raw_entries)
		e->bulk_mixed_runs++;
	return 0;
}

int swapz_engine_write_window_batched_read_cap(struct swapz_engine *e,
				   const struct swapz_compressed_page *pages,
				   swapz_u8 count, swapz_u8 *committed_pages,
				   swapz_u8 plan_read_blocks)
{
	struct swapz_io_run run;
	swapz_u8 total = 0;
	swapz_u8 raw_count = 0;
	swapz_u8 index;
	int error;

	if (!e || !e->authority || !committed_pages || plan_read_blocks > 3U)
		return -EINVAL;
	*committed_pages = 0;
	if (!pages || !count || count > SWAPZ_MAX_RECORDS)
		return -EINVAL;
	for (index = 0; index < count; ++index)
		if (pages[index].raw)
			raw_count++;

	if (!raw_count && (!e->bulk_enabled || !e->bulk_scratch ||
	    !e->bulk_txs || !e->io.write_run || e->verify_after_write ||
	    count <= 1))
		return swapz_engine_write_window_planned(e, pages, count,
						      committed_pages,
						      plan_read_blocks);
	if (!e->bulk_enabled || !e->bulk_scratch || !e->bulk_txs ||
	    !e->io.write_run || e->verify_after_write)
		return -EOPNOTSUPP;

	memset(&run, 0, sizeof(run));
	run.bytes = e->bulk_scratch;
	run.txs = e->bulk_txs;
	while (total < count) {
		swapz_u8 prepared = 0, published = 0;
		swapz_u16 completed = 0;

		error = swapz_engine_prepare_batched_run(
			e, pages + total, count - total, &run, &prepared,
			plan_read_blocks);
		if (error == -EEXIST && !raw_count && !total)
			return swapz_engine_write_window_planned(
				e, pages, count, committed_pages, plan_read_blocks);
		if (error)
			return error;
		if (!prepared || prepared > count - total)
			return -EUCLEAN;

		e->submitted_blocks += run.blocks;
		error = e->io.write_run(e->io.opaque, run.start_block, run.blocks,
					run.bytes, &completed);
		if (completed > run.blocks) {
			completed = 0;
			error = -EUCLEAN;
		}
		if (!error && completed != run.blocks)
			error = -EIO;
		{
			int complete_error = swapz_engine_complete_batched_run(
				e, &run, completed, error, &published);

			if (complete_error)
				return complete_error;
		}
		if (published != prepared)
			return -EUCLEAN;
		total += published;
		*committed_pages = total;
	}
	return 0;
}

int swapz_engine_write_window_batched(struct swapz_engine *e,
				   const struct swapz_compressed_page *pages,
				   swapz_u8 count, swapz_u8 *committed_pages)
{
	if (!e)
		return -EINVAL;
	return swapz_engine_write_window_batched_read_cap(e, pages, count,
						committed_pages,
						e->max_read_blocks_per_record);
}

int swapz_engine_read_page(struct swapz_engine *engine, swapz_u32 logical_page,
			 swapz_u8 *payload, swapz_u16 payload_capacity,
			 swapz_u16 *payload_length)
{
	struct swapz_decoded peek;
	struct swapz_map observed;
	const swapz_u8 *stored;
	swapz_u32 bytes, first, last, start, count, block;
	swapz_u32 payload_first, payload_last;
	swapz_u8 initial_blocks = 1, cached_mask, coalesced_mask = 0;
	int error;
	int cached_metadata, cached_full, lru_cached_metadata;
	int extent_lru_slot, metadata_lru_slot;

	if (!engine || !engine->authority || !engine->read_scratch ||
	    !engine->io.read_blocks || !payload || !payload_length ||
	    logical_page >= engine->authority->logical_pages)
		return -EINVAL;
	*payload_length = 0;
	observed = engine->authority->maps[logical_page];
	if (!observed.valid || !observed.extent_blocks ||
	    observed.extent_blocks > SWAPZ_MAX_BLOCKS ||
	    observed.start_block >= engine->authority->physical_blocks ||
	    observed.extent_blocks >
			engine->authority->physical_blocks - observed.start_block ||
	    !observed.payload_length ||
	    observed.payload_offset >=
		(swapz_u32)observed.extent_blocks * SWAPZ_BLOCK_BYTES ||
	    observed.payload_length >
		(swapz_u32)observed.extent_blocks * SWAPZ_BLOCK_BYTES -
		observed.payload_offset)
		return -ESTALE;
	bytes = (swapz_u32)observed.extent_blocks * SWAPZ_BLOCK_BYTES;
	/*
	 * Two-block extent: the bounded one-request read trades up to one
	 * extra 4KiB block for avoiding a second synchronous lower callback.
	 * Never exceed the explicit one-block read-budget policy. Other
	 * extents keep metadata-first selective I/O.
	 *
	 * The ordered worker owns read_scratch and invalidates on every
	 * write/GC/discard/barrier. Only the same immutable physical extent
	 * can reuse its block-zero metadata or complete two-block contents;
	 * payload/generation/CRC validation still runs for EVERY logical read.
	 */
	cached_metadata = engine->read_cache_valid &&
		engine->read_cached_start_block == observed.start_block &&
		engine->read_cached_extent_blocks == observed.extent_blocks;
	cached_full = cached_metadata && engine->read_cached_full;
	cached_mask = cached_metadata ? engine->read_cached_block_mask : 0;
	coalesced_mask = cached_metadata ?
		engine->read_coalesced_block_mask : 0;
	extent_lru_slot = engine->max_read_blocks_per_record != 1 ?
		swapz_read_extent_lru_lookup(engine, observed.start_block,
					     observed.extent_blocks) : -1;
	if (extent_lru_slot >= 0) {
		swapz_u8 extent_mask =
			engine->read_extent_lru_block_masks[extent_lru_slot];

		for (block = 0; block < observed.extent_blocks; ++block)
			if (extent_mask & (1U << block))
				memcpy(engine->read_scratch +
				       (size_t)block * SWAPZ_BLOCK_BYTES,
				       engine->read_extent_cache +
				       (size_t)extent_lru_slot * SWAPZ_MAX_EXTENT_BYTES +
				       (size_t)block * SWAPZ_BLOCK_BYTES,
				       SWAPZ_BLOCK_BYTES);
		cached_mask |= extent_mask;
		cached_metadata = !!(cached_mask & 1U);
		cached_full = cached_mask ==
			(swapz_u8)((1U << observed.extent_blocks) - 1U);
	}
	metadata_lru_slot = swapz_read_metadata_lru_lookup(engine,
						 observed.start_block,
						 observed.extent_blocks);
	lru_cached_metadata = !cached_metadata && metadata_lru_slot >= 0;
	engine->read_cache_valid = 0;
	engine->read_cached_full = 0;
	engine->read_cached_block_mask = 0;
	engine->read_coalesced_block_mask = 0;
	if (lru_cached_metadata) {
		memcpy(engine->read_scratch,
		       engine->read_metadata_cache +
		       (size_t)metadata_lru_slot * SWAPZ_BLOCK_BYTES,
		       SWAPZ_BLOCK_BYTES);
		cached_mask |= 1U;
	} else if (!cached_metadata) {
		if (observed.extent_blocks == 2 &&
		    engine->max_read_blocks_per_record != 1 &&
		    (swapz_u32)observed.payload_offset +
			observed.payload_length > SWAPZ_BLOCK_BYTES)
			initial_blocks = 2;
		error = engine->io.read_blocks(engine->io.opaque,
					       observed.start_block, initial_blocks,
					       engine->read_scratch);
		if (error)
			return error;
		engine->physical_read_blocks += initial_blocks;
		engine->read_metadata_requests++;
		cached_mask = (swapz_u8)((1U << initial_blocks) - 1U);
		if (initial_blocks == 2)
			engine->read_full_extent_requests++;
		else if (observed.extent_blocks == 2 &&
			 engine->max_read_blocks_per_record != 1)
			engine->read_two_block_skips++;
	}
	error = swapz_peek(engine->read_scratch, bytes,
			 observed.record_index, &peek);
	if (error)
		return error;
	if (peek.logical_page != logical_page ||
	    peek.generation != observed.generation ||
	    peek.payload_length != observed.payload_length ||
	    peek.payload_offset != observed.payload_offset)
		return -EUCLEAN;
	payload_first = peek.payload_offset / SWAPZ_BLOCK_BYTES;
	payload_last = ((swapz_u32)peek.payload_offset +
		peek.payload_length - 1U) / SWAPZ_BLOCK_BYTES;
	first = payload_first;
	last = payload_last;
	/*
	 * Block zero is already resident before peek. A compressed record is at
	 * most SWAPZ_MAX_COMPRESSED bytes, so first..last spans at most two
	 * contiguous 4KiB blocks. Trimming resident blocks from both ends
	 * therefore leaves either one contiguous missing run or nothing.
	 */
	start = first ? first : 1U;
	while (start <= last && (cached_mask & (1U << start)))
		start++;
	while (start <= last && (cached_mask & (1U << last)))
		last--;
	if (last >= start) {
		count = last - start + 1U;
		if (start + count > observed.extent_blocks)
			return -EUCLEAN;
		error = engine->io.read_blocks(engine->io.opaque,
			observed.start_block + start, count,
			engine->read_scratch + start * SWAPZ_BLOCK_BYTES);
		if (error)
			return error;
		engine->physical_read_blocks += count;
		engine->read_payload_requests++;
		engine->read_payload_blocks += count;
		/* The explicit one-block budget is selective-I/O semantics, not a
		 * prefetch/residency mode. Do not retain payload blocks there: the
		 * next logical read must independently exercise its bounded lower
		 * payload callback and fail closed if that callback fails. */
		if (observed.extent_blocks > 1 &&
		    engine->max_read_blocks_per_record != 1)
			for (block = start; block < start + count; ++block)
				cached_mask |= (swapz_u8)(1U << block);
	}
	error = swapz_read_authoritative_peeked(engine->authority, logical_page,
					      &observed, engine->read_scratch,
					      bytes, &peek, &stored);
	if (error)
		return error;
	if (peek.payload_length > payload_capacity)
		return -ENOSPC;
	memcpy(payload, stored, peek.payload_length);
	*payload_length = peek.payload_length;
	/* Publish reusable bytes only after successful authority, generation
	 * and payload-CRC validation. Any error path leaves the cache invalid. */
	engine->read_cached_start_block = observed.start_block;
	engine->read_cached_extent_blocks = observed.extent_blocks;
	/* Preserve the qualified one-block/selective-read contract: "full" is
	 * reusable multi-block extent residency, never merely a fetched 4KiB
	 * metadata block. The exact block mask remains authoritative either way. */
	engine->read_cached_full = observed.extent_blocks > 1 &&
		engine->max_read_blocks_per_record != 1 &&
		cached_mask == (swapz_u8)((1U << observed.extent_blocks) - 1U);
	engine->read_cached_block_mask = cached_mask;
	engine->read_cache_valid = 1;
	/* Seeded combined-read blocks become reusable cache only after this
	 * record validates its immutable metadata/generation/payload CRC. */
	{
		swapz_u8 validated = 1U;
		swapz_u32 validated_block;

		for (validated_block = payload_first;
		     validated_block <= payload_last; ++validated_block)
			validated |= (swapz_u8)(1U << validated_block);
		engine->read_coalesced_block_mask =
			coalesced_mask & (swapz_u8)~validated;
	}
	if (cached_metadata && !(coalesced_mask & 1U))
		engine->read_metadata_cache_hits++;
	if (cached_full && !coalesced_mask)
		engine->read_full_extent_cache_hits++;
	if (lru_cached_metadata)
		engine->read_metadata_lru_hits++;
	swapz_read_metadata_lru_commit(engine, observed.start_block,
				     observed.extent_blocks,
				     metadata_lru_slot, engine->read_scratch);
	if (engine->read_extent_cache &&
	    engine->max_read_blocks_per_record != 1 &&
	    observed.extent_blocks > 1)
		swapz_read_extent_lru_commit(engine, observed.start_block,
					     observed.extent_blocks,
					     cached_mask, engine->read_scratch);
	return 0;
}
