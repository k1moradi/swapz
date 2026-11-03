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

static void assert_record_equals(int directory_fd, const char *name,
				 const char *expected)
{
	struct stat info;
	char buffer[192];
	ssize_t count;
	int fd = openat(directory_fd, name, O_RDONLY | O_NOFOLLOW);

	assert(fd >= 0);
	assert(fstat(fd, &info) == 0);
	assert(S_ISREG(info.st_mode));
	assert(info.st_uid == geteuid());
	assert((info.st_mode & 0777U) == 0600U);
	count = read(fd, buffer, sizeof(buffer) - 1U);
	assert(count >= 0);
	buffer[count] = '\0';
	assert(strcmp(buffer, expected) == 0);
	assert(close(fd) == 0);
}

int main(void)
{
	uint64_t pages = swapz_primary_maximum_logical_pages(
		SWAPZ_PRIMARY_PHYSICAL_BLOCKS);
	const char *home = getenv("HOME");
	char base_template[PATH_MAX];
	char lock_path[PATH_MAX];
	char target_path[PATH_MAX];
	char active_name[64];
	char consumed_name[64];
	const char *run_id = "0123456789abcdef0123456789abcdef";
	const char *other_run_id = "fedcba9876543210fedcba9876543210";
	const char *expected_record =
		"{\"major\":8,\"minor\":4,\"partuuid\":\"7fb9401d-04\","
		"\"run_id\":\"0123456789abcdef0123456789abcdef\"}\n";
	int recovery_fd;
	int first_lock;
	int second_lock;
	int unlocked_lock;
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
	assert(snprintf(active_name, sizeof(active_name),
			 "partition-7fb9401d-04.active") > 0);
	assert(snprintf(consumed_name, sizeof(consumed_name),
			 "consumed-%s.json", run_id) > 0);
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
	unlocked_lock = openat(recovery_fd, "partition-7fb9401d-04.lock",
			      O_RDWR | O_NOFOLLOW);
	assert(unlocked_lock >= 0);
	assert(swapz_primary_claim_partition_owner_at(
		recovery_fd, unlocked_lock, run_id, geteuid()) < 0);
	assert(errno == EWOULDBLOCK || errno == EAGAIN);
	assert(close(unlocked_lock) == 0);
	assert(swapz_primary_claim_partition_owner_at(
		recovery_fd, first_lock, "invalid-run-id", geteuid()) < 0);
	assert(errno == EINVAL);
	assert(swapz_primary_claim_partition_owner_at(
		recovery_fd, first_lock, run_id, geteuid()) == 0);
	assert(swapz_primary_claim_partition_owner_at(
		recovery_fd, first_lock, run_id, geteuid()) < 0);
	assert(errno == EBUSY);
	assert(swapz_primary_claim_partition_owner_at(
		recovery_fd, first_lock, other_run_id, geteuid()) < 0);
	assert(errno == EBUSY);
	assert_record_equals(recovery_fd, active_name, expected_record);
	assert_record_equals(recovery_fd, consumed_name, expected_record);
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
	assert(unlinkat(recovery_fd, active_name, 0) == 0);
	assert(unlinkat(recovery_fd, consumed_name, 0) == 0);
	assert(fsync(recovery_fd) == 0);
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
	puts("PASS: primary swap capacity, durable owner claim, shared lock and disabled lifecycle gate");
	return 0;
}
