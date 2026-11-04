// SPDX-License-Identifier: GPL-2.0-only
#define main swapzctl_program_main
#include "../../../../src/userspace/swapzctl.c"
#undef main

#include <assert.h>
#include <stdio.h>

static int parse_swapz_ratio_status(const char *status,
				    struct swapz_ratio_status *ratio)
{
	struct status_problem problem;

	return parse_swapz_ratio_status_diagnostic(status, ratio, &problem);
}

static void test_mixed_foreground_ratio_excludes_gc(void)
{
	const char *status =
		"physical_write_reqs=99 logical_write=32768 physical_write=20480 "
		"compressed=4 raw=2 zero_elided=2 gc_write=4096 "
		"bulk_mode=1 bulk_padding=0 failed=0 error=0";
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
		"compressed=0 raw=2 zero_elided=0 bulk_mode=1 bulk_padding=0 failed=0 error=0";
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
		"compressed=1 raw=0 zero_elided=3 bulk_mode=1 bulk_padding=0 failed=0 error=0";
	struct swapz_ratio_status ratio;

	assert(parse_swapz_ratio_status(status, &ratio) == 0);
	assert(ratio.compressed_extent_bytes == 4096ULL);
	assert(ratio.overall_physical_bytes == 4096ULL);
}

static void test_zero_only_overall_ratio_has_no_lower_bytes(void)
{
	const char *status =
		"logical_write=12288 physical_write=0 gc_write=0 "
		"compressed=0 raw=0 zero_elided=3 bulk_mode=1 bulk_padding=0 failed=0 error=0";
	struct swapz_ratio_status ratio;

	assert(parse_swapz_ratio_status(status, &ratio) == 0);
	assert(ratio.overall_physical_bytes == 0ULL);
	assert(ratio.compressed_extent_bytes == 0ULL);
}

static void test_padding_refuses_compressed_extent_estimate(void)
{
	const char *status =
		"logical_write=16384 physical_write=12288 gc_write=0 "
		"compressed=4 raw=0 zero_elided=0 bulk_mode=2 bulk_padding=1 failed=0 error=0";
	const char *raw_with_padding =
		"logical_write=4096 physical_write=8192 gc_write=0 "
		"compressed=0 raw=1 zero_elided=0 bulk_mode=2 bulk_padding=1 failed=0 error=0";
	struct swapz_ratio_status ratio;
	struct status_problem problem;

	assert(parse_swapz_ratio_status(status, &ratio) == STATUS_READY);
	assert(ratio.compressed_extent_ratio_exact == 0);
	assert(ratio.compressed_extent_bytes == 0ULL);
	assert(ratio.overall_physical_bytes == 12288ULL);
	assert(parse_swapz_ratio_status(raw_with_padding, &ratio) == STATUS_READY);
	assert(ratio.compressed_extent_ratio_exact == 0);
	assert(ratio.compressed_extent_bytes == 0ULL);
	assert(ratio.overall_physical_bytes == 8192ULL);
	assert(parse_swapz_ratio_status_diagnostic(
		"logical_write=0 physical_write=4096 gc_write=0 "
		"compressed=0 raw=0 zero_elided=0 bulk_mode=1 bulk_padding=1 "
		"failed=0 error=0",
		&ratio, &problem) == STATUS_BLOCKED);
	assert(!strcmp(problem.field, "bulk_padding"));
	assert(strstr(problem.observed, "non-padding mode"));
}

static void test_inconsistent_live_snapshot_retries(void)
{
	const char *status =
		"logical_write=12288 physical_write=8192 gc_write=0 "
		"compressed=4 raw=0 zero_elided=0 bulk_mode=1 bulk_padding=0 failed=0 error=0";
	struct swapz_ratio_status ratio;

	assert(parse_swapz_ratio_status(status, &ratio) == 1);
}

static void test_missing_or_overflowing_fields_fail(void)
{
	struct swapz_ratio_status ratio;

	assert(parse_swapz_ratio_status(
		"logical_write=0 physical_write=0 compressed=0 raw=0 "
		"zero_elided=0 bulk_mode=1 bulk_padding=0 failed=0 error=0", &ratio) == -1);
	assert(parse_swapz_ratio_status(
		"logical_write=0 physical_write=0 gc_write=0 "
		"compressed=18446744073709551616 raw=0 zero_elided=0 "
		"bulk_mode=1 bulk_padding=0 failed=0 error=0", &ratio) == -1);
}

