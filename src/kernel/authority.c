// SPDX-License-Identifier: GPL-2.0-only
#include "authority.h"
#include "gc-cost.h"

#ifdef __KERNEL__
#include <linux/errno.h>
#include <linux/ktime.h>
#include <linux/string.h>
#else
#include <errno.h>
#include <string.h>
#endif

static unsigned long long swapz_authority_now_ns(void)
{
#ifdef __KERNEL__
	return ktime_get_ns();
#else
	return 0;
#endif
}

static swapz_u32 swapz_publish_crc32c(struct swapz_authority *a,
				      const void *bytes, swapz_u32 length)
{
	unsigned long long start = swapz_authority_now_ns();
	swapz_u32 crc = swapz_crc32c_bytes(bytes, length);
	unsigned long long end = swapz_authority_now_ns();

	if (end >= start)
		a->publish_crc_wall_ns += end - start;
	return crc;
}

static swapz_u32 swapz_batch_snapshot_crc32c(struct swapz_authority *a,
					     const struct swapz_tx *tx,
					     unsigned long long *phase_wall_ns)
{
	unsigned long long start = swapz_authority_now_ns();
	swapz_u32 crc = swapz_crc32c_bytes(tx, sizeof(*tx));
	unsigned long long end = swapz_authority_now_ns();

	if (end >= start) {
		unsigned long long elapsed = end - start;

		a->batch_snapshot_crc_wall_ns += elapsed;
		*phase_wall_ns += elapsed;
	}
	return crc;
}

static int swapz_legal_class(swapz_u8 blocks)
{
	return blocks == 1U || blocks == 2U || blocks == 4U;
}

static int swapz_gc_accounting_enabled(const struct swapz_authority *a)
{
	return a->segment_gc_live_bytes || a->segment_gc_io_cost ||
	       a->segment_gc_min_live_blocks;
}

static int swapz_gc_account_costs(const struct swapz_authority *a,
				  const struct swapz_map *m,
				  swapz_u32 *segment,
				  swapz_u32 *bytes,
				  swapz_u32 *io_cost,
				  swapz_u16 *min_blocks)
{
	swapz_u8 min;

	if (!swapz_gc_accounting_enabled(a))
		return 0;
	if (!a->segment_gc_live_bytes || !a->segment_gc_io_cost ||
	    !a->segment_gc_min_live_blocks || !a->segment_mapped_pages ||
	    !m || !m->valid || m->start_block >= a->physical_blocks)
		return -EUCLEAN;
	*segment = m->start_block / SWAPZ_SEGMENT_BLOCKS;
	if (*segment >= a->segment_count)
		return -EUCLEAN;
	*bytes = swapz_gc_live_byte_cost(m);
	*io_cost = swapz_gc_estimated_io_cost(m);
	min = swapz_gc_min_live_blocks(m);
	if (!*bytes || !*io_cost)
		return -EUCLEAN;
	*min_blocks = min;
	return 0;
}

static int swapz_gc_account_adjust_checked(struct swapz_authority *a,
					   const struct swapz_map *m,
					   int add)
{
	swapz_u32 segment, bytes, io_cost;
	swapz_u16 min_blocks;
	int error;

	if (!swapz_gc_accounting_enabled(a))
		return 0;
	error = swapz_gc_account_costs(a, m, &segment, &bytes, &io_cost,
				       &min_blocks);
	if (error)
		return error;
	if (add) {
		if (a->segment_gc_live_bytes[segment] > ~(swapz_u32)0 - bytes ||
		    a->segment_gc_io_cost[segment] > ~(swapz_u32)0 - io_cost ||
		    a->segment_gc_min_live_blocks[segment] >
			    (swapz_u16)~0U - min_blocks)
			return -EOVERFLOW;
		a->segment_gc_live_bytes[segment] += bytes;
		a->segment_gc_io_cost[segment] += io_cost;
		a->segment_gc_min_live_blocks[segment] += min_blocks;
	} else {
		if (a->segment_gc_live_bytes[segment] < bytes ||
		    a->segment_gc_io_cost[segment] < io_cost ||
		    a->segment_gc_min_live_blocks[segment] < min_blocks)
			return -EUCLEAN;
		a->segment_gc_live_bytes[segment] -= bytes;
		a->segment_gc_io_cost[segment] -= io_cost;
		a->segment_gc_min_live_blocks[segment] -= min_blocks;
	}
	return 0;
}

static void swapz_gc_account_adjust_unchecked(struct swapz_authority *a,
					      const struct swapz_map *m,
					      int add)
{
	swapz_u32 segment, bytes, io_cost;
	swapz_u16 min_blocks;

	if (!swapz_gc_accounting_enabled(a) || !m || !m->valid)
		return;
	if (swapz_gc_account_costs(a, m, &segment, &bytes, &io_cost,
				   &min_blocks))
		return;
	if (add) {
		a->segment_gc_live_bytes[segment] += bytes;
		a->segment_gc_io_cost[segment] += io_cost;
		a->segment_gc_min_live_blocks[segment] += min_blocks;
	} else {
		a->segment_gc_live_bytes[segment] -= bytes;
		a->segment_gc_io_cost[segment] -= io_cost;
		a->segment_gc_min_live_blocks[segment] -= min_blocks;
	}
}

