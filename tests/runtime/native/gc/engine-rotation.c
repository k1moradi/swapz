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
static swapz_u8 extent_sequence_delta[PBLKS];
static swapz_u32 segment_sequence_base[4];
static struct swapz_engine e;
static swapz_u8 write_scratch[SWAPZ_MAX_EXTENT_BYTES];
static swapz_u8 read_scratch[SWAPZ_MAX_EXTENT_BYTES];
static swapz_u8 contents[8][2072];
static swapz_u8 late_payloads[5][SWAPZ_MAX_COMPRESSED];
static swapz_u8 late_readback[SWAPZ_MAX_COMPRESSED];
static swapz_u8 bulk_scratch[SWAPZ_BULK_BLOCKS * SWAPZ_BLOCK_BYTES];
static struct swapz_tx bulk_txs[SWAPZ_MAX_RECORDS];
static unsigned int lower_reads, lower_writes;
static int fail_read, fail_write, corrupt_replay_tail;
static swapz_u16 partial_run_blocks;

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
	if (fail_read) {
		fail_read = 0;
		return -EIO;
	}
	memcpy(out, lower + (size_t)start * SWAPZ_BLOCK_BYTES,
	       (size_t)blocks * SWAPZ_BLOCK_BYTES);
	lower_reads += blocks;
	return 0;
}

static int lower_write_run(void *opaque, swapz_u32 start, swapz_u16 blocks,
			   const swapz_u8 *bytes, swapz_u16 *completed)
{
	(void)opaque;
	*completed = 0;
	if (!blocks || blocks > SWAPZ_BULK_BLOCKS || start >= PBLKS ||
	    blocks > PBLKS - start ||
	    start / SWAPZ_SEGMENT_BLOCKS !=
		(start + blocks - 1U) / SWAPZ_SEGMENT_BLOCKS)
		return -ERANGE;
	if (partial_run_blocks) {
		const swapz_u16 written_blocks = partial_run_blocks;

		partial_run_blocks = 0;
		if (written_blocks >= blocks)
			return -EUCLEAN;
		/*
		 * A lower device may have written these blocks even though it reports
		 * a terminal error. No part of this run is safe to publish or reuse.
		 */
		memcpy(lower + (size_t)start * SWAPZ_BLOCK_BYTES, bytes,
		       (size_t)written_blocks * SWAPZ_BLOCK_BYTES);
		lower_writes += written_blocks;
		*completed = written_blocks;
		return -EIO;
	}
	memcpy(lower + (size_t)start * SWAPZ_BLOCK_BYTES, bytes,
	       (size_t)blocks * SWAPZ_BLOCK_BYTES);
	lower_writes += blocks;
	*completed = blocks;
	/* Corrupt only the replay image after the lower copy is complete. The
	 * last paused transaction then fails authority validation after all older
	 * extents in the same lower run have already replayed successfully. */
	if (corrupt_replay_tail) {
		swapz_u32 tail;

		if (a.batch_pending < 2U)
			return -EUCLEAN;
		tail = bulk_txs[a.batch_pending - 1U].start_block - start;
		if (tail >= blocks)
			return -EUCLEAN;
		bulk_scratch[(size_t)tail * SWAPZ_BLOCK_BYTES] ^= 1U;
		corrupt_replay_tail = 0;
	}
	return 0;
}

