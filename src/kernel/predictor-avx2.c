// SPDX-License-Identifier: GPL-2.0-only
#include "predictor-internal.h"
#include "predictor-shuffle.h"
typedef unsigned long long swapz_u64x4 __attribute__((vector_size(32)));
union swapz_vec256 { swapz_u64x4 u64; };
swapz_u32 swapz_predict_delta64_avx2(const swapz_u8 *input, swapz_u8 *output)
{
	unsigned long long previous = swapz_predictor_load64(input);
	swapz_u32 offset = SWAPZ_PREDICTOR_U64_BYTES;

	swapz_predictor_store64(output, previous);
	/*
	 * Seed three scalar deltas so current-block loads and output stores start
	 * at byte 32. Page-backed inputs are naturally aligned; the predecessor
	 * load remains intentionally overlapping to preserve the exact format.
	 */
	for (; offset < sizeof(swapz_u64x4);
	     offset += SWAPZ_PREDICTOR_U64_BYTES) {
		unsigned long long value = swapz_predictor_load64(input + offset);

		swapz_predictor_store64(output + offset, value - previous);
		previous = value;
	}
	for (; offset + sizeof(swapz_u64x4) <= SWAPZ_BLOCK_BYTES;
	     offset += sizeof(swapz_u64x4)) {
		swapz_u64x4 value, previous_vec, delta;

		memcpy(&value, input + offset, sizeof(value));
		memcpy(&previous_vec,
		       input + offset - SWAPZ_PREDICTOR_U64_BYTES,
		       sizeof(previous_vec));
		delta = value - previous_vec;
		memcpy(output + offset, &delta, sizeof(delta));
	}
	return 0;
}

void swapz_unpredict_delta64_avx2(const swapz_u8 *input, swapz_u8 *output)
{
	const swapz_u64x4 upper_mask = {0ULL, 0ULL, ~0ULL, ~0ULL};
	swapz_u64x4 base = {0ULL, 0ULL, 0ULL, 0ULL};
	swapz_u32 offset = 0;

	/*
	 * Reconstruct from virtual x[-1] = 0 so YMM loads/stores are aligned.
	 * Tree-associate the two local totals so the loop-carried recurrence is
	 * one packed add per 64B while both vector-local scans execute ahead.
	 */
	for (; offset + 2U * sizeof(swapz_u64x4) <= SWAPZ_BLOCK_BYTES;
	     offset += 2U * sizeof(swapz_u64x4)) {
		swapz_u64x4 delta0, delta1, shifted0, shifted1;
		swapz_u64x4 pairs0, pairs1, low0, low1, high0, high1;
		swapz_u64x4 local0, local1, step0, step1, step_pair;
		swapz_u64x4 out0, out1;

		memcpy(&delta0, input + offset, sizeof(delta0));
		memcpy(&delta1, input + offset + sizeof(delta0), sizeof(delta1));
		__asm__("vpslldq $8, %1, %0"
			: "=x"(shifted0) : "x"(delta0));
		__asm__("vpslldq $8, %1, %0"
			: "=x"(shifted1) : "x"(delta1));
		pairs0 = delta0 + shifted0;
		pairs1 = delta1 + shifted1;
		__asm__("vpermq $0x55, %1, %0"
			: "=x"(low0) : "x"(pairs0));
		__asm__("vpermq $0xff, %1, %0"
			: "=x"(high0) : "x"(pairs0));
		__asm__("vpermq $0x55, %1, %0"
			: "=x"(low1) : "x"(pairs1));
		__asm__("vpermq $0xff, %1, %0"
			: "=x"(high1) : "x"(pairs1));
		step0 = low0 + high0;
		step1 = low1 + high1;
		step_pair = step0 + step1;
		local0 = pairs0 + (low0 & upper_mask);
		local1 = pairs1 + (low1 & upper_mask);
		out0 = local0 + base;
		out1 = local1 + (base + step0);
		base += step_pair;
		memcpy(output + offset, &out0, sizeof(out0));
		memcpy(output + offset + sizeof(out0), &out1, sizeof(out1));
	}
}

/* Byte-plane shuffle stage of DELTA64_SHUF8, built with this unit's ISA. */
void swapz_shuffle8_avx2(const swapz_u8 *input, swapz_u8 *output)
{
	swapz_shuffle8_vector(input, output);
}

void swapz_unshuffle8_avx2(const swapz_u8 *input, swapz_u8 *output)
{
	swapz_unshuffle8_vector(input, output);
}
