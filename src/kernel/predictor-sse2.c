// SPDX-License-Identifier: GPL-2.0-only
#include "predictor-internal.h"
typedef unsigned long long swapz_u64x2 __attribute__((vector_size(16)));
union swapz_vec128 { swapz_u64x2 u64; };
swapz_u32 swapz_predict_delta64_sse2(const swapz_u8 *input, swapz_u8 *output)
{
	unsigned long long previous = swapz_predictor_load64(input);
	unsigned long long value = swapz_predictor_load64(
		input + SWAPZ_PREDICTOR_U64_BYTES);
	swapz_u32 offset = 2U * SWAPZ_PREDICTOR_U64_BYTES;

	/*
	 * Keep vector stores on 16-byte boundaries on Core-2-class x86. The
	 * one scalar delta pays for eliminating a split vector store per pair.
	 */
	swapz_predictor_store64(output, previous);
	swapz_predictor_store64(output + SWAPZ_PREDICTOR_U64_BYTES,
			       value - previous);
	for (; offset + sizeof(swapz_u64x2) <= SWAPZ_BLOCK_BYTES;
	     offset += sizeof(swapz_u64x2)) {
		swapz_u64x2 values, predecessors, delta;

		memcpy(&values, input + offset, sizeof(values));
		memcpy(&predecessors,
		       input + offset - SWAPZ_PREDICTOR_U64_BYTES,
		       sizeof(predecessors));
		delta = values - predecessors;
		memcpy(output + offset, &delta, sizeof(delta));
	}
	return 0;
}

void swapz_unpredict_delta64_sse2(const swapz_u8 *input, swapz_u8 *output)
{
	unsigned long long previous = swapz_predictor_load64(input);
	swapz_u32 offset = 2U * SWAPZ_PREDICTOR_U64_BYTES;

	swapz_predictor_store64(output, previous);
	previous += swapz_predictor_load64(
		input + SWAPZ_PREDICTOR_U64_BYTES);
	swapz_predictor_store64(output + SWAPZ_PREDICTOR_U64_BYTES, previous);
	/*
	 * Starting at byte 16 keeps both vector input and output accesses on
	 * pair boundaries; the old byte-8 loop forced split SIMD accesses.
	 */
	for (; offset + sizeof(swapz_u64x2) <= SWAPZ_BLOCK_BYTES;
	     offset += sizeof(swapz_u64x2)) {
		union swapz_vec128 delta, prefix;
		swapz_u64x2 shifted, base;

		memcpy(&delta.u64, input + offset, sizeof(delta.u64));
		shifted = (swapz_u64x2){0ULL, delta.u64[0]};
		prefix.u64 = delta.u64 + shifted;
		base = (swapz_u64x2){previous, previous};
		prefix.u64 += base;
		memcpy(output + offset, &prefix.u64, sizeof(prefix.u64));
		previous = prefix.u64[1];
	}
}
