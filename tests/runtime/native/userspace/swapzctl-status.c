// SPDX-License-Identifier: GPL-2.0-only
#define main swapzctl_program_main
#include "../../../../src/userspace/swapzctl.c"
#undef main

#include <assert.h>
#include <stdio.h>

static void test_mixed_foreground_ratio_excludes_gc(void)
{
	const char *status =
		"physical_write_reqs=99 logical_write=32768 physical_write=20480 "
		"compressed=4 raw=2 zero_elided=2 gc_write=4096 "
		"bulk_mode=1 bulk_padding=0 failed=0";
	struct swapz_ratio_status ratio;

	assert(parse_swapz_ratio_status(status, &ratio) == 0);
	assert(ratio.compressed_logical_bytes == 16384ULL);
	assert(ratio.compressed_extent_bytes == 8192ULL);
	assert(ratio.overall_physical_bytes == 16384ULL);
	assert(ratio.compressed_extent_ratio_exact == 1);
}

static void test_raw_only_ratio(void)
{
	const char *status =
		"logical_write=8192 physical_write=8192 gc_write=0 "
		"compressed=0 raw=2 zero_elided=0 bulk_mode=1 bulk_padding=0 failed=0";
	struct swapz_ratio_status ratio;

	assert(parse_swapz_ratio_status(status, &ratio) == 0);
	assert(ratio.compressed_logical_bytes == 0ULL);
	assert(ratio.compressed_extent_bytes == 0ULL);
	assert(ratio.overall_physical_bytes == 8192ULL);
}

static void test_zero_elision_increases_overall_ratio(void)
{
	const char *status =
		"logical_write=16384 physical_write=4096 gc_write=0 "
		"compressed=1 raw=0 zero_elided=3 bulk_mode=1 bulk_padding=0 failed=0";
	struct swapz_ratio_status ratio;

	assert(parse_swapz_ratio_status(status, &ratio) == 0);
	assert(ratio.compressed_extent_bytes == 4096ULL);
	assert(ratio.overall_physical_bytes == 4096ULL);
}

static void test_zero_only_overall_ratio_has_no_lower_bytes(void)
{
	const char *status =
		"logical_write=12288 physical_write=0 gc_write=0 "
		"compressed=0 raw=0 zero_elided=3 bulk_mode=1 bulk_padding=0 failed=0";
	struct swapz_ratio_status ratio;

	assert(parse_swapz_ratio_status(status, &ratio) == 0);
	assert(ratio.overall_physical_bytes == 0ULL);
	assert(ratio.compressed_extent_bytes == 0ULL);
}

static void test_padding_refuses_compressed_extent_estimate(void)
{
	const char *status =
		"logical_write=16384 physical_write=12288 gc_write=0 "
		"compressed=4 raw=0 zero_elided=0 bulk_mode=2 bulk_padding=1 failed=0";
	struct swapz_ratio_status ratio;

	assert(parse_swapz_ratio_status(status, &ratio) == 0);
	assert(ratio.compressed_extent_ratio_exact == 0);
	assert(ratio.overall_physical_bytes == 12288ULL);
}

static void test_inconsistent_live_snapshot_retries(void)
{
	const char *status =
		"logical_write=12288 physical_write=8192 gc_write=0 "
		"compressed=4 raw=0 zero_elided=0 bulk_mode=1 bulk_padding=0 failed=0";
	struct swapz_ratio_status ratio;

	assert(parse_swapz_ratio_status(status, &ratio) == 1);
}

static void test_missing_or_overflowing_fields_fail(void)
{
	struct swapz_ratio_status ratio;

	assert(parse_swapz_ratio_status(
		"logical_write=0 physical_write=0 compressed=0 raw=0 "
		"zero_elided=0 bulk_mode=1 bulk_padding=0 failed=0", &ratio) == -1);
	assert(parse_swapz_ratio_status(
		"logical_write=0 physical_write=0 gc_write=0 "
		"compressed=18446744073709551616 raw=0 zero_elided=0 "
		"bulk_mode=1 bulk_padding=0 failed=0", &ratio) == -1);
}

static void test_failed_target_refuses_ratio(void)
{
	const char *status =
		"logical_write=4096 physical_write=8192 gc_write=0 "
		"compressed=1 raw=0 zero_elided=0 bulk_mode=1 bulk_padding=0 failed=1";
	struct swapz_ratio_status ratio;

	assert(parse_swapz_ratio_status(status, &ratio) == 2);
	assert(ratio.failed == 1ULL);
}

static void test_ratio_snapshot_equality_covers_all_inputs(void)
{
	const char *status =
		"logical_write=8192 physical_write=4096 gc_write=0 "
		"compressed=2 raw=0 zero_elided=0 bulk_mode=1 bulk_padding=0 failed=0";
	struct swapz_ratio_status first;
	struct swapz_ratio_status second;

	assert(parse_swapz_ratio_status(status, &first) == 0);
	second = first;
	assert(ratio_status_equal(&first, &second));
	second.physical_write_bytes += 4096ULL;
	assert(!ratio_status_equal(&first, &second));
}

int main(void)
{
	test_mixed_foreground_ratio_excludes_gc();
	test_raw_only_ratio();
	test_zero_elision_increases_overall_ratio();
	test_zero_only_overall_ratio_has_no_lower_bytes();
	test_padding_refuses_compressed_extent_estimate();
	test_inconsistent_live_snapshot_retries();
	test_missing_or_overflowing_fields_fail();
	test_failed_target_refuses_ratio();
	test_ratio_snapshot_equality_covers_all_inputs();
	puts("PASS: swapzctl status compression-ratio accounting");
	return 0;
}
