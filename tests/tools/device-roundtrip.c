// SPDX-License-Identifier: GPL-2.0-only
/* Small byte-exact smoke oracle for a freshly owned swapz DM test mapping.
 * Never accepts an arbitrary block path, never invokes swapon or partitions.
 * The deployment harness independently verifies DM UUID and null_blk backing.
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

enum { PAGE = 4096, NPAGES = 128, LOGICAL_PAGES = 4096 };

static void pattern(unsigned char *p, unsigned int page, unsigned int round)
{
	uint32_t s = 0x71f12345U ^ (page * 1640531527U) ^ (round * 2246822519U);
	unsigned int i;

	memset(p, 0, PAGE);
	if (round == 1 && page % 16U == 0)
		return;
	switch (page % 4U) {
	case 0:
		break;
	case 1:
		for (i = 0; i < PAGE / 2; i++) {
			s ^= s << 13;
			s ^= s >> 17;
			s ^= s << 5;
			p[i] = (unsigned char)s;
		}
		break;
	case 2:
		for (i = 0; i < PAGE; i++) {
			s ^= s << 13;
			s ^= s >> 17;
			s ^= s << 5;
			p[i] = (unsigned char)s;
		}
		break;
	default:
		for (i = 0; i < PAGE; i++)
			p[i] = (unsigned char)("object=swapz;field=value\n"[i % 24U]);
	}
	p[PAGE - 8] = (unsigned char)page;
	p[PAGE - 7] = (unsigned char)round;
}

static int transfer(int fd, void *buffer, unsigned int page, int write_data)
{
	ssize_t count;
	off_t pos = (off_t)page * PAGE;

	do {
		count = write_data ? pwrite(fd, buffer, PAGE, pos)
				   : pread(fd, buffer, PAGE, pos);
	} while (count == -1 && errno == EINTR);
	if (count != PAGE) {
		fprintf(stderr, "FAIL %s page=%u n=%zd errno=%d\n",
			write_data ? "write" : "read", page, count, errno);
		return -1;
	}
	return 0;
}

static int parse_uint(const char *text, unsigned int maximum,
		      unsigned int *value)
{
	char *end = NULL;
	unsigned long parsed;

	errno = 0;
	parsed = strtoul(text, &end, 10);
	if (errno || !text[0] || !end || *end || parsed > maximum)
		return -1;
	*value = (unsigned int)parsed;
	return 0;
}

static int validate_owned_device(int fd)
{
	struct stat st;
	uint64_t size = 0;

	return fd >= 0 && !fstat(fd, &st) && S_ISBLK(st.st_mode) &&
		!ioctl(fd, BLKGETSIZE64, &size) &&
		size == UINT64_C(16) * 1024 * 1024 ? 0 : -1;
}

static int gc_stress(int fd, unsigned char *buf, unsigned char *expected,
		     unsigned int rounds)
{
	unsigned char *latest = NULL;
	unsigned int page, round;

	latest = calloc(LOGICAL_PAGES, sizeof(*latest));
	if (!latest)
		return -1;
	/*
	 * Populate the full 16MiB logical target first. Subsequent deterministic
	 * scattered half-page overwrites keep live survivors distributed across
	 * old physical segments instead of manufacturing trivially dead segments.
	 * This is a bounded loaded GC oracle, not a performance benchmark.
	 */
	for (page = 0; page < LOGICAL_PAGES; ++page) {
		pattern(expected, page, 1);
		if (transfer(fd, expected, page, 1))
			goto fail;
		latest[page] = 1;
	}
	for (round = 2; round < rounds + 2; ++round) {
		for (page = 0; page < LOGICAL_PAGES; ++page) {
			uint32_t mix = (uint32_t)page * 2654435761U ^
				       (uint32_t)round * 2246822519U;

			mix ^= mix >> 16;
			mix *= 0x7feb352dU;
			mix ^= mix >> 15;
			if (mix & 1U)
				continue;
			pattern(expected, page, round);
			if (transfer(fd, expected, page, 1))
				goto fail;
			latest[page] = (unsigned char)round;
		}
	}
	if (fsync(fd))
		goto fail;
	for (page = 0; page < LOGICAL_PAGES; ++page) {
		pattern(expected, page, latest[page]);
		if (transfer(fd, buf, page, 0) || memcmp(buf, expected, PAGE)) {
			fprintf(stderr, "FAIL GC byte-exact page=%u round=%u\n",
				page, latest[page]);
			goto fail;
		}
	}
	free(latest);
	return 0;
fail:
	free(latest);
	return -1;
}

