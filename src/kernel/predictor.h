/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_PREDICTOR_H
#define SWAPZ_PREDICTOR_H

#include "codec.h"

#define SWAPZ_PREDICTOR_CACHELINE_BYTES 64U /* structured corpus geometry */
#define SWAPZ_PREDICTOR_U64_BYTES 8U
#define SWAPZ_PREDICTOR_SUBPAGE_BYTES 512U
#define SWAPZ_PREDICTOR_STAGE1_PAIRS 8U
#define SWAPZ_PREDICTOR_STAGE1_MIN_SCORE 2U
#define SWAPZ_PREDICTOR_SAMPLE_STRIDE_BYTES 128U
#define SWAPZ_PREDICTOR_SAMPLE_PAIRS 32U

#if __SIZEOF_LONG_LONG__ != 8
#error "swapz delta64 predictor requires an exact 64-bit unsigned long long"
#endif

int swapz_predictor_init(void);
const char *swapz_predictor_transform_backend_name(void);
const char *swapz_predictor_inverse_backend_name(void);

swapz_u32 swapz_predict_delta64_sample_score(const swapz_u8 *input);
int swapz_predict_should_try_delta64(const swapz_u8 *input, swapz_u32 threshold);
swapz_u32 swapz_predict_delta64(const swapz_u8 *input, swapz_u8 *output);
void swapz_unpredict_delta64(const swapz_u8 *input, swapz_u8 *output);

#endif
