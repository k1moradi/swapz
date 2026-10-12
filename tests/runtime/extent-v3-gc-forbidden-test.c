// SPDX-License-Identifier: GPL-2.0-only
/*
 * Exact-production-C regression: GC must never allocate into the paused
 * foreground OPEN segment or the still-live victim it is relocating.
 * Both may temporarily appear to have no authoritative live references.
 */
#include <stdio.h>
#include <errno.h>
#include <string.h>
#include "../../kernel/extent-v3/authority.h"

#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "%s:%d FAILED: %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)

static struct sv3_authority a;
static struct sv3_map maps[32];
static sv3_u16 live[768];
static sv3_u8 classes[768];
static sv3_u8 raw_page[SV3_BLOCK_BYTES];

static int initialize_gc(void)
{
	if (sv3_authority_init(&a, maps, live, classes, 32, 768))
		return -1;
	a.reuse_dead_segments = 1;
	a.gc_allocation = 1;
	a.gc_forbidden_open = 0;
	a.gc_forbidden_victim = 1;
	a.open_segment = ~(sv3_u32)0;
	a.next_segment_probe = 0;
	memset(raw_page, 0x62, sizeof(raw_page));
	return 0;
}

static int test_no_allocation_into_paused_foreground_or_victim(void)
{
	struct sv3_tx tx;
	sv3_u32 page = 0;

	CHECK(initialize_gc() == 0);
	CHECK(sv3_stage(&a, &page, 1, 1, &tx) == 0);
	CHECK(tx.start_block == 512);
	CHECK(a.open_segment == 2);
	CHECK(sv3_finish_raw(&a, &tx, raw_page, 1, 0) == 0);
	CHECK(maps[page].valid && maps[page].start_block == 512);
	CHECK(!live[0] && !classes[0] && !live[256] && !classes[256]);
	return 0;
}

static int test_fail_closed_when_only_forbidden_segments_are_free(void)
{
	struct sv3_tx tx;
	sv3_u32 page = 0;
	unsigned int i;

	CHECK(initialize_gc() == 0);
	for (i = 0; i < SV3_SEGMENT_BLOCKS; ++i) {
		CHECK(sv3_stage(&a, &page, 1, 1, &tx) == 0);
		CHECK(tx.start_block == 512 + i);
		CHECK(sv3_finish_raw(&a, &tx, raw_page, 1, 0) == 0);
	}
	CHECK(a.next_block == 768);
	CHECK(live[767] == 1 && maps[0].start_block == 767);
	CHECK(sv3_stage(&a, &page, 1, 1, &tx) == -ENOSPC);
	CHECK(maps[0].start_block == 767 && maps[0].raw_crc32c ==
	      sv3_crc32c_bytes(raw_page, SV3_BLOCK_BYTES));
	CHECK(a.gc_forbidden_open == 0 && a.gc_forbidden_victim == 1);
	CHECK(a.in_flight == 0);
	return 0;
}

static int test_idle_mode_allows_dead_segment_without_gc_guards(void)
{
	struct sv3_tx tx;
	sv3_u32 page = 1;

	CHECK(initialize_gc() == 0);
	a.gc_allocation = 0;
	/* Foreground dead reuse has no paused-cursor or victim constraints.
	 * Segment zero is legal and the fixed logical reserve remains closed. */
	CHECK(sv3_stage(&a, &page, 1, 1, &tx) == 0);
	CHECK(tx.start_block == 0 && a.open_segment == 0);
	CHECK(sv3_abort(&a, &tx) == 0);
	return 0;
}

int main(void)
{
	int passed = 0;

	CHECK(test_no_allocation_into_paused_foreground_or_victim() == 0);
	passed++;
	CHECK(test_fail_closed_when_only_forbidden_segments_are_free() == 0);
	passed++;
	CHECK(test_idle_mode_allows_dead_segment_without_gc_guards() == 0);
	passed++;
	printf("SV3_GC_FORBIDDEN_SEGMENT_TESTS_PASS=%d\n", passed);
	return 0;
}
