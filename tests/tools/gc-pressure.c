// SPDX-License-Identifier: GPL-2.0-only
/*
 * Bounded owned-device GC pressure oracle.
 *
 * This helper accepts only the test harness's private swapz mapper naming
 * convention and an exact 48MiB block target. It writes deterministic
 * incompressible pages, then overwrites every page except one 4KiB survivor
 * per 1MiB logical stripe. With the harness's 64MiB lower and rotating reserve,
 * that pattern forces copying GC instead of allowing whole old segments to
 * become trivially dead. Every logical page is verified byte-exact afterwards.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/fs.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>

enum {
	PAGE = 4096,
	PAGES_PER_MIB = 256,
	NPAGES = 48 * PAGES_PER_MIB,
};

static void pattern(unsigned char *page, unsigned int logical,
		    unsigned int round)
{
	uint32_t state = UINT32_C(0x9e3779b9) ^
		(logical * UINT32_C(0x85ebca6b)) ^
		(round * UINT32_C(0xc2b2ae35));
	unsigned int i;

	for (i = 0; i < PAGE; ++i) {
		state ^= state << 13;
		state ^= state >> 17;
		state ^= state << 5;
		page[i] = (unsigned char)state;
	}
	/* Prevent accidental equality across phases even on a pathological seed. */
	page[PAGE - 8] = (unsigned char)logical;
	page[PAGE - 7] = (unsigned char)(logical >> 8);
	page[PAGE - 6] = (unsigned char)round;
}

static int transfer(int fd, void *buffer, unsigned int logical, int write_data)
{
	ssize_t count;
	off_t offset = (off_t)logical * PAGE;

	do {
		count = write_data ? pwrite(fd, buffer, PAGE, offset)
				   : pread(fd, buffer, PAGE, offset);
	} while (count < 0 && errno == EINTR);
	if (count != PAGE) {
		fprintf(stderr, "FAIL gc-pressure %s page=%u n=%zd errno=%d\n",
			write_data ? "write" : "read", logical, count, errno);
		return -1;
	}
	return 0;
}

static int validate_owned_device(int fd)
{
	struct stat st;
	uint64_t bytes = 0;

	return fd >= 0 && !fstat(fd, &st) && S_ISBLK(st.st_mode) &&
		!ioctl(fd, BLKGETSIZE64, &bytes) &&
		bytes == UINT64_C(48) * 1024 * 1024 ? 0 : -1;
}

int main(int argc, char **argv)
{
	const char *prefix = "/dev/mapper/swapz-demo-";
	unsigned char *page = NULL, *expected = NULL;
	int fd = -1, rc = 1;
	unsigned int logical;
	int flags = O_RDWR | O_CLOEXEC | O_DIRECT | O_NOFOLLOW;

	if (argc != 2 || strncmp(argv[1], prefix, strlen(prefix)) ||
	    strlen(argv[1]) <= strlen(prefix)) {
		fprintf(stderr, "FAIL refusing non-owned GC-pressure mapper path\n");
		return 2;
	}
	if (posix_memalign((void **)&page, PAGE, PAGE) ||
	    posix_memalign((void **)&expected, PAGE, PAGE)) {
		fprintf(stderr, "FAIL allocating GC-pressure buffers\n");
		goto out;
	}
	fd = open(argv[1], flags);
	if (fd < 0 && errno == ELOOP)
		fd = open(argv[1], flags & ~O_NOFOLLOW);
	if (validate_owned_device(fd)) {
		fprintf(stderr, "FAIL expected owned 48MiB GC-pressure target\n");
		goto out;
	}

	/* Fill 48 logical MiB with RAW-looking pages. The 64MiB lower keeps
	 * only 52MiB foreground capacity after swapz's 12MiB rotating reserve. */
	for (logical = 0; logical < NPAGES; ++logical) {
		pattern(page, logical, 0);
		if (transfer(fd, page, logical, 1))
			goto out;
	}
	if (fsync(fd)) {
		perror("FAIL GC-pressure initial fsync");
		goto out;
	}

	/*
	 * Preserve exactly one old live page in each 1MiB logical stripe while
	 * rewriting every companion. Initial foreground segments therefore stay
	 * partially live and cannot be reclaimed as wholly dead allocator skips.
	 */
	for (logical = 0; logical < NPAGES; ++logical) {
		if (!(logical % PAGES_PER_MIB))
			continue;
		pattern(page, logical, 1);
		if (transfer(fd, page, logical, 1))
			goto out;
	}
	if (fsync(fd)) {
		perror("FAIL GC-pressure overwrite fsync");
		goto out;
	}

	for (logical = 0; logical < NPAGES; ++logical) {
		unsigned int round = logical % PAGES_PER_MIB ? 1U : 0U;

		pattern(expected, logical, round);
		if (transfer(fd, page, logical, 0) ||
		    memcmp(page, expected, PAGE)) {
			fprintf(stderr,
				"FAIL GC-pressure byte-exact page=%u round=%u\n",
				logical, round);
			goto out;
		}
	}

	puts("PASS: owned swapz GC pressure forced partial-live overwrite and byte-exact reread");
	rc = 0;
out:
	if (fd >= 0)
		close(fd);
	free(page);
	free(expected);
	return rc;
}
