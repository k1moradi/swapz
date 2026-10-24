// SPDX-License-Identifier: GPL-2.0-only
/*
 * Execute exact V3 kernel authority C in opt-in segment-reuse mode.
 * A still-referenced 4KiB block must NEVER be recycled, including when
 * its live_records count is fault-injected to zero.
 */
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include "authority.h"

#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "%s:%d FAIL: %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)

static struct swapz_authority a;
static struct swapz_map maps[32];
static swapz_u16 live[1280];
static swapz_u8 classes[1280];
static swapz_u8 roles[5];
static swapz_u32 mapped_pages[5];
static swapz_u32 program_counts[5];
static swapz_u32 first_page[5];
static swapz_u32 last_page[5];
static swapz_u32 prev_page[32];
static swapz_u32 next_page[32];
static swapz_u8 bytes[SWAPZ_BLOCK_BYTES];
static swapz_u8 data[100];
static int recycle_hook_calls;
static swapz_u32 recycle_hook_last_segment;
static int recycle_hook_error;

static int recycle_hook(void *opaque, swapz_u32 segment)
{
	struct swapz_authority *authority = opaque;
	swapz_u32 block;

	CHECK(authority == &a);
	CHECK(segment < 3);
	for (block = segment * SWAPZ_SEGMENT_BLOCKS;
	     block < (segment + 1U) * SWAPZ_SEGMENT_BLOCKS; ++block)
		CHECK(authority->live_records[block] == 0);
	recycle_hook_calls++;
	recycle_hook_last_segment = segment;
	return recycle_hook_error;
}

static int setup(void)
{
	int rc = swapz_authority_init(&a, maps, live, classes, 32, 768);

	recycle_hook_calls = 0;
	recycle_hook_last_segment = ~(swapz_u32)0;
	recycle_hook_error = 0;
	a.reuse_dead_segments = 1;
	a.dead_segment_recycle = recycle_hook;
	a.dead_segment_recycle_opaque = &a;
	return rc;
}

static int setup_indexed(swapz_u32 physical_blocks)
{
	swapz_u32 segments = physical_blocks / SWAPZ_SEGMENT_BLOCKS;
	int rc;

	rc = swapz_authority_init(&a, maps, live, classes, 32, physical_blocks);
	if (rc)
		return rc;
	rc = swapz_enable_segment_rotation(&a, roles, segments);
	if (rc)
		return rc;
	rc = swapz_enable_segment_mapping_counts(&a, mapped_pages, segments);
	if (rc)
		return rc;
	rc = swapz_enable_segment_program_counts(&a, program_counts, segments);
	if (rc)
		return rc;
	rc = swapz_enable_segment_page_lists(&a, first_page, last_page,
					      prev_page, next_page,
					      segments, 32);
	if (rc)
		return rc;
	recycle_hook_calls = 0;
	recycle_hook_last_segment = ~(swapz_u32)0;
	recycle_hook_error = 0;
	a.reuse_dead_segments = 1;
	a.dead_segment_recycle = recycle_hook;
	a.dead_segment_recycle_opaque = &a;
	return 0;
}

static int write_page(swapz_u32 logical)
{
	struct swapz_tx tx;
	struct swapz_builder builder;
	int rc;

	rc = swapz_stage(&a, &logical, 1, 1, &tx);
	if (rc)
		return rc;
	memset(data, logical + 1, sizeof(data));
	rc = swapz_begin(&builder, bytes, SWAPZ_BLOCK_BYTES, tx.sequence);
	if (!rc)
		rc = swapz_append(&builder, logical, tx.records[0].generation,
				data, sizeof(data));
	if (!rc)
		rc = swapz_seal(&builder);
	if (rc) {
		swapz_abort(&a, &tx);
		return rc;
	}
	return swapz_finish(&a, &tx, bytes, SWAPZ_BLOCK_BYTES, 1, 0);
}

static int test_recycle_wholly_dead_segment(void)
{
	int i;

	CHECK(setup() == 0);
	for (i = 0; i < 256; ++i)
		CHECK(write_page(0) == 0);
	CHECK(a.next_block == 256);
	CHECK(a.recycled_dead_segments == 0);
	CHECK(live[255] == 1);
	CHECK(swapz_discard_page(&a, 0) == 0);
	CHECK(live[255] == 0 && !maps[0].valid);
	CHECK(write_page(1) == 0);
	CHECK(a.recycled_dead_segments == 1);
	CHECK(recycle_hook_calls == 1 && recycle_hook_last_segment == 0);
	CHECK(a.next_block == 1 && a.open_segment == 0);
	CHECK(maps[1].start_block == 0 && maps[1].valid);
	CHECK(live[0] == 1 && classes[0] == 1);
	return 0;
}

