/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_NATIVE_OBSERVATION_RECORDER_H
#define SWAPZ_NATIVE_OBSERVATION_RECORDER_H

/*
 * Host-test opt-in recorder prototype, NOT a kernel capture interface.
 * Caller owns preallocated contiguous storage and external entrant lifetime.
 * No allocation, formatting, hashing, I/O, waiting or callbacks in append.
 * A bounded atomic reservation assigns a unique slot before its private copy.
 * Exhausted retries or capacity lose evidence, never block product progress.
 */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdatomic.h>

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
#define SWAPZ_OBS_FIELD64(name) uint64_t name;
	SWAPZ_OBSERVATION_U64_FIELDS(SWAPZ_OBS_FIELD64)
#undef SWAPZ_OBS_FIELD64
#define SWAPZ_OBS_FIELD32(name) uint32_t name;
	SWAPZ_OBSERVATION_U32_FIELDS(SWAPZ_OBS_FIELD32)
#undef SWAPZ_OBS_FIELD32
#define SWAPZ_OBS_DIGEST(name) uint8_t name[SWAPZ_OBSERVATION_DIGEST_BYTES];
	SWAPZ_OBSERVATION_DIGEST_FIELDS(SWAPZ_OBS_DIGEST)
#undef SWAPZ_OBS_DIGEST
};

struct swapz_observation_recorder {
	struct swapz_observation_record *records;
	size_t capacity;
	atomic_uint count;
	atomic_uint token_high;
	unsigned token_limit;
	uint8_t scope_sha256[SWAPZ_OBSERVATION_DIGEST_BYTES];
	atomic_bool enabled;
	atomic_uint loss;
	bool sealed;
};

typedef bool (*swapz_observation_sink)(void *context, const uint8_t *bytes,
				      size_t length);

/* Init before publishing to producers; no concurrent reinit or storage reuse. */
bool swapz_observation_init(struct swapz_observation_recorder *recorder,
			    struct swapz_observation_record *records,
			    size_t capacity, const uint8_t scope_sha256[32]);
/* Tokens are monotonically minted run-local integers, never pointer-derived. */
uint64_t swapz_observation_mint(struct swapz_observation_recorder *recorder);
bool swapz_observation_append(struct swapz_observation_recorder *recorder,
			      const struct swapz_observation_record *record);
/*
 * External producer revoke/join MUST precede stop/seal, and outlive export.
 * Stop prevents new entries; a reserved append completes its private copy and
 * marks observed late stop as loss. Seal checks every reserved sequence only
 * after the external join; it is not safe to inspect concurrently written slots.
 * Seal does not establish external quiescence and must not be used as one.
 * Caller retains recorder and backing array until all entrants have exited.
 */
void swapz_observation_stop(struct swapz_observation_recorder *recorder);
bool swapz_observation_seal(struct swapz_observation_recorder *recorder);
/* Only sealed immutable records; export loss flags, never hide failed sink. */
bool swapz_observation_export(const struct swapz_observation_recorder *recorder,
			      swapz_observation_sink sink, void *context);

#endif
