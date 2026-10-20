// SPDX-License-Identifier: GPL-2.0-only
/*
 * Test the EXACT production GC cost helper and authority.c publication C.
 * Simulate two physical candidates where the old count heuristic chooses
 * a more expensive victim than live-byte accounting.
 */
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include "gc-cost.h"
#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "%s:%d failed %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)

static struct swapz_authority a;
static struct swapz_map maps[32];
static swapz_u16 live[1024];
static swapz_u8 classes[1024];
static swapz_u8 bytes[4096];
static swapz_u8 p0[2200], p1[1600];
static swapz_u8 segment_roles[4];
static swapz_u32 segment_maps[4];
static swapz_u32 segment_bytes[4];
static swapz_u32 segment_io[4];
static swapz_u16 segment_min_blocks[4];

static int test_bytes_vs_count_victim_policy(void)
{
	struct swapz_map one = { .valid = 1, .extent_blocks = 1,
				.payload_length = 3500 };
	struct swapz_map three = { .valid = 1, .extent_blocks = 1,
				.payload_length = 500 };
	swapz_u32 score_one, score_three;

	score_one = swapz_gc_live_byte_cost(&one);
	score_three = 3 * swapz_gc_live_byte_cost(&three);
	CHECK(score_one == 3516 && score_three == 1548);
	CHECK(swapz_gc_prefer(1, 1, 3, 3)); /* old count picks one */
	CHECK(swapz_gc_prefer(score_three, 3, score_one, 1));
	CHECK(!swapz_gc_prefer(score_one, 1, score_three, 3));
	CHECK(swapz_gc_prefer(4096, 1, 4096, 2)); /* tie fewer records */
	CHECK(!swapz_gc_prefer(4096, 0, 65535, 1));
	return 0;
}

static int test_io_aware_cost_corrects_loaded_gc_counterexample(void)
{
	/* Alpha.4: one 3335-byte survivor required 4KiB read+write;
	 * three 496-byte survivors required three 4KiB reads and one
	 * packed 4KiB write. Both extents held one lower 4KiB block. */
	struct swapz_map large = { .valid = 1, .extent_blocks = 1,
				.payload_length = 3335 };
	struct swapz_map tiny = { .valid = 1, .extent_blocks = 1,
			       .payload_length = 496 };
	struct swapz_map multi = { .valid = 1, .extent_blocks = 4,
				.payload_length = 2082 };
	swapz_u32 one, three;

	CHECK(swapz_gc_live_byte_cost(&large) == 3351);
	CHECK(3 * swapz_gc_live_byte_cost(&tiny) == 1536);
	CHECK(3 * swapz_gc_live_byte_cost(&tiny) <
	      swapz_gc_live_byte_cost(&large)); /* byte policy gets it wrong */
	one = swapz_gc_estimated_io_cost(&large);
	three = 3 * swapz_gc_estimated_io_cost(&tiny);
	CHECK(one == 7447 && three == 13824);
	CHECK(!swapz_gc_prefer(three, 3, one, 1));
	CHECK(swapz_gc_prefer(one, 1, three, 3));
	CHECK(swapz_gc_estimated_io_cost(&multi) ==
	      2098 + 3 * SWAPZ_BLOCK_BYTES);
	multi.extent_blocks = 3;
	CHECK(swapz_gc_estimated_io_cost(&multi) == 0);
	tiny.valid = 0;
	CHECK(swapz_gc_estimated_io_cost(&tiny) == 0);
	return 0;
}

static int test_reclaim_headroom_preflight(void)
{
	const swapz_u32 capacity = SWAPZ_SEGMENT_BLOCKS * SWAPZ_BLOCK_BYTES;

	CHECK(!swapz_gc_has_possible_headroom(0));
	CHECK(swapz_gc_has_possible_headroom(4096));
	CHECK(swapz_gc_has_possible_headroom(capacity - 1));
	CHECK(!swapz_gc_has_possible_headroom(capacity));
	CHECK(!swapz_gc_has_possible_headroom(capacity + 4096));
	/* 256 distinct raw pages each use a complete 4KiB container,
	 * so moving them into one 1MiB reserve cannot free a single block.
	 * Avoid wasting 256 reads+256 writes before inevitable ENOSPC. */
	CHECK(!swapz_gc_has_possible_headroom(
	      SWAPZ_SEGMENT_BLOCKS * swapz_gc_live_byte_cost(
		      &(struct swapz_map){ .valid=1, .raw=1,
				   .extent_blocks=1, .payload_length=4096 })));
	return 0;
}