static int swapz_gc_account_transition_preflight(struct swapz_authority *a,
						 const struct swapz_map *old,
						 const struct swapz_map *new_map)
{
	int error;

	if (!swapz_gc_accounting_enabled(a))
		return 0;
	if (old && old->valid) {
		error = swapz_gc_account_adjust_checked(a, old, 0);
		if (error)
			return error;
	}
	if (new_map && new_map->valid) {
		error = swapz_gc_account_adjust_checked(a, new_map, 1);
		if (error) {
			if (old && old->valid)
				swapz_gc_account_adjust_unchecked(a, old, 1);
			return error;
		}
		swapz_gc_account_adjust_unchecked(a, new_map, 0);
	}
	if (old && old->valid)
		swapz_gc_account_adjust_unchecked(a, old, 1);
	return 0;
}

static void swapz_gc_account_transition_apply(struct swapz_authority *a,
					      const struct swapz_map *old,
					      const struct swapz_map *new_map)
{
	if (old && old->valid)
		swapz_gc_account_adjust_unchecked(a, old, 0);
	if (new_map && new_map->valid)
		swapz_gc_account_adjust_unchecked(a, new_map, 1);
}

static int swapz_gc_account_batch_preflight(struct swapz_authority *a,
					    const struct swapz_tx *tx,
					    const swapz_u16 *payload_lengths)
{
	swapz_u8 removed = 0, added = 0, index;
	int error = 0;

	if (!swapz_gc_accounting_enabled(a))
		return 0;
	for (index = 0; index < tx->count; ++index) {
		const struct swapz_map *old =
			&a->maps[tx->records[index].logical_page];

		if (old->valid) {
			error = swapz_gc_account_adjust_checked(a, old, 0);
			if (error)
				goto restore;
		}
		removed = index + 1U;
	}
	for (index = 0; index < tx->count; ++index) {
		struct swapz_map candidate = {
			.start_block = tx->start_block,
			.payload_length = payload_lengths[index],
			.extent_blocks = tx->extent_blocks,
			.valid = 1,
		};

		error = swapz_gc_account_adjust_checked(a, &candidate, 1);
		if (error)
			goto restore;
		added = index + 1U;
	}
restore:
	for (index = 0; index < added; ++index) {
		struct swapz_map candidate = {
			.start_block = tx->start_block,
			.payload_length = payload_lengths[index],
			.extent_blocks = tx->extent_blocks,
			.valid = 1,
		};

		swapz_gc_account_adjust_unchecked(a, &candidate, 0);
	}
	for (index = 0; index < removed; ++index) {
		const struct swapz_map *old =
			&a->maps[tx->records[index].logical_page];

		if (old->valid)
			swapz_gc_account_adjust_unchecked(a, old, 1);
	}
	return error;
}

int swapz_authority_init(struct swapz_authority *a,
		       struct swapz_map *maps, swapz_u16 *live_records,
		       swapz_u8 *extent_classes, swapz_u32 logical_pages,
		       swapz_u32 physical_blocks)
{
	swapz_u32 reserve;

	if (!a || !maps || !live_records || !extent_classes ||
	    !logical_pages || physical_blocks < 3U * SWAPZ_SEGMENT_BLOCKS ||
	    physical_blocks % SWAPZ_SEGMENT_BLOCKS)
		return -EINVAL;
	reserve = (logical_pages / 4U) + (logical_pages % 4U != 0);
	if (reserve < 2U * SWAPZ_SEGMENT_BLOCKS)
		reserve = 2U * SWAPZ_SEGMENT_BLOCKS;
	if (reserve >= physical_blocks ||
	    logical_pages > ((physical_blocks - reserve) /
			     SWAPZ_SEGMENT_BLOCKS) * SWAPZ_SEGMENT_BLOCKS)
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
	a->open_segment = ~(swapz_u32)0;
	a->gc_forbidden_open = ~(swapz_u32)0;
	a->gc_forbidden_victim = ~(swapz_u32)0;
	a->gc_destination = ~(swapz_u32)0;
	a->batch_segment = ~(swapz_u32)0;
	a->next_sequence = 1;
	return 0;
}

/*
 * The safe, strictly limited first swapz GC step: reuse only wholly-dead
 * 1MiB segments.  A live object is NEVER copied or overwritten here.
 *
 * Each candidate is checked against BOTH physical live-record counts and
 * all valid logical mappings, because a corrupt refcount must not cause
 * silent live-data overwrite.  No segment in the fixed reserve tail is used.
 * One ordered worker owns maps, segment metadata and the active write.
 */