static void test_failed_target_refuses_ratio(void)
{
	const char *status =
		"logical_write=4096 physical_write=8192 gc_write=0 "
		"compressed=1 raw=0 zero_elided=0 bulk_mode=1 bulk_padding=0 failed=1 error=-5";
	struct swapz_ratio_status ratio;

	assert(parse_swapz_ratio_status(status, &ratio) == 2);
	assert(ratio.failed == 1ULL);
}

static void test_ratio_snapshot_equality_covers_all_inputs(void)
{
	const char *status =
		"logical_write=8192 physical_write=4096 gc_write=0 "
		"compressed=2 raw=0 zero_elided=0 bulk_mode=1 bulk_padding=0 failed=0 error=0";
	struct swapz_ratio_status first;
	struct swapz_ratio_status second;

	assert(parse_swapz_ratio_status(status, &first) == 0);
	second = first;
	assert(ratio_status_equal(&first, &second));
	second.physical_write_bytes += 4096ULL;
	assert(!ratio_status_equal(&first, &second));
}

static const char *const fixture_valid_status =
	"logical_write=8192 physical_write=4096 gc_write=0 "
	"compressed=2 raw=0 zero_elided=0 bulk_mode=1 bulk_padding=0 "
	"failed=0 error=0";

static void assert_status_problem(const char *status, int expected_result,
				  const char *field, const char *condition)
{
	struct swapz_ratio_status ratio;
	struct status_problem problem = { 0 };

	assert(parse_swapz_ratio_status_diagnostic(status, &ratio, &problem) ==
	       expected_result);
	assert(problem.field && !strcmp(problem.field, field));
	if (!problem.observed || !strstr(problem.observed, condition))
		fprintf(stderr,
			"status diagnostic mismatch: field=%s expected=%s observed=%s\n",
			problem.field ? problem.field : "(null)", condition,
			problem.observed ? problem.observed : "(null)");
	assert(problem.observed && strstr(problem.observed, condition));
}

static void test_required_tokens_duplicates_and_canonical_numbers(void)
{
	const char *reordered =
		"error=0 raw=1 bulk_padding=0 logical_write=12288 "
		"zero_elided=1 failed=0 physical_write=8192 compressed=1 "
		"bulk_mode=1 gc_write=0 ignored_future_counter=7";
	struct swapz_ratio_status ratio;

	assert(parse_swapz_ratio_status(reordered, &ratio) == STATUS_READY);
	assert(ratio.logical_write_bytes == 12288ULL);
	assert(ratio.overall_physical_bytes == 8192ULL);
	assert(ratio.compressed_extent_bytes == 4096ULL);
	assert_status_problem("failed=0 error=0 logical_write=0", STATUS_BLOCKED,
			      "physical_write", "missing");
	assert_status_problem(
		"failed=0 error=0 logical_write=0 logical_write=0",
		STATUS_BLOCKED, "logical_write", "duplicate");
	assert_status_problem(
		"failed=0 error=0 logical_write=garbage logical_write=0",
		STATUS_BLOCKED, "logical_write", "duplicate");
	assert_status_problem(
		"failed=0 error=0 logical_write=01",
		STATUS_BLOCKED, "logical_write", "noncanonical");
	assert_status_problem(
		"failed=0 error=0 logical_write=-1",
		STATUS_BLOCKED, "logical_write", "signed");
	assert_status_problem(
		"failed=0 error=0 logical_write=18446744073709551616",
		STATUS_BLOCKED, "logical_write", "out-of-range");
	assert_status_problem(
		"failed=0 error=0 logical_write",
		STATUS_BLOCKED, "logical_write", "no '='");
	assert_status_problem(
		"failed=2 error=0", STATUS_BLOCKED, "failed", "out-of-range");
	assert_status_problem(
		"failed=0 error=+1", STATUS_BLOCKED, "error", "positive");
	assert_status_problem(
		"failed=0 error=-0", STATUS_BLOCKED, "error", "noncanonical");
	assert_status_problem(
		"failed=0 error=-4096", STATUS_BLOCKED, "error", "out-of-range");
	assert_status_problem(
		"failed=0 error=-5", STATUS_FAILED, "error", "negative kernel");
	assert_status_problem(
		"failed=1", STATUS_FAILED, "failed", "kernel target is failed");
	assert_status_problem(
		"status_snapshot_error=-12", STATUS_UNAVAILABLE,
		"status_snapshot_error", "kernel could not produce");
	assert_status_problem(
		"status_snapshot_error=3", STATUS_BLOCKED,
		"status_snapshot_error", "positive");
	assert_status_problem(
		"status_snapshot_error=0", STATUS_BLOCKED,
		"status_snapshot_error", "zero is not");
	assert_status_problem(
		"failed=0 error=0 logical_write=0 physical_write=0 gc_write=0 "
		"compressed=0 raw=0 zero_elided=0 bulk_mode=3 bulk_padding=0",
		STATUS_BLOCKED, "bulk_mode", "out-of-range");
	assert_status_problem(
		"failed=0 error=0 logical_write=0 physical_write=0 gc_write=0 "
		"compressed=0 raw=0 zero_elided=0 bulk_mode=2 bulk_padding=4294967296",
		STATUS_BLOCKED, "bulk_padding", "out-of-range");
}

