/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_PREDICTOR_ROUTE_H
#define SWAPZ_PREDICTOR_ROUTE_H

#include "engine.h"
#include "predictor.h"

#define SWAPZ_PREDICTOR_RESCUE_MIN_LENGTH 2024U

/* Shared production/native eligibility and candidate-adoption policy. */
struct swapz_delta64_route {
	swapz_u16 pack_limit;
	swapz_u8 threshold;
	swapz_u8 pack_path;
};

static inline int swapz_delta64_route_init(
	int baseline_length, struct swapz_delta64_route *route)
{
	if (!route)
		return 0;

	route->pack_limit = 0;
	route->threshold = 0;
	route->pack_path = 0;
	if (baseline_length > (int)SWAPZ_BLOCK_BYTES)
		return 0;
	if (baseline_length <= 0 ||
	    baseline_length > (int)SWAPZ_PREDICTOR_RESCUE_MIN_LENGTH) {
		route->threshold = SWAPZ_PREDICTOR_PRODUCTION_THRESHOLD;
		return 1;
	}

	route->pack_limit = swapz_engine_next_uniform_pack_limit(
		(swapz_u16)baseline_length);
	if (!route->pack_limit)
		return 0;
	route->pack_path = 1;
	route->threshold = SWAPZ_PREDICTOR_PACK_THRESHOLD;
	return 1;
}

static inline int swapz_delta64_candidate_smaller(int baseline_length,
						  int candidate_length)
{
	return candidate_length > 0 &&
		(baseline_length <= 0 || candidate_length < baseline_length);
}

static inline int swapz_delta64_candidate_adoptable(
	const struct swapz_delta64_route *route, int baseline_length,
	int candidate_length)
{
	return route && route->threshold &&
		swapz_delta64_candidate_smaller(baseline_length,
						candidate_length) &&
		(!route->pack_path ||
		 candidate_length <= (int)route->pack_limit);
}

#endif
