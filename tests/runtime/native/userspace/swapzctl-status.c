// SPDX-License-Identifier: GPL-2.0-only
#define ioctl swapzctl_status_test_ioctl
#define main swapzctl_program_main
#include "../../../../src/userspace/swapzctl.c"
#undef main
#undef ioctl

#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <sys/wait.h>

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


/*
 * The seven newer INFO counters are optional for the original read-only
 * display, but all must be independently canonical before watch sampling.
 * These are synthetic strings; they do not confer live-mapper provenance.
 */
static void build_watch_info_fixture(char *output, size_t capacity,
				      size_t omitted_field, size_t replaced_field,
				      const char *replacement_value)
{
	static const char *const keys[] = {
		"logical_read", "physical_read", "physical_read_reqs",
		"physical_write_reqs", "gc_read", "gc_read_reqs",
		"gc_write_reqs"
	};
	static const char *const values[] = {
		"4096", "8192", "5", "7", "4096", "2", "0"
	};
	static const char *const legacy =
		"failed=0 error=0 logical_write=8192 physical_write=4096 "
		"gc_write=0 compressed=2 raw=0 zero_elided=0 "
		"bulk_mode=1 bulk_padding=0";
	size_t used_length;
	size_t index;
	int rendered;

	assert(output && capacity &&
	       (omitted_field == SIZE_MAX || omitted_field < 7U) &&
	       (replaced_field == SIZE_MAX || replaced_field < 7U));
	rendered = snprintf(output, capacity, "%s", legacy);
	assert(rendered > 0 && (size_t)rendered < capacity);
	used_length = (size_t)rendered;
	for (index = 0; index < sizeof(keys) / sizeof(keys[0]); ++index) {
		if (index == omitted_field)
			continue;
		rendered = snprintf(output + used_length, capacity - used_length,
				   " %s=%s", keys[index],
				   index == replaced_field ? replacement_value :
				   values[index]);
		assert(rendered > 0 && (size_t)rendered < capacity - used_length);
		used_length += (size_t)rendered;
	}
}

static void test_optional_watch_info_counter_validation(void)
{
	static const struct {
		size_t counter_index;
		const char *invalid_value;
		int expected_status;
		const char *expected_field;
	} adversarial[] = {
		{ 0, "01", STATUS_BLOCKED, "logical_read" },
		{ 1, "-1", STATUS_BLOCKED, "physical_read" },
		{ 2, "+1", STATUS_BLOCKED, "physical_read_reqs" },
		{ 3, "18446744073709551616", STATUS_BLOCKED,
		  "physical_write_reqs" },
		{ 4, "", STATUS_BLOCKED, "gc_read" },
		{ 5, "2x", STATUS_BLOCKED, "gc_read_reqs" },
		{ 6, "01", STATUS_BLOCKED, "gc_write_reqs" },
		{ 4, "8193", STATUS_RETRY, "GC/lower read and request counters" },
		{ 5, "6", STATUS_RETRY, "GC/lower read and request counters" },
		{ 6, "8", STATUS_RETRY, "GC/lower read and request counters" }
	};
	struct swapz_ratio_status ratio;
	struct status_problem problem = { 0 };
	char status_text[1024];
	size_t index;

	build_watch_info_fixture(status_text, sizeof(status_text),
				 SIZE_MAX, SIZE_MAX, NULL);
	assert(parse_swapz_ratio_status_diagnostic(status_text, &ratio,
						    &problem) == STATUS_READY);
	assert(ratio.watch_counters_valid == 1);
	assert(ratio.logical_read_bytes == 4096ULL);
	assert(ratio.physical_read_bytes == 8192ULL);
	assert(ratio.physical_read_requests == 5ULL);
	assert(ratio.physical_write_requests == 7ULL);
	assert(ratio.gc_read_bytes == 4096ULL);
	assert(ratio.gc_read_requests == 2ULL);
	assert(ratio.gc_write_requests == 0ULL);
	assert(status_watch_counters_equal(&ratio, &ratio));

	for (index = 0; index < 7U; ++index) {
		struct swapz_ratio_status incomplete;

		build_watch_info_fixture(status_text, sizeof(status_text),
					 index, SIZE_MAX, NULL);
		assert(parse_swapz_ratio_status_diagnostic(status_text, &incomplete,
							    &problem) == STATUS_READY);
		assert(!incomplete.watch_counters_valid);
		assert(!status_watch_counters_equal(&ratio, &incomplete));
	}
	for (index = 0; index < sizeof(adversarial) / sizeof(adversarial[0]);
	     ++index) {
		build_watch_info_fixture(status_text, sizeof(status_text),
					 SIZE_MAX, adversarial[index].counter_index,
					 adversarial[index].invalid_value);
		assert(parse_swapz_ratio_status_diagnostic(status_text, &ratio,
							    &problem) ==
		       adversarial[index].expected_status);
		assert(problem.field &&
		       !strcmp(problem.field, adversarial[index].expected_field));
		assert(!ratio.watch_counters_valid ||
		       adversarial[index].expected_status == STATUS_RETRY);
	}
	build_watch_info_fixture(status_text, sizeof(status_text),
				 SIZE_MAX, SIZE_MAX, NULL);
	assert(strlen(status_text) + sizeof(" logical_read=4096") <
	       sizeof(status_text));
	strcat(status_text, " logical_read=4096");
	assert(parse_swapz_ratio_status_diagnostic(status_text, &ratio,
						    &problem) == STATUS_BLOCKED);
	assert(problem.field && !strcmp(problem.field, "logical_read"));
	assert(problem.observed && strstr(problem.observed, "duplicate"));
}

static const char *const fixture_valid_status =
	"logical_write=8192 physical_write=4096 gc_write=0 "
	"compressed=2 raw=0 zero_elided=0 bulk_mode=1 bulk_padding=0 "
	"failed=0 error=0";

/* Synthetic INFO strings exercise the actual compiled production parser. */
static void test_optional_origin_info_group(void)
{
	static const struct {
		const char *suffix;
		int expected_state;
		const char *field;
	} cases[] = {
		{ "", STATUS_READY, NULL },
		{ " verified_zswap_origin_admitted=0 "
		  "foreground_committed_verified_zswap_writeback=0 "
		  "origin_carrier_compiled=0", STATUS_READY, NULL },
		{ " verified_zswap_origin_admitted=0 "
		  "foreground_committed_verified_zswap_writeback=0 "
		  "origin_carrier_compiled=1", STATUS_READY, NULL },
		{ " verified_zswap_origin_admitted=2 "
		  "foreground_committed_verified_zswap_writeback=1 "
		  "origin_carrier_compiled=1", STATUS_READY, NULL },
		{ " verified_zswap_origin_admitted=1", STATUS_BLOCKED,
		  "origin provenance INFO group" },
		{ " foreground_committed_verified_zswap_writeback=0 "
		  "origin_carrier_compiled=1", STATUS_BLOCKED,
		  "origin provenance INFO group" },
		{ " verified_zswap_origin_admitted=2 "
		  "foreground_committed_verified_zswap_writeback=1", STATUS_BLOCKED,
		  "origin provenance INFO group" },
		{ " verified_zswap_origin_admitted=1 "
		  "foreground_committed_verified_zswap_writeback=0 "
		  "origin_carrier_compiled=1 verified_zswap_origin_admitted=1",
		  STATUS_BLOCKED, "verified_zswap_origin_admitted" },
		{ " verified_zswap_origin_admitted=01 "
		  "foreground_committed_verified_zswap_writeback=0 "
		  "origin_carrier_compiled=1", STATUS_BLOCKED,
		  "verified_zswap_origin_admitted" },
		{ " verified_zswap_origin_admitted=+1 "
		  "foreground_committed_verified_zswap_writeback=0 "
		  "origin_carrier_compiled=1", STATUS_BLOCKED,
		  "verified_zswap_origin_admitted" },
		{ " verified_zswap_origin_admitted= "
		  "foreground_committed_verified_zswap_writeback=0 "
		  "origin_carrier_compiled=1", STATUS_BLOCKED,
		  "verified_zswap_origin_admitted" },
		{ " verified_zswap_origin_admitted=18446744073709551616 "
		  "foreground_committed_verified_zswap_writeback=0 "
		  "origin_carrier_compiled=1", STATUS_BLOCKED,
		  "verified_zswap_origin_admitted" },
		{ " verified_zswap_origin_admitted=2 "
		  "foreground_committed_verified_zswap_writeback=-1 "
		  "origin_carrier_compiled=1", STATUS_BLOCKED,
		  "foreground_committed_verified_zswap_writeback" },
		{ " verified_zswap_origin_admitted=2 "
		  "foreground_committed_verified_zswap_writeback=18446744073709551616 "
		  "origin_carrier_compiled=1", STATUS_BLOCKED,
		  "foreground_committed_verified_zswap_writeback" },
		{ " verified_zswap_origin_admitted=2 "
		  "foreground_committed_verified_zswap_writeback=1 "
		  "origin_carrier_compiled=2", STATUS_BLOCKED,
		  "origin_carrier_compiled" },
		{ " verified_zswap_origin_admitted=2 "
		  "foreground_committed_verified_zswap_writeback=1 "
		  "origin_carrier_compiled=01", STATUS_BLOCKED,
		  "origin_carrier_compiled" },
		{ " verified_zswap_origin_admitted=1 "
		  "foreground_committed_verified_zswap_writeback=2 "
		  "origin_carrier_compiled=1", STATUS_RETRY,
		  "foreground_committed_verified_zswap_writeback" },
		{ " verified_zswap_origin_admitted=3 "
		  "foreground_committed_verified_zswap_writeback=3 "
		  "origin_carrier_compiled=1", STATUS_RETRY,
		  "foreground_committed_verified_zswap_writeback" },
		{ " verified_zswap_origin_admitted=1 "
		  "foreground_committed_verified_zswap_writeback=1 "
		  "origin_carrier_compiled=0", STATUS_BLOCKED,
		  "origin_carrier_compiled" }
	};
	struct swapz_ratio_status first = { 0 };
	struct swapz_ratio_status second = { 0 };
	struct status_problem problem = { 0 };
	char text[1024];
	size_t index;

	for (index = 0; index < sizeof(cases) / sizeof(cases[0]); ++index) {
		int length = snprintf(text, sizeof(text), "%s%s",
				      fixture_valid_status, cases[index].suffix);
		int result;

		assert(length > 0 && (size_t)length < sizeof(text));
		result = parse_swapz_ratio_status_diagnostic(text, &first, &problem);
		if (result != cases[index].expected_state ||
		    (cases[index].field &&
		     (!problem.field || strcmp(problem.field, cases[index].field)))) {
			fprintf(stderr, "FAIL: origin INFO case=%zu result=%d expected=%d field=%s\n",
				index, result, cases[index].expected_state,
				problem.field ? problem.field : "(none)");
			abort();
		}
		if (result == STATUS_READY) {
			assert(first.origin_telemetry_valid == (index != 0U));
			assert(first.foreground_committed_verified_zswap_writeback <=
			       first.verified_zswap_origin_admitted);
		}
	}
	assert(parse_swapz_ratio_status_diagnostic(
		fixture_valid_status, &first, &problem) == STATUS_READY);
	assert(!first.origin_telemetry_valid);
	assert(parse_swapz_ratio_status_diagnostic(
		"logical_write=8192 physical_write=4096 gc_write=0 compressed=2 raw=0 "
		"zero_elided=0 bulk_mode=1 bulk_padding=0 failed=0 error=0 "
		"verified_zswap_origin_admitted=2 "
		"foreground_committed_verified_zswap_writeback=1 "
		"origin_carrier_compiled=1", &first, &problem) == STATUS_READY);
	second = first;
	assert(ratio_status_equal(&first, &second));
	++second.foreground_committed_verified_zswap_writeback;
	assert(!ratio_status_equal(&first, &second));
	second = first;
	second.origin_telemetry_valid = 0;
	assert(!ratio_status_equal(&first, &second));
}



