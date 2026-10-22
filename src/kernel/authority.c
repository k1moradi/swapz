// SPDX-License-Identifier: GPL-2.0-only
#include "authority.h"
#include "gc-cost.h"

#ifdef __KERNEL__
#include <linux/errno.h>
#include <linux/ktime.h>
#include <linux/stddef.h>
#include <linux/string.h>
#else
#include <errno.h>
#include <stddef.h>
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

static int swapz_finish_alloc_probe(struct swapz_authority *a,
				    unsigned long long start, int result)
{
	unsigned long long end = swapz_authority_now_ns();

	if (end >= start)
		a->alloc_probe_wall_ns += end - start;
	return result;
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

/*
 * Only the fixed header plus count authoritative record identities participate
 * in staged-transaction ownership. Keep caller-visible transactions fully
 * initialized in swapz_stage(), but avoid repeatedly copying/clearing the
 * unused record tail in the authority-owned immutable snapshot.
 */
static size_t swapz_tx_active_bytes(swapz_u8 count)
{
	if (count > SWAPZ_MAX_RECORDS)
		count = SWAPZ_MAX_RECORDS;
	return offsetof(struct swapz_tx, records) +
		(size_t)count * sizeof(((struct swapz_tx *)0)->records[0]);
}

static swapz_u32 swapz_batch_snapshot_crc32c(struct swapz_authority *a,
					     const struct swapz_tx *tx,
					     unsigned long long *phase_wall_ns)
{
	unsigned long long start = swapz_authority_now_ns();
	swapz_u32 active_bytes = (swapz_u32)swapz_tx_active_bytes(tx->count);
	swapz_u32 crc = swapz_crc32c_bytes(tx, active_bytes);
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

static int swapz_segment_page_lists_enabled(const struct swapz_authority *a)
{
	return a->segment_first_page || a->segment_last_page ||
	       a->page_prev_in_segment || a->page_next_in_segment;
}

static int swapz_segment_page_lists_complete(const struct swapz_authority *a)
{
	return a->segment_first_page && a->segment_last_page &&
	       a->page_prev_in_segment && a->page_next_in_segment &&
	       a->segment_mapped_pages;
}

static int swapz_page_list_validate_segment(const struct swapz_authority *a,
					    swapz_u32 segment)
{
	const swapz_u32 none = ~(swapz_u32)0;
	swapz_u32 first, last;

	if (!swapz_segment_page_lists_enabled(a))
		return 0;
	if (!swapz_segment_page_lists_complete(a) ||
	    segment >= a->segment_count)
		return -EUCLEAN;
	first = a->segment_first_page[segment];
	last = a->segment_last_page[segment];
	if (!a->segment_mapped_pages[segment])
		return first == none && last == none ? 0 : -EUCLEAN;
	if (first >= a->logical_pages || last >= a->logical_pages)
		return -EUCLEAN;
	if (!a->maps[first].valid || !a->maps[last].valid ||
	    a->maps[first].start_block / SWAPZ_SEGMENT_BLOCKS != segment ||
	    a->maps[last].start_block / SWAPZ_SEGMENT_BLOCKS != segment ||
	    a->page_prev_in_segment[first] != none ||
	    a->page_next_in_segment[last] != none)
		return -EUCLEAN;
	return 0;
}

static int swapz_page_list_validate_entry(const struct swapz_authority *a,
					  swapz_u32 logical)
{
	const swapz_u32 none = ~(swapz_u32)0;
	const struct swapz_map *m;
	swapz_u32 segment, prev, next;

	if (!swapz_segment_page_lists_enabled(a))
		return 0;
	if (!swapz_segment_page_lists_complete(a) ||
	    logical >= a->logical_pages)
		return -EUCLEAN;
	m = &a->maps[logical];
	if (!m->valid)
		return a->page_prev_in_segment[logical] == none &&
		       a->page_next_in_segment[logical] == none ? 0 : -EUCLEAN;
	if (m->start_block >= a->physical_blocks)
		return -EUCLEAN;
	segment = m->start_block / SWAPZ_SEGMENT_BLOCKS;
	if (swapz_page_list_validate_segment(a, segment))
		return -EUCLEAN;
	prev = a->page_prev_in_segment[logical];
	next = a->page_next_in_segment[logical];
	if (prev == none) {
		if (a->segment_first_page[segment] != logical)
			return -EUCLEAN;
	} else if (prev >= a->logical_pages || !a->maps[prev].valid ||
		   a->maps[prev].start_block / SWAPZ_SEGMENT_BLOCKS != segment ||
		   a->page_next_in_segment[prev] != logical) {
		return -EUCLEAN;
	}
	if (next == none) {
		if (a->segment_last_page[segment] != logical)
			return -EUCLEAN;
	} else if (next >= a->logical_pages || !a->maps[next].valid ||
		   a->maps[next].start_block / SWAPZ_SEGMENT_BLOCKS != segment ||
		   a->page_prev_in_segment[next] != logical) {
		return -EUCLEAN;
	}
	return 0;
}

static void swapz_page_list_unlink_unchecked(struct swapz_authority *a,
					     swapz_u32 logical,
					     swapz_u32 segment)
{
	const swapz_u32 none = ~(swapz_u32)0;
	swapz_u32 prev = a->page_prev_in_segment[logical];
	swapz_u32 next = a->page_next_in_segment[logical];

	if (prev == none)
		a->segment_first_page[segment] = next;
	else
		a->page_next_in_segment[prev] = next;
	if (next == none)
		a->segment_last_page[segment] = prev;
	else
		a->page_prev_in_segment[next] = prev;
	a->page_prev_in_segment[logical] = none;
	a->page_next_in_segment[logical] = none;
}

static void swapz_page_list_append_unchecked(struct swapz_authority *a,
					     swapz_u32 logical,
					     swapz_u32 segment)
{
	const swapz_u32 none = ~(swapz_u32)0;
	swapz_u32 last = a->segment_last_page[segment];

	a->page_prev_in_segment[logical] = last;
	a->page_next_in_segment[logical] = none;
	if (last == none)
		a->segment_first_page[segment] = logical;
	else
		a->page_next_in_segment[last] = logical;
	a->segment_last_page[segment] = logical;
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
static int swapz_claim_dead_segment(struct swapz_authority *a,
				    swapz_u32 segment,
				    unsigned long long probe_start)
{
	swapz_u32 start = segment * SWAPZ_SEGMENT_BLOCKS;
	swapz_u32 off, logical, live_total = 0;
	int used = 0, blocked = 0;

	if (swapz_page_list_validate_segment(a, segment))
		return swapz_finish_alloc_probe(a, probe_start, -EUCLEAN);
	a->alloc_probe_full_scans++;
	for (off = 0; off < SWAPZ_SEGMENT_BLOCKS; ++off) {
		live_total += a->live_records[start + off];
		if (a->extent_classes[start + off])
			used = 1;
	}
	if (a->segment_mapped_pages) {
		if (live_total)
			return swapz_finish_alloc_probe(a, probe_start, -EUCLEAN);
	} else {
		if (live_total)
			return -EAGAIN;
		for (logical = 0; logical < a->logical_pages; ++logical) {
			const struct swapz_map *map = &a->maps[logical];

			if (!map->valid)
				continue;
			if (map->start_block >= a->physical_blocks)
				return swapz_finish_alloc_probe(a, probe_start,
							 -EUCLEAN);
			if (map->start_block / SWAPZ_SEGMENT_BLOCKS == segment) {
				blocked = 1;
				break;
			}
		}
		if (blocked)
			return -EAGAIN;
	}
	if (used && a->dead_segment_recycle) {
		int error = a->dead_segment_recycle(
			a->dead_segment_recycle_opaque, segment);

		if (error)
			return swapz_finish_alloc_probe(a, probe_start, error);
	}
	memset(a->live_records + start, 0,
	       SWAPZ_SEGMENT_BLOCKS * sizeof(*a->live_records));
	memset(a->extent_classes + start, 0,
	       SWAPZ_SEGMENT_BLOCKS * sizeof(*a->extent_classes));
	if (used)
		a->recycled_dead_segments++;
	if (a->segment_program_counts &&
	    a->segment_program_counts[segment] != ~(swapz_u32)0)
		a->segment_program_counts[segment]++;
	a->next_block = start;
	a->open_segment = segment;
	a->next_segment_probe = (segment + 1U) %
		(a->segment_foreground ? a->segment_count :
		 (a->gc_allocation ? a->physical_blocks :
		  a->physical_blocks - a->reserve_blocks) /
		 SWAPZ_SEGMENT_BLOCKS);
	return swapz_finish_alloc_probe(a, probe_start, 0);
}

static int swapz_dead_segment_eligible(const struct swapz_authority *a,
				       swapz_u32 segment)
{
	if (a->gc_allocation &&
	    (segment == a->gc_forbidden_open ||
	     segment == a->gc_forbidden_victim))
		return 0;
	if (a->segment_foreground &&
	    (a->gc_allocation ?
	     (a->segment_foreground[segment] ||
	      a->gc_destination != ~(swapz_u32)0) :
	     !a->segment_foreground[segment]))
		return 0;
	return !a->segment_mapped_pages ||
	       !a->segment_mapped_pages[segment];
}

/*
 * Reuse only wholly-dead 1MiB segments. Exact mapped-page counts reject
 * known-live candidates before the 256-block fail-closed verification scan.
 * Optional logical-open balancing scans only the O(segments) sidecars and
 * chooses the least-opened eligible destination; this is allocator fairness,
 * not a claim about NAND wear.
 */
static int swapz_pick_dead_segment(struct swapz_authority *a)
{
	swapz_u32 count = a->segment_foreground ?
			a->segment_count :
			(a->gc_allocation ?
			 a->physical_blocks :
			 a->physical_blocks - a->reserve_blocks) /
			SWAPZ_SEGMENT_BLOCKS;
	unsigned long long probe_start = swapz_authority_now_ns();
	swapz_u32 scan;

	if (!count)
		return swapz_finish_alloc_probe(a, probe_start, -ENOSPC);
	if (a->balance_segment_opens && a->segment_mapped_pages &&
	    a->segment_program_counts) {
		swapz_u32 selected = ~(swapz_u32)0;
		swapz_u32 best = ~(swapz_u32)0;

		for (scan = 0; scan < count; ++scan) {
			swapz_u32 segment =
				(a->next_segment_probe + scan) % count;
			swapz_u32 programs;

			a->alloc_probe_segments++;
			if (!swapz_dead_segment_eligible(a, segment))
				continue;
			programs = a->segment_program_counts[segment];
			if (programs < best) {
				selected = segment;
				best = programs;
				if (!programs)
					break;
			}
		}
		if (selected == ~(swapz_u32)0)
			return swapz_finish_alloc_probe(a, probe_start, -ENOSPC);
		return swapz_claim_dead_segment(a, selected, probe_start);
	}
	for (scan = 0; scan < count; ++scan) {
		swapz_u32 segment = (a->next_segment_probe + scan) % count;
		int result;

		a->alloc_probe_segments++;
		if (!swapz_dead_segment_eligible(a, segment))
			continue;
		result = swapz_claim_dead_segment(a, segment, probe_start);
		if (result == -EAGAIN)
			continue;
		return result;
	}
	return swapz_finish_alloc_probe(a, probe_start, -ENOSPC);
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

int swapz_enable_segment_program_counts(struct swapz_authority *a,
				      swapz_u32 *counts, swapz_u32 count)
{
	if (!a || !counts || a->segment_program_counts ||
	    !a->segment_foreground || !a->segment_mapped_pages ||
	    a->in_flight || a->batch_pending || a->gc_allocation ||
	    a->next_block || a->open_segment != ~(swapz_u32)0 ||
	    count != a->segment_count)
		return -EINVAL;
	memset(counts, 0, (size_t)count * sizeof(*counts));
	a->segment_program_counts = counts;
	return 0;
}

int swapz_enable_segment_page_lists(struct swapz_authority *a,
				  swapz_u32 *first_page,
				  swapz_u32 *last_page,
				  swapz_u32 *prev_page,
				  swapz_u32 *next_page,
				  swapz_u32 count,
				  swapz_u32 logical_pages)
{
	if (!a || !first_page || !last_page || !prev_page || !next_page ||
	    swapz_segment_page_lists_enabled(a) || !a->segment_foreground ||
	    !a->segment_mapped_pages || a->in_flight || a->batch_pending ||
	    a->gc_allocation || a->next_block ||
	    a->open_segment != ~(swapz_u32)0 || count != a->segment_count ||
	    logical_pages != a->logical_pages)
		return -EINVAL;
	memset(first_page, 0xff, (size_t)count * sizeof(*first_page));
	memset(last_page, 0xff, (size_t)count * sizeof(*last_page));
	memset(prev_page, 0xff, (size_t)logical_pages * sizeof(*prev_page));
	memset(next_page, 0xff, (size_t)logical_pages * sizeof(*next_page));
	a->segment_first_page = first_page;
	a->segment_last_page = last_page;
	a->page_prev_in_segment = prev_page;
	a->page_next_in_segment = next_page;
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
	/*
	 * Preserve next_segment_probe across successful GC. The allocator's
	 * circular probe is independent of victim identity; resetting it to a
	 * low-numbered victim would bias subsequent dead-segment reuse.
	 */
	/* Deliberately leave OPEN and next_block pointing at GC destination:
	 * subsequent foreground writes use the *same* compacted segment. */
	return 0;
}

int swapz_stage(struct swapz_authority *a, const swapz_u32 *pages,
	      swapz_u8 count, swapz_u8 blocks, struct swapz_tx *out)
{
	swapz_u32 limit, start, tail_waste = 0;
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
		swapz_u32 placed = a->next_block;

		if (!a->reuse_dead_segments ||
		    a->open_segment != a->batch_segment ||
		    placed >= a->physical_blocks ||
		    blocks > a->physical_blocks - placed ||
		    placed / SWAPZ_SEGMENT_BLOCKS != a->batch_segment ||
		    placed % SWAPZ_SEGMENT_BLOCKS + blocks >
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
		if (a->next_block > limit)
			return -ENOSPC;
		start = a->next_block;
		/*
		 * Packed extents may start at any block, but one extent must stay
		 * inside its 1MiB segment. In append-only mode there is no dead
		 * segment picker to move the cursor, so skip only the unusable tail
		 * of this segment. Keep the candidate local until the complete
		 * extent has also passed the exclusive reserve-bound check below.
		 */
		if (start % SWAPZ_SEGMENT_BLOCKS + blocks >
		    SWAPZ_SEGMENT_BLOCKS) {
			tail_waste = SWAPZ_SEGMENT_BLOCKS -
				(start % SWAPZ_SEGMENT_BLOCKS);
			if (tail_waste > limit - start)
				return -ENOSPC;
			start += tail_waste;
		}
		if (start > limit || blocks > limit - start ||
		    start % SWAPZ_SEGMENT_BLOCKS + blocks > SWAPZ_SEGMENT_BLOCKS)
			return -ENOSPC;
		if (tail_waste) {
			if (a->gc_allocation) {
				a->alignment_hole_blocks_gc += tail_waste;
				a->segment_tail_waste_blocks_gc += tail_waste;
			} else {
				a->alignment_hole_blocks_foreground += tail_waste;
				a->segment_tail_waste_blocks_foreground += tail_waste;
			}
		}
	} else {
		limit = a->segment_foreground ? a->physical_blocks :
			((a->gc_allocation ?
			  a->physical_blocks :
			  a->physical_blocks - a->reserve_blocks) /
			 SWAPZ_SEGMENT_BLOCKS) * SWAPZ_SEGMENT_BLOCKS;
		/*
		 * Reuse the OPEN segment only while the entire placed extent fits.
		 * A crossed segment edge MUST run the mapped-record liveness scan;
		 * merely advancing to the numerically next segment can destroy data
		 * after physical cursor wrap.
		 */
		start = a->next_block;
		{
			swapz_u32 placed = start;

			if (a->open_segment == ~(swapz_u32)0 ||
			    start >= limit || blocks - 1U > limit - start ||
			    placed > limit - blocks ||
			    placed / SWAPZ_SEGMENT_BLOCKS != a->open_segment ||
			    placed % SWAPZ_SEGMENT_BLOCKS + blocks >
					SWAPZ_SEGMENT_BLOCKS) {
				int error;

				/*
				 * Account the blocks abandoned at a real segment edge before
				 * swapz_pick_dead_segment() resets next_block to the new
				 * segment. This is physical placement waste, not media I/O.
				 */
				if (a->open_segment != ~(swapz_u32)0 &&
				    a->next_block / SWAPZ_SEGMENT_BLOCKS ==
						a->open_segment &&
				    a->next_block % SWAPZ_SEGMENT_BLOCKS &&
				    (placed / SWAPZ_SEGMENT_BLOCKS !=
						a->open_segment ||
				     placed % SWAPZ_SEGMENT_BLOCKS + blocks >
						SWAPZ_SEGMENT_BLOCKS))
					tail_waste = SWAPZ_SEGMENT_BLOCKS -
						(a->next_block % SWAPZ_SEGMENT_BLOCKS);
				error = swapz_pick_dead_segment(a);
				if (error)
					return error;
				if (tail_waste) {
					if (a->gc_allocation) {
						a->alignment_hole_blocks_gc += tail_waste;
						a->segment_tail_waste_blocks_gc +=
							tail_waste;
					} else {
						a->alignment_hole_blocks_foreground +=
							tail_waste;
						a->segment_tail_waste_blocks_foreground +=
							tail_waste;
					}
				}
				start = a->next_block;
			}
		}
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
	memcpy(&a->active_tx, out, swapz_tx_active_bytes(count));
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
	memset(&a->active_tx, 0, swapz_tx_active_bytes(a->active_count));
	a->in_flight = 0;
	a->active_sequence = 0;
	a->active_blocks = 0;
	a->active_count = 0;
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
	memcpy(&a->active_tx, tx, swapz_tx_active_bytes(tx->count));
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
	memset(&a->active_tx, 0, swapz_tx_active_bytes(a->active_count));
	a->in_flight = 0;
	a->active_sequence = 0;
	a->active_blocks = 0;
	a->active_count = 0;
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
	if (swapz_page_list_validate_entry(a, page)) {
		error = -EUCLEAN;
		goto fail;
	}
	if (swapz_page_list_validate_segment(a, new_segment)) {
		error = -EUCLEAN;
		goto fail;
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
	if (swapz_segment_page_lists_enabled(a)) {
		if (old->valid)
			swapz_page_list_unlink_unchecked(a, page, old_segment);
		swapz_page_list_append_unchecked(a, page, new_segment);
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
	if (swapz_page_list_validate_entry(a, logical_page))
		return -EUCLEAN;
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
	if (old->valid && swapz_segment_page_lists_enabled(a))
		swapz_page_list_unlink_unchecked(a, logical_page, old_segment);
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

static struct swapz_finish_extent_delta *
swapz_finish_extent_delta_get(struct swapz_authority *a, swapz_u8 *count,
			      swapz_u32 start_block)
{
	swapz_u8 index;

	for (index = 0; index < *count; ++index)
		if (a->finish_extent_deltas[index].start_block == start_block)
			return &a->finish_extent_deltas[index];
	if (*count >= SWAPZ_MAX_RECORDS)
		return NULL;
	memset(&a->finish_extent_deltas[*count], 0,
	       sizeof(a->finish_extent_deltas[*count]));
	a->finish_extent_deltas[*count].start_block = start_block;
	return &a->finish_extent_deltas[(*count)++];
}

static struct swapz_finish_segment_delta *
swapz_finish_segment_delta_get(struct swapz_authority *a, swapz_u8 *count,
			       swapz_u32 segment)
{
	swapz_u8 index;

	for (index = 0; index < *count; ++index)
		if (a->finish_segment_deltas[index].segment == segment)
			return &a->finish_segment_deltas[index];
	if (*count >= SWAPZ_MAX_RECORDS)
		return NULL;
	memset(&a->finish_segment_deltas[*count], 0,
	       sizeof(a->finish_segment_deltas[*count]));
	a->finish_segment_deltas[*count].segment = segment;
	return &a->finish_segment_deltas[(*count)++];
}

int swapz_finish(struct swapz_authority *a, const struct swapz_tx *tx,
	       const void *extent, swapz_u32 bytes_total,
	       swapz_u8 completed_blocks, int io_error)
{
	const swapz_u8 *image = extent;
	swapz_u16 payload_lengths[SWAPZ_MAX_RECORDS] = { 0 };
	swapz_u16 payload_offsets[SWAPZ_MAX_RECORDS] = { 0 };
	swapz_u8 payload_encodings[SWAPZ_MAX_RECORDS] = { 0 };
	swapz_u32 new_segment;
	swapz_u32 new_gc_live_bytes = 0, new_gc_io_cost = 0;
	swapz_u16 new_gc_min_live_blocks = 0;
	swapz_u8 extent_delta_count = 0, segment_delta_count = 0;
	swapz_u8 index;
	int gc_enabled, page_lists_enabled;
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
	gc_enabled = swapz_gc_accounting_enabled(a);
	page_lists_enabled = swapz_segment_page_lists_enabled(a);
	if ((a->segment_mapped_pages || gc_enabled || page_lists_enabled) &&
	    new_segment >= a->segment_count) {
		error = -EUCLEAN;
		goto fail;
	}
	if (gc_enabled &&
	    (!a->segment_gc_live_bytes || !a->segment_gc_io_cost ||
	     !a->segment_gc_min_live_blocks || !a->segment_mapped_pages)) {
		error = -EUCLEAN;
		goto fail;
	}
	if (image[7] != tx->count || swapz_disk_sequence(image) != tx->sequence) {
		error = -EUCLEAN;
		goto fail;
	}

	/*
	 * Phase 1. Validate every descriptor, payload CRC, generation and old
	 * liveness while accumulating bounded per-extent/per-segment deltas.
	 * Global authority and GC accounting remain untouched until all checks
	 * have succeeded.
	 */
	for (index = 0; index < tx->count; ++index) {
		struct swapz_decoded decoded;
		const swapz_u8 *payload;
		const struct swapz_map *old;
		struct swapz_finish_extent_delta *extent_delta;
		struct swapz_finish_segment_delta *segment_delta = NULL;
		swapz_u32 logical = tx->records[index].logical_page;
		swapz_u32 old_segment;

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
		payload_encodings[index] = decoded.encoding;
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
		if (swapz_page_list_validate_entry(a, logical)) {
			error = -EUCLEAN;
			goto fail;
		}

		if (gc_enabled) {
			struct swapz_map candidate = {
				.start_block = tx->start_block,
				.payload_length = payload_lengths[index],
				.extent_blocks = tx->extent_blocks,
				.valid = 1,
			};
			swapz_u32 candidate_segment, candidate_bytes, candidate_io;
			swapz_u16 candidate_min_blocks;

			error = swapz_gc_account_costs(a, &candidate,
						       &candidate_segment,
						       &candidate_bytes,
						       &candidate_io,
						       &candidate_min_blocks);
			if (error)
				goto fail;
			if (candidate_segment != new_segment ||
			    new_gc_live_bytes > ~(swapz_u32)0 - candidate_bytes ||
			    new_gc_io_cost > ~(swapz_u32)0 - candidate_io ||
			    new_gc_min_live_blocks >
				(swapz_u16)~0U - candidate_min_blocks) {
				error = -EOVERFLOW;
				goto fail;
			}
			new_gc_live_bytes += candidate_bytes;
			new_gc_io_cost += candidate_io;
			new_gc_min_live_blocks += candidate_min_blocks;
		}
		if (!old->valid)
			continue;
		if (old->start_block >= a->physical_blocks ||
		    !swapz_legal_class(old->extent_blocks) ||
		    a->extent_classes[old->start_block] != old->extent_blocks) {
			error = -EUCLEAN;
			goto fail;
		}
		extent_delta = swapz_finish_extent_delta_get(
			a, &extent_delta_count, old->start_block);
		if (!extent_delta ||
		    extent_delta->references == (swapz_u8)~0U) {
			error = -EOVERFLOW;
			goto fail;
		}
		extent_delta->references++;
		if (a->live_records[old->start_block] < extent_delta->references) {
			error = -EUCLEAN;
			goto fail;
		}

		old_segment = old->start_block / SWAPZ_SEGMENT_BLOCKS;
		if ((a->segment_mapped_pages || gc_enabled || page_lists_enabled) &&
		    old_segment >= a->segment_count) {
			error = -EUCLEAN;
			goto fail;
		}
		if (a->segment_mapped_pages || gc_enabled) {
			segment_delta = swapz_finish_segment_delta_get(
				a, &segment_delta_count, old_segment);
			if (!segment_delta) {
				error = -EOVERFLOW;
				goto fail;
			}
		}
		if (a->segment_mapped_pages) {
			if (segment_delta->mapped_pages == (swapz_u8)~0U) {
				error = -EOVERFLOW;
				goto fail;
			}
			segment_delta->mapped_pages++;
			if (a->segment_mapped_pages[old_segment] <
			    segment_delta->mapped_pages) {
				error = -EUCLEAN;
				goto fail;
			}
		}
		if (gc_enabled) {
			swapz_u32 cost_segment, live_bytes, io_cost;
			swapz_u16 min_live_blocks;

			error = swapz_gc_account_costs(a, old, &cost_segment,
						       &live_bytes, &io_cost,
						       &min_live_blocks);
			if (error)
				goto fail;
			if (cost_segment != old_segment ||
			    segment_delta->live_bytes >
				~(swapz_u32)0 - live_bytes ||
			    segment_delta->io_cost > ~(swapz_u32)0 - io_cost ||
			    segment_delta->min_live_blocks >
				(swapz_u16)~0U - min_live_blocks) {
				error = -EOVERFLOW;
				goto fail;
			}
			segment_delta->live_bytes += live_bytes;
			segment_delta->io_cost += io_cost;
			segment_delta->min_live_blocks += min_live_blocks;
			if (a->segment_gc_live_bytes[old_segment] <
				    segment_delta->live_bytes ||
			    a->segment_gc_io_cost[old_segment] <
				    segment_delta->io_cost ||
			    a->segment_gc_min_live_blocks[old_segment] <
				    segment_delta->min_live_blocks) {
				error = -EUCLEAN;
				goto fail;
			}
		}
	}
	if (swapz_page_list_validate_segment(a, new_segment)) {
		error = -EUCLEAN;
		goto fail;
	}
	if (a->segment_mapped_pages) {
		swapz_u32 mapped_base = a->segment_mapped_pages[new_segment];
		swapz_u8 delta_index;

		for (delta_index = 0; delta_index < segment_delta_count;
		     ++delta_index)
			if (a->finish_segment_deltas[delta_index].segment ==
			    new_segment) {
				mapped_base -=
					a->finish_segment_deltas[delta_index].mapped_pages;
				break;
			}
		if ((swapz_u32)tx->count > ~(swapz_u32)0 - mapped_base) {
			error = -EOVERFLOW;
			goto fail;
		}
	}
	if (gc_enabled) {
		swapz_u32 live_base = a->segment_gc_live_bytes[new_segment];
		swapz_u32 io_base = a->segment_gc_io_cost[new_segment];
		swapz_u16 min_base = a->segment_gc_min_live_blocks[new_segment];
		swapz_u8 delta_index;

		for (delta_index = 0; delta_index < segment_delta_count;
		     ++delta_index)
			if (a->finish_segment_deltas[delta_index].segment ==
			    new_segment) {
				live_base -=
					a->finish_segment_deltas[delta_index].live_bytes;
				io_base -=
					a->finish_segment_deltas[delta_index].io_cost;
				min_base -=
					a->finish_segment_deltas[delta_index].min_live_blocks;
				break;
			}
		if (live_base > ~(swapz_u32)0 - new_gc_live_bytes ||
		    io_base > ~(swapz_u32)0 - new_gc_io_cost ||
		    min_base > (swapz_u16)~0U - new_gc_min_live_blocks) {
			error = -EOVERFLOW;
			goto fail;
		}
	}
	if (a->live_records[tx->start_block] ||
	    a->extent_classes[tx->start_block]) {
		error = -EUCLEAN;
		goto fail;
	}

	/*
	 * Phase 2. Apply each prevalidated aggregate once, then publish the
	 * distinct logical mappings and page-list links. No rollback is needed
	 * because no operation below can fail.
	 */
	a->live_records[tx->start_block] = tx->count;
	a->extent_classes[tx->start_block] = tx->extent_blocks;
	for (index = 0; index < extent_delta_count; ++index)
		a->live_records[a->finish_extent_deltas[index].start_block] -=
			a->finish_extent_deltas[index].references;
	for (index = 0; index < segment_delta_count; ++index) {
		const struct swapz_finish_segment_delta *delta =
			&a->finish_segment_deltas[index];

		if (a->segment_mapped_pages)
			a->segment_mapped_pages[delta->segment] -=
				delta->mapped_pages;
		if (gc_enabled) {
			a->segment_gc_live_bytes[delta->segment] -=
				delta->live_bytes;
			a->segment_gc_io_cost[delta->segment] -= delta->io_cost;
			a->segment_gc_min_live_blocks[delta->segment] -=
				delta->min_live_blocks;
		}
	}
	if (a->segment_mapped_pages)
		a->segment_mapped_pages[new_segment] += tx->count;
	if (gc_enabled) {
		a->segment_gc_live_bytes[new_segment] += new_gc_live_bytes;
		a->segment_gc_io_cost[new_segment] += new_gc_io_cost;
		a->segment_gc_min_live_blocks[new_segment] +=
			new_gc_min_live_blocks;
	}
	for (index = 0; index < tx->count; ++index) {
		swapz_u32 logical = tx->records[index].logical_page;
		struct swapz_map *entry = &a->maps[logical];
		swapz_u32 old_segment = entry->valid ?
			entry->start_block / SWAPZ_SEGMENT_BLOCKS : 0;
		struct swapz_map new_map = {
			.start_block = tx->start_block,
			.sequence = tx->sequence,
			.generation = tx->records[index].generation,
			.payload_length = payload_lengths[index],
			.payload_offset = payload_offsets[index],
			.extent_blocks = tx->extent_blocks,
			.record_index = swapz_map_pack_record_index(
				index, payload_encodings[index]),
			.valid = 1,
		};

		if (swapz_segment_page_lists_enabled(a)) {
			if (entry->valid)
				swapz_page_list_unlink_unchecked(
					a, logical, old_segment);
			swapz_page_list_append_unchecked(a, logical, new_segment);
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

int swapz_read_authoritative_peeked_payload(
				  const struct swapz_authority *a,
				  swapz_u32 logical_page,
				  const struct swapz_map *observed,
				  const void *metadata, swapz_u32 bytes_total,
				  const struct swapz_decoded *peeked,
				  const swapz_u8 *stored,
				  const swapz_u8 **payload)
{
	const struct swapz_map *current_map;
	int error;
	if (!peeked || !stored || !payload) return -EINVAL;
	*payload = NULL;
	error = swapz_read_observed_authority(a, logical_page, observed,
					   metadata, bytes_total, &current_map);
	if (error) return error;
	if (peeked->logical_page != logical_page ||
	    peeked->generation != current_map->generation ||
	    peeked->encoding != swapz_map_encoding(current_map) ||
	    peeked->payload_length != current_map->payload_length ||
	    peeked->payload_offset != current_map->payload_offset ||
	    !peeked->payload_length ||
	    peeked->payload_length > SWAPZ_MAX_COMPRESSED ||
	    peeked->payload_offset >= bytes_total ||
	    peeked->payload_length > bytes_total - peeked->payload_offset ||
	    swapz_disk_sequence(metadata) != current_map->sequence)
		return -EUCLEAN;
	if (swapz_crc32c_bytes(stored, peeked->payload_length) != peeked->payload_crc32c)
		return -EBADMSG;
	*payload = stored;
	return 0;
}

int swapz_read_authoritative_peeked(const struct swapz_authority *a,
				  swapz_u32 logical_page,
				  const struct swapz_map *observed,
				  const void *extent, swapz_u32 bytes_total,
				  const struct swapz_decoded *peeked,
				  const swapz_u8 **payload)
{
	if (!extent || !peeked || peeked->payload_offset >= bytes_total) return -EINVAL;
	return swapz_read_authoritative_peeked_payload(
		a, logical_page, observed, extent, bytes_total, peeked,
		(const swapz_u8 *)extent + peeked->payload_offset, payload);
}
