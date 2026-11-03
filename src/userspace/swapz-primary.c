// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#include "swapz-primary.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define SWAPZ_PRIMARY_BLOCK_BYTES 4096ULL
#define SWAPZ_PRIMARY_SEGMENT_BLOCKS 256ULL
#define SWAPZ_PRIMARY_MIN_RESERVE_BLOCKS 512ULL
#define SWAPZ_PRIMARY_DEVICE_BYTES 17179869184ULL
#define SWAPZ_PRIMARY_RECOVERY_BASE "/var/lib/swapz/physical-recovery"
#define SWAPZ_PRIMARY_PARTUUID "7fb9401d-04"
#define SWAPZ_PRIMARY_PHYSICAL_BLOCKS \
	(((SWAPZ_PRIMARY_DEVICE_BYTES / SWAPZ_PRIMARY_BLOCK_BYTES - 1ULL) / \
	  SWAPZ_PRIMARY_SEGMENT_BLOCKS) * SWAPZ_PRIMARY_SEGMENT_BLOCKS)

/* Privileged lifecycle stays disabled until provisioning and recovery qualify. */
#define SWAPZ_PRIMARY_EXECUTION_ENABLED 0

static int swapz_primary_valid_partuuid(const char *partuuid)
{
	size_t i;

	if (!partuuid || !partuuid[0] || strlen(partuuid) > 36U)
		return 0;
	for (i = 0; partuuid[i]; ++i) {
		unsigned char ch = (unsigned char)partuuid[i];

		if (!((ch >= '0' && ch <= '9') ||
		      (ch >= 'a' && ch <= 'f') ||
		      (ch >= 'A' && ch <= 'F') || ch == '-'))
			return 0;
	}
	return 1;
}

