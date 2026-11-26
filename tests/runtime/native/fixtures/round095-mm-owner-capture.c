/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual staged MM functions + actual built-in owner/broker; host Linux ABI. */
#include <errno.h>
#include <stdint.h>
#include <string.h>
#include <openssl/sha.h>
#include "round094-owner-shim.h"
#include "zswap-original-ticket.h"

typedef swapz_u64 u64;
typedef swapz_u32 u32;
typedef swapz_u8 u8;
typedef int64_t s64;
typedef u64 sector_t;
typedef struct { u64 val; } swp_entry_t;
typedef _Atomic(s64) atomic64_t;
#define S64_MAX INT64_MAX
#define PAGE_SIZE 4096U
#define CONFIG_SWAPZ_ORIGINAL_MM_CARRIER_TEST 1
struct block_device { bool partition; };
struct page { unsigned int unused; };
struct folio { struct page page; swp_entry_t swap; bool locked, swapcache; unsigned int order; u8 bytes[4096]; };
struct swap_info_struct { struct block_device *bdev; const int *ops; };
struct zswap_pool { const char *tfm_name; const u8 *zs_pool; };
struct zswap_entry { swp_entry_t swpentry; u64 original_cookie; u32 length; unsigned long handle; struct zswap_pool *pool; };
struct crypto_acomp { const char *name, *driver; };
struct acomp_req { struct crypto_acomp *tfm; };
struct scatterlist { const u8 *bytes; size_t length; };
struct bio_vec { struct page *bv_page; unsigned int bv_offset, bv_len; };
struct bio {
	struct block_device *bi_bdev;
	struct { sector_t bi_sector; unsigned int bi_size, bi_idx, bi_offset; } bi_iter;
	unsigned int bi_vcnt, bi_opf, bi_flags;
	struct bio_vec *bi_io_vec;
	_Atomic(struct swapz_mm_carrier *) bi_swapz_original;
};
struct work_struct { int unused; };
#define REQ_OP_WRITE 1U
#define REQ_SWAP 256U
#define BIO_CLONED 1U
#define BIO_REMAPPED 2U
static unsigned int bio_op(const struct bio *bio) { return bio->bi_opf & 255U; }
static bool bio_flagged(const struct bio *bio, unsigned int flag) { return !!(bio->bi_flags & flag); }
static struct module provider_module = {.live = true};
#define THIS_MODULE (&provider_module)
#include "r095-carrier.h"
struct swap_io_ctx { void *sio; struct swapz_mm_carrier *original; };

static unsigned int checks, allocations, compressor_calls, folio_calls, slot_calls, sg_copies, hashes, callbacks, grace_calls, reader_calls;
static bool work_queued, sg_pinned, short_copy;
static atomic_bool pause_entrant;
static pthread_barrier_t entered, resume;
static struct swapz_mm_carrier swapz_mm_carrier;
static atomic_int swapz_mm_busy;
static atomic64_t swapz_mm_store_sequence, swapz_mm_area_epochs[2];
static pthread_mutex_t swapz_mm_provider_lock = PTHREAD_MUTEX_INITIALIZER;
static _Atomic(const struct swapz_mm_route_provider *) swapz_mm_provider;
static _Atomic(struct module *) swapz_mm_provider_owner;
static pthread_rwlock_t readers = PTHREAD_RWLOCK_INITIALIZER;
static _Thread_local bool reader_held;
static const int swap_bdev_ops;
static struct block_device device;
static struct swap_info_struct swap_info = {.bdev = &device, .ops = &swap_bdev_ops};
static struct swapz_ticket_cap route_cap;
static struct swapz_mm_route route_snapshot;

