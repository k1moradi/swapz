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
