/* SPDX-License-Identifier: GPL-2.0-only */
/* Original pinned zswap helper extraction with host ABI shim, NOT kernel execution. */
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <openssl/sha.h>
#include <pthread.h>
#include <stdalign.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "zswap-original-ticket.h"

typedef swapz_u64 u64;
typedef swapz_u32 u32;
typedef swapz_u8 u8;
typedef int64_t s64;
#define S64_MAX INT64_MAX
typedef struct { _Atomic(int64_t) value; } atomic64_t;
static s64 atomic64_read(const atomic64_t *counter)
{
	return atomic_load_explicit(&counter->value, memory_order_relaxed);
}
static bool atomic64_try_cmpxchg(atomic64_t *counter, s64 *expected, s64 next)
{
	return atomic_compare_exchange_strong_explicit(&counter->value, expected,
		next, memory_order_acq_rel, memory_order_relaxed);
}
static void sha256(const void *bytes, size_t length, u8 digest[32])
{
	(void)SHA256(bytes, length, digest);
}

/* These definitions come from exact staged original mm/zswap.c, never a model. */
#include "r091-extracted-functions.h"

static unsigned int checks;
#define CHECK(condition, witness) do { \
	++checks; \
	if (!(condition)) { \
		fprintf(stderr, "R091_FIRST_ERROR %s line=%d\n", witness, __LINE__); \
		return 77; \
	} \
} while (0)

struct race_context {
	atomic64_t *sequence;
	pthread_barrier_t *barrier;
	u64 result;
};
static void *race_once(void *opaque)
{
	struct race_context *context = opaque;
	int error = pthread_barrier_wait(context->barrier);
	if (error && error != PTHREAD_BARRIER_SERIAL_THREAD)
		return NULL;
	context->result = swapz_mm_next(context->sequence);
	return NULL;
}

static unsigned int delayed_eviction_trace(unsigned int stores, unsigned int lag)
{
	unsigned int hits = 0;
	u8 compressed[64];
	u8 decoded[4096];
	struct swapz_ticket_key key;
	memset(compressed, 0x6d, sizeof(compressed));
	memset(decoded, 0x29, sizeof(decoded));
	for (unsigned int store_sequence = 1; store_sequence <= stores; ++store_sequence) {
		if (store_sequence > lag) {
			u64 original_sequence = (u64)store_sequence - lag;
			if (swapz_mm_eviction_key(&key, original_sequence, 1U,
			    original_sequence, 1U, SWAPZ_TICKET_LZ4,
			    (u32)sizeof(compressed), compressed, decoded))
				++hits;
		}
	}
	return hits;
}

