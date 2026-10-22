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

static const char *swapz_transform_backend = "scalar";
static const char *swapz_inverse_backend = "scalar";

static swapz_u32 swapz_predict_delta64_pair_score_scalar(const swapz_u8 *input)
{
	unsigned long long previous = swapz_predictor_load64(input);
	unsigned long long value = swapz_predictor_load64(input + SWAPZ_PREDICTOR_U64_BYTES);
	if (swapz_predictor_small_nonzero_delta64(value, previous))
		return 2U;
	return swapz_predictor_small_nonzero_delta32((swapz_u32)value, (swapz_u32)previous) +
		swapz_predictor_small_nonzero_delta32((swapz_u32)(value >> 32),
						      (swapz_u32)(previous >> 32));
}

static swapz_u32 swapz_predict_delta64_sample_offset(swapz_u32 subpage,
						       swapz_u32 lane)
{
	swapz_u32 phase = (subpage + SWAPZ_PREDICTOR_SAMPLE_PHASE_STEP * lane) %
		SWAPZ_PREDICTOR_SAMPLE_PHASES;

	return subpage * SWAPZ_PREDICTOR_SUBPAGE_BYTES +
		lane * SWAPZ_PREDICTOR_SAMPLE_STRIDE_BYTES +
		phase * SWAPZ_PREDICTOR_SAMPLE_PHASE_BYTES;
}

