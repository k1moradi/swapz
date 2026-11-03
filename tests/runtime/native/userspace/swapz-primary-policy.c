// SPDX-License-Identifier: GPL-2.0-only
#define main swapzctl_program_main
#include "../../../../src/userspace/swapz-primary.c"
#undef main

#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

int main(void)
{
	uint64_t pages = swapz_primary_maximum_logical_pages(
		SWAPZ_PRIMARY_PHYSICAL_BLOCKS);
	const char *home = getenv("HOME");
	char base_template[PATH_MAX];
	char lock_path[PATH_MAX];
	char target_path[PATH_MAX];
	int recovery_fd;
	int first_lock;
	int second_lock;
	char *plan[] = {"plan"};
	char *prepare[] = {"prepare"};
	char *start[] = {"start"};
	char *stop[] = {"stop"};
	char *recover[] = {"recover"};

	assert(pages == 3727872ULL);
	assert(swapz_primary_page_limit_fits(SWAPZ_PRIMARY_PHYSICAL_BLOCKS,
						 pages));
	assert(!swapz_primary_page_limit_fits(SWAPZ_PRIMARY_PHYSICAL_BLOCKS,
						  pages + 1ULL));
	assert(home && home[0] == '/');
	assert(snprintf(base_template, sizeof(base_template),
			 "%s/.swapz-primary-lock-XXXXXX", home) > 0);
	assert(mkdtemp(base_template));
	assert(snprintf(lock_path, sizeof(lock_path),
			 "%s/partition-7fb9401d-04.lock", base_template) > 0);
	assert(snprintf(target_path, sizeof(target_path),
			 "%s/target", base_template) > 0);
	recovery_fd = swapz_primary_recovery_base_open(
		base_template, geteuid());
	assert(recovery_fd >= 0);
	first_lock = swapz_primary_partition_lock_at(
		recovery_fd, "7fb9401d-04", geteuid());
	assert(first_lock >= 0);
	second_lock = swapz_primary_partition_lock_at(
		recovery_fd, "7fb9401d-04", geteuid());
	assert(second_lock < 0);
	assert(errno == EWOULDBLOCK || errno == EAGAIN);
	assert(close(first_lock) == 0);
	first_lock = swapz_primary_partition_lock_at(
		recovery_fd, "7fb9401d-04", geteuid());
	assert(first_lock >= 0);
	assert(close(first_lock) == 0);
	assert(close(recovery_fd) == 0);
	assert(unlink(lock_path) == 0);
	assert(symlink("target", lock_path) == 0);
	recovery_fd = swapz_primary_recovery_base_open(
		base_template, geteuid());
	assert(recovery_fd >= 0);
	assert(swapz_primary_partition_lock_at(
		recovery_fd, "7fb9401d-04", geteuid()) < 0);
	assert(unlink(lock_path) == 0);
	first_lock = open(target_path, O_WRONLY | O_CREAT | O_EXCL, 0600);
	assert(first_lock >= 0);
	assert(close(first_lock) == 0);
	assert(unlink(target_path) == 0);
	first_lock = openat(recovery_fd, "partition-7fb9401d-04.lock",
			    O_RDWR | O_CREAT | O_EXCL, 0600);
	assert(first_lock >= 0);
	assert(fchmod(first_lock, 0644) == 0);
	assert(close(first_lock) == 0);
	assert(swapz_primary_partition_lock_at(
		recovery_fd, "7fb9401d-04", geteuid()) < 0);
	assert(unlink(lock_path) == 0);
	assert(swapz_primary_partition_lock_at(
		recovery_fd, "../sda4", geteuid()) < 0);
	assert(close(recovery_fd) == 0);
	assert(chmod(base_template, 0755) == 0);
	assert(swapz_primary_recovery_base_open(
		base_template, geteuid()) < 0);
	assert(chmod(base_template, 0700) == 0);
	assert(rmdir(base_template) == 0);
	assert(swapz_primary_command(1, plan) == 2);
	assert(swapz_primary_command(1, prepare) == 2);
	assert(swapz_primary_command(1, start) == 2);
	assert(swapz_primary_command(1, stop) == 2);
	assert(swapz_primary_command(1, recover) == 2);
	puts("PASS: primary swap capacity, shared lock and disabled lifecycle gate");
	return 0;
}
