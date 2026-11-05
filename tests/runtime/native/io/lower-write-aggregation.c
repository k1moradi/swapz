// SPDX-License-Identifier: GPL-2.0-only
/*
 * EXACT production engine.c + authority.c + codec.c grouped-lower I/O.
 * This test is independent of the Device Mapper driver: it verifies that
 * no compressed map is committed until one full lower run has completed,
 * that 64 logical writes issue FEWER physical submissions, and that a
 * failed/short combined write leaves existing authority unchanged.
 */
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include "engine.h"
#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "FAIL: lower-write-aggregation.c:%d expression=%s\n", \
		__LINE__, #x); \
	return 1; \
} } while (0)

#define PHYSICAL (4U * SWAPZ_SEGMENT_BLOCKS)
static swapz_u8 media[PHYSICAL * SWAPZ_BLOCK_BYTES];
static struct swapz_authority a;
static struct swapz_map maps[128];
static swapz_u16 live[PHYSICAL];
static swapz_u8 classes[PHYSICAL], roles[4];
static swapz_u8 extent_sequence_delta[PHYSICAL];
static swapz_u32 segment_sequence_base[4];
static struct swapz_engine e;
static struct swapz_tx bulk_txs[SWAPZ_MAX_RECORDS];
static swapz_u8 scratch[SWAPZ_MAX_EXTENT_BYTES], reader[SWAPZ_MAX_EXTENT_BYTES];
static swapz_u8 bulk[SWAPZ_BULK_BLOCKS * SWAPZ_BLOCK_BYTES];
static swapz_u8 payloads[SWAPZ_MAX_RECORDS][SWAPZ_MAX_COMPRESSED];
static struct swapz_compressed_page pages[SWAPZ_MAX_RECORDS];
/* Exact 4KiB raw originals, distinct from the compressed test payloads. */
static swapz_u8 raw_payloads[SWAPZ_MAX_RECORDS][SWAPZ_BLOCK_BYTES];
static unsigned int extent_calls, run_calls, read_calls;
static unsigned int fail_on_run;
static unsigned int partial_fail_on_run;
static unsigned int overcomplete_fail_on_run;
static unsigned int unsupported_on_run;
static unsigned int corrupt_on_run;
static unsigned int short_on_run;
static unsigned int maps_visible_during_run;
static unsigned int ownership_violation;
static unsigned int sealed_calls, sealed_pages;
static unsigned int published_calls, published_pages;
static unsigned int sealed_missing_before_lower;
static unsigned int publication_visibility_errors;
static swapz_u8 sealed_pending_pages;
static unsigned long long lower_written_bytes;

static int read_blocks(void *opaque, swapz_u32 block, swapz_u8 blocks, swapz_u8 *out)
{
	(void)opaque;
	if (block >= PHYSICAL || blocks > PHYSICAL - block)
		return -ERANGE;
	memcpy(out, media + (size_t)block * SWAPZ_BLOCK_BYTES,
	       (size_t)blocks * SWAPZ_BLOCK_BYTES);
	read_calls++;
	return 0;
}

static int write_extent(void *opaque, swapz_u32 block, swapz_u8 blocks,
			const swapz_u8 *src, swapz_u8 *completed)
{
	(void)opaque;
	*completed = 0;
	if (!sealed_pending_pages)
		sealed_missing_before_lower++;
	sealed_pending_pages = 0;
	if (block >= PHYSICAL || blocks > PHYSICAL - block)
		return -ERANGE;
	memcpy(media + (size_t)block * SWAPZ_BLOCK_BYTES, src,
	       (size_t)blocks * SWAPZ_BLOCK_BYTES);
	extent_calls++;
	lower_written_bytes += (unsigned long long)blocks * SWAPZ_BLOCK_BYTES;
	*completed = blocks;
	return 0;
}

static void write_sealed(void *opaque, swapz_u8 pages_count)
{
	(void)opaque;
	sealed_calls++;
	sealed_pages += pages_count;
	sealed_pending_pages = pages_count;
}

static void write_published(void *opaque, swapz_u8 pages_count)
{
	unsigned int valid = 0;
	unsigned int index;

	(void)opaque;
	for (index = 0; index < 128; ++index)
		if (maps[index].valid)
			valid++;
	published_calls++;
	published_pages += pages_count;
	if (valid < published_pages)
		publication_visibility_errors++;
}

static int write_run(void *opaque, swapz_u32 block, swapz_u16 blocks,
		     const swapz_u8 *src, swapz_u16 *completed)
{
	swapz_u32 i;

	(void)opaque;
	*completed = 0;
	if (!sealed_pending_pages)
		sealed_missing_before_lower++;
	sealed_pending_pages = 0;
	if (!blocks || blocks > SWAPZ_BULK_BLOCKS ||
	    block >= PHYSICAL || blocks > PHYSICAL - block ||
	    block / SWAPZ_SEGMENT_BLOCKS !=
	    (block + blocks - 1U) / SWAPZ_SEGMENT_BLOCKS)
		return -ERANGE;
	run_calls++;
	{
		struct swapz_tx unauthorized;
		swapz_u32 logical = 0;

		/* Lower callback executes with staged-but-UNPUBLISHED maps.
		 * No unrelated discard or direct stage may race its ownership. */
		if (swapz_stage(&a, &logical, 1, 1, &unauthorized) != -EBUSY ||
		    swapz_discard_page(&a, logical) != -EBUSY)
			ownership_violation++;
	}
	/* Older, already completed combined runs legitimately published
	 * mappings. Only the current run's NEW generations must remain
	 * invisible until this lower callback returns success. */
	for (i = 0; i < a.batch_pending; ++i) {
		const struct swapz_tx *tx = &bulk_txs[i];
		swapz_u8 j;

		for (j = 0; j < tx->count; ++j) {
			swapz_u32 logical = tx->records[j].logical_page;

			if (maps[logical].generation >=
			    tx->records[j].generation)
				maps_visible_during_run++;
		}
	}
	if (partial_fail_on_run && run_calls == partial_fail_on_run) {
		*completed = blocks > 1U ? blocks - 1U : 0U;
		if (*completed) {
			memcpy(media + (size_t)block * SWAPZ_BLOCK_BYTES, src,
			       (size_t)*completed * SWAPZ_BLOCK_BYTES);
			lower_written_bytes +=
				(unsigned long long)*completed * SWAPZ_BLOCK_BYTES;
		}
		return -EIO;
	}
	if (overcomplete_fail_on_run && run_calls == overcomplete_fail_on_run) {
		/* Malformed completion metadata must not replace this lower EIO. */
		*completed = blocks + 1U;
		return -EIO;
	}
	if (fail_on_run && run_calls == fail_on_run)
		return -EIO;
	if (unsupported_on_run && run_calls == unsupported_on_run)
		return -EOPNOTSUPP;
	if (short_on_run && run_calls == short_on_run) {
		*completed = blocks - 1;
		memcpy(media + (size_t)block * SWAPZ_BLOCK_BYTES, src,
		       (size_t)*completed * SWAPZ_BLOCK_BYTES);
		lower_written_bytes +=
			(unsigned long long)*completed * SWAPZ_BLOCK_BYTES;
		return 0;
	}
	memcpy(media + (size_t)block * SWAPZ_BLOCK_BYTES, src,
	       (size_t)blocks * SWAPZ_BLOCK_BYTES);
	if (corrupt_on_run && run_calls == corrupt_on_run)
		media[(size_t)block * SWAPZ_BLOCK_BYTES + 7] ^= 1;
	lower_written_bytes += (unsigned long long)blocks * SWAPZ_BLOCK_BYTES;
	*completed = blocks;
	return 0;
}

static int setup(void)
{
	unsigned int i;
	int error = swapz_authority_init(&a, maps, live, classes,
					128, PHYSICAL);

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
	memset(media, 0, sizeof(media));
	memset(reader, 0xa5, sizeof(reader));
	memset(&e, 0, sizeof(e));
	e.authority = &a;
	e.io.write_extent = write_extent;
	e.io.write_run = write_run;
	e.io.write_sealed = write_sealed;
	e.io.write_published = write_published;
	e.io.read_blocks = read_blocks;
	e.write_scratch = scratch;
	e.read_scratch = reader;
	e.bulk_scratch = bulk;
	e.bulk_txs = bulk_txs;
	e.bulk_enabled = 1;
	extent_calls = run_calls = read_calls = 0;
	fail_on_run = partial_fail_on_run = overcomplete_fail_on_run = 0;
	unsupported_on_run = short_on_run = corrupt_on_run = 0;
	maps_visible_during_run = 0;
	ownership_violation = 0;
	sealed_calls = sealed_pages = 0;
	published_calls = published_pages = 0;
	sealed_missing_before_lower = 0;
	publication_visibility_errors = 0;
	sealed_pending_pages = 0;
	lower_written_bytes = 0;
	for (i = 0; i < SWAPZ_MAX_RECORDS; ++i) {
		swapz_u16 length = i % 3 == 0 ? 2089 : i % 3 == 1 ? 1032 : 2200;

		memset(payloads[i], (int)i + 1, length);
		pages[i] = (struct swapz_compressed_page){
			.logical_page = i,
			.payload = payloads[i],
			.length = length
		};
	}
	return 0;
}

static int validate_prefix(unsigned int committed)
{
	unsigned int i;

	for (i = 0; i < SWAPZ_MAX_RECORDS; ++i) {
		swapz_u8 output[SWAPZ_MAX_COMPRESSED];
		swapz_u16 length = 0;

		CHECK((maps[i].valid != 0) == (i < committed));
		if (i >= committed)
			continue;
		CHECK(swapz_engine_read_page(&e, i, output,
					  sizeof(output), &length) == 0);
		CHECK(length == pages[i].length);
		CHECK(!memcmp(output, payloads[i], length));
	}
	CHECK(!a.batch_pending && !a.in_flight);
	return 0;
}

static int test_real_aggregation_and_readback(void)
{
	swapz_u8 committed = 0;

	CHECK(setup() == 0);
	CHECK(swapz_engine_write_window_batched(&e, pages, 64,
					     &committed) == 0);
	CHECK(committed == 64);
	CHECK(!maps_visible_during_run && !ownership_violation);
	CHECK(e.bulk_extents >= 3 && run_calls >= 1);
	CHECK(run_calls < e.bulk_extents);
	CHECK(run_calls < 20);
	CHECK(extent_calls == 0);
	CHECK(e.bulk_writes == run_calls);
	CHECK(e.bulk_padding_blocks == 0); /* default never pads IO */
	CHECK(validate_prefix(64) == 0);
	return 0;
}

/*
 * A failed lower group replacing already-authoritative pages must keep
 * the OLD generations and OLD readable media intact. No upper BIO in
 * the failed group can claim success, even if the driver successfully
 * reserved every new physical extent before submitting lower I/O.
 */
