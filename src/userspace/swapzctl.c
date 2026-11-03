// SPDX-License-Identifier: GPL-2.0-only
/* Explicit swapz administrative tool. It never activates a mapper or swapon. */
#define _GNU_SOURCE
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

static void usage(FILE *out)
{
	fputs("Usage: swapzctl version | status | format <blockdev> | help\n", out);
	fputs("       swapzctl primary plan|prepare|start|stop|recover\n", out);
	fputs("       swapzctl format <blockdev> --expect-major-minor <major>:<minor> "
	      "--expect-bytes <decimal-bytes>\n", out);
	fputs("status reports cumulative committed foreground compression ratios "
	      "for active swapz targets.\n", out);
	fputs("format is conservative: block 0 must be all-zero or already SWAPZ.\n",
	      out);
	fputs("Primary-swap lifecycle commands remain disabled until separately "
	      "qualified.\n", out);
	fputs("The format command creates no mapper target and never enables swap.\n",
	      out);
}

struct format_expectation {
	unsigned int device_major;
	unsigned int device_minor;
	unsigned long long device_bytes;
};

/* Parse unsigned decimal without accepting signs, whitespace or overflow. */
static int parse_unsigned_decimal(const char *text, unsigned long long limit,
				  const char **end, unsigned long long *value)
{
	const char *cursor = text;
	unsigned long long parsed = 0;

	if (*cursor < '0' || *cursor > '9')
		return -1;
	while (*cursor >= '0' && *cursor <= '9') {
		unsigned int digit = (unsigned int)(*cursor - '0');

		if (parsed > (limit - digit) / 10ULL)
			return -1;
		parsed = parsed * 10ULL + digit;
		++cursor;
	}
	*end = cursor;
	*value = parsed;
	return 0;
}

static int parse_format_expectation(const char *identity, const char *bytes,
				    struct format_expectation *expected)
{
	const char *end;
	unsigned long long device_major;
	unsigned long long device_minor;
	dev_t expected_device;

	if (parse_unsigned_decimal(identity, UINT_MAX, &end, &device_major) < 0 ||
	    *end != ':' ||
	    parse_unsigned_decimal(end + 1, UINT_MAX, &end, &device_minor) < 0 ||
	    *end != '\0' ||
	    parse_unsigned_decimal(bytes, ULLONG_MAX, &end,
				   &expected->device_bytes) < 0 ||
	    *end != '\0')
		return -1;

	expected->device_major = (unsigned int)device_major;
	expected->device_minor = (unsigned int)device_minor;
	/* Reject numbers not round-trippable through the platform's dev_t. */
	expected_device = makedev(expected->device_major, expected->device_minor);
	if (major(expected_device) != expected->device_major ||
	    minor(expected_device) != expected->device_minor)
		return -1;
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