#define CHECK(condition, witness) do { \
	++checks; \
	if (!(condition)) { fprintf(stderr, "R095_A11_FIRST_ERROR %s line=%d\n", witness, __LINE__); exit(77); } \
} while (0)
static void must(int error) { if (error) { fprintf(stderr, "R095_A11_INFRA pthread=%d\n", error); exit(78); } }
static void meet(pthread_barrier_t *barrier) { int error = pthread_barrier_wait(barrier); if (error != PTHREAD_BARRIER_SERIAL_THREAD) must(error); }
void r094_owner_mutex_lock(pthread_mutex_t *lock) { must(pthread_mutex_lock(lock)); }
void r094_owner_mutex_unlock(pthread_mutex_t *lock) { must(pthread_mutex_unlock(lock)); }
void *r094_owner_allocate(size_t bytes) { void *pointer = aligned_alloc(64, (bytes + 63U) & ~(size_t)63U); if (pointer) ++allocations; return pointer; }
void r094_owner_free(void *pointer) { if (pointer) { --allocations; free(pointer); } }
void r094_owner_after_enter(void) { if (atomic_load(&pause_entrant)) { meet(&entered); meet(&resume); } }
static void rcu_read_lock(void) { ++reader_calls; must(pthread_rwlock_rdlock(&readers)); reader_held = true; }
static void rcu_read_unlock(void) { reader_held = false; must(pthread_rwlock_unlock(&readers)); }
static void reader_guard(void) { if (!reader_held) must(EINVAL); }
#define rcu_dereference(pointer) (reader_guard(), atomic_load_explicit(&(pointer), memory_order_acquire))
#define rcu_access_pointer(pointer) atomic_load_explicit(&(pointer), memory_order_acquire)
#define rcu_assign_pointer(pointer, value) atomic_store_explicit(&(pointer), (value), memory_order_release)
#define READ_ONCE(pointer) atomic_load(&(pointer))
#define WRITE_ONCE(pointer, value) atomic_store(&(pointer), (value))
#define mutex_lock(pointer) must(pthread_mutex_lock(pointer))
#define mutex_unlock(pointer) must(pthread_mutex_unlock(pointer))
static void synchronize_rcu(void) { ++grace_calls; must(pthread_rwlock_wrlock(&readers)); must(pthread_rwlock_unlock(&readers)); }
static bool warn_on(bool condition) { if (condition) must(EIO); return condition; }
#define WARN_ON_ONCE(condition) warn_on(!!(condition))
#define atomic_set_release(pointer, value) atomic_store_explicit((pointer), (value), memory_order_release)
static s64 atomic64_read(const atomic64_t *value) { return atomic_load(value); }
static bool atomic64_try_cmpxchg(atomic64_t *value, s64 *previous, s64 next) { return atomic_compare_exchange_strong(value, previous, next); }
static int atomic_cmpxchg_acquire(atomic_int *value, int previous, int next) { (void)atomic_compare_exchange_strong(value, &previous, next); return previous; }
static struct crypto_acomp *crypto_acomp_reqtfm(struct acomp_req *request) { ++compressor_calls; return request->tfm; }
static const char *crypto_acomp_alg_name(struct crypto_acomp *tfm) { return tfm->name; }
static const char *crypto_acomp_driver_name(struct crypto_acomp *tfm) { return tfm->driver; }
static swp_entry_t folio_swap_entry(struct folio *folio, long index) { ++folio_calls; (void)index; return folio->swap; }
static unsigned int folio_order(const struct folio *folio) { return folio->order; }
static bool folio_test_locked(const struct folio *folio) { return folio->locked; }
static bool folio_test_swapcache(const struct folio *folio) { return folio->swapcache; }
static unsigned int swp_type(swp_entry_t slot) { (void)slot; return 1; }
static u64 swp_offset(swp_entry_t slot) { return slot.val; }
static struct swap_info_struct *__swap_entry_to_info(swp_entry_t slot) { ++slot_calls; (void)slot; return &swap_info; }
static bool bdev_is_partition(const struct block_device *bdev) { return bdev->partition; }
static sector_t swap_folio_sector(const struct folio *folio) { return folio->swap.val * 8U; }
static struct zswap_pool *zswap_entry_pool(struct zswap_entry *entry) { return entry->pool; }
static void zs_obj_read_sg_begin(const u8 *pool, unsigned long handle, struct scatterlist *sg, u32 length) { (void)handle; if (sg_pinned) must(EINVAL); sg_pinned = true; *sg = (struct scatterlist){pool, length}; }
static bool sg_is_last(const struct scatterlist *sg) { (void)sg; return true; }
static size_t sg_copy_to_buffer(const struct scatterlist *sg, unsigned int nents, u8 *destination, size_t length) { if (!sg_pinned || nents != 1 || length != sg->length) must(EINVAL); ++sg_copies; if (short_copy) return length - 1; memcpy(destination, sg->bytes, length); return length; }
static void zs_obj_read_sg_end(const u8 *pool, unsigned long handle) { (void)pool; (void)handle; if (!sg_pinned) must(EINVAL); sg_pinned = false; }
static const void *kmap_local_folio(const struct folio *folio, unsigned int offset) { if (sg_pinned || offset) must(EINVAL); return folio->bytes; }
static void kunmap_local(const void *bytes) { (void)bytes; }
static void sha256(const void *bytes, size_t length, u8 digest[32]) { if (sg_pinned) must(EINVAL); ++hashes; (void)SHA256(bytes, length, digest); }
static struct work_struct swapz_mm_release_work;
static bool queue_work(int queue, struct work_struct *work) { (void)queue; (void)work; if (work_queued) return false; work_queued = true; return true; }
#define system_unbound_wq 0
#include "r095-functions.h"

