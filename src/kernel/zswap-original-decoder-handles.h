/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_ORIGINAL_DECODER_HANDLES_H
#define SWAPZ_ORIGINAL_DECODER_HANDLES_H

#include "zswap-original-decode.h"

/* New value-only candidate; NOT the frozen storage void * callback ABI.
 * Neither the handle nor the content bytes are source authentication.
 * A future admitted caller must retain module provider and source ownership.
 */
#define SWAPZ_ORIGINAL_DECODER_HANDLES_ACTIVE 0U
#define SWAPZ_ORIGINAL_DECODER_HANDLE_SLOTS 64U

#ifdef SWAPZ_ORIGINAL_STORAGE_TEST
struct swapz_original_decoder_value_handle {
	swapz_u64 lifecycle_epoch;
	swapz_u64 generation;
	swapz_u32 slot_index;
	swapz_u8 codec;
	swapz_u8 version;
};

struct swapz_original_decoder_value_slot {
	struct swapz_zswap_import_decoder_lease record_lease;
	swapz_u64 last_generation;
	swapz_u8 active;
};

struct swapz_original_decoder_handle_owner {
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	pthread_mutex_t lock;
#else
	spinlock_t lock;
#endif
	struct swapz_zswap_import_decoder_owner decoders[2];
	struct swapz_original_decoder_value_slot slots[
		SWAPZ_ORIGINAL_DECODER_HANDLE_SLOTS];
	swapz_u64 lifecycle_epoch;
	unsigned int active_records;
	unsigned int active_reads;
	swapz_u8 closing;
	swapz_u8 faulted;
};

struct swapz_original_decoder_value_snapshot {
	struct swapz_original_decoder_value_handle handle;
	struct swapz_original_decode_record record;
	const swapz_u8 *compressed_bytes;
	swapz_u32 compressed_capacity;
};

/* The owner must be zeroed and exclusively uninitialized before init.
 * Epochs are monotonically allocated per linked binary and never wrap.
 * Reloadable module identity across unload/reload is NOT established.
 * All entry points require owner storage to remain alive and stable.
 */
int swapz_original_decoder_handles_init(
	struct swapz_original_decoder_handle_owner *owner);

/* Successful get retains one original-codec owner reference per record.
 * Slot addresses may be reused, but slot generations NEVER wrap or repeat.
 * Handle output stays unmodified on all failures, including exhaustion. */
int swapz_original_decoder_handle_get(
	struct swapz_original_decoder_handle_owner *owner,
	swapz_u8 codec, swapz_u8 version,
	struct swapz_original_decoder_value_handle *handle);

/* A stale, duplicate, foreign-owner or mismatched handle fails -ESTALE.
 * A read already holding its independent lease outlives this put.
 * The immutable handle value itself is deliberately never cleared. */
int swapz_original_decoder_handle_put(
	struct swapz_original_decoder_handle_owner *owner,
	const struct swapz_original_decoder_value_handle *handle);

/* Caller holds a separately authenticated immutable record and exact bytes
 * for the entire synchronous read. Working pages and output are disjoint,
 * caller-owned 4096-byte spans. Output changes only after exact original
 * decode, CRC/SHA verification and successful read-lease release.
 * No hot-path allocation or per-page module_get is performed.
 */
int swapz_original_decoder_handle_read(
	struct swapz_original_decoder_handle_owner *owner,
	const struct swapz_original_decoder_value_snapshot *snapshot,
	swapz_u32 ceiling, swapz_u8 *scratch, swapz_u32 scratch_capacity,
	swapz_u8 *verified, swapz_u32 verified_capacity,
	swapz_u8 *output, swapz_u32 output_capacity);

/* Caller quiesces external entrants BEFORE a successful close. Never close
 * from its own reader; an active reader or record returns -EBUSY without
 * waiting, blocking teardown races and pool-owner use-after-free. */
int swapz_original_decoder_handles_close(
	struct swapz_original_decoder_handle_owner *owner);
#endif
#endif
