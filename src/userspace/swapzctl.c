// SPDX-License-Identifier: GPL-2.0-only
/*
 * Explicit swapz administrative tool. Status is read-only; primary lifecycle
 * subcommands delegate mapper and swapon/swapoff ownership to swapz-primary,
 * which preserves the ordinary SWAPSPACE2 backing header and fails closed.
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/dm-ioctl.h>
#include <linux/fs.h>
#include <limits.h>
#include <inttypes.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

#include "swapz-primary.h"

#ifndef SWAPZ_VERSION
#define SWAPZ_VERSION "unknown"
#endif

#define SWAPZ_LOGICAL_PAGE_BYTES 4096ULL
#define SWAPZ_DM_CONTROL_PATH "/dev/mapper/control"
#define SWAPZ_DM_BUFFER_INITIAL (64U * 1024U)
#define SWAPZ_DM_BUFFER_MAX (1024U * 1024U)
/* Device Mapper records are eight-byte aligned on the wire, even on 32-bit C ABIs. */
#define SWAPZ_DM_WIRE_ALIGNMENT 8U
#define SWAPZ_STATUS_MAX_TARGETS 4096U
#define SWAPZ_STATUS_MAX_RESULTS 65536U
#define SWAPZ_STATUS_SNAPSHOT_RETRIES 8U

static void usage(FILE *out)
{
	fputs("Usage: swapzctl version | status [--json] | list [--json] | help [command]\n", out);
	fputs("       swapzctl inspect|stats|health|diagnose <mapper-name> [--json]\n", out);
	fputs("       swapzctl primary plan|qualification-import <report>|"
	      "prepare|start|stop|recover\n", out);
	fputs("status reports cumulative committed foreground compression ratios "
	      "for active swapz targets.\n", out);
	fputs("Physical backing requires validated exclusive partition ownership.\n", out);
	fputs("Raw backing partitions are never formatted by swapzctl.\n", out);
	fputs("Primary lifecycle commands remain guarded by qualification and "
	      "ownership checks.\n", out);
	fputs("Only the new virtual mapper may receive mkswap.\n", out);
}

struct swapz_ratio_status {
	unsigned long long logical_write_bytes;
	unsigned long long physical_write_bytes;
	unsigned long long gc_write_bytes;
	unsigned long long compressed_pages;
	unsigned long long raw_pages;
	unsigned long long zero_elided_pages;
	unsigned long long bulk_mode;
	unsigned long long bulk_padding_blocks;
	unsigned long long failed;
	int error;
	unsigned long long compressed_logical_bytes;
	unsigned long long compressed_extent_bytes;
	unsigned long long overall_physical_bytes;
	int compressed_extent_ratio_exact;
};

enum status_ratio_state {
	STATUS_BLOCKED = -1,
	STATUS_READY = 0,
	STATUS_RETRY = 1,
	STATUS_FAILED = 2,
	STATUS_UNAVAILABLE = 3
};

struct status_problem {
	const char *field;
	const char *expected;
	const char *observed;
	int kernel_errno;
	/* Zero for wire/parser faults; keep the originating bounded-read errno. */
	int failure_errno;
};

struct swapz_target_snapshot {
	uint64_t sector_start;
	uint64_t length;
	uint64_t device_id;
	uint32_t event_number;
	struct swapz_ratio_status ratio;
	struct status_problem problem;
	int ratio_state;
	int target_status;
	int is_swapz;
	char target_type[DM_MAX_TYPE_NAME];
	/* Both pointers refer to the owning observation's immutable reply. */
	const char *status_text;
	size_t status_length;
};

struct dm_status_observation {
	unsigned char *reply;
	struct swapz_target_snapshot *targets;
	uint64_t device_id;
	uint32_t event_number;
	uint32_t target_count;
	uint32_t flags;
};

struct status_ready_target {
	char name[DM_NAME_LEN];
	unsigned int target_index;
	uint64_t device_id;
	uint64_t sector_start;
	uint64_t sector_length;
	struct swapz_ratio_status ratio;
};

struct status_ready_report {
	struct status_ready_target *targets;
	size_t count;
	size_t capacity;
};

struct dm_list_record {
	const char *name;
	const char *uuid;
	uint64_t device_id;
	uint32_t event_number;
	uint32_t flags;
	size_t record_size;
};

static void status_set_problem(struct status_problem *problem,
			       const char *field, const char *expected,
			       const char *observed)
{
	problem->field = field;
	problem->expected = expected;
	problem->observed = observed;
	problem->kernel_errno = 0;
	problem->failure_errno = 0;
}

static int status_separator(char character)
{
	return character == ' ' || character == '\t' || character == '\n';
}

/* Find exactly one complete key=value token; unknown status keys are harmless. */
static int status_find_value(const char *status, const char *key,
			     const char *expected, const char **value_start,
			     const char **value_end, struct status_problem *problem)
{
	const size_t key_length = strlen(key);
	const char *cursor = status;
	int found = 0;

	while (*cursor) {
		const char *token_end;
		size_t token_length;

		while (*cursor && status_separator(*cursor))
			++cursor;
		if (!*cursor)
			break;
		token_end = cursor;
		while (*token_end && !status_separator(*token_end))
			++token_end;
		token_length = (size_t)(token_end - cursor);
		if (token_length >= key_length &&
		    !memcmp(cursor, key, key_length) &&
		    (token_length == key_length || cursor[key_length] == '=')) {
			if (found) {
				status_set_problem(problem, key, expected, "duplicate token");
				return -1;
			}
			if (token_length == key_length) {
				status_set_problem(problem, key, expected,
						   "token has no '=' or value");
				return -1;
			}
			*value_start = cursor + key_length + 1U;
			*value_end = token_end;
			found = 1;
		}
		cursor = token_end;
	}
	return found;
}

/*
 * Parse a canonical unsigned decimal prefix without locale, allocations or
 * overflow. Leave outputs unchanged on failure; callers verify the token end.
 */
static int parse_unsigned_decimal(const char *text, unsigned long long limit,
				  const char **parsed_end, unsigned long long *value)
{
	const char *cursor;
	unsigned long long number = 0;

	if (!text || !parsed_end || !value || *text < '0' || *text > '9')
		return -1;
	if (text[0] == '0' && text[1] >= '0' && text[1] <= '9')
		return -1;
	for (cursor = text; *cursor >= '0' && *cursor <= '9'; ++cursor) {
		const unsigned int digit = (unsigned int)(*cursor - '0');

		if (number > limit / 10ULL ||
		    (number == limit / 10ULL && digit > limit % 10ULL))
			return -1;
		number = number * 10ULL + digit;
	}
	*parsed_end = cursor;
	*value = number;
	return 0;
}

static int parse_status_unsigned(const char *status, const char *key,
				 unsigned long long limit,
				 unsigned long long *value,
				 struct status_problem *problem)
{
	const char *value_start;
	const char *value_end;
	const char *parsed_end;
	const char *expected = limit == 1ULL ?
		"one canonical decimal boolean (0 or 1)" :
		limit == 2ULL ? "one canonical decimal mode (0, 1 or 2)" :
		limit == UINT_MAX ?
		"one canonical unsigned 32-bit decimal (0..4294967295)" :
		"one canonical unsigned 64-bit decimal (0..18446744073709551615)";
	int found = status_find_value(status, key, expected, &value_start,
				      &value_end, problem);

	if (found < 0)
		return -1;
	if (!found) {
		status_set_problem(problem, key, expected, "missing token");
		return -1;
	}
	if (parse_unsigned_decimal(value_start, limit, &parsed_end, value) < 0 ||
	    parsed_end != value_end) {
		status_set_problem(problem, key, expected,
				   "empty, noncanonical, signed or out-of-range value");
		return -1;
	}
	return 0;
}

static int parse_status_errno(const char *status, const char *key,
			      int optional, int *value,
			      struct status_problem *problem)
{
	const char *value_start;
	const char *value_end;
	const char *parsed_end;
	const char *expected =
		"one canonical signed errno (0 or -1..-4095)";
	unsigned long long magnitude;
	int found = status_find_value(status, key, expected, &value_start,
				      &value_end, problem);

	if (found < 0)
		return -1;
	if (!found) {
		if (optional)
			return 0;
		status_set_problem(problem, key, expected, "missing token");
		return -1;
	}
	if (*value_start == '-') {
		if (parse_unsigned_decimal(value_start + 1, 4095ULL,
					   &parsed_end, &magnitude) < 0 ||
		    parsed_end != value_end || magnitude == 0ULL)
			goto invalid;
		*value = -(int)magnitude;
	} else {
		if (parse_unsigned_decimal(value_start, 0ULL,
					   &parsed_end, &magnitude) < 0 ||
		    parsed_end != value_end)
			goto invalid;
		*value = 0;
	}
	return 1;

invalid:
	status_set_problem(problem, key, expected,
			   "empty, positive, noncanonical or out-of-range errno");
	return -1;
}

static int pages_to_bytes(unsigned long long pages,
			  unsigned long long *bytes)
{
	if (pages > ULLONG_MAX / SWAPZ_LOGICAL_PAGE_BYTES)
		return -1;
	*bytes = pages * SWAPZ_LOGICAL_PAGE_BYTES;
	return 0;
}