static bool eligible(struct block_device *bdev, sector_t sector, u8 codec, u32 length)
{
	if (!reader_held || !atomic_load(&provider_module.refs)) must(EINVAL);
	++callbacks;
	return bdev == &device && sector == 8U && codec == SWAPZ_TICKET_LZ4 && length <= 3568U;
}
static bool lookup(struct block_device *bdev, sector_t sector, u8 codec, u32 length, struct swapz_mm_route *route)
{
	if (!eligible(bdev, sector, codec, length)) return false;
	*route = route_snapshot;
	return true;
}
static const struct swapz_mm_route_provider provider = {.eligible = eligible, .lookup = lookup};
static void release_work(void)
{
	CHECK(work_queued, "release_queued");
	work_queued = false;
	swapz_mm_release_workfn(NULL);
}
struct route_context { bool result; struct swapz_mm_route route; struct swapz_ticket_cap cap; struct module *owner; };
static void *route_reader(void *opaque)
{
	struct route_context *context = opaque;
	context->result = swapz_mm_route_try(&swap_info, 8, SWAPZ_TICKET_LZ4, 64,
		&context->route, &context->cap, &context->owner);
	return NULL;
}
int main(void)
{
	u8 compressed[4096];
	memset(compressed, 0x6b, sizeof(compressed));
	struct zswap_pool pool = {.tfm_name = "lz4", .zs_pool = compressed};
	struct zswap_entry entry = {.swpentry = {1}, .length = 64, .pool = &pool};
	struct folio folio = {.swap = {1}, .locked = true, .swapcache = true};
	struct crypto_acomp tfm = {.name = "lz4", .driver = "lz4-scomp"};
	struct acomp_req request = {.tfm = &tfm};
	struct swap_io_ctx ctx = {0};
	struct bio_vec vector = {&folio.page, 0, 4096};
	struct bio origin = {.bi_bdev = &device, .bi_iter = {8, 4096, 0, 0}, .bi_vcnt = 1,
		.bi_opf = REQ_OP_WRITE | REQ_SWAP, .bi_io_vec = &vector};
	struct swapz_ticket_ref candidate = {0};
	struct swapz_ticket_view view = {0};
	memset(folio.bytes, 0xa5, sizeof(folio.bytes));
	atomic_store(&swapz_mm_area_epochs[1], 7);
	CHECK(!swapz_mm_broker_owner_open(8, 3568, 8U * 3568U, &route_cap), "owner_open");
	u64 session = route_cap.session, epoch = route_cap.epoch;
	struct swapz_ticket_broker *broker = route_cap.broker;
	route_snapshot = (struct swapz_mm_route){.broker = broker, .target_session = session,
		.table_epoch = epoch, .target_epoch = 3, .logical_page = 1, .dm_generation = 2};
	CHECK(broker->capacity == 8 && broker->stride == 3584 && broker->payload_bytes == 28672 &&
		(unsigned long)broker->payload % 64U == 0 && allocations == 3, "eight_slot_layout");
	CHECK(!swapz_mm_register_provider(&provider) && !atomic_load(&provider_module.refs), "register");
	swapz_mm_capture(&entry, &folio, 0, &pool, &request);
#ifdef SWAPZ_ROUND095_MM_CAPTURE_OBSERVATION_TEST
	CHECK(entry.original_cookie && callbacks == 1 && compressor_calls == 1, "enabled_capture");
	entry.length = 3569;
	unsigned int before = callbacks;
	swapz_mm_capture(&entry, &folio, 0, &pool, &request);
	swapz_mm_preerase(&entry, &folio, folio.swap, &ctx);
	CHECK(callbacks == before && !sg_copies && !hashes && !ctx.original, "m3568_bound");
	entry.length = 64;
	short_copy = true;
	swapz_mm_preerase(&entry, &folio, folio.swap, &ctx);
	CHECK(!ctx.original && !hashes && sg_copies == 1 && work_queued, "short_copy_declines");
	release_work();
	CHECK(!atomic_load(&provider_module.refs) && !atomic_load(&swapz_mm_busy), "short_copy_drained");
	short_copy = false;
	swapz_mm_preerase(&entry, &folio, folio.swap, &ctx);
	CHECK(ctx.original && sg_copies == 2 && hashes == 1 && !sg_pinned, "actual_preerase");
	CHECK(atomic_load(&provider_module.refs) == 1 && broker->capability_refs == 2, "carrier_holds");
	rcu_assign_pointer(origin.bi_swapz_original, ctx.original);
	CHECK(!swapz_mm_candidate_get(&origin, &candidate), "actual_candidate");
	CHECK(!swapz_ticket_view(&candidate, &view) && view.key.area_epoch == 7 &&
		view.key.store_sequence == entry.original_cookie && view.key.slot_offset == 1 &&
		view.key.target_session == session && view.key.table_epoch == epoch &&
		view.key.dm_generation == 2 && view.key.length == 64 &&
		!memcmp(view.bytes, compressed, 64), "source_identity");
	rcu_assign_pointer(origin.bi_swapz_original, NULL);
	swapz_mm_drop(&ctx.original);
	CHECK(!ctx.original && work_queued, "terminal_drop");
	CHECK(!swapz_mm_unregister_provider(&provider), "unpublish");
	CHECK(!swapz_mm_broker_owner_begin_close(session, epoch) && !swapz_ticket_broker_put(&route_cap), "begin_close");
	CHECK(swapz_mm_broker_owner_finish_close(session, epoch) == -EBUSY, "carrier_busy");
	release_work();
	CHECK(atomic_load(&provider_module.refs) == 1 && !atomic_load(&swapz_mm_busy) && grace_calls == 2, "candidate_outlives_carrier");
	CHECK(swapz_mm_broker_owner_finish_close(session, epoch) == -EBUSY, "candidate_busy");
	CHECK(!swapz_ticket_view(&candidate, &view) && !memcmp(view.bytes, compressed, 64), "retained_bytes");
	CHECK(!swapz_ticket_put(&candidate) && !atomic_load(&provider_module.refs), "candidate_drained");
	CHECK(!swapz_mm_broker_owner_finish_close(session, epoch) && !allocations, "actual_destroy");
#else
	CHECK(!entry.original_cookie && !callbacks && !compressor_calls && !folio_calls, "disabled_store_zero");
	entry.original_cookie = 99;
	swapz_mm_preerase(&entry, &folio, folio.swap, &ctx);
	CHECK(!ctx.original && !slot_calls && !sg_copies && !hashes && !work_queued && !callbacks, "disabled_eviction_zero");
	CHECK(swapz_mm_candidate_get(&origin, &candidate) == -EOPNOTSUPP && !candidate.broker && !reader_calls, "disabled_candidate");
	CHECK(!swapz_mm_unregister_provider(&provider), "unpublish");
	CHECK(!swapz_mm_broker_owner_begin_close(session, epoch) && !swapz_ticket_broker_put(&route_cap), "begin_close");
	CHECK(!swapz_mm_broker_owner_finish_close(session, epoch) && !allocations, "disabled_destroy");
#endif
	/* New cross-boundary adversarial interleaving: actual MM callback has
	 * returned the borrowed route, actual owner entrant paused pre-ref.
	 * Deliberately close before modeled target grace to stress permanent gate.
	 */
	(void)view;
	(void)release_work;
	CHECK(!swapz_mm_broker_owner_open(8, 3568, 8U * 3568U, &route_cap), "reopen");
	CHECK(route_cap.session > session && route_cap.epoch > epoch && route_cap.broker == broker, "fresh_identity");
	session = route_cap.session; epoch = route_cap.epoch;
	route_snapshot.target_session = session; route_snapshot.table_epoch = epoch;
	CHECK(!swapz_mm_register_provider(&provider), "register_again");
	must(pthread_barrier_init(&entered, NULL, 2));
	must(pthread_barrier_init(&resume, NULL, 2));
	struct route_context context = {0};
	pthread_t thread;
	atomic_store(&pause_entrant, true);
	must(pthread_create(&thread, NULL, route_reader, &context));
	meet(&entered);
	CHECK(atomic_load(&provider_module.refs) == 1, "paused_callback_pin");
	CHECK(!swapz_mm_broker_owner_begin_close(session, epoch) && !swapz_ticket_broker_put(&route_cap), "paused_close");
	CHECK(swapz_mm_broker_owner_finish_close(session, epoch) == -EBUSY && allocations == 3, "paused_mm_entrant");
	meet(&resume);
	must(pthread_join(thread, NULL));
	atomic_store(&pause_entrant, false);
	CHECK(!context.result && !context.cap.broker && !context.owner && !atomic_load(&provider_module.refs), "late_cap_decline");
	CHECK(!swapz_mm_unregister_provider(&provider), "final_unpublish");
	CHECK(!swapz_mm_broker_owner_finish_close(session, epoch) && !allocations, "final_destroy");
	must(pthread_barrier_destroy(&entered));
	must(pthread_barrier_destroy(&resume));
	printf("PASS_HOST_ONLY R095 A11 checks=%u observation=%u sg=%u hash=%u\n", checks,
#ifdef SWAPZ_ROUND095_MM_CAPTURE_OBSERVATION_TEST
		1U,
#else
		0U,
#endif
		sg_copies, hashes);
	return 0;
}
