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

/* For the selected policy choose lower relocation cost, then fewer
 * records. Stable segment scan order breaks remaining ties. */
static inline int sv3_gc_prefer(sv3_u32 score, sv3_u16 count,
			       sv3_u32 best, sv3_u16 best_count)
{
	return count && (score < best ||
			 (score == best && count < best_count));
}

#endif
