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
#include "../../kernel/extent-v3/engine.h"
#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)

#define PHYSICAL (4U * SV3_SEGMENT_BLOCKS)
static sv3_u8 media[PHYSICAL * SV3_BLOCK_BYTES];
static struct sv3_authority a;
static struct sv3_map maps[128];
static sv3_u16 live[PHYSICAL];
static sv3_u8 classes[PHYSICAL], roles[4];
static struct sv3_engine e;
static struct sv3_tx bulk_txs[SV3_MAX_RECORDS];
static sv3_u8 scratch[SV3_MAX_EXTENT_BYTES], reader[SV3_MAX_EXTENT_BYTES];
static sv3_u8 bulk[SV3_BULK_BLOCKS * SV3_BLOCK_BYTES];
static sv3_u8 payloads[SV3_MAX_RECORDS][SV3_MAX_COMPRESSED];
static struct sv3_compressed_page pages[SV3_MAX_RECORDS];
static unsigned int extent_calls, run_calls, read_calls;
static unsigned int fail_on_run;
static unsigned int corrupt_on_run;
static unsigned int short_on_run;
static unsigned int maps_visible_during_run;
static unsigned int ownership_violation;
static unsigned long long lower_written_bytes;

static int read_blocks(void *opaque, sv3_u32 block, sv3_u8 blocks, sv3_u8 *out)
{
	(void)opaque;
	if (block >= PHYSICAL || blocks > PHYSICAL - block)
		return -ERANGE;
	memcpy(out, media + (size_t)block * SV3_BLOCK_BYTES,
	       (size_t)blocks * SV3_BLOCK_BYTES);
	read_calls++;
	return 0;
}

static int write_extent(void *opaque, sv3_u32 block, sv3_u8 blocks,
			const sv3_u8 *src, sv3_u8 *completed)
{
	(void)opaque;
	*completed = 0;
	if (block >= PHYSICAL || blocks > PHYSICAL - block)
		return -ERANGE;
	memcpy(media + (size_t)block * SV3_BLOCK_BYTES, src,
	       (size_t)blocks * SV3_BLOCK_BYTES);
	extent_calls++;
	lower_written_bytes += (unsigned long long)blocks * SV3_BLOCK_BYTES;
	*completed = blocks;
	return 0;
}

static int write_run(void *opaque, sv3_u32 block, sv3_u16 blocks,
		     const sv3_u8 *src, sv3_u16 *completed)
{
	sv3_u32 i;

	(void)opaque;
	*completed = 0;
	if (!blocks || blocks > SV3_BULK_BLOCKS ||
	    block >= PHYSICAL || blocks > PHYSICAL - block ||
	    block / SV3_SEGMENT_BLOCKS !=
	    (block + blocks - 1U) / SV3_SEGMENT_BLOCKS)
		return -ERANGE;
	run_calls++;
	{
		struct sv3_tx unauthorized;
		sv3_u32 logical = 0;

		/* Lower callback executes with staged-but-UNPUBLISHED maps.
		 * No unrelated discard or direct stage may race its ownership. */
		if (sv3_stage(&a, &logical, 1, 1, &unauthorized) != -EBUSY ||
		    sv3_discard_page(&a, logical) != -EBUSY)
			ownership_violation++;
	}
	/* Older, already completed combined runs legitimately published
	 * mappings. Only the current run's NEW generations must remain
	 * invisible until this lower callback returns success. */
	for (i = 0; i < a.batch_pending; ++i) {
		const struct sv3_tx *tx = &bulk_txs[i];
		sv3_u8 j;

		for (j = 0; j < tx->count; ++j) {
			sv3_u32 logical = tx->records[j].logical_page;

			if (maps[logical].generation >=
			    tx->records[j].generation)
				maps_visible_during_run++;
		}
	}
	if (fail_on_run && run_calls == fail_on_run)
		return -EIO;
	if (short_on_run && run_calls == short_on_run) {
		*completed = blocks - 1;
		memcpy(media + (size_t)block * SV3_BLOCK_BYTES, src,
		       (size_t)*completed * SV3_BLOCK_BYTES);
		return 0;
	}
	memcpy(media + (size_t)block * SV3_BLOCK_BYTES, src,
	       (size_t)blocks * SV3_BLOCK_BYTES);
	if (corrupt_on_run && run_calls == corrupt_on_run)
		media[(size_t)block * SV3_BLOCK_BYTES + 7] ^= 1;
	lower_written_bytes += (unsigned long long)blocks * SV3_BLOCK_BYTES;
	*completed = blocks;
	return 0;
}

