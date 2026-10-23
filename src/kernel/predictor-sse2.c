// SPDX-License-Identifier: GPL-2.0-only
#include "predictor-internal.h"
typedef unsigned long long swapz_u64x2 __attribute__((vector_size(16)));
union swapz_vec128 { swapz_u64x2 u64; };
swapz_u32 swapz_predict_delta64_sse2(const swapz_u8 *input, swapz_u8 *output)
{
	unsigned long long previous = swapz_predictor_load64(input);
	unsigned long long value = swapz_predictor_load64(
		input + SWAPZ_PREDICTOR_U64_BYTES);
	swapz_u64x2 previous_values;
	swapz_u32 offset = 2U * SWAPZ_PREDICTOR_U64_BYTES;

	/*
	 * Same format and aligned prologue as the qualified baseline. Process two
	 * independent XMM pairs per iteration so load/shuffle/subtract work can
	 * overlap while retaining only the preceding input pair as loop state.
	 * Two same-host machines measured this exact form faster than the 1x loop.
	 */
	swapz_predictor_store64(output, previous);
	swapz_predictor_store64(output + SWAPZ_PREDICTOR_U64_BYTES,
			       value - previous);
	memcpy(&previous_values, input, sizeof(previous_values));
	for (; offset + 2U * sizeof(swapz_u64x2) <= SWAPZ_BLOCK_BYTES;
	     offset += 2U * sizeof(swapz_u64x2)) {
		swapz_u64x2 values0, values1, predecessors0, predecessors1;
		swapz_u64x2 delta0, delta1;

		memcpy(&values0, input + offset, sizeof(values0));
		memcpy(&values1, input + offset + sizeof(values0),
		       sizeof(values1));
		predecessors0 = previous_values;
		predecessors1 = values0;
		__asm__("shufpd $1, %1, %0"
			: "+x"(predecessors0) : "x"(values0));
		__asm__("shufpd $1, %1, %0"
			: "+x"(predecessors1) : "x"(values1));
		delta0 = values0 - predecessors0;
		delta1 = values1 - predecessors1;
		memcpy(output + offset, &delta0, sizeof(delta0));
		memcpy(output + offset + sizeof(delta0), &delta1,
		       sizeof(delta1));
		previous_values = values1;
	}
	for (; offset + sizeof(swapz_u64x2) <= SWAPZ_BLOCK_BYTES;
	     offset += sizeof(swapz_u64x2)) {
		swapz_u64x2 values, predecessors, delta;

		memcpy(&values, input + offset, sizeof(values));
		predecessors = previous_values;
		__asm__("shufpd $1, %1, %0"
			: "+x"(predecessors) : "x"(values));
		delta = values - predecessors;
		memcpy(output + offset, &delta, sizeof(delta));
		previous_values = values;
	}
	return 0;
}

#ifndef __KERNEL__
/*
 * Native-only pre-promotion baseline. Keeping the old 1x loop here preserves
 * a same-host regression control without exposing it to kernel dispatch.
 */
swapz_u32 swapz_predict_delta64_sse2_baseline(const swapz_u8 *input,
					      swapz_u8 *output)
{
	unsigned long long previous = swapz_predictor_load64(input);
	unsigned long long value = swapz_predictor_load64(
		input + SWAPZ_PREDICTOR_U64_BYTES);
	swapz_u64x2 previous_values;
	swapz_u32 offset = 2U * SWAPZ_PREDICTOR_U64_BYTES;

	swapz_predictor_store64(output, previous);
	swapz_predictor_store64(output + SWAPZ_PREDICTOR_U64_BYTES,
			       value - previous);
	memcpy(&previous_values, input, sizeof(previous_values));
	for (; offset + sizeof(swapz_u64x2) <= SWAPZ_BLOCK_BYTES;
	     offset += sizeof(swapz_u64x2)) {
		swapz_u64x2 values, predecessors, delta;

		memcpy(&values, input + offset, sizeof(values));
		predecessors = previous_values;
		__asm__("shufpd $1, %1, %0"
			: "+x"(predecessors)
			: "x"(values));
		delta = values - predecessors;
		memcpy(output + offset, &delta, sizeof(delta));
		previous_values = values;
	}
	return 0;
}
#endif

void swapz_unpredict_delta64_sse2(const swapz_u8 *input, swapz_u8 *output)
{
	swapz_u64x2 base = { 0ULL, 0ULL };
	swapz_u32 offset = 0;

	/*
	 * Reconstruct from virtual x[-1] = 0 so every XMM load/store is aligned.
	 * Tree-associate each two-vector carry: both local scans are independent
	 * of the loop-carried base and the recurrence is one packed add per 32B.
	 */
	for (; offset + 2U * sizeof(swapz_u64x2) <= SWAPZ_BLOCK_BYTES;
	     offset += 2U * sizeof(swapz_u64x2)) {
		swapz_u64x2 delta0, delta1, shifted0, shifted1;
		swapz_u64x2 local0, local1, step0, step1, step_pair;
		swapz_u64x2 out0, out1;

		memcpy(&delta0, input + offset, sizeof(delta0));
		memcpy(&delta1, input + offset + sizeof(delta0), sizeof(delta1));
		shifted0 = delta0;
		shifted1 = delta1;
		__asm__("pslldq $8, %0" : "+x"(shifted0));
		__asm__("pslldq $8, %0" : "+x"(shifted1));
		local0 = delta0 + shifted0;
		local1 = delta1 + shifted1;
		__asm__("pshufd $0xee, %1, %0"
			: "=x"(step0) : "x"(local0));
		__asm__("pshufd $0xee, %1, %0"
			: "=x"(step1) : "x"(local1));
		step_pair = step0 + step1;
		out0 = local0 + base;
		out1 = local1 + (base + step0);
		base += step_pair;
		memcpy(output + offset, &out0, sizeof(out0));
		memcpy(output + offset + sizeof(out0), &out1, sizeof(out1));
	}
}
