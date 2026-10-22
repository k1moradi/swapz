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
	 * Keep vector stores on 16-byte boundaries on Core-2-class x86. The
	 * one scalar delta pays for eliminating a split vector store per pair.
	 */
	swapz_predictor_store64(output, previous);
	swapz_predictor_store64(output + SWAPZ_PREDICTOR_U64_BYTES,
			       value - previous);
	memcpy(&previous_values, input, sizeof(previous_values));
	for (; offset + sizeof(swapz_u64x2) <= SWAPZ_BLOCK_BYTES;
	     offset += sizeof(swapz_u64x2)) {
		swapz_u64x2 values, predecessors, delta;

		/*
		 * Retain the preceding input pair in-register. SHUFPD imm=1 forms
		 * [previous.high, current.low], so every 16-byte result needs only
		 * one new 16-byte input load instead of two overlapping loads.
		 */
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

#ifndef __KERNEL__
/*
 * Native A/B candidate only: leave the production SSE2 encoder unchanged.
 * Each pair has independent load/shuffle/subtract work and a shared retained
 * previous input vector. No encoded-format or alignment assumptions change.
 */
swapz_u32 swapz_predict_delta64_sse2_unrolled(const swapz_u8 *input,
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
#endif

void swapz_unpredict_delta64_sse2(const swapz_u8 *input, swapz_u8 *output)
{
	unsigned long long previous = swapz_predictor_load64(input);
	swapz_u64x2 base;
	swapz_u32 offset = 2U * SWAPZ_PREDICTOR_U64_BYTES;

	swapz_predictor_store64(output, previous);
	previous += swapz_predictor_load64(
		input + SWAPZ_PREDICTOR_U64_BYTES);
	swapz_predictor_store64(output + SWAPZ_PREDICTOR_U64_BYTES, previous);
	base = (swapz_u64x2){previous, previous};
	/*
	 * Compute each pair-local prefix independently from the loop-carried
	 * carry. The high qword is broadcast before base is added, so the next
	 * iteration depends only on one packed add instead of an XMM->GPR->XMM
	 * round trip. Two-way unrolling lets both local scans execute ahead.
	 */
	for (; offset + 2U * sizeof(swapz_u64x2) <= SWAPZ_BLOCK_BYTES;
	     offset += 2U * sizeof(swapz_u64x2)) {
		swapz_u64x2 delta0, delta1, shifted0, shifted1;
		swapz_u64x2 local0, local1, step0, step1, out0, out1;

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
		out0 = local0 + base;
		base += step0;
		out1 = local1 + base;
		base += step1;
		memcpy(output + offset, &out0, sizeof(out0));
		memcpy(output + offset + sizeof(out0), &out1, sizeof(out1));
	}
	for (; offset + sizeof(swapz_u64x2) <= SWAPZ_BLOCK_BYTES;
	     offset += sizeof(swapz_u64x2)) {
		swapz_u64x2 delta, shifted, local, step, out;

		memcpy(&delta, input + offset, sizeof(delta));
		shifted = delta;
		__asm__("pslldq $8, %0" : "+x"(shifted));
		local = delta + shifted;
		__asm__("pshufd $0xee, %1, %0"
			: "=x"(step) : "x"(local));
		out = local + base;
		base += step;
		memcpy(output + offset, &out, sizeof(out));
	}
}
