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
static swapz_u8 failed_extent[2U * SWAPZ_BLOCK_BYTES];
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

static int test_invalid_compressed_extent_classes(void)
{
	struct swapz_map map = { .valid = 1, .extent_blocks = 1,
				  .payload_length = 3258 };
	unsigned int extent_blocks;

	for (extent_blocks = 0; extent_blocks < 8; ++extent_blocks) {
		int legal = extent_blocks == 1 || extent_blocks == 2 ||
			    extent_blocks == 4;

		map.extent_blocks = extent_blocks;
		CHECK((swapz_gc_live_byte_cost(&map) != 0) == legal);
		CHECK((swapz_gc_estimated_io_cost(&map) != 0) == legal);
		CHECK((swapz_gc_min_live_blocks(&map) != 0) == legal);
	}
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

/* Captured by the single serialized authority owner; never shared with I/O. */
struct gc_cost_snapshot {
	struct swapz_map authoritative_map;
	swapz_u32 mapped_count, live_bytes, io_cost;
	swapz_u16 min_blocks;
	swapz_u32 committed_blocks, abandoned_blocks;
};

static struct gc_cost_snapshot gc_cost_capture(swapz_u32 logical)
{
	const swapz_u32 segment = maps[logical].start_block /
				 SWAPZ_SEGMENT_BLOCKS;

	return (struct gc_cost_snapshot) {
		.authoritative_map = maps[logical],
		.mapped_count = segment_maps[segment],
		.live_bytes = segment_bytes[segment],
		.io_cost = segment_io[segment],
		.min_blocks = segment_min_blocks[segment],
		.committed_blocks = a.committed_blocks,
		.abandoned_blocks = a.abandoned_blocks,
	};
}

static int gc_cost_check_rejected_write(
	const char *phase, swapz_u32 logical, swapz_u32 attempted_block,
	swapz_u8 attempted_blocks, const struct gc_cost_snapshot *expected,
	int actual_error)
{
	const swapz_u32 segment = expected->authoritative_map.start_block /
				 SWAPZ_SEGMENT_BLOCKS;
	swapz_u32 expected_abandoned_blocks = expected->abandoned_blocks;
	swapz_u8 block_offset;
	int reservation_unpublished = 1;

	if (!attempted_blocks || attempted_block >= a.physical_blocks ||
	    attempted_blocks > a.physical_blocks - attempted_block ||
	    expected_abandoned_blocks > ~(swapz_u32)0 - attempted_blocks) {
		reservation_unpublished = 0;
	} else {
		expected_abandoned_blocks += attempted_blocks;
		for (block_offset = 0; block_offset < attempted_blocks;
		     ++block_offset) {
			const swapz_u32 block = attempted_block + block_offset;

			if (a.live_records[block] || a.extent_classes[block]) {
				reservation_unpublished = 0;
				break;
			}
		}
	}

	if (actual_error == -EIO && !a.in_flight &&
	    !memcmp(&maps[logical], &expected->authoritative_map,
		    sizeof(expected->authoritative_map)) &&
	    segment_maps[segment] == expected->mapped_count &&
	    segment_bytes[segment] == expected->live_bytes &&
	    segment_io[segment] == expected->io_cost &&
	    segment_min_blocks[segment] == expected->min_blocks &&
	    a.committed_blocks == expected->committed_blocks &&
	    reservation_unpublished &&
	    a.abandoned_blocks == expected_abandoned_blocks &&
	    a.next_block == attempted_block + attempted_blocks)
		return 0;

	fprintf(stderr,
		"GC_COST_FAIL phase=%s logical=%u physical=%u blocks=%u "
		"expected_authority=previous_mapping expected_block=%u "
		"expected_generation=%u actual_generation=%u "
		"expected_errno=%d actual_errno=%d\n",
		phase, logical, attempted_block, (unsigned int)attempted_blocks,
		expected->authoritative_map.start_block,
		expected->authoritative_map.generation,
		maps[logical].generation, -EIO, actual_error);
	return 1;
}

static int test_failed_lower_writes_preserve_committed_costs(void)
{
	struct swapz_tx tx;
	struct swapz_builder builder;
	struct gc_cost_snapshot expected;
	const swapz_u32 logical = 7;
	unsigned int failure_case;
	int actual_error;

	CHECK(swapz_authority_init(&a, maps, live, classes, 32, 1024) == 0);
	a.reuse_dead_segments = 1;
	CHECK(swapz_enable_segment_rotation(&a, segment_roles, 4) == 0);
	CHECK(swapz_enable_segment_mapping_counts(&a, segment_maps, 4) == 0);
	CHECK(swapz_enable_segment_gc_accounting(
	      &a, segment_bytes, segment_io, segment_min_blocks, 4) == 0);
	memset(p0, 0x47, sizeof(p0));
	memset(bytes, 0x6b, sizeof(bytes));

	/* Publish the first generation before injecting failed lower writes. */
	CHECK(swapz_stage(&a, &logical, 1, 1, &tx) == 0);
	CHECK(swapz_begin(&builder, bytes, sizeof(bytes), tx.sequence) == 0);
	CHECK(swapz_append(&builder, logical, tx.records[0].generation,
			   p0, sizeof(p0)) == 0);
	CHECK(swapz_seal(&builder) == 0);
	CHECK(swapz_finish(&a, &tx, bytes, sizeof(bytes), 1, 0) == 0);
	CHECK(maps[logical].valid && !maps[logical].raw);
	CHECK(segment_maps[0] == 1);
	CHECK(segment_bytes[0] == sizeof(p0) + sizeof(struct swapz_record));

	for (failure_case = 0; failure_case < 2; ++failure_case) {
		const swapz_u8 completed = failure_case == 0 ? 1 : 0;
		const int lower_error = failure_case == 0 ? -EIO : 0;
		const char *phase = failure_case == 0 ?
			"compressed_error" : "compressed_short_write";

		expected = gc_cost_capture(logical);
		CHECK(swapz_stage(&a, &logical, 1, 1, &tx) == 0);
		CHECK(segment_bytes[0] == expected.live_bytes);
		actual_error = swapz_finish(&a, &tx, bytes, sizeof(bytes),
					    completed, lower_error);
		CHECK(!gc_cost_check_rejected_write(
			phase, logical, tx.start_block, tx.extent_blocks,
			&expected, actual_error));
	}

	/*
	 * A one-block short write can only report zero completed blocks. Exercise
	 * a nonzero strict prefix of a multi-block compressed reservation so
	 * incomplete lower-I/O observation cannot masquerade as durable savings.
	 */
	expected = gc_cost_capture(logical);
	CHECK(swapz_stage(&a, &logical, 1, 2, &tx) == 0);
	CHECK(segment_bytes[0] == expected.live_bytes);
	actual_error = swapz_finish(&a, &tx, failed_extent,
				    sizeof(failed_extent), 1, 0);
	CHECK(!gc_cost_check_rejected_write(
		"compressed_partial_short_write", logical, tx.start_block,
		tx.extent_blocks, &expected, actual_error));

	/* RAW changes the live cost only after a successful publication. */
	CHECK(swapz_stage(&a, &logical, 1, 1, &tx) == 0);
	CHECK(swapz_finish_raw(&a, &tx, bytes, 1, 0) == 0);
	CHECK(maps[logical].valid && maps[logical].raw);
	CHECK(segment_bytes[0] == SWAPZ_BLOCK_BYTES);
	CHECK(segment_io[0] == 2U * SWAPZ_BLOCK_BYTES);
	CHECK(segment_min_blocks[0] == 1);

	for (failure_case = 0; failure_case < 2; ++failure_case) {
		const swapz_u8 completed = failure_case == 0 ? 1 : 0;
		const int lower_error = failure_case == 0 ? -EIO : 0;
		const char *phase = failure_case == 0 ?
			"raw_error" : "raw_short_write";

		expected = gc_cost_capture(logical);
		CHECK(swapz_stage(&a, &logical, 1, 1, &tx) == 0);
		CHECK(segment_io[0] == expected.io_cost);
		actual_error = swapz_finish_raw(&a, &tx, bytes,
						completed, lower_error);
		CHECK(!gc_cost_check_rejected_write(
			phase, logical, tx.start_block, tx.extent_blocks,
			&expected, actual_error));
	}
	return 0;
}

/*
 * Synthetic u32/u16 sidecar saturation is a pre-publication overflow probe,
 * not a physical full-capacity result. The previous compressed generation is
 * durable in previous_extent; an entirely completed RAW replacement must be
 * abandoned before any mapping, checksum or reserve role changes.
 * Serialized authority owns every array throughout this bounded test.
 */
static int test_saturated_gc_accounting_preserves_durable_generation(void)
{
	static swapz_u8 previous_extent[SWAPZ_BLOCK_BYTES];
	static swapz_u8 raw_replacement[SWAPZ_BLOCK_BYTES];
	static swapz_u8 sequence_deltas[4U * SWAPZ_SEGMENT_BLOCKS];
	static swapz_u32 sequence_bases[4];
	const char *const phases[] = {
		"live_bytes_overflow", "io_cost_overflow", "min_blocks_overflow"
	};
	const swapz_u32 logical = 7U;
	struct swapz_builder builder;
	struct swapz_tx transaction;
	struct swapz_map durable_map;
	struct swapz_decoded decoded;
	const swapz_u8 *readback;
	swapz_u8 durable_roles[sizeof(segment_roles)];
	swapz_u32 durable_live_bytes, durable_io_cost;
	swapz_u16 durable_min_blocks;
	unsigned int failure_case;

	CHECK(swapz_authority_init(&a, maps, live, classes, 32, 1024) == 0);
	CHECK(swapz_enable_extent_sequence_index(
	      &a, sequence_deltas, sequence_bases, 4) == 0);
	a.reuse_dead_segments = 1;
	CHECK(swapz_enable_segment_rotation(&a, segment_roles, 4) == 0);
	CHECK(swapz_enable_segment_mapping_counts(&a, segment_maps, 4) == 0);
	CHECK(swapz_enable_segment_gc_accounting(
	      &a, segment_bytes, segment_io, segment_min_blocks, 4) == 0);
	memset(p0, 0x3c, sizeof(p0));
	memset(raw_replacement, 0xa7, sizeof(raw_replacement));
	CHECK(swapz_stage(&a, &logical, 1, 1, &transaction) == 0);
	CHECK(swapz_begin(&builder, previous_extent, sizeof(previous_extent),
			  transaction.sequence) == 0);
	CHECK(swapz_append(&builder, logical,
			   transaction.records[0].generation,
			   p0, sizeof(p0)) == 0);
	CHECK(swapz_seal(&builder) == 0);
	CHECK(swapz_finish(&a, &transaction, previous_extent,
			   sizeof(previous_extent), 1, 0) == 0);
	durable_map = maps[logical];
	durable_live_bytes = segment_bytes[0];
	durable_io_cost = segment_io[0];
	durable_min_blocks = segment_min_blocks[0];
	memcpy(durable_roles, segment_roles, sizeof(durable_roles));
	CHECK(durable_map.valid && !durable_map.raw &&
	      durable_map.generation == 1U &&
	      durable_live_bytes == sizeof(p0) + sizeof(struct swapz_record));

	for (failure_case = 0; failure_case < 3; ++failure_case) {
		struct gc_cost_snapshot expected;
		swapz_u32 failed_block;
		int actual_error, read_error;
		int state_retained, byte_exact;

		if (failure_case == 0)
			segment_bytes[0] = ~(swapz_u32)0;
		else if (failure_case == 1)
			segment_io[0] = ~(swapz_u32)0;
		else
			segment_min_blocks[0] = (swapz_u16)~0U;
		expected = gc_cost_capture(logical);
		CHECK(swapz_stage(&a, &logical, 1, 1, &transaction) == 0);
		failed_block = transaction.start_block;
		/* A lower-complete write is not an authority publication. */
		actual_error = swapz_finish_raw(&a, &transaction,
					       raw_replacement, 1, 0);
		state_retained = !memcmp(&maps[logical], &durable_map,
					 sizeof(durable_map)) &&
			!a.in_flight && !a.gc_allocation &&
			segment_maps[0] == expected.mapped_count &&
			segment_bytes[0] == expected.live_bytes &&
			segment_io[0] == expected.io_cost &&
			segment_min_blocks[0] == expected.min_blocks &&
			a.committed_blocks == expected.committed_blocks &&
			a.abandoned_blocks == expected.abandoned_blocks + 1U &&
			a.next_block == failed_block + 1U &&
			failed_block < a.physical_blocks &&
			!live[failed_block] && !classes[failed_block] &&
			live[durable_map.start_block] == 1U &&
			classes[durable_map.start_block] == 1U &&
			!memcmp(segment_roles, durable_roles,
				sizeof(durable_roles));
		readback = NULL;
		read_error = swapz_peek(previous_extent, sizeof(previous_extent),
					durable_map.record_index, &decoded);
		if (!read_error)
			read_error = swapz_read_authoritative_peeked(
				&a, logical, &durable_map, previous_extent,
				sizeof(previous_extent), &decoded, &readback);
		byte_exact = !read_error && readback &&
			     decoded.generation == durable_map.generation &&
			     decoded.payload_length == sizeof(p0) &&
			     !memcmp(readback, p0, sizeof(p0));
		if (actual_error != -EOVERFLOW || !state_retained || !byte_exact) {
			fprintf(stderr,
				"GC_COST_FAIL phase=%s victim=none reserve=untouched "
				"expected_errno=%d observed_errno=%d "
				"expected_progress=0 observed_progress=%u "
				"state_retained=%d byte_exact=%d "
				"expected_generation=%u observed_generation=%u "
				"failed_block=%u abandoned=%u\n",
				phases[failure_case], -EOVERFLOW, actual_error,
				maps[logical].generation != durable_map.generation,
				state_retained, byte_exact, durable_map.generation,
				maps[logical].generation, failed_block,
				a.abandoned_blocks);
			return 1;
		}
		/* Undo only synthetic corrupt sidecars, never the failed cursor. */
		segment_bytes[0] = durable_live_bytes;
		segment_io[0] = durable_io_cost;
		segment_min_blocks[0] = durable_min_blocks;
	}

	/* A later valid publication must use fresh media and generation two. */
	CHECK(swapz_stage(&a, &logical, 1, 1, &transaction) == 0);
	CHECK(transaction.start_block == 4U);
	CHECK(swapz_finish_raw(&a, &transaction, raw_replacement, 1, 0) == 0);
	CHECK(maps[logical].raw && maps[logical].generation == 2U);
	CHECK(swapz_verify_raw(&a, logical, raw_replacement) == 0);
	CHECK(segment_bytes[0] == SWAPZ_BLOCK_BYTES);
	CHECK(segment_io[0] == 2U * SWAPZ_BLOCK_BYTES);
	CHECK(segment_min_blocks[0] == 1U);
	CHECK(!memcmp(segment_roles, durable_roles, sizeof(durable_roles)));
	return 0;
}

int main(void)
{
	int passed = 0;

	CHECK(test_bytes_vs_count_victim_policy() == 0); passed++;
	CHECK(test_raw_and_invalid_cost() == 0); passed++;
	CHECK(test_invalid_compressed_extent_classes() == 0); passed++;
	CHECK(test_exact_committed_payload_lengths() == 0); passed++;
	CHECK(test_failed_lower_writes_preserve_committed_costs() == 0); passed++;
	CHECK(test_io_aware_cost_corrects_loaded_gc_counterexample() == 0); passed++;
	CHECK(test_reclaim_headroom_preflight() == 0); passed++;
	CHECK(test_proven_large_record_gc_block_bound() == 0); passed++;
	CHECK(test_saturated_gc_accounting_preserves_durable_generation() == 0); passed++;
	printf("SWAPZ_GC_COST_TESTS_PASS=%d\n", passed);
	return 0;
}
