/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_V3_WINDOW_POLICY_H
#define SWAPZ_V3_WINDOW_POLICY_H

#include "codec.h"

struct bio;

/* Prepared bytes and upper completion ownership remain with the worker. */
struct swapz_pending_bio {
	struct bio *bio;
	swapz_u32 logical;
	swapz_u16 length;
	/* True only for the complete 4KiB incompressible fallback. */
	swapz_u8 raw;
};

/*
 * The serialized caller supplies every ordering/authority fence in blocked.
 * This predicate only proves that a READ cannot observe any staged slot;
 * it never publishes a write or changes the pending BIOs' ownership.
 */
static inline int swapz_window_read_independent(
		const struct swapz_pending_bio *pending, swapz_u8 count,
		swapz_u32 logical, swapz_u8 retain_ms, int blocked)
{
	swapz_u8 index;

	if (!retain_ms || !count || count > SWAPZ_MAX_RECORDS ||
	    !pending || blocked)
		return 0;
	for (index = 0; index < count; ++index)
		if (pending[index].logical == logical)
			return 0;
	return 1;
}

/*
 * Retained packed-write geometry.
 *
 * A single small/medium pack is useful for byte reduction, but owner-loaded
 * profiling shows synchronous lower WRITE wait dominates the slow model.
 * Closing immediately at two small records or three medium records turns
 * each first pack into a separate synchronous dm_io. The first staged BIO
 * already pins a hard retain_ms deadline, so wait for a SECOND equivalent
 * pack when geometry permits:
 *
 *   4 records fitting 8KiB  -> one lower callback instead of two 4KiB packs
 *   6 records fitting 16KiB -> one lower callback instead of two 8KiB packs
 *
 * If companions never arrive, the existing absolute timer drains the
 * smaller window. FUA/conflict/read/discard/shutdown fences remain caller
 * owned and bypass this predicate. This changes only the early-close point;
 * the engine still chooses the real extent and publishes only after lower
 * success. Restricted read budgets, RAW records and invalid inputs fail
 * closed.
 */
static inline int swapz_window_extent_fits(
		const struct swapz_pending_bio *pending, swapz_u8 count,
		swapz_u8 retain_ms, swapz_u8 read_budget, swapz_u8 extent_blocks)
{
	swapz_u32 extent_bytes;
	swapz_u8 i;

	if (!retain_ms || read_budget || !pending || !count ||
	    count > SWAPZ_MAX_RECORDS ||
	    (extent_blocks != 1U && extent_blocks != 2U &&
	     extent_blocks != 4U))
		return 0;
	extent_bytes = sizeof(struct swapz_header) +
		(swapz_u32)count * sizeof(struct swapz_record);
	for (i = 0; i < count; ++i) {
		if (pending[i].raw || !pending[i].length ||
		    pending[i].length > SWAPZ_MAX_COMPRESSED)
			return 0;
		extent_bytes += pending[i].length;
	}
	return extent_bytes <= (swapz_u32)extent_blocks * SWAPZ_BLOCK_BYTES;
}

/*
 * Identify the first useful pack. The worker decides whether an already
 * accepted local FIFO successor exists: only that immediate backlog may
 * justify deferring this pack for a second group. This pure geometry helper
 * never inspects queue state or changes the absolute retention deadline.
 */
static inline int swapz_window_single_pack_ready(
		const struct swapz_pending_bio *pending, swapz_u8 count,
		swapz_u8 retain_ms, swapz_u8 read_budget)
{
	if (count == 2U)
		return swapz_window_extent_fits(pending, count, retain_ms,
					     read_budget, 1U);
	if (count == 3U) {
		/* A two-record 4KiB first pack was already counted at count=2. */
		if (swapz_window_extent_fits(pending, 2U, retain_ms,
					   read_budget, 1U))
			return 0;
		return swapz_window_extent_fits(pending, count, retain_ms,
					     read_budget, 2U);
	}
	return 0;
}

static inline int swapz_window_pack_ready(
		const struct swapz_pending_bio *pending, swapz_u8 count,
		swapz_u8 retain_ms, swapz_u8 read_budget)
{
	if (count == 4U)
		return swapz_window_extent_fits(pending, count, retain_ms,
					     read_budget, 2U);
	if (count == 6U)
		return swapz_window_extent_fits(pending, count, retain_ms,
					     read_budget, 4U);
	return 0;
}

/*
 * Once this accepted burst has already committed a useful packed group,
 * an idle worker may finish its one/two compressed records without another
 * retention wait. Initial lone writes retain their ordinary opportunity
 * to collect companions. The serialized caller supplies packed_burst only
 * after a successful packed commit and owns all idle/dependency fences.
 * This predicate neither establishes that history nor completes a BIO.
 */
