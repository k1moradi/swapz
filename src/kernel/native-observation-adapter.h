/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_NATIVE_OBSERVATION_ADAPTER_H
#define SWAPZ_NATIVE_OBSERVATION_ADAPTER_H

/*
 * Guarded native adapter; no normal Kbuild entry, producers or activation.
 * Wire schema is the frozen R095 host recorder v2.
 * One-shot gate and recorder; caller owns preallocated contiguous records.
 * All control operations are serialized in process context by the owner.
 * Gate itself must outlive every potential caller, including pre-RCU entry.
 */
#ifndef SWAPZ_NATIVE_OBSERVATION_ADAPTER
#error "native observation adapter requires an explicit development build guard"
#endif
#include <linux/types.h>
#include <linux/atomic.h>
#include <linux/rcupdate.h>

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

enum swapz_observation_event {
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

enum swapz_observation_kind {
	SWAPZ_OBS_TYPED_WRITE = 1,
	SWAPZ_OBS_TYPED_READ,
	SWAPZ_OBS_ORDINARY_WRITE,
	SWAPZ_OBS_DISCARD_BIO,
	SWAPZ_OBS_GC
};

enum swapz_observation_loss {
	SWAPZ_OBS_LOST_CONTENTION = 1U,
	SWAPZ_OBS_LOST_OVERFLOW = 2U,
	SWAPZ_OBS_LOST_INVALID = 4U,
	SWAPZ_OBS_LOST_LATE = 8U
};

struct swapz_observation_record {
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

struct swapz_observation_recorder {
	struct swapz_observation_record *records;
	size_t capacity;
	atomic_t count;
	atomic_t token_high;
	int token_limit;
	u8 scope_sha256[SWAPZ_OBSERVATION_DIGEST_BYTES];
	bool enabled;
	atomic_t loss;
	bool drained;
	bool sealed;
};

/* Stable external gate: never recycle for a different capture epoch. */
struct swapz_observation_gate {
	struct swapz_observation_recorder __rcu *active;
	struct swapz_observation_recorder *retained;
	bool used;
};

typedef bool (*swapz_observation_sink)(void *context, const u8 *bytes,
				      size_t length);

/* Initialize fresh storage only; no concurrent initialization or reuse. */
bool swapz_observation_init(struct swapz_observation_recorder *recorder,
			    struct swapz_observation_record *records,
			    size_t capacity, const u8 scope_sha256[32]);
/* Initialize a fresh, externally lifetime-fenced gate before any caller. */
void swapz_observation_gate_init(struct swapz_observation_gate *gate);
/* One-shot publication; requires successful init of fresh recorder/storage. */
bool swapz_observation_publish(struct swapz_observation_gate *gate,
			       struct swapz_observation_recorder *recorder);
/* IDs are monotonically minted run-local integers, never pointer-derived. */
u64 swapz_observation_mint(struct swapz_observation_gate *gate);
bool swapz_observation_append(struct swapz_observation_gate *gate,
			      const struct swapz_observation_record *record);
/*
 * Process context only: disable, unpublish, then synchronize_rcu().
 * No control-path locks required by entrants may be held. A paused reserved
 * writer publishes its unique slot and sets late loss before exiting RCU.
 * Enclosing owner must separately revoke/join gate callers before freeing
 * the gate itself; RCU protects recorder access, not an unentered caller.
 * Stop is idempotent after publication; no stale recorder pointer retained.
 */
bool swapz_observation_stop(struct swapz_observation_gate *gate);
/* Seal/export only after stop returned, serialized with all control calls. */
bool swapz_observation_seal(struct swapz_observation_recorder *recorder);
bool swapz_observation_export(const struct swapz_observation_recorder *recorder,
			      swapz_observation_sink sink, void *context);

#endif
