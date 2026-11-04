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
		STATUS_RETRY, "physical_write-gc_write-raw*4096", "disagree");
}

static size_t fixture_align_target_offset(size_t value)
{
	const size_t alignment = _Alignof(struct dm_target_spec);
	const size_t remainder = value % alignment;

	assert(value <= SIZE_MAX - (remainder ? alignment - remainder : 0U));
	return remainder ? value + alignment - remainder : value;
}

static size_t make_dm_status_fixture(unsigned char *buffer, size_t capacity,
				     const char *target_type, const char *parameters,
				     int target_status)
{
	struct dm_ioctl header = { 0 };
	struct dm_target_spec specification = { 0 };
	const size_t parameter_bytes = strlen(parameters) + 1U;
	const size_t payload_used = sizeof(specification) + parameter_bytes;
	const size_t terminal_next = fixture_align_target_offset(payload_used);
	const size_t data_size = sizeof(header) + payload_used;
	const size_t reply_capacity = sizeof(header) + terminal_next;

	assert(reply_capacity <= capacity);
	assert(terminal_next <= UINT32_MAX);
	memset(buffer, 0, capacity);
	header.data_start = sizeof(header);
	header.data_size = (uint32_t)data_size;
	header.target_count = 1;
	header.dev = 1;
	memcpy(header.name, "fixture", sizeof("fixture"));
	specification.length = 1024;
	specification.status = target_status;
	specification.next = (uint32_t)terminal_next;
	assert(strlen(target_type) < sizeof(specification.target_type));
	memcpy(specification.target_type, target_type, strlen(target_type) + 1U);
	memcpy(buffer, &header, sizeof(header));
	memcpy(buffer + sizeof(header), &specification, sizeof(specification));
	memcpy(buffer + sizeof(header) + sizeof(specification),
	       parameters, parameter_bytes);
	return reply_capacity;
}

static void test_dm_reply_boundaries_and_identity(void)
{
	unsigned char buffer[2048];
	struct dm_ioctl header;
	struct dm_target_spec specification;
	struct swapz_target_snapshot snapshot;
	size_t size = make_dm_status_fixture(buffer, sizeof(buffer), "swapz",
					     fixture_valid_status, 0);

	memcpy(&header, buffer, sizeof(header));
	memcpy(&specification, buffer + sizeof(header), sizeof(specification));
	assert(specification.next != 0U);
	assert((size_t)specification.next ==
	       fixture_align_target_offset(
		       (size_t)header.data_size - header.data_start));
	assert(parse_dm_target_snapshot(buffer, size, "fixture", 0, &snapshot) == 1);
	assert(snapshot.ratio_state == STATUS_READY);
	assert(snapshot.device_id == 1);
	assert(parse_dm_target_snapshot(buffer, (size_t)header.data_size - 1U,
					"fixture", 0, &snapshot) < 0);
	assert(!strcmp(snapshot.problem.field, "dm_ioctl.data_start/data_size"));
	assert(parse_dm_target_snapshot(buffer, size, "different", 0,
					&snapshot) < 0);
	assert(!strcmp(snapshot.problem.field, "dm_ioctl.name"));

	memcpy(&specification, buffer + sizeof(header), sizeof(specification));
	specification.next = 0;
	memcpy(buffer + sizeof(header), &specification, sizeof(specification));
	assert(parse_dm_target_snapshot(buffer, size, "fixture", 0,
					&snapshot) < 0);
	assert(!strcmp(snapshot.problem.field, "dm_target_spec.next"));

	size = make_dm_status_fixture(buffer, sizeof(buffer), "swapz",
				      fixture_valid_status, 0);
	memcpy(&header, buffer, sizeof(header));
	header.target_count = 2;
	memcpy(buffer, &header, sizeof(header));
	assert(parse_dm_target_snapshot(buffer, size, "fixture", 0,
					&snapshot) < 0);
	assert(!strcmp(snapshot.problem.field, "dm_target_spec.next"));

	size = make_dm_status_fixture(buffer, sizeof(buffer), "swapz",
				      fixture_valid_status, 0);
	memcpy(&specification, buffer + sizeof(header), sizeof(specification));
	specification.next = UINT_MAX;
	memcpy(buffer + sizeof(header), &specification, sizeof(specification));
	assert(parse_dm_target_snapshot(buffer, size, "fixture", 0,
					&snapshot) < 0);
	assert(!strcmp(snapshot.problem.field, "dm_target_spec.next"));

	size = make_dm_status_fixture(buffer, sizeof(buffer), "swapz",
				      fixture_valid_status, -5);
	assert(parse_dm_target_snapshot(buffer, size, "fixture", 0, &snapshot) == 1);
	assert(snapshot.ratio_state == STATUS_FAILED);
	assert(!strcmp(snapshot.problem.field, "dm_target_spec.status"));
	size = make_dm_status_fixture(buffer, sizeof(buffer), "swapz",
				      fixture_valid_status, 5);
	assert(parse_dm_target_snapshot(buffer, size, "fixture", 0, &snapshot) == 1);
	assert(snapshot.ratio_state == STATUS_BLOCKED);

	size = make_dm_status_fixture(buffer, sizeof(buffer), "linear",
				      fixture_valid_status, 0);
	assert(parse_dm_target_snapshot(buffer, size, "fixture", 0, &snapshot) == 0);
	assert(!snapshot.problem.field);
	size = make_dm_status_fixture(buffer, sizeof(buffer), "swapz",
				      fixture_valid_status, 0);
	memcpy(&specification, buffer + sizeof(header), sizeof(specification));
	memset(specification.target_type, 'x', sizeof(specification.target_type));
	memcpy(buffer + sizeof(header), &specification, sizeof(specification));
	assert(parse_dm_target_snapshot(buffer, size, "fixture", 0,
					&snapshot) < 0);
	assert(!strcmp(snapshot.problem.field, "dm_target_spec.target_type"));

	size = make_dm_status_fixture(buffer, sizeof(buffer), "swapz",
				      fixture_valid_status, 0);
	memcpy(&header, buffer, sizeof(header));
	header.dev = 0;
	memcpy(buffer, &header, sizeof(header));
	assert(parse_dm_target_snapshot(buffer, size, "fixture", 0, &snapshot) < 0);
	assert(!strcmp(snapshot.problem.field, "dm_ioctl.dev"));
}

