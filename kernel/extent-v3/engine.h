/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_V3_EXTENT_ENGINE_H
#define SWAPZ_V3_EXTENT_ENGINE_H
#include "authority.h"
#define SV3_BULK_BLOCKS 64U

/* Bit-exact 4KiB zero-page test; no false-positive compressed content. */
int sv3_page_is_zero(const sv3_u8 *page);

/*
 * Experimental synchronous lower-I/O boundary for an ORDERED worker.
 * It is NOT a Device Mapper callback yet. All memory is preallocated by
 * the caller. Every write callback MUST return only after full lower I/O
 * completion, never after mere submission.
 */
struct sv3_io {
	void *opaque;
	int (*write_extent)(void *opaque, sv3_u32 start_block, sv3_u8 blocks,
			    const sv3_u8 *bytes, sv3_u8 *completed_blocks);
	/* Optional single synchronous lower write for a 1..64-block
	 * concatenation of individually valid SWZ3 extents and raw blocks.
	 * The authority publishes NONE before this callback has returned
	 * full confirmed completion. See sv3_batch_pause()/resume(). */
	int (*write_run)(void *opaque, sv3_u32 start_block, sv3_u16 blocks,
			 const sv3_u8 *bytes, sv3_u16 *completed_blocks);
	int (*read_blocks)(void *opaque, sv3_u32 start_block, sv3_u8 blocks,
			   sv3_u8 *destination);
};

struct sv3_compressed_page {
	sv3_u32 logical_page;
	const sv3_u8 *payload;
	sv3_u16 length;
	/* True for an uncompressed 4096-byte page. Raw entries follow all
	 * compressed entries in a mixed physical write window. */
	sv3_u8 raw;
};

struct sv3_engine {
	struct sv3_authority *authority;
	struct sv3_io io;
	sv3_u8 *write_scratch; /* at least 16384 bytes */
	sv3_u8 *read_scratch;  /* at least 16384 bytes */
	/*
	 * Optional, preallocated batch path. 64 lower blocks = 256KiB.
	 * When absent (or write verification enabled), use the original
	 * exact per-extent synchronous implementation unchanged.
	 */
	sv3_u8 *bulk_scratch; /* at least 64*4096 bytes */
	struct sv3_tx *bulk_txs; /* at least SV3_MAX_RECORDS transactions */
	sv3_u16 bulk_offsets[SV3_MAX_RECORDS];
	sv3_u8 bulk_takes[SV3_MAX_RECORDS];
	/* Snapshot publication is type-specific: compressed or raw CRC. */
	sv3_u8 bulk_raw[SV3_MAX_RECORDS];
	/* 0=per-extent; 1=adjacent only, no added bytes (default);
	 * 2=also coalesce aligned padding gaps, count extra write bytes. */
	sv3_u8 bulk_enabled;
	sv3_u32 bulk_writes;
	sv3_u32 bulk_extents;
	sv3_u32 bulk_padding_blocks;
	/* Successful fully published runs by media composition, not a claim
	 * about block-layer merged/split requests. */
	sv3_u32 bulk_mixed_runs;
	sv3_u32 bulk_raw_only_runs;
	sv3_u32 bulk_raw_entries;
	/* Context-owned scratch, never a >1KiB frame on the kernel worker stack. */
	struct sv3_tx pending;
	sv3_u32 logical_scratch[SV3_MAX_RECORDS];
	sv3_u8 plan_classes[SV3_MAX_RECORDS];
	sv3_u8 plan_takes[SV3_MAX_RECORDS];
	/*
	 * Optional diagnostic: read back each whole completed extent and
	 * byte-compare it BEFORE publishing mappings. Expensive; OFF by default.
	 * This tests immediate write/read consistency, not power-loss durability.
	 */
	int verify_after_write;
	/*
	 * 0 = byte-minimal planner; 1..3 = physical 4KiB read blocks per
	 * compressed record, including uncached metadata block zero.
	 * This is a planning policy, not a hardware latency guarantee.
	 */
	sv3_u8 max_read_blocks_per_record;
	sv3_u32 write_verify_read_blocks;
	sv3_u32 submitted_blocks;
	sv3_u32 completed_blocks;
	sv3_u32 physical_read_blocks;
	/* Successful targeted compressed reads: header block zero and additional
	 * payload callbacks/blocks. Diagnostics do not own I/O or mappings. */
	sv3_u32 read_metadata_requests;
	sv3_u32 read_payload_requests;
	sv3_u32 read_payload_blocks;
	/* One-extent read cache in preallocated read_scratch. On a bounded
	 * 8KiB fetch it may contain both blocks; otherwise only block zero.
	 * The serialized caller invalidates before any mutation. */
	sv3_u32 read_cached_start_block;
	sv3_u8 read_cached_extent_blocks;
	sv3_u8 read_cache_valid;
	sv3_u8 read_cached_full;
	sv3_u32 read_metadata_cache_hits;
	/* Lower callbacks, not block-queue requests; byte deltas are independent. */
	sv3_u32 read_full_extent_requests;
	sv3_u32 read_full_extent_cache_hits;
	/* Cold two-block records proven wholly inside metadata block zero;
	 * avoiding a speculative second block does not skip CRC validation. */
	sv3_u32 read_two_block_skips;
};

/* CPU-only finite-window selection, 4/8/16KiB; output classes 1/2/4. */
int sv3_engine_plan(const struct sv3_compressed_page *pages, sv3_u8 count,
		    sv3_u8 *classes, sv3_u8 *records_per_extent,
		    sv3_u8 *extent_count);
int sv3_engine_plan_bounded(const struct sv3_compressed_page *pages,
			    sv3_u8 count, sv3_u8 max_read_blocks,
			    sv3_u8 *classes, sv3_u8 *records_per_extent,
			    sv3_u8 *extent_count);
/*
 * Partial failure returns a nonzero status and sets *committed_pages to
 * exactly the prefix whose complete extents became authoritative. It NEVER
 * reports atomic success for an uncommitted full logical window.
 */
int sv3_engine_write_window(struct sv3_engine *engine,
			    const struct sv3_compressed_page *pages,
			    sv3_u8 count, sv3_u8 *committed_pages);
/*
 * Optional batched physically adjacent extent/raw writer. Stages multiple
 * logically independent records but publishes no mapping until ONE
 * confirmed lower write completes. Respects 1MiB segment boundary,
 * a 256KiB memory/I/O cap, and the prior committed-page-prefix ABI.
 */
int sv3_engine_write_window_batched(struct sv3_engine *engine,
				   const struct sv3_compressed_page *pages,
				   sv3_u8 count, sv3_u8 *committed_pages);
/* Caller-owned and serialized: invalidate before writes, discards and barriers.
 * Never invalidate from a concurrent preparation producer. */
void sv3_engine_invalidate_read_cache(struct sv3_engine *engine);
/* Targeted read: metadata 4KiB plus only the required payload 4KiB blocks. */
int sv3_engine_read_page(struct sv3_engine *engine, sv3_u32 logical_page,
			 sv3_u8 *payload, sv3_u16 payload_capacity,
			 sv3_u16 *payload_length);

#endif
