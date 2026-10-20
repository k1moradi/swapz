// SPDX-License-Identifier: GPL-2.0-only
#include "predictor-internal.h"

#ifdef __KERNEL__
#include <linux/fpu.h>
#include <linux/preempt.h>
#include <linux/printk.h>
#include <linux/static_call.h>
#if defined(CONFIG_X86_64)
#include <asm/cpufeature.h>
#include <asm/fpu/api.h>
#include <asm/fpu/types.h>
#endif
#endif

static const char *swapz_predictor_backend = "scalar";

static swapz_u32 swapz_predict_delta64_pair_score_scalar(
						const swapz_u8 *input)
{
	unsigned long long previous = swapz_predictor_load64(input);
	unsigned long long value =
		swapz_predictor_load64(input + SWAPZ_PREDICTOR_U64_BYTES);

	if (swapz_predictor_small_nonzero_delta64(value, previous))
		return 2U;
	return swapz_predictor_small_nonzero_delta32(
			(swapz_u32)value, (swapz_u32)previous) +
		swapz_predictor_small_nonzero_delta32(
			(swapz_u32)(value >> 32),
			(swapz_u32)(previous >> 32));
}

swapz_u32 swapz_predict_delta64_sample_score_scalar(const swapz_u8 *input)
{
	swapz_u32 score = 0;
	swapz_u32 base;

	for (base = 0; base < SWAPZ_BLOCK_BYTES;
	     base += SWAPZ_PREDICTOR_SUBPAGE_BYTES)
		score += swapz_predict_delta64_pair_score_scalar(input + base);
	if (score < SWAPZ_PREDICTOR_STAGE1_MIN_SCORE)
		return 0;
	for (base = 0; base < SWAPZ_BLOCK_BYTES;
	     base += SWAPZ_PREDICTOR_SUBPAGE_BYTES) {
		score += swapz_predict_delta64_pair_score_scalar(
			input + base + SWAPZ_PREDICTOR_SAMPLE_STRIDE_BYTES);
		score += swapz_predict_delta64_pair_score_scalar(
			input + base + 2U * SWAPZ_PREDICTOR_SAMPLE_STRIDE_BYTES);
		score += swapz_predict_delta64_pair_score_scalar(
			input + base + 3U * SWAPZ_PREDICTOR_SAMPLE_STRIDE_BYTES);
	}
	return score;
}

swapz_u32 swapz_predict_delta64_scalar(const swapz_u8 *input,
				       swapz_u8 *output)
{
	unsigned long long previous = swapz_predictor_load64(input);
	swapz_u32 offset;

	swapz_predictor_store64(output, previous);
	for (offset = sizeof(previous); offset < SWAPZ_BLOCK_BYTES;
	     offset += sizeof(previous)) {
		unsigned long long value =
			swapz_predictor_load64(input + offset);

		swapz_predictor_store64(output + offset, value - previous);
		previous = value;
	}
	return 0;
}

void swapz_unpredict_delta64_scalar(const swapz_u8 *input,
				    swapz_u8 *output)
{
	unsigned long long previous = swapz_predictor_load64(input);
	swapz_u32 offset;

	swapz_predictor_store64(output, previous);
	for (offset = sizeof(previous); offset < SWAPZ_BLOCK_BYTES;
	     offset += sizeof(previous)) {
		previous += swapz_predictor_load64(input + offset);
		swapz_predictor_store64(output + offset, previous);
	}
}

#ifdef __KERNEL__

#if defined(CONFIG_X86_64)
#define SWAPZ_X86_SIMD_WRAPPERS(suffix) static swapz_u32 swapz_score_##suffix(const swapz_u8 *input) { 	swapz_u32 score; 	if (!in_task()) 		return swapz_predict_delta64_sample_score_scalar(input); 	kernel_fpu_begin(); 	score = swapz_predict_delta64_sample_score_##suffix(input); 	kernel_fpu_end(); 	return score; } static swapz_u32 swapz_predict_##suffix(const swapz_u8 *input, 					swapz_u8 *output) { 	swapz_u32 result; 	if (!in_task()) 		return swapz_predict_delta64_scalar(input, output); 	kernel_fpu_begin(); 	result = swapz_predict_delta64_##suffix(input, output); 	kernel_fpu_end(); 	return result; } static void swapz_unpredict_##suffix(const swapz_u8 *input, 				     swapz_u8 *output) { 	if (!in_task()) { 		swapz_unpredict_delta64_scalar(input, output); 		return; 	} 	kernel_fpu_begin(); 	swapz_unpredict_delta64_##suffix(input, output); 	kernel_fpu_end(); }

SWAPZ_X86_SIMD_WRAPPERS(sse2)
SWAPZ_X86_SIMD_WRAPPERS(avx2)
#undef SWAPZ_X86_SIMD_WRAPPERS
#endif

#if defined(CONFIG_ARM64) && defined(CONFIG_KERNEL_MODE_NEON)
static swapz_u32 swapz_score_neon_guarded(const swapz_u8 *input)
{
	swapz_u32 score;

	if (!in_task())
		return swapz_predict_delta64_sample_score_scalar(input);
	kernel_fpu_begin();
	score = swapz_predict_delta64_sample_score_neon(input);
	kernel_fpu_end();
	return score;
}

static swapz_u32 swapz_predict_neon_guarded(const swapz_u8 *input,
					    swapz_u8 *output)
{
	swapz_u32 result;

	if (!in_task())
		return swapz_predict_delta64_scalar(input, output);
	kernel_fpu_begin();
	result = swapz_predict_delta64_neon(input, output);
	kernel_fpu_end();
	return result;
}

