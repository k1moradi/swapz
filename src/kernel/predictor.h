/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_PREDICTOR_H
#define SWAPZ_PREDICTOR_H

#include "codec.h"

#ifdef __KERNEL__
#include <linux/string.h>
#else
#include <string.h>
#endif

#define SWAPZ_PREDICTOR_CACHELINE_BYTES 64U
#define SWAPZ_PREDICTOR_U64_BYTES 8U
#define SWAPZ_PREDICTOR_CL_WORDS 8U
#define SWAPZ_PREDICTOR_CL_DELTA32X2_RESIDUALS 896U
#define SWAPZ_PREDICTOR_SUBPAGE_BYTES 512U
#define SWAPZ_PREDICTOR_STAGE1_PAIRS 8U
#define SWAPZ_PREDICTOR_STAGE1_MIN_SCORE 2U
#define SWAPZ_PREDICTOR_SAMPLE_STRIDE_BYTES 128U
#define SWAPZ_PREDICTOR_SAMPLE_PAIRS 32U

#if __SIZEOF_LONG_LONG__ != 8
#error "swapz predictor qualification requires an exact 64-bit unsigned long long"
#endif

static inline swapz_u32 swapz_predictor_load32(const swapz_u8 *bytes)
{
	swapz_u32 value;

	memcpy(&value, bytes, sizeof(value));
	return value;
}

static inline void swapz_predictor_store32(swapz_u8 *bytes, swapz_u32 value)
{
	memcpy(bytes, &value, sizeof(value));
}

static inline unsigned long long swapz_predictor_load64(const swapz_u8 *bytes)
{
	unsigned long long value;

	memcpy(&value, bytes, sizeof(value));
	return value;
}

static inline void swapz_predictor_store64(swapz_u8 *bytes,
					   unsigned long long value)
{
	memcpy(bytes, &value, sizeof(value));
}

static inline int swapz_predictor_small_nonzero_delta32(swapz_u32 current,
						 swapz_u32 previous)
{
	swapz_u32 delta = current - previous;

	return delta && (swapz_u32)(delta + 128U) <= 255U;
}

static inline int swapz_predictor_small_nonzero_delta64(
					unsigned long long current,
					unsigned long long previous)
{
	unsigned long long delta = current - previous;

	return delta && (unsigned long long)(delta + 0x8000ULL) <= 0xffffULL;
}

/*
 * Cacheline-reset two-lane 32-bit delta. Each 8-byte word is treated as two
 * independent u32 lanes. The first word in every 64-byte cacheline is an
 * anchor, bounding decode dependency to seven words and preventing low-lane
 * borrow from perturbing the neighboring high lane.
 *
 * The return value is a free classifier collected during the transform:
 * the number of residual u32 lanes fitting signed 8 bits. Such residuals have
 * three identical high bytes (00 or ff), which is useful LZ4 evidence without
 * a second scan.
 */
static inline swapz_u32 swapz_predict_cl_delta32x2(const swapz_u8 *input,
					    swapz_u8 *output)
{
	swapz_u32 small_residuals = 0;
	swapz_u32 line;

	for (line = 0; line < SWAPZ_BLOCK_BYTES;
	     line += SWAPZ_PREDICTOR_CACHELINE_BYTES) {
		swapz_u32 previous0 = swapz_predictor_load32(input + line);
		swapz_u32 previous1 =
			swapz_predictor_load32(input + line + sizeof(swapz_u32));
		swapz_u32 word;

		swapz_predictor_store32(output + line, previous0);
		swapz_predictor_store32(output + line + sizeof(swapz_u32),
					 previous1);
		for (word = 1; word < SWAPZ_PREDICTOR_CL_WORDS; ++word) {
			swapz_u32 offset = line +
				word * SWAPZ_PREDICTOR_U64_BYTES;
			swapz_u32 current0 =
				swapz_predictor_load32(input + offset);
			swapz_u32 current1 =
				swapz_predictor_load32(input + offset +
						       sizeof(swapz_u32));
			swapz_u32 delta0 = current0 - previous0;
			swapz_u32 delta1 = current1 - previous1;

			swapz_predictor_store32(output + offset, delta0);
			swapz_predictor_store32(output + offset +
					       sizeof(swapz_u32), delta1);
			small_residuals +=
				swapz_predictor_small_nonzero_delta32(current0,
								       previous0);
			small_residuals +=
				swapz_predictor_small_nonzero_delta32(current1,
								       previous1);
			previous0 = current0;
			previous1 = current1;
		}
	}
	return small_residuals;
}

