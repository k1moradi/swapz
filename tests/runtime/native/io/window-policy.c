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
	struct sv3_pending_bio pending[3] = {
		{ .logical = 7, .length = 2073 },
		{ .logical = 8, .length = SV3_BLOCK_BYTES, .raw = 1 },
		{ .logical = 9, .length = 256 },
	};
	struct sv3_pending_bio original[3];

	memcpy(original, pending, sizeof(original));
	CHECK(sv3_window_read_independent(pending, 3, 6, 2, 0));
	CHECK(sv3_window_read_independent(pending, 3, 10, 2, 0));
	CHECK(sv3_window_read_independent(pending, 3, 0, 2, 0));
	CHECK(sv3_window_read_independent(pending, 3, ~(sv3_u32)0, 2, 0));
	CHECK(!memcmp(pending, original, sizeof(pending)));
	return 0;
}

static int test_every_pending_slot_fences_read(void)
{
	struct sv3_pending_bio pending[SV3_MAX_RECORDS] = { 0 };
	sv3_u8 index;

	for (index = 0; index < SV3_MAX_RECORDS; ++index) {
		pending[index].logical = 100 + index;
		pending[index].raw = index & 1U;
		pending[index].length = pending[index].raw ?
			SV3_BLOCK_BYTES : 2073;
	}
	/* Check the first, middle and last slot, including RAW dependencies. */
	for (index = 0; index < SV3_MAX_RECORDS; ++index)
		CHECK(!sv3_window_read_independent(pending, SV3_MAX_RECORDS,
					pending[index].logical, 2, 0));
	CHECK(sv3_window_read_independent(pending, SV3_MAX_RECORDS,
					99, 2, 0));
	CHECK(sv3_window_read_independent(pending, SV3_MAX_RECORDS,
					100 + SV3_MAX_RECORDS, 2, 0));
	return 0;
}

static int test_disabled_empty_and_invalid_window(void)
{
	struct sv3_pending_bio pending = { .logical = 4, .length = 2073 };

	CHECK(!sv3_window_read_independent(&pending, 1, 5, 0, 0));
	CHECK(!sv3_window_read_independent(&pending, 0, 5, 2, 0));
	CHECK(!sv3_window_read_independent(NULL, 1, 5, 2, 0));
	/* Invalid count must be rejected before accessing any array element. */
	CHECK(!sv3_window_read_independent(&pending, SV3_MAX_RECORDS + 1,
					5, 2, 0));
	CHECK(!sv3_window_read_independent(NULL, SV3_MAX_RECORDS + 1,
					5, 2, 0));
	return 0;
}

static int test_caller_fences_override_independence(void)
{
	struct sv3_pending_bio pending = { .logical = 4, .length = 2073 };
	unsigned int fence;

	/* Each of shutdown, failure, inflight, batch publication and flags
	 * must block independently when the caller supplies its predicate. */
	for (fence = 1; fence <= 32; fence <<= 1)
		CHECK(!sv3_window_read_independent(&pending, 1, 5, 2,
						(int)fence));
	CHECK(!sv3_window_read_independent(&pending, 1, 5, 2, -1));
	CHECK(sv3_window_read_independent(&pending, 1, 5, 2, 0));
	return 0;
}

static int test_pack_ready_seven_medium_pages(void)
{
	struct sv3_pending_bio batch[8] = { 0 };
	unsigned int i;

	for (i = 0; i < 8; ++i) {
		batch[i].logical = 100 + i;
		batch[i].length = 2073;
	}
	/* 7*2073 + 16 + 7*16 = 14639B, inside one 16KiB extent. */
	CHECK(!sv3_window_pack_ready(batch, 6, 2, 0));
	CHECK(sv3_window_pack_ready(batch, 7, 2, 0));
	CHECK(!sv3_window_pack_ready(batch, 8, 2, 0));
	CHECK(!sv3_window_pack_ready(batch, 7, 0, 0));
	CHECK(!sv3_window_pack_ready(batch, 7, 2, 1));
	CHECK(!sv3_window_pack_ready(batch, 7, 2, 3));
	CHECK(!sv3_window_pack_ready(NULL, 7, 2, 0));
	return 0;
}

