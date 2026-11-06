// SPDX-License-Identifier: GPL-2.0-only
/* Bounded C11 producer/ordered-owner lifetime model of production helpers.
 * READY/ERROR payloads require the state acquire; RAW_SELECTED completion
 * instead supplies the late-result acquire. Refcount acq_rel RMWs establish
 * the final owner, but only final-put's EMPTY store and release_slot's fence/OR
 * authorize the next claimant's acquire-CAS slot reuse. The ordered drain's
 * lane lease is modeled separately from BIO reference lifetime. These test
 * executions are NOT an LKMM exhaustive proof or loaded kernel coverage. */
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
	fprintf(stderr, "prepared-lifetime iteration=%u codec=%d state=%d " \
		"refs=%u free_mask=0x%llx: %s:%d: %s\n", \
		iteration, codec_result, state, \
		atomic_load_explicit(&handoff.references, memory_order_relaxed), \
		(unsigned long long)atomic64_read(&handoff.free_mask), \
		__FILE__, __LINE__, #condition); \
	atomic_fetch_add(&handoff.protocol_failures, 1); \
} } while (0)

#define ROUNDS 2048U
#define RAW_SNAPSHOT_BYTES 64U

struct prepared_handoff {
	atomic_t state;
	atomic64_t free_mask;
	_Atomic unsigned int references;
	_Atomic int result_ready;
	/* Relaxed scheduling only: do not publish the producer payload through it. */
	_Atomic int allow_result_completion;
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
		/*
		 * Keep modeled completion unpublished until the producer-won consumer
		 * has acquired the actual READY/ERROR state and inspected its payload.
		 * RAW_SELECTED cannot change state and instead waits for completion.
		 * This gate is relaxed scheduling, not a second publication edge.
		 */
		if (expected_state == SWAPZ_PREPARATION_PREPARING)
			while (!atomic_load_explicit(
				       &handoff->allow_result_completion,
				       memory_order_relaxed))
				sched_yield();
		atomic_store_explicit(&handoff->result_ready, 1,
					      memory_order_release);
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
	atomic_init(&handoff.allow_result_completion, 0);
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
		int state = SWAPZ_PREPARATION_EMPTY;

