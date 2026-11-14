// SPDX-License-Identifier: GPL-2.0-only
#define ioctl swapzctl_status_test_ioctl
#define main swapzctl_program_main
#include "../../../../src/userspace/swapzctl.c"
#undef main
#undef ioctl

#include <assert.h>
#include <stdarg.h>
#include <stdio.h>

enum fake_dm_ioctl_behavior {
	FAKE_DM_IOCTL_DISABLED,
	FAKE_DM_IOCTL_BUFFER_FULL,
	FAKE_DM_IOCTL_BAD_HEADER,
	FAKE_DM_IOCTL_ERROR
};

static enum fake_dm_ioctl_behavior fake_dm_ioctl_behavior;
static int fake_dm_ioctl_error;
static unsigned int fake_dm_ioctl_calls;

int swapzctl_status_test_ioctl(int fd, unsigned long request, ...)
{
	struct dm_ioctl *io;
	va_list arguments;

	(void)fd;
	++fake_dm_ioctl_calls;
	if (request != DM_TABLE_STATUS) {
		errno = ENOTTY;
		return -1;
	}
	if (fake_dm_ioctl_behavior == FAKE_DM_IOCTL_ERROR) {
		errno = fake_dm_ioctl_error;
		return -1;
	}
	va_start(arguments, request);
	io = va_arg(arguments, struct dm_ioctl *);
	va_end(arguments);
	if (fake_dm_ioctl_behavior == FAKE_DM_IOCTL_BUFFER_FULL) {
		io->flags |= DM_BUFFER_FULL_FLAG;
		return 0;
	}
	if (fake_dm_ioctl_behavior == FAKE_DM_IOCTL_BAD_HEADER) {
		io->data_size = 0;
		return 0;
	}
	errno = ENOTTY;
	return -1;
}

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
	struct status_problem problem = { 0 };

	assert(parse_swapz_ratio_status_diagnostic(status, &ratio, &problem) ==
	       STATUS_FAILED);
	assert(ratio.failed == 1ULL);
	assert(ratio.error == -5);
	assert(problem.kernel_errno == -5);
	assert(problem.field && !strcmp(problem.field, "failed"));
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

static void test_unsigned_decimal_parser_bounds(void)
{
	const char *parsed_end = NULL;
	unsigned long long value = 42ULL;

	assert(parse_unsigned_decimal("0", 0ULL, &parsed_end, &value) == 0);
	assert(value == 0ULL && *parsed_end == '\0');
	assert(parse_unsigned_decimal("18446744073709551615", ULLONG_MAX,
				      &parsed_end, &value) == 0);
	assert(value == ULLONG_MAX && *parsed_end == '\0');
	assert(parse_unsigned_decimal("18446744073709551616", ULLONG_MAX,
				      &parsed_end, &value) < 0);
	assert(value == ULLONG_MAX);
	assert(parse_unsigned_decimal("4294967295", UINT_MAX,
				      &parsed_end, &value) == 0);
	assert(value == UINT_MAX && *parsed_end == '\0');
	assert(parse_unsigned_decimal("4294967296", UINT_MAX,
				      &parsed_end, &value) < 0);
	assert(parse_unsigned_decimal("1", 0ULL, &parsed_end, &value) < 0);
	assert(parse_unsigned_decimal("00", 1ULL, &parsed_end, &value) < 0);
	assert(parse_unsigned_decimal("01", 1ULL, &parsed_end, &value) < 0);
	assert(parse_unsigned_decimal("+1", 1ULL, &parsed_end, &value) < 0);
	assert(parse_unsigned_decimal("-1", 1ULL, &parsed_end, &value) < 0);
	assert(parse_unsigned_decimal("", 1ULL, &parsed_end, &value) < 0);
	assert(parse_unsigned_decimal("12x", 12ULL, &parsed_end, &value) == 0);
	assert(value == 12ULL && *parsed_end == 'x');
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
		"failed=1", STATUS_BLOCKED, "error", "missing");
	assert_status_problem(
		"failed=1 error=0", STATUS_RETRY, "failed/error", "terminal errno");
	assert_status_problem(
		"failed=1 error=-5", STATUS_FAILED, "failed", "kernel target is failed");
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

struct fixture_c32_aligned_record {
	uint32_t words[2];
};

static size_t fixture_align_target_offset(size_t value)
{
	size_t aligned = 0;

	assert(status_align_target_offset(value, &aligned) == 0);
	return aligned;
}

