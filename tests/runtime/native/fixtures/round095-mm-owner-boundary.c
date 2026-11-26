/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual staged broker + extracted MM boundaries. Host RCU, geometry and
 * module primitives are models; no native claim, I/O or physical admission.
 */
#include <errno.h>
#include <string.h>
#include "round094-owner-shim.h"
#include "r095-broker.c"

static unsigned int checks, allocations, reader_depth, grace_calls;
static unsigned int capture_calls, preerase_calls, lookup_calls;
#define CHECK(condition, witness) do { \
	++checks; \
	if (!(condition)) { \
		fprintf(stderr, "R095_A11_FIRST_ERROR %s line=%d\n", witness, __LINE__); \
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
void r094_owner_after_enter(void) {}

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

#define swapz_mm_capture(...) (++capture_calls)
#define swapz_mm_preerase(...) (++preerase_calls)
struct source_entry { swapz_u64 original_cookie; };
#include "r095-mm-extracted.h"
#undef swapz_mm_capture
#undef swapz_mm_preerase

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

int main(void)
{
	struct source_entry entry = {.original_cookie = 99U};
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
	CHECK(!swapz_mm_capture_permitted(), "claim_off_gate");
	store_site(false, &entry);
	CHECK(!entry.original_cookie && !capture_calls, "disabled_store");
	entry.original_cookie = 77U;
	store_site(true, &entry);
	CHECK(!entry.original_cookie && !capture_calls, "disabled_raw_store");
	preerase_site();
	CHECK(!preerase_calls && !lookup_calls && !allocations, "disabled_eviction");
	CHECK(!swapz_mm_broker_owner_open(8U, 3568U, 8U * 3568U, &owner),
	      "exact_target_owner");
	CHECK(owner.broker->stride == 3584U && owner.broker->payload_bytes == 28672U &&
	      owner.broker->capacity == 8U && allocations == 3U, "exact_target_arrays");
	const swapz_u64 session = owner.session, epoch = owner.epoch;
	published_route = (struct swapz_mm_route){owner.broker, session, epoch, 3U, 1U, 1U};
	swapz_mm_provider = &provider;
	swapz_mm_provider_owner = &module;
	atomic_store(&module.live, false);
	CHECK(!swapz_mm_eligible(&device, 8U, SWAPZ_TICKET_LZ4, 64U) &&
	      !swapz_mm_route_try(&info, 8U, SWAPZ_TICKET_LZ4, 64U, &route,
				 &refused, &swapz_mm_carrier.provider_owner) &&
	      !lookup_calls && !atomic_load(&module.refs), "module_exit_refuses_callback");
	atomic_store(&module.live, true);
	CHECK(swapz_mm_eligible(&device, 8U, SWAPZ_TICKET_LZ4, 64U) &&
	      !atomic_load(&module.refs), "eligible_pin_balanced");
	/* Explicit host-only boundary exercise, not native capture or admission. */
	CHECK(swapz_mm_route_try(&info, 8U, SWAPZ_TICKET_LZ4, 64U, &route,
			       &swapz_mm_carrier.cap, &swapz_mm_carrier.provider_owner),
	      "route_cap_transfer");
	CHECK(swapz_mm_carrier.cap.broker == owner.broker &&
	      swapz_mm_carrier.provider_owner == &module &&
	      atomic_load(&module.refs) == 1U && !reader_depth, "carrier_pin_transfer");
	key.target_session = session;
	key.table_epoch = epoch;
	memset(bytes, 0x5b, sizeof(bytes));
	key.crc = swapz_crc32c_bytes(bytes, (swapz_u32)sizeof(bytes));
	CHECK(!swapz_ticket_reserve(swapz_mm_carrier.cap.broker, &key, &swapz_mm_carrier.lease) &&
	      !swapz_ticket_seal(&swapz_mm_carrier.lease, bytes, (swapz_u32)sizeof(bytes)),
	      "host_sealed_carrier");
	swapz_mm_carrier.bdev = &device;
	swapz_mm_carrier.page = &page;
	atomic_store(&swapz_mm_busy, 1);
	CHECK(!swapz_mm_candidate_get(&bio, &candidate) &&
	      candidate.provider_owner == &module && atomic_load(&module.refs) == 2U,
	      "actual_mm_candidate_independent_pin");
	/* Model target unpublication and BIO terminal unpublish before deferred
	 * MM release; actual grace primitive/DM core not executed here.
	 */
	swapz_mm_provider = NULL;
	bio.bi_swapz_original = NULL;
	CHECK(!swapz_mm_broker_owner_begin_close(session, epoch) &&
	      !swapz_ticket_broker_put(&owner), "target_owner_close");
	CHECK(swapz_mm_broker_owner_finish_close(session, epoch) == -EBUSY,
	      "carrier_and_candidate_block_finish");
	swapz_mm_release_workfn(&work);
	CHECK(grace_calls == 1U && !atomic_load(&swapz_mm_busy) &&
	      !swapz_mm_carrier.lease.broker && !swapz_mm_carrier.cap.broker &&
	      !swapz_mm_carrier.provider_owner && atomic_load(&module.refs) == 1U,
	      "carrier_release_preserves_candidate");
	CHECK(swapz_mm_broker_owner_finish_close(session, epoch) == -EBUSY &&
	      !swapz_ticket_view(&candidate, &view) && !memcmp(view.bytes, bytes, sizeof(bytes)),
	      "candidate_outlives_mm_carrier");
	CHECK(!swapz_ticket_put(&candidate) && !atomic_load(&module.refs) &&
	      !swapz_mm_broker_owner_finish_close(session, epoch) && !allocations,
	      "last_candidate_releases_owner");
	CHECK(!swapz_mm_broker_owner_open(8U, 3568U, 8U * 3568U, &replacement) &&
	      replacement.broker == published_route.broker && replacement.session > session,
	      "same_address_new_session");
	swapz_mm_provider = &provider; /* deliberately stale lookup result */
	CHECK(!swapz_mm_route_try(&info, 8U, SWAPZ_TICKET_LZ4, 64U, &route,
				 &refused, &swapz_mm_carrier.provider_owner) &&
	      !refused.broker && !atomic_load(&module.refs) && !reader_depth,
	      "stale_route_cannot_pin_reopened_owner");
	swapz_mm_provider = NULL;
	const swapz_u64 next_session = replacement.session, next_epoch = replacement.epoch;
	CHECK(!swapz_mm_broker_owner_begin_close(next_session, next_epoch) &&
	      !swapz_ticket_broker_put(&replacement) &&
	      !swapz_mm_broker_owner_finish_close(next_session, next_epoch) && !allocations,
	      "reopened_owner_drained");
	printf("PASS_HOST_ONLY R095 A11 checks=%u\n", checks);
	return 0;
}
