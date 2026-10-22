// SPDX-License-Identifier: GPL-2.0-only
#include "predictor-internal.h"
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
	unsigned long long previous = swapz_predictor_load64(input);
	swapz_u64x4 base;
	swapz_u32 offset = SWAPZ_PREDICTOR_U64_BYTES;

	swapz_predictor_store64(output, previous);
	/*
	 * Seed three deltas in scalar so the vector loop starts at byte 32. More
	 * importantly, keep the cumulative carry in YMM: each vector-local prefix
	 * and its total are independent of base, eliminating the per-iteration
	 * YMM->GPR->YMM dependency. Two-way unrolling overlaps both local scans.
	 */
	for (; offset < sizeof(swapz_u64x4);
	     offset += SWAPZ_PREDICTOR_U64_BYTES) {
		previous += swapz_predictor_load64(input + offset);
		swapz_predictor_store64(output + offset, previous);
	}
	base = (swapz_u64x4){previous, previous, previous, previous};
	for (; offset + 2U * sizeof(swapz_u64x4) <= SWAPZ_BLOCK_BYTES;
	     offset += 2U * sizeof(swapz_u64x4)) {
		swapz_u64x4 delta0, delta1, shifted0, shifted1;
		swapz_u64x4 pairs0, pairs1, low0, low1, high0, high1;
		swapz_u64x4 local0, local1, step0, step1, out0, out1;

		memcpy(&delta0, input + offset, sizeof(delta0));
		memcpy(&delta1, input + offset + sizeof(delta0), sizeof(delta1));
		__asm__ volatile("vpslldq $8, %1, %0"
				 : "=x"(shifted0) : "x"(delta0));
		__asm__ volatile("vpslldq $8, %1, %0"
				 : "=x"(shifted1) : "x"(delta1));
		pairs0 = delta0 + shifted0;
		pairs1 = delta1 + shifted1;
		__asm__ volatile("vpermq $0x55, %1, %0"
				 : "=x"(low0) : "x"(pairs0));
		__asm__ volatile("vpermq $0xff, %1, %0"
				 : "=x"(high0) : "x"(pairs0));
		__asm__ volatile("vpermq $0x55, %1, %0"
				 : "=x"(low1) : "x"(pairs1));
		__asm__ volatile("vpermq $0xff, %1, %0"
				 : "=x"(high1) : "x"(pairs1));
		step0 = low0 + high0;
		step1 = low1 + high1;
		local0 = pairs0 + (low0 & upper_mask);
		local1 = pairs1 + (low1 & upper_mask);
		out0 = local0 + base;
		base += step0;
		out1 = local1 + base;
		base += step1;
		memcpy(output + offset, &out0, sizeof(out0));
		memcpy(output + offset + sizeof(out0), &out1, sizeof(out1));
	}
	for (; offset + sizeof(swapz_u64x4) <= SWAPZ_BLOCK_BYTES;
	     offset += sizeof(swapz_u64x4)) {
		swapz_u64x4 delta, shifted, pairs, low, high, local, step, out;

		memcpy(&delta, input + offset, sizeof(delta));
		__asm__ volatile("vpslldq $8, %1, %0"
				 : "=x"(shifted) : "x"(delta));
		pairs = delta + shifted;
		__asm__ volatile("vpermq $0x55, %1, %0"
				 : "=x"(low) : "x"(pairs));
		__asm__ volatile("vpermq $0xff, %1, %0"
				 : "=x"(high) : "x"(pairs));
		step = low + high;
		local = pairs + (low & upper_mask);
		out = local + base;
		base += step;
		memcpy(output + offset, &out, sizeof(out));
	}
}
