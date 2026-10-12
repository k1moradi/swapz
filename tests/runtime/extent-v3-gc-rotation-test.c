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
#include "../../kernel/extent-v3/authority.h"
#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "%s:%d failed: %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)

#define NPHYS (4U * SV3_SEGMENT_BLOCKS)
static struct sv3_authority a;
static struct sv3_map maps[16];
static sv3_u16 live[NPHYS];
static sv3_u8 classes[NPHYS];
static sv3_u8 roles[4];
static sv3_u8 raw[SV3_BLOCK_BYTES];

static int setup(void)
{
	int error = sv3_authority_init(&a, maps, live, classes, 16, NPHYS);

	if (error)
		return error;
	a.reuse_dead_segments = 1;
	memset(raw, 0xa5, sizeof(raw));
	return sv3_enable_segment_rotation(&a, roles, 4);
}

static int write_raw(sv3_u32 page)
{
	struct sv3_tx tx;
	int error = sv3_stage(&a, &page, 1, 1, &tx);

	if (error)
		return error;
	return sv3_finish_raw(&a, &tx, raw, 1, 0);
}

/* A small exact-authority mock of an owned lower completion. The payload
 * stays byte-identical and the new generation publishes only after 1/1
 * successful completion. The final role swap validates all mapping refs. */
static int relocate_all_live_pages(sv3_u32 victim)
{
	struct sv3_tx tx;
	sv3_u32 page;
	int error;

	error = sv3_gc_begin_rotation(&a, victim);
	if (error)
		return error;
	for (page = 0; page < 16; ++page) {
		if (!maps[page].valid ||
		    maps[page].start_block / SV3_SEGMENT_BLOCKS != victim)
			continue;
		error = sv3_stage(&a, &page, 1, 1, &tx);
		if (error)
			return error;
		error = sv3_finish_raw(&a, &tx, raw, 1, 0);
		if (error)
			return error;
	}
	return sv3_gc_commit_rotation(&a, victim);
}

static int test_three_rotations_and_foreground_progress(void)
{
	unsigned int i, cycle;

	CHECK(setup() == 0);
	CHECK(roles[0] == 1 && roles[1] == 1);
	CHECK(roles[2] == 0 && roles[3] == 0);
	/* Fill foreground segment 0; retain one live record. */
	for (i = 0; i < SV3_SEGMENT_BLOCKS; ++i)
		CHECK(write_raw(0) == 0);
	CHECK(a.open_segment == 0 && a.next_block == 256);
	/* Fill segment 1; retain one live record. */
	for (i = 0; i < SV3_SEGMENT_BLOCKS; ++i)
		CHECK(write_raw(1) == 0);
	CHECK(a.open_segment == 1 && a.next_block == 512);
	CHECK(a.maps[0].start_block == 255 && a.maps[1].start_block == 511);
	CHECK(write_raw(2) == -ENOSPC);
	/* GC cannot pick a reserved victim: src must be eligible foreground. */
	CHECK(sv3_gc_begin_rotation(&a, 2) == -EINVAL);
	CHECK(relocate_all_live_pages(0) == 0);
	CHECK(roles[0] == 0 && roles[2] == 1);
	CHECK(a.open_segment == 2 && a.maps[0].start_block == 512);
	CHECK(a.next_block == 513);
	/* Foreground must use the GC destination's remaining space rather
	 * than restoring cursor to the previously exhausted segment 1. */
	CHECK(write_raw(2) == 0 && a.maps[2].start_block == 513);
	/* First free reserve is now the *old* foreground victim 0. */
	CHECK(relocate_all_live_pages(1) == 0);
	CHECK(roles[1] == 0 && roles[0] == 1);
	CHECK(a.open_segment == 0 && a.maps[1].start_block == 0);
	CHECK(write_raw(3) == 0 && a.maps[3].start_block == 1);
	/* Rotate a third time, now from the formerly reserved segment2.
	 * Neither reserve segment3 nor another reserve may be a victim. */
	CHECK(relocate_all_live_pages(2) == 0);
	CHECK(roles[2] == 0 && roles[1] == 1);
	CHECK(a.open_segment == 1 && a.maps[0].start_block == 256);
	CHECK(a.maps[1].valid && a.maps[1].start_block == 0);
	CHECK(a.maps[2].valid && a.maps[2].start_block == 257); /* moved with victim 2 */
	CHECK(a.maps[3].valid && a.maps[3].start_block == 1);
	for (cycle = 0; cycle < 4; ++cycle) {
		CHECK(write_raw(4) == 0);
		CHECK(maps[4].valid && maps[4].raw_crc32c ==
		      sv3_crc32c_bytes(raw, sizeof(raw)));
	}
	CHECK(roles[3] == 0); /* permanent second reserve was untouched */
	return 0;
}