static void test_checked_counter_arithmetic(void)
{
	assert_status_problem(
		"failed=0 error=0 logical_write=0 physical_write=0 gc_write=0 "
		"compressed=18446744073709551615 raw=1 zero_elided=0 "
		"bulk_mode=1 bulk_padding=0",
		STATUS_BLOCKED, "compressed+raw+zero_elided", "addition overflow");
	assert_status_problem(
		"failed=0 error=0 logical_write=0 physical_write=0 gc_write=0 "
		"compressed=4503599627370496 raw=0 zero_elided=0 "
		"bulk_mode=1 bulk_padding=0",
		STATUS_BLOCKED, "compressed+raw+zero_elided", "multiplication overflow");
	assert_status_problem(
		"failed=0 error=0 logical_write=8192 physical_write=0 gc_write=1 "
		"compressed=2 raw=0 zero_elided=0 bulk_mode=1 bulk_padding=0",
		STATUS_RETRY, "gc_write", "exceed");
	assert_status_problem(
		"failed=0 error=0 logical_write=8192 physical_write=2048 gc_write=0 "
		"compressed=1 raw=1 zero_elided=0 bulk_mode=1 bulk_padding=0",
		STATUS_RETRY, "physical_write-gc_write", "smaller");
	assert_status_problem(
		"failed=0 error=0 logical_write=4096 physical_write=0 gc_write=0 "
		"compressed=1 raw=0 zero_elided=0 bulk_mode=1 bulk_padding=0",
		STATUS_RETRY, "physical_write-gc_write-raw*4096",
		"no lower bytes remain for committed compressed pages");
}

static size_t fixture_align_target_offset(size_t value)
{
	size_t aligned = 0;

	assert(status_align_target_offset(value, &aligned) == 0);
	return aligned;
}

/* Construct real absolute DM_TABLE_STATUS offsets without touching a mapper. */
static size_t make_dm_multi_fixture(
	unsigned char *buffer, size_t capacity, const char *const *types,
	const char *const *parameters, const int *target_status,
	size_t count, uint64_t device_id)
{
	struct dm_ioctl header = { 0 };
	size_t next_offset = 0;
	size_t used_end = 0;
	size_t target;

	assert(count <= SWAPZ_STATUS_MAX_TARGETS);
	assert(capacity >= sizeof(header));
	memset(buffer, 0, capacity);
	for (target = 0; target < count; ++target) {
		struct dm_target_spec specification = { 0 };
		size_t status_bytes = strlen(parameters[target]) + 1U;

		used_end = next_offset + sizeof(specification) + status_bytes;
		assert(used_end <= capacity - sizeof(header));
		assert(strlen(types[target]) < sizeof(specification.target_type));
		specification.sector_start = (uint64_t)target * 1024U;
		specification.length = 1024U;
		specification.status = target_status ? target_status[target] : 0;
		specification.next = (uint32_t)fixture_align_target_offset(used_end);
		memcpy(specification.target_type, types[target], strlen(types[target]) + 1U);
		memcpy(buffer + sizeof(header) + next_offset,
		       &specification, sizeof(specification));
		memcpy(buffer + sizeof(header) + next_offset + sizeof(specification),
		       parameters[target], status_bytes);
		next_offset = specification.next;
		assert(next_offset <= capacity - sizeof(header));
	}
	header.data_start = sizeof(header);
	header.data_size = (uint32_t)(sizeof(header) + used_end);
	header.target_count = (uint32_t)count;
	header.dev = device_id;
	memcpy(header.name, "fixture", sizeof("fixture"));
	memcpy(buffer, &header, sizeof(header));
	return sizeof(header) + next_offset;
}

