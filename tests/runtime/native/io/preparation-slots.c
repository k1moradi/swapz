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
	/* Do not give Linux's failed-CAS path stronger ordering in this shim. */
	atomic_compare_exchange_strong_explicit(&value->value, &old, replacement,
			memory_order_seq_cst, memory_order_relaxed);
	if (value == publication.state && old != expected)
		publication.failed_cas++;
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

int main(void)
{
	CHECK(!test_representation_race());
	CHECK(!test_ready_publication_wins_raw_cas());
	CHECK(!test_thread_published_terminal_metadata_after_failed_cas());
	CHECK(!test_closed_admission_suppresses_producer_owner_wake());
	CHECK(!test_production_failure_and_wake_gates());
	CHECK(!test_capacity_high_bit_and_reuse());
	CHECK(!test_concurrent_reuse());
	puts("SWAPZ_PREPARATION_SLOTS_PASS=7");
	return 0;
}