static void test_absolute_offsets_for_multiple_dm_targets(void)
{
	unsigned char buffer[2048] = { 0 };
	struct dm_ioctl header = { 0 };
	struct dm_target_spec specification = { 0 };
	struct swapz_target_snapshot snapshot;
	const char *const first_params = "not-a-swapz-status";
	const char *const second_params = "another-linear-status";
	const size_t first_used = sizeof(specification) + strlen(first_params) + 1U;
	const size_t first_next = fixture_align_target_offset(first_used);
	const size_t second_used = first_next + sizeof(specification) +
				   strlen(second_params) + 1U;
	const size_t second_next = fixture_align_target_offset(second_used);
	const size_t final_used = second_next + sizeof(specification) +
				  strlen(fixture_valid_status) + 1U;
	const size_t final_next = fixture_align_target_offset(final_used);
	const size_t data_size = sizeof(header) + final_used;
	const size_t capacity = sizeof(header) + final_next;
	unsigned char *first = buffer + sizeof(header);
	unsigned char *second = first + first_next;
	unsigned char *third = first + second_next;

	assert(capacity <= sizeof(buffer));
	assert(final_next <= UINT32_MAX);
	header.data_size = (uint32_t)data_size;
	header.data_start = sizeof(header);
	header.target_count = 3;
	header.dev = 1;
	memcpy(header.name, "fixture", sizeof("fixture"));
	memcpy(buffer, &header, sizeof(header));
	memcpy(specification.target_type, "linear", sizeof("linear"));
	specification.length = 1024;
	specification.next = (uint32_t)first_next;
	memcpy(first, &specification, sizeof(specification));
	memcpy(first + sizeof(specification), first_params, strlen(first_params) + 1U);
	specification.next = (uint32_t)second_next;
	memcpy(second, &specification, sizeof(specification));
	memcpy(second + sizeof(specification), second_params, strlen(second_params) + 1U);
	memcpy(specification.target_type, "swapz", sizeof("swapz"));
	specification.next = (uint32_t)final_next;
	memcpy(third, &specification, sizeof(specification));
	memcpy(third + sizeof(specification), fixture_valid_status,
	       strlen(fixture_valid_status) + 1U);

	assert(parse_dm_target_snapshot(buffer, capacity, "fixture", 0,
					&snapshot) == 1);
	assert(snapshot.ratio_state == STATUS_READY);
	memcpy(&specification, second, sizeof(specification));
	specification.next =
		(uint32_t)(first_next + sizeof(specification) + 1U);
	memcpy(second, &specification, sizeof(specification));
	assert(parse_dm_target_snapshot(buffer, capacity, "fixture", 0,
					&snapshot) < 0);
	assert(!strcmp(snapshot.problem.field, "dm_target_spec.next"));
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
};

