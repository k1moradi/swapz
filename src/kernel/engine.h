/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_EXTENT_ENGINE_H
#define SWAPZ_EXTENT_ENGINE_H
#include "authority.h"
#define SWAPZ_BULK_BLOCKS 64U
#define SWAPZ_READ_METADATA_CACHE_ENTRIES 64

/* Bit-exact 4KiB zero-page test; no false-positive compressed content. */
int swapz_page_is_zero(const swapz_u8 *page);

/*
 * Experimental synchronous lower-I/O boundary for an ORDERED worker.
 * It is NOT a Device Mapper callback yet. All memory is preallocated by
 * the caller. Every write callback MUST return only after full lower I/O
 * completion, never after mere submission.
 */
struct swapz_io {
	void *opaque;
	int (*write_extent)(void *opaque, swapz_u32 start_block, swapz_u8 blocks,
			    const swapz_u8 *bytes, swapz_u8 *completed_blocks);
	/* Optional single synchronous lower write for a 1..64-block
	 * concatenation of individually valid SWZ3 extents and raw blocks.
	 * The authority publishes NONE before this callback has returned
	 * full confirmed completion. See swapz_batch_pause()/resume(). */
	int (*write_run)(void *opaque, swapz_u32 start_block, swapz_u16 blocks,
			 const swapz_u8 *bytes, swapz_u16 *completed_blocks);
	int (*read_blocks)(void *opaque, swapz_u32 start_block, swapz_u8 blocks,
			   swapz_u8 *destination);
};

struct swapz_compressed_page {
	swapz_u32 logical_page;
	const swapz_u8 *payload;
	swapz_u16 length;
	/* True for an uncompressed 4096-byte page. Raw entries follow all
	 * compressed entries in a mixed physical write window. */
	swapz_u8 raw;
};

struct swapz_engine {
	struct swapz_authority *authority;
	struct swapz_io io;
	swapz_u8 *write_scratch; /* at least 16384 bytes */
	swapz_u8 *read_scratch;  /* at least 16384 bytes */
	/*
	 * Optional, preallocated batch path. 64 lower blocks = 256KiB.
	 * When absent (or write verification enabled), use the original
	 * exact per-extent synchronous implementation unchanged.
	 */
	swapz_u8 *bulk_scratch; /* at least 64*4096 bytes */
	struct swapz_tx *bulk_txs; /* at least SWAPZ_MAX_RECORDS transactions */
	swapz_u16 bulk_offsets[SWAPZ_MAX_RECORDS];
	swapz_u8 bulk_takes[SWAPZ_MAX_RECORDS];
	/* Snapshot publication is type-specific: compressed or raw CRC. */
	swapz_u8 bulk_raw[SWAPZ_MAX_RECORDS];
	/* 0=per-extent; 1=adjacent only, no added bytes (default);
	 * 2=also coalesce aligned padding gaps, count extra write bytes. */
	swapz_u8 bulk_enabled;
	swapz_u32 bulk_writes;
	swapz_u32 bulk_extents;
	swapz_u32 bulk_padding_blocks;
	/* Successful fully published runs by media composition, not a claim
	 * about block-layer merged/split requests. */
	swapz_u32 bulk_mixed_runs;
	swapz_u32 bulk_raw_only_runs;
	swapz_u32 bulk_raw_entries;
	/* Context-owned scratch, never a >1KiB frame on the kernel worker stack. */
	struct swapz_tx pending;
	swapz_u32 logical_scratch[SWAPZ_MAX_RECORDS];
	swapz_u8 plan_classes[SWAPZ_MAX_RECORDS];
	swapz_u8 plan_takes[SWAPZ_MAX_RECORDS];
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
	swapz_u8 max_read_blocks_per_record;
	swapz_u32 write_verify_read_blocks;
	swapz_u32 submitted_blocks;
	swapz_u32 completed_blocks;
	swapz_u32 physical_read_blocks;
	/* Successful targeted compressed reads: header block zero and additional
	 * payload callbacks/blocks. Diagnostics do not own I/O or mappings. */
	swapz_u32 read_metadata_requests;
	swapz_u32 read_payload_requests;
	swapz_u32 read_payload_blocks;
	/* One-extent read cache in preallocated read_scratch. On a bounded
	 * 8KiB fetch it may contain both blocks; otherwise only block zero.
	 * The serialized caller invalidates before any mutation. */
	swapz_u32 read_cached_start_block;
	swapz_u8 read_cached_extent_blocks;
	swapz_u8 read_cache_valid;
	swapz_u8 read_cached_full;
	swapz_u32 read_metadata_cache_hits;
	/*
	 * Owner-preallocated metadata-only cache. Each slot holds exactly the
	 * immutable SWZ3 block zero for one extent; payload blocks are never
	 * cached here. The serialized reader scans 64 fixed slots and uses an
	 * age stamp for exact LRU replacement without moving 4KiB data blocks.
	 */
	swapz_u8 *read_metadata_cache; /* 64 * 4096 bytes */
	swapz_u32 read_metadata_lru_start_blocks[SWAPZ_READ_METADATA_CACHE_ENTRIES];
	swapz_u32 read_metadata_lru_ages[SWAPZ_READ_METADATA_CACHE_ENTRIES];
	swapz_u8 read_metadata_lru_extent_blocks[SWAPZ_READ_METADATA_CACHE_ENTRIES];
	swapz_u8 read_metadata_lru_valid[SWAPZ_READ_METADATA_CACHE_ENTRIES];
	swapz_u32 read_metadata_lru_clock;
	swapz_u32 read_metadata_lru_hits;
	/* Lower callbacks, not block-queue requests; byte deltas are independent. */
	swapz_u32 read_full_extent_requests;
	swapz_u32 read_full_extent_cache_hits;
	/* Cold two-block records proven wholly inside metadata block zero;
	 * avoiding a speculative second block does not skip CRC validation. */
	swapz_u32 read_two_block_skips;
};

