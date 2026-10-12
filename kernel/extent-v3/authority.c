// SPDX-License-Identifier: GPL-2.0-only
#include "authority.h"

#ifdef __KERNEL__
#include <linux/errno.h>
#include <linux/string.h>
#else
#include <errno.h>
#include <string.h>
#endif

static int sv3_legal_class(sv3_u8 blocks)
{
	return blocks == 1U || blocks == 2U || blocks == 4U;
}

int sv3_authority_init(struct sv3_authority *a,
		       struct sv3_map *maps, sv3_u16 *live_records,
		       sv3_u8 *extent_classes, sv3_u32 logical_pages,
		       sv3_u32 physical_blocks)
{
	sv3_u32 reserve;

	if (!a || !maps || !live_records || !extent_classes ||
	    !logical_pages || physical_blocks < 3U * SV3_SEGMENT_BLOCKS ||
	    physical_blocks % SV3_SEGMENT_BLOCKS)
		return -EINVAL;
	reserve = (logical_pages / 4U) + (logical_pages % 4U != 0);
	if (reserve < 2U * SV3_SEGMENT_BLOCKS)
		reserve = 2U * SV3_SEGMENT_BLOCKS;
	if (reserve >= physical_blocks ||
	    logical_pages > ((physical_blocks - reserve) /
			     SV3_SEGMENT_BLOCKS) * SV3_SEGMENT_BLOCKS)
		return -ENOSPC;

	memset(a, 0, sizeof(*a));
	memset(maps, 0, (size_t)logical_pages * sizeof(*maps));
	memset(live_records, 0,
	       (size_t)physical_blocks * sizeof(*live_records));
	memset(extent_classes, 0,
	       (size_t)physical_blocks * sizeof(*extent_classes));
	a->maps = maps;
	a->live_records = live_records;
	a->extent_classes = extent_classes;
	a->logical_pages = logical_pages;
	a->physical_blocks = physical_blocks;
	a->reserve_blocks = reserve;
	a->open_segment = ~(sv3_u32)0;
	a->gc_forbidden_open = ~(sv3_u32)0;
	a->gc_forbidden_victim = ~(sv3_u32)0;
	a->next_sequence = 1;
	return 0;
}

/*
 * The safe, strictly limited first V3 GC step: reuse only wholly-dead
 * 1MiB segments.  A live object is NEVER copied or overwritten here.
 *
 * Each candidate is checked against BOTH physical live-record counts and
 * all valid logical mappings, because a corrupt refcount must not cause
 * silent live-data overwrite.  No segment in the fixed reserve tail is used.
 * One ordered worker owns maps, segment metadata and the active write.
 */
static int sv3_pick_dead_segment(struct sv3_authority *a)
{
	sv3_u32 count = (a->gc_allocation ?
				a->physical_blocks :
				a->physical_blocks - a->reserve_blocks) /
			SV3_SEGMENT_BLOCKS;
	sv3_u32 scan;

	if (!count)
		return -ENOSPC;
	for (scan = 0; scan < count; ++scan) {
		sv3_u32 segment = (a->next_segment_probe + scan) % count;
		sv3_u32 start = segment * SV3_SEGMENT_BLOCKS;
		sv3_u32 off, logical;
		int used = 0, blocked = 0;

		/*
		 * GC temporarily borrows the segment ring. Never let it
		 * allocate into the paused foreground OPEN segment even if
		 * all current mappings there are dead: the foreground cursor
		 * will be restored after GC. Nor may it allocate into the
		 * victim until the entire move is verified complete.
		 */
		if (a->gc_allocation &&
		    (segment == a->gc_forbidden_open ||
		     segment == a->gc_forbidden_victim))
			continue;
		for (off = 0; off < SV3_SEGMENT_BLOCKS; ++off) {
			if (a->live_records[start + off]) {
				blocked = 1;
				break;
			}
			if (a->extent_classes[start + off])
				used = 1;
		}
		if (blocked)
			continue;
		for (logical = 0; logical < a->logical_pages; ++logical) {
			const struct sv3_map *map = &a->maps[logical];

			if (!map->valid)
				continue;
			if (map->start_block >= a->physical_blocks)
				return -EUCLEAN;
			if (map->start_block / SV3_SEGMENT_BLOCKS == segment) {
				blocked = 1;
				break;
			}
		}
		if (blocked)
			continue;
		/*
		 * Segment has no authoritative records and no pending writes.
		 * The previous contents are disposable swap bytes, not durable
		 * data. Reuse the WHOLE segment; stage never crosses its edge.
		 */
		memset(a->live_records + start, 0,
		       SV3_SEGMENT_BLOCKS * sizeof(*a->live_records));
		memset(a->extent_classes + start, 0,
		       SV3_SEGMENT_BLOCKS * sizeof(*a->extent_classes));
		if (used)
			a->recycled_dead_segments++;
		a->next_block = start;
		a->open_segment = segment;
		a->next_segment_probe = (segment + 1U) % count;
		return 0;
	}
	return -ENOSPC;
}