static size_t make_dm_status_fixture(unsigned char *buffer, size_t capacity,
				     const char *target_type, const char *parameters,
				     int target_status)
{
	const char *const types[] = { target_type };
	const char *const texts[] = { parameters };
	const int codes[] = { target_status };

	return make_dm_multi_fixture(buffer, capacity, types, texts, codes, 1, 1);
}

static int parse_fixture(const unsigned char *buffer, size_t size,
			 uint64_t expected_device,
			 struct dm_status_observation *observation,
			 struct status_problem *problem, unsigned int *problem_target)
{
	memset(observation, 0, sizeof(*observation));
	return parse_dm_status_observation(buffer, size, "fixture", expected_device,
					   observation, problem, problem_target);
}

static void test_dm_reply_boundaries_and_identity(void)
{
	unsigned char buffer[2048];
	struct dm_ioctl header;
	struct dm_target_spec specification;
	struct dm_status_observation observation;
	struct status_problem problem;
	unsigned int failed_target;
	size_t size = make_dm_status_fixture(buffer, sizeof(buffer), "swapz",
					      fixture_valid_status, 0);

	/* These are wire records, not _Alignof(struct dm_target_spec). */
	assert(SWAPZ_DM_WIRE_ALIGNMENT == 8U);
	assert(fixture_align_target_offset(8) == 8U);
	assert(fixture_align_target_offset(9) == 16U);
	assert(fixture_align_target_offset(16) == 16U);
	assert(fixture_align_target_offset(17) == 24U);
	assert(fixture_align_target_offset(24) == 24U);
	assert(fixture_align_target_offset(25) == 32U);
	memcpy(&header, buffer, sizeof(header));
	memcpy(&specification, buffer + sizeof(header), sizeof(specification));
	assert((size_t)specification.next == fixture_align_target_offset(
		(size_t)header.data_size - header.data_start));
	assert(parse_fixture(buffer, size, 1, &observation,
			     &problem, &failed_target) == 0);
	assert(observation.target_count == 1 && observation.targets[0].is_swapz);
	assert(observation.targets[0].ratio_state == STATUS_READY);
	status_free_observation(&observation);
	/* Final padding is metadata; data_size ends at the last status NUL. */
	assert(parse_fixture(buffer, header.data_size, 1, &observation,
			     &problem, &failed_target) == 0);
	status_free_observation(&observation);
	assert(parse_fixture(buffer, header.data_size - 1U, 1, &observation,
			     &problem, &failed_target) < 0);
	assert(!strcmp(problem.field, "dm_ioctl.data_start/data_size"));
	status_free_observation(&observation);
	assert(parse_fixture(buffer, size, 2, &observation,
			     &problem, &failed_target) < 0);
	assert(!strcmp(problem.field, "dm_ioctl.dev"));
	status_free_observation(&observation);
	specification.next = 0;
	memcpy(buffer + sizeof(header), &specification, sizeof(specification));
	assert(parse_fixture(buffer, size, 1, &observation,
			     &problem, &failed_target) < 0);
	assert(!strcmp(problem.field, "dm_target_spec.next"));
	status_free_observation(&observation);

	size = make_dm_status_fixture(buffer, sizeof(buffer), "swapz",
				      fixture_valid_status, 0);
	memcpy(&header, buffer, sizeof(header));
	header.target_count = 2;
	memcpy(buffer, &header, sizeof(header));
	assert(parse_fixture(buffer, size, 1, &observation,
			     &problem, &failed_target) < 0);
	assert(!strcmp(problem.field, "dm_target_spec.next"));
	status_free_observation(&observation);

	size = make_dm_status_fixture(buffer, sizeof(buffer), "swapz",
				      fixture_valid_status, 0);
	memcpy(&specification, buffer + sizeof(header), sizeof(specification));
	specification.next = UINT32_MAX;
	memcpy(buffer + sizeof(header), &specification, sizeof(specification));
	assert(parse_fixture(buffer, size, 1, &observation,
			     &problem, &failed_target) < 0);
	assert(!strcmp(problem.field, "dm_target_spec.next"));
	status_free_observation(&observation);

	size = make_dm_status_fixture(buffer, sizeof(buffer), "swapz",
				      fixture_valid_status, -5);
	assert(parse_fixture(buffer, size, 1, &observation,
			     &problem, &failed_target) == -2);
	assert(!strcmp(problem.field, "dm_target_spec.status"));
	status_free_observation(&observation);
	size = make_dm_status_fixture(buffer, sizeof(buffer), "swapz",
				      fixture_valid_status, 5);
	assert(parse_fixture(buffer, size, 1, &observation,
			     &problem, &failed_target) == -2);
	assert(!strcmp(problem.field, "dm_target_spec.status"));
	status_free_observation(&observation);

	size = make_dm_status_fixture(buffer, sizeof(buffer), "linear",
				      "private-target-data", 0);
	assert(parse_fixture(buffer, size, 1, &observation,
			     &problem, &failed_target) == 0);
	assert(!observation.targets[0].is_swapz);
	status_free_observation(&observation);
	size = make_dm_status_fixture(buffer, sizeof(buffer), "swapz",
				      fixture_valid_status, 0);
	memcpy(&specification, buffer + sizeof(header), sizeof(specification));
	memset(specification.target_type, 'x', sizeof(specification.target_type));
	memcpy(buffer + sizeof(header), &specification, sizeof(specification));
	assert(parse_fixture(buffer, size, 1, &observation,
			     &problem, &failed_target) < 0);
	assert(!strcmp(problem.field, "dm_target_spec.target_type"));
	status_free_observation(&observation);
	size = make_dm_status_fixture(buffer, sizeof(buffer), "swapz",
				      fixture_valid_status, 0);
	memcpy(&header, buffer, sizeof(header));
	header.dev = 0;
	memcpy(buffer, &header, sizeof(header));
	assert(parse_fixture(buffer, size, 1, &observation,
			     &problem, &failed_target) < 0);
	assert(!strcmp(problem.field, "dm_ioctl.dev"));
	status_free_observation(&observation);
}