static int test_overwrite_failed_run_preserves_old_pages(void)
{
	unsigned int mode;

	for (mode = 0; mode < 2U; ++mode) {
		struct swapz_map original[16];
		swapz_u8 committed = 0;
		unsigned int i, j;

		CHECK(setup() == 0);
		CHECK(swapz_engine_write_window_batched(&e, pages, 16,
						     &committed) == 0);
		CHECK(committed == 16);
		memcpy(original, maps, sizeof(original));
		for (i = 0; i < 16; ++i)
			memset(payloads[i], 0xa7, pages[i].length);
		if (mode == 0U)
			fail_on_run = run_calls + 1;
		else
			partial_fail_on_run = run_calls + 1;
		committed = 91;
		CHECK(swapz_engine_write_window_batched(&e, pages, 16,
						     &committed) == -EIO);
		CHECK(committed == 0 && !a.in_flight && !a.batch_pending);
		CHECK(a.abandoned_blocks > 0);
		CHECK(!ownership_violation && !maps_visible_during_run);
		for (i = 0; i < 16; ++i) {
			swapz_u8 output[SWAPZ_MAX_COMPRESSED];
			swapz_u16 length = 0;

			CHECK(maps[i].valid &&
			      maps[i].start_block == original[i].start_block &&
			      maps[i].generation == original[i].generation);
			CHECK(swapz_engine_read_page(&e, i, output,
						  sizeof(output), &length) == 0);
			CHECK(length == pages[i].length);
			for (j = 0; j < length; ++j)
				CHECK(output[j] == (swapz_u8)(i + 1U));
		}
	}
	return 0;
}

static int test_publication_observer_follows_authority_publish(void)
{
	swapz_u8 committed = 0;

	CHECK(setup() == 0);
	e.bulk_enabled = 0;
	CHECK(swapz_engine_write_window_batched(&e, pages, 4, &committed) == 0);
	CHECK(committed == 4 && published_pages == 4 && published_calls > 0);
	CHECK(sealed_pages == 4 && sealed_calls == published_calls);
	CHECK(!sealed_missing_before_lower && !sealed_pending_pages);
	CHECK(!publication_visibility_errors && !maps_visible_during_run);

	CHECK(setup() == 0);
	committed = 0;
	CHECK(swapz_engine_write_window_batched(&e, pages, 16, &committed) == 0);
	CHECK(committed == 16 && published_pages == 16 && published_calls > 0);
	CHECK(sealed_pages == 16 && sealed_calls == published_calls);
	CHECK(!sealed_missing_before_lower && !sealed_pending_pages);
	CHECK(!publication_visibility_errors && !maps_visible_during_run);
	return 0;
}

static int test_successful_bulk_overwrite_publishes_after_completion(void)
{
	swapz_u8 committed = 0;
	unsigned int i;

	CHECK(setup() == 0);
	CHECK(swapz_engine_write_window_batched(&e, pages, 16,
					     &committed) == 0);
	CHECK(committed == 16);
	for (i = 0; i < 16; ++i)
		memset(payloads[i], 0xb8, pages[i].length);
	committed = 0;
	CHECK(swapz_engine_write_window_batched(&e, pages, 16,
					     &committed) == 0);
	CHECK(committed == 16 && !maps_visible_during_run);
	CHECK(!a.in_flight && !a.batch_pending && !ownership_violation);
	for (i = 0; i < 16; ++i) {
		swapz_u8 output[SWAPZ_MAX_COMPRESSED];
		swapz_u16 length = 0;

		CHECK(maps[i].valid && maps[i].generation == 2);
		CHECK(swapz_engine_read_page(&e, i, output,
					  sizeof(output), &length) == 0);
		CHECK(length == pages[i].length);
		CHECK(!memcmp(output, payloads[i], length));
	}
	return 0;
}

static int test_failed_run_acks_nothing(void)
{
	swapz_u8 committed = 87;

	CHECK(setup() == 0);
	fail_on_run = 1;
	CHECK(swapz_engine_write_window_batched(&e, pages, 64,
					     &committed) == -EIO);
	CHECK(committed == 0);
	CHECK(run_calls == 1 && extent_calls == 0);
	CHECK(validate_prefix(0) == 0);
	CHECK(a.abandoned_blocks > 0);
	return 0;
}

static int test_corrupted_completed_run_detected_on_read(void)
{
	swapz_u8 committed = 77;
	int error;

	CHECK(setup() == 0);
	/* The lower callback reports full completion, but mutates the
	 * first extent's on-media header. This models corruption of
	 * submitted pages BEFORE independent CRC/mapping publication.
	 * The engine uses its original immutable RAM image for swapz_finish
	 * and must also be tested with explicit verify_after_write=1
	 * (which keeps the old serialized full readback path). */
	corrupt_on_run = 1;
	error = swapz_engine_write_window_batched(&e, pages, 64,
					       &committed);
	/* With write_verify=0, a lower device that lies about writes
	 * cannot be detected until a later read; logical publication
	 * remains valid only for the supplied immutable source image.
	 * The read MUST detect the corrupted on-media metadata. */
	CHECK(error == 0 && committed == 64);
	{
		swapz_u8 out[SWAPZ_MAX_COMPRESSED];
		swapz_u16 len = 0;

		CHECK(swapz_engine_read_page(&e, 0, out,
					  sizeof(out), &len) != 0);
	}
	CHECK(!a.batch_pending && !a.in_flight);
	return 0;
}

static int test_short_run_acks_nothing(void)
{
	swapz_u8 committed = 87;

	CHECK(setup() == 0);
	short_on_run = 1;
	CHECK(swapz_engine_write_window_batched(&e, pages, 64,
					     &committed) == -EIO);
	CHECK(committed == 0);
	CHECK(run_calls == 1 && extent_calls == 0);
	CHECK(validate_prefix(0) == 0);
	return 0;
}

static int test_duplicate_slots_use_original_sequential_path(void)
{
	swapz_u8 committed = 0;

	CHECK(setup() == 0);
	pages[1].logical_page = pages[0].logical_page;
	CHECK(swapz_engine_write_window_batched(&e, pages, 2,
					     &committed) == 0);
	CHECK(committed == 2);
	CHECK(run_calls == 0 && extent_calls >= 2);
	CHECK(maps[0].valid && maps[0].generation == 2);
	CHECK(!a.batch_pending);
	return 0;
}

static int test_padding_option_measures_exact_request_byte_tradeoff(void)
{
	const swapz_u16 uniform[4] = { 2073, 2073, 2073, 2073 };
	const swapz_u16 lengths[4] = { 2000, 2073, 2073, 2000 };
	swapz_u8 committed = 0;
	unsigned int canonical_calls;
	unsigned long long canonical_bytes;
	unsigned int i;

	/*
	 * Exact planner ties still prefer the larger existing class, so the
	 * canonical packed allocator emits one adjacent 12KiB lower run.
	 */
	CHECK(setup() == 0);
	for (i = 0; i < 4; ++i) {
		memset(payloads[i], (int)i + 1, uniform[i]);
		pages[i].length = uniform[i];
	}
	CHECK(swapz_engine_write_window_batched(&e, pages, 4,
					     &committed) == 0);
	CHECK(committed == 4 && run_calls == 1);
	CHECK(lower_written_bytes == 3U * SWAPZ_BLOCK_BYTES);
	CHECK(e.bulk_padding_blocks == 0 && validate_prefix(4) == 0);

	/*
	 * The former aligned policy made this non-tied [1,2] geometry split
	 * around an internal hole, and bulk mode 2 could explicitly write that
	 * padding. Canonical packed placement removes the hole, so both modes
	 * must now produce the same one-request, no-padding result.
	 */
	CHECK(setup() == 0);
	committed = 0;
	for (i = 0; i < 4; ++i) {
		memset(payloads[i], (int)i + 1, lengths[i]);
		pages[i].length = lengths[i];
	}
	CHECK(swapz_engine_write_window_batched(&e, pages, 4,
					     &committed) == 0);
	CHECK(committed == 4 && validate_prefix(4) == 0);
	canonical_calls = run_calls;
	canonical_bytes = lower_written_bytes;
	CHECK(canonical_calls == 1 &&
	      canonical_bytes == 3U * SWAPZ_BLOCK_BYTES);
	CHECK(e.bulk_padding_blocks == 0);
	CHECK(a.alignment_hole_blocks_foreground == 0);
	CHECK(e.run_splits_by_hole == 0);

	CHECK(setup() == 0);
	for (i = 0; i < 4; ++i) {
		memset(payloads[i], (int)i + 1, lengths[i]);
		pages[i].length = lengths[i];
	}
	e.bulk_enabled = 2;
	committed = 0;
	CHECK(swapz_engine_write_window_batched(&e, pages, 4,
					     &committed) == 0);
	CHECK(committed == 4 && validate_prefix(4) == 0);
	CHECK(run_calls == canonical_calls);
	CHECK(lower_written_bytes == canonical_bytes);
	CHECK(e.bulk_padding_blocks == 0);
	CHECK(a.alignment_hole_blocks_foreground == 0);
	CHECK(e.run_splits_by_hole == 0);
	return 0;
}

static int test_packed_placement_removes_internal_hole(void)
{
	const swapz_u16 lengths[4] = { 2000, 2073, 2073, 2000 };
	swapz_u8 committed = 0;
	unsigned int i;

	CHECK(setup() == 0);
	for (i = 0; i < 4; ++i) {
		memset(payloads[i], (int)i + 1, lengths[i]);
		pages[i].length = lengths[i];
	}
	CHECK(swapz_engine_write_window_batched(&e, pages, 4, &committed) == 0);
	CHECK(committed == 4 && validate_prefix(4) == 0);
	CHECK(run_calls == 1);
	CHECK(lower_written_bytes == 3U * SWAPZ_BLOCK_BYTES);
	CHECK(a.alignment_hole_blocks_foreground == 0);
	CHECK(a.segment_tail_waste_blocks_foreground == 0);
	CHECK(e.run_splits_by_hole == 0);
	CHECK(maps[0].start_block == 0);
	CHECK(maps[1].start_block == 1);
	CHECK(maps[2].start_block == 1);
	CHECK(maps[3].start_block == 1);
	return 0;
}

static int test_segment_tail_waste_is_accounted_before_rotation(void)
{
	swapz_u8 raw[SWAPZ_BLOCK_BYTES];
	swapz_u32 page = 80, logical = 0;
	struct swapz_tx tx;
	swapz_u8 completed = 0;
	unsigned int i;

	CHECK(setup() == 0);
	memset(raw, 0x5a, sizeof(raw));
	for (i = 0; i < SWAPZ_SEGMENT_BLOCKS - 3U; ++i) {
		CHECK(swapz_stage(&a, &page, 1, 1, &tx) == 0);
		CHECK(write_extent(NULL, tx.start_block, 1, raw, &completed) == 0);
		CHECK(swapz_finish_raw(&a, &tx, raw, completed, 0) == 0);
	}
	CHECK(a.next_block == SWAPZ_SEGMENT_BLOCKS - 3U);
	CHECK(a.alignment_hole_blocks_foreground == 0);
	CHECK(swapz_stage(&a, &logical, 1, 4, &tx) == 0);
	CHECK(tx.start_block == SWAPZ_SEGMENT_BLOCKS);
	CHECK(a.alignment_hole_blocks_foreground == 3);
	CHECK(a.segment_tail_waste_blocks_foreground == 3);
	CHECK(swapz_abort(&a, &tx) == 0);
	return 0;
}