/*
 * Build ratios only from successfully committed target counters. Device Mapper
 * status is observational, so a live commit can cross the individual reads.
 * Return 1 for a bounded retry, 2 for a failed target, and -1 for malformed
 * status; 3 denotes a kernel INFO snapshot unavailable to the observer.
 * The caller also requires two identical relevant snapshots before
 * printing a ratio.
 */
static int parse_swapz_ratio_status_diagnostic(
	const char *status, struct swapz_ratio_status *ratio,
	struct status_problem *problem)
{
	unsigned long long total_pages;
	unsigned long long page_logical_bytes;
	unsigned long long raw_physical_bytes;
	int snapshot_error = 0;
	int snapshot_error_present;

	memset(ratio, 0, sizeof(*ratio));
	memset(problem, 0, sizeof(*problem));
	snapshot_error_present = parse_status_errno(
		status, "status_snapshot_error", 1, &snapshot_error, problem);
	if (snapshot_error_present < 0)
		return STATUS_BLOCKED;
	if (snapshot_error_present && !snapshot_error) {
		status_set_problem(problem, "status_snapshot_error",
				   "negative errno -1..-4095 when present",
				   "zero is not a kernel snapshot failure");
		return STATUS_BLOCKED;
	}
	if (snapshot_error) {
		status_set_problem(problem, "status_snapshot_error",
				   "absent when kernel INFO counters are available",
				   "kernel could not produce a status snapshot (negative errno)");
		problem->kernel_errno = snapshot_error;
		return STATUS_UNAVAILABLE;
	}
	if (parse_status_unsigned(status, "failed", 1ULL,
				  &ratio->failed, problem) < 0 ||
	    parse_status_errno(status, "error", 0, &ratio->error, problem) < 0)
		return STATUS_BLOCKED;
	if (ratio->failed) {
		/*
		 * The kernel publishes last_error before the terminal failed flag,
		 * but INFO field reads are observational and may straddle that
		 * publication. Retry failed=1/error=0 rather than emit FAILED
		 * without the terminal errno.
		 */
		if (!ratio->error) {
			status_set_problem(problem, "failed/error",
					   "failed=1 paired with kernel errno -1..-4095",
					   "failed flag observed before terminal errno");
			return STATUS_RETRY;
		}
		status_set_problem(problem, "failed", "0 for a healthy target",
				   "1: kernel target is failed");
		problem->kernel_errno = ratio->error;
		return STATUS_FAILED;
	}
	if (ratio->error) {
		status_set_problem(problem, "error",
				   "0 for a healthy target (-1..-4095 indicates errno)",
				   "negative kernel error");
		problem->kernel_errno = ratio->error;
		return STATUS_FAILED;
	}
	if (parse_status_unsigned(status, "logical_write", ULLONG_MAX,
				  &ratio->logical_write_bytes, problem) < 0 ||
	    parse_status_unsigned(status, "physical_write", ULLONG_MAX,
				  &ratio->physical_write_bytes, problem) < 0 ||
	    parse_status_unsigned(status, "gc_write", ULLONG_MAX,
				  &ratio->gc_write_bytes, problem) < 0 ||
	    parse_status_unsigned(status, "compressed", ULLONG_MAX,
				  &ratio->compressed_pages, problem) < 0 ||
	    parse_status_unsigned(status, "raw", ULLONG_MAX,
				  &ratio->raw_pages, problem) < 0 ||
	    parse_status_unsigned(status, "zero_elided", ULLONG_MAX,
				  &ratio->zero_elided_pages, problem) < 0 ||
	    parse_status_unsigned(status, "bulk_mode", 2ULL,
				  &ratio->bulk_mode, problem) < 0 ||
	    parse_status_unsigned(status, "bulk_padding", UINT_MAX,
				  &ratio->bulk_padding_blocks, problem) < 0)
		return STATUS_BLOCKED;

	if (ratio->compressed_pages > ULLONG_MAX - ratio->raw_pages ||
	    ratio->compressed_pages + ratio->raw_pages >
			ULLONG_MAX - ratio->zero_elided_pages) {
		status_set_problem(problem, "compressed+raw+zero_elided",
				   "sum of pages <= UINT64_MAX / 4096",
				   "64-bit page-count addition overflow");
		return STATUS_BLOCKED;
	}
	total_pages = ratio->compressed_pages + ratio->raw_pages +
		      ratio->zero_elided_pages;
	if (pages_to_bytes(total_pages, &page_logical_bytes) < 0) {
		status_set_problem(problem, "compressed+raw+zero_elided",
				   "sum of pages <= UINT64_MAX / 4096",
				   "page-to-byte multiplication overflow");
		return STATUS_BLOCKED;
	}
	if (pages_to_bytes(ratio->compressed_pages,
			   &ratio->compressed_logical_bytes) < 0 ||
	    pages_to_bytes(ratio->raw_pages, &raw_physical_bytes) < 0) {
		status_set_problem(problem, "compressed/raw",
				   "each page count <= UINT64_MAX / 4096",
				   "page-to-byte multiplication overflow");
		return STATUS_BLOCKED;
	}

	/* A mismatch is most likely one status read crossing a live commit. */
	if (page_logical_bytes != ratio->logical_write_bytes) {
		status_set_problem(problem, "logical_write",
				   "(compressed + raw + zero_elided) * 4096 bytes",
				   "does not equal committed foreground page counts");
		return STATUS_RETRY;
	}
	if (ratio->physical_write_bytes < ratio->gc_write_bytes) {
		status_set_problem(problem, "gc_write",
				   "<= physical_write (cumulative lower-WRITE bytes)",
				   "GC lower writes exceed total lower writes");
		return STATUS_RETRY;
	}
	ratio->overall_physical_bytes =
		ratio->physical_write_bytes - ratio->gc_write_bytes;
	if (ratio->overall_physical_bytes < raw_physical_bytes) {
		status_set_problem(problem, "physical_write-gc_write",
				   ">= raw * 4096 lower-WRITE bytes",
				   "foreground lower writes smaller than committed RAW bytes");
		return STATUS_RETRY;
	}
	ratio->compressed_extent_bytes =
		ratio->overall_physical_bytes - raw_physical_bytes;
	/*
	 * lower_bulk=0/1 never writes padding. A nonzero padding counter in
	 * either mode is malformed rather than evidence that may be folded into
	 * compressed bytes.
	 */
	if (ratio->bulk_mode <= 1ULL && ratio->bulk_padding_blocks) {
		status_set_problem(problem, "bulk_padding",
				   "0 when bulk_mode is 0 or 1",
				   "nonzero padding counter in a non-padding mode");
		return STATUS_BLOCKED;
	}
	/*
	 * With mode 2, a nonzero cumulative padding counter is not success- or
	 * foreground-partitioned. The foreground lower-WRITE total remains exact,
	 * but its bytes cannot be split between padding and compressed extents.
	 * Do not retain an inferred compressed denominator.
	 */
	ratio->compressed_extent_ratio_exact =
		ratio->bulk_padding_blocks == 0ULL;
	if (ratio->compressed_pages && !ratio->compressed_extent_bytes) {
		status_set_problem(problem, "physical_write-gc_write-raw*4096",
				   "> 0 when compressed > 0",
				   "no lower bytes remain for committed compressed pages");
		return STATUS_RETRY;
	}
	if (!ratio->compressed_extent_ratio_exact) {
		ratio->compressed_extent_bytes = 0;
		return STATUS_READY;
	}
	if (!ratio->compressed_pages && ratio->compressed_extent_bytes) {
		status_set_problem(problem, "physical_write-gc_write-raw*4096",
				   "0 when compressed=0 and bulk_padding=0",
				   "lower bytes remain without compressed pages or padding");
		return STATUS_RETRY;
	}
	return STATUS_READY;
}

static int ratio_status_equal(const struct swapz_ratio_status *left,
			      const struct swapz_ratio_status *right)
{
	return left->logical_write_bytes == right->logical_write_bytes &&
	       left->physical_write_bytes == right->physical_write_bytes &&
	       left->gc_write_bytes == right->gc_write_bytes &&
	       left->compressed_pages == right->compressed_pages &&
	       left->raw_pages == right->raw_pages &&
	       left->zero_elided_pages == right->zero_elided_pages &&
	       left->bulk_mode == right->bulk_mode &&
	       left->bulk_padding_blocks == right->bulk_padding_blocks &&
	       left->failed == right->failed &&
	       left->error == right->error;
}

static void format_bytes(unsigned long long bytes, char *text, size_t text_size)
{
	static const char *const units[] = {
		"B", "KiB", "MiB", "GiB", "TiB", "PiB"
	};
	long double value = (long double)bytes;
	size_t unit = 0;

	while (value >= 1024.0L &&
	       unit + 1U < sizeof(units) / sizeof(units[0])) {
		value /= 1024.0L;
		++unit;
	}
	if (unit == 0)
		snprintf(text, text_size, "%llu %s", bytes, units[unit]);
	else
		snprintf(text, text_size, "%.2Lf %s", value, units[unit]);
}

/* A 64-bit page count has at most 20 digits and six separators. */
static void format_page_count(unsigned long long count, char text[32])
{
	char digits[32];
	size_t length = (size_t)snprintf(digits, sizeof(digits), "%llu", count);
	size_t output_position = 0;
	size_t index;

	for (index = 0; index < length; ++index) {
		if (index && (length - index) % 3U == 0U)
			text[output_position++] = ',';
		text[output_position++] = digits[index];
	}
	text[output_position] = '\0';
}

