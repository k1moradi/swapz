// SPDX-License-Identifier: GPL-2.0-only
/* Small byte-exact smoke oracle for a freshly owned swapz3 DM test mapping.
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

enum { PAGE = 4096, NPAGES = 128 };
static void pattern(unsigned char *p, unsigned int page, unsigned int round)
{
	uint32_t s = 0x71f12345U ^ (page * 1640531527U) ^ (round * 2246822519U);
	unsigned int i;
	memset(p, 0, PAGE);
	/* Exercise successful replacement of a previously nonzero mapping
	 * with the exact all-zero page, including O_SYNC/FUA semantics.
	 * The phase-two readback uses this very same deterministic oracle. */
	if (round == 1 && page % 16U == 0)
		return;
	switch (page % 4U) {
	case 0: /* fully sparse */
		break;
	case 1: /* approximately 2KiB incompressible + 2KiB sparse */
		for (i = 0; i < PAGE / 2; i++) {
			s ^= s << 13;
			s ^= s >> 17;
			s ^= s << 5;
			p[i] = (unsigned char)s;
		}
		break;
	case 2: /* RAW fallback; high entropy */
		for (i = 0; i < PAGE; i++) {
			s ^= s << 13;
			s ^= s >> 17;
			s ^= s << 5;
			p[i] = (unsigned char)s;
		}
		break;
	default: /* structured strings */
		for (i = 0; i < PAGE; i++)
			p[i] = (unsigned char)("object=swapz;field=value\n"[i % 24U]);
	}
	/* Every class changes on overwrite; check authority, not just zeros. */
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
int main(int argc, char **argv)
{
	const char *prefix = "/dev/mapper/swapz-demo-";
	unsigned char *buf = NULL, *expected = NULL;
	struct stat st;
	uint64_t size = 0;
	int fd = -1, rc = 1;
	unsigned int i, phase;
	if (argc != 2 || strncmp(argv[1], prefix, strlen(prefix)) ||
	    strlen(argv[1]) <= strlen(prefix)) {
		fprintf(stderr, "Usage: device-roundtrip /dev/mapper/swapz-demo-<owned-id>\n");
		return 2;
	}
	if (posix_memalign((void **)&buf, PAGE, PAGE) ||
	    posix_memalign((void **)&expected, PAGE, PAGE)) {
		fprintf(stderr, "FAIL allocating aligned test buffers\n");
		goto out;
	}
	fd = open(argv[1], O_RDWR | O_CLOEXEC | O_DIRECT | O_SYNC | O_NOFOLLOW);
	/* /dev/mapper/ entries are normally symlinks: allow only that link,
	 * after the calling harness validates its dedicated UUID and lower. */
	if (fd < 0 && errno == ELOOP)
		fd = open(argv[1], O_RDWR | O_CLOEXEC | O_DIRECT | O_SYNC);
	if (fd < 0 || fstat(fd, &st) || !S_ISBLK(st.st_mode) ||
	    ioctl(fd, BLKGETSIZE64, &size) || size != UINT64_C(16) * 1024 * 1024) {
		fprintf(stderr, "FAIL expected owned 16MiB DM block target\n");
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
				fprintf(stderr, "FAIL byte-exact page=%u pass=%u\n", i, phase);
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
