/* SPDX-License-Identifier: GPL-2.0-only */
#include "native-observation-recorder.h"

#include <limits.h>
#include <string.h>

_Static_assert(UINT_MAX >= SWAPZ_OBSERVATION_MAX_RECORDS * 8U,
	       "observation counters must hold the complete token space");

static bool nonzero_digest(const uint8_t digest[32])
{
	uint8_t bits = 0;

	for (size_t index = 0; index < 32; ++index)
		bits |= digest[index];
	return bits != 0;
}

static void mark_loss(struct swapz_observation_recorder *recorder, unsigned flag)
{
	atomic_fetch_or_explicit(&recorder->loss, flag, memory_order_relaxed);
}

/* Reservation is the sequence linearization point, not copy completion.
 * Saturating strong CAS: no counter wrap, no held lock, no unbounded retry.
 * A paused writer owns only its unique slot, not another writer's progress.
 */
static unsigned reserve_next(struct swapz_observation_recorder *recorder,
			     atomic_uint *counter, unsigned limit)
{
	unsigned previous = atomic_load_explicit(counter, memory_order_relaxed);

	for (unsigned attempt = 0; attempt < SWAPZ_OBSERVATION_RESERVATION_ATTEMPTS;
	     ++attempt) {
		if (previous >= limit) {
			mark_loss(recorder, SWAPZ_OBS_LOST_OVERFLOW);
			return 0;
		}
		if (atomic_compare_exchange_strong_explicit(counter, &previous,
				previous + 1U, memory_order_relaxed, memory_order_relaxed))
			return previous + 1U;
		/* Failure refreshes previous; retry only within the fixed budget. */
	}
	mark_loss(recorder, SWAPZ_OBS_LOST_CONTENTION);
	return 0;
}

/* Disabled entry is cheap. Caller lifetime fence protects this entire call. */
static bool enter(const struct swapz_observation_recorder *recorder)
{
	return recorder && atomic_load_explicit(&recorder->enabled, memory_order_acquire);
}

static bool check_late_stop(struct swapz_observation_recorder *recorder)
{
	if (atomic_load_explicit(&recorder->enabled, memory_order_acquire))
		return true;
	mark_loss(recorder, SWAPZ_OBS_LOST_LATE);
	return false;
}

bool swapz_observation_init(struct swapz_observation_recorder *recorder,
			    struct swapz_observation_record *records,
			    size_t capacity, const uint8_t scope_sha256[32])
{
	if (!recorder || !records || !scope_sha256 || !capacity ||
	    capacity > SWAPZ_OBSERVATION_MAX_RECORDS || !nonzero_digest(scope_sha256))
		return false;
	atomic_init(&recorder->enabled, false);
	atomic_init(&recorder->count, 0U);
	atomic_init(&recorder->token_high, 0U);
	atomic_init(&recorder->loss, 0U);
	/* No hidden atomic library locks in this prototype's hot path. */
	if (!atomic_is_lock_free(&recorder->enabled) ||
	    !atomic_is_lock_free(&recorder->count) ||
	    !atomic_is_lock_free(&recorder->token_high) ||
	    !atomic_is_lock_free(&recorder->loss))
		return false;
	recorder->records = records;
	recorder->capacity = capacity;
	recorder->token_limit = (unsigned)capacity * 8U;
	/* Cold initialization of commit markers only; no payload zeroing. */
	for (size_t index = 0; index < capacity; ++index)
		records[index].sequence = 0;
	recorder->sealed = false;
	memcpy(recorder->scope_sha256, scope_sha256, 32);
	atomic_store_explicit(&recorder->enabled, true, memory_order_release);
	return true;
}

uint64_t swapz_observation_mint(struct swapz_observation_recorder *recorder)
{
	if (!enter(recorder))
		return 0;
	/* Bounded token space proportional to capture capacity; no wrap/reuse. */
	const unsigned token = reserve_next(recorder, &recorder->token_high,
					    recorder->token_limit);
	if (!token || !check_late_stop(recorder))
		return 0;
	return token;
}

static bool token_valid(uint64_t token, uint64_t high)
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

_Static_assert(OBS_FIELD_COUNT <= 64, "observation field mask overflow");
#define OBS_BIT(name) (UINT64_C(1) << OBS_FIELD_##name)
static const uint64_t allowed_fields[SWAPZ_OBS_CLEANUP + 1] = {
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
	const uint64_t allowed = allowed_fields[record->event];

#define OBS_CHECK_NUMBER(name) \
	if (!(allowed & OBS_BIT(name)) && record->name) return false;
	SWAPZ_OBSERVATION_U64_FIELDS(OBS_CHECK_NUMBER)
	SWAPZ_OBSERVATION_U32_FIELDS(OBS_CHECK_NUMBER)
#undef OBS_CHECK_NUMBER
#define OBS_CHECK_DIGEST(name) \
	if (!(allowed & OBS_BIT(name)) && nonzero_digest(record->name)) return false;
	SWAPZ_OBSERVATION_DIGEST_FIELDS(OBS_CHECK_DIGEST)
#undef OBS_CHECK_DIGEST
	return record->status <= UINT8_MAX;
}
#undef OBS_BIT

