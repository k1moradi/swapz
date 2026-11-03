// SPDX-License-Identifier: GPL-2.0-only
/*
 * Exact production V3 authority C: reproduce the old 32-segment
 * "GC moves reserve30 -> reserve31 -> foreground ENOSPC" failure.
 *
 * Here four 1MiB segments suffice to exercise the exact invariant:
 * foreground [0,1], reserve [2,3]; evacuate foreground 0 to reserve 2,
 * then foreground 1 to reserve 0, and rotate repeatedly WITHOUT
 * consuming a permanent reserve or publishing stale/missing mappings.
 */
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include "authority.h"
#include "gc-cost.h"
#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "%s:%d failed: %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)

#define NPHYS (4U * SWAPZ_SEGMENT_BLOCKS)
static struct swapz_authority a;
static struct swapz_map maps[16];
static swapz_u16 live[NPHYS];
static swapz_u8 classes[NPHYS];
static swapz_u8 roles[4];
static swapz_u8 raw[SWAPZ_BLOCK_BYTES];

static int near_full_recycle_error;
static unsigned int near_full_recycle_calls;
static swapz_u32 near_full_recycle_segment;

static int near_full_recycle(void *opaque, swapz_u32 segment)
{
	(void)opaque;
	near_full_recycle_calls++;
	near_full_recycle_segment = segment;
	return near_full_recycle_error;
}

static void near_full_fill_raw(swapz_u32 logical, swapz_u32 version)
{
	swapz_u32 offset;

	for (offset = 0; offset < SWAPZ_BLOCK_BYTES; ++offset)
		raw[offset] = (swapz_u8)(offset * 29U + logical * 37U +
					 version * 101U);
	raw[0] = (swapz_u8)logical;
	raw[1] = (swapz_u8)(logical >> 8);
	raw[2] = (swapz_u8)version;
	raw[3] = (swapz_u8)(version >> 8);
}

static int near_full_finish_raw(struct swapz_authority *authority,
				struct swapz_tx *tx,
				swapz_u32 logical, swapz_u32 version)
{
	near_full_fill_raw(logical, version);
	return swapz_finish_raw(authority, tx, raw, 1, 0);
}

static swapz_u32 near_full_raw_crc(swapz_u32 logical, swapz_u32 version)
{
	near_full_fill_raw(logical, version);
	return swapz_crc32c_bytes(raw, SWAPZ_BLOCK_BYTES);
}

static int setup(void)
{
	int error = swapz_authority_init(&a, maps, live, classes, 16, NPHYS);

	if (error)
		return error;
	a.reuse_dead_segments = 1;
	memset(raw, 0xa5, sizeof(raw));
	return swapz_enable_segment_rotation(&a, roles, 4);
}

static int write_raw(swapz_u32 page)
{
	struct swapz_tx tx;
	int error = swapz_stage(&a, &page, 1, 1, &tx);

	if (error)
		return error;
	return swapz_finish_raw(&a, &tx, raw, 1, 0);
}

/* A small exact-authority mock of an owned lower completion. The payload
 * stays byte-identical and the new generation publishes only after 1/1
 * successful completion. The final role swap validates all mapping refs. */
static int relocate_all_live_pages(swapz_u32 victim)
{
	struct swapz_tx tx;
	swapz_u32 page;
	int error;

	error = swapz_gc_begin_rotation(&a, victim);
	if (error)
		return error;
	for (page = 0; page < 16; ++page) {
		if (!maps[page].valid ||
		    maps[page].start_block / SWAPZ_SEGMENT_BLOCKS != victim)
			continue;
		error = swapz_stage(&a, &page, 1, 1, &tx);
		if (error)
			return error;
		error = swapz_finish_raw(&a, &tx, raw, 1, 0);
		if (error)
			return error;
	}
	return swapz_gc_commit_rotation(&a, victim);
}

