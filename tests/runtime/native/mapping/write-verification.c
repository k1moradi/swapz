// SPDX-License-Identifier: GPL-2.0-only
/*
 * Exact kernel-C tests for optional V3 read-after-write verification.
 * All lower calls are in-memory, bounded and fault-injectable: NO real I/O.
 */
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "engine.h"

#define CHECK(expr) do { \
	if (!(expr)) { \
		fprintf(stderr, "%s:%d: FAILED: %s\n", __FILE__, __LINE__, #expr); \
		return 1; \
	} \
} while (0)
#define NPHYS 2048U
static struct swapz_map map[64];
static swapz_u16 live[NPHYS];
static swapz_u8 klass[NPHYS];
static struct swapz_authority auth;
static struct swapz_engine engine;
static swapz_u8 scratch_w[16384], scratch_r[16384];
static swapz_u8 disk[NPHYS * SWAPZ_BLOCK_BYTES];
static swapz_u8 payloads[3][2072];
static struct swapz_compressed_page pages[3];
static swapz_u32 writes, reads;
static int corrupt_after_write, fail_read, lie_about_completion;

static int write_lower(void *unused, swapz_u32 block, swapz_u8 blocks,
		       const swapz_u8 *bytes, swapz_u8 *completed)
{
	struct swapz_decoded d;
	const swapz_u8 *p;
	size_t offset = (size_t)block * SWAPZ_BLOCK_BYTES;
	size_t size = (size_t)blocks * SWAPZ_BLOCK_BYTES;

	(void)unused;
	*completed = 0;
	if (block >= NPHYS || blocks > NPHYS - block)
		return -ERANGE;
	writes++;
	if (lie_about_completion) {
		*completed = blocks + 1U;
		return 0;
	}
	memcpy(disk + offset, bytes, size);
	*completed = blocks;
	if (corrupt_after_write) {
		if (swapz_lookup(bytes, (swapz_u32)size, 0, &d, &p))
			return -EUCLEAN;
		disk[offset + d.payload_offset] ^= 0x80;
	}
	return 0;
}

static int read_lower(void *unused, swapz_u32 block, swapz_u8 blocks,
		      swapz_u8 *bytes)
{
	(void)unused;
	reads += blocks;
	if (fail_read)
		return -EIO;
	if (block >= NPHYS || blocks > NPHYS - block)
		return -ERANGE;
	memcpy(bytes, disk + (size_t)block * SWAPZ_BLOCK_BYTES,
	       (size_t)blocks * SWAPZ_BLOCK_BYTES);
	return 0;
}

static int setup(void)
{
	unsigned int i;

	memset(&engine, 0, sizeof(engine));
	memset(disk, 0, sizeof(disk));
	writes = reads = 0;
	corrupt_after_write = fail_read = lie_about_completion = 0;
	if (swapz_authority_init(&auth, map, live, klass, 64, NPHYS))
		return 1;
	engine.authority = &auth;
	engine.write_scratch = scratch_w;
	engine.read_scratch = scratch_r;
	engine.io.write_extent = write_lower;
	engine.io.read_blocks = read_lower;
	for (i = 0; i < 3; ++i) {
		memset(payloads[i], i + 1, sizeof(payloads[i]));
		pages[i].logical_page = i;
		pages[i].payload = payloads[i];
		pages[i].length = sizeof(payloads[i]);
	}
	return 0;
}

static int test_good_full_readback_publishes(void)
{
	swapz_u8 committed = 99;
	swapz_u8 result[2072];
	swapz_u16 size = 0;
	unsigned int i;

	CHECK(setup() == 0);
	engine.verify_after_write = 1;
	CHECK(swapz_engine_write_window_batched(&engine, pages, 3, &committed) == 0);
	CHECK(committed == 3 && writes == 1 && reads == 2);
	CHECK(auth.committed_blocks == 2 && auth.abandoned_blocks == 0);
	CHECK(engine.completed_blocks == 2 && engine.write_verify_read_blocks == 2);
	for (i = 0; i < 3; ++i) {
		CHECK(map[i].valid && map[i].generation == 1);
		CHECK(swapz_engine_read_page(&engine, i, result,
					   sizeof(result), &size) == 0);
		CHECK(size == 2072 && !memcmp(payloads[i], result, size));
	}
	return 0;
}