static void test_absolute_offsets_for_multiple_dm_targets(void)
{
	unsigned char buffer[2048];
	const char *const types[] = { "linear", "linear", "swapz" };
	const char *const texts[] = {
		"private-status", "another-private-status", fixture_valid_status
	};
	struct dm_status_observation observation;
	struct status_problem problem;
	struct dm_ioctl header;
	struct dm_target_spec specification;
	unsigned int failed_target = 0;
	size_t size = make_dm_multi_fixture(buffer, sizeof(buffer), types,
					    texts, NULL, 3, 1);
	size_t second_offset;

	assert(parse_fixture(buffer, size, 1, &observation,
			     &problem, &failed_target) == 0);
	assert(observation.target_count == 3);
	assert(observation.targets[2].is_swapz);
	status_free_observation(&observation);
	memcpy(&header, buffer, sizeof(header));
	memcpy(&specification, buffer + sizeof(header), sizeof(specification));
	second_offset = specification.next;
	/* Overlap the next record even though the next offset is aligned. */
	memcpy(&specification, buffer + sizeof(header) + second_offset,
	       sizeof(specification));
	specification.next = (uint32_t)(second_offset + 8U);
	memcpy(buffer + sizeof(header) + second_offset, &specification,
	       sizeof(specification));
	assert(parse_fixture(buffer, size, 1, &observation,
			     &problem, &failed_target) < 0);
	assert(failed_target == 1);
	assert(!strcmp(problem.field, "dm_target_spec.next"));
	status_free_observation(&observation);

	size = make_dm_multi_fixture(buffer, sizeof(buffer), types,
				     texts, NULL, 3, 1);
	memcpy(&header, buffer, sizeof(header));
	header.data_size -= 1U; /* Truncate the final NUL. */
	memcpy(buffer, &header, sizeof(header));
	assert(parse_fixture(buffer, size, 1, &observation,
			     &problem, &failed_target) < 0);
	assert(!strcmp(problem.field, "dm_target_spec.params") ||
	       !strcmp(problem.field, "dm_target_spec.next"));
	status_free_observation(&observation);
}

