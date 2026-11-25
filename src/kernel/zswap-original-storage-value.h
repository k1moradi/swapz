/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_ORIGINAL_STORAGE_VALUE_H
#define SWAPZ_ORIGINAL_STORAGE_VALUE_H

#include "zswap-original-storage.h"

#define SWAPZ_SHARED_STORAGE_VALUE_ACTIVE 0U

#ifdef SWAPZ_SHARED_STORAGE_VALUE_TEST
#if !defined(SWAPZ_SHARED_ORIGINAL_TEST) || !defined(SWAPZ_ORIGINAL_STORAGE_TEST)
#error "value storage requires the dormant shared storage adapter"
#endif
#include "zswap-original-decoder-handles.h"

/* One sleepable ordered owner serializes every call, including ordinary
 * authority mutation, pin/put, and callbacks. Caller retains the provider,
 * authority and all context storage through successful close. No reentry.
 * get/put use the frozen R091 value ABI, not a decoder pointer. Successful
 * get transfers one independent record reference; failed get transfers none.
 * put must succeed for a retained exact handle; a violation quarantines
 * the private slot and permanently hard-refuses new typed work/close.
 */
struct swapz_shared_storage_value_ops {
	void *context;
	int (*write)(void *, swapz_u32, const swapz_u8 *, swapz_u32, swapz_u32 *);
	int (*flush)(void *);
	int (*read)(void *, swapz_u32, swapz_u8 *, swapz_u32, swapz_u32 *);
	int (*decoder_get)(void *, swapz_u8, swapz_u8,
			   struct swapz_original_decoder_value_handle *);
	int (*decoder_put)(void *, const struct swapz_original_decoder_value_handle *);
	/* Same synchronous contract as frozen handle_read: acquire a distinct
	 * transient decoder lease, release it exactly once on every acquired
	 * path, and commit output only after successful release. No reentry. */
	int (*decoder_read)(void *, const struct swapz_original_decoder_value_snapshot *,
		swapz_u32, swapz_u8 *, swapz_u32, swapz_u8 *, swapz_u32,
		swapz_u8 *, swapz_u32);
};

struct swapz_shared_storage_value_slot {
	struct swapz_original_decoder_value_handle handle;
	swapz_u8 active;
};

/* Fixed private bridge: the legacy authority's opaque token names a stable
 * slot here, NOT a decoder. A slot cannot be reused while any mapped or
 * retired pinned record owns it. No extra map, heap allocation or copied
 * ownership. The embedded legacy adapter and slots are implementation
 * details; callers must NOT invoke its pointer APIs or modify its state.
 * Last generation is indexed by the frozen provider slot, independently
 * of the smaller authority sidecar. All pins must drain before reset.
 */
struct swapz_shared_storage_value {
	struct swapz_shared_storage shared;
	struct swapz_shared_storage_value_ops ops;
	struct swapz_shared_storage_value_slot slots[SWAPZ_SHARED_ORIGINAL_CAPACITY];
	swapz_u64 last_generation[SWAPZ_ORIGINAL_DECODER_HANDLE_SLOTS];
	swapz_u64 lifecycle_epoch;
	int get_error;
	swapz_u8 faulted;
};

struct swapz_shared_storage_value_snapshot {
	struct swapz_authority_import_spec spec;
	struct swapz_map map;
	struct swapz_original_decoder_value_handle handle;
	swapz_u32 sequence;
};

/* Return the snapshot by value: no writable snapshot span can alias the
 * authority or the compressed output. Error has no valid snapshot and
 * leaves the compressed output unchanged. The handle is a BORROWED value,
 * valid only until the exact pin's final put; never put it independently.
 * Caller builds the frozen decoder snapshot and retains the pin across
 * synchronous decode. No actual decode or authentication is claimed here.
 */
struct swapz_shared_storage_value_result {
	struct swapz_shared_storage_value_snapshot snapshot;
	int error;
};

int swapz_shared_storage_value_init(struct swapz_shared_storage_value *,
	struct swapz_authority *, const struct swapz_shared_storage_value_ops *);
int swapz_shared_storage_value_write(struct swapz_shared_storage_value *,
	const struct swapz_authority_import_spec *, const struct swapz_original_extent_input *);
int swapz_shared_storage_value_reserve(struct swapz_shared_storage_value *,
	const struct swapz_authority_import_spec *, const struct swapz_original_extent_input *,
	swapz_u32 *credit);
int swapz_shared_storage_value_cancel_reserved(struct swapz_shared_storage_value *, swapz_u32);
int swapz_shared_storage_value_commit_reserved(struct swapz_shared_storage_value *, swapz_u32);
int swapz_shared_storage_value_pin(struct swapz_shared_storage_value *, swapz_u32, swapz_u64 *);
int swapz_shared_storage_value_put(struct swapz_shared_storage_value *, swapz_u64);
struct swapz_shared_storage_value_result swapz_shared_storage_value_read_pinned(
	struct swapz_shared_storage_value *, swapz_u64, swapz_u8 *, swapz_u32);
/* All four buffers are disjoint, caller-owned, capacity-byte spans;
 * capacity must equal one page. Caller holds the exact storage pin through
 * this synchronous operation and puts it separately after return. The
 * ordered owner excludes retirement of that pin and callback reentry.
 * The provider acquires/releases its own transient decoder read lease;
 * the borrowed record handle is never independently put. Output is
 * unchanged on failure per the frozen decoder callback contract.
 * Compressed/scratch/verified buffers may change. No source authentication. */
int swapz_shared_storage_value_decode_pinned(struct swapz_shared_storage_value *,
	swapz_u64 pin, swapz_u8 *compressed, swapz_u8 *scratch,
	swapz_u8 *verified, swapz_u8 *output, swapz_u32 capacity);
int swapz_shared_storage_value_relocate(struct swapz_shared_storage_value *, swapz_u64, swapz_u64);
int swapz_shared_storage_value_close(struct swapz_shared_storage_value *);
#endif
#endif
