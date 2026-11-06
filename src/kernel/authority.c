// SPDX-License-Identifier: GPL-2.0-only
#include "authority.h"
#include "gc-cost.h"

#ifdef __KERNEL__
#include <linux/errno.h>
#include <linux/ktime.h>
#include <linux/printk.h>
#include <linux/sched.h>
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

/*
 * Validate a logical page's intrusive segment-list links. When segment_checked
 * is non-zero, the caller has already validated the containing segment header
 * and tail during the current serialized preflight pass.
 */
static int swapz_page_list_validate_membership(
	const struct swapz_authority *a, swapz_u32 logical, swapz_u32 segment)
{
	const swapz_u32 none = ~(swapz_u32)0;
	const swapz_u32 maximum_segment_pages =
		SWAPZ_SEGMENT_BLOCKS * SWAPZ_MAX_RECORDS;
	swapz_u32 current_logical = logical;
	swapz_u32 visited_pages = 1U;

	if (segment >= a->segment_count ||
	    a->segment_first_page[segment] >= a->logical_pages)
		return -EUCLEAN;

	/*
	 * Local reciprocity alone cannot prove membership: a detached cycle can
	 * satisfy both neighboring links. Walk toward the authoritative head and
	 * bound corruption by the maximum physically possible maps in one segment.
	 */
	while (current_logical != a->segment_first_page[segment]) {
		swapz_u32 previous =
			a->page_prev_in_segment[current_logical];

		if (previous == logical || previous == none ||
		    previous >= a->logical_pages ||
		    visited_pages >= maximum_segment_pages)
			return -EUCLEAN;
		if (!a->maps[previous].valid ||
		    a->maps[previous].start_block >= a->physical_blocks ||
		    a->maps[previous].start_block / SWAPZ_SEGMENT_BLOCKS != segment ||
		    a->page_next_in_segment[previous] != current_logical)
			return -EUCLEAN;
		current_logical = previous;
		visited_pages++;
	}
	return 0;
}

static int swapz_page_list_validate_entry_cached(
	const struct swapz_authority *a, swapz_u32 logical, int segment_checked)
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
	if (!segment_checked && swapz_page_list_validate_segment(a, segment))
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

