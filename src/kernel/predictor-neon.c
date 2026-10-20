// SPDX-License-Identifier: GPL-2.0-only
#include <arm_neon.h>

#include "predictor-internal.h"

static swapz_u32 swapz_predict_delta64_score_two_neon(
						const swapz_u8 *input,
						swapz_u32 first,
						swapz_u32 second)
{
	uint64x2_t previous =
		vdupq_n_u64(swapz_predictor_load64(input + first));
	uint64x2_t current = vdupq_n_u64(swapz_predictor_load64(
		input + first + SWAPZ_PREDICTOR_U64_BYTES));
	uint64x2_t delta64;
	int64x2_t signed_delta64;
	int64x2_t sign_extended16;
	uint64x2_t fit64;
	uint32x4_t delta32;
	int32x4_t signed_delta32;
	int32x4_t sign_extended8;
	uint32x4_t fit8;
	swapz_u32 score = 0;

	previous = vsetq_lane_u64(
		swapz_predictor_load64(input + second), previous, 1);
	current = vsetq_lane_u64(swapz_predictor_load64(
		input + second + SWAPZ_PREDICTOR_U64_BYTES), current, 1);
	delta64 = vsubq_u64(current, previous);
	signed_delta64 = vreinterpretq_s64_u64(delta64);
	sign_extended16 = vshrq_n_s64(vshlq_n_s64(signed_delta64, 48), 48);
	fit64 = vandq_u64(vceqq_s64(signed_delta64, sign_extended16),
			 vmvnq_u64(vceqq_u64(delta64, vdupq_n_u64(0))));
	delta32 = vsubq_u32(vreinterpretq_u32_u64(current),
			   vreinterpretq_u32_u64(previous));
	signed_delta32 = vreinterpretq_s32_u32(delta32);
	sign_extended8 = vshrq_n_s32(vshlq_n_s32(signed_delta32, 24), 24);
	fit8 = vandq_u32(vceqq_s32(signed_delta32, sign_extended8),
			 vmvnq_u32(vceqq_u32(delta32, vdupq_n_u32(0))));

	if (vgetq_lane_u64(fit64, 0))
		score += 2U;
	else
		score += (swapz_u32)(vgetq_lane_u32(fit8, 0) != 0) +
			 (swapz_u32)(vgetq_lane_u32(fit8, 1) != 0);
	if (vgetq_lane_u64(fit64, 1))
		score += 2U;
	else
		score += (swapz_u32)(vgetq_lane_u32(fit8, 2) != 0) +
			 (swapz_u32)(vgetq_lane_u32(fit8, 3) != 0);
	return score;
}

swapz_u32 swapz_predict_delta64_sample_score_neon(const swapz_u8 *input)
{
	swapz_u32 score = 0;
	swapz_u32 base;
	swapz_u32 offset;

	for (base = 0; base < SWAPZ_BLOCK_BYTES;
	     base += 2U * SWAPZ_PREDICTOR_SUBPAGE_BYTES)
		score += swapz_predict_delta64_score_two_neon(
			input, base, base + SWAPZ_PREDICTOR_SUBPAGE_BYTES);
	if (score < SWAPZ_PREDICTOR_STAGE1_MIN_SCORE)
		return 0;
	for (offset = SWAPZ_PREDICTOR_SAMPLE_STRIDE_BYTES;
	     offset < SWAPZ_PREDICTOR_SUBPAGE_BYTES;
	     offset += SWAPZ_PREDICTOR_SAMPLE_STRIDE_BYTES)
		for (base = 0; base < SWAPZ_BLOCK_BYTES;
		     base += 2U * SWAPZ_PREDICTOR_SUBPAGE_BYTES)
			score += swapz_predict_delta64_score_two_neon(
				input, base + offset,
				base + SWAPZ_PREDICTOR_SUBPAGE_BYTES + offset);
	return score;
}

swapz_u32 swapz_predict_delta64_neon(const swapz_u8 *input,
				     swapz_u8 *output)
{
	swapz_u32 offset = SWAPZ_PREDICTOR_U64_BYTES;

	swapz_predictor_store64(output, swapz_predictor_load64(input));
	for (; offset + 16U <= SWAPZ_BLOCK_BYTES; offset += 16U) {
		uint64x2_t current = vreinterpretq_u64_u8(
			vld1q_u8(input + offset));
		uint64x2_t previous = vreinterpretq_u64_u8(
			vld1q_u8(input + offset - 8U));

		vst1q_u8(output + offset,
			 vreinterpretq_u8_u64(vsubq_u64(current, previous)));
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

void swapz_unpredict_delta64_neon(const swapz_u8 *input, swapz_u8 *output)
{
	unsigned long long previous = swapz_predictor_load64(input);
	swapz_u32 offset = SWAPZ_PREDICTOR_U64_BYTES;

	swapz_predictor_store64(output, previous);
	for (; offset + 16U <= SWAPZ_BLOCK_BYTES; offset += 16U) {
		uint64x2_t delta =
			vreinterpretq_u64_u8(vld1q_u8(input + offset));
		uint64x2_t shifted =
			vextq_u64(vdupq_n_u64(0), delta, 1);
		uint64x2_t prefix = vaddq_u64(delta, shifted);

		prefix = vaddq_u64(prefix, vdupq_n_u64(previous));
		vst1q_u8(output + offset, vreinterpretq_u8_u64(prefix));
		previous = vgetq_lane_u64(prefix, 1);
	}
	for (; offset < SWAPZ_BLOCK_BYTES; offset += 8U) {
		previous += swapz_predictor_load64(input + offset);
		swapz_predictor_store64(output + offset, previous);
	}
}
