/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_V3_WINDOW_POLICY_H
#define SWAPZ_V3_WINDOW_POLICY_H

#include "codec.h"

struct bio;

/* Prepared bytes and upper completion ownership remain with the worker. */
struct sv3_pending_bio {
	struct bio *bio;
	sv3_u32 logical;
	sv3_u16 length;
	/* True only for the complete 4KiB incompressible fallback. */
	sv3_u8 raw;
};

/*
 * The serialized caller supplies every ordering/authority fence in blocked.
 * This predicate only proves that a READ cannot observe any staged slot;
 * it never publishes a write or changes the pending BIOs' ownership.
 */
static inline int sv3_window_read_independent(
		const struct sv3_pending_bio *pending, sv3_u8 count,
		sv3_u32 logical, sv3_u8 retain_ms, int blocked)
{
	sv3_u8 index;

	if (!retain_ms || !count || count > SV3_MAX_RECORDS ||
	    !pending || blocked)
		return 0;
	for (index = 0; index < count; ++index)
		if (pending[index].logical == logical)
			return 0;
	return 1;
}

/*
 * Alpha.21: the opt-in retained stream no longer needs to wait for seven
 * records before EVERY useful lower write. Two sufficiently small LZ4
 * records fit in one 4KiB extent, three medium records can fit in one
 * 8KiB extent, and seven can fit in one 16KiB extent. A full format
 * header plus one descriptor per record is included in each bound.
 *
 * For the measured 2073-byte medium pages, two do NOT fit one 4KiB
 * extent (4194B); three DO fit 8KiB (6283B vs 12KiB separate).
 * This can end a 2ms retained window before the seventh arrival.
 * It deliberately trades potential seven-page density for earlier
 * acknowledgement, but only after the SAME successful lower write,
 * mapping publication and optional flush as the original path.
 *
 * All page dependencies, duplicate slots and FUA/PREFLUSH fences are
 * handled by the serialized caller before this eligibility check.
 * Restricted read budgets, default retain_ms=0 and RAW/invalid pages
 * fail closed. This geometry proof does NOT guarantee a speedup:
 * benchmark lower WRITE bytes/requests and upper read/write p99 too.
 */
static inline int sv3_window_pack_ready(
		const struct sv3_pending_bio *pending, sv3_u8 count,
		sv3_u8 retain_ms, sv3_u8 read_budget)
{
	sv3_u32 extent_bytes;
	sv3_u8 extent_blocks;
	sv3_u8 i;

	if (!retain_ms || read_budget || !pending)
		return 0;
	if (count == 2U)
		extent_blocks = 1U;
	else if (count == 3U)
		extent_blocks = 2U;
	else if (count == 7U)
		extent_blocks = 4U;
	else
		return 0;
	extent_bytes = sizeof(struct sv3_header) +
		(sv3_u32)count * sizeof(struct sv3_record);
	for (i = 0; i < count; ++i) {
		if (pending[i].raw || !pending[i].length ||
		    pending[i].length > SV3_MAX_COMPRESSED)
			return 0;
		extent_bytes += pending[i].length;
	}
	return extent_bytes <= (sv3_u32)extent_blocks * SV3_BLOCK_BYTES;
}

/*
 * Once this accepted burst has already committed a useful packed group,
 * an idle worker may finish its one/two compressed records without another
 * retention wait. Initial lone writes retain their ordinary opportunity
 * to collect companions. The serialized caller supplies packed_burst only
 * after a successful packed commit and owns all idle/dependency fences.
 * This predicate neither establishes that history nor completes a BIO.
 */
static inline int sv3_window_burst_tail_ready(
		const struct sv3_pending_bio *pending, sv3_u8 count,
		sv3_u8 retain_ms, sv3_u8 read_budget, int packed_burst)
{
	sv3_u8 index;

	if (!retain_ms || read_budget || !packed_burst || !pending ||
	    !count || count > 2U)
		return 0;
	for (index = 0; index < count; ++index)
		if (pending[index].raw || !pending[index].length ||
		    pending[index].length > SV3_MAX_COMPRESSED)
			return 0;
	if (count == 2U && pending[0].logical == pending[1].logical)
		return 0;
	return 1;
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
static inline int sv3_window_uniform_compressed(
		const struct sv3_pending_bio *pending, sv3_u8 count)
{
	sv3_u16 length;
	sv3_u8 index;

	if (!pending || !count || count > SV3_MAX_RECORDS ||
	    pending[0].raw || !pending[0].length ||
	    pending[0].length > SV3_MAX_COMPRESSED)
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
static inline int sv3_window_timer_enabled(sv3_u8 retain_ms)
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
static inline int sv3_retention_timer_needs_arm(sv3_u8 retain_ms, int queued)
{
	return sv3_window_timer_enabled(retain_ms) && !queued;
}

/*
 * Report elapsed wall-time for a completed synchronous section. The Linux
 * monotonic clock normally advances; a reversed sample is NOT elapsed work
 * and must not underflow an unsigned counter. This does not measure CPU
 * cycles, host device saturation, or upper BIO queueing/retention wait.
 */
static inline unsigned long long sv3_elapsed_ns(unsigned long long start_ns,
						unsigned long long end_ns)
{
	return end_ns >= start_ns ? end_ns - start_ns : 0;
}

/*
 * One clock sample decides expiry against the original first admission.
 * Compare elapsed time, never subtract it from an unsigned remaining
 * budget: a crossed deadline must expire instead of wrapping the delay.
 */
static inline int sv3_window_retention_expired(unsigned long long first_ns,
		unsigned long long now_ns, sv3_u8 retain_ms)
{
	if (!retain_ms || !first_ns)
		return 1;
	if (now_ns < first_ns)
		return 0;
	return now_ns - first_ns >= (unsigned long long)retain_ms * 1000000ULL;
}

#endif