static void swapz_unpredict_neon_guarded(const swapz_u8 *input,
					 swapz_u8 *output)
{
	if (!in_task()) {
		swapz_unpredict_delta64_scalar(input, output);
		return;
	}
	kernel_fpu_begin();
	swapz_unpredict_delta64_neon(input, output);
	kernel_fpu_end();
}
#endif

DEFINE_STATIC_CALL(swapz_predictor_score_call,
		   swapz_predict_delta64_sample_score_scalar);
DEFINE_STATIC_CALL(swapz_predictor_transform_call, swapz_predict_delta64_scalar);
DEFINE_STATIC_CALL(swapz_predictor_inverse_call, swapz_unpredict_delta64_scalar);

int swapz_predictor_init(void)
{
	swapz_predictor_backend = "scalar";

#if defined(CONFIG_X86_64)
	if (kernel_fpu_available() &&
	    boot_cpu_has(X86_FEATURE_AVX2) &&
	    cpu_has_xfeatures(XFEATURE_MASK_SSE | XFEATURE_MASK_YMM, NULL)) {
		static_call_update(swapz_predictor_score_call, swapz_score_avx2);
		static_call_update(swapz_predictor_transform_call, swapz_predict_avx2);
		static_call_update(swapz_predictor_inverse_call, swapz_unpredict_avx2);
		swapz_predictor_backend = "avx2";
	} else if (kernel_fpu_available() &&
		   boot_cpu_has(X86_FEATURE_XMM2) &&
		   cpu_has_xfeatures(XFEATURE_MASK_SSE, NULL)) {
		static_call_update(swapz_predictor_score_call, swapz_score_sse2);
		static_call_update(swapz_predictor_transform_call, swapz_predict_sse2);
		static_call_update(swapz_predictor_inverse_call, swapz_unpredict_sse2);
		swapz_predictor_backend = "sse2";
	}
#elif defined(CONFIG_ARM64) && defined(CONFIG_KERNEL_MODE_NEON)
	if (kernel_fpu_available()) {
		static_call_update(swapz_predictor_score_call,
				   swapz_score_neon_guarded);
		static_call_update(swapz_predictor_transform_call,
				   swapz_predict_neon_guarded);
		static_call_update(swapz_predictor_inverse_call,
				   swapz_unpredict_neon_guarded);
		swapz_predictor_backend = "neon";
	}
#endif
	pr_info("swapz: delta64 predictor backend=%s\n", swapz_predictor_backend);
	return 0;
}

const char *swapz_predictor_backend_name(void)
{
	return swapz_predictor_backend;
}

swapz_u32 swapz_predict_delta64_sample_score(const swapz_u8 *input)
{
	return static_call(swapz_predictor_score_call)(input);
}

swapz_u32 swapz_predict_delta64(const swapz_u8 *input, swapz_u8 *output)
{
	return static_call(swapz_predictor_transform_call)(input, output);
}

void swapz_unpredict_delta64(const swapz_u8 *input, swapz_u8 *output)
{
	static_call(swapz_predictor_inverse_call)(input, output);
}

#else

typedef swapz_u32 (*swapz_score_fn)(const swapz_u8 *);
typedef swapz_u32 (*swapz_predict_fn)(const swapz_u8 *, swapz_u8 *);
typedef void (*swapz_unpredict_fn)(const swapz_u8 *, swapz_u8 *);

static swapz_score_fn swapz_score_impl =
	swapz_predict_delta64_sample_score_scalar;
static swapz_predict_fn swapz_predict_impl = swapz_predict_delta64_scalar;
static swapz_unpredict_fn swapz_unpredict_impl = swapz_unpredict_delta64_scalar;

int swapz_predictor_init(void)
{
	swapz_predictor_backend = "scalar";
	swapz_score_impl = swapz_predict_delta64_sample_score_scalar;
	swapz_predict_impl = swapz_predict_delta64_scalar;
	swapz_unpredict_impl = swapz_unpredict_delta64_scalar;

#if defined(__x86_64__) && (defined(__GNUC__) || defined(__clang__))
	__builtin_cpu_init();
	if (__builtin_cpu_supports("avx2")) {
		swapz_score_impl = swapz_predict_delta64_sample_score_avx2;
		swapz_predict_impl = swapz_predict_delta64_avx2;
		swapz_unpredict_impl = swapz_unpredict_delta64_avx2;
		swapz_predictor_backend = "avx2";
	} else {
		swapz_score_impl = swapz_predict_delta64_sample_score_sse2;
		swapz_predict_impl = swapz_predict_delta64_sse2;
		swapz_unpredict_impl = swapz_unpredict_delta64_sse2;
		swapz_predictor_backend = "sse2";
	}
#elif defined(__aarch64__)
	swapz_score_impl = swapz_predict_delta64_sample_score_neon;
	swapz_predict_impl = swapz_predict_delta64_neon;
	swapz_unpredict_impl = swapz_unpredict_delta64_neon;
	swapz_predictor_backend = "neon";
#endif
	return 0;
}

const char *swapz_predictor_backend_name(void)
{
	return swapz_predictor_backend;
}

swapz_u32 swapz_predict_delta64_sample_score(const swapz_u8 *input)
{
	return swapz_score_impl(input);
}

swapz_u32 swapz_predict_delta64(const swapz_u8 *input, swapz_u8 *output)
{
	return swapz_predict_impl(input, output);
}

void swapz_unpredict_delta64(const swapz_u8 *input, swapz_u8 *output)
{
	swapz_unpredict_impl(input, output);
}

#endif

int swapz_predict_should_try_delta64(const swapz_u8 *input,
				     swapz_u32 threshold)
{
	return input && threshold &&
	       threshold <= 2U * SWAPZ_PREDICTOR_SAMPLE_PAIRS &&
	       swapz_predict_delta64_sample_score(input) >= threshold;
}
