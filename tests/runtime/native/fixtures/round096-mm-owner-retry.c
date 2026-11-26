/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual staged broker + extracted MM boundaries. Host RCU, geometry and
 * module primitives are models; no native claim, I/O or physical admission.
 */
#include <errno.h>
#include <string.h>
#include "round094-owner-shim.h"
#include "r096-broker.c"

static unsigned int checks, allocations, reader_depth, grace_calls;
static unsigned int lookup_calls, scheduled, executed;
static bool pending;
static pthread_mutex_t pause_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t pause_cond = PTHREAD_COND_INITIALIZER;
static bool pause_enter, entered, resume_enter;
#define CHECK(condition, witness) do { \
	++checks; \
	if (!(condition)) { \
		fprintf(stderr, "R096_A11_FIRST_ERROR %s line=%d\n", witness, __LINE__); \
		exit(77); \
	} \
} while (0)
static void must(int error)
{
	if (error)
		exit(78);
}
void r094_owner_mutex_lock(pthread_mutex_t *lock) { must(pthread_mutex_lock(lock)); }
void r094_owner_mutex_unlock(pthread_mutex_t *lock) { must(pthread_mutex_unlock(lock)); }
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
		must(allocations == 0U ? EINVAL : 0);
		--allocations;
		free(pointer);
	}
}
void r094_owner_after_enter(void)
{
	must(pthread_mutex_lock(&pause_lock));
	if (pause_enter) {
		entered = true;
		must(pthread_cond_signal(&pause_cond));
		while (!resume_enter)
			must(pthread_cond_wait(&pause_cond, &pause_lock));
	}
	must(pthread_mutex_unlock(&pause_lock));
}
void r096_owner_schedule_retry(void)
{
	/* Actual owner gate serializes publication; no inline execution. */
	must(pending ? EALREADY : 0);
	pending = true;
	++scheduled;
}
static void run_retry(void)
{
	must(pending ? 0 : EINVAL);
	pending = false;
	++executed;
	owner_retry_run();
}

typedef swapz_u8 u8;
typedef swapz_u32 u32;
typedef swapz_u64 sector_t;
struct block_device { unsigned int identity; };
struct swap_info_struct { struct block_device *bdev; };
struct page { unsigned int identity; };
struct work_struct { unsigned int unused; };
struct swapz_mm_route {
	struct swapz_ticket_broker *broker;
	swapz_u64 target_session, table_epoch, target_epoch, logical_page, dm_generation;
};
struct swapz_mm_route_provider {
	bool (*eligible)(struct block_device *, sector_t, u8, u32);
	bool (*lookup)(struct block_device *, sector_t, u8, u32, struct swapz_mm_route *);
};
struct swapz_mm_carrier {
	struct swapz_ticket_ref lease;
	struct swapz_ticket_cap cap;
	struct module *provider_owner;
	struct block_device *bdev;
	struct page *page;
};
struct bio {
	const struct swapz_mm_carrier *bi_swapz_original;
	bool exact_geometry;
};
static struct swapz_mm_carrier swapz_mm_carrier;
static atomic_int swapz_mm_busy;
static const struct swapz_mm_route_provider *swapz_mm_provider;
static struct module *swapz_mm_provider_owner;
#define READ_ONCE(value) (value)
#define rcu_dereference(value) (value)
#define WARN_ON_ONCE(value) (value)
#define atomic_set_release(pointer, value) atomic_store_explicit(pointer, value, memory_order_release)
static void rcu_read_lock(void) { ++reader_depth; }
static void rcu_read_unlock(void) { must(reader_depth ? 0 : EINVAL); --reader_depth; }
static void synchronize_rcu(void)
{
	CHECK(!reader_depth && swapz_mm_carrier.lease.broker &&
	      swapz_mm_carrier.cap.broker && swapz_mm_carrier.provider_owner &&
	      atomic_load(&swapz_mm_carrier.provider_owner->refs) == 2U,
	      "grace_before_carrier_puts");
	++grace_calls;
}
static bool swapz_mm_bio_matches(const struct bio *bio, const struct swapz_mm_carrier *carrier)
{
	return bio && bio->exact_geometry && carrier && carrier->lease.broker;
}

#include "r096-mm-extracted.h"

static struct swapz_mm_route published_route;
static bool eligible(struct block_device *device, sector_t sector, u8 codec, u32 length)
{
	CHECK(reader_depth == 1U && atomic_load(&swapz_mm_provider_owner->refs) == 1U,
	      "callback_module_pin");
	return device && sector == 8U && codec == SWAPZ_TICKET_LZ4 && length == 64U;
}
static bool lookup(struct block_device *device, sector_t sector, u8 codec, u32 length,
		struct swapz_mm_route *route)
{
	++lookup_calls;
	if (!eligible(device, sector, codec, length))
		return false;
	*route = published_route;
	return true;
}
static const struct swapz_mm_route_provider provider = {eligible, lookup};