static int test_three_rotations_and_foreground_progress(void)
{
	unsigned int i, cycle;

	CHECK(setup() == 0);
	CHECK(roles[0] == 1 && roles[1] == 1);
	CHECK(roles[2] == 0 && roles[3] == 0);
	/* Fill foreground segment 0; retain one live record. */
	for (i = 0; i < SWAPZ_SEGMENT_BLOCKS; ++i)
		CHECK(write_raw(0) == 0);
	CHECK(a.open_segment == 0 && a.next_block == 256);
	/* Fill segment 1; retain one live record. */
	for (i = 0; i < SWAPZ_SEGMENT_BLOCKS; ++i)
		CHECK(write_raw(1) == 0);
	CHECK(a.open_segment == 1 && a.next_block == 512);
	CHECK(a.maps[0].start_block == 255 && a.maps[1].start_block == 511);
	CHECK(write_raw(2) == -ENOSPC);
	/* GC cannot pick a reserved victim: src must be eligible foreground. */
	CHECK(swapz_gc_begin_rotation(&a, 2) == -EINVAL);
	CHECK(relocate_all_live_pages(0) == 0);
	CHECK(a.next_segment_probe == 3);
	CHECK(roles[0] == 0 && roles[2] == 1);
	CHECK(a.open_segment == 2 && a.maps[0].start_block == 512);
	CHECK(a.next_block == 513);
	/* Foreground must use the GC destination's remaining space rather
	 * than restoring cursor to the previously exhausted segment 1. */
	CHECK(write_raw(2) == 0 && a.maps[2].start_block == 513);
	/* Preserve the circular probe: after destination2, the untouched
	 * reserve3 is selected before wrapping to the evacuated victim0. */
	CHECK(relocate_all_live_pages(1) == 0);
	CHECK(a.next_segment_probe == 0);
	CHECK(roles[1] == 0 && roles[3] == 1);
	CHECK(a.open_segment == 3 && a.maps[1].start_block == 768);
	CHECK(write_raw(3) == 0 && a.maps[3].start_block == 769);
	/* Rotate a third time from the formerly reserved segment2. The probe
	 * now wraps to reserve0; reserve1 becomes the newly evacuated spare. */
	CHECK(relocate_all_live_pages(2) == 0);
	CHECK(roles[2] == 0 && roles[0] == 1);
	CHECK(a.open_segment == 0 && a.maps[0].start_block == 0);
	CHECK(a.maps[1].valid && a.maps[1].start_block == 768);
	CHECK(a.maps[2].valid && a.maps[2].start_block == 1); /* moved with victim 2 */
	CHECK(a.maps[3].valid && a.maps[3].start_block == 769);
	CHECK(a.next_segment_probe == 1);
	for (cycle = 0; cycle < 4; ++cycle) {
		CHECK(write_raw(4) == 0);
		CHECK(maps[4].valid && maps[4].raw_crc32c ==
		      swapz_crc32c_bytes(raw, sizeof(raw)));
	}
	CHECK(roles[1] == 0 && roles[2] == 0);
	return 0;
}

static int test_failed_handoff_does_not_change_roles(void)
{
	struct swapz_tx tx;
	swapz_u32 page = 1;
	swapz_u32 saved, failed_block, generation;

	CHECK(setup() == 0);
	for (unsigned int i = 0; i < SWAPZ_SEGMENT_BLOCKS; ++i)
		CHECK(write_raw(0) == 0);
	CHECK(write_raw(1) == 0);
	saved = maps[0].start_block;
	generation = maps[0].generation;
	CHECK(swapz_gc_begin_rotation(&a, 1) == -EINVAL); /* OPEN protected */
	/* Normal writes never enter segments2/3 when they are reserved. */
	CHECK(a.next_block == 257);
	/* Start GC of foreground segment0 and model an uncertain failed lower
	 * RAW write. Its reservation remains quarantined, while the same active
	 * rotation must be able to resume after the transient failure. */
	CHECK(swapz_gc_begin_rotation(&a, 0) == 0);
	CHECK(swapz_stage(&a, &page, 1, 1, &tx) == 0);
	CHECK(tx.start_block >= 512 && tx.start_block < 768);
	failed_block = tx.start_block;
	CHECK(swapz_abort(&a, &tx) == 0);
	CHECK(swapz_gc_commit_rotation(&a, 0) == -EUCLEAN);
	CHECK(roles[0] == 1 && roles[2] == 0);
	CHECK(maps[0].start_block == saved && live[saved]);
	CHECK(a.gc_allocation && a.gc_destination == 2);

	page = 0;
	CHECK(swapz_stage(&a, &page, 1, 1, &tx) == 0);
	CHECK(tx.start_block == failed_block + 1U);
	CHECK(swapz_finish_raw(&a, &tx, raw, 1, 0) == 0);
	CHECK(maps[0].generation == generation + 1U);
	CHECK(!live[failed_block] && live[maps[0].start_block]);
	CHECK(swapz_gc_commit_rotation(&a, 0) == 0);
	CHECK(roles[0] == 0 && roles[2] == 1);
	for (page = 0; page < SWAPZ_SEGMENT_BLOCKS; ++page)
		CHECK(!live[page]);
	return 0;
}


/*
 * Match Codex's exact 32MiB / 1024-page geometry: 30 foreground segments
 * followed by two initially free reserve segments. Repeat eight successful
 * foreground evacuations; a static reserve-tail design fails by relocating
 * live records between segment30 and segment31 without freeing foreground.
 */
static struct swapz_authority large_a;
static struct swapz_map large_maps[1024];
static swapz_u16 large_live[32U * SWAPZ_SEGMENT_BLOCKS];
static swapz_u8 large_classes[32U * SWAPZ_SEGMENT_BLOCKS];
static swapz_u8 large_roles[32];