static int swapz_primary_recovery_base_open(const char *path,
						    uid_t expected_owner)
{
	struct stat before;
	struct stat opened;
	char prefix[PATH_MAX];
	const char *component;
	const char *cursor;
	size_t length;
	size_t i;
	int fd;

	if (!path || path[0] != '/') {
		errno = EINVAL;
		return -1;
	}
	component = path + 1;
	for (cursor = component; ; ++cursor) {
		if (*cursor != '/' && *cursor != '\0')
			continue;
		if (cursor == component ||
		    (cursor - component == 1 && component[0] == '.') ||
		    (cursor - component == 2 && component[0] == '.' &&
		     component[1] == '.')) {
			errno = EINVAL;
			return -1;
		}
		if (!*cursor)
			break;
		component = cursor + 1;
	}
	length = strlen(path);
	if (length < 2U || length >= sizeof(prefix) || path[length - 1U] == '/') {
		errno = EINVAL;
		return -1;
	}
	memcpy(prefix, path, length + 1U);
	for (i = 1U; i <= length; ++i) {
		if (prefix[i] != '/' && prefix[i] != '\0')
			continue;
		if (prefix[i] == '/' && prefix[i + 1U] == '\0') {
			errno = EINVAL;
			return -1;
		}
		prefix[i] = '\0';
		if (lstat(prefix, &before) < 0 || !S_ISDIR(before.st_mode) ||
		    (before.st_uid != 0 && before.st_uid != expected_owner) ||
		    (before.st_mode & (S_IWGRP | S_IWOTH))) {
			errno = EPERM;
			return -1;
		}
		if (i < length)
			prefix[i] = '/';
	}
	if (stat(path, &before) < 0 || before.st_uid != expected_owner ||
	    (before.st_mode & 0777U) != 0700U) {
		errno = EPERM;
		return -1;
	}
	fd = open(path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
	if (fd < 0)
		return -1;
	if (fstat(fd, &opened) < 0) {
		int saved_errno = errno;

		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (!S_ISDIR(opened.st_mode) || opened.st_dev != before.st_dev ||
	    opened.st_ino != before.st_ino || opened.st_uid != expected_owner ||
	    (opened.st_mode & 0777U) != 0700U) {
		close(fd);
		errno = EPERM;
		return -1;
	}
	return fd;
}

static int swapz_primary_partition_lock_at(int recovery_fd,
						   const char *partuuid,
						   uid_t expected_owner)
{
	struct stat info;
	char name[64];
	int fd;

	if (recovery_fd < 0 || !swapz_primary_valid_partuuid(partuuid)) {
		errno = EINVAL;
		return -1;
	}
	if (snprintf(name, sizeof(name), "partition-%s.lock", partuuid) < 0 ||
	    strlen(name) >= sizeof(name)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	fd = openat(recovery_fd, name, O_RDWR | O_CREAT | O_NOFOLLOW |
		    O_CLOEXEC, 0600);
	if (fd < 0)
		return -1;
	if (fstat(fd, &info) < 0) {
		int saved_errno = errno;

		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (!S_ISREG(info.st_mode) || info.st_uid != expected_owner ||
	    (info.st_mode & 0777U) != 0600U || info.st_nlink != 1) {
		close(fd);
		errno = EPERM;
		return -1;
	}
	if (flock(fd, LOCK_EX | LOCK_NB) < 0) {
		int saved_errno = errno;

		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (fsync(recovery_fd) < 0) {
		int saved_errno = errno;

		close(fd);
		errno = saved_errno;
		return -1;
	}
	return fd;
}

static int swapz_primary_valid_run_id(const char *run_id)
{
	size_t i;

	if (!run_id || strlen(run_id) != 32U)
		return 0;
	for (i = 0; i < 32U; ++i) {
		if (!((run_id[i] >= '0' && run_id[i] <= '9') ||
		      (run_id[i] >= 'a' && run_id[i] <= 'f')))
			return 0;
	}
	return 1;
}

static int swapz_primary_write_record_at(int recovery_fd, const char *name,
						 const char *record,
						 uid_t expected_owner)
{
	struct stat info;
	const char *cursor = record;
	size_t remaining = strlen(record);
	int fd;
	int saved_errno;

	fd = openat(recovery_fd, name, O_WRONLY | O_CREAT | O_EXCL |
		    O_NOFOLLOW | O_CLOEXEC, 0600);
	if (fd < 0)
		return -1;
	if (fstat(fd, &info) < 0) {
		saved_errno = errno;
		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (!S_ISREG(info.st_mode) || info.st_uid != expected_owner ||
	    (info.st_mode & 0777U) != 0600U || info.st_nlink != 1) {
		close(fd);
		errno = EPERM;
		return -1;
	}
	while (remaining) {
		ssize_t count = write(fd, cursor, remaining);

		if (count < 0 && errno == EINTR)
			continue;
		if (count <= 0) {
			saved_errno = count < 0 ? errno : EIO;
			close(fd);
			errno = saved_errno;
			return -1;
		}
		cursor += count;
		remaining -= (size_t)count;
	}
	if (fsync(fd) < 0) {
		saved_errno = errno;
		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (close(fd) < 0)
		return -1;
	return fsync(recovery_fd);
}

int swapz_primary_claim_partition_owner_at(int recovery_fd, int lock_fd,
						  const char *run_id,
						  uid_t expected_owner)
{
	struct stat directory_info;
	struct stat held_lock_info;
	struct stat named_lock_info;
	struct stat marker_info;
	char lock_name[64];
	char active_name[64];
	char consumed_name[64];
	char record[192];
	int count;

	if (recovery_fd < 0 || lock_fd < 0 ||
	    !swapz_primary_valid_run_id(run_id)) {
		errno = EINVAL;
		return -1;
	}
	if (fstat(recovery_fd, &directory_info) < 0)
		return -1;
	if (!S_ISDIR(directory_info.st_mode) ||
	    directory_info.st_uid != expected_owner ||
	    (directory_info.st_mode & 0777U) != 0700U) {
		errno = EPERM;
		return -1;
	}
	if (snprintf(lock_name, sizeof(lock_name), "partition-%s.lock",
		     SWAPZ_PRIMARY_PARTUUID) < 0 ||
	    snprintf(active_name, sizeof(active_name), "partition-%s.active",
		     SWAPZ_PRIMARY_PARTUUID) < 0 ||
	    snprintf(consumed_name, sizeof(consumed_name), "consumed-%s.json",
		     run_id) < 0) {
		errno = EIO;
		return -1;
	}
	if (fstat(lock_fd, &held_lock_info) < 0 ||
	    fstatat(recovery_fd, lock_name, &named_lock_info,
		    AT_SYMLINK_NOFOLLOW) < 0)
		return -1;
	if (!S_ISREG(held_lock_info.st_mode) ||
	    held_lock_info.st_uid != expected_owner ||
	    (held_lock_info.st_mode & 0777U) != 0600U ||
	    held_lock_info.st_nlink != 1 ||
	    held_lock_info.st_dev != named_lock_info.st_dev ||
	    held_lock_info.st_ino != named_lock_info.st_ino ||
	    !S_ISREG(named_lock_info.st_mode) ||
	    named_lock_info.st_uid != expected_owner ||
	    (named_lock_info.st_mode & 0777U) != 0600U ||
	    named_lock_info.st_nlink != 1) {
		errno = EPERM;
		return -1;
	}
	if (flock(lock_fd, LOCK_EX | LOCK_NB) < 0)
		return -1;
	if (fstatat(recovery_fd, active_name, &marker_info,
		    AT_SYMLINK_NOFOLLOW) == 0) {
		errno = EBUSY;
		return -1;
	}
	if (errno != ENOENT)
		return -1;
	if (fstatat(recovery_fd, consumed_name, &marker_info,
		    AT_SYMLINK_NOFOLLOW) == 0) {
		errno = EEXIST;
		return -1;
	}
	if (errno != ENOENT)
		return -1;
	count = snprintf(record, sizeof(record),
			 "{\"major\":8,\"minor\":4,\"partuuid\":\"%s\","
			 "\"run_id\":\"%s\"}\n",
			 SWAPZ_PRIMARY_PARTUUID, run_id);
	if (count < 0 || (size_t)count >= sizeof(record)) {
		errno = EOVERFLOW;
		return -1;
	}
	if (swapz_primary_write_record_at(recovery_fd, consumed_name,
					  record, expected_owner) < 0)
		return -1;
	return swapz_primary_write_record_at(recovery_fd, active_name,
					     record, expected_owner);
}

int swapz_primary_partition_lock_acquire(void)
{
	uid_t expected_owner = 0;
	int recovery_fd;
	int lock_fd;
	int saved_errno;

	if (geteuid() != expected_owner) {
		errno = EPERM;
		return -1;
	}
	recovery_fd = swapz_primary_recovery_base_open(
		SWAPZ_PRIMARY_RECOVERY_BASE, expected_owner);
	if (recovery_fd < 0)
		return -1;
	lock_fd = swapz_primary_partition_lock_at(
		recovery_fd, SWAPZ_PRIMARY_PARTUUID, expected_owner);
	saved_errno = errno;
	close(recovery_fd);
	errno = saved_errno;
	return lock_fd;
}

static int swapz_primary_page_limit_fits(uint64_t physical_blocks,
					uint64_t logical_pages)
{
	uint64_t reserve;
	uint64_t data_blocks;

	reserve = (logical_pages + 7ULL) / 8ULL;
	if (reserve < SWAPZ_PRIMARY_MIN_RESERVE_BLOCKS)
		reserve = SWAPZ_PRIMARY_MIN_RESERVE_BLOCKS;
	if (reserve >= physical_blocks)
		return 0;
	data_blocks = ((physical_blocks - reserve) /
		       SWAPZ_PRIMARY_SEGMENT_BLOCKS) *
		      SWAPZ_PRIMARY_SEGMENT_BLOCKS;
	return logical_pages <= data_blocks;
}

static uint64_t swapz_primary_maximum_logical_pages(uint64_t physical_blocks)
{
	uint64_t low = 0;
	uint64_t high = physical_blocks;

	while (low < high) {
		uint64_t candidate = low + (high - low + 1ULL) / 2ULL;

		if (swapz_primary_page_limit_fits(physical_blocks, candidate))
			low = candidate;
		else
			high = candidate - 1ULL;
	}
	return low;
}

static int swapz_primary_read_only_plan(void)
{
	uint64_t logical_pages = swapz_primary_maximum_logical_pages(
		SWAPZ_PRIMARY_PHYSICAL_BLOCKS);
	uint64_t logical_bytes = logical_pages * SWAPZ_PRIMARY_BLOCK_BYTES;
	uint64_t reserve = (logical_pages + 7ULL) / 8ULL;

	printf("{\"schema\":\"swapz-primary-plan-v1\","
	       "\"status\":\"BLOCKED\","
	       "\"privileged_execution_enabled\":false,"
	       "\"live_device_gates_checked\":false,"
	       "\"logical_pages\":%llu,\"logical_bytes\":%llu,"
	       "\"linux_swap_kib\":%llu,\"gc_reserve_blocks\":%llu,"
	       "\"reason\":\"provisioning_and_recovery_not_qualified\"}\n",
	       (unsigned long long)logical_pages,
	       (unsigned long long)logical_bytes,
	       (unsigned long long)(logical_bytes / 1024ULL - 4ULL),
	       (unsigned long long)reserve);
	return 2;
}

int swapz_primary_command(int argc, char **argv)
{
	if (argc != 1 || !argv || !argv[0]) {
		fputs("Usage: swapzctl primary plan|prepare|start|stop|recover\n",
		      stderr);
		return 2;
	}
	if (!strcmp(argv[0], "plan"))
		return swapz_primary_read_only_plan();
	if (strcmp(argv[0], "prepare") && strcmp(argv[0], "start") &&
	    strcmp(argv[0], "stop") && strcmp(argv[0], "recover")) {
		fputs("BLOCKED: unsupported primary-swap action\n", stderr);
		return 2;
	}
	if (!SWAPZ_PRIMARY_EXECUTION_ENABLED) {
		fputs("BLOCKED: primary-swap provisioning, activation, teardown and "
		      "recovery remain disabled pending qualification\n", stderr);
		return 2;
	}
	fputs("BLOCKED: primary-swap lifecycle action is not implemented\n", stderr);
	return 2;
}
