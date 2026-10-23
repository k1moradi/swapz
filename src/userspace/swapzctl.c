// SPDX-License-Identifier: GPL-2.0-only
/* Explicit swapz administrative tool. It never activates a mapper or swapon. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/fs.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/random.h>
#include <sys/stat.h>
#include <unistd.h>

#include "../kernel/superblock.h"

#ifndef SWAPZ_VERSION
#define SWAPZ_VERSION "unknown"
#endif

#define SWAPZ_MIN_DATA_BYTES (3ULL * 1024ULL * 1024ULL)

static void usage(FILE *out)
{
	fputs("Usage: swapzctl version | status | format <blockdev> | help\n", out);
	fputs("format is conservative: block 0 must be all-zero or already SWAPZ.\n",
	      out);
	fputs("No mapper target is created and swap is never enabled by swapzctl.\n",
	      out);
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

static int format_device(const char *path)
{
	unsigned char block[SWAPZ_SUPERBLOCK_BYTES];
	unsigned long long device_bytes = 0;
	struct stat info;
	int fd;

	if (stat(path, &info) < 0) {
		perror("swapzctl format: stat");
		return 1;
	}
	if (!S_ISBLK(info.st_mode)) {
		fprintf(stderr, "swapzctl format: %s is not a block device\n", path);
		return 2;
	}
	fd = open(path, O_RDWR | O_EXCL | O_CLOEXEC);
	if (fd < 0) {
		perror("swapzctl format: exclusive open");
		return 1;
	}
	if (ioctl(fd, BLKGETSIZE64, &device_bytes) < 0) {
		perror("swapzctl format: BLKGETSIZE64");
		close(fd);
		return 1;
	}
	if (device_bytes < SWAPZ_SUPERBLOCK_BYTES + SWAPZ_MIN_DATA_BYTES) {
		fprintf(stderr, "swapzctl format: device is too small\n");
		close(fd);
		return 2;
	}
	if (exact_io(fd, block, sizeof(block), 0) < 0) {
		perror("swapzctl format: read block 0");
		close(fd);
		return 1;
	}
	if (swapz_sb_valid(block, device_bytes)) {
		printf("swapzctl: already formatted SWAPZ device uuid=");
		print_uuid(block + SWAPZ_SUPERBLOCK_UUID_OFFSET);
		printf(" size=%llu\n", device_bytes);
		close(fd);
		return 0;
	}
	if (!block_is_zero(block)) {
		fputs("swapzctl format: REFUSED: block 0 contains nonzero data; "
		      "use a dedicated zeroed device/partition\n", stderr);
		close(fd);
		return 2;
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
		close(fd);
		return 1;
	}
	block[SWAPZ_SUPERBLOCK_UUID_OFFSET + 6U] =
		(unsigned char)((block[SWAPZ_SUPERBLOCK_UUID_OFFSET + 6U] & 0x0fU) |
				0x40U);
	block[SWAPZ_SUPERBLOCK_UUID_OFFSET + 8U] =
		(unsigned char)((block[SWAPZ_SUPERBLOCK_UUID_OFFSET + 8U] & 0x3fU) |
				0x80U);

	if (exact_io(fd, block, sizeof(block), 1) < 0 || fsync(fd) < 0) {
		perror("swapzctl format: write header");
		close(fd);
		return 1;
	}
	if (close(fd) < 0) {
		perror("swapzctl format: close");
		return 1;
	}
	printf("swapzctl: formatted SWAPZ authorization header uuid=");
	print_uuid(block + SWAPZ_SUPERBLOCK_UUID_OFFSET);
	printf(" size=%llu data_start=4096\n", device_bytes);
	return 0;
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
		return format_device(argv[2]);

	usage(stderr);
	fputs("BLOCKED: unsupported command; no mapper or swap activation performed.\n",
	      stderr);
	return 2;
}
