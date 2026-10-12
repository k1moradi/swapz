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
	sv3_u32 next_block;
	sv3_u32 open_segment;		/* UINT32_MAX before the first allocation */
	sv3_u32 next_segment_probe;
	sv3_u32 recycled_dead_segments;
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
		   sv3_u8 completed_blocks, int io_error);
/* Serialized explicit logical discard: invalidate and advance generation. */
int sv3_discard_page(struct sv3_authority *authority, sv3_u32 logical_page);
/* Binds on-media readback to current in-memory mapping and generation. */
int sv3_read_authoritative(const struct sv3_authority *authority,
			   sv3_u32 logical_page, const struct sv3_map *observed,
			   const void *extent, sv3_u32 bytes_total,
			   struct sv3_decoded *decoded,
			   const sv3_u8 **payload);

#endif
