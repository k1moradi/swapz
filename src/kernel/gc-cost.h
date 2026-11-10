/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_GC_COST_H
#define SWAPZ_GC_COST_H

#include "authority.h"

/* Only 1/2/4-block extents can carry authoritative GC records. */
static inline int swapz_gc_valid_extent_blocks(swapz_u8 extent_blocks)
{
	return extent_blocks == 1 || extent_blocks == 2 ||
	       extent_blocks == 4;
}

/*
 * This estimator runs over authoritative volatile metadata: no extra
 * lower reads during victim selection. Zero denotes corrupt/not-live input.
 * Compressed payload bytes are the only live backing bytes. All descriptors
 * and integrity metadata are volatile RAM authority. Packing fragmentation and
 * lower read amplification are accounted separately.
 */
static inline swapz_u32 swapz_gc_live_byte_cost(const struct swapz_map *m)
{
	if (!m || !m->valid ||
	    !swapz_gc_valid_extent_blocks(m->extent_blocks))
		return 0;
	if (m->raw)
		return m->extent_blocks == 1 &&
			m->payload_length == SWAPZ_BLOCK_BYTES ?
			SWAPZ_BLOCK_BYTES : 0;
	if (!m->payload_length || m->payload_length > SWAPZ_MAX_COMPRESSED)
		return 0;
	return m->payload_length;
}

/*
 * Fast-path helper when swapz_gc_live_byte_cost(m) has already been computed
 * by the caller, avoiding a duplicate validation and length calculation.
 */
static inline swapz_u32 swapz_gc_estimated_io_cost_with_bytes(
	const struct swapz_map *m, swapz_u32 bytes)
{
	swapz_u32 first_block, last_block, reads;

	if (!bytes || !m || !swapz_gc_valid_extent_blocks(m->extent_blocks))
		return 0;
	if (m->raw)
		return m->extent_blocks == 1 ? bytes + SWAPZ_BLOCK_BYTES : 0;
	if (!m->payload_length ||
	    m->payload_offset >=
		(swapz_u32)m->extent_blocks * SWAPZ_BLOCK_BYTES ||
	    m->payload_length >
		(swapz_u32)m->extent_blocks * SWAPZ_BLOCK_BYTES -
		m->payload_offset)
		return 0;
	first_block = m->payload_offset >> SWAPZ_BLOCK_SHIFT;
	last_block = ((swapz_u32)m->payload_offset +
		      m->payload_length - 1U) >> SWAPZ_BLOCK_SHIFT;
	reads = last_block - first_block + 1U;
	return bytes + reads * SWAPZ_BLOCK_BYTES;
}

/*
 * Conservative host I/O-cost estimate for one authoritative RAM mapping.
 * A GC move MUST issue a selective lower read of the source payload before
 * writing the destination. A packed swapz payload may span more than one
 * lower block; no serialized metadata block is read. The actual read path
 * and payload cache/budget decide the completed count, so this is a
 * selection heuristic, NOT a measured or guaranteed bound on physical I/O.
 *
 * Raw: one lower 4KiB read + a 4KiB copy; compressed: one or two lower
 * payload-block reads plus payload-only write cost. Explicitly penalizing
 * PER-MAPPING reads corrects the three-tiny-payloads versus one-large-payload
 * counterexample found by loaded alpha.4 tests.
 */
static inline swapz_u32 swapz_gc_estimated_io_cost(const struct swapz_map *m)
{
	return swapz_gc_estimated_io_cost_with_bytes(
		m, swapz_gc_live_byte_cost(m));
}

/*
 * A single 1MiB destination MUST retain some free space for the
 * blocked foreground write. A lower bound on the relocated object
 * footprint is the sum of raw page bytes or compressed payload bytes. If
 * even that optimistic lower bound fills the whole
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
 * At most FOUR >=3277-byte records can occupy one 16KiB payload extent:
 * five such payloads exceed 16384B even with no on-media metadata.
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
	(SWAPZ_MAX_EXTENT_BYTES / 5U + 1U)

static inline swapz_u8 swapz_gc_min_live_blocks(const struct swapz_map *m)
{
	if (!m || !m->valid ||
	    !swapz_gc_valid_extent_blocks(m->extent_blocks))
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