static int large_write(swapz_u32 page)
{
	struct swapz_tx tx;
	int error = swapz_stage(&large_a, &page, 1, 1, &tx);

	if (error)
		return error;
	return swapz_finish_raw(&large_a, &tx, raw, 1, 0);
}

static int large_relocate(swapz_u32 segment)
{
	struct swapz_tx tx;
	swapz_u32 page;
	int error = swapz_gc_begin_rotation(&large_a, segment);

	if (error)
		return error;
	for (page = 0; page < 1024; ++page) {
		if (!large_maps[page].valid ||
		    large_maps[page].start_block / SWAPZ_SEGMENT_BLOCKS != segment)
			continue;
		error = swapz_stage(&large_a, &page, 1, 1, &tx);
		if (error)
			return error;
		error = swapz_finish_raw(&large_a, &tx, raw, 1, 0);
		if (error)
			return error;
	}
	return swapz_gc_commit_rotation(&large_a, segment);
}

static int test_exact_32mib_foreground_progress(void)
{
	swapz_u32 segment, i, rotation, reserve_count;

	CHECK(swapz_authority_init(&large_a, large_maps, large_live,
				large_classes, 1024,
				32U * SWAPZ_SEGMENT_BLOCKS) == 0);
	large_a.reuse_dead_segments = 1;
	CHECK(swapz_enable_segment_rotation(&large_a, large_roles, 32) == 0);
	for (segment = 0; segment < 30; ++segment)
		for (i = 0; i < SWAPZ_SEGMENT_BLOCKS; ++i)
			CHECK(large_write(segment) == 0);
	CHECK(large_a.next_block == 30U * SWAPZ_SEGMENT_BLOCKS);
	CHECK(large_write(100) == -ENOSPC);
	for (rotation = 0; rotation < 8; ++rotation) {
		swapz_u32 dest;

		/* Every old foreground victim has one correct live raw page. */
		CHECK(large_relocate(rotation) == 0);
		dest = large_maps[rotation].start_block /
		       SWAPZ_SEGMENT_BLOCKS;
		CHECK(dest < 32 && large_roles[dest] == 1);
		CHECK(large_roles[rotation] == 0);
		CHECK(large_a.open_segment == dest);
		CHECK(large_write(100 + rotation) == 0);
		CHECK(large_maps[100 + rotation].start_block /
		      SWAPZ_SEGMENT_BLOCKS == dest);
		for (i = 0; i <= rotation; ++i)
			CHECK(large_maps[i].valid &&
			      large_live[large_maps[i].start_block] &&
			      large_maps[i].raw_crc32c ==
			      swapz_crc32c_bytes(raw, sizeof(raw)));
		reserve_count = 0;
		for (i = 0; i < 32; ++i)
			if (!large_roles[i])
				reserve_count++;
		CHECK(reserve_count == 2);
	}
	/* Two reserved capacity segments are preserved after every rotation.
	 * No foreground ENOSPC retry was needed for new pages 100..107. */
	return 0;
}

/*
 * All 256 source pages are LIVE. Copying the victim into one reserve
 * consumes all 256 destination blocks; source is now fully evacuated.
 * A GC commit must still refuse the role handoff: it creates ZERO
 * foreground-writable blocks and falsely promises allocation progress.
 */
static int test_full_destination_is_not_gc_progress(void)
{
	swapz_u32 page;

	CHECK(swapz_authority_init(&large_a, large_maps, large_live,
				large_classes, 1024,
				32U * SWAPZ_SEGMENT_BLOCKS) == 0);
	large_a.reuse_dead_segments = 1;
	CHECK(swapz_enable_segment_rotation(&large_a, large_roles, 32) == 0);
	for (page = 0; page < SWAPZ_SEGMENT_BLOCKS; ++page)
		CHECK(large_write(page) == 0);
	/* Keep the foreground OPEN segment1 while evacuating segment0. */
	CHECK(large_write(800) == 0);
	CHECK(large_a.open_segment == 1);
	CHECK(swapz_gc_begin_rotation(&large_a, 0) == 0);
	CHECK(large_a.gc_destination == 30);
	for (page = 0; page < SWAPZ_SEGMENT_BLOCKS; ++page)
		CHECK(large_write(page) == 0);
	CHECK(large_a.next_block == 31U * SWAPZ_SEGMENT_BLOCKS);
	CHECK(swapz_gc_commit_rotation(&large_a, 0) == -ENOSPC);
	CHECK(large_roles[0] == 1 && large_roles[30] == 0 &&
	      large_roles[31] == 0);
	for (page = 0; page < SWAPZ_SEGMENT_BLOCKS; ++page)
		CHECK(large_maps[page].valid &&
		      large_maps[page].start_block ==
			      30U * SWAPZ_SEGMENT_BLOCKS + page &&
		      large_live[large_maps[page].start_block] == 1);
	return 0;
}

