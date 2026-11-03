// SPDX-License-Identifier: GPL-2.0-only
/* Execute the production preparation result classifier and publication race. */
#include <errno.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>

typedef int64_t s64;
typedef struct { _Atomic int64_t value; } atomic64_t;
typedef struct { _Atomic int value; } atomic_t;

static int atomic_read_acquire(const atomic_t *value)
{
	return atomic_load_explicit(&value->value, memory_order_acquire);
}

static int atomic_cmpxchg(atomic_t *value, int old, int replacement)
{
	atomic_compare_exchange_strong_explicit(&value->value, &old, replacement,
			memory_order_seq_cst, memory_order_relaxed);
	return old;
}

static s64 atomic64_read(atomic64_t *mask)
{
	return atomic_load_explicit(&mask->value, memory_order_relaxed);
}

static s64 atomic64_cmpxchg(atomic64_t *mask, s64 old, s64 value)
{
	atomic_compare_exchange_strong_explicit(&mask->value, &old, value,
			memory_order_seq_cst, memory_order_relaxed);
	return old;
}

static void atomic64_or(s64 bits, atomic64_t *mask)
{
	atomic_fetch_or_explicit(&mask->value, bits, memory_order_relaxed);
}

#define __ffs64(word) ((unsigned int)__builtin_ctzll(word))
#define smp_mb__before_atomic() atomic_thread_fence(memory_order_seq_cst)
#include "preparation-slots.h"

#define CHECK(expression) do { if (!(expression)) { \
	fprintf(stderr, "%s:%d failed %s\\n", __FILE__, __LINE__, #expression); \
	return 1; \
} } while (0)

static int test_codec_result_classification(void)
{
	CHECK(swapz_preparation_codec_result_state(-EINVAL) ==
	      SWAPZ_PREPARATION_ERROR);
	CHECK(swapz_preparation_codec_result_state(-EIO) ==
	      SWAPZ_PREPARATION_ERROR);
	CHECK(swapz_preparation_codec_result_state(0) ==
	      SWAPZ_PREPARATION_READY_RAW);
	CHECK(swapz_preparation_codec_result_state(1) ==
	      SWAPZ_PREPARATION_READY_COMPRESSED);
	CHECK(swapz_preparation_codec_result_state(4096) ==
	      SWAPZ_PREPARATION_READY_COMPRESSED);
	return 0;
}

static int test_codec_success_publication(void)
{
	atomic_t state;

	atomic_init(&state.value, SWAPZ_PREPARATION_PREPARING);
	CHECK(swapz_preparation_publish_codec_result(&state, 0) ==
	      SWAPZ_PREPARATION_PREPARING);
	CHECK(swapz_preparation_read_state(&state) ==
	      SWAPZ_PREPARATION_READY_RAW);

	atomic_store(&state.value, SWAPZ_PREPARATION_PREPARING);
	CHECK(swapz_preparation_publish_codec_result(&state, 1024) ==
	      SWAPZ_PREPARATION_PREPARING);
	CHECK(swapz_preparation_read_state(&state) ==
	      SWAPZ_PREPARATION_READY_COMPRESSED);
	return 0;
}

static int test_codec_error_publication_wins(void)
{
	atomic_t state;

	atomic_init(&state.value, SWAPZ_PREPARATION_PREPARING);
	CHECK(swapz_preparation_publish_codec_result(&state, -EIO) ==
	      SWAPZ_PREPARATION_PREPARING);
	CHECK(swapz_preparation_select_raw(&state) == SWAPZ_PREPARATION_ERROR);
	CHECK(atomic_read_acquire(&state) == SWAPZ_PREPARATION_ERROR);
	return 0;
}

static int test_raw_selection_wins_late_codec_error(void)
{
	atomic_t state;

	atomic_init(&state.value, SWAPZ_PREPARATION_PREPARING);
	CHECK(swapz_preparation_select_raw(&state) ==
	      SWAPZ_PREPARATION_RAW_SELECTED);
	CHECK(swapz_preparation_publish_codec_result(&state, -EIO) ==
	      SWAPZ_PREPARATION_RAW_SELECTED);
	CHECK(atomic_read_acquire(&state) == SWAPZ_PREPARATION_RAW_SELECTED);
	return 0;
}

int main(void)
{
	CHECK(!test_codec_result_classification());
	CHECK(!test_codec_success_publication());
	CHECK(!test_codec_error_publication_wins());
	CHECK(!test_raw_selection_wins_late_codec_error());
	puts("SWAPZ_PREPARATION_CODEC_RESULT_PASS=4");
	return 0;
}
