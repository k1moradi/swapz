/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_WINDOW_POLICY_H
#define SWAPZ_WINDOW_POLICY_H

#include "codec.h"

struct bio;

#define SWAPZ_WINDOW_DRY_PACK_MIN_RECORDS 4U
/*
 * Owner report 64f6e8e1890e on source e17f05a1c256 measured the fast
 * suppressed-tail reach-four p99 inside the <=500us bucket. Keep this fixed
 * until another exact-source owner qualification replaces that evidence.
 */
#define SWAPZ_SUPPRESSED_TAIL_RESUBMIT_NS 500000ULL

/* Prepared bytes and upper completion ownership remain with the worker. */
struct swapz_pending_bio {
	struct bio *bio;
	swapz_u32 logical;
	swapz_u32 payload_crc32c;
	swapz_u16 length;
	swapz_u8 payload_crc32c_valid;
	swapz_u8 encoding;
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
 * success. Restricted read budgets and invalid compressed inputs fail
 * closed. RAW records are never members of a compressed extent; the separate
 * compressed-prefix helper below may skip earlier RAW slots because the flush
 * planner already emits them after the compressed prefix.
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
 * Bulk windows may stage incompressible RAW records beside compressed records;
 * the flush planner later orders compressed records before the RAW tail.  Early
 * pack recognition must therefore follow the compressed prefix geometry rather
 * than let an earlier RAW admission permanently poison the window.  Latch a
 * pack only when the newest admission is compressed and the bounded prefix now
 * contains exactly the requested number of valid compressed records.
 */
static inline int swapz_window_compressed_extent_fits(
		const struct swapz_pending_bio *pending, swapz_u8 count,
		swapz_u8 retain_ms, swapz_u8 read_budget,
		swapz_u8 compressed_target, swapz_u8 extent_blocks)
{
	swapz_u32 extent_bytes;
	swapz_u8 compressed = 0;
	swapz_u8 i;

	if (!retain_ms || read_budget || !pending || !count ||
	    count > SWAPZ_MAX_RECORDS || !compressed_target ||
	    pending[count - 1U].raw ||
	    (extent_blocks != 1U && extent_blocks != 2U &&
	     extent_blocks != 4U))
		return 0;
	extent_bytes = sizeof(struct swapz_header) +
		(swapz_u32)compressed_target * sizeof(struct swapz_record);
	for (i = 0; i < count; ++i) {
		if (pending[i].raw)
			continue;
		if (!pending[i].length ||
		    pending[i].length > SWAPZ_MAX_COMPRESSED)
			return 0;
		if (++compressed > compressed_target)
			return 0;
		extent_bytes += pending[i].length;
		if (extent_bytes > (swapz_u32)extent_blocks * SWAPZ_BLOCK_BYTES)
			return 0;
	}
	return compressed == compressed_target;
}

/*
 * The exact three-record first-pack check must know whether its first two
 * compressed predecessors had already formed the 4KiB first pack.  Find that
 * bounded compressed prefix directly instead of re-scanning every total-count
 * prefix when RAW records are interleaved.
 */
static inline int swapz_window_first_compressed_extent_fits(
		const struct swapz_pending_bio *pending, swapz_u8 count,
		swapz_u8 compressed_target, swapz_u8 extent_blocks)
{
	swapz_u32 extent_bytes;
	swapz_u8 compressed = 0;
	swapz_u8 i;

	if (!pending || !count || count > SWAPZ_MAX_RECORDS ||
	    !compressed_target ||
	    (extent_blocks != 1U && extent_blocks != 2U &&
	     extent_blocks != 4U))
		return 0;
	extent_bytes = sizeof(struct swapz_header) +
		(swapz_u32)compressed_target * sizeof(struct swapz_record);
	for (i = 0; i < count; ++i) {
		if (pending[i].raw)
			continue;
		if (!pending[i].length ||
		    pending[i].length > SWAPZ_MAX_COMPRESSED)
			return 0;
		extent_bytes += pending[i].length;
		if (++compressed == compressed_target)
			return extent_bytes <=
				(swapz_u32)extent_blocks * SWAPZ_BLOCK_BYTES;
	}
	return 0;
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
	/* Count four is the learned floor but remains below the count > 4 K=1
	 * detach threshold. RAW skipping must not recreate the refuted four-record
	 * first-pack close through otherwise selective compressed geometry. */
	if (count == 4U)
		return 0;
	if (swapz_window_compressed_extent_fits(pending, count, retain_ms,
						read_budget, 2U, 1U))
		return 1;
	if (swapz_window_compressed_extent_fits(pending, count, retain_ms,
						read_budget, 3U, 2U)) {
		if (swapz_window_first_compressed_extent_fits(
				pending, count, 2U, 1U))
			return 0;
		return 1;
	}
	return 0;
}

static inline int swapz_window_pack_ready(
		const struct swapz_pending_bio *pending, swapz_u8 count,
		swapz_u8 retain_ms, swapz_u8 read_budget)
{
	if (swapz_window_compressed_extent_fits(pending, count, retain_ms,
						read_budget, 4U, 2U))
		return 1;
	if (swapz_window_compressed_extent_fits(pending, count, retain_ms,
						read_budget, 6U, 4U))
		return 1;
	return 0;
}

/*
 * Retained windows learn only from closed-loop evidence already observable
 * without waiting for a future arrival. Start at four records. A successful
 * pack-ready close may expose a finite admitted tail accumulated while lower
 * I/O was in flight; that tail raises the learned target, capped by max_window.
 * A later smaller multi-record deadline may shrink it only to the original
 * four-record floor; a transient two/three-record deadline must not recreate
 * first-pack chopping. QD1 remains separate.
 */
static inline swapz_u8 swapz_window_initial_burst_target(swapz_u8 max_window)
{
	if (!max_window)
		return 0;
	return max_window < 4U ? max_window : 4U;
}
static inline swapz_u8 swapz_window_grow_burst_target(
		swapz_u8 current_target, swapz_u8 completed, swapz_u8 admitted_tail,
		swapz_u8 max_window)
{
	unsigned int observed;
	if (!max_window)
		return 0;
	if (!current_target)
		current_target = swapz_window_initial_burst_target(max_window);
	observed = (unsigned int)completed + admitted_tail;
	if (observed > max_window)
		observed = max_window;
	if (observed > current_target)
		current_target = (swapz_u8)observed;
	return current_target;
}
static inline swapz_u8 swapz_window_shrink_burst_target(
		swapz_u8 current_target, swapz_u8 observed)
{
	/*
	 * A single two/three-record deadline is not enough evidence to undo the
	 * four-record floor that prevents first-pack chopping. Smaller streams
	 * retain the hard deadline until a separately qualified policy proves a
	 * safe low-QD adaptation.
	 */
	if (observed >= 4U && observed < current_target)
		return observed;
	return current_target;
}
/*
 * A post-PACK sampled tail becomes a one-shot close target only at or above
 * the qualified four-record floor. Two/three-record samples are dominated by
 * writers resubmitted after bio_endio(), so they are not immediate close
 * targets; only the separately qualified bounded resubmission/read-pivot path
 * may release a valid staged 2/3 tail before the ordinary hard deadline.
 * A staged-only prefix is still not a finite accepted tail.
 */
static inline swapz_u8 swapz_window_sampled_tail_target(
		swapz_u8 tail, swapz_u8 queued_tail)
{
	if (!queued_tail || tail < SWAPZ_WINDOW_DRY_PACK_MIN_RECORDS)
		return 0;
	return tail;
}

/*
 * SERVICE_DRY is allowed below the four-record floor only for an already
 * staged valid pack. Existing read/fence evidence remains authoritative; the
 * separately qualified suppressed-tail path may also close counts two/three
 * after its bounded post-completion resubmission window or a cache-hit READ
 * wave pivot. A one-record window can never become PACK_READY here.
 */
static inline int swapz_window_service_close_ready(
		int valid_pack, int lower_idle, swapz_u8 count,
		swapz_u8 sampled_tail_target, int chain_completed,
		int read_bypasses, int wave_interrupted,
		int suppressed_tail_exhausted)
{
	if (!valid_pack || sampled_tail_target || count < 2U)
		return 0;
	if (count < SWAPZ_WINDOW_DRY_PACK_MIN_RECORDS)
		return read_bypasses || wave_interrupted ||
			suppressed_tail_exhausted;
	return chain_completed || read_bypasses || lower_idle;
}

static inline swapz_u8 swapz_window_effective_burst_target(
		swapz_u8 learned, swapz_u8 admitted_tail)
{
	return admitted_tail ? admitted_tail : learned;
}
static inline int swapz_window_burst_close_ready(
		int first_pack_seen, int accepted_pack_ready, swapz_u8 count,
		swapz_u8 learned_target, swapz_u8 admitted_tail_target)
{
	swapz_u8 target = swapz_window_effective_burst_target(
		learned_target, admitted_tail_target);

	if (!count)
		return 0;
	/*
	 * Once a complete second pack is already staged and the caller proves
	 * the finite accepted queue is dry, waiting only for a larger learned
	 * target spends the retention deadline without gaining accepted work.
	 */
	if (accepted_pack_ready)
		return 1;
	/* A sampled one-record tail is admission skew, not a useful packed
	 * residual. Keep it on the existing pinned retention deadline so a
	 * companion already in flight can join without manufacturing win1. */
	if (count < 2U)
		return 0;
	return target && count >= target &&
		(first_pack_seen || admitted_tail_target);
}


/*
 * An idle lower path alone must not fragment an opted-in retained window.
 * Already-admitted FIFO work is finite: consume it until the learned/sampled
 * target is reached. While an accepted plain WRITE remains, the existing
 * eight-record pressure hand stays authoritative and cannot split the wave
 * below its effective target.
 *
 * Once the serialized worker proves both accepted FIFOs dry, a staged valid
 * compressed pack may close below a larger learned target at the four-record
 * floor. Counts 1..3 retain the pinned deadline; only a sampled finite tail
 * already filtered to the four-record floor or above remains authoritative.
 * This never waits for future admissions and does not change the pinned
 * retention deadline.
 */
static inline int swapz_window_work_conserving_close_ready(
		swapz_u8 retain_ms, int has_valid_pack,
		swapz_u8 count, swapz_u8 learned_target,
		swapz_u8 admitted_tail_target, swapz_u8 hand_records,
		int next_local_is_plain_write)
{
	swapz_u8 target = swapz_window_effective_burst_target(
		learned_target, admitted_tail_target);

	if (count < 2U)
		return 0;
	if (!retain_ms)
		return 1;
	if (target && count >= target)
		return !next_local_is_plain_write ||
			(hand_records && count >= hand_records);
	if (next_local_is_plain_write || admitted_tail_target)
		return 0;
	return has_valid_pack &&
		count >= SWAPZ_WINDOW_DRY_PACK_MIN_RECORDS;
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
 * The first accepted record pins one ordinary absolute retention deadline.
 * Deferred sampled singletons use this same deadline; no shorter active
 * singleton deadline is permitted after the rejected ID53 experiment.
 */
static inline unsigned long long swapz_window_retention_deadline_ns(
		unsigned long long first_ns, swapz_u8 retain_ms)
{
	unsigned long long duration;

	if (!retain_ms || !first_ns)
		return 0;
	duration = (unsigned long long)retain_ms * 1000000ULL;
	return first_ns > ~0ULL - duration ? ~0ULL : first_ns + duration;
}

/*
 * This is not a second retention budget. It is a bounded wake point inside the
 * existing ordinary deadline for the specifically qualified suppressed 2/3
 * post-PACK tail. Saturating addition keeps the helper total for native tests.
 */
static inline unsigned long long
swapz_window_suppressed_tail_resubmit_deadline_ns(
		unsigned long long sample_start_ns)
{
	if (!sample_start_ns)
		return 0;
	return sample_start_ns >
		~0ULL - SWAPZ_SUPPRESSED_TAIL_RESUBMIT_NS ?
		~0ULL :
		sample_start_ns + SWAPZ_SUPPRESSED_TAIL_RESUBMIT_NS;
}

static inline int swapz_window_suppressed_tail_resubmit_expired(
		unsigned long long sample_start_ns,
		unsigned long long now_ns)
{
	if (!sample_start_ns || now_ns < sample_start_ns)
		return 0;
	return now_ns - sample_start_ns >=
		SWAPZ_SUPPRESSED_TAIL_RESUBMIT_NS;
}

static inline int swapz_window_deadline_expired(unsigned long long deadline_ns,
		unsigned long long now_ns)
{
	return !deadline_ns || now_ns >= deadline_ns;
}

/*
 * A queued hrtimer already carries the immutable first-record deadline.
 * Rearm only after the previous timer has dequeued; never extend the window.
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