static int test_silent_media_corruption_rejected_before_publication(void)
{
	swapz_u8 committed = 99;

	CHECK(setup() == 0);
	engine.verify_after_write = 1;
	corrupt_after_write = 1;
	CHECK(swapz_engine_write_window_batched(&engine, pages, 3, &committed) == -EBADMSG);
	CHECK(committed == 0 && writes == 1 && reads == 2);
	CHECK(engine.completed_blocks == 2 && engine.write_verify_read_blocks == 2);
	CHECK(!map[0].valid && !map[1].valid && !map[2].valid);
	CHECK(auth.abandoned_blocks == 2 && !auth.in_flight);
	return 0;
}

static int test_readback_io_failure_preserves_unmapped(void)
{
	swapz_u8 committed = 99;

	CHECK(setup() == 0);
	engine.verify_after_write = 1;
	fail_read = 1;
	CHECK(swapz_engine_write_window_batched(&engine, pages, 3, &committed) == -EIO);
	CHECK(committed == 0 && writes == 1 && reads == 2);
	CHECK(engine.completed_blocks == 2 && engine.write_verify_read_blocks == 0);
	CHECK(!map[0].valid && !map[1].valid && !map[2].valid);
	CHECK(auth.abandoned_blocks == 2 && !auth.in_flight);
	return 0;
}

static int test_unverified_mode_detects_corruption_later(void)
{
	swapz_u8 committed = 99, result[2072];
	swapz_u16 size = 99;

	CHECK(setup() == 0);
	corrupt_after_write = 1;
	CHECK(swapz_engine_write_window_batched(&engine, pages, 3, &committed) == 0);
	CHECK(committed == 3 && writes == 1 && reads == 0);
	CHECK(map[0].valid && engine.write_verify_read_blocks == 0);
	CHECK(swapz_engine_read_page(&engine, 0, result,
				   sizeof(result), &size) == -EBADMSG);
	CHECK(size == 0);
	return 0;
}

static int test_impossible_completion_never_fakes_write_or_readback(void)
{
	swapz_u8 committed = 99;

	CHECK(setup() == 0);
	engine.verify_after_write = 1;
	lie_about_completion = 1;
	CHECK(swapz_engine_write_window_batched(&engine, pages, 3, &committed) == -EUCLEAN);
	CHECK(committed == 0 && writes == 1 && reads == 0);
	CHECK(engine.submitted_blocks == 2 && engine.completed_blocks == 0);
	CHECK(engine.write_verify_read_blocks == 0);
	CHECK(auth.abandoned_blocks == 2 && !map[0].valid && !auth.in_flight);
	return 0;
}

static int test_preflight_requires_distinct_readback_buffers(void)
{
	swapz_u8 committed = 99;

	CHECK(setup() == 0);
	engine.verify_after_write = 1;
	engine.read_scratch = engine.write_scratch;
	CHECK(swapz_engine_write_window_batched(&engine, pages, 3, &committed) == -EINVAL);
	CHECK(committed == 0 && writes == 0 && !auth.in_flight);
	engine.read_scratch = scratch_r;
	engine.io.read_blocks = NULL;
	CHECK(swapz_engine_write_window_batched(&engine, pages, 3, &committed) == -EINVAL);
	CHECK(committed == 0 && writes == 0 && !auth.in_flight);
	return 0;
}

static int test_failed_overwrite_keeps_prior_generation(void)
{
	swapz_u8 committed = 0, result[2072];
	swapz_u16 size = 0;
	struct swapz_map old;

	CHECK(setup() == 0);
	engine.verify_after_write = 1;
	CHECK(swapz_engine_write_window_batched(&engine, pages, 3, &committed) == 0);
	old = map[0];
	corrupt_after_write = 1;
	CHECK(swapz_engine_write_window_batched(&engine, pages, 3, &committed) == -EBADMSG);
	CHECK(map[0].start_block == old.start_block &&
	      map[0].generation == old.generation);
	CHECK(auth.committed_blocks == 2 && auth.abandoned_blocks == 2);
	CHECK(swapz_engine_read_page(&engine, 0, result, sizeof(result), &size) == 0);
	CHECK(size == 2072 && !memcmp(result, payloads[0], size));
	return 0;
}

/*
 * The bounded full-extent fast path uses existing scratch space and still
 * checks every record's authoritative generation, metadata and payload CRC.
 * Direct writes, discards and failed reads invalidate both cached blocks.
 */
