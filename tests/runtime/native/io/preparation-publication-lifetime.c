// SPDX-License-Identifier: GPL-2.0-only
/* Deterministic producer/ordered-owner interleavings of the production helpers.
 * This models ownership and ACK gates; it is not a Linux memory-model proof. */
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

static s64 atomic64_read(atomic64_t *value)
{
	return atomic_load_explicit(&value->value, memory_order_relaxed);
}

static s64 atomic64_cmpxchg(atomic64_t *value, s64 old, s64 replacement)
{
	atomic_compare_exchange_strong_explicit(&value->value, &old, replacement,
		memory_order_seq_cst, memory_order_relaxed);
	return old;
}

/* TSan cannot instrument standalone fences; use the equivalent release RMW. */
#if defined(__SANITIZE_THREAD__)
#define smp_mb__before_atomic() ((void)0)
#define SLOT_RELEASE_ORDER memory_order_release
#else
#define smp_mb__before_atomic() atomic_thread_fence(memory_order_seq_cst)
#define SLOT_RELEASE_ORDER memory_order_relaxed
#endif
static void atomic64_or(s64 bits, atomic64_t *value)
{
	atomic_fetch_or_explicit(&value->value, bits, SLOT_RELEASE_ORDER);
}

#define __ffs64(value) ((unsigned int)__builtin_ctzll(value))
#include "preparation-slots.h"

#define CHECK(condition) do { if (!(condition)) { \
	fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #condition); \
	return 1; \
} } while (0)

/* A failed assertion must not strand the other thread at a test barrier. */
#define RACE_CHECK(condition) do { if (!(condition)) { \
	fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #condition); \
	atomic_fetch_add(&handoff.protocol_failures, 1); \
} } while (0)

#define ROUNDS 2048U
#define RAW_SNAPSHOT_BYTES 64U

struct prepared_handoff {
	atomic_t state;
	atomic64_t free_mask;
	_Atomic unsigned int references;
	_Atomic int result_ready;
	_Atomic int terminal_error;
	_Atomic unsigned int protocol_failures;
	pthread_barrier_t snapshot_ready;
	pthread_barrier_t allow_result;
	pthread_barrier_t result_published;
	pthread_barrier_t allow_producer_release;
	pthread_barrier_t slot_recycled;
	pthread_barrier_t next_iteration;
	int codec_result;
	int length;
	int previous_state;
	unsigned char raw_bytes[RAW_SNAPSHOT_BYTES];
	unsigned char compressed_bytes[RAW_SNAPSHOT_BYTES];
};

static void release_reference(struct prepared_handoff *handoff)
{
	if (atomic_fetch_sub_explicit(&handoff->references, 1,
					  memory_order_acq_rel) != 1)
		return;
	atomic_store_explicit(&handoff->state.value, SWAPZ_PREPARATION_EMPTY,
				      memory_order_relaxed);
	swapz_preparation_release_slot(&handoff->free_mask, 63);
}

static void *prepare_in_background(void *opaque)
{
	struct prepared_handoff *handoff = opaque;
	unsigned int iteration, byte;

	for (iteration = 0; iteration < ROUNDS; ++iteration) {
		int expected_state;

		/* The upper BIO is needed only for this immutable RAW snapshot. */
		for (byte = 0; byte < RAW_SNAPSHOT_BYTES; ++byte)
			handoff->raw_bytes[byte] =
				(unsigned char)(iteration + byte);
		(void)pthread_barrier_wait(&handoff->snapshot_ready);
		/* After the snapshot handoff, touch no per-BIO descriptor. */
		(void)pthread_barrier_wait(&handoff->allow_result);
		handoff->length = handoff->codec_result;
		if (handoff->length > 0)
			for (byte = 0; byte < RAW_SNAPSHOT_BYTES; ++byte)
				handoff->compressed_bytes[byte] =
					(unsigned char)(iteration ^ byte);
		if (handoff->length < 0)
			/* Elect failure before ERROR (or a losing RAW_SELECTED CAS). */
			atomic_store_explicit(&handoff->terminal_error,
					      handoff->length, memory_order_release);
		expected_state = swapz_preparation_publish_codec_result(
			&handoff->state, handoff->length);
		handoff->previous_state = expected_state;
		if (expected_state != SWAPZ_PREPARATION_PREPARING &&
		    expected_state != SWAPZ_PREPARATION_RAW_SELECTED)
			atomic_fetch_add(&handoff->protocol_failures, 1);
		atomic_store_explicit(&handoff->result_ready, 1,
					      memory_order_release);
		(void)pthread_barrier_wait(&handoff->result_published);
		/* Upper completion may run while this producer still owns its slot. */
		(void)pthread_barrier_wait(&handoff->allow_producer_release);
		release_reference(handoff);
		(void)pthread_barrier_wait(&handoff->slot_recycled);
		(void)pthread_barrier_wait(&handoff->next_iteration);
	}
	return NULL;
}