static int test_failed_handoff_does_not_change_roles(void)
{
	struct sv3_tx tx;
	sv3_u32 page = 1;
	sv3_u32 saved;

	CHECK(setup() == 0);
	for (unsigned int i = 0; i < SV3_SEGMENT_BLOCKS; ++i)
		CHECK(write_raw(0) == 0);
	CHECK(write_raw(1) == 0);
	saved = maps[0].start_block;
	CHECK(sv3_gc_begin_rotation(&a, 1) == -EINVAL); /* OPEN protected */
	/* Normal writes never enter segments2/3 when they are reserved. */
	CHECK(a.next_block == 257);
	/* Start GC of foreground segment0 but do NOT relocate its live
	 * page0. Even a staged/aborted reserve write cannot permit the
	 * source victim to become foreground reusable. */
	CHECK(sv3_gc_begin_rotation(&a, 0) == 0);
	CHECK(sv3_stage(&a, &page, 1, 1, &tx) == 0);
	CHECK(tx.start_block >= 512 && tx.start_block < 768);
	CHECK(sv3_abort(&a, &tx) == 0);
	CHECK(sv3_gc_commit_rotation(&a, 0) == -EUCLEAN);
	CHECK(roles[0] == 1 && roles[2] == 0);
	CHECK(maps[0].start_block == saved && live[saved]);
	return 0;
}

/*
 * Match Codex's exact 32MiB / 1024-page geometry: 30 foreground segments
 * followed by two initially free reserve segments. Repeat eight successful
 * foreground evacuations; a static reserve-tail design fails by relocating
 * live records between segment30 and segment31 without freeing foreground.
 */
static struct sv3_authority large_a;
static struct sv3_map large_maps[1024];
static sv3_u16 large_live[32U * SV3_SEGMENT_BLOCKS];
static sv3_u8 large_classes[32U * SV3_SEGMENT_BLOCKS];
static sv3_u8 large_roles[32];

static int large_write(sv3_u32 page)
{
	struct sv3_tx tx;
	int error = sv3_stage(&large_a, &page, 1, 1, &tx);

	if (error)
		return error;
	return sv3_finish_raw(&large_a, &tx, raw, 1, 0);
}

static int large_relocate(sv3_u32 segment)
{
	struct sv3_tx tx;
	sv3_u32 page;
	int error = sv3_gc_begin_rotation(&large_a, segment);

	if (error)
		return error;
	for (page = 0; page < 1024; ++page) {
		if (!large_maps[page].valid ||
		    large_maps[page].start_block / SV3_SEGMENT_BLOCKS != segment)
			continue;
		error = sv3_stage(&large_a, &page, 1, 1, &tx);
		if (error)
			return error;
		error = sv3_finish_raw(&large_a, &tx, raw, 1, 0);
		if (error)
			return error;
	}
	return sv3_gc_commit_rotation(&large_a, segment);
}

static int test_exact_32mib_foreground_progress(void)
{
	sv3_u32 segment, i, rotation, reserve_count;

	CHECK(sv3_authority_init(&large_a, large_maps, large_live,
				large_classes, 1024,
				32U * SV3_SEGMENT_BLOCKS) == 0);
	large_a.reuse_dead_segments = 1;
	CHECK(sv3_enable_segment_rotation(&large_a, large_roles, 32) == 0);
	for (segment = 0; segment < 30; ++segment)
		for (i = 0; i < SV3_SEGMENT_BLOCKS; ++i)
			CHECK(large_write(segment) == 0);
	CHECK(large_a.next_block == 30U * SV3_SEGMENT_BLOCKS);
	CHECK(large_write(100) == -ENOSPC);
	for (rotation = 0; rotation < 8; ++rotation) {
		sv3_u32 dest;

		/* Every old foreground victim has one correct live raw page. */
		CHECK(large_relocate(rotation) == 0);
		dest = large_maps[rotation].start_block /
		       SV3_SEGMENT_BLOCKS;
		CHECK(dest < 32 && large_roles[dest] == 1);
		CHECK(large_roles[rotation] == 0);
		CHECK(large_a.open_segment == dest);
		CHECK(large_write(100 + rotation) == 0);
		CHECK(large_maps[100 + rotation].start_block /
		      SV3_SEGMENT_BLOCKS == dest);
		for (i = 0; i <= rotation; ++i)
			CHECK(large_maps[i].valid &&
			      large_live[large_maps[i].start_block] &&
			      large_maps[i].raw_crc32c ==
			      sv3_crc32c_bytes(raw, sizeof(raw)));
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

static int test_empty_gc_destination_cannot_rotate_roles(void)
{
	CHECK(setup() == 0);
	/* Calling GC on an otherwise empty foreground source is invalid
	 * as a progress action: do not turn an untouched empty reserve into
	 * foreground without actually relocating any survivor. */
	CHECK(sv3_gc_begin_rotation(&a, 0) == 0);
	CHECK(a.gc_destination == 2 && a.next_block == 512);
	CHECK(sv3_gc_commit_rotation(&a, 0) == -EUCLEAN);
	CHECK(roles[0] == 1 && roles[2] == 0);
	return 0;
}

int main(void)
{
	int passed = 0;

	CHECK(test_three_rotations_and_foreground_progress() == 0); passed++;
	CHECK(test_failed_handoff_does_not_change_roles() == 0); passed++;
	CHECK(test_exact_32mib_foreground_progress() == 0); passed++;
	CHECK(test_empty_gc_destination_cannot_rotate_roles() == 0); passed++;
	printf("SV3_ROTATING_GC_TESTS_PASS=%d\n", passed);
	return 0;
}
