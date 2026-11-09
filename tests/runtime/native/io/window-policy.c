// SPDX-License-Identifier: GPL-2.0-only
/*
 * Execute the exact predicates included by the production DM worker.
 * These tests cover bounded slot dependencies and nanosecond expiry;
 * they do not emulate Linux BIO completion, timers or loaded lower I/O.
 */
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include "window-policy.h"

#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "%s:%d failed %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)

/* Diagnostics are emitted only on a failed bounded-pressure invariant. */
#define CHECK_PRESSURE(condition, constraint, lane_capacity, lanes_in_use, \
		       staged, queued, reserve_error) do { \
	if (!(condition)) { \
		fprintf(stderr, \
			"%s:%d failed %s (constraint=%s lane_capacity=%u lanes_in_use=%u staged=%u queued=%u reserve_errno=%d)\n", \
			__FILE__, __LINE__, #condition, (constraint), \
			(unsigned int)(lane_capacity), (unsigned int)(lanes_in_use), \
			(unsigned int)(staged), (unsigned int)(queued), \
			(int)(reserve_error)); \
		return 1; \
	} \
} while (0)

static int test_independent_compressed_and_raw(void)
{
	struct swapz_pending_bio pending[3] = {
		{ .logical = 7, .length = 2073 },
		{ .logical = 8, .length = SWAPZ_BLOCK_BYTES, .raw = 1 },
		{ .logical = 9, .length = 256 },
	};
	struct swapz_pending_bio original[3];

	memcpy(original, pending, sizeof(original));
	CHECK(swapz_window_read_independent(pending, 3, 6, 2, 0));
	CHECK(swapz_window_read_independent(pending, 3, 10, 2, 0));
	CHECK(swapz_window_read_independent(pending, 3, 0, 2, 0));
	CHECK(swapz_window_read_independent(pending, 3, ~(swapz_u32)0, 2, 0));
	CHECK(!memcmp(pending, original, sizeof(pending)));
	return 0;
}

static int test_every_pending_slot_fences_read(void)
{
	struct swapz_pending_bio pending[SWAPZ_MAX_RECORDS] = { 0 };
	swapz_u8 index;

	for (index = 0; index < SWAPZ_MAX_RECORDS; ++index) {
		pending[index].logical = 100 + index;
		pending[index].raw = index & 1U;
		pending[index].length = pending[index].raw ?
			SWAPZ_BLOCK_BYTES : 2073;
	}
	/* Check the first, middle and last slot, including RAW dependencies. */
	for (index = 0; index < SWAPZ_MAX_RECORDS; ++index)
		CHECK(!swapz_window_read_independent(pending, SWAPZ_MAX_RECORDS,
					pending[index].logical, 2, 0));
	CHECK(swapz_window_read_independent(pending, SWAPZ_MAX_RECORDS,
					99, 2, 0));
	CHECK(swapz_window_read_independent(pending, SWAPZ_MAX_RECORDS,
					100 + SWAPZ_MAX_RECORDS, 2, 0));
	return 0;
}

static int test_disabled_empty_and_invalid_window(void)
{
	struct swapz_pending_bio pending = { .logical = 4, .length = 2073 };

	CHECK(!swapz_window_read_independent(&pending, 1, 5, 0, 0));
	CHECK(!swapz_window_read_independent(&pending, 0, 5, 2, 0));
	CHECK(!swapz_window_read_independent(NULL, 1, 5, 2, 0));
	/* Invalid count must be rejected before accessing any array element. */
	CHECK(!swapz_window_read_independent(&pending, SWAPZ_MAX_RECORDS + 1,
					5, 2, 0));
	CHECK(!swapz_window_read_independent(NULL, SWAPZ_MAX_RECORDS + 1,
					5, 2, 0));
	return 0;
}

static int test_caller_fences_override_independence(void)
{
	struct swapz_pending_bio pending = { .logical = 4, .length = 2073 };
	unsigned int fence;

	/* Each of shutdown, failure, inflight, batch publication and flags
	 * must block independently when the caller supplies its predicate. */
	for (fence = 1; fence <= 32; fence <<= 1)
		CHECK(!swapz_window_read_independent(&pending, 1, 5, 2,
						(int)fence));
	CHECK(!swapz_window_read_independent(&pending, 1, 5, 2, -1));
	CHECK(swapz_window_read_independent(&pending, 1, 5, 2, 0));
	return 0;
}

static int test_pack_ready_waits_for_second_medium_pack(void)
{
	struct swapz_pending_bio batch[8] = { 0 };
	unsigned int i;

	for (i = 0; i < 8; ++i) {
		batch[i].logical = 100 + i;
		batch[i].length = 2073;
	}
	/* Two medium pages fit 8KiB but save no 4KiB block, so they are
	 * planner-only geometry. Three medium pages fit 8KiB and save one block.
	 * Six fit one 16KiB extent: same bytes as two old 8KiB commits, one
	 * synchronous lower callback. */
	CHECK(!swapz_window_single_pack_ready(batch, 2, 2, 0));
	CHECK(swapz_window_single_pack_ready(batch, 3, 2, 0));
	CHECK(!swapz_window_pack_ready(batch, 3, 2, 0));
	CHECK(!swapz_window_pack_ready(batch, 5, 2, 0));
	CHECK(swapz_window_pack_ready(batch, 6, 2, 0));
	CHECK(!swapz_window_pack_ready(batch, 7, 2, 0));
	CHECK(!swapz_window_pack_ready(batch, 8, 2, 0));
	CHECK(!swapz_window_pack_ready(batch, 6, 0, 0));
	CHECK(!swapz_window_pack_ready(batch, 6, 2, 1));
	CHECK(!swapz_window_pack_ready(batch, 6, 2, 3));
	CHECK(!swapz_window_pack_ready(NULL, 6, 2, 0));
	return 0;
}

