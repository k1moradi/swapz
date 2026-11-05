// SPDX-License-Identifier: GPL-2.0-only
/* Execute the production preparation result classifier and publication race. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <pthread.h>
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

/*
 * Linux release_slot() is a full barrier before a relaxed atomic OR. GCC's
 * TSan rejects atomic_thread_fence() under -Werror because it cannot instrument
 * standalone fences. Give the sanitizer an equivalent release edge on the RMW
 * itself; successful slot claims use an acquire/seq_cst cmpxchg. Non-TSan
 * builds retain the explicit fence model used by the production-header shim.
 */
#if defined(__SANITIZE_THREAD__)
static void atomic64_or(s64 bits, atomic64_t *mask)
{
	atomic_fetch_or_explicit(&mask->value, bits, memory_order_release);
}
#define smp_mb__before_atomic() ((void)0)
#else
static void atomic64_or(s64 bits, atomic64_t *mask)
{
	atomic_fetch_or_explicit(&mask->value, bits, memory_order_relaxed);
}
#define smp_mb__before_atomic() atomic_thread_fence(memory_order_seq_cst)
#endif

#define __ffs64(word) ((unsigned int)__builtin_ctzll(word))
#include "preparation-slots.h"

#define CHECK(expression) do { if (!(expression)) { \
	fprintf(stderr, "%s:%d failed %s\n", __FILE__, __LINE__, #expression); \
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

/*
 * Terminal publications are one-shot: neither a later successful codec
 * result nor a late failure may overwrite READY, ERROR, RAW_SELECTED,
 * CANCELLED or CONSUMED.
 * Invalid direct ready-state requests must not mutate PREPARING either.
 */
static int test_terminal_states_reject_republication(void)
{
	const int states[] = { SWAPZ_PREPARATION_READY_COMPRESSED,
			       SWAPZ_PREPARATION_READY_RAW,
			       SWAPZ_PREPARATION_ERROR,
			       SWAPZ_PREPARATION_RAW_SELECTED,
			       SWAPZ_PREPARATION_CANCELLED,
			       SWAPZ_PREPARATION_CONSUMED };
	atomic_t state;
	unsigned int index;

	for (index = 0; index < sizeof(states) / sizeof(states[0]); ++index) {
		atomic_init(&state.value, states[index]);
		CHECK(swapz_preparation_publish_codec_result(&state, -EIO) ==
		      states[index]);
		CHECK(swapz_preparation_read_state(&state) == states[index]);
		CHECK(swapz_preparation_publish_codec_result(&state, 2048) ==
		      states[index]);
		CHECK(swapz_preparation_read_state(&state) == states[index]);
	}
	atomic_init(&state.value, SWAPZ_PREPARATION_PREPARING);
	CHECK(swapz_preparation_publish_result(&state,
					      SWAPZ_PREPARATION_ERROR) ==
	      SWAPZ_PREPARATION_ERROR);
	CHECK(swapz_preparation_read_state(&state) == SWAPZ_PREPARATION_PREPARING);
	return 0;
}

#define PUBLICATION_RACE_ITERATIONS 8192U

struct publication_race_context {
	atomic_t state;
	pthread_barrier_t start;
	pthread_barrier_t finish;
	_Atomic int failed;
	int codec_result;
	int preparation_error;
	uint64_t payload;
};

static uint64_t publication_payload(unsigned int iteration)
{
	return 0x9e3779b97f4a7c15ULL ^
	       ((uint64_t)iteration * 0xbf58476d1ce4e5b9ULL);
}

static void publication_race_fail(struct publication_race_context *context,
				  const char *phase, unsigned int iteration,
				  int observed_state)
{
	if (!atomic_exchange_explicit(&context->failed, 1,
				      memory_order_relaxed))
		fprintf(stderr, "codec-publication %s: iteration=%u codec=%d "
			"observed_state=%d expected_terminal=%d\n",
			phase, iteration, context->codec_result, observed_state,
			swapz_preparation_codec_result_state(context->codec_result));
}

static void *publish_codec_results(void *opaque)
{
	struct publication_race_context *context = opaque;
	unsigned int iteration;

	for (iteration = 1; iteration <= PUBLICATION_RACE_ITERATIONS; ++iteration) {
		int observed;

		(void)pthread_barrier_wait(&context->start);
		if (context->codec_result < 0)
			context->preparation_error = context->codec_result;
		else
			context->payload = publication_payload(iteration);
		observed = swapz_preparation_publish_codec_result(
			&context->state, context->codec_result);
		if (observed != SWAPZ_PREPARATION_PREPARING &&
		    observed != SWAPZ_PREPARATION_RAW_SELECTED)
			publication_race_fail(context, "producer-or-consumer", iteration, observed);
		(void)pthread_barrier_wait(&context->finish);
	}
	return NULL;
}

static void *select_raw_concurrently(void *opaque)
{
	struct publication_race_context *context = opaque;
	unsigned int iteration;

	for (iteration = 1; iteration <= PUBLICATION_RACE_ITERATIONS; ++iteration) {
		int observed;

		(void)pthread_barrier_wait(&context->start);
		observed = swapz_preparation_select_raw(&context->state);
		switch (observed) {
		case SWAPZ_PREPARATION_READY_COMPRESSED:
			if (context->codec_result <= 0 ||
			    context->payload != publication_payload(iteration))
				publication_race_fail(context, "producer-or-consumer", iteration, observed);
			break;
		case SWAPZ_PREPARATION_READY_RAW:
			if (context->codec_result != 0 ||
			    context->payload != publication_payload(iteration))
				publication_race_fail(context, "producer-or-consumer", iteration, observed);
			break;
		case SWAPZ_PREPARATION_ERROR:
			if (context->codec_result >= 0 ||
			    context->preparation_error != context->codec_result)
				publication_race_fail(context, "producer-or-consumer", iteration, observed);
			break;
		case SWAPZ_PREPARATION_RAW_SELECTED:
			break;
		default:
			publication_race_fail(context, "producer-or-consumer", iteration, observed);
			break;
		}
		(void)pthread_barrier_wait(&context->finish);
	}
	return NULL;
}

static int test_concurrent_codec_publication_preserves_payload_visibility(void)
{
	struct publication_race_context context;
	pthread_t producer, consumer;
	unsigned int iteration;

	atomic_init(&context.state.value, SWAPZ_PREPARATION_PREPARING);
	atomic_init(&context.failed, 0);
	CHECK(pthread_barrier_init(&context.start, NULL, 3) == 0);
	CHECK(pthread_barrier_init(&context.finish, NULL, 3) == 0);
	CHECK(pthread_create(&producer, NULL, publish_codec_results, &context) == 0);
	CHECK(pthread_create(&consumer, NULL, select_raw_concurrently, &context) == 0);

	for (iteration = 1; iteration <= PUBLICATION_RACE_ITERATIONS; ++iteration) {
		int final_state;

		atomic_store_explicit(&context.state.value,
				      SWAPZ_PREPARATION_PREPARING,
				      memory_order_relaxed);
		context.codec_result = iteration % 3U == 0U ? -EIO :
			(iteration % 3U == 1U ? 0 : 2048);
		context.preparation_error = 0;
		context.payload = 0;
		(void)pthread_barrier_wait(&context.start);
		(void)pthread_barrier_wait(&context.finish);

		final_state = swapz_preparation_read_state(&context.state);
		if (final_state == SWAPZ_PREPARATION_PREPARING ||
		    final_state == SWAPZ_PREPARATION_EMPTY)
			publication_race_fail(&context, "drain-final", iteration, final_state);
		if (context.codec_result < 0 &&
		    final_state != SWAPZ_PREPARATION_ERROR &&
		    final_state != SWAPZ_PREPARATION_RAW_SELECTED)
			publication_race_fail(&context, "drain-final", iteration, final_state);
		if (context.codec_result == 0 &&
		    final_state != SWAPZ_PREPARATION_READY_RAW &&
		    final_state != SWAPZ_PREPARATION_RAW_SELECTED)
			publication_race_fail(&context, "drain-final", iteration, final_state);
		if (context.codec_result > 0 &&
		    final_state != SWAPZ_PREPARATION_READY_COMPRESSED &&
		    final_state != SWAPZ_PREPARATION_RAW_SELECTED)
			publication_race_fail(&context, "drain-final", iteration, final_state);
	}
	CHECK(pthread_join(producer, NULL) == 0);
	CHECK(pthread_join(consumer, NULL) == 0);
	CHECK(pthread_barrier_destroy(&context.start) == 0);
	CHECK(pthread_barrier_destroy(&context.finish) == 0);
	CHECK(!atomic_load_explicit(&context.failed, memory_order_relaxed));
	return 0;
}

int main(void)
{
	CHECK(!test_codec_result_classification());
	CHECK(!test_codec_success_publication());
	CHECK(!test_codec_error_publication_wins());
	CHECK(!test_raw_selection_wins_late_codec_error());
	CHECK(!test_terminal_states_reject_republication());
	CHECK(!test_concurrent_codec_publication_preserves_payload_visibility());
	puts("SWAPZ_PREPARATION_CODEC_RESULT_PASS=6");
	return 0;
}
