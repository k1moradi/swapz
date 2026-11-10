// SPDX-License-Identifier: GPL-2.0-only
/*
 * Exercise the exact production payload-only extent engine + RAM authority
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
static swapz_u8 extent_sequence_delta[PHYSICAL_BLOCKS];
static swapz_u32 segment_sequence_base[
	PHYSICAL_BLOCKS / SWAPZ_SEGMENT_BLOCKS];
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
/* Fixed preallocated storage for real batch prepare/complete regression. */
static swapz_u8 padding_run_bytes[SWAPZ_BULK_BLOCKS * SWAPZ_BLOCK_BYTES];
static struct swapz_tx padding_run_transactions[SWAPZ_MAX_RECORDS];
static swapz_u8 padding_segment_roles[
	PHYSICAL_BLOCKS / SWAPZ_SEGMENT_BLOCKS];
static swapz_u8 padding_raw_page[SWAPZ_BLOCK_BYTES];

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
			       LOGICAL_PAGES, PHYSICAL_BLOCKS) ||
	    swapz_enable_extent_sequence_index(
		    &authority, extent_sequence_delta, segment_sequence_base,
		    PHYSICAL_BLOCKS / SWAPZ_SEGMENT_BLOCKS))
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
	CHECK(swapz_engine_next_uniform_pack_limit(2072) == 2048);
	CHECK(swapz_engine_next_uniform_pack_limit(2024) == 1820);
	CHECK(swapz_engine_next_uniform_pack_limit(1500) == 1489);
	CHECK(swapz_engine_next_uniform_pack_limit(568) == 564);
	CHECK(swapz_engine_next_uniform_pack_limit(1) == 0);
	CHECK(swapz_engine_next_uniform_pack_limit(3569) == 0);

	for (index = 0; index < 9; ++index)
		pages[index].length = 1821;
	CHECK(plan_default(pages, 9, classes, takes, &groups) == 0);
	for (index = 0; index < groups; ++index)
		blocks += classes[index];
	/* Nine 1821-byte payloads exceed 16KiB. Five blocks are byte-minimal;
	 * the cold-read tie-breaker prefers five one-block extents. */
	CHECK(blocks == 5 && groups == 5);

	blocks = 0;
	for (index = 0; index < 9; ++index)
		pages[index].length = 1820;
	CHECK(plan_default(pages, 9, classes, takes, &groups) == 0);
	for (index = 0; index < groups; ++index)
		blocks += classes[index];
	CHECK(blocks == 4 && groups == 1 && classes[0] == 4 && takes[0] == 9);
	return 0;
}

static int test_full_window_and_selective_reads(void)
{
	struct swapz_compressed_page pages[16];
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
	/* Cold reads derive their exact range from RAM mapping metadata. Disable
	 * reuse between samples so every lower block count is independently visible. */
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
	CHECK(reads >= 16 && reads <= 32);
	/* Verify the exact payload-only selective-read contract from authoritative
	 * RAM offsets. No serialized header or descriptor block is read. */
	for (index = 0; index < 16; ++index) {
		const struct swapz_map *m = &maps[index];
		int expected;

		{
			swapz_u32 first = m->payload_offset / SWAPZ_BLOCK_BYTES;
			swapz_u32 last = ((swapz_u32)m->payload_offset +
				m->payload_length - 1U) / SWAPZ_BLOCK_BYTES;

			expected = (int)(last - first + 1U);
		}
		CHECK(expected >= 1 && expected <= 2);
		swapz_engine_invalidate_read_cache(&engine);
		disk.read_blocks = 0;
		CHECK(swapz_engine_read_page(&engine, index,
					   output, sizeof(output), &length) == 0);
		CHECK(disk.read_blocks == (swapz_u32)expected);
	}
	return 0;
}

/*
 * Under the explicit one-block cold-read budget, each compressed logical
 * payload must independently read its one lower data block and validate its
 * RAM-authoritative CRC. No former in-band metadata-cache hit is allowed to
 * satisfy a subsequent read, even with the block-zero LRU provisioned.
 */