static int test_recycle_hook_failure_preserves_dead_segment(void)
{
	int i;

	CHECK(setup() == 0);
	for (i = 0; i < 256; ++i)
		CHECK(write_page(0) == 0);
	CHECK(swapz_discard_page(&a, 0) == 0);
	recycle_hook_error = -EIO;
	CHECK(write_page(1) == -EIO);
	CHECK(recycle_hook_calls == 1 && recycle_hook_last_segment == 0);
	CHECK(a.recycled_dead_segments == 0);
	CHECK(a.next_block == 256 && a.open_segment == 0);
	CHECK(!maps[0].valid && !maps[1].valid);
	recycle_hook_error = 0;
	CHECK(write_page(1) == 0);
	CHECK(recycle_hook_calls == 2 && a.recycled_dead_segments == 1);
	return 0;
}

static int test_live_segment_is_never_overwritten(void)
{
	int i;

	CHECK(setup() == 0);
	CHECK(write_page(0) == 0); /* pinned live page in physical block 0 */
	for (i = 1; i < 256; ++i)
		CHECK(write_page(1) == 0);
	CHECK(a.next_block == 256);
	CHECK(maps[0].valid && maps[0].start_block == 0);
	CHECK(maps[1].valid && maps[1].start_block == 255);
	CHECK(write_page(2) == -ENOSPC);
	CHECK(a.recycled_dead_segments == 0);
	CHECK(maps[0].start_block == 0 && live[0] == 1);
	CHECK(swapz_discard_page(&a, 0) == 0);
	CHECK(write_page(2) == -ENOSPC); /* still-live page1 */
	CHECK(swapz_discard_page(&a, 1) == 0);
	CHECK(write_page(2) == 0);
	CHECK(a.recycled_dead_segments == 1);
	return 0;
}

static int test_corrupted_liveness_never_reclaims_live_map(void)
{
	int i;

	CHECK(setup() == 0);
	CHECK(write_page(0) == 0);
	for (i = 1; i < 256; ++i)
		CHECK(write_page(1) == 0);
	live[0] = 0; /* corrupt physical liveness count deliberately */
	live[255] = 0;
	CHECK(write_page(2) == -ENOSPC); /* second scan checks maps */
	CHECK(a.recycled_dead_segments == 0 && maps[0].start_block == 0);
	CHECK(maps[1].start_block == 255 && maps[0].valid);
	return 0;
}

static int test_two_block_class_respects_segment_edges(void)
{
	swapz_u32 logical = 0;
	struct swapz_tx tx;
	int i;

	CHECK(setup() == 0);
	for (i = 0; i < 254; ++i)
		CHECK(write_page(0) == 0);
	/* current NEXT offset is 254, last valid 2block extent 254-255 */
	CHECK(swapz_stage(&a, &logical, 1, 2, &tx) == 0);
	CHECK(tx.start_block == 254);
	CHECK(swapz_abort(&a, &tx) == 0);
	CHECK(write_page(0) == -ENOSPC); /* page 0 remains live at 253 */
	CHECK(swapz_discard_page(&a, 0) == 0);
	CHECK(write_page(0) == 0);
	CHECK(maps[0].start_block == 0 && a.recycled_dead_segments == 1);
	return 0;
}

