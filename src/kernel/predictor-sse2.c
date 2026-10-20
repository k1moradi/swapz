// SPDX-License-Identifier: GPL-2.0-only
#include "predictor-internal.h"
typedef unsigned long long swapz_u64x2 __attribute__((vector_size(16)));
union swapz_vec128 { swapz_u64x2 u64; };
swapz_u32 swapz_predict_delta64_sse2(const swapz_u8 *input, swapz_u8 *output)
{
	swapz_u32 offset = SWAPZ_PREDICTOR_U64_BYTES;
	swapz_predictor_store64(output, swapz_predictor_load64(input));
	for (; offset + sizeof(swapz_u64x2) <= SWAPZ_BLOCK_BYTES; offset += sizeof(swapz_u64x2)) {
		swapz_u64x2 value, previous, delta;
		memcpy(&value, input + offset, sizeof(value));
		memcpy(&previous, input + offset - SWAPZ_PREDICTOR_U64_BYTES, sizeof(previous));
		delta = value - previous; memcpy(output + offset, &delta, sizeof(delta));
	}
	for (; offset < SWAPZ_BLOCK_BYTES; offset += SWAPZ_PREDICTOR_U64_BYTES) {
		unsigned long long value = swapz_predictor_load64(input + offset);
		unsigned long long previous = swapz_predictor_load64(input + offset - SWAPZ_PREDICTOR_U64_BYTES);
		swapz_predictor_store64(output + offset, value - previous);
	}
	return 0;
}
void swapz_unpredict_delta64_sse2(const swapz_u8 *input, swapz_u8 *output)
{
	unsigned long long previous = swapz_predictor_load64(input);
	swapz_u32 offset = SWAPZ_PREDICTOR_U64_BYTES;
	swapz_predictor_store64(output, previous);
	for (; offset + sizeof(swapz_u64x2) <= SWAPZ_BLOCK_BYTES; offset += sizeof(swapz_u64x2)) {
		union swapz_vec128 delta, prefix; swapz_u64x2 shifted, base;
		memcpy(&delta.u64, input + offset, sizeof(delta.u64));
		shifted = (swapz_u64x2){0ULL, delta.u64[0]}; prefix.u64 = delta.u64 + shifted;
		base = (swapz_u64x2){previous, previous}; prefix.u64 += base;
		memcpy(output + offset, &prefix.u64, sizeof(prefix.u64)); previous = prefix.u64[1];
	}
	for (; offset < SWAPZ_BLOCK_BYTES; offset += SWAPZ_PREDICTOR_U64_BYTES) {
		previous += swapz_predictor_load64(input + offset);
		swapz_predictor_store64(output + offset, previous);
	}
}
