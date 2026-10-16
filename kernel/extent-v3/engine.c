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
	return page && !page->raw && page->payload && page->length > 0 &&
		page->length <= SV3_MAX_COMPRESSED;
}

/*
 * Check a complete logical page only after the caller's cheap LZ4 size
 * admission (<64B). A merely compressible/patterned page is NOT zero;
 * missing even a single nonzero byte would corrupt authoritative data.
 * No temporary allocation, no lower I/O, no unaligned word loads.
 */
int sv3_page_is_zero(const sv3_u8 *page)
{
	sv3_u32 i;

	if (!page)
		return 0;
	for (i = 0; i < SV3_BLOCK_BYTES; ++i)
		if (page[i])
			return 0;
	return 1;
}

/* How many *ordered* records fit the size class, without duplicate slots. */
static sv3_u8 sv3_fit_count(const struct sv3_compressed_page *pages,
			   sv3_u8 count, sv3_u8 start, sv3_u8 blocks,
			   sv3_u8 max_read_blocks, sv3_u32 *read_blocks)
{
	sv3_u32 payload_start = (sv3_u32)blocks * SV3_BLOCK_BYTES;
	sv3_u8 included = 0;
	sv3_u8 index;

	*read_blocks = 0;
	for (index = start; index < count; ++index) {
		sv3_u8 earlier;
		sv3_u32 offset;
		sv3_u32 first, last, record_reads;
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

int sv3_engine_plan_bounded(const struct sv3_compressed_page *pages,
			    sv3_u8 count, sv3_u8 max_read_blocks,
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
	    !count || count > SV3_MAX_RECORDS || max_read_blocks > 3U)
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
						   max_read_blocks,
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

int sv3_engine_plan(const struct sv3_compressed_page *pages, sv3_u8 count,
		    sv3_u8 *classes, sv3_u8 *records_per_extent,
		    sv3_u8 *extent_count)
{
	return sv3_engine_plan_bounded(pages, count, 0,
				      classes, records_per_extent,
				      extent_count);
}

void sv3_engine_invalidate_read_cache(struct sv3_engine *engine)
{
	if (engine) {
		engine->read_cache_valid = 0;
		engine->read_cached_full = 0;
	}
}

static int sv3_engine_write_window_planned(struct sv3_engine *engine,
			    const struct sv3_compressed_page *pages,
			    sv3_u8 count, sv3_u8 *committed_pages,
			    sv3_u8 plan_read_blocks)
{
	struct sv3_tx *tx;
	sv3_u8 extent_count, entry = 0, group;
	int error;

	if (!engine || !engine->authority || !engine->write_scratch ||
	    !engine->io.write_extent || !committed_pages)
		return -EINVAL;
	*committed_pages = 0;
	/* Even a failed/torn write must never leave reusable old metadata. */
	sv3_engine_invalidate_read_cache(engine);
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
	error = sv3_engine_plan_bounded(pages, count, plan_read_blocks,
					engine->plan_classes,
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
			/*
			 * A lower callback claiming impossible completion counts
			 * is not trustworthy: do not count any validated blocks.
			 * sv3_finish() quarantines the whole allocated extent.
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
			memset(engine->read_scratch, 0, bytes);
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

int sv3_engine_write_window(struct sv3_engine *engine,
			    const struct sv3_compressed_page *pages,
			    sv3_u8 count, sv3_u8 *committed_pages)
{
	if (!engine)
		return -EINVAL;
	return sv3_engine_write_window_planned(engine, pages, count,
					      committed_pages,
					      engine->max_read_blocks_per_record);
}

/*
 * Bounded lower request aggregation (up to 64 adjacent physical 4KiB
 * blocks), WITHOUT changing the independent on-disk SWZ3 extents.
 *
 * Stage each extent and leave its mapping UNPUBLISHED. Consecutive
 * transaction snapshots are replayed through the original sv3_finish()
 * only after the ONE combined lower I/O has completed successfully.
 * This preserves the original committed-prefix semantics on a failed
 * group, and prevents false acknowledgement of durable media.
 */
static int sv3_bulk_abort(struct sv3_engine *e, sv3_u8 count,
			  sv3_u8 first)
{
	sv3_u8 i;
	int error;

	for (i = first; i < count; ++i) {
		error = sv3_batch_resume(e->authority, &e->bulk_txs[i]);
		if (error)
			return error;
		error = sv3_abort(e->authority, &e->bulk_txs[i]);
		if (error)
			return error;
	}
	return 0;
}

static int sv3_bulk_flush(struct sv3_engine *e, sv3_u32 start,
			  sv3_u16 blocks, sv3_u8 count,
			  sv3_u8 *committed_pages)
{
	sv3_u16 completed = 0;
	sv3_u8 i, raw_entries = 0;
	int error;

	if (!count)
		return 0;
	if (!blocks || blocks > SV3_BULK_BLOCKS)
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
		int cleanup = sv3_bulk_abort(e, count, 0);

		return cleanup ? cleanup : error;
	}
	e->completed_blocks += completed;
	e->bulk_writes++;
	e->bulk_extents += count;
	for (i = 0; i < count; ++i) {
		struct sv3_tx *tx = &e->bulk_txs[i];
		sv3_u16 offset = e->bulk_offsets[i];

		error = sv3_batch_resume(e->authority, tx);
		if (error) {
			int cleanup = sv3_bulk_abort(e, count, i);

			return cleanup ? cleanup : error;
		}
		/* Same lower completion, but distinct CRC/mapping publication:
		 * raw blocks carry no SWZ3 metadata on physical media. */
		if (e->bulk_raw[i])
			error = sv3_finish_raw(e->authority, tx,
				e->bulk_scratch +
					(size_t)offset * SV3_BLOCK_BYTES,
				tx->extent_blocks, 0);
		else
			error = sv3_finish(e->authority, tx,
				   e->bulk_scratch +
					(size_t)offset * SV3_BLOCK_BYTES,
				   (sv3_u32)tx->extent_blocks * SV3_BLOCK_BYTES,
				   tx->extent_blocks, 0);
		if (error) {
			int cleanup = sv3_bulk_abort(e, count, i + 1);

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

int sv3_engine_write_window_batched_read_cap(struct sv3_engine *e,
				   const struct sv3_compressed_page *pages,
				   sv3_u8 count, sv3_u8 *committed_pages,
				   sv3_u8 plan_read_blocks)
{
	sv3_u8 extent_count = 0, compressed_count = 0, raw_count = 0;
	sv3_u8 entry = 0, group, staged = 0;
	sv3_u32 run_start = 0;
	sv3_u16 run_blocks = 0;
	int error;

	if (!e || !e->authority || !committed_pages || plan_read_blocks > 3U)
		return -EINVAL;
	*committed_pages = 0;
	sv3_engine_invalidate_read_cache(e);
	if (!pages || !count || count > SV3_MAX_RECORDS)
		return -EINVAL;
	/* Validate every record BEFORE reserving any physical blocks. The
	 * worker sorts compressed records first and appends the raw tail.
	 * Malformed or duplicate mixed input must not fall into the old
	 * SWZ3-only path, which cannot interpret raw data. */
	for (group = 0; group < count; ++group) {
		sv3_u8 j;

		if (pages[group].raw) {
			if (!pages[group].payload ||
			    pages[group].length != SV3_BLOCK_BYTES)
				return -EINVAL;
			raw_count++;
		} else {
			if (raw_count || !sv3_page_valid(&pages[group]))
				return -EINVAL;
			compressed_count++;
		}
		for (j = 0; j < group; ++j)
			if (pages[group].logical_page == pages[j].logical_page) {
				if (raw_count)
					return -EEXIST;
				return sv3_engine_write_window_planned(e, pages, count,
							      committed_pages,
							      plan_read_blocks);
			}
	}
	if (!raw_count && (!e->bulk_enabled || !e->bulk_scratch ||
	    !e->bulk_txs || !e->io.write_run || e->verify_after_write ||
	    count <= 1))
		return sv3_engine_write_window_planned(e, pages, count,
					      committed_pages,
					      plan_read_blocks);
	/* Raw admission stays serialized in lower_bulk=0/verify mode.
	 * Never silently reinterpret it as a compressed SWZ3 record. */
	if (!e->bulk_enabled || !e->bulk_scratch || !e->bulk_txs ||
	    !e->io.write_run || e->verify_after_write)
		return -EOPNOTSUPP;
	if (compressed_count) {
		error = sv3_engine_plan_bounded(pages, compressed_count,
					plan_read_blocks,
					e->plan_classes, e->plan_takes,
					&extent_count);
		if (error)
			return error;
	}
	for (group = 0; group < extent_count + raw_count; ++group) {
		struct sv3_builder builder;
		struct sv3_tx *tx;
		const sv3_u8 raw = group >= extent_count;
		sv3_u8 blocks = raw ? 1 : e->plan_classes[group];
		sv3_u8 take = raw ? 1 : e->plan_takes[group], j;
		sv3_u32 aligned;

		/*
		 * Flush the old run BEFORE trying to move the authority
		 * beyond its pending segment or 256KiB limit. Alignment
		 * holes are explicitly zero filled and count as real lower
		 * bytes; never pack across independently recyclable segments.
		 */
		if (staged) {
			aligned = (e->authority->next_block + blocks - 1U) &
				  ~(sv3_u32)(blocks - 1U);
			if (aligned / SV3_SEGMENT_BLOCKS !=
					run_start / SV3_SEGMENT_BLOCKS ||
			    aligned < run_start ||
			    (e->bulk_enabled == 1 &&
			     aligned != run_start + run_blocks) ||
			    aligned - run_start + blocks > SV3_BULK_BLOCKS) {
				error = sv3_bulk_flush(e, run_start, run_blocks,
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
		error = sv3_stage_batch(e->authority, e->logical_scratch,
					take, blocks, tx);
		if (error == -EAGAIN && staged) {
			error = sv3_bulk_flush(e, run_start, run_blocks,
					       staged, committed_pages);
			if (error)
				return error;
			staged = 0;
			goto retry_stage;
		}
		if (error) {
			if (staged) {
				int flushed = sv3_bulk_flush(e, run_start,
						run_blocks, staged, committed_pages);

				if (flushed)
					return flushed;
			}
			return error;
		}
		if (!staged) {
			run_start = tx->start_block;
			run_blocks = 0;
			memset(e->bulk_scratch, 0,
			       SV3_BULK_BLOCKS * SV3_BLOCK_BYTES);
		}
		if (tx->start_block < run_start ||
		    (e->bulk_enabled == 1 && staged &&
		     tx->start_block != run_start + run_blocks) ||
		    tx->start_block - run_start + blocks > SV3_BULK_BLOCKS ||
		    tx->start_block / SV3_SEGMENT_BLOCKS !=
					run_start / SV3_SEGMENT_BLOCKS) {
			sv3_abort(e->authority, tx);
			error = -EUCLEAN;
			goto abort_group;
		}
		{
			sv3_u16 offset = tx->start_block - run_start;
			sv3_u16 end = offset + blocks;
			sv3_u8 *image = e->bulk_scratch +
					       (size_t)offset * SV3_BLOCK_BYTES;

			if (raw) {
				/* A raw block must not acquire a fake SWZ3 header. */
				memcpy(image, pages[entry].payload, SV3_BLOCK_BYTES);
			} else {
				error = sv3_begin(&builder, image,
					  (sv3_u32)blocks * SV3_BLOCK_BYTES,
					  tx->sequence);
				if (error)
					goto abort_current;
				for (j = 0; j < take; ++j) {
					const struct sv3_compressed_page *p =
							&pages[entry + j];

					error = sv3_append(&builder, p->logical_page,
						   tx->records[j].generation,
						   p->payload, p->length);
					if (error)
						goto abort_current;
				}
				error = sv3_seal(&builder);
				if (error)
					goto abort_current;
			}
			error = sv3_batch_pause(e->authority, tx);
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
		sv3_abort(e->authority, tx);
abort_group:
		if (staged) {
			int cleanup = sv3_bulk_abort(e, staged, 0);

			if (cleanup)
				return cleanup;
		}
		return error;
	}
	return sv3_bulk_flush(e, run_start, run_blocks, staged,
			      committed_pages);
}

int sv3_engine_write_window_batched(struct sv3_engine *e,
				   const struct sv3_compressed_page *pages,
				   sv3_u8 count, sv3_u8 *committed_pages)
{
	if (!e)
		return -EINVAL;
	return sv3_engine_write_window_batched_read_cap(e, pages, count,
						committed_pages,
						e->max_read_blocks_per_record);
}

int sv3_engine_read_page(struct sv3_engine *engine, sv3_u32 logical_page,
			 sv3_u8 *payload, sv3_u16 payload_capacity,
			 sv3_u16 *payload_length)
{
	struct sv3_decoded peek, decoded;
	struct sv3_map observed;
	const sv3_u8 *stored;
	sv3_u32 bytes, first, last, start, count;
	sv3_u8 initial_blocks = 1;
	int error;
	int cached_metadata, cached_full;

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
			engine->authority->physical_blocks - observed.start_block ||
	    !observed.payload_length ||
	    observed.payload_offset >=
		(sv3_u32)observed.extent_blocks * SV3_BLOCK_BYTES ||
	    observed.payload_length >
		(sv3_u32)observed.extent_blocks * SV3_BLOCK_BYTES -
		observed.payload_offset)
		return -ESTALE;
	bytes = (sv3_u32)observed.extent_blocks * SV3_BLOCK_BYTES;
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
	engine->read_cache_valid = 0;
	engine->read_cached_full = 0;
	if (cached_metadata) {
		if (!cached_full && bytes > SV3_BLOCK_BYTES)
			memset(engine->read_scratch + SV3_BLOCK_BYTES, 0,
			       bytes - SV3_BLOCK_BYTES);
	} else {
		if (observed.extent_blocks == 2 &&
		    engine->max_read_blocks_per_record != 1 &&
		    (sv3_u32)observed.payload_offset +
			observed.payload_length > SV3_BLOCK_BYTES)
			initial_blocks = 2;
		memset(engine->read_scratch, 0, bytes);
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
	error = sv3_peek(engine->read_scratch, bytes,
			 observed.record_index, &peek);
	if (error)
		return error;
	if (peek.logical_page != logical_page ||
	    peek.generation != observed.generation ||
	    peek.payload_length != observed.payload_length ||
	    peek.payload_offset != observed.payload_offset)
		return -EUCLEAN;
	first = peek.payload_offset / SV3_BLOCK_BYTES;
	last = ((sv3_u32)peek.payload_offset +
		peek.payload_length - 1U) / SV3_BLOCK_BYTES;
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
			engine->read_scratch + start * SV3_BLOCK_BYTES);
		if (error)
			return error;
		engine->physical_read_blocks += count;
		engine->read_payload_requests++;
		engine->read_payload_blocks += count;
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
	return 0;
}
