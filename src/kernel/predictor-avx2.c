// SPDX-License-Identifier: GPL-2.0-only
#include "predictor-internal.h"
typedef unsigned long long swapz_u64x4 __attribute__((vector_size(32)));
union swapz_vec256 { swapz_u64x4 u64; };
swapz_u32 swapz_predict_delta64_avx2(const swapz_u8 *input, swapz_u8 *output)
{
	swapz_u32 offset = SWAPZ_PREDICTOR_U64_BYTES;
	swapz_predictor_store64(output, swapz_predictor_load64(input));
	for (; offset + sizeof(swapz_u64x4) <= SWAPZ_BLOCK_BYTES; offset += sizeof(swapz_u64x4)) {
		swapz_u64x4 value, previous, delta;
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
void swapz_unpredict_delta64_avx2(const swapz_u8 *input, swapz_u8 *output)
{
	const swapz_u64x4 upper_mask = {0ULL, 0ULL, ~0ULL, ~0ULL};
	unsigned long long previous = swapz_predictor_load64(input);
	swapz_u32 offset = SWAPZ_PREDICTOR_U64_BYTES;
	swapz_predictor_store64(output, previous);
	for (; offset + sizeof(swapz_u64x4) <= SWAPZ_BLOCK_BYTES; offset += sizeof(swapz_u64x4)) {
		union swapz_vec256 delta, prefix; swapz_u64x4 shifted, upper_carry, base;
		memcpy(&delta.u64, input + offset, sizeof(delta.u64));
		__asm__ volatile("vpslldq $8, %1, %0" : "=x"(shifted) : "x"(delta.u64));
		prefix.u64 = delta.u64 + shifted;
		__asm__ volatile("vpermq $0x55, %1, %0" : "=x"(upper_carry) : "x"(prefix.u64));
		upper_carry &= upper_mask; prefix.u64 += upper_carry;
		base = (swapz_u64x4){previous, previous, previous, previous}; prefix.u64 += base;
		memcpy(output + offset, &prefix.u64, sizeof(prefix.u64)); previous = prefix.u64[3];
	}
	for (; offset < SWAPZ_BLOCK_BYTES; offset += SWAPZ_PREDICTOR_U64_BYTES) {
		previous += swapz_predictor_load64(input + offset);
		swapz_predictor_store64(output + offset, previous);
	}
}