static int test_pack_ready_rejects_raw_and_unfittable(void)
{
	struct sv3_pending_bio batch[7] = { 0 };
	unsigned int i;

	for (i = 0; i < 7; ++i) {
		batch[i].logical = 200 + i;
		batch[i].length = 2073;
	}
	batch[4].raw = 1;
	batch[4].length = SV3_BLOCK_BYTES;
	CHECK(!sv3_window_pack_ready(batch, 7, 2, 0));
	batch[4].raw = 0;
	batch[4].length = 0;
	CHECK(!sv3_window_pack_ready(batch, 7, 2, 0));
	batch[4].length = SV3_MAX_COMPRESSED + 1;
	CHECK(!sv3_window_pack_ready(batch, 7, 2, 0));
	batch[4].length = SV3_MAX_COMPRESSED;
	CHECK(sv3_window_pack_ready(batch, 7, 2, 0));
	for (i = 0; i < 7; ++i)
		batch[i].length = SV3_MAX_COMPRESSED;
	CHECK(!sv3_window_pack_ready(batch, 7, 2, 0));
	for (i = 0; i < 7; ++i)
		batch[i].length = 2000;
	CHECK(sv3_window_pack_ready(batch, 7, 1, 0));
	/* Moving a short outlier does not make six 2800B pages fit. */
	for (i = 0; i < 7; ++i)
		batch[i].length = 2800;
	batch[6].length = 100;
	CHECK(!sv3_window_pack_ready(batch, 7, 2, 0));
	batch[6].length = 2800;
	batch[0].length = 100;
	CHECK(!sv3_window_pack_ready(batch, 7, 2, 0));
	return 0;
}

static int test_uniform_compressed_identity_sort_safety(void)
{
	struct sv3_pending_bio batch[SV3_MAX_RECORDS] = { 0 };
	struct sv3_pending_bio snapshot[SV3_MAX_RECORDS];
	sv3_u8 i;

	CHECK(!sv3_window_uniform_compressed(NULL, 1));
	CHECK(!sv3_window_uniform_compressed(batch, 0));
	CHECK(!sv3_window_uniform_compressed(batch, SV3_MAX_RECORDS + 1));
	for (i = 0; i < SV3_MAX_RECORDS; ++i) {
		batch[i].logical = 100 + i;
		batch[i].length = 2073;
	}
	memcpy(snapshot, batch, sizeof(batch));
	CHECK(sv3_window_uniform_compressed(batch, 1));
	CHECK(sv3_window_uniform_compressed(batch, 7));
	CHECK(sv3_window_uniform_compressed(batch, SV3_MAX_RECORDS));
	CHECK(!memcmp(batch, snapshot, sizeof(batch)));
	batch[SV3_MAX_RECORDS - 1].length = 2072;
	CHECK(!sv3_window_uniform_compressed(batch, SV3_MAX_RECORDS));
	CHECK(sv3_window_uniform_compressed(batch, 7));
	batch[SV3_MAX_RECORDS - 1].length = 2073;
	batch[0].raw = 1;
	CHECK(!sv3_window_uniform_compressed(batch, 7));
	batch[0].raw = 0;
	batch[3].raw = 1;
	CHECK(!sv3_window_uniform_compressed(batch, 7));
	batch[3].raw = 0;
	batch[2].length = 0;
	CHECK(!sv3_window_uniform_compressed(batch, 7));
	batch[2].length = 2073;
	batch[0].length = SV3_MAX_COMPRESSED + 1U;
	CHECK(!sv3_window_uniform_compressed(batch, 7));
	/* Tiny uniform compressed payloads may pair into a 4KiB block;
	 * the greedy ordering is still first-then-next, i.e. identity. */
	for (i = 0; i < SV3_MAX_RECORDS; ++i)
		batch[i].length = 500;
	CHECK(sv3_window_uniform_compressed(batch, 8));
	/* RAW controls and mixed entropy retain the greedy fallback. */
	batch[4].length = SV3_BLOCK_BYTES;
	batch[4].raw = 1;
	CHECK(!sv3_window_uniform_compressed(batch, 8));
	return 0;
}

static int test_timer_cancel_only_for_enabled_retention(void)
{
	unsigned int retain;

	CHECK(!sv3_window_timer_enabled(0));
	for (retain = 1; retain <= 4; ++retain)
		CHECK(sv3_window_timer_enabled((sv3_u8)retain));
	return 0;
}

static int test_timer_rearm_requires_retention_and_unqueued_timer(void)
{
	unsigned int retain;

	CHECK(!sv3_retention_timer_needs_arm(0, 0));
	CHECK(!sv3_retention_timer_needs_arm(0, 1));
	for (retain = 1; retain <= 4; ++retain) {
		CHECK(sv3_retention_timer_needs_arm((sv3_u8)retain, 0));
		CHECK(!sv3_retention_timer_needs_arm((sv3_u8)retain, 1));
	}
	/* A dequeued/expired timer may be rearmed to the SAME original
	 * deadline; it will promptly dispatch the worker if overdue. */
	CHECK(sv3_retention_timer_needs_arm(2, 0));
	return 0;
}