static int setup(void)
{
	unsigned int i;
	int error = sv3_authority_init(&a, maps, live, classes,
					128, PHYSICAL);

	if (error)
		return error;
	a.reuse_dead_segments = 1;
	error = sv3_enable_segment_rotation(&a, roles, 4);
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
	for (i = 0; i < SV3_MAX_RECORDS; ++i) {
		sv3_u16 length = i % 3 == 0 ? 2089 : i % 3 == 1 ? 1032 : 2200;

		memset(payloads[i], (int)i + 1, length);
		pages[i] = (struct sv3_compressed_page){
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

	for (i = 0; i < SV3_MAX_RECORDS; ++i) {
		sv3_u8 output[SV3_MAX_COMPRESSED];
		sv3_u16 length = 0;

		CHECK((maps[i].valid != 0) == (i < committed));
		if (i >= committed)
			continue;
		CHECK(sv3_engine_read_page(&e, i, output,
					  sizeof(output), &length) == 0);
		CHECK(length == pages[i].length);
		CHECK(!memcmp(output, payloads[i], length));
	}
	CHECK(!a.batch_pending && !a.in_flight);
	return 0;
}

static int test_real_aggregation_and_readback(void)
{
	sv3_u8 committed = 0;

	CHECK(setup() == 0);
	CHECK(sv3_engine_write_window_batched(&e, pages, 64,
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
	struct sv3_map original[16];
	sv3_u8 committed = 0;
	unsigned int i, j;

	CHECK(setup() == 0);
	CHECK(sv3_engine_write_window_batched(&e, pages, 16,
					     &committed) == 0);
	CHECK(committed == 16);
	memcpy(original, maps, sizeof(original));
	for (i = 0; i < 16; ++i)
		memset(payloads[i], 0xa7, pages[i].length);
	fail_on_run = run_calls + 1;
	committed = 91;
	CHECK(sv3_engine_write_window_batched(&e, pages, 16,
					     &committed) == -EIO);
	CHECK(committed == 0 && !a.in_flight && !a.batch_pending);
	CHECK(!ownership_violation && !maps_visible_during_run);
	for (i = 0; i < 16; ++i) {
		sv3_u8 output[SV3_MAX_COMPRESSED];
		sv3_u16 length = 0;

		CHECK(maps[i].valid &&
		      maps[i].start_block == original[i].start_block &&
		      maps[i].generation == original[i].generation &&
		      maps[i].sequence == original[i].sequence);
		CHECK(sv3_engine_read_page(&e, i, output,
					  sizeof(output), &length) == 0);
		CHECK(length == pages[i].length);
		for (j = 0; j < length; ++j)
			CHECK(output[j] == (sv3_u8)(i + 1U));
	}
	return 0;
}

static int test_successful_bulk_overwrite_publishes_after_completion(void)
{
	sv3_u8 committed = 0;
	unsigned int i;

	CHECK(setup() == 0);
	CHECK(sv3_engine_write_window_batched(&e, pages, 16,
					     &committed) == 0);
	CHECK(committed == 16);
	for (i = 0; i < 16; ++i)
		memset(payloads[i], 0xb8, pages[i].length);
	committed = 0;
	CHECK(sv3_engine_write_window_batched(&e, pages, 16,
					     &committed) == 0);
	CHECK(committed == 16 && !maps_visible_during_run);
	CHECK(!a.in_flight && !a.batch_pending && !ownership_violation);
	for (i = 0; i < 16; ++i) {
		sv3_u8 output[SV3_MAX_COMPRESSED];
		sv3_u16 length = 0;

		CHECK(maps[i].valid && maps[i].generation == 2);
		CHECK(sv3_engine_read_page(&e, i, output,
					  sizeof(output), &length) == 0);
		CHECK(length == pages[i].length);
		CHECK(!memcmp(output, payloads[i], length));
	}
	return 0;
}

static int test_failed_run_acks_nothing(void)
{
	sv3_u8 committed = 87;

	CHECK(setup() == 0);
	fail_on_run = 1;
	CHECK(sv3_engine_write_window_batched(&e, pages, 64,
					     &committed) == -EIO);
	CHECK(committed == 0);
	CHECK(run_calls == 1 && extent_calls == 0);
	CHECK(validate_prefix(0) == 0);
	CHECK(a.abandoned_blocks > 0);
	return 0;
}

static int test_corrupted_completed_run_detected_on_read(void)
{
	sv3_u8 committed = 77;
	int error;

	CHECK(setup() == 0);
	/* The lower callback reports full completion, but mutates the
	 * first extent's on-media header. This models corruption of
	 * submitted pages BEFORE independent CRC/mapping publication.
	 * The engine uses its original immutable RAM image for sv3_finish
	 * and must also be tested with explicit verify_after_write=1
	 * (which keeps the old serialized full readback path). */
	corrupt_on_run = 1;
	error = sv3_engine_write_window_batched(&e, pages, 64,
					       &committed);
	/* With write_verify=0, a lower device that lies about writes
	 * cannot be detected until a later read; logical publication
	 * remains valid only for the supplied immutable source image.
	 * The read MUST detect the corrupted on-media metadata. */
	CHECK(error == 0 && committed == 64);
	{
		sv3_u8 out[SV3_MAX_COMPRESSED];
		sv3_u16 len = 0;

		CHECK(sv3_engine_read_page(&e, 0, out,
					  sizeof(out), &len) != 0);
	}
	CHECK(!a.batch_pending && !a.in_flight);
	return 0;
}

static int test_short_run_acks_nothing(void)
{
	sv3_u8 committed = 87;

	CHECK(setup() == 0);
	short_on_run = 1;
	CHECK(sv3_engine_write_window_batched(&e, pages, 64,
					     &committed) == -EIO);
	CHECK(committed == 0);
	CHECK(run_calls == 1 && extent_calls == 0);
	CHECK(validate_prefix(0) == 0);
	return 0;
}

static int test_duplicate_slots_use_original_sequential_path(void)
{
	sv3_u8 committed = 0;

	CHECK(setup() == 0);
	pages[1].logical_page = pages[0].logical_page;
	CHECK(sv3_engine_write_window_batched(&e, pages, 2,
					     &committed) == 0);
	CHECK(committed == 2);
	CHECK(run_calls == 0 && extent_calls >= 2);
	CHECK(maps[0].valid && maps[0].generation == 2);
	CHECK(!a.batch_pending);
	return 0;
}

static int test_padding_option_measures_exact_request_byte_tradeoff(void)
{
	const sv3_u16 lengths[4] = { 700, 3500, 700, 3500 };
	sv3_u8 committed = 0;
	unsigned int adjacent_calls;
	unsigned long long adjacent_bytes;
	unsigned int i;

	CHECK(setup() == 0);
	for (i = 0; i < 4; ++i) {
		memset(payloads[i], (int)i + 1, lengths[i]);
		pages[i].length = lengths[i];
	}
	/* The real DP plans [1 block x1 record] then [2 blocks x3
	 * records]. Physical alignment skips block1. Mode1 does not
	 * overwrite it; mode2 explicitly pads one extra physical block. */
	CHECK(sv3_engine_write_window_batched(&e, pages, 4,
					     &committed) == 0);
	CHECK(committed == 4 && e.bulk_padding_blocks == 0);
	CHECK(validate_prefix(4) == 0);
	adjacent_calls = run_calls;
	adjacent_bytes = lower_written_bytes;
	CHECK(adjacent_calls == 2 && adjacent_bytes == 3U * SV3_BLOCK_BYTES);
	CHECK(setup() == 0);
	for (i = 0; i < 4; ++i) {
		memset(payloads[i], (int)i + 1, lengths[i]);
		pages[i].length = lengths[i];
	}
	e.bulk_enabled = 2;
	committed = 0;
	CHECK(sv3_engine_write_window_batched(&e, pages, 4,
					     &committed) == 0);
	CHECK(committed == 4 && validate_prefix(4) == 0);
	CHECK(e.bulk_padding_blocks == 1 && run_calls == 1);
	CHECK(lower_written_bytes == adjacent_bytes + SV3_BLOCK_BYTES);
	return 0;
}

static int test_same_input_no_padding_writes_identical_bytes(void)
{
	sv3_u8 committed = 0;
	unsigned long long combined_bytes;
	unsigned int combined_calls;

	CHECK(setup() == 0);
	e.bulk_enabled = 1;
	CHECK(sv3_engine_write_window_batched(&e, pages, 64,
					     &committed) == 0);
	CHECK(committed == 64 && !e.bulk_padding_blocks);
	combined_bytes = lower_written_bytes;
	combined_calls = run_calls;
	CHECK(setup() == 0);
	e.bulk_enabled = 0;
	committed = 0;
	CHECK(sv3_engine_write_window_batched(&e, pages, 64,
					     &committed) == 0);
	CHECK(committed == 64);
	CHECK(lower_written_bytes == combined_bytes);
	CHECK(extent_calls > combined_calls);
	CHECK(validate_prefix(64) == 0);
	return 0;
}

static int test_explicit_padding_mode_preserves_crc_and_authority(void)
{
	sv3_u8 committed = 0;

	CHECK(setup() == 0);
	e.bulk_enabled = 2;
	CHECK(sv3_engine_write_window_batched(&e, pages, 64,
					     &committed) == 0);
	CHECK(committed == 64 && run_calls && !maps_visible_during_run);
	CHECK(!ownership_violation && run_calls < e.bulk_extents);
	CHECK(validate_prefix(64) == 0);
	return 0;
}

static int test_bulk_control_uses_original_lower_requests(void)
{
	sv3_u8 committed = 0;

	CHECK(setup() == 0);
	e.bulk_enabled = 0;
	CHECK(sv3_engine_write_window_batched(&e, pages, 64,
					     &committed) == 0);
	CHECK(committed == 64 && run_calls == 0);
	CHECK(extent_calls > 3 && e.bulk_extents == 0);
	CHECK(validate_prefix(64) == 0);
	return 0;
}

static int test_write_verify_stays_serialized(void)
{
	sv3_u8 committed = 0;

	CHECK(setup() == 0);
	e.verify_after_write = 1;
	CHECK(sv3_engine_write_window_batched(&e, pages, 3,
					     &committed) == 0);
	CHECK(committed == 3);
	CHECK(run_calls == 0 && extent_calls);
	CHECK(!a.batch_pending);
	return 0;
}

static int test_forged_deferred_snapshot_is_rejected(void)
{
	struct sv3_tx tx, forged;
	sv3_u32 page = 0;

	CHECK(setup() == 0);
	CHECK(sv3_stage_batch(&a, &page, 1, 1, &tx) == 0);
	CHECK(sv3_batch_pause(&a, &tx) == 0);
	CHECK(!maps[0].valid && a.batch_pending == 1);
	forged = tx;
	forged.records[0].logical_page = 1;
	CHECK(sv3_batch_resume(&a, &forged) == -ESTALE);
	CHECK(!maps[0].valid && !maps[1].valid);
	CHECK(sv3_batch_resume(&a, &tx) == 0);
	CHECK(sv3_abort(&a, &tx) == 0);
	CHECK(!a.batch_pending && !a.in_flight && !maps[0].valid);
	return 0;
}

static int test_error_after_completed_prefix_at_segment_boundary(void)
{
	sv3_u8 committed = 0;
	sv3_u8 raw[SV3_BLOCK_BYTES];
	unsigned int i;

	CHECK(setup() == 0);
	memset(raw, 0x83, sizeof(raw));
	/* Fill foreground segment0 to within 4 blocks, while preserving
	 * one existing valid logical mapping outside the 0..63 window. */
	for (i = 0; i < SV3_SEGMENT_BLOCKS - 4; ++i) {
		struct sv3_tx tx;
		sv3_u32 page = 80;
		sv3_u8 complete = 0;

		CHECK(sv3_stage(&a, &page, 1, 1, &tx) == 0);
		CHECK(write_extent(NULL, tx.start_block, 1, raw,
				   &complete) == 0);
		CHECK(sv3_finish_raw(&a, &tx, raw, complete, 0) == 0);
	}
	CHECK(a.next_block == SV3_SEGMENT_BLOCKS - 4);
	/* The last four block slots were intentionally left empty: the
	 * previous loop allocated 252 blocks. */
	CHECK(maps[80].valid && maps[80].raw);
	fail_on_run = 2;
	CHECK(sv3_engine_write_window_batched(&e, pages, 64,
					     &committed) == -EIO);
	CHECK(run_calls == 2 && committed > 0 && committed < 64);
	CHECK(!ownership_violation);
	CHECK(validate_prefix(committed) == 0);
	CHECK(maps[80].valid && maps[80].raw_crc32c ==
	      sv3_crc32c_bytes(raw, sizeof(raw)));
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
	CHECK(test_padding_option_measures_exact_request_byte_tradeoff() == 0); passed++;
	CHECK(test_forged_deferred_snapshot_is_rejected() == 0); passed++;
	CHECK(test_error_after_completed_prefix_at_segment_boundary() == 0); passed++;
	printf("SV3_BULK_IO_TESTS_PASS=%d\n", passed);
	return 0;
}
