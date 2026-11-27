/* SPDX-License-Identifier: GPL-2.0-only */
/* Changed R101 scope/retirement cases. Kernel RCU, BIO and scheduler are
 * host models; the staged MM functions, geometry and broker are actual. */
#include "native-observation-owner-host-model.h"
#include "native-observation-owner.h"
#include "round094-owner-shim.h"
#include "zswap-original-ticket.h"
#include <errno.h>
#include <openssl/sha.h>
#include <sys/stat.h>

static unsigned checks, allocations, owner_allocations, retry_queued;
static unsigned grace_count, readers;
static _Thread_local unsigned reader_depth;
static pthread_mutex_t reader_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t reader_changed = PTHREAD_COND_INITIALIZER;
#define CHECK(condition) do { \
	++checks; \
	if (!(condition)) { \
		fprintf(stderr, "R101_A11_FIRST_ERROR line=%d: %s\n", __LINE__, #condition); \
		exit(77); \
	} \
} while (0)

bool model_try_cmpxchg(atomic_t *counter, int *previous, int next)
{
	return atomic_compare_exchange_strong_explicit(&counter->value, previous, next,
		memory_order_relaxed, memory_order_relaxed);
}
void model_read_lock(void)
{
	if (reader_depth++)
		return;
	mutex_lock(&reader_mutex);
	++readers;
	mutex_unlock(&reader_mutex);
}
void model_read_unlock(void)
{
	if (!reader_depth)
		abort();
	if (--reader_depth)
		return;
	mutex_lock(&reader_mutex);
	--readers;
	if (pthread_cond_broadcast(&reader_changed))
		abort();
	mutex_unlock(&reader_mutex);
}
void model_synchronize_rcu(void)
{
	if (reader_depth)
		abort();
	mutex_lock(&reader_mutex);
	++grace_count;
	if (pthread_cond_broadcast(&reader_changed))
		abort();
	while (readers)
		if (pthread_cond_wait(&reader_changed, &reader_mutex))
			abort();
	mutex_unlock(&reader_mutex);
}
void *model_kvcalloc(size_t count, size_t size, int flags)
{
	(void)flags;
	void *value = calloc(count, size);
	if (value)
		++allocations;
	return value;
}
void model_kvfree(void *pointer)
{
	if (pointer) {
		if (!allocations)
			abort();
		--allocations;
		free(pointer);
	}
}
void sha256(const u8 *bytes, unsigned int length, u8 *digest)
{
	if (!SHA256(bytes, length, digest))
		abort();
}
void r094_owner_mutex_lock(pthread_mutex_t *lock) { mutex_lock(lock); }
void r094_owner_mutex_unlock(pthread_mutex_t *lock) { mutex_unlock(lock); }
void *r094_owner_allocate(size_t bytes)
{
	void *value = aligned_alloc(64, (bytes + 63U) & ~(size_t)63U);
	if (value)
		++owner_allocations;
	return value;
}
void r094_owner_free(void *pointer)
{
	if (pointer) {
		if (!owner_allocations)
			abort();
		--owner_allocations;
		free(pointer);
	}
}
void r094_owner_after_enter(void) {}
/* Deterministic queue, never execute work inline under the broker lock. */
void r096_owner_schedule_retry(void) { ++retry_queued; }
#include "zswap-original-ticket.c"

