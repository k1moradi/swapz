/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual extracted gated target + staged autonomous owner retry + original codecs.
 * Only Linux primitives, selected BIO identity, lower media and upper endio
 * are host boundaries. Never a native entry or an authentication credential.
 */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "round094-owner-shim.h"
#include "zswap-original-ticket.h"
#include "zswap-original-storage.h"
#include "zswap-original-decoder-bridge.h"
#include "zswap-original-storage-shared-decoder.h"
#include "engine.h"

typedef swapz_u64 u64;
typedef swapz_u32 u32;
typedef swapz_u16 u16;
typedef swapz_u8 u8;
typedef int64_t s64;
typedef s64 atomic64_t;
#define ATOMIC64_INIT(value) (value)
#define S64_MAX INT64_MAX
#define U32_MAX UINT32_MAX
#define SWAPZ_SECTORS 8U
#define SWAPZ_ROUND094_GENERATION_PAGES 16U
#define SWAPZ_ROUND094_BROKER_SLOTS 8U
#define MAX_SWAPFILES 32U
#define SWAPZ_CLOSE_OTHER 0
#define REQ_OP_WRITE 1
#define REQ_OP_READ 0
#define __maybe_unused __attribute__((unused))
#define SWAPZ_ROUND094_TARGET_OWNER_TEST 1
#define SWAPZ_ROUND097_GATED_TARGET_TEST 1
#define SWAPZ_ROUND096_OWNER_RETRY_TEST 1
#define SWAPZ_ROUND097_TARGET_OBSERVATION_TEST 1
#define SWAPZ_ROUND098_SCOPED_TARGET_TEST 1
#define SWAPZ_SCOPED_TARGET_OBSERVATION 1
#define SWAPZ_NATIVE_OBSERVATION_ADAPTER 1
#define spin_trylock_irqsave(lock, flags) ((flags) = 0, *(lock) ? false : (*(lock) = true))
typedef u64 sector_t;
struct block_device { unsigned int identity; };
#include "r098-types.h"
bool swapz_trial_observation_active(void);
u64 swapz_trial_observation_mint(void);
bool swapz_trial_observation_append(const struct swapz_observation_record *);
void sha256(const u8 *, unsigned int, u8 *);
bool r098_recorder_start(u64, u64, u64, u64);
bool r098_recorder_finish(unsigned int, unsigned int);
#define READ_ONCE(value) (value)
#define smp_load_acquire(pointer) (*(pointer))
#define lockdep_assert_held(lock) assert(*(lock))
#define spin_lock_irqsave(lock, flags) do { assert(!*(lock)); *(lock) = true; (flags) = 0; } while (0)
#define spin_unlock_irqrestore(lock, flags) do { assert(*(lock)); *(lock) = false; (void)(flags); } while (0)
#define mutex_lock(lock) do { assert(!*(lock)); *(lock) = true; } while (0)
#define mutex_unlock(lock) do { assert(*(lock)); *(lock) = false; } while (0)
#define list_empty(list) (!*(list))
#define atomic_read(pointer) (*(pointer))
#define atomic_set_release(pointer, value) (*(pointer) = (value))
#define rcu_read_lock() ((void)0)
#define rcu_read_unlock() ((void)0)
#define WARN_ON_ONCE(condition) ((condition) ? (abort(), true) : false)
#define container_of(pointer, type, member) ((type *)((char *)(pointer) - offsetof(type, member)))
static s64 atomic64_read(const atomic64_t *sequence) { return *sequence; }
static s64 atomic64_cmpxchg(atomic64_t *sequence, s64 old, s64 next)
{
	s64 observed = *sequence;
	if (observed == old) *sequence = next;
	return observed;
}
static int atomic_cmpxchg_acquire(int *value, int old, int next)
{
	int observed = *value;
	if (observed == old) *value = next;
	return observed;
}
struct work_struct { void (*function)(struct work_struct *); bool pending; };
static bool queue_work(int queue, struct work_struct *work)
{
	(void)queue;
	if (work->pending) return false;
	work->pending = true;
	return true;
}
static void flush_work(struct work_struct *work)
{
	if (work->pending) {
		work->pending = false;
		work->function(work);
	}
}
#define system_unbound_wq 0
static bool swapz_round090_registry_mutex, swapz_round090_targets;
static unsigned int grace_periods;
static void list_add_tail_rcu(bool *node, bool *head)
{ assert(!*node && !*head); *node = *head = true; }
static void list_del_rcu(bool *node)
{ assert(*node && swapz_round090_targets); *node = swapz_round090_targets = false; }
static void synchronize_rcu(void) { ++grace_periods; }
#define INIT_LIST_HEAD(node) (*(node) = false)
struct dm_target { void *private; void *table; u64 begin; };
struct bio {
	struct { u64 bi_sector; } bi_iter;
	struct block_device *bi_bdev;
	bool selected;
	const struct swapz_mm_carrier *bi_swapz_original;
};
static bool swapz_mm_bio_matches(const struct bio *bio, const struct swapz_mm_carrier *carrier)
{
	return bio && bio->selected && carrier && carrier->lease.broker &&
		bio->bi_bdev == carrier->bdev && bio->bi_iter.bi_sector == carrier->sector;
}
#define rcu_dereference(value) (value)
#include "r098-mm.h"
/* Explicit host boundary: query calls the actual frozen R097 predicate.
 * This does not implement the new R098 native scope publication. */