static int swapz_pick_dead_segment(struct swapz_authority *a)
{
	swapz_u32 count = a->segment_foreground ?
			a->segment_count :
			(a->gc_allocation ?
			 a->physical_blocks :
			 a->physical_blocks - a->reserve_blocks) /
			SWAPZ_SEGMENT_BLOCKS;
	swapz_u32 scan;

	if (!count)
		return -ENOSPC;
	for (scan = 0; scan < count; ++scan) {
		swapz_u32 segment = (a->next_segment_probe + scan) % count;
		swapz_u32 start = segment * SWAPZ_SEGMENT_BLOCKS;
		swapz_u32 off, logical, live_total = 0;
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
		/*
		 * In rotating mode a GC destination must be one of the
		 * reserved, entirely dead segments. Foreground allocation
		 * must never consume reserved space. Once GC has begun it
		 * may NOT spill into another reserve segment: a complete
		 * handoff needs exactly one destination and one victim.
		 */
		if (a->segment_foreground &&
		    (a->gc_allocation ?
		     (a->segment_foreground[segment] ||
		      a->gc_destination != ~(swapz_u32)0) :
		     !a->segment_foreground[segment]))
			continue;
		for (off = 0; off < SWAPZ_SEGMENT_BLOCKS; ++off) {
			live_total += a->live_records[start + off];
			if (a->extent_classes[start + off])
				used = 1;
		}
		if (a->segment_mapped_pages) {
			if (live_total != a->segment_mapped_pages[segment])
				return -EUCLEAN;
			if (live_total)
				continue;
		} else {
			if (live_total)
				continue;
			for (logical = 0; logical < a->logical_pages; ++logical) {
				const struct swapz_map *map = &a->maps[logical];

				if (!map->valid)
					continue;
				if (map->start_block >= a->physical_blocks)
					return -EUCLEAN;
				if (map->start_block / SWAPZ_SEGMENT_BLOCKS == segment) {
					blocked = 1;
					break;
				}
			}
			if (blocked)
				continue;
		}
		/*
		 * Segment has no authoritative records and no pending writes.
		 * The previous contents are disposable swap bytes, not durable
		 * data. Give the production target one serialized advisory-reclaim
		 * hook before reuse, but only when this segment was written before.
		 */
		if (used && a->dead_segment_recycle) {
			int error = a->dead_segment_recycle(
				a->dead_segment_recycle_opaque, segment);

			if (error)
				return error;
		}
		/* Reuse the WHOLE segment; stage never crosses its edge. */
		memset(a->live_records + start, 0,
		       SWAPZ_SEGMENT_BLOCKS * sizeof(*a->live_records));
		memset(a->extent_classes + start, 0,
		       SWAPZ_SEGMENT_BLOCKS * sizeof(*a->extent_classes));
		if (used)
			a->recycled_dead_segments++;
		a->next_block = start;
		a->open_segment = segment;
		a->next_segment_probe = (segment + 1U) % count;
		return 0;
	}
	return -ENOSPC;
}

/*
 * The original fixed reserve tail is retained for research callers that
 * do not opt in. The production Device Mapper target supplies a
 * persistent per-segment role array so GC can exchange its just-evacuated
 * foreground victim with its fully written reserved destination.
 */
int swapz_enable_segment_rotation(struct swapz_authority *a,
				swapz_u8 *roles, swapz_u32 count)
{
	swapz_u32 i, foreground;

	if (!a || !a->maps || !roles || a->segment_foreground ||
	    a->in_flight || a->gc_allocation || a->next_sequence != 1 ||
	    a->next_block || a->open_segment != ~(swapz_u32)0 ||
	    count != a->physical_blocks / SWAPZ_SEGMENT_BLOCKS)
		return -EINVAL;
	foreground = (a->physical_blocks - a->reserve_blocks) /
		     SWAPZ_SEGMENT_BLOCKS;
	if (foreground < 1 || count - foreground < 2)
		return -ENOSPC;
	for (i = 0; i < count; ++i)
		roles[i] = i < foreground ? 1 : 0;
	a->segment_foreground = roles;
	a->segment_count = count;
	a->gc_destination = ~(swapz_u32)0;
	return 0;
}

int swapz_enable_segment_mapping_counts(struct swapz_authority *a,
				      swapz_u32 *counts, swapz_u32 count)
{
	if (!a || !counts || a->segment_mapped_pages || !a->segment_foreground ||
	    a->in_flight || a->batch_pending || a->gc_allocation ||
	    a->next_block || a->open_segment != ~(swapz_u32)0 ||
	    count != a->segment_count)
		return -EINVAL;
	memset(counts, 0, (size_t)count * sizeof(*counts));
	a->segment_mapped_pages = counts;
	return 0;
}

int swapz_enable_segment_gc_accounting(struct swapz_authority *a,
				     swapz_u32 *live_bytes,
				     swapz_u32 *io_cost,
				     swapz_u16 *min_live_blocks,
				     swapz_u32 count)
{
	if (!a || !live_bytes || !io_cost || !min_live_blocks ||
	    !a->segment_foreground || !a->segment_mapped_pages ||
	    swapz_gc_accounting_enabled(a) || a->in_flight ||
	    a->batch_pending || a->gc_allocation || a->next_block ||
	    a->open_segment != ~(swapz_u32)0 || count != a->segment_count)
		return -EINVAL;
	memset(live_bytes, 0, (size_t)count * sizeof(*live_bytes));
	memset(io_cost, 0, (size_t)count * sizeof(*io_cost));
	memset(min_live_blocks, 0, (size_t)count * sizeof(*min_live_blocks));
	a->segment_gc_live_bytes = live_bytes;
	a->segment_gc_io_cost = io_cost;
	a->segment_gc_min_live_blocks = min_live_blocks;
	return 0;
}

/*
 * Force relocation into ONE verified dead reserve segment. Do not touch
 * the foreground cursor here: the sole DM worker saves it before GC and
 * restores it on any failure. No lower I/O has occurred if this fails.
 */