static void test_full_target_inventory_comparison(void)
{
	unsigned char first_buffer[2048];
	unsigned char second_buffer[2048];
	const char *const types[] = { "linear", "swapz" };
	const char *const statuses[] = { "private-target-data", fixture_valid_status };
	struct dm_status_observation first = { 0 };
	struct dm_status_observation second = { 0 };
	struct status_problem problem;
	struct dm_ioctl header;
	struct dm_target_spec specification;
	unsigned int failed_target = 0;
	size_t first_size = make_dm_multi_fixture(first_buffer, sizeof(first_buffer),
						   types, statuses, NULL, 2, 1);
	size_t second_size = make_dm_multi_fixture(second_buffer, sizeof(second_buffer),
						    types, statuses, NULL, 2, 1);
	size_t second_record_offset;

	assert(parse_fixture(first_buffer, first_size, 1, &first,
			     &problem, &failed_target) == 0);
	assert(parse_fixture(second_buffer, second_size, 1, &second,
			     &problem, &failed_target) == 0);
	assert(status_observations_equal(&first, &second, &problem, &failed_target));
	status_free_observation(&second);

	memcpy(&header, second_buffer, sizeof(header));
	header.event_nr = 17;
	memcpy(second_buffer, &header, sizeof(header));
	assert(parse_fixture(second_buffer, second_size, 1, &second,
			     &problem, &failed_target) == 0);
	assert(!status_observations_equal(&first, &second, &problem, &failed_target));
	assert(!strcmp(problem.field, "dm_ioctl.event_nr"));
	status_free_observation(&second);
	header.event_nr = 0;
	memcpy(second_buffer, &header, sizeof(header));

	memcpy(&specification, second_buffer + sizeof(header), sizeof(specification));
	second_record_offset = specification.next;
	specification.length += 1U;
	memcpy(second_buffer + sizeof(header), &specification, sizeof(specification));
	assert(parse_fixture(second_buffer, second_size, 1, &second,
			     &problem, &failed_target) == 0);
	assert(!status_observations_equal(&first, &second, &problem, &failed_target));
	assert(failed_target == 0 && !strcmp(problem.field,
					     "dm_target_spec.sector_start/length"));
	status_free_observation(&second);
	specification.length -= 1U;
	memcpy(second_buffer + sizeof(header), &specification, sizeof(specification));

	memcpy(specification.target_type, "crypt", sizeof("crypt"));
	memcpy(second_buffer + sizeof(header), &specification, sizeof(specification));
	assert(parse_fixture(second_buffer, second_size, 1, &second,
			     &problem, &failed_target) == 0);
	assert(!status_observations_equal(&first, &second, &problem, &failed_target));
	assert(!strcmp(problem.field, "dm_target_spec.target_type"));
	status_free_observation(&second);
	memcpy(specification.target_type, "linear", sizeof("linear"));
	memcpy(second_buffer + sizeof(header), &specification, sizeof(specification));

	/* A changed non-swapz INFO string must not be ignored. */
	second_buffer[sizeof(header) + sizeof(specification)] = 'X';
	assert(parse_fixture(second_buffer, second_size, 1, &second,
			     &problem, &failed_target) == 0);
	assert(!status_observations_equal(&first, &second, &problem, &failed_target));
	assert(!strcmp(problem.field, "dm_target_spec.params"));
	status_free_observation(&second);

	/* No parser can infer a new target from the same truncated payload. */
	header.target_count = SWAPZ_STATUS_MAX_TARGETS + 1U;
	memcpy(second_buffer, &header, sizeof(header));
	assert(parse_fixture(second_buffer, second_size, 1, &second,
			     &problem, &failed_target) < 0);
	assert(!strcmp(problem.field, "dm_target_spec.next"));
	status_free_observation(&second);
	assert(second_record_offset > sizeof(specification));
	status_free_observation(&first);
}

static void test_padding_output_has_no_fabricated_compressed_ratio(void)
{
	const char *const padded_status =
		"logical_write=16384 physical_write=12288 gc_write=0 "
		"compressed=4 raw=0 zero_elided=0 bulk_mode=2 bulk_padding=1 "
		"failed=0 error=0";
	struct swapz_ratio_status ratio;
	FILE *capture = tmpfile();
	int saved_stdout = dup(STDOUT_FILENO);
	char output[2048] = { 0 };
	size_t bytes;

	assert(capture && saved_stdout >= 0);
	assert(parse_swapz_ratio_status(padded_status, &ratio) == STATUS_READY);
	fflush(stdout);
	assert(dup2(fileno(capture), STDOUT_FILENO) >= 0);
	report_swapz_target("fixture", 0, &ratio);
	fflush(stdout);
	assert(dup2(saved_stdout, STDOUT_FILENO) >= 0);
	rewind(capture);
	bytes = fread(output, 1, sizeof(output) - 1U, capture);
	output[bytes] = '\0';
	assert(strstr(output, "compressed ratio (SWZ extents): UNAVAILABLE"));
	assert(strstr(output, "field 'bulk_padding'"));
	assert(strstr(output, "overall ratio (compressed + RAW + zero): 1.33:1"));
	assert(!strstr(output, "compressed ratio (SWZ extents): 1.33:1"));
	close(saved_stdout);
	fclose(capture);
}

