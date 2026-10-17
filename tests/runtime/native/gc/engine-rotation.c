// SPDX-License-Identifier: GPL-2.0-only
/*
 * Execute exact production codec + mapping authority + extent engine C.
 * Storage is a 4MiB RAM array, not a real block device: this validates
 * actual on-media compressed extents, CRCs and mapping generations across
 * rotating GC handoffs before any privileged null_blk test.
 */
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include "engine.h"

#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "%s:%d failed %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)
#define PBLKS (4U * SWAPZ_SEGMENT_BLOCKS)
static swapz_u8 lower[PBLKS * SWAPZ_BLOCK_BYTES];
static struct swapz_authority a;
static struct swapz_map maps[32];
static swapz_u16 live[PBLKS];
static swapz_u8 classes[PBLKS], roles[4];
static struct swapz_engine e;
static swapz_u8 write_scratch[SWAPZ_MAX_EXTENT_BYTES];
static swapz_u8 read_scratch[SWAPZ_MAX_EXTENT_BYTES];
static swapz_u8 contents[8][2072];
static unsigned int lower_reads, lower_writes;
static int fail_write;

static int lower_write(void *opaque, swapz_u32 start, swapz_u8 blocks,
		       const swapz_u8 *bytes, swapz_u8 *completed)
{
	(void)opaque;
	*completed = 0;
	if (start >= PBLKS || blocks > PBLKS - start)
		return -ERANGE;
	if (fail_write) {
		fail_write = 0;
		return -EIO;
	}
	memcpy(lower + (size_t)start * SWAPZ_BLOCK_BYTES, bytes,
	       (size_t)blocks * SWAPZ_BLOCK_BYTES);
	lower_writes += blocks;
	*completed = blocks;
	return 0;
}

static int lower_read(void *opaque, swapz_u32 start, swapz_u8 blocks, swapz_u8 *out)
{
	(void)opaque;
	if (start >= PBLKS || blocks > PBLKS - start)
		return -ERANGE;
	memcpy(out, lower + (size_t)start * SWAPZ_BLOCK_BYTES,
	       (size_t)blocks * SWAPZ_BLOCK_BYTES);
	lower_reads += blocks;
	return 0;
}

static int setup(void)
{
	int error = swapz_authority_init(&a, maps, live, classes, 32, PBLKS);
	unsigned int i;

	if (error)
		return error;
	a.reuse_dead_segments = 1;
	error = swapz_enable_segment_rotation(&a, roles, 4);
	if (error)
		return error;
	memset(&e, 0, sizeof(e));
	e.authority = &a;
	e.write_scratch = write_scratch;
	e.read_scratch = read_scratch;
	e.io.write_extent = lower_write;
	e.io.read_blocks = lower_read;
	lower_reads = lower_writes = 0;
	for (i = 0; i < 8; ++i)
		memset(contents[i], (int)i + 1, sizeof(contents[i]));
	return 0;
}

static int write_one(swapz_u32 logical)
{
	struct swapz_compressed_page p = {
		.logical_page = logical,
		.payload = contents[logical],
		.length = 2072,
	};
	swapz_u8 complete = 0;
	int error = swapz_engine_write_window_batched(&e, &p, 1, &complete);

	if (!error && complete != 1)
		return -EUCLEAN;
	return error;
}

static int verify_page(swapz_u32 logical)
{
	swapz_u8 out[2072];
	swapz_u16 len = 0;
	int error = swapz_engine_read_page(&e, logical, out, sizeof(out), &len);

	if (error)
		return error;
	return len == sizeof(out) &&
	       !memcmp(out, contents[logical], sizeof(out)) ? 0 : -EUCLEAN;
}

static int evacuate(swapz_u32 victim)
{
	struct swapz_compressed_page pages[8];
	swapz_u8 completed = 0, count = 0;
	swapz_u32 logical;
	int error = swapz_gc_begin_rotation(&a, victim);

	if (error)
		return error;
	for (logical = 0; logical < 8; ++logical) {
		swapz_u8 got[2072];
		swapz_u16 len;

		if (!maps[logical].valid ||
		    maps[logical].start_block / SWAPZ_SEGMENT_BLOCKS != victim)
			continue;
		error = swapz_engine_read_page(&e, logical, got,
					    sizeof(got), &len);
		if (error)
			return error;
		if (len != 2072 ||
		    memcmp(got, contents[logical], len))
			return -EUCLEAN;
		pages[count++] = (struct swapz_compressed_page) {
			.logical_page = logical,
			.payload = contents[logical], .length = len,
		};
	}
	if (!count)
		return -EUCLEAN;
	error = swapz_engine_write_window_batched(&e, pages, count, &completed);
	if (error)
		return error;
	if (completed != count)
		return -EIO;
	return swapz_gc_commit_rotation(&a, victim);
}

static int test_compressed_gc_handoff(void)
{
	swapz_u32 i;

	CHECK(setup() == 0);
	for (i = 0; i < 256; ++i)
		CHECK(write_one(0) == 0);
	for (i = 0; i < 256; ++i)
		CHECK(write_one(1) == 0);
	CHECK(a.next_block == 512 && write_one(2) == -ENOSPC);
	CHECK(verify_page(0) == 0 && verify_page(1) == 0);
	CHECK(evacuate(0) == 0);
	CHECK(roles[0] == 0 && roles[2] == 1 && maps[0].start_block == 512);
	CHECK(write_one(2) == 0);
	CHECK(verify_page(0) == 0 && verify_page(2) == 0);
	CHECK(evacuate(1) == 0);
	CHECK(roles[1] == 0 && roles[0] == 1 && maps[1].start_block == 0);
	CHECK(write_one(3) == 0);
	CHECK(evacuate(2) == 0); /* two survivor pages0 and2 */
	CHECK(roles[2] == 0 && roles[1] == 1);
	for (i = 0; i < 4; ++i)
		CHECK(verify_page(i) == 0);
	CHECK(write_one(4) == 0 && verify_page(4) == 0);
	CHECK(lower_reads && lower_writes);
	return 0;
}

static int test_failed_gc_write_preserves_live_mapping(void)
{
	struct swapz_compressed_page p;
	swapz_u8 completed = 99;
	swapz_u32 previous;

	CHECK(setup() == 0);
	CHECK(write_one(0) == 0);
	/* Move foreground OPEN away from victim0 first. */
	for (unsigned int i = 1; i < 256; ++i)
		CHECK(write_one(0) == 0);
	previous = maps[0].start_block;
	CHECK(write_one(1) == 0);
	CHECK(swapz_gc_begin_rotation(&a, 0) == 0);
	p = (struct swapz_compressed_page) {
		.logical_page = 0, .payload = contents[0], .length = 2072,
	};
	fail_write = 1;
	CHECK(swapz_engine_write_window_batched(&e, &p, 1, &completed) == -EIO);
	CHECK(completed == 0 && maps[0].start_block == previous);
	CHECK(maps[0].valid && verify_page(0) == 0);
	CHECK(swapz_gc_commit_rotation(&a, 0) == -EUCLEAN);
	CHECK(roles[0] == 1 && roles[2] == 0);
	return 0;
}

int main(void)
{
	int passed = 0;

	CHECK(test_compressed_gc_handoff() == 0); passed++;
	CHECK(test_failed_gc_write_preserves_live_mapping() == 0); passed++;
	printf("SWAPZ_GC_ENGINE_ROTATION_TESTS_PASS=%d\n", passed);
	return 0;
}
