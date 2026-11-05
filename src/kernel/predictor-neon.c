// SPDX-License-Identifier: GPL-2.0-only
#include "predictor-internal.h"
#include "predictor-shuffle.h"
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

#define SWAPZ_NEON_ZIP1(dst, a, b) \
	__asm__("zip1 %0.2d, %1.2d, %2.2d" : "=w"(dst) : "w"(a), "w"(b))
#define SWAPZ_NEON_ZIP2(dst, a, b) \
	__asm__("zip2 %0.2d, %1.2d, %2.2d" : "=w"(dst) : "w"(a), "w"(b))

void swapz_unpredict_delta64_neon(const swapz_u8 *input, swapz_u8 *output)
{
	const swapz_u64x2 zero = { 0ULL, 0ULL };
	swapz_u64x2 base = { 0ULL, 0ULL };
	swapz_u32 offset = 0;

	/*
	 * Reconstruct 128 bytes per iteration as eight two-lane columns
	 * [d[j], d[8 + j]]. ZIP transposes eight loaded vectors, one serial
	 * column scan yields both eight-word prefixes at once, EXT carries the
	 * lower half's total into the upper lanes, and ADDP forms the line total
	 * off the loop-carried chain, so base advances by one add per 128 bytes.
	 * ZIP restores natural order. At -O2 on ARM64 this cut the inverse ~18%
	 * versus the per-vector EXT/DUP tree; LD4/ST4 columns were slower.
	 */
	for (; offset + 8U * sizeof(swapz_u64x2) <= SWAPZ_BLOCK_BYTES;
	     offset += 8U * sizeof(swapz_u64x2)) {
		swapz_u64x2 q0, q1, q2, q3, q4, q5, q6, q7;
		swapz_u64x2 c0, c1, c2, c3, c4, c5, c6, c7;
		swapz_u64x2 column, carry, total, result;

		memcpy(&q0, input + offset, sizeof(q0));
		memcpy(&q1, input + offset + sizeof(q0), sizeof(q1));
		memcpy(&q2, input + offset + 2U * sizeof(q0), sizeof(q2));
		memcpy(&q3, input + offset + 3U * sizeof(q0), sizeof(q3));
		memcpy(&q4, input + offset + 4U * sizeof(q0), sizeof(q4));
		memcpy(&q5, input + offset + 5U * sizeof(q0), sizeof(q5));
		memcpy(&q6, input + offset + 6U * sizeof(q0), sizeof(q6));
		memcpy(&q7, input + offset + 7U * sizeof(q0), sizeof(q7));

		SWAPZ_NEON_ZIP1(c0, q0, q4);
		SWAPZ_NEON_ZIP2(column, q0, q4);
		c1 = c0 + column;
		SWAPZ_NEON_ZIP1(column, q1, q5);
		c2 = c1 + column;
		SWAPZ_NEON_ZIP2(column, q1, q5);
		c3 = c2 + column;
		SWAPZ_NEON_ZIP1(column, q2, q6);
		c4 = c3 + column;
		SWAPZ_NEON_ZIP2(column, q2, q6);
		c5 = c4 + column;
		SWAPZ_NEON_ZIP1(column, q3, q7);
		c6 = c5 + column;
		SWAPZ_NEON_ZIP2(column, q3, q7);
		c7 = c6 + column;

		__asm__("ext %0.16b, %1.16b, %2.16b, #8"
			: "=w"(carry) : "w"(zero), "w"(c7));
		carry += base;
		__asm__("addp %0.2d, %1.2d, %1.2d" : "=w"(total) : "w"(c7));
		base += total;
		c0 += carry; c1 += carry; c2 += carry; c3 += carry;
		c4 += carry; c5 += carry; c6 += carry; c7 += carry;

		SWAPZ_NEON_ZIP1(result, c0, c1);
		memcpy(output + offset, &result, sizeof(result));
		SWAPZ_NEON_ZIP1(result, c2, c3);
		memcpy(output + offset + sizeof(result), &result, sizeof(result));
		SWAPZ_NEON_ZIP1(result, c4, c5);
		memcpy(output + offset + 2U * sizeof(result), &result, sizeof(result));
		SWAPZ_NEON_ZIP1(result, c6, c7);
		memcpy(output + offset + 3U * sizeof(result), &result, sizeof(result));
		SWAPZ_NEON_ZIP2(result, c0, c1);
		memcpy(output + offset + 4U * sizeof(result), &result, sizeof(result));
		SWAPZ_NEON_ZIP2(result, c2, c3);
		memcpy(output + offset + 5U * sizeof(result), &result, sizeof(result));
		SWAPZ_NEON_ZIP2(result, c4, c5);
		memcpy(output + offset + 6U * sizeof(result), &result, sizeof(result));
		SWAPZ_NEON_ZIP2(result, c6, c7);
		memcpy(output + offset + 7U * sizeof(result), &result, sizeof(result));
	}
}

#undef SWAPZ_NEON_ZIP1
#undef SWAPZ_NEON_ZIP2

/* Byte-plane shuffle stage of DELTA64_SHUF8, built with this unit's ISA. */
void swapz_shuffle8_neon(const swapz_u8 *input, swapz_u8 *output)
{
	swapz_shuffle8_vector(input, output);
}

void swapz_unshuffle8_neon(const swapz_u8 *input, swapz_u8 *output)
{
	swapz_unshuffle8_vector(input, output);
}
