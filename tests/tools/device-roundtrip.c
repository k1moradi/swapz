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
#include <time.h>
#include <unistd.h>

enum { PAGE = 4096, NPAGES = 128, GC_PAGES = 4096 };

static uint64_t monotonic_ns(void)
{
	struct timespec now;

	if (clock_gettime(CLOCK_MONOTONIC, &now))
		return 0;
	return (uint64_t)now.tv_sec * UINT64_C(1000000000) +
		(uint64_t)now.tv_nsec;
}

static uint64_t elapsed_ns(uint64_t start, uint64_t end)
{
	return end >= start ? end - start : 0;
}

static int compare_u64(const void *left, const void *right)
{
	uint64_t a = *(const uint64_t *)left;
	uint64_t b = *(const uint64_t *)right;

	return (a > b) - (a < b);
}

static uint64_t p99_ns(uint64_t *samples, unsigned int count)
{
	unsigned int index;

	if (!count)
		return 0;
	qsort(samples, count, sizeof(*samples), compare_u64);
	index = (99U * count + 99U) / 100U - 1U;
	return samples[index];
}

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

static void raw_pattern(unsigned char *p, unsigned int page,
			unsigned int round)
{
	uint32_t s = 0x9e3779b9U ^ (page * 2654435761U) ^
		     (round * 2246822519U);
	unsigned int i;

	for (i = 0; i < PAGE; ++i) {
		s ^= s << 13;
		s ^= s >> 17;
		s ^= s << 5;
		p[i] = (unsigned char)(s >> 8);
	}
	p[PAGE - 8] = (unsigned char)page;
	p[PAGE - 7] = (unsigned char)(page >> 8);
	p[PAGE - 6] = (unsigned char)round;
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

static int series(int fd, unsigned char *buf, unsigned char *expected,
		  unsigned int count, unsigned int round, int write_data,
		  int raw_data)
{
	unsigned int i;

	for (i = 0; i < count; ++i) {
		if (raw_data)
			raw_pattern(expected, i, round);
		else
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

static unsigned int gc_expected_round(unsigned int page,
				      unsigned int rounds)
{
	unsigned int offset = page % 256U;

	return offset < rounds - 1U ? offset : rounds - 1U;
}

static int gc_stress(int fd, unsigned char *buf, unsigned char *expected,
		    unsigned int rounds)
{
	uint64_t *latencies = NULL;
	unsigned int round, page;
	int result = -1;

	if (rounds < 4)
		return -1;
	latencies = calloc(GC_PAGES, sizeof(*latencies));
	if (!latencies)
		return -1;
	for (round = 0; round < rounds; ++round) {
		uint64_t write_wall_ns = 0;
		uint64_t flush_start, flush_wall_ns;
		unsigned int writes = 0;

		for (page = 0; page < GC_PAGES; ++page) {
			uint64_t start, end;

			/*
			 * Preserve a distinct page from every prior generation in
			 * each 1MiB logical stripe: round 1 keeps offset 0, round 2
			 * keeps offsets 0..1, and so on. No earlier generation can
			 * become wholly dead before capacity pressure, so allocator
			 * dead-segment reuse cannot substitute for copying live GC.
			 */
			if (round && (page % 256U) < round)
				continue;
			raw_pattern(expected, page, round);
			start = monotonic_ns();
			if (transfer(fd, expected, page, 1))
				goto out;
			end = monotonic_ns();
			latencies[writes] = elapsed_ns(start, end);
			write_wall_ns += latencies[writes++];
		}
		flush_start = monotonic_ns();
		if (fsync(fd))
			goto out;
		flush_wall_ns = elapsed_ns(flush_start, monotonic_ns());
		printf("GC_PRESSURE_ROUND=%u writes:%u write_wall_ns:%" PRIu64
		       " write_p99_ns:%" PRIu64 " fsync_ns:%" PRIu64 "\n",
		       round, writes, write_wall_ns, p99_ns(latencies, writes),
		       flush_wall_ns);
		fflush(stdout);
	}
	for (page = 0; page < GC_PAGES; ++page) {
		unsigned int expected_round = gc_expected_round(page, rounds);

		raw_pattern(expected, page, expected_round);
		if (transfer(fd, buf, page, 0) ||
		    memcmp(buf, expected, PAGE)) {
			fprintf(stderr,
				"FAIL GC byte-exact page=%u expected_round=%u\n",
				page, expected_round);
			goto out;
		}
	}
	result = 0;
out:
	free(latencies);
	return result;
}

int main(int argc, char **argv)
{
	const char *prefix = "/dev/mapper/swapz-demo-";
	unsigned char *buf = NULL, *expected = NULL;
	int fd = -1, rc = 1, private_mode = 0, write_series = 0;
	int raw_series = 0, discard_pages = 0, gc_mode = 0;
	unsigned int i, phase, count = 0, round = 0, gc_rounds = 0;
	int open_flags = O_RDWR | O_CLOEXEC | O_DIRECT | O_SYNC | O_NOFOLLOW;

	if (argc != 2 && argc != 5 && argc != 4) {
		fprintf(stderr,
			"Usage: device-roundtrip /dev/mapper/swapz-demo-<owned-id> [private series mode]\n");
		return 2;
	}
	if (strncmp(argv[1], prefix, strlen(prefix)) ||
	    strlen(argv[1]) <= strlen(prefix)) {
		fprintf(stderr, "FAIL refusing non-owned mapper path\n");
		return 2;
	}
	if (argc == 4) {
		if (strcmp(argv[2], "--gc-stress") ||
		    parse_uint(argv[3], 8U, &gc_rounds) ||
		    gc_rounds < 4U) {
			fprintf(stderr, "FAIL invalid private GC mode\n");
			return 2;
		}
		gc_mode = 1;
		open_flags &= ~O_SYNC;
	}
	if (argc == 5) {
		if (!strcmp(argv[2], "--write-series"))
			write_series = 1;
		else if (!strcmp(argv[2], "--raw-write-series")) {
			write_series = 1;
			raw_series = 1;
		} else if (!strcmp(argv[2], "--raw-verify-series")) {
			raw_series = 1;
		} else if (!strcmp(argv[2], "--discard-pages")) {
			discard_pages = 1;
		} else if (strcmp(argv[2], "--verify-series")) {
			fprintf(stderr, "FAIL unknown private oracle mode\n");
			return 2;
		}
		if (discard_pages) {
			if (parse_uint(argv[3], GC_PAGES - 1U, &round) ||
			    parse_uint(argv[4], GC_PAGES, &count) || !count ||
			    count > GC_PAGES - round) {
				fprintf(stderr, "FAIL invalid private discard range\n");
				return 2;
			}
		} else if (parse_uint(argv[3], GC_PAGES, &count) || !count ||
			   parse_uint(argv[4], 255U, &round)) {
			fprintf(stderr, "FAIL invalid private count/round\n");
			return 2;
		}
		private_mode = 1;
		/* Deliberately omit O_SYNC here: the lifecycle writer must be
		 * eligible for retention rather than closing through FUA. */
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
		printf("PASS: owned swapz live-GC stress rounds=%u pages=%u\n",
		       gc_rounds, GC_PAGES);
		rc = 0;
		goto out;
	}
	if (private_mode) {
		if (discard_pages) {
			uint64_t range[2] = {
				(uint64_t)round * PAGE,
				(uint64_t)count * PAGE,
			};

			if (ioctl(fd, BLKDISCARD, &range)) {
				perror("FAIL owned swapz BLKDISCARD");
				goto out;
			}
			printf("PASS: owned swapz discard start=%u count=%u\n",
			       round, count);
		} else {
			if (series(fd, buf, expected, count, round,
				   write_series, raw_series))
				goto out;
			printf("PASS: owned swapz direct %s%s series count=%u round=%u\n",
			       raw_series ? "raw-" : "",
			       write_series ? "write" : "verify", count, round);
		}
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