static int swapz_page_list_validate_entry(const struct swapz_authority *a,
					  swapz_u32 logical)
{
	return swapz_page_list_validate_entry_cached(a, logical, 0);
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

/*
 * A segment declared dead by the allocation/recovery path must have no
 * contradictory cached authority. These sidecars are maintained atomically
 * with mapping publication and therefore must reach zero with the last map.
 * Validate them before any recycle hook or GC role exchange can make reuse
 * externally visible.
 */
static int swapz_dead_segment_sidecars_validate(
	const struct swapz_authority *a, swapz_u32 segment)
{
	if (a->segment_mapped_pages &&
	    (segment >= a->segment_count ||
	     a->segment_mapped_pages[segment]))
		return -EUCLEAN;
	if (swapz_page_list_validate_segment(a, segment))
		return -EUCLEAN;
	if (!swapz_gc_accounting_enabled(a))
		return 0;
	if (!a->segment_mapped_pages || !a->segment_gc_live_bytes ||
	    !a->segment_gc_io_cost || !a->segment_gc_min_live_blocks ||
	    segment >= a->segment_count ||
	    a->segment_gc_live_bytes[segment] ||
	    a->segment_gc_io_cost[segment] ||
	    a->segment_gc_min_live_blocks[segment])
		return -EUCLEAN;
	return 0;
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
	/* swapz_gc_estimated_io_cost(m) evaluates byte cost plus extent read penalty;
	 * reuse the already-computed byte cost via swapz_gc_estimated_io_cost_with_bytes. */
	*io_cost = swapz_gc_estimated_io_cost_with_bytes(m, *bytes);
	min = swapz_gc_min_live_blocks(m);
	if (!*bytes || !*io_cost)
		return -EUCLEAN;
	*min_blocks = min;
	return 0;
}

/*
 * Validate and apply a single-page GC accounting transition in one pass
 * after all other preflight checks in swapz_finish_raw() or
 * swapz_discard_page() have succeeded. This eliminates computing costs
 * three times per page and mutating/undoing the arrays during preflight.
 */
static int swapz_gc_account_transition_commit(struct swapz_authority *a,
					      const struct swapz_map *old,
					      const struct swapz_map *new_map)
{
	swapz_u32 old_seg = 0, old_bytes = 0, old_io = 0;
	swapz_u32 new_seg = 0, new_bytes = 0, new_io = 0;
	swapz_u16 old_min = 0, new_min = 0;
	int have_old = old && old->valid;
	int have_new = new_map && new_map->valid;
	int error;

	if (!swapz_gc_accounting_enabled(a))
		return 0;
	if (have_old) {
		error = swapz_gc_account_costs(a, old, &old_seg, &old_bytes,
					       &old_io, &old_min);
		if (error)
			return error;
		if (a->segment_gc_live_bytes[old_seg] < old_bytes ||
		    a->segment_gc_io_cost[old_seg] < old_io ||
		    a->segment_gc_min_live_blocks[old_seg] < old_min)
			return -EUCLEAN;
	}
	if (have_new) {
		swapz_u32 base_bytes, base_io;
		swapz_u16 base_min;

		error = swapz_gc_account_costs(a, new_map, &new_seg, &new_bytes,
					       &new_io, &new_min);
		if (error)
			return error;
		base_bytes = a->segment_gc_live_bytes[new_seg];
		base_io = a->segment_gc_io_cost[new_seg];
		base_min = a->segment_gc_min_live_blocks[new_seg];
		if (have_old && old_seg == new_seg) {
			base_bytes -= old_bytes;
			base_io -= old_io;
			base_min -= old_min;
		}
		if (base_bytes > ~(swapz_u32)0 - new_bytes ||
		    base_io > ~(swapz_u32)0 - new_io ||
		    base_min > (swapz_u16)~0U - new_min)
			return -EOVERFLOW;
	}
	if (have_old) {
		a->segment_gc_live_bytes[old_seg] -= old_bytes;
		a->segment_gc_io_cost[old_seg] -= old_io;
		a->segment_gc_min_live_blocks[old_seg] -= old_min;
	}
	if (have_new) {
		swapz_u32 segment = new_seg;
		swapz_u32 bytes = new_bytes;
		swapz_u32 io_cost = new_io;
		swapz_u16 min_blocks = new_min;

		a->segment_gc_live_bytes[segment] += bytes;
		a->segment_gc_io_cost[segment] += io_cost;
		a->segment_gc_min_live_blocks[segment] += min_blocks;
	}
	return 0;
}

static int swapz_authority_physical_geometry(swapz_u32 physical_blocks)
{
	if (physical_blocks < 3U * SWAPZ_SEGMENT_BLOCKS ||
	    physical_blocks % SWAPZ_SEGMENT_BLOCKS)
		return -EINVAL;
	return 0;
}

static int swapz_authority_validate_candidate(swapz_u32 logical_pages,
					      swapz_u32 physical_blocks,
					      swapz_u32 *reserve_blocks)
{
	swapz_u32 reserve;
	int error;

	if (!logical_pages)
		return -EINVAL;
	error = swapz_authority_physical_geometry(physical_blocks);
	if (error)
		return error;

	/*
	 * The shared window owns ceil(logical_pages / 8), the two-segment GC
	 * minimum and the independent foreground COW headroom requirement.
	 * Keep userspace mapper planning on this exact same capacity policy.
	 */
	if (!swapz_authority_capacity_window(logical_pages, physical_blocks,
					     &reserve))
		return -ENOSPC;

	/*
	 * Before authority_init() clears arrays, reject an unaddressable byte
	 * count on 32-bit kernels. The map is the widest per-logical-page array;
	 * the u16 liveness index is the widest per-physical-block array.
	 * This is a size_t bound, not a promise that allocation can succeed.
	 */
	if ((swapz_u64)logical_pages * sizeof(struct swapz_map) >
		    (swapz_u64)(size_t)-1 ||
	    (swapz_u64)physical_blocks * sizeof(swapz_u16) >
		    (swapz_u64)(size_t)-1)
		return -EOVERFLOW;
	if (reserve_blocks)
		*reserve_blocks = reserve;
	return 0;
}

int swapz_authority_capacity(swapz_u32 physical_blocks,
			     struct swapz_authority_geometry *geometry)
{
	swapz_u32 low = 1U;
	swapz_u32 high = physical_blocks;
	swapz_u32 maximum = 0;
	swapz_u32 reserve = 0;
	int error;

	if (!geometry)
		return -EINVAL;
	error = swapz_authority_physical_geometry(physical_blocks);
	if (error)
		return error;
	/*
	 * This failure is independent of logical capacity. Detect it before the
	 * binary search so a 32-bit physical-index overflow is not misreported as
	 * an empty but otherwise valid geometry.
	 */
	if ((swapz_u64)physical_blocks * sizeof(swapz_u16) >
	    (swapz_u64)(size_t)-1)
		return -EOVERFLOW;

	while (low <= high) {
		swapz_u32 middle = low + (high - low) / 2U;

		error = swapz_authority_validate_candidate(middle, physical_blocks,
							   NULL);
		if (!error) {
			maximum = middle;
			low = middle + 1U;
			continue;
		}
		if (error != -ENOSPC && error != -EOVERFLOW)
			return error;
		high = middle - 1U;
	}
	if (!maximum)
		return -ENOSPC;
	error = swapz_authority_validate_candidate(maximum, physical_blocks,
						   &reserve);
	if (error)
		return error;

	*geometry = (struct swapz_authority_geometry){
		.usable_physical_blocks = physical_blocks,
		.gc_reserve_blocks = reserve,
		.required_foreground_headroom_blocks =
			SWAPZ_FOREGROUND_HEADROOM_BLOCKS,
		.maximum_logical_pages = maximum,
		.logical_mapper_bytes =
			(swapz_u64)maximum * SWAPZ_BLOCK_BYTES,
		.linux_usable_swap_bytes =
			(swapz_u64)(maximum - SWAPZ_LINUX_SWAP_HEADER_BLOCKS) *
			SWAPZ_BLOCK_BYTES,
	};
	return 0;
}

int swapz_authority_validate_geometry(swapz_u32 logical_pages,
				      swapz_u32 physical_blocks,
				      swapz_u32 *reserve_blocks)
{
	return swapz_authority_validate_candidate(logical_pages, physical_blocks,
						  reserve_blocks);
}

int swapz_authority_init(struct swapz_authority *a,
			 struct swapz_map *maps, swapz_u16 *live_records,
			 swapz_u8 *extent_classes, swapz_u32 logical_pages,
			 swapz_u32 physical_blocks)
{
	swapz_u32 reserve;
	int error;

	if (!a || !maps || !live_records || !extent_classes)
		return -EINVAL;
	error = swapz_authority_validate_geometry(logical_pages, physical_blocks,
						 &reserve);
	if (error)
		return error;

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

int swapz_enable_extent_sequence_index(struct swapz_authority *a,
				       swapz_u8 *sequence_delta,
				       swapz_u32 *segment_sequence_base,
				       swapz_u32 segment_count)
{
	swapz_u32 expected_segments;

	if (!a || !sequence_delta || !segment_sequence_base ||
	    a->extent_sequence_delta || a->segment_sequence_base ||
	    a->next_block ||
	    a->open_segment != ~(swapz_u32)0 || a->in_flight || a->batch_pending)
		return -EINVAL;
	expected_segments = a->physical_blocks / SWAPZ_SEGMENT_BLOCKS;
	if (!expected_segments || segment_count != expected_segments)
		return -EINVAL;
	memset(sequence_delta, 0,
	       (size_t)a->physical_blocks * sizeof(*sequence_delta));
	memset(segment_sequence_base, 0,
	       (size_t)segment_count * sizeof(*segment_sequence_base));
	a->extent_sequence_delta = sequence_delta;
	a->segment_sequence_base = segment_sequence_base;
	a->sequence_segment_count = segment_count;
	return 0;
}

static int swapz_extent_sequence_delta_for(const struct swapz_authority *a,
					   swapz_u32 start_block,
					   swapz_u32 sequence,
					   swapz_u8 *delta)
{
	swapz_u32 segment, base;

	if (!a || !sequence || !delta)
		return -EINVAL;
	if (!a->extent_sequence_delta && !a->segment_sequence_base) {
		*delta = 0;
		return 0;
	}
	if (!a->extent_sequence_delta || !a->segment_sequence_base ||
	    start_block >= a->physical_blocks)
		return -EUCLEAN;
	segment = start_block / SWAPZ_SEGMENT_BLOCKS;
	if (segment >= a->sequence_segment_count)
		return -EUCLEAN;
	base = a->segment_sequence_base[segment];
	if (!base) {
		*delta = 0;
		return 0;
	}
	if (sequence < base || sequence - base > (swapz_u8)~0U)
		return -EOVERFLOW;
	*delta = (swapz_u8)(sequence - base);
	return 0;
}

int swapz_extent_sequence_lookup(const struct swapz_authority *a,
				swapz_u32 start_block,
				swapz_u32 *sequence)
{
	swapz_u32 segment, base, value;

	if (!a || !sequence || start_block >= a->physical_blocks)
		return -EINVAL;
	*sequence = 0;
	if (!a->extent_sequence_delta || !a->segment_sequence_base ||
	    start_block >= a->physical_blocks ||
	    !a->live_records[start_block] || !a->extent_classes[start_block])
		return -EUCLEAN;
	segment = start_block / SWAPZ_SEGMENT_BLOCKS;
	if (segment >= a->sequence_segment_count)
		return -EUCLEAN;
	base = a->segment_sequence_base[segment];
	if (!base || base > ~(swapz_u32)0 -
	    a->extent_sequence_delta[start_block])
		return -EUCLEAN;
	value = base + a->extent_sequence_delta[start_block];
	if (!value)
		return -EUCLEAN;
	*sequence = value;
	return 0;
}

/*
 * All production full-map authority callers own dm-target.c's ordered_owner
 * mutex on its sleepable WQ_MEM_RECLAIM worker. queue_lock is released before
 * reaching authority; no spinlock, RCU read section, IRQ-disabled region or
 * kmap_local mapping spans the proof. Submitter ->map can stage but cannot
 * claim/recycle a segment or publish mappings. Only the ordered owner mutates
 * maps, physical sidecars and GC roles, including throughout a voluntary yield.
 * A caller holding an atomic lock must never invoke a full-map proof.
 *
 * 4096 map entries per reschedule opportunity bounds uninterrupted scan work;
 * the full proof still covers every logical entry. cond_resched() may return
 * without scheduling and does not impose a wall-clock completion bound.
 */
#define SWAPZ_MAP_PROOF_RESCHED_PAGES 4096U
_Static_assert(
	SWAPZ_MAP_PROOF_RESCHED_PAGES != 0U &&
	!(SWAPZ_MAP_PROOF_RESCHED_PAGES &
	  (SWAPZ_MAP_PROOF_RESCHED_PAGES - 1U)),
	"map proof reschedule interval must be a nonzero power of two");

static inline void swapz_map_proof_resched(swapz_u32 logical)
{
#ifdef __KERNEL__
	if (logical && !(logical & (SWAPZ_MAP_PROOF_RESCHED_PAGES - 1U)))
		cond_resched();
#else
	(void)logical;
#endif
}

static int swapz_map_proof_refuse(const char *transition,
				  const char *category, int error)
{
#ifdef __KERNEL__
	pr_err_ratelimited(
		"swapz: GC transition=%s corruption=%s errno=%d disposition=refused\n",
		transition, category, error);
#else
	(void)transition;
	(void)category;
#endif
	return error;
}

/*
 * A shared compressed extent is physically releasable only after its current
 * authoritative siblings are independently accounted. Production traverses
 * the bounded per-segment page list; research callers without that index use
 * the legacy full logical-map fallback. This runs only when a shared extent's
 * physical reference count is about to reach zero.
 */
static int swapz_verify_shared_extent_release(
	const struct swapz_authority *a, const struct swapz_map *target,
	swapz_u32 expected_references, const char *transition)
{
	const swapz_u32 none = ~(swapz_u32)0;
	const swapz_u32 maximum_segment_pages =
		SWAPZ_SEGMENT_BLOCKS * SWAPZ_MAX_RECORDS;
	const swapz_u32 target_start = target ? target->start_block : 0U;
	swapz_u32 target_end, target_segment, found = 0;
	swapz_u64 record_mask = 0;

	if (!a || !a->maps || !target || !target->valid || target->raw ||
	    !target->shared_extent || !expected_references ||
	    target_start >= a->physical_blocks ||
	    !swapz_legal_class(target->extent_blocks) ||
	    target->extent_blocks > a->physical_blocks - target_start ||
	    target_start % SWAPZ_SEGMENT_BLOCKS + target->extent_blocks >
		    SWAPZ_SEGMENT_BLOCKS)
		return swapz_map_proof_refuse(
			transition, "invalid_extent_release_request", -EINVAL);

	target_end = target_start + target->extent_blocks;
	target_segment = target_start / SWAPZ_SEGMENT_BLOCKS;

	if (swapz_segment_page_lists_enabled(a)) {
		swapz_u32 current, last = none, visited = 0;
		swapz_u32 mapped_pages;

		if (!swapz_segment_page_lists_complete(a) ||
		    target_segment >= a->segment_count ||
		    swapz_page_list_validate_segment(a, target_segment))
			return swapz_map_proof_refuse(
				transition, "extent_release_page_list", -EUCLEAN);
		mapped_pages = a->segment_mapped_pages[target_segment];
		if (!mapped_pages || mapped_pages > maximum_segment_pages)
			return swapz_map_proof_refuse(
				transition, "extent_release_page_list", -EUCLEAN);

		current = a->segment_first_page[target_segment];
		while (current != none) {
			const struct swapz_map *map;
			swapz_u32 map_end;
			swapz_u64 record_bit;

			if (current >= a->logical_pages ||
			    visited >= mapped_pages ||
			    swapz_page_list_validate_entry_cached(a, current, 1))
				return swapz_map_proof_refuse(
					transition, "extent_release_page_list",
					-EUCLEAN);
			map = &a->maps[current];
			if (!map->valid ||
			    map->start_block >= a->physical_blocks ||
			    !swapz_legal_class(map->extent_blocks) ||
			    (map->raw &&
			     (map->extent_blocks != 1U || map->shared_extent)) ||
			    (!map->raw && swapz_map_record_index(map) &&
			     !map->shared_extent) ||
			    map->extent_blocks >
				    a->physical_blocks - map->start_block ||
			    map->start_block % SWAPZ_SEGMENT_BLOCKS +
				    map->extent_blocks > SWAPZ_SEGMENT_BLOCKS ||
			    map->start_block / SWAPZ_SEGMENT_BLOCKS !=
				    target_segment)
				return swapz_map_proof_refuse(
					transition, "extent_geometry", -EUCLEAN);
			map_end = map->start_block + map->extent_blocks;
			if (map->start_block < target_end &&
			    map_end > target_start) {
				if (map->start_block != target_start ||
				    map->extent_blocks != target->extent_blocks ||
				    map->raw || !map->shared_extent)
					return swapz_map_proof_refuse(
						transition, "overlapping_extent",
						-EUCLEAN);
				record_bit = (swapz_u64)1U <<
					swapz_map_record_index(map);
				if (record_mask & record_bit)
					return swapz_map_proof_refuse(
						transition, "duplicate_record",
						-EUCLEAN);
				record_mask |= record_bit;
				found++;
				if (found > expected_references)
					return swapz_map_proof_refuse(
						transition, "unexpected_reference",
						-EUCLEAN);
			}
			last = current;
			current = a->page_next_in_segment[current];
			visited++;
		}
		if (visited != mapped_pages ||
		    last != a->segment_last_page[target_segment])
			return swapz_map_proof_refuse(
				transition, "extent_release_page_list", -EUCLEAN);
	} else {
		swapz_u32 logical;

		for (logical = 0; logical < a->logical_pages; ++logical) {
			const struct swapz_map *map = &a->maps[logical];
			swapz_u32 map_end;
			swapz_u64 record_bit;

			swapz_map_proof_resched(logical);
			if (!map->valid)
				continue;
			if (map->start_block >= a->physical_blocks ||
			    !swapz_legal_class(map->extent_blocks) ||
			    (map->raw &&
			     (map->extent_blocks != 1U || map->shared_extent)) ||
			    (!map->raw && swapz_map_record_index(map) &&
			     !map->shared_extent) ||
			    map->extent_blocks >
				    a->physical_blocks - map->start_block ||
			    map->start_block % SWAPZ_SEGMENT_BLOCKS +
				    map->extent_blocks > SWAPZ_SEGMENT_BLOCKS)
				return swapz_map_proof_refuse(
					transition, "extent_geometry", -EUCLEAN);
			map_end = map->start_block + map->extent_blocks;
			if (map->start_block >= target_end ||
			    map_end <= target_start)
				continue;
			if (map->start_block != target_start ||
			    map->extent_blocks != target->extent_blocks ||
			    map->raw || !map->shared_extent)
				return swapz_map_proof_refuse(
					transition, "overlapping_extent",
					-EUCLEAN);
			record_bit = (swapz_u64)1U <<
				swapz_map_record_index(map);
			if (record_mask & record_bit)
				return swapz_map_proof_refuse(
					transition, "duplicate_record", -EUCLEAN);
			record_mask |= record_bit;
			found++;
			if (found > expected_references)
				return swapz_map_proof_refuse(
					transition, "unexpected_reference",
					-EUCLEAN);
		}
	}
	if (found != expected_references)
		return swapz_map_proof_refuse(
			transition, "reference_count", -EUCLEAN);
	return 0;
}

/*
 * The safe, strictly limited first swapz GC step: reuse only wholly-dead
 * 1MiB segments. A live object is NEVER copied or overwritten here.
 *
 * The primary logical map is the final ownership authority. Exact segment
 * sidecars reject obvious live candidates cheaply, while every zero-sidecar
 * segment receives an independent full-map proof before reuse. Recovery/role
 * exchange additionally authenticates every surviving map's extent class and
 * start-block liveness; false-zero cached metadata must never weaken either
 * proof at the transition where that metadata is authoritative.
 */
static int swapz_verify_segment_authoritative_maps(
	const struct swapz_authority *a, swapz_u32 segment,
	swapz_u32 expected_logical, swapz_u32 expected_count,
	int verify_physical_metadata, const char *transition)
{
	const swapz_u32 none = ~(swapz_u32)0;
	swapz_u32 logical, start_block, end_block, found_count = 0;

	if (!a || !a->maps || segment >= a->segment_count ||
	    expected_count > a->logical_pages ||
	    (verify_physical_metadata &&
	     (!a->live_records || !a->extent_classes)) ||
	    (expected_logical != none &&
	     (expected_logical >= a->logical_pages || expected_count != 1U)))
		return swapz_map_proof_refuse(transition, "invalid_request", -EINVAL);
	start_block = segment * SWAPZ_SEGMENT_BLOCKS;
	end_block = start_block + SWAPZ_SEGMENT_BLOCKS;

	for (logical = 0; logical < a->logical_pages; ++logical) {
		const struct swapz_map *map = &a->maps[logical];
		swapz_u32 map_end_block;

		swapz_map_proof_resched(logical);
		if (!map->valid)
			continue;
		if (map->start_block >= a->physical_blocks ||
		    !swapz_legal_class(map->extent_blocks) ||
		    (map->raw &&
		     (map->extent_blocks != 1U || map->shared_extent)) ||
		    (!map->raw && swapz_map_record_index(map) &&
		     !map->shared_extent) ||
		    map->extent_blocks > a->physical_blocks - map->start_block ||
		    map->start_block % SWAPZ_SEGMENT_BLOCKS +
			    map->extent_blocks > SWAPZ_SEGMENT_BLOCKS)
			return swapz_map_proof_refuse(
				transition, "extent_geometry", -EUCLEAN);
		if (verify_physical_metadata) {
			swapz_u8 block_offset;

			if (a->extent_classes[map->start_block] !=
				    map->extent_blocks ||
			    !a->live_records[map->start_block])
				return swapz_map_proof_refuse(
					transition, "physical_start", -EUCLEAN);
			/*
			 * Physical descriptors and liveness exist only at an
			 * extent START. Any nonzero interior entry contradicts
			 * this live extent and can also witness an overlapping
			 * physical start. Recovery must reject that state before
			 * publishing a segment-role exchange.
			 */
			for (block_offset = 1U;
			     block_offset < map->extent_blocks;
			     ++block_offset)
				if (a->extent_classes[map->start_block +
						     block_offset] ||
				    a->live_records[map->start_block +
						    block_offset])
					return swapz_map_proof_refuse(
						transition, "physical_interior",
						-EUCLEAN);
		}
		map_end_block = map->start_block + map->extent_blocks;
		if (map->start_block >= end_block || map_end_block <= start_block)
			continue;
		if (expected_logical != none && logical != expected_logical)
			return swapz_map_proof_refuse(
				transition, "unexpected_logical", -EUCLEAN);
		if (found_count >= expected_count)
			return swapz_map_proof_refuse(
				transition, "unexpected_reference", -EUCLEAN);
		found_count++;
	}
	if (found_count != expected_count)
		return swapz_map_proof_refuse(
			transition, "reference_count", -EUCLEAN);
	return 0;
}

static int swapz_claim_dead_segment(struct swapz_authority *a,
				    swapz_u32 segment,
				    unsigned long long probe_start)
{
	swapz_u32 start = segment * SWAPZ_SEGMENT_BLOCKS;
	swapz_u32 off, logical, live_total = 0;
	swapz_u8 used_mask = 0;
	const char *transition = a->gc_allocation ?
		"gc_reserve_claim" : "foreground_segment_claim";
	int used, previously_claimed, reclaim_required, blocked = 0;
	int proof_error;

	if (swapz_dead_segment_sidecars_validate(a, segment))
		return swapz_finish_alloc_probe(a, probe_start,
			swapz_map_proof_refuse(
				transition, "dead_segment_sidecars", -EUCLEAN));
	a->alloc_probe_full_scans++;
	for (off = 0; off < SWAPZ_SEGMENT_BLOCKS; ++off) {
		live_total += a->live_records[start + off];
		used_mask |= a->extent_classes[start + off];
	}
	used = used_mask != 0;
	previously_claimed = a->segment_program_counts &&
			     a->segment_program_counts[segment];
	reclaim_required = used || previously_claimed;
	if (a->segment_mapped_pages) {
		if (live_total)
			return swapz_finish_alloc_probe(a, probe_start,
				swapz_map_proof_refuse(
					transition, "physical_live", -EUCLEAN));
		/*
		 * Program counts and extent classes are cached witnesses, not map
		 * authority. Even a seemingly virgin segment needs the primary-map
		 * proof: both cached witnesses may be falsely zero after corruption.
		 */
		proof_error = swapz_verify_segment_authoritative_maps(
			a, segment, ~(swapz_u32)0, 0U, 0, transition);
		if (proof_error)
			return swapz_finish_alloc_probe(a, probe_start, -EUCLEAN);
	} else {
		if (live_total)
			return -EAGAIN;
		for (logical = 0; logical < a->logical_pages; ++logical) {
			const struct swapz_map *map = &a->maps[logical];

			swapz_map_proof_resched(logical);
			if (!map->valid)
				continue;
			/*
			 * The legacy no-sidecar path still owns the full logical map.
			 * Reject malformed extents before deciding whether this candidate
			 * is unreferenced: a corrupt extent starting in the preceding
			 * segment must not overlap a segment that is about to be reused.
			 */
			if (map->start_block >= a->physical_blocks ||
			    !swapz_legal_class(map->extent_blocks) ||
			    (map->raw &&
			     (map->extent_blocks != 1U || map->shared_extent)) ||
			    (!map->raw && swapz_map_record_index(map) &&
			     !map->shared_extent) ||
			    map->extent_blocks >
				    a->physical_blocks - map->start_block ||
			    map->start_block % SWAPZ_SEGMENT_BLOCKS +
				    map->extent_blocks > SWAPZ_SEGMENT_BLOCKS)
				return swapz_finish_alloc_probe(a, probe_start,
					swapz_map_proof_refuse(
						transition, "extent_geometry",
						-EUCLEAN));
			if (map->start_block / SWAPZ_SEGMENT_BLOCKS == segment) {
				blocked = 1;
				break;
			}
		}
		if (blocked)
			return -EAGAIN;
	}
	if (reclaim_required && a->dead_segment_recycle) {
		int error = a->dead_segment_recycle(
			a->dead_segment_recycle_opaque, segment);

		if (error)
			return swapz_finish_alloc_probe(a, probe_start, error);
	}
	/*
	 * A prior claim can contain abandoned/uncertain lower writes even when
	 * current extent-class bytes are all zero. Clear every per-segment
	 * physical descriptor before reuse; the recycle hook above is likewise
	 * conservative for that case.
	 */
	if (reclaim_required) {
		memset(a->extent_classes + start, 0,
		       SWAPZ_SEGMENT_BLOCKS * sizeof(*a->extent_classes));
		if (a->extent_sequence_delta)
			memset(a->extent_sequence_delta + start, 0,
			       SWAPZ_SEGMENT_BLOCKS *
			       sizeof(*a->extent_sequence_delta));
		if (a->segment_sequence_base &&
		    segment < a->sequence_segment_count)
			a->segment_sequence_base[segment] = 0;
		if (used)
			a->recycled_dead_segments++;
	}
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
 * A recovery destination can become physically full after one uncertain block
 * plus all still-authoritative survivors have been relocated. At that point
 * the original victim is dead but commit_rotation() correctly refuses to call
 * the full destination foreground progress.
 *
 * Roll forward without exposing that no-progress role exchange to foreground:
 * first run the original victim through a full-map validator that also
 * authenticates every surviving map's physical start sidecars, then through
 * the same recycle hook used by ordinary allocation. Only after that succeeds do
 * the infallible in-memory role changes below make the full destination the
 * next GC victim and the verified-dead original victim the next destination.
 * No mapping, generation or live refcount changes here.
 */
static int swapz_verify_recovery_victim_dead_for_transition(
	const struct swapz_authority *a, swapz_u32 segment,
	int verify_global_map_physical_metadata, const char *transition)
{
	swapz_u32 start_block, block;
	int error;

	if (!a || !a->live_records || segment >= a->segment_count)
		return swapz_map_proof_refuse(
			transition, "invalid_request", -EINVAL);
	error = swapz_verify_segment_authoritative_maps(
		a, segment, ~(swapz_u32)0, 0U,
		verify_global_map_physical_metadata, transition);
	if (error)
		return error;
	if (a->segment_mapped_pages && a->segment_mapped_pages[segment])
		return swapz_map_proof_refuse(
			transition, "dead_segment_mapped_sidecar", -EUCLEAN);

	start_block = segment * SWAPZ_SEGMENT_BLOCKS;
	for (block = 0; block < SWAPZ_SEGMENT_BLOCKS; ++block)
		if (a->live_records[start_block + block])
			return swapz_map_proof_refuse(
				transition, "dead_segment_physical_live", -EUCLEAN);
	return 0;
}

/*
 * Keep recovery advance's original three-argument validation boundary.
 * The other role transitions identify themselves explicitly to the common
 * full-map verifier for category-specific refusal diagnostics.
 */
static int swapz_verify_recovery_victim_dead(
	const struct swapz_authority *a, swapz_u32 segment,
	int verify_global_map_physical_metadata)
{
	return swapz_verify_recovery_victim_dead_for_transition(
		a, segment, verify_global_map_physical_metadata, "gc_advance");
}

/*
 * Continue the same victim into a different reserve when a multi-block
 * relocation cannot fit the current destination tail. Unlike full-destination
 * roll-forward, the original victim can still be live, so it cannot be
 * recycled. Claim another independently dead reserve first; only after that
 * complete proof succeeds may the blocked destination become foreground.
 *
 * This is recovery-only capacity degradation: one reserve role is consumed by
 * the blocked destination. Repeated advances are bounded by the finite reserve
 * pool. No replacement reserve means the caller must fail the owned recovery
 * closed rather than retry the same non-fitting extent forever.
 */
int swapz_gc_advance_rotation_destination(struct swapz_authority *a,
					 swapz_u32 blocked_destination)
{
	swapz_u32 old_next, old_open, old_probe, scan;
	unsigned long long probe_start;
	int error;

	if (!a || !a->segment_foreground || !a->gc_allocation ||
	    a->in_flight || a->batch_pending || a->batch_replaying ||
	    blocked_destination >= a->segment_count ||
	    blocked_destination != a->gc_destination ||
	    a->open_segment != blocked_destination ||
	    a->gc_forbidden_victim >= a->segment_count ||
	    a->gc_forbidden_victim == blocked_destination ||
	    a->gc_forbidden_open == blocked_destination ||
	    a->segment_foreground[blocked_destination] ||
	    !a->segment_foreground[a->gc_forbidden_victim])
		return -EINVAL;
	old_next = a->next_block;
	old_open = a->open_segment;
	old_probe = a->next_segment_probe;
	if (old_next <= blocked_destination * SWAPZ_SEGMENT_BLOCKS ||
	    old_next > (blocked_destination + 1U) * SWAPZ_SEGMENT_BLOCKS)
		return -EINVAL;

	probe_start = swapz_authority_now_ns();
	for (scan = 0; scan < a->segment_count; ++scan) {
		swapz_u32 segment = (old_probe + scan) % a->segment_count;

		a->alloc_probe_segments++;
		if (segment == blocked_destination ||
		    segment == a->gc_forbidden_open ||
		    segment == a->gc_forbidden_victim ||
		    a->segment_foreground[segment])
			continue;
		/*
		 * A reserve should never carry authority unless it is the current
		 * destination. Treat contradictory maps/liveness as corruption, not
		 * as a candidate to skip and silently route around.
		 */
		/*
		 * A destination-role change must not conceal a corrupted physical
		 * descriptor on any surviving logical map, including other segments.
		 */
		error = swapz_verify_recovery_victim_dead(a, segment, 1);
		if (error) {
#ifdef __KERNEL__
			pr_err_ratelimited(
				"swapz: GC advance blocked=%u candidate=%u victim=%u map_proof=%d; roles intact\n",
				blocked_destination, segment,
				a->gc_forbidden_victim, error);
#endif
			return error;
		}
		error = swapz_claim_dead_segment(a, segment, probe_start);
		if (error) {
#ifdef __KERNEL__
			pr_err_ratelimited(
				"swapz: GC advance blocked=%u candidate=%u claim=%d; restoring cursor\n",
				blocked_destination, segment, error);
#endif
			a->next_block = old_next;
			a->open_segment = old_open;
			a->next_segment_probe = old_probe;
			return error;
		}
		if (a->open_segment != segment ||
		    a->next_block != segment * SWAPZ_SEGMENT_BLOCKS ||
		    a->segment_foreground[segment]) {
			/* Claimed only a dead reserve, so fail closed if internal state
			 * contradicts the claim rather than attempting rollback. */
			return swapz_map_proof_refuse(
				"gc_advance", "claimed_cursor_state", -EUCLEAN);
		}
		a->segment_foreground[blocked_destination] = 1;
		a->gc_destination = segment;
		return 0;
	}
	return swapz_finish_alloc_probe(a, probe_start, -ENOSPC);
}

int swapz_gc_roll_forward_rotation(struct swapz_authority *a,
				   swapz_u32 exhausted_destination)
{
	swapz_u32 evacuated_victim;
	unsigned long long probe_start;
	int error;

	if (!a || !a->segment_foreground || !a->gc_allocation ||
	    a->in_flight || a->batch_pending || a->batch_replaying ||
	    exhausted_destination >= a->segment_count ||
	    exhausted_destination != a->gc_destination ||
	    a->open_segment != exhausted_destination ||
	    a->next_block !=
		    (exhausted_destination + 1U) * SWAPZ_SEGMENT_BLOCKS)
		return -EINVAL;

	evacuated_victim = a->gc_forbidden_victim;
	if (evacuated_victim >= a->segment_count ||
	    evacuated_victim == exhausted_destination ||
	    evacuated_victim == a->gc_forbidden_open ||
	    !a->segment_foreground[evacuated_victim] ||
	    a->segment_foreground[exhausted_destination])
		return swapz_map_proof_refuse(
			"gc_roll_forward", "role_state", -EUCLEAN);

	/*
	 * Independently prove the old victim is absent from the authoritative map
	 * array, cached mapped-page sidecar and physical liveness before any recycle
	 * hook can touch it. swapz_claim_dead_segment() then revalidates the normal
	 * dead-segment metadata and performs the only externally fallible hook.
	 * Roles remain unchanged until every check and the hook have succeeded.
	 */
	error = swapz_verify_recovery_victim_dead_for_transition(
		a, evacuated_victim, 1, "gc_roll_forward");
	if (error) {
#ifdef __KERNEL__
		pr_err_ratelimited(
			"swapz: GC roll-forward victim=%u exhausted=%u map_proof=%d; roles intact\n",
			evacuated_victim, exhausted_destination, error);
#endif
		return error;
	}
	probe_start = swapz_authority_now_ns();
	error = swapz_claim_dead_segment(a, evacuated_victim, probe_start);
	if (error) {
#ifdef __KERNEL__
		pr_err_ratelimited(
			"swapz: GC roll-forward victim=%u exhausted=%u claim=%d; roles intact\n",
			evacuated_victim, exhausted_destination, error);
#endif
		return error;
	}

	a->segment_foreground[exhausted_destination] = 1;
	a->segment_foreground[evacuated_victim] = 0;
	a->gc_forbidden_victim = exhausted_destination;
	a->gc_destination = evacuated_victim;
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
	int error;

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
		return swapz_map_proof_refuse(
			"gc_commit", "role_or_cursor_state", -EUCLEAN);
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
			return swapz_map_proof_refuse(
				"gc_commit", "victim_mapped_sidecar", -EUCLEAN);
	} else {
		for (logical = 0; logical < a->logical_pages; ++logical) {
			const struct swapz_map *m = &a->maps[logical];

			swapz_map_proof_resched(logical);
			if (m->valid && (m->start_block >= a->physical_blocks ||
			    m->start_block / SWAPZ_SEGMENT_BLOCKS == victim))
				return swapz_map_proof_refuse(
					"gc_commit", "victim_reference", -EUCLEAN);
		}
	}
	for (block = victim * SWAPZ_SEGMENT_BLOCKS;
	     block < (victim + 1U) * SWAPZ_SEGMENT_BLOCKS; ++block)
		live_total += a->live_records[block];
	if (live_total || (a->segment_mapped_pages &&
			   live_total != a->segment_mapped_pages[victim]))
		return swapz_map_proof_refuse(
			"gc_commit", "victim_physical_live", -EUCLEAN);
	if (swapz_dead_segment_sidecars_validate(a, victim))
		return swapz_map_proof_refuse(
			"gc_commit", "dead_segment_sidecars", -EUCLEAN);
	/* Cached zero sidecars are not proof of zero authoritative maps.
	 * Verify the primary mapping table before publishing a new GC role. */
	/*
	 * A successful role exchange can immediately expose destination data to
	 * foreground reads. Authenticate class/liveness for EVERY surviving map
	 * before exchanging roles, not just the old victim's deadness.
	 */
	error = swapz_verify_recovery_victim_dead_for_transition(
		a, victim, 1, "gc_commit");
	if (error) {
#ifdef __KERNEL__
		pr_err_ratelimited(
			"swapz: GC commit victim=%u dest=%u cursor=%u map_proof=%d; roles intact\n",
			victim, dest, a->next_block, error);
#endif
		return -EUCLEAN;
	}
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

static int swapz_stage_policy(struct swapz_authority *a,
			      const swapz_u32 *pages, swapz_u8 count,
			      swapz_u8 blocks, struct swapz_tx *out,
			      int logical_pages_unique)
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
		swapz_u32 page = pages[index];
		swapz_u8 earlier;

		if (page >= a->logical_pages)
			return -ERANGE;
		if (a->maps[page].generation == ~(swapz_u32)0)
			return -EOVERFLOW;
		if (!logical_pages_unique)
			for (earlier = 0; earlier < index; ++earlier)
				if (pages[earlier] == page)
					return -EEXIST;
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

/*
 * Read-only placement proof for a caller that must never wait for lower I/O.
 * Returns 1 only when swapz_stage_policy() would place one `blocks` extent in
 * the CURRENT open segment: no dead-segment pick (whose recycle callback may
 * issue a synchronous DISCARD), no append-only tail skip and no -ENOSPC.
 * Any staged/in-flight transaction, GC allocation or unknown cursor returns 0.
 * The caller owns the serialized authority; this mutates nothing.
 */
int swapz_open_segment_fits(const struct swapz_authority *a, swapz_u8 blocks)
{
	swapz_u32 limit, start;

	if (!a || !a->maps || !swapz_legal_class(blocks) || a->in_flight ||
	    a->batch_pending || a->gc_allocation ||
	    !a->next_sequence || a->next_sequence == ~(swapz_u32)0)
		return 0;
	start = a->next_block;
	if (!a->reuse_dead_segments) {
		limit = a->physical_blocks - a->reserve_blocks;
		return start <= limit && blocks <= limit - start &&
		       start % SWAPZ_SEGMENT_BLOCKS + blocks <= SWAPZ_SEGMENT_BLOCKS;
	}
	limit = a->segment_foreground ? a->physical_blocks :
		((a->physical_blocks - a->reserve_blocks) /
		 SWAPZ_SEGMENT_BLOCKS) * SWAPZ_SEGMENT_BLOCKS;
	return a->open_segment != ~(swapz_u32)0 && start < limit &&
	       blocks <= limit - start &&
	       start / SWAPZ_SEGMENT_BLOCKS == a->open_segment &&
	       start % SWAPZ_SEGMENT_BLOCKS + blocks <= SWAPZ_SEGMENT_BLOCKS;
}

int swapz_stage(struct swapz_authority *a, const swapz_u32 *pages,
		swapz_u8 count, swapz_u8 blocks, struct swapz_tx *out)
{
	return swapz_stage_policy(a, pages, count, blocks, out, 0);
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

	/* batch_resume() has already authenticated and copied this exact
	 * authority-owned snapshot. External caller handles still require the
	 * full record-by-record identity comparison below. */
	if (tx == &a->active_tx)
		return 1;

	/* Compare fields, not padding, and NEVER trust a caller-mutated
	 * transaction record before the authority-owned identity check.
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
	error = swapz_stage_policy(a, pages, count, blocks, tx, 0);
	a->batch_stage_allowed = 0;
	return error;
}

int swapz_stage_batch_unique(struct swapz_authority *a,
			     const swapz_u32 *pages, swapz_u8 count,
			     swapz_u8 blocks, struct swapz_tx *tx)
{
	int error;

	if (!a || a->batch_stage_allowed || a->batch_replaying)
		return -EBUSY;
	a->batch_stage_allowed = 1;
	error = swapz_stage_policy(a, pages, count, blocks, tx, 1);
	a->batch_stage_allowed = 0;
	return error;
}

static int swapz_batch_pause_representation(struct swapz_authority *a,
					   const struct swapz_tx *tx,
					   swapz_u8 raw)
{
	swapz_u32 segment;
	swapz_u16 snapshot_index;

	if (!swapz_is_active(a, tx) || raw > 1U || !a->reuse_dead_segments ||
	    a->batch_replaying)
		return -EINVAL;
	snapshot_index = (swapz_u16)a->batch_consumed + a->batch_pending;
	if (snapshot_index >= SWAPZ_MAX_RECORDS)
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
		snapshot_index = 0;
	}
	a->batch_hashes[snapshot_index] =
		swapz_batch_snapshot_crc32c(a, tx,
					    &a->batch_pause_crc_wall_ns);
	a->batch_raw[snapshot_index] = raw;
	a->batch_pending++;
	memset(&a->active_tx, 0, swapz_tx_active_bytes(a->active_count));
	a->in_flight = 0;
	a->active_sequence = 0;
	a->active_blocks = 0;
	a->active_count = 0;
	return 0;
}

int swapz_batch_pause(struct swapz_authority *a, const struct swapz_tx *tx)
{
	return swapz_batch_pause_representation(a, tx, 0);
}

int swapz_batch_pause_run(struct swapz_authority *a,
			 const struct swapz_tx *tx, swapz_u8 raw)
{
	return swapz_batch_pause_representation(a, tx, raw);
}

int swapz_batch_abort_tail(struct swapz_authority *a,
			   const struct swapz_tx *tx)
{
	swapz_u8 index;
	swapz_u32 expected_sequence;

	/*
	 * Tail cancellation is deliberately narrower than replay/abort. It is
	 * valid only before the oldest paused snapshot has been consumed, which
	 * lets a failed second-run preparation roll back without publishing or
	 * disturbing the older run.
	 */
	if (!a || !tx || a->in_flight || a->batch_replaying ||
	    !a->batch_pending || a->batch_consumed)
		return -EINVAL;
	index = a->batch_pending - 1U;
	expected_sequence = a->batch_first_sequence + index;
	if (tx->sequence != expected_sequence ||
	    tx->start_block / SWAPZ_SEGMENT_BLOCKS != a->batch_segment ||
	    a->batch_hashes[index] !=
		swapz_batch_snapshot_crc32c(a, tx,
					    &a->batch_resume_crc_wall_ns))
		return -ESTALE;
	a->batch_hashes[index] = 0;
	a->batch_raw[index] = 0;
	a->batch_pending--;
	a->abandoned_blocks += tx->extent_blocks;
	if (!a->batch_pending) {
		a->batch_segment = ~(swapz_u32)0;
		a->batch_consumed = 0;
	}
	return 0;
}

/* A saved snapshot can only be rearmed in exactly increasing staged
 * sequence order. Reusing a stage never fabricates physical completion.
 * The caller MUST subsequently finish/abort the rearmed transaction. */

/*
 * Read-only authentication of every paused snapshot in one immutable lower
 * run. A valid oldest sequence is insufficient: a later damaged snapshot
 * must not be discovered only after an earlier mapping was published.
 * The ordered owner holds transaction storage and authority serialization.
 */
int swapz_batch_authenticate_run(struct swapz_authority *a,
				 const struct swapz_tx *transactions,
				 const swapz_u8 *raw_entries,
				 swapz_u8 extent_count)
{
	swapz_u8 index;

	if (!a || !transactions || !raw_entries || a->in_flight ||
	    a->batch_replaying || !extent_count ||
	    extent_count > a->batch_pending ||
	    (swapz_u16)a->batch_consumed + a->batch_pending >
		    SWAPZ_MAX_RECORDS)
		return -ESTALE;
	for (index = 0; index < extent_count; ++index) {
		const struct swapz_tx *transaction = &transactions[index];
		swapz_u16 snapshot_index =
			(swapz_u16)a->batch_consumed + index;

		if (raw_entries[index] > 1U ||
		    a->batch_raw[snapshot_index] != raw_entries[index] ||
		    transaction->sequence != a->batch_first_sequence + index ||
		    transaction->start_block / SWAPZ_SEGMENT_BLOCKS !=
			    a->batch_segment ||
		    !swapz_legal_class(transaction->extent_blocks) ||
		    !transaction->count || transaction->count > SWAPZ_MAX_RECORDS ||
		    transaction->start_block >= a->physical_blocks ||
		    transaction->extent_blocks >
			    a->physical_blocks - transaction->start_block ||
		    transaction->start_block + transaction->extent_blocks >
			    a->next_block ||
		    a->batch_hashes[snapshot_index] !=
			    swapz_batch_snapshot_crc32c(
				    a, transaction, &a->batch_resume_crc_wall_ns))
			return -ESTALE;
	}
	return 0;
}

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
		a->batch_hashes[a->batch_consumed] = 0;
		a->batch_raw[a->batch_consumed] = 0;
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
	     (old->raw &&
	      (old->extent_blocks != 1U || old->shared_extent)) ||
	     (!old->raw && swapz_map_record_index(old) &&
	      !old->shared_extent) ||
	     old->extent_blocks > a->physical_blocks - old->start_block ||
	     old->start_block % SWAPZ_SEGMENT_BLOCKS +
	         old->extent_blocks > SWAPZ_SEGMENT_BLOCKS ||
	     a->extent_classes[old->start_block] != old->extent_blocks ||
	     !a->live_records[old->start_block])) {
		error = -EUCLEAN;
		goto fail;
	}
	new_map = (struct swapz_map){
		.start_block = tx->start_block,
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
	if ((!old->valid || old_segment != new_segment) &&
	    swapz_page_list_validate_segment(a, new_segment)) {
		error = -EUCLEAN;
		goto fail;
	}
	/*
	 * Replacing a closed segment's apparent final map can expose a physical
	 * early-TRIM to the caller. A false-one mapped count must not make an
	 * unmentioned surviving logical map disappear from physical storage.
	 */
	if (old->valid && old->shared_extent &&
	    a->live_records[old->start_block] == 1U) {
		error = swapz_verify_shared_extent_release(
			a, old, 1U,
			a->gc_allocation ? "gc_raw_extent_release" :
			"raw_extent_release");
		if (error)
			goto fail;
	}
	if (a->segment_mapped_pages && old->valid &&
	    old_segment != new_segment &&
	    a->segment_mapped_pages[old_segment] == 1U &&
	    swapz_verify_segment_authoritative_maps(
		    a, old_segment, page, 1U, 0,
		    a->gc_allocation ? "gc_raw_final_map" : "raw_final_map")) {
		error = -EUCLEAN;
		goto fail;
	}
	error = swapz_gc_account_transition_commit(a, old, &new_map);
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


/*
 * Validate every authority-side failure condition which can be known before a
 * multi-page upper DISCARD starts publishing generation changes. The ordered
 * owner is the only mutator. Temporary physical-liveness, mapped and GC
 * accounting is restored before return; maps, generations and page lists are
 * never changed.
 *
 * The final full-map pass is required only when the range would make a closed
 * segment appear dead. It treats logical pages inside this authenticated range
 * as the pending removals, so a false-low mapped count or hidden survivor is
 * refused before the first swapz_discard_page() commit.
 */
int swapz_prevalidate_discard_range(struct swapz_authority *a,
				    swapz_u32 first_logical,
				    swapz_u32 page_count)
{
	swapz_u32 processed = 0;
	int error = 0;
	int needs_full_map_proof = 0;
	int gc_enabled;

	if (!a || !a->maps || first_logical >= a->logical_pages ||
	    page_count > a->logical_pages - first_logical)
		return -EINVAL;
	if (!page_count)
		return 0;
	if (a->in_flight || a->batch_pending)
		return -EBUSY;

	gc_enabled = swapz_gc_accounting_enabled(a);
	while (processed < page_count) {
		swapz_u32 logical = first_logical + processed;
		const struct swapz_map *map = &a->maps[logical];
		swapz_u32 segment = 0, live_bytes = 0, io_cost = 0;
		swapz_u16 min_live_blocks = 0;

		if (map->generation == ~(swapz_u32)0) {
			error = -EOVERFLOW;
			break;
		}
		if (map->valid) {
			if (map->start_block >= a->physical_blocks ||
			    !swapz_legal_class(map->extent_blocks) ||
			    (map->raw &&
			     (map->extent_blocks != 1U || map->shared_extent)) ||
			    (!map->raw && swapz_map_record_index(map) &&
			     !map->shared_extent) ||
			    map->extent_blocks >
				    a->physical_blocks - map->start_block ||
			    map->start_block % SWAPZ_SEGMENT_BLOCKS +
				    map->extent_blocks > SWAPZ_SEGMENT_BLOCKS ||
			    a->extent_classes[map->start_block] !=
				    map->extent_blocks ||
			    !a->live_records[map->start_block]) {
				error = -EUCLEAN;
				break;
			}
			segment = map->start_block / SWAPZ_SEGMENT_BLOCKS;
			if (a->segment_mapped_pages &&
			    (segment >= a->segment_count ||
			     !a->segment_mapped_pages[segment])) {
				error = -EUCLEAN;
				break;
			}
		}
		if (swapz_page_list_validate_entry(a, logical)) {
			error = -EUCLEAN;
			break;
		}
		if (map->valid && swapz_segment_page_lists_enabled(a) &&
		    swapz_page_list_validate_membership(a, logical, segment)) {
			error = -EUCLEAN;
			break;
		}
		if (!map->valid) {
			processed++;
			continue;
		}
		if (gc_enabled) {
			error = swapz_gc_account_costs(a, map, &segment,
						       &live_bytes, &io_cost,
						       &min_live_blocks);
			if (error)
				break;
			if (a->segment_gc_live_bytes[segment] < live_bytes ||
			    a->segment_gc_io_cost[segment] < io_cost ||
			    a->segment_gc_min_live_blocks[segment] <
				    min_live_blocks) {
				error = -EUCLEAN;
				break;
			}
		}

		/*
		 * Model the exact post-DISCARD physical and cached state without
		 * publishing it. If this is the final logical map in a closed
		 * segment, the later dead-segment callback will require every
		 * physical START/interior liveness entry in that 1MiB segment to
		 * be zero. Prove that now, before any generation can advance.
		 */
		a->live_records[map->start_block]--;
		if (!a->live_records[map->start_block] && map->shared_extent)
			needs_full_map_proof = 1;
		if (a->segment_mapped_pages)
			a->segment_mapped_pages[segment]--;
		if (gc_enabled) {
			a->segment_gc_live_bytes[segment] -= live_bytes;
			a->segment_gc_io_cost[segment] -= io_cost;
			a->segment_gc_min_live_blocks[segment] -=
				min_live_blocks;
		}
		processed++;
		/*
		 * An empty logical segment must have empty exact GC accounting too.
		 * A positive remainder is corruption just as an underflow is; refuse
		 * before any generation or persistent reference change is published.
		 */
		if (a->segment_mapped_pages &&
		    !a->segment_mapped_pages[segment] && gc_enabled &&
		    (a->segment_gc_live_bytes[segment] ||
		     a->segment_gc_io_cost[segment] ||
		     a->segment_gc_min_live_blocks[segment])) {
			error = -EUCLEAN;
			break;
		}
		if (a->segment_mapped_pages &&
		    !a->segment_mapped_pages[segment] &&
		    segment != a->open_segment) {
			swapz_u32 block;
			swapz_u32 segment_start =
				segment * SWAPZ_SEGMENT_BLOCKS;

			for (block = segment_start;
			     block < segment_start + SWAPZ_SEGMENT_BLOCKS;
			     ++block)
				if (a->live_records[block]) {
					error = -EUCLEAN;
					break;
				}
			if (error)
				break;
			needs_full_map_proof = 1;
		}
	}

	if (!error && needs_full_map_proof) {
		swapz_u32 logical;

		for (logical = 0; logical < a->logical_pages; ++logical) {
			const struct swapz_map *map = &a->maps[logical];
			swapz_u32 segment;

			swapz_map_proof_resched(logical);
			if (!map->valid)
				continue;
			if (map->start_block >= a->physical_blocks ||
			    !swapz_legal_class(map->extent_blocks) ||
			    (map->raw &&
			     (map->extent_blocks != 1U || map->shared_extent)) ||
			    (!map->raw && swapz_map_record_index(map) &&
			     !map->shared_extent) ||
			    map->extent_blocks >
				    a->physical_blocks - map->start_block ||
			    map->start_block % SWAPZ_SEGMENT_BLOCKS +
				    map->extent_blocks > SWAPZ_SEGMENT_BLOCKS) {
				error = swapz_map_proof_refuse(
					"discard_range", "extent_geometry",
					-EUCLEAN);
				break;
			}
			segment = map->start_block / SWAPZ_SEGMENT_BLOCKS;
			if (segment >= a->segment_count) {
				error = swapz_map_proof_refuse(
					"discard_range", "segment_index",
					-EUCLEAN);
				break;
			}
			if (!a->live_records[map->start_block] &&
			    (logical < first_logical ||
			     logical - first_logical >= page_count)) {
				error = swapz_map_proof_refuse(
					"discard_range", "hidden_extent_reference",
					-EUCLEAN);
				break;
			}
			if (a->segment_mapped_pages &&
			    !a->segment_mapped_pages[segment] &&
			    (logical < first_logical ||
			     logical - first_logical >= page_count)) {
				error = swapz_map_proof_refuse(
					"discard_range", "hidden_survivor",
					-EUCLEAN);
				break;
			}
		}
	}

	while (processed) {
		swapz_u32 logical = first_logical + --processed;
		const struct swapz_map *map = &a->maps[logical];
		swapz_u32 segment, live_bytes, io_cost;
		swapz_u16 min_live_blocks;

		if (!map->valid)
			continue;
		segment = map->start_block / SWAPZ_SEGMENT_BLOCKS;
		a->live_records[map->start_block]++;
		if (a->segment_mapped_pages)
			a->segment_mapped_pages[segment]++;
		if (!gc_enabled)
			continue;
		live_bytes = swapz_gc_live_byte_cost(map);
		io_cost = swapz_gc_estimated_io_cost_with_bytes(map, live_bytes);
		min_live_blocks = swapz_gc_min_live_blocks(map);
		a->segment_gc_live_bytes[segment] += live_bytes;
		a->segment_gc_io_cost[segment] += io_cost;
		a->segment_gc_min_live_blocks[segment] += min_live_blocks;
	}

	return error;
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
	     (old->raw &&
	      (old->extent_blocks != 1U || old->shared_extent)) ||
	     (!old->raw && swapz_map_record_index(old) &&
	      !old->shared_extent) ||
	     old->extent_blocks > a->physical_blocks - old->start_block ||
	     old->start_block % SWAPZ_SEGMENT_BLOCKS +
	         old->extent_blocks > SWAPZ_SEGMENT_BLOCKS ||
	     a->extent_classes[old->start_block] != old->extent_blocks ||
	     !a->live_records[old->start_block]))
		return -EUCLEAN;
	generation = old->generation + 1U;
	if (a->segment_mapped_pages && old->valid) {
		old_segment = old->start_block / SWAPZ_SEGMENT_BLOCKS;
		if (old_segment >= a->segment_count ||
		    !a->segment_mapped_pages[old_segment])
			return -EUCLEAN;
		/*
		 * The DM worker may issue immediate whole-segment DISCARD when this
		 * appears to be the last mapping in a CLOSED segment. Prove from the
		 * primary map that this logical page really is the sole reference
		 * before mutating the sidecars that make that reclaim admissible.
		 */
		if (old_segment != a->open_segment &&
		    a->segment_mapped_pages[old_segment] == 1U &&
		    swapz_verify_segment_authoritative_maps(
			    a, old_segment, logical_page, 1U, 0,
			    a->gc_allocation ? "gc_discard_final_map" :
			    "discard_final_map"))
			return -EUCLEAN;
	}
	if (swapz_page_list_validate_entry(a, logical_page))
		return -EUCLEAN;
	if (old->valid && swapz_segment_page_lists_enabled(a) &&
	    swapz_page_list_validate_membership(a, logical_page, old_segment))
		return -EUCLEAN;
	if (old->valid && old->shared_extent &&
	    a->live_records[old->start_block] == 1U) {
		int reference_error = swapz_verify_shared_extent_release(
			a, old, 1U,
			a->gc_allocation ? "gc_discard_extent_release" :
			"discard_extent_release");

		if (reference_error)
			return reference_error;
	}
	if (old->valid) {
		int score_error =
			swapz_gc_account_transition_commit(a, old, NULL);

		if (score_error)
			return score_error;
		a->live_records[old->start_block]--;
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

	for (index = *count; index > 0; --index)
		if (a->finish_extent_deltas[index - 1U].start_block == start_block)
			return &a->finish_extent_deltas[index - 1U];
	if (*count >= SWAPZ_MAX_RECORDS)
		return NULL;
	a->finish_extent_deltas[*count] = (struct swapz_finish_extent_delta){
		.start_block = start_block,
	};
	return &a->finish_extent_deltas[(*count)++];
}

static struct swapz_finish_segment_delta *
swapz_finish_segment_delta_get(struct swapz_authority *a, swapz_u8 *count,
			       swapz_u32 segment, int *is_new)
{
	swapz_u8 index;

	if (is_new)
		*is_new = 0;
	for (index = *count; index > 0; --index)
		if (a->finish_segment_deltas[index - 1U].segment == segment)
			return &a->finish_segment_deltas[index - 1U];
	if (*count >= SWAPZ_MAX_RECORDS)
		return NULL;
	if (is_new)
		*is_new = 1;
	a->finish_segment_deltas[*count] = (struct swapz_finish_segment_delta){
		.segment = segment,
	};
	return &a->finish_segment_deltas[(*count)++];
}

int swapz_finish(struct swapz_authority *a, const struct swapz_tx *tx,
		 const void *extent, swapz_u32 bytes_total,
		 swapz_u8 completed_blocks, int io_error)
{
	const swapz_u8 *image = extent;
	swapz_u16 payload_lengths[SWAPZ_MAX_RECORDS];
	swapz_u16 payload_offsets[SWAPZ_MAX_RECORDS];
	swapz_u8 payload_encodings[SWAPZ_MAX_RECORDS];
	swapz_u32 new_segment;
	swapz_u32 metadata_end, previous_end;
	swapz_u32 new_record_read_penalty;
	swapz_u8 new_sequence_delta = 0;
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
	error = swapz_validate_metadata_crc(image, bytes_total);
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
	error = swapz_extent_sequence_delta_for(a, tx->start_block,
						 tx->sequence,
						 &new_sequence_delta);
	if (error)
		goto fail;
	metadata_end = sizeof(struct swapz_header) +
		(swapz_u32)tx->count * sizeof(struct swapz_record);
	previous_end = bytes_total;
	new_record_read_penalty =
		(tx->extent_blocks == 4U ? 3U : (swapz_u32)tx->extent_blocks) *
		SWAPZ_BLOCK_BYTES;

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
		int is_new_segment_delta = 0;

		error = swapz_lookup_validated_descriptor(image, bytes_total, index,
							  &decoded, &payload);
		if (error)
			goto fail;
		if (decoded.payload_offset < metadata_end ||
		    (swapz_u32)decoded.payload_offset + decoded.payload_length !=
			    previous_end) {
			error = -EUCLEAN;
			goto fail;
		}
		previous_end = decoded.payload_offset;
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

		if (gc_enabled) {
			swapz_u32 candidate_bytes =
				(swapz_u32)payload_lengths[index] +
				sizeof(struct swapz_record);
			swapz_u32 candidate_io =
				candidate_bytes + new_record_read_penalty;
			swapz_u16 candidate_min_blocks =
				payload_lengths[index] >=
				SWAPZ_GC_UNSHAREABLE_MIN_LENGTH ? 1U : 0U;

			if (new_gc_live_bytes > ~(swapz_u32)0 - candidate_bytes ||
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
		if (!old->valid) {
			if (page_lists_enabled &&
			    swapz_page_list_validate_entry_cached(a, logical, 1)) {
				error = -EUCLEAN;
				goto fail;
			}
			continue;
		}
		if (old->start_block >= a->physical_blocks ||
		    !swapz_legal_class(old->extent_blocks) ||
		    (old->raw &&
		     (old->extent_blocks != 1U || old->shared_extent)) ||
		    (!old->raw && swapz_map_record_index(old) &&
		     !old->shared_extent) ||
		    old->extent_blocks > a->physical_blocks - old->start_block ||
		    old->start_block % SWAPZ_SEGMENT_BLOCKS +
		        old->extent_blocks > SWAPZ_SEGMENT_BLOCKS ||
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
		if (a->segment_mapped_pages || gc_enabled || page_lists_enabled) {
			segment_delta = swapz_finish_segment_delta_get(
				a, &segment_delta_count, old_segment,
				&is_new_segment_delta);
			if (!segment_delta) {
				error = -EOVERFLOW;
				goto fail;
			}
		}
		if (page_lists_enabled) {
			if (is_new_segment_delta &&
			    swapz_page_list_validate_segment(a, old_segment)) {
				error = -EUCLEAN;
				goto fail;
			}
			if (swapz_page_list_validate_entry_cached(a, logical, 1)) {
				error = -EUCLEAN;
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
			swapz_u32 live_bytes = swapz_gc_live_byte_cost(old);
			swapz_u32 io_cost;
			swapz_u16 min_live_blocks;

			if (!live_bytes) {
				error = -EUCLEAN;
				goto fail;
			}
			io_cost = live_bytes +
				((old->extent_blocks == 4U ?
				  3U : (swapz_u32)old->extent_blocks) <<
				 SWAPZ_BLOCK_SHIFT);
			min_live_blocks = swapz_gc_min_live_blocks(old);
			if (segment_delta->live_bytes >
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
	if (page_lists_enabled &&
	    swapz_page_list_validate_segment(a, new_segment)) {
		error = -EUCLEAN;
		goto fail;
	}
	/*
	 * A stale-low physical reference count must not let COW publication
	 * release a shared compressed extent while an authoritative sibling
	 * survives. Only the would-be final physical release needs this proof.
	 */
	for (index = 0; index < extent_delta_count; ++index) {
		const struct swapz_finish_extent_delta *delta =
			&a->finish_extent_deltas[index];
		const struct swapz_map *release_map = NULL;
		swapz_u8 record_index;

		if (a->live_records[delta->start_block] != delta->references)
			continue;
		for (record_index = 0; record_index < tx->count; ++record_index) {
			const struct swapz_map *candidate =
				&a->maps[tx->records[record_index].logical_page];

			if (candidate->valid && candidate->shared_extent &&
			    candidate->start_block == delta->start_block) {
				release_map = candidate;
				break;
			}
		}
		if (!release_map)
			continue;
		error = swapz_verify_shared_extent_release(
			a, release_map, delta->references,
			a->gc_allocation ? "gc_batch_extent_release" :
			"batch_extent_release");
		if (error)
			goto fail;
	}
	/*
	 * Publishing a batch can zero several cached source-segment counts.
	 * Before any such count becomes visible to early-TRIM or GC, independently
	 * prove that the batch replaces every map still in each source segment.
	 * The phase-1 delta already contains distinct validated source mappings.
	 */
	if (a->segment_mapped_pages) {
		swapz_u8 delta_index;

		for (delta_index = 0; delta_index < segment_delta_count;
		     ++delta_index) {
			const struct swapz_finish_segment_delta *delta =
				&a->finish_segment_deltas[delta_index];

			if (delta->segment != new_segment &&
			    a->segment_mapped_pages[delta->segment] ==
				    delta->mapped_pages &&
			    swapz_verify_segment_authoritative_maps(
				    a, delta->segment, ~(swapz_u32)0,
				    delta->mapped_pages, 0,
				    a->gc_allocation ? "gc_batch_final_map" :
				    "batch_final_map")) {
				error = -EUCLEAN;
				goto fail;
			}
		}
	}
	if (a->segment_mapped_pages || gc_enabled) {
		const struct swapz_finish_segment_delta *new_seg_delta = NULL;
		swapz_u8 delta_index;

		for (delta_index = 0; delta_index < segment_delta_count;
		     ++delta_index)
			if (a->finish_segment_deltas[delta_index].segment ==
			    new_segment) {
				new_seg_delta =
					&a->finish_segment_deltas[delta_index];
				break;
			}
		if (a->segment_mapped_pages) {
			swapz_u32 mapped_base =
				a->segment_mapped_pages[new_segment] -
				(new_seg_delta ? new_seg_delta->mapped_pages : 0U);

			if ((swapz_u32)tx->count > ~(swapz_u32)0 - mapped_base) {
				error = -EOVERFLOW;
				goto fail;
			}
		}
		if (gc_enabled) {
			swapz_u32 live_base =
				a->segment_gc_live_bytes[new_segment] -
				(new_seg_delta ? new_seg_delta->live_bytes : 0U);
			swapz_u32 io_base =
				a->segment_gc_io_cost[new_segment] -
				(new_seg_delta ? new_seg_delta->io_cost : 0U);
			swapz_u16 min_base =
				a->segment_gc_min_live_blocks[new_segment] -
				(new_seg_delta ? new_seg_delta->min_live_blocks : 0U);

			if (live_base > ~(swapz_u32)0 - new_gc_live_bytes ||
			    io_base > ~(swapz_u32)0 - new_gc_io_cost ||
			    min_base > (swapz_u16)~0U - new_gc_min_live_blocks) {
				error = -EOVERFLOW;
				goto fail;
			}
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
	if (a->extent_sequence_delta) {
		if (!a->segment_sequence_base[new_segment])
			a->segment_sequence_base[new_segment] = tx->sequence;
		a->extent_sequence_delta[tx->start_block] = new_sequence_delta;
	}
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
		struct swapz_map new_map = {
			.start_block = tx->start_block,
			.generation = tx->records[index].generation,
			.payload_length = payload_lengths[index],
			.payload_offset = payload_offsets[index],
			.extent_blocks = tx->extent_blocks,
			.shared_extent = tx->count > 1U,
			.record_index = swapz_map_pack_record_index(
				index, payload_encodings[index]),
			.valid = 1,
		};

		if (page_lists_enabled) {
			if (entry->valid)
				swapz_page_list_unlink_unchecked(
					a, logical,
					entry->start_block /
					SWAPZ_SEGMENT_BLOCKS);
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
	    current_map->generation != observed->generation ||
	    current_map->extent_blocks != observed->extent_blocks ||
	    current_map->raw != observed->raw ||
	    current_map->shared_extent != observed->shared_extent ||
	    current_map->record_index != observed->record_index ||
	    current_map->payload_length != observed->payload_length)
		return -ESTALE;
	if (current_map->raw) {
		if (current_map->raw_crc32c != observed->raw_crc32c)
			return -ESTALE;
		return -EOPNOTSUPP;
	}
	if (current_map->payload_offset != observed->payload_offset)
		return -ESTALE;
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
	swapz_u32 expected_sequence;
	int error;
	if (!peeked || !stored || !payload) return -EINVAL;
	*payload = NULL;
	error = swapz_read_observed_authority(a, logical_page, observed,
					     metadata, bytes_total, &current_map);
	if (error) return error;
	error = swapz_extent_sequence_lookup(a, current_map->start_block,
					     &expected_sequence);
	if (error)
		return error;
	if (peeked->logical_page != logical_page ||
	    peeked->generation != current_map->generation ||
	    peeked->encoding != swapz_map_encoding(current_map) ||
	    peeked->payload_length != current_map->payload_length ||
	    peeked->payload_offset != current_map->payload_offset ||
	    !peeked->payload_length ||
	    peeked->payload_length > SWAPZ_MAX_COMPRESSED ||
	    peeked->payload_offset >= bytes_total ||
	    peeked->payload_length > bytes_total - peeked->payload_offset ||
	    swapz_disk_sequence(metadata) != expected_sequence)
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