static struct swapz_mm_trial_scope published_scope;
static bool swapz_mm_trial_scope_matches_route(struct block_device *bdev, sector_t sector,
	u64 area, u32 type, u8 codec, u32 length, const struct swapz_mm_route *route)
{
	return swapz_mm_scope_matches(&published_scope, bdev, sector, area, type, codec, length, route);
}
struct swapz_bio_ref {
	struct bio *bio;
	bool list, preparation_list, preparation_inline, original_claimed;
	int preparation_submitter_active;
	void *prepared_page;
	struct swapz_ticket_ref original_candidate;
	struct swapz_ticket_view original_view;
	u64 original_registration_epoch, published_ns, original_scope_identity;
	u64 observation_operation, observation_original, observation_clone, observation_descriptor, observation_extent;
	u8 observation_compressed_sha256[32];
};
#include "route-record.h"
static atomic64_t swapz_round089_route_sequence = ATOMIC64_INIT(0);
struct swapz_dm {
	struct dm_target *target;
	bool accepting, failed, ordered_owner, queue_lock, async_prepare;
	bool incoming, preparation_incoming, preparation_queued, batch_count, inflight;
	struct { bool active; } gc_recovery;
	struct swapz_authority authority;
	struct swapz_map *maps;
	u32 logical_pages;
	struct swapz_round089_route original_route;
	struct swapz_ticket_cap original_cap, original_retired_cap;
	struct swapz_shared_storage *original_storage;
	struct swapz_original_decoder_bridge *original_decoder_bridge;
	u8 *original_decode_scratch, *original_decode_verified;
	u64 original_owner_session, original_owner_epoch, original_snapshot_epoch;
	u32 original_generations[SWAPZ_ROUND094_GENERATION_PAGES];
	bool original_trial, original_bridge_ready, original_storage_ready, original_owner_closing;
	bool original_target_drained;
	struct swapz_shared_storage_decoder *original_gated_storage;
	bool original_epoch_consumed, original_retry_transferred;
	struct swapz_mm_trial_scope original_scope;
	u64 original_scope_used_session;
	struct swapz_bio_ref *observation_commit;
	u64 observation_release_operation, observation_release_descriptor;
	bool original_listed, original_registry;
	struct work_struct original_setup_work, original_teardown_work, original_cap_release_work, original_release_work;
	struct swapz_ticket_ref original_release_ref;
	int original_release_busy, original_setup_error, original_teardown_error, next_window_close;
	u64 logical_write_bytes, compressed_pages;
};