	while (done < length) {
		ssize_t count = write_io ?
			pwrite(fd, bytes + done, length - done, (off_t)done) :
			pread(fd, bytes + done, length - done, (off_t)done);

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

static int format_device(const char *path,
			 const struct format_expectation *expected)
{
	unsigned char block[SWAPZ_SUPERBLOCK_BYTES];
	unsigned long long device_bytes = 0;
	struct stat inspected_info;
	struct stat opened_info;
	int already_formatted = 0;
	int result = 1;
	int fd;

	if (stat(path, &inspected_info) < 0) {
		perror("swapzctl format: stat");
		return 1;
	}
	if (!S_ISBLK(inspected_info.st_mode)) {
		fprintf(stderr, "swapzctl format: %s is not a block device\n", path);
		return 2;
	}
	fd = open(path, O_RDWR | O_EXCL | O_CLOEXEC);
	if (fd < 0) {
		perror("swapzctl format: exclusive open");
		return 1;
	}
	/* The opened descriptor, not the path, is the authority for block-zero I/O. */
	if (fstat(fd, &opened_info) < 0) {
		perror("swapzctl format: fstat");
		goto close_error;
	}
	if (!S_ISBLK(opened_info.st_mode) ||
	    opened_info.st_rdev != inspected_info.st_rdev) {
		fputs("swapzctl format: REFUSED: opened device identity changed\n",
		      stderr);
		result = 2;
		goto close_error;
	}
	if (expected &&
	    (major(opened_info.st_rdev) != expected->device_major ||
	     minor(opened_info.st_rdev) != expected->device_minor)) {
		fputs("swapzctl format: REFUSED: device major:minor mismatch\n",
		      stderr);
		result = 2;
		goto close_error;
	}
	if (ioctl(fd, BLKGETSIZE64, &device_bytes) < 0) {
		perror("swapzctl format: BLKGETSIZE64");
		goto close_error;
	}
	if (expected && device_bytes != expected->device_bytes) {
		fputs("swapzctl format: REFUSED: device size mismatch\n", stderr);
		result = 2;
		goto close_error;
	}
	if (device_bytes < SWAPZ_SUPERBLOCK_BYTES + SWAPZ_MIN_DATA_BYTES) {
		fprintf(stderr, "swapzctl format: device is too small\n");
		result = 2;
		goto close_error;
	}
	/* No block-zero read or write occurs until all FD checks have passed. */
	if (exact_io(fd, block, sizeof(block), 0) < 0) {
		perror("swapzctl format: read block 0");
		goto close_error;
	}
	if (swapz_sb_valid(block, device_bytes)) {
		already_formatted = 1;
		goto close_success;
	}
	if (!block_is_zero(block)) {
		fputs("swapzctl format: REFUSED: block 0 contains nonzero data; "
		      "use a dedicated zeroed device/partition\n", stderr);
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
			 device_bytes);
	if (fill_random(block + SWAPZ_SUPERBLOCK_UUID_OFFSET,
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

	if (exact_io(fd, block, sizeof(block), 1) < 0) {
		perror("swapzctl format: write header");
		goto close_error;
	}
	if (fsync(fd) < 0) {
		perror("swapzctl format: fsync header");
		goto close_error;
	}

close_success:
	if (close(fd) < 0) {
		perror("swapzctl format: close");
		return 1;
	}
	if (already_formatted) {
		printf("swapzctl: already formatted SWAPZ device uuid=");
		print_uuid(block + SWAPZ_SUPERBLOCK_UUID_OFFSET);
		printf(" size=%llu\n", device_bytes);
	} else {
		printf("swapzctl: formatted SWAPZ authorization header uuid=");
		print_uuid(block + SWAPZ_SUPERBLOCK_UUID_OFFSET);
		printf(" size=%llu data_start=4096\n", device_bytes);
	}
	return 0;

close_error:
	if (close(fd) < 0)
		perror("swapzctl format: close");
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
	if (argc == 2 && !strcmp(argv[1], "status")) {
		if (stat("/sys/module/dm_swapz", &info) == 0 &&
		    S_ISDIR(info.st_mode)) {
			puts("dm-swapz: loaded (experimental)");
			return status_targets();
		}
		puts("dm-swapz: not loaded (experimental)");
		return 0;
	}
	if (argc == 3 && !strcmp(argv[1], "format"))
		return format_device(argv[2], NULL);
	if (argc == 7 && !strcmp(argv[1], "format") &&
	    !strcmp(argv[3], "--expect-major-minor") &&
	    !strcmp(argv[5], "--expect-bytes")) {
		struct format_expectation expected;

		if (parse_format_expectation(argv[4], argv[6], &expected) < 0) {
			fputs("swapzctl format: BLOCKED: invalid expected identity or size\n",
			      stderr);
			return 2;
		}
		return format_device(argv[2], &expected);
	}

	usage(stderr);
	fputs("BLOCKED: unsupported command; no mapper or swap activation performed.\n",
	      stderr);
	return 2;
}