typedef u64 sector_t;
#define U32_MAX UINT32_MAX
#define MAX_SWAPFILES 32U
struct block_device { sector_t sectors; bool partition; };
struct inode { mode_t i_mode; };
struct file { struct inode inode; struct block_device *bdev; unsigned refs; };
struct page { unsigned unused; };
static struct inode *file_inode(struct file *file) { return &file->inode; }
static struct block_device *file_bdev(struct file *file) { return file->bdev; }
static bool bdev_is_partition(struct block_device *bdev) { return bdev->partition; }
static sector_t bdev_nr_sectors(struct block_device *bdev) { return bdev->sectors; }
static void get_file(struct file *file) { ++file->refs; }
static void fput(struct file *file) { if (!file->refs) abort(); --file->refs; }
static atomic_uint_fast64_t swapz_mm_area_epochs[MAX_SWAPFILES];
#define atomic64_read(value) atomic_load(value)
#define atomic_read_acquire(counter) atomic_load_explicit(&(counter)->value, memory_order_acquire)
static atomic_t swapz_mm_busy;
#include "r101-types.h"
struct bio_vec { struct page *bv_page; unsigned int bv_offset, bv_len; };
struct bvec_iter { sector_t bi_sector; unsigned int bi_size, bi_idx, bi_offset; };
struct bio {
	const struct swapz_mm_carrier *bi_swapz_original;
	struct bio_vec *bi_io_vec;
	struct block_device *bi_bdev;
	struct bvec_iter bi_iter;
	unsigned int bi_vcnt, bi_opf, flags;
};
enum { REQ_OP_WRITE = 1, REQ_SWAP = 1U << 8, BIO_CLONED = 1U, BIO_REMAPPED = 2U };
static unsigned int bio_op(const struct bio *bio) { return bio->bi_opf & 255U; }
static bool bio_flagged(const struct bio *bio, unsigned int flag)
{
	return (bio->flags & flag) != 0;
}
#include "r101-extracted.h"

struct stop_call { u64 identity; int result; };
static void *stop_thread(void *context)
{
	struct stop_call *call = context;
	call->result = swapz_mm_trial_scope_stop_capture(call->identity);
	return NULL;
}
static struct swapz_trial_observation_scope manifest(void)
{
	struct swapz_trial_observation_scope value = {
		.session = 1, .epoch = 1, .target_epoch = 13,
		.registration_epoch = 14, .first_logical = 7, .page_count = 2,
	};
	memcpy(value.source, SWAPZ_OBSERVATION_BUILD_SOURCE, 40);
	memset(value.kernel_sha256, '1', sizeof(value.kernel_sha256));
	memset(value.module_sha256, '2', sizeof(value.module_sha256));
	memset(value.workload_sha256, '3', sizeof(value.workload_sha256));
	memset(value.run_nonce, '4', sizeof(value.run_nonce));
	memset(value.target, '5', sizeof(value.target));
	return value;
}
static bool join_empty(void *context) { (void)context; return !reader_depth; }

