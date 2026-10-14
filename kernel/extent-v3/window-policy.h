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
 * Alpha.13 early-commit: after eight independent compressed writes are
 * staged, the LARGEST seven payloads plus the exact V3 header and seven
 * record descriptors must fit a 16KiB extent; the eighth valid compressed
 * page fits 4KiB. The byte-minimal planner can therefore use at most
 * 20KiB instead of eight standalone 4KiB blocks (32KiB).
 *
 * This is only a geometry bound, not a lower-I/O request or p99 guarantee.
 * It never acknowledges BIOs, stages extents, or publishes a mapping.
 * Restricted-read, nonretained, RAW and invalid batches are excluded.
 * The serialized caller has already fenced FUA, duplicate slots, and
 * other dependencies.
 */
static inline int sv3_window_pack_ready(
		const struct sv3_pending_bio *pending, sv3_u8 count,
		sv3_u8 retain_ms, sv3_u8 read_budget)
{
	sv3_u32 largest_seven_bytes = sizeof(struct sv3_header) +
		7U * sizeof(struct sv3_record);
	sv3_u16 shortest = SV3_MAX_COMPRESSED;
	sv3_u8 i;

	if (!retain_ms || read_budget || count != 8U || !pending)
		return 0;
	for (i = 0; i < count; ++i) {
		if (pending[i].raw || !pending[i].length ||
		    pending[i].length > SV3_MAX_COMPRESSED)
			return 0;
		largest_seven_bytes += pending[i].length;
		if (pending[i].length < shortest)
			shortest = pending[i].length;
	}
	/* Worst-case seven remain valid after length-based reordering. */
	return largest_seven_bytes - shortest <= SV3_MAX_EXTENT_BYTES;
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
