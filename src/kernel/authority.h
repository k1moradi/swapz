/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_EXTENT_AUTHORITY_H
#define SWAPZ_EXTENT_AUTHORITY_H
#include "codec.h"

#define SWAPZ_SEGMENT_BLOCKS 256U

/*
 * Experimental worker-owned volatile mapping authority. Caller provisions
 * all arrays. It does NOT implement physical recycling or GC. On failure,
 * an allocated extent is permanently abandoned: NEVER reuse a possibly
 * partially written location before a separately verified reclaim path.
 */
struct swapz_map {
	swapz_u32 start_block;
	swapz_u32 sequence;
	swapz_u32 generation;
	/* Volatile sidecar integrity for a full raw 4KiB fallback page.
	 * Raw has no space for an on-media CRC without another physical block. */
	swapz_u32 raw_crc32c;
	/* Volatile compressed payload bytes (4096 for raw). Required for
	 * real live-byte GC victim selection without reading every extent. */
	swapz_u16 payload_length;
	/* Validated at publication; read hint only, cross-checked against the
	 * on-media CRC-protected record before trusting returned payload. */
	swapz_u16 payload_offset;
	swapz_u8 extent_blocks;
	swapz_u8 record_index;
	swapz_u8 raw;
	swapz_u8 valid;
};

struct swapz_tx_record {
	swapz_u32 logical_page;
	swapz_u32 generation;
};

struct swapz_tx {
	swapz_u32 start_block;
	swapz_u32 sequence;
	swapz_u8 extent_blocks;
	swapz_u8 count;
	struct swapz_tx_record records[SWAPZ_MAX_RECORDS];
};

typedef int (*swapz_dead_segment_recycle_fn)(void *opaque,
					      swapz_u32 segment);

