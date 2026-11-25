/* SPDX-License-Identifier: GPL-2.0-only */
/* ABI shim only. Actual staged header/functions and real broker linked.
 * No Linux BIO/SG execution or source authentication implied. */
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>
#include <time.h>
#include "zswap-original-ticket.h"

typedef uint64_t sector_t;
typedef uint8_t u8;
struct block_device { unsigned int identity; };
struct page { unsigned int identity; };
struct bio_vec {
	struct page *bv_page;
	unsigned int bv_offset, bv_len;
};
struct bio {
	struct block_device *bi_bdev;
	struct {
		sector_t bi_sector;
		unsigned int bi_size, bi_idx, bi_offset;
	} bi_iter;
	unsigned int bi_vcnt, bi_opf, bi_flags;
	struct bio_vec *bi_io_vec;
	_Atomic(struct swapz_mm_carrier *) bi_swapz_original;
};
#define REQ_OP_WRITE 1U
#define REQ_SWAP 256U
#define BIO_CLONED 1U
#define BIO_REMAPPED 2U
static void gate_bio_op(void);
static unsigned int bio_op(const struct bio *bio) { gate_bio_op(); return bio->bi_opf & 255U; }
static bool bio_flagged(const struct bio *bio, unsigned int flag) { return !!(bio->bi_flags & flag); }

#define CONFIG_SWAPZ_ORIGINAL_MM_CARRIER_TEST 1
#include "r090-staged-carrier.h"


/* POSIX reader/writer gate is a test ABI shim, NOT native Linux RCU.
 * The exact staged candidate and release functions are extracted verbatim.
 */
static struct swapz_mm_carrier swapz_mm_carrier;
static atomic_int swapz_mm_busy;
static pthread_rwlock_t readers = PTHREAD_RWLOCK_INITIALIZER;
static pthread_barrier_t reader_arrived, reader_resume, writer_arrived;
static bool gate;
static _Thread_local bool reader_held;
static atomic_uint grace_calls;
struct work_struct { int unused; };
static void must(int error)
{
	if (error) {
		fprintf(stderr, "R090_FIRST_ERROR pthread=%d\n", error);
		exit(77);
	}
}
static void meet(pthread_barrier_t *barrier)
{
	int error = pthread_barrier_wait(barrier);
	if (error != PTHREAD_BARRIER_SERIAL_THREAD)
		must(error);
}
static void rcu_read_lock(void)
{
	must(pthread_rwlock_rdlock(&readers));
	reader_held = true;
}
static void rcu_read_unlock(void)
{
	reader_held = false;
	must(pthread_rwlock_unlock(&readers));
}
static struct swapz_mm_carrier *read_carrier(const _Atomic(struct swapz_mm_carrier *) *pointer)
{
	if (!reader_held) {
		fprintf(stderr, "R090_FIRST_ERROR reader not protected\n");
		exit(77);
	}
	return atomic_load_explicit(pointer, memory_order_acquire);
}
#define rcu_dereference(pointer) read_carrier(&(pointer))
static void synchronize_rcu(void)
{
	(void)atomic_fetch_add_explicit(&grace_calls, 1U, memory_order_relaxed);
	if (gate)
		meet(&writer_arrived);
	must(pthread_rwlock_wrlock(&readers));
	must(pthread_rwlock_unlock(&readers));
}
static void gate_bio_op(void)
{
	if (gate) {
		meet(&reader_arrived);
		meet(&reader_resume);
	}
}
#define WARN_ON_ONCE(condition) (!!(condition))
#define atomic_set_release(pointer, value) atomic_store_explicit((pointer), (value), memory_order_release)
#include "r090-staged-functions.h"

