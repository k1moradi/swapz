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
	 * Four vectors cover one 64-byte cache line per iteration, halving loop
	 * overhead and the cross-iteration predecessor recurrence versus the
	 * previous two-vector implementation.
	 */
	for (; offset + 4U * sizeof(swapz_u64x2) <= SWAPZ_BLOCK_BYTES;
	     offset += 4U * sizeof(swapz_u64x2)) {
		swapz_u64x2 current0, current1, current2, current3;
		swapz_u64x2 predecessor, delta;

		memcpy(&current0, input + offset, sizeof(current0));
		memcpy(&current1, input + offset + sizeof(current0), sizeof(current1));
		memcpy(&current2, input + offset + 2U * sizeof(current0), sizeof(current2));
		memcpy(&current3, input + offset + 3U * sizeof(current0), sizeof(current3));

		__asm__("ext %0.16b, %1.16b, %2.16b, #8"
			: "=w"(predecessor) : "w"(previous), "w"(current0));
		delta = current0 - predecessor;
		memcpy(output + offset, &delta, sizeof(delta));

		__asm__("ext %0.16b, %1.16b, %2.16b, #8"
			: "=w"(predecessor) : "w"(current0), "w"(current1));
		delta = current1 - predecessor;
		memcpy(output + offset + sizeof(current0), &delta, sizeof(delta));

		__asm__("ext %0.16b, %1.16b, %2.16b, #8"
			: "=w"(predecessor) : "w"(current1), "w"(current2));
		delta = current2 - predecessor;
		memcpy(output + offset + 2U * sizeof(current0), &delta, sizeof(delta));

		__asm__("ext %0.16b, %1.16b, %2.16b, #8"
			: "=w"(predecessor) : "w"(current2), "w"(current3));
		delta = current3 - predecessor;
		memcpy(output + offset + 3U * sizeof(current0), &delta, sizeof(delta));
		previous = current3;
	}
	return 0;
}

void swapz_unpredict_delta64_neon(const swapz_u8 *input, swapz_u8 *output)
{
	const swapz_u64x2 zero = { 0ULL, 0ULL };
	swapz_u64x2 base = { 0ULL, 0ULL };
	swapz_u32 offset = 0;

	/*
	 * Reconstruct one 64-byte cache line per iteration. Each two-lane local
	 * prefix is independent of the incoming base; tree-associate the four
	 * local totals so the loop-carried base recurrence is one packed add per
	 * 64 bytes. Reuse temporaries to keep register pressure bounded.
	 */
	for (; offset + 4U * sizeof(swapz_u64x2) <= SWAPZ_BLOCK_BYTES;
	     offset += 4U * sizeof(swapz_u64x2)) {
		swapz_u64x2 delta, shifted, result;
		swapz_u64x2 local0, local1, local2, local3;
		swapz_u64x2 step0, step1, step2, step3;
		swapz_u64x2 step01, step23, step012, step_quad;

		memcpy(&delta, input + offset, sizeof(delta));
		__asm__("ext %0.16b, %1.16b, %2.16b, #8"
			: "=w"(shifted) : "w"(zero), "w"(delta));
		local0 = delta + shifted;
		__asm__("dup %0.2d, %1.d[1]" : "=w"(step0) : "w"(local0));

		memcpy(&delta, input + offset + sizeof(delta), sizeof(delta));
		__asm__("ext %0.16b, %1.16b, %2.16b, #8"
			: "=w"(shifted) : "w"(zero), "w"(delta));
		local1 = delta + shifted;
		__asm__("dup %0.2d, %1.d[1]" : "=w"(step1) : "w"(local1));

		memcpy(&delta, input + offset + 2U * sizeof(delta), sizeof(delta));
		__asm__("ext %0.16b, %1.16b, %2.16b, #8"
			: "=w"(shifted) : "w"(zero), "w"(delta));
		local2 = delta + shifted;
		__asm__("dup %0.2d, %1.d[1]" : "=w"(step2) : "w"(local2));

		memcpy(&delta, input + offset + 3U * sizeof(delta), sizeof(delta));
		__asm__("ext %0.16b, %1.16b, %2.16b, #8"
			: "=w"(shifted) : "w"(zero), "w"(delta));
		local3 = delta + shifted;
		__asm__("dup %0.2d, %1.d[1]" : "=w"(step3) : "w"(local3));

		step01 = step0 + step1;
		step23 = step2 + step3;
		step012 = step01 + step2;
		step_quad = step01 + step23;

		result = local0 + base;
		memcpy(output + offset, &result, sizeof(result));
		result = local1 + (base + step0);
		memcpy(output + offset + sizeof(result), &result, sizeof(result));
		result = local2 + (base + step01);
		memcpy(output + offset + 2U * sizeof(result), &result, sizeof(result));
		result = local3 + (base + step012);
		memcpy(output + offset + 3U * sizeof(result), &result, sizeof(result));
		base += step_quad;
	}
}
