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

/*
 * Audit of the current failure contract, NOT a forward-progress success.
 * If a GC read/write fails after a prior relocation has published, the
 * reserved destination contains authoritative mappings. The DM worker
 * restores foreground cursors, but it cannot reuse that reserve as dead.
 * Two such failures can pin both reserves; role checks must still refuse
 * to overwrite referenced extents. Authority/worker recovery is required.
 */
static void restore_failed_gc_cursor(swapz_u32 next_block,
				     swapz_u32 open_segment,
				     swapz_u32 next_probe)
{
	a.gc_allocation = 0;
	a.gc_forbidden_open = ~(swapz_u32)0;
	a.gc_forbidden_victim = ~(swapz_u32)0;
	a.gc_destination = ~(swapz_u32)0;
	a.next_block = next_block;
	a.open_segment = open_segment;
	a.next_segment_probe = next_probe;
}

static int test_partial_gc_failures_pin_both_reserves_safely(void)
{
	const swapz_u32 victim = 0U;
	swapz_u32 saved_next, saved_open, saved_probe;
	unsigned int index;

	CHECK(setup() == 0);
	for (index = 0; index < SWAPZ_SEGMENT_BLOCKS - 2U; ++index)
		CHECK(write_one(0) == 0);
	CHECK(write_one(1) == 0);
	CHECK(write_one(2) == 0);
	for (index = 0; index < SWAPZ_SEGMENT_BLOCKS; ++index)
		CHECK(write_one(3) == 0);
	CHECK(write_one(4) == -ENOSPC);
	saved_next = a.next_block;
	saved_open = a.open_segment;
	saved_probe = a.next_segment_probe;

	CHECK(swapz_gc_begin_rotation(&a, victim) == 0);
	CHECK(a.gc_destination == 2U);
	CHECK(write_one(0) == 0);
	fail_write = 1;
	CHECK(write_one(1) == -EIO);
	CHECK(swapz_gc_commit_rotation(&a, victim) == -EUCLEAN);
	restore_failed_gc_cursor(saved_next, saved_open, saved_probe);
	CHECK(roles[2] == 0 && maps[0].start_block == 512U);
	CHECK(verify_page(0) == 0 && verify_page(1) == 0);

	CHECK(swapz_gc_begin_rotation(&a, victim) == 0);
	CHECK(a.gc_destination == 3U);
	CHECK(write_one(1) == 0);
	fail_write = 1;
	CHECK(write_one(2) == -EIO);
	CHECK(swapz_gc_commit_rotation(&a, victim) == -EUCLEAN);
	restore_failed_gc_cursor(saved_next, saved_open, saved_probe);

	/* The reserve roles remain reserved and each contains a live extent.
	 * This is safe (no reference is reused), but GC cannot make progress
	 * without an authority-owned resume/recovery protocol. */
	CHECK(a.segment_foreground[2] == 0 && a.segment_foreground[3] == 0);
	CHECK(maps[0].start_block / SWAPZ_SEGMENT_BLOCKS == 2);
	CHECK(maps[1].start_block / SWAPZ_SEGMENT_BLOCKS == 3);
	CHECK(maps[2].start_block / SWAPZ_SEGMENT_BLOCKS == victim);
	CHECK(live[maps[0].start_block] && live[maps[1].start_block] &&
	      live[maps[2].start_block]);
	CHECK(swapz_gc_begin_rotation(&a, victim) == -ENOSPC);
	CHECK(write_one(4) == -ENOSPC);
	for (index = 0; index < 4; ++index)
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
	CHECK(test_partial_gc_failures_pin_both_reserves_safely() == 0); passed++;
	printf("SWAPZ_GC_ENGINE_ROTATION_TESTS_PASS=%d\n", passed);
	return 0;
}
