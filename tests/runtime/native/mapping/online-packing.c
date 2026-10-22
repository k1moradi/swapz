// SPDX-License-Identifier: GPL-2.0-only
/*
 * Exercise the EXACT kernel SWZ codec + authority + bounded I/O engine C
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
static swapz_u8 scratch_read_second[SWAPZ_MAX_EXTENT_BYTES];
static swapz_u8 scratch_read_third[SWAPZ_MAX_EXTENT_BYTES];
static swapz_u8 scratch_coalesced[2U * SWAPZ_MAX_EXTENT_BYTES];
static swapz_u8 scratch_metadata_cache[
	SWAPZ_READ_METADATA_CACHE_ENTRIES * SWAPZ_BLOCK_BYTES];
static swapz_u8 scratch_extent_cache[
	SWAPZ_READ_EXTENT_CACHE_ENTRIES * SWAPZ_MAX_EXTENT_BYTES];
static swapz_u8 originals[64][2072];

struct memory_disk {
	swapz_u8 *storage;
	swapz_u32 write_calls;
	swapz_u32 write_blocks;
	swapz_u32 read_calls;
	swapz_u32 read_blocks;
	swapz_u32 read_block_hits[PHYSICAL_BLOCKS];
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
	swapz_u32 block;

	if (m->fail_reads)
		return -EIO;
	if (start >= PHYSICAL_BLOCKS ||
	    (swapz_u32)blocks > PHYSICAL_BLOCKS - start)
		return -ERANGE;
	memcpy(target, m->storage + (size_t)start * SWAPZ_BLOCK_BYTES,
	       (size_t)blocks * SWAPZ_BLOCK_BYTES);
	m->read_calls++;
	m->read_blocks += blocks;
	for (block = 0; block < blocks; ++block)
		m->read_block_hits[start + block]++;
	return 0;
}

static int setup(void)
{
	memset(disk.storage, 0, (size_t)PHYSICAL_BLOCKS * SWAPZ_BLOCK_BYTES);
	disk.write_calls = 0;
	disk.write_blocks = 0;
	disk.read_calls = 0;
	disk.read_blocks = 0;
	memset(disk.read_block_hits, 0, sizeof(disk.read_block_hits));
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
		/*
		 * Initialize the complete descriptor. The optional precomputed-CRC
		 * fields must start clear so native callers use the ordinary hashing
		 * path unless they explicitly provide a matching payload CRC.
		 */
		pages[index] = (struct swapz_compressed_page) {
			.logical_page = base + index,
			.payload = originals[index],
			.length = sizeof(originals[index]),
			.raw = 0,
		};
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
	pages[0].length = 4096; /* raw cannot masquerade as SWZ compressed */
	CHECK(plan_default(pages, 16, classes, takes, &groups) ==
	      -EOPNOTSUPP);
	return 0;
}