int main(void)
{
	u8 compressed[64], decoded[4096], expected_digest[32];
	struct swapz_ticket_key source_key = {0}, stale_key, reused_key;
	struct swapz_ticket_broker broker = {0};
	struct swapz_ticket_slot slots[1];
	swapz_u32 free_indices[1];
	alignas(64) swapz_u8 broker_payload[3584];
	struct swapz_ticket_ref lease = {0}, refused = {0};
	struct swapz_ticket_view view = {0};
	atomic64_t counter = {0};
	pthread_mutex_t incoming_lock = PTHREAD_MUTEX_INITIALIZER;
	pthread_barrier_t race_barrier;
	pthread_t first_thread, second_thread;
	struct race_context first = {.sequence = &counter, .barrier = &race_barrier};
	struct race_context second = {.sequence = &counter, .barrier = &race_barrier};
	clock_t started, finished;
	unsigned int lag64, lag256, lag1024;

	memset(compressed, 0x6d, sizeof(compressed));
	memset(decoded, 0x29, sizeof(decoded));
	(void)SHA256(decoded, sizeof(decoded), expected_digest);

	CHECK(swapz_mm_pool_codec("lz4") == SWAPZ_TICKET_LZ4, "pool_lz4");
	CHECK(swapz_mm_pool_codec("lzo") == SWAPZ_TICKET_LZO1X, "pool_lzo");
	CHECK(swapz_mm_pool_codec("zstd") == 0U, "pool_unknown");
	CHECK(swapz_mm_pool_codec(NULL) == 0U, "pool_null");
	CHECK(swapz_mm_profile("lz4", "lz4-scomp") == SWAPZ_TICKET_LZ4, "store_lz4");
	CHECK(swapz_mm_profile("lzo", "lzo-scomp") == SWAPZ_TICKET_LZO1X, "store_lzo");
	CHECK(swapz_mm_profile("lz4", "different-driver") == 0U, "store_driver_mismatch");
	CHECK(swapz_mm_profile("zstd", "zstd-scomp") == 0U, "store_unknown");

	CHECK(!swapz_mm_eviction_key(&source_key, 0, 1, 42, 1, SWAPZ_TICKET_LZ4,
		(u32)sizeof(compressed), compressed, decoded), "bad_sequence");
	CHECK(!swapz_mm_eviction_key(&source_key, 1, 0, 42, 1, SWAPZ_TICKET_LZ4,
		(u32)sizeof(compressed), compressed, decoded), "bad_area");
	CHECK(!swapz_mm_eviction_key(&source_key, 1, 1, 42, 1, 99,
		(u32)sizeof(compressed), compressed, decoded), "bad_codec");
	CHECK(!swapz_mm_eviction_key(&source_key, 1, 1, 42, 1, SWAPZ_TICKET_LZ4,
		0, compressed, decoded), "zero_length");
	CHECK(!swapz_mm_eviction_key(&source_key, 1, 1, 42, 1, SWAPZ_TICKET_LZ4,
		4096, compressed, decoded), "oversize_length");
	CHECK(!swapz_mm_eviction_key(&source_key, 1, 1, 42, 1, SWAPZ_TICKET_LZ4,
		(u32)sizeof(compressed), NULL, decoded), "null_stream");
	CHECK(!swapz_mm_eviction_key(&source_key, 1, 1, 42, 1, SWAPZ_TICKET_LZ4,
		(u32)sizeof(compressed), compressed, NULL), "null_decoded");
	CHECK(!swapz_mm_eviction_key(NULL, 1, 1, 42, 1, SWAPZ_TICKET_LZ4,
		(u32)sizeof(compressed), compressed, decoded), "null_destination");

	CHECK(swapz_mm_eviction_key(&source_key, 1, 1, 42, 1, SWAPZ_TICKET_LZ4,
		(u32)sizeof(compressed), compressed, decoded), "valid_source");
	CHECK(source_key.length == sizeof(compressed) &&
	      source_key.decoded_length == 4096 &&
	      source_key.store_sequence == 1 && source_key.area_epoch == 1 &&
	      source_key.slot_offset == 42 && source_key.swap_type == 1 &&
	      source_key.representation == SWAPZ_TICKET_ORIGINAL &&
	      source_key.codec == SWAPZ_TICKET_LZ4 &&
	      source_key.version == 1 && !source_key.dictionary, "source_identity");
	CHECK(source_key.crc == swapz_crc32c_bytes(compressed,
		(u32)sizeof(compressed)), "crc_compare");
	CHECK(!memcmp(source_key.sha256, expected_digest, sizeof(expected_digest)),
		"sha_compare");
	compressed[0] ^= 0x55U;
	CHECK(swapz_mm_eviction_key(&reused_key, 2, 1, 42, 1, SWAPZ_TICKET_LZ4,
		(u32)sizeof(compressed), compressed, decoded), "reused_source");
	CHECK(reused_key.store_sequence == 2 && reused_key.crc != source_key.crc,
		"source_reuse_crc");
	decoded[0] ^= 0x33U;
	CHECK(swapz_mm_eviction_key(&reused_key, 3, 1, 42, 1, SWAPZ_TICKET_LZ4,
		(u32)sizeof(compressed), compressed, decoded), "changed_page");
	CHECK(memcmp(reused_key.sha256, source_key.sha256, sizeof(source_key.sha256)),
		"changed_page_digest");
	compressed[0] ^= 0x55U;
	decoded[0] ^= 0x33U;

	CHECK(swapz_mm_next(&counter) == 1U, "sequence_first");
	atomic_store(&counter.value, INT64_MAX - 1);
	CHECK(swapz_mm_next(&counter) == (u64)INT64_MAX, "sequence_last");
	CHECK(swapz_mm_next(&counter) == 0U, "sequence_exhaustion");
	atomic_store(&counter.value, 0);
	CHECK(!pthread_barrier_init(&race_barrier, NULL, 2), "barrier_init");
	CHECK(!pthread_create(&first_thread, NULL, race_once, &first), "thread_first");
	CHECK(!pthread_create(&second_thread, NULL, race_once, &second), "thread_second");
	CHECK(!pthread_join(first_thread, NULL), "join_first");
	CHECK(!pthread_join(second_thread, NULL), "join_second");
	CHECK((first.result || second.result) &&
	      (!first.result || !second.result || first.result != second.result),
	      "concurrent_unique_generation");
	CHECK(!pthread_barrier_destroy(&race_barrier), "barrier_destroy");

	source_key.target_session = 17;
	source_key.table_epoch = 20;
	source_key.target_epoch = 21;
	source_key.logical_page = 42;
	source_key.dm_generation = 22;
	CHECK(!swapz_ticket_init(&broker, slots, sizeof(slots), broker_payload,
		sizeof(broker_payload), free_indices, sizeof(free_indices),
		1, 3568, (u64)sizeof(compressed), 17, 20), "broker_init");
	CHECK(!swapz_ticket_reserve(&broker, &source_key, &lease), "broker_reserve");
	CHECK(swapz_ticket_reserve(&broker, &source_key, &refused) == -ENOSPC,
		"carrier_credit_exhaustion");
	CHECK(!swapz_ticket_seal(&lease, compressed, (u32)sizeof(compressed)),
		"seal_exact_stream");
	CHECK(!swapz_ticket_view(&lease, &view) &&
	      !memcmp(view.bytes, compressed, sizeof(compressed)), "sealed_bytes");
	stale_key = source_key;
	++stale_key.store_sequence;
	CHECK(!pthread_mutex_lock(&incoming_lock), "incoming_lock");
	CHECK(swapz_ticket_claim_under_queue_lock(&lease, &stale_key) == -ESTALE,
		"stale_generation_claim");
	stale_key = source_key;
	++stale_key.area_epoch;
	CHECK(swapz_ticket_claim_under_queue_lock(&lease, &stale_key) == -ESTALE,
		"stale_area_claim");
	CHECK(!swapz_ticket_claim_under_queue_lock(&lease, &source_key),
		"ordered_head_claim");
	CHECK(swapz_ticket_claim_under_queue_lock(&lease, &source_key) == -EALREADY,
		"duplicate_claim");
	CHECK(!pthread_mutex_unlock(&incoming_lock), "incoming_unlock");
	CHECK(!swapz_ticket_revoke(&broker, 21), "revoke");
	CHECK(!swapz_ticket_put(&lease), "final_put");
	CHECK(!swapz_ticket_close(&broker), "close");
	CHECK(!swapz_ticket_destroy(&broker), "destroy");
	CHECK(!pthread_mutex_destroy(&incoming_lock), "lock_destroy");

	started = clock();
	lag64 = delayed_eviction_trace(1024U, 64U);
	lag256 = delayed_eviction_trace(1024U, 256U);
	lag1024 = delayed_eviction_trace(2048U, 1024U);
	finished = clock();
	CHECK(lag64 == 960U && lag256 == 768U && lag1024 == 1024U,
		"delayed_eviction_provenance");
	CHECK(started != (clock_t)-1 && finished >= started, "host_trace_timer");
	printf("PASS_HOST_ONLY R091 checks=%u lag64=%u/960 lag256=%u/768 lag1024=%u/1024 cookie=%zu broker=%zu trace_cpu_seconds=%.9f\n",
	       checks, lag64, lag256, lag1024, sizeof(u64), sizeof(broker),
	       (double)(finished - started) / (double)CLOCKS_PER_SEC);
	return 0;
}