bool swapz_observation_append(struct swapz_observation_recorder *recorder,
			      const struct swapz_observation_record *record)
{
	if (!enter(recorder))
		return false;
	const unsigned token_high = atomic_load_explicit(&recorder->token_high,
							memory_order_relaxed);
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
		return false;
	}
	const unsigned sequence = reserve_next(recorder, &recorder->count,
					       (unsigned)recorder->capacity);
	if (!sequence)
		return false;
	struct swapz_observation_record *destination = &recorder->records[sequence - 1U];

	/* Caller owns immutable event input through this synchronous copy.
	 * Unique slot is private until external producer join; no reader may
	 * observe a partial copy. Sequence is written last as a commit marker.
	 * Finish even on observed late stop, so export never fabricates a slot.
	 */
	*destination = *record;
	destination->sequence = sequence;
	return check_late_stop(recorder);
}

void swapz_observation_stop(struct swapz_observation_recorder *recorder)
{
	if (recorder)
		atomic_store_explicit(&recorder->enabled, false, memory_order_release);
}

bool swapz_observation_seal(struct swapz_observation_recorder *recorder)
{
	if (!recorder || atomic_load_explicit(&recorder->enabled, memory_order_acquire))
		return false;
	/* Caller has already revoked and joined every producer entrant.
	 * Never scan sequence markers concurrently with slot writers.
	 */
	const unsigned count = atomic_load_explicit(&recorder->count, memory_order_relaxed);

	recorder->sealed = false;
	if (count > recorder->capacity) {
		mark_loss(recorder, SWAPZ_OBS_LOST_INVALID);
		return false;
	}
	for (unsigned index = 0; index < count; ++index) {
		if (recorder->records[index].sequence != (uint64_t)index + 1U) {
			mark_loss(recorder, SWAPZ_OBS_LOST_INVALID);
			return false;
		}
	}
	recorder->sealed = true;
	return true;
}

static void put_u32(uint8_t **output, uint32_t value)
{
	for (unsigned index = 0; index < 4; ++index) {
		*(*output)++ = (uint8_t)value;
		value >>= 8;
	}
}

static void put_u64(uint8_t **output, uint64_t value)
{
	for (unsigned index = 0; index < 8; ++index) {
		*(*output)++ = (uint8_t)value;
		value >>= 8;
	}
}

static void put_bytes(uint8_t **output, const void *bytes, size_t length)
{
	memcpy(*output, bytes, length);
	*output += length;
}

static bool export_record(const struct swapz_observation_record *record,
			  swapz_observation_sink sink, void *context)
{
	uint8_t wire[SWAPZ_OBSERVATION_RECORD_BYTES];
	uint8_t *output = wire;

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
	uint8_t header[SWAPZ_OBSERVATION_HEADER_BYTES];
	uint8_t footer[SWAPZ_OBSERVATION_FOOTER_BYTES];
	uint8_t *output = header;
	unsigned loss;

	if (!recorder || !sink || !recorder->sealed ||
	    atomic_load_explicit(&recorder->enabled, memory_order_acquire))
		return false;
	/* External producer fence/join makes count, records and loss immutable. */
	const unsigned count = atomic_load_explicit(&recorder->count, memory_order_relaxed);
	const unsigned token_high = atomic_load_explicit(&recorder->token_high,
							memory_order_relaxed);
	if (count > recorder->capacity)
		return false;
	loss = atomic_load_explicit(&recorder->loss, memory_order_relaxed);
	put_bytes(&output, "SWZOBS2\0", 8);
	put_bytes(&output, SWAPZ_OBSERVATION_MAPPING_SOURCE, 40);
	put_bytes(&output, recorder->scope_sha256, 32);
	put_u64(&output, (uint64_t)count);
	put_u64(&output, token_high);
	put_u32(&output, (uint32_t)recorder->capacity);
	put_u32(&output, SWAPZ_OBSERVATION_RECORD_BYTES);
	if ((size_t)(output - header) != sizeof(header) ||
	    !sink(context, header, sizeof(header)))
		return false;
	for (size_t index = 0; index < count; ++index)
		if (!export_record(&recorder->records[index], sink, context))
			return false;
	output = footer;
	put_bytes(&output, "SWZEND2\0", 8);
	put_u64(&output, (uint64_t)count);
	put_u32(&output, (uint32_t)loss);
	put_u32(&output, 0); /* reserved; must remain zero */
	return (size_t)(output - footer) == sizeof(footer) &&
		sink(context, footer, sizeof(footer));
}