static int setup(void)
{
	int error = swapz_authority_init(&a, maps, live, classes, 32, PBLKS);
	unsigned int i;

	if (error)
		return error;
	error = swapz_enable_extent_sequence_index(&a, extent_sequence_delta,
						   segment_sequence_base, 4);
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
	fail_read = fail_write = corrupt_replay_tail = 0;
	partial_run_blocks = 0;
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
	int error;

	if (!a.gc_allocation)
		error = swapz_gc_begin_rotation(&a, victim);
	else if (a.gc_forbidden_victim != victim ||
		 a.gc_destination == ~(swapz_u32)0 ||
		 a.open_segment != a.gc_destination)
		return -EUCLEAN;
	else
		error = 0;
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
	CHECK(roles[1] == 0 && roles[3] == 1 && maps[1].start_block == 768);
	CHECK(write_one(3) == 0);
	CHECK(evacuate(2) == 0); /* two survivor pages0 and2 */
	CHECK(roles[2] == 0 && roles[0] == 1);
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
	swapz_u32 failed_block, previous;

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
	failed_block = a.next_block - 1U;
	CHECK(completed == 0 && maps[0].start_block == previous);
	CHECK(maps[0].valid && verify_page(0) == 0);
	CHECK(!live[failed_block] && !classes[failed_block]);
	CHECK(swapz_gc_commit_rotation(&a, 0) == -EUCLEAN);
	CHECK(roles[0] == 1 && roles[2] == 0);

	/* The uncertain physical block is quarantined by the monotonic cursor.
	 * Retrying relocation must publish into the next block, then the same
	 * reserve rotation can complete without ever reusing failed media. */
	completed = 0;
	CHECK(swapz_engine_write_window_batched(&e, &p, 1, &completed) == 0);
	CHECK(completed == 1 && maps[0].start_block == failed_block + 1U);
	CHECK(!live[failed_block] && live[maps[0].start_block]);
	CHECK(swapz_gc_commit_rotation(&a, 0) == 0);
	CHECK(roles[0] == 0 && roles[2] == 1);
	CHECK(verify_page(0) == 0);
	return 0;
}

static int test_failed_gc_read_preserves_live_mapping(void)
{
	swapz_u32 previous;

	CHECK(setup() == 0);
	for (unsigned int i = 0; i < SWAPZ_SEGMENT_BLOCKS; ++i)
		CHECK(write_one(0) == 0);
	previous = maps[0].start_block;
	CHECK(write_one(1) == 0); /* move OPEN away from victim0 */
	fail_read = 1;
	CHECK(evacuate(0) == -EIO);
	CHECK(maps[0].valid && maps[0].start_block == previous && live[previous]);
	CHECK(roles[0] == 1 && roles[2] == 0);
	CHECK(verify_page(0) == 0);
	CHECK(swapz_gc_commit_rotation(&a, 0) == -EUCLEAN);
	/* The failed READ consumed no destination blocks. The same authenticated
	 * victim/destination can be resumed after the transient fault is gone. */
	CHECK(evacuate(0) == 0);
	CHECK(roles[0] == 0 && roles[2] == 1);
	CHECK(verify_page(0) == 0);
	return 0;
}

static int test_delayed_gc_completion_fences_mutation(void)
{
	struct swapz_compressed_page p;
	struct swapz_io_run run = {
		.bytes = bulk_scratch,
		.txs = bulk_txs,
	};
	struct swapz_tx blocked;
	swapz_u8 committed = 0, prepared = 0;
	swapz_u16 completed = 0;
	swapz_u32 logical = 0, previous;

	CHECK(setup() == 0);
	for (unsigned int i = 0; i < SWAPZ_SEGMENT_BLOCKS; ++i)
		CHECK(write_one(0) == 0);
	previous = maps[0].start_block;
	CHECK(write_one(1) == 0);
	CHECK(swapz_gc_begin_rotation(&a, 0) == 0);
	e.bulk_enabled = 1;
	e.bulk_scratch = bulk_scratch;
	e.bulk_txs = bulk_txs;
	p = (struct swapz_compressed_page) {
		.logical_page = 0, .payload = contents[0], .length = 2072,
	};
	CHECK(swapz_engine_prepare_batched_run(&e, &p, 1, &run,
					       &prepared, 0) == 0);
	CHECK(prepared == 1 && a.batch_pending && !a.in_flight);
	CHECK(maps[0].start_block == previous);
	/* Model a delayed owned lower completion. Until completion is replayed,
	 * neither an overwrite reservation nor DISCARD may change authority. */
	CHECK(swapz_stage(&a, &logical, 1, 1, &blocked) == -EBUSY);
	CHECK(swapz_discard_page(&a, logical) == -EBUSY);
	CHECK(maps[0].start_block == previous && maps[0].valid);
	CHECK(lower_write_run(NULL, run.start_block, run.blocks,
			      run.bytes, &completed) == 0);
	CHECK(completed == run.blocks);
	CHECK(swapz_engine_complete_batched_run(&e, &run, completed, 0,
						 &committed) == 0);
	CHECK(committed == 1 && !a.batch_pending && !a.in_flight);
	CHECK(maps[0].start_block != previous);
	CHECK(swapz_gc_commit_rotation(&a, 0) == 0);
	CHECK(roles[0] == 0 && roles[2] == 1);
	CHECK(verify_page(0) == 0);
	return 0;
}

