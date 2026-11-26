/* SPDX-License-Identifier: GPL-2.0-only */
/* R098 new MM event and scope edges. Actual selected owner/adapter, actual
 * staged ticket owner/broker, actual extracted producer/core helpers.
 * Host file/RCU/BIO geometry and kernel scheduling primitives only.
 * Consumer discard records are explicitly fixture assertions, never native.
 */
#include "native-observation-owner-host-model.h"
#include "native-observation-owner.h"
#include "round092-module-shim.h"
#include "zswap-original-ticket.h"
#include <errno.h>
#include <openssl/sha.h>
#include <sys/stat.h>

static unsigned checks, allocations, owner_allocations, grace_count;
static unsigned reader_depth;
#define CHECK(condition) do { \
	++checks; \
	if (!(condition)) { \
		fprintf(stderr, "R098_A11_FIRST_ERROR line=%d: %s\n", __LINE__, #condition); \
		exit(77); \
	} \
} while (0)
bool model_try_cmpxchg(atomic_t *counter, int *previous, int next)
{
	return atomic_compare_exchange_strong_explicit(&counter->value, previous, next,
		memory_order_relaxed, memory_order_relaxed);
}
void model_read_lock(void) { ++reader_depth; }
void model_read_unlock(void) { if (!reader_depth) abort(); --reader_depth; }
void model_synchronize_rcu(void)
{
	if (reader_depth) abort();
	++grace_count;
}
void *model_kvcalloc(size_t count, size_t size, int flags)
{
	(void)flags;
	void *value = calloc(count, size);
	if (value) ++allocations;
	return value;
}
void model_kvfree(void *pointer)
{
	if (pointer) { if (!allocations) abort(); --allocations; free(pointer); }
}
void sha256(const u8 *bytes, unsigned int length, u8 *digest)
{
	if (!SHA256(bytes, length, digest)) abort();
}
void r094_owner_mutex_lock(pthread_mutex_t *lock) { mutex_lock(lock); }
void r094_owner_mutex_unlock(pthread_mutex_t *lock) { mutex_unlock(lock); }
void *r094_owner_allocate(size_t bytes)
{
	void *value = aligned_alloc(64, (bytes + 63U) & ~(size_t)63U);
	if (value) ++owner_allocations;
	return value;
}
void r094_owner_free(void *pointer)
{
	if (pointer) { if (!owner_allocations) abort(); --owner_allocations; free(pointer); }
}
void r094_owner_after_enter(void) {}
/* No retry scheduled in this new scope case: revoke releases its own cap
 * before owner close. Prior accepted autonomous retry is not replayed. */
void r096_owner_schedule_retry(void) { abort(); }

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
#include "r098-types.h"
struct bio { const struct swapz_mm_carrier *bi_swapz_original; bool exact_geometry; };
static bool swapz_mm_bio_matches(const struct bio *bio, const struct swapz_mm_carrier *carrier)
{
	return bio && bio->exact_geometry && carrier && carrier->lease.broker;
}
typedef unsigned int blk_status_t;
struct dm_io { u64 swapz_observation_operation, swapz_observation_original; bool requeue_flush_with_data, split; };
#define DM_IO_WAS_SPLIT 1
static bool dm_io_flagged(struct dm_io *io, unsigned int flag) { (void)flag; return io->split; }
static int blk_status_to_errno(blk_status_t status) { return status ? -EIO : 0; }
#include "r098-extracted.h"

