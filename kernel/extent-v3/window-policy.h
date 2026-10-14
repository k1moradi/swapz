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
 * Alpha.14: a seven-record compressed window fits in ONE 16KiB extent
 * when the exact SWZ3 header, seven descriptors and all accepted LZ4
 * payloads occupy at most 16384 bytes. Seven separate 4KiB writes would
 * cost 28KiB; closing before an eighth write can reduce wait time.
 *
 * This is only a byte-minimal planner feasibility bound, not a lower
 * device request-count or latency guarantee. It never publishes mappings,
 * modifies BIO ownership or changes the existing completion gate.
 * Only explicitly retained, unrestricted-read windows qualify; FUA and
 * duplicate-slot dependencies are fenced by the serialized caller.
 */
static inline int sv3_window_pack_ready(
		const struct sv3_pending_bio *pending, sv3_u8 count,
		sv3_u8 retain_ms, sv3_u8 read_budget)
{
	sv3_u32 extent_bytes = sizeof(struct sv3_header) +
		7U * sizeof(struct sv3_record);
	sv3_u8 i;

	if (!retain_ms || read_budget || count != 7U || !pending)
		return 0;
	for (i = 0; i < count; ++i) {
		if (pending[i].raw || !pending[i].length ||
		    pending[i].length > SV3_MAX_COMPRESSED)
			return 0;
		extent_bytes += pending[i].length;
	}
	/* All seven ordered records, including exact metadata, fit. */
	return extent_bytes <= SV3_MAX_EXTENT_BYTES;
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
 * A serialized worker may consume BIOs which arrived mid-quantum in its
 * current invocation, without a redundant workqueue handoff. ONLY when
 * the original finite quantum has remaining budget AND admission is open.
 * When the budget is exhausted it must requeue to preserve fairness;
 * during presuspend/shutdown it instead drains all accepted BIOs and
 * resets a finite quantum after cond_resched().
 *
 * The caller holds queue_lock while deciding; older unprocessed entries
 * were spliced back ahead of newer arrivals, so continuation keeps FIFO.
 * This never completes, reorders, or publishes an upper BIO itself.
 */
static inline int sv3_worker_can_inline_drain(unsigned int remaining,
					     int accepting)
{
	return accepting && remaining != 0;
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
