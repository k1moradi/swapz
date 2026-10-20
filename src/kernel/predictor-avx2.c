// SPDX-License-Identifier: GPL-2.0-only
#include <immintrin.h>

#include "predictor-internal.h"

static swapz_u32 swapz_predict_delta64_score_four_avx2(
						const swapz_u8 *input,
						swapz_u32 first,
						swapz_u32 second,
						swapz_u32 third,
						swapz_u32 fourth)
{
	__m256i previous = _mm256_set_epi64x(
		(long long)swapz_predictor_load64(input + fourth),
		(long long)swapz_predictor_load64(input + third),
		(long long)swapz_predictor_load64(input + second),
		(long long)swapz_predictor_load64(input + first));
	__m256i current = _mm256_set_epi64x(
		(long long)swapz_predictor_load64(
			input + fourth + SWAPZ_PREDICTOR_U64_BYTES),
		(long long)swapz_predictor_load64(
			input + third + SWAPZ_PREDICTOR_U64_BYTES),
		(long long)swapz_predictor_load64(
			input + second + SWAPZ_PREDICTOR_U64_BYTES),
		(long long)swapz_predictor_load64(
			input + first + SWAPZ_PREDICTOR_U64_BYTES));
	__m256i delta64 = _mm256_sub_epi64(current, previous);
	__m256i zero = _mm256_setzero_si256();
	__m256i sign16 =
		_mm256_srai_epi32(_mm256_slli_epi32(delta64, 16), 31);
	__m256i pair_sign =
		_mm256_shuffle_epi32(sign16, _MM_SHUFFLE(2, 2, 0, 0));
	int low_ok = _mm256_movemask_ps(_mm256_castsi256_ps(
		_mm256_cmpeq_epi32(_mm256_srai_epi32(delta64, 16),
				   pair_sign)));
	int high_ok = _mm256_movemask_ps(_mm256_castsi256_ps(
		_mm256_cmpeq_epi32(delta64, pair_sign)));
	int zero16 = _mm256_movemask_ps(_mm256_castsi256_ps(
		_mm256_cmpeq_epi32(_mm256_and_si256(
			delta64, _mm256_set1_epi32(0xffff)), zero)));
	__m256i delta32 = _mm256_sub_epi32(current, previous);
	__m256i sign8 =
		_mm256_srai_epi32(_mm256_slli_epi32(delta32, 24), 31);
	int lane8 = _mm256_movemask_ps(_mm256_castsi256_ps(
		_mm256_cmpeq_epi32(_mm256_srai_epi32(delta32, 8), sign8))) &
		~_mm256_movemask_ps(_mm256_castsi256_ps(
			_mm256_cmpeq_epi32(delta32, zero)));
	swapz_u32 score = 0;
	swapz_u32 pair;

	for (pair = 0; pair < 4U; ++pair) {
		int low = 1 << (2U * pair);
		int high = 1 << (2U * pair + 1U);

		if ((low_ok & low) && (high_ok & high) && !(zero16 & low))
			score += 2U;
		else
			score += (swapz_u32)((lane8 & low) != 0) +
				 (swapz_u32)((lane8 & high) != 0);
	}
	return score;
}

swapz_u32 swapz_predict_delta64_sample_score_avx2(const swapz_u8 *input)
{
	swapz_u32 score = 0;
	swapz_u32 base;
	swapz_u32 offset;

	for (base = 0; base < SWAPZ_BLOCK_BYTES;
	     base += 4U * SWAPZ_PREDICTOR_SUBPAGE_BYTES)
		score += swapz_predict_delta64_score_four_avx2(
			input, base, base + SWAPZ_PREDICTOR_SUBPAGE_BYTES,
			base + 2U * SWAPZ_PREDICTOR_SUBPAGE_BYTES,
			base + 3U * SWAPZ_PREDICTOR_SUBPAGE_BYTES);
	if (score < SWAPZ_PREDICTOR_STAGE1_MIN_SCORE) {
		_mm256_zeroupper();
		return 0;
	}
	for (offset = SWAPZ_PREDICTOR_SAMPLE_STRIDE_BYTES;
	     offset < SWAPZ_PREDICTOR_SUBPAGE_BYTES;
	     offset += SWAPZ_PREDICTOR_SAMPLE_STRIDE_BYTES)
		for (base = 0; base < SWAPZ_BLOCK_BYTES;
		     base += 4U * SWAPZ_PREDICTOR_SUBPAGE_BYTES)
			score += swapz_predict_delta64_score_four_avx2(
				input, base + offset,
				base + SWAPZ_PREDICTOR_SUBPAGE_BYTES + offset,
				base + 2U * SWAPZ_PREDICTOR_SUBPAGE_BYTES + offset,
				base + 3U * SWAPZ_PREDICTOR_SUBPAGE_BYTES + offset);
	_mm256_zeroupper();
	return score;
}

swapz_u32 swapz_predict_delta64_avx2(const swapz_u8 *input,
				     swapz_u8 *output)
{
	swapz_u32 offset = SWAPZ_PREDICTOR_U64_BYTES;

	swapz_predictor_store64(output, swapz_predictor_load64(input));
	for (; offset + 32U <= SWAPZ_BLOCK_BYTES; offset += 32U) {
		__m256i current =
			_mm256_loadu_si256((const __m256i *)(input + offset));
		__m256i previous =
			_mm256_loadu_si256((const __m256i *)(input + offset - 8U));

		_mm256_storeu_si256((__m256i *)(output + offset),
				    _mm256_sub_epi64(current, previous));
	}
	for (; offset < SWAPZ_BLOCK_BYTES; offset += 8U) {
		unsigned long long current =
			swapz_predictor_load64(input + offset);
		unsigned long long previous =
			swapz_predictor_load64(input + offset - 8U);

		swapz_predictor_store64(output + offset, current - previous);
	}
	_mm256_zeroupper();
	return 0;
}

void swapz_unpredict_delta64_avx2(const swapz_u8 *input, swapz_u8 *output)
{
	unsigned long long previous = swapz_predictor_load64(input);
	swapz_u32 offset = SWAPZ_PREDICTOR_U64_BYTES;

	swapz_predictor_store64(output, previous);
	for (; offset + 32U <= SWAPZ_BLOCK_BYTES; offset += 32U) {
		__m256i delta =
			_mm256_loadu_si256((const __m256i *)(input + offset));
		__m256i prefix =
			_mm256_add_epi64(delta, _mm256_slli_si256(delta, 8));
		__m256i lower_carry = _mm256_permute4x64_epi64(
			prefix, _MM_SHUFFLE(1, 1, 1, 1));
		__m256i upper_carry = _mm256_blend_epi32(
			_mm256_setzero_si256(), lower_carry, 0xf0);

		prefix = _mm256_add_epi64(prefix, upper_carry);
		prefix = _mm256_add_epi64(
			prefix, _mm256_set1_epi64x((long long)previous));
		_mm256_storeu_si256((__m256i *)(output + offset), prefix);
		previous = (unsigned long long)_mm256_extract_epi64(prefix, 3);
	}
	for (; offset < SWAPZ_BLOCK_BYTES; offset += 8U) {
		previous += swapz_predictor_load64(input + offset);
		swapz_predictor_store64(output + offset, previous);
	}
	_mm256_zeroupper();
}
