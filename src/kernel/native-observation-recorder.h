/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_KERNEL_OBSERVATION_RECORDER_H
#define SWAPZ_KERNEL_OBSERVATION_RECORDER_H

/*
 * Guarded kernel adapter only: no producer, Kbuild or activation here.
 * Caller owns preallocated contiguous storage and external entrant lifetime.
 * No allocation, formatting, hashing, I/O, waiting or callbacks in append.
 * A bounded atomic reservation assigns a unique slot before its private copy.
 * Exhausted retries or capacity lose evidence, never block product progress.
 */
#include <linux/types.h>
#include <linux/atomic.h>

#define SWAPZ_OBSERVATION_MAX_RECORDS 8192U
#define SWAPZ_OBSERVATION_RESERVATION_ATTEMPTS 64U
#define SWAPZ_OBSERVATION_DIGEST_BYTES 32U
#define SWAPZ_OBSERVATION_MAPPING_SOURCE "ff972661a75ca7f8c3c0458c3feb8b603c185eb8"
#define SWAPZ_OBSERVATION_HEADER_BYTES 104U
#define SWAPZ_OBSERVATION_RECORD_BYTES 296U
#define SWAPZ_OBSERVATION_FOOTER_BYTES 24U

/* Fixed little-endian wire order, no structure padding on the wire. */
#define SWAPZ_OBSERVATION_U64_FIELDS(X) \
	X(sequence) X(operation) X(descriptor) X(clone) X(original) \
	X(lower) X(extent) X(pin) X(slot) X(area_epoch) X(store) \
	X(gc_epoch) X(credit)
#define SWAPZ_OBSERVATION_U32_FIELDS(X) \
	X(event) X(operation_kind) X(logical) X(swap_type) X(generation) \
	X(new_generation) X(status) X(requested) X(completed) \
	X(compressed_length) X(decoded_length) X(compared) X(codec) \
	X(tag) X(version) X(dictionary) X(flags) X(caps) X(tickets) \
	X(pins) X(reservations) X(bios) X(maps) X(quarantines)
#define SWAPZ_OBSERVATION_DIGEST_FIELDS(X) \
	X(compressed_sha256) X(page_sha256) X(observed_sha256)

enum swapz_native_observation_event {
	SWAPZ_OBS_CAPTURE = 1,
	SWAPZ_OBS_BIND,
	SWAPZ_OBS_ACCEPT,
	SWAPZ_OBS_DISPATCH,
	SWAPZ_OBS_PREPARATION,
	SWAPZ_OBS_RESERVE,
	SWAPZ_OBS_CLAIM,
	SWAPZ_OBS_REFUSE,
	SWAPZ_OBS_CANCEL,
	SWAPZ_OBS_FALLBACK,
	SWAPZ_OBS_LOWER_SUBMIT,
	SWAPZ_OBS_LOWER_COMPLETE,
	SWAPZ_OBS_FLUSH,
	SWAPZ_OBS_PUBLISH,
	SWAPZ_OBS_PIN,
	SWAPZ_OBS_ORACLE,
	SWAPZ_OBS_PIN_RELEASE,
	SWAPZ_OBS_CLONE_ENDIO,
	SWAPZ_OBS_UPPER_ENDIO,
	SWAPZ_OBS_CANDIDATE_RELEASE,
	SWAPZ_OBS_CARRIER_RELEASE,
	SWAPZ_OBS_DISCARD,
	SWAPZ_OBS_QUARANTINE,
	SWAPZ_OBS_GC_BEGIN,
	SWAPZ_OBS_GC_END,
	SWAPZ_OBS_CAPTURE_DROP,
	SWAPZ_OBS_CLEANUP
};

enum swapz_native_observation_kind {
	SWAPZ_OBS_TYPED_WRITE = 1,
	SWAPZ_OBS_TYPED_READ,
	SWAPZ_OBS_ORDINARY_WRITE,
	SWAPZ_OBS_DISCARD_BIO,
	SWAPZ_OBS_GC
};

