/* SPDX-License-Identifier: GPL-2.0-only */
#define _POSIX_C_SOURCE 200809L
#include "swapzctl-watch.h"

#include <errno.h>
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define SWAPZ_WATCH_NANOSECONDS_PER_SECOND 1000000000ULL
#define SWAPZ_WATCH_PAGE_BYTES 4096ULL
#define SWAPZ_WATCH_MAX_INTERRUPTED_WAITS 8U

int swapz_watch_parse_interval(const char *seconds, uint64_t *nanoseconds)
{
	uint64_t whole_seconds = 0;
	uint64_t fractional_nanoseconds = 0;
	unsigned int fractional_digits = 0;
	const unsigned char *cursor;

	if (!seconds || !nanoseconds || !seconds[0]) {
		errno = EINVAL;
		return -1;
	}
	cursor = (const unsigned char *)seconds;
	if (*cursor < '0' || *cursor > '9') {
		errno = EINVAL;
		return -1;
	}
	/* Reject ambiguous noncanonical forms and locale-specific spellings. */
	if (*cursor == '0' && cursor[1] >= '0' && cursor[1] <= '9') {
		errno = EINVAL;
		return -1;
	}
	while (*cursor >= '0' && *cursor <= '9') {
		unsigned int digit = (unsigned int)(*cursor++ - '0');

		if (whole_seconds >
		    (SWAPZ_WATCH_MAX_INTERVAL_NS /
		     SWAPZ_WATCH_NANOSECONDS_PER_SECOND - digit) / 10ULL) {
			errno = ERANGE;
			return -1;
		}
		whole_seconds = whole_seconds * 10ULL + digit;
	}
	if (*cursor == '.') {
		++cursor;
		if (*cursor < '0' || *cursor > '9') {
			errno = EINVAL;
			return -1;
		}
		while (*cursor >= '0' && *cursor <= '9') {
			if (fractional_digits == 9U) {
				errno = ERANGE;
				return -1;
			}
			fractional_nanoseconds =
				fractional_nanoseconds * 10ULL +
				(unsigned int)(*cursor++ - '0');
			++fractional_digits;
		}
	}
	if (*cursor) {
		errno = EINVAL;
		return -1;
	}
	while (fractional_digits++ < 9U)
		fractional_nanoseconds *= 10ULL;
	if (whole_seconds ==
	    SWAPZ_WATCH_MAX_INTERVAL_NS /
	    SWAPZ_WATCH_NANOSECONDS_PER_SECOND && fractional_nanoseconds) {
		errno = ERANGE;
		return -1;
	}
	whole_seconds = whole_seconds * SWAPZ_WATCH_NANOSECONDS_PER_SECOND +
		fractional_nanoseconds;
	if (whole_seconds < SWAPZ_WATCH_MIN_INTERVAL_NS ||
	    whole_seconds > SWAPZ_WATCH_MAX_INTERVAL_NS) {
		errno = ERANGE;
		return -1;
	}
	*nanoseconds = whole_seconds;
	return 0;
}

static int swapz_watch_valid_snapshot(const struct swapz_watch_snapshot *snapshot)
{
	uint64_t page_count;
	const uint64_t *cumulative = snapshot->cumulative;

	if (snapshot->validated != 1 || snapshot->kernel_failed ||
	    snapshot->kernel_error || !snapshot->dm_device ||
	    snapshot->target_count != 1U || snapshot->target_index != 0U ||
	    !snapshot->sector_count ||
	    snapshot->sector_start > UINT64_MAX - snapshot->sector_count ||
	    !memchr(snapshot->mapper_name, '\0', sizeof(snapshot->mapper_name)) ||
	    !snapshot->mapper_name[0] ||
	    (snapshot->has_dm_uuid != 0 && snapshot->has_dm_uuid != 1) ||
	    !memchr(snapshot->dm_uuid, '\0', sizeof(snapshot->dm_uuid)) ||
	    (snapshot->has_dm_uuid ? !snapshot->dm_uuid[0] :
	     snapshot->dm_uuid[0] != '\0') ||
	    !memchr(snapshot->target_type, '\0', sizeof(snapshot->target_type)) ||
	    strcmp(snapshot->target_type, "swapz")) {
		errno = EPROTO;
		return -1;
	}
	if (cumulative[SWAPZ_WATCH_COMPRESSED_PAGES] >
	    UINT64_MAX - cumulative[SWAPZ_WATCH_RAW_PAGES]) {
		errno = EOVERFLOW;
		return -1;
	}
	page_count = cumulative[SWAPZ_WATCH_COMPRESSED_PAGES] +
		cumulative[SWAPZ_WATCH_RAW_PAGES];
	if (page_count > UINT64_MAX - cumulative[SWAPZ_WATCH_ZERO_ELIDED_PAGES]) {
		errno = EOVERFLOW;
		return -1;
	}
	page_count += cumulative[SWAPZ_WATCH_ZERO_ELIDED_PAGES];
	if (page_count > UINT64_MAX / SWAPZ_WATCH_PAGE_BYTES ||
	    cumulative[SWAPZ_WATCH_LOGICAL_WRITE_BYTES] !=
	    page_count * SWAPZ_WATCH_PAGE_BYTES ||
	    cumulative[SWAPZ_WATCH_GC_READ_BYTES] >
	    cumulative[SWAPZ_WATCH_LOWER_READ_BYTES] ||
	    cumulative[SWAPZ_WATCH_GC_WRITE_BYTES] >
	    cumulative[SWAPZ_WATCH_LOWER_WRITE_BYTES] ||
	    cumulative[SWAPZ_WATCH_GC_READ_REQUESTS] >
	    cumulative[SWAPZ_WATCH_LOWER_READ_REQUESTS] ||
	    cumulative[SWAPZ_WATCH_GC_WRITE_REQUESTS] >
	    cumulative[SWAPZ_WATCH_LOWER_WRITE_REQUESTS]) {
		errno = EPROTO;
		return -1;
	}
	return 0;
}