static int test_torn_lower_run_quarantines_unpublished_prefix(void)
{
	struct swapz_compressed_page pages[5];
	struct swapz_map original;
	swapz_u8 committed = 99;
	swapz_u32 logical, start;
	unsigned int index;

	CHECK(setup() == 0);
	CHECK(write_one(0) == 0);
	original = maps[0];
	e.bulk_enabled = 1;
	e.bulk_scratch = bulk_scratch;
	e.bulk_txs = bulk_txs;
	e.io.write_run = lower_write_run;
	for (index = 0; index < 5; ++index) {
		memset(late_payloads[index], (int)index + 0x51,
		       sizeof(late_payloads[index]));
		pages[index] = (struct swapz_compressed_page) {
			.logical_page = index,
			.payload = late_payloads[index],
			.length = SWAPZ_MAX_COMPRESSED,
		};
	}

	/* Simulate two blocks reaching media followed by a failed combined
	 * WRITE. Earlier torn blocks must not become logical authority. */
	start = a.next_block;
	partial_run_blocks = 2;
	CHECK(swapz_engine_write_window_batched(&e, pages, 5,
						 &committed) == -EIO);
	CHECK(committed == 0 && partial_run_blocks == 0);
	CHECK(lower_writes == 3); /* one initial, two failed lower blocks */
	CHECK(a.next_block == start + 5U && a.abandoned_blocks == 5U);
	CHECK(!a.in_flight && !a.batch_pending);
	CHECK(maps[0].start_block == original.start_block &&
	      maps[0].generation == original.generation);
	CHECK(verify_page(0) == 0);
	for (index = 1; index < 5; ++index)
		CHECK(!maps[index].valid && !maps[index].generation);
	for (logical = start; logical < a.next_block; ++logical)
		CHECK(!live[logical] && !classes[logical]);

	/* Retry cannot overwrite any of those uncertain physical blocks. */
	committed = 0;
	CHECK(swapz_engine_write_window_batched(&e, pages, 5,
						 &committed) == 0);
	CHECK(committed == 5 && !a.in_flight && !a.batch_pending);
	for (index = 0; index < 5; ++index) {
		swapz_u16 length = 0;

		CHECK(maps[index].valid &&
		      maps[index].start_block >= start + 5U &&
		      maps[index].generation == (index == 0 ? 2U : 1U));
		CHECK(swapz_engine_read_page(&e, index, late_readback,
						     sizeof(late_readback), &length) == 0);
		CHECK(length == sizeof(late_payloads[index]));
		CHECK(!memcmp(late_readback, late_payloads[index], length));
	}
	return 0;
}

static int test_late_replay_failure_reports_committed_prefix(void)
{
	struct swapz_compressed_page pages[5];
	swapz_u8 committed = 99;
	unsigned int i;

	CHECK(setup() == 0);
	e.bulk_enabled = 1;
	e.bulk_scratch = bulk_scratch;
	e.bulk_txs = bulk_txs;
	e.io.write_run = lower_write_run;
	for (i = 0; i < 5; ++i) {
		memset(late_payloads[i], (int)i + 0x31, sizeof(late_payloads[i]));
		pages[i] = (struct swapz_compressed_page) {
			.logical_page = i,
			.payload = late_payloads[i],
			.length = SWAPZ_MAX_COMPRESSED,
		};
	}
	/* Five maximum-size records require at least two extents in one completed
	 * lower run. Corrupt only the last replay image so all earlier extents are
	 * authoritative before the tail validation failure is observed. */
	corrupt_replay_tail = 1;
	CHECK(swapz_engine_write_window_batched(&e, pages, 5, &committed) == -EUCLEAN);
	CHECK(committed == 4);
	CHECK(lower_writes == 5 && e.completed_blocks == 5);
	CHECK(!a.in_flight && !a.batch_pending && a.abandoned_blocks == 1);
	CHECK(!maps[4].valid && maps[4].generation == 0);
	for (i = 0; i < 4; ++i) {
		swapz_u16 length = 0;

		CHECK(maps[i].valid && maps[i].generation == 1);
		CHECK(swapz_engine_read_page(&e, i, late_readback,
					     sizeof(late_readback), &length) == 0);
		CHECK(length == sizeof(late_payloads[i]));
		CHECK(!memcmp(late_readback, late_payloads[i], length));
	}
	return 0;
}

