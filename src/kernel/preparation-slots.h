/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_PREPARATION_SLOTS_H
#define SWAPZ_PREPARATION_SLOTS_H

#include "codec.h"
#ifdef __KERNEL__
#include <linux/atomic.h>
#include <linux/bitops.h>
#endif

#if SWAPZ_MAX_RECORDS != 64U
#error "swapz preparation slots require exactly 64 records"
#endif

#define SWAPZ_PREPARATION_FREE_MASK (~0ULL)

enum swapz_preparation_state {
	SWAPZ_PREPARATION_EMPTY = 0,
	SWAPZ_PREPARATION_PREPARING,
	SWAPZ_PREPARATION_READY_COMPRESSED,
	SWAPZ_PREPARATION_READY_RAW,
	SWAPZ_PREPARATION_RAW_SELECTED,
	SWAPZ_PREPARATION_ERROR,
	/* Consumer abandoned a still-running candidate after terminal failure. */
	SWAPZ_PREPARATION_CANCELLED,
	/* A READY representation has been consumed or discarded exactly once. */
	SWAPZ_PREPARATION_CONSUMED,
};

static inline int swapz_preparation_read_state(const atomic_t *state)
{
	/*
	 * READY publishes payload metadata and bytes before the state change.
	 * Use acquire ordering for non-RMW observation on weakly ordered CPUs.
	 */
	return atomic_read_acquire(state);
}

static inline int swapz_preparation_select_raw(atomic_t *state)
{
	int observed = swapz_preparation_read_state(state);

	if (observed == SWAPZ_PREPARATION_PREPARING) {
		observed = atomic_cmpxchg(state, SWAPZ_PREPARATION_PREPARING,
					 SWAPZ_PREPARATION_RAW_SELECTED);
		/*
		 * A failed conditional RMW need not acquire READY publication.
		 * The consumer still holds its page reference: acquire that stable
		 * state before using the producer's immutable payload metadata.
		 */
		if (observed != SWAPZ_PREPARATION_PREPARING)
			return swapz_preparation_read_state(state);
	}
	return observed == SWAPZ_PREPARATION_PREPARING ?
		SWAPZ_PREPARATION_RAW_SELECTED : observed;
}

/*
 * Terminal failure may complete a BIO before its speculative codec producer
 * publishes. CANCELLED prevents that late result from becoming orphaned READY
 * work. If READY already won, transition it to CONSUMED so its ready counter
 * has exactly one owner responsible for decrementing it.
 */
static inline int swapz_preparation_retire(atomic_t *state)
{
	int observed = swapz_preparation_read_state(state);

	for (;;) {
		int replacement;

		if (observed == SWAPZ_PREPARATION_PREPARING)
			replacement = SWAPZ_PREPARATION_CANCELLED;
		else if (observed == SWAPZ_PREPARATION_READY_COMPRESSED ||
			 observed == SWAPZ_PREPARATION_READY_RAW)
			replacement = SWAPZ_PREPARATION_CONSUMED;
		else
			return observed;

		if (atomic_cmpxchg(state, observed, replacement) == observed)
			return replacement == SWAPZ_PREPARATION_CANCELLED ?
				SWAPZ_PREPARATION_CANCELLED : observed;
		/* Failed conditional RMW is not an acquire of READY publication. */
		observed = swapz_preparation_read_state(state);
	}
}

/* Return the READY state only for the caller that consumes it exactly once. */
static inline int swapz_preparation_consume_ready(atomic_t *state)
{
	int observed = swapz_preparation_read_state(state);

	if (observed != SWAPZ_PREPARATION_READY_COMPRESSED &&
	    observed != SWAPZ_PREPARATION_READY_RAW)
		return observed;
	if (atomic_cmpxchg(state, observed, SWAPZ_PREPARATION_CONSUMED) == observed)
		return observed;
	return swapz_preparation_read_state(state);
}

static inline int swapz_preparation_publish_result(atomic_t *state,
						   int ready_state)
{
	if (ready_state != SWAPZ_PREPARATION_READY_COMPRESSED &&
	    ready_state != SWAPZ_PREPARATION_READY_RAW)
		return SWAPZ_PREPARATION_ERROR;
	return atomic_cmpxchg(state, SWAPZ_PREPARATION_PREPARING, ready_state);
}

/*
 * swapz_compress_page() has three distinct outcomes: positive means a valid
 * compressed payload, zero is the ordinary no-fit RAW fallback, and a negative
 * errno is a genuine codec/preparation error. Never collapse a negative result
 * into READY_RAW. A caller publishing ERROR must make its exact errno visible
 * before this terminal state; if RAW_SELECTED already won the speculative
 * representation race, the caller still owns fail-closed error handling.
 */
static inline int swapz_preparation_codec_result_state(int codec_result)
{
	if (codec_result < 0)
		return SWAPZ_PREPARATION_ERROR;
	return codec_result == 0 ? SWAPZ_PREPARATION_READY_RAW :
		SWAPZ_PREPARATION_READY_COMPRESSED;
}

static inline int swapz_preparation_publish_codec_result(atomic_t *state,
							 int codec_result)
{
	return atomic_cmpxchg(state, SWAPZ_PREPARATION_PREPARING,
			      swapz_preparation_codec_result_state(codec_result));
}

/*
 * The final preparation-workqueue drain runs after the ordered workqueue has
 * drained. Once admission is closed, a producer finishing there must not
 * publish a fresh ordered-worker wake. A producer that observed open admission
 * before closure is joined by the first preparation drain, so the later
 * ordered drain still catches its wake. Callers sample admission and publish
 * any wake while holding the same queue_lock that closes admission.
 */
static inline int swapz_preparation_owner_wake_allowed(int accepting)
{
	return accepting != 0;
}

/*
 * Bounded preparers may clear bits concurrently; cmpxchg keeps each claim
 * unique and consumers return bits only after their slot use is complete.
 * During a claim at most 64 occupied slots can be returned, so 65 attempts
 * suffice. A failed claim must fall back without waiting for capacity.
 */
static inline int swapz_preparation_claim_slot(atomic64_t *free_mask)
{
	unsigned int attempt, slot;
	unsigned long long mask;

	for (attempt = 0; attempt <= SWAPZ_MAX_RECORDS; ++attempt) {
		mask = (unsigned long long)atomic64_read(free_mask);
		if (!mask)
			return -1;
		slot = __ffs64(mask);
		/* Full ordering on success orders reuse after the owner's release. */
		if ((unsigned long long)atomic64_cmpxchg(free_mask, (s64)mask,
				(s64)(mask & ~(1ULL << slot))) == mask)
			return (int)slot;
	}
	return -1;
}

static inline void swapz_preparation_release_slot(atomic64_t *free_mask,
						 unsigned int slot)
{
	/* atomic64_or alone is relaxed: finish all reads before reuse. */
	smp_mb__before_atomic();
	atomic64_or((s64)(1ULL << slot), free_mask);
}

#endif