static int test_packed_tie_uses_larger_extent_without_padding(void)
{
	const swapz_u16 uniform[4] = { 2073, 2073, 2073, 2073 };
	swapz_u8 raw[SWAPZ_BLOCK_BYTES];
	struct swapz_tx seed;
	swapz_u32 seed_page = 80;
	swapz_u8 seed_done = 0, committed = 0;
	unsigned int i;

	CHECK(setup() == 0);
	memset(raw, 0x6d, sizeof(raw));
	CHECK(swapz_stage(&a, &seed_page, 1, 1, &seed) == 0);
	CHECK(write_extent(NULL, seed.start_block, 1, raw, &seed_done) == 0);
	CHECK(swapz_finish_raw(&a, &seed, raw, seed_done, 0) == 0);
	CHECK(a.next_block == 1);
	extent_calls = 0;
	lower_written_bytes = 0;
	for (i = 0; i < 4; ++i) {
		memset(payloads[i], (int)i + 1, uniform[i]);
		pages[i].length = uniform[i];
	}
	CHECK(swapz_engine_write_window_batched(&e, pages, 4, &committed) == 0);
	CHECK(committed == 4 && run_calls == 1 && extent_calls == 0);
	CHECK(lower_written_bytes == 3U * SWAPZ_BLOCK_BYTES);
	CHECK(e.bulk_padding_blocks == 0);
	CHECK(a.next_block == 4);
	CHECK(maps[0].valid && maps[0].start_block == 1 &&
	      maps[0].extent_blocks == 2 && maps[0].record_index == 0);
	CHECK(maps[1].valid && maps[1].start_block == 1 &&
	      maps[1].extent_blocks == 2 && maps[1].record_index == 1);
	CHECK(maps[2].valid && maps[2].start_block == 1 &&
	      maps[2].extent_blocks == 2 && maps[2].record_index == 2);
	CHECK(maps[3].valid && maps[3].start_block == 3 &&
	      maps[3].extent_blocks == 1 && maps[3].record_index == 0);
	CHECK(validate_prefix(4) == 0);
	CHECK(maps[80].valid && maps[80].raw_crc32c ==
	      swapz_crc32c_bytes(raw, sizeof(raw)));
	return 0;
}

static int test_same_input_no_padding_writes_identical_bytes(void)
{
	swapz_u8 committed = 0;
	unsigned long long combined_bytes;
	unsigned int combined_calls;

	CHECK(setup() == 0);
	e.bulk_enabled = 1;
	CHECK(swapz_engine_write_window_batched(&e, pages, 64,
					     &committed) == 0);
	CHECK(committed == 64 && !e.bulk_padding_blocks);
	combined_bytes = lower_written_bytes;
	combined_calls = run_calls;
	CHECK(setup() == 0);
	e.bulk_enabled = 0;
	committed = 0;
	CHECK(swapz_engine_write_window_batched(&e, pages, 64,
					     &committed) == 0);
	CHECK(committed == 64);
	CHECK(lower_written_bytes == combined_bytes);
	CHECK(extent_calls > combined_calls);
	CHECK(validate_prefix(64) == 0);
	return 0;
}

static int test_explicit_padding_mode_preserves_crc_and_authority(void)
{
	swapz_u8 committed = 0;

	CHECK(setup() == 0);
	e.bulk_enabled = 2;
	CHECK(swapz_engine_write_window_batched(&e, pages, 64,
					     &committed) == 0);
	CHECK(committed == 64 && run_calls && !maps_visible_during_run);
	CHECK(!ownership_violation && run_calls < e.bulk_extents);
	CHECK(validate_prefix(64) == 0);
	return 0;
}

/*
 * Deterministic exact-production-C differential test: vary every record
 * size and payload over 32 windows, replay the SAME window with the old
 * one-dm_io-per-extent path and the new adjacent-only lower aggregation.
 * Planner optimizations may deliberately choose a different physical
 * extent layout. Logical generations/payload lengths and byte-exact
 * readback must remain equivalent, while the new mode must not transfer
 * one additional lower byte or expose unpublished authority.
 */
static int test_randomized_same_binary_authority_equivalence(void)
{
	struct swapz_map baseline[SWAPZ_MAX_RECORDS];
	unsigned int iteration, i, j;
	unsigned int old_calls;
	unsigned long long old_bytes;
	swapz_u32 seed = 0x5a17c0deU;
	swapz_u16 sizes[SWAPZ_MAX_RECORDS];

	for (iteration = 0; iteration < 32; ++iteration) {
		swapz_u8 committed = 0;

		for (i = 0; i < SWAPZ_MAX_RECORDS; ++i) {
			seed = seed * 1664525U + 1013904223U;
			sizes[i] = 128 + (swapz_u16)((seed >> 8) % 3350U);
		}
		CHECK(setup() == 0);
		for (i = 0; i < SWAPZ_MAX_RECORDS; ++i) {
			pages[i].length = sizes[i];
			memset(payloads[i], (int)(i + iteration + 9U),
			       sizes[i]);
		}
		e.bulk_enabled = 0;
		CHECK(swapz_engine_write_window_batched(&e, pages, 64,
						     &committed) == 0);
		CHECK(committed == 64);
		memcpy(baseline, maps, sizeof(baseline));
		old_bytes = lower_written_bytes;
		old_calls = extent_calls;
		CHECK(validate_prefix(64) == 0);

		committed = 0;
		CHECK(setup() == 0);
		for (i = 0; i < SWAPZ_MAX_RECORDS; ++i) {
			pages[i].length = sizes[i];
			memset(payloads[i], (int)(i + iteration + 9U),
			       sizes[i]);
		}
		e.bulk_enabled = 1;
		CHECK(swapz_engine_write_window_batched(&e, pages, 64,
						     &committed) == 0);
		CHECK(committed == 64);
		CHECK(!e.bulk_padding_blocks && !ownership_violation);
		CHECK(!maps_visible_during_run);
		CHECK(lower_written_bytes == old_bytes);
		CHECK(run_calls <= old_calls);
		for (j = 0; j < SWAPZ_MAX_RECORDS; ++j) {
			CHECK(maps[j].valid == baseline[j].valid);
			CHECK(maps[j].generation == baseline[j].generation);
			CHECK(maps[j].payload_length == baseline[j].payload_length);
		}
		CHECK(validate_prefix(64) == 0);
	}
	return 0;
}

static int test_bulk_control_uses_original_lower_requests(void)
{
	swapz_u8 committed = 0;

	CHECK(setup() == 0);
	e.bulk_enabled = 0;
	CHECK(swapz_engine_write_window_batched(&e, pages, 64,
					     &committed) == 0);
	CHECK(committed == 64 && run_calls == 0);
	CHECK(extent_calls > 3 && e.bulk_extents == 0);
	CHECK(validate_prefix(64) == 0);
	return 0;
}

static int test_write_verify_stays_serialized(void)
{
	swapz_u8 committed = 0;

	CHECK(setup() == 0);
	e.verify_after_write = 1;
	CHECK(swapz_engine_write_window_batched(&e, pages, 3,
					     &committed) == 0);
	CHECK(committed == 3);
	CHECK(run_calls == 0 && extent_calls);
	CHECK(!a.batch_pending);
	return 0;
}

static int test_forged_deferred_snapshot_is_rejected(void)
{
	struct swapz_tx tx, forged;
	swapz_u32 page = 0;

	CHECK(setup() == 0);
	CHECK(swapz_stage_batch(&a, &page, 1, 1, &tx) == 0);
	CHECK(swapz_batch_pause(&a, &tx) == 0);
	CHECK(!maps[0].valid && a.batch_pending == 1);
	forged = tx;
	forged.records[0].logical_page = 1;
	CHECK(swapz_batch_resume(&a, &forged) == -ESTALE);
	CHECK(!maps[0].valid && !maps[1].valid);
	CHECK(swapz_batch_resume(&a, &tx) == 0);
	CHECK(swapz_abort(&a, &tx) == 0);
	CHECK(!a.batch_pending && !a.in_flight && !maps[0].valid);
	return 0;
}

static int test_error_after_completed_prefix_at_segment_boundary(void)
{
	swapz_u8 committed = 0;
	swapz_u8 raw[SWAPZ_BLOCK_BYTES];
	unsigned int i;

	CHECK(setup() == 0);
	memset(raw, 0x83, sizeof(raw));
	/* Fill foreground segment0 to within 4 blocks, while preserving
	 * one existing valid logical mapping outside the 0..63 window. */
	for (i = 0; i < SWAPZ_SEGMENT_BLOCKS - 4; ++i) {
		struct swapz_tx tx;
		swapz_u32 page = 80;
		swapz_u8 complete = 0;

		CHECK(swapz_stage(&a, &page, 1, 1, &tx) == 0);
		CHECK(write_extent(NULL, tx.start_block, 1, raw,
				   &complete) == 0);
		CHECK(swapz_finish_raw(&a, &tx, raw, complete, 0) == 0);
	}
	CHECK(a.next_block == SWAPZ_SEGMENT_BLOCKS - 4);
	/* The last four block slots were intentionally left empty: the
	 * previous loop allocated 252 blocks. */
	CHECK(maps[80].valid && maps[80].raw);
	fail_on_run = 2;
	CHECK(swapz_engine_write_window_batched(&e, pages, 64,
					     &committed) == -EIO);
	CHECK(run_calls == 2 && committed > 0 && committed < 64);
	CHECK(!ownership_violation);
	CHECK(validate_prefix(committed) == 0);
	CHECK(maps[80].valid && maps[80].raw_crc32c ==
	      swapz_crc32c_bytes(raw, sizeof(raw)));
	return 0;
}


/*
 * Production mixed-window ABI: the target moves raw fallbacks after all
 * compressed entries, but retains the original BIO order in its index map.
 * Both formats share a run without sharing on-media representation.
 */
static void prepare_raw_tail(unsigned int compressed_count, unsigned int count)
{
	unsigned int i, j;

	for (i = compressed_count; i < count; ++i) {
		for (j = 0; j < SWAPZ_BLOCK_BYTES; ++j)
			raw_payloads[i][j] = (swapz_u8)(i * 13U + j);
		pages[i].raw = 1;
		pages[i].length = SWAPZ_BLOCK_BYTES;
		pages[i].payload = raw_payloads[i];
	}
}

static int validate_mixed_prefix(unsigned int count, unsigned int committed)
{
	unsigned int i;

	for (i = 0; i < count; ++i) {
		swapz_u8 output[SWAPZ_BLOCK_BYTES];
		swapz_u16 length = 0;

		CHECK((maps[i].valid != 0) == (i < committed));
		if (i >= committed)
			continue;
		CHECK(maps[i].raw == pages[i].raw);
		if (pages[i].raw) {
			CHECK(maps[i].extent_blocks == 1);
			CHECK(maps[i].payload_length == SWAPZ_BLOCK_BYTES);
			CHECK(read_blocks(NULL, maps[i].start_block, 1, output) == 0);
			CHECK(!memcmp(output, pages[i].payload, SWAPZ_BLOCK_BYTES));
			CHECK(swapz_verify_raw(&a, i, output) == 0);
		} else {
			CHECK(swapz_engine_read_page(&e, i, output, sizeof(output),
						   &length) == 0);
			CHECK(length == pages[i].length);
			CHECK(!memcmp(output, pages[i].payload, length));
		}
	}
	CHECK(!a.batch_pending && !a.in_flight);
	return 0;
}

static int test_mixed_and_raw_only_share_lower_runs(void)
{
	swapz_u8 committed = 0;

	CHECK(setup() == 0);
	prepare_raw_tail(48, 64);
	CHECK(swapz_engine_write_window_batched(&e, pages, 64,
					     &committed) == 0);
	CHECK(committed == 64);
	CHECK(run_calls < 16 && extent_calls == 0);
	CHECK(e.bulk_raw_entries == 16);
	CHECK(e.bulk_mixed_runs + e.bulk_raw_only_runs > 0);
	CHECK(!maps_visible_during_run && !ownership_violation);
	CHECK(e.bulk_padding_blocks == 0);
	CHECK(validate_mixed_prefix(64, 64) == 0);

	CHECK(setup() == 0);
	prepare_raw_tail(0, 64);
	committed = 0;
	CHECK(swapz_engine_write_window_batched(&e, pages, 64,
					     &committed) == 0);
	CHECK(committed == 64 && run_calls == 1 && extent_calls == 0);
	CHECK(e.bulk_raw_only_runs == 1 && !e.bulk_mixed_runs);
	CHECK(e.bulk_raw_entries == 64);
	CHECK(lower_written_bytes == 64ULL * SWAPZ_BLOCK_BYTES);
	CHECK(!maps_visible_during_run && !ownership_violation);
	CHECK(validate_mixed_prefix(64, 64) == 0);
	return 0;
}

