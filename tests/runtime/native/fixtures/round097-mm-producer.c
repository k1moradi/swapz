/* SPDX-License-Identifier: GPL-2.0-only */
/* New R097 edges: actual staged scope/correlation helpers and R096 owner.
 * Linux RCU, module, workqueue, digest and wrapper primitives are modeled.
 * No runtime admission, native capture, or replay of the accepted corpus.
 */
#include <errno.h>
#include <string.h>
#include <stdint.h>
#include "round094-owner-shim.h"
#include "r097-broker.c"

static unsigned int checks, allocations, scheduled, executed, grace_calls;
static bool pending, release_during_worker;
static struct swapz_ticket_cap *release_cap;
#define CHECK(condition, witness) do { \
	++checks; \
	if (!(condition)) { \
		fprintf(stderr, "R097_A11_FIRST_ERROR %s line=%d\n", witness, __LINE__); \
		exit(77); \
	} \
} while (0)
static void must(int error)
{
	if (error)
		exit(78);
}
void r094_owner_mutex_lock(pthread_mutex_t *lock) { must(pthread_mutex_lock(lock)); }
void r094_owner_mutex_unlock(pthread_mutex_t *lock)
{
	must(pthread_mutex_unlock(lock));
	/* Deterministic interleaving: after the running retry consumed its
	 * queued slot but before it observes remaining broker debt. This
	 * substitutes a competing put at exactly that unlocked boundary.
	 */
	if (lock == &owner_gate_lock && release_during_worker && !owner_retry_pending) {
		release_during_worker = false;
		CHECK(release_cap && release_cap->broker &&
		      !swapz_ticket_broker_put(release_cap), "release_while_retry_running");
	}
}
void *r094_owner_allocate(size_t bytes)
{
	void *pointer = aligned_alloc(64, (bytes + 63U) & ~(size_t)63U);
	if (pointer)
		++allocations;
	return pointer;
}
void r094_owner_free(void *pointer)
{
	if (pointer) {
		must(allocations ? 0 : EINVAL);
		--allocations;
		free(pointer);
	}
}
void r094_owner_after_enter(void) {}
void r096_owner_schedule_retry(void)
{
	must(pending ? EALREADY : 0);
	pending = true;
	++scheduled;
}
static void run_retry(void)
{
	must(pending ? 0 : EINVAL);
	pending = false; /* model workqueue's running, no longer pending state */
	++executed;
	owner_retry_run();
}

typedef swapz_u8 u8;
typedef swapz_u32 u32;
typedef swapz_u64 u64;
typedef u64 sector_t;
#define U32_MAX UINT32_MAX
struct block_device { unsigned int identity; };
struct page { unsigned int identity; };
struct work_struct { unsigned int unused; };
#include "r097-types.h"
struct bio {
	const struct swapz_mm_carrier *bi_swapz_original;
	bool exact_geometry;
};
static struct swapz_mm_carrier swapz_mm_carrier;
static atomic_int swapz_mm_busy;
static unsigned int reader_depth;
#define rcu_dereference(value) (value)
#define WARN_ON_ONCE(value) (value)
#define atomic_set_release(pointer, value) atomic_store_explicit(pointer, value, memory_order_release)
static void rcu_read_lock(void) { ++reader_depth; }
static void rcu_read_unlock(void) { must(reader_depth ? 0 : EINVAL); --reader_depth; }
static void synchronize_rcu(void)
{
	CHECK(!reader_depth, "release_grace");
	++grace_calls;
}
static bool swapz_mm_bio_matches(const struct bio *bio, const struct swapz_mm_carrier *carrier)
{
	return bio && bio->exact_geometry && carrier && carrier->lease.broker;
}

/* Only the frozen observation wrappers are modeled, not a second recorder.
 * Model digests are deliberately not evidence of actual SHA or native I/O. */
static bool active, fail_append;
static unsigned int mints, appends, hashes;
static struct swapz_observation_record records[12];
bool swapz_trial_observation_active(void) { return active; }
u64 swapz_trial_observation_mint(void) { return ++mints; }
bool swapz_trial_observation_append(const struct swapz_observation_record *record)
{
	if (!active || fail_append)
		return false;
	must(appends < sizeof(records) / sizeof(records[0]) ? 0 : ENOSPC);
	records[appends++] = *record;
	return true;
}
static void sha256(const u8 *bytes, u32 length, u8 *digest)
{
	must(bytes && length ? 0 : EINVAL);
	++hashes;
	memset(digest, 0x5a, 32);
}
#include "r097-mm-extracted.h"

