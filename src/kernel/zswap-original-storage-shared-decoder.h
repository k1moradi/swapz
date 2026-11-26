/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_ORIGINAL_STORAGE_SHARED_DECODER_H
#define SWAPZ_ORIGINAL_STORAGE_SHARED_DECODER_H

#include "zswap-original-storage.h"
#include "zswap-original-decoder-shared.h"

#define SWAPZ_SHARED_STORAGE_DECODER_ACTIVE 0U

#ifdef SWAPZ_SHARED_STORAGE_DECODER_TEST
#if !defined(SWAPZ_SHARED_ORIGINAL_TEST) || !defined(SWAPZ_ORIGINAL_DECODER_SHARED_TEST)
#error "shared storage decoder requires both frozen implementations"
#endif

struct swapz_shared_storage_decoder_ops {
	void *context;
	int (*write)(void *, swapz_u32, const swapz_u8 *, swapz_u32, swapz_u32 *);
	int (*flush)(void *);
	int (*read)(void *, swapz_u32, swapz_u8 *, swapz_u32, swapz_u32 *);
	int (*reserve_epoch)(void *, swapz_u64 *);
	/* Retained external gate and exact fresh broker cap pair. Caller
	 * initializes the gate once and consumes the cap in reserve_epoch.
	 * Host fixtures explicitly model that external broker boundary. */
	struct swapz_original_decoder_shared_gate *gate;
	swapz_u64 session;
	swapz_u64 broker_epoch;
};

/* One externally retained, sleepable ordered owner serializes ALL access,
 * including authority mutations, pin/put, callbacks and close. No reentry,
 * no independent provider entry, no resetting authority while attached.
 * Retain the external gate before entry, through return and exact pin put;
 * revoke/join all pre-lock entrants before close or freeing the gate.
 * A pin remains held through the decoder's final output copy.
 * Fresh zeroed storage instance only at init; never reset the gate on reopen.
 * The legacy decoder field carries a non-owning attachment marker, NOT
 * a provider lease. The actual authority sidecar is the only record table.
 * Gate lifetime and the fresh exact broker cap are external to storage.
 * A failed bind burns the session; caller closes that exact cap before
 * reopening with a new identity, and quarantines any uncertain unwind.
 * The provider lifetime covers all current and retired storage records.
 * Use embedded storage only for frozen write/reserve/commit/cancel/relocate
 * under that owner; never use its init/close or call provider directly.
 * All caller buffers/context must be backed, disjoint and stable.
 */
struct swapz_shared_storage_decoder {
	struct swapz_shared_storage storage;
	struct swapz_original_decoder_shared provider;
	struct swapz_shared_storage_decoder_ops ops;
	swapz_u64 epoch;
	swapz_u64 scoped_pin;
	const swapz_u8 *scoped_bytes;
	swapz_u8 state;
};

int swapz_shared_storage_decoder_init(struct swapz_shared_storage_decoder *,
	struct swapz_authority *, const struct swapz_shared_storage_decoder_ops *);

/* Existing retained authority pin, not a new pin or a caller snapshot.
 * Caller supplies the captured lifetime epoch, never a refreshed epoch for
 * an old pin. Pins are numeric and may restart after authority reinit.
 * Exactly one lower read, followed by actual gate admission. Four
 * disjoint page buffers (also disjoint from the external gate); output unchanged
 * on error. Caller puts the exact pin separately, only after return. */
int swapz_shared_storage_decoder_read(struct swapz_shared_storage_decoder *,
	swapz_u64 epoch, swapz_u64 pin, swapz_u8 *compressed, swapz_u8 *scratch,
	swapz_u8 *verified, swapz_u8 *output, swapz_u32 capacity);

/* Busy leaves attachment and provider open; after successful detach,
 * provider failure quarantines the instance, never reset/free on error. */
int swapz_shared_storage_decoder_close(struct swapz_shared_storage_decoder *);
#endif
#endif
