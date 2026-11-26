/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_ORIGINAL_DECODER_SHARED_H
#define SWAPZ_ORIGINAL_DECODER_SHARED_H

#include "zswap-original-decoder-handles.h"

#define SWAPZ_ORIGINAL_DECODER_SHARED_ACTIVE 0U

#ifdef SWAPZ_ORIGINAL_DECODER_SHARED_TEST
#ifndef SWAPZ_ORIGINAL_STORAGE_TEST
#error "shared decoder requires the frozen value identity"
#endif

/* Independent, trusted storage authority. No decoder-owned record table.
 * reserve_epoch must issue a nonzero, never-reused epoch from an authority
 * surviving consumer reload, or refuse. A linked-image counter alone is
 * insufficient. snapshot resolves an EXISTING caller-retained storage pin,
 * not a new pin or caller-supplied record. The authority must issue nonzero
 * nonwrapping record generations and never recycle a pinned record; the
 * descriptor and bytes remain
 * immutable until the caller releases that pin after read returns.
 * Both callbacks are sleepable, outside decoder locks, and must not reenter
 * teardown. Neither callback authenticates a live zswap source by itself.
 */
struct swapz_original_decoder_shared_ops {
	void *context;
	int (*reserve_epoch)(void *, swapz_u64 *);
	int (*snapshot)(void *, swapz_u64,
		struct swapz_original_decoder_value_snapshot *);
};

struct swapz_original_decoder_shared {
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	pthread_mutex_t lock;
#else
	spinlock_t lock;
#endif
	struct swapz_zswap_import_decoder_owner providers[2];
	struct swapz_zswap_import_decoder_lease retained[2];
	struct swapz_original_decoder_shared_ops ops;
	swapz_u64 epoch;
	swapz_u32 capacity;
	unsigned int active_reads;
	swapz_u8 state;
};

/* Exclusive zeroed owner and trusted, retained authority; no allocation.
 * The consumer must link both original codec symbols for module lifetime.
 * Output epoch unchanged on failure. Owner is single-lifetime; after
 * successful finish, no calls until a fresh zeroed owner is initialized.
 */
int swapz_original_decoder_shared_init(
	struct swapz_original_decoder_shared *,
	const struct swapz_original_decoder_shared_ops *,
	swapz_u32 capacity, swapz_u64 *epoch);

/* Expected identity is borrowed, not a record ref. Caller holds the exact
 * storage pin and exclusively owns disjoint scratch/verified/output pages
 * through return. External admission keeps owner/context alive through
 * return, including entrants paused before the owner lock. All callback
 * context, metadata and byte ranges must be separate from writable buffers.
 * No allocation or module_get per record/read; no output on error.
 */
int swapz_original_decoder_shared_read(
	struct swapz_original_decoder_shared *, swapz_u64 pin,
	const struct swapz_original_decoder_value_handle *,
	swapz_u32 ceiling, swapz_u8 *scratch, swapz_u32 scratch_capacity,
	swapz_u8 *verified, swapz_u32 verified_capacity,
	swapz_u8 *output, swapz_u32 output_capacity);

/* Nonblocking admission fence. Existing admitted readers may finish.
 * Caller must revoke external entry and join ALL entrants, retire/drain
 * storage pins and ensure no future caller can enter BEFORE finish.
 * A busy finish leaves closing state intact. Invariant/release failures
 * quarantine the owner; never free or reuse it on failed finish.
 */
int swapz_original_decoder_shared_begin_close(
	struct swapz_original_decoder_shared *, swapz_u64 epoch);
int swapz_original_decoder_shared_finish_close(
	struct swapz_original_decoder_shared *, swapz_u64 epoch);
#endif
#endif
