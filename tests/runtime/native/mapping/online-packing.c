// SPDX-License-Identifier: GPL-2.0-only
/*
 * Exercise the EXACT kernel V3 codec + authority + bounded I/O engine C
 * against a deterministic fault-injectable RAM lower device. No /dev access.
 */
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "engine.h"
#include "window-policy.h"

#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "%s:%d: FAIL: %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)

#define PHYSICAL_BLOCKS 2048U
#define LOGICAL_PAGES 64U
static struct sv3_authority authority;
static struct sv3_map maps[LOGICAL_PAGES];
static sv3_u16 live[PHYSICAL_BLOCKS];
static sv3_u8 classes[PHYSICAL_BLOCKS];
static sv3_u8 scratch_write[SV3_MAX_EXTENT_BYTES];
static sv3_u8 scratch_read[SV3_MAX_EXTENT_BYTES];
static sv3_u8 originals[64][2072];

struct memory_disk {
	sv3_u8 *storage;
	sv3_u32 write_calls;
	sv3_u32 write_blocks;
	sv3_u32 read_blocks;
	sv3_u32 fail_write_on_call;
	int fail_reads;
};

static struct memory_disk disk;
static struct sv3_engine engine;

static int lower_write(void *opaque, sv3_u32 start, sv3_u8 blocks,
		       const sv3_u8 *payload, sv3_u8 *completed)
{
	struct memory_disk *m = opaque;
	sv3_u8 permitted = blocks;

	*completed = 0;
	if (start >= PHYSICAL_BLOCKS ||
	    (sv3_u32)blocks > PHYSICAL_BLOCKS - start)
		return -ERANGE;
	m->write_calls++;
	if (m->write_calls == m->fail_write_on_call)
		permitted = blocks > 1 ? 1 : 0;
	if (permitted) {
		memcpy(m->storage + (size_t)start * SV3_BLOCK_BYTES, payload,
		       (size_t)permitted * SV3_BLOCK_BYTES);
		m->write_blocks += permitted;
		*completed = permitted;
	}
	return permitted == blocks ? 0 : -EIO;
}

static int lower_read(void *opaque, sv3_u32 start, sv3_u8 blocks,
		      sv3_u8 *target)
{
	struct memory_disk *m = opaque;

	if (m->fail_reads)
		return -EIO;
	if (start >= PHYSICAL_BLOCKS ||
	    (sv3_u32)blocks > PHYSICAL_BLOCKS - start)
		return -ERANGE;
	memcpy(target, m->storage + (size_t)start * SV3_BLOCK_BYTES,
	       (size_t)blocks * SV3_BLOCK_BYTES);
	m->read_blocks += blocks;
	return 0;
}

static int setup(void)
{
	memset(disk.storage, 0, (size_t)PHYSICAL_BLOCKS * SV3_BLOCK_BYTES);
	disk.write_calls = 0;
	disk.write_blocks = 0;
	disk.read_blocks = 0;
	disk.fail_write_on_call = 0;
	disk.fail_reads = 0;
	if (sv3_authority_init(&authority, maps, live, classes,
			       LOGICAL_PAGES, PHYSICAL_BLOCKS))
		return 1;
	memset(&engine, 0, sizeof(engine));
	engine.authority = &authority;
	engine.io.opaque = &disk;
	engine.io.write_extent = lower_write;
	engine.io.read_blocks = lower_read;
	engine.write_scratch = scratch_write;
	engine.read_scratch = scratch_read;
	return 0;
}

static void prepare(struct sv3_compressed_page *pages, sv3_u8 count,
		    sv3_u32 base, int salt)
{
	sv3_u8 index;

	for (index = 0; index < count; ++index) {
		memset(originals[index], (int)(index + salt + 1),
		       sizeof(originals[index]));
		pages[index].logical_page = base + index;
		pages[index].payload = originals[index];
		pages[index].length = sizeof(originals[index]);
		pages[index].raw = 0;
	}
}

