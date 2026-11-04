// SPDX-License-Identifier: GPL-2.0-only
/* Deterministic producer/ordered-owner interleavings of the production helpers.
 * This models ownership and ACK gates; it is not a Linux memory-model proof. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <pthread.h>
#include <sched.h>
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
		/*
		 * Do not add a post-publication barrier here: the consumer below must
		 * acquire result_ready itself before it reads length or terminal_error.
		 */
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

	atomic_init(&handoff.free_mask.value, (s64)(1ULL << 63));
	atomic_init(&handoff.state.value, SWAPZ_PREPARATION_EMPTY);
	atomic_init(&handoff.references, 0);
	atomic_init(&handoff.result_ready, 0);
	atomic_init(&handoff.terminal_error, 0);
	atomic_init(&handoff.protocol_failures, 0);
	CHECK(pthread_barrier_init(&handoff.snapshot_ready, NULL, 2) == 0);
	CHECK(pthread_barrier_init(&handoff.allow_result, NULL, 2) == 0);
	CHECK(pthread_barrier_init(&handoff.allow_producer_release, NULL, 2) == 0);
	CHECK(pthread_barrier_init(&handoff.slot_recycled, NULL, 2) == 0);
	CHECK(pthread_barrier_init(&handoff.next_iteration, NULL, 2) == 0);
	CHECK(pthread_create(&producer, NULL, prepare_in_background, &handoff) == 0);

	for (iteration = 0; iteration < ROUNDS; ++iteration) {
		const int codec_result = results[(iteration / 2U) %
			(sizeof(results) / sizeof(results[0]))];
		const int raw_wins_race = iteration % 2U == 0U;
		unsigned int byte;
		int state;

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
		while (!atomic_load_explicit(&handoff.result_ready,
						     memory_order_acquire))
			sched_yield();
		/*
		 * The acquire above, not a pthread barrier, publishes the producer's
		 * exact result for a RAW_SELECTED ACK decision.
		 */
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
			negative_results++;
		} else {
			RACE_CHECK(handoff.length == codec_result);
		}
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
	CHECK(pthread_barrier_destroy(&handoff.allow_producer_release) == 0);
	CHECK(pthread_barrier_destroy(&handoff.slot_recycled) == 0);
	CHECK(pthread_barrier_destroy(&handoff.next_iteration) == 0);
	CHECK(atomic_load(&handoff.protocol_failures) == 0);
	CHECK(producer_wins == ROUNDS / 2U);
	CHECK(raw_wins == ROUNDS / 2U);
	CHECK(negative_results > 0);
	return 0;
}

static int test_closed_admission_suppresses_owner_wake(void)
{
	CHECK(swapz_preparation_owner_wake_allowed(1));
	CHECK(!swapz_preparation_owner_wake_allowed(0));
	return 0;
}

/* Submitter work has one prepared-page reference, plus a separate lane lease.
 * The ordered owner may finish the BIO after the active release store, but
 * drain must still join the task's final scratch-lane release. */
#define SUBMITTER_ROUNDS 256U
struct submitter_handoff {
	atomic_t state;
	atomic_t active;
	atomic_t terminal_error;
	atomic64_t page_mask;
	atomic64_t lane_mask;
	pthread_barrier_t start;
	pthread_barrier_t owner_observed;
	pthread_barrier_t return_lane;
	pthread_barrier_t lane_returned;
	pthread_barrier_t next_iteration;
	_Atomic int payload_ready;
	_Atomic int allow_release;
	_Atomic unsigned int failures;
	int codec_result;
	unsigned int payload;
};

static void *prepare_in_submitter(void *opaque)
{
	struct submitter_handoff *handoff = opaque;
	unsigned int iteration;

	for (iteration = 0; iteration < SUBMITTER_ROUNDS; ++iteration) {
		int old_state;

		(void)pthread_barrier_wait(&handoff->start);
		handoff->payload = iteration ^ 0xa5a5U;
		if (handoff->codec_result < 0)
			atomic_store_explicit(&handoff->terminal_error.value,
					      handoff->codec_result, memory_order_release);
		old_state = swapz_preparation_publish_codec_result(
			&handoff->state, handoff->codec_result);
		if (old_state != SWAPZ_PREPARATION_PREPARING)
			atomic_fetch_add(&handoff->failures, 1);
		/*
		 * This relaxed flag is scheduling only. It deliberately does not
		 * publish payload: the ordered owner must acquire active == 0.
		 */
		atomic_store_explicit(&handoff->payload_ready, 1,
					      memory_order_relaxed);
		while (!atomic_load_explicit(&handoff->allow_release,
						     memory_order_relaxed))
			sched_yield();
		/* All modeled descriptor and prepared-page accesses precede this release. */
		atomic_store_explicit(&handoff->active.value, 0,
					      memory_order_release);
		/*
		 * Wait only after releasing the active gate. The owner reads payload
		 * before reaching this barrier, so the barrier cannot mask the acquire.
		 */
		(void)pthread_barrier_wait(&handoff->owner_observed);
		/* The owner can end the BIO; drain still sees a leased lane. */
		(void)pthread_barrier_wait(&handoff->return_lane);
		swapz_preparation_release_slot(&handoff->lane_mask, 0);
		(void)pthread_barrier_wait(&handoff->lane_returned);
		(void)pthread_barrier_wait(&handoff->next_iteration);
	}
	return NULL;
}

