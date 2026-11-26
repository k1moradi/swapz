/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_ORIGINAL_DECODER_SHARED_H
#define SWAPZ_ORIGINAL_DECODER_SHARED_H

#include "zswap-original-decoder-handles.h"

#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
#include <stdatomic.h>
#else
#include <linux/atomic.h>
#endif

#define SWAPZ_ORIGINAL_DECODER_SHARED_ACTIVE 0U

#ifdef SWAPZ_ORIGINAL_DECODER_SHARED_TEST
#ifndef SWAPZ_ORIGINAL_STORAGE_TEST
#error "shared decoder requires the frozen value identity"
#endif

/* Independent, trusted storage authority. No decoder-owned record table.
 * reserve_epoch must issue a nonzero, never-reused epoch from an authority
 * surviving consumer reload, or refuse. A linked-image counter alone is
 * insufficient. For native composition the exact freshly opened built-in
 * broker session is the epoch; consume it once even on failed init, and
 * close that broker session before another provider lifetime. Reopening
 * against an existing session after consumer reload is forbidden. snapshot resolves an EXISTING caller-retained storage pin,
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

#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
typedef atomic_uint swapz_shared_decoder_count;
#else
typedef atomic_t swapz_shared_decoder_count;
#endif

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
	swapz_shared_decoder_count active_reads;
	swapz_u8 state;
};

/* Exclusive zeroed owner and trusted, retained authority; no allocation.
 * The consumer must link both original codec symbols for module lifetime.
 * Output epoch unchanged on failure. Owner is single-lifetime; after
 * successful finish, no calls until a fresh zeroed owner is initialized.
 * A failed initialization after epoch reservation burns that identity.
 * Failed init never permits entry; quarantine must remain allocated.
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
 * The read count includes the final unlocked output copy, but not a caller
 * paused before the lock or after its final decrement. A busy finish leaves
 * closing state intact. Invariant/release failures
 * quarantine the owner; never free or reuse it on failed finish.
 */
int swapz_original_decoder_shared_begin_close(
	struct swapz_original_decoder_shared *, swapz_u64 epoch);
int swapz_original_decoder_shared_finish_close(
	struct swapz_original_decoder_shared *, swapz_u64 epoch);

/* Stable external admission gate, not a second record authority. The gate
 * storage and its lock outlive every possible entrant, including paused
 * callers not yet inside the gate. Lifecycle calls are externally serialized;
 * no gate lock is held over provider callbacks or page copying. Initialize
 * once, not per provider lifetime. Native users must obtain a fresh retained
 * cap from built-in broker owner_open for every bind, and never rebind that
 * session after module reload; the gate high-water mark is not a substitute
 * for the built-in authority. Host adapter models that external capability.
 */
struct swapz_original_decoder_shared_gate {
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	pthread_mutex_t lock;
#else
	spinlock_t lock;
#endif
	struct swapz_original_decoder_shared *owner;
	struct swapz_original_decoder_shared_ops authority;
	swapz_u64 last_session;
	swapz_shared_decoder_count entrants;
	swapz_u8 state;
};

int swapz_original_decoder_shared_gate_init(
	struct swapz_original_decoder_shared_gate *gate);
/* session and broker_epoch must be the fresh exact retained owner cap pair.
 * The supplied reserve_epoch callback consumes that same identity once;
 * different/repeated identity fails closed. Gate burns the session before
 * invoking provider init. Owner/context storage retained until gate finish.
 */
int swapz_original_decoder_shared_gate_open(
	struct swapz_original_decoder_shared_gate *gate,
	struct swapz_original_decoder_shared *owner,
	const struct swapz_original_decoder_shared_ops *authority,
	swapz_u32 capacity, swapz_u64 session, swapz_u64 broker_epoch);
/* Gate read never returns a naked provider pointer. The caller retains the
 * exact storage pin and gate through return. Even a delayed old caller is
 * rejected by session before touching a new provider. */
int swapz_original_decoder_shared_gate_read(
	struct swapz_original_decoder_shared_gate *gate, swapz_u64 session,
	swapz_u64 pin, const struct swapz_original_decoder_value_handle *expected,
	swapz_u32 ceiling, swapz_u8 *scratch, swapz_u32 scratch_capacity,
	swapz_u8 *verified, swapz_u32 verified_capacity,
	swapz_u8 *output, swapz_u32 output_capacity);
int swapz_original_decoder_shared_gate_begin_close(
	struct swapz_original_decoder_shared_gate *gate, swapz_u64 session);
/* Caller revokes route, drains storage pins and holds gate alive. Busy
 * preserves the owner; successful finish permits freeing owner/context, not
 * freeing the gate until all pre-gate callers are externally quiesced. */
int swapz_original_decoder_shared_gate_finish_close(
	struct swapz_original_decoder_shared_gate *gate, swapz_u64 session);
#endif
#endif
