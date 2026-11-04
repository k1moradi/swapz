// SPDX-License-Identifier: GPL-2.0-only
/*
 * Exact-production-C regression: GC must never allocate into the paused
 * foreground OPEN segment or the still-live victim it is relocating.
 * Both may temporarily appear to have no authoritative live references.
 */
#include <stdio.h>
#include <errno.h>
#include <string.h>
#include "authority.h"

#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "%s:%d FAILED: %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)

static struct swapz_authority a;
static struct swapz_map maps[32];
static swapz_u16 live[1024];
static swapz_u8 classes[1024];
static swapz_u8 raw_page[SWAPZ_BLOCK_BYTES];

static int unexpected_recycle_calls;

static int unexpected_recycle(void *opaque, swapz_u32 segment)
{
	int *calls = opaque;

	(void)segment;
	++*calls;
	return -EIO;
}

static int initialize_gc(void)
{
	if (swapz_authority_init(&a, maps, live, classes, 32, 1024))
		return -1;
	a.reuse_dead_segments = 1;
	a.gc_allocation = 1;
	a.gc_forbidden_open = 0;
	a.gc_forbidden_victim = 1;
	a.open_segment = ~(swapz_u32)0;
	a.next_segment_probe = 0;
	memset(raw_page, 0x62, sizeof(raw_page));
	return 0;
}

static int test_no_allocation_into_paused_foreground_or_victim(void)
{
	struct swapz_tx tx;
	swapz_u32 page = 0;

	CHECK(initialize_gc() == 0);
	CHECK(swapz_stage(&a, &page, 1, 1, &tx) == 0);
	CHECK(tx.start_block == 512);
	CHECK(a.open_segment == 2);
	CHECK(swapz_finish_raw(&a, &tx, raw_page, 1, 0) == 0);
	CHECK(maps[page].valid && maps[page].start_block == 512);
	CHECK(!live[0] && !classes[0] && !live[256] && !classes[256]);
	return 0;
}

static int test_fail_closed_when_only_forbidden_segments_are_free(void)
{
	struct swapz_tx tx;
	swapz_u32 page = 0;
	unsigned int i;

	CHECK(initialize_gc() == 0);
	for (i = 0; i < SWAPZ_SEGMENT_BLOCKS; ++i) {
		CHECK(swapz_stage(&a, &page, 1, 1, &tx) == 0);
		CHECK(tx.start_block == 2U * SWAPZ_SEGMENT_BLOCKS + i);
		CHECK(swapz_finish_raw(&a, &tx, raw_page, 1, 0) == 0);
	}
	CHECK(live[3U * SWAPZ_SEGMENT_BLOCKS - 1U] == 1 &&
	      maps[0].start_block == 3U * SWAPZ_SEGMENT_BLOCKS - 1U);

	page = 1;
	for (i = 0; i < SWAPZ_SEGMENT_BLOCKS; ++i) {
		CHECK(swapz_stage(&a, &page, 1, 1, &tx) == 0);
		CHECK(tx.start_block == 3U * SWAPZ_SEGMENT_BLOCKS + i);
		CHECK(swapz_finish_raw(&a, &tx, raw_page, 1, 0) == 0);
	}
	CHECK(a.next_block == 4U * SWAPZ_SEGMENT_BLOCKS);
	CHECK(live[4U * SWAPZ_SEGMENT_BLOCKS - 1U] == 1 &&
	      maps[1].start_block == 4U * SWAPZ_SEGMENT_BLOCKS - 1U);

	page = 2;
	CHECK(swapz_stage(&a, &page, 1, 1, &tx) == -ENOSPC);
	CHECK(maps[0].start_block == 3U * SWAPZ_SEGMENT_BLOCKS - 1U &&
	      maps[1].start_block == 4U * SWAPZ_SEGMENT_BLOCKS - 1U &&
	      maps[0].raw_crc32c ==
		      swapz_crc32c_bytes(raw_page, SWAPZ_BLOCK_BYTES) &&
	      maps[1].raw_crc32c ==
		      swapz_crc32c_bytes(raw_page, SWAPZ_BLOCK_BYTES));
	CHECK(a.gc_forbidden_open == 0 && a.gc_forbidden_victim == 1);
	CHECK(a.in_flight == 0);
	return 0;
}