/* Mixed bulk planning may relocate compressed extents while RAW mappings
 * retain their own CRC/type authority; physical start identity is not ABI. */
static int test_mixed_default_equal_bytes_vs_serial_raw_control(void)
{
	struct swapz_map combined[40];
	swapz_u8 committed = 0;
	unsigned int combined_calls, i;
	unsigned long long combined_bytes;

	CHECK(setup() == 0);
	prepare_raw_tail(24, 40);
	CHECK(swapz_engine_write_window_batched(&e, pages, 40,
					     &committed) == 0);
	CHECK(committed == 40 && e.bulk_padding_blocks == 0);
	CHECK(validate_mixed_prefix(40, 40) == 0);
	memcpy(combined, maps, sizeof(combined));
	combined_calls = run_calls;
	combined_bytes = lower_written_bytes;

	CHECK(setup() == 0);
	prepare_raw_tail(24, 40);
	e.bulk_enabled = 0;
	committed = 0;
	CHECK(swapz_engine_write_window_batched(&e, pages, 24,
					     &committed) == 0);
	CHECK(committed == 24);
	for (i = 24; i < 40; ++i) {
		struct swapz_tx transaction;
		swapz_u32 logical = i;
		swapz_u8 completed = 0;

		CHECK(swapz_stage(&a, &logical, 1, 1, &transaction) == 0);
		CHECK(write_extent(NULL, transaction.start_block, 1,
				   raw_payloads[i], &completed) == 0);
		CHECK(swapz_finish_raw(&a, &transaction, raw_payloads[i],
					     completed, 0) == 0);
	}
	CHECK(lower_written_bytes == combined_bytes);
	CHECK(run_calls == 0 && extent_calls > combined_calls);
	CHECK(validate_mixed_prefix(40, 40) == 0);
	for (i = 0; i < 40; ++i) {
		CHECK(maps[i].generation == combined[i].generation);
		CHECK(maps[i].raw == combined[i].raw);
		if (maps[i].raw) {
			CHECK(maps[i].raw_crc32c == combined[i].raw_crc32c);
		} else {
			CHECK(maps[i].payload_length ==
			      combined[i].payload_length);
			CHECK(swapz_map_encoding(&maps[i]) ==
			      swapz_map_encoding(&combined[i]));
		}
	}
	return 0;
}

static int test_mixed_lower_failures_quarantine_unpublished_raw(void)
{
	unsigned int failure_mode;

	/*
	 * The production dm_io WRITE adapter reports lower device failure as
	 * -EIO, with -EOPNOTSUPP retained from its separate unsupported bitmap.
	 * Keep short/partial shapes as engine hardening, but model -ENOSPC only
	 * at the authority-capacity or durability-flush production boundaries.
	 */
	for (failure_mode = 0; failure_mode < 4; ++failure_mode) {
		swapz_u8 committed = 77;
		int expected_error = failure_mode == 2 ? -EOPNOTSUPP : -EIO;

		CHECK(setup() == 0);
		prepare_raw_tail(8, 32);
		if (failure_mode == 0)
			fail_on_run = 1;
		else if (failure_mode == 1)
			short_on_run = 1;
		else if (failure_mode == 2)
			unsupported_on_run = 1;
		else
			partial_fail_on_run = 1;
		CHECK(swapz_engine_write_window_batched(&e, pages, 32,
						     &committed) == expected_error);
		CHECK(committed == 0);
		CHECK(run_calls == 1 && extent_calls == 0);
		CHECK(!maps_visible_during_run && !ownership_violation);
		CHECK(a.abandoned_blocks > 0);
		CHECK(validate_mixed_prefix(32, 0) == 0);
	}
	return 0;
}

static int test_mixed_failed_overwrite_preserves_old_generations(void)
{
	struct swapz_map previous[16];
	swapz_u8 committed = 0;
	unsigned int i, j;

	CHECK(setup() == 0);
	prepare_raw_tail(8, 16);
	CHECK(swapz_engine_write_window_batched(&e, pages, 16,
					     &committed) == 0);
	CHECK(committed == 16);
	memcpy(previous, maps, sizeof(previous));
	for (i = 0; i < 8; ++i)
		memset(payloads[i], 0xdc, pages[i].length);
	for (i = 8; i < 16; ++i)
		memset(raw_payloads[i], 0xeb, SWAPZ_BLOCK_BYTES);
	fail_on_run = run_calls + 1;
	committed = 55;
	CHECK(swapz_engine_write_window_batched(&e, pages, 16,
					     &committed) == -EIO);
	CHECK(committed == 0 && !a.batch_pending && !a.in_flight);
	CHECK(!maps_visible_during_run && !ownership_violation);
	for (i = 0; i < 16; ++i) {
		swapz_u8 output[SWAPZ_BLOCK_BYTES];
		swapz_u16 length = 0;

		CHECK(maps[i].valid);
		CHECK(maps[i].start_block == previous[i].start_block);
		CHECK(maps[i].generation == previous[i].generation);
		CHECK(maps[i].raw == previous[i].raw);
		if (maps[i].raw) {
			CHECK(maps[i].raw_crc32c == previous[i].raw_crc32c);
		} else {
			CHECK(maps[i].payload_offset == previous[i].payload_offset);
			CHECK(maps[i].payload_length == previous[i].payload_length);
			CHECK(swapz_map_encoding(&maps[i]) ==
			      swapz_map_encoding(&previous[i]));
		}
		if (i >= 8) {
			CHECK(read_blocks(NULL, maps[i].start_block, 1, output) == 0);
			CHECK(swapz_verify_raw(&a, i, output) == 0);
			for (j = 0; j < SWAPZ_BLOCK_BYTES; ++j)
				CHECK(output[j] == (swapz_u8)(i * 13U + j));
		} else {
			CHECK(swapz_engine_read_page(&e, i, output,
						   sizeof(output), &length) == 0);
			CHECK(length == pages[i].length);
			for (j = 0; j < length; ++j)
				CHECK(output[j] == (swapz_u8)(i + 1U));
		}
	}
	return 0;
}

static int test_mixed_later_run_failure_keeps_only_completed_prefix(void)
{
	swapz_u8 committed = 0, raw[SWAPZ_BLOCK_BYTES];
	unsigned int i;

	CHECK(setup() == 0);
	memset(raw, 0x92, sizeof(raw));
	/* Leave exactly four blocks in foreground segment zero. */
	for (i = 0; i < SWAPZ_SEGMENT_BLOCKS - 4; ++i) {
		struct swapz_tx transaction;
		swapz_u32 logical = 80;
		swapz_u8 completed = 0;

		CHECK(swapz_stage(&a, &logical, 1, 1, &transaction) == 0);
		CHECK(write_extent(NULL, transaction.start_block, 1, raw,
				   &completed) == 0);
		CHECK(swapz_finish_raw(&a, &transaction, raw, completed, 0) == 0);
	}
	prepare_raw_tail(0, 32);
	fail_on_run = 2;
	CHECK(swapz_engine_write_window_batched(&e, pages, 32,
					     &committed) == -EIO);
	CHECK(run_calls == 2 && committed == 4);
	CHECK(validate_mixed_prefix(32, 4) == 0);
	CHECK(maps[80].valid && maps[80].raw_crc32c ==
	      swapz_crc32c_bytes(raw, sizeof(raw)));
	return 0;
}

/*
 * A mapping may change representation on overwrite. Ensure publication
 * decrements the old extent's liveness and switches raw CRC authority
 * only after the complete replacement lower run.
 */
static int test_mixed_successful_cross_format_overwrite(void)
{
	swapz_u8 committed = 0;
	unsigned int i;

	CHECK(setup() == 0);
	prepare_raw_tail(8, 16);
	CHECK(swapz_engine_write_window_batched(&e, pages, 16,
					     &committed) == 0);
	CHECK(committed == 16 && validate_mixed_prefix(16, 16) == 0);

	/* Four formerly raw logical pages become compressed. */
	for (i = 0; i < 12; ++i) {
		memset(payloads[i], 0xc3, 1200);
		pages[i].payload = payloads[i];
		pages[i].length = 1200;
		pages[i].raw = 0;
	}
	prepare_raw_tail(12, 16);
	committed = 0;
	CHECK(swapz_engine_write_window_batched(&e, pages, 16,
					     &committed) == 0);
	CHECK(committed == 16 && validate_mixed_prefix(16, 16) == 0);
	for (i = 0; i < 16; ++i)
		CHECK(maps[i].generation == 2);

	/* Eight formerly compressed logical pages become raw. */
	prepare_raw_tail(4, 16);
	committed = 0;
	CHECK(swapz_engine_write_window_batched(&e, pages, 16,
					     &committed) == 0);
	CHECK(committed == 16 && validate_mixed_prefix(16, 16) == 0);
	for (i = 0; i < 16; ++i)
		CHECK(maps[i].generation == 3);
	CHECK(!maps_visible_during_run && !ownership_violation);
	return 0;
}

/*
 * Reproduce the 819-compressed / 205-raw DISTRIBUTION of the earlier
 * 1024-page benchmark across 16 independently reset 64-record windows.
 * This is a rootless source submission test, NOT that loaded IO fixture:
 * backing-block request merging and persistent segment churn remain
 * separate null_blk validation gates.
 */
static int test_mixed_819_205_distribution_economy(void)
{
	unsigned int window;
	unsigned int total_compressed = 0, total_raw = 0;
	unsigned int combined_calls = 0, serialized_calls = 0;

	for (window = 0; window < 16; ++window) {
		const unsigned int compressed_count = window < 13 ? 51 : 52;
		swapz_u8 committed = 0;
		unsigned int i;
		unsigned long long combined_bytes;

		CHECK(setup() == 0);
		prepare_raw_tail(compressed_count, 64);
		CHECK(swapz_engine_write_window_batched(&e, pages, 64,
						     &committed) == 0);
		CHECK(committed == 64);
		CHECK(e.bulk_raw_entries == 64 - compressed_count);
		CHECK(validate_mixed_prefix(64, 64) == 0);
		CHECK(!e.bulk_padding_blocks && !maps_visible_during_run);
		combined_bytes = lower_written_bytes;
		combined_calls += run_calls;
		total_compressed += compressed_count;
		total_raw += 64 - compressed_count;

		CHECK(setup() == 0);
		prepare_raw_tail(compressed_count, 64);
		e.bulk_enabled = 0;
		committed = 0;
		CHECK(swapz_engine_write_window_batched(&e, pages,
						     compressed_count, &committed) == 0);
		CHECK(committed == compressed_count);
		for (i = compressed_count; i < 64; ++i) {
			struct swapz_tx transaction;
			swapz_u32 logical = i;
			swapz_u8 completed = 0;

			CHECK(swapz_stage(&a, &logical, 1, 1,
						&transaction) == 0);
			CHECK(write_extent(NULL, transaction.start_block, 1,
					   raw_payloads[i], &completed) == 0);
			CHECK(swapz_finish_raw(&a, &transaction,
					     raw_payloads[i], completed, 0) == 0);
		}
		CHECK(lower_written_bytes == combined_bytes);
		serialized_calls += extent_calls;
		CHECK(validate_mixed_prefix(64, 64) == 0);
	}
	CHECK(total_compressed == 819 && total_raw == 205);
	CHECK(combined_calls < 205 && combined_calls < serialized_calls);
	return 0;
}