static int test_finite_window_planner(void)
{
	struct sv3_compressed_page pages[16];
	sv3_u8 classes[SV3_MAX_RECORDS], takes[SV3_MAX_RECORDS], groups = 0;
	sv3_u32 blocks = 0;
	sv3_u8 i;
	unsigned int total = 0;

	prepare(pages, 16, 0, 0);
	CHECK(sv3_engine_plan(pages, 16, classes, takes, &groups) == 0);
	for (i = 0; i < groups; ++i) {
		CHECK(classes[i] == 1 || classes[i] == 2 || classes[i] == 4);
		CHECK(takes[i] && takes[i] <= 7);
		total += takes[i];
		blocks += classes[i];
	}
	CHECK(total == 16);
	/* 7+7+2 records in aligned 16K+16K+8K = 40KiB. */
	CHECK(blocks == 10);
	CHECK(groups >= 3 && groups <= 5); /* read amplification breaks byte ties */

	pages[0].payload = NULL;
	CHECK(sv3_engine_plan(pages, 16, classes, takes, &groups) ==
	      -EOPNOTSUPP);
	pages[0].payload = originals[0];
	pages[0].length = 4096; /* raw cannot masquerade as V3 compressed */
	CHECK(sv3_engine_plan(pages, 16, classes, takes, &groups) ==
	      -EOPNOTSUPP);
	return 0;
}

static int test_planner_stats_quantify_cap_tradeoff(void)
{
	struct sv3_compressed_page pages[16];
	sv3_u16 blocks = 99;
	sv3_u8 extents = 99, four = 99;

	prepare(pages, 16, 0, 0);
	CHECK(sv3_engine_plan_stats(pages, 16, 0,
				    &blocks, &extents, &four) == 0);
	CHECK(blocks == 10);
	/* Equal-byte plans prefer lower predicted read cost: 3+3+3+7. */
	CHECK(extents == 4);
	CHECK(four == 1);

	blocks = 99;
	extents = four = 99;
	CHECK(sv3_engine_plan_stats(pages, 16, 2,
				    &blocks, &extents, &four) == 0);
	CHECK(blocks == 11);
	CHECK(extents == 6);
	CHECK(four == 0);

	blocks = 99;
	extents = four = 99;
	CHECK(sv3_engine_plan_stats(pages, 16, 3,
				    &blocks, &extents, &four) == 0);
	CHECK(blocks == 10);
	CHECK(extents == 4);
	CHECK(four == 1);
	CHECK(!sv3_window_cap3_pareto_candidate(10, 11, 10, 1));

	blocks = 99;
	extents = four = 99;
	CHECK(sv3_engine_plan_stats(pages, 16, 4,
				    &blocks, &extents, &four) == -EINVAL);
	CHECK(blocks == 0 && extents == 0 && four == 0);
	return 0;
}

static int test_planner_stats_pareto_tail_candidate(void)
{
	static const sv3_u16 lengths[13] = {
		2546, 1813, 2689, 2003, 2975, 2759, 2292,
		2916, 2922, 2416, 2806, 2912, 2597,
	};
	struct sv3_compressed_page pages[13];
	sv3_u16 uncapped_blocks = 0, cap2_blocks = 0, cap3_blocks = 0;
	sv3_u8 extents = 0, uncapped_four = 0, cap2_four = 0, cap3_four = 0;
	sv3_u8 index;

	/* plan_stats validates pointers/lengths but never dereferences payload. */
	for (index = 0; index < 13; ++index) {
		pages[index].logical_page = index;
		pages[index].payload = originals[index];
		pages[index].length = lengths[index];
		pages[index].raw = 0;
	}
	CHECK(sv3_engine_plan_stats(pages, 13, 0, &uncapped_blocks,
				    &extents, &uncapped_four) == 0);
	CHECK(uncapped_blocks == 9 && extents == 4 && uncapped_four == 1);
	CHECK(sv3_engine_plan_stats(pages, 13, 2, &cap2_blocks,
				    &extents, &cap2_four) == 0);
	CHECK(cap2_blocks == 11 && extents == 9 && cap2_four == 0);
	CHECK(sv3_engine_plan_stats(pages, 13, 3, &cap3_blocks,
				    &extents, &cap3_four) == 0);
	CHECK(cap3_blocks == 9 && extents == 4 && cap3_four == 1);
	CHECK(sv3_window_cap3_pareto_candidate(uncapped_blocks, cap2_blocks,
				       cap3_blocks, cap3_four));
	return 0;
}