/*
 * Round 004: bounded parser adversaries exercise the included production C,
 * never a stand-in parser. Seed and maximum input length are fixed for CI.
 */
#define ORIGIN_ADVERSARIAL_SEED 0x5a17c0deU
#define ORIGIN_ADVERSARIAL_RANDOM_CASES 256U
#define ORIGIN_ADVERSARIAL_TEXT_CAPACITY 1024U

static const char *const origin_adversarial_keys[] = {
	"verified_zswap_origin_admitted",
	"foreground_committed_verified_zswap_writeback",
	"origin_carrier_compiled"
};

static uint32_t origin_adversarial_next(uint32_t *state)
{
	uint32_t value = *state;

	value ^= value << 13;
	value ^= value >> 17;
	value ^= value << 5;
	*state = value;
	return value;
}

static size_t origin_adversarial_append(char *output, size_t capacity,
					size_t used, const char *key,
					const char *value)
{
	int written;

	assert(used < capacity);
	written = snprintf(output + used, capacity - used,
			   " %s=%s", key, value);
	assert(written > 0 && (size_t)written < capacity - used);
	return used + (size_t)written;
}

static void origin_adversarial_build(char *output, size_t capacity,
				     unsigned int present_mask,
				     unsigned int starting_key,
				     const char *const values[3],
				     const char *extra_token)
{
	int written = snprintf(output, capacity, "%s", fixture_valid_status);
	size_t used;
	unsigned int index;

	assert(written > 0 && (size_t)written < capacity);
	used = (size_t)written;
	for (index = 0; index < 3U; ++index) {
		unsigned int key_index = (starting_key + index) % 3U;

		if (present_mask & (1U << key_index))
			used = origin_adversarial_append(output, capacity, used,
				origin_adversarial_keys[key_index], values[key_index]);
	}
	if (extra_token) {
		written = snprintf(output + used, capacity - used, " %s",
				   extra_token);
		assert(written > 0 && (size_t)written < capacity - used);
	}
}

static void origin_adversarial_expect(const char *status, int expected_state,
				      const char *expected_field,
				      int expected_valid,
				      size_t case_index)
{
	struct swapz_ratio_status ratio;
	struct status_problem problem = { 0 };
	int actual = parse_swapz_ratio_status_diagnostic(status, &ratio, &problem);

	if (actual != expected_state ||
	    (expected_field &&
	     (!problem.field || strcmp(problem.field, expected_field))) ||
	    (actual == STATUS_READY &&
	     ratio.origin_telemetry_valid != expected_valid)) {
		fprintf(stderr,
			"FAIL: Round 004 origin parser case=%zu state=%d expected=%d field=%s expected_field=%s\n",
			case_index, actual, expected_state,
			problem.field ? problem.field : "(none)",
			expected_field ? expected_field : "(none)");
		abort();
	}
}

static void test_round004_origin_adversarial_matrix(void)
{
	static const char *const invalid_values[] = {
		"", "00", "01", "+1", "-1", "18446744073709551616",
		"1suffix", "1,other=0", "1\r", "1\v", "1\f",
		"1\200", "1\302\240"
	};
	static const char *const ignored_tokens[] = {
		"xverified_zswap_origin_admitted=1",
		"verified_zswap_origin_admitted_extra=1",
		"xforeground_committed_verified_zswap_writeback=1",
		"foreground_committed_verified_zswap_writeback_extra=1",
		"xorigin_carrier_compiled=1",
		"origin_carrier_compiled_extra=1",
		"unrelated=1verified_zswap_origin_admitted=1",
		"unrelated=0\200verified_zswap_origin_admitted=1"
	};
	static const char *const admitted_counts[] = {
		"0", "1", "2", "3", "18446744073709551615"
	};
	static const char *const committed_counts[] = {
		"0", "1", "2", "3", "4"
	};
	const char *values[3] = { "2", "1", "1" };
	struct swapz_ratio_status original;
	struct swapz_ratio_status changed;
	struct status_problem problem = { 0 };
	char status[ORIGIN_ADVERSARIAL_TEXT_CAPACITY];
	uint32_t random_state = ORIGIN_ADVERSARIAL_SEED;
	size_t executed_cases = 0;
	unsigned int mask, field, variant, start, admitted, committed, carrier;

	/* Every subset: wholly absent legacy is valid but not measured. */
	for (mask = 0; mask < 8U; ++mask) {
		origin_adversarial_build(status, sizeof(status), mask,
					  0U, values, NULL);
		origin_adversarial_expect(status,
			mask == 0U || mask == 7U ? STATUS_READY : STATUS_BLOCKED,
			mask == 0U || mask == 7U ? NULL :
			"origin provenance INFO group", mask == 7U,
			executed_cases++);
	}
	/* Each canonical field must independently reject noncanonical bytes. */
	for (field = 0; field < 3U; ++field) {
		for (variant = 0; variant < sizeof(invalid_values) /
							 sizeof(invalid_values[0]); ++variant) {
			values[field] = invalid_values[variant];
			origin_adversarial_build(status, sizeof(status), 7U,
						  field, values, NULL);
			origin_adversarial_expect(status, STATUS_BLOCKED,
					origin_adversarial_keys[field], -1, executed_cases++);
		}
		values[field] = field == 0U ? "2" : "1";
	}
	/* Duplicate exact keys fail even when their values are identical. */
	for (field = 0; field < 3U; ++field) {
		char duplicate[96];
		int written = snprintf(duplicate, sizeof(duplicate), "%s=%s",
			origin_adversarial_keys[field], values[field]);

		assert(written > 0 && (size_t)written < sizeof(duplicate));
		origin_adversarial_build(status, sizeof(status), 7U,
					  0U, values, duplicate);
		origin_adversarial_expect(status, STATUS_BLOCKED,
			origin_adversarial_keys[field], -1, executed_cases++);
	}
	/* Prefix/suffix lookalikes and bytes glued to tokens cannot create a tag. */
	for (variant = 0; variant < sizeof(ignored_tokens) /
							 sizeof(ignored_tokens[0]); ++variant) {
		origin_adversarial_build(status, sizeof(status), 0U,
					  0U, values, ignored_tokens[variant]);
		origin_adversarial_expect(status, STATUS_READY, NULL, 0,
					  executed_cases++);
	}
	/* Check semantic bounds independently of any presentation/RAW policy. */
	for (carrier = 0; carrier < 2U; ++carrier) {
		for (admitted = 0; admitted < 5U; ++admitted) {
			for (committed = 0; committed < 5U; ++committed) {
				int expected;
				const char *field_name = NULL;

				values[0] = admitted_counts[admitted];
				values[1] = committed_counts[committed];
				values[2] = carrier ? "1" : "0";
				if (!carrier && (admitted || committed)) {
					expected = STATUS_BLOCKED;
					field_name = "origin_carrier_compiled";
				} else if (carrier && (committed > 2U ||
						     (admitted != 4U && committed > admitted))) {
					expected = STATUS_RETRY;
					field_name =
						"foreground_committed_verified_zswap_writeback";
				} else {
					expected = STATUS_READY;
				}
				origin_adversarial_build(status, sizeof(status), 7U,
							  admitted % 3U, values, NULL);
				origin_adversarial_expect(status, expected, field_name,
							  1, executed_cases++);
			}
		}
	}
	/* Whitespace separators and reordered canonical keys are accepted. */
	origin_adversarial_expect(
		"failed=0 error=0 logical_write=8192 physical_write=4096 "
		"gc_write=0 compressed=2 raw=0 zero_elided=0 bulk_mode=1 "
		"bulk_padding=0\tverified_zswap_origin_admitted=2\n"
		"origin_carrier_compiled=1\tforeground_committed_verified_zswap_writeback=1",
		STATUS_READY, NULL, 1, executed_cases++);

	/* Fixed xorshift32 seed, bounded 256 additional order/value adversaries. */
	values[0] = "2";
	values[1] = "1";
	values[2] = "1";
	for (start = 0; start < ORIGIN_ADVERSARIAL_RANDOM_CASES; ++start) {
		uint32_t choice = origin_adversarial_next(&random_state);
		unsigned int selected_field = (choice >> 8) % 3U;
		unsigned int selected_variant = (choice >> 12) %
			(unsigned int)(sizeof(invalid_values) / sizeof(invalid_values[0]));
		unsigned int selected_mask = (choice & 3U) == 0U ? 0U : 7U;
		int expected = STATUS_READY;
		const char *field_name = NULL;

		if (selected_mask && (choice & 3U) == 2U) {
			values[selected_field] = invalid_values[selected_variant];
			expected = STATUS_BLOCKED;
			field_name = origin_adversarial_keys[selected_field];
		}
		origin_adversarial_build(status, sizeof(status), selected_mask,
					  (choice >> 20) % 3U, values, NULL);
		origin_adversarial_expect(status, expected, field_name,
					  selected_mask == 7U, executed_cases++);
		values[selected_field] = selected_field == 0U ? "2" : "1";
	}
	/* Two INFO samples must agree on all three fields AND group presence. */
	values[0] = "2";
	values[1] = "1";
	values[2] = "1";
	origin_adversarial_build(status, sizeof(status), 7U, 0U, values, NULL);
	assert(parse_swapz_ratio_status_diagnostic(status, &original,
						      &problem) == STATUS_READY);
	for (field = 0; field < 3U; ++field) {
		values[field] = field == 0U ? "3" :
				field == 1U ? "2" : "0";
		/* A disabled carrier cannot coexist with positive provenance. */
		if (field == 2U) {
			values[0] = "0";
			values[1] = "0";
		}
		origin_adversarial_build(status, sizeof(status), 7U,
						  field, values, NULL);
		assert(parse_swapz_ratio_status_diagnostic(status, &changed,
						      &problem) == STATUS_READY);
		assert(!ratio_status_equal(&original, &changed));
		values[0] = "2";
		values[1] = "1";
		values[2] = "1";
		++executed_cases;
	}
	origin_adversarial_build(status, sizeof(status), 0U, 0U, values, NULL);
	assert(parse_swapz_ratio_status_diagnostic(status, &changed,
						      &problem) == STATUS_READY);
	assert(!changed.origin_telemetry_valid &&
	       !ratio_status_equal(&original, &changed));
	++executed_cases;
	values[0] = "0";
	values[1] = "0";
	values[2] = "0";
	origin_adversarial_build(status, sizeof(status), 7U, 0U, values, NULL);
	assert(parse_swapz_ratio_status_diagnostic(status, &changed,
						      &problem) == STATUS_READY);
	assert(changed.origin_telemetry_valid &&
	       changed.verified_zswap_origin_admitted == 0ULL &&
	       changed.foreground_committed_verified_zswap_writeback == 0ULL);
	assert(!ratio_status_equal(&original, &changed));
	++executed_cases;
	/* A measured all-zero group differs from an unmeasured legacy group. */
	assert(parse_swapz_ratio_status_diagnostic(fixture_valid_status,
						      &original, &problem) == STATUS_READY);
	assert(!original.origin_telemetry_valid &&
	       !ratio_status_equal(&original, &changed));
	++executed_cases;
	/* With counters identically zero, carrier identity alone must differ. */
	values[2] = "1";
	origin_adversarial_build(status, sizeof(status), 7U, 0U, values, NULL);
	assert(parse_swapz_ratio_status_diagnostic(status, &original,
						      &problem) == STATUS_READY);
	assert(original.origin_carrier_compiled == 1ULL &&
	       !ratio_status_equal(&original, &changed));
	++executed_cases;
	/* One run owns this fixed case count; no unbounded malformed-input loop. */
	assert(executed_cases == 372U);
}

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
	/* Reproduce the actual Lubuntu mapper's cumulative foreground counters. */
	const char *const status =
		"logical_write=589369344 physical_write=570134528 gc_write=0 "
		"compressed=7860 raw=136020 zero_elided=9 bulk_mode=1 "
		"bulk_padding=0 failed=0 error=0";
	struct swapz_ratio_status ratio;
	FILE *capture = tmpfile();
	int saved_stdout = dup(STDOUT_FILENO);
	char output[4096] = { 0 };
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
	assert(strstr(output, "Health: OK (failed=0, error=0)"));
	assert(strstr(output, "WRITE EFFICIENCY (cumulative foreground)"));
	assert(strstr(output, "Category"));
	assert(strstr(output, "Overall"));
	assert(strstr(output, "1.03:1"));
	assert(strstr(output, "562.07 MiB"));
	assert(strstr(output, "543.72 MiB"));
	assert(strstr(output, "SWZ extents"));
	assert(strstr(output, "2.48:1"));
	assert(strstr(output, "30.70 MiB"));
	assert(strstr(output, "12.39 MiB"));
	assert(strstr(output, "Net WRITE reduction"));
	assert(strstr(output, "18.34 MiB"));
	assert(strstr(output, "3.26% of logical"));
	assert(strstr(output, "PAGE CLASSIFICATION (4 KiB each)"));
	assert(strstr(output, "7,860"));
	assert(strstr(output, "5.46%"));
	assert(strstr(output, "136,020"));
	assert(strstr(output, "94.53%"));
	assert(strstr(output, "Zero-elided"));
	assert(strstr(output, "0.01%"));
	assert(strstr(output, "GC lower WRITEs: 0 B (excluded from ratios)"));
	assert(strstr(output, "not current swap usage"));
	assert(!strstr(output, "compressed ratio (SWZ extents)"));
	fclose(capture);
	close(saved_stdout);
}