static struct swapz_trial_observation_scope manifest(void)
{
	struct swapz_trial_observation_scope value = {
		.session = 11, .epoch = 12, .target_epoch = 13,
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
static bool sink(void *context, const u8 *bytes, size_t length)
{
	return fwrite(bytes, 1, length, context) == length;
}

int main(int argc, char **argv)
{
	if (argc != 3) return 2;
	const bool bound = !strcmp(argv[1], "bound");
	CHECK(bound || !strcmp(argv[1], "drop"));
	struct block_device mapper = {128, false}, wrong = {128, false};
	struct file opened = {{S_IFBLK}, &mapper, 1}, bad_file = {{S_IFBLK}, &wrong, 1};
	struct swapz_ticket_cap owner = {0};
	CHECK(!swapz_mm_broker_owner_open(8, 3568, 8 * 3568, &owner));
	struct swapz_mm_trial_scope requested = {
		.bdev = &mapper, .broker = owner.broker, .identity = 17,
		.session = owner.session, .table_epoch = owner.epoch,
		.target_epoch = 13, .area_epoch = 4, .first_sector = 56,
		.sector_count = 16, .swap_type = 2,
	};
	struct swapz_mm_route route = {
		.broker = owner.broker, .target_session = owner.session,
		.table_epoch = owner.epoch, .target_epoch = 13,
		.logical_page = 7, .dm_generation = 1,
	};
	atomic_store(&swapz_mm_area_epochs[2], 4);
	CHECK(!swapz_mm_capture_permitted());
	CHECK(swapz_mm_trial_scope_publish(&requested, &bad_file) == -EINVAL);
	struct swapz_mm_trial_scope bad = requested;
	bad.sector_count = 136;
	CHECK(swapz_mm_trial_scope_publish(&bad, &opened) == -EINVAL);
	bad = requested;
	bad.session++;
	CHECK(swapz_mm_trial_scope_publish(&bad, &opened) == -ESTALE);
	CHECK(opened.refs == 1 && !swapz_mm_capture_permitted());
	CHECK(!swapz_mm_trial_scope_publish(&requested, &opened));
	CHECK(opened.refs == 2 && swapz_mm_capture_permitted());
	CHECK(swapz_mm_trial_scope_matches_origin(&mapper, 64));
	CHECK(!swapz_mm_trial_scope_matches_origin(&mapper, 72));
	CHECK(!swapz_mm_trial_scope_matches_origin(&wrong, 56));
	CHECK(swapz_mm_trial_scope_matches_route(&mapper, 56, 4, 2,
		SWAPZ_TICKET_LZ4, 64, &route));
	CHECK(!swapz_mm_trial_scope_matches_route(&wrong, 56, 4, 2,
		SWAPZ_TICKET_LZ4, 64, &route));
	CHECK(!swapz_mm_trial_scope_matches_route(&mapper, 56, 4, 2,
		SWAPZ_TICKET_LZ4, 3569, &route));
	CHECK(swapz_mm_trial_scope_revoke(18) == -ESTALE && swapz_mm_capture_permitted());
	atomic_store(&swapz_mm_area_epochs[2], 5);
	CHECK(!swapz_mm_trial_scope_matches_route(&mapper, 56, 4, 2,
		SWAPZ_TICKET_LZ4, 64, &route));
	atomic_store(&swapz_mm_area_epochs[2], 4);
	CHECK(swapz_mm_trial_scope_publish(&requested, &opened) == -EBUSY);

	/* Actual sealed ticket and exact correlation, with host-only page
	 * geometry and known byte buffers. Recorder does not admit capture. */
	struct swapz_mm_carrier carrier = {0};
	struct swapz_ticket_key key = {
		.area_epoch = 4, .store_sequence = 8, .slot_offset = 1,
		.target_session = owner.session, .table_epoch = owner.epoch,
		.target_epoch = 13, .logical_page = 7, .dm_generation = 1,
		.swap_type = 2, .length = 64, .decoded_length = 4096,
		.representation = SWAPZ_TICKET_ORIGINAL, .codec = SWAPZ_TICKET_LZ4,
		.version = 1,
	};
	memset(carrier.scratch, 0xa5, key.length);
	key.crc = swapz_crc32c_bytes(carrier.scratch, key.length);
	memset(key.sha256, 0x33, sizeof(key.sha256));
	CHECK(!swapz_ticket_reserve(owner.broker, &key, &carrier.lease));
	CHECK(!swapz_ticket_seal(&carrier.lease, carrier.scratch, key.length));
	carrier.scope_identity = requested.identity;
	struct bio origin = {&carrier, true};
	struct swapz_ticket_ref candidate = {0};
	CHECK(!swapz_mm_candidate_get(&origin, &candidate));
	struct swapz_trial_observation_scope scope = manifest();
	CHECK(swapz_trial_observation_start(&scope, 32));
	swapz_mm_observation_capture(&carrier, &key);
	CHECK(carrier.observation.operation && carrier.observation.event == SWAPZ_OBS_CAPTURE &&
		!carrier.observation.original && !carrier.observation_original);
	if (bound) {
		swapz_mm_observation_bind(&carrier);
		struct swapz_observation_record correlation = {0};
		CHECK(swapz_mm_candidate_observation(&origin, &candidate, &correlation));
		CHECK(correlation.operation == carrier.observation.operation &&
			correlation.original == carrier.observation_original &&
			correlation.event == SWAPZ_OBS_CAPTURE && correlation.store == 8 &&
			!carrier.observation.original && carrier.observation.event == SWAPZ_OBS_CAPTURE);
		struct swapz_ticket_ref mismatched = candidate;
		++mismatched.generation;
		CHECK(!swapz_mm_candidate_observation(&origin, &mismatched, &correlation));
	}
	atomic_set(&swapz_mm_busy, 1);
	CHECK(swapz_mm_trial_scope_revoke(requested.identity) == -EBUSY &&
		opened.refs == 2 && !swapz_mm_capture_permitted() && grace_count == 1);
	CHECK(!swapz_mm_trial_scope_matches_route(&mapper, 56, 4, 2,
		SWAPZ_TICKET_LZ4, 64, &route));
	CHECK(!swapz_mm_trial_scope_matches_origin(&mapper, 56));
	struct swapz_ticket_ref late = {0};
	CHECK(swapz_mm_candidate_get(&origin, &late) == -EOPNOTSUPP && !late.broker);
	struct swapz_ticket_view view = {0};
	CHECK(!swapz_ticket_view(&candidate, &view) && view.key.store_sequence == 8);
	if (bound)
		swapz_mm_observation_endio(&carrier, EIO); /* actual MM producer event */
	CHECK(!swapz_ticket_put(&candidate) && !swapz_ticket_put(&carrier.lease));
	swapz_mm_observation_release(&carrier); /* after actual puts in this fixture */
	CHECK(!carrier.observation.operation && !carrier.observation_original);
	atomic_set(&swapz_mm_busy, 0);
	CHECK(!swapz_mm_trial_scope_revoke(requested.identity) && opened.refs == 1);
	CHECK(swapz_mm_trial_scope_publish(&requested, &opened) == -EBUSY);
	CHECK(swapz_mm_trial_scope_revoke(requested.identity) == -ESTALE);
	const u64 session = owner.session, epoch = owner.epoch;
	CHECK(!swapz_mm_broker_owner_begin_close(session, epoch));
	CHECK(!swapz_ticket_broker_put(&owner));
	CHECK(!swapz_mm_broker_owner_finish_close(session, epoch) && !owner_allocations);

	/* New original-core ACK helper; only discard consumer events are
	 * fixture assertions. Actual wire checker must see distinct IDs.
	 * Bound case deliberately lacks consumer lineage and must be BLOCKED. */
	struct dm_io io = {
		.swapz_observation_operation = swapz_trial_observation_mint(),
		.swapz_observation_original = swapz_trial_observation_mint(),
	};
	const u64 operation = io.swapz_observation_operation;
	const u64 original = io.swapz_observation_original;
	const u64 descriptor = swapz_trial_observation_mint();
	const u64 clone = swapz_trial_observation_mint();
	struct swapz_observation_record record = {
		.event = SWAPZ_OBS_ACCEPT, .operation = operation, .original = original,
		.descriptor = descriptor, .clone = clone, .logical = 8,
		.operation_kind = SWAPZ_OBS_DISCARD_BIO,
	};
	CHECK(swapz_trial_observation_append(&record));
	record = (struct swapz_observation_record){.event = SWAPZ_OBS_DISPATCH,
		.operation = operation, .flags = 1};
	CHECK(swapz_trial_observation_append(&record));
	record = (struct swapz_observation_record){.event = SWAPZ_OBS_DISCARD,
		.operation = operation, .new_generation = 1};
	CHECK(swapz_trial_observation_append(&record));
	record = (struct swapz_observation_record){.event = SWAPZ_OBS_CLONE_ENDIO,
		.operation = operation, .descriptor = descriptor, .clone = clone};
	CHECK(swapz_trial_observation_append(&record));
	dm_swapz_original_observation_endio(&io, false, 0);
	CHECK(!io.swapz_observation_operation && !io.swapz_observation_original);
	dm_swapz_original_observation_endio(&io, false, 0); /* no duplicate */
	record = (struct swapz_observation_record){.event = SWAPZ_OBS_CLEANUP, .flags = 7};
	CHECK(swapz_trial_observation_append(&record));
	CHECK(swapz_trial_observation_stop(join_empty, NULL));
	FILE *output = fopen(argv[2], "wb");
	CHECK(output && swapz_trial_observation_export(sink, output));
	CHECK(!fclose(output) && swapz_trial_observation_release() && !allocations);
	printf("R098_A11_HOST_ONLY mode=%s checks=%u\n", argv[1], checks);
	return 0;
}