static void print_ratio(const char *label, unsigned long long logical_bytes,
			unsigned long long physical_bytes)
{
	char logical_text[64];
	char lower_text[64];
	char ratio_text[64];

	format_bytes(logical_bytes, logical_text, sizeof(logical_text));
	format_bytes(physical_bytes, lower_text, sizeof(lower_text));
	if (!logical_bytes)
		(void)snprintf(ratio_text, sizeof(ratio_text), "n/a");
	else if (!physical_bytes)
		(void)snprintf(ratio_text, sizeof(ratio_text), "infinite");
	else
		(void)snprintf(ratio_text, sizeof(ratio_text), "%.2Lf:1",
			       (long double)logical_bytes / (long double)physical_bytes);
	printf("    %-20s %12s %12s %10s\n",
	       label, logical_text, lower_text, ratio_text);
}

/* No page share is meaningful before the first successful foreground WRITE. */
static void report_page_classification(const char *label,
				      unsigned long long pages,
				      unsigned long long total_pages)
{
	char page_text[32];

	format_page_count(pages, page_text);
	if (!total_pages) {
		printf("    %-20s %12s %9s\n", label, page_text, "n/a");
		return;
	}
	printf("    %-20s %12s %8.2Lf%%\n", label, page_text,
	       100.0L * (long double)pages / (long double)total_pages);
}


static void dm_initialize_ioctl(struct dm_ioctl *io, size_t buffer_size,
				const char *name)
{
	io->version[0] = DM_VERSION_MAJOR;
	io->version[1] = DM_VERSION_MINOR;
	io->version[2] = DM_VERSION_PATCHLEVEL;
	io->data_size = (uint32_t)buffer_size;
	io->data_start = sizeof(*io);
	if (name)
		memcpy(io->name, name, strlen(name) + 1U);
}

static uint32_t dm_query_input_flags(unsigned long request)
{
	/* Ask LIST_DEVICES for UUID metadata when the kernel supports it. */
	return request == DM_LIST_DEVICES ? DM_UUID_FLAG : 0U;
}

static int dm_query(int fd, unsigned long request, const char *name,
		    unsigned char **result, size_t *result_size)
{
	size_t buffer_size = SWAPZ_DM_BUFFER_INITIAL;

	if (request != DM_TABLE_STATUS && request != DM_LIST_DEVICES) {
		errno = EPERM;
		return -1;
	}
	if (name && strlen(name) >= DM_NAME_LEN) {
		errno = ENAMETOOLONG;
		return -1;
	}
	while (buffer_size <= SWAPZ_DM_BUFFER_MAX) {
		unsigned char *buffer = calloc(1, buffer_size);
		struct dm_ioctl *io;
		int saved_errno;

		if (!buffer)
			return -1;
		io = (struct dm_ioctl *)buffer;
		dm_initialize_ioctl(io, buffer_size, name);
		io->flags = dm_query_input_flags(request);
		if (ioctl(fd, request, io) < 0) {
			saved_errno = errno;
			free(buffer);
			errno = saved_errno;
			return -1;
		}
		if (io->flags & DM_BUFFER_FULL_FLAG) {
			free(buffer);
			if (buffer_size > SWAPZ_DM_BUFFER_MAX / 2U)
				break;
			buffer_size *= 2U;
			continue;
		}
		if (io->data_size > buffer_size || io->data_size < sizeof(*io) ||
		    io->data_start < sizeof(*io) || io->data_start > io->data_size) {
			free(buffer);
			errno = EPROTO;
			return -1;
		}
		*result = buffer;
		*result_size = buffer_size;
		return 0;
	}
	errno = EOVERFLOW;
	return -1;
}

/*
 * DM_TABLE_STATUS spec.next is an offset from the first target specification,
 * unlike the relative offsets in DM_LIST_DEVICES. Decode bounded replies
 * without trusting kernel-provided alignment, record counts or terminators.
 */
static int status_align_target_offset(size_t value, size_t *aligned)
{
	const size_t alignment = SWAPZ_DM_WIRE_ALIGNMENT;
	const size_t remainder = value % alignment;
	const size_t padding = remainder ? alignment - remainder : 0U;

	if (value > SIZE_MAX - padding)
		return -1;
	*aligned = value + padding;
	return 0;
}

static int status_parse_name_list_record(
	const unsigned char *record, size_t remaining,
	struct dm_list_record *parsed, struct status_problem *problem)
{
	const size_t name_offset = offsetof(struct dm_name_list, name);
	const char *name;
	const char *name_end;
	size_t metadata_offset;
	uint32_t flags;
	uint32_t next;

	memset(parsed, 0, sizeof(*parsed));
	memset(problem, 0, sizeof(*problem));
	if (remaining < name_offset + 1U) {
		status_set_problem(problem, "dm_name_list",
				   "complete record header and NUL-terminated name",
				   "truncated Device Mapper device-list record");
		return -1;
	}
	memcpy(&parsed->device_id, record + offsetof(struct dm_name_list, dev),
	       sizeof(parsed->device_id));
	memcpy(&next, record + offsetof(struct dm_name_list, next), sizeof(next));
	if (next && (next % SWAPZ_DM_WIRE_ALIGNMENT ||
		     next < name_offset + 1U || (size_t)next > remaining)) {
		status_set_problem(problem, "dm_name_list.next",
				   "8-byte-aligned forward record offset within data_size",
				   "unaligned, overlapping or truncated next record");
		return -1;
	}
	parsed->record_size = next ? (size_t)next : remaining;
	if (parsed->record_size % SWAPZ_DM_WIRE_ALIGNMENT) {
		status_set_problem(problem, "dm_name_list.next",
				   "8-byte-aligned record end",
				   "terminal Device Mapper record is not wire-aligned");
		return -1;
	}
	name = (const char *)record + name_offset;
	name_end = memchr(name, '\0', parsed->record_size - name_offset);
	if (!name_end || name == name_end ||
	    (size_t)(name_end - name) >= DM_NAME_LEN) {
		status_set_problem(problem, "dm_name_list.name",
				   "bounded nonempty NUL-terminated mapping name",
				   "empty, unterminated or too-long mapping name");
		return -1;
	}
	metadata_offset = (size_t)(name_end - (const char *)record) + 1U;
	if (status_align_target_offset(metadata_offset, &metadata_offset) < 0 ||
	    metadata_offset > parsed->record_size ||
	    parsed->record_size - metadata_offset < 2U * sizeof(uint32_t)) {
		status_set_problem(problem, "dm_name_list.event_nr/flags",
				   "8-byte-aligned event number and flags inside record",
				   "truncated post-name Device Mapper metadata");
		return -1;
	}
	memcpy(&parsed->event_number, record + metadata_offset,
	       sizeof(parsed->event_number));
	memcpy(&flags, record + metadata_offset + sizeof(parsed->event_number),
	       sizeof(flags));
	parsed->flags = flags;
	if (flags & DM_NAME_LIST_FLAG_HAS_UUID) {
		const size_t uuid_offset = metadata_offset + 2U * sizeof(uint32_t);
		size_t uuid_bytes = parsed->record_size - uuid_offset;

		if (uuid_bytes > DM_UUID_LEN)
			uuid_bytes = DM_UUID_LEN;
		if (!uuid_bytes || !memchr(record + uuid_offset, '\0', uuid_bytes)) {
			status_set_problem(problem, "dm_name_list.uuid",
					   "bounded NUL-terminated mapping UUID when flagged",
					   "truncated or unterminated device-list UUID");
			return -1;
		}
		parsed->uuid = (const char *)record + uuid_offset;
	}
	if (!parsed->device_id) {
		status_set_problem(problem, "dm_name_list.dev",
				   "nonzero LIST_DEVICES identity",
				   "zero device number");
		return -1;
	}
	parsed->name = name;
	return 0;
}


/* Every LIST reply is an independent, bounded observation, not an atomic snapshot. */
static int status_parse_list_header(const unsigned char *buffer, size_t buffer_size,
				    struct dm_ioctl *header,
				    struct status_problem *problem)
{
	if (!buffer || buffer_size < sizeof(*header)) {
		status_set_problem(problem, "dm_ioctl.data_size",
				   "complete DM_LIST_DEVICES header",
				   "truncated device-list header");
		return -1;
	}
	memcpy(header, buffer, sizeof(*header));
	if (header->data_size > buffer_size ||
	    header->data_size < sizeof(*header) ||
	    header->data_start < sizeof(*header) ||
	    header->data_start > header->data_size ||
	    header->data_start % SWAPZ_DM_WIRE_ALIGNMENT) {
		status_set_problem(problem, "dm_ioctl.data_start/data_size",
				   "bounded 8-byte-aligned device-list payload",
				   "invalid Device Mapper device-list bounds or alignment");
		return -1;
	}
	return 0;
}

/*
 * Re-read every identity after staging all INFO observations. An unrelated
 * mapping can change while previously listed mappings and counters stay
 * unchanged. This detects observed drift but cannot make ioctls atomic.
 */
static int status_list_inventories_equal(
	const unsigned char *first_buffer, const struct dm_ioctl *first_header,
	const unsigned char *second_buffer, size_t second_buffer_size,
	struct status_problem *problem)
{
	struct dm_ioctl second_header;
	size_t first_offset = first_header->data_start;
	size_t second_offset;
	int result;