static inline void swapz_unpredict_cl_delta32x2(const swapz_u8 *input,
						 swapz_u8 *output)
{
	swapz_u32 line;

	for (line = 0; line < SWAPZ_BLOCK_BYTES;
	     line += SWAPZ_PREDICTOR_CACHELINE_BYTES) {
		swapz_u32 previous0 = swapz_predictor_load32(input + line);
		swapz_u32 previous1 =
			swapz_predictor_load32(input + line + sizeof(swapz_u32));
		swapz_u32 word;

		swapz_predictor_store32(output + line, previous0);
		swapz_predictor_store32(output + line + sizeof(swapz_u32),
					 previous1);
		for (word = 1; word < SWAPZ_PREDICTOR_CL_WORDS; ++word) {
			swapz_u32 offset = line +
				word * SWAPZ_PREDICTOR_U64_BYTES;
			swapz_u32 current0 =
				previous0 + swapz_predictor_load32(input + offset);
			swapz_u32 current1 =
				previous1 + swapz_predictor_load32(
					input + offset + sizeof(swapz_u32));

			swapz_predictor_store32(output + offset, current0);
			swapz_predictor_store32(output + offset +
					       sizeof(swapz_u32), current1);
			previous0 = current0;
			previous1 = current1;
		}
	}
}

static inline swapz_u32 swapz_predict_cl_bytedelta8(const swapz_u8 *input,
					     swapz_u8 *output)
{
	swapz_u32 line;

	for (line = 0; line < SWAPZ_BLOCK_BYTES;
	     line += SWAPZ_PREDICTOR_CACHELINE_BYTES) {
		swapz_u32 index;

		output[line] = input[line];
		for (index = 1; index < SWAPZ_PREDICTOR_CACHELINE_BYTES; ++index)
			output[line + index] =
				(swapz_u8)(input[line + index] -
					   input[line + index - 1U]);
	}
	return 0;
}

static inline void swapz_unpredict_cl_bytedelta8(const swapz_u8 *input,
						  swapz_u8 *output)
{
	swapz_u32 line;

	for (line = 0; line < SWAPZ_BLOCK_BYTES;
	     line += SWAPZ_PREDICTOR_CACHELINE_BYTES) {
		swapz_u32 index;

		output[line] = input[line];
		for (index = 1; index < SWAPZ_PREDICTOR_CACHELINE_BYTES; ++index)
			output[line + index] =
				(swapz_u8)(output[line + index - 1U] +
					   input[line + index]);
	}
}

static inline swapz_u32 swapz_predict_delta32(const swapz_u8 *input,
					       swapz_u8 *output)
{
	swapz_u32 previous = swapz_predictor_load32(input);
	swapz_u32 offset;

	swapz_predictor_store32(output, previous);
	for (offset = sizeof(swapz_u32); offset < SWAPZ_BLOCK_BYTES;
	     offset += sizeof(swapz_u32)) {
		swapz_u32 current = swapz_predictor_load32(input + offset);

		swapz_predictor_store32(output + offset, current - previous);
		previous = current;
	}
	return 0;
}

static inline void swapz_unpredict_delta32(const swapz_u8 *input,
					    swapz_u8 *output)
{
	swapz_u32 previous = swapz_predictor_load32(input);
	swapz_u32 offset;

	swapz_predictor_store32(output, previous);
	for (offset = sizeof(swapz_u32); offset < SWAPZ_BLOCK_BYTES;
	     offset += sizeof(swapz_u32)) {
		swapz_u32 current =
			previous + swapz_predictor_load32(input + offset);

		swapz_predictor_store32(output + offset, current);
		previous = current;
	}
}

/*
 * Cheap rescue signpost for whole-page delta64. A pair contributes two points
 * for a nonzero signed-16-bit u64 delta, otherwise one point for each nonzero
 * signed-8-bit u32 lane delta. Identical raw words deliberately contribute
 * nothing because plain LZ4 already sees that repetition.
 */
static inline swapz_u32 swapz_predict_delta64_pair_score(
						const swapz_u8 *input)
{
	unsigned long long previous = swapz_predictor_load64(input);
	unsigned long long current =
		swapz_predictor_load64(input + SWAPZ_PREDICTOR_U64_BYTES);

	if (swapz_predictor_small_nonzero_delta64(current, previous))
		return 2U;
	return swapz_predictor_small_nonzero_delta32(
			(swapz_u32)current, (swapz_u32)previous) +
		swapz_predictor_small_nonzero_delta32(
			(swapz_u32)(current >> 32),
			(swapz_u32)(previous >> 32));
}

/*
 * ID67a.3 two-stage strided router. Stage 1 touches one adjacent pair in each
 * 512-byte region (8 pairs / 128 bytes total). Pages with fewer than two points
 * stop immediately. Passing pages add three evenly spaced pairs per region for
 * 32 pairs / 512 bytes total.
 */
