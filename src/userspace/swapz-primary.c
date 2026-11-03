// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#include "swapz-primary.h"

#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/fs.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#include "../kernel/superblock.h"

#define SWAPZ_PRIMARY_BLOCK_BYTES 4096ULL
#define SWAPZ_PRIMARY_SEGMENT_BLOCKS 256ULL
#define SWAPZ_PRIMARY_MIN_RESERVE_BLOCKS 512ULL
#define SWAPZ_PRIMARY_DEVICE_BYTES 17179869184ULL
#define SWAPZ_PRIMARY_SWAP_SIZE_KIB 16777212ULL
#define SWAPZ_PRIMARY_DEVICE_PATH "/dev/sda4"
#define SWAPZ_PRIMARY_UUID_PATH \
	"/dev/disk/by-uuid/728b4c06-44b0-46ee-91ec-560ab1bad358"
#define SWAPZ_PRIMARY_PARTUUID_PATH "/dev/disk/by-partuuid/7fb9401d-04"
#define SWAPZ_PRIMARY_ORIGINAL_HEADER_SHA256 \
	"ace016a7a3ecd22b0aca05946a305aef2113bc50439452756ae68909010f0afe"
#define SWAPZ_PRIMARY_PLAN_BUFFER_BYTES 16384U
#define SWAPZ_PRIMARY_SWAP_ROWS_MAX 32U
#define SWAPZ_PRIMARY_RECOVERY_BASE "/var/lib/swapz/physical-recovery"
#define SWAPZ_PRIMARY_PARTUUID "7fb9401d-04"
#define SWAPZ_PRIMARY_PHYSICAL_BLOCKS \
	(((SWAPZ_PRIMARY_DEVICE_BYTES / SWAPZ_PRIMARY_BLOCK_BYTES - 1ULL) / \
	  SWAPZ_PRIMARY_SEGMENT_BLOCKS) * SWAPZ_PRIMARY_SEGMENT_BLOCKS)

/* Privileged lifecycle stays disabled until provisioning and recovery qualify. */
#define SWAPZ_PRIMARY_EXECUTION_ENABLED 0

struct swapz_primary_swap_entry {
	char path[PATH_MAX];
	char type[32];
	uint64_t size_kib;
	uint64_t used_kib;
	int priority;
};

static int swapz_primary_device_number_matches(dev_t device)
{
	return major(device) == 8U && minor(device) == 4U;
}

static int swapz_primary_original_swap_signature(
	const unsigned char block[SWAPZ_PRIMARY_BLOCK_BYTES])
{
	static const unsigned char magic[] = "SWAPSPACE2";

	return !swapz_sb_valid(block, SWAPZ_PRIMARY_DEVICE_BYTES) &&
	       !memcmp(block + SWAPZ_PRIMARY_BLOCK_BYTES - sizeof(magic) + 1U,
		       magic, sizeof(magic) - 1U);
}

static int swapz_primary_exact_read(int fd, unsigned char *buffer,
				    size_t length)
{
	size_t completed = 0;

	while (completed < length) {
		ssize_t count = pread(fd, buffer + completed,
				      length - completed, (off_t)completed);

		if (count < 0 && errno == EINTR)
			continue;
		if (count <= 0) {
			if (!count)
				errno = EIO;
			return -1;
		}
		completed += (size_t)count;
	}
	return 0;
}

