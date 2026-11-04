// SPDX-License-Identifier: GPL-2.0-only
/*
 * Explicit swapz administrative tool. Generic status/format never activate
 * swap; primary lifecycle subcommands delegate mapper and swapon/swapoff
 * ownership to swapz-primary, which remains fail-closed behind its gate.
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/dm-ioctl.h>
#include <linux/fs.h>
#include <limits.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/random.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

#include "../kernel/superblock.h"
#include "swapz-primary.h"

#ifndef SWAPZ_VERSION
#define SWAPZ_VERSION "unknown"
#endif

#define SWAPZ_MIN_DATA_BYTES (3ULL * 1024ULL * 1024ULL)
#define SWAPZ_LOGICAL_PAGE_BYTES 4096ULL
#define SWAPZ_DM_CONTROL_PATH "/dev/mapper/control"
#define SWAPZ_DM_BUFFER_INITIAL (64U * 1024U)
#define SWAPZ_DM_BUFFER_MAX (1024U * 1024U)
#define SWAPZ_STATUS_SNAPSHOT_RETRIES 8U
#define SWAPZ_FORMAT_PROC_LINE_BYTES 8192U
#define SWAPZ_FORMAT_PROC_MAX_BYTES (16U * 1024U * 1024U)
#define SWAPZ_FORMAT_PROC_MAX_ROWS 65536U
#define SWAPZ_FORMAT_PROC_MAX_PID_TABLES (4U * 1024U * 1024U)
#define SWAPZ_FORMAT_PARENT_MODEL_BYTES 128U

static void usage(FILE *out)
{
	fputs("Usage: swapzctl version | status | help\n", out);
	fputs("       swapzctl primary plan|qualification-import <report>|"
	      "prepare|start|stop|recover\n", out);
	fputs("       swapzctl format <blockdev> --expect-major-minor <major>:<minor> "
	      "--expect-bytes <decimal-bytes> --expect-partuuid <partuuid> "
	      "--expect-parent-major-minor <major>:<minor> "
	      "--expect-parent-model <model> --expect-parent-transport usb\n", out);
	fputs("status reports cumulative committed foreground compression ratios "
	      "for active swapz targets.\n", out);
	fputs("format is identity-bound: the partition, PARTUUID, exact geometry, "
	      "removable parent, mounts and holders must all verify.\n", out);
	fputs("format writes only the 4096-byte SWZ authorization header and never "
	      "issues DISCARD/TRIM.\n", out);
	fputs("Primary-swap lifecycle commands remain disabled until separately "
	      "qualified.\n", out);
	fputs("The format command creates no mapper target and never enables swap.\n",
	      out);
}

struct format_expectation {
	unsigned int device_major;
	unsigned int device_minor;
	unsigned int parent_major;
	unsigned int parent_minor;
	unsigned long long device_bytes;
	char partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	char parent_model[SWAPZ_FORMAT_PARENT_MODEL_BYTES];
};

/* Parse unsigned decimal without accepting signs, whitespace or overflow. */
static int parse_unsigned_decimal(const char *text, unsigned long long limit,
				  const char **end, unsigned long long *value)
{
	const char *cursor = text;
	unsigned long long parsed = 0;

	if (!text || !end || !value || *cursor < '0' || *cursor > '9')
		return -1;
	/* Kernel and CLI numeric fields are canonical decimal: no leading zeroes. */
	if (*cursor == '0' && cursor[1] >= '0' && cursor[1] <= '9')
		return -1;
	while (*cursor >= '0' && *cursor <= '9') {
		unsigned int digit = (unsigned int)(*cursor - '0');

		if (digit > limit || parsed > (limit - digit) / 10ULL)
			return -1;
		parsed = parsed * 10ULL + digit;
		++cursor;
	}
	*end = cursor;
	*value = parsed;
	return 0;
}

/*
 * Kernel mountinfo uses major zero for pseudofilesystems. Only the inventory
 * parser accepts it; physical partition/parent identity remains nonzero.
 */
static int parse_device_identity_fields(const char *identity,
					unsigned int *device_major,
					unsigned int *device_minor,
					int require_nonzero_major)
{
	const char *end;
	unsigned long long parsed_major;
	unsigned long long parsed_minor;
	dev_t device;

	if (!identity || !device_major || !device_minor ||
	    parse_unsigned_decimal(identity, UINT_MAX, &end, &parsed_major) < 0 ||
	    *end != ':' ||
	    parse_unsigned_decimal(end + 1, UINT_MAX, &end, &parsed_minor) < 0 ||
	    *end != '\0' || (require_nonzero_major && !parsed_major))
		return -1;
	device = makedev((unsigned int)parsed_major, (unsigned int)parsed_minor);
	if (major(device) != (unsigned int)parsed_major ||
	    minor(device) != (unsigned int)parsed_minor)
		return -1;
	*device_major = (unsigned int)parsed_major;
	*device_minor = (unsigned int)parsed_minor;
	return 0;
}

static int parse_device_identity(const char *identity,
				 unsigned int *device_major,
				 unsigned int *device_minor)
{
	return parse_device_identity_fields(identity, device_major, device_minor, 1);
}

static int format_partuuid_normalize(
	const char *text,
	char normalized[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U])
{
	size_t length;
	size_t i;
	unsigned int hex_digits = 0;
	int previous_dash = 0;

	if (!text || !normalized)
		return -1;
	length = strnlen(text, SWAPZ_PRIMARY_PARTUUID_LENGTH + 2U);
	if (length < 8U || length > SWAPZ_PRIMARY_PARTUUID_LENGTH ||
	    text[0] == '-' || text[length - 1U] == '-')
		return -1;
	for (i = 0; i < length; ++i) {
		unsigned char character = (unsigned char)text[i];

		if (character >= '0' && character <= '9') {
			normalized[i] = (char)character;
			hex_digits++;
			previous_dash = 0;
		} else if (character >= 'a' && character <= 'f') {
			normalized[i] = (char)character;
			hex_digits++;
			previous_dash = 0;
		} else if (character >= 'A' && character <= 'F') {
			normalized[i] = (char)(character - 'A' + 'a');
			hex_digits++;
			previous_dash = 0;
		} else if (character == '-' && !previous_dash) {
			normalized[i] = '-';
			previous_dash = 1;
		} else {
			return -1;
		}
	}
	if (hex_digits < 8U)
		return -1;
	normalized[length] = '\0';
	return 0;
}

static int format_parent_expectation(
	const char *model, const char *transport,
	struct format_expectation *expected)
{
	size_t length;
	size_t i;

	if (!model || !transport || !expected || strcmp(transport, "usb"))
		return -1;
	length = strnlen(model, sizeof(expected->parent_model));
	if (!length || length >= sizeof(expected->parent_model) ||
	    model[0] == ' ' || model[length - 1U] == ' ')
		return -1;
	for (i = 0; i < length; ++i) {
		unsigned char character = (unsigned char)model[i];

		if (character < 0x20U || character > 0x7eU)
			return -1;
	}
	memcpy(expected->parent_model, model, length + 1U);
	return 0;
}

static int parse_format_expectation(const char *identity,
				    const char *parent_identity,
				    const char *bytes,
				    const char *partuuid,
				    struct format_expectation *expected)
{
	const char *end;
	unsigned long long device_bytes;
	dev_t device;
	dev_t parent_device;
	struct format_expectation parsed = {0};

	if (!expected ||
	    parse_device_identity(identity, &parsed.device_major,
				  &parsed.device_minor) < 0 ||
	    parse_device_identity(parent_identity, &parsed.parent_major,
				  &parsed.parent_minor) < 0 ||
	    parse_unsigned_decimal(bytes, ULLONG_MAX, &end, &device_bytes) < 0 ||
	    *end != '\0' ||
	    format_partuuid_normalize(partuuid, parsed.partuuid) < 0)
		return -1;

	device = makedev(parsed.device_major, parsed.device_minor);
	parent_device = makedev(parsed.parent_major, parsed.parent_minor);
	if (device == parent_device ||
	    device_bytes < SWAPZ_SUPERBLOCK_BYTES + SWAPZ_MIN_DATA_BYTES ||
	    device_bytes % SWAPZ_SUPERBLOCK_BYTES)
		return -1;
	parsed.device_bytes = device_bytes;
	*expected = parsed;
	return 0;
}

static int block_is_zero(const unsigned char *block)
{
	size_t i;
	unsigned char any = 0;

	for (i = 0; i < SWAPZ_SUPERBLOCK_BYTES; ++i)
		any |= block[i];
	return any == 0;
}

static int fill_random(unsigned char *bytes, size_t length)
{
	size_t done = 0;

	while (done < length) {
		ssize_t count = getrandom(bytes + done, length - done, 0);

		if (count < 0) {
			if (errno == EINTR)
				continue;
			return -1;
		}
		if (!count) {
			errno = EIO;
			return -1;
		}
		done += (size_t)count;
	}
	return 0;
}

static int exact_io(int fd, void *buffer, size_t length, int write_io)
{
	unsigned char *bytes = buffer;
	size_t done = 0;

	if (write_io) {
		/*
		 * A short successful block-zero write may have torn the header.
		 * Never resume a destructive write after losing the complete
		 * per-operation identity proof.
		 */
		ssize_t count = pwrite(fd, bytes, length, 0);

		if (count < 0)
			return -1;
		if ((size_t)count != length) {
			errno = EIO;
			return -1;
		}
		return 0;
	}
	while (done < length) {
		ssize_t count = pread(fd, bytes + done, length - done, (off_t)done);

		if (count < 0) {
			if (errno == EINTR)
				continue;
			return -1;
		}
		if (!count) {
			errno = EIO;
			return -1;
		}
		done += (size_t)count;
	}
	return 0;
}

