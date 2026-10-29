/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_PREDICTOR_SHUFFLE_H
#define SWAPZ_PREDICTOR_SHUFFLE_H
/*
 * Byte-plane shuffle for SWAPZ_ENCODING_DELTA64_SHUF8: a 4KiB page of 512
 * eight-byte words becomes eight 512-byte planes, plane b holding byte b of
 * every word in order (out[b * 512 + w] = in[w * 8 + b]). After delta64,
 * small deltas leave their upper planes as long zero runs that LZ4 encodes
 * quickly and compactly.
 *
 * One portable GNU vector-extension body is compiled into each SIMD
 * translation unit with that unit's flags. Constant 16-byte permutes have
 * the same semantics on every ISA, so byte-exactness is proven by executing
 * any one build against the scalar oracle; the compiler selects UZP/ZIP on
 * NEON and PACK/UNPACK on x86. Callers own kernel FPU entry/exit.
 */
#include "predictor-internal.h"

typedef unsigned char swapz_u8x16 __attribute__((vector_size(16)));

#if defined(__clang__)
#define SWAPZ_SHUFFLE16(a, b, ...) __builtin_shufflevector((a), (b), __VA_ARGS__)
#else
#define SWAPZ_SHUFFLE16(a, b, ...) \
	__builtin_shuffle((a), (b), (swapz_u8x16){ __VA_ARGS__ })
#endif
#define SWAPZ_UZP1_8(a, b) SWAPZ_SHUFFLE16(a, b, 0, 2, 4, 6, 8, 10, 12, 14, \
	16, 18, 20, 22, 24, 26, 28, 30)
#define SWAPZ_UZP2_8(a, b) SWAPZ_SHUFFLE16(a, b, 1, 3, 5, 7, 9, 11, 13, 15, \
	17, 19, 21, 23, 25, 27, 29, 31)
#define SWAPZ_ZIP1_8(a, b) SWAPZ_SHUFFLE16(a, b, 0, 16, 1, 17, 2, 18, 3, 19, \
	4, 20, 5, 21, 6, 22, 7, 23)
#define SWAPZ_ZIP2_8(a, b) SWAPZ_SHUFFLE16(a, b, 8, 24, 9, 25, 10, 26, 11, 27, \
	12, 28, 13, 29, 14, 30, 15, 31)

#define SWAPZ_SHUF8_WORDS (SWAPZ_BLOCK_BYTES / SWAPZ_PREDICTOR_U64_BYTES)

/*
 * Sixteen words (128 bytes) per iteration: three UZP rounds separate byte
 * index bits 0, 1 and 2, yielding 16 consecutive bytes of each plane.
 */
static inline void swapz_shuffle8_vector(const swapz_u8 *input, swapz_u8 *output)
{
	swapz_u32 word;

	for (word = 0; word < SWAPZ_SHUF8_WORDS; word += 16U) {
		const swapz_u8 *s = input + word * SWAPZ_PREDICTOR_U64_BYTES;
		swapz_u8x16 v0, v1, v2, v3, v4, v5, v6, v7;
		swapz_u8x16 e0, e1, e2, e3, o0, o1, o2, o3;
		swapz_u8x16 ee0, ee1, eo0, eo1, oe0, oe1, oo0, oo1, plane;

		memcpy(&v0, s, sizeof(v0));
		memcpy(&v1, s + 16, sizeof(v1));
		memcpy(&v2, s + 32, sizeof(v2));
		memcpy(&v3, s + 48, sizeof(v3));
		memcpy(&v4, s + 64, sizeof(v4));
		memcpy(&v5, s + 80, sizeof(v5));
		memcpy(&v6, s + 96, sizeof(v6));
		memcpy(&v7, s + 112, sizeof(v7));
		e0 = SWAPZ_UZP1_8(v0, v1); o0 = SWAPZ_UZP2_8(v0, v1);
		e1 = SWAPZ_UZP1_8(v2, v3); o1 = SWAPZ_UZP2_8(v2, v3);
		e2 = SWAPZ_UZP1_8(v4, v5); o2 = SWAPZ_UZP2_8(v4, v5);
		e3 = SWAPZ_UZP1_8(v6, v7); o3 = SWAPZ_UZP2_8(v6, v7);
		ee0 = SWAPZ_UZP1_8(e0, e1); eo0 = SWAPZ_UZP2_8(e0, e1);
		ee1 = SWAPZ_UZP1_8(e2, e3); eo1 = SWAPZ_UZP2_8(e2, e3);
		oe0 = SWAPZ_UZP1_8(o0, o1); oo0 = SWAPZ_UZP2_8(o0, o1);
		oe1 = SWAPZ_UZP1_8(o2, o3); oo1 = SWAPZ_UZP2_8(o2, o3);
		plane = SWAPZ_UZP1_8(ee0, ee1);
		memcpy(output + 0U * SWAPZ_SHUF8_WORDS + word, &plane, sizeof(plane));
		plane = SWAPZ_UZP2_8(ee0, ee1);
		memcpy(output + 4U * SWAPZ_SHUF8_WORDS + word, &plane, sizeof(plane));
		plane = SWAPZ_UZP1_8(eo0, eo1);
		memcpy(output + 2U * SWAPZ_SHUF8_WORDS + word, &plane, sizeof(plane));
		plane = SWAPZ_UZP2_8(eo0, eo1);
		memcpy(output + 6U * SWAPZ_SHUF8_WORDS + word, &plane, sizeof(plane));
		plane = SWAPZ_UZP1_8(oe0, oe1);
		memcpy(output + 1U * SWAPZ_SHUF8_WORDS + word, &plane, sizeof(plane));
		plane = SWAPZ_UZP2_8(oe0, oe1);
		memcpy(output + 5U * SWAPZ_SHUF8_WORDS + word, &plane, sizeof(plane));
		plane = SWAPZ_UZP1_8(oo0, oo1);
		memcpy(output + 3U * SWAPZ_SHUF8_WORDS + word, &plane, sizeof(plane));
		plane = SWAPZ_UZP2_8(oo0, oo1);
		memcpy(output + 7U * SWAPZ_SHUF8_WORDS + word, &plane, sizeof(plane));
	}
}