/*
 * The 819/205 loaded fixture compresses its 819 pages to just ~57 bytes.
 * This test instead exercises the actual production C engine with 1-3KiB+
 * compressed records and 25% raw pages, including SWZ 4/8/16KiB extents.
 * Request-call savings are not backing queue request counts.
 */
static int test_mixed_realistic_payloads_keep_zero_padding(void)
{
	const unsigned int compressed = 48, total = 64;
	unsigned int i, combined_calls;
	unsigned long long combined_bytes;
	swapz_u8 committed = 0;

	CHECK(setup() == 0);
	prepare_raw_tail(compressed, total);
	for (i = 0; i < compressed; ++i) {
		swapz_u16 bytes = i % 3 == 0 ? 3500 : i % 3 == 1 ? 2089 : 1032;

		memset(payloads[i], (int)(i + 1U), bytes);
		pages[i].length = bytes;
	}
	CHECK(swapz_engine_write_window_batched(&e, pages, total,
					     &committed) == 0);
	CHECK(committed == total && e.bulk_padding_blocks == 0);
	CHECK(e.bulk_raw_entries == total - compressed);
	CHECK(!maps_visible_during_run && !ownership_violation);
	CHECK(validate_mixed_prefix(total, total) == 0);
	combined_calls = run_calls;
	combined_bytes = lower_written_bytes;

	/* Exact same source pages with compressed-only planner plus raw
	 * serialized control must transfer identical bytes, even with
	 * alignment gaps. Bulk mode 1 cannot secretly write padding. */
	CHECK(setup() == 0);
	prepare_raw_tail(compressed, total);
	for (i = 0; i < compressed; ++i) {
		swapz_u16 bytes = i % 3 == 0 ? 3500 : i % 3 == 1 ? 2089 : 1032;

		memset(payloads[i], (int)(i + 1U), bytes);
		pages[i].length = bytes;
	}
	e.bulk_enabled = 0;
	committed = 0;
	CHECK(swapz_engine_write_window_batched(&e, pages, compressed,
					     &committed) == 0);
	CHECK(committed == compressed);
	for (i = compressed; i < total; ++i) {
		struct swapz_tx tx;
		swapz_u8 done = 0;
		swapz_u32 logical = i;

		CHECK(swapz_stage(&a, &logical, 1, 1, &tx) == 0);
		CHECK(write_extent(NULL, tx.start_block, 1,
				   raw_payloads[i], &done) == 0);
		CHECK(swapz_finish_raw(&a, &tx, raw_payloads[i], done, 0) == 0);
	}
	CHECK(lower_written_bytes == combined_bytes);
	CHECK(extent_calls > combined_calls);
	CHECK(validate_mixed_prefix(total, total) == 0);
	return 0;
}

static int test_explicit_read_cap_keeps_bulk_run_and_avoids_4block_extents(void)
{
	unsigned long long unbounded_bytes;
	unsigned int i, unbounded_calls;
	swapz_u8 committed = 0;
	int saw_four = 0;

	CHECK(setup() == 0);
	for (i = 0; i < 16; ++i) {
		pages[i].length = 2072;
		memset(payloads[i], (int)i + 31, pages[i].length);
	}
	CHECK(swapz_engine_write_window_batched(&e, pages, 16, &committed) == 0);
	CHECK(committed == 16);
	for (i = 0; i < 16; ++i)
		if (maps[i].extent_blocks == 4)
			saw_four = 1;
	CHECK(saw_four);
	unbounded_bytes = lower_written_bytes;
	unbounded_calls = run_calls;
	CHECK(unbounded_bytes == 10ULL * SWAPZ_BLOCK_BYTES);
	CHECK(validate_prefix(16) == 0);

	CHECK(setup() == 0);
	for (i = 0; i < 16; ++i) {
		pages[i].length = 2072;
		memset(payloads[i], (int)i + 31, pages[i].length);
	}
	committed = 0;
	CHECK(swapz_engine_write_window_batched_read_cap(&e, pages, 16,
						      &committed, 2) == 0);
	CHECK(committed == 16);
	for (i = 0; i < 16; ++i)
		CHECK(maps[i].extent_blocks <= 2);
	CHECK(lower_written_bytes == 11ULL * SWAPZ_BLOCK_BYTES);
	CHECK(!e.bulk_padding_blocks);
	CHECK(run_calls < e.bulk_extents);
	CHECK(run_calls <= unbounded_calls + 1);
	CHECK(validate_prefix(16) == 0);

	CHECK(setup() == 0);
	committed = 55;
	CHECK(swapz_engine_write_window_batched_read_cap(&e, pages, 16,
						      &committed, 4) == -EINVAL);
	CHECK(committed == 55);
	CHECK(!run_calls && !extent_calls && !a.in_flight && !a.batch_pending);
	return 0;
}

static int test_malformed_mixed_input_fails_before_staging(void)
{
	swapz_u8 committed = 44;

	CHECK(setup() == 0);
	prepare_raw_tail(1, 2);
	pages[1].length = SWAPZ_BLOCK_BYTES - 1;
	CHECK(swapz_engine_write_window_batched(&e, pages, 2,
					     &committed) == -EINVAL);
	CHECK(committed == 0 && !a.batch_pending && !a.in_flight);
	CHECK(!run_calls && !extent_calls);
	CHECK(setup() == 0);
	prepare_raw_tail(1, 3);
	pages[1].logical_page = pages[0].logical_page;
	/* Duplicate compressed/raw logical identities cannot be replayed
	 * safely inside one deferred group. */
	CHECK(swapz_engine_write_window_batched(&e, pages, 3,
					     &committed) == -EEXIST);
	CHECK(!run_calls && !extent_calls);
	CHECK(setup() == 0);
	prepare_raw_tail(0, 2);
	e.bulk_enabled = 0;
	CHECK(swapz_engine_write_window_batched(&e, pages, 2,
					     &committed) == -EOPNOTSUPP);
	CHECK(!run_calls && !extent_calls);
	return 0;
}

static int test_planned_write_preserves_nonoverlap_read_residency(void)
{
	swapz_u8 output[SWAPZ_MAX_COMPRESSED];
	swapz_u16 length = 0;
	swapz_u8 committed = 0;
	unsigned int reads_after_first;

	CHECK(setup() == 0);
	/* count==1 deliberately exercises swapz_engine_write_window_planned(). */
	CHECK(swapz_engine_write_window_batched(&e, pages, 1, &committed) == 0);
	CHECK(committed == 1 && extent_calls == 1 && run_calls == 0);
	CHECK(swapz_engine_read_page(&e, 0, output, sizeof(output), &length) == 0);
	CHECK(length == pages[0].length);
	CHECK(!memcmp(output, payloads[0], length));
	reads_after_first = read_calls;
	CHECK(reads_after_first > 0);

	/* A second one-record append mutates a disjoint physical range. It must
	 * not evict page 0's validated direct/shared residency. */
	committed = 0;
	CHECK(swapz_engine_write_window_batched(&e, pages + 1, 1,
					     &committed) == 0);
	CHECK(committed == 1 && extent_calls == 2 && run_calls == 0);
	CHECK(swapz_engine_read_page(&e, 0, output, sizeof(output), &length) == 0);
	CHECK(length == pages[0].length);
	CHECK(!memcmp(output, payloads[0], length));
	CHECK(read_calls == reads_after_first);
	return 0;
}

static int test_immutable_run_prepare_then_complete(void)
{
	struct swapz_io_run run = {
		.bytes = bulk,
		.txs = bulk_txs,
	};
	swapz_u8 total = 0;
	unsigned int i;

	CHECK(setup() == 0);
	while (total < 16) {
		swapz_u8 prepared = 0, committed = 0;
		swapz_u16 completed = 0;

		CHECK(swapz_engine_prepare_batched_run(&e, pages + total,
						       16 - total, &run,
						       &prepared, 0) == 0);
		CHECK(prepared > 0 && prepared <= 16 - total);
		CHECK(run.page_count == prepared && run.extent_count > 0 &&
		      run.blocks > 0 && run.blocks <= SWAPZ_BULK_BLOCKS);
		CHECK(a.batch_pending == run.extent_count && !a.in_flight);
		for (i = total; i < total + prepared; ++i)
			CHECK(!maps[i].valid);
		/* Prepared bytes and transactions are the sole publication source.
		 * Mutating their original compressed inputs after freeze must not
		 * affect this immutable lower run. Later prefixes use untouched
		 * input pages. */
		for (i = total; i < total + prepared; ++i)
			memset(payloads[i], 0xee, pages[i].length);
		CHECK(write_run(NULL, run.start_block, run.blocks,
				run.bytes, &completed) == 0);
		CHECK(completed == run.blocks);
		CHECK(swapz_engine_complete_batched_run(&e, &run, completed, 0,
							 &committed) == 0);
		CHECK(committed == prepared && !a.batch_pending && !a.in_flight);
		total += committed;
	}
	CHECK(total == 16);
	for (i = 0; i < total; ++i)
		CHECK(maps[i].valid && maps[i].generation == 1);
	return 0;
}

static int test_immutable_run_failure_quarantines_all(void)
{
	struct swapz_io_run run = {
		.bytes = bulk,
		.txs = bulk_txs,
	};
	swapz_u8 prepared = 0, committed = 99;
	unsigned int i;

	CHECK(setup() == 0);
	CHECK(swapz_engine_prepare_batched_run(&e, pages, 16, &run,
					       &prepared, 0) == 0);
	CHECK(prepared > 0 && prepared <= 16 && a.batch_pending);
	CHECK(swapz_engine_complete_batched_run(&e, &run, 0, -EIO,
						 &committed) == -EIO);
	CHECK(committed == 0 && !a.batch_pending && !a.in_flight);
	for (i = 0; i < prepared; ++i)
		CHECK(!maps[i].valid);
	CHECK(a.abandoned_blocks > 0);
	return 0;
}


/*
 * The extra test pin keeps the immutable run alive through a deliberately
 * repeated completion delivery. It does not model a second legitimate dm_io
 * callback: the loaded callback-once and BIO lifetime contract is separate.
 */
struct synthetic_lower_write_owner {
	unsigned int accepted_writes;
	unsigned int references;
	unsigned int upper_final_completions;
	unsigned int upper_success_completions;
	int original_lower_errno;
};

static int check_lower_completion_phase(const char *scenario, const char *phase,
					int condition,
					const struct synthetic_lower_write_owner *owner,
					unsigned int expected_references,
					unsigned int expected_final_completions,
					unsigned int expected_publications,
					unsigned long long expected_lower_bytes,
					unsigned int expected_pending,
					unsigned int expected_visible)
{
	unsigned long long observed_lower_bytes =
		(unsigned long long)e.completed_blocks * SWAPZ_BLOCK_BYTES;
	unsigned int visible = 0, index;

	for (index = 0; index < owner->accepted_writes; ++index)
		visible += maps[index].valid != 0;
	if (condition && owner->references == expected_references &&
	    owner->upper_final_completions == expected_final_completions &&
	    published_calls == expected_publications &&
	    observed_lower_bytes == expected_lower_bytes &&
	    a.batch_pending == expected_pending && visible == expected_visible)
		return 0;
	fprintf(stderr,
		"FAIL: lower-write-aggregation scenario=%s phase=%s condition=%d "
		"owner_expected=%u owner_observed=%u accepted=%u "
		"final_expected=%u final_observed=%u success_observed=%u "
		"publication_expected=%u publication_observed=%u "
		"lower_bytes_expected=%llu lower_bytes_observed=%llu "
		"pending_expected=%u pending_observed=%u "
		"visible_expected=%u visible_observed=%u original_lower_errno=%d\n",
		scenario, phase, condition, expected_references, owner->references,
		owner->accepted_writes, expected_final_completions,
		owner->upper_final_completions, owner->upper_success_completions,
		expected_publications, published_calls, expected_lower_bytes,
		observed_lower_bytes, expected_pending, a.batch_pending,
		expected_visible, visible, owner->original_lower_errno);
	return 1;
}

