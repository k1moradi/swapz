/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_V3_EXTENT_AUTHORITY_H
#define SWAPZ_V3_EXTENT_AUTHORITY_H
#include "codec.h"

#define SV3_SEGMENT_BLOCKS 256U

/*
 * Experimental worker-owned volatile mapping authority. Caller provisions
 * all arrays. It does NOT implement physical recycling or GC. On failure,
 * an allocated extent is permanently abandoned: NEVER reuse a possibly
 * partially written location before a separately verified reclaim path.
 */
struct sv3_map {
	sv3_u32 start_block;
	sv3_u32 sequence;
	sv3_u32 generation;
	/* Volatile sidecar integrity for a full raw 4KiB fallback page.
	 * Raw has no space for an on-media CRC without another physical block. */
	sv3_u32 raw_crc32c;
	/* Volatile compressed payload bytes (4096 for raw). Required for
	 * real live-byte GC victim selection without reading every extent. */
	sv3_u16 payload_length;
	sv3_u8 extent_blocks;
	sv3_u8 record_index;
	sv3_u8 raw;
	sv3_u8 valid;
};

struct sv3_tx_record {
	sv3_u32 logical_page;
	sv3_u32 generation;
};

struct sv3_tx {
	sv3_u32 start_block;
	sv3_u32 sequence;
	sv3_u8 extent_blocks;
	sv3_u8 count;
	struct sv3_tx_record records[SV3_MAX_RECORDS];
};

struct sv3_authority {
	struct sv3_map *maps;		/* [logical_pages] */
	sv3_u16 *live_records;		/* [physical_blocks]; extent START */
	sv3_u8 *extent_classes;		/* [physical_blocks]; extent START */
	sv3_u32 logical_pages;
	sv3_u32 physical_blocks;
	sv3_u32 reserve_blocks;
	/*
	 * Optional production GC segment roles: one byte per 1MiB segment.
	 * 1 = foreground writable; 0 = reserved GC destination. Roles are
	 * exchanged ONLY after a fully verified live relocation. A fixed
	 * numeric "reserve tail" is not sustainable across GC cycles.
	 * NULL retains the original research allocator/test behavior.
	 */
	sv3_u8 *segment_foreground;
	sv3_u32 segment_count;
	sv3_u32 gc_destination;
	sv3_u32 next_block;
	sv3_u32 open_segment;		/* UINT32_MAX before the first allocation */
	sv3_u32 next_segment_probe;
	sv3_u32 recycled_dead_segments;
	/*
	 * Runtime-only opt-in. Preserves old research append-only semantics by
	 * default; the separately reviewed Device Mapper target enables this.
	 */
	sv3_u8 reuse_dead_segments;
	/* Only the serialized GC worker may set this, never foreground. */
	sv3_u8 gc_allocation;
	/* GC may NOT allocate into the paused foreground OPEN segment or
	 * the victim being relocated, even if its current live count is zero. */
	sv3_u32 gc_forbidden_open;
	sv3_u32 gc_forbidden_victim;
	sv3_u32 next_sequence;
	sv3_u32 abandoned_blocks;
	sv3_u32 committed_blocks;
	sv3_u32 active_start;
	sv3_u32 active_sequence;
	sv3_u8 active_blocks;
	sv3_u8 active_count;
	/*
	 * Worker-owned immutable staged descriptor snapshot. The caller may
	 * retain or mutate its returned sv3_tx, but publication must never trust
	 * caller-supplied record identities or generations absent this match.
	 */
	struct sv3_tx active_tx;
	int in_flight;
};

/*
 * Enable rotating GC reserve ownership, using a preallocated segment_count
 * byte array. Must be called on a fresh authority before staging any write.
 * Initially first physical-reserve segments are foreground and the tail
 * is reserve; after successful GC, victim and destination exchange roles.
 */
int sv3_enable_segment_rotation(struct sv3_authority *authority,
				sv3_u8 *segment_roles,
				sv3_u32 segment_count);
/* Begin GC into ONE entirely dead reserve segment (not a foreground one).
 * Caller preserves the foreground cursor until commit; no nested GC. */
int sv3_gc_begin_rotation(struct sv3_authority *authority, sv3_u32 victim);
/* Swap physical roles ONLY after the source victim is wholly dead.
 * Leaves foreground cursor inside new (formerly reserve) destination. */
int sv3_gc_commit_rotation(struct sv3_authority *authority, sv3_u32 victim);

/* Returns -ENOSPC unless capacity supports logical pages plus GC reserve. */
int sv3_authority_init(struct sv3_authority *authority,
		       struct sv3_map *maps, sv3_u16 *live_records,
		       sv3_u8 *extent_classes, sv3_u32 logical_pages,
		       sv3_u32 physical_blocks);
/* Reserves aligned physical blocks; single worker, one pending transaction. */
int sv3_stage(struct sv3_authority *authority, const sv3_u32 *logical_pages,
	      sv3_u8 count, sv3_u8 blocks, struct sv3_tx *out);
/*
 * IMPORTANT: success requires full extent I/O completion (not submission).
 * The caller must provide the exact completed on-media bytes. Verify all
 * record CRC32Cs and old-authority invariants BEFORE publishing any mapping.
 */
int sv3_finish(struct sv3_authority *authority, const struct sv3_tx *tx,
	       const void *extent, sv3_u32 bytes_total,
	       sv3_u8 completed_blocks, int io_error);
/* Cancel an abandoned physical region; old mappings remain authoritative. */
int sv3_abort(struct sv3_authority *authority, const struct sv3_tx *tx);
/*
 * Raw 4KiB page (LZ4 fallback) occupies a whole aligned block and has no
 * V3 descriptor. The caller must stage exactly one record / one block and
 * only call finish_raw after the WHOLE lower write completes.
 */
int sv3_finish_raw(struct sv3_authority *authority, const struct sv3_tx *tx,
		   const void *raw_page, sv3_u8 completed_blocks, int io_error);
/* Check raw payload integrity against volatile authoritative CRC. */
int sv3_verify_raw(const struct sv3_authority *authority,
		   sv3_u32 logical_page, const void *raw_page);
/* Serialized explicit logical discard: invalidate and advance generation. */
int sv3_discard_page(struct sv3_authority *authority, sv3_u32 logical_page);
/* Fail-closed multi-page discard: prevalidate entire range before mutation. */
int sv3_discard_range(struct sv3_authority *authority,
		      sv3_u32 first_page, sv3_u32 page_count);
/* Binds on-media readback to current in-memory mapping and generation. */
int sv3_read_authoritative(const struct sv3_authority *authority,
			   sv3_u32 logical_page, const struct sv3_map *observed,
			   const void *extent, sv3_u32 bytes_total,
			   struct sv3_decoded *decoded,
			   const sv3_u8 **payload);

#endif