	if (status_parse_list_header(second_buffer, second_buffer_size,
				     &second_header, problem) < 0)
		return -1;
	second_offset = second_header.data_start;
	while (first_offset < first_header->data_size &&
	       second_offset < second_header.data_size) {
		struct dm_list_record first;
		struct dm_list_record second;

		if (status_parse_name_list_record(
			    first_buffer + first_offset, first_header->data_size - first_offset,
			    &first, problem) < 0 ||
		    status_parse_name_list_record(
			    second_buffer + second_offset, second_header.data_size - second_offset,
			    &second, problem) < 0)
			return -1;
		if (strcmp(first.name, second.name) ||
		    first.device_id != second.device_id ||
		    first.event_number != second.event_number ||
		    first.flags != second.flags ||
		    (first.uuid != NULL) != (second.uuid != NULL) ||
		    (first.uuid && strcmp(first.uuid, second.uuid)))
			goto changed;
		first_offset += first.record_size;
		second_offset += second.record_size;
	}
	result = first_offset == first_header->data_size &&
		 second_offset == second_header.data_size;
	if (result)
		return 1;
changed:
	status_set_problem(problem, "DM_LIST_DEVICES inventory",
			   "identical ordered names, UUIDs, device numbers, flags and events",
			   "mapping inventory changed between enumerations");
	return 0;
}

static int status_report_list_problem(const char *state,
				      const struct status_problem *problem)
{
	fprintf(stderr, "swapzctl status: %s: DM_LIST_DEVICES field '%s'; expected %s; observed %s\n",
		state, problem->field, problem->expected, problem->observed);
	errno = !strcmp(state, "UNAVAILABLE") ? EAGAIN : EPROTO;
	return 1;
}

static int status_report_list_ioctl_failure(const char *phase, int error_number)
{
	if (error_number == EPROTO || error_number == EOVERFLOW) {
		fprintf(stderr,
			"swapzctl status: %s: %s DM_LIST_DEVICES reply; errno=%d (%s)\n",
			error_number == EPROTO ? "BLOCKED" : "UNAVAILABLE",
			phase, error_number, strerror(error_number));
	} else {
		fprintf(stderr,
			"swapzctl status: UNAVAILABLE: %s DM_LIST_DEVICES errno=%d (%s)%s\n",
			phase, error_number, strerror(error_number),
			(error_number == EPERM || error_number == EACCES) ?
			"; observational ioctl requires CAP_SYS_ADMIN; no escalation attempted" : "");
	}
	errno = error_number;
	return 1;
}

static void status_free_observation(struct dm_status_observation *observation)
{
	free(observation->reply);
	free(observation->targets);
	memset(observation, 0, sizeof(*observation));
}

/*
 * Parse the entire DM_TABLE_STATUS reply once. INFO strings remain owned by
 * the reply buffer until the complete pair of observations is compared.
 * Every spec is copied before access: neither kernel offsets nor host ABI
 * alignment can turn a wire record into a dereferenced C structure.
 */
static int parse_dm_status_observation(
	const unsigned char *buffer, size_t buffer_size, const char *expected_name,
	uint64_t expected_device, struct dm_status_observation *observation,
	struct status_problem *problem, unsigned int *problem_target)
{
	struct dm_ioctl header;
	const unsigned char *record_base;
	size_t payload_size;
	size_t terminal_next = 0;
	size_t current_offset = 0;
	uint32_t target;

	*problem_target = UINT_MAX;
	memset(problem, 0, sizeof(*problem));
	if (buffer_size < sizeof(header)) {
		status_set_problem(problem, "dm_ioctl.data_size",
				   "complete DM ioctl header", "truncated DM ioctl header");
		return -1;
	}
	memcpy(&header, buffer, sizeof(header));
	if (header.data_size > buffer_size ||
	    header.data_size < sizeof(header) ||
	    header.data_start < sizeof(header) ||
	    header.data_start > header.data_size ||
	    header.data_start % SWAPZ_DM_WIRE_ALIGNMENT) {
		status_set_problem(problem, "dm_ioctl.data_start/data_size",
				   "8-byte-aligned start and bounded INFO payload",
				   "out-of-bounds or misaligned DM INFO payload");
		return -1;
	}
	payload_size = (size_t)header.data_size - header.data_start;
	if (header.target_count > SWAPZ_STATUS_MAX_TARGETS ||
	    (header.target_count &&
	     (payload_size < sizeof(struct dm_target_spec) + 1U ||
	      header.target_count > payload_size /
		      (sizeof(struct dm_target_spec) + 1U) ||
	      status_align_target_offset(payload_size, &terminal_next) < 0 ||
	      terminal_next > UINT32_MAX))) {
		status_set_problem(problem, "dm_target_spec.next",
				   "bounded target count and representable 8-byte terminal offset",
				   "impossible count or terminal offset overflow");
		return -1;
	}
	/*
	 * With no live table, DM_TABLE_STATUS leaves data_size at the caller's
	 * request capacity. target_count=0 is authoritative: those bytes are
	 * request-buffer slack, not target records to infer or validate.
	 */
	if (!memchr(header.name, '\0', sizeof(header.name)) ||
	    strcmp(header.name, expected_name)) {
		status_set_problem(problem, "dm_ioctl.name",
				   "NUL-terminated queried mapping name",
				   "missing terminator or changed mapping identity");
		return -1;
	}
	if (!header.dev || header.dev != expected_device) {
		status_set_problem(problem, "dm_ioctl.dev",
				   "same nonzero device number as LIST_DEVICES",
				   "device number changed or is zero (mapping name reused)");
		return -1;
	}
	if (header.flags & DM_STATUS_TABLE_FLAG) {
		status_set_problem(problem, "dm_ioctl.flags",
				   "INFO status rather than table parameters",
				   "DM_STATUS_TABLE_FLAG set");
		return -1;
	}
	if (header.target_count) {
		observation->targets = calloc(header.target_count,
					      sizeof(*observation->targets));
		if (!observation->targets) {
			status_set_problem(problem, "DM target inventory",
					   "bounded snapshot allocation",
					   "allocation failed");
			errno = ENOMEM;
			problem->failure_errno = errno;
			return -1;
		}
	}
	observation->device_id = header.dev;
	observation->event_number = header.event_nr;
	observation->target_count = header.target_count;
	observation->flags = header.flags;
	record_base = buffer + header.data_start;
	for (target = 0; target < header.target_count; ++target) {
		struct dm_target_spec specification;
		struct swapz_target_snapshot *entry = &observation->targets[target];
		const unsigned char *parameters;
		const unsigned char *record_end;
		const unsigned char *terminator;
		size_t record_end_offset;
		size_t type_length;
		const int final_target = target + 1U == header.target_count;

		*problem_target = target;
		if (current_offset > payload_size ||
		    payload_size - current_offset < sizeof(specification) + 1U) {
			status_set_problem(problem, "dm_target_spec",
					   "complete target header and status terminator",
					   "truncated or overlapping target record");
			return -1;
		}
		memcpy(&specification, record_base + current_offset,
		       sizeof(specification));
		if (final_target) {
			/*
			 * The final next offset is aligned beyond the last
			 * status NUL; data_size need not include that padding.
			 */
			if ((size_t)specification.next != terminal_next) {
				status_set_problem(problem, "dm_target_spec.next",
						   "8-byte-aligned terminal INFO payload offset",
						   "incorrect final target offset");
				return -1;
			}
			record_end_offset = payload_size;
		} else {
			if (!specification.next ||
			    specification.next % SWAPZ_DM_WIRE_ALIGNMENT ||
			    (size_t)specification.next <= current_offset ||
			    (size_t)specification.next - current_offset <
				    sizeof(specification) + 1U ||
			    (size_t)specification.next > payload_size ||
			    payload_size - (size_t)specification.next <
				    sizeof(specification) + 1U) {
				status_set_problem(problem, "dm_target_spec.next",
						   "8-byte-aligned forward absolute offset with next record",
						   "zero, misaligned, overlapping or truncated offset");
				return -1;
			}
			record_end_offset = specification.next;
		}
		type_length = strnlen(specification.target_type,
				      sizeof(specification.target_type));
		if (type_length == sizeof(specification.target_type)) {
			status_set_problem(problem, "dm_target_spec.target_type",
					   "NUL-terminated target type",
					   "unterminated target identity");
			return -1;
		}
		if (!specification.length ||
		    specification.sector_start > UINT64_MAX - specification.length) {
			status_set_problem(problem, "dm_target_spec.sector_start/length",
					   "nonzero length and nonoverflowing sector end",
					   "invalid target geometry");
			return -1;
		}
		parameters = record_base + current_offset + sizeof(specification);
		record_end = record_base + record_end_offset;
		terminator = memchr(parameters, '\0',
				   (size_t)(record_end - parameters));
		if (!terminator) {
			status_set_problem(problem, "dm_target_spec.params",
					   "status NUL contained within target record",
					   "missing terminator or truncated INFO reply");
			return -1;
		}
		if (final_target) {
			if (terminator + 1 != record_end) {
				status_set_problem(problem, "dm_target_spec.params",
						   "final status NUL exactly at data_size",
						   "bytes follow the final status terminator");
				return -1;
			}
		} else {
			size_t expected_next =
				(size_t)(terminator + 1 - record_base);

			if (status_align_target_offset(expected_next,
						       &expected_next) < 0 ||
			    expected_next != (size_t)specification.next) {
				status_set_problem(problem, "dm_target_spec.next",
						   "exact 8-byte alignment after status NUL",
						   "record offset skips or overlaps wire bytes");
				return -1;
			}
		}
		entry->sector_start = specification.sector_start;
		entry->length = specification.length;
		entry->device_id = header.dev;
		entry->event_number = header.event_nr;
		entry->target_status = specification.status;
		memcpy(entry->target_type, specification.target_type,
		       sizeof(entry->target_type));
		entry->status_text = (const char *)parameters;
		entry->status_length = (size_t)(terminator - parameters);
		entry->is_swapz = !strcmp(entry->target_type, "swapz");
		if (specification.status > 0 || specification.status < -4095) {
			status_set_problem(problem, "dm_target_spec.status",
					   "0 or kernel errno -1..-4095",
					   "invalid DM target status");
			entry->ratio_state = STATUS_BLOCKED;
		} else if (specification.status < 0) {
			status_set_problem(problem, "dm_target_spec.status",
					   "0 for healthy target",
					   "negative errno: Device Mapper reports target failure");
			problem->kernel_errno = specification.status;
			entry->ratio_state = STATUS_FAILED;
		} else if (entry->is_swapz) {
			entry->ratio_state = parse_swapz_ratio_status_diagnostic(
				entry->status_text, &entry->ratio, problem);
		} else {
			entry->ratio_state = STATUS_READY;
		}
		if (entry->ratio_state == STATUS_BLOCKED ||
		    entry->ratio_state == STATUS_FAILED ||
		    entry->ratio_state == STATUS_UNAVAILABLE)
			return -2;
		if (entry->ratio_state == STATUS_RETRY)
			entry->problem = *problem;
		current_offset = record_end_offset;
	}
	return 0;
}

