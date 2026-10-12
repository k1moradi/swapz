// SPDX-License-Identifier: GPL-2.0-only
#include "authority.h"

#ifdef __KERNEL__
#include <linux/errno.h>
#include <linux/string.h>
#else
#include <errno.h>
#include <string.h>
#endif

static int sv3_legal_class(sv3_u8 blocks)
{
	return blocks == 1U || blocks == 2U || blocks == 4U;
}

int sv3_authority_init(struct sv3_authority *a,
		       struct sv3_map *maps, sv3_u16 *live_records,
		       sv3_u8 *extent_classes, sv3_u32 logical_pages,
		       sv3_u32 physical_blocks)
{
	sv3_u32 reserve;

	if (!a || !maps || !live_records || !extent_classes ||
	    !logical_pages || physical_blocks < 3U * SV3_SEGMENT_BLOCKS ||
	    physical_blocks % SV3_SEGMENT_BLOCKS)
		return -EINVAL;
	reserve = (logical_pages / 4U) + (logical_pages % 4U != 0);
	if (reserve < 2U * SV3_SEGMENT_BLOCKS)
		reserve = 2U * SV3_SEGMENT_BLOCKS;
	if (reserve >= physical_blocks ||
	    logical_pages > physical_blocks - reserve)
		return -ENOSPC;

	memset(a, 0, sizeof(*a));
	memset(maps, 0, (size_t)logical_pages * sizeof(*maps));
	memset(live_records, 0,
	       (size_t)physical_blocks * sizeof(*live_records));
	memset(extent_classes, 0,
	       (size_t)physical_blocks * sizeof(*extent_classes));
	a->maps = maps;
	a->live_records = live_records;
	a->extent_classes = extent_classes;
	a->logical_pages = logical_pages;
	a->physical_blocks = physical_blocks;
	a->reserve_blocks = reserve;
	a->next_sequence = 1;
	return 0;
}

int sv3_stage(struct sv3_authority *a, const sv3_u32 *pages,
	      sv3_u8 count, sv3_u8 blocks, struct sv3_tx *out)
{
	sv3_u32 limit, start;
	sv3_u8 index;

	if (!a || !a->maps || !pages || !out ||
	    !sv3_legal_class(blocks) || !count || count > SV3_MAX_RECORDS)
		return -EINVAL;
	if (a->in_flight)
		return -EBUSY;
	if (!a->next_sequence || a->next_sequence == ~(sv3_u32)0)
		return -EOVERFLOW;
	for (index = 0; index < count; ++index) {
		sv3_u8 earlier;

		if (pages[index] >= a->logical_pages)
			return -ERANGE;
		if (a->maps[pages[index]].generation == ~(sv3_u32)0)
			return -EOVERFLOW;
		for (earlier = 0; earlier < index; ++earlier) {
			if (pages[earlier] == pages[index])
				return -EEXIST;
		}
	}

	limit = a->physical_blocks - a->reserve_blocks;
	if (a->next_block > limit)
		return -ENOSPC;
	/* Classes 1,2,4 divide the 1MiB segment width without crossing it. */
	if (blocks - 1U > limit - a->next_block)
		return -ENOSPC;
	start = (a->next_block + blocks - 1U) & ~(sv3_u32)(blocks - 1U);
	if (start > limit || blocks > limit - start ||
	    start % SV3_SEGMENT_BLOCKS + blocks > SV3_SEGMENT_BLOCKS)
		return -ENOSPC;

	memset(out, 0, sizeof(*out));
	out->start_block = start;
	out->sequence = a->next_sequence++;
	out->extent_blocks = blocks;
	out->count = count;
	for (index = 0; index < count; ++index) {
		out->records[index].logical_page = pages[index];
		out->records[index].generation =
			a->maps[pages[index]].generation + 1U;
	}
	/*
	 * Consume the reserved space NOW, before lower submission.  On any
	 * short/torn write it will be quarantined, never reused by this code.
	 */
	a->next_block = start + blocks;
	a->active_start = start;
	a->active_sequence = out->sequence;
	a->active_blocks = blocks;
	a->active_count = count;
	/* All original record identities and generations are now authoritative. */
	a->active_tx = *out;
	a->in_flight = 1;
	return 0;
}

static int sv3_is_active(const struct sv3_authority *a,
			 const struct sv3_tx *tx)
{
	sv3_u8 index;

	if (!a || !tx || !a->in_flight ||
	    tx->start_block != a->active_start ||
	    tx->sequence != a->active_sequence ||
	    tx->extent_blocks != a->active_blocks ||
	    tx->count != a->active_count ||
	    tx->start_block != a->active_tx.start_block ||
	    tx->sequence != a->active_tx.sequence ||
	    tx->extent_blocks != a->active_tx.extent_blocks ||
	    tx->count != a->active_tx.count ||
	    !sv3_legal_class(tx->extent_blocks) ||
	    !tx->count || tx->count > SV3_MAX_RECORDS)
		return 0;

	/* Compare fields, not padding, and NEVER trust a caller-mutated
	 * tx record in either finish or abort before this full identity check.
	 * A rejected forged handle leaves the original transaction in flight.
	 */
	for (index = 0; index < tx->count; ++index) {
		if (tx->records[index].logical_page !=
				a->active_tx.records[index].logical_page ||
		    tx->records[index].generation !=
				a->active_tx.records[index].generation)
			return 0;
	}
	return 1;
}

static void sv3_forget_active(struct sv3_authority *a, int published)
{
	if (!published)
		a->abandoned_blocks += a->active_blocks;
	else
		a->committed_blocks += a->active_blocks;
	a->in_flight = 0;
	a->active_sequence = 0;
	a->active_blocks = 0;
	a->active_count = 0;
	memset(&a->active_tx, 0, sizeof(a->active_tx));
}