static int test_duplicate_lower_completion_accounted_once(void)
{
	static const struct {
		const char *name;
		int lower_errno;
		int completion_errno;
		unsigned int mode;
	} scenarios[] = {
		{ "full-then-duplicate", 0, 0, 0 },
		{ "zero-eio-then-duplicate", -EIO, -EIO, 1 },
		{ "partial-eio-then-duplicate", -EIO, -EIO, 2 },
		{ "short-success-then-duplicate", 0, -EIO, 3 },
		{ "unsupported-then-duplicate", -EOPNOTSUPP, -EOPNOTSUPP, 4 },
		{ "overcomplete-eio-then-duplicate", -EIO, -EIO, 5 },
	};
	unsigned int scenario;

	for (scenario = 0; scenario < sizeof(scenarios) / sizeof(scenarios[0]);
	     ++scenario) {
		struct swapz_io_run run = { .bytes = bulk, .txs = bulk_txs };
		struct synthetic_lower_write_owner owner = {};
		struct swapz_tx next_transaction;
		swapz_u8 prepared = 0, published = 99, duplicate_published = 99;
		swapz_u16 completed = 0;
		swapz_u32 next_logical_page = 100;
		swapz_u32 saved_abandoned, saved_committed, saved_next;
		swapz_u32 run_end;
		unsigned int expected_visible, expected_publications;
		unsigned long long completed_bytes;
		int error, lower_error, duplicate_error;

		error = setup();
		if (check_lower_completion_phase(scenarios[scenario].name, "setup",
				error == 0, &owner, 0, 0, 0, 0, 0, 0))
			return 1;
		error = swapz_engine_prepare_batched_run(&e, pages, 16, &run,
							 &prepared, 0);
		owner.accepted_writes = prepared;
		/* Ordered owner, lower request and test-only lifetime pin. */
		owner.references = 3;
		run_end = run.start_block + run.blocks;
		if (check_lower_completion_phase(scenarios[scenario].name, "prepared",
				error == 0 && prepared && prepared <= 16 &&
				run.blocks && run.extent_count &&
				run_end <= PHYSICAL && !a.in_flight,
				&owner, 3, 0, 0, 0, run.extent_count, 0))
			return 1;

		/* A delayed lower completion cannot publish or release the extent. */
		error = swapz_stage(&a, &next_logical_page, 1, 1,
				    &next_transaction);
		if (check_lower_completion_phase(scenarios[scenario].name, "delayed",
				error == -EBUSY && a.next_block >= run_end,
				&owner, 3, 0, 0, 0, run.extent_count, 0))
			return 1;

		if (scenarios[scenario].mode == 1)
			fail_on_run = 1;
		else if (scenarios[scenario].mode == 2)
			partial_fail_on_run = 1;
		else if (scenarios[scenario].mode == 3)
			short_on_run = 1;
		else if (scenarios[scenario].mode == 4)
			unsupported_on_run = 1;
		else if (scenarios[scenario].mode == 5)
			overcomplete_fail_on_run = 1;
		write_sealed(NULL, prepared);
		lower_error = write_run(NULL, run.start_block, run.blocks,
					run.bytes, &completed);
		owner.original_lower_errno = lower_error;
		/* Only the lower request's reference is released at notification. */
		owner.references--;
		completed_bytes = completed <= run.blocks ?
			(unsigned long long)completed * SWAPZ_BLOCK_BYTES : 0;
		if (check_lower_completion_phase(scenarios[scenario].name,
				"lower-notified",
				lower_error == scenarios[scenario].lower_errno &&
				((scenarios[scenario].mode == 5 &&
				  completed > run.blocks) ||
				 (scenarios[scenario].mode != 5 &&
				  completed <= run.blocks)) && run_calls == 1 &&
				!maps_visible_during_run && !ownership_violation &&
				!sealed_missing_before_lower,
				&owner, 2, 0, 0, 0, run.extent_count, 0))
			return 1;

		error = swapz_engine_complete_batched_run(&e, &run, completed,
							  lower_error, &published);
		expected_visible = scenarios[scenario].mode == 0 ? prepared : 0;
		expected_publications = scenarios[scenario].mode == 0 ? 1 : 0;
		if (!error && published == prepared) {
			write_published(NULL, published);
			owner.upper_success_completions = published;
		}
		/* The ordered owner completes every accepted upper request once. */
		owner.upper_final_completions = prepared;
		owner.references--;
		saved_abandoned = a.abandoned_blocks;
		saved_committed = a.committed_blocks;
		saved_next = a.next_block;
		if (check_lower_completion_phase(scenarios[scenario].name,
				"first-finalization",
				error == scenarios[scenario].completion_errno &&
				published == expected_visible && !a.in_flight &&
				!a.batch_replaying && !publication_visibility_errors &&
				(expected_visible || saved_abandoned > 0) &&
				owner.upper_success_completions == expected_visible,
				&owner, 1, prepared, expected_publications,
				completed_bytes, 0, expected_visible))
			return 1;

		/*
		 * Deliberately deliver the old completion a second time while the
		 * test pin still owns its storage. It cannot re-credit completed
		 * lower bytes, republish or change the first upper completion.
		 */
		duplicate_error = swapz_engine_complete_batched_run(
			&e, &run, completed, lower_error, &duplicate_published);
		if (check_lower_completion_phase(scenarios[scenario].name,
				"duplicate-finalization",
				duplicate_error == (lower_error ?
						   lower_error : -ESTALE) &&
				duplicate_published == 0 &&
				a.abandoned_blocks == saved_abandoned &&
				a.committed_blocks == saved_committed &&
				a.next_block == saved_next && !a.in_flight,
				&owner, 1, prepared, expected_publications,
				completed_bytes, 0, expected_visible))
			return 1;

		/* A new reservation must not reuse a possibly torn old run. */
		error = swapz_stage(&a, &next_logical_page, 1, 1,
				    &next_transaction);
		if (check_lower_completion_phase(scenarios[scenario].name,
				"new-reservation",
				error == 0 && next_transaction.start_block >= run_end &&
				a.next_block >= saved_next,
				&owner, 1, prepared, expected_publications,
				completed_bytes, 0, expected_visible))
			return 1;
		error = swapz_abort(&a, &next_transaction);
		owner.references--; /* Drop the test pin only after stale replay. */
		if (check_lower_completion_phase(scenarios[scenario].name,
				"owner-released", error == 0,
				&owner, 0, prepared, expected_publications,
				completed_bytes, 0, expected_visible))
			return 1;
	}
	return 0;
}


static int test_overcomplete_failed_wrapper_preserves_lower_errno(void)
{
	swapz_u8 committed = 99;
	unsigned int index;

	CHECK(setup() == 0);
	overcomplete_fail_on_run = 1;
	CHECK(swapz_engine_write_window_batched(&e, pages, 16,
					     &committed) == -EIO);
	CHECK(committed == 0 && run_calls == 1 && e.completed_blocks == 0);
	CHECK(!published_calls && !a.batch_pending && !a.in_flight);
	CHECK(a.abandoned_blocks > 0);
	for (index = 0; index < 16; ++index)
		CHECK(!maps[index].valid);
	return 0;
}


/* A delivered predecessor must not consume a younger still-paused run. */
static int test_stale_lower_completion_keeps_successor_reserved(void)
{
	static struct swapz_tx successor_txs[SWAPZ_MAX_RECORDS];
	struct swapz_io_run first = { .bytes = bulk, .txs = bulk_txs };
	struct swapz_io_run second = {
		.bytes = (swapz_u8 *)raw_payloads,
		.txs = successor_txs,
	};
	struct synthetic_lower_write_owner owner = {};
	swapz_u8 first_prepared = 0, second_prepared = 0;
	swapz_u8 first_published = 0, duplicate_published = 99;
	swapz_u16 first_completed = 0;
	swapz_u32 previous_next, previous_abandoned;
	swapz_u8 successor_pending;
	unsigned long long first_lower_bytes;
	int error;

	error = setup();
	if (check_lower_completion_phase("stale-predecessor", "setup",
			error == 0, &owner, 0, 0, 0, 0, 0, 0))
		return 1;
	error = swapz_engine_prepare_batched_run(&e, pages, 8, &first,
						 &first_prepared, 0);
	owner.accepted_writes = first_prepared;
	owner.references = 3;
	if (check_lower_completion_phase("stale-predecessor", "first-prepared",
			error == 0 && first_prepared && first.extent_count &&
			first.blocks, &owner, 3, 0, 0, 0,
			first.extent_count, 0))
		return 1;
	write_sealed(NULL, first_prepared);
	error = write_run(NULL, first.start_block, first.blocks,
			  first.bytes, &first_completed);
	owner.references--;
	if (check_lower_completion_phase("stale-predecessor", "first-lower",
			error == 0 && first_completed == first.blocks,
			&owner, 2, 0, 0, 0, first.extent_count, 0))
		return 1;
	error = swapz_engine_complete_batched_run(&e, &first, first_completed,
						  0, &first_published);
	if (!error && first_published == first_prepared)
		write_published(NULL, first_published);
	owner.upper_final_completions = first_prepared;
	owner.upper_success_completions = first_published;
	owner.references--;
	first_lower_bytes = (unsigned long long)first_completed *
			    SWAPZ_BLOCK_BYTES;
	if (check_lower_completion_phase("stale-predecessor", "first-finalized",
			error == 0 && first_published == first_prepared,
			&owner, 1, first_prepared, 1, first_lower_bytes,
			0, first_prepared))
		return 1;

	/* The next immutable run uses disjoint, still-live backing buffers. */
	error = swapz_engine_prepare_batched_run(&e, pages + 8, 8, &second,
						 &second_prepared, 0);
	successor_pending = a.batch_pending;
	previous_next = a.next_block;
	previous_abandoned = a.abandoned_blocks;
	if (check_lower_completion_phase("stale-predecessor", "successor-paused",
			error == 0 && second_prepared &&
			successor_pending == second.extent_count &&
			second.txs[0].sequence != first.txs[0].sequence,
			&owner, 1, first_prepared, 1, first_lower_bytes,
			successor_pending, first_prepared))
		return 1;

	error = swapz_engine_complete_batched_run(
		&e, &first, first_completed, 0, &duplicate_published);
	if (check_lower_completion_phase("stale-predecessor", "old-callback",
			error == -ESTALE && duplicate_published == 0 &&
			a.next_block == previous_next &&
			a.abandoned_blocks == previous_abandoned,
			&owner, 1, first_prepared, 1, first_lower_bytes,
			successor_pending, first_prepared))
		return 1;

	/* The successor was never submitted: tail cancellation owns its cleanup. */
	error = swapz_engine_abort_batched_run_tail(&e, &second);
	owner.references--;
	if (check_lower_completion_phase("stale-predecessor", "tail-cancelled",
			error == 0 && a.abandoned_blocks > previous_abandoned,
			&owner, 0, first_prepared, 1, first_lower_bytes,
			0, first_prepared))
		return 1;
	return 0;
}