enum { PAGES = 64, BLOCKS = 2048, SEGS = BLOCKS / SWAPZ_SEGMENT_BLOCKS };
static struct swapz_dm fixture_target;
static struct swapz_map maps[PAGES];
static u16 live[BLOCKS], min_blocks[SEGS];
static u8 classes[BLOCKS], roles[SEGS], delta[BLOCKS];
static u32 counts[SEGS], programs[SEGS], bases[SEGS], first[SEGS], last[SEGS];
static u32 prev[PAGES], next[PAGES], costs[SEGS], live_bytes[SEGS];
static u8 media[BLOCKS][SWAPZ_BLOCK_BYTES], page[SWAPZ_BLOCK_BYTES], fixture_compressed[SWAPZ_BLOCK_BYTES];
static unsigned int checks, allocations, owner_allocations, writes, flushes, reads, terminal_calls;
static unsigned int claims, fallbacks, claimed_errors;
static bool retry_pending;
static int fail_write, fail_flush, terminal_error;
static struct swapz_bio_ref *active_entry;
#define CHECK(condition) do { ++checks; if (!(condition)) { \
	fprintf(stderr, "R098_SEMANTIC_FAIL line=%d %s\n", __LINE__, #condition); exit(77); \
} } while (0)
void r094_owner_mutex_lock(pthread_mutex_t *lock) { assert(!fixture_target.queue_lock && !fixture_target.ordered_owner); assert(!pthread_mutex_lock(lock)); }
void r094_owner_mutex_unlock(pthread_mutex_t *lock) { assert(!pthread_mutex_unlock(lock)); }
void *r094_owner_allocate(size_t bytes)
{
	void *address = aligned_alloc(64, (bytes + 63U) & ~(size_t)63U);
	if (address) ++owner_allocations;
	return address;
}
void r094_owner_free(void *address)
{
	if (address) { assert(owner_allocations); --owner_allocations; free(address); }
}
void r094_owner_after_enter(void) {}
/* Only Linux workqueue scheduling is substituted: the staged owner worker
 * itself executes the real retry implementation, with no target pointer.
 */