static int test_empty_gc_destination_cannot_rotate_roles(void)
{
	CHECK(setup() == 0);
	/* Calling GC on an otherwise empty foreground source is invalid
	 * as a progress action: do not turn an untouched empty reserve into
	 * foreground without actually relocating any survivor. */
	CHECK(swapz_gc_begin_rotation(&a, 0) == 0);
	CHECK(a.gc_destination == 2 && a.next_block == 512);
	CHECK(swapz_gc_commit_rotation(&a, 0) == -EUCLEAN);
	CHECK(roles[0] == 1 && roles[2] == 0);
	return 0;
}

static int test_gc_cannot_spill_into_second_reserve(void)
{
	struct swapz_tx tx;
	swapz_u32 page = 7;
	unsigned int i;

	CHECK(setup() == 0);
	/* Segment0 remains live while foreground moves to segment1. */
	for (i = 0; i < SWAPZ_SEGMENT_BLOCKS; ++i)
		CHECK(write_raw(0) == 0);
	CHECK(write_raw(1) == 0);
	CHECK(swapz_gc_begin_rotation(&a, 0) == 0);
	CHECK(a.gc_destination == 2);
	/* Deliberately consume the WHOLE single GC destination without
	 * evacuating the source page0. An unsafe collector would spill
	 * into reserve3, then claim false foreground reclaim progress. */
	for (i = 0; i < SWAPZ_SEGMENT_BLOCKS; ++i)
		CHECK(write_raw(page) == 0);
	CHECK(a.next_block == 768 && a.open_segment == 2);
	CHECK(swapz_stage(&a, &page, 1, 1, &tx) == -ENOSPC);
	/* A full destination now fails on lack of foreground capacity,
	 * before the remaining-source-mappings validation. Both reject. */
	CHECK(swapz_gc_commit_rotation(&a, 0) == -ENOSPC);
	CHECK(roles[0] == 1 && roles[1] == 1);
	CHECK(roles[2] == 0 && roles[3] == 0);
	CHECK(maps[0].valid && maps[0].start_block == 255);
	CHECK(live[255] == 1 && maps[0].raw_crc32c ==
	      swapz_crc32c_bytes(raw, SWAPZ_BLOCK_BYTES));
	CHECK(a.gc_destination == 2); /* fail-closed, not committed */
	return 0;
}

/*
 * Worst-case recoverable RAW boundary: 255 authoritative survivors leave one
 * destination block of slack. One uncertain lower reservation consumes that
 * slack, so the first destination becomes full exactly as the original victim
 * reaches zero liveness. Recovery must not publish the full destination as
 * foreground progress. It instead rolls that verified-dead victim forward as
 * the next reserve destination, evacuates the full intermediate segment, and
 * restores at least one successful foreground overwrite.
 */