static int swapz_primary_sha256(const unsigned char *bytes, size_t length,
				char digest[65])
{
	char descriptor_path[64];
	char output_buffer[128];
	size_t output_length = 0;
	int output_pipe[2];
	int memory_fd;
	int descriptor_flags;
	pid_t child;
	int status;

	if (!bytes || !digest) {
		errno = EINVAL;
		return -1;
	}
	memory_fd = memfd_create("swapz-primary-digest", MFD_CLOEXEC);
	if (memory_fd < 0)
		return -1;
	{
		size_t written = 0;

		while (written < length) {
			ssize_t count = write(memory_fd, bytes + written,
					      length - written);

			if (count < 0 && errno == EINTR)
				continue;
			if (count <= 0) {
				int saved_errno = count < 0 ? errno : EIO;

				close(memory_fd);
				errno = saved_errno;
				return -1;
			}
			written += (size_t)count;
		}
	}
	if (lseek(memory_fd, 0, SEEK_SET) < 0 ||
	    pipe2(output_pipe, O_CLOEXEC) < 0) {
		int saved_errno = errno;

		close(memory_fd);
		errno = saved_errno;
		return -1;
	}
	descriptor_flags = fcntl(memory_fd, F_GETFD);
	if (descriptor_flags < 0 ||
	    fcntl(memory_fd, F_SETFD, descriptor_flags & ~FD_CLOEXEC) < 0 ||
	    snprintf(descriptor_path, sizeof(descriptor_path),
		     "/proc/self/fd/%d", memory_fd) < 0) {
		int saved_errno = errno ? errno : EIO;

		close(output_pipe[0]);
		close(output_pipe[1]);
		close(memory_fd);
		errno = saved_errno;
		return -1;
	}
	child = fork();
	if (child < 0) {
		int saved_errno = errno;

		close(output_pipe[0]);
		close(output_pipe[1]);
		close(memory_fd);
		errno = saved_errno;
		return -1;
	}
	if (child == 0) {
		if (dup2(output_pipe[1], STDOUT_FILENO) < 0)
			_exit(127);
		close(output_pipe[0]);
		close(output_pipe[1]);
		execl("/usr/bin/sha256sum", "sha256sum", descriptor_path,
		      (char *)NULL);
		_exit(127);
	}
	close(output_pipe[1]);
	close(memory_fd);
	while (output_length + 1U < sizeof(output_buffer)) {
		ssize_t count = read(output_pipe[0], output_buffer + output_length,
				     sizeof(output_buffer) - output_length - 1U);

		if (count < 0 && errno == EINTR)
			continue;
		if (count < 0) {
			int saved_errno = errno;

			close(output_pipe[0]);
			while (waitpid(child, &status, 0) < 0 && errno == EINTR)
				;
			errno = saved_errno;
			return -1;
		}
		if (!count)
			break;
		output_length += (size_t)count;
	}
	close(output_pipe[0]);
	while (waitpid(child, &status, 0) < 0) {
		if (errno == EINTR)
			continue;
		return -1;
	}
	if (!WIFEXITED(status) || WEXITSTATUS(status) != 0 ||
	    output_length < 66U || output_buffer[64] != ' ' ||
	    output_buffer[65] != ' ') {
		errno = EIO;
		return -1;
	}
	for (output_length = 0; output_length < 64U; ++output_length) {
		char value = output_buffer[output_length];

		if (!((value >= '0' && value <= '9') ||
		      (value >= 'a' && value <= 'f'))) {
			errno = EINVAL;
			return -1;
		}
		digest[output_length] = value;
	}
	digest[64] = '\0';
	return 0;
}

static int swapz_primary_target_preflight(uint64_t *device_bytes,
						 int *original_swap_header,
						 int *original_header_hash_matches)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)device_bytes;
	(void)original_swap_header;
	(void)original_header_hash_matches;
	errno = ENODEV;
	return -1;