void r097_run_builtin_retry(void);
void r096_owner_schedule_retry(void)
{
	CHECK(!retry_pending);
	retry_pending = true;
}
static void *vzalloc(size_t bytes)
{
	assert(fixture_target.ordered_owner && !fixture_target.queue_lock);
	void *address = calloc(1, bytes);
	if (address) ++allocations;
	return address;
}
static void vfree(void *address)
{
	assert(fixture_target.ordered_owner && !fixture_target.queue_lock);
	if (address) { assert(allocations); --allocations; free(address); }
}
static bool swapz_has_inflight(const struct swapz_dm *target) { return target->inflight; }
static const struct bio *dm_swapz_round090_selected_origin(struct dm_target *target, struct bio *bio)
{ return target == fixture_target.target && bio->selected ? bio : NULL; }
static bool dm_swapz_round091_accepted_clone_matches(struct dm_target *target, struct bio *bio)
{ return dm_swapz_round090_selected_origin(target, bio) != NULL; }
static bool dm_swapz_round090_route_live(struct dm_target *target, struct block_device *bdev, u64 sector)
{ return target == fixture_target.target && bdev == fixture_target.target->table && sector == SWAPZ_SECTORS && fixture_target.original_listed; }
static int swapz_lower(void *opaque, int operation, u32 block, u8 blocks, u8 *bytes)
{
	CHECK(opaque == &fixture_target && fixture_target.ordered_owner && !fixture_target.queue_lock && block < BLOCKS && blocks == 1U);
	if (operation == REQ_OP_WRITE) {
		CHECK(fixture_target.authority.in_flight && !fixture_target.authority.shared_unissued_sequence && !live[block]);
		CHECK(active_entry && active_entry->original_claimed);
		++writes;
		memcpy(media[block], bytes, SWAPZ_BLOCK_BYTES);
		return fail_write;
	}
	CHECK(operation == REQ_OP_READ);
	++reads;
	memcpy(bytes, media[block], SWAPZ_BLOCK_BYTES);
	return 0;
}
static int swapz_lower_read(void *opaque, u32 block, u8 blocks, u8 *bytes)
{ return swapz_lower(opaque, REQ_OP_READ, block, blocks, bytes); }
static int swapz_issue_flush(void *opaque)
{
	CHECK(opaque == &fixture_target && fixture_target.ordered_owner && !fixture_target.queue_lock && fixture_target.authority.in_flight);
	++flushes;
	return fail_flush;
}
static int swapz_flush_window(struct swapz_dm *target) { CHECK(target == &fixture_target && !target->batch_count); return 0; }
static int swapz_finalize_all_inflight(struct swapz_dm *target, bool wait)
{ CHECK(target == &fixture_target && wait && !target->inflight); return 0; }
static void swapz_invalidate_read_caches(struct swapz_dm *target) { CHECK(target == &fixture_target); }
static void swapz_fail(struct swapz_dm *target, int error) { CHECK(target == &fixture_target && error); target->failed = true; }
static u64 ktime_get_ns(void) { return 1U; }
static void swapz_count_verified_zswap_writeback_commit(struct swapz_dm *target, struct bio *bio)
{ CHECK(target == &fixture_target && bio == active_entry->bio); }
static void swapz_complete(struct bio *, int);
typedef struct { u64 val; } swp_entry_t;
/* Host-only reversible swap identity encoding, not a native swp_entry claim. */
static swp_entry_t swp_entry(u32 type, u64 offset)
{ return (swp_entry_t){ ((u64)type << 56U) | offset }; }
static u32 swp_type(swp_entry_t slot) { return (u32)(slot.val >> 56U); }
static u64 swp_offset(swp_entry_t slot) { return slot.val & UINT64_C(0x00ffffffffffffff); }

#include "target-fragments.h"

static void swapz_complete(struct bio *bio, int error)
{
	CHECK(active_entry && active_entry->bio == bio && !terminal_calls);
	CHECK(!fixture_target.queue_lock);
	if (active_entry->original_claimed) {
		++claims;
		if (error) ++claimed_errors;
		else CHECK((maps[1].state & SWAPZ_MAP_ORIGINAL) && flushes == 1U);
	}
	++terminal_calls;
	terminal_error = error;
	swapz_round091_release_candidate(&fixture_target, active_entry);
	/* Modeled DM core invokes actual event helper at clone completion. */
	swapz_scope_observe_clone(active_entry, error);
}

int round085_compress(u8 codec, const u8 *source, u32 length, u8 *destination, u32 capacity, u32 *written);