int swapz_gc_begin_rotation(struct swapz_authority *a, swapz_u32 victim)
{
	int error;

	if (!a || !a->segment_foreground || a->in_flight ||
	    a->batch_pending || a->gc_allocation || victim >= a->segment_count ||
	    !a->segment_foreground[victim] ||
	    victim == a->open_segment)
		return -EINVAL;
	a->gc_allocation = 1;
	a->gc_forbidden_open = a->open_segment;
	a->gc_forbidden_victim = victim;
	a->gc_destination = ~(swapz_u32)0;
	a->open_segment = ~(swapz_u32)0;
	/*
	 * Keep the circular probe inherited from foreground allocation and the
	 * previous committed rotation. Resetting it to segment zero on every
	 * collection biases destination reuse toward low-numbered reserves.
	 */
	error = swapz_pick_dead_segment(a);
	if (error) {
		/* Caller will restore the saved foreground cursor. */
		a->gc_allocation = 0;
		a->gc_forbidden_open = ~(swapz_u32)0;
		a->gc_forbidden_victim = ~(swapz_u32)0;
		return error;
	}
	a->gc_destination = a->open_segment;
	return 0;
}

/*
 * Commit one evacuated victim -> free reserve, one new GC destination ->
 * foreground. All new physical writes and authority publications have
 * completed before this function is invoked by the sole DM worker.
 * A failed validation must NEVER change roles or re-enable unsafe reuse.
 */
int swapz_gc_commit_rotation(struct swapz_authority *a, swapz_u32 victim)
{
	swapz_u32 dest, logical, block, live_total = 0;

	if (!a || !a->segment_foreground || !a->gc_allocation ||
	    a->in_flight || a->batch_pending || victim >= a->segment_count ||
	    victim != a->gc_forbidden_victim)
		return -EINVAL;
	dest = a->gc_destination;
	if (dest >= a->segment_count ||
	    !a->segment_foreground[victim] ||
	    a->segment_foreground[dest] || dest == victim ||
	    dest == a->gc_forbidden_open ||
	    a->open_segment != dest ||
	    a->next_block <= dest * SWAPZ_SEGMENT_BLOCKS ||
	    a->next_block > (dest + 1U) * SWAPZ_SEGMENT_BLOCKS)
		return -EUCLEAN;
	/*
	 * GC is invoked because foreground allocation needs capacity.
	 * If survivor relocation consumes all 256 destination blocks, the
	 * role exchange would merely rename a FULL reserve segment as
	 * foreground: no new foreground write could succeed. Fail closed
	 * with no role exchange rather than reporting false GC progress.
	 */
	if (a->next_block == (dest + 1U) * SWAPZ_SEGMENT_BLOCKS)
		return -ENOSPC;
	if (a->segment_mapped_pages) {
		if (a->segment_mapped_pages[victim])
			return -EUCLEAN;
	} else {
		for (logical = 0; logical < a->logical_pages; ++logical) {
			const struct swapz_map *m = &a->maps[logical];

			if (m->valid && (m->start_block >= a->physical_blocks ||
			    m->start_block / SWAPZ_SEGMENT_BLOCKS == victim))
				return -EUCLEAN;
		}
	}
	for (block = victim * SWAPZ_SEGMENT_BLOCKS;
	     block < (victim + 1U) * SWAPZ_SEGMENT_BLOCKS; ++block)
		live_total += a->live_records[block];
	if (live_total || (a->segment_mapped_pages &&
			   live_total != a->segment_mapped_pages[victim]))
		return -EUCLEAN;
	/* Commit both roles without further lower I/O or fallible work. */
	a->segment_foreground[dest] = 1;
	a->segment_foreground[victim] = 0;
	a->gc_allocation = 0;
	a->gc_forbidden_open = ~(swapz_u32)0;
	a->gc_forbidden_victim = ~(swapz_u32)0;
	a->gc_destination = ~(swapz_u32)0;
	a->next_segment_probe = (victim + 1U) % a->segment_count;
	/* Deliberately leave OPEN and next_block pointing at GC destination:
	 * subsequent foreground writes use the *same* compacted segment. */
	return 0;
}

