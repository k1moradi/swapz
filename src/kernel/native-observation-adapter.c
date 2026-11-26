/* SPDX-License-Identifier: GPL-2.0-only */
#include "native-observation-adapter.h"

#include <linux/build_bug.h>
#include <linux/limits.h>
#include <linux/string.h>

/* Supported native targets have a naturally atomic, aligned u64 marker. */
static_assert(sizeof(unsigned long) == sizeof(u64));
static_assert(sizeof(struct swapz_observation_record) == SWAPZ_OBSERVATION_RECORD_BYTES);
static_assert(INT_MAX >= SWAPZ_OBSERVATION_MAX_RECORDS * 8U);

static bool nonzero_digest(const u8 digest[32])
{
	u8 bits = 0;

	for (size_t index = 0; index < 32; ++index)
		bits |= digest[index];
	return bits != 0;
}

static void mark_loss(struct swapz_observation_recorder *recorder, unsigned flag)
{
	atomic_or((int)flag, &recorder->loss);
}

/* Reservation is the sequence linearization point, not copy completion.
 * Saturating strong CAS: no counter wrap, no held lock, no unbounded retry.
 * A paused writer owns only its unique slot, not another writer's progress.
 */
static unsigned reserve_next(struct swapz_observation_recorder *recorder,
			     atomic_t *counter, int limit)
{
	int previous = atomic_read(counter);

	for (unsigned attempt = 0; attempt < SWAPZ_OBSERVATION_RESERVATION_ATTEMPTS;
	     ++attempt) {
		if (previous >= limit) {
			mark_loss(recorder, SWAPZ_OBS_LOST_OVERFLOW);
			return 0;
		}
		if (atomic_try_cmpxchg_relaxed(counter, &previous, previous + 1))
			return (unsigned)previous + 1U;
		/* Failure refreshes previous; retry only within the fixed budget. */
	}
	mark_loss(recorder, SWAPZ_OBS_LOST_CONTENTION);
	return 0;
}

/* The inactive fast path touches only the stable gate, not the recorder. */
static struct swapz_observation_recorder *enter(struct swapz_observation_gate *gate)
{
	struct swapz_observation_recorder *recorder;

	if (!gate || !rcu_access_pointer(gate->active))
		return NULL;
	rcu_read_lock();
	recorder = rcu_dereference(gate->active);
	if (!recorder || !smp_load_acquire(&recorder->enabled)) {
		rcu_read_unlock();
		return NULL;
	}
	return recorder;
}

static bool check_late_stop(struct swapz_observation_recorder *recorder)
{
	if (smp_load_acquire(&recorder->enabled))
		return true;
	mark_loss(recorder, SWAPZ_OBS_LOST_LATE);
	return false;
}

bool swapz_observation_init(struct swapz_observation_recorder *recorder,
			    struct swapz_observation_record *records,
			    size_t capacity, const u8 scope_sha256[32])
{
	if (!recorder || !records || !scope_sha256 || !capacity ||
	    capacity > SWAPZ_OBSERVATION_MAX_RECORDS || !nonzero_digest(scope_sha256))
		return false;
	recorder->enabled = false;
	atomic_set(&recorder->count, 0);
	atomic_set(&recorder->token_high, 0);
	atomic_set(&recorder->loss, 0);
	recorder->drained = false;
	recorder->records = records;
	recorder->capacity = capacity;
	recorder->token_limit = (int)capacity * 8;
	/* Cold initialization of commit markers only; no payload zeroing. */
	for (size_t index = 0; index < capacity; ++index)
		records[index].sequence = 0;
	recorder->sealed = false;
	memcpy(recorder->scope_sha256, scope_sha256, 32);
	return true;
}

void swapz_observation_gate_init(struct swapz_observation_gate *gate)
{
	RCU_INIT_POINTER(gate->active, NULL);
	gate->retained = NULL;
	gate->used = false;
}

bool swapz_observation_publish(struct swapz_observation_gate *gate,
			       struct swapz_observation_recorder *recorder)
{
	if (!gate || gate->used || !recorder || !recorder->records ||
	    recorder->drained || recorder->sealed || smp_load_acquire(&recorder->enabled))
		return false;
	gate->used = true;
	gate->retained = recorder;
	smp_store_release(&recorder->enabled, true);
	rcu_assign_pointer(gate->active, recorder);
	return true;
}