static void raw(u32 logical)
{
	struct swapz_tx transaction;
	CHECK(!swapz_stage(&fixture_target.authority, &logical, 1U, 1U, &transaction));
	CHECK(!swapz_finish_raw(&fixture_target.authority, &transaction, page, 1U, 0));
}
static void initialize(struct dm_target *target)
{
	CHECK(!allocations && !owner_allocations && !swapz_round090_targets);
	memset(&fixture_target, 0, sizeof(fixture_target));
	fixture_target.target = target; target->private = &fixture_target;
	fixture_target.maps = maps; fixture_target.logical_pages = PAGES; fixture_target.accepting = true; fixture_target.original_trial = true;
	fixture_target.async_prepare = true;
	fixture_target.original_setup_work.function = swapz_round094_setup_work;
	fixture_target.original_teardown_work.function = swapz_round094_teardown_work;
	fixture_target.original_cap_release_work.function = swapz_round090_cap_release_work;
	fixture_target.original_release_work.function = swapz_round090_release_work;
	CHECK(!swapz_authority_init(&fixture_target.authority, maps, live, classes, PAGES, BLOCKS));
	CHECK(!swapz_enable_segment_rotation(&fixture_target.authority, roles, SEGS));
	CHECK(!swapz_enable_segment_mapping_counts(&fixture_target.authority, counts, SEGS));
	CHECK(!swapz_enable_segment_program_counts(&fixture_target.authority, programs, SEGS));
	CHECK(!swapz_enable_segment_page_lists(&fixture_target.authority, first, last, prev, next, SEGS, PAGES));
	CHECK(!swapz_enable_segment_gc_accounting(&fixture_target.authority, live_bytes, costs, min_blocks, SEGS));
	CHECK(!swapz_enable_extent_sequence_index(&fixture_target.authority, delta, bases, SEGS));
	fixture_target.authority.reuse_dead_segments = 1;
	writes = flushes = reads = terminal_calls = 0;
	fail_write = fail_flush = terminal_error = 0;
	mutex_lock(&fixture_target.ordered_owner); raw(1U); mutex_unlock(&fixture_target.ordered_owner);
	CHECK(queue_work(system_unbound_wq, &fixture_target.original_setup_work));
	flush_work(&fixture_target.original_setup_work);
	CHECK(!fixture_target.original_setup_error && fixture_target.original_listed && fixture_target.original_cap.broker);
	CHECK(allocations == 3U && owner_allocations == 3U &&
		fixture_target.original_storage == &fixture_target.original_gated_storage->storage &&
		fixture_target.original_storage->authority == &fixture_target.authority &&
		!fixture_target.original_decoder_bridge && fixture_target.original_epoch_consumed &&
		fixture_target.original_gated_storage->epoch == fixture_target.original_cap.session &&
		swapz_round097_decoder_gate.owner == &fixture_target.original_gated_storage->provider);
	mutex_lock(&fixture_target.ordered_owner);
	u64 duplicate = 99U;
	CHECK(swapz_round097_reserve_epoch(&fixture_target, &duplicate) == -ESTALE && duplicate == 99U);
	mutex_unlock(&fixture_target.ordered_owner);
	CHECK(fixture_target.original_snapshot_epoch == fixture_target.original_route.registration_epoch);
}
/* Each execution is a fresh one-shot recorder owner. Exercise only the
 * newly connected scoped path, not R097 retry/read/codec acceptance corpus.
 */
