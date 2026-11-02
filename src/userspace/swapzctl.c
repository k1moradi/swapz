// SPDX-License-Identifier: GPL-2.0-only
/* Explicit swapz administrative tool. It never activates a mapper or swapon. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/fs.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/random.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

#include "../kernel/superblock.h"

#ifndef SWAPZ_VERSION
#define SWAPZ_VERSION "unknown"
#endif

#define SWAPZ_MIN_DATA_BYTES (3ULL * 1024ULL * 1024ULL)

static void usage(FILE *out)
{
	fputs("Usage: swapzctl version | status | format <blockdev> | help\n", out);
	fputs("       swapzctl format <blockdev> --expect-major-minor <major>:<minor> "
	      "--expect-bytes <decimal-bytes>\n", out);
	fputs("format is conservative: block 0 must be all-zero or already SWAPZ.\n",
	      out);
	fputs("No mapper target is created and swap is never enabled by swapzctl.\n",
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
		    S_ISDIR(info.st_mode))
			puts("dm-swapz: loaded (experimental)");
		else
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