u64 swapz_observation_mint(struct swapz_observation_gate *gate)
{
	struct swapz_observation_recorder *recorder = enter(gate);
	unsigned token;

	if (!recorder)
		return 0;
	token = reserve_next(recorder, &recorder->token_high, recorder->token_limit);
	if (!check_late_stop(recorder))
		token = 0;
	rcu_read_unlock();
	return token;
}

static bool token_valid(u64 token, u64 high)
{
	return token <= high;
}

/* Explicit wire field allowlist: reject unused values before retaining/exporting
 * them. Numeric tokens are minted IDs, not addresses. The producer must still
 * provide actual digests/source keys, never fill allowed fields with raw data.
 */
enum observation_field {
#define OBS_INDEX(name) OBS_FIELD_##name,
	SWAPZ_OBSERVATION_U64_FIELDS(OBS_INDEX)
	SWAPZ_OBSERVATION_U32_FIELDS(OBS_INDEX)
	SWAPZ_OBSERVATION_DIGEST_FIELDS(OBS_INDEX)
#undef OBS_INDEX
	OBS_FIELD_COUNT
};

static_assert(OBS_FIELD_COUNT <= 64, "observation field mask overflow");
#define OBS_BIT(name) (1ULL << OBS_FIELD_##name)
static const u64 allowed_fields[SWAPZ_OBS_CLEANUP + 1] = {
	[SWAPZ_OBS_CAPTURE] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(operation_kind) |
		OBS_BIT(logical) | OBS_BIT(swap_type) | OBS_BIT(slot) | OBS_BIT(area_epoch) |
		OBS_BIT(store) | OBS_BIT(generation) | OBS_BIT(compressed_length) |
		OBS_BIT(decoded_length) | OBS_BIT(codec) | OBS_BIT(tag) | OBS_BIT(version) |
		OBS_BIT(dictionary) | OBS_BIT(compressed_sha256) | OBS_BIT(page_sha256),
	[SWAPZ_OBS_BIND] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(original),
	[SWAPZ_OBS_ACCEPT] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(operation_kind) |
		OBS_BIT(descriptor) | OBS_BIT(clone) | OBS_BIT(original) | OBS_BIT(flags) |
		OBS_BIT(logical) | OBS_BIT(swap_type) | OBS_BIT(slot) | OBS_BIT(area_epoch) |
		OBS_BIT(store) | OBS_BIT(generation),
	[SWAPZ_OBS_DISPATCH] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(flags),
	[SWAPZ_OBS_PREPARATION] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(flags),
	[SWAPZ_OBS_RESERVE] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(credit) |
		OBS_BIT(extent),
	[SWAPZ_OBS_CLAIM] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(credit) |
		OBS_BIT(descriptor),
	[SWAPZ_OBS_REFUSE] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(status),
	[SWAPZ_OBS_CANCEL] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(credit) | OBS_BIT(flags),
	[SWAPZ_OBS_FALLBACK] = OBS_BIT(event) | OBS_BIT(operation),
	[SWAPZ_OBS_LOWER_SUBMIT] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(lower) |
		OBS_BIT(extent) | OBS_BIT(flags) | OBS_BIT(requested) | OBS_BIT(compressed_length) |
		OBS_BIT(compressed_sha256),
	[SWAPZ_OBS_LOWER_COMPLETE] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(lower) |
		OBS_BIT(completed) | OBS_BIT(status) | OBS_BIT(observed_sha256),
	[SWAPZ_OBS_FLUSH] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(extent) | OBS_BIT(status),
	[SWAPZ_OBS_PUBLISH] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(extent) |
		OBS_BIT(new_generation) | OBS_BIT(gc_epoch) | OBS_BIT(compressed_length) |
		OBS_BIT(decoded_length) | OBS_BIT(codec) | OBS_BIT(tag) | OBS_BIT(version) |
		OBS_BIT(dictionary) | OBS_BIT(compressed_sha256) | OBS_BIT(page_sha256),
	[SWAPZ_OBS_PIN] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(pin) | OBS_BIT(extent) |
		OBS_BIT(gc_epoch) | OBS_BIT(logical) | OBS_BIT(swap_type) | OBS_BIT(slot) |
		OBS_BIT(area_epoch) | OBS_BIT(store) | OBS_BIT(generation),
	[SWAPZ_OBS_ORACLE] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(pin) |
		OBS_BIT(decoded_length) | OBS_BIT(compared) | OBS_BIT(flags) | OBS_BIT(status) |
		OBS_BIT(page_sha256) | OBS_BIT(observed_sha256),
	[SWAPZ_OBS_PIN_RELEASE] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(pin) |
		OBS_BIT(status),
	[SWAPZ_OBS_CLONE_ENDIO] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(descriptor) |
		OBS_BIT(clone) | OBS_BIT(status),
	[SWAPZ_OBS_UPPER_ENDIO] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(original) |
		OBS_BIT(status),
	[SWAPZ_OBS_CANDIDATE_RELEASE] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(descriptor) |
		OBS_BIT(status),
	[SWAPZ_OBS_CARRIER_RELEASE] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(original) |
		OBS_BIT(status),
	[SWAPZ_OBS_DISCARD] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(new_generation),
	[SWAPZ_OBS_QUARANTINE] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(extent),
	[SWAPZ_OBS_GC_BEGIN] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(operation_kind) |
		OBS_BIT(extent) | OBS_BIT(gc_epoch) | OBS_BIT(logical) | OBS_BIT(swap_type) |
		OBS_BIT(slot) | OBS_BIT(area_epoch) | OBS_BIT(store) | OBS_BIT(generation),
	[SWAPZ_OBS_GC_END] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(status),
	[SWAPZ_OBS_CAPTURE_DROP] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(status),
	[SWAPZ_OBS_CLEANUP] = OBS_BIT(event) | OBS_BIT(operation) | OBS_BIT(flags) | OBS_BIT(caps) |
		OBS_BIT(tickets) | OBS_BIT(pins) | OBS_BIT(reservations) | OBS_BIT(bios) | OBS_BIT(maps) |
		OBS_BIT(quarantines),
};