int main(int argc, char **argv)
{
	struct block_device device = {1U}, other = {2U};
	struct dm_target target = { .table = &device };
	struct swapz_mm_carrier carrier = {};
	struct bio bio = { .bi_iter = { SWAPZ_SECTORS }, .bi_bdev = &device,
		.selected = true, .bi_swapz_original = &carrier };
	struct swapz_bio_ref entry = { .bio = &bio, .preparation_inline = true };
	struct swapz_ticket_ref candidate = {};
	struct swapz_ticket_view view = {};
	struct swapz_ticket_key key = {};
	struct swapz_observation_record producer = {}, wrong;
	struct swapz_mm_trial_scope scope;
	u64 generation = 0, session, epoch;
	u32 length = 0, next_sequence;
	bool revoked, handled;

	CHECK(argc == 2);
	revoked = !strcmp(argv[1], "revoked");
	CHECK(revoked || !strcmp(argv[1], "connected"));
	CHECK(!swapz_original_decoder_shared_gate_init(&swapz_round097_decoder_gate));
	for (u32 index = 0; index < sizeof(page); ++index)
		page[index] = (u8)(index % 127U == 0U ? 0x5aU : 0U);
	initialize(&target);
	session = fixture_target.original_owner_session;
	epoch = fixture_target.original_owner_epoch;
	scope = (struct swapz_mm_trial_scope){
		.bdev = &device, .broker = fixture_target.original_cap.broker,
		.identity = 19U, .session = session, .table_epoch = epoch,
		.target_epoch = fixture_target.original_route.target_epoch, .area_epoch = 3U,
		.first_sector = 8U, .sector_count = 8U, .swap_type = 2U,
	};
	CHECK(!swapz_round091_ordered_claim_permitted());
	swapz_round090_candidate_get(&target, &bio, &candidate, &view, &entry);
	CHECK(!candidate.broker);
	fixture_target.queue_lock = true;
	CHECK(!swapz_scope_route_ready_locked(&fixture_target, &device, 8U));
	CHECK(swapz_scope_install_locked(&fixture_target, &scope) == -ESTALE);
	published_scope = scope;
	CHECK(!swapz_scope_install_locked(&fixture_target, &scope));
	CHECK(swapz_scope_install_locked(&fixture_target, &scope) == -ESTALE);
	CHECK(swapz_scope_route_ready_locked(&fixture_target, &device, 8U));
	CHECK(!swapz_scope_route_ready_locked(&fixture_target, &other, 8U));
	CHECK(!swapz_scope_route_ready_locked(&fixture_target, &device, 16U));
	CHECK(swapz_round094_snapshot_next_locked(&fixture_target, 1U, &generation));
	fixture_target.queue_lock = false;

	CHECK(!round085_compress(1U, page, sizeof(page), fixture_compressed, sizeof(fixture_compressed), &length));
	key = (struct swapz_ticket_key){ .area_epoch = scope.area_epoch, .store_sequence = 4U, .slot_offset = 8U,
		.target_session = session, .table_epoch = epoch, .target_epoch = scope.target_epoch,
		.logical_page = 1U, .dm_generation = generation, .swap_type = scope.swap_type,
		.length = length, .decoded_length = SWAPZ_BLOCK_BYTES, .representation = SWAPZ_TICKET_ORIGINAL,
		.codec = 1U, .version = 1U, .crc = swapz_crc32c_bytes(fixture_compressed, length) };
	CHECK(!swapz_zswap_import_sha256(page, key.sha256));
	CHECK(!swapz_ticket_reserve(scope.broker, &key, &carrier.lease));
	CHECK(!swapz_ticket_seal(&carrier.lease, fixture_compressed, length));
	carrier.bdev = &device;
	carrier.sector = 8U;

	/* Host-only source observation seed, because frozen R097 producer's
	 * later event builders are invalid. Actual accessor consumes the
	 * retained real ticket; no native producer success is inferred. */
	CHECK(r098_recorder_start(session, epoch, scope.target_epoch,
		fixture_target.original_route.registration_epoch));
	producer = (struct swapz_observation_record){
		.event = SWAPZ_OBS_CAPTURE, .operation = swapz_trial_observation_mint(),
		.operation_kind = SWAPZ_OBS_TYPED_WRITE, .slot = key.slot_offset,
		.area_epoch = key.area_epoch, .store = key.store_sequence,
		.logical = (u32)key.logical_page, .generation = (u32)generation, .swap_type = key.swap_type,
		.compressed_length = length, .decoded_length = SWAPZ_BLOCK_BYTES,
		.codec = key.codec, .tag = key.representation, .version = key.version,
	};
	sha256(fixture_compressed, length, producer.compressed_sha256);
	memcpy(producer.page_sha256, key.sha256, 32);
	CHECK(swapz_trial_observation_append(&producer));
	producer.original = swapz_trial_observation_mint();
	CHECK(swapz_trial_observation_append(&(struct swapz_observation_record){
		.event = SWAPZ_OBS_BIND, .operation = producer.operation, .original = producer.original }));
	carrier.observation = producer;
	wrong = producer;
	++wrong.slot;
	CHECK(!swapz_scope_observation_bind(&entry, &wrong, &key));
	CHECK(!entry.observation_operation);
	swapz_round090_candidate_get(&target, &bio, &candidate, &view, &entry);
	CHECK(candidate.broker && entry.observation_operation == producer.operation &&
		entry.observation_original == producer.original &&
		entry.observation_clone != entry.observation_original &&
		entry.observation_descriptor != entry.observation_clone);
	struct swapz_ticket_ref stale = candidate; /* comparison-only copy, not a lease */
	++stale.generation;
	CHECK(!swapz_mm_candidate_observation(&bio, &stale, &wrong));
	fixture_target.queue_lock = true;
	CHECK(!swapz_scope_key_matches_locked(&fixture_target, &device, 8U, &key, scope.identity + 1U));
	CHECK(swapz_round091_retain_candidate_locked(&fixture_target, &entry, &candidate, &view));
	CHECK(!candidate.broker && entry.original_scope_identity == scope.identity);
	entry.list = true;
	swapz_scope_observe_accept(&entry);
	swapz_round094_invalidate_locked(&fixture_target);
	fixture_target.queue_lock = false;
	active_entry = &entry;
	mutex_lock(&fixture_target.ordered_owner);
	entry.list = false;
	next_sequence = fixture_target.authority.next_sequence;
	if (revoked)
		published_scope = (struct swapz_mm_trial_scope){};
	handled = swapz_round091_process_candidate(&fixture_target, &entry,
		entry.original_scope_identity != 0);
	CHECK(handled == !revoked);
	CHECK(!fixture_target.authority.in_flight && !fixture_target.original_storage->pending_decoder);
	if (revoked) {
		CHECK(!writes && !flushes && !terminal_calls && maps[1].raw);
		CHECK(fixture_target.authority.next_sequence == next_sequence + 1U);
		++fallbacks;
		raw(1U);
		swapz_complete(&bio, 0);
	} else {
		CHECK(writes == 1U && flushes == 1U && terminal_calls == 1U && !terminal_error);
		CHECK(maps[1].generation == generation && maps[1].payload_length == length &&
			!memcmp(media[maps[1].start_block] + maps[1].payload_offset, fixture_compressed, length));
	}
	CHECK(!entry.observation_operation && fixture_target.original_release_busy);
	mutex_unlock(&fixture_target.ordered_owner);
	flush_work(&fixture_target.original_release_work);
	CHECK(!fixture_target.original_release_busy);
	CHECK(!swapz_ticket_put(&carrier.lease));
	/* Host controller drain only, not proof of real core original endio. */
	fixture_target.queue_lock = true;
	fixture_target.accepting = false;
	swapz_round089_revoke_route_locked(&fixture_target);
	swapz_round094_invalidate_locked(&fixture_target);
	CHECK(!fixture_target.original_scope.identity);
	fixture_target.queue_lock = false;
	published_scope = (struct swapz_mm_trial_scope){};
	swapz_round090_unpublish_target(&fixture_target);
	fixture_target.original_target_drained = true;
	mutex_lock(&fixture_target.ordered_owner);
	CHECK(!swapz_round097_retire_target_records(&fixture_target));
	mutex_unlock(&fixture_target.ordered_owner);
	CHECK(queue_work(system_unbound_wq, &fixture_target.original_teardown_work));
	flush_work(&fixture_target.original_teardown_work);
	CHECK(!allocations && !owner_allocations && !retry_pending);
	CHECK(swapz_round096_target_can_free(&fixture_target, false));
	CHECK(claims == (revoked ? 0U : 1U) && fallbacks == (revoked ? 1U : 0U));
	CHECK(r098_recorder_finish(revoked ? 10U : 12U, revoked ? SWAPZ_OBS_LOST_INVALID : 0U));
	printf("PASS R098_SCOPED mode=%s checks=%u claims=%u fallbacks=%u events=%u loss=%u AUTH0\n",
		argv[1], checks, claims, fallbacks, revoked ? 10U : 12U,
		revoked ? SWAPZ_OBS_LOST_INVALID : 0U);
	return 0;
}
