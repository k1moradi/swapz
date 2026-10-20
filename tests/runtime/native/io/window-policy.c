// SPDX-License-Identifier: GPL-2.0-only
/*
 * Execute the exact predicates included by the production DM worker.
 * These tests cover bounded slot dependencies and nanosecond expiry;
 * they do not emulate Linux BIO completion, timers or loaded lower I/O.
 */
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include "window-policy.h"

#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "%s:%d failed %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)

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
	/* Three medium pages fit 8KiB but are deliberately retained.
	 * Six fit one 16KiB extent: same bytes as two old 8KiB commits,
	 * one synchronous lower callback. */
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
	/* Two medium pages do not fit 4KiB. Three fit 8KiB, but wait for
	 * a second triplet instead of closing the first pack immediately. */
	CHECK(!swapz_window_single_pack_ready(batch, 2, 2, 0));
	CHECK(swapz_window_single_pack_ready(batch, 3, 2, 0));
	CHECK(!swapz_window_pack_ready(batch, 3, 2, 0));
	CHECK(swapz_window_pack_ready(batch, 6, 2, 0));

	/* Exact 4KiB two-record pack is deferred; two such packs close
	 * together at the exact 8KiB four-record metadata limit. */
	for (i = 0; i < 4; ++i)
		batch[i].length = 2028;
	batch[0].length = 2024;
	batch[1].length = 2024;
	CHECK(swapz_window_single_pack_ready(batch, 2, 2, 0));
	CHECK(!swapz_window_single_pack_ready(batch, 3, 2, 0));
	CHECK(!swapz_window_pack_ready(batch, 2, 2, 0));
	for (i = 0; i < 4; ++i)
		batch[i].length = 2028;
	CHECK(swapz_window_pack_ready(batch, 4, 2, 0));
	batch[3].length = 2029;
	CHECK(!swapz_window_pack_ready(batch, 4, 2, 0));

	/* Six records have 112 bytes of SWZ3 header/descriptor overhead:
	 * 6 * 2712 + 112 == 16384 exactly. */
	for (i = 0; i < 6; ++i)
		batch[i].length = 2712;
	CHECK(swapz_window_pack_ready(batch, 6, 2, 0));
	batch[5].length = 2713;
	CHECK(!swapz_window_pack_ready(batch, 6, 2, 0));
	batch[5].length = 2712;
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

static int test_ordinary_retention_deadline_is_pinned(void)
{
	const unsigned long long first = 1000000ULL;

	CHECK(swapz_window_retention_deadline_ns(first, 2) == 3000000ULL);
	CHECK(!swapz_window_deadline_expired(3000000ULL, 2999999ULL));
	CHECK(swapz_window_deadline_expired(3000000ULL, 3000000ULL));
	CHECK(swapz_window_retention_deadline_ns(first, 0) == 0);
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
	CHECK(test_retained_burst_target_adapts_from_finite_evidence() == 0); passed++;
	CHECK(test_retained_burst_close_requires_geometry_or_sampled_tail() == 0); passed++;
	CHECK(test_timer_cancel_only_for_enabled_retention() == 0); passed++;
	CHECK(test_timer_arm_requires_retention_and_unqueued_timer() == 0); passed++;
	CHECK(test_ordinary_retention_deadline_is_pinned() == 0); passed++;
	CHECK(test_uniform_compressed_identity_sort_safety() == 0); passed++;
	CHECK(test_section_wall_ns_never_underflows() == 0); passed++;
	CHECK(test_disabled_or_missing_timestamp_expires() == 0); passed++;
	CHECK(test_exact_nanosecond_deadline() == 0); passed++;
	CHECK(test_expiry_remains_pinned_after_later_arrivals() == 0); passed++;
	CHECK(test_backwards_clock_has_zero_age() == 0); passed++;
	CHECK(test_late_clock_does_not_wrap_remaining_budget() == 0); passed++;
	printf("SWAPZ_WINDOW_POLICY_TESTS_PASS=%d\n", passed);
	return 0;
}