static void print_uuid(const unsigned char *uuid)
{
	unsigned int i;

	for (i = 0; i < SWAPZ_SUPERBLOCK_UUID_BYTES; ++i) {
		printf("%02x", uuid[i]);
		if (i == 3U || i == 5U || i == 7U || i == 9U)
			putchar('-');
	}
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
	unsigned long long compressed_logical_bytes;
	unsigned long long compressed_extent_bytes;
	unsigned long long overall_physical_bytes;
	int compressed_extent_ratio_exact;
};

struct swapz_target_snapshot {
	uint64_t sector_start;
	uint64_t length;
	struct swapz_ratio_status ratio;
	int ratio_state;
};

static int status_separator(char character)
{
	return character == ' ' || character == '\t' || character == '\n';
}

static int parse_status_unsigned(const char *status, const char *key,
				 unsigned long long *value)
{
	const size_t key_length = strlen(key);
	const char *cursor = status;

	while (*cursor) {
		const char *token_end;
		const char *parsed_end;
		unsigned long long parsed;

		while (*cursor && status_separator(*cursor))
			++cursor;
		if (!*cursor)
			break;
		token_end = cursor;
		while (*token_end && !status_separator(*token_end))
			++token_end;
		if ((size_t)(token_end - cursor) > key_length + 1U &&
		    !memcmp(cursor, key, key_length) && cursor[key_length] == '=' &&
		    parse_unsigned_decimal(cursor + key_length + 1U, ULLONG_MAX,
					   &parsed_end, &parsed) == 0 &&
		    parsed_end == token_end) {
			*value = parsed;
			return 0;
		}
		cursor = token_end;
	}
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
 * status. The caller also requires two identical relevant snapshots before
 * printing a ratio.
 */
static int parse_swapz_ratio_status(const char *status,
				    struct swapz_ratio_status *ratio)
{
	unsigned long long total_pages;
	unsigned long long page_logical_bytes;
	unsigned long long raw_physical_bytes;

	memset(ratio, 0, sizeof(*ratio));
	if (parse_status_unsigned(status, "logical_write",
				  &ratio->logical_write_bytes) < 0 ||
	    parse_status_unsigned(status, "physical_write",
				  &ratio->physical_write_bytes) < 0 ||
	    parse_status_unsigned(status, "gc_write", &ratio->gc_write_bytes) < 0 ||
	    parse_status_unsigned(status, "compressed", &ratio->compressed_pages) < 0 ||
	    parse_status_unsigned(status, "raw", &ratio->raw_pages) < 0 ||
	    parse_status_unsigned(status, "zero_elided", &ratio->zero_elided_pages) < 0 ||
	    parse_status_unsigned(status, "bulk_mode", &ratio->bulk_mode) < 0 ||
	    parse_status_unsigned(status, "bulk_padding",
				  &ratio->bulk_padding_blocks) < 0 ||
	    parse_status_unsigned(status, "failed", &ratio->failed) < 0)
		return -1;

	if (ratio->failed)
		return 2;
	if (ratio->compressed_pages > ULLONG_MAX - ratio->raw_pages ||
	    ratio->compressed_pages + ratio->raw_pages >
			ULLONG_MAX - ratio->zero_elided_pages)
		return -1;
	total_pages = ratio->compressed_pages + ratio->raw_pages +
		      ratio->zero_elided_pages;
	if (pages_to_bytes(total_pages, &page_logical_bytes) < 0 ||
	    pages_to_bytes(ratio->compressed_pages,
			   &ratio->compressed_logical_bytes) < 0 ||
	    pages_to_bytes(ratio->raw_pages, &raw_physical_bytes) < 0)
		return -1;

	/* A mismatch is most likely one status read crossing a live commit. */
	if (page_logical_bytes != ratio->logical_write_bytes ||
	    ratio->physical_write_bytes < ratio->gc_write_bytes)
		return 1;
	ratio->overall_physical_bytes =
		ratio->physical_write_bytes - ratio->gc_write_bytes;
	if (ratio->overall_physical_bytes < raw_physical_bytes)
		return 1;
	ratio->compressed_extent_bytes =
		ratio->overall_physical_bytes - raw_physical_bytes;
	if ((!ratio->compressed_pages && ratio->compressed_extent_bytes) ||
	    (ratio->compressed_pages && !ratio->compressed_extent_bytes))
		return 1;

	/*
	 * lower_bulk=0/1 never writes padding. With mode 2, a nonzero cumulative
	 * padding counter is not success- or foreground-partitioned, so do not
	 * pretend it can be subtracted from compressed SWZ extent bytes.
	 */
	if (ratio->bulk_mode > 2ULL)
		return -1;
	ratio->compressed_extent_ratio_exact =
		ratio->bulk_mode <= 1ULL || ratio->bulk_padding_blocks == 0ULL;
	return 0;
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
	       left->failed == right->failed;
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

static void print_ratio(const char *label, unsigned long long logical_bytes,
			unsigned long long physical_bytes)
{
	char logical_text[64];
	char physical_text[64];

	format_bytes(logical_bytes, logical_text, sizeof(logical_text));
	format_bytes(physical_bytes, physical_text, sizeof(physical_text));
	if (!logical_bytes) {
		printf("  %s: n/a (no logical data)\n", label);
		return;
	}
	if (!physical_bytes) {
		printf("  %s: infinite (%s logical / 0 B lower)\n",
		       label, logical_text);
		return;
	}
	printf("  %s: %.2Lf:1 (%s logical / %s lower)\n", label,
	       (long double)logical_bytes / (long double)physical_bytes,
	       logical_text, physical_text);
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

static int dm_query(int fd, unsigned long request, const char *name,
		    unsigned char **result, size_t *result_size)
{
	size_t buffer_size = SWAPZ_DM_BUFFER_INITIAL;

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
		if (io->data_size > buffer_size || io->data_start > io->data_size) {
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

static int read_swapz_target_snapshot(int fd, const char *name,
				      unsigned int wanted_target,
				      struct swapz_target_snapshot *snapshot)
{
	unsigned char *buffer = NULL;
	size_t buffer_size = 0;
	struct dm_ioctl *io;
	char *cursor;
	char *data_end;
	uint32_t target;
	unsigned int swapz_index = 0;
	int result = 0;

	if (dm_query(fd, DM_TABLE_STATUS, name, &buffer, &buffer_size) < 0)
		return -1;
	(void)buffer_size;
	io = (struct dm_ioctl *)buffer;
	cursor = (char *)buffer + io->data_start;
	data_end = (char *)buffer + io->data_size;
	for (target = 0; target < io->target_count; ++target) {
		struct dm_target_spec *spec;
		char *record_end;
		char *params;
		size_t type_length;
		const char *params_end;

		if ((size_t)(data_end - cursor) < sizeof(*spec)) {
			errno = EPROTO;
			result = -1;
			break;
		}
		spec = (struct dm_target_spec *)cursor;
		if (spec->next) {
			if (spec->next < sizeof(*spec) ||
			    (size_t)(data_end - cursor) < spec->next) {
				errno = EPROTO;
				result = -1;
				break;
			}
			record_end = cursor + spec->next;
		} else {
			record_end = data_end;
		}
		type_length = strnlen(spec->target_type, sizeof(spec->target_type));
		if (type_length == sizeof(spec->target_type)) {
			errno = EPROTO;
			result = -1;
			break;
		}
		params = (char *)(spec + 1);
		if (params > record_end) {
			errno = EPROTO;
			result = -1;
			break;
		}
		params_end = memchr(params, '\0', (size_t)(record_end - params));
		if (!params_end) {
			errno = EPROTO;
			result = -1;
			break;
		}
		if (type_length == sizeof("swapz") - 1U &&
		    !memcmp(spec->target_type, "swapz", sizeof("swapz") - 1U)) {
			if (swapz_index == wanted_target) {
				snapshot->sector_start = spec->sector_start;
				snapshot->length = spec->length;
				snapshot->ratio_state =
					parse_swapz_ratio_status(params, &snapshot->ratio);
				if (snapshot->ratio_state < 0) {
					errno = EPROTO;
					result = -1;
				} else {
					result = 1;
				}
				break;
			}
			swapz_index++;
		}
		if (!spec->next) {
			if (target + 1U != io->target_count) {
				errno = EPROTO;
				result = -1;
			}
			break;
		}
		cursor = record_end;
	}
	free(buffer);
	return result;
}

static void report_swapz_target(const char *name, unsigned int target_index,
				const struct swapz_ratio_status *ratio)
{
	char gc_text[64];
	char foreground_text[64];

	printf("swapz target: %s", name);
	if (target_index)
		printf(" (target %u)", target_index + 1U);
	putchar('\n');
	if (ratio->failed) {
		puts("  compression ratios: unavailable "
		     "(target is failed; lower writes may not be published)");
		return;
	}
	if (ratio->compressed_pages) {
		if (ratio->compressed_extent_ratio_exact)
			print_ratio("compressed ratio (SWZ extents)",
				    ratio->compressed_logical_bytes,
				    ratio->compressed_extent_bytes);
		else
			puts("  compressed ratio (SWZ extents): unavailable "
			     "(nonzero lower_bulk padding cannot be partitioned exactly)");
	} else {
		puts("  compressed ratio (SWZ extents): n/a (no compressed pages)");
	}
	print_ratio("overall ratio (compressed + RAW + zero)",
		    ratio->logical_write_bytes, ratio->overall_physical_bytes);
	printf("  pages: compressed=%llu raw=%llu zero-elided=%llu\n",
	       ratio->compressed_pages, ratio->raw_pages, ratio->zero_elided_pages);
	format_bytes(ratio->overall_physical_bytes, foreground_text,
		     sizeof(foreground_text));
	format_bytes(ratio->gc_write_bytes, gc_text, sizeof(gc_text));
	printf("  foreground lower writes: %s; GC excluded: %s\n",
	       foreground_text, gc_text);
	puts("  scope: cumulative successful foreground writes since target creation");
}

static int report_device_status(int fd, const char *name, int *swapz_targets)
{
	unsigned int target_index;

	for (target_index = 0;; ++target_index) {
		unsigned int attempt;
		int found_target = 0;

		for (attempt = 0; attempt < SWAPZ_STATUS_SNAPSHOT_RETRIES; ++attempt) {
			struct swapz_target_snapshot first = { 0 };
			struct swapz_target_snapshot second = { 0 };
			int first_result;
			int second_result;

			first_result = read_swapz_target_snapshot(
				fd, name, target_index, &first);
			if (first_result < 0)
				return -1;
			if (!first_result)
				break;
			found_target = 1;
			second_result = read_swapz_target_snapshot(
				fd, name, target_index, &second);
			if (second_result < 0)
				return -1;
			if (!second_result ||
			    first.sector_start != second.sector_start ||
			    first.length != second.length ||
			    first.ratio_state != second.ratio_state ||
			    !ratio_status_equal(&first.ratio, &second.ratio))
				continue;
			if (first.ratio_state == 1)
				continue;
			report_swapz_target(name, target_index, &first.ratio);
			(*swapz_targets)++;
			break;
		}
		if (!found_target)
			return 0;
		if (attempt == SWAPZ_STATUS_SNAPSHOT_RETRIES) {
			errno = EAGAIN;
			return -1;
		}
	}
}

static int status_targets(void)
{
	unsigned char *buffer = NULL;
	size_t buffer_size = 0;
	struct dm_ioctl *io;
	char *cursor;
	char *data_end;
	int fd;
	int swapz_targets = 0;
	int result = 1;

	fd = open(SWAPZ_DM_CONTROL_PATH, O_RDWR | O_CLOEXEC);
	if (fd < 0) {
		perror("swapzctl status: open /dev/mapper/control");
		return 1;
	}
	if (dm_query(fd, DM_LIST_DEVICES, NULL, &buffer, &buffer_size) < 0) {
		perror("swapzctl status: list Device Mapper devices");
		goto out;
	}
	(void)buffer_size;
	io = (struct dm_ioctl *)buffer;
	cursor = (char *)buffer + io->data_start;
	data_end = (char *)buffer + io->data_size;
	while (cursor < data_end) {
		struct dm_name_list *entry;
		char *record_end;
		char *name;
		const char *name_end;

		if ((size_t)(data_end - cursor) <
		    offsetof(struct dm_name_list, name) + 1U) {
			errno = EPROTO;
			perror("swapzctl status: malformed Device Mapper device list");
			goto out;
		}
		entry = (struct dm_name_list *)cursor;
		if (entry->next) {
			if (entry->next < offsetof(struct dm_name_list, name) + 1U ||
			    (size_t)(data_end - cursor) < entry->next) {
				errno = EPROTO;
				perror("swapzctl status: malformed Device Mapper device list");
				goto out;
			}
			record_end = cursor + entry->next;
		} else {
			record_end = data_end;
		}
		name = entry->name;
		name_end = memchr(name, '\0', (size_t)(record_end - name));
		if (!name_end) {
			errno = EPROTO;
			perror("swapzctl status: malformed Device Mapper device name");
			goto out;
		}
		if (*name && report_device_status(fd, name, &swapz_targets) < 0 &&
		    errno != ENXIO && errno != ENODEV) {
			perror("swapzctl status: read Device Mapper target status");
			goto out;
		}
		if (!entry->next)
			break;
		cursor = record_end;
	}
	if (!swapz_targets)
		puts("swapz targets: none");
	result = 0;
out:
	free(buffer);
	if (close(fd) < 0) {
		perror("swapzctl status: close /dev/mapper/control");
		return 1;
	}
	return result;
}

static int format_read_text_file(const char *path, char *buffer,
				 size_t capacity)
{
	size_t used = 0;
	int fd;
	int saved_errno;

	if (!path || !buffer || capacity < 2U) {
		errno = EINVAL;
		return -1;
	}
	fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
	if (fd < 0)
		return -1;
	while (used + 1U < capacity) {
		ssize_t count = read(fd, buffer + used, capacity - used - 1U);

		if (count < 0) {
			if (errno == EINTR)
				continue;
			saved_errno = errno;
			close(fd);
			errno = saved_errno;
			return -1;
		}
		if (!count)
			break;
		used += (size_t)count;
	}
	if (used + 1U == capacity) {
		unsigned char extra;
		ssize_t count;

		do {
			count = read(fd, &extra, 1U);
		} while (count < 0 && errno == EINTR);
		if (count != 0) {
			saved_errno = count < 0 ? errno : EOVERFLOW;
			close(fd);
			errno = saved_errno;
			return -1;
		}
	}
	/* sysfs data is byte-counted; an embedded NUL must never hide a field. */
	if (memchr(buffer, '\0', used)) {
		close(fd);
		errno = EPROTO;
		return -1;
	}
	buffer[used] = '\0';
	if (close(fd) < 0)
		return -1;
	return 0;
}

static int format_parse_text_u64(const char *text, unsigned long long limit,
				 unsigned long long *value)
{
	const char *end;

	if (!text || !value ||
	    parse_unsigned_decimal(text, limit, &end, value) < 0)
		return -1;
	if (*end == '\n')
		++end;
	return *end == '\0' ? 0 : -1;
}

static int format_parse_device_text(const char *text, dev_t *device)
{
	unsigned int device_major;
	unsigned int device_minor;
	char identity[64];
	const char *newline;
	size_t length;

	if (!text || !device)
		return -1;
	newline = strchr(text, '\n');
	length = newline ? (size_t)(newline - text) : strlen(text);
	if (!length || length >= sizeof(identity) ||
	    (newline && newline[1] != '\0'))
		return -1;
	memcpy(identity, text, length);
	identity[length] = '\0';
	if (parse_device_identity(identity, &device_major, &device_minor) < 0)
		return -1;
	*device = makedev(device_major, device_minor);
	return 0;
}

static int format_sysfs_directory_empty(const char *path)
{
	DIR *directory;
	struct dirent *entry;
	int saved_errno;

	directory = opendir(path);
	if (!directory)
		return -1;
	for (;;) {
		errno = 0;
		entry = readdir(directory);
		if (!entry)
			break;
		if (strcmp(entry->d_name, ".") && strcmp(entry->d_name, "..")) {
			if (closedir(directory) < 0)
				return -1;
			return 0;
		}
	}
	saved_errno = errno;
	if (closedir(directory) < 0 && !saved_errno)
		return -1;
	if (saved_errno) {
		errno = saved_errno;
		return -1;
	}
	return 1;
}

static int format_parent_only_partition(const char *parent_path,
					const char *partition_path)
{
	char attribute_path[PATH_MAX];
	const char *expected_name;
	DIR *directory;
	struct dirent *entry;
	unsigned int partition_count = 0;
	int expected_found = 0;
	int saved_errno = 0;

	if (!parent_path || !partition_path) {
		errno = EINVAL;
		return -1;
	}
	expected_name = strrchr(partition_path, '/');
	if (!expected_name || !expected_name[1]) {
		errno = EINVAL;
		return -1;
	}
	++expected_name;
	directory = opendir(parent_path);
	if (!directory)
		return -1;
	for (;;) {
		struct stat info;
		int length;

		errno = 0;
		entry = readdir(directory);
		if (!entry)
			break;
		if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, ".."))
			continue;
		length = snprintf(attribute_path, sizeof(attribute_path),
				  "%s/%s/partition", parent_path, entry->d_name);
		if (length < 0 || (size_t)length >= sizeof(attribute_path)) {
			saved_errno = ENAMETOOLONG;
			break;
		}
		if (stat(attribute_path, &info) < 0) {
			if (errno == ENOENT || errno == ENOTDIR)
				continue;
			saved_errno = errno;
			break;
		}
		if (!S_ISREG(info.st_mode)) {
			saved_errno = EPROTO;
			break;
		}
		partition_count++;
		if (!strcmp(entry->d_name, expected_name))
			expected_found = 1;
	}
	if (!saved_errno && errno)
		saved_errno = errno;
	if (closedir(directory) < 0 && !saved_errno)
		saved_errno = errno;
	if (saved_errno) {
		errno = saved_errno;
		return -1;
	}
	return expected_found && partition_count == 1U;
}

static int format_usb_transport_path(const char *physical_path)
{
	const char *cursor = physical_path;

	if (!physical_path)
		return 0;
	while ((cursor = strstr(cursor, "/usb")) != NULL) {
		const char *digits = cursor + 4;

		if (*digits >= '0' && *digits <= '9') {
			while (*digits >= '0' && *digits <= '9')
				++digits;
			if (*digits == '/' || *digits == '\0')
				return 1;
		}
		cursor += 4;
	}
	return 0;
}

static int format_observed_model_matches(
	char *observed, const char *expected_model)
{
	size_t length;
	size_t i;

	if (!observed || !expected_model)
		return 0;
	length = strlen(observed);
	while (length && (observed[length - 1U] == '\n' ||
			  observed[length - 1U] == '\r' ||
			  observed[length - 1U] == ' ' ||
			  observed[length - 1U] == '\t'))
		observed[--length] = '\0';
	if (!length)
		return 0;
	for (i = 0; i < length; ++i) {
		unsigned char character = (unsigned char)observed[i];

		if (character < 0x20U || character > 0x7eU)
			return 0;
	}
	return !strcmp(observed, expected_model);
}

static int format_topology_flags_allowed(int partition_number_valid,
					 int sole_partition,
					 int parent_removable,
					 int parent_model_matches,
					 int parent_transport_matches,
					 int partition_holders_empty,
					 int partition_slaves_empty,
					 int parent_holders_empty,
					 int parent_slaves_empty)
{
	return partition_number_valid && sole_partition && parent_removable &&
	       parent_model_matches && parent_transport_matches &&
	       partition_holders_empty == 1 && partition_slaves_empty == 1 &&
	       parent_holders_empty == 1 && parent_slaves_empty == 1;
}

static int format_verify_parent_topology(
	dev_t device, const struct format_expectation *expected,
	dev_t *parent_device)
{
	static const char devices_prefix[] = "/sys/devices/";
	char link_path[128];
	char partition_path[PATH_MAX];
	char parent_path[PATH_MAX];
	char device_link[PATH_MAX];
	char physical_path[PATH_MAX];
	char path[PATH_MAX];
	char text[128];
	struct stat info;
	struct stat link_info;
	dev_t observed_device;
	dev_t observed_parent;
	unsigned long long partition_number;
	unsigned long long removable;
	char *slash;
	int partition_holders_empty;
	int partition_slaves_empty;
	int parent_holders_empty;
	int parent_slaves_empty;
	int length;

	if (!expected || !expected->parent_model[0] ||
	    !parent_device || !major(device)) {
		errno = EINVAL;
		return -1;
	}
	length = snprintf(link_path, sizeof(link_path), "/sys/dev/block/%u:%u",
			  major(device), minor(device));
	if (length < 0 || (size_t)length >= sizeof(link_path))
		goto path_overflow;
	if (lstat(link_path, &link_info) < 0)
		return -1;
	if (!S_ISLNK(link_info.st_mode)) {
		errno = ENODEV;
		return -1;
	}
	if (!realpath(link_path, partition_path))
		return -1;
	if (strncmp(partition_path, devices_prefix,
		    sizeof(devices_prefix) - 1U) ||
	    strstr(partition_path, "/virtual/") != NULL) {
		errno = ENODEV;
		return -1;
	}
	if (stat(partition_path, &info) < 0)
		return -1;
	if (!S_ISDIR(info.st_mode)) {
		errno = ENODEV;
		return -1;
	}

	length = snprintf(path, sizeof(path), "%s/dev", partition_path);
	if (length < 0 || (size_t)length >= sizeof(path))
		goto path_overflow;
	if (format_read_text_file(path, text, sizeof(text)) < 0)
		return -1;
	if (format_parse_device_text(text, &observed_device) < 0 ||
	    observed_device != device) {
		errno = ESTALE;
		return -1;
	}

	length = snprintf(path, sizeof(path), "%s/partition", partition_path);
	if (length < 0 || (size_t)length >= sizeof(path))
		goto path_overflow;
	if (format_read_text_file(path, text, sizeof(text)) < 0)
		return -1;
	if (format_parse_text_u64(text, ULLONG_MAX, &partition_number) < 0 ||
	    !partition_number) {
		errno = ENODEV;
		return -1;
	}

	length = snprintf(parent_path, sizeof(parent_path), "%s", partition_path);
	if (length < 0 || (size_t)length >= sizeof(parent_path))
		goto path_overflow;
	slash = strrchr(parent_path, '/');
	if (!slash || slash == parent_path) {
		errno = ENODEV;
		return -1;
	}
	*slash = '\0';

	length = snprintf(path, sizeof(path), "%s/dev", parent_path);
	if (length < 0 || (size_t)length >= sizeof(path))
		goto path_overflow;
	if (format_read_text_file(path, text, sizeof(text)) < 0)
		return -1;
	if (format_parse_device_text(text, &observed_parent) < 0 ||
	    observed_parent == device) {
		errno = ENODEV;
		return -1;
	}

	length = snprintf(path, sizeof(path), "%s/removable", parent_path);
	if (length < 0 || (size_t)length >= sizeof(path))
		goto path_overflow;
	if (format_read_text_file(path, text, sizeof(text)) < 0)
		return -1;
	if (format_parse_text_u64(text, 1ULL, &removable) < 0) {
		errno = EPROTO;
		return -1;
	}

	length = snprintf(device_link, sizeof(device_link), "%s/device", parent_path);
	if (length < 0 || (size_t)length >= sizeof(device_link))
		goto path_overflow;
	if (lstat(device_link, &link_info) < 0)
		return -1;
	if (!S_ISLNK(link_info.st_mode)) {
		errno = ENODEV;
		return -1;
	}
	if (!realpath(device_link, physical_path))
		return -1;
	if (strncmp(physical_path, devices_prefix, sizeof(devices_prefix) - 1U) ||
	    strstr(physical_path, "/virtual/") != NULL) {
		errno = ENODEV;
		return -1;
	}

	length = snprintf(path, sizeof(path), "%s/device/model", parent_path);
	if (length < 0 || (size_t)length >= sizeof(path))
		goto path_overflow;
	if (format_read_text_file(path, text, sizeof(text)) < 0)
		return -1;
	if (!format_observed_model_matches(text, expected->parent_model)) {
		errno = ESTALE;
		return -1;
	}
	if (!format_usb_transport_path(physical_path)) {
		errno = ESTALE;
		return -1;
	}
	if (format_parent_only_partition(parent_path, partition_path) != 1) {
		if (!errno)
			errno = EBUSY;
		return -1;
	}

	length = snprintf(path, sizeof(path), "%s/queue", parent_path);
	if (length < 0 || (size_t)length >= sizeof(path))
		goto path_overflow;
	if (stat(path, &info) < 0)
		return -1;
	if (!S_ISDIR(info.st_mode)) {
		errno = ENODEV;
		return -1;
	}

	length = snprintf(path, sizeof(path), "%s/holders", partition_path);
	if (length < 0 || (size_t)length >= sizeof(path))
		goto path_overflow;
	partition_holders_empty = format_sysfs_directory_empty(path);
	if (partition_holders_empty < 0)
		return -1;
	length = snprintf(path, sizeof(path), "%s/slaves", partition_path);
	if (length < 0 || (size_t)length >= sizeof(path))
		goto path_overflow;
	partition_slaves_empty = format_sysfs_directory_empty(path);
	if (partition_slaves_empty < 0)
		return -1;
	length = snprintf(path, sizeof(path), "%s/holders", parent_path);
	if (length < 0 || (size_t)length >= sizeof(path))
		goto path_overflow;
	parent_holders_empty = format_sysfs_directory_empty(path);
	if (parent_holders_empty < 0)
		return -1;
	length = snprintf(path, sizeof(path), "%s/slaves", parent_path);
	if (length < 0 || (size_t)length >= sizeof(path))
		goto path_overflow;
	parent_slaves_empty = format_sysfs_directory_empty(path);
	if (parent_slaves_empty < 0)
		return -1;

	if (!format_topology_flags_allowed(
		    1, 1, removable == 1ULL, 1, 1, partition_holders_empty,
		    partition_slaves_empty, parent_holders_empty,
		    parent_slaves_empty)) {
		errno = EBUSY;
		return -1;
	}
	*parent_device = observed_parent;
	return 0;

path_overflow:
	errno = ENAMETOOLONG;
	return -1;
}

static int format_sysfs_partuuid_matches(dev_t device,
					 const char *expected_partuuid)
{
	char path[128];
	char text[4096];
	char normalized[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	char observed[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	const char *cursor;
	int found = 0;
	int length;

	length = snprintf(path, sizeof(path), "/sys/dev/block/%u:%u/uevent",
			  major(device), minor(device));
	if (length < 0 || (size_t)length >= sizeof(path)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	if (format_read_text_file(path, text, sizeof(text)) < 0)
		return -1;
	cursor = text;
	while (*cursor) {
		const char *line_end = strchr(cursor, '\n');
		size_t line_length =
			line_end ? (size_t)(line_end - cursor) : strlen(cursor);

		if (line_length > sizeof("PARTUUID=") - 1U &&
		    !memcmp(cursor, "PARTUUID=", sizeof("PARTUUID=") - 1U)) {
			size_t value_length =
				line_length - (sizeof("PARTUUID=") - 1U);

			if (found || value_length > SWAPZ_PRIMARY_PARTUUID_LENGTH) {
				errno = EPROTO;
				return -1;
			}
			memcpy(observed, cursor + sizeof("PARTUUID=") - 1U,
			       value_length);
			observed[value_length] = '\0';
			if (format_partuuid_normalize(observed, normalized) < 0 ||
			    strcmp(normalized, expected_partuuid)) {
				errno = ESTALE;
				return -1;
			}
			found = 1;
		}
		if (!line_end)
			break;
		cursor = line_end + 1;
	}
	if (!found) {
		errno = ENODEV;
		return -1;
	}
	return 0;
}

/* Mountinfo encodes whitespace and backslashes in path fields as octal. */
static int format_mountinfo_path_valid(const char *begin, const char *end)
{
	const char *cursor = begin;

	if (cursor == end || *cursor != '/')
		return 0;
	while (cursor < end) {
		if (*cursor != '\\') {
			++cursor;
			continue;
		}
		if (end - cursor < 4 || cursor[1] < '0' || cursor[1] > '7' ||
		    cursor[2] < '0' || cursor[2] > '7' ||
		    cursor[3] < '0' || cursor[3] > '7')
			return 0;
		{
			const unsigned int escaped_byte =
				((unsigned int)(cursor[1] - '0') << 6) |
				((unsigned int)(cursor[2] - '0') << 3) |
				(unsigned int)(cursor[3] - '0');

			/* Linux only escapes these four otherwise ambiguous bytes. */
			if (escaped_byte != ' ' && escaped_byte != '\t' &&
			    escaped_byte != '\n' && escaped_byte != '\\')
				return 0;
		}
		cursor += 4;
	}
	return 1;
}

/* Known mountinfo propagation fields are unique; unknown fields are extensible. */
static int format_mountinfo_optional_valid(const char *begin, const char *end,
					   unsigned int *seen_fields)
{
	static const struct {
		const char *name;
		unsigned int bit;
	} numeric_fields[] = {
		{ "shared", 1U << 0 },
		{ "master", 1U << 1 },
		{ "propagate_from", 1U << 2 },
	};
	const size_t length = (size_t)(end - begin);
	size_t index;

	if (!begin || !end || !seen_fields || begin >= end)
		return 0;
	if (length == sizeof("unbindable") - 1U &&
	    !memcmp(begin, "unbindable", sizeof("unbindable") - 1U)) {
		const unsigned int bit = 1U << 3;

		if (*seen_fields & bit)
			return 0;
		*seen_fields |= bit;
		return 1;
	}
	if (length > sizeof("unbindable") - 1U &&
	    !memcmp(begin, "unbindable:", sizeof("unbindable:") - 1U))
		return 0;

	for (index = 0; index < sizeof(numeric_fields) / sizeof(numeric_fields[0]);
	     ++index) {
		const size_t name_length = strlen(numeric_fields[index].name);
		const char *number_end;
		unsigned long long mount_identifier;

		if (length == name_length &&
		    !memcmp(begin, numeric_fields[index].name, name_length))
			return 0;
		if (length <= name_length || begin[name_length] != ':' ||
		    memcmp(begin, numeric_fields[index].name, name_length))
			continue;
		if ((*seen_fields & numeric_fields[index].bit) ||
		    parse_unsigned_decimal(begin + name_length + 1U,
					      (unsigned long long)INT_MAX,
					      &number_end, &mount_identifier) < 0 ||
		    number_end != end || !mount_identifier)
			return 0;
		if (numeric_fields[index].bit == (1U << 2) &&
		    !(*seen_fields & (1U << 1)))
			return 0;
		*seen_fields |= numeric_fields[index].bit;
		return 1;
	}

	/*
	 * mountinfo is extensible. Linux requires parsers to ignore fields they do
	 * not recognize so a future unrelated mount does not become ambiguity.
	 */
	return 1;
}

static int format_mountinfo_rw_options_valid(const char *begin,
					     const char *end)
{
	const size_t length = (size_t)(end - begin);

	if (!begin || !end || length < 2U)
		return 0;
	if ((memcmp(begin, "ro", 2U) && memcmp(begin, "rw", 2U)) ||
	    (length > 2U && begin[2] != ','))
		return 0;
	return 1;
}

static int format_mountinfo_line_device(const char *line, dev_t *device)
{
	const char *cursor;
	const char *separator;
	unsigned int mounted_major = 0U;
	unsigned int mounted_minor = 0U;
	unsigned int field = 0U;
	unsigned int optional_fields = 0U;

	if (!line || !device)
		return -1;
	separator = strstr(line, " - ");
	if (!separator)
		return -1;
	cursor = line;
	while (cursor < separator) {
		const char *token_end;

		while (cursor < separator && (*cursor == ' ' || *cursor == '\t'))
			++cursor;
		if (cursor == separator)
			break;
		token_end = cursor;
		while (token_end < separator && *token_end != ' ' &&
		       *token_end != '\t')
			++token_end;
		if (field < 2U) {
			const char *end;
			unsigned long long mount_identifier;

			if (parse_unsigned_decimal(cursor, (unsigned long long)INT_MAX,
						   &end, &mount_identifier) < 0 ||
			    end != token_end || !mount_identifier)
				return -1;
		} else if (field == 2U) {
			char token[64];
			size_t length = (size_t)(token_end - cursor);

			if (!length || length >= sizeof(token))
				return -1;
			memcpy(token, cursor, length);
			token[length] = '\0';
			if (parse_device_identity_fields(token, &mounted_major,
							 &mounted_minor, 0) < 0)
				return -1;
		} else if (field == 4U &&
			   !format_mountinfo_path_valid(cursor, token_end)) {
			/*
			 * The root field is filesystem-specific: nsfs and other
			 * filesystems may emit a non-path token. The mountpoint is
			 * always the escaped absolute path that must validate here.
			 */
			return -1;
		} else if (field == 5U &&
			   !format_mountinfo_rw_options_valid(cursor, token_end)) {
			return -1;
		} else if (field >= 6U &&
			   !format_mountinfo_optional_valid(cursor, token_end,
						    &optional_fields)) {
			return -1;
		}
		++field;
		cursor = token_end;
	}
	/* Mount ID, parent ID, device, root, mountpoint and options are required. */
	if (field < 6U)
		return -1;
	cursor = separator + 3U;
	/* Filesystem type, source and ro/rw-prefixed superblock options are required. */
	for (field = 0U; field < 3U; ++field) {
		const char *token_begin;

		while (*cursor == ' ' || *cursor == '\t')
			++cursor;
		if (!*cursor || *cursor == '\n')
			return -1;
		token_begin = cursor;
		while (*cursor && *cursor != ' ' && *cursor != '\t' &&
		       *cursor != '\n')
			++cursor;
		if (field == 2U &&
		    !format_mountinfo_rw_options_valid(token_begin, cursor))
			return -1;
	}
	while (*cursor == ' ' || *cursor == '\t')
		++cursor;
	if (*cursor != '\0' && (*cursor != '\n' || cursor[1] != '\0'))
		return -1;
	*device = makedev(mounted_major, mounted_minor);
	return 0;
}

static int format_inventory_device_conflicts(dev_t observed_device,
					     dev_t device,
					     dev_t parent_device)
{
	return observed_device == device || observed_device == parent_device;
}

/*
 * Swapfiles name regular files, not block nodes. Their filesystem st_dev
 * still identifies a directly mounted target/parent backing device even if
 * that mount is absent from this process's mount namespace.
 */
static int format_swap_entry_conflicts(const struct stat *info, dev_t device,
				       dev_t parent_device)
{
	if (!info)
		return 1;
	if (S_ISBLK(info->st_mode))
		return format_inventory_device_conflicts(info->st_rdev, device,
						  parent_device);
	if (S_ISREG(info->st_mode))
		return format_inventory_device_conflicts(info->st_dev, device,
						  parent_device);
	/* /proc/swaps cannot legitimately name another file type. */
	return 1;
}

/*
 * Mounts in another process's namespace still use the same backing device.
 * Inspect every visible process, not only /proc/self/mountinfo. Process churn
 * is normal: an exiting task can lose its mount namespace before its /proc PID
 * entry disappears. Ignore only an unopened table whose namespace is also
 * absent; opened, malformed, unreadable or still-namespaced tables fail closed.
 */
/*
 * /proc inventories are records, not NUL-terminated user strings. Every
 * kernel row ends in a newline; a truncated, embedded-NUL or over-budget
 * snapshot is never evidence that the device is idle. Other filename bytes
 * remain opaque because Linux can emit them literally.
 */
static int format_inventory_read_line(FILE *stream, char *line, size_t capacity,
				      size_t *total_bytes)
{
	size_t used = 0;

	if (!stream || !line || !total_bytes || capacity < 2U) {
		errno = EINVAL;
		return -1;
	}
	for (;;) {
		/* This parser alone owns the stream; no per-byte stdio lock. */
		int character = getc_unlocked(stream);

		if (character == EOF) {
			if (ferror(stream)) {
				if (!errno)
					errno = EIO;
				return -1;
			}
			if (!used)
				return 0;
			errno = EPROTO;
			return -1;
		}
		if (*total_bytes >= SWAPZ_FORMAT_PROC_MAX_BYTES ||
		    used + 1U >= capacity) {
			errno = EOVERFLOW;
			return -1;
		}
		if (character == '\0') {
			errno = EPROTO;
			return -1;
		}
		line[used++] = (char)character;
		++*total_bytes;
		if (character == '\n') {
			line[used] = '\0';
			return 1;
		}
	}
}

/* A bounded contiguous set, sorted only once after the complete snapshot. */
static int format_inventory_append(void **entries, size_t *count,
				   size_t *capacity, const void *entry,
				   size_t entry_size)
{
	if (!entries || !count || !capacity || !entry || !entry_size) {
		errno = EINVAL;
		return -1;
	}
	if (*count >= SWAPZ_FORMAT_PROC_MAX_ROWS) {
		errno = EOVERFLOW;
		return -1;
	}
	if (*count == *capacity) {
		size_t next_capacity = *capacity ? *capacity * 2U : 32U;
		void *extended;

		if (next_capacity > SWAPZ_FORMAT_PROC_MAX_ROWS)
			next_capacity = SWAPZ_FORMAT_PROC_MAX_ROWS;
		if (next_capacity > SIZE_MAX / entry_size) {
			errno = EOVERFLOW;
			return -1;
		}
		extended = realloc(*entries, next_capacity * entry_size);
		if (!extended)
			return -1;
		*entries = extended;
		*capacity = next_capacity;
	}
	memcpy((unsigned char *)*entries + *count * entry_size,
	       entry, entry_size);
	++*count;
	return 0;
}

static int format_mount_identifier_compare(const void *left, const void *right)
{
	const unsigned long long first = *(const unsigned long long *)left;
	const unsigned long long second = *(const unsigned long long *)right;

	return (first > second) - (first < second);
}

struct format_swap_inventory_identity {
	dev_t device;
	ino_t inode;
	int block_entry;
};

static int format_swap_inventory_identity_compare(const void *left,
						   const void *right)
{
	const struct format_swap_inventory_identity *first = left;
	const struct format_swap_inventory_identity *second = right;

	if (first->block_entry != second->block_entry)
		return (first->block_entry > second->block_entry) -
		       (first->block_entry < second->block_entry);
	if (first->device != second->device)
		return (first->device > second->device) -
		       (first->device < second->device);
	return (first->inode > second->inode) -
	       (first->inode < second->inode);
}

static int format_mountinfo_stream_clear(FILE *stream, dev_t device,
					 dev_t parent_device)
{
	char line[SWAPZ_FORMAT_PROC_LINE_BYTES];
	void *mount_identifiers = NULL;
	size_t mount_count = 0;
	size_t mount_capacity = 0;
	size_t total_bytes = 0;
	int read_result;
	int saved_errno;

	if (!stream) {
		errno = EINVAL;
		return -1;
	}
	while ((read_result = format_inventory_read_line(
			stream, line, sizeof(line), &total_bytes)) > 0) {
		dev_t mounted_device;
		unsigned long long mount_identifier;
		const char *identifier_end;

		if (format_mountinfo_line_device(line, &mounted_device) < 0 ||
		    parse_unsigned_decimal(line, (unsigned long long)INT_MAX,
					   &identifier_end, &mount_identifier) < 0 ||
		    !mount_identifier ||
		    (*identifier_end != ' ' && *identifier_end != '\t')) {
			errno = EPROTO;
			goto failed;
		}
		if (format_inventory_device_conflicts(mounted_device, device,
						     parent_device)) {
			errno = EBUSY;
			goto failed;
		}
		if (format_inventory_append(&mount_identifiers,
					    &mount_count, &mount_capacity,
					    &mount_identifier,
					    sizeof(mount_identifier)) < 0)
			goto failed;
	}
	if (read_result < 0)
		goto failed;
	if (!mount_count) {
		errno = EPROTO;
		goto failed;
	}
	qsort(mount_identifiers, mount_count, sizeof(unsigned long long),
	      format_mount_identifier_compare);
	for (size_t index = 1; index < mount_count; ++index) {
		const unsigned long long *sorted = mount_identifiers;

		if (sorted[index] == sorted[index - 1U]) {
			errno = EPROTO;
			goto failed;
		}
	}
	free(mount_identifiers);
	return 0;

failed:
	saved_errno = errno;
	free(mount_identifiers);
	errno = saved_errno;
	return -1;
}

static int format_mountinfo_path_clear(const char *path, dev_t device,
				       dev_t parent_device, int *opened)
{
	FILE *stream;
	int saved_errno;

	if (opened)
		*opened = 0;
	stream = fopen(path, "r");
	if (!stream)
		return -1;
	if (opened)
		*opened = 1;
	if (format_mountinfo_stream_clear(stream, device, parent_device) < 0) {
		saved_errno = errno;
		(void)fclose(stream);
		errno = saved_errno;
		return -1;
	}
	return fclose(stream);
}

static int format_proc_entry_is_pid(const char *name)
{
	const unsigned char *cursor = (const unsigned char *)name;

	if (!cursor || !*cursor)
		return 0;
	for (; *cursor; ++cursor) {
		if (*cursor < '0' || *cursor > '9')
			return 0;
	}
	return 1;
}

/*
 * Linux can return EINVAL for /proc/<pid>/mountinfo after an exiting task has
 * dropped its mount namespace but before its PID entry is reaped. ENOENT/ESRCH
 * can likewise race task exit. Only classify those open failures as harmless
 * after /proc/<pid>/ns/mnt is also proven absent. A present or unreadable
 * namespace keeps the formatter fail-closed.
 */
static int format_proc_mount_namespace_present(const char *proc_path,
					       const char *pid)
{
	char path[PATH_MAX];
	struct stat info;
	int length;

	if (!proc_path || !pid || !format_proc_entry_is_pid(pid)) {
		errno = EINVAL;
		return -1;
	}
	length = snprintf(path, sizeof(path), "%s/%s/ns/mnt", proc_path, pid);
	if (length < 0 || (size_t)length >= sizeof(path)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	if (stat(path, &info) == 0)
		return 1;
	if (errno == ENOENT || errno == ESRCH)
		return 0;
	return -1;
}

static int format_mountinfo_open_failure_ignorable(
	const char *proc_path, const char *pid, int error)
{
	int namespace_present;

	if (error != EINVAL && error != ENOENT && error != ESRCH)
		return 0;
	namespace_present = format_proc_mount_namespace_present(proc_path, pid);
	if (namespace_present < 0)
		return -1;
	return namespace_present == 0;
}

static int format_mount_inventory_clear_from_proc(
	const char *proc_path, dev_t device, dev_t parent_device)
{
	char path[PATH_MAX];
	DIR *directory;
	struct dirent *entry;
	int length;
	int saved_errno = 0;
	size_t pid_tables = 0;

	if (!proc_path) {
		errno = EINVAL;
		return -1;
	}
	length = snprintf(path, sizeof(path), "%s/self/mountinfo", proc_path);
	if (length < 0 || (size_t)length >= sizeof(path)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	if (format_mountinfo_path_clear(path, device, parent_device, NULL) < 0)
		return -1;
	directory = opendir(proc_path);
	if (!directory)
		return -1;
	for (;;) {
		errno = 0;
		entry = readdir(directory);
		if (!entry) {
			saved_errno = errno;
			break;
		}
		if (!format_proc_entry_is_pid(entry->d_name))
			continue;
		if (pid_tables >= SWAPZ_FORMAT_PROC_MAX_PID_TABLES) {
			saved_errno = EOVERFLOW;
			break;
		}
		++pid_tables;
		length = snprintf(path, sizeof(path), "%s/%s/mountinfo",
				  proc_path, entry->d_name);
		if (length < 0 || (size_t)length >= sizeof(path)) {
			saved_errno = ENAMETOOLONG;
			break;
		}
		{
			int mountinfo_opened = 0;

			if (format_mountinfo_path_clear(
				    path, device, parent_device,
				    &mountinfo_opened) < 0) {
				int mountinfo_error = errno;
				int ignorable = 0;

				if (!mountinfo_opened)
					ignorable =
						format_mountinfo_open_failure_ignorable(
							proc_path, entry->d_name,
							mountinfo_error);
				if (ignorable > 0)
					continue;
				saved_errno =
					ignorable < 0 ? errno : mountinfo_error;
				break;
			}
		}
	}
	if (closedir(directory) < 0 && !saved_errno)
		saved_errno = errno;
	if (saved_errno) {
		errno = saved_errno;
		return -1;
	}
	return 0;
}

static int format_mount_inventory_clear(dev_t device, dev_t parent_device)
{
	return format_mount_inventory_clear_from_proc("/proc", device,
						      parent_device);
}

static int format_swap_inventory_header_valid(const char *line)
{
	static const char expected[] =
		"Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n";

	return line && !strcmp(line, expected);
}

/*
 * seq_file_path(..., " \\t\\n\\\\") octal-escapes exactly the bytes
 * that would otherwise break /proc/swaps tokenization. Decode only those
 * kernel escapes and preserve every other non-NUL filename byte verbatim.
 */
static int format_proc_path_decode(const char *begin, const char *end,
				   char path[PATH_MAX])
{
	const char *cursor = begin;
	size_t used = 0;

	if (!begin || !end || !path || begin >= end || *begin != '/')
		return -1;
	while (cursor < end) {
		unsigned char value = (unsigned char)*cursor++;

		if (value == '\\') {
			if (end - cursor < 3 ||
			    cursor[0] < '0' || cursor[0] > '7' ||
			    cursor[1] < '0' || cursor[1] > '7' ||
			    cursor[2] < '0' || cursor[2] > '7')
				return -1;
			value = (unsigned char)(
				((unsigned int)(cursor[0] - '0') << 6) |
				((unsigned int)(cursor[1] - '0') << 3) |
				(unsigned int)(cursor[2] - '0'));
			cursor += 3;
			if (value != ' ' && value != '\t' &&
			    value != '\n' && value != '\\')
				return -1;
		}
		if (value == '\0' || used + 1U >= PATH_MAX)
			return -1;
		path[used++] = (char)value;
	}
	path[used] = '\0';
	return 0;
}

static int format_swap_inventory_entry_parse(const char *line,
					     char swap_path[PATH_MAX],
					     int *block_entry)
{
	const char *field_begin[5];
	const char *field_end[5];
	const char *cursor = line;
	const char *end;
	unsigned long long size_kib;
	unsigned long long used_kib;
	unsigned long long priority_magnitude;
	unsigned long long priority_limit = INT_MAX;
	unsigned int field;
	int negative_priority = 0;

	if (!line || !swap_path || !block_entry)
		return -1;
	for (field = 0U; field < 5U; ++field) {
		while (*cursor == ' ' || *cursor == '\t')
			++cursor;
		if (!*cursor || *cursor == '\n')
			return -1;
		field_begin[field] = cursor;
		while (*cursor && *cursor != ' ' && *cursor != '\t' &&
		       *cursor != '\n')
			++cursor;
		field_end[field] = cursor;
	}
	while (*cursor == ' ' || *cursor == '\t')
		++cursor;
	if (*cursor != '\0' && (*cursor != '\n' || cursor[1] != '\0'))
		return -1;

	if (format_proc_path_decode(field_begin[0], field_end[0],
				    swap_path) < 0)
		return -1;
	if ((size_t)(field_end[1] - field_begin[1]) == sizeof("partition") - 1U &&
	    !memcmp(field_begin[1], "partition", sizeof("partition") - 1U)) {
		*block_entry = 1;
	} else if ((size_t)(field_end[1] - field_begin[1]) ==
			   sizeof("file") - 1U &&
		   !memcmp(field_begin[1], "file", sizeof("file") - 1U)) {
		*block_entry = 0;
	} else {
		return -1;
	}
	if (parse_unsigned_decimal(field_begin[2], (unsigned long long)ULONG_MAX,
				   &end, &size_kib) < 0 ||
	    end != field_end[2] ||
	    parse_unsigned_decimal(field_begin[3], (unsigned long long)ULONG_MAX,
				   &end, &used_kib) < 0 ||
	    end != field_end[3] || !size_kib || used_kib > size_kib)
		return -1;

	cursor = field_begin[4];
	if (*cursor == '-') {
		negative_priority = 1;
		++cursor;
		priority_limit = (unsigned long long)INT_MAX + 1ULL;
		if (cursor == field_end[4])
			return -1;
	} else if (*cursor == '+') {
		return -1;
	}
	if (parse_unsigned_decimal(cursor, priority_limit, &end,
				   &priority_magnitude) < 0 ||
	    end != field_end[4] ||
	    (negative_priority && priority_magnitude == 0ULL))
		return -1;
	return 0;
}

static int format_swap_inventory_stream_clear(FILE *stream, dev_t device,
					      dev_t parent_device)
{
	char line[SWAPZ_FORMAT_PROC_LINE_BYTES];
	void *swap_identities = NULL;
	size_t swap_count = 0;
	size_t swap_capacity = 0;
	size_t total_bytes = 0;
	int saw_header = 0;
	int read_result;
	int saved_errno;

	if (!stream) {
		errno = EINVAL;
		return -1;
	}
	while ((read_result = format_inventory_read_line(
			stream, line, sizeof(line), &total_bytes)) > 0) {
		char swap_path[PATH_MAX];
		struct stat info;
		struct format_swap_inventory_identity identity;
		int block_entry;

		if (!saw_header) {
			if (!format_swap_inventory_header_valid(line)) {
				errno = EPROTO;
				goto failed;
			}
			saw_header = 1;
			continue;
		}
		if (format_swap_inventory_entry_parse(line, swap_path,
						      &block_entry) < 0) {
			errno = EPROTO;
			goto failed;
		}
		/*
		 * The kernel row names the already-open swap object. Refuse a
		 * final-component symlink instead of following a substituted path.
		 */
		if (lstat(swap_path, &info) < 0)
			goto failed;
		if ((block_entry && !S_ISBLK(info.st_mode)) ||
		    (!block_entry && !S_ISREG(info.st_mode))) {
			errno = EPROTO;
			goto failed;
		}
		if (format_swap_entry_conflicts(&info, device, parent_device)) {
			errno = EBUSY;
			goto failed;
		}
		/* Duplicate aliases of the same active swap are ambiguous. */
		identity.device = block_entry ? info.st_rdev : info.st_dev;
		identity.inode = block_entry ? 0 : info.st_ino;
		identity.block_entry = block_entry;
		if (format_inventory_append(&swap_identities,
					    &swap_count, &swap_capacity,
					    &identity, sizeof(identity)) < 0)
			goto failed;
	}
	if (read_result < 0)
		goto failed;
	if (!saw_header) {
		errno = EPROTO;
		goto failed;
	}
	if (swap_count > 1U)
		qsort(swap_identities, swap_count,
		      sizeof(struct format_swap_inventory_identity),
		      format_swap_inventory_identity_compare);
	for (size_t index = 1; index < swap_count; ++index) {
		const struct format_swap_inventory_identity *sorted =
			swap_identities;

		if (!format_swap_inventory_identity_compare(
				&sorted[index - 1U], &sorted[index])) {
			errno = EPROTO;
			goto failed;
		}
	}
	free(swap_identities);
	return 0;

failed:
	saved_errno = errno;
	free(swap_identities);
	errno = saved_errno;
	return -1;
}

static int format_swap_inventory_clear(dev_t device, dev_t parent_device)
{
	FILE *stream = fopen("/proc/swaps", "r");
	int saved_errno;

	if (!stream)
		return -1;
	if (format_swap_inventory_stream_clear(stream, device, parent_device) < 0) {
		saved_errno = errno;
		(void)fclose(stream);
		errno = saved_errno;
		return -1;
	}
	return fclose(stream);
}

static int format_identity_values_match(
	const struct format_expectation *expected,
	const struct stat *path_info,
	const struct stat *opened_info,
	const struct stat *partuuid_info,
	unsigned long long opened_bytes,
	dev_t parent_device)
{
	dev_t expected_device;
	dev_t expected_parent;

	if (!expected || !path_info || !opened_info || !partuuid_info)
		return 0;
	expected_device = makedev(expected->device_major, expected->device_minor);
	expected_parent = makedev(expected->parent_major, expected->parent_minor);
	return S_ISBLK(path_info->st_mode) &&
	       S_ISBLK(opened_info->st_mode) &&
	       S_ISBLK(partuuid_info->st_mode) &&
	       path_info->st_uid == 0 && opened_info->st_uid == 0 &&
	       partuuid_info->st_uid == 0 &&
	       !(path_info->st_mode & S_IWOTH) &&
	       !(opened_info->st_mode & S_IWOTH) &&
	       !(partuuid_info->st_mode & S_IWOTH) &&
	       path_info->st_dev == opened_info->st_dev &&
	       path_info->st_ino == opened_info->st_ino &&
	       path_info->st_rdev == expected_device &&
	       opened_info->st_rdev == expected_device &&
	       partuuid_info->st_rdev == expected_device &&
	       opened_bytes == expected->device_bytes &&
	       parent_device == expected_parent;
}

static int format_partuuid_alias_stat(const char *partuuid, struct stat *info)
{
	char path[PATH_MAX];
	int length;

	if (!partuuid || !info) {
		errno = EINVAL;
		return -1;
	}
	length = snprintf(path, sizeof(path), "/dev/disk/by-partuuid/%s", partuuid);
	if (length < 0 || (size_t)length >= sizeof(path)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	return stat(path, info);
}

static int format_preopen_verify(const char *path,
				 const struct format_expectation *expected)
{
	struct stat path_info;
	struct stat partuuid_info;
	dev_t expected_device;
	dev_t expected_parent;
	dev_t parent_device;

	if (!path || !expected) {
		errno = EINVAL;
		return -1;
	}
	expected_device = makedev(expected->device_major, expected->device_minor);
	expected_parent = makedev(expected->parent_major, expected->parent_minor);
	if (lstat(path, &path_info) < 0 ||
	    format_partuuid_alias_stat(expected->partuuid, &partuuid_info) < 0)
		return -1;
	if (!S_ISBLK(path_info.st_mode) || !S_ISBLK(partuuid_info.st_mode) ||
	    path_info.st_uid != 0 || partuuid_info.st_uid != 0 ||
	    (path_info.st_mode & S_IWOTH) ||
	    (partuuid_info.st_mode & S_IWOTH) ||
	    path_info.st_rdev != expected_device ||
	    partuuid_info.st_rdev != expected_device) {
		errno = ESTALE;
		return -1;
	}
	if (format_sysfs_partuuid_matches(expected_device, expected->partuuid) < 0 ||
	    format_verify_parent_topology(expected_device, expected,
					  &parent_device) < 0)
		return -1;
	if (parent_device != expected_parent) {
		errno = ESTALE;
		return -1;
	}
	if (format_mount_inventory_clear(expected_device, expected_parent) < 0 ||
	    format_swap_inventory_clear(expected_device, expected_parent) < 0)
		return -1;
	return 0;
}

static int format_opened_verify(int fd, const char *path,
				const struct format_expectation *expected)
{
	struct stat path_info;
	struct stat opened_info;
	struct stat partuuid_info;
	unsigned long long opened_bytes = 0;
	dev_t parent_device;
	int opened_read_only = 0;

	if (fd < 0 || !path || !expected) {
		errno = EINVAL;
		return -1;
	}
	if (lstat(path, &path_info) < 0 ||
	    fstat(fd, &opened_info) < 0 ||
	    format_partuuid_alias_stat(expected->partuuid, &partuuid_info) < 0 ||
	    ioctl(fd, BLKGETSIZE64, &opened_bytes) < 0 ||
	    ioctl(fd, BLKROGET, &opened_read_only) < 0 ||
	    format_verify_parent_topology(opened_info.st_rdev, expected,
					  &parent_device) < 0)
		return -1;
	if (opened_read_only) {
		errno = EROFS;
		return -1;
	}
	if (!format_identity_values_match(expected, &path_info, &opened_info,
					  &partuuid_info, opened_bytes,
					  parent_device)) {
		errno = ESTALE;
		return -1;
	}
	if (format_sysfs_partuuid_matches(opened_info.st_rdev,
					 expected->partuuid) < 0 ||
	    format_mount_inventory_clear(opened_info.st_rdev, parent_device) < 0 ||
	    format_swap_inventory_clear(opened_info.st_rdev, parent_device) < 0)
		return -1;
	return 0;
}

struct format_runtime_ops {
	void *context;
	int (*authorized_target_verify)(
		void *context, const struct format_expectation *expected);
	int (*preopen_verify)(void *context, const char *path,
			      const struct format_expectation *expected);
	int (*open_device)(void *context, const char *path);
	int (*verify_opened)(void *context, int fd, const char *path,
			     const struct format_expectation *expected);
	int (*read_header)(void *context, int fd,
			   unsigned char block[SWAPZ_SUPERBLOCK_BYTES]);
	int (*random_bytes)(void *context, unsigned char *bytes, size_t length);
	int (*write_header)(void *context, int fd,
			    const unsigned char block[SWAPZ_SUPERBLOCK_BYTES]);
	int (*sync_device)(void *context, int fd);
	int (*close_device)(void *context, int fd);
};

/*
 * CLI identity assertions alone do not grant access to arbitrary media.
 * Require the matching PARTUUID in the root-owned primary target selector.
 */
static int format_default_authorized_target_verify(
	void *context, const struct format_expectation *expected)
{
	char configured_partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];

	(void)context;
	if (!expected) {
		errno = EINVAL;
		return -1;
	}
	if (swapz_primary_target_config_read(configured_partuuid) < 0)
		return -1;
	if (strcmp(configured_partuuid, expected->partuuid)) {
		errno = EPERM;
		return -1;
	}
	return 0;
}

static int format_default_preopen_verify(
	void *context, const char *path,
	const struct format_expectation *expected)
{
	(void)context;
	return format_preopen_verify(path, expected);
}

static int format_default_open_device(void *context, const char *path)
{
	(void)context;
	/* Reject final-component symlinks; retain exclusive descriptor authority. */
	return open(path, O_RDWR | O_EXCL | O_CLOEXEC | O_NOFOLLOW);
}

static int format_default_verify_opened(
	void *context, int fd, const char *path,
	const struct format_expectation *expected)
{
	(void)context;
	return format_opened_verify(fd, path, expected);
}

static int format_default_read_header(
	void *context, int fd, unsigned char block[SWAPZ_SUPERBLOCK_BYTES])
{
	(void)context;
	return exact_io(fd, block, SWAPZ_SUPERBLOCK_BYTES, 0);
}

static int format_default_random_bytes(void *context, unsigned char *bytes,
				       size_t length)
{
	(void)context;
	return fill_random(bytes, length);
}

static int format_default_write_header(
	void *context, int fd,
	const unsigned char block[SWAPZ_SUPERBLOCK_BYTES])
{
	(void)context;
	return exact_io(fd, (void *)block, SWAPZ_SUPERBLOCK_BYTES, 1);
}

static int format_default_sync_device(void *context, int fd)
{
	(void)context;
	return fsync(fd);
}

static int format_default_close_device(void *context, int fd)
{
	(void)context;
	return close(fd);
}

static void format_report_refusal(const char *stage, int error)
{
	fprintf(stderr, "swapzctl format: REFUSED: %s: %s\n", stage,
		strerror(error ? error : EPERM));
}

static void format_report_uncertain(const char *stage, int error)
{
	fprintf(stderr,
		"swapzctl format: UNCERTAIN: %s: %s; RECOVERY REQUIRED before retry\n",
		stage, strerror(error ? error : EIO));
}

static int format_authorized_opened_verify(
	const struct format_runtime_ops *ops, int fd, const char *path,
	const struct format_expectation *expected)
{
	if (ops->authorized_target_verify(ops->context, expected) < 0)
		return -1;
	return ops->verify_opened(ops->context, fd, path, expected);
}

static int format_device_with_ops(
	const char *path, const struct format_expectation *expected,
	const struct format_runtime_ops *ops)
{
	unsigned char block[SWAPZ_SUPERBLOCK_BYTES];
	unsigned char readback[SWAPZ_SUPERBLOCK_BYTES];
	int already_formatted = 0;
	int publication_attempted = 0;
	int fd = -1;
	int result = 1;
	int saved_errno;

	if (!path || !expected || !ops || !ops->authorized_target_verify ||
	    !ops->preopen_verify ||
	    !ops->open_device || !ops->verify_opened || !ops->read_header ||
	    !ops->random_bytes || !ops->write_header || !ops->sync_device ||
	    !ops->close_device) {
		errno = EINVAL;
		return 1;
	}
	if (ops->authorized_target_verify(ops->context, expected) < 0) {
		saved_errno = errno;
		format_report_refusal("protected target selector does not authorize "
				      "this partition", saved_errno);
		return 2;
	}
	if (ops->preopen_verify(ops->context, path, expected) < 0) {
		saved_errno = errno;
		format_report_refusal("pre-open target identity is not proven",
				      saved_errno);
		return 2;
	}
	fd = ops->open_device(ops->context, path);
	if (fd < 0) {
		perror("swapzctl format: exclusive open");
		return 1;
	}
	if (format_authorized_opened_verify(ops, fd, path, expected) < 0) {
		saved_errno = errno;
		format_report_refusal("opened descriptor identity is not proven",
				      saved_errno);
		result = 2;
		goto close_error;
	}
	if (ops->read_header(ops->context, fd, block) < 0) {
		perror("swapzctl format: read block 0");
		goto close_error;
	}
	if (swapz_sb_valid(block, expected->device_bytes)) {
		already_formatted = 1;
		if (format_authorized_opened_verify(ops, fd, path, expected) < 0) {
			saved_errno = errno;
			format_report_refusal(
				"target identity changed while recognizing existing SWZ header",
				saved_errno);
			result = 2;
			goto close_error;
		}
		goto close_success;
	}
	if (!block_is_zero(block)) {
		fputs("swapzctl format: REFUSED: block 0 is neither zero nor a valid "
		      "SWZ authorization header; RECOVERY REQUIRED before retry\n",
		      stderr);
		result = 2;
		goto close_error;
	}

	memset(block, 0, sizeof(block));
	memcpy(block + SWAPZ_SUPERBLOCK_MAGIC_OFFSET, swapz_superblock_magic,
	       SWAPZ_SUPERBLOCK_MAGIC_BYTES);
	swapz_sb_put_u32(block + SWAPZ_SUPERBLOCK_VERSION_OFFSET,
			 SWAPZ_SUPERBLOCK_VERSION);
	swapz_sb_put_u32(block + SWAPZ_SUPERBLOCK_HEADER_BYTES_OFFSET,
			 SWAPZ_SUPERBLOCK_BYTES);
	swapz_sb_put_u64(block + SWAPZ_SUPERBLOCK_DEVICE_BYTES_OFFSET,
			 expected->device_bytes);
	if (ops->random_bytes(ops->context,
			      block + SWAPZ_SUPERBLOCK_UUID_OFFSET,
			      SWAPZ_SUPERBLOCK_UUID_BYTES) < 0) {
		perror("swapzctl format: getrandom");
		goto close_error;
	}
	block[SWAPZ_SUPERBLOCK_UUID_OFFSET + 6U] =
		(unsigned char)((block[SWAPZ_SUPERBLOCK_UUID_OFFSET + 6U] & 0x0fU) |
				0x40U);
	block[SWAPZ_SUPERBLOCK_UUID_OFFSET + 8U] =
		(unsigned char)((block[SWAPZ_SUPERBLOCK_UUID_OFFSET + 8U] & 0x3fU) |
				0x80U);
	if (!swapz_sb_valid(block, expected->device_bytes)) {
		fputs("swapzctl format: internal SWZ header construction failed\n",
		      stderr);
		errno = EINVAL;
		goto close_error;
	}

	/* This is the last gate before the only destructive operation. */
	if (format_authorized_opened_verify(ops, fd, path, expected) < 0) {
		saved_errno = errno;
		format_report_refusal("target identity changed before header write",
				      saved_errno);
		result = 2;
		goto close_error;
	}
	publication_attempted = 1;
	if (ops->write_header(ops->context, fd, block) < 0) {
		saved_errno = errno;
		format_report_uncertain("header write did not complete",
					saved_errno);
		result = 3;
		goto close_error;
	}
	if (ops->sync_device(ops->context, fd) < 0) {
		saved_errno = errno;
		format_report_uncertain("header durability is not proven",
					saved_errno);
		result = 3;
		goto close_error;
	}
	if (format_authorized_opened_verify(ops, fd, path, expected) < 0) {
		saved_errno = errno;
		format_report_uncertain(
			"target identity became uncertain after header write",
			saved_errno);
		result = 3;
		goto close_error;
	}
	if (ops->read_header(ops->context, fd, readback) < 0) {
		saved_errno = errno;
		format_report_uncertain("header readback could not be verified",
					saved_errno);
		result = 3;
		goto close_error;
	}
	if (memcmp(readback, block, sizeof(block)) ||
	    !swapz_sb_valid(readback, expected->device_bytes)) {
		errno = EIO;
		format_report_uncertain("SWZ header readback mismatch", errno);
		result = 3;
		goto close_error;
	}
	if (format_authorized_opened_verify(ops, fd, path, expected) < 0) {
		saved_errno = errno;
		format_report_uncertain(
			"target identity changed after header verification",
			saved_errno);
		result = 3;
		goto close_error;
	}

close_success:
	if (ops->close_device(ops->context, fd) < 0) {
		saved_errno = errno;
		if (publication_attempted) {
			format_report_uncertain(
				"device close failed after verified header publication",
				saved_errno);
			return 3;
		}
		errno = saved_errno;
		perror("swapzctl format: close");
		return 1;
	}
	if (already_formatted) {
		printf("swapzctl: already formatted SWAPZ device uuid=");
		print_uuid(block + SWAPZ_SUPERBLOCK_UUID_OFFSET);
		printf(" size=%llu\n", expected->device_bytes);
	} else {
		printf("swapzctl: formatted SWAPZ authorization header uuid=");
		print_uuid(block + SWAPZ_SUPERBLOCK_UUID_OFFSET);
		printf(" size=%llu data_start=4096\n", expected->device_bytes);
	}
	return 0;

close_error:
	saved_errno = errno;
	if (fd >= 0 && ops->close_device(ops->context, fd) < 0)
		perror("swapzctl format: close");
	errno = saved_errno;
	return result;
}

static int format_device(const char *path,
			 const struct format_expectation *expected)
{
	static const struct format_runtime_ops ops = {
		.context = NULL,
		.authorized_target_verify = format_default_authorized_target_verify,
		.preopen_verify = format_default_preopen_verify,
		.open_device = format_default_open_device,
		.verify_opened = format_default_verify_opened,
		.read_header = format_default_read_header,
		.random_bytes = format_default_random_bytes,
		.write_header = format_default_write_header,
		.sync_device = format_default_sync_device,
		.close_device = format_default_close_device,
	};

	return format_device_with_ops(path, expected, &ops);
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
	if (argc == 2 && !strcmp(argv[1], "status")) {
		if (stat("/sys/module/dm_swapz", &info) == 0 &&
		    S_ISDIR(info.st_mode)) {
			puts("dm-swapz: loaded (experimental)");
			return status_targets();
		}
		puts("dm-swapz: not loaded (experimental)");
		return 0;
	}
	if (argc == 15 && !strcmp(argv[1], "format") &&
	    !strcmp(argv[3], "--expect-major-minor") &&
	    !strcmp(argv[5], "--expect-bytes") &&
	    !strcmp(argv[7], "--expect-partuuid") &&
	    !strcmp(argv[9], "--expect-parent-major-minor") &&
	    !strcmp(argv[11], "--expect-parent-model") &&
	    !strcmp(argv[13], "--expect-parent-transport")) {
		struct format_expectation expected;

		if (parse_format_expectation(argv[4], argv[10], argv[6], argv[8],
					     &expected) < 0 ||
		    format_parent_expectation(argv[12], argv[14], &expected) < 0) {
			fputs("swapzctl format: BLOCKED: invalid expected partition, "
			      "parent, model, transport, PARTUUID or size\n", stderr);
			return 2;
		}
		return format_device(argv[2], &expected);
	}
	if (argc >= 2 && !strcmp(argv[1], "format")) {
		usage(stderr);
		fputs("swapzctl format: BLOCKED: complete partition and parent "
		      "identity binding is required; no write performed.\n", stderr);
		return 2;
	}

	usage(stderr);
	fputs("BLOCKED: unsupported command; no mapper or swap activation performed.\n",
	      stderr);
	return 2;
}