static int setup_gc_bulk_victim(struct swapz_map original[5],
				swapz_u32 *filler_generation)
{
	struct swapz_compressed_page page;
	swapz_u8 completed;
	unsigned int index;
	int error = setup();

	if (error)
		return error;
	for (index = 0; index < 5; ++index) {
		memset(late_payloads[index], (int)index + 0x61,
		       sizeof(late_payloads[index]));
		page = (struct swapz_compressed_page) {
			.logical_page = index,
			.payload = late_payloads[index],
			.length = SWAPZ_MAX_COMPRESSED,
		};
		completed = 0;
		error = swapz_engine_write_window_batched(&e, &page, 1,
							 &completed);
		if (error || completed != 1)
			return error ? error : -EUCLEAN;
		original[index] = maps[index];
	}
	while (a.next_block < SWAPZ_SEGMENT_BLOCKS) {
		error = write_one(7);
		if (error)
			return error;
	}
	if (a.next_block != SWAPZ_SEGMENT_BLOCKS || !maps[7].valid)
		return -EUCLEAN;
	*filler_generation = maps[7].generation;
	error = write_one(6);
	if (error)
		return error;
	return a.open_segment == 1U ? 0 : -EUCLEAN;
}

static void prepare_gc_bulk_pages(struct swapz_compressed_page pages[5])
{
	unsigned int index;

	for (index = 0; index < 5; ++index)
		pages[index] = (struct swapz_compressed_page) {
			.logical_page = index,
			.payload = late_payloads[index],
			.length = SWAPZ_MAX_COMPRESSED,
		};
}

static int verify_gc_bulk_page(unsigned int logical)
{
	swapz_u16 length = 0;
	int error = swapz_engine_read_page(&e, logical, late_readback,
					   sizeof(late_readback), &length);

	if (error)
		return error;
	return length == sizeof(late_payloads[logical]) &&
	       !memcmp(late_readback, late_payloads[logical], length) ?
	       0 : -EUCLEAN;
}

static int test_gc_torn_run_resumes_same_destination(void)
{
	struct swapz_compressed_page pages[5];
	struct swapz_map original[5];
	swapz_u8 committed = 99;
	swapz_u32 filler_generation, start, end, index;

	CHECK(setup_gc_bulk_victim(original, &filler_generation) == 0);
	prepare_gc_bulk_pages(pages);
	e.bulk_enabled = 1;
	e.bulk_scratch = bulk_scratch;
	e.bulk_txs = bulk_txs;
	e.io.write_run = lower_write_run;
	CHECK(swapz_gc_begin_rotation(&a, 0) == 0);
	start = a.next_block;
	partial_run_blocks = 2;
	CHECK(swapz_engine_write_window_batched(&e, pages, 5,
						 &committed) == -EIO);
	CHECK(committed == 0 && !a.in_flight && !a.batch_pending);
	CHECK(a.gc_allocation && a.gc_destination == 2U &&
	      a.open_segment == a.gc_destination);
	CHECK(a.next_block == start + 5U);
	end = a.next_block;
	for (index = 0; index < 5; ++index)
		CHECK(maps[index].start_block == original[index].start_block &&
		      maps[index].generation == original[index].generation);
	for (index = start; index < end; ++index)
		CHECK(!live[index] && !classes[index]);

	/* The whole uncertain reservation stays quarantined. Retry starts after
	 * it, publishes each generation once, then finishes the same rotation. */
	committed = 0;
	CHECK(swapz_engine_write_window_batched(&e, pages, 5,
						 &committed) == 0);
	CHECK(committed == 5);
	CHECK(write_one(7) == 0);
	CHECK(swapz_gc_commit_rotation(&a, 0) == 0);
	for (index = 0; index < 5; ++index) {
		CHECK(maps[index].generation == original[index].generation + 1U);
		CHECK(maps[index].start_block >= end);
		CHECK(verify_gc_bulk_page(index) == 0);
	}
	CHECK(maps[7].generation == filler_generation + 1U);
	CHECK(verify_page(7) == 0 && verify_page(6) == 0);
	for (index = 0; index < SWAPZ_SEGMENT_BLOCKS; ++index)
		CHECK(!live[index]);
	return 0;
}