static int test_one_uncertain_block_rolls_forward_raw_recovery_headroom(void)
{
	static struct swapz_authority near_full_authority;
	static struct swapz_map near_full_maps[SWAPZ_SEGMENT_BLOCKS + 1U];
	static swapz_u16 near_full_liveness[5U * SWAPZ_SEGMENT_BLOCKS];
	static swapz_u8 near_full_classes[5U * SWAPZ_SEGMENT_BLOCKS];
	static swapz_u8 near_full_roles[5];
	static swapz_u32 near_full_mapped_pages[5];
	static swapz_u32 near_full_versions[SWAPZ_SEGMENT_BLOCKS];
	const swapz_u32 survivors = SWAPZ_SEGMENT_BLOCKS - 1U;
	struct swapz_tx tx;
	swapz_u32 page, block;

	memset(near_full_versions, 0, sizeof(near_full_versions));
	CHECK(swapz_authority_init(&near_full_authority, near_full_maps,
				  near_full_liveness, near_full_classes,
				  SWAPZ_SEGMENT_BLOCKS + 1U,
				  5U * SWAPZ_SEGMENT_BLOCKS) == 0);
	near_full_authority.reuse_dead_segments = 1;
	CHECK(swapz_enable_segment_rotation(&near_full_authority,
					    near_full_roles, 5) == 0);
	CHECK(swapz_enable_segment_mapping_counts(
		      &near_full_authority, near_full_mapped_pages, 5) == 0);
	near_full_recycle_error = 0;
	near_full_recycle_calls = 0;
	near_full_recycle_segment = ~(swapz_u32)0;
	near_full_authority.dead_segment_recycle = near_full_recycle;
	near_full_authority.dead_segment_recycle_opaque = NULL;
	CHECK(swapz_gc_candidate_can_free_block(
		      survivors * SWAPZ_BLOCK_BYTES,
		      (swapz_u16)survivors));

	for (page = 0; page < survivors; ++page) {
		CHECK(swapz_stage(&near_full_authority, &page, 1, 1, &tx) == 0);
		near_full_versions[page] = 1U;
		CHECK(near_full_finish_raw(&near_full_authority, &tx, page,
					   near_full_versions[page]) == 0);
	}
	page = 0;
	CHECK(swapz_stage(&near_full_authority, &page, 1, 1, &tx) == 0);
	near_full_versions[page]++;
	CHECK(near_full_finish_raw(&near_full_authority, &tx, page,
				   near_full_versions[page]) == 0);
	page = survivors;
	CHECK(swapz_stage(&near_full_authority, &page, 1, 1, &tx) == 0);
	near_full_versions[page] = 1U;
	CHECK(near_full_finish_raw(&near_full_authority, &tx, page,
				   near_full_versions[page]) == 0);
	CHECK(near_full_authority.open_segment == 1U);
	CHECK(swapz_gc_begin_rotation(&near_full_authority, 0) == 0);
	CHECK(near_full_authority.gc_destination == 3U);

	page = 0;
	CHECK(swapz_stage(&near_full_authority, &page, 1, 1, &tx) == 0);
	CHECK(near_full_finish_raw(&near_full_authority, &tx, page,
				   near_full_versions[page]) == 0);
	page = 1;
	CHECK(swapz_stage(&near_full_authority, &page, 1, 1, &tx) == 0);
	CHECK(tx.start_block == 3U * SWAPZ_SEGMENT_BLOCKS + 1U);
	CHECK(swapz_abort(&near_full_authority, &tx) == 0);

	for (page = 1; page < survivors; ++page) {
		CHECK(swapz_stage(&near_full_authority, &page, 1, 1, &tx) == 0);
		CHECK(near_full_finish_raw(&near_full_authority, &tx, page,
					   near_full_versions[page]) == 0);
	}
	CHECK(near_full_authority.next_block == 4U * SWAPZ_SEGMENT_BLOCKS);
	CHECK(swapz_gc_commit_rotation(&near_full_authority, 0) == -ENOSPC);
	CHECK(near_full_authority.gc_allocation &&
	      near_full_authority.gc_forbidden_victim == 0U &&
	      near_full_authority.gc_destination == 3U);
	for (block = 0; block < SWAPZ_SEGMENT_BLOCKS; ++block)
		CHECK(!near_full_liveness[block]);
	CHECK(near_full_mapped_pages[0] == 0U);

	/*
	 * Roll-forward is allowed to reuse the evacuated victim only after three
	 * independent views agree it is dead. A contradictory map, cached mapped
	 * count, or physical liveness record must fail before the recycle hook and
	 * without changing the authenticated recovery state.
	 */
	{
		struct swapz_map saved_map = near_full_maps[survivors];

		near_full_maps[survivors].start_block = 0U;
		CHECK(swapz_gc_roll_forward_rotation(
			      &near_full_authority, 3U) == -EUCLEAN);
		CHECK(near_full_recycle_calls == 0U);
		CHECK(near_full_authority.gc_forbidden_victim == 0U &&
		      near_full_authority.gc_destination == 3U &&
		      near_full_authority.open_segment == 3U &&
		      near_full_authority.next_block ==
			      4U * SWAPZ_SEGMENT_BLOCKS);
		CHECK(near_full_roles[0] == 1U && near_full_roles[3] == 0U);
		near_full_maps[survivors] = saved_map;
	}
	near_full_mapped_pages[0] = 1U;
	CHECK(swapz_gc_roll_forward_rotation(
		      &near_full_authority, 3U) == -EUCLEAN);
	CHECK(near_full_recycle_calls == 0U);
	CHECK(near_full_authority.gc_forbidden_victim == 0U &&
	      near_full_authority.gc_destination == 3U &&
	      near_full_authority.open_segment == 3U &&
	      near_full_authority.next_block == 4U * SWAPZ_SEGMENT_BLOCKS);
	CHECK(near_full_roles[0] == 1U && near_full_roles[3] == 0U);
	near_full_mapped_pages[0] = 0U;

	near_full_liveness[0] = 1U;
	CHECK(swapz_gc_roll_forward_rotation(
		      &near_full_authority, 3U) == -EUCLEAN);
	CHECK(near_full_recycle_calls == 0U);
	CHECK(near_full_authority.gc_forbidden_victim == 0U &&
	      near_full_authority.gc_destination == 3U &&
	      near_full_authority.open_segment == 3U &&
	      near_full_authority.next_block == 4U * SWAPZ_SEGMENT_BLOCKS);
	CHECK(near_full_roles[0] == 1U && near_full_roles[3] == 0U);
	near_full_liveness[0] = 0U;

	/* A recycle failure is externally fallible but must be state-atomic. */
	near_full_recycle_error = -EIO;
	CHECK(swapz_gc_roll_forward_rotation(
		      &near_full_authority, 3U) == -EIO);
	CHECK(near_full_recycle_calls == 1U &&
	      near_full_recycle_segment == 0U);
	CHECK(near_full_authority.recycled_dead_segments == 0U);
	CHECK(near_full_authority.gc_forbidden_victim == 0U &&
	      near_full_authority.gc_destination == 3U &&
	      near_full_authority.open_segment == 3U &&
	      near_full_authority.next_block == 4U * SWAPZ_SEGMENT_BLOCKS);
	CHECK(near_full_roles[0] == 1U && near_full_roles[3] == 0U);

	near_full_recycle_error = 0;
	CHECK(swapz_gc_roll_forward_rotation(
		      &near_full_authority, 3U) == 0);
	CHECK(near_full_recycle_calls == 2U &&
	      near_full_recycle_segment == 0U);
	CHECK(near_full_authority.recycled_dead_segments == 1U);
	CHECK(near_full_authority.gc_allocation &&
	      near_full_authority.gc_forbidden_victim == 3U &&
	      near_full_authority.gc_destination == 0U &&
	      near_full_authority.open_segment == 0U &&
	      near_full_authority.next_block == 0U);
	CHECK(near_full_roles[0] == 0U && near_full_roles[1] == 1U &&
	      near_full_roles[2] == 1U && near_full_roles[3] == 1U &&
	      near_full_roles[4] == 0U);

	for (page = 0; page < survivors; ++page) {
		CHECK(near_full_maps[page].valid &&
		      near_full_maps[page].start_block / SWAPZ_SEGMENT_BLOCKS == 3U &&
		      near_full_maps[page].raw_crc32c ==
			      near_full_raw_crc(page, near_full_versions[page]));
		CHECK(swapz_stage(&near_full_authority, &page, 1, 1, &tx) == 0);
		CHECK(near_full_finish_raw(&near_full_authority, &tx, page,
					   near_full_versions[page]) == 0);
	}
	CHECK(near_full_authority.next_block == SWAPZ_SEGMENT_BLOCKS - 1U);
	CHECK(swapz_gc_commit_rotation(&near_full_authority, 3U) == 0);
	CHECK(!near_full_authority.gc_allocation);
	CHECK(near_full_roles[0] == 1U && near_full_roles[1] == 1U &&
	      near_full_roles[2] == 1U && near_full_roles[3] == 0U &&
	      near_full_roles[4] == 0U);

	page = survivors;
	CHECK(swapz_stage(&near_full_authority, &page, 1, 1, &tx) == 0);
	CHECK(tx.start_block == SWAPZ_SEGMENT_BLOCKS - 1U);
	near_full_versions[page]++;
	CHECK(near_full_finish_raw(&near_full_authority, &tx, page,
				   near_full_versions[page]) == 0);

	for (page = 0; page < survivors; ++page) {
		CHECK(near_full_maps[page].valid && near_full_maps[page].raw &&
		      near_full_maps[page].start_block < SWAPZ_SEGMENT_BLOCKS &&
		      near_full_maps[page].raw_crc32c ==
			      near_full_raw_crc(page, near_full_versions[page]) &&
		      near_full_maps[page].generation == (page == 0 ? 4U : 3U));
	}
	CHECK(near_full_maps[survivors].valid &&
	      near_full_maps[survivors].start_block ==
		      SWAPZ_SEGMENT_BLOCKS - 1U &&
	      near_full_maps[survivors].generation == 2U &&
	      near_full_maps[survivors].raw_crc32c ==
		      near_full_raw_crc(survivors,
					near_full_versions[survivors]));
	for (block = 3U * SWAPZ_SEGMENT_BLOCKS;
	     block < 5U * SWAPZ_SEGMENT_BLOCKS; ++block)
		CHECK(!near_full_liveness[block]);
	return 0;
}