static void test_status_report_handles_zero_and_expansion_cases(void)
{
	const struct {
		const char *status;
		const char *expected;
		const char *additional;
	} cases[] = {
		{
			"logical_write=0 physical_write=0 gc_write=0 "
			"compressed=0 raw=0 zero_elided=0 bulk_mode=1 "
			"bulk_padding=0 failed=0 error=0",
			"n/a", "PAGE CLASSIFICATION"
		},
		{
			"logical_write=12288 physical_write=0 gc_write=0 "
			"compressed=0 raw=0 zero_elided=3 bulk_mode=1 "
			"bulk_padding=0 failed=0 error=0",
			"infinite", "100.00% of logical"
		},
		{
			"logical_write=4096 physical_write=8192 gc_write=0 "
			"compressed=1 raw=0 zero_elided=0 bulk_mode=1 "
			"bulk_padding=0 failed=0 error=0",
			"0.50:1", "Net WRITE overhead"
		},
	};
	size_t index;

	for (index = 0; index < sizeof(cases) / sizeof(cases[0]); ++index) {
		struct swapz_ratio_status ratio;
		FILE *capture = tmpfile();
		int saved_stdout = dup(STDOUT_FILENO);
		char output[4096] = { 0 };
		size_t bytes;

		assert(capture && saved_stdout >= 0);
		assert(parse_swapz_ratio_status(cases[index].status, &ratio) ==
		       STATUS_READY);
		fflush(stdout);
		assert(dup2(fileno(capture), STDOUT_FILENO) >= 0);
		report_swapz_target("fixture", 0, &ratio);
		fflush(stdout);
		assert(dup2(saved_stdout, STDOUT_FILENO) >= 0);
		rewind(capture);
		bytes = fread(output, 1, sizeof(output) - 1U, capture);
		output[bytes] = '\0';
		assert(strstr(output, "Health: OK"));
		assert(strstr(output, cases[index].expected));
		assert(strstr(output, cases[index].additional));
		assert(!strstr(output, "nan"));
		assert(!strstr(output, "-nan"));
		fclose(capture);
		close(saved_stdout);
	}
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
	assert(strstr(output, "SWZ extents"));
	assert(strstr(output, "'bulk_padding'"));
	assert(strstr(output, "nonzero staged padding"));
	assert(!strstr(output, "cumulative padding"));
	assert(strstr(output, "Overall"));
	assert(!strstr(output, "SWZ extents       1.33:1"));
	close(saved_stdout);
	fclose(capture);
}

