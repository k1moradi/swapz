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
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/uio.h>
#include <time.h>
#include <unistd.h>

#define PHYSICAL_DM_UUID_PREFIX "SWAPZ-TEST-PHYSICAL-"
#define OWNED_DM_UUID_PREFIX "SWAPZ-TEST-"

enum {
	PHYSICAL_DM_UUID_TOKEN_LENGTH = 16,
	PAGE = 4096,
	NPAGES = 128,
	GC_PAGES = 4096,
	CHURN_LOGICAL_PAGES = 4096,
	CHURN_SEED_PAGES = 2867,
	CHURN_COLD_PAGES = 2294,
	CHURN_HOT_PAGES = 573,
	CHURN_HOT_WRITES = 40960,
	GC_RECOVERY_LOGICAL_PAGES = 512,
	GC_RECOVERY_FOREGROUND_WRITES = 768,
	GC_RECOVERY_FAULT_WRITE = 769,
	MAX_CAPACITY_LOGICAL_PAGES = 3727616U,
	CHURN_FSYNC_INTERVAL = 256
};

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

/*
 * Production delta64+DELTA64_SHUF8+LZ4 positive control, mirroring the
 * anon-page-fixture delta64 profile: a high-entropy 64-bit start value with
 * nonzero adjacent deltas <= 256. Ordinary LZ4 sees roughly 2.3KiB, while the
 * page-local delta64 transform exposes narrow deltas that the classifier and
 * rescue adopt. Correctness smoke only; never an off/on benchmark.
 */