/*
 * The oldest sequence alone does not authenticate every paused snapshot.
 * Keep the predecessor's test-only reference until after a repeated engine
 * finalizer; this is NOT a second real dm_io callback or a post-release access.
 */
static int check_damaged_snapshot_phase(
				   const char *phase, int condition,
				   const struct swapz_io_run *predecessor,
				   const struct swapz_io_run *successor,
				   const struct synthetic_lower_write_owner *owner,
				   swapz_u16 reported_blocks,
				   swapz_u32 expected_credited_blocks,
				   swapz_u32 expected_oldest_sequence,
				   swapz_u8 expected_pending,
				   unsigned int expected_references,
				   unsigned int expected_final_completions,
				   int expected_errno, int observed_errno)
{
	unsigned int visible = 0, changed_generations = 0;
	unsigned int index;

	for (index = 0; index < 24; ++index) {
		visible += maps[index].valid != 0;
		changed_generations += maps[index].generation != 0;
	}
	if (condition && observed_errno == expected_errno &&
	    e.completed_blocks == expected_credited_blocks &&
	    a.batch_first_sequence == expected_oldest_sequence &&
	    a.batch_pending == expected_pending &&
	    owner->references == expected_references &&
	    owner->upper_final_completions == expected_final_completions &&
	    !owner->upper_success_completions && !published_calls &&
	    !visible && !changed_generations && !e.bulk_writes &&
	    !e.bulk_extents)
		return 0;

	fprintf(stderr,
		"FAIL: lower-write-aggregation scenario=damaged-snapshot "
		"phase=%s condition=%d predecessor_sequence=%u "
		"successor_sequence=%u oldest_sequence_expected=%u "
		"oldest_sequence_observed=%u predecessor_blocks=%u "
		"successor_blocks=%u reported_blocks=%u "
		"credited_blocks_expected=%u credited_blocks_observed=%u "
		"pending_expected=%u pending_observed=%u "
		"references_expected=%u references_observed=%u "
		"upper_accepted=%u upper_final_expected=%u "
		"upper_final_observed=%u upper_success_observed=%u "
		"publication_observed=%u generation_expected=0 "
		"predecessor_generation_observed=%u successor_generation_observed=%u "
		"changed_generations_observed=%u visible_observed=%u "
		"bulk_writes_observed=%u bulk_extents_observed=%u "
		"errno_expected=%d errno_observed=%d original_lower_errno=%d\n",
		phase, condition, predecessor->txs[0].sequence,
		successor->txs[0].sequence, expected_oldest_sequence,
		a.batch_first_sequence, predecessor->blocks, successor->blocks,
		reported_blocks, expected_credited_blocks, e.completed_blocks,
		expected_pending, a.batch_pending, expected_references,
		owner->references, owner->accepted_writes,
		expected_final_completions, owner->upper_final_completions,
		owner->upper_success_completions, published_calls,
		maps[0].generation, maps[16].generation,
		changed_generations, visible, e.bulk_writes, e.bulk_extents,
		expected_errno, observed_errno, owner->original_lower_errno);
	return 1;
}

static int test_damaged_nonoldest_snapshot_preserves_lower_ownership(void)
{
	static struct swapz_tx successor_transactions[SWAPZ_MAX_RECORDS];
	struct swapz_io_run predecessor = { .bytes = bulk, .txs = bulk_txs };
	struct swapz_io_run successor = {
		.bytes = (swapz_u8 *)raw_payloads,
		.txs = successor_transactions,
	};
	struct synthetic_lower_write_owner owner = {};
	struct swapz_tx next_transaction;
	swapz_u8 predecessor_prepared = 0, successor_prepared = 0;
	swapz_u8 published = 99, repeated_published = 99;
	swapz_u16 reported_blocks = 0;
	swapz_u32 saved_next_block, saved_abandoned;
	swapz_u32 saved_generation, first_sequence;
	swapz_u32 next_logical_page = 100;
	unsigned int index;
	int error, lower_error;

	error = setup();
	if (error) {
		fprintf(stderr, "FAIL: lower-write-aggregation "
			"scenario=damaged-snapshot phase=setup errno_expected=0 "
			"errno_observed=%d\n", error);
		return 1;
	}
	error = swapz_engine_prepare_batched_run(
		&e, pages, 16, &predecessor, &predecessor_prepared, 0);
	owner.accepted_writes = predecessor_prepared;
	owner.references = 3; /* Upper owner, lower notification, test-only pin. */
	first_sequence = predecessor.txs[0].sequence;
	if (check_damaged_snapshot_phase("predecessor-paused",
			error == 0 && predecessor_prepared &&
			predecessor.extent_count >= 2 && predecessor.blocks > 1 &&
			!a.in_flight, &predecessor, &successor, &owner, 0, 0,
			first_sequence, predecessor.extent_count, 3, 0, 0, error))
		return 1;

	partial_fail_on_run = 1;
	write_sealed(NULL, predecessor_prepared);
	lower_error = write_run(NULL, predecessor.start_block,
				predecessor.blocks, predecessor.bytes,
				&reported_blocks);
	owner.original_lower_errno = lower_error;
	owner.references--; /* The sole real lower notification has returned. */
	if (check_damaged_snapshot_phase("lower-notified",
			lower_error == -EIO && reported_blocks > 0 &&
			reported_blocks < predecessor.blocks && run_calls == 1 &&
			lower_written_bytes ==
				(unsigned long long)reported_blocks * SWAPZ_BLOCK_BYTES &&
			!maps_visible_during_run && !ownership_violation &&
			!sealed_missing_before_lower,
			&predecessor, &successor, &owner, reported_blocks, 0,
			first_sequence, predecessor.extent_count, 2, 0,
			-EIO, lower_error))
		return 1;

	/* The lower result is pending ordered publication, not buffer reuse.
	 * A successor stages disjoint bytes while sharing paused authority. */
	error = swapz_engine_prepare_batched_run(
		&e, pages + 16, 8, &successor, &successor_prepared, 0);
	owner.accepted_writes += successor_prepared;
	owner.references++; /* Unsubmitted successor's accepted upper owner. */
	saved_next_block = a.next_block;
	saved_abandoned = a.abandoned_blocks;
	if (check_damaged_snapshot_phase("successor-paused",
			error == 0 && successor_prepared && successor.extent_count &&
			successor.start_block >=
				predecessor.start_block + predecessor.blocks &&
			successor.txs[0].sequence ==
				predecessor.txs[predecessor.extent_count - 1U].sequence + 1U &&
			a.batch_consumed == 0,
			&predecessor, &successor, &owner, reported_blocks, 0,
			first_sequence,
			predecessor.extent_count + successor.extent_count,
			3, 0, 0, error))
		return 1;

	/* Leave the oldest sequence and its CRC valid; corrupt only its follower. */
	saved_generation = predecessor.txs[1].records[0].generation;
	predecessor.txs[1].records[0].generation++;
	if (check_damaged_snapshot_phase("snapshot-damaged",
			predecessor.txs[0].sequence == a.batch_first_sequence &&
			predecessor.txs[1].records[0].generation != saved_generation,
			&predecessor, &successor, &owner, reported_blocks, 0,
			first_sequence,
			predecessor.extent_count + successor.extent_count,
			3, 0, 0, 0))
		return 1;

	error = swapz_engine_complete_batched_run(
		&e, &predecessor, reported_blocks, lower_error, &published);
	owner.upper_final_completions += predecessor_prepared;
	owner.references--; /* Predecessor upper owner finishes once with EIO. */
	if (check_damaged_snapshot_phase("failed-finalization",
			error == lower_error && published == 0 &&
			!a.in_flight && !a.batch_replaying &&
			a.batch_consumed == 1 && a.next_block == saved_next_block &&
			a.abandoned_blocks ==
				saved_abandoned + predecessor.txs[0].extent_blocks,
			&predecessor, &successor, &owner, reported_blocks, 0,
			predecessor.txs[1].sequence,
			predecessor.extent_count + successor.extent_count - 1U,
			2, predecessor_prepared, -EIO, error))
		return 1;

	/* The synthetic repeat is legal ONLY because the test pin remains. */
	error = swapz_engine_complete_batched_run(
		&e, &predecessor, reported_blocks, lower_error,
		&repeated_published);
	if (check_damaged_snapshot_phase("pinned-duplicate",
			error == lower_error && repeated_published == 0 &&
			a.next_block == saved_next_block &&
			a.abandoned_blocks ==
				saved_abandoned + predecessor.txs[0].extent_blocks,
			&predecessor, &successor, &owner, reported_blocks, 0,
			predecessor.txs[1].sequence,
			predecessor.extent_count + successor.extent_count - 1U,
			2, predecessor_prepared, -EIO, error))
		return 1;

	/* Controlled fixture cleanup restores the exact staged identity.
	 * No failed completion may consume or release the successor's reserve. */
	predecessor.txs[1].records[0].generation = saved_generation;
	for (index = 1; index < predecessor.extent_count; ++index) {
		error = swapz_batch_resume(&a, &predecessor.txs[index]);
		if (!error)
			error = swapz_abort(&a, &a.active_tx);
		if (error)
			return check_damaged_snapshot_phase("drain-predecessor", 0,
				&predecessor, &successor, &owner, reported_blocks,
				0, a.batch_first_sequence, a.batch_pending,
				2, predecessor_prepared, 0, error);
	}
	for (index = 0; index < successor.extent_count; ++index) {
		error = swapz_batch_resume(&a, &successor.txs[index]);
		if (!error)
			error = swapz_abort(&a, &a.active_tx);
		if (error)
			return check_damaged_snapshot_phase("drain-successor", 0,
				&predecessor, &successor, &owner, reported_blocks,
				0, a.batch_first_sequence, a.batch_pending,
				2, predecessor_prepared, 0, error);
	}
	owner.upper_final_completions += successor_prepared;
	owner.references--; /* Successor upper owner is now complete. */
	owner.references--; /* The pinned predecessor is finally released. */
	error = swapz_stage(&a, &next_logical_page, 1, 1, &next_transaction);
	if (check_damaged_snapshot_phase("new-reservation",
			error == 0 && next_transaction.start_block >= saved_next_block &&
			next_transaction.start_block >=
				successor.start_block + successor.blocks &&
			a.abandoned_blocks > saved_abandoned &&
			!a.batch_pending && !a.batch_replaying,
			&predecessor, &successor, &owner, reported_blocks, 0,
			a.batch_first_sequence, 0, 0, owner.accepted_writes, 0, error))
		return 1;
	error = swapz_abort(&a, &next_transaction);
	if (check_damaged_snapshot_phase("reservation-released",
			error == 0 && !a.in_flight && !a.batch_pending,
			&predecessor, &successor, &owner, reported_blocks, 0,
			a.batch_first_sequence, 0, 0, owner.accepted_writes, 0, error))
		return 1;
	return 0;
}


/*
 * A full, CRC-valid physical lower run must not permit its first mapping to
 * publish just because the oldest sequence matches. This uses the real
 * prepare/write/complete C path and a test-only lifetime pin, not another
 * legitimate dm_io notification or a second ordered publisher.
 */
