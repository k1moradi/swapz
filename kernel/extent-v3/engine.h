/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_V3_EXTENT_ENGINE_H
#define SWAPZ_V3_EXTENT_ENGINE_H
#include "authority.h"

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
	int (*read_blocks)(void *opaque, sv3_u32 start_block, sv3_u8 blocks,
			   sv3_u8 *destination);
};

struct sv3_compressed_page {
	sv3_u32 logical_page;
	const sv3_u8 *payload;
	sv3_u16 length;
};

struct sv3_engine {
	struct sv3_authority *authority;
	struct sv3_io io;
	sv3_u8 *write_scratch; /* at least 16384 bytes */
	sv3_u8 *read_scratch;  /* at least 16384 bytes */
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
/* Targeted read: metadata 4KiB plus only the required payload 4KiB blocks. */
int sv3_engine_read_page(struct sv3_engine *engine, sv3_u32 logical_page,
			 sv3_u8 *payload, sv3_u16 payload_capacity,
			 sv3_u16 *payload_length);

#endif
