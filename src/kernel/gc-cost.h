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
static inline swapz_u32 swapz_gc_live_byte_cost(const struct swapz_map *m)
{
	if (!m || !m->valid)
		return 0;
	if (m->raw)
		return m->extent_blocks == 1 &&
			m->payload_length == SWAPZ_BLOCK_BYTES ?
			SWAPZ_BLOCK_BYTES : 0;
	if (!m->payload_length || m->payload_length > SWAPZ_MAX_COMPRESSED)
		return 0;
	return (swapz_u32)m->payload_length + sizeof(struct swapz_record);
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
static inline swapz_u32 swapz_gc_estimated_io_cost(const struct swapz_map *m)
{
	swapz_u32 bytes = swapz_gc_live_byte_cost(m);
	swapz_u32 reads;

	if (!bytes || (m->extent_blocks != 1 && m->extent_blocks != 2 &&
		       m->extent_blocks != 4))
		return 0;
	reads = m->extent_blocks == 4 ? 3 : m->extent_blocks;
	return bytes + reads * SWAPZ_BLOCK_BYTES;
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
static inline int swapz_gc_has_possible_headroom(swapz_u32 live_bytes)
{
	return live_bytes && live_bytes <
	       SWAPZ_SEGMENT_BLOCKS * SWAPZ_BLOCK_BYTES;
}

/*
 * PROVEN physical lower bound for large compressed GC survivors.
 *
 * At most FOUR >=3258-byte records can occupy one 16KiB SWZ3 extent:
 * five of them + one header + five 16B descriptors exceed 16384B.
 * Similarly at most two can occupy an 8KiB extent, or one a 4KiB
 * extent. Consequently every such survivor requires at least ONE
 * physical 4KiB allocation unit on average, even with perfect packing.
 * Each raw record independently requires exactly one dedicated block.
 * Mixing smaller records cannot lower the required block count.
 *
 * This is a NECESSARY bound, not a prediction of fragmentation. Use it
 * solely to reject victims with a provably full GC destination before
 * performing potentially 2MiB of wasted relocation I/O.
 */
#define SWAPZ_GC_UNSHAREABLE_MIN_LENGTH \
	((SWAPZ_MAX_EXTENT_BYTES - sizeof(struct swapz_header) - \
	  5U * sizeof(struct swapz_record)) / 5U + 1U)

static inline swapz_u8 swapz_gc_min_live_blocks(const struct swapz_map *m)
{
	if (!m || !m->valid)
		return 0;
	if (m->raw)
		return m->payload_length == SWAPZ_BLOCK_BYTES &&
		       m->extent_blocks == 1 ? 1 : 0;
	return m->payload_length >= SWAPZ_GC_UNSHAREABLE_MIN_LENGTH &&
	       m->payload_length <= SWAPZ_MAX_COMPRESSED ? 1 : 0;
}

static inline int swapz_gc_candidate_can_free_block(swapz_u32 live_bytes,
						  swapz_u16 min_live_blocks)
{
	return swapz_gc_has_possible_headroom(live_bytes) &&
	       min_live_blocks < SWAPZ_SEGMENT_BLOCKS;
}

/* For the selected policy choose lower relocation cost, then fewer
 * records. Stable segment scan order breaks remaining ties. */
static inline int swapz_gc_prefer(swapz_u32 score, swapz_u16 count,
			       swapz_u32 best, swapz_u16 best_count)
{
	return count && (score < best ||
			 (score == best && count < best_count));
}

#endif