static bool event_fields_valid(const struct swapz_observation_record *record)
{
	const u64 allowed = allowed_fields[record->event];

#define OBS_CHECK_NUMBER(name) \
	if (!(allowed & OBS_BIT(name)) && record->name) return false;
	SWAPZ_OBSERVATION_U64_FIELDS(OBS_CHECK_NUMBER)
	SWAPZ_OBSERVATION_U32_FIELDS(OBS_CHECK_NUMBER)
#undef OBS_CHECK_NUMBER
#define OBS_CHECK_DIGEST(name) \
	if (!(allowed & OBS_BIT(name)) && nonzero_digest(record->name)) return false;
	SWAPZ_OBSERVATION_DIGEST_FIELDS(OBS_CHECK_DIGEST)
#undef OBS_CHECK_DIGEST
	return record->status <= U8_MAX;
}
#undef OBS_BIT

bool swapz_observation_append(struct swapz_observation_gate *gate,
			      const struct swapz_observation_record *record)
{
	struct swapz_observation_recorder *recorder = enter(gate);
	struct swapz_observation_record *destination;
	unsigned token_high, sequence;
	bool result = false;

	if (!recorder)
		return false;
	token_high = (unsigned)atomic_read(&recorder->token_high);
	if (!record || record->sequence || record->event < SWAPZ_OBS_CAPTURE ||
	    record->event > SWAPZ_OBS_CLEANUP || !event_fields_valid(record) ||
	    (record->event == SWAPZ_OBS_CLEANUP ? record->operation != 0 :
						 record->operation == 0) ||
	    !token_valid(record->operation, token_high) ||
	    !token_valid(record->descriptor, token_high) ||
	    !token_valid(record->clone, token_high) ||
	    !token_valid(record->original, token_high) ||
	    !token_valid(record->lower, token_high) ||
	    !token_valid(record->extent, token_high) ||
	    !token_valid(record->pin, token_high)) {
		mark_loss(recorder, SWAPZ_OBS_LOST_INVALID);
		goto out;
	}
	sequence = reserve_next(recorder, &recorder->count, (int)recorder->capacity);
	if (!sequence)
		goto out;
	destination = &recorder->records[sequence - 1U];

	/* Reservation order is not completion order. The producer must reserve
	 * at the authoritative transition or express only supported partial order.
	 * No reader touches payload before external drain and acquire of sequence.
	 */
	*destination = *record;
	smp_store_release(&destination->sequence, (u64)sequence);
	result = true;
out:
	if (!check_late_stop(recorder))
		result = false;
	rcu_read_unlock();
	return result;
}

bool swapz_observation_stop(struct swapz_observation_gate *gate)
{
	struct swapz_observation_recorder *recorder;

	if (!gate || !gate->used)
		return false;
	recorder = gate->retained;
	if (!recorder)
		return true;
	smp_store_release(&recorder->enabled, false);
	rcu_assign_pointer(gate->active, NULL);
	synchronize_rcu();
	/* All entrants that obtained the recorder have finished their copies. */
	recorder->drained = true;
	gate->retained = NULL;
	return true;
}

