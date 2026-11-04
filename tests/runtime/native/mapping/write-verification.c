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
static swapz_u8 extent_sequence_delta[NPHYS];
static swapz_u32 segment_sequence_base[NPHYS / SWAPZ_SEGMENT_BLOCKS];
static struct swapz_authority auth;
static struct swapz_engine engine;
static swapz_u8 scratch_w[16384], scratch_r[16384];
static swapz_u8 disk[NPHYS * SWAPZ_BLOCK_BYTES];
static swapz_u8 payloads[3][2072];
static struct swapz_compressed_page pages[3];
static swapz_u32 writes, reads;
static swapz_u32 last_lower_write_block;
static swapz_u8 last_lower_write_blocks;
static int corrupt_after_write, fail_read, lie_about_completion;
static int partial_write_error, short_success;
/* One-shot lower rejection before a single physical block is written. */
static int injected_write_error;

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
	last_lower_write_block = block;
	last_lower_write_blocks = blocks;
	if (injected_write_error) {
		const int error = injected_write_error;

		injected_write_error = 0;
		return error;
	}
	if (lie_about_completion) {
		*completed = blocks + 1U;
		return 0;
	}
	if (partial_write_error || short_success) {
		swapz_u8 partial = blocks > 1U ? blocks - 1U : 0U;

		if (partial)
			memcpy(disk + offset, bytes,
			       (size_t)partial * SWAPZ_BLOCK_BYTES);
		*completed = partial;
		return partial_write_error ? -EIO : 0;
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
	last_lower_write_block = 0;
	last_lower_write_blocks = 0;
	corrupt_after_write = fail_read = lie_about_completion = 0;
	partial_write_error = short_success = injected_write_error = 0;
	if (swapz_authority_init(&auth, map, live, klass, 64, NPHYS) ||
	    swapz_enable_extent_sequence_index(
		    &auth, extent_sequence_delta, segment_sequence_base,
		    NPHYS / SWAPZ_SEGMENT_BLOCKS))
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

static int test_compressed_engine_reader_rejects_raw_map_before_io(void)
{
	const swapz_u32 logical_page = 7;
	struct swapz_tx tx;
	swapz_u8 output[SWAPZ_BLOCK_BYTES];
	swapz_u16 output_length = 99;

	CHECK(setup() == 0);
	memset(scratch_w, 0x5a, SWAPZ_BLOCK_BYTES);
	CHECK(swapz_stage(&auth, &logical_page, 1, 1, &tx) == 0);
	CHECK(swapz_finish_raw(&auth, &tx, scratch_w, 1, 0) == 0);
	CHECK(map[logical_page].valid && map[logical_page].raw);
	CHECK(swapz_engine_read_page(&engine, logical_page, output,
				     sizeof(output), &output_length) == -ESTALE);
	CHECK(reads == 0 && output_length == 0);
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

static int test_partial_or_short_write_never_publishes(void)
{
	unsigned int mode;

	for (mode = 0; mode < 2U; ++mode) {
		swapz_u8 committed = 99;
		size_t lower_write_offset;
		size_t byte_index;

		CHECK(setup() == 0);
		engine.verify_after_write = 1;
		partial_write_error = mode == 0U;
		short_success = mode == 1U;
		CHECK(swapz_engine_write_window_batched(
			      &engine, pages, 3, &committed) == -EIO);
		CHECK(committed == 0 && writes == 1 && reads == 0);
		CHECK(engine.submitted_blocks == 2 &&
		      engine.completed_blocks == 1);
		CHECK(last_lower_write_blocks == 2U);
		lower_write_offset =
			(size_t)last_lower_write_block * SWAPZ_BLOCK_BYTES;
		/* The lower callback must really write the acknowledged prefix. */
		CHECK(!memcmp(disk + lower_write_offset, scratch_w,
			      SWAPZ_BLOCK_BYTES));
		/* Its unacknowledged block must remain physically untouched. */
		for (byte_index = 0; byte_index < SWAPZ_BLOCK_BYTES;
		     ++byte_index)
			CHECK(disk[lower_write_offset + SWAPZ_BLOCK_BYTES +
				   byte_index] == 0);
		CHECK(engine.write_verify_read_blocks == 0);
		CHECK(auth.abandoned_blocks == 2 && !auth.in_flight);
		CHECK(!map[0].valid && !map[1].valid && !map[2].valid);
	}
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

	/* A new authoritative generation cannot reuse old metadata. The old
	 * immutable physical extent may remain resident because this append
	 * mutates a disjoint range; the authoritative start-block mismatch must
	 * still force a fresh lower read for generation 2. */
	memset(payloads[0], 0x5a, sizeof(payloads[0]));
	CHECK(swapz_engine_write_window_batched(&engine, pages, 3, &committed) == 0);
	CHECK(committed == 3 && engine.read_cache_valid);
	CHECK(engine.read_cached_start_block == old_start);
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


/*
 * Rejected lower writes must retain the last acknowledged generation, even
 * when the next attempt reuses the SAME scratch buffer for different bytes.
 * The abandoned physical reservation is never a retry destination.
 */
static int test_lower_rejection_retry_rebuilds_scratch(void)
{
	static const int errors[] = { -EIO, -ENOSPC };
	unsigned int fault;

	for (fault = 0; fault < sizeof(errors) / sizeof(errors[0]); ++fault) {
		struct swapz_map prior_maps[3];
		swapz_u8 committed = 99, result[2072];
		swapz_u16 length = 0;
		swapz_u32 rejected_start;
		swapz_u8 rejected_blocks;
		size_t rejected_offset, rejected_bytes, byte_index;
		unsigned int logical;

		CHECK(setup() == 0);
		engine.verify_after_write = 1;
		CHECK(swapz_engine_write_window_batched(
			      &engine, pages, 3, &committed) == 0);
		CHECK(committed == 3);
		memcpy(prior_maps, map, sizeof(prior_maps));
		CHECK(prior_maps[0].extent_blocks == 2U);
		for (logical = 1; logical < 3U; ++logical)
			CHECK(prior_maps[logical].start_block ==
			      prior_maps[0].start_block);
		rejected_start = auth.next_block;
		rejected_blocks = prior_maps[0].extent_blocks;
		rejected_offset = (size_t)rejected_start * SWAPZ_BLOCK_BYTES;
		rejected_bytes = (size_t)rejected_blocks * SWAPZ_BLOCK_BYTES;
		for (logical = 0; logical < 3U; ++logical)
			memset(payloads[logical],
			       0x71 + (int)(fault * 3U + logical),
			       sizeof(payloads[logical]));
		injected_write_error = errors[fault];
		CHECK(swapz_engine_write_window_batched(
			      &engine, pages, 3, &committed) == errors[fault]);
		CHECK(committed == 0 && !auth.in_flight);
		CHECK(engine.completed_blocks == rejected_blocks);
		CHECK(live[prior_maps[0].start_block] == 3U &&
		      !live[rejected_start]);
		CHECK(auth.next_block == rejected_start + rejected_blocks &&
		      auth.abandoned_blocks == rejected_blocks &&
		      auth.committed_blocks == rejected_blocks);
		for (logical = 0; logical < 3U; ++logical) {
			CHECK(map[logical].valid &&
			      map[logical].start_block ==
				prior_maps[logical].start_block &&
			      map[logical].generation ==
				prior_maps[logical].generation);
			CHECK(swapz_engine_read_page(&engine, logical, result,
						     sizeof(result), &length) == 0);
			CHECK(length == sizeof(result));
			for (byte_index = 0; byte_index < sizeof(result); ++byte_index)
				CHECK(result[byte_index] == (swapz_u8)(logical + 1U));
		}
		for (byte_index = 0; byte_index < rejected_bytes; ++byte_index)
			CHECK(disk[rejected_offset + byte_index] == 0);

		/* Deliberately poison the now-free scratch before preparing a retry:
		 * every record in the new extent must be rebuilt from caller payloads. */
		memset(scratch_w, 0xa5, sizeof(scratch_w));
		CHECK(swapz_engine_write_window_batched(
			      &engine, pages, 3, &committed) == 0);
		CHECK(committed == 3 && !auth.in_flight);
		CHECK(engine.completed_blocks ==
		      (swapz_u32)rejected_blocks * 2U);
		CHECK(!live[prior_maps[0].start_block] && !live[rejected_start] &&
		      live[map[0].start_block] == 3U);
		for (logical = 0; logical < 3U; ++logical) {
			CHECK(map[logical].generation ==
			      prior_maps[logical].generation + 1U &&
			      map[logical].start_block >=
				rejected_start + rejected_blocks);
			CHECK(swapz_engine_read_page(&engine, logical, result,
						     sizeof(result), &length) == 0);
			CHECK(length == sizeof(result) &&
			      !memcmp(result, payloads[logical], length));
		}
		/* The retry starts after the abandoned extent and cannot overwrite it. */
		for (byte_index = 0; byte_index < rejected_bytes; ++byte_index)
			CHECK(disk[rejected_offset + byte_index] == 0);
	}
	return 0;
}


/*
 * Production engine/codec integration: input ownership is checked before
 * the sole unprehashed payload CRC. This fixture is fully in-memory. The
 * owner supplies the run bytes/transactions and alone submits lower I/O
 * after successful preparation. No kernel device or storage is opened.
 *
 * SWAPZ_TEST_PREHASH_BEFORE_VALIDATE is an intentionally BROKEN native-only
 * negative control. Build with ASan and that macro to make a caller hash
 * the poisoned overlapping source before the codec can reject it; ASan
 * must report a use-after-poison. Never enable it in production builds.
 */
#if defined(__SANITIZE_ADDRESS__)
#define SWAPZ_NATIVE_ASAN 1
#elif defined(__has_feature)
#if __has_feature(address_sanitizer)
#define SWAPZ_NATIVE_ASAN 1
#endif
#endif

#ifdef SWAPZ_NATIVE_ASAN
#include <sanitizer/asan_interface.h>
#endif
#if defined(SWAPZ_TEST_PREHASH_BEFORE_VALIDATE) && !defined(SWAPZ_NATIVE_ASAN)
#error "The broken prehash control must only execute under ASan"
#endif

#define PROOF_RUN_BYTES (SWAPZ_BULK_BLOCKS * SWAPZ_BLOCK_BYTES)
static swapz_u8 proof_run_storage[PROOF_RUN_BYTES + 2U * SWAPZ_BLOCK_BYTES];
static struct swapz_tx proof_transactions[SWAPZ_MAX_RECORDS];
static swapz_u8 proof_segment_roles[NPHYS / SWAPZ_SEGMENT_BLOCKS];
static swapz_u8 proof_independent[3][SWAPZ_BLOCK_BYTES];
static swapz_u32 proof_lower_writes;
static swapz_u32 proof_publications;

struct proof_diagnostic {
	const char *phase;
	const char *category;
	long boundary_offset;
	swapz_u16 length;
	int expected_errno;
	int actual_errno;
	swapz_u32 writes_before;
	swapz_u32 publications_before;
};

#define PROOF_CHECK(diagnostic, condition) do { \
	if (!(condition)) { \
		fprintf(stderr, "engine_phase=%s input=%s boundary_offset=%ld " \
			"length=%u expected_errno=%d actual_errno=%d " \
			"write_advanced=%u publication_advanced=%u " \
			"at=%s:%d check=%s\n", \
			(diagnostic)->phase, (diagnostic)->category, \
			(diagnostic)->boundary_offset, (unsigned int)(diagnostic)->length, \
			(diagnostic)->expected_errno, (diagnostic)->actual_errno, \
			proof_lower_writes != (diagnostic)->writes_before, \
			proof_publications != (diagnostic)->publications_before, \
			__FILE__, __LINE__, #condition); \
		return 1; \
	} \
} while (0)

/* This is an in-memory lower completion, not a production I/O simulator. */
static int proof_write_run(void *opaque, swapz_u32 start_block,
			   swapz_u16 blocks, const swapz_u8 *bytes,
			   swapz_u16 *completed_blocks)
{
	(void)opaque;
	*completed_blocks = 0;
	if (!blocks || start_block >= NPHYS ||
	    blocks > NPHYS - start_block)
		return -ERANGE;
	proof_lower_writes++;
	memcpy(disk + (size_t)start_block * SWAPZ_BLOCK_BYTES, bytes,
	       (size_t)blocks * SWAPZ_BLOCK_BYTES);
	*completed_blocks = blocks;
	return 0;
}

static int proof_initialize_run(struct swapz_io_run *run)
{
	int error;

	memset(proof_run_storage, 0x73, sizeof(proof_run_storage));
	memset(proof_transactions, 0, sizeof(proof_transactions));
	memset(proof_independent, 0x4b, sizeof(proof_independent));
	memset(run, 0, sizeof(*run));
	/* A one-page prefix allows legal left-edge contact and straddling. */
	run->bytes = proof_run_storage + SWAPZ_BLOCK_BYTES;
	run->txs = proof_transactions;
	engine.bulk_enabled = 1;
	engine.bulk_scratch = run->bytes;
	engine.bulk_txs = run->txs;
	engine.io.write_run = proof_write_run;
	/* Batched snapshots are a production segment-rotation feature. Enable the
	 * same authority mode before the first reservation in each proof case. */
	auth.reuse_dead_segments = 1;
	error = swapz_enable_segment_rotation(
		&auth, proof_segment_roles,
		NPHYS / SWAPZ_SEGMENT_BLOCKS);
	if (error)
		return error;
	proof_lower_writes = 0;
	proof_publications = 0;
	return 0;
}

/* The production prepare/complete pair, with an explicit lower-I/O owner. */
static int proof_prepare_and_complete(struct swapz_io_run *run,
				      const struct swapz_compressed_page *input,
				      swapz_u8 count, swapz_u8 *published)
{
	swapz_u8 prepared = 0;
	swapz_u16 completed = 0;
	int error;

	*published = 0;
	error = swapz_engine_prepare_batched_run(&engine, input, count, run,
						  &prepared, 0);
	if (error)
		return error;
	if (prepared != count)
		return -EUCLEAN;
	engine.submitted_blocks += run->blocks;
	error = proof_write_run(NULL, run->start_block, run->blocks,
				run->bytes, &completed);
	error = swapz_engine_complete_batched_run(&engine, run, completed,
						   error, published);
	if (!error)
		proof_publications += *published;
	return error;
}

static int proof_reservations_clear(void)
{
	return !auth.in_flight && !auth.batch_pending &&
	       !auth.batch_replaying && !auth.batch_stage_allowed;
}

static int test_engine_prepare_alias_validation_before_crc(void)
{
	static const struct {
		const char *category;
		long offset;
		swapz_u16 length;
		swapz_u8 prehashed;
	} aliases[] = {
		{ "compressed-inside-unhashed", 128, 96, 0 },
		{ "compressed-inside-prehashed", 256, 96, 1 },
		{ "compressed-at-start", 0, 96, 0 },
		{ "compressed-straddles-start", -32, 64, 0 },
		{ "compressed-straddles-end", SWAPZ_BLOCK_BYTES - 32, 64, 1 },
	};
	unsigned int case_index;

	for (case_index = 0; case_index < sizeof(aliases) / sizeof(aliases[0]);
	     ++case_index) {
		struct swapz_io_run run;
		struct swapz_compressed_page input = { 0 };
		struct swapz_map prior;
		struct proof_diagnostic diagnostic = {
			.phase = "baseline",
			.category = aliases[case_index].category,
			.boundary_offset = aliases[case_index].offset,
			.length = aliases[case_index].length,
		};
		swapz_u8 published = 0;
		swapz_u8 *source;
#ifdef SWAPZ_NATIVE_ASAN
		swapz_u8 *poisoned;
#endif
		swapz_u32 abandoned_before, reservation_before, committed_before;
		swapz_u32 prehashed_before;
		swapz_u16 read_length = 0;
		swapz_u8 readback[128];
		int error;

		PROOF_CHECK(&diagnostic, setup() == 0);
		PROOF_CHECK(&diagnostic, proof_initialize_run(&run) == 0);
		input.logical_page = 5;
		input.payload = proof_independent[0];
		input.length = 96;
		input.encoding = SWAPZ_ENCODING_LZ4;
		diagnostic.expected_errno = 0;
		error = proof_prepare_and_complete(&run, &input, 1, &published);
		diagnostic.actual_errno = error;
		PROOF_CHECK(&diagnostic, error == 0 && published == 1);
		PROOF_CHECK(&diagnostic, map[5].valid && map[5].generation == 1);
		prior = map[5];
		diagnostic.phase = "reject-before-hash";
		diagnostic.expected_errno = -EINVAL;
		diagnostic.writes_before = proof_lower_writes;
		diagnostic.publications_before = proof_publications;
		prehashed_before = engine.prehashed_records;
		abandoned_before = auth.abandoned_blocks;
		reservation_before = auth.next_block;
		committed_before = auth.committed_blocks;

		source = run.bytes + aliases[case_index].offset;
		input.payload = source;
		input.length = aliases[case_index].length;
		input.payload_crc32c_valid = aliases[case_index].prehashed;
		/* A caller-provided prehash is not recomputed on the fast path. */
		input.payload_crc32c = 0xa0b1c2d3U;
#ifdef SWAPZ_NATIVE_ASAN
		poisoned = run.bytes + (aliases[case_index].offset < 0 ? 20 :
			aliases[case_index].offset >= SWAPZ_BLOCK_BYTES - 32 ?
				SWAPZ_BLOCK_BYTES - 24 :
				aliases[case_index].offset + 24);
		__asan_poison_memory_region(poisoned, 8);
#endif
#ifdef SWAPZ_TEST_PREHASH_BEFORE_VALIDATE
		/* Broken producer: deterministically reads poisoned scratch. */
		input.payload_crc32c = swapz_crc32c_bytes(input.payload, input.length);
		input.payload_crc32c_valid = 1;
#endif
		published = 99;
		error = swapz_engine_prepare_batched_run(&engine, &input, 1, &run,
							&published, 0);
#ifdef SWAPZ_NATIVE_ASAN
		__asan_unpoison_memory_region(poisoned, 8);
#endif
		diagnostic.actual_errno = error;
		PROOF_CHECK(&diagnostic, error == -EINVAL && published == 0);
		PROOF_CHECK(&diagnostic, proof_lower_writes == diagnostic.writes_before);
		PROOF_CHECK(&diagnostic,
			    proof_publications == diagnostic.publications_before);
		PROOF_CHECK(&diagnostic, proof_reservations_clear() &&
			    auth.committed_blocks == committed_before);
		PROOF_CHECK(&diagnostic, auth.next_block > reservation_before &&
			    auth.abandoned_blocks > abandoned_before);
		PROOF_CHECK(&diagnostic, map[5].valid &&
			    memcmp(&prior, &map[5], sizeof(prior)) == 0);
		PROOF_CHECK(&diagnostic,
			    engine.prehashed_records == prehashed_before);

		/*
		 * Deliberately reuse the failed run image. The independent retry
		 * must rebuild it and publish a fresh generation, never retain a
		 * pointer to its former caller-owned overlapping source.
		 */
		diagnostic.phase = "independent-retry";
		diagnostic.expected_errno = 0;
		input.payload = proof_independent[1];
		input.length = 96;
		input.payload_crc32c_valid = 1;
		input.payload_crc32c = swapz_crc32c_bytes(input.payload, input.length);
		published = 0;
		error = proof_prepare_and_complete(&run, &input, 1, &published);
		diagnostic.actual_errno = error;
		PROOF_CHECK(&diagnostic, error == 0 && published == 1);
		PROOF_CHECK(&diagnostic, proof_reservations_clear());
		PROOF_CHECK(&diagnostic, map[5].generation == 2 &&
			    map[5].start_block != prior.start_block);
		PROOF_CHECK(&diagnostic,
			    engine.prehashed_records == prehashed_before + 1U);
		PROOF_CHECK(&diagnostic,
			    swapz_engine_read_page(&engine, 5, readback,
					      sizeof(readback), &read_length) == 0);
		PROOF_CHECK(&diagnostic, read_length == input.length &&
			    !memcmp(readback, input.payload, read_length));
	}
	return 0;
}

static int test_engine_prepare_boundary_contact_and_packed_siblings(void)
{
	struct swapz_io_run run;
	struct swapz_compressed_page input[3] = { { 0 } };
	struct swapz_decoded record;
	struct proof_diagnostic diagnostic = {
		.phase = "packed-prepare",
		.category = "compressed-packed-siblings",
		.boundary_offset = SWAPZ_BLOCK_BYTES,
		.length = 96,
	};
	const swapz_u8 *encoded;
	swapz_u8 published = 0, prepared = 0;
	swapz_u16 completed = 0;
	swapz_u8 index;
	int error;

	PROOF_CHECK(&diagnostic, setup() == 0);
	PROOF_CHECK(&diagnostic, proof_initialize_run(&run) == 0);
	for (index = 0; index < 3; ++index) {
		memset(proof_independent[index], 0x31 + index, 128);
		input[index].logical_page = 10U + index;
		input[index].payload = proof_independent[index];
		input[index].length = 96;
		input[index].encoding = index == 0 ? SWAPZ_ENCODING_LZ4 :
			index == 1 ? SWAPZ_ENCODING_DELTA64 :
				     SWAPZ_ENCODING_DELTA64_SHUF8;
		input[index].payload_crc32c_valid = index != 1;
		if (input[index].payload_crc32c_valid)
			input[index].payload_crc32c = swapz_crc32c_bytes(
				input[index].payload, input[index].length);
	}
	error = swapz_engine_prepare_batched_run(&engine, input, 3,
						  &run, &prepared, 0);
	diagnostic.actual_errno = error;
	PROOF_CHECK(&diagnostic, !error && prepared == 3 &&
		    run.extent_count == 1 && run.takes[0] == 3 &&
		    run.blocks == 1 && proof_lower_writes == 0);
	PROOF_CHECK(&diagnostic, engine.prehashed_records == 2);
	for (index = 0; index < 3; ++index) {
		PROOF_CHECK(&diagnostic,
			    swapz_lookup(run.bytes, SWAPZ_BLOCK_BYTES,
					 index, &record, &encoded) == 0);
		PROOF_CHECK(&diagnostic, record.logical_page == 10U + index &&
			    record.generation == 1 &&
			    record.encoding == input[index].encoding &&
			    record.payload_length == input[index].length &&
			    record.payload_crc32c == swapz_crc32c_bytes(
				    input[index].payload, input[index].length) &&
			    !memcmp(encoded, input[index].payload, record.payload_length));
	}
	diagnostic.phase = "packed-completion";
	PROOF_CHECK(&diagnostic,
		    proof_write_run(NULL, run.start_block, run.blocks,
				    run.bytes, &completed) == 0);
	error = swapz_engine_complete_batched_run(&engine, &run, completed, 0,
						  &published);
	diagnostic.actual_errno = error;
	PROOF_CHECK(&diagnostic, !error && published == 3);
	proof_publications += published;
	PROOF_CHECK(&diagnostic, proof_reservations_clear() &&
		    live[map[10].start_block] == 3);
	PROOF_CHECK(&diagnostic, map[10].start_block == map[11].start_block &&
		    map[11].start_block == map[12].start_block);

	/*
	 * The synchronous public batched writer must also stop at its REAL
	 * prepare boundary: a legal sibling was appended into this image,
	 * but the next sibling aliases the same extent. No lower WRITE or
	 * partial sibling publication may escape the failed pack.
	 */
	{
		struct swapz_compressed_page rejected[2] = { { 0 } };
#ifdef SWAPZ_NATIVE_ASAN
		swapz_u8 *poisoned = run.bytes + 280;
#endif
		swapz_u32 before_writes = proof_lower_writes;
		swapz_u32 before_publications = proof_publications;
		swapz_u32 before_abandoned = auth.abandoned_blocks;
		swapz_u32 before_committed = auth.committed_blocks;
		swapz_u8 committed = 99;

		diagnostic.phase = "packed-overlap-rejection";
		diagnostic.category = "compressed-second-sibling";
		diagnostic.boundary_offset = 256;
		diagnostic.length = 96;
		diagnostic.expected_errno = -EINVAL;
		diagnostic.writes_before = before_writes;
		diagnostic.publications_before = before_publications;
		rejected[0] = input[0];
		rejected[0].logical_page = 30;
		rejected[1] = input[1];
		rejected[1].logical_page = 31;
		rejected[1].payload = run.bytes + 256;
#ifdef SWAPZ_NATIVE_ASAN
		__asan_poison_memory_region(poisoned, 8);
#endif
		error = swapz_engine_write_window_batched(&engine, rejected, 2,
							 &committed);
#ifdef SWAPZ_NATIVE_ASAN
		__asan_unpoison_memory_region(poisoned, 8);
#endif
		diagnostic.actual_errno = error;
		PROOF_CHECK(&diagnostic, error == -EINVAL && committed == 0);
		PROOF_CHECK(&diagnostic, proof_lower_writes == before_writes &&
			    proof_publications == before_publications);
		PROOF_CHECK(&diagnostic, proof_reservations_clear() &&
			    auth.committed_blocks == before_committed &&
			    auth.abandoned_blocks > before_abandoned);
		PROOF_CHECK(&diagnostic, !map[30].valid && !map[31].valid &&
			    !map[30].generation && !map[31].generation);

		diagnostic.phase = "packed-independent-retry";
		diagnostic.expected_errno = 0;
		rejected[1].payload = proof_independent[1];
		error = proof_prepare_and_complete(&run, rejected, 2, &published);
		diagnostic.actual_errno = error;
		PROOF_CHECK(&diagnostic, !error && published == 2 &&
			    map[30].valid && map[31].valid &&
			    map[30].start_block == map[31].start_block &&
			    map[30].generation == 1 && map[31].generation == 1);
	}

	/* Exactly touching either one-block boundary is not overlap. */
	for (index = 0; index < 2; ++index) {
		swapz_u8 *contact = index == 0 ?
			run.bytes - 96 : run.bytes + SWAPZ_BLOCK_BYTES;

		diagnostic.phase = "boundary-contact";
		diagnostic.category = index == 0 ?
			"compressed-left-contact" : "compressed-right-contact";
		diagnostic.boundary_offset = index == 0 ?
			-96L : (long)SWAPZ_BLOCK_BYTES;
		input[0].logical_page = 20U + index;
		input[0].payload = contact;
		input[0].length = 96;
		input[0].payload_crc32c_valid = 0;
		error = proof_prepare_and_complete(&run, input, 1, &published);
		diagnostic.actual_errno = error;
		PROOF_CHECK(&diagnostic, !error && published == 1 &&
			    map[input[0].logical_page].valid);
	}

	/* RAW bypasses the compressed CRC gate, but remains a real run. */
	diagnostic.phase = "raw-contact";
	diagnostic.category = "raw-disjoint";
	diagnostic.boundary_offset = SWAPZ_BLOCK_BYTES;
	diagnostic.length = SWAPZ_BLOCK_BYTES;
	input[0].logical_page = 25;
	input[0].raw = 1;
	input[0].length = SWAPZ_BLOCK_BYTES;
	input[0].payload = run.bytes + SWAPZ_BLOCK_BYTES;
	error = proof_prepare_and_complete(&run, input, 1, &published);
	diagnostic.actual_errno = error;
	PROOF_CHECK(&diagnostic, !error && published == 1 &&
		    map[25].valid && map[25].raw);
	/* The zero-page decision belongs above encoded preparation. */
	memset(proof_independent[2], 0, SWAPZ_BLOCK_BYTES);
	PROOF_CHECK(&diagnostic, swapz_page_is_zero(proof_independent[2]));
	PROOF_CHECK(&diagnostic, swapz_discard_page(&auth, 25) == 0);
	PROOF_CHECK(&diagnostic, !map[25].valid && map[25].generation == 2);
	input[0].raw = 0;
	input[0].length = 96;
	input[0].payload = proof_independent[0];
	input[0].encoding = SWAPZ_ENCODING_LZ4;
	error = proof_prepare_and_complete(&run, input, 1, &published);
	diagnostic.actual_errno = error;
	PROOF_CHECK(&diagnostic, !error && published == 1 &&
		    map[25].valid && !map[25].raw && map[25].generation == 3);
	return 0;
}

static int test_engine_prepare_preflight_never_submits(void)
{
	static const struct {
		const char *category;
		swapz_u16 length;
		swapz_u8 encoding;
		swapz_u8 raw;
		int expected;
	} cases[] = {
		{ "unsupported-encoding", 96, SWAPZ_ENCODING_INVALID, 0, -EINVAL },
		{ "oversize-compressed", SWAPZ_MAX_COMPRESSED + 1U,
		  SWAPZ_ENCODING_LZ4, 0, -EINVAL },
		{ "zero-length", 0, SWAPZ_ENCODING_LZ4, 0, -EINVAL },
		{ "short-raw", 96, SWAPZ_ENCODING_LZ4, 1, -EINVAL },
	};
	struct swapz_io_run run;
	struct swapz_compressed_page input = { 0 };
	struct proof_diagnostic diagnostic = {
		.phase = "preflight",
		.boundary_offset = 0,
	};
	swapz_u8 committed = 99;
	unsigned int index;
	int error;

	PROOF_CHECK(&diagnostic, setup() == 0);
	PROOF_CHECK(&diagnostic, proof_initialize_run(&run) == 0);
	input.logical_page = 33;
	input.payload = proof_independent[0];
	input.payload_crc32c_valid = 1;
	input.payload_crc32c = 0x12345678U;
	for (index = 0; index < sizeof(cases) / sizeof(cases[0]); ++index) {
		diagnostic.category = cases[index].category;
		diagnostic.length = cases[index].length;
		diagnostic.expected_errno = cases[index].expected;
		diagnostic.writes_before = proof_lower_writes;
		diagnostic.publications_before = proof_publications;
		input.length = cases[index].length;
		input.encoding = cases[index].encoding;
		input.raw = cases[index].raw;
		committed = 99;
		error = swapz_engine_prepare_batched_run(&engine, &input, 1,
						      &run, &committed, 0);
		diagnostic.actual_errno = error;
		PROOF_CHECK(&diagnostic, error == cases[index].expected &&
			    committed == 0 && proof_reservations_clear() &&
			    !map[33].valid && map[33].generation == 0 &&
			    proof_lower_writes == diagnostic.writes_before);
	}
	diagnostic.category = "generation-overflow";
	diagnostic.length = 96;
	diagnostic.expected_errno = -EOVERFLOW;
	input.length = 96;
	input.encoding = SWAPZ_ENCODING_LZ4;
	input.raw = 0;
	map[33].generation = ~(swapz_u32)0;
	committed = 99;
	error = swapz_engine_prepare_batched_run(&engine, &input, 1,
						      &run, &committed, 0);
	diagnostic.actual_errno = error;
	PROOF_CHECK(&diagnostic, error == -EOVERFLOW && committed == 0 &&
		    proof_reservations_clear() && !map[33].valid &&
		    map[33].generation == ~(swapz_u32)0);
	map[33].generation = 0;

	/* Exhaust the finite append-only placement boundary before a snapshot can
	 * pause. This isolates capacity admission from dead-segment recycling. */
	auth.reuse_dead_segments = 0;
	diagnostic.category = "physical-capacity";
	diagnostic.expected_errno = -ENOSPC;
	auth.next_block = NPHYS;
	committed = 99;
	error = swapz_engine_prepare_batched_run(&engine, &input, 1,
						      &run, &committed, 0);
	diagnostic.actual_errno = error;
	PROOF_CHECK(&diagnostic, error == -ENOSPC && committed == 0 &&
		    proof_reservations_clear() && !map[33].valid &&
		    proof_lower_writes == diagnostic.writes_before &&
		    proof_publications == diagnostic.publications_before);
	return 0;
}


int main(void)
{
	int passed = 0;

	CHECK(test_compressed_engine_reader_rejects_raw_map_before_io() == 0); passed++;
	CHECK(test_good_full_readback_publishes() == 0); passed++;
	CHECK(test_silent_media_corruption_rejected_before_publication() == 0); passed++;
	CHECK(test_readback_io_failure_preserves_unmapped() == 0); passed++;
	CHECK(test_unverified_mode_detects_corruption_later() == 0); passed++;
	CHECK(test_impossible_completion_never_fakes_write_or_readback() == 0); passed++;
	CHECK(test_partial_or_short_write_never_publishes() == 0); passed++;
	CHECK(test_preflight_requires_distinct_readback_buffers() == 0); passed++;
	CHECK(test_failed_overwrite_keeps_prior_generation() == 0); passed++;
	CHECK(test_lower_rejection_retry_rebuilds_scratch() == 0); passed++;
	CHECK(test_same_extent_read_cache_reuse_and_fail_closed() == 0); passed++;
	CHECK(test_one_block_read_budget_remains_selective() == 0); passed++;
	CHECK(test_two_block_payload_offset_skips_unneeded_second_block() == 0); passed++;
	CHECK(test_engine_prepare_alias_validation_before_crc() == 0); passed++;
	CHECK(test_engine_prepare_boundary_contact_and_packed_siblings() == 0); passed++;
	CHECK(test_engine_prepare_preflight_never_submits() == 0); passed++;
	printf("SWAPZ_VERIFY_AFTER_WRITE_TESTS_PASS=%d\n", passed);
	return 0;
}