struct status_reader_fixture {
	const char *const *statuses;
	size_t count;
	size_t calls;
	size_t present_reads; /* Zero means present on every read. */
	uint64_t second_device; /* Nonzero changes the identity on the second read. */
	int second_target_status; /* Negative means a failed later target. */
	int fail_errno;
};

static int read_fixture_observation(
	void *context, const char *name, uint64_t expected_device,
	struct dm_status_observation *observation,
	struct status_problem *problem, unsigned int *problem_target)
{
	struct status_reader_fixture *fixture = context;
	const char *const types[] = { "swapz", "swapz" };
	const char *texts[2];
	const int codes[] = { 0, fixture->second_target_status };
	unsigned char *buffer;
	size_t size;
	int result;

	(void)name;
	if ((fixture->present_reads && fixture->calls >= fixture->present_reads) ||
	    fixture->fail_errno) {
		++fixture->calls;
		errno = fixture->fail_errno ? fixture->fail_errno : ENXIO;
		return -1;
	}
	assert(fixture->count);
	texts[0] = fixture_valid_status;
	texts[1] = fixture->statuses[fixture->calls % fixture->count];
	buffer = malloc(2048);
	assert(buffer);
	size = make_dm_multi_fixture(buffer, 2048, types, texts, codes, 2,
				     fixture->second_device && (fixture->calls % 2U) ?
				     fixture->second_device : expected_device);
	++fixture->calls;
	memset(observation, 0, sizeof(*observation));
	observation->reply = buffer;
	result = parse_fixture(buffer, size, expected_device, observation,
			       problem, problem_target);
	observation->reply = buffer;
	return result;
}

