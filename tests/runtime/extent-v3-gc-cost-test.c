// SPDX-License-Identifier: GPL-2.0-only
/*
 * Test the EXACT production GC cost helper and authority.c publication C.
 * Simulate two physical candidates where the old count heuristic chooses
 * a more expensive victim than live-byte accounting.
 */
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include "../../kernel/extent-v3/gc-cost.h"
#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "%s:%d failed %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)

static struct sv3_authority a;
static struct sv3_map maps[32];
static sv3_u16 live[1024];
static sv3_u8 classes[1024];
static sv3_u8 bytes[4096];
static sv3_u8 p0[2200], p1[1600];

static int test_bytes_vs_count_victim_policy(void)
{
	struct sv3_map one = { .valid = 1, .extent_blocks = 1,
				.payload_length = 3500 };
	struct sv3_map three = { .valid = 1, .extent_blocks = 1,
				.payload_length = 500 };
	sv3_u32 score_one, score_three;

	score_one = sv3_gc_live_byte_cost(&one);
	score_three = 3 * sv3_gc_live_byte_cost(&three);
	CHECK(score_one == 3516 && score_three == 1548);
	CHECK(sv3_gc_prefer(1, 1, 3, 3)); /* old count picks one */
	CHECK(sv3_gc_prefer(score_three, 3, score_one, 1));
	CHECK(!sv3_gc_prefer(score_one, 1, score_three, 3));
	CHECK(sv3_gc_prefer(4096, 1, 4096, 2)); /* tie fewer records */
	CHECK(!sv3_gc_prefer(4096, 0, 65535, 1));
	return 0;
}

static int test_io_aware_cost_corrects_loaded_gc_counterexample(void)
{
	/* Alpha.4: one 3335-byte survivor required 4KiB read+write;
	 * three 496-byte survivors required three 4KiB reads and one
	 * packed 4KiB write. Both extents held one lower 4KiB block. */
	struct sv3_map large = { .valid = 1, .extent_blocks = 1,
				.payload_length = 3335 };
	struct sv3_map tiny = { .valid = 1, .extent_blocks = 1,
			       .payload_length = 496 };
	struct sv3_map multi = { .valid = 1, .extent_blocks = 4,
				.payload_length = 2082 };
	sv3_u32 one, three;

	CHECK(sv3_gc_live_byte_cost(&large) == 3351);
	CHECK(3 * sv3_gc_live_byte_cost(&tiny) == 1536);
	CHECK(3 * sv3_gc_live_byte_cost(&tiny) <
	      sv3_gc_live_byte_cost(&large)); /* byte policy gets it wrong */
	one = sv3_gc_estimated_io_cost(&large);
	three = 3 * sv3_gc_estimated_io_cost(&tiny);
	CHECK(one == 7447 && three == 13824);
	CHECK(!sv3_gc_prefer(three, 3, one, 1));
	CHECK(sv3_gc_prefer(one, 1, three, 3));
	CHECK(sv3_gc_estimated_io_cost(&multi) ==
	      2098 + 3 * SV3_BLOCK_BYTES);
	multi.extent_blocks = 3;
	CHECK(sv3_gc_estimated_io_cost(&multi) == 0);
	tiny.valid = 0;
	CHECK(sv3_gc_estimated_io_cost(&tiny) == 0);
	return 0;
}

static int test_raw_and_invalid_cost(void)
{
	struct sv3_map m = { .valid = 1, .raw = 1,
			    .extent_blocks = 1, .payload_length = 4096 };

	CHECK(sv3_gc_live_byte_cost(&m) == 4096);
	m.payload_length = 4095;
	CHECK(sv3_gc_live_byte_cost(&m) == 0);
	m.raw = 0;
	m.payload_length = 3568;
	CHECK(sv3_gc_live_byte_cost(&m) == 3584);
	m.payload_length = 3569;
	CHECK(sv3_gc_live_byte_cost(&m) == 0);
	m.payload_length = 0;
	CHECK(sv3_gc_live_byte_cost(&m) == 0);
	m.valid = 0;
	CHECK(sv3_gc_live_byte_cost(&m) == 0);
	CHECK(sv3_gc_live_byte_cost(NULL) == 0);
	return 0;
}

static int test_exact_committed_payload_lengths(void)
{
	struct sv3_tx tx;
	struct sv3_builder b;
	sv3_u32 pages[2] = { 2, 3 };

	CHECK(sv3_authority_init(&a, maps, live, classes, 32, 1024) == 0);
	memset(p0, 0x3a, sizeof(p0));
	memset(p1, 0x59, sizeof(p1));
	CHECK(sv3_stage(&a, pages, 2, 1, &tx) == 0);
	CHECK(sv3_begin(&b, bytes, sizeof(bytes), tx.sequence) == 0);
	CHECK(sv3_append(&b, pages[0], tx.records[0].generation,
			 p0, sizeof(p0)) == 0);
	CHECK(sv3_append(&b, pages[1], tx.records[1].generation,
			 p1, sizeof(p1)) == 0);
	CHECK(sv3_seal(&b) == 0);
	CHECK(sv3_finish(&a, &tx, bytes, sizeof(bytes), 1, 0) == 0);
	CHECK(maps[2].payload_length == sizeof(p0));
	CHECK(maps[3].payload_length == sizeof(p1));
	CHECK(sv3_gc_live_byte_cost(&maps[2]) == sizeof(p0) + 16);
	CHECK(sv3_gc_live_byte_cost(&maps[3]) == sizeof(p1) + 16);
	CHECK(live[0] == 2);
	CHECK(sv3_discard_page(&a, 2) == 0);
	CHECK(sv3_gc_live_byte_cost(&maps[2]) == 0);
	CHECK(sv3_gc_live_byte_cost(&maps[3]) == sizeof(p1) + 16);
	return 0;
}

int main(void)
{
	int passed = 0;

	CHECK(test_bytes_vs_count_victim_policy() == 0); passed++;
	CHECK(test_raw_and_invalid_cost() == 0); passed++;
	CHECK(test_exact_committed_payload_lengths() == 0); passed++;
	CHECK(test_io_aware_cost_corrects_loaded_gc_counterexample() == 0); passed++;
	printf("SV3_GC_COST_TESTS_PASS=%d\n", passed);
	return 0;
}