int swapz_stage(struct swapz_authority *a, const swapz_u32 *pages,
	      swapz_u8 count, swapz_u8 blocks, struct swapz_tx *out)
{
	swapz_u32 limit, start;
	swapz_u8 index;

	if (!a || !a->maps || !pages || !out ||
	    !swapz_legal_class(blocks) || !count || count > SWAPZ_MAX_RECORDS)
		return -EINVAL;
	if (a->in_flight ||
	    (a->batch_pending && !a->batch_stage_allowed))
		return -EBUSY;
	if (!a->next_sequence || a->next_sequence == ~(swapz_u32)0)
		return -EOVERFLOW;
	/*
	 * A lower-write group has already RESERVED physical extents but none
	 * has been published. Do not change its physical segment underneath
	 * the combined IO; the engine flushes the group on -EAGAIN and retries.
	 */
	if (a->batch_pending) {
		swapz_u32 aligned = (a->next_block + blocks - 1U) &
				  ~(swapz_u32)(blocks - 1U);
		if (!a->reuse_dead_segments ||
		    a->open_segment != a->batch_segment ||
		    aligned >= a->physical_blocks ||
		    blocks > a->physical_blocks - aligned ||
		    aligned / SWAPZ_SEGMENT_BLOCKS != a->batch_segment ||
		    aligned % SWAPZ_SEGMENT_BLOCKS + blocks >
					SWAPZ_SEGMENT_BLOCKS)
			return -EAGAIN;
	}
	for (index = 0; index < count; ++index) {
		swapz_u8 earlier;

		if (pages[index] >= a->logical_pages)
			return -ERANGE;
		if (a->maps[pages[index]].generation == ~(swapz_u32)0)
			return -EOVERFLOW;
		for (earlier = 0; earlier < index; ++earlier) {
			if (pages[earlier] == pages[index])
				return -EEXIST;
		}
	}

	if (!a->reuse_dead_segments) {
		/* Frozen append-only behavior used by the original extent model. */
		limit = a->physical_blocks - a->reserve_blocks;
		if (a->next_block > limit ||
		    blocks - 1U > limit - a->next_block)
			return -ENOSPC;
		start = (a->next_block + blocks - 1U) &
			~(swapz_u32)(blocks - 1U);
		if (start > limit || blocks > limit - start ||
		    start % SWAPZ_SEGMENT_BLOCKS + blocks > SWAPZ_SEGMENT_BLOCKS)
			return -ENOSPC;
	} else {
		limit = a->segment_foreground ? a->physical_blocks :
			((a->gc_allocation ?
			  a->physical_blocks :
			  a->physical_blocks - a->reserve_blocks) /
			 SWAPZ_SEGMENT_BLOCKS) * SWAPZ_SEGMENT_BLOCKS;
		/*
		 * Reuse the OPEN segment only while the entire aligned extent fits.
		 * A crossed segment edge MUST run the mapped-record liveness scan;
		 * merely advancing to the numerically next segment can destroy data
		 * after physical cursor wrap.
		 */
		start = a->next_block;
		if (a->open_segment == ~(swapz_u32)0 ||
		    start >= limit || blocks - 1U > limit - start ||
		    ((start + blocks - 1U) & ~(swapz_u32)(blocks - 1U)) >
				limit - blocks ||
		    (((start + blocks - 1U) & ~(swapz_u32)(blocks - 1U)) /
		     SWAPZ_SEGMENT_BLOCKS) != a->open_segment ||
		    ((start + blocks - 1U) & ~(swapz_u32)(blocks - 1U)) %
				SWAPZ_SEGMENT_BLOCKS + blocks > SWAPZ_SEGMENT_BLOCKS) {
			int error = swapz_pick_dead_segment(a);

			if (error)
				return error;
			start = a->next_block;
		}
		start = (start + blocks - 1U) & ~(swapz_u32)(blocks - 1U);
		if (start >= limit || blocks > limit - start ||
		    start / SWAPZ_SEGMENT_BLOCKS != a->open_segment ||
		    start % SWAPZ_SEGMENT_BLOCKS + blocks > SWAPZ_SEGMENT_BLOCKS)
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

static int swapz_is_active(const struct swapz_authority *a,
			 const struct swapz_tx *tx)
{
	swapz_u8 index;

	if (!a || !tx || !a->in_flight ||
	    tx->start_block != a->active_start ||
	    tx->sequence != a->active_sequence ||
	    tx->extent_blocks != a->active_blocks ||
	    tx->count != a->active_count ||
	    tx->start_block != a->active_tx.start_block ||
	    tx->sequence != a->active_tx.sequence ||
	    tx->extent_blocks != a->active_tx.extent_blocks ||
	    tx->count != a->active_tx.count ||
	    !swapz_legal_class(tx->extent_blocks) ||
	    !tx->count || tx->count > SWAPZ_MAX_RECORDS)
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

/*
 * The sole worker may keep up to 64 staged extents in an isolated
 * preallocated RAM run. Pausing clears the active identity but DOES NOT
 * report success, mutate any logical mapping or free the physical blocks.
 * All paused extents remain reserved in one physical segment.
 */
/*
 * No normal stage/discard/GC operation may enter while lower-batch
 * snapshots exist. The engine calls this explicit serialized wrapper
 * for the second and later reservation of an unpublished group.
 */
int swapz_stage_batch(struct swapz_authority *a, const swapz_u32 *pages,
		    swapz_u8 count, swapz_u8 blocks, struct swapz_tx *tx)
{
	int error;

	if (!a || a->batch_stage_allowed || a->batch_replaying)
		return -EBUSY;
	a->batch_stage_allowed = 1;
	error = swapz_stage(a, pages, count, blocks, tx);
	a->batch_stage_allowed = 0;
	return error;
}

int swapz_batch_pause(struct swapz_authority *a, const struct swapz_tx *tx)
{
	swapz_u32 segment;

	if (!swapz_is_active(a, tx) || !a->reuse_dead_segments ||
	    a->batch_replaying || a->batch_pending >= SWAPZ_MAX_RECORDS)
		return -EINVAL;
	segment = tx->start_block / SWAPZ_SEGMENT_BLOCKS;
	if (a->batch_pending) {
		if (segment != a->batch_segment ||
		    tx->sequence != a->batch_first_sequence + a->batch_pending)
			return -EUCLEAN;
	} else {
		a->batch_first_sequence = tx->sequence;
		a->batch_segment = segment;
		a->batch_consumed = 0;
	}
	a->batch_hashes[a->batch_pending] =
		swapz_batch_snapshot_crc32c(a, tx,
					    &a->batch_pause_crc_wall_ns);
	a->batch_pending++;
	a->in_flight = 0;
	a->active_sequence = 0;
	a->active_blocks = 0;
	a->active_count = 0;
	memset(&a->active_tx, 0, sizeof(a->active_tx));
	return 0;
}

/* A saved snapshot can only be rearmed in exactly increasing staged
 * sequence order. Reusing a stage never fabricates physical completion.
 * The caller MUST subsequently finish/abort the rearmed transaction. */
int swapz_batch_resume(struct swapz_authority *a, const struct swapz_tx *tx)
{
	swapz_u8 i;

	if (!a || !tx || a->in_flight || !a->batch_pending ||
	    a->batch_replaying || tx->sequence != a->batch_first_sequence ||
	    tx->start_block / SWAPZ_SEGMENT_BLOCKS != a->batch_segment ||
	    (tx->extent_blocks != 1 && tx->extent_blocks != 2 &&
	     tx->extent_blocks != 4) ||
	    !tx->count || tx->count > SWAPZ_MAX_RECORDS ||
	    tx->start_block % tx->extent_blocks ||
	    tx->start_block >= a->physical_blocks ||
	    tx->extent_blocks > a->physical_blocks - tx->start_block ||
	    tx->start_block + tx->extent_blocks > a->next_block ||
	    a->batch_consumed >= SWAPZ_MAX_RECORDS ||
	    a->batch_hashes[a->batch_consumed] !=
				swapz_batch_snapshot_crc32c(
					a, tx, &a->batch_resume_crc_wall_ns))
		return -ESTALE;
	for (i = 0; i < tx->count; ++i)
		if (tx->records[i].logical_page >= a->logical_pages ||
		    tx->records[i].generation !=
		    a->maps[tx->records[i].logical_page].generation + 1U)
			return -ESTALE;
	a->active_tx = *tx;
	a->active_start = tx->start_block;
	a->active_sequence = tx->sequence;
	a->active_blocks = tx->extent_blocks;
	a->active_count = tx->count;
	a->in_flight = 1;
	a->batch_replaying = 1;
	return 0;
}

static void swapz_forget_active(struct swapz_authority *a, int published)
{
	if (a->batch_replaying) {
		a->batch_replaying = 0;
		a->batch_pending--;
		a->batch_first_sequence++;
		a->batch_consumed++;
		if (!a->batch_pending) {
			a->batch_segment = ~(swapz_u32)0;
			a->batch_consumed = 0;
		}
	}
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

int swapz_abort(struct swapz_authority *a, const struct swapz_tx *tx)
{
	if (!swapz_is_active(a, tx))
		return -ESTALE;
	swapz_forget_active(a, 0);
	return 0;
}

/*
 * Both raw fallbacks and compressed extents share one physical-log allocator.
 * Raw writes never publish on short or failed lower I/O.  The raw marker is
 * held exclusively in volatile mappings, NEVER guessed from media content.
 */
int swapz_finish_raw(struct swapz_authority *a, const struct swapz_tx *tx,
		   const void *raw_page, swapz_u8 completed_blocks, int io_error)
{
	struct swapz_map *old;
	struct swapz_map new_map;
	swapz_u32 page, old_segment = 0, new_segment;
	int error;

	if (!swapz_is_active(a, tx))
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
	new_segment = tx->start_block / SWAPZ_SEGMENT_BLOCKS;
	if (old->generation == ~(swapz_u32)0 ||
	    old->generation + 1U != tx->records[0].generation ||
	    a->live_records[tx->start_block] ||
	    a->extent_classes[tx->start_block]) {
		error = -EUCLEAN;
		goto fail;
	}
	if (old->valid &&
	    (old->start_block >= a->physical_blocks ||
	     !swapz_legal_class(old->extent_blocks) ||
	     a->extent_classes[old->start_block] != old->extent_blocks ||
	     !a->live_records[old->start_block])) {
		error = -EUCLEAN;
		goto fail;
	}
	new_map = (struct swapz_map){
		.start_block = tx->start_block,
		.sequence = tx->sequence,
		.generation = tx->records[0].generation,
		.raw_crc32c = swapz_publish_crc32c(a, raw_page, SWAPZ_BLOCK_BYTES),
		.payload_length = SWAPZ_BLOCK_BYTES,
		.extent_blocks = 1,
		.record_index = 0,
		.raw = 1,
		.valid = 1,
	};
	if (a->segment_mapped_pages) {
		if (new_segment >= a->segment_count) {
			error = -EUCLEAN;
			goto fail;
		}
		if (old->valid) {
			old_segment = old->start_block / SWAPZ_SEGMENT_BLOCKS;
			if (old_segment >= a->segment_count ||
			    !a->segment_mapped_pages[old_segment]) {
				error = -EUCLEAN;
				goto fail;
			}
		}
		if ((!old->valid || old_segment != new_segment) &&
		    a->segment_mapped_pages[new_segment] == ~(swapz_u32)0) {
			error = -EOVERFLOW;
			goto fail;
		}
	}
	error = swapz_gc_account_transition_preflight(a, old, &new_map);
	if (error)
		goto fail;
	a->live_records[tx->start_block] = 1;
	a->extent_classes[tx->start_block] = 1;
	if (old->valid)
		a->live_records[old->start_block]--;
	if (a->segment_mapped_pages &&
	    (!old->valid || old_segment != new_segment)) {
		if (old->valid)
			a->segment_mapped_pages[old_segment]--;
		a->segment_mapped_pages[new_segment]++;
	}
	swapz_gc_account_transition_apply(a, old, &new_map);
	*old = new_map;
	swapz_forget_active(a, 1);
	return 0;
fail:
	swapz_forget_active(a, 0);
	return error;
}

/*
 * The raw-page format deliberately consumes exactly one full 4KiB lower
 * block; any on-media checksum would force a second write. The volatile
 * mapping authority retains the CRC32C instead. This is NOT persistent
 * metadata and does not provide crash recovery.
 */
int swapz_verify_raw(const struct swapz_authority *a, swapz_u32 logical_page,
		   const void *raw_page)
{
	const struct swapz_map *m;

	if (!a || !a->maps || !raw_page || logical_page >= a->logical_pages)
		return -EINVAL;
	m = &a->maps[logical_page];
	if (!m->valid || !m->raw || m->extent_blocks != 1 ||
	    m->payload_length != SWAPZ_BLOCK_BYTES ||
	    m->start_block >= a->physical_blocks ||
	    a->extent_classes[m->start_block] != 1 ||
	    !a->live_records[m->start_block])
		return -EUCLEAN;
	if (swapz_crc32c_bytes(raw_page, SWAPZ_BLOCK_BYTES) != m->raw_crc32c)
		return -EBADMSG;
	return 0;
}

int swapz_discard_page(struct swapz_authority *a, swapz_u32 logical_page)
{
	struct swapz_map *old;
	swapz_u32 generation, old_segment = 0;

	if (!a || !a->maps || logical_page >= a->logical_pages)
		return -EINVAL;
	if (a->in_flight || a->batch_pending)
		return -EBUSY;
	old = &a->maps[logical_page];
	if (old->generation == ~(swapz_u32)0)
		return -EOVERFLOW;
	if (old->valid &&
	    (old->start_block >= a->physical_blocks ||
	     !swapz_legal_class(old->extent_blocks) ||
	     a->extent_classes[old->start_block] != old->extent_blocks ||
	     !a->live_records[old->start_block]))
		return -EUCLEAN;
	generation = old->generation + 1U;
	if (a->segment_mapped_pages && old->valid) {
		old_segment = old->start_block / SWAPZ_SEGMENT_BLOCKS;
		if (old_segment >= a->segment_count ||
		    !a->segment_mapped_pages[old_segment])
			return -EUCLEAN;
	}
	if (old->valid) {
		int score_error =
			swapz_gc_account_transition_preflight(a, old, NULL);

		if (score_error)
			return score_error;
		a->live_records[old->start_block]--;
		swapz_gc_account_transition_apply(a, old, NULL);
	}
	if (a->segment_mapped_pages && old->valid)
		a->segment_mapped_pages[old_segment]--;
	memset(old, 0, sizeof(*old));
	old->generation = generation;
	return 0;
}

static swapz_u32 swapz_disk_sequence(const swapz_u8 *bytes)
{
	/* Sequence bytes 8-11, always LE, no unaligned u32 access. */
	return (swapz_u32)bytes[8] | ((swapz_u32)bytes[9] << 8) |
		((swapz_u32)bytes[10] << 16) | ((swapz_u32)bytes[11] << 24);
}

int swapz_finish(struct swapz_authority *a, const struct swapz_tx *tx,
	       const void *extent, swapz_u32 bytes_total,
	       swapz_u8 completed_blocks, int io_error)
{
	const swapz_u8 *image = extent;
	swapz_u16 payload_lengths[SWAPZ_MAX_RECORDS] = { 0 };
	swapz_u16 payload_offsets[SWAPZ_MAX_RECORDS] = { 0 };
	swapz_u32 old_segments[SWAPZ_MAX_RECORDS] = { 0 };
	swapz_u32 new_segment, new_additions = 0;
	swapz_u8 index;
	int error = 0;

	if (!swapz_is_active(a, tx))
		return -ESTALE;
	if (io_error || completed_blocks != tx->extent_blocks ||
	    bytes_total != (swapz_u32)tx->extent_blocks * SWAPZ_BLOCK_BYTES ||
	    !image) {
		error = io_error < 0 ? io_error : -EIO;
		goto fail;
	}
	error = swapz_validate(image, bytes_total);
	if (error)
		goto fail;
	new_segment = tx->start_block / SWAPZ_SEGMENT_BLOCKS;
	if (a->segment_mapped_pages && new_segment >= a->segment_count) {
		error = -EUCLEAN;
		goto fail;
	}
	if (image[7] != tx->count || swapz_disk_sequence(image) != tx->sequence) {
		error = -EUCLEAN;
		goto fail;
	}

	/*
	 * Phase 1. All metadata, payload CRC32Cs, generations and old liveness
	 * validated. No map is mutated during this pass.
	 */
	for (index = 0; index < tx->count; ++index) {
		struct swapz_decoded decoded;
		const swapz_u8 *payload;
		const struct swapz_map *old;
		swapz_u32 logical = tx->records[index].logical_page;
		swapz_u8 prior = 0;
		swapz_u8 j;

		/*
		 * The complete immutable image was validated once above. Verify this
		 * record's final payload CRC without reparsing/revalidating every
		 * sibling descriptor on each iteration.
		 */
		error = swapz_lookup_validated_descriptor(image, bytes_total, index,
						       &decoded, &payload);
		if (error)
			goto fail;
		if (swapz_publish_crc32c(a, payload, decoded.payload_length) !=
		    decoded.payload_crc32c) {
			error = -EBADMSG;
			goto fail;
		}
		payload_lengths[index] = decoded.payload_length;
		payload_offsets[index] = decoded.payload_offset;
		if (!payload_lengths[index] ||
		    payload_lengths[index] > SWAPZ_MAX_COMPRESSED) {
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
		if (old->generation == ~(swapz_u32)0 ||
		    old->generation + 1U != decoded.generation) {
			error = -ESTALE;
			goto fail;
		}
		if (!old->valid) {
			if (a->segment_mapped_pages)
				new_additions++;
			continue;
		}
		if (old->start_block >= a->physical_blocks ||
		    !swapz_legal_class(old->extent_blocks) ||
		    a->extent_classes[old->start_block] != old->extent_blocks) {
			error = -EUCLEAN;
			goto fail;
		}
		for (j = 0; j <= index; ++j) {
			const struct swapz_map *earlier_old =
				&a->maps[tx->records[j].logical_page];

			if (earlier_old->valid &&
			    earlier_old->start_block == old->start_block)
				prior++;
		}
		if (a->live_records[old->start_block] < prior) {
			error = -EUCLEAN;
			goto fail;
		}
		if (a->segment_mapped_pages) {
			swapz_u8 segment_prior = 0;

			old_segments[index] =
				old->start_block / SWAPZ_SEGMENT_BLOCKS;
			if (old_segments[index] >= a->segment_count) {
				error = -EUCLEAN;
				goto fail;
			}
			for (j = 0; j <= index; ++j) {
				const struct swapz_map *earlier_old =
					&a->maps[tx->records[j].logical_page];

				if (earlier_old->valid &&
				    earlier_old->start_block / SWAPZ_SEGMENT_BLOCKS ==
						old_segments[index])
					segment_prior++;
			}
			if (a->segment_mapped_pages[old_segments[index]] <
			    segment_prior) {
				error = -EUCLEAN;
				goto fail;
			}
			if (old_segments[index] != new_segment)
				new_additions++;
		}
	}
	if (a->segment_mapped_pages &&
	    new_additions > ~(swapz_u32)0 -
			a->segment_mapped_pages[new_segment]) {
		error = -EOVERFLOW;
		goto fail;
	}
	error = swapz_gc_account_batch_preflight(a, tx, payload_lengths);
	if (error)
		goto fail;
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
		swapz_u32 logical = tx->records[index].logical_page;
		struct swapz_map *entry = &a->maps[logical];
		struct swapz_map new_map = {
			.start_block = tx->start_block,
			.sequence = tx->sequence,
			.generation = tx->records[index].generation,
			.payload_length = payload_lengths[index],
			.payload_offset = payload_offsets[index],
			.extent_blocks = tx->extent_blocks,
			.record_index = index,
			.valid = 1,
		};

		if (entry->valid)
			a->live_records[entry->start_block]--;
		swapz_gc_account_transition_apply(a, entry, &new_map);
		if (a->segment_mapped_pages) {
			if (entry->valid && old_segments[index] != new_segment)
				a->segment_mapped_pages[old_segments[index]]--;
			if (!entry->valid || old_segments[index] != new_segment)
				a->segment_mapped_pages[new_segment]++;
		}
		*entry = new_map;
	}
	swapz_forget_active(a, 1);
	return 0;
fail:
	swapz_forget_active(a, 0);
	return error;
}

static int swapz_read_observed_authority(
			   const struct swapz_authority *a,
			   swapz_u32 logical_page, const struct swapz_map *observed,
			   const void *extent, swapz_u32 bytes_total,
			   const struct swapz_map **current_out)
{
	const struct swapz_map *current_map;

	if (!a || !observed || !current_out ||
	    logical_page >= a->logical_pages)
		return -EINVAL;
	current_map = &a->maps[logical_page];
	if (!current_map->valid || !observed->valid ||
	    current_map->start_block != observed->start_block ||
	    current_map->sequence != observed->sequence ||
	    current_map->generation != observed->generation ||
	    current_map->extent_blocks != observed->extent_blocks ||
	    current_map->record_index != observed->record_index ||
	    current_map->payload_length != observed->payload_length ||
	    current_map->payload_offset != observed->payload_offset)
		return -ESTALE;
	if (current_map->raw)
		return -EOPNOTSUPP;
	if (!extent ||
	    bytes_total != (swapz_u32)current_map->extent_blocks * SWAPZ_BLOCK_BYTES)
		return -EINVAL;
	*current_out = current_map;
	return 0;
}

int swapz_read_authoritative_peeked(const struct swapz_authority *a,
				  swapz_u32 logical_page,
				  const struct swapz_map *observed,
				  const void *extent, swapz_u32 bytes_total,
				  const struct swapz_decoded *peeked,
				  const swapz_u8 **payload)
{
	const struct swapz_map *current_map;
	const swapz_u8 *stored;
	int error;

	if (!peeked || !payload)
		return -EINVAL;
	*payload = NULL;
	error = swapz_read_observed_authority(a, logical_page, observed,
					   extent, bytes_total, &current_map);
	if (error)
		return error;
	/*
	 * swapz_peek() already validated the complete metadata block before the
	 * engine fetched any missing payload blocks. read_scratch is owned by
	 * the serialized worker, so only those payload bytes can change before
	 * this call. Recheck volatile authority and on-media sequence, then
	 * validate the payload CRC exactly once without reparsing metadata.
	 */
	if (peeked->logical_page != logical_page ||
	    peeked->generation != current_map->generation ||
	    peeked->payload_length != current_map->payload_length ||
	    peeked->payload_offset != current_map->payload_offset ||
	    !peeked->payload_length ||
	    peeked->payload_length > SWAPZ_MAX_COMPRESSED ||
	    peeked->payload_offset >= bytes_total ||
	    peeked->payload_length > bytes_total - peeked->payload_offset ||
	    swapz_disk_sequence(extent) != current_map->sequence)
		return -EUCLEAN;
	stored = (const swapz_u8 *)extent + peeked->payload_offset;
	if (swapz_crc32c_bytes(stored, peeked->payload_length) !=
	    peeked->payload_crc32c)
		return -EBADMSG;
	*payload = stored;
	return 0;
}