static int read_dm_status_observation(
	int fd, const char *name, uint64_t expected_device,
	struct dm_status_observation *observation,
	struct status_problem *problem, unsigned int *problem_target)
{
	unsigned char *buffer = NULL;
	size_t buffer_size = 0;
	int parse_result;

	memset(observation, 0, sizeof(*observation));
	memset(problem, 0, sizeof(*problem));
	*problem_target = UINT_MAX;
	if (dm_query(fd, DM_TABLE_STATUS, name, &buffer, &buffer_size) < 0) {
		if (errno == EPROTO)
			status_set_problem(problem, "dm_ioctl.data_start/data_size",
					   "bounded DM INFO header", "invalid reply header");
		else if (errno == EOVERFLOW)
			status_set_problem(problem, "DM_BUFFER_FULL_FLAG",
					   "complete INFO reply within 1048576 bytes",
					   "reply remained buffer-full");
		problem->failure_errno = errno;
		return -1;
	}
	observation->reply = buffer;
	parse_result = parse_dm_status_observation(buffer, buffer_size, name,
						 expected_device, observation,
						 problem, problem_target);
	return parse_result;
}

static void status_safe_mapping_name(const char *name,
				     char safe_name[DM_NAME_LEN + 1U])
{
	size_t index;
	size_t length = strnlen(name, DM_NAME_LEN);

	/* Escape path punctuation and control bytes rather than echoing paths. */
	if (!length || length >= DM_NAME_LEN) {
		memcpy(safe_name, "<unverified>", sizeof("<unverified>"));
		return;
	}
	if (memchr(name, '/', length) || memchr(name, '\\', length)) {
		memcpy(safe_name, "<redacted>", sizeof("<redacted>"));
		return;
	}
	for (index = 0; index < length; ++index) {
		char character = name[index];

		safe_name[index] =
			(character >= 'a' && character <= 'z') ||
			(character >= 'A' && character <= 'Z') ||
			(character >= '0' && character <= '9') ||
			character == '_' || character == '-' ||
			character == '.' || character == '+' ?
			character : '_';
	}
	safe_name[length] = '\0';
}

static void report_swapz_target(const char *name, unsigned int target_index,
				const struct swapz_ratio_status *ratio)
{
	char gc_text[64];
	char lower_write_delta_text[64];
	char compressed_logical_text[64];
	char safe_name[DM_NAME_LEN + 1U];
	unsigned long long total_pages;
	unsigned long long lower_write_delta;
	const char *lower_write_delta_label;

	status_safe_mapping_name(name, safe_name);
	printf("swapz target: %s", safe_name);
	if (target_index)
		printf(" (target %u)", target_index + 1U);
	putchar('\n');
	if (ratio->failed) {
		puts("  Health: FAILED");
		puts("  Compression ratios unavailable; lower WRITEs may not be published.");
		return;
	}

	puts("  Health: OK (failed=0, error=0)");
	puts("");
	puts("  WRITE EFFICIENCY (cumulative foreground)");
	printf("    %-20s %12s %12s %10s\n",
	       "Category", "Logical", "Lower", "Ratio");
	print_ratio("Overall", ratio->logical_write_bytes,
		    ratio->overall_physical_bytes);
	if (!ratio->compressed_pages) {
		print_ratio("SWZ extents", 0, 0);
	} else if (ratio->compressed_extent_ratio_exact) {
		print_ratio("SWZ extents", ratio->compressed_logical_bytes,
			    ratio->compressed_extent_bytes);
	} else {
		format_bytes(ratio->compressed_logical_bytes, compressed_logical_text,
			     sizeof(compressed_logical_text));
		printf("    %-20s %12s %12s %10s\n", "SWZ extents",
		       compressed_logical_text, "n/a", "unavailable");
		puts("    Note: nonzero staged padding ('bulk_padding') prevents an exact");
		puts("          compressed lower-byte split between foreground and GC.");
	}
	if (ratio->logical_write_bytes) {
		if (ratio->logical_write_bytes >= ratio->overall_physical_bytes) {
			lower_write_delta = ratio->logical_write_bytes -
					    ratio->overall_physical_bytes;
			lower_write_delta_label = "Net WRITE reduction";
		} else {
			lower_write_delta = ratio->overall_physical_bytes -
					    ratio->logical_write_bytes;
			lower_write_delta_label = "Net WRITE overhead";
		}
		format_bytes(lower_write_delta, lower_write_delta_text,
			     sizeof(lower_write_delta_text));
		printf("    %-20s %12s  (%.2Lf%% of logical)\n",
		       lower_write_delta_label, lower_write_delta_text,
		       100.0L * (long double)lower_write_delta /
		       (long double)ratio->logical_write_bytes);
	}

	/* These committed page counts were range-checked by the status parser. */
	total_pages = ratio->compressed_pages + ratio->raw_pages +
		      ratio->zero_elided_pages;
	puts("");
	puts("  PAGE CLASSIFICATION (4 KiB each)");
	printf("    %-20s %12s %9s\n", "Category", "Pages", "Share");
	report_page_classification("Compressed", ratio->compressed_pages,
				   total_pages);
	report_page_classification("RAW", ratio->raw_pages, total_pages);
	report_page_classification("Zero-elided", ratio->zero_elided_pages,
				   total_pages);

	format_bytes(ratio->gc_write_bytes, gc_text, sizeof(gc_text));
	printf("\n  GC lower WRITEs: %s (excluded from ratios)\n", gc_text);
	puts("  Note: counters are cumulative since target creation; not current swap usage.");
	putchar('\n');
}


/* Do not include untrusted INFO text, device paths or unverified counters. */
static int status_report_problem(const char *state, const char *name,
				 uint64_t device_id, unsigned int target_index,
				 unsigned int generation,
				 const struct status_problem *problem)
{
	char safe_name[DM_NAME_LEN + 1U];

	status_safe_mapping_name(name, safe_name);
	if (target_index == UINT_MAX)
		fprintf(stderr,
			"swapzctl status: %s: mapping '%s' device %u:%u snapshot %u: field '%s'; expected %s; observed %s",
			state, safe_name, major((dev_t)device_id),
			minor((dev_t)device_id), generation, problem->field,
			problem->expected, problem->observed);
	else
		fprintf(stderr,
			"swapzctl status: %s: mapping '%s' device %u:%u target %u snapshot %u: field '%s'; expected %s; observed %s",
			state, safe_name, major((dev_t)device_id),
			minor((dev_t)device_id), target_index + 1U, generation,
			problem->field, problem->expected, problem->observed);
	if (problem->kernel_errno)
		fprintf(stderr, "; kernel errno=%d", problem->kernel_errno);
	if (problem->failure_errno)
		fprintf(stderr, "; errno=%d (%s)", problem->failure_errno,
			strerror(problem->failure_errno));
	fputc('\n', stderr);
	errno = problem->failure_errno ? problem->failure_errno : EPROTO;
	return -2;
}

static int status_report_ioctl_failure(const char *name, uint64_t device_id,
				       unsigned int generation, int error_number)
{
	char safe_name[DM_NAME_LEN + 1U];

	status_safe_mapping_name(name, safe_name);
	fprintf(stderr,
		"swapzctl status: UNAVAILABLE: mapping '%s' device %u:%u snapshot %u: DM_TABLE_STATUS errno=%d (%s)%s\n",
		safe_name, major((dev_t)device_id), minor((dev_t)device_id),
		generation, error_number, strerror(error_number),
		(error_number == EACCES || error_number == EPERM) ?
			"; observational DM ioctl needs CAP_SYS_ADMIN; no escalation attempted" : "");
	errno = error_number;
	return -2;
}