int sv3_stage(struct sv3_authority *a, const sv3_u32 *pages,
	      sv3_u8 count, sv3_u8 blocks, struct sv3_tx *out)
{
	sv3_u32 limit, start;
	sv3_u8 index;

	if (!a || !a->maps || !pages || !out ||
	    !sv3_legal_class(blocks) || !count || count > SV3_MAX_RECORDS)
		return -EINVAL;
	if (a->in_flight)
		return -EBUSY;
	if (!a->next_sequence || a->next_sequence == ~(sv3_u32)0)
		return -EOVERFLOW;
	for (index = 0; index < count; ++index) {
		sv3_u8 earlier;

		if (pages[index] >= a->logical_pages)
			return -ERANGE;
		if (a->maps[pages[index]].generation == ~(sv3_u32)0)
			return -EOVERFLOW;
		for (earlier = 0; earlier < index; ++earlier) {
			if (pages[earlier] == pages[index])
				return -EEXIST;
		}
	}

	if (!a->reuse_dead_segments) {
		/* Frozen append-only behavior used by the original V3 model. */
		limit = a->physical_blocks - a->reserve_blocks;
		if (a->next_block > limit ||
		    blocks - 1U > limit - a->next_block)
			return -ENOSPC;
		start = (a->next_block + blocks - 1U) &
			~(sv3_u32)(blocks - 1U);
		if (start > limit || blocks > limit - start ||
		    start % SV3_SEGMENT_BLOCKS + blocks > SV3_SEGMENT_BLOCKS)
			return -ENOSPC;
	} else {
		limit = ((a->gc_allocation ?
				 a->physical_blocks :
				 a->physical_blocks - a->reserve_blocks) /
			 SV3_SEGMENT_BLOCKS) * SV3_SEGMENT_BLOCKS;
		/*
		 * Reuse the OPEN segment only while the entire aligned extent fits.
		 * A crossed segment edge MUST run the mapped-record liveness scan;
		 * merely advancing to the numerically next segment can destroy data
		 * after physical cursor wrap.
		 */
		start = a->next_block;
		if (a->open_segment == ~(sv3_u32)0 ||
		    start >= limit || blocks - 1U > limit - start ||
		    ((start + blocks - 1U) & ~(sv3_u32)(blocks - 1U)) >
				limit - blocks ||
		    (((start + blocks - 1U) & ~(sv3_u32)(blocks - 1U)) /
		     SV3_SEGMENT_BLOCKS) != a->open_segment ||
		    ((start + blocks - 1U) & ~(sv3_u32)(blocks - 1U)) %
				SV3_SEGMENT_BLOCKS + blocks > SV3_SEGMENT_BLOCKS) {
			int error = sv3_pick_dead_segment(a);

			if (error)
				return error;
			start = a->next_block;
		}
		start = (start + blocks - 1U) & ~(sv3_u32)(blocks - 1U);
		if (start >= limit || blocks > limit - start ||
		    start / SV3_SEGMENT_BLOCKS != a->open_segment ||
		    start % SV3_SEGMENT_BLOCKS + blocks > SV3_SEGMENT_BLOCKS)
			return -EUCLEAN;

	}
	memset(out, 0, sizeof(*out));
	out->start_block = start;
	out->sequence = a->next_sequence++;
	out->extent_blocks = blocks;
	out->count = count;
	for (index = 0; index < count; ++index) {
		out->records[index].logical_page = pages[index];
		out->records[index].generation =
			a->maps[pages[index]].generation + 1U;
	}
	/*
	 * Consume the reserved space NOW, before lower submission.  On any
	 * short/torn write it will be quarantined, never reused by this code.
	 */
	a->next_block = start + blocks;
	a->active_start = start;
	a->active_sequence = out->sequence;
	a->active_blocks = blocks;
	a->active_count = count;
	/* All original record identities and generations are now authoritative. */
	a->active_tx = *out;
	a->in_flight = 1;
	return 0;
}