static int series(int fd, unsigned char *buf, unsigned char *expected,
		  unsigned int count, unsigned int round, int write_data)
{
	unsigned int i;

	for (i = 0; i < count; ++i) {
		pattern(expected, i, round);
		if (write_data) {
			if (transfer(fd, expected, i, 1))
				return -1;
		} else if (transfer(fd, buf, i, 0) ||
			   memcmp(buf, expected, PAGE)) {
			fprintf(stderr, "FAIL byte-exact page=%u round=%u\n",
				i, round);
			return -1;
		}
	}
	return 0;
}

int main(int argc, char **argv)
{
	const char *prefix = "/dev/mapper/swapz-demo-";
	unsigned char *buf = NULL, *expected = NULL;
	int fd = -1, rc = 1, private_mode = 0, write_series = 0, gc_mode = 0;
	unsigned int i, phase, count = 0, round = 0, gc_rounds = 0;
	int open_flags = O_RDWR | O_CLOEXEC | O_DIRECT | O_SYNC | O_NOFOLLOW;

	if (argc != 2 && argc != 4 && argc != 5) {
		fprintf(stderr,
			"Usage: device-roundtrip /dev/mapper/swapz-demo-<owned-id> [private series|GC mode]\n");
		return 2;
	}
	if (strncmp(argv[1], prefix, strlen(prefix)) ||
	    strlen(argv[1]) <= strlen(prefix)) {
		fprintf(stderr, "FAIL refusing non-owned mapper path\n");
		return 2;
	}
	if (argc == 5) {
		if (!strcmp(argv[2], "--write-series"))
			write_series = 1;
		else if (strcmp(argv[2], "--verify-series")) {
			fprintf(stderr, "FAIL unknown private oracle mode\n");
			return 2;
		}
		if (parse_uint(argv[3], NPAGES, &count) || !count ||
		    parse_uint(argv[4], 255U, &round)) {
			fprintf(stderr, "FAIL invalid private count/round\n");
			return 2;
		}
		private_mode = 1;
		/* Deliberately omit O_SYNC here: the lifecycle writer must be
		 * eligible for retention rather than closing through FUA. */
		open_flags &= ~O_SYNC;
	} else if (argc == 4) {
		if (strcmp(argv[2], "--gc-stress") ||
		    parse_uint(argv[3], 96U, &gc_rounds) ||
		    gc_rounds < 8U || gc_rounds > 96U) {
			fprintf(stderr, "FAIL invalid private GC mode\n");
			return 2;
		}
		gc_mode = 1;
		open_flags &= ~O_SYNC;
	}
	if (posix_memalign((void **)&buf, PAGE, PAGE) ||
	    posix_memalign((void **)&expected, PAGE, PAGE)) {
		fprintf(stderr, "FAIL allocating aligned test buffers\n");
		goto out;
	}
	fd = open(argv[1], open_flags);
	if (fd < 0 && errno == ELOOP)
		fd = open(argv[1], open_flags & ~O_NOFOLLOW);
	if (validate_owned_device(fd)) {
		fprintf(stderr, "FAIL expected owned 16MiB DM block target\n");
		goto out;
	}

	if (gc_mode) {
		if (gc_stress(fd, buf, expected, gc_rounds))
			goto out;
		printf("PASS: owned swapz live GC stress rounds=%u logical_pages=%u\n",
		       gc_rounds, LOGICAL_PAGES);
		rc = 0;
		goto out;
	}
	if (private_mode) {
		if (series(fd, buf, expected, count, round, write_series))
			goto out;
		printf("PASS: owned swapz direct %s series count=%u round=%u\n",
		       write_series ? "write" : "verify", count, round);
		rc = 0;
		goto out;
	}

	for (i = 0; i < NPAGES; i++) {
		pattern(buf, i, 0);
		if (transfer(fd, buf, i, 1))
			goto out;
	}
	if (fsync(fd)) {
		perror("FAIL initial flush");
		goto out;
	}
	for (phase = 0; phase < 2; phase++) {
		if (phase) {
			for (i = 0; i < NPAGES; i += 2) {
				pattern(buf, i, 1);
				if (transfer(fd, buf, i, 1))
					goto out;
			}
			if (fsync(fd)) {
				perror("FAIL overwrite flush");
				goto out;
			}
		}
		for (i = 0; i < NPAGES; i++) {
			pattern(expected, i, phase && !(i % 2U));
			if (transfer(fd, buf, i, 0) ||
			    memcmp(buf, expected, PAGE)) {
				fprintf(stderr, "FAIL byte-exact page=%u pass=%u\n",
					i, phase);
				goto out;
			}
		}
	}
	puts("PASS: owned V3 DM 128-page direct I/O, flush, full readback, overwrite");
	rc = 0;
out:
	if (fd >= 0)
		close(fd);
	free(buf);
	free(expected);
	return rc;
}
