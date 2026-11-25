/* SPDX-License-Identifier: GPL-2.0-only */
/* Exact staged broker, modeled external owner admission and module ABI.
 * No real DM setup, kernel RCU, module loader or device access.
 */
#include <errno.h>
#include <stdalign.h>
#include <string.h>
#include "round092-module-shim.h"
#include "zswap-original-ticket.h"

static unsigned int checks;
#define CHECK(condition, witness) do { \
	++checks; \
	if (!(condition)) { \
		fprintf(stderr, "R093_A11_FIRST_ERROR %s line=%d\n", witness, __LINE__); \
		exit(77); \
	} \
} while (0)

/* The gate survives the allocation it protects. Single lifecycle owner;
 * new entrants obtain a pointer and increment the count under one lock.
 * No broker operation is performed while holding this foreign lock.
 */
struct storage {
	struct swapz_ticket_broker broker;
	struct swapz_ticket_slot slots[1];
	swapz_u32 indices[1];
	alignas(64) swapz_u8 payload[3584];
};
struct owner_gate {
	pthread_mutex_t lock;
	struct storage *storage;
	unsigned int entrants;
	bool accepting;
};
struct pending_context {
	struct owner_gate *gate;
	pthread_barrier_t arrived, resume;
	int result;
};
static void must(int error)
{
	if (error) {
		fprintf(stderr, "R093_A11_INFRA pthread=%d\n", error);
		exit(78);
	}
}
static void meet(pthread_barrier_t *barrier)
{
	int error = pthread_barrier_wait(barrier);
	if (error != PTHREAD_BARRIER_SERIAL_THREAD)
		must(error);
}
static void owner_init(struct owner_gate *gate)
{
	must(pthread_mutex_init(&gate->lock, NULL));
	gate->storage = aligned_alloc(alignof(struct storage), sizeof(struct storage));
	CHECK(gate->storage, "allocation");
	memset(gate->storage, 0, sizeof(*gate->storage));
	struct storage *storage = gate->storage;
	CHECK(!swapz_ticket_init(&storage->broker, storage->slots, sizeof(storage->slots),
		storage->payload, sizeof(storage->payload), storage->indices,
		sizeof(storage->indices), 1, 3568, 64, 17, 20), "init");
	gate->entrants = 0;
	gate->accepting = true;
}
static struct storage *owner_enter(struct owner_gate *gate)
{
	struct storage *storage = NULL;
	must(pthread_mutex_lock(&gate->lock));
	if (gate->accepting) {
		storage = gate->storage;
		++gate->entrants;
	}
	must(pthread_mutex_unlock(&gate->lock));
	return storage;
}
static void owner_leave(struct owner_gate *gate)
{
	must(pthread_mutex_lock(&gate->lock));
	if (!gate->entrants)
		must(EINVAL);
	--gate->entrants;
	must(pthread_mutex_unlock(&gate->lock));
}
static void owner_unpublish(struct owner_gate *gate)
{
	must(pthread_mutex_lock(&gate->lock));
	gate->accepting = false;
	must(pthread_mutex_unlock(&gate->lock));
}
static int owner_finish(struct owner_gate *gate)
{
	/* Only the lifecycle owner calls finish. Closed admission is permanent
	 * until destruction; once zero entrants is observed it stays zero.
	 * Independent ticket/capability holders are fenced by broker destroy.
	 */
	must(pthread_mutex_lock(&gate->lock));
	bool blocked = gate->accepting || gate->entrants != 0U;
	must(pthread_mutex_unlock(&gate->lock));
	if (blocked)
		return -EBUSY;
	int error = swapz_ticket_destroy(&gate->storage->broker);
	if (!error) {
		free(gate->storage);
		gate->storage = NULL;
	}
	return error;
}
static void *pending_entrant(void *opaque)
{
	struct pending_context *context = opaque;
	struct storage *storage = owner_enter(context->gate);
	if (!storage)
		must(EINVAL);
	meet(&context->arrived);
	meet(&context->resume);
	struct swapz_ticket_cap cap = {0};
	context->result = swapz_ticket_broker_try_get(&storage->broker, 17, 20, &cap);
	if (cap.broker)
		must(swapz_ticket_broker_put(&cap));
	owner_leave(context->gate);
	return NULL;
}
static void pre_reference_entrant(void)
{
	struct owner_gate gate = {0};
	struct pending_context context = {.gate = &gate};
	struct swapz_ticket_usage usage = {0};
	pthread_t thread;
	owner_init(&gate);
	must(pthread_barrier_init(&context.arrived, NULL, 2));
	must(pthread_barrier_init(&context.resume, NULL, 2));
	must(pthread_create(&thread, NULL, pending_entrant, &context));
	meet(&context.arrived);
	owner_unpublish(&gate);
	CHECK(!owner_enter(&gate), "late_entrant_refusal");
	CHECK(!swapz_ticket_usage(&gate.storage->broker, &usage) &&
		!usage.live_slots && !gate.storage->broker.capability_refs, "zero_counted_refs");
	CHECK(!swapz_ticket_revoke(&gate.storage->broker, 21), "revoke_before_close");
	CHECK(!swapz_ticket_close(&gate.storage->broker), "close_zero_refs");
	/* Close succeeded, but the pre-reference borrower still owns access. */
	CHECK(owner_finish(&gate) == -EBUSY && gate.storage, "pre_reference_entrant_fence");
	meet(&context.resume);
	must(pthread_join(thread, NULL));
	CHECK(context.result == -ESTALE, "inflight_entrant_refused");
	CHECK(!owner_finish(&gate) && !gate.storage, "destroy_after_join");
	CHECK(!owner_enter(&gate), "post_free_admission_refused");
	must(pthread_barrier_destroy(&context.arrived));
	must(pthread_barrier_destroy(&context.resume));
	must(pthread_mutex_destroy(&gate.lock));
}
static void independent_capability(void)
{
	struct owner_gate gate = {0};
	struct swapz_ticket_cap cap = {0};
	owner_init(&gate);
	CHECK(!swapz_ticket_broker_try_get(&gate.storage->broker, 17, 20, &cap), "cap_get");
	owner_unpublish(&gate);
	CHECK(swapz_ticket_close(&gate.storage->broker) == -EBUSY, "cap_only_close_busy");
	CHECK(owner_finish(&gate) == -EBUSY && gate.storage, "cap_only_destroy_busy");
	CHECK(!swapz_ticket_broker_put(&cap) && !cap.broker, "cap_drop");
	CHECK(!owner_finish(&gate), "cap_only_destroy_after_drop");
	must(pthread_mutex_destroy(&gate.lock));
}
static void ordered_candidate(bool claim_first, bool revoke_first, bool cap_first)
{
	struct owner_gate gate = {0};
	struct module module = {.live = true};
	struct swapz_ticket_ref producer = {0}, candidate = {0};
	struct swapz_ticket_cap cap = {0};
	struct swapz_ticket_view view = {0};
	swapz_u8 bytes[64];
	struct swapz_ticket_key key = {
		.area_epoch = 1, .store_sequence = 1, .slot_offset = 2,
		.target_session = 17, .table_epoch = 20, .target_epoch = 3,
		.logical_page = 4, .dm_generation = 5, .swap_type = 1,
		.length = 64, .decoded_length = 4096, .representation = SWAPZ_TICKET_ORIGINAL,
		.codec = SWAPZ_TICKET_LZ4, .version = 1
	};
	owner_init(&gate);
	struct swapz_ticket_broker *broker = &gate.storage->broker;
	memset(bytes, 0x5b, sizeof(bytes));
	key.crc = swapz_crc32c_bytes(bytes, (swapz_u32)sizeof(bytes));
	CHECK(!swapz_ticket_broker_try_get(broker, 17, 20, &cap), "route_cap");
	CHECK(!swapz_ticket_reserve(broker, &key, &producer), "reserve");
	CHECK(!swapz_ticket_seal(&producer, bytes, (swapz_u32)sizeof(bytes)), "seal");
	/* Model the already-qualified MM candidate acquisition: independent
	 * module pin and actual retained ticket; producer lease has no pin.
	 */
	CHECK(try_module_get(&module), "candidate_module_get");
	CHECK(!swapz_ticket_retain(&producer, &candidate), "candidate_retain");
	candidate.provider_owner = &module;
	CHECK(!swapz_ticket_put(&producer), "producer_drop");
	owner_unpublish(&gate);
	if (claim_first) {
		CHECK(!swapz_ticket_claim_under_queue_lock(&candidate, &key), "claim_before_revoke");
		CHECK(!swapz_ticket_revoke(broker, 21), "revoke_after_claim");
		CHECK(swapz_ticket_claim_under_queue_lock(&candidate, &key) == -ESTALE, "claimed_then_revoked_refusal");
	} else if (revoke_first) {
		CHECK(!swapz_ticket_revoke(broker, 21), "revoke_before_claim");
		CHECK(swapz_ticket_claim_under_queue_lock(&candidate, &key) == -ESTALE, "revoked_claim_refusal");
	} else {
		/* Close at the same epoch independently exercises the closing fence. */
		CHECK(swapz_ticket_close(broker) == -EBUSY, "close_before_claim");
		CHECK(swapz_ticket_claim_under_queue_lock(&candidate, &key) == -ESTALE, "closed_claim_refusal");
	}
	CHECK(swapz_ticket_close(broker) == -EBUSY, "both_close_busy");
	CHECK(!swapz_ticket_view(&candidate, &view) && !memcmp(view.bytes, bytes, sizeof(bytes)),
		"retired_bytes_pinned");
	if (cap_first) {
		CHECK(!swapz_ticket_broker_put(&cap), "cap_first_drop");
		CHECK(owner_finish(&gate) == -EBUSY && atomic_load(&module.refs) == 1U,
			"candidate_only_destroy_busy");
		CHECK(!swapz_ticket_put(&candidate), "candidate_last_drop");
	} else {
		CHECK(!swapz_ticket_put(&candidate) && !atomic_load(&module.refs), "candidate_first_drop");
		CHECK(owner_finish(&gate) == -EBUSY, "remaining_cap_destroy_busy");
		CHECK(!swapz_ticket_broker_put(&cap), "cap_last_drop");
	}
	CHECK(!atomic_load(&module.refs), "module_pin_drained");
	CHECK(!owner_finish(&gate), "all_holders_destroy");
	must(pthread_mutex_destroy(&gate.lock));
}
int main(void)
{
	pre_reference_entrant();
	independent_capability();
	ordered_candidate(true, false, true);
	ordered_candidate(false, true, false);
	ordered_candidate(false, false, false);
	printf("PASS_HOST_ONLY R093 A11 checks=%u scenarios=5\n", checks);
	return 0;
}