static int swapz_watch_elapsed(const struct timespec *before,
			       const struct timespec *after, uint64_t *elapsed)
{
	uint64_t seconds;
	uint64_t nanoseconds;

	if (before->tv_sec < 0 || after->tv_sec < 0 ||
	    before->tv_nsec < 0 || before->tv_nsec >= 1000000000L ||
	    after->tv_nsec < 0 || after->tv_nsec >= 1000000000L ||
	    after->tv_sec < before->tv_sec ||
	    (after->tv_sec == before->tv_sec &&
	     after->tv_nsec <= before->tv_nsec)) {
		errno = ERANGE;
		return -1;
	}
	seconds = (uint64_t)after->tv_sec - (uint64_t)before->tv_sec;
	if (after->tv_nsec >= before->tv_nsec) {
		nanoseconds = (uint64_t)(after->tv_nsec - before->tv_nsec);
	} else {
		--seconds;
		nanoseconds = SWAPZ_WATCH_NANOSECONDS_PER_SECOND -
			(uint64_t)(before->tv_nsec - after->tv_nsec);
	}
	if (seconds > (UINT64_MAX - nanoseconds) /
	    SWAPZ_WATCH_NANOSECONDS_PER_SECOND) {
		errno = EOVERFLOW;
		return -1;
	}
	*elapsed = seconds * SWAPZ_WATCH_NANOSECONDS_PER_SECOND +
		nanoseconds;
	return 0;
}

int swapz_watch_compute_interval(const struct swapz_watch_snapshot *before,
				 const struct swapz_watch_snapshot *after,
				 struct swapz_watch_interval *interval)
{
	struct swapz_watch_interval computed = { 0 };
	unsigned int counter_index;

	if (!before || !after || !interval) {
		errno = EINVAL;
		return -1;
	}
	if (swapz_watch_valid_snapshot(before) < 0 ||
	    swapz_watch_valid_snapshot(after) < 0)
		return -1;
	if (strcmp(before->mapper_name, after->mapper_name) ||
	    before->has_dm_uuid != after->has_dm_uuid ||
	    (before->has_dm_uuid && strcmp(before->dm_uuid, after->dm_uuid)) ||
	    before->dm_device != after->dm_device ||
	    before->event_number != after->event_number ||
	    before->table_generation != after->table_generation ||
	    before->target_index != after->target_index ||
	    before->target_count != after->target_count ||
	    before->sector_start != after->sector_start ||
	    before->sector_count != after->sector_count ||
	    strcmp(before->target_type, after->target_type)) {
		errno = ESTALE;
		return -1;
	}
	if (swapz_watch_elapsed(&before->observed_at, &after->observed_at,
				&computed.elapsed_nanoseconds) < 0)
		return -1;
	for (counter_index = 0; counter_index < SWAPZ_WATCH_COUNTER_COUNT;
	     ++counter_index) {
		uint64_t earlier = before->cumulative[counter_index];
		uint64_t later = after->cumulative[counter_index];

		if (later < earlier) {
			errno = ERANGE; /* reset/wrap, never a negative or huge rate */
			return -1;
		}
		computed.cumulative[counter_index] = later;
		computed.delta[counter_index] = later - earlier;
		computed.per_second[counter_index] =
			(double)computed.delta[counter_index] *
			(double)SWAPZ_WATCH_NANOSECONDS_PER_SECOND /
			(double)computed.elapsed_nanoseconds;
	}
	*interval = computed; /* Never publish partial counter/rate sets. */
	return 0;
}

