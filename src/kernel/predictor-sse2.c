// SPDX-License-Identifier: GPL-2.0-only
#include <emmintrin.h>

#include "predictor-internal.h"

static swapz_u32 swapz_predict_delta64_score_two_sse2(
						const swapz_u8 *input,
						swapz_u32 first,
						swapz_u32 second)
{
	__m128i previous = _mm_set_epi64x(
		(long long)swapz_predictor_load64(input + second),
		(long long)swapz_predictor_load64(input + first));
	__m128i current = _mm_set_epi64x(
		(long long)swapz_predictor_load64(
			input + second + SWAPZ_PREDICTOR_U64_BYTES),
		(long long)swapz_predictor_load64(
			input + first + SWAPZ_PREDICTOR_U64_BYTES));
	__m128i delta64 = _mm_sub_epi64(current, previous);
	__m128i zero = _mm_setzero_si128();
	__m128i sign16 =
		_mm_srai_epi32(_mm_slli_epi32(delta64, 16), 31);
	__m128i pair_sign =
		_mm_shuffle_epi32(sign16, _MM_SHUFFLE(2, 2, 0, 0));
	int low_ok = _mm_movemask_ps(_mm_castsi128_ps(_mm_cmpeq_epi32(
		_mm_srai_epi32(delta64, 16), pair_sign)));
	int high_ok = _mm_movemask_ps(_mm_castsi128_ps(
		_mm_cmpeq_epi32(delta64, pair_sign)));
	__m128i low16 = _mm_and_si128(delta64, _mm_set1_epi32(0xffff));
	int zero16 = _mm_movemask_ps(_mm_castsi128_ps(
		_mm_cmpeq_epi32(low16, zero)));
	__m128i delta32 = _mm_sub_epi32(current, previous);
	__m128i sign8 =
		_mm_srai_epi32(_mm_slli_epi32(delta32, 24), 31);
	int fit8 = _mm_movemask_ps(_mm_castsi128_ps(_mm_cmpeq_epi32(
		_mm_srai_epi32(delta32, 8), sign8)));
	int zero32 = _mm_movemask_ps(_mm_castsi128_ps(
		_mm_cmpeq_epi32(delta32, zero)));
	int lane8 = fit8 & ~zero32;
	swapz_u32 score = 0;

	if ((low_ok & 0x1) && (high_ok & 0x2) && !(zero16 & 0x1))
		score += 2U;
	else
		score += (swapz_u32)((lane8 & 0x1) != 0) +
			 (swapz_u32)((lane8 & 0x2) != 0);
	if ((low_ok & 0x4) && (high_ok & 0x8) && !(zero16 & 0x4))
		score += 2U;
	else
		score += (swapz_u32)((lane8 & 0x4) != 0) +
			 (swapz_u32)((lane8 & 0x8) != 0);
	return score;
}

swapz_u32 swapz_predict_delta64_sample_score_sse2(const swapz_u8 *input)
{
	swapz_u32 score = 0;
	swapz_u32 base;
	swapz_u32 offset;

	for (base = 0; base < SWAPZ_BLOCK_BYTES;
	     base += 2U * SWAPZ_PREDICTOR_SUBPAGE_BYTES)
		score += swapz_predict_delta64_score_two_sse2(
			input, base, base + SWAPZ_PREDICTOR_SUBPAGE_BYTES);
	if (score < SWAPZ_PREDICTOR_STAGE1_MIN_SCORE)
		return 0;
	for (offset = SWAPZ_PREDICTOR_SAMPLE_STRIDE_BYTES;
	     offset < SWAPZ_PREDICTOR_SUBPAGE_BYTES;
	     offset += SWAPZ_PREDICTOR_SAMPLE_STRIDE_BYTES)
		for (base = 0; base < SWAPZ_BLOCK_BYTES;
		     base += 2U * SWAPZ_PREDICTOR_SUBPAGE_BYTES)
			score += swapz_predict_delta64_score_two_sse2(
				input, base + offset,
				base + SWAPZ_PREDICTOR_SUBPAGE_BYTES + offset);
	return score;
}

swapz_u32 swapz_predict_delta64_sse2(const swapz_u8 *input,
				     swapz_u8 *output)
{
	swapz_u32 offset = SWAPZ_PREDICTOR_U64_BYTES;

	swapz_predictor_store64(output, swapz_predictor_load64(input));
	for (; offset + 16U <= SWAPZ_BLOCK_BYTES; offset += 16U) {
		__m128i current =
			_mm_loadu_si128((const __m128i *)(input + offset));
		__m128i previous =
			_mm_loadu_si128((const __m128i *)(input + offset - 8U));

		_mm_storeu_si128((__m128i *)(output + offset),
				 _mm_sub_epi64(current, previous));
	}
	for (; offset < SWAPZ_BLOCK_BYTES; offset += 8U) {
		unsigned long long current =
			swapz_predictor_load64(input + offset);
		unsigned long long previous =
			swapz_predictor_load64(input + offset - 8U);

		swapz_predictor_store64(output + offset, current - previous);
	}
	return 0;
}

void swapz_unpredict_delta64_sse2(const swapz_u8 *input, swapz_u8 *output)
{
	unsigned long long previous = swapz_predictor_load64(input);
	swapz_u32 offset = SWAPZ_PREDICTOR_U64_BYTES;

	swapz_predictor_store64(output, previous);
	for (; offset + 16U <= SWAPZ_BLOCK_BYTES; offset += 16U) {
		__m128i delta =
			_mm_loadu_si128((const __m128i *)(input + offset));
		__m128i prefix = _mm_add_epi64(
			delta, _mm_slli_si128(delta, SWAPZ_PREDICTOR_U64_BYTES));

		prefix = _mm_add_epi64(prefix,
				      _mm_set1_epi64x((long long)previous));
		_mm_storeu_si128((__m128i *)(output + offset), prefix);
		previous = (unsigned long long)_mm_cvtsi128_si64(
			_mm_srli_si128(prefix, SWAPZ_PREDICTOR_U64_BYTES));
	}
	for (; offset < SWAPZ_BLOCK_BYTES; offset += 8U) {
		previous += swapz_predictor_load64(input + offset);
		swapz_predictor_store64(output + offset, previous);
	}
}