static int test_same_extent_read_cache_reuse_and_fail_closed(void)
{
	swapz_u8 committed = 0;
	swapz_u8 result[2072];
	swapz_u16 size = 0;
	swapz_u32 old_start;
	unsigned int index;

	CHECK(setup() == 0);
	CHECK(swapz_engine_write_window_batched(&engine, pages, 3, &committed) == 0);
	CHECK(committed == 3);
	old_start = map[0].start_block;
	CHECK(map[1].start_block == old_start &&
	      map[2].start_block == old_start);
	for (index = 0; index < 3; ++index) {
		CHECK(swapz_engine_read_page(&engine, index, result,
					   sizeof(result), &size) == 0);
		CHECK(size == sizeof(result) &&
		      !memcmp(result, payloads[index], size));
	}
	CHECK(engine.read_metadata_requests == 1);
	CHECK(engine.read_metadata_cache_hits == 2);
	CHECK(engine.read_full_extent_requests == 1);
	CHECK(engine.read_full_extent_cache_hits == 2);
	CHECK(engine.physical_read_blocks == 2);
	CHECK(engine.read_payload_requests == 0);
	CHECK(engine.read_cache_valid && engine.read_cached_full);

	/* A caller-owned DISCARD/barrier invalidates even without a WRITE. */
	swapz_engine_invalidate_read_cache(&engine);
	CHECK(swapz_engine_read_page(&engine, 1, result,
					   sizeof(result), &size) == 0);
	CHECK(engine.read_metadata_requests == 2);
	CHECK(engine.read_metadata_cache_hits == 2);
	CHECK(engine.read_full_extent_requests == 2);

	/* A cold full-extent lower failure cannot leave stale metadata or
	 * payload available to the next read. */
	swapz_engine_invalidate_read_cache(&engine);
	fail_read = 1;
	CHECK(swapz_engine_read_page(&engine, 0, result,
					   sizeof(result), &size) == -EIO);
	CHECK(!engine.read_cache_valid && size == 0);
	fail_read = 0;
	CHECK(swapz_engine_read_page(&engine, 0, result,
					   sizeof(result), &size) == 0);
	CHECK(engine.read_metadata_requests == 3);
	CHECK(engine.read_full_extent_requests == 3);
	CHECK(size == sizeof(result) &&
	      !memcmp(result, payloads[0], size));

	/* A new authoritative generation cannot reuse old metadata. */
	memset(payloads[0], 0x5a, sizeof(payloads[0]));
	CHECK(swapz_engine_write_window_batched(&engine, pages, 3, &committed) == 0);
	CHECK(committed == 3 && !engine.read_cache_valid);
	CHECK(map[0].start_block != old_start && map[0].generation == 2);
	CHECK(swapz_engine_read_page(&engine, 0, result,
					   sizeof(result), &size) == 0);
	CHECK(engine.read_metadata_requests == 4);
	CHECK(engine.read_full_extent_requests == 4);
	CHECK(size == sizeof(result) &&
	      !memcmp(result, payloads[0], size));
	return 0;
}

/*
 * The explicit one-block read budget must not be bypassed by prefetch,
 * including on the slow payload branch. A failed selective payload read
 * invalidates the cached header and forces a fresh lower metadata read.
 */
static int test_one_block_read_budget_remains_selective(void)
{
	swapz_u8 committed = 0, result[2072];
	swapz_u16 size = 0;

	CHECK(setup() == 0);
	CHECK(swapz_engine_write_window_batched(&engine, pages, 3, &committed) == 0);
	CHECK(committed == 3 && map[0].extent_blocks == 2);
	/* The fixture's first record spans a second physical block. */
	engine.max_read_blocks_per_record = 1;
	CHECK(swapz_engine_read_page(&engine, 0, result,
					   sizeof(result), &size) == 0);
	CHECK(size == sizeof(result) && !memcmp(result, payloads[0], size));
	CHECK(engine.read_metadata_requests == 1);
	CHECK(engine.read_full_extent_requests == 0);
	CHECK(engine.read_payload_requests == 1);
	CHECK(engine.physical_read_blocks == 2);
	CHECK(!engine.read_cached_full && engine.read_cache_valid);
	fail_read = 1;
	CHECK(swapz_engine_read_page(&engine, 0, result,
					   sizeof(result), &size) == -EIO);
	CHECK(!engine.read_cache_valid && size == 0);
	fail_read = 0;
	CHECK(swapz_engine_read_page(&engine, 0, result,
					   sizeof(result), &size) == 0);
	CHECK(engine.read_metadata_requests == 2);
	CHECK(engine.read_full_extent_requests == 0);
	CHECK(size == sizeof(result) && !memcmp(result, payloads[0], size));
	return 0;
}