static int test_ordered_ack_and_refcount_lifetime(void)
{
	static const int results[] = { 1024, 0, -EIO, -EINVAL, -EBADMSG, 7 };
	struct prepared_handoff handoff = { 0 };
	pthread_t producer;
	unsigned int iteration;
	unsigned int producer_wins = 0, raw_wins = 0, negative_results = 0;
	int first_acknowledged_status = -1;

	atomic_init(&handoff.free_mask.value, (s64)(1ULL << 63));
	atomic_init(&handoff.state.value, SWAPZ_PREPARATION_EMPTY);
	atomic_init(&handoff.references, 0);
	atomic_init(&handoff.result_ready, 0);
	atomic_init(&handoff.terminal_error, 0);
	atomic_init(&handoff.protocol_failures, 0);
	CHECK(pthread_barrier_init(&handoff.snapshot_ready, NULL, 2) == 0);
	CHECK(pthread_barrier_init(&handoff.allow_result, NULL, 2) == 0);
	CHECK(pthread_barrier_init(&handoff.result_published, NULL, 2) == 0);
	CHECK(pthread_barrier_init(&handoff.allow_producer_release, NULL, 2) == 0);
	CHECK(pthread_barrier_init(&handoff.slot_recycled, NULL, 2) == 0);
	CHECK(pthread_barrier_init(&handoff.next_iteration, NULL, 2) == 0);
	CHECK(pthread_create(&producer, NULL, prepare_in_background, &handoff) == 0);

	for (iteration = 0; iteration < ROUNDS; ++iteration) {
		const int codec_result = results[(iteration / 2U) %
			(sizeof(results) / sizeof(results[0]))];
		const int raw_wins_race = iteration % 2U == 0U;
		unsigned int byte;
		int state, acknowledged_status;

		RACE_CHECK(swapz_preparation_claim_slot(&handoff.free_mask) == 63);
		RACE_CHECK(swapz_preparation_claim_slot(&handoff.free_mask) == -1);
		atomic_store_explicit(&handoff.references, 2, memory_order_relaxed);
		atomic_store_explicit(&handoff.result_ready, 0, memory_order_relaxed);
		atomic_store_explicit(&handoff.terminal_error, 0, memory_order_relaxed);
		atomic_store_explicit(&handoff.state.value,
				      SWAPZ_PREPARATION_PREPARING,
				      memory_order_relaxed);
		handoff.codec_result = codec_result;
		(void)pthread_barrier_wait(&handoff.snapshot_ready);
		if (raw_wins_race) {
			RACE_CHECK(swapz_preparation_select_raw(&handoff.state) ==
			      SWAPZ_PREPARATION_RAW_SELECTED);
			/* Lower I/O can use the snapshot, never mutable codec bytes. */
			for (byte = 0; byte < RAW_SNAPSHOT_BYTES; ++byte)
				RACE_CHECK(handoff.raw_bytes[byte] ==
				      (unsigned char)(iteration + byte));
			/* Lower completion alone cannot authorize an upper ACK. */
			RACE_CHECK(!atomic_load_explicit(&handoff.result_ready,
						    memory_order_acquire));
			raw_wins++;
		}
		(void)pthread_barrier_wait(&handoff.allow_result);
		(void)pthread_barrier_wait(&handoff.result_published);
		RACE_CHECK(atomic_load_explicit(&handoff.result_ready,
						   memory_order_acquire));
		state = swapz_preparation_select_raw(&handoff.state);
		if (raw_wins_race) {
			RACE_CHECK(state == SWAPZ_PREPARATION_RAW_SELECTED);
			RACE_CHECK(handoff.previous_state == SWAPZ_PREPARATION_RAW_SELECTED);
		} else {
			RACE_CHECK(handoff.previous_state == SWAPZ_PREPARATION_PREPARING);
			RACE_CHECK(state == swapz_preparation_codec_result_state(codec_result));
			producer_wins++;
		}
		/* Publication and result_ready both precede reading exact errno. */
		if (codec_result < 0) {
			RACE_CHECK(handoff.length == codec_result);
			RACE_CHECK(atomic_load_explicit(&handoff.terminal_error,
							   memory_order_acquire) == codec_result);
			acknowledged_status = codec_result;
			negative_results++;
		} else {
			RACE_CHECK(handoff.length == codec_result);
			acknowledged_status = 0;
		}
		/* The first successful RAW ACK predates the later codec faults. */
		if (iteration == 0)
			first_acknowledged_status = acknowledged_status;
		if (codec_result < 0)
			RACE_CHECK(first_acknowledged_status == 0);
		/* The upper BIO can finish, but the producer still owns the page. */
		RACE_CHECK(atomic_load(&handoff.references) == 2);
		release_reference(&handoff);
		RACE_CHECK(atomic_load(&handoff.references) == 1);
		RACE_CHECK(atomic64_read(&handoff.free_mask) == 0);
		(void)pthread_barrier_wait(&handoff.allow_producer_release);
		(void)pthread_barrier_wait(&handoff.slot_recycled);
		RACE_CHECK(atomic_load(&handoff.references) == 0);
		RACE_CHECK((uint64_t)atomic64_read(&handoff.free_mask) == (1ULL << 63));
		RACE_CHECK(swapz_preparation_read_state(&handoff.state) ==
		      SWAPZ_PREPARATION_EMPTY);
		(void)pthread_barrier_wait(&handoff.next_iteration);
	}
	CHECK(pthread_join(producer, NULL) == 0);
	CHECK(pthread_barrier_destroy(&handoff.snapshot_ready) == 0);
	CHECK(pthread_barrier_destroy(&handoff.allow_result) == 0);
	CHECK(pthread_barrier_destroy(&handoff.result_published) == 0);
	CHECK(pthread_barrier_destroy(&handoff.allow_producer_release) == 0);
	CHECK(pthread_barrier_destroy(&handoff.slot_recycled) == 0);
	CHECK(pthread_barrier_destroy(&handoff.next_iteration) == 0);
	CHECK(atomic_load(&handoff.protocol_failures) == 0);
	CHECK(producer_wins == ROUNDS / 2U);
	CHECK(raw_wins == ROUNDS / 2U);
	CHECK(negative_results > 0);
	return 0;
}

static int test_drain_wake_gate_and_terminal_ack(void)
{
	int acknowledged_status = 0;
	atomic_t terminal_error;

	atomic_init(&terminal_error.value, 0);
	CHECK(swapz_preparation_owner_wake_allowed(1));
	CHECK(!swapz_preparation_owner_wake_allowed(0));
	/* A prior success remains acknowledged after an unrelated later fault. */
	atomic_store_explicit(&terminal_error.value, -EIO, memory_order_release);
	CHECK(acknowledged_status == 0);
	/* A still-owned BIO must instead see the terminal error before ACK. */
	if (swapz_preparation_read_state(&terminal_error))
		acknowledged_status = swapz_preparation_read_state(&terminal_error);
	CHECK(acknowledged_status == -EIO);
	return 0;
}

int main(void)
{
	CHECK(!test_ordered_ack_and_refcount_lifetime());
	CHECK(!test_drain_wake_gate_and_terminal_ack());
	puts("SWAPZ_PREPARATION_PUBLICATION_LIFETIME_PASS=2");
	return 0;
}