/* Inverse: ZIP planes (0,4) (2,6) (1,5) (3,7), then by two, then by one. */
static inline void swapz_unshuffle8_vector(const swapz_u8 *input, swapz_u8 *output)
{
	swapz_u32 word;

	for (word = 0; word < SWAPZ_SHUF8_WORDS; word += 16U) {
		swapz_u8 *d = output + word * SWAPZ_PREDICTOR_U64_BYTES;
		swapz_u8x16 p0, p1, p2, p3, p4, p5, p6, p7;
		swapz_u8x16 a0, a1, b0, b1, c0, c1, d0, d1;
		swapz_u8x16 ab0, ab1, ab2, ab3, cd0, cd1, cd2, cd3, words;

		memcpy(&p0, input + 0U * SWAPZ_SHUF8_WORDS + word, sizeof(p0));
		memcpy(&p1, input + 1U * SWAPZ_SHUF8_WORDS + word, sizeof(p1));
		memcpy(&p2, input + 2U * SWAPZ_SHUF8_WORDS + word, sizeof(p2));
		memcpy(&p3, input + 3U * SWAPZ_SHUF8_WORDS + word, sizeof(p3));
		memcpy(&p4, input + 4U * SWAPZ_SHUF8_WORDS + word, sizeof(p4));
		memcpy(&p5, input + 5U * SWAPZ_SHUF8_WORDS + word, sizeof(p5));
		memcpy(&p6, input + 6U * SWAPZ_SHUF8_WORDS + word, sizeof(p6));
		memcpy(&p7, input + 7U * SWAPZ_SHUF8_WORDS + word, sizeof(p7));
		a0 = SWAPZ_ZIP1_8(p0, p4); a1 = SWAPZ_ZIP2_8(p0, p4);
		b0 = SWAPZ_ZIP1_8(p2, p6); b1 = SWAPZ_ZIP2_8(p2, p6);
		c0 = SWAPZ_ZIP1_8(p1, p5); c1 = SWAPZ_ZIP2_8(p1, p5);
		d0 = SWAPZ_ZIP1_8(p3, p7); d1 = SWAPZ_ZIP2_8(p3, p7);
		ab0 = SWAPZ_ZIP1_8(a0, b0); ab1 = SWAPZ_ZIP2_8(a0, b0);
		ab2 = SWAPZ_ZIP1_8(a1, b1); ab3 = SWAPZ_ZIP2_8(a1, b1);
		cd0 = SWAPZ_ZIP1_8(c0, d0); cd1 = SWAPZ_ZIP2_8(c0, d0);
		cd2 = SWAPZ_ZIP1_8(c1, d1); cd3 = SWAPZ_ZIP2_8(c1, d1);
		words = SWAPZ_ZIP1_8(ab0, cd0); memcpy(d, &words, sizeof(words));
		words = SWAPZ_ZIP2_8(ab0, cd0); memcpy(d + 16, &words, sizeof(words));
		words = SWAPZ_ZIP1_8(ab1, cd1); memcpy(d + 32, &words, sizeof(words));
		words = SWAPZ_ZIP2_8(ab1, cd1); memcpy(d + 48, &words, sizeof(words));
		words = SWAPZ_ZIP1_8(ab2, cd2); memcpy(d + 64, &words, sizeof(words));
		words = SWAPZ_ZIP2_8(ab2, cd2); memcpy(d + 80, &words, sizeof(words));
		words = SWAPZ_ZIP1_8(ab3, cd3); memcpy(d + 96, &words, sizeof(words));
		words = SWAPZ_ZIP2_8(ab3, cd3); memcpy(d + 112, &words, sizeof(words));
	}
}

#endif