/*
 * Multi-block recovery boundary: one block remains in the owned destination
 * while the original victim still has one live page. A 2-block extent cannot
 * fit, but the destination is not numerically full, so full-destination
 * roll-forward is inapplicable. Recovery must claim the other dead reserve
 * before promoting the blocked destination, then finish the same victim.
 */
static int test_roll_forward_rejects_cross_segment_extent(void)
{
	static struct swapz_authority crossing_authority;
	static struct swapz_map crossing_maps[1];
	static swapz_u16 crossing_liveness[5U * SWAPZ_SEGMENT_BLOCKS];
	static swapz_u8 crossing_classes[5U * SWAPZ_SEGMENT_BLOCKS];
	static swapz_u8 crossing_roles[5];
	static swapz_u32 crossing_mapped_pages[5];
	const swapz_u32 victim = 1U;
	const swapz_u32 destination = 3U;
	const swapz_u32 crossing_start = SWAPZ_SEGMENT_BLOCKS - 1U;

	CHECK(swapz_authority_init(&crossing_authority, crossing_maps,
				  crossing_liveness, crossing_classes, 1U,
				  5U * SWAPZ_SEGMENT_BLOCKS) == 0);
	CHECK(swapz_enable_segment_rotation(
		      &crossing_authority, crossing_roles, 5U) == 0);
	CHECK(swapz_enable_segment_mapping_counts(
		      &crossing_authority, crossing_mapped_pages, 5U) == 0);

	/*
	 * Model corrupted authority metadata that normal allocation can never
	 * create: a two-block extent starts in segment0 but overlaps victim1.
	 * The victim's own mapping-count and liveness views remain zero, so a
	 * start-block-only reclaim scan would incorrectly declare it dead.
	 */
	crossing_maps[0] = (struct swapz_map) {
		.start_block = crossing_start,
		.generation = 1U,
		.payload_offset = 0U,
		.payload_length = 16U,
		.record_index = 0U,
		.extent_blocks = 2U,
		.raw = 0U,
		.valid = 1U,
	};
	crossing_liveness[crossing_start] = 1U;
	crossing_classes[crossing_start] = 2U;
	crossing_mapped_pages[0] = 1U;
	CHECK(crossing_mapped_pages[victim] == 0U);
	CHECK(crossing_liveness[victim * SWAPZ_SEGMENT_BLOCKS] == 0U);

	crossing_authority.gc_allocation = 1U;
	crossing_authority.gc_forbidden_open = 2U;
	crossing_authority.gc_forbidden_victim = victim;
	crossing_authority.gc_destination = destination;
	crossing_authority.open_segment = destination;
	crossing_authority.next_block =
		(destination + 1U) * SWAPZ_SEGMENT_BLOCKS;

	CHECK(swapz_gc_roll_forward_rotation(
		      &crossing_authority, destination) == -EUCLEAN);
	CHECK(crossing_authority.gc_allocation &&
	      crossing_authority.gc_forbidden_victim == victim &&
	      crossing_authority.gc_destination == destination &&
	      crossing_authority.open_segment == destination &&
	      crossing_authority.next_block ==
		      (destination + 1U) * SWAPZ_SEGMENT_BLOCKS);
	CHECK(crossing_roles[victim] == 1U &&
	      crossing_roles[destination] == 0U);
	CHECK(crossing_liveness[crossing_start] == 1U &&
	      crossing_classes[crossing_start] == 2U);
	return 0;
}