static int test_gc_publication_prefix_is_not_republished(void)
{
	struct swapz_compressed_page pages[5];
	struct swapz_map original[5];
	swapz_u8 committed = 99;
	swapz_u32 filler_generation, index;

	CHECK(setup_gc_bulk_victim(original, &filler_generation) == 0);
	prepare_gc_bulk_pages(pages);
	e.bulk_enabled = 1;
	e.bulk_scratch = bulk_scratch;
	e.bulk_txs = bulk_txs;
	e.io.write_run = lower_write_run;
	CHECK(swapz_gc_begin_rotation(&a, 0) == 0);

	/* Complete the lower run, then fail authority replay after its first
	 * extent published. The exact prefix remains authoritative. */
	corrupt_replay_tail = 1;
	CHECK(swapz_engine_write_window_batched(&e, pages, 5,
						 &committed) == -EUCLEAN);
	CHECK(committed == 4 && a.gc_allocation &&
	      a.gc_destination == 2U && a.open_segment == 2U);
	for (index = 0; index < 4; ++index)
		CHECK(maps[index].generation == original[index].generation + 1U &&
		      maps[index].start_block / SWAPZ_SEGMENT_BLOCKS == 2U);
	CHECK(maps[4].start_block == original[4].start_block &&
	      maps[4].generation == original[4].generation);

	/* Recovery retries only the unpublished victim member. Replaying the
	 * authoritative prefix would increment its generations a second time. */
	committed = 0;
	CHECK(swapz_engine_write_window_batched(&e, &pages[4], 1,
						 &committed) == 0);
	CHECK(committed == 1);
	CHECK(write_one(7) == 0);
	CHECK(swapz_gc_commit_rotation(&a, 0) == 0);
	for (index = 0; index < 5; ++index) {
		CHECK(maps[index].generation == original[index].generation + 1U);
		CHECK(verify_gc_bulk_page(index) == 0);
	}
	CHECK(maps[7].generation == filler_generation + 1U);
	CHECK(verify_page(7) == 0 && verify_page(6) == 0);
	for (index = 0; index < SWAPZ_SEGMENT_BLOCKS; ++index)
		CHECK(!live[index]);
	return 0;
}


/*
 * Production recovery contract: once begin_rotation succeeds, a failed later
 * relocation retains the SAME victim/destination ownership and monotonic
 * destination cursor. Already-published pages are absent from the victim on
 * retry, so they must not be republished or consume a second reserve.
 */
