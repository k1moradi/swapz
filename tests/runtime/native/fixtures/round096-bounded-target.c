/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual extracted target helpers + staged owner/broker + real storage/codec.
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
struct bio { struct { u64 bi_sector; } bi_iter; void *bi_bdev; bool selected; };
struct swapz_bio_ref {
	struct bio *bio;
	bool list, preparation_list, preparation_inline, original_claimed;
	int preparation_submitter_active;
	void *prepared_page;
	struct swapz_ticket_ref original_candidate;
	struct swapz_ticket_view original_view;
	u64 original_registration_epoch, published_ns;
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
static u8 media[BLOCKS][SWAPZ_BLOCK_BYTES], page[SWAPZ_BLOCK_BYTES],
	fixture_compressed[SWAPZ_BLOCK_BYTES], compressed_read[SWAPZ_BLOCK_BYTES], fixture_output[SWAPZ_BLOCK_BYTES], upper_output[SWAPZ_BLOCK_BYTES];
static unsigned int checks, allocations, owner_allocations, writes, flushes, reads, terminal_calls;
static unsigned int claims, fallbacks, typed_reads, ordinary_preparations, claimed_errors, reopened;
static int fail_write, fail_flush, terminal_error;
static bool short_write;
static struct swapz_bio_ref *active_entry;
#define CHECK(condition) do { ++checks; if (!(condition)) { \
	fprintf(stderr, "R096_SEMANTIC_FAIL line=%d %s\n", __LINE__, #condition); exit(77); \
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
static bool dm_swapz_round090_selected_origin(struct dm_target *target, struct bio *bio)
{ return target == fixture_target.target && bio->selected; }
static bool dm_swapz_round091_accepted_clone_matches(struct dm_target *target, struct bio *bio)
{ return dm_swapz_round090_selected_origin(target, bio); }
static bool dm_swapz_round090_route_live(struct dm_target *target, void *bdev, u64 sector)
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

/* Short completion injected at the lower callback boundary; ordinary native
 * dm_io callback itself only reports complete block or error. */
static int short_lower(void *opaque, u32 block, const u8 *bytes, u32 length, u32 *completed)
{
	int error = swapz_round090_storage_write(opaque, block, bytes, length, completed);
	if (!error && short_write) --*completed;
	return error;
}
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
	fail_write = fail_flush = terminal_error = 0; short_write = false;
	mutex_lock(&fixture_target.ordered_owner); raw(1U); mutex_unlock(&fixture_target.ordered_owner);
	CHECK(queue_work(system_unbound_wq, &fixture_target.original_setup_work));
	flush_work(&fixture_target.original_setup_work);
	CHECK(!fixture_target.original_setup_error && fixture_target.original_listed && fixture_target.original_cap.broker);
	CHECK(allocations == 4U && owner_allocations == 3U && fixture_target.original_storage->authority == &fixture_target.authority);
	CHECK(fixture_target.original_snapshot_epoch == fixture_target.original_route.registration_epoch);
}
enum scenario { OK, STALE_ROUTE, STALE_INCARNATION, STALE_GENERATION, BUSY, SHORT, WRITE_ERROR, FLUSH_ERROR, LIVE_OFF, PREPARED, SCOPE_OFF };
static void exercise(u8 codec, enum scenario scenario)
{
	int table = 0;
	struct dm_target target = { .table = &table };
	struct bio bio = { .bi_iter = { SWAPZ_SECTORS }, .bi_bdev = &table, .selected = true };
	struct swapz_bio_ref entry = { .bio = &bio, .preparation_inline = true };
	struct swapz_ticket_ref source = {0}, candidate = {0}, external_carrier = {0};
	struct swapz_ticket_view view = {0};
	struct swapz_ticket_key key = {0};
	struct swapz_map predecessor;
	struct swapz_ticket_cap external = {0};
	u64 generation = 0, session, epoch, registration;
	u32 length = 0, reserve_start, next_sequence;
	unsigned int old_graces = grace_periods;
	bool handled, expected_claim = scenario == OK || scenario == SHORT ||
		scenario == WRITE_ERROR || scenario == FLUSH_ERROR;

	initialize(&target);
	session = fixture_target.original_owner_session; epoch = fixture_target.original_owner_epoch;
	registration = fixture_target.original_route.registration_epoch;
	predecessor = maps[1]; reserve_start = fixture_target.authority.next_block; next_sequence = fixture_target.authority.next_sequence;
	CHECK(!swapz_round091_ordered_claim_permitted());
	fixture_target.queue_lock = true;
	CHECK(swapz_round094_snapshot_next_locked(&fixture_target, 1U, &generation));
	fixture_target.queue_lock = false;
	CHECK(!round085_compress(codec, page, sizeof(page), fixture_compressed, sizeof(fixture_compressed), &length));
	key = (struct swapz_ticket_key){ .area_epoch = 3U, .store_sequence = 4U, .slot_offset = 8U,
		.target_session = session, .table_epoch = epoch, .target_epoch = fixture_target.original_route.target_epoch,
		.logical_page = 1U, .dm_generation = generation, .length = length,
		.decoded_length = SWAPZ_BLOCK_BYTES, .representation = SWAPZ_TICKET_ORIGINAL,
		.codec = codec, .version = 1U, .crc = swapz_crc32c_bytes(fixture_compressed, length) };
	CHECK(!swapz_zswap_import_sha256(page, key.sha256));
	CHECK(!swapz_ticket_broker_try_get(fixture_target.original_cap.broker, session, epoch, &external));
	CHECK(!swapz_ticket_reserve(external.broker, &key, &source));
	CHECK(!swapz_ticket_seal(&source, fixture_compressed, length));
	CHECK(!swapz_ticket_retain(&source, &candidate));
	CHECK(!swapz_ticket_retain(&source, &external_carrier));
	CHECK(!swapz_ticket_view(&candidate, &view));
	CHECK(!swapz_ticket_put(&source));
	fixture_target.queue_lock = true;
	CHECK(swapz_round091_retain_candidate_locked(&fixture_target, &entry, &candidate, &view));
	CHECK(!candidate.broker && entry.original_candidate.broker);
	swapz_round094_invalidate_locked(&fixture_target);
	entry.list = true; /* one already accepted descriptor */
	fixture_target.queue_lock = false;
	active_entry = &entry;
	mutex_lock(&fixture_target.ordered_owner);
	entry.list = false; /* ordered head dequeued once */
	if (scenario == STALE_ROUTE) {
		fixture_target.queue_lock = true;
		swapz_round089_revoke_route_locked(&fixture_target);
		fixture_target.queue_lock = false;
	}
	if (scenario == STALE_INCARNATION)
		--entry.original_registration_epoch;
	if (scenario == STALE_GENERATION) {
		raw(1U); /* actual ordinary authority publication, not a guessed generation */
		predecessor = maps[1]; reserve_start = fixture_target.authority.next_block; next_sequence = fixture_target.authority.next_sequence;
	}
	if (scenario == BUSY) CHECK(!pthread_mutex_lock(&external.broker->lock));
	if (scenario == PREPARED) { entry.prepared_page = page; ++ordinary_preparations; }
	if (scenario == SHORT) {
		short_write = true;
		fixture_target.original_decoder_bridge->lower_write = short_lower;
	}
	if (scenario == WRITE_ERROR) fail_write = -EIO;
	if (scenario == FLUSH_ERROR) fail_flush = -EIO;
	/* Positive permission only in this extracted rootless translation unit. */
	if (scenario == SCOPE_OFF) fixture_target.original_trial = false;
	handled = swapz_round091_process_candidate(&fixture_target, &entry, scenario != LIVE_OFF);
	fixture_target.original_trial = true;
	if (scenario == BUSY) CHECK(!pthread_mutex_unlock(&external.broker->lock));
	CHECK(handled == expected_claim);
	CHECK(!fixture_target.authority.in_flight && !fixture_target.authority.shared_unissued_sequence && !fixture_target.original_storage->pending_decoder);
	if (!handled) {
		CHECK(!terminal_calls && !writes && !flushes);
		CHECK(!memcmp(&maps[1], &predecessor, sizeof(predecessor)));
		CHECK(fixture_target.authority.next_block == reserve_start);
		CHECK(fixture_target.authority.next_sequence == next_sequence +
			((scenario == STALE_ROUTE || scenario == STALE_INCARNATION ||
			  scenario == BUSY || scenario == PREPARED) ? 1U : 0U));
		/* Real ordinary allocator/finish, modeled ordinary dispatch/endio. */
		++fallbacks;
		if (!entry.prepared_page) ++ordinary_preparations;
		raw(1U);
		swapz_complete(&bio, 0);
		CHECK(maps[1].raw && !(maps[1].state & SWAPZ_MAP_ORIGINAL));
	} else {
		CHECK(writes == 1U && terminal_calls == 1U);
		CHECK(flushes == ((scenario == SHORT || scenario == WRITE_ERROR) ? 0U : 1U));
		if (scenario == OK) {
			CHECK(!terminal_error && maps[1].generation == generation);
			CHECK(maps[1].payload_length == length &&
				!memcmp(media[maps[1].start_block] + maps[1].payload_offset, fixture_compressed, length));
			u64 retained_pin = 0;
			CHECK(!swapz_round096_read_original_pinned(&fixture_target.authority, fixture_target.original_storage,
				fixture_target.original_decoder_bridge, 1U, compressed_read, fixture_target.original_decode_scratch,
				fixture_target.original_decode_verified, fixture_output, &retained_pin));
			CHECK(retained_pin && swapz_shared_original_view(&fixture_target.authority, retained_pin));
			/* Modeled final upper copy, still under the actual authoritative pin. */
			memcpy(upper_output, fixture_output, sizeof(upper_output));
			CHECK(!memcmp(upper_output, page, sizeof(upper_output)) && reads == 1U);
			CHECK(!swapz_shared_original_put(&fixture_target.authority, retained_pin));
			++typed_reads;
		} else {
			CHECK(terminal_error == -EIO && !memcmp(&maps[1], &predecessor, sizeof(predecessor)));
		}
	}
	CHECK(terminal_calls == 1U);
	CHECK(!entry.original_candidate.broker && fixture_target.original_release_busy);
	CHECK(!swapz_prevalidate_discard_range(&fixture_target.authority, 1U, 1U));
	CHECK(!swapz_discard_page(&fixture_target.authority, 1U));
	CHECK(!fixture_target.original_decoder_bridge->active_reads && !fixture_target.original_decoder_bridge->active_tokens);
	mutex_unlock(&fixture_target.ordered_owner);
	/* Actual release work runs outside locks; preserve external cap to prove
	 * finish refuses until real outstanding references have drained. */
	fixture_target.queue_lock = true; fixture_target.accepting = false;
	swapz_round089_revoke_route_locked(&fixture_target);
	swapz_round094_invalidate_locked(&fixture_target);
	fixture_target.queue_lock = false;
	swapz_round090_unpublish_target(&fixture_target);
	CHECK(grace_periods == old_graces + 1U && !fixture_target.original_listed && !fixture_target.original_cap.broker);
	/* Deliberately invoke teardown before the deferred ticket put joins. */
	CHECK(queue_work(system_unbound_wq, &fixture_target.original_teardown_work));
	flush_work(&fixture_target.original_teardown_work);
	CHECK(fixture_target.original_teardown_error == -EBUSY && fixture_target.original_release_busy);
	CHECK(allocations == 4U && owner_allocations == 3U && fixture_target.original_storage);
	CHECK(!swapz_round096_target_can_free(&fixture_target, true));
	flush_work(&fixture_target.original_release_work);
	CHECK(!fixture_target.original_release_busy);
	CHECK(queue_work(system_unbound_wq, &fixture_target.original_teardown_work));
	flush_work(&fixture_target.original_teardown_work);
	CHECK(fixture_target.original_teardown_error == -EBUSY && fixture_target.original_owner_session == session);
	CHECK(!allocations && owner_allocations == 3U);
	/* Native R095 must quarantine. Model the independent future contract
	 * only after target debt is zero and explicitly witnessed as drained. */
	CHECK(!swapz_round096_target_can_free(&fixture_target, true));
	fixture_target.original_target_drained = true;
	CHECK(!swapz_round096_target_can_free(&fixture_target, false));
	CHECK(swapz_round096_target_can_free(&fixture_target, true));
	fixture_target.original_release_busy = 1;
	CHECK(!swapz_round096_target_can_free(&fixture_target, true));
	fixture_target.original_release_busy = 0;
	CHECK(swapz_ticket_revoke(external.broker, epoch + 1U) == -ESTALE);
	fixture_target.original_teardown_error = -EIO;
	CHECK(!swapz_round096_target_can_free(&fixture_target, true));
	fixture_target.original_teardown_error = -EBUSY;
	/* Model transfer of exact retry identity to permanent owner boundary.
	 * The frozen owner itself still requires explicit finish. No target work
	 * or target identity is used after this simulated detach. */
	target.private = NULL;
	memset(&fixture_target, 0, sizeof(fixture_target));
	CHECK(!swapz_ticket_broker_put(&external));
	CHECK(swapz_mm_broker_owner_finish_close(session, epoch) == -EBUSY);
	CHECK(!swapz_ticket_put(&external_carrier));
	CHECK(!swapz_mm_broker_owner_finish_close(session, epoch));
	CHECK(!owner_allocations);
	initialize(&target);
	CHECK(!fixture_target.original_setup_error && fixture_target.original_owner_session > session &&
		fixture_target.original_route.registration_epoch > registration);
	++reopened;
	fixture_target.queue_lock = true; fixture_target.accepting = false;
	swapz_round089_revoke_route_locked(&fixture_target);
	swapz_round094_invalidate_locked(&fixture_target);
	fixture_target.queue_lock = false;
	swapz_round090_unpublish_target(&fixture_target);
	CHECK(queue_work(system_unbound_wq, &fixture_target.original_teardown_work));
	flush_work(&fixture_target.original_teardown_work);
	CHECK(!fixture_target.original_teardown_error && !allocations && !owner_allocations);
	fixture_target.original_target_drained = true;
	CHECK(swapz_round096_target_can_free(&fixture_target, false));
	active_entry = NULL;
}
int main(void)
{
	for (u32 index = 0; index < sizeof(page); ++index)
		page[index] = (u8)(index % 127U == 0U ? 0x5aU : 0U);
	/* Changed read-pin and detach paths only; no replay of accepted corpus. */
	exercise(1U, OK);
	exercise(2U, OK);
	exercise(1U, WRITE_ERROR);
	exercise(2U, PREPARED);
	exercise(1U, SCOPE_OFF);
	CHECK(claims == 3U && claimed_errors == 1U && typed_reads == 2U &&
		fallbacks == 2U && ordinary_preparations == 2U && reopened == 5U);
	printf("PASS R096_COMPOSED checks=%u claims=%u errors=%u reads=%u fallbacks=%u preparations=%u reopens=%u AUTH0\n",
		checks, claims, claimed_errors, typed_reads, fallbacks, ordinary_preparations, reopened);
	return 0;
}