/* All wait times are monotonic absolute deadlines, not repeated relative sleeps. */
static int swapz_watch_deadline(const struct timespec *now,
				uint64_t interval_nanoseconds,
				struct timespec *deadline)
{
	uint64_t seconds;
	uint64_t nanoseconds;

	if (now->tv_sec < 0 || now->tv_nsec < 0 ||
	    now->tv_nsec >= 1000000000L) {
		errno = ERANGE;
		return -1;
	}
	seconds = interval_nanoseconds / SWAPZ_WATCH_NANOSECONDS_PER_SECOND;
	nanoseconds = (uint64_t)now->tv_nsec +
		interval_nanoseconds % SWAPZ_WATCH_NANOSECONDS_PER_SECOND;
	if (nanoseconds >= SWAPZ_WATCH_NANOSECONDS_PER_SECOND) {
		++seconds;
		nanoseconds -= SWAPZ_WATCH_NANOSECONDS_PER_SECOND;
	}
	/* Linux time_t may be 32-bit even with a 64-bit counter type. */
	if (seconds > (sizeof(time_t) == sizeof(int32_t) ?
			(uint64_t)INT32_MAX : (uint64_t)INT64_MAX) -
	    (uint64_t)now->tv_sec) {
		errno = EOVERFLOW;
		return -1;
	}
	deadline->tv_sec = now->tv_sec + (time_t)seconds;
	deadline->tv_nsec = (long)nanoseconds;
	return 0;
}

int swapz_watch_run(const char *mapper_name, uint64_t interval_nanoseconds,
		    unsigned int maximum_samples,
		    const volatile sig_atomic_t *stop_requested,
		    const struct swapz_watch_callbacks *callbacks)
{
	struct swapz_watch_snapshot previous = { 0 };
	struct swapz_watch_snapshot next = { 0 };
	unsigned int emitted_samples;

	if (!mapper_name || !*mapper_name || !callbacks ||
	    !callbacks->read_snapshot || !callbacks->monotonic_clock ||
	    !callbacks->wait_until || !callbacks->emit_interval ||
	    !stop_requested || !maximum_samples ||
	    maximum_samples > SWAPZ_WATCH_MAX_SAMPLES ||
	    interval_nanoseconds < SWAPZ_WATCH_MIN_INTERVAL_NS ||
	    interval_nanoseconds > SWAPZ_WATCH_MAX_INTERVAL_NS ||
	    !memchr(mapper_name, '\0', DM_NAME_LEN)) {
		errno = EINVAL;
		return -1;
	}
	if (*stop_requested)
		return 0;
	if (callbacks->read_snapshot(callbacks->context, mapper_name, &previous) < 0)
		return -1;
	if (callbacks->monotonic_clock(callbacks->context, &previous.observed_at) < 0)
		return -1;
	if (swapz_watch_valid_snapshot(&previous) < 0 ||
	    strcmp(previous.mapper_name, mapper_name)) {
		errno = EPROTO;
		return -1;
	}
	for (emitted_samples = 0; emitted_samples < maximum_samples;
	     ++emitted_samples) {
		struct timespec deadline;
		struct swapz_watch_interval interval;
		unsigned int interrupted_waits = 0;

		if (*stop_requested)
			return 0;
		if (swapz_watch_deadline(&previous.observed_at,
					interval_nanoseconds, &deadline) < 0)
			return -1;
		for (;;) {
			if (*stop_requested)
				return 0;
			if (callbacks->wait_until(callbacks->context, &deadline) == 0)
				break;
			if (errno != EINTR || ++interrupted_waits >
			    SWAPZ_WATCH_MAX_INTERRUPTED_WAITS)
				return -1;
		}
		if (*stop_requested)
			return 0;
		memset(&next, 0, sizeof(next));
		if (callbacks->read_snapshot(callbacks->context, mapper_name, &next) < 0)
			return -1;
		if (callbacks->monotonic_clock(callbacks->context, &next.observed_at) < 0)
			return -1;
		if (swapz_watch_compute_interval(&previous, &next, &interval) < 0)
			return -1;
		if (*stop_requested)
			return 0;
		if (callbacks->emit_interval(callbacks->context, &interval) < 0)
			return -1;
		previous = next;
	}
	return 0;
}

int swapz_watch_monotonic_clock(void *context, struct timespec *now)
{
	(void)context;
	if (!now) {
		errno = EINVAL;
		return -1;
	}
	return clock_gettime(CLOCK_MONOTONIC, now);
}

int swapz_watch_wait_until(void *context, const struct timespec *deadline)
{
	int error;

	(void)context;
	if (!deadline) {
		errno = EINVAL;
		return -1;
	}
	error = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME,
				deadline, NULL);
	if (error) {
		errno = error;
		return -1;
	}
	return 0;
}