static int test_full_window_and_selective_reads(void)
{
	struct sv3_compressed_page pages[16];
	struct sv3_decoded decoded;
	const sv3_u8 *stored;
	sv3_u8 output[3568], committed = 0;
	sv3_u16 length = 0;
	sv3_u32 index;
	sv3_u32 reads;

	CHECK(setup() == 0);
	prepare(pages, 16, 0, 0);
	CHECK(sv3_engine_write_window(&engine, pages, 16, &committed) == 0);
	CHECK(committed == 16 && !authority.in_flight);
	CHECK(engine.submitted_blocks == 10);
	CHECK(engine.completed_blocks == 10);
	CHECK(disk.write_blocks == 10);
	/* Preserve the existing cold, metadata-first lower-block bound:
	 * disable prefetch and reuse for BOTH loops in this test. */
	engine.max_read_blocks_per_record = 1;
	for (index = 0; index < 16; ++index) {
		sv3_engine_invalidate_read_cache(&engine);
		CHECK(maps[index].valid && maps[index].generation == 1);
		CHECK(sv3_engine_read_page(&engine, index,
					   output, sizeof(output), &length) == 0);
		CHECK(length == 2072);
		CHECK(!memcmp(output, originals[index], length));
	}
	reads = disk.read_blocks;
	CHECK(reads == engine.physical_read_blocks);
	CHECK(reads >= 16 && reads <= 48);
	/* Preserve the original exact metadata-first selective-read contract.
	 * Explicitly disable two-block prefetch for these per-page read-budget
	 * checks and invalidate any warm metadata before each sample. The
	 * separate engine tests verify the bounded full-extent fast path. */
	for (index = 0; index < 16; ++index) {
		const struct sv3_map *m = &maps[index];
		int expected;

		CHECK(sv3_lookup(disk.storage +
				 (size_t)m->start_block * SV3_BLOCK_BYTES,
				 m->extent_blocks * SV3_BLOCK_BYTES,
				 m->record_index, &decoded, &stored) == 0);
		expected = sv3_record_read_blocks(&decoded);
		CHECK(expected >= 1 && expected <= 3);
		sv3_engine_invalidate_read_cache(&engine);
		disk.read_blocks = 0;
		CHECK(sv3_engine_read_page(&engine, index,
					   output, sizeof(output), &length) == 0);
		CHECK(disk.read_blocks == (sv3_u32)expected);
	}
	return 0;
}

static int test_full_extent_corruption_rejected(void)
{
	struct sv3_compressed_page pages[7];
	sv3_u8 output[3568], committed = 0;
	sv3_u16 length = 0;
	struct sv3_decoded d;
	const sv3_u8 *stored;
	struct sv3_map map;

	CHECK(setup() == 0);
	prepare(pages, 7, 0, 0);
	CHECK(sv3_engine_write_window(&engine, pages, 7, &committed) == 0);
	CHECK(committed == 7);
	map = maps[6];
	CHECK(sv3_lookup(disk.storage +
			 (size_t)map.start_block * SV3_BLOCK_BYTES,
			 map.extent_blocks * SV3_BLOCK_BYTES,
			 map.record_index, &d, &stored) == 0);
	disk.storage[(size_t)map.start_block * SV3_BLOCK_BYTES +
		     d.payload_offset] ^= 1;
	CHECK(sv3_engine_read_page(&engine, 6,
				   output, sizeof(output), &length) == -EBADMSG);
	CHECK(length == 0);
	return 0;
}