bool swapz_observation_seal(struct swapz_observation_recorder *recorder)
{
	unsigned count;

	if (!recorder || !recorder->drained || smp_load_acquire(&recorder->enabled))
		return false;
	/* Control is serialized and the RCU drain has completed. */
	count = (unsigned)atomic_read(&recorder->count);

	recorder->sealed = false;
	if (count > recorder->capacity) {
		mark_loss(recorder, SWAPZ_OBS_LOST_INVALID);
		return false;
	}
	for (unsigned index = 0; index < count; ++index) {
		if (smp_load_acquire(&recorder->records[index].sequence) != (u64)index + 1U) {
			mark_loss(recorder, SWAPZ_OBS_LOST_INVALID);
			return false;
		}
	}
	recorder->sealed = true;
	return true;
}

static void put_u32(u8 **output, u32 value)
{
	for (unsigned index = 0; index < 4; ++index) {
		*(*output)++ = (u8)value;
		value >>= 8;
	}
}

static void put_u64(u8 **output, u64 value)
{
	for (unsigned index = 0; index < 8; ++index) {
		*(*output)++ = (u8)value;
		value >>= 8;
	}
}

static void put_bytes(u8 **output, const void *bytes, size_t length)
{
	memcpy(*output, bytes, length);
	*output += length;
}

static bool export_record(const struct swapz_observation_record *record,
			  swapz_observation_sink sink, void *context)
{
	u8 wire[SWAPZ_OBSERVATION_RECORD_BYTES];
	u8 *output = wire;

#define SWAPZ_OBS_WRITE64(name) put_u64(&output, record->name);
	SWAPZ_OBSERVATION_U64_FIELDS(SWAPZ_OBS_WRITE64)
#undef SWAPZ_OBS_WRITE64
#define SWAPZ_OBS_WRITE32(name) put_u32(&output, record->name);
	SWAPZ_OBSERVATION_U32_FIELDS(SWAPZ_OBS_WRITE32)
#undef SWAPZ_OBS_WRITE32
#define SWAPZ_OBS_WRITE_DIGEST(name) put_bytes(&output, record->name, 32);
	SWAPZ_OBSERVATION_DIGEST_FIELDS(SWAPZ_OBS_WRITE_DIGEST)
#undef SWAPZ_OBS_WRITE_DIGEST
	return (size_t)(output - wire) == sizeof(wire) && sink(context, wire, sizeof(wire));
}

bool swapz_observation_export(const struct swapz_observation_recorder *recorder,
			      swapz_observation_sink sink, void *context)
{
	u8 header[SWAPZ_OBSERVATION_HEADER_BYTES];
	u8 footer[SWAPZ_OBSERVATION_FOOTER_BYTES];
	u8 *output = header;
	unsigned count, token_high, loss;

	if (!recorder || !sink || !recorder->drained || !recorder->sealed ||
	    smp_load_acquire(&recorder->enabled))
		return false;
	/* External producer fence/join makes count, records and loss immutable. */
	count = (unsigned)atomic_read(&recorder->count);
	token_high = (unsigned)atomic_read(&recorder->token_high);
	if (count > recorder->capacity)
		return false;
	loss = (unsigned)atomic_read(&recorder->loss);
	put_bytes(&output, "SWZOBS2\0", 8);
	put_bytes(&output, SWAPZ_OBSERVATION_MAPPING_SOURCE, 40);
	put_bytes(&output, recorder->scope_sha256, 32);
	put_u64(&output, (u64)count);
	put_u64(&output, token_high);
	put_u32(&output, (u32)recorder->capacity);
	put_u32(&output, SWAPZ_OBSERVATION_RECORD_BYTES);
	if ((size_t)(output - header) != sizeof(header) ||
	    !sink(context, header, sizeof(header)))
		return false;
	for (size_t index = 0; index < count; ++index)
		if (!export_record(&recorder->records[index], sink, context))
			return false;
	output = footer;
	put_bytes(&output, "SWZEND2\0", 8);
	put_u64(&output, (u64)count);
	put_u32(&output, (u32)loss);
	put_u32(&output, 0); /* reserved; must remain zero */
	return (size_t)(output - footer) == sizeof(footer) &&
		sink(context, footer, sizeof(footer));
}