struct swapz_authority {
	struct swapz_map *maps;		/* [logical_pages] */
	swapz_u16 *live_records;		/* [physical_blocks]; extent START */
	swapz_u8 *extent_classes;		/* [physical_blocks]; extent START */
	swapz_u32 logical_pages;
	swapz_u32 physical_blocks;
	swapz_u32 reserve_blocks;
	/*
	 * Optional production GC segment roles: one byte per 1MiB segment.
	 * 1 = foreground writable; 0 = reserved GC destination. Roles are
	 * exchanged ONLY after a fully verified live relocation. A fixed
	 * numeric "reserve tail" is not sustainable across GC cycles.
	 * NULL retains the original research allocator/test behavior.
	 */
	swapz_u8 *segment_foreground;
	/* Optional exact logical-map occupancy per 1MiB segment. Production
	 * supplies this bounded sidecar so dead-segment validation is O(256)
	 * instead of rescanning every logical page. */
	swapz_u32 *segment_mapped_pages;
	/* Optional logical segment-open counts. These are allocator write-cycle
	 * telemetry, not physical NAND wear measurements. */
	swapz_u32 *segment_program_counts;
	/* Optional per-segment GC scores maintained with map publication. */
	swapz_u32 *segment_gc_live_bytes;
	swapz_u32 *segment_gc_io_cost;
	swapz_u16 *segment_gc_min_live_blocks;
	swapz_u32 segment_count;
	swapz_u32 gc_destination;
	swapz_u32 next_block;
	swapz_u32 open_segment;		/* UINT32_MAX before the first allocation */
	swapz_u32 next_segment_probe;
	/* Placement/allocation evidence only; never participates in policy. */
	unsigned long long alignment_hole_blocks_foreground;
	unsigned long long alignment_hole_blocks_gc;
	unsigned long long alloc_probe_segments;
	unsigned long long alloc_probe_full_scans;
	unsigned long long alloc_probe_wall_ns;
	swapz_u32 recycled_dead_segments;
	/*
	 * Optional caller hook invoked only after a previously written 1MiB
	 * segment is proven wholly dead and immediately before allocator reuse.
	 * A negative return blocks reuse without mutating authority state.
	 */
	swapz_dead_segment_recycle_fn dead_segment_recycle;
	void *dead_segment_recycle_opaque;
	/*
	 * Runtime-only opt-in. Preserves old research append-only semantics by
	 * default; the separately reviewed Device Mapper target enables this.
	 */
	swapz_u8 reuse_dead_segments;
	/*
	 * Experimental placement A/B. Zero preserves the qualified power-of-two
	 * physical-start alignment; one packs existing 1/2/4-block extents
	 * back-to-back at 4KiB granularity. This never changes SWZ3 bytes.
	 */
	swapz_u8 packed_placement;
	/* Only the serialized GC worker may set this, never foreground. */
	swapz_u8 gc_allocation;
	/* GC may NOT allocate into the paused foreground OPEN segment or
	 * the victim being relocated, even if its current live count is zero. */
	swapz_u32 gc_forbidden_open;
	swapz_u32 gc_forbidden_victim;
	swapz_u32 next_sequence;
	swapz_u32 abandoned_blocks;
	swapz_u32 committed_blocks;
	swapz_u32 active_start;
	swapz_u32 active_sequence;
	swapz_u8 active_blocks;
	swapz_u8 active_count;
	/*
	 * Worker-owned immutable staged descriptor snapshot. The caller may
	 * retain or mutate its returned swapz_tx, but publication must never trust
	 * caller-supplied record identities or generations absent this match.
	 */
	struct swapz_tx active_tx;
	int in_flight;
	/*
	 * Bounded writer-only group: immutable transactions are kept in the
	 * engine, and none are published until a combined lower write finishes.
	 * Unlike in_flight, batch_pending can represent up to 64 RESERVED
	 * extents in ONE physical segment, but zero committed mappings.
	 */
	swapz_u8 batch_pending;
	swapz_u8 batch_replaying;
	swapz_u8 batch_stage_allowed;
	swapz_u8 batch_consumed;
	swapz_u32 batch_segment;
	swapz_u32 batch_first_sequence;
	/* CRC of the exact immutable staged transaction snapshots,
	 * including record identities and generations. A forged caller
	 * snapshot can never publish an unrelated page into a batch. */
	swapz_u32 batch_hashes[SWAPZ_MAX_RECORDS];
	/* Diagnostic only: exact wall time inside final publication payload CRC32C
	 * calls. Native builds leave this at zero; it never affects authority. */
	unsigned long long publish_crc_wall_ns;
	/* Exact wall time hashing immutable paused transaction snapshots.
	 * This measures the existing full-struct CRC only; it changes no
	 * transaction identity, protection scope or publication semantics. */
	unsigned long long batch_snapshot_crc_wall_ns;
	/* Phase split for the same unchanged full-transaction snapshot hash.
	 * pause is outside engine publish; resume is inside publish authority. */
	unsigned long long batch_pause_crc_wall_ns;
	unsigned long long batch_resume_crc_wall_ns;
};

/*
 * Enable rotating GC reserve ownership, using a preallocated segment_count
 * byte array. Must be called on a fresh authority before staging any write.
 * Initially first physical-reserve segments are foreground and the tail
 * is reserve; after successful GC, victim and destination exchange roles.
 */
int swapz_enable_segment_rotation(struct swapz_authority *authority,
				swapz_u8 *segment_roles,
				swapz_u32 segment_count);
/* Attach a caller-owned exact mapping-count sidecar on a fresh rotating
 * authority. Native/research callers may omit it and retain full-map checks. */
int swapz_enable_segment_mapping_counts(struct swapz_authority *authority,
				      swapz_u32 *segment_mapped_pages,
				      swapz_u32 segment_count);
int swapz_enable_segment_program_counts(struct swapz_authority *authority,
				      swapz_u32 *segment_program_counts,
				      swapz_u32 segment_count);