static int test_torn_extent_quarantined_without_authority(void)
{
	struct sv3_compressed_page pages[16];
	sv3_u8 committed = 0;

	CHECK(setup() == 0);
	prepare(pages, 16, 0, 0);
	disk.fail_write_on_call = 1;
	CHECK(sv3_engine_write_window(&engine, pages, 16, &committed) == -EIO);
	CHECK(committed == 0);
	CHECK(authority.abandoned_blocks >= 2);
	CHECK(authority.next_block == authority.abandoned_blocks);
	CHECK(engine.submitted_blocks > engine.completed_blocks);
	CHECK(disk.write_blocks == engine.completed_blocks);
	CHECK(!maps[0].valid && !maps[15].valid);
	CHECK(!authority.in_flight);
	return 0;
}

static int test_failure_second_extent_reports_prefix(void)
{
	struct sv3_compressed_page pages[16];
	sv3_u8 chosen[SV3_MAX_RECORDS], takes[SV3_MAX_RECORDS], groups = 0;
	sv3_u8 committed = 0;
	sv3_u8 output[3568];
	sv3_u16 len = 0;
	sv3_u32 index;

	CHECK(setup() == 0);
	prepare(pages, 16, 0, 0);
	CHECK(sv3_engine_plan(pages, 16, chosen, takes, &groups) == 0);
	CHECK(groups > 1);
	disk.fail_write_on_call = 2;
	CHECK(sv3_engine_write_window(&engine, pages, 16, &committed) == -EIO);
	CHECK(committed == takes[0]);
	for (index = 0; index < committed; ++index) {
		CHECK(maps[index].valid);
		CHECK(sv3_engine_read_page(&engine, index,
					   output, sizeof(output), &len) == 0);
	}
	for (index = committed; index < 16; ++index)
		CHECK(!maps[index].valid);
	CHECK(!authority.in_flight);
	return 0;
}

static int test_overwrite_old_mapping_survives_failure(void)
{
	struct sv3_compressed_page pages[7];
	sv3_u8 committed = 0, output[3568];
	sv3_u16 length = 0;
	struct sv3_map previous;

	CHECK(setup() == 0);
	prepare(pages, 7, 0, 0);
	CHECK(sv3_engine_write_window(&engine, pages, 7, &committed) == 0);
	previous = maps[0];
	prepare(pages, 7, 0, 70);
	disk.fail_write_on_call = disk.write_calls + 1;
	committed = 0;
	CHECK(sv3_engine_write_window(&engine, pages, 7, &committed) == -EIO);
	CHECK(committed == 0);
	CHECK(maps[0].start_block == previous.start_block &&
	      maps[0].generation == previous.generation);
	CHECK(sv3_engine_read_page(&engine, 0,
				   output, sizeof(output), &length) == 0);
	CHECK(output[0] == 1 && length == 2072);
	disk.fail_write_on_call = 0;
	CHECK(sv3_engine_write_window(&engine, pages, 7, &committed) == 0);
	CHECK(committed == 7 && maps[0].generation == 2);
	CHECK(sv3_engine_read_page(&engine, 0,
				   output, sizeof(output), &length) == 0);
	CHECK(output[0] == 71);
	return 0;
}

static int test_lower_read_failure_does_not_fake_bytes(void)
{
	struct sv3_compressed_page pages[1];
	sv3_u8 committed = 0, output[3568];
	sv3_u16 length = 321;

	CHECK(setup() == 0);
	prepare(pages, 1, 0, 0);
	CHECK(sv3_engine_write_window(&engine, pages, 1, &committed) == 0);
	disk.fail_reads = 1;
	CHECK(sv3_engine_read_page(&engine, 0, output,
				   sizeof(output), &length) == -EIO);
	CHECK(length == 0 && engine.physical_read_blocks == 0);
	return 0;
}

/*
 * Force the actual planner and full read path to honor a cold-read cap.
 * Unlike read-cost tie-breaking, this permits an explicit write/read
 * tradeoff for a latency-sensitive host.
 */
