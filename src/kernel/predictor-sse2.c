// SPDX-License-Identifier: GPL-2.0-only
#include "predictor-internal.h"

typedef unsigned long long swapz_u64x2
	__attribute__((vector_size(16)));
typedef swapz_u32 swapz_u32x4 __attribute__((vector_size(16)));

union swapz_vec128 {
	swapz_u64x2 u64;
	swapz_u32x4 u32;
};

static int swapz_small_nonzero_delta32_value(swapz_u32 delta)
{
	return delta && (swapz_u32)(delta + 128U) <= 255U;
}

static int swapz_small_nonzero_delta64_value(unsigned long long delta)
{
	return delta && (unsigned long long)(delta + 0x8000ULL) <= 0xffffULL;
}

static swapz_u32 swapz_predict_delta64_score_two_sse2(
						const swapz_u8 *input,
						swapz_u32 first,
						swapz_u32 second)
{
	union swapz_vec128 previous;
	union swapz_vec128 value;
	union swapz_vec128 delta64;
	union swapz_vec128 delta32;
	swapz_u32 score = 0;
	swapz_u32 pair;

	previous.u64[0] = swapz_predictor_load64(input + first);
	previous.u64[1] = swapz_predictor_load64(input + second);
	value.u64[0] = swapz_predictor_load64(
		input + first + SWAPZ_PREDICTOR_U64_BYTES);
	value.u64[1] = swapz_predictor_load64(
		input + second + SWAPZ_PREDICTOR_U64_BYTES);
	delta64.u64 = value.u64 - previous.u64;
	delta32.u32 = value.u32 - previous.u32;

	for (pair = 0; pair < 2U; ++pair) {
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
	for (; offset + sizeof(swapz_u64x2) <= SWAPZ_BLOCK_BYTES;
	     offset += sizeof(swapz_u64x2)) {
		swapz_u64x2 value;
		swapz_u64x2 previous;
		swapz_u64x2 delta;

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

void swapz_unpredict_delta64_sse2(const swapz_u8 *input, swapz_u8 *output)
{
	unsigned long long previous = swapz_predictor_load64(input);
	swapz_u32 offset = SWAPZ_PREDICTOR_U64_BYTES;

	swapz_predictor_store64(output, previous);
	for (; offset + sizeof(swapz_u64x2) <= SWAPZ_BLOCK_BYTES;
	     offset += sizeof(swapz_u64x2)) {
		union swapz_vec128 delta;
		union swapz_vec128 prefix;
		swapz_u64x2 shifted;
		swapz_u64x2 base;

		memcpy(&delta.u64, input + offset, sizeof(delta.u64));
		shifted = (swapz_u64x2){0ULL, delta.u64[0]};
		prefix.u64 = delta.u64 + shifted;
		base = (swapz_u64x2){previous, previous};
		prefix.u64 += base;
		memcpy(output + offset, &prefix.u64, sizeof(prefix.u64));
		previous = prefix.u64[1];
	}
	for (; offset < SWAPZ_BLOCK_BYTES; offset += SWAPZ_PREDICTOR_U64_BYTES) {
		previous += swapz_predictor_load64(input + offset);
		swapz_predictor_store64(output + offset, previous);
	}
}