static void test_dm_wire_alignment_is_host_independent(void)
{
	/*
	 * Model a common 32-bit C ABI record alignment explicitly. DM output
	 * records still use the Linux UAPI's fixed eight-byte wire alignment.
	 */
	assert(_Alignof(struct fixture_c32_aligned_record) == 4U);
	assert(_Alignof(struct fixture_c32_aligned_record) !=
	       SWAPZ_DM_WIRE_ALIGNMENT);
	assert(fixture_align_target_offset(8U) == 8U);
	assert(fixture_align_target_offset(9U) == 16U);
	assert(fixture_align_target_offset(16U) == 16U);
	assert(fixture_align_target_offset(17U) == 24U);
	assert(fixture_align_target_offset(24U) == 24U);
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

static size_t make_dm_empty_status_fixture(unsigned char *buffer, size_t capacity,
					   uint64_t device_id)
{
	struct dm_ioctl header = { 0 };

	assert(capacity >= sizeof(header));
	assert(capacity <= UINT32_MAX);
	memset(buffer, 0, capacity);
	header.data_start = sizeof(header);
	/*
	 * Linux leaves the requested data_size unchanged when no live table is
	 * present because retrieve_status() is not called.
	 */
	header.data_size = (uint32_t)capacity;
	header.dev = device_id;
	memcpy(header.name, "fixture", sizeof("fixture"));
	memcpy(buffer, &header, sizeof(header));
	return capacity;
}

static size_t make_dm_name_list_fixture(
	unsigned char *buffer, size_t capacity, const char *name,
	uint64_t device_id, uint32_t event_number)
{
	const size_t name_offset = offsetof(struct dm_name_list, name);
	size_t metadata_offset;
	size_t record_size;
	uint32_t next = 0;
	uint32_t flags = 0;

	assert(strlen(name) < DM_NAME_LEN);
	metadata_offset = fixture_align_target_offset(
		name_offset + strlen(name) + 1U);
	record_size = metadata_offset + 2U * sizeof(uint32_t);
	assert(record_size <= capacity);
	memset(buffer, 0, capacity);
	memcpy(buffer + offsetof(struct dm_name_list, dev), &device_id,
	       sizeof(device_id));
	memcpy(buffer + offsetof(struct dm_name_list, next), &next, sizeof(next));
	memcpy(buffer + name_offset, name, strlen(name) + 1U);
	memcpy(buffer + metadata_offset, &event_number, sizeof(event_number));
	memcpy(buffer + metadata_offset + sizeof(event_number), &flags,
	       sizeof(flags));
	return record_size;
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

static void test_empty_dm_target_inventory(void)
{
	unsigned char first_buffer[2048];
	unsigned char second_buffer[2048];
	struct dm_status_observation first = { 0 };
	struct dm_status_observation second = { 0 };
	struct status_problem problem;
	unsigned int problem_target = UINT_MAX;
	size_t first_size = make_dm_empty_status_fixture(
		first_buffer, sizeof(first_buffer), 1);
	size_t second_size = make_dm_empty_status_fixture(
		second_buffer, sizeof(second_buffer), 1);

	assert(parse_fixture(first_buffer, first_size, 1, &first,
			     &problem, &problem_target) == 0);
	assert(first.target_count == 0);
	assert(!first.targets);
	assert(parse_fixture(second_buffer, second_size, 1, &second,
			     &problem, &problem_target) == 0);
	assert(status_observations_equal(&first, &second, &problem,
					 &problem_target));
	status_free_observation(&first);
	status_free_observation(&second);
}

static void test_list_query_requests_mapping_uuids(void)
{
	assert(dm_query_input_flags(DM_LIST_DEVICES) == DM_UUID_FLAG);
	assert(dm_query_input_flags(DM_TABLE_STATUS) == 0U);
}

static void test_dm_name_list_wire_records(void)
{
	unsigned char buffer[128];
	struct dm_list_record record;
	struct status_problem problem;
	uint32_t next;
	size_t size = make_dm_name_list_fixture(
		buffer, sizeof(buffer), "a", 7, 11);

	assert(size == 24U);
	assert(status_parse_name_list_record(buffer, size, &record, &problem) == 0);
	assert(record.device_id == 7U);
	assert(record.event_number == 11U);
	assert(record.record_size == size);
	assert(!strcmp(record.name, "a"));

	next = 16U;
	memcpy(buffer + offsetof(struct dm_name_list, next), &next, sizeof(next));
	assert(status_parse_name_list_record(buffer, size, &record, &problem) < 0);
	assert(!strcmp(problem.field, "dm_name_list.event_nr/flags"));

	size = make_dm_name_list_fixture(buffer, sizeof(buffer), "a", 7, 11);
	next = 23U;
	memcpy(buffer + offsetof(struct dm_name_list, next), &next, sizeof(next));
	assert(status_parse_name_list_record(buffer, size, &record, &problem) < 0);
	assert(!strcmp(problem.field, "dm_name_list.next"));

	size = make_dm_name_list_fixture(buffer, sizeof(buffer), "a", 7, 11);
	assert(status_parse_name_list_record(buffer, 16U, &record, &problem) < 0);
	assert(!strcmp(problem.field, "dm_name_list.event_nr/flags"));

	size = make_dm_name_list_fixture(buffer, sizeof(buffer), "a", 7, 11);
	memset(buffer + offsetof(struct dm_name_list, name) + 1U, 'x',
	       size - offsetof(struct dm_name_list, name) - 1U);
	assert(status_parse_name_list_record(buffer, size, &record, &problem) < 0);
	assert(!strcmp(problem.field, "dm_name_list.name"));
}

static void test_list_generation_binding(void)
{
	struct dm_status_observation observation = {
		.device_id = 7,
		.event_number = 12
	};
	struct status_problem problem;
	unsigned int problem_target = 0;

	assert(status_validate_list_generation(&observation, 12, &problem,
					       &problem_target) == 0);
	assert(status_validate_list_generation(&observation, 11, &problem,
					       &problem_target) < 0);
	assert(errno == EAGAIN);
	assert(problem.failure_errno == EAGAIN);
	assert(problem_target == UINT_MAX);
	assert(!strcmp(problem.field, "dm_ioctl.event_nr"));

	problem = (struct status_problem){
		.field = "dm_target_spec.params",
		.expected = "original parser expectation",
		.observed = "original parser failure"
	};
	problem_target = 1;
	errno = EPROTO;
	assert(status_bind_list_generation(-2, &observation, 11,
					   &problem, &problem_target) == -2);
	assert(errno == EPROTO);
	assert(problem_target == 1);
	assert(!strcmp(problem.field, "dm_target_spec.params"));
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
	assert(fixture_align_target_offset(25U) == 32U);
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

	/* An aligned gap after the first NUL is not a valid next target offset. */
	specification.next += SWAPZ_DM_WIRE_ALIGNMENT;
	memcpy(buffer + sizeof(header), &specification, sizeof(specification));
	assert(parse_fixture(buffer, size, 1, &observation,
			     &problem, &failed_target) < 0);
	assert(!strcmp(problem.field, "dm_target_spec.next"));
	status_free_observation(&observation);

	size = make_dm_multi_fixture(buffer, sizeof(buffer), types,
				     texts, NULL, 3, 1);
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

	{
		const char *const one_type[] = { "linear" };
		const char *const one_text[] = { "x" };

		size = make_dm_multi_fixture(buffer, sizeof(buffer), one_type,
					     one_text, NULL, 1, 1);
		memcpy(&header, buffer, sizeof(header));
		assert((size_t)header.data_size < size);
		header.data_size += 1U;
		memcpy(buffer, &header, sizeof(header));
		assert(parse_fixture(buffer, size, 1, &observation,
				     &problem, &failed_target) < 0);
		assert(!strcmp(problem.field, "dm_target_spec.params"));
		status_free_observation(&observation);
	}
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

static void test_page_count_grouping(void)
{
	char text[32];

	format_page_count(0, text);
	assert(!strcmp(text, "0"));
	format_page_count(999, text);
	assert(!strcmp(text, "999"));
	format_page_count(1000, text);
	assert(!strcmp(text, "1,000"));
	format_page_count(136020, text);
	assert(!strcmp(text, "136,020"));
	format_page_count(ULLONG_MAX, text);
	assert(!strcmp(text, "18,446,744,073,709,551,615"));
}

static void test_status_report_groups_live_swapz_counts(void)
{
	/* Reproduce real-device logical/physical and page-count proportions. */
	const char *const status =
		"logical_write=589369344 physical_write=570134528 gc_write=0 "
		"compressed=7860 raw=136020 zero_elided=9 bulk_mode=1 "
		"bulk_padding=0 failed=0 error=0";
	struct swapz_ratio_status ratio;
	FILE *capture = tmpfile();
	int saved_stdout = dup(STDOUT_FILENO);
	char output[2048] = { 0 };
	size_t bytes;

	assert(capture && saved_stdout >= 0);
	assert(parse_swapz_ratio_status(status, &ratio) == STATUS_READY);
	fflush(stdout);
	assert(dup2(fileno(capture), STDOUT_FILENO) >= 0);
	report_swapz_target("swapz-demo-physical-fixture", 0, &ratio);
	fflush(stdout);
	assert(dup2(saved_stdout, STDOUT_FILENO) >= 0);
	rewind(capture);
	bytes = fread(output, 1, sizeof(output) - 1U, capture);
	output[bytes] = '\0';
	assert(strstr(output, "swapz target: swapz-demo-physical-fixture"));
	assert(strstr(output, "Ratios (logical / lower, foreground)"));
	assert(strstr(output, "SWZ compressed"));
	assert(strstr(output, "2.48:1  (30.70 MiB / 12.39 MiB)"));
	assert(strstr(output, "Overall"));
	assert(strstr(output, "1.03:1  (562.07 MiB / 543.72 MiB)"));
	assert(strstr(output, "Pages (4 KiB)"));
	assert(strstr(output, "7,860"));
	assert(strstr(output, "136,020"));
	assert(strstr(output, "Zero-elided"));
	assert(strstr(output, "GC lower writes: 0 B (excluded from ratios)"));
	assert(strstr(output, "Scope: cumulative successful foreground writes"));
	assert(!strstr(output, "compressed ratio (SWZ extents)"));
	fclose(capture);
	close(saved_stdout);
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
	assert(strstr(output, "SWZ compressed"));
	assert(strstr(output, "field 'bulk_padding'"));
	assert(strstr(output, "nonzero staged padding"));
	assert(!strstr(output, "cumulative padding"));
	assert(strstr(output, "Overall"));
	assert(!strstr(output, "SWZ compressed     1.33:1"));
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
	FILE *failed_capture = tmpfile();
	FILE *stdout_capture = tmpfile();
	int saved_stdout = dup(STDOUT_FILENO);
	int saved_stderr = dup(STDERR_FILENO);
	size_t bytes;
	int result;

	assert(capture && failed_capture && stdout_capture &&
	       saved_stderr >= 0 && saved_stdout >= 0);
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
	assert(dup2(fileno(failed_capture), STDERR_FILENO) >= 0);
	assert(report_device_status_with_reader(&fixture, read_fixture_observation,
						"fixture", 1, &report) == -2);
	fflush(stderr);
	assert(dup2(saved_stderr, STDERR_FILENO) >= 0);
	assert(!report.count && fixture.calls == 2);
	memset(diagnostic, 0, sizeof(diagnostic));
	rewind(failed_capture);
	bytes = fread(diagnostic, 1, sizeof(diagnostic) - 1U, failed_capture);
	diagnostic[bytes] = '\0';
	assert(strstr(diagnostic, "FAILED"));
	assert(strstr(diagnostic, "target 2 snapshot 2"));
	assert(strstr(diagnostic, "kernel errno=-5"));
	assert(!strstr(diagnostic, fixture_valid_status));
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
	fclose(failed_capture);
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


static void test_saturated_staged_padding_is_unavailable(void)
{
	const char *status =
		"logical_write=16384 physical_write=12288 gc_write=0 "
		"compressed=4 raw=0 zero_elided=0 bulk_mode=2 "
		"bulk_padding=4294967295 failed=0 error=0";
	struct swapz_ratio_status ratio;
	struct status_problem problem;
	FILE *capture = tmpfile();
	int saved_stdout = dup(STDOUT_FILENO);
	char output[2048] = { 0 };
	size_t bytes;

	assert(capture && saved_stdout >= 0);
	assert(parse_swapz_ratio_status_diagnostic(status, &ratio, &problem) ==
	       STATUS_READY);
	assert(ratio.bulk_padding_blocks == UINT_MAX);
	assert(!ratio.compressed_extent_ratio_exact);
	assert(ratio.compressed_extent_bytes == 0);
	assert(ratio.overall_physical_bytes == 12288);
	fflush(stdout);
	assert(dup2(fileno(capture), STDOUT_FILENO) >= 0);
	report_swapz_target("fixture", 0, &ratio);
	fflush(stdout);
	assert(dup2(saved_stdout, STDOUT_FILENO) >= 0);
	rewind(capture);
	bytes = fread(output, 1, sizeof(output) - 1U, capture);
	output[bytes] = '\0';
	assert(strstr(output, "SWZ compressed"));
	assert(strstr(output, "nonzero staged padding"));
	assert(strstr(output, "Overall"));
	assert(!strstr(output, "SWZ compressed     1.33:1"));
	close(saved_stdout);
	fclose(capture);
}

enum fake_inventory_change {
	FAKE_INVENTORY_STABLE,
	FAKE_INVENTORY_ADD,
	FAKE_INVENTORY_REMOVE,
	FAKE_INVENTORY_RENAME,
	FAKE_INVENTORY_REORDER,
	FAKE_INVENTORY_DEVICE,
	FAKE_INVENTORY_EVENT,
	FAKE_INVENTORY_UUID,
	FAKE_INVENTORY_MALFORMED,
	FAKE_INVENTORY_IOCTL_FAILURE,
	FAKE_INFO_FAILURE_AFTER_STAGE,
	FAKE_INFO_GENERATION_AFTER_STAGE
};

struct fake_list_device {
	const char *name;
	uint64_t device_id;
	uint32_t event_number;
	const char *uuid;
};

struct fake_inventory_ioctl {
	enum fake_inventory_change change;
	unsigned int list_reads;
	unsigned int status_reads;
	unsigned int devices_observed;
	size_t last_info_reply_size;
};

/* Fake DM_LIST_DEVICES, including its optional UUID metadata and record links. */
static int fake_list_devices_ioctl(void *context, unsigned char **reply,
				   size_t *reply_size)
{
	struct fake_inventory_ioctl *fixture = context;
	struct fake_list_device devices[3] = {
		{ "alpha", 1, 7, "uuid-alpha" },
		{ "beta", 2, 9, "uuid-beta" },
		{ "gamma", 3, 11, "uuid-gamma" }
	};
	const size_t capacity = 1024U;
	struct dm_ioctl header = { 0 };
	unsigned char *buffer;
	size_t record_offset = sizeof(header);
	size_t final_record_offset = record_offset;
	size_t count = 2;
	size_t index;
	int final_read = fixture->list_reads != 0;

	assert(fixture->list_reads < 2U);
	++fixture->list_reads;
	if (final_read) {
		switch (fixture->change) {
		case FAKE_INVENTORY_ADD:
			count = 3;
			break;
		case FAKE_INVENTORY_REMOVE:
			count = 1;
			break;
		case FAKE_INVENTORY_RENAME:
			devices[1].name = "renamed";
			break;
		case FAKE_INVENTORY_REORDER: {
			struct fake_list_device moved = devices[0];

			devices[0] = devices[1];
			devices[1] = moved;
			break;
		}
		case FAKE_INVENTORY_DEVICE:
			devices[1].device_id = 22;
			break;
		case FAKE_INVENTORY_EVENT:
			devices[1].event_number++;
			break;
		case FAKE_INVENTORY_UUID:
			devices[1].uuid = "uuid-replaced";
			break;
		case FAKE_INVENTORY_IOCTL_FAILURE:
			errno = EACCES;
			return -1;
		default:
			break;
		}
	}
	buffer = calloc(1, capacity);
	assert(buffer);
	for (index = 0; index < count; ++index) {
		const size_t name_offset = offsetof(struct dm_name_list, name);
		const size_t metadata_offset = fixture_align_target_offset(
			name_offset + strlen(devices[index].name) + 1U);
		const size_t uuid_offset = metadata_offset + 2U * sizeof(uint32_t);
		const size_t uuid_bytes = strlen(devices[index].uuid) + 1U;
		const size_t record_size = fixture_align_target_offset(uuid_offset + uuid_bytes);
		uint32_t flags = DM_NAME_LIST_FLAG_HAS_UUID;

		assert(record_offset + record_size <= capacity);
		final_record_offset = record_offset;
		assert(make_dm_name_list_fixture(buffer + record_offset,
				capacity - record_offset, devices[index].name,
				devices[index].device_id, devices[index].event_number) <=
		       record_size);
		memcpy(buffer + record_offset + metadata_offset + sizeof(uint32_t),
		       &flags, sizeof(flags));
		memcpy(buffer + record_offset + uuid_offset,
		       devices[index].uuid, uuid_bytes);
		if (index + 1U < count) {
			uint32_t next = (uint32_t)record_size;

			memcpy(buffer + record_offset + offsetof(struct dm_name_list, next),
			       &next, sizeof(next));
		}
		record_offset += record_size;
	}
	if (final_read && fixture->change == FAKE_INVENTORY_MALFORMED) {
		uint32_t invalid_next = 23U;

		memcpy(buffer + final_record_offset +
		       offsetof(struct dm_name_list, next),
		       &invalid_next, sizeof(invalid_next));
	}
	header.data_start = sizeof(header);
	header.data_size = (uint32_t)record_offset;
	memcpy(buffer, &header, sizeof(header));
	*reply = buffer;
	*reply_size = capacity;
	return 0;
}

/*
 * Fake DM_TABLE_STATUS with the exact initially enumerated name, device and
 * generation. The production parser and generation binding must both pass.
 */
struct fake_status_snapshot_reader {
	uint32_t event_number;
	unsigned int calls;
	size_t last_reply_size;
};

static int fake_read_status_observation_ioctl(
	void *context, const char *name, uint64_t expected_device,
	struct dm_status_observation *observation,
	struct status_problem *problem, unsigned int *problem_target)
{
	struct fake_status_snapshot_reader *reader = context;
	const char *const target_types[] = { "swapz" };
	const char *const target_statuses[] = { fixture_valid_status };
	unsigned char *buffer = malloc(2048U);
	struct dm_ioctl header;
	size_t reply_size;
	int result;

	assert(buffer);
	reply_size = make_dm_multi_fixture(buffer, 2048U, target_types,
					   target_statuses, NULL, 1, expected_device);
	reader->last_reply_size = reply_size;
	memcpy(&header, buffer, sizeof(header));
	memset(header.name, 0, sizeof(header.name));
	assert(strlen(name) < sizeof(header.name));
	memcpy(header.name, name, strlen(name) + 1U);
	header.event_nr = reader->event_number;
	memcpy(buffer, &header, sizeof(header));
	++reader->calls;
	memset(observation, 0, sizeof(*observation));
	observation->reply = buffer;
	result = parse_dm_status_observation(buffer, reply_size, name,
					     expected_device, observation,
					     problem, problem_target);
	return status_bind_list_generation(result, observation,
					   reader->event_number,
					   problem, problem_target);
}

/* Each initially listed mapping yields two unchanged fake DM_TABLE_STATUS replies. */
static int fake_device_status_ioctl(void *context, const char *name,
				    uint64_t device_id, uint32_t event_number,
				    struct status_ready_report *report)
{
	struct fake_inventory_ioctl *fixture = context;
	struct fake_status_snapshot_reader observations = {
		.event_number = event_number
	};
	int result;

	assert(fixture->list_reads == 1U);
	assert(fixture->devices_observed < 2U);
	assert(!strcmp(name, fixture->devices_observed ? "beta" : "alpha"));
	assert(device_id == (uint64_t)fixture->devices_observed + 1U);
	assert(event_number == (fixture->devices_observed ? 9U : 7U));
	result = report_device_status_with_reader(&observations,
			fake_read_status_observation_ioctl, name, device_id, report);
	fixture->status_reads += (unsigned int)observations.calls;
	++fixture->devices_observed;
	return result;
}

static void test_final_inventory_fake_ioctl_observation_gap(void)
{
	const enum fake_inventory_change changes[] = {
		FAKE_INVENTORY_STABLE, FAKE_INVENTORY_ADD,
		FAKE_INVENTORY_REMOVE, FAKE_INVENTORY_RENAME,
		FAKE_INVENTORY_REORDER, FAKE_INVENTORY_DEVICE,
		FAKE_INVENTORY_EVENT, FAKE_INVENTORY_UUID,
		FAKE_INVENTORY_MALFORMED, FAKE_INVENTORY_IOCTL_FAILURE
	};
	size_t case_index;

	for (case_index = 0; case_index < sizeof(changes) / sizeof(changes[0]);
	     ++case_index) {
		struct fake_inventory_ioctl fixture = { .change = changes[case_index] };
		struct status_ready_report report = { 0 };
		FILE *stdout_capture = tmpfile();
		FILE *stderr_capture = tmpfile();
		int saved_stdout = dup(STDOUT_FILENO);
		int saved_stderr = dup(STDERR_FILENO);
		char output[2048] = { 0 };
		char diagnostic[2048] = { 0 };
		size_t output_bytes;
		size_t diagnostic_bytes;
		size_t target;
		int result;

		assert(stdout_capture && stderr_capture);
		assert(saved_stdout >= 0 && saved_stderr >= 0);
		fflush(stdout);
		fflush(stderr);
		assert(dup2(fileno(stdout_capture), STDOUT_FILENO) >= 0);
		assert(dup2(fileno(stderr_capture), STDERR_FILENO) >= 0);
		result = status_collect_targets_with_readers(
			&fixture, fake_list_devices_ioctl, fake_device_status_ioctl, &report);
		/* Match the CLI's all-or-nothing output gate. */
		if (!result)
			for (target = 0; target < report.count; ++target)
				report_swapz_target(report.targets[target].name,
						    report.targets[target].target_index,
						    &report.targets[target].ratio);
		fflush(stdout);
		fflush(stderr);
		assert(dup2(saved_stdout, STDOUT_FILENO) >= 0);
		assert(dup2(saved_stderr, STDERR_FILENO) >= 0);
		rewind(stdout_capture);
		output_bytes = fread(output, 1, sizeof(output) - 1U, stdout_capture);
		output[output_bytes] = '\0';
		rewind(stderr_capture);
		diagnostic_bytes = fread(diagnostic, 1, sizeof(diagnostic) - 1U,
					 stderr_capture);
		diagnostic[diagnostic_bytes] = '\0';
		assert(fixture.list_reads == 2U);
		assert(fixture.devices_observed == 2U);
		assert(fixture.status_reads == 4U);
		assert(report.count == 2U);
		if (fixture.change == FAKE_INVENTORY_STABLE) {
			assert(result == 0);
			assert(strstr(output, "Ratios (logical / lower, foreground)"));
			assert(!diagnostic_bytes);
		} else {
			assert(result != 0);
			assert(!output_bytes); /* No staged numeric metric can escape. */
			assert(strstr(diagnostic, "DM_LIST_DEVICES"));
			assert(strstr(diagnostic,
				fixture.change == FAKE_INVENTORY_MALFORMED ?
				"BLOCKED" : "UNAVAILABLE"));
		}
		free(report.targets);
		close(saved_stdout);
		close(saved_stderr);
		fclose(stdout_capture);
		fclose(stderr_capture);
	}
}


/*
 * Deterministic malformed DM wire corpus. These are synthetic ioctl reply
 * bytes consumed by the included production parsers, not a parser model.
 * Keep capacities fixed: a corrupt count/offset must never drive allocation
 * or traversal proportional to its untrusted value.
 */
static void expect_adversarial_status_failure(
	const char *phase, size_t case_index, const unsigned char *buffer,
	size_t reply_size, size_t expected_wire_bound, size_t observed_offset,
	size_t observed_length, const char *expected_field,
	unsigned int expected_target, int require_no_target_allocation)
{
	struct dm_status_observation observation = { 0 };
	struct status_problem problem = { 0 };
	unsigned int problem_target = UINT_MAX;
	int parser_result;
	int original_errno;
	int target_allocation_observed;

	errno = 0;
	parser_result = parse_fixture(buffer, reply_size, 1, &observation,
				      &problem, &problem_target);
	original_errno = errno;
	target_allocation_observed = observation.targets != NULL;
	status_free_observation(&observation);
	if (parser_result >= 0 || !problem.field ||
	    strcmp(problem.field, expected_field) ||
	    problem_target != expected_target ||
	    (require_no_target_allocation && target_allocation_observed)) {
		fprintf(stderr,
			"adversarial DM_TABLE_STATUS %s case=%zu: expected wire bound=%zu "
			"field=%s target=%u allocation=%s; observed offset=%zu length=%zu "
			"result=%d field=%s target=%u allocation=%s; "
			"parser expected=%s; parser observed=%s; original errno=%d (%s)\n",
			phase, case_index, expected_wire_bound, expected_field,
			expected_target,
			require_no_target_allocation ? "none" : "bounded",
			observed_offset, observed_length, parser_result,
			problem.field ? problem.field : "(none)", problem_target,
			target_allocation_observed ? "yes" : "no",
			problem.expected ? problem.expected : "(none)",
			problem.observed ? problem.observed : "(none)",
			original_errno, strerror(original_errno));
		abort();
	}
}

static void expect_adversarial_list_failure(
	const char *phase, size_t case_index, const unsigned char *record,
	size_t record_size, size_t expected_wire_bound, size_t observed_offset,
	size_t observed_length, const char *expected_field)
{
	struct dm_list_record parsed;
	struct status_problem problem = { 0 };
	int parser_result;
	int original_errno;

	errno = 0;
	parser_result = status_parse_name_list_record(record, record_size,
						      &parsed, &problem);
	original_errno = errno;
	if (parser_result >= 0 || !problem.field ||
	    strcmp(problem.field, expected_field)) {
		fprintf(stderr,
			"adversarial DM_LIST_DEVICES %s case=%zu: expected wire bound=%zu "
			"field=%s; observed offset=%zu length=%zu result=%d field=%s; "
			"parser expected=%s; parser observed=%s; original errno=%d (%s)\n",
			phase, case_index, expected_wire_bound, expected_field,
			observed_offset, observed_length, parser_result,
			problem.field ? problem.field : "(none)",
			problem.expected ? problem.expected : "(none)",
			problem.observed ? problem.observed : "(none)",
			original_errno, strerror(original_errno));
		abort();
	}
}

static void test_bounded_adversarial_dm_status_corpus(void)
{
	enum { CORPUS_CASES = 256 };
	const char *const types[] = { "swapz", "swapz" };
	const char *const statuses[] = {
		fixture_valid_status, fixture_valid_status
	};
	uint32_t generator_state = UINT32_C(0x9e3779b9);
	size_t case_index;

	/* Eight mutation classes, 32 seeded variants each; no random runtime seed. */
	for (case_index = 0; case_index < CORPUS_CASES; ++case_index) {
		unsigned char buffer[2048];
		struct dm_ioctl header;
		struct dm_target_spec specification;
		const char *expected_field = NULL;
		unsigned int expected_target = UINT_MAX;
		size_t observed_offset = 0;
		size_t observed_length = 0;
		size_t record_offset = sizeof(header);
		size_t reply_size = make_dm_multi_fixture(
			buffer, sizeof(buffer), types, statuses, NULL, 2, 1);

		generator_state = generator_state * UINT32_C(1664525) +
				  UINT32_C(1013904223);
		memcpy(&header, buffer, sizeof(header));
		memcpy(&specification, buffer + record_offset,
		       sizeof(specification));
		switch (case_index % 8U) {
		case 0:
			header.data_start = (uint32_t)sizeof(header) +
					    1U + generator_state % 7U;
			observed_offset = header.data_start;
			observed_length = header.data_size;
			expected_field = "dm_ioctl.data_start/data_size";
			break;
		case 1:
			header.data_size = UINT32_MAX - generator_state % 32U;
			observed_offset = header.data_start;
			observed_length = header.data_size;
			expected_field = "dm_ioctl.data_start/data_size";
			break;
		case 2:
			header.target_count = SWAPZ_STATUS_MAX_TARGETS + 1U +
					      generator_state % 128U;
			observed_length = header.target_count;
			expected_field = "dm_target_spec.next";
			break;
		case 3:
			specification.next = UINT32_MAX - generator_state % 64U;
			observed_offset = specification.next;
			observed_length = sizeof(specification);
			expected_field = "dm_target_spec.next";
			expected_target = 0;
			break;
		case 4:
			assert((size_t)specification.next <=
			       reply_size - sizeof(header));
			record_offset += specification.next;
			memcpy(&specification, buffer + record_offset,
			       sizeof(specification));
			specification.next = UINT32_MAX - generator_state % 64U;
			observed_offset = specification.next;
			observed_length = sizeof(specification);
			expected_field = "dm_target_spec.next";
			expected_target = 1;
			break;
		case 5:
			memset(header.name, 'n', sizeof(header.name));
			observed_length = sizeof(header.name);
			expected_field = "dm_ioctl.name";
			break;
		case 6:
			if (generator_state & UINT32_C(0x100)) {
				specification.sector_start = UINT64_MAX;
				specification.length = 2U;
			} else {
				specification.length = 0;
			}
			observed_offset = record_offset;
			observed_length = sizeof(specification);
			expected_field = "dm_target_spec.sector_start/length";
			expected_target = 0;
			break;
		default:
			header.flags |= DM_STATUS_TABLE_FLAG;
			observed_length = header.flags;
			expected_field = "dm_ioctl.flags";
			break;
		}
		memcpy(buffer, &header, sizeof(header));
		if (case_index % 8U == 3U || case_index % 8U == 4U ||
		    case_index % 8U == 6U)
			memcpy(buffer + record_offset, &specification,
			       sizeof(specification));
		expect_adversarial_status_failure(
			"bounded-record-mutation", case_index, buffer, reply_size,
			reply_size, observed_offset, observed_length,
			expected_field, expected_target,
			case_index % 8U == 2U);
	}
}

static void test_bounded_adversarial_dm_list_corpus(void)
{
	enum { CORPUS_CASES = 64 };
	uint32_t generator_state = UINT32_C(0x6d2b79f5);
	size_t case_index;

	for (case_index = 0; case_index < CORPUS_CASES; ++case_index) {
		unsigned char record[256];
		const size_t name_offset = offsetof(struct dm_name_list, name);
		const size_t metadata_offset = fixture_align_target_offset(
			name_offset + sizeof("a"));
		size_t record_size = make_dm_name_list_fixture(
			record, sizeof(record), "a", 7, 11);
		const char *expected_field;
		size_t observed_offset = 0;
		size_t observed_length = record_size;
		uint32_t next;
		uint32_t flags;

		generator_state = generator_state * UINT32_C(1664525) +
				  UINT32_C(1013904223);
		switch (case_index % 4U) {
		case 0:
			next = 1U + generator_state % 7U;
			memcpy(record + offsetof(struct dm_name_list, next),
			       &next, sizeof(next));
			observed_offset = next;
			expected_field = "dm_name_list.next";
			break;
		case 1:
			next = UINT32_MAX - generator_state % 7U;
			memcpy(record + offsetof(struct dm_name_list, next),
			       &next, sizeof(next));
			observed_offset = next;
			expected_field = "dm_name_list.next";
			break;
		case 2:
			memset(record + name_offset, 'n', record_size - name_offset);
			observed_offset = name_offset;
			expected_field = "dm_name_list.name";
			break;
		default:
			flags = DM_NAME_LIST_FLAG_HAS_UUID;
			memcpy(record + metadata_offset + sizeof(uint32_t),
			       &flags, sizeof(flags));
			observed_offset = metadata_offset + 2U * sizeof(uint32_t);
			expected_field = "dm_name_list.uuid";
			break;
		}
		expect_adversarial_list_failure(
			"bounded-record-mutation", case_index, record, record_size,
			record_size, observed_offset, observed_length, expected_field);
	}
}

static void test_adversarial_dm_list_header_bounds(void)
{
	enum { CORPUS_CASES = 32 };
	unsigned char buffer[sizeof(struct dm_ioctl) + 32U] = { 0 };
	struct dm_ioctl header = { 0 };
	struct dm_ioctl parsed;
	struct status_problem problem = { 0 };
	size_t case_index;

	/* A zero-entry device list is legitimate; an invalid header is not. */
	header.data_start = sizeof(header);
	header.data_size = sizeof(header);
	memcpy(buffer, &header, sizeof(header));
	assert(status_parse_list_header(buffer, sizeof(buffer),
					&parsed, &problem) == 0);
	for (case_index = 0; case_index < CORPUS_CASES; ++case_index) {
		size_t observed_offset;
		size_t observed_length;
		int parser_result;
		int original_errno;

		header.data_start = sizeof(header);
		header.data_size = sizeof(buffer);
		if (case_index & 1U)
			header.data_start += 1U + (uint32_t)(case_index % 7U);
		else
			header.data_size = UINT32_MAX - (uint32_t)case_index;
		observed_offset = header.data_start;
		observed_length = header.data_size;
		memcpy(buffer, &header, sizeof(header));
		errno = 0;
		parser_result = status_parse_list_header(buffer, sizeof(buffer),
							&parsed, &problem);
		original_errno = errno;
		if (parser_result >= 0 || !problem.field ||
		    strcmp(problem.field, "dm_ioctl.data_start/data_size")) {
			fprintf(stderr,
				"adversarial DM_LIST_DEVICES header-bounds case=%zu: "
				"expected wire bound=%zu field=dm_ioctl.data_start/data_size; "
				"observed offset=%zu length=%zu result=%d field=%s; "
				"parser expected=%s; parser observed=%s; "
				"original errno=%d (%s)\n",
				case_index, sizeof(buffer), observed_offset,
				observed_length, parser_result,
				problem.field ? problem.field : "(none)",
				problem.expected ? problem.expected : "(none)",
				problem.observed ? problem.observed : "(none)",
				original_errno, strerror(original_errno));
			abort();
		}
	}
}

static void test_adversarial_wire_boundaries(void)
{
	const char *const types[] = { "swapz", "swapz" };
	const char *const statuses[] = {
		fixture_valid_status, fixture_valid_status
	};
	unsigned char buffer[2048];
	unsigned char name_record[512];
	struct dm_ioctl header;
	struct dm_target_spec specification;
	struct dm_list_record parsed;
	struct status_problem problem = { 0 };
	char maximum_name[DM_NAME_LEN];
	size_t aligned_offset = 0;
	size_t reply_size;
	size_t record_offset;
	size_t record_size;
	size_t metadata_offset;
	uint32_t flags;
	uint32_t next;

	assert(sizeof(struct dm_target_spec) == 40U);
	assert(offsetof(struct dm_name_list, name) == 12U);
	assert(sizeof(struct dm_ioctl) % SWAPZ_DM_WIRE_ALIGNMENT == 0U);

	reply_size = make_dm_multi_fixture(buffer, sizeof(buffer),
					    types, statuses, NULL, 2, 1);
	memcpy(&header, buffer, sizeof(header));
	memcpy(&specification, buffer + sizeof(header), sizeof(specification));
	record_offset = sizeof(header) + specification.next;
	/* An aligned forward skip and a backwards/looping last offset must fail. */
	specification.next += SWAPZ_DM_WIRE_ALIGNMENT;
	memcpy(buffer + sizeof(header), &specification, sizeof(specification));
	expect_adversarial_status_failure(
		"aligned-gap", 0, buffer, reply_size, header.data_size,
		specification.next, sizeof(specification), "dm_target_spec.next", 0, 0);

	reply_size = make_dm_multi_fixture(buffer, sizeof(buffer),
					    types, statuses, NULL, 2, 1);
	memcpy(&header, buffer, sizeof(header));
	memcpy(&specification, buffer + sizeof(header), sizeof(specification));
	record_offset = sizeof(header) + specification.next;
	next = specification.next;
	memcpy(buffer + record_offset + offsetof(struct dm_target_spec, next),
	       &next, sizeof(next));
	expect_adversarial_status_failure(
		"looping-final-next", 1, buffer, reply_size, header.data_size,
		next, sizeof(specification), "dm_target_spec.next", 1, 0);

	reply_size = make_dm_multi_fixture(buffer, sizeof(buffer),
					    types, statuses, NULL, 2, 1);
	memcpy(&header, buffer, sizeof(header));
	memcpy(&specification, buffer + sizeof(header), sizeof(specification));
	record_offset = sizeof(header) + specification.next;
	/* The final NUL is required even when the caller buffer has zero slack. */
	buffer[header.data_size - 1U] = 'X';
	expect_adversarial_status_failure(
		"missing-final-status-nul", 2, buffer, reply_size, header.data_size,
		header.data_size - 1U, 1U, "dm_target_spec.params", 1, 0);

	reply_size = make_dm_multi_fixture(buffer, sizeof(buffer),
					    types, statuses, NULL, 2, 1);
	memcpy(&header, buffer, sizeof(header));
	memcpy(&specification, buffer + sizeof(header), sizeof(specification));
	memset(specification.target_type, 't', sizeof(specification.target_type));
	memcpy(buffer + sizeof(header), &specification, sizeof(specification));
	expect_adversarial_status_failure(
		"missing-type-nul", 3, buffer, reply_size, header.data_size,
		sizeof(header), sizeof(specification.target_type),
		"dm_target_spec.target_type", 0, 0);

	reply_size = make_dm_multi_fixture(buffer, sizeof(buffer),
					    types, statuses, NULL, 2, 1);
	memcpy(&header, buffer, sizeof(header));
	memcpy(&specification, buffer + sizeof(header), sizeof(specification));
	specification.length = 0;
	memcpy(buffer + sizeof(header), &specification, sizeof(specification));
	expect_adversarial_status_failure(
		"zero-target-length", 4, buffer, reply_size, header.data_size,
		sizeof(header), 0, "dm_target_spec.sector_start/length", 0, 0);

	reply_size = make_dm_multi_fixture(buffer, sizeof(buffer),
					    types, statuses, NULL, 2, 1);
	memcpy(&header, buffer, sizeof(header));
	header.target_count = UINT32_MAX;
	memcpy(buffer, &header, sizeof(header));
	expect_adversarial_status_failure(
		"impossible-target-count", 5, buffer, reply_size, header.data_size,
		header.data_start, header.target_count, "dm_target_spec.next",
		UINT_MAX, 1);

	reply_size = make_dm_multi_fixture(buffer, sizeof(buffer),
					    types, statuses, NULL, 2, 1);
	memcpy(&header, buffer, sizeof(header));
	header.target_count = SWAPZ_STATUS_MAX_TARGETS;
	memcpy(buffer, &header, sizeof(header));
	expect_adversarial_status_failure(
		"max-count-with-short-payload", 6, buffer, reply_size,
		header.data_size, header.data_start, header.target_count,
		"dm_target_spec.next", UINT_MAX, 1);

	errno = 0;
	if (status_align_target_offset(SIZE_MAX, &aligned_offset) == 0) {
		const int original_errno = errno;

		fprintf(stderr,
			"adversarial DM wire alignment-overflow case=7: "
			"expected wire bound=%zu without size_t wrap; "
			"observed offset=%zu length=%u; original errno=%d (%s)\n",
			SIZE_MAX, aligned_offset, SWAPZ_DM_WIRE_ALIGNMENT,
			original_errno, strerror(original_errno));
		abort();
	}

	/* The name terminator, metadata and optional UUID each have own bounds. */
	record_size = make_dm_name_list_fixture(name_record, sizeof(name_record),
						"a", 7, 11);
	assert(record_size == 24U);
	expect_adversarial_list_failure(
		"truncated-metadata", 0, name_record, 16U, record_size,
		offsetof(struct dm_name_list, name), 16U,
		"dm_name_list.event_nr/flags");
	expect_adversarial_list_failure(
		"truncated-name-header", 1, name_record,
		offsetof(struct dm_name_list, name), record_size, 0,
		offsetof(struct dm_name_list, name), "dm_name_list");

	record_size = make_dm_name_list_fixture(name_record, sizeof(name_record),
						"a", 7, 11);
	assert(record_size <= sizeof(name_record) - SWAPZ_DM_WIRE_ALIGNMENT);
	metadata_offset = fixture_align_target_offset(
		offsetof(struct dm_name_list, name) + sizeof("a"));
	flags = DM_NAME_LIST_FLAG_HAS_UUID;
	memcpy(name_record + metadata_offset + sizeof(uint32_t),
	       &flags, sizeof(flags));
	memset(name_record + record_size, 'u', SWAPZ_DM_WIRE_ALIGNMENT);
	expect_adversarial_list_failure(
		"unterminated-uuid", 2, name_record,
		record_size + SWAPZ_DM_WIRE_ALIGNMENT, record_size,
		record_size, SWAPZ_DM_WIRE_ALIGNMENT, "dm_name_list.uuid");

	/* The exact maximum bounded name and a terminated UUID are legitimate. */
	memset(maximum_name, 'm', sizeof(maximum_name) - 1U);
	maximum_name[sizeof(maximum_name) - 1U] = '\0';
	record_size = make_dm_name_list_fixture(name_record, sizeof(name_record),
						maximum_name, 7, 11);
	assert(status_parse_name_list_record(name_record, record_size,
					      &parsed, &problem) == 0);
	assert(strlen(parsed.name) == DM_NAME_LEN - 1U);
	record_size = make_dm_name_list_fixture(name_record, sizeof(name_record),
						"a", 7, 11);
	memcpy(name_record + metadata_offset + sizeof(uint32_t),
	       &flags, sizeof(flags));
	memcpy(name_record + record_size, "uuid", sizeof("uuid"));
	assert(status_parse_name_list_record(
		name_record, record_size + SWAPZ_DM_WIRE_ALIGNMENT,
		&parsed, &problem) == 0);
	assert(parsed.uuid && !strcmp(parsed.uuid, "uuid"));
}

/* The first binding in the shared fake reader is intentionally self-consistent.
 * Bind once more to the *listed* generation to inject INFO-after-LIST drift.
 */
static int fake_drifted_generation_observation(
	void *context, const char *name, uint64_t expected_device,
	struct dm_status_observation *observation,
	struct status_problem *problem, unsigned int *problem_target)
{
	const struct fake_status_snapshot_reader *reader = context;
	int result = fake_read_status_observation_ioctl(
		context, name, expected_device, observation, problem,
		problem_target);

	return status_bind_list_generation(result, observation,
					   reader->event_number - 1U,
					   problem, problem_target);
}

static int fake_adversarial_device_status_ioctl(
	void *context, const char *name, uint64_t device_id,
	uint32_t event_number, struct status_ready_report *report)
{
	struct fake_inventory_ioctl *fixture = context;

	if (!fixture->devices_observed)
		return fake_device_status_ioctl(context, name, device_id,
						event_number, report);
	assert(fixture->devices_observed == 1U);
	++fixture->devices_observed;
	if (fixture->change == FAKE_INFO_FAILURE_AFTER_STAGE) {
		errno = EIO;
		return status_report_ioctl_failure(name, device_id, 1, errno);
	}
	{
		struct fake_status_snapshot_reader reader = {
			.event_number = event_number + 1U
		};
		int result = report_device_status_with_reader(
			&reader, fake_drifted_generation_observation,
			name, device_id, report);

		fixture->status_reads += reader.calls;
		fixture->last_info_reply_size = reader.last_reply_size;
		return result;
	}
}

static void test_adversarial_failed_info_after_staging(void)
{
	const enum fake_inventory_change changes[] = {
		FAKE_INFO_FAILURE_AFTER_STAGE, FAKE_INFO_GENERATION_AFTER_STAGE
	};
	size_t case_index;

	for (case_index = 0; case_index < sizeof(changes) / sizeof(changes[0]);
	     ++case_index) {
		struct fake_inventory_ioctl fixture = { .change = changes[case_index] };
		struct status_ready_report report = { 0 };
		FILE *stdout_capture = tmpfile();
		FILE *stderr_capture = tmpfile();
		int saved_stdout = dup(STDOUT_FILENO);
		int saved_stderr = dup(STDERR_FILENO);
		char output[1024] = { 0 };
		char diagnostic[1024] = { 0 };
		size_t output_bytes;
		size_t diagnostic_bytes;
		int result;
		int original_errno;

		assert(stdout_capture && stderr_capture);
		assert(saved_stdout >= 0 && saved_stderr >= 0);
		fflush(stdout);
		fflush(stderr);
		assert(dup2(fileno(stdout_capture), STDOUT_FILENO) >= 0);
		assert(dup2(fileno(stderr_capture), STDERR_FILENO) >= 0);
		result = status_collect_targets_with_readers(
			&fixture, fake_list_devices_ioctl,
			fake_adversarial_device_status_ioctl, &report);
		original_errno = errno;
		/* Exactly the CLI output gate: staged metrics are never printed. */
		if (!result)
			for (size_t target = 0; target < report.count; ++target)
				report_swapz_target(report.targets[target].name,
						    report.targets[target].target_index,
						    &report.targets[target].ratio);
		fflush(stdout);
		fflush(stderr);
		assert(dup2(saved_stdout, STDOUT_FILENO) >= 0);
		assert(dup2(saved_stderr, STDERR_FILENO) >= 0);
		rewind(stdout_capture);
		output_bytes = fread(output, 1, sizeof(output) - 1U, stdout_capture);
		rewind(stderr_capture);
		diagnostic_bytes = fread(diagnostic, 1,
					 sizeof(diagnostic) - 1U, stderr_capture);
		diagnostic[diagnostic_bytes] = '\0';
		if (!result || output_bytes || report.count != 1U ||
		    fixture.list_reads != 1U || fixture.devices_observed != 2U ||
		    fixture.status_reads !=
		    (changes[case_index] == FAKE_INFO_FAILURE_AFTER_STAGE ? 2U : 3U) ||
		    !strstr(diagnostic, "snapshot 1") ||
		    !strstr(diagnostic,
			    changes[case_index] == FAKE_INFO_FAILURE_AFTER_STAGE ?
			    "DM_TABLE_STATUS errno=5" : "dm_ioctl.event_nr") ||
		    (changes[case_index] == FAKE_INFO_GENERATION_AFTER_STAGE &&
		     !strstr(diagnostic, "errno=11")) ||
		    original_errno !=
		    (changes[case_index] == FAKE_INFO_FAILURE_AFTER_STAGE ?
		     EIO : EAGAIN)) {
			fprintf(stderr,
				"adversarial staged INFO case=%zu phase=%s: expected complete "
				"first inventory and no published bytes, wire bound=%zu; "
				"observed offset=0 length=%zu list=%u INFO=%u staged=%zu "
				"stdout=%zu diagnostic=%zu result=%d; original errno=%d (%s)\n",
				case_index,
				changes[case_index] == FAKE_INFO_FAILURE_AFTER_STAGE ?
				"failed-INFO-after-stage" : "event-generation-after-stage",
				fixture.last_info_reply_size, fixture.last_info_reply_size,
				fixture.list_reads, fixture.status_reads, report.count,
				output_bytes, diagnostic_bytes, result,
				original_errno, strerror(original_errno));
			abort();
		}
		free(report.targets);
		close(saved_stdout);
		close(saved_stderr);
		fclose(stdout_capture);
		fclose(stderr_capture);
	}
}


/*
 * Reproduce INFO bounded-read errors through the production observation
 * reporter. A successful neighboring read uses the production DM parser.
 * Do not substitute EPROTO for the original EOVERFLOW/ENOMEM diagnosis.
 */
struct fake_status_errno_reader {
	struct fake_status_snapshot_reader successful_read;
	unsigned int calls;
	unsigned int failing_read;
	int failure_errno;
};

static int fake_status_errno_observation(
	void *context, const char *name, uint64_t expected_device,
	struct dm_status_observation *observation,
	struct status_problem *problem, unsigned int *problem_target)
{
	struct fake_status_errno_reader *fixture = context;
	unsigned int read_index = fixture->calls++;

	if (read_index != fixture->failing_read)
		return fake_read_status_observation_ioctl(
			&fixture->successful_read, name, expected_device,
			observation, problem, problem_target);
	*problem_target = UINT_MAX;
	if (fixture->failure_errno == EOVERFLOW)
		status_set_problem(problem, "DM_BUFFER_FULL_FLAG",
				   "complete INFO reply within 1048576 bytes",
				   "reply remained buffer-full");
	else
		status_set_problem(problem, "DM target inventory",
				   "bounded snapshot allocation", "allocation failed");
	problem->failure_errno = fixture->failure_errno;
	errno = fixture->failure_errno;
	return -1;
}

static void test_status_info_errno_precedence(void)
{
	const int failures[] = { EOVERFLOW, ENOMEM };
	size_t failure_index;
	unsigned int failing_read;

	for (failure_index = 0; failure_index < sizeof(failures) / sizeof(failures[0]);
	     ++failure_index) {
		for (failing_read = 0; failing_read < 2U; ++failing_read) {
			struct fake_status_errno_reader fixture = {
				.failing_read = failing_read,
				.failure_errno = failures[failure_index]
			};
			struct status_ready_report report = { 0 };
			FILE *capture = tmpfile();
			int saved_stderr = dup(STDERR_FILENO);
			char diagnostic[1024] = { 0 };
			char errno_text[32];
			size_t bytes;
			int result;
			int original_errno;

			assert(capture && saved_stderr >= 0);
			fflush(stderr);
			assert(dup2(fileno(capture), STDERR_FILENO) >= 0);
			result = report_device_status_with_reader(
				&fixture, fake_status_errno_observation,
				"fixture", 1, &report);
			original_errno = errno;
			fflush(stderr);
			assert(dup2(saved_stderr, STDERR_FILENO) >= 0);
			rewind(capture);
			bytes = fread(diagnostic, 1, sizeof(diagnostic) - 1U, capture);
			diagnostic[bytes] = '\0';
			assert(snprintf(errno_text, sizeof(errno_text), "errno=%d",
					failures[failure_index]) > 0);
			if (result != -2 || original_errno != failures[failure_index] ||
			    fixture.calls != failing_read + 1U ||
			    fixture.successful_read.calls != failing_read ||
			    report.count || !strstr(diagnostic, "UNAVAILABLE") ||
			    !strstr(diagnostic, "mapping 'fixture' device 0:1") ||
			    !strstr(diagnostic, failing_read ? "snapshot 2" : "snapshot 1") ||
			    !strstr(diagnostic, failures[failure_index] == EOVERFLOW ?
				    "DM_BUFFER_FULL_FLAG" : "DM target inventory") ||
			    !strstr(diagnostic, errno_text) ||
			    strstr(diagnostic, fixture_valid_status)) {
				fprintf(stderr,
					"bounded INFO errno case=%zu read=%u: result=%d "
					"errno=%d expected=%d calls=%u parsed=%u staged=%zu "
					"diagnostic_bytes=%zu\n",
					failure_index, failing_read, result, original_errno,
					failures[failure_index], fixture.calls,
					fixture.successful_read.calls, report.count, bytes);
				abort();
			}
			free(report.targets);
			close(saved_stderr);
			fclose(capture);
		}
	}
}


static void test_production_dm_query_error_precedence(void)
{
	struct dm_status_observation observation = { 0 };
	struct status_problem problem = { 0 };
	unsigned int problem_target = UINT_MAX;

	fake_dm_ioctl_behavior = FAKE_DM_IOCTL_BUFFER_FULL;
	fake_dm_ioctl_calls = 0;
	assert(read_dm_status_observation(-1, "fixture", 1, &observation,
					  &problem, &problem_target) < 0);
	assert(fake_dm_ioctl_calls == 5U);
	assert(errno == EOVERFLOW);
	assert(problem.failure_errno == EOVERFLOW);
	assert(problem.field && !strcmp(problem.field, "DM_BUFFER_FULL_FLAG"));
	assert(problem_target == UINT_MAX);
	assert(!observation.reply && !observation.targets);

	fake_dm_ioctl_behavior = FAKE_DM_IOCTL_BAD_HEADER;
	fake_dm_ioctl_calls = 0;
	memset(&problem, 0, sizeof(problem));
	assert(read_dm_status_observation(-1, "fixture", 1, &observation,
					  &problem, &problem_target) < 0);
	assert(fake_dm_ioctl_calls == 1U);
	assert(errno == EPROTO);
	assert(problem.failure_errno == EPROTO);
	assert(problem.field &&
	       !strcmp(problem.field, "dm_ioctl.data_start/data_size"));
	assert(problem_target == UINT_MAX);
	assert(!observation.reply && !observation.targets);

	fake_dm_ioctl_behavior = FAKE_DM_IOCTL_ERROR;
	fake_dm_ioctl_error = EACCES;
	fake_dm_ioctl_calls = 0;
	memset(&problem, 0, sizeof(problem));
	assert(read_dm_status_observation(-1, "fixture", 1, &observation,
					  &problem, &problem_target) < 0);
	assert(fake_dm_ioctl_calls == 1U);
	assert(errno == EACCES);
	assert(problem.failure_errno == EACCES);
	assert(!problem.field);
	assert(problem_target == UINT_MAX);
	assert(!observation.reply && !observation.targets);

	fake_dm_ioctl_behavior = FAKE_DM_IOCTL_DISABLED;
	fake_dm_ioctl_error = 0;
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
	test_unsigned_decimal_parser_bounds();
	test_required_tokens_duplicates_and_canonical_numbers();
	test_checked_counter_arithmetic();
	test_dm_wire_alignment_is_host_independent();
	test_empty_dm_target_inventory();
	test_list_query_requests_mapping_uuids();
	test_dm_name_list_wire_records();
	test_list_generation_binding();
	test_dm_reply_boundaries_and_identity();
	test_absolute_offsets_for_multiple_dm_targets();
	test_full_target_inventory_comparison();
	test_page_count_grouping();
	test_status_report_groups_live_swapz_counts();
	test_padding_output_has_no_fabricated_compressed_ratio();
	test_saturated_staged_padding_is_unavailable();
	test_snapshot_retry_exhaustion_and_failures();
	test_complete_snapshot_before_output();
	test_final_inventory_fake_ioctl_observation_gap();
	test_bounded_adversarial_dm_status_corpus();
	test_bounded_adversarial_dm_list_corpus();
	test_adversarial_dm_list_header_bounds();
	test_adversarial_wire_boundaries();
	test_adversarial_failed_info_after_staging();
	test_status_info_errno_precedence();
	test_production_dm_query_error_precedence();
	test_status_is_read_only();
	puts("PASS: swapzctl status compression-ratio accounting");
	return 0;
}