static int test_read_budget_tradeoff_on_uniform_2072(void)
{
	struct sv3_compressed_page pages[16];
	sv3_u8 planned[SV3_MAX_RECORDS], takes[SV3_MAX_RECORDS], groups;
	sv3_u8 committed, output[3568];
	sv3_u16 length;
	sv3_u32 class_blocks, i, j;
	sv3_u8 cap;

	prepare(pages, 16, 0, 0);
	CHECK(sv3_engine_plan_bounded(pages, 16, 4, planned,
				      takes, &groups) == -EINVAL);
	for (cap = 0; cap <= 3; ++cap) {
		CHECK(setup() == 0);
		prepare(pages, 16, 0, 0);
		engine.max_read_blocks_per_record = cap;
		CHECK(sv3_engine_plan_bounded(pages, 16, cap, planned,
					      takes, &groups) == 0);
		class_blocks = 0;
		j = 0;
		for (i = 0; i < groups; ++i) {
			CHECK(planned[i] == 1 || planned[i] == 2 ||
			      planned[i] == 4);
			class_blocks += planned[i];
			j += takes[i];
		}
		CHECK(j == 16);
		committed = 99;
		CHECK(sv3_engine_write_window(&engine, pages, 16,
					      &committed) == 0);
		CHECK(committed == 16);
		CHECK(disk.write_blocks == class_blocks);
		for (i = 0; i < 16; ++i) {
			disk.read_blocks = 0;
			CHECK(sv3_engine_read_page(&engine, i, output,
						   sizeof(output), &length) == 0);
			CHECK(length == 2072);
			CHECK(!memcmp(output, originals[i], length));
			CHECK(!cap || disk.read_blocks <= cap);
		}
		if (cap == 0 || cap == 3)
			CHECK(class_blocks == 10);
		if (cap == 1)
			CHECK(class_blocks == 16);
		if (cap == 2)
			CHECK(class_blocks == 11);
	}
	return 0;
}

static int test_mapping_length_mismatch_stops_before_payload_io(void)
{
	struct sv3_compressed_page pages[7];
	sv3_u8 output[3568], committed = 0;
	sv3_u16 length = 91;
	sv3_u16 original;

	CHECK(setup() == 0);
	prepare(pages, 7, 0, 0);
	CHECK(sv3_engine_write_window(&engine, pages, 7, &committed) == 0);
	CHECK(committed == 7 && maps[6].valid);
	original = maps[6].payload_length;
	CHECK(original == 2072);
	maps[6].payload_length = original - 1;
	disk.read_blocks = 0;
	CHECK(sv3_engine_read_page(&engine, 6, output,
				   sizeof(output), &length) == -EUCLEAN);
	CHECK(length == 0 && disk.read_blocks == 1);
	/* Restore the accurate authoritative length. The physical payload
	 * was never modified; reading it must still succeed byte-for-byte. */
	maps[6].payload_length = original;
	CHECK(sv3_engine_read_page(&engine, 6, output,
				   sizeof(output), &length) == 0);
	CHECK(length == original && !memcmp(output, originals[6], length));
	return 0;
}

int main(void)
{
	int completed = 0;

	disk.storage = calloc(PHYSICAL_BLOCKS, SV3_BLOCK_BYTES);
	CHECK(disk.storage != NULL);
	CHECK(test_finite_window_planner() == 0); completed++;
	CHECK(test_planner_stats_quantify_cap_tradeoff() == 0); completed++;
	CHECK(test_planner_stats_pareto_tail_candidate() == 0); completed++;
	CHECK(test_full_window_and_selective_reads() == 0); completed++;
	CHECK(test_full_extent_corruption_rejected() == 0); completed++;
	CHECK(test_torn_extent_quarantined_without_authority() == 0); completed++;
	CHECK(test_failure_second_extent_reports_prefix() == 0); completed++;
	CHECK(test_overwrite_old_mapping_survives_failure() == 0); completed++;
	CHECK(test_lower_read_failure_does_not_fake_bytes() == 0); completed++;
	CHECK(test_read_budget_tradeoff_on_uniform_2072() == 0); completed++;
	CHECK(test_mapping_length_mismatch_stops_before_payload_io() == 0); completed++;
	free(disk.storage);
	printf("SV3_EXACT_ENGINE_TESTS_PASS=%d\n", completed);
	return 0;
}