static inline int swapz_window_burst_tail_ready(
		const struct swapz_pending_bio *pending, swapz_u8 count,
		swapz_u8 retain_ms, swapz_u8 read_budget, int packed_burst)
{
	swapz_u8 index;

	if (!retain_ms || read_budget || !packed_burst || !pending ||
	    !count || count > 2U)
		return 0;
	for (index = 0; index < count; ++index)
		if (pending[index].raw || !pending[index].length ||
		    pending[index].length > SWAPZ_MAX_COMPRESSED)
			return 0;
	if (count == 2U && pending[0].logical == pending[1].logical)
		return 0;
	return 1;
}

/*
 * Diagnostic classifier for the rejected cap=3 Pareto rule.
 *
 * Owner-loaded qualification selected cap=3 zero times, so production stays
 * at the proven cap=2. Probe only expensive (>1 extra 4KiB block) windows
 * and classify whether cap=3 would both recover the byte-minimal block count
 * and contain at most one 16KiB extent. This helper performs no I/O and does
 * not choose the real planner cap.
 */
static inline int swapz_window_cap3_pareto_candidate(
		swapz_u16 uncapped_blocks, swapz_u16 cap2_blocks,
		swapz_u16 cap3_blocks, swapz_u8 cap3_four_extents)
{
	return cap2_blocks > uncapped_blocks &&
		cap2_blocks - uncapped_blocks > 1 &&
		cap3_blocks == uncapped_blocks &&
		cap3_four_extents <= 1U;
}

/*
 * Equal-length accepted compressed records retain their exact input order
 * under the production greedy ordering: largest is always the earliest
 * remaining record and, when a 4KiB complement exists, the chosen partner
 * is the next earliest remaining record. This permits a linear identity
 * mapping instead of repeated O(n^2) greedy scans for common homogeneous
 * workloads, with unchanged plan, physical placement and BIO ordering.
 *
 * Caller has already fenced duplicate logical pages and barriers before
 * preparing this bounded window. RAW or invalid lengths use the original
 * general sorting path, not an assumed compressed record.
 */
static inline int swapz_window_uniform_compressed(
		const struct swapz_pending_bio *pending, swapz_u8 count)
{
	swapz_u16 length;
	swapz_u8 index;

	if (!pending || !count || count > SWAPZ_MAX_RECORDS ||
	    pending[0].raw || !pending[0].length ||
	    pending[0].length > SWAPZ_MAX_COMPRESSED)
		return 0;
	length = pending[0].length;
	for (index = 1; index < count; ++index)
		if (pending[index].raw || pending[index].length != length)
			return 0;
	return 1;
}

/*
 * The retention hrtimer is armed ONLY for nonzero retain_ms. A nonretained
 * window never schedules a timer; skipping its synchronous cancellation
 * avoids an unnecessary timer operation in the single-window write path.
 * The drain/free path must still unconditionally cancel to handle any
 * previously armed callback during teardown and avoid use-after-free.
 */
static inline int swapz_window_timer_enabled(swapz_u8 retain_ms)
{
	return retain_ms != 0;
}

/*
 * An existing queued hrtimer already carries the immutable first-record
 * absolute deadline. Starting the same timer again on every empty-queue
 * worker pass buys no additional wakeup, and adds timer-base overhead.
 * The queued snapshot is taken while the serialized worker holds
 * queue_lock. If a callback has already dequeued the timer, a rearm
 * remains permitted; that callback may also schedule another worker.
 * Never skip the FIRST timer arm of a new retained window.
 */
static inline int swapz_retention_timer_needs_arm(swapz_u8 retain_ms, int queued)
{
	return swapz_window_timer_enabled(retain_ms) && !queued;
}

/*
 * Report elapsed wall-time for a completed synchronous section. The Linux
 * monotonic clock normally advances; a reversed sample is NOT elapsed work
 * and must not underflow an unsigned counter. This does not measure CPU
 * cycles, host device saturation, or upper BIO queueing/retention wait.
 */
static inline unsigned long long swapz_elapsed_ns(unsigned long long start_ns,
						unsigned long long end_ns)
{
	return end_ns >= start_ns ? end_ns - start_ns : 0;
}

/*
 * One clock sample decides expiry against the original first admission.
 * Compare elapsed time, never subtract it from an unsigned remaining
 * budget: a crossed deadline must expire instead of wrapping the delay.
 */
static inline int swapz_window_retention_expired(unsigned long long first_ns,
		unsigned long long now_ns, swapz_u8 retain_ms)
{
	if (!retain_ms || !first_ns)
		return 1;
	if (now_ns < first_ns)
		return 0;
	return now_ns - first_ns >= (unsigned long long)retain_ms * 1000000ULL;
}

#endif