static int status_observations_equal(
	const struct dm_status_observation *first,
	const struct dm_status_observation *second,
	struct status_problem *problem, unsigned int *problem_target)
{
	uint32_t target;

	*problem_target = UINT_MAX;
	if (first->device_id != second->device_id) {
		status_set_problem(problem, "dm_ioctl.dev",
				   "identical device numbers in snapshots 1 and 2",
				   "device identity changed");
		return 0;
	}
	if (first->flags != second->flags) {
		status_set_problem(problem, "dm_ioctl.flags",
				   "identical DM flags in snapshots 1 and 2",
				   "DM flags changed");
		return 0;
	}
	if (first->event_number != second->event_number) {
		status_set_problem(problem, "dm_ioctl.event_nr",
				   "identical event generations in snapshots 1 and 2",
				   "event generation changed");
		return 0;
	}
	if (first->target_count != second->target_count) {
		status_set_problem(problem, "dm_ioctl.target_count",
				   "identical target count and order in snapshots 1 and 2",
				   "target count changed");
		return 0;
	}
	for (target = 0; target < first->target_count; ++target) {
		const struct swapz_target_snapshot *left = &first->targets[target];
		const struct swapz_target_snapshot *right = &second->targets[target];

		*problem_target = target;
		if (strcmp(left->target_type, right->target_type)) {
			status_set_problem(problem, "dm_target_spec.target_type",
					   "identical ordered target types",
					   "target inventory changed");
			return 0;
		}
		if (left->sector_start != right->sector_start ||
		    left->length != right->length) {
			status_set_problem(problem, "dm_target_spec.sector_start/length",
					   "identical target geometry across snapshots",
					   "target geometry changed");
			return 0;
		}
		if (left->target_status != right->target_status) {
			status_set_problem(problem, "dm_target_spec.status",
					   "identical target status across snapshots",
					   "target status changed");
			return 0;
		}
		if (left->status_length != right->status_length ||
		    memcmp(left->status_text, right->status_text,
			   left->status_length)) {
			status_set_problem(problem, "dm_target_spec.params",
					   "identical complete INFO status across snapshots",
					   "target status text or counters changed");
			return 0;
		}
		if (left->is_swapz && !ratio_status_equal(&left->ratio, &right->ratio)) {
			status_set_problem(problem, "swapz counters",
					   "identical committed counters across snapshots",
					   "relevant counter changed");
			return 0;
		}
	}
	return 1;
}

static int status_append_ready_target(
	struct status_ready_report *report, const char *name,
	unsigned int target_index, const struct swapz_target_snapshot *source)
{
	struct status_ready_target *grown;
	size_t capacity;

	if (report->count == SWAPZ_STATUS_MAX_RESULTS) {
		errno = EOVERFLOW;
		return -1;
	}
	if (report->count == report->capacity) {
		capacity = report->capacity ? report->capacity * 2U : 8U;
		if (capacity > SWAPZ_STATUS_MAX_RESULTS)
			capacity = SWAPZ_STATUS_MAX_RESULTS;
		grown = realloc(report->targets, capacity * sizeof(*grown));
		if (!grown)
			return -1;
		report->targets = grown;
		report->capacity = capacity;
	}
	memcpy(report->targets[report->count].name, name, strlen(name) + 1U);
	report->targets[report->count].target_index = target_index;
	report->targets[report->count].device_id = source->device_id;
	report->targets[report->count].sector_start = source->sector_start;
	report->targets[report->count].sector_length = source->length;
	report->targets[report->count].ratio = source->ratio;
	++report->count;
	return 0;
}

typedef int (*status_observation_reader)(
	void *context, const char *name, uint64_t expected_device,
	struct dm_status_observation *observation,
	struct status_problem *problem, unsigned int *problem_target);

struct status_fd_reader_context {
	int fd;
	uint32_t list_event_number;
};

static int status_validate_list_generation(
	const struct dm_status_observation *observation,
	uint32_t list_event_number, struct status_problem *problem,
	unsigned int *problem_target)
{
	if (!observation->device_id ||
	    observation->event_number == list_event_number)
		return 0;
	*problem_target = UINT_MAX;
	status_set_problem(problem, "dm_ioctl.event_nr",
			   "same event generation as DM_LIST_DEVICES",
			   "mapping generation changed after device enumeration");
	/* Preserve the transient generation-drift errno through diagnostics. */
	problem->failure_errno = EAGAIN;
	errno = EAGAIN;
	return -1;
}

static int status_bind_list_generation(
	int read_result, const struct dm_status_observation *observation,
	uint32_t list_event_number, struct status_problem *problem,
	unsigned int *problem_target)
{
	/* A failed read has no valid generation to bind; preserve its diagnosis. */
	if (read_result < 0)
		return read_result;
	if (status_validate_list_generation(observation, list_event_number,
					    problem, problem_target) < 0)
		return -1;
	return read_result;
}

static int status_read_observation_with_fd(
	void *context, const char *name, uint64_t expected_device,
	struct dm_status_observation *observation,
	struct status_problem *problem, unsigned int *problem_target)
{
	const struct status_fd_reader_context *reader = context;
	int result = read_dm_status_observation(reader->fd, name, expected_device,
						 observation, problem,
						 problem_target);

	return status_bind_list_generation(result, observation,
					   reader->list_event_number,
					   problem, problem_target);
}

static int report_device_status_with_reader(
	void *context, status_observation_reader read_observation,
	const char *name, uint64_t expected_device,
	struct status_ready_report *report)
{
	struct status_problem last_problem = {
		.field = "complete consecutive DM INFO snapshots",
		.expected = "two identical full target inventories within 8 retries",
		.observed = "inventory, identity or counters changed between generations 1 and 2"
	};
	unsigned int last_target = UINT_MAX;
	unsigned int attempt;

	for (attempt = 0; attempt < SWAPZ_STATUS_SNAPSHOT_RETRIES; ++attempt) {
		struct dm_status_observation first = { 0 };
		struct dm_status_observation second = { 0 };
		struct status_problem problem = { 0 };
		unsigned int problem_target = 0;
		unsigned int target;
		int result;

		result = read_observation(context, name, expected_device, &first,
					  &problem, &problem_target);
		if (result < 0) {
			int saved_errno = errno;
			int target_state = result == -2 ?
				first.targets[problem_target].ratio_state : STATUS_BLOCKED;

			status_free_observation(&first);
			if (problem.field)
				return status_report_problem(
					target_state == STATUS_FAILED ? "FAILED" :
					target_state == STATUS_UNAVAILABLE ||
					saved_errno == EOVERFLOW || saved_errno == ENOMEM ||
					saved_errno == EAGAIN ?
					"UNAVAILABLE" : "BLOCKED",
					name, expected_device, problem_target, 1, &problem);
			return status_report_ioctl_failure(name, expected_device,
							   1, saved_errno);
		}
		/* A second-read ioctl error must not inherit first-read diagnostics. */
		memset(&problem, 0, sizeof(problem));
		problem_target = 0;
		result = read_observation(context, name, expected_device, &second,
					  &problem, &problem_target);
		if (result < 0) {
			int saved_errno = errno;
			int target_state = result == -2 ?
				second.targets[problem_target].ratio_state : STATUS_BLOCKED;

			status_free_observation(&first);
			status_free_observation(&second);
			if (problem.field)
				return status_report_problem(
					target_state == STATUS_FAILED ? "FAILED" :
					target_state == STATUS_UNAVAILABLE ||
					saved_errno == EOVERFLOW || saved_errno == ENOMEM ||
					saved_errno == EAGAIN ?
					"UNAVAILABLE" : "BLOCKED",
					name, expected_device, problem_target, 2, &problem);
			return status_report_ioctl_failure(name, expected_device,
							   2, saved_errno);
		}
		if (!status_observations_equal(&first, &second,
					       &problem, &problem_target)) {
			last_problem = problem;
			last_target = problem_target;
			goto retry;
		}
		for (target = 0; target < first.target_count; ++target) {
			const struct swapz_target_snapshot *entry = &first.targets[target];

			if (entry->ratio_state == STATUS_RETRY) {
				last_problem = entry->problem;
				last_target = target;
				goto retry;
			}
		}
		for (target = 0; target < first.target_count; ++target) {
			const struct swapz_target_snapshot *entry = &first.targets[target];

			if (entry->is_swapz &&
			    status_append_ready_target(report, name, target, entry) < 0) {
				struct status_problem allocation_problem = {
					.field = "validated status results",
					.expected = "bounded output inventory allocation",
					.observed = "allocation failed or result limit exceeded",
					.failure_errno = errno
				};

				status_free_observation(&first);
				status_free_observation(&second);
				return status_report_problem("UNAVAILABLE", name, expected_device,
							     target, 2, &allocation_problem);
			}
		}
		status_free_observation(&first);
		status_free_observation(&second);
		return 0;
retry:
		status_free_observation(&first);
		status_free_observation(&second);
	}
	return status_report_problem("UNAVAILABLE", name, expected_device,
				     last_target, 2, &last_problem);
}