static int test_pack_ready_small_and_medium_exact_geometry(void)
{
	struct swapz_pending_bio batch[6] = { 0 };
	unsigned int i;

	for (i = 0; i < 6; ++i) {
		batch[i].logical = 300 + i;
		batch[i].length = 2073;
	}
	/* Two medium pages exceed 4KiB and need two physical blocks, so they
	 * remain planner-only geometry. Three fit 8KiB and save one block, which
	 * may qualify as deferred pack geometry when service policy permits. */
	CHECK(!swapz_window_single_pack_ready(batch, 2, 2, 0));
	CHECK(swapz_window_single_pack_ready(batch, 3, 2, 0));
	CHECK(!swapz_window_pack_ready(batch, 3, 2, 0));
	CHECK(swapz_window_pack_ready(batch, 6, 2, 0));

	/*
	 * Four larger compressed records trivially fit the existing 16KiB
	 * extent class, but that is not selective first-pack evidence. Treating
	 * count=4 as a first pack closes at the learned floor below the >4
	 * asynchronous-detach threshold and can split QD8 into synchronous 4+4
	 * waves. Keep first-pack discovery restricted to the 4/8KiB tests.
	 */
	for (i = 0; i < 5; ++i)
		batch[i].length = 3000;
	CHECK(!swapz_window_single_pack_ready(batch, 2, 2, 0));
	CHECK(!swapz_window_single_pack_ready(batch, 3, 2, 0));
	CHECK(!swapz_window_single_pack_ready(batch, 4, 2, 0));
	CHECK(!swapz_window_pack_ready(batch, 4, 2, 0));
	CHECK(!swapz_window_single_pack_ready(batch, 5, 2, 0));

	/* Exact payload-only boundaries: RAM metadata consumes no extent bytes. */
	for (i = 0; i < 4; ++i)
		batch[i].length = 2048;
	CHECK(swapz_window_single_pack_ready(batch, 2, 2, 0));
	CHECK(!swapz_window_single_pack_ready(batch, 3, 2, 0));
	CHECK(!swapz_window_pack_ready(batch, 2, 2, 0));
	CHECK(swapz_window_pack_ready(batch, 4, 2, 0));
	batch[3].length = 2049;
	CHECK(!swapz_window_pack_ready(batch, 4, 2, 0));

	for (i = 0; i < 6; ++i)
		batch[i].length = 2730;
	batch[5].length = 2734; /* 5 * 2730 + 2734 == 16384 exactly. */
	CHECK(swapz_window_pack_ready(batch, 6, 2, 0));
	batch[5].length = 2735;
	CHECK(!swapz_window_pack_ready(batch, 6, 2, 0));
	batch[5].length = 2734;
	batch[0].raw = 1;
	CHECK(!swapz_window_pack_ready(batch, 6, 2, 0));
	batch[0].raw = 0;
	batch[1].length = 0;
	CHECK(!swapz_window_pack_ready(batch, 6, 2, 0));
	batch[1].length = SWAPZ_MAX_COMPRESSED + 1U;
	CHECK(!swapz_window_pack_ready(batch, 6, 2, 0));
	CHECK(!swapz_window_pack_ready(batch, 1, 2, 0));
	CHECK(!swapz_window_pack_ready(batch, 3, 2, 0));
	return 0;
}

static int test_pack_ready_rejects_raw_and_unfittable(void)
{
	struct swapz_pending_bio batch[6] = { 0 };
	unsigned int i;

	for (i = 0; i < 6; ++i) {
		batch[i].logical = 200 + i;
		batch[i].length = 2073;
	}
	batch[4].raw = 1;
	batch[4].length = SWAPZ_BLOCK_BYTES;
	CHECK(!swapz_window_pack_ready(batch, 6, 2, 0));
	batch[4].raw = 0;
	batch[4].length = 0;
	CHECK(!swapz_window_pack_ready(batch, 6, 2, 0));
	batch[4].length = SWAPZ_MAX_COMPRESSED + 1;
	CHECK(!swapz_window_pack_ready(batch, 6, 2, 0));
	batch[4].length = 2073;
	CHECK(swapz_window_pack_ready(batch, 6, 2, 0));
	for (i = 0; i < 6; ++i)
		batch[i].length = SWAPZ_MAX_COMPRESSED;
	CHECK(!swapz_window_pack_ready(batch, 6, 2, 0));
	for (i = 0; i < 6; ++i)
		batch[i].length = 2000;
	CHECK(swapz_window_pack_ready(batch, 6, 1, 0));
	/* The same geometry fails closed when retention/read policy disallows it. */
	CHECK(!swapz_window_pack_ready(batch, 6, 0, 0));
	CHECK(!swapz_window_pack_ready(batch, 6, 2, 1));
	CHECK(!swapz_window_pack_ready(NULL, 6, 2, 0));
	return 0;
}

static int test_pack_ready_uses_compressed_geometry_across_raw_slots(void)
{
	struct swapz_pending_bio batch[8] = { 0 };
	unsigned int i;

	batch[0].logical = 400;
	batch[0].length = SWAPZ_BLOCK_BYTES;
	batch[0].raw = 1;
	for (i = 1; i < 8; ++i) {
		batch[i].logical = 400 + i;
		batch[i].length = 2028;
	}
	batch[1].length = 2048;
	batch[2].length = 2048;
	/* RAW remains part of the eventual lower run, but it must not poison
	 * recognition of two compressed payloads that exactly fit one block. */
	CHECK(!swapz_window_single_pack_ready(batch, 2, 2, 0));
	CHECK(swapz_window_single_pack_ready(batch, 3, 2, 0));
	/* RAW skipping must not recreate the refuted total-count-four first-pack
	 * close below the K=1 asynchronous detach threshold. */
	batch[3].length = 2712;
	CHECK(!swapz_window_single_pack_ready(batch, 4, 2, 0));
	CHECK(!swapz_window_prior_single_pack_ready(batch, 4, 2, 0));
	/* Once total count crosses four, preserve proof that the earlier two-page
	 * compressed pack existed even if a later admission changes exact geometry. */
	batch[4].length = 1000;
	CHECK(swapz_window_prior_single_pack_ready(batch, 5, 2, 0));
	batch[4].length = SWAPZ_BLOCK_BYTES;
	batch[4].raw = 1;
	CHECK(swapz_window_prior_single_pack_ready(batch, 5, 2, 0));
	batch[4].raw = 0;
	batch[4].length = 2048;
	batch[3].length = 2048;
	/* Four compressed payloads plus one RAW record exactly fill the same 8KiB
	 * compressed extent geometry used by a RAW-free four-record prefix. */
	batch[1].length = 2048;
	batch[2].length = 2048;
	CHECK(swapz_window_pack_ready(batch, 5, 2, 0));
	/* A RAW newest admission cannot manufacture a fresh geometry transition. */
	batch[5].length = SWAPZ_BLOCK_BYTES;
	batch[5].raw = 1;
	CHECK(!swapz_window_pack_ready(batch, 6, 2, 0));
	batch[5].raw = 0;
	/* Six compressed payloads plus an earlier RAW record fill 16KiB exactly. */
	for (i = 1; i <= 6; ++i)
		batch[i].length = 2730;
	batch[6].length = 2734;
	CHECK(swapz_window_pack_ready(batch, 7, 2, 0));
	/* Invalid compressed records still fail closed even when RAW is skipped. */
	batch[3].length = 0;
	CHECK(!swapz_window_pack_ready(batch, 7, 2, 0));
	batch[3].length = SWAPZ_MAX_COMPRESSED + 1U;
	CHECK(!swapz_window_pack_ready(batch, 7, 2, 0));
	CHECK(!swapz_window_pack_ready(batch, 7, 0, 0));
	CHECK(!swapz_window_pack_ready(batch, 7, 2, 1));
	return 0;
}