/* The owner retry work is explicitly driven by the host scheduler; the
 * paused pre-ref entrant is a real pthread with a deterministic rendezvous.
 * No Linux workqueue, native RCU or target execution is claimed. */
struct entrant_argument {
	struct swapz_ticket_broker *broker;
	swapz_u64 session, epoch;
	struct swapz_ticket_cap cap;
	int result;
};
static void *entrant_thread(void *opaque)
{
	struct entrant_argument *argument = opaque;
	argument->result = swapz_ticket_broker_try_get(argument->broker,
		argument->session, argument->epoch, &argument->cap);
	return NULL;
}
static void open_owner(struct swapz_ticket_cap *cap)
{
	CHECK(!swapz_mm_broker_owner_open(8U, 3568U, 8U * 3568U, cap) &&
	      allocations == 3U && !pending, "new_owner");
}
static void close_owner(struct swapz_ticket_cap *cap)
{
	CHECK(!swapz_mm_broker_owner_begin_close(cap->session, cap->epoch) &&
	      !swapz_ticket_broker_put(cap), "fence_and_drop_target_cap");
}
int main(void)
{
	struct swapz_ticket_cap owner = {0}, replacement = {0}, refused = {0};
	struct swapz_ticket_ref candidate = {0};
	struct swapz_ticket_view view = {0};
	struct swapz_mm_route route = {0};
	struct module module = {.live = true};
	struct block_device device = {1U};
	struct page page = {1U};
	struct swap_info_struct info = {&device};
	struct bio bio = {&swapz_mm_carrier, true};
	struct work_struct work = {0};
	swapz_u8 bytes[64];
	struct swapz_ticket_key key = {
		.area_epoch = 1U, .store_sequence = 2U, .slot_offset = 1U,
		.target_epoch = 3U, .logical_page = 1U, .dm_generation = 1U,
		.swap_type = 1U, .length = 64U, .decoded_length = 4096U,
		.representation = SWAPZ_TICKET_ORIGINAL, .codec = SWAPZ_TICKET_LZ4,
		.version = 1U
	};
	CHECK(!swapz_mm_capture_permitted(), "capture_still_off");
	open_owner(&owner);
	const swapz_u64 first_session = owner.session, first_epoch = owner.epoch;
	published_route = (struct swapz_mm_route){owner.broker, first_session, first_epoch, 3U, 1U, 1U};
	swapz_mm_provider = &provider;
	swapz_mm_provider_owner = &module;
	CHECK(swapz_mm_route_try(&info, 8U, SWAPZ_TICKET_LZ4, 64U, &route,
		&swapz_mm_carrier.cap, &swapz_mm_carrier.provider_owner), "actual_route");
	key.target_session = first_session;
	key.table_epoch = first_epoch;
	memset(bytes, 0x5b, sizeof(bytes));
	key.crc = swapz_crc32c_bytes(bytes, (swapz_u32)sizeof(bytes));
	CHECK(!swapz_ticket_reserve(swapz_mm_carrier.cap.broker, &key, &swapz_mm_carrier.lease) &&
	      !swapz_ticket_seal(&swapz_mm_carrier.lease, bytes, (swapz_u32)sizeof(bytes)),
	      "carrier_ticket");
	swapz_mm_carrier.bdev = &device;
	swapz_mm_carrier.page = &page;
	atomic_store(&swapz_mm_busy, 1);
	CHECK(!swapz_mm_candidate_get(&bio, &candidate) && atomic_load(&module.refs) == 2U,
	      "independent_candidate");
	swapz_mm_provider = NULL;
	bio.bi_swapz_original = NULL;
	close_owner(&owner);
	CHECK(swapz_mm_broker_owner_finish_close(first_session + 1U, first_epoch) == -ESTALE &&
	      !owner_retry_armed, "wrong_identity_does_not_arm");
	CHECK(swapz_mm_broker_owner_finish_close(first_session, first_epoch) == -EBUSY &&
	      owner_retry_armed && !pending && allocations == 3U, "busy_arms_without_poll");
	CHECK(swapz_mm_broker_owner_open(8U, 3568U, 8U * 3568U, &refused) == -EBUSY &&
	      !refused.broker, "no_reopen_before_destroy");
	CHECK(swapz_ticket_claim(&candidate, &key) == -ESTALE, "claim_fenced");
	swapz_mm_release_workfn(&work);
	CHECK(grace_calls == 1U && !atomic_load(&swapz_mm_busy) && atomic_load(&module.refs) == 1U &&
	      !pending && allocations == 3U && !swapz_ticket_view(&candidate, &view) &&
	      !memcmp(view.bytes, bytes, sizeof(bytes)), "carrier_drain_not_candidate_drain");
	CHECK(!swapz_ticket_put(&candidate) && !atomic_load(&module.refs) &&
	      pending && scheduled == 1U && allocations == 3U, "candidate_last_schedules");
	/* No consumer identity or explicit finish is used after the last release. */
	run_retry();
	CHECK(!owner_broker.initialized && !allocations && !pending && !owner_retry_armed &&
	      executed == 1U, "eventual_candidate_destroy");
	owner_retry_run(); /* duplicate execution must be harmless */
	CHECK(!allocations && !owner_broker.initialized, "duplicate_work_safe");

	open_owner(&replacement);
	CHECK(replacement.session > first_session && replacement.broker == published_route.broker,
	      "nonreuse");
	const swapz_u64 second_session = replacement.session, second_epoch = replacement.epoch;
	struct entrant_argument argument = {replacement.broker, second_session, second_epoch, {0}, 0};
	pthread_t thread;
	must(pthread_mutex_lock(&pause_lock));
	pause_enter = true;
	must(pthread_create(&thread, NULL, entrant_thread, &argument));
	while (!entered)
		must(pthread_cond_wait(&pause_cond, &pause_lock));
	must(pthread_mutex_unlock(&pause_lock));
	CHECK(owner_entrants == 1U && !argument.cap.broker, "paused_pre_ref");
	/* Hold an independent cap so the first queued retry sees real debt. */
	struct swapz_ticket_cap late_cap = {0};
	CHECK(!ticket_broker_try_get_raw(replacement.broker, second_session, second_epoch, &late_cap),
	      "independent_cap");
	close_owner(&replacement);
	CHECK(swapz_mm_broker_owner_finish_close(second_session, second_epoch) == -EBUSY &&
	      !pending && allocations == 3U, "entrant_busy_arms");
	must(pthread_mutex_lock(&pause_lock));
	resume_enter = true;
	must(pthread_cond_signal(&pause_cond));
	must(pthread_mutex_unlock(&pause_lock));
	must(pthread_join(thread, NULL));
	CHECK(argument.result == -ESTALE && !argument.cap.broker && !owner_entrants &&
	      pending && scheduled == 2U, "entrant_last_schedules");
	run_retry();
	CHECK(owner_broker.initialized && owner_retry_armed && !pending &&
	      allocations == 3U && executed == 2U, "retry_busy_no_poll");
	CHECK(!swapz_ticket_broker_put(&late_cap) && pending && scheduled == 3U,
	      "late_cap_schedules");
	run_retry();
	CHECK(!owner_broker.initialized && !allocations && !pending && executed == 3U,
	      "eventual_cap_destroy");

	open_owner(&owner);
	const swapz_u64 third_session = owner.session, third_epoch = owner.epoch;
	CHECK(swapz_mm_broker_owner_begin_close(third_session, third_epoch) == 0 &&
	      swapz_mm_broker_owner_finish_close(third_session, third_epoch) == -EBUSY,
	      "explicit_race_arm");
	CHECK(!swapz_ticket_broker_put(&owner) && pending, "explicit_race_queued");
	CHECK(!swapz_mm_broker_owner_finish_close(third_session, third_epoch) &&
	      !allocations && !owner_broker.initialized, "explicit_finish_wins");
	CHECK(swapz_mm_broker_owner_open(8U, 3568U, 8U * 3568U, &refused) == -EBUSY,
	      "old_work_slot_not_reused");
	run_retry();
	CHECK(!pending && !allocations, "stale_work_retires");
	open_owner(&replacement);
	const swapz_u64 fourth_session = replacement.session, fourth_epoch = replacement.epoch;
	CHECK(fourth_session > third_session, "fourth_identity");
	owner_release_event(replacement.broker, third_session);
	CHECK(!pending && owner_broker.initialized, "late_old_notification_ignored");
	close_owner(&replacement);
	CHECK(!swapz_mm_broker_owner_finish_close(fourth_session, fourth_epoch) &&
	      !allocations && !pending && scheduled == executed, "balanced_final_destroy");
	printf("PASS_HOST_ONLY R096 A11 checks=%u retries=%u\n", checks, executed);
	return 0;
}