static int report_device_status(int fd, const char *name, uint64_t expected_device,
				uint32_t list_event_number,
				struct status_ready_report *report)
{
	struct status_fd_reader_context reader = {
		.fd = fd,
		.list_event_number = list_event_number
	};

	return report_device_status_with_reader(&reader,
						status_read_observation_with_fd,
						name, expected_device, report);
}

typedef int (*status_list_reader)(void *context, unsigned char **reply,
				  size_t *reply_size);
typedef int (*status_device_reader)(void *context, const char *name,
				    uint64_t device_id, uint32_t event_number,
				    struct status_ready_report *report);

static int status_read_list_with_fd(void *context, unsigned char **reply,
				    size_t *reply_size)
{
	return dm_query(*(const int *)context, DM_LIST_DEVICES, NULL,
			 reply, reply_size);
}

static int status_read_device_with_fd(void *context, const char *name,
				      uint64_t device_id, uint32_t event_number,
				      struct status_ready_report *report)
{
	return report_device_status(*(const int *)context, name, device_id,
				    event_number, report);
}

/* Stage complete results before comparing a fresh, read-only device inventory. */
static int status_collect_targets_with_readers(
	void *context, status_list_reader read_list, status_device_reader read_device,
	struct status_ready_report *report)
{
	unsigned char *first_buffer = NULL;
	unsigned char *second_buffer = NULL;
	size_t first_buffer_size = 0;
	size_t second_buffer_size = 0;
	struct dm_ioctl first_header;
	struct status_problem problem = { 0 };
	size_t current_offset;
	int comparison;
	int result = 1;

	if (read_list(context, &first_buffer, &first_buffer_size) < 0) {
		result = status_report_list_ioctl_failure("initial", errno);
		goto out;
	}
	if (status_parse_list_header(first_buffer, first_buffer_size,
				     &first_header, &problem) < 0) {
		result = status_report_list_problem("BLOCKED", &problem);
		goto out;
	}
	current_offset = first_header.data_start;
	while (current_offset < first_header.data_size) {
		struct dm_list_record record;
		const size_t remaining = first_header.data_size - current_offset;

		if (status_parse_name_list_record(first_buffer + current_offset,
						  remaining, &record, &problem) < 0) {
			result = status_report_list_problem("BLOCKED", &problem);
			goto out;
		}
		if (read_device(context, record.name, record.device_id,
				record.event_number, report) < 0)
			goto out;
		current_offset += record.record_size;
	}
	if (read_list(context, &second_buffer, &second_buffer_size) < 0) {
		result = status_report_list_ioctl_failure("final", errno);
		goto out;
	}
	comparison = status_list_inventories_equal(first_buffer, &first_header,
						  second_buffer, second_buffer_size, &problem);
	if (comparison <= 0) {
		result = status_report_list_problem(
			comparison < 0 ? "BLOCKED" : "UNAVAILABLE", &problem);
		goto out;
	}
	result = 0;
out:
	free(first_buffer);
	free(second_buffer);
	return result;
}



/*
 * /proc/swaps is an advisory Linux inventory, not a lifecycle token.
 * Kernel names are re-resolved in our mount namespace for display only.
 * An unmatched/overmounted name is never proof that the original swap
 * object was drained. Mutating paths must use swapz-primary's pinned proof.
 */
struct swapz_linux_swap {
	const char *state;
	unsigned long long size_bytes;
	unsigned long long used_bytes;
	long priority;
	int has_usage;
};

static int swapz_parse_swap_kib(const char *token, unsigned long long *bytes)
{
	const char *end;
	unsigned long long kib;

	if (parse_unsigned_decimal(token, ULLONG_MAX / 1024ULL, &end, &kib) < 0 ||
	    *end != '\0')
		return -1;
	*bytes = kib * 1024ULL;
	return 0;
}

static int swapz_read_linux_swap(FILE *inventory,
				  const struct status_ready_report *report,
				  struct swapz_linux_swap *observations)
{
	char line[4096];
	size_t line_count = 0;
	size_t index;

	if (!fgets(line, sizeof(line), inventory) ||
	    !strchr(line, '\n') || strncmp(line, "Filename", 8))
		return -1;
	while (fgets(line, sizeof(line), inventory)) {
		char *fields[6] = { 0 };
		char *save = NULL;
		char *cursor;
		char *priority_end;
		struct stat path_info;
		unsigned long long size_bytes;
		unsigned long long used_bytes;
		long priority;
		size_t count = 0;

		if (++line_count > SWAPZ_STATUS_MAX_RESULTS ||
		    !strchr(line, '\n'))
			return -1;
		for (cursor = strtok_r(line, " \t\r\n", &save);
		     cursor && count < 6U;
		     cursor = strtok_r(NULL, " \t\r\n", &save))
			fields[count++] = cursor;
		if (count != 5U || (strcmp(fields[1], "partition") &&
				      strcmp(fields[1], "file")) ||
		    swapz_parse_swap_kib(fields[2], &size_bytes) < 0 ||
		    swapz_parse_swap_kib(fields[3], &used_bytes) < 0 ||
		    used_bytes > size_bytes)
			return -1;
		errno = 0;
		priority = strtol(fields[4], &priority_end, 10);
		if (errno == ERANGE || priority_end == fields[4] ||
		    *priority_end != '\0')
			return -1;
		/* Do not follow arbitrary non-absolute procfs fields. */
		if (fields[0][0] != '/' || stat(fields[0], &path_info) < 0 ||
		    !S_ISBLK(path_info.st_mode))
			continue;
		for (index = 0; index < report->count; ++index) {
			struct swapz_linux_swap *observed = &observations[index];

			if ((uint64_t)path_info.st_rdev != report->targets[index].device_id)
				continue;
			if (observed->has_usage)
				return -1; /* Same DM identity listed twice. */
			observed->state = "active";
			observed->size_bytes = size_bytes;
			observed->used_bytes = used_bytes;
			observed->priority = priority;
			observed->has_usage = 1;
		}
	}
	return ferror(inventory) ? -1 : 0;
}

static void swapz_observe_linux_swaps(const struct status_ready_report *report,
				      struct swapz_linux_swap *observations)
{
	FILE *inventory;
	size_t index;

	for (index = 0; index < report->count; ++index)
		observations[index].state = "not_observed";
	inventory = fopen("/proc/swaps", "re");
	if (!inventory)
		goto unknown;
	if (swapz_read_linux_swap(inventory, report, observations) < 0) {
		fclose(inventory);
		goto unknown;
	}
	if (fclose(inventory) == 0)
		return;
unknown:
	for (index = 0; index < report->count; ++index) {
		memset(&observations[index], 0, sizeof(observations[index]));
		observations[index].state = "unknown";
	}
}

/*
 * A display view is not an ownership claim. All commands below share the
 * validated INFO/inventory collector; none resolves a name into cleanup
 * authority, opens raw backing, or issues a mutating Device Mapper ioctl.
 */
enum swapz_view {
	SWAPZ_VIEW_STATUS,
	SWAPZ_VIEW_LIST,
	SWAPZ_VIEW_INSPECT,
	SWAPZ_VIEW_STATS,
	SWAPZ_VIEW_HEALTH,
	SWAPZ_VIEW_DIAGNOSE
};

static const char *swapz_view_name(enum swapz_view view)
{
	switch (view) {
	case SWAPZ_VIEW_STATUS: return "status";
	case SWAPZ_VIEW_LIST: return "list";
	case SWAPZ_VIEW_INSPECT: return "inspect";
	case SWAPZ_VIEW_STATS: return "stats";
	case SWAPZ_VIEW_HEALTH: return "health";
	case SWAPZ_VIEW_DIAGNOSE: return "diagnose";
	}
	return "unknown";
}

static int swapz_target_capacity_bytes(const struct status_ready_target *target,
				       unsigned long long *capacity)
{
	if (target->sector_length > ULLONG_MAX / 512ULL)
		return -1;
	*capacity = target->sector_length * 512ULL;
	return 0;
}