static int test_retained_burst_target_adapts_from_finite_evidence(void)
{
	swapz_u8 target = swapz_window_initial_burst_target(SWAPZ_MAX_RECORDS);
	CHECK(swapz_window_initial_burst_target(0) == 0);
	CHECK(swapz_window_initial_burst_target(3) == 3);
	CHECK(target == 4);
	CHECK(swapz_window_grow_burst_target(target, 4, 4, SWAPZ_MAX_RECORDS) == 8);
	CHECK(swapz_window_grow_burst_target(8, 8, 8, SWAPZ_MAX_RECORDS) == 16);
	CHECK(swapz_window_grow_burst_target(48, 48, 32, SWAPZ_MAX_RECORDS) == SWAPZ_MAX_RECORDS);
	CHECK(swapz_window_shrink_burst_target(32, 8) == 8);
	CHECK(swapz_window_shrink_burst_target(32, 3) == 32);
	CHECK(swapz_window_shrink_burst_target(4, 3) == 4);
	CHECK(swapz_window_shrink_burst_target(4, 1) == 4);
	return 0;
}

static int test_sampled_tail_target_distinguishes_mixed_wave(void)
{
	CHECK(swapz_window_sampled_tail_target(0, 0, 0) == 0);
	CHECK(swapz_window_sampled_tail_target(1, 1, 1) == 0);
	CHECK(swapz_window_sampled_tail_target(2, 2, 0) == 0);
	CHECK(swapz_window_sampled_tail_target(3, 3, 0) == 0);
	/* The caller requires current queued followers before allowing
	 * earlier chain-level READ proof to classify a short mixed tail. */
	CHECK(swapz_window_sampled_tail_target(3, 0, 0) == 0);
	CHECK(swapz_window_sampled_tail_target(3, 1, 1) == 3);
	CHECK(swapz_window_sampled_tail_target(2, 0, 1) == 2);
	CHECK(swapz_window_sampled_tail_target(3, 2, 1) == 3);
	CHECK(swapz_window_sampled_tail_target(4, 0, 0) == 0);
	CHECK(swapz_window_sampled_tail_target(4, 1, 0) == 4);
	CHECK(swapz_window_sampled_tail_target(8, 3, 0) == 8);
	return 0;
}

static int test_post_pack_read_boundary_requires_fresh_finite_tail(void)
{
	CHECK(!swapz_window_post_pack_read_boundary_ready(0, 2, 0, 1, 1, 0));
	CHECK(!swapz_window_post_pack_read_boundary_ready(1, 1, 0, 1, 1, 0));
	CHECK(!swapz_window_post_pack_read_boundary_ready(1, 4, 0, 1, 1, 0));
	CHECK(!swapz_window_post_pack_read_boundary_ready(1, 2, 0, 0, 1, 0));
	CHECK(!swapz_window_post_pack_read_boundary_ready(1, 3, 0, 1, 0, 0));
	CHECK(!swapz_window_post_pack_read_boundary_ready(1, 3, 0, 1, 1, 1));
	CHECK(!swapz_window_post_pack_read_boundary_ready(1, 3, 3, 1, 1, 0));
	CHECK(swapz_window_post_pack_read_boundary_ready(1, 2, 0, 1, 1, 0));
	CHECK(swapz_window_post_pack_read_boundary_ready(1, 3, 0, 1, 1, 0));
	return 0;
}

static int test_post_pack_boundary_observation_survives_pending_sample(void)
{
	int serviced_after_tail =
		swapz_window_post_pack_read_boundary_observed(2, 1);

	CHECK(!swapz_window_post_pack_read_boundary_observed(1, 1));
	CHECK(!swapz_window_post_pack_read_boundary_observed(4, 1));
	CHECK(!swapz_window_post_pack_read_boundary_observed(3, 0));
	CHECK(swapz_window_post_pack_read_boundary_observed(3, 1));
	/* K=1 still owns the tail sample when this READ finishes. */
	CHECK(serviced_after_tail);
	CHECK(!swapz_window_post_pack_read_boundary_ready(
		1, 2, 0, 1, serviced_after_tail, 1));
	/* Once the sample is consumed, the original observation survives. */
	CHECK(swapz_window_post_pack_read_boundary_ready(
		1, 2, 0, 1, serviced_after_tail, 0));
	/* A subsequent staged WRITE revokes that ordering evidence. */
	serviced_after_tail = 0;
	CHECK(!swapz_window_post_pack_read_boundary_ready(
		1, 3, 0, 1, serviced_after_tail, 0));
	return 0;
}

static int test_service_dry_pack_requires_valid_multi_record_pack(void)
{
	CHECK(!swapz_window_service_close_ready(0, 1, 1, 0, 1, 1, 1));
	CHECK(!swapz_window_service_close_ready(0, 1, 2, 0, 1, 1, 0));
	CHECK(!swapz_window_service_close_ready(1, 1, 1, 0, 1, 1, 1));
	CHECK(!swapz_window_service_close_ready(1, 1, 2, 0, 1, 0, 0));
	CHECK(swapz_window_service_close_ready(1, 1, 2, 0, 1, 1, 0));
	CHECK(swapz_window_service_close_ready(1, 1, 3, 0, 1, 0, 1));
	CHECK(!swapz_window_service_close_ready(1, 1, 3, 4, 1, 1, 1));
	CHECK(swapz_window_service_close_ready(1, 1, 4, 0, 0, 0, 0));
	CHECK(swapz_window_service_close_ready(1, 0, 4, 0, 1, 0, 0));
	CHECK(!swapz_window_service_close_ready(1, 0, 4, 0, 0, 0, 0));
	/* Dry four-plus-record service must work for mixed compressed/RAW pages;
	 * an unproven two/three-record tail must not inherit this permission. */
	CHECK(!swapz_window_service_close_ready(0, 1, 3, 0, 0, 1, 1));
	CHECK(swapz_window_service_close_ready(0, 1, 4, 0, 0, 0, 0));
	CHECK(!swapz_window_service_close_ready(0, 1, 4, 8, 0, 0, 0));
	CHECK(!swapz_window_service_close_ready(0, 1, 7, 16, 0, 0, 0));
	CHECK(!swapz_window_service_close_ready(1, 1, 4, 8, 1, 1, 1));
	CHECK(swapz_window_service_close_ready(0, 1, 7, 0, 0, 0, 0));
	CHECK(!swapz_window_service_close_ready(0, 0, 4, 0, 0, 0, 0));
	return 0;
}


