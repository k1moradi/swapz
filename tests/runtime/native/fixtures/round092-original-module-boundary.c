/* SPDX-License-Identifier: GPL-2.0-only */
/* Real staged MM helpers/header and broker; pthread RCU/module ABI model only. */
#include <errno.h>
#include <stdint.h>
#include <stdalign.h>
#include <string.h>
#include <pthread.h>
#include "round092-module-shim.h"
#include "zswap-original-ticket.h"

typedef uint64_t sector_t;
typedef uint8_t u8;
typedef uint32_t u32;
struct block_device { unsigned int identity; };
struct page { unsigned int identity; };
struct swap_info_struct { struct block_device *bdev; };
struct bio_vec { struct page *bv_page; unsigned int bv_offset, bv_len; };
struct bio {
	struct block_device *bi_bdev;
	struct { sector_t bi_sector; unsigned int bi_size, bi_idx, bi_offset; } bi_iter;
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
static struct module provider_module = {.live = true};
#define THIS_MODULE (&provider_module)
#define CONFIG_SWAPZ_ORIGINAL_MM_CARRIER_TEST 1
#include "r092-staged-carrier.h"

static struct swapz_mm_carrier swapz_mm_carrier;
static atomic_int swapz_mm_busy;
static pthread_mutex_t swapz_mm_provider_lock = PTHREAD_MUTEX_INITIALIZER;
static _Atomic(const struct swapz_mm_route_provider *) swapz_mm_provider;
static _Atomic(struct module *) swapz_mm_provider_owner;
static pthread_rwlock_t readers = PTHREAD_RWLOCK_INITIALIZER;
static pthread_barrier_t reader_arrived, reader_resume, writer_arrived;
static unsigned int gate;
static _Thread_local bool reader_held;
static atomic_uint grace_calls;
struct work_struct { int unused; };
static struct swapz_ticket_broker *route_broker;
static swapz_u64 route_epoch = 20;
static bool lookup_success = true;
static atomic_uint callbacks;
static void must(int error)
{
	if (error) {
		fprintf(stderr, "R092_FIRST_ERROR pthread=%d\n", error);
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
static void reader_guard(void)
{
	if (!reader_held) {
		fprintf(stderr, "R092_FIRST_ERROR reader_unprotected\n");
		exit(77);
	}
}
#define rcu_dereference(pointer) (reader_guard(), atomic_load_explicit(&(pointer), memory_order_acquire))
#define rcu_access_pointer(pointer) atomic_load_explicit(&(pointer), memory_order_acquire)
#define rcu_assign_pointer(pointer, value) atomic_store_explicit(&(pointer), (value), memory_order_release)
#define READ_ONCE(pointer) atomic_load(&(pointer))
#define WRITE_ONCE(pointer, value) atomic_store(&(pointer), (value))
#define mutex_lock(pointer) must(pthread_mutex_lock(pointer))
#define mutex_unlock(pointer) must(pthread_mutex_unlock(pointer))
static void synchronize_rcu(void)
{
	(void)atomic_fetch_add(&grace_calls, 1U);
	if (gate)
		meet(&writer_arrived);
	must(pthread_rwlock_wrlock(&readers));
	must(pthread_rwlock_unlock(&readers));
}
static void gate_bio_op(void)
{
	if (gate == 2U) {
		meet(&reader_arrived);
		meet(&reader_resume);
	}
}
#define WARN_ON_ONCE(condition) (!!(condition))
#define atomic_set_release(pointer, value) atomic_store_explicit((pointer), (value), memory_order_release)
#include "r092-staged-functions.h"

static void callback_guard(void)
{
	if (!reader_held || !atomic_load(&provider_module.refs)) {
		fprintf(stderr, "R092_FIRST_ERROR callback_without_module_pin\n");
		exit(77);
	}
	(void)atomic_fetch_add(&callbacks, 1U);
}
static bool eligible(struct block_device *bdev, sector_t sector, u8 codec, u32 length)
{
	callback_guard();
	if (gate == 1U) {
		meet(&reader_arrived);
		meet(&reader_resume);
	}
	return bdev && sector == 8U && codec == SWAPZ_TICKET_LZ4 && length == 64U;
}
static bool lookup(struct block_device *bdev, sector_t sector, u8 codec, u32 length,
		   struct swapz_mm_route *route)
{
	if (!eligible(bdev, sector, codec, length) || !lookup_success)
		return false;
	*route = (struct swapz_mm_route){.broker = route_broker, .target_session = 17,
		.table_epoch = route_epoch, .target_epoch = 3, .logical_page = 4,
		.dm_generation = 5};
	return true;
}
static const struct swapz_mm_route_provider provider = {.eligible = eligible, .lookup = lookup};
static unsigned int checks;
#define CHECK(condition, witness) do { \
	++checks; \
	if (!(condition)) { fprintf(stderr, "R092_FIRST_ERROR %s line=%d\n", witness, __LINE__); return 77; } \
} while (0)

struct reader_context { struct bio *origin; struct swapz_ticket_ref retained; int result; };
struct callback_context { struct block_device *device; bool result; };
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
static void *read_provider(void *opaque)
{
	struct callback_context *context = opaque;
	context->result = swapz_mm_eligible(context->device, 8, SWAPZ_TICKET_LZ4, 64);
	return NULL;
}
static void *unregister_provider(void *opaque)
{
	int *result = opaque;
	*result = swapz_mm_unregister_provider(&provider);
	return NULL;
}
int main(void)
{
	struct swapz_ticket_broker broker = {0};
	struct swapz_ticket_slot slots[1];
	swapz_u32 indices[1];
	alignas(64) swapz_u8 payload[3584];
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
	struct swap_info_struct si = {.bdev = &device};
	struct bio_vec vector = {&page, 0, 4096};
	struct bio origin = {.bi_bdev = &device, .bi_iter = {8, 4096, 0, 0},
		.bi_vcnt = 1, .bi_opf = REQ_OP_WRITE | REQ_SWAP, .bi_io_vec = &vector};
	struct swapz_mm_route route = {0};
	struct swapz_ticket_ref duplicate = {0}, rejected = {0};
	struct swapz_ticket_view view = {0};
	struct callback_context callback = {.device = &device};
	struct reader_context context = {.origin = &origin};
	pthread_t reader, writer;
	int unregister_result = -1;
	memset(bytes, 0x5b, sizeof(bytes));
	memset(key.sha256, 0xa5, sizeof(key.sha256));
	key.crc = swapz_crc32c_bytes(bytes, (u32)sizeof(bytes));
	route_broker = &broker;
	CHECK(!swapz_ticket_init(&broker, slots, sizeof(slots), payload, sizeof(payload),
		indices, sizeof(indices), 1, 3568, sizeof(bytes), 17, 20), "broker_init");
	CHECK(!swapz_mm_eligible(&device, 8, SWAPZ_TICKET_LZ4, 64), "absent");
	CHECK(!swapz_mm_register_provider(&provider), "register");
	CHECK(!atomic_load(&provider_module.refs), "registration_no_self_pin");
	CHECK(swapz_mm_register_provider(&provider) == -EBUSY, "duplicate_register");
	atomic_store(&provider_module.live, false);
	CHECK(!swapz_mm_eligible(&device, 8, SWAPZ_TICKET_LZ4, 64), "unloading_decline");
	CHECK(!atomic_load(&callbacks), "no_dead_callback");
	atomic_store(&provider_module.live, true);
	CHECK(swapz_mm_eligible(&device, 8, SWAPZ_TICKET_LZ4, 64), "eligible");
	CHECK(!atomic_load(&provider_module.refs), "callback_put");
	must(pthread_barrier_init(&reader_arrived, NULL, 2));
	must(pthread_barrier_init(&reader_resume, NULL, 2));
	must(pthread_barrier_init(&writer_arrived, NULL, 2));
	gate = 1;
	must(pthread_create(&reader, NULL, read_provider, &callback));
	meet(&reader_arrived);
	CHECK(atomic_load(&provider_module.refs) == 1U, "callback_pin");
	must(pthread_create(&writer, NULL, unregister_provider, &unregister_result));
	meet(&writer_arrived);
	CHECK(!rcu_access_pointer(swapz_mm_provider), "unpublish_before_grace");
	CHECK(atomic_load(&provider_module.refs) == 1U, "callback_pin_during_grace");
	meet(&reader_resume);
	must(pthread_join(reader, NULL));
	must(pthread_join(writer, NULL));
	gate = 0;
	CHECK(!unregister_result && callback.result, "unregister_drained");
	CHECK(!atomic_load(&provider_module.refs) && !READ_ONCE(swapz_mm_provider_owner), "unregister_no_pin");
	CHECK(!swapz_mm_register_provider(&provider), "reregister");
	lookup_success = false;
	CHECK(!swapz_mm_route_try(&si, 8, SWAPZ_TICKET_LZ4, 64, &route,
		&swapz_mm_carrier.cap, &swapz_mm_carrier.provider_owner), "lookup_decline");
	CHECK(!atomic_load(&provider_module.refs), "decline_no_pin");
	lookup_success = true;
	route_epoch = 21;
	CHECK(!swapz_mm_route_try(&si, 8, SWAPZ_TICKET_LZ4, 64, &route,
		&swapz_mm_carrier.cap, &swapz_mm_carrier.provider_owner), "stale_cap");
	CHECK(!atomic_load(&provider_module.refs), "failed_cap_put");
	route_epoch = 20;
	CHECK(swapz_mm_route_try(&si, 8, SWAPZ_TICKET_LZ4, 64, &route,
		&swapz_mm_carrier.cap, &swapz_mm_carrier.provider_owner), "route_cap");
	CHECK(atomic_load(&provider_module.refs) == 1U, "carrier_pin");
	CHECK(!swapz_ticket_reserve(&broker, &key, &swapz_mm_carrier.lease), "reserve");
	CHECK(!swapz_ticket_seal(&swapz_mm_carrier.lease, bytes, (u32)sizeof(bytes)), "seal");
	swapz_mm_carrier.bdev = &device;
	swapz_mm_carrier.page = &page;
	swapz_mm_carrier.sector = 8;
	atomic_store(&swapz_mm_busy, 1);
	atomic_store(&origin.bi_swapz_original, &swapz_mm_carrier);
	gate = 2;
	must(pthread_create(&reader, NULL, read_candidate, &context));
	meet(&reader_arrived);
	atomic_store(&origin.bi_swapz_original, NULL);
	must(pthread_create(&writer, NULL, release_carrier, NULL));
	meet(&writer_arrived);
	CHECK(atomic_load(&swapz_mm_busy) == 1 && atomic_load(&provider_module.refs) == 1U, "carrier_grace_pin");
	meet(&reader_resume);
	must(pthread_join(reader, NULL));
	must(pthread_join(writer, NULL));
	gate = 0;
	CHECK(!context.result && context.retained.provider_owner == &provider_module, "candidate_owner");
	CHECK(!atomic_load(&swapz_mm_busy) && !swapz_mm_carrier.cap.broker, "carrier_released");
	CHECK(atomic_load(&provider_module.refs) == 1U, "candidate_pin_after_carrier_put");
	CHECK(!swapz_ticket_retain(&context.retained, &duplicate), "duplicate_retain");
	CHECK(atomic_load(&provider_module.refs) == 2U, "duplicate_pin");
	CHECK(!swapz_ticket_view(&duplicate, &view) && !memcmp(view.bytes, bytes, sizeof(bytes)), "exact_view");
	CHECK(!swapz_mm_unregister_provider(&provider), "revoke_provider");
	CHECK(!swapz_ticket_revoke(&broker, 21), "revoke_broker");
	CHECK(swapz_ticket_retain(&duplicate, &rejected) == -ESTALE, "stale_retain");
	CHECK(!rejected.broker && atomic_load(&provider_module.refs) == 2U, "stale_retain_put");
	CHECK(swapz_ticket_close(&broker) == -EBUSY, "close_busy");
	CHECK(swapz_ticket_destroy(&broker) == -EBUSY, "destroy_busy");
	CHECK(!swapz_ticket_put(&context.retained) && atomic_load(&provider_module.refs) == 1U, "first_put");
	CHECK(!swapz_ticket_put(&duplicate) && !atomic_load(&provider_module.refs), "last_put");
	CHECK(!swapz_ticket_close(&broker) && !swapz_ticket_destroy(&broker), "drained_destroy");
	must(pthread_barrier_destroy(&reader_arrived));
	must(pthread_barrier_destroy(&reader_resume));
	must(pthread_barrier_destroy(&writer_arrived));
	must(pthread_rwlock_destroy(&readers));
	must(pthread_mutex_destroy(&swapz_mm_provider_lock));
	printf("PASS_HOST_ONLY R092 checks=%u lifecycle_races=2 carrier=%zu ref=%zu broker=%zu\n",
		checks, sizeof(swapz_mm_carrier), sizeof(struct swapz_ticket_ref), sizeof(broker));
	return 0;
}