static inline swapz_u32 swapz_predict_delta64_sample_score(
						const swapz_u8 *input)
{
	swapz_u32 score = 0;
	swapz_u32 base, offset;

	for (base = 0; base < SWAPZ_BLOCK_BYTES;
	     base += SWAPZ_PREDICTOR_SUBPAGE_BYTES)
		score += swapz_predict_delta64_pair_score(input + base);
	if (score < SWAPZ_PREDICTOR_STAGE1_MIN_SCORE)
		return 0;
	for (offset = SWAPZ_PREDICTOR_SAMPLE_STRIDE_BYTES;
	     offset < SWAPZ_PREDICTOR_SUBPAGE_BYTES;
	     offset += SWAPZ_PREDICTOR_SAMPLE_STRIDE_BYTES)
		for (base = 0; base < SWAPZ_BLOCK_BYTES;
		     base += SWAPZ_PREDICTOR_SUBPAGE_BYTES)
			score += swapz_predict_delta64_pair_score(input + base + offset);
	return score;
}

static inline int swapz_predict_should_try_delta64(const swapz_u8 *input,
						   swapz_u32 threshold)
{
	return input && threshold &&
	       threshold <= 2U * SWAPZ_PREDICTOR_SAMPLE_PAIRS &&
	       swapz_predict_delta64_sample_score(input) >= threshold;
}

static inline swapz_u32 swapz_predict_delta64(const swapz_u8 *input,
					       swapz_u8 *output)
{
	unsigned long long previous = swapz_predictor_load64(input);
	swapz_u32 offset;

	swapz_predictor_store64(output, previous);
	for (offset = sizeof(previous); offset < SWAPZ_BLOCK_BYTES;
	     offset += sizeof(previous)) {
		unsigned long long current =
			swapz_predictor_load64(input + offset);

		swapz_predictor_store64(output + offset, current - previous);
		previous = current;
	}
	return 0;
}

static inline void swapz_unpredict_delta64(const swapz_u8 *input,
					    swapz_u8 *output)
{
	unsigned long long previous = swapz_predictor_load64(input);
	swapz_u32 offset;

	swapz_predictor_store64(output, previous);
	for (offset = sizeof(previous); offset < SWAPZ_BLOCK_BYTES;
	     offset += sizeof(previous)) {
		unsigned long long current =
			previous + swapz_predictor_load64(input + offset);

		swapz_predictor_store64(output + offset, current);
		previous = current;
	}
}

/* Eight anchors per page: a middle ground between whole-page delta64 and
 * cacheline-reset prediction for independently based subpage structures. */
static inline swapz_u32 swapz_predict_delta64_512(const swapz_u8 *input,
						   swapz_u8 *output)
{
	swapz_u32 base;

	for (base = 0; base < SWAPZ_BLOCK_BYTES;
	     base += SWAPZ_PREDICTOR_SUBPAGE_BYTES) {
		unsigned long long previous = swapz_predictor_load64(input + base);
		swapz_u32 offset;

		swapz_predictor_store64(output + base, previous);
		for (offset = base + sizeof(previous);
		     offset < base + SWAPZ_PREDICTOR_SUBPAGE_BYTES;
		     offset += sizeof(previous)) {
			unsigned long long current =
				swapz_predictor_load64(input + offset);

			swapz_predictor_store64(output + offset, current - previous);
			previous = current;
		}
	}
	return 0;
}

static inline void swapz_unpredict_delta64_512(const swapz_u8 *input,
						swapz_u8 *output)
{
	swapz_u32 base;

	for (base = 0; base < SWAPZ_BLOCK_BYTES;
	     base += SWAPZ_PREDICTOR_SUBPAGE_BYTES) {
		unsigned long long previous = swapz_predictor_load64(input + base);
		swapz_u32 offset;

		swapz_predictor_store64(output + base, previous);
		for (offset = base + sizeof(previous);
		     offset < base + SWAPZ_PREDICTOR_SUBPAGE_BYTES;
		     offset += sizeof(previous)) {
			unsigned long long current =
				previous + swapz_predictor_load64(input + offset);

			swapz_predictor_store64(output + offset, current);
			previous = current;
		}
	}
}

static inline swapz_u32 swapz_predict_xor64(const swapz_u8 *input,
					     swapz_u8 *output)
{
	unsigned long long previous = swapz_predictor_load64(input);
	swapz_u32 offset;

	swapz_predictor_store64(output, previous);
	for (offset = sizeof(previous); offset < SWAPZ_BLOCK_BYTES;
	     offset += sizeof(previous)) {
		unsigned long long current =
			swapz_predictor_load64(input + offset);

		swapz_predictor_store64(output + offset, current ^ previous);
		previous = current;
	}
	return 0;
}

static inline void swapz_unpredict_xor64(const swapz_u8 *input,
					  swapz_u8 *output)
{
	unsigned long long previous = swapz_predictor_load64(input);
	swapz_u32 offset;

	memcpy(output, input, sizeof(previous));
	for (offset = sizeof(previous); offset < SWAPZ_BLOCK_BYTES;
	     offset += sizeof(previous)) {
		unsigned long long current =
			previous ^ swapz_predictor_load64(input + offset);

		swapz_predictor_store64(output + offset, current);
		previous = current;
	}
}

#endif