		RACE_CHECK(swapz_preparation_claim_slot(&handoff.free_mask) == 63);
		RACE_CHECK(swapz_preparation_claim_slot(&handoff.free_mask) == -1);
		atomic_store_explicit(&handoff.references, 2, memory_order_relaxed);
		atomic_store_explicit(&handoff.result_ready, 0, memory_order_relaxed);
		atomic_store_explicit(&handoff.allow_result_completion, 0,
				      memory_order_relaxed);
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
		if (raw_wins_race) {
			/*
			 * RAW_SELECTED does not transition to READY or ERROR. Its late
			 * result is published by the modeled producer completion.
			 */
			while (!atomic_load_explicit(&handoff.result_ready,
						     memory_order_acquire))
				sched_yield();
			state = swapz_preparation_select_raw(&handoff.state);
			RACE_CHECK(state == SWAPZ_PREPARATION_RAW_SELECTED);
			RACE_CHECK(handoff.previous_state == SWAPZ_PREPARATION_RAW_SELECTED);
		} else {
			/*
			 * No result_ready acquire or pthread barrier before reading
			 * length, errno and compressed bytes: these must be visible
			 * through the real production READY/ERROR state acquire.
			 */
			do {
				state = swapz_preparation_read_state(&handoff.state);
				if (state == SWAPZ_PREPARATION_PREPARING)
					sched_yield();
			} while (state == SWAPZ_PREPARATION_PREPARING);
			RACE_CHECK(state == swapz_preparation_codec_result_state(codec_result));
			RACE_CHECK(handoff.length == codec_result);
			if (codec_result < 0)
				RACE_CHECK(atomic_load_explicit(&handoff.terminal_error,
							       memory_order_relaxed) == codec_result);
			if (codec_result > 0)
				for (byte = 0; byte < RAW_SNAPSHOT_BYTES; ++byte)
					RACE_CHECK(handoff.compressed_bytes[byte] ==
					      (unsigned char)(iteration ^ byte));
			/* The producer must still be parked before modeled completion. */
			RACE_CHECK(!atomic_load_explicit(&handoff.result_ready,
							memory_order_relaxed));
			atomic_store_explicit(&handoff.allow_result_completion, 1,
					      memory_order_relaxed);
			while (!atomic_load_explicit(&handoff.result_ready,
						     memory_order_acquire))
				sched_yield();
			/* previous_state was written after publication, not before it. */
			RACE_CHECK(handoff.previous_state == SWAPZ_PREPARATION_PREPARING);
			producer_wins++;
		}
		/* RAW_SELECTED uses result_ready; READY/ERROR was checked before it. */
		if (raw_wins_race) {
			RACE_CHECK(handoff.length == codec_result);
			if (codec_result < 0)
				RACE_CHECK(atomic_load_explicit(&handoff.terminal_error,
							       memory_order_relaxed) == codec_result);
		}
		if (codec_result < 0)
			negative_results++;
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

/*
 * A background preparer may finish first and drop its own reference while the
 * ordered owner still needs the prepared bytes. Observing the producer's relaxed
 * refcount drop proves ownership order only; payload visibility comes from the
 * terminal state acquire. The final consumer release returns slot 63.
 */
#define EARLY_RELEASE_ROUNDS 512U
struct early_producer_release {
	atomic_t state;
	atomic64_t free_mask;
	_Atomic unsigned int references;
	_Atomic unsigned int failures;
	pthread_barrier_t start;
	pthread_barrier_t end;
	int codec_result;
	int length;
	unsigned char payload[RAW_SNAPSHOT_BYTES];
};

static void *finish_preparation_before_consumer(void *opaque)
{
	struct early_producer_release *handoff = opaque;
	unsigned int iteration, byte;

	for (iteration = 0; iteration < EARLY_RELEASE_ROUNDS; ++iteration) {
		(void)pthread_barrier_wait(&handoff->start);
		handoff->length = handoff->codec_result;
		if (handoff->length > 0)
			for (byte = 0; byte < RAW_SNAPSHOT_BYTES; ++byte)
				handoff->payload[byte] = (unsigned char)(iteration ^ byte);
		if (swapz_preparation_publish_codec_result(
			    &handoff->state, handoff->length) !=
		    SWAPZ_PREPARATION_PREPARING)
			atomic_fetch_add(&handoff->failures, 1);
		if (atomic_fetch_sub_explicit(&handoff->references, 1,
					      memory_order_acq_rel) != 2)
			atomic_fetch_add(&handoff->failures, 1);
		(void)pthread_barrier_wait(&handoff->end);
	}
	return NULL;
}

static int test_producer_releases_first_consumer_reclaims_last(void)
{
	static const int results[] = { 1024, 0, -EIO };
	struct early_producer_release handoff = { 0 };
	pthread_t producer;
	unsigned int iteration, byte;

	atomic_init(&handoff.state.value, SWAPZ_PREPARATION_EMPTY);
	atomic_init(&handoff.free_mask.value, (s64)(1ULL << 63));
	atomic_init(&handoff.references, 0);
	atomic_init(&handoff.failures, 0);
	CHECK(pthread_barrier_init(&handoff.start, NULL, 2) == 0);
	CHECK(pthread_barrier_init(&handoff.end, NULL, 2) == 0);
	CHECK(pthread_create(&producer, NULL,
			     finish_preparation_before_consumer, &handoff) == 0);

	for (iteration = 0; iteration < EARLY_RELEASE_ROUNDS; ++iteration) {
		CHECK(swapz_preparation_claim_slot(&handoff.free_mask) == 63);
		atomic_store_explicit(&handoff.references, 2, memory_order_relaxed);
		atomic_store_explicit(&handoff.state.value,
				      SWAPZ_PREPARATION_PREPARING,
				      memory_order_relaxed);
		handoff.codec_result =
			results[iteration % (sizeof(results) / sizeof(results[0]))];
		handoff.length = 0;
		(void)pthread_barrier_wait(&handoff.start);
		/* Observe the producer's actual reference drop. A separate relaxed
		 * scheduling flag cannot establish the value of this atomic or publish
		 * payload bytes; the state acquire below remains the publication edge. */
		while (atomic_load_explicit(&handoff.references,
						    memory_order_relaxed) != 1)
			sched_yield();
		/* The refcount observation does not order a different atomic. Poll the
		 * production acquire until the producer's terminal publication is seen. */
		for (;;) {
			int final_state = swapz_preparation_read_state(&handoff.state);

			if (final_state == SWAPZ_PREPARATION_PREPARING) {
				sched_yield();
				continue;
			}
			CHECK(final_state ==
			      swapz_preparation_codec_result_state(handoff.codec_result));
			break;
		}
		/* These are the first synchronizing producer-payload observations. */
		CHECK(handoff.length == handoff.codec_result);
		if (handoff.codec_result > 0)
			for (byte = 0; byte < RAW_SNAPSHOT_BYTES; ++byte)
				CHECK(handoff.payload[byte] ==
				      (unsigned char)(iteration ^ byte));
		CHECK(atomic64_read(&handoff.free_mask) == 0);
		CHECK(swapz_preparation_claim_slot(&handoff.free_mask) == -1);
		CHECK(atomic_fetch_sub_explicit(&handoff.references, 1,
						memory_order_acq_rel) == 1);
		CHECK(atomic_load_explicit(&handoff.references,
						   memory_order_relaxed) == 0);
		atomic_store_explicit(&handoff.state.value, SWAPZ_PREPARATION_EMPTY,
				      memory_order_relaxed);
		swapz_preparation_release_slot(&handoff.free_mask, 63);
		CHECK((uint64_t)atomic64_read(&handoff.free_mask) == (1ULL << 63));
		(void)pthread_barrier_wait(&handoff.end);
	}
	CHECK(pthread_join(producer, NULL) == 0);
	CHECK(pthread_barrier_destroy(&handoff.start) == 0);
	CHECK(pthread_barrier_destroy(&handoff.end) == 0);
	CHECK(atomic_load_explicit(&handoff.failures, memory_order_relaxed) == 0);
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



/*
 * Force terminal failure either before or after a worker terminal publication.
 * The worker holds a prepared-page reference until its last access, while the
 * ordered BIO owner holds the other. Drain joins both completion paths; only
 * final-put may clear the state and return slot 63. The next claimant must not
 * see an old terminal state or bytes from a prior failed preparation.
 *
 * READY is charged before publication, matching production reservoir
 * accounting. A terminal owner retires unconsumed READY to CONSUMED and drops
 * that charge exactly once; an early PREPARING cancellation becomes CANCELLED,
 * and a later non-error worker result rolls its speculative charge back when
 * publication loses. Scheduling barriers force order but do not replace the
 * state/result release-acquire edges. This is a finite C11 model, not LKMM.
 */
#define CANCELLATION_ROUNDS 384U
struct cancellation_lifetime_handoff {
	atomic_t state;
	atomic64_t free_mask;
	_Atomic unsigned int references;
	_Atomic unsigned int result_attempts;
	_Atomic unsigned int terminal_publications;
	_Atomic unsigned int cancellation_claims;
	_Atomic unsigned int final_puts;
	_Atomic unsigned int owner_done;
	_Atomic unsigned int worker_done;
	_Atomic unsigned int drain_done;
	_Atomic unsigned int failures;
	_Atomic int result_ready;
	_Atomic int previous_state;
	_Atomic int ready_charges;
	pthread_barrier_t start;
	pthread_barrier_t snapshot_taken;
	pthread_barrier_t allow_result;
	pthread_barrier_t allow_worker_put;
	pthread_barrier_t recycled;
	int codec_result;
	int result_length;
	unsigned int generation;
	unsigned int prepared_generation;
	unsigned char raw_snapshot[RAW_SNAPSHOT_BYTES];
	unsigned char prepared_bytes[RAW_SNAPSHOT_BYTES];
};

static int cancellation_precedes_result(unsigned int iteration)
{
	return iteration % 6U >= 3U;
}

static int cancellation_worker_puts_first(unsigned int iteration)
{
	const unsigned int case_index = iteration % 6U;

	return case_index == 1U || case_index == 2U;
}

static const char *cancellation_terminal_owner(unsigned int iteration)
{
	return cancellation_precedes_result(iteration) ?
		"ordered-cancel" : "worker-publish";
}

static const char *cancellation_final_owner(unsigned int iteration)
{
	return cancellation_worker_puts_first(iteration) ? "ordered" : "worker";
}

static void cancellation_expect(struct cancellation_lifetime_handoff *handoff,
		unsigned int iteration, const char *phase,
		const char *expected_terminal_owner, const char *expected_final_owner,
		unsigned int refs_before, unsigned int refs_after,
		int actual_transition, const char *condition, int passed)
{
	if (passed)
		return;
	fprintf(stderr, "preparation-lifetime iteration=%u phase=%s "
		"refs=%u->%u slot_mask=0x%llx slot_state=%d ready_charge=%d "
		"expected_terminal_owner=%s expected_final_owner=%s "
		"actual_transition=%d: %s\n", iteration, phase,
		refs_before, refs_after,
		(unsigned long long)atomic64_read(&handoff->free_mask),
		swapz_preparation_read_state(&handoff->state),
		atomic_load_explicit(&handoff->ready_charges, memory_order_relaxed),
		expected_terminal_owner, expected_final_owner,
		actual_transition, condition);
	atomic_fetch_add_explicit(&handoff->failures, 1, memory_order_relaxed);
}

#define CANCELLATION_CHECK(handoff, iteration, phase, terminal_owner, final_owner, \
		refs_before, refs_after, transition, condition) \
	cancellation_expect(handoff, iteration, phase, terminal_owner, final_owner, \
		refs_before, refs_after, transition, #condition, !!(condition))

/* The caller holds a reference; the return value identifies the final owner. */
static unsigned int cancellation_put(struct cancellation_lifetime_handoff *handoff,
		unsigned int iteration, const char *phase,
		const char *terminal_owner, const char *final_owner)
{
	const unsigned int refs_before = atomic_fetch_sub_explicit(
		&handoff->references, 1, memory_order_acq_rel);
	const unsigned int refs_after = refs_before - 1U;

	CANCELLATION_CHECK(handoff, iteration, phase, terminal_owner, final_owner,
		refs_before, refs_after, -1, refs_before == 1U || refs_before == 2U);
	if (refs_before == 1U) {
		atomic_store_explicit(&handoff->state.value,
			SWAPZ_PREPARATION_EMPTY, memory_order_relaxed);
		swapz_preparation_release_slot(&handoff->free_mask, 63);
		atomic_fetch_add_explicit(&handoff->final_puts, 1,
			memory_order_release);
	}
	return refs_before;
}

static void *cancelled_preparation_worker(void *opaque)
{
	struct cancellation_lifetime_handoff *handoff = opaque;
	unsigned int iteration;

	for (iteration = 0; iteration < CANCELLATION_ROUNDS; ++iteration) {
		const int cancel_first = cancellation_precedes_result(iteration);
		const char *terminal_owner = cancellation_terminal_owner(iteration);
		const char *final_owner = cancellation_final_owner(iteration);
		unsigned int byte, refs_before;
		int previous_state;

		(void)pthread_barrier_wait(&handoff->start);
		for (byte = 0; byte < RAW_SNAPSHOT_BYTES; ++byte)
			handoff->raw_snapshot[byte] =
				(unsigned char)(handoff->generation + byte);
		(void)pthread_barrier_wait(&handoff->snapshot_taken);
		(void)pthread_barrier_wait(&handoff->allow_result);

		refs_before = atomic_load_explicit(&handoff->references,
			memory_order_relaxed);
		CANCELLATION_CHECK(handoff, iteration, "worker-before-result",
			terminal_owner, final_owner, refs_before, refs_before, -1,
			refs_before == (cancel_first ? 1U : 2U));

		handoff->result_length = handoff->codec_result;
		if (handoff->result_length > 0) {
			handoff->prepared_generation = handoff->generation;
			for (byte = 0; byte < RAW_SNAPSHOT_BYTES; ++byte)
				handoff->prepared_bytes[byte] =
					(unsigned char)(handoff->generation ^ byte ^ 0x5aU);
		}
		if (handoff->result_length >= 0)
			atomic_fetch_add_explicit(&handoff->ready_charges, 1,
				memory_order_relaxed);

		previous_state = swapz_preparation_publish_codec_result(
			&handoff->state, handoff->result_length);
		atomic_store_explicit(&handoff->previous_state, previous_state,
			memory_order_relaxed);
		if (previous_state == SWAPZ_PREPARATION_PREPARING) {
			atomic_fetch_add_explicit(&handoff->terminal_publications, 1,
				memory_order_relaxed);
		} else if (handoff->result_length >= 0) {
			CANCELLATION_CHECK(handoff, iteration, "worker-ready-rollback",
				terminal_owner, final_owner, refs_before, refs_before,
				previous_state,
				atomic_fetch_sub_explicit(&handoff->ready_charges, 1,
					memory_order_relaxed) == 1);
		}
		atomic_fetch_add_explicit(&handoff->result_attempts, 1,
			memory_order_relaxed);
		CANCELLATION_CHECK(handoff, iteration, "worker-result-cas",
			terminal_owner, final_owner, refs_before, refs_before,
			previous_state, previous_state == (cancel_first ?
				SWAPZ_PREPARATION_CANCELLED :
				SWAPZ_PREPARATION_PREPARING));

		atomic_store_explicit(&handoff->result_ready, 1,
			memory_order_release);
		(void)pthread_barrier_wait(&handoff->allow_worker_put);
		refs_before = cancellation_put(handoff, iteration, "worker-put",
			terminal_owner, final_owner);
		CANCELLATION_CHECK(handoff, iteration, "worker-put-owner",
			terminal_owner, final_owner, refs_before, refs_before - 1U,
			previous_state,
			refs_before == (cancellation_worker_puts_first(iteration) ?
				2U : 1U));
		/* No descriptor, state or payload access is permitted after this put. */
		atomic_store_explicit(&handoff->worker_done, iteration + 1U,
			memory_order_release);
		(void)pthread_barrier_wait(&handoff->recycled);
	}
	return NULL;
}

static void *drain_cancelled_preparations(void *opaque)
{
	struct cancellation_lifetime_handoff *handoff = opaque;
	unsigned int iteration;

	for (iteration = 0; iteration < CANCELLATION_ROUNDS; ++iteration) {
		const unsigned int epoch = iteration + 1U;
		const char *terminal_owner = cancellation_terminal_owner(iteration);
		const char *final_owner = cancellation_final_owner(iteration);
		unsigned int references;

		while (atomic_load_explicit(&handoff->owner_done,
				memory_order_acquire) < epoch ||
		       atomic_load_explicit(&handoff->worker_done,
				memory_order_acquire) < epoch)
			sched_yield();
		references = atomic_load_explicit(&handoff->references,
			memory_order_acquire);
		CANCELLATION_CHECK(handoff, iteration, "drain-joined",
			terminal_owner, final_owner, references, references, -1,
			references == 0 &&
			atomic_load_explicit(&handoff->ready_charges,
				memory_order_relaxed) == 0 &&
			(uint64_t)atomic64_read(&handoff->free_mask) ==
				(1ULL << 63) &&
			swapz_preparation_read_state(&handoff->state) ==
				SWAPZ_PREPARATION_EMPTY);
		atomic_store_explicit(&handoff->drain_done, epoch,
			memory_order_release);
		(void)pthread_barrier_wait(&handoff->recycled);
	}
	return NULL;
}

static int test_cancellation_terminal_drain_and_slot_reuse(void)
{
	static const int results[] = { 320, 0, -EIO, 320, 0, -EINVAL };
	struct cancellation_lifetime_handoff handoff = { 0 };
	pthread_t worker, drainer;
	unsigned int iteration;

	atomic_init(&handoff.state.value, SWAPZ_PREPARATION_EMPTY);
	atomic_init(&handoff.free_mask.value, (s64)(1ULL << 63));
	atomic_init(&handoff.references, 0);
	atomic_init(&handoff.result_attempts, 0);
	atomic_init(&handoff.terminal_publications, 0);
	atomic_init(&handoff.cancellation_claims, 0);
	atomic_init(&handoff.final_puts, 0);
	atomic_init(&handoff.owner_done, 0);
	atomic_init(&handoff.worker_done, 0);
	atomic_init(&handoff.drain_done, 0);
	atomic_init(&handoff.failures, 0);
	atomic_init(&handoff.result_ready, 0);
	atomic_init(&handoff.previous_state, SWAPZ_PREPARATION_EMPTY);
	atomic_init(&handoff.ready_charges, 0);
	CHECK(pthread_barrier_init(&handoff.start, NULL, 2) == 0);
	CHECK(pthread_barrier_init(&handoff.snapshot_taken, NULL, 2) == 0);
	CHECK(pthread_barrier_init(&handoff.allow_result, NULL, 2) == 0);
	CHECK(pthread_barrier_init(&handoff.allow_worker_put, NULL, 2) == 0);
	CHECK(pthread_barrier_init(&handoff.recycled, NULL, 3) == 0);
	CHECK(pthread_create(&worker, NULL, cancelled_preparation_worker,
		&handoff) == 0);
	CHECK(pthread_create(&drainer, NULL, drain_cancelled_preparations,
		&handoff) == 0);

	for (iteration = 0; iteration < CANCELLATION_ROUNDS; ++iteration) {
		const int cancel_first = cancellation_precedes_result(iteration);
		const int worker_first_put =
			cancellation_worker_puts_first(iteration);
		const int codec_result =
			results[iteration % (sizeof(results) / sizeof(results[0]))];
		const char *terminal_owner = cancellation_terminal_owner(iteration);
		const char *final_owner = cancellation_final_owner(iteration);
		unsigned int byte, refs_before;
		int observed_state, retired_state;

		CANCELLATION_CHECK(&handoff, iteration, "claim-old-slot",
			terminal_owner, final_owner, 0, 0, -1,
			swapz_preparation_claim_slot(&handoff.free_mask) == 63);
		CANCELLATION_CHECK(&handoff, iteration, "single-slot",
			terminal_owner, final_owner, 0, 0, -1,
			swapz_preparation_claim_slot(&handoff.free_mask) == -1);
		atomic_store_explicit(&handoff.references, 2, memory_order_relaxed);
		atomic_store_explicit(&handoff.state.value,
			SWAPZ_PREPARATION_PREPARING, memory_order_relaxed);
		atomic_store_explicit(&handoff.result_ready, 0, memory_order_relaxed);
		handoff.codec_result = codec_result;
		handoff.result_length = 0x7fffffff;
		handoff.generation = iteration;
		handoff.prepared_generation = ~0U;

		(void)pthread_barrier_wait(&handoff.start);
		(void)pthread_barrier_wait(&handoff.snapshot_taken);
		for (byte = 0; byte < RAW_SNAPSHOT_BYTES; ++byte)
			CANCELLATION_CHECK(&handoff, iteration, "snapshot",
				terminal_owner, final_owner, 2, 2, -1,
				handoff.raw_snapshot[byte] ==
					(unsigned char)(iteration + byte));

		if (cancel_first) {
			retired_state = swapz_preparation_retire(&handoff.state);
			if (retired_state == SWAPZ_PREPARATION_CANCELLED)
				atomic_fetch_add_explicit(&handoff.cancellation_claims, 1,
					memory_order_relaxed);
			CANCELLATION_CHECK(&handoff, iteration,
				"ordered-cancel-before-result", terminal_owner,
				final_owner, 2, 2, retired_state,
				retired_state == SWAPZ_PREPARATION_CANCELLED &&
				swapz_preparation_read_state(&handoff.state) ==
					SWAPZ_PREPARATION_CANCELLED);
			refs_before = cancellation_put(&handoff, iteration,
				"ordered-put-first", terminal_owner, final_owner);
			CANCELLATION_CHECK(&handoff, iteration, "ordered-put-first",
				terminal_owner, final_owner, refs_before,
				refs_before - 1U, retired_state, refs_before == 2U);
			atomic_store_explicit(&handoff.owner_done, iteration + 1U,
				memory_order_release);
			CANCELLATION_CHECK(&handoff, iteration,
				"cancelled-not-reusable", terminal_owner, final_owner,
				2, 1, retired_state,
				swapz_preparation_claim_slot(&handoff.free_mask) == -1 &&
				atomic_load_explicit(&handoff.drain_done,
					memory_order_relaxed) == iteration);
		}

		(void)pthread_barrier_wait(&handoff.allow_result);
		if (cancel_first) {
			while (!atomic_load_explicit(&handoff.result_ready,
					memory_order_acquire))
				sched_yield();
			observed_state = atomic_load_explicit(&handoff.previous_state,
				memory_order_relaxed);
			CANCELLATION_CHECK(&handoff, iteration,
				"late-result-after-cancel", terminal_owner, final_owner,
				1, 1, observed_state,
				observed_state == SWAPZ_PREPARATION_CANCELLED &&
				swapz_preparation_read_state(&handoff.state) ==
					SWAPZ_PREPARATION_CANCELLED &&
				atomic_load_explicit(&handoff.ready_charges,
					memory_order_relaxed) == 0 &&
				atomic_load_explicit(&handoff.references,
					memory_order_relaxed) == 1 &&
				atomic64_read(&handoff.free_mask) == 0);
		} else {
			do {
				observed_state =
					swapz_preparation_read_state(&handoff.state);
				if (observed_state == SWAPZ_PREPARATION_PREPARING)
					sched_yield();
			} while (observed_state == SWAPZ_PREPARATION_PREPARING);
			CANCELLATION_CHECK(&handoff, iteration,
				"worker-terminal-acquire", terminal_owner, final_owner,
				2, 2, observed_state,
				observed_state ==
					swapz_preparation_codec_result_state(codec_result) &&
				handoff.result_length == codec_result);
			if (codec_result > 0) {
				CANCELLATION_CHECK(&handoff, iteration,
					"worker-ready-generation", terminal_owner,
					final_owner, 2, 2, observed_state,
					handoff.prepared_generation == iteration);
				for (byte = 0; byte < RAW_SNAPSHOT_BYTES; ++byte)
					CANCELLATION_CHECK(&handoff, iteration,
						"worker-ready-payload", terminal_owner,
						final_owner, 2, 2, observed_state,
						handoff.prepared_bytes[byte] ==
							(unsigned char)(iteration ^ byte ^
									0x5aU));
			}
			if (codec_result >= 0)
				CANCELLATION_CHECK(&handoff, iteration,
					"ready-charge-before-retire", terminal_owner,
					final_owner, 2, 2, observed_state,
					atomic_load_explicit(&handoff.ready_charges,
						memory_order_relaxed) == 1);

			if (!worker_first_put) {
				retired_state =
					swapz_preparation_retire(&handoff.state);
				CANCELLATION_CHECK(&handoff, iteration,
					"ordered-retire-ready-before-worker-put",
					terminal_owner, final_owner, 2, 2,
					retired_state,
					retired_state ==
						swapz_preparation_codec_result_state(codec_result) &&
					retired_state != SWAPZ_PREPARATION_ERROR &&
					swapz_preparation_read_state(&handoff.state) ==
						SWAPZ_PREPARATION_CONSUMED);
				CANCELLATION_CHECK(&handoff, iteration,
					"ready-charge-retired", terminal_owner,
					final_owner, 2, 2, retired_state,
					atomic_fetch_sub_explicit(
						&handoff.ready_charges, 1,
						memory_order_relaxed) == 1);
				refs_before = cancellation_put(&handoff, iteration,
					"ordered-put-first", terminal_owner,
					final_owner);
				CANCELLATION_CHECK(&handoff, iteration,
					"ordered-put-first", terminal_owner,
					final_owner, refs_before, refs_before - 1U,
					retired_state, refs_before == 2U);
				atomic_store_explicit(&handoff.owner_done,
					iteration + 1U, memory_order_release);
			}
		}

		(void)pthread_barrier_wait(&handoff.allow_worker_put);
		if (!cancel_first && worker_first_put) {
			while (atomic_load_explicit(&handoff.worker_done,
					memory_order_acquire) != iteration + 1U)
				sched_yield();
			CANCELLATION_CHECK(&handoff, iteration, "worker-put-first",
				terminal_owner, final_owner, 2, 1, observed_state,
				atomic_load_explicit(&handoff.references,
					memory_order_relaxed) == 1 &&
				atomic64_read(&handoff.free_mask) == 0 &&
				atomic_load_explicit(&handoff.drain_done,
					memory_order_relaxed) == iteration);

			retired_state = swapz_preparation_retire(&handoff.state);
			if (codec_result >= 0) {
				CANCELLATION_CHECK(&handoff, iteration,
					"ordered-retire-ready-after-worker-put",
					terminal_owner, final_owner, 1, 1,
					retired_state,
					retired_state ==
						swapz_preparation_codec_result_state(codec_result) &&
					swapz_preparation_read_state(&handoff.state) ==
						SWAPZ_PREPARATION_CONSUMED);
				CANCELLATION_CHECK(&handoff, iteration,
					"ready-charge-retired", terminal_owner,
					final_owner, 1, 1, retired_state,
					atomic_fetch_sub_explicit(
						&handoff.ready_charges, 1,
						memory_order_relaxed) == 1);
			} else {
				CANCELLATION_CHECK(&handoff, iteration,
					"ordered-retire-error", terminal_owner,
					final_owner, 1, 1, retired_state,
					retired_state == SWAPZ_PREPARATION_ERROR &&
					swapz_preparation_read_state(&handoff.state) ==
						SWAPZ_PREPARATION_ERROR);
			}
			refs_before = cancellation_put(&handoff, iteration,
				"ordered-final-put", terminal_owner, final_owner);
			CANCELLATION_CHECK(&handoff, iteration, "ordered-final-put",
				terminal_owner, final_owner, refs_before,
				refs_before - 1U, retired_state, refs_before == 1U);
			atomic_store_explicit(&handoff.owner_done, iteration + 1U,
				memory_order_release);
		}

		while (atomic_load_explicit(&handoff.drain_done,
				memory_order_acquire) != iteration + 1U)
			sched_yield();
		CANCELLATION_CHECK(&handoff, iteration, "drained-final-put",
			terminal_owner, final_owner, 1, 0, observed_state,
			atomic_load_explicit(&handoff.references,
				memory_order_relaxed) == 0 &&
			atomic_load_explicit(&handoff.final_puts,
				memory_order_relaxed) == iteration + 1U &&
			atomic_load_explicit(&handoff.ready_charges,
				memory_order_relaxed) == 0 &&
			swapz_preparation_read_state(&handoff.state) ==
				SWAPZ_PREPARATION_EMPTY);
		CANCELLATION_CHECK(&handoff, iteration, "drained-terminal-once",
			terminal_owner, final_owner, 1, 0, observed_state,
			atomic_load_explicit(&handoff.result_attempts,
				memory_order_relaxed) == iteration + 1U &&
			atomic_load_explicit(&handoff.terminal_publications,
				memory_order_relaxed) +
			atomic_load_explicit(&handoff.cancellation_claims,
				memory_order_relaxed) == iteration + 1U);

		CANCELLATION_CHECK(&handoff, iteration, "reclaim-after-drain",
			terminal_owner, final_owner, 0, 0, observed_state,
			swapz_preparation_claim_slot(&handoff.free_mask) == 63);
		for (byte = 0; byte < RAW_SNAPSHOT_BYTES; ++byte)
			handoff.prepared_bytes[byte] = 0xa5U;
		handoff.prepared_generation = ~0U;
		handoff.result_length = 0x7fffffff;
		CANCELLATION_CHECK(&handoff, iteration, "no-stale-publisher",
			terminal_owner, final_owner, 0, 0, observed_state,
			atomic_load_explicit(&handoff.result_attempts,
				memory_order_relaxed) == iteration + 1U &&
			swapz_preparation_read_state(&handoff.state) ==
				SWAPZ_PREPARATION_EMPTY);
		swapz_preparation_release_slot(&handoff.free_mask, 63);
		(void)pthread_barrier_wait(&handoff.recycled);
	}

	CHECK(pthread_join(worker, NULL) == 0);
	CHECK(pthread_join(drainer, NULL) == 0);
	CHECK(pthread_barrier_destroy(&handoff.start) == 0);
	CHECK(pthread_barrier_destroy(&handoff.snapshot_taken) == 0);
	CHECK(pthread_barrier_destroy(&handoff.allow_result) == 0);
	CHECK(pthread_barrier_destroy(&handoff.allow_worker_put) == 0);
	CHECK(pthread_barrier_destroy(&handoff.recycled) == 0);
	CHECK(atomic_load_explicit(&handoff.failures, memory_order_relaxed) == 0);
	return 0;
}



/*
 * Model the target's final lifetime joins with real pthread joins. The three
 * workers represent an in-flight lower callback, already-published completion
 * work and a cancelled preparation producer. Shutdown closes admission while
 * all three are live. Clearing an active flag or returning slot 63 is not
 * sufficient to authorize memory release: the corresponding worker must have
 * actually returned and been joined.
 *
 * This is rootless C11/POSIX lifetime evidence only. It does not model dm_io,
 * workqueue internals or prove loaded-kernel race freedom.
 */
#define SHUTDOWN_OVERLAP_ROUNDS 32U
struct shutdown_overlap_handoff {
	atomic_t state;
	atomic64_t free_mask;
	_Atomic unsigned int references;
	_Atomic unsigned int accepting;
	_Atomic unsigned int lower_active;
	_Atomic unsigned int completion_active;
	_Atomic unsigned int producer_active;
	_Atomic unsigned int lower_entered;
	_Atomic unsigned int completion_entered;
	_Atomic unsigned int producer_entered;
	_Atomic unsigned int drain_started;
	_Atomic unsigned int allow_lower_return;
	_Atomic unsigned int allow_completion_clear;
	_Atomic unsigned int allow_completion_return;
	_Atomic unsigned int allow_producer_put;
	_Atomic unsigned int allow_producer_return;
	_Atomic unsigned int lower_final_access_done;
	_Atomic unsigned int completion_waiting_to_return;
	_Atomic unsigned int producer_put_done;
	_Atomic unsigned int memory_released;
	_Atomic unsigned int failures;
	pthread_t lower_thread;
	pthread_t completion_thread;
	pthread_t producer_thread;
	int codec_result;
	int observed_publish_state;
	unsigned int lower_payload;
	unsigned int completion_payload;
	unsigned int producer_payload;
};

static void shutdown_overlap_fail(struct shutdown_overlap_handoff *handoff,
				  unsigned int iteration, const char *phase,
				  const char *condition)
{
	fprintf(stderr,
		"preparation-lifetime shutdown-overlap iteration=%u phase=%s "
		"lower_active=%u completion_active=%u producer_active=%u "
		"refs=%u slot_mask=0x%llx state=%d memory_released=%u: %s\n",
		iteration, phase,
		atomic_load_explicit(&handoff->lower_active, memory_order_relaxed),
		atomic_load_explicit(&handoff->completion_active,
				     memory_order_relaxed),
		atomic_load_explicit(&handoff->producer_active,
				     memory_order_relaxed),
		atomic_load_explicit(&handoff->references, memory_order_relaxed),
		(unsigned long long)atomic64_read(&handoff->free_mask),
		swapz_preparation_read_state(&handoff->state),
		atomic_load_explicit(&handoff->memory_released,
				     memory_order_relaxed),
		condition);
	atomic_fetch_add_explicit(&handoff->failures, 1, memory_order_relaxed);
}

#define SHUTDOWN_OVERLAP_CHECK(handoff, iteration, phase, condition) do { \
	if (!(condition)) \
		shutdown_overlap_fail((handoff), (iteration), (phase), #condition); \
} while (0)

static void shutdown_overlap_release_prepared(
	struct shutdown_overlap_handoff *handoff)
{
	unsigned int references = atomic_fetch_sub_explicit(
		&handoff->references, 1, memory_order_acq_rel);

	if (references != 1U) {
		atomic_fetch_add_explicit(&handoff->failures, 1,
					 memory_order_relaxed);
		atomic_store_explicit(&handoff->references, 0, memory_order_relaxed);
	}
	atomic_store_explicit(&handoff->state.value, SWAPZ_PREPARATION_EMPTY,
			      memory_order_relaxed);
	swapz_preparation_release_slot(&handoff->free_mask, 63);
}

static void *shutdown_overlap_lower_callback(void *opaque)
{
	struct shutdown_overlap_handoff *handoff = opaque;

	atomic_store_explicit(&handoff->lower_entered, 1, memory_order_release);
	while (!atomic_load_explicit(&handoff->allow_lower_return,
				     memory_order_acquire))
		sched_yield();
	/* Final modeled target access occurs before lower ownership is released. */
	handoff->lower_payload ^= 0x13579bdfU;
	atomic_store_explicit(&handoff->lower_active, 0, memory_order_release);
	atomic_store_explicit(&handoff->lower_final_access_done, 1,
			      memory_order_release);
	return NULL;
}

static void *shutdown_overlap_completion_work(void *opaque)
{
	struct shutdown_overlap_handoff *handoff = opaque;

	atomic_store_explicit(&handoff->completion_entered, 1,
			      memory_order_release);
	while (!atomic_load_explicit(&handoff->allow_completion_clear,
				     memory_order_acquire))
		sched_yield();
	/* completion_active clears only after the work item has stopped using data. */
	handoff->completion_payload ^= 0x2468ace0U;
	atomic_store_explicit(&handoff->completion_active, 0,
			      memory_order_release);
	atomic_store_explicit(&handoff->completion_waiting_to_return, 1,
			      memory_order_release);
	while (!atomic_load_explicit(&handoff->allow_completion_return,
				     memory_order_acquire))
		sched_yield();
	return NULL;
}

static void *shutdown_overlap_preparation_producer(void *opaque)
{
	struct shutdown_overlap_handoff *handoff = opaque;

	atomic_store_explicit(&handoff->producer_entered, 1, memory_order_release);
	while (!atomic_load_explicit(&handoff->allow_producer_put,
				     memory_order_acquire))
		sched_yield();
	handoff->producer_payload ^= 0x55aa55aaU;
	handoff->observed_publish_state = swapz_preparation_publish_codec_result(
		&handoff->state, handoff->codec_result);
	shutdown_overlap_release_prepared(handoff);
	atomic_store_explicit(&handoff->producer_active, 0, memory_order_release);
	atomic_store_explicit(&handoff->producer_put_done, 1,
			      memory_order_release);
	while (!atomic_load_explicit(&handoff->allow_producer_return,
				     memory_order_acquire))
		sched_yield();
	return NULL;
}

static void *shutdown_overlap_drainer(void *opaque)
{
	struct shutdown_overlap_handoff *handoff = opaque;

	atomic_store_explicit(&handoff->accepting, 0, memory_order_release);
	atomic_store_explicit(&handoff->drain_started, 1, memory_order_release);
	if (pthread_join(handoff->lower_thread, NULL) != 0 ||
	    pthread_join(handoff->completion_thread, NULL) != 0 ||
	    pthread_join(handoff->producer_thread, NULL) != 0) {
		atomic_fetch_add_explicit(&handoff->failures, 1,
					 memory_order_relaxed);
		return NULL;
	}
	if (atomic_load_explicit(&handoff->lower_active, memory_order_acquire) ||
	    atomic_load_explicit(&handoff->completion_active,
				 memory_order_acquire) ||
	    atomic_load_explicit(&handoff->producer_active,
				 memory_order_acquire) ||
	    atomic_load_explicit(&handoff->references, memory_order_acquire) ||
	    (uint64_t)atomic64_read(&handoff->free_mask) != (1ULL << 63) ||
	    swapz_preparation_read_state(&handoff->state) !=
		    SWAPZ_PREPARATION_EMPTY)
		atomic_fetch_add_explicit(&handoff->failures, 1,
					 memory_order_relaxed);
	/* The modeled allocation may be released only after every owner joined. */
	atomic_store_explicit(&handoff->memory_released, 1,
			      memory_order_release);
	return NULL;
}

static int test_shutdown_joins_callback_completion_and_preparation(void)
{
	static const int results[] = { 320, 0, -EIO };
	unsigned int iteration;

	for (iteration = 0; iteration < SHUTDOWN_OVERLAP_ROUNDS; ++iteration) {
		struct shutdown_overlap_handoff handoff = { 0 };
		pthread_t drainer;

		atomic_init(&handoff.state.value, SWAPZ_PREPARATION_CANCELLED);
		atomic_init(&handoff.free_mask.value, (s64)(1ULL << 63));
		atomic_init(&handoff.references, 1);
		atomic_init(&handoff.accepting, 1);
		atomic_init(&handoff.lower_active, 1);
		atomic_init(&handoff.completion_active, 1);
		atomic_init(&handoff.producer_active, 1);
		atomic_init(&handoff.lower_entered, 0);
		atomic_init(&handoff.completion_entered, 0);
		atomic_init(&handoff.producer_entered, 0);
		atomic_init(&handoff.drain_started, 0);
		atomic_init(&handoff.allow_lower_return, 0);
		atomic_init(&handoff.allow_completion_clear, 0);
		atomic_init(&handoff.allow_completion_return, 0);
		atomic_init(&handoff.allow_producer_put, 0);
		atomic_init(&handoff.allow_producer_return, 0);
		atomic_init(&handoff.lower_final_access_done, 0);
		atomic_init(&handoff.completion_waiting_to_return, 0);
		atomic_init(&handoff.producer_put_done, 0);
		atomic_init(&handoff.memory_released, 0);
		atomic_init(&handoff.failures, 0);
		handoff.codec_result =
			results[iteration % (sizeof(results) / sizeof(results[0]))];
		handoff.observed_publish_state = SWAPZ_PREPARATION_EMPTY;
		handoff.lower_payload = iteration;
		handoff.completion_payload = iteration;
		handoff.producer_payload = iteration;

		SHUTDOWN_OVERLAP_CHECK(&handoff, iteration, "claim-slot",
			swapz_preparation_claim_slot(&handoff.free_mask) == 63);
		CHECK(pthread_create(&handoff.lower_thread, NULL,
				     shutdown_overlap_lower_callback, &handoff) == 0);
		CHECK(pthread_create(&handoff.completion_thread, NULL,
				     shutdown_overlap_completion_work, &handoff) == 0);
		CHECK(pthread_create(&handoff.producer_thread, NULL,
				     shutdown_overlap_preparation_producer,
				     &handoff) == 0);
		CHECK(pthread_create(&drainer, NULL, shutdown_overlap_drainer,
				     &handoff) == 0);

		while (!atomic_load_explicit(&handoff.lower_entered,
					    memory_order_acquire) ||
		       !atomic_load_explicit(&handoff.completion_entered,
					    memory_order_acquire) ||
		       !atomic_load_explicit(&handoff.producer_entered,
					    memory_order_acquire) ||
		       !atomic_load_explicit(&handoff.drain_started,
					    memory_order_acquire))
			sched_yield();
		SHUTDOWN_OVERLAP_CHECK(&handoff, iteration, "shutdown-overlap",
			!atomic_load_explicit(&handoff.accepting,
					     memory_order_acquire) &&
			!atomic_load_explicit(&handoff.memory_released,
					     memory_order_acquire));

		atomic_store_explicit(&handoff.allow_lower_return, 1,
				      memory_order_release);
		while (!atomic_load_explicit(&handoff.lower_final_access_done,
					    memory_order_acquire))
			sched_yield();
		SHUTDOWN_OVERLAP_CHECK(&handoff, iteration, "lower-return",
			!atomic_load_explicit(&handoff.lower_active,
					     memory_order_acquire) &&
			handoff.lower_payload == (iteration ^ 0x13579bdfU) &&
			!atomic_load_explicit(&handoff.memory_released,
					     memory_order_acquire));

		atomic_store_explicit(&handoff.allow_completion_clear, 1,
				      memory_order_release);
		while (!atomic_load_explicit(&handoff.completion_waiting_to_return,
					    memory_order_acquire))
			sched_yield();
		SHUTDOWN_OVERLAP_CHECK(&handoff, iteration, "completion-active-clear",
			!atomic_load_explicit(&handoff.completion_active,
					     memory_order_acquire) &&
			handoff.completion_payload == (iteration ^ 0x2468ace0U) &&
			!atomic_load_explicit(&handoff.memory_released,
					     memory_order_acquire));

		atomic_store_explicit(&handoff.allow_producer_put, 1,
				      memory_order_release);
		while (!atomic_load_explicit(&handoff.producer_put_done,
					    memory_order_acquire))
			sched_yield();
		SHUTDOWN_OVERLAP_CHECK(&handoff, iteration, "prepared-slot-free",
			handoff.observed_publish_state == SWAPZ_PREPARATION_CANCELLED &&
			!atomic_load_explicit(&handoff.references,
					     memory_order_acquire) &&
			(uint64_t)atomic64_read(&handoff.free_mask) == (1ULL << 63) &&
			swapz_preparation_read_state(&handoff.state) ==
				SWAPZ_PREPARATION_EMPTY &&
			!atomic_load_explicit(&handoff.producer_active,
					     memory_order_acquire) &&
			handoff.producer_payload == (iteration ^ 0x55aa55aaU) &&
			!atomic_load_explicit(&handoff.memory_released,
					     memory_order_acquire));

		/* Clearing active flags and freeing the slot are insufficient while
		 * work items are still blocked from returning. */
		atomic_store_explicit(&handoff.allow_completion_return, 1,
				      memory_order_release);
		sched_yield();
		SHUTDOWN_OVERLAP_CHECK(&handoff, iteration, "completion-return-only",
			!atomic_load_explicit(&handoff.memory_released,
					     memory_order_acquire));
		atomic_store_explicit(&handoff.allow_producer_return, 1,
				      memory_order_release);
		CHECK(pthread_join(drainer, NULL) == 0);
		SHUTDOWN_OVERLAP_CHECK(&handoff, iteration, "all-joined",
			atomic_load_explicit(&handoff.memory_released,
					    memory_order_acquire) &&
			!atomic_load_explicit(&handoff.failures,
					     memory_order_relaxed));
		if (atomic_load_explicit(&handoff.failures, memory_order_relaxed))
			return 1;
	}
	return 0;
}

int main(void)
{
	CHECK(!test_ordered_ack_and_refcount_lifetime());
	CHECK(!test_producer_releases_first_consumer_reclaims_last());
	CHECK(!test_closed_admission_suppresses_owner_wake());
	CHECK(!test_submitter_active_gate_and_lane_drain());
	CHECK(!test_cancellation_terminal_drain_and_slot_reuse());
	CHECK(!test_shutdown_joins_callback_completion_and_preparation());
	puts("SWAPZ_PREPARATION_PUBLICATION_LIFETIME_PASS=6");
	return 0;
}