static int test_partial_gc_failures_resume_same_reserve(void)
{
	const swapz_u32 victim = 0U;
	swapz_u32 generations[4];
	swapz_u32 destination;
	unsigned int index;

	CHECK(setup() == 0);
	for (index = 0; index < SWAPZ_SEGMENT_BLOCKS - 2U; ++index)
		CHECK(write_one(0) == 0);
	CHECK(write_one(1) == 0);
	CHECK(write_one(2) == 0);
	for (index = 0; index < SWAPZ_SEGMENT_BLOCKS; ++index)
		CHECK(write_one(3) == 0);
	CHECK(write_one(4) == -ENOSPC);
	for (index = 0; index < 4; ++index)
		generations[index] = maps[index].generation;

	CHECK(swapz_gc_begin_rotation(&a, victim) == 0);
	destination = a.gc_destination;
	CHECK(destination == 2U);
	CHECK(write_one(0) == 0);
	fail_write = 1;
	CHECK(write_one(1) == -EIO);
	CHECK(swapz_gc_commit_rotation(&a, victim) == -EUCLEAN);
	CHECK(a.gc_allocation && a.gc_destination == destination &&
	      a.open_segment == destination);
	CHECK(roles[destination] == 0);
	CHECK(maps[0].start_block / SWAPZ_SEGMENT_BLOCKS == destination);
	CHECK(maps[1].start_block / SWAPZ_SEGMENT_BLOCKS == victim);

	/* Interrupt the SAME rotation again after one more publication. The
	 * second reserve must remain untouched and available. */
	CHECK(write_one(1) == 0);
	fail_write = 1;
	CHECK(write_one(2) == -EIO);
	CHECK(swapz_gc_commit_rotation(&a, victim) == -EUCLEAN);
	CHECK(a.gc_allocation && a.gc_destination == destination &&
	      a.open_segment == destination);
	CHECK(roles[3] == 0);
	for (index = 3U * SWAPZ_SEGMENT_BLOCKS;
	     index < 4U * SWAPZ_SEGMENT_BLOCKS; ++index)
		CHECK(!live[index]);

	/* Fault removed: relocate only the still-authoritative victim member,
	 * commit the role exchange, and immediately prove foreground progress. */
	CHECK(write_one(2) == 0);
	CHECK(swapz_gc_commit_rotation(&a, victim) == 0);
	CHECK(!a.gc_allocation);
	CHECK(roles[victim] == 0 && roles[destination] == 1 && roles[3] == 0);
	CHECK(write_one(4) == 0);
	for (index = 0; index < 4; ++index) {
		CHECK(maps[index].generation == generations[index] +
		      (index < 3 ? 1U : 0U));
		CHECK(verify_page(index) == 0);
	}
	CHECK(verify_page(4) == 0);
	/* The evacuated victim is reusable only after every authoritative
	 * reference left it; the untouched reserve stayed dead throughout. */
	for (index = victim * SWAPZ_SEGMENT_BLOCKS;
	     index < (victim + 1U) * SWAPZ_SEGMENT_BLOCKS; ++index)
		CHECK(!live[index]);

	/* Remove the fault, then force another complete GC cycle. Forward
	 * progress must not depend on this being the final rotation. */
	while (a.next_block < (destination + 1U) * SWAPZ_SEGMENT_BLOCKS)
		CHECK(write_one(4) == 0);
	CHECK(write_one(5) == -ENOSPC);
	fail_write = 1;
	CHECK(evacuate(1) == -EIO);
	CHECK(a.gc_allocation && a.gc_forbidden_victim == 1U &&
	      a.gc_destination == 3U && a.open_segment == 3U);
	CHECK(evacuate(1) == 0);
	CHECK(write_one(5) == 0);
	for (index = 0; index < 6; ++index)
		CHECK(verify_page(index) == 0);
	return 0;
}


int main(void)
{
	int passed = 0;

	CHECK(test_compressed_gc_handoff() == 0); passed++;
	CHECK(test_failed_gc_write_preserves_live_mapping() == 0); passed++;
	CHECK(test_failed_gc_read_preserves_live_mapping() == 0); passed++;
	CHECK(test_delayed_gc_completion_fences_mutation() == 0); passed++;
	CHECK(test_torn_lower_run_quarantines_unpublished_prefix() == 0); passed++;
	CHECK(test_late_replay_failure_reports_committed_prefix() == 0); passed++;
	CHECK(test_gc_torn_run_resumes_same_destination() == 0); passed++;
	CHECK(test_gc_publication_prefix_is_not_republished() == 0); passed++;
	CHECK(test_partial_gc_failures_resume_same_reserve() == 0); passed++;
	printf("SWAPZ_GC_ENGINE_ROTATION_TESTS_PASS=%d\n", passed);
	return 0;
}
