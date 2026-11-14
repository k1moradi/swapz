/* SPDX-License-Identifier: GPL-2.0-only */
#define _POSIX_C_SOURCE 200809L
#include "../../../../src/userspace/swapzctl-watch.h"

#include <errno.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define CHECK(condition) do { \
	if (!(condition)) { \
		fprintf(stderr, "FAIL: swapzctl-watch-test.c:%d: %s\n", __LINE__, #condition); \
		return -1; \
	} \
} while (0)

static struct swapz_watch_snapshot sample(uint64_t seconds, long nanoseconds)
{
	struct swapz_watch_snapshot result = { 0 };

	memcpy(result.mapper_name, "swapz-test", sizeof("swapz-test"));
	memcpy(result.target_type, "swapz", sizeof("swapz"));
	result.dm_device = 0x00080001ULL;
	result.event_number = 8;
	result.table_generation = 21;
	result.sector_start = 0;
	result.sector_count = 16384;
	result.target_count = 1;
	result.validated = 1;
	result.observed_at.tv_sec = (time_t)seconds;
	result.observed_at.tv_nsec = nanoseconds;
	result.cumulative[SWAPZ_WATCH_COMPRESSED_PAGES] = 1;
	result.cumulative[SWAPZ_WATCH_RAW_PAGES] = 1;
	result.cumulative[SWAPZ_WATCH_LOGICAL_WRITE_BYTES] = 8192;
	result.cumulative[SWAPZ_WATCH_LOGICAL_READ_BYTES] = 4096;
	result.cumulative[SWAPZ_WATCH_LOWER_READ_BYTES] = 8192;
	result.cumulative[SWAPZ_WATCH_LOWER_WRITE_BYTES] = 8192;
	result.cumulative[SWAPZ_WATCH_LOWER_READ_REQUESTS] = 2;
	result.cumulative[SWAPZ_WATCH_LOWER_WRITE_REQUESTS] = 2;
	result.cumulative[SWAPZ_WATCH_GC_READ_BYTES] = 4096;
	result.cumulative[SWAPZ_WATCH_GC_WRITE_BYTES] = 0;
	result.cumulative[SWAPZ_WATCH_GC_READ_REQUESTS] = 1;
	return result;
}

static struct swapz_watch_snapshot later_sample(uint64_t seconds, long nanoseconds)
{
	struct swapz_watch_snapshot result = sample(seconds, nanoseconds);

	result.cumulative[SWAPZ_WATCH_COMPRESSED_PAGES] = 2;
	result.cumulative[SWAPZ_WATCH_ZERO_ELIDED_PAGES] = 1;
	result.cumulative[SWAPZ_WATCH_LOGICAL_WRITE_BYTES] = 16384;
	result.cumulative[SWAPZ_WATCH_LOGICAL_READ_BYTES] = 12288;
	result.cumulative[SWAPZ_WATCH_LOWER_READ_BYTES] = 16384;
	result.cumulative[SWAPZ_WATCH_LOWER_WRITE_BYTES] = 16384;
	result.cumulative[SWAPZ_WATCH_LOWER_READ_REQUESTS] = 3;
	result.cumulative[SWAPZ_WATCH_LOWER_WRITE_REQUESTS] = 4;
	result.cumulative[SWAPZ_WATCH_GC_READ_BYTES] = 8192;
	result.cumulative[SWAPZ_WATCH_GC_WRITE_BYTES] = 4096;
	result.cumulative[SWAPZ_WATCH_GC_READ_REQUESTS] = 2;
	result.cumulative[SWAPZ_WATCH_GC_WRITE_REQUESTS] = 1;
	return result;
}

