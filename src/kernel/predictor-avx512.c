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
	swapz_u64x8 base;
	swapz_u32 offset = SWAPZ_PREDICTOR_U64_BYTES;

	swapz_predictor_store64(output, previous);
	base = (swapz_u64x8){
		previous, previous, previous, previous,
		previous, previous, previous, previous
	};
	/*
	 * Keep the inter-vector carry in ZMM. Each local eight-lane prefix and
	 * its broadcast total are independent of base, so the expensive VALIGNQ
	 * scan can execute ahead while the loop-carried path is one packed add.
	 * The vector constructor is intentionally data-derived: GCC and Clang
	 * lower this broadcast to vector permute/broadcast instructions without
	 * extracting the prefix value through a general-purpose register.
	 */
	for (; offset + 2U * sizeof(swapz_u64x8) <= SWAPZ_BLOCK_BYTES;
	     offset += 2U * sizeof(swapz_u64x8)) {
		swapz_u64x8 delta0, delta1, prefix0, prefix1, shifted;
		swapz_u64x8 step0, step1, out0, out1;

		memcpy(&delta0, input + offset, sizeof(delta0));
		memcpy(&delta1, input + offset + sizeof(delta0), sizeof(delta1));
		prefix0 = delta0;
		prefix1 = delta1;
		__asm__ volatile("valignq $7, %1, %2, %0"
				 : "=v"(shifted) : "v"(zero), "v"(prefix0));
		prefix0 += shifted;
		__asm__ volatile("valignq $7, %1, %2, %0"
				 : "=v"(shifted) : "v"(zero), "v"(prefix1));
		prefix1 += shifted;
		__asm__ volatile("valignq $6, %1, %2, %0"
				 : "=v"(shifted) : "v"(zero), "v"(prefix0));
		prefix0 += shifted;
		__asm__ volatile("valignq $6, %1, %2, %0"
				 : "=v"(shifted) : "v"(zero), "v"(prefix1));
		prefix1 += shifted;
		__asm__ volatile("valignq $4, %1, %2, %0"
				 : "=v"(shifted) : "v"(zero), "v"(prefix0));
		prefix0 += shifted;
		__asm__ volatile("valignq $4, %1, %2, %0"
				 : "=v"(shifted) : "v"(zero), "v"(prefix1));
		prefix1 += shifted;
		step0 = (swapz_u64x8){
			prefix0[7], prefix0[7], prefix0[7], prefix0[7],
			prefix0[7], prefix0[7], prefix0[7], prefix0[7]
		};
		step1 = (swapz_u64x8){
			prefix1[7], prefix1[7], prefix1[7], prefix1[7],
			prefix1[7], prefix1[7], prefix1[7], prefix1[7]
		};
		out0 = prefix0 + base;
		base += step0;
		out1 = prefix1 + base;
		base += step1;
		memcpy(output + offset, &out0, sizeof(out0));
		memcpy(output + offset + sizeof(out0), &out1, sizeof(out1));
	}
	for (; offset + sizeof(swapz_u64x8) <= SWAPZ_BLOCK_BYTES;
	     offset += sizeof(swapz_u64x8)) {
		swapz_u64x8 delta, prefix, shifted, step, out;

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
		step = (swapz_u64x8){
			prefix[7], prefix[7], prefix[7], prefix[7],
			prefix[7], prefix[7], prefix[7], prefix[7]
		};
		out = prefix + base;
		base += step;
		memcpy(output + offset, &out, sizeof(out));
	}
	/* One vector->scalar handoff after all ZMM work is acceptable for the
	 * seven-qword tail; it is no longer part of the vector-loop dependency. */
	previous = base[0];
	for (; offset < SWAPZ_BLOCK_BYTES; offset += SWAPZ_PREDICTOR_U64_BYTES) {
		previous += swapz_predictor_load64(input + offset);
		swapz_predictor_store64(output + offset, previous);
	}
}