static void scope_checks(struct swapz_ticket_cap *owner)
{
	struct block_device selected = {1U}, other = {2U};
	struct swapz_mm_trial_scope scope = {
		.bdev = &selected, .broker = owner->broker, .identity = 11,
		.session = owner->session, .table_epoch = owner->epoch,
		.target_epoch = 3, .area_epoch = 4, .first_sector = 8,
		.sector_count = 16, .swap_type = 2
	};
	struct swapz_mm_route route = {
		.broker = owner->broker, .target_session = owner->session,
		.table_epoch = owner->epoch, .target_epoch = 3, .logical_page = 1,
		.dm_generation = 7
	};
	CHECK(swapz_mm_scope_matches(&scope, &selected, 8, 4, 2,
		SWAPZ_TICKET_LZ4, 3568, &route), "exact_scope");
	CHECK(!swapz_mm_scope_matches(&scope, &other, 8, 4, 2,
		SWAPZ_TICKET_LZ4, 3568, &route), "wrong_mapper");
	CHECK(!swapz_mm_scope_matches(&scope, &selected, 8, 5, 2,
		SWAPZ_TICKET_LZ4, 3568, &route), "wrong_area");
	CHECK(!swapz_mm_scope_matches(&scope, &selected, 8, 4, 3,
		SWAPZ_TICKET_LZ4, 3568, &route), "wrong_swap_type");
	CHECK(!swapz_mm_scope_matches(&scope, &selected, 9, 4, 2,
		SWAPZ_TICKET_LZ4, 3568, &route), "unaligned_sector");
	CHECK(!swapz_mm_scope_matches(&scope, &selected, 8, 4, 2,
		SWAPZ_TICKET_LZ4, 3569, &route), "m3568_bound");
	CHECK(!swapz_mm_scope_matches(&scope, &selected, 8, 4, 2,
		0, 64, &route), "unknown_codec");
	route.target_session++;
	CHECK(!swapz_mm_scope_matches(&scope, &selected, 8, 4, 2,
		SWAPZ_TICKET_LZ4, 64, &route), "stale_session");
	route.target_session = owner->session;
	route.table_epoch++;
	CHECK(!swapz_mm_scope_matches(&scope, &selected, 8, 4, 2,
		SWAPZ_TICKET_LZ4, 64, &route), "stale_table");
	route.table_epoch = owner->epoch;
	route.target_epoch++;
	CHECK(!swapz_mm_scope_matches(&scope, &selected, 8, 4, 2,
		SWAPZ_TICKET_LZ4, 64, &route), "stale_target");
	route.target_epoch = 3;
	route.logical_page = 2;
	CHECK(swapz_mm_scope_matches(&scope, &selected, 16, 4, 2,
		SWAPZ_TICKET_LZO1X, 64, &route), "last_page");
	CHECK(!swapz_mm_scope_matches(&scope, &selected, 8, 4, 2,
		SWAPZ_TICKET_LZ4, 64, &route), "wrong_logical");
	route.logical_page = 3;
	CHECK(!swapz_mm_scope_matches(&scope, &selected, 24, 4, 2,
		SWAPZ_TICKET_LZ4, 64, &route), "outside_range");
	route.logical_page = 1;
	route.dm_generation = (u64)U32_MAX + 1;
	CHECK(!swapz_mm_scope_matches(&scope, &selected, 8, 4, 2,
		SWAPZ_TICKET_LZ4, 64, &route), "generation_not_representable");
	route.dm_generation = 7;
	scope.identity = 0;
	CHECK(!swapz_mm_scope_matches(&scope, &selected, 8, 4, 2,
		SWAPZ_TICKET_LZ4, 64, &route), "no_admitted_scope");
}
static void prepare_carrier(struct swapz_ticket_cap *owner, struct swapz_ticket_key *key,
	struct block_device *device, struct page *page, struct module *module)
{
	struct swapz_mm_carrier *carrier = &swapz_mm_carrier;

