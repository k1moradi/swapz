/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual staged broker and owner; pthread/allocator/module ABI substitutions. */
#include <errno.h>
#include <stdalign.h>
#include <string.h>
#include "round094-owner-shim.h"
#include "r094-broker.c"

static unsigned int checks, allocation_attempt, fail_at, allocations;
static atomic_bool pause_entrant;
static pthread_barrier_t entered, resume;
#define CHECK(condition, witness) do { \
	++checks; \
	if (!(condition)) { \
		fprintf(stderr, "R094_A11_FIRST_ERROR %s line=%d\n", witness, __LINE__); \
		exit(77); \
	} \
} while (0)
static void must(int error)
{
	if (error) {
		fprintf(stderr, "R094_A11_INFRA pthread=%d\n", error);
		exit(78);
	}
}
static void meet(pthread_barrier_t *barrier)
{
	int error = pthread_barrier_wait(barrier);
	if (error != PTHREAD_BARRIER_SERIAL_THREAD)
		must(error);
}
void r094_owner_mutex_lock(pthread_mutex_t *lock) { must(pthread_mutex_lock(lock)); }
void r094_owner_mutex_unlock(pthread_mutex_t *lock) { must(pthread_mutex_unlock(lock)); }
void *r094_owner_allocate(size_t bytes)
{
	if (++allocation_attempt == fail_at)
		return NULL;
	void *pointer = aligned_alloc(64, (bytes + 63U) & ~(size_t)63U);
	if (pointer)
		++allocations;
	return pointer;
}
void r094_owner_free(void *pointer)
{
	if (pointer) {
		if (!allocations)
			must(EINVAL);
		--allocations;
		free(pointer);
	}
}
void r094_owner_after_enter(void)
{
	if (atomic_load(&pause_entrant)) {
		meet(&entered);
		meet(&resume);
	}
}
struct entrant_context {
	struct swapz_ticket_broker *broker;
	swapz_u64 session, epoch;
	int result;
	struct swapz_ticket_cap cap;
};
static void *entrant(void *opaque)
{
	struct entrant_context *context = opaque;
	context->result = swapz_ticket_broker_try_get(context->broker,
		context->session, context->epoch, &context->cap);
	return NULL;
}
static void allocation_failure(void)
{
	struct swapz_ticket_cap out = {.session = 91, .epoch = 92};
	for (unsigned int index = 1; index <= 3; ++index) {
		allocation_attempt = 0;
		fail_at = index;
		CHECK(swapz_mm_broker_owner_open(1, 3568, 64, &out) == -ENOMEM, "allocation_failure");
		CHECK(!out.broker && out.session == 91 && out.epoch == 92, "failure_output_unchanged");
		CHECK(!allocations && !owner_broker.initialized, "allocation_unwind");
	}
	fail_at = 0;
	CHECK(swapz_mm_broker_owner_open(0, 3568, 64, &out) == -EINVAL, "zero_capacity");
	CHECK(swapz_mm_broker_owner_open(1025, 3568, 64, &out) == -EINVAL, "capacity_bound");
	CHECK(swapz_mm_broker_owner_open(1, 4096, 64, &out) == -EMSGSIZE, "length_bound");
	CHECK(swapz_mm_broker_owner_open(1, 3568, 3569, &out) == -EMSGSIZE, "byte_bound");
	CHECK(!allocations && !out.broker && out.session == 91 && out.epoch == 92, "invalid_unchanged");
}
static void paused_entrant(void)
{
	struct swapz_ticket_cap owner = {0}, second = {.session = 88};
	struct entrant_context context = {0};
	pthread_t thread;
	CHECK(!swapz_mm_broker_owner_open(1, 3568, 64, &owner), "open");
	CHECK(owner.broker && owner.session && owner.epoch && allocations == 3, "counted_owner");
	CHECK(swapz_mm_broker_owner_open(1, 3568, 64, &second) == -EBUSY &&
		!second.broker && second.session == 88, "second_open_refused");
	context.broker = owner.broker;
	context.session = owner.session;
	context.epoch = owner.epoch;
	CHECK(swapz_mm_broker_owner_finish_close(owner.session, owner.epoch) == -EBUSY, "finish_requires_begin");
	CHECK(swapz_mm_broker_owner_begin_close(owner.session + 1, owner.epoch) == -ESTALE, "wrong_begin_identity");
	must(pthread_barrier_init(&entered, NULL, 2));
	must(pthread_barrier_init(&resume, NULL, 2));
	atomic_store(&pause_entrant, true);
	must(pthread_create(&thread, NULL, entrant, &context));
	meet(&entered);
	CHECK(!swapz_mm_broker_owner_begin_close(context.session, context.epoch), "begin_while_entered");
	CHECK(!swapz_mm_broker_owner_begin_close(context.session, context.epoch), "begin_idempotent");
	CHECK(!swapz_ticket_broker_put(&owner), "owner_cap_drop");
	CHECK(!context.broker->capability_refs, "zero_counted_caps");
	CHECK(swapz_mm_broker_owner_finish_close(context.session, context.epoch) == -EBUSY &&
		allocations == 3, "paused_entrant_fence");
	CHECK(swapz_ticket_broker_try_get(context.broker, context.session, context.epoch, &second) == -ESTALE &&
		!second.broker && second.session == 88, "closed_gate");
	meet(&resume);
	must(pthread_join(thread, NULL));
	atomic_store(&pause_entrant, false);
	CHECK(context.result == -ESTALE && !context.cap.broker, "paused_refused");
	CHECK(!swapz_mm_broker_owner_finish_close(context.session, context.epoch) && !allocations, "finish_after_join");
	CHECK(swapz_mm_broker_owner_finish_close(context.session, context.epoch) == -ESTALE, "no_double_free");
	CHECK(!swapz_mm_broker_owner_open(1, 4095, 64, &owner), "reopen");
	CHECK(owner.broker == context.broker && owner.session > context.session && owner.epoch > context.epoch, "nonreused_identity");
	/* No stale raw borrower can enter the new session even at the same address. */
	CHECK(swapz_ticket_broker_try_get(context.broker, context.session, context.epoch, &second) == -ESTALE &&
		!second.broker, "stale_reopen");
	CHECK(swapz_mm_broker_owner_begin_close(context.session, context.epoch) == -ESTALE, "stale_begin");
	CHECK(swapz_mm_broker_owner_finish_close(context.session, context.epoch) == -ESTALE, "stale_finish");
	swapz_u64 session = owner.session, epoch = owner.epoch;
	CHECK(!swapz_mm_broker_owner_begin_close(session, epoch), "reopen_close");
	CHECK(!swapz_ticket_broker_put(&owner), "reopen_put");
	CHECK(!swapz_mm_broker_owner_finish_close(session, epoch) && !allocations, "reopen_destroy");
	must(pthread_barrier_destroy(&entered));
	must(pthread_barrier_destroy(&resume));
}
static void retained_holders(bool claim_first)
{
	struct swapz_ticket_cap owner = {0}, route = {0};
	struct swapz_ticket_ref producer = {0}, candidate = {0}, refused = {0};
	struct swapz_ticket_view view = {0};
	struct module module = {.live = true};
	swapz_u8 bytes[64];
	struct swapz_ticket_key key = {
		.area_epoch = 1, .store_sequence = 1, .slot_offset = 2,
		.target_epoch = 3, .logical_page = 4, .dm_generation = 5,
		.swap_type = 1, .length = 64, .decoded_length = 4096,
		.representation = SWAPZ_TICKET_ORIGINAL, .codec = SWAPZ_TICKET_LZ4,
		.version = 1
	};
	CHECK(!swapz_mm_broker_owner_open(2, 3568, 128, &owner), "holders_open");
	struct swapz_ticket_broker *broker = owner.broker;
	swapz_u64 session = owner.session, epoch = owner.epoch;
	key.target_session = session;
	key.table_epoch = epoch;
	memset(bytes, 0x5b, sizeof(bytes));
	key.crc = swapz_crc32c_bytes(bytes, (swapz_u32)sizeof(bytes));
	CHECK(!swapz_ticket_broker_try_get(broker, session, epoch, &route), "route_cap");
	CHECK(!swapz_ticket_reserve(broker, &key, &producer), "reserve");
	CHECK(!swapz_ticket_seal(&producer, bytes, (swapz_u32)sizeof(bytes)), "seal");
	CHECK(try_module_get(&module) && !swapz_ticket_retain(&producer, &candidate), "candidate_acquire");
	candidate.provider_owner = &module;
	CHECK(!swapz_ticket_put(&producer), "carrier_ticket_drop");
	if (claim_first)
		CHECK(!swapz_ticket_claim_under_queue_lock(&candidate, &key), "claim_before_close");
	else
		CHECK(!swapz_ticket_revoke(broker, epoch + 1), "revoke_before_close");
	CHECK(!swapz_mm_broker_owner_begin_close(session, epoch), "holders_close");
	CHECK(swapz_ticket_claim_under_queue_lock(&candidate, &key) == -ESTALE, "closed_claim");
	CHECK(swapz_ticket_reserve(broker, &key, &refused) == -ESHUTDOWN && !refused.broker, "closed_reserve");
	CHECK(swapz_ticket_retain(&candidate, &refused) == -ESTALE && !refused.broker &&
		atomic_load(&module.refs) == 1U, "closed_retain_pin");
	CHECK(!swapz_ticket_view(&candidate, &view) && !memcmp(view.bytes, bytes, sizeof(bytes)), "retained_view");
	CHECK(!swapz_ticket_broker_put(&owner), "owner_drop");
	if (claim_first) {
		CHECK(!swapz_ticket_broker_put(&route), "route_first");
		CHECK(swapz_mm_broker_owner_finish_close(session, epoch) == -EBUSY &&
			allocations == 3 && atomic_load(&module.refs) == 1U, "ticket_only_busy");
		CHECK(!swapz_ticket_put(&candidate), "candidate_last");
	} else {
		CHECK(!swapz_ticket_put(&candidate), "candidate_first");
		CHECK(swapz_mm_broker_owner_finish_close(session, epoch) == -EBUSY &&
			allocations == 3, "cap_only_busy");
		CHECK(!swapz_ticket_broker_put(&route), "route_last");
	}
	CHECK(!atomic_load(&module.refs), "candidate_module_drained");
	CHECK(!swapz_mm_broker_owner_finish_close(session, epoch) && !allocations, "holders_destroy");
	if (!claim_first) {
		CHECK(!swapz_mm_broker_owner_open(1, 3568, 64, &owner), "after_revoke_open");
		CHECK(owner.epoch > epoch + 1 && owner.session > session, "revoked_epoch_nonreuse");
		session = owner.session;
		epoch = owner.epoch;
		CHECK(!swapz_mm_broker_owner_begin_close(session, epoch), "after_revoke_close");
		CHECK(!swapz_ticket_broker_put(&owner), "after_revoke_put");
		CHECK(!swapz_mm_broker_owner_finish_close(session, epoch) && !allocations, "after_revoke_destroy");
	}
}
int main(void)
{
	allocation_failure();
	paused_entrant();
	retained_holders(true);
	retained_holders(false);
	/* Test-private fault injection at a quiescent owner, not a public API. */
	owner_last_identity = ~(swapz_u64)0;
	struct swapz_ticket_cap out = {.session = 99};
	CHECK(swapz_mm_broker_owner_open(1, 3568, 64, &out) == -EOVERFLOW &&
		!out.broker && out.session == 99 && !allocations, "identity_wrap");
	printf("PASS_HOST_ONLY R094 A11 checks=%u scenarios=5\n", checks);
	return 0;
}