static int test_uniform_pack_cliff_reduces_physical_blocks(void)
{
	struct swapz_compressed_page pages[9];
	swapz_u8 classes[SWAPZ_MAX_RECORDS], takes[SWAPZ_MAX_RECORDS];
	swapz_u8 groups = 0, index;
	swapz_u32 blocks = 0;

	prepare(pages, 9, 0, 0);
	CHECK(swapz_engine_next_uniform_pack_limit(2072) == 2030);
	CHECK(swapz_engine_next_uniform_pack_limit(2024) == 1802);
	CHECK(swapz_engine_next_uniform_pack_limit(1500) == 1472);
	CHECK(swapz_engine_next_uniform_pack_limit(568) == 566);
	CHECK(swapz_engine_next_uniform_pack_limit(1) == 0);
	CHECK(swapz_engine_next_uniform_pack_limit(3569) == 0);

	for (index = 0; index < 9; ++index)
		pages[index].length = 1803;
	CHECK(plan_default(pages, 9, classes, takes, &groups) == 0);
	for (index = 0; index < groups; ++index)
		blocks += classes[index];
	/* Five blocks are byte-minimal at 1803. The existing read-cost
	 * tie-breaker correctly prefers five one-block extents here. */
	CHECK(blocks == 5 && groups == 5);

	blocks = 0;
	for (index = 0; index < 9; ++index)
		pages[index].length = 1802;
	CHECK(plan_default(pages, 9, classes, takes, &groups) == 0);
	for (index = 0; index < groups; ++index)
		blocks += classes[index];
	CHECK(blocks == 4 && groups == 1 && classes[0] == 4 && takes[0] == 9);
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

static int test_metadata_set_cache_reuses_validated_block_zero(void)
{
	struct swapz_compressed_page pages[64];
	swapz_u8 committed = 0, output[3568];
	swapz_u16 length = 0;
	swapz_u32 i;
	swapz_u32 reads_before;
	swapz_u32 epoch_before, epoch_after;

	CHECK(setup() == 0);
	CHECK(sizeof(struct swapz_read_metadata_tag) == 16);
	CHECK(((uintptr_t)&engine.read_metadata_tags[0] & 63U) == 0);
	CHECK((uintptr_t)&engine.read_metadata_tags[4] -
	      (uintptr_t)&engine.read_metadata_tags[0] == 64);
	memset(scratch_metadata_cache, 0, sizeof(scratch_metadata_cache));
	engine.read_metadata_cache = scratch_metadata_cache;
	engine.max_read_blocks_per_record = 1;
	prepare(pages, 64, 0, 0);
	CHECK(write_window_sequential(pages, 64, &committed) == 0);
	CHECK(committed == 64);

	/* Five distinct one-block extents evict the real one-entry cache but not
	 * the 512-entry four-way metadata cache. A successful set hit must return
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
	CHECK(engine.read_metadata_set_hits >= 1);
	CHECK(engine.read_metadata_set_probes <=
	      8U * engine.read_metadata_set_lookups);
	CHECK(engine.read_metadata_copy_bytes == 2072);

	/* The ordinary mutation fence invalidates by epoch. Re-reading after it
	 * must hit the lower device again without clearing the 512-tag directory. */
	epoch_before = engine.read_metadata_epoch;
	swapz_engine_invalidate_read_cache(&engine);
	epoch_after = engine.read_metadata_epoch;
	CHECK(epoch_before != 0 && epoch_after != epoch_before);
	CHECK(engine.read_metadata_lru_clock == 0);
	/* Repeated mutation fences on an already-empty metadata LRU are a
	 * semantic no-op and must not churn the epoch. */
	swapz_engine_invalidate_read_cache(&engine);
	CHECK(engine.read_metadata_epoch == epoch_after);
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
	CHECK(engine.read_metadata_copy_bytes == 4144);
	return 0;
}

static int test_metadata_siblings_keep_unique_tags_in_a_full_set(void)
{
	struct swapz_compressed_page pages[28];
	swapz_u8 output[3568], committed;
	swapz_u16 length = 0, first_slot = 0, last_slot = 0;
	swapz_u32 extent, record, slot, valid = 0, matches = 0;
	swapz_u32 epoch, reads_before;

	CHECK(setup() == 0);
	engine.read_metadata_cache = scratch_metadata_cache;
	engine.read_extent_cache = scratch_extent_cache;
	prepare(pages, 28, 0, 0);
	/* All four starts hash into the same four-way set. Use real engine
	 * writes and authoritative maps, leaving unused physical gaps only
	 * to construct this collision fixture. */
	for (extent = 0; extent < 4; ++extent) {
		authority.next_block = extent * 128U;
		committed = 0;
		CHECK(write_window_sequential(pages + extent * 7U, 7,
					      &committed) == 0);
		CHECK(committed == 7);
		CHECK(maps[extent * 7U].start_block == extent * 128U);
		CHECK(maps[extent * 7U].extent_blocks == 4);
	}
	for (extent = 0; extent < 4; ++extent)
		CHECK(swapz_engine_read_page(&engine, extent * 7U, output,
					   sizeof(output), &length) == 0);
	epoch = engine.read_metadata_epoch;
	CHECK(epoch != 0 && engine.read_metadata_set_replacements == 0);
	for (slot = 0; slot < SWAPZ_READ_METADATA_CACHE_ENTRIES; ++slot) {
		if (engine.read_metadata_tags[slot].epoch != epoch)
			continue;
		if (!valid)
			first_slot = slot;
		last_slot = slot;
		valid++;
	}
	CHECK(valid == 4 && last_slot == first_slot + 3U);
	CHECK(first_slot / 4U == last_slot / 4U);
	CHECK(engine.read_metadata_tags[last_slot].start_block == 384U);

	/* A hole before a matching tag must not terminate the commit scan.
	 * The scratch hit below skips the initial metadata-set lookup. */
	engine.read_metadata_tags[first_slot].epoch = 0;
	CHECK(swapz_engine_read_page(&engine, 21, output,
				   sizeof(output), &length) == 0);
	CHECK(engine.read_metadata_tags[first_slot].epoch == 0);
	CHECK(engine.read_metadata_tags[last_slot].start_block == 384U);
	engine.read_metadata_tags[first_slot].epoch = epoch;

	/* Payloads are appended from the end of the extent. With seven
	 * 2072-byte records, record zero occupies block 3, so the four cold
	 * reads above have already fetched blocks 0 and 3 for every extent. */
	for (extent = 0; extent < 4; ++extent) {
		swapz_u32 start = extent * 128U;

		CHECK(disk.read_block_hits[start] == 1);
		CHECK(disk.read_block_hits[start + 1U] == 0);
		CHECK(disk.read_block_hits[start + 2U] == 0);
		CHECK(disk.read_block_hits[start + 3U] == 1);
	}
	reads_before = disk.read_blocks;
	for (record = 0; record < 7; ++record)
		for (extent = 0; extent < 4; ++extent) {
			swapz_u32 logical = extent * 7U + record;

			CHECK(swapz_engine_read_page(&engine, logical, output,
						   sizeof(output), &length) == 0);
			CHECK(length == 2072);
			CHECK(!memcmp(output, originals[logical], length));
		}
	/* The sibling sweep needs only blocks 1 and 2: two additional blocks
	 * per extent, with each physical block fetched exactly once overall. */
	CHECK(disk.read_blocks == reads_before + 8U);
	for (extent = 0; extent < 4; ++extent) {
		swapz_u32 start = extent * 128U;

		CHECK(disk.read_block_hits[start] == 1);
		CHECK(disk.read_block_hits[start + 1U] == 1);
		CHECK(disk.read_block_hits[start + 2U] == 1);
		CHECK(disk.read_block_hits[start + 3U] == 1);
	}
	reads_before = disk.read_blocks;
	for (extent = 0; extent < 4; ++extent)
		CHECK(swapz_engine_read_page(&engine, extent * 7U, output,
					   sizeof(output), &length) == 0);
	CHECK(disk.read_blocks == reads_before);
	CHECK(engine.read_metadata_set_replacements == 0);
	for (extent = 0; extent < 4; ++extent) {
		matches = 0;
		for (slot = first_slot; slot <= last_slot; ++slot)
			if (engine.read_metadata_tags[slot].epoch == epoch &&
			    engine.read_metadata_tags[slot].start_block == extent * 128U &&
			    engine.read_metadata_tags[slot].extent_blocks == 4)
				matches++;
		CHECK(matches == 1);
	}
	return 0;
}

static int test_metadata_secondary_choice_retains_primary_collisions(void)
{
	struct swapz_compressed_page pages[63];
	swapz_u8 output[3568], committed;
	swapz_u16 length = 0, primary_base = SWAPZ_READ_METADATA_CACHE_ENTRIES;
	swapz_u16 secondary_slot = SWAPZ_READ_METADATA_CACHE_ENTRIES, outside_slot;
	swapz_u32 extent, slot, valid = 0, matches;
	swapz_u32 epoch, reads_before, hits_before;
	unsigned long long primary_before, secondary_before, probes_before;

	CHECK(setup() == 0);
	engine.read_metadata_cache = scratch_metadata_cache;
	/* Leave the optional full-extent cache off. Interleaving distinct
	 * extents then exercises the metadata directory rather than scratch. */
	prepare(pages, 63, 0, 0);
	for (extent = 0; extent < 9; ++extent) {
		/* The primary hash folds start>>9 into its low seven bits.
		 * These nine starts all collide there, across five segments. */
		authority.next_block = extent * 128U + extent / 4U;
		committed = 0;
		CHECK(write_window_sequential(pages + extent * 7U, 7,
					      &committed) == 0);
		CHECK(committed == 7);
		CHECK(maps[extent * 7U].start_block == extent * 128U + extent / 4U);
		CHECK(maps[extent * 7U].extent_blocks == 4);
	}
	for (extent = 0; extent < 9; ++extent)
		CHECK(swapz_engine_read_page(&engine, extent * 7U, output,
					   sizeof(output), &length) == 0);
	epoch = engine.read_metadata_epoch;
	CHECK(engine.read_metadata_set_replacements == 0);
	for (slot = 0; slot < SWAPZ_READ_METADATA_CACHE_ENTRIES; ++slot) {
		if (engine.read_metadata_tags[slot].epoch != epoch)
			continue;
		valid++;
		if (engine.read_metadata_tags[slot].start_block == maps[0].start_block)
			primary_base = slot - slot % SWAPZ_READ_METADATA_CACHE_WAYS;
		if (engine.read_metadata_tags[slot].start_block == maps[28].start_block)
			secondary_slot = slot;
	}
	/* Five secondary residents require at least two different secondary
	 * sets; a fixed second set would already have evicted one of nine. */
	CHECK(valid == 9);
	CHECK(primary_base < SWAPZ_READ_METADATA_CACHE_ENTRIES);
	CHECK(secondary_slot < SWAPZ_READ_METADATA_CACHE_ENTRIES);
	CHECK(secondary_slot / SWAPZ_READ_METADATA_CACHE_WAYS !=
	      primary_base / SWAPZ_READ_METADATA_CACHE_WAYS);
	reads_before = engine.read_metadata_requests;
	hits_before = engine.read_metadata_lru_hits;
	primary_before = engine.read_metadata_primary_hits;
	secondary_before = engine.read_metadata_secondary_hits;
	probes_before = engine.read_metadata_set_probes;
	for (extent = 0; extent < 9; ++extent) {
		swapz_u32 logical = extent * 7U;

		CHECK(swapz_engine_read_page(&engine, logical, output,
					   sizeof(output), &length) == 0);
		CHECK(length == 2072 && !memcmp(output, originals[logical], length));
	}
	CHECK(engine.read_metadata_requests == reads_before);
	CHECK(engine.read_metadata_lru_hits == hits_before + 9U);
	CHECK(engine.read_metadata_primary_hits == primary_before + 4U);
	CHECK(engine.read_metadata_secondary_hits == secondary_before + 5U);
	CHECK(engine.read_metadata_set_probes - probes_before <= 9U * 8U);
	CHECK(engine.read_metadata_set_hits == engine.read_metadata_primary_hits +
	      engine.read_metadata_secondary_hits);

	/* A scratch hit must find its secondary tag even if a primary way is
	 * now invalid. Refill scratch through real lower I/O with the optional
	 * directory temporarily bypassed, then restore the existing tags. */
	engine.read_metadata_cache = NULL;
	engine.read_cache_valid = 0;
	CHECK(swapz_engine_read_page(&engine, 28, output,
				   sizeof(output), &length) == 0);
	engine.read_metadata_cache = scratch_metadata_cache;
	engine.read_metadata_tags[primary_base].epoch = 0;
	CHECK(swapz_engine_read_page(&engine, 28, output,
				   sizeof(output), &length) == 0);
	CHECK(engine.read_metadata_tags[primary_base].epoch == 0);
	CHECK(engine.read_metadata_tags[secondary_slot].epoch == epoch);
	matches = 0;
	for (slot = 0; slot < SWAPZ_READ_METADATA_CACHE_ENTRIES; ++slot)
		if (engine.read_metadata_tags[slot].epoch == epoch &&
		    engine.read_metadata_tags[slot].start_block == maps[28].start_block)
			matches++;
	CHECK(matches == 1 && engine.read_metadata_set_replacements == 0);

	/* Fill both candidate sets (and all other ways) with distinct dummy
	 * keys. Only the two candidate lines may supply the victim. Make a
	 * secondary way oldest and a noncandidate way even older. */
	for (slot = 0; slot < SWAPZ_READ_METADATA_CACHE_ENTRIES; ++slot) {
		engine.read_metadata_tags[slot].start_block = PHYSICAL_BLOCKS + slot;
		engine.read_metadata_tags[slot].extent_blocks = 4;
		engine.read_metadata_tags[slot].epoch = epoch;
		engine.read_metadata_tags[slot].age = 50;
	}
	engine.read_metadata_tags[secondary_slot].age = 2;
	engine.read_metadata_tags[primary_base].age = 3;
	outside_slot = (primary_base + SWAPZ_READ_METADATA_CACHE_WAYS) %
		SWAPZ_READ_METADATA_CACHE_ENTRIES;
	if (outside_slot / SWAPZ_READ_METADATA_CACHE_WAYS ==
	    secondary_slot / SWAPZ_READ_METADATA_CACHE_WAYS)
		outside_slot = (outside_slot + SWAPZ_READ_METADATA_CACHE_WAYS) %
			SWAPZ_READ_METADATA_CACHE_ENTRIES;
	engine.read_metadata_tags[outside_slot].age = 1;
	engine.read_metadata_lru_clock = 100;
	engine.read_cache_valid = 0;
	probes_before = engine.read_metadata_set_probes;
	CHECK(swapz_engine_read_page(&engine, 28, output,
				   sizeof(output), &length) == 0);
	CHECK(length == 2072 && !memcmp(output, originals[28], length));
	CHECK(engine.read_metadata_set_probes == probes_before + 8U);
	CHECK(engine.read_metadata_set_replacements == 1);
	CHECK(engine.read_metadata_tags[secondary_slot].start_block == maps[28].start_block);
	CHECK(engine.read_metadata_tags[primary_base].start_block == PHYSICAL_BLOCKS + primary_base);
	CHECK(engine.read_metadata_tags[outside_slot].start_block == PHYSICAL_BLOCKS + outside_slot);

	/* Both mutation-epoch wrap and age-clock wrap must invalidate both
	 * choices before accepting any tag in a new epoch. */
	engine.read_metadata_epoch = ~(swapz_u32)0;
	swapz_engine_invalidate_read_cache(&engine);
	CHECK(engine.read_metadata_epoch == 1);
	for (slot = 0; slot < SWAPZ_READ_METADATA_CACHE_ENTRIES; ++slot)
		CHECK(engine.read_metadata_tags[slot].epoch == 0);
	CHECK(swapz_engine_read_page(&engine, 28, output,
				   sizeof(output), &length) == 0);
	engine.read_metadata_lru_clock = ~(swapz_u32)0;
	CHECK(swapz_engine_read_page(&engine, 28, output,
				   sizeof(output), &length) == 0);
	CHECK(engine.read_metadata_epoch == 2 && engine.read_metadata_lru_clock == 1);
	CHECK(length == 2072 && !memcmp(output, originals[28], length));
	return 0;
}

static int test_four_block_extent_reuses_each_payload_block_once(void)
{
	struct swapz_compressed_page pages[7];
	swapz_u8 output[3568], committed = 0;
	swapz_u16 length = 0;
	swapz_u32 start, index;

	CHECK(setup() == 0);
	prepare(pages, 7, 0, 0);
	CHECK(write_window_sequential(pages, 7, &committed) == 0);
	CHECK(committed == 7);
	start = maps[0].start_block;
	for (index = 0; index < 7; ++index) {
		CHECK(maps[index].valid);
		CHECK(maps[index].start_block == start);
		CHECK(maps[index].extent_blocks == 4);
	}

	disk.read_blocks = 0;
	memset(disk.read_block_hits, 0, sizeof(disk.read_block_hits));
	swapz_engine_invalidate_read_cache(&engine);
	CHECK(engine.read_cached_block_mask == 0);
	for (index = 0; index < 7; ++index) {
		CHECK(swapz_engine_read_page(&engine, index, output,
					   sizeof(output), &length) == 0);
		CHECK(length == 2072);
		CHECK(!memcmp(output, originals[index], length));
	}
	CHECK(disk.read_blocks == 4);
	for (index = 0; index < 4; ++index)
		CHECK(disk.read_block_hits[start + index] == 1);
	CHECK(engine.read_cached_block_mask == 0x0fU);
	CHECK(engine.read_cached_full == 1);

	swapz_engine_invalidate_read_cache(&engine);
	CHECK(engine.read_cached_block_mask == 0);
	CHECK(engine.read_cached_full == 0);

	/* Production writes use the same mutation fence before lower I/O. */
	prepare(pages, 1, 0, 70);
	committed = 0;
	CHECK(write_window_sequential(pages, 1, &committed) == 0);
	CHECK(committed == 1);
	CHECK(engine.read_cached_block_mask == 0);
	CHECK(engine.read_cache_valid == 0);
	return 0;
}

static int test_extent_lru_reuses_eight_interleaved_extents(void)
{
	struct swapz_compressed_page pages[56];
	swapz_u8 output[3568], committed;
	swapz_u16 length = 0;
	swapz_u32 extent, record, start;

	CHECK(setup() == 0);
	memset(scratch_metadata_cache, 0, sizeof(scratch_metadata_cache));
	memset(scratch_extent_cache, 0, sizeof(scratch_extent_cache));
	engine.read_metadata_cache = scratch_metadata_cache;
	engine.read_extent_cache = scratch_extent_cache;
	engine.max_read_blocks_per_record = 0;
	prepare(pages, 56, 0, 0);
	for (extent = 0; extent < 8; ++extent) {
		committed = 0;
		CHECK(write_window_sequential(pages + extent * 7U, 7,
					      &committed) == 0);
		CHECK(committed == 7);
		start = maps[extent * 7U].start_block;
		for (record = 0; record < 7; ++record) {
			CHECK(maps[extent * 7U + record].start_block == start);
			CHECK(maps[extent * 7U + record].extent_blocks == 4);
		}
	}

	disk.read_blocks = 0;
	memset(disk.read_block_hits, 0, sizeof(disk.read_block_hits));
	swapz_engine_invalidate_read_cache(&engine);
	for (record = 0; record < 7; ++record)
		for (extent = 0; extent < 8; ++extent) {
			swapz_u32 logical = extent * 7U + record;

			CHECK(swapz_engine_read_page(&engine, logical, output,
						   sizeof(output), &length) == 0);
			CHECK(length == 2072);
			CHECK(!memcmp(output, originals[logical], length));
		}
	CHECK(disk.read_blocks == 8U * 4U);
	for (extent = 0; extent < 8; ++extent) {
		start = maps[extent * 7U].start_block;
		for (record = 0; record < 4; ++record)
			CHECK(disk.read_block_hits[start + record] == 1);
	}
	CHECK(engine.read_extent_lru_clock != 0);
	swapz_engine_invalidate_read_cache(&engine);
	CHECK(engine.read_extent_lru_clock == 0);
	for (extent = 0; extent < SWAPZ_READ_EXTENT_CACHE_ENTRIES; ++extent)
		CHECK(engine.read_extent_lru_valid[extent] == 0);
	return 0;
}

static int test_prime_absorb_preserves_shared_read_residency(void)
{
	struct swapz_compressed_page pages[7];
	struct swapz_engine slot, probe;
	swapz_u8 slot_scratch[SWAPZ_MAX_EXTENT_BYTES];
	swapz_u8 probe_scratch[SWAPZ_MAX_EXTENT_BYTES];
	swapz_u8 output[3568], committed = 0;
	swapz_u16 length = 0;
	swapz_u32 start;
	swapz_u8 slot_mask;
	swapz_u8 *saved_extent_cache;

	CHECK(setup() == 0);
	memset(scratch_metadata_cache, 0, sizeof(scratch_metadata_cache));
	memset(scratch_extent_cache, 0, sizeof(scratch_extent_cache));
	engine.read_metadata_cache = scratch_metadata_cache;
	engine.read_extent_cache = scratch_extent_cache;
	engine.max_read_blocks_per_record = 0;
	prepare(pages, 7, 0, 0);
	CHECK(write_window_sequential(pages, 7, &committed) == 0);
	CHECK(committed == 7);
	start = maps[0].start_block;
	CHECK(swapz_engine_read_page(&engine, 0, output,
				     sizeof(output), &length) == 0);

	memset(&slot, 0, sizeof(slot));
	memset(slot_scratch, 0, sizeof(slot_scratch));
	slot.authority = &authority;
	slot.io.opaque = &disk;
	slot.io.read_blocks = lower_read;
	slot.max_read_blocks_per_record = 0;
	slot.read_scratch = slot_scratch;
	swapz_engine_prime_read_slot(&engine, &slot, start, 4);
	CHECK(slot.read_cache_valid == 1);
	CHECK(slot.read_cached_start_block == start);
	CHECK(slot.read_cached_extent_blocks == 4);
	CHECK(slot.read_cached_block_mask != 0);
	CHECK(swapz_engine_read_page(&slot, 1, output,
				     sizeof(output), &length) == 0);
	slot_mask = slot.read_cached_block_mask;
	CHECK(slot_mask != 0);
	swapz_engine_absorb_read_slot(&engine, &slot);

	memset(&probe, 0, sizeof(probe));
	memset(probe_scratch, 0, sizeof(probe_scratch));
	probe.read_scratch = probe_scratch;
	swapz_engine_prime_read_slot(&engine, &probe, start, 4);
	CHECK(probe.read_cache_valid == 1);
	CHECK((probe.read_cached_block_mask & slot_mask) == slot_mask);

	/* Absorb also publishes block zero into the master's metadata LRU. */
	saved_extent_cache = engine.read_extent_cache;
	engine.read_extent_cache = NULL;
	engine.read_cache_valid = 0;
	memset(&probe, 0, sizeof(probe));
	memset(probe_scratch, 0, sizeof(probe_scratch));
	probe.read_scratch = probe_scratch;
	swapz_engine_prime_read_slot(&engine, &probe, start, 4);
	CHECK(probe.read_cache_valid == 1);
	CHECK(probe.read_cached_block_mask == 1U);
	engine.read_extent_cache = saved_extent_cache;
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

static void init_private_read_engine(struct swapz_engine *private,
				     swapz_u8 *scratch)
{
	memset(private, 0, sizeof(*private));
	memset(scratch, 0, SWAPZ_MAX_EXTENT_BYTES);
	private->authority = &authority;
	private->io.opaque = &disk;
	private->io.read_blocks = lower_read;
	private->read_scratch = scratch;
}

static int test_adjacent_distinct_extent_coalescing(void)
{
	struct swapz_compressed_page pages[3];
	struct swapz_engine first, second, third;
	struct swapz_engine *chain_engines[3] = { &first, &second, &third };
	swapz_u32 logical0[1] = { 0 }, logical1[1] = { 1 };
	swapz_u32 chain_starts[3];
	const swapz_u8 chain_extents[3] = { 1, 1, 1 };
	const swapz_u8 chain_first[3] = { 0, 0, 0 };
	const swapz_u8 chain_blocks[3] = { 1, 1, 1 };
	swapz_u32 combined_start;
	swapz_u8 committed = 0, first0, first1, blocks0, blocks1;
	swapz_u8 combined_blocks, output[3568];
	swapz_u16 length = 0;
	swapz_u32 corrupt_at;
	int error;

	CHECK(setup() == 0);
	prepare(pages, 3, 0, 0);
	CHECK(write_window_sequential(&pages[0], 1, &committed) == 0);
	CHECK(committed == 1);
	committed = 0;
	CHECK(write_window_sequential(&pages[1], 1, &committed) == 0);
	CHECK(committed == 1);
	committed = 0;
	CHECK(write_window_sequential(&pages[2], 1, &committed) == 0);
	CHECK(committed == 1);
	CHECK(maps[0].valid && maps[1].valid && maps[2].valid);
	CHECK(maps[0].extent_blocks == 1 && maps[1].extent_blocks == 1 &&
	      maps[2].extent_blocks == 1);
	CHECK(maps[0].start_block + 1U == maps[1].start_block);
	CHECK(maps[1].start_block + 1U == maps[2].start_block);
	chain_starts[0] = maps[0].start_block;
	chain_starts[1] = maps[1].start_block;
	chain_starts[2] = maps[2].start_block;

	init_private_read_engine(&first, scratch_read);
	init_private_read_engine(&second, scratch_read_second);
	CHECK(swapz_engine_required_read_range(&first, logical0, 1,
			maps[0].start_block, maps[0].extent_blocks,
			&first0, &blocks0) == 0);
	CHECK(swapz_engine_required_read_range(&second, logical1, 1,
			maps[1].start_block, maps[1].extent_blocks,
			&first1, &blocks1) == 0);
	CHECK(first0 == 0 && blocks0 == 1 && first1 == 0 && blocks1 == 1);
	CHECK(swapz_engine_coalesced_span(
			maps[0].start_block, maps[0].extent_blocks, first0, blocks0,
			maps[1].start_block, maps[1].extent_blocks, first1, blocks1,
			&combined_start, &combined_blocks) == 0);
	CHECK(combined_start == maps[0].start_block && combined_blocks == 2);
	/* Reverse physical order is equally valid. */
	CHECK(swapz_engine_coalesced_span(
			maps[1].start_block, maps[1].extent_blocks, first1, blocks1,
			maps[0].start_block, maps[0].extent_blocks, first0, blocks0,
			&combined_start, &combined_blocks) == 0);
	CHECK(combined_start == maps[0].start_block && combined_blocks == 2);
	/* A gap or a 1MiB segment crossing is never hidden by padding reads. */
	CHECK(swapz_engine_coalesced_span(10, 1, 0, 1, 12, 1, 0, 1,
			&combined_start, &combined_blocks) == -EOPNOTSUPP);
	CHECK(swapz_engine_coalesced_span(
			SWAPZ_SEGMENT_BLOCKS - 1U, 1, 0, 1,
			SWAPZ_SEGMENT_BLOCKS, 1, 0, 1,
			&combined_start, &combined_blocks) == -EOPNOTSUPP);

	disk.read_calls = 0;
	disk.read_blocks = 0;
	CHECK(swapz_engine_coalesce_read_pair(
			&first, &second,
			maps[0].start_block, maps[0].extent_blocks, first0, blocks0,
			maps[1].start_block, maps[1].extent_blocks, first1, blocks1,
			scratch_coalesced, 2U * SWAPZ_MAX_BLOCKS) == 0);
	CHECK(disk.read_calls == 1 && disk.read_blocks == 2);
	CHECK(first.physical_read_blocks == 1 && second.physical_read_blocks == 1);
	CHECK(first.read_coalesced_block_mask == 1U);
	CHECK(second.read_coalesced_block_mask == 1U);
	CHECK(swapz_engine_read_page(&first, 0, output,
				     sizeof(output), &length) == 0);
	CHECK(length == 2072 && !memcmp(output, originals[0], length));
	CHECK(swapz_engine_read_page(&second, 1, output,
				     sizeof(output), &length) == 0);
	CHECK(length == 2072 && !memcmp(output, originals[1], length));
	CHECK(disk.read_calls == 1);
	CHECK(first.read_coalesced_block_mask == 0);
	CHECK(second.read_coalesced_block_mask == 0);

	/* Three adjacent one-block ranges use the same 32KiB scratch and one
	 * lower callback. Each constituent still validates its own payload CRC. */
	init_private_read_engine(&first, scratch_read);
	init_private_read_engine(&second, scratch_read_second);
	init_private_read_engine(&third, scratch_read_third);
	disk.read_calls = 0;
	disk.read_blocks = 0;
	CHECK(swapz_engine_coalesce_read_chain(
			chain_engines, chain_starts, chain_extents,
			chain_first, chain_blocks, 3,
			scratch_coalesced, 2U * SWAPZ_MAX_BLOCKS) == 0);
	CHECK(disk.read_calls == 1 && disk.read_blocks == 3);
	CHECK(first.physical_read_blocks == 1 &&
	      second.physical_read_blocks == 1 &&
	      third.physical_read_blocks == 1);
	CHECK(swapz_engine_read_page(&first, 0, output,
				     sizeof(output), &length) == 0);
	CHECK(swapz_engine_read_page(&second, 1, output,
				     sizeof(output), &length) == 0);
	CHECK(swapz_engine_read_page(&third, 2, output,
				     sizeof(output), &length) == 0);
	CHECK(disk.read_calls == 1);

	/* A gap is rejected before lower I/O. */
	init_private_read_engine(&first, scratch_read);
	init_private_read_engine(&second, scratch_read_second);
	init_private_read_engine(&third, scratch_read_third);
	{
		swapz_u32 gapped_starts[3] = {
			chain_starts[0], chain_starts[1], chain_starts[2] + 1U
		};

		disk.read_calls = 0;
		CHECK(swapz_engine_coalesce_read_chain(
				chain_engines, gapped_starts, chain_extents,
				chain_first, chain_blocks, 3,
				scratch_coalesced, 2U * SWAPZ_MAX_BLOCKS) ==
		      -EOPNOTSUPP);
		CHECK(disk.read_calls == 0);
	}

	/* A failed combined lower callback publishes no seeded private residency. */
	init_private_read_engine(&first, scratch_read);
	init_private_read_engine(&second, scratch_read_second);
	disk.fail_reads = 1;
	disk.read_calls = 0;
	error = swapz_engine_coalesce_read_pair(
			&first, &second,
			maps[0].start_block, 1, 0, 1,
			maps[1].start_block, 1, 0, 1,
			scratch_coalesced, 2U * SWAPZ_MAX_BLOCKS);
	CHECK(error == -EIO && disk.read_calls == 0);
	CHECK(!first.read_cache_valid && !second.read_cache_valid);
	disk.fail_reads = 0;

	/* Corruption fetched by the one combined request still fails the normal
	 * constituent CRC path; private seed bytes never become shared authority. */
	corrupt_at = maps[1].start_block * SWAPZ_BLOCK_BYTES +
		maps[1].payload_offset;
	disk.storage[corrupt_at] ^= 1U;
	init_private_read_engine(&first, scratch_read);
	init_private_read_engine(&second, scratch_read_second);
	disk.read_calls = 0;
	CHECK(swapz_engine_coalesce_read_pair(
			&first, &second,
			maps[0].start_block, 1, 0, 1,
			maps[1].start_block, 1, 0, 1,
			scratch_coalesced, 2U * SWAPZ_MAX_BLOCKS) == 0);
	CHECK(disk.read_calls == 1);
	CHECK(swapz_engine_read_page(&first, 0, output,
				     sizeof(output), &length) == 0);
	CHECK(swapz_engine_read_page(&second, 1, output,
				     sizeof(output), &length) == -EBADMSG);
	CHECK(!second.read_cache_valid);
	disk.storage[corrupt_at] ^= 1U;
	return 0;
}

static int test_private_read_telemetry_merge_preserves_cache_state(void)
{
	struct swapz_engine source;

	CHECK(setup() == 0);
	memset(&source, 0, sizeof(source));
	engine.physical_read_blocks = 7;
	engine.read_payload_requests = 3;
	source.physical_read_blocks = 5;
	source.read_metadata_requests = 2;
	source.read_payload_requests = 4;
	source.read_payload_blocks = 6;
	source.read_metadata_cache_hits = 1;
	source.read_metadata_set_lookups = 4;
	source.read_metadata_set_hits = 3;
	source.read_metadata_primary_hits = 1;
	source.read_metadata_secondary_hits = 2;
	source.read_metadata_set_probes = 21;
	source.read_full_extent_cache_hits = 2;
	source.read_cache_valid = 1;
	source.read_cached_start_block = 123;
	source.read_cached_extent_blocks = 4;
	source.read_cached_block_mask = 0x0fU;

	swapz_engine_merge_read_telemetry(&engine, &source);
	CHECK(engine.physical_read_blocks == 12);
	CHECK(engine.read_metadata_requests == 2);
	CHECK(engine.read_payload_requests == 7);
	CHECK(engine.read_payload_blocks == 6);
	CHECK(engine.read_metadata_cache_hits == 1);
	CHECK(engine.read_metadata_set_hits == 3);
	CHECK(engine.read_metadata_primary_hits == 1);
	CHECK(engine.read_metadata_secondary_hits == 2);
	CHECK(engine.read_metadata_set_probes == 21);
	CHECK(engine.read_full_extent_cache_hits == 2);
	CHECK(source.physical_read_blocks == 0);
	CHECK(source.read_metadata_requests == 0);
	CHECK(source.read_payload_requests == 0);
	CHECK(source.read_payload_blocks == 0);
	CHECK(source.read_metadata_set_hits == 0);
	CHECK(source.read_metadata_primary_hits == 0);
	CHECK(source.read_metadata_secondary_hits == 0);
	/* Telemetry transfer must not steal or invalidate private residency. */
	CHECK(source.read_cache_valid == 1);
	CHECK(source.read_cached_start_block == 123);
	CHECK(source.read_cached_extent_blocks == 4);
	CHECK(source.read_cached_block_mask == 0x0fU);
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
	CHECK(test_uniform_pack_cliff_reduces_physical_blocks() == 0); completed++;
	CHECK(test_full_window_and_selective_reads() == 0); completed++;
	CHECK(test_metadata_set_cache_reuses_validated_block_zero() == 0); completed++;
	CHECK(test_metadata_siblings_keep_unique_tags_in_a_full_set() == 0); completed++;
	CHECK(test_metadata_secondary_choice_retains_primary_collisions() == 0); completed++;
	CHECK(test_four_block_extent_reuses_each_payload_block_once() == 0); completed++;
	CHECK(test_extent_lru_reuses_eight_interleaved_extents() == 0); completed++;
	CHECK(test_prime_absorb_preserves_shared_read_residency() == 0); completed++;
	CHECK(test_full_extent_corruption_rejected() == 0); completed++;
	CHECK(test_torn_extent_quarantined_without_authority() == 0); completed++;
	CHECK(test_failure_second_extent_reports_prefix() == 0); completed++;
	CHECK(test_overwrite_old_mapping_survives_failure() == 0); completed++;
	CHECK(test_lower_read_failure_does_not_fake_bytes() == 0); completed++;
	CHECK(test_read_budget_tradeoff_on_uniform_2072() == 0); completed++;
	CHECK(test_adjacent_distinct_extent_coalescing() == 0); completed++;
	CHECK(test_mapping_length_mismatch_stops_before_payload_io() == 0); completed++;
	CHECK(test_private_read_telemetry_merge_preserves_cache_state() == 0); completed++;
	free(disk.storage);
	printf("SWAPZ_EXACT_ENGINE_TESTS_PASS=%d\n", completed);
	return 0;
}