static int test_nonfull_recovery_tail_advances_destination(void)
{
	static struct swapz_authority tail_authority;
	static struct swapz_map tail_maps[4];
	static swapz_u16 tail_liveness[5U * SWAPZ_SEGMENT_BLOCKS];
	static swapz_u8 tail_classes[5U * SWAPZ_SEGMENT_BLOCKS];
	static swapz_u8 tail_roles[5];
	static swapz_u32 tail_mapped_pages[5];
	struct swapz_tx tx;
	swapz_u32 blocked_destination, replacement_destination;
	swapz_u32 page, block, index;
	const swapz_u32 victim = 0U;

	memset(raw, 0x3c, sizeof(raw));
	CHECK(swapz_authority_init(&tail_authority, tail_maps,
				  tail_liveness, tail_classes, 4U,
				  5U * SWAPZ_SEGMENT_BLOCKS) == 0);
	tail_authority.reuse_dead_segments = 1;
	CHECK(swapz_enable_segment_rotation(
		      &tail_authority, tail_roles, 5U) == 0);
	CHECK(swapz_enable_segment_mapping_counts(
		      &tail_authority, tail_mapped_pages, 5U) == 0);

	/* Leave two authoritative pages in victim0, then move OPEN to segment1. */
	page = 0U;
	for (index = 0; index < SWAPZ_SEGMENT_BLOCKS - 1U; ++index) {
		CHECK(swapz_stage(&tail_authority, &page, 1, 1, &tx) == 0);
		CHECK(swapz_finish_raw(&tail_authority, &tx, raw, 1, 0) == 0);
	}
	page = 1U;
	CHECK(swapz_stage(&tail_authority, &page, 1, 1, &tx) == 0);
	CHECK(swapz_finish_raw(&tail_authority, &tx, raw, 1, 0) == 0);
	page = 2U;
	CHECK(swapz_stage(&tail_authority, &page, 1, 1, &tx) == 0);
	CHECK(swapz_finish_raw(&tail_authority, &tx, raw, 1, 0) == 0);
	CHECK(tail_authority.open_segment == 1U);
	CHECK(tail_mapped_pages[victim] == 2U);

	CHECK(swapz_gc_begin_rotation(&tail_authority, victim) == 0);
	blocked_destination = tail_authority.gc_destination;
	CHECK(blocked_destination == 3U);

	/* Publish page0, then consume only reservation space until one block
	 * remains. Aborted ranges are quarantined by the monotonic cursor. */
	page = 0U;
	CHECK(swapz_stage(&tail_authority, &page, 1, 1, &tx) == 0);
	CHECK(swapz_finish_raw(&tail_authority, &tx, raw, 1, 0) == 0);
	page = 3U;
	while (tail_authority.next_block <
	       (blocked_destination + 1U) * SWAPZ_SEGMENT_BLOCKS - 1U) {
		CHECK(swapz_stage(&tail_authority, &page, 1, 1, &tx) == 0);
		CHECK(swapz_abort(&tail_authority, &tx) == 0);
	}
	CHECK(tail_authority.next_block ==
	      (blocked_destination + 1U) * SWAPZ_SEGMENT_BLOCKS - 1U);
	CHECK(tail_mapped_pages[victim] == 1U);

	/* The remaining victim page models a compressed extent that requires two
	 * blocks. The ordinary allocator cannot spill while gc_destination owns
	 * the current reserve, so this is the non-full -ENOSPC boundary. */
	page = 1U;
	CHECK(swapz_stage(&tail_authority, &page, 1, 2, &tx) == -ENOSPC);
	CHECK(tail_authority.gc_destination == blocked_destination);
	CHECK(!tail_roles[blocked_destination]);

	CHECK(swapz_gc_advance_rotation_destination(
		      &tail_authority, blocked_destination) == 0);
	replacement_destination = tail_authority.gc_destination;
	CHECK(replacement_destination == 4U);
	CHECK(tail_roles[blocked_destination] == 1U);
	CHECK(tail_roles[replacement_destination] == 0U);
	CHECK(tail_authority.gc_forbidden_victim == victim);
	CHECK(tail_authority.open_segment == replacement_destination);
	CHECK(tail_authority.next_block ==
	      replacement_destination * SWAPZ_SEGMENT_BLOCKS);

	/* Finish the same original victim, then prove foreground progress. */
	CHECK(swapz_stage(&tail_authority, &page, 1, 1, &tx) == 0);
	CHECK(swapz_finish_raw(&tail_authority, &tx, raw, 1, 0) == 0);
	CHECK(tail_mapped_pages[victim] == 0U);
	CHECK(swapz_gc_commit_rotation(&tail_authority, victim) == 0);
	CHECK(!tail_authority.gc_allocation);
	CHECK(tail_roles[victim] == 0U);
	CHECK(tail_roles[blocked_destination] == 1U);
	CHECK(tail_roles[replacement_destination] == 1U);

	page = 3U;
	CHECK(swapz_stage(&tail_authority, &page, 1, 1, &tx) == 0);
	CHECK(swapz_finish_raw(&tail_authority, &tx, raw, 1, 0) == 0);
	for (page = 0; page < 4U; ++page)
		CHECK(swapz_verify_raw(&tail_authority, page, raw) == 0);

	/* None of the abandoned tail blocks became authoritative mappings. */
	for (page = 0; page < 4U; ++page)
		CHECK(tail_maps[page].start_block <=
		      blocked_destination * SWAPZ_SEGMENT_BLOCKS ||
		      tail_maps[page].start_block >=
			      replacement_destination * SWAPZ_SEGMENT_BLOCKS);
	for (block = blocked_destination * SWAPZ_SEGMENT_BLOCKS + 1U;
	     block < (blocked_destination + 1U) * SWAPZ_SEGMENT_BLOCKS;
	     ++block)
		CHECK(!tail_liveness[block]);
	return 0;
}

int main(void)
{
	int passed = 0;

	CHECK(test_three_rotations_and_foreground_progress() == 0); passed++;
	CHECK(test_failed_handoff_does_not_change_roles() == 0); passed++;
	CHECK(test_exact_32mib_foreground_progress() == 0); passed++;
	CHECK(test_empty_gc_destination_cannot_rotate_roles() == 0); passed++;
	CHECK(test_gc_cannot_spill_into_second_reserve() == 0); passed++;
	CHECK(test_full_destination_is_not_gc_progress() == 0); passed++;
	CHECK(test_one_uncertain_block_rolls_forward_raw_recovery_headroom() == 0); passed++;
	CHECK(test_roll_forward_rejects_cross_segment_extent() == 0); passed++;
	CHECK(test_nonfull_recovery_tail_advances_destination() == 0); passed++;
	printf("SWAPZ_ROTATING_GC_TESTS_PASS=%d\n", passed);
	return 0;
}
