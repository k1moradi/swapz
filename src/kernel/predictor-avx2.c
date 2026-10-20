// SPDX-License-Identifier: GPL-2.0-only
#include "predictor-internal.h"

typedef unsigned long long swapz_u64x4
	__attribute__((vector_size(32)));
typedef swapz_u32 swapz_u32x8 __attribute__((vector_size(32)));

union swapz_vec256 {
	swapz_u64x4 u64;
	swapz_u32x8 u32;
};

static int swapz_small_nonzero_delta32_value(swapz_u32 delta)
{
	return delta && (swapz_u32)(delta + 128U) <= 255U;
}

static int swapz_small_nonzero_delta64_value(unsigned long long delta)
{
	return delta && (unsigned long long)(delta + 0x8000ULL) <= 0xffffULL;
}

static swapz_u32 swapz_predict_delta64_score_four_avx2(
						const swapz_u8 *input,
						swapz_u32 first,
						swapz_u32 second,
						swapz_u32 third,
						swapz_u32 fourth)
{
	union swapz_vec256 previous;
	union swapz_vec256 value;
	union swapz_vec256 delta64;
	union swapz_vec256 delta32;
	swapz_u32 offsets[4] = { first, second, third, fourth };
	swapz_u32 score = 0;
	swapz_u32 pair;

	for (pair = 0; pair < 4U; ++pair) {
		previous.u64[pair] =
			swapz_predictor_load64(input + offsets[pair]);
		value.u64[pair] = swapz_predictor_load64(
			input + offsets[pair] + SWAPZ_PREDICTOR_U64_BYTES);
	}
	delta64.u64 = value.u64 - previous.u64;
	delta32.u32 = value.u32 - previous.u32;

	for (pair = 0; pair < 4U; ++pair) {
		if (swapz_small_nonzero_delta64_value(delta64.u64[pair]))
			score += 2U;
		else {
			swapz_u32 lane = 2U * pair;

			score += swapz_small_nonzero_delta32_value(
				delta32.u32[lane]);
			score += swapz_small_nonzero_delta32_value(
				delta32.u32[lane + 1U]);
		}
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
	if (score < SWAPZ_PREDICTOR_STAGE1_MIN_SCORE)
		return 0;
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
	return score;
}

swapz_u32 swapz_predict_delta64_avx2(const swapz_u8 *input,
				     swapz_u8 *output)
{
	swapz_u32 offset = SWAPZ_PREDICTOR_U64_BYTES;

	swapz_predictor_store64(output, swapz_predictor_load64(input));
	for (; offset + sizeof(swapz_u64x4) <= SWAPZ_BLOCK_BYTES;
	     offset += sizeof(swapz_u64x4)) {
		swapz_u64x4 value;
		swapz_u64x4 previous;
		swapz_u64x4 delta;

		memcpy(&value, input + offset, sizeof(value));
		memcpy(&previous, input + offset - SWAPZ_PREDICTOR_U64_BYTES,
		       sizeof(previous));
		delta = value - previous;
		memcpy(output + offset, &delta, sizeof(delta));
	}
	for (; offset < SWAPZ_BLOCK_BYTES; offset += SWAPZ_PREDICTOR_U64_BYTES) {
		unsigned long long value =
			swapz_predictor_load64(input + offset);
		unsigned long long previous =
			swapz_predictor_load64(
				input + offset - SWAPZ_PREDICTOR_U64_BYTES);

		swapz_predictor_store64(output + offset, value - previous);
	}
	return 0;
}

void swapz_unpredict_delta64_avx2(const swapz_u8 *input, swapz_u8 *output)
{
	unsigned long long previous = swapz_predictor_load64(input);
	swapz_u32 offset = SWAPZ_PREDICTOR_U64_BYTES;

	swapz_predictor_store64(output, previous);
	for (; offset + sizeof(swapz_u64x4) <= SWAPZ_BLOCK_BYTES;
	     offset += sizeof(swapz_u64x4)) {
		union swapz_vec256 delta;
		union swapz_vec256 prefix;
		swapz_u64x4 shifted;
		swapz_u64x4 upper_carry;
		swapz_u64x4 base;
		unsigned long long lower_carry;

		memcpy(&delta.u64, input + offset, sizeof(delta.u64));
		shifted = (swapz_u64x4){
			0ULL, delta.u64[0], 0ULL, delta.u64[2]
		};
		prefix.u64 = delta.u64 + shifted;
		lower_carry = prefix.u64[1];
		upper_carry = (swapz_u64x4){
			0ULL, 0ULL, lower_carry, lower_carry
		};
		prefix.u64 += upper_carry;
		base = (swapz_u64x4){previous, previous, previous, previous};
		prefix.u64 += base;
		memcpy(output + offset, &prefix.u64, sizeof(prefix.u64));
		previous = prefix.u64[3];
	}
	for (; offset < SWAPZ_BLOCK_BYTES; offset += SWAPZ_PREDICTOR_U64_BYTES) {
		previous += swapz_predictor_load64(input + offset);
		swapz_predictor_store64(output + offset, previous);
	}
}
