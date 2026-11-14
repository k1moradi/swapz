/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZCTL_WATCH_H
#define SWAPZCTL_WATCH_H

#include <linux/dm-ioctl.h>
#include <signal.h>
#include <stdint.h>
#include <time.h>

/* A bounded, read-only worker for a future CLI integration; no DM reader here. */
#define SWAPZ_WATCH_MIN_INTERVAL_NS 1000000ULL
#define SWAPZ_WATCH_MAX_INTERVAL_NS 3600000000000ULL
#define SWAPZ_WATCH_MAX_SAMPLES 4096U

enum swapz_watch_counter {
	SWAPZ_WATCH_LOGICAL_READ_BYTES,
	SWAPZ_WATCH_LOGICAL_WRITE_BYTES,
	SWAPZ_WATCH_LOWER_READ_BYTES,
	SWAPZ_WATCH_LOWER_WRITE_BYTES,
	SWAPZ_WATCH_LOWER_READ_REQUESTS,
	SWAPZ_WATCH_LOWER_WRITE_REQUESTS,
	SWAPZ_WATCH_GC_READ_BYTES,
	SWAPZ_WATCH_GC_WRITE_BYTES,
	SWAPZ_WATCH_GC_READ_REQUESTS,
	SWAPZ_WATCH_GC_WRITE_REQUESTS,
	SWAPZ_WATCH_COMPRESSED_PAGES,
	SWAPZ_WATCH_RAW_PAGES,
	SWAPZ_WATCH_ZERO_ELIDED_PAGES,
	SWAPZ_WATCH_COUNTER_COUNT
};

/*
 * Only an independently validated, complete two-INFO/final-LIST report may
 * set validated=1. The producer owns no borrowed DM buffers after returning.
 * Observational identity is not lifecycle ownership or swapoff authority.
 */
struct swapz_watch_snapshot {
	char mapper_name[DM_NAME_LEN];
	/* DM UUID is optional; its presence and exact bytes form one identity. */
	char dm_uuid[DM_UUID_LEN];
	char target_type[DM_MAX_TYPE_NAME];
	uint64_t dm_device;
	uint64_t sector_start;
	uint64_t sector_count;
	uint64_t table_generation;
	uint32_t event_number;
	uint32_t target_index;
	uint32_t target_count;
	uint64_t cumulative[SWAPZ_WATCH_COUNTER_COUNT];
	int has_dm_uuid;
	int validated;
	int kernel_failed;
	int kernel_error;
	struct timespec observed_at;
};

/* Exact integer deltas and cumulative totals; rate estimates are floating point. */
struct swapz_watch_interval {
	uint64_t elapsed_nanoseconds;
	uint64_t cumulative[SWAPZ_WATCH_COUNTER_COUNT];
	uint64_t delta[SWAPZ_WATCH_COUNTER_COUNT];
	double per_second[SWAPZ_WATCH_COUNTER_COUNT];
};

/*
 * All callbacks run synchronously on the caller's thread. read_snapshot must
 * use only the validated read-only status collector, identify exactly one
 * selected swapz target and return -1 with errno on ANY failure. The worker
 * never opens a device, prints to stdout, starts threads or installs handlers.
 * Caller-owned signal handlers may ONLY set *stop_requested (sig_atomic_t).
 * wait_until receives a monotonic absolute deadline and may report EINTR.
 * emit_interval must report failed/closed output (including EPIPE) as -1.
 */
struct swapz_watch_callbacks {
	int (*read_snapshot)(void *context, const char *mapper_name,
			     struct swapz_watch_snapshot *snapshot);
	int (*monotonic_clock)(void *context, struct timespec *now);
	int (*wait_until)(void *context, const struct timespec *deadline);
	int (*emit_interval)(void *context,
			     const struct swapz_watch_interval *interval);
	void *context;
};

int swapz_watch_parse_interval(const char *seconds, uint64_t *nanoseconds);
int swapz_watch_compute_interval(const struct swapz_watch_snapshot *before,
				 const struct swapz_watch_snapshot *after,
				 struct swapz_watch_interval *interval);
int swapz_watch_run(const char *mapper_name, uint64_t interval_nanoseconds,
		    unsigned int maximum_samples,
		    const volatile sig_atomic_t *stop_requested,
		    const struct swapz_watch_callbacks *callbacks);

/* Production clock/wait adapters: no signal handlers or side effects. */
int swapz_watch_monotonic_clock(void *context, struct timespec *now);
int swapz_watch_wait_until(void *context, const struct timespec *deadline);

#endif
