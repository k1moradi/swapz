/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_ORIGINAL_STORAGE_H
#define SWAPZ_ORIGINAL_STORAGE_H

#include "zswap-original-extent.h"
#include "authority.h"

#define SWAPZ_ORIGINAL_STORAGE_ACTIVE 0U

#ifdef SWAPZ_ORIGINAL_STORAGE_TEST
#if !defined(SWAPZ_ORIGINAL_EXTENT_TEST) || \
    !defined(SWAPZ_ROUND067_IMPORT_DISK_PAYLOAD_TEST)
#error "original storage requires the isolated extent and real import allocator"
#endif

/* All calls are serialized by ONE sleepable ordered owner, including put
 * and close. Callbacks must not reenter this owner or mutate its state.
 * Caller owns storage, authority and callback context until successful close.
 * Init only on fresh storage or after successful close, with disjoint
 * authority arrays. All external input/output spans must be genuinely
 * backed, disjoint from storage and authority, and stable during calls.
 * This is a conservative dedicated candidate, NOT a live DM route. The
 * authority must be exclusive, append-only and have no ordinary map traffic,
 * rotating GC, sequence index or segment-accounting sidecars.
 *
 * A future real adapter must return definitive lower completion (including
 * error/short count) from write/read, and definitive persistence from flush.
 * No synthetic completion is generated here; test callbacks are RAM only.
 * All start blocks are DATA relative (adapter must protect physical page 0).
 * Decoder get returns an independently retained codec/version lease or NULL;
 * put releases exactly that lease. It must not borrow the source pool tfm.
 */
struct swapz_original_storage_ops {
	void *context;
	int (*write)(void *, swapz_u32, const swapz_u8 *, swapz_u32,
		     swapz_u32 *);
	int (*flush)(void *);
	int (*read)(void *, swapz_u32, swapz_u8 *, swapz_u32, swapz_u32 *);
	void *(*decoder_get)(void *, swapz_u8, swapz_u8);
	void (*decoder_put)(void *, void *);
};

struct swapz_original_storage_pin {
	struct swapz_import_disk_view view;
	swapz_u64 id;
};

/* Fixed contiguous bounded storage; no allocation or added ordinary map
 * bytes. The actual dormant import pool is the ONLY typed mapping owner.
 * Decoder references are attached to its exact record slots, including
 * retired pinned records; pins name immutable snapshots, never current map.
 */
struct swapz_original_storage {
	struct swapz_import_disk_pool disk;
	struct swapz_original_storage_ops ops;
	void *decoder[SWAPZ_IMPORT_DISK_CAPACITY];
	struct swapz_original_storage_pin pins[SWAPZ_IMPORT_DISK_CAPACITY];
	struct swapz_tx transaction;
	struct swapz_original_extent extent;
	struct swapz_original_extent_record record;
	swapz_u64 next_pin;
	swapz_u8 faulted;
	swapz_u8 image[SWAPZ_BLOCK_BYTES];
	swapz_u8 read_image[SWAPZ_BLOCK_BYTES];
	swapz_u8 gc_copy[SWAPZ_BLOCK_BYTES];
};

int swapz_original_storage_init(struct swapz_original_storage *,
	struct swapz_authority *, const struct swapz_original_storage_ops *);
/* Sealed, caller-authenticated bytes and source spec remain immutable through
 * synchronous return. This API cannot establish authentication; caller
 * retains its original failure/completion owner. No upper ACK callback.
 * Generation must equal the real ordinary allocator's next generation.
 * Only M3568 is admitted here; experimental packing/M4095 are not routed.
 * Ticket output is unchanged on failure. */
int swapz_original_storage_write(struct swapz_original_storage *,
	const struct swapz_authority_import_spec *,
	const struct swapz_original_extent_input *, swapz_u64 *ticket);
int swapz_original_storage_pin(struct swapz_original_storage *,
	swapz_u64 ticket, swapz_u64 *pin);
/* Returns exact compressed bytes only, no recompression/decoded page claim.
 * A future typed read adapter must decode using the independently retained
 * lease and verify the original SHA. Output unchanged on error. */
int swapz_original_storage_read(struct swapz_original_storage *,
	swapz_u64 pin, swapz_u8 *output, swapz_u32 capacity);
int swapz_original_storage_put(struct swapz_original_storage *, swapz_u64 pin);
/* Byte-exact COW relocation with strictly increasing GC epoch. Caller keeps
 * its old pin; temporary relocation uses that same immutable snapshot.
 * Actual rotating GC/ordinary map publication are NOT supported. */
int swapz_original_storage_relocate(struct swapz_original_storage *,
	swapz_u64 pin, swapz_u64 next_epoch, swapz_u64 *ticket);
int swapz_original_storage_retire(struct swapz_original_storage *,
	swapz_u64 ticket);
int swapz_original_storage_close(struct swapz_original_storage *);

#ifdef SWAPZ_SHARED_ORIGINAL_TEST
/* Independent opt-in shared adapter; the legacy isolated pool is not
 * instantiated. Caller owns disjoint backing arrays and all buffers,
 * serialized by the same ordered owner. No live DM route/early TRIM.
 * Before activation the real DM caller must invalidate caches and check
 * the retained segment pins on all external discard/reclaim paths. */
struct swapz_shared_storage {
	struct swapz_authority *authority;
	struct swapz_shared_original_owner owner;
	struct swapz_original_storage_ops ops;
	struct swapz_tx transaction;
	struct swapz_original_extent extent;
	struct swapz_original_extent_record record;
	swapz_u8 image[SWAPZ_BLOCK_BYTES];
	swapz_u8 read_image[SWAPZ_BLOCK_BYTES];
	swapz_u8 gc_copy[SWAPZ_BLOCK_BYTES];
};
int swapz_shared_storage_init(struct swapz_shared_storage *,
	struct swapz_authority *, const struct swapz_original_storage_ops *);
int swapz_shared_storage_write(struct swapz_shared_storage *,
	const struct swapz_authority_import_spec *, const struct swapz_original_extent_input *);
int swapz_shared_storage_read(struct swapz_shared_storage *, swapz_u64,
	swapz_u8 *, swapz_u32);
int swapz_shared_storage_relocate(struct swapz_shared_storage *, swapz_u64, swapz_u64);
int swapz_shared_storage_close(struct swapz_shared_storage *);
#endif

#endif
#endif