static int test_interval_parsing(void)
{
	static const struct {
		const char *text;
		uint64_t nanoseconds;
	} valid[] = {
		{ "1", 1000000000ULL },
		{ "2", 2000000000ULL },
		{ "0.001", 1000000ULL },
		{ "0.123456789", 123456789ULL },
		{ "1.50", 1500000000ULL },
		{ "3600", 3600000000000ULL },
	};
	static const char *invalid[] = {
		"", "0", "0.000000001", "0.0001", "3600.000000001",
		"3601", "0002", "1.", ".1", "+1", "-1", "nan",
		"inf", "1e3", "1,2", "1\n", " 1", "1 ", "1.1234567890",
		"18446744073709551616", "9.0\t",
	};
	uint64_t nanoseconds = 71;
	size_t index;

	for (index = 0; index < sizeof(valid) / sizeof(valid[0]); ++index) {
		CHECK(swapz_watch_parse_interval(valid[index].text, &nanoseconds) == 0);
		CHECK(nanoseconds == valid[index].nanoseconds);
	}
	for (index = 0; index < sizeof(invalid) / sizeof(invalid[0]); ++index) {
		nanoseconds = 71;
		CHECK(swapz_watch_parse_interval(invalid[index], &nanoseconds) == -1);
		CHECK(errno == EINVAL || errno == ERANGE);
		CHECK(nanoseconds == 71);
	}
	CHECK(swapz_watch_parse_interval(NULL, &nanoseconds) == -1);
	CHECK(swapz_watch_parse_interval("1", NULL) == -1);
	return 0;
}

static int test_intervals(void)
{
	struct swapz_watch_snapshot before = sample(9, 500000000L);
	struct swapz_watch_snapshot after = later_sample(11, 0);
	struct swapz_watch_interval result = { 0 };
	struct swapz_watch_interval unchanged;
	unsigned int index;

	CHECK(swapz_watch_compute_interval(&before, &after, &result) == 0);
	CHECK(result.elapsed_nanoseconds == 1500000000ULL);
	CHECK(result.cumulative[SWAPZ_WATCH_LOGICAL_READ_BYTES] == 12288);
	CHECK(result.delta[SWAPZ_WATCH_LOGICAL_READ_BYTES] == 8192);
	CHECK(result.delta[SWAPZ_WATCH_LOGICAL_WRITE_BYTES] == 8192);
	CHECK(result.delta[SWAPZ_WATCH_LOWER_READ_REQUESTS] == 1);
	CHECK(result.delta[SWAPZ_WATCH_LOWER_WRITE_REQUESTS] == 2);
	CHECK(result.delta[SWAPZ_WATCH_GC_WRITE_BYTES] == 4096);
	CHECK(result.per_second[SWAPZ_WATCH_GC_WRITE_BYTES] > 2730.0);
	CHECK(result.per_second[SWAPZ_WATCH_GC_WRITE_BYTES] < 2731.0);
	CHECK(result.delta[SWAPZ_WATCH_RAW_PAGES] == 0);
	before = sample(0, 0);
	after = later_sample(1, 0);
	CHECK(swapz_watch_compute_interval(&before, &after, &result) == 0);
	CHECK(result.elapsed_nanoseconds == 1000000000ULL);
	CHECK(result.per_second[SWAPZ_WATCH_LOGICAL_WRITE_BYTES] == 8192.0);
	before.cumulative[SWAPZ_WATCH_LOGICAL_READ_BYTES] = UINT64_MAX - 20;
	after.cumulative[SWAPZ_WATCH_LOGICAL_READ_BYTES] = UINT64_MAX;
	CHECK(swapz_watch_compute_interval(&before, &after, &result) == 0);
	CHECK(result.delta[SWAPZ_WATCH_LOGICAL_READ_BYTES] == 20);
	CHECK(result.cumulative[SWAPZ_WATCH_LOGICAL_READ_BYTES] == UINT64_MAX);
	/* Preserve the last successful result when any later field is invalid. */
	unchanged = result;
	after.cumulative[SWAPZ_WATCH_LOGICAL_READ_BYTES] = 0;
	CHECK(swapz_watch_compute_interval(&before, &after, &result) == -1);
	CHECK(errno == ERANGE);
	CHECK(memcmp(&unchanged, &result, sizeof(result)) == 0);
	after = later_sample(1, 0);
	for (index = 0; index < 10; ++index) {
		struct swapz_watch_snapshot broken = after;

		switch (index) {
		case 0: ++broken.dm_device; break;
		case 1: ++broken.event_number; break;
		case 2: ++broken.table_generation; break;
		case 3: ++broken.sector_count; break;
		case 4: ++broken.sector_start; break;
		case 5: memcpy(broken.mapper_name, "other", 6); break;
		case 6: broken.target_count = 2; break;
		case 7: broken.kernel_failed = 1; break;
		case 8: broken.kernel_error = -EIO; break;
		default: memcpy(broken.target_type, "linear", 7); break;
		}
		before = sample(0, 0);
		CHECK(swapz_watch_compute_interval(&before, &broken, &result) == -1);
		CHECK(memcmp(&unchanged, &result, sizeof(result)) == 0);
	}
	before = sample(1, 0);
	after = later_sample(1, 0);
	CHECK(swapz_watch_compute_interval(&before, &after, &result) == -1);
	CHECK(errno == ERANGE);
	after.observed_at.tv_sec = 0;
	CHECK(swapz_watch_compute_interval(&before, &after, &result) == -1);
	before = sample(0, 0);
	after = later_sample(2, 0);
	after.cumulative[SWAPZ_WATCH_COMPRESSED_PAGES] = UINT64_MAX;
	CHECK(swapz_watch_compute_interval(&before, &after, &result) == -1);
	before.validated = 0;
	CHECK(swapz_watch_compute_interval(&before, &after, &result) == -1);
	return 0;
}