enum swapz_native_observation_loss {
	SWAPZ_OBS_LOST_CONTENTION = 1U,
	SWAPZ_OBS_LOST_OVERFLOW = 2U,
	SWAPZ_OBS_LOST_INVALID = 4U,
	SWAPZ_OBS_LOST_LATE = 8U
};

struct swapz_native_observation_record {
#define SWAPZ_OBS_FIELD64(name) u64 name;
	SWAPZ_OBSERVATION_U64_FIELDS(SWAPZ_OBS_FIELD64)
#undef SWAPZ_OBS_FIELD64
#define SWAPZ_OBS_FIELD32(name) u32 name;
	SWAPZ_OBSERVATION_U32_FIELDS(SWAPZ_OBS_FIELD32)
#undef SWAPZ_OBS_FIELD32
#define SWAPZ_OBS_DIGEST(name) u8 name[SWAPZ_OBSERVATION_DIGEST_BYTES];
	SWAPZ_OBSERVATION_DIGEST_FIELDS(SWAPZ_OBS_DIGEST)
#undef SWAPZ_OBS_DIGEST
};

/* Separate naturally aligned 32-bit release/acquire commit marker. */
struct swapz_native_observation_slot {
	struct swapz_native_observation_record record;
	u32 published;
};

struct swapz_native_observation_recorder {
	struct swapz_native_observation_slot *slots;
	size_t capacity;
	atomic_t count;
	atomic_t token_high;
	int token_limit;
	u8 scope_sha256[SWAPZ_OBSERVATION_DIGEST_BYTES];
	bool enabled;
	atomic_t loss;
	/* Lifecycle operations are serialized by the external owner. */
	bool started;
	bool stopped;
	bool drained;
	bool sealed;
};

typedef bool (*swapz_native_observation_sink)(void *context, const u8 *bytes,
				      size_t length);

/* Init leaves capture disabled. Owner and slots must be disjoint, valid,
 * preallocated and exclusively owned; scope must not alias either. No
 * concurrent init/reuse. A failed init must not be published or started.
 */
bool swapz_native_observation_init(struct swapz_native_observation_recorder *recorder,
			    struct swapz_native_observation_slot *slots,
			    size_t capacity, const u8 scope_sha256[32]);
/* One-shot start before publishing to producers, not a production gate. */
bool swapz_native_observation_start(struct swapz_native_observation_recorder *recorder);
/* Tokens are monotonically minted run-local integers, never pointer-derived. */
u64 swapz_native_observation_mint(struct swapz_native_observation_recorder *recorder);
bool swapz_native_observation_append(struct swapz_native_observation_recorder *recorder,
			      const struct swapz_native_observation_record *record);
/*
 * Every entrant (including one paused before the first enabled load) holds
 * an external lifetime reference. Stop disables append/mint but does not
 * revoke those references. Drain is a sleepable owner operation: the supplied
 * callback must revoke publication and synchronously join ALL such entrants,
 * including deferred callbacks. False means retain all memory and retry the
 * join; never seal/free. No lifecycle operation is concurrent with another.
 * No re-enable, no pointer-derived tokens, no I/O/hash/allocation in append.
 * The externally serialized owner also owns the export sink and storage until
 * export returns. Sequence reservation alone is NOT causal completion order.
 */
typedef bool (*swapz_native_observation_join)(void *context);
void swapz_native_observation_stop(struct swapz_native_observation_recorder *recorder);
bool swapz_native_observation_drain(struct swapz_native_observation_recorder *recorder,
			   swapz_native_observation_join revoke_and_join, void *context);
bool swapz_native_observation_seal(struct swapz_native_observation_recorder *recorder);
/* Only sealed immutable records; export loss flags, never hide failed sink. */
bool swapz_native_observation_export(const struct swapz_native_observation_recorder *recorder,
			      swapz_native_observation_sink sink, void *context);

#endif