int main(int argc, char **argv)
{
	if (argc != 2)
		return 2;
	const bool explicit_finish = !strcmp(argv[1], "explicit");
	CHECK(explicit_finish || !strcmp(argv[1], "worker"));
	struct block_device mapper = {128, false};
	struct file opened = {{S_IFBLK}, &mapper, 1};
	struct swapz_ticket_cap owner = {0};
	CHECK(!swapz_mm_broker_owner_open(8, 3568, 8 * 3568, &owner));
	const u64 session = owner.session, epoch = owner.epoch;
	CHECK(swapz_mm_broker_owner_retired(session, epoch) == -EBUSY);
	CHECK(swapz_mm_broker_owner_retired(session, epoch + 1) == -ESTALE);
	struct swapz_mm_trial_scope requested = {
		.bdev = &mapper, .broker = owner.broker, .identity = 17,
		.session = session, .table_epoch = epoch, .target_epoch = 13,
		.area_epoch = 4, .first_sector = 56, .sector_count = 16, .swap_type = 2,
	};
	struct swapz_mm_route route = {
		.broker = owner.broker, .target_session = session, .table_epoch = epoch,
		.target_epoch = 13, .logical_page = 7, .dm_generation = 1,
	};
	atomic_store(&swapz_mm_area_epochs[2], 4);
	CHECK(!swapz_mm_capture_permitted());
	CHECK(!swapz_mm_trial_scope_publish(&requested, &opened));
	CHECK(opened.refs == 2 && swapz_mm_capture_permitted());
	CHECK(swapz_mm_trial_scope_stop_capture(18) == -ESTALE);
	struct page page = {0};
	struct swapz_mm_carrier carrier = {
		.bdev = &mapper, .page = &page, .sector = 56, .scope_identity = 17,
	};
	struct swapz_ticket_key key = {
		.area_epoch = 4, .store_sequence = 8, .slot_offset = 1,
		.target_session = session, .table_epoch = epoch, .target_epoch = 13,
		.logical_page = 7, .dm_generation = 1, .swap_type = 2,
		.length = 64, .decoded_length = 4096, .representation = SWAPZ_TICKET_ORIGINAL,
		.codec = SWAPZ_TICKET_LZ4, .version = 1,
	};
	CHECK(!swapz_ticket_broker_try_get(owner.broker, session, epoch, &carrier.cap));
	memset(carrier.scratch, 0xa5, key.length);
	key.crc = swapz_crc32c_bytes(carrier.scratch, key.length);
	memset(key.sha256, 0x33, sizeof(key.sha256));
	CHECK(!swapz_ticket_reserve(owner.broker, &key, &carrier.lease));
	CHECK(!swapz_ticket_seal(&carrier.lease, carrier.scratch, key.length));
	/* This busy owner models the preerase/SIO handover; all broker debt
	 * below is real. Neither the model nor stop invents a zero count. */
	atomic_set(&swapz_mm_busy, 1);
	struct bio_vec vec = {&page, 0, 4096};
	struct bio origin = {
		.bi_io_vec = &vec, .bi_bdev = &mapper, .bi_iter = {56, 4096, 0, 0},
		.bi_vcnt = 1, .bi_opf = REQ_OP_WRITE | REQ_SWAP,
	};
	CHECK(swapz_mm_bio_matches(&origin, &carrier));
	carrier.cap.epoch++;
	CHECK(!swapz_mm_bio_matches(&origin, &carrier));
	carrier.cap.epoch--;
	atomic_store(&swapz_mm_area_epochs[2], 5);
	CHECK(!swapz_mm_bio_matches(&origin, &carrier));
	atomic_store(&swapz_mm_area_epochs[2], 4);
	struct swapz_trial_observation_scope scope = manifest();
	CHECK(swapz_trial_observation_start(&scope, 32));
	swapz_mm_observation_capture(&carrier, &key);
	swapz_mm_observation_bind(&carrier);
	CHECK(carrier.observation.operation && carrier.observation_original);
	rcu_assign_pointer(origin.bi_swapz_original, &carrier);
	struct swapz_ticket_ref candidate = {0}, late = {0};
	CHECK(!swapz_mm_candidate_get(&origin, &candidate));
	struct swapz_observation_record correlation = {0};
	CHECK(swapz_mm_candidate_observation(&origin, &candidate, &correlation));

	/* A modeled pre-stop reader holds the real control transition in its
	 * grace period. The controller mutex must not be held during the wait. */
	struct stop_call call = {requested.identity, -1};
	pthread_t thread;
	rcu_read_lock();
	mutex_lock(&reader_mutex);
	unsigned prior_grace = grace_count;
	mutex_unlock(&reader_mutex);
	CHECK(!pthread_create(&thread, NULL, stop_thread, &call));
	mutex_lock(&reader_mutex);
	while (grace_count == prior_grace)
		if (pthread_cond_wait(&reader_changed, &reader_mutex))
			abort();
	mutex_unlock(&reader_mutex);
	CHECK(!swapz_mm_capture_permitted());
	CHECK(swapz_mm_trial_scope_matches_origin(&mapper, 64));
	CHECK(swapz_mm_trial_scope_stop_capture(18) == -ESTALE);
	CHECK(swapz_mm_trial_scope_stop_capture(requested.identity) == -EBUSY);
	CHECK(swapz_mm_trial_scope_revoke(requested.identity) == -EBUSY);
	CHECK(!swapz_mm_trial_scope_matches_route(&mapper, 56, 4, 2,
		SWAPZ_TICKET_LZ4, 64, &route));
	CHECK(swapz_mm_candidate_get(&origin, &late) == -EOPNOTSUPP && !late.broker);
	struct bio unbound = origin;
	unbound.bi_swapz_original = NULL;
	CHECK(!swapz_mm_bio_matches(&unbound, &carrier));
	CHECK(swapz_mm_bio_matches(&origin, &carrier));
	CHECK(swapz_mm_candidate_observation(&origin, &candidate, &correlation));
	rcu_read_unlock();
	CHECK(!pthread_join(thread, NULL) && !call.result);
	CHECK(grace_count == prior_grace + 1U);
	CHECK(swapz_mm_trial_scope_stop_capture(requested.identity) == -EALREADY);
	CHECK(swapz_mm_trial_scope_revoke(requested.identity) == -EBUSY);
	CHECK(opened.refs == 2 && swapz_mm_trial_scope_matches_origin(&mapper, 56));
	CHECK(!swapz_mm_trial_scope_matches_origin(&mapper, 72));
	struct swapz_ticket_view view = {0};
	CHECK(!swapz_ticket_view(&candidate, &view) && view.key.store_sequence == 8);
	swapz_mm_observation_endio(&carrier, EIO);
	rcu_assign_pointer(origin.bi_swapz_original, NULL);
	CHECK(!swapz_ticket_put(&candidate));
	CHECK(!swapz_ticket_put(&carrier.lease));
	CHECK(!swapz_ticket_broker_put(&carrier.cap));
	swapz_mm_observation_release(&carrier);
	atomic_set(&swapz_mm_busy, 0);

	CHECK(!swapz_mm_broker_owner_begin_close(session, epoch));
	CHECK(!swapz_ticket_broker_put(&owner));
	CHECK(swapz_mm_broker_owner_finish_close(session, epoch) == -EBUSY);
	CHECK(owner_broker.capability_refs == 1 && owner_allocations == 3);
	CHECK(swapz_mm_broker_owner_retired(session, epoch) == -EBUSY);
	CHECK(!swapz_mm_trial_scope_revoke(requested.identity) && opened.refs == 1);
	CHECK(!swapz_mm_trial_scope_matches_origin(&mapper, 56));
	CHECK(swapz_mm_trial_scope_revoke(requested.identity) == -ESTALE);
	CHECK(retry_queued == 1 && owner_retry_pending && owner_retry_armed);
	CHECK(swapz_mm_broker_owner_retired(session, epoch) == -EBUSY);
	if (explicit_finish) {
		CHECK(!swapz_mm_broker_owner_finish_close(session, epoch));
		CHECK(!owner_allocations && owner_retry_pending && !owner_retry_armed);
		/* The host has no native flush_work; pending work is explicit debt. */
		CHECK(swapz_mm_broker_owner_retired(session, epoch) == -EBUSY);
	}
	owner_retry_run();
	CHECK(!owner_allocations && !owner_broker.initialized && !owner_retry_pending);
	CHECK(!swapz_mm_broker_owner_retired(session, epoch));
	CHECK(swapz_mm_broker_owner_retired(session + 1, epoch) == -ESTALE);
	CHECK(swapz_mm_broker_owner_retired(session, epoch + 1) == -ESTALE);
	CHECK(!swapz_mm_broker_owner_retired(session, epoch));
	CHECK(retry_queued == 1);
	CHECK(swapz_trial_observation_stop(join_empty, NULL));
	CHECK(swapz_trial_observation_release() && !allocations);
	printf("R101_A11_HOST_ONLY mode=%s checks=%u retries=%u\n", argv[1], checks, retry_queued);
	return 0;
}