struct fake_context {
	struct swapz_watch_snapshot readings[4];
	struct timespec times[4];
	unsigned int reading_count;
	unsigned int read_index;
	unsigned int clock_index;
	unsigned int emitted;
	unsigned int waited;
	unsigned int interrupt_count;
	unsigned int stop_on_wait;
	unsigned int fail_on_read;
	unsigned int fail_on_clock;
	unsigned int fail_on_emit;
	uint64_t latest_elapsed;
	uint64_t latest_logical_write_delta;
	struct timespec last_deadline;
	volatile sig_atomic_t stop_requested;
};

static int fake_read(void *context, const char *mapper_name,
		     struct swapz_watch_snapshot *snapshot)
{
	struct fake_context *fixture = context;

	if (fixture->read_index == fixture->fail_on_read ||
	    fixture->read_index >= fixture->reading_count) {
		errno = ENODEV;
		return -1;
	}
	if (strcmp(mapper_name, "swapz-test")) {
		errno = EINVAL;
		return -1;
	}
	*snapshot = fixture->readings[fixture->read_index++];
	return 0;
}

static int fake_clock(void *context, struct timespec *now)
{
	struct fake_context *fixture = context;

	if (fixture->clock_index == fixture->fail_on_clock) {
		errno = EIO;
		return -1;
	}
	*now = fixture->times[fixture->clock_index++];
	return 0;
}

static int fake_wait(void *context, const struct timespec *deadline)
{
	struct fake_context *fixture = context;

	++fixture->waited;
	fixture->last_deadline = *deadline;
	if (fixture->stop_on_wait == fixture->waited)
		fixture->stop_requested = 1;
	if (fixture->interrupt_count) {
		--fixture->interrupt_count;
		errno = EINTR;
		return -1;
	}
	return 0;
}

static int fake_emit(void *context, const struct swapz_watch_interval *interval)
{
	struct fake_context *fixture = context;

	if (fixture->emitted == fixture->fail_on_emit) {
		errno = EPIPE; /* Simulate a closed stdout consumer. */
		return -1;
	}
	++fixture->emitted;
	fixture->latest_elapsed = interval->elapsed_nanoseconds;
	fixture->latest_logical_write_delta =
		interval->delta[SWAPZ_WATCH_LOGICAL_WRITE_BYTES];
	return 0;
}

static struct fake_context fake_fixture(void)
{
	struct fake_context fixture = { 0 };

	fixture.readings[0] = sample(0, 0);
	fixture.readings[1] = later_sample(0, 0);
	fixture.readings[2] = later_sample(0, 0);
	fixture.times[0] = (struct timespec){ .tv_sec = 10, .tv_nsec = 0 };
	fixture.times[1] = (struct timespec){ .tv_sec = 11, .tv_nsec = 500000000 };
	fixture.times[2] = (struct timespec){ .tv_sec = 13, .tv_nsec = 500000000 };
	fixture.reading_count = 3;
	fixture.fail_on_read = UINT32_MAX;
	fixture.fail_on_clock = UINT32_MAX;
	fixture.fail_on_emit = UINT32_MAX;
	return fixture;
}

