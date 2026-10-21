/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_EXTENT_ENGINE_H
#define SWAPZ_EXTENT_ENGINE_H
#include "authority.h"
#define SWAPZ_BULK_BLOCKS 64U
#define SWAPZ_READ_METADATA_CACHE_ENTRIES 512U
#define SWAPZ_READ_METADATA_CACHE_WAYS 4U
#define SWAPZ_READ_METADATA_CACHE_SETS \
	(SWAPZ_READ_METADATA_CACHE_ENTRIES / SWAPZ_READ_METADATA_CACHE_WAYS)
#define SWAPZ_READ_EXTENT_CACHE_ENTRIES 16U
#define SWAPZ_PARALLEL_READ_SLOTS 2U

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
	 * concatenation of individually valid SWZ extents and raw blocks.
	 * The authority publishes NONE before this callback has returned
	 * full confirmed completion. See swapz_batch_pause()/resume(). */
	int (*write_run)(void *opaque, swapz_u32 start_block, swapz_u16 blocks,
			 const swapz_u8 *bytes, swapz_u16 *completed_blocks);
	int (*read_blocks)(void *opaque, swapz_u32 start_block, swapz_u8 blocks,
			   swapz_u8 *destination);
};

struct swapz_read_metadata_tag {
	swapz_u32 start_block;
	swapz_u32 age;
	swapz_u32 epoch;
	swapz_u8 extent_blocks;
	swapz_u8 reserved[3];
};

struct swapz_compressed_page {
	swapz_u32 logical_page;
	const swapz_u8 *payload;
	swapz_u32 payload_crc32c;
	swapz_u16 length;
	swapz_u8 encoding;
	/* When set, payload_crc32c was computed over exactly payload/length
	 * before serialized packing. Final bulk_scratch is still CRC-verified
	 * again by authority publication after lower I/O. */
	swapz_u8 payload_crc32c_valid;
	/* True for an uncompressed 4096-byte page. Raw entries follow all
	 * compressed entries in a mixed physical write window. */
	swapz_u8 raw;
};

/*
 * One immutable packed lower run. The caller owns bytes/tx storage for the
 * complete lifetime from staging through confirmed lower-I/O completion and
 * authority replay. Upper BIO ownership intentionally stays in dm-target.c so
 * the portable engine never depends on Linux bio types.
 */
struct swapz_io_run {
	swapz_u8 *bytes; /* at least SWAPZ_BULK_BLOCKS * SWAPZ_BLOCK_BYTES */
	struct swapz_tx *txs; /* at least SWAPZ_MAX_RECORDS transactions */
	swapz_u16 offsets[SWAPZ_MAX_RECORDS];
	swapz_u8 takes[SWAPZ_MAX_RECORDS];
	swapz_u8 raw[SWAPZ_MAX_RECORDS];
	swapz_u32 start_block;
	swapz_u16 blocks;
	swapz_u8 extent_count;
	swapz_u8 page_count;
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
	/* Adjacent-only runs closed because extent alignment inserted a gap. */
	swapz_u32 run_splits_by_hole;
	/* Successful fully published runs by media composition, not a claim
	 * about block-layer merged/split requests. */
	swapz_u32 bulk_mixed_runs;
	swapz_u32 bulk_raw_only_runs;
	swapz_u32 bulk_raw_entries;
	/*
	 * Kernel wall-time attribution for serialized write-engine CPU/memory
	 * phases. Userspace codec/unit builds leave these at zero. These are
	 * diagnostics only and never participate in correctness decisions.
	 */
	unsigned long long plan_wall_ns;
	unsigned long long pack_wall_ns;
	unsigned long long publish_wall_ns;
	swapz_u32 prehashed_records;
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
	/* One-extent read cache in preallocated read_scratch. The block mask
	 * records exactly which 4KiB blocks were successfully fetched for the
	 * current immutable extent. The serialized caller invalidates all
	 * residency before any mutation. */
	swapz_u32 read_cached_start_block;
	swapz_u8 read_cached_extent_blocks;
	swapz_u8 read_cache_valid;
	swapz_u8 read_cached_full;
	swapz_u8 read_cached_block_mask;
	/* Blocks inserted by an ID63 combined lower read but not yet validated
	 * by a constituent record. Residency is not cache-hit evidence. */
	swapz_u8 read_coalesced_block_mask;
	swapz_u32 read_metadata_cache_hits;
	/*
	 * Owner-preallocated metadata-only cache. Capacity remains 512 immutable
	 * SWZ block-zero images, but the directory is 128 sets x 4 ways so lookup
	 * and replacement touch at most four compact directory entries. Payload
	 * blocks are never cached here. Per-set age replacement trades exact
	 * global LRU ordering for bounded Core-2-friendly L1/L2 work.
	 */
	swapz_u8 *read_metadata_cache; /* entries * 4096 bytes */
	/*
	 * Four 16-byte tags make one 64-byte set. Align the directory so one
	 * four-way lookup/replacement is contained in one Core-2 cache line.
	 * epoch makes normal mutation invalidation O(1); stale tags are ignored.
	 */
	struct swapz_read_metadata_tag
		read_metadata_tags[SWAPZ_READ_METADATA_CACHE_ENTRIES]
		__attribute__((aligned(64)));
	swapz_u32 read_metadata_epoch;
	swapz_u32 read_metadata_lru_clock;
	swapz_u32 read_metadata_lru_hits;
	unsigned long long read_metadata_set_lookups;
	unsigned long long read_metadata_set_hits;
	unsigned long long read_metadata_set_probes;
	unsigned long long read_metadata_set_replacements;
	/* Bytes copied from cached block zero into read_scratch solely because
	 * the selected payload overlaps block zero; never count lower-I/O copies. */
	unsigned long long read_metadata_copy_bytes;
	/* Ordered-owner shared extent residency. Each fixed slot stores only
	 * blocks proven fetched for one immutable 4/8/16KiB extent. Helpers are
	 * primed from this cache before dispatch and absorbed only after join. */
	swapz_u8 *read_extent_cache; /* entries * SWAPZ_MAX_EXTENT_BYTES */
	swapz_u32 read_extent_lru_start_blocks[SWAPZ_READ_EXTENT_CACHE_ENTRIES];
	swapz_u32 read_extent_lru_ages[SWAPZ_READ_EXTENT_CACHE_ENTRIES];
	swapz_u8 read_extent_lru_extent_blocks[SWAPZ_READ_EXTENT_CACHE_ENTRIES];
	swapz_u8 read_extent_lru_block_masks[SWAPZ_READ_EXTENT_CACHE_ENTRIES];
	swapz_u8 read_extent_lru_valid[SWAPZ_READ_EXTENT_CACHE_ENTRIES];
	swapz_u32 read_extent_lru_clock;
	/* Lower callbacks, not block-queue requests; byte deltas are independent. */
	swapz_u32 read_full_extent_requests;
	swapz_u32 read_full_extent_cache_hits;
	/* Cold two-block records proven wholly inside metadata block zero;
	 * avoiding a speculative second block does not skip CRC validation. */
	swapz_u32 read_two_block_skips;
};

