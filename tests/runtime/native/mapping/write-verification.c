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
static struct sv3_map map[64];
static sv3_u16 live[NPHYS];
static sv3_u8 klass[NPHYS];
static struct sv3_authority auth;
static struct sv3_engine engine;
static sv3_u8 scratch_w[16384], scratch_r[16384];
static sv3_u8 disk[NPHYS * SV3_BLOCK_BYTES];
static sv3_u8 payloads[3][2072];
static struct sv3_compressed_page pages[3];
static sv3_u32 writes, reads;
static int corrupt_after_write, fail_read, lie_about_completion;

static int write_lower(void *unused, sv3_u32 block, sv3_u8 blocks,
		       const sv3_u8 *bytes, sv3_u8 *completed)
{
	struct sv3_decoded d;
	const sv3_u8 *p;
	size_t offset = (size_t)block * SV3_BLOCK_BYTES;
	size_t size = (size_t)blocks * SV3_BLOCK_BYTES;

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
		if (sv3_lookup(bytes, (sv3_u32)size, 0, &d, &p))
			return -EUCLEAN;
		disk[offset + d.payload_offset] ^= 0x80;
	}
	return 0;
}

static int read_lower(void *unused, sv3_u32 block, sv3_u8 blocks,
		      sv3_u8 *bytes)
{
	(void)unused;
	reads += blocks;
	if (fail_read)
		return -EIO;
	if (block >= NPHYS || blocks > NPHYS - block)
		return -ERANGE;
	memcpy(bytes, disk + (size_t)block * SV3_BLOCK_BYTES,
	       (size_t)blocks * SV3_BLOCK_BYTES);
	return 0;
}

static int setup(void)
{
	unsigned int i;

	memset(&engine, 0, sizeof(engine));
	memset(disk, 0, sizeof(disk));
	writes = reads = 0;
	corrupt_after_write = fail_read = lie_about_completion = 0;
	if (sv3_authority_init(&auth, map, live, klass, 64, NPHYS))
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
	sv3_u8 committed = 99;
	sv3_u8 result[2072];
	sv3_u16 size = 0;
	unsigned int i;

	CHECK(setup() == 0);
	engine.verify_after_write = 1;
	CHECK(sv3_engine_write_window(&engine, pages, 3, &committed) == 0);
	CHECK(committed == 3 && writes == 1 && reads == 2);
	CHECK(auth.committed_blocks == 2 && auth.abandoned_blocks == 0);
	CHECK(engine.completed_blocks == 2 && engine.write_verify_read_blocks == 2);
	for (i = 0; i < 3; ++i) {
		CHECK(map[i].valid && map[i].generation == 1);
		CHECK(sv3_engine_read_page(&engine, i, result,
					   sizeof(result), &size) == 0);
		CHECK(size == 2072 && !memcmp(payloads[i], result, size));
	}
	return 0;
}

static int test_silent_media_corruption_rejected_before_publication(void)
{
	sv3_u8 committed = 99;

	CHECK(setup() == 0);
	engine.verify_after_write = 1;
	corrupt_after_write = 1;
	CHECK(sv3_engine_write_window(&engine, pages, 3, &committed) == -EBADMSG);
	CHECK(committed == 0 && writes == 1 && reads == 2);
	CHECK(engine.completed_blocks == 2 && engine.write_verify_read_blocks == 2);
	CHECK(!map[0].valid && !map[1].valid && !map[2].valid);
	CHECK(auth.abandoned_blocks == 2 && !auth.in_flight);
	return 0;
}

static int test_readback_io_failure_preserves_unmapped(void)
{
	sv3_u8 committed = 99;

	CHECK(setup() == 0);
	engine.verify_after_write = 1;
	fail_read = 1;
	CHECK(sv3_engine_write_window(&engine, pages, 3, &committed) == -EIO);
	CHECK(committed == 0 && writes == 1 && reads == 2);
	CHECK(engine.completed_blocks == 2 && engine.write_verify_read_blocks == 0);
	CHECK(!map[0].valid && !map[1].valid && !map[2].valid);
	CHECK(auth.abandoned_blocks == 2 && !auth.in_flight);
	return 0;
}

static int test_unverified_mode_detects_corruption_later(void)
{
	sv3_u8 committed = 99, result[2072];
	sv3_u16 size = 99;

	CHECK(setup() == 0);
	corrupt_after_write = 1;
	CHECK(sv3_engine_write_window(&engine, pages, 3, &committed) == 0);
	CHECK(committed == 3 && writes == 1 && reads == 0);
	CHECK(map[0].valid && engine.write_verify_read_blocks == 0);
	CHECK(sv3_engine_read_page(&engine, 0, result,
				   sizeof(result), &size) == -EBADMSG);
	CHECK(size == 0);
	return 0;
}

static int test_impossible_completion_never_fakes_write_or_readback(void)
{
	sv3_u8 committed = 99;

	CHECK(setup() == 0);
	engine.verify_after_write = 1;
	lie_about_completion = 1;
	CHECK(sv3_engine_write_window(&engine, pages, 3, &committed) == -EUCLEAN);
	CHECK(committed == 0 && writes == 1 && reads == 0);
	CHECK(engine.submitted_blocks == 2 && engine.completed_blocks == 0);
	CHECK(engine.write_verify_read_blocks == 0);
	CHECK(auth.abandoned_blocks == 2 && !map[0].valid && !auth.in_flight);
	return 0;
}

