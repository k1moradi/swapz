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

static int swapz_page_valid(const struct swapz_compressed_page *page)
{
	return page && !page->raw && page->payload && page->length > 0 &&
		page->length <= SWAPZ_MAX_COMPRESSED;
}

static int swapz_engine_append_page(struct swapz_builder *builder,
				    const struct swapz_compressed_page *page,
				    swapz_u32 generation)
{
	if (page->payload_crc_valid)
		return swapz_append_prehashed(builder, page->logical_page,
					      generation, page->payload,
					      page->length,
					      page->payload_crc32c);
	return swapz_append(builder, page->logical_page, generation,
			    page->payload, page->length);
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
			     * identical, put the more strictly aligned extent
			     * first. With power-of-two 4/8/16KiB classes this
			     * moves an unavoidable alignment hole before the
			     * lower run instead of between two extents, allowing
			     * adjacent-only mode to submit one request without
			     * writing any padding bytes.
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
				swapz_u32 aligned, hole;

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
				aligned = (alignment_cursor + blocks - 1U) &
					  ~(swapz_u32)(blocks - 1U);
				hole = aligned - alignment_cursor;
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
		alignment_cursor =
			((alignment_cursor + chosen_class - 1U) &
			 ~(swapz_u32)(chosen_class - 1U)) + chosen_class;
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

static int swapz_read_metadata_lru_lookup(const struct swapz_engine *engine,
					swapz_u32 start_block,
					swapz_u8 extent_blocks)
{
	swapz_u16 index;

	if (!engine->read_metadata_cache)
		return -1;
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
					int hit_slot)
{
	swapz_u32 oldest_age = ~(swapz_u32)0;
	swapz_u16 index, slot = 0;
	int have_slot = 0;

	if (!engine->read_metadata_cache)
		return;
	engine->read_metadata_lru_clock++;
	if (!engine->read_metadata_lru_clock) {
		/* Preserve exact age ordering across wrap by starting a fresh epoch.
		 * Current validated metadata is inserted below. */
		memset(engine->read_metadata_lru_valid, 0,
		       sizeof(engine->read_metadata_lru_valid));
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
		       engine->read_scratch, SWAPZ_BLOCK_BYTES);
	engine->read_metadata_lru_start_blocks[slot] = start_block;
	engine->read_metadata_lru_extent_blocks[slot] = extent_blocks;
	engine->read_metadata_lru_ages[slot] = engine->read_metadata_lru_clock;
	engine->read_metadata_lru_valid[slot] = 1;
}

void swapz_engine_invalidate_read_cache(struct swapz_engine *engine)
{
	if (engine) {
		engine->read_cache_valid = 0;
		engine->read_cached_full = 0;
		/*
		 * clock==0 is the canonical empty-LRU state. Writes commonly hit
		 * this fence more than once (process-level mutation plus physical
		 * lower WRITE), so do not rescan/clear 512 validity bytes when the
		 * previous invalidation already made every slot unreachable.
		 */
		if (engine->read_metadata_lru_clock) {
			memset(engine->read_metadata_lru_valid, 0,
			       sizeof(engine->read_metadata_lru_valid));
			engine->read_metadata_lru_clock = 0;
		}
	}
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
		phase_start = swapz_engine_now_ns();
		error = swapz_stage(engine->authority, engine->logical_scratch,
				  take, blocks, tx);
		engine->stage_wall_ns += swapz_engine_elapsed_ns(
			phase_start, swapz_engine_now_ns());
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

			error = swapz_engine_append_page(
				&builder, page, tx->records[j].generation);
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
static int swapz_bulk_abort(struct swapz_engine *e, swapz_u8 count,
			  swapz_u8 first)
{
	swapz_u8 i;
	int error;

	for (i = first; i < count; ++i) {
		error = swapz_batch_resume(e->authority, &e->bulk_txs[i]);
		if (error)
			return error;
		error = swapz_abort(e->authority, &e->bulk_txs[i]);
		if (error)
			return error;
	}
	return 0;
}

static int swapz_bulk_flush(struct swapz_engine *e, swapz_u32 start,
			  swapz_u16 blocks, swapz_u8 count,
			  swapz_u8 *committed_pages)
{
	swapz_u16 completed = 0;
	swapz_u8 i, raw_entries = 0;
	int error;

	if (!count)
		return 0;
	if (!blocks || blocks > SWAPZ_BULK_BLOCKS)
		return -EUCLEAN;
	e->submitted_blocks += blocks;
	error = e->io.write_run(e->io.opaque, start, blocks,
				e->bulk_scratch, &completed);
	if (completed > blocks) {
		completed = 0;
		error = -EUCLEAN;
	}
	if (!error && completed != blocks)
		error = -EIO;
	/*
	 * An uncertain lower I/O is NEVER interpreted as partial success.
	 * Quarantine all its reservations, including possibly written pages,
	 * and preserve prior authoritative generations.
	 */
	if (error) {
		int cleanup = swapz_bulk_abort(e, count, 0);

		return cleanup ? cleanup : error;
	}
	e->completed_blocks += completed;
	e->bulk_writes++;
	e->bulk_extents += count;
	for (i = 0; i < count; ++i) {
		struct swapz_tx *tx = &e->bulk_txs[i];
		swapz_u16 offset = e->bulk_offsets[i];
		unsigned long long publish_start = swapz_engine_now_ns();
		unsigned long long resume_start = publish_start;

		error = swapz_batch_resume(e->authority, tx);
		e->resume_wall_ns += swapz_engine_elapsed_ns(
			resume_start, swapz_engine_now_ns());
		if (error) {
			int cleanup;

			e->publish_wall_ns += swapz_engine_elapsed_ns(
				publish_start, swapz_engine_now_ns());
			cleanup = swapz_bulk_abort(e, count, i);
			return cleanup ? cleanup : error;
		}
		/* Same lower completion, but distinct CRC/mapping publication:
		 * raw blocks carry no SWZ3 metadata on physical media. */
		if (e->bulk_raw[i])
			error = swapz_finish_raw(e->authority, tx,
				e->bulk_scratch +
					(size_t)offset * SWAPZ_BLOCK_BYTES,
				tx->extent_blocks, 0);
		else
			error = swapz_finish(e->authority, tx,
				   e->bulk_scratch +
					(size_t)offset * SWAPZ_BLOCK_BYTES,
				   (swapz_u32)tx->extent_blocks * SWAPZ_BLOCK_BYTES,
				   tx->extent_blocks, 0);
		e->publish_wall_ns += swapz_engine_elapsed_ns(
			publish_start, swapz_engine_now_ns());
		if (error) {
			int cleanup = swapz_bulk_abort(e, count, i + 1);

			return cleanup ? cleanup : error;
		}
		*committed_pages += e->bulk_takes[i];
		if (e->bulk_raw[i])
			raw_entries++;
	}
	/* These composition counters count fully published runs, not
	 * attempted I/O and not independent backing-device requests. */
	e->bulk_raw_entries += raw_entries;
	if (raw_entries == count)
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
	swapz_u8 extent_count = 0, compressed_count = 0, raw_count = 0;
	swapz_u8 entry = 0, group, staged = 0;
	swapz_u32 run_start = 0;
	swapz_u16 run_blocks = 0;
	unsigned long long phase_start;
	int error;

	if (!e || !e->authority || !committed_pages || plan_read_blocks > 3U)
		return -EINVAL;
	*committed_pages = 0;
	swapz_engine_invalidate_read_cache(e);
	if (!pages || !count || count > SWAPZ_MAX_RECORDS)
		return -EINVAL;
	/* Validate every record BEFORE reserving any physical blocks. The
	 * worker sorts compressed records first and appends the raw tail.
	 * Malformed or duplicate mixed input must not fall into the old
	 * SWZ3-only path, which cannot interpret raw data. */
	for (group = 0; group < count; ++group) {
		swapz_u8 j;

		if (pages[group].raw) {
			if (!pages[group].payload ||
			    pages[group].length != SWAPZ_BLOCK_BYTES)
				return -EINVAL;
			raw_count++;
		} else {
			if (raw_count || !swapz_page_valid(&pages[group]))
				return -EINVAL;
			compressed_count++;
		}
		for (j = 0; j < group; ++j)
			if (pages[group].logical_page == pages[j].logical_page) {
				if (raw_count)
					return -EEXIST;
				return swapz_engine_write_window_planned(e, pages, count,
							      committed_pages,
							      plan_read_blocks);
			}
	}
	if (!raw_count && (!e->bulk_enabled || !e->bulk_scratch ||
	    !e->bulk_txs || !e->io.write_run || e->verify_after_write ||
	    count <= 1))
		return swapz_engine_write_window_planned(e, pages, count,
					      committed_pages,
					      plan_read_blocks);
	/* Raw admission stays serialized in lower_bulk=0/verify mode.
	 * Never silently reinterpret it as a compressed SWZ3 record. */
	if (!e->bulk_enabled || !e->bulk_scratch || !e->bulk_txs ||
	    !e->io.write_run || e->verify_after_write)
		return -EOPNOTSUPP;
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
		swapz_u32 aligned;

		/*
		 * Flush the old run BEFORE trying to move the authority
		 * beyond its pending segment or 256KiB limit. Alignment
		 * holes are explicitly zero filled and count as real lower
		 * bytes; never pack across independently recyclable segments.
		 */
		if (staged) {
			aligned = (e->authority->next_block + blocks - 1U) &
				  ~(swapz_u32)(blocks - 1U);
			if (aligned / SWAPZ_SEGMENT_BLOCKS !=
					run_start / SWAPZ_SEGMENT_BLOCKS ||
			    aligned < run_start ||
			    (e->bulk_enabled == 1 &&
			     aligned != run_start + run_blocks) ||
			    aligned - run_start + blocks > SWAPZ_BULK_BLOCKS) {
				error = swapz_bulk_flush(e, run_start, run_blocks,
						       staged, committed_pages);
				if (error)
					return error;
				staged = 0;
			}
		}
retry_stage:
		tx = &e->bulk_txs[staged];
		for (j = 0; j < take; ++j)
			e->logical_scratch[j] = pages[entry + j].logical_page;
		phase_start = swapz_engine_now_ns();
		error = swapz_stage_batch(e->authority, e->logical_scratch,
					take, blocks, tx);
		e->stage_wall_ns += swapz_engine_elapsed_ns(
			phase_start, swapz_engine_now_ns());
		if (error == -EAGAIN && staged) {
			error = swapz_bulk_flush(e, run_start, run_blocks,
					       staged, committed_pages);
			if (error)
				return error;
			staged = 0;
			goto retry_stage;
		}
		if (error) {
			if (staged) {
				int flushed = swapz_bulk_flush(e, run_start,
						run_blocks, staged, committed_pages);

				if (flushed)
					return flushed;
			}
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
			goto abort_group;
		}
		{
			swapz_u16 offset = tx->start_block - run_start;
			swapz_u16 end = offset + blocks;
			swapz_u8 *image = e->bulk_scratch +
					       (size_t)offset * SWAPZ_BLOCK_BYTES;

			/*
			 * Each extent initializes every byte it owns: compressed
			 * builders clear their final unused gap at seal, while RAW
			 * records overwrite one full block. Only mode 2 alignment holes
			 * become lower-media bytes, so clear exactly those holes instead
			 * of the whole 256KiB scratch buffer for every run.
			 */
			if (offset > run_blocks) {
				phase_start = swapz_engine_now_ns();
				memset(e->bulk_scratch +
				       (size_t)run_blocks * SWAPZ_BLOCK_BYTES, 0,
				       (size_t)(offset - run_blocks) *
				       SWAPZ_BLOCK_BYTES);
				e->hole_clear_wall_ns += swapz_engine_elapsed_ns(
					phase_start, swapz_engine_now_ns());
			}

			phase_start = swapz_engine_now_ns();
			if (raw) {
				/* A raw block must not acquire a fake SWZ3 header. */
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

					error = swapz_engine_append_page(
						&builder, p,
						tx->records[j].generation);
					if (error) {
						e->pack_wall_ns += swapz_engine_elapsed_ns(
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
			phase_start = swapz_engine_now_ns();
			error = swapz_batch_pause(e->authority, tx);
			e->pause_wall_ns += swapz_engine_elapsed_ns(
				phase_start, swapz_engine_now_ns());
			if (error)
				goto abort_current;
			e->bulk_offsets[staged] = offset;
			e->bulk_takes[staged] = take;
			e->bulk_raw[staged] = raw;
			e->bulk_padding_blocks += offset > run_blocks ?
						      offset - run_blocks : 0;
			run_blocks = end;
			staged++;
			entry += take;
		}
		continue;
abort_current:
		swapz_abort(e->authority, tx);
abort_group:
		if (staged) {
			int cleanup = swapz_bulk_abort(e, staged, 0);

			if (cleanup)
				return cleanup;
		}
		return error;
	}
	return swapz_bulk_flush(e, run_start, run_blocks, staged,
			      committed_pages);
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
	swapz_u32 bytes, first, last, start, count;
	swapz_u8 initial_blocks = 1;
	int error;
	int cached_metadata, cached_full, lru_cached_metadata;
	int metadata_lru_slot;

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
	metadata_lru_slot = swapz_read_metadata_lru_lookup(engine,
						 observed.start_block,
						 observed.extent_blocks);
	lru_cached_metadata = !cached_metadata && metadata_lru_slot >= 0;
	engine->read_cache_valid = 0;
	engine->read_cached_full = 0;
	if (lru_cached_metadata) {
		memcpy(engine->read_scratch,
		       engine->read_metadata_cache +
		       (size_t)metadata_lru_slot * SWAPZ_BLOCK_BYTES,
		       SWAPZ_BLOCK_BYTES);
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
	first = peek.payload_offset / SWAPZ_BLOCK_BYTES;
	last = ((swapz_u32)peek.payload_offset +
		peek.payload_length - 1U) / SWAPZ_BLOCK_BYTES;
	/* Both blocks are already present after full prefetch or a
	 * successful same-extent reuse; never issue a duplicate payload I/O. */
	start = (cached_full || initial_blocks == 2) ?
		observed.extent_blocks : (first ? first : 1U);
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
	engine->read_cached_full = cached_full || initial_blocks == 2;
	engine->read_cache_valid = 1;
	if (cached_metadata)
		engine->read_metadata_cache_hits++;
	if (cached_full)
		engine->read_full_extent_cache_hits++;
	if (lru_cached_metadata)
		engine->read_metadata_lru_hits++;
	swapz_read_metadata_lru_commit(engine, observed.start_block,
				     observed.extent_blocks,
				     metadata_lru_slot);
	return 0;
}