static int test_runner(void)
{
	struct fake_context fixture = fake_fixture();
	struct swapz_watch_callbacks callbacks = {
		.read_snapshot = fake_read,
		.monotonic_clock = fake_clock,
		.wait_until = fake_wait,
		.emit_interval = fake_emit,
		.context = &fixture,
	};

	CHECK(swapz_watch_run("swapz-test", 2000000000ULL, 2,
			      &fixture.stop_requested, &callbacks) == 0);
	CHECK(fixture.emitted == 2);
	CHECK(fixture.latest_elapsed == 2000000000ULL);
	CHECK(fixture.latest_logical_write_delta == 0);
	CHECK(fixture.waited == 2);
	CHECK(fixture.last_deadline.tv_sec == 13);
	CHECK(fixture.last_deadline.tv_nsec == 500000000);
	fixture = fake_fixture();
	fixture.stop_on_wait = 1;
	CHECK(swapz_watch_run("swapz-test", 1000000000ULL, 2,
			      &fixture.stop_requested, &callbacks) == 0);
	CHECK(fixture.emitted == 0 && fixture.read_index == 1);
	fixture = fake_fixture();
	fixture.fail_on_read = 1;
	CHECK(swapz_watch_run("swapz-test", 1000000000ULL, 2,
			      &fixture.stop_requested, &callbacks) == -1);
	CHECK(errno == ENODEV && fixture.emitted == 0);
	fixture = fake_fixture();
	fixture.fail_on_clock = 1;
	CHECK(swapz_watch_run("swapz-test", 1000000000ULL, 2,
			      &fixture.stop_requested, &callbacks) == -1);
	CHECK(errno == EIO && fixture.emitted == 0);
	fixture = fake_fixture();
	fixture.fail_on_emit = 0;
	CHECK(swapz_watch_run("swapz-test", 1000000000ULL, 2,
			      &fixture.stop_requested, &callbacks) == -1);
	CHECK(errno == EPIPE && fixture.emitted == 0);
	fixture = fake_fixture();
	fixture.interrupt_count = 9;
	CHECK(swapz_watch_run("swapz-test", 1000000000ULL, 2,
			      &fixture.stop_requested, &callbacks) == -1);
	CHECK(errno == EINTR && fixture.emitted == 0);
	fixture = fake_fixture();
	fixture.interrupt_count = 2;
	CHECK(swapz_watch_run("swapz-test", 1000000000ULL, 1,
			      &fixture.stop_requested, &callbacks) == 0);
	CHECK(fixture.emitted == 1 && fixture.waited == 3);
	fixture = fake_fixture();
	fixture.readings[1].event_number++;
	CHECK(swapz_watch_run("swapz-test", 1000000000ULL, 2,
			      &fixture.stop_requested, &callbacks) == -1);
	CHECK(errno == ESTALE && fixture.emitted == 0);
	fixture = fake_fixture();
	fixture.readings[0].validated = 0;
	CHECK(swapz_watch_run("swapz-test", 1000000000ULL, 2,
			      &fixture.stop_requested, &callbacks) == -1);
	CHECK(errno == EPROTO && fixture.emitted == 0);
	fixture = fake_fixture();
	CHECK(swapz_watch_run("swapz-test", 0, 2,
			      &fixture.stop_requested, &callbacks) == -1);
	CHECK(errno == EINVAL && fixture.emitted == 0);
	fixture = fake_fixture();
	CHECK(swapz_watch_run("swapz-test", 1000000000ULL, 0,
			      &fixture.stop_requested, &callbacks) == -1);
	CHECK(errno == EINVAL && fixture.emitted == 0);
	fixture = fake_fixture();
	CHECK(swapz_watch_run("swapz-test", 1000000000ULL,
			      SWAPZ_WATCH_MAX_SAMPLES + 1U,
			      &fixture.stop_requested, &callbacks) == -1);
	CHECK(errno == EINVAL && fixture.emitted == 0);
	fixture = fake_fixture();
	fixture.times[0] = (struct timespec){
		.tv_sec = (time_t)INT64_MAX, .tv_nsec = 0
	};
	CHECK(swapz_watch_run("swapz-test", 1000000000ULL, 1,
			      &fixture.stop_requested, &callbacks) == -1);
	CHECK(errno == EOVERFLOW && fixture.emitted == 0);
	fixture = fake_fixture();
	fixture.stop_requested = 1;
	CHECK(swapz_watch_run("swapz-test", 1000000000ULL, 2,
			      &fixture.stop_requested, &callbacks) == 0);
	CHECK(fixture.read_index == 0 && fixture.emitted == 0);
	return 0;
}

int main(void)
{
	if (test_interval_parsing() < 0 || test_intervals() < 0 ||
	    test_runner() < 0)
		return 1;
	puts("swapzctl-watch-test: PASS (rootless; staged/unlinked sampler)");
	return 0;
}