static int swapz_print_view(const struct status_ready_report *report,
			    enum swapz_view view, const char *selected_name,
			    int json)
{
	struct swapz_linux_swap *linux_swaps = NULL;
	size_t index;
	size_t matches = 0;
	size_t emitted = 0;

	/* Verify selection and capacity before any output, including a JSON prefix. */
	for (index = 0; index < report->count; ++index) {
		const struct status_ready_target *target = &report->targets[index];
		unsigned long long capacity;

		if (selected_name && strcmp(target->name, selected_name))
			continue;
		if (swapz_target_capacity_bytes(target, &capacity) < 0) {
			fprintf(stderr, "swapzctl %s: BLOCKED: target capacity overflow\n",
				swapz_view_name(view));
			return 1;
		}
		++matches;
	}
	if (selected_name && !matches) {
		fprintf(stderr,
			"swapzctl %s: UNAVAILABLE: no validated swapz target with that exact mapper name; no control action attempted\n",
			swapz_view_name(view));
		return 1;
	}
	if (report->count) {
		linux_swaps = calloc(report->count, sizeof(*linux_swaps));
		if (!linux_swaps) {
			fputs("swapzctl: UNAVAILABLE: swap inventory allocation failed\n", stderr);
			return 1;
		}
		swapz_observe_linux_swaps(report, linux_swaps);
	}
	if (json) {
		/* Mapping names are reduced to ASCII-safe, JSON-safe characters. */
		printf("{\"schema_version\":1,\"command\":\"%s\",\"devices\":[",
		       swapz_view_name(view));
	} else if (view == SWAPZ_VIEW_LIST && matches) {
		puts("MAPPER  TARGET  DM_DEV  CAPACITY_BYTES  HEALTH");
	} else if (!matches) {
		puts("swapz targets: none");
	}
	for (index = 0; index < report->count; ++index) {
		const struct status_ready_target *target = &report->targets[index];
		char safe_name[DM_NAME_LEN + 1U];
		unsigned long long capacity;
		unsigned int device_major;
		unsigned int device_minor;

		if (selected_name && strcmp(target->name, selected_name))
			continue;
		status_safe_mapping_name(target->name, safe_name);
		(void)swapz_target_capacity_bytes(target, &capacity);
		device_major = major((dev_t)target->device_id);
		device_minor = minor((dev_t)target->device_id);
		if (json) {
			printf("%s{\"name\":\"%s\",\"target_index\":%u,"
			       "\"dm_major\":%u,\"dm_minor\":%u,"
			       "\"sector_start\":%" PRIu64 ",\"sector_length\":%" PRIu64 ","
			       "\"logical_capacity_bytes\":%llu,\"kernel_health\":\"ok\","
			       "\"ownership\":\"unverified\","
			       "\"lifetime\":{\"logical_write_bytes\":%llu,"
			       "\"physical_write_bytes\":%llu,\"gc_write_bytes\":%llu,"
			       "\"compressed_pages\":%llu,\"raw_pages\":%llu,"
			       "\"zero_elided_pages\":%llu,"
			       "\"compressed_extent_bytes_exact\":%s},"
			       "\"linux_swap\":{\"state\":\"%s\",\"size_bytes\":",
			       emitted ? "," : "", safe_name, target->target_index,
			       device_major, device_minor, target->sector_start,
			       target->sector_length, capacity,
			       target->ratio.logical_write_bytes,
			       target->ratio.physical_write_bytes,
			       target->ratio.gc_write_bytes,
			       target->ratio.compressed_pages,
			       target->ratio.raw_pages,
			       target->ratio.zero_elided_pages,
			       target->ratio.compressed_extent_ratio_exact ?
			       "true" : "false", linux_swaps[index].state);
			if (linux_swaps[index].has_usage)
				printf("%llu,\"used_bytes\":%llu,\"priority\":%ld}}",
				       linux_swaps[index].size_bytes,
				       linux_swaps[index].used_bytes,
				       linux_swaps[index].priority);
			else
				fputs("null,\"used_bytes\":null,\"priority\":null}}", stdout);
		} else if (view == SWAPZ_VIEW_LIST) {
			printf("%s  %u  %u:%u  %llu  OK\n", safe_name,
			       target->target_index + 1U, device_major, device_minor, capacity);
		} else if (view == SWAPZ_VIEW_HEALTH) {
			printf("%s target %u: OK (kernel failed=0, error=0); "
			       "Linux swap activity and ownership not verified\n",
			       safe_name, target->target_index + 1U);
		} else if (view == SWAPZ_VIEW_DIAGNOSE) {
			printf("%s target %u: INFO counters and Device Mapper identity "
			       "validated; no kernel failure reported\n",
			       safe_name, target->target_index + 1U);
			puts("  Live swap usage and lifecycle ownership have not been proved.");
			puts("  Safe next step: check /proc/swaps and the original "
			     "owner journal; use only the existing verified helper for cleanup.");
			puts("  Never run force dmsetup remove, raw mkswap, or blind swapoff.");
		} else {
			if (view == SWAPZ_VIEW_INSPECT) {
				printf("Device Mapper: %s target %u, device %u:%u\n",
				       safe_name, target->target_index + 1U,
				       device_major, device_minor);
				printf("  Logical sectors: start=%" PRIu64 " length=%" PRIu64
				       " (capacity=%llu bytes)\n",
				       target->sector_start, target->sector_length, capacity);
				puts("  Ownership: unverified (a mapper name is not an owner journal)");
				puts("  Backing identity and Linux swap state: not verified by INFO");
			}
			report_swapz_target(target->name, target->target_index, &target->ratio);
		}
		if (!json && view != SWAPZ_VIEW_DIAGNOSE) {
			if (linux_swaps[index].has_usage)
				printf("  Linux swap: active (advisory), size=%llu used=%llu free=%llu bytes, priority=%ld\n",
				       linux_swaps[index].size_bytes,
				       linux_swaps[index].used_bytes,
				       linux_swaps[index].size_bytes - linux_swaps[index].used_bytes,
				       linux_swaps[index].priority);
			else
				printf("  Linux swap: %s (not proof of an inactive or drained mapper)\n",
				       linux_swaps[index].state);
		}
		++emitted;
	}
	if (json)
		puts("]}");
	free(linux_swaps);
	return 0;
}

static int status_control_open_flags(void)
{
	/* Status uses only DM_LIST_DEVICES and DM_TABLE_STATUS, never a mutation. */
	return O_RDONLY | O_CLOEXEC;
}

static int status_targets(enum swapz_view view, const char *selected_name, int json)
{
	struct status_ready_report report = { 0 };
	int fd;
	int result;

	fd = open(SWAPZ_DM_CONTROL_PATH, status_control_open_flags());
	if (fd < 0) {
		if (errno == EPERM || errno == EACCES)
			fprintf(stderr, "swapzctl status: UNAVAILABLE: opening DM control for observation needs permission (CAP_SYS_ADMIN may be required); errno=%d (%s); no escalation attempted\n",
				errno, strerror(errno));
		else
			perror("swapzctl status: open /dev/mapper/control");
		return 1;
	}
	result = status_collect_targets_with_readers(&fd, status_read_list_with_fd,
						    status_read_device_with_fd, &report);
	if (close(fd) < 0) {
		perror("swapzctl status: close /dev/mapper/control");
		result = 1;
	}
	/* No numeric output until both INFO reads and the final inventory agree. */
	if (!result)
		result = swapz_print_view(&report, view, selected_name, json);
	free(report.targets);
	return result;
}

int main(int argc, char **argv)
{
	struct stat info;

	if (argc >= 2 && !strcmp(argv[1], "primary"))
		return swapz_primary_command(argc - 2, argv + 2);

	if (argc == 2 &&
	    (!strcmp(argv[1], "help") || !strcmp(argv[1], "--help"))) {
		usage(stdout);
		return 0;
	}
	if (argc == 2 &&
	    (!strcmp(argv[1], "version") || !strcmp(argv[1], "--version"))) {
		printf("swapzctl %s (EXPERIMENTAL)\n", SWAPZ_VERSION);
		return 0;
	}
	if (argc >= 2) {
		enum swapz_view view;
		const char *selected_name = NULL;
		int json = 0;

		if (!strcmp(argv[1], "status"))
			view = SWAPZ_VIEW_STATUS;
		else if (!strcmp(argv[1], "list"))
			view = SWAPZ_VIEW_LIST;
		else if (!strcmp(argv[1], "inspect"))
			view = SWAPZ_VIEW_INSPECT;
		else if (!strcmp(argv[1], "stats"))
			view = SWAPZ_VIEW_STATS;
		else if (!strcmp(argv[1], "health"))
			view = SWAPZ_VIEW_HEALTH;
		else if (!strcmp(argv[1], "diagnose"))
			view = SWAPZ_VIEW_DIAGNOSE;
		else
			goto unsupported;

		if (view == SWAPZ_VIEW_STATUS || view == SWAPZ_VIEW_LIST) {
			if (argc == 3 && !strcmp(argv[2], "--json"))
				json = 1;
			else if (argc != 2)
				goto unsupported;
		} else {
			if (argc < 3 || argc > 4)
				goto unsupported;
			selected_name = argv[2];
			if (!selected_name[0] ||
			    strnlen(selected_name, DM_NAME_LEN) >= DM_NAME_LEN ||
			    strchr(selected_name, '/'))
				goto unsupported;
			if (argc == 4) {
				if (strcmp(argv[3], "--json"))
					goto unsupported;
				json = 1;
			}
		}
		if (stat("/sys/module/dm_swapz", &info) == 0 &&
		    S_ISDIR(info.st_mode)) {
			if (view == SWAPZ_VIEW_STATUS && !json)
				puts("dm-swapz: loaded (experimental)");
			return status_targets(view, selected_name, json);
		}
		if (view == SWAPZ_VIEW_STATUS && !json) {
			puts("dm-swapz: not loaded (experimental)");
			return 0;
		}
		if (view == SWAPZ_VIEW_LIST || (view == SWAPZ_VIEW_STATUS && json)) {
			if (json)
				printf("{\"schema_version\":1,\"command\":\"%s\",\"devices\":[]}\\n",
				       swapz_view_name(view));
			else
				puts("swapz targets: none");
			return 0;
		}
		fprintf(stderr, "swapzctl %s: UNAVAILABLE: dm-swapz not loaded\n",
			swapz_view_name(view));
		return 1;
	}
unsupported:
	usage(stderr);
	fputs("BLOCKED: unsupported command; no mapper or swap activation performed.\n",
	      stderr);
	return 2;
}
