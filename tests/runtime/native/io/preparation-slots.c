// SPDX-License-Identifier: GPL-2.0-only
/* Run the production slot algorithm with C11 atomic operations. This is not
 * a Linux memory-model proof or a substitute for loaded BIO/drain coverage. */
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>

typedef int64_t s64;
typedef struct { _Atomic int64_t value; } atomic64_t;
typedef struct { _Atomic int value; } atomic_t;

static int atomic_read(atomic_t *value)
{
	return atomic_load_explicit(&value->value, memory_order_relaxed);
}

static int atomic_read_acquire(const atomic_t *value)
{
	return atomic_load_explicit(&value->value, memory_order_acquire);
}

static int atomic_cmpxchg(atomic_t *value, int old, int replacement)
{
	atomic_compare_exchange_strong_explicit(&value->value, &old, replacement,
			memory_order_seq_cst, memory_order_acquire);
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

#define TRANSFERS 8192U
static struct {
	atomic64_t mask;
	atomic_uint ready[SWAPZ_MAX_RECORDS];
	uint64_t bytes[SWAPZ_MAX_RECORDS][16];
	atomic_int failed;
} exchange;

static void *produce(void *unused)
{
	unsigned int sequence, i;

	(void)unused;
	for (sequence = 1; sequence <= TRANSFERS; ++sequence) {
		int slot;

		while ((slot = swapz_preparation_claim_slot(&exchange.mask)) < 0) {
			if (atomic_load(&exchange.failed))
				return NULL;
			sched_yield();
		}
		for (i = 0; i < 16; ++i)
			exchange.bytes[slot][i] = (uint64_t)sequence * 17U + i;
		atomic_store_explicit(&exchange.ready[slot], sequence,
				      memory_order_release);
	}
	return NULL;
}

static void *consume(void *unused)
{
	unsigned int completed = 0, slot, i;
	unsigned char seen[TRANSFERS] = { 0 };

	(void)unused;
	while (completed < TRANSFERS && !atomic_load(&exchange.failed)) {
		for (slot = 0; slot < SWAPZ_MAX_RECORDS; ++slot) {
			unsigned int sequence = atomic_load_explicit(
				&exchange.ready[slot], memory_order_acquire);

			if (!sequence)
				continue;
			if (sequence > TRANSFERS || seen[sequence - 1]) {
				atomic_store(&exchange.failed, 1);
				return NULL;
			}
			seen[sequence - 1] = 1;
			for (i = 0; i < 16; ++i) {
				if (exchange.bytes[slot][i] !=
				    (uint64_t)sequence * 17U + i) {
					atomic_store(&exchange.failed, 1);
					return NULL;
				}
			}
			atomic_store_explicit(&exchange.ready[slot], 0,
					      memory_order_relaxed);
			swapz_preparation_release_slot(&exchange.mask, slot);
			completed++;
		}
		sched_yield();
	}
	return NULL;
}

static int test_concurrent_reuse(void)
{
	pthread_t producer, consumer;
	unsigned int i;

	atomic_init(&exchange.mask.value, (s64)SWAPZ_PREPARATION_FREE_MASK);
	atomic_init(&exchange.failed, 0);
	for (i = 0; i < SWAPZ_MAX_RECORDS; ++i)
		atomic_init(&exchange.ready[i], 0);
	CHECK(pthread_create(&producer, NULL, produce, NULL) == 0);
	CHECK(pthread_create(&consumer, NULL, consume, NULL) == 0);
	CHECK(pthread_join(producer, NULL) == 0);
	CHECK(pthread_join(consumer, NULL) == 0);
	CHECK(!atomic_load(&exchange.failed));
	CHECK((uint64_t)atomic64_read(&exchange.mask) ==
	      SWAPZ_PREPARATION_FREE_MASK);
	for (i = 0; i < SWAPZ_MAX_RECORDS; ++i)
		CHECK(!atomic_load(&exchange.ready[i]));
	return 0;
}

int main(void)
{
	CHECK(!test_representation_race());
	CHECK(!test_capacity_high_bit_and_reuse());
	CHECK(!test_concurrent_reuse());
	puts("SWAPZ_PREPARATION_SLOTS_PASS=3");
	return 0;
}