static int test_retained_burst_close_requires_geometry_or_sampled_tail(void)
{
	CHECK(!swapz_window_burst_close_ready(0, 0, 3, 4, 0));
	CHECK(!swapz_window_burst_close_ready(1, 0, 3, 4, 0));
	CHECK(swapz_window_burst_close_ready(1, 0, 4, 4, 0));
	CHECK(!swapz_window_burst_close_ready(1, 0, 7, 8, 0));
	CHECK(swapz_window_burst_close_ready(1, 0, 8, 8, 0));
	/* A complete second pack on a proven dry accepted queue must not wait
	 * for an oversized learned target and burn the absolute deadline. */
	CHECK(swapz_window_burst_close_ready(1, 1, 6, 32, 0));
	CHECK(swapz_window_burst_close_ready(0, 1, 6, 32, 0));
	CHECK(!swapz_window_burst_close_ready(0, 0, 1, 8, 1));
	CHECK(swapz_window_burst_close_ready(0, 0, 2, 8, 2));
	CHECK(!swapz_window_burst_close_ready(0, 0, 2, 8, 3));
	CHECK(swapz_window_burst_close_ready(0, 0, 3, 8, 3));
	return 0;
}


static int test_raw_pressure_hand_requires_dispatchable_target(void)
{
	CHECK(!swapz_window_raw_pressure_hand_dispatchable(2, 4, 0, 0));
	CHECK(swapz_window_raw_pressure_hand_dispatchable(0, 32, 0, 8));
	CHECK(swapz_window_raw_pressure_hand_dispatchable(2, 4, 0, 8));
	CHECK(swapz_window_raw_pressure_hand_dispatchable(2, 8, 0, 8));
	CHECK(!swapz_window_raw_pressure_hand_dispatchable(2, 9, 0, 8));
	CHECK(!swapz_window_raw_pressure_hand_dispatchable(2, 32, 0, 8));
	CHECK(swapz_window_raw_pressure_hand_dispatchable(2, 32, 6, 8));
	CHECK(!swapz_window_raw_pressure_hand_dispatchable(2, 32, 12, 8));
	return 0;
}

static int test_work_conserving_close_respects_retained_target(void)
{
	swapz_u8 count;

	CHECK(!swapz_window_work_conserving_close_ready(2, 1, 1, 4, 0, 8, 0));
	CHECK(swapz_window_work_conserving_close_ready(0, 0, 2, 4, 0, 8, 0));

	/* Counts 1..3 keep the pinned deadline even with valid pack evidence. */
	CHECK(!swapz_window_work_conserving_close_ready(2, 1, 2, 4, 0, 8, 0));
	CHECK(!swapz_window_work_conserving_close_ready(2, 1, 3, 4, 0, 8, 0));
	CHECK(swapz_window_work_conserving_close_ready(2, 0, 4, 4, 0, 8, 0));

	/* An accepted plain WRITE keeps the active wave on its target/hand rule. */
	CHECK(!swapz_window_work_conserving_close_ready(2, 1, 4, 16, 0, 8, 1));
	CHECK(!swapz_window_work_conserving_close_ready(2, 1, 7, 16, 0, 8, 1));
	CHECK(!swapz_window_work_conserving_close_ready(2, 1, 8, 16, 0, 8, 1));
	CHECK(swapz_window_work_conserving_close_ready(2, 0, 16, 16, 0, 8, 1));

	/* A genuinely dry FIFO may service a valid pack at the four-record floor. */
	CHECK(!swapz_window_work_conserving_close_ready(2, 0, 4, 32, 0, 8, 0));
	for (count = SWAPZ_WINDOW_DRY_PACK_MIN_RECORDS; count < 8U; ++count)
		CHECK(swapz_window_work_conserving_close_ready(
			2, 1, count, 32, 0, 8, 0));
	CHECK(swapz_window_work_conserving_close_ready(2, 1, 8, 32, 0, 8, 0));

	/* A sampled finite tail overrides the learned target and dry floor. */
	CHECK(!swapz_window_work_conserving_close_ready(2, 1, 4, 32, 8, 8, 0));
	CHECK(!swapz_window_work_conserving_close_ready(2, 1, 7, 32, 8, 8, 0));
	CHECK(swapz_window_work_conserving_close_ready(2, 0, 8, 32, 8, 8, 0));

	/* Changing only the hand width cannot bypass the four-record floor
	 * or demand new arrivals; it delays early close for a queued plain WRITE. */
	CHECK(swapz_window_work_conserving_close_ready(2, 1, 8, 8, 0, 8, 1));
	CHECK(!swapz_window_work_conserving_close_ready(2, 1, 8, 8, 0, 16, 1));
	CHECK(swapz_window_work_conserving_close_ready(2, 1, 16, 8, 0, 16, 1));
	CHECK(!swapz_window_work_conserving_close_ready(2, 1, 16, 8, 0, 64, 1));
	CHECK(swapz_window_work_conserving_close_ready(2, 1, 64, 8, 0, 64, 1));
	CHECK(!swapz_window_raw_pressure_hand_dispatchable(2, 32, 0, 16));
	CHECK(swapz_window_raw_pressure_hand_dispatchable(2, 16, 0, 16));
	CHECK(swapz_window_raw_pressure_hand_dispatchable(2, 32, 0, 64));
	return 0;
}