static void delta64_pattern(unsigned char *p, unsigned int page,
			    unsigned int round)
{
	uint32_t s = 0x2545f491U ^ (page * 2654435761U) ^
		     (round * 2246822519U);
	uint64_t value;
	unsigned int slot;

	s ^= s << 13; s ^= s >> 17; s ^= s << 5;
	value = (uint64_t)s << 32;
	s ^= s << 13; s ^= s >> 17; s ^= s << 5;
	value |= s;
	for (slot = 0; slot < PAGE / 8U; ++slot) {
		s ^= s << 13;
		s ^= s >> 17;
		s ^= s << 5;
		value += 1U + (s & 0xffU);
		memcpy(p + (size_t)slot * 8U, &value, sizeof(value));
	}
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

static int transfer_segmented(int fd, unsigned char *buffer, unsigned int page,
			      int write_data)
{
	struct iovec iov[4];
	int iovcnt;
	ssize_t count;
	off_t pos = (off_t)page * PAGE;
	unsigned int mode = page % 5U;

	switch (mode) {
	case 0:
		iov[0].iov_base = buffer;
		iov[0].iov_len = 2048;
		iov[1].iov_base = buffer + 2048;
		iov[1].iov_len = 2048;
		iovcnt = 2;
		break;
	case 1:
		iov[0].iov_base = buffer;
		iov[0].iov_len = 1024;
		iov[1].iov_base = buffer + 1024;
		iov[1].iov_len = 3072;
		iovcnt = 2;
		break;
	case 2:
		iov[0].iov_base = buffer;
		iov[0].iov_len = 512;
		iov[1].iov_base = buffer + 512;
		iov[1].iov_len = 1536;
		iov[2].iov_base = buffer + 2048;
		iov[2].iov_len = 2048;
		iovcnt = 3;
		break;
	case 3:
		iov[0].iov_base = buffer;
		iov[0].iov_len = 1024;
		iov[1].iov_base = buffer + 1024;
		iov[1].iov_len = 1024;
		iov[2].iov_base = buffer + 2048;
		iov[2].iov_len = 1024;
		iov[3].iov_base = buffer + 3072;
		iov[3].iov_len = 1024;
		iovcnt = 4;
		break;
	default:
		/* Non-zero bv_offset within page: buffer + 512 */
		iov[0].iov_base = buffer + 512;
		iov[0].iov_len = 3584;
		iov[1].iov_base = buffer + 4096;
		iov[1].iov_len = 512;
		iovcnt = 2;
		break;
	}

	do {
		count = write_data ? pwritev(fd, iov, iovcnt, pos)
				   : preadv(fd, iov, iovcnt, pos);
	} while (count == -1 && errno == EINTR);
	if (count != PAGE) {
		fprintf(stderr, "FAIL %s-segmented page=%u n=%zd errno=%d\n",
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

static int validate_owned_device(int fd, dev_t *opened_device,
				uint64_t expected_size)
{
	struct stat st;
	uint64_t size = 0;

	if (fd < 0 || fstat(fd, &st) || !S_ISBLK(st.st_mode) ||
	    ioctl(fd, BLKGETSIZE64, &size) ||
	    size != expected_size)
		return -1;
	*opened_device = st.st_rdev;
	return 0;
}

static int valid_owned_dm_uuid(const char *uuid)
{
	const size_t prefix_length = sizeof(OWNED_DM_UUID_PREFIX) - 1U;
	size_t index;

	if (strnlen(uuid, prefix_length + PHYSICAL_DM_UUID_TOKEN_LENGTH + 1U) !=
	    prefix_length + PHYSICAL_DM_UUID_TOKEN_LENGTH ||
	    memcmp(uuid, OWNED_DM_UUID_PREFIX, prefix_length))
		return 0;
	for (index = prefix_length;
	     index < prefix_length + PHYSICAL_DM_UUID_TOKEN_LENGTH; ++index) {
		if ((uuid[index] < '0' || uuid[index] > '9') &&
		    (uuid[index] < 'a' || uuid[index] > 'f'))
			return 0;
	}
	return 1;
}

static int verify_dm_uuid_exact(dev_t opened_device, const char *expected_uuid)
{
	char sysfs_path[128];
	char reported_uuid[96];
	size_t expected_length = strlen(expected_uuid);
	size_t total_bytes = 0;
	int sysfs_fd = -1, result = -1;
	int path_length;

	if (!expected_length || expected_length + 1U >= sizeof(reported_uuid))
		return -1;
	path_length = snprintf(sysfs_path, sizeof(sysfs_path),
			       "/sys/dev/block/%u:%u/dm/uuid",
			       major(opened_device), minor(opened_device));
	if (path_length < 0 || (size_t)path_length >= sizeof(sysfs_path))
		return -1;
	sysfs_fd = open(sysfs_path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
	if (sysfs_fd < 0)
		return -1;
	while (total_bytes < sizeof(reported_uuid)) {
		ssize_t read_bytes = read(sysfs_fd, reported_uuid + total_bytes,
					  sizeof(reported_uuid) - total_bytes);

		if (read_bytes < 0) {
			if (errno == EINTR)
				continue;
			goto out;
		}
		if (!read_bytes)
			break;
		total_bytes += (size_t)read_bytes;
	}
	if (total_bytes == expected_length + 1U &&
	    reported_uuid[total_bytes - 1U] == '\n' &&
	    !memcmp(reported_uuid, expected_uuid, expected_length))
		result = 0;
out:
	if (close(sysfs_fd))
		return -1;
	return result;
}

/*
 * Physical-smoke metadata is trusted only after checking the actual opened
 * block descriptor. The helper-generated UUID has a fixed, lowercase token.
 */
static int valid_physical_dm_uuid(const char *uuid)
{
	const size_t prefix_length = sizeof(PHYSICAL_DM_UUID_PREFIX) - 1U;
	const size_t uuid_length = prefix_length + PHYSICAL_DM_UUID_TOKEN_LENGTH;
	size_t index;

	if (strnlen(uuid, uuid_length + 1U) != uuid_length ||
	    memcmp(uuid, PHYSICAL_DM_UUID_PREFIX, prefix_length))
		return 0;
	for (index = prefix_length;
	     index < prefix_length + PHYSICAL_DM_UUID_TOKEN_LENGTH; ++index) {
		if ((uuid[index] < '0' || uuid[index] > '9') &&
		    (uuid[index] < 'a' || uuid[index] > 'f'))
			return 0;
	}
	return 1;
}

static int verify_physical_dm_uuid(dev_t opened_device, const char *expected_uuid)
{
	const size_t expected_uuid_length =
		sizeof(PHYSICAL_DM_UUID_PREFIX) - 1U +
		PHYSICAL_DM_UUID_TOKEN_LENGTH;
	char sysfs_path[128];
	/* One extra byte beyond "<expected UUID>\n" proves exact EOF. */
	char reported_uuid[sizeof(PHYSICAL_DM_UUID_PREFIX) +
			   PHYSICAL_DM_UUID_TOKEN_LENGTH + 1U];
	size_t total_bytes = 0;
	int sysfs_fd = -1, result = -1;
	int path_length;

	path_length = snprintf(sysfs_path, sizeof(sysfs_path),
			       "/sys/dev/block/%u:%u/dm/uuid",
			       major(opened_device), minor(opened_device));
	if (path_length < 0 || (size_t)path_length >= sizeof(sysfs_path))
		return -1;
	sysfs_fd = open(sysfs_path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
	if (sysfs_fd < 0)
		return -1;
	while (total_bytes < sizeof(reported_uuid)) {
		ssize_t read_bytes = read(sysfs_fd, reported_uuid + total_bytes,
					  sizeof(reported_uuid) - total_bytes);

		if (read_bytes < 0) {
			if (errno == EINTR)
				continue;
			goto out;
		}
		if (!read_bytes)
			break;
		total_bytes += (size_t)read_bytes;
	}
	if (total_bytes == expected_uuid_length + 1U &&
	    reported_uuid[total_bytes - 1U] == '\n' &&
	    !memcmp(reported_uuid, expected_uuid, expected_uuid_length))
		result = 0;
out:
	if (close(sysfs_fd))
		return -1;
	return result;
}

static int series(int fd, unsigned char *buf, unsigned char *expected,
		  unsigned int count, unsigned int round, int write_data,
		  int raw_data)
{
	unsigned int i;

	for (i = 0; i < count; ++i) {
		if (raw_data == 2)
			delta64_pattern(expected, i, round);
		else if (raw_data)
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

static int maximum_capacity_boundary_roundtrip(int fd, unsigned char *buf,
					       unsigned char *expected)
{
	const unsigned int pages[] = {
		0U,
		MAX_CAPACITY_LOGICAL_PAGES - 1U,
	};
	size_t index;

	for (index = 0; index < sizeof(pages) / sizeof(pages[0]); ++index) {
		raw_pattern(expected, pages[index], 0U);
		if (transfer(fd, expected, pages[index], 1))
			return -1;
	}
	if (fsync(fd)) {
		perror("FAIL maximum-capacity boundary fsync");
		return -1;
	}
	for (index = 0; index < sizeof(pages) / sizeof(pages[0]); ++index) {
		raw_pattern(expected, pages[index], 0U);
		if (transfer(fd, buf, pages[index], 0) ||
		    memcmp(buf, expected, PAGE)) {
			fprintf(stderr,
				"FAIL maximum-capacity boundary byte-exact page=%u\n",
				pages[index]);
			return -1;
		}
	}
	return 0;
}

/* Correctness-only persistent writers; each lane owns disjoint logical pages. */
struct parallel_writer {
	int fd;
	unsigned int lane, count, round;
	unsigned char *page;
	int error;
};

static void *parallel_writer_main(void *argument)
{
	struct parallel_writer *writer = argument;
	unsigned int round, page;

	for (round = 0; round <= writer->round; ++round)
		for (page = writer->lane; page < writer->count; page += 32U) {
			pattern(writer->page, page, round);
			if (transfer(writer->fd, writer->page, page, 1)) {
				writer->error = 1;
				return NULL;
			}
		}
	return NULL;
}

static int parallel_series(int fd, unsigned int count, unsigned int round)
{
	struct parallel_writer writers[32] = {0};
	pthread_t threads[32];
	unsigned int lane, started = 0;
	int error = 0;

	if (count < 32U || count % 32U)
		return -1;
	for (lane = 0; lane < 32U; ++lane) {
		writers[lane].fd = fd;
		writers[lane].lane = lane;
		writers[lane].count = count;
		writers[lane].round = round;
		if (posix_memalign((void **)&writers[lane].page, PAGE, PAGE)) {
			error = 1;
			goto out;
		}
	}
	for (lane = 0; lane < 32U; ++lane) {
		if (pthread_create(&threads[lane], NULL, parallel_writer_main,
				   &writers[lane])) {
			error = 1;
			break;
		}
		started++;
	}
	for (lane = 0; lane < started; ++lane) {
		if (pthread_join(threads[lane], NULL)) {
			fprintf(stderr, "FAIL joining private parallel writer\n");
			_exit(2);
		}
		if (writers[lane].error)
			error = 1;
	}
	if (!error && fsync(fd))
		error = 1;
out:
	for (lane = 0; lane < 32U; ++lane)
		free(writers[lane].page);
	return error ? -1 : 0;
}

#ifndef MADV_HUGEPAGE
#define MADV_HUGEPAGE 14
#endif
#ifndef MADV_COLLAPSE
#define MADV_COLLAPSE 25
#endif

static int series_thp(int fd, unsigned char *expected,
		      unsigned int count, unsigned int round,
		      int write_data)
{
	size_t thp_size = 2U * 1024U * 1024U;
	size_t map_size = 2U * thp_size;
	unsigned char *thp_map;
	unsigned char *thp_buf;
	uintptr_t aligned_addr;
	unsigned int i;

	thp_map = mmap(NULL, map_size, PROT_READ | PROT_WRITE,
		       MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
	if (thp_map == MAP_FAILED) {
		perror("mmap THP buffer");
		return -1;
	}
	/* MADV_COLLAPSE needs a complete, PMD-aligned anonymous range. */
	aligned_addr = ((uintptr_t)thp_map + thp_size - 1) &
		       ~((uintptr_t)thp_size - 1);
	thp_buf = (unsigned char *)aligned_addr;
	if (madvise(thp_buf, thp_size, MADV_HUGEPAGE)) {
		perror("madvise(MADV_HUGEPAGE)");
		munmap(thp_map, map_size);
		return -1;
	}
	memset(thp_buf, 0, thp_size);
	/* MADV_HUGEPAGE is only a hint; collapse now so the following direct-I/O
	 * BIOs are guaranteed to carry pages from an actual compound folio.
	 */
	if (madvise(thp_buf, thp_size, MADV_COLLAPSE)) {
		perror("madvise(MADV_COLLAPSE)");
		munmap(thp_map, map_size);
		return -1;
	}

	for (i = 0; i < count; ++i) {
		unsigned char *page_ptr = thp_buf + ((size_t)(i % 512U) * PAGE);

		pattern(expected, i, round);
		if (write_data) {
			memcpy(page_ptr, expected, PAGE);
			if (transfer(fd, page_ptr, i, 1)) {
				munmap(thp_map, map_size);
				return -1;
			}
		} else {
			if (transfer(fd, page_ptr, i, 0) ||
			    memcmp(page_ptr, expected, PAGE)) {
				fprintf(stderr,
					"FAIL byte-exact THP page=%u round=%u\n",
					i, round);
				munmap(thp_map, map_size);
				return -1;
			}
		}
	}
	munmap(thp_map, map_size);
	return 0;
}

static int series_segmented(int fd, unsigned char *buf, unsigned char *expected,
			    unsigned int count, unsigned int round,
			    int write_data)
{
	unsigned int i;

	for (i = 0; i < count; ++i) {
		unsigned int mode = i % 5U;

		pattern(expected, i, round);
		if (write_data) {
			if (mode == 4) {
				memcpy(buf + 512, expected, 3584);
				memcpy(buf + 4096, expected + 3584, 512);
				if (transfer_segmented(fd, buf, i, 1))
					return -1;
			} else {
				if (transfer_segmented(fd, expected, i, 1))
					return -1;
			}
		} else {
			if (transfer_segmented(fd, buf, i, 0))
				return -1;
			if (mode == 4) {
				if (memcmp(buf + 512, expected, 3584) ||
				    memcmp(buf + 4096, expected + 3584, 512)) {
					fprintf(stderr,
						"FAIL byte-exact segmented page=%u round=%u\n",
						i, round);
					return -1;
				}
			} else if (memcmp(buf, expected, PAGE)) {
				fprintf(stderr,
					"FAIL byte-exact segmented page=%u round=%u\n",
					i, round);
				return -1;
			}
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

/*
 * Exact full-destination GC recovery boundary on a 5MiB owned null_blk.
 * Three foreground segments are filled with RAW pages. Closed segments 0 and 1
 * retain exactly 255 authoritative survivors each; open segment 2 is forbidden
 * as a victim. The mapper injects lower WRITE #769, which is therefore the
 * first GC relocation write.
 */
static int gc_roll_forward_fault_recovery(int fd, unsigned char *buf,
					  unsigned char *expected)
{
	const unsigned int hot_page = GC_RECOVERY_LOGICAL_PAGES - 1U;
	const unsigned int last_cold_page = hot_page - 1U;
	const unsigned int trigger_round = 257U;
	unsigned int page, round, retry_attempts = 0, foreground_writes = 0;
	ssize_t count;

	for (page = 0; page < 255U; ++page) {
		raw_pattern(buf, page, 0U);
		if (transfer(fd, buf, page, 1))
			return -1;
		foreground_writes++;
	}
	raw_pattern(buf, hot_page, 0U);
	if (transfer(fd, buf, hot_page, 1))
		return -1;
	foreground_writes++;

	for (page = 255U; page < 510U; ++page) {
		raw_pattern(buf, page, 0U);
		if (transfer(fd, buf, page, 1))
			return -1;
		foreground_writes++;
	}
	raw_pattern(buf, hot_page, 1U);
	if (transfer(fd, buf, hot_page, 1))
		return -1;
	foreground_writes++;

	raw_pattern(buf, last_cold_page, 0U);
	if (transfer(fd, buf, last_cold_page, 1))
		return -1;
	foreground_writes++;
	for (round = 2U; round <= 256U; ++round) {
		raw_pattern(buf, hot_page, round);
		if (transfer(fd, buf, hot_page, 1))
			return -1;
		foreground_writes++;
	}
	if (foreground_writes != GC_RECOVERY_FOREGROUND_WRITES) {
		fprintf(stderr,
			"FAIL GC recovery setup writes=%u expected=%u\n",
			foreground_writes, GC_RECOVERY_FOREGROUND_WRITES);
		return -1;
	}

	raw_pattern(buf, hot_page, trigger_round);
	do {
		errno = 0;
		count = pwrite(fd, buf, PAGE, (off_t)hot_page * PAGE);
	} while (count == -1 && errno == EINTR);
	if (count != -1 || errno != EIO) {
		fprintf(stderr,
			"FAIL GC recovery trigger expected EIO n=%zd errno=%d\n",
			count, errno);
		return -1;
	}

	for (retry_attempts = 1U; retry_attempts <= 3U; ++retry_attempts) {
		do {
			errno = 0;
			count = pwrite(fd, buf, PAGE, (off_t)hot_page * PAGE);
		} while (count == -1 && errno == EINTR);
		if (count == PAGE)
			break;
		if (count == -1 && errno == ENOSPC)
			continue;
		fprintf(stderr,
			"FAIL GC recovery retry=%u n=%zd errno=%d\n",
			retry_attempts, count, errno);
		return -1;
	}
	if (count != PAGE) {
		fprintf(stderr, "FAIL GC recovery did not regain foreground progress\n");
		return -1;
	}
	if (fsync(fd)) {
		perror("FAIL GC recovery fsync");
		return -1;
	}

	for (page = 0; page < hot_page; ++page) {
		raw_pattern(expected, page, 0U);
		if (transfer(fd, buf, page, 0) || memcmp(buf, expected, PAGE)) {
			fprintf(stderr,
				"FAIL GC recovery byte-exact cold page=%u\n", page);
			return -1;
		}
	}
	raw_pattern(expected, hot_page, trigger_round);
	if (transfer(fd, buf, hot_page, 0) || memcmp(buf, expected, PAGE)) {
		fprintf(stderr, "FAIL GC recovery byte-exact hot page\n");
		return -1;
	}

	printf("GC_ROLL_FORWARD_FAULT_ORACLE=foreground_writes:%u "
	       "fault_write:%u retry_attempts:%u verified_pages:%u\n",
	       foreground_writes, GC_RECOVERY_FAULT_WRITE,
	       retry_attempts, GC_RECOVERY_LOGICAL_PAGES);
	return 0;
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

static void churn_medium_pattern(unsigned char *p, unsigned int page,
				 unsigned int gen)
{
	uint32_t s = 0x51a0a931U ^ (page * 2654435761U) ^
		     (gen * 2246822519U);
	unsigned int i;

	memset(p, 0, PAGE);
	for (i = 0; i < 2040; ++i) {
		s ^= s << 13;
		s ^= s >> 17;
		s ^= s << 5;
		p[i] = (unsigned char)(s >> 8);
	}
	p[PAGE - 8] = (unsigned char)page;
	p[PAGE - 7] = (unsigned char)(page >> 8);
	p[PAGE - 6] = (unsigned char)gen;
	p[PAGE - 5] = (unsigned char)(gen >> 8);
}

static void init_hot_permutation(unsigned int *perm, unsigned int n,
				 uint32_t *rng)
{
	unsigned int i, j, tmp;

	for (i = 0; i < n; ++i)
		perm[i] = i;
	for (i = n - 1; i > 0; --i) {
		*rng = *rng * 1664525U + 1013904223U;
		j = (unsigned int)(((uint64_t)(*rng >> 16) * (i + 1)) >> 16);
		if (j > i)
			j = i;
		tmp = perm[i];
		perm[i] = perm[j];
		perm[j] = tmp;
	}
}

static int id72_churn_stress(int fd, unsigned char *buf, unsigned char *expected)
{
	uint64_t *latencies = NULL;
	unsigned int *hot_gen = NULL;
	unsigned int *perm = NULL;
	uint32_t rng = 0x51a0a931U;
	uint64_t total_write_wall_ns = 0, start_wall, end_wall;
	uint64_t flush_wall_ns = 0, f_start;
	unsigned int page, write_idx, perm_pos = 0;
	int result = -1;

	latencies = calloc(CHURN_HOT_WRITES, sizeof(*latencies));
	hot_gen = calloc(CHURN_HOT_PAGES, sizeof(*hot_gen));
	perm = calloc(CHURN_HOT_PAGES, sizeof(*perm));
	if (!latencies || !hot_gen || !perm)
		goto out;

	/* 1. Seed phase: exactly 2,867 of 4,096 logical pages (70.0% occupancy) */
	for (page = 0; page < CHURN_SEED_PAGES; ++page) {
		churn_medium_pattern(expected, page, 0);
		if (transfer(fd, expected, page, 1))
			goto out;
	}
	if (fsync(fd))
		goto out;

	/* 2. Hot-page write phase: 40,960 deterministic writes across the 573 hot pages */
	init_hot_permutation(perm, CHURN_HOT_PAGES, &rng);
	perm_pos = 0;

	start_wall = monotonic_ns();
	for (write_idx = 0; write_idx < CHURN_HOT_WRITES; ++write_idx) {
		uint64_t t0, t1;
		unsigned int hot_idx = perm[perm_pos++];
		unsigned int target_page = CHURN_COLD_PAGES + hot_idx;

		if (perm_pos >= CHURN_HOT_PAGES) {
			init_hot_permutation(perm, CHURN_HOT_PAGES, &rng);
			perm_pos = 0;
		}

		hot_gen[hot_idx]++;
		churn_medium_pattern(expected, target_page, hot_gen[hot_idx]);

		t0 = monotonic_ns();
		if (transfer(fd, expected, target_page, 1))
			goto out;
		t1 = monotonic_ns();
		latencies[write_idx] = elapsed_ns(t0, t1);
		total_write_wall_ns += latencies[write_idx];

		if ((write_idx + 1) % CHURN_FSYNC_INTERVAL == 0) {
			f_start = monotonic_ns();
			if (fsync(fd))
				goto out;
			flush_wall_ns += elapsed_ns(f_start, monotonic_ns());
		}
	}
	f_start = monotonic_ns();
	if (fsync(fd))
		goto out;
	flush_wall_ns += elapsed_ns(f_start, monotonic_ns());
	end_wall = monotonic_ns();

	/* 3. Verification: verify every seeded cold page and the final generation of every hot page byte-for-byte */
	for (page = 0; page < CHURN_COLD_PAGES; ++page) {
		churn_medium_pattern(expected, page, 0);
		if (transfer(fd, buf, page, 0) ||
		    memcmp(buf, expected, PAGE)) {
			fprintf(stderr, "FAIL ID72 churn byte-exact cold page=%u\n", page);
			goto out;
		}
	}
	for (page = CHURN_COLD_PAGES; page < CHURN_SEED_PAGES; ++page) {
		unsigned int hot_idx = page - CHURN_COLD_PAGES;
		churn_medium_pattern(expected, page, hot_gen[hot_idx]);
		if (transfer(fd, buf, page, 0) ||
		    memcmp(buf, expected, PAGE)) {
			fprintf(stderr, "FAIL ID72 churn byte-exact hot page=%u gen=%u\n",
				page, hot_gen[hot_idx]);
			goto out;
		}
	}

	{
		uint64_t total_elapsed_ns = elapsed_ns(start_wall, end_wall);
		double total_mb = ((double)CHURN_HOT_WRITES * PAGE) / (1024.0 * 1024.0);
		double throughput_mbps = total_elapsed_ns > 0 ?
			(total_mb / ((double)total_elapsed_ns / 1e9)) : 0.0;
		uint64_t p99 = p99_ns(latencies, CHURN_HOT_WRITES);

		printf("ID72_CHURN_EVIDENCE writes:%u write_wall_ns:%" PRIu64
		       " total_wall_ns:%" PRIu64 " flush_wall_ns:%" PRIu64
		       " useful_write_mbps:%.3f write_p99_ns:%" PRIu64
		       " verified_cold:%u verified_hot:%u\n",
		       CHURN_HOT_WRITES, total_write_wall_ns, total_elapsed_ns,
		       flush_wall_ns, throughput_mbps, p99,
		       CHURN_COLD_PAGES, CHURN_HOT_PAGES);
		fflush(stdout);
	}

	result = 0;
out:
	free(latencies);
	free(hot_gen);
	free(perm);
	return result;
}

int main(int argc, char **argv)
{
	const char *prefix = "/dev/mapper/swapz-demo-";
	const char *expected_dm_uuid = NULL;
	dev_t opened_mapper_device = 0;
	unsigned char *buf = NULL, *expected = NULL;
	int fd = -1, rc = 1, private_mode = 0, write_series = 0;
	int raw_series = 0, discard_pages = 0, gc_mode = 0, churn_mode = 0;
	int gc_roll_forward_fault_mode = 0;
	int segmented_series_mode = 0, thp_series_mode = 0;
	int parallel_series_mode = 0;
	unsigned int i, phase, count = 0, round = 0, gc_rounds = 0;
	int maximum_capacity_mode = 0;
	uint64_t expected_device_bytes = UINT64_C(16) * 1024 * 1024;
	int open_flags = O_RDWR | O_CLOEXEC | O_DIRECT | O_SYNC | O_NOFOLLOW;

	if (argc != 2 && argc != 3 && argc != 5 && argc != 4) {
		fprintf(stderr,
		"Usage: device-roundtrip /dev/mapper/swapz-demo-<owned-id> "
		"[private series mode | --maximum-capacity-boundary SWAPZ-TEST-<owned-id> "
		"| --gc-roll-forward-fault SWAPZ-TEST-<owned-id>]\n");
		return 2;
	}
	if (strncmp(argv[1], prefix, strlen(prefix)) ||
	    strlen(argv[1]) <= strlen(prefix)) {
		fprintf(stderr, "FAIL refusing non-owned mapper path\n");
		return 2;
	}
	if (argc == 3) {
		if (!strcmp(argv[2], "--id72-churn")) {
			churn_mode = 1;
			open_flags &= ~O_SYNC;
		} else {
			fprintf(stderr, "FAIL invalid private mode\n");
			return 2;
		}
	}
	if (argc == 4) {
		if (!strcmp(argv[2], "--expect-dm-uuid")) {
			if (!valid_physical_dm_uuid(argv[3])) {
				fprintf(stderr, "FAIL invalid physical DM UUID\n");
				return 2;
			}
			expected_dm_uuid = argv[3];
		} else if (!strcmp(argv[2], "--maximum-capacity-boundary")) {
			if (!valid_owned_dm_uuid(argv[3])) {
				fprintf(stderr, "FAIL invalid owned maximum-capacity DM UUID\n");
				return 2;
			}
			maximum_capacity_mode = 1;
			expected_dm_uuid = argv[3];
			expected_device_bytes =
				(uint64_t)MAX_CAPACITY_LOGICAL_PAGES * PAGE;
		} else if (!strcmp(argv[2], "--gc-roll-forward-fault")) {
			if (!valid_owned_dm_uuid(argv[3])) {
				fprintf(stderr, "FAIL invalid owned GC-recovery DM UUID\n");
				return 2;
			}
			gc_roll_forward_fault_mode = 1;
			expected_dm_uuid = argv[3];
			expected_device_bytes =
				(uint64_t)GC_RECOVERY_LOGICAL_PAGES * PAGE;
			open_flags &= ~O_SYNC;
		} else {
			if (strcmp(argv[2], "--gc-stress") ||
			    parse_uint(argv[3], 8U, &gc_rounds) ||
			    gc_rounds < 4U) {
				fprintf(stderr, "FAIL invalid private GC mode\n");
				return 2;
			}
			gc_mode = 1;
			open_flags &= ~O_SYNC;
		}
	}
	if (argc == 5) {
		if (!strcmp(argv[2], "--write-series"))
			write_series = 1;
		else if (!strcmp(argv[2], "--parallel-write-series")) {
			write_series = 1;
			parallel_series_mode = 1;
		}
		else if (!strcmp(argv[2], "--raw-write-series")) {
			write_series = 1;
			raw_series = 1;
		} else if (!strcmp(argv[2], "--raw-verify-series")) {
			raw_series = 1;
		} else if (!strcmp(argv[2], "--delta64-write-series")) {
			write_series = 1;
			raw_series = 2;
		} else if (!strcmp(argv[2], "--delta64-verify-series")) {
			raw_series = 2;
		} else if (!strcmp(argv[2], "--segmented-write-series")) {
			write_series = 1;
			segmented_series_mode = 1;
		} else if (!strcmp(argv[2], "--segmented-verify-series")) {
			segmented_series_mode = 1;
		} else if (!strcmp(argv[2], "--thp-write-series")) {
			write_series = 1;
			thp_series_mode = 1;
		} else if (!strcmp(argv[2], "--thp-verify-series")) {
			thp_series_mode = 1;
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
	if (posix_memalign((void **)&buf, PAGE, PAGE * 2) ||
	    posix_memalign((void **)&expected, PAGE, PAGE * 2)) {
		fprintf(stderr, "FAIL allocating aligned test buffers\n");
		goto out;
	}
	fd = open(argv[1], open_flags);
	if (fd < 0 && errno == ELOOP)
		fd = open(argv[1], open_flags & ~O_NOFOLLOW);
	if (validate_owned_device(fd, &opened_mapper_device,
				  expected_device_bytes)) {
		fprintf(stderr, "FAIL opened owned DM block target has unexpected size\n");
		goto out;
	}
	if (expected_dm_uuid &&
	    ((maximum_capacity_mode || gc_roll_forward_fault_mode) ?
	     verify_dm_uuid_exact(opened_mapper_device, expected_dm_uuid) :
	     verify_physical_dm_uuid(opened_mapper_device, expected_dm_uuid))) {
		fprintf(stderr, "FAIL opened DM UUID missing or not the expected identity\n");
		goto out;
	}
	if (maximum_capacity_mode) {
		if (maximum_capacity_boundary_roundtrip(fd, buf, expected))
			goto out;
		printf("PASS: maximum-capacity boundary byte-exact pages=2 highest_page=%u\n",
		       MAX_CAPACITY_LOGICAL_PAGES - 1U);
		rc = 0;
		goto out;
	}
	if (gc_roll_forward_fault_mode) {
		if (gc_roll_forward_fault_recovery(fd, buf, expected))
			goto out;
		puts("PASS: owned swapz full-destination GC roll-forward recovery");
		rc = 0;
		goto out;
	}

	if (churn_mode) {
		if (id72_churn_stress(fd, buf, expected))
			goto out;
		printf("PASS: owned swapz ID72 70%% churn writes=%u pages=%u\n",
		       CHURN_HOT_WRITES, CHURN_SEED_PAGES);
		rc = 0;
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
		} else if (parallel_series_mode) {
			if (parallel_series(fd, count, round))
				goto out;
			printf("PASS: owned swapz parallel series pages=%u round=%u\n",
			       count, round);
		} else if (segmented_series_mode) {
			if (series_segmented(fd, buf, expected, count, round,
					     write_series))
				goto out;
			printf("PASS: owned swapz direct segmented %s series count=%u round=%u\n",
			       write_series ? "write" : "verify", count, round);
		} else if (thp_series_mode) {
			if (series_thp(fd, expected, count, round, write_series))
				goto out;
			printf("PASS: owned swapz direct THP compound-folio %s series count=%u round=%u\n",
			       write_series ? "write" : "verify", count, round);
		} else {
			if (series(fd, buf, expected, count, round,
				   write_series, raw_series))
				goto out;
			printf("PASS: owned swapz direct %s%s series count=%u round=%u\n",
			       raw_series == 2 ? "delta64-" :
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