#else
	struct stat uuid_info;
	struct stat partuuid_info;
	struct stat device_info;
	struct stat opened_info;
	unsigned char block[SWAPZ_PRIMARY_BLOCK_BYTES];
	char digest[65];
	int fd;

	if (!device_bytes || !original_swap_header ||
	    !original_header_hash_matches) {
		errno = EINVAL;
		return -1;
	}
	*original_swap_header = 0;
	*original_header_hash_matches = 0;
	if (stat(SWAPZ_PRIMARY_UUID_PATH, &uuid_info) < 0 ||
	    stat(SWAPZ_PRIMARY_PARTUUID_PATH, &partuuid_info) < 0 ||
	    stat(SWAPZ_PRIMARY_DEVICE_PATH, &device_info) < 0)
		return -1;
	if (!S_ISBLK(uuid_info.st_mode) || !S_ISBLK(partuuid_info.st_mode) ||
	    !S_ISBLK(device_info.st_mode) ||
	    !swapz_primary_device_number_matches(uuid_info.st_rdev) ||
	    uuid_info.st_rdev != partuuid_info.st_rdev ||
	    uuid_info.st_rdev != device_info.st_rdev) {
		errno = ENODEV;
		return -1;
	}
	fd = open(SWAPZ_PRIMARY_UUID_PATH, O_RDONLY | O_CLOEXEC);
	if (fd < 0)
		return -1;
	if (fstat(fd, &opened_info) < 0) {
		int saved_errno = errno;

		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (!S_ISBLK(opened_info.st_mode) ||
	    opened_info.st_rdev != uuid_info.st_rdev ||
	    !swapz_primary_device_number_matches(opened_info.st_rdev)) {
		close(fd);
		errno = ENODEV;
		return -1;
	}
	if (ioctl(fd, BLKGETSIZE64, device_bytes) < 0) {
		int saved_errno = errno;

		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (*device_bytes != SWAPZ_PRIMARY_DEVICE_BYTES) {
		close(fd);
		errno = EINVAL;
		return -1;
	}
	if (swapz_primary_exact_read(fd, block, sizeof(block)) < 0) {
		int saved_errno = errno;

		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (close(fd) < 0)
		return -1;
	*original_swap_header = swapz_primary_original_swap_signature(block);
	if (*original_swap_header &&
	    swapz_primary_sha256(block, sizeof(block), digest) == 0)
		*original_header_hash_matches =
			!strcmp(digest, SWAPZ_PRIMARY_ORIGINAL_HEADER_SHA256);
	return 0;
#endif
}

static int swapz_primary_parse_u64(const char *text, uint64_t *value)
{
	uint64_t parsed = 0;
	const unsigned char *cursor = (const unsigned char *)text;

	if (!text || !*text || !value)
		return -1;
	while (*cursor) {
		unsigned int digit;

		if (*cursor < '0' || *cursor > '9')
			return -1;
		digit = (unsigned int)(*cursor - '0');
		if (parsed > (UINT64_MAX - digit) / 10U)
			return -1;
		parsed = parsed * 10U + digit;
		++cursor;
	}
	*value = parsed;
	return 0;
}

static int swapz_primary_parse_priority(const char *text, int *priority)
{
	uint64_t magnitude;
	int negative = 0;

	if (!text || !*text || !priority)
		return -1;
	if (*text == '-') {
		negative = 1;
		++text;
	}
	if (swapz_primary_parse_u64(text, &magnitude) < 0 ||
	    magnitude > (uint64_t)INT_MAX + (unsigned int)negative)
		return -1;
	if (negative && magnitude == (uint64_t)INT_MAX + 1U)
		*priority = INT_MIN;
	else
		*priority = negative ? -(int)magnitude : (int)magnitude;
	return 0;
}

static int swapz_primary_split_fields(char *line, char **fields,
				      size_t field_capacity, size_t *field_count)
{
	char *cursor = line;
	size_t count = 0;

	while (*cursor) {
		while (*cursor && isspace((unsigned char)*cursor))
			++cursor;
		if (!*cursor)
			break;
		if (count == field_capacity)
			return -1;
		fields[count++] = cursor;
		while (*cursor && !isspace((unsigned char)*cursor))
			++cursor;
		if (*cursor)
			*cursor++ = '\0';
	}
	*field_count = count;
	return 0;
}

static int swapz_primary_parse_swaps(const char *text,
				     struct swapz_primary_swap_entry *entries,
				     size_t capacity, size_t *entry_count)
{
	const char *line = text;
	int header_seen = 0;
	size_t count = 0;

	if (!text || !entries || !entry_count || !capacity)
		return -1;
	while (*line) {
		char buffer[PATH_MAX + 128U];
		char *fields[6];
		const char *end = strchr(line, '\n');
		size_t length = end ? (size_t)(end - line) : strlen(line);
		size_t field_count = 0;

		if (length >= sizeof(buffer))
			return -1;
		memcpy(buffer, line, length);
		buffer[length] = '\0';
		line = end ? end + 1 : line + length;
		if (!buffer[0])
			continue;
		if (swapz_primary_split_fields(buffer, fields,
					      sizeof(fields) / sizeof(fields[0]),
					      &field_count) < 0)
			return -1;
		if (!header_seen) {
			if (field_count != 5U || strcmp(fields[0], "Filename") ||
			    strcmp(fields[1], "Type") || strcmp(fields[2], "Size") ||
			    strcmp(fields[3], "Used") || strcmp(fields[4], "Priority"))
				return -1;
			header_seen = 1;
			continue;
		}
		if (field_count != 5U || count == capacity ||
		    strlen(fields[0]) >= sizeof(entries[count].path) ||
		    strlen(fields[1]) >= sizeof(entries[count].type) ||
		    !fields[0][0] || !fields[1][0] ||
		    swapz_primary_parse_u64(fields[2], &entries[count].size_kib) < 0 ||
		    swapz_primary_parse_u64(fields[3], &entries[count].used_kib) < 0 ||
		    swapz_primary_parse_priority(fields[4],
						&entries[count].priority) < 0)
			return -1;
		strcpy(entries[count].path, fields[0]);
		strcpy(entries[count].type, fields[1]);
		{
			size_t prior;

			for (prior = 0; prior < count; ++prior)
				if (!strcmp(entries[prior].path, entries[count].path))
					return -1;
		}
		++count;
	}
	if (!header_seen)
		return -1;
	*entry_count = count;
	return 0;
}

static int swapz_primary_read_swap_inventory(
	struct swapz_primary_swap_entry *entries, size_t capacity,
	size_t *entry_count)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)entries;
	(void)capacity;
	(void)entry_count;
	errno = ENODEV;
	return -1;
#else
	char buffer[SWAPZ_PRIMARY_PLAN_BUFFER_BYTES];
	size_t used = 0;
	int fd = open("/proc/swaps", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);

	if (fd < 0)
		return -1;
	while (used + 1U < sizeof(buffer)) {
		ssize_t count = read(fd, buffer + used, sizeof(buffer) - used - 1U);

		if (count < 0 && errno == EINTR)
			continue;
		if (count < 0) {
			int saved_errno = errno;

			close(fd);
			errno = saved_errno;
			return -1;
		}
		if (!count)
			break;
		used += (size_t)count;
	}
	if (close(fd) < 0)
		return -1;
	if (used + 1U == sizeof(buffer)) {
		errno = EOVERFLOW;
		return -1;
	}
	buffer[used] = '\0';
	return swapz_primary_parse_swaps(buffer, entries, capacity, entry_count);
#endif
}

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
	struct swapz_primary_swap_entry swaps[SWAPZ_PRIMARY_SWAP_ROWS_MAX];
	struct swapz_primary_swap_entry *target_swap = NULL;
	uint64_t logical_pages = swapz_primary_maximum_logical_pages(
		SWAPZ_PRIMARY_PHYSICAL_BLOCKS);
	uint64_t logical_bytes = logical_pages * SWAPZ_PRIMARY_BLOCK_BYTES;
	uint64_t reserve = (logical_pages + 7ULL) / 8ULL;
	uint64_t target_device_bytes = 0;
	size_t swap_count = 0;
	size_t target_count = 0;
	size_t i;
	int swaps_valid = swapz_primary_read_swap_inventory(
		swaps, SWAPZ_PRIMARY_SWAP_ROWS_MAX, &swap_count) == 0;
	int single_target_swap = 0;
	int target_swap_size_ok = 0;
	int target_swap_zero_used = 0;
	int target_swap_priority_ok = 0;
	int original_swap_header = 0;
	int original_header_hash_matches = 0;
	int target_device_preflight = swapz_primary_target_preflight(
		&target_device_bytes, &original_swap_header,
		&original_header_hash_matches) == 0;

	if (swaps_valid) {
		for (i = 0; i < swap_count; ++i) {
			struct stat info;

			if (stat(swaps[i].path, &info) == 0 && S_ISBLK(info.st_mode) &&
			    major(info.st_rdev) == 8U && minor(info.st_rdev) == 4U) {
				++target_count;
				target_swap = &swaps[i];
			}
		}
		single_target_swap = swap_count == 1U && target_count == 1U;
		if (target_swap) {
			target_swap_size_ok =
				target_swap->size_kib == SWAPZ_PRIMARY_SWAP_SIZE_KIB &&
				!strcmp(target_swap->type, "partition");
			target_swap_zero_used = target_swap->used_kib == 0ULL;
			target_swap_priority_ok = target_swap->priority == -1;
		}
	}

	printf("{\"schema\":\"swapz-primary-plan-v1\","
	       "\"status\":\"BLOCKED\","
	       "\"privileged_execution_enabled\":false,"
	       "\"live_device_gates_checked\":false,"
	       "\"target_device_preflight\":%s,"
	       "\"target_device_bytes\":%llu,"
	       "\"original_swap_signature\":%s,"
	       "\"original_header_hash_matches\":%s,"
	       "\"swap_inventory_read\":%s,"
	       "\"active_swap_entries\":%llu,"
	       "\"target_swap_entries\":%llu,"
	       "\"single_target_swap_active\":%s,"
	       "\"target_swap_size_ok\":%s,"
	       "\"target_swap_zero_used\":%s,"
	       "\"target_swap_priority_ok\":%s,"
	       "\"logical_pages\":%llu,\"logical_bytes\":%llu,"
	       "\"linux_swap_kib\":%llu,\"gc_reserve_blocks\":%llu,"
	       "\"reason\":\"device_identity_recovery_and_lifecycle_gates_not_qualified\"}\n",
	       target_device_preflight ? "true" : "false",
	       (unsigned long long)target_device_bytes,
	       original_swap_header ? "true" : "false",
	       original_header_hash_matches ? "true" : "false",
	       swaps_valid ? "true" : "false",
	       (unsigned long long)swap_count,
	       (unsigned long long)target_count,
	       single_target_swap ? "true" : "false",
	       target_swap_size_ok ? "true" : "false",
	       target_swap_zero_used ? "true" : "false",
	       target_swap_priority_ok ? "true" : "false",
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