int swapz_enable_segment_gc_accounting(struct swapz_authority *authority,
				     swapz_u32 *live_bytes,
				     swapz_u32 *io_cost,
				     swapz_u16 *min_live_blocks,
				     swapz_u32 segment_count);
/* Begin GC into ONE entirely dead reserve segment (not a foreground one).
 * Caller preserves the foreground cursor until commit; no nested GC. */
int swapz_gc_begin_rotation(struct swapz_authority *authority, swapz_u32 victim);
/* Swap physical roles ONLY after the source victim is wholly dead.
 * Leaves foreground cursor inside new (formerly reserve) destination. */
int swapz_gc_commit_rotation(struct swapz_authority *authority, swapz_u32 victim);

/* Returns -ENOSPC unless capacity supports logical pages plus GC reserve. */
int swapz_authority_init(struct swapz_authority *authority,
		       struct swapz_map *maps, swapz_u16 *live_records,
		       swapz_u8 *extent_classes, swapz_u32 logical_pages,
		       swapz_u32 physical_blocks);
/* Reserves physical blocks; single worker, one pending transaction. */
int swapz_stage(struct swapz_authority *authority, const swapz_u32 *logical_pages,
	      swapz_u8 count, swapz_u8 blocks, struct swapz_tx *out);
/*
 * IMPORTANT: success requires full extent I/O completion (not submission).
 * The caller must provide the exact completed on-media bytes. Verify all
 * record CRC32Cs and old-authority invariants BEFORE publishing any mapping.
 */
int swapz_finish(struct swapz_authority *authority, const struct swapz_tx *tx,
	       const void *extent, swapz_u32 bytes_total,
	       swapz_u8 completed_blocks, int io_error);
/*
 * Serialized batched-lower-write transition: transfer the active stage
 * to a caller-owned immutable swapz_tx snapshot without publishing mappings.
 * Stage further extents ONLY inside the same physical segment. On lower
 * completion restore snapshots in sequence and use normal swapz_finish().
 * Failed lower writes require resume+abort of every snapshot. No upper BIO
 * may be acknowledged during this protocol.
 */
int swapz_stage_batch(struct swapz_authority *authority,
		    const swapz_u32 *logical_pages, swapz_u8 count,
		    swapz_u8 blocks, struct swapz_tx *out);
int swapz_batch_pause(struct swapz_authority *authority, const struct swapz_tx *tx);
int swapz_batch_resume(struct swapz_authority *authority, const struct swapz_tx *tx);
/* Cancel an abandoned physical region; old mappings remain authoritative. */
int swapz_abort(struct swapz_authority *authority, const struct swapz_tx *tx);
/*
 * Raw 4KiB page (LZ4 fallback) occupies a whole aligned block and has no
 * SWZ3 descriptor. The caller must stage exactly one record / one block and
 * only call finish_raw after the WHOLE lower write completes.
 */
int swapz_finish_raw(struct swapz_authority *authority, const struct swapz_tx *tx,
		   const void *raw_page, swapz_u8 completed_blocks, int io_error);
/* Check raw payload integrity against volatile authoritative CRC. */
int swapz_verify_raw(const struct swapz_authority *authority,
		   swapz_u32 logical_page, const void *raw_page);
/* Serialized explicit logical discard: invalidate and advance generation. */
int swapz_discard_page(struct swapz_authority *authority, swapz_u32 logical_page);
/*
 * Fast path after swapz_peek() has validated metadata in worker-owned scratch.
 * Rechecks current authority/sequence and verifies the payload CRC without
 * re-running the metadata parser over the same block-zero bytes.
 */
int swapz_read_authoritative_peeked(const struct swapz_authority *authority,
				  swapz_u32 logical_page,
				  const struct swapz_map *observed,
				  const void *extent, swapz_u32 bytes_total,
				  const struct swapz_decoded *peeked,
				  const swapz_u8 **payload);

#endif
