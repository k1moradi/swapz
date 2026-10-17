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
	fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)

#define PHYSICAL (4U * SWAPZ_SEGMENT_BLOCKS)
static swapz_u8 media[PHYSICAL * SWAPZ_BLOCK_BYTES];
static struct swapz_authority a;
static struct swapz_map maps[128];
static swapz_u16 live[PHYSICAL];
static swapz_u8 classes[PHYSICAL], roles[4];
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
static unsigned int corrupt_on_run;
static unsigned int short_on_run;
static unsigned int maps_visible_during_run;
static unsigned int ownership_violation;
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
	if (block >= PHYSICAL || blocks > PHYSICAL - block)
		return -ERANGE;
	memcpy(media + (size_t)block * SWAPZ_BLOCK_BYTES, src,
	       (size_t)blocks * SWAPZ_BLOCK_BYTES);
	extent_calls++;
	lower_written_bytes += (unsigned long long)blocks * SWAPZ_BLOCK_BYTES;
	*completed = blocks;
	return 0;
}

static int write_run(void *opaque, swapz_u32 block, swapz_u16 blocks,
		     const swapz_u8 *src, swapz_u16 *completed)
{
	swapz_u32 i;

	(void)opaque;
	*completed = 0;
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
	if (fail_on_run && run_calls == fail_on_run)
		return -EIO;
	if (short_on_run && run_calls == short_on_run) {
		*completed = blocks - 1;
		memcpy(media + (size_t)block * SWAPZ_BLOCK_BYTES, src,
		       (size_t)*completed * SWAPZ_BLOCK_BYTES);
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
	a.reuse_dead_segments = 1;
	error = swapz_enable_segment_rotation(&a, roles, 4);
	if (error)
		return error;
	memset(media, 0, sizeof(media));
	memset(&e, 0, sizeof(e));
	e.authority = &a;
	e.io.write_extent = write_extent;
	e.io.write_run = write_run;
	e.io.read_blocks = read_blocks;
	e.write_scratch = scratch;
	e.read_scratch = reader;
	e.bulk_scratch = bulk;
	e.bulk_txs = bulk_txs;
	e.bulk_enabled = 1;
	extent_calls = run_calls = read_calls = 0;
	fail_on_run = short_on_run = corrupt_on_run = 0;
	maps_visible_during_run = 0;
	ownership_violation = 0;
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
	fail_on_run = run_calls + 1;
	committed = 91;
	CHECK(swapz_engine_write_window_batched(&e, pages, 16,
					     &committed) == -EIO);
	CHECK(committed == 0 && !a.in_flight && !a.batch_pending);
	CHECK(!ownership_violation && !maps_visible_during_run);
	for (i = 0; i < 16; ++i) {
		swapz_u8 output[SWAPZ_MAX_COMPRESSED];
		swapz_u16 length = 0;

		CHECK(maps[i].valid &&
		      maps[i].start_block == original[i].start_block &&
		      maps[i].generation == original[i].generation &&
		      maps[i].sequence == original[i].sequence);
		CHECK(swapz_engine_read_page(&e, i, output,
					  sizeof(output), &length) == 0);
		CHECK(length == pages[i].length);
		for (j = 0; j < length; ++j)
			CHECK(output[j] == (swapz_u8)(i + 1U));
	}
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
	unsigned int adjacent_calls;
	unsigned long long adjacent_bytes;
	unsigned int i;

	/*
	 * Four representative medium pages have two byte/read/extent-count
	 * equivalent plans: [1,2] and [2,1]. Prefer [2,1] so the same 12KiB
	 * is one adjacent lower run instead of two requests around an internal
	 * alignment hole. No padding bytes are written.
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
	 * Preserve a non-tied geometry where [1,2] is genuinely required.
	 * Mode1 skips the internal hole; mode2 may explicitly write it to
	 * trade one extra 4KiB block for one lower request.
	 */
	CHECK(setup() == 0);
	committed = 0;
	for (i = 0; i < 4; ++i) {
		memset(payloads[i], (int)i + 1, lengths[i]);
		pages[i].length = lengths[i];
	}
	CHECK(swapz_engine_write_window_batched(&e, pages, 4,
					     &committed) == 0);
	CHECK(committed == 4 && e.bulk_padding_blocks == 0);
	CHECK(validate_prefix(4) == 0);
	adjacent_calls = run_calls;
	adjacent_bytes = lower_written_bytes;
	CHECK(adjacent_calls == 2 && adjacent_bytes == 3U * SWAPZ_BLOCK_BYTES);
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
	CHECK(e.bulk_padding_blocks == 1 && run_calls == 1);
	CHECK(lower_written_bytes == adjacent_bytes + SWAPZ_BLOCK_BYTES);
	/* The explicit alignment hole is real lower-media padding and must
	 * be zero even when bulk_scratch contains bytes from an earlier run. */
	for (i = 0; i < SWAPZ_BLOCK_BYTES; ++i)
		CHECK(media[SWAPZ_BLOCK_BYTES + i] == 0);
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
		CHECK(maps[i].raw_crc32c == combined[i].raw_crc32c);
		CHECK(maps[i].raw == combined[i].raw);
	}
	return 0;
}

static int test_mixed_lower_failures_quarantine_unpublished_raw(void)
{
	unsigned int failure_mode;

	for (failure_mode = 0; failure_mode < 2; ++failure_mode) {
		swapz_u8 committed = 77;

		CHECK(setup() == 0);
		prepare_raw_tail(8, 32);
		if (failure_mode)
			short_on_run = 1;
		else
			fail_on_run = 1;
		CHECK(swapz_engine_write_window_batched(&e, pages, 32,
						     &committed) == -EIO);
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
		CHECK(maps[i].raw_crc32c == previous[i].raw_crc32c);
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
 * compressed records and 25% raw pages, including SWZ3 4/8/16KiB extents.
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

int main(void)
{
	int passed = 0;

	CHECK(test_real_aggregation_and_readback() == 0); passed++;
	CHECK(test_failed_run_acks_nothing() == 0); passed++;
	CHECK(test_overwrite_failed_run_preserves_old_pages() == 0); passed++;
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
