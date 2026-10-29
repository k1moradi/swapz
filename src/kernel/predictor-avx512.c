// SPDX-License-Identifier: GPL-2.0-only
#include "predictor-internal.h"
#include "predictor-shuffle.h"

typedef unsigned long long swapz_u64x8 __attribute__((vector_size(64)));

swapz_u32 swapz_predict_delta64_avx512(const swapz_u8 *input, swapz_u8 *output)
{
	swapz_u64x8 previous_block = { 0 };
	swapz_u32 offset = 0;

	/*
	 * delta64 defines y[0] = x[0], which is x[0] - virtual x[-1] with
	 * x[-1] = 0. Start at byte zero so every 64-byte load/store is naturally
	 * cache-line aligned and the scalar prologue/tail disappear completely.
	 * Process two ZMM vectors per iteration to cover one 128-byte pair.
	 */
	for (; offset + 2U * sizeof(swapz_u64x8) <= SWAPZ_BLOCK_BYTES;
	     offset += 2U * sizeof(swapz_u64x8)) {
		swapz_u64x8 current0, current1, predecessor0, predecessor1;
		swapz_u64x8 delta0, delta1;

		memcpy(&current0, input + offset, sizeof(current0));
		memcpy(&current1, input + offset + sizeof(current0),
		       sizeof(current1));
		/*
		 * In AT&T VALIGNQ form used here, imm=7 produces
		 * [previous[7], current[0..6]]. The first iteration uses an all-zero
		 * previous vector, so lane zero emits x[0] unchanged.
		 */
		__asm__("valignq $7, %1, %2, %0"
			: "=v"(predecessor0)
			: "v"(previous_block), "v"(current0));
		__asm__("valignq $7, %1, %2, %0"
			: "=v"(predecessor1)
			: "v"(current0), "v"(current1));
		delta0 = current0 - predecessor0;
		delta1 = current1 - predecessor1;
		memcpy(output + offset, &delta0, sizeof(delta0));
		memcpy(output + offset + sizeof(delta0), &delta1,
		       sizeof(delta1));
		previous_block = current1;
	}
	return 0;
}

void swapz_unpredict_delta64_avx512(const swapz_u8 *input, swapz_u8 *output)
{
	const swapz_u64x8 zero = { 0 };
	swapz_u64x8 base = { 0 };
	swapz_u32 offset = 0;

	/*
	 * Reconstruct from virtual x[-1] = 0 so all ZMM loads/stores are aligned.
	 * Each local eight-lane prefix is independent of the loop-carried base.
	 * Tree-associate the two totals so the recurrence is one packed add per
	 * 128B; separate shift temporaries avoid an artificial dependency chain.
	 */
	for (; offset + 2U * sizeof(swapz_u64x8) <= SWAPZ_BLOCK_BYTES;
	     offset += 2U * sizeof(swapz_u64x8)) {
		swapz_u64x8 delta0, delta1, prefix0, prefix1;
		swapz_u64x8 shifted0, shifted1;
		swapz_u64x8 step0, step1, step_pair, out0, out1;

		memcpy(&delta0, input + offset, sizeof(delta0));
		memcpy(&delta1, input + offset + sizeof(delta0), sizeof(delta1));
		prefix0 = delta0;
		prefix1 = delta1;
		__asm__("valignq $7, %1, %2, %0"
			: "=v"(shifted0) : "v"(zero), "v"(prefix0));
		__asm__("valignq $7, %1, %2, %0"
			: "=v"(shifted1) : "v"(zero), "v"(prefix1));
		prefix0 += shifted0;
		prefix1 += shifted1;
		__asm__("valignq $6, %1, %2, %0"
			: "=v"(shifted0) : "v"(zero), "v"(prefix0));
		__asm__("valignq $6, %1, %2, %0"
			: "=v"(shifted1) : "v"(zero), "v"(prefix1));
		prefix0 += shifted0;
		prefix1 += shifted1;
		__asm__("valignq $4, %1, %2, %0"
			: "=v"(shifted0) : "v"(zero), "v"(prefix0));
		__asm__("valignq $4, %1, %2, %0"
			: "=v"(shifted1) : "v"(zero), "v"(prefix1));
		prefix0 += shifted0;
		prefix1 += shifted1;
		step0 = (swapz_u64x8){
			prefix0[7], prefix0[7], prefix0[7], prefix0[7],
			prefix0[7], prefix0[7], prefix0[7], prefix0[7]
		};
		step1 = (swapz_u64x8){
			prefix1[7], prefix1[7], prefix1[7], prefix1[7],
			prefix1[7], prefix1[7], prefix1[7], prefix1[7]
		};
		step_pair = step0 + step1;
		out0 = prefix0 + base;
		out1 = prefix1 + (base + step0);
		base += step_pair;
		memcpy(output + offset, &out0, sizeof(out0));
		memcpy(output + offset + sizeof(out0), &out1, sizeof(out1));
	}
}

/* Byte-plane shuffle stage of DELTA64_SHUF8, built with this unit's ISA. */
void swapz_shuffle8_avx512(const swapz_u8 *input, swapz_u8 *output)
{
	swapz_shuffle8_vector(input, output);
}

void swapz_unshuffle8_avx512(const swapz_u8 *input, swapz_u8 *output)
{
	swapz_unshuffle8_vector(input, output);
}