swapz_u32 swapz_predict_delta64_sample_score_scalar(const swapz_u8 *input)
{
	swapz_u32 score = 0, subpage, lane;

	/*
	 * Spread the cheap stage across every 128-byte record lane and all
	 * eight 16-byte phases. Sampling only offset zero in each 512-byte
	 * region allowed repeated headers to hide structured values elsewhere.
	 */
	for (subpage = 0; subpage <
	     SWAPZ_BLOCK_BYTES / SWAPZ_PREDICTOR_SUBPAGE_BYTES; ++subpage) {
		lane = subpage % SWAPZ_PREDICTOR_SUBPAGE_LANES;
		score += swapz_predict_delta64_pair_score_scalar(
			input + swapz_predict_delta64_sample_offset(subpage, lane));
	}
	if (score < SWAPZ_PREDICTOR_STAGE1_MIN_SCORE)
		return 0;
	for (subpage = 0; subpage <
	     SWAPZ_BLOCK_BYTES / SWAPZ_PREDICTOR_SUBPAGE_BYTES; ++subpage) {
		for (lane = 0; lane < SWAPZ_PREDICTOR_SUBPAGE_LANES; ++lane) {
			if (lane == subpage % SWAPZ_PREDICTOR_SUBPAGE_LANES)
				continue;
			score += swapz_predict_delta64_pair_score_scalar(
				input + swapz_predict_delta64_sample_offset(subpage,
									   lane));
		}
	}
	return score;
}
swapz_u32 swapz_predict_delta64_scalar(const swapz_u8 *input, swapz_u8 *output)
{
	unsigned long long previous = swapz_predictor_load64(input);
	swapz_u32 offset;
	swapz_predictor_store64(output, previous);
	for (offset = sizeof(previous); offset < SWAPZ_BLOCK_BYTES; offset += sizeof(previous)) {
		unsigned long long value = swapz_predictor_load64(input + offset);
		swapz_predictor_store64(output + offset, value - previous);
		previous = value;
	}
	return 0;
}
void swapz_unpredict_delta64_scalar(const swapz_u8 *input, swapz_u8 *output)
{
	unsigned long long previous = swapz_predictor_load64(input);
	swapz_u32 offset;
	swapz_predictor_store64(output, previous);
	for (offset = sizeof(previous); offset < SWAPZ_BLOCK_BYTES; offset += sizeof(previous)) {
		previous += swapz_predictor_load64(input + offset);
		swapz_predictor_store64(output + offset, previous);
	}
}
#ifdef __KERNEL__
#if defined(CONFIG_X86_64)
#define SWAPZ_X86_TRANSFORM_WRAPPER(suffix) static swapz_u32 swapz_predict_##suffix(const swapz_u8 *input, swapz_u8 *output) { swapz_u32 result; if (!in_task()) return swapz_predict_delta64_scalar(input, output); kernel_fpu_begin(); result = swapz_predict_delta64_##suffix(input, output); kernel_fpu_end(); return result; }
#define SWAPZ_X86_INVERSE_WRAPPER(suffix) static void swapz_unpredict_##suffix(const swapz_u8 *input, swapz_u8 *output) { if (!in_task()) { swapz_unpredict_delta64_scalar(input, output); return; } kernel_fpu_begin(); swapz_unpredict_delta64_##suffix(input, output); kernel_fpu_end(); }
SWAPZ_X86_TRANSFORM_WRAPPER(sse2)
SWAPZ_X86_TRANSFORM_WRAPPER(avx2)
SWAPZ_X86_TRANSFORM_WRAPPER(avx512)
SWAPZ_X86_INVERSE_WRAPPER(sse2)
SWAPZ_X86_INVERSE_WRAPPER(avx2)
SWAPZ_X86_INVERSE_WRAPPER(avx512)
#undef SWAPZ_X86_TRANSFORM_WRAPPER
#undef SWAPZ_X86_INVERSE_WRAPPER
#endif
#if defined(CONFIG_ARM64) && defined(CONFIG_KERNEL_MODE_NEON)
static swapz_u32 swapz_predict_neon_guarded(const swapz_u8 *input, swapz_u8 *output)
{
	swapz_u32 result;
	if (!in_task()) return swapz_predict_delta64_scalar(input, output);
	kernel_fpu_begin(); result = swapz_predict_delta64_neon(input, output); kernel_fpu_end();
	return result;
}
static void swapz_unpredict_neon_guarded(const swapz_u8 *input, swapz_u8 *output)
{
	if (!in_task()) { swapz_unpredict_delta64_scalar(input, output); return; }
	kernel_fpu_begin(); swapz_unpredict_delta64_neon(input, output); kernel_fpu_end();
}
#endif
DEFINE_STATIC_CALL(swapz_predictor_transform_call, swapz_predict_delta64_scalar);
DEFINE_STATIC_CALL(swapz_predictor_inverse_call, swapz_unpredict_delta64_scalar);
int swapz_predictor_init(void)
{
	swapz_transform_backend = "scalar";
	swapz_inverse_backend = "scalar";
#if defined(CONFIG_X86_64)
	if (kernel_fpu_available() && boot_cpu_has(X86_FEATURE_AVX512F) &&
	    cpu_has_xfeatures(XFEATURE_MASK_SSE | XFEATURE_MASK_YMM |
			      XFEATURE_MASK_AVX512, NULL)) {
		static_call_update(swapz_predictor_transform_call, swapz_predict_avx512);
		static_call_update(swapz_predictor_inverse_call, swapz_unpredict_avx512);
		/*
		 * Native same-host qualification selected AVX-512 for both directions.
		 * Loaded rescue A/B remains the end-to-end policy evidence because the
		 * native timing does not include kernel_fpu_begin/end transition cost.
		 */
		swapz_transform_backend = "avx512"; swapz_inverse_backend = "avx512";
	} else if (kernel_fpu_available() && boot_cpu_has(X86_FEATURE_AVX2) &&
		   cpu_has_xfeatures(XFEATURE_MASK_SSE | XFEATURE_MASK_YMM, NULL)) {
		static_call_update(swapz_predictor_transform_call, swapz_predict_avx2);
		/*
		 * Same-host batched evidence on AVX2 x86 shows the dependency-heavy
		 * inverse remains faster in scalar C than either vector backend.
		 */
		swapz_transform_backend = "avx2"; swapz_inverse_backend = "scalar";
	} else if (kernel_fpu_available() && boot_cpu_has(X86_FEATURE_XMM2) &&
		   cpu_has_xfeatures(XFEATURE_MASK_SSE, NULL)) {
		static_call_update(swapz_predictor_transform_call, swapz_predict_sse2);
		static_call_update(swapz_predictor_inverse_call, swapz_unpredict_sse2);
		swapz_transform_backend = "sse2"; swapz_inverse_backend = "sse2";
	}
#elif defined(CONFIG_ARM64) && defined(CONFIG_KERNEL_MODE_NEON)
	if (kernel_fpu_available()) {
		static_call_update(swapz_predictor_transform_call, swapz_predict_neon_guarded);
		static_call_update(swapz_predictor_inverse_call, swapz_unpredict_neon_guarded);
		swapz_transform_backend = "neon"; swapz_inverse_backend = "neon";
	}
#endif
	pr_info("swapz: delta64 classifier=scalar transform=%s inverse=%s\n",
		swapz_transform_backend, swapz_inverse_backend);
	return 0;
}
const char *swapz_predictor_transform_backend_name(void){ return swapz_transform_backend; }
const char *swapz_predictor_inverse_backend_name(void){ return swapz_inverse_backend; }
swapz_u32 swapz_predict_delta64_sample_score(const swapz_u8 *input)
{ return swapz_predict_delta64_sample_score_scalar(input); }
swapz_u32 swapz_predict_delta64(const swapz_u8 *input, swapz_u8 *output)
{ return static_call(swapz_predictor_transform_call)(input, output); }
void swapz_unpredict_delta64(const swapz_u8 *input, swapz_u8 *output)
{ static_call(swapz_predictor_inverse_call)(input, output); }
#else
typedef swapz_u32 (*swapz_predict_fn)(const swapz_u8 *, swapz_u8 *);
typedef void (*swapz_unpredict_fn)(const swapz_u8 *, swapz_u8 *);
static swapz_predict_fn swapz_predict_impl = swapz_predict_delta64_scalar;
static swapz_unpredict_fn swapz_unpredict_impl = swapz_unpredict_delta64_scalar;
int swapz_predictor_init(void)
{
	swapz_transform_backend = "scalar"; swapz_inverse_backend = "scalar";
	swapz_predict_impl = swapz_predict_delta64_scalar;
	swapz_unpredict_impl = swapz_unpredict_delta64_scalar;
#if defined(__x86_64__) && (defined(__GNUC__) || defined(__clang__))
	__builtin_cpu_init();
	if (__builtin_cpu_supports("avx512f")) {
		swapz_predict_impl = swapz_predict_delta64_avx512;
		swapz_unpredict_impl = swapz_unpredict_delta64_avx512;
		swapz_transform_backend = "avx512"; swapz_inverse_backend = "avx512";
	} else if (__builtin_cpu_supports("avx2")) {
		swapz_predict_impl = swapz_predict_delta64_avx2;
		swapz_unpredict_impl = swapz_unpredict_delta64_scalar;
		swapz_transform_backend = "avx2"; swapz_inverse_backend = "scalar";
	} else {
		swapz_predict_impl = swapz_predict_delta64_sse2;
		swapz_unpredict_impl = swapz_unpredict_delta64_sse2;
		swapz_transform_backend = "sse2"; swapz_inverse_backend = "sse2";
	}
#elif defined(__aarch64__)
	swapz_predict_impl = swapz_predict_delta64_neon;
	swapz_unpredict_impl = swapz_unpredict_delta64_neon;
	swapz_transform_backend = "neon"; swapz_inverse_backend = "neon";
#endif
	return 0;
}
const char *swapz_predictor_transform_backend_name(void){ return swapz_transform_backend; }
const char *swapz_predictor_inverse_backend_name(void){ return swapz_inverse_backend; }
swapz_u32 swapz_predict_delta64_sample_score(const swapz_u8 *input)
{ return swapz_predict_delta64_sample_score_scalar(input); }
swapz_u32 swapz_predict_delta64(const swapz_u8 *input, swapz_u8 *output)
{ return swapz_predict_impl(input, output); }
void swapz_unpredict_delta64(const swapz_u8 *input, swapz_u8 *output)
{ swapz_unpredict_impl(input, output); }
#endif
int swapz_predict_should_try_delta64(const swapz_u8 *input, swapz_u32 threshold)
{
	return input && threshold && threshold <= 2U * SWAPZ_PREDICTOR_SAMPLE_PAIRS &&
	       swapz_predict_delta64_sample_score(input) >= threshold;
}