static int sv3_is_active(const struct sv3_authority *a,
			 const struct sv3_tx *tx)
{
	sv3_u8 index;

	if (!a || !tx || !a->in_flight ||
	    tx->start_block != a->active_start ||
	    tx->sequence != a->active_sequence ||
	    tx->extent_blocks != a->active_blocks ||
	    tx->count != a->active_count ||
	    tx->start_block != a->active_tx.start_block ||
	    tx->sequence != a->active_tx.sequence ||
	    tx->extent_blocks != a->active_tx.extent_blocks ||
	    tx->count != a->active_tx.count ||
	    !sv3_legal_class(tx->extent_blocks) ||
	    !tx->count || tx->count > SV3_MAX_RECORDS)
		return 0;

	/* Compare fields, not padding, and NEVER trust a caller-mutated
	 * tx record in either finish or abort before this full identity check.
	 * A rejected forged handle leaves the original transaction in flight.
	 */
	for (index = 0; index < tx->count; ++index) {
		if (tx->records[index].logical_page !=
				a->active_tx.records[index].logical_page ||
		    tx->records[index].generation !=
				a->active_tx.records[index].generation)
			return 0;
	}
	return 1;
}

static void sv3_forget_active(struct sv3_authority *a, int published)
{
	if (!published)
		a->abandoned_blocks += a->active_blocks;
	else
		a->committed_blocks += a->active_blocks;
	a->in_flight = 0;
	a->active_sequence = 0;
	a->active_blocks = 0;
	a->active_count = 0;
	memset(&a->active_tx, 0, sizeof(a->active_tx));
}

int sv3_abort(struct sv3_authority *a, const struct sv3_tx *tx)
{
	if (!sv3_is_active(a, tx))
		return -ESTALE;
	sv3_forget_active(a, 0);
	return 0;
}

/*
 * Both raw fallbacks and compressed extents share one physical-log allocator.
 * Raw writes never publish on short or failed lower I/O.  The raw marker is
 * held exclusively in volatile mappings, NEVER guessed from media content.
 */
int sv3_finish_raw(struct sv3_authority *a, const struct sv3_tx *tx,
		   const void *raw_page, sv3_u8 completed_blocks, int io_error)
{
	struct sv3_map *old;
	sv3_u32 page;
	int error;

	if (!sv3_is_active(a, tx))
		return -ESTALE;
	if (tx->count != 1 || tx->extent_blocks != 1) {
		error = -EINVAL;
		goto fail;
	}
	if (!io_error && completed_blocks == 1 && !raw_page) {
		error = -EINVAL;
		goto fail;
	}
	if (io_error || completed_blocks != 1) {
		error = io_error < 0 ? io_error : -EIO;
		goto fail;
	}
	page = tx->records[0].logical_page;
	if (page >= a->logical_pages) {
		error = -ERANGE;
		goto fail;
	}
	old = &a->maps[page];
	if (old->generation == ~(sv3_u32)0 ||
	    old->generation + 1U != tx->records[0].generation ||
	    a->live_records[tx->start_block] ||
	    a->extent_classes[tx->start_block]) {
		error = -EUCLEAN;
		goto fail;
	}
	if (old->valid &&
	    (old->start_block >= a->physical_blocks ||
	     !sv3_legal_class(old->extent_blocks) ||
	     a->extent_classes[old->start_block] != old->extent_blocks ||
	     !a->live_records[old->start_block])) {
		error = -EUCLEAN;
		goto fail;
	}
	a->live_records[tx->start_block] = 1;
	a->extent_classes[tx->start_block] = 1;
	if (old->valid)
		a->live_records[old->start_block]--;
	*old = (struct sv3_map){
		.start_block = tx->start_block,
		.sequence = tx->sequence,
		.generation = tx->records[0].generation,
		.raw_crc32c = sv3_crc32c_bytes(raw_page, SV3_BLOCK_BYTES),
		.payload_length = SV3_BLOCK_BYTES,
		.extent_blocks = 1,
		.record_index = 0,
		.raw = 1,
		.valid = 1,
	};
	sv3_forget_active(a, 1);
	return 0;
fail:
	sv3_forget_active(a, 0);
	return error;
}