static int test_uniform_compressed_identity_sort_safety(void)
{
	struct swapz_pending_bio batch[SWAPZ_MAX_RECORDS] = { 0 };
	struct swapz_pending_bio snapshot[SWAPZ_MAX_RECORDS];
	swapz_u8 i;

	CHECK(!swapz_window_uniform_compressed(NULL, 1));
	CHECK(!swapz_window_uniform_compressed(batch, 0));
	CHECK(!swapz_window_uniform_compressed(batch, SWAPZ_MAX_RECORDS + 1));
	for (i = 0; i < SWAPZ_MAX_RECORDS; ++i) {
		batch[i].logical = 100 + i;
		batch[i].length = 2073;
	}
	memcpy(snapshot, batch, sizeof(batch));
	CHECK(swapz_window_uniform_compressed(batch, 1));
	CHECK(swapz_window_uniform_compressed(batch, 7));
	CHECK(swapz_window_uniform_compressed(batch, SWAPZ_MAX_RECORDS));
	CHECK(!memcmp(batch, snapshot, sizeof(batch)));
	batch[SWAPZ_MAX_RECORDS - 1].length = 2072;
	CHECK(!swapz_window_uniform_compressed(batch, SWAPZ_MAX_RECORDS));
	CHECK(swapz_window_uniform_compressed(batch, 7));
	batch[SWAPZ_MAX_RECORDS - 1].length = 2073;
	batch[0].raw = 1;
	CHECK(!swapz_window_uniform_compressed(batch, 7));
	batch[0].raw = 0;
	batch[3].raw = 1;
	CHECK(!swapz_window_uniform_compressed(batch, 7));
	batch[3].raw = 0;
	batch[2].length = 0;
	CHECK(!swapz_window_uniform_compressed(batch, 7));
	batch[2].length = 2073;
	batch[0].length = SWAPZ_MAX_COMPRESSED + 1U;
	CHECK(!swapz_window_uniform_compressed(batch, 7));
	/* Tiny uniform compressed payloads may pair into a 4KiB block;
	 * the greedy ordering is still first-then-next, i.e. identity. */
	for (i = 0; i < SWAPZ_MAX_RECORDS; ++i)
		batch[i].length = 500;
	CHECK(swapz_window_uniform_compressed(batch, 8));
	/* RAW controls and mixed entropy retain the greedy fallback. */
	batch[4].length = SWAPZ_BLOCK_BYTES;
	batch[4].raw = 1;
	CHECK(!swapz_window_uniform_compressed(batch, 8));
	return 0;
}

static int test_timer_cancel_only_for_enabled_retention(void)
{
	unsigned int retain;

	CHECK(!swapz_window_timer_enabled(0));
	for (retain = 1; retain <= 4; ++retain)
		CHECK(swapz_window_timer_enabled((swapz_u8)retain));
	return 0;
}

static int test_timer_arm_requires_retention_and_unqueued_timer(void)
{
	unsigned int retain;

	CHECK(!swapz_retention_timer_needs_arm(0, 0));
	CHECK(!swapz_retention_timer_needs_arm(0, 1));
	for (retain = 1; retain <= 4; ++retain) {
		CHECK(swapz_retention_timer_needs_arm((swapz_u8)retain, 0));
		CHECK(!swapz_retention_timer_needs_arm((swapz_u8)retain, 1));
	}
	return 0;
}

static int test_two_record_two_block_pack_geometry_survives_raw_slots(void)
{
	struct swapz_pending_bio batch[5] = { 0 };
	unsigned int index;

	batch[0].logical = 700;
	batch[1].logical = 701;
	batch[0].length = 2100;
	batch[1].length = 2100;
	for (index = 2; index < 5; ++index) {
		batch[index].logical = 700 + index;
		batch[index].length = SWAPZ_BLOCK_BYTES;
		batch[index].raw = 1;
	}

	/* The two compressed records still form valid 8KiB representation
	 * geometry across RAW slots, but two blocks for two records save no
	 * physical block and therefore must not arm deferred early-close state. */
	CHECK(swapz_window_first_compressed_extent_fits(batch, 5, 2U, 2U));
	CHECK(!swapz_window_single_pack_ready(batch, 2, 2, 0));
	CHECK(!swapz_window_single_pack_ready(batch, 2, 0, 0));
	CHECK(!swapz_window_single_pack_ready(batch, 2, 2, 1));
	/* Count four stays the protected first-pack floor. */
	CHECK(!swapz_window_single_pack_ready(batch, 4, 2, 0));
	CHECK(!swapz_window_prior_single_pack_ready(batch, 5, 2, 0));
	CHECK(!swapz_window_prior_single_pack_ready(batch, 4, 2, 0));
	return 0;
}

static int test_ordinary_retention_deadline_is_pinned(void)
{
	const unsigned long long first = 1000000ULL;

	CHECK(swapz_window_retention_deadline_ns(first, 2) == 3000000ULL);
	CHECK(!swapz_window_deadline_expired(3000000ULL, 2999999ULL));
	CHECK(swapz_window_deadline_expired(3000000ULL, 3000000ULL));
	CHECK(swapz_window_retention_deadline_ns(first, 0) == 0);
	return 0;
}

static int test_idle_bound_scales_with_lower_service(void)
{
	/* No retention means no timer; no sample keeps the ordinary deadline. */
	CHECK(swapz_window_idle_bound_ns(150000ULL, 0) == 0);
	CHECK(swapz_window_idle_bound_ns(0, 2) == 2000000ULL);
	/* Half of one lower service interval, floored and capped. */
	CHECK(swapz_window_idle_bound_ns(190000ULL, 2) == 95000ULL);
	CHECK(swapz_window_idle_bound_ns(30000ULL, 2) ==
	      SWAPZ_WINDOW_IDLE_BOUND_MIN_NS);
	CHECK(swapz_window_idle_bound_ns(10000000ULL, 2) == 2000000ULL);
	CHECK(swapz_window_idle_bound_ns(10000000ULL, 4) == 4000000ULL);
	return 0;
}

static int test_effective_deadline_only_moves_earlier(void)
{
	unsigned long long first = swapz_window_retention_deadline_ns(1000000ULL, 2);

	/* No lower-idle interval or bound: the pinned first-record deadline. */
	CHECK(swapz_window_effective_deadline_ns(first, 0, 95000ULL) == first);
	CHECK(swapz_window_effective_deadline_ns(first, 1500000ULL, 0) == first);
	CHECK(swapz_window_effective_deadline_ns(0, 1500000ULL, 95000ULL) == 0);
	/* An idle interval makes it earlier, never later. */
	CHECK(swapz_window_effective_deadline_ns(first, 1500000ULL, 95000ULL) ==
	      1595000ULL);
	CHECK(swapz_window_effective_deadline_ns(first, 2950000ULL, 95000ULL) ==
	      first);
	CHECK(swapz_window_effective_deadline_ns(first, ~0ULL - 1ULL, 95000ULL) ==
	      first);
	return 0;
}