static int test_full_lower_success_authenticates_entire_run_before_publish(void)
{
	static const char *const scenarios[] = {
		"nonoldest-generation", "oldest-sequence",
		"nonoldest-offset", "intact-control",
	};
	unsigned int scenario;

	for (scenario = 0; scenario < sizeof(scenarios) /
	     sizeof(scenarios[0]); ++scenario) {
		struct swapz_io_run run = { .bytes = bulk, .txs = bulk_txs };
		struct synthetic_lower_write_owner owner = {};
		swapz_u8 initial_committed = 0, prepared = 0;
		swapz_u8 committed = 99, repeated_committed = 99;
		swapz_u16 lower_completed = 0;
		swapz_u32 credited_before, next_before;
		swapz_u32 abandoned_before, committed_before;
		swapz_u8 pending_before;
		unsigned long long physical_before;
		unsigned int publications_before, index;
		int error, lower_error, repeated_error;
		int valid_control = scenario == 3;

		CHECK(setup() == 0);
		CHECK(swapz_engine_write_window_batched(
			&e, pages, 16, &initial_committed) == 0);
		CHECK(initial_committed == 16);
		for (index = 0; index < 16; ++index)
			CHECK(maps[index].valid && maps[index].generation == 1);
		credited_before = e.completed_blocks;
		physical_before = lower_written_bytes;
		publications_before = published_calls;
		CHECK(swapz_engine_prepare_batched_run(
			&e, pages, 16, &run, &prepared, 0) == 0);
		CHECK(prepared == 16 && run.extent_count >= 2);
		owner.accepted_writes = prepared;
		owner.references = 3; /* Accepted upper, lower request, test pin. */
		next_before = a.next_block;
		abandoned_before = a.abandoned_blocks;
		committed_before = a.committed_blocks;
		pending_before = a.batch_pending;
		if (scenario == 0)
			run.txs[1].records[0].generation++;
		else if (scenario == 1)
			run.txs[0].sequence++;
		else if (scenario == 2)
			run.offsets[1]++;

		write_sealed(NULL, prepared);
		lower_error = write_run(NULL, run.start_block, run.blocks,
					run.bytes, &lower_completed);
		owner.original_lower_errno = lower_error;
		owner.references--; /* The only real lower notification. */
		CHECK(lower_error == 0 && lower_completed == run.blocks);
		CHECK(lower_written_bytes - physical_before ==
		      (unsigned long long)run.blocks * SWAPZ_BLOCK_BYTES);
		CHECK(!maps_visible_during_run && !ownership_violation);
		error = swapz_engine_complete_batched_run(
			&e, &run, lower_completed, lower_error, &committed);
		if (!error && committed == prepared) {
			write_published(NULL, committed);
			owner.upper_success_completions = committed;
		}
		owner.upper_final_completions = prepared;
		owner.references--; /* Ordered owner gives each upper BIO one result. */
		repeated_error = swapz_engine_complete_batched_run(
			&e, &run, lower_completed, lower_error, &repeated_committed);
		if (valid_control) {
			if (error || committed != prepared ||
			    published_calls != publications_before + 1U ||
			    a.batch_pending || e.completed_blocks !=
				    credited_before + run.blocks ||
			    owner.upper_success_completions != prepared)
				goto failed;
			for (index = 0; index < prepared; ++index)
				if (!maps[index].valid || maps[index].generation != 2)
					goto failed;
		} else {
			if (error != -ESTALE || committed ||
			    published_calls != publications_before ||
			    e.completed_blocks != credited_before ||
			    a.batch_pending != pending_before ||
			    a.next_block != next_before ||
			    a.abandoned_blocks != abandoned_before ||
			    a.committed_blocks != committed_before ||
			    owner.upper_success_completions)
				goto failed;
			for (index = 0; index < prepared; ++index)
				if (!maps[index].valid || maps[index].generation != 1)
					goto failed;
			/* Unauthenticated, physically written space stays reserved. */
			{
				struct swapz_tx unrelated;
				swapz_u32 logical_page = 100;

				if (swapz_stage(&a, &logical_page, 1, 1,
						&unrelated) != -EBUSY)
					goto failed;
			}
		}
		if (repeated_error != -ESTALE || repeated_committed ||
		    owner.references != 1 ||
		    owner.upper_final_completions != owner.accepted_writes ||
		    owner.original_lower_errno != 0)
			goto failed;
		owner.references--; /* The synthetic duplicate's lifetime pin. */
		CHECK(!owner.references);
		continue;
failed:
		fprintf(stderr,
			"FAIL: lower-write-aggregation scenario=%s "
			"lower_errno=%d completion_errno=%d repeated_errno=%d "
			"upper_final=%u upper_success=%u accepted=%u refs=%u "
			"committed=%u repeat_committed=%u credited_before=%u "
			"credited_after=%u physical_written_delta=%llu "
			"published_before=%u published_after=%u "
			"pending_before=%u pending_after=%u "
			"generation_first=%u generation_second=%u\n",
			scenarios[scenario], lower_error, error, repeated_error,
			owner.upper_final_completions, owner.upper_success_completions,
			owner.accepted_writes, owner.references,
			committed, repeated_committed, credited_before,
			e.completed_blocks, lower_written_bytes - physical_before,
			publications_before, published_calls, pending_before,
			a.batch_pending, maps[0].generation, maps[1].generation);
		return 1;
	}
	return 0;
}



/*
 * Representation is part of the immutable lower-run identity. A compressed
 * one-block transaction and a RAW one-block transaction have the same basic
 * transaction geometry, so transaction CRC authentication alone cannot
 * distinguish them. Damage only the caller-side representation bit after the
 * real lower write and require rejection before either overwrite publishes.
 */
static int test_full_lower_success_rejects_representation_substitution(void)
{
	struct swapz_io_run run = { .bytes = bulk, .txs = bulk_txs };
	swapz_u8 initial_committed = 0, prepared = 0, committed = 99;
	swapz_u16 completed = 0;
	swapz_u32 credited_before, abandoned_before, committed_before;
	swapz_u8 pending_before;
	unsigned int publications_before;
	unsigned long long physical_before;
	int error;

	CHECK(setup() == 0);
	prepare_raw_tail(1, 2);
	CHECK(swapz_engine_write_window_batched(
		&e, pages, 2, &initial_committed) == 0);
	CHECK(initial_committed == 2);
	CHECK(maps[0].valid && !maps[0].raw && maps[0].generation == 1);
	CHECK(maps[1].valid && maps[1].raw && maps[1].generation == 1);
	CHECK(swapz_engine_prepare_batched_run(
		&e, pages, 2, &run, &prepared, 0) == 0);
	CHECK(prepared == 2 && run.extent_count == 2);
	CHECK(run.txs[0].count == 1 && run.txs[0].extent_blocks == 1);
	CHECK(!run.raw[0] && run.raw[1]);
	pending_before = a.batch_pending;
	credited_before = e.completed_blocks;
	abandoned_before = a.abandoned_blocks;
	committed_before = a.committed_blocks;
	publications_before = published_calls;
	physical_before = lower_written_bytes;
	write_sealed(NULL, prepared);
	CHECK(write_run(NULL, run.start_block, run.blocks,
			run.bytes, &completed) == 0);
	CHECK(completed == run.blocks);
	CHECK(lower_written_bytes - physical_before ==
	      (unsigned long long)run.blocks * SWAPZ_BLOCK_BYTES);
	CHECK(!maps_visible_during_run && !ownership_violation);
	/* Old code accepted this because count=1/blocks=1 is legal for RAW too. */
	run.raw[0] = 1;
	error = swapz_engine_complete_batched_run(
		&e, &run, completed, 0, &committed);
	CHECK(error == -ESTALE && committed == 0);
	CHECK(e.completed_blocks == credited_before);
	CHECK(a.batch_pending == pending_before);
	CHECK(a.abandoned_blocks == abandoned_before);
	CHECK(a.committed_blocks == committed_before);
	CHECK(published_calls == publications_before);
	CHECK(maps[0].valid && !maps[0].raw && maps[0].generation == 1);
	CHECK(maps[1].valid && maps[1].raw && maps[1].generation == 1);
	return 0;
}

int main(void)
{
	int passed = 0;

	CHECK(test_full_lower_success_rejects_representation_substitution() == 0); passed++;
	CHECK(test_full_lower_success_authenticates_entire_run_before_publish() == 0); passed++;
	CHECK(test_damaged_nonoldest_snapshot_preserves_lower_ownership() == 0); passed++;
	CHECK(test_stale_lower_completion_keeps_successor_reserved() == 0); passed++;
	CHECK(test_duplicate_lower_completion_accounted_once() == 0); passed++;
	CHECK(test_overcomplete_failed_wrapper_preserves_lower_errno() == 0); passed++;

	CHECK(test_planned_write_preserves_nonoverlap_read_residency() == 0); passed++;
	CHECK(test_immutable_run_prepare_then_complete() == 0); passed++;
	CHECK(test_immutable_run_failure_quarantines_all() == 0); passed++;
	CHECK(test_real_aggregation_and_readback() == 0); passed++;
	CHECK(test_failed_run_acks_nothing() == 0); passed++;
	CHECK(test_overwrite_failed_run_preserves_old_pages() == 0); passed++;
	CHECK(test_publication_observer_follows_authority_publish() == 0); passed++;
	CHECK(test_successful_bulk_overwrite_publishes_after_completion() == 0); passed++;
	CHECK(test_short_run_acks_nothing() == 0); passed++;
	CHECK(test_corrupted_completed_run_detected_on_read() == 0); passed++;
	CHECK(test_duplicate_slots_use_original_sequential_path() == 0); passed++;
	CHECK(test_write_verify_stays_serialized() == 0); passed++;
	CHECK(test_bulk_control_uses_original_lower_requests() == 0); passed++;
	CHECK(test_explicit_padding_mode_preserves_crc_and_authority() == 0); passed++;
	CHECK(test_same_input_no_padding_writes_identical_bytes() == 0); passed++;
	CHECK(test_randomized_same_binary_authority_equivalence() == 0); passed++;
	CHECK(test_padding_option_measures_exact_request_byte_tradeoff() == 0); passed++;
	CHECK(test_packed_placement_removes_internal_hole() == 0); passed++;
	CHECK(test_segment_tail_waste_is_accounted_before_rotation() == 0); passed++;
	CHECK(test_packed_tie_uses_larger_extent_without_padding() == 0); passed++;
	CHECK(test_forged_deferred_snapshot_is_rejected() == 0); passed++;
	CHECK(test_error_after_completed_prefix_at_segment_boundary() == 0); passed++;
	CHECK(test_mixed_and_raw_only_share_lower_runs() == 0); passed++;
	CHECK(test_mixed_default_equal_bytes_vs_serial_raw_control() == 0); passed++;
	CHECK(test_mixed_lower_failures_quarantine_unpublished_raw() == 0); passed++;
	CHECK(test_mixed_failed_overwrite_preserves_old_generations() == 0); passed++;
	CHECK(test_mixed_later_run_failure_keeps_only_completed_prefix() == 0); passed++;
	CHECK(test_mixed_successful_cross_format_overwrite() == 0); passed++;
	CHECK(test_mixed_819_205_distribution_economy() == 0); passed++;
	CHECK(test_mixed_realistic_payloads_keep_zero_padding() == 0); passed++;
	CHECK(test_explicit_read_cap_keeps_bulk_run_and_avoids_4block_extents() == 0); passed++;
	CHECK(test_malformed_mixed_input_fails_before_staging() == 0); passed++;
	printf("SWAPZ_BULK_IO_TESTS_PASS=%d\n", passed);
	return 0;
}