/*
 * The raw-page format deliberately consumes exactly one full 4KiB lower
 * block; any on-media checksum would force a second write. The volatile
 * mapping authority retains the CRC32C instead. This is NOT persistent
 * metadata and does not provide crash recovery.
 */
int sv3_verify_raw(const struct sv3_authority *a, sv3_u32 logical_page,
		   const void *raw_page)
{
	const struct sv3_map *m;

	if (!a || !a->maps || !raw_page || logical_page >= a->logical_pages)
		return -EINVAL;
	m = &a->maps[logical_page];
	if (!m->valid || !m->raw || m->extent_blocks != 1 ||
	    m->payload_length != SV3_BLOCK_BYTES ||
	    m->start_block >= a->physical_blocks ||
	    a->extent_classes[m->start_block] != 1 ||
	    !a->live_records[m->start_block])
		return -EUCLEAN;
	if (sv3_crc32c_bytes(raw_page, SV3_BLOCK_BYTES) != m->raw_crc32c)
		return -EBADMSG;
	return 0;
}

int sv3_discard_page(struct sv3_authority *a, sv3_u32 logical_page)
{
	struct sv3_map *old;
	sv3_u32 generation;

	if (!a || !a->maps || logical_page >= a->logical_pages)
		return -EINVAL;
	if (a->in_flight)
		return -EBUSY;
	old = &a->maps[logical_page];
	if (old->generation == ~(sv3_u32)0)
		return -EOVERFLOW;
	if (old->valid &&
	    (old->start_block >= a->physical_blocks ||
	     !sv3_legal_class(old->extent_blocks) ||
	     a->extent_classes[old->start_block] != old->extent_blocks ||
	     !a->live_records[old->start_block]))
		return -EUCLEAN;
	generation = old->generation + 1U;
	if (old->valid)
		a->live_records[old->start_block]--;
	memset(old, 0, sizeof(*old));
	old->generation = generation;
	return 0;
}

static sv3_u32 sv3_disk_sequence(const sv3_u8 *bytes)
{
	/* Sequence bytes 8-11, always LE, no unaligned u32 access. */
	return (sv3_u32)bytes[8] | ((sv3_u32)bytes[9] << 8) |
		((sv3_u32)bytes[10] << 16) | ((sv3_u32)bytes[11] << 24);
}