static int test_lower_service_ewma(void)
{
	unsigned long long ewma = 0;

	CHECK(swapz_window_ewma_update(0, 0) == 0);
	ewma = swapz_window_ewma_update(ewma, 160000ULL);
	CHECK(ewma == 160000ULL);
	CHECK(swapz_window_ewma_update(ewma, 0) == ewma);
	ewma = swapz_window_ewma_update(ewma, 240000ULL);
	CHECK(ewma == 170000ULL);
	return 0;
}

static int test_pure_write_half_burst_waits_for_learned_width(void)
{
	/* QD8 under K=1: four staged while the run flew, four just released. */
	CHECK(swapz_window_pure_write_below_burst(0, 4, 8));
	CHECK(!swapz_window_pure_write_below_burst(0, 8, 8));
	CHECK(!swapz_window_pure_write_below_burst(0, 9, 8));
	/* Mixed READ/non-WRITE evidence keeps finite tails immediate. */
	CHECK(!swapz_window_pure_write_below_burst(1, 4, 8));
	/* No learned width: the existing floor policy decides. */
	CHECK(!swapz_window_pure_write_below_burst(0, 4, 0));
	return 0;
}

static int test_raw_hand_pays_only_for_slow_compression(void)
{
	/* Missing evidence keeps the existing pressure hand. */
	CHECK(swapz_window_raw_hand_pays(0, 38000ULL));
	CHECK(swapz_window_raw_hand_pays(900ULL, 0));
	/* Sub-microsecond LZ4 never beats tens of microseconds per block. */
	CHECK(!swapz_window_raw_hand_pays(900ULL, 38000ULL));
	CHECK(!swapz_window_raw_hand_pays(900ULL, 6500ULL));
	/* Slow compression in front of a fast device prefers RAW. */
	CHECK(swapz_window_raw_hand_pays(4000ULL, 6500ULL));
	/* The 2*LZ4 comparison used to wrap above ULLONG_MAX/2. */
	CHECK(!swapz_window_raw_hand_pays(ULLONG_MAX / 2ULL, ULLONG_MAX));
	CHECK(swapz_window_raw_hand_pays(ULLONG_MAX / 2ULL + 1ULL,
						 ULLONG_MAX));
	CHECK(swapz_window_raw_hand_pays(ULLONG_MAX, ULLONG_MAX));
	CHECK(!swapz_window_raw_hand_pays(3250ULL, 6500ULL));
	CHECK(swapz_window_raw_hand_pays(3251ULL, 6500ULL));
	CHECK(!swapz_window_raw_hand_pays(2ULL, 5ULL));
	CHECK(swapz_window_raw_hand_pays(3ULL, 5ULL));
	return 0;
}

static int test_section_wall_ns_never_underflows(void)
{
	CHECK(swapz_elapsed_ns(100, 170) == 70ULL);
	CHECK(swapz_elapsed_ns(100, 100) == 0ULL);
	CHECK(swapz_elapsed_ns(170, 100) == 0ULL);
	CHECK(swapz_elapsed_ns(0, ULLONG_MAX) == ULLONG_MAX);
	CHECK(swapz_elapsed_ns(ULLONG_MAX, 0) == 0ULL);
	return 0;
}

static int test_disabled_or_missing_timestamp_expires(void)
{
	CHECK(swapz_window_retention_expired(1000, 1000, 0));
	CHECK(swapz_window_retention_expired(0, 0, 2));
	CHECK(swapz_window_retention_expired(0, 1000, 2));
	return 0;
}

static int test_exact_nanosecond_deadline(void)
{
	const unsigned long long first = 123456789ULL;
	swapz_u8 retain;

	for (retain = 1; retain <= 4; ++retain) {
		unsigned long long deadline = first +
			(unsigned long long)retain * 1000000ULL;

		CHECK(!swapz_window_retention_expired(first, first, retain));
		CHECK(!swapz_window_retention_expired(first, deadline - 1, retain));
		CHECK(swapz_window_retention_expired(first, deadline, retain));
		CHECK(swapz_window_retention_expired(first, deadline + 1, retain));
	}
	return 0;
}

static int test_expiry_remains_pinned_after_later_arrivals(void)
{
	const unsigned long long first = 1000000ULL;
	const unsigned long long arrivals[] = {
		1000001ULL, 1500000ULL, 2000000ULL, 2999999ULL,
	};
	unsigned int index;

	for (index = 0; index < sizeof(arrivals) / sizeof(arrivals[0]); ++index)
		CHECK(!swapz_window_retention_expired(first, arrivals[index], 2));
	CHECK(swapz_window_retention_expired(first, 3000000ULL, 2));
	CHECK(swapz_window_retention_expired(first, 3000001ULL, 2));
	CHECK(swapz_window_retention_expired(first, 6000000ULL, 2));
	return 0;
}

static int test_backwards_clock_has_zero_age(void)
{
	CHECK(!swapz_window_retention_expired(3000000ULL, 2999999ULL, 2));
	CHECK(!swapz_window_retention_expired(3000000ULL, 0, 2));
	CHECK(!swapz_window_retention_expired(ULLONG_MAX, 1, 2));
	return 0;
}

static int test_late_clock_does_not_wrap_remaining_budget(void)
{
	const unsigned long long first = 1;

	/* The alpha.11 second clock sample could cross expiry and underflow
	 * budget-age. Every sample at or after expiry must remain expired. */
	CHECK(!swapz_window_retention_expired(first, 2000000ULL, 2));
	CHECK(swapz_window_retention_expired(first, 2000001ULL, 2));
	CHECK(swapz_window_retention_expired(first, 2000002ULL, 2));
	CHECK(swapz_window_retention_expired(first, ULLONG_MAX, 2));
	CHECK(!swapz_window_retention_expired(ULLONG_MAX - 2000000ULL,
					ULLONG_MAX - 1, 2));
	CHECK(swapz_window_retention_expired(ULLONG_MAX - 2000000ULL,
					ULLONG_MAX, 2));
	return 0;
}

