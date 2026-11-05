// SPDX-License-Identifier: GPL-2.0-only
#define _POSIX_C_SOURCE 200809L
/* Run the production slot algorithm with C11 atomic operations. This is not
 * a Linux memory-model proof or a substitute for loaded BIO/drain coverage. */
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef int64_t s64;
typedef struct { _Atomic int64_t value; } atomic64_t;
typedef struct { _Atomic int value; } atomic_t;

/* The producer is forced to publish between the consumer's initial acquire
 * and its RAW CAS. Relaxed scheduling flags intentionally publish no payload. */
struct forced_terminal_publication {
	atomic_t state;
	_Atomic int publisher_requested;
	_Atomic int publication_done;
	_Atomic int producer_failed;
	int codec_result;
	int terminal_state;
	uint64_t expected_metadata;
	uint64_t metadata;
};

/*
 * Only the consumer thread intercepts its RAW-selection cmpxchg. A publisher
 * thread starts with a null thread-local hook and therefore executes the shared
 * production publication helper normally.
 */
static _Thread_local struct forced_terminal_publication *forced_publication;

/* CAS collision is only a reader-side schedule, not a payload publication. */
struct ready_collision_hook {
	const atomic_t *state;
	pthread_barrier_t *collision;
	int expected_ready_state;
	int replacement_state;
	unsigned int acquire_reads;
	unsigned int failed_cas;
};
static _Thread_local struct ready_collision_hook *ready_collision;

/* Defined after the included production header; keep the CAS shim neutral. */
static void publish_interposed_terminal(atomic_t *state, int terminal_state);

/* A deterministic producer publication between the first read and raw CAS.
 * Counts API-level acquire observations; it is not a hardware reordering or
 * LKMM proof. The contract allows an unordered failed conditional RMW. */
static struct {
	const atomic_t *state;
	int ready_state;
	int publish_before_cas;
	unsigned int acquire_reads;
	unsigned int ready_acquires;
	unsigned int failed_cas;
	unsigned int helper_publications;
	unsigned int failed_helper_publications;
} publication;

static int atomic_read(atomic_t *value)
{
	return atomic_load_explicit(&value->value, memory_order_relaxed);
}

static int atomic_read_acquire(const atomic_t *value)
{
	int observed = atomic_load_explicit(&value->value, memory_order_acquire);

	if (value == publication.state) {
		publication.acquire_reads++;
		if (observed == publication.ready_state)
			publication.ready_acquires++;
	}
	if (ready_collision && value == ready_collision->state)
		ready_collision->acquire_reads++;
	return observed;
}