static int test_one_block_budget_does_not_reuse_payload_cache(void)
{
	struct swapz_compressed_page pages[64];
	swapz_u8 committed = 0, output[3568];
	swapz_u16 length = 0;
	swapz_u32 index, reads_before;

	CHECK(setup() == 0);
	memset(scratch_metadata_cache, 0, sizeof(scratch_metadata_cache));
	engine.read_metadata_cache = scratch_metadata_cache;
	engine.max_read_blocks_per_record = 1;
	prepare(pages, 64, 0, 0);
	CHECK(write_window_sequential(pages, 64, &committed) == 0);
	CHECK(committed == 64);

	for (index = 0; index < 5; ++index) {
		reads_before = disk.read_blocks;
		CHECK(swapz_engine_read_page(&engine, index, output,
					   sizeof(output), &length) == 0);
		CHECK(length == 2072);
		CHECK(!memcmp(output, originals[index], length));
		CHECK(disk.read_blocks == reads_before + 1U);
	}
	reads_before = disk.read_blocks;
	CHECK(swapz_engine_read_page(&engine, 0, output,
				   sizeof(output), &length) == 0);
	CHECK(!memcmp(output, originals[0], length));
	CHECK(disk.read_blocks == reads_before + 1U);
	CHECK(engine.read_metadata_cache_hits == 0);
	CHECK(engine.read_metadata_lru_hits == 0);
	CHECK(engine.read_metadata_set_hits == 0);
	CHECK(engine.read_metadata_copy_bytes == 0);

	/* Mutation fences cannot resurrect a stale block-zero data cache. */
	swapz_engine_invalidate_read_cache(&engine);
	reads_before = disk.read_blocks;
	CHECK(swapz_engine_read_page(&engine, 0, output,
				   sizeof(output), &length) == 0);
	CHECK(disk.read_blocks == reads_before + 1U);

	prepare(pages, 1, 0, 70);
	committed = 0;
	CHECK(write_window_sequential(pages, 1, &committed) == 0);
	CHECK(committed == 1 && maps[0].generation == 2);
	reads_before = disk.read_blocks;
	CHECK(swapz_engine_read_page(&engine, 0, output,
				   sizeof(output), &length) == 0);
	CHECK(disk.read_blocks == reads_before + 1U);
	CHECK(length == 2072 && output[0] == 71);

	/* Even 63 intervening successful reads never turn the 64th into a
	 * retained payload hit under the one-block cold-read policy. */
	swapz_engine_invalidate_read_cache(&engine);
	for (index = 1; index < 64; ++index) {
		reads_before = disk.read_blocks;
		CHECK(swapz_engine_read_page(&engine, index, output,
					   sizeof(output), &length) == 0);
		CHECK(length == 2072);
		CHECK(!memcmp(output, originals[index], length));
		CHECK(disk.read_blocks == reads_before + 1U);
	}
	reads_before = disk.read_blocks;
	CHECK(swapz_engine_read_page(&engine, 0, output,
				   sizeof(output), &length) == 0);
	CHECK(length == 2072 && output[0] == 71);
	CHECK(disk.read_blocks == reads_before + 1U);
	CHECK(engine.read_metadata_lru_hits == 0);
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
		CHECK(swapz_engine_read_page(&engine, extent * 7U + 6U, output,
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
	CHECK(swapz_engine_read_page(&engine, 27, output,
				   sizeof(output), &length) == 0);
	CHECK(engine.read_metadata_tags[first_slot].epoch == 0);
	CHECK(engine.read_metadata_tags[last_slot].start_block == 384U);
	engine.read_metadata_tags[first_slot].epoch = epoch;

	/* Seven 2072-byte payloads fill backward from the end; record six is
	 * wholly in block zero. These cold reads therefore populate only the
	 * block-zero data directory for each extent. */
	for (extent = 0; extent < 4; ++extent) {
		swapz_u32 start = extent * 128U;

		CHECK(disk.read_block_hits[start] == 1);
		CHECK(disk.read_block_hits[start + 1U] == 0);
		CHECK(disk.read_block_hits[start + 2U] == 0);
		CHECK(disk.read_block_hits[start + 3U] == 0);
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
	/* The sibling sweep fills blocks 3, 2 and 1. Block zero was already
	 * validated above, so every physical block is fetched exactly once. */
	CHECK(disk.read_blocks == reads_before + 12U);
	for (extent = 0; extent < 4; ++extent) {
		swapz_u32 start = extent * 128U;

		CHECK(disk.read_block_hits[start] == 1);
		CHECK(disk.read_block_hits[start + 1U] == 1);
		CHECK(disk.read_block_hits[start + 2U] == 1);
		CHECK(disk.read_block_hits[start + 3U] == 1);
	}
	reads_before = disk.read_blocks;
	for (extent = 0; extent < 4; ++extent)
		CHECK(swapz_engine_read_page(&engine, extent * 7U + 6U, output,
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
		CHECK(swapz_engine_read_page(&engine, extent * 7U + 6U, output,
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
	reads_before = disk.read_blocks;
	hits_before = engine.read_metadata_lru_hits;
	primary_before = engine.read_metadata_primary_hits;
	secondary_before = engine.read_metadata_secondary_hits;
	probes_before = engine.read_metadata_set_probes;
	for (extent = 0; extent < 9; ++extent) {
		swapz_u32 logical = extent * 7U + 6U;

		CHECK(swapz_engine_read_page(&engine, logical, output,
					   sizeof(output), &length) == 0);
		CHECK(length == 2072 && !memcmp(output, originals[logical], length));
	}
	CHECK(disk.read_blocks == reads_before);
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
	CHECK(swapz_engine_read_page(&engine, 34, output,
				   sizeof(output), &length) == 0);
	engine.read_metadata_cache = scratch_metadata_cache;
	engine.read_metadata_tags[primary_base].epoch = 0;
	CHECK(swapz_engine_read_page(&engine, 34, output,
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
	CHECK(swapz_engine_read_page(&engine, 34, output,
				   sizeof(output), &length) == 0);
	CHECK(length == 2072 && !memcmp(output, originals[34], length));
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
	CHECK(swapz_engine_read_page(&engine, 34, output,
				   sizeof(output), &length) == 0);
	engine.read_metadata_lru_clock = ~(swapz_u32)0;
	CHECK(swapz_engine_read_page(&engine, 34, output,
				   sizeof(output), &length) == 0);
	CHECK(engine.read_metadata_epoch == 2 && engine.read_metadata_lru_clock == 1);
	CHECK(length == 2072 && !memcmp(output, originals[34], length));
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
	/* Record five spans blocks zero and one. Pull it through the private
	 * slot so absorb has actually validated block-zero payload bytes. */
	CHECK(swapz_engine_read_page(&slot, 5, output,
				     sizeof(output), &length) == 0);
	slot_mask = slot.read_cached_block_mask;
	CHECK(slot_mask != 0 && (slot_mask & 1U));
	swapz_engine_absorb_read_slot(&engine, &slot);

	memset(&probe, 0, sizeof(probe));
	memset(probe_scratch, 0, sizeof(probe_scratch));
	probe.read_scratch = probe_scratch;
	swapz_engine_prime_read_slot(&engine, &probe, start, 4);
	CHECK(probe.read_cache_valid == 1);
	CHECK((probe.read_cached_block_mask & slot_mask) == slot_mask);

	/* Absorb also publishes validated block-zero payload bytes into the master's block-zero LRU. */
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
	struct swapz_map map;

	CHECK(setup() == 0);
	prepare(pages, 7, 0, 0);
	CHECK(write_window_sequential(pages, 7, &committed) == 0);
	CHECK(committed == 7);
	map = maps[6];
	CHECK(map.valid && !map.raw && map.payload_length);
	disk.storage[(size_t)map.start_block * SWAPZ_BLOCK_BYTES +
		     map.payload_offset] ^= 1;
	CHECK(swapz_engine_read_page(&engine, 6,
				   output, sizeof(output), &length) == -EBADMSG);
	CHECK(length == 0);
	return 0;
}

static int test_torn_extent_quarantined_without_authority(void)
{
	struct swapz_compressed_page pages[16];
	swapz_u8 planned_classes[SWAPZ_MAX_RECORDS];
	swapz_u8 planned_takes[SWAPZ_MAX_RECORDS];
	swapz_u8 planned_extents = 0;
	swapz_u8 committed = 0;

	CHECK(setup() == 0);
	prepare(pages, 16, 0, 0);
	CHECK(plan_default(pages, 16, planned_classes, planned_takes,
			   &planned_extents) == 0);
	CHECK(planned_extents && planned_takes[0]);
	disk.fail_write_on_call = 1;
	CHECK(write_window_sequential(pages, 16, &committed) == -EIO);
	CHECK(committed == 0);
	/* With payload-only packing the failed first extent may occupy just
	 * one block. Quarantine its exact reservation, whether the lower I/O
	 * wrote zero blocks or returned a torn multi-block completion. */
	CHECK(authority.abandoned_blocks == planned_classes[0]);
	CHECK(authority.next_block == authority.abandoned_blocks);
	CHECK(engine.submitted_blocks == planned_classes[0]);
	CHECK(disk.write_calls == 1);
	CHECK(disk.write_blocks == (planned_classes[0] > 1U ? 1U : 0U));
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
			CHECK(class_blocks == 10);
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

/* The first data block is not a compulsory metadata read. For a
 * single compressed record located in a later block, the cached directory
 * cannot contribute to its read set. The same preflight must fail safely
 * when volatile mapping ownership has not been initialized.
 */
static int test_ram_read_range_preflight_and_block_zero_skip(void)
{
	struct swapz_compressed_page pages[3];
	const swapz_u32 highest_page[1] = { 0 };
	const swapz_u32 lowest_page[1] = { 2 };
	struct swapz_map *retained_maps;
	swapz_u8 committed = 0, first_block = 0, blocks = 0;
	swapz_u32 start_block;

	CHECK(setup() == 0);
	prepare(pages, 3, 0, 0);
	CHECK(write_window_sequential(pages, 3, &committed) == 0);
	CHECK(committed == 3);
	CHECK(maps[0].valid && maps[2].valid &&
	      maps[0].start_block == maps[2].start_block &&
	      maps[0].extent_blocks == 2);
	CHECK(maps[0].payload_offset >= SWAPZ_BLOCK_BYTES);
	CHECK(maps[2].payload_offset < SWAPZ_BLOCK_BYTES);
	start_block = maps[0].start_block;

	/* Enable an empty block-zero directory. Its presence must not make
	 * records in the upper 4KiB block depend on lower block zero. */
	engine.read_metadata_cache = scratch_metadata_cache;
	engine.read_metadata_epoch = 1;
	engine.read_metadata_lru_clock = 1;
	engine.read_metadata_segment_mask =
		1ULL << ((start_block / SWAPZ_SEGMENT_BLOCKS) & 63U);
	CHECK(swapz_engine_required_read_range_cached(
		      &engine, highest_page, 1, start_block, 2,
		      &first_block, &blocks) == 0);
	CHECK(first_block == 1 && blocks == 1);
	CHECK(swapz_engine_required_read_range_cached(
		      &engine, lowest_page, 1, start_block, 2,
		      &first_block, &blocks) == 0);
	CHECK(first_block == 0 && blocks == 1);

	retained_maps = authority.maps;
	authority.maps = NULL;
	CHECK(swapz_engine_required_read_range(
		      &engine, highest_page, 1, start_block, 2,
		      &first_block, &blocks) == -EINVAL);
	CHECK(swapz_engine_required_read_range_cached(
		      &engine, highest_page, 1, start_block, 2,
		      &first_block, &blocks) == -EINVAL);
	authority.maps = retained_maps;
	return 0;
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
	/* A corrupted RAM descriptor can still fit inside its physical
	 * extent. It must not authorize either direct or cached lower reads
	 * when the compressed length exceeds the production codec limit. */
	{
		const swapz_u16 saved_length = maps[0].payload_length;
		const swapz_u32 saved_offset = maps[0].payload_offset;

		/* The malformed descriptor still fits within a 4KiB extent.
		 * A bounds-only preflight must not suffice for admission. */
		maps[0].payload_offset = 0;
		maps[0].payload_length = SWAPZ_BLOCK_BYTES;
		CHECK(swapz_engine_required_read_range(
			      &first, logical0, 1,
			      maps[0].start_block, maps[0].extent_blocks,
			      &first0, &blocks0) == -ESTALE);
		CHECK(swapz_engine_required_read_range_cached(
			      &first, logical0, 1,
			      maps[0].start_block, maps[0].extent_blocks,
			      &first0, &blocks0) == -ESTALE);
		maps[0].payload_offset = saved_offset;
		maps[0].payload_length = saved_length;
	}
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

	/* An invalid full extent cannot reach lower I/O through the
	 * coalescer, even if its requested subrange looks harmless. */
	disk.read_calls = 0;
	CHECK(swapz_engine_coalesce_read_pair(
			&first, &second,
			maps[0].start_block, 1, 0, 1,
			PHYSICAL_BLOCKS, 1, 0, 1,
			scratch_coalesced, 2U * SWAPZ_MAX_BLOCKS) == -EINVAL);
	CHECK(swapz_engine_coalesce_read_pair(
			&first, &second,
			PHYSICAL_BLOCKS - 1U, 2, 0, 1,
			maps[1].start_block, 1, 0, 1,
			scratch_coalesced, 2U * SWAPZ_MAX_BLOCKS) == -EINVAL);
	CHECK(swapz_engine_coalesce_read_pair(
			&first, &second,
			maps[0].start_block, 3, 0, 1,
			maps[1].start_block, 1, 0, 1,
			scratch_coalesced, 2U * SWAPZ_MAX_BLOCKS) == -EINVAL);
	CHECK(swapz_engine_coalesce_read_pair(
			&first, &second,
			SWAPZ_SEGMENT_BLOCKS - 1U, 2, 0, 1,
			SWAPZ_SEGMENT_BLOCKS + 1U, 1, 0, 1,
			scratch_coalesced, 2U * SWAPZ_MAX_BLOCKS) == -EINVAL);
	CHECK(disk.read_calls == 0);
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
	/* An absent authoritative RAM length is structurally invalid and must
	 * not submit a lower READ or accept cached bytes. */
	maps[6].payload_length = 0;
	disk.read_blocks = 0;
	CHECK(swapz_engine_read_page(&engine, 6, output,
				   sizeof(output), &length) == -ESTALE);
	CHECK(length == 0 && disk.read_blocks == 0);
	/* A nonzero but truncated RAM length is in range, so only the
	 * independent payload CRC can reject it after reading media. */
	maps[6].payload_length = original - 1;
	length = 91;
	CHECK(swapz_engine_read_page(&engine, 6, output,
				   sizeof(output), &length) == -EBADMSG);
	CHECK(length == 0 && disk.read_blocks == 1);
	/* Restore the accurate authoritative length. The physical payload
	 * was never modified; reading it must still succeed byte-for-byte. */
	maps[6].payload_length = original;
	CHECK(swapz_engine_read_page(&engine, 6, output,
				   sizeof(output), &length) == 0);
	CHECK(length == original && !memcmp(output, originals[6], length));
	return 0;
}


static int test_staged_padding_counter_saturates(void)
{
	const swapz_u32 maximum = ~(swapz_u32)0;
	const struct {
		swapz_u32 initial_blocks;
		swapz_u16 additional_blocks;
		swapz_u32 expected_blocks;
	} cases[] = {
		{ 0, 0, 0 },
		{ 0, 1, 1 },
		{ 1, 0, 1 },
		{ 1, 1, 2 },
		{ maximum - 1U, 1, maximum },
		{ maximum - 1U, 2, maximum }, /* would overflow */
		{ maximum, 0, maximum },
		{ maximum, 1, maximum },
		{ maximum, SWAPZ_BULK_BLOCKS, maximum },
	};
	struct swapz_engine telemetry = { 0 };
	size_t index;

	for (index = 0; index < sizeof(cases) / sizeof(cases[0]); ++index) {
		telemetry.bulk_padding_blocks = cases[index].initial_blocks;
		swapz_engine_account_staged_padding(
			&telemetry, cases[index].additional_blocks);
		CHECK(telemetry.bulk_padding_blocks ==
		      cases[index].expected_blocks);
		/* A status consumer may claim exactness only at zero. */
		if (cases[index].initial_blocks || cases[index].additional_blocks)
			CHECK(telemetry.bulk_padding_blocks != 0);
	}

	telemetry.bulk_padding_blocks = maximum - 1U;
	for (index = 0; index < 1024; ++index)
		swapz_engine_account_staged_padding(&telemetry, SWAPZ_BULK_BLOCKS);
	CHECK(telemetry.bulk_padding_blocks == maximum);
	return 0;
}

static int test_staged_padding_survives_mixed_run_failures(void)
{
	struct swapz_compressed_page pages[3];
	struct swapz_io_run run = {
		.bytes = padding_run_bytes,
		.txs = padding_run_transactions,
	};
	const swapz_u32 maximum = ~(swapz_u32)0;
	swapz_u8 prepared, committed, iteration;
	swapz_u8 group;
	swapz_u16 extent_blocks;

	CHECK(setup() == 0);
	authority.reuse_dead_segments = 1;
	CHECK(swapz_enable_segment_rotation(
	      &authority, padding_segment_roles,
	      PHYSICAL_BLOCKS / SWAPZ_SEGMENT_BLOCKS) == 0);
	engine.bulk_enabled = 2;

	for (iteration = 0; iteration < 5; ++iteration) {
		prepare(pages, 2, 0, 7 * iteration);
		/* Two small compressed records share one block before the RAW tail. */
		pages[0].length = 1000;
		pages[1].length = 1000;
		memset(padding_raw_page, 0x30 + iteration,
		       sizeof(padding_raw_page));
		pages[2] = (struct swapz_compressed_page) {
			.logical_page = 2,
			.payload = padding_raw_page,
			.length = SWAPZ_BLOCK_BYTES,
			.raw = 1,
		};
		prepared = 0;
		CHECK(swapz_engine_prepare_batched_run(
		      &engine, pages, 3, &run, &prepared, 0) == 0);
		CHECK(prepared == 3 && run.extent_count == 2);
		CHECK(run.raw[0] == 0 && run.raw[1] == 1);
		CHECK(!authority.in_flight && authority.batch_pending == 2);
		extent_blocks = 0;
		for (group = 0; group < run.extent_count; ++group) {
			CHECK(run.offsets[group] == extent_blocks);
			extent_blocks += run.txs[group].extent_blocks;
		}
		/* Packed compressed+RAW staging adds no intra-run padding. */
		CHECK(run.blocks == extent_blocks);
		committed = 99;
		if (iteration == 0 || iteration == 4) {
			/* A deterministic completed RAM lower write, then real replay. */
			memcpy(disk.storage +
			       (size_t)run.start_block * SWAPZ_BLOCK_BYTES,
			       run.bytes, (size_t)run.blocks * SWAPZ_BLOCK_BYTES);
			CHECK(swapz_engine_complete_batched_run(
			      &engine, &run, run.blocks, 0, &committed) == 0);
			CHECK(committed == 3);
			CHECK(maps[0].valid && maps[1].valid && maps[2].valid);
			CHECK(maps[0].generation == (iteration == 0 ? 1U : 2U));
		} else if (iteration == 1) {
			/*
			 * The source-derived counter helper models a positive gap.
			 * Packed placement currently does not naturally create one.
			 * Tail cancellation may not erase prior staging evidence.
			 */
			swapz_engine_account_staged_padding(&engine, 1);
			CHECK(engine.bulk_padding_blocks == 1);
			CHECK(maps[0].generation == 1);
			CHECK(swapz_engine_abort_batched_run_tail(&engine,
								&run) == 0);
			CHECK(committed == 99);
		} else {
			/* Inject near-overflow history before the terminal lower error. */
			if (iteration == 2)
				engine.bulk_padding_blocks = maximum - 1U;
			swapz_engine_account_staged_padding(&engine, 2);
			CHECK(engine.bulk_padding_blocks == maximum);
			CHECK(swapz_engine_complete_batched_run(
			      &engine, &run, 0,
			      iteration == 2 ? -EIO : -EBADMSG,
			      &committed) ==
			      (iteration == 2 ? -EIO : -EBADMSG));
			CHECK(committed == 0);
			CHECK(maps[0].generation == 1);
		}
		CHECK(!authority.in_flight && !authority.batch_pending);
		CHECK(engine.bulk_padding_blocks ==
		      (iteration == 0 ? 0U : iteration == 1 ? 1U : maximum));
	}
	/* Once nonzero, even future successful mixed runs cannot suggest exactness. */
	CHECK(engine.bulk_padding_blocks == maximum);
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
	CHECK(test_one_block_budget_does_not_reuse_payload_cache() == 0); completed++;
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
	CHECK(test_ram_read_range_preflight_and_block_zero_skip() == 0); completed++;
	CHECK(test_adjacent_distinct_extent_coalescing() == 0); completed++;
	CHECK(test_mapping_length_mismatch_stops_before_payload_io() == 0); completed++;
	CHECK(test_private_read_telemetry_merge_preserves_cache_state() == 0); completed++;
	CHECK(test_staged_padding_counter_saturates() == 0); completed++;
	CHECK(test_staged_padding_survives_mixed_run_failures() == 0); completed++;
	free(disk.storage);
	printf("SWAPZ_EXACT_ENGINE_TESTS_PASS=%d\n", completed);
	return 0;
}
