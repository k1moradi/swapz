// SPDX-License-Identifier: GPL-2.0-only
#include "predictor-internal.h"
/* AArch64 vector types lower to Advanced SIMD/NEON under kernel FPU flags. */
typedef unsigned long long swapz_u64x2 __attribute__((vector_size(16)));

swapz_u32 swapz_predict_delta64_neon(const swapz_u8 *input, swapz_u8 *output)
{
	swapz_u64x2 previous = { 0ULL, 0ULL };
	swapz_u32 offset = 0;

	/*
	 * Use virtual x[-1] = 0 so the vector loop emits y[0] = x[0].
	 * Two vectors cover 32 bytes per iteration with naturally aligned accesses.
	 */
	for (; offset + 2U * sizeof(swapz_u64x2) <= SWAPZ_BLOCK_BYTES;
	     offset += 2U * sizeof(swapz_u64x2)) {
		swapz_u64x2 current0, current1, predecessor0, predecessor1;
		swapz_u64x2 delta0, delta1;

		memcpy(&current0, input + offset, sizeof(current0));
		memcpy(&current1, input + offset + sizeof(current0),
		       sizeof(current1));
		__asm__("ext %0.16b, %1.16b, %2.16b, #8"
			: "=w"(predecessor0) : "w"(previous), "w"(current0));
		__asm__("ext %0.16b, %1.16b, %2.16b, #8"
			: "=w"(predecessor1) : "w"(current0), "w"(current1));
		delta0 = current0 - predecessor0;
		delta1 = current1 - predecessor1;
		memcpy(output + offset, &delta0, sizeof(delta0));
		memcpy(output + offset + sizeof(delta0), &delta1,
		       sizeof(delta1));
		previous = current1;
	}
	return 0;
}

void swapz_unpredict_delta64_neon(const swapz_u8 *input, swapz_u8 *output)
{
	const swapz_u64x2 zero = { 0ULL, 0ULL };
	swapz_u64x2 base = { 0ULL, 0ULL };
	swapz_u32 offset = 0;

	/*
	 * Inclusive-prefix reconstruction also starts from virtual base zero.
	 * Keep the pair carry entirely in NEON and tree-associate the two local
	 * totals so the loop-carried base recurrence is one packed add per 32B.
	 */
	for (; offset + 2U * sizeof(swapz_u64x2) <= SWAPZ_BLOCK_BYTES;
	     offset += 2U * sizeof(swapz_u64x2)) {
		swapz_u64x2 delta0, delta1, shifted0, shifted1;
		swapz_u64x2 local0, local1, step0, step1, step_pair;
		swapz_u64x2 out0, out1;

		memcpy(&delta0, input + offset, sizeof(delta0));
		memcpy(&delta1, input + offset + sizeof(delta0), sizeof(delta1));
		__asm__("ext %0.16b, %1.16b, %2.16b, #8"
			: "=w"(shifted0) : "w"(zero), "w"(delta0));
		__asm__("ext %0.16b, %1.16b, %2.16b, #8"
			: "=w"(shifted1) : "w"(zero), "w"(delta1));
		local0 = delta0 + shifted0;
		local1 = delta1 + shifted1;
		__asm__("dup %0.2d, %1.d[1]" : "=w"(step0) : "w"(local0));
		__asm__("dup %0.2d, %1.d[1]" : "=w"(step1) : "w"(local1));
		step_pair = step0 + step1;
		out0 = local0 + base;
		out1 = local1 + (base + step0);
		base += step_pair;
		memcpy(output + offset, &out0, sizeof(out0));
		memcpy(output + offset + sizeof(out0), &out1, sizeof(out1));
	}
}
