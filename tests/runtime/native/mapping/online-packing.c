// SPDX-License-Identifier: GPL-2.0-only
/*
 * Exercise the EXACT kernel SWZ3 codec + authority + bounded I/O engine C
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
static struct swapz_authority authority;
static struct swapz_map maps[LOGICAL_PAGES];
static swapz_u16 live[PHYSICAL_BLOCKS];
static swapz_u8 classes[PHYSICAL_BLOCKS];
static swapz_u8 scratch_write[SWAPZ_MAX_EXTENT_BYTES];
static swapz_u8 scratch_read[SWAPZ_MAX_EXTENT_BYTES];
static swapz_u8 scratch_metadata_cache[
	SWAPZ_READ_METADATA_CACHE_ENTRIES * SWAPZ_BLOCK_BYTES];
static swapz_u8 originals[64][2072];

struct memory_disk {
	swapz_u8 *storage;
	swapz_u32 write_calls;
	swapz_u32 write_blocks;
	swapz_u32 read_blocks;
	swapz_u32 fail_write_on_call;
	int fail_reads;
};

static struct memory_disk disk;
static struct swapz_engine engine;

static int lower_write(void *opaque, swapz_u32 start, swapz_u8 blocks,
		       const swapz_u8 *payload, swapz_u8 *completed)
{
	struct memory_disk *m = opaque;
	swapz_u8 permitted = blocks;

	*completed = 0;
	if (start >= PHYSICAL_BLOCKS ||
	    (swapz_u32)blocks > PHYSICAL_BLOCKS - start)
		return -ERANGE;
	m->write_calls++;
	if (m->write_calls == m->fail_write_on_call)
		permitted = blocks > 1 ? 1 : 0;
	if (permitted) {
		memcpy(m->storage + (size_t)start * SWAPZ_BLOCK_BYTES, payload,
		       (size_t)permitted * SWAPZ_BLOCK_BYTES);
		m->write_blocks += permitted;
		*completed = permitted;
	}
	return permitted == blocks ? 0 : -EIO;
}

static int lower_read(void *opaque, swapz_u32 start, swapz_u8 blocks,
		      swapz_u8 *target)
{
	struct memory_disk *m = opaque;

	if (m->fail_reads)
		return -EIO;
	if (start >= PHYSICAL_BLOCKS ||
	    (swapz_u32)blocks > PHYSICAL_BLOCKS - start)
		return -ERANGE;
	memcpy(target, m->storage + (size_t)start * SWAPZ_BLOCK_BYTES,
	       (size_t)blocks * SWAPZ_BLOCK_BYTES);
	m->read_blocks += blocks;
	return 0;
}

static int setup(void)
{
	memset(disk.storage, 0, (size_t)PHYSICAL_BLOCKS * SWAPZ_BLOCK_BYTES);
	disk.write_calls = 0;
	disk.write_blocks = 0;
	disk.read_blocks = 0;
	disk.fail_write_on_call = 0;
	disk.fail_reads = 0;
	if (swapz_authority_init(&authority, maps, live, classes,
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

static void prepare(struct swapz_compressed_page *pages, swapz_u8 count,
		    swapz_u32 base, int salt)
{
	swapz_u8 index;

	for (index = 0; index < count; ++index) {
		memset(originals[index], (int)(index + salt + 1),
		       sizeof(originals[index]));
		pages[index].logical_page = base + index;
		pages[index].payload = originals[index];
		pages[index].payload_crc32c = 0;
		pages[index].length = sizeof(originals[index]);
		pages[index].payload_crc_valid = 0;
		pages[index].raw = 0;
	}
}

static int plan_default(const struct swapz_compressed_page *pages,
			swapz_u8 count, swapz_u8 *classes,
			swapz_u8 *records_per_extent, swapz_u8 *extent_count)
{
	return swapz_engine_plan_bounded(pages, count, 0, classes,
					 records_per_extent, extent_count);
}

static int write_window_sequential(const struct swapz_compressed_page *pages,
				   swapz_u8 count,
				   swapz_u8 *committed_pages)
{
	swapz_u8 bulk = engine.bulk_enabled;
	int error;

	engine.bulk_enabled = 0;
	error = swapz_engine_write_window_batched(&engine, pages, count,
						 committed_pages);
	engine.bulk_enabled = bulk;
	return error;
}

static int test_finite_window_planner(void)
{
	struct swapz_compressed_page pages[16];
	swapz_u8 classes[SWAPZ_MAX_RECORDS], takes[SWAPZ_MAX_RECORDS], groups = 0;
	swapz_u32 blocks = 0;
	swapz_u8 i;
	unsigned int total = 0;

	prepare(pages, 16, 0, 0);
	CHECK(plan_default(pages, 16, classes, takes, &groups) == 0);
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
	CHECK(plan_default(pages, 16, classes, takes, &groups) ==
	      -EOPNOTSUPP);
	pages[0].payload = originals[0];
	pages[0].length = 4096; /* raw cannot masquerade as SWZ3 compressed */
	CHECK(plan_default(pages, 16, classes, takes, &groups) ==
	      -EOPNOTSUPP);
	return 0;
}

