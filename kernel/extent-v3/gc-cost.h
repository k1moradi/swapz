/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_V3_GC_COST_H
#define SWAPZ_V3_GC_COST_H

#include "authority.h"

/*
 * This estimator runs over authoritative volatile metadata: no extra
 * lower reads during victim selection. Zero denotes corrupt/not-live input.
 * One 16-byte descriptor per compressed record is included; headers,
 * packing fragmentation and lower read amplification are not predicted.
 * Actual GC lower bytes are separately measured after relocation.
 */
static inline sv3_u32 sv3_gc_live_byte_cost(const struct sv3_map *m)
{
	if (!m || !m->valid)
		return 0;
	if (m->raw)
		return m->extent_blocks == 1 &&
			m->payload_length == SV3_BLOCK_BYTES ?
			SV3_BLOCK_BYTES : 0;
	if (!m->payload_length || m->payload_length > SV3_MAX_COMPRESSED)
		return 0;
	return (sv3_u32)m->payload_length + sizeof(struct sv3_record);
}

/*
 * Conservative host I/O-cost estimate for a single authoritative record.
 * A GC move MUST issue a selective lower read of the source before writing
 * the destination. A packed V3 extent may take more than one block to
 * fetch the metadata and record payload. The actual read path and read
 * cache/budget decide the completed count, so this is a selection
 * heuristic, NOT a measured or guaranteed bound on physical IO.
 *
 * Raw: 1 lower 4KiB read + a 4KiB copy; compressed: up to 1/2/3
 * lower reads for 1/2/4-block extents plus payload+descriptor write cost.
 * Explicitly penalizing PER-RECORD reads corrects the 3 tiny records
 * versus 1 large record counterexample found by loaded alpha.4 tests.
 */
static inline sv3_u32 sv3_gc_estimated_io_cost(const struct sv3_map *m)
{
	sv3_u32 bytes = sv3_gc_live_byte_cost(m);
	sv3_u32 reads;

	if (!bytes || (m->extent_blocks != 1 && m->extent_blocks != 2 &&
		       m->extent_blocks != 4))
		return 0;
	reads = m->extent_blocks == 4 ? 3 : m->extent_blocks;
	return bytes + reads * SV3_BLOCK_BYTES;
}

/*
 * A single 1MiB destination MUST retain some free space for the
 * blocked foreground write. A lower bound on the relocated object
 * footprint is the sum of raw page bytes or compressed payloads plus
 * V3 descriptors. If even that optimistic lower bound fills the whole
 * destination, no packing heuristic can produce useful reclaim.
 *
 * This is a necessary condition, NOT a promise that a candidate with
 * less data fits after 4/8/16KiB extent/header fragmentation.
 */
static inline int sv3_gc_has_possible_headroom(sv3_u32 live_bytes)
{
	return live_bytes && live_bytes <
	       SV3_SEGMENT_BLOCKS * SV3_BLOCK_BYTES;
}

/* For the selected policy choose lower relocation cost, then fewer
 * records. Stable segment scan order breaks remaining ties. */
static inline int sv3_gc_prefer(sv3_u32 score, sv3_u16 count,
			       sv3_u32 best, sv3_u16 best_count)
{
	return count && (score < best ||
			 (score == best && count < best_count));
}

#endif