static int test_segment_page_lists_track_authority(void)
{
	const swapz_u32 none = ~(swapz_u32)0;

	CHECK(setup_indexed(768) == 0);
	CHECK(first_page[0] == none && last_page[0] == none);
	CHECK(write_page(0) == 0);
	CHECK(write_page(1) == 0);
	CHECK(mapped_pages[0] == 2);
	CHECK(first_page[0] == 0 && last_page[0] == 1);
	CHECK(prev_page[0] == none && next_page[0] == 1);
	CHECK(prev_page[1] == 0 && next_page[1] == none);

	/* Same-segment rewrite moves the logical page to the list tail. */
	CHECK(write_page(0) == 0);
	CHECK(mapped_pages[0] == 2);
	CHECK(first_page[0] == 1 && last_page[0] == 0);
	CHECK(prev_page[1] == none && next_page[1] == 0);
	CHECK(prev_page[0] == 1 && next_page[0] == none);

	CHECK(swapz_discard_page(&a, 1) == 0);
	CHECK(mapped_pages[0] == 1);
	CHECK(first_page[0] == 0 && last_page[0] == 0);
	CHECK(prev_page[0] == none && next_page[0] == none);

	/* Corrupt a valid local link: discard must fail before mutation. */
	next_page[0] = 7;
	CHECK(swapz_discard_page(&a, 0) == -EUCLEAN);
	CHECK(maps[0].valid && mapped_pages[0] == 1);
	next_page[0] = none;
	CHECK(swapz_discard_page(&a, 0) == 0);
	CHECK(!maps[0].valid && mapped_pages[0] == 0);
	CHECK(first_page[0] == none && last_page[0] == none);

	/* Invalid maps must also carry no stale membership links. */
	prev_page[0] = 1;
	CHECK(write_page(0) == -EUCLEAN);
	CHECK(!maps[0].valid && mapped_pages[0] == 0);
	return 0;
}

static int test_circular_allocator_fairness_probes_sequentially(void)
{
	struct swapz_tx tx;
	swapz_u32 logical = 0;

	CHECK(setup_indexed(1280) == 0);
	/* 32 logical pages => two reserve segments, three foreground segments. */
	CHECK(roles[0] == 1 && roles[1] == 1 && roles[2] == 1);
	a.next_segment_probe = 0;

	/* Probe 1 claims segment 0 and advances next_segment_probe to 1 */
	CHECK(swapz_stage(&a, &logical, 1, 1, &tx) == 0);
	CHECK(tx.start_block == 0U);
	CHECK(a.open_segment == 0 && a.next_segment_probe == 1);
	CHECK(swapz_abort(&a, &tx) == 0);
	a.open_segment = ~(swapz_u32)0;

	/* Probe 2 claims segment 1 and advances next_segment_probe to 2 */
	CHECK(swapz_stage(&a, &logical, 1, 1, &tx) == 0);
	CHECK(tx.start_block == SWAPZ_SEGMENT_BLOCKS);
	CHECK(a.open_segment == 1 && a.next_segment_probe == 2);
	CHECK(swapz_abort(&a, &tx) == 0);
	a.open_segment = ~(swapz_u32)0;

	/* Probe 3 claims segment 2 and sets next_segment_probe to 3 */
	CHECK(swapz_stage(&a, &logical, 1, 1, &tx) == 0);
	CHECK(tx.start_block == 2U * SWAPZ_SEGMENT_BLOCKS);
	CHECK(a.open_segment == 2 && a.next_segment_probe == 3);
	CHECK(swapz_abort(&a, &tx) == 0);
	a.open_segment = ~(swapz_u32)0;

	/* Probe 4 skips reserve segments 3 and 4, wrapping back to claim segment 0 */
	CHECK(swapz_stage(&a, &logical, 1, 1, &tx) == 0);
	CHECK(tx.start_block == 0U);
	CHECK(a.open_segment == 0 && a.next_segment_probe == 1);
	CHECK(swapz_abort(&a, &tx) == 0);
	return 0;
}

static int test_circular_allocator_fairness_applies_to_gc_destination(void)
{
	CHECK(setup_indexed(1280) == 0);
	a.next_segment_probe = 3;
	CHECK(swapz_gc_begin_rotation(&a, 0) == 0);
	CHECK(a.gc_destination == 3 && a.open_segment == 3);
	CHECK(a.next_segment_probe == 4);
	return 0;
}

int main(void)
{
	int passed = 0;

	CHECK(test_recycle_wholly_dead_segment() == 0); passed++;
	CHECK(test_recycle_hook_failure_preserves_dead_segment() == 0); passed++;
	CHECK(test_live_segment_is_never_overwritten() == 0); passed++;
	CHECK(test_corrupted_liveness_never_reclaims_live_map() == 0); passed++;
	CHECK(test_two_block_class_respects_segment_edges() == 0); passed++;
	CHECK(test_segment_page_lists_track_authority() == 0); passed++;
	CHECK(test_circular_allocator_fairness_probes_sequentially() == 0); passed++;
	CHECK(test_circular_allocator_fairness_applies_to_gc_destination() == 0); passed++;
	printf("SWAPZ_DEAD_SEGMENT_REUSE_TESTS_PASS=%d\n", passed);
	return 0;
}
