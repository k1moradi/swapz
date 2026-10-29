/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_PREDICTOR_INTERNAL_H
#define SWAPZ_PREDICTOR_INTERNAL_H
#include "predictor.h"
#ifdef __KERNEL__
#include <linux/string.h>
#else
#include <string.h>
#endif
static inline unsigned long long swapz_predictor_load64(const swapz_u8 *bytes)
{
	unsigned long long value;
	memcpy(&value, bytes, sizeof(value));
	return value;
}
static inline void swapz_predictor_store64(swapz_u8 *bytes, unsigned long long value)
{
	memcpy(bytes, &value, sizeof(value));
}
static inline int swapz_predictor_small_nonzero_delta32(swapz_u32 value, swapz_u32 previous)
{
	swapz_u32 delta = value - previous;
	return delta && (swapz_u32)(delta + 128U) <= 255U;
}
static inline int swapz_predictor_small_nonzero_delta64(unsigned long long value,
						unsigned long long previous)
{
	unsigned long long delta = value - previous;
	return delta && (unsigned long long)(delta + 0x8000ULL) <= 0xffffULL;
}
swapz_u32 swapz_predict_delta64_sample_score_scalar(const swapz_u8 *input);
swapz_u32 swapz_predict_delta64_scalar(const swapz_u8 *input, swapz_u8 *output);
void swapz_unpredict_delta64_scalar(const swapz_u8 *input, swapz_u8 *output);
void swapz_shuffle8_scalar(const swapz_u8 *input, swapz_u8 *output);
void swapz_unshuffle8_scalar(const swapz_u8 *input, swapz_u8 *output);
swapz_u32 swapz_predict_delta64_shuf8_scalar(const swapz_u8 *input,
					     swapz_u8 *scratch, swapz_u8 *output);
void swapz_unpredict_delta64_shuf8_scalar(const swapz_u8 *input,
					  swapz_u8 *scratch, swapz_u8 *output);
#if defined(CONFIG_X86_64) || defined(__x86_64__)
swapz_u32 swapz_predict_delta64_sse2(const swapz_u8 *input, swapz_u8 *output);
#if defined(__x86_64__) && !defined(__KERNEL__)
/* Native-only pre-promotion baseline; never selected by kernel dispatch. */
swapz_u32 swapz_predict_delta64_sse2_baseline(const swapz_u8 *input,
					      swapz_u8 *output);
#endif
void swapz_unpredict_delta64_sse2(const swapz_u8 *input, swapz_u8 *output);
swapz_u32 swapz_predict_delta64_avx2(const swapz_u8 *input, swapz_u8 *output);
void swapz_unpredict_delta64_avx2(const swapz_u8 *input, swapz_u8 *output);
swapz_u32 swapz_predict_delta64_avx512(const swapz_u8 *input, swapz_u8 *output);
void swapz_unpredict_delta64_avx512(const swapz_u8 *input, swapz_u8 *output);
void swapz_shuffle8_sse2(const swapz_u8 *input, swapz_u8 *output);
void swapz_unshuffle8_sse2(const swapz_u8 *input, swapz_u8 *output);
void swapz_shuffle8_avx2(const swapz_u8 *input, swapz_u8 *output);
void swapz_unshuffle8_avx2(const swapz_u8 *input, swapz_u8 *output);
void swapz_shuffle8_avx512(const swapz_u8 *input, swapz_u8 *output);
void swapz_unshuffle8_avx512(const swapz_u8 *input, swapz_u8 *output);
#endif
#if (defined(CONFIG_ARM64) && defined(CONFIG_KERNEL_MODE_NEON)) || defined(__aarch64__)
swapz_u32 swapz_predict_delta64_neon(const swapz_u8 *input, swapz_u8 *output);
void swapz_unpredict_delta64_neon(const swapz_u8 *input, swapz_u8 *output);
void swapz_shuffle8_neon(const swapz_u8 *input, swapz_u8 *output);
void swapz_unshuffle8_neon(const swapz_u8 *input, swapz_u8 *output);
#endif
#endif
