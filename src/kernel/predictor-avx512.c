// SPDX-License-Identifier: GPL-2.0-only
#include "predictor-internal.h"

typedef unsigned long long swapz_u64x8 __attribute__((vector_size(64)));

swapz_u32 swapz_predict_delta64_avx512(const swapz_u8 *input, swapz_u8 *output)
{
	swapz_u64x8 previous_block, current_block, shifted, delta;
	swapz_u32 base = 0, offset = SWAPZ_PREDICTOR_U64_BYTES;

	swapz_predictor_store64(output, swapz_predictor_load64(input));
	memcpy(&previous_block, input, sizeof(previous_block));
	for (; base + 2U * sizeof(swapz_u64x8) <= SWAPZ_BLOCK_BYTES;
	     base += sizeof(swapz_u64x8), offset += sizeof(swapz_u64x8)) {
		memcpy(&current_block, input + base + sizeof(swapz_u64x8),
		       sizeof(current_block));
		/*
		 * previous_block = x[n..n+7], current_block = x[n+8..n+15].
		 * VALIGNQ builds x[n+1..n+8], so one packed subtraction emits
		 * eight consecutive deltas while each 64-byte input block is
		 * loaded only once.
		 */
		__asm__ volatile("valignq $1, %1, %2, %0"
				 : "=v"(shifted)
				 : "v"(previous_block), "v"(current_block));
		delta = shifted - previous_block;
		memcpy(output + offset, &delta, sizeof(delta));
		previous_block = current_block;
	}
	for (; offset < SWAPZ_BLOCK_BYTES; offset += SWAPZ_PREDICTOR_U64_BYTES) {
		unsigned long long value = swapz_predictor_load64(input + offset);
		unsigned long long previous =
			swapz_predictor_load64(input + offset -
					       SWAPZ_PREDICTOR_U64_BYTES);

		swapz_predictor_store64(output + offset, value - previous);
	}
	return 0;
}

void swapz_unpredict_delta64_avx512(const swapz_u8 *input, swapz_u8 *output)
{
	const swapz_u64x8 zero = { 0 };
	unsigned long long previous = swapz_predictor_load64(input);
	swapz_u32 offset = SWAPZ_PREDICTOR_U64_BYTES;

	swapz_predictor_store64(output, previous);
	for (; offset + sizeof(swapz_u64x8) <= SWAPZ_BLOCK_BYTES;
	     offset += sizeof(swapz_u64x8)) {
		swapz_u64x8 delta, prefix, shifted;
		swapz_u64x8 base = {
			previous, previous, previous, previous,
			previous, previous, previous, previous
		};

		memcpy(&delta, input + offset, sizeof(delta));
		prefix = delta;
		__asm__ volatile("valignq $7, %1, %2, %0"
				 : "=v"(shifted) : "v"(zero), "v"(prefix));
		prefix += shifted;
		__asm__ volatile("valignq $6, %1, %2, %0"
				 : "=v"(shifted) : "v"(zero), "v"(prefix));
		prefix += shifted;
		__asm__ volatile("valignq $4, %1, %2, %0"
				 : "=v"(shifted) : "v"(zero), "v"(prefix));
		prefix += shifted;
		prefix += base;
		memcpy(output + offset, &prefix, sizeof(prefix));
		previous = prefix[7];
	}
	for (; offset < SWAPZ_BLOCK_BYTES; offset += SWAPZ_PREDICTOR_U64_BYTES) {
		previous += swapz_predictor_load64(input + offset);
		swapz_predictor_store64(output + offset, previous);
	}
}
