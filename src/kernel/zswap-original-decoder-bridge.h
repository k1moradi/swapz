/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_ORIGINAL_DECODER_BRIDGE_H
#define SWAPZ_ORIGINAL_DECODER_BRIDGE_H

#include "zswap-original-decode.h"

/* Dormant source-linked storage callback adapter, never a source credential.
 * Frozen storage callbacks carry only a void * for an independent decoder
 * reference. To reject ABA stale tokens without changing that frozen API,
 * each address is issued at most ONCE per bridge lifetime. Exhaustion fails
 * closed; a future production ABI needs a generation-bearing handle.
 * No pool tfm, memory allocation, per-page module_get or live DM binding.
 */
#define SWAPZ_ORIGINAL_DECODER_BRIDGE_ACTIVE 0U
#define SWAPZ_ORIGINAL_DECODER_BRIDGE_TOKENS 64U

#ifdef SWAPZ_ORIGINAL_STORAGE_TEST
struct swapz_original_storage_ops;

struct swapz_original_decoder_bridge_token {
	struct swapz_zswap_import_decoder_lease lease;
	swapz_u8 issued;
	swapz_u8 active;
};

struct swapz_original_decoder_bridge {
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	pthread_mutex_t lock;
#else
	spinlock_t lock;
#endif
	struct swapz_zswap_import_decoder_owner owners[2];
	struct swapz_original_decoder_bridge_token tokens[
		SWAPZ_ORIGINAL_DECODER_BRIDGE_TOKENS];
	void *lower_context;
	int (*lower_write)(void *, swapz_u32, const swapz_u8 *, swapz_u32,
			   swapz_u32 *);
	int (*lower_read)(void *, swapz_u32, swapz_u8 *, swapz_u32,
			  swapz_u32 *);
	int (*lower_flush)(void *);
	unsigned int issued_tokens;
	unsigned int active_tokens;
	unsigned int active_reads;
	swapz_u8 closing;
	swapz_u8 faulted;
};

/* Caller owns a stable immutable, externally authenticated typed sidecar
 * and separately pinned, exact compressed bytes throughout read. The opaque
 * record_token comes from decoder_get for that same storage record; it is
 * never inferred from the payload. Bridge cannot prove selected-DM source,
 * epoch, durable publication or lower completion and does not claim to.
 */
struct swapz_original_decoder_snapshot {
	struct swapz_original_decode_record record;
	const swapz_u8 *compressed_bytes;
	swapz_u32 compressed_capacity;
	const void *record_token;
};

/* Fresh zeroed bridge; caller supplies REAL lower callbacks. Output ops are
 * valid until successful close. The ordered storage owner must serialize
 * its callbacks and stop new calls before releasing the bridge. */
int swapz_original_decoder_bridge_init(
	struct swapz_original_decoder_bridge *bridge,
	const struct swapz_original_storage_ops *lower,
	struct swapz_original_storage_ops *wrapped);

/* Synchronous exclusive reader: two caller-owned nonoverlapping 4096-byte
 * working pages (scratch, verified) and one final output. Output is untouched
 * on every error, including failed lease release; scratch may change. No hot
 * read allocations. The bridge forbids closing with its own live reader.
 * No token can be reused even after put, preventing pointer ABA replay.
 */
int swapz_original_decoder_bridge_read(
	struct swapz_original_decoder_bridge *bridge,
	const struct swapz_original_decoder_snapshot *snapshot,
	swapz_u32 ceiling, swapz_u8 *scratch, swapz_u32 scratch_capacity,
	swapz_u8 *verified, swapz_u32 verified_capacity,
	swapz_u8 *output, swapz_u32 output_capacity);

/* Returns EBUSY without changing state if ANY record/read ref remains.
 * Caller must quiesce all get attempts before final destruction. Host-only
 * lock/condition cleanup is done here after success (no further calls).
 * Never invoke close from inside the current reader or lower callback.
 */
int swapz_original_decoder_bridge_close(struct swapz_original_decoder_bridge *);
#endif /* SWAPZ_ORIGINAL_STORAGE_TEST */
#endif /* SWAPZ_ORIGINAL_DECODER_BRIDGE_H */