static int test_preflight_requires_distinct_readback_buffers(void)
{
	sv3_u8 committed = 99;

	CHECK(setup() == 0);
	engine.verify_after_write = 1;
	engine.read_scratch = engine.write_scratch;
	CHECK(sv3_engine_write_window(&engine, pages, 3, &committed) == -EINVAL);
	CHECK(committed == 0 && writes == 0 && !auth.in_flight);
	engine.read_scratch = scratch_r;
	engine.io.read_blocks = NULL;
	CHECK(sv3_engine_write_window(&engine, pages, 3, &committed) == -EINVAL);
	CHECK(committed == 0 && writes == 0 && !auth.in_flight);
	return 0;
}

static int test_failed_overwrite_keeps_prior_generation(void)
{
	sv3_u8 committed = 0, result[2072];
	sv3_u16 size = 0;
	struct sv3_map old;

	CHECK(setup() == 0);
	engine.verify_after_write = 1;
	CHECK(sv3_engine_write_window(&engine, pages, 3, &committed) == 0);
	old = map[0];
	corrupt_after_write = 1;
	CHECK(sv3_engine_write_window(&engine, pages, 3, &committed) == -EBADMSG);
	CHECK(map[0].start_block == old.start_block &&
	      map[0].generation == old.generation);
	CHECK(auth.committed_blocks == 2 && auth.abandoned_blocks == 2);
	CHECK(sv3_engine_read_page(&engine, 0, result, sizeof(result), &size) == 0);
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
	sv3_u8 committed = 0;
	sv3_u8 result[2072];
	sv3_u16 size = 0;
	sv3_u32 old_start;
	unsigned int index;

	CHECK(setup() == 0);
	CHECK(sv3_engine_write_window(&engine, pages, 3, &committed) == 0);
	CHECK(committed == 3);
	old_start = map[0].start_block;
	CHECK(map[1].start_block == old_start &&
	      map[2].start_block == old_start);
	for (index = 0; index < 3; ++index) {
		CHECK(sv3_engine_read_page(&engine, index, result,
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
	sv3_engine_invalidate_read_cache(&engine);
	CHECK(sv3_engine_read_page(&engine, 1, result,
					   sizeof(result), &size) == 0);
	CHECK(engine.read_metadata_requests == 2);
	CHECK(engine.read_metadata_cache_hits == 2);
	CHECK(engine.read_full_extent_requests == 2);

	/* A cold full-extent lower failure cannot leave stale metadata or
	 * payload available to the next read. */
	sv3_engine_invalidate_read_cache(&engine);
	fail_read = 1;
	CHECK(sv3_engine_read_page(&engine, 0, result,
					   sizeof(result), &size) == -EIO);
	CHECK(!engine.read_cache_valid && size == 0);
	fail_read = 0;
	CHECK(sv3_engine_read_page(&engine, 0, result,
					   sizeof(result), &size) == 0);
	CHECK(engine.read_metadata_requests == 3);
	CHECK(engine.read_full_extent_requests == 3);
	CHECK(size == sizeof(result) &&
	      !memcmp(result, payloads[0], size));

	/* A new authoritative generation cannot reuse old metadata. */
	memset(payloads[0], 0x5a, sizeof(payloads[0]));
	CHECK(sv3_engine_write_window(&engine, pages, 3, &committed) == 0);
	CHECK(committed == 3 && !engine.read_cache_valid);
	CHECK(map[0].start_block != old_start && map[0].generation == 2);
	CHECK(sv3_engine_read_page(&engine, 0, result,
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
	sv3_u8 committed = 0, result[2072];
	sv3_u16 size = 0;

	CHECK(setup() == 0);
	CHECK(sv3_engine_write_window(&engine, pages, 3, &committed) == 0);
	CHECK(committed == 3 && map[0].extent_blocks == 2);
	/* The fixture's first record spans a second physical block. */
	engine.max_read_blocks_per_record = 1;
	CHECK(sv3_engine_read_page(&engine, 0, result,
					   sizeof(result), &size) == 0);
	CHECK(size == sizeof(result) && !memcmp(result, payloads[0], size));
	CHECK(engine.read_metadata_requests == 1);
	CHECK(engine.read_full_extent_requests == 0);
	CHECK(engine.read_payload_requests == 1);
	CHECK(engine.physical_read_blocks == 2);
	CHECK(!engine.read_cached_full && engine.read_cache_valid);
	fail_read = 1;
	CHECK(sv3_engine_read_page(&engine, 0, result,
					   sizeof(result), &size) == -EIO);
	CHECK(!engine.read_cache_valid && size == 0);
	fail_read = 0;
	CHECK(sv3_engine_read_page(&engine, 0, result,
					   sizeof(result), &size) == 0);
	CHECK(engine.read_metadata_requests == 2);
	CHECK(engine.read_full_extent_requests == 0);
	CHECK(size == sizeof(result) && !memcmp(result, payloads[0], size));
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
	printf("SV3_VERIFY_AFTER_WRITE_TESTS_PASS=%d\n", passed);
	return 0;
}