static int atomic_cmpxchg(atomic_t *value, int old, int replacement)
{
	int expected = old;

	if (value == publication.state && publication.publish_before_cas) {
		int terminal_state = publication.ready_state;

		/* Clear the hook before calling the real helper's nested CAS. */
		publication.publish_before_cas = 0;
		publication.helper_publications++;
		publish_interposed_terminal(value, terminal_state);
	}
	if (value == publication.state && forced_publication) {
		atomic_store_explicit(&forced_publication->publisher_requested, 1,
				      memory_order_relaxed);
		while (!atomic_load_explicit(&forced_publication->publication_done,
						    memory_order_relaxed))
			sched_yield();
	}
	/* Both READY readers reach their real CAS before either can win. */
	if (ready_collision && value == ready_collision->state &&
	    old == ready_collision->expected_ready_state &&
	    replacement == ready_collision->replacement_state)
		(void)pthread_barrier_wait(ready_collision->collision);
	/* Do not give Linux's failed-CAS path stronger ordering in this shim. */
	atomic_compare_exchange_strong_explicit(&value->value, &old, replacement,
			memory_order_seq_cst, memory_order_relaxed);
	if (value == publication.state && old != expected)
		publication.failed_cas++;
	if (ready_collision && value == ready_collision->state && old != expected)
		ready_collision->failed_cas++;
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

/* Forced CAS interposition publishes via the real production codec helper. */
static void publish_interposed_terminal(atomic_t *state, int terminal_state)
{
	int codec_result;

	switch (terminal_state) {
	case SWAPZ_PREPARATION_READY_COMPRESSED:
		codec_result = 2048;
		break;
	case SWAPZ_PREPARATION_READY_RAW:
		codec_result = 0;
		break;
	case SWAPZ_PREPARATION_ERROR:
		codec_result = -EIO;
		break;
	default:
		publication.failed_helper_publications++;
		return;
	}
	if (swapz_preparation_publish_codec_result(state, codec_result) !=
	    SWAPZ_PREPARATION_PREPARING)
		publication.failed_helper_publications++;
}

#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "%s:%d failed %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)

static int test_representation_race(void)
{
	atomic_t state;
	int observed;

	atomic_init(&state.value, SWAPZ_PREPARATION_PREPARING);
	CHECK(swapz_preparation_select_raw(&state) ==
	      SWAPZ_PREPARATION_RAW_SELECTED);
	CHECK(atomic_read(&state) == SWAPZ_PREPARATION_RAW_SELECTED);
	CHECK(swapz_preparation_publish_result(
		      &state, SWAPZ_PREPARATION_READY_COMPRESSED) ==
	      SWAPZ_PREPARATION_RAW_SELECTED);

	atomic_store(&state.value, SWAPZ_PREPARATION_PREPARING);
	observed = swapz_preparation_publish_result(
		&state, SWAPZ_PREPARATION_READY_COMPRESSED);
	CHECK(observed == SWAPZ_PREPARATION_PREPARING);
	CHECK(swapz_preparation_select_raw(&state) ==
	      SWAPZ_PREPARATION_READY_COMPRESSED);

	atomic_store(&state.value, SWAPZ_PREPARATION_PREPARING);
	CHECK(swapz_preparation_publish_result(
		      &state, SWAPZ_PREPARATION_READY_RAW) ==
	      SWAPZ_PREPARATION_PREPARING);
	CHECK(swapz_preparation_select_raw(&state) ==
	      SWAPZ_PREPARATION_READY_RAW);
	return 0;
}

static int test_terminal_failure_retires_preparation_result(void)
{
	atomic_t state;
	int retired;

	atomic_init(&state.value, SWAPZ_PREPARATION_PREPARING);
	CHECK(swapz_preparation_retire(&state) ==
	      SWAPZ_PREPARATION_CANCELLED);
	CHECK(swapz_preparation_publish_codec_result(&state, 2048) ==
	      SWAPZ_PREPARATION_CANCELLED);
	CHECK(swapz_preparation_read_state(&state) ==
	      SWAPZ_PREPARATION_CANCELLED);

	atomic_store(&state.value, SWAPZ_PREPARATION_PREPARING);
	CHECK(swapz_preparation_publish_codec_result(&state, 2048) ==
	      SWAPZ_PREPARATION_PREPARING);
	retired = swapz_preparation_retire(&state);
	CHECK(retired == SWAPZ_PREPARATION_READY_COMPRESSED);
	CHECK(swapz_preparation_read_state(&state) ==
	      SWAPZ_PREPARATION_CONSUMED);
	CHECK(swapz_preparation_retire(&state) ==
	      SWAPZ_PREPARATION_CONSUMED);
	CHECK(swapz_preparation_consume_ready(&state) ==
	      SWAPZ_PREPARATION_CONSUMED);

	atomic_store(&state.value, SWAPZ_PREPARATION_PREPARING);
	CHECK(swapz_preparation_publish_codec_result(&state, 0) ==
	      SWAPZ_PREPARATION_PREPARING);
	CHECK(swapz_preparation_consume_ready(&state) ==
	      SWAPZ_PREPARATION_READY_RAW);
	CHECK(swapz_preparation_read_state(&state) ==
	      SWAPZ_PREPARATION_CONSUMED);
	return 0;
}

/*
 * Negative control for the READY publication oracle below. This intentionally
 * weakens only the failed-CAS reread to relaxed ordering while preserving the
 * returned state value, so the test must reject it on acquire-count evidence.
 */
static int swapz_preparation_select_raw_relaxed_reread_mutant(atomic_t *state)
{
	int observed = swapz_preparation_read_state(state);

	if (observed == SWAPZ_PREPARATION_PREPARING) {
		observed = atomic_cmpxchg(state, SWAPZ_PREPARATION_PREPARING,
					 SWAPZ_PREPARATION_RAW_SELECTED);
		if (observed != SWAPZ_PREPARATION_PREPARING)
			return atomic_read(state);
	}
	return observed == SWAPZ_PREPARATION_PREPARING ?
		SWAPZ_PREPARATION_RAW_SELECTED : observed;
}

static int test_capacity_high_bit_and_reuse(void)
{
	atomic64_t mask;
	unsigned int i;

	atomic_init(&mask.value, (s64)SWAPZ_PREPARATION_FREE_MASK);
	for (i = 0; i < SWAPZ_MAX_RECORDS; ++i)
		CHECK(swapz_preparation_claim_slot(&mask) == (int)i);
	CHECK(atomic64_read(&mask) == 0);
	CHECK(swapz_preparation_claim_slot(&mask) == -1);
	swapz_preparation_release_slot(&mask, 63);
	CHECK((uint64_t)atomic64_read(&mask) == (1ULL << 63));
	CHECK(swapz_preparation_claim_slot(&mask) == 63);
	CHECK(swapz_preparation_claim_slot(&mask) == -1);
	for (i = 0; i < SWAPZ_MAX_RECORDS; ++i)
		swapz_preparation_release_slot(&mask, i);
	CHECK((uint64_t)atomic64_read(&mask) == SWAPZ_PREPARATION_FREE_MASK);
	/* Empty queue, rejected tail and failed copy all return a reserved slot. */
	for (i = 0; i < 3; ++i) {
		int slot = swapz_preparation_claim_slot(&mask);

		CHECK(slot == 0);
		swapz_preparation_release_slot(&mask, (unsigned int)slot);
		CHECK((uint64_t)atomic64_read(&mask) ==
		      SWAPZ_PREPARATION_FREE_MASK);
	}
	return 0;
}

static int test_ready_publication_wins_raw_cas(void)
{
	const int states[] = { SWAPZ_PREPARATION_READY_COMPRESSED,
			       SWAPZ_PREPARATION_READY_RAW,
			       SWAPZ_PREPARATION_ERROR };
	atomic_t state;
	unsigned int i;

	for (i = 0; i < sizeof(states) / sizeof(states[0]); ++i) {
		atomic_init(&state.value, SWAPZ_PREPARATION_PREPARING);
		publication.state = &state;
		publication.ready_state = states[i];
		publication.publish_before_cas = 1;
		publication.acquire_reads = 0;
		publication.ready_acquires = 0;
		publication.failed_cas = 0;
		publication.helper_publications = 0;
		publication.failed_helper_publications = 0;
		CHECK(swapz_preparation_select_raw(&state) == states[i]);
		CHECK(publication.failed_cas == 1);
		CHECK(publication.helper_publications == 1);
		CHECK(publication.failed_helper_publications == 0);
		CHECK(publication.ready_acquires == 1);
		CHECK(publication.acquire_reads == 2);
		CHECK(atomic_read(&state) == states[i]);

		/*
		 * Compiled negative control: the weakened reread returns the same
		 * READY value but must not satisfy the acquire-publication oracle.
		 */
		atomic_store(&state.value, SWAPZ_PREPARATION_PREPARING);
		publication.publish_before_cas = 1;
		publication.acquire_reads = 0;
		publication.ready_acquires = 0;
		publication.failed_cas = 0;
		publication.helper_publications = 0;
		publication.failed_helper_publications = 0;
		CHECK(swapz_preparation_select_raw_relaxed_reread_mutant(&state) ==
		      states[i]);
		CHECK(publication.failed_cas == 1);
		CHECK(publication.helper_publications == 1);
		CHECK(publication.failed_helper_publications == 0);
		CHECK(publication.ready_acquires == 0);
		CHECK(publication.acquire_reads == 1);
		CHECK(atomic_read(&state) == states[i]);

		/* Already-READY is the ordinary one-acquire fast path. */
		publication.acquire_reads = 0;
		publication.ready_acquires = 0;
		publication.failed_cas = 0;
		publication.helper_publications = 0;
		publication.failed_helper_publications = 0;
		CHECK(swapz_preparation_select_raw(&state) == states[i]);
		CHECK(publication.acquire_reads == 1);
		CHECK(publication.ready_acquires == 1);
		CHECK(publication.failed_cas == 0);
	}
	/* A successful RAW claim likewise needs no extra state read. */
	atomic_store(&state.value, SWAPZ_PREPARATION_PREPARING);
	publication.acquire_reads = 0;
	publication.ready_acquires = 0;
	publication.failed_cas = 0;
	publication.helper_publications = 0;
	publication.failed_helper_publications = 0;
	CHECK(swapz_preparation_select_raw(&state) == SWAPZ_PREPARATION_RAW_SELECTED);
	CHECK(publication.acquire_reads == 1);
	CHECK(publication.ready_acquires == 0);
	CHECK(publication.failed_cas == 0);
	CHECK(publication.helper_publications == 0);
	CHECK(publication.failed_helper_publications == 0);
	publication.state = NULL;
	return 0;
}

static void *publish_terminal_between_read_and_cas(void *opaque)
{
	struct forced_terminal_publication *handoff = opaque;
	int previous_state;

	while (!atomic_load_explicit(&handoff->publisher_requested,
				     memory_order_relaxed))
		sched_yield();
	handoff->metadata = handoff->expected_metadata;
	previous_state = swapz_preparation_publish_codec_result(
		&handoff->state, handoff->codec_result);
	if (previous_state != SWAPZ_PREPARATION_PREPARING)
		atomic_store_explicit(&handoff->producer_failed, 1,
				      memory_order_relaxed);
	atomic_store_explicit(&handoff->publication_done, 1,
			      memory_order_relaxed);
	return NULL;
}

static int test_thread_published_terminal_metadata_after_failed_cas(void)
{
	static const struct {
		int codec_result;
		int terminal_state;
	} cases[] = {
		{ 2048, SWAPZ_PREPARATION_READY_COMPRESSED },
		{ 0, SWAPZ_PREPARATION_READY_RAW },
		{ -EIO, SWAPZ_PREPARATION_ERROR },
	};
	unsigned int case_index, iteration;

	for (case_index = 0; case_index < sizeof(cases) / sizeof(cases[0]);
	     ++case_index) {
		for (iteration = 0; iteration < 64U; ++iteration) {
			struct forced_terminal_publication handoff;
			pthread_t producer;

			atomic_init(&handoff.state.value, SWAPZ_PREPARATION_PREPARING);
			atomic_init(&handoff.publisher_requested, 0);
			atomic_init(&handoff.publication_done, 0);
			atomic_init(&handoff.producer_failed, 0);
			handoff.codec_result = cases[case_index].codec_result;
			handoff.terminal_state = cases[case_index].terminal_state;
			handoff.expected_metadata =
				((uint64_t)handoff.terminal_state << 48) ^
				((uint64_t)iteration * UINT64_C(0x9e3779b97f4a7c15));
			handoff.metadata = 0;
			publication.state = &handoff.state;
			publication.ready_state = handoff.terminal_state;
			publication.publish_before_cas = 0;
			publication.acquire_reads = 0;
			publication.ready_acquires = 0;
			publication.failed_cas = 0;
			forced_publication = &handoff;
			CHECK(pthread_create(&producer, NULL,
					     publish_terminal_between_read_and_cas,
					     &handoff) == 0);
			CHECK(swapz_preparation_select_raw(&handoff.state) ==
			      handoff.terminal_state);
			/*
			 * The relaxed publication_done flag is only a schedule gate.
			 * This ordinary metadata read must be justified by the failed
			 * CAS path's second acquire, not by thread join or a barrier.
			 */
			CHECK(handoff.metadata == handoff.expected_metadata);
			CHECK(!atomic_load_explicit(&handoff.producer_failed,
						    memory_order_relaxed));
			CHECK(publication.failed_cas == 1);
			CHECK(publication.acquire_reads == 2);
			CHECK(publication.ready_acquires == 1);
			CHECK(pthread_join(producer, NULL) == 0);
			forced_publication = NULL;
			publication.state = NULL;
		}
	}
	return 0;
}

static int test_closed_admission_suppresses_producer_owner_wake(void)
{
	unsigned int ordered_wakes = 0;

	CHECK(swapz_preparation_owner_wake_allowed(1));
	CHECK(!swapz_preparation_owner_wake_allowed(0));
	/* Model a producer that finishes only in the final preparation drain,
	 * after the ordered workqueue has already drained. */
	if (swapz_preparation_owner_wake_allowed(0))
		ordered_wakes++;
	CHECK(ordered_wakes == 0);
	/* Ordinary operation retains the producer-to-owner progress edge. */
	if (swapz_preparation_owner_wake_allowed(1))
		ordered_wakes++;
	CHECK(ordered_wakes == 1);
	return 0;
}

/*
 * Kernel-side locking is not exercised by the pure preparation-slot policy.
 * Read the actual target source to guard both wake/close critical sections
 * and the first-terminal-error release-publication order.
 */
static int test_production_failure_and_wake_gates(void)
{
	static const char marker[] = "tests/runtime/native/io/preparation-slots.c";
	static const char target[] = "src/kernel/dm-target.c";
	char source_path[4096], line[1024], failure_body[2048] = { 0 };
	char drain_body[6144] = { 0 };
	const char *marker_position = strstr(__FILE__, marker);
	const char *lock_position, *condition_position, *error_position;
	const char *publication_position, *unlock_position, *log_position;
	const char *drain_lock, *admission_close, *drain_unlock, *submitter_wait;
	const char *first_preparation_drain, *ordered_flush, *ordered_drain;
	const char *last_preparation_drain, *reclaim_check;
	FILE *source;
	size_t failure_bytes = 0, drain_bytes = 0;
	unsigned int wake_guards = 0, wake_publications = 0;
	int in_producer = 0, in_failure = 0, in_drain = 0;
	int producer_locked = 0;
	int pending_wake = 0, path_length;

	CHECK(marker_position != NULL);
	path_length = snprintf(source_path, sizeof(source_path), "%.*s%s",
			       (int)(marker_position - __FILE__), __FILE__, target);
	CHECK(path_length > 0 && (size_t)path_length < sizeof(source_path));
	source = fopen(source_path, "r");
	CHECK(source != NULL);
	while (fgets(line, sizeof(line), source)) {
		if (strstr(line, "static void swapz_preparation_worker("))
			in_producer = 1;
		if (strstr(line, "static void swapz_order_window_greedy("))
			in_producer = 0;
		if (!failure_bytes &&
		    (strstr(line, "static void swapz_fail_at(") ||
		     strstr(line, "static void swapz_fail(")))
			in_failure = 1;
		if (in_failure) {
			size_t length = strlen(line);

			CHECK(failure_bytes + length < sizeof(failure_body));
			memcpy(failure_body + failure_bytes, line, length);
			failure_bytes += length;
			if (line[0] == '}')
				in_failure = 0;
		}
		if (strstr(line, "static void swapz_drain("))
			in_drain = 1;
		if (in_drain) {
			size_t length = strlen(line);

			CHECK(drain_bytes + length < sizeof(drain_body));
			memcpy(drain_body + drain_bytes, line, length);
			drain_bytes += length;
			if (line[0] == '}')
				in_drain = 0;
		}
		if (!in_producer)
			continue;
		if (strstr(line, "spin_lock_irqsave(&ctx->queue_lock, flags)"))
			producer_locked = 1;
		if (strstr(line, "swapz_preparation_owner_wake_allowed(")) {
			CHECK(producer_locked && !pending_wake);
			wake_guards++;
			pending_wake = 1;
		}
		if (pending_wake &&
		    strstr(line, "mod_delayed_work(ctx->workqueue, &ctx->worker, 0)")) {
			CHECK(producer_locked);
			wake_publications++;
		}
		if (strstr(line, "spin_unlock_irqrestore(&ctx->queue_lock, flags)")) {
			if (pending_wake) {
				CHECK(producer_locked);
				pending_wake = 0;
			}
			producer_locked = 0;
		}
	}
	CHECK(!ferror(source));
	CHECK(!fclose(source));
	CHECK(!in_failure && !in_drain && !pending_wake);
	CHECK(drain_bytes > 0);
	CHECK(wake_guards == 2 && wake_publications == 2);
	lock_position = strstr(failure_body, "spin_lock_irqsave(&ctx->queue_lock, flags)");
	condition_position = strstr(failure_body, "if (!ctx->failed)");
	error_position = strstr(failure_body, "WRITE_ONCE(ctx->last_error, terminal_error)");
	publication_position = strstr(failure_body, "smp_store_release(&ctx->failed, true)");
	unlock_position = strstr(failure_body, "spin_unlock_irqrestore(&ctx->queue_lock, flags)");
	log_position = strstr(failure_body, "DMERR(");
	CHECK(lock_position && condition_position && error_position &&
	      publication_position && unlock_position && log_position);
	CHECK(lock_position < condition_position &&
	      condition_position < error_position &&
	      error_position < publication_position &&
	      publication_position < unlock_position &&
	      unlock_position < log_position);
	/* This is a source-order guard, not a substitute for loaded drain testing.
	 * The last producer drain is necessary because the ordered worker can
	 * schedule a final producer even after the first preparation drain. */
	drain_lock = strstr(drain_body, "spin_lock_irqsave(&ctx->queue_lock, flags)");
	admission_close = strstr(drain_body, "WRITE_ONCE(ctx->accepting, false)");
	drain_unlock = strstr(drain_body, "spin_unlock_irqrestore(&ctx->queue_lock, flags)");
	submitter_wait = strstr(drain_body, "while (ctx->submitter_prepare &&");
	first_preparation_drain = strstr(drain_body,
					 "drain_workqueue(ctx->preparation_workqueue);");
	ordered_flush = strstr(drain_body, "flush_delayed_work(&ctx->worker);");
	ordered_drain = strstr(drain_body, "drain_workqueue(ctx->workqueue);");
	last_preparation_drain = first_preparation_drain ?
		strstr(first_preparation_drain + 1,
		       "drain_workqueue(ctx->preparation_workqueue);") : NULL;
	reclaim_check = strstr(drain_body, "SWAPZ_PREPARATION_FREE_MASK");
	CHECK(drain_lock && admission_close && drain_unlock && submitter_wait &&
	      first_preparation_drain && ordered_flush && ordered_drain &&
	      last_preparation_drain && reclaim_check);
	CHECK(drain_lock < admission_close && admission_close < drain_unlock &&
	      drain_unlock < submitter_wait &&
	      submitter_wait < first_preparation_drain &&
	      first_preparation_drain < ordered_flush &&
	      ordered_flush < ordered_drain &&
	      ordered_drain < last_preparation_drain &&
	      last_preparation_drain < reclaim_check);
	return 0;
}

/*
 * Bounded C11 publication/ref-release/slot-reuse model (NOT an LKMM proof):
 * each producer owns a claimed slot and is its only PREPARING->terminal
 * publisher. Its metadata is sequenced before the real production CAS.
 * The consumer's acquire read of that CAS exposes immutable metadata.
 * The final owner stores EMPTY before release_slot's fence + relaxed OR;
 * the next producer's successful acquire CAS on the mask orders reuse.
 * Four concurrent producers contend for slots; no test-only ready store
 * is used as the publication edge. The relaxed-reread mutant above is
 * the deliberately broken negative control for the READY acquire edge.
 */
/*
 * Both preparers race for the only free bit. The loser cannot observe or
 * publish that slot until the first producer has dropped its reference and
 * the final consumer has returned the bit. Barriers schedule the two epochs;
 * they are NOT evidence of payload visibility (the concurrent test below
 * observes payload only after the actual terminal-state acquire).
 */
struct rival_slot_context {
	atomic64_t free_mask;
	atomic_t state;
	_Atomic unsigned int references;
	pthread_barrier_t start;
	pthread_barrier_t first_done;
	pthread_barrier_t retry;
	pthread_barrier_t second_done;
	int first_claim[2];
	int second_claim[2];
	int first_publication[2];
	int second_publication[2];
	unsigned int payload_owner;
};

struct rival_slot_argument {
	struct rival_slot_context *context;
	unsigned int producer_index;
};

static void *rival_slot_producer(void *opaque)
{
	const struct rival_slot_argument *argument = opaque;
	struct rival_slot_context *context = argument->context;
	const unsigned int producer_index = argument->producer_index;
	int slot;

	(void)pthread_barrier_wait(&context->start);
	slot = swapz_preparation_claim_slot(&context->free_mask);
	context->first_claim[producer_index] = slot;
	if (slot >= 0) {
		atomic_store_explicit(&context->state.value,
				      SWAPZ_PREPARATION_PREPARING,
				      memory_order_relaxed);
		context->payload_owner = producer_index + 1U;
		context->first_publication[producer_index] =
			swapz_preparation_publish_codec_result(&context->state, 2048);
		/* The producer is finished; only the consumer still owns the page. */
		(void)atomic_fetch_sub_explicit(&context->references, 1,
						 memory_order_acq_rel);
	}
	(void)pthread_barrier_wait(&context->first_done);
	(void)pthread_barrier_wait(&context->retry);
	if (slot < 0) {
		slot = swapz_preparation_claim_slot(&context->free_mask);
		context->second_claim[producer_index] = slot;
		if (slot >= 0) {
			atomic_store_explicit(&context->state.value,
					      SWAPZ_PREPARATION_PREPARING,
					      memory_order_relaxed);
			context->payload_owner = producer_index + 1U;
			context->second_publication[producer_index] =
				swapz_preparation_publish_codec_result(&context->state, 0);
			(void)atomic_fetch_sub_explicit(&context->references, 1,
							 memory_order_acq_rel);
		}
	}
	(void)pthread_barrier_wait(&context->second_done);
	return NULL;
}

static int test_two_producers_reclaim_only_after_final_consumer(void)
{
	struct rival_slot_context context = { 0 };
	struct rival_slot_argument arguments[2];
	pthread_t producers[2];
	unsigned int index, winning_producer, losing_producer;
	unsigned int first_references, second_references;
	unsigned int first_payload_owner, second_payload_owner;
	uint64_t first_free_mask, second_free_mask, final_free_mask;
	int first_terminal_state, second_terminal_state, premature_claim;

	atomic_init(&context.free_mask.value, (s64)(1ULL << 63));
	atomic_init(&context.state.value, SWAPZ_PREPARATION_EMPTY);
	atomic_init(&context.references, 2);
	for (index = 0; index < 2; ++index) {
		context.first_claim[index] = -2;
		context.second_claim[index] = -2;
		context.first_publication[index] = -2;
		context.second_publication[index] = -2;
	}
	CHECK(pthread_barrier_init(&context.start, NULL, 3) == 0);
	CHECK(pthread_barrier_init(&context.first_done, NULL, 3) == 0);
	CHECK(pthread_barrier_init(&context.retry, NULL, 3) == 0);
	CHECK(pthread_barrier_init(&context.second_done, NULL, 3) == 0);
	for (index = 0; index < 2; ++index) {
		arguments[index].context = &context;
		arguments[index].producer_index = index;
		CHECK(pthread_create(&producers[index], NULL, rival_slot_producer,
				     &arguments[index]) == 0);
	}
	(void)pthread_barrier_wait(&context.start);
	(void)pthread_barrier_wait(&context.first_done);

	/* One successful claim and one rejection while the slot is occupied. */
	winning_producer = context.first_claim[0] == 63 ? 0U : 1U;
	losing_producer = winning_producer ^ 1U;
	first_terminal_state = swapz_preparation_read_state(&context.state);
	first_payload_owner = context.payload_owner;
	first_references = atomic_load_explicit(&context.references,
						 memory_order_relaxed);
	premature_claim = swapz_preparation_claim_slot(&context.free_mask);
	/* Final consumer put and EMPTY store precede slot bit publication. */
	(void)atomic_fetch_sub_explicit(&context.references, 1,
					memory_order_acq_rel);
	atomic_store_explicit(&context.state.value, SWAPZ_PREPARATION_EMPTY,
			      memory_order_relaxed);
	swapz_preparation_release_slot(&context.free_mask, 63);
	first_free_mask = (uint64_t)atomic64_read(&context.free_mask);
	atomic_store_explicit(&context.references, 2, memory_order_relaxed);

	(void)pthread_barrier_wait(&context.retry);
	(void)pthread_barrier_wait(&context.second_done);
	second_terminal_state = swapz_preparation_read_state(&context.state);
	second_payload_owner = context.payload_owner;
	second_references = atomic_load_explicit(&context.references,
						  memory_order_relaxed);
	second_free_mask = (uint64_t)atomic64_read(&context.free_mask);
	(void)atomic_fetch_sub_explicit(&context.references, 1,
					memory_order_acq_rel);
	atomic_store_explicit(&context.state.value, SWAPZ_PREPARATION_EMPTY,
			      memory_order_relaxed);
	swapz_preparation_release_slot(&context.free_mask, 63);
	final_free_mask = (uint64_t)atomic64_read(&context.free_mask);

	for (index = 0; index < 2; ++index)
		CHECK(pthread_join(producers[index], NULL) == 0);
	CHECK(pthread_barrier_destroy(&context.start) == 0);
	CHECK(pthread_barrier_destroy(&context.first_done) == 0);
	CHECK(pthread_barrier_destroy(&context.retry) == 0);
	CHECK(pthread_barrier_destroy(&context.second_done) == 0);
	/* All validations follow thread joins; a failure cannot strand a barrier. */
	if (context.first_claim[winning_producer] != 63 ||
	    context.first_claim[losing_producer] != -1 ||
	    context.first_publication[winning_producer] !=
		    SWAPZ_PREPARATION_PREPARING ||
	    first_terminal_state != SWAPZ_PREPARATION_READY_COMPRESSED ||
	    first_payload_owner != winning_producer + 1U ||
	    first_references != 1 || premature_claim != -1 ||
	    first_free_mask != (1ULL << 63) ||
	    context.second_claim[losing_producer] != 63 ||
	    context.second_claim[winning_producer] != -2 ||
	    context.second_publication[losing_producer] !=
		    SWAPZ_PREPARATION_PREPARING ||
	    second_terminal_state != SWAPZ_PREPARATION_READY_RAW ||
	    second_payload_owner != losing_producer + 1U ||
	    second_references != 1 || second_free_mask != 0 ||
	    final_free_mask != (1ULL << 63)) {
		fprintf(stderr, "two-producer slot 63: claims=(%d,%d) retry=(%d,%d) "
			"CAS=(%d,%d)/(%d,%d) terminal=%d/%d refs=%u/%u "
			"payload_owner=%u/%u mask=0x%llx/0x%llx/0x%llx "
			"premature_claim=%d\n",
			context.first_claim[0], context.first_claim[1],
			context.second_claim[0], context.second_claim[1],
			context.first_publication[0], context.first_publication[1],
			context.second_publication[0], context.second_publication[1],
			first_terminal_state, second_terminal_state,
			first_references, second_references,
			first_payload_owner, second_payload_owner,
			(unsigned long long)first_free_mask,
			(unsigned long long)second_free_mask,
			(unsigned long long)final_free_mask, premature_claim);
		return 1;
	}
	CHECK(swapz_preparation_read_state(&context.state) ==
	      SWAPZ_PREPARATION_EMPTY);
	CHECK(atomic_load_explicit(&context.references, memory_order_relaxed) == 0);
	CHECK(swapz_preparation_claim_slot(&context.free_mask) == 63);
	CHECK(swapz_preparation_claim_slot(&context.free_mask) == -1);
	swapz_preparation_release_slot(&context.free_mask, 63);
	return 0;
}

#define TRANSFERS 8192U
#define PRODUCERS 4U
#define MAX_STALLED_POLLS 20000000U
_Static_assert(TRANSFERS % PRODUCERS == 0, "even producer sequence ranges");
static struct {
	atomic64_t mask;
	atomic_t states[SWAPZ_MAX_RECORDS];
	unsigned int sequences[SWAPZ_MAX_RECORDS];
	uint64_t bytes[SWAPZ_MAX_RECORDS][16];
	atomic_int failed;
	pthread_barrier_t start;
} exchange;

static void exchange_fail(const char *phase, unsigned int sequence,
			  unsigned int slot, int state, int expected_state)
{
	/* Emit one fail-only diagnostic even if several workers notice failure. */
	if (!atomic_exchange_explicit(&exchange.failed, 1, memory_order_relaxed))
		fprintf(stderr, "slot-reuse %s: sequence=%u slot=%u state=%d expected=%d\n",
			phase, sequence, slot, state, expected_state);
}

static void *produce(void *opaque)
{
	const unsigned int producer_index = *(const unsigned int *)opaque;
	const unsigned int first_sequence =
		producer_index * (TRANSFERS / PRODUCERS) + 1U;
	const unsigned int final_sequence =
		(producer_index + 1U) * (TRANSFERS / PRODUCERS);
	unsigned int sequence, byte;

	(void)pthread_barrier_wait(&exchange.start);
	for (sequence = first_sequence; sequence <= final_sequence; ++sequence) {
		unsigned int stalled_polls;
		int slot = -1;
		int codec_result = sequence % 3U == 0U ? -EIO :
			(sequence % 3U == 1U ? 0 : 2048);
		int previous_state;

		for (stalled_polls = 0; stalled_polls < MAX_STALLED_POLLS;
		     ++stalled_polls) {
			slot = swapz_preparation_claim_slot(&exchange.mask);
			if (slot >= 0 || atomic_load_explicit(
					&exchange.failed, memory_order_relaxed))
				break;
			sched_yield();
		}
		if (atomic_load_explicit(&exchange.failed, memory_order_relaxed))
			return NULL;
		if (slot < 0) {
			exchange_fail("producer-claim-timeout", sequence,
				      SWAPZ_MAX_RECORDS, -1, 0);
			return NULL;
		}
		/* The successful slot claim orders the previous owner's return. */
		atomic_store_explicit(&exchange.states[slot].value,
				      SWAPZ_PREPARATION_PREPARING,
				      memory_order_relaxed);
		exchange.sequences[slot] = sequence;
		for (byte = 0; byte < 16; ++byte)
			exchange.bytes[slot][byte] = (uint64_t)sequence * 17U + byte;
		previous_state = swapz_preparation_publish_codec_result(
			&exchange.states[slot], codec_result);
		if (previous_state != SWAPZ_PREPARATION_PREPARING) {
			exchange_fail("producer-publish-CAS", sequence,
				      (unsigned int)slot, previous_state,
				      SWAPZ_PREPARATION_PREPARING);
			return NULL;
		}
		/* The consumer owns reclamation; no producer reads this slot again. */
	}
	return NULL;
}

static void *consume(void *unused)
{
	unsigned int completed = 0, slot, byte, stalled_polls = 0;
	unsigned char seen[TRANSFERS] = { 0 };

	(void)unused;
	(void)pthread_barrier_wait(&exchange.start);
	while (completed < TRANSFERS &&
	       !atomic_load_explicit(&exchange.failed, memory_order_relaxed)) {
		unsigned int progress = 0;

		for (slot = 0; slot < SWAPZ_MAX_RECORDS; ++slot) {
			const int state = swapz_preparation_read_state(
				&exchange.states[slot]);
			unsigned int sequence;
			int expected_state, codec_result;

			if (state == SWAPZ_PREPARATION_EMPTY ||
			    state == SWAPZ_PREPARATION_PREPARING)
				continue;
			if (state != SWAPZ_PREPARATION_READY_COMPRESSED &&
			    state != SWAPZ_PREPARATION_READY_RAW &&
			    state != SWAPZ_PREPARATION_ERROR) {
				exchange_fail("consumer-terminal-state", 0,
					      slot, state, SWAPZ_PREPARATION_ERROR);
				return NULL;
			}
			/* Acquire of the real producer CAS precedes plain payload reads. */
			sequence = exchange.sequences[slot];
			if (!sequence || sequence > TRANSFERS ||
			    seen[sequence - 1]) {
				exchange_fail("consumer-duplicate-sequence", sequence,
					      slot, state, 0);
				return NULL;
			}
			codec_result = sequence % 3U == 0U ? -EIO :
				(sequence % 3U == 1U ? 0 : 2048);
			expected_state =
				swapz_preparation_codec_result_state(codec_result);
			if (state != expected_state) {
				exchange_fail("consumer-codec-state", sequence,
					      slot, state, expected_state);
				return NULL;
			}
			for (byte = 0; byte < 16; ++byte) {
				if (exchange.bytes[slot][byte] !=
				    (uint64_t)sequence * 17U + byte) {
					exchange_fail("consumer-payload", sequence,
						      slot, state, expected_state);
					return NULL;
				}
			}
			seen[sequence - 1] = 1;
			/* Final consumer reference: EMPTY before reuse publication. */
			atomic_store_explicit(&exchange.states[slot].value,
					      SWAPZ_PREPARATION_EMPTY,
					      memory_order_relaxed);
			swapz_preparation_release_slot(&exchange.mask, slot);
			completed++;
			progress++;
		}
		if (progress) {
			stalled_polls = 0;
		} else {
			if (++stalled_polls == MAX_STALLED_POLLS) {
				exchange_fail("consumer-drain-timeout", completed,
					      SWAPZ_MAX_RECORDS, -1, 0);
				return NULL;
			}
			sched_yield();
		}
	}
	return NULL;
}

static int test_concurrent_reuse(void)
{
	pthread_t producers[PRODUCERS], consumer;
	unsigned int producer_indices[PRODUCERS];
	unsigned int index;

	atomic_init(&exchange.mask.value, (s64)SWAPZ_PREPARATION_FREE_MASK);
	atomic_init(&exchange.failed, 0);
	for (index = 0; index < SWAPZ_MAX_RECORDS; ++index)
		atomic_init(&exchange.states[index].value, SWAPZ_PREPARATION_EMPTY);
	CHECK(pthread_barrier_init(&exchange.start, NULL, PRODUCERS + 1U) == 0);
	CHECK(pthread_create(&consumer, NULL, consume, NULL) == 0);
	for (index = 0; index < PRODUCERS; ++index) {
		producer_indices[index] = index;
		CHECK(pthread_create(&producers[index], NULL, produce,
				     &producer_indices[index]) == 0);
	}
	for (index = 0; index < PRODUCERS; ++index)
		CHECK(pthread_join(producers[index], NULL) == 0);
	CHECK(pthread_join(consumer, NULL) == 0);
	CHECK(pthread_barrier_destroy(&exchange.start) == 0);
	CHECK(!atomic_load_explicit(&exchange.failed, memory_order_relaxed));
	CHECK((uint64_t)atomic64_read(&exchange.mask) ==
	      SWAPZ_PREPARATION_FREE_MASK);
	for (index = 0; index < SWAPZ_MAX_RECORDS; ++index)
		CHECK(swapz_preparation_read_state(&exchange.states[index]) ==
		      SWAPZ_PREPARATION_EMPTY);
	return 0;
}

/*
 * Deterministic final-reference handoff across two uses of slot 63. The first
 * epoch covers both cancellation before producer publication and producer-first
 * completion. The second epoch immediately reuses the slot. Relaxed atomic
 * flags schedule the interleaving without publishing payload bytes; terminal
 * payload visibility must come from the production state acquire, and reuse
 * visibility must come from release_slot()/claim_slot().
 *
 * Generation values are diagnostic payload epochs only. They never guard a put
 * or make a stale release safe: production has no per-slot generation check.
 */
enum {
	HANDOFF_SLOT = 63,
	HANDOFF_REPEATS = 24,
	HANDOFF_OWNER_NONE = 0,
	HANDOFF_OWNER_PRODUCER = 1,
	HANDOFF_OWNER_CONSUMER = 2,
};

struct generation_handoff {
	atomic64_t free_mask;
	atomic_t state;
	_Atomic unsigned int references;
	_Atomic unsigned int owner_generation;
	_Atomic unsigned int final_puts[2];
	_Atomic unsigned int final_owner[2];
	_Atomic unsigned int completions[2];
	_Atomic unsigned int publication_attempts[2];
	_Atomic unsigned int accepted_publications[2];
	_Atomic int ready_current;
	_Atomic int failed;
	_Atomic int first_release_done;
	_Atomic int blocked_retry_done;
	_Atomic int old_generation_done;
	_Atomic int new_published;
	_Atomic int new_consumer_done;
	pthread_barrier_t start;
	unsigned int old_generation;
	unsigned int new_generation;
	unsigned int released_generation;
	int old_codec_result;
	int new_codec_result;
	int producer_first;
	uint64_t payload_generation;
	uint64_t metadata;
};

static void generation_handoff_fail(struct generation_handoff *handoff,
				    const char *transition, int expected,
				    int observed)
{
	if (!atomic_exchange_explicit(&handoff->failed, 1,
					      memory_order_relaxed)) {
		unsigned int owner = atomic_load_explicit(&handoff->owner_generation,
							 memory_order_relaxed);
		int expected_terminal = owner == handoff->old_generation ?
			swapz_preparation_codec_result_state(handoff->old_codec_result) :
			owner == handoff->new_generation ?
			swapz_preparation_codec_result_state(handoff->new_codec_result) :
			SWAPZ_PREPARATION_EMPTY;

		fprintf(stderr, "preparation-handoff slot=%u old_gen=%u new_gen=%u "
			"owner_gen=%u refs=%u ready=%d transition=%s "
			"expected=%d observed=%d terminal_expected=%d "
			"terminal_observed=%d\n",
			HANDOFF_SLOT, handoff->old_generation, handoff->new_generation,
			owner, atomic_load_explicit(&handoff->references,
						 memory_order_relaxed),
			atomic_load_explicit(&handoff->ready_current,
						 memory_order_relaxed),
			transition, expected, observed, expected_terminal,
			swapz_preparation_read_state(&handoff->state));
	}
}

static uint64_t generation_metadata(unsigned int generation, int codec_result)
{
	return UINT64_C(0x6c39e1b700000000) ^
		((uint64_t)generation << 16) ^ (uint32_t)codec_result;
}

static void generation_wait_relaxed(const _Atomic int *flag)
{
	while (!atomic_load_explicit(flag, memory_order_relaxed))
		sched_yield();
}

/* Test-side model of refcount_dec_and_test() followed by the real slot return. */
static int generation_handoff_put(struct generation_handoff *handoff,
				  unsigned int epoch, unsigned int owner)
{
	unsigned int references;

	references = atomic_load_explicit(&handoff->references,
					 memory_order_relaxed);
	for (;;) {
		if (!references) {
			generation_handoff_fail(handoff, "put-without-reference", 1, 0);
			return -ESTALE;
		}
		if (atomic_compare_exchange_weak_explicit(&handoff->references,
				&references, references - 1U,
				memory_order_acq_rel, memory_order_relaxed))
			break;
	}
	if (references != 1U)
		return 0;
	if (atomic_fetch_add_explicit(&handoff->final_puts[epoch], 1,
					memory_order_relaxed) != 0)
		generation_handoff_fail(handoff, "duplicate-final-put", 0, 1);
	if (atomic_exchange_explicit(&handoff->final_owner[epoch], owner,
				     memory_order_relaxed) != HANDOFF_OWNER_NONE)
		generation_handoff_fail(handoff, "duplicate-final-owner",
					HANDOFF_OWNER_NONE, (int)owner);
	/*
	 * Plain released_generation must become visible to the next claimant
	 * through release_slot()/claim_slot(), not through a scheduling flag.
	 */
	handoff->released_generation = atomic_load_explicit(
		&handoff->owner_generation, memory_order_relaxed);
	atomic_store_explicit(&handoff->owner_generation, 0,
			      memory_order_relaxed);
	atomic_store_explicit(&handoff->state.value, SWAPZ_PREPARATION_EMPTY,
			      memory_order_relaxed);
	swapz_preparation_release_slot(&handoff->free_mask, HANDOFF_SLOT);
	return 1;
}

static int generation_handoff_publish(struct generation_handoff *handoff,
				      unsigned int epoch, unsigned int generation,
				      int codec_result)
{
	int previous_state;

	handoff->payload_generation = generation;
	handoff->metadata = generation_metadata(generation, codec_result);
	(void)atomic_fetch_add_explicit(&handoff->publication_attempts[epoch], 1,
					       memory_order_relaxed);
	if (codec_result >= 0)
		(void)atomic_fetch_add_explicit(&handoff->ready_current, 1,
					       memory_order_relaxed);
	previous_state = swapz_preparation_publish_codec_result(&handoff->state,
								 codec_result);
	if (previous_state == SWAPZ_PREPARATION_PREPARING) {
		(void)atomic_fetch_add_explicit(&handoff->accepted_publications[epoch],
					       1, memory_order_relaxed);
	} else {
		if (codec_result >= 0)
			(void)atomic_fetch_sub_explicit(&handoff->ready_current, 1,
					       memory_order_relaxed);
		if (previous_state != SWAPZ_PREPARATION_CANCELLED)
			generation_handoff_fail(handoff,
				"publish-preparing-to-terminal-or-cancelled",
				SWAPZ_PREPARATION_CANCELLED, previous_state);
	}
	return previous_state;
}

static void generation_handoff_consume(struct generation_handoff *handoff,
				       unsigned int epoch, unsigned int generation,
				       int codec_result)
{
	int expected_state = swapz_preparation_codec_result_state(codec_result);
	int observed_state = swapz_preparation_read_state(&handoff->state);

	/*
	 * The relaxed scheduling flag that led here is not a publication edge.
	 * These plain payload reads therefore depend on the terminal-state acquire.
	 */
	if (observed_state != expected_state ||
	    handoff->payload_generation != generation ||
	    handoff->metadata != generation_metadata(generation, codec_result) ||
	    atomic_load_explicit(&handoff->owner_generation,
				 memory_order_relaxed) != generation) {
		generation_handoff_fail(handoff, "acquire-terminal-and-payload",
					expected_state, observed_state);
		return;
	}
	if (observed_state == SWAPZ_PREPARATION_READY_COMPRESSED ||
	    observed_state == SWAPZ_PREPARATION_READY_RAW) {
		int consumed = swapz_preparation_consume_ready(&handoff->state);
		int ready_before;

		if (consumed != expected_state)
			generation_handoff_fail(handoff, "consume-ready-once",
						expected_state, consumed);
		ready_before = atomic_fetch_sub_explicit(&handoff->ready_current, 1,
							memory_order_relaxed);
		if (ready_before != 1)
			generation_handoff_fail(handoff, "ready-charge-consume",
						1, ready_before);
	}
	if (atomic_fetch_add_explicit(&handoff->completions[epoch], 1,
					 memory_order_relaxed) != 0)
		generation_handoff_fail(handoff, "duplicate-upper-completion", 0, 1);
}

static void *generation_old_producer(void *opaque)
{
	struct generation_handoff *handoff = opaque;
	int previous_state;

	(void)pthread_barrier_wait(&handoff->start);
	if (handoff->producer_first) {
		previous_state = generation_handoff_publish(
			handoff, 0, handoff->old_generation,
			handoff->old_codec_result);
		if (previous_state != SWAPZ_PREPARATION_PREPARING)
			generation_handoff_fail(handoff, "producer-first-publication",
						SWAPZ_PREPARATION_PREPARING,
						previous_state);
		if (generation_handoff_put(handoff, 0,
					   HANDOFF_OWNER_PRODUCER) != 0)
			generation_handoff_fail(handoff, "producer-first-put", 0, -1);
		atomic_store_explicit(&handoff->first_release_done, 1,
				      memory_order_relaxed);
		generation_wait_relaxed(&handoff->old_generation_done);
	} else {
		generation_wait_relaxed(&handoff->blocked_retry_done);
		previous_state = generation_handoff_publish(
			handoff, 0, handoff->old_generation,
			handoff->old_codec_result);
		if (previous_state != SWAPZ_PREPARATION_CANCELLED)
			generation_handoff_fail(handoff, "late-producer-after-cancel",
						SWAPZ_PREPARATION_CANCELLED,
						previous_state);
		if (generation_handoff_put(handoff, 0,
					   HANDOFF_OWNER_PRODUCER) != 1)
			generation_handoff_fail(handoff, "producer-final-put", 1, -1);
		atomic_store_explicit(&handoff->old_generation_done, 1,
				      memory_order_relaxed);
	}
	return NULL;
}

static void *generation_reclaimer(void *opaque)
{
	struct generation_handoff *handoff = opaque;
	int previous_state, slot;

	(void)pthread_barrier_wait(&handoff->start);
	generation_wait_relaxed(&handoff->first_release_done);
	/* One old reference remains, so retry cannot reuse the slot yet. */
	if (atomic_load_explicit(&handoff->references,
				 memory_order_relaxed) != 1U)
		generation_handoff_fail(handoff, "first-release-reference-count",
					1, (int)atomic_load_explicit(
						&handoff->references,
						memory_order_relaxed));
	slot = swapz_preparation_claim_slot(&handoff->free_mask);
	if (slot != -1)
		generation_handoff_fail(handoff, "premature-retry-claim", -1, slot);
	atomic_store_explicit(&handoff->blocked_retry_done, 1,
			      memory_order_relaxed);

	generation_wait_relaxed(&handoff->old_generation_done);
	slot = swapz_preparation_claim_slot(&handoff->free_mask);
	if (slot != HANDOFF_SLOT) {
		generation_handoff_fail(handoff, "reclaim-after-final-put",
					HANDOFF_SLOT, slot);
		return NULL;
	}
	/* The successful claim acquire must observe the old final owner's cleanup. */
	if (handoff->released_generation != handoff->old_generation ||
	    atomic_load_explicit(&handoff->references,
				 memory_order_relaxed) != 0U ||
	    atomic_load_explicit(&handoff->owner_generation,
				 memory_order_relaxed) != 0U ||
	    atomic_load_explicit(&handoff->ready_current,
				 memory_order_relaxed) != 0)
		generation_handoff_fail(handoff, "reuse-acquires-final-cleanup",
					(int)handoff->old_generation,
					(int)handoff->released_generation);

	atomic_store_explicit(&handoff->references, 2, memory_order_relaxed);
	atomic_store_explicit(&handoff->owner_generation,
			      handoff->new_generation, memory_order_relaxed);
	atomic_store_explicit(&handoff->state.value,
			      SWAPZ_PREPARATION_PREPARING,
			      memory_order_relaxed);
	previous_state = generation_handoff_publish(
		handoff, 1, handoff->new_generation, handoff->new_codec_result);
	if (previous_state != SWAPZ_PREPARATION_PREPARING)
		generation_handoff_fail(handoff, "new-producer-publication",
					SWAPZ_PREPARATION_PREPARING,
					previous_state);
	if (generation_handoff_put(handoff, 1,
				   HANDOFF_OWNER_PRODUCER) != 0)
		generation_handoff_fail(handoff, "new-producer-put", 0, -1);
	atomic_store_explicit(&handoff->new_published, 1,
			      memory_order_relaxed);

	generation_wait_relaxed(&handoff->new_consumer_done);
	slot = swapz_preparation_claim_slot(&handoff->free_mask);
	if (slot != HANDOFF_SLOT) {
		generation_handoff_fail(handoff, "reclaim-after-new-final-put",
					HANDOFF_SLOT, slot);
		return NULL;
	}
	if (handoff->released_generation != handoff->new_generation ||
	    atomic_load_explicit(&handoff->references,
				 memory_order_relaxed) != 0U ||
	    atomic_load_explicit(&handoff->owner_generation,
				 memory_order_relaxed) != 0U ||
	    atomic_load_explicit(&handoff->ready_current,
				 memory_order_relaxed) != 0)
		generation_handoff_fail(handoff, "new-reuse-acquires-final-cleanup",
					(int)handoff->new_generation,
					(int)handoff->released_generation);
	swapz_preparation_release_slot(&handoff->free_mask, HANDOFF_SLOT);
	return NULL;
}

static int test_generation_handoff_after_cancel_or_completion(void)
{
	static const int old_results[] = { 2048, 0, -EIO };
	static const int new_results[] = { -EIO, 2048, 0 };
	unsigned int iteration, case_index, order;

	for (order = 0; order < 2U; ++order) {
		for (case_index = 0; case_index < 3U; ++case_index) {
			for (iteration = 0; iteration < HANDOFF_REPEATS; ++iteration) {
				struct generation_handoff handoff = { 0 };
				pthread_t producer, reclaimer;
				unsigned int epoch;
				int retired, slot;

				handoff.producer_first = (int)order;
				handoff.old_generation = iteration * 2U + 1U;
				handoff.new_generation = handoff.old_generation + 1U;
				handoff.old_codec_result = old_results[case_index];
				handoff.new_codec_result = new_results[case_index];
				atomic_init(&handoff.free_mask.value,
					    (s64)(1ULL << HANDOFF_SLOT));
				atomic_init(&handoff.state.value, SWAPZ_PREPARATION_EMPTY);
				atomic_init(&handoff.references, 2);
				atomic_init(&handoff.owner_generation,
					    handoff.old_generation);
				atomic_init(&handoff.ready_current, 0);
				atomic_init(&handoff.failed, 0);
				atomic_init(&handoff.first_release_done, 0);
				atomic_init(&handoff.blocked_retry_done, 0);
				atomic_init(&handoff.old_generation_done, 0);
				atomic_init(&handoff.new_published, 0);
				atomic_init(&handoff.new_consumer_done, 0);
				for (epoch = 0; epoch < 2U; ++epoch) {
					atomic_init(&handoff.final_puts[epoch], 0);
					atomic_init(&handoff.final_owner[epoch],
						    HANDOFF_OWNER_NONE);
					atomic_init(&handoff.completions[epoch], 0);
					atomic_init(&handoff.publication_attempts[epoch], 0);
					atomic_init(&handoff.accepted_publications[epoch], 0);
				}
				slot = swapz_preparation_claim_slot(&handoff.free_mask);
				CHECK(slot == HANDOFF_SLOT);
				atomic_store_explicit(&handoff.state.value,
						      SWAPZ_PREPARATION_PREPARING,
						      memory_order_relaxed);
				CHECK(pthread_barrier_init(&handoff.start, NULL, 3) == 0);
				CHECK(pthread_create(&producer, NULL,
						     generation_old_producer,
						     &handoff) == 0);
				CHECK(pthread_create(&reclaimer, NULL,
						     generation_reclaimer,
						     &handoff) == 0);

				(void)pthread_barrier_wait(&handoff.start);
				if (!handoff.producer_first) {
					/*
					 * Production error completion retires PREPARING before
					 * dropping the consumer reference. The late producer
					 * must then lose its publication CAS to CANCELLED.
					 */
					retired = swapz_preparation_retire(&handoff.state);
					if (retired != SWAPZ_PREPARATION_CANCELLED)
						generation_handoff_fail(&handoff,
							"cancel-preparing-before-put",
							SWAPZ_PREPARATION_CANCELLED,
							retired);
					if (atomic_fetch_add_explicit(
						    &handoff.completions[0], 1,
						    memory_order_relaxed) != 0)
						generation_handoff_fail(&handoff,
							"duplicate-cancel-completion", 0, 1);
					if (generation_handoff_put(
						    &handoff, 0,
						    HANDOFF_OWNER_CONSUMER) != 0)
						generation_handoff_fail(&handoff,
							"cancel-first-put", 0, -1);
					atomic_store_explicit(
						&handoff.first_release_done, 1,
						memory_order_relaxed);
				}

				generation_wait_relaxed(&handoff.blocked_retry_done);
				if (handoff.producer_first) {
					generation_handoff_consume(
						&handoff, 0, handoff.old_generation,
						handoff.old_codec_result);
					if (generation_handoff_put(
						    &handoff, 0,
						    HANDOFF_OWNER_CONSUMER) != 1)
						generation_handoff_fail(&handoff,
							"consumer-final-put", 1, -1);
					atomic_store_explicit(
						&handoff.old_generation_done, 1,
						memory_order_relaxed);
				} else {
					generation_wait_relaxed(
						&handoff.old_generation_done);
				}

				generation_wait_relaxed(&handoff.new_published);
				/* The new producer still owns one ref: no early reuse. */
				slot = swapz_preparation_claim_slot(&handoff.free_mask);
				if (slot != -1)
					generation_handoff_fail(&handoff,
							"retry-before-new-consumer-put",
							-1, slot);
				generation_handoff_consume(
					&handoff, 1, handoff.new_generation,
					handoff.new_codec_result);
				if (generation_handoff_put(
					    &handoff, 1,
					    HANDOFF_OWNER_CONSUMER) != 1)
					generation_handoff_fail(&handoff,
							"new-consumer-final-put", 1, -1);
				atomic_store_explicit(&handoff.new_consumer_done, 1,
						      memory_order_relaxed);

				CHECK(pthread_join(producer, NULL) == 0);
				CHECK(pthread_join(reclaimer, NULL) == 0);
				CHECK(pthread_barrier_destroy(&handoff.start) == 0);
				CHECK(!atomic_load_explicit(&handoff.failed,
							    memory_order_relaxed));
				CHECK(atomic_load(&handoff.final_puts[0]) == 1U);
				CHECK(atomic_load(&handoff.final_puts[1]) == 1U);
				CHECK(atomic_load(&handoff.final_owner[0]) ==
				      (handoff.producer_first ?
				       HANDOFF_OWNER_CONSUMER :
				       HANDOFF_OWNER_PRODUCER));
				CHECK(atomic_load(&handoff.final_owner[1]) ==
				      HANDOFF_OWNER_CONSUMER);
				CHECK(atomic_load(&handoff.completions[0]) == 1U);
				CHECK(atomic_load(&handoff.completions[1]) == 1U);
				CHECK(atomic_load(&handoff.publication_attempts[0]) == 1U);
				CHECK(atomic_load(&handoff.publication_attempts[1]) == 1U);
				CHECK(atomic_load(&handoff.accepted_publications[0]) ==
				      (handoff.producer_first ? 1U : 0U));
				CHECK(atomic_load(&handoff.accepted_publications[1]) == 1U);
				CHECK(atomic_load(&handoff.ready_current) == 0);
				CHECK(atomic_load(&handoff.references) == 0U);
				CHECK(atomic_load(&handoff.owner_generation) == 0U);
				CHECK(swapz_preparation_read_state(&handoff.state) ==
				      SWAPZ_PREPARATION_EMPTY);
				CHECK((uint64_t)atomic64_read(&handoff.free_mask) ==
				      (1ULL << HANDOFF_SLOT));
			}
		}
	}
	return 0;
}

/*
 * Two terminal observers acquire the same READY state before either CAS.
 * The barrier only forces CAS contention between readers; it never serves as
 * a payload-publication edge. Only the successful claimant retires the ready
 * charge and accounts for the first modeled upper completion.
 */
enum { READY_COLLISION_SLOT = 63, READY_COLLISION_REPEATS = 64 };
struct ready_collision_context {
	atomic64_t free_mask;
	atomic_t state;
	_Atomic unsigned int references;
	_Atomic unsigned int ready_current;
	_Atomic unsigned int publications[2];
	_Atomic unsigned int completions[2];
	_Atomic int failed;
	pthread_barrier_t collision;
	int expected_ready_state;
	int retired_states[2];
	unsigned int acquire_reads[2];
	unsigned int failed_cas[2];
};

struct ready_collision_argument {
	struct ready_collision_context *context;
	unsigned int contender;
};

static void ready_collision_fail(struct ready_collision_context *context,
				 const char *phase, const char *cause,
				 int expected, int observed)
{
	if (!atomic_exchange_explicit(&context->failed, 1,
					      memory_order_relaxed))
		fprintf(stderr, "ready-collision slot=%u phase=%s cause=%s "
			"terminal=%d refs=%u expected=%d observed=%d "
			"publications_expected=1/1 publications_observed=%u/%u "
			"completions_expected=1/1 completions_observed=%u/%u ready=%u\n",
			READY_COLLISION_SLOT, phase, cause,
			swapz_preparation_read_state(&context->state),
			atomic_load_explicit(&context->references,
					     memory_order_relaxed),
			expected, observed,
			atomic_load_explicit(&context->publications[0],
					     memory_order_relaxed),
			atomic_load_explicit(&context->publications[1],
					     memory_order_relaxed),
			atomic_load_explicit(&context->completions[0],
					     memory_order_relaxed),
			atomic_load_explicit(&context->completions[1],
					     memory_order_relaxed),
			atomic_load_explicit(&context->ready_current,
					     memory_order_relaxed));
}

static void *ready_collision_contender(void *opaque)
{
	const struct ready_collision_argument *argument = opaque;
	struct ready_collision_context *context = argument->context;
	struct ready_collision_hook hook = {
		.state = &context->state,
		.collision = &context->collision,
		.expected_ready_state = context->expected_ready_state,
		.replacement_state = SWAPZ_PREPARATION_CONSUMED,
	};
	const unsigned int contender = argument->contender;
	int retired;

	ready_collision = &hook;
	retired = contender == 0 ? swapz_preparation_retire(&context->state) :
		swapz_preparation_consume_ready(&context->state);
	ready_collision = NULL;
	context->retired_states[contender] = retired;
	context->acquire_reads[contender] = hook.acquire_reads;
	context->failed_cas[contender] = hook.failed_cas;
	if (retired == context->expected_ready_state) {
		unsigned int previous_ready = atomic_fetch_sub_explicit(
			&context->ready_current, 1, memory_order_relaxed);

		if (previous_ready != 1U)
			ready_collision_fail(context, "ready-retirement",
				"ready-charge-not-unique", 1, (int)previous_ready);
		if (atomic_fetch_add_explicit(&context->completions[0], 1,
					      memory_order_relaxed) != 0)
			ready_collision_fail(context, "upper-completion",
				"multiple-ready-owners", 0, 1);
	} else if (retired != SWAPZ_PREPARATION_CONSUMED) {
		ready_collision_fail(context, "losing-ready-claim",
			"unexpected-terminal", SWAPZ_PREPARATION_CONSUMED, retired);
	}
	return NULL;
}

static int test_simultaneous_ready_retirement_and_slot_reuse(void)
{
	static const int ready_results[] = { 2048, 0 };
	unsigned int case_index, iteration;

	for (case_index = 0; case_index < 2U; ++case_index) {
		for (iteration = 0; iteration < READY_COLLISION_REPEATS; ++iteration) {
			struct ready_collision_context context = { 0 };
			struct ready_collision_argument arguments[2];
			pthread_t contenders[2];
			unsigned int contender, winner, loser;
			int slot, previous;

			atomic_init(&context.free_mask.value,
				    (s64)(1ULL << READY_COLLISION_SLOT));
			atomic_init(&context.state.value, SWAPZ_PREPARATION_EMPTY);
			atomic_init(&context.references, 2);
			atomic_init(&context.ready_current, 0);
			atomic_init(&context.publications[0], 0);
			atomic_init(&context.publications[1], 0);
			atomic_init(&context.completions[0], 0);
			atomic_init(&context.completions[1], 0);
			atomic_init(&context.failed, 0);
			context.expected_ready_state =
				swapz_preparation_codec_result_state(
					ready_results[case_index]);
			slot = swapz_preparation_claim_slot(&context.free_mask);
			CHECK(slot == READY_COLLISION_SLOT);
			atomic_store_explicit(&context.state.value,
					      SWAPZ_PREPARATION_PREPARING,
					      memory_order_relaxed);
			/* Producer charges readiness before terminal publication. */
			(void)atomic_fetch_add_explicit(&context.ready_current, 1,
							 memory_order_relaxed);
			previous = swapz_preparation_publish_codec_result(
				&context.state, ready_results[case_index]);
			CHECK(previous == SWAPZ_PREPARATION_PREPARING);
			(void)atomic_fetch_add_explicit(&context.publications[0], 1,
							 memory_order_relaxed);
			/* Producer put leaves the ordered owner holding the final ref. */
			CHECK(atomic_fetch_sub_explicit(&context.references, 1,
					memory_order_acq_rel) == 2U);
			CHECK(pthread_barrier_init(&context.collision, NULL, 2) == 0);
			for (contender = 0; contender < 2; ++contender) {
				arguments[contender].context = &context;
				arguments[contender].contender = contender;
				CHECK(pthread_create(&contenders[contender], NULL,
						     ready_collision_contender,
						     &arguments[contender]) == 0);
			}
			for (contender = 0; contender < 2; ++contender)
				CHECK(pthread_join(contenders[contender], NULL) == 0);
			CHECK(pthread_barrier_destroy(&context.collision) == 0);
			winner = context.retired_states[0] ==
				 context.expected_ready_state ? 0U : 1U;
			loser = winner ^ 1U;
			if (context.retired_states[winner] != context.expected_ready_state ||
			    context.retired_states[loser] != SWAPZ_PREPARATION_CONSUMED ||
			    context.acquire_reads[winner] != 1U ||
			    context.acquire_reads[loser] != 2U ||
			    context.failed_cas[winner] != 0U ||
			    context.failed_cas[loser] != 1U ||
			    atomic_load_explicit(&context.ready_current,
						 memory_order_relaxed) != 0U ||
			    atomic_load_explicit(&context.completions[0],
						 memory_order_relaxed) != 1U ||
			    swapz_preparation_read_state(&context.state) !=
				    SWAPZ_PREPARATION_CONSUMED)
				ready_collision_fail(&context, "ready-CAS-collision",
					"double-consume-or-missing-reread", 1,
					(int)atomic_load_explicit(
						&context.completions[0],
						memory_order_relaxed));
			CHECK(swapz_preparation_claim_slot(&context.free_mask) == -1);
			CHECK(atomic_load_explicit(&context.references,
						  memory_order_relaxed) == 1U);
			CHECK(atomic_fetch_sub_explicit(&context.references, 1,
					memory_order_acq_rel) == 1U);
			atomic_store_explicit(&context.state.value,
					      SWAPZ_PREPARATION_EMPTY,
					      memory_order_relaxed);
			swapz_preparation_release_slot(&context.free_mask,
						       READY_COLLISION_SLOT);
			slot = swapz_preparation_claim_slot(&context.free_mask);
			if (slot != READY_COLLISION_SLOT ||
			    swapz_preparation_read_state(&context.state) !=
				    SWAPZ_PREPARATION_EMPTY)
				ready_collision_fail(&context, "immediate-reuse",
					"state-not-cleared-after-final-put",
					READY_COLLISION_SLOT, slot);
			/* A negative codec result in the reused slot remains ERROR. */
			atomic_store_explicit(&context.references, 2,
					      memory_order_relaxed);
			atomic_store_explicit(&context.state.value,
					      SWAPZ_PREPARATION_PREPARING,
					      memory_order_relaxed);
			previous = swapz_preparation_publish_codec_result(
				&context.state, -EIO);
			if (previous == SWAPZ_PREPARATION_PREPARING)
				(void)atomic_fetch_add_explicit(
					&context.publications[1], 1,
					memory_order_relaxed);
			if (previous != SWAPZ_PREPARATION_PREPARING ||
			    swapz_preparation_read_state(&context.state) !=
				    SWAPZ_PREPARATION_ERROR ||
			    swapz_preparation_retire(&context.state) !=
				    SWAPZ_PREPARATION_ERROR ||
			    swapz_preparation_consume_ready(&context.state) !=
				    SWAPZ_PREPARATION_ERROR)
				ready_collision_fail(&context, "reused-error-publication",
					"error-converted-to-ready",
					SWAPZ_PREPARATION_ERROR,
					swapz_preparation_read_state(&context.state));
			/* ERROR completes the new BIO only through its ordered owner. */
			(void)atomic_fetch_add_explicit(&context.completions[1], 1,
							 memory_order_relaxed);
			CHECK(swapz_preparation_claim_slot(&context.free_mask) == -1);
			CHECK(atomic_fetch_sub_explicit(&context.references, 1,
					memory_order_acq_rel) == 2U);
			CHECK(swapz_preparation_claim_slot(&context.free_mask) == -1);
			CHECK(atomic_fetch_sub_explicit(&context.references, 1,
					memory_order_acq_rel) == 1U);
			atomic_store_explicit(&context.state.value,
					      SWAPZ_PREPARATION_EMPTY,
					      memory_order_relaxed);
			swapz_preparation_release_slot(&context.free_mask,
						       READY_COLLISION_SLOT);
			CHECK((uint64_t)atomic64_read(&context.free_mask) ==
			      (1ULL << READY_COLLISION_SLOT));
			if (atomic_load_explicit(&context.publications[0],
						 memory_order_relaxed) != 1U ||
			    atomic_load_explicit(&context.publications[1],
						 memory_order_relaxed) != 1U ||
			    atomic_load_explicit(&context.completions[0],
						 memory_order_relaxed) != 1U ||
			    atomic_load_explicit(&context.completions[1],
						 memory_order_relaxed) != 1U)
				ready_collision_fail(&context, "final-counts",
					"publication-or-completion-not-once", 1,
					(int)atomic_load_explicit(
						&context.completions[1],
						memory_order_relaxed));
			CHECK(!atomic_load_explicit(&context.failed,
						   memory_order_relaxed));
		}
	}
	return 0;
}

int main(void)
{
	CHECK(!test_representation_race());
	CHECK(!test_terminal_failure_retires_preparation_result());
	CHECK(!test_ready_publication_wins_raw_cas());
	CHECK(!test_thread_published_terminal_metadata_after_failed_cas());
	CHECK(!test_closed_admission_suppresses_producer_owner_wake());
	CHECK(!test_production_failure_and_wake_gates());
	CHECK(!test_capacity_high_bit_and_reuse());
	CHECK(!test_two_producers_reclaim_only_after_final_consumer());
	CHECK(!test_concurrent_reuse());
	CHECK(!test_generation_handoff_after_cancel_or_completion());
	CHECK(!test_simultaneous_ready_retirement_and_slot_reuse());
	puts("SWAPZ_PREPARATION_SLOTS_PASS=11");
	return 0;
}
