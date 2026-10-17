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
static swapz_u16 live[768];
static swapz_u8 classes[768];
static swapz_u8 bytes[SWAPZ_BLOCK_BYTES];
static swapz_u8 data[100];

static int setup(void)
{
	int rc = swapz_authority_init(&a, maps, live, classes, 32, 768);
	a.reuse_dead_segments = 1;
	return rc;
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
	CHECK(a.next_block == 1 && a.open_segment == 0);
	CHECK(maps[1].start_block == 0 && maps[1].valid);
	CHECK(live[0] == 1 && classes[0] == 1);
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

int main(void)
{
	int passed = 0;

	CHECK(test_recycle_wholly_dead_segment() == 0); passed++;
	CHECK(test_live_segment_is_never_overwritten() == 0); passed++;
	CHECK(test_corrupted_liveness_never_reclaims_live_map() == 0); passed++;
	CHECK(test_two_block_class_respects_segment_edges() == 0); passed++;
	printf("SWAPZ_DEAD_SEGMENT_REUSE_TESTS_PASS=%d\n", passed);
	return 0;
}