/* CPU-only finite-window selection, 4/8/16KiB; output classes 1/2/4. */
int swapz_engine_plan_bounded(const struct swapz_compressed_page *pages,
			    swapz_u8 count, swapz_u8 max_read_blocks,
			    swapz_u8 *classes, swapz_u8 *records_per_extent,
			    swapz_u8 *extent_count);
/* Largest lower uniform-payload threshold that can add one more record to a
 * 4/8/16KiB SWZ extent. Zero means no useful lower cliff within 64 records. */
swapz_u16 swapz_engine_next_uniform_pack_limit(swapz_u16 length);
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
/*
 * Split batched write ownership for asynchronous lower-I/O callers.
 * prepare reserves/stages and packs one bounded physical run but publishes
 * no mapping. complete may run only after the caller has a definitive lower
 * completion result. A failed/uncertain run quarantines every reservation.
 */
int swapz_engine_prepare_batched_run(
				   struct swapz_engine *engine,
				   const struct swapz_compressed_page *pages,
				   swapz_u8 count, struct swapz_io_run *run,
				   swapz_u8 *prepared_pages,
				   swapz_u8 plan_read_blocks);
int swapz_engine_complete_batched_run(
				    struct swapz_engine *engine,
				    const struct swapz_io_run *run,
				    swapz_u16 completed_blocks, int io_error,
				    swapz_u8 *committed_pages);

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
/* Serialized owner transfers diagnostic read counters from a private read
 * engine after its bounded concurrent operation has joined. Cache residency
 * and authority pointers are intentionally not transferred. */
void swapz_engine_merge_read_telemetry(struct swapz_engine *destination,
				       struct swapz_engine *source);
/* Ordered-owner cache synchronization for private read engines. Neither helper
 * performs lower I/O or changes mapping authority. */
void swapz_engine_prime_read_slot(const struct swapz_engine *master,
				  struct swapz_engine *slot,
				  swapz_u32 start_block,
				  swapz_u8 extent_blocks);
void swapz_engine_absorb_read_slot(struct swapz_engine *master,
				   struct swapz_engine *slot);
/*
 * ID63 helpers. required_read_range computes the exact contiguous lower range
 * still missing for one immutable extent after caller-side cache priming.
 * required_read_range_cached performs the same calculation directly against
 * the ordered owner's direct/LRU residency without copying cached blocks into a
 * private slot. coalesced_span accepts only zero-gap, same-segment ranges.
 * coalesce_read_pair performs exactly one lower callback and seeds two private
 * engines; normal per-record generation/CRC validation remains mandatory
 * before shared cache publication.
 */
int swapz_engine_required_read_range(
				   const struct swapz_engine *engine,
				   const swapz_u32 *logical_pages,
				   swapz_u8 count,
				   swapz_u32 start_block,
				   swapz_u8 extent_blocks,
				   swapz_u8 *first_block,
				   swapz_u8 *blocks);
int swapz_engine_required_read_range_cached(
				   const struct swapz_engine *engine,
				   const swapz_u32 *logical_pages,
				   swapz_u8 count,
				   swapz_u32 start_block,
				   swapz_u8 extent_blocks,
				   swapz_u8 *first_block,
				   swapz_u8 *blocks);
int swapz_engine_coalesced_span(
				   swapz_u32 start0, swapz_u8 extent0,
				   swapz_u8 first0, swapz_u8 blocks0,
				   swapz_u32 start1, swapz_u8 extent1,
				   swapz_u8 first1, swapz_u8 blocks1,
				   swapz_u32 *combined_start,
				   swapz_u8 *combined_blocks);
int swapz_engine_coalesce_read_pair(
				   struct swapz_engine *first,
				   struct swapz_engine *second,
				   swapz_u32 start0, swapz_u8 extent0,
				   swapz_u8 first0, swapz_u8 blocks0,
				   swapz_u32 start1, swapz_u8 extent1,
				   swapz_u8 first1, swapz_u8 blocks1,
				   swapz_u8 *scratch,
				   swapz_u8 scratch_blocks);
/* Targeted read: metadata 4KiB plus only the required payload 4KiB blocks. */
int swapz_engine_read_page(struct swapz_engine *engine, swapz_u32 logical_page,
			 swapz_u8 *payload, swapz_u16 payload_capacity,
			 swapz_u16 *payload_length);

#endif