static unsigned int checks;
#define CHECK(condition) do { \
	++checks; \
	if (!(condition)) { fprintf(stderr, "R090_FIRST_ERROR line=%d %s\n", __LINE__, #condition); return 77; } \
} while (0)

struct reader_context {
	struct bio *origin;
	struct swapz_ticket_ref retained;
	int result;
};
static void *read_candidate(void *opaque)
{
	struct reader_context *context = opaque;
	context->result = swapz_mm_candidate_get(context->origin, &context->retained);
	return NULL;
}
static void *release_carrier(void *unused)
{
	(void)unused;
	swapz_mm_release_workfn(NULL);
	return NULL;
}

/* Exact source index/key helpers, deterministic no-contention store/eviction
 * trace. This is not a measured natural Linux reclaim distribution.
 */
static unsigned int trace(unsigned int lag)
{
	struct swapz_mm_source cells[SWAPZ_MM_SOURCE_SLOTS] = {0};
	struct swapz_ticket_key key;
	unsigned int hits = 0;
	for (unsigned int sequence = 1; sequence <= 1024U; ++sequence) {
		struct swapz_mm_source *source = &cells[swapz_mm_source_index(sequence)];
		*source = (struct swapz_mm_source){
			.cookie = sequence, .area_epoch = 1, .slot_offset = sequence,
			.swap_type = 1, .length = 64, .codec = SWAPZ_TICKET_LZ4
		};
		if (sequence > lag) {
			unsigned int victim = sequence - lag;
			if (swapz_mm_source_key(&cells[swapz_mm_source_index(victim)],
				victim, 1, victim, 1, 64, &key))
				++hits;
		}
	}
	return hits;
}

int main(void)
{
	struct swapz_ticket_broker broker = {0};
	struct swapz_ticket_slot slots[1];
	swapz_u32 indices[1];
	_Alignas(64) swapz_u8 payload[3584];
	swapz_u8 bytes[64];
	struct swapz_ticket_key key = {
		.area_epoch = 1, .store_sequence = 1, .slot_offset = 2,
		.target_session = 17, .table_epoch = 20, .target_epoch = 3,
		.logical_page = 4, .dm_generation = 5, .swap_type = 1,
		.length = 64, .decoded_length = 4096, .representation = SWAPZ_TICKET_ORIGINAL,
		.codec = SWAPZ_TICKET_LZ4, .version = 1
	};
	struct block_device device = {1};
	struct page page = {2};
	struct bio_vec vector = {&page, 0, 4096};
	struct bio origin = {
		.bi_bdev = &device, .bi_iter = {8, 4096, 0, 0},
		.bi_vcnt = 1, .bi_opf = REQ_OP_WRITE | REQ_SWAP, .bi_io_vec = &vector
	};
	struct swapz_ticket_ref retained = {0};
	struct swapz_ticket_view view = {0};
	struct reader_context context = {.origin = &origin};
	pthread_t reader, writer;
	unsigned int immediate, lag32, lag64, lag256;
	clock_t started, finished;

	memset(bytes, 0x5b, sizeof(bytes));
	memset(key.sha256, 0xa5, sizeof(key.sha256));
	key.crc = swapz_crc32c_bytes(bytes, sizeof(bytes));
	CHECK(!swapz_ticket_init(&broker, slots, sizeof(slots), payload, sizeof(payload),
		indices, sizeof(indices), 1, 3568, sizeof(bytes), 17, 20));
	CHECK(swapz_mm_candidate_get(&origin, &retained) == -EOPNOTSUPP);
	CHECK(!swapz_ticket_broker_try_get(&broker, 17, 20, &swapz_mm_carrier.cap));
	CHECK(!swapz_ticket_reserve(&broker, &key, &swapz_mm_carrier.lease));
	CHECK(!swapz_ticket_seal(&swapz_mm_carrier.lease, bytes, sizeof(bytes)));
	swapz_mm_carrier.bdev = &device;
	swapz_mm_carrier.page = &page;
	swapz_mm_carrier.sector = 8;
	atomic_store(&swapz_mm_busy, 1);
	atomic_store(&origin.bi_swapz_original, &swapz_mm_carrier);
	CHECK(!swapz_mm_candidate_get(&origin, &retained));
	atomic_store(&origin.bi_swapz_original, NULL);
	swapz_mm_release_workfn(NULL);
	CHECK(atomic_load(&grace_calls) == 1U);
	CHECK(!atomic_load(&swapz_mm_busy));
	CHECK(!swapz_mm_carrier.lease.broker && !swapz_mm_carrier.cap.broker);
	CHECK(!swapz_ticket_view(&retained, &view) && !memcmp(view.bytes, bytes, sizeof(bytes)));
	CHECK(!swapz_ticket_put(&retained));

	/* A live reader has seen the carrier but has not retained its ticket.
	 * Terminal clears the borrow and deferred work must wait for reader exit.
	 */
	++key.store_sequence;
	CHECK(!swapz_ticket_broker_try_get(&broker, 17, 20, &swapz_mm_carrier.cap));
	CHECK(!swapz_ticket_reserve(&broker, &key, &swapz_mm_carrier.lease));
	CHECK(!swapz_ticket_seal(&swapz_mm_carrier.lease, bytes, sizeof(bytes)));
	swapz_mm_carrier.bdev = &device;
	swapz_mm_carrier.page = &page;
	swapz_mm_carrier.sector = 8;
	atomic_store(&swapz_mm_busy, 1);
	atomic_store(&origin.bi_swapz_original, &swapz_mm_carrier);
	must(pthread_barrier_init(&reader_arrived, NULL, 2));
	must(pthread_barrier_init(&reader_resume, NULL, 2));
	must(pthread_barrier_init(&writer_arrived, NULL, 2));
	gate = true;
	must(pthread_create(&reader, NULL, read_candidate, &context));
	meet(&reader_arrived);
	atomic_store(&origin.bi_swapz_original, NULL);
	must(pthread_create(&writer, NULL, release_carrier, NULL));
	meet(&writer_arrived);
	CHECK(atomic_load(&swapz_mm_busy) == 1);
	CHECK(atomic_load(&grace_calls) == 2U);
	meet(&reader_resume);
	must(pthread_join(reader, NULL));
	must(pthread_join(writer, NULL));
	gate = false;
	CHECK(!context.result && context.retained.broker == &broker);
	CHECK(!atomic_load(&swapz_mm_busy));
	CHECK(!swapz_mm_carrier.bdev && !swapz_mm_carrier.page);
	CHECK(swapz_mm_candidate_get(&origin, &retained) == -EOPNOTSUPP);
	CHECK(!swapz_ticket_revoke(&broker, 21));
	CHECK(swapz_ticket_close(&broker) == -EBUSY);
	CHECK(swapz_ticket_destroy(&broker) == -EBUSY);
	CHECK(!swapz_ticket_view(&context.retained, &view) && !memcmp(view.bytes, bytes, sizeof(bytes)));
	CHECK(!swapz_ticket_put(&context.retained));
	CHECK(!swapz_ticket_close(&broker));
	CHECK(!swapz_ticket_destroy(&broker));
	must(pthread_barrier_destroy(&reader_arrived));
	must(pthread_barrier_destroy(&reader_resume));
	must(pthread_barrier_destroy(&writer_arrived));
	must(pthread_rwlock_destroy(&readers));

	started = clock();
	immediate = trace(0);
	lag32 = trace(32);
	lag64 = trace(64);
	lag256 = trace(256);
	finished = clock();
	CHECK(immediate == 1024U && lag32 == 992U);
	CHECK(!lag64 && !lag256);
	CHECK(started != (clock_t)-1 && finished >= started);
	printf("PASS_HOST_ONLY R090 checks=%u lifecycle_races=1 immediate=%u lag32=%u lag64=%u lag256=%u source=%zu carrier=%zu broker=%zu trace_cpu_seconds=%.9f\n",
		checks, immediate, lag32, lag64, lag256, sizeof(struct swapz_mm_source),
		sizeof(struct swapz_mm_carrier), sizeof(broker),
		(double)(finished - started) / (double)CLOCKS_PER_SEC);
	return 0;
}