static int test_proven_large_record_gc_block_bound(void)
{
	struct swapz_map m = { .valid = 1, .extent_blocks = 4,
			    .payload_length = 3258 };
	struct swapz_builder builder;
	swapz_u8 image[SWAPZ_MAX_EXTENT_BYTES];
	swapz_u8 payload[3258];
	unsigned int i;
	const swapz_u32 optimistic_bytes =
		SWAPZ_SEGMENT_BLOCKS * (3258U + sizeof(struct swapz_record));

	/* Five of 3257B fit a 16KiB extent. Five of 3258B do NOT.
	 * The exact production codec establishes this physical boundary. */
	CHECK(SWAPZ_GC_UNSHAREABLE_MIN_LENGTH == 3258);
	memset(payload, 0x34, sizeof(payload));
	CHECK(swapz_begin(&builder, image, sizeof(image), 3) == 0);
	for (i = 0; i < 5; ++i)
		CHECK(swapz_append(&builder, i, 1, payload, 3257) == 0);
	CHECK(swapz_seal(&builder) == 0);
	CHECK(swapz_begin(&builder, image, sizeof(image), 4) == 0);
	for (i = 0; i < 4; ++i)
		CHECK(swapz_append(&builder, i, 1, payload, 3258) == 0);
	CHECK(swapz_append(&builder, 4, 1, payload, 3258) != 0);
	CHECK(swapz_gc_min_live_blocks(&m) == 1);
	CHECK(swapz_gc_has_possible_headroom(optimistic_bytes));
	CHECK(!swapz_gc_candidate_can_free_block(
	      optimistic_bytes, SWAPZ_SEGMENT_BLOCKS));
	CHECK(swapz_gc_candidate_can_free_block(
	      optimistic_bytes, SWAPZ_SEGMENT_BLOCKS - 1));
	m.payload_length = 3257;
	CHECK(!swapz_gc_min_live_blocks(&m));
	m.payload_length = 3535;
	CHECK(swapz_gc_min_live_blocks(&m) == 1);
	m.raw = 1;
	m.extent_blocks = 1;
	m.payload_length = 4096;
	CHECK(swapz_gc_min_live_blocks(&m) == 1);
	return 0;
}

static int test_raw_and_invalid_cost(void)
{
	struct swapz_map m = { .valid = 1, .raw = 1,
			    .extent_blocks = 1, .payload_length = 4096 };

	CHECK(swapz_gc_live_byte_cost(&m) == 4096);
	m.payload_length = 4095;
	CHECK(swapz_gc_live_byte_cost(&m) == 0);
	m.raw = 0;
	m.payload_length = 3568;
	CHECK(swapz_gc_live_byte_cost(&m) == 3584);
	m.payload_length = 3569;
	CHECK(swapz_gc_live_byte_cost(&m) == 0);
	m.payload_length = 0;
	CHECK(swapz_gc_live_byte_cost(&m) == 0);
	m.valid = 0;
	CHECK(swapz_gc_live_byte_cost(&m) == 0);
	CHECK(swapz_gc_live_byte_cost(NULL) == 0);
	return 0;
}

static int test_exact_committed_payload_lengths(void)
{
	struct swapz_tx tx;
	struct swapz_builder b;
	swapz_u32 pages[2] = { 2, 3 };

	CHECK(swapz_authority_init(&a, maps, live, classes, 32, 1024) == 0);
	a.reuse_dead_segments = 1;
	CHECK(swapz_enable_segment_rotation(&a, segment_roles, 4) == 0);
	CHECK(swapz_enable_segment_mapping_counts(&a, segment_maps, 4) == 0);
	CHECK(swapz_enable_segment_gc_accounting(
	      &a, segment_bytes, segment_io, segment_min_blocks, 4) == 0);
	memset(p0, 0x3a, sizeof(p0));
	memset(p1, 0x59, sizeof(p1));
	CHECK(swapz_stage(&a, pages, 2, 1, &tx) == 0);
	CHECK(swapz_begin(&b, bytes, sizeof(bytes), tx.sequence) == 0);
	CHECK(swapz_append(&b, pages[0], tx.records[0].generation,
			 p0, sizeof(p0)) == 0);
	CHECK(swapz_append(&b, pages[1], tx.records[1].generation,
			 p1, sizeof(p1)) == 0);
	CHECK(swapz_seal(&b) == 0);
	CHECK(swapz_finish(&a, &tx, bytes, sizeof(bytes), 1, 0) == 0);
	CHECK(maps[2].payload_length == sizeof(p0));
	CHECK(maps[3].payload_length == sizeof(p1));
	CHECK(swapz_gc_live_byte_cost(&maps[2]) == sizeof(p0) + 16);
	CHECK(swapz_gc_live_byte_cost(&maps[3]) == sizeof(p1) + 16);
	CHECK(live[0] == 2);
	CHECK(segment_maps[0] == 2);
	CHECK(segment_bytes[0] ==
	      swapz_gc_live_byte_cost(&maps[2]) +
	      swapz_gc_live_byte_cost(&maps[3]));
	CHECK(segment_io[0] ==
	      swapz_gc_estimated_io_cost(&maps[2]) +
	      swapz_gc_estimated_io_cost(&maps[3]));
	CHECK(segment_min_blocks[0] ==
	      swapz_gc_min_live_blocks(&maps[2]) +
	      swapz_gc_min_live_blocks(&maps[3]));
	CHECK(swapz_discard_page(&a, 2) == 0);
	CHECK(swapz_gc_live_byte_cost(&maps[2]) == 0);
	CHECK(swapz_gc_live_byte_cost(&maps[3]) == sizeof(p1) + 16);
	CHECK(segment_maps[0] == 1);
	CHECK(segment_bytes[0] == swapz_gc_live_byte_cost(&maps[3]));
	CHECK(segment_io[0] == swapz_gc_estimated_io_cost(&maps[3]));
	CHECK(segment_min_blocks[0] == swapz_gc_min_live_blocks(&maps[3]));
	return 0;
}

int main(void)
{
	int passed = 0;

	CHECK(test_bytes_vs_count_victim_policy() == 0); passed++;
	CHECK(test_raw_and_invalid_cost() == 0); passed++;
	CHECK(test_exact_committed_payload_lengths() == 0); passed++;
	CHECK(test_io_aware_cost_corrects_loaded_gc_counterexample() == 0); passed++;
	CHECK(test_reclaim_headroom_preflight() == 0); passed++;
	CHECK(test_proven_large_record_gc_block_bound() == 0); passed++;
	printf("SWAPZ_GC_COST_TESTS_PASS=%d\n", passed);
	return 0;
}
