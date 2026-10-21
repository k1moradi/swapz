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

/*
 * One serialized producer clears bits; consumers only return them. During a
 * claim at most 64 occupied slots can be returned, so 65 attempts suffice.
 * A failed claim leaves the BIO available for the ordered worker's inline
 * preparation. Never wait for capacity after claiming a FIFO descriptor.
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