static int test_submitter_active_gate_and_lane_drain(void)
{
	struct submitter_handoff handoff = { 0 };
	pthread_t submitter;
	unsigned int iteration, page_peak = 0, lane_peak = 0;
	unsigned int page_current = 0, lane_current = 0;

	atomic_init(&handoff.state.value, SWAPZ_PREPARATION_EMPTY);
	atomic_init(&handoff.active.value, 0);
	atomic_init(&handoff.terminal_error.value, 0);
	atomic_init(&handoff.page_mask.value, (s64)(1ULL << 63));
	atomic_init(&handoff.lane_mask.value, 1);
	atomic_init(&handoff.payload_ready, 0);
	atomic_init(&handoff.allow_release, 0);
	atomic_init(&handoff.failures, 0);
	CHECK(pthread_barrier_init(&handoff.start, NULL, 2) == 0);
	CHECK(pthread_barrier_init(&handoff.owner_observed, NULL, 2) == 0);
	CHECK(pthread_barrier_init(&handoff.return_lane, NULL, 2) == 0);
	CHECK(pthread_barrier_init(&handoff.lane_returned, NULL, 2) == 0);
	CHECK(pthread_barrier_init(&handoff.next_iteration, NULL, 2) == 0);
	CHECK(pthread_create(&submitter, NULL, prepare_in_submitter, &handoff) == 0);
	for (iteration = 0; iteration < SUBMITTER_ROUNDS; ++iteration) {
		const int codec_result = iteration % 3U == 0U ? 300 :
			(iteration % 3U == 1U ? 0 : -EIO);
		const int closed_admission = iteration % 2U == 0U;
		int final_state;

		CHECK(swapz_preparation_claim_slot(&handoff.page_mask) == 63);
		CHECK(swapz_preparation_claim_slot(&handoff.lane_mask) == 0);
		page_current++;
		lane_current++;
		if (page_current > page_peak)
			page_peak = page_current;
		if (lane_current > lane_peak)
			lane_peak = lane_current;
		atomic_store_explicit(&handoff.active.value, 1, memory_order_relaxed);
		atomic_store_explicit(&handoff.state.value, SWAPZ_PREPARATION_PREPARING,
					      memory_order_relaxed);
		atomic_store_explicit(&handoff.terminal_error.value, 0,
					      memory_order_relaxed);
		atomic_store_explicit(&handoff.payload_ready, 0,
					      memory_order_relaxed);
		atomic_store_explicit(&handoff.allow_release, 0,
					      memory_order_relaxed);
		handoff.codec_result = codec_result;
		(void)pthread_barrier_wait(&handoff.start);
		while (!atomic_load_explicit(&handoff.payload_ready,
						     memory_order_relaxed))
			sched_yield();
		/* A terminal state cannot bypass a still-active submitter descriptor. */
		CHECK(atomic_load_explicit(&handoff.active.value,
						memory_order_relaxed) == 1);
		if (closed_admission)
			CHECK(!swapz_preparation_owner_wake_allowed(0));
		atomic_store_explicit(&handoff.allow_release, 1,
					      memory_order_relaxed);
		while (atomic_load_explicit(&handoff.active.value,
						    memory_order_acquire) != 0)
			sched_yield();
		/*
		 * Read ordinary payload before any state acquire or pthread barrier:
		 * visibility therefore comes from the submitter-active release/acquire.
		 */
		CHECK(handoff.payload == (iteration ^ 0xa5a5U));
		final_state = swapz_preparation_read_state(&handoff.state);
		CHECK(final_state == swapz_preparation_codec_result_state(codec_result));
		if (codec_result < 0)
			CHECK(swapz_preparation_read_state(&handoff.terminal_error) ==
			      codec_result);
		(void)pthread_barrier_wait(&handoff.owner_observed);
		/* BIO completion returns the only prepared-page reference. */
		atomic_store_explicit(&handoff.state.value, SWAPZ_PREPARATION_EMPTY,
					      memory_order_relaxed);
		swapz_preparation_release_slot(&handoff.page_mask, 63);
		page_current--;
		CHECK((uint64_t)atomic64_read(&handoff.page_mask) == (1ULL << 63));
		CHECK(atomic64_read(&handoff.lane_mask) == 0);
		/* No completed drain is possible until the submitter returns its lane. */
		(void)pthread_barrier_wait(&handoff.return_lane);
		(void)pthread_barrier_wait(&handoff.lane_returned);
		lane_current--;
		CHECK(atomic64_read(&handoff.lane_mask) == 1);
		(void)pthread_barrier_wait(&handoff.next_iteration);
	}
	CHECK(pthread_join(submitter, NULL) == 0);
	CHECK(pthread_barrier_destroy(&handoff.start) == 0);
	CHECK(pthread_barrier_destroy(&handoff.owner_observed) == 0);
	CHECK(pthread_barrier_destroy(&handoff.return_lane) == 0);
	CHECK(pthread_barrier_destroy(&handoff.lane_returned) == 0);
	CHECK(pthread_barrier_destroy(&handoff.next_iteration) == 0);
	CHECK(atomic_load(&handoff.failures) == 0);
	CHECK(page_current == 0 && lane_current == 0);
	CHECK(page_peak == 1 && lane_peak == 1);
	return 0;
}

int main(void)
{
	CHECK(!test_ordered_ack_and_refcount_lifetime());
	CHECK(!test_closed_admission_suppresses_owner_wake());
	CHECK(!test_submitter_active_gate_and_lane_drain());
	puts("SWAPZ_PREPARATION_PUBLICATION_LIFETIME_PASS=3");
	return 0;
}