static int test_full_window_and_selective_reads(void)
{
	struct swapz_compressed_page pages[16];
	struct swapz_decoded decoded;
	const swapz_u8 *stored;
	swapz_u8 output[3568], committed = 0;
	swapz_u16 length = 0;
	swapz_u32 index;
	swapz_u32 reads;

	CHECK(setup() == 0);
	prepare(pages, 16, 0, 0);
	CHECK(write_window_sequential(pages, 16, &committed) == 0);
	CHECK(committed == 16 && !authority.in_flight);
	CHECK(engine.submitted_blocks == 10);
	CHECK(engine.completed_blocks == 10);
	CHECK(disk.write_blocks == 10);
	/* Preserve the existing cold, metadata-first lower-block bound:
	 * disable prefetch and reuse for BOTH loops in this test. */
	engine.max_read_blocks_per_record = 1;
	for (index = 0; index < 16; ++index) {
		swapz_engine_invalidate_read_cache(&engine);
		CHECK(maps[index].valid && maps[index].generation == 1);
		CHECK(swapz_engine_read_page(&engine, index,
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
		const struct swapz_map *m = &maps[index];
		int expected;

		CHECK(swapz_lookup(disk.storage +
				 (size_t)m->start_block * SWAPZ_BLOCK_BYTES,
				 m->extent_blocks * SWAPZ_BLOCK_BYTES,
				 m->record_index, &decoded, &stored) == 0);
		{
			swapz_u32 first = decoded.payload_offset / SWAPZ_BLOCK_BYTES;
			swapz_u32 last = ((swapz_u32)decoded.payload_offset +
				decoded.payload_length - 1U) / SWAPZ_BLOCK_BYTES;

			expected = (int)(last - first + 1U + (first ? 1U : 0U));
		}
		CHECK(expected >= 1 && expected <= 3);
		swapz_engine_invalidate_read_cache(&engine);
		disk.read_blocks = 0;
		CHECK(swapz_engine_read_page(&engine, index,
					   output, sizeof(output), &length) == 0);
		CHECK(disk.read_blocks == (swapz_u32)expected);
	}
	return 0;
}

static int test_metadata_lru64_reuses_validated_block_zero(void)
{
	struct swapz_compressed_page pages[64];
	swapz_u8 committed = 0, output[3568];
	swapz_u16 length = 0;
	swapz_u32 i;
	swapz_u32 reads_before;

	CHECK(setup() == 0);
	memset(scratch_metadata_cache, 0, sizeof(scratch_metadata_cache));
	engine.read_metadata_cache = scratch_metadata_cache;
	engine.max_read_blocks_per_record = 1;
	prepare(pages, 64, 0, 0);
	CHECK(write_window_sequential(pages, 64, &committed) == 0);
	CHECK(committed == 64);

	/* Five distinct one-block extents evict the real one-entry cache but not
	 * the bounded 64-entry metadata cache. A successful LRU hit must return
	 * exact data without issuing another lower read. */
	for (i = 0; i < 5; ++i)
		CHECK(swapz_engine_read_page(&engine, i, output,
					   sizeof(output), &length) == 0);
	reads_before = disk.read_blocks;
	CHECK(swapz_engine_read_page(&engine, 0, output,
				   sizeof(output), &length) == 0);
	CHECK(length == 2072 && !memcmp(output, originals[0], length));
	CHECK(disk.read_blocks == reads_before);
	CHECK(engine.read_metadata_cache_hits == 0);
	CHECK(engine.read_metadata_lru_hits == 1);

	/* The ordinary mutation fence clears residency. Re-reading after an
	 * explicit invalidation must hit the lower device again. */
	swapz_engine_invalidate_read_cache(&engine);
	/* Repeated mutation fences on an already-empty metadata LRU are a
	 * semantic no-op; the optimized invalidation skips redundant clearing. */
	swapz_engine_invalidate_read_cache(&engine);
	reads_before = disk.read_blocks;
	CHECK(swapz_engine_read_page(&engine, 0, output,
				   sizeof(output), &length) == 0);
	CHECK(disk.read_blocks == reads_before + 1);
	CHECK(engine.read_metadata_lru_hits == 1);

	/* A real engine write invokes the same invalidation before publication.
	 * The old cached block-zero must never survive a generation change. */
	prepare(pages, 1, 0, 70);
	committed = 0;
	CHECK(write_window_sequential(pages, 1, &committed) == 0);
	CHECK(committed == 1 && maps[0].generation == 2);
	reads_before = disk.read_blocks;
	CHECK(swapz_engine_read_page(&engine, 0, output,
				   sizeof(output), &length) == 0);
	CHECK(disk.read_blocks == reads_before + 1);
	CHECK(length == 2072 && output[0] == 71);

	/* The measured capacity retains an entry across 63 distinct successors. */
	swapz_engine_invalidate_read_cache(&engine);
	CHECK(swapz_engine_read_page(&engine, 0, output,
				   sizeof(output), &length) == 0);
	for (i = 1; i < 64; ++i)
		CHECK(swapz_engine_read_page(&engine, i, output,
					   sizeof(output), &length) == 0);
	/* Page 0 is still resident after only 63 distinct successors. */
	reads_before = disk.read_blocks;
	CHECK(swapz_engine_read_page(&engine, 0, output,
				   sizeof(output), &length) == 0);
	CHECK(disk.read_blocks == reads_before);
	CHECK(engine.read_metadata_lru_hits == 2);
	return 0;
}

static int test_full_extent_corruption_rejected(void)
{
	struct swapz_compressed_page pages[7];
	swapz_u8 output[3568], committed = 0;
	swapz_u16 length = 0;
	struct swapz_decoded d;
	const swapz_u8 *stored;
	struct swapz_map map;

	CHECK(setup() == 0);
	prepare(pages, 7, 0, 0);
	CHECK(write_window_sequential(pages, 7, &committed) == 0);
	CHECK(committed == 7);
	map = maps[6];
	CHECK(swapz_lookup(disk.storage +
			 (size_t)map.start_block * SWAPZ_BLOCK_BYTES,
			 map.extent_blocks * SWAPZ_BLOCK_BYTES,
			 map.record_index, &d, &stored) == 0);
	disk.storage[(size_t)map.start_block * SWAPZ_BLOCK_BYTES +
		     d.payload_offset] ^= 1;
	CHECK(swapz_engine_read_page(&engine, 6,
				   output, sizeof(output), &length) == -EBADMSG);
	CHECK(length == 0);
	return 0;
}

static int test_torn_extent_quarantined_without_authority(void)
{
	struct swapz_compressed_page pages[16];
	swapz_u8 committed = 0;

	CHECK(setup() == 0);
	prepare(pages, 16, 0, 0);
	disk.fail_write_on_call = 1;
	CHECK(write_window_sequential(pages, 16, &committed) == -EIO);
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
	struct swapz_compressed_page pages[16];
	swapz_u8 chosen[SWAPZ_MAX_RECORDS], takes[SWAPZ_MAX_RECORDS], groups = 0;
	swapz_u8 committed = 0;
	swapz_u8 output[3568];
	swapz_u16 len = 0;
	swapz_u32 index;

	CHECK(setup() == 0);
	prepare(pages, 16, 0, 0);
	CHECK(plan_default(pages, 16, chosen, takes, &groups) == 0);
	CHECK(groups > 1);
	disk.fail_write_on_call = 2;
	CHECK(write_window_sequential(pages, 16, &committed) == -EIO);
	CHECK(committed == takes[0]);
	for (index = 0; index < committed; ++index) {
		CHECK(maps[index].valid);
		CHECK(swapz_engine_read_page(&engine, index,
					   output, sizeof(output), &len) == 0);
	}
	for (index = committed; index < 16; ++index)
		CHECK(!maps[index].valid);
	CHECK(!authority.in_flight);
	return 0;
}

static int test_overwrite_old_mapping_survives_failure(void)
{
	struct swapz_compressed_page pages[7];
	swapz_u8 committed = 0, output[3568];
	swapz_u16 length = 0;
	struct swapz_map previous;

	CHECK(setup() == 0);
	prepare(pages, 7, 0, 0);
	CHECK(write_window_sequential(pages, 7, &committed) == 0);
	previous = maps[0];
	prepare(pages, 7, 0, 70);
	disk.fail_write_on_call = disk.write_calls + 1;
	committed = 0;
	CHECK(write_window_sequential(pages, 7, &committed) == -EIO);
	CHECK(committed == 0);
	CHECK(maps[0].start_block == previous.start_block &&
	      maps[0].generation == previous.generation);
	CHECK(swapz_engine_read_page(&engine, 0,
				   output, sizeof(output), &length) == 0);
	CHECK(output[0] == 1 && length == 2072);
	disk.fail_write_on_call = 0;
	CHECK(write_window_sequential(pages, 7, &committed) == 0);
	CHECK(committed == 7 && maps[0].generation == 2);
	CHECK(swapz_engine_read_page(&engine, 0,
				   output, sizeof(output), &length) == 0);
	CHECK(output[0] == 71);
	return 0;
}

static int test_lower_read_failure_does_not_fake_bytes(void)
{
	struct swapz_compressed_page pages[1];
	swapz_u8 committed = 0, output[3568];
	swapz_u16 length = 321;

	CHECK(setup() == 0);
	prepare(pages, 1, 0, 0);
	CHECK(write_window_sequential(pages, 1, &committed) == 0);
	disk.fail_reads = 1;
	CHECK(swapz_engine_read_page(&engine, 0, output,
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
	struct swapz_compressed_page pages[16];
	swapz_u8 planned[SWAPZ_MAX_RECORDS], takes[SWAPZ_MAX_RECORDS], groups;
	swapz_u8 committed, output[3568];
	swapz_u16 length;
	swapz_u32 class_blocks, i, j;
	swapz_u8 cap;

	prepare(pages, 16, 0, 0);
	CHECK(swapz_engine_plan_bounded(pages, 16, 4, planned,
				      takes, &groups) == -EINVAL);
	for (cap = 0; cap <= 3; ++cap) {
		CHECK(setup() == 0);
		prepare(pages, 16, 0, 0);
		engine.max_read_blocks_per_record = cap;
		CHECK(swapz_engine_plan_bounded(pages, 16, cap, planned,
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
		CHECK(write_window_sequential(pages, 16,
					      &committed) == 0);
		CHECK(committed == 16);
		CHECK(disk.write_blocks == class_blocks);
		for (i = 0; i < 16; ++i) {
			disk.read_blocks = 0;
			CHECK(swapz_engine_read_page(&engine, i, output,
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
	struct swapz_compressed_page pages[7];
	swapz_u8 output[3568], committed = 0;
	swapz_u16 length = 91;
	swapz_u16 original;

	CHECK(setup() == 0);
	prepare(pages, 7, 0, 0);
	CHECK(write_window_sequential(pages, 7, &committed) == 0);
	CHECK(committed == 7 && maps[6].valid);
	original = maps[6].payload_length;
	CHECK(original == 2072);
	maps[6].payload_length = original - 1;
	disk.read_blocks = 0;
	CHECK(swapz_engine_read_page(&engine, 6, output,
				   sizeof(output), &length) == -EUCLEAN);
	CHECK(length == 0 && disk.read_blocks == 1);
	/* Restore the accurate authoritative length. The physical payload
	 * was never modified; reading it must still succeed byte-for-byte. */
	maps[6].payload_length = original;
	CHECK(swapz_engine_read_page(&engine, 6, output,
				   sizeof(output), &length) == 0);
	CHECK(length == original && !memcmp(output, originals[6], length));
	return 0;
}

int main(void)
{
	int completed = 0;

	disk.storage = calloc(PHYSICAL_BLOCKS, SWAPZ_BLOCK_BYTES);
	CHECK(disk.storage != NULL);
	CHECK(test_finite_window_planner() == 0); completed++;
	CHECK(test_full_window_and_selective_reads() == 0); completed++;
	CHECK(test_metadata_lru64_reuses_validated_block_zero() == 0); completed++;
	CHECK(test_full_extent_corruption_rejected() == 0); completed++;
	CHECK(test_torn_extent_quarantined_without_authority() == 0); completed++;
	CHECK(test_failure_second_extent_reports_prefix() == 0); completed++;
	CHECK(test_overwrite_old_mapping_survives_failure() == 0); completed++;
	CHECK(test_lower_read_failure_does_not_fake_bytes() == 0); completed++;
	CHECK(test_read_budget_tradeoff_on_uniform_2072() == 0); completed++;
	CHECK(test_mapping_length_mismatch_stops_before_payload_io() == 0); completed++;
	free(disk.storage);
	printf("SWAPZ_EXACT_ENGINE_TESTS_PASS=%d\n", completed);
	return 0;
}