int sv3_abort(struct sv3_authority *a, const struct sv3_tx *tx)
{
	if (!sv3_is_active(a, tx))
		return -ESTALE;
	sv3_forget_active(a, 0);
	return 0;
}

static sv3_u32 sv3_disk_sequence(const sv3_u8 *bytes)
{
	/* Sequence bytes 8-11, always LE, no unaligned u32 access. */
	return (sv3_u32)bytes[8] | ((sv3_u32)bytes[9] << 8) |
		((sv3_u32)bytes[10] << 16) | ((sv3_u32)bytes[11] << 24);
}

int sv3_finish(struct sv3_authority *a, const struct sv3_tx *tx,
	       const void *extent, sv3_u32 bytes_total,
	       sv3_u8 completed_blocks, int io_error)
{
	const sv3_u8 *image = extent;
	sv3_u8 index;
	int error = 0;

	if (!sv3_is_active(a, tx))
		return -ESTALE;
	if (io_error || completed_blocks != tx->extent_blocks ||
	    bytes_total != (sv3_u32)tx->extent_blocks * SV3_BLOCK_BYTES ||
	    !image) {
		error = io_error < 0 ? io_error : -EIO;
		goto fail;
	}
	error = sv3_validate(image, bytes_total);
	if (error)
		goto fail;
	if (image[7] != tx->count || sv3_disk_sequence(image) != tx->sequence) {
		error = -EUCLEAN;
		goto fail;
	}

	/*
	 * Phase 1. All metadata, payload CRC32Cs, generations and old liveness
	 * validated. No map is mutated during this pass.
	 */
	for (index = 0; index < tx->count; ++index) {
		struct sv3_decoded decoded;
		const sv3_u8 *payload;
		const struct sv3_map *old;
		sv3_u32 logical = tx->records[index].logical_page;
		sv3_u8 prior = 0;
		sv3_u8 j;

		error = sv3_lookup(image, bytes_total, index, &decoded, &payload);
		if (error)
			goto fail;
		if (logical >= a->logical_pages ||
		    decoded.logical_page != logical ||
		    decoded.generation != tx->records[index].generation) {
			error = -EUCLEAN;
			goto fail;
		}
		old = &a->maps[logical];
		if (old->generation == ~(sv3_u32)0 ||
		    old->generation + 1U != decoded.generation) {
			error = -ESTALE;
			goto fail;
		}
		if (!old->valid)
			continue;
		if (old->start_block >= a->physical_blocks ||
		    !sv3_legal_class(old->extent_blocks) ||
		    a->extent_classes[old->start_block] != old->extent_blocks) {
			error = -EUCLEAN;
			goto fail;
		}
		for (j = 0; j <= index; ++j) {
			const struct sv3_map *earlier_old =
				&a->maps[tx->records[j].logical_page];

			if (earlier_old->valid &&
			    earlier_old->start_block == old->start_block)
				prior++;
		}
		if (a->live_records[old->start_block] < prior) {
			error = -EUCLEAN;
			goto fail;
		}
	}
	if (a->live_records[tx->start_block] ||
	    a->extent_classes[tx->start_block]) {
		error = -EUCLEAN;
		goto fail;
	}

	/*
	 * Phase 2. The single ordered worker owns ALL mapping publication.
	 * A failed physical write or a malformed sibling leaves old authority
	 * untouched, even when an earlier block completed successfully.
	 */
	a->live_records[tx->start_block] = tx->count;
	a->extent_classes[tx->start_block] = tx->extent_blocks;
	for (index = 0; index < tx->count; ++index) {
		sv3_u32 logical = tx->records[index].logical_page;
		struct sv3_map *entry = &a->maps[logical];

		if (entry->valid)
			a->live_records[entry->start_block]--;
		*entry = (struct sv3_map){
			.start_block = tx->start_block,
			.sequence = tx->sequence,
			.generation = tx->records[index].generation,
			.extent_blocks = tx->extent_blocks,
			.record_index = index,
			.valid = 1,
		};
	}
	sv3_forget_active(a, 1);
	return 0;
fail:
	sv3_forget_active(a, 0);
	return error;
}

int sv3_read_authoritative(const struct sv3_authority *a,
			   sv3_u32 logical_page, const struct sv3_map *observed,
			   const void *extent, sv3_u32 bytes_total,
			   struct sv3_decoded *decoded,
			   const sv3_u8 **payload)
{
	const struct sv3_map *current;
	int error;

	if (!a || !observed || !decoded || !payload ||
	    logical_page >= a->logical_pages)
		return -EINVAL;
	current = &a->maps[logical_page];
	if (!current->valid || !observed->valid ||
	    current->start_block != observed->start_block ||
	    current->sequence != observed->sequence ||
	    current->generation != observed->generation ||
	    current->extent_blocks != observed->extent_blocks ||
	    current->record_index != observed->record_index)
		return -ESTALE;
	if (!extent ||
	    bytes_total != (sv3_u32)current->extent_blocks * SV3_BLOCK_BYTES)
		return -EINVAL;
	error = sv3_lookup(extent, bytes_total, current->record_index,
			   decoded, payload);
	if (error)
		return error;
	if (decoded->logical_page != logical_page ||
	    decoded->generation != current->generation ||
	    sv3_disk_sequence(extent) != current->sequence) {
		*decoded = (struct sv3_decoded){ 0 };
		*payload = NULL;
		return -EUCLEAN;
	}
	return 0;
}