/*
 * A validated volatile offset can save the extra 4KiB without adding a
 * second delayed lower request. This is distinct from the strictly
 * metadata-first budget and complete-two-block read regression above.
 */
static int test_two_block_payload_offset_skips_unneeded_second_block(void)
{
	swapz_u8 committed = 0, result[2072];
	swapz_u16 size = 0;
	swapz_u16 offset;
	swapz_u32 before;

	CHECK(setup() == 0);
	CHECK(swapz_engine_write_window_batched(&engine, pages, 3, &committed) == 0);
	CHECK(committed == 3 && map[2].extent_blocks == 2);
	CHECK(map[2].payload_offset + map[2].payload_length <=
	      SWAPZ_BLOCK_BYTES);
	CHECK(map[0].payload_offset + map[0].payload_length >
	      SWAPZ_BLOCK_BYTES);
	CHECK(map[1].payload_offset < SWAPZ_BLOCK_BYTES &&
	      map[1].payload_offset + map[1].payload_length >
	      SWAPZ_BLOCK_BYTES);
	CHECK(swapz_engine_read_page(&engine, 2, result,
					   sizeof(result), &size) == 0);
	CHECK(size == sizeof(result) && !memcmp(result, payloads[2], size));
	CHECK(reads == 1 && engine.physical_read_blocks == 1);
	CHECK(engine.read_two_block_skips == 1);
	CHECK(!engine.read_cached_full && engine.read_cache_valid);
	/* Shared block-zero metadata remains validated for sibling access. */
	CHECK(swapz_engine_read_page(&engine, 1, result,
					   sizeof(result), &size) == 0);
	CHECK(size == sizeof(result) && !memcmp(result, payloads[1], size));
	CHECK(reads == 2 && engine.read_metadata_cache_hits == 1);
	CHECK(engine.read_payload_requests == 1 &&
	      engine.read_full_extent_requests == 0);

	/* A corrupt mapping hint is never allowed to bypass the on-disk
	 * descriptor equality check, including when the correct payload
	 * happens to reside wholly in metadata block zero. */
	swapz_engine_invalidate_read_cache(&engine);
	offset = map[2].payload_offset;
	map[2].payload_offset++;
	before = reads;
	CHECK(swapz_engine_read_page(&engine, 2, result,
					   sizeof(result), &size) == -EUCLEAN);
	CHECK(size == 0 && !engine.read_cache_valid && reads == before + 1);
	map[2].payload_offset = offset;

	/* Other records still get one complete two-block request. */
	swapz_engine_invalidate_read_cache(&engine);
	before = reads;
	CHECK(swapz_engine_read_page(&engine, 0, result,
					   sizeof(result), &size) == 0);
	CHECK(size == sizeof(result) && !memcmp(result, payloads[0], size));
	CHECK(reads == before + 2 &&
	      engine.read_full_extent_requests == 1);
	return 0;
}

int main(void)
{
	int passed = 0;

	CHECK(test_good_full_readback_publishes() == 0); passed++;
	CHECK(test_silent_media_corruption_rejected_before_publication() == 0); passed++;
	CHECK(test_readback_io_failure_preserves_unmapped() == 0); passed++;
	CHECK(test_unverified_mode_detects_corruption_later() == 0); passed++;
	CHECK(test_impossible_completion_never_fakes_write_or_readback() == 0); passed++;
	CHECK(test_preflight_requires_distinct_readback_buffers() == 0); passed++;
	CHECK(test_failed_overwrite_keeps_prior_generation() == 0); passed++;
	CHECK(test_same_extent_read_cache_reuse_and_fail_closed() == 0); passed++;
	CHECK(test_one_block_read_budget_remains_selective() == 0); passed++;
	CHECK(test_two_block_payload_offset_skips_unneeded_second_block() == 0); passed++;
	printf("SWAPZ_VERIFY_AFTER_WRITE_TESTS_PASS=%d\n", passed);
	return 0;
}
