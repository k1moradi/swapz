// SPDX-License-Identifier: GPL-2.0-only
/* Pure ID178 accounting checks: no privileged device or BIO simulation. */
#include <inttypes.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include "lane-gap.h"
#define CHECK(condition) do { if (!(condition)) { \
	fprintf(stderr, "%s:%d failed %s\n", __FILE__, __LINE__, #condition); \
	return 1; } } while (0)
static swapz_u64 sum(const struct swapz_lane_gap_parts *part)
{
	return part->completion_wake_ns + part->publication_ns +
		part->no_work_ns + part->admitted_unowned_ns +
		part->staged_held_ns + part->seal_ns;
}
static int test_partitions(void)
{
	struct swapz_lane_gap_parts part = { 0 };
	swapz_u64 observed, published, admitted, owned, seal;
	unsigned int cases = 0;

	CHECK(swapz_lane_gap_partition(100, 110, 120, 130, 140, 150, 160, &part));
	CHECK(part.completion_wake_ns == 10 && part.publication_ns == 10);
	CHECK(part.no_work_ns == 10 && part.admitted_unowned_ns == 10);
	CHECK(part.staged_held_ns == 10 && part.seal_ns == 10);
	CHECK(sum(&part) == 60);
	CHECK(swapz_lane_gap_partition(100, 105, 110, 20, 50, 80, 130, &part));
	CHECK(part.no_work_ns == 0 && part.admitted_unowned_ns == 0);
	CHECK(part.staged_held_ns == 0 && part.seal_ns == 20);
	CHECK(swapz_lane_gap_partition(100, 120, 125, 130, 90, 95, 145, &part));
	CHECK(part.no_work_ns == 5 && part.admitted_unowned_ns == 0);
	CHECK(part.staged_held_ns == 0 && part.seal_ns == 15);
	CHECK(swapz_lane_gap_partition(100, 110, 140, 105, 107, 108, 150, &part));
	CHECK(part.no_work_ns == 0 && part.seal_ns == 10);
	for (observed = 98; observed <= 106; ++observed)
	for (published = 98; published <= 106; ++published)
	for (admitted = 98; admitted <= 106; ++admitted)
	for (owned = 98; owned <= 106; ++owned)
	for (seal = 98; seal <= 106; ++seal) {
		CHECK(swapz_lane_gap_partition(100, observed, published,
			admitted, owned, seal, 104, &part));
		CHECK(sum(&part) == 4);
		cases++;
	}
	CHECK(cases == 59049);
	return 0;
}
/* Rejected samples must never partially rewrite an earlier valid partition. */
static int parts_unchanged(const struct swapz_lane_gap_parts *observed,
			   const struct swapz_lane_gap_parts *expected,
			   const char *phase, swapz_u64 completion_ns,
			   swapz_u64 submit_ns)
{
	const struct {
		const char *name;
		swapz_u64 expected;
		swapz_u64 observed;
	} fields[] = {
		{ "completion_wake", expected->completion_wake_ns,
			observed->completion_wake_ns },
		{ "publication", expected->publication_ns,
			observed->publication_ns },
		{ "no_work", expected->no_work_ns, observed->no_work_ns },
		{ "admitted_unowned", expected->admitted_unowned_ns,
			observed->admitted_unowned_ns },
		{ "staged_held", expected->staged_held_ns,
			observed->staged_held_ns },
		{ "seal", expected->seal_ns, observed->seal_ns },
	};
	unsigned int index;

	for (index = 0; index < sizeof(fields) / sizeof(fields[0]); ++index) {
		if (fields[index].expected == fields[index].observed)
			continue;
		fprintf(stderr, "phase=%s completion_ns=%" PRIu64
			" submit_ns=%" PRIu64 " field=%s expected=%" PRIu64
			" observed=%" PRIu64 " exit_code=1\n", phase,
			completion_ns, submit_ns, fields[index].name,
			fields[index].expected, fields[index].observed);
		return 0;
	}
	return 1;
}
static int test_invalid(void)
{
	const struct swapz_lane_gap_parts retained = {
		.completion_wake_ns = 101,
		.publication_ns = 102,
		.no_work_ns = 103,
		.admitted_unowned_ns = 104,
		.staged_held_ns = 105,
		.seal_ns = 987,
	};
	struct swapz_lane_gap_parts part = retained;
	swapz_u64 marks[] = { 100, 101, 102, 103, 104, 105, 106 };
	unsigned int index;

	CHECK(!swapz_lane_gap_partition(100, 101, 102, 103, 104, 105, 99, &part));
	CHECK(parts_unchanged(&part, &retained, "reversed-endpoints", 100, 99));
	CHECK(!swapz_lane_gap_partition(100, 101, 102, 103, 104, 105, 106, NULL));
	CHECK(parts_unchanged(&part, &retained, "null-output", 100, 106));
	for (index = 0; index < 7; ++index) {
		swapz_u64 saved = marks[index];

		marks[index] = 0;
		CHECK(!swapz_lane_gap_partition(marks[0], marks[1], marks[2],
			marks[3], marks[4], marks[5], marks[6], &part));
		CHECK(parts_unchanged(&part, &retained, "zero-mark",
					marks[0], marks[6]));
		marks[index] = saved;
	}
	CHECK(swapz_lane_gap_partition(100, 101, 102, 103, 104, 105, 100, &part));
	CHECK(sum(&part) == 0);
	return 0;
}
static int test_bins(void)
{
	static const unsigned int successor_input[] =
		{0, 1, 2, 3, 4, 7, 8, 15, 16, 1024};
	static const unsigned int successor_bin[] =
		{0, 1, 2, 2, 3, 3, 4, 4, 5, 5};
	static const swapz_u64 dwell_input[] =
		{0, 999, 1000, 1001, 4000, 4001, 16000, 16001,
		 64000, 64001, 256000, 256001, 1000000, 1000001, UINT64_MAX};
	static const unsigned int dwell_bin[] =
		{0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6};
	unsigned int index;

	for (index = 0; index < sizeof(successor_input)/sizeof(successor_input[0]);
	     ++index)
		CHECK(swapz_lane_gap_successor_bin(successor_input[index]) ==
			successor_bin[index]);
	for (index = 0; index < sizeof(dwell_input)/sizeof(dwell_input[0]);
	     ++index)
		CHECK(swapz_lane_gap_dwell_bin(dwell_input[index]) ==
			dwell_bin[index]);
	return 0;
}
/* Production successor counts are bounded by the 64-record submitted run. */
static int test_extreme_timestamps_and_successor_counts(void)
{
	struct swapz_lane_gap_parts part = { .seal_ns = 987 };
	const unsigned int successor_counts[] = { 0U, 1U, 8U, 64U };
	unsigned int index;

	CHECK(swapz_lane_gap_partition(1, UINT64_MAX, UINT64_MAX,
		UINT64_MAX, UINT64_MAX, UINT64_MAX, UINT64_MAX, &part));
	CHECK(part.completion_wake_ns == UINT64_MAX - 1U);
	CHECK(part.publication_ns == 0 && part.seal_ns == 0);
	CHECK(sum(&part) == UINT64_MAX - 1U);
	CHECK(swapz_lane_gap_partition(UINT64_MAX - 1U, 1, 1, 1, 1,
		1, UINT64_MAX, &part));
	CHECK(part.completion_wake_ns == 0 && part.seal_ns == 1);
	CHECK(sum(&part) == 1);
	CHECK(swapz_lane_gap_partition(UINT64_MAX, 1, 1, 1, 1, 1,
		UINT64_MAX, &part));
	CHECK(sum(&part) == 0);
	{
		const struct swapz_lane_gap_parts retained = part;

		CHECK(!swapz_lane_gap_partition(UINT64_MAX, 1, 1, 1, 1, 1,
			UINT64_MAX - 1U, &part));
		CHECK(parts_unchanged(&part, &retained, "reversed-u64",
					UINT64_MAX, UINT64_MAX - 1U));
	}
	CHECK(sum(&part) == 0);

	for (index = 0; index < sizeof(successor_counts) /
					 sizeof(successor_counts[0]); ++index)
		CHECK(swapz_lane_gap_successor_bin(successor_counts[index]) <
			SWAPZ_LANE_SUCCESSOR_BINS);
	/* Keep the total helper defined even for a defensive out-of-contract count. */
	CHECK(swapz_lane_gap_successor_bin(UINT_MAX) <
		SWAPZ_LANE_SUCCESSOR_BINS);
	CHECK(swapz_lane_gap_dwell_bin(UINT64_MAX) <
		SWAPZ_LANE_DWELL_BINS);
	return 0;
}
int main(void)
{
	if (test_partitions() || test_invalid() || test_bins() ||
	    test_extreme_timestamps_and_successor_counts())
		return 1;
	puts("PASS lane-gap: 59049 timestamp grids, invalids, successor and 64-bit edges");
	return 0;
}
