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