static int read_fixture_snapshot(void *context, const char *name,
				 unsigned int target_index,
				 struct swapz_target_snapshot *snapshot)
{
	struct status_reader_fixture *fixture = context;
	const char *status;

	(void)name;
	if (target_index)
		return 0;
	if (fixture->present_reads && fixture->calls >= fixture->present_reads) {
		++fixture->calls;
		return 0;
	}
	assert(fixture->count);
	status = fixture->statuses[fixture->calls % fixture->count];
	++fixture->calls;
	memset(snapshot, 0, sizeof(*snapshot));
	snapshot->sector_start = 1;
	snapshot->length = 1024;
	snapshot->device_id = 1;
	snapshot->event_number = 2;
	snapshot->ratio_state = parse_swapz_ratio_status_diagnostic(
		status, &snapshot->ratio, &snapshot->problem);
	return 1;
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
	struct status_reader_fixture fixture = { changing, 2, 0, 0 };
	char diagnostic[1024] = { 0 };
	FILE *capture = tmpfile();
	int saved_stderr = dup(STDERR_FILENO);
	int targets = 0;
	size_t bytes;
	int result;

	assert(capture && saved_stderr >= 0);
	assert(dup2(fileno(capture), STDERR_FILENO) >= 0);
	result = report_device_status_with_reader(&fixture, read_fixture_snapshot,
						   "fixture", &targets);
	fflush(stderr);
	assert(dup2(saved_stderr, STDERR_FILENO) >= 0);
	assert(result == -2 && targets == 0);
	assert(fixture.calls == 2U * SWAPZ_STATUS_SNAPSHOT_RETRIES);
	rewind(capture);
	bytes = fread(diagnostic, 1, sizeof(diagnostic) - 1U, capture);
	diagnostic[bytes] = '\0';
	assert(strstr(diagnostic, "UNAVAILABLE"));
	assert(strstr(diagnostic, "consecutive DM INFO snapshots"));

	fixture = (struct status_reader_fixture){ failed, 2, 0, 0 };
	targets = 0;
	assert(dup2(fileno(capture), STDERR_FILENO) >= 0);
	result = report_device_status_with_reader(&fixture, read_fixture_snapshot,
						   "fixture", &targets);
	fflush(stderr);
	assert(dup2(saved_stderr, STDERR_FILENO) >= 0);
	assert(result == -2 && targets == 0 && fixture.calls == 2);
	fixture = (struct status_reader_fixture){ torn, 1, 0, 0 };
	targets = 0;
	assert(dup2(fileno(capture), STDERR_FILENO) >= 0);
	result = report_device_status_with_reader(&fixture, read_fixture_snapshot,
						   "fixture", &targets);
	fflush(stderr);
	assert(dup2(saved_stderr, STDERR_FILENO) >= 0);
	assert(result == -2 && targets == 0);
	assert(fixture.calls == 2U * SWAPZ_STATUS_SNAPSHOT_RETRIES);

	fixture = (struct status_reader_fixture){ torn, 1, 0, 1 };
	targets = 0;
	assert(dup2(fileno(capture), STDERR_FILENO) >= 0);
	result = report_device_status_with_reader(&fixture, read_fixture_snapshot,
						   "fixture", &targets);
	fflush(stderr);
	assert(dup2(saved_stderr, STDERR_FILENO) >= 0);
	assert(result == -2 && targets == 0);
	assert(fixture.calls == SWAPZ_STATUS_SNAPSHOT_RETRIES + 1U);

	close(saved_stderr);
	fclose(capture);
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
	test_padding_output_has_no_fabricated_compressed_ratio();
	test_snapshot_retry_exhaustion_and_failures();
	test_status_is_read_only();
	puts("PASS: swapzctl status compression-ratio accounting");
	return 0;
}