/* ID175: only a learned isolated idle stream may skip the ordered worker. */
static int test_submitter_dispatch_requires_proven_idle_singleton(void)
{
	CHECK(swapz_window_submitter_dispatch_ready(2, 1, 0, 0, 0, 0, 0));
	CHECK(swapz_window_submitter_dispatch_ready(4, 1, 0, 0, 0, 0, 0));
	/* Retention off or not yet learned: the ordinary owner decides. */
	CHECK(!swapz_window_submitter_dispatch_ready(0, 1, 0, 0, 0, 0, 0));
	CHECK(!swapz_window_submitter_dispatch_ready(2, 0, 0, 0, 0, 0, 0));
	/* Each pending scheduling or ownership state keeps the worker path. */
	CHECK(!swapz_window_submitter_dispatch_ready(2, 1, 1, 0, 0, 0, 0));
	CHECK(!swapz_window_submitter_dispatch_ready(2, 1, 0, 1, 0, 0, 0));
	CHECK(!swapz_window_submitter_dispatch_ready(2, 1, 0, 0, 1, 0, 0));
	CHECK(!swapz_window_submitter_dispatch_ready(2, 1, 0, 0, SWAPZ_MAX_RECORDS,
						      0, 0));
	CHECK(!swapz_window_submitter_dispatch_ready(2, 1, 0, 0, 0, 1, 0));
	/* A queued follower must be offered to the ordinary aggregation policy. */
	CHECK(!swapz_window_submitter_dispatch_ready(2, 1, 0, 0, 0, 0, 1));
	CHECK(!swapz_window_submitter_dispatch_ready(2, 1, 0, 0, 0, 0, 64));
	return 0;
}

/*
 * Production bounds: one background preparation worker, at most eight
 * submitter lanes, 64 accepted BIOs per ordered quantum and a 64-slot window.
 * The lane claim itself is caller-owned; model its source-derived capacity
 * separately from queued-follower state before exercising the pure window
 * predicate. ENOSPC is likewise a caller-owned errno converted to blocked.
 */
static int test_bounded_queue_pressure_and_retry(void)
{
	struct swapz_pending_bio staged[SWAPZ_MAX_RECORDS] = { 0 };
	static const struct {
		unsigned int capacity;
		unsigned int in_use;
		int available;
	} lane_cases[] = {
		{ 0U, 0U, 0 },
		{ 1U, 0U, 1 },
		{ 1U, 1U, 0 },
		{ 8U, 0U, 1 },
		{ 8U, 7U, 1 },
		{ 8U, 8U, 0 },
	};
	const unsigned int queued_follower_counts[] = {
		0U, 1U, SWAPZ_MAX_RECORDS,
	};
	const swapz_u8 hand_counts[] = { 8U, 16U, SWAPZ_MAX_RECORDS };
	const unsigned long long first_ns = 1000000ULL;
	const unsigned long long deadline_ns =
		swapz_window_retention_deadline_ns(first_ns, 2U);
	unsigned int index, lane_index, queue_index, hand_index, count;
	int reserve_error = 0;

	for (index = 0; index < SWAPZ_MAX_RECORDS; ++index) {
		staged[index].logical = 1000U + index;
		/* Four compressed records exactly fit an 8KiB extent. */
		staged[index].length = 2028U;
	}
	CHECK(swapz_window_initial_burst_target(0) == 0);
	CHECK(swapz_window_initial_burst_target(1) == 1);
	CHECK(swapz_window_initial_burst_target(SWAPZ_MAX_RECORDS) == 4);
	CHECK(swapz_window_grow_burst_target(4, SWAPZ_MAX_RECORDS,
					SWAPZ_MAX_RECORDS, SWAPZ_MAX_RECORDS) ==
		SWAPZ_MAX_RECORDS);
	CHECK(!swapz_window_work_conserving_close_ready(
		2, 1, 1, 1, 0, 8, 0));
	CHECK(deadline_ns == 3000000ULL);
	CHECK(!swapz_window_deadline_expired(deadline_ns, deadline_ns - 1ULL));
	CHECK(swapz_window_deadline_expired(deadline_ns, deadline_ns));

	/* A full batch must be scanned, never truncated or indexed past 64. */
	CHECK(!swapz_window_read_independent(staged, SWAPZ_MAX_RECORDS,
						1000U + SWAPZ_MAX_RECORDS - 1U, 2, 0));
	CHECK(swapz_window_read_independent(staged, SWAPZ_MAX_RECORDS,
					       999U, 2, 0));
	CHECK(!swapz_window_read_independent(staged,
					SWAPZ_MAX_RECORDS + 1U, 999U, 2, 0));
	CHECK(!swapz_window_uniform_compressed(staged,
					SWAPZ_MAX_RECORDS + 1U));
	CHECK(!swapz_window_compressed_extent_fits(staged,
					SWAPZ_MAX_RECORDS + 1U, 2, 0, 4, 2));

	for (lane_index = 0; lane_index < sizeof(lane_cases) /
					      sizeof(lane_cases[0]); ++lane_index) {
		const unsigned int lane_capacity = lane_cases[lane_index].capacity;
		const unsigned int lanes_in_use = lane_cases[lane_index].in_use;
		const int lane_available = lane_cases[lane_index].available;

		CHECK_PRESSURE(lane_available ==
			(lane_capacity && lanes_in_use < lane_capacity),
			"submitter-lane", lane_capacity, lanes_in_use,
			0, 0, reserve_error);
		for (queue_index = 0;
		     queue_index < sizeof(queued_follower_counts) /
				   sizeof(queued_follower_counts[0]); ++queue_index) {
			const unsigned int queued_followers =
				queued_follower_counts[queue_index];
			const int helper_ready = swapz_window_submitter_dispatch_ready(
				2, 1, 0, 0, 0, 0, queued_followers);
			const int dispatch = lane_available && helper_ready;

			CHECK_PRESSURE(helper_ready == !queued_followers,
				"accepted-queue", lane_capacity, lanes_in_use,
				0, queued_followers, reserve_error);
			CHECK_PRESSURE(dispatch ==
				(lane_available && !queued_followers),
				"submitter-dispatch", lane_capacity, lanes_in_use,
				0, queued_followers, reserve_error);
		}
	}

	/* Timer queue state is independent of accepted-work queue occupancy. */
	CHECK_PRESSURE(swapz_retention_timer_needs_arm(2, 0),
		"retention-timer", 8, 0, 1, SWAPZ_MAX_RECORDS, reserve_error);
	CHECK_PRESSURE(!swapz_retention_timer_needs_arm(2, 1),
		"retention-timer", 8, 0, 1, 0, reserve_error);
	CHECK_PRESSURE(!swapz_retention_timer_needs_arm(0, 0),
		"retention-disabled", 8, 0, 1, 0, reserve_error);

	/* Foreground ENOSPC is a per-WRITE capacity result: it must not poison
	 * committed disjoint READs while the caller runs bounded GC/retry. A
	 * terminal lower-I/O error does set the caller's blocking failure state. */
	reserve_error = -ENOSPC;
	CHECK_PRESSURE(swapz_window_read_independent(
		staged, SWAPZ_MAX_RECORDS, 999U, 2, 0),
		"reserve-enospc-readable", 8, 0, SWAPZ_MAX_RECORDS, 0,
		reserve_error);
	reserve_error = -EIO;
	CHECK_PRESSURE(!swapz_window_read_independent(
		staged, SWAPZ_MAX_RECORDS, 999U, 2, 1),
		"terminal-error", 8, 0, SWAPZ_MAX_RECORDS, 0, reserve_error);
	reserve_error = 0;
	CHECK_PRESSURE(swapz_window_read_independent(
		staged, SWAPZ_MAX_RECORDS, 999U, 2, 0),
		"reserve-retry-readable", 8, 0, SWAPZ_MAX_RECORDS, 0,
		reserve_error);

	for (hand_index = 0;
	     hand_index < sizeof(hand_counts) / sizeof(hand_counts[0]);
	     ++hand_index) {
		int qualified_pack_seen = 0;
		const swapz_u8 hand = hand_counts[hand_index];

		for (count = 0; count <= SWAPZ_MAX_RECORDS; ++count) {
			const int next_local_is_plain_write =
				count < SWAPZ_MAX_RECORDS;
			const unsigned int queued_followers =
				next_local_is_plain_write ? 1U : 0U;
			int pressure_close;

			/* Production records current-admission geometry before testing
			 * worker close predicates. Preserve that order in the fixture. */
			if (count &&
			    swapz_window_pack_ready(staged, (swapz_u8)count, 2, 0))
				qualified_pack_seen = 1;
			pressure_close = swapz_window_work_conserving_close_ready(
				2, qualified_pack_seen, (swapz_u8)count,
				SWAPZ_MAX_RECORDS, 0, hand,
				next_local_is_plain_write);
			/* An accepted WRITE cannot split the learned 64-page wave
			 * before its target, even with a smaller pressure hand. */
			CHECK_PRESSURE(pressure_close ==
				(count == SWAPZ_MAX_RECORDS),
				"window-target", 8, 0, count,
				queued_followers, reserve_error);
			/* Once both accepted FIFOs are dry, a latched 4-page pack
			 * is finite work, rather than a wait for future arrivals. */
			CHECK_PRESSURE(swapz_window_work_conserving_close_ready(
				2, qualified_pack_seen, (swapz_u8)count,
				SWAPZ_MAX_RECORDS, 0, hand, 0) ==
				(count >= SWAPZ_WINDOW_DRY_PACK_MIN_RECORDS),
				"service-dry", 8, 0, count, 0, reserve_error);
			/* Neither a retry nor growing the staged batch can move the
			 * first-record deadline later. */
			CHECK_PRESSURE(swapz_window_retention_deadline_ns(
				first_ns, 2U) == deadline_ns,
				"retention-deadline", 8, 0, count,
				queued_followers, reserve_error);
		}
	}
	return 0;
}