	key->target_session = owner->session;
	key->table_epoch = owner->epoch;
	memset(carrier->scratch, 0xa5, key->length);
	key->crc = swapz_crc32c_bytes(carrier->scratch, key->length);
	memset(key->sha256, 0x33, sizeof(key->sha256));
	CHECK(!swapz_ticket_broker_try_get(owner->broker, owner->session, owner->epoch,
		&carrier->cap) && try_module_get(module), "carrier_cap_and_pin");
	carrier->provider_owner = module;
	CHECK(!swapz_ticket_reserve(carrier->cap.broker, key, &carrier->lease) &&
	      !swapz_ticket_seal(&carrier->lease, carrier->scratch, key->length), "carrier_seal");
	carrier->bdev = device;
	carrier->page = page;
	carrier->sector = 8;
	atomic_store(&swapz_mm_busy, 1);
}
int main(void)
{
	struct swapz_ticket_cap owner = {0}, late = {0}, refused = {0};
	struct swapz_ticket_ref candidate = {0}, wrong;
	struct swapz_observation_record correlation = {0};
	struct block_device device = {1};
	struct page page = {1};
	struct module module = {.live = true};
	struct bio bio = {&swapz_mm_carrier, true};
	struct work_struct work = {0};
	struct swapz_ticket_key key = {
		.area_epoch = 4, .store_sequence = 8, .slot_offset = 1,
		.target_epoch = 3, .logical_page = 1, .dm_generation = 7,
		.swap_type = 2, .length = 64, .decoded_length = 4096,
		.representation = SWAPZ_TICKET_ORIGINAL, .codec = SWAPZ_TICKET_LZ4,
		.version = 1
	};
	CHECK(!swapz_mm_broker_owner_open(8, 3568, 8 * 3568, &owner), "open");
	scope_checks(&owner);
	prepare_carrier(&owner, &key, &device, &page, &module);
	swapz_mm_observation_capture(&swapz_mm_carrier, &key);
	swapz_mm_observation_bind(&swapz_mm_carrier);
	CHECK(!hashes && !mints && !appends, "inactive_no_digest_or_event");
	active = true;
	swapz_mm_observation_capture(&swapz_mm_carrier, &key);
	CHECK(hashes == 1 && mints == 1 && appends == 2 &&
	      records[0].event == SWAPZ_OBS_CAPTURE && records[0].operation == 1 &&
	      records[0].original == 0 && records[0].store == key.store_sequence &&
	      records[0].generation == key.dm_generation &&
	      records[0].compressed_sha256[0] == 0x5a &&
	      records[0].page_sha256[0] == 0x33 &&
	      records[1].event == SWAPZ_OBS_PREPARATION && records[1].flags == 1,
	      "capture_and_prior_decode");
	swapz_mm_observation_bind(&swapz_mm_carrier);
	CHECK(appends == 3 && mints == 2 && records[2].event == SWAPZ_OBS_BIND &&
	      records[2].original == 2 && records[2].operation == 1, "actual_bind_metadata");
	CHECK(!swapz_ticket_retain(&swapz_mm_carrier.lease, &candidate), "retained_candidate");
	CHECK(swapz_mm_candidate_observation(&bio, &candidate, &correlation) &&
	      correlation.operation == 1 && correlation.original == 2 &&
	      correlation.store == key.store_sequence && !reader_depth, "exact_candidate_correlation");
	wrong = candidate; /* intentionally non-owning wrong identity, never put */
	++wrong.generation;
	CHECK(!swapz_mm_candidate_observation(&bio, &wrong, &correlation) &&
	      correlation.operation == 1 && !reader_depth, "wrong_ticket_generation");
	bio.exact_geometry = false;
	CHECK(!swapz_mm_candidate_observation(&bio, &candidate, &correlation), "wrong_geometry");
	bio.exact_geometry = true;
	/* Model actual terminal unpublication; SIO owner, not clone, supplies
	 * observed original status. Kernel BIO callback is source-audited. */
	bio.bi_swapz_original = NULL;
	swapz_mm_observation_endio(&swapz_mm_carrier, EIO);
	CHECK(appends == 4 && records[3].event == SWAPZ_OBS_UPPER_ENDIO &&
	      records[3].status == EIO && records[3].original == 2, "original_error_status");
	swapz_mm_release_workfn(&work);
	CHECK(appends == 5 && records[4].event == SWAPZ_OBS_CARRIER_RELEASE &&
	      records[4].original == 2 && !swapz_mm_carrier.observation.operation &&
	      !atomic_load(&module.refs) && grace_calls == 1 && !atomic_load(&swapz_mm_busy),
	      "release_after_actual_puts");
	CHECK(!swapz_ticket_put(&candidate), "release_candidate");

	/* Unbound capture is explicitly dropped; never synthesize an upper ACK. */
	prepare_carrier(&owner, &key, &device, &page, &module);
	swapz_mm_observation_capture(&swapz_mm_carrier, &key);
	swapz_mm_release_workfn(&work);
	CHECK(appends == 9 && records[7].event == SWAPZ_OBS_CAPTURE_DROP &&
	      records[7].original == 0 && records[7].status == EOPNOTSUPP &&
	      records[8].event == SWAPZ_OBS_CARRIER_RELEASE && records[8].original == 0,
	      "unbound_capture_drop");
	prepare_carrier(&owner, &key, &device, &page, &module);
	fail_append = true;
	swapz_mm_observation_capture(&swapz_mm_carrier, &key);
	swapz_mm_observation_bind(&swapz_mm_carrier);
	swapz_mm_release_workfn(&work);
	CHECK(appends == 9 && !swapz_mm_carrier.observation.operation &&
	      !swapz_mm_carrier.lease.broker && !swapz_mm_carrier.cap.broker &&
	      !atomic_load(&module.refs), "failed_observation_does_not_keep_carrier");
	active = false;
	const u64 session = owner.session, epoch = owner.epoch;
	/* New edge: last cap release after work consumed pending, while
	 * work still runs. A second work item can be queued, then the first
	 * destroys. Old queued identity must retire before fresh open. */
	CHECK(!swapz_ticket_broker_try_get(owner.broker, session, epoch, &late) &&
	      !owner_enter(session, epoch), "two_independent_debts");
	CHECK(!swapz_ticket_revoke(owner.broker, epoch + 9), "burn_revoked_epoch");
	CHECK(!swapz_mm_broker_owner_begin_close(session, epoch) &&
	      !swapz_ticket_broker_put(&owner) &&
	      swapz_mm_broker_owner_finish_close(session, epoch) == -EBUSY,
	      "arm_before_remaining_debts");
	owner_leave();
	CHECK(pending && scheduled == 1, "entrant_queues_running_edge");
	release_cap = &late;
	release_during_worker = true;
	run_retry();
	CHECK(!release_during_worker && !late.broker && !allocations &&
	      !owner_broker.initialized && pending && scheduled == 2,
	      "running_retry_requeued_then_destroyed");
	CHECK(swapz_mm_broker_owner_open(8, 3568, 8 * 3568, &refused) == -EBUSY,
	      "queued_old_work_blocks_open");
	run_retry();
	CHECK(!pending && executed == 2 && !allocations, "queued_old_work_retires");
	CHECK(!swapz_mm_broker_owner_open(8, 3568, 8 * 3568, &owner) &&
	      owner.session > epoch + 9, "revoked_epoch_never_reused");
	const u64 next_session = owner.session, next_epoch = owner.epoch;
	CHECK(!swapz_mm_broker_owner_begin_close(next_session, next_epoch) &&
	      swapz_mm_broker_owner_finish_close(next_session, next_epoch) == -EBUSY,
	      "new_identity_armed");
	owner_release_event(owner.broker, session);
	CHECK(!pending && scheduled == 2, "old_notification_cannot_queue_new_armed_owner");
	CHECK(!swapz_ticket_broker_put(&owner) && pending, "new_last_release");
	run_retry();
	CHECK(!allocations && !pending && executed == 3 && scheduled == executed &&
	      !owner_broker.initialized, "balanced_teardown");
	printf("PASS_HOST_ONLY R097 A11 checks=%u retries=%u events=%u\n", checks, executed, appends);
	return 0;
}