static int test_inline_drain_respects_finite_budget_and_shutdown(void)
{
	unsigned int left;

	CHECK(!sv3_worker_can_inline_drain(0, 1));
	CHECK(!sv3_worker_can_inline_drain(0, 0));
	CHECK(!sv3_worker_can_inline_drain(1, 0));
	CHECK(!sv3_worker_can_inline_drain(64, 0));
	for (left = 1; left <= 64; ++left)
		CHECK(sv3_worker_can_inline_drain(left, 1));
	/* A completed 64th BIO must yield to the workqueue even when
	 * more BIOs arrive; an unfinished 63-BIO mini-wave may drain. */
	CHECK(sv3_worker_can_inline_drain(1, 1));
	CHECK(!sv3_worker_can_inline_drain(0, 1));
	return 0;
}

static int test_section_wall_ns_never_underflows(void)
{
	CHECK(sv3_elapsed_ns(100, 170) == 70ULL);
	CHECK(sv3_elapsed_ns(100, 100) == 0ULL);
	CHECK(sv3_elapsed_ns(170, 100) == 0ULL);
	CHECK(sv3_elapsed_ns(0, ULLONG_MAX) == ULLONG_MAX);
	CHECK(sv3_elapsed_ns(ULLONG_MAX, 0) == 0ULL);
	return 0;
}

static int test_disabled_or_missing_timestamp_expires(void)
{
	CHECK(sv3_window_retention_expired(1000, 1000, 0));
	CHECK(sv3_window_retention_expired(0, 0, 2));
	CHECK(sv3_window_retention_expired(0, 1000, 2));
	return 0;
}

static int test_exact_nanosecond_deadline(void)
{
	const unsigned long long first = 123456789ULL;
	sv3_u8 retain;

	for (retain = 1; retain <= 4; ++retain) {
		unsigned long long deadline = first +
			(unsigned long long)retain * 1000000ULL;

		CHECK(!sv3_window_retention_expired(first, first, retain));
		CHECK(!sv3_window_retention_expired(first, deadline - 1, retain));
		CHECK(sv3_window_retention_expired(first, deadline, retain));
		CHECK(sv3_window_retention_expired(first, deadline + 1, retain));
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
		CHECK(!sv3_window_retention_expired(first, arrivals[index], 2));
	CHECK(sv3_window_retention_expired(first, 3000000ULL, 2));
	CHECK(sv3_window_retention_expired(first, 3000001ULL, 2));
	CHECK(sv3_window_retention_expired(first, 6000000ULL, 2));
	return 0;
}

static int test_backwards_clock_has_zero_age(void)
{
	CHECK(!sv3_window_retention_expired(3000000ULL, 2999999ULL, 2));
	CHECK(!sv3_window_retention_expired(3000000ULL, 0, 2));
	CHECK(!sv3_window_retention_expired(ULLONG_MAX, 1, 2));
	return 0;
}

static int test_late_clock_does_not_wrap_remaining_budget(void)
{
	const unsigned long long first = 1;

	/* The alpha.11 second clock sample could cross expiry and underflow
	 * budget-age. Every sample at or after expiry must remain expired. */
	CHECK(!sv3_window_retention_expired(first, 2000000ULL, 2));
	CHECK(sv3_window_retention_expired(first, 2000001ULL, 2));
	CHECK(sv3_window_retention_expired(first, 2000002ULL, 2));
	CHECK(sv3_window_retention_expired(first, ULLONG_MAX, 2));
	CHECK(!sv3_window_retention_expired(ULLONG_MAX - 2000000ULL,
					ULLONG_MAX - 1, 2));
	CHECK(sv3_window_retention_expired(ULLONG_MAX - 2000000ULL,
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
	CHECK(test_pack_ready_seven_medium_pages() == 0); passed++;
	CHECK(test_pack_ready_rejects_raw_and_unfittable() == 0); passed++;
	CHECK(test_timer_cancel_only_for_enabled_retention() == 0); passed++;
	CHECK(test_timer_rearm_requires_retention_and_unqueued_timer() == 0); passed++;
	CHECK(test_uniform_compressed_identity_sort_safety() == 0); passed++;
	CHECK(test_inline_drain_respects_finite_budget_and_shutdown() == 0); passed++;
	CHECK(test_section_wall_ns_never_underflows() == 0); passed++;
	CHECK(test_disabled_or_missing_timestamp_expires() == 0); passed++;
	CHECK(test_exact_nanosecond_deadline() == 0); passed++;
	CHECK(test_expiry_remains_pinned_after_later_arrivals() == 0); passed++;
	CHECK(test_backwards_clock_has_zero_age() == 0); passed++;
	CHECK(test_late_clock_does_not_wrap_remaining_budget() == 0); passed++;
	printf("SV3_WINDOW_POLICY_TESTS_PASS=%d\n", passed);
	return 0;
}