int main(void)
{
	int passed = 0;

	CHECK(test_independent_compressed_and_raw() == 0); passed++;
	CHECK(test_every_pending_slot_fences_read() == 0); passed++;
	CHECK(test_disabled_empty_and_invalid_window() == 0); passed++;
	CHECK(test_caller_fences_override_independence() == 0); passed++;
	CHECK(test_pack_ready_waits_for_second_medium_pack() == 0); passed++;
	CHECK(test_pack_ready_small_and_medium_exact_geometry() == 0); passed++;
	CHECK(test_pack_ready_rejects_raw_and_unfittable() == 0); passed++;
	CHECK(test_pack_ready_uses_compressed_geometry_across_raw_slots() == 0); passed++;
	CHECK(test_retained_burst_target_adapts_from_finite_evidence() == 0); passed++;
	CHECK(test_sampled_tail_target_distinguishes_mixed_wave() == 0); passed++;
	CHECK(test_service_dry_pack_requires_valid_multi_record_pack() == 0); passed++;
	CHECK(test_post_pack_read_boundary_requires_fresh_finite_tail() == 0); passed++;
	CHECK(test_post_pack_boundary_observation_survives_pending_sample() == 0); passed++;
	CHECK(test_retained_burst_close_requires_geometry_or_sampled_tail() == 0); passed++;
	CHECK(test_raw_pressure_hand_requires_dispatchable_target() == 0); passed++;
	CHECK(test_work_conserving_close_respects_retained_target() == 0); passed++;
	CHECK(test_two_record_two_block_pack_geometry_survives_raw_slots() == 0); passed++;
	CHECK(test_timer_cancel_only_for_enabled_retention() == 0); passed++;
	CHECK(test_timer_arm_requires_retention_and_unqueued_timer() == 0); passed++;
	CHECK(test_ordinary_retention_deadline_is_pinned() == 0); passed++;
	CHECK(test_idle_bound_scales_with_lower_service() == 0); passed++;
	CHECK(test_effective_deadline_only_moves_earlier() == 0); passed++;
	CHECK(test_lower_service_ewma() == 0); passed++;
	CHECK(test_pure_write_half_burst_waits_for_learned_width() == 0); passed++;
	CHECK(test_raw_hand_pays_only_for_slow_compression() == 0); passed++;
	CHECK(test_uniform_compressed_identity_sort_safety() == 0); passed++;
	CHECK(test_section_wall_ns_never_underflows() == 0); passed++;
	CHECK(test_disabled_or_missing_timestamp_expires() == 0); passed++;
	CHECK(test_exact_nanosecond_deadline() == 0); passed++;
	CHECK(test_expiry_remains_pinned_after_later_arrivals() == 0); passed++;
	CHECK(test_backwards_clock_has_zero_age() == 0); passed++;
	CHECK(test_late_clock_does_not_wrap_remaining_budget() == 0); passed++;
	CHECK(test_submitter_dispatch_requires_proven_idle_singleton() == 0); passed++;
	CHECK(test_bounded_queue_pressure_and_retry() == 0); passed++;
	printf("SWAPZ_WINDOW_POLICY_TESTS_PASS=%d\n", passed);
	return 0;
}