static void test_snapshot_retry_exhaustion_and_failures(void)
{
	const char *const changing[] = {
		"logical_write=8192 physical_write=4096 gc_write=0 "
		"compressed=2 raw=0 zero_elided=0 bulk_mode=1 bulk_padding=0 "
		"failed=0 error=0",
		"logical_write=12288 physical_write=8192 gc_write=0 "
		"compressed=3 raw=0 zero_elided=0 bulk_mode=1 bulk_padding=0 "
		"failed=0 error=0"
	};
	const char *const failed[] = { fixture_valid_status, "failed=1 error=-5" };
	const char *const torn[] = {
		"logical_write=4096 physical_write=4096 gc_write=0 "
		"compressed=2 raw=0 zero_elided=0 bulk_mode=1 bulk_padding=0 "
		"failed=0 error=0"
	};
	struct status_reader_fixture fixture = {
		.statuses = changing, .count = 2
	};
	struct status_ready_report report = { 0 };
	char diagnostic[2048] = { 0 };
	FILE *capture = tmpfile();
	FILE *stdout_capture = tmpfile();
	int saved_stdout = dup(STDOUT_FILENO);
	int saved_stderr = dup(STDERR_FILENO);
	size_t bytes;
	int result;

	assert(capture && stdout_capture && saved_stderr >= 0 && saved_stdout >= 0);
	assert(dup2(fileno(capture), STDERR_FILENO) >= 0);
	result = report_device_status_with_reader(&fixture, read_fixture_observation,
						   "fixture", 1, &report);
	fflush(stderr);
	assert(dup2(saved_stderr, STDERR_FILENO) >= 0);
	assert(result == -2 && report.count == 0);
	assert(fixture.calls == 2U * SWAPZ_STATUS_SNAPSHOT_RETRIES);
	rewind(capture);
	bytes = fread(diagnostic, 1, sizeof(diagnostic) - 1U, capture);
	diagnostic[bytes] = '\0';
	assert(strstr(diagnostic, "UNAVAILABLE"));
	assert(strstr(diagnostic, "snapshot 2"));
	assert(strstr(diagnostic, "dm_target_spec.params"));
	assert(!strstr(diagnostic, fixture_valid_status));

	fixture = (struct status_reader_fixture){ .statuses = failed, .count = 2 };
	assert(report_device_status_with_reader(&fixture, read_fixture_observation,
						"fixture", 1, &report) == -2);
	assert(!report.count && fixture.calls == 2);
	fixture = (struct status_reader_fixture){ .statuses = torn, .count = 1 };
	assert(report_device_status_with_reader(&fixture, read_fixture_observation,
						"fixture", 1, &report) == -2);
	assert(!report.count && fixture.calls == 2U * SWAPZ_STATUS_SNAPSHOT_RETRIES);

	fixture = (struct status_reader_fixture){
		.statuses = changing, .count = 2, .second_device = 2
	};
	assert(report_device_status_with_reader(&fixture, read_fixture_observation,
						"fixture", 1, &report) == -2);
	assert(!report.count && fixture.calls == 2);

	fixture = (struct status_reader_fixture){
		.statuses = changing, .count = 2, .second_target_status = -5
	};
	assert(dup2(fileno(stdout_capture), STDOUT_FILENO) >= 0);
	assert(report_device_status_with_reader(&fixture, read_fixture_observation,
						"fixture", 1, &report) == -2);
	fflush(stdout);
	assert(dup2(saved_stdout, STDOUT_FILENO) >= 0);
	assert(!report.count && fixture.calls == 1);
	/* Even if the first target is healthy, the later failure emits no metrics. */
	rewind(stdout_capture);
	assert(fread(diagnostic, 1, sizeof(diagnostic) - 1U, stdout_capture) == 0);
	fixture = (struct status_reader_fixture){
		.statuses = changing, .count = 2, .fail_errno = EACCES
	};
	assert(report_device_status_with_reader(&fixture, read_fixture_observation,
						"fixture", 1, &report) == -2);
	assert(!report.count && fixture.calls == 1);
	fixture = (struct status_reader_fixture){
		.statuses = torn, .count = 1, .present_reads = 1
	};
	assert(report_device_status_with_reader(&fixture, read_fixture_observation,
						"fixture", 1, &report) == -2);
	assert(!report.count && fixture.calls == 2);
	assert(errno == ENXIO); /* The second ioctl errno, never a stale parser field. */

	free(report.targets);
	close(saved_stdout);
	close(saved_stderr);
	fclose(capture);
	fclose(stdout_capture);
}

static void test_complete_snapshot_before_output(void)
{
	const char *const stable[] = { fixture_valid_status };
	struct status_reader_fixture fixture = {
		.statuses = stable, .count = 1
	};
	struct status_ready_report report = { 0 };

	assert(report_device_status_with_reader(&fixture, read_fixture_observation,
						"fixture", 1, &report) == 0);
	assert(fixture.calls == 2 && report.count == 2);
	assert(report.targets[0].target_index == 0);
	assert(report.targets[1].target_index == 1);
	free(report.targets);
}

static void test_status_is_read_only(void)
{
	unsigned char *reply = NULL;
	size_t reply_size = 0;

	assert((status_control_open_flags() & O_ACCMODE) == O_RDONLY);
	assert(!(status_control_open_flags() & (O_CREAT | O_TRUNC)));
	assert(dm_query(-1, DM_DEV_REMOVE, "fixture",
			&reply, &reply_size) == -1);
	assert(errno == EPERM);
	assert(dm_query(-1, DM_TABLE_LOAD, "fixture",
			&reply, &reply_size) == -1);
	assert(errno == EPERM);
	assert(dm_query(-1, DM_DEV_SUSPEND, "fixture",
			&reply, &reply_size) == -1);
	assert(errno == EPERM);
	assert(!reply && reply_size == 0);
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
	test_required_tokens_duplicates_and_canonical_numbers();
	test_checked_counter_arithmetic();
	test_dm_reply_boundaries_and_identity();
	test_absolute_offsets_for_multiple_dm_targets();
	test_full_target_inventory_comparison();
	test_padding_output_has_no_fabricated_compressed_ratio();
	test_snapshot_retry_exhaustion_and_failures();
	test_complete_snapshot_before_output();
	test_status_is_read_only();
	puts("PASS: swapzctl status compression-ratio accounting");
	return 0;
}