struct status_reader_fixture {
	const char *const *statuses;
	size_t count;
	size_t calls;
	/* Optional deterministic INFO sequence for the first of two targets. */
	const char *const *first_statuses;
	size_t first_status_count;
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
	if (fixture->first_statuses) {
		assert(fixture->first_status_count);
		texts[0] = fixture->first_statuses[fixture->calls %
					   fixture->first_status_count];
	} else {
		texts[0] = fixture_valid_status;
	}
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
	assert(strstr(output, "SWZ extents"));
	assert(strstr(output, "nonzero staged padding"));
	assert(strstr(output, "Overall"));
	assert(!strstr(output, "SWZ extents       1.33:1"));
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
			assert(strstr(output, "WRITE EFFICIENCY (cumulative foreground)"));
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


/* Pure read-only view regression: no block devices, swapon, or elevated rights. */
static void test_swapz_observation_views(void)
{
	struct status_ready_target targets[2] = {
		{
			.name = "swapz-demo-physical-fixture",
			.target_index = 0,
			.device_id = makedev(253, 7),
			.sector_length = 8192,
			.ratio = { .logical_write_bytes = 16384,
				   .physical_write_bytes = 8192,
				   .compressed_pages = 4,
				   .compressed_logical_bytes = 16384,
				   .compressed_extent_bytes = 8192,
				   .overall_physical_bytes = 8192,
				   .compressed_extent_ratio_exact = 1 }
		},
		{
			.name = "swapz-other-fixture",
			.target_index = 1,
			.device_id = makedev(253, 8),
			.sector_start = 8192,
			.sector_length = 16384
		}
	};
	struct status_ready_report report = {
		.targets = targets, .count = 2, .capacity = 2
	};
	FILE *capture = tmpfile();
	int saved_stdout = dup(STDOUT_FILENO);
	char output[8192] = { 0 };
	size_t bytes;
	unsigned long long capacity = 0;

	assert(capture && saved_stdout >= 0);
	assert(swapz_target_capacity_bytes(&targets[0], &capacity) == 0);
	assert(capacity == 4194304ULL);
	assert(swapz_target_capacity_bytes(&targets[1], &capacity) == 0);
	assert(capacity == 8388608ULL);
	assert(!strcmp(swapz_view_name(SWAPZ_VIEW_DIAGNOSE), "diagnose"));

	fflush(stdout);
	assert(dup2(fileno(capture), STDOUT_FILENO) >= 0);
	assert(swapz_print_view(&report, SWAPZ_VIEW_LIST, NULL, 1) == 0);
	fflush(stdout);
	assert(dup2(saved_stdout, STDOUT_FILENO) >= 0);
	rewind(capture);
	bytes = fread(output, 1, sizeof(output) - 1U, capture);
	output[bytes] = '\0';
	assert(strstr(output, "\"schema_version\":1"));
	assert(strstr(output, "\"command\":\"list\""));
	assert(strstr(output, "\"dm_major\":253,\"dm_minor\":7"));
	assert(strstr(output, "\"logical_capacity_bytes\":4194304"));
	assert(strstr(output, "\"compressed_extent_bytes_exact\":true"));
	assert(strstr(output, "},{\"name\":\"swapz-other-fixture\""));
	assert(strstr(output, "\"logical_capacity_bytes\":8388608"));
	assert(strstr(output, "\"ownership\":\"unverified\""));
	assert(strstr(output, "}]}\n"));
	assert(!strstr(output, "[,"));

	assert(ftruncate(fileno(capture), 0) == 0);
	rewind(capture);
	fflush(stdout);
	assert(dup2(fileno(capture), STDOUT_FILENO) >= 0);
	assert(swapz_print_view(&report, SWAPZ_VIEW_INSPECT,
				"swapz-demo-physical-fixture", 0) == 0);
	fflush(stdout);
	assert(dup2(saved_stdout, STDOUT_FILENO) >= 0);
	rewind(capture);
	memset(output, 0, sizeof(output));
	bytes = fread(output, 1, sizeof(output) - 1U, capture);
	output[bytes] = '\0';
	assert(strstr(output, "device 253:7"));
	assert(strstr(output, "capacity=4194304 bytes"));
	assert(strstr(output, "Ownership: unverified"));
	assert(!strstr(output, "swapz-other-fixture"));

	/* Unknown names and oversized sector geometry fail without output. */
	assert(ftruncate(fileno(capture), 0) == 0);
	rewind(capture);
	fflush(stdout);
	assert(dup2(fileno(capture), STDOUT_FILENO) >= 0);
	assert(swapz_print_view(&report, SWAPZ_VIEW_STATS, "missing", 1) != 0);
	fflush(stdout);
	assert(dup2(saved_stdout, STDOUT_FILENO) >= 0);
	rewind(capture);
	assert(fread(output, 1, 1, capture) == 0);

	targets[0].sector_length = UINT64_MAX;
	assert(swapz_target_capacity_bytes(&targets[0], &capacity) < 0);
	assert(ftruncate(fileno(capture), 0) == 0);
	rewind(capture);
	fflush(stdout);
	assert(dup2(fileno(capture), STDOUT_FILENO) >= 0);
	assert(swapz_print_view(&report, SWAPZ_VIEW_HEALTH,
				"swapz-demo-physical-fixture", 1) != 0);
	fflush(stdout);
	assert(dup2(saved_stdout, STDOUT_FILENO) >= 0);
	rewind(capture);
	assert(fread(output, 1, 1, capture) == 0);

	fclose(capture);
	close(saved_stdout);
}


/* Read-only procfs inventory parser: synthetic regular/character fixtures only. */
static void test_swapz_linux_swap_inventory_parser(void)
{
	const struct {
		const char *inventory;
		int valid;
	} cases[] = {
		{ "Filename\tType\tSize\tUsed\tPriority\n", 1 },
		{ "Filename\tType\tSize\tUsed\tPriority\n"
		  "/dev/null partition 1024 512 -1\n", 1 },
		{ "Filename\tType\tSize\tUsed\tPriority\n"
		  "/dev/null file 1024 0 1\n", 1 },
		{ "Filename\tType\tSize\tUsed\tPriority\n"
		  "/dev/null partition 1 2 -1\n", 0 },
		{ "Filename\tType\tSize\tUsed\tPriority\n"
		  "/dev/null partition 18014398509481984 0 -1\n", 0 },
		{ "Filename\tType\tSize\tUsed\tPriority\n"
		  "/dev/null partition -1 0 -1\n", 0 },
		{ "Filename\tType\tSize\tUsed\tPriority\n"
		  "/dev/null unknown 1024 1 -1\n", 0 },
		{ "Filename\tType\tSize\tUsed\tPriority\n"
		  "/dev/null partition 1024 1 invalid\n", 0 },
		{ "Filename\tType\tSize\tUsed\tPriority\n"
		  "/dev/null partition 1024 1 9999999999999999999999999\n", 0 },
		{ "Filename\tType\tSize\tUsed\tPriority\n"
		  "/dev/null partition 1024 1 1 extra\n", 0 },
		{ "Filename\tType\tSize\tUsed\tPriority\n"
		  "/dev/null partition 1024 1 -1", 0 },
		{ "Broken header\n", 0 },
		{ "", 0 }
	};
	struct status_ready_target target = {
		.name = "swapz-observation",
		.device_id = makedev(253, 9),
		.sector_length = 8192
	};
	const struct status_ready_report report = {
		.targets = &target, .count = 1, .capacity = 1
	};
	size_t index;
	unsigned long long bytes = 777;

	assert(swapz_parse_swap_kib("0", &bytes) == 0 && bytes == 0);
	assert(swapz_parse_swap_kib("1", &bytes) == 0 && bytes == 1024);
	assert(swapz_parse_swap_kib("18446744073709551615", &bytes) < 0);
	assert(swapz_parse_swap_kib("01", &bytes) < 0);
	assert(swapz_parse_swap_kib("-1", &bytes) < 0);

	for (index = 0; index < sizeof(cases) / sizeof(cases[0]); ++index) {
		struct swapz_linux_swap observation = { .state = "not_observed" };
		FILE *inventory = tmpfile();
		int parsed;

		assert(inventory);
		assert(fputs(cases[index].inventory, inventory) >= 0);
		rewind(inventory);
		parsed = swapz_read_linux_swap(inventory, &report, &observation);
		assert((parsed == 0) == cases[index].valid);
		/* /dev/null is a character device, never the fake mapper. */
		assert(!observation.has_usage);
		assert(!strcmp(observation.state, "not_observed"));
		assert(fclose(inventory) == 0);
	}
}



/*
 * Independent Python JSON decoder: complete syntax and identity checks, not
 * substring matching. All mapper identities below are synthetic.
 */
static void test_swapz_json_identity_and_document_framing(void)
{
	const char *const names[] = {
		"ordinary", "quote\"name", "back\\slash", "line\nbreak",
		"utf8-\xc3\xa9", "invalid-\xff", "invalid-_", "slash/name"
	};
	struct status_ready_target targets[sizeof(names) / sizeof(names[0])] = { 0 };
	struct status_ready_report report = {
		.targets = targets, .capacity = sizeof(targets) / sizeof(targets[0])
	};
	const size_t device_counts[] = { 0U, 1U, sizeof(targets) / sizeof(targets[0]) };
	const char *const decoder =
		"import json,os,sys,urllib.parse\n"
		"document=json.load(sys.stdin)\n"
		"count=int(sys.argv[1])\n"
		"assert document['schema_version']==1 and document['command']=='list'\n"
		"devices=document['devices']\n"
		"assert len(devices)==count\n"
		"names=[device['name'] for device in devices]\n"
		"assert all(name.isascii() for name in names)\n"
		"decoded=[urllib.parse.unquote_to_bytes(name) for name in names]\n"
		"assert decoded[:5]==[os.fsencode(name) for name in sys.argv[2:2+min(count,5)]]\n"
		"assert len(set(decoded))==len(decoded)\n"
		"assert all(device['ownership']=='unverified' for device in devices)\n";
	size_t index;

	for (index = 0; index < sizeof(targets) / sizeof(targets[0]); ++index) {
		size_t name_length = strlen(names[index]);

		assert(name_length < sizeof(targets[index].name));
		memcpy(targets[index].name, names[index], name_length + 1U);
		targets[index].device_id = makedev(253, (unsigned int)index + 1U);
		targets[index].sector_length = 8192U;
	}
	for (index = 0; index < sizeof(device_counts) / sizeof(device_counts[0]);
	     ++index) {
		FILE *capture = tmpfile();
		int saved_stdout = dup(STDOUT_FILENO);
		char count_text[16];
		pid_t decoder_pid;
		int decoder_status = 0;
		int printed;

		assert(capture && saved_stdout >= 0);
		report.count = device_counts[index];
		assert(snprintf(count_text, sizeof(count_text), "%zu",
				report.count) > 0);
		fflush(stdout);
		assert(dup2(fileno(capture), STDOUT_FILENO) >= 0);
		printed = swapz_print_view(&report, SWAPZ_VIEW_LIST, NULL, 1);
		fflush(stdout);
		assert(dup2(saved_stdout, STDOUT_FILENO) >= 0);
		close(saved_stdout);
		assert(printed == 0);
		rewind(capture);
		decoder_pid = fork();
		assert(decoder_pid >= 0);
		if (decoder_pid == 0) {
			int quiet_output = open("/dev/null", O_WRONLY | O_CLOEXEC);

			if (quiet_output < 0 ||
			    dup2(fileno(capture), STDIN_FILENO) < 0 ||
			    dup2(quiet_output, STDOUT_FILENO) < 0 ||
			    dup2(quiet_output, STDERR_FILENO) < 0)
				_exit(127);
			close(quiet_output);
			execlp("python3", "python3", "-c", decoder, count_text,
			       names[0], names[1], names[2], names[3], names[4],
			       (char *)NULL);
			_exit(127);
		}
		while (waitpid(decoder_pid, &decoder_status, 0) < 0) {
			if (errno != EINTR) {
				fprintf(stderr,
					"FAIL: JSON decoder wait case=%zu errno=%d\n",
					index, errno);
				abort();
			}
		}
		if (!WIFEXITED(decoder_status) || WEXITSTATUS(decoder_status) != 0) {
			fprintf(stderr,
				"FAIL: JSON parser/name identity case=%zu count=%zu status=%d\n",
				index, report.count, decoder_status);
			abort();
		}
		assert(fclose(capture) == 0);
	}
}

/* Injected FILE* procfs inventory; no real swap or block-device operation. */

/* Priority text must have its exact Linux signed numeric value, not just parse. */
static void test_swapz_linux_swap_priority_exact_values(void)
{
	const struct {
		const char *token;
		long expected;
		int valid;
	} cases[] = {
		{ "-32768", -32768L, 1 },
		{ "-1", -1L, 1 },
		{ "0", 0L, 1 },
		{ "32767", 32767L, 1 },
		{ "-32769", 0L, 0 },
		{ "32768", 0L, 0 },
		{ "-0", 0L, 0 },
		{ "+1", 0L, 0 },
		{ "01", 0L, 0 }
	};
	size_t index;

	for (index = 0; index < sizeof(cases) / sizeof(cases[0]); ++index) {
		long value = LONG_MAX;
		int parsed = swapz_parse_swap_priority(cases[index].token, &value) == 0;

		if (parsed != cases[index].valid ||
		    (parsed && value != cases[index].expected)) {
			fprintf(stderr,
				"FAIL: priority token case=%zu expected_valid=%d "
				"actual_valid=%d expected=%ld actual=%ld\n",
				index, cases[index].valid, parsed,
				cases[index].expected, value);
			abort();
		}
	}
}

static void test_swapz_linux_swap_inventory_adversarial_records(void)
{
	const struct {
		const char *label;
		const char *inventory;
		int valid;
	} cases[] = {
		{ "minimum-priority", "Filename\tType\tSize\tUsed\tPriority\n"
		  "/dev/null partition 1 0 -32768\n", 1 },
		{ "maximum-priority", "Filename\tType\tSize\tUsed\tPriority\n"
		  "/dev/null partition 1 0 32767\n", 1 },
		{ "priority-plus", "Filename\tType\tSize\tUsed\tPriority\n"
		  "/dev/null partition 1 0 +1\n", 0 },
		{ "priority-leading-zero", "Filename\tType\tSize\tUsed\tPriority\n"
		  "/dev/null partition 1 0 01\n", 0 },
		{ "priority-negative-zero", "Filename\tType\tSize\tUsed\tPriority\n"
		  "/dev/null partition 1 0 -0\n", 0 },
		{ "priority-too-high", "Filename\tType\tSize\tUsed\tPriority\n"
		  "/dev/null partition 1 0 32768\n", 0 },
		{ "priority-too-low", "Filename\tType\tSize\tUsed\tPriority\n"
		  "/dev/null partition 1 0 -32769\n", 0 },
		{ "forged-header", "Filename\tWrong\tSize\tUsed\tPriority\n", 0 },
		{ "forged-prefix", "FilenameOther\tType\tSize\tUsed\tPriority\n", 0 },
		{ "missing-header-newline", "Filename\tType\tSize\tUsed\tPriority", 0 },
		{ "empty-inventory", "Filename\tType\tSize\tUsed\tPriority\n", 1 },
		{ "duplicate-character-not-mapper",
		  "Filename\tType\tSize\tUsed\tPriority\n"
		  "/dev/null partition 2 1 -1\n"
		  "/dev/null partition 2 1 -1\n", 1 },
		{ "relative-path", "Filename\tType\tSize\tUsed\tPriority\n"
		  "relative-path partition 2 1 -1\n", 1 },
		{ "swapfile", "Filename\tType\tSize\tUsed\tPriority\n"
		  "/dev/null file 2 1 -1\n", 1 },
		{ "maximum-safe-kib", "Filename\tType\tSize\tUsed\tPriority\n"
		  "/dev/null partition 18014398509481983 0 -1\n", 1 },
		{ "kib-overflow", "Filename\tType\tSize\tUsed\tPriority\n"
		  "/dev/null partition 18014398509481984 0 -1\n", 0 }
	};
	struct status_ready_target target = {
		.name = "fixture", .device_id = makedev(253, 9), .sector_length = 8192
	};
	const struct status_ready_report report = {
		.targets = &target, .count = 1, .capacity = 1
	};
	size_t index;

	for (index = 0; index < sizeof(cases) / sizeof(cases[0]); ++index) {
		struct swapz_linux_swap observation = { .state = "not_observed" };
		FILE *inventory = tmpfile();
		int result;

		assert(inventory);
		assert(fputs(cases[index].inventory, inventory) >= 0);
		rewind(inventory);
		result = swapz_read_linux_swap(inventory, &report, &observation);
		if ((result == 0) != cases[index].valid) {
			fprintf(stderr,
				"FAIL: procfs case=%s expected_valid=%d actual_valid=%d\n",
				cases[index].label, cases[index].valid, result == 0);
			abort();
		}
		assert(!observation.has_usage);
		assert(!strcmp(observation.state, "not_observed"));
		assert(fclose(inventory) == 0);
	}
	{
		char long_record[4096 + 80];
		struct swapz_linux_swap observation = { .state = "not_observed" };
		FILE *inventory = tmpfile();

		assert(inventory);
		memset(long_record, 'x', sizeof(long_record));
		long_record[0] = '/';
		long_record[sizeof(long_record) - 2U] = '\n';
		long_record[sizeof(long_record) - 1U] = '\0';
		assert(fputs("Filename\tType\tSize\tUsed\tPriority\n", inventory) >= 0);
		assert(fputs(long_record, inventory) >= 0);
		rewind(inventory);
		assert(swapz_read_linux_swap(inventory, &report, &observation) < 0);
		assert(!observation.has_usage);
		assert(fclose(inventory) == 0);
	}
}

static void test_swapz_command_specific_help(void)
{
	char *list_help[] = { "swapzctl", "help", "list", NULL };
	char *inspect_help[] = { "swapzctl", "inspect", "--help", NULL };
	char *primary_help[] = { "swapzctl", "help", "primary", NULL };
	char *bad_help[] = { "swapzctl", "help", "not-a-command", NULL };
	FILE *capture = tmpfile();
	FILE *error_capture = tmpfile();
	int saved_stdout = dup(STDOUT_FILENO);
	int saved_stderr = dup(STDERR_FILENO);
	char output[2048] = { 0 };
	size_t bytes;

	assert(capture && error_capture && saved_stdout >= 0 && saved_stderr >= 0);
	fflush(stdout);
	assert(dup2(fileno(capture), STDOUT_FILENO) >= 0);
	assert(swapzctl_program_main(3, list_help) == 0);
	assert(swapzctl_program_main(3, inspect_help) == 0);
	assert(swapzctl_program_main(3, primary_help) == 0);
	fflush(stdout);
	assert(dup2(saved_stdout, STDOUT_FILENO) >= 0);
	rewind(capture);
	bytes = fread(output, 1, sizeof(output) - 1U, capture);
	output[bytes] = '\0';
	assert(strstr(output, "Usage: swapzctl list [--json]"));
	assert(strstr(output, "Usage: swapzctl inspect <mapper-name> [--json]"));
	assert(strstr(output, "Usage: swapzctl primary plan"));
	assert(strstr(output, "not prove a mapper is inactive"));
	assert(strstr(output, "ownership are unverified"));
	assert(swapz_command_usage(capture, "not-a-command") < 0);
	/* Unknown topics fail without running a primary lifecycle command. */
	fflush(stderr);
	assert(dup2(fileno(error_capture), STDERR_FILENO) >= 0);
	assert(swapzctl_program_main(3, bad_help) == 2);
	fflush(stderr);
	assert(dup2(saved_stderr, STDERR_FILENO) >= 0);
	rewind(error_capture);
	memset(output, 0, sizeof(output));
	bytes = fread(output, 1, sizeof(output) - 1U, error_capture);
	output[bytes] = '\0';
	assert(strstr(output, "BLOCKED: unsupported help topic"));
	assert(!strstr(output, "dev/sd"));
	close(saved_stderr);
	close(saved_stdout);
	fclose(error_capture);
	fclose(capture);
}


/*
 * Public human option output is exercised without a loaded DM module.
 * No device descriptor, activation command or physical swap path is opened.
 */
struct swapz_test_view_call {
	const struct status_ready_report *report;
	enum swapz_view view;
	const char *selected_name;
	struct swapz_view_options options;
};

struct swapz_test_cli_call {
	int argc;
	char **argv;
};

static int swapz_test_invoke_view(void *context)
{
	const struct swapz_test_view_call *call = context;

	return swapz_print_view_with_options(call->report, call->view,
					      call->selected_name, &call->options);
}

static int swapz_test_invoke_cli(void *context)
{
	const struct swapz_test_cli_call *call = context;

	return swapzctl_program_main(call->argc, call->argv);
}

static void swapz_test_read_stream(FILE *stream, char *output, size_t capacity)
{
	size_t count;

	assert(capacity >= 2U);
	rewind(stream);
	count = fread(output, 1, capacity - 1U, stream);
	assert(!ferror(stream));
	output[count] = '\0';
	/* Truncation would conceal a diagnostics or formatting regression. */
	assert(fgetc(stream) == EOF);
}

static int swapz_test_capture_output(int (*invoke)(void *), void *context,
				     char *standard_output, size_t output_capacity,
				     char *standard_error, size_t error_capacity)
{
	FILE *output_capture = tmpfile();
	FILE *error_capture = tmpfile();
	int saved_stdout = dup(STDOUT_FILENO);
	int saved_stderr = dup(STDERR_FILENO);
	int result;

	assert(output_capture && error_capture && saved_stdout >= 0 &&
	       saved_stderr >= 0);
	assert(fflush(stdout) == 0 && fflush(stderr) == 0);
	assert(dup2(fileno(output_capture), STDOUT_FILENO) >= 0);
	assert(dup2(fileno(error_capture), STDERR_FILENO) >= 0);
	result = invoke(context);
	assert(fflush(stdout) == 0 && fflush(stderr) == 0);
	assert(dup2(saved_stdout, STDOUT_FILENO) >= 0);
	assert(dup2(saved_stderr, STDERR_FILENO) >= 0);
	assert(close(saved_stdout) == 0 && close(saved_stderr) == 0);
	swapz_test_read_stream(output_capture, standard_output, output_capacity);
	swapz_test_read_stream(error_capture, standard_error, error_capacity);
	assert(fclose(output_capture) == 0 && fclose(error_capture) == 0);
	return result;
}

static void test_swapz_human_option_views(void)
{
	struct status_ready_target targets[2] = {
		{
			.name = "fixture-one", .device_id = makedev(253, 7),
			.sector_length = 8192, .mapper_sector_end = 8192,
			.ratio = {
				.logical_write_bytes = 16384,
				.physical_write_bytes = 12288,
				.gc_write_bytes = 4096,
				.compressed_pages = 4,
				.compressed_logical_bytes = 16384,
				.compressed_extent_bytes = 8192,
				.overall_physical_bytes = 8192,
				.compressed_extent_ratio_exact = 1
			}
		},
		{
			.name = "fixture-two", .device_id = makedev(253, 8),
			.sector_length = 16384, .mapper_sector_end = 16384
		}
	};
	struct status_ready_report report = {
		.targets = targets, .count = 0, .capacity = 2
	};
	struct swapz_test_view_call call = {
		.report = &report, .view = SWAPZ_VIEW_LIST,
		.options = { .no_headers = 1 }
	};
	char output[8192];
	char diagnostic[1024];
	int result;

	/* Headerless empty lists must write exactly zero bytes. */
	result = swapz_test_capture_output(swapz_test_invoke_view, &call,
					   output, sizeof(output),
					   diagnostic, sizeof(diagnostic));
	assert(result == 0 && !output[0] && !diagnostic[0]);
	report.count = 2;
	result = swapz_test_capture_output(swapz_test_invoke_view, &call,
					   output, sizeof(output),
					   diagnostic, sizeof(diagnostic));
	assert(result == 0 && !diagnostic[0]);
	assert(strstr(output, "fixture-one  1  253:7  4194304"));
	assert(strstr(output, "fixture-two  1  253:8  8388608"));
	assert(!strstr(output, "MAPPER  TARGET"));
	assert(!strstr(output, "swapz targets: none"));
	call.options.no_headers = 0;
	result = swapz_test_capture_output(swapz_test_invoke_view, &call,
					   output, sizeof(output),
					   diagnostic, sizeof(diagnostic));
	assert(result == 0 && !diagnostic[0]);
	assert(strstr(output, "MAPPER  TARGET  DM_DEV  MAPPER_BYTES"));

	/* INFO parsing is independent; manually staged views must stay passive. */
	targets[0].ratio.origin_telemetry_valid = 1;
	targets[0].ratio.verified_zswap_origin_admitted = 2ULL;
	targets[0].ratio.foreground_committed_verified_zswap_writeback = 1ULL;
	targets[0].ratio.origin_carrier_compiled = 1ULL;
	/* Exact decimal byte formatting must not round the retained counters. */
	call.view = SWAPZ_VIEW_INSPECT;
	call.selected_name = "fixture-one";
	call.options.raw_bytes = 1;
	result = swapz_test_capture_output(swapz_test_invoke_view, &call,
					   output, sizeof(output),
					   diagnostic, sizeof(diagnostic));
	assert(result == 0 && !diagnostic[0]);
	assert(strstr(output, "capacity=4194304 bytes"));
	assert(strstr(output, "Byte columns: exact decimal bytes"));
	assert(strstr(output, "Overall") && strstr(output, "16384"));
	assert(strstr(output, "SWZ extents") && strstr(output, "8192"));
	assert(strstr(output, "GC lower WRITEs: 4096 bytes"));
	assert(strstr(output, "Ownership: unverified"));
	assert(strstr(output, "Verified admissions: 2 pages"));
	assert(strstr(output, "Verified foreground commits: 1 pages"));
	assert(strstr(output, "Carrier compiled: yes (header capability only)"));
	assert(strstr(output, "Runtime BIO ABI and genuine stored-entry eviction: unverified."));
	assert(!strstr(output, "fixture-two"));
	call.options.raw_bytes = 0;
	result = swapz_test_capture_output(swapz_test_invoke_view, &call,
					   output, sizeof(output),
					   diagnostic, sizeof(diagnostic));
	assert(result == 0 && !diagnostic[0]);
	assert(strstr(output, "16.00 KiB") && strstr(output, "8.00 KiB"));
	assert(!strstr(output, "Byte columns: exact decimal bytes"));
	call.view = SWAPZ_VIEW_STATS;
	result = swapz_test_capture_output(swapz_test_invoke_view, &call,
					   output, sizeof(output),
					   diagnostic, sizeof(diagnostic));
	assert(result == 0 && !diagnostic[0]);
	assert(strstr(output, "Verified foreground commits: 1 pages"));
	call.options.json = 1;
	result = swapz_test_capture_output(swapz_test_invoke_view, &call,
					   output, sizeof(output),
					   diagnostic, sizeof(diagnostic));
	assert(result == 0 && !diagnostic[0]);
	assert(strstr(output, "\"schema_version\":1"));
	assert(!strstr(output, "verified_zswap_origin_admitted"));
	assert(!strstr(output, "origin_carrier_compiled"));
	call.options.json = 0;
	call.view = SWAPZ_VIEW_INSPECT;
	targets[0].ratio.origin_telemetry_valid = 0;
	result = swapz_test_capture_output(swapz_test_invoke_view, &call,
					   output, sizeof(output),
					   diagnostic, sizeof(diagnostic));
	assert(result == 0 && !diagnostic[0]);
	assert(strstr(output, "Origin INFO: unavailable"));
	targets[0].ratio.origin_telemetry_valid = 1;

	/* Invalid selections must publish neither a list prefix nor counters. */
	call.view = SWAPZ_VIEW_STATS;
	call.selected_name = "fixture";
	call.options.raw_bytes = 1;
	result = swapz_test_capture_output(swapz_test_invoke_view, &call,
					   output, sizeof(output),
					   diagnostic, sizeof(diagnostic));
	assert(result != 0 && !output[0]);
	assert(strstr(diagnostic, "no validated swapz target"));
	call.view = SWAPZ_VIEW_INSPECT;
	call.selected_name = "fixture-one";
	strcpy(targets[1].name, "fixture-one");
	result = swapz_test_capture_output(swapz_test_invoke_view, &call,
					   output, sizeof(output),
					   diagnostic, sizeof(diagnostic));
	assert(result != 0 && !output[0]);
	assert(strstr(diagnostic, "multiple swapz targets"));
	strcpy(targets[1].name, "fixture-two");
	targets[0].sector_length = UINT64_MAX;
	result = swapz_test_capture_output(swapz_test_invoke_view, &call,
					   output, sizeof(output),
					   diagnostic, sizeof(diagnostic));
	assert(result != 0 && !output[0]);
	assert(strstr(diagnostic, "target capacity overflow"));
}

static void test_swapz_public_option_dispatch(void)
{
	struct {
		const char *label;
		int argc;
		char *argv[7];
	} invalid[] = {
		{ "list-json-bytes", 4,
		  { "swapzctl", "list", "--json", "--bytes", NULL } },
		{ "list-json-no-headers", 4,
		  { "swapzctl", "list", "--json", "--no-headers", NULL } },
		{ "list-duplicate-no-headers", 4,
		  { "swapzctl", "list", "--no-headers", "--no-headers", NULL } },
		{ "list-duplicate-bytes", 4,
		  { "swapzctl", "list", "--bytes", "--bytes", NULL } },
		{ "status-no-headers", 3,
		  { "swapzctl", "status", "--no-headers", NULL } },
		{ "inspect-no-headers", 4,
		  { "swapzctl", "inspect", "fixture", "--no-headers", NULL } },
		{ "health-json-bytes", 5,
		  { "swapzctl", "health", "fixture", "--json", "--bytes", NULL } },
		{ "unknown-option", 3,
		  { "swapzctl", "list", "--unknown", NULL } },
		{ "watch-separate", 5,
		  { "swapzctl", "stats", "fixture", "--watch", "1", NULL } },
		{ "watch-attached", 4,
		  { "swapzctl", "stats", "fixture", "--watch=1", NULL } },
		{ "watch-list", 4,
		  { "swapzctl", "list", "--watch", "1", NULL } },
		{ "selected-path", 4,
		  { "swapzctl", "inspect", "fixture/other", "--bytes", NULL } },
		{ "selected-empty", 4,
		  { "swapzctl", "inspect", "", "--json", NULL } }
	};
	char output[2048];
	char diagnostic[2048];
	unsigned int ioctl_calls = fake_dm_ioctl_calls;
	size_t index;

	/* All invalid forms refuse before probing a module or touching a mapper. */
	for (index = 0; index < sizeof(invalid) / sizeof(invalid[0]); ++index) {
		struct swapz_test_cli_call call = {
			.argc = invalid[index].argc,
			.argv = invalid[index].argv
		};
		int result = swapz_test_capture_output(swapz_test_invoke_cli, &call,
						       output, sizeof(output),
						       diagnostic, sizeof(diagnostic));

		if (result != 2 || output[0] ||
		    !strstr(diagnostic, "BLOCKED: unsupported") ||
		    !strstr(diagnostic, "no mapper or swap activation performed") ||
		    fake_dm_ioctl_calls != ioctl_calls) {
			fprintf(stderr, "FAIL: public CLI option case=%s exit=%d\n",
				invalid[index].label, result);
			abort();
		}
	}
}


/*
 * The public observer filters non-swapz DM targets from its ready report.
 * A single ready target is therefore not proof that the complete DM table has
 * exactly one target: the future watch adapter must retain the full count.
 * Exercise actual INFO parsing and two-read identity binding, not a guessed
 * mapping constructed from already-filtered reporting structures.
 */
enum swapz_test_mixed_table_change {
	SWAPZ_TEST_MIXED_STABLE,
	SWAPZ_TEST_MIXED_NAME_CHANGE,
	SWAPZ_TEST_MIXED_DEVICE_CHANGE,
	SWAPZ_TEST_MIXED_EVENT_CHANGE,
	SWAPZ_TEST_MIXED_TARGET_COUNT_CHANGE,
	SWAPZ_TEST_MIXED_TARGET_TYPE_CHANGE,
	SWAPZ_TEST_MIXED_TARGET_STATUS_CHANGE,
	SWAPZ_TEST_MIXED_TARGET_GEOMETRY_CHANGE,
	SWAPZ_TEST_MIXED_SWAPZ_COUNTER_CHANGE,
	SWAPZ_TEST_MIXED_SECOND_SWAPZ_CHANGE
};

struct swapz_test_mixed_table_fixture {
	struct status_ready_report report;
	enum swapz_test_mixed_table_change change;
	unsigned int full_target_count;
	unsigned int swapz_target_index;
	int two_swapz_targets;
	unsigned int read_calls;
};

static int swapz_test_read_mixed_table(void *context, const char *name,
				      uint64_t expected_device,
				      struct dm_status_observation *observation,
				      struct status_problem *problem,
				      unsigned int *problem_target)
{
	struct swapz_test_mixed_table_fixture *fixture = context;
	const int second_read = (fixture->read_calls++ & 1U) != 0U;
	const char *types[2] = { "linear", "linear" };
	const char *statuses[2] = { "non-swapz-private", "non-swapz-private" };
	unsigned int count = fixture->full_target_count;
	unsigned char *buffer = malloc(2048U);
	struct dm_ioctl header;
	size_t reply_size;
	int result;

	assert(buffer && count >= 1U && count <= 2U);
	assert(fixture->swapz_target_index < count);
	types[fixture->swapz_target_index] = "swapz";
	statuses[fixture->swapz_target_index] = fixture_valid_status;
	if (fixture->two_swapz_targets) {
		assert(count == 2U);
		types[1U - fixture->swapz_target_index] = "swapz";
		statuses[1U - fixture->swapz_target_index] = fixture_valid_status;
	}
	if (second_read) {
		switch (fixture->change) {
		case SWAPZ_TEST_MIXED_TARGET_COUNT_CHANGE:
			count = 1U;
			break;
		case SWAPZ_TEST_MIXED_TARGET_TYPE_CHANGE:
			types[1] = "crypt";
			break;
		case SWAPZ_TEST_MIXED_TARGET_STATUS_CHANGE:
			statuses[1] = "modified-non-swapz-private";
			break;
		case SWAPZ_TEST_MIXED_SWAPZ_COUNTER_CHANGE:
			statuses[fixture->swapz_target_index] =
				"logical_write=8192 physical_write=8192 gc_write=0 "
				"compressed=2 raw=0 zero_elided=0 bulk_mode=1 "
				"bulk_padding=0 failed=0 error=0";
			break;
		case SWAPZ_TEST_MIXED_SECOND_SWAPZ_CHANGE:
			types[1] = "swapz";
			statuses[1] = fixture_valid_status;
			break;
		default:
			break;
		}
	}
	reply_size = make_dm_multi_fixture(buffer, 2048U, types, statuses,
					   NULL, count, expected_device);
	memcpy(&header, buffer, sizeof(header));
	header.event_nr = 7U;
	if (second_read) {
		struct dm_target_spec specification;

		switch (fixture->change) {
		case SWAPZ_TEST_MIXED_NAME_CHANGE:
			memset(header.name, 0, sizeof(header.name));
			memcpy(header.name, "replacement", sizeof("replacement"));
			break;
		case SWAPZ_TEST_MIXED_DEVICE_CHANGE:
			header.dev = expected_device + 1U;
			break;
		case SWAPZ_TEST_MIXED_EVENT_CHANGE:
			++header.event_nr;
			break;
		case SWAPZ_TEST_MIXED_TARGET_GEOMETRY_CHANGE:
			memcpy(&specification, buffer + sizeof(header),
			       sizeof(specification));
			++specification.length;
			memcpy(buffer + sizeof(header), &specification,
			       sizeof(specification));
			break;
		default:
			break;
		}
	}
	memcpy(buffer, &header, sizeof(header));
	memset(observation, 0, sizeof(*observation));
	observation->reply = buffer;
	result = parse_dm_status_observation(buffer, reply_size, name,
					     expected_device, observation,
					     problem, problem_target);
	/* A changed generation must not be accepted after LIST enumeration. */
	return status_bind_list_generation(result, observation, 7U, problem,
					   problem_target);
}

static int swapz_test_collect_mixed_table(void *context)
{
	struct swapz_test_mixed_table_fixture *fixture = context;

	return report_device_status_with_reader(
		fixture, swapz_test_read_mixed_table, "fixture", 1U,
		&fixture->report);
}

static void test_swapz_mixed_full_table_identity_guards(void)
{
	static const struct {
		const char *name;
		enum swapz_test_mixed_table_change change;
		unsigned int full_target_count;
		unsigned int swapz_target_index;
		int two_swapz_targets;
		unsigned int ready_count;
		const char *failure_field;
	} cases[] = {
		{ "single-target", SWAPZ_TEST_MIXED_STABLE, 1, 0, 0, 1, NULL },
		{ "swapz-then-linear", SWAPZ_TEST_MIXED_STABLE, 2, 0, 0, 1, NULL },
		{ "linear-then-swapz", SWAPZ_TEST_MIXED_STABLE, 2, 1, 0, 1, NULL },
		{ "two-swapz", SWAPZ_TEST_MIXED_STABLE, 2, 0, 1, 2, NULL },
		{ "mapper-name-reuse", SWAPZ_TEST_MIXED_NAME_CHANGE, 2, 0, 0, 0,
		  "dm_ioctl.name" },
		{ "mapper-device-reuse", SWAPZ_TEST_MIXED_DEVICE_CHANGE, 2, 0, 0, 0,
		  "dm_ioctl.dev" },
		{ "mapper-generation-change", SWAPZ_TEST_MIXED_EVENT_CHANGE, 2, 0, 0, 0,
		  "dm_ioctl.event_nr" },
		{ "table-target-removed", SWAPZ_TEST_MIXED_TARGET_COUNT_CHANGE,
		  2, 0, 0, 0, "dm_ioctl.target_count" },
		{ "foreign-target-type-changed", SWAPZ_TEST_MIXED_TARGET_TYPE_CHANGE,
		  2, 0, 0, 0, "dm_target_spec.target_type" },
		{ "foreign-target-status-changed", SWAPZ_TEST_MIXED_TARGET_STATUS_CHANGE,
		  2, 0, 0, 0, "dm_target_spec.params" },
		{ "foreign-target-geometry-changed",
		  SWAPZ_TEST_MIXED_TARGET_GEOMETRY_CHANGE, 2, 0, 0, 0,
		  "dm_target_spec.sector_start/length" },
		{ "swapz-counters-changed", SWAPZ_TEST_MIXED_SWAPZ_COUNTER_CHANGE,
		  2, 0, 0, 0, "dm_target_spec.params" },
		{ "foreign-target-converted-to-swapz",
		  SWAPZ_TEST_MIXED_SECOND_SWAPZ_CHANGE, 2, 0, 0, 0,
		  "dm_target_spec.target_type" }
	};
	size_t index;

	for (index = 0; index < sizeof(cases) / sizeof(cases[0]); ++index) {
		struct swapz_test_mixed_table_fixture fixture = {
			.change = cases[index].change,
			.full_target_count = cases[index].full_target_count,
			.swapz_target_index = cases[index].swapz_target_index,
			.two_swapz_targets = cases[index].two_swapz_targets
		};
		char output[64];
		char diagnostic[1024];
		int result = swapz_test_capture_output(
			swapz_test_collect_mixed_table, &fixture,
			output, sizeof(output), diagnostic, sizeof(diagnostic));

		if (cases[index].failure_field) {
			/* Full-table identity drift invalidates the entire snapshot. */
			if (result == 0 || fixture.report.count != 0U ||
			    output[0] || !strstr(diagnostic, cases[index].failure_field) ||
			    strstr(diagnostic, "non-swapz-private") ||
			    strstr(diagnostic, fixture_valid_status)) {
				fprintf(stderr,
					"FAIL: full-table drift case=%s result=%d staged=%zu reads=%u\n",
					cases[index].name, result, fixture.report.count,
					fixture.read_calls);
				abort();
			}
		} else {
			const unsigned int expected_target_count =
				cases[index].full_target_count;

			if (result || diagnostic[0] || output[0] ||
			    fixture.read_calls != 2U ||
			    fixture.report.count != cases[index].ready_count ||
			    fixture.report.targets[0].target_index !=
			    cases[index].swapz_target_index ||
			    fixture.report.targets[0].mapper_sector_end !=
			    (uint64_t)expected_target_count * 1024ULL ||
			    fixture.report.targets[0].dm_table_target_count !=
			    expected_target_count) {
				fprintf(stderr,
					"FAIL: stable full-table case=%s result=%d staged=%zu reads=%u\n",
					cases[index].name, result, fixture.report.count,
					fixture.read_calls);
				abort();
			}
			if (fixture.two_swapz_targets)
				assert(fixture.report.targets[1].target_index == 1U &&
				       fixture.report.targets[1].dm_table_target_count ==
				       expected_target_count);
			/*
			 * Crucial watch-admission negative control: for the mixed
			 * swapz+linear table, ready_count=1 and index=0 despite the
			 * complete table containing two targets. Neither that
			 * filtered count nor a stable INFO pair proves watch safety.
			 */
			if (expected_target_count == 2U &&
			    !fixture.two_swapz_targets)
				assert(fixture.report.count == 1U &&
				       expected_target_count != fixture.report.count);
		}
		free(fixture.report.targets);
	}
}

/*
 * Round 005: real two-INFO origin observations, including multi-target
 * atomicity. All generated DM replies use the existing bounded fake reader.
 */
#define ROUND005_BASE_STATUS \
	"logical_write=8192 physical_write=4096 gc_write=0 " \
	"compressed=2 raw=0 zero_elided=0 bulk_mode=1 bulk_padding=0 " \
	"failed=0 error=0"
#define ROUND005_ORIGIN(admitted, committed, carrier) \
	ROUND005_BASE_STATUS \
	" verified_zswap_origin_admitted=" admitted \
	" foreground_committed_verified_zswap_writeback=" committed \
	" origin_carrier_compiled=" carrier

struct round005_expected_origin {
	unsigned int valid;
	unsigned long long admitted;
	unsigned long long committed;
	unsigned long long carrier;
};

struct round005_origin_reader_call {
	struct status_reader_fixture *fixture;
	struct status_ready_report *report;
};

static int round005_read_origin_pair(void *context)
{
	struct round005_origin_reader_call *call = context;

	return report_device_status_with_reader(call->fixture,
		read_fixture_observation, "fixture", 1, call->report);
}

static int round005_report_origin(void *context)
{
	report_swapz_origin_telemetry(context);
	return 0;
}

static void round005_assert_origin(const struct swapz_ratio_status *ratio,
				   const struct round005_expected_origin *expected)
{
	char output[512];
	char error_output[128];

	assert(ratio->origin_telemetry_valid == (int)expected->valid);
	assert(ratio->verified_zswap_origin_admitted == expected->admitted);
	assert(ratio->foreground_committed_verified_zswap_writeback ==
	       expected->committed);
	assert(ratio->origin_carrier_compiled == expected->carrier);
	assert(swapz_test_capture_output(round005_report_origin, (void *)ratio,
					 output, sizeof(output), error_output,
					 sizeof(error_output)) == 0);
	assert(!error_output[0]);
	if (!expected->valid) {
		assert(strstr(output, "Origin INFO: unavailable"));
		assert(!strstr(output, "Verified admissions: 0 pages"));
	} else {
		assert(!strstr(output, "Origin INFO: unavailable"));
		assert(strstr(output, expected->carrier ?
			      "Carrier compiled: yes" : "Carrier compiled: no"));
		if (!expected->admitted)
			assert(strstr(output, "Verified admissions: 0 pages"));
		if (!expected->committed)
			assert(strstr(output, "Verified foreground commits: 0 pages"));
	}
}

struct round005_origin_case {
	const char *name;
	const char *const *first_statuses;
	size_t first_count;
	const char *const *second_statuses;
	size_t second_count;
	uint64_t second_device;
	int second_target_status;
	size_t expected_reads;
	const char *expected_state;
	const char *expected_field;
	const char *expected_target;
	struct round005_expected_origin first_origin;
	struct round005_expected_origin second_origin;
};

static void test_round005_double_info_origin_snapshot_races(void)
{
	static const char *const legacy[] = { ROUND005_BASE_STATUS };
	static const char *const zero_disabled[] = {
		ROUND005_ORIGIN("0", "0", "0")
	};
	static const char *const zero_enabled[] = {
		ROUND005_ORIGIN("0", "0", "1")
	};
	static const char *const one_committed[] = {
		ROUND005_ORIGIN("2", "1", "1")
	};
	static const char *const two_committed[] = {
		ROUND005_ORIGIN("2", "2", "1")
	};
	static const char *const torn_admissions[] = {
		ROUND005_ORIGIN("1", "2", "1")
	};
	static const char *const torn_total_pages[] = {
		ROUND005_ORIGIN("3", "3", "1")
	};
	static const char *const invalid_carrier[] = {
		ROUND005_ORIGIN("2", "1", "2")
	};
	static const char *const partial_group[] = {
		ROUND005_BASE_STATUS " verified_zswap_origin_admitted=2"
	};
	static const char *const unavailable[] = {
		"status_snapshot_error=-5"
	};
	static const char *const changing_admissions[] = {
		ROUND005_ORIGIN("2", "1", "1"),
		ROUND005_ORIGIN("3", "1", "1")
	};
	static const char *const changing_commits[] = {
		ROUND005_ORIGIN("2", "1", "1"),
		ROUND005_ORIGIN("2", "2", "1")
	};
	static const char *const changing_carrier[] = {
		ROUND005_ORIGIN("0", "0", "0"),
		ROUND005_ORIGIN("0", "0", "1")
	};
	static const char *const changing_availability[] = {
		ROUND005_BASE_STATUS,
		ROUND005_ORIGIN("0", "0", "0")
	};
	static const char *const converging[] = {
		ROUND005_ORIGIN("2", "1", "1"),
		ROUND005_ORIGIN("2", "2", "1"),
		ROUND005_ORIGIN("2", "2", "1"),
		ROUND005_ORIGIN("2", "2", "1")
	};
	static const struct round005_origin_case cases[] = {
		{ .name = "legacy-both", .first_statuses = legacy,
		  .first_count = 1, .second_statuses = legacy,
		  .second_count = 1, .expected_reads = 2 },
		{ .name = "measured-zero-disabled", .first_statuses = zero_disabled,
		  .first_count = 1, .second_statuses = zero_disabled,
		  .second_count = 1, .expected_reads = 2,
		  .first_origin = { 1, 0, 0, 0 },
		  .second_origin = { 1, 0, 0, 0 } },
		{ .name = "measured-zero-enabled", .first_statuses = zero_enabled,
		  .first_count = 1, .second_statuses = zero_enabled,
		  .second_count = 1, .expected_reads = 2,
		  .first_origin = { 1, 0, 0, 1 },
		  .second_origin = { 1, 0, 0, 1 } },
		{ .name = "enabled-both", .first_statuses = one_committed,
		  .first_count = 1, .second_statuses = two_committed,
		  .second_count = 1, .expected_reads = 2,
		  .first_origin = { 1, 2, 1, 1 },
		  .second_origin = { 1, 2, 2, 1 } },
		{ .name = "torn-admissions-second", .first_statuses = one_committed,
		  .first_count = 1, .second_statuses = torn_admissions,
		  .second_count = 1, .expected_reads = 2U * SWAPZ_STATUS_SNAPSHOT_RETRIES,
		  .expected_state = "UNAVAILABLE",
		  .expected_field = "foreground_committed_verified_zswap_writeback",
		  .expected_target = "target 2 snapshot 2" },
		{ .name = "torn-pages-second", .first_statuses = one_committed,
		  .first_count = 1, .second_statuses = torn_total_pages,
		  .second_count = 1, .expected_reads = 2U * SWAPZ_STATUS_SNAPSHOT_RETRIES,
		  .expected_state = "UNAVAILABLE",
		  .expected_field = "foreground_committed_verified_zswap_writeback",
		  .expected_target = "target 2 snapshot 2" },
		{ .name = "torn-admissions-first", .first_statuses = torn_admissions,
		  .first_count = 1, .second_statuses = one_committed,
		  .second_count = 1, .expected_reads = 2U * SWAPZ_STATUS_SNAPSHOT_RETRIES,
		  .expected_state = "UNAVAILABLE",
		  .expected_field = "foreground_committed_verified_zswap_writeback",
		  .expected_target = "target 1 snapshot 2" },
		{ .name = "changing-admissions-first", .first_statuses = changing_admissions,
		  .first_count = 2, .second_statuses = one_committed,
		  .second_count = 1, .expected_reads = 2U * SWAPZ_STATUS_SNAPSHOT_RETRIES,
		  .expected_state = "UNAVAILABLE",
		  .expected_field = "dm_target_spec.params",
		  .expected_target = "target 1 snapshot 2" },
		{ .name = "changing-commits-second", .first_statuses = one_committed,
		  .first_count = 1, .second_statuses = changing_commits,
		  .second_count = 2, .expected_reads = 2U * SWAPZ_STATUS_SNAPSHOT_RETRIES,
		  .expected_state = "UNAVAILABLE",
		  .expected_field = "dm_target_spec.params",
		  .expected_target = "target 2 snapshot 2" },
		{ .name = "changing-carrier-second", .first_statuses = zero_enabled,
		  .first_count = 1, .second_statuses = changing_carrier,
		  .second_count = 2, .expected_reads = 2U * SWAPZ_STATUS_SNAPSHOT_RETRIES,
		  .expected_state = "UNAVAILABLE",
		  .expected_field = "dm_target_spec.params",
		  .expected_target = "target 2 snapshot 2" },
		{ .name = "changing-presence-second", .first_statuses = legacy,
		  .first_count = 1, .second_statuses = changing_availability,
		  .second_count = 2, .expected_reads = 2U * SWAPZ_STATUS_SNAPSHOT_RETRIES,
		  .expected_state = "UNAVAILABLE",
		  .expected_field = "dm_target_spec.params",
		  .expected_target = "target 2 snapshot 2" },
		{ .name = "converges-on-second-attempt", .first_statuses = one_committed,
		  .first_count = 1, .second_statuses = converging,
		  .second_count = 4, .expected_reads = 4,
		  .first_origin = { 1, 2, 1, 1 },
		  .second_origin = { 1, 2, 2, 1 } },
		{ .name = "invalid-carrier-second", .first_statuses = one_committed,
		  .first_count = 1, .second_statuses = invalid_carrier,
		  .second_count = 1, .expected_reads = 1,
		  .expected_state = "BLOCKED", .expected_field = "origin_carrier_compiled",
		  .expected_target = "target 2 snapshot 1" },
		{ .name = "partial-group-second", .first_statuses = one_committed,
		  .first_count = 1, .second_statuses = partial_group,
		  .second_count = 1, .expected_reads = 1,
		  .expected_state = "BLOCKED",
		  .expected_field = "origin provenance INFO group",
		  .expected_target = "target 2 snapshot 1" },
		{ .name = "invalid-carrier-first", .first_statuses = invalid_carrier,
		  .first_count = 1, .second_statuses = one_committed,
		  .second_count = 1, .expected_reads = 1,
		  .expected_state = "BLOCKED", .expected_field = "origin_carrier_compiled",
		  .expected_target = "target 1 snapshot 1" },
		{ .name = "failed-later-target", .first_statuses = one_committed,
		  .first_count = 1, .second_statuses = one_committed,
		  .second_count = 1, .second_target_status = -5,
		  .expected_reads = 1, .expected_state = "FAILED",
		  .expected_field = "dm_target_spec.status",
		  .expected_target = "target 2 snapshot 1" },
		{ .name = "unavailable-later-target", .first_statuses = one_committed,
		  .first_count = 1, .second_statuses = unavailable,
		  .second_count = 1, .expected_reads = 1,
		  .expected_state = "UNAVAILABLE",
		  .expected_field = "status_snapshot_error",
		  .expected_target = "target 2 snapshot 1" },
		{ .name = "identity-mismatch-second", .first_statuses = one_committed,
		  .first_count = 1, .second_statuses = one_committed,
		  .second_count = 1, .second_device = 2,
		  .expected_reads = 2, .expected_state = "BLOCKED",
		  .expected_field = "dm_ioctl.dev",
		  .expected_target = "snapshot 2" }
	};
	size_t case_index;

	for (case_index = 0; case_index < sizeof(cases) / sizeof(cases[0]);
	     ++case_index) {
		const struct round005_origin_case *scenario = &cases[case_index];
		struct status_reader_fixture fixture = {
			.statuses = scenario->second_statuses,
			.count = scenario->second_count,
			.first_statuses = scenario->first_statuses,
			.first_status_count = scenario->first_count,
			.second_device = scenario->second_device,
			.second_target_status = scenario->second_target_status
		};
		struct status_ready_report report = { 0 };
		struct round005_origin_reader_call call = {
			.fixture = &fixture, .report = &report
		};
		char output[512];
		char diagnostic[2048];
		int result = swapz_test_capture_output(round005_read_origin_pair, &call,
					output, sizeof(output), diagnostic,
					sizeof(diagnostic));

		if (fixture.calls != scenario->expected_reads || output[0]) {
			fprintf(stderr, "FAIL: origin snapshot case=%s reads=%zu expected=%zu partial_output=%u\n",
				scenario->name, fixture.calls, scenario->expected_reads,
				(unsigned int)(output[0] != '\0'));
			abort();
		}
		if (scenario->expected_state) {
			if (result != -2 || report.count || !diagnostic[0] ||
			    !strstr(diagnostic, scenario->expected_state) ||
			    !strstr(diagnostic, scenario->expected_field) ||
			    !strstr(diagnostic, scenario->expected_target) ||
			    strstr(diagnostic, "logical_write=8192") ||
			    strstr(diagnostic, "verified_zswap_origin_admitted=")) {
				fprintf(stderr, "FAIL: origin snapshot case=%s state/result/diagnosis mismatch\n",
					scenario->name);
				abort();
			}
		} else {
			if (result || diagnostic[0] || report.count != 2U ||
			    report.targets[0].target_index != 0U ||
			    report.targets[1].target_index != 1U) {
				fprintf(stderr, "FAIL: origin snapshot case=%s success/target count mismatch\n",
					scenario->name);
				abort();
			}
			round005_assert_origin(&report.targets[0].ratio,
					      &scenario->first_origin);
			round005_assert_origin(&report.targets[1].ratio,
					      &scenario->second_origin);
		}
		free(report.targets);
	}
	assert(sizeof(cases) / sizeof(cases[0]) == 18U);
}

#undef ROUND005_ORIGIN
#undef ROUND005_BASE_STATUS

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
	test_optional_origin_info_group();
	test_round004_origin_adversarial_matrix();
	test_optional_watch_info_counter_validation();
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
	test_status_report_handles_zero_and_expansion_cases();
	test_padding_output_has_no_fabricated_compressed_ratio();
	test_saturated_staged_padding_is_unavailable();
	test_snapshot_retry_exhaustion_and_failures();
	test_complete_snapshot_before_output();
	test_round005_double_info_origin_snapshot_races();
	test_final_inventory_fake_ioctl_observation_gap();
	test_bounded_adversarial_dm_status_corpus();
	test_bounded_adversarial_dm_list_corpus();
	test_adversarial_dm_list_header_bounds();
	test_adversarial_wire_boundaries();
	test_adversarial_failed_info_after_staging();
	test_status_info_errno_precedence();
	test_production_dm_query_error_precedence();
	test_status_is_read_only();
	test_swapz_observation_views();
	test_swapz_linux_swap_inventory_parser();
	test_swapz_linux_swap_priority_exact_values();
	test_swapz_linux_swap_inventory_adversarial_records();
	test_swapz_json_identity_and_document_framing();
	test_swapz_command_specific_help();
	test_swapz_human_option_views();
	test_swapz_public_option_dispatch();
	test_swapz_mixed_full_table_identity_guards();
	puts("PASS: swapzctl status compression-ratio accounting");
	return 0;
}