int sv3_finish(struct sv3_authority *a, const struct sv3_tx *tx,
	       const void *extent, sv3_u32 bytes_total,
	       sv3_u8 completed_blocks, int io_error)
{
	const sv3_u8 *image = extent;
	sv3_u16 payload_lengths[SV3_MAX_RECORDS] = { 0 };
	sv3_u8 index;
	int error = 0;

	if (!sv3_is_active(a, tx))
		return -ESTALE;
	if (io_error || completed_blocks != tx->extent_blocks ||
	    bytes_total != (sv3_u32)tx->extent_blocks * SV3_BLOCK_BYTES ||
	    !image) {
		error = io_error < 0 ? io_error : -EIO;
		goto fail;
	}
	error = sv3_validate(image, bytes_total);
	if (error)
		goto fail;
	if (image[7] != tx->count || sv3_disk_sequence(image) != tx->sequence) {
		error = -EUCLEAN;
		goto fail;
	}

	/*
	 * Phase 1. All metadata, payload CRC32Cs, generations and old liveness
	 * validated. No map is mutated during this pass.
	 */
	for (index = 0; index < tx->count; ++index) {
		struct sv3_decoded decoded;
		const sv3_u8 *payload;
		const struct sv3_map *old;
		sv3_u32 logical = tx->records[index].logical_page;
		sv3_u8 prior = 0;
		sv3_u8 j;

		error = sv3_lookup(image, bytes_total, index, &decoded, &payload);
		if (error)
			goto fail;
		payload_lengths[index] = decoded.payload_length;
		if (!payload_lengths[index] ||
		    payload_lengths[index] > SV3_MAX_COMPRESSED) {
			error = -EUCLEAN;
			goto fail;
		}
		if (logical >= a->logical_pages ||
		    decoded.logical_page != logical ||
		    decoded.generation != tx->records[index].generation) {
			error = -EUCLEAN;
			goto fail;
		}
		old = &a->maps[logical];
		if (old->generation == ~(sv3_u32)0 ||
		    old->generation + 1U != decoded.generation) {
			error = -ESTALE;
			goto fail;
		}
		if (!old->valid)
			continue;
		if (old->start_block >= a->physical_blocks ||
		    !sv3_legal_class(old->extent_blocks) ||
		    a->extent_classes[old->start_block] != old->extent_blocks) {
			error = -EUCLEAN;
			goto fail;
		}
		for (j = 0; j <= index; ++j) {
			const struct sv3_map *earlier_old =
				&a->maps[tx->records[j].logical_page];

			if (earlier_old->valid &&
			    earlier_old->start_block == old->start_block)
				prior++;
		}
		if (a->live_records[old->start_block] < prior) {
			error = -EUCLEAN;
			goto fail;
		}
	}
	if (a->live_records[tx->start_block] ||
	    a->extent_classes[tx->start_block]) {
		error = -EUCLEAN;
		goto fail;
	}

	/*
	 * Phase 2. The single ordered worker owns ALL mapping publication.
	 * A failed physical write or a malformed sibling leaves old authority
	 * untouched, even when an earlier block completed successfully.
	 */
	a->live_records[tx->start_block] = tx->count;
	a->extent_classes[tx->start_block] = tx->extent_blocks;
	for (index = 0; index < tx->count; ++index) {
		sv3_u32 logical = tx->records[index].logical_page;
		struct sv3_map *entry = &a->maps[logical];

		if (entry->valid)
			a->live_records[entry->start_block]--;
		*entry = (struct sv3_map){
			.start_block = tx->start_block,
			.sequence = tx->sequence,
			.generation = tx->records[index].generation,
			.payload_length = payload_lengths[index],
			.extent_blocks = tx->extent_blocks,
			.record_index = index,
			.valid = 1,
		};
	}
	sv3_forget_active(a, 1);
	return 0;
fail:
	sv3_forget_active(a, 0);
	return error;
}

int sv3_read_authoritative(const struct sv3_authority *a,
			   sv3_u32 logical_page, const struct sv3_map *observed,
			   const void *extent, sv3_u32 bytes_total,
			   struct sv3_decoded *decoded,
			   const sv3_u8 **payload)
{
	const struct sv3_map *current;
	int error;

	if (!a || !observed || !decoded || !payload ||
	    logical_page >= a->logical_pages)
		return -EINVAL;
	current = &a->maps[logical_page];
	if (!current->valid || !observed->valid ||
	    current->start_block != observed->start_block ||
	    current->sequence != observed->sequence ||
	    current->generation != observed->generation ||
	    current->extent_blocks != observed->extent_blocks ||
	    current->record_index != observed->record_index ||
	    current->payload_length != observed->payload_length)
		return -ESTALE;
	if (current->raw)
		return -EOPNOTSUPP;
	if (!extent ||
	    bytes_total != (sv3_u32)current->extent_blocks * SV3_BLOCK_BYTES)
		return -EINVAL;
	error = sv3_lookup(extent, bytes_total, current->record_index,
			   decoded, payload);
	if (error)
		return error;
	if (decoded->logical_page != logical_page ||
	    decoded->generation != current->generation ||
	    decoded->payload_length != current->payload_length ||
	    sv3_disk_sequence(extent) != current->sequence) {
		*decoded = (struct sv3_decoded){ 0 };
		*payload = NULL;
		return -EUCLEAN;
	}
	return 0;
}
