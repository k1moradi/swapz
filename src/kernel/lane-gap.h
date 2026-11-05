/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_LANE_GAP_H
#define SWAPZ_LANE_GAP_H

#include "codec.h"

/* Pure, passive ID178 accounting. Never consult these results for scheduling. */
#define SWAPZ_LANE_SUCCESSOR_BINS 6U
#define SWAPZ_LANE_DWELL_BINS 7U

struct swapz_lane_gap_parts {
	swapz_u64 completion_wake_ns;
	swapz_u64 publication_ns;
	swapz_u64 no_work_ns;
	swapz_u64 admitted_unowned_ns;
	swapz_u64 staged_held_ns;
	swapz_u64 seal_ns;
};

static inline swapz_u64 swapz_lane_gap_clamp(swapz_u64 value,
					 swapz_u64 minimum, swapz_u64 maximum)
{
	if (value < minimum)
		return minimum;
	return value > maximum ? maximum : value;
}

/* Missing/reversed endpoints are invalid; do not modify the caller's output. */
static inline int swapz_lane_gap_partition(
	swapz_u64 completion_ns, swapz_u64 owner_ns, swapz_u64 publication_ns,
	swapz_u64 admission_ns, swapz_u64 ownership_ns, swapz_u64 seal_ns,
	swapz_u64 submit_ns, struct swapz_lane_gap_parts *parts)
{
	struct swapz_lane_gap_parts measured;
	swapz_u64 observed, published, admitted, owned, sealed;

	if (!parts || !completion_ns || !owner_ns || !publication_ns ||
	    !admission_ns || !ownership_ns || !seal_ns || !submit_ns ||
	    submit_ns < completion_ns)
		return 0;
	observed = swapz_lane_gap_clamp(owner_ns, completion_ns, submit_ns);
	published = swapz_lane_gap_clamp(publication_ns, observed, submit_ns);
	admitted = swapz_lane_gap_clamp(admission_ns, published, submit_ns);
	owned = swapz_lane_gap_clamp(ownership_ns, admitted, submit_ns);
	sealed = swapz_lane_gap_clamp(seal_ns, owned, submit_ns);
	measured.completion_wake_ns = observed - completion_ns;
	measured.publication_ns = published - observed;
	measured.no_work_ns = admitted - published;
	measured.admitted_unowned_ns = owned - admitted;
	measured.staged_held_ns = sealed - owned;
	measured.seal_ns = submit_ns - sealed;
	*parts = measured;
	return 1;
}

/* Successor counts: 0, 1, 2-3, 4-7, 8-15, 16+. */
static inline unsigned int swapz_lane_gap_successor_bin(unsigned int count)
{
	if (!count)
		return 0;
	if (count == 1)
		return 1;
	if (count <= 3)
		return 2;
	if (count <= 7)
		return 3;
	return count <= 15 ? 4 : 5;
}

/* Inclusive upper bounds: 1, 4, 16, 64, 256, 1000 us; then >1 ms. */
static inline unsigned int swapz_lane_gap_dwell_bin(swapz_u64 nanoseconds)
{
	if (nanoseconds <= 1000)
		return 0;
	if (nanoseconds <= 4000)
		return 1;
	if (nanoseconds <= 16000)
		return 2;
	if (nanoseconds <= 64000)
		return 3;
	if (nanoseconds <= 256000)
		return 4;
	return nanoseconds <= 1000000 ? 5 : 6;
}
#endif