/* CPU-only finite-window selection, 4/8/16KiB; output classes 1/2/4. */
int swapz_engine_plan(const struct swapz_compressed_page *pages, swapz_u8 count,
		    swapz_u8 *classes, swapz_u8 *records_per_extent,
		    swapz_u8 *extent_count);
int swapz_engine_plan_bounded(const struct swapz_compressed_page *pages,
			    swapz_u8 count, swapz_u8 max_read_blocks,
			    swapz_u8 *classes, swapz_u8 *records_per_extent,
			    swapz_u8 *extent_count);
/*
 * Partial failure returns a nonzero status and sets *committed_pages to
 * exactly the prefix whose complete extents became authoritative. It NEVER
 * reports atomic success for an uncommitted full logical window.
 */
int swapz_engine_write_window(struct swapz_engine *engine,
			    const struct swapz_compressed_page *pages,
			    swapz_u8 count, swapz_u8 *committed_pages);
/*
 * Optional batched physically adjacent extent/raw writer. Stages multiple
 * logically independent records but publishes no mapping until ONE
 * confirmed lower write completes. Respects 1MiB segment boundary,
 * a 256KiB memory/I/O cap, and the prior committed-page-prefix ABI.
 */
/*
 * Explicit planning-only cold-read cap for an otherwise identical batched
 * write. This selects a less read-amplifying 4/8/16KiB layout without
 * changing the target's runtime read policy or lower publication contract.
 */
int swapz_engine_write_window_batched_read_cap(
				   struct swapz_engine *engine,
				   const struct swapz_compressed_page *pages,
				   swapz_u8 count, swapz_u8 *committed_pages,
				   swapz_u8 plan_read_blocks);
int swapz_engine_write_window_batched(struct swapz_engine *engine,
				   const struct swapz_compressed_page *pages,
				   swapz_u8 count, swapz_u8 *committed_pages);
/* Caller-owned and serialized: invalidate before writes, discards and barriers.
 * Never invalidate from a concurrent preparation producer. */
void swapz_engine_invalidate_read_cache(struct swapz_engine *engine);
/* Targeted read: metadata 4KiB plus only the required payload 4KiB blocks. */
int swapz_engine_read_page(struct swapz_engine *engine, swapz_u32 logical_page,
			 swapz_u8 *payload, swapz_u16 payload_capacity,
			 swapz_u16 *payload_length);

#endif