/*
 * Unindexed GC still scans the primary logical map when both the block
 * liveness and extent-class caches falsely report that all writable targets
 * are blank. Repeated reserve exhaustion must neither reclaim a live map nor
 * invoke a physical recycle callback.
 */
static int test_forged_empty_reserves_fail_without_recycling(void)
{
	struct swapz_tx tx;
	struct swapz_map original_maps[32];
	swapz_u16 original_live[1024];
	swapz_u8 original_classes[1024];
	swapz_u32 page;
	unsigned int index, attempt;

	CHECK(initialize_gc() == 0);
	for (page = 0; page < 2U; ++page) {
		for (index = 0; index < SWAPZ_SEGMENT_BLOCKS; ++index) {
			CHECK(swapz_stage(&a, &page, 1, 1, &tx) == 0);
			CHECK(swapz_finish_raw(&a, &tx, raw_page, 1, 0) == 0);
		}
	}
	CHECK(maps[0].valid && maps[1].valid &&
	      maps[0].start_block == 3U * SWAPZ_SEGMENT_BLOCKS - 1U &&
	      maps[1].start_block == 4U * SWAPZ_SEGMENT_BLOCKS - 1U);
	a.dead_segment_recycle = unexpected_recycle;
	a.dead_segment_recycle_opaque = &unexpected_recycle_calls;
	unexpected_recycle_calls = 0;
	memset(live, 0, sizeof(live));
	memset(classes, 0, sizeof(classes));
	memcpy(original_maps, maps, sizeof(maps));
	memcpy(original_live, live, sizeof(live));
	memcpy(original_classes, classes, sizeof(classes));

	page = 2U;
	for (attempt = 0; attempt < 2U; ++attempt) {
		CHECK(swapz_stage(&a, &page, 1, 1, &tx) == -ENOSPC);
		CHECK(!memcmp(original_maps, maps, sizeof(maps)));
		CHECK(!memcmp(original_live, live, sizeof(live)));
		CHECK(!memcmp(original_classes, classes, sizeof(classes)));
		CHECK(a.next_block == 4U * SWAPZ_SEGMENT_BLOCKS &&
		      a.open_segment == 3U && a.in_flight == 0);
		CHECK(a.gc_allocation && a.gc_forbidden_open == 0U &&
		      a.gc_forbidden_victim == 1U);
		CHECK(unexpected_recycle_calls == 0 &&
		      a.recycled_dead_segments == 0U);
	}
	return 0;
}

static int test_idle_mode_allows_dead_segment_without_gc_guards(void)
{
	struct swapz_tx tx;
	swapz_u32 page = 1;

	CHECK(initialize_gc() == 0);
	a.gc_allocation = 0;
	/* Foreground dead reuse has no paused-cursor or victim constraints.
	 * Segment zero is legal and the fixed logical reserve remains closed. */
	CHECK(swapz_stage(&a, &page, 1, 1, &tx) == 0);
	CHECK(tx.start_block == 0 && a.open_segment == 0);
	CHECK(swapz_abort(&a, &tx) == 0);
	return 0;
}

int main(void)
{
	int passed = 0;

	CHECK(test_no_allocation_into_paused_foreground_or_victim() == 0);
	passed++;
	CHECK(test_fail_closed_when_only_forbidden_segments_are_free() == 0);
	passed++;
	CHECK(test_forged_empty_reserves_fail_without_recycling() == 0);
	passed++;
	CHECK(test_idle_mode_allows_dead_segment_without_gc_guards() == 0);
	passed++;
	printf("SWAPZ_GC_FORBIDDEN_SEGMENT_TESTS_PASS=%d\n", passed);
	return 0;
}
