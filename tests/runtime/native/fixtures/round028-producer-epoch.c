/* Rootless source-extracted pinned MM monotonic allocation witness. */
#include <assert.h>
#include <limits.h>
#include <pthread.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
typedef int64_t s64;
typedef uint64_t u64;
typedef _Atomic int64_t atomic64_t;
#define ATOMIC64_INIT(number) ATOMIC_VAR_INIT(number)
#define atomic64_read(pointer) atomic_load(pointer)
static s64 atomic64_cmpxchg(atomic64_t *pointer, s64 previous, s64 next)
{
	atomic_compare_exchange_strong(pointer, &previous, next);
	return previous;
}
static atomic64_t swapz_round028_epoch_counter = ATOMIC64_INIT(0);
#define THREAD_COUNT 4U
#define PER_THREAD 256U
static u64 results[THREAD_COUNT * PER_THREAD];
struct worker_state { unsigned int worker_index; };
/* ROUND028_SOURCE_REAL_EPOCH_MINT */
static void *mint_worker(void *opaque)
{
	struct worker_state *state = opaque;
	unsigned int index;
	for (index = 0; index < PER_THREAD; ++index) {
		const u64 epoch = swapz_round028_epoch_mint();
		assert(epoch != 0U);
		results[state->worker_index * PER_THREAD + index] = epoch;
	}
	return NULL;
}
static int epoch_compare(const void *first, const void *second)
{
	const u64 a = *(const u64 *)first;
	const u64 b = *(const u64 *)second;
	return (a > b) - (a < b);
}
int main(void)
{
	pthread_t threads[THREAD_COUNT];
	struct worker_state states[THREAD_COUNT];
	unsigned int index;
	assert(swapz_round028_epoch_mint() == 1U);
	assert(swapz_round028_epoch_mint() == 2U);
	for (index = 0; index < THREAD_COUNT; ++index) {
		states[index].worker_index = index;
		assert(!pthread_create(&threads[index], NULL, mint_worker, &states[index]));
	}
	for (index = 0; index < THREAD_COUNT; ++index)
		assert(!pthread_join(threads[index], NULL));
	qsort(results, THREAD_COUNT * PER_THREAD, sizeof(results[0]), epoch_compare);
	for (index = 0; index < THREAD_COUNT * PER_THREAD; ++index)
		assert(results[index] == (u64)index + 3U);
	atomic_store(&swapz_round028_epoch_counter, LONG_MAX - 1);
	assert(swapz_round028_epoch_mint() == (u64)LONG_MAX);
	assert(swapz_round028_epoch_mint() == 0U);
	atomic_store(&swapz_round028_epoch_counter, -1);
	assert(swapz_round028_epoch_mint() == 0U);
	puts("ROUND028_EPOCH_SOURCE_REAL_MINT_PASS");
	return 0;
}
